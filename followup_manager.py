"""
followup_manager.py
-------------------
Stores and retrieves coaching follow-up schedules.

Storage: Supabase coaching_followups table only.
"""

from datetime import date, timedelta


def _tenant_today(tenant_id: str = "") -> date:
    try:
        from services.settings_service import get_tenant_local_now

        return get_tenant_local_now(str(tenant_id or "")).date()
    except Exception as exc:
        raise RuntimeError("Tenant-local date is unavailable.") from exc


def add_followup(
    emp_id: str,
    name: str,
    dept: str,
    followup_date: str,
    note_preview: str = "",
    tenant_id: str = "",
) -> None:
    """Schedule a follow-up for an employee on a specific date (YYYY-MM-DD)."""
    from database import add_followup_db

    add_followup_db(emp_id, name, dept, followup_date, note_preview, tenant_id=tenant_id)


def get_followups_for_range(from_date: str = None, to_date: str = None, tenant_id: str = "") -> list[dict]:
    """Return all follow-ups within an inclusive date range, sorted by date."""
    today_value = _tenant_today(tenant_id)
    _from = from_date or today_value.isoformat()
    _to   = to_date   or (today_value + timedelta(days=30)).isoformat()
    from database import get_followups_db

    return list(get_followups_db(_from, _to, tenant_id=tenant_id))


def get_followups_for_employee(
    emp_id: str,
    from_date: str = None,
    to_date: str = None,
    tenant_id: str = "",
) -> list[dict]:
    rows = get_followups_for_range(from_date=from_date, to_date=to_date, tenant_id=tenant_id)
    target = str(emp_id or "").strip()
    return [row for row in rows if str(row.get("emp_id") or "").strip() == target]


def get_followups_for_employees(
    employee_ids: list[str] | tuple[str, ...],
    from_date: str = None,
    to_date: str = None,
    tenant_id: str = "",
    limit: int | None = None,
    exists_only: bool = False,
) -> list[dict]:
    """Return follow-ups within range scoped to employee IDs."""
    today_value = _tenant_today(tenant_id)
    _from = from_date or today_value.isoformat()
    _to = to_date or (today_value + timedelta(days=30)).isoformat()
    from database import get_followups_for_employee_ids_db

    return list(
        get_followups_for_employee_ids_db(
            employee_ids,
            _from,
            _to,
            tenant_id=tenant_id,
            limit=limit,
            exists_only=exists_only,
        )
    )


def get_followups_due_today(tenant_id: str = "") -> list[dict]:
    today_value = _tenant_today(tenant_id)
    return get_followups_for_range(
        from_date=today_value.isoformat(),
        to_date=today_value.isoformat(),
        tenant_id=tenant_id,
    )


def get_followups_this_week(tenant_id: str = "") -> list[dict]:
    today = _tenant_today(tenant_id)
    sunday = today + timedelta(days=(6 - today.weekday()))
    return get_followups_for_range(
        from_date=today.isoformat(),
        to_date=sunday.isoformat(),
        tenant_id=tenant_id,
    )


def remove_followup(emp_id: str, followup_date: str, tenant_id: str = "") -> None:
    """Remove a follow-up once it has been completed."""
    from database import remove_followup_db

    remove_followup_db(emp_id, followup_date, tenant_id=tenant_id)


def update_followup(emp_id: str, name: str, dept: str,
                    old_date: str, new_date: str, note_preview: str = "", tenant_id: str = "") -> None:
    """Move a follow-up from old_date to new_date."""
    remove_followup(emp_id, old_date, tenant_id=tenant_id)
    add_followup(emp_id, name, dept, new_date, note_preview, tenant_id=tenant_id)


def count_due_today(tenant_id: str = "") -> int:
    return len(get_followups_due_today(tenant_id=tenant_id))
