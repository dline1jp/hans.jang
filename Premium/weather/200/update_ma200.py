# -*- coding: utf-8 -*-
"""Daily 200-day moving-average trend signals for the major index funds.

매수(보유): the latest daily close is above its 200-day simple moving average.
매도(현금): the latest daily close is at or below that average.
Both the close and the average use adjusted prices, so splits and dividends
do not break the line. A name flips only when today's side differs from
yesterday's side.
"""
import html
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGE = Path(__file__).with_name("index.html")
SMA = 200
TV_STUDIES = urllib.parse.quote(json.dumps([
    {"id": "MASimple@tv-basicstudies", "inputs": {"length": SMA}},
], separators=(",", ":")))
TV_OVERRIDES = urllib.parse.quote(json.dumps({
    "moving average.ma.color": "#E53935",
    "moving average.ma.linewidth": 2,
    "moving average.length": SMA,
}, separators=(",", ":")))

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


def chart_url(symbol):
    return (
        "https://www.tradingview.com/widgetembed/?symbol="
        + urllib.parse.quote(symbol, safe="")
        + "&interval=D&style=1&theme=dark&hideideas=1"
        + "&studies=" + TV_STUDIES
        + "&studies_overrides=" + TV_OVERRIDES
    )


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
            if len(bars) >= SMA + 1:
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
    ma = sma(closes, today)
    prev_ma = sma(closes, yesterday)
    close = closes[today]
    prev = closes[yesterday]
    above = close > ma
    prev_above = prev > prev_ma
    if above and not prev_above:
        change = "매수 전환"
    elif above:
        change = "보유 유지"
    elif prev_above:
        change = "매도 전환"
    else:
        change = "현금 유지"
    return {
        "date": bars[today]["date"],
        "close": close,
        "ma": ma,
        "disparity": close / ma * 100,
        "buy": above,
        "signal": "매수" if above else "매도",
        "change": change,
    }


def money(value, currency):
    if currency == "KRW":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def chip(row):
    return (
        f'<a href="{chart_url(row["symbol"])}" target="_blank">{html.escape(row["label"])}</a>'
        f'<span>{html.escape(row["name"])}</span>'
    )


def render(rows):
    buys = [row for row in rows if row["buy"]]
    sells = [row for row in rows if not row["buy"]]
    asof = max(row["date"] for row in rows)
    buy_html = "".join(f"<li>{chip(row)}</li>" for row in buys) or "<li>없음</li>"
    sell_html = "".join(f"<li>{chip(row)}</li>" for row in sells) or "<li>없음</li>"
    body = []
    for row in rows:
        side = "buy" if row["buy"] else "sell"
        body.append(
            f'<tr class="{side}">'
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
    return f"""<!DOCTYPE html>
<html>
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>200일 이동평균 매매 시그널</title>
  <style>
    body {{ background: #111; color: white; font-family: Arial, sans-serif; margin: 0; padding: 16px; }}
    a {{ color: #4da3ff; }}
    .home {{ color: #D8C0FF; font-size: 28px; text-decoration: none; }}
    h1 {{ text-align: center; color: #FFFFE0; font-size: 32px; line-height: 1.35; }}
    .note, .formula {{ color: #ccc; font-size: 18px; line-height: 1.5; max-width: 980px; margin: 8px auto; }}
    .formula {{ color: #8a8a8a; }}
    .summary {{ max-width: 980px; margin: 18px auto 28px; display: grid; gap: 14px; }}
    .box {{ border: 1px solid #444; border-radius: 12px; padding: 14px 16px; }}
    .box.buy {{ background: #143024; }}
    .box.sell {{ background: #3a1c1c; }}
    .box h2 {{ margin: 0 0 10px; font-size: 24px; }}
    .box.buy h2 {{ color: #7dcea0; }}
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
    table.rank tr.sell td.signal, table.rank td.sell {{ color: #f1948a; font-weight: 700; }}
    table.rank tr.buy {{ background: #10261c; }}
    table.rank tr.sell {{ background: #2a1616; }}
    @media (max-width: 800px) {{
      h1 {{ font-size: 26px; }}
      table.rank thead {{ display: none; }}
      table.rank, table.rank tbody, table.rank tr, table.rank td {{ display: block; width: 100%; }}
      table.rank tr {{ border: 1px solid #444; border-radius: 10px; margin: 0 0 12px; padding: 8px; }}
      table.rank td {{ display: flex; justify-content: space-between; border: none; text-align: right; padding: 4px 0; }}
      table.rank td::before {{ content: attr(data-label); color: #D8C0FF; font-weight: 700; margin-right: 12px; }}
    }}
  </style>
</head>
<body>
  <p><a class="home" href="../index.html">← 주가 방향 날씨</a></p>
  <h1>200일 이동평균 추세 매매</h1>
  <p class="note">가격이 200일 이동평균 위에 있을 때만 매수(보유)하고, 아래로 내려오면 매도하고 현금으로 둡니다. 평일 미국장 마감 후 갱신됩니다. 기준일 {asof}. 매수·매도 추천이 아닙니다. 참조만 하세요.</p>
  <p class="formula">이격도 = 수정 종가 ÷ 200일 이동평균 × 100. 이격도 100 초과가 매수, 100 이하가 매도입니다.</p>
  <section class="summary">
    <div class="box buy">
      <h2>매수 {len(buys)}개 · 200일선 위, 보유</h2>
      <ol>{buy_html}</ol>
    </div>
    <div class="box sell">
      <h2>매도 {len(sells)}개 · 200일선 아래, 현금</h2>
      <ol>{sell_html}</ol>
    </div>
  </section>
  <section class="rank-wrap">
    <table class="rank">
      <thead>
        <tr>
          <th class="code">코드</th><th class="name">종목</th><th>기준일</th><th>종가</th><th>200일선</th><th>이격도</th><th>시그널</th><th>변화</th>
        </tr>
      </thead>
      <tbody>
        {"".join(body)}
      </tbody>
    </table>
  </section>
</body>
</html>
"""


def main():
    rows = []
    failed = []
    for ticker, label, name, currency, symbol in FUNDS:
        bars = daily_closes(ticker)
        if not bars:
            failed.append(label)
            print(f"FAIL {label}", file=sys.stderr)
            continue
        row = judge(bars)
        row.update({"label": label, "name": name, "currency": currency, "symbol": symbol})
        rows.append(row)
        print(f"{label} {row['date']} {row['signal']} {row['disparity']:.1f} {row['change']}")
        time.sleep(0.25)
    if failed:
        raise SystemExit("시세를 받지 못했습니다: " + ", ".join(failed))
    PAGE.write_text(render(rows), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()

