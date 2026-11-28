# -*- coding: utf-8 -*-
"""SOXX 타점: SOXX 일봉 RSI(14)로 경기순환사이클 하락장 매수 타점을 계산한다.

규칙
1. 경기순환사이클 하락 추정 시기에는 RSI(14)가 30 아래로 내려갔다 올라오기를 반복한다.
2. 30 이탈이 세 번 나온 뒤, 네 번째와 그 이후에도 30 아래로 내려가면 매수하지 않고 계속 대기한다.
3. 그 뒤 RSI 가 35 아래로 내려왔지만 30 아래로는 가지 않은 저점에서, 그 저점보다 2 오른 날이 매수 타점이다.
   (상승 다이버전스 출현으로 보고 매수한다.)
4. 30 이탈끼리 1년 이상 벌어지면 앞의 이탈은 무시하고 새로 센다.

    python Premium/hansjang/SOXX/update_soxx.py

결과는 같은 폴더의 soxx-data.js 로 쓴다. 페이지(SOXX/index.html)는 그 파일만 읽는다.
한스장 타점 메뉴(Premium/hansjang/index.html)에 SOXX 타점이 없으면 넣고,
AI 혁신주 타점(Premium/ai-trend/index.html)에 남은 예전 SOXL 메뉴는 지운다.
"""
import calendar
import json
import re
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

TICKER = "SOXX"
HERE = Path(__file__).resolve().parent
DATA = HERE / "soxx-data.js"
HUB = HERE.parent / "index.html"                        # Premium/hansjang/index.html
AI_TREND = HERE.parents[1] / "ai-trend" / "index.html"  # Premium/ai-trend/index.html
CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
             "?interval=1d&period1={start}&period2={end}")
HEADERS = {"User-Agent": "Mozilla/5.0"}
FIRST_YEAR = 2000       # 복기 구간이 2000-2002 부터다. SOXX 상장은 2001-07 이다.
CHUNK_YEARS = 4         # 한 번에 받을 기간(년). 길게 받으면 일봉이 줄어든다.

# 한스장 타점 메뉴에 이 페이지를 넣는다. 다른 스크립트가 랜딩 페이지를 다시 써도 살아남게 여기서 관리한다.
MENU_ANCHOR = '<a class="topbar-link" href="LEAD/index.html">선행지수 타점</a></span>'
MENU_SLOT = ('\n    <span class="menu-slot"><span class="menu-horizon">경기순환사이클 하락(일봉 RSI 30 세 번 이탈 뒤, '
             '35 이하 저점 +2 반등)</span><a class="topbar-link" href="SOXX/index.html">SOXX 타점</a></span>')
RSI_PERIOD = 14
RSI_LEVEL = 30.0        # 30 이탈 = 하락 신호
RSI_LEVEL_BUY = 35.0    # 35 이하 저점이되 30 위에서 멈춘 자리 = 상승 다이버전스 후보
REBOUND = 2.0           # 저점보다 2 오르면 타점
MIN_DIPS = 3            # 30 이탈이 세 번은 있어야 한다
RESET_MONTHS = 12       # 30 이탈끼리 1년 이상 벌어지면 앞의 이탈은 무시하고 새로 센다
RESET_DAYS = 365        # 30 이탈 사이 간격이 이만큼 벌어지면 앞의 이탈은 다른 하락으로 보고 새로 센다

# kind: past = 과거 복기, cycle = 경기순환사이클 하락 추정 시기
WINDOWS = [
    {"key": "2000-2002", "from": "2000-01-01", "to": "2002-12-31", "kind": "past"},
    {"key": "2003-2004", "from": "2003-01-01", "to": "2004-12-31", "kind": "past"},
    {"key": "2007-2009", "from": "2007-01-01", "to": "2009-12-31", "kind": "past"},
    {"key": "2011-2012", "from": "2011-01-01", "to": "2012-12-31", "kind": "past"},
    {"key": "2015-2016", "from": "2015-01-01", "to": "2016-12-31", "kind": "past"},
    {"key": "2018-2019", "from": "2018-01-01", "to": "2019-12-31", "kind": "past"},
    {"key": "2022-2023", "from": "2022-01-01", "to": "2023-12-31", "kind": "past"},
    {"key": "2025-2027", "from": "2025-01-01", "to": "2027-12-31", "kind": "cycle"},
    {"key": "2029-2031", "from": "2029-01-01", "to": "2031-12-31", "kind": "cycle"},
    {"key": "2033-2035", "from": "2033-01-01", "to": "2035-12-31", "kind": "cycle"},
]


