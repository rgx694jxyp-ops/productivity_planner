"""Today-home section adapter built on centralized signal interpretation helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionSummary, score_attention_items
from services.signal_interpretation_service import interpret_today_view_signals


_MEANINGFUL_CHANGE_KINDS = {
    "trend_change",
    "below_expected_performance",
    "post_activity_outcome",
}
_UNRESOLVED_OR_REPEATED_KINDS = {
    "unresolved_issue",
    "repeated_pattern",
    "follow_up_due",
}


def _is_recent_enough(signal: InsightCardContract, *, today: date, max_age_days: int = 7) -> bool:
    observed = signal.time_context.window_end.date() if signal.time_context.window_end else None
    if observed is None:
        return True
    age_days = (today - observed).days
    return age_days <= max_age_days


def is_signal_display_eligible(signal: InsightCardContract, *, today: date) -> bool:
    """Return True when a signal should appear in the main Today view."""
    kind = str(signal.insight_kind or "")
    confidence = str(signal.confidence.level or "low").lower()
    metadata = signal.metadata or {}

    is_unresolved_or_repeated = kind in _UNRESOLVED_OR_REPEATED_KINDS
    is_meaningful_change = kind in _MEANINGFUL_CHANGE_KINDS
    if kind == "post_activity_outcome":
        delta_uph = abs(float(metadata.get("delta_uph") or 0.0))
        is_meaningful_change = delta_uph >= 1.0

    if not (is_meaningful_change or is_unresolved_or_repeated):
        return False

    if not _is_recent_enough(signal, today=today):
        return False

    resolved = bool(
        metadata.get("resolved")
        or metadata.get("is_resolved")
        or str(metadata.get("action_status") or "").strip().lower() in {"resolved", "closed", "done"}
    )
    if resolved and not is_unresolved_or_repeated:
        return False

    confidence_ok = confidence in {"high", "medium"}
    important_despite_low = is_unresolved_or_repeated or bool(metadata.get("important_despite_low_confidence"))
    if not confidence_ok and not important_despite_low:
        return False

    return True


def build_today_home_sections(
    *,
    queue_items: list[dict],
    goal_status: list[dict],
    import_summary: dict | None,
    today: date,
) -> dict[str, list[InsightCardContract]]:
    """Build sectioned insight cards for the Today home screen.

    Centralized interpretation logic lives in signal_interpretation_service.
    """
    sections = interpret_today_view_signals(
        queue_items=queue_items,
        goal_status=goal_status,
        import_summary=import_summary,
        today=today,
    )
    filtered: dict[str, list[InsightCardContract]] = {}
    suppressed: list[InsightCardContract] = []
    for key, items in sections.items():
        allowed: list[InsightCardContract] = []
        for item in items:
            if is_signal_display_eligible(item, today=today):
                allowed.append(item)
            else:
                suppressed.append(item)
        filtered[key] = allowed
    filtered["suppressed_signals"] = suppressed
    return filtered


def build_today_attention_summary(
    *,
    goal_status: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
    open_exception_rows: list[dict[str, Any]] | None = None,
    eligible_employee_ids: set[str] | None = None,
    max_items: int = 10,
) -> AttentionSummary:
    """Score and rank Today screen items by attention priority.

    Accepts goal-status rows in the format returned by
    ``load_goal_status_history`` / ``snapshots_to_goal_status_rows``.
    The ``employee_id`` key is populated from ``EmployeeID`` when missing so
    that the scorer's lookup sets work correctly.

    Parameters
    ----------
    goal_status:
        Rows with keys: EmployeeID, Average UPH, Target UPH, trend,
        confidence_label, repeat_count, Department.
    queue_items:
        Open action queue items enriched with ``_queue_status``.
    open_exception_rows:
        Open operational exception rows (key: ``employee_id``).
    max_items:
        Maximum number of items to return in the ranked list.
    """
    normalized: list[dict[str, Any]] = []
    for row in goal_status or []:
        employee_id = str(row.get("EmployeeID") or row.get("employee_id") or "").strip()
        if not employee_id:
            continue
        if eligible_employee_ids is not None and employee_id not in eligible_employee_ids:
            continue
        normalized.append({**row, "employee_id": employee_id})

    return score_attention_items(
        snapshots=normalized,
        queue_items=queue_items,
        open_exception_rows=open_exception_rows,
        max_items=max_items,
    )
