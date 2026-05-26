"""
Options flow signal — unusual call activity as a leading pre-spike indicator.

Call/Put volume ratio spikes often precede price moves because options buyers
are positioning ahead of expected catalysts. Fresh call buying (volume >> OI)
is more meaningful than existing positions.

Uses yfinance options chain (free, no API key). Only called for tickers
that already have meaningful signals from other sources.
"""
import logging

import yfinance as yf
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Minimum total option volume to consider flow meaningful
_MIN_OPTION_VOLUME = 200

# Use options expiring within this many days (most sentiment-driven)
_MAX_DTE = 45


def compute_options_flow_score(ticker: str) -> tuple[float, dict]:
    """
    Score based on unusual call options activity (0-100).

    Signals:
    - Call/Put volume ratio > 2x = bullish directional flow
    - Call volume / open interest > 0.3 = fresh new positioning
    - Concentrating in near-term expiry = more urgent / conviction
    """
    try:
        t = yf.Ticker(ticker)
        expiries = t.options
        if not expiries:
            return 0.0, {}

        # Find the nearest expiry within DTE window
        today = datetime.now().date()
        target_expiry = None
        for exp in expiries:
            try:
                exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                dte = (exp_date - today).days
                if 0 < dte <= _MAX_DTE:
                    target_expiry = exp
                    break
            except ValueError:
                continue

        if target_expiry is None and expiries:
            target_expiry = expiries[0]  # Fallback to nearest available

        if target_expiry is None:
            return 0.0, {}

        chain = t.option_chain(target_expiry)
        calls = chain.calls
        puts = chain.puts

        if calls.empty or puts.empty:
            return 0.0, {}

        call_vol = float(calls["volume"].fillna(0).sum())
        put_vol  = float(puts["volume"].fillna(0).sum())
        call_oi  = float(calls["openInterest"].fillna(0).sum())

        total_vol = call_vol + put_vol
        if total_vol < _MIN_OPTION_VOLUME:
            return 0.0, {"reason": "insufficient_volume", "total_vol": int(total_vol)}

        cp_ratio    = call_vol / max(put_vol, 1)
        call_vol_oi = call_vol / max(call_oi, 1)

        score = 0.0

        # Call/Put ratio scoring: bullish if calls dominate
        if cp_ratio >= 5.0:
            score += 60
        elif cp_ratio >= 3.0:
            score += 40
        elif cp_ratio >= 2.0:
            score += 25
        elif cp_ratio >= 1.5:
            score += 10

        # Volume/OI: high ratio = fresh new call buying (not just existing positions)
        if call_vol_oi >= 0.5:
            score += 40
        elif call_vol_oi >= 0.3:
            score += 25
        elif call_vol_oi >= 0.1:
            score += 10

        return min(score, 100.0), {
            "cp_ratio":    round(cp_ratio, 2),
            "call_vol":    int(call_vol),
            "put_vol":     int(put_vol),
            "call_vol_oi": round(call_vol_oi, 3),
            "expiry":      target_expiry,
        }

    except Exception as e:
        logger.debug(f"Options flow failed for {ticker}: {e}")
        return 0.0, {}
