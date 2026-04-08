import os
from types import ModuleType, SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "placeholder-key")

import database
from error_log import _tenant_suffix as error_suffix
from history_manager import _tenant_suffix as history_suffix
from services import billing_service
from services import import_service


def test_tenant_suffix_isolated_file_names():
    assert error_suffix("tenant-a") == "_tenant-a"
    assert history_suffix("tenant-b") == "_tenant-b"
    assert error_suffix("") == ""
    assert history_suffix("   ") == ""


def test_import_upload_helpers_require_tenant_id():
    assert import_service._list_recent_uploads(tenant_id="") == []
    assert import_service._record_upload_event("", "file.csv", 10, {"x": 1}) is None
    assert import_service._get_upload_by_id("", 123) is None


def test_tq_adds_tenant_filter(monkeypatch):
    class _Q:
        def __init__(self):
            self.eq_calls = []

        def eq(self, key, value):
            self.eq_calls.append((key, value))
            return self

    monkeypatch.setattr(database, "get_tenant_id", lambda: "tenant-a")
    q = _Q()

    out = database._tq(q)

    assert out is q
    assert ("tenant_id", "tenant-a") in q.eq_calls


def test_subscription_lookup_is_tenant_scoped(monkeypatch):
    class _Query:
        def __init__(self):
            self.eq_calls = []

        def select(self, _cols):
            return self

        def eq(self, key, value):
            self.eq_calls.append((key, value))
            return self

        def limit(self, _n):
            return self

        def execute(self):
            tenant = ""
            for key, value in self.eq_calls:
                if key == "tenant_id":
                    tenant = value
            data = {
                "tenant-a": {"tenant_id": "tenant-a", "plan": "starter"},
                "tenant-b": {"tenant_id": "tenant-b", "plan": "business"},
            }
            row = data.get(tenant)
            return SimpleNamespace(data=[row] if row else [])

    query = _Query()

    class _Client:
        def table(self, table_name):
            assert table_name == "subscriptions"
            return query

    monkeypatch.setattr(database, "get_client", lambda: _Client())

    sub_a = database.get_subscription("tenant-a", allow_live_fallback=False)

    assert sub_a["tenant_id"] == "tenant-a"
    assert sub_a["plan"] == "starter"
    assert ("tenant_id", "tenant-a") in query.eq_calls


def test_billing_entitlement_uses_requested_tenant_only(monkeypatch):
    calls = []
    sub_by_tenant = {
        "tenant-a": {
            "plan": "starter",
            "status": "active",
            "employee_limit": 25,
            "current_period_end": "2026-06-01T00:00:00Z",
        },
        "tenant-b": {
            "plan": "business",
            "status": "active",
            "employee_limit": -1,
            "current_period_end": "2026-06-01T00:00:00Z",
        },
    }
    count_by_tenant = {"tenant-a": 7, "tenant-b": 999}

    fake_db = ModuleType("database")
    fake_db.PLAN_LIMITS = {"starter": 25, "pro": 100, "business": -1}

    def _get_subscription(tenant_id):
        calls.append(("subscription", tenant_id))
        return sub_by_tenant.get(tenant_id)

    def _get_employee_count(tenant_id):
        calls.append(("employee_count", tenant_id))
        return count_by_tenant.get(tenant_id, 0)

    fake_db.get_subscription = _get_subscription
    fake_db.get_employee_count = _get_employee_count
    monkeypatch.setitem(__import__("sys").modules, "database", fake_db)

    ent = billing_service.get_subscription_entitlement("tenant-a")

    assert ent["plan"] == "starter"
    assert ent["employee_count"] == 7
    assert ent["employee_count"] != 999
    assert calls == [("subscription", "tenant-a"), ("employee_count", "tenant-a")]


def test_actions_lookup_is_tenant_scoped(monkeypatch):
    class _Query:
        def __init__(self):
            self.eq_calls = []

        def select(self, _cols):
            return self

        def eq(self, key, value):
            self.eq_calls.append((key, value))
            return self

        def order(self, *_args, **_kwargs):
            return self

        def execute(self):
            tenant = ""
            for key, value in self.eq_calls:
                if key == "tenant_id":
                    tenant = value
            data = {
                "tenant-a": [{"id": 1, "tenant_id": "tenant-a", "employee_id": "E1"}],
                "tenant-b": [{"id": 2, "tenant_id": "tenant-b", "employee_id": "E2"}],
            }
            return SimpleNamespace(data=data.get(tenant, []))

    query = _Query()

    class _Client:
        def table(self, table_name):
            assert table_name == "actions"
            return query

    monkeypatch.setattr(database, "get_client", lambda: _Client())

    rows = database.list_actions("tenant-a")

    assert rows == [{"id": 1, "tenant_id": "tenant-a", "employee_id": "E1"}]
    assert ("tenant_id", "tenant-a") in query.eq_calls