def fetch_chunk(start_stamp, end_stamp):
    """한 구간의 일봉을 받는다. range=max 는 일봉 대신 월봉을 주기 때문에 기간을 나눠 받는다."""
    url = CHART_URL.format(ticker=TICKER, start=start_stamp, end=end_stamp)
    last_error = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.load(response)
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                raise ValueError("empty result")
            block = result[0]
            stamps = block.get("timestamp") or []
            quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
            adjusted = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
            bars = []
            for index, stamp in enumerate(stamps):
                close = quote["close"][index]
                high = quote["high"][index]
                low = quote["low"][index]
                open_ = quote["open"][index]
                if None in (close, high, low, open_):
                    continue
                factor = 1.0
                if adjusted and index < len(adjusted) and adjusted[index] and close:
                    factor = adjusted[index] / close
                day = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d")
                bars.append([
                    day,
                    round(open_ * factor, 2),
                    round(high * factor, 2),
                    round(low * factor, 2),
                    round(close * factor, 2),
                ])
            if bars:
                return bars, (block.get("meta") or {})
            raise ValueError("no bars")
        except Exception as error:  # noqa: BLE001
            last_error = error
            time.sleep(1.2 * (attempt + 1))
    raise SystemExit("SOXX 데이터를 가져오지 못했습니다: %s" % last_error)


def fetch_bars():
    end_year = datetime.now(timezone.utc).year + 1
    merged = {}
    meta = {}
    for year in range(FIRST_YEAR, end_year, CHUNK_YEARS):
        stop = min(year + CHUNK_YEARS, end_year)
        bars, chunk_meta = fetch_chunk(
            int(calendar.timegm((year, 1, 1, 0, 0, 0))),
            int(calendar.timegm((stop, 1, 1, 0, 0, 0))),
        )
        for bar in bars:
            merged[bar[0]] = bar
        if chunk_meta and not meta:
            meta = chunk_meta
    bars = [merged[day] for day in sorted(merged)]
    if not bars:
        raise SystemExit("SOXX 일봉이 비어 있습니다.")
    return bars, meta


def rsi_series(closes, period=RSI_PERIOD):
    values = [None] * len(closes)
    if len(closes) <= period:
        return values
    gain = 0.0
    loss = 0.0
    for index in range(1, period + 1):
        delta = closes[index] - closes[index - 1]
        if delta >= 0:
            gain += delta
        else:
            loss -= delta
    avg_gain = gain / period
    avg_loss = loss / period

    def reading(up, down):
        if down == 0:
            return 100.0
        return 100.0 - (100.0 / (1.0 + up / down))

    values[period] = round(reading(avg_gain, avg_loss), 1)
    for index in range(period + 1, len(closes)):
        delta = closes[index] - closes[index - 1]
        up = delta if delta > 0 else 0.0
        down = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + up) / period
        avg_loss = (avg_loss * (period - 1) + down) / period
        values[index] = round(reading(avg_gain, avg_loss), 1)
    return values


def find_dips(series, level):
    """RSI 가 level 아래로 내려간 구간을 순서대로 모은다. level 위로 올라와야 구간이 나뉜다."""
    dips = []
    current = None
    for index, value in enumerate(series):
        if value is None:
            continue
        if value < level:
            if current is None:
                current = {"start": index, "end": index, "low": index, "lowValue": value}
            else:
                current["end"] = index
                if value < current["lowValue"]:
                    current["lowValue"] = value
                    current["low"] = index
        elif current is not None:
            dips.append(current)
            current = None
    if current is not None:
        dips.append(current)
    return dips


def annotate(dip, bars):
    dip["lowValue"] = round(dip["lowValue"], 1)
    dip["startDate"] = bars[dip["start"]][0]
    dip["endDate"] = bars[dip["end"]][0]
    dip["lowDate"] = bars[dip["low"]][0]
    dip["lowPrice"] = bars[dip["low"]][4]
    return dip


def as_date(day):
    return date(*[int(part) for part in day.split("-")])


