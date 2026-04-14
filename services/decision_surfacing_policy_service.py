from __future__ import annotations

from dataclasses import dataclass

from services.decision_engine_service import DecisionItem


BUCKET_NEEDS_ATTENTION_NOW = "needs_attention_now"
BUCKET_FOLLOW_THROUGH_SOON = "follow_through_soon"
BUCKET_WATCHLIST = "watchlist"


@dataclass(frozen=True)
class DecisionSurfacingPolicy:
    primary_cap: int
    primary_employee_ids: tuple[str, ...]
    secondary_employee_ids: tuple[str, ...]
    bucket_by_employee_id: dict[str, str]
    reason_by_employee_id: dict[str, str]


def _is_negative_trend(decision: DecisionItem) -> bool:
    factor_keys = {str(f.key or "").strip().lower() for f in list(decision.attention_item.factors_applied or [])}
    if factor_keys.intersection({"trend_declining", "trend_below_expected"}):
        return True
    text = str(decision.primary_reason or "").strip().lower()
    return any(token in text for token in ("decline", "below", "under", "output is"))


def _has_meaningful_repeat_evidence(decision: DecisionItem) -> bool:
    repeat_count = int((decision.source_snapshot or {}).get("repeat_count") or 0)
    if repeat_count >= 2 and _is_negative_trend(decision):
        return True
    text = str(decision.primary_reason or "").strip().lower()
    return repeat_count >= 2 and "pattern" in text


def _has_sufficient_support(decision: DecisionItem) -> bool:
    confidence = str(decision.confidence_label or "").strip().lower()
    completeness = str((decision.source_snapshot or {}).get("data_completeness_status") or "").strip().lower()
    if confidence not in {"high", "medium"}:
        return False
    if completeness in {"limited", "unknown"}:
        return False
    return True


def _is_improving_open_item(decision: DecisionItem) -> bool:
    text = str(decision.primary_reason or "").strip().lower()
    open_state = str(decision.normalized_action_state or "").strip().lower() not in {"", "resolved"}
    return open_state and "improv" in text


def _is_low_confidence_informational(decision: DecisionItem) -> bool:
    confidence = str(decision.confidence_label or "").strip().lower()
    if confidence == "low":
        return True
    if str(decision.final_tier or "").strip().lower() == "low":
        return True
    return False


def _is_overdue_decision(decision: DecisionItem) -> bool:
    queue_status = str(decision.action_queue_status or "").strip().lower()
    action_state = str(decision.normalized_action_state or "").strip().lower()
    return queue_status == "overdue" or "overdue" in action_state


def _is_low_confidence(decision: DecisionItem) -> bool:
    confidence = str(decision.confidence_label or "").strip().lower()
    return confidence == "low"


def _bucket_for(decision: DecisionItem) -> tuple[str, str]:
    queue_status = str(decision.action_queue_status or "").strip().lower()
    action_state = str(decision.normalized_action_state or "").strip().lower()

    if queue_status == "overdue" or "overdue" in action_state:
        return BUCKET_NEEDS_ATTENTION_NOW, "Overdue follow-up requires immediate visibility"

    if _has_meaningful_repeat_evidence(decision):
        return BUCKET_NEEDS_ATTENTION_NOW, "Repeat negative pattern has meaningful support"

    if _is_negative_trend(decision) and _has_sufficient_support(decision):
        return BUCKET_NEEDS_ATTENTION_NOW, "Underperformance has enough support for immediate attention"

    if _is_improving_open_item(decision):
        return BUCKET_FOLLOW_THROUGH_SOON, "Improving item still has open follow-through"

    if queue_status in {"due_today", "pending"} or action_state in {"follow-up scheduled", "in progress"}:
        return BUCKET_FOLLOW_THROUGH_SOON, "Open action should remain visible for follow-through"

    if _is_low_confidence_informational(decision):
        return BUCKET_WATCHLIST, "Low-confidence or lower-severity informational signal"

    return BUCKET_FOLLOW_THROUGH_SOON, "Lower-severity signal stays in secondary follow-through"


def build_decision_surfacing_policy(
    decision_items: list[DecisionItem],
    *,
    primary_cap: int = 8,
) -> DecisionSurfacingPolicy:
    cap = max(1, int(primary_cap or 8))
    bucketed: dict[str, list[DecisionItem]] = {
        BUCKET_NEEDS_ATTENTION_NOW: [],
        BUCKET_FOLLOW_THROUGH_SOON: [],
        BUCKET_WATCHLIST: [],
    }
    reason_by_employee_id: dict[str, str] = {}

    for item in list(decision_items or []):
        bucket, reason = _bucket_for(item)
        bucketed[bucket].append(item)
        if item.employee_id:
            reason_by_employee_id[item.employee_id] = reason

    for key in list(bucketed.keys()):
        bucketed[key].sort(
            key=lambda row: (
                1 if key == BUCKET_NEEDS_ATTENTION_NOW and _is_overdue_decision(row) and _is_low_confidence(row) else 0,
                -int(row.final_score or 0),
                str(row.employee_id or "").lower(),
                str(row.process_name or "").lower(),
            )
        )

    primary_candidates = list(bucketed[BUCKET_NEEDS_ATTENTION_NOW])
    primary = primary_candidates[:cap]
    overflow = primary_candidates[cap:]

    secondary = [
        *overflow,
        *list(bucketed[BUCKET_FOLLOW_THROUGH_SOON]),
        *list(bucketed[BUCKET_WATCHLIST]),
    ]

    for overflow_item in overflow:
        if overflow_item.employee_id:
            reason_by_employee_id[overflow_item.employee_id] = "Urgent signal retained in secondary due to primary cap"

    bucket_by_employee_id: dict[str, str] = {}
    for item in primary:
        if item.employee_id:
            bucket_by_employee_id[item.employee_id] = BUCKET_NEEDS_ATTENTION_NOW
    for item in secondary:
        if item.employee_id:
            bucket_by_employee_id[item.employee_id] = BUCKET_FOLLOW_THROUGH_SOON if item in overflow else bucket_by_employee_id.get(item.employee_id, _bucket_for(item)[0])

    return DecisionSurfacingPolicy(
        primary_cap=cap,
        primary_employee_ids=tuple(item.employee_id for item in primary if item.employee_id),
        secondary_employee_ids=tuple(item.employee_id for item in secondary if item.employee_id),
        bucket_by_employee_id=bucket_by_employee_id,
        reason_by_employee_id=reason_by_employee_id,
    )