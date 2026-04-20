"""Data access for actions current-state records."""

from __future__ import annotations

from datetime import date, datetime

from repositories._common import get_client, get_tenant_id
from repositories.action_events_repo import log_action_event
from services.app_logging import log_error, log_warn


def create_action(
    employee_id: str,
    employee_name: str,
    department: str,
    issue_type: str,
    trigger_summary: str,
    action_type: str,
    success_metric: str,
    follow_up_due_at: str,
    note: str = "",
    created_by: str = "",
    baseline_uph: float = 0.0,
    latest_uph: float = 0.0,
    priority: str = "medium",
    tenant_id: str = "",
) -> dict:
    tid = tenant_id or get_tenant_id()
    if not tid or not employee_id:
        return {}

    now = datetime.utcnow().isoformat() + "Z"
    payload = {
        "tenant_id": tid,
        "employee_id": str(employee_id),
        "employee_name": str(employee_name or "")[:120],
        "department": str(department or "")[:80],
        "issue_type": str(issue_type or "")[:80],
        "trigger_summary": str(trigger_summary or "")[:500],
        "action_type": str(action_type or "")[:80],
        "success_metric": str(success_metric or "")[:250],
        "follow_up_due_at": str(follow_up_due_at or "")[:10] or None,
        "note": str(note or "")[:2000],
        "created_by": str(created_by or "")[:120],
        "baseline_uph": baseline_uph,
        "latest_uph": latest_uph,
        "priority": str(priority or "medium")[:20],
        "status": "new",
        "last_event_at": now,
    }

    try:
        sb = get_client()
        result = sb.table("actions").insert(payload).execute()
        row = result.data[0] if result.data else {}

        if row.get("id"):
            log_action_event(
                action_id=str(row["id"]),
                event_type="created",
                employee_id=str(employee_id),
                performed_by=created_by,
                notes=str(note or trigger_summary or "")[:500],
                outcome="not_applicable",
                next_follow_up_at=payload["follow_up_due_at"],
                tenant_id=tid,
            )

        if payload["follow_up_due_at"]:
            import database

            database.add_followup_db(
                employee_id,
                employee_name,
                department,
                payload["follow_up_due_at"],
                trigger_summary[:80],
                tenant_id=tid,
            )

        return row
    except Exception as error:
        log_error(
            "repo_actions_create_failed",
            "Repository action creation failed.",
            tenant_id=tid,
            context={
                "employee_id": str(employee_id),
                "issue_type": str(issue_type or ""),
                "action_type": str(action_type or ""),
                "has_follow_up": bool(payload.get("follow_up_due_at")),
            },
            error=error,
        )
        return {}


def list_actions(tenant_id: str = "", statuses: list[str] | None = None, employee_id: str = "") -> list[dict]:
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []

    try:
        sb = get_client()
        query = sb.table("actions").select("*").eq("tenant_id", tid).order("last_event_at", desc=True)

        if employee_id:
            query = query.eq("employee_id", str(employee_id))
        if statuses:
            normalized = [str(status or "").lower() for status in statuses if str(status or "").strip()]
            if normalized:
                query = query.in_("status", normalized)

        result = query.execute()
        return result.data or []
    except Exception as error:
        log_warn(
            "repo_actions_list_failed",
            "Repository action listing failed.",
            tenant_id=tid,
            context={"employee_id": str(employee_id or ""), "statuses": statuses or []},
            error=error,
        )
        return []


def list_actions_for_employee_ids(
    *,
    employee_ids: list[str] | tuple[str, ...],
    tenant_id: str = "",
    statuses: list[str] | None = None,
) -> list[dict]:
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []

    normalized_employee_ids = [str(employee_id or "").strip() for employee_id in (employee_ids or []) if str(employee_id or "").strip()]
    if not normalized_employee_ids:
        return []

    try:
        sb = get_client()
        query = (
            sb.table("actions")
            .select("*")
            .eq("tenant_id", tid)
            .in_("employee_id", normalized_employee_ids)
            .order("last_event_at", desc=True)
        )

        if statuses:
            normalized = [str(status or "").lower() for status in statuses if str(status or "").strip()]
            if normalized:
                query = query.in_("status", normalized)

        result = query.execute()
        return result.data or []
    except Exception as error:
        log_warn(
            "repo_actions_batch_list_failed",
            "Repository batched action listing failed.",
            tenant_id=tid,
            context={"employee_id_count": len(normalized_employee_ids), "statuses": statuses or []},
            error=error,
        )
        return []


