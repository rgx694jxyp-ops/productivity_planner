import json

from core.runtime import datetime, st, time
from services.app_logging import log_error as _log_error_event
from services.app_logging import log_info as _log_info_event
from services.app_logging import sanitize_text

try:
    from database import get_client as get_db_client
    DB_AVAILABLE = True
    DB_ERROR = ""
except RuntimeError as error:
    DB_AVAILABLE = False
    DB_ERROR = str(error)
except ImportError as error:
    DB_AVAILABLE = False
    message = str(error)
    if "supabase" in message.lower():
        DB_ERROR = "supabase library not installed. Run: pip3 install supabase"
    else:
        DB_ERROR = f"Import error: {message}"
except Exception as error:
    DB_AVAILABLE = False
    DB_ERROR = f"Unexpected error loading database module: {type(error).__name__}: {error}"

from auth import (
    check_session_timeout,
    clear_auth_cookies,
    full_sign_out as _auth_full_sign_out,
    login_page,
    render_sign_out_button,
    restore_session_from_cookies,
    set_auth_cookies,
)
from billing import subscription_page as billing_subscription_page
from billing import verify_checkout_and_activate
from cache import (
    bust_cache,
    cached_active_flags,
    cached_all_coaching_notes,
    cached_coaching_notes_for,
    cached_employees,
    cached_targets,
    cached_uph_history,
)


def require_db() -> bool:
    if not DB_AVAILABLE:
        st.error(f"Database not available: {DB_ERROR}")
        st.info("Run `pip3 install supabase` in your terminal then restart the app.")
        return False
    return True


def full_sign_out() -> None:
    _auth_full_sign_out(bust_cache)


def show_subscription_page() -> None:
    billing_subscription_page(render_sign_out_button, full_sign_out)


def success_then_rerun(msg: str, delay: float = 0) -> None:
    st.toast(msg, icon="✅")
    st.rerun()


def tenant_log_path(base_name: str) -> str:
    import os

    directory = os.path.dirname(__file__)
    tid = st.session_state.get("tenant_id", "")
    if tid:
        return os.path.join(os.path.dirname(directory), f"{base_name}_{tid}.log")
    return os.path.join(os.path.dirname(directory), f"{base_name}.log")


def get_audit_timestamp() -> str:
    try:
        from zoneinfo import ZoneInfo
        from settings import Settings

        tenant_id = st.session_state.get("tenant_id", "")
        settings = Settings(tenant_id)
        tz_str = settings.get("timezone", "").strip()
        if tz_str:
            try:
                tz = ZoneInfo(tz_str)
                now = datetime.now(tz)
                return now.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def audit(action: str, detail: str = "") -> None:
    try:
        entry = f"{get_audit_timestamp()} | {action} | {detail}\n"
        with open(tenant_log_path("dpd_audit"), "a", encoding="utf-8") as handle:
            handle.write(entry)
    except Exception:
        pass


def log_app_error(category: str, message: str, detail: str = "", severity: str = "error") -> None:
    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    user_email = str(st.session_state.get("user_email", "") or "")
    _log_error_event(
        category,
        message,
        tenant_id=tenant_id,
        user_email=user_email,
        context={"severity": severity, "detail": detail},
    )
    try:
        from database import log_error

        log_error(
            category=category,
            message=message,
            detail=detail,
            user_email=user_email,
            tenant_id=tenant_id,
            severity=severity,
        )
    except Exception:
        print(f"[APP_ERROR] [{severity}] [{category}] {sanitize_text(message)}")


def show_user_error(
    message: str,
    *,
    next_steps: str = "",
    technical_detail: str = "",
    category: str = "app",
    severity: str = "error",
    expander_label: str = "Technical details",
) -> None:
    """Show a clean user message while preserving technical detail for diagnosis."""
    st.error(message)
    if next_steps:
        st.info(next_steps)
    if technical_detail:
        with st.expander(expander_label, expanded=False):
            st.code(str(technical_detail))
        try:
            log_app_error(category, message, detail=str(technical_detail), severity=severity)
        except Exception:
            pass


def log_operational_event(
    event_type: str,
    *,
    status: str = "info",
    detail: str = "",
    context: dict | None = None,
    tenant_id: str = "",
    user_email: str = "",
) -> None:
    """Write a JSONL operations event for production diagnostics."""
    resolved_tenant_id = str(tenant_id or st.session_state.get("tenant_id", "") or "")
    resolved_user_email = str(user_email or st.session_state.get("user_email", "") or "")
    _log_info_event(
        event_type,
        detail or event_type,
        tenant_id=resolved_tenant_id,
        user_email=resolved_user_email,
        context={"status": status, "context": context or {}},
    )

    try:
        payload = {
            "ts": get_audit_timestamp(),
            "event_type": str(event_type or "unknown"),
            "status": str(status or "info"),
            "detail": str(detail or ""),
            "tenant_id": resolved_tenant_id,
            "user_email": resolved_user_email,
            "context": context or {},
        }
        with open(tenant_log_path("dpd_ops"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _get_db_client():
    if not DB_AVAILABLE:
        raise RuntimeError(DB_ERROR)
    return get_db_client()


_audit = audit
_bust_cache = bust_cache
_cached_active_flags = cached_active_flags
_cached_all_coaching_notes = cached_all_coaching_notes
_cached_coaching_notes_for = cached_coaching_notes_for
_cached_employees = cached_employees
_cached_targets = cached_targets
_cached_uph_history = cached_uph_history
_full_sign_out = full_sign_out
_log_app_error = log_app_error
_log_operational_event = log_operational_event
_show_user_error = show_user_error
_render_sign_out_button = render_sign_out_button
_set_auth_cookies = set_auth_cookies
_success_then_rerun = success_then_rerun
_tenant_log_path = tenant_log_path
