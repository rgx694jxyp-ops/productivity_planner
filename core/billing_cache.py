from cache import bust_cache
from core.runtime import st


BILLING_CACHE_TTL_SECONDS = 30

_BILLING_SESSION_KEYS = (
    "_sub_active",
    "_sub_check_result",
    "_sub_check_ts",
    "_sub_entitlement",
    "_banner_sub",
    "_banner_sub_ts",
    "_billing_entitlement",
    "_billing_entitlement_ts",
    "_current_plan",
    "_current_plan_ts",
)


def clear_billing_cache(*, clear_checkout_state: bool = False, clear_portal_feedback: bool = False) -> None:
    for key in _BILLING_SESSION_KEYS:
        st.session_state.pop(key, None)

    for key in list(st.session_state.keys()):
        if key.startswith("_live_subscription_fallback_") or key.startswith("_live_subscription_fallback_ts_"):
            st.session_state.pop(key, None)

    if clear_checkout_state:
        st.session_state.pop("_checkout_url", None)
        st.session_state.pop("_checkout_plan", None)

    if clear_portal_feedback:
        st.session_state.pop("_portal_synced_plan", None)

    bust_cache()