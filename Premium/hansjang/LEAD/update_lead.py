# -*- coding: utf-8 -*-
"""선행지수 타점: G20 경기선행지수(CLI) 전월비(mom)로 나스닥100(QQQ) 매수 타점을 계산한다.

규칙
  1. G20 전월비(mom)가 음수인 하락 구간만 본다.
  2. 하락폭이 더 커지다가(전월 대비 더 큰 하락) 하락폭을 줄이기 시작한다.
  3. 하락폭을 줄인 지 2달째 되는 달을 매수 신호 월로 본다.
  4. 경기순환사이클 하락 및 주가 바닥 가능시기(BUY_PERIODS)에만 매수 타점을 적용한다.
  5. 선행지수 전월비 하락폭을 2달 줄인 뒤, QQQ 일봉 RSI(14)가 30 미만일 때 분할 매수한다.

데이터
  - G20 CLI 월별: OECD SDMX(2000-01~) + Supabase(hangjang-table) 최신값을 덮어쓴다.
  - QQQ 주봉: Yahoo Finance(수정주가, 2000~). 가격 차트에 쓴다.
  - QQQ 일봉: Yahoo Finance(수정주가). 일봉 RSI(14)와 매수일에 쓴다.

    python Premium/hansjang/LEAD/update_lead.py

결과는 같은 폴더의 lead-data.js 로 쓴다. 페이지(LEAD/index.html)는 그 파일만 읽는다.
"""
import csv
import io
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TICKER = "QQQ"
DATA = Path(__file__).with_name("lead-data.js")

SUPABASE_URL = "https://vlvblacfffkalojefjwp.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_C4BZUGCN_QyMZkVe3PIysQ_ZkqosPCL"

# OECD 경기선행지수(CLI) G20 월별 (OECD amplitude adjusted index, 100 기준)
OECD_URL = (
    "https://sdmx.oecd.org/public/rest/data/"
    "OECD.SDD.STES,DSD_STES@DF_CLI,4.1/G20.M.LI.IX._Z.AA.IX._Z.H"
    "?startPeriod=2000-01&format=csvfilewithlabels&dimensionAtObservation=AllDimensions"
)
# range=max 는 interval 을 무시하고 월봉으로 떨어진다(예전엔 실제로 월봉이 내려왔다). period1/period2 로 기간을 지정한다.
CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
             "?interval={interval}&period1={period1}&period2={period2}")
HEADERS = {"User-Agent": "Mozilla/5.0"}
START_EPOCH = 915148800   # 1999-01-01 UTC (Yahoo period1)

MOM_DECIMALS = 2    # 전월비는 소수 둘째 자리(예: -0.06%)까지. Supabase 표와 같은 규칙.
START_YEAR = 2000   # 차트/타점 시작 연도
WINDOW_YEARS = 4    # 3~4년 단위로 차트를 나눈다.
RSI_PERIOD = 14         # 일봉 RSI 기간
RSI_DIP_LEVEL = 30.0    # QQQ 일봉 RSI(14) 30 이탈 = 하락 신호
RSI_DIV_LEVEL = 35.0    # 35 이하(30 위) 저점 = 상승 다이버전스 후보
REBOUND = 2.0           # 저점보다 2 오르면 매수 타점
MIN_DIPS = 3            # 30 이탈이 세 번은 있어야 한다
RESET_MONTHS = 12       # 30 이탈끼리 1년 이상 벌어지면 앞의 이탈은 무시하고 새로 센다
G20_MIN_MONTHS = 2      # G20 선행지수 전월비가 이만큼 연속 하락한 이후에만 매수한다

# 경기순환사이클 하락 및 주가 바닥 가능시기: 이 구간에만 매수 타점을 적용한다. (start_year, end_year) 양끝 포함.
BUY_PERIODS = [
    (2000, 2002),
    (2003, 2004),
    (2007, 2009),
    (2011, 2012),
    (2015, 2016),
    (2018, 2019),
    (2022, 2023),
    (2025, 2027),
    (2029, 2031),
    (2033, 2035),
]


