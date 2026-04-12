"""Factory helpers for strict DisplaySignal creation and downgrade behavior."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from domain.display_signal import DataCompleteness, DisplaySignal, SignalConfidence, SignalLabel
from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionItem


_PLACEHOLDERS = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "undefined",
    "nan",
    "-",
    "--",
    "—",
}


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return None
    return text


def _safe_float(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    return num


def _safe_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        try:
            return date.fromisoformat(text[:10])
        except Exception:
            return None


def _coerce_confidence(value: Any) -> SignalConfidence | None:
    text = str(value or "").strip().lower()
    if text == "high":
        return SignalConfidence.HIGH
    if text == "medium":
        return SignalConfidence.MEDIUM
    if text == "low":
        return SignalConfidence.LOW
    return None


def _coerce_completeness(value: Any) -> DataCompleteness | None:
    text = str(value or "").strip().lower()
    if text in {"complete", "partial", "incomplete", "unknown", "limited"}:
        return DataCompleteness(text)
    return None


def _coerce_signal_label(value: Any) -> SignalLabel | None:
    text = str(value or "").strip().lower()
    mapping = {
        "below_expected_pace": SignalLabel.BELOW_EXPECTED_PACE,
        "below expected pace": SignalLabel.BELOW_EXPECTED_PACE,
        "lower_than_recent_pace": SignalLabel.LOWER_THAN_RECENT_PACE,
        "lower than recent pace": SignalLabel.LOWER_THAN_RECENT_PACE,
        "inconsistent_pace": SignalLabel.INCONSISTENT_PACE,
        "improving_pace": SignalLabel.IMPROVING_PACE,
        "follow_up_overdue": SignalLabel.FOLLOW_UP_OVERDUE,
        "follow_up_due_today": SignalLabel.FOLLOW_UP_DUE_TODAY,
        "unresolved_issue": SignalLabel.UNRESOLVED_ISSUE,
        "repeated_pattern": SignalLabel.REPEATED_PATTERN,
        "low_data": SignalLabel.LOW_DATA,
    }
    return mapping.get(text)


def _downgrade_low_data(
    *,
    employee_name: str | None,
    process: str | None,
    observed_date: date | None,
    flags: dict[str, bool] | None,
    today: date,
) -> DisplaySignal:
    return DisplaySignal(
        employee_name=employee_name or "Unknown employee",
        process=process or "Unassigned",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=observed_date or today,
        observed_value=None,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=DataCompleteness.LIMITED,
        flags={**(flags or {}), "downgraded_low_data": True},
    )


def build_display_signal(
    *,
    employee_name: Any,
    process: Any,
    signal_label: Any,
    observed_date: Any,
    observed_value: Any = None,
    comparison_start_date: Any = None,
    comparison_end_date: Any = None,
    comparison_value: Any = None,
    confidence: Any,
    data_completeness: Any = None,
    flags: dict[str, bool] | None = None,
    today: date | None = None,
) -> DisplaySignal:
    """Build a strict display signal and downgrade to low-data on invalid input."""
    today_value = today or date.today()

    clean_employee = _clean_text(employee_name)
    clean_process = _clean_text(process)
    label = _coerce_signal_label(signal_label)
    obs_date = _safe_date(observed_date)
    obs_value = _safe_float(observed_value)
    comp_start = _safe_date(comparison_start_date)
    comp_end = _safe_date(comparison_end_date)
    comp_value = _safe_float(comparison_value)
    conf = _coerce_confidence(confidence)
    completeness = _coerce_completeness(data_completeness)

    if clean_employee is None or clean_process is None or label is None or obs_date is None or conf is None:
        return _downgrade_low_data(
            employee_name=clean_employee,
            process=clean_process,
            observed_date=obs_date,
            flags=flags,
            today=today_value,
        )

    try:
        return DisplaySignal(
            employee_name=clean_employee,
            process=clean_process,
            signal_label=label,
            observed_date=obs_date,
            observed_value=obs_value,
            comparison_start_date=comp_start,
            comparison_end_date=comp_end,
            comparison_value=comp_value,
            confidence=conf,
            data_completeness=completeness,
            flags=dict(flags or {}),
        )
    except ValueError:
        return _downgrade_low_data(
            employee_name=clean_employee,
            process=clean_process,
            observed_date=obs_date,
            flags=flags,
            today=today_value,
        )


def build_display_signal_from_insight_card(*, card: InsightCardContract, today: date | None = None) -> DisplaySignal:
    today_value = today or date.today()
    metadata = dict(card.metadata or {})
    confidence = str(card.confidence.level or "low").lower()
    completeness = str(card.data_completeness.status or "unknown").lower()

    label_map = {
        "below_expected_performance": SignalLabel.BELOW_EXPECTED_PACE,
        "trend_change": SignalLabel.LOWER_THAN_RECENT_PACE,
        "post_activity_outcome": SignalLabel.LOWER_THAN_RECENT_PACE,
        "repeated_pattern": SignalLabel.REPEATED_PATTERN,
        "unresolved_issue": SignalLabel.UNRESOLVED_ISSUE,
        "follow_up_due": SignalLabel.FOLLOW_UP_DUE_TODAY,
        "suspicious_import_data": SignalLabel.LOW_DATA,
    }

    observed_date = card.time_context.window_end.date() if card.time_context.window_end else today_value
    comparison_start = card.time_context.compared_window_start.date() if card.time_context.compared_window_start else None
    comparison_end = card.time_context.compared_window_end.date() if card.time_context.compared_window_end else None

    return build_display_signal(
        employee_name=metadata.get("employee_name") or card.drill_down.entity_id or "Unknown employee",
        process=metadata.get("process_name") or card.workload_context.impacted_group_label or "Unassigned",
        signal_label=label_map.get(str(card.insight_kind or ""), SignalLabel.LOW_DATA.value),
        observed_date=observed_date,
        observed_value=card.workload_context.observed_volume,
        comparison_start_date=comparison_start,
        comparison_end_date=comparison_end,
        comparison_value=card.workload_context.baseline_volume,
        confidence=confidence,
        data_completeness=completeness,
        flags={
            "repeat": int(metadata.get("repeat_count") or 0) > 0,
            "overdue": str(metadata.get("queue_status") or "").lower() == "overdue",
            "due_today": str(metadata.get("queue_status") or "").lower() == "due_today",
        },
        today=today_value,
    )


def build_display_signal_from_attention_item(*, item: AttentionItem, today: date | None = None) -> DisplaySignal:
    today_value = today or date.today()
    snapshot = dict(item.snapshot or {})

    trend = str(snapshot.get("trend_state") or snapshot.get("trend") or "").strip().lower()
    queue_status = str(snapshot.get("_queue_status") or "").strip().lower()
    goal_status = str(snapshot.get("goal_status") or "").strip().lower()

    if queue_status == "overdue":
        label = SignalLabel.FOLLOW_UP_OVERDUE
    elif queue_status == "due_today":
        label = SignalLabel.FOLLOW_UP_DUE_TODAY
    elif trend in {"inconsistent"}:
        label = SignalLabel.INCONSISTENT_PACE
    elif trend in {"improving", "up"}:
        label = SignalLabel.IMPROVING_PACE
    elif goal_status == "below_goal":
        label = SignalLabel.BELOW_EXPECTED_PACE
    else:
        label = SignalLabel.LOWER_THAN_RECENT_PACE

    observed_date = _safe_date(snapshot.get("snapshot_date")) or (today_value - timedelta(days=1))

    comp_dates = []
    raw_metrics = snapshot.get("raw_metrics") or {}
    for value in list(raw_metrics.get("prior_dates") or []):
        parsed = _safe_date(value)
        if parsed is not None:
            comp_dates.append(parsed)
    comparison_start = min(comp_dates) if comp_dates else (observed_date - timedelta(days=5))
    comparison_end = max(comp_dates) if comp_dates else (observed_date - timedelta(days=1))

    return build_display_signal(
        employee_name=item.employee_id,
        process=item.process_name or snapshot.get("Department") or "Unassigned",
        signal_label=label.value,
        observed_date=observed_date,
        observed_value=snapshot.get("recent_average_uph") if snapshot.get("recent_average_uph") is not None else snapshot.get("Average UPH"),
        comparison_start_date=comparison_start,
        comparison_end_date=comparison_end,
        comparison_value=snapshot.get("expected_uph") if snapshot.get("expected_uph") is not None else snapshot.get("Target UPH"),
        confidence=snapshot.get("confidence_label") or "low",
        data_completeness=snapshot.get("data_completeness_status") or snapshot.get("completeness"),
        flags={
            "repeat": int(snapshot.get("repeat_count") or 0) > 0,
            "overdue": queue_status == "overdue",
            "due_today": queue_status == "due_today",
        },
        today=today_value,
    )


def build_display_signal_from_employee_detail_context(
    *,
    detail_context: dict[str, Any],
    employee_name: str,
    process: str,
    today: date | None = None,
) -> DisplaySignal:
    today_value = today or date.today()
    summary = dict(detail_context.get("signal_summary") or {})
    trend_state = str(detail_context.get("trend_state") or summary.get("trend_state") or "").strip().lower()

    if bool(summary.get("low_data_state") or detail_context.get("low_data_state")):
        label = SignalLabel.LOW_DATA
    elif trend_state in {"inconsistent"}:
        label = SignalLabel.INCONSISTENT_PACE
    elif trend_state in {"improving", "up"}:
        label = SignalLabel.IMPROVING_PACE
    elif trend_state in {"below_expected"}:
        label = SignalLabel.BELOW_EXPECTED_PACE
    else:
        label = SignalLabel.LOWER_THAN_RECENT_PACE

    observed_date = _safe_date((detail_context.get("contributing_periods") or {}).get("trailing_dates", [None])[-1]) or (today_value - timedelta(days=1))

    prior_dates = [
        _safe_date(value)
        for value in list((detail_context.get("contributing_periods") or {}).get("prior_dates") or [])
    ]
    prior_dates = [value for value in prior_dates if value is not None]
    comparison_start = min(prior_dates) if prior_dates else (observed_date - timedelta(days=5))
    comparison_end = max(prior_dates) if prior_dates else (observed_date - timedelta(days=1))

    before_after = dict(detail_context.get("before_after_summary") or {})
    observed_value = before_after.get("trailing_avg_uph")
    comparison_value = before_after.get("prior_avg_uph")

    return build_display_signal(
        employee_name=employee_name,
        process=process,
        signal_label=label.value,
        observed_date=observed_date,
        observed_value=observed_value,
        comparison_start_date=comparison_start,
        comparison_end_date=comparison_end,
        comparison_value=comparison_value,
        confidence=detail_context.get("confidence_label") or summary.get("confidence_label") or "low",
        data_completeness=summary.get("data_completeness_label") or detail_context.get("data_completeness_label") or "unknown",
        flags={
            "repeat": bool((detail_context.get("pattern_history") or {}).get("pattern_detected")),
        },
        today=today_value,
    )
