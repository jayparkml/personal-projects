#!/usr/bin/env python3
"""
Daily spike scanner orchestrator.

Run manually:   python3 runner.py
Schedule (cron): 0 19 * * 1-5  cd ~/Documents/personal-projects/spike_scanner && python3 runner.py >> data/scanner.log 2>&1

Pipeline:
  1. Load/rebuild stock universe
  2. Batch-fetch price data (yfinance) + short interest metadata
  3. Compute momentum signals (parallel, CPU-only)
  4. Scan EDGAR globally for recent 8-K and 13D filings
  5. Scan Reddit for mention velocity
  6. Compute composite heat scores per ticker (parallel)
  7. Compare to yesterday's scores (deltas)
  8. Generate console + CSV + JSON reports
  9. Save state for tomorrow
"""
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import yfinance as yf

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cache
import config
import report
import scoring
import strategy
import universe as univ
from signals import momentum, options_flow, sec_filings, sentiment, short_interest, technicals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE, mode="a"),
    ],
)
logger = logging.getLogger(__name__)

# yfinance logs noisy false "possibly delisted" errors for rate-limited tickers
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def main():
    start_time = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    cache.ensure_dirs()

    logger.info("=" * 60)
    logger.info(f"SPIKE SCANNER — {today}")
    logger.info("=" * 60)

    # ── 1. Universe ───────────────────────────────────────────────────────────
    df_universe = univ.load_universe()
    tickers = df_universe["ticker"].tolist()
    logger.info(f"Universe: {len(tickers)} tickers")

    # ── 2. Price data (batch yfinance) ────────────────────────────────────────
    logger.info("Fetching price history...")
    price_data, yf_info = _fetch_all_price_data(tickers)
    logger.info(f"Price data: {len(price_data)} tickers fetched")

    # ── 3. EDGAR global scans (one request each, no per-ticker API calls) ────────
    logger.info("Scanning EDGAR for recent 8-K filings...")
    recent_8k = sec_filings.fetch_recent_filings("8-K", lookback_days=config.EDGAR_LOOKBACK_DAYS)
    recent_8k_tickers = {f["ticker"] for f in recent_8k}
    # Build item map: {ticker: [item_numbers]} for 8-K item scoring
    recent_8k_items: dict[str, list] = {}
    for f in recent_8k:
        t = f["ticker"]
        recent_8k_items.setdefault(t, [])
        recent_8k_items[t].extend(f.get("items", []))
    logger.info(f"  8-K filings: {len(recent_8k)} filings, {len(recent_8k_tickers)} unique tickers")

    logger.info("Scanning EDGAR for recent Form 4 insider filings...")
    recent_form4 = sec_filings.fetch_recent_filings("4", lookback_days=7)
    from collections import Counter
    form4_counts: dict[str, int] = dict(Counter(f["ticker"] for f in recent_form4))
    logger.info(f"  Form 4 filings: {len(recent_form4)} filings, {len(form4_counts)} unique tickers")

    logger.info("Scanning EDGAR for 13D activist filings...")
    recent_13d = sec_filings.fetch_recent_filings("SC 13D", lookback_days=30)
    activist_tickers = {f["ticker"] for f in recent_13d}
    logger.info(f"  13D filings: {len(recent_13d)} filings")

    # ── 4. Reddit sentiment ───────────────────────────────────────────────────
    logger.info("Fetching Reddit mention data...")
    today_mentions = sentiment.fetch_all_subreddit_mentions()
    logger.info(f"  Reddit: {len(today_mentions)} tickers mentioned")
    cache.append_sentiment_day(today, today_mentions)

    # ── 5. Load prior scores + open positions ────────────────────────────────
    state = cache.load_state()
    prior_scores: dict[str, float] = state.get("scores", {})
    positions = cache.load_positions()

    # ── 6. Compute composite scores (parallel) ────────────────────────────────
    logger.info(f"Scoring {len(tickers)} tickers (max_workers={config.MAX_WORKERS})...")
    results = []

    def score_ticker(ticker: str) -> dict | None:
        df = price_data.get(ticker)
        info = yf_info.get(ticker, {})
        if df is None or df.empty:
            return None
        try:
            signals = _compute_signals(
                ticker, df, info,
                recent_8k_tickers, recent_8k_items,
                form4_counts, activist_tickers,
                today_mentions,
            )
            heat, breakdown = scoring.compute_heat_score(signals)
            delta_info = scoring.compute_delta(ticker, heat, prior_scores)
            return {
                "ticker":         ticker,
                "score":          heat,
                "class":          scoring.classify_heat(heat),
                "top_signal":     scoring.top_signal_label(breakdown),
                "breakdown":      breakdown,
                **delta_info,
            }
        except Exception as e:
            logger.debug(f"Score failed for {ticker}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = {executor.submit(score_ticker, t): t for t in tickers}
        done = 0
        for future in as_completed(futures):
            result = future.result()
            if result and result["score"] > 0:
                results.append(result)
            done += 1
            if done % 200 == 0:
                logger.info(f"  Scored {done}/{len(tickers)}...")

    # ── 7. Sort + trim ────────────────────────────────────────────────────────
    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = results[:config.TOP_N_REPORT]

    # Build score lookup for strategy decisions
    score_by_ticker = {r["ticker"]: (r["score"], r["breakdown"]) for r in results}

    # ── 8. Apply entry / hold / exit rules ───────────────────────────────────
    exits, entries = [], []

    # Update held positions and check exits
    for ticker, pos in list(positions.items()):
        score, breakdown = score_by_ticker.get(ticker, (0.0, {}))
        current_price = _get_close_price(ticker, price_data)
        updated = strategy.update_hold(pos, score, current_price)
        updated["pnl_pct_today"] = strategy.pnl_pct(updated, current_price)
        positions[ticker] = updated
        do_exit, exit_reason = strategy.should_exit(positions[ticker], current_price)
        if do_exit:
            exits.append((ticker, exit_reason))
            logger.info(f"EXIT signal: {ticker} ({exit_reason}, day {updated.get('hold_days', 0)})")

    for ticker, exit_reason in exits:
        pos = positions[ticker]
        exit_price = _get_close_price(ticker, price_data)
        exit_score = score_by_ticker.get(ticker, (0.0, {}))[0]
        entry_date  = pos.get("entry_date", "")
        entry_price = pos.get("entry_price")
        hold_days   = pos.get("hold_days")
        pnl_pct = strategy.pnl_pct(pos, exit_price)
        cache.log_trade(
            ticker=ticker, action="SELL", date=today, price=exit_price,
            score=exit_score, reason=exit_reason,
            entry_date=entry_date, entry_price=entry_price,
            hold_days=hold_days, pnl_pct=pnl_pct,
        )
        del positions[ticker]

    # Evaluate HOT tickers for new entries
    for r in top_results:
        ticker, score, breakdown = r["ticker"], r["score"], r["breakdown"]
        if strategy.should_enter(ticker, score, breakdown, positions):
            price = _get_close_price(ticker, price_data)
            positions[ticker] = strategy.open_position(ticker, today, price, score)
            entries.append(ticker)
            logger.info(f"ENTRY: {ticker} score={score:.1f}")
            cache.log_trade(ticker=ticker, action="BUY", date=today, price=price,
                            score=score, reason="HOT_ENTRY")
        elif len(positions) >= strategy.MAX_POSITIONS:
            evict = strategy.check_rotation(ticker, score, breakdown, positions)
            if evict:
                evict_pos = positions[evict]
                evict_price = _get_close_price(evict, price_data)
                evict_score = score_by_ticker.get(evict, (0.0, {}))[0]
                evict_hold = (
                    (datetime.strptime(today, "%Y-%m-%d") -
                     datetime.strptime(evict_pos.get("entry_date", today), "%Y-%m-%d")).days
                )
                cache.log_trade(
                    ticker=evict, action="SELL", date=today, price=evict_price,
                    score=evict_score, reason="ROTATION_OUT",
                    entry_date=evict_pos.get("entry_date", ""),
                    entry_price=evict_pos.get("entry_price"),
                    hold_days=evict_hold,
                    pnl_pct=strategy.pnl_pct(evict_pos, evict_price),
                )
                del positions[evict]
                price = _get_close_price(ticker, price_data)
                positions[ticker] = strategy.open_position(ticker, today, price, score)
                entries.append(ticker)
                logger.info(f"ROTATION: out={evict}, in={ticker} score={score:.1f}")
                cache.log_trade(ticker=ticker, action="BUY", date=today, price=price,
                                score=score, reason="ROTATION_IN")

    cache.save_positions(positions)

    # ── 9. Reports ────────────────────────────────────────────────────────────
    runtime = time.time() - start_time
    report.print_daily_report(top_results, today, runtime, len(tickers))
    report.print_positions_section(positions, score_by_ticker, price_data, today)
    csv_path  = report.save_csv_report(top_results, today)
    json_path = report.save_json_report(top_results, today)
    logger.info(f"Reports saved: {csv_path}")
    logger.info(f"              {json_path}")

    # ── 10. Persist state ─────────────────────────────────────────────────────
    state["scores"] = {r["ticker"]: r["score"] for r in results}
    cache.save_state(state)
    logger.info(f"State saved. Total runtime: {int(runtime // 60)}m {int(runtime % 60)}s")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_close_price(ticker: str, price_data: dict) -> float:
    """Return today's close price for a ticker, or 0 if unavailable."""
    df = price_data.get(ticker)
    if df is None or df.empty:
        return 0.0
    try:
        close = df["Close"]
        if hasattr(close, "iloc"):
            val = close.iloc[-1]
            if hasattr(val, "item"):
                return float(val.item())
            return float(val)
    except Exception:
        pass
    return 0.0


def _fetch_all_price_data(tickers: list[str]) -> tuple[dict, dict]:
    """
    Batch-download 1yr daily OHLCV for all tickers.
    Also fetches per-ticker info (for short interest) in smaller batches.
    Returns (price_data_dict, info_dict).
    """
    price_data: dict = {}
    yf_info: dict = {}

    batches = [tickers[i:i + config.YFINANCE_BATCH_SIZE]
               for i in range(0, len(tickers), config.YFINANCE_BATCH_SIZE)]

    for i, batch in enumerate(batches):
        # Check cache first
        uncached = []
        for t in batch:
            cached = cache.load_price_data(t)
            if cached is not None:
                price_data[t] = cached
            else:
                uncached.append(t)

        if uncached:
            # threads=False prevents yfinance from spawning internal threads that
            # race on its SQLite timezone cache and trigger rate-limit errors
            try:
                raw = yf.download(
                    uncached,
                    period=config.YFINANCE_PERIOD,
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                )
                for t in uncached:
                    try:
                        if len(uncached) == 1:
                            df = raw.copy()
                        else:
                            df = raw[t].copy() if t in raw.columns.get_level_values(0) else None
                        if df is not None and not df.empty:
                            df = df.dropna(how="all")
                            price_data[t] = df
                            cache.save_price_data(t, df)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Batch download failed (batch {i}): {e}")

            # Retry individual tickers that the batch missed (rate-limiting false negatives)
            still_missing = [t for t in uncached if t not in price_data]
            if still_missing:
                logger.debug(f"Retrying {len(still_missing)} tickers individually...")
                for t in still_missing:
                    try:
                        df = yf.download(
                            t,
                            period=config.YFINANCE_PERIOD,
                            interval="1d",
                            auto_adjust=True,
                            progress=False,
                            threads=False,
                        )
                        if df is not None and not df.empty:
                            df = df.dropna(how="all")
                            price_data[t] = df
                            cache.save_price_data(t, df)
                    except Exception:
                        pass
                    time.sleep(0.3)

        # Fetch info for short interest (separate call, smaller batch)
        for t in batch:
            try:
                info = yf.Ticker(t).info
                yf_info[t] = {
                    "shortPercentOfFloat": info.get("shortPercentOfFloat"),
                    "shortRatio":          info.get("shortRatio"),
                }
            except Exception:
                yf_info[t] = {}

        if i < len(batches) - 1:
            time.sleep(config.YFINANCE_SLEEP)

    return price_data, yf_info


def _compute_signals(
    ticker: str,
    df,
    info: dict,
    recent_8k_tickers: set[str],
    recent_8k_items: dict[str, list],
    form4_counts: dict[str, int],
    activist_tickers: set[str],
    today_mentions: dict[str, int],
) -> dict:
    """Compute all signal sub-scores for a single ticker."""
    # Momentum: volume anomaly + BB compression (combined)
    mom_score, mom_detail = momentum.compute_momentum_score(ticker, df)

    # Short interest
    si_score, si_detail = short_interest.compute_short_squeeze_score(ticker, info)

    # Sentiment velocity
    sent_score, sent_detail = sentiment.compute_sentiment_score(ticker, today_mentions)

    # SEC filings — all data pre-fetched globally, no per-ticker EDGAR calls
    sec_score, sec_detail = sec_filings.compute_sec_score(
        ticker,
        recent_8k_tickers=recent_8k_tickers,
        recent_8k_items=recent_8k_items,
        form4_counts=form4_counts,
        activist_tickers=activist_tickers,
    )
    insider_score = 100.0 if sec_detail.get("insider_cluster") else (
        25.0 if sec_detail.get("insider_count", 0) >= 1 else 0.0
    )

    # Technicals: pure price computation, always fast
    tech_score, tech_detail = technicals.compute_technicals_score(ticker, df)

    # Options flow: API call — gate to tickers already showing meaningful signals
    other_strength = mom_score + si_score + sent_score + tech_score
    if other_strength >= 20:
        opt_score, opt_detail = options_flow.compute_options_flow_score(ticker)
    else:
        opt_score, opt_detail = 0.0, {}

    return {
        "sec_filings":        (sec_score, sec_detail),
        "insider_buying":     (insider_score, {"insider_count": sec_detail.get("insider_count", 0)}),
        "volume_anomaly":     (mom_score, mom_detail),
        "sentiment_velocity": (sent_score, sent_detail),
        "short_squeeze":      (si_score, si_detail),
        "technicals":         (tech_score, tech_detail),
        "options_flow":       (opt_score, opt_detail),
    }


if __name__ == "__main__":
    main()
