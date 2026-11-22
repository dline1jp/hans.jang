# -*- coding: utf-8 -*-
"""Buy-and-hold total return with dividends reinvested.

    python Premium/weather/fujimoto/update_fujimoto.py

Prices are Yahoo split-adjusted closes. Dividends are Yahoo cash dividends,
reinvested at that session's close. There is no commission.
"""
import html
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
PAGE = Path(__file__).with_name("index.html")
KST = timezone(timedelta(hours=9))
START_CASH = 10000.0
CUTOFF = "2026-11-22"

# Single-name holdings. Dividends, when Yahoo lists them, are reinvested.
INSTRUMENTS = [
    ("QQQ", "QQQ", "나스닥 100"),
    ("SPY", "SPY", "S&P 500"),
    ("VOO", "VOO", "뱅가드 S&P 500"),
    ("SMH", "SMH", "반도체 VanEck"),
    ("SOXX", "SOXX", "반도체 iShares"),
    ("SCHD", "SCHD", "슈왑 미국배당"),
    ("BTC-USD", "BTC", "비트코인"),
    ("ETH-USD", "ETH", "이더리움"),
    ("GLD", "GLD", "금"),
    ("SLV", "SLV", "은"),
    ("TLT", "TLT", "미국 장기국채"),
    ("EDV", "EDV", "미국 초장기국채"),
    ("069500.KS", "069500", "KODEX 200"),
    ("102110.KS", "102110", "TIGER 200"),
    ("EWY", "EWY", "한국 MSCI"),
    ("FLKR", "FLKR", "한국 FTSE"),
]

# Annual Q1 market-cap leader, American Business History Center via Visual Capitalist.
# Switched on the first session on or after January 1 of that year, not a daily tape.
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
# Korea common-stock leader: Samsung from 2000-11-21, SK hynix from the 2026-06-22 close.
KR_LEADERS = [
    ("2000-11-21", "005930.KS", "삼성전자"),
    ("2026-06-22", "000660.KS", "SK하이닉스"),
]
# Japan: NTT Docomo led a June 2000 ranking; Toyota was reported as #1 from 2003;
# SoftBank Group was reported ahead of Toyota on 2026-06-02.
JP_LEADERS = [
    ("2000-01-01", "9437.T", "NTT도코모"),
    ("2003-01-01", "7203.T", "토요타"),
    ("2026-06-02", "9984.T", "소프트뱅크그룹"),
]


def fetch(ticker):
    start = int(datetime(1999, 12, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 11, 24, tzinfo=timezone.utc).timestamp())
    url = CHART.format(ticker=urllib.parse.quote(ticker, safe=".-"))
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
        raise RuntimeError(f"no prices for {ticker}")
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
        if amount > 0:
            dividends[day] = dividends.get(day, 0.0) + amount
    if not rows:
        raise RuntimeError(f"no bars for {ticker}")
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


def hold_return(rows, dividends):
    usable = [(day, price) for day, price in rows if day.isoformat() >= "2000-01-01"]
    if not usable:
        usable = rows
    shares = START_CASH / usable[0][1]
    paid = 0
    for index, (day, price) in enumerate(usable):
        if index == 0 or day not in dividends:
            continue
        shares += shares * dividends[day] / price
        paid += 1
    end = shares * usable[-1][1]
    years = max((usable[-1][0] - usable[0][0]).days, 1) / 365.25
    return {
        "started": usable[0][0].isoformat(),
        "ended": usable[-1][0].isoformat(),
        "return_pct": (end / START_CASH - 1.0) * 100.0,
        "cagr": ((end / START_CASH) ** (1.0 / years) - 1.0) * 100.0,
        "dividends": paid,
    }


def leader_on(leaders, day):
    chosen = leaders[0]
    for item in leaders:
        if day.isoformat() >= item[0]:
            chosen = item
    return chosen


