# -*- coding: utf-8 -*-
"""한스장 종목 정보: 티커로 검색해 투자 정보와 간략 차트를 본다.

    python Premium/hansjang/stock/update_stock.py

Yahoo Finance 에서 S&P 500 과 한국 주요 종목을 받아
  Premium/hansjang/stock/data/<티커>.json
  Premium/hansjang/stock/index.json
을 쓴다. 페이지(stock/index.html)는 이 파일들만 읽는다.
"""
import datetime
import io
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
INDEX_FILE = ROOT / "index.json"
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
QUOTE_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules={modules}&crumb={crumb}"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y"
TRANS_URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q={text}"
TRANS_CACHE = {}
MODULES = ("price,summaryDetail,defaultKeyStatistics,financialData,assetProfile,"
           "earnings,earningsTrend,recommendationTrend")
UA = {"User-Agent": "Mozilla/5.0"}

KR_CODES = [
    "005930", "000660", "373220", "207940", "005380", "000270", "068270", "035420", "035720",
    "051910", "006400", "028260", "012330", "055550", "105560", "086790", "032830", "005490",
    "015760", "017670", "030200", "034730", "096770", "010950", "011200", "011070", "009150",
    "066570", "003550", "090430", "097950", "001040", "004020", "010130", "000100", "128940",
    "302440", "326030", "247540", "086520", "196170", "293490", "036570", "251270", "259960",
    "352820", "000720", "006360", "047040", "267260", "010120", "298040", "000500", "083450",
    "417200", "307950", "042700", "240810", "058470", "403870", "023530", "021240", "034020",
    "241560", "012450", "047810", "064350", "009540", "329180", "042660", "138040", "316140",
    "024110", "006800", "016360", "000810", "017800", "003670", "005070", "282330", "069960",
]

EXTRA = ["QQQ", "SPY", "VOO", "IVV", "SOXX", "SOXL", "SMH", "TQQQ", "TLT", "EDV",
         "GLD", "SLV", "IWM", "DIA", "ARKK", "BTC-USD", "ETH-USD",
         "^GSPC", "^IXIC", "^DJI", "^SOX", "^TNX"]


def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = UA["User-Agent"]
    try:
        session.get("https://fc.yahoo.com", timeout=20)
    except Exception:  # noqa: BLE001
        pass
    crumb = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
    if not crumb or crumb.startswith("<") or crumb.startswith("{"):
        raise SystemExit("Yahoo crumb 를 받지 못했습니다.")
    return session, crumb


def raw(node):
    if isinstance(node, dict):
        value = node.get("raw")
        return value if isinstance(value, (int, float)) else None
    if isinstance(node, (int, float)):
        return node
    return None


def num(node, digits=2):
    value = raw(node)
    if value is None:
        return None
    if digits is None:
        return value
    return round(value, digits)


def sp500_tickers():
    response = requests.get(SP500_URL, headers=UA, timeout=40)
    response.raise_for_status()
    out = []
    lines = response.text.splitlines()
    for line in lines[1:]:
        symbol = line.split(",")[0].strip().strip('"')
        if symbol:
            out.append(symbol.replace(".", "-"))
    return out


def quote(session, crumb, ticker):
    url = QUOTE_URL.format(ticker=urllib.parse.quote(ticker, safe=""), modules=MODULES, crumb=crumb)
    response = session.get(url, timeout=30)
    if response.status_code != 200:
        return None
    result = ((response.json().get("quoteSummary") or {}).get("result") or [])
    return result[0] if result else None


def chart(session, ticker):
    url = CHART_URL.format(ticker=urllib.parse.quote(ticker, safe=""))
    response = session.get(url, timeout=30)
    if response.status_code != 200:
        return None
    result = ((response.json().get("chart") or {}).get("result") or [])
    if not result:
        return None
    block = result[0]
    meta = block.get("meta") or {}
    stamps = block.get("timestamp") or []
    quotes = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    adjusted = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    closes = quotes.get("close") or []
    volumes = quotes.get("volume") or []
    days = []
    values = []
    vols = []
    for index, stamp in enumerate(stamps):
        close = closes[index] if index < len(closes) else None
        if not isinstance(close, (int, float)) or close <= 0:
            continue
        factor = 1.0
        if adjusted and index < len(adjusted) and isinstance(adjusted[index], (int, float)):
            factor = adjusted[index] / close
        volume = volumes[index] if index < len(volumes) else 0
        days.append(datetime.datetime.utcfromtimestamp(stamp).strftime("%Y-%m-%d"))
        values.append(round(close * factor, 2))
        vols.append(int(volume) if isinstance(volume, (int, float)) else 0)
    if not days:
        return None
    base = datetime.datetime.strptime(days[0], "%Y-%m-%d")
    offsets = [int((datetime.datetime.strptime(day, "%Y-%m-%d") - base).days) for day in days]
    return {"d0": days[0], "dd": offsets, "c": values, "v": vols, "m": meta}


