"""Team/process interpreted summary builder for systemic-vs-isolated drill-down."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from services.signal_pattern_memory_service import detect_pattern_memory_from_goal_row
from services.target_service import build_comparison_descriptions, normalize_process_name, resolve_target_context
from services.trend_classification_service import normalize_trend_state


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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


def _employee_id(row: dict) -> str:
    raw = str(row.get("EmployeeID") or row.get("emp_id") or row.get("employee_id") or "").strip()
    return raw[:-2] if raw.endswith(".0") and raw[:-2].isdigit() else raw


def _process_key(row: dict) -> str:
    return normalize_process_name(str(
        row.get("Department")
        or row.get("department")
        or row.get("Process")
        or row.get("process_name")
        or "Unassigned"
    ).strip()) or "Unassigned"


def _history_process_key(row: dict) -> str:
    return normalize_process_name(str(
        row.get("Department")
        or row.get("department")
        or row.get("process_name")
        or row.get("Process")
        or "Unassigned"
    ).strip()) or "Unassigned"


def _history_uph(row: dict) -> float:
    for candidate in (row.get("uph"), row.get("UPH"), row.get("Average UPH")):
        value = _safe_float(candidate)
        if value > 0:
            return value
    return 0.0


def _history_units(row: dict) -> float:
    for candidate in (row.get("units"), row.get("Units"), row.get("Total Units")):
        value = _safe_float(candidate)
        if value >= 0:
            return value
    return 0.0


def _history_hours(row: dict) -> float:
    for candidate in (row.get("hours_worked"), row.get("Hours"), row.get("Hours Worked")):
        value = _safe_float(candidate)
        if value >= 0:
            return value
    return 0.0


def _confidence_label(coverage_ratio: float, included_count: int, affected_people: int) -> str:
    if coverage_ratio >= 0.7 and included_count >= 8 and affected_people >= 2:
        return "High"
    if coverage_ratio >= 0.4 and included_count >= 4:
        return "Medium"
    return "Low"


def _completeness_label(coverage_ratio: float, included_count: int) -> str:
    if coverage_ratio >= 0.7 and included_count >= 8:
        return "Data mostly complete"
    if coverage_ratio >= 0.4 and included_count >= 4:
        return "Partial data"
    return "Limited data"


def _source_references(rows: list[dict]) -> list[dict]:
    references: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        raw = row.get("raw") or {}
        source_file = str(raw.get("source_file") or raw.get("Source File") or raw.get("filename") or "").strip()
        import_job = str(raw.get("import_job_id") or raw.get("job_id") or raw.get("import_job") or "").strip()
        upload_id = str(raw.get("upload_id") or raw.get("source_upload_id") or "").strip()
        if not any((source_file, import_job, upload_id)):
            continue
        row_date = row.get("date")
        date_text = row_date.isoformat() if isinstance(row_date, date) else str(row_date or "")
        dedupe = (date_text, source_file, import_job or upload_id)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        references.append(
            {
                "Date": date_text,
                "Source File": source_file,
                "Import Job": import_job,
                "Upload": upload_id,
            }
        )
    references.sort(key=lambda item: str(item.get("Date") or ""), reverse=True)
    return references[:12]


def build_team_process_contexts(
    *,
    goal_status_rows: list[dict],
    history_rows: list[dict],
    lookback_days: int = 14,
    comparison_days: int = 5,
) -> dict:
    process_rows: dict[str, list[dict]] = {}
    for row in goal_status_rows or []:
        key = _process_key(row)
        process_rows.setdefault(key, []).append(row)

    process_history: dict[str, dict[str, Any]] = {}
    for row in history_rows or []:
        key = _history_process_key(row)
        bucket = process_history.setdefault(key, {"included": [], "excluded": []})
        row_date = _parse_date(row.get("work_date") or row.get("Date") or row.get("date") or row.get("Week"))
        uph = _history_uph(row)
        units = _history_units(row)
        hours = _history_hours(row)
        mapped = {"date": row_date, "uph": uph, "units": units, "hours": hours, "raw": row}
        if not row_date or uph <= 0:
            mapped["reason"] = "Missing/invalid date" if not row_date else "Missing/invalid UPH"
            bucket["excluded"].append(mapped)
        else:
            bucket["included"].append(mapped)

    cards: list[dict] = []
    for process_name, rows in process_rows.items():
        history_bucket = process_history.get(process_name, {"included": [], "excluded": []})
        included = sorted(history_bucket.get("included") or [], key=lambda item: item.get("date") or date.min)
        excluded = history_bucket.get("excluded") or []
        trend_rows = included[-lookback_days:]
        trailing_rows = trend_rows[-comparison_days:]
        prior_rows = trend_rows[-(comparison_days * 2):-comparison_days] if len(trend_rows) > comparison_days else []

        trailing_avg = round(sum(float(row.get("uph") or 0.0) for row in trailing_rows) / len(trailing_rows), 2) if trailing_rows else 0.0
        prior_avg = round(sum(float(row.get("uph") or 0.0) for row in prior_rows) / len(prior_rows), 2) if prior_rows else 0.0
        delta = round(trailing_avg - prior_avg, 2) if trailing_rows and prior_rows else 0.0

        employee_ids = sorted({eid for eid in (_employee_id(row) for row in rows) if eid})
        below_rows = [row for row in rows if str(row.get("goal_status") or "") == "below_goal" or normalize_trend_state(row.get("trend") or "") == "below_expected"]
        down_rows = [row for row in rows if normalize_trend_state(row.get("trend") or "") == "declining"]
        improving_rows = [row for row in rows if normalize_trend_state(row.get("trend") or "") == "improving"]
        inconsistent_rows = [row for row in rows if normalize_trend_state(row.get("trend") or "") == "inconsistent"]

        pattern_repeat = 0
        pattern_detected = False
        for row in rows:
            pattern = detect_pattern_memory_from_goal_row(row=row)
            pattern_repeat = max(pattern_repeat, int(pattern.repeat_count or 0))
            pattern_detected = pattern_detected or bool(pattern.pattern_detected)

        affected_people = len({eid for eid in (_employee_id(row) for row in below_rows + down_rows) if eid})
        coverage_ratio = round(len(trend_rows) / float(lookback_days), 2) if lookback_days > 0 else 0.0
        confidence = _confidence_label(coverage_ratio, len(trend_rows), affected_people)
        completeness_label = _completeness_label(coverage_ratio, len(trend_rows))
        completeness_note = (
            f"{completeness_label}: {len(trend_rows)} included and {len(excluded)} excluded records in the latest {lookback_days}-day window"
            f" (coverage {int(coverage_ratio * 100)}%)."
        )

        process_target_context = resolve_target_context(
            process_name=process_name,
            explicit_target=round(
                sum(_safe_float(row.get("Target UPH")) for row in rows if _safe_float(row.get("Target UPH")) > 0)
                / max(1, len([row for row in rows if _safe_float(row.get("Target UPH")) > 0])),
                2,
            ) if any(_safe_float(row.get("Target UPH")) > 0 for row in rows) else 0.0,
        )
        avg_target = _safe_float(process_target_context.get("target_uph"))

        if affected_people >= 2 and below_rows:
            current_state = "below expected pace across multiple people"
        elif below_rows:
            current_state = "below expected pace in isolated areas"
        elif down_rows and affected_people >= 2:
            current_state = "declining across multiple people"
        elif down_rows:
            current_state = "declining in a smaller subset"
        elif inconsistent_rows:
            current_state = "inconsistent from day to day"
        elif improving_rows:
            current_state = "improving in recent days"
        else:
            current_state = "holding steady"

        comparison_descriptions = build_comparison_descriptions(
            target_context=process_target_context,
            comparison_days=comparison_days,
            recent_avg=trailing_avg,
            prior_avg=prior_avg,
        )
        compared_to_what = (
            f"Compared with the latest {comparison_days} comparable days versus the prior {comparison_days} comparable days"
            + (f", and target {avg_target:.1f} UPH from the {process_target_context.get('target_source_label', 'configured target')}." if avg_target > 0 else ".")
        )

        units_values = [float(row.get("units") or 0.0) for row in trailing_rows if float(row.get("units") or 0.0) > 0]
        hours_values = [float(row.get("hours") or 0.0) for row in trailing_rows if float(row.get("hours") or 0.0) > 0]
        if units_values and hours_values:
            workload_context = (
                f"Recent workload context: about {sum(units_values) / len(units_values):.1f} units and "
                f"{sum(hours_values) / len(hours_values):.1f} hours per included day in the latest window."
            )
        else:
            workload_context = "Workload/volume context is limited because units/hours are incomplete in recent records."

        pattern_messages: list[str] = []
        if pattern_detected or pattern_repeat >= 2:
            repeat_count = max(2, pattern_repeat)
            pattern_messages.append(f"Similar pattern observed multiple times ({repeat_count} recent matches).")
        if len(below_rows) >= 2:
            pattern_messages.append("Repeated below-expected performance is affecting more than one person.")
        if len(down_rows) >= 2 or delta <= -1.0:
            pattern_messages.append("A declining pattern is present in this process.")
        if inconsistent_rows:
            pattern_messages.append("Recent daily results are moving around enough that the pattern is not steady yet.")

        major_signals: list[dict] = []
        if below_rows:
            major_signals.append(
                {
                    "what_happened": f"{len(below_rows)} of {len(rows)} people are currently below configured target pace.",
                    "compared_to_what": compared_to_what,
                    "why_showing": "Surfaced now because below-target status appears in current process-level signals.",
                }
            )
        if down_rows:
            major_signals.append(
                {
                    "what_happened": f"{len(down_rows)} people in this process are currently classified as declining.",
                    "compared_to_what": compared_to_what,
                    "why_showing": "Surfaced now because the recent average is below the prior comparable window for one or more people.",
                }
            )
        if inconsistent_rows:
            major_signals.append(
                {
                    "what_happened": f"{len(inconsistent_rows)} people in this process have recent results that are inconsistent day to day.",
                    "compared_to_what": compared_to_what,
                    "why_showing": "Surfaced now because recent day-to-day variation is too wide for a steady label.",
                }
            )
        if not major_signals:
            major_signals.append(
                {
                    "what_happened": "No major process-level deviations were found in the latest comparable window.",
                    "compared_to_what": compared_to_what,
                    "why_showing": "Shown for coverage so users can confirm stability, not only risk.",
                }
            )

        trend_points = [
            {
                "Date": row["date"].isoformat(),
                "UPH": round(float(row.get("uph") or 0.0), 2),
                "Target UPH": avg_target if avg_target > 0 else None,
            }
            for row in trend_rows
        ]

        card = {
            "process_name": process_name,
            "current_state": current_state,
            "compared_to_what": compared_to_what,
            "confidence_label": confidence,
            "data_completeness_note": completeness_note,
            "data_completeness_label": completeness_label,
            "comparison_breakdown": comparison_descriptions,
            "target_context": process_target_context,
            "trend_explanation": (
                "Recent process results are holding steady."
                if current_state == "holding steady"
                else "Recent process results are below expected pace."
                if "below expected pace" in current_state
                else "Recent process results are declining."
                if "declining" in current_state
                else "Recent process results are improving."
                if "improving" in current_state
                else "Recent process results are inconsistent from day to day."
            ),
            "workload_context": workload_context,
            "affected_people_count": affected_people,
            "employee_ids": employee_ids,
            "major_signals": major_signals,
            "pattern_messages": pattern_messages,
            "before_after_delta_uph": delta,
            "before_after_summary": (
                "improving"
                if delta >= 1.0
                else "still below expected"
                if avg_target > 0 and trailing_avg < avg_target and trailing_rows
                else "no clear change yet"
            ),
            "trend_points": trend_points,
            "time_breakdown": {
                "trailing_dates": [row["date"].isoformat() for row in trailing_rows],
                "prior_dates": [row["date"].isoformat() for row in prior_rows],
            },
            "included_records": [
                {
                    "Date": row["date"].isoformat(),
                    "UPH": round(float(row.get("uph") or 0.0), 2),
                    "Units": round(float(row.get("units") or 0.0), 2),
                    "Hours": round(float(row.get("hours") or 0.0), 2),
                }
                for row in trend_rows
            ],
            "excluded_records": [
                {
                    "Date": row.get("date").isoformat() if isinstance(row.get("date"), date) else str(row.get("date") or ""),
                    "Reason": str(row.get("reason") or "Excluded"),
                    "UPH": round(float(row.get("uph") or 0.0), 2),
                }
                for row in excluded[-lookback_days:]
            ],
            "source_references": _source_references(trend_rows + excluded),
            "has_notable_change": bool(below_rows or down_rows or pattern_messages),
        }
        cards.append(card)

    cards.sort(
        key=lambda card: (
            int(card.get("has_notable_change") is True),
            int(card.get("affected_people_count") or 0),
            -1 if str(card.get("confidence_label") or "") == "High" else 0,
        ),
        reverse=True,
    )

    has_notable = any(bool(card.get("has_notable_change")) for card in cards)
    return {
        "cards": cards,
        "has_notable_change": has_notable,
        "healthy_message": "No meaningful team-level changes from recent performance.",
    }
