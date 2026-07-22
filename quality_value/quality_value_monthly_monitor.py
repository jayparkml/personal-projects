#!/usr/bin/env python3
"""
QUALITY VALUE MONTHLY MONITOR

Monthly: Check if current holdings still pass quality filters
         Recommend sells + replacement buys if stocks deteriorate

Quarterly: Full rebalancing (compare current vs top 10 recommendations)

Positions tracked in: quality_value_positions.json
"""

import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime
import time
import ssl
import requests
from io import StringIO
import sys
import logging

# Fix SSL
ssl._create_default_https_context = ssl._create_unverified_context

# PARAMETERS
BASE_DIR = '/Users/Jay.Park/Documents/personal-projects/quality_value'
POSITIONS_FILE = '/Users/Jay.Park/Documents/personal-projects/quality_value/quality_value_positions.json'
PERFORMANCE_CSV = '/Users/Jay.Park/Documents/personal-projects/quality_value/performance_history.csv'
LOGS_DIR = '/Users/Jay.Park/Documents/personal-projects/quality_value/logs'
NUM_STOCKS = 10
PE_DISCOUNT_THRESHOLD = 0.30  # 30% below sector

# Quality Filters
MIN_ROE = 0.10
MAX_DEBT_TO_EQUITY = 100
MIN_REVENUE_GROWTH = 0.0

# Sector average P/E
SECTOR_PE = {
    'Technology': 35,
    'Communication Services': 25,
    'Consumer Cyclical': 25,
    'Healthcare': 30,
    'Financial Services': 12,
    'Industrials': 22,
    'Consumer Defensive': 22,
    'Energy': 15,
    'Utilities': 18,
    'Real Estate': 35,
    'Basic Materials': 18
}

def is_quarter_end():
    """Check if current month is quarter end (Mar, Jun, Sep, Dec)"""
    month = datetime.now().month
    return month in [3, 6, 9, 12]

def load_positions():
    """Load current positions from JSON file. Returns (open_positions, closed_positions)."""
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        if 'open' in data:
            return data.get('open', {}), data.get('closed', {})
        else:
            # Backward compat: old flat format had only open positions
            return data, {}
    return {}, {}

def save_positions(open_positions, closed_positions=None):
    """Save positions to JSON file."""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    data = {'open': open_positions, 'closed': closed_positions or {}}
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_current_price(ticker):
    """Fetch latest market price for a ticker."""
    try:
        info = yf.Ticker(ticker).info
        return info.get('currentPrice', info.get('regularMarketPrice'))
    except Exception:
        return None

