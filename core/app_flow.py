from core.dependencies import (
    bust_cache,
    check_session_timeout,
    clear_auth_cookies,
    login_page,
    log_operational_event,
    log_app_error,
    restore_session_from_cookies,
    verify_checkout_and_activate,
)
from core.billing_cache import BILLING_CACHE_TTL_SECONDS, clear_billing_cache
from core.runtime import st, time, traceback
from ui.landing import show_landing_page, track_landing_event


def handle_logout_request() -> bool:
    if not (st.session_state.get("_logout_requested") or st.query_params.get("logout") == "1"):
        return False

    from core.session import clear_session_state

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


def handle_public_query_actions() -> None:
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


def ensure_authenticated_session() -> bool:
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


def enforce_live_session() -> bool:
    if not check_session_timeout():
        return True

    st.info("Session expired due to inactivity. Please sign in again.")
    login_page(bust_cache, log_app_error)
    return False


def sync_billing_portal_return() -> None:
    if st.query_params.get("portal") != "return":
        return

    st.query_params.clear()
    clear_billing_cache(clear_portal_feedback=True)
    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    user_id = str(st.session_state.get("user_id", "") or "")
    with st.spinner("Refreshing your subscription…"):
        try:
            synced_ok = verify_checkout_and_activate(tenant_id, user_id)
        except Exception:
            synced_ok = False

    if synced_ok:
        try:
            from database import get_subscription

            new_sub = get_subscription(tenant_id)
            if new_sub:
                st.session_state["_portal_synced_plan"] = new_sub.get("plan", "").capitalize()
        except Exception:
            pass

    st.rerun()


def enforce_subscription_access() -> bool:
    admin_emails = []
    try:
        admin_emails = [
            email.strip().lower()
            for email in st.secrets.get("ADMIN_EMAILS", "").split(",")
            if email.strip()
        ]
    except Exception:
        pass

    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    user_id = str(st.session_state.get("user_id", "") or "")
    user_email = st.session_state.get("user_email", "").lower()
    if user_email and user_email in admin_emails:
        log_operational_event(
            "access_gate_allow",
            status="allowed",
            tenant_id=tenant_id,
            user_email=user_email,
            detail="Admin allowlist bypass",
            context={"reason": "admin_email_allowlist"},
        )
        st.session_state["_sub_active"] = True
        return True

    sub_check_ts = float(st.session_state.get("_sub_check_ts", 0) or 0)
    sub_cached = st.session_state.get("_sub_check_result")
    # Keep access changes responsive without hammering billing lookups.
    cache_ttl = BILLING_CACHE_TTL_SECONDS
    if sub_cached is None or (time.time() - sub_check_ts) > cache_ttl:
        try:
            from services.billing_service import get_subscription_entitlement

            entitlement = get_subscription_entitlement(
                tenant_id=tenant_id,
                user_email=user_email,
            )
            sub_cached = entitlement["has_access"]
            st.session_state["_sub_entitlement"] = entitlement
            st.session_state["_billing_entitlement"] = entitlement
            st.session_state["_billing_entitlement_ts"] = time.time()
        except Exception as error:
            log_app_error(
                "subscription_enforcement",
                "Subscription entitlement lookup failed; falling back to allow access.",
                detail=str(error),
                severity="warning",
            )
            sub_cached = True
        st.session_state["_sub_check_result"] = sub_cached
        st.session_state["_sub_check_ts"] = time.time()

    st.session_state["_sub_active"] = bool(sub_cached)
    if sub_cached:
        return True

    try:
        stripe_sync_ok = verify_checkout_and_activate(tenant_id, user_id)
    except Exception as error:
        log_app_error(
            "subscription_enforcement",
            "Checkout verification failed during subscription enforcement.",
            detail=str(error),
            severity="warning",
        )
        stripe_sync_ok = False

    if stripe_sync_ok:
        log_operational_event(
            "access_gate_allow",
            status="allowed",
            tenant_id=tenant_id,
            user_email=user_email,
            detail="Access restored after verification",
            context={"recheck": True},
        )
        clear_billing_cache()
        st.session_state["_sub_active"] = True
        st.rerun()

    entitlement = st.session_state.get("_billing_entitlement") or st.session_state.get("_sub_entitlement") or {}
    log_operational_event(
        "access_gate_denial",
        status="denied",
        tenant_id=tenant_id,
        user_email=user_email,
        detail="Subscription gate denied app access",
        context={
            "status": entitlement.get("status", "unknown"),
            "access_reason": entitlement.get("access_reason", "unknown"),
            "plan": entitlement.get("plan", "starter"),
        },
    )

    from core.dependencies import show_subscription_page

    show_subscription_page()
    return False


def show_post_portal_feedback() -> None:
    if not st.session_state.get("_portal_synced_plan"):
        return

    synced_label = st.session_state.pop("_portal_synced_plan")
    st.toast(f"Subscription updated — you're now on the {synced_label} plan.", icon="✅")


def track_page_entry(page: str) -> None:
    prev_page = str(st.session_state.get("_last_rendered_page_key", "") or "")
    st.session_state["_entered_from_page_key"] = prev_page
    st.session_state["_last_rendered_page_key"] = page


def handle_fatal_app_error(fatal_error: Exception) -> None:
    fatal_tb = traceback.format_exc()
    try:
        log_app_error("fatal", f"Unhandled app error: {fatal_error}", detail=fatal_tb)
    except Exception:
        print(f"Fatal app error logging failed: {fatal_error}")
    st.error("A fatal app error occurred. Please refresh or contact support.")
    with st.expander("Technical details"):
        st.code(fatal_tb)