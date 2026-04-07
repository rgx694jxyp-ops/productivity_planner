"""Today Screen execution logic and queue-building helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

HIGH_PERFORMER_LOOKBACK_DAYS = 21
NO_IMPROVEMENT_OUTCOMES = {"no_change", "worse", "blocked"}
OPEN_ACTION_STATUSES = {"new", "in_progress", "escalated"}


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
    if str(action.get("status") or "").lower() == "closed":
        return "Closed"
    due = _parse_date(action.get("due_date"))
    if due and due < today:
        return "Overdue"
    if due and due == today:
        return "Due Today"
    status = str(action.get("status") or "new").replace("_", " ").title()
    return status or "New"


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
        emp_id = normalize_emp_id(action.get("emp_id"))
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
        if str(action.get("status") or "").lower() == "closed":
            continue
        emp_id = normalize_emp_id(action.get("emp_id"))
        due = _parse_date(action.get("due_date"))
        state = _queue_state(action, today)
        urgency = 70
        if state == "Overdue":
            urgency = 100 + max((today - (due or today)).days, 0)
        elif state == "Due Today":
            urgency = 90
        elif str(action.get("status") or "").lower() == "escalated":
            urgency = 85
        queue.append({
            "source": "action",
            "id": action.get("id"),
            "emp_id": emp_id,
            "employee_name": action.get("employee_name") or emp_id,
            "department": action.get("department") or "",
            "issue_type": action.get("issue_type") or "",
            "reason": action.get("reason") or "Open follow-up requires attention",
            "status": state,
            "due_date": action.get("due_date"),
            "action_type": action.get("action_type") or "",
            "success_metric": action.get("success_metric") or "",
            "baseline_uph": _safe_float(action.get("baseline_uph"), 0.0),
            "latest_uph": _safe_float(action.get("latest_uph"), 0.0),
            "next_step": _build_next_step(action.get("action_type"), "Complete follow-up"),
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
            "emp_id": emp_id,
            "employee_name": _extract_row_name(row),
            "department": _extract_row_dept(row),
            "issue_type": "below_goal_unhandled",
            "reason": f"Below goal for {streak} shifts with no action logged",
            "status": "New",
            "due_date": today.isoformat(),
            "action_type": "",
            "success_metric": f"Return to {target:.1f} UPH target" if target > 0 else "Return to baseline",
            "baseline_uph": avg_uph,
            "latest_uph": avg_uph,
            "next_step": "Start follow-up cycle",
            "urgency": 80 + streak,
        })

    queue.sort(key=lambda item: (-int(item.get("urgency") or 0), str(item.get("employee_name") or "")))

    closed_actions = [a for a in actions or [] if str(a.get("status") or "").lower() == "closed"]
    repeat_offenders = build_repeat_offenders(closed_actions, gs)
    ignored_high_performers = build_ignored_high_performers(gs, actions, today=today)
    recent_outcomes = build_recent_outcomes(closed_actions, today=today)

    summary = {
        "open_actions": sum(1 for item in queue if item.get("status") not in {"Closed"}),
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
        if str(action.get("outcome") or "").lower() not in NO_IMPROVEMENT_OUTCOMES:
            continue
        emp_id = normalize_emp_id(action.get("emp_id"))
        if emp_id:
            grouped.setdefault(emp_id, []).append(action)

    offenders = []
    for emp_id, items in grouped.items():
        if len(items) < 2:
            continue
        current = current_by_emp.get(emp_id, {})
        offenders.append({
            "emp_id": emp_id,
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
        if str(action.get("issue_type") or "") != "high_performer_development":
            continue
        created = _parse_date(action.get("created_at"))
        if created and created >= recent_cutoff:
            recent_dev_emp_ids.add(normalize_emp_id(action.get("emp_id")))

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
            "emp_id": emp_id,
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
        completed = _parse_date(action.get("completed_at") or action.get("updated_at"))
        if completed and completed >= cutoff:
            recent.append({
                "employee_name": action.get("employee_name") or normalize_emp_id(action.get("emp_id")),
                "department": action.get("department") or "",
                "outcome": str(action.get("outcome") or "").replace("_", " ").title(),
                "delta": round(_safe_float(action.get("improvement_delta"), 0.0), 2),
                "completed_at": completed.isoformat(),
            })
    recent.sort(key=lambda item: item.get("completed_at", ""), reverse=True)
    return recent[:10]
