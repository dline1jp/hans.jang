# -*- coding: utf-8 -*-
"""Refresh US, Korea, and Japan top-20 market-cap lists and BNF 25-day signals.

Buy signal on the latest daily bar only when every rule below is true:
1. Over the last 10 sessions into yesterday, disparity fell in a staircase
   of at least 3 down days, each drop smaller than the previous drop.
   Bounces between those down days are allowed. The lowest disparity in
   those 10 sessions is also -20% or deeper.
2. Disparity fall stopped: today's disparity >= yesterday's disparity.
3. Price fall stopped: today's low does not break yesterday's low.
4. Volume spike: today's volume, or yesterday's volume, is at least 2x
   the average of the prior 20 sessions (the 20 days before that bar).
5. First bullish candle: today close > open, and yesterday was not a
   bullish candle (close > open).

A positive disparity means the close is above the 25-day SMA. Those
names are out of scope (대상외) and never get a buy signal.

Disparity = (close / 25-day SMA - 1) * 100, using adjusted closes.
Candle color and the low comparison use unadjusted OHLC.

Market-cap source: Yahoo screener (region us / jp), sorted by
intraday market cap. If the Japan screener returns no .T names, fall
back to the public TradingView Japan scanner. Korea uses the Naver
KOSPI market-value list, same endpoint as update_rank.py.
"""
import html
import json
import pathlib
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener"
KOSPI_URL = "https://m.stock.naver.com/api/stocks/marketValue/KOSPI"
TV_SCAN = "https://scanner.tradingview.com/japan/scan"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGE = pathlib.Path(__file__).with_name("index.html")
TV_STUDIES = urllib.parse.quote(json.dumps([
    {
        "id": "MASimple@tv-basicstudies",
        "inputs": {"length": 25},
        "overrides": {"MovAvgSimple.color": "#FFD54F", "MovAvgSimple.linewidth": 2},
    },
    {
        "id": "MASimple@tv-basicstudies",
        "inputs": {"length": 50},
        "overrides": {"MovAvgSimple.color": "#42A5F5", "MovAvgSimple.linewidth": 2},
    },
    {"id": "RSI@tv-basicstudies", "inputs": {"length": 14}},
], separators=(",", ":")))
TOP_N = 20
CANDIDATES = 30
SMA = 25
FALL_STEPS = 3
TROUGH_WINDOW = 10
TROUGH_LIMIT = -20.0
VOLUME_AVG = 20
VOLUME_MULT = 2.0
WATCH = [
    ("QQQ", "QQQ", "Invesco QQQ", "USD", "NASDAQ:QQQ"),
    ("SPY", "SPY", "SPDR S&P 500", "USD", "AMEX:SPY"),
    ("VOO", "VOO", "Vanguard S&P 500", "USD", "AMEX:VOO"),
    ("^SOX", "SOX", "필라델피아 반도체", "USD", "NASDAQ:SOX"),
    ("SMH", "SMH", "VanEck 반도체", "USD", "NASDAQ:SMH"),
    ("SLV", "SLV", "iShares 은", "USD", "AMEX:SLV"),
    ("GLD", "GLD", "SPDR 금", "USD", "AMEX:GLD"),
    ("SCHD", "SCHD", "Schwab 미국배당", "USD", "AMEX:SCHD"),
    ("069500.KS", "069500", "KODEX 200", "KRW", "KRX:069500"),
    ("102110.KS", "102110", "TIGER 200", "KRW", "KRX:102110"),
    ("EWY", "EWY", "iShares 한국", "USD", "AMEX:EWY"),
    ("FLKR", "FLKR", "Franklin 한국", "USD", "AMEX:FLKR"),
    ("BTC-USD", "BTC-USD", "비트코인", "USD", "BITSTAMP:BTCUSD"),
    ("ETH-USD", "ETH-USD", "이더리움", "USD", "BITSTAMP:ETHUSD"),
]
TV_EXCHANGES = {
    "NMS": "NASDAQ",
    "NGM": "NASDAQ",
    "NCM": "NASDAQ",
    "NYQ": "NYSE",
    "NYS": "NYSE",
    "ASE": "AMEX",
    "PCX": "AMEX",
    "BTS": "AMEX",
    "JPX": "TSE",
    "TKS": "TSE",
    "TYO": "TSE",
}

