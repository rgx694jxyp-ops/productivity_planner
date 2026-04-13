"""Daily snapshot generation and compatibility adapters for interpreted performance views."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from repositories import daily_employee_snapshots_repo, get_employees
from services.activity_records_service import get_recent_activity_records
from services.signal_interpretation_service import derive_confidence_from_coverage_policy
from services.signal_pattern_memory_service import detect_pattern_memory_from_goal_row
from services.target_service import normalize_process_name, resolve_target_context
from services.trend_classification_service import classify_trend_state, normalize_trend_state


_SNAPSHOT_READ_CACHE_TTL_SECONDS = 30
_LATEST_SNAPSHOT_CACHE: dict[tuple[str, int], tuple[float, tuple[list[dict], list[dict], str]]] = {}


def _latest_snapshot_cache_key(*, tenant_id: str, days: int) -> tuple[str, int]:
    return (str(tenant_id or "").strip(), int(days or 30))


def _clear_latest_snapshot_cache() -> None:
    _LATEST_SNAPSHOT_CACHE.clear()


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _group_activity_records(records: list[dict]) -> tuple[dict[tuple[str, str], list[dict]], dict[tuple[str, str], int]]:
    grouped_days: dict[tuple[str, str, date], dict[str, Any]] = {}
    excluded_counts: dict[tuple[str, str], int] = defaultdict(int)

    for row in records or []:
        employee_id = str(row.get("employee_id") or row.get("emp_id") or "").strip()
        if not employee_id:
            continue
        process_name = normalize_process_name(row.get("process_name") or row.get("department") or row.get("Process") or "") or "Unassigned"
        activity_date = _parse_date(row.get("activity_date") or row.get("work_date") or row.get("Date"))
        productivity_value = _safe_float(row.get("productivity_value") if row.get("productivity_value") is not None else row.get("uph"))
        units = _safe_float(row.get("units"))
        hours = _safe_float(row.get("hours") if row.get("hours") is not None else row.get("hours_worked"))
        quality_status = str(row.get("data_quality_status") or "partial").strip().lower()

        if not activity_date or productivity_value <= 0 or quality_status in {"invalid", "excluded"}:
            excluded_counts[(employee_id, process_name)] += 1
            continue

        bucket_key = (employee_id, process_name, activity_date)
        bucket = grouped_days.setdefault(
            bucket_key,
            {
                "employee_id": employee_id,
                "process_name": process_name,
                "snapshot_date": activity_date,
                "units": 0.0,
                "hours": 0.0,
                "productivity_values": [],
                "quality_statuses": set(),
                "source_count": 0,
            },
        )
        bucket["units"] += units
        bucket["hours"] += hours
        bucket["productivity_values"].append(productivity_value)
        bucket["quality_statuses"].add(quality_status)
        bucket["source_count"] += 1

    grouped_rows: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for (employee_id, process_name, snapshot_date), bucket in grouped_days.items():
        units = float(bucket.get("units") or 0.0)
        hours = float(bucket.get("hours") or 0.0)
        values = [float(value) for value in (bucket.get("productivity_values") or []) if float(value) > 0]
        if hours > 0 and units > 0:
            performance_uph = round(units / hours, 2)
        else:
            performance_uph = round(sum(values) / len(values), 2) if values else 0.0
        grouped_rows[(employee_id, process_name)].append(
            {
                "employee_id": employee_id,
                "process_name": process_name,
                "snapshot_date": snapshot_date,
                "performance_uph": performance_uph,
                "units": round(units, 2),
                "hours": round(hours, 2),
                "quality_statuses": sorted(bucket.get("quality_statuses") or []),
                "source_count": int(bucket.get("source_count") or 0),
            }
        )

    for rows in grouped_rows.values():
        rows.sort(key=lambda item: item.get("snapshot_date") or date.min)

    return grouped_rows, excluded_counts


def _confidence_label(coverage_ratio: float, included_count: int, expected_uph: float) -> tuple[str, float, str]:
    # Daily snapshots only allow High confidence when a target baseline is configured.
    confidence = derive_confidence_from_coverage_policy(
        coverage_ratio=coverage_ratio,
        included_count=included_count,
        high_min_coverage=0.7,
        high_min_count=7,
        medium_min_coverage=0.4,
        medium_min_count=4,
        allow_high=expected_uph > 0,
        high_basis="Recent daily coverage is strong and an expected pace is configured.",
        medium_basis="Partial recent daily coverage is available for comparison.",
        low_basis="Recent daily coverage is still limited, so treat this as an early signal.",
    )
    return str(confidence.level or "low").title(), float(confidence.score or 0.48), str(confidence.basis or "")


def _completeness_status(coverage_ratio: float, included_count: int, excluded_count: int) -> tuple[str, str]:
    if coverage_ratio >= 0.7 and included_count >= 7 and excluded_count == 0:
        return "complete", "Recent daily data is mostly complete."
    if coverage_ratio >= 0.4 and included_count >= 4:
        return "partial", "Some recent daily records are missing or excluded."
    return "limited", "Recent daily context is limited, so trend interpretation is cautious."


def build_daily_employee_snapshots(
    *,
    activity_records: list[dict],
    tenant_id: str = "",
    lookback_days: int = 14,
    comparison_days: int = 5,
) -> list[dict]:
    grouped_rows, excluded_counts = _group_activity_records(activity_records)
    snapshots: list[dict] = []

    for (employee_id, process_name), rows in grouped_rows.items():
        performance_history: list[float] = []
        goal_history: list[str] = []
        trend_history: list[str] = []

        for index, row in enumerate(rows):
            snapshot_date = row.get("snapshot_date")
            if not isinstance(snapshot_date, date):
                continue
            eligible_rows = [candidate for candidate in rows if candidate.get("snapshot_date") and candidate.get("snapshot_date") <= snapshot_date]
            lookback_rows = eligible_rows[-lookback_days:]
            trailing_rows = lookback_rows[-comparison_days:]
            prior_rows = lookback_rows[-(comparison_days * 2):-comparison_days] if len(lookback_rows) > comparison_days else []
            recent_average_uph = round(
                sum(_safe_float(candidate.get("performance_uph")) for candidate in trailing_rows) / len(trailing_rows),
                2,
            ) if trailing_rows else 0.0
            prior_average_uph = round(
                sum(_safe_float(candidate.get("performance_uph")) for candidate in prior_rows) / len(prior_rows),
                2,
            ) if prior_rows else 0.0
            target_context = resolve_target_context(
                employee_id=employee_id,
                process_name=process_name,
                explicit_target=0.0,
                tenant_id=tenant_id,
            )
            expected_uph = _safe_float(target_context.get("target_uph"))
            trend_result = classify_trend_state(
                recent_average_uph=recent_average_uph,
                prior_average_uph=prior_average_uph,
                expected_uph=expected_uph,
                included_count=len(lookback_rows),
                recent_values=[_safe_float(candidate.get("performance_uph")) for candidate in trailing_rows],
            )
            trend_state = normalize_trend_state(trend_result.get("state"))
            change_pct = round(((recent_average_uph - prior_average_uph) / prior_average_uph) * 100, 1) if prior_average_uph > 0 else 0.0
            goal_status = "no_goal"
            if expected_uph > 0:
                goal_status = "on_goal" if recent_average_uph >= expected_uph else "below_goal"

            performance_uph = _safe_float(row.get("performance_uph"))
            variance_uph = round(performance_uph - expected_uph, 2) if expected_uph > 0 else 0.0
            coverage_ratio = round(len(lookback_rows) / float(lookback_days), 2) if lookback_days > 0 else 0.0
            excluded_count = int(excluded_counts.get((employee_id, process_name), 0) or 0)
            confidence_label, confidence_score, confidence_basis = _confidence_label(coverage_ratio, len(lookback_rows), expected_uph)
            completeness_status, completeness_note = _completeness_status(coverage_ratio, len(lookback_rows), excluded_count)

            performance_history.append(performance_uph)
            goal_history.append(goal_status)
            trend_history.append(trend_state)
            recent_goal_status_history = goal_history[-6:]
            recent_trend_history = trend_history[-6:]
            pattern_memory = detect_pattern_memory_from_goal_row(
                row={
                    "trend": trend_state,
                    "change_pct": change_pct,
                    "recent_goal_status_history": recent_goal_status_history,
                    "recent_trend_history": recent_trend_history,
                }
            )

            snapshots.append(
                {
                    "tenant_id": tenant_id,
                    "snapshot_date": snapshot_date.isoformat(),
                    "employee_id": employee_id,
                    "process_name": process_name,
                    "performance_uph": round(performance_uph, 2),
                    "expected_uph": round(expected_uph, 2) if expected_uph > 0 else 0.0,
                    "variance_uph": variance_uph,
                    "recent_average_uph": recent_average_uph,
                    "prior_average_uph": prior_average_uph,
                    "trend_state": trend_state,
                    "goal_status": goal_status,
                    "confidence_label": confidence_label,
                    "confidence_score": confidence_score,
                    "data_completeness_status": completeness_status,
                    "data_completeness_note": (
                        f"{completeness_note} {len(lookback_rows)} included day(s), {excluded_count} excluded day(s), coverage {int(coverage_ratio * 100)}%."
                    ),
                    "coverage_ratio": coverage_ratio,
                    "included_day_count": len(lookback_rows),
                    "excluded_day_count": excluded_count,
                    "repeat_count": int(pattern_memory.repeat_count or 0),
                    "pattern_marker": str(pattern_memory.pattern_kind or "none"),
                    "recent_trend_history": recent_trend_history,
                    "recent_goal_status_history": recent_goal_status_history,
                    "workload_units": round(_safe_float(row.get("units")), 2),
                    "workload_hours": round(_safe_float(row.get("hours")), 2),
                    "raw_metrics": {
                        "confidence_basis": confidence_basis,
                        "target_context": target_context,
                        "change_pct": change_pct,
                        "trend_rule_applied": str(trend_result.get("rule_applied") or ""),
                        "trend_plain_explanation": str(trend_result.get("plain_explanation") or ""),
                        "lookback_dates": [candidate.get("snapshot_date").isoformat() for candidate in lookback_rows if candidate.get("snapshot_date")],
                        "trailing_dates": [candidate.get("snapshot_date").isoformat() for candidate in trailing_rows if candidate.get("snapshot_date")],
                        "prior_dates": [candidate.get("snapshot_date").isoformat() for candidate in prior_rows if candidate.get("snapshot_date")],
                        "source_count": _safe_int(row.get("source_count")),
                        "quality_statuses": list(row.get("quality_statuses") or []),
                    },
                }
            )

    snapshots.sort(key=lambda item: (str(item.get("snapshot_date") or ""), str(item.get("employee_id") or ""), str(item.get("process_name") or "")))
    return snapshots


def recompute_daily_employee_snapshots(
    *,
    tenant_id: str = "",
    from_date: str = "",
    to_date: str = "",
    days: int = 30,
    lookback_days: int = 14,
    comparison_days: int = 5,
) -> dict:
    if from_date and to_date:
        start_date = _parse_date(from_date)
        end_date = _parse_date(to_date)
        if start_date and end_date and end_date < start_date:
            start_date, end_date = end_date, start_date
        span_days = max(1, (end_date - start_date).days + 1) if start_date and end_date else max(1, int(days or 30))
        fetch_days = span_days + (lookback_days * 3)
    else:
        end_date = date.today()
        fetch_days = max(1, int(days or 30)) + (lookback_days * 3)
        start_date = end_date - timedelta(days=max(0, int(days or 30) - 1))

    activity_rows = get_recent_activity_records(tenant_id=tenant_id, days=fetch_days, limit=5000)
    snapshots = build_daily_employee_snapshots(
        activity_records=activity_rows,
        tenant_id=tenant_id,
        lookback_days=lookback_days,
        comparison_days=comparison_days,
    )
    filtered_snapshots = [
        row
        for row in snapshots
        if (not start_date or (_parse_date(row.get("snapshot_date")) or date.min) >= start_date)
        and (not end_date or (_parse_date(row.get("snapshot_date")) or date.max) <= end_date)
    ]

    if start_date and end_date:
        daily_employee_snapshots_repo.delete_daily_employee_snapshots(
            tenant_id=tenant_id,
            from_date=start_date.isoformat(),
            to_date=end_date.isoformat(),
        )
    if filtered_snapshots:
        daily_employee_snapshots_repo.batch_upsert_daily_employee_snapshots(filtered_snapshots)
    _clear_latest_snapshot_cache()

    return {
        "inserted": len(filtered_snapshots),
        "from_date": start_date.isoformat() if start_date else "",
        "to_date": end_date.isoformat() if end_date else "",
        "source_rows": len(activity_rows),
    }


def _employee_lookup() -> dict[str, dict]:
    return {
        str(row.get("emp_id") or "").strip(): row
        for row in (get_employees() or [])
        if str(row.get("emp_id") or "").strip()
    }


def snapshots_to_goal_status_rows(snapshot_rows: list[dict]) -> list[dict]:
    employee_lookup = _employee_lookup()
    out: list[dict] = []
    for row in snapshot_rows or []:
        employee_id = str(row.get("employee_id") or "").strip()
        employee = employee_lookup.get(employee_id, {})
        recent_average_uph = _safe_float(row.get("recent_average_uph"))
        expected_uph = _safe_float(row.get("expected_uph"))
        prior_average_uph = _safe_float(row.get("prior_average_uph"))
        change_pct = round(((recent_average_uph - prior_average_uph) / prior_average_uph) * 100, 1) if prior_average_uph > 0 else 0.0
        out.append(
            {
                "EmployeeID": employee_id,
                "Employee": str(employee.get("name") or employee_id),
                "Employee Name": str(employee.get("name") or employee_id),
                "Department": str(row.get("process_name") or employee.get("department") or "Unassigned"),
                "Average UPH": recent_average_uph,
                "Target UPH": expected_uph if expected_uph > 0 else "—",
                "Target Source": str(((row.get("raw_metrics") or {}).get("target_context") or {}).get("target_source_label") or "configured target"),
                "Resolved Process": str(row.get("process_name") or employee.get("department") or "Unassigned"),
                "goal_status": str(row.get("goal_status") or "no_goal"),
                "trend": normalize_trend_state(row.get("trend_state") or "insufficient_data"),
                "change_pct": change_pct,
                "recent_average_uph": recent_average_uph,
                "prior_average_uph": prior_average_uph,
                "expected_uph": expected_uph,
                "recent_trend_history": list(row.get("recent_trend_history") or []),
                "recent_goal_status_history": list(row.get("recent_goal_status_history") or []),
                "Record Count": int(row.get("included_day_count") or 0),
                "included_day_count": int(row.get("included_day_count") or 0),
                "Total Units": round(_safe_float(row.get("workload_units")), 2),
                "Hours Worked": round(_safe_float(row.get("workload_hours")), 2),
                "snapshot_date": str(row.get("snapshot_date") or ""),
                "confidence_label": str(row.get("confidence_label") or "Low"),
                "data_completeness_status": str(row.get("data_completeness_status") or "limited"),
                "data_completeness_note": str(row.get("data_completeness_note") or ""),
                "repeat_count": int(row.get("repeat_count") or 0),
                "pattern_marker": str(row.get("pattern_marker") or "none"),
                "trend_explanation": str(((row.get("raw_metrics") or {}).get("trend_plain_explanation") or "")),
            }
        )
    return out


def snapshots_to_history_rows(snapshot_rows: list[dict]) -> list[dict]:
    history_rows: list[dict] = []
    for row in snapshot_rows or []:
        history_rows.append(
            {
                "emp_id": str(row.get("employee_id") or ""),
                "department": str(row.get("process_name") or "Unassigned"),
                "work_date": str(row.get("snapshot_date") or "")[:10],
                "uph": round(_safe_float(row.get("performance_uph")), 2),
                "units": round(_safe_float(row.get("workload_units")), 2),
                "hours_worked": round(_safe_float(row.get("workload_hours")), 2),
                "source_file": "daily_snapshot",
                "raw_metrics": row.get("raw_metrics") or {},
            }
        )
    history_rows.sort(key=lambda item: (str(item.get("emp_id") or ""), str(item.get("work_date") or "")))
    return history_rows


def get_latest_snapshot_goal_status(*, tenant_id: str = "", days: int = 30, rebuild_if_missing: bool = True) -> tuple[list[dict], list[dict], str]:
    cache_key = _latest_snapshot_cache_key(tenant_id=tenant_id, days=days)
    now_ts = time.time()
    cached = _LATEST_SNAPSHOT_CACHE.get(cache_key)
    if cached and (now_ts - cached[0]) < _SNAPSHOT_READ_CACHE_TTL_SECONDS:
        return cached[1]

    snapshot_rows = daily_employee_snapshots_repo.list_daily_employee_snapshots(tenant_id=tenant_id, days=days, limit=5000)
    if not snapshot_rows and rebuild_if_missing:
        recompute_daily_employee_snapshots(tenant_id=tenant_id, days=days)
        snapshot_rows = daily_employee_snapshots_repo.list_daily_employee_snapshots(tenant_id=tenant_id, days=days, limit=5000)

    if not snapshot_rows:
        result: tuple[list[dict], list[dict], str] = ([], [], "")
        _LATEST_SNAPSHOT_CACHE[cache_key] = (now_ts, result)
        return result

    latest_date = max(str(row.get("snapshot_date") or "")[:10] for row in snapshot_rows if str(row.get("snapshot_date") or "").strip())
    latest_rows = [row for row in snapshot_rows if str(row.get("snapshot_date") or "")[:10] == latest_date]
    result = (snapshots_to_goal_status_rows(latest_rows), snapshots_to_history_rows(snapshot_rows), latest_date)
    _LATEST_SNAPSHOT_CACHE[cache_key] = (now_ts, result)
    return result


def get_employee_snapshot_history(*, tenant_id: str = "", employee_id: str, days: int = 30) -> list[dict]:
    rows = daily_employee_snapshots_repo.list_daily_employee_snapshots(
        tenant_id=tenant_id,
        employee_id=employee_id,
        days=days,
        limit=max(30, days * 4),
    )
    return rows


def get_team_process_snapshot_support(*, tenant_id: str = "", days: int = 30) -> dict:
    goal_status_rows, history_rows, snapshot_date = get_latest_snapshot_goal_status(tenant_id=tenant_id, days=days)
    return {
        "goal_status_rows": goal_status_rows,
        "history_rows": history_rows,
        "snapshot_date": snapshot_date,
        "has_notable_change": any(
            str(row.get("goal_status") or "") == "below_goal"
            or normalize_trend_state(row.get("trend") or "") in {"below_expected", "declining", "improving", "inconsistent"}
            for row in goal_status_rows
        ),
    }