"""
Signal detection and state management for dip-ladder strategy.

Level rules:
  Level 1: price <= 20MA  →  buy over 2 days
  Level 2: price <= 60MA  →  buy over 3 days
  Level 3: price <= 120MA →  buy over 5 days
  Level 4: price <= 120MA AND RSI < 35  →  buy over 5 days

Re-trigger rules (after a level completes):
  A completed level enters cooldown. It re-triggers only when:
    (a) price rises above that level's MA trigger, then falls back to it, OR
    (b) a deeper level triggers first (independent — no interaction needed)
  While in cooldown, the level is skipped even if the condition is still met.
"""

import json
import os
from datetime import date

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

LEVELS = {
    1: {"total_days": 2},
    2: {"total_days": 3},
    3: {"total_days": 5},
    4: {"total_days": 5},
}


def _default_ticker_state() -> dict:
    return {
        str(lvl): {
            "active": False,
            "day": 0,
            "total_days": cfg["total_days"],
            "triggered_on": None,
            "cooldown": False,       # True after completion, waiting for bounce
            "price_rose_above": False,  # True once price crosses back above trigger MA
        }
        for lvl, cfg in LEVELS.items()
    }


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _is_triggered(level: int, ind: dict) -> bool:
    price, ma20, ma60, ma120, rsi_val = (
        ind["price"], ind["ma20"], ind["ma60"], ind["ma120"], ind["rsi"]
    )
    if level == 1:
        return price <= ma20
    if level == 2:
        return price <= ma60
    if level == 3:
        return price <= ma120
    if level == 4:
        return price <= ma120 and rsi_val < 35
    return False


def _trigger_ma(level: int, ind: dict) -> float:
    """Return the MA value that acts as the trigger line for a given level."""
    if level == 1:
        return ind["ma20"]
    if level == 2:
        return ind["ma60"]
    if level in (3, 4):
        return ind["ma120"]
    return float("inf")


def update_ticker(ticker: str, ind: dict, state: dict) -> tuple[dict, list[dict]]:
    """
    Advance state for one ticker and return updated state + list of buy actions.

    Each buy action dict:
      {level, day, total_days, action: 'new'|'continue'|'complete'}
    """
    if ticker not in state:
        state[ticker] = _default_ticker_state()

    today = date.today().isoformat()
    actions = []
    price = ind["price"]

    for lvl in range(1, 5):
        key = str(lvl)
        lvl_state = state[ticker][key]

        # Ensure cooldown fields exist for states saved before this logic was added
        lvl_state.setdefault("cooldown", False)
        lvl_state.setdefault("price_rose_above", False)

        if lvl_state["active"]:
            # Ongoing sequence: advance day
            lvl_state["day"] += 1
            if lvl_state["day"] >= lvl_state["total_days"]:
                lvl_state["active"] = False
                lvl_state["cooldown"] = True
                lvl_state["price_rose_above"] = False
                action = "complete"
            else:
                action = "continue"
            actions.append({
                "level": lvl,
                "day": lvl_state["day"],
                "total_days": lvl_state["total_days"],
                "action": action,
            })

        elif lvl_state["cooldown"]:
            # After completion: wait for price to bounce above trigger MA, then return to it
            trigger_ma = _trigger_ma(lvl, ind)
            if price > trigger_ma:
                lvl_state["price_rose_above"] = True

            if lvl_state["price_rose_above"] and price <= trigger_ma:
                # Bounce complete — clear cooldown and trigger new sequence
                lvl_state["cooldown"] = False
                lvl_state["price_rose_above"] = False
                lvl_state["active"] = True
                lvl_state["day"] = 1
                lvl_state["triggered_on"] = today
                actions.append({
                    "level": lvl,
                    "day": 1,
                    "total_days": lvl_state["total_days"],
                    "action": "new",
                })
            # else: still in cooldown, no action this tick

        elif _is_triggered(lvl, ind):
            # New signal (no cooldown)
            lvl_state["active"] = True
            lvl_state["day"] = 1
            lvl_state["triggered_on"] = today
            actions.append({
                "level": lvl,
                "day": 1,
                "total_days": lvl_state["total_days"],
                "action": "new",
            })

    return state, actions
