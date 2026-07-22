# Quality Value Investing System

**Strategy:** Buy quality undervalued S&P 500 stocks, hold until fairly valued, rebalance quarterly

**Backtest Results (2021-2026):**
- Quality Value: **+120.59%**
- QQQ Buy-and-Hold: +104.66%
- **Beat QQQ by 15.93%**
- Win Rate: 100%

---

## 📋 How It Works

### Monthly Monitor (Every Month)
**When:** Last Friday of each month  
**Time:** ~2-3 minutes  
**Action:** Defensive - Check if current holdings still pass quality filters

**The script checks each stock for:**
- ✅ ROE > 10% (still profitable)
- ✅ Revenue Growth > 0% (not declining)
- ✅ Debt/Equity < 100% (strong balance sheet)
- ✅ Free Cash Flow > $0 (generating cash)
- ✅ P/E still undervalued vs sector

**Recommendations:**
- **HOLD:** Stock still passes all filters → do nothing
- **SELL:** Stock failed quality filters → sell immediately
- **REPLACE:** If you sell, get recommendations for replacement buys

### Quarterly Rebalance (Every 3 Months)
**When:** End of Mar, Jun, Sep, Dec  
**Time:** ~5-10 minutes  
**Action:** Offensive - Optimize entire portfolio

**The script:**
1. Screens all 503 S&P 500 stocks
2. Finds top 10 quality undervalued stocks
3. Compares to your current holdings
4. Shows sells (no longer in top 10) and buys (new opportunities)

**This is when you make major portfolio changes.**

---

## 🚀 Setup Instructions

### Step 1: Initialize Your Portfolio

Run this once to get your first 10 stocks:

```bash
cd /tmp
python3 initialize_portfolio.py
```

This will:
- Screen all S&P 500 stocks (~5 minutes)
- Show top 10 quality undervalued picks
- Create `quality_value_positions.json` to track holdings

### Step 2: Buy the Stocks

**Important:** Use equal dollar amounts for each stock

Example with $10,000 allocated (10% of $100k account):
- $10,000 ÷ 10 stocks = $1,000 per stock
- If GOOG is $300/share → buy 3 shares
- If MU is $100/share → buy 10 shares

### Step 3: Monthly Monitoring

**Set up monthly reminder** (last Friday of each month):

```bash
# Add to your calendar or cron
# Last Friday of each month at 5pm
cd /tmp && python3 quality_value_monthly_monitor.py
```

**What you'll see:**

**Non-quarter months (Jan, Feb, Apr, May, Jul, Aug, Oct, Nov):**
```
📊 MONTHLY MONITOR - January 2026

🔍 Checking GOOG...
   ✅ HOLD - Still quality + undervalued (P/E 12.3, 65% discount)

🔍 Checking MU...
   ❌ SELL - Failed quality: ROE too low (7.2% < 10%)

📥 BUY CMCSA - Communication Services - P/E 5.4 (70% discount)
```

**Quarter-end months (Mar, Jun, Sep, Dec):**
```
🔄 QUARTERLY REBALANCE - March 2026

🔍 Screening 503 S&P 500 stocks...
✅ Found 42 quality undervalued stocks

🎯 TOP 10 RECOMMENDATIONS
1. CMCSA - Communication Services - P/E 5.4 (70% discount)
2. MRK   - Healthcare          - P/E 11.5 (61% discount)
...

📋 TRADING RECOMMENDATIONS
📤 SELL (3 stocks):
   ❌ GOOG - Not in top 10 anymore
   ❌ MU   - Not in top 10 anymore
   ❌ WDC  - Not in top 10 anymore

📥 BUY (3 stocks):
   ✅ CMCSA - Communication Services - P/E 5.4 (70% discount)
   ✅ MRK   - Healthcare          - P/E 11.5 (61% discount)
   ✅ TGT   - Consumer Defensive  - P/E 11.0 (59% discount)
```

---

## 📊 Position Tracking

Your holdings are tracked in:
```
/Users/Jay.Park/Downloads/stock_strategies/quality_value_positions.json
```

**Format:**
```json
{
  "GOOG": {
    "entry_date": "2026-04-14",
    "entry_price": 300.50,
    "sector": "Communication Services"
  },
  "MU": {
    "entry_date": "2026-04-14",
    "entry_price": 100.25,
    "sector": "Technology"
  }
}
```

The script automatically updates this file when you accept recommendations.

---

## 🎯 Decision Rules

### When to SELL (during monthly monitor)
1. ❌ **Quality deteriorated** → Sell immediately, buy replacement
   - ROE dropped below 10%
   - Revenue declining
   - Debt spiked above 100% D/E
   - Negative free cash flow

2. ⚠️ **No longer undervalued** → Monitor closely, sell at quarter-end
   - P/E discount < 30%
   - Stock recovered to fair value
   - This is a GOOD thing (you made money!)

### When to REBALANCE (quarterly)
1. Compare current holdings vs top 10 recommendations
2. Sell anything not in top 10
3. Buy new opportunities that entered top 10
4. This captures value rotation across sectors

---

## 💡 Best Practices

### Position Sizing
- **Allocate 10% of account** (conservative)
- **Equal dollar amounts** per stock ($1,000 each if $10k total)
- Rebalance back to equal weights quarterly

### Tax Optimization
- Hold stocks **> 1 year** for long-term capital gains
- Our backtest held positions 6-24 months on average
- Quarterly rebalancing is tax-efficient

### Monitoring Schedule
```
Monthly:    Last Friday of each month
Quarterly:  Last Friday of Mar, Jun, Sep, Dec
Time:       2-3 min monthly, 5-10 min quarterly
```

### When to Ignore Recommendations
- If a stock is 1 day away from 1-year holding period (wait for long-term gains)
- During extreme market volatility (wait a few days)
- If commission costs > expected benefit

---

## 📈 What to Expect

### Typical Holding Period
- **Short:** 3-6 months (rapid recovery)
- **Medium:** 6-12 months (most common)
- **Long:** 12-24 months (deep value)

### Example Wins from Backtest
1. **WDC** (Western Digital): +355% in 2 years
2. **MU** (Micron): +223% in 2 years
3. **LRCX** (Lam Research): +124% in 2 years
4. **GOOG** (Google): +126% in 2 years

### Annual Activity
- **4 quarterly rebalances** (major changes)
- **~8-12 trades per year** (vs 250 for momentum!)
- **Very low maintenance**

---

## 🔧 Troubleshooting

### "No current positions" on first run
→ Run `initialize_portfolio.py` first

### "Error fetching S&P 500 list"
→ Check internet connection, Wikipedia might be blocking requests

### "Only found X stocks, need 10"
→ Market might be overvalued, consider reducing NUM_STOCKS parameter

### Script takes too long
→ Normal! Full screening takes 4-5 minutes. Monthly checks are faster (2-3 min).

---

## 📞 Support

Questions? Check:
1. This README
2. Backtest results: `/tmp/sp500_backtest.log`
3. Your positions: `quality_value_positions.json`

---

## 🎓 Strategy Summary

**What:** Buy quality companies trading below sector P/E  
**How:** Screen S&P 500 monthly, rebalance quarterly  
**Why:** Value eventually gets recognized, quality ensures it's real  
**When:** Set and forget, check monthly, trade quarterly  
**Risk:** Very low (blue chip S&P 500 stocks, diversified across 10)  

**This is NOT momentum trading** - it's patient, disciplined value investing with a quality twist.
