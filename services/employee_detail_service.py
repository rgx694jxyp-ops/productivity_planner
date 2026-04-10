"""Trust-first explanation context builder for Employee Detail drill-down."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _parse_date(value: Any) -> date | None:
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


def _emp_id(row: dict) -> str:
    raw = str(row.get("emp_id") or row.get("EmployeeID") or row.get("employee_id") or row.get("Employee") or "").strip()
    return raw[:-2] if raw.endswith(".0") and raw[:-2].isdigit() else raw


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _uph(row: dict) -> float:
    for candidate in (row.get("uph"), row.get("UPH"), row.get("Average UPH")):
        out = _safe_float(candidate)
        if out > 0:
            return out
    return 0.0


def _units(row: dict) -> float:
    for candidate in (row.get("units"), row.get("Units"), row.get("Total Units")):
        out = _safe_float(candidate)
        if out >= 0:
            return out
    return 0.0


def _hours(row: dict) -> float:
    for candidate in (row.get("hours_worked"), row.get("Hours"), row.get("Hours Worked")):
        out = _safe_float(candidate)
        if out >= 0:
            return out
    return 0.0


def _confidence_label(coverage_ratio: float, included_count: int) -> str:
    if coverage_ratio >= 0.7 and included_count >= 7:
        return "High"
    if coverage_ratio >= 0.4 and included_count >= 4:
        return "Medium"
    return "Low"


def build_employee_detail_context(
    *,
    emp_id: str,
    goal_row: dict,
    history_rows: list[dict],
    lookback_days: int = 14,
    comparison_days: int = 5,
) -> dict:
    employee_history = [row for row in (history_rows or []) if _emp_id(row) == str(emp_id or "")]
    mapped_rows: list[dict] = []
    excluded_rows: list[dict] = []
    for row in employee_history:
        row_date = _parse_date(row.get("work_date") or row.get("Date") or row.get("date") or row.get("Week"))
        uph = _uph(row)
        units = _units(row)
        hours = _hours(row)
        if not row_date:
            excluded_rows.append({"date": "", "reason": "Missing/invalid date", "uph": uph, "units": units, "hours": hours})
            continue
        if uph <= 0:
            excluded_rows.append({"date": row_date.isoformat(), "reason": "Missing/invalid UPH", "uph": uph, "units": units, "hours": hours})
            continue
        mapped_rows.append({"date": row_date, "uph": uph, "units": units, "hours": hours, "raw": row})

    mapped_rows.sort(key=lambda item: item["date"])
    trend_rows = mapped_rows[-lookback_days:]
    trailing_rows = trend_rows[-comparison_days:]
    prior_rows = trend_rows[-(comparison_days * 2):-comparison_days] if len(trend_rows) > comparison_days else []

    trailing_avg = round(sum(row["uph"] for row in trailing_rows) / len(trailing_rows), 2) if trailing_rows else 0.0
    prior_avg = round(sum(row["uph"] for row in prior_rows) / len(prior_rows), 2) if prior_rows else 0.0

    goal_status = str(goal_row.get("goal_status") or "").strip().lower()
    trend = str(goal_row.get("trend") or "").strip().lower()
    target_uph = _safe_float(goal_row.get("Target UPH"))
    current_uph = _safe_float(goal_row.get("Average UPH")) if _safe_float(goal_row.get("Average UPH")) > 0 else trailing_avg

    if target_uph > 0 and current_uph < target_uph:
        current_state = "below expected pace"
    elif target_uph > 0 and current_uph >= target_uph:
        current_state = "at or above expected pace"
    else:
        current_state = "pace status available with limited target context"

    compared_to_what = (
        f"Compared with the latest {comparison_days} comparable days"
        + (f" versus the prior {comparison_days} comparable days" if prior_rows else " (prior window not yet complete)")
        + (f" and target {target_uph:.1f} UPH" if target_uph > 0 else "")
    )

    trigger_parts: list[str] = []
    if goal_status:
        trigger_parts.append(f"goal status marked as {goal_status.replace('_', ' ')}")
    if trend:
        trigger_parts.append(f"trend marked as {trend}")
    if trailing_rows:
        trigger_parts.append("recent activity/follow-through entries exist for this employee")
    trigger_text = "; ".join(trigger_parts) if trigger_parts else "employee drill-down selected"

    coverage_ratio = round(len(trend_rows) / float(lookback_days), 2) if lookback_days > 0 else 0.0
    completeness_note = (
        f"{len(trend_rows)} included and {len(excluded_rows)} excluded records in the latest {lookback_days}-day window"
        f" (coverage {int(coverage_ratio * 100)}%)."
    )

    confidence_label = _confidence_label(coverage_ratio, len(trend_rows))

    if trailing_rows and prior_rows:
        delta = round(trailing_avg - prior_avg, 2)
        if delta >= 1.0:
            before_after_label = "improved compared to prior period"
        elif target_uph > 0 and trailing_avg < target_uph:
            before_after_label = "still below expected"
        else:
            before_after_label = "no clear change yet"
    else:
        delta = 0.0
        before_after_label = "no clear change yet"

    def _avg(items: list[dict], key: str) -> float:
        if not items:
            return 0.0
        return round(sum(float(item.get(key) or 0.0) for item in items) / len(items), 2)

    trailing_units = _avg(trailing_rows, "units")
    trailing_hours = _avg(trailing_rows, "hours")
    prior_units = _avg(prior_rows, "units")
    prior_hours = _avg(prior_rows, "hours")

    has_workload = bool((trailing_units > 0 or trailing_hours > 0) and (prior_units > 0 or prior_hours > 0))
    workload_context = (
        f"Trailing window average workload: {trailing_units:.1f} units / {trailing_hours:.1f} hours; "
        f"prior window: {prior_units:.1f} units / {prior_hours:.1f} hours."
        if has_workload
        else "Workload/volume context is limited because units/hours fields are incomplete in one or both windows."
    )

    trend_points = [
        {
            "Date": row["date"].isoformat(),
            "UPH": round(float(row["uph"]), 2),
            "Target UPH": round(target_uph, 2) if target_uph > 0 else None,
            "Included": "Included",
        }
        for row in trend_rows
    ]

    included_records = [
        {
            "Date": row["date"].isoformat(),
            "UPH": round(float(row["uph"]), 2),
            "Units": round(float(row["units"]), 2),
            "Hours": round(float(row["hours"]), 2),
        }
        for row in trend_rows
    ]

    excluded_records = excluded_rows[-lookback_days:]

    return {
        "current_state": current_state,
        "compared_to_what": compared_to_what,
        "confidence_label": confidence_label,
        "data_completeness_note": completeness_note,
        "what_happened": f"Current observed pace is {current_uph:.1f} UPH." if current_uph > 0 else "Current pace is not fully available.",
        "why_showing": f"This appears because {trigger_text}.",
        "comparison_logic": (
            f"Deterministic comparison uses the latest {comparison_days} included days versus the prior {comparison_days} included days, "
            "with no manual overrides."
        ),
        "timeframe_used": f"Latest {lookback_days} calendar days with valid records for this employee.",
        "baseline_used": (f"Target baseline: {target_uph:.1f} UPH." if target_uph > 0 else "No target baseline is currently set."),
        "workload_context": workload_context,
        "missing_data_note": (
            "Excluded records are shown in drill-down for transparency."
            if excluded_records
            else "No excluded records in the current lookback window."
        ),
        "before_after_summary": {
            "label": before_after_label,
            "trailing_avg_uph": trailing_avg,
            "prior_avg_uph": prior_avg,
            "delta_uph": delta,
            "trailing_days": len(trailing_rows),
            "prior_days": len(prior_rows),
        },
        "trend_points": trend_points,
        "contributing_periods": {
            "trailing_dates": [row["date"].isoformat() for row in trailing_rows],
            "prior_dates": [row["date"].isoformat() for row in prior_rows],
        },
        "included_records": included_records,
        "excluded_records": excluded_records,
    }
