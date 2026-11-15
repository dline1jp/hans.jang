# -*- coding: utf-8 -*-
"""AI 혁신주 동향: quarterly EPS bars and bullish-divergence double-bottom proximity.

Run on the same weekday schedule as the other Premium updates
(22:30 UTC, Monday-Friday, after the US cash close):

    python Premium/ai-trend/update_ai.py

Those workflows each call one existing script. This script is separate and
does not change them.
"""
import calendar
import html
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
NAVER_FINANCE = "https://m.stock.naver.com/api/stock/{code}/finance/quarter"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGE = Path(__file__).with_name("index.html")
KST = timezone(timedelta(hours=9))

DAILY = {"wing": 5, "min_sep": 8, "max_sep": 80, "lookback": 140}
WEEKLY = {"wing": 3, "min_sep": 3, "max_sep": 26, "lookback": 80}

US_GROUPS = [
    ("전력·그리드", [
        ("GEV", "GE Vernova"),
        ("CEG", "Constellation Energy"),
        ("VST", "Vistra"),
        ("ETN", "Eaton"),
        ("POWL", "Powell Industries"),
    ]),
    ("데이터센터·클라우드", [
        ("AMZN", "Amazon"),
        ("MSFT", "Microsoft"),
        ("GOOGL", "Alphabet"),
        ("STX", "Seagate"),
        ("META", "Meta"),
        ("ORCL", "Oracle"),
        ("NBIS", "Nebius"),
    ]),
    ("AI 칩", [
        ("NVDA", "NVIDIA"),
        ("AMD", "AMD"),
        ("ALAB", "Astera Labs"),
        ("AVGO", "Broadcom"),
        ("MRVL", "Marvell"),
        ("MU", "Micron"),
        ("CLS", "Celestica"),
    ]),
    ("냉각·전력관리", [
        ("VRT", "Vertiv"),
        ("ETN", "Eaton"),
    ]),
    ("ESS·SMR", [
        ("NEE", "NextEra Energy"),
        ("CEG", "Constellation Energy"),
        ("VST", "Vistra"),
        ("OKLO", "Oklo"),
        ("SMR", "NuScale"),
        ("CRDO", "Credo"),
    ]),
    ("비트코인에서 데이터센터", [
        ("IREN", "IREN"),
        ("MARA", "MARA"),
        ("RIOT", "Riot Platforms"),
        ("WULF", "TeraWulf"),
        ("CORZ", "Core Scientific"),
    ]),
    ("AI 보안", [
        ("PLTR", "Palantir"),
        ("PANW", "Palo Alto Networks"),
    ]),
    ("기타", [
        ("AVGO", "Broadcom"),
    ]),
]

KR_GROUPS = [
    ("전력망·전력장비", [
        ("298040.KS", "효성중공업"),
        ("000500.KS", "가온전선"),
        ("267260.KS", "HD현대일렉트릭"),
        ("010120.KS", "LS일렉트릭"),
    ]),
    ("데이터센터·클라우드", [
        ("017670.KS", "SK텔레콤"),
        ("030200.KS", "KT"),
    ]),
    ("AI 가속기·반도체·메모리", [
        ("005930.KS", "삼성전자"),
        ("000660.KS", "SK하이닉스"),
    ]),
    ("냉각·전력관리", [
        ("417200.KQ", "LS머트리얼즈"),
        ("298040.KS", "효성중공업"),
        ("083450.KQ", "지에스티"),
    ]),
    ("ESS·SMR", [
        ("373220.KS", "LG에너지솔루션"),
        ("034020.KS", "두산에너빌리티"),
        ("006400.KS", "삼성SDI"),
        ("010120.KS", "LS일렉트릭"),
    ]),
    ("기타", [
        ("307950.KS", "현대오토에버"),
        ("042700.KQ", "한미반도체"),
    ]),
]


