"""Contextual plan usage and upgrade prompt helpers.

This module is intentionally read-only relative to plan enforcement. It only
derives UI messaging based on already computed entitlement/plan context.
"""

from typing import Any

from services.plan_service import compare_plan_names, normalize_plan_name


def build_plan_usage_indicator(entitlement: dict[str, Any]) -> dict[str, Any]:
    plan = normalize_plan_name(entitlement.get("plan") or "starter")
    employee_count = int(entitlement.get("employee_count", 0) or 0)
    employee_limit = int(entitlement.get("employee_limit", 0) or 0)

    unlimited = employee_limit in (-1, 0)
    usage_ratio = None if unlimited else (employee_count / employee_limit if employee_limit > 0 else None)
    usage_percent = None if usage_ratio is None else int(round(max(0.0, min(1.0, usage_ratio)) * 100))

    if unlimited:
        pressure = "unlimited"
    elif employee_count >= employee_limit:
        pressure = "at_limit"
    elif usage_ratio is not None and usage_ratio >= 0.8:
        pressure = "near_limit"
    else:
        pressure = "healthy"

    return {
        "plan": plan,
        "plan_label": plan.capitalize() if plan != "admin" else "Admin",
        "employee_count": employee_count,
        "employee_limit": employee_limit,
        "unlimited": unlimited,
        "usage_ratio": usage_ratio,
        "usage_percent": usage_percent,
        "pressure": pressure,
    }


def build_employee_capacity_upgrade_prompt(*, plan: str, employee_count: int, employee_limit: int) -> dict[str, str] | None:
    normalized_plan = normalize_plan_name(plan)
    if employee_limit in (-1, 0):
        return None

    count = int(employee_count or 0)
    limit = int(employee_limit or 0)
    if limit <= 0:
        return None

    if count >= limit:
        return {
            "level": "error",
            "headline": f"You've reached {limit} employees on {normalized_plan.capitalize()}.",
            "body": "Upgrade to keep full-team tracking active as your roster grows.",
        }

    usage_ratio = count / limit
    if usage_ratio >= 0.8:
        seats_left = max(0, limit - count)
        seat_label = "seat" if seats_left == 1 else "seats"
        return {
            "level": "info",
            "headline": f"{count}/{limit} employee seats are in use on {normalized_plan.capitalize()}.",
            "body": f"{seats_left} {seat_label} remain before imports or adds can hit your plan limit.",
        }

    return None


def build_advanced_value_upgrade_prompt(*, plan: str) -> dict[str, str] | None:
    normalized_plan = normalize_plan_name(plan)
    if compare_plan_names(normalized_plan, "pro"):
        return None

    return {
        "level": "info",
        "headline": "Advanced trends and deeper history are available on Pro.",
        "body": "Pro adds trend depth, coaching insights, and expanded planning/reporting views.",
    }


def build_coaching_insights_upgrade_prompt(*, plan: str) -> dict[str, str] | None:
    normalized_plan = normalize_plan_name(plan)
    if compare_plan_names(normalized_plan, "pro"):
        return None

    return {
        "level": "info",
        "headline": "Coaching Insights is available on Pro.",
        "body": "Pro includes richer coaching-history context and follow-through visibility.",
    }