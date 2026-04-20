"""Team page.

Informational drill-down surface with no operational action controls.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.dependencies import _cached_coaching_notes_for
from pages.common import load_goal_status_history
from services.action_query_service import get_employee_action_timeline
from services.exception_tracking_service import build_exception_context_line, list_recent_operational_exceptions
from services.follow_through_service import build_follow_through_context_line, list_recent_follow_through_events


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.fromisoformat(text[:19])
        except Exception:
            return None


def _employee_display_name(row: dict) -> str:
    name = str(row.get("Employee Name") or row.get("Employee") or "Unknown").strip() or "Unknown"
    emp_id = str(row.get("EmployeeID") or row.get("emp_id") or "").strip()
    return f"{name} ({emp_id})" if emp_id else name


def _employee_id(row: dict) -> str:
    return str(row.get("EmployeeID") or row.get("emp_id") or "").strip()


def page_team() -> None:
    st.markdown("## Team")
    st.caption("Drill-down context for trends, history, and prior logs. Operational actions are surfaced on Today.")

    goal_status, history_rows = load_goal_status_history("Loading team context…")
    goal_status = list(goal_status or [])
    history_rows = list(history_rows or [])

    if not goal_status:
        st.info("No team records are available yet.")
        return

    employees_sorted = sorted(goal_status, key=lambda row: str(row.get("Employee Name") or row.get("Employee") or "").lower())
    labels = [_employee_display_name(row) for row in employees_sorted]
    requested_employee_id = str(
        st.session_state.get("team_selected_emp_id")
        or st.session_state.get("cn_selected_emp")
        or ""
    ).strip()
    default_index = 0
    if requested_employee_id:
        for index, row in enumerate(employees_sorted):
            if _employee_id(row) == requested_employee_id:
                default_index = index
                break
    selected_label = st.selectbox("Employee", labels, index=default_index, key="team_drilldown_employee")
    selected_row = employees_sorted[labels.index(selected_label)]

    employee_id = _employee_id(selected_row)
    employee_name = str(selected_row.get("Employee Name") or selected_row.get("Employee") or "Unknown").strip() or "Unknown"
    department = str(selected_row.get("Department") or "").strip() or "Unknown"
    st.session_state["team_selected_emp_id"] = employee_id

    avg_uph = _safe_float(selected_row.get("Average UPH"))
    target_uph = _safe_float(selected_row.get("Target UPH"))
    trend_state = str(selected_row.get("trend") or "stable").replace("_", " ").title()
    goal_state = str(selected_row.get("goal_status") or "unknown").replace("_", " ").title()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Employee", employee_name)
    col2.metric("Department", department)
    col3.metric("Average UPH", f"{avg_uph:.1f}" if avg_uph is not None else "-")
    col4.metric("Target UPH", f"{target_uph:.1f}" if target_uph is not None else "-")
    st.caption(f"Trend: {trend_state} | Goal status: {goal_state}")

    employee_history = []
    for row in history_rows:
        row_emp_id = str(row.get("EmployeeID") or row.get("emp_id") or "").strip()
        row_emp_name = str(row.get("Employee Name") or row.get("Employee") or "").strip()
        if (employee_id and row_emp_id == employee_id) or (not employee_id and row_emp_name == employee_name):
            employee_history.append(row)

    if employee_history:
        chart_rows: list[dict] = []
        for row in employee_history:
            dt_text = str(row.get("Date") or row.get("work_date") or row.get("Week") or "").strip()
            dt_value = _parse_dt(dt_text)
            if dt_value is None:
                continue
            uph = _safe_float(row.get("UPH") if "UPH" in row else row.get("uph") if "uph" in row else row.get("Average UPH"))
            if uph is None:
                continue
            chart_rows.append({"Date": dt_value.date().isoformat(), "UPH": uph})

        if chart_rows:
            history_df = pd.DataFrame(chart_rows).drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
            st.line_chart(history_df.set_index("Date")["UPH"], use_container_width=True)
            with st.expander("Daily history", expanded=False):
                st.dataframe(history_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No historical points found for this employee.")

    with st.expander("Prior notes", expanded=False):
        notes = list(_cached_coaching_notes_for(employee_name) or [])
        if not notes:
            st.caption("No prior notes found.")
        else:
            for note in notes[:15]:
                when = str(note.get("date") or note.get("created_at") or "").strip()
                author = str(note.get("author") or note.get("coach") or "").strip()
                text = str(note.get("note") or note.get("notes") or "").strip()
                context_bits = [bit for bit in [when[:10], author] if bit]
                st.markdown(f"- {' | '.join(context_bits) if context_bits else 'Note'}")
                if text:
                    st.caption(text)

    tenant_id = str(st.session_state.get("tenant_id") or "").strip()

    with st.expander("Operational exception history", expanded=False):
        exceptions = list_recent_operational_exceptions(tenant_id=tenant_id, employee_id=employee_id, limit=20)
        if not exceptions:
            st.caption("No operational exceptions recorded.")
        else:
            for row in exceptions:
                context = build_exception_context_line(row)
                summary = str(row.get("summary") or "").strip()
                st.markdown(f"- {context}")
                if summary:
                    st.caption(summary)

    with st.expander("Follow-through history", expanded=False):
        follow_rows = list_recent_follow_through_events(tenant_id=tenant_id, employee_id=employee_id, limit=25)
        if not follow_rows:
            st.caption("No follow-through logs recorded.")
        else:
            for row in follow_rows:
                context = build_follow_through_context_line(row)
                details = str(row.get("details") or row.get("notes") or "").strip()
                st.markdown(f"- {context or 'Follow-through'}")
                if details:
                    st.caption(details)

    with st.expander("Action timeline", expanded=False):
        timeline_rows = list(get_employee_action_timeline(employee_id, tenant_id=tenant_id) or [])[:40]
        if not timeline_rows:
            st.caption("No action timeline records found.")
        else:
            for row in timeline_rows:
                event_type = str(row.get("event_type") or "event").replace("_", " ").title()
                event_at = str(row.get("event_at") or "").strip()
                status = str(row.get("status") or "").strip()
                linked_exception_id = str(row.get("linked_exception_id") or "").strip()
                bits = [bit for bit in [event_type, event_at[:10], status] if bit]
                if linked_exception_id:
                    bits.append(f"Exception {linked_exception_id[:8]}")
                st.markdown(f"- {' | '.join(bits)}")
                note = str(row.get("notes") or "").strip()
                if note:
                    st.caption(note)
