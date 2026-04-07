from datetime import datetime, timedelta, timezone
from types import ModuleType

import pytest

from services import billing_service


def _install_db(monkeypatch, status):
    fake_db = ModuleType("database")
    fake_db.PLAN_LIMITS = {"starter": 25, "pro": 100, "business": -1}
    fake_db.get_subscription = lambda tenant_id: {
        "plan": "starter",
        "status": status,
        "employee_limit": 25,
        "current_period_end": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    fake_db.get_employee_count = lambda tenant_id: 3
    monkeypatch.setitem(__import__("sys").modules, "database", fake_db)


@pytest.mark.parametrize(
    "status, expected_access, expected_banner",
    [
        ("active", True, False),
        ("trialing", True, False),
        ("incomplete", False, True),
        ("unpaid", False, True),
        ("canceled", False, False),
    ],
)
def test_entitlement_status_matrix(monkeypatch, status, expected_access, expected_banner):
    _install_db(monkeypatch, status)

    ent = billing_service.get_subscription_entitlement("tenant-z")

    assert ent["status"] == status
    assert ent["has_access"] is expected_access
    assert ent["show_payment_banner"] is expected_banner


def test_entitlement_missing_subscription_returns_no_access(monkeypatch):
    fake_db = ModuleType("database")
    fake_db.PLAN_LIMITS = {"starter": 25}
    fake_db.get_subscription = lambda tenant_id: {}
    fake_db.get_employee_count = lambda tenant_id: 0
    monkeypatch.setitem(__import__("sys").modules, "database", fake_db)

    ent = billing_service.get_subscription_entitlement("tenant-empty")

    assert ent["has_access"] is False
    assert ent["access_reason"] == "no_subscription"
