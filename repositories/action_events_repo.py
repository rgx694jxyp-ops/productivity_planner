"""Data access for action_events."""

from __future__ import annotations

from repositories._common import get_client, get_tenant_id
from services.app_logging import log_error, log_warn


def log_action_event(
    action_id: str,
    event_type: str,
    employee_id: str,
    performed_by: str = "",
    notes: str = "",
    outcome: str | None = None,
    next_follow_up_at: str | None = None,
    linked_exception_id: str = "",
    owner: str = "",
    status: str = "",
    due_date: str | None = None,
    details: str = "",
    tenant_id: str = "",
) -> dict:
    """Append one immutable event to action_events."""
    tid = tenant_id or get_tenant_id()
    if not tid or not str(event_type or "").strip():
        return {}
    if not str(action_id or "").strip() and not str(employee_id or "").strip() and not str(linked_exception_id or "").strip():
        return {}

    owner_value = str(owner or performed_by or "")[:120]
    detail_text = str(details or notes or "")[:2000]
    due_value = str(due_date or next_follow_up_at or "")[:30]
    payload: dict = {
        "tenant_id": tid,
        "employee_id": str(employee_id or ""),
        "event_type": str(event_type or "")[:80],
        "performed_by": owner_value,
        "notes": detail_text,
        "owner": owner_value,
        "status": str(status or "logged")[:40],
        "details": detail_text,
    }
    if str(action_id or "").strip():
        payload["action_id"] = action_id
    if outcome is not None:
        payload["outcome"] = str(outcome)[:40]
    if due_value:
        payload["next_follow_up_at"] = due_value
        payload["due_date"] = due_value
    if str(linked_exception_id or "").strip():
        payload["linked_exception_id"] = linked_exception_id

    try:
        sb = get_client()
        result = sb.table("action_events").insert(payload).execute()
        return result.data[0] if result.data else {}
    except Exception as error:
        log_error(
            "repo_action_events_insert_failed",
            "Repository action event insert failed.",
            tenant_id=tid,
            context={
                "action_id": str(action_id),
                "employee_id": str(employee_id or ""),
                "linked_exception_id": str(linked_exception_id or ""),
                "event_type": str(event_type or ""),
            },
            error=error,
        )
        return {}


def list_action_events(
    action_id: str,
    tenant_id: str = "",
    employee_id: str = "",
    linked_exception_id: str = "",
    limit: int = 200,
    newest_first: bool = False,
    columns: str = "*",
) -> list[dict]:
    """Return events filtered by action, employee, and/or linked exception."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []

    try:
        sb = get_client()
        query = sb.table("action_events").select(columns or "*").eq("tenant_id", tid)
        if str(action_id or "").strip():
            query = query.eq("action_id", action_id)
        if str(employee_id or "").strip():
            query = query.eq("employee_id", str(employee_id))
        if str(linked_exception_id or "").strip():
            query = query.eq("linked_exception_id", linked_exception_id)

        result = query.order("event_at", desc=newest_first).limit(limit).execute()
        return result.data or []
    except Exception as error:
        log_warn(
            "repo_action_events_list_failed",
            "Repository action event listing failed.",
            tenant_id=tid,
            context={
                "action_id": str(action_id),
                "employee_id": str(employee_id or ""),
                "linked_exception_id": str(linked_exception_id or ""),
            },
            error=error,
        )
        return []


def list_action_events_for_action_ids(
    *,
    action_ids: list[str],
    tenant_id: str = "",
    limit: int = 500,
    newest_first: bool = False,
    columns: str = "*",
) -> list[dict]:
    """Return events for many action IDs in one query.

    This avoids N+1 patterns where callers fetch events per action.
    """
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []

    normalized_ids = [str(action_id or "").strip() for action_id in (action_ids or []) if str(action_id or "").strip()]
    if not normalized_ids:
        return []

    try:
        sb = get_client()
        query = (
            sb.table("action_events")
            .select(columns or "*")
            .eq("tenant_id", tid)
            .in_("action_id", normalized_ids)
        )
        result = query.order("event_at", desc=newest_first).limit(max(1, int(limit or 500))).execute()
        return result.data or []
    except Exception as error:
        log_warn(
            "repo_action_events_batch_list_failed",
            "Repository action events batch listing failed.",
            tenant_id=tid,
            context={"action_id_count": len(normalized_ids), "limit": int(limit or 500)},
            error=error,
        )
        return []
