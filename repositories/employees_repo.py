"""Data access for employees."""

from __future__ import annotations

from repositories._common import get_client, tenant_query, tenant_scoped_count


def get_employees() -> list[dict]:
    sb = get_client()
    result = tenant_query(sb.table("employees").select("*")).order("name").execute()
    return result.data or []


def get_employee_count(tenant_id: str = "") -> int:
    """Return current number of employees for the tenant."""
    return tenant_scoped_count("employees", "emp_id", tenant_id)
