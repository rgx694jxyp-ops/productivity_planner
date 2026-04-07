from datetime import datetime, timedelta, timezone
from types import ModuleType

from services import billing_service


def _install_fake_database(monkeypatch, subscription, employee_count=0):
    fake_db = ModuleType("database")
    fake_db.PLAN_LIMITS = {"starter": 25, "pro": 100, "business": -1}
    fake_db.get_subscription = lambda tenant_id: subscription
    fake_db.get_employee_count = lambda tenant_id: employee_count
    monkeypatch.setitem(__import__("sys").modules, "database", fake_db)


def test_get_subscription_entitlement_active_plan(monkeypatch):
    sub = {
        "plan": "pro",
        "status": "active",
        "employee_limit": 100,
        "pending_plan": "starter",
        "pending_change_at": "2026-05-01T00:00:00Z",
        "current_period_end": "2026-05-01T00:00:00Z",
        "cancel_at_period_end": False,
    }
    _install_fake_database(monkeypatch, sub, employee_count=42)

    out = billing_service.get_subscription_entitlement("tenant-a")

    assert out["has_access"] is True
    assert out["plan"] == "pro"
    assert out["employee_limit"] == 100
    assert out["employee_count"] == 42
    assert out["show_pending_downgrade_banner"] is True
    assert out["pending_plan"] == "starter"


def test_get_subscription_entitlement_past_due_grace_period(monkeypatch):
    period_end = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    sub = {
        "plan": "starter",
        "status": "past_due",
        "employee_limit": 25,
        "current_period_end": period_end,
    }
    _install_fake_database(monkeypatch, sub, employee_count=5)

    out = billing_service.get_subscription_entitlement("tenant-b")

    assert out["status"] == "past_due"
    assert out["show_payment_banner"] is True
    assert out["has_access"] is True
    assert out["access_reason"] == "grace_period"


def test_get_subscription_entitlement_unpaid_blocked(monkeypatch):
    sub = {
        "plan": "starter",
        "status": "unpaid",
        "employee_limit": 25,
    }
    _install_fake_database(monkeypatch, sub, employee_count=7)

    out = billing_service.get_subscription_entitlement("tenant-c")

    assert out["has_access"] is False
    assert out["show_payment_banner"] is True
    assert out["access_reason"] == "unpaid"
