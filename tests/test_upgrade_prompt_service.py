from services.upgrade_prompt_service import (
    build_advanced_value_upgrade_prompt,
    build_coaching_insights_upgrade_prompt,
    build_employee_capacity_upgrade_prompt,
    build_plan_usage_indicator,
)


def test_build_employee_capacity_upgrade_prompt_shows_when_near_limit():
    prompt = build_employee_capacity_upgrade_prompt(
        plan="starter",
        employee_count=22,
        employee_limit=25,
    )

    assert prompt is not None
    assert "22/25" in prompt["headline"]


def test_build_employee_capacity_upgrade_prompt_shows_when_at_limit():
    prompt = build_employee_capacity_upgrade_prompt(
        plan="starter",
        employee_count=25,
        employee_limit=25,
    )

    assert prompt is not None
    assert prompt["level"] == "error"
    assert "reached 25 employees" in prompt["headline"]


def test_build_employee_capacity_upgrade_prompt_omits_when_not_applicable():
    healthy = build_employee_capacity_upgrade_prompt(
        plan="starter",
        employee_count=10,
        employee_limit=25,
    )
    unlimited = build_employee_capacity_upgrade_prompt(
        plan="business",
        employee_count=300,
        employee_limit=-1,
    )

    assert healthy is None
    assert unlimited is None


def test_advanced_prompt_only_shows_for_non_pro():
    starter_prompt = build_advanced_value_upgrade_prompt(plan="starter")
    pro_prompt = build_advanced_value_upgrade_prompt(plan="pro")

    assert starter_prompt is not None
    assert "Advanced trends" in starter_prompt["headline"]
    assert pro_prompt is None


def test_coaching_insights_prompt_only_shows_for_non_pro():
    starter_prompt = build_coaching_insights_upgrade_prompt(plan="starter")
    business_prompt = build_coaching_insights_upgrade_prompt(plan="business")

    assert starter_prompt is not None
    assert "Coaching Insights" in starter_prompt["headline"]
    assert business_prompt is None


def test_plan_usage_indicator_marks_pressure_levels():
    near_limit = build_plan_usage_indicator(
        {"plan": "starter", "employee_count": 24, "employee_limit": 25}
    )
    at_limit = build_plan_usage_indicator(
        {"plan": "starter", "employee_count": 25, "employee_limit": 25}
    )
    unlimited = build_plan_usage_indicator(
        {"plan": "business", "employee_count": 140, "employee_limit": -1}
    )

    assert near_limit["pressure"] == "near_limit"
    assert at_limit["pressure"] == "at_limit"
    assert unlimited["pressure"] == "unlimited"