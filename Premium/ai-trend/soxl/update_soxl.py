# -*- coding: utf-8 -*-
"""SOXL 타점: SOXX 일봉 RSI(14)가 30 아래로 네 번 내려갈 때를 매수 타점으로 본다.

경기순환사이클 하락 추정 시기(2026-2027, 2029-2030, 2033-2034)와
과거 복기(2018-2019, 2022-2023)를 같은 규칙으로 계산한다.

    python Premium/ai-trend/soxl/update_soxl.py

결과는 같은 폴더의 soxl-data.js 로 쓴다. 페이지(soxl/index.html)는 그 파일만 읽는다.
"""
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TICKER = "SOXX"
DATA = Path(__file__).with_name("soxl-data.js")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10y"
HEADERS = {"User-Agent": "Mozilla/5.0"}
RSI_PERIOD = 14
RSI_LEVEL = 30.0

# kind: past = 과거 복기, cycle = 경기순환사이클 하락 추정 시기
WINDOWS = [
    {"key": "2018-2019", "from": "2018-01-01", "to": "2019-12-31", "kind": "past"},
    {"key": "2022-2023", "from": "2022-01-01", "to": "2023-12-31", "kind": "past"},
    {"key": "2026-2027", "from": "2026-01-01", "to": "2027-12-31", "kind": "cycle"},
    {"key": "2029-2030", "from": "2029-01-01", "to": "2030-12-31", "kind": "cycle"},
    {"key": "2033-2034", "from": "2033-01-01", "to": "2034-12-31", "kind": "cycle"},
]


def fetch_bars():
    url = CHART_URL.format(ticker=TICKER)
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


def find_dips(series, level=RSI_LEVEL):
    """RSI 가 level 아래로 내려간 구간을 순서대로 모은다. 구간 사이는 30 위로 올라와야 나뉜다."""
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


def main():
    bars, meta = fetch_bars()
    closes = [bar[4] for bar in bars]
    series = rsi_series(closes)
    dips = find_dips(series)
    for dip in dips:
        dip["lowValue"] = round(dip["lowValue"], 1)
        dip["startDate"] = bars[dip["start"]][0]
        dip["lowDate"] = bars[dip["low"]][0]
        dip["lowPrice"] = bars[dip["low"]][4]

    asof = bars[-1][0]
    windows = []
    for window in WINDOWS:
        picked = [i for i, dip in enumerate(dips) if window["from"] <= dip["startDate"] <= window["to"]]
        buy = picked[3] if len(picked) >= 4 else None
        if window["from"] > asof:
            state = "future"
        elif window["to"] < asof:
            state = "past"
        else:
            state = "active"
        entry = {
            "key": window["key"],
            "from": window["from"],
            "to": window["to"],
            "kind": window["kind"],
            "state": state,
            "dips": picked,
            "buy": buy,
        }
        if buy is not None:
            entry["buyDate"] = dips[buy]["startDate"]
            entry["buyPrice"] = bars[dips[buy]["start"]][4]
            entry["lowDate"] = dips[buy]["lowDate"]
            entry["lowPrice"] = dips[buy]["lowPrice"]
        windows.append(entry)

    payload = {
        "asof": asof,
        "ticker": TICKER,
        "name": meta.get("shortName") or meta.get("longName") or TICKER,
        "currency": meta.get("currency") or "USD",
        "rsiPeriod": RSI_PERIOD,
        "rsiLevel": RSI_LEVEL,
        "bars": bars,
        "rsi": series,
        "dips": dips,
        "windows": windows,
    }
    DATA.write_text(
        "window.SOXL_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    print("bars=%d %s..%s dips=%d" % (len(bars), bars[0][0], asof, len(dips)))
    for window in windows:
        if window.get("buy") is not None:
            print("  %-9s %-7s dips=%d  BUY %s @ %s" % (window["key"], window["state"], len(window["dips"]), window["buyDate"], window["buyPrice"]))
        else:
            print("  %-9s %-7s dips=%d" % (window["key"], window["state"], len(window["dips"])))


if __name__ == "__main__":
    main()
