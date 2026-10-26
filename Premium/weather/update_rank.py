# -*- coding: utf-8 -*-
import html
import json
import pathlib
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import requests
SP_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
KOSPI_URL = "https://m.stock.naver.com/api/stocks/marketValue/KOSPI"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
TV_SEARCH = "https://symbol-search.tradingview.com/symbol_search/v3/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TV_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "NYSE ARCA"}
TV_STUDIES = urllib.parse.quote(json.dumps([
    {"id": "MASimple@tv-basicstudies", "inputs": {"length": 200}},
    {"id": "RSI@tv-basicstudies", "inputs": {"length": 14}},
], separators=(",", ":")))
TV_OVERRIDES = urllib.parse.quote(json.dumps({
    "moving average.ma.color": "#E53935",
    "moving average.ma.linewidth": 2,
    "moving average.length": 200,
}, separators=(",", ":")))
WEEKS = 200
PAGE = pathlib.Path(__file__).with_name("index.html")
SKIP_NAME = ("WARRANT", " RIGHT", " UNIT", "PREFERRED", "DEBENTURE", " NOTE", "WHEN ISSUED")
HIGH_HEADING = (
    '<h1>1. S&P500 주봉기준 과매수 종목 후보입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일 이동평균선 위로 이격이 큰 종목 랭킹입니다. "
    "종목 링크를 클릭후 주봉 2중 혹은 3중 천장과 RSI 하락 다이버전스가 나오면 하락 가능성이 큽니다.매도 추천이 아닙니다. 참조만 하세요.</h1>"
)
LOW_HEADING = (
    '<h1 class="low">2. S&P500 주봉기준 과매도 종목 후보입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일 이동평균선 아래로 이격이 큰 종목 랭킹입니다. "
    "종목 링크를 클릭후 주봉 2중 혹은 3중 바닥과 RSI 상승 다이버전스가 나오면 반등 가능성이 있습니다.단 파산 가능성이 크서 전혀 매수 추천하지 않습니다. 경기사이클 EPS BPS 매출 현금흐름등 지표도 확인해야 하니 참조만 하세요.</h1>"
)
NASDAQ_HIGH_HEADING = (
    '<h1 class="low">3. 나스닥 composite 주봉기준 과매수 종목 후보입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일 이동평균선 위로 이격이 큰 종목 랭킹입니다. "
    "종목 링크를 클릭후 주봉 2중 혹은 3중 천장 RSI 하락 다이버전스가 나오면 하락 가능성이 큽니다.매도 추천이 아닙니다. 참조만 하세요.</h1>"
)
NASDAQ_LOW_HEADING = (
    '<h1 class="low">4. 나스닥 composite주봉기준 과매도 종목 후보입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일 이동평균선 아래로 이격이 큰 종목 랭킹입니다. "
    "종목 링크를 클릭후 주봉 2중 혹은 3중 바닥과 RSI 상승 다이버전스가 나오면 반등 가능성이 있습니다.단 파산 가능성이 크서 전혀 매수 추천하지 않습니다. 경기사이클 EPS BPS 매출 현금흐름등 지표도 확인해야 하니 참조만 하세요.</h1>"
)
KOSPI_HIGH_HEADING = (
    '<h1 class="low">5. 코스피 주봉기준 과매수 종목 후보입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일 이동평균선 위로 이격이 큰 종목 랭킹입니다. "
    "종목 링크를 클릭후 주봉 2중 혹은 3중 천장 RSI 하락 다이버전스가 나오면 하락 가능성이 큽니다.매도 추천이 아닙니다. 참조만 하세요. 코스피는 차트중 200이평과 RSI가 안뜨니 트레이딩뷰 무료버젼에 로그인해서 200이평과 RSI을 미리 띄워 놓으셔야 보입니다.</h1>"
)
KOSPI_LOW_HEADING = (
    '<h1 class="low">6. 코스피 주봉기준 과매도 종목 후보입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일 이동평균선 아래로 이격이 큰 종목 랭킹입니다. "
    "종목 링크를 클릭후 주봉 2중 혹은 3중 바닥과 RSI 상승 다이버전스가 나오면 반등 가능성이 있습니다.단 파산 가능성이 크서 전혀 매수 추천하지 않습니다. 경기사이클 EPS BPS 매출 현금흐름등 지표도 확인해야 하니 참조만 하세요. 코스피는 차트중 200이평과 RSI가 안뜨니 트레이딩뷰 무료버젼에 로그인해서 200이평과 RSI을 미리 띄워 놓으셔야 보입니다.</h1>"
)

