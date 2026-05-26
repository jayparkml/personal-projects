#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Spike Scanner — Double-click to run
# macOS: Right-click → Open (first time only to bypass Gatekeeper)
# ──────────────────────────────────────────────────────────────────────────────

# Change to the directory where this script lives (not wherever Finder launched it)
cd "$(dirname "$0")"

clear
echo "╔══════════════════════════════════════════════════════════╗"
echo "║             SPIKE SCANNER — Daily Run                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Starting at $(date '+%Y-%m-%d %H:%M')"
echo ""

# Run the scanner
python3 runner.py

EXIT_CODE=$?

echo ""
echo "──────────────────────────────────────────────────────────────"

if [ $EXIT_CODE -eq 0 ]; then
    TODAY=$(date '+%Y-%m-%d')
    REPORT="data/reports/${TODAY}.csv"

    echo ""

    # ── Full daily summary (buy signals, sell actions, positions) ────────────
    python3 - <<'PYEOF'
import csv, json, os
from datetime import date

today = str(date.today())
SEP = "──────────────────────────────────────────────────────────────"

# ── 1. Buy / Watch / Nothing recommendation ───────────────────────────────
report_path = f"data/reports/{today}.csv"
if os.path.exists(report_path):
    with open(report_path) as f:
        rows = list(csv.DictReader(f))
    hot  = [r for r in rows if r.get("class","").strip() == "HOT"]
    warm = [r for r in rows if r.get("class","").strip() == "WARM"]

    print(SEP)
    if hot:
        print("\n  ✅  BUY TODAY:")
        for r in hot:
            sig = r.get("top_signal","").strip()
            print(f"  🔥  {r['ticker']:<6}  score {float(r['score']):.0f}  —  {sig}")
        print()
    elif warm:
        print("\n  👀  WATCH (not HOT yet — do not buy):")
        for r in warm[:3]:
            sig = r.get("top_signal","").strip()
            print(f"  🌡  {r['ticker']:<6}  score {float(r['score']):.0f}  —  {sig}")
        print()
        print("  Nothing to buy today — no stock has reached HOT (60+).")
        print()
    else:
        top = rows[0] if rows else None
        print()
        if top:
            print(f"  ❌  NOTHING TO BUY TODAY")
            print(f"     Top: {top['ticker']} at {float(top['score']):.0f} pts — still COLD.")
        else:
            print("  ❌  No results today.")
        print()

# ── 2. Trades auto-executed today ─────────────────────────────────────────
log_path = "data/trade_log.csv"
if os.path.exists(log_path):
    with open(log_path) as f:
        trades = list(csv.DictReader(f))
    today_trades = [t for t in trades if t.get("date","").startswith(today)]
    buys  = [t for t in today_trades if t.get("action") == "BUY"]
    sells = [t for t in today_trades if t.get("action") == "SELL"]

    if buys:
        print(SEP)
        print("\n  🟢  BOUGHT TODAY (auto-logged):")
        for t in buys:
            print(f"     {t['ticker']:<6}  ${float(t['price']):.2f}  score {t['score']}  ({t.get('reason','')})")
        print()

    if sells:
        print(SEP)
        print("\n  🔴  SOLD TODAY (auto-logged):")
        for t in sells:
            pnl = t.get("pnl_pct","")
            hold = t.get("hold_days","")
            ep   = t.get("entry_price","")
            pnl_str  = f"  P&L {pnl}" if pnl else ""
            hold_str = f"  held {hold}d" if hold else ""
            ep_str   = f"  bought @ ${float(ep):.2f}" if ep else ""
            print(f"     {t['ticker']:<6}  ${float(t['price']):.2f}{ep_str}{hold_str}{pnl_str}  ({t.get('reason','')})")
        print()

# ── 3. Current open positions ─────────────────────────────────────────────
STOP_LOSS_PCT  = 0.08
TRAIL_STOP_PCT = 0.20
PHASE1_DAYS    = 10

pos_path = "data/positions.json"
if os.path.exists(pos_path):
    with open(pos_path) as f:
        positions = json.load(f)
    if positions:
        print(SEP)
        print(f"\n  📂  OPEN POSITIONS ({len(positions)}):")
        print(f"  {'Ticker':<7} {'Bought':<12} {'@ Price':>9}  {'Day':>4}  {'Stop$':>8}  P&L%")
        print(f"  {'-'*7} {'-'*12} {'-'*9}  {'-'*4}  {'-'*8}  ----")
        exit_warn = []
        for ticker, pos in positions.items():
            ep    = pos.get("entry_price", 0)
            peak  = pos.get("peak_price", ep)
            hdays = pos.get("hold_days", 0)
            edate = pos.get("entry_date", "")
            pnl   = pos.get("pnl_pct_today")
            pnl_str = f"{pnl:+.1f}%" if isinstance(pnl, (int, float)) else "—"

            if hdays <= PHASE1_DAYS:
                stop = ep * (1 - STOP_LOSS_PCT)
                phase = f"day {hdays}/10 hard-stop"
            else:
                stop = peak * (1 - TRAIL_STOP_PCT)
                phase = f"day {hdays} trail"

            print(f"  {ticker:<7} {edate:<12} ${ep:>8.2f}  {hdays:>4}  ${stop:>7.2f}  {pnl_str}  ({phase})")

            # Flag if today's price is within 5% of stop (close to triggering)
            cur_pnl = pnl if isinstance(pnl, (int, float)) else 0
            if ep > 0:
                cur_price = ep * (1 + cur_pnl / 100)
                if cur_price < stop * 1.05:
                    exit_warn.append(ticker)

        print()
        if exit_warn:
            print(f"  ⚠  NEAR EXIT TRIGGER: {', '.join(exit_warn)} (within 5% of stop)")
            print()
PYEOF

else
    echo "  ✗  Scanner exited with error (code $EXIT_CODE)"
    echo "     Check data/scanner.log for details"
fi

echo ""
echo "──────────────────────────────────────────────────────────────"
echo "  Press any key to close..."
read -n 1 -s
