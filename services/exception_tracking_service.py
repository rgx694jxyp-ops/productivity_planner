"""Lightweight operational exception tracking service."""

from __future__ import annotations

from datetime import date

from domain.operational_exceptions import normalize_exception_category
from repositories import operational_exceptions_repo
from services.access_control_service import require_write
from services.observability import log_operational_event


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
    user_role: str = "",
) -> dict:
    require_write(user_role)
    cleaned_summary = str(summary or "").strip()
    if not cleaned_summary:
        return {}

    result = operational_exceptions_repo.create_operational_exception(
        exception_date=exception_date,
        category=normalize_exception_category(category),
        summary=cleaned_summary,
        employee_id=employee_id,
        employee_name=employee_name,
        department=department,
        shift=shift,
        process_name=process_name,
        notes=notes,
        created_by=created_by,
        tenant_id=tenant_id,
    )
    if result:
        log_operational_event(
            "exception_created",
            status="completed",
            tenant_id=tenant_id,
            context={
                "exception_id": str(result.get("id") or ""),
                "employee_id": str(employee_id or ""),
                "category": str(normalize_exception_category(category) or "unknown"),
            },
        )
    return result


def resolve_operational_exception(
    exception_id: str,
    *,
    resolution_note: str = "",
    resolved_by: str = "",
    tenant_id: str = "",
) -> dict:
    result = operational_exceptions_repo.resolve_operational_exception(
        exception_id,
        resolution_note=resolution_note,
        resolved_by=resolved_by,
        tenant_id=tenant_id,
    )
    if result:
        log_operational_event(
            "exception_resolved",
            status="completed",
            tenant_id=tenant_id,
            context={"exception_id": str(exception_id or ""), "resolved_by": str(resolved_by or "")},
        )
    return result


def list_open_operational_exceptions(*, tenant_id: str = "", employee_id: str = "", limit: int = 100) -> list[dict]:
    return operational_exceptions_repo.list_operational_exceptions(
        tenant_id=tenant_id,
        employee_id=employee_id,
        status="open",
        limit=limit,
    )


def list_recent_operational_exceptions(*, tenant_id: str = "", employee_id: str = "", limit: int = 100) -> list[dict]:
    return operational_exceptions_repo.list_operational_exceptions(
        tenant_id=tenant_id,
        employee_id=employee_id,
        include_resolved=True,
        limit=limit,
    )


def summarize_open_operational_exceptions(*, tenant_id: str = "", employee_id: str = "") -> dict:
    rows = list_open_operational_exceptions(tenant_id=tenant_id, employee_id=employee_id, limit=250)
    by_category: dict[str, int] = {}
    linked_employee_ids: set[str] = set()
    for row in rows:
        category = str(row.get("category") or "unknown")
        by_category[category] = by_category.get(category, 0) + 1
        employee_key = str(row.get("employee_id") or "").strip()
        if employee_key:
            linked_employee_ids.add(employee_key)

    return {
        "open_count": len(rows),
        "linked_employee_count": len(linked_employee_ids),
        "categories": by_category,
        "rows": rows,
    }


def build_exception_context_line(row: dict) -> str:
    parts: list[str] = []
    exception_date = str(row.get("exception_date") or "").strip()
    shift = str(row.get("shift") or "").strip()
    process_name = str(row.get("process_name") or "").strip()
    category = str(row.get("category") or "unknown").strip()
    if exception_date:
        parts.append(exception_date)
    if shift:
        parts.append(shift)
    if process_name:
        parts.append(process_name)
    parts.append(category)
    return " | ".join(parts)


def is_exception_active_on_date(row: dict, target_date: date) -> bool:
    text = str(row.get("exception_date") or "").strip()
    if not text:
        return False
    try:
        return date.fromisoformat(text[:10]) == target_date
    except Exception:
        return False
