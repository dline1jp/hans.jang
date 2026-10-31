const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

const US_EXCHANGES = ["NMS", "NYQ", "NAS", "NCM", "NGM"];
const US_MIN_CAP = 1_000_000_000;
const KR_MIN_CAP_USD = 500_000_000;

function cookieFrom(res) {
  if (typeof res.headers.getSetCookie === "function") {
    const list = res.headers.getSetCookie();
    if (list && list.length) return list.map((c) => c.split(";")[0]).join("; ");
  }
  const single = res.headers.get("set-cookie");
  if (!single) return "";
  return single
    .split(/,(?=[^;,]+=)/)
    .map((c) => c.split(";")[0].trim())
    .join("; ");
}

async function yahooSession() {
  const fc = await fetch("https://fc.yahoo.com", {
    headers: { "User-Agent": UA },
    redirect: "manual",
  });
  const cookie = cookieFrom(fc);
  const crumbRes = await fetch("https://query1.finance.yahoo.com/v1/test/getcrumb", {
    headers: { "User-Agent": UA, Cookie: cookie },
  });
  const crumb = (await crumbRes.text()).trim();
  if (!crumb || crumb.startsWith("{") || crumb.includes(" ")) {
    throw new Error("Yahoo crumb failed");
  }
  return { cookie, crumb };
}

async function yahoo(session, url, options) {
  const headers = {
    "User-Agent": UA,
    Cookie: session.cookie,
    ...(options && options.headers),
  };
  const res = await fetch(url, { ...options, headers });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new Error("Yahoo response was not JSON");
  }
  if (!res.ok) {
    const message = data && data.finance && data.finance.error && data.finance.error.description;
    throw new Error(message || "Yahoo request failed");
  }
  return data;
}

function exchangeOr(codes) {
  return {
    operator: "OR",
    operands: codes.map((code) => ({ operator: "EQ", operands: ["exchange", code] })),
  };
}

