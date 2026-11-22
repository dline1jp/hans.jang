# -*- coding: utf-8 -*-
"""Fujimoto Shigeru ladder on SPY, QQQ, and KODEX KOSPI, dividends reinvested.

Weekday update after the US cash close:

    python Premium/weather/fujimoto/update_fujimoto.py
"""
import html
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
PAGE = Path(__file__).with_name("index.html")
KST = timezone(timedelta(hours=9))
START_CASH = 10000.0
# Initial stake I, then +10% of cost, then +25% of the new cost => 1.375 I.
RESERVE = 1.375
CUTOFF = "2026-11-22"
SYMBOLS = [
    ("SPY", "SPY", "미국 S&P 500"),
    ("QQQ", "QQQ", "미국 나스닥 100"),
    ("226490.KS", "226490", "KODEX 코스피"),
]
SELLS = ((0.25, 0.10, "10% 매도"), (0.35, 0.20, "20% 매도"), (0.45, 0.30, "30% 매도"), (0.60, 0.40, "40% 매도"))


def fetch(ticker):
    start = int(datetime(1999, 12, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 11, 24, tzinfo=timezone.utc).timestamp())
    url = CHART.format(ticker=urllib.parse.quote(ticker, safe=".-"))
    query = urllib.parse.urlencode({
        "period1": start,
        "period2": end,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    })
    request = urllib.request.Request(url + "?" + query, headers={"User-Agent": "Mozilla/5.0"})
    payload = json.load(urllib.request.urlopen(request, timeout=60))
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"no prices for {ticker}")
    block = result[0]
    stamps = block.get("timestamp") or []
    closes = ((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    rows = []
    for stamp, close in zip(stamps, closes):
        if not isinstance(close, (int, float)) or close <= 0:
            continue
        day = datetime.fromtimestamp(stamp, timezone.utc).date()
        if day.isoformat() < "2000-01-01" or day.isoformat() > CUTOFF:
            continue
        rows.append({"date": day, "close": float(close)})
    dividends = {}
    events = (block.get("events") or {}).get("dividends") or {}
    for item in events.values():
        day = datetime.fromtimestamp(item["date"], timezone.utc).date()
        dividends[day] = dividends.get(day, 0.0) + float(item["amount"])
    name = ((block.get("meta") or {}).get("shortName") or (block.get("meta") or {}).get("longName") or ticker)
    if not rows:
        raise RuntimeError(f"no bars for {ticker}")
    return rows, dividends, name


def run(rows, dividends):
    cash = START_CASH
    shares = 0.0
    cost = 0.0
    did15 = False
    did25 = False
    sold = set()
    curve = []
    last = None

    def equity(price):
        return cash + shares * price

    def buy(dollars):
        nonlocal cash, shares, cost
        dollars = min(dollars, cash)
        if dollars <= 1e-8:
            return 0.0
        shares += dollars / price
        cost += dollars
        cash -= dollars
        return dollars

    def sell(qty):
        nonlocal cash, shares, cost
        qty = min(max(qty, 0.0), shares)
        if qty <= 1e-10:
            return 0.0
        cash += qty * price
        cost = 0.0 if qty >= shares - 1e-10 else cost * (shares - qty) / shares
        shares -= qty
        if shares <= 1e-8:
            shares = 0.0
            cost = 0.0
        return qty

    for row in rows:
        price = row["close"]
        day = row["date"]
        actions = []
        if shares > 0 and day in dividends:
            payout = shares * dividends[day]
            if payout > 0 and price > 0:
                shares += payout / price
                cost += payout
        if shares == 0:
            bought = buy(equity(price) / RESERVE)
            did15 = did25 = False
            sold = set()
            if bought:
                actions.append("시작 매수")
        else:
            avg = cost / shares
            ret = price / avg - 1.0
            if ret <= 0:
                sold = set()
            if ret >= 0:
                did15 = did25 = False
            if ret <= -0.15 and not did15:
                if buy(0.10 * cost):
                    actions.append("10% 매수")
                did15 = True
                avg = cost / shares
                ret = price / avg - 1.0
            if ret <= -0.25 and not did25 and shares > 0:
                if buy(0.25 * cost):
                    actions.append("25% 매수")
                did25 = True
                avg = cost / shares
                ret = price / avg - 1.0
            if shares > 0 and ret >= 0.25:
                for threshold, fraction, label in SELLS:
                    if ret >= threshold and threshold not in sold and shares > 0:
                        if sell(shares * fraction):
                            actions.append(label)
                        sold.add(threshold)
                if ret >= 1.0 and shares > 0:
                    if sell(shares):
                        actions.append("전량 매도")
                    sold.add(1.0)
        curve.append(equity(price))
        last = {
            "date": day,
            "price": price,
            "shares": shares,
            "cost": cost,
            "cash": cash,
            "actions": actions,
            "did15": did15,
            "did25": did25,
            "sold": set(sold),
        }
    return curve, last


def judgment(state):
    price = state["price"]
    if state["shares"] <= 0 or state["cost"] <= 0:
        if "전량 매도" in state["actions"]:
            text = f"종가 {fmt_price(price)}가 평단의 2배에 닿아 남은 수량을 모두 팔았습니다."
            return "전량 매도", "sell", text
        if "시작 매수" in state["actions"]:
            text = f"보유가 없어 종가 {fmt_price(price)}에 다시 시작 매수했습니다. 추가 매수 현금은 남겨 둡니다."
            return "시작 매수", "buy", text
        return "보유", "hold", "보유 수량이 없습니다."
    avg = state["cost"] / state["shares"]
    move = price / avg - 1.0
    pct = f"{move * 100:+.1f}%"
    base = f"종가 {fmt_price(price)}, 평단 {fmt_price(avg)}, 평단 대비 {pct}."
    actions = state["actions"]
    if "25% 매수" in actions:
        extra = " 같은 날 15% 하락 구간에서 투자금의 10%도 먼저 샀습니다." if "10% 매수" in actions else ""
        return "25% 매수", "buy", base + " 25% 이상 하락이라 투자금의 25%를 추가 매수했습니다." + extra
    if "10% 매수" in actions:
        return "10% 매수", "buy", base + " 15% 이상 하락이라 투자금의 10%를 추가 매수했습니다."
    sell_labels = [label for _, _, label in SELLS if label in actions]
    if "전량 매도" in actions:
        return "전량 매도", "sell", base + " 100% 이상 상승이라 남은 수량을 모두 팔았습니다."
    if sell_labels:
        return sell_labels[-1], "sell", base + f" 해당 상승 구간이라 {sell_labels[-1]}를 실행했습니다."
    if move <= -0.25 and state["did25"]:
        return "보유", "hold", base + " 25% 하락 추가매수는 이번 하락에서 이미 했습니다. 평단으로 돌아오기 전에는 다시 사지 않습니다."
    if move <= -0.15 and state["did15"]:
        return "보유", "hold", base + " 15% 하락 추가매수는 이미 했고, 25% 하락에는 아직 닿지 않았습니다."
    if move <= -0.05:
        return "보유", "hold", base + " 15% 하락 전에는 추가 매수하지 않습니다. 5% 하락은 그대로 둡니다."
    if move < 0:
        return "보유", "hold", base + " 하락폭이 5%보다 작아 보유입니다."
    if 0.05 <= move < 0.25:
        return "보유", "hold", base + " 25% 상승 전에는 팔지 않아 보유입니다."
    if move < 0.05:
        return "보유", "hold", base + " 상승폭이 5%보다 작아 보유입니다."
    done = []
    for threshold, _, label in SELLS:
        if move >= threshold and threshold in state["sold"]:
            done.append(label)
    if 1.0 in state["sold"] or state["shares"] == 0:
        done.append("전량 매도")
    if done:
        return "보유", "hold", base + f" {done[-1]}는 이번 상승에서 이미 실행했습니다. 다음 구간 전에는 보유입니다."
    return "보유", "hold", base + " 매수·매도 구간 밖이라 보유입니다."


def fmt_price(value):
    if value >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def polyline(values, width, height, pad):
    if not values:
        return ""
    low = min(values)
    high = max(values)
    if high == low:
        high += 1.0
    step = max(1, len(values) // 420)
    picked = list(range(0, len(values), step))
    if picked[-1] != len(values) - 1:
        picked.append(len(values) - 1)
    points = []
    span = max(1, len(values) - 1)
    for index in picked:
        x = pad + (width - 2 * pad) * index / span
        y = pad + (height - 2 * pad) * (high - values[index]) / (high - low)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def page(results, stamped):
    cards = []
    for item in results:
        label, kind, reason = item["signal"]
        late = ""
        if item["started"] != "2000-01-03":
            late = f" 상장 전이라 {item['started']}부터 계산했습니다."
        cards.append(
            f'<article class="signal {kind}">'
            f'<h2>{html.escape(item["label"])} <span>{html.escape(item["code"])}</span></h2>'
            f'<p class="badge">{html.escape(label)}</p>'
            f'<p>{html.escape(reason)}{html.escape(late)}</p>'
            f'</article>'
        )
    rows = []
    for item in results:
        rows.append(
            "<tr>"
            f'<td>{html.escape(item["label"])}</td>'
            f'<td>{html.escape(item["code"])}</td>'
            f'<td>{html.escape(item["started"])}</td>'
            f'<td>{html.escape(item["ended"])}</td>'
            f'<td>{item["return_pct"]:+.1f}%</td>'
            f'<td>{item["multiple"]:.2f}배</td>'
            "</tr>"
        )
    width, height, pad = 760, 280, 28
    colors = {"SPY": "#7dcea0", "QQQ": "#4da3ff", "226490": "#f7dc6f"}
    lines = []
    for item in results:
        points = polyline(item["curve"], width, height, pad)
        lines.append(
            f'<polyline fill="none" stroke="{colors[item["code"]]}" stroke-width="2" points="{points}"/>'
        )
    legend = " · ".join(
        f'<span style="color:{colors[item["code"]]}">{html.escape(item["code"])}</span>' for item in results
    )
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>후지모토 시게루 타점</title>
  <style>
    body {{ background: #111; color: #fff; font-family: "Malgun Gothic", "Apple SD Gothic Neo", Arial, sans-serif; margin: 0; padding: 16px; }}
    a {{ color: #4da3ff; }}
    .home {{ color: #D8C0FF; font-size: 28px; text-decoration: none; }}
    h1 {{ text-align: center; color: #FFFFE0; font-size: 32px; line-height: 1.35; }}
    .note, .rules {{ max-width: 980px; margin: 8px auto; color: #ccc; font-size: 18px; line-height: 1.55; }}
    .signals {{ max-width: 980px; margin: 12px auto; display: grid; grid-template-columns: 1fr; gap: 12px; }}
    .signal {{ border: 1px solid #444; border-radius: 12px; padding: 14px 16px; background: #181818; }}
    .signal h2 {{ margin: 0 0 6px; font-size: 22px; }}
    .signal h2 span {{ color: #D8C0FF; font-size: 16px; margin-left: 6px; }}
    .badge {{ margin: 0 0 8px; font-size: 28px; font-weight: 800; }}
    .signal.buy .badge {{ color: #7dcea0; }}
    .signal.sell .badge {{ color: #f1948a; }}
    .signal.hold .badge {{ color: #f7dc6f; }}
    .signal p {{ margin: 0; color: #ddd; font-size: 18px; line-height: 1.5; }}
    table {{ max-width: 980px; width: 100%; margin: 8px auto 16px; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #333; padding: 10px 8px; text-align: right; font-size: 18px; }}
    th {{ color: #D8C0FF; }}
    td:first-child, th:first-child, td:nth-child(2), th:nth-child(2) {{ text-align: left; }}
    svg {{ width: min(980px, 100%); height: auto; display: block; margin: 0 auto; background: #0c0c0c; border: 1px solid #333; border-radius: 8px; }}
    .legend {{ max-width: 980px; margin: 8px auto; color: #ccc; }}
    h2.sec {{ max-width: 980px; margin: 22px auto 8px; color: #FFFFE0; font-size: 24px; }}
    @media (max-width: 800px) {{
      h1 {{ font-size: 26px; }}
      .badge {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
  <p><a class="home" href="/Premium/weather/index.html">← 주가 방향 날씨</a></p>
  <h1>후지모토 시게루 타점</h1>
  <p class="note">투자 권유가 아닙니다. 기준 시각 {html.escape(stamped)}. 퍼센트는 평단 대비이고, 배당은 종가로 재투자했습니다. 2026-11-22는 일요일이라 그 이전 마지막 거래일 종가까지입니다.</p>
  <h2 class="sec">지금 판단</h2>
  <div class="signals">
    {''.join(cards)}
  </div>
  <h2 class="sec">매매법 개요</h2>
  <div class="rules">
    <p>후지모토 시게루의 가격 규칙은 평단을 기준으로 내리면 나눠 사고, 오르면 나눠 파는 것입니다. 5% 하락은 그대로 둡니다. 15% 하락이면 그때 투자금의 10%를 더 사고, 25% 하락이면 투자금의 25%를 더 삽니다. 5%에서 15% 사이 상승은 보유입니다. 25% 상승에 보유 수량의 10%, 35%에 20%, 45%에 30%, 60%에 40%를 팔고, 100% 상승이면 남은 수량을 모두 팝니다.</p>
    <p>같은 구간은 한 번만 실행합니다. 가격이 평단으로 돌아오면 그 구간을 다시 켭니다. 보유가 없으면 다음 거래일에 전체 자금의 약 72.7%로 다시 시작합니다. 나머지는 15%와 25% 추가 매수 현금입니다. 현금이 모자라면 있는 만큼만 삽니다. 배당금은 그 날 종가로 같은 종목을 더 사서 평단에 반영합니다. 수수료는 없습니다.</p>
  </div>
  <h2 class="sec">배당 재투자 누적 수익률</h2>
  <table>
    <thead><tr><th>종목</th><th>코드</th><th>시작</th><th>끝</th><th>누적 수익률</th><th>배수</th></tr></thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <p class="legend">평가액 추이. 시작을 100으로 두었습니다. {legend}</p>
  <svg viewBox="0 0 {width} {height}" role="img" aria-label="평가액 추이">
    <line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#555"/>
    {''.join(lines)}
  </svg>
  <p class="note">평일 미국장 마감 후 <code>python Premium/weather/fujimoto/update_fujimoto.py</code>로 갱신합니다.</p>
</body>
</html>
'''


def main():
    results = []
    for ticker, code, label in SYMBOLS:
        rows, dividends, _market_name = fetch(ticker)
        curve, state = run(rows, dividends)
        label_text, kind, reason = judgment(state)
        end = curve[-1]
        results.append({
            "code": code,
            "label": label,
            "started": rows[0]["date"].isoformat(),
            "ended": rows[-1]["date"].isoformat(),
            "return_pct": (end / START_CASH - 1.0) * 100.0,
            "multiple": end / START_CASH,
            "signal": (label_text, kind, reason),
            "curve": [value / START_CASH * 100.0 for value in curve],
        })
        print(code, results[-1]["started"], results[-1]["ended"], f'{results[-1]["return_pct"]:.1f}%', label_text)
        print(reason)
    stamped = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    PAGE.write_text(page(results, stamped), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
