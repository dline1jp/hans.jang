# -*- coding: utf-8 -*-
"""TQQQ 무한매수법(라오어 v2.2) 페이지를 매일 갱신합니다.

- 야후 파이낸스 TQQQ 일봉(5년)을 읽어 v2.2 규칙으로 사이클을 시뮬레이션합니다.
- 시드 $10,000 / 40분할 / 2024-01-02 시작 기준입니다.
- 결과를 Premium/weather/muhan/index.html 의 MUHAN_DATA 로 심고 기준일 안내문을 갱신합니다.
- GitHub Actions(.github/workflows/update-muhan.yml)에서 미국장 마감 후 실행합니다.

v2.2 규칙 요약
- 1회 매수금 = 시드 / 40
- T = 누적 매수금 / 1회 매수금 (소수 첫째 자리까지 올림)
- 전반전(T<20): 1회분의 1/2은 평단, 1/2은 평단*(1+(10-T/2)/100) LOC 매수
- 후반전(T>=20): 1회분 전체를 평단*(1+(10-T/2)/100) LOC 매수
- 매도: 보유 1/4을 같은 기준가에 LOC 매도, 3/4을 평단+10% 지정가 매도
- 전량 매도되면 사이클 종료 후 같은 1회 매수금으로 새 사이클 시작(단리)
"""
import datetime
import json
import math
import pathlib
import re
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "index.html"
SUMMARY = HERE / "muhan-summary.js"

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/TQQQ"
HEADERS = {"User-Agent": "Mozilla/5.0"}
RANGE = "5y"
SEED = 10000.0
ROUNDS = 40
UNIT = SEED / ROUNDS
START = "2024-01-02"
VERSION = "v2.2"
CHART_BARS = 620


