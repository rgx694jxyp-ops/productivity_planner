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
    tenant_id: str = "",
) -> dict:
    """Append one immutable event to action_events."""
    tid = tenant_id or get_tenant_id()
    if not tid or not action_id:
        return {}

    payload: dict = {
        "tenant_id": tid,
        "action_id": action_id,
        "employee_id": str(employee_id or ""),
        "event_type": str(event_type or "")[:80],
        "performed_by": str(performed_by or "")[:120],
        "notes": str(notes or "")[:2000],
    }
    if outcome is not None:
        payload["outcome"] = str(outcome)[:40]
    if next_follow_up_at:
        payload["next_follow_up_at"] = str(next_follow_up_at)[:30]

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
                "event_type": str(event_type or ""),
            },
            error=error,
        )
        return {}


def list_action_events(action_id: str, tenant_id: str = "") -> list[dict]:
    """Return all events for a given action, oldest first."""
    tid = tenant_id or get_tenant_id()
    if not tid or not action_id:
        return []

    try:
        sb = get_client()
        result = (
            sb.table("action_events")
            .select("*")
            .eq("tenant_id", tid)
            .eq("action_id", action_id)
            .order("event_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception as error:
        log_warn(
            "repo_action_events_list_failed",
            "Repository action event listing failed.",
            tenant_id=tid,
            context={"action_id": str(action_id)},
            error=error,
        )
        return []
