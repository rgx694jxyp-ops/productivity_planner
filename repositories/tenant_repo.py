"""Data access for tenant-level records."""

from __future__ import annotations

from typing import Optional

from repositories._common import first_row, get_client, get_tenant_id


def get_tenant(tenant_id: str = "", columns: str = "*") -> Optional[dict]:
    """Return the tenant row for the current tenant, or None."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return None

    sb = get_client()
    return first_row(sb.table("tenants").select(columns).eq("id", tid))


def set_tenant_stripe_customer_id(stripe_customer_id: str, tenant_id: str = "") -> bool:
    """Persist a Stripe customer id on the tenant row."""
    tid = tenant_id or get_tenant_id()
    if not tid or not stripe_customer_id:
        return False

    try:
        sb = get_client()
        sb.table("tenants").update({"stripe_customer_id": stripe_customer_id}).eq("id", tid).execute()
        return True
    except Exception:
        return False
