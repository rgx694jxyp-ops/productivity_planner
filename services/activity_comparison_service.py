"""Deterministic before/after comparisons tied to logged activity."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from repositories import action_events_repo
from services.target_service import build_comparison_descriptions

COMPARABLE_ACTIVITY_EVENT_TYPES: set[str] = {
    "coached",
    "follow_up_logged",
    "follow_through_logged",
    "recognized",
}


def _parse_iso_date(value: Any) -> date | None:
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


def _extract_history_emp_id(row: dict) -> str:
    raw = str(
        row.get("emp_id")
        or row.get("EmployeeID")
        or row.get("employee_id")
        or row.get("Employee")
        or ""
    ).strip()
    return raw[:-2] if raw.endswith(".0") and raw[:-2].isdigit() else raw


def _extract_history_date(row: dict) -> date | None:
    return _parse_iso_date(row.get("work_date") or row.get("Date") or row.get("date") or row.get("Week"))


def _extract_history_uph(row: dict) -> float:
    candidates = [row.get("uph"), row.get("UPH"), row.get("Average UPH")]
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def _extract_history_units(row: dict) -> float:
    candidates = [row.get("units"), row.get("Units"), row.get("Total Units")]
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return 0.0


def _extract_history_hours(row: dict) -> float:
    candidates = [row.get("hours_worked"), row.get("Hours"), row.get("Hours Worked")]
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return 0.0


def _window_stats(history_rows: list[dict], employee_id: str, start_date: date, end_date: date) -> dict:
    values: list[float] = []
    matched_dates: list[str] = []
    units_values: list[float] = []
    hours_values: list[float] = []
    workload_rows = 0
    for row in history_rows or []:
        if _extract_history_emp_id(row) != str(employee_id or ""):
            continue
        row_date = _extract_history_date(row)
        if not row_date or row_date < start_date or row_date > end_date:
            continue
        uph = _extract_history_uph(row)
        if uph <= 0:
            continue
        values.append(uph)
        matched_dates.append(row_date.isoformat())
        units = _extract_history_units(row)
        hours = _extract_history_hours(row)
        if units > 0 or hours > 0:
            workload_rows += 1
            units_values.append(units)
            hours_values.append(hours)

    avg = round(sum(values) / len(values), 2) if values else None
    units_avg = round(sum(units_values) / len(units_values), 2) if units_values else None
    hours_avg = round(sum(hours_values) / len(hours_values), 2) if hours_values else None
    return {
        "count": len(values),
        "avg": avg,
        "dates": matched_dates,
        "units_avg": units_avg,
        "hours_avg": hours_avg,
        "workload_rows": workload_rows,
    }


def _comparison_confidence(before_count: int, after_count: int) -> str:
    if before_count >= 3 and after_count >= 3:
        return "High"
    if before_count >= 2 and after_count >= 2:
        return "Medium"
    return "Low"


def compare_logged_activity(
    activity_row: dict,
    *,
    history_rows: list[dict],
    expected_uph: float = 0.0,
    window_days: int = 7,
    min_points_per_side: int = 2,
    min_absolute_change: float = 1.0,
    relative_change_threshold: float = 0.03,
) -> dict:
    employee_id = str(activity_row.get("employee_id") or "").strip()
    activity_date = _parse_iso_date(activity_row.get("event_at") or activity_row.get("created_at"))
    if not employee_id or not activity_date:
        return {}

    before_stats = _window_stats(
        history_rows,
        employee_id,
        activity_date - timedelta(days=window_days),
        activity_date - timedelta(days=1),
    )
    after_stats = _window_stats(
        history_rows,
        employee_id,
        activity_date + timedelta(days=1),
        activity_date + timedelta(days=window_days),
    )

    before_avg = before_stats.get("avg")
    after_avg = after_stats.get("avg")
    before_count = int(before_stats.get("count") or 0)
    after_count = int(after_stats.get("count") or 0)
    confidence = _comparison_confidence(before_count, after_count)
    before_coverage_ratio = round(before_count / float(window_days), 2) if window_days > 0 else 0.0
    after_coverage_ratio = round(after_count / float(window_days), 2) if window_days > 0 else 0.0
    combined_coverage_ratio = min(before_coverage_ratio, after_coverage_ratio)
    threshold = max(min_absolute_change, abs(float(before_avg or 0.0)) * relative_change_threshold)
    delta = round(float(after_avg or 0.0) - float(before_avg or 0.0), 2) if before_avg is not None and after_avg is not None else None
    before_units_avg = before_stats.get("units_avg")
    after_units_avg = after_stats.get("units_avg")
    before_hours_avg = before_stats.get("hours_avg")
    after_hours_avg = after_stats.get("hours_avg")
    workload_available = bool((before_stats.get("workload_rows") or 0) and (after_stats.get("workload_rows") or 0))

    if before_count < min_points_per_side or after_count < min_points_per_side:
        outcome_key = "no_clear_change_yet"
        outcome_label = "No clear change yet"
        why_shown = "Shown because a logged activity exists, but there are not enough comparable days on both sides yet."
    elif expected_uph > 0 and after_avg is not None and after_avg < expected_uph:
        outcome_key = "still_below_expected"
        outcome_label = "Still below expected"
        why_shown = "Shown because there is enough post-log data and the recent average remains below the current expected pace."
    elif delta is not None and delta >= threshold:
        outcome_key = "improved_compared_to_prior_period"
        outcome_label = "Improved compared to prior period"
        why_shown = "Shown because the post-log average is deterministically higher than the comparable pre-log period."
    else:
        outcome_key = "no_clear_change_yet"
        outcome_label = "No clear change yet"
        why_shown = "Shown because the post-log average looks similar to the prior period within the fixed comparison threshold."

    compared_to_what = (
        f"Compared with the {window_days}-day period before the log date versus the {window_days}-day period after it."
    )
    comparison_breakdown = build_comparison_descriptions(
        target_context={
            "target_uph": expected_uph,
            "target_source_label": "resolved target",
            "process_name": "",
        },
        comparison_days=window_days,
        recent_avg=float(after_avg or 0.0),
        prior_avg=float(before_avg or 0.0),
    )
    evidence_parts = [
        f"Before: {before_avg:.1f} UPH across {before_count} day(s)" if before_avg is not None else f"Before: {before_count} comparable day(s)",
        f"After: {after_avg:.1f} UPH across {after_count} day(s)" if after_avg is not None else f"After: {after_count} comparable day(s)",
    ]
    if expected_uph > 0:
        evidence_parts.append(f"Expected: {expected_uph:.1f} UPH")

    if workload_available:
        workload_context = (
            f"Workload context: before {float(before_units_avg or 0):.1f} units / {float(before_hours_avg or 0):.1f} hours, "
            f"after {float(after_units_avg or 0):.1f} units / {float(after_hours_avg or 0):.1f} hours."
        )
    else:
        workload_context = "Workload context: insufficient units/hours fields in one or both periods."

    completeness_note = (
        f"Data completeness: {before_count}/{window_days} pre days and {after_count}/{window_days} post days with valid UPH "
        f"(coverage {int(combined_coverage_ratio * 100)}%)."
    )
    is_weak_signal = confidence == "Low" or combined_coverage_ratio < 0.4

    return {
        "employee_id": employee_id,
        "activity_date": activity_date.isoformat(),
        "event_type": str(activity_row.get("event_type") or "logged_activity"),
        "details": str(activity_row.get("details") or activity_row.get("notes") or "Logged activity").strip(),
        "owner": str(activity_row.get("owner") or activity_row.get("performed_by") or "").strip(),
        "linked_exception_id": activity_row.get("linked_exception_id"),
        "outcome_key": outcome_key,
        "outcome_label": outcome_label,
        "what_happened": f"A logged activity was recorded on {activity_date.isoformat()}.",
        "compared_to_what": compared_to_what,
        "comparison_breakdown": comparison_breakdown,
        "why_shown": why_shown,
        "confidence_label": confidence,
        "data_supports": " | ".join(evidence_parts),
        "time_context": f"Log date: {activity_date.isoformat()} with fixed {window_days}-day pre/post comparison windows.",
        "workload_context": workload_context,
        "data_completeness_note": completeness_note,
        "is_weak_signal": is_weak_signal,
        "before_avg_uph": before_avg,
        "after_avg_uph": after_avg,
        "expected_uph": round(expected_uph, 2) if expected_uph else 0.0,
        "before_count": before_count,
        "after_count": after_count,
        "before_coverage_ratio": before_coverage_ratio,
        "after_coverage_ratio": after_coverage_ratio,
        "delta_uph": delta,
        "before_dates": before_stats.get("dates") or [],
        "after_dates": after_stats.get("dates") or [],
        "before_units_avg": before_units_avg,
        "after_units_avg": after_units_avg,
        "before_hours_avg": before_hours_avg,
        "after_hours_avg": after_hours_avg,
    }


def list_recent_activity_comparisons(
    *,
    tenant_id: str,
    history_rows: list[dict],
    expected_uph_by_employee: dict[str, float] | None = None,
    employee_id: str = "",
    per_employee_latest_only: bool = False,
    include_weak_signals: bool = True,
    limit: int = 6,
) -> list[dict]:
    expected_uph_by_employee = expected_uph_by_employee or {}
    rows = action_events_repo.list_action_events(
        action_id="",
        tenant_id=tenant_id,
        employee_id=employee_id,
        limit=max(limit * 8, 80),
        newest_first=True,
    )
    results: list[dict] = []
    seen_employee_ids: set[str] = set()
    for row in rows:
        event_type = str(row.get("event_type") or "")
        emp_id = str(row.get("employee_id") or "").strip()
        if event_type not in COMPARABLE_ACTIVITY_EVENT_TYPES or not emp_id:
            continue
        if per_employee_latest_only and emp_id in seen_employee_ids:
            continue
        comparison = compare_logged_activity(
            row,
            history_rows=history_rows,
            expected_uph=float(expected_uph_by_employee.get(emp_id) or 0.0),
        )
        if not comparison:
            continue
        if per_employee_latest_only and comparison.get("confidence_label") == "Low":
            continue
        if not include_weak_signals and bool(comparison.get("is_weak_signal")):
            continue
        results.append(comparison)
        seen_employee_ids.add(emp_id)
        if len(results) >= limit:
            break
    return results


def summarize_activity_comparisons(comparisons: list[dict]) -> dict:
    counts = {
        "improved_compared_to_prior_period": 0,
        "no_clear_change_yet": 0,
        "still_below_expected": 0,
    }
    for comparison in comparisons or []:
        key = str(comparison.get("outcome_key") or "no_clear_change_yet")
        counts[key] = counts.get(key, 0) + 1
    return {
        "total_count": len(comparisons or []),
        "improved_count": counts.get("improved_compared_to_prior_period", 0),
        "no_clear_change_count": counts.get("no_clear_change_yet", 0),
        "still_below_expected_count": counts.get("still_below_expected", 0),
    }