def get(url, headers=None, timeout=60):
    merged = dict(HEADERS)
    if headers:
        merged.update(headers)
    request = urllib.request.Request(url, headers=merged)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def month_index(period):
    year, month = int(period[0:4]), int(period[5:7])
    return year * 12 + month - 1


def in_buy_period(period):
    """경기순환사이클 하락/주가 바닥 가능시기(매수 타점을 적용하는 구간)인지 확인한다."""
    year = int(str(period)[0:4])
    return any(start <= year <= end for start, end in BUY_PERIODS)


def fetch_oecd_cli():
    """OECD SDMX 에서 G20 CLI 월별 관측치를 받는다. {period: obs_value}"""
    raw = get(OECD_URL, {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}, timeout=120)
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    header = {name: index for index, name in enumerate(rows[0])}
    period_col = header["TIME_PERIOD"]
    value_col = header["OBS_VALUE"]
    out = {}
    for row in rows[1:]:
        if len(row) <= max(period_col, value_col):
            continue
        period = row[period_col].strip()
        value = row[value_col].strip()
        if period and value:
            try:
                out[period] = float(value)
            except ValueError:
                pass
    return out


def fetch_supabase_cli():
    """Supabase hangjang-table 에서 G20 전월비를 받는다. {period: (obs, mom)}"""
    url = (SUPABASE_URL + "/rest/v1/hangjang-table"
           "?select=reference_area,time_period,obs_value,mom&reference_area=eq.G20"
           "&order=time_period.asc&limit=5000")
    raw = get(url, {"apikey": SUPABASE_ANON_KEY, "Authorization": "Bearer " + SUPABASE_ANON_KEY})
    out = {}
    for row in json.loads(raw.decode("utf-8")):
        period = str(row.get("time_period") or "")[:7]
        if not period:
            continue
        obs = None
        mom = None
        try:
            obs = float(row.get("obs_value"))
        except (TypeError, ValueError):
            obs = None
        text = str(row.get("mom") or "").replace("%", "").strip()
        try:
            mom = float(text)
        except ValueError:
            mom = None
        out[period] = (obs, mom)
    return out


def build_cli():
    """OECD 이력 + Supabase 최신값을 합쳐 {period, obs, mom} 목록을 만든다. 오래된 순 정렬."""
    oecd = fetch_oecd_cli()
    supa = fetch_supabase_cli()
    values = dict(oecd)
    mom_override = {}
    for period, (obs, mom) in supa.items():
        if obs is not None:
            values[period] = obs
        if mom is not None:
            mom_override[period] = mom
    periods = sorted(values.keys(), key=month_index)
    series = []
    for index, period in enumerate(periods):
        obs = values[period]
        if period in mom_override:
            mom = round(mom_override[period], MOM_DECIMALS)
        elif index > 0:
            mom = round((obs / values[periods[index - 1]] - 1) * 100, MOM_DECIMALS)
        else:
            mom = None
        series.append({"period": period, "obs": round(obs, 5), "mom": mom})
    return series


def fetch_bars(interval):
    """Yahoo Finance 봉(수정주가) 전체 이력. [[date, open, high, low, close], ...]"""
    url = CHART_URL.format(ticker=TICKER, interval=interval,
                           period1=START_EPOCH, period2=int(time.time()) + 86400)
    last_error = None
    for attempt in range(4):
        try:
            payload = json.loads(get(url).decode("utf-8"))
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
    raise SystemExit("QQQ 데이터를 가져오지 못했습니다: %s" % last_error)


def narrowing_state(cli):
    """월별 하락폭 축소 상태를 계산한다. {period: narrowing} (하락폭을 줄인 달 수).

    하락폭을 줄인 지 2달째(narrowing == 2)가 매수 신호 월, 2달 이상(narrowing >= 2)이 매수 구간이다.
    전월비가 0 이상으로 돌아서거나 다시 하락이 심화되면 초기화한다.
    """
    state = {}
    previous = None
    deepened = False
    narrowing = 0
    for row in cli:
        mom = row["mom"]
        if mom is None:
            continue
        if previous is None:
            previous = mom
            state[row["period"]] = 0
            continue
        if mom >= 0:
            deepened = False
            narrowing = 0
        elif mom < previous:
            deepened = True
            narrowing = 0
        elif mom > previous:
            if deepened:
                narrowing += 1
            else:
                narrowing = 0
        else:
            narrowing = 0
        state[row["period"]] = narrowing
        previous = mom
    return state


