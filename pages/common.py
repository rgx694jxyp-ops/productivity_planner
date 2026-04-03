import streamlit as st

from app import require_db


def load_goal_status_history(spinner_text: str = "Loading data…"):
    """Shared bootstrap for pages that depend on goal_status/history in session."""
    if not require_db():
        return None, None

    if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
        with st.spinner(spinner_text):
            try:
                from pages.employees import _build_archived_productivity

                _build_archived_productivity()
            except Exception:
                pass

    return st.session_state.get("goal_status", []), st.session_state.get("history", [])
