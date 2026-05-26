from datetime import datetime
from fetcher import TICKERS

LEVEL_LABELS = {
    1: ("1차 (20일선)", "2일"),
    2: ("2차 (60일선)", "3일"),
    3: ("3차 (120일선)", "5일"),
    4: ("4차 (RSI<35)", "5일"),
}

BUY_PORTION = {
    1: "현금의 5~10%",
    2: "남은현금의 약 33%",
    3: "남은현금의 20%",
    4: "남은현금의 20%",
}


def _signal_line(ind: dict) -> list[str]:
    lines = []
    price = ind["price"]
    for ma_key, label in [("ma20", "20MA"), ("ma60", "60MA"), ("ma120", "120MA")]:
        ma_val = ind[ma_key]
        marker = "  ← 현재가 < {label}".format(label=label) if price <= ma_val else ""
        lines.append(f"  {label}:    ${ma_val:>8.2f}{marker}")
    return lines


def build_report(results: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep = "=" * 62
    thin = "-" * 62

    lines = [sep, f"웅덩이 매매법 리포트 [{now}]", sep, ""]

    buy_summary = []

    for r in results:
        ticker = r["ticker"]
        label = TICKERS[ticker]
        ind = r["indicators"]
        actions = r["actions"]

        lines.append(f"[{ticker}]  {label}")
        lines.append(f"  현재가:  ${ind['price']:>8.2f}")
        lines.extend(_signal_line(ind))
        lines.append(f"  RSI(14): {ind['rsi']:>6.1f}")

        if actions:
            lines.append("")
            lines.append("  📋 오늘 매수 행동:")
            for a in actions:
                lvl = a["level"]
                lbl, _ = LEVEL_LABELS[lvl]
                portion = BUY_PORTION[lvl]
                day_str = f"{a['day']}일차/{a['total_days']}일"
                if a["action"] == "complete":
                    tag = f"→ {lbl} {day_str} ✅ 마지막 매수 ({portion})"
                elif a["action"] == "new":
                    tag = f"→ {lbl} {day_str} 🆕 신규 신호 ({portion})"
                else:
                    tag = f"→ {lbl} {day_str} 진행중 ({portion})"
                lines.append(f"    {tag}")
                buy_summary.append(f"{ticker} {lbl} {day_str}")
        else:
            lines.append("")
            lines.append("  ✅ 매수 신호 없음")

        lines.append(thin)

    if buy_summary:
        lines.append("")
        lines.append("⚠️  오늘 매수 필요:")
        for s in buy_summary:
            lines.append(f"   • {s}")
    else:
        lines.append("")
        lines.append("✅ 오늘은 매수 신호 없음")

    lines.append(sep)
    return "\n".join(lines)
