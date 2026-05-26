# Dip Ladder

Automated leveraged ETF accumulator based on the Korean 웅덩이 매매법 (puddle trading) strategy. Buys in staged tranches when price drops below key moving averages, spreading entry risk across multiple days.

## Strategy

Three ETFs, $50K total allocation:

| Ticker | Name | Allocation |
|--------|------|-----------|
| QLD | Invesco Nasdaq-100 2x | $25,000 |
| SSO | ProShares S&P 500 2x | $15,000 |
| USD | Direxion Semiconductor 2x | $10,000 |

Four buy triggers per ETF, each deploying a tranche over multiple days:

| Level | Trigger | Cash deployed | Days |
|-------|---------|---------------|------|
| 1 | Price ≤ 20-day MA | 5% of pool | 2 |
| 2 | Price ≤ 60-day MA | 50% of remaining | 3 |
| 3 | Price ≤ 120-day MA | 50% of remaining | 5 |
| 4 | Price ≤ 120-day MA + RSI < 35 | 100% of remaining | 5 |

## Usage

```bash
# Daily check (run any time after market open)
python3 main.py

# Double-click launcher (macOS)
open run.command  # right-click → Open first time to bypass Gatekeeper

# Backtest (2020–present)
python3 backtest.py
python3 backtest.py --start 2022-01-01 --end 2023-12-31
```

## Output

Daily report logged to `logs/YYYY-MM-DD.txt` (gitignored). Shows current price vs MAs, RSI, active buy levels, and today's action.

Backtest results go to `backtest_results/` (gitignored): `buy_events.csv`, `portfolio_daily.csv`, `summary.txt`.

## Setup

```bash
pip install yfinance pandas
python3 main.py
```
