# -*- coding: utf-8 -*-
import json
import pathlib
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import requests
LIST_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
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
    "moving average.length": 200,HEADING
}, separators=(",", ":")))
WEEKS = 200
PAGE = pathlib.Path(__file__).with_name("index.html")
LOW_HEADING = (
    '<h1 class="low">2. S&P500중 과매도 종목 후보입니다. 매주 업데이트됩니다. '
    "주봉 200일 이동평균선 아래로 이격이 큰 종목 랭킹입니다. "
    "종목 링크를 클릭하여 주봉 2중 혹은 3중 바닥과 RSI 상승 다이버전스가 나오면 반등 가능성이 큽니다.</h1>"
)
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
    symbol = urllib.parse.quote(tradingview_symbol(ticker), safe="")
    return (
        "https://www.tradingview.com/widgetembed/?symbol="
        + symbol
        + "&interval=W&style=1&theme=dark&hideideas=1"
        + "&studies="
        + TV_STUDIES
        + "&studies_overrides="
        + TV_OVERRIDES
    )
def weekly_close(ticker):
    response = requests.get(
        CHART_URL.format(ticker=ticker),
        params={"interval": "1wk", "range": "10y", "events": "div,splits", "includeAdjustedClose": "true"},
        headers=HEADERS,
        timeout=30,
    )
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
def score(ticker, name):
    series = weekly_close(ticker)
    if series is None or len(series) < WEEKS:
        return None
    price = float(series.iloc[-1])
    ma200 = float(series.tail(WEEKS).mean())
    if ma200 <= 0 or price == ma200:
        return None
    return {
        "ticker": ticker,
        "name": name,
        "price": round(price, 2),
        "ma200": round(ma200, 2),
        "disparity": round(price / ma200 * 100, 1),
        "asof": series.index[-1].date().isoformat(),
        "side": "below" if price < ma200 else "above",
    }
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
            f'<tr{top}><td>{order}</td><td class="code"><a href="{chart_url(row.ticker)}" target="_blank">{row.ticker}</a></td><td class="name">{row.name}</td>'
            f'<td>{row.price:.2f}</td><td>{row.ma200:.2f}</td><td class="{gap_class}">{row.disparity:.1f}</td></tr>'
        )
    lines.append("</tbody></table></section>")
    return "\n".join(lines)
def render(above, below):
    asof = above.iloc[0]["asof"]
    above_html = render_table(
        above,
        f"기준 주봉 {asof} · 200주 이평 위 {len(above)}종목 중 이격 상위 10",
        "gap",
    )
    below_html = render_table(
        below,
        f"기준 주봉 {asof} · 200주 이평 아래 {len(below)}종목 중 아래로 이격이 큰 10. 이격도가 작을수록 이평선 아래로 더 멀리 있습니다.",
        "gap-low",
    )
    return above_html + "\n" + LOW_HEADING + "\n" + below_html
def main():
    constituents = pd.read_csv(LIST_URL)
    constituents["yahoo"] = constituents["Symbol"].str.replace(".", "-", regex=False)
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(score, ticker, name)
            for ticker, name in zip(constituents["yahoo"], constituents["Security"])
        ]
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
    frame = pd.DataFrame(rows)
    above = frame[frame["side"] == "above"].sort_values(["disparity", "ticker"], ascending=[False, True])
    below = frame[frame["side"] == "below"].sort_values(["disparity", "ticker"], ascending=[True, True])
    html = PAGE.read_text(encoding="utf-8")
    pattern = re.compile(r"<!-- RANK_START -->.*?<!-- RANK_END -->", re.S)
    if not pattern.search(html):
        raise SystemExit("RANK_START / RANK_END 표시가 없습니다.")
    PAGE.write_text(
        pattern.sub("<!-- RANK_START -->\n" + render(above, below) + "\n<!-- RANK_END -->", html),
        encoding="utf-8",
    )
    print(above.head(10).to_string(index=False))
    print(below.head(10).to_string(index=False))
if __name__ == "__main__":
    main()
