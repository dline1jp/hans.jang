# -*- coding: utf-8 -*-
"""미국 장기채권(TLT·EDV) vs TNX 주봉 20년 차트 데이터를 갱신합니다.

- 야후 파이낸스 주봉(1wk) 20년 종가를 읽어 Premium/hansjang/BOND/index.html 의
  window.BOND_SERIES 를 새로 심고, 기준일 안내문(.note)을 갱신합니다.
- GitHub Actions(.github/workflows/update-bond.yml)에서 매주 토요일 실행합니다.
"""
import datetime
import json
import pathlib
import re
import time
import urllib.parse

import requests

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "index.html"

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HEADERS = {"User-Agent": "Mozilla/5.0"}
RANGE = "20y"

# (ticker, label, name)  label 은 BOND_SERIES 키로도 씁니다.
SYMBOLS = [
    ("TLT", "TLT", "iShares 20+년 국채 ETF"),
    ("EDV", "EDV", "Vanguard 초장기 국채 ETF"),
    ("^TNX", "TNX", "미국 10년 국채금리"),
]


def weekly_closes(ticker):
    """야후 주봉 수정종가를 [(date, close), ...] 로 돌려줍니다."""
    for attempt in range(4):
        try:
            response = requests.get(
                CHART_URL.format(ticker=urllib.parse.quote(ticker, safe="")),
                params={
                    "interval": "1wk",
                    "range": RANGE,
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
            payload = response.json()
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                time.sleep(0.8 * (attempt + 1))
                continue
            stamps = result[0].get("timestamp") or []
            indicators = result[0].get("indicators") or {}
            adj = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
            raw = (indicators.get("quote") or [{}])[0].get("close") or []
            bars = []
            for index, stamp in enumerate(stamps):
                value = raw[index] if index < len(raw) else None
                if not isinstance(value, (int, float)):
                    value = adj[index] if index < len(adj) else None
                if not isinstance(value, (int, float)):
                    continue
                stamp_date = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).date()
                bars.append((stamp_date, round(float(value), 4)))
            if len(bars) >= 200:
                return bars
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(0.8 * (attempt + 1))
    return None


def series_json(rows, asof):
    payload = {"asof": asof}
    for row in rows:
        payload[row["label"]] = {
            "label": row["label"],
            "name": row["name"],
            "dates": row["dates"],
            "closes": row["closes"],
        }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return body.replace("<", "\\u003c")


def replace_region(text, start, end, body):
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit("%s / %s 표시가 없습니다." % (start, end))
    return pattern.sub(lambda _match: start + "\n" + body + "\n" + end, text, count=1)


def main():
    rows = []
    for ticker, label, name in SYMBOLS:
        bars = weekly_closes(ticker)
        if not bars:
            raise SystemExit("%s 주봉 데이터를 받지 못했습니다." % ticker)
        dates = [bar_date.isoformat() for bar_date, _close in bars]
        closes = [close for _bar_date, close in bars]
        rows.append({"label": label, "name": name, "dates": dates, "closes": closes})
        print(
            "%-5s %-24s %s ~ %s bars=%d last=%s"
            % (label, name, dates[0], dates[-1], len(closes), closes[-1])
        )
        time.sleep(0.2)

    asof = max(row["dates"][-1] for row in rows)
    note = (
        '<p class="note">기준일 %s. TLT·EDV(미국 장기국채 ETF)와 TNX(미국 10년 국채금리)의 '
        "주봉 20년 차트입니다. 클릭 없이 바로 보이며, 데이터는 매주 자동 갱신됩니다.</p>" % asof
    )

    text = PAGE.read_text(encoding="utf-8")
    text = replace_region(text, "<!-- NOTE_START -->", "<!-- NOTE_END -->", note)
    body = "  <script>window.BOND_SERIES = %s;</script>" % series_json(rows, asof)
    text = replace_region(text, "<!-- SERIES_START -->", "<!-- SERIES_END -->", body)

    with open(str(PAGE), "w", encoding="utf-8", newline="") as handle:
        handle.write(text)

    print()
    print("기준일: %s" % asof)
    print("갱신 완료: %s" % PAGE)


if __name__ == "__main__":
    main()