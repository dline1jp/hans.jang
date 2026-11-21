# -*- coding: utf-8 -*-
"""한스장 시크리컬 200주 매수타점 페이지를 주 1회(토요일) 갱신합니다.

계산 방식 (index.html 의 표/서머리와 같은 규칙)
- 종가 = 야후 주봉(1wk) 수정종가의 마지막 값
- 200주선 = 최근 200개 주봉 종가의 단순평균
- 확률 = round(200주선 / 종가 * 100), 100 을 넘으면 100
- 200주선 대비 = (종가 / 200주선 - 1) * 100
- 색 구분: 확률 90% 이상 buy, 80% 이상 wait, 그 아래 miss

갱신 대상
1. Premium/hansjang/200W/index.html  (기준일 / 서머리 카드 / 표 / MA_SERIES)
2. Premium/hansjang/summary-data.js  (상단 소개 페이지가 읽는 서머리 데이터)
3. Premium/hansjang/index.html       (상단 소개 페이지의 기준일 안내문)
"""
import datetime
import html
import json
import pathlib
import re
import time
import urllib.parse

import requests

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "index.html"
SUMMARY_JS = HERE.parent / "summary-data.js"
LANDING = HERE.parent / "index.html"

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HEADERS = {"User-Agent": "Mozilla/5.0"}
WEEKS = 200
BUY_PROB = 90
WAIT_PROB = 80
SUMMARY_PRIMARY = "QQQ"

# (ticker, label, name)  name 은 표/카드에 보이는 이름
SYMBOLS = [
    ("QQQ", "QQQ", "Invesco QQQ"),
    ("SPY", "SPY", "SPDR S&P 500 ETF"),
    ("VOO", "VOO", "Vanguard S&P 500 ETF"),
    ("SMH", "SMH", "VanEck 반도체 ETF"),
    ("SOXX", "SOXX", "iShares 반도체 ETF"),
    ("SCHD", "SCHD", "Schwab 미국 배당주 ETF"),
    ("BTC-USD", "BTC-USD", "비트코인"),
    ("GLD", "GLD", "SPDR 금 ETF"),
    ("SLV", "SLV", "iShares 은 ETF"),
]