def get_sp500_tickers():
    """Fetch S&P 500 ticker list"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        response = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers)
        sp500_table = pd.read_html(StringIO(response.text))
        sp500_df = sp500_table[0]
        return sp500_df['Symbol'].str.replace('.', '-').tolist()
    except Exception as e:
        print(f"❌ Error fetching S&P 500 list: {e}")
        return []

def check_quality_filters(ticker):
    """
    Check if a stock passes quality filters
    Returns: (passes: bool, metrics: dict, reason: str)
    """
    try:
        stock = yf.Ticker(ticker)

        # Get data
        info = stock.info
        sector = info.get('sector', 'Unknown')

        income_stmt = stock.income_stmt
        balance_sheet = stock.balance_sheet
        cash_flow = stock.cashflow

        if income_stmt is None or income_stmt.empty:
            return False, {}, "No income statement data"

        # Calculate metrics
        metrics = {}

        # 1. ROE
        if balance_sheet is not None and not balance_sheet.empty:
            equity_items = [idx for idx in balance_sheet.index if 'Stockholder' in idx or 'Equity' in idx]
            if equity_items:
                equity = balance_sheet.loc[equity_items[0]].iloc[0]
            else:
                return False, {}, "No equity data"
        else:
            return False, {}, "No balance sheet"

        income_items = [idx for idx in income_stmt.index if 'Net Income' in idx]
        if income_items:
            net_income = income_stmt.loc[income_items[0]].iloc[0]
        else:
            return False, {}, "No net income data"

        if equity and net_income and equity > 0:
            roe = net_income / equity
            metrics['roe'] = roe
            if roe < MIN_ROE:
                return False, metrics, f"ROE too low ({roe:.1%} < {MIN_ROE:.0%})"
        else:
            return False, metrics, "Invalid ROE calculation"

        # 2. Revenue Growth
        if 'Total Revenue' in income_stmt.index:
            revenues = income_stmt.loc['Total Revenue']
            if len(revenues) >= 2:
                latest_rev = revenues.iloc[0]
                prior_rev = revenues.iloc[1]
                rev_growth = (latest_rev - prior_rev) / prior_rev if prior_rev > 0 else 0
                metrics['rev_growth'] = rev_growth

                if rev_growth < MIN_REVENUE_GROWTH:
                    return False, metrics, f"Declining revenue ({rev_growth:.1%})"
            else:
                return False, metrics, "Not enough revenue history"
        else:
            return False, metrics, "No revenue data"

        # 3. Debt/Equity
        debt_items = [idx for idx in balance_sheet.index if 'Total Debt' in idx]
        if debt_items and equity:
            total_debt = balance_sheet.loc[debt_items[0]].iloc[0]
            debt_to_equity = (total_debt / equity) * 100
            metrics['debt_to_equity'] = debt_to_equity

            if debt_to_equity > MAX_DEBT_TO_EQUITY:
                return False, metrics, f"Too much debt ({debt_to_equity:.0f}% > {MAX_DEBT_TO_EQUITY}%)"

        # 4. Free Cash Flow
        if cash_flow is not None and not cash_flow.empty:
            fcf_items = [idx for idx in cash_flow.index if 'Free Cash Flow' in idx]
            if fcf_items:
                fcf = cash_flow.loc[fcf_items[0]].iloc[0]
                metrics['fcf'] = fcf

                if fcf <= 0:
                    return False, metrics, f"Negative FCF (${fcf/1e9:.1f}B)"
            else:
                return False, metrics, "No FCF data"
        else:
            return False, metrics, "No cash flow data"

        # All filters passed!
        return True, metrics, "PASS"

    except Exception as e:
        return False, {}, f"Error: {str(e)}"

def check_pe_undervalued(ticker):
    """
    Check if stock is still undervalued (P/E < sector avg - 30%)
    Returns: (undervalued: bool, pe: float, sector_pe: float, discount: float)
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Get current price
        price = info.get('currentPrice', info.get('regularMarketPrice', None))
        if price is None:
            return False, None, None, None

        # Get sector
        sector = info.get('sector', 'Unknown')
        sector_pe = SECTOR_PE.get(sector, 25)

        # Get EPS (trailing 12 months)
        eps = info.get('trailingEps', None)

        if eps is None or eps <= 0:
            return False, None, sector_pe, None

        pe = price / eps

        # Sanity check
        if pe < 1 or pe > 200:
            return False, pe, sector_pe, None

        discount = (sector_pe - pe) / sector_pe
        undervalued = discount >= PE_DISCOUNT_THRESHOLD

        return undervalued, pe, sector_pe, discount

    except Exception as e:
        return False, None, None, None