NAME_SUFFIX = [
    ", Inc.", " Inc.", " Inc", ", Ltd.", " Ltd.", " Ltd", " Co., Ltd.", " Co.,Ltd.", " Co.,Ltd",
    " Corporation", " Corp.", " Company", " Limited", " PLC", " plc", " S.A.", " N.V.",
    " 주식회사", "주식회사", "(주)", "㈜", " 코퍼레이션", " 코포레이션",
]


# 번역이 실패할 때를 대비한 잘 알려진 이름
NAME_FALLBACK = {
    "Doosan Enerbility Co., Ltd.": "두산에너빌리티",
    "NC Corporation": "엔씨소프트",
    "Global Standard Technology, Limited": "지에스티",
}


def clean_name(text):
    """번역된 회사명에서 법인격 접미사를 떼어 검색하기 좋게 만든다."""
    text = (text or "").strip()
    changed = True
    while changed and text:
        changed = False
        for suffix in NAME_SUFFIX:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[:-len(suffix)].strip()
                changed = True
    return text or None


def tr(text):
    """영문 회사 정보를 한국어로 옮긴다. 실패하면 None 을 돌려주고 영문을 그대로 쓴다."""
    text = (text or "").strip()
    if not text:
        return None
    if text in TRANS_CACHE:
        return TRANS_CACHE[text]
    out = None
    for attempt in range(3):
        try:
            url = TRANS_URL.format(text=urllib.parse.quote(text[:1600]))
            response = requests.get(url, headers=UA, timeout=25)
            if response.status_code == 200:
                data = response.json()
                out = "".join(part[0] for part in data[0] if part and part[0]).strip() or None
                if out:
                    break
        except Exception:  # noqa: BLE001
            out = None
        time.sleep(0.6 * (attempt + 1))
    TRANS_CACHE[text] = out
    return out


def build_profile(profile):
    profile = profile or {}
    summary = (profile.get("longBusinessSummary") or "").strip()[:800]
    return {
        "c": profile.get("country"),
        "cKo": tr(profile.get("country")),
        "s": profile.get("sector"),
        "sKo": tr(profile.get("sector")),
        "i": profile.get("industry"),
        "iKo": tr(profile.get("industry")),
        "city": profile.get("city"),
        "emp": profile.get("fullTimeEmployees"),
        "web": profile.get("website"),
        "sum": summary,
        "sumKo": tr(summary) if summary else None,
    }


def build_financials(earnings):
    earnings = earnings or {}
    charts = earnings.get("financialsChart") or {}
    annual = []
    for row in charts.get("yearly") or []:
        annual.append({"y": row.get("date"), "rev": num(row.get("revenue"), 0), "ni": num(row.get("earnings"), 0)})
    quarterly = []
    for row in charts.get("quarterly") or []:
        quarterly.append({"q": row.get("date"), "rev": num(row.get("revenue"), 0), "ni": num(row.get("earnings"), 0)})
    eps = []
    for row in (earnings.get("earningsChart") or {}).get("quarterly") or []:
        eps.append({"q": row.get("date"), "act": num(row.get("actual"), 3), "est": num(row.get("estimate"), 3)})
    return {"annual": annual, "quarterly": quarterly, "eps": eps}


def build_trend(earnings_trend):
    out = []
    for row in (earnings_trend or {}).get("trend") or []:
        estimate = row.get("earningsEstimate") or {}
        revenue = row.get("revenueEstimate") or {}
        out.append({
            "p": row.get("period"),
            "eps": num(estimate.get("avg"), 3),
            "n": num(estimate.get("numberOfAnalysts"), 0),
            "rev": num(revenue.get("avg"), 0),
            "growth": num(row.get("growth"), 4),
        })
    return out


def build_rec(rec, financial):
    current = {}
    for row in (rec or {}).get("trend") or []:
        if row.get("period") == "0m":
            current = row
    financial = financial or {}
    return {
        "sb": current.get("strongBuy"), "b": current.get("buy"), "h": current.get("hold"),
        "s": current.get("sell"), "ss": current.get("strongSell"),
        "key": financial.get("recommendationKey"),
        "mean": num(financial.get("recommendationMean"), 2),
        "n": num(financial.get("numberOfAnalystOpinions"), 0),
        "tgt": num(financial.get("targetMeanPrice"), 2),
        "tgtH": num(financial.get("targetHighPrice"), 2),
        "tgtL": num(financial.get("targetLowPrice"), 2),
    }


