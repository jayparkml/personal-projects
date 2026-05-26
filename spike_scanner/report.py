"""Console, CSV, and JSON report generation."""
import csv
import json
import os
from datetime import datetime

import config
import scoring


def print_daily_report(results: list[dict], date: str, runtime_seconds: float, universe_size: int) -> None:
    hot   = [r for r in results if r["class"] == "HOT"]
    warm  = [r for r in results if r["class"] == "WARM"]
    new   = [r for r in results if r["is_new_entrant"]]
    accel = sorted([r for r in results if r["is_accelerating"]], key=lambda x: x["delta_1d"] or 0, reverse=True)

    width = 80
    print("=" * width)
    print(f"  SPIKE SCANNER — Daily Watchlist  {date}")
    print(f"  Universe: {universe_size:,} stocks  |  Runtime: {_fmt_seconds(runtime_seconds)}")
    print(f"  HOT: {len(hot)}  |  WARM: {len(warm)}  |  Total shown: {len(results)}")
    print("=" * width)
    print(f"  {'#':<4} {'Ticker':<7} {'Score':<7} {'Class':<6} {'Delta':<8} Top Signal")
    print("-" * width)

    for i, r in enumerate(results, 1):
        delta_str = _fmt_delta(r.get("delta_1d"), r.get("is_new_entrant"))
        class_str = r["class"]
        print(f"  {i:<4} {r['ticker']:<7} {r['score']:<7.1f} {class_str:<6} {delta_str:<8} {r['top_signal']}")

    print("-" * width)

    if new:
        tickers = ", ".join(f"{r['ticker']} ({r['score']:.0f})" for r in new[:10])
        print(f"\n  NEW ENTRANTS: {tickers}")

    if accel:
        movers = ", ".join(
            f"{r['ticker']} +{r['delta_1d']:.0f}" for r in accel[:5]
        )
        print(f"  BIGGEST MOVERS: {movers}")

    print("=" * width)


def _fmt_seconds(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}m {s}s"


def _fmt_delta(delta, is_new: bool) -> str:
    if is_new:
        return "NEW"
    if delta is None:
        return "—"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}"


def save_csv_report(results: list[dict], date: str) -> str:
    path = os.path.join(config.REPORT_DIR, f"{date}.csv")
    fieldnames = ["rank", "ticker", "score", "class", "delta_1d", "is_new_entrant",
                  "is_accelerating", "top_signal", "sec_contribution", "insider_contribution",
                  "volume_contribution", "sentiment_contribution", "si_contribution"]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for i, r in enumerate(results, 1):
            breakdown = r.get("breakdown", {})
            writer.writerow({
                "rank":                i,
                "ticker":              r["ticker"],
                "score":               r["score"],
                "class":               r["class"],
                "delta_1d":            r.get("delta_1d"),
                "is_new_entrant":      r.get("is_new_entrant"),
                "is_accelerating":     r.get("is_accelerating"),
                "top_signal":          r.get("top_signal"),
                "sec_contribution":    _contribution(breakdown, "sec_filings"),
                "insider_contribution": _contribution(breakdown, "insider_buying"),
                "volume_contribution": _contribution(breakdown, "volume_anomaly"),
                "sentiment_contribution": _contribution(breakdown, "sentiment_velocity"),
                "si_contribution":     _contribution(breakdown, "short_squeeze"),
            })
    return path


def print_positions_section(
    positions: dict,
    score_by_ticker: dict,
    price_data: dict,
    today: str,
) -> None:
    """Print active positions table with two-phase exit levels."""
    if not positions:
        print("\n  (No active positions)")
        return

    import strategy as strat

    width = 88
    print(f"\n{'─' * width}")
    print(f"  ACTIVE POSITIONS ({len(positions)}/{strat.MAX_POSITIONS})")
    print(f"{'─' * width}")
    print(f"  {'Ticker':<7} {'Entry':<11} {'Entry$':>8} {'Day':>4} {'Price':>8} {'Stop$':>8} {'P&L%':>7}  Phase")
    print(f"  {'-'*7} {'-'*11} {'-'*8} {'-'*4} {'-'*8} {'-'*8} {'-'*7}  -----")

    exit_warnings = []
    for ticker, pos in positions.items():
        current_price = _close_from_price_data(ticker, price_data)
        pnl   = strat.pnl_pct(pos, current_price)
        stop  = strat.trail_stop_price(pos)
        hdays = pos.get("hold_days", 0)
        phase = f"Stop-loss ({strat.STOP_LOSS_PCT*100:.0f}%)" if hdays <= strat.PHASE1_DAYS else f"Trail ({strat.TRAIL_STOP_PCT*100:.0f}%)"

        pnl_str   = f"{pnl:+.1f}%" if pnl is not None else "—"
        price_str = f"${current_price:.2f}" if current_price else "—"
        stop_str  = f"${stop:.2f}" if stop else "—"

        do_exit, reason = strat.should_exit(pos, current_price)
        if do_exit:
            exit_warnings.append((ticker, reason))

        print(f"  {ticker:<7} {pos['entry_date']:<11} ${pos['entry_price']:>7.2f} "
              f"{hdays:>4} {price_str:>8} {stop_str:>8} {pnl_str:>7}  {phase}")

    print(f"{'─' * width}")
    if exit_warnings:
        for ticker, reason in exit_warnings:
            print(f"  ⚠  EXIT: {ticker} — {reason}")
    else:
        print("  ✓  No exit signals today")


def _classify(score: float) -> str:
    if score >= 60:
        return "HOT"
    if score >= 40:
        return "WARM"
    return "COLD"


def _close_from_price_data(ticker: str, price_data: dict) -> float:
    df = price_data.get(ticker)
    if df is None or df.empty:
        return 0.0
    try:
        close = df["Close"]
        if hasattr(close, "iloc"):
            val = close.iloc[-1]
            return float(val.item() if hasattr(val, "item") else val)
    except Exception:
        pass
    return 0.0


def save_json_report(results: list[dict], date: str) -> str:
    path = os.path.join(config.REPORT_DIR, f"{date}.json")
    with open(path, "w") as f:
        json.dump({"date": date, "results": results}, f, indent=2, default=str)
    return path


def _contribution(breakdown: dict, key: str) -> float | None:
    entry = breakdown.get(key)
    if entry and isinstance(entry, dict):
        return entry.get("contribution")
    return None