SHELL = """<!DOCTYPE html>
<html>
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BNF 25일선 매수점</title>
  <style>
    html { overflow-x: hidden; }
    body { background: #111; color: white; font-family: Arial, sans-serif; margin: 0; padding: 12px 8px; overflow-x: hidden; }
    * { box-sizing: border-box; }
    a { color: #D8C0FF; }
    .home { font-size: clamp(20px, 2vw, 32px); }
    h1 { text-align: center; color: #FFFFE0; font-size: clamp(20px, 2vw, 32px); line-height: 1.3; margin: 8px 0; }
    h1.low { margin-top: 28px; }
    .rank-wrap { width: 100%; max-width: none; margin: 8px auto; }
    .note, .formula { margin: 8px 0; color: #ccc; font-size: clamp(13px, 1.15vw, 18px); line-height: 1.4; }
    .formula { color: #8a8a8a; }
    .intro .note, .intro .formula { font-size: clamp(19.5px, 1.725vw, 27px); line-height: 1.5; }
    .table-scroll { overflow: visible; width: 100%; }
    table.rank { width: 100%; table-layout: fixed; border-collapse: collapse; margin-top: 8px; }
    table.rank th, table.rank td { border-bottom: 1px solid #444; padding: 5px 2px; text-align: center; white-space: normal; word-break: break-word; overflow-wrap: anywhere; vertical-align: middle; line-height: 1.2; }
    table.rank td, table.rank th { font-size: clamp(11px, 0.78vw, 15px); }
    table.rank th { color: #D8C0FF; }
    table.rank td.name, table.rank th.name { text-align: left; }
    table.rank td.code { color: gold; font-weight: 700; }
    table.rank td.code a { color: #4da3ff; text-decoration: underline; }
    table.rank td.gap-low { color: #f1948a; font-weight: 700; }
    table.rank td.yes { color: #f7dc6f; font-weight: 700; }
    table.rank td.no { color: #888; }
    table.rank tr.buy { background: #143024; }
    table.rank td.signal { color: #7dcea0; font-weight: 700; white-space: nowrap; letter-spacing: 1px; }
    table.rank td.wait { color: #f7dc6f; white-space: nowrap; letter-spacing: 1px; }
    table.rank td.out { color: #888; }
    table.rank .star-on { color: #f7dc6f; }
    table.rank td.signal .star-on { color: #7dcea0; }
    table.rank .star-off { color: #555; }
    table.rank.top td:nth-child(6) { white-space: nowrap; }
    @media (max-width: 860px) {
      body { padding: 8px 6px; }
      .note, .formula { font-size: 14px; }
      .intro .note, .intro .formula { font-size: 21px; }
      table.rank { table-layout: auto; }
      table.rank colgroup { display: none; }
      table.rank thead { display: none; }
      table.rank, table.rank tbody { display: block; width: 100%; }
      table.rank tr {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        column-gap: 8px;
        row-gap: 4px;
        border: 1px solid #444;
        border-radius: 10px;
        margin: 0 0 10px;
        padding: 8px;
        background: #161616;
      }
      table.rank tr.buy { background: #143024; }
      table.rank td {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 6px;
        width: calc(50% - 4px);
        border: none;
        padding: 1px 0;
        text-align: right;
        font-size: 14px;
        white-space: nowrap;
        word-break: keep-all;
        overflow-wrap: normal;
      }
      table.rank td:nth-child(1) { order: 1; width: 1.8rem; justify-content: flex-start; font-weight: 700; }
      table.rank td:nth-child(2) { order: 2; width: auto; justify-content: flex-start; }
      table.rank td:nth-child(14) { order: 3; width: auto; margin-left: auto; justify-content: flex-end; font-size: 13px; }
      table.rank td:nth-child(3) { order: 4; width: 100%; flex: none; justify-content: flex-start; text-align: left; white-space: normal; word-break: break-word; }
      table.rank td:nth-child(n+4):not(:nth-child(14)) { order: 5; }
      table.rank td:nth-child(n+4):not(:nth-child(14))::before {
        content: attr(data-label);
        color: #D8C0FF;
        font-size: 12px;
        font-weight: 700;
      }
      table.rank.top td:nth-child(3) { order: 2; width: auto; flex: none; justify-content: flex-start; text-align: right; white-space: nowrap; }
      table.rank.top td:nth-child(4) { order: 4; width: 100%; flex: none; justify-content: flex-start; text-align: left; white-space: normal; }
      table.rank.top td:nth-child(5) { order: 5; }
      table.rank.top td:nth-child(5)::before { content: attr(data-label); color: #D8C0FF; font-size: 12px; font-weight: 700; }
      table.rank.top td:nth-child(6) { order: 3; width: auto; margin-left: auto; justify-content: flex-end; font-size: 13px; }
      table.rank.top td:nth-child(6)::before { content: none; }
    }
  </style>
</head>
<body>
  <p><a class="home" href="../index.html">← 주가 방향 날씨</a></p>
  <div class="BNF">
<style>
  .bnf-link-banner {
    display: block;
    padding: 14px 18px;
    background: #fff3cd;
    border: 1px solid #e6c45a;
    border-radius: 8px;
    color: #0000FF;
    font-weight: 700;
    font-size: 1.5em;
    text-align: center;
    text-decoration: underline;  }
</style>
<a class="bnf-link-banner"
  href="https://naver.me/xAfwLIjY"
  target="_blank"
  rel="noopener noreferrer">
  0.02억엔으로 200억 번 BNF 전략이 맞는 시기는 이때뿐 </a> <br>
    <img src="Designer (2).png" alt="차트 4">
  </div>
  <h1>BNF 25일선 매수점. 평일 미국장 마감 후 업데이트됩니다.</h1>
<!-- BNF_START -->
<!-- BNF_END -->
</body>
</html>
"""


