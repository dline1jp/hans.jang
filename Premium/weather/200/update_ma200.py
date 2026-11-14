# -*- coding: utf-8 -*-
"""Daily 200-day moving-average trend signals for the major index funds.

매수(보유): the close broke above the 200-day average and stayed above for at least one more day.
매도(현금): the latest daily close is at or below that average.
The first day back above the line is 돌파 대기, not a buy yet.
Both the close and the average use adjusted prices, so splits and dividends
do not break the line. A name flips only when today's side differs from
yesterday's side.
"""
import html
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener"
KOSPI_URL = "https://m.stock.naver.com/api/stocks/marketValue/KOSPI"
TV_SCAN = "https://scanner.tradingview.com/japan/scan"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGE = Path(__file__).with_name("index.html")
SMA = 200
TOP_N = 20
CANDIDATES = 30
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
# ticker, label, name, currency, TradingView symbol
FUNDS = [
    ("QQQ", "QQQ", "Invesco QQQ", "USD", "NASDAQ:QQQ"),
    ("SPY", "SPY", "SPDR S&P 500", "USD", "AMEX:SPY"),
    ("VOO", "VOO", "Vanguard S&P 500", "USD", "AMEX:VOO"),
    ("^SOX", "SOX", "필라델피아 반도체", "USD", "NASDAQ:SOX"),
    ("SMH", "SMH", "VanEck 반도체", "USD", "NASDAQ:SMH"),
    ("SOXX", "SOXX", "iShares 반도체", "USD", "NASDAQ:SOXX"),
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
        rows.append({
            "ticker": symbol,
            "name": quote.get("shortName") or quote.get("longName") or symbol,
            "currency": quote.get("currency") or "",
            "exchange": quote.get("exchange") or "",
        })
    return rows


def load_us(session, crumb):
    return screener_quotes(session, crumb, "us")[:TOP_N]


def load_japan_yahoo(session, crumb):
    return [row for row in screener_quotes(session, crumb, "jp") if str(row["ticker"]).endswith(".T")]


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
        fields = item.get("d") or []
        name = fields[2] if len(fields) > 2 and fields[2] else (fields[0] if fields else code)
        currency = fields[3] if len(fields) > 3 and fields[3] else "JPY"
        rows.append({
            "ticker": f"{code}.T",
            "name": name,
            "currency": currency,
            "exchange": exchange or "TSE",
        })
    return rows


def load_japan(session, crumb):
    try:
        rows = load_japan_yahoo(session, crumb)
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as error:
        print(f"Japan Yahoo screener failed: {error}", flush=True)
        rows = []
    if len(rows) < TOP_N:
        print(f"Japan Yahoo screener returned {len(rows)} .T names; using TradingView scanner", flush=True)
        seen = {row["ticker"] for row in rows}
        for row in load_japan_tradingview():
            if row["ticker"] not in seen:
                rows.append(row)
                seen.add(row["ticker"])
    return rows[:TOP_N]


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
        rows.append({
            "ticker": f"{code}.KS",
            "name": item.get("stockName") or code,
            "currency": "KRW",
            "exchange": "KRX",
        })
        if len(rows) >= TOP_N:
            break
    return rows


def tv_symbol(ticker, exchange):
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return "KRX:" + ticker.split(".")[0]
    if ticker.endswith(".T"):
        return "TSE:" + ticker[:-2]
    mapped = TV_EXCHANGES.get(exchange or "", "")
    code = ticker.replace("-", ".")
    return f"{mapped}:{code}" if mapped else code


def display_code(ticker):
    if ticker.endswith(".KS") or ticker.endswith(".KQ") or ticker.endswith(".T"):
        return ticker.rsplit(".", 1)[0]
    return ticker


def chart_url(symbol):
    # widgetembed rejects KRX and TSE and shows its default Apple chart.
    return "index.html?symbol=" + urllib.parse.quote(symbol, safe="")


def daily_closes(ticker):
    quoted = urllib.parse.quote(ticker, safe=".-")
    for attempt in range(4):
        try:
            response = requests.get(
                CHART_URL.format(ticker=quoted),
                params={
                    "interval": "1d",
                    "range": "2y",
                    "events": "div,splits",
                    "includeAdjustedClose": "true",
                },
                headers=HEADERS,
                timeout=30,
            )
            if response.status_code in (429, 500, 502, 503):
                time.sleep(1.4 * (attempt + 1))
                continue
            response.raise_for_status()
            result = (response.json().get("chart") or {}).get("result") or []
            if not result:
                time.sleep(0.8 * (attempt + 1))
                continue
            block = result[0]
            stamps = block.get("timestamp") or []
            quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
            adjusted = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
            closes = quote.get("close") or []
            bars = []
            for index, stamp in enumerate(stamps):
                close = closes[index] if index < len(closes) else None
                adj = adjusted[index] if adjusted and index < len(adjusted) else None
                price = adj if isinstance(adj, (int, float)) and adj > 0 else close
                if not isinstance(price, (int, float)) or price <= 0:
                    continue
                bars.append({
                    "date": datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(),
                    "close": float(price),
                })
            if bars:
                return bars
        except (requests.RequestException, ValueError, KeyError, TypeError):
            time.sleep(0.8 * (attempt + 1))
    return None


def sma(closes, end):
    window = closes[end - SMA + 1:end + 1]
    return sum(window) / SMA


def judge(bars):
    closes = [bar["close"] for bar in bars]
    today = len(closes) - 1
    yesterday = today - 1
    before = today - 2
    ma = sma(closes, today)
    prev_ma = sma(closes, yesterday)
    prev2_ma = sma(closes, before)
    close = closes[today]
    prev = closes[yesterday]
    prev2 = closes[before]
    above = close > ma
    prev_above = prev > prev_ma
    prev2_above = prev2 > prev2_ma
    if above and prev_above and not prev2_above:
        signal, change = "매수", "매수 전환"
    elif above and prev_above:
        signal, change = "매수", "보유 유지"
    elif above:
        signal, change = "대기", "돌파 대기"
    elif prev_above:
        signal, change = "매도", "매도 전환"
    else:
        signal, change = "매도", "현금 유지"
    return {
        "date": bars[today]["date"],
        "close": close,
        "ma": ma,
        "disparity": close / ma * 100,
        "buy": signal == "매수",
        "wait": signal == "대기",
        "signal": signal,
        "change": change,
    }


def money(value, currency):
    if currency in ("KRW", "JPY"):
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def chip(row):
    return (
        f'<a href="{chart_url(row["symbol"])}" target="_blank">{html.escape(row["label"])}</a>'
        f'<span>{html.escape(row["name"])}</span>'
    )


def blank_row(item, reason):
    return {
        "label": display_code(item["ticker"]),
        "name": item["name"],
        "currency": item.get("currency") or "",
        "symbol": tv_symbol(item["ticker"], item.get("exchange")),
        "date": "",
        "close": None,
        "ma": None,
        "disparity": None,
        "buy": False,
        "wait": False,
        "signal": "없음",
        "change": reason,
        "missing": True,
    }


def score_items(items, strict):
    scored = []
    failed = []

    def one(item):
        bars = daily_closes(item["ticker"])
        return item, bars

    found = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, item) for item in items]
        for future in as_completed(futures):
            item, bars = future.result()
            found[item["ticker"]] = (item, bars)
    for item in items:
        item, bars = found[item["ticker"]]
        if not bars or len(bars) < SMA + 2:
            reason = "조회 실패" if not bars else "200일선 없음"
            failed.append(display_code(item["ticker"]))
            print(f"FAIL {display_code(item['ticker'])} {reason}", file=sys.stderr)
            if not strict:
                scored.append(blank_row(item, reason))
            continue
        row = judge(bars)
        row.update({
            "label": item.get("label") or display_code(item["ticker"]),
            "name": item["name"],
            "currency": item["currency"],
            "symbol": item.get("symbol") or tv_symbol(item["ticker"], item.get("exchange")),
            "closes": [round(bar["close"], 4) for bar in bars[-320:]],
            "missing": False,
        })
        scored.append(row)
        print(f"{row['label']} {row['date']} {row['signal']} {row['disparity']:.1f} {row['change']}")
    if strict and failed:
        raise SystemExit("시세를 받지 못했습니다: " + ", ".join(failed))
    return scored