def screen_sp500_stocks(sp500_tickers, verbose=False):
    """
    Screen all S&P 500 stocks for quality + value
    Returns: DataFrame of qualified stocks sorted by discount
    """
    print(f"\n🔍 Screening {len(sp500_tickers)} S&P 500 stocks...")
    print("⏱️  This will take ~4-5 minutes...\n")

    candidates = []
    start_time = time.time()

    for i, ticker in enumerate(sp500_tickers):
        if verbose and (i+1) % 50 == 0:
            elapsed = (time.time() - start_time) / 60
            eta = (elapsed / (i+1)) * (len(sp500_tickers) - i - 1)
            print(f"[{i+1}/{len(sp500_tickers)}] {ticker:6s} | Elapsed: {elapsed:.1f}min | ETA: {eta:.1f}min")

        try:
            # Check quality filters
            passes_quality, metrics, reason = check_quality_filters(ticker)
            if not passes_quality:
                continue

            # Check P/E undervaluation
            undervalued, pe, sector_pe, discount = check_pe_undervalued(ticker)
            if not undervalued or pe is None or discount is None:
                continue

            # Get sector
            stock = yf.Ticker(ticker)
            sector = stock.info.get('sector', 'Unknown')

            candidates.append({
                'ticker': ticker,
                'sector': sector,
                'pe': pe,
                'sector_pe': sector_pe,
                'discount': discount,
                'roe': metrics.get('roe', 0),
                'rev_growth': metrics.get('rev_growth', 0),
                'debt_to_equity': metrics.get('debt_to_equity', 0)
            })

            time.sleep(0.5)  # Rate limiting

        except Exception as e:
            continue

    df = pd.DataFrame(candidates)
    if len(df) > 0:
        df = df.sort_values('discount', ascending=False)

    print(f"\n✅ Found {len(df)} quality undervalued stocks")
    return df

def calculate_portfolio_performance(current_positions):
    """
    Calculate P&L for each position and total portfolio
    Returns: performance_summary dict
    """
    if not current_positions:
        return None

    print("\n" + "="*100)
    print(f"💰 PORTFOLIO PERFORMANCE")
    print("="*100)

    total_invested = 0
    total_current_value = 0
    position_performance = []

    for ticker, position in current_positions.items():
        try:
            entry_price = position.get('entry_price')
            if entry_price is None or entry_price == 0:
                print(f"\n⚠️  {ticker}: No entry price recorded - skipping P&L")
                continue

            # Get current price
            stock = yf.Ticker(ticker)
            info = stock.info
            current_price = info.get('currentPrice', info.get('regularMarketPrice', None))

            if current_price is None:
                print(f"\n⚠️  {ticker}: Cannot fetch current price - skipping P&L")
                continue

            # Calculate P&L (assuming $500 position size, adjust if different)
            shares = 500 / entry_price  # Assumes $500 invested per stock
            invested = shares * entry_price
            current_value = shares * current_price
            pnl_dollars = current_value - invested
            pnl_percent = (current_price - entry_price) / entry_price

            total_invested += invested
            total_current_value += current_value

            position_performance.append({
                'ticker': ticker,
                'sector': position.get('sector', 'Unknown'),
                'entry_price': entry_price,
                'current_price': current_price,
                'entry_date': position.get('entry_date', 'Unknown'),
                'shares': shares,
                'invested': invested,
                'current_value': current_value,
                'pnl_dollars': pnl_dollars,
                'pnl_percent': pnl_percent,
                'days_held': (datetime.now() - datetime.strptime(position.get('entry_date', datetime.now().strftime('%Y-%m-%d')), '%Y-%m-%d')).days
            })

        except Exception as e:
            print(f"\n⚠️  {ticker}: Error calculating P&L - {e}")
            continue

    # Print individual positions
    if position_performance:
        print("\n📈 Individual Positions:")
        print("-" * 100)
        print(f"{'Ticker':<8} {'Sector':<20} {'Entry':<10} {'Current':<10} {'P&L $':<12} {'P&L %':<10} {'Days':<6}")
        print("-" * 100)

        for pos in sorted(position_performance, key=lambda x: x['pnl_percent'], reverse=True):
            pnl_symbol = "📈" if pos['pnl_dollars'] >= 0 else "📉"
            print(f"{pos['ticker']:<8} {pos['sector'][:18]:<20} ${pos['entry_price']:>7.2f} ${pos['current_price']:>9.2f} "
                  f"{pnl_symbol} ${pos['pnl_dollars']:>7.2f}  {pos['pnl_percent']*100:>7.1f}%  {pos['days_held']:>5}")

        # Print portfolio summary
        total_pnl_dollars = total_current_value - total_invested
        total_pnl_percent = (total_current_value - total_invested) / total_invested if total_invested > 0 else 0

        print("-" * 100)
        print(f"{'TOTAL':<8} {'':<20} {'':>18} {'':>10} "
              f"   ${total_pnl_dollars:>7.2f}  {total_pnl_percent*100:>7.1f}%")
        print("-" * 100)
        print(f"\n💵 Total Invested:     ${total_invested:,.2f}")
        print(f"💵 Current Value:      ${total_current_value:,.2f}")
        print(f"{'📈' if total_pnl_dollars >= 0 else '📉'} Net P&L:           ${total_pnl_dollars:,.2f} ({total_pnl_percent*100:+.1f}%)")

        # Winners vs Losers
        winners = [p for p in position_performance if p['pnl_percent'] >= 0]
        losers = [p for p in position_performance if p['pnl_percent'] < 0]
        print(f"\n🎯 Winners: {len(winners)}/{len(position_performance)}  |  Losers: {len(losers)}/{len(position_performance)}")

        if winners:
            best = max(winners, key=lambda x: x['pnl_percent'])
            print(f"🏆 Best: {best['ticker']} (+{best['pnl_percent']*100:.1f}%)")

        if losers:
            worst = min(losers, key=lambda x: x['pnl_percent'])
            print(f"⚠️  Worst: {worst['ticker']} ({worst['pnl_percent']*100:.1f}%)")

    return {
        'total_invested': total_invested,
        'total_current_value': total_current_value,
        'total_pnl_dollars': total_pnl_dollars,
        'total_pnl_percent': total_pnl_percent,
        'positions': position_performance
    }