#ETF start
ETF_HEADING = (
    '<h1 class="low">7. 주요 ETF 주봉기준 200일 이동평균선 이격도입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일선 아래일때가 이격도 100이하입니다. 이 시기는 장기보유를 위해 분할 매수를 고려할수 있습니다.</h1>"
)
ETF_ROWS = [
    ("QQQ", "QQQ", "Invesco QQQ"),
    ("SPY", "SPY", "SPDR S&P 500"),
    ("VOO", "VOO", "Vanguard S&P 500"),
    ("^SOX", "SOX", "필라델피아 반도체"),
    ("SMH", "SMH", "VanEck 반도체"),
    ("SLV", "SLV", "iShares 은"),
    ("GLD", "GLD", "SPDR 금"),
    ("SCHD", "SCHD", "Schwab 미국배당"),
    ("069500.KS", "069500", "KODEX 200"),
    ("102110.KS", "102110", "TIGER 200"),
    ("EWY", "EWY", "iShares 한국"),
    ("FLKR", "FLKR", "Franklin 한국"),
    ("BTC-USD", "BTC-USD", "비트코인"),
    ("ETH-USD", "ETH-USD", "이더리움"),
]
def etf_chart_url(ticker):
    if ticker == "^SOX":
        return "https://www.tradingview.com/chart/?symbol=NASDAQ:SOX&interval=W"
    fixed = {"BTC-USD": "BITSTAMP:BTCUSD", "ETH-USD": "BITSTAMP:ETHUSD"}
    if ticker not in fixed:
        return chart_url(ticker)
    return (
        "https://www.tradingview.com/widgetembed/?symbol="
        + urllib.parse.quote(fixed[ticker], safe="")
        + "&interval=W&style=1&theme=dark&hideideas=1"
        + "&studies=" + TV_STUDIES
        + "&studies_overrides=" + TV_OVERRIDES
    )
def render_etf(scored):
    rows = []
    for ticker, label, name in ETF_ROWS:
        row = scored.get(ticker)
        if not row:
            continue
        item = dict(row)
        item["label"] = label
        item["name"] = name
        rows.append(item)
    asof = rows[0]["asof"] if rows else ""
    lines = [
        ETF_HEADING,
        '<section class="rank-wrap">',
        f'<p class="note">기준 주봉 {asof} · 이격도 100 이하는 주봉 200일선 아래입니다.</p>',
        '<p class="formula">이격도 = 주봉 종가 ÷ 200주 이동평균 × 100</p>',
        '<table class="rank">',
        '<thead><tr><th>순위</th><th>코드</th><th>종목</th><th>주봉 종가</th><th>200주 이평</th><th>이격도</th></tr></thead>',
        '<tbody>',
    ]
    for order, row in enumerate(rows, start=1):
        gap_class = "gap-low" if row["disparity"] <= 100 else "gap"
        top = ' class="top"' if row["disparity"] <= 100 else ""
        lines.append(
            f'<tr{top}><td>{order}</td><td class="code"><a href="{etf_chart_url(row["ticker"])}" target="_blank">{html.escape(row["label"])}</a></td>'
            f'<td class="name">{html.escape(row["name"])}</td><td>{row["price"]:.2f}</td><td>{row["ma200"]:.2f}</td>'
            f'<td class="{gap_class}">{row["disparity"]:.1f}</td></tr>'
        )
    lines.append("</tbody></table></section>")
    return "\n".join(lines)
