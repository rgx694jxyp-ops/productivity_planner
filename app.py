"""Productivity Planner entrypoint.

Run with:
    streamlit run app.py
"""

from core.dependencies import (
    bust_cache,
    check_session_timeout,
    clear_auth_cookies,
    login_page,
    log_app_error,
    require_db,
    restore_session_from_cookies,
    verify_checkout_and_activate,
)
from core.navigation import render_sidebar, render_subscription_banner
from core.runtime import init_runtime, st, time, traceback
from core.session import clear_session_state, init_session_state, roll_coached_yesterday
from services.email_service import EMAIL_SCHEDULER_ENABLED, email_log, run_page_render_email_check, start_email_thread
from ui.landing import show_landing_page, track_landing_event


def _handle_logout_request() -> bool:
    if not (st.session_state.get("_logout_requested") or st.query_params.get("logout") == "1"):
        return False
    clear_session_state()
    clear_auth_cookies()
    try:
        del st.query_params["logout"]
    except Exception:
        st.query_params.clear()
    st.query_params["logged_out"] = "1"
    st.session_state["show_login"] = False
    show_landing_page()
    return True


def _handle_public_query_actions() -> None:
    if st.query_params.get("start") == "1":
        st.session_state["show_login"] = True
        track_landing_event("cta_click", "sticky_get_started")
        try:
            del st.query_params["start"]
        except Exception:
            st.query_params.clear()
    if st.query_params.get("demo") == "1":
        st.session_state["lp_show_demo"] = True
        track_landing_event("cta_click", "sticky_see_demo")
        try:
            del st.query_params["demo"]
        except Exception:
            st.query_params.clear()

    invite = st.query_params.get("invite", "")
    if invite and not st.session_state.get("_pending_invite"):
        st.session_state["_pending_invite"] = invite.strip().lower()
        st.query_params.clear()


def _ensure_authenticated() -> bool:
    force_login_after_logout = st.query_params.get("logged_out") == "1"
    restored_from_cookie = False if force_login_after_logout else restore_session_from_cookies()

    if "supabase_session" in st.session_state or restored_from_cookie:
        if st.query_params.get("logged_out") == "1":
            try:
                del st.query_params["logged_out"]
            except Exception:
                st.query_params.clear()
        return True

    if not st.session_state.get("show_login", False):
        show_landing_page()
        return False

    if st.button("← Back", key="lp_back_to_landing"):
        st.session_state["show_login"] = False
        st.rerun()
    login_page(bust_cache, log_app_error)
    return False


def _sync_billing_portal_return() -> None:
    if st.query_params.get("portal") != "return":
        return

    st.query_params.clear()
    for key in (
        "_sub_active",
        "_sub_check_result",
        "_sub_check_ts",
        "_banner_sub",
        "_banner_sub_ts",
        "_current_plan",
        "_current_plan_ts",
        "_portal_synced_plan",
    ):
        st.session_state.pop(key, None)
    bust_cache()
    with st.spinner("Refreshing your subscription…"):
        try:
            synced_ok = verify_checkout_and_activate()
        except Exception:
            synced_ok = False
    if synced_ok:
        try:
            from database import get_subscription

            new_sub = get_subscription()
            if new_sub:
                st.session_state["_portal_synced_plan"] = new_sub.get("plan", "").capitalize()
        except Exception:
            pass
    st.rerun()


def _enforce_subscription() -> bool:
    admin_emails = []
    try:
        admin_emails = [email.strip().lower() for email in st.secrets.get("ADMIN_EMAILS", "").split(",") if email.strip()]
    except Exception:
        pass

    user_email = st.session_state.get("user_email", "").lower()
    if user_email and user_email in admin_emails:
        st.session_state["_sub_active"] = True
        return True

    sub_check_ts = float(st.session_state.get("_sub_check_ts", 0) or 0)
    sub_cached = st.session_state.get("_sub_check_result")
    if sub_cached is None or (time.time() - sub_check_ts) > 300:
        try:
            from database import has_active_subscription

            sub_cached = has_active_subscription()
        except Exception:
            sub_cached = True
        st.session_state["_sub_check_result"] = sub_cached
        st.session_state["_sub_check_ts"] = time.time()

    st.session_state["_sub_active"] = bool(sub_cached)
    if sub_cached:
        return True

    try:
        stripe_sync_ok = verify_checkout_and_activate()
    except Exception:
        stripe_sync_ok = False
    if stripe_sync_ok:
        st.session_state["_sub_active"] = True
        st.rerun()

    from core.dependencies import show_subscription_page

    show_subscription_page()
    return False


def _route_page(page: str) -> None:
    from pages.coaching_intel import page_coaching_intel
    from pages.cost_impact import page_cost_impact
    from pages.dashboard import page_dashboard
    from pages.email_page import page_email
    from pages.employees import page_employees
    from pages.import_page import page_import
    from pages.productivity import page_productivity
    from pages.settings_page import page_settings
    from pages.shift_plan import page_shift_plan
    from pages.supervisor import page_supervisor

    handlers = {
        "supervisor": page_supervisor,
        "dashboard": page_dashboard,
        "import": page_import,
        "employees": page_employees,
        "productivity": page_productivity,
        "shift_plan": page_shift_plan,
        "coaching_intel": page_coaching_intel,
        "cost_impact": page_cost_impact,
        "email": page_email,
        "settings": page_settings,
    }
    handler = handlers.get(page, page_import)
    try:
        handler()
    except Exception as page_error:
        tb = traceback.format_exc()
        log_app_error("page", f"Page render failed ({page}): {page_error}", detail=tb, severity="error")
        st.error("This page encountered an unexpected error.")
        with st.expander("Technical details"):
            st.code(tb)


def main() -> None:
    init_runtime()
    init_session_state()
    roll_coached_yesterday()

    if _handle_logout_request():
        st.stop()

    _handle_public_query_actions()

    if not _ensure_authenticated():
        st.stop()

    if check_session_timeout():
        st.info("Session expired due to inactivity. Please sign in again.")
        login_page(bust_cache, log_app_error)
        st.stop()

    _sync_billing_portal_return()

    if not _enforce_subscription():
        st.stop()

    if EMAIL_SCHEDULER_ENABLED:
        start_email_thread()
        run_page_render_email_check()

    if st.session_state.get("_portal_synced_plan"):
        synced_label = st.session_state.pop("_portal_synced_plan")
        st.toast(f"Subscription updated — you're now on the {synced_label} plan.", icon="✅")

    page = render_sidebar()
    prev_page = str(st.session_state.get("_last_rendered_page_key", "") or "")
    st.session_state["_entered_from_page_key"] = prev_page
    st.session_state["_last_rendered_page_key"] = page
    _route_page(page)


if __name__ == "__main__":
    init_runtime()
    render_subscription_banner()
    try:
        main()
    except Exception as fatal_error:
        fatal_tb = traceback.format_exc()
        try:
            log_app_error("fatal", f"Unhandled app error: {fatal_error}", detail=fatal_tb)
        except Exception:
            email_log(f"Fatal app error logging failed: {fatal_error}")
        st.error("A fatal app error occurred. Please refresh or contact support.")
        with st.expander("Technical details"):
            st.code(fatal_tb)
