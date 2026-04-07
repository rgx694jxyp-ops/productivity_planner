import pytest

from services import plan_service


def test_evaluate_employee_limit_disallows_over_plan_limit(monkeypatch):
    monkeypatch.setattr(
        plan_service,
        "get_subscription_entitlement",
        lambda tenant_id: {"plan": "starter", "employee_limit": 25, "has_access": True},
    )

    result = plan_service.evaluate_employee_limit("tenant-1", current_count=24, additional_count=2)

    assert result["allowed"] is False
    assert result["employee_limit"] == 25
    assert result["projected_total"] == 26


def test_enforce_invite_limit_raises_with_clear_message(monkeypatch):
    monkeypatch.setattr(
        plan_service,
        "get_subscription_entitlement",
        lambda tenant_id: {"plan": "starter", "employee_limit": 25, "has_access": True},
    )

    with pytest.raises(plan_service.PlanEnforcementError) as exc:
        plan_service.enforce_people_limit("tenant-1", current_count=25, additional_count=1, limit_type="invite")

    assert "team seats" in str(exc.value)


def test_get_invite_limit_blocks_when_no_access(monkeypatch):
    monkeypatch.setattr(
        plan_service,
        "get_subscription_entitlement",
        lambda tenant_id: {"plan": "starter", "employee_limit": 25, "has_access": False},
    )

    limit = plan_service.get_invite_limit("tenant-2")

    assert limit == 0


def test_productivity_navigation_changes_by_plan(monkeypatch):
    monkeypatch.setattr(
        plan_service,
        "get_subscription_entitlement",
        lambda tenant_id: {"plan": "pro", "employee_limit": 100, "has_access": True},
    )

    nav = plan_service.get_productivity_navigation("tenant-3")

    assert "Plan" in nav["mode_options"]
    assert "📈 Trends" in nav["monitor_options"]
