# -*- coding: utf-8 -*-
"""선행지수 타점: G20 경기선행지수(CLI) 전월비(mom)로 나스닥100(QQQ) 매수 타점을 계산한다.

규칙
  1. G20 전월비(mom)가 음수인 하락 구간만 본다.
  2. 하락폭이 더 커지다가(전월 대비 더 큰 하락) 하락폭을 줄이기 시작한다.
  3. 하락폭을 줄인 지 2달째 되는 달을 매수 타점으로 본다.

데이터
  - G20 CLI 월별: OECD SDMX(2000-01~) + Supabase(hangjang-table) 최신값을 덮어쓴다.
  - QQQ 주봉: Yahoo Finance(수정주가, 2000~).

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
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1wk&range=max"
HEADERS = {"User-Agent": "Mozilla/5.0"}

MOM_DECIMALS = 2    # 전월비는 소수 둘째 자리(예: -0.06%)까지. Supabase 표와 같은 규칙.
START_YEAR = 2000   # 차트/타점 시작 연도
WINDOW_YEARS = 4    # 3~4년 단위로 차트를 나눈다.


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


def fetch_bars():
    """Yahoo Finance 주봉(수정주가) 전체 이력. [[date, open, high, low, close], ...]"""
    url = CHART_URL.format(ticker=TICKER)
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


def find_signals(cli):
    """G20 전월비 하락 구간에서, 하락폭을 2달 연속 줄인 달(2달째)을 타점으로 본다."""
    result = []
    previous = None
    deepened = False
    narrowing = 0
    for row in cli:
        mom = row["mom"]
        if mom is None:
            continue
        if previous is None:
            previous = mom
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
                if narrowing == 2:
                    result.append(row)
            else:
                narrowing = 0
        else:
            narrowing = 0
        previous = mom
    return result


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
    bars, meta = fetch_bars()
    cli = [row for row in cli if row["period"][0:4].isdigit()]
    asof = cli[-1]["period"]
    price_asof = bars[-1][0]

    raw_signals = find_signals(cli)
    signals = []
    for row in raw_signals:
        index, bar = bar_in_month(bars, row["period"])
        signals.append({
            "period": row["period"],
            "mom": row["mom"],
            "obs": row["obs"],
            "barDate": bar[0] if bar else None,
            "price": bar[4] if bar else None,
        })

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
        "bars": bars,
        "cli": [[row["period"], row["obs"], row["mom"]] for row in cli],
        "signals": signals,
        "windows": windows,
    }
    DATA.write_text(
        "window.LEAD_DATA = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print("cli=%d %s..%s  bars=%d %s..%s  signals=%d"
          % (len(cli), cli[0]["period"], asof, len(bars), bars[0][0], price_asof, len(signals)))
    for window in windows:
        marks = ", ".join(window["signals"]) or "-"
        print("  %-9s %-7s %s" % (window["key"], window["state"], marks))


if __name__ == "__main__":
    main()
