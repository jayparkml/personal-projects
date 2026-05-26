"""File-based state management between daily runs."""
import csv
import json
import os
from datetime import datetime, timedelta

import pandas as pd

import config

TRADE_LOG_FILE = os.path.join(config.DATA_DIR, "trade_log.csv")


def ensure_dirs():
    for d in [
        config.DATA_DIR,
        config.CACHE_DIR,
        config.REPORT_DIR,
        os.path.join(config.CACHE_DIR, "price"),
        os.path.join(config.CACHE_DIR, "filings"),
        os.path.join(config.CACHE_DIR, "sentiment"),
    ]:
        os.makedirs(d, exist_ok=True)


def load_state() -> dict:
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    return {"scores": {}, "universe_built": None, "sentiment_history": {}}


def save_state(state: dict) -> None:
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Price data cache ──────────────────────────────────────────────────────────

def price_cache_path(ticker: str) -> str:
    return os.path.join(config.CACHE_DIR, "price", f"{ticker}.csv")


def load_price_data(ticker: str, max_age_hours: int = 20) -> pd.DataFrame | None:
    path = price_cache_path(ticker)
    if not os.path.exists(path):
        return None
    age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
    if age > timedelta(hours=max_age_hours):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True, date_format="%Y-%m-%d")
        if df.empty or len(df) < 30:
            return None
        return df
    except Exception:
        return None


def save_price_data(ticker: str, df: pd.DataFrame) -> None:
    df.to_csv(price_cache_path(ticker))


# ── Sentiment history cache ───────────────────────────────────────────────────

def sentiment_history_path() -> str:
    return os.path.join(config.CACHE_DIR, "sentiment", "history.json")


def load_sentiment_history() -> dict:
    path = sentiment_history_path()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_sentiment_history(history: dict) -> None:
    with open(sentiment_history_path(), "w") as f:
        json.dump(history, f)


def append_sentiment_day(date_str: str, mentions: dict[str, int]) -> None:
    history = load_sentiment_history()
    history[date_str] = mentions
    # Keep only last 14 days
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    history = {k: v for k, v in history.items() if k >= cutoff}
    save_sentiment_history(history)


def get_sentiment_baseline(ticker: str, lookback_days: int = 7) -> float:
    history = load_sentiment_history()
    today = datetime.now().strftime("%Y-%m-%d")
    counts = []
    for i in range(1, lookback_days + 1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        if day in history:
            counts.append(history[day].get(ticker, 0))
    return sum(counts) / max(len(counts), 1)


# ── Filing cache ──────────────────────────────────────────────────────────────

def filing_cache_path(cik: str) -> str:
    return os.path.join(config.CACHE_DIR, "filings", f"{cik}.json")


def load_filing_cache(cik: str) -> dict | None:
    path = filing_cache_path(cik)
    if not os.path.exists(path):
        return None
    age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
    if age > timedelta(hours=12):
        return None
    with open(path, "r") as f:
        return json.load(f)


def save_filing_cache(cik: str, data: dict) -> None:
    with open(filing_cache_path(cik), "w") as f:
        json.dump(data, f)


# ── Live positions ────────────────────────────────────────────────────────────

def positions_path() -> str:
    return os.path.join(config.DATA_DIR, "positions.json")


def load_positions() -> dict:
    path = positions_path()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_positions(positions: dict) -> None:
    with open(positions_path(), "w") as f:
        json.dump(positions, f, indent=2)


# ── Trade log ─────────────────────────────────────────────────────────────────

_TRADE_LOG_FIELDS = [
    "date", "ticker", "action", "reason", "price", "score",
    "entry_date", "entry_price", "hold_days", "pnl_pct",
]


def log_trade(
    ticker: str,
    action: str,
    date: str,
    price: float,
    score: float,
    reason: str = "",
    entry_date: str = "",
    entry_price: float | None = None,
    hold_days: int | None = None,
    pnl_pct: float | None = None,
) -> None:
    """Append one BUY or SELL record to the persistent trade log CSV."""
    file_exists = os.path.exists(TRADE_LOG_FILE)
    with open(TRADE_LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_TRADE_LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "date":         date,
            "ticker":       ticker,
            "action":       action,
            "reason":       reason,
            "price":        round(price, 2),
            "score":        round(score, 1),
            "entry_date":   entry_date,
            "entry_price":  round(entry_price, 2) if entry_price is not None else "",
            "hold_days":    hold_days if hold_days is not None else "",
            "pnl_pct":      f"{pnl_pct:+.2f}%" if pnl_pct is not None else "",
        })