def sleeve_return(leaders, books):
    needed = []
    for _start, ticker, _name in leaders:
        if ticker not in books:
            return None, ticker
        needed.append(ticker)
    calendar = sorted({day for ticker in needed for day, _price in books[ticker]["rows"]})
    calendar = [day for day in calendar if day.isoformat() >= leaders[0][0] and day.isoformat() <= CUTOFF]
    price = {
        ticker: {day: close for day, close in books[ticker]["rows"]}
        for ticker in needed
    }
    shares = 0.0
    cash = START_CASH
    held = None
    started = None
    ended = calendar[0]
    for day in calendar:
        _rule, want, _label = leader_on(leaders, day)
        if held and day in books[held]["dividends"] and held in price and day in price[held] and shares > 0:
            shares += shares * books[held]["dividends"][day] / price[held][day]
        if held != want:
            if held is not None:
                if held not in price or day not in price[held] or want not in price or day not in price[want]:
                    if held in price and day in price[held]:
                        ended = day
                    continue
                cash += shares * price[held][day]
                shares = 0.0
                held = None
            if want in price and day in price[want] and cash > 0:
                shares = cash / price[want][day]
                cash = 0.0
                held = want
                if started is None:
                    started = day
        if held in price and day in price[held]:
            ended = day
    if started is None or held not in price or ended not in price[held]:
        return None, held or needed[0]
    end_value = cash + shares * price[held][ended]
    years = max((ended - started).days, 1) / 365.25
    current_name = leader_on(leaders, ended)[2]
    return {
        "started": started.isoformat(),
        "ended": ended.isoformat(),
        "return_pct": (end_value / START_CASH - 1.0) * 100.0,
        "cagr": ((end_value / START_CASH) ** (1.0 / years) - 1.0) * 100.0,
        "current": current_name,
        "dividends": 1,
    }, None


