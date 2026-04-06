"""Billing workflow orchestration for the Settings page."""

from services.settings_service import format_iso_date_human, get_plan_alternatives, get_plan_constants


def get_billing_dashboard(tenant_id: str, app_origin: str) -> dict:
    """Load subscription + derived billing state for the Settings Billing tab."""
    try:
        from database import (
            _get_config,
            create_billing_portal_url,
            get_employee_count,
            get_subscription,
        )
    except Exception as exc:
        return {
            "success": False,
            "data": None,
            "error": f"Billing dependencies unavailable: {exc}",
            "warnings": [],
        }

    try:
        sub = get_subscription(tenant_id)
        if not sub:
            return {
                "success": True,
                "data": {
                    "has_subscription": False,
                    "app_url": app_origin or "http://localhost:8501",
                },
                "error": None,
                "warnings": [],
            }

        plan_raw = str(sub.get("plan", "unknown") or "unknown").lower()
        status = str(sub.get("status", "unknown") or "unknown")
        limit_val = int(sub.get("employee_limit", 0) or 0)
        limit_str = "Unlimited" if limit_val == -1 else str(limit_val)
        emp_count = int(get_employee_count(tenant_id) or 0)
        renew_str = format_iso_date_human(sub.get("current_period_end", ""))

        app_url = app_origin or "http://localhost:8501"
        return_url = f"{app_url}/?portal=return"
        portal_url = create_billing_portal_url(return_url=return_url)
        manage_plan_url = create_billing_portal_url(
            return_url=return_url,
            flow="subscription_update",
        ) or portal_url

        price_map = {
            "starter": _get_config("STRIPE_PRICE_STARTER") or "",
            "pro": _get_config("STRIPE_PRICE_PRO") or "",
            "business": _get_config("STRIPE_PRICE_BUSINESS") or "",
        }

        pending_plan = str(sub.get("pending_plan") or "").strip().lower()
        pending_change_at = sub.get("pending_change_at") or ""
        pending_date = "period end"
        if pending_change_at:
            _fmt = format_iso_date_human(pending_change_at)
            pending_date = _fmt or renew_str or "period end"
        elif renew_str:
            pending_date = renew_str

        plan_order, plan_info, gains, rank = get_plan_constants()
        alternatives = get_plan_alternatives(plan_raw, pending_plan)

        return {
            "success": True,
            "data": {
                "has_subscription": True,
                "sub": sub,
                "plan_raw": plan_raw,
                "plan_label": plan_raw.capitalize(),
                "status": status,
                "limit_str": limit_str,
                "emp_count": emp_count,
                "renew_str": renew_str,
                "portal_url": portal_url,
                "manage_plan_url": manage_plan_url,
                "price_map": price_map,
                "pending_plan": pending_plan,
                "pending_date": pending_date,
                "plan_order": plan_order,
                "plan_info": plan_info,
                "gains": gains,
                "rank": rank,
                "alternatives": alternatives,
                "app_url": app_url,
            },
            "error": None,
            "warnings": [],
        }
    except Exception as exc:
        return {
            "success": False,
            "data": None,
            "error": str(exc),
            "warnings": [],
        }


def request_plan_change(target_price: str, tenant_id: str) -> dict:
    """Request plan change in Stripe and normalize return shape."""
    try:
        from database import modify_subscription
        ok, msg = modify_subscription(target_price, tenant_id)
        return {
            "success": bool(ok),
            "data": {"ok": bool(ok), "message": msg or ""},
            "error": None if ok else (msg or "Could not change plan."),
            "warnings": [],
        }
    except Exception as exc:
        return {
            "success": False,
            "data": None,
            "error": str(exc),
            "warnings": [],
        }
