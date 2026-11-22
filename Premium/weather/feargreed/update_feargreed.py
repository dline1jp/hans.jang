# -*- coding: utf-8 -*-
"""CNN 공포·탐욕 지수(Fear & Greed) 기반 QQQ·SPY·VOO 분할매수 시그널 페이지를 매일 갱신합니다.

- CNN 공포·탐욕 지수(https://edition.cnn.com/markets/fear-and-greed)를 읽어
  지수가 10 이하이면 QQQ·SPY·VOO 분할매수 시그널로 표시합니다.
- CNN 공포지수 차트와 QQQ 차트를 한 화면에 겹쳐 그립니다.
- 이 신호는 장타(몇년)가 아니라 중타(몇달, 매매 기간 몇개월) 기준입니다.
- 결과를 Premium/weather/feargreed/index.html 의 FEARGREED_DATA 로 심고 기준일 안내문을 갱신합니다.
- GitHub Actions(.github/workflows/update-feargreed.yml)에서 미국장 마감 후 실행합니다.

규칙 요약
- 시그널 ON  : CNN 공포·탐욕 지수 <= 10 (극단적 공포)  -> QQQ/SPY/VOO 분할매수, 표시 확률 100%
- 시그널 OFF : CNN 공포·탐욕 지수 > 10              -> 대기, 남은 하락폭(=score-10)을 표시
"""
import datetime
import json
import pathlib
import re
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "index.html"
SUMMARY = HERE / "feargreed-summary.js"

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%s"
CNN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cnn.com/",
}
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

THRESHOLD = 10.0
HORIZON = "중단타(몇달이내)"
SPLITS = 5
TARGETS = [
    ("QQQ", "Invesco QQQ Trust"),
    ("SPY", "SPDR S&P 500 ETF"),
    ("VOO", "Vanguard S&P 500 ETF"),
]
RATING_KO = {
    "extreme fear": "극단적 공포",
    "fear": "공포",
    "neutral": "중립",
    "greed": "탐욕",
    "extreme greed": "극단적 탐욕",
}
FORWARD_DAYS = 63  # 약 3개월(거래일) 뒤 주가로 시그널 이후 성과를 참고 계산합니다.


def fetch_fng():
    """CNN 공포·탐욕 지수 (현재값, 일별 이력) 을 읽어옵니다."""
    for attempt in range(5):
        try:
            response = requests.get(CNN_URL, headers=CNN_HEADERS, timeout=30)
            if response.status_code in (418, 429, 500, 502, 503):
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json()
            current = payload.get("fear_and_greed") or {}
            hist = (payload.get("fear_and_greed_historical") or {}).get("data") or []
            if not current or not hist:
                time.sleep(0.8 * (attempt + 1))
                continue
            return current, hist
        except (requests.RequestException, ValueError):
            time.sleep(0.8 * (attempt + 1))
    return None, None


