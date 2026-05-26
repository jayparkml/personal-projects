"""
Volume anomaly and price compression signals.

Two patterns that precede large moves:
1. Volume surge + flat price = institutional accumulation (someone working
   a large order over days without moving price yet)
2. Price compression (Bollinger Band squeeze) = spring coiling before
   expansion — volume dries up, range tightens, then a volume spike triggers

Both measured from daily OHLCV via yfinance. No API key required.
"""
import logging

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


def _extract_series(df: pd.DataFrame, col: str) -> pd.Series:
    """Extract a named column as a 1-D Series, handling yfinance multi-level columns."""
    series = df[col]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    return series.dropna()


def compute_volume_signals(df: pd.DataFrame) -> dict:
    """
    Measures recent volume vs baseline.
    Returns dict with score (0-100) and detail fields.
    """
    if df is None or len(df) < config.VOL_LOOKBACK_LONG + 5:
        return {"score": 0, "surge_ratio": None, "divergence": False}

    vol = _extract_series(df, "Volume")
    if len(vol) < config.VOL_LOOKBACK_LONG:
        return {"score": 0, "surge_ratio": None, "divergence": False}

    recent_vol   = vol.iloc[-config.VOL_LOOKBACK_SHORT:].mean()
    baseline_vol = vol.iloc[-(config.VOL_LOOKBACK_LONG + config.VOL_LOOKBACK_SHORT):
                            -config.VOL_LOOKBACK_SHORT].mean()

    if baseline_vol == 0:
        return {"score": 0, "surge_ratio": None, "divergence": False}

    ratio = recent_vol / baseline_vol

    # Score: linear between 2x (score=50) and 4x+ (score=100)
    if ratio < config.VOL_SURGE_THRESHOLD:
        score = 0
    elif ratio >= config.VOL_SPIKE_THRESHOLD:
        score = 100
    else:
        score = int(50 + 50 * (ratio - config.VOL_SURGE_THRESHOLD) /
                    (config.VOL_SPIKE_THRESHOLD - config.VOL_SURGE_THRESHOLD))

    # Divergence: volume surging but price flat/down = accumulation
    close = _extract_series(df, "Close")
    if len(close) >= config.VOL_LOOKBACK_SHORT:
        recent_price_chg = (close.iloc[-1] - close.iloc[-config.VOL_LOOKBACK_SHORT]) / close.iloc[-config.VOL_LOOKBACK_SHORT]
        divergence = ratio >= config.VOL_SURGE_THRESHOLD and abs(recent_price_chg) < 0.02
        if divergence:
            score = min(100, int(score * 1.2))
    else:
        divergence = False

    return {"score": score, "surge_ratio": round(ratio, 2), "divergence": divergence}


def compute_compression_signals(df: pd.DataFrame) -> dict:
    """
    Bollinger Band squeeze: BB width in bottom 10th percentile = spring coiling.
    Returns dict with score (0-100) and detail fields.
    """
    if df is None or len(df) < 252:
        return {"score": 0, "bb_width_percentile": None, "is_compressed": False}

    close = _extract_series(df, "Close")
    rolling_mean = close.rolling(config.BB_PERIOD).mean()
    rolling_std  = close.rolling(config.BB_PERIOD).std()

    bb_width = (2 * rolling_std / rolling_mean).dropna()
    if len(bb_width) < 60:
        return {"score": 0, "bb_width_percentile": None, "is_compressed": False}

    current_width = bb_width.iloc[-1]
    historical_widths = bb_width.iloc[-252:]
    percentile = int((historical_widths < current_width).mean() * 100)

    is_compressed = percentile <= config.BB_COMPRESSION_PERCENTILE
    # Score: 100 at 0th percentile, 0 at 50th+
    score = max(0, int(100 * (50 - percentile) / 50)) if percentile < 50 else 0

    return {
        "score": score,
        "bb_width_percentile": percentile,
        "is_compressed": is_compressed,
    }


def compute_momentum_score(ticker: str, df: pd.DataFrame) -> tuple[float, dict]:
    """
    Composite momentum sub-score (0-100).
    Combines volume anomaly and price compression — both can independently signal.
    A stock with both (accumulation + compression) gets a multiplicative boost.
    """
    vol_signals  = compute_volume_signals(df)
    comp_signals = compute_compression_signals(df)

    # Base: average of the two sub-signals
    vol_score  = vol_signals["score"]
    comp_score = comp_signals["score"]
    base_score = (vol_score * 0.7 + comp_score * 0.3)

    # Boost when both fire simultaneously
    if vol_score >= 50 and comp_score >= 50:
        base_score = min(100, base_score * 1.2)

    return round(base_score, 1), {
        "volume": vol_signals,
        "compression": comp_signals,
    }
