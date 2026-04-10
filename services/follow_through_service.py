"""Lightweight follow-through logging on top of action_events."""

from __future__ import annotations

from repositories import action_events_repo


FOLLOW_THROUGH_STATUSES: list[str] = ["logged", "pending", "done", "blocked"]
FOLLOW_THROUGH_OPEN_STATUSES: set[str] = {"logged", "pending", "blocked"}
FOLLOW_THROUGH_OUTCOMES: list[str] = ["improved", "no_change", "worse", "blocked", "pending", "not_applicable"]
FOLLOW_THROUGH_EVENT_TYPES: set[str] = {
    "coached",
    "follow_up_logged",
    "recognized",
    "escalated",
    "resolved",
    "deprioritized",
    "reopened",
    "follow_through_logged",
}


def normalize_follow_through_status(value: str, *, default: str = "logged") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in FOLLOW_THROUGH_STATUSES else default


def normalize_follow_through_outcome(value: str) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in FOLLOW_THROUGH_OUTCOMES else None


def log_follow_through_event(
    *,
    employee_id: str = "",
    action_id: str = "",
    linked_exception_id: str = "",
    owner: str = "",
    status: str = "logged",
    due_date: str = "",
    details: str,
    outcome: str = "",
    tenant_id: str = "",
) -> dict:
    cleaned_details = str(details or "").strip()
    if not cleaned_details:
        return {}

    return action_events_repo.log_action_event(
        action_id=action_id,
        event_type="follow_through_logged" if not action_id else "follow_up_logged",
        employee_id=employee_id,
        performed_by=owner,
        notes=cleaned_details,
        outcome=normalize_follow_through_outcome(outcome),
        next_follow_up_at=due_date or None,
        linked_exception_id=linked_exception_id,
        owner=owner,
        status=normalize_follow_through_status(status),
        due_date=due_date or None,
        details=cleaned_details,
        tenant_id=tenant_id,
    )


def list_recent_follow_through_events(
    *,
    tenant_id: str = "",
    employee_id: str = "",
    linked_exception_id: str = "",
    limit: int = 20,
) -> list[dict]:
    rows = action_events_repo.list_action_events(
        action_id="",
        tenant_id=tenant_id,
        employee_id=employee_id,
        linked_exception_id=linked_exception_id,
        limit=max(limit * 3, 50),
        newest_first=True,
    )
    filtered = [row for row in rows if str(row.get("event_type") or "") in FOLLOW_THROUGH_EVENT_TYPES]
    return filtered[:limit]


def summarize_follow_through_events(
    *,
    tenant_id: str = "",
    employee_id: str = "",
    linked_exception_id: str = "",
    limit: int = 50,
) -> dict:
    rows = list_recent_follow_through_events(
        tenant_id=tenant_id,
        employee_id=employee_id,
        linked_exception_id=linked_exception_id,
        limit=limit,
    )
    open_count = sum(1 for row in rows if str(row.get("status") or "logged") in FOLLOW_THROUGH_OPEN_STATUSES)
    return {
        "rows": rows,
        "total_count": len(rows),
        "open_count": open_count,
    }


def build_follow_through_context_line(row: dict) -> str:
    parts: list[str] = []
    status = str(row.get("status") or "logged").replace("_", " ").title()
    owner = str(row.get("owner") or row.get("performed_by") or "").strip()
    due_date = str(row.get("due_date") or row.get("next_follow_up_at") or "").strip()
    if status:
        parts.append(status)
    if owner:
        parts.append(owner)
    if due_date:
        parts.append(f"Due {due_date[:10]}")
    return " | ".join(parts)