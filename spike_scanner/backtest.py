#!/usr/bin/env python3
"""
Spike scanner historical backtest.

Usage:
  python3 backtest.py                        # Full portfolio backtest 2023-2025
  python3 backtest.py --validate             # Score timeline for known spike events
  python3 backtest.py --start 2024-01-01     # Custom date range

What signals are replayable with free data:
  ✅ Volume anomaly (20 pts) — historical OHLCV sliced by date
  ✅ BB compression (5 pts)  — historical OHLCV
  ✅ SEC 8-K filings (25 pts)— EDGAR submissions endpoint (pre-fetched, filtered by date)
  ✅ Form 4 insider buying (20 pts) — same EDGAR approach
  ❌ Reddit sentiment (15 pts) — no free historical data
  ❌ Short interest (10 pts)   — yfinance only has current SI
  ❌ Technicals (5 pts)        — skipped for simplicity

Effective tested weight: 45-65 pts of 100.
Results caveat is printed in the report.
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import scoring
import strategy
from signals.momentum import compute_momentum_score
from signals.sec_filings import load_cik_map

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S")

_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_HEADERS = {"User-Agent": config.EDGAR_USER_AGENT}

# Known spike validation events: (ticker, spike_date, description)
KNOWN_EVENTS = [
    ("NVDA", "2023-05-24", "NVDA earnings gap — AI revenue surge"),
    ("PLTR", "2024-02-05", "PLTR earnings — first profitable quarter"),
    ("INTC", "2023-10-27", "INTC quarterly earnings surge"),
    ("SMCI", "2024-02-06", "SMCI guidance raise — AI server demand"),
]


# ─────────────────────────────────────────────────────────────────────────────
# EDGAR pre-fetch (one call per ticker, cached locally)
# ─────────────────────────────────────────────────────────────────────────────

def prefetch_edgar_filings(
    tickers: list[str],
    start_date: str,
    end_date: str,
    cache_path: str = None,
) -> dict[str, list[dict]]:
    """
    Fetch all filings for each ticker from EDGAR submissions endpoint.
    Returns {ticker: [{form_type, filed_date}, ...]}.
    One API call per ticker — avoids per-day EDGAR queries during the backtest loop.
    Saves to cache_path (JSON) so reruns skip the API calls.
    """
    if cache_path is None:
        cache_path = os.path.join(config.DATA_DIR, "backtest_edgar_cache.json")

    if os.path.exists(cache_path):
        logger.info(f"Loading EDGAR filing cache from {cache_path}")
        with open(cache_path) as f:
            return json.load(f)

    cik_map = load_cik_map()
    result: dict[str, list[dict]] = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers):
        cik = cik_map.get(ticker.upper())
        if not cik:
            continue
        try:
            url = _EDGAR_SUBMISSIONS.format(cik=cik.zfill(10))
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            filings = data.get("filings", {}).get("recent", {})
            forms  = filings.get("form", [])
            dates  = filings.get("filingDate", [])

            relevant = [
                {"form_type": f, "filed_date": d}
                for f, d in zip(forms, dates)
                if d >= start_date and d <= end_date
                and f in ("8-K", "8-K/A", "4", "4/A", "SC 13D", "SC 13D/A")
            ]
            result[ticker] = relevant
        except Exception as e:
            logger.debug(f"EDGAR fetch failed for {ticker}: {e}")
            result[ticker] = []

        time.sleep(config.EDGAR_SLEEP)
        if (i + 1) % 50 == 0:
            logger.info(f"  EDGAR prefetch: {i+1}/{total} tickers")

    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(result, f)
    logger.info(f"EDGAR filing cache saved to {cache_path}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Point-in-time signal scoring (for backtest replay)
# ─────────────────────────────────────────────────────────────────────────────

def _sec_score_at_date(ticker: str, edgar_data: dict, sim_date: str) -> tuple[float, dict]:
    """Compute SEC filing score using only filings available on sim_date."""
    filings = edgar_data.get(ticker, [])
    cutoff_start = (datetime.strptime(sim_date, "%Y-%m-%d") - timedelta(days=config.EDGAR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    recent = [f for f in filings if cutoff_start <= f["filed_date"] <= sim_date]
    form_types = {f["form_type"] for f in recent}

    score = 0.0
    has_8k      = any(f in form_types for f in ("8-K", "8-K/A"))
    has_insider = any(f in form_types for f in ("4", "4/A"))
    has_activist = any(f in form_types for f in ("SC 13D", "SC 13D/A"))

    # Count unique Form 4 filers (proxy for cluster buying)
    form4_count = len([f for f in recent if f["form_type"] in ("4", "4/A")])

    if has_8k:
        score += 80   # Material event — high confidence signal
    if form4_count >= 3:
        score += 40   # Cluster buying (3+ insiders)
    elif form4_count >= 1:
        score += 15   # Single insider
    if has_activist:
        score += 20

    detail = {
        "has_8k": has_8k,
        "insider_cluster": form4_count >= 3,
        "has_activist": has_activist,
        "insider_count": form4_count,
    }
    return min(score, 100.0), detail


# Available signal weight in the backtest (sum of weights for signals we can replay)
# sec_filings(25) + insider_buying(20) + volume_anomaly(20) = 65
_BACKTEST_AVAILABLE_WEIGHT = (
    config.WEIGHTS["sec_filings"]
    + config.WEIGHTS["insider_buying"]
    + config.WEIGHTS["volume_anomaly"]
)


def compute_partial_score_at_date(
    ticker: str,
    full_df: pd.DataFrame,
    edgar_data: dict,
    sim_date: str,
) -> tuple[float, dict]:
    """
    Point-in-time composite score using only data available on sim_date.
    Omits Reddit sentiment and short interest (no historical free data).

    Score is NORMALIZED to 0-100 based on available signal weight (65/100),
    so the HOT threshold of 60 remains meaningful even with partial signals.
    A raw score of 39/65 = 60% = normalized 60 → HOT.
    """
    sim_dt = pd.Timestamp(sim_date)
    df_slice = full_df.loc[full_df.index <= sim_dt]
    if len(df_slice) < 35:
        return 0.0, {}

    mom_score, mom_detail = compute_momentum_score(ticker, df_slice)
    sec_score, sec_detail = _sec_score_at_date(ticker, edgar_data, sim_date)

    insider_score = 100.0 if sec_detail.get("insider_cluster") else (
        25.0 if sec_detail.get("insider_count", 0) >= 1 else 0.0
    )

    signals = {
        "sec_filings":    (sec_score, sec_detail),
        "insider_buying": (insider_score, sec_detail),
        "volume_anomaly": (mom_score, mom_detail),
        # sentiment_velocity, short_squeeze omitted — no historical data
    }
    raw_heat, breakdown = scoring.compute_heat_score(signals)

    # Normalize: scale raw score (max = _BACKTEST_AVAILABLE_WEIGHT) to 0-100
    normalized = min(100.0, raw_heat / _BACKTEST_AVAILABLE_WEIGHT * 100)
    return normalized, breakdown


# ─────────────────────────────────────────────────────────────────────────────
# Full portfolio backtest
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31",
    tickers: list[str] = None,
    initial_capital: float = 10_000.0,
    position_size: float = 1_000.0,
    max_positions: int = 3,
) -> dict:
    """
    Day-by-day portfolio simulation of the spike scanner entry/exit rules.
    Returns {trades: DataFrame, portfolio_values: DataFrame, metrics: dict}.
    """
    if tickers is None:
        tickers = _fetch_sp500_tickers()

    logger.info(f"Backtest: {start_date} → {end_date}  |  {len(tickers)} tickers")

    # 1. Download historical price data
    logger.info("Downloading historical price data...")
    price_data = _download_price_history(tickers, start_date, end_date)
    logger.info(f"  {len(price_data)} tickers with data")

    # 2. Pre-fetch EDGAR filings (one call per ticker)
    logger.info("Pre-fetching EDGAR filings...")
    edgar_data = prefetch_edgar_filings(list(price_data.keys()), start_date, end_date)

    # 3. Build sorted trading-day list (intersection avoids missing-date issues)
    sample_df = next(iter(price_data.values()))
    all_dates = [
        d.strftime("%Y-%m-%d")
        for d in sample_df.index
        if start_date <= d.strftime("%Y-%m-%d") <= end_date
    ]
    logger.info(f"  {len(all_dates)} trading days to simulate")

    # 4. Day-by-day replay
    cash = initial_capital
    holdings: dict[str, dict] = {}   # {ticker: position_dict}
    trades: list[dict] = []
    portfolio_values: list[dict] = []

    for sim_date in all_dates:
        # Update and check exits for current holdings
        for ticker in list(holdings.keys()):
            df = price_data.get(ticker)
            if df is None:
                continue
            score, breakdown = compute_partial_score_at_date(ticker, df, edgar_data, sim_date)
            holdings[ticker] = strategy.update_hold(holdings[ticker], score)

            if strategy.should_exit(holdings[ticker]):
                exit_price = _get_next_open(df, sim_date)
                pnl = (exit_price - holdings[ticker]["entry_price"]) * holdings[ticker]["shares"]
                cash += exit_price * holdings[ticker]["shares"]
                trades.append({
                    "date": sim_date,
                    "ticker": ticker,
                    "action": "SELL",
                    "reason": "COLD_EXIT",
                    "price": exit_price,
                    "shares": holdings[ticker]["shares"],
                    "value": exit_price * holdings[ticker]["shares"],
                    "pnl": round(pnl, 2),
                    "hold_days": (datetime.strptime(sim_date, "%Y-%m-%d") -
                                  datetime.strptime(holdings[ticker]["entry_date"], "%Y-%m-%d")).days,
                    "entry_score": holdings[ticker]["entry_score"],
                    "exit_score": score,
                })
                del holdings[ticker]

        # Score all tickers and find new HOT candidates
        hot_candidates = []
        for ticker, df in price_data.items():
            if ticker in holdings:
                continue
            score, breakdown = compute_partial_score_at_date(ticker, df, edgar_data, sim_date)
            if score >= config.HOT_THRESHOLD:
                active = scoring._get_compression_score({"volume_anomaly": (score, breakdown)})  # reuse count helper
                # Simplified: count non-zero contributions
                active_count = sum(
                    1 for k, v in breakdown.items()
                    if not k.startswith("_") and isinstance(v, dict) and v.get("contribution", 0) > 0
                )
                if active_count >= strategy.MIN_ACTIVE_SIGNALS:
                    hot_candidates.append((ticker, score, breakdown))

        hot_candidates.sort(key=lambda x: x[1], reverse=True)

        for ticker, score, breakdown in hot_candidates:
            if len(holdings) < max_positions and cash >= position_size:
                entry_price = _get_next_open(price_data[ticker], sim_date)
                if entry_price <= 0:
                    continue
                shares = position_size / entry_price
                cash -= position_size
                holdings[ticker] = strategy.open_position(ticker, sim_date, entry_price, score)
                trades.append({
                    "date": sim_date,
                    "ticker": ticker,
                    "action": "BUY",
                    "reason": "HOT_ENTRY",
                    "price": entry_price,
                    "shares": round(shares, 4),
                    "value": position_size,
                    "pnl": None,
                    "hold_days": None,
                    "entry_score": score,
                    "exit_score": None,
                })
            elif len(holdings) >= max_positions:
                evict = strategy.check_rotation(ticker, score, breakdown, holdings)
                if evict and cash + (holdings[evict]["shares"] * _get_next_open(price_data.get(evict, pd.DataFrame()), sim_date)) >= position_size:
                    # Sell evicted
                    evict_price = _get_next_open(price_data[evict], sim_date)
                    evict_proceeds = evict_price * holdings[evict]["shares"]
                    evict_pnl = (evict_price - holdings[evict]["entry_price"]) * holdings[evict]["shares"]
                    cash += evict_proceeds
                    trades.append({
                        "date": sim_date,
                        "ticker": evict,
                        "action": "SELL",
                        "reason": "ROTATION_OUT",
                        "price": evict_price,
                        "shares": holdings[evict]["shares"],
                        "value": evict_proceeds,
                        "pnl": round(evict_pnl, 2),
                        "hold_days": (datetime.strptime(sim_date, "%Y-%m-%d") -
                                      datetime.strptime(holdings[evict]["entry_date"], "%Y-%m-%d")).days,
                        "entry_score": holdings[evict]["entry_score"],
                        "exit_score": score,
                    })
                    del holdings[evict]
                    # Buy new
                    entry_price = _get_next_open(price_data[ticker], sim_date)
                    if entry_price > 0 and cash >= position_size:
                        cash -= position_size
                        holdings[ticker] = strategy.open_position(ticker, sim_date, entry_price, score)
                        trades.append({
                            "date": sim_date,
                            "ticker": ticker,
                            "action": "BUY",
                            "reason": "HOT_ENTRY",
                            "price": entry_price,
                            "shares": round(position_size / entry_price, 4),
                            "value": position_size,
                            "pnl": None,
                            "hold_days": None,
                            "entry_score": score,
                            "exit_score": None,
                        })

        # Mark-to-market
        holdings_value = sum(
            holdings[t]["shares"] * _get_close(price_data.get(t, pd.DataFrame()), sim_date)
            for t in holdings
        )
        portfolio_values.append({
            "date": sim_date,
            "total_value": round(cash + holdings_value, 2),
            "cash": round(cash, 2),
            "holdings_value": round(holdings_value, 2),
            "num_holdings": len(holdings),
        })

    # Close all remaining positions at end
    final_date = all_dates[-1]
    for ticker in list(holdings.keys()):
        exit_price = _get_close(price_data.get(ticker, pd.DataFrame()), final_date)
        pnl = (exit_price - holdings[ticker]["entry_price"]) * holdings[ticker]["shares"]
        cash += exit_price * holdings[ticker]["shares"]
        trades.append({
            "date": final_date,
            "ticker": ticker,
            "action": "SELL",
            "reason": "END_OF_BACKTEST",
            "price": exit_price,
            "shares": holdings[ticker]["shares"],
            "value": exit_price * holdings[ticker]["shares"],
            "pnl": round(pnl, 2),
            "hold_days": (datetime.strptime(final_date, "%Y-%m-%d") -
                          datetime.strptime(holdings[ticker]["entry_date"], "%Y-%m-%d")).days,
            "entry_score": holdings[ticker]["entry_score"],
            "exit_score": None,
        })

    trades_df = pd.DataFrame(trades)
    pv_df = pd.DataFrame(portfolio_values)
    metrics = _compute_metrics(trades_df, pv_df, initial_capital, start_date, end_date)
    return {"trades": trades_df, "portfolio_values": pv_df, "metrics": metrics}


# ─────────────────────────────────────────────────────────────────────────────
# Known event validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_known_events() -> None:
    """
    For each known spike event, show the heat score in the 30 days leading up to it.
    Shows whether the system would have flagged it HOT before the spike.
    """
    print("\n" + "=" * 70)
    print("  KNOWN EVENT VALIDATION")
    print("  (Tests only volume + SEC signals — 45% of total weight)")
    print("=" * 70)

    edgar_data = prefetch_edgar_filings(
        [e[0] for e in KNOWN_EVENTS],
        "2022-12-01",
        "2024-12-31",
        cache_path=os.path.join(config.DATA_DIR, "validation_edgar_cache.json"),
    )

    for ticker, spike_date, description in KNOWN_EVENTS:
        print(f"\n  {ticker}: {description}")
        print(f"  Spike date: {spike_date}")
        print(f"  {'Date':<12} {'Score':>6} {'Class':<6} {'Vol Ratio':>10} {'8-K':>5} {'Form4':>6}")
        print(f"  {'-'*12} {'-'*6} {'-'*6} {'-'*10} {'-'*5} {'-'*6}")

        try:
            df = yf.download(ticker, start="2022-12-01", end="2024-12-31", progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception as e:
            print(f"  Could not fetch data for {ticker}: {e}")
            continue

        spike_dt = datetime.strptime(spike_date, "%Y-%m-%d")
        first_hot_days_before = None

        for days_before in range(30, -1, -1):
            check_date = (spike_dt - timedelta(days=days_before)).strftime("%Y-%m-%d")
            if check_date > spike_date:
                continue
            score, breakdown = compute_partial_score_at_date(ticker, df, edgar_data, check_date)
            class_str = scoring.classify_heat(score)

            vol_detail = breakdown.get("volume_anomaly", {})
            if isinstance(vol_detail, dict) and "detail" in vol_detail:
                vol_detail = vol_detail["detail"]
            vol_ratio = vol_detail.get("volume", {}).get("surge_ratio", "—") if isinstance(vol_detail, dict) else "—"

            sec_detail = breakdown.get("sec_filings", {})
            if isinstance(sec_detail, dict) and "detail" in sec_detail:
                sec_detail = sec_detail["detail"]
            has_8k   = "YES" if (isinstance(sec_detail, dict) and sec_detail.get("has_8k")) else "—"
            has_form4 = "YES" if (isinstance(sec_detail, dict) and sec_detail.get("insider_cluster")) else "—"

            marker = " ← SPIKE" if days_before == 0 else ""
            print(f"  {check_date:<12} {score:>6.1f} {class_str:<6} {str(vol_ratio):>10} {has_8k:>5} {has_form4:>6}{marker}")

            if class_str == "HOT" and first_hot_days_before is None:
                first_hot_days_before = days_before

        if first_hot_days_before is not None:
            print(f"\n  → System flagged HOT {first_hot_days_before} days before spike ✓")
        else:
            print(f"\n  → System did NOT flag HOT in 30-day window (volume/SEC signal only)")


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

def print_backtest_report(results: dict) -> None:
    metrics = results["metrics"]
    trades  = results["trades"]
    pv      = results["portfolio_values"]

    print("\n" + "=" * 70)
    print("  BACKTEST RESULTS")
    print("  Signals tested: Volume anomaly + SEC filings (~45% of total weight)")
    print("  Reddit sentiment and short interest NOT included (no historical data)")
    print("=" * 70)
    print(f"\n  Period:            {pv['date'].iloc[0]}  →  {pv['date'].iloc[-1]}")
    print(f"  Starting capital:  ${metrics['initial_capital']:,.2f}")
    print(f"  Ending value:      ${metrics['final_value']:,.2f}")
    print(f"\n  Total return:      {metrics['total_return_pct']:+.1f}%")
    print(f"  CAGR:              {metrics['cagr_pct']:+.1f}%")
    print(f"  Max drawdown:      {metrics['max_drawdown_pct']:.1f}%")
    print(f"\n  Total trades:      {metrics['total_trades']}")
    print(f"  Win rate:          {metrics['win_rate_pct']:.1f}%")
    print(f"  Avg hold period:   {metrics['avg_hold_days']:.0f} days")
    print(f"  Avg P&L / trade:   ${metrics['avg_pnl_per_trade']:+.2f}")
    print(f"  Best trade:        ${metrics['best_trade']:+.2f}  ({metrics['best_trade_ticker']})")
    print(f"  Worst trade:       ${metrics['worst_trade']:+.2f}  ({metrics['worst_trade_ticker']})")
    print(f"  Capital utilized:  {metrics['capital_utilization_pct']:.0f}% avg")

    if not trades.empty:
        sells = trades[trades["action"] == "SELL"]
        print("\n  Exit reasons:")
        for reason, count in sells["reason"].value_counts().items():
            print(f"    {reason:<25} {count}")

    print("=" * 70)


def save_backtest_results(results: dict, label: str = None) -> str:
    label = label or datetime.now().strftime("%Y%m%d_%H%M")
    os.makedirs(config.DATA_DIR, exist_ok=True)

    trades_path = os.path.join(config.DATA_DIR, f"backtest_trades_{label}.csv")
    pv_path     = os.path.join(config.DATA_DIR, f"backtest_portfolio_{label}.csv")

    results["trades"].to_csv(trades_path, index=False)
    results["portfolio_values"].to_csv(pv_path, index=False)
    logger.info(f"Backtest results saved: {trades_path}")
    return trades_path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_sp500_tickers() -> list[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                              attrs={"id": "constituents"})
        return tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
    except Exception:
        return []


def _download_price_history(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    price_data = {}
    # Add 1yr buffer before start for BB percentile calculation
    dl_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")

    batches = [tickers[i:i + 50] for i in range(0, len(tickers), 50)]
    for i, batch in enumerate(batches):
        try:
            raw = yf.download(batch, start=dl_start, end=end, interval="1d",
                              group_by="ticker", auto_adjust=True, progress=False, threads=True)
            for t in batch:
                try:
                    df = raw[t] if len(batch) > 1 else raw
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df = df.dropna(how="all")
                    if len(df) >= 60:
                        price_data[t] = df
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Batch download failed: {e}")
        time.sleep(0.5)
        if (i + 1) % 5 == 0:
            logger.info(f"  Price data: {(i+1)*50}/{len(tickers)} tickers")

    return price_data


def _get_next_open(df: pd.DataFrame, sim_date: str) -> float:
    """Get the next trading day's OPEN after sim_date (realistic entry/exit price)."""
    if df is None or df.empty:
        return 0.0
    try:
        future = df.loc[df.index > pd.Timestamp(sim_date)]
        if future.empty:
            return _get_close(df, sim_date)
        val = future["Open"].iloc[0]
        return float(val.item() if hasattr(val, "item") else val)
    except Exception:
        return 0.0


