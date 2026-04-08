"""Action query/read-model service.

Responsible for read paths and payload assembly used by pages.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from domain.actions import (
    IssueType,
    NO_IMPROVEMENT_OUTCOMES,
    OPEN_STATUSES,
    determine_priority,
    runtime_status,
    status_label,
    urgency_score,
)
from repositories import action_events_repo, actions_repo

HIGH_PERFORMER_LOOKBACK_DAYS = 21
OPEN_ACTION_STATUSES = OPEN_STATUSES

def get_open_actions(
    tenant_id: str = "",
    employee_id: str = "",
    today: date | None = None,
) -> list[dict]:
    """Return all open actions (not resolved/deprioritized), enriched with runtime status."""
    today = today or date.today()
    try:
        actions = actions_repo.list_actions(
            tenant_id=tenant_id,
            statuses=list(OPEN_STATUSES),
            employee_id=employee_id,
        )
        for action in actions:
            action["_runtime_status"] = runtime_status(
                str(action.get("status") or "new"),
                action.get("follow_up_due_at"),
                today=today,
            )
        return actions
    except Exception as e:
        print(f"[Error] get_open_actions failed: {e}")
        return []


def get_overdue_actions(tenant_id: str = "", today: date | None = None) -> list[dict]:
    """Return all actions with follow_up_due_at in the past."""
    today = today or date.today()
    try:
        open_actions = get_open_actions(tenant_id=tenant_id, today=today)
        return [a for a in open_actions if a.get("_runtime_status") == "overdue"]
    except Exception as e:
        print(f"[Error] get_overdue_actions failed: {e}")
        return []



def get_action_history(
    action_id: str,
    tenant_id: str = "",
) -> list[dict]:
    """Return timeline events for one action, oldest first."""
    try:
        events = action_events_repo.list_action_events(
            action_id=action_id,
            tenant_id=tenant_id,
        )
        return events or []
    except Exception as e:
        print(f"[Error] get_action_history failed: {e}")
        return []


def get_employee_actions(
    employee_id: str,
    tenant_id: str = "",
    today: date | None = None,
) -> list[dict]:
    """Return all actions for one employee, enriched with runtime status."""
    today = today or date.today()
    try:
        actions = actions_repo.list_actions(
            tenant_id=tenant_id,
            employee_id=employee_id,
        )
        for action in actions:
            action["_runtime_status"] = runtime_status(
                str(action.get("status") or "new"),
                action.get("follow_up_due_at"),
                today=today,
            )
        return actions
    except Exception as e:
        print(f"[Error] get_employee_actions failed: {e}")
        return []


def get_employee_action_timeline(
    employee_id: str,
    tenant_id: str = "",
) -> list[dict]:
    """Return flattened timeline across all actions for one employee, newest first."""
    try:
        actions = actions_repo.list_actions(
            tenant_id=tenant_id,
            employee_id=employee_id,
        )
        by_action_id = {str(a.get("id") or ""): a for a in (actions or [])}
        timeline: list[dict] = []
        for action in actions or []:
            action_id = str(action.get("id") or "")
            events = action_events_repo.list_action_events(
                action_id=action_id,
                tenant_id=tenant_id,
            )
            for ev in events or []:
                timeline.append(
                    {
                        "action_id": action_id,
                        "event_type": ev.get("event_type"),
                        "event_at": ev.get("event_at"),
                        "performed_by": ev.get("performed_by"),
                        "notes": ev.get("notes"),
                        "outcome": ev.get("outcome"),
                        "next_follow_up_at": ev.get("next_follow_up_at"),
                        "status": action.get("status"),
                        "issue_type": action.get("issue_type"),
                        "action_type": action.get("action_type"),
                        "trigger_summary": action.get("trigger_summary"),
                    }
                )
        timeline.sort(key=lambda item: str(item.get("event_at") or ""), reverse=True)
        return timeline
    except Exception as e:
        print(f"[Error] get_employee_action_timeline failed: {e}")
        return []



def normalize_emp_id(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0") and raw[:-2].isdigit():
        return raw[:-2]
    return raw


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _extract_row_emp_id(row: dict) -> str:
    return normalize_emp_id(
        row.get("EmployeeID")
        or row.get("emp_id")
        or row.get("Employee Name")
        or row.get("Employee")
        or ""
    )


def _extract_row_name(row: dict) -> str:
    return str(row.get("Employee Name") or row.get("Employee") or row.get("name") or "Unknown")


def _extract_row_dept(row: dict) -> str:
    return str(row.get("Department") or row.get("department") or "")


def _extract_row_uph(row: dict) -> float:
    if "UPH" in row:
        return _safe_float(row.get("UPH"), 0.0)
    if "uph" in row:
        return _safe_float(row.get("uph"), 0.0)
    return _safe_float(row.get("Average UPH"), 0.0)


def _history_by_emp(history: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in history or []:
        emp_id = _extract_row_emp_id(row)
        if not emp_id:
            continue
        grouped.setdefault(emp_id, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: (_parse_date(item.get("Date") or item.get("work_date") or item.get("Week")) or date.min))
    return grouped


def _recent_average_uph(history_rows: list[dict], trailing_days: int = 7) -> float:
    if not history_rows:
        return 0.0
    cutoff = date.today() - timedelta(days=trailing_days)
    values = []
    for row in history_rows:
        row_date = _parse_date(row.get("Date") or row.get("work_date"))
        if row_date and row_date >= cutoff:
            uph = _extract_row_uph(row)
            if uph > 0:
                values.append(uph)
    if not values:
        values = [_extract_row_uph(row) for row in history_rows[-trailing_days:] if _extract_row_uph(row) > 0]
    return round(sum(values) / len(values), 2) if values else 0.0


def _below_goal_streak(row: dict, history_rows: list[dict]) -> int:
    target = _safe_float(row.get("Target UPH"), 0.0)
    if target <= 0 or not history_rows:
        return 0
    streak = 0
    for item in reversed(history_rows):
        uph = _extract_row_uph(item)
        if uph <= 0:
            continue
        if uph < target:
            streak += 1
        else:
            break
    return streak


def _queue_state(action: dict, today: date) -> str:
    return status_label(str(action.get("status") or "new"), action.get("follow_up_due_at"), today=today)


def _build_next_step(action_type: str, fallback: str) -> str:
    cleaned = str(action_type or "").strip().replace("_", " ")
    if cleaned:
        return cleaned.title()
    return fallback


def _open_actions_by_emp(actions: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for action in sorted(actions or [], key=lambda item: str(item.get("created_at") or ""), reverse=True):
        status = str(action.get("status") or "new").lower()
        if status not in OPEN_ACTION_STATUSES:
            continue
        emp_id = normalize_emp_id(action.get("employee_id"))
        if emp_id and emp_id not in latest:
            latest[emp_id] = action
    return latest


def build_today_screen_payload(
    gs: list[dict],
    history: list[dict],
    actions: list[dict],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    history_map = _history_by_emp(history)
    open_actions = _open_actions_by_emp(actions)
    queue: list[dict] = []

    for action in actions or []:
        if str(action.get("status") or "").lower() == "resolved":
            continue
        emp_id = normalize_emp_id(action.get("employee_id"))
        state = _queue_state(action, today)
        failed_cycles = int(action.get("failed_cycles") or 0)
        urgency = urgency_score(
            status=str(action.get("status") or "new"),
            due_date=action.get("follow_up_due_at"),
            issue_type=str(action.get("issue_type") or ""),
            failed_cycles=failed_cycles,
            today=today,
        )
        queue.append({
            "source": "action",
            "id": action.get("id"),
            "employee_id": emp_id,
            "employee_name": action.get("employee_name") or emp_id,
            "department": action.get("department") or "",
            "issue_type": action.get("issue_type") or "",
            "trigger_summary": action.get("trigger_summary") or "Open follow-up requires attention",
            "status": state,
            "follow_up_due_at": action.get("follow_up_due_at"),
            "action_type": action.get("action_type") or "",
            "success_metric": action.get("success_metric") or "",
            "baseline_uph": _safe_float(action.get("baseline_uph"), 0.0),
            "latest_uph": _safe_float(action.get("latest_uph"), 0.0),
            "next_step": _build_next_step(action.get("action_type"), "Complete follow-up"),
            "priority": determine_priority(
                issue_type=str(action.get("issue_type") or ""),
                status=str(action.get("status") or "new"),
                follow_up_due_at=action.get("follow_up_due_at"),
                failed_cycles=failed_cycles,
                today=today,
            ),
            "urgency": urgency,
        })

    for row in gs or []:
        emp_id = _extract_row_emp_id(row)
        if not emp_id or emp_id in open_actions:
            continue
        if str(row.get("goal_status") or "") != "below_goal":
            continue
        streak = _below_goal_streak(row, history_map.get(emp_id, []))
        if streak < 3:
            continue
        avg_uph = _safe_float(row.get("Average UPH"), 0.0)
        target = _safe_float(row.get("Target UPH"), 0.0)
        queue.append({
            "source": "generated",
            "id": None,
            "employee_id": emp_id,
            "employee_name": _extract_row_name(row),
            "department": _extract_row_dept(row),
            "issue_type": IssueType.LOW_PERFORMANCE_UNADDRESSED,
            "trigger_summary": f"Below goal for {streak} shifts with no action logged",
            "status": "New",
            "follow_up_due_at": today.isoformat(),
            "action_type": "",
            "success_metric": f"Return to {target:.1f} UPH target" if target > 0 else "Return to baseline",
            "baseline_uph": avg_uph,
            "latest_uph": avg_uph,
            "next_step": "Start follow-up cycle",
            "priority": determine_priority(
                issue_type=IssueType.LOW_PERFORMANCE_UNADDRESSED,
                status="new",
                follow_up_due_at=today.isoformat(),
                failed_cycles=streak,
                today=today,
            ),
            "urgency": 80 + streak,
        })

    queue.sort(key=lambda item: (-int(item.get("urgency") or 0), str(item.get("employee_name") or "")))

    closed_actions = [a for a in actions or [] if str(a.get("status") or "").lower() == "resolved"]
    repeat_offenders = build_repeat_offenders(closed_actions, gs)
    ignored_high_performers = build_ignored_high_performers(gs, actions, today=today)
    recent_outcomes = build_recent_outcomes(closed_actions, today=today)

    summary = {
        "open_actions": sum(1 for item in queue if item.get("status") not in {"Resolved"}),
        "overdue": sum(1 for item in queue if item.get("status") == "Overdue"),
        "repeat_offenders": len(repeat_offenders),
        "ignored_high_performers": len(ignored_high_performers),
    }

    return {
        "summary": summary,
        "action_queue": queue,
        "repeat_offenders": repeat_offenders,
        "ignored_high_performers": ignored_high_performers,
        "recent_outcomes": recent_outcomes,
    }


def build_repeat_offenders(closed_actions: list[dict], gs: list[dict]) -> list[dict]:
    current_by_emp = {_extract_row_emp_id(row): row for row in gs or []}
    grouped: dict[str, list[dict]] = {}
    for action in closed_actions or []:
        if str(action.get("resolution_type") or "").lower() not in NO_IMPROVEMENT_OUTCOMES:
            continue
        emp_id = normalize_emp_id(action.get("employee_id"))
        if emp_id:
            grouped.setdefault(emp_id, []).append(action)

    offenders = []
    for emp_id, items in grouped.items():
        if len(items) < 2:
            continue
        current = current_by_emp.get(emp_id, {})
        offenders.append({
            "employee_id": emp_id,
            "employee_name": items[0].get("employee_name") or _extract_row_name(current),
            "department": items[0].get("department") or _extract_row_dept(current),
            "failed_cycles": len(items),
            "current_uph": _safe_float(current.get("Average UPH"), 0.0),
            "target_uph": _safe_float(current.get("Target UPH"), 0.0),
            "recommendation": "Change approach or escalate; prior coaching cycles did not improve performance.",
        })

    offenders.sort(key=lambda item: (-int(item.get("failed_cycles") or 0), str(item.get("employee_name") or "")))
    return offenders


def build_ignored_high_performers(gs: list[dict], actions: list[dict], *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    recent_cutoff = today - timedelta(days=HIGH_PERFORMER_LOOKBACK_DAYS)
    recent_dev_emp_ids = set()
    for action in actions or []:
        if str(action.get("issue_type") or "") != IssueType.HIGH_PERFORMER_IGNORED:
            continue
        created = _parse_date(action.get("created_at"))
        if created and created >= recent_cutoff:
            recent_dev_emp_ids.add(normalize_emp_id(action.get("employee_id")))

    high_performers = []
    for row in gs or []:
        emp_id = _extract_row_emp_id(row)
        if not emp_id or emp_id in recent_dev_emp_ids:
            continue
        avg_uph = _safe_float(row.get("Average UPH"), 0.0)
        target = _safe_float(row.get("Target UPH"), 0.0)
        if target <= 0 or avg_uph < (target * 1.10):
            continue
        if str(row.get("goal_status") or "") == "below_goal":
            continue
        high_performers.append({
            "employee_id": emp_id,
            "employee_name": _extract_row_name(row),
            "department": _extract_row_dept(row),
            "avg_uph": avg_uph,
            "target_uph": target,
            "recommendation": "Assign a development touchpoint so strong performers are not ignored.",
        })

    high_performers.sort(key=lambda item: (-float(item.get("avg_uph") or 0.0), str(item.get("employee_name") or "")))
    return high_performers[:5]


def build_recent_outcomes(closed_actions: list[dict], *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    cutoff = today - timedelta(days=14)
    recent = []
    for action in closed_actions or []:
        completed = _parse_date(action.get("resolved_at") or action.get("last_event_at"))
        if completed and completed >= cutoff:
            recent.append({
                "employee_name": action.get("employee_name") or normalize_emp_id(action.get("employee_id")),
                "department": action.get("department") or "",
                "outcome": str(action.get("resolution_type") or "").replace("_", " ").title(),
                "delta": round(_safe_float(action.get("improvement_delta"), 0.0), 2),
                "completed_at": completed.isoformat(),
            })
    recent.sort(key=lambda item: item.get("completed_at", ""), reverse=True)
    return recent[:10]