def dedupe(groups):
    order = []
    found = {}
    for group, items in groups:
        for ticker, name in items:
            row = found.get(ticker)
            if row is None:
                row = {"ticker": ticker, "name": name, "groups": [], "market": ""}
                found[ticker] = row
                order.append(row)
            if group not in row["groups"]:
                row["groups"].append(group)
    return order


def display_code(ticker):
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return ticker.split(".")[0]
    return ticker


def raw_num(node):
    if isinstance(node, (int, float)):
        return float(node)
    if isinstance(node, dict):
        value = node.get("raw")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def parse_eps(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("원", "")
    if text in {"", "-", "N/A", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def yahoo_session():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    session.get("https://fc.yahoo.com", timeout=20)
    crumb = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
    if not crumb or crumb.startswith("{") or crumb.startswith("<"):
        raise RuntimeError("Yahoo crumb failed")
    return session, crumb


def fetch_bars(ticker):
    quoted = urllib.parse.quote(ticker, safe=".-")
    for attempt in range(4):
        try:
            response = requests.get(
                CHART_URL.format(ticker=quoted),
                params={
                    "interval": "1d",
                    "range": "5y",
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
            result = (response.json().get("chart") or {}).get("result") or []
            if not result:
                time.sleep(0.8 * (attempt + 1))
                continue
            block = result[0]
            meta = block.get("meta") or {}
            stamps = block.get("timestamp") or []
            quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
            adjusted = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
            highs = quote.get("high") or []
            lows = quote.get("low") or []
            closes = quote.get("close") or []
            bars = []
            seen = set()
            for index, stamp in enumerate(stamps):
                close = closes[index] if index < len(closes) else None
                high = highs[index] if index < len(highs) else None
                low = lows[index] if index < len(lows) else None
                adj = adjusted[index] if adjusted and index < len(adjusted) else None
                if not all(isinstance(value, (int, float)) and value > 0 for value in (close, high, low)):
                    continue
                factor = adj / close if isinstance(adj, (int, float)) and adj > 0 else 1.0
                day = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
                bar = {
                    "date": day,
                    "high": float(high) * factor,
                    "low": float(low) * factor,
                    "close": float(close) * factor,
                }
                if bar["high"] < bar["low"]:
                    continue
                if day in seen:
                    bars = [item for item in bars if item["date"] != day]
                seen.add(day)
                bars.append(bar)
            if bars:
                return {
                    "bars": bars,
                    "market_name": meta.get("shortName") or meta.get("longName") or "",
                    "currency": meta.get("currency") or "",
                }
        except (requests.RequestException, ValueError, KeyError, TypeError):
            time.sleep(0.8 * (attempt + 1))
    return None


def weekly_bars(bars):
    buckets = {}
    order = []
    for bar in bars:
        year, week, _ = datetime.fromisoformat(bar["date"]).isocalendar()
        key = (year, week)
        if key not in buckets:
            buckets[key] = {
                "date": bar["date"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
            }
            order.append(key)
            continue
        row = buckets[key]
        row["high"] = max(row["high"], bar["high"])
        row["low"] = min(row["low"], bar["low"])
        row["close"] = bar["close"]
        row["date"] = bar["date"]
    return [buckets[key] for key in order]


def rsi_series(closes, period=14):
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
        return 100.0 - (100.0 / (1.0 + avg_up / avg_down))

    values[period] = reading(avg_gain, avg_loss)
    for index in range(period + 1, len(closes)):
        delta = closes[index] - closes[index - 1]
        up = delta if delta > 0 else 0.0
        down = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + up) / period
        avg_loss = (avg_loss * (period - 1) + down) / period
        values[index] = reading(avg_gain, avg_loss)
    return values


def ema_series(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    acc = sum(values[:period]) / period
    out[period - 1] = acc
    weight = 2 / (period + 1)
    for index in range(period, len(values)):
        acc = values[index] * weight + acc * (1 - weight)
        out[index] = acc
    return out


def macd_line(closes):
    fast = ema_series(closes, 12)
    slow = ema_series(closes, 26)
    out = [None] * len(closes)
    for index, (left, right) in enumerate(zip(fast, slow)):
        if left is not None and right is not None:
            out[index] = left - right
    return out


def swing_lows(lows, wing):
    found = []
    last = len(lows) - wing
    for index in range(wing, last):
        price = lows[index]
        if price < min(lows[index - wing:index]) and price < min(lows[index + 1:index + wing + 1]):
            found.append(index)
    return found


def clamp_score(value):
    return max(0.0, min(100.0, value))


def indicator_score(newer, older, span):
    if newer is None or older is None or span <= 0:
        return 0.0
    if newer > older:
        return 100.0
    return min(99.0, clamp_score(100.0 * (1 - (older - newer) / span)))


def price_score(low1, low2):
    if low1 <= 0 or low2 <= 0:
        return 0.0
    distance = abs(low2 - low1) / low1
    if distance <= 0.03:
        return 100.0
    if distance >= 0.10:
        return 0.0
    return clamp_score(100.0 * (1 - (distance - 0.03) / 0.07))


def score_bars(bars, spec):
    empty = {"percent": 0, "price": 0, "macd": 0, "rsi": 0, "low1": "", "low2": "", "formed": False}
    if not bars:
        return empty
    closes = [bar["close"] for bar in bars]
    lows = [bar["low"] for bar in bars]
    highs = [bar["high"] for bar in bars]
    macd = macd_line(closes)
    rsi = rsi_series(closes)
    start = max(0, len(bars) - spec["lookback"])
    swings = [index for index in swing_lows(lows, spec["wing"]) if index >= start]
    if not swings:
        return empty
    later = swings[-1]
    earlier = None
    for index in reversed(swings[:-1]):
        gap = later - index
        if gap < spec["min_sep"] or gap > spec["max_sep"]:
            continue
        peak = max(highs[index + 1:later])
        base = max(lows[index], lows[later])
        if base <= 0 or peak < base * 1.03:
            continue
        earlier = index
        break
    if earlier is None:
        return empty
    low1 = lows[earlier]
    low2 = lows[later]
    ratio = low2 / low1 if low1 else 0
    window = [value for value in macd[start:] if value is not None]
    macd_span = (max(window) - min(window)) if window else 0.0
    p_score = price_score(low1, low2)
    m_score = indicator_score(macd[later], macd[earlier], macd_span)
    r_score = indicator_score(rsi[later], rsi[earlier], 15.0)
    formed = (
        0.95 <= ratio <= 1.03
        and macd[later] is not None
        and macd[earlier] is not None
        and macd[later] > macd[earlier]
        and rsi[later] is not None
        and rsi[earlier] is not None
        and rsi[later] > rsi[earlier]
    )
    if formed:
        percent = 100
    else:
        percent = min(99, int(0.34 * p_score + 0.33 * m_score + 0.33 * r_score + 0.5))
    return {
        "percent": percent,
        "price": int(p_score + 0.5),
        "macd": int(m_score + 0.5),
        "rsi": int(r_score + 0.5),
        "low1": bars[earlier]["date"],
        "low2": bars[later]["date"],
        "formed": formed,
    }


def yahoo_eps(session, crumb, ticker):
    quoted = urllib.parse.quote(ticker, safe=".-")
    for attempt in range(3):
        try:
            response = session.get(
                SUMMARY_URL.format(ticker=quoted),
                params={"modules": "earnings", "crumb": crumb},
                timeout=30,
            )
            if response.status_code in (401, 429, 500, 502, 503):
                time.sleep(1.2 * (attempt + 1))
                continue
            response.raise_for_status()
            result = (response.json().get("quoteSummary") or {}).get("result") or []
            if not result:
                return []
            quarterly = ((result[0].get("earnings") or {}).get("earningsChart") or {}).get("quarterly") or []
            points = []
            for row in quarterly:
                period = row.get("periodEndDate") or {}
                points.append({
                    "label": row.get("date") or period.get("fmt") or "",
                    "end": period.get("fmt") or "",
                    "eps": raw_num(row.get("actual")),
                })
            points.sort(key=lambda point: point["end"] or point["label"])
            return points
        except (requests.RequestException, ValueError, KeyError, TypeError):
            time.sleep(0.8 * (attempt + 1))
    return []


def naver_eps(ticker):
    code = ticker.split(".")[0]
    if not (len(code) == 6 and code.isdigit()):
        return []
    for attempt in range(3):
        try:
            response = requests.get(
                NAVER_FINANCE.format(code=code),
                headers=HEADERS,
                timeout=30,
            )
            if response.status_code in (429, 500, 502, 503):
                time.sleep(1.2 * (attempt + 1))
                continue
            response.raise_for_status()
            info = (response.json().get("financeInfo") or {})
            titles = info.get("trTitleList") or []
            rows = info.get("rowList") or []
            eps_row = next((row for row in rows if row.get("title") == "EPS"), None)
            if not eps_row:
                return []
            columns = eps_row.get("columns") or {}
            points = []
            for col in titles:
                if col.get("isConsensus") == "Y":
                    continue
                key = str(col.get("key") or "")
                if len(key) != 6 or not key.isdigit():
                    continue
                year = int(key[:4])
                month = int(key[4:])
                last_day = calendar.monthrange(year, month)[1]
                points.append({
                    "label": col.get("title") or key,
                    "end": f"{year:04d}-{month:02d}-{last_day:02d}",
                    "eps": parse_eps((columns.get(key) or {}).get("value")),
                })
            points.sort(key=lambda point: point["end"])
            return points
        except (requests.RequestException, ValueError, KeyError, TypeError):
            time.sleep(0.8 * (attempt + 1))
    return []


def series_key(points):
    actuals = [point["end"] for point in points if point["eps"] is not None and point["end"]]
    latest = max(actuals) if actuals else ""
    return latest, len(actuals)


def choose_eps(yahoo_points, naver_points):
    choices = []
    if yahoo_points:
        choices.append(("Yahoo Finance", yahoo_points))
    if naver_points:
        choices.append(("네이버금융", naver_points))
    if not choices:
        return "", []
    source, points = max(choices, key=lambda item: series_key(item[1]))
    return source, points[-3:]


def same_eps(left, right, currency):
    if currency == "KRW":
        return round(left) == round(right)
    return round(left, 4) == round(right, 4)


def eps_label(points, currency):
    if len(points) < 2 or points[-1]["eps"] is None or points[-2]["eps"] is None:
        return "비교 불가", "flat"
    latest = points[-1]["eps"]
    prior = points[-2]["eps"]
    if same_eps(latest, prior, currency):
        return "보합", "flat"
    if latest > prior:
        return "매수후보", "up"
    return "매수보류", "down"


def fmt_eps(value, currency):
    if currency == "KRW":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def fmt_price(value, currency):
    if currency in ("KRW", "JPY"):
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def eps_svg(points, currency):
    if not points or all(point["eps"] is None for point in points):
        return '<p class="missing">실적 없음</p>'
    values = [point["eps"] for point in points if point["eps"] is not None]
    low = min(0.0, min(values))
    high = max(0.0, max(values))
    if high == low:
        high += 1.0
        low -= 1.0
    width, height = 360, 156
    pad_left, pad_right, pad_top, pad_bottom = 8, 8, 18, 40
    plot_h = height - pad_top - pad_bottom
    gap = (width - pad_left - pad_right) / len(points)

    def y_of(value):
        return pad_top + (high - value) / (high - low) * plot_h

    zero_y = y_of(0)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="주가순이익">']
    parts.append(
        f'<line x1="{pad_left}" y1="{zero_y:.1f}" x2="{width - pad_right}" y2="{zero_y:.1f}" stroke="#555"/>'
    )
    for index, point in enumerate(points):
        center = pad_left + gap * index + gap / 2
        label = html.escape(point["label"])
        parts.append(
            f'<text x="{center:.1f}" y="{height - 22}" text-anchor="middle" fill="#ccc" font-size="11">{label}</text>'
        )
        if point["eps"] is None:
            parts.append(
                f'<text x="{center:.1f}" y="{height - 8}" text-anchor="middle" fill="#888" font-size="11">없음</text>'
            )
            continue
        y_value = y_of(point["eps"])
        top = min(y_value, zero_y)
        bar_h = max(1.0, abs(zero_y - y_value))
        color = "#7dcea0" if point["eps"] >= 0 else "#f1948a"
        bar_w = gap * 0.52
        parts.append(
            f'<rect x="{center - bar_w / 2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}"/>'
        )
        text_y = max(12, top - 4) if point["eps"] >= 0 else min(height - 44, top + bar_h + 12)
        parts.append(
            f'<text x="{center:.1f}" y="{text_y:.1f}" text-anchor="middle" fill="#fff" font-size="11">{html.escape(fmt_eps(point["eps"], currency))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def pct_html(score):
    if not score or (not score["low1"] and score["percent"] == 0 and score["price"] == 0):
        detail = "확정된 스윙 저점 쌍이 없습니다."
    else:
        state = "쌍바닥 상승다이버전스" if score["formed"] else "아직 쌍바닥 상승다이버전스가 아닙니다"
        detail = (
            f'{html.escape(score["low1"])} / {html.escape(score["low2"])} · '
            f'가격 {score["price"]}% · MACD {score["macd"]}% · RSI {score["rsi"]}% · {state}'
        )
    return (
        f'<p class="pct"><b>{score["percent"]}%</b></p>'
        f'<p class="sub">{detail}</p>'
    )


def card_html(stock):
    code = display_code(stock["ticker"])
    tags = " · ".join(html.escape(group) for group in stock["groups"])
    currency = stock.get("currency") or ""
    unit = "원" if currency == "KRW" else ("USD" if currency == "USD" else currency)
    points = stock.get("eps") or []
    label, kind = eps_label(points, currency) if points else ("실적 없음", "flat")
    if not points or all(point["eps"] is None for point in points):
        label, kind = "실적 없음", "flat"
    source = stock.get("eps_source") or ""
    source_line = f"출처 {html.escape(source)}" if source and label != "실적 없음" else "발표된 분기 EPS가 없습니다."
    price = stock.get("close")
    price_line = "시세 없음" if price is None else f'{html.escape(stock.get("date") or "")} 종가 {fmt_price(price, currency)} {html.escape(unit)}'
    daily = stock.get("daily") or {"percent": 0, "price": 0, "macd": 0, "rsi": 0, "low1": "", "low2": "", "formed": False}
    weekly = stock.get("weekly") or daily
    if price is None:
        daily_html = '<p class="pct"><b>계산 불가</b></p><p class="sub">일봉 시세가 없습니다.</p>'
        weekly_html = '<p class="pct"><b>계산 불가</b></p><p class="sub">주봉을 만들 시세가 없습니다.</p>'
    else:
        daily_html = pct_html(daily)
        weekly_html = pct_html(weekly)
    chart = "chart.html?" + urllib.parse.urlencode({"symbol": code, "name": stock["name"]})
    return f'''<article class="card" id="{html.escape(code)}">
      <h3><a href="{html.escape(chart)}"><span class="ticker">{html.escape(code)}</span> {html.escape(stock["name"])}</a></h3>
      <p class="tags">{tags}</p>
      <p class="asof">{price_line}</p>
      <p><span class="badge {kind}">{html.escape(label)}</span></p>
      <p class="frame">주가순이익</p>
      {eps_svg(points, currency)}
      <p class="sub">{source_line} · 단위 {html.escape(unit) if unit else "-"} · 직전 분기 대비</p>
      <p class="frame">일봉</p>
      {daily_html}
      <p class="frame">주봉</p>
      {weekly_html}
    </article>'''


def page_html(us_rows, kr_rows, stamped):
    us_cards = "\n".join(card_html(row) for row in us_rows)
    kr_cards = "\n".join(card_html(row) for row in kr_rows)
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 혁신주 타점</title>
  <style>
    body {{ background: #111; color: #fff; font-family: "Malgun Gothic", "Apple SD Gothic Neo", Arial, sans-serif; margin: 0; padding: 16px; }}
    a {{ color: #4da3ff; }}
    .home {{ color: #D8C0FF; font-size: 28px; text-decoration: none; }}
    h1 {{ text-align: center; color: #FFFFE0; font-size: 32px; line-height: 1.35; }}
    .warn {{ max-width: 980px; margin: 12px auto; background: #3a2a12; color: #ffe08a; border: 1px solid #8a6a2a; border-radius: 12px; padding: 14px 16px; font-size: 20px; line-height: 1.5; font-weight: 700; }}
    .note, .groups {{ max-width: 980px; margin: 8px auto; color: #ccc; font-size: 16px; line-height: 1.55; }}
    .groups h2, .rules h2 {{ color: #FFFFE0; font-size: 22px; margin: 18px 0 8px; }}
    .groups ul {{ margin: 0 0 8px; padding-left: 1.2em; }}
    h2.market {{ max-width: 1100px; margin: 28px auto 8px; color: #FFFFE0; font-size: 28px; }}
    .grid {{ max-width: 1100px; margin: 0 auto 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .card {{ border: 1px solid #444; border-radius: 12px; padding: 14px 14px 10px; background: #181818; }}
    .card h3 {{ margin: 0 0 4px; font-size: 22px; }}
    .ticker {{ color: #D8C0FF; }}
    .tags, .asof, .sub {{ color: #aaa; font-size: 14px; line-height: 1.45; }}
    .badge {{ display: inline-block; margin-top: 6px; padding: 4px 10px; border-radius: 999px; font-weight: 700; font-size: 18px; }}
    .badge.up {{ background: #143024; color: #7dcea0; }}
    .badge.down {{ background: #3a1c1c; color: #f1948a; }}
    .badge.flat {{ background: #2c2c2c; color: #ddd; }}
    .missing {{ color: #ccc; font-size: 18px; }}
    svg {{ width: 100%; height: auto; background: #0c0c0c; border: 1px solid #333; border-radius: 8px; }}
    .frame {{ margin: 10px 0 0; color: #D8C0FF; font-weight: 700; }}
    .pct {{ margin: 2px 0; }}
    .pct b {{ font-size: 28px; color: #fff; }}
    @media (max-width: 800px) {{
      h1 {{ font-size: 26px; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <p><a class="home" href="/index.html">← 처음</a></p>
  <h1>AI 혁신주 타점</h1>
  <p class="warn">투자 권유가 아닙니다. 참고용. 매수후보·매수보류는 최근 분기 주당순이익이 바로 앞 분기보다 늘었는지 줄었는지만 표시합니다.</p>
  <p class="note">기준 시각 {html.escape(stamped)}. 시세는 종목별 마지막 거래일의 수정주가입니다. 평일 미국장 마감 후 <code>python Premium/ai-trend/update_ai.py</code>로 갱신합니다.</p>
  <section class="groups">
    <h2>산업 구분 (참고)</h2>
    <p>아래는 요청에 적힌 구분입니다. 종목 카드는 상장 시장마다 한 번씩만 보여 주고, 겹치는 산업은 카드 안에 같이 적습니다.</p>
    <h2>국주</h2>
    <ul>
      <li>전력망·전력장비: 효성중공업, LS전선, 가온전선, HD현대일렉트릭, LS일렉트릭</li>
      <li>데이터센터·클라우드: SK텔레콤, KT, 네이버클라우드</li>
      <li>AI 가속기·반도체·메모리: 삼성전자, SK하이닉스</li>
      <li>냉각·전력관리: LS머트리얼즈, 효성중공업</li>
      <li>ESS·SMR: LG에너지솔루션, 두산에너빌리티, 삼성SDI, LS일렉트릭</li>
      <li>기타: 현대오토에버, 한미반도체</li>
    </ul>
    <h2>미국주</h2>
    <ul>
      <li>전력·그리드: GEV (GE Vernova), CEG, VST, ETN (Eaton), POWL (Powell Industries)</li>
      <li>데이터센터·클라우드: AMZN, MSFT, GOOGL, STX, META, ORCL, NBIS</li>
      <li>AI 칩: NVDA, AMD, ALAB, AVGO, MRVL, MU, CLS</li>
      <li>냉각·전력관리: VRT (Vertiv), GST, ETN</li>
      <li>ESS·SMR: NEE, CEG, VST, OKLO, SMR (NuScale), CRDO</li>
      <li>비트코인에서 데이터센터: IREN, MARA, RIOT, WULF, CORZ</li>
      <li>AI 보안: PLTR, PANW</li>
      <li>기타: AVGO</li>
    </ul>
    <p>LS전선은 별도 상장사가 아니라 카드에서 뺐습니다. 네이버클라우드도 네이버의 비상장 자회사라 카드에서 뺐습니다. 미국 티커 GST는 냉각 회사가 아닙니다. 냉각·전력관리의 GST는 코스닥 지에스티(Global Standard Technology, 083450)라서 국주에 넣었습니다.</p>
  </section>
  <section class="rules note">
    <h2>쌍바닥 상승다이버전스 퍼센트</h2>
    <p>일봉과 주봉을 따로 계산합니다. MACD선은 12기간 지수이동평균에서 26기간 지수이동평균을 뺀 값이고, RSI는 14기간 Wilder입니다. 가격은 수정주가의 고가·저가·종가입니다.</p>
    <p>스윙 저점은 일봉은 좌우 5봉, 주봉은 좌우 3봉보다 저가가 낮은 봉입니다. 오른쪽이 아직 안 찬 최근 봉은 빼서 확정된 저점만 씁니다. 가장 최근 스윙 저점과, 그보다 일봉 8~80봉(주봉 3~26봉) 앞의 스윙 저점을 비교합니다. 두 저점 사이에 고가가 두 저점보다 3% 이상 높아야 합니다. 이런 쌍이 없으면 0%입니다.</p>
    <p>100%는 둘째 저가가 첫째 저가의 95% 이상 103% 이하이고, 둘째 저점의 MACD선과 RSI가 둘 다 첫째 저점보다 높을 때만입니다. 하나라도 아니면 가격 비슷함 34%, MACD 33%, RSI 33%를 더해 99를 넘기지 않습니다. 가격 점수는 저가 차이가 3% 이내면 100, 10% 이상이면 0입니다. RSI는 둘째가 더 높으면 100, 15포인트 이상 낮으면 0입니다. MACD는 둘째가 더 높으면 100, 아니면 그 차이를 최근 구간의 MACD 폭으로 나눕니다. 지표가 같거나 낮으면 그 지표 점수는 99를 넘지 않습니다.</p>
    <p>분기 주당순이익은 발표된 실제치만 씁니다. 추정치는 쓰지 않습니다. 미국 종목은 Yahoo Finance, 한국 종목은 Yahoo Finance와 네이버금융 중 실제치 최근 분기가 더 새로운 쪽입니다. 네이버 컨센서스 열은 뺍니다. 숫자가 없으면 실적 없음입니다. 바로 앞 분기와 비교할 수 없으면 비교 불가입니다.</p>
  </section>
  <h2 class="market">1. 미국주</h2>
  <div class="grid">
    {us_cards}
  </div>
  <h2 class="market">2. 국주</h2>
  <div class="grid">
    {kr_cards}
  </div>
</body>
</html>
'''


def attach_market(rows, session, crumb):
    def load_price(row):
        payload = fetch_bars(row["ticker"])
        return row["ticker"], payload

    prices = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(load_price, row) for row in rows]
        for future in as_completed(futures):
            ticker, payload = future.result()
            prices[ticker] = payload

    for row in rows:
        payload = prices.get(row["ticker"])
        if not payload:
            row["bars"] = None
            row["close"] = None
            row["date"] = ""
            row["currency"] = "KRW" if row["ticker"].endswith((".KS", ".KQ")) else "USD"
            row["daily"] = None
            row["weekly"] = None
            print("price miss", row["ticker"])
            continue
        row["bars"] = payload["bars"]
        row["close"] = payload["bars"][-1]["close"]
        row["date"] = payload["bars"][-1]["date"]
        row["currency"] = payload["currency"] or row.get("currency") or ""
        row["daily"] = score_bars(payload["bars"], DAILY)
        row["weekly"] = score_bars(weekly_bars(payload["bars"]), WEEKLY)
        print(
            "price",
            row["ticker"],
            row["date"],
            f'{row["close"]:.4f}',
            "D",
            row["daily"]["percent"],
            "W",
            row["weekly"]["percent"],
        )

    for row in rows:
        yahoo_points = yahoo_eps(session, crumb, row["ticker"])
        naver_points = naver_eps(row["ticker"]) if row["ticker"].endswith((".KS", ".KQ")) else []
        source, points = choose_eps(yahoo_points, naver_points)
        row["eps_source"] = source
        row["eps"] = points
        label, _ = eps_label(points, row.get("currency") or "")
        shown = ", ".join(
            f'{point["label"]}={fmt_eps(point["eps"], row.get("currency") or "") if point["eps"] is not None else "없음"}'
            for point in points
        )
        print("eps", row["ticker"], source, label, shown)
        time.sleep(0.15)


def self_test():
    closes = [50.0] * 80
    for index, value in enumerate((46, 40, 32, 30)):
        closes[37 + index] = value
    for index in range(41, 80):
        closes[index] = 50
    closes[61] = 48
    bars = []
    for index, close in enumerate(closes):
        bars.append({
            "date": f"d{index:03d}",
            "high": max(close, 50) + 1,
            "low": close - 0.2,
            "close": close,
        })
    bars[40]["low"] = 28
    bars[61]["low"] = 27.2
    bars[50]["high"] = 60
    spec = {"wing": 2, "min_sep": 5, "max_sep": 40, "lookback": 80}
    formed = score_bars(bars, spec)
    if formed["percent"] != 100 or not formed["formed"]:
        raise RuntimeError(f"expected a formed double bottom, got {formed}")
    bars[61]["low"] = 10
    broken = score_bars(bars, spec)
    if broken["percent"] == 100:
        raise RuntimeError(f"price far from the first low must not be 100, got {broken}")
    flat = [{"date": "2024-01-01", "high": 10.0, "low": 9.0, "close": 9.5} for _ in range(30)]
    none = score_bars(flat, DAILY)
    if none["percent"] != 0:
        raise RuntimeError(f"no swing pair must be 0, got {none}")


def main():
    self_test()
    us_rows = dedupe(US_GROUPS)
    kr_rows = dedupe(KR_GROUPS)
    for row in us_rows:
        row["market"] = "us"
    for row in kr_rows:
        row["market"] = "kr"
    session, crumb = yahoo_session()
    attach_market(us_rows, session, crumb)
    attach_market(kr_rows, session, crumb)
    priced = sum(1 for row in us_rows + kr_rows if row.get("close") is not None)
    total = len(us_rows) + len(kr_rows)
    if priced < total * 0.7:
        raise SystemExit(f"too few prices {priced}/{total}; page not written")
    stamped = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    PAGE.write_text(page_html(us_rows, kr_rows, stamped), encoding="utf-8")
    print(f"wrote {PAGE} prices {priced}/{total}")


if __name__ == "__main__":
    main()
