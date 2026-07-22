#!/usr/bin/env python3
"""
Initialize Quality Value Portfolio

Use this to set up your first 10-stock portfolio.
This will run a full screening and let you save the top 10 picks.
"""

import json
import os
from datetime import datetime

# Run the monthly monitor in quarterly mode to get initial picks
POSITIONS_FILE = '/Users/Jay.Park/Documents/personal-projects/quality_value/quality_value_positions.json'

print("="*100)
print("INITIALIZE QUALITY VALUE PORTFOLIO")
print("="*100)
print("\nThis will:")
print("1. Screen all S&P 500 stocks")
print("2. Find top 10 quality undervalued stocks")
print("3. Create initial positions file")
print("\n⏱️  Takes ~4-5 minutes")
print("\nStarting screening...")

# Import and run the quarterly rebalance
import sys
sys.path.insert(0, '/Users/Jay.Park/Documents/personal-projects/quality_value')

from quality_value_monthly_monitor import get_sp500_tickers, screen_sp500_stocks, save_positions

# Get S&P 500 list
sp500_tickers = get_sp500_tickers()
if not sp500_tickers:
    print("❌ Failed to fetch S&P 500 list")
    exit(1)

# Screen all stocks
qualified = screen_sp500_stocks(sp500_tickers, verbose=True)

if len(qualified) < 10:
    print(f"\n❌ Only found {len(qualified)} stocks, need at least 10")
    exit(1)

# Get top 10
top_picks = qualified.head(10)

print("\n" + "="*100)
print("🎯 TOP 10 QUALITY VALUE PICKS")
print("="*100)

for i, (idx, row) in enumerate(top_picks.iterrows(), 1):
    print(f"{i:2d}. {row['ticker']:6s} - {row['sector'][:20]:20s} - P/E {row['pe']:5.1f} ({row['discount']*100:.0f}% discount)")
    print(f"      ROE: {row['roe']*100:.1f}%, Rev Growth: {row['rev_growth']*100:.1f}%, D/E: {row['debt_to_equity']:.0f}%")

# Create positions file
positions = {}
for idx, row in top_picks.iterrows():
    positions[row['ticker']] = {
        'entry_date': datetime.now().strftime('%Y-%m-%d'),
        'entry_price': None,  # User will fill in after buying
        'sector': row['sector']
    }

# Save
save_positions(positions)

print("\n" + "="*100)
print("✅ PORTFOLIO INITIALIZED")
print("="*100)
print(f"\nPositions saved to: {POSITIONS_FILE}")
print(f"Holdings: {', '.join(positions.keys())}")

print("\n📋 NEXT STEPS:")
print("1. Review the 10 stocks above")
print("2. Buy equal dollar amounts of each (e.g., $1,000 per stock for $10,000 total)")
print("3. Update entry prices in positions file (optional, for tracking)")
print("4. Run monthly monitor on the last Friday of each month")

print("\n💡 TIP: Allocate 10% of your account to this strategy")
print("   Example: $100,000 account → $10,000 to quality value → $1,000 per stock")