def add_months(day, months):
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def rebound_index(series, bars, dip, limit_day):
    """저점보다 REBOUND 만큼 오른 첫 봉.

    buy = 그 봉, fail = 그 전에 다시 30 아래로 내려가 상승 다이버전스가 아님,
    pending = 구간이 끝날 때까지 +2 반등이 아직 없음.
    """
    target = dip["lowValue"] + REBOUND
    for index in range(dip["low"] + 1, len(series)):
        if bars[index][0] > limit_day:
            return None, "pending"
        value = series[index]
        if value is None:
            continue
        if value < RSI_LEVEL:
            return None, "fail"
        if value >= target:
            return index, "buy"
    return None, "pending"


def plan_window(window, strict, loose, series, bars):
    """한 구간의 매수 타점을 규칙대로 계산한다. 30 이탈과 35 이하(30 위) 저점을 시간 순서로 본다.

    30 이탈끼리 1년 이상 벌어지면(앞 이탈의 끝 ~ 다음 이탈의 시작) 앞의 이탈은 무시하고 새로 센다.

    reason: dips = 30 이탈 3회 미만, div = 35 이하(30 위) 저점 없음,
            wait = 저점은 나왔지만 아직 +2 반등 없음.
    """
    events = []
    for dip in strict:
        if window["from"] <= dip["startDate"] <= window["to"]:
            events.append((dip["start"], 0, dip))   # RSI 30 이탈
    for dip in loose:
        if dip["lowValue"] < RSI_LEVEL:
            continue                                # 30 이탈 쪽에서 이미 센다
        if window["from"] <= dip["startDate"] <= window["to"]:
            events.append((dip["start"], 1, dip))   # RSI 35 이하이면서 30 위인 저점
    events.sort(key=lambda item: (item[0], item[1]))

    picked = []
    ignored = []
    plan = {"dips": picked, "ignored": ignored, "div": None, "trigger": None, "reason": None}
    last_end = None
    for _start, kind, dip in events:
        if kind == 0:
            start = as_date(dip["startDate"])
            if last_end is not None and start >= add_months(last_end, RESET_MONTHS):
                ignored.extend(picked)      # 1년 이상 벌어졌다. 앞의 이탈은 무시하고 새로 센다.
                del picked[:]
            picked.append(dip)              # 4번째 이후 30 이탈도 여기서 센다.
            last_end = as_date(dip["endDate"])
            continue
        if len(picked) < MIN_DIPS:
            continue                    # 30 이탈이 세 번은 있어야 한다
        trigger, status = rebound_index(series, bars, dip, window["to"])
        if status == "buy":
            plan["div"] = dip
            plan["trigger"] = trigger
            break
        if status == "pending":
            plan["div"] = dip           # 저점은 나왔고 반등을 기다린다
            break
        # fail: 35 이하 저점이 다시 30 아래로 내려갔다. 다음 이벤트로 넘긴다.
    if plan["div"] is None:
        plan["reason"] = "dips" if len(picked) < MIN_DIPS else "div"
    elif plan["trigger"] is None:
        plan["reason"] = "wait"
    return plan


def patch_hub():
    """한스장 타점 메뉴에 SOXX 타점이 없으면 넣는다. 있으면 아무것도 하지 않는다."""
    if not HUB.exists():
        return False
    text = HUB.read_text(encoding="utf-8")
    if 'href="SOXX/index.html"' in text:
        return False
    if MENU_ANCHOR not in text:
        raise SystemExit("한스장 메뉴에서 선행지수 타점을 찾지 못했습니다: %s" % HUB)
    HUB.write_text(text.replace(MENU_ANCHOR, MENU_ANCHOR + MENU_SLOT, 1), encoding="utf-8")
    return True


def clean_old_menu():
    """AI 혁신주 타점 페이지에 남아 있는 예전 SOXL 메뉴 묶음을 지운다."""
    if not AI_TREND.exists():
        return False
    text = AI_TREND.read_text(encoding="utf-8")
    if "soxl" not in text:
        return False
    trimmed = re.sub(r'\s*<nav class="menu"[\s\S]*?</nav>', "", text, count=1)
    if trimmed == text:
        return False
    AI_TREND.write_text(trimmed, encoding="utf-8")
    return True


def window_state(window, asof):
    if window["from"] > asof:
        return "future"
    if window["to"] < asof:
        return "past"
    return "active"