def monthly_monitor(current_positions):
    """
    Monthly check: Verify each holding still passes quality + value filters
    Returns: (positions_to_sell, replacements_to_buy)
    """
    print("\n" + "="*100)
    print(f"📊 MONTHLY MONITOR - {datetime.now().strftime('%B %Y')}")
    print("="*100)

    if not current_positions:
        print("\n⚠️  No current positions tracked. Run quarterly rebalance first.")
        return [], []

    # Show performance first and save to CSV
    performance = calculate_portfolio_performance(current_positions)
    if performance:
        save_performance_to_csv(performance, 'monthly')

    print(f"\n📋 Current Holdings: {len(current_positions)} stocks")
    print("-" * 100)

    to_sell = []
    to_hold = []

    for ticker, position in current_positions.items():
        print(f"\n🔍 Checking {ticker}...")

        # Check quality filters
        passes_quality, metrics, reason = check_quality_filters(ticker)

        # Check P/E
        undervalued, pe, sector_pe, discount = check_pe_undervalued(ticker)

        # Decision logic
        if not passes_quality:
            print(f"   ❌ SELL - Failed quality: {reason}")
            to_sell.append({
                'ticker': ticker,
                'reason': f'Quality filter failed: {reason}',
                'entry_date': position.get('entry_date'),
                'entry_price': position.get('entry_price')
            })
        elif not undervalued:
            if discount is not None:
                print(f"   ⚠️  HOLD - No longer undervalued (P/E {pe:.1f}, discount {discount*100:.0f}%)")
                print(f"      Still quality, but watch closely. Consider selling at quarter-end.")
            else:
                print(f"   ❌ SELL - Cannot calculate P/E (invalid fundamentals)")
                to_sell.append({
                    'ticker': ticker,
                    'reason': 'Invalid P/E calculation',
                    'entry_date': position.get('entry_date'),
                    'entry_price': position.get('entry_price')
                })
            to_hold.append(ticker)
        else:
            print(f"   ✅ HOLD - Still quality + undervalued (P/E {pe:.1f}, {discount*100:.0f}% discount)")
            print(f"      ROE: {metrics.get('roe', 0)*100:.1f}%, Rev Growth: {metrics.get('rev_growth', 0)*100:.1f}%")
            to_hold.append(ticker)

    # Find replacements if we need to sell
    replacements = []
    if to_sell:
        print("\n" + "="*100)
        print(f"🔍 FINDING REPLACEMENTS ({len(to_sell)} needed)")
        print("="*100)

        sp500_tickers = get_sp500_tickers()
        if sp500_tickers:
            # Quick screen - only check top 50 by market cap for speed
            quick_screen = sp500_tickers[:100]

            candidates = []
            for ticker in quick_screen:
                if ticker in current_positions or ticker in [s['ticker'] for s in to_sell]:
                    continue

                try:
                    passes_quality, metrics, reason = check_quality_filters(ticker)
                    if not passes_quality:
                        continue

                    undervalued, pe, sector_pe, discount = check_pe_undervalued(ticker)
                    if not undervalued or pe is None:
                        continue

                    stock = yf.Ticker(ticker)
                    sector = stock.info.get('sector', 'Unknown')

                    candidates.append({
                        'ticker': ticker,
                        'sector': sector,
                        'pe': pe,
                        'sector_pe': sector_pe,
                        'discount': discount
                    })

                    time.sleep(0.5)
                except:
                    continue

            if candidates:
                candidates_df = pd.DataFrame(candidates).sort_values('discount', ascending=False)
                replacements = candidates_df.head(len(to_sell)).to_dict('records')

    return to_sell, replacements

