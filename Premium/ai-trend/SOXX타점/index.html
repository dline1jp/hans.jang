import pandas as pd
import yfinance as yf
import requests

# ---------- 설정 ----------
SOXL_TICKER = "SOXL"
RSI_PERIOD = 14
WINDOW = 20
HORIZONS = [20, 60, 120]

# ---------- 시장 데이터 ----------
soxl = yf.download(SOXL_TICKER, period="max", auto_adjust=True, progress=False)
vix = yf.download("^VIX", period="max", auto_adjust=True, progress=False)

def close_series(df, ticker):
    if isinstance(df.columns, pd.MultiIndex):
        s = df["Close"][ticker]
    else:
        s = df["Close"]
    return s.rename(ticker)

soxl_close = close_series(soxl, SOXL_TICKER)
vix_close = close_series(vix, "^VIX")

# ---------- RSI 계산 ----------
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

rsi = calculate_rsi(soxl_close, RSI_PERIOD)

# ---------- CNN 공포·탐욕지수 ----------
# 공개 CSV 미러를 사용합니다.
# 미러가 작동하지 않는 경우 CNN 공식 페이지에서 수집 로직을 교체하세요.
cnn_url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
try:
    response = requests.get(cnn_url, timeout=30)
    response.raise_for_status()
    raw = response.json()

    records = []
    for key in raw:
        if key != "fear_and_greed":
            continue
        for row in raw[key]:
            records.append(row)

    cnn = pd.DataFrame(records)
    if "x" in cnn.columns and "y" in cnn.columns:
        cnn.index = pd.to_datetime(cnn["x"], unit="ms", utc=True).tz_convert(None)
        cnn = cnn["y"].astype(float).rename("FearGreed")
    else:
        raise ValueError("CNN 응답 형식이 예상과 다릅니다.")
except Exception as exc:
    print(f"CNN 지수 수집 실패: {exc}")
    cnn = pd.Series(dtype=float, name="FearGreed")

# ---------- 데이터 병합 ----------
df = pd.concat(
    [soxl_close.rename("SOXL_Close"),
     rsi.rename("RSI"),
     vix_close.rename("VIX"),
     cnn],
    axis=1
).sort_index()
df = df.groupby(level=0).first()

# ---------- 바닥 판정 ----------
df["Bottom"] = (
    df["SOXL_Close"] ==
    df["SOXL_Close"].rolling(
        window=2 * WINDOW + 1,
        center=True,
        min_periods=2 * WINDOW + 1
    ).min()
)

bottom_dates = df.index[df["Bottom"]]

# ---------- 향후 수익률 ----------
for horizon in HORIZONS:
    df[f"Return_{horizon}D"] = (
        df["SOXL_Close"].shift(-horizon) / df["SOXL_Close"] - 1
    )

results = df.loc[bottom_dates].copy()
results = results[[
    "SOXL_Close",
    "RSI",
    "VIX",
    "FearGreed",
    "Return_20D",
    "Return_60D",
    "Return_120D"
]]

print("\nSOXL 바닥일별 지표")
print(results.to_string())

print("\n평균 향후 수익률")
print(results[
    ["Return_20D", "Return_60D", "Return_120D"]
].mean().mul(100).round(2).astype(str) + "%")

print("\nCNN 구간별 평균 수익률")
cnn_bins = pd.cut(
    results["FearGreed"],
    bins=[0, 25, 45, 55, 75, 100],
    labels=[
        "Extreme Fear",
        "Fear",
        "Neutral",
        "Greed",
        "Extreme Greed"
    ]
)
print(
    results.groupby(cnn_bins, observed=True)[
        ["Return_20D", "Return_60D", "Return_120D"]
    ].mean().mul(100).round(2)
)

print("\nVIX 구간별 평균 수익률")
vix_bins = pd.cut(
    results["VIX"],
    bins=[0, 15, 20, 30, 50, 100],
    labels=["<15", "15-20", "20-30", "30-50", ">=50"]
)
print(
    results.groupby(vix_bins, observed=True)[
        ["Return_20D", "Return_60D", "Return_120D"]
    ].mean().mul(100).round(2)
)