def rsi_series(closes, period=RSI_PERIOD):
    """Wilder 방식 RSI. 앞 period 구간은 None. [None, ..., float, ...]"""
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

    def reading(avg_up, avg_down):
        if avg_down == 0:
            return 100.0
        rs = avg_up / avg_down
        return 100.0 - (100.0 / (1.0 + rs))

    values[period] = reading(avg_gain, avg_loss)
    for index in range(period + 1, len(closes)):
        delta = closes[index] - closes[index - 1]
        up = delta if delta > 0 else 0.0
        down = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + up) / period
        avg_loss = (avg_loss * (period - 1) + down) / period
        values[index] = reading(avg_gain, avg_loss)
    return values


def decline_run(cli):
    """월별 G20 전월비 연속 하락 개월 수. {period: n}. 전월비가 0 이상이면 0 으로 초기화한다."""
    run = {}
    current = 0
    for row in cli:
        mom = row["mom"]
        current = current + 1 if (mom is not None and mom < 0) else 0
        run[row["period"]] = current
    return run


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


def annotate_dips(dips, bars):
    for dip in dips:
        dip["lowValue"] = round(dip["lowValue"], 2)
        dip["startDate"] = bars[dip["start"]][0]
        dip["endDate"] = bars[dip["end"]][0]
        dip["lowDate"] = bars[dip["low"]][0]
    return dips


def rebound_index(series, bars, dip, limit):
    """저점보다 REBOUND 만큼 오른 첫 봉. (index, 'buy') / (None, 'fail') / (None, 'pending')"""
    target = dip["lowValue"] + REBOUND
    for index in range(dip["low"] + 1, len(series)):
        if bars[index][0] > limit:
            return None, "pending"
        value = series[index]
        if value is None:
            continue
        if value < RSI_DIP_LEVEL:
            return None, "fail"
        if value >= target:
            return index, "buy"
    return None, "pending"


def month_diff(start_day, end_day):
    """start_day(YYYY-MM-DD) 부터 end_day 까지 개월 수."""
    return ((int(end_day[0:4]) * 12 + int(end_day[5:7])) -
            (int(start_day[0:4]) * 12 + int(start_day[5:7])))


def plan_entry(window, dips30, dips35, series, bars, gate):
    """한 매수허용구간의 진입 타점. 30 이탈 3회 뒤, 35 이하(30 위) 저점에서 +REBOUND 반등이면 매수한다.

    30 이탈끼리 RESET_MONTHS 달 이상 벌어지면(앞 이탈의 끝 ~ 다음 이탈의 시작) 앞의 이탈은 무시하고 새로 센다.
    gate(day) 가 False 면 그 후보는 건너뛰고 다음 저점을 본다. (하락폭 2달 축소 / G20 2달 하락 조건)

    reason: dips = 30 이탈 3회 미만, div = 35 이하(30 위) 저점 없음, wait = +2 반등 대기.
    """
    events = []
    for dip in dips30:
        if window["from"] <= dip["startDate"] <= window["to"]:
            events.append((dip["start"], 0, dip))
    for dip in dips35:
        if dip["lowValue"] < RSI_DIP_LEVEL:
            continue                                # 30 이탈 쪽에서 이미 센다
        if window["from"] <= dip["startDate"] <= window["to"]:
            events.append((dip["start"], 1, dip))
    events.sort(key=lambda item: (item[0], item[1]))

    picked = []
    last_end = None
    for _start, kind, dip in events:
        if kind == 0:
            if last_end is not None and month_diff(last_end, dip["startDate"]) >= RESET_MONTHS:
                del picked[:]               # 1년 이상 벌어졌다. 앞의 이탈은 무시하고 새로 센다.
            picked.append(dip)              # 4번째 이후 30 이탈도 여기서 센다.
            last_end = dip["endDate"]
            continue
        if len(picked) < MIN_DIPS:
            continue                        # 30 이탈이 세 번은 있어야 한다
        trigger, status = rebound_index(series, bars, dip, window["to"])
        if status == "buy":
            if not gate(bars[trigger][0]):
                continue            # 매수 조건(하락폭 2달 축소 / G20 2달 하락) 미충족. 다음 후보를 본다.
            return {"dips": len(picked), "div": dip, "trigger": trigger, "reason": None}
        if status == "pending":
            return {"dips": len(picked), "div": dip, "trigger": None, "reason": "wait"}
        # fail: 35 이하 저점이 다시 30 아래로 내려갔다. 다음 이벤트로 넘긴다.
    return {"dips": len(picked), "div": None, "trigger": None,
            "reason": "dips" if len(picked) < MIN_DIPS else "div"}


