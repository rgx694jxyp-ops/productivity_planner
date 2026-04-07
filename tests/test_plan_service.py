import pytest

from services import plan_service


def _patch_entitlements(monkeypatch, by_tenant):
    monkeypatch.setattr(
        plan_service,
        "get_subscription_entitlement",
        lambda tenant_id: by_tenant[tenant_id],
    )


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


@pytest.mark.parametrize(
    "tenant_id,feature_name,expected",
    [
        ("starter", "advanced", False),
        ("starter", "coaching_insights", False),
        ("starter", "priority_support", False),
        ("pro", "advanced", True),
        ("pro", "coaching_insights", True),
        ("pro", "priority_support", False),
        ("business", "advanced", True),
        ("business", "coaching_insights", True),
        ("business", "priority_support", True),
    ],
)
def test_feature_access_matrix_by_plan(monkeypatch, tenant_id, feature_name, expected):
    _patch_entitlements(
        monkeypatch,
        {
            "starter": {"plan": "starter", "employee_limit": 25, "has_access": True},
            "pro": {"plan": "pro", "employee_limit": 100, "has_access": True},
            "business": {"plan": "business", "employee_limit": -1, "has_access": True},
        },
    )

    assert plan_service.can_access_feature(tenant_id, feature_name) is expected


def test_employee_limit_matrix(monkeypatch):
    _patch_entitlements(
        monkeypatch,
        {
            "starter": {"plan": "starter", "employee_limit": 25, "has_access": True},
            "pro": {"plan": "pro", "employee_limit": 100, "has_access": True},
            "business": {"plan": "business", "employee_limit": -1, "has_access": True},
        },
    )

    assert plan_service.get_employee_limit("starter") == 25
    assert plan_service.get_employee_limit("pro") == 100
    assert plan_service.get_employee_limit("business") == -1


def test_invite_limit_matrix(monkeypatch):
    _patch_entitlements(
        monkeypatch,
        {
            "starter": {"plan": "starter", "employee_limit": 25, "has_access": True},
            "pro": {"plan": "pro", "employee_limit": 100, "has_access": True},
            "business": {"plan": "business", "employee_limit": -1, "has_access": True},
            "blocked": {"plan": "starter", "employee_limit": 25, "has_access": False},
        },
    )

    assert plan_service.get_invite_limit("starter") == 25
    assert plan_service.get_invite_limit("pro") == 100
    assert plan_service.get_invite_limit("business") == -1
    assert plan_service.get_invite_limit("blocked") == 0


def test_import_restriction_blocks_starter_when_over_limit(monkeypatch):
    _patch_entitlements(
        monkeypatch,
        {
            "starter": {"plan": "starter", "employee_limit": 25, "has_access": True},
        },
    )

    result = plan_service.evaluate_import_limit("starter", current_count=20, new_unique_count=10)

    assert result["allowed"] is False
    assert result["employee_limit"] == 25
    assert result["import_limit"] == 25
    assert result["projected_total"] == 30


def test_import_restriction_allows_business_unlimited(monkeypatch):
    _patch_entitlements(
        monkeypatch,
        {
            "business": {"plan": "business", "employee_limit": -1, "has_access": True},
        },
    )

    result = plan_service.evaluate_import_limit("business", current_count=1000, new_unique_count=500)

    assert result["allowed"] is True
    assert result["employee_limit"] == -1
    assert result["import_limit"] == -1
