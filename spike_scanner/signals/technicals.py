"""
Technical momentum signals — pure price-based indicators.

Three patterns that confirm a stock is in motion:
1. RSI in the 50-70 sweet spot: building momentum, not yet overbought
2. MACD bullish crossover: trend shift from bearish to bullish
3. Price above 50-day MA: trend confirmation
4. Near 52-week high: potential breakout zone (within 5%)

All computed from OHLCV — no API key or external data needed.
"""
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _extract_series(df: pd.DataFrame, col: str) -> pd.Series:
    series = df[col]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    return series.dropna()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def compute_technicals_score(ticker: str, df: pd.DataFrame) -> tuple[float, dict]:
    """
    Composite technical momentum score (0-100).

    RSI sweet spot + MACD cross + MA alignment + 52w high proximity.
    Each component scores independently; all four firing = max signal.
    """
    if df is None or len(df) < 60:
        return 0.0, {}

    try:
        close = _extract_series(df, "Close")
        if len(close) < 30:
            return 0.0, {}

        # ── RSI(14) ───────────────────────────────────────────────────────────
        rsi_series  = _rsi(close)
        current_rsi = float(rsi_series.iloc[-1])

        rsi_score = 0.0
        if 55 <= current_rsi <= 70:
            rsi_score = 35   # Sweet spot: building momentum
        elif 50 <= current_rsi < 55:
            rsi_score = 20   # Early momentum
        elif 70 < current_rsi <= 80:
            rsi_score = 10   # Extended but still trending

        # ── MACD (12-26-9) ────────────────────────────────────────────────────
        ema12  = close.ewm(span=12, adjust=False).mean()
        ema26  = close.ewm(span=26, adjust=False).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist   = macd - signal

        macd_score = 0.0
        macd_bullish_cross = False
        if len(hist) >= 3:
            if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
                macd_score = 40        # Fresh bullish crossover — strongest signal
                macd_bullish_cross = True
            elif hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
                macd_score = 20        # Continuing bullish momentum

        # ── Price vs 50-day MA ────────────────────────────────────────────────
        ma50 = close.rolling(50, min_periods=30).mean()
        above_ma50 = bool(close.iloc[-1] > ma50.iloc[-1]) if not ma50.isna().iloc[-1] else False
        ma50_score = 15.0 if above_ma50 else 0.0

        # ── 52-week high proximity ────────────────────────────────────────────
        high_52w = close.rolling(252, min_periods=60).max().iloc[-1]
        current  = float(close.iloc[-1])
        pct_from_high = (current / high_52w - 1.0) * 100 if high_52w > 0 else -100.0
        near_high_score = 10.0 if pct_from_high >= -5.0 else 0.0

        total = rsi_score + macd_score + ma50_score + near_high_score

        return round(min(total, 100.0), 1), {
            "rsi":              round(current_rsi, 1),
            "macd_bullish":     hist.iloc[-1] > 0 if len(hist) >= 1 else False,
            "macd_fresh_cross": macd_bullish_cross,
            "above_ma50":       above_ma50,
            "pct_from_52w_high": round(pct_from_high, 1),
        }

    except Exception as e:
        logger.debug(f"Technicals failed for {ticker}: {e}")
        return 0.0, {}
