"""Deterministic signal filtering and confidence-ranking rules."""

from __future__ import annotations

from dataclasses import dataclass, replace

from domain.insight_card_contract import InsightCardContract


@dataclass(frozen=True)
class SignalQualityDecision:
    include: bool
    score: int
    reasons: list[str]
    tier: str  # strong | usable | weak


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def evaluate_signal_quality(card: InsightCardContract) -> SignalQualityDecision:
    """Compute deterministic quality score from confidence + completeness + context.

    Score model:
    - Start at 50
    - Incomplete/partial data, low sample, partial shifts/rows, anomalies reduce score
    - Repeated pattern and complete supporting data increase score
    """
    score = 50
    reasons: list[str] = []

    confidence_level = str(card.confidence.level or "low")
    sample_size = _as_int(card.confidence.sample_size, 0)
    min_expected = _as_int(card.confidence.minimum_expected_points, 1)

    if confidence_level == "high":
        score += 30
        reasons.append("high confidence")
    elif confidence_level == "medium":
        score += 10
        reasons.append("medium confidence")
    else:
        score -= 15
        reasons.append("low confidence")

    completeness = str(card.data_completeness.status or "unknown")
    if completeness == "complete":
        score += 15
        reasons.append("complete data")
    elif completeness == "partial":
        score -= 10
        reasons.append("partial data")
    elif completeness == "incomplete":
        score -= 25
        reasons.append("incomplete data")

    if sample_size > 0 and min_expected > 0 and sample_size < min_expected:
        score -= 20
        reasons.append("sample size below threshold")

    meta = card.metadata or {}
    partial_shift = bool(meta.get("partial_shift"))
    partial_row = bool(meta.get("partial_row"))
    anomaly_count = _as_int(meta.get("anomaly_count"), 0)

    if partial_shift or partial_row:
        score -= 12
        reasons.append("partial shift/row")

    if anomaly_count > 0:
        score -= min(20, 5 * anomaly_count)
        reasons.append("known anomaly")

    repeated_supported = (
        str(card.insight_kind or "") == "repeated_pattern"
        or _as_int(meta.get("repeat_count"), 0) >= 2
    )
    if repeated_supported and completeness == "complete":
        score += 15
        reasons.append("repeated supported pattern")

    score = max(0, min(100, score))

    if score >= 70:
        tier = "strong"
    elif score >= 45:
        tier = "usable"
    else:
        tier = "weak"

    include = score >= 45
    return SignalQualityDecision(include=include, score=score, reasons=reasons, tier=tier)


def rank_and_filter_signals(
    cards: list[InsightCardContract],
    *,
    keep_weak: bool = False,
    max_items: int | None = None,
) -> list[InsightCardContract]:
    """Apply deterministic filtering and ranking.

    - Suppress weak signals unless keep_weak=True
    - Rank by quality score desc, then by stable insight_id asc
    - Persist decision metadata on returned cards
    """
    scored: list[tuple[int, InsightCardContract]] = []
    weak: list[tuple[int, InsightCardContract]] = []

    for card in cards or []:
        decision = evaluate_signal_quality(card)
        card_with_quality = replace(
            card,
            metadata={
                **(card.metadata or {}),
                "quality_score": decision.score,
                "quality_tier": decision.tier,
                "quality_reasons": list(decision.reasons),
                "quality_included": bool(decision.include),
            },
        )
        bucket = scored if decision.include else weak
        bucket.append((decision.score, card_with_quality))

    ordered = sorted(scored, key=lambda row: (-row[0], str(row[1].insight_id)))
    if keep_weak:
        ordered.extend(sorted(weak, key=lambda row: (-row[0], str(row[1].insight_id))))

    out = [row[1] for row in ordered]
    if isinstance(max_items, int) and max_items > 0:
        out = out[:max_items]
    return out
