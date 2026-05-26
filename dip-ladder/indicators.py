import pandas as pd


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))


def compute(df: pd.DataFrame) -> dict:
    """Return latest indicator values for a single ticker's OHLCV DataFrame."""
    close = df["Close"]
    latest = close.iloc[-1]
    ma20 = moving_average(close, 20).iloc[-1]
    ma60 = moving_average(close, 60).iloc[-1]
    ma120 = moving_average(close, 120).iloc[-1]
    rsi_val = rsi(close).iloc[-1]
    return {
        "price": round(float(latest), 2),
        "ma20": round(float(ma20), 2),
        "ma60": round(float(ma60), 2),
        "ma120": round(float(ma120), 2),
        "rsi": round(float(rsi_val), 1),
    }