def quarterly_rebalance(current_positions):
    """
    Quarterly: Full portfolio rebalancing
    Compare current vs top 10 recommendations
    """
    print("\n" + "="*100)
    print(f"🔄 QUARTERLY REBALANCE - {datetime.now().strftime('%B %Y')}")
    print("="*100)

    # Show performance first if we have positions and save to CSV
    if current_positions:
        performance = calculate_portfolio_performance(current_positions)
        if performance:
            save_performance_to_csv(performance, 'quarterly')

    # Get complete S&P 500 screening
    sp500_tickers = get_sp500_tickers()
    if not sp500_tickers:
        print("❌ Cannot fetch S&P 500 list")
        return [], []

    # Screen all stocks
    qualified = screen_sp500_stocks(sp500_tickers, verbose=True)

    if len(qualified) < NUM_STOCKS:
        print(f"\n⚠️  Only found {len(qualified)} stocks, need {NUM_STOCKS}")
        print("Cannot perform full rebalance")
        return [], []

    # Get top 10 recommendations
    top_picks = qualified.head(NUM_STOCKS)

    print("\n" + "="*100)
    print(f"🎯 TOP {NUM_STOCKS} RECOMMENDATIONS")
    print("="*100)

    for i, (idx, row) in enumerate(top_picks.iterrows(), 1):
        print(f"{i:2d}. {row['ticker']:6s} - {row['sector'][:20]:20s} - P/E {row['pe']:5.1f} ({row['discount']*100:.0f}% discount)")

    # Compare with current holdings
    current_tickers = set(current_positions.keys()) if current_positions else set()
    target_tickers = set(top_picks['ticker'].tolist())

    to_sell = []
    to_buy = []

    # Sell what's not in top 10
    for ticker in current_tickers:
        if ticker not in target_tickers:
            to_sell.append({
                'ticker': ticker,
                'reason': 'Not in top 10 anymore',
                'entry_date': current_positions[ticker].get('entry_date'),
                'entry_price': current_positions[ticker].get('entry_price')
            })

    # Buy what's missing
    for ticker in target_tickers:
        if ticker not in current_tickers:
            row = top_picks[top_picks['ticker'] == ticker].iloc[0]
            to_buy.append({
                'ticker': ticker,
                'sector': row['sector'],
                'pe': row['pe'],
                'discount': row['discount']
            })

    return to_sell, to_buy