async function screen(session, { region, direction, minCap, exchanges }) {
  const ops = [
    {
      operator: direction === "down" ? "LT" : "GT",
      operands: ["percentchange", direction === "down" ? -9.5 : 9.5],
    },
    { operator: "EQ", operands: ["region", region] },
    { operator: "GT", operands: ["intradaymarketcap", minCap] },
  ];
  if (exchanges) ops.push(exchangeOr(exchanges));
  const quotes = [];
  let total = 0;
  for (let offset = 0; offset < 250; offset += 100) {
    const body = {
      size: 100,
      offset,
      sortField: "percentchange",
      sortType: direction === "down" ? "ASC" : "DESC",
      quoteType: "EQUITY",
      query: { operator: "AND", operands: ops },
    };
    const data = await yahoo(
      session,
      "https://query1.finance.yahoo.com/v1/finance/screener?crumb=" + encodeURIComponent(session.crumb),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
    const result = data.finance.result && data.finance.result[0];
    if (!result) break;
    total = result.total || 0;
    quotes.push(...(result.quotes || []));
    if (quotes.length >= total) break;
  }
  return quotes;
}

function isPreferredKorea(symbol, name) {
  const code = String(symbol || "").split(".")[0];
  if (/[57KL]$/.test(code)) return true;
  return /\(1P\)|\(2P|우선주|우B|\(우\)/.test(name || "");
}

function tvExchange(code) {
  if (code === "NYQ") return "NYSE";
  if (code === "ASE" || code === "PCX") return "AMEX";
  return "NASDAQ";
}

function chartUrl(quote) {
  const symbol = quote.symbol || "";
  if (symbol.endsWith(".KS") || symbol.endsWith(".KQ")) {
    const code = symbol.split(".")[0];
    return "https://www.tradingview.com/chart/?symbol=KRX:" + encodeURIComponent(code) + "&interval=D";
  }
  const tv = tvExchange(quote.exchange) + ":" + symbol;
  return "https://www.tradingview.com/chart/?symbol=" + encodeURIComponent(tv) + "&interval=D";
}

async function mapPool(items, limit, worker) {
  const out = new Array(items.length);
  let next = 0;
  async function run() {
    while (next < items.length) {
      const index = next++;
      out[index] = await worker(items[index], index);
    }
  }
  const workers = [];
  const count = Math.min(limit, items.length);
  for (let i = 0; i < count; i++) workers.push(run());
  await Promise.all(workers);
  return out;
}

async function latestQuarterEps(session, symbol) {
  try {
    const data = await yahoo(
      session,
      "https://query1.finance.yahoo.com/v10/finance/quoteSummary/" +
        encodeURIComponent(symbol) +
        "?modules=earnings&crumb=" +
        encodeURIComponent(session.crumb)
    );
    const quarters =
      (((data.quoteSummary || {}).result || [])[0] || {}).earnings?.earningsChart?.quarterly || [];
    let last = null;
    let period = "";
    for (const quarter of quarters) {
      const raw = quarter && quarter.actual && quarter.actual.raw;
      if (raw != null && Number.isFinite(raw)) {
        last = raw;
        period = quarter.date || "";
      }
    }
    return { eps: last, period };
  } catch (e) {
    return { eps: null, period: "" };
  }
}

function toRow(quote, marketCapUsd, eps) {
  return {
    symbol: quote.symbol,
    code: String(quote.symbol).replace(/\.(KS|KQ)$/, ""),
    name: quote.shortName || quote.longName || quote.symbol,
    price: quote.regularMarketPrice,
    currency: quote.currency || "USD",
    changePercent: quote.regularMarketChangePercent,
    marketCapUsd,
    eps,
    period: "",
    chart: chartUrl(quote),
  };
}

async function buildSection(session, spec, fx) {
  const minCap = spec.region === "kr" ? KR_MIN_CAP_USD * fx * 0.98 : US_MIN_CAP;
  const quotes = await screen(session, {
    region: spec.region,
    direction: spec.direction,
    minCap,
    exchanges: spec.region === "us" ? US_EXCHANGES : null,
  });
  let rows = [];
  for (const quote of quotes) {
    const pct = Number(quote.regularMarketChangePercent);
    if (!Number.isFinite(pct)) continue;
    if (spec.direction === "down" && pct > -10) continue;
    if (spec.direction === "up" && pct < 10) continue;
    const cap = Number(quote.marketCap);
    if (!Number.isFinite(cap) || cap <= 0) continue;
    const marketCapUsd = quote.currency === "KRW" ? cap / fx : cap;
    const floor = spec.region === "kr" ? KR_MIN_CAP_USD : US_MIN_CAP;
    if (marketCapUsd < floor) continue;
    if (spec.region === "kr" && isPreferredKorea(quote.symbol, quote.shortName || quote.longName)) continue;
    rows.push(toRow(quote, marketCapUsd, null));
  }
  if (rows.length) {
    const epsList = await mapPool(rows, 8, (row) => latestQuarterEps(session, row.symbol));
    rows = rows.filter((row, index) => {
      const found = epsList[index] || {};
      if (found.eps == null || found.eps <= 0) return false;
      row.eps = found.eps;
      row.period = found.period || "";
      return true;
    });
  }
  rows.sort((a, b) =>
    spec.direction === "down" ? a.changePercent - b.changePercent : b.changePercent - a.changePercent
  );
  return {
    id: spec.id,
    title: spec.title,
    note: spec.note,
    rows,
  };
}

async function buildPayload() {
  const session = await yahooSession();
  const fxData = await yahoo(
    session,
    "https://query1.finance.yahoo.com/v7/finance/quote?symbols=KRW%3DX&crumb=" +
      encodeURIComponent(session.crumb)
  );
  const fx = Number((((fxData.quoteResponse || {}).result || [])[0] || {}).regularMarketPrice);
  if (!Number.isFinite(fx) || fx <= 0) throw new Error("USD/KRW rate missing");

  const specs = [
    {
      id: "us-down",
      region: "us",
      direction: "down",
      title: "1. 미국 10% 이상 급락주",
      note: "시가총액 10억 달러 이상, 직전 분기 EPS(주당순이익)가 플러스인 뉴욕·나스닥 종목입니다.",
    },
    {
      id: "kr-down",
      region: "kr",
      direction: "down",
      title: "2. 한국 10% 이상 급락주",
      note: "시가총액 5억 달러 이상, 직전 분기 EPS(주당순이익)가 플러스인 코스피·코스닥 종목입니다. 우선주는 빼었습니다.",
    },
    {
      id: "us-up",
      region: "us",
      direction: "up",
      title: "3. 미국 10% 이상 급등주",
      note: "시가총액 10억 달러 이상, 직전 분기 EPS(주당순이익)가 플러스인 뉴욕·나스닥 종목입니다.",
    },
    {
      id: "kr-up",
      region: "kr",
      direction: "up",
      title: "4. 한국 10% 이상 급등주",
      note: "시가총액 5억 달러 이상, 직전 분기 EPS(주당순이익)가 플러스인 코스피·코스닥 종목입니다. 우선주는 빼었습니다.",
    },
  ];
  const sections = await Promise.all(specs.map((spec) => buildSection(session, spec, fx)));
  return {
    updatedAt: new Date().toISOString(),
    fxKrw: fx,
    sections,
  };
}

module.exports = async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  try {
    const payload = await buildPayload();
    res.status(200).json(payload);
  } catch (error) {
    res.status(502).json({ error: error.message || "시세를 가져오지 못했습니다." });
  }
};

module.exports.buildPayload = buildPayload;
