"""Data access for subscriptions/billing records and Stripe-backed mutations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from repositories._common import first_row, get_client, get_config, get_tenant_id
from repositories.employees_repo import get_employee_count as _employees_get_employee_count
from services.app_logging import log_error, log_warn

PLAN_LIMITS = {
    "starter": 25,
    "pro": 100,
    "business": -1,
    "trial": 10,
}


def get_plan_limits() -> dict:
    """Return plan limits, preferring database module overrides when present."""
    try:
        import database

        limits = getattr(database, "PLAN_LIMITS", None)
        if isinstance(limits, dict) and limits:
            return limits
    except Exception:
        pass
    return PLAN_LIMITS


def get_subscription(
    tenant_id: str = "",
    columns: str = "*",
    allow_live_fallback: bool = True,
) -> Optional[dict]:
    """Return the subscription row for a tenant, with optional Stripe live fallback."""
    try:
        import database

        if not hasattr(database, "get_client") and hasattr(database, "get_subscription"):
            try:
                return database.get_subscription(tenant_id)
            except TypeError:
                return database.get_subscription(tenant_id=tenant_id)
    except Exception:
        pass

    tid = tenant_id or get_tenant_id()
    if not tid:
        return None

    sb = get_client()
    row = first_row(sb.table("subscriptions").select(columns).eq("tenant_id", tid))
    if row:
        return row

    if not allow_live_fallback:
        return None

    fallback = _get_live_subscription_fallback(tid)
    if not fallback:
        return None

    if columns.strip() == "*":
        return fallback

    requested_columns = {part.strip() for part in columns.split(",") if part.strip()}
    return {key: value for key, value in fallback.items() if key in requested_columns}


def update_subscription_state(updates: dict, tenant_id: str = "") -> bool:
    """Update mirrored subscription row and bump updated_at."""
    tid = tenant_id or get_tenant_id()
    if not tid or not updates:
        return False

    payload = dict(updates)
    payload["updated_at"] = datetime.utcnow().isoformat() + "Z"
    try:
        sb = get_client()
        sb.table("subscriptions").update(payload).eq("tenant_id", tid).execute()
        return True
    except Exception as error:
        log_error(
            "repo_billing_subscription_update_failed",
            "Repository subscription state update failed.",
            tenant_id=tid,
            context={"update_keys": sorted(list(payload.keys()))},
            error=error,
        )
        return False


def get_employee_count(tenant_id: str = "") -> int:
    """Return employee count, with monkeypatch-friendly database fallback for tests."""
    try:
        import database

        if not hasattr(database, "get_client") and hasattr(database, "get_employee_count"):
            return int(database.get_employee_count(tenant_id) or 0)
    except Exception:
        pass
    return int(_employees_get_employee_count(tenant_id) or 0)


def _get_live_subscription_fallback(tenant_id: str = "") -> Optional[dict]:
    import database

    return database._get_live_subscription_fallback(tenant_id)


def modify_subscription(new_price_id: str, tenant_id: str = "") -> tuple:
    """Compatibility wrapper for existing Stripe update flow."""
    try:
        import database

        return database.modify_subscription(new_price_id, tenant_id)
    except Exception as error:
        log_error(
            "repo_billing_modify_subscription_failed",
            "Repository Stripe subscription modification failed.",
            tenant_id=tenant_id or get_tenant_id(),
            context={"has_price_id": bool(new_price_id)},
            error=error,
        )
        raise


def get_live_stripe_subscription_status(tenant_id: str = "") -> Optional[dict]:
    """Compatibility wrapper for existing Stripe status sync flow."""
    try:
        import database

        return database.get_live_stripe_subscription_status(tenant_id)
    except Exception as error:
        log_warn(
            "repo_billing_live_status_failed",
            "Repository live Stripe subscription lookup failed.",
            tenant_id=tenant_id or get_tenant_id(),
            error=error,
        )
        raise


def create_billing_portal_url(
    return_url: str,
    tenant_id: str = "",
    target_price_id: str = "",
    flow: str = "",
) -> Optional[str]:
    """Compatibility wrapper for existing billing portal session creation."""
    try:
        import database

        return database.create_billing_portal_url(
            return_url=return_url,
            tenant_id=tenant_id,
            target_price_id=target_price_id,
            flow=flow,
        )
    except Exception as error:
        log_error(
            "repo_billing_portal_url_failed",
            "Repository billing portal URL creation failed.",
            tenant_id=tenant_id or get_tenant_id(),
            context={"flow": str(flow or ""), "has_target_price_id": bool(target_price_id)},
            error=error,
        )
        raise