def sides(rows):
    live = [row for row in rows if not row.get("missing")]
    buys = [row for row in live if row["buy"]]
    waits = [row for row in live if row["wait"]]
    sells = [row for row in live if not row["buy"] and not row["wait"]]
    return buys, waits, sells


def summary_block(title, rows):
    buys, waits, sells = sides(rows)
    buy_html = "".join(f"<li>{chip(row)}</li>" for row in buys) or "<li>없음</li>"
    wait_box = ""
    if waits:
        wait_html = "".join(f"<li>{chip(row)}</li>" for row in waits)
        wait_box = (
            '<div class="box wait">'
            f"<h2>대기 {len(waits)}개 · 오늘 처음 돌파, 내일 확인</h2>"
            f"<ol>{wait_html}</ol></div>"
        )
    sell_html = "".join(f"<li>{chip(row)}</li>" for row in sells) or "<li>없음</li>"
    return f"""
  <h2 class="market">{html.escape(title)}</h2>
  <section class="summary">
    <div class="box buy">
      <h2>매수 {len(buys)}개 · 200일선 위, 보유</h2>
      <ol>{buy_html}</ol>
    </div>
    <div class="box sell">
      <h2>매도 {len(sells)}개 · 200일선 아래, 현금</h2>
      <ol>{sell_html}</ol>
    </div>
    {wait_box}
  </section>
"""


