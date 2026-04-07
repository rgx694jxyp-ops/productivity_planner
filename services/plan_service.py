"""
Centralized plan enforcement helpers for service layer.
"""
from typing import Any

from services.billing_service import get_subscription_entitlement

PLAN_RANKS = {
    "starter": 1,
    "pro": 2,
    "business": 3,
    "admin": 99,
    "enterprise": 100,
}

PLAN_FEATURES = {
    "starter": {
        "max_seats": 25,
        "max_invites": 25,
        "max_import_employees": 25,
        "features": {
            "basic": True,
            "advanced": False,
            "coaching_insights": False,
            "team_management": True,
        },
    },
    "pro": {
        "max_seats": 100,
        "max_invites": 100,
        "max_import_employees": 100,
        "features": {
            "basic": True,
            "advanced": True,
            "coaching_insights": True,
            "team_management": True,
        },
    },
    "business": {
        "max_seats": float("inf"),
        "max_invites": float("inf"),
        "max_import_employees": float("inf"),
        "features": {
            "basic": True,
            "advanced": True,
            "coaching_insights": True,
            "team_management": True,
            "priority_support": True,
        },
    },
    "admin": {
        "max_seats": float("inf"),
        "max_invites": float("inf"),
        "max_import_employees": float("inf"),
        "features": {
            "basic": True,
            "advanced": True,
            "coaching_insights": True,
            "team_management": True,
            "priority_support": True,
        },
    },
    "enterprise": {
        "max_seats": float("inf"),
        "max_invites": float("inf"),
        "max_import_employees": float("inf"),
        "features": {
            "basic": True,
            "advanced": True,
            "coaching_insights": True,
            "team_management": True,
            "priority_support": True,
        },
    },
}

FEATURE_MIN_PLAN = {
    "advanced": "pro",
    "coaching_insights": "pro",
    "priority_support": "business",
}

FEATURE_MESSAGES = {
    "advanced": "This feature requires a Pro plan or higher.",
    "coaching_insights": "Coaching Insights requires a Pro plan or higher.",
    "priority_support": "This feature requires a Business plan.",
}

EMPLOYEE_BASE_VIEWS = ["Employee History", "Performance Journal"]
EMPLOYEE_PAID_VIEWS = ["Coaching Insights"]
PRODUCTIVITY_MONITOR_STARTER = ["📅 Weekly", "📋 Priority List"]
PRODUCTIVITY_MONITOR_PAID = ["📊 Goal Status", "📈 Trends", "📉 Rolling Avg", "📅 Weekly", "📋 Priority List", "🧑‍🏫 Coaching"]
PRODUCTIVITY_PLAN_PAID = ["🎯 Dept Goals", "💰 Labor Cost"]
PRODUCTIVITY_VIEW_FEATURES = {
    "📊 Goal Status": "advanced",
    "📈 Trends": "advanced",
    "📉 Rolling Avg": "advanced",
    "🧑‍🏫 Coaching": "advanced",
    "🎯 Dept Goals": "advanced",
    "💰 Labor Cost": "advanced",
}

class PlanEnforcementError(Exception):
    pass


def normalize_plan_name(plan_name: str) -> str:
    return str(plan_name or "starter").lower().strip() or "starter"


def get_plan_rank(plan_name: str) -> int:
    return PLAN_RANKS.get(normalize_plan_name(plan_name), 1)


def compare_plan_names(current_plan: str, required_plan: str) -> bool:
    return get_plan_rank(current_plan) >= get_plan_rank(required_plan)


def get_plan_definition(plan_name: str) -> dict[str, Any]:
    return PLAN_FEATURES.get(normalize_plan_name(plan_name), PLAN_FEATURES["starter"])

def get_current_plan(tenant_id: str) -> str:
    """Return the current plan name for a tenant."""
    ent = get_subscription_entitlement(tenant_id=tenant_id)
    return normalize_plan_name(ent.get("plan") or "starter")


def has_minimum_plan(tenant_id: str, required_plan: str) -> bool:
    return compare_plan_names(get_current_plan(tenant_id), required_plan)


def get_feature_upgrade_message(feature_name: str) -> str:
    return FEATURE_MESSAGES.get(feature_name, "This feature is not available on your current plan.")

def can_access_feature(tenant_id: str, feature_name: str) -> bool:
    plan = get_current_plan(tenant_id)
    return bool(get_plan_definition(plan).get("features", {}).get(feature_name, False))


def get_employee_limit(tenant_id: str) -> int:
    ent = get_subscription_entitlement(tenant_id=tenant_id)
    limit = int(ent.get("employee_limit", 0) or 0)
    if limit:
        return limit
    max_seats = get_plan_definition(ent.get("plan") or "starter").get("max_seats", 0)
    return -1 if max_seats == float("inf") else int(max_seats or 0)


def get_import_limit(tenant_id: str) -> int:
    limit = get_employee_limit(tenant_id)
    if limit == -1:
        return -1
    fallback = get_plan_definition(get_current_plan(tenant_id)).get("max_import_employees", limit)
    return int(fallback or limit)


