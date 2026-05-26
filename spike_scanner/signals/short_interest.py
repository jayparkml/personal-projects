"""
Short squeeze setup detection.

Short interest alone is NOT a leading indicator — many heavily shorted stocks
deserve to be shorted. It becomes signal when:
  SI > 15% of float AND days-to-cover > 3 AND a positive catalyst exists elsewhere.

This signal is fuel, not a trigger. Weight accordingly (10 pts max).
Data comes from yfinance (already fetched in runner price pass) — no extra API calls.
"""
import logging

import config

logger = logging.getLogger(__name__)


def compute_short_squeeze_score(ticker: str, yf_info: dict) -> tuple[float, dict]:
    """
    Compute short squeeze setup score (0-100) from yfinance info dict.

    yf_info fields used:
      shortPercentOfFloat — SI as % of float (e.g. 0.22 = 22%)
      shortRatio          — days-to-cover (short interest / avg daily volume)
    """
    si_pct = yf_info.get("shortPercentOfFloat") or 0.0
    days_to_cover = yf_info.get("shortRatio") or 0.0

    detail = {
        "short_pct_float": round(si_pct * 100, 1) if si_pct else None,
        "days_to_cover": round(days_to_cover, 1) if days_to_cover else None,
        "is_squeeze_setup": False,
    }

    if not si_pct or not days_to_cover:
        return 0.0, detail

    score = 0.0

    # High SI: > 20% float = extreme (max SI contribution)
    if si_pct >= 0.20:
        score += 50
    elif si_pct >= 0.15:
        score += 35
    elif si_pct >= 0.10:
        score += 15
    else:
        return 0.0, detail  # < 10% SI = not a squeeze candidate

    # Days to cover: > 5 = hard to unwind quickly
    if days_to_cover >= 5:
        score += 50
    elif days_to_cover >= 3:
        score += 30
    else:
        score += 10

    is_setup = si_pct >= 0.15 and days_to_cover >= 3
    detail["is_squeeze_setup"] = is_setup

    return min(score, 100.0), detail