def yahoo_session():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    session.get("https://fc.yahoo.com", timeout=20)
    crumb = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
    if not crumb or crumb.startswith("{") or crumb.startswith("<"):
        raise RuntimeError("Yahoo crumb failed")
    return session, crumb


def screener_quotes(session, crumb, region):
    payload = {
        "size": CANDIDATES,
        "offset": 0,
        "sortField": "intradaymarketcap",
        "sortType": "DESC",
        "quoteType": "EQUITY",
        "query": {
            "operator": "AND",
            "operands": [{"operator": "eq", "operands": ["region", region]}],
        },
    }
    response = session.post(
        SCREENER_URL,
        params={"crumb": crumb, "lang": "en-US", "region": region.upper()},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    result = (response.json().get("finance") or {}).get("result") or []
    if not result:
        return []
    rows = []
    for quote in result[0].get("quotes") or []:
        if quote.get("quoteType") != "EQUITY":
            continue
        symbol = quote.get("symbol") or ""
        if not symbol or symbol.startswith("^"):
            continue
        rows.append(
            {
                "ticker": symbol,
                "name": quote.get("shortName") or quote.get("longName") or symbol,
                "currency": quote.get("currency") or "",
                "market_cap": quote.get("marketCap"),
                "exchange": quote.get("exchange") or "",
                "source": f"Yahoo screener region={region}",
            }
        )
    return rows


def load_us(session, crumb):
    return screener_quotes(session, crumb, "us")


def load_japan_yahoo(session, crumb):
    rows = [row for row in screener_quotes(session, crumb, "jp") if row["ticker"].endswith(".T")]
    return rows


def load_japan_tradingview():
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "options": {"lang": "en"},
        "markets": ["japan"],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "market_cap_basic", "description", "currency", "exchange"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, CANDIDATES],
    }
    response = requests.post(
        TV_SCAN,
        json=payload,
        headers={**HEADERS, "Origin": "https://www.tradingview.com"},
        timeout=30,
    )
    response.raise_for_status()
    rows = []
    for item in response.json().get("data") or []:
        symbol = item.get("s") or ""
        if ":" not in symbol:
            continue
        exchange, code = symbol.split(":", 1)
        if not code.isdigit():
            continue
        fields = item.get("d") or []
        name = fields[2] if len(fields) > 2 and fields[2] else (fields[0] if fields else code)
        market_cap = fields[1] if len(fields) > 1 else None
        currency = fields[3] if len(fields) > 3 and fields[3] else "JPY"
        rows.append(
            {
                "ticker": f"{code}.T",
                "name": name,
                "currency": currency,
                "market_cap": market_cap,
                "exchange": exchange or "TSE",
                "source": "TradingView Japan scanner (Yahoo jp screener had no .T names)",
            }
        )
    return rows


