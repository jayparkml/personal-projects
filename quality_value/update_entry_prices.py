#!/usr/bin/env python3
"""
Quick script to update entry prices in positions file
Run this after you've bought your stocks
"""

import json
import yfinance as yf

POSITIONS_FILE = '/Users/Jay.Park/Documents/personal-projects/quality_value/quality_value_positions.json'

# Load positions
with open(POSITIONS_FILE, 'r') as f:
    positions = json.load(f)

print("="*80)
print("UPDATE ENTRY PRICES")
print("="*80)
print("\nFetching current prices for your stocks...\n")

# Get current prices
for ticker in positions.keys():
    try:
        stock = yf.Ticker(ticker)
        current_price = stock.info.get('currentPrice', stock.info.get('regularMarketPrice', 0))
        
        print(f"{ticker:6s} - Current price: ${current_price:.2f}")
        print(f"         (You bought ~$500 worth = {500/current_price:.1f} shares)")
        
        # Ask user for their actual entry price
        entry = input(f"         Enter YOUR purchase price (or press Enter to use ${current_price:.2f}): ").strip()
        
        if entry:
            positions[ticker]['entry_price'] = float(entry)
        else:
            positions[ticker]['entry_price'] = current_price
            
        print()
        
    except Exception as e:
        print(f"❌ Error fetching {ticker}: {e}\n")

# Save updated positions
with open(POSITIONS_FILE, 'w') as f:
    json.dump(positions, f, indent=2)

print("="*80)
print("✅ Entry prices updated!")
print("="*80)
print(f"\nUpdated file: {POSITIONS_FILE}")

# Show summary
print("\n📊 PORTFOLIO SUMMARY:")
print("-" * 80)
total_invested = 0
for ticker, pos in positions.items():
    if pos['entry_price']:
        shares = 500 / pos['entry_price']
        print(f"{ticker:6s} - {shares:6.2f} shares @ ${pos['entry_price']:7.2f} = ${shares * pos['entry_price']:7.2f}")
        total_invested += shares * pos['entry_price']

print("-" * 80)
print(f"Total Invested: ${total_invested:.2f}")
print("="*80)