def window_low(window, bars):
    low = None
    for bar in bars:
        if window["from"] <= bar[0] <= window["to"]:
            if low is None or bar[3] < low[3]:
                low = bar
    return low


def main():
    if clean_old_menu():
        print("AI 혁신주 타점에서 예전 SOXL 메뉴를 지웠습니다: %s" % AI_TREND)
    if patch_hub():
        print("한스장 타점 메뉴에 SOXX 타점을 넣었습니다: %s" % HUB)

    bars, meta = fetch_bars()
    closes = [bar[4] for bar in bars]
    series = rsi_series(closes)
    strict = [annotate(dip, bars) for dip in find_dips(series, RSI_LEVEL)]
    loose = [annotate(dip, bars) for dip in find_dips(series, RSI_LEVEL_BUY)]

    asof = bars[-1][0]
    plans = []
    for window in WINDOWS:
        plan = plan_window(window, strict, loose, series, bars)
        plan["window"] = window
        plan["state"] = window_state(window, asof)
        plans.append(plan)

    pool = {}

    def add(dip, strict_flag):
        key = (dip["start"], dip["end"])
        if key in pool:
            return
        pool[key] = {
            "start": dip["start"], "end": dip["end"], "startDate": dip["startDate"],
            "endDate": dip["endDate"], "low": dip["low"], "lowDate": dip["lowDate"],
            "lowValue": dip["lowValue"], "lowPrice": dip["lowPrice"], "strict": strict_flag,
        }

    for dip in strict:
        add(dip, True)
    for dip in loose:
        if dip["lowValue"] >= RSI_LEVEL:
            add(dip, False)   # 35 이하(30 위) 저점은 모두 차트에 표시한다

    dips = sorted(pool.values(), key=lambda item: item["start"])
    position = {}
    for index, dip in enumerate(dips):
        position[(dip["start"], dip["end"])] = index

    windows = []
    for plan in plans:
        window = plan["window"]
        low = window_low(window, bars)
        entry = {
            "key": window["key"], "from": window["from"], "to": window["to"],
            "kind": window["kind"], "state": plan["state"],
            "dips": [position[(dip["start"], dip["end"])] for dip in plan["dips"]],
            "ignored": [position[(dip["start"], dip["end"])] for dip in plan["ignored"]],
            "div": None, "buy": None, "reason": plan["reason"],
            "lowDate": low[0] if low else None,
            "lowPrice": round(low[3], 2) if low else None,
            "firstDipDate": plan["dips"][0]["startDate"] if plan["dips"] else None,
        }
        if plan["div"] is not None:
            entry["div"] = position[(plan["div"]["start"], plan["div"]["end"])]
            entry["divDate"] = plan["div"]["startDate"]
            entry["divValue"] = plan["div"]["lowValue"]
            entry["divLowDate"] = plan["div"]["lowDate"]
        if plan["trigger"] is not None:
            entry["buy"] = plan["trigger"]
            entry["buyDate"] = bars[plan["trigger"]][0]
            entry["buyPrice"] = bars[plan["trigger"]][4]
            entry["buyRsi"] = series[plan["trigger"]]
        windows.append(entry)

    payload = {
        "asof": asof,
        "ticker": TICKER,
        "name": meta.get("shortName") or meta.get("longName") or TICKER,
        "currency": meta.get("currency") or "USD",
        "rsiPeriod": RSI_PERIOD,
        "rsiLevel": RSI_LEVEL,
        "rsiLevelBuy": RSI_LEVEL_BUY,
        "rebound": REBOUND,
        "bars": bars,
        "rsi": series,
        "dips": dips,
        "windows": windows,
    }
    DATA.write_text(
        "window.SOXX_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    print("bars=%d %s..%s dips30=%d dips35=%d" % (len(bars), bars[0][0], asof, len(strict), len(loose)))
    for window in windows:
        if window.get("buy") is not None:
            print("  %-9s %-6s dips30=%d  BUY %s @ %s (RSI %s, 저점 %s %s)"
                  % (window["key"], window["state"], len(window["dips"]), window["buyDate"],
                     window["buyPrice"], window["buyRsi"], window["divValue"], window["divDate"]))
        else:
            print("  %-9s %-6s dips30=%d  no buy (%s)"
                  % (window["key"], window["state"], len(window["dips"]), window["reason"]))


if __name__ == "__main__":
    main()
