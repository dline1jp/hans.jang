# -*- coding: utf-8 -*-
"""Fujimoto ladder: buys versus the reference price, sells versus average cost.

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
CUTOFF = "2026-11-22"
SYMBOLS = [
    ("SPY", "SPY", "미국 S&P 500"),
    ("QQQ", "QQQ", "미국 나스닥 100"),
    ("226490.KS", "226490", "KODEX 코스피"),
]
SELLS = (
    (0.25, 0.10, "10% 매도"),
    (0.35, 0.20, "20% 매도"),
    (0.45, 0.30, "30% 매도"),
    (0.60, 0.40, "40% 매도"),
)


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
    if not rows:
        raise RuntimeError(f"no bars for {ticker}")
    return rows, dividends


def buy_rungs(drop):
    """15% down buys 10% of the frozen account. From 25% down, buy the same percent."""
    if drop + 1e-9 < 0.15:
        return []
    levels = [(0.15, 0.10)]
    step = 0.25
    while step <= drop + 1e-9:
        levels.append((round(step, 10), round(step, 10)))
        step += 0.10
    return levels


def run(rows, dividends):
    cash = START_CASH
    shares = 0.0
    cost = 0.0
    ref_price = rows[0]["close"]
    ref_kind = "시작"
    frozen = START_CASH
    buy_done = set()
    sell_done = set()
    skip_next = False
    curve = []
    last = None

    def equity(price):
        return cash + shares * price

    def buy(price, dollars):
        nonlocal cash, shares, cost
        dollars = min(dollars, cash)
        if dollars <= 1e-8:
            return 0.0
        shares += dollars / price
        cost += dollars
        cash -= dollars
        return dollars

    def sell(price, qty):
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
        sold_all_today = False
        skipped_today = False
        if shares > 0 and day in dividends:
            payout = shares * dividends[day]
            if payout > 0:
                shares += payout / price
                cost += payout
        if shares > 0 and cost > 0:
            avg = cost / shares
            ret = price / avg - 1.0
            if ret <= 0:
                sell_done = set()
            elif ret >= 0.25:
                for threshold, fraction, label in SELLS:
                    if ret >= threshold and threshold not in sell_done and shares > 0:
                        if sell(price, shares * fraction):
                            actions.append(label)
                        sell_done.add(threshold)
                if ret >= 1.0 and shares > 0:
                    if sell(price, shares):
                        actions.append("전량 매도")
                    sell_done.add(1.0)
            if shares == 0:
                ref_price = price
                ref_kind = "매도"
                frozen = cash
                buy_done = set()
                sell_done = set()
                sold_all_today = True
                skip_next = True
        if sold_all_today:
            pass
        elif skip_next:
            skip_next = False
            skipped_today = True
        else:
            drop = 1.0 - price / ref_price
            for rung, portion in buy_rungs(drop):
                if rung in buy_done:
                    continue
                spent = buy(price, frozen * portion)
                buy_done.add(rung)
                if spent > 0:
                    actions.append(f"{portion * 100:.0f}% 매수")
        curve.append(equity(price))
        last = {
            "date": day,
            "price": price,
            "shares": shares,
            "cost": cost,
            "cash": cash,
            "actions": actions,
            "ref_price": ref_price,
            "ref_kind": ref_kind,
            "sell_done": set(sell_done),
            "buy_done": set(buy_done),
            "skipped": skipped_today,
        }
    return curve, last


def judgment(state):
    price = state["price"]
    ref = state["ref_price"]
    ref_name = "시작 종가" if state["ref_kind"] == "시작" else "매도가"
    gap = price / ref - 1.0
    actions = state["actions"]
    buys = [item for item in actions if item.endswith("매수")]
    sells = [item for item in actions if "매도" in item]
    if state["shares"] > 0 and state["cost"] > 0:
        avg = state["cost"] / state["shares"]
        versus = price / avg - 1.0
        base = (
            f"종가 {fmt_price(price)}, 평단 {fmt_price(avg)}, 평단 대비 {versus * 100:+.1f}%. "
            f"{ref_name} {fmt_price(ref)}, 기준가 대비 {gap * 100:+.1f}%."
        )
    else:
        base = f"종가 {fmt_price(price)}, {ref_name} {fmt_price(ref)}, 기준가 대비 {gap * 100:+.1f}%."
        avg = None
        versus = None
    if "전량 매도" in sells:
        return "전량 매도", "sell", base + " 평단 대비 100% 이상이라 남은 수량을 모두 팔았습니다. 다음 거래일에는 사지 않습니다."
    if sells:
        return sells[-1], "sell", base + f" 평단 상승 구간이라 {sells[-1]}를 실행했습니다."
    if buys:
        extra = ""
        if len(buys) > 1:
            extra = " 같은 날 " + ", ".join(buys[:-1]) + "도 먼저 했습니다."
        return buys[-1], "buy", base + f" 기준가 하락 구간이라 {buys[-1]}를 실행했습니다." + extra
    if state["shares"] <= 0:
        if state.get("skipped"):
            return "매수 대기", "hold", base + " 전량 매도 다음 거래일이라 사지 않습니다."
        return "매수 대기", "hold", base + " 15% 하락 전에는 사지 않습니다. 현금으로 기다립니다."
    if versus <= 0:
        return "보유", "hold", base + " 평단 아래라 매도하지 않습니다. 매수는 기준가 하락 구간에서만 합니다."
    if versus < 0.25:
        return "보유", "hold", base + " 평단 대비 25% 상승 전에는 팔지 않아 보유입니다."
    done = [label for threshold, _, label in SELLS if versus >= threshold and threshold in state["sell_done"]]
    if 1.0 in state["sell_done"]:
        done.append("전량 매도")
    if done:
        return "보유", "hold", base + f" {done[-1]}는 이번 상승에서 이미 실행했습니다. 평단으로 돌아오기 전에는 같은 매도를 반복하지 않습니다."
    return "보유", "hold", base + " 보유입니다."


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
            late = f" 상장일이 {item['started']}라 그날 종가를 기준가로 두고 전액 현금에서 시작했습니다."
        cards.append(
            f'<article class="signal {kind}">'
            f'<h2>{html.escape(item["label"])} <span>{html.escape(item["code"])}</span></h2>'
            f'<p class="badge">{html.escape(label)}</p>'
            f'<p class="split">현금 보유 {item["cash_pct"]:.1f}% · 투자(주식) {item["invest_pct"]:.1f}%</p>'
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
    .split {{ margin: 0 0 8px; color: #fff; font-size: 20px; font-weight: 700; }}
    table {{ max-width: 980px; width: 100%; margin: 8px auto 16px; border-collapse: collapse; }}
    table.ladder {{ max-width: 720px; margin: 12px 0 18px; }}
    table.ladder th, table.ladder td {{ text-align: left; }}
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
  <p class="note">투자 권유가 아닙니다. 기준 시각 {html.escape(stamped)}. 2026-11-22는 일요일이라 그 이전 마지막 거래일 종가까지입니다.</p>
  <p class="note">처음에는 전액 현금입니다. 시작 종가나 전량 매도가보다 15% 내릴 때 그 기준 계좌의 10%를 사고, 더 내리면 같은 기준 금액으로 25%, 35%, 45%를 삽니다. 전량 매도 다음 거래일에는 사지 않습니다. 현금이 남으면 그대로 둡니다.</p>
  <h2 class="sec">지금 판단</h2>
  <div class="signals">
    {''.join(cards)}
  </div>
  <h2 class="sec">매매법 개요</h2>
  <div class="rules">
    <p>보유 중 매도와 보유는 평단 기준입니다. 배당은 그날 종가로 다시 사서 평단에 넣습니다. 같은 매도 구간은 평단으로 돌아오기 전에 한 번만 실행합니다.</p>
    <table class="ladder">
      <thead><tr><th>평단 대비</th><th>행동</th></tr></thead>
      <tbody>
        <tr><td>5~15% 상승</td><td>보유</td></tr>
        <tr><td>25% 상승</td><td>보유 수량의 10% 매도</td></tr>
        <tr><td>35% 상승</td><td>20% 매도</td></tr>
        <tr><td>45% 상승</td><td>30% 매도</td></tr>
        <tr><td>60% 상승</td><td>40% 매도</td></tr>
        <tr><td>100% 상승</td><td>전량 매도</td></tr>
      </tbody>
    </table>
    <p>매수는 평단이 아니라 기준가 대비입니다. 첫 기준가는 시작 종가이고, 전량 매도 뒤에는 그 매도가입니다. 전량 매도 다음 날에는 사지 않습니다. 현금이 남으면 그대로 둡니다. 각 구간은 그 기준가마다 한 번입니다.</p>
    <table class="ladder">
      <thead><tr><th>매도점(기준가) 대비</th><th>행동</th></tr></thead>
      <tbody>
        <tr><td>15% 하락</td><td>계좌의 10% 매수</td></tr>
        <tr><td>25% 하락</td><td>25% 매수</td></tr>
        <tr><td>35% 하락</td><td>35% 매수</td></tr>
        <tr><td>45% 하락</td><td>45% 매수</td></tr>
        <tr><td>이후 10%포인트마다</td><td>하락폭과 같은 비율 매수</td></tr>
        <tr><td>전량 매도 다음 날</td><td>사지 않음</td></tr>
        <tr><td>현금이 남으면</td><td>그대로 둠</td></tr>
      </tbody>
    </table>
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
        rows, dividends = fetch(ticker)
        curve, state = run(rows, dividends)
        label_text, kind, reason = judgment(state)
        end = curve[-1]
        stock_value = state["shares"] * state["price"]
        account = stock_value + state["cash"]
        results.append({
            "code": code,
            "label": label,
            "started": rows[0]["date"].isoformat(),
            "ended": rows[-1]["date"].isoformat(),
            "return_pct": (end / START_CASH - 1.0) * 100.0,
            "multiple": end / START_CASH,
            "cash_pct": 100.0 * state["cash"] / account,
            "invest_pct": 100.0 * stock_value / account,
            "signal": (label_text, kind, reason),
            "curve": [value / START_CASH * 100.0 for value in curve],
        })
        print(
            code,
            results[-1]["started"],
            results[-1]["ended"],
            f'{results[-1]["return_pct"]:.1f}%',
            label_text,
            f'cash {results[-1]["cash_pct"]:.1f}%',
            f'invest {results[-1]["invest_pct"]:.1f}%',
        )
        print(reason)
    stamped = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    PAGE.write_text(page(results, stamped), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