#ETF end    
#etc. start
ETC_HEADING = (
    '<h1 class="low">8. 주요 기타종목 주봉기준 200일 이동평균선 이격도입니다. 매주 토요일 업데이트됩니다. '
    "주봉 200일선 아래일때가 이격도 100이하입니다. 이 시기는 몇년정도 장기보유를 위해 분할 매수를 고려할수 있습니다.</h1>"
)
ETC_ROWS = [
    ("UUP", "UUP", "Invesco 달러"),
    ("SGOV", "SGOV", "iShares 초단기국채"),
    ("SOXX", "SOXX", "iShares 반도체"),
    ("NVDA", "NVDA", "NVIDIA"),
    ("PLTR", "PLTR", "Palantir"),
    ("VRT", "VRT", "Vertiv"),
    ("CLS", "CLS", "Celestica"),
    ("GOOG", "GOOG", "Alphabet"),
    ("AMZN", "AMZN", "Amazon"),
    ("MSFT", "MSFT", "Microsoft"),
    ("QTUM", "QTUM", "Defiance Quantum"),
    ("036930.KQ", "036930", "주성엔지니어링"),
    ("277810.KQ", "277810", "레인보우로보틱스"),
    ("307950.KS", "307950", "현대오토에버"),
    ("005930.KS", "005930", "삼성전자"),
    ("000660.KS", "000660", "SK하이닉스"),
    ("454910.KS", "454910", "두산로보틱스"),
    ("108490.KQ", "108490", "로보티즈"),
    ("012450.KS", "012450", "한화에어로스페이스"),
    ("064350.KS", "064350", "현대로템"),
    ("079550.KS", "079550", "LIG넥스원"),
    ("047810.KS", "047810", "한국항공우주"),
    ("034020.KS", "034020", "두산에너빌리티"),
    ("298040.KS", "298040", "효성중공업"),
    ("267260.KS", "267260", "HD현대일렉트릭"),
]
def render_etc(scored):
    lines = [
        ETC_HEADING,
        '<section class="rank-wrap">',
        '<p class="note">기준 주봉 {asof} · 이격도 100 이하는 주봉 200일선 아래입니다. 200주가 없는 종목은 이격도를 비워 둡니다.</p>',
        '<p class="formula">이격도 = 주봉 종가 ÷ 200주 이동평균 × 100</p>',
        '<table class="rank">',
        '<thead><tr><th>순위</th><th>코드</th><th>종목</th><th>주봉 종가</th><th>200주 이평</th><th>이격도</th></tr></thead>',
        '<tbody>',
    ]
    body = []
    asof = ""
    for ticker, label, name in ETC_ROWS:
        row = scored.get(ticker)
        if row and not asof:
            asof = row["asof"]
        price = f'{row["price"]:.2f}' if row else "-"
        ma = f'{row["ma200"]:.2f}' if row else "-"
        if row and row["disparity"] <= 100:
            gap = f'<td class="gap-low">{row["disparity"]:.1f}</td>'
            top = ' class="top"'
        elif row:
            gap = f'<td class="gap">{row["disparity"]:.1f}</td>'
            top = ""
        else:
            gap = "<td>-</td>"
            top = ""
            series = weekly_close(ticker)
            if series is not None and len(series):
                price = f"{float(series.iloc[-1]):.2f}"
        body.append(
            f'<tr{top}><td>{len(body)+1}</td><td class="code"><a href="{chart_url(ticker)}" target="_blank">{html.escape(label)}</a></td>'
            f'<td class="name">{html.escape(name)}</td><td>{price}</td><td>{ma}</td>{gap}</tr>'
        )
    lines[2] = lines[2].format(asof=asof)
    lines.extend(body)
    lines.append("</tbody></table></section>")
    return "\n".join(lines)

#etc end

