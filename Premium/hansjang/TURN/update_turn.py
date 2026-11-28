# -*- coding: utf-8 -*-
"""쌍바닥 + 계단식 하락법 바닥 타점 (v1).

규칙 출처: 첫책핵심 -CLI.xlsx(바닥시그널 시트) + 주가바닥잡기및계단식법비결.docx
  1. G20 CLI 전월비(mom) 하락폭이 커지다가 2달 연속 줄어들면 매수 시그널.
  2. 시그널 후 4개월 이내 주가 하락이 오면 쌍바닥을 찾는다.
  3. 쌍바닥의 2번째 바닥에서 매수.
  4. Case A(천장->1쌍바닥 4개월 초과 ~ 18개월 미만): 2쌍이 1쌍보다 낮음 -> 2쌍이 1쌍을 뚫은 뒤부터 카운트 -> 4단계 매수.
     Case B(4개월 이하 또는 18개월 이상): 1쌍이 더 낮음 -> 2쌍 시작(전고점)부터 카운트 -> 3단계 매수.
  5. 계단식 하락법: 일봉 하락률을 절대치 크기순으로 카운트(1단계=최대 하락, 2단계=2번째 ...).

v1 가정(검증 필요)
  - 천장/바닥: QQQ 일봉 종가 지그재그(반전 ZIGZAG_PCT).
  - 쌍바닥: 케이스 구간의 마지막 두 스윙 저점.
  - CLI: G20 전월비를 소수점 한자리(Rule 7)로 반올림해 2달 연속 축소를 판정.

데이터: G20 CLI(LEAD와 동일) + QQQ 일봉(Yahoo).
    python Premium/hansjang/TURN/update_turn.py
결과는 같은 폴더의 turn-data.js 로 쓴다.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "LEAD"))
import update_lead as lead  # noqa: E402

DATA = HERE / "turn-data.js"
TICKER = "QQQ"
ZIGZAG_PCT = 0.08       # 스윙(천장/바닥) 판정 반전폭
CLI_DECIMALS = 1        # Rule 7: CLI 는 소수점 한자리
MAX_STEP = 6            # 계단식 단계 표시 상한

# 사례(폭락) 구간. anchor 는 문서에 나온 확정 천장/쌍바닥 날짜, ref 는 엑셀 Sheet1 참고값(검증용).
CASES = [
    {"key": "닷컴버블1(IT1차)", "from": "2000-01-01", "to": "2002-06-30",
     "anchor": {"peak": "2000-03-27", "first": "2001-04-04", "second": "2001-09-21"},
     "ref": {"case": "A", "lower": "2쌍"}},
    {"key": "닷컴버블2(IT2차)", "from": "2002-01-01", "to": "2003-06-30",
     "anchor": {"first": "2002-07-23", "second": "2002-10-07"},
     "ref": {"lower": "2쌍", "to1": "6개월"}},
    {"key": "리먼쇼크", "from": "2007-06-01", "to": "2009-12-31",
     "anchor": {"peak": "2007-10-31", "first": "2008-11-20", "second": "2009-03-09"},
     "ref": {"case": "A", "lower": "2쌍", "to1": "13개월", "to2": "17개월"}},
    {"key": "2011년 하락", "from": "2011-01-01", "to": "2012-06-30", "anchor": {}, "ref": {}},
    {"key": "2015년 하락", "from": "2015-06-01", "to": "2016-12-31", "anchor": {}, "ref": {}},
    {"key": "2018년 하락", "from": "2018-06-01", "to": "2019-12-31", "anchor": {}, "ref": {}},
    {"key": "2022년 하락", "from": "2021-11-01", "to": "2023-06-30", "anchor": {}, "ref": {"case": "A", "lower": "2쌍"}},
    {"key": "2026년 하락", "from": "2025-01-01", "to": "2026-12-31", "anchor": {}, "ref": {}},
]


def zigzag(bars, pct):
    """종가 지그재그. pct 이상 반전마다 (kind, index) 를 기록한다."""
    pivots = []
    n = len(bars)
    if n == 0:
        return pivots
    ext = 0
    direction = 0
    for i in range(1, n):
        price = bars[i][4]
        if direction == 0:
            if price >= bars[ext][4] * (1 + pct):
                direction = 1
                pivots.append(("L", ext))
                ext = i
            elif price <= bars[ext][4] * (1 - pct):
                direction = -1
                pivots.append(("H", ext))
                ext = i
        elif direction == 1:
            if price > bars[ext][4]:
                ext = i
            elif price <= bars[ext][4] * (1 - pct):
                pivots.append(("H", ext))
                direction = -1
                ext = i
        else:
            if price < bars[ext][4]:
                ext = i
            elif price >= bars[ext][4] * (1 + pct):
                pivots.append(("L", ext))
                direction = 1
                ext = i
    return pivots


def staircase(bars, start_idx, end_idx):
    """계단식 하락법: 일봉 하락률을 시간 순서로 보며 단계를 매긴다.

    폭락폭(하락률)이 줄면 단계가 1 늘고, 늘면 그 하락이 속하는 앞(높은) 단계로 되돌아간다.
    단계 = 지금까지 나온 '더 큰 하락' 단계 수 + 1.
    """
    levels = []          # 단계별 하락률(절대치), 내림차순
    steps = []
    for i in range(start_idx + 1, min(end_idx, len(bars) - 1) + 1):
        prev = bars[i - 1][4]
        cur = bars[i][4]
        if not prev or cur >= prev:
            continue
        drop = abs((cur / prev - 1) * 100)
        step = 1 + sum(1 for level in levels if level > drop)
        levels = levels[:step - 1] + [drop]
        steps.append({"step": step, "date": bars[i][0], "pct": round(-drop, 2), "price": cur})
    return steps


def index_on_or_after(bars, day):
    for i, bar in enumerate(bars):
        if bar[0] >= day:
            return i
    return len(bars) - 1


def month_diff(a, b):
    return (int(b[0:4]) * 12 + int(b[5:7])) - (int(a[0:4]) * 12 + int(a[5:7]))

def cli_narrowing(cli):
    """CLI(1자리) 전월비 하락폭이 커지다가 2달 연속 줄어든 달. {period: narrowing}"""
    rows = []
    for row in cli:
        if row["mom"] is not None:
            rows.append((row["period"], round(row["mom"], CLI_DECIMALS)))
    state = {}
    prev = None
    deepened = False
    narrowing = 0
    for period, mom in rows:
        if prev is None:
            prev = mom
            state[period] = 0
            continue
        if mom >= 0:
            deepened = False
            narrowing = 0
        elif mom < prev:
            deepened = True
            narrowing = 0
        elif mom > prev:
            narrowing = narrowing + 1 if deepened else 0
        else:
            narrowing = 0
        state[period] = narrowing
        prev = mom
    return state


def build_case(bars, pivots, cli_state, case):
    from_idx = index_on_or_after(bars, case["from"])
    to_idx = index_on_or_after(bars, case["to"])
    closes = [bars[i][4] for i in range(from_idx, to_idx + 1)]
    low_off = min(range(len(closes)), key=lambda k: closes[k])
    low_idx = from_idx + low_off
    peak_idx = from_idx + max(range(low_off + 1), key=lambda k: closes[k])

    lows = [i for (kind, i) in pivots if kind == "L" and from_idx <= i <= to_idx]
    highs = [i for (kind, i) in pivots if kind == "H" and from_idx <= i <= to_idx]
    if len(lows) >= 2:
        first, second = lows[-2], lows[-1]
    elif lows:
        first = second = lows[-1]
    else:
        first = second = low_idx

    anchor = case.get("anchor") or {}
    if anchor.get("peak"):
        peak_idx = index_on_or_after(bars, anchor["peak"])
    if anchor.get("first"):
        first = index_on_or_after(bars, anchor["first"])
    if anchor.get("second"):
        second = index_on_or_after(bars, anchor["second"])

    peak_date, first_date, second_date = bars[peak_idx][0], bars[first][0], bars[second][0]
    to1 = month_diff(peak_date, first_date)
    to2 = month_diff(peak_date, second_date)
    kind = "B" if (to1 <= 4 or to1 >= 18) else "A"

    if kind == "A":
        start_idx = None
        i = second
        while i > first and bars[i][4] >= bars[first][4]:
            i -= 1
        if i > first:
            j = i
            while j - 1 > first and bars[j - 1][4] < bars[first][4]:
                j -= 1
            start_idx = j
            start_note = "2쌍이 1쌍바닥을 뚫은 날"
        else:
            before = [h for h in highs if h < second]
            start_idx = before[-1] if before else first
            start_note = "2쌍 직전 전고점(1쌍 미돌파)"
    else:
        before = [i for i in highs if i < second]
        start_idx = before[-1] if before else first
        start_note = "2쌍 직전 전고점"

    steps = staircase(bars, start_idx, second)     # 2쌍바닥까지 카운트
    target = 3                                     # 문서 기준: 3번째 큰 하락폭에서 매수
    buy = next((s for s in steps if s["step"] >= target), None)
    signals = sorted(p for p, n in cli_state.items() if n >= 2 and case["from"][:7] <= p <= case["to"][:7])

    return {
        "key": case["key"],
        "from": case["from"], "to": case["to"],
        "peak": {"date": peak_date, "price": bars[peak_idx][4]},
        "low": {"date": bars[low_idx][0], "price": bars[low_idx][4]},
        "first": {"date": first_date, "price": bars[first][4]},
        "second": {"date": second_date, "price": bars[second][4]},
        "caseKind": kind,
        "to1": to1, "to2": to2,
        "lower": "2쌍" if bars[second][4] < bars[first][4] else "1쌍",
        "drop30": round((bars[peak_idx][4] - bars[second][4]) / bars[peak_idx][4], 3),
        "startDate": bars[start_idx][0], "startNote": start_note,
        "target": target, "buy": buy,
        "steps": steps,
        "signals": signals,
        "pivotLows": [{"date": bars[i][0], "price": bars[i][4]} for i in lows],
        "ref": case.get("ref", {}),
    }


def main():
    cli = lead.build_cli()
    bars, _ = lead.fetch_bars("1d")
    cli_state = cli_narrowing(cli)
    pivots = zigzag(bars, ZIGZAG_PCT)
    cases = [build_case(bars, pivots, cli_state, case) for case in CASES]

    payload = {
        "asof": bars[-1][0],
        "ticker": TICKER,
        "zigzagPct": ZIGZAG_PCT,
        "cliDecimals": CLI_DECIMALS,
        "bars": [[b[0], b[4]] for b in bars],     # 일봉 종가 (차트용)
        "cases": cases,
    }
    DATA.write_text(
        "window.TURN_DATA = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print("bars=%d %s..%s  zigzag=%d%%" % (len(bars), bars[0][0], bars[-1][0], int(ZIGZAG_PCT * 100)))
    for c in cases:
        buy = c["buy"]
        buy_text = ("%d단계 %s (%.2f%%)" % (buy["step"], buy["date"], buy["pct"])) if buy else "미도달"
        print("  %-16s 천장 %s | 1쌍 %s %.2f | 2쌍 %s %.2f | Case %s | 낮은쪽 %s | 신호 %s | 매수 %s"
              % (c["key"], c["peak"]["date"], c["first"]["date"], c["first"]["price"],
                 c["second"]["date"], c["second"]["price"], c["caseKind"], c["lower"],
                 ",".join(c["signals"]) or "-", buy_text))
        print("      카운트 시작 %s (%s)" % (c["startDate"], c["startNote"]))


if __name__ == "__main__":
    main()
