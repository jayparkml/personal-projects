import yfinance as yf
import pandas as pd


TICKERS = {
    "QLD": "나스닥 2x",
    "SSO": "S&P500 2x",
    "USD": "반도체 2x",
}


def fetch_ohlcv(ticker: str, days: int = 200) -> pd.DataFrame:
    """Download OHLCV data for a ticker. Returns DataFrame with DatetimeIndex."""
    data = yf.download(ticker, period=f"{days}d", auto_adjust=True, progress=False)
    if data.empty:
        raise ValueError(f"No data returned for {ticker}")
    # yfinance may return MultiIndex columns when downloading single ticker
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)
    return data[["Open", "High", "Low", "Close", "Volume"]]


def fetch_all(days: int = 200) -> dict[str, pd.DataFrame]:
    return {ticker: fetch_ohlcv(ticker, days) for ticker in TICKERS}
