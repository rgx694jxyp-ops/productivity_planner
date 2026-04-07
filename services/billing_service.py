"""Billing workflow orchestration for the Settings page."""

from datetime import datetime

from services.settings_service import format_iso_date_human, get_plan_alternatives, get_plan_constants


def get_subscription_entitlement(tenant_id: str = "", user_email: str = "") -> dict:
    """Return a single subscription/access truth object for all billing gates and UI."""
    out = {
        "has_access": False,
        "status": "none",
        "plan": "starter",
        "employee_limit": 0,
        "show_payment_banner": False,
        "show_pending_downgrade_banner": False,
        "pending_plan": "",
        "pending_change_at": "",
        "access_reason": "none",
        # Optional convenience fields for shared UI widgets.
        "employee_count": 0,
        "cancel_at_period_end": False,
        "current_period_end": "",
    }

    try:
        from database import PLAN_LIMITS, get_employee_count, get_subscription
    except Exception as exc:
        out["access_reason"] = f"billing_dependencies_unavailable:{exc}"
        return out

    try:
        sub = get_subscription(tenant_id) or {}
        if not sub:
            out["access_reason"] = "no_subscription"
            return out

        plan = str(sub.get("plan") or "starter").lower()
        status = str(sub.get("status") or "none").lower()
        pending_plan = str(sub.get("pending_plan") or "").strip().lower()
        pending_change_at = str(sub.get("pending_change_at") or "").strip()
        period_end = str(sub.get("current_period_end") or "").strip()
        cancel_at_period_end = bool(sub.get("cancel_at_period_end"))

        try:
            limit = int(sub.get("employee_limit", 0) or 0)
        except Exception:
            limit = 0
        if limit in (0, None):
            limit = int(PLAN_LIMITS.get(plan, 25) or 25)

        out["plan"] = plan
        out["status"] = status
        out["employee_limit"] = limit
        out["pending_plan"] = pending_plan
        out["pending_change_at"] = pending_change_at
        out["cancel_at_period_end"] = cancel_at_period_end
        out["current_period_end"] = period_end

        try:
            out["employee_count"] = int(get_employee_count(tenant_id) or 0)
        except Exception:
            out["employee_count"] = 0

        if status in ("active", "trialing"):
            out["has_access"] = True
            out["access_reason"] = status
        elif status == "past_due":
            out["show_payment_banner"] = True
            if period_end:
                try:
                    from datetime import datetime as _dt, timedelta, timezone

                    pe = _dt.fromisoformat(period_end.replace("Z", "+00:00"))
                    if _dt.now(timezone.utc) <= (pe + timedelta(hours=48)):
                        out["has_access"] = True
                        out["access_reason"] = "grace_period"
                    else:
                        out["access_reason"] = "past_due_blocked"
                except Exception:
                    out["access_reason"] = "past_due_blocked"
            else:
                out["access_reason"] = "past_due_blocked"
        elif status in ("unpaid", "incomplete"):
            out["show_payment_banner"] = True
            out["access_reason"] = status
        elif status == "canceled":
            out["access_reason"] = "canceled"
        else:
            out["access_reason"] = status or "unknown"

        rank = {"starter": 1, "pro": 2, "business": 3, "admin": 99, "enterprise": 100}
        if pending_plan and pending_plan != plan and rank.get(pending_plan, 0) < rank.get(plan, 0):
            out["show_pending_downgrade_banner"] = True

        return out
    except Exception as exc:
        out["access_reason"] = f"entitlement_error:{exc}"
        return out


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
        # Keep Manage action on the generic billing portal because some Stripe
        # workspaces reject/loop on subscription_update deep-links.
        manage_plan_url = portal_url

        price_map = {
            "starter": _get_config("STRIPE_PRICE_STARTER") or "",
            "pro": _get_config("STRIPE_PRICE_PRO") or "",
            "business": _get_config("STRIPE_PRICE_BUSINESS") or "",
        }

        pending_plan = str(sub.get("pending_plan") or "").strip().lower()
        pending_change_at = sub.get("pending_change_at") or ""
        pending_date = "period end"
        pending_cancel = bool(sub.get("cancel_at_period_end"))
        pending_kind = "cancel" if pending_cancel else ""
        if pending_change_at:
            _fmt = format_iso_date_human(pending_change_at)
            pending_date = _fmt or renew_str or "period end"
        elif renew_str:
            pending_date = renew_str

        # Fallback: when Stripe portal schedules a change but DB pending fields
        # have not been reconciled yet, read live Stripe pending_update state.
        if not pending_plan:
            try:
                from database import get_live_stripe_subscription_status

                live = get_live_stripe_subscription_status(tenant_id) or {}
                live_pending = str(live.get("pending_plan") or "").strip().lower()
                if live.get("has_pending_update") and live_pending:
                    pending_plan = live_pending
                    pending_kind = "plan_change"
                    try:
                        _pending_ts = live.get("pending_change_at_ts")
                        if _pending_ts:
                            pending_date = datetime.fromtimestamp(int(_pending_ts)).strftime("%b %d, %Y")
                        else:
                            live_period_end = live.get("current_period_end")
                            if live_period_end:
                                pending_date = datetime.fromtimestamp(int(live_period_end)).strftime("%b %d, %Y")
                    except Exception:
                        pass
                elif bool(live.get("cancel_at_period_end")):
                    pending_cancel = True
                    pending_kind = "cancel"
            except Exception:
                pass

        if pending_plan and not pending_kind:
            pending_kind = "plan_change"

        plan_order, plan_info, gains, rank = get_plan_constants()
        alternatives = get_plan_alternatives(plan_raw, pending_plan)
        # Product decision: in-app change cards should only offer upgrades.
        alternatives = [p for p in alternatives if rank.get(p, 0) > rank.get(plan_raw, 0)]

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
                "pending_cancel": pending_cancel,
                "pending_kind": pending_kind,
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
        from database import _get_config, get_subscription, modify_subscription
        # Block in-app downgrades; upgrades remain immediate.
        sub = get_subscription(tenant_id) or {}
        current_plan = str(sub.get("plan", "starter") or "starter").lower()
        price_to_plan = {
            _get_config("STRIPE_PRICE_STARTER") or "": "starter",
            _get_config("STRIPE_PRICE_PRO") or "": "pro",
            _get_config("STRIPE_PRICE_BUSINESS") or "": "business",
        }
        target_plan = price_to_plan.get(target_price, "")
        plan_rank = {"starter": 1, "pro": 2, "business": 3}
        if target_plan and plan_rank.get(target_plan, 0) < plan_rank.get(current_plan, 0):
            return {
                "success": False,
                "data": None,
                "error": "Downgrades are disabled in this screen. Keep your current plan and contact support if you need a billing change.",
                "warnings": [],
            }

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
