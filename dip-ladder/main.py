#!/usr/bin/env python3
import os
import sys
from datetime import date

from fetcher import TICKERS, fetch_all
from indicators import compute
from signals import load_state, save_state, update_ticker
from reporter import build_report

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")


def main():
    print("데이터 다운로드 중...")

    try:
        all_data = fetch_all(days=200)
    except Exception as e:
        print(f"데이터 다운로드 실패: {e}")
        sys.exit(1)

    state = load_state()
    results = []

    for ticker in TICKERS:
        df = all_data[ticker]
        ind = compute(df)
        state, actions = update_ticker(ticker, ind, state)
        results.append({"ticker": ticker, "indicators": ind, "actions": actions})

    save_state(state)

    report = build_report(results)

    print("\n" + report)

    log_path = os.path.join(LOG_DIR, f"{date.today().isoformat()}.txt")
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    print(f"\n📁 로그 저장: {log_path}")


if __name__ == "__main__":
    main()