def load_japan(session, crumb):
    try:
        rows = load_japan_yahoo(session, crumb)
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as error:
        print(f"Japan Yahoo screener failed: {error}", flush=True)
        rows = []
    if len(rows) >= TOP_N:
        return rows
    print(f"Japan Yahoo screener returned {len(rows)} .T names; using TradingView scanner", flush=True)
    fallback = load_japan_tradingview()
    seen = {row["ticker"] for row in rows}
    for row in fallback:
        if row["ticker"] not in seen:
            rows.append(row)
            seen.add(row["ticker"])
    return rows


def load_watch():
    rows = []
    for ticker, label, name, currency, tv in WATCH:
        rows.append(
            {
                "ticker": ticker,
                "label": label,
                "name": name,
                "currency": currency,
                "market_cap": market_cap_of(ticker),
                "exchange": "",
                "tv": tv,
                "source": "고정 목록",
            }
        )
    return rows


def market_cap_of(ticker):
    try:
        response = requests.get(
            CHART_URL.format(ticker=urllib.parse.quote(ticker, safe=".-")),
            params={"interval": "1d", "range": "5d"},
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        result = (response.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        value = (result[0].get("meta") or {}).get("marketCap")
        return value if isinstance(value, (int, float)) and value > 0 else None
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def load_korea():
    response = requests.get(
        KOSPI_URL,
        params={"page": 1, "pageSize": 80},
        headers={**HEADERS, "Referer": "https://m.stock.naver.com/"},
        timeout=30,
    )
    response.raise_for_status()
    rows = []
    for item in response.json().get("stocks") or []:
        if item.get("stockEndType") != "stock":
            continue
        code = item.get("itemCode") or ""
        if not code.isdigit() or len(code) != 6 or not code.endswith("0"):
            continue
        market_cap = item.get("marketValueRaw")
        if isinstance(market_cap, str):
            digits = market_cap.replace(",", "").strip()
            market_cap = float(digits) if digits.isdigit() else None
        rows.append(
            {
                "ticker": f"{code}.KS",
                "name": item.get("stockName") or code,
                "currency": "KRW",
                "market_cap": market_cap,
                "exchange": "KRX",
                "source": "Naver KOSPI market value",
            }
        )
        if len(rows) >= CANDIDATES:
            break
    return rows


def chart_url(row):
    ticker = row["ticker"]
    if row.get("tv"):
        symbol = row["tv"]
    elif ticker.endswith(".KS") or ticker.endswith(".KQ"):
        symbol = "KRX:" + ticker.split(".")[0]
    elif ticker.endswith(".T"):
        symbol = "TSE:" + ticker.split(".")[0]
    else:
        exchange = TV_EXCHANGES.get(row.get("exchange") or "", "")
        symbol = f"{exchange}:{ticker}" if exchange else ticker
    return (
        "https://www.tradingview.com/widgetembed/?symbol="
        + urllib.parse.quote(symbol, safe="")
        + "&interval=D&style=1&theme=dark&hideideas=1"
        + "&studies="
        + TV_STUDIES
    )


def daily_bars(ticker):
    for attempt in range(3):
        try:
            response = requests.get(
                CHART_URL.format(ticker=urllib.parse.quote(ticker, safe=".-")),
                params={
                    "interval": "1d",
                    "range": "1y",
                    "events": "div,splits",
                    "includeAdjustedClose": "true",
                },
                headers=HEADERS,
                timeout=30,
            )
            if response.status_code in (429, 500, 502, 503):
                time.sleep(1.2 * (attempt + 1))
                continue
            response.raise_for_status()
            result = (response.json().get("chart") or {}).get("result") or []
            if not result:
                return None
            block = result[0]
            stamps = block.get("timestamp") or []
            quote = (block.get("indicators") or {}).get("quote") or [{}]
            quote = quote[0] if quote else {}
            adjusted = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
            opens = quote.get("open") or []
            highs = quote.get("high") or []
            lows = quote.get("low") or []
            closes = quote.get("close") or []
            volumes = quote.get("volume") or []
            bars = []
            for index, stamp in enumerate(stamps):
                close = closes[index] if index < len(closes) else None
                open_ = opens[index] if index < len(opens) else None
                high = highs[index] if index < len(highs) else None
                low = lows[index] if index < len(lows) else None
                volume = volumes[index] if index < len(volumes) else None
                adj = adjusted[index] if adjusted and index < len(adjusted) else None
                if None in (close, open_, high, low, volume):
                    continue
                if close <= 0 or open_ <= 0 or high <= 0 or low <= 0:
                    continue
                price = adj if isinstance(adj, (int, float)) and adj > 0 else close
                bars.append(
                    {
                        "date": datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(),
                        "open": float(open_),
                        "high": float(high),
                        "low": float(low),
                        "close": float(close),
                        "adj": float(price),
                        "volume": float(volume),
                    }
                )
            return bars or None
        except (requests.RequestException, ValueError, KeyError, TypeError):
            time.sleep(0.6 * (attempt + 1))
    return None


def disparity_series(bars):
    values = []
    for index in range(len(bars)):
        if index + 1 < SMA:
            values.append(None)
            continue
        window = [bar["adj"] for bar in bars[index + 1 - SMA : index + 1]]
        average = sum(window) / SMA
        if average <= 0:
            values.append(None)
            continue
        values.append((bars[index]["adj"] / average - 1) * 100)
    return values


def staircase_steps(values, end, window):
    """Shrinking down-steps in disparity, ending on `end`.

    A step is a day disparity fell. Up days are pauses and do not reset
    the staircase. The latest drops must get smaller each step.
    """
    if end <= 0 or values[end] is None or values[end - 1] is None:
        return 0
    if values[end] >= values[end - 1]:
        return 0
    start = max(1, end - window + 1)
    drops = []
    for index in range(start, end + 1):
        previous = values[index - 1]
        current = values[index]
        if previous is None or current is None or current >= previous:
            continue
        drops.append(previous - current)
    count = 1
    for index in range(len(drops) - 1, 0, -1):
        if drops[index - 1] <= drops[index]:
            break
        count += 1
    return count


def average_volume(bars, end, length):
    window = bars[end - length : end]
    if len(window) < length:
        return None
    return sum(bar["volume"] for bar in window) / length


def evaluate(bars):
    need = SMA + VOLUME_AVG + FALL_STEPS
    if not bars or len(bars) < need:
        return None
    values = disparity_series(bars)
    today = len(bars) - 1
    yesterday = today - 1
    if values[today] is None or values[yesterday] is None:
        return None
    trough_slice = [value for value in values[today + 1 - TROUGH_WINDOW : today + 1] if value is not None]
    if len(trough_slice) < TROUGH_WINDOW:
        return None
    trough = min(trough_slice)
    steps = staircase_steps(values, yesterday, TROUGH_WINDOW)
    falling = steps >= FALL_STEPS
    deep = trough <= TROUGH_LIMIT
    disparity_stop = values[today] >= values[yesterday]
    price_stop = bars[today]["low"] >= bars[yesterday]["low"]
    average_today = average_volume(bars, today, VOLUME_AVG)
    average_yesterday = average_volume(bars, yesterday, VOLUME_AVG)
    multiple_today = bars[today]["volume"] / average_today if average_today else 0
    multiple_yesterday = bars[yesterday]["volume"] / average_yesterday if average_yesterday else 0
    volume_multiple = max(multiple_today, multiple_yesterday)
    volume_spike = volume_multiple >= VOLUME_MULT
    bullish_today = bars[today]["close"] > bars[today]["open"]
    bullish_yesterday = bars[yesterday]["close"] > bars[yesterday]["open"]
    first_yang = bullish_today and not bullish_yesterday
    above_ma = values[today] > 0
    signal = (
        not above_ma
        and falling
        and deep
        and disparity_stop
        and price_stop
        and volume_spike
        and first_yang
    )
    sma = sum(bar["adj"] for bar in bars[today + 1 - SMA : today + 1]) / SMA
    return {
        "date": bars[today]["date"],
        "price": bars[today]["adj"],
        "sma": sma,
        "disparity": values[today],
        "trough": trough,
        "fall_steps": steps,
        "falling": falling and deep,
        "disparity_stop": disparity_stop,
        "price_stop": price_stop,
        "volume_multiple": volume_multiple,
        "volume_spike": volume_spike,
        "first_yang": first_yang,
        "above_ma": above_ma,
        "signal": signal,
    }


def fmt_number(value, currency):
    if currency in ("KRW", "JPY"):
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def fmt_market_cap(value, currency):
    if not isinstance(value, (int, float)) or value <= 0:
        return "-"
    scaled = value / 1e12
    unit = {"USD": "조달러", "KRW": "조원", "JPY": "조엔"}.get(currency, "조")
    if scaled >= 1:
        return f"{scaled:,.2f}{unit}"
    return f"{value / 1e8:,.0f}{'억' + unit[1:] if unit.startswith('조') else unit}"


def yn(flag):
    return "예" if flag else "아니오"


def score_row(seed, bars):
    signal = evaluate(bars)
    if not signal:
        return None
    row = dict(seed)
    row.update(signal)
    row["checks"] = sum(
        1
        for flag in (
            signal["falling"],
            signal["disparity_stop"],
            signal["price_stop"],
            signal["volume_spike"],
            signal["first_yang"],
        )
        if flag
    )
    return row


def company_key(name):
    text = str(name).lower()
    for token in (
        " inc.",
        " inc",
        " corporation",
        " corp.",
        " corp",
        " ltd.",
        " ltd",
        " plc",
        " co.,",
        " co.",
        " new",
        " class a",
        " class b",
        " class c",
    ):
        text = text.replace(token, " ")
    return " ".join(text.split())


def unique_companies(rows):
    kept = []
    seen = set()
    for row in rows:
        key = company_key(row["name"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def collect(seeds):
    picked = []
    pending = list(seeds)
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(daily_bars, row["ticker"]): row for row in pending[:CANDIDATES]}
        for future in as_completed(future_map):
            seed = future_map[future]
            bars = future.result()
            row = score_row(seed, bars)
            if row:
                picked.append(row)
    order = {row["ticker"]: index for index, row in enumerate(seeds)}
    picked.sort(key=lambda row: order.get(row["ticker"], 999))
    picked = picked[:TOP_N]
    for index, row in enumerate(picked, start=1):
        row["cap_rank"] = index
    picked.sort(key=lambda row: (0 if row["signal"] else 1, row["cap_rank"]))
    return picked


def cell_flag(flag, label):
    kind = "yes" if flag else "no"
    return f'<td class="{kind}" data-label="{label}">{yn(flag)}</td>'


def stars(count, total=5):
    filled = "★" * count
    empty = "☆" * (total - count)
    return f'<span class="star-on">{filled}</span><span class="star-off">{empty}</span>'


def verdict_of(row):
    if row["disparity"] > 0:
        return "대상외", "out", "대상외"
    if row["signal"]:
        return stars(5), "signal", "매수 시그널 5/5"
    count = row["checks"]
    return stars(count), "wait", f"관찰 {count}/5"


def render_table(title, rows, lead=None):
    if not rows:
        return f'<h1 class="low">{html.escape(title)}</h1><section class="rank-wrap"><p class="note">데이터를 가져오지 못했습니다.</p></section>'
    source = rows[0].get("source") or ""
    asof = max(row["date"] for row in rows)
    signals = [row for row in rows if row["signal"]]
    blurb = lead or f"시가총액 상위 {len(rows)}종목"
    lines = [
        f'<h1 class="low">{html.escape(title)}</h1>',
        '<section class="rank-wrap">',
        f'<p class="note">기준 일봉 {html.escape(asof)} · {html.escape(blurb)} · 매수 시그널 {len(signals)}종목. 출처: {html.escape(source)}. 매수 시그널이 위로 올라옵니다. 시그널이 없어도 조건표는 모두 보여 줍니다.</p>',
        '<div class="table-scroll"><table class="rank">',
        "<colgroup>"
        '<col style="width:4%"><col style="width:7%"><col style="width:14%"><col style="width:8%">'
        '<col style="width:8%"><col style="width:8%"><col style="width:6%"><col style="width:6%">'
        '<col style="width:5%"><col style="width:5%"><col style="width:5%">'
        '<col style="width:6%"><col style="width:5%"><col style="width:13%">'
        "</colgroup>",
        "<thead><tr>"
        '<th title="시가총액 순위">시총</th><th class="code">코드</th><th class="name">종목</th><th>시총액</th>'
        f'<th>종가</th><th title="{SMA}일 단순이동평균">{SMA}일</th><th title="{SMA}일선 이격도">이격</th><th title="최근 10거래일 이격도 저점">저점</th>'
        '<th class="flag" title="최근 10거래일 계단식 3단계 이상, 하락폭은 단계마다 감소, 저점 -20% 이하">추락</th>'
        '<th class="flag" title="오늘 이격도 ≥ 어제 이격도">정지</th>'
        '<th class="flag" title="오늘 저가 ≥ 어제 저가">하락</th>'
        '<th title="거래량이 20일 평균의 몇 배인지">거래</th>'
        '<th class="flag" title="오늘 첫 양봉">양봉</th><th class="flag">판정</th>'
        "</tr></thead><tbody>",
    ]
    for row in rows:
        verdict, verdict_class, verdict_title = verdict_of(row)
        tr = ' class="buy"' if row["signal"] else ""
        lines.append(
            f"<tr{tr}>"
            f'<td data-label="시총">{row["cap_rank"]}</td>'
            f'<td class="code" data-label="코드"><a href="{html.escape(chart_url(row))}" target="_blank">{html.escape(row.get("label") or row["ticker"].split(".")[0])}</a></td>'
            f'<td class="name" data-label="종목">{html.escape(str(row["name"]))}</td>'
            f'<td data-label="시총액">{html.escape(fmt_market_cap(row.get("market_cap"), row.get("currency") or ""))}</td>'
            f'<td data-label="종가">{fmt_number(row["price"], row.get("currency") or "")}</td>'
            f'<td data-label="{SMA}일">{fmt_number(row["sma"], row.get("currency") or "")}</td>'
            f'<td class="gap-low" data-label="이격">{row["disparity"]:.1f}%</td>'
            f'<td class="gap-low" data-label="저점">{row["trough"]:.1f}%</td>'
            f'{cell_flag(row["falling"], "추락")}'
            f'{cell_flag(row["disparity_stop"], "정지")}'
            f'{cell_flag(row["price_stop"], "하락")}'
            f'<td data-label="거래">{row["volume_multiple"]:.1f}x</td>'
            f'{cell_flag(row["first_yang"], "양봉")}'
            f'<td class="{verdict_class}" data-label="판정" title="{html.escape(verdict_title)}">{verdict}</td>'
            "</tr>"
        )
    lines.append("</tbody></table></div></section>")
    return "\n".join(lines)


def star_count(row):
    if row["disparity"] > 0:
        return None
    if row["signal"]:
        return 5
    return row["checks"]


def render_intro():
    return """<section class="rank-wrap">
<div class="intro">
<p class="note">일봉 25일 단순이동평균 기준 이격도만 봅니다. 이격도가 플러스(종가가 25일선 위)이면 대상외입니다. 매수 시그널은 이격도가 0 이하이고 아래 다섯 가지가 최신 일봉에서 동시에 맞을 때만 붙입니다. 매수 추천이 아닙니다. 파산 가능성, 실적, 경기사이클을 따로 보셔야 하니 참조만 하세요.</p>
<p class="formula">이격도 = (일봉 종가 ÷ 25일 단순이동평균 − 1) × 100. 종가는 수정주가입니다. 양봉과 저가 비교는 수정 전 시고저종입니다.</p>
<p class="formula">1)추락: 최근 10거래일 이격도가 계단식으로 3단계 이상 하락하고, 각 하락폭은 직전 하락보다 작다. 그 사이 반등은 있어도 된다. 최근 10거래일 이격도 저점이 -20% 이하. 2) 정지: 오늘 이격도 ≥ 어제 이격도 (추락 정지). 3) 하락: 오늘 저가 ≥ 어제 저가 (하락 정지). 4) 거래: 오늘 또는 어제 거래량이 그 직전 20일 평균의 2배 이상 (거래량 폭증). 5) 양봉: 오늘 종가 &gt; 시가이고, 어제는 양봉이 아님 (첫 양봉) 판정: 별5개가 만점 매수 시그널이나 별3개, 4개때부터 관찰이 필요함. 여기에 매일 시세가 업데이트됨.</p>
<p class="formula">종목 코드를 누르면 일봉 차트에 25일 단순이동평균, 50일 단순이동평균, RSI 14가 함께 열립니다.</p>
</div>
</section>"""


def render_summary(rows):
    ranked = []
    for row in rows:
        count = star_count(row)
        if count is None:
            continue
        item = dict(row)
        item["star_count"] = count
        ranked.append(item)
    ranked.sort(key=lambda row: (-row["star_count"], row["disparity"], row.get("group") or "", row["cap_rank"]))
    ranked = ranked[:10]
    lines = [
        '<h1 class="low">별이 많은 10종목</h1>',
        '<section class="rank-wrap">',
        '<p class="note">미국·한국·일본·주요 목록에서 대상외를 빼고, 별이 많은 순입니다. 별이 같으면 이격도가 더 낮은 종목이 위입니다.</p>',
        '<div class="table-scroll"><table class="rank top">',
        '<colgroup><col style="width:8%"><col style="width:10%"><col style="width:14%"><col style="width:34%"><col style="width:12%"><col style="width:22%"></colgroup>',
        "<thead><tr>"
        "<th>순위</th><th>시장</th><th class=\"code\">코드</th><th class=\"name\">종목</th>"
        '<th title="25일선 이격도">이격</th><th>판정</th>'
        "</tr></thead><tbody>",
    ]
    if not ranked:
        lines.append('<tr><td colspan="6">별이 있는 종목이 없습니다.</td></tr>')
    for index, row in enumerate(ranked, start=1):
        verdict, verdict_class, verdict_title = verdict_of(row)
        tr = ' class="buy"' if row["signal"] else ""
        label = row.get("label") or row["ticker"].split(".")[0]
        lines.append(
            f"<tr{tr}>"
            f'<td data-label="순위">{index}</td>'
            f'<td data-label="시장">{html.escape(row.get("group") or "")}</td>'
            f'<td class="code" data-label="코드"><a href="{html.escape(chart_url(row))}" target="_blank">{html.escape(label)}</a></td>'
            f'<td class="name" data-label="종목">{html.escape(str(row["name"]))}</td>'
            f'<td class="gap-low" data-label="이격">{row["disparity"]:.1f}%</td>'
            f'<td class="{verdict_class}" data-label="판정" title="{html.escape(verdict_title)}">{verdict}</td>'
            "</tr>"
        )
    lines.append("</tbody></table></div></section>")
    return "\n".join(lines)


def write_page(sections):
    if PAGE.exists():
        text = PAGE.read_text(encoding="utf-8")
    else:
        text = SHELL
    start = text.find("<!-- BNF_START -->")
    end = text.find("<!-- BNF_END -->")
    block = "<!-- BNF_START -->\n" + "\n".join(sections) + "\n<!-- BNF_END -->"
    if start == -1 or end == -1 or end < start:
        text = SHELL
        start = text.find("<!-- BNF_START -->")
        end = text.find("<!-- BNF_END -->")
    text = text[:start] + block + text[end + len("<!-- BNF_END -->") :]
    PAGE.write_text(text, encoding="utf-8")


def main():
    session, crumb = yahoo_session()
    markets = [
        ("1. 미국 시가총액 상위 20종목", "미국", load_us(session, crumb), None),
        ("2. 한국 코스피 시가총액 상위 20종목", "한국", load_korea(), None),
        ("3. 일본 시가총액 상위 20종목", "일본", load_japan(session, crumb), None),
        ("4. 주요 ETF·지수 14종목", "주요", load_watch(), "목록 순서 14종목"),
    ]
    sections = []
    ranked = []
    summary = []
    for title, group, seeds, lead in markets:
        seeds = unique_companies(seeds)
        for seed in seeds:
            seed["group"] = group
        print(f"{title}: candidates {len(seeds)}", flush=True)
        rows = collect(seeds)
        print(f"  kept {len(rows)} signals {sum(1 for row in rows if row['signal'])}", flush=True)
        sections.append(render_table(title, rows, lead))
        ranked.extend(rows)
        summary.append(
            {
                "title": title,
                "count": len(rows),
                "source": rows[0]["source"] if rows else "",
                "signals": [
                    {"ticker": row["ticker"], "name": row["name"], "disparity": round(row["disparity"], 1)}
                    for row in rows
                    if row["signal"]
                ],
            }
        )
    sections.insert(0, render_summary(ranked))
    sections.insert(1, render_intro())
    write_page(sections)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