def bar_in_month(bars, period):
    """period('YYYY-MM')의 첫 주봉을 찾는다. (index, bar) 또는 (None, None)"""
    for index, bar in enumerate(bars):
        if bar[0] >= period + "-01":
            if bar[0][:7] == period:
                return index, bar
            return None, None
    return None, None


def build_windows(cli, start_year=START_YEAR, span=WINDOW_YEARS):
    """2000년부터 span년 단위 구간을 만든다. 마지막 데이터가 있는 구간 다음에 예정 구간 하나를 더 둔다."""
    last_period = cli[-1]["period"] if cli else "%d-01" % start_year
    last_year = int(last_period[0:4])
    windows = []
    year = start_year
    while year <= last_year:
        windows.append({
            "key": "%d-%d" % (year, year + span - 1),
            "from": "%d-01-01" % year,
            "to": "%d-12-31" % (year + span - 1),
        })
        year += span
    windows.append({
        "key": "%d-%d" % (year, year + span - 1),
        "from": "%d-01-01" % year,
        "to": "%d-12-31" % (year + span - 1),
    })
    return windows


def main():
    cli = build_cli()
    weekly, meta = fetch_bars("1wk")
    daily, _ = fetch_bars("1d")
    cli = [row for row in cli if row["period"][0:4].isdigit()]
    asof = cli[-1]["period"]
    price_asof = weekly[-1][0]
    cli_by_period = {row["period"]: row for row in cli}

    # 일봉 RSI(14) 와 월별 최저 RSI(그 달에 RSI가 얼마나 내려왔는지)
    daily_closes = [bar[4] for bar in daily]
    daily_rsi = rsi_series(daily_closes)
    days = []
    month_rsi = {}
    for index, bar in enumerate(daily):
        value = daily_rsi[index]
        if value is None:
            days.append([bar[0], None])
            continue
        days.append([bar[0], round(value, 2)])
        period = bar[0][:7]
        lowest = month_rsi.get(period)
        if lowest is None or value < lowest[0]:
            month_rsi[period] = (value, bar[0])

    # 하락폭 축소 상태: 2달째(narrowing == 2)가 매수 신호 월, 2달 이상(narrowing >= 2)이 매수 구간.
    mom_state = narrowing_state(cli)
    buy_zone = {period for period, narrowing in mom_state.items() if narrowing >= 2}

    # 매수 신호 월: 매수허용구간(BUY_PERIODS) 안에 있는 2달째 월만 남긴다.
    signals = []
    for period in sorted(p for p, n in mom_state.items() if n == 2 and in_buy_period(p)):
        row = cli_by_period[period]
        index, bar = bar_in_month(weekly, period)
        lowest = month_rsi.get(period)
        signals.append({
            "period": period,
            "mom": row["mom"],
            "obs": row["obs"],
            "barDate": bar[0] if bar else None,
            "price": bar[4] if bar else None,
            "rsiMin": None if lowest is None else round(lowest[0], 2),
            "rsiMinDate": None if lowest is None else lowest[1],
        })

    # 진입 타점: QQQ 일봉 RSI(14) 30 이탈 3회 뒤, 35 이하(30 위) 저점에서 +2 반등한 날 매수.
    # 30 이탈끼리 벌어짐에 따른 리셋 기준은 두지 않는다. 하락폭 2달 이상 축소 + G20 전월비 2달 이상 하락 이후여야 한다.
    g20_run = decline_run(cli)
    dips30 = annotate_dips(find_dips(daily_rsi, RSI_DIP_LEVEL), daily)
    dips35 = annotate_dips(find_dips(daily_rsi, RSI_DIV_LEVEL), daily)

    def buy_gate(day):
        period = day[:7]
        return period in buy_zone and g20_run.get(period, 0) >= G20_MIN_MONTHS

    buys = []
    for start_year, end_year in BUY_PERIODS:
        window = {"from": "%d-01-01" % start_year, "to": "%d-12-31" % end_year}
        plan = plan_entry(window, dips30, dips35, daily_rsi, daily, buy_gate)
        if plan["trigger"] is None:
            continue
        trigger = plan["trigger"]
        day = daily[trigger][0]
        period = day[:7]
        buys.append({
            "date": day,
            "period": period,
            "window": "%d-%d" % (start_year, end_year),
            "rsi": round(daily_rsi[trigger], 2),
            "price": daily[trigger][4],
            "dips": plan["dips"],
            "divLowDate": plan["div"]["lowDate"],
            "divLowRsi": plan["div"]["lowValue"],
        })
    buys.sort(key=lambda item: item["date"])
    buy_days = buys

    # 차트용 30 이탈(strict) / 35 이하·30 위 저점 목록
    dip_pool = [{"start": dip["start"], "end": dip["end"], "low": dip["low"], "strict": 1} for dip in dips30]
    dip_pool += [{"start": dip["start"], "end": dip["end"], "low": dip["low"], "strict": 0}
                 for dip in dips35 if dip["lowValue"] >= RSI_DIP_LEVEL]
    dip_pool.sort(key=lambda item: item["start"])

    blocks = build_windows(cli)
    windows = []
    for block in blocks:
        picked = [signal["period"] for signal in signals
                  if block["from"] <= signal["period"] + "-01" <= block["to"]]
        if block["from"] > asof + "-01":
            state = "future"
        elif block["to"] < asof + "-01":
            state = "past"
        else:
            state = "active"
        windows.append({
            "key": block["key"],
            "from": block["from"],
            "to": block["to"],
            "state": state,
            "signals": picked,
        })

    payload = {
        "asof": asof,
        "priceAsof": price_asof,
        "ticker": TICKER,
        "name": meta.get("shortName") or meta.get("longName") or TICKER,
        "currency": meta.get("currency") or "USD",
        "area": "G20",
        "momDecimals": MOM_DECIMALS,
        "startYear": START_YEAR,
        "windowYears": WINDOW_YEARS,
        "rsiPeriod": RSI_PERIOD,
        "rsiDipLevel": RSI_DIP_LEVEL,
        "rsiDivLevel": RSI_DIV_LEVEL,
        "rebound": REBOUND,
        "minDips": MIN_DIPS,
        "resetMonths": RESET_MONTHS,
        "g20MinMonths": G20_MIN_MONTHS,
        "g20AsOf": cli[-1]["period"],
        "g20Run": g20_run.get(cli[-1]["period"], 0),
        "bars": weekly,
        "cli": [[row["period"], row["obs"], row["mom"]] for row in cli],
        "days": days,
        "dips": [[dip["start"], dip["end"], dip["low"], dip["strict"]] for dip in dip_pool],
        "signals": signals,
        "buyDays": buy_days,
        "buyPeriods": [[start, end] for start, end in BUY_PERIODS],
        "windows": windows,
    }
    DATA.write_text(
        "window.LEAD_DATA = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print("cli=%d %s..%s  weekly=%d  daily=%d  signals=%d  buys=%d  dips30=%d dips35=%d"
          % (len(cli), cli[0]["period"], asof, len(weekly), len(daily),
             len(signals), len(buy_days), len(dips30), len(dips35)))
    for start_year, end_year in BUY_PERIODS:
        key = "%d-%d" % (start_year, end_year)
        marks = [buy for buy in buy_days if buy["window"] == key]
        print("  %-9s %s" % (key, ", ".join(
            "%s (RSI %.2f, %d회 이탈)" % (buy["date"], buy["rsi"], buy["dips"]) for buy in marks) or "타점 없음"))


if __name__ == "__main__":
    main()
