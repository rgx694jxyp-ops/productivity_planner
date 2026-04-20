from functools import lru_cache

from core.dependencies import log_app_error
from core.runtime import st, traceback


@lru_cache(maxsize=32)
def _get_handlers() -> dict[str, callable]:
    from pages.coaching_intel import page_coaching_intel
    from pages.cost_impact import page_cost_impact
    from pages.dashboard import page_dashboard
    from pages.email_page import page_email
    from pages.import_page import page_import
    from pages.productivity import page_productivity
    from pages.settings_page import page_settings
    from pages.shift_plan import page_shift_plan
    from pages.team import page_team
    from pages.today import page_today

    return {
        "today": page_today,
        "team": page_team,
        "supervisor": page_today,
        "dashboard": page_dashboard,
        "import": page_import,
        "employees": page_team,
        "productivity": page_productivity,
        "shift_plan": page_shift_plan,
        "coaching_intel": page_coaching_intel,
        "cost_impact": page_cost_impact,
        "email": page_email,
        "settings": page_settings,
    }


def dispatch_page(page: str) -> None:
    try:
        handlers = _get_handlers()
    except Exception as import_error:
        tb = traceback.format_exc()
        log_app_error("page", f"Page module import failed ({page}): {import_error}", detail=tb, severity="error")
        st.error("The app could not load one or more page modules.")
        with st.expander("Technical details"):
            st.code(tb)
        return

    handler = handlers.get(str(page or "").strip().lower(), handlers["today"])

    try:
        handler()
    except Exception as page_error:
        tb = traceback.format_exc()
        log_app_error("page", f"Page render failed ({page}): {page_error}", detail=tb, severity="error")
        st.error("This page encountered an unexpected error.")
        with st.expander("Technical details"):
            st.code(tb)