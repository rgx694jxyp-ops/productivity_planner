"""Trust-first explanation context builder for Employee Detail drill-down."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from services.plain_language_service import describe_trend
from services.signal_pattern_memory_service import detect_pattern_memory_from_goal_row
from services.signal_interpretation_service import (
    derive_confidence_from_coverage_policy,
    format_comparison_window,
    format_observed_label,
)
from services.target_service import build_comparison_descriptions, resolve_target_context
from services.trend_classification_service import classify_trend_state, normalize_trend_state


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
    confidence = derive_confidence_from_coverage_policy(
        coverage_ratio=coverage_ratio,
        included_count=included_count,
        high_min_coverage=0.7,
        high_min_count=7,
        medium_min_coverage=0.4,
        medium_min_count=4,
        allow_high=True,
    )
    return str(confidence.level or "low").title()


def _completeness_label(coverage_ratio: float, included_count: int) -> str:
    if coverage_ratio >= 0.7 and included_count >= 7:
        return "Data mostly complete"
    if coverage_ratio >= 0.4 and included_count >= 4:
        return "Partial data"
    return "Limited data"


def _source_value(raw: dict, *keys: str) -> str:
    for key in keys:
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return ""


def _name_from_goal_row(goal_row: dict, fallback: str) -> str:
    for key in ("Employee", "Employee Name", "employee_name", "name"):
        value = str(goal_row.get(key) or "").strip()
        if value:
            return value
    return fallback


def _build_reference_today(trend_rows: list[dict]) -> date:
    if trend_rows:
        latest = max((row.get("date") for row in trend_rows if isinstance(row.get("date"), date)), default=None)
        if latest is not None:
            return latest + timedelta(days=1)
    return date.today()


def _build_source_references(*, included_rows: list[dict], excluded_rows: list[dict]) -> list[dict]:
    references: list[dict] = []
    seen_keys: set[tuple[str, str, str, str, str]] = set()

    for label, rows in (("Included", included_rows), ("Excluded", excluded_rows)):
        for row in rows:
            raw = row.get("raw") or {}
            source_file = _source_value(raw, "source_file", "Source File", "filename", "import_file")
            import_job_id = _source_value(raw, "import_job_id", "job_id", "import_job", "Import Job")
            upload_id = _source_value(raw, "upload_id", "source_upload_id", "import_upload_id")
            upload_name = _source_value(raw, "upload_name", "source_upload_name")
            if not any((source_file, import_job_id, upload_id, upload_name)):
                continue
            row_date = ""
            if isinstance(row.get("date"), date):
                row_date = row["date"].isoformat()
            else:
                row_date = str(row.get("date") or "")
            dedupe_key = (label, row_date, source_file, import_job_id, upload_id or upload_name)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            references.append(
                {
                    "Date": row_date,
                    "Included": label,
                    "Source File": source_file,
                    "Import Job": import_job_id,
                    "Upload": upload_name or upload_id,
                }
            )

    references.sort(key=lambda item: (str(item.get("Date") or ""), str(item.get("Included") or "")), reverse=True)
    return references[:12]


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
            excluded_rows.append({"date": "", "reason": "Missing/invalid date", "uph": uph, "units": units, "hours": hours, "raw": row})
            continue
        if uph <= 0:
            excluded_rows.append({"date": row_date.isoformat(), "reason": "Missing/invalid UPH", "uph": uph, "units": units, "hours": hours, "raw": row})
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
    snapshot_trend_state = normalize_trend_state(goal_row.get("trend") or "")
    employee_name = _name_from_goal_row(goal_row, str(emp_id or "Employee"))
    process_name = str(goal_row.get("Resolved Process") or goal_row.get("Department") or goal_row.get("department") or "Team")
    target_context = resolve_target_context(
        employee_id=emp_id,
        process_name=process_name,
        explicit_target=_safe_float(goal_row.get("Target UPH")),
    )
    target_uph = _safe_float(target_context.get("target_uph"))
    current_uph = _safe_float(goal_row.get("Average UPH")) if _safe_float(goal_row.get("Average UPH")) > 0 else trailing_avg
    comparison_descriptions = build_comparison_descriptions(
        target_context=target_context,
        comparison_days=comparison_days,
        recent_avg=trailing_avg,
        prior_avg=prior_avg,
    )

    compared_to_what = (
        f"Compared with the latest {comparison_days} comparable days"
        + (f" versus the prior {comparison_days} comparable days" if prior_rows else " (prior window not yet complete)")
        + (f", plus target {target_uph:.1f} UPH from the {target_context.get('target_source_label', 'configured target')}" if target_uph > 0 else "")
    )

    coverage_ratio = round(len(trend_rows) / float(lookback_days), 2) if lookback_days > 0 else 0.0
    computed_confidence_label = _confidence_label(coverage_ratio, len(trend_rows))
    snapshot_confidence_label = str(goal_row.get("confidence_label") or "").strip().title()
    confidence_label = snapshot_confidence_label if snapshot_confidence_label in {"Low", "Medium", "High"} else computed_confidence_label

    computed_completeness_label = _completeness_label(coverage_ratio, len(trend_rows))
    snapshot_completeness_label = str(goal_row.get("data_completeness_status") or "").strip().lower()
    completeness_label = snapshot_completeness_label if snapshot_completeness_label in {"complete", "partial", "limited", "unknown"} else computed_completeness_label

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

    trend_result = classify_trend_state(
        recent_average_uph=trailing_avg if trailing_avg > 0 else current_uph,
        prior_average_uph=prior_avg,
        expected_uph=target_uph,
        included_count=len(trend_rows),
        recent_values=[float(row.get("uph") or 0.0) for row in trailing_rows if float(row.get("uph") or 0.0) > 0],
    )
    resolved_trend_state = str(trend_result.get("state") or "").strip().lower()
    if resolved_trend_state == "insufficient_data" and snapshot_trend_state != "insufficient_data":
        resolved_trend_state = snapshot_trend_state
    current_state = str(describe_trend(resolved_trend_state) or "Worth review").strip()

    completeness_note = (
        f"{completeness_label}: {len(trend_rows)} included and {len(excluded_rows)} excluded records in the latest {lookback_days}-day window"
        f" (coverage {int(coverage_ratio * 100)}%)."
    )

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

    if resolved_trend_state == "below_expected" and target_uph > 0 and current_uph > 0:
        trigger_reason = f"Recent observed pace is {current_uph:.1f} UPH versus {target_uph:.1f} UPH from the {target_context.get('target_source_label', 'configured target')}."
    elif resolved_trend_state == "improving" and prior_rows:
        trigger_reason = f"Recent average moved by {delta:+.1f} UPH versus the prior comparable window."
    elif resolved_trend_state == "declining" and prior_rows:
        trigger_reason = f"Recent average moved by {delta:+.1f} UPH versus the prior comparable window."
    elif resolved_trend_state == "inconsistent":
        trigger_reason = f"Recent comparable days vary by {float(trend_result.get('volatility_span_uph') or 0):.1f} UPH, so the pattern is not steady yet."
    else:
        trigger_reason = str(trend_result.get("plain_explanation") or goal_row.get("trend_explanation") or "Recent comparable days look broadly similar to the prior context.")

    why_now_parts: list[str] = []
    if goal_status:
        why_now_parts.append(f"the latest goal status is {goal_status.replace('_', ' ')}")
    if trend:
        why_now_parts.append(f"recent direction is {trend}")
    if trailing_rows:
        why_now_parts.append(f"{len(trailing_rows)} recent comparable day(s) are available")
    why_now = (
        "Shown now because " + ", ".join(why_now_parts) + "."
        if why_now_parts
        else "Shown now because this employee drill-down has enough recent context to summarize."
    )

    pattern_memory = detect_pattern_memory_from_goal_row(row=goal_row or {})
    resolved_repeat_count = max(int(pattern_memory.repeat_count or 0), int(goal_row.get("repeat_count") or 0))
    pattern_history = {
        "has_pattern": bool(pattern_memory.pattern_detected) or resolved_repeat_count > 0,
        "summary": (
            pattern_memory.summary
            if pattern_memory.pattern_detected
            else "No repeated pattern is standing out in the recent trend context."
        ),
        "repeat_count": resolved_repeat_count,
        "pattern_kind": str(pattern_memory.pattern_kind or "none"),
        "evidence_points": list(pattern_memory.evidence_points or []),
    }

    trend_points = [
        {
            "Date": row["date"].isoformat(),
            "UPH": round(float(row["uph"]), 2),
            "Target UPH": round(target_uph, 2) if target_uph > 0 else None,
            "Included": "Included",
        }
        for row in trend_rows
    ]

    source_references = _build_source_references(included_rows=trend_rows, excluded_rows=excluded_rows)
    if target_uph > 0 and prior_rows:
        baseline_used = f"Configured target baseline: {target_uph:.1f} UPH from the {target_context.get('target_source_label', 'configured target')} plus the prior {comparison_days} comparable days."
    elif target_uph > 0:
        baseline_used = f"Configured target baseline: {target_uph:.1f} UPH from the {target_context.get('target_source_label', 'configured target')}. Prior comparison window is still limited."
    elif prior_rows:
        baseline_used = f"Baseline comes from the prior {comparison_days} comparable days because no configured target is set."
    else:
        baseline_used = "No configured target or complete prior baseline is currently available."

    has_minimum_context = bool(len(trend_rows) > 0)
    has_notable_signal = bool(
        (target_uph > 0 and current_uph > 0 and current_uph < target_uph)
        or delta >= 1.0
        or bool(trend_result.get("is_notable"))
        or pattern_history["has_pattern"]
    )
    if not has_minimum_context:
        healthy_state_message = "Waiting for enough recent comparable records to classify this employee confidently."
    else:
        healthy_state_message = "" if has_notable_signal else "No major changes in recent performance."

    observed_date = trailing_rows[-1]["date"] if trailing_rows else (trend_rows[-1]["date"] if trend_rows else None)
    comparison_dates = [row["date"] for row in prior_rows] or [row["date"] for row in trailing_rows]
    if observed_date:
        comparison_dates = [d for d in comparison_dates if isinstance(d, date) and d < observed_date]
    else:
        comparison_dates = []
    comparison_count = len(comparison_dates)
    today_ref = _build_reference_today(trend_rows)

    observed_label = format_observed_label(observed_date, today=today_ref)
    comparison_label = format_comparison_window(comparison_dates, comparison_count or None)
    has_observed_data = bool(observed_date and trailing_avg > 0)
    has_comparison_data = bool(comparison_dates and prior_avg > 0 and comparison_label)

    signal_state = ""
    summary_block = {
        "line_1": f"{employee_name} · {process_name}",
        "line_2": current_state,
        "line_3": f"Observed: {observed_label} ({trailing_avg:.1f})",
        "line_4": f"Compared to: {comparison_label} avg ({prior_avg:.1f})",
        "line_5": f"Confidence: {confidence_label}",
        "current_state": current_state,
        "trend_state": resolved_trend_state,
        "signal_state": signal_state,
        "trend_explanation": str(trend_result.get("plain_explanation") or goal_row.get("trend_explanation") or ""),
        "compared_to_what": compared_to_what,
        "confidence_label": confidence_label,
        "data_completeness_note": completeness_note,
        "data_completeness_label": completeness_label,
    }

    low_data_state = False
    if not has_observed_data:
        low_data_state = True
        signal_state = "LOW_DATA"
        summary_block.update(
            {
                "line_1": "",
                "line_2": "Not enough history yet",
                "line_3": "",
                "line_4": "",
                "line_5": "Confidence: Low",
                "signal_state": signal_state,
                "low_data_state": True,
                "low_data_note": "No recent performance data",
            }
        )
    elif not has_comparison_data:
        if target_uph > 0 and confidence_label in {"Medium", "High"}:
            signal_state = "STABLE_TREND" if confidence_label == "High" else "EARLY_TREND"
        summary_block.update(
            {
                "signal_state": signal_state,
                "line_2": current_state,
                "line_3": f"Observed: {observed_label}",
                "line_4": "",
                "line_5": f"Confidence: {confidence_label}",
                "low_data_state": False,
                "low_data_note": "No comparison available",
            }
        )

    why_this_is_showing = {
        "trigger": trigger_reason,
        "comparison_used": compared_to_what,
        "why_now": why_now,
        "comparison_breakdown": comparison_descriptions,
    }

    what_this_is_based_on = {
        "timeframe_used": f"Latest {lookback_days} calendar days with valid records for this employee; primary comparison uses up to {comparison_days} recent included days.",
        "baseline_used": baseline_used,
        "workload_context": workload_context,
        "missing_data_note": (
            "Excluded records are shown in drill-down for transparency."
            if excluded_rows
            else "No excluded records in the current lookback window."
        ),
        "comparison_breakdown": comparison_descriptions,
    }

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
        "signal_summary": summary_block,
        "why_this_is_showing": why_this_is_showing,
        "what_this_is_based_on": what_this_is_based_on,
        "current_state": current_state,
        "signal_state": signal_state,
        "compared_to_what": compared_to_what,
        "confidence_label": confidence_label,
        "data_completeness_note": completeness_note,
        "data_completeness_label": completeness_label,
        "what_happened": f"Current observed pace is {current_uph:.1f} UPH." if current_uph > 0 else "Current pace is not fully available.",
        "why_showing": why_now,
        "comparison_logic": (
            f"Deterministic comparison uses the latest {comparison_days} included days versus the prior {comparison_days} included days, "
            "with no manual overrides."
        ),
        "comparison_breakdown": comparison_descriptions,
        "target_context": target_context,
        "trend_state": resolved_trend_state,
        "trend_explanation": str(trend_result.get("plain_explanation") or goal_row.get("trend_explanation") or ""),
        "timeframe_used": what_this_is_based_on["timeframe_used"],
        "baseline_used": baseline_used,
        "workload_context": workload_context,
        "missing_data_note": what_this_is_based_on["missing_data_note"],
        "before_after_summary": {
            "label": before_after_label,
            "trailing_avg_uph": trailing_avg,
            "prior_avg_uph": prior_avg,
            "delta_uph": delta,
            "trailing_days": len(trailing_rows),
            "prior_days": len(prior_rows),
        },
        "pattern_history": pattern_history,
        "healthy_state_message": healthy_state_message,
        "has_minimum_context": has_minimum_context,
        "has_notable_signal": has_notable_signal,
        "trend_points": trend_points,
        "contributing_periods": {
            "trailing_dates": [row["date"].isoformat() for row in trailing_rows],
            "prior_dates": [row["date"].isoformat() for row in prior_rows],
        },
        "included_records": included_records,
        "excluded_records": excluded_records,
        "source_references": source_references,
        "low_data_state": bool(summary_block.get("low_data_state")),
        "low_data_note": str(summary_block.get("low_data_note") or ""),
    }
