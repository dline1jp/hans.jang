# -*- coding: utf-8 -*-
"""Monthly 300,000 KRW buy-and-hold with dividends reinvested.

    python Premium/hansjang/DRIP/update_drip.py

On the first session on or after the 1st of each month, invest 300,000 won.
USD and JPY prices are converted with that day's Yahoo KRW=X and JPY=X
(or the latest prior print). Korean listings are bought in won. Nothing is
sold, except the market-cap #1 sleeves, which switch leader on the documented
handoff dates. Dividends buy more of the same holding at that close.
"""
import html
import json
import re
import urllib.parse
import urllib.request
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HERE = Path(__file__).resolve().parent
PAGE = HERE / "index.html"
HUB = HERE.parent / "index.html"
REDIRECT = HERE.parents[1] / "weather" / "fujimoto" / "index.html"
KST = timezone(timedelta(hours=9))
CUTOFF = "2026-11-22"
MONTHLY_KRW = 300_000.0
TITLE = "버핏 적립보유법"
LINE = "매달 1일경 30만 원씩 넣고, 배당은 전액 다시 사며, 팔지 않는다."

INSTRUMENTS = [
    ("QQQ", "QQQ", "나스닥 100", "USD"),
    ("SPY", "SPY", "S&P 500", "USD"),
    ("VOO", "VOO", "뱅가드 S&P 500", "USD"),
    ("SMH", "SMH", "반도체 VanEck", "USD"),
    ("SOXX", "SOXX", "반도체 iShares", "USD"),
    ("SCHD", "SCHD", "슈왑 미국배당", "USD"),
    ("BTC-USD", "BTC", "비트코인", "USD"),
    ("ETH-USD", "ETH", "이더리움", "USD"),
    ("GLD", "GLD", "금", "USD"),
    ("SLV", "SLV", "은", "USD"),
    ("TLT", "TLT", "미국 장기국채", "USD"),
    ("EDV", "EDV", "미국 초장기국채", "USD"),
    ("069500.KS", "069500", "KODEX 200", "KRW"),
    ("102110.KS", "102110", "TIGER 200", "KRW"),
    ("EWY", "EWY", "한국 MSCI", "USD"),
    ("FLKR", "FLKR", "한국 FTSE", "USD"),
]

US_LEADERS = [
    ("2000-01-01", "MSFT", "마이크로소프트"),
    ("2001-01-01", "GE", "제너럴일렉트릭"),
    ("2003-01-01", "MSFT", "마이크로소프트"),
    ("2004-01-01", "GE", "제너럴일렉트릭"),
    ("2005-01-01", "XOM", "엑슨모빌"),
    ("2012-01-01", "AAPL", "애플"),
    ("2019-01-01", "MSFT", "마이크로소프트"),
    ("2021-01-01", "AAPL", "애플"),
    ("2024-01-01", "MSFT", "마이크로소프트"),
    ("2025-01-01", "AAPL", "애플"),
]
KR_LEADERS = [
    ("2000-11-21", "005930.KS", "삼성전자"),
    ("2026-06-22", "000660.KS", "SK하이닉스"),
]
# NTT Docomo (9437.T) has no Yahoo history. NTT (9432.T) was the other
# documented leader in 2000, second on the 2000-06-27 ranking, so 2000-2002
# uses that price instead of dropping the years.
JP_LEADERS = [
    ("2000-01-01", "9432.T", "NTT"),
    ("2003-01-01", "7203.T", "토요타"),
    ("2026-06-02", "9984.T", "소프트뱅크그룹"),
]


