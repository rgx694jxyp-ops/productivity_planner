"""Factory helpers for strict DisplaySignal creation and downgrade behavior."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from domain.display_signal import (
    DataCompleteness,
    DisplayConfidenceLevel,
    DisplaySignal,
    DisplaySignalState,
    SignalConfidence,
    SignalLabel,
)
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
    employee_id: str | None,
    employee_name: str | None,
    process: str | None,
    observed_date: date | None,
    flags: dict[str, bool] | None,
    today: date,
) -> DisplaySignal:
    clean_flags = dict(flags or {})
    return DisplaySignal(
        employee_id=employee_id or "unknown-employee",
        employee_name=employee_name or "Unknown employee",
        process=process or "Unassigned",
        state=DisplaySignalState.LOW_DATA,
        primary_label="Not enough history yet",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=observed_date or today,
        observed_value=None,
        observed_unit="UPH",
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        pattern_count=None,
        pattern_window_label=None,
        confidence_level=DisplayConfidenceLevel.LOW,
        confidence=SignalConfidence.LOW,
        is_low_data=True,
        is_new_employee=bool(clean_flags.get("new_employee") or clean_flags.get("is_new_employee")),
        is_actionable=False,
        supporting_text=[],
        delta_percent=None,
        data_completeness=DataCompleteness.LIMITED,
        flags={**clean_flags, "downgraded_low_data": True},
    )


def _derive_state(*, label: SignalLabel, has_observed: bool, has_comparison: bool, confidence: SignalConfidence, pattern_count: int | None) -> DisplaySignalState:
    return _derive_state_with_inputs(
        label=label,
        has_observed=has_observed,
        has_comparison=has_comparison,
        confidence=confidence,
        pattern_count=pattern_count,
        usable_points=None,
        minimum_trend_points=None,
    )


def _derive_state_with_inputs(
    *,
    label: SignalLabel,
    has_observed: bool,
    has_comparison: bool,
    confidence: SignalConfidence,
    pattern_count: int | None,
    usable_points: int | None,
    minimum_trend_points: int | None,
) -> DisplaySignalState:
    metric_labels = {
        SignalLabel.BELOW_EXPECTED_PACE,
        SignalLabel.LOWER_THAN_RECENT_PACE,
        SignalLabel.INCONSISTENT_PACE,
        SignalLabel.IMPROVING_PACE,
    }
    if label == SignalLabel.LOW_DATA or not has_observed:
        return DisplaySignalState.LOW_DATA
    if label in metric_labels and usable_points is not None and usable_points <= 1:
        return DisplaySignalState.CURRENT
    if label in metric_labels and usable_points is not None and usable_points == 2:
        return DisplaySignalState.EARLY_TREND
    if label in metric_labels and not has_comparison:
        return DisplaySignalState.CURRENT
    if label in {SignalLabel.REPEATED_PATTERN, SignalLabel.UNRESOLVED_ISSUE, SignalLabel.FOLLOW_UP_OVERDUE, SignalLabel.FOLLOW_UP_DUE_TODAY}:
        return DisplaySignalState.PATTERN
    if label not in metric_labels and pattern_count is not None and int(pattern_count or 0) > 1:
        return DisplaySignalState.PATTERN
    if usable_points is not None and usable_points <= 1:
        return DisplaySignalState.CURRENT
    if usable_points is not None and usable_points == 2:
        return DisplaySignalState.EARLY_TREND
    if not has_comparison:
        return DisplaySignalState.CURRENT
    if confidence == SignalConfidence.LOW:
        return DisplaySignalState.EARLY_TREND
    if usable_points is not None and minimum_trend_points is not None and usable_points < max(int(minimum_trend_points), 3):
        return DisplaySignalState.EARLY_TREND
    if confidence == SignalConfidence.HIGH:
        return DisplaySignalState.STABLE_TREND
    return DisplaySignalState.STABLE_TREND


def _derive_primary_label(label: SignalLabel, observed_value: float | None, state: DisplaySignalState) -> str:
    if state == DisplaySignalState.CURRENT:
        return "Current pace"
    if label == SignalLabel.BELOW_EXPECTED_PACE:
        return "Below expected pace"
    if label == SignalLabel.LOWER_THAN_RECENT_PACE:
        return "Lower than recent pace"
    if label == SignalLabel.INCONSISTENT_PACE:
        return "Inconsistent performance"
    if label == SignalLabel.IMPROVING_PACE:
        return "Improving pace"
    if label in {SignalLabel.FOLLOW_UP_OVERDUE, SignalLabel.FOLLOW_UP_DUE_TODAY, SignalLabel.UNRESOLVED_ISSUE}:
        return "Follow-up not completed"
    if label == SignalLabel.REPEATED_PATTERN:
        return "Repeated pattern"
    return "Not enough history yet"


def _meaningful_pattern_count(pattern_count: int | None) -> bool:
    return pattern_count is not None and int(pattern_count or 0) >= 2


def _normalize_pattern_window_label(pattern_count: int | None, pattern_window_label: str | None) -> str | None:
    if not _meaningful_pattern_count(pattern_count):
        return None
    clean_label = _clean_text(pattern_window_label)
    return clean_label or "this week"


def _pattern_supporting_line(pattern_count: int | None, pattern_window_label: str | None) -> str:
    if not _meaningful_pattern_count(pattern_count):
        return ""
    window_label = _normalize_pattern_window_label(pattern_count, pattern_window_label) or "this week"
    return f"Seen {int(pattern_count or 0)} times {window_label}"


def _normalize_supporting_text(
    *,
    supporting_text: list[str] | None,
    pattern_count: int | None,
    pattern_window_label: str | None,
) -> list[str]:
    pattern_line = _pattern_supporting_line(pattern_count, pattern_window_label)
    normalized: list[str] = []
    seen: set[str] = set()
    for line in list(supporting_text or []):
        text = " ".join(str(line or "").strip().split())
        lowered = text.lower()
        if not text:
            continue
        if "similar pattern" in lowered or "recurring issue" in lowered or "repeated decline" in lowered:
            continue
        if lowered.startswith("seen ") and " times " in lowered:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    if pattern_line:
        lowered_pattern = pattern_line.lower()
        if lowered_pattern not in seen:
            normalized.append(pattern_line)
    return normalized


def build_display_signal(
    *,
    employee_id: Any = "",
    employee_name: Any,
    process: Any,
    signal_label: Any,
    observed_date: Any,
    observed_value: Any = None,
    observed_unit: Any = "UPH",
    comparison_start_date: Any = None,
    comparison_end_date: Any = None,
    comparison_value: Any = None,
    pattern_count: Any = None,
    pattern_window_label: Any = None,
    state: Any = None,
    usable_points: Any = None,
    minimum_trend_points: Any = None,
    confidence: Any,
    data_completeness: Any = None,
    flags: dict[str, bool] | None = None,
    supporting_text: list[str] | None = None,
    delta_percent: Any = None,
    today: date | None = None,
) -> DisplaySignal:
    """Build a strict display signal and downgrade to low-data on invalid input."""
    today_value = today or date.today()

    clean_employee_id = _clean_text(employee_id)
    clean_employee = _clean_text(employee_name)
    clean_process = _clean_text(process)
    label = _coerce_signal_label(signal_label)
    obs_date = _safe_date(observed_date)
    obs_value = _safe_float(observed_value)
    comp_start = _safe_date(comparison_start_date)
    comp_end = _safe_date(comparison_end_date)
    comp_value = _safe_float(comparison_value)
    obs_unit = _clean_text(observed_unit)
    pattern_count_value = None
    try:
        if pattern_count is not None and str(pattern_count).strip() != "":
            pattern_count_value = int(pattern_count)
    except Exception:
        pattern_count_value = None
    try:
        usable_points_value = None if usable_points is None or str(usable_points).strip() == "" else int(usable_points)
    except Exception:
        usable_points_value = None
    try:
        minimum_trend_points_value = None if minimum_trend_points is None or str(minimum_trend_points).strip() == "" else int(minimum_trend_points)
    except Exception:
        minimum_trend_points_value = None
    pattern_window_text = _clean_text(pattern_window_label)
    delta_percent_value = _safe_float(delta_percent)
    conf = _coerce_confidence(confidence)
    completeness = _coerce_completeness(data_completeness)
    clean_flags = dict(flags or {})
    explicit_state = None
    try:
        if state is not None and str(state).strip():
            explicit_state = DisplaySignalState(str(getattr(state, "value", state)).strip().upper())
    except Exception:
        explicit_state = None

    had_any_comparison_input = any(
        value is not None
        for value in (comparison_start_date, comparison_end_date, comparison_value)
    )
    has_baseline_only = comp_value is not None and comp_start is None and comp_end is None
    has_full_dated_comparison = (
        comp_start is not None
        and comp_end is not None
        and comp_value is not None
        and obs_date is not None
        and comp_start <= comp_end < obs_date
    )
    has_date_hints_without_baseline = comp_value is None and (comp_start is not None or comp_end is not None)
    malformed_comparison_input = had_any_comparison_input and not (has_baseline_only or has_full_dated_comparison or has_date_hints_without_baseline)
    if malformed_comparison_input:
        return _downgrade_low_data(
            employee_id=clean_employee_id,
            employee_name=clean_employee,
            process=clean_process,
            observed_date=obs_date,
            flags=clean_flags,
            today=today_value,
        )

    if has_date_hints_without_baseline:
        comp_start = None
        comp_end = None

    has_valid_comparison = has_baseline_only or has_full_dated_comparison

    if clean_employee_id is None:
        clean_employee_id = _clean_text(clean_employee) or "unknown-employee"

    if clean_employee is None or clean_process is None or label is None or obs_date is None or conf is None:
        return _downgrade_low_data(
            employee_id=clean_employee_id,
            employee_name=clean_employee,
            process=clean_process,
            observed_date=obs_date,
            flags=clean_flags,
            today=today_value,
        )

    state = explicit_state or _derive_state_with_inputs(
        label=label,
        has_observed=obs_value is not None,
        has_comparison=has_valid_comparison,
        confidence=conf,
        pattern_count=pattern_count_value,
        usable_points=usable_points_value,
        minimum_trend_points=minimum_trend_points_value,
    )
    if state == DisplaySignalState.CURRENT:
        comp_start = None
        comp_end = None
        comp_value = None
    pattern_window_text = _normalize_pattern_window_label(pattern_count_value, pattern_window_text)
    normalized_supporting_text = _normalize_supporting_text(
        supporting_text=supporting_text,
        pattern_count=pattern_count_value,
        pattern_window_label=pattern_window_text,
    )
    primary_label = _derive_primary_label(label, obs_value, state)
    confidence_level = DisplayConfidenceLevel.LOW if state == DisplaySignalState.CURRENT else DisplayConfidenceLevel[str(conf.value).upper()]
    is_low_data = state == DisplaySignalState.LOW_DATA or (state == DisplaySignalState.CURRENT and obs_value is not None and usable_points_value is not None and usable_points_value < 3)
    is_new_employee = bool(clean_flags.get("new_employee") or clean_flags.get("is_new_employee"))
    is_actionable = state in {DisplaySignalState.CURRENT, DisplaySignalState.EARLY_TREND, DisplaySignalState.STABLE_TREND, DisplaySignalState.PATTERN} and label != SignalLabel.IMPROVING_PACE

    try:
        return DisplaySignal(
            employee_id=clean_employee_id,
            employee_name=clean_employee,
            process=clean_process,
            state=state,
            primary_label=primary_label,
            signal_label=label,
            observed_date=obs_date,
            observed_value=obs_value,
            observed_unit=obs_unit or "UPH",
            comparison_start_date=comp_start,
            comparison_end_date=comp_end,
            comparison_value=comp_value,
            pattern_count=pattern_count_value,
            pattern_window_label=pattern_window_text,
            confidence_level=confidence_level,
            confidence=conf,
            is_low_data=is_low_data,
            is_new_employee=is_new_employee,
            is_actionable=is_actionable,
            supporting_text=normalized_supporting_text,
            delta_percent=delta_percent_value,
            data_completeness=completeness,
            flags=clean_flags,
        )
    except ValueError:
        return _downgrade_low_data(
            employee_id=clean_employee_id,
            employee_name=clean_employee,
            process=clean_process,
            observed_date=obs_date,
            flags=clean_flags,
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

    resolved_label = label_map.get(str(card.insight_kind or ""), SignalLabel.LOW_DATA)

    return build_display_signal(
        employee_id=metadata.get("employee_id") or card.drill_down.entity_id or metadata.get("employee_name") or "unknown-employee",
        employee_name=metadata.get("employee_name") or card.drill_down.entity_id or "Unknown employee",
        process=metadata.get("process_name") or card.workload_context.impacted_group_label or "Unassigned",
        signal_label=resolved_label.value,
        observed_date=observed_date,
        observed_value=card.workload_context.observed_volume,
        comparison_start_date=comparison_start,
        comparison_end_date=comparison_end,
        comparison_value=card.workload_context.baseline_volume,
        pattern_count=metadata.get("repeat_count"),
        pattern_window_label=metadata.get("pattern_window_label"),
        state=metadata.get("signal_state"),
        usable_points=card.confidence.sample_size,
        minimum_trend_points=card.confidence.minimum_expected_points,
        confidence=confidence,
        data_completeness=completeness,
        flags={
            "repeat": int(metadata.get("repeat_count") or 0) > 0,
            "overdue": str(metadata.get("queue_status") or "").lower() == "overdue",
            "due_today": str(metadata.get("queue_status") or "").lower() == "due_today",
            "is_new_employee": bool(metadata.get("is_new_employee") or False),
        },
        supporting_text=[
            str(card.what_happened or ""),
            str(card.compared_to_what or ""),
            str(card.why_flagged or ""),
        ],
        delta_percent=metadata.get("change_pct"),
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

    comparison_value = None
    for candidate in (
        snapshot.get("prior_average_uph"),
        snapshot.get("prior_avg_uph"),
        snapshot.get("expected_uph"),
        snapshot.get("Target UPH"),
    ):
        parsed = _safe_float(candidate)
        if parsed is not None and parsed > 0:
            comparison_value = parsed
            break

    usable_points = (
        snapshot.get("sample_size")
        or snapshot.get("included_rows")
        or snapshot.get("included_day_count")
        or snapshot.get("Record Count")
        or snapshot.get("record_count")
        or (len(comp_dates) + (1 if snapshot.get("recent_average_uph") is not None or snapshot.get("Average UPH") is not None else 0))
    )

    return build_display_signal(
        employee_id=item.employee_id,
        employee_name=item.employee_id,
        process=item.process_name or snapshot.get("Department") or "Unassigned",
        signal_label=label.value,
        observed_date=observed_date,
        observed_value=snapshot.get("recent_average_uph") if snapshot.get("recent_average_uph") is not None else snapshot.get("Average UPH"),
        comparison_start_date=comparison_start,
        comparison_end_date=comparison_end,
        comparison_value=comparison_value,
        pattern_count=snapshot.get("repeat_count"),
        pattern_window_label=snapshot.get("pattern_window_label"),
        state=snapshot.get("signal_state"),
        usable_points=usable_points,
        minimum_trend_points=snapshot.get("minimum_expected_points") or 3,
        confidence=snapshot.get("confidence_label") or "low",
        data_completeness=snapshot.get("data_completeness_status") or snapshot.get("completeness"),
        flags={
            "repeat": int(snapshot.get("repeat_count") or 0) > 0,
            "overdue": queue_status == "overdue",
            "due_today": queue_status == "due_today",
            "is_new_employee": bool(snapshot.get("is_new_employee") or False),
        },
        supporting_text=[
            str(item.attention_summary or ""),
            str((item.attention_reasons or [""])[0] or ""),
        ],
        delta_percent=snapshot.get("change_pct"),
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
    pattern_history = dict(detail_context.get("pattern_history") or {})
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

    trailing_dates = list((detail_context.get("contributing_periods") or {}).get("trailing_dates") or [])
    trailing_last = trailing_dates[-1] if trailing_dates else None
    observed_date = _safe_date(trailing_last) or (today_value - timedelta(days=1))

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
    if comparison_value in {None, 0, 0.0}:
        target_context = dict(detail_context.get("target_context") or {})
        target_uph = _safe_float(target_context.get("target_uph"))
        if target_uph is not None and target_uph > 0 and observed_value is not None:
            comparison_value = target_uph

    compared_to_what = str(
        detail_context.get("compared_to_what")
        or summary.get("compared_to_what")
        or (detail_context.get("what_this_is_based_on") or {}).get("compared_to_what")
        or ""
    )

    return build_display_signal(
        employee_id=detail_context.get("employee_id") or employee_name,
        employee_name=employee_name,
        process=process,
        signal_label=label.value,
        observed_date=observed_date,
        observed_value=observed_value,
        comparison_start_date=comparison_start,
        comparison_end_date=comparison_end,
        comparison_value=comparison_value,
        pattern_count=pattern_history.get("repeat_count"),
        pattern_window_label=pattern_history.get("window_label"),
        state=detail_context.get("signal_state") or summary.get("signal_state"),
        usable_points=len(trailing_dates) if trailing_dates else (1 if observed_value is not None else 0),
        minimum_trend_points=summary.get("minimum_expected_points") or 3,
        confidence=detail_context.get("confidence_label") or summary.get("confidence_label") or "low",
        data_completeness=summary.get("data_completeness_label") or detail_context.get("data_completeness_label") or "unknown",
        flags={
            "repeat": bool(pattern_history.get("has_pattern") or pattern_history.get("pattern_detected")),
            "is_new_employee": bool(detail_context.get("is_new_employee") or False),
        },
        supporting_text=[
            str((detail_context.get("why_this_is_showing") or {}).get("why_now") or ""),
            compared_to_what,
        ],
        delta_percent=(detail_context.get("signal_summary") or {}).get("delta_percent"),
        today=today_value,
    )