def _get_close(df: pd.DataFrame, sim_date: str) -> float:
    """Get close price on or before sim_date."""
    if df is None or df.empty:
        return 0.0
    try:
        past = df.loc[df.index <= pd.Timestamp(sim_date)]
        if past.empty:
            return 0.0
        val = past["Close"].iloc[-1]
        return float(val.item() if hasattr(val, "item") else val)
    except Exception:
        return 0.0


def _compute_metrics(
    trades: pd.DataFrame,
    pv: pd.DataFrame,
    initial_capital: float,
    start_date: str,
    end_date: str,
) -> dict:
    final_value = pv["total_value"].iloc[-1] if not pv.empty else initial_capital
    total_return = (final_value - initial_capital) / initial_capital * 100

    years = (datetime.strptime(end_date, "%Y-%m-%d") -
             datetime.strptime(start_date, "%Y-%m-%d")).days / 365.25
    cagr = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

    # Max drawdown
    rolling_max = pv["total_value"].cummax()
    drawdown = (pv["total_value"] - rolling_max) / rolling_max * 100
    max_drawdown = drawdown.min()

    # Capital utilization: avg % of capital deployed
    avg_util = (pv["holdings_value"] / initial_capital * 100).mean() if not pv.empty else 0

    # Trade metrics
    sells = trades[trades["action"] == "SELL"] if not trades.empty else pd.DataFrame()
    closed = sells[sells["pnl"].notna()] if not sells.empty else pd.DataFrame()

    win_rate      = (closed["pnl"] > 0).mean() * 100 if len(closed) > 0 else 0
    avg_pnl       = closed["pnl"].mean() if len(closed) > 0 else 0
    avg_hold_days = closed["hold_days"].mean() if len(closed) > 0 else 0
    best_trade    = closed["pnl"].max() if len(closed) > 0 else 0
    worst_trade   = closed["pnl"].min() if len(closed) > 0 else 0

    best_idx  = closed["pnl"].idxmax() if len(closed) > 0 else None
    worst_idx = closed["pnl"].idxmin() if len(closed) > 0 else None
    best_ticker  = closed.loc[best_idx, "ticker"] if best_idx is not None else "—"
    worst_ticker = closed.loc[worst_idx, "ticker"] if worst_idx is not None else "—"

    return {
        "initial_capital":        initial_capital,
        "final_value":            round(final_value, 2),
        "total_return_pct":       round(total_return, 2),
        "cagr_pct":               round(cagr, 2),
        "max_drawdown_pct":       round(max_drawdown, 2),
        "total_trades":           len(closed),
        "win_rate_pct":           round(win_rate, 1),
        "avg_hold_days":          round(avg_hold_days, 1),
        "avg_pnl_per_trade":      round(avg_pnl, 2),
        "best_trade":             round(best_trade, 2),
        "best_trade_ticker":      best_ticker,
        "worst_trade":            round(worst_trade, 2),
        "worst_trade_ticker":     worst_ticker,
        "capital_utilization_pct": round(avg_util, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spike scanner backtest")
    parser.add_argument("--validate", action="store_true",
                        help="Run known-event validation instead of full backtest")
    parser.add_argument("--start", default="2023-01-01", help="Backtest start date")
    parser.add_argument("--end",   default="2025-12-31", help="Backtest end date")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital")
    args = parser.parse_args()

    os.makedirs(config.DATA_DIR, exist_ok=True)

    if args.validate:
        validate_known_events()
    else:
        results = run_backtest(
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
        )
        print_backtest_report(results)
        save_backtest_results(results)