def fetch(ticker):
    start = int(datetime(1999, 12, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 11, 24, tzinfo=timezone.utc).timestamp())
    url = CHART.format(ticker=urllib.parse.quote(ticker, safe=".-="))
    query = urllib.parse.urlencode({
        "period1": start,
        "period2": end,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    })
    request = urllib.request.Request(url + "?" + query, headers={"User-Agent": "Mozilla/5.0"})
    payload = json.load(urllib.request.urlopen(request, timeout=60))
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError("no prices for " + ticker)
    block = result[0]
    rows = []
    closes = ((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    for stamp, close in zip(block.get("timestamp") or [], closes):
        if not isinstance(close, (int, float)) or close <= 0:
            continue
        day = datetime.fromtimestamp(stamp, timezone.utc).date()
        if day.isoformat() > CUTOFF:
            continue
        rows.append((day, float(close)))
    dividends = {}
    for item in ((block.get("events") or {}).get("dividends") or {}).values():
        day = datetime.fromtimestamp(item["date"], timezone.utc).date()
        amount = float(item.get("amount") or 0)
        if amount > 0 and day.isoformat() <= CUTOFF:
            dividends[day] = dividends.get(day, 0.0) + amount
    if not rows:
        raise RuntimeError("no bars for " + ticker)
    return {"rows": rows, "dividends": dividends}


def load_all(tickers):
    found = {}
    failed = []

    def one(ticker):
        try:
            return ticker, fetch(ticker), None
        except Exception as exc:
            return ticker, None, exc

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(one, ticker) for ticker in tickers]
        for future in as_completed(futures):
            ticker, payload, exc = future.result()
            if exc is not None:
                failed.append(ticker)
                print("fail", ticker, exc)
                continue
            found[ticker] = payload
            print("ok", ticker, payload["rows"][0][0], payload["rows"][-1][0], "div", len(payload["dividends"]))
    return found, failed


def lookup(pairs):
    pairs = sorted((day, rate) for day, rate in pairs if rate and rate > 0)
    dates = [day for day, _rate in pairs]
    rates = [rate for _day, rate in pairs]

    def on(day):
        index = bisect_right(dates, day) - 1
        if index < 0:
            return None
        return rates[index]

    return on, (dates[0].isoformat() if dates else None), (dates[-1].isoformat() if dates else None), set(dates)


def hold_flat_before(pairs):
    """Before the first real print, reuse that first print. Later gaps use the prior print."""
    real, first, last, have = lookup(pairs)
    anchor_day = datetime.fromisoformat(first).date()
    anchor = real(anchor_day)
    flat_months = set()
    carried_months = set()

    def on(day):
        if day < anchor_day:
            flat_months.add((day.year, day.month))
            return anchor
        if day not in have:
            carried_months.add((day.year, day.month))
        return real(day)

    return on, anchor, anchor_day, first, last, flat_months, carried_months


def leader_on(leaders, day):
    chosen = None
    for item in leaders:
        if day.isoformat() >= item[0]:
            chosen = item
    return chosen


def won(amount):
    return f"{amount:,.0f}원"


# Daily chart + 200-day SMA. Do not link drip tickers at the 200-week product.
CHART_PAGE = "/Premium/hansjang/DRIP/chart.html"
CHART_DATA = HERE / "chart-data.js"
TV_EXCHANGE = {
    "AAPL": "NASDAQ",
    "MSFT": "NASDAQ",
    "QQQ": "NASDAQ",
    "SMH": "NASDAQ",
    "SOXX": "NASDAQ",
    "GE": "NYSE",
    "XOM": "NYSE",
    "SPY": "AMEX",
    "VOO": "AMEX",
    "GLD": "AMEX",
    "SLV": "AMEX",
    "SCHD": "AMEX",
    "TLT": "AMEX",
    "EDV": "AMEX",
    "EWY": "AMEX",
    "FLKR": "AMEX",
}
TV_STUDIES = urllib.parse.quote(json.dumps([
    {
        "id": "MASimple@tv-basicstudies",
        "inputs": {"length": 200},
        "overrides": {"MovAvgSimple.color": "#E53935", "MovAvgSimple.linewidth": 2},
    },
], separators=(",", ":")))


def local_chart(ticker):
    # TradingView's embed widget rejects KRX and TSE (it reports an invalid symbol).
    return ticker.endswith(".KS") or ticker.endswith(".T")


def chart_url(ticker):
    if local_chart(ticker):
        return CHART_PAGE + "?symbol=" + urllib.parse.quote(ticker, safe=".")
    if ticker == "BTC-USD":
        symbol = "BITSTAMP:BTCUSD"
    elif ticker == "ETH-USD":
        symbol = "BITSTAMP:ETHUSD"
    else:
        symbol = TV_EXCHANGE.get(ticker, "NASDAQ") + ":" + ticker
    return (
        "https://www.tradingview.com/widgetembed/?symbol="
        + urllib.parse.quote(symbol, safe="")
        + "&interval=D&style=1&theme=dark&hideideas=1&studies="
        + TV_STUDIES
    )


def write_chart_data(books):
    payload = {}
    for ticker, book in books.items():
        if not local_chart(ticker):
            continue
        payload[ticker] = [round(price, 4) for _day, price in book["rows"]]
    CHART_DATA.write_text(
        "window.DRIP_DAILY=" + json.dumps(payload, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


def trailing_yield(book):
    rows = book["rows"]
    if not rows:
        return None
    last_day, last_price = rows[-1]
    window = last_day - timedelta(days=365)
    total = 0.0
    for day, amount in book["dividends"].items():
        if window < day <= last_day:
            total += amount
    if total <= 0 or last_price <= 0:
        return None
    return total / last_price * 100.0


def yield_text(value):
    if not value:
        return "배당 없음"
    return f"{value:.2f}%"


def xirr(flows):
    """Money-weighted annual return. Contributions are negative, the final value is positive."""
    grouped = {}
    for day, amount in flows:
        grouped[day] = grouped.get(day, 0.0) + amount
    flows = sorted(grouped.items())
    if len(flows) < 2:
        return None
    start = flows[0][0]

    def npv(rate):
        base = 1.0 + rate
        if base <= 0:
            return None
        total = 0.0
        for day, amount in flows:
            years = (day - start).days / 365.0
            total += amount / (base ** years)
        return total

    zero = npv(0.0)
    if zero is None:
        return None
    if abs(zero) < 1:
        return 0.0
    if zero > 0:
        lo = 0.0
        hi = 0.1
        while True:
            high = npv(hi)
            if high is None:
                return None
            if high <= 0 or hi >= 100:
                break
            hi *= 2
        if npv(hi) > 0:
            return None
    else:
        hi = 0.0
        lo = -0.9
        if npv(lo) is None or npv(lo) < 0:
            return None
    for _ in range(80):
        mid = (lo + hi) / 2
        val = npv(mid)
        if val is None:
            return None
        if val > 0:
            lo = mid
        else:
            hi = mid
    return ((lo + hi) / 2) * 100.0


def result_row(name, code, started, contributed, ending, dividends, ticker=""):
    gain = (ending / contributed - 1.0) * 100.0
    return {
        "name": name,
        "code": code,
        "ticker": ticker,
        "started": started,
        "contributed": contributed,
        "ending": ending,
        "gain": gain,
        "dividends": dividends,
    }


def simulate_one(rows, dividends, to_native, to_krw, floor):
    days = [day for day, _price in rows if day.isoformat() >= floor and day.isoformat() <= CUTOFF]
    price = {day: close for day, close in rows if day.isoformat() <= CUTOFF}
    if not days:
        return None
    shares = 0.0
    contributed = 0.0
    paid = 0
    seen = set()
    started = None
    last_day = None
    flows = []
    for day in days:
        close = price[day]
        last_day = day
        if shares > 0 and day in dividends:
            shares += shares * dividends[day] / close
            paid += 1
        key = (day.year, day.month)
        if key in seen:
            continue
        native = to_native(day)
        if native is None or native <= 0:
            continue
        shares += native / close
        contributed += MONTHLY_KRW
        flows.append((day, -MONTHLY_KRW))
        seen.add(key)
        if started is None:
            started = day
    if started is None or last_day is None or shares <= 0:
        return None
    ending = to_krw(shares * price[last_day], last_day)
    if ending is None:
        return None
    flows.append((last_day, ending))
    stats = result_row("", "", started.isoformat(), contributed, ending, paid)
    stats["xirr"] = xirr(flows)
    return stats


def simulate_sleeve(leaders, books, to_native, to_krw):
    needed = []
    for _start, ticker, _name in leaders:
        if ticker not in books:
            return None
        needed.append(ticker)
    price = {
        ticker: {day: close for day, close in books[ticker]["rows"] if day.isoformat() <= CUTOFF}
        for ticker in needed
    }
    dividends = {ticker: books[ticker]["dividends"] for ticker in needed}
    calendar = sorted({day for ticker in needed for day in price[ticker]})
    floor = leaders[0][0]
    calendar = [day for day in calendar if day.isoformat() >= floor and day.isoformat() <= CUTOFF]
    shares = 0.0
    held = None
    contributed = 0.0
    paid = 0
    seen = set()
    started = None
    last_day = None
    last_price = None
    flows = []
    for day in calendar:
        rule = leader_on(leaders, day)
        if rule is None:
            continue
        _start, want, _label = rule
        if held and held in dividends and day in dividends[held] and day in price[held] and shares > 0:
            shares += shares * dividends[held][day] / price[held][day]
            paid += 1
        if held != want:
            if held is not None:
                if day not in price.get(held, {}) or day not in price.get(want, {}):
                    if held in price and day in price[held]:
                        last_day = day
                        last_price = price[held][day]
                    continue
                shares = shares * price[held][day] / price[want][day]
                held = want
            elif day in price[want]:
                held = want
                shares = 0.0
        if held == want and day in price[want]:
            last_day = day
            last_price = price[want][day]
            key = (day.year, day.month)
            if key not in seen:
                native = to_native(day)
                if native is not None and native > 0:
                    shares += native / price[want][day]
                    contributed += MONTHLY_KRW
                    flows.append((day, -MONTHLY_KRW))
                    seen.add(key)
                    if started is None:
                        started = day
    if started is None or last_price is None or contributed <= 0:
        return None
    ending = to_krw(shares * last_price, last_day)
    if ending is None:
        return None
    current = leader_on(leaders, last_day)
    flows.append((last_day, ending))
    stats = result_row("", "", started.isoformat(), contributed, ending, paid, current[1])
    stats["holding"] = current[2]
    stats["xirr"] = xirr(flows)
    return stats


def converters(currency, usdkrw, usdjpy):
    def usd_native(day):
        rate = usdkrw(day)
        if not rate:
            return None
        return MONTHLY_KRW / rate

    def usd_back(amount, day):
        rate = usdkrw(day)
        if not rate:
            return None
        return amount * rate

    def jpy_native(day):
        krw = usdkrw(day)
        jpy = usdjpy(day)
        if not krw or not jpy:
            return None
        return MONTHLY_KRW / krw * jpy

    def jpy_back(amount, day):
        krw = usdkrw(day)
        jpy = usdjpy(day)
        if not krw or not jpy:
            return None
        return amount / jpy * krw

    def krw_native(_day):
        return MONTHLY_KRW

    def krw_back(amount, _day):
        return amount

    if currency == "USD":
        return usd_native, usd_back
    if currency == "JPY":
        return jpy_native, jpy_back
    return krw_native, krw_back


def name_cell(item):
    ticker = item.get("ticker") or ""
    name = html.escape(item["name"])
    if not ticker:
        return name
    href = html.escape(chart_url(ticker), quote=True)
    extra = ' target="_blank" rel="noopener"' if href.startswith("http") else ""
    return name + f' <a href="{href}"{extra}>{html.escape(ticker)}</a>'


def table_rows(rows, compact):
    body = []
    for item in rows:
        div = "" if compact else ("<td>배당 없음</td>" if item["dividends"] == 0 else "<td>배당 재투자</td>")
        end = "" if compact else f"<td>{won(item['ending'])}</td>"
        body.append(
            "<tr>"
            f"<td>{name_cell(item)}</td>"
            f"<td>{html.escape(item['started'])}</td>"
            f"<td>{won(item['contributed'])}</td>"
            f"{end}"
            f"<td>{item['gain']:+.1f}%</td>"
            f"<td>{'' if item.get('xirr') is None else format(item['xirr'], '.1f') + '%'}</td>"
            f"<td>{yield_text(item.get('yield'))}</td>"
            f"{div}"
            "</tr>"
        )
    return "".join(body)


HYBRID_ROWS = [
    ("비트코인", "BTC-USD", "+4279.5%", "56.3%", "+3918.3%", "55.0%"),
    ("반도체 VanEck", "SMH", "+2114.3%", "19.1%", "+971.6%", "15.0%"),
    ("반도체 iShares", "SOXX", "+1800.7%", "19.1%", "+712.9%", "14.0%"),
    ("미국 시총 1위", "AAPL", "+1539.5%", "17.1%", "+3911.3%", "22.1%"),
    ("나스닥 100", "QQQ", "+1109.3%", "15.4%", "+568.0%", "12.1%"),
    ("한국 시총 1위", "000660.KS", "+1042.8%", "15.6%", "+703.9%", "13.6%"),
    ("S&P 500", "SPY", "+548.5%", "11.9%", "+231.4%", "7.9%"),
    ("한국 MSCI", "EWY", "+342.3%", "9.8%", "+237.3%", "8.1%"),
    ("뱅가드 S&P 500", "VOO", "+288.6%", "15.1%", "+166.2%", "11.1%"),
    ("금", "GLD", "+242.9%", "10.0%", "+168.8%", "8.2%"),
    ("이더리움", "ETH-USD", "+237.1%", "25.7%", "+717.7%", "44.3%"),
    ("슈왑 미국배당", "SCHD", "+227.6%", "14.4%", "+85.6%", "7.7%"),
    ("TIGER 200", "102110.KS", "+216.7%", "11.9%", "+190.4%", "11.0%"),
    ("KODEX 200", "069500.KS", "+213.7%", "11.6%", "+181.0%", "10.6%"),
    ("은", "SLV", "+131.2%", "7.5%", "+140.0%", "7.8%"),
    ("한국 FTSE", "FLKR", "+113.3%", "16.3%", "+128.7%", "17.8%"),
    ("미국 장기국채", "TLT", "+41.1%", "2.7%", "+26.1%", "1.8%"),
    ("일본 시총 1위", "9984.T", "+8.1%", "0.6%", "-31.9%", "-3.0%"),
    ("미국 초장기국채", "EDV", "+1.0%", "0.1%", "+0.2%", "0.0%"),
]


def hybrid_section():
    """Reference backtest. Only the full DRIP page includes this block."""
    head = (
        "<tr><th>이름</th><th>티커</th><th>적립 수익</th><th>적립 연평균</th>"
        "<th>200일선 수익</th><th>200일선 연평균</th></tr>"
    )
    body = []
    for name, ticker, drip_gain, drip_cagr, ma_gain, ma_cagr in HYBRID_ROWS:
        href = html.escape(chart_url(ticker), quote=True)
        extra = ' target="_blank" rel="noopener"' if chart_url(ticker).startswith("http") else ""
        body.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td><a href=\"{href}\"{extra}>{html.escape(ticker)}</a></td>"
            f"<td>{html.escape(drip_gain)}</td>"
            f"<td>{html.escape(drip_cagr)}</td>"
            f"<td>{html.escape(ma_gain)}</td>"
            f"<td>{html.escape(ma_cagr)}</td>"
            "</tr>"
        )
    rules = (
        "매달 30만 원, 시작일, 환율은 위 표와 같다. 주식을 보유한 동안에만 배당을 재투자하고, "
        "현금 이자와 수수료는 없다. 일봉 종가가 200일 단순이동평균 위에 있으면 그달 30만 원을 그대로 산다. "
        "종가가 200일선 아래로 내려온 날 그 종가에 전량을 판다. 아래에 머무는 동안은 사지 않고 매달 30만 원을 현금으로 쌓는다. "
        "종가가 다시 200일선 위로 올라온 날 모아 둔 현금 전부를 그 종가에 산다. "
        "종가가 200개 쌓이기 전에는 매달 매수를 이어 간다."
    )
    why = (
        "200일선 규칙은 하락이 이미 시작된 뒤에 팔고, 가격이 늦은 평균 위로 돌아온 뒤에만 다시 산다. "
        "전량을 팔면 계좌가 전부 현금이 되었다가 더 낮은 가격에 다시 들어간다. "
        "적립은 새 30만 원만 낮은 가격에 사고, 먼저 산 주식은 그대로 둔다. "
        "그래서 낙폭이 깊고 회복이 느릴 때 하이브리드가 낫다."
    )
    cases = (
        "미국 시총 1위는 개별 주식이고, 닷컴, 2008년, 2022년처럼 200일선 아래에 깊고 오래 머물렀다. "
        "연평균은 17.1%에서 22.1%다. "
        "이더리움은 2018년과 2022년 겨울이 깊고 느렸다. 기간이 짧아 그 두 하락이 결과를 좌우한다. "
        "연평균은 25.7%와 44.3%다. "
        "은은 2011년 고점 이후의 긴 하락을 팔고 다음 상승을 샀다. 차이는 작아서 +131.2%와 +140.0%다. "
        "한국 FTSE는 2017년 말에 상장해서 2018년, 2020년, 2022년이 대부분이다. 차이도 작아서 +113.3%와 +128.7%다."
    )
    rest = (
        "나머지 15개 이름은 200일선을 금방 되찾는 때가 많다. 코로나 급락, 반도체와 나스닥의 짧은 조정, 채권의 등락이 그렇다. "
        "그 왕복은 더 낮게 팔고 더 비싸게 사며, 현금인 동안 배당을 놓친다. "
        "19개 가운데 15개는 그냥 적립이 낫다. 일본 시총 1위는 거짓 돌파가 반복되어 -31.9%로 끝났다."
    )
    scope = "이 구간은 참고용 백테스트다. 위의 본표는 팔지 않고 매달 넣는 방법이다."
    return (
        "<h2>200이평 매도 매수 하이브리드법</h2>\n"
        f'  <p class="note">{html.escape(rules)}</p>\n'
        '  <table class="hybrid">\n'
        f"    <thead>{head}</thead>\n"
        "    <tbody>\n"
        "      " + "".join(body) + "\n"
        "    </tbody>\n"
        "  </table>\n"
        f'  <p class="note">{html.escape(why)}</p>\n'
        f'  <p class="note">{html.escape(cases)}</p>\n'
        f'  <p class="note">{html.escape(rest)}</p>\n'
        f'  <p class="note">{html.escape(scope)}</p>'
    )


def full_page(rows, failed, stamped, fx_note):
    head = (
        "<tr><th>이름</th><th>시작</th><th>납입</th><th>평가액</th>"
        "<th>수익</th><th>연평균</th><th>배당률</th><th>배당</th></tr>"
    )
    missing = ""
    if failed:
        missing = "<p class=\"note\">가격이나 환율을 받지 못한 항목: " + html.escape(", ".join(failed)) + ".</p>"
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{TITLE}</title>
  <style>
    body {{ background: #111; color: #fff; font-family: "Malgun Gothic", "Apple SD Gothic Neo", Arial, sans-serif; margin: 0; padding: 16px; }}
    a {{ color: #4da3ff; }}
    .home {{ color: #D8C0FF; font-size: 22px; text-decoration: none; }}
    h1 {{ text-align: center; color: #FFFFE0; font-size: 32px; line-height: 1.35; }}
    h2 {{ text-align: center; color: #FFFFE0; font-size: 26px; line-height: 1.35; margin: 28px auto 8px; }}
    .note {{ max-width: 980px; margin: 8px auto; color: #ccc; font-size: 18px; line-height: 1.55; }}
    table {{ max-width: 980px; width: 100%; margin: 12px auto; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #333; padding: 10px 8px; text-align: right; font-size: 17px; }}
    th {{ color: #D8C0FF; }}
    td:first-child, th:first-child {{ text-align: left; }}
    table.hybrid td:nth-child(2), table.hybrid th:nth-child(2) {{ text-align: left; }}
    @media (max-width: 800px) {{
      h1 {{ font-size: 26px; }}
      h2 {{ font-size: 22px; }}
      th, td {{ font-size: 14px; padding: 8px 4px; }}
    }}
  </style>
</head>
<body>
  <p><a class="home" href="/Premium/hansjang/index.html">← 한스장 타점</a></p>
  <h1>{TITLE}</h1>
  <p class="note">{LINE} 과거 가격으로 계산한 결과이며, 앞날을 예측하지 않고 매수를 권하지 않는다. 기준 시각 {html.escape(stamped)}.</p>
  <p class="note">{html.escape(fx_note)}</p>
  <table>
    <thead>{head}</thead>
    <tbody>
      {table_rows(rows, False)}
    </tbody>
  </table>
  {missing}
  <p class="note">가격은 액면분할이 반영된 종가다. 배당이 있는 날은 이미 가진 수량에 그 배당금을 더해 같은 날 종가를 샀다. 배당 이벤트가 없으면 배당 없음이다. 수수료는 없다. 상장 전 달은 넣지 않고, 상장한 달의 첫 거래일부터 매달 30만 원을 넣는다. 2026년 11월은 그달 1일 이후 마지막 거래일까지 평가한다.</p>
  <p class="note">장마감 후 자동 업데이트된다.</p>
  {hybrid_section()}
</body>
</html>
'''


def summary_rows(rows):
    top = list(rows[:10])
    extra = [item for item in rows if item.get("ticker") == "ETH-USD" and item not in top]
    return top + extra


def top_block(rows):
    head = "<tr><th>이름</th><th>시작</th><th>납입</th><th>수익</th><th>연평균</th><th>배당률</th></tr>"
    shown = summary_rows(rows)
    note = ""
    if any(item.get("ticker") == "ETH-USD" and item not in rows[:10] for item in shown):
        note = '<p class="bond-note">이더리움은 상위 10개 밖에 있어도 아래에 따로 둔다.</p>\n'
    return (
        '<div class="drip-top">\n'
        '      <h2><a href="DRIP/index.html">' + TITLE + '</a></h2>\n'
        '      <p class="bond-note">' + LINE + '</p>\n'
        '      <table class="drip-table"><thead>' + head + '</thead><tbody>\n'
        '        ' + table_rows(shown, True) + '\n'
        '      </tbody></table>\n'
        + note +
        '      <p class="bond-note"><a href="DRIP/index.html">전체 표 보기</a></p>\n'
        '    </div>'
    )


def redirect_page():
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url=/Premium/hansjang/DRIP/index.html">
  <title>{TITLE}</title>
  <style>
    body {{ background: #111; color: #fff; font-family: "Malgun Gothic", Arial, sans-serif; padding: 24px; }}
    a {{ color: #4da3ff; font-size: 22px; }}
  </style>
</head>
<body>
  <p><a href="/Premium/hansjang/DRIP/index.html">{TITLE}</a>으로 옮겼습니다.</p>
</body>
</html>
'''


def patch_hub(block):
    text = HUB.read_text(encoding="utf-8")
    text = text.replace("버핏옹 그냥 보유법", TITLE)
    if 'href="DRIP/index.html"' not in text:
        old = '<a class="topbar-link" href="BOND/index.html">채권 타점</a></span>'
        new = old + '\n    <span class="menu-slot"><span class="menu-horizon">장기(매달 1일경 30만 원, 배당 재투자)</span><a class="topbar-link" href="DRIP/index.html">' + TITLE + '</a></span>'
        if old not in text:
            raise SystemExit("한스장 메뉴에서 채권 타점을 찾지 못했습니다.")
        text = text.replace(old, new, 1)
    pattern = re.compile(r"<!-- DRIP_TOP_START -->.*?<!-- DRIP_TOP_END -->", re.S)
    replacement = "<!-- DRIP_TOP_START -->\n    " + block + "\n    <!-- DRIP_TOP_END -->"
    if not pattern.search(text):
        raise SystemExit("DRIP_TOP 표시가 없습니다.")
    text = pattern.sub(replacement, text, count=1)
    HUB.write_text(text, encoding="utf-8")


def main():
    tickers = [item[0] for item in INSTRUMENTS] + ["KRW=X", "JPY=X"]
    for _start, ticker, _name in US_LEADERS + KR_LEADERS + JP_LEADERS:
        if ticker not in tickers:
            tickers.append(ticker)
    books, failed = load_all(tickers)
    if "KRW=X" not in books:
        raise SystemExit("KRW=X 환율을 받지 못했습니다.")
    usdkrw, krw_anchor, krw_anchor_day, krw_from, krw_to, krw_flat, krw_carried = hold_flat_before(books["KRW=X"]["rows"])
    if "JPY=X" not in books:
        failed.append("JPY=X")
        usdjpy = lambda _day: None
        jpy_from = jpy_to = None
        jpy_anchor = None
        jpy_anchor_day = None
    else:
        usdjpy, jpy_anchor, jpy_anchor_day, jpy_from, jpy_to, _jpy_flat, _jpy_carried = hold_flat_before(books["JPY=X"]["rows"])
    print("USDKRW anchor", krw_anchor_day, krw_anchor, "series", krw_from, "->", krw_to)
    print("USDJPY", jpy_from, "->", jpy_to, "anchor", jpy_anchor_day, jpy_anchor)

    rows = []
    for ticker, code, name, currency in INSTRUMENTS:
        if ticker not in books:
            if ticker not in failed:
                failed.append(ticker)
            continue
        to_native, to_krw = converters(currency, usdkrw, usdjpy)
        stats = simulate_one(books[ticker]["rows"], books[ticker]["dividends"], to_native, to_krw, "2000-01-01")
        if stats is None:
            failed.append(ticker)
            print("calc fail", code)
            continue
        stats["name"] = name
        stats["code"] = code
        stats["ticker"] = ticker
        stats["yield"] = trailing_yield(books[ticker])
        if stats["dividends"] == 0:
            pass
        rows.append(stats)
        print(code, stats["started"], won(stats["contributed"]), won(stats["ending"]), f'{stats["gain"]:+.1f}%', "div" if stats["dividends"] else "nodiv")

    sleeves = [
        ("미국 시총 1위", "US#1", US_LEADERS, "USD"),
        ("한국 시총 1위", "KR#1", KR_LEADERS, "KRW"),
        ("일본 시총 1위", "JP#1", [item for item in JP_LEADERS if item[1] in books], "JPY"),
    ]
    for name, code, leaders, currency in sleeves:
        if not leaders:
            failed.append(code)
            continue
        to_native, to_krw = converters(currency, usdkrw, usdjpy)
        stats = simulate_sleeve(leaders, books, to_native, to_krw)
        if stats is None:
            failed.append(code)
            print("sleeve fail", name)
            continue
        stats["name"] = name
        stats["code"] = code
        if stats.get("ticker") in books:
            stats["yield"] = trailing_yield(books[stats["ticker"]])
        rows.append(stats)
        print(name, stats["started"], won(stats["contributed"]), f'{stats["gain"]:+.1f}%')

    rows.sort(key=lambda item: item["gain"], reverse=True)
    fx_note = (
        "미국 시총 1위는 아메리칸 비즈니스 히스토리 센터의 연도별 1분기 순위를 그해 첫 거래일에 교체한 것이다. 2000년 1월은 마이크로소프트다. 일별 순위가 아니다. "
        "한국은 2000-11-21부터 삼성전자, 2026-06-22 종가부터는 보통주 기준 SK하이닉스다. "
        "일본은 NTT도코모(9437.T) 시세가 없어 2000년부터 2002년까지는 2000년 6월 27일 순위에서 2위였던 NTT(9432.T)를 보유로 계산했다. 2003년부터 토요타, 2026-06-02 보도부터 소프트뱅크그룹이다."
    )
    print("flat months", len(krw_flat), "carried", len(krw_carried))
    stamped = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    shown_failed = []
    for item in failed:
        if item == "9437.T":
            shown_failed.append("NTT도코모(9437.T)")
        elif item not in shown_failed:
            shown_failed.append(item)
    write_chart_data(books)
    PAGE.write_text(full_page(rows, shown_failed, stamped, fx_note), encoding="utf-8")
    patch_hub(top_block(rows))
    REDIRECT.parent.mkdir(parents=True, exist_ok=True)
    REDIRECT.write_text(redirect_page(), encoding="utf-8")
    print("failed", shown_failed)
    print("wrote", PAGE)
    print("patched", HUB)


if __name__ == "__main__":
    main()
