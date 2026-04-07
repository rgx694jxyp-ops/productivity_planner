"""Non-UI helpers for the Settings page."""

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


def format_iso_date_human(value: str) -> str:
    """Format an ISO date string into 'Mon DD, YYYY' or empty string."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


def get_plan_constants() -> tuple[list[str], dict, dict, dict]:
    """Return plan order, display info, delta/gain matrix, and rank map."""
    plan_order = ["starter", "pro", "business"]
    plan_info = {
        "starter": {"label": "Starter", "price": "$30/mo", "emp": "Up to 25", "clr": "#6b7280"},
        "pro": {"label": "Pro", "price": "$59/mo", "emp": "Up to 100", "clr": "#2563eb"},
        "business": {"label": "Business", "price": "$99/mo", "emp": "Unlimited", "clr": "#7c3aed"},
    }
    gains = {
        ("starter", "pro"): [
            "75 more employee slots (25 -> 100)",
            "Goal setting & UPH targets",
            "Employee trend analysis",
            "Underperformer alerts",
            "Custom date ranges",
            "Coaching notes per employee",
        ],
        ("pro", "business"): ["Unlimited employees (100 -> inf)"],
        ("starter", "business"): [
            "Unlimited employees",
            "Goal setting & UPH targets",
            "Employee trend analysis",
            "Underperformer alerts",
            "Custom date ranges",
            "Coaching notes per employee",
        ],
        ("pro", "starter"): [
            "75 employee slots (100 -> 25)",
            "Goal setting & UPH targets",
            "Employee trend analysis",
            "Underperformer alerts",
            "Custom date ranges",
            "Coaching notes per employee",
        ],
        ("business", "pro"): ["Unlimited employees (capped at 100)"],
        ("business", "starter"): [
            "Unlimited employees",
            "Goal setting & UPH targets",
            "Employee trend analysis",
            "Underperformer alerts",
            "Custom date ranges",
            "Coaching notes per employee",
        ],
    }
    rank = {"starter": 1, "pro": 2, "business": 3}
    return plan_order, plan_info, gains, rank


def get_plan_alternatives(current_plan: str, pending_plan: str) -> list[str]:
    """Return selectable plans excluding current plan, unless a pending change exists."""
    plan_order, _, _, _ = get_plan_constants()
    if pending_plan:
        return []
    return [p for p in plan_order if p != current_plan]


def escape_html(text: str) -> str:
    """Escape minimal HTML chars for safe markdown rendering."""
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def summarize_error_counts(errors: list[dict]) -> tuple[int, int, int]:
    """Return (error_count, warning_count, info_count)."""
    err_count = sum(1 for e in errors if e.get("severity") == "error")
    warn_count = sum(1 for e in errors if e.get("severity") == "warning")
    info_count = sum(1 for e in errors if e.get("severity") == "info")
    return err_count, warn_count, info_count


def format_error_timestamp(raw_ts: str, tz_offset_min: int | None = None) -> str:
    """Convert UTC ISO timestamp to local time.

    If a browser offset (minutes) is provided, use it; otherwise fall back to
    the Python process local timezone.
    """
    try:
        raw = str(raw_ts or "").replace("Z", "+00:00")
        if not raw:
            return ""
        utc_dt = datetime.fromisoformat(raw)
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        if tz_offset_min is None:
            local_dt = utc_dt.astimezone()
        else:
            local_dt = utc_dt.astimezone(timezone(offset=timedelta(minutes=-int(tz_offset_min))))
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(raw_ts or "")[:19].replace("T", " ")


def get_tenant_timezone_name(tenant_id: str = "") -> str:
    """Return the configured timezone name for a tenant, or empty string."""
    tid = str(tenant_id or "").strip()
    if not tid:
        return ""
    try:
        from settings import Settings

        settings = Settings(tid)
        return str(settings.get("timezone", "") or "").strip()
    except Exception:
        return ""


def get_tenant_local_now(tenant_id: str = "") -> datetime:
    """Return the current datetime in the tenant's configured timezone if available."""
    tz_str = get_tenant_timezone_name(tenant_id)
    if tz_str and ZoneInfo:
        try:
            return datetime.now(ZoneInfo(tz_str))
        except Exception:
            pass
    return datetime.now()