def table_block(title, rows, ranked):
    head = "<th>순위</th>" if ranked else ""
    body = []
    for order, row in enumerate(rows, start=1):
        rank = f'<td data-label="순위">{order}</td>' if ranked else ""
        if row.get("missing"):
            body.append(
                f'<tr class="miss">{rank}'
                f'<td class="code" data-label="코드">{html.escape(row["label"])}</td>'
                f'<td class="name" data-label="종목">{html.escape(row["name"])}</td>'
                f'<td data-label="기준일">-</td><td data-label="종가">-</td><td data-label="200일선">-</td>'
                f'<td data-label="이격도">-</td><td class="signal" data-label="시그널">없음</td>'
                f'<td data-label="변화">{html.escape(row["change"])}</td></tr>'
            )
            continue
        side = "buy" if row["buy"] else "wait" if row["wait"] else "sell"
        body.append(
            f'<tr class="{side}">{rank}'
            f'<td class="code" data-label="코드"><a href="{chart_url(row["symbol"])}" target="_blank">{html.escape(row["label"])}</a></td>'
            f'<td class="name" data-label="종목">{html.escape(row["name"])}</td>'
            f'<td data-label="기준일">{row["date"]}</td>'
            f'<td data-label="종가">{money(row["close"], row["currency"])}</td>'
            f'<td data-label="200일선">{money(row["ma"], row["currency"])}</td>'
            f'<td class="{side}" data-label="이격도">{row["disparity"]:.1f}</td>'
            f'<td class="signal {side}" data-label="시그널">{row["signal"]}</td>'
            f'<td data-label="변화">{html.escape(row["change"])}</td>'
            "</tr>"
        )
    return f"""
  <h2 class="market">{html.escape(title)}</h2>
  <section class="rank-wrap">
    <table class="rank">
      <thead>
        <tr>
          {head}<th class="code">코드</th><th class="name">종목</th><th>기준일</th><th>종가</th><th>200일선</th><th>이격도</th><th>시그널</th><th>변화</th>
        </tr>
      </thead>
      <tbody>
        {"".join(body)}
      </tbody>
    </table>
  </section>
"""


