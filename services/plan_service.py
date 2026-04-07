"""
Centralized plan enforcement helpers for service layer.
"""
from typing import Any
from database import get_subscription_by_tenant

# Example plan definitions (should match your Stripe/Supabase logic)
PLAN_FEATURES = {
    "starter": {"max_seats": 25, "features": {"basic": True, "advanced": False}},
    "pro": {"max_seats": 100, "features": {"basic": True, "advanced": True}},
    "business": {"max_seats": float("inf"), "features": {"basic": True, "advanced": True, "priority_support": True}},
}

class PlanEnforcementError(Exception):
    pass

def get_current_plan(tenant_id: str) -> str:
    """Return the current plan name for a tenant."""
    sub = get_subscription_by_tenant(tenant_id)
    if not sub or not sub.get("plan"):
        return "starter"  # Default/fallback
    return sub["plan"]

def can_access_feature(tenant_id: str, feature_name: str) -> bool:
    plan = get_current_plan(tenant_id)
    return PLAN_FEATURES.get(plan, {}).get("features", {}).get(feature_name, False)

def enforce_seat_limit(tenant_id: str, requested_count: int) -> None:
    plan = get_current_plan(tenant_id)
    max_seats = PLAN_FEATURES.get(plan, {}).get("max_seats", 0)
    if requested_count > max_seats:
        raise PlanEnforcementError(f"Plan '{plan}' allows max {max_seats} seats, requested {requested_count}.")

def enforce_plan_or_raise(tenant_id: str, feature_name: str) -> None:
    if not can_access_feature(tenant_id, feature_name):
        raise PlanEnforcementError(f"Feature '{feature_name}' not available on current plan.")