def daily_bars():
    """TQQQ 일봉 종가를 [(date, close), ...] 로 돌려줍니다."""
    for attempt in range(4):
        try:
            response = requests.get(
                CHART_URL,
                params={"interval": "1d", "range": RANGE, "events": "div,splits"},
                headers=HEADERS,
                timeout=30,
            )
            if response.status_code in (429, 500, 502, 503):
                time.sleep(1.4 * (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json()
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                time.sleep(0.8 * (attempt + 1))
                continue
            stamps = result[0].get("timestamp") or []
            close = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            bars = []
            for index, stamp in enumerate(stamps):
                value = close[index] if index < len(close) else None
                if not isinstance(value, (int, float)):
                    continue
                bar_date = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).date()
                bars.append((bar_date, round(float(value), 4)))
            if len(bars) >= 100:
                return bars
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(0.8 * (attempt + 1))
    return None


def t_value(cash_used):
    """누적 매수금 기준 T값. 소수 첫째 자리까지 올림합니다."""
    return math.ceil((cash_used / UNIT) * 10 - 1e-9) / 10.0


def star_percent(t_value_now):
    """평단 대비 매수/매도 기준 퍼센트 (10 - T/2)."""
    return 10.0 - t_value_now / 2.0

def simulate(bars):
    data = [bar for bar in bars if bar[0].isoformat() >= START]
    if len(data) < 20:
        return None

    cash_used = 0.0
    shares = 0.0
    avg = 0.0
    cycle = 1
    realized = 0.0
    max_t = 0.0
    buy_count = 0
    sell_count = 0
    cycle_start = None
    cycle_trades = []
    avg_by_day = {}

    for day, close in data:
        if shares <= 1e-9:
            amount = min(UNIT, SEED - cash_used)
            if amount > 1e-6:
                shares = amount / close
                cash_used += amount
                avg = cash_used / shares
                cycle_start = day
                buy_count += 1
                cycle_trades.append({
                    "date": day.isoformat(),
                    "type": "buy",
                    "price": round(close, 2),
                    "shares": round(shares, 3),
                })
            avg_by_day[day] = avg
            continue

        t_now = t_value(cash_used)
        star = star_percent(t_now)
        basis_price = avg * (1 + star / 100.0)
        target_price = avg * 1.10

        if t_now < 20:
            buy_orders = [(avg, UNIT / 2.0), (basis_price, UNIT / 2.0)]
        else:
            buy_orders = [(basis_price, UNIT)]

        qty_first = shares / 4.0
        qty_rest = shares * 3.0 / 4.0
        sold_all = False
        for qty, price in ((qty_first, basis_price), (qty_rest, target_price)):
            if qty <= 1e-9 or close < price:
                continue
            basis = qty * avg
            realized += qty * close - basis
            cash_used -= basis
            shares -= qty
            sell_count += 1
            cycle_trades.append({
                "date": day.isoformat(),
                "type": "sell",
                "price": round(close, 2),
                "shares": round(qty, 3),
            })
            if shares <= 1e-6:
                sold_all = True
                break

        if sold_all:
            shares = 0.0
            cash_used = 0.0
            avg = 0.0
            cycle += 1
            cycle_start = None
            cycle_trades = []
            avg_by_day[day] = None
            continue

        avg = cash_used / shares if shares > 1e-9 else 0.0
        if shares > 1e-9:
            max_t = max(max_t, t_value(cash_used))

        for price, amount in buy_orders:
            if cash_used >= SEED - 1e-6:
                break
            if close > price:
                continue
            amount = min(amount, SEED - cash_used)
            if amount <= 1e-6:
                break
            shares += amount / close
            cash_used += amount
            buy_count += 1
            cycle_trades.append({
                "date": day.isoformat(),
                "type": "buy",
                "price": round(close, 2),
                "shares": round(amount / close, 3),
            })

        if shares > 1e-9:
            avg = cash_used / shares
            max_t = max(max_t, t_value(cash_used))
            avg_by_day[day] = avg
        else:
            cycle += 1
            cash_used = 0.0
            avg = 0.0
            cycle_start = None
            cycle_trades = []
            avg_by_day[day] = None

    last_day, last_close = data[-1]
    t_now = t_value(cash_used) if shares > 1e-9 else 0.0
    unrealized = shares * last_close - cash_used
    total = realized + unrealized

    chart_data = data[-CHART_BARS:]
    chart_dates = [day.isoformat() for day, _close in chart_data]
    chart_closes = [round(close, 2) for _day, close in chart_data]
    chart_avg = []
    for day, _close in chart_data:
        value = avg_by_day.get(day)
        if cycle_start is not None and day >= cycle_start and value:
            chart_avg.append(round(value, 2))
        else:
            chart_avg.append(None)

    return {
        "asof": last_day.isoformat(),
        "lastClose": round(last_close, 2),
        "start": START,
        "seed": SEED,
        "rounds": ROUNDS,
        "unit": UNIT,
        "version": VERSION,
        "cycleNo": cycle,
        "T": round(t_now, 1),
        "phase": "전반전" if t_now < 20 else "후반전",
        "star": round(star_percent(t_now), 2) if shares > 1e-9 else 10.0,
        "avg": round(avg, 2) if shares > 1e-9 else 0.0,
        "shares": round(shares, 2),
        "invested": round(cash_used, 2),
        "cashLeft": round(SEED - cash_used, 2),
        "realized": round(realized, 2),
        "unrealized": round(unrealized, 2),
        "total": round(total, 2),
        "returnPct": round(total / SEED * 100.0, 2),
        "maxT": round(max_t, 1),
        "buyCount": buy_count,
        "sellCount": sell_count,
        "cycleStart": cycle_start.isoformat() if cycle_start else "",
        "targetPrice": round(avg * 1.10, 2) if shares > 1e-9 else 0.0,
        "chart": {
            "dates": chart_dates,
            "closes": chart_closes,
            "avg": chart_avg,
        },
        "trades": cycle_trades[-80:],
    }

def make_orders(state):
    orders = []
    if state["shares"] <= 1e-9:
        price = state["lastClose"]
        amount = round(min(UNIT, state["cashLeft"]), 2)
        orders.append({
            "type": "buy",
            "label": "신규 사이클 첫 매수",
            "price": price,
            "amount": amount,
            "shares": round(amount / price, 2),
            "note": "사이클 시작일 종가 기준 1회분 매수(참고가)",
        })
        return orders

    t_now = state["T"]
    avg = state["avg"]
    star = state["star"]
    basis_price = round(avg * (1 + star / 100.0), 2)
    target_price = round(avg * 1.10, 2)
    cash_left = state["cashLeft"]

    if t_now < 20:
        first_amount = round(min(UNIT / 2.0, cash_left), 2)
        if first_amount > 0.01:
            orders.append({
                "type": "buy",
                "label": "LOC 매수 1/2",
                "price": round(avg, 2),
                "amount": first_amount,
                "shares": round(first_amount / avg, 2),
                "note": "종가가 지정가 이하이면 종가 체결",
            })
        cash_left -= first_amount
        second_amount = round(min(UNIT / 2.0, cash_left), 2)
        if second_amount > 0.01:
            orders.append({
                "type": "buy",
                "label": "LOC 매수 2/2",
                "price": basis_price,
                "amount": second_amount,
                "shares": round(second_amount / basis_price, 2),
                "note": "평단 대비 %+.1f%% LOC" % star,
            })
    else:
        amount = round(min(UNIT, cash_left), 2)
        if amount > 0.01:
            orders.append({
                "type": "buy",
                "label": "LOC 매수",
                "price": basis_price,
                "amount": amount,
                "shares": round(amount / basis_price, 2),
                "note": "평단 대비 %+.1f%% LOC" % star,
            })

    orders.append({
        "type": "sell",
        "label": "LOC 매도 1/4",
        "price": basis_price,
        "shares": round(state["shares"] / 4.0, 2),
        "note": "평단 대비 %+.1f%% (후반전은 손실 구간일 수 있음)" % star,
    })
    orders.append({
        "type": "sell",
        "label": "지정가 매도 3/4",
        "price": target_price,
        "shares": round(state["shares"] * 3.0 / 4.0, 2),
        "note": "평단 +10% 목표",
    })
    return orders


def series_json(state):
    body = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    return "  <script>window.MUHAN_DATA = %s;</script>" % body.replace("<", "\\u003c")

def replace_region(text, start, end, body):
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit("%s / %s 표시가 없습니다." % (start, end))
    return pattern.sub(lambda _match: start + "\n" + body + "\n" + end, text, count=1)


def trade_state(state):
    """지금 매수/매도 중 무엇이 체결되는지 판정합니다.

    - buyNow : 현재가가 매수 지정가(들) 이하 -> LOC 매수 체결
    - sellNow: 현재가가 매도 지정가(들) 이상 -> LOC 매도 / 지정가 매도 체결
    """
    orders = state.get("orders") or []
    buys = [order["price"] for order in orders if order["type"] == "buy" and order.get("price")]
    sells = [order["price"] for order in orders if order["type"] == "sell" and order.get("price")]
    buy_limit = max(buys) if buys else None
    sell_limit = min(sells) if sells else None
    price = state["lastClose"]
    buy_now = buy_limit is not None and price <= buy_limit
    sell_now = sell_limit is not None and price >= sell_limit
    if sell_now and buy_now:
        action, action_cls = "매수·매도", "both"
        action_text = "매수와 매도 주문이 함께 체결되는 구간입니다."
    elif sell_now:
        action, action_cls = "매도", "sell"
        action_text = "매도 구간입니다. 지정가 이상이라 보유 일부(1/4·3/4)가 매도됩니다."
    elif buy_now:
        action, action_cls = "매수", "buy"
        action_text = "매수 구간입니다. 다음 거래일 LOC 매수가 지정가 이하에서 체결됩니다."
    else:
        action, action_cls = "관망", "hold"
        action_text = "관망 구간입니다. 지정가에 닿지 않아 매수·매도가 체결되지 않습니다."
    target = state.get("targetPrice") or 0
    to_target = round((target / price - 1.0) * 100.0, 1) if price and target else None
    return {
        "buyNow": buy_now,
        "sellNow": sell_now,
        "buyLimit": buy_limit,
        "sellLimit": sell_limit,
        "targetPrice": target,
        "lastClose": price,
        "avg": state.get("avg"),
        "action": action,
        "actionCls": action_cls,
        "actionText": action_text,
        "toTargetPct": to_target,
    }


def make_summary(state):
    """주가 방향 날씨 페이지의 서머리에 넣을 무한매수 요약을 만듭니다."""
    trade = state.get("trade") or {}
    return {
        "asof": state["asof"],
        "lastClose": state["lastClose"],
        "T": state["T"],
        "phase": state["phase"],
        "avg": state["avg"],
        "targetPrice": state["targetPrice"],
        "buyNow": trade.get("buyNow"),
        "sellNow": trade.get("sellNow"),
        "buyLimit": trade.get("buyLimit"),
        "sellLimit": trade.get("sellLimit"),
        "action": trade.get("action"),
        "actionCls": trade.get("actionCls"),
        "actionText": trade.get("actionText"),
        "toTargetPct": trade.get("toTargetPct"),
        "cycleNo": state["cycleNo"],
        "returnPct": state["returnPct"],
        "total": state["total"],
    }


def summary_json(summary):
    body = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    return "window.MUHAN_SUMMARY = %s;" % body.replace("<", "\\u003c")


def main():
    bars = daily_bars()
    if not bars:
        raise SystemExit("TQQQ 일봉 데이터를 받지 못했습니다.")
    state = simulate(bars)
    if not state:
        raise SystemExit("시뮬레이션할 일봉이 부족합니다.")
    state["orders"] = make_orders(state)
    state["trade"] = trade_state(state)

    note = (
        '<p class="note">기준일 %s · TQQQ %s · 시드 $%s · %d분할 · 라오어 %s · '
        "미국장 마감 후 매일 자동 갱신</p>"
        % (
            state["asof"],
            "{:,.2f}".format(state["lastClose"]),
            "{:,.0f}".format(state["seed"]),
            state["rounds"],
            state["version"],
        )
    )

    text = PAGE.read_text(encoding="utf-8")
    text = replace_region(text, "<!-- NOTE_START -->", "<!-- NOTE_END -->", note)
    text = replace_region(text, "<!-- DATA_START -->", "<!-- DATA_END -->", series_json(state))
    with open(str(PAGE), "w", encoding="utf-8", newline="") as handle:
        handle.write(text)

    SUMMARY.write_text(summary_json(make_summary(state)) + "\n", encoding="utf-8")
    print("서머리 갱신:", SUMMARY)

    print(
        "기준일 %s | TQQQ %.2f | T %.1f | 평단 %.2f | 보유 %.2f주 | 누적매수 $%.2f | 총손익 $%.2f"
        % (
            state["asof"],
            state["lastClose"],
            state["T"],
            state["avg"],
            state["shares"],
            state["invested"],
            state["total"],
        )
    )
    print("갱신 완료:", PAGE)


if __name__ == "__main__":
    main()