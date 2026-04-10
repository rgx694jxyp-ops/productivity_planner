"""Data access for lightweight operational exception records."""

from __future__ import annotations

from datetime import datetime, timezone

from repositories._common import get_client, get_tenant_id
from services.app_logging import log_error, log_warn


def create_operational_exception(
    *,
    exception_date: str,
    category: str,
    summary: str,
    employee_id: str = "",
    employee_name: str = "",
    department: str = "",
    shift: str = "",
    process_name: str = "",
    notes: str = "",
    created_by: str = "",
    tenant_id: str = "",
) -> dict:
    tid = tenant_id or get_tenant_id()
    cleaned_summary = str(summary or "").strip()
    if not tid or not cleaned_summary:
        return {}

    payload = {
        "tenant_id": tid,
        "exception_date": str(exception_date or "")[:10],
        "category": str(category or "unknown")[:40],
        "summary": cleaned_summary[:500],
        "employee_id": str(employee_id or "")[:120],
        "employee_name": str(employee_name or "")[:120],
        "department": str(department or "")[:80],
        "shift": str(shift or "")[:80],
        "process_name": str(process_name or "")[:120],
        "notes": str(notes or "")[:2000],
        "created_by": str(created_by or "")[:120],
        "status": "open",
    }

    try:
        sb = get_client()
        result = sb.table("operational_exceptions").insert(payload).execute()
        return result.data[0] if result.data else {}
    except Exception as error:
        log_error(
            "repo_operational_exception_create_failed",
            "Repository operational exception creation failed.",
            tenant_id=tid,
            context={
                "employee_id": str(employee_id or ""),
                "category": str(category or "unknown"),
                "has_shift": bool(str(shift or "").strip()),
                "has_process": bool(str(process_name or "").strip()),
            },
            error=error,
        )
        return {}


def list_operational_exceptions(
    *,
    tenant_id: str = "",
    status: str = "",
    employee_id: str = "",
    include_resolved: bool = False,
    limit: int = 100,
) -> list[dict]:
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []

    try:
        sb = get_client()
        query = sb.table("operational_exceptions").select("*").eq("tenant_id", tid).order("exception_date", desc=True).limit(limit)
        if employee_id:
            query = query.eq("employee_id", str(employee_id))
        if status:
            query = query.eq("status", str(status).lower())
        elif not include_resolved:
            query = query.eq("status", "open")

        result = query.execute()
        return result.data or []
    except Exception as error:
        log_warn(
            "repo_operational_exception_list_failed",
            "Repository operational exception listing failed.",
            tenant_id=tid,
            context={"employee_id": str(employee_id or ""), "status": str(status or "")},
            error=error,
        )
        return []


def resolve_operational_exception(
    exception_id: str,
    *,
    resolution_note: str = "",
    resolved_by: str = "",
    tenant_id: str = "",
) -> dict:
    tid = tenant_id or get_tenant_id()
    if not tid or not exception_id:
        return {}

    patch = {
        "status": "resolved",
        "resolution_note": str(resolution_note or "")[:2000],
        "resolved_by": str(resolved_by or "")[:120],
        "resolved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    try:
        sb = get_client()
        result = (
            sb.table("operational_exceptions")
            .update(patch)
            .eq("tenant_id", tid)
            .eq("id", exception_id)
            .execute()
        )
        return result.data[0] if result.data else {}
    except Exception as error:
        log_error(
            "repo_operational_exception_resolve_failed",
            "Repository operational exception resolve failed.",
            tenant_id=tid,
            context={"exception_id": str(exception_id)},
            error=error,
        )
        return {}