def build_entry(ticker, summary):
    price = summary.get("price") or {}
    detail = summary.get("summaryDetail") or {}
    stats = summary.get("defaultKeyStatistics") or {}
    financial = summary.get("financialData") or {}
    name = price.get("longName") or price.get("shortName") or ticker
    return {
        "t": ticker,
        "n": name,
        "nKo": clean_name(tr(name)) or NAME_FALLBACK.get(name),
        "ex": price.get("exchangeName"),
        "cur": price.get("currency") or detail.get("currency"),
        "px": num(price.get("regularMarketPrice")),
        "chg": num(price.get("regularMarketChange")),
        "chgPct": num(price.get("regularMarketChangePercent"), 5),
        "prev": num(detail.get("regularMarketPreviousClose") or detail.get("previousClose")),
        "dayH": num(detail.get("regularMarketDayHigh") or detail.get("dayHigh")),
        "dayL": num(detail.get("regularMarketDayLow") or detail.get("dayLow")),
        "w52H": num(detail.get("fiftyTwoWeekHigh")),
        "w52L": num(detail.get("fiftyTwoWeekLow")),
        "vol": num(price.get("regularMarketVolume") or detail.get("volume"), 0),
        "avgVol": num(price.get("averageDailyVolume10Day") or detail.get("averageVolume"), 0),
        "mcap": num(detail.get("marketCap"), 0),
        "pe": num(detail.get("trailingPE")),
        "fpe": num(detail.get("forwardPE") or stats.get("forwardPE")),
        "eps": num(stats.get("trailingEps")),
        "feps": num(stats.get("forwardEps")),
        "pb": num(stats.get("priceToBook")),
        "div": num(detail.get("dividendRate")),
        "divY": num(detail.get("dividendYield"), 5),
        "beta": num(detail.get("beta") or stats.get("beta")),
        "short": num(stats.get("sharesShort"), 0),
        "shortPct": num(stats.get("shortPercentOfFloat"), 5),
        "shortRatio": num(stats.get("shortRatio")),
        "prof": build_profile(summary.get("assetProfile")),
        "fin": build_financials(summary.get("earnings")),
        "trend": build_trend(summary.get("earningsTrend")),
        "rec": build_rec(summary.get("recommendationTrend"), financial),
        "growth": {
            "rev": num(financial.get("revenueGrowth"), 5),
            "earn": num(financial.get("earningsGrowth"), 5),
            "margin": num(financial.get("profitMargins"), 5),
            "gross": num(financial.get("grossMargins"), 5),
            "roe": num(financial.get("returnOnEquity"), 5),
            "debt": num(financial.get("debtToEquity")),
            "current": num(financial.get("currentRatio")),
        },
    }


def safe_name(ticker):
    return ticker.replace(".", "_").replace("^", "IDX_").replace("-", "_") + ".json"


def job(ticker, session, crumb):
    try:
        summary = quote(session, crumb, ticker)
        if not summary:
            return None
        entry = build_entry(ticker, summary)
        series = chart(session, ticker)
        if series:
            entry["ch"] = {"d0": series["d0"], "dd": series["dd"], "c": series["c"], "v": series["v"]}
            if series["m"].get("longName") and entry["n"] == ticker:
                entry["n"] = series["m"]["longName"]
        return entry
    except Exception as error:  # noqa: BLE001
        print("  fail", ticker, error)
        return None


def resolve_kr(code, session, crumb):
    for suffix in (".KS", ".KQ"):
        if quote(session, crumb, code + suffix):
            return code + suffix
    return None


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    try:
        tickers = sp500_tickers()
    except Exception as error:  # noqa: BLE001
        print("S&P 500 list failed:", error)
        tickers = []
    tickers = tickers + EXTRA
    kr = list(KR_CODES)
    if limit:
        tickers = tickers[:limit]
        kr = kr[:limit]
    print("US %d, KR %d" % (len(tickers), len(kr)))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    session, crumb = make_session()
    index = {}

    def record(entry):
        if not entry:
            return
        (DATA_DIR / safe_name(entry["t"])).write_text(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index[entry["t"]] = {"t": entry["t"], "n": entry["n"], "k": entry.get("nKo"),
                             "m": entry.get("cur"), "e": entry.get("ex")}

    with ThreadPoolExecutor(max_workers=10) as pool:
        for entry in pool.map(lambda item: job(item, session, crumb), tickers):
            record(entry)
    print("US done", len(index))

    with ThreadPoolExecutor(max_workers=10) as pool:
        kr_tickers = [item for item in pool.map(lambda code: resolve_kr(code, session, crumb), kr) if item]
    print("KR resolved", len(kr_tickers))
    with ThreadPoolExecutor(max_workers=10) as pool:
        for entry in pool.map(lambda item: job(item, session, crumb), kr_tickers):
            record(entry)

    rows = [index[key] for key in sorted(index)]
    INDEX_FILE.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("total", len(rows))


if __name__ == "__main__":
    main()
