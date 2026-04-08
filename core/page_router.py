from core.dependencies import log_app_error
from core.runtime import st, traceback


def dispatch_page(page: str) -> None:
    from pages.coaching_intel import page_coaching_intel
    from pages.cost_impact import page_cost_impact
    from pages.dashboard import page_dashboard
    from pages.email_page import page_email
    from pages.employees import page_employees
    from pages.import_page import page_import
    from pages.productivity import page_productivity
    from pages.settings_page import page_settings
    from pages.shift_plan import page_shift_plan
    from pages.today import page_today

    handlers = {
        "supervisor": page_today,
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