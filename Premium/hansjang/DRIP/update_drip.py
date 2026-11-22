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
JP_LEADERS = [
    ("2000-01-01", "9437.T", "NTT도코모"),
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

    return on, (dates[0].isoformat() if dates else None), (dates[-1].isoformat() if dates else None)


def leader_on(leaders, day):
    chosen = None
    for item in leaders:
        if day.isoformat() >= item[0]:
            chosen = item
    return chosen


def won(amount):
    return f"{amount:,.0f}원"


CHART_ON_HANJANG = {"QQQ", "SPY", "VOO", "SMH", "SOXX", "SCHD", "BTC-USD", "GLD", "SLV"}
TV_EXCHANGE = {
    "AAPL": "NASDAQ",
    "MSFT": "NASDAQ",
    "TLT": "AMEX",
    "EDV": "AMEX",
    "EWY": "AMEX",
    "FLKR": "AMEX",
    "GE": "NYSE",
    "XOM": "NYSE",
}


def chart_url(ticker):
    if ticker in CHART_ON_HANJANG:
        return "/Premium/hansjang/200W/index.html?symbol=" + urllib.parse.quote(ticker)
    if ticker == "ETH-USD":
        symbol = "BINANCE:ETHUSDT"
    elif ticker.endswith(".KS"):
        symbol = "KRX:" + ticker[:-3]
    elif ticker.endswith(".T"):
        symbol = "TSE:" + ticker[:-2]
    else:
        symbol = TV_EXCHANGE.get(ticker, "NASDAQ") + ":" + ticker
    return "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(symbol) + "&interval=D"


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
        seen.add(key)
        if started is None:
            started = day
    if started is None or last_day is None or shares <= 0:
        return None
    ending = to_krw(shares * price[last_day], last_day)
    if ending is None:
        return None
    return result_row("", "", started.isoformat(), contributed, ending, paid)


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
                    seen.add(key)
                    if started is None:
                        started = day
    if started is None or last_price is None or contributed <= 0:
        return None
    ending = to_krw(shares * last_price, last_day)
    if ending is None:
        return None
    current = leader_on(leaders, last_day)
    stats = result_row("", "", started.isoformat(), contributed, ending, paid, current[1])
    stats["holding"] = current[2]
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
            f"<td>{yield_text(item.get('yield'))}</td>"
            f"{div}"
            "</tr>"
        )
    return "".join(body)


def full_page(rows, failed, stamped, fx_note):
    head = (
        "<tr><th>이름</th><th>시작</th><th>납입</th><th>평가액</th>"
        "<th>수익</th><th>배당률</th><th>배당</th></tr>"
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
    .note {{ max-width: 980px; margin: 8px auto; color: #ccc; font-size: 18px; line-height: 1.55; }}
    table {{ max-width: 980px; width: 100%; margin: 12px auto; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #333; padding: 10px 8px; text-align: right; font-size: 17px; }}
    th {{ color: #D8C0FF; }}
    td:first-child, th:first-child {{ text-align: left; }}
    @media (max-width: 800px) {{
      h1 {{ font-size: 26px; }}
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
  <p class="note">평일 마감 후 <code>python Premium/hansjang/DRIP/update_drip.py</code>로 다시 계산한다.</p>
</body>
</html>
'''


def top_block(rows):
    head = "<tr><th>이름</th><th>시작</th><th>납입</th><th>수익</th><th>배당률</th></tr>"
    return (
        '<div class="drip-top">\n'
        '      <h2><a href="DRIP/index.html">' + TITLE + '</a></h2>\n'
        '      <p class="bond-note">' + LINE + '</p>\n'
        '      <table class="drip-table"><thead>' + head + '</thead><tbody>\n'
        '        ' + table_rows(rows[:10], True) + '\n'
        '      </tbody></table>\n'
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
    usdkrw, krw_from, krw_to = lookup(books["KRW=X"]["rows"])
    if "JPY=X" not in books:
        failed.append("JPY=X")
        usdjpy = lambda _day: None
        jpy_from = jpy_to = None
    else:
        usdjpy, jpy_from, jpy_to = lookup(books["JPY=X"]["rows"])
    print("USDKRW", krw_from, usdkrw(datetime.fromisoformat(krw_from).date()) if krw_from else None, "->", krw_to)
    print("USDJPY", jpy_from, "->", jpy_to)

    fx_note = (
        "원/달러(KRW=X) 시세는 2003-12-01부터라, 달러와 엔으로 사는 종목은 그달부터 30만 원을 넣었다. "
        "2000년 1월부터 2003년 11월은 환율이 없어 넣지 않았다. "
        "원화 종목인 KODEX 200, TIGER 200, 한국 시총 1위는 상장일 또는 교체일부터 바로 30만 원을 넣는다. "
        "달러 자산은 넣는 날의 원/달러로 바꾸고, 일본 시총 1위는 원/달러와 달러/엔(JPY=X)으로 엔화로 바꾼다. "
        "그날 환율이 없으면 그 이전 최근 환율을 쓴다. 평가는 마지막 거래일 환율로 다시 원화로 환산한다. "
        f"KRW=X {krw_from}~{krw_to}, JPY=X {jpy_from}~{jpy_to}. "
        "미국 시총 1위는 아메리칸 비즈니스 히스토리 센터의 연도별 1분기 순위를 그해 첫 거래일에 교체한 것이다. 일별 순위가 아니다. "
        "한국은 2000-11-21부터 삼성전자, 2026-06-22 종가부터는 보통주 기준 SK하이닉스다. "
        "일본은 NTT도코모 시세를 받지 못했고 환율도 2003-12-01부터라 그날 토요타부터 넣었으며, 2026-06-02 보도부터 소프트뱅크그룹이다."
    )

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
    stamped = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    shown_failed = []
    for item in failed:
        if item == "9437.T":
            shown_failed.append("NTT도코모(9437.T)")
        elif item not in shown_failed:
            shown_failed.append(item)
    PAGE.write_text(full_page(rows, shown_failed, stamped, fx_note), encoding="utf-8")
    patch_hub(top_block(rows))
    REDIRECT.parent.mkdir(parents=True, exist_ok=True)
    REDIRECT.write_text(redirect_page(), encoding="utf-8")
    print("failed", shown_failed)
    print("wrote", PAGE)
    print("patched", HUB)


if __name__ == "__main__":
    main()