def fetch_closes(symbol):
    """야후 파이낸스 일봉 종가를 {date(iso): close} 로 돌려줍니다."""
    for attempt in range(4):
        try:
            response = requests.get(
                YAHOO_URL % symbol,
                params={"interval": "1d", "range": "2y", "events": "div,splits"},
                headers=YAHOO_HEADERS,
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
            out = {}
            for index, stamp in enumerate(stamps):
                value = close[index] if index < len(close) else None
                if not isinstance(value, (int, float)):
                    continue
                bar_date = datetime.datetime.fromtimestamp(
                    stamp, datetime.timezone.utc
                ).date().isoformat()
                out[bar_date] = round(float(value), 2)
            if out:
                return out
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(0.8 * (attempt + 1))
    return {}


def build_series(hist, qqq_closes):
    """CNN 이력(날짜별 지수)과 QQQ 종가를 같은 날짜 축으로 정렬합니다."""
    by_date = {}
    for point in hist:
        value = point.get("y")
        stamp = point.get("x")
        if not isinstance(value, (int, float)) or not isinstance(stamp, (int, float)):
            continue
        iso = datetime.datetime.fromtimestamp(
            stamp / 1000.0, datetime.timezone.utc
        ).date().isoformat()
        by_date[iso] = round(float(value), 2)

    dates = sorted(by_date)
    fng = [by_date[day] for day in dates]
    qqq = []
    last = None
    for day in dates:
        if day in qqq_closes:
            last = qqq_closes[day]
        qqq.append(last)
    return dates, fng, qqq



def forward_stat(dates, fng, qqq):
    """지수가 10 이하로 진입한 뒤 약 3개월 뒤 QQQ 성과를 참고용으로 계산합니다."""
    episodes = 0
    returns = []
    in_zone = False
    for index, value in enumerate(fng):
        if value is not None and value <= THRESHOLD:
            if not in_zone:
                in_zone = True
                episodes += 1
                target = index + FORWARD_DAYS
                if target < len(qqq) and qqq[index] and qqq[target]:
                    returns.append((qqq[target] / qqq[index] - 1.0) * 100.0)
        else:
            in_zone = False
    avg = round(sum(returns) / len(returns), 1) if returns else None
    best = round(max(returns), 1) if returns else None
    worst = round(min(returns), 1) if returns else None
    return {
        "episodes": episodes,
        "forwardDays": FORWARD_DAYS,
        "forwardAvg": avg,
        "forwardBest": best,
        "forwardWorst": worst,
        "forwardCount": len(returns),
    }


def make_targets(price_map):
    targets = []
    for symbol, name in TARGETS:
        closes = price_map.get(symbol) or {}
        price = None
        asof = None
        if closes:
            asof = max(closes)
            price = closes[asof]
        targets.append(
            {
                "symbol": symbol,
                "name": name,
                "price": price,
                "splits": SPLITS,
                "priceAsof": asof,
            }
        )
    return targets


def build_state():
    current, hist = fetch_fng()
    if not current or not hist:
        raise SystemExit("CNN 공포·탐욕 지수를 받지 못했습니다.")

    price_map = {}
    for symbol, _name in TARGETS:
        price_map[symbol] = fetch_closes(symbol)
    if not price_map.get("QQQ"):
        raise SystemExit("QQQ 일봉 데이터를 받지 못했습니다.")

    dates, fng, qqq = build_series(hist, price_map["QQQ"])
    if len(dates) < 30:
        raise SystemExit("CNN 이력 데이터가 부족합니다.")

    score = round(float(current.get("score", fng[-1])), 2)
    rating = str(current.get("rating") or "").strip()
    signal_on = score <= THRESHOLD

    def rnd(value):
        return round(float(value), 2) if isinstance(value, (int, float)) else None

    return {
        "asof": max(price_map["QQQ"]),
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "score": score,
        "rating": rating,
        "ratingKo": RATING_KO.get(rating, rating),
        "timestamp": current.get("timestamp"),
        "previousClose": rnd(current.get("previous_close")),
        "previous1Week": rnd(current.get("previous_1_week")),
        "previous1Month": rnd(current.get("previous_1_month")),
        "previous1Year": rnd(current.get("previous_1_year")),
        "threshold": THRESHOLD,
        "signalOn": signal_on,
        "probability": 100,
        "horizon": HORIZON,
        "splits": SPLITS,
        "stats": forward_stat(dates, fng, qqq),
        "targets": make_targets(price_map),
        "chart": {"dates": dates, "fng": fng, "qqq": qqq},
    }



def series_json(state):
    body = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    return "  <script>window.FEARGREED_DATA = %s;</script>" % body.replace("<", "\\u003c")


def replace_region(text, start, end, body):
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit("%s / %s 표시가 없습니다." % (start, end))
    return pattern.sub(lambda _match: start + "\n" + body + "\n" + end, text, count=1)


def make_summary(state):
    """주가 방향 날씨 페이지의 서머리에 넣을 CNN 공포지수 요약을 만듭니다."""
    return {
        "asof": state["asof"],
        "score": state["score"],
        "rating": state["rating"],
        "ratingKo": state["ratingKo"],
        "threshold": state["threshold"],
        "signalOn": state["signalOn"],
        "probability": state["probability"],
        "horizon": state["horizon"],
        "splits": state["splits"],
        "targets": [
            {"symbol": target["symbol"], "name": target["name"], "price": target["price"]}
            for target in state["targets"]
        ],
        "chart": state["chart"],
    }


def summary_json(summary):
    body = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    return "window.FEARGREED_SUMMARY = %s;" % body.replace("<", "\\u003c")


def main():
    state = build_state()

    if state["signalOn"]:
        signal_text = "시그널 ON · 지수 %s 이하" % ("{:g}".format(state["threshold"]))
    else:
        signal_text = "시그널 대기 · 지수 %s 이하에서 ON" % ("{:g}".format(state["threshold"]))

    note = (
        '<p class="note">기준일 %s · CNN 공포·탐욕 지수 %s (%s) · %s · '
        "이 신호는 장타가 아닌 중타(몇달) 기준입니다 · 미국장 마감 후 매일 자동 갱신</p>"
        % (
            state["asof"],
            "{:.2f}".format(state["score"]),
            state["ratingKo"],
            signal_text,
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
        "기준일 %s | 공포지수 %.2f (%s) | 시그널 %s | 확률 %d%% | QQQ %s"
        % (
            state["asof"],
            state["score"],
            state["ratingKo"],
            "ON" if state["signalOn"] else "OFF",
            state["probability"],
            "{:,.2f}".format(state["targets"][0]["price"] or 0),
        )
    )
    print("갱신 완료:", PAGE)


if __name__ == "__main__":
    main()