def get_invite_limit(tenant_id: str) -> int:
    ent = get_subscription_entitlement(tenant_id=tenant_id)
    if not ent.get("has_access") and get_plan_rank(ent.get("plan") or "starter") < get_plan_rank("admin"):
        return 0
    limit = get_plan_definition(get_current_plan(tenant_id)).get("max_invites", float("inf"))
    return -1 if limit == float("inf") else int(limit or 0)


def evaluate_people_limit(
    tenant_id: str,
    current_count: int,
    additional_count: int,
    limit_type: str = "employee",
) -> dict[str, Any]:
    plan = get_current_plan(tenant_id)
    normalized_type = str(limit_type or "employee").lower().strip()
    if normalized_type == "invite":
        limit = get_invite_limit(tenant_id)
        limit_key = "invite_limit"
    else:
        limit = get_employee_limit(tenant_id)
        limit_key = "employee_limit"
    current_total = int(current_count or 0)
    additional_total = int(additional_count or 0)
    projected_total = current_total + additional_total
    allowed = limit in (-1, 0) or projected_total <= limit
    slots_left = -1 if limit == -1 else max(0, limit - current_total)
    result = {
        "allowed": allowed,
        "plan": plan,
        "current_count": current_total,
        "additional_count": additional_total,
        "projected_total": projected_total,
        "slots_left": slots_left,
        "limit_type": normalized_type,
    }
    result[limit_key] = limit
    return result


def evaluate_employee_limit(tenant_id: str, current_count: int, additional_count: int) -> dict[str, Any]:
    return evaluate_people_limit(
        tenant_id=tenant_id,
        current_count=current_count,
        additional_count=additional_count,
        limit_type="employee",
    )


def evaluate_import_limit(tenant_id: str, current_count: int, new_unique_count: int) -> dict[str, Any]:
    result = evaluate_employee_limit(tenant_id, current_count, new_unique_count)
    result["import_limit"] = get_import_limit(tenant_id)
    return result


def evaluate_invite_limit(tenant_id: str, current_member_count: int, additional_count: int = 1) -> dict[str, Any]:
    return evaluate_people_limit(
        tenant_id=tenant_id,
        current_count=current_member_count,
        additional_count=additional_count,
        limit_type="invite",
    )


def enforce_people_limit(
    tenant_id: str,
    current_count: int,
    additional_count: int,
    limit_type: str = "employee",
) -> dict[str, Any]:
    result = evaluate_people_limit(
        tenant_id=tenant_id,
        current_count=current_count,
        additional_count=additional_count,
        limit_type=limit_type,
    )
    if result["allowed"]:
        return result

    if result["limit_type"] == "invite":
        raise PlanEnforcementError(
            f"Plan '{result['plan']}' allows max {result['invite_limit']} team seats, requested {result['projected_total']}."
        )

    raise PlanEnforcementError(
        f"Plan '{result['plan']}' allows max {result['employee_limit']} employee seats, requested {result['projected_total']}."
    )


def can_manage_team(tenant_id: str, user_role: str) -> bool:
    role_name = str(user_role or "").lower().strip()
    return role_name == "admin" or compare_plan_names(get_current_plan(tenant_id), "admin")


def get_available_employee_views(tenant_id: str) -> list[str]:
    views = list(EMPLOYEE_BASE_VIEWS)
    if can_access_feature(tenant_id, "coaching_insights"):
        views.extend(EMPLOYEE_PAID_VIEWS)
    return views


def get_productivity_navigation(tenant_id: str) -> dict[str, list[str]]:
    if can_access_feature(tenant_id, "advanced"):
        monitor_options = list(PRODUCTIVITY_MONITOR_PAID)
        plan_options = list(PRODUCTIVITY_PLAN_PAID)
    else:
        monitor_options = list(PRODUCTIVITY_MONITOR_STARTER)
        plan_options = []
    mode_options = ["Monitor"] + (["Plan"] if plan_options else [])
    return {
        "mode_options": mode_options,
        "monitor_options": monitor_options,
        "plan_options": plan_options,
    }


def enforce_productivity_view_access(tenant_id: str, view_name: str) -> None:
    feature_name = PRODUCTIVITY_VIEW_FEATURES.get(view_name)
    if feature_name:
        enforce_plan_or_raise(tenant_id, feature_name)

def enforce_seat_limit(tenant_id: str, requested_count: int) -> None:
    enforce_people_limit(
        tenant_id=tenant_id,
        current_count=0,
        additional_count=requested_count,
        limit_type="employee",
    )

def enforce_plan_or_raise(tenant_id: str, feature_name: str) -> None:
    if not can_access_feature(tenant_id, feature_name):
        raise PlanEnforcementError(get_feature_upgrade_message(feature_name))

# Plans that unlock the full feature set (pro / business / admin / enterprise).
_PAID_PLANS = {"pro", "business", "admin", "enterprise"}

def is_paid_plan(plan_name: str) -> bool:
    """Return True if *plan_name* grants access to paid/advanced features."""
    return str(plan_name or "").lower() in _PAID_PLANS
