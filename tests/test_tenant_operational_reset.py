import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "placeholder-key")

import database


class _DeleteQuery:
    def __init__(self, table_name: str, recorder: dict):
        self._table_name = table_name
        self._recorder = recorder

    def delete(self):
        self._recorder["delete_order"].append(self._table_name)
        return self

    def eq(self, key, value):
        self._recorder["eq_calls"].append((self._table_name, key, value))
        return self

    def execute(self):
        if self._table_name in self._recorder["raise_on"]:
            raise RuntimeError(f"boom:{self._table_name}")
        return None


class _Client:
    def __init__(self, recorder: dict):
        self._recorder = recorder

    def table(self, table_name):
        self._recorder["tables_seen"].append(table_name)
        return _DeleteQuery(table_name, self._recorder)


def test_reset_tenant_operational_data_deletes_expected_tables_in_order(monkeypatch):
    recorder = {
        "delete_order": [],
        "eq_calls": [],
        "tables_seen": [],
        "raise_on": set(),
    }
    monkeypatch.setattr(database, "get_client", lambda: _Client(recorder))

    out = database.reset_tenant_operational_data("tenant-a")

    expected = [
        "daily_signals",
        "daily_employee_snapshots",
        "activity_records",
        "operational_exceptions",
        "action_events",
        "actions",
        "coaching_followups",
        "coaching_notes",
        "uph_history",
        "unit_submissions",
        "order_assignments",
        "orders",
        "client_trends",
        "clients",
        "employees",
        "shifts",
        "uploaded_files",
        "error_reports",
    ]

    assert out["tenant_id"] == "tenant-a"
    assert out["attempted_tables"] == expected
    assert out["errors"] == []
    assert recorder["delete_order"] == expected
    assert all(key == "tenant_id" and value == "tenant-a" for _, key, value in recorder["eq_calls"])

    preserved_tables = {
        "tenants",
        "user_profiles",
        "tenant_goals",
        "tenant_settings",
        "tenant_email_config",
        "subscriptions",
    }
    assert not (set(recorder["tables_seen"]) & preserved_tables)


def test_reset_tenant_operational_data_uses_session_tenant_fallback(monkeypatch):
    recorder = {
        "delete_order": [],
        "eq_calls": [],
        "tables_seen": [],
        "raise_on": set(),
    }
    monkeypatch.setattr(database, "get_client", lambda: _Client(recorder))
    monkeypatch.setattr(database, "get_tenant_id", lambda: "tenant-from-session")

    out = database.reset_tenant_operational_data("")

    assert out["tenant_id"] == "tenant-from-session"
    assert recorder["delete_order"]


def test_reset_tenant_operational_data_continues_after_table_error(monkeypatch):
    recorder = {
        "delete_order": [],
        "eq_calls": [],
        "tables_seen": [],
        "raise_on": {"activity_records"},
    }
    monkeypatch.setattr(database, "get_client", lambda: _Client(recorder))

    out = database.reset_tenant_operational_data("tenant-a")

    assert len(out["errors"]) == 1
    assert out["errors"][0]["table"] == "activity_records"
    assert recorder["delete_order"][0] == "daily_signals"
    assert recorder["delete_order"][-1] == "error_reports"


def test_reset_tenant_operational_data_no_tenant_noop(monkeypatch):
    monkeypatch.setattr(database, "get_tenant_id", lambda: "")

    out = database.reset_tenant_operational_data("")

    assert out == {"tenant_id": "", "attempted_tables": [], "errors": []}