def print_recommendations(to_sell, to_buy):
    """Print trading recommendations"""
    print("\n" + "="*100)
    print("📋 TRADING RECOMMENDATIONS")
    print("="*100)

    if not to_sell and not to_buy:
        print("\n✅ No changes needed - current portfolio looks good!")
        return

    if to_sell:
        print(f"\n📤 SELL ({len(to_sell)} stocks):")
        print("-" * 100)
        for stock in to_sell:
            print(f"   ❌ {stock['ticker']:6s} - {stock['reason']}")
            if stock.get('entry_date'):
                print(f"      Bought: {stock['entry_date']} @ ${stock.get('entry_price', 0):.2f}")

    if to_buy:
        print(f"\n📥 BUY ({len(to_buy)} stocks):")
        print("-" * 100)
        for stock in to_buy:
            print(f"   ✅ {stock['ticker']:6s} - {stock.get('sector', 'Unknown')[:20]:20s} - P/E {stock.get('pe', 0):.1f} ({stock.get('discount', 0)*100:.0f}% discount)")

    print("\n" + "="*100)

def update_positions(open_positions, closed_positions, to_sell, to_buy):
    """Update positions file after trades. Returns (new_open, new_closed)."""
    new_open = open_positions.copy()
    new_closed = closed_positions.copy()

    for stock in to_sell:
        ticker = stock['ticker']
        if ticker in new_open:
            position = new_open.pop(ticker)
            position['exit_date'] = datetime.now().strftime('%Y-%m-%d')
            position['exit_price'] = get_current_price(ticker)
            new_closed[ticker] = position

    for stock in to_buy:
        ticker = stock['ticker']
        print(f"   💰 {ticker} 매수가 조회 중...")
        entry_price = get_current_price(ticker)
        new_open[ticker] = {
            'entry_date': datetime.now().strftime('%Y-%m-%d'),
            'entry_price': entry_price,
            'sector': stock.get('sector', 'Unknown')
        }

    return new_open, new_closed