def series_json(groups):
    payload = {}
    for rows in groups.values():
        for row in rows:
            closes = row.get("closes")
            if not closes or not row.get("symbol"):
                continue
            payload[row["symbol"]] = {
                "label": row["label"],
                "name": row["name"],
                "closes": closes,
            }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render(groups):
    dated = [row["date"] for rows in groups.values() for row in rows if row.get("date")]
    asof = max(dated) if dated else ""
    charts = series_json(groups)
    summaries = []
    tables = []
    for title, rows in groups.items():
        ranked = title != "인덱스"
        summaries.append(summary_block(title, rows))
        tables.append(table_block(title, rows, ranked))
    return f"""<!DOCTYPE html>
<html>
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>200일 이동평균 추세 장투 매매</title>
  <style>
    body {{ background: #111; color: white; font-family: Arial, sans-serif; margin: 0; padding: 16px; }}
    a {{ color: #4da3ff; }}
    .home {{ color: #D8C0FF; font-size: 28px; text-decoration: none; }}
    h1 {{ text-align: center; color: #FFFFE0; font-size: 32px; line-height: 1.35; }}
    .horizon {{ text-align: center; color: #f7dc6f; font-size: 22px; font-weight: 700; line-height: 1.45; max-width: 980px; margin: 6px auto 4px; }}
    .note, .formula {{ color: #ccc; font-size: 18px; line-height: 1.5; max-width: 980px; margin: 8px auto; }}
    .formula {{ color: #8a8a8a; }}
    .rules {{ max-width: 980px; margin: 14px auto 8px; }}
    .rules h2 {{ color: #FFFFE0; font-size: 26px; margin: 0 0 8px; }}
    .rules ol {{ margin: 0; padding-left: 1.3em; color: #eee; font-size: 20px; line-height: 1.55; }}
    .rules li {{ margin: 6px 0; }}
    h2.market {{ max-width: 1100px; margin: 22px auto 8px; color: #FFFFE0; font-size: 28px; }}
    .glance {{ max-width: 1100px; margin: 8px auto 12px; }}
    .summary {{ max-width: 1100px; margin: 0 auto 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .summary .box.wait {{ grid-column: 1 / -1; }}
    .box {{ border: 1px solid #444; border-radius: 12px; padding: 14px 16px; }}
    .box.buy {{ background: #143024; }}
    .box.wait {{ background: #2e2a14; }}
    .box.sell {{ background: #3a1c1c; }}
    .box h2 {{ margin: 0 0 10px; font-size: 24px; }}
    .box.buy h2 {{ color: #7dcea0; }}
    .box.wait h2 {{ color: #f7dc6f; }}
    .box.sell h2 {{ color: #f1948a; }}
    .box ol {{ margin: 0; padding-left: 1.2em; }}
    .box li {{ margin: 4px 0; font-size: 20px; }}
    .box li span {{ color: #ddd; margin-left: 8px; }}
    .rank-wrap {{ max-width: 1100px; margin: 0 auto; }}
    table.rank {{ width: 100%; border-collapse: collapse; }}
    table.rank th, table.rank td {{ border-bottom: 1px solid #444; padding: 12px 8px; text-align: right; font-size: 18px; }}
    table.rank th {{ color: #D8C0FF; text-align: center; }}
    table.rank td.code, table.rank td.name, table.rank th.code, table.rank th.name {{ text-align: left; }}
    table.rank td.code {{ font-weight: 700; }}
    table.rank tr.buy td.signal, table.rank td.buy {{ color: #7dcea0; font-weight: 700; }}
    table.rank tr.wait td.signal, table.rank td.wait {{ color: #f7dc6f; font-weight: 700; }}
    table.rank tr.sell td.signal, table.rank td.sell {{ color: #f1948a; font-weight: 700; }}
    table.rank tr.buy {{ background: #10261c; }}
    table.rank tr.wait {{ background: #2a2610; }}
    table.rank tr.sell {{ background: #2a1616; }}
    table.rank tr.miss td {{ color: #888; }}
    @media (max-width: 800px) {{
      h1 {{ font-size: 26px; }}
      .summary {{ grid-template-columns: 1fr; }}
      table.rank thead {{ display: none; }}
      table.rank, table.rank tbody, table.rank tr, table.rank td {{ display: block; width: 100%; }}
      table.rank tr {{ border: 1px solid #444; border-radius: 10px; margin: 0 0 12px; padding: 8px; }}
      table.rank td {{ display: flex; justify-content: space-between; border: none; text-align: right; padding: 4px 0; }}
      table.rank td::before {{ content: attr(data-label); color: #D8C0FF; font-weight: 700; margin-right: 12px; }}
    }}
    #ma-chart {{ max-width: 1100px; margin: 0 auto; }}
    .ma-legend {{ font-size: 18px; }}
    .ma-legend i {{ display: inline-block; width: 28px; height: 4px; margin: 0 6px 0 14px; vertical-align: middle; }}
    .ma-legend i.ma50 {{ background: #9C27B0; }}
    .ma-legend i.ma200 {{ background: #E53935; }}
    .ma-legend i.mapx {{ background: #bbbbbb; }}
    #ma-canvas {{ width: 100%; height: 520px; background: #0c0c0c; border: 1px solid #333; }}
  </style>
</head>
<body>
  <div id="ma-chart" hidden>
    <p><a class="home" href="index.html">← 목록</a></p>
    <h1 id="ma-chart-title"></h1>
    <p class="ma-legend"><i class="ma50"></i>50일선 <i class="ma200"></i>200일선 <i class="mapx"></i>수정 종가</p>
    <canvas id="ma-canvas"></canvas>
  </div>
  <div id="report">
  <p><a class="home" href="../index.html">← 주가 방향 날씨</a></p>
  <p class="horizon">장타(몇년이내, 단 매일 시세 업데이트 확인 필요)</p>
  <h1>200일 이동평균 추세 장투 매매</h1>
  <p class="note">몇년안에 몇번 이하의 빈도의 장기 추세 매매를 할때만 적용합니다. 즉 시크리컬 경기 사이클 장투 추세 매매법입니다. 장기가격이 200일 이동평균 위에 있을 때만 매수(보유)하고, 아래로 내려오면 매도하고 현금으로 둡니다. 평일 미국장 마감 후 갱신됩니다. 기준일 {asof}. 매수·매도 추천이 아닙니다. 참조만 하세요.</p>
  <div class="glance">
    {"".join(summaries)}
  </div>
  <section class="rules">
    <h2>규칙</h2>
    <ol>
      <li>종목이나 지수(예: S&amp;P 500, 코스피)의 200일 단순이동평균을 계산합니다.</li>
      <li>매수: 종가가 200일선을 위로 돌파하고, 그 상태가 하루 이상 유지되면 매수합니다.</li>
      <li>보유: 가격이 200일선 위에 있는 동안 보유합니다.</li>
      <li>매도: 종가가 200일선 아래로 내려가면 전량 매도하고 현금으로 대기합니다.</li>
      <li>다시 위로 올라오면 같은 규칙으로 재진입합니다.</li>
    </ol>
  </section>
  <p class="formula">이격도 = 수정 종가 ÷ 200일 이동평균 × 100. 이격도 100 초과가 하루 더 유지되면 매수, 100 이하로 내려오면 매도입니다.</p>
  {"".join(tables)}
  </div>
  <script>window.MA_SERIES = {charts};</script>
  <script src="/Premium/weather/ma-chart.js"></script>
</body>
</html>
"""


def fund_items():
    items = []
    for ticker, label, name, currency, symbol in FUNDS:
        items.append({
            "ticker": ticker,
            "label": label,
            "name": name,
            "currency": currency,
            "symbol": symbol,
            "exchange": "",
        })
    return items


def main():
    session, crumb = yahoo_session()
    markets = [
        ("미국 시가총액 상위 20", load_us(session, crumb)),
        ("한국 시가총액 상위 20", load_korea()),
        ("일본 시가총액 상위 20", load_japan(session, crumb)),
    ]
    for title, items in markets:
        if len(items) < TOP_N:
            raise SystemExit(f"{title} 목록이 {len(items)}개뿐입니다.")
        print(title + ": " + ", ".join(display_code(item["ticker"]) for item in items), flush=True)
    groups = {"인덱스": score_items(fund_items(), strict=True)}
    for title, items in markets:
        groups[title] = score_items(items, strict=False)
    PAGE.write_text(render(groups), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
