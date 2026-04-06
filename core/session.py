from datetime import date

from core.runtime import st


SESSION_DEFAULTS = {
    "uploaded_sessions": [],
    "submission_plan": None,
    "split_overrides": {},
    "import_step": 1,
    "alloc_rows": [],
    "alloc_date": None,
    "chart_months": 12,
    "trend_weeks": 4,
    "target_uph": 0.0,
    "top_pct": 10,
    "bot_pct": 10,
    "smart_merge": True,
    "raw_rows": [],
    "csv_headers": [],
    "mapping": {},
    "mapping_ready": False,
    "history": [],
    "top_performers": [],
    "dept_report": {},
    "dept_trends": [],
    "weekly_summary": [],
    "employee_rolling_avg": [],
    "employee_risk": [],
    "goal_status": [],
    "trend_data": {},
    "pipeline_done": False,
    "pipeline_error": "",
    "warnings": [],
}


def init_session_state() -> None:
    for key, value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def roll_coached_yesterday() -> None:
    last_date = st.session_state.get("_coached_date", "")
    today = date.today().isoformat()
    if last_date and last_date != today:
        st.session_state["_coached_yesterday"] = int(st.session_state.get("_coached_today", 0))
        st.session_state["_coached_today"] = 0
        st.session_state.pop("_welcome_shown", None)
    st.session_state["_coached_date"] = today


def clear_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