def print_portfolio_history(open_positions, closed_positions):
    """Print full portfolio history: past rebalancings + current holdings with live prices."""
    from collections import defaultdict

    if not closed_positions and not open_positions:
        return

    # Build combined map for held-stock lookup
    all_pos = {}
    for t, p in open_positions.items():
        all_pos[t] = {**p, '_status': 'open'}
    for t, p in closed_positions.items():
        all_pos[t] = {**p, '_status': 'closed'}

    W = 90
    print("\n" + "="*W)
    print("📊 포트폴리오 히스토리")
    print("="*W)

    # Group closed positions by exit_date (each = one rebalancing event)
    by_exit = defaultdict(list)
    for t, p in closed_positions.items():
        by_exit[p.get('exit_date', '?')].append((t, p))

    total_realized_pnl = 0
    total_realized_invested = 0

    for exit_date in sorted(by_exit.keys()):
        batch = by_exit[exit_date]
        entry_dates = [p.get('entry_date') for _, p in batch]
        entry_date = min(entry_dates) if entry_dates else '?'

        try:
            days = (datetime.strptime(exit_date, '%Y-%m-%d') - datetime.strptime(entry_date, '%Y-%m-%d')).days
        except Exception:
            days = 0

        print(f"\n리밸런싱: {entry_date} → {exit_date} ({days}일 보유)")
        print("-"*W)

        # Sold stocks
        print(f"\n📤 매도 종목")
        print(f"  {'종목':<8} {'섹터':<22} {'매수가':>9} {'매도가':>9} {'수익률':>8} {'손익':>10}")
        print("  " + "-"*70)

        sold_tickers = {t for t, _ in batch}
        for t, p in sorted(batch, key=lambda x: -(x[1].get('exit_price', 0) - x[1].get('entry_price', 0)) / (x[1].get('entry_price') or 1)):
            ep = p.get('entry_price') or 0
            xp = p.get('exit_price') or 0
            if ep and xp:
                shares = 500 / ep
                pnl = shares * (xp - ep)
                pct = (xp - ep) / ep * 100
                total_realized_pnl += pnl
                total_realized_invested += 500
                sym = "📈" if pnl >= 0 else "📉"
                print(f"  {t:<8} {p.get('sector', '')[:20]:<22} ${ep:>7.2f}  ${xp:>7.2f}  {sym}{pct:>+6.1f}%  ${pnl:>+8.2f}")

        # Held stocks (same entry_date batch, not sold this event)
        held = [(t, p) for t, p in all_pos.items()
                if p.get('entry_date') == entry_date and t not in sold_tickers]
        if held:
            print(f"\n📋 유지 종목")
            print(f"  {'종목':<8} {'섹터':<22} {'매수가':>9} {'상태':>14}")
            print("  " + "-"*56)
            for t, p in sorted(held, key=lambda x: x[0]):
                ep = p.get('entry_price') or 0
                if p['_status'] == 'open':
                    print(f"  {t:<8} {p.get('sector', '')[:20]:<22} ${ep:>7.2f}  {'보유중':>14}")
                else:
                    print(f"  {t:<8} {p.get('sector', '')[:20]:<22} ${ep:>7.2f}  → {p.get('exit_date', '?')} 매도")

    # Current open positions with live prices
    if open_positions:
        print(f"\n{'='*W}")
        print(f"📋 현재 보유 종목 ({datetime.now().strftime('%Y-%m-%d')} 기준)")
        print("-"*W)
        print(f"  {'종목':<8} {'섹터':<22} {'매수일':<12} {'매수가':>9} {'현재가':>9} {'수익률':>8} {'손익':>10}")
        print("  " + "-"*82)

        open_invested = 0
        open_value = 0

        for t in sorted(open_positions):
            p = open_positions[t]
            ep = p.get('entry_price') or 0
            entry_dt = p.get('entry_date', '?')
            cp = 0
            try:
                info = yf.Ticker(t).info
                cp = info.get('currentPrice') or info.get('regularMarketPrice') or 0
            except Exception:
                pass

            if ep and cp:
                shares = 500 / ep
                pnl = shares * (cp - ep)
                pct = (cp - ep) / ep * 100
                open_invested += 500
                open_value += shares * cp
                sym = "📈" if pnl >= 0 else "📉"
                print(f"  {t:<8} {p.get('sector', '')[:20]:<22} {entry_dt:<12} ${ep:>7.2f}  ${cp:>7.2f}  {sym}{pct:>+6.1f}%  ${pnl:>+8.2f}")
            else:
                print(f"  {t:<8} {p.get('sector', '')[:20]:<22} {entry_dt:<12} ${ep:>7.2f}  {'조회불가':>9}")

        if open_invested:
            open_pnl = open_value - open_invested
            open_pct = open_pnl / open_invested * 100
            print("  " + "-"*82)
            print(f"  현재 보유 소계: ${open_invested:,.0f} 투자 → ${open_value:,.2f} ({open_pct:>+.1f}%, ${open_pnl:>+.2f})")

    # Overall summary
    print(f"\n{'='*W}")
    print("💰 전체 포트폴리오 요약")
    print("-"*W)
    if total_realized_pnl != 0:
        print(f"  실현 손익 (매도 완료):   ${total_realized_pnl:>+,.2f}")
    if open_invested and open_value:
        open_pnl_final = open_value - open_invested
        print(f"  미실현 손익 (현재 보유): ${open_pnl_final:>+,.2f}")
        combined_pnl = total_realized_pnl + open_pnl_final
        combined_invested = total_realized_invested + open_invested
        combined_pct = combined_pnl / combined_invested * 100 if combined_invested else 0
        print(f"  통합 손익:               ${combined_pnl:>+,.2f} ({combined_pct:>+.1f}%) on ${combined_invested:,.0f} 투자")
    print("="*W + "\n")