def get_action(action_id: str, tenant_id: str = "", columns: str = "*") -> dict:
    tid = tenant_id or get_tenant_id()
    if not tid or not str(action_id or "").strip():
        return {}

    try:
        sb = get_client()
        result = (
            sb.table("actions")
            .select(columns or "*")
            .eq("tenant_id", tid)
            .eq("id", action_id)
            .limit(1)
            .execute()
        )
        return (result.data or [{}])[0] if (result.data or []) else {}
    except Exception as error:
        log_warn(
            "repo_actions_get_failed",
            "Repository action lookup failed.",
            tenant_id=tid,
            context={"action_id": str(action_id)},
            error=error,
        )
        return {}


def update_action(action_id: str, updates: dict, tenant_id: str = "") -> dict:
    tid = tenant_id or get_tenant_id()
    if not tid or not action_id:
        return {}

    now = datetime.utcnow().isoformat() + "Z"
    patch = dict(updates or {})
    patch["last_event_at"] = now
    status = str(patch.get("status") or "").lower()
    if status == "resolved" and not patch.get("resolved_at"):
        patch["resolved_at"] = now
    if status == "escalated" and not patch.get("escalated_at"):
        patch["escalated_at"] = now

    try:
        current = get_action(
            action_id,
            tenant_id=tid,
            columns="id, employee_id, employee_name, department, issue_type, action_type, status, trigger_summary, follow_up_due_at",
        )

        sb = get_client()
        result = (
            sb.table("actions")
            .update(patch)
            .eq("tenant_id", tid)
            .eq("id", action_id)
            .execute()
        )
        updated_row = result.data[0] if result.data else {}
    except Exception as error:
        log_error(
            "repo_actions_update_failed",
            "Repository action update failed.",
            tenant_id=tid,
            context={
                "action_id": str(action_id),
                "status": status,
                "update_keys": sorted(list(patch.keys())),
            },
            error=error,
        )
        return {}

    due = str(patch.get("follow_up_due_at") or current.get("follow_up_due_at") or "")[:10]
    emp_code = str(current.get("employee_id") or "")
    emp_name = str(current.get("employee_name") or "")
    dept = str(current.get("department") or "")
    summary = str(current.get("trigger_summary") or "")

    status_to_event = {
        "resolved": "resolved",
        "escalated": "escalated",
        "deprioritized": "deprioritized",
        "in_progress": "coached",
        "follow_up_due": "follow_up_logged",
    }
    event_type = status_to_event.get(status) or ("follow_up_logged" if patch.get("follow_up_due_at") else "coached")
    note_text = str(patch.get("note") or patch.get("resolution_note") or "")
    outcome_val = str(patch.get("resolution_type") or "") or None

    side_effect_error = ""
    try:
        log_action_event(
            action_id=str(action_id),
            event_type=event_type,
            employee_id=emp_code,
            performed_by=str(patch.get("created_by") or ""),
            notes=note_text,
            outcome=outcome_val,
            next_follow_up_at=due or None,
            tenant_id=tid,
        )

        import database

        if status == "resolved":
            if due and emp_code:
                database.remove_followup_db(emp_code, due, tenant_id=tid)
        elif due and emp_code:
            database.add_followup_db(emp_code, emp_name, dept, due, summary[:80], tenant_id=tid)
    except Exception as error:
        side_effect_error = str(error)
        log_error(
            "repo_actions_update_side_effect_failed",
            "Action row updated but event/follow-up side effects failed.",
            tenant_id=tid,
            context={
                "action_id": str(action_id),
                "status": status,
                "event_type": event_type,
            },
            error=error,
        )

    if side_effect_error:
        if not updated_row:
            updated_row = {"id": str(action_id)}
        updated_row = dict(updated_row)
        updated_row["side_effect_error"] = side_effect_error
    return updated_row
