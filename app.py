"""Pulse Ops entrypoint.

Run with:
    streamlit run app.py
"""

from core.app_flow import (
    enforce_live_session,
    enforce_subscription_access,
    ensure_authenticated_session,
    handle_fatal_app_error,
    handle_logout_request,
    handle_public_query_actions,
    show_post_portal_feedback,
    sync_billing_portal_return,
    track_page_entry,
)
from core.navigation import render_app_navigation
from core.page_router import dispatch_page
from core.runtime import init_runtime, st
from core.session import init_session_state, roll_coached_yesterday


def main() -> None:
    init_runtime()
    init_session_state()
    roll_coached_yesterday()

    if handle_logout_request():
        st.stop()

    handle_public_query_actions()

    if not ensure_authenticated_session():
        st.stop()

    if not enforce_live_session():
        st.stop()

    sync_billing_portal_return()

    if not enforce_subscription_access():
        st.stop()

    show_post_portal_feedback()

    page = render_app_navigation()
    track_page_entry(page)
    dispatch_page(page)


if __name__ == "__main__":
    init_runtime()
    try:
        main()
    except Exception as fatal_error:
        handle_fatal_app_error(fatal_error)
