"""Shared low-level helpers for repository modules.

These helpers intentionally proxy to the existing database module so this refactor
can stay incremental and behavior-preserving.
"""

from __future__ import annotations


def _db_module():
    import database

    return database


def get_client():
    return _db_module().get_client()


def get_tenant_id() -> str:
    return _db_module().get_tenant_id()


def tenant_fields() -> dict:
    return _db_module()._tenant_fields()


def tenant_query(query):
    return _db_module()._tq(query)


def first_row(query):
    return _db_module()._first_row(query)


def get_config(key: str) -> str:
    return _db_module()._get_config(key)


def tenant_scoped_count(table_name: str, count_column: str, tenant_id: str = "") -> int:
    return _db_module()._get_tenant_scoped_count(table_name, count_column, tenant_id)


def log_error(category: str, message: str, detail: str = "", severity: str = "error") -> None:
    _db_module().log_error(category, message, detail=detail, severity=severity)


def require_tenant(tenant_id: str = "") -> str:
    """Return *tenant_id* (or the session tenant) and raise if neither is set.

    Use this at the start of any repository write operation to guarantee that
    a cross-tenant mutation cannot silently succeed due to an empty ``tenant_id``.

    Returns:
        The resolved non-empty tenant UUID string.

    Raises:
        ValueError: When no tenant context is available.
    """
    tid = str(tenant_id or "").strip() or str(get_tenant_id() or "").strip()
    if not tid:
        raise ValueError(
            "No tenant context. Set tenant_id explicitly or ensure the user "
            "session contains a valid tenant_id before calling this function."
        )
    return tid
