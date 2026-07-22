import time
import yfinance as yf
import pandas as pd


TICKERS = {
    "QLD": "나스닥 2x",
    "SSO": "S&P500 2x",
    "USD": "반도체 2x",
}

_COLS = ["Open", "High", "Low", "Close", "Volume"]


def fetch_all(days: int = 200, max_retries: int = 3) -> dict[str, pd.DataFrame]:
    """Download all tickers in a single batch request to avoid rate limits."""
    symbols = list(TICKERS.keys())

    for attempt in range(max_retries):
        try:
            raw = yf.download(
                symbols,
                period=f"{days}d",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
            )
            if raw.empty:
                raise ValueError("No data returned for any ticker")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 5 * (attempt + 1)
                print(f"다운로드 실패 (시도 {attempt + 1}/{max_retries}), {wait}초 후 재시도: {e}")
                time.sleep(wait)
            else:
                raise

    result = {}
    for ticker in symbols:
        # Batch download returns MultiIndex (col, ticker) when >1 symbol
        if isinstance(raw.columns, pd.MultiIndex):
            df = raw[ticker][_COLS].dropna(how="all")
        else:
            df = raw[_COLS].dropna(how="all")

        if df.empty:
            raise ValueError(f"No data returned for {ticker}")
        result[ticker] = df

    return result