def setup_logging():
    """Setup dual logging to console + file"""
    # Create logs directory
    os.makedirs(LOGS_DIR, exist_ok=True)

    # Create log filename with date
    log_file = os.path.join(LOGS_DIR, f"monitor_{datetime.now().strftime('%Y-%m-%d_%H%M')}.log")

    # Setup logging to both file and console
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return log_file

def log_print(message):
    """Print to both console and log file"""
    logging.info(message)

def save_performance_to_csv(performance_data, run_type):
    """
    Append performance snapshot to CSV for historical tracking
    Args:
        performance_data: dict from calculate_portfolio_performance()
        run_type: 'monthly' or 'quarterly'
    """
    if performance_data is None:
        return

    # Create CSV if doesn't exist
    csv_exists = os.path.exists(PERFORMANCE_CSV)

    # Prepare row data
    row = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'run_type': run_type,
        'total_invested': performance_data.get('total_invested', 0),
        'current_value': performance_data.get('total_current_value', 0),
        'pnl_dollars': performance_data.get('total_pnl_dollars', 0),
        'pnl_percent': performance_data.get('total_pnl_percent', 0),
        'num_positions': len(performance_data.get('positions', [])),
        'num_winners': len([p for p in performance_data.get('positions', []) if p['pnl_percent'] >= 0]),
        'num_losers': len([p for p in performance_data.get('positions', []) if p['pnl_percent'] < 0])
    }

    # Add best/worst performers
    positions = performance_data.get('positions', [])
    if positions:
        best = max(positions, key=lambda x: x['pnl_percent'])
        worst = min(positions, key=lambda x: x['pnl_percent'])
        row['best_ticker'] = best['ticker']
        row['best_return'] = best['pnl_percent']
        row['worst_ticker'] = worst['ticker']
        row['worst_return'] = worst['pnl_percent']

    # Append to CSV
    df = pd.DataFrame([row])
    df.to_csv(PERFORMANCE_CSV, mode='a', header=not csv_exists, index=False)

    print(f"\n📊 Performance saved to: {PERFORMANCE_CSV}")

# MAIN EXECUTION
if __name__ == '__main__':
    # Setup logging
    log_file = setup_logging()

    print("="*100)
    print("QUALITY VALUE MONTHLY MONITOR")
    print("="*100)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Positions file: {POSITIONS_FILE}")
    print(f"Log file: {log_file}")
    print(f"Performance CSV: {PERFORMANCE_CSV}")

    # Load current positions
    current_positions, closed_positions = load_positions()

    if current_positions:
        print(f"Current holdings: {', '.join(current_positions.keys())}")
    else:
        print("No current positions (first run)")

    # Print full portfolio history + current holdings with live prices
    print_portfolio_history(current_positions, closed_positions)

    # Determine if quarterly rebalance or monthly monitor
    run_type = 'quarterly' if is_quarter_end() else 'monthly'

    if is_quarter_end():
        print("\n🔔 QUARTER END DETECTED - Running full rebalancing")
        to_sell, to_buy = quarterly_rebalance(current_positions)
    else:
        print("\n📅 Monthly monitor - Checking current holdings")
        to_sell, to_buy = monthly_monitor(current_positions)

    # Print recommendations
    print_recommendations(to_sell, to_buy)

    # Ask user if they want to update positions file
    print("\n" + "="*100)
    print("💾 POSITION TRACKING")
    print("="*100)

    if to_sell or to_buy:
        response = input("\nUpdate positions file with these recommendations? (yes/no): ").strip().lower()

        if response == 'yes':
            new_open, new_closed = update_positions(current_positions, closed_positions, to_sell, to_buy)
            save_positions(new_open, new_closed)
            print(f"\n✅ Positions updated and saved to: {POSITIONS_FILE}")
            print(f"New holdings: {', '.join(new_open.keys())}")
        else:
            print("\n⏭️  Positions file not updated")
    else:
        print("\nNo changes - positions file unchanged")

    print("\n" + "="*100)
    print("MONITORING COMPLETE")
    print("="*100)
    print(f"\n📁 Full log saved to: {log_file}")