def tradingview_symbol(ticker):
    query = ticker.replace("-", ".")
    try:
        response = requests.get(
            TV_SEARCH,
            params={"text": query, "lang": "en", "search_type": "stocks", "domain": "production"},
            headers={**HEADERS, "Origin": "https://www.tradingview.com"},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException:
        return query
    cleaned = []
    for item in response.json().get("symbols") or []:
        symbol = re.sub(r"</?em>", "", item.get("symbol") or "")
        exchange = (item.get("exchange") or "").upper()
        cleaned.append((exchange, symbol))
    for exchange, symbol in cleaned:
        if symbol == query and exchange in TV_EXCHANGES:
            return f"{exchange}:{symbol}"
    for exchange, symbol in cleaned:
        if symbol == query and exchange:
            return f"{exchange}:{symbol}"
    return query
def chart_url(ticker):
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        symbol = "KRX:" + ticker.split(".")[0]
        return (
            "https://www.tradingview.com/chart/?symbol="
            + urllib.parse.quote(symbol, safe=":")
            + "&interval=W"
        )
    symbol = tradingview_symbol(ticker)
    return (
        "https://www.tradingview.com/widgetembed/?symbol="
        + urllib.parse.quote(symbol, safe="")
        + "&interval=W&style=1&theme=dark&hideideas=1"
        + "&studies="
        + TV_STUDIES
        + "&studies_overrides="
        + TV_OVERRIDES
    )
def weekly_close(ticker):
    for attempt in range(3):
        try:
            response = requests.get(
                CHART_URL.format(ticker=ticker),
                params={"interval": "1wk", "range": "10y", "events": "div,splits", "includeAdjustedClose": "true"},
                headers=HEADERS,
                timeout=30,
            )
            if response.status_code in (429, 500, 502, 503):
                time.sleep(1.2 * (attempt + 1))
                continue
            response.raise_for_status()
            result = response.json()["chart"]["result"]
            if not result:
                return None
            indicators = result[0]["indicators"]
            stamps = result[0].get("timestamp") or []
            adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose")
            raw = (indicators.get("quote") or [{}])[0].get("close")
            closes = adjusted or raw
            if not closes or not stamps:
                return None
            series = pd.Series(closes, index=pd.to_datetime(stamps, unit="s")).dropna()
            return series[~series.index.duplicated(keep="last")].sort_index()
        except (requests.RequestException, ValueError, KeyError, TypeError):
            time.sleep(0.6 * (attempt + 1))
    return None
def score(ticker):
    series = weekly_close(ticker)
    if series is None or len(series) < WEEKS:
        return None
    last4 = series.tail(4)
    if len(last4) == 4 and float(last4.max()) == float(last4.min()):
        return None
    price = float(series.iloc[-1])
    ma200 = float(series.tail(WEEKS).mean())
    if ma200 <= 0 or price == ma200:
        return None
    disparity = price / ma200 * 100
    if disparity < 5 or disparity > 3000:
        band = series[(series >= price / 40) & (series <= price * 40)]
        if len(band) < WEEKS:
            return None
        ma200 = float(band.tail(WEEKS).mean())
        if ma200 <= 0 or price == ma200:
            return None
        disparity = price / ma200 * 100
    return {
        "ticker": ticker,
        "price": round(price, 2),
        "ma200": round(ma200, 2),
        "disparity": round(disparity, 1),
        "asof": series.index[-1].date().isoformat(),
        "side": "below" if price < ma200 else "above",
    }
def load_sp():
    constituents = pd.read_csv(SP_URL)
    constituents["yahoo"] = constituents["Symbol"].str.replace(".", "-", regex=False)
    return list(zip(constituents["yahoo"], constituents["Security"]))
def load_nasdaq():
    text = requests.get(NASDAQ_URL, headers=HEADERS, timeout=30).text
    rows = []
    seen = set()
    for line in text.splitlines()[1:]:
        if line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        symbol, name, _market, test, _fin, _lot, etf = parts[:7]
        if test == "Y" or etf == "Y" or symbol in seen:
            continue
        if not re.fullmatch(r"[A-Z]{1,5}", symbol):
            continue
        upper = name.upper()
        if " ETF" in f" {upper}" or any(key in upper for key in SKIP_NAME):
            continue
        seen.add(symbol)
        rows.append((symbol, name.split(" - ", 1)[0].strip()))
    return rows
def load_kospi():
    rows = []
    seen = set()
    page = 1
    while True:
        response = requests.get(
            KOSPI_URL,
            params={"page": page, "pageSize": 100},
            headers={**HEADERS, "Referer": "https://m.stock.naver.com/"},
            timeout=30,
        )
        response.raise_for_status()
        stocks = response.json().get("stocks") or []
        if not stocks:
            break
        for item in stocks:
            if item.get("stockEndType") != "stock":
                continue
            code = item.get("itemCode") or ""
            if not code.isdigit() or len(code) != 6 or not code.endswith("0") or code in seen:
                continue
            seen.add(code)
            rows.append((f"{code}.KS", item.get("stockName") or code))
        page += 1
    return rows
def ranked(pairs, scored):
    rows = []
    for ticker, name in pairs:
        row = scored.get(ticker)
        if not row:
            continue
        item = dict(row)
        item["name"] = name
        item["label"] = ticker.split(".")[0] if ticker.endswith(".KS") else ticker
        rows.append(item)
    frame = pd.DataFrame(rows)
    above = frame[frame["side"] == "above"].sort_values(["disparity", "ticker"], ascending=[False, True])
    below = frame[frame["side"] == "below"].sort_values(["disparity", "ticker"], ascending=[True, True])
    return above, below
def render_table(rank, note, gap_class):
    lines = [
        '<section class="rank-wrap">',
        f'<p class="note">{note}</p>',
        '<p class="formula">이격도 = 주봉 종가 ÷ 200주 이동평균 × 100</p>',
        '<table class="rank">',
        '<thead><tr><th>순위</th><th>코드</th><th>종목</th><th>주봉 종가</th><th>200주 이평</th><th>이격도</th></tr></thead>',
        '<tbody>',
    ]
    for order, row in enumerate(rank.head(10).itertuples(index=False), start=1):
        top = ' class="top"' if order <= 3 else ""
        lines.append(
            f'<tr{top}><td>{order}</td><td class="code"><a href="{chart_url(row.ticker)}" target="_blank">{html.escape(row.label)}</a></td>'
            f'<td class="name">{html.escape(str(row.name))}</td><td>{row.price:.2f}</td><td>{row.ma200:.2f}</td>'
            f'<td class="{gap_class}">{row.disparity:.1f}</td></tr>'
        )
    lines.append("</tbody></table></section>")
    return "\n".join(lines)
def block(above, below, high, low, market):
    asof = above.iloc[0]["asof"]
    prefix = f"{market} " if market else ""
    above_note = f"기준 주봉 {asof} · {prefix}200주 이평 위 {len(above)}종목 중 이격 상위 10"
    below_note = (
        f"기준 주봉 {asof} · {prefix}200주 이평 아래 {len(below)}종목 중 아래로 이격이 큰 10. "
        "이격도가 작을수록 이평선 아래로 더 멀리 있습니다."
    )
    return "\n".join([
        high,
        render_table(above, above_note, "gap"),
        low,
        render_table(below, below_note, "gap-low"),
    ])
def render(sp_above, sp_below, nq_above, nq_below, ks_above, ks_below, scored):
    return "\n".join([
        block(sp_above, sp_below, HIGH_HEADING, LOW_HEADING, ""),
        block(nq_above, nq_below, NASDAQ_HIGH_HEADING, NASDAQ_LOW_HEADING, "나스닥"),
        block(ks_above, ks_below, KOSPI_HIGH_HEADING, KOSPI_LOW_HEADING, "코스피"),
        render_etf(scored),
        render_etc(scored),
    ])
def main():
    groups = (load_sp(), load_nasdaq(), load_kospi())
    seen = set()
    tickers = []
    for pairs in groups:
        for ticker, _name in pairs:
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)
    for ticker, _label, _name in ETF_ROWS:
      if ticker not in seen:
         seen.add(ticker)
         tickers.append(ticker)
      for ticker, _label, _name in ETC_ROWS:
        if ticker not in seen:
        seen.add(ticker)
        tickers.append(ticker)
    
    scored = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(score, ticker) for ticker in tickers]
        for future in as_completed(futures):
            row = future.result()
            if row:
                scored[row["ticker"]] = row
    sp_above, sp_below = ranked(groups[0], scored)
    nq_above, nq_below = ranked(groups[1], scored)
    ks_above, ks_below = ranked(groups[2], scored)
    html_text = PAGE.read_text(encoding="utf-8")
    pattern = re.compile(r"<!-- RANK_START -->.*?<!-- RANK_END -->", re.S)
    if not pattern.search(html_text):
        raise SystemExit("RANK_START / RANK_END 표시가 없습니다.")
    PAGE.write_text(
        pattern.sub(
           "<!-- RANK_START -->\n" + render(sp_above, sp_below, nq_above, nq_below, ks_above, ks_below, scored) + "\n<!-- RANK_END -->",
            html_text,
        ),
        encoding="utf-8",
    )
    for title, frame in (
        ("SP ABOVE", sp_above), ("SP BELOW", sp_below),
        ("NQ ABOVE", nq_above), ("NQ BELOW", nq_below),
        ("KS ABOVE", ks_above), ("KS BELOW", ks_below),
    ):
        print(title)
        print(frame.head(10).to_string(index=False))
if __name__ == "__main__":
    main()
