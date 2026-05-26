"""
Entry, hold, and exit rule engine for the spike scanner.

Entry:   score >= HOT (60), ≥2 distinct active signals, not already held
Exit:
  Phase 1 (days 0-10): hard stop-loss at -8% from entry price
  Phase 2 (day 10+):   20% trailing stop from highest close since entry
  Always:              force exit after 60 trading days
Rotation: if max positions full, evict lowest-scorer if new score beats it by ROTATION_MARGIN
Sizing:   $1,000 per position, max 3 concurrent

Based on analysis of NVDA/PLTR/INTC/SMCI/CELH spikes:
- 10% trailing stop triggers during normal mid-run consolidations (loses winners early)
- Score-based exit is worse — filing signals age out in 3-7 days, exits week 1 every time
- Two-phase approach: protect capital early, ride momentum with wide trail after day 10
"""
from datetime import datetime

import config

POSITION_SIZE_USD  = 1_000.0
MAX_POSITIONS      = 3
ROTATION_MARGIN    = 5.0    # New score must beat evictee by this many pts
MIN_ACTIVE_SIGNALS = 2      # Signal categories with contribution > 0 required to enter

STOP_LOSS_PCT  = 0.08   # Phase 1: exit if price drops 8% below entry (days 0-10)
TRAIL_STOP_PCT = 0.20   # Phase 2: exit if price drops 20% below peak close (day 10+)
MAX_HOLD_DAYS  = 60     # Force exit after 60 trading days regardless
PHASE1_DAYS    = 10     # Days in hard-stop phase before switching to trailing stop

_SIGNAL_CATEGORIES = {
    "sec_filings", "insider_buying", "volume_anomaly",
    "sentiment_velocity", "short_squeeze", "options_flow", "technicals",
}


def count_active_signals(breakdown: dict) -> int:
    """Count signal categories that contributed a non-zero score."""
    return sum(
        1 for k, v in breakdown.items()
        if k in _SIGNAL_CATEGORIES
        and isinstance(v, dict)
        and v.get("contribution", 0) > 0
    )


def should_enter(ticker: str, score: float, breakdown: dict, current_positions: dict) -> bool:
    """Return True if entry conditions are met and a slot is available."""
    if ticker in current_positions:
        return False
    if score < config.HOT_THRESHOLD:
        return False
    if count_active_signals(breakdown) < MIN_ACTIVE_SIGNALS:
        return False
    if len(current_positions) < MAX_POSITIONS:
        return True
    return False


def check_rotation(new_ticker: str, new_score: float, breakdown: dict, current_positions: dict) -> str | None:
    """
    If all slots are full, check whether new_ticker should evict the weakest holding.
    Returns the ticker to evict, or None.
    """
    if new_ticker in current_positions:
        return None
    if len(current_positions) < MAX_POSITIONS:
        return None
    if count_active_signals(breakdown) < MIN_ACTIVE_SIGNALS:
        return None
    if new_score < config.HOT_THRESHOLD:
        return None

    weakest_ticker = min(
        current_positions,
        key=lambda t: current_positions[t].get("latest_score", 0),
    )
    weakest_score = current_positions[weakest_ticker].get("latest_score", 0)

    if new_score >= weakest_score + ROTATION_MARGIN:
        return weakest_ticker
    return None


def open_position(ticker: str, entry_date: str, entry_price: float, entry_score: float) -> dict:
    """Create a new position record."""
    shares = POSITION_SIZE_USD / entry_price if entry_price > 0 else 0
    return {
        "entry_date":            entry_date,
        "entry_price":           entry_price,
        "entry_score":           entry_score,
        "shares":                round(shares, 4),
        "latest_score":          entry_score,
        "peak_price":            entry_price,   # highest close since entry — drives trailing stop
        "hold_days":             0,
        "consecutive_cold_days": 0,             # informational only, not used for exit
        "score_history":         [entry_score],
    }


def update_hold(position: dict, today_score: float, current_price: float = 0.0) -> dict:
    """Update a held position with today's score and price. Returns updated position dict."""
    pos = dict(position)
    pos["latest_score"]  = today_score
    pos["score_history"] = pos.get("score_history", []) + [today_score]
    pos["hold_days"]     = pos.get("hold_days", 0) + 1

    if current_price > 0:
        pos["peak_price"] = max(pos.get("peak_price", pos.get("entry_price", 0)), current_price)

    # Track cold days for display only
    if today_score < config.WARM_THRESHOLD:
        pos["consecutive_cold_days"] = pos.get("consecutive_cold_days", 0) + 1
    else:
        pos["consecutive_cold_days"] = 0

    return pos


def should_exit(position: dict, current_price: float = 0.0) -> tuple[bool, str]:
    """
    Returns (do_exit, reason).

    Phase 1 (hold_days <= PHASE1_DAYS): hard stop at -STOP_LOSS_PCT from entry
    Phase 2 (hold_days > PHASE1_DAYS):  trailing stop at -TRAIL_STOP_PCT from peak close
    Always: force exit at MAX_HOLD_DAYS
    """
    if current_price <= 0:
        return False, ""

    hold_days   = position.get("hold_days", 0)
    entry_price = position.get("entry_price", 0)
    peak_price  = position.get("peak_price", entry_price)

    if hold_days >= MAX_HOLD_DAYS:
        return True, "MAX_HOLD"

    if hold_days <= PHASE1_DAYS:
        if entry_price > 0 and current_price < entry_price * (1 - STOP_LOSS_PCT):
            return True, "STOP_LOSS"
    else:
        if peak_price > 0 and current_price < peak_price * (1 - TRAIL_STOP_PCT):
            return True, "TRAIL_STOP"

    return False, ""


def trail_stop_price(position: dict) -> float:
    """Return the current trailing stop price (useful for display)."""
    hold_days   = position.get("hold_days", 0)
    entry_price = position.get("entry_price", 0)
    peak_price  = position.get("peak_price", entry_price)

    if hold_days <= PHASE1_DAYS:
        return entry_price * (1 - STOP_LOSS_PCT) if entry_price else 0.0
    return peak_price * (1 - TRAIL_STOP_PCT) if peak_price else 0.0


def pnl_pct(position: dict, current_price: float) -> float | None:
    """Return unrealized P&L % for a position given today's price."""
    entry = position.get("entry_price")
    if not entry or not current_price:
        return None
    return round((current_price - entry) / entry * 100, 2)
