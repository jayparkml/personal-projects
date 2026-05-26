# Spike Scanner

Daily U.S. stock scanner that detects momentum spikes using 7 signals — SEC filings, insider buying, volume anomalies, Reddit sentiment, short squeeze setups, options flow, and technicals. Scores ~2,500 tickers each evening and manages a 3-slot paper portfolio.

## How it works

Each ticker gets a composite heat score (0–100). Stocks above 60 (HOT) with 2+ active signals are trade candidates.

| Signal | Weight | Source |
|--------|--------|--------|
| SEC filings (8-K, 13D, Form 4) | 25 pts | EDGAR |
| Insider buying clusters | 20 pts | EDGAR Form 4 |
| Volume anomaly + BB compression | 20 pts | yfinance |
| Reddit mention velocity | 15 pts | Reddit JSON API |
| Short squeeze setup | 10 pts | yfinance |
| Options flow (call/put ratio) | 5 pts | yfinance |
| Technicals (RSI, MACD, MA50) | 5 pts | yfinance |

**No API keys required** — all sources are free and public.

## Usage

```bash
# Daily run (manual)
python3 runner.py

# Double-click launcher (macOS)
open run_scanner.command  # right-click → Open first time to bypass Gatekeeper

# Backtest
python3 backtest.py
```

Cron (7pm ET, weekdays):
```
0 19 * * 1-5  cd ~/Documents/personal-projects/spike_scanner && python3 runner.py >> data/scanner.log 2>&1
```

## Portfolio rules

- **Entry:** HOT score (60+) + 2+ signals + open slot (max 3 positions)
- **Position size:** $1,000
- **Exit — Phase 1 (days 0–10):** 8% hard stop loss
- **Exit — Phase 2 (days 10+):** 20% trailing stop
- **Force exit:** 60 trading days
- **Rotation:** Evict lowest scorer if a new HOT beats it by 5+ points

## Setup

```bash
pip install -r requirements.txt
python3 runner.py
```

Generated output goes to `data/` (gitignored): positions, scores, trade log, daily reports.
