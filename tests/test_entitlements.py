from datetime import datetime, timedelta, timezone
from types import ModuleType

import pytest

from services import billing_service


def _install_db(monkeypatch, subscription):
    fake_db = ModuleType("database")
    fake_db.PLAN_LIMITS = {"starter": 25, "pro": 100, "business": -1}
    fake_db.get_subscription = lambda tenant_id: subscription
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
    _install_db(
        monkeypatch,
        {
            "plan": "starter",
            "status": status,
            "employee_limit": 25,
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )

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


def test_past_due_in_grace_window_keeps_access(monkeypatch):
    _install_db(
        monkeypatch,
        {
            "plan": "starter",
            "status": "past_due",
            "employee_limit": 25,
            "current_period_end": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
        },
    )

    ent = billing_service.get_subscription_entitlement("tenant-past-due-grace")

    assert ent["status"] == "past_due"
    assert ent["has_access"] is True
    assert ent["show_payment_banner"] is True
    assert ent["access_reason"] == "grace_period"


def test_past_due_outside_grace_window_blocks_access(monkeypatch):
    _install_db(
        monkeypatch,
        {
            "plan": "starter",
            "status": "past_due",
            "employee_limit": 25,
            "current_period_end": (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(),
        },
    )

    ent = billing_service.get_subscription_entitlement("tenant-past-due-expired")

    assert ent["status"] == "past_due"
    assert ent["has_access"] is False
    assert ent["show_payment_banner"] is True
    assert ent["access_reason"] == "past_due_blocked"


def test_pending_downgrade_sets_banner(monkeypatch):
    _install_db(
        monkeypatch,
        {
            "plan": "pro",
            "status": "active",
            "employee_limit": 100,
            "pending_plan": "starter",
            "pending_change_at": "2026-05-01T00:00:00Z",
            "current_period_end": "2026-05-01T00:00:00Z",
        },
    )

    ent = billing_service.get_subscription_entitlement("tenant-downgrade")

    assert ent["has_access"] is True
    assert ent["pending_plan"] == "starter"
    assert ent["show_pending_downgrade_banner"] is True
