"""
Composite heat score engine.

Each signal module returns a 0-100 sub-score. The composite is a weighted sum
where each weight represents how many of the 100 total points that category
can contribute (e.g. weight=25 means a perfect sub-score contributes 25 pts).

Multiplicative boosters applied on top for synergistic signal combinations:
  8-K filing + volume surge    → 1.3x  (institution already moving + news catalyst)
  Insider cluster + compression → 1.25x (insiders know + spring coiled)
  High short interest + catalyst → 1.2x (fuel + trigger = squeeze)
"""
import config


def compute_heat_score(signals: dict) -> tuple[float, dict]:
    """
    signals: {
      "sec_filings":        (score_0_100, detail_dict),
      "insider_buying":     (score_0_100, detail_dict),
      "volume_anomaly":     (score_0_100, detail_dict),
      "sentiment_velocity": (score_0_100, detail_dict),
      "short_squeeze":      (score_0_100, detail_dict),
      "options_flow":       (score_0_100, detail_dict),   # optional
      "technicals":         (score_0_100, detail_dict),   # optional
    }
    Returns (composite_heat_score_0_100, breakdown_dict).
    """
    weights = config.WEIGHTS
    base_score = 0.0
    breakdown = {}

    for category, weight in weights.items():
        if category in signals:
            sub_score, detail = signals[category]
            contribution = (sub_score / 100.0) * weight
            base_score += contribution
            breakdown[category] = {
                "sub_score": round(sub_score, 1),
                "weight": weight,
                "contribution": round(contribution, 2),
                "detail": detail,
            }

    boosted_score = _apply_boosters(base_score, signals, breakdown)
    final = round(min(100.0, boosted_score), 1)

    return final, breakdown


def _apply_boosters(base_score: float, signals: dict, breakdown: dict) -> float:
    """Apply multiplicative boosters for synergistic signal combinations."""
    multiplier = 1.0

    sec_score = signals.get("sec_filings", (0,))[0]
    vol_score = signals.get("volume_anomaly", (0,))[0]
    insider_score = signals.get("insider_buying", (0,))[0]
    comp_score = _get_compression_score(signals)
    si_score = signals.get("short_squeeze", (0,))[0]
    has_catalyst = sec_score > 0 or insider_score >= 40

    # 8-K + volume surge: institution is already buying on the news
    if sec_score >= 40 and vol_score >= 50:
        multiplier = max(multiplier, 1.30)
        breakdown["_booster_8k_volume"] = 1.30

    # Insider cluster + compression: insiders know + spring coiled
    if insider_score >= 40 and comp_score >= 50:
        multiplier = max(multiplier, 1.25)
        breakdown["_booster_insider_compression"] = 1.25

    # High short interest + any catalyst = squeeze fuel + trigger
    if si_score >= 60 and has_catalyst:
        multiplier = max(multiplier, 1.20)
        breakdown["_booster_squeeze"] = 1.20

    return base_score * multiplier


def _get_compression_score(signals: dict) -> float:
    """Extract compression sub-score from the momentum signal detail."""
    momentum = signals.get("volume_anomaly")
    if not momentum:
        return 0.0
    _, detail = momentum
    return detail.get("compression", {}).get("score", 0.0)


def classify_heat(score: float) -> str:
    if score >= config.HOT_THRESHOLD:
        return "HOT"
    elif score >= config.WARM_THRESHOLD:
        return "WARM"
    return "COLD"


def compute_delta(ticker: str, current_score: float, prior_scores: dict) -> dict:
    """
    Compare current score to prior day's score.
    Returns {delta_1d, is_new_entrant, is_accelerating}.
    """
    prior = prior_scores.get(ticker)
    if prior is None:
        return {"delta_1d": None, "is_new_entrant": True, "is_accelerating": False}

    delta = round(current_score - prior, 1)
    return {
        "delta_1d": delta,
        "is_new_entrant": False,
        "is_accelerating": delta >= 10,  # Score jumped 10+ pts overnight
    }


def top_signal_label(breakdown: dict) -> str:
    """Return a human-readable string describing the strongest signal."""
    contributions = {
        k: v["contribution"]
        for k, v in breakdown.items()
        if not k.startswith("_") and isinstance(v, dict) and "contribution" in v
    }
    if not contributions:
        return "—"

    top = max(contributions, key=contributions.get)
    sub_score = breakdown[top]["sub_score"]
    detail = breakdown[top].get("detail", {})

    labels = {
        "sec_filings":        _sec_label(detail, sub_score),
        "insider_buying":     _insider_label(detail, sub_score),
        "volume_anomaly":     _vol_label(detail, sub_score),
        "sentiment_velocity": _sentiment_label(detail, sub_score),
        "short_squeeze":      _si_label(detail, sub_score),
        "options_flow":       f"Options flow {sub_score:.0f}/100",
        "technicals":         f"Technical pattern {sub_score:.0f}/100",
    }
    return labels.get(top, top)


def _sec_label(d: dict, score: float) -> str:
    parts = []
    if d.get("has_8k"):
        parts.append("8-K filing")
    if d.get("insider_cluster"):
        parts.append("Insider cluster buy")
    if d.get("has_activist"):
        parts.append("13D activist")
    return " + ".join(parts) if parts else f"SEC filing {score:.0f}/100"


def _insider_label(d: dict, score: float) -> str:
    n = d.get("insider_count", 0)
    return f"{n} insiders buying" if n else f"Insider activity {score:.0f}/100"


def _vol_label(d: dict, score: float) -> str:
    vol_d = d.get("volume", {})
    ratio = vol_d.get("surge_ratio")
    div = vol_d.get("divergence", False)
    if ratio:
        label = f"Vol {ratio:.1f}x baseline"
        if div:
            label += " (accumulation)"
        return label
    return f"Volume anomaly {score:.0f}/100"


def _sentiment_label(d: dict, score: float) -> str:
    vel = d.get("velocity")
    mentions = d.get("today_mentions", 0)
    if vel:
        return f"Reddit {vel:.1f}x mention surge ({mentions} mentions)"
    return f"Reddit {mentions} mentions"


def _si_label(d: dict, score: float) -> str:
    pct = d.get("short_pct_float")
    dtc = d.get("days_to_cover")
    if pct and dtc:
        return f"SI {pct:.0f}% float, {dtc:.1f} days to cover"
    return f"Short squeeze setup {score:.0f}/100"
