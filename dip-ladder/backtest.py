#!/usr/bin/env python3
"""
Dip-ladder strategy backtest (2020-01-01 ~ present)

자본 배분:
  QLD $25,000 / SSO $15,000 / USD $10,000

매수 비중:
  1차 (20MA 터치): 현금풀의 7.5% 총 2일 분할
  2차 (60MA 터치): 트리거 시점 남은현금의 50% 총 3일 분할
  3차 (120MA 터치): 트리거 시점 남은현금의 50% 총 5일 분할
  4차 (120MA 아래 + RSI < 35): 트리거 시점 남은현금 100% 총 5일 분할
"""

import argparse
import csv
import os
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import yfinance as yf

START_DATE = "2020-01-01"
END_DATE = None  # None = 오늘까지
INITIAL_CASH = {
    "QLD": 25_000.0,
    "SSO": 15_000.0,
    "USD": 10_000.0,
}
TICKER_LABELS = {
    "QLD": "나스닥 2x",
    "SSO": "S&P500 2x",
    "USD": "반도체 2x",
}

# Level 1: % of INITIAL pool (not remaining)
LEVEL1_PCT_OF_POOL = 0.05  # 5%
LEVEL_DAYS = {1: 2, 2: 3, 3: 5, 4: 5}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "backtest_results")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def download_data(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    # 120MA 계산을 위해 start보다 200일 더 일찍 받음
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    df = df.copy()
    df["ma20"] = close.rolling(20).mean()
    df["ma60"] = close.rolling(60).mean()
    df["ma120"] = close.rolling(120).mean()
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, min_periods=14).mean()
    avg_loss = loss.ewm(com=13, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


# ---------------------------------------------------------------------------
# State per ticker
# ---------------------------------------------------------------------------

@dataclass
class TickerState:
    ticker: str
    initial_cash: float
    cash: float = 0.0
    shares: float = 0.0
    pending: list = field(default_factory=list)  # list of (daily_amount, level, days_left)

    def __post_init__(self):
        self.cash = self.initial_cash


# ---------------------------------------------------------------------------
# Signal detection (mirrors signals.py logic)
# ---------------------------------------------------------------------------

def detect_signals(row: pd.Series, active_levels: set[int]) -> list[int]:
    """Return newly triggered levels (not already active)."""
    price, ma20, ma60, ma120, rsi_val = (
        float(row["Close"]),
        row["ma20"], row["ma60"], row["ma120"], row["rsi"],
    )
    if any(pd.isna(v) for v in [ma20, ma60, ma120, rsi_val]):
        return []

    triggered = []
    if 1 not in active_levels and price <= float(ma20):
        triggered.append(1)
    if 2 not in active_levels and price <= float(ma60):
        triggered.append(2)
    if 3 not in active_levels and price <= float(ma120):
        triggered.append(3)
    if 4 not in active_levels and price <= float(ma120) and rsi_val < 35:
        triggered.append(4)
    return triggered


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

@dataclass
class BuyEvent:
    date: str
    ticker: str
    level: int
    action: str  # new / continue / complete
    day: int
    total_days: int
    price: float
    amount: float
    shares_bought: float
    cash_after: float
    shares_total: float
    portfolio_value: float


def run_ticker(ticker: str, df: pd.DataFrame) -> tuple[list[BuyEvent], list[tuple]]:
    """Run simulation for a single ticker. Returns buy events and daily portfolio snapshots."""
    state = TickerState(ticker=ticker, initial_cash=INITIAL_CASH[ticker])
    active_levels: set[int] = set()  # currently running split-buy sequences
    events: list[BuyEvent] = []
    snapshots: list[tuple] = []  # (date, price, cash, shares, portfolio_value)

    for ts, row in df.iterrows():
        day_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        price = float(row["Close"])

        # Execute pending daily buys (from active sequences)
        still_pending = []
        for daily_amount, lvl, days_left in state.pending:
            spend = min(daily_amount, state.cash)
            if spend > 0 and price > 0:
                bought = spend / price
                state.cash -= spend
                state.shares += bought
                day_num = LEVEL_DAYS[lvl] - days_left + 1
                action = "complete" if days_left == 1 else "continue"
                events.append(BuyEvent(
                    date=day_str, ticker=ticker, level=lvl,
                    action=action, day=day_num, total_days=LEVEL_DAYS[lvl],
                    price=price, amount=spend, shares_bought=bought,
                    cash_after=state.cash, shares_total=state.shares,
                    portfolio_value=state.cash + state.shares * price,
                ))
                if action == "complete":
                    active_levels.discard(lvl)
            if days_left > 1:
                still_pending.append((daily_amount, lvl, days_left - 1))
        state.pending = still_pending

        # Detect new signals
        for lvl in detect_signals(row, active_levels):
            if lvl == 1:
                total = state.initial_cash * LEVEL1_PCT_OF_POOL
            elif lvl == 2:
                total = state.cash * 0.50
            elif lvl == 3:
                total = state.cash * 0.50
            else:  # lvl == 4
                total = state.cash
            daily = total / LEVEL_DAYS[lvl]

            # First day buy immediately
            spend = min(daily, state.cash)
            if spend > 0 and price > 0:
                bought = spend / price
                state.cash -= spend
                state.shares += bought
                active_levels.add(lvl)
                events.append(BuyEvent(
                    date=day_str, ticker=ticker, level=lvl,
                    action="new", day=1, total_days=LEVEL_DAYS[lvl],
                    price=price, amount=spend, shares_bought=bought,
                    cash_after=state.cash, shares_total=state.shares,
                    portfolio_value=state.cash + state.shares * price,
                ))
                remaining_days = LEVEL_DAYS[lvl] - 1
                if remaining_days > 0:
                    state.pending.append((daily, lvl, remaining_days))

        pv = state.cash + state.shares * price
        snapshots.append((day_str, price, state.cash, state.shares, pv))

    return events, snapshots


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_results(all_events: list[BuyEvent], all_snapshots: dict[str, list],
                 start: str, end: str) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Buy events CSV
    events_path = os.path.join(OUTPUT_DIR, "buy_events.csv")
    with open(events_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["날짜", "티커", "차수", "액션", "일차", "총일수",
                    "매수가", "투자금액($)", "매수주수", "남은현금($)", "총주수", "평가금액($)"])
        for e in all_events:
            w.writerow([
                e.date, e.ticker, f"{e.level}차", e.action, e.day, e.total_days,
                f"{e.price:.2f}", f"{e.amount:.2f}", f"{e.shares_bought:.4f}",
                f"{e.cash_after:.2f}", f"{e.shares_total:.4f}", f"{e.portfolio_value:.2f}",
            ])

    # Portfolio daily snapshot CSV
    snap_path = os.path.join(OUTPUT_DIR, "portfolio_daily.csv")
    with open(snap_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["날짜", "티커", "현재가", "남은현금($)", "보유주수", "평가금액($)"])
        for ticker, snaps in all_snapshots.items():
            for day_str, price, cash, shares, pv in snaps:
                w.writerow([day_str, ticker, f"{price:.2f}",
                            f"{cash:.2f}", f"{shares:.4f}", f"{pv:.2f}"])

    # Summary report
    summary_path = os.path.join(OUTPUT_DIR, "summary.txt")
    sep = "=" * 62
    lines = [sep, f"웅덩이 매매법 백테스트 결과 [{date.today()}]", f"기간: {start} ~ {end}", sep, ""]

    total_initial = sum(INITIAL_CASH.values())
    total_final = 0.0

    for ticker, snaps in all_snapshots.items():
        initial = INITIAL_CASH[ticker]
        _, last_price, last_cash, last_shares, last_pv = snaps[-1]
        total_final += last_pv
        ret = (last_pv - initial) / initial * 100
        ticker_events = [e for e in all_events if e.ticker == ticker]
        level_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for e in ticker_events:
            if e.action == "new":
                level_counts[e.level] += 1

        lines.append(f"[{ticker}] {TICKER_LABELS[ticker]}")
        lines.append(f"  시작 현금:    ${initial:>10,.2f}")
        lines.append(f"  현재 평가액:  ${last_pv:>10,.2f}  ({ret:+.1f}%)")
        lines.append(f"  남은 현금:    ${last_cash:>10,.2f}")
        lines.append(f"  보유 주수:    {last_shares:.4f}주 @ ${last_price:.2f}")
        lines.append(f"  매수 이벤트:  1차 {level_counts[1]}회 / 2차 {level_counts[2]}회 / "
                     f"3차 {level_counts[3]}회 / 4차 {level_counts[4]}회")
        lines.append("")

    total_ret = (total_final - total_initial) / total_initial * 100
    lines.append("-" * 62)
    lines.append(f"  전체 시작:    ${total_initial:>10,.2f}")
    lines.append(f"  전체 평가액:  ${total_final:>10,.2f}  ({total_ret:+.1f}%)")

    # Hold & compare (just buy and hold from start)
    lines.append("")
    lines.append("  (참고: 첫날 전액 매수 시나리오는 buy_events.csv 참조)")
    lines.append(sep)

    report = "\n".join(lines)
    print(report)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    print(f"\n📁 결과 저장: {OUTPUT_DIR}/")
    print(f"   - summary.txt       (전체 요약)")
    print(f"   - buy_events.csv    (매수 이력)")
    print(f"   - portfolio_daily.csv (일별 평가)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="dip-ladder backtest")
    parser.add_argument("--start", default=START_DATE, help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="종료일 (YYYY-MM-DD), 생략 시 오늘")
    args = parser.parse_args()

    end_label = args.end or str(date.today())
    print(f"백테스트 실행 중 ({args.start} ~ {end_label})...")

    all_events: list[BuyEvent] = []
    all_snapshots: dict[str, list] = {}

    for ticker in INITIAL_CASH:
        print(f"  {ticker} 데이터 다운로드 및 시뮬레이션...")
        df = download_data(ticker, args.start, args.end)
        df = add_indicators(df)
        events, snapshots = run_ticker(ticker, df)
        all_events.extend(events)
        all_snapshots[ticker] = snapshots

    all_events.sort(key=lambda e: e.date)
    print()
    save_results(all_events, all_snapshots, start=args.start, end=end_label)


if __name__ == "__main__":
    main()
