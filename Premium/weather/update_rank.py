# -*- coding: utf-8 -*-
import pathlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import requests
LIST_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HEADERS = {"User-Agent": "Mozilla/5.0"}
WEEKS = 200
PAGE = pathlib.Path(__file__).with_name("index.html")
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
    if ma200 <= 0 or price <= ma200:
        return None
    return {
        "ticker": ticker,
        "name": name,
        "price": round(price, 2),
        "ma200": round(ma200, 2),
        "disparity": round(price / ma200 * 100, 1),
        "asof": series.index[-1].date().isoformat(),
    }
def render(rank):
    asof = rank.iloc[0]["asof"]
    above = len(rank)
    lines = [
        '<section class="rank-wrap">',
        f'<p class="note">기준 주봉 {asof} · 200주 이평 위 {above}종목 중 이격 상위 10</p>',
        '<p class="formula">이격도 = 주봉 종가 ÷ 200주 이동평균 × 100</p>',
        '<table class="rank">',
        '<thead><tr><th>순위</th><th>코드</th><th>종목</th><th>주봉 종가</th><th>200주 이평</th><th>이격도</th></tr></thead>',
        '<tbody>',
    ]
    for order, row in enumerate(rank.head(10).itertuples(index=False), start=1):
        top = ' class="top"' if order <= 3 else ''
        lines.append(
            f'<tr{top}><td>{order}</td><td class="code">{row.ticker}</td><td class="name">{row.name}</td>'
            f'<td>{row.price:.2f}</td><td>{row.ma200:.2f}</td><td class="gap">{row.disparity:.1f}</td></tr>'
        )
    lines.append('</tbody></table></section>')
    return '\n'.join(lines)
    
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
    rank = pd.DataFrame(rows).sort_values(["disparity", "ticker"], ascending=[False, True])
    html = PAGE.read_text(encoding="utf-8")
    pattern = re.compile(r"<!-- RANK_START -->.*?<!-- RANK_END -->", re.S)
    if not pattern.search(html):
        raise SystemExit("RANK_START / RANK_END 표시가 없습니다.")
    PAGE.write_text(
        pattern.sub("<!-- RANK_START -->\n" + render(rank) + "\n<!-- RANK_END -->", html),
        encoding="utf-8",
    )
    print(rank.head(10).to_string(index=False))
if __name__ == "__main__":
    main()