def page(rows, failed, stamped):
    body = []
    for item in rows:
        div = "배당 없음" if item["dividends"] == 0 else "배당 재투자"
        body.append(
            "<tr>"
            f"<td>{html.escape(item['name'])}</td>"
            f"<td>{html.escape(item['code'])}</td>"
            f"<td>{html.escape(item['started'])}</td>"
            f"<td>{item['return_pct']:+.1f}%</td>"
            f"<td>{item['cagr']:.2f}%</td>"
            f"<td>{div}</td>"
            "</tr>"
        )
    missing = ""
    if failed:
        missing = "<p class=\"note\">가격을 받지 못한 종목: " + html.escape(", ".join(failed)) + ".</p>"
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <script src="/Premium/gate.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>인덱스 배당 재투자법</title>
  <style>
    body {{ background: #111; color: #fff; font-family: "Malgun Gothic", "Apple SD Gothic Neo", Arial, sans-serif; margin: 0; padding: 16px; }}
    a {{ color: #4da3ff; }}
    .home {{ color: #D8C0FF; font-size: 28px; text-decoration: none; }}
    h1 {{ text-align: center; color: #FFFFE0; font-size: 32px; line-height: 1.35; }}
    .note {{ max-width: 980px; margin: 8px auto; color: #ccc; font-size: 18px; line-height: 1.55; }}
    table {{ max-width: 980px; width: 100%; margin: 12px auto; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #333; padding: 10px 8px; text-align: right; font-size: 18px; }}
    th {{ color: #D8C0FF; }}
    td:first-child, th:first-child, td:nth-child(2), th:nth-child(2), td:last-child, th:last-child {{ text-align: left; }}
    @media (max-width: 800px) {{
      h1 {{ font-size: 26px; }}
      th, td {{ font-size: 15px; padding: 8px 4px; }}
    }}
  </style>
</head>
<body>
  <p><a class="home" href="/Premium/weather/index.html">← 주가 방향 날씨</a></p>
  <h1>인덱스 배당 재투자법</h1>
  <p class="note">계속 보유하고 배당은 다시 그 종목에 재투자한다. 과거 가격으로 계산한 결과이며, 앞날의 수익을 뜻하지 않고 매수를 권하지 않는다. 기준 시각 {html.escape(stamped)}. 주식과 상장지수펀드는 2026-11-20 종가까지이고, 비트코인과 이더리움은 2026-11-22 종가까지다.</p>
  <p class="note">미국 시총 1위는 아메리칸 비즈니스 히스토리 센터의 연도별 1분기 순위를 그해 첫 거래일에 교체한 것이다. 일별 순위가 아니다. 한국은 2000-11-21부터 삼성전자, 2026-06-22 종가부터는 보통주 기준 SK하이닉스다. 그 앞의 짧은 교체는 날짜가 확정되지 않아 빼었다. 일본은 NTT도코모 과거 시세를 받지 못해 2003-01-01 토요타부터이고, 2026-06-02 보도부터 소프트뱅크그룹이다. 2000년부터 2002년까지는 이 줄에 없다. 2025년 이후 미국의 일별 역전과, 2026년 6월 이후 한일 재역전은 이 표에 없다.</p>
  <table>
    <thead><tr><th>이름</th><th>코드</th><th>시작</th><th>누적 수익률</th><th>연복리</th><th>배당</th></tr></thead>
    <tbody>
      {''.join(body)}
    </tbody>
  </table>
  {missing}
  <p class="note">가격은 액면분할이 반영된 종가다. 배당이 있는 날은 그 배당금으로 같은 날 종가를 더 샀다. 배당 이벤트가 없으면 배당 없음이고, 가격 수익률만 보인다. 수수료는 없다. 상장이 2000년 이후인 종목은 첫 거래일부터다.</p>
  <p class="note">평일 마감 후 <code>python Premium/weather/fujimoto/update_fujimoto.py</code>로 다시 계산한다.</p>
</body>
</html>
'''


def main():
    tickers = [item[0] for item in INSTRUMENTS]
    for _start, ticker, _name in US_LEADERS + KR_LEADERS + JP_LEADERS:
        if ticker not in tickers:
            tickers.append(ticker)
    books, failed = load_all(tickers)
    rows = []
    for ticker, code, name in INSTRUMENTS:
        if ticker not in books:
            if ticker not in failed:
                failed.append(ticker)
            continue
        stats = hold_return(books[ticker]["rows"], books[ticker]["dividends"])
        rows.append({
            "name": name,
            "code": code,
            "started": stats["started"],
            "ended": stats["ended"],
            "return_pct": stats["return_pct"],
            "cagr": stats["cagr"],
            "dividends": stats["dividends"],
        })
        print(code, stats["started"], f'{stats["return_pct"]:+.1f}%', "div" if stats["dividends"] else "nodiv")

    sleeves = [
        ("미국 시총 1위", "US#1", US_LEADERS),
        ("한국 시총 1위", "KR#1", KR_LEADERS),
        ("일본 시총 1위", "JP#1", JP_LEADERS),
    ]
    for name, code, leaders in sleeves:
        if leaders[0][1] not in books and name.startswith("일본"):
            leaders = [item for item in leaders if item[1] in books]
            if not leaders:
                failed.append("일본 시총 1위")
                continue
        stats, missing = sleeve_return(leaders, books)
        if stats is None:
            failed.append(missing or code)
            print("sleeve fail", name, missing)
            continue
        rows.append({
            "name": f"{name} (지금 {stats['current']})",
            "code": code,
            "started": stats["started"],
            "ended": stats["ended"],
            "return_pct": stats["return_pct"],
            "cagr": stats["cagr"],
            "dividends": stats["dividends"],
        })
        print(name, stats["current"], stats["started"], f'{stats["return_pct"]:+.1f}%')

    rows.sort(key=lambda item: item["return_pct"], reverse=True)
    stamped = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    PAGE.write_text(page(rows, failed, stamped), encoding="utf-8")
    print("failed", failed)
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
