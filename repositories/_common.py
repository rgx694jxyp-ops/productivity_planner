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