def weekly_closes(ticker):
    """야후 주봉 수정종가를 [(date, close), ...] 로 돌려줍니다."""
    for attempt in range(4):
        try:
            response = requests.get(
                CHART_URL.format(ticker=urllib.parse.quote(ticker, safe="")),
                params={
                    "interval": "1wk",
                    # range=max 는 야후가 월봉 수준으로 다운샘플하므로 30년을 씁니다.
                    "range": "30y",
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
                value = adj[index] if index < len(adj) else None
                if not isinstance(value, (int, float)):
                    value = raw[index] if index < len(raw) else None
                if not isinstance(value, (int, float)):
                    continue
                stamp_date = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).date()
                bars.append((stamp_date, round(float(value), 4)))
            if len(bars) >= WEEKS:
                return bars
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(0.8 * (attempt + 1))
    return None


def score(ticker, label, name):
    bars = weekly_closes(ticker)
    if not bars:
        return None
    closes = [close for _date, close in bars]
    close = closes[-1]
    ma = sum(closes[-WEEKS:]) / float(WEEKS)
    prob = min(100, int(round(ma / close * 100.0)))
    gap = (close / ma - 1.0) * 100.0
    if prob >= BUY_PROB:
        cls = "buy"
    elif prob >= WAIT_PROB:
        cls = "wait"
    else:
        cls = "miss"
    return {
        "ticker": ticker,
        "label": label,
        "name": name,
        "closes": closes,
        "date": bars[-1][0],
        "close": close,
        "ma": ma,
        "prob": prob,
        "gap": gap,
        "cls": cls,
    }


def money(value):
    return "{:,.2f}".format(value)


def percent(value):
    return "{:+.1f}%".format(value)


def summary_tickers(rows):
    """서머리 카드에 넣을 2종목: QQQ + 확률이 가장 높은 종목."""
    others = [row for row in rows if row["ticker"] != SUMMARY_PRIMARY]
    others.sort(key=lambda row: -row["prob"])
    picks = [SUMMARY_PRIMARY]
    if others:
        picks.append(others[0]["ticker"])
    return picks


def render_row(row, picks):
    anchor = ' id="row-%s"' % row["ticker"] if row["ticker"] in picks else ""
    return (
        '<tr class="%s"%s><td class="code" data-label="종목">'
        '<a href="index.html?symbol=%s">%s</a></td>'
        '<td class="name" data-label="이름">%s</td>'
        '<td data-label="종가">%s</td>'
        '<td data-label="200주선">%s</td>'
        '<td class="prob" data-label="확률">%d%%</td></tr>'
        % (
            row["cls"],
            anchor,
            html.escape(row["ticker"]),
            html.escape(row["label"]),
            html.escape(row["name"]),
            money(row["close"]),
            money(row["ma"]),
            row["prob"],
        )
    )


def render_card(row):
    gap = row["gap"]
    if gap > 0:
        desc = (
            "시세가 200주선보다 %s%% 위에 있어 아직 매수 구간이 아닙니다. "
            "200주선에 가까워질수록 확률이 높아지고, 200주선 아래로 내려오면 100%%가 됩니다. "
            "아래 그래프는 클릭 없이 바로 보이는 주봉 종가(회색)와 200주선(빨강)입니다."
            % "{:.1f}".format(abs(gap))
        )
    else:
        desc = (
            "시세가 200주선 아래로 내려와 확률 100%인 종목입니다. 다만 버블기 종목은 예외로 봅니다. "
            "아래 그래프는 클릭 없이 바로 보이는 주봉 종가(회색)와 200주선(빨강)입니다."
        )
    return (
        '<div class="stock-card %s">\n'
        "  <h2>%s · %s · 확률 %d%%</h2>\n"
        '  <p class="stock-meta">종가 %s · 200주선 %s · 200주선 대비 %s</p>\n'
        '  <p class="stock-desc">%s</p>\n'
        '  <p class="ma-legend"><i class="ma200"></i>200주선 <i class="mapx"></i>주봉 종가</p>\n'
        '  <canvas class="mini-canvas" data-symbol="%s" width="1100" height="220"></canvas>\n'
        '  <p class="jump"><a href="#row-%s">▼ 표에서 %s 행 보기</a></p>\n'
        "</div>"
        % (
            row["cls"],
            html.escape(row["label"]),
            html.escape(row["name"]),
            row["prob"],
            money(row["close"]),
            money(row["ma"]),
            percent(gap),
            desc,
            html.escape(row["ticker"]),
            html.escape(row["ticker"]),
            html.escape(row["label"]),
        )
    )


def series_json(rows):
    payload = {}
    for row in rows:
        payload[row["ticker"]] = {
            "label": row["label"],
            "name": row["name"],
            "closes": row["closes"],
        }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def summary_json(rows):
    picks = summary_tickers(rows)
    payload = {}
    for row in rows:
        if row["ticker"] not in picks:
            continue
        payload[row["ticker"]] = {
            "symbol": row["ticker"],
            "label": row["label"],
            "name": row["name"],
            "close": round(row["close"], 2),
            "ma": round(row["ma"], 2),
            "prob": row["prob"],
            "gap": round(row["gap"], 2),
            "cls": row["cls"],
            "closes": row["closes"],
        }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    order = json.dumps(picks, ensure_ascii=False)
    return "window.MA_SUMMARY_ORDER = %s;\nwindow.MA_SUMMARY = %s;\n" % (order, body)


def replace_region(text, start, end, body):
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit("%s / %s 표시가 없습니다." % (start, end))
    return pattern.sub(lambda _match: start + "\n" + body + "\n" + end, text, count=1)


def main():
    rows = []
    for ticker, label, name in SYMBOLS:
        row = score(ticker, label, name)
        if row is None:
            raise SystemExit("%s 주봉 데이터를 받지 못했습니다." % ticker)
        rows.append(row)
        print(
            "%-8s %-22s close=%12s ma200=%12s prob=%3d%% gap=%s"
            % (ticker, name, money(row["close"]), money(row["ma"]), row["prob"], percent(row["gap"]))
        )
        time.sleep(0.2)

    picks = summary_tickers(rows)
    picked = [row for row in rows if row["ticker"] in picks]
    picked.sort(key=lambda row: picks.index(row["ticker"]))

    asof = max(row["date"] for row in rows)
    asof = asof + datetime.timedelta(days=4 - asof.weekday())
    today = datetime.datetime.now(datetime.timezone.utc).date()
    if asof > today:
        asof = today

    text = PAGE.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"

    note = (
        '<p class="note">기준일 %s. 시세가 200주 이동평균선에 접근할수록 확률이 높아지고, '
        "200주선 아래로 내려오면 100%%입니다. 시세가 200주선에 내려오면 분할 매수를 검토할 수 있습니다. </p>"
        % asof.isoformat()
    )
    text, count = re.subn(r'<p class="note">.*?</p>', lambda _match: note, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit("기준일 안내문(.note)을 찾지 못했습니다.")

    summary_body = newline.join(
        ['    <section class="summary">']
        + ["      " + render_card(row).replace("\n", newline + "      ") for row in picked]
        + ["    </section>"]
    )
    rows_body = newline.join(render_row(row, picks) for row in rows)
    series_body = '  <script>window.MA_SERIES = %s;</script>' % series_json(rows)

    text = replace_region(text, "<!-- SUMMARY_START -->", "<!-- SUMMARY_END -->", summary_body)
    text = replace_region(text, "<!-- ROWS_START -->", "<!-- ROWS_END -->", rows_body)
    text = replace_region(text, "<!-- SERIES_START -->", "<!-- SERIES_END -->", series_body)

    with open(str(PAGE), "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    with open(str(SUMMARY_JS), "w", encoding="utf-8", newline="") as handle:
        handle.write(summary_json(rows).replace("\n", newline))

    # 상단 소개 페이지의 기준일 안내문도 같은 날짜로 맞춥니다.
    landing_text = LANDING.read_text(encoding="utf-8")
    landing_text = replace_region(landing_text, "<!-- NOTE_START -->", "<!-- NOTE_END -->", note)
    with open(str(LANDING), "w", encoding="utf-8", newline="") as handle:
        handle.write(landing_text)

    print()
    print("서머리 카드: %s" % ", ".join(picks))
    print("기준일: %s" % asof.isoformat())
    print("갱신 완료: %s" % PAGE)
    print("갱신 완료: %s" % SUMMARY_JS)
    print("갱신 완료: %s" % LANDING)


if __name__ == "__main__":
    main()
