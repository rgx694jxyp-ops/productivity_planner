from core.dependencies import (
    _cached_active_flags,
    _cached_all_coaching_notes,
    _cached_coaching_notes_for,
    _cached_employees,
    _cached_targets,
    _get_db_client,
    _log_app_error,
    require_db,
)
from services.plan_service import get_available_employee_views
from core.runtime import _html_mod, date, datetime, io, pd, st, time, traceback, init_runtime
from domain.operational_exceptions import EXCEPTION_CATEGORIES

init_runtime()
from services.coaching_service import find_coaching_impact
from services.employee_service import (
    build_employee_history_frames,
    filter_employees_by_department,
    load_employee_history_workflow,
    parse_history_range,
)
from services.action_lifecycle_service import log_coaching_lifecycle_entry
from services.action_query_service import get_employee_action_timeline, get_employee_actions
from services.activity_comparison_service import list_recent_activity_comparisons, summarize_activity_comparisons
from services.employee_detail_service import build_employee_detail_context
from services.team_process_service import build_team_process_contexts
from services.exception_tracking_service import (
    build_exception_context_line,
    create_operational_exception,
    list_recent_operational_exceptions,
    resolve_operational_exception,
)
from services.follow_through_service import (
    FOLLOW_THROUGH_STATUSES,
    build_follow_through_context_line,
    log_follow_through_event,
    summarize_follow_through_events,
)
from services.employees_service import _build_archived_productivity
from database import add_coaching_note, archive_coaching_notes, delete_coaching_note
from export_manager import export_employee
from cache import (
    raw_cached_active_flags as _raw_cached_active_flags,
    raw_cached_all_coaching_notes as _raw_cached_all_coaching_notes,
    raw_cached_coaching_notes_for as _raw_cached_coaching_notes_for,
)
from ui.components import (
    _render_breadcrumb,
    _render_session_context_bar,
    show_coaching_impact,
)
from ui.floor_language import translate_to_floor_language
from ui.state_panels import (
    show_error_state,
    show_healthy_state,
    show_loading_state,
    show_low_confidence_state,
    show_no_data_state,
    show_partial_data_state,
    show_success_state,
)
from ui.traceability_panel import render_traceability_panel
from services.trend_classification_service import normalize_trend_state
try:
    from pages.common import _build_coaching_recommendations
except Exception:
    def _build_coaching_recommendations():
        return []


def _normalize_label_text(value, max_len: int = 64) -> str:
    """Normalize labels to keep employee dropdown text readable."""
    s = str(value or "").replace("\x00", " ").strip()
    s = " ".join(s.split())
    s = s.replace("|", " ").replace("<", " ").replace(">", " ")
    s = s.strip(" '\"")
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s or "Unknown"


def _render_employee_exception_panel(*, tenant_id: str, emp_id: str, emp_name: str, emp_dept: str) -> None:
    st.subheader("Operational Exceptions")
    st.caption("Operational context linked to this employee that may help explain recent performance.")

    recent_rows = list_recent_operational_exceptions(tenant_id=tenant_id, employee_id=emp_id, limit=20)
    open_rows = [row for row in recent_rows if str(row.get("status") or "") == "open"]

    with st.expander("Log linked exception", expanded=False):
        with st.form(f"employee_exception_form_{emp_id}", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                exception_date = st.date_input("Date", value=date.today(), key=f"employee_exception_date_{emp_id}")
            with c2:
                category = st.selectbox(
                    "Category",
                    EXCEPTION_CATEGORIES,
                    index=EXCEPTION_CATEGORIES.index("unknown"),
                    key=f"employee_exception_category_{emp_id}",
                )
            with c3:
                shift = st.text_input("Shift", value="", key=f"employee_exception_shift_{emp_id}")
            process_name = st.text_input("Process", value=emp_dept, key=f"employee_exception_process_{emp_id}")
            summary = st.text_input(
                "What happened",
                placeholder="Example: training overlap slowed pack station",
                key=f"employee_exception_summary_{emp_id}",
            )
            notes = st.text_area("Notes (optional)", value="", key=f"employee_exception_notes_{emp_id}")
            submitted = st.form_submit_button("Save exception", type="primary")
            if submitted:
                _user_role = str(st.session_state.get("user_role", "") or "")
                result = create_operational_exception(
                    exception_date=exception_date.isoformat(),
                    category=category,
                    summary=summary,
                    employee_id=emp_id,
                    employee_name=emp_name,
                    department=emp_dept,
                    shift=shift,
                    process_name=process_name,
                    notes=notes,
                    created_by=str(st.session_state.get("user_email", "supervisor") or "supervisor"),
                    tenant_id=tenant_id,
                    user_role=_user_role,
                )
                if result:
                    show_success_state(f"{emp_name}: operational exception saved.")
                    st.rerun()
                else:
                    show_error_state("Operational exception could not be saved right now.")

    if not recent_rows:
        show_partial_data_state("No linked operational exceptions are on file for this employee yet.")
        return

    m1, m2 = st.columns(2)
    m1.metric("Open exceptions", len(open_rows))
    m2.metric("Recent exception history", len(recent_rows))

    for row in recent_rows[:6]:
        exception_id = str(row.get("id") or "")
        status = str(row.get("status") or "open").title()
        with st.container(border=True):
            st.markdown(f"**{row.get('summary', 'Operational exception')}**")
            st.caption(build_exception_context_line(row) + f" | Status: {status}")
            if str(row.get("notes") or "").strip():
                st.write(str(row.get("notes") or ""))
            if str(row.get("resolution_note") or "").strip():
                st.caption(f"Resolution: {row.get('resolution_note')}")
            if str(row.get("status") or "") == "open":
                if st.button("Resolve", key=f"employee_exception_resolve_{exception_id}"):
                    resolved = resolve_operational_exception(
                        exception_id,
                        resolution_note="Resolved from employee detail.",
                        resolved_by=str(st.session_state.get("user_email", "supervisor") or "supervisor"),
                        tenant_id=tenant_id,
                    )
                    if resolved:
                        show_success_state(f"{emp_name}: operational exception resolved.")
                        st.rerun()
                    else:
                        show_error_state("Operational exception could not be resolved right now.")


def _render_employee_follow_through_panel(*, tenant_id: str, emp_id: str, emp_name: str) -> None:
    st.subheader("Follow-through Log")
    st.caption("Quick log of what was checked, scheduled, or observed. New entries are stored in the lightweight follow-through log.")

    exception_rows = list_recent_operational_exceptions(tenant_id=tenant_id, employee_id=emp_id, limit=12)
    exception_lookup = {str(row.get("id") or ""): row for row in exception_rows}
    summary = summarize_follow_through_events(tenant_id=tenant_id, employee_id=emp_id, limit=20)
    rows = summary.get("rows") or []

    exception_options = {"Not linked to an exception": ""}
    for row in exception_rows:
        exception_id = str(row.get("id") or "")
        if not exception_id:
            continue
        label = f"#{exception_id} | {str(row.get('summary') or 'Operational exception')[:60]}"
        exception_options[label] = exception_id

    with st.expander("Log quick follow-through", expanded=False):
        with st.form(f"employee_follow_through_form_{emp_id}", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                status = st.selectbox("Status", FOLLOW_THROUGH_STATUSES, index=0, key=f"follow_through_status_{emp_id}")
            with c2:
                outcome_label = st.selectbox(
                    "Outcome (optional)",
                    ["Not captured", "Improved", "No change", "Worse", "Blocked", "Pending"],
                    index=0,
                    key=f"follow_through_outcome_{emp_id}",
                )
            with c3:
                has_due_date = st.checkbox("Add due date", value=False, key=f"follow_through_due_toggle_{emp_id}")
            due_date = st.date_input(
                "Due date",
                value=date.today() + __import__("datetime").timedelta(days=3),
                key=f"follow_through_due_date_{emp_id}",
                disabled=not has_due_date,
            )
            linked_exception_label = st.selectbox(
                "Linked exception",
                list(exception_options.keys()),
                key=f"follow_through_exception_{emp_id}",
            )
            details = st.text_area(
                "Notes/details",
                height=100,
                placeholder="Example: checked scanner lane, swapped spare device, recheck tomorrow morning.",
                key=f"follow_through_details_{emp_id}",
            )
            submitted = st.form_submit_button("Save follow-through", type="primary")
            if submitted:
                outcome_map = {
                    "Not captured": "",
                    "Improved": "improved",
                    "No change": "no_change",
                    "Worse": "worse",
                    "Blocked": "blocked",
                    "Pending": "pending",
                }
                result = log_follow_through_event(
                    employee_id=emp_id,
                    linked_exception_id=exception_options.get(linked_exception_label, ""),
                    owner=str(st.session_state.get("user_email", "supervisor") or "supervisor"),
                    status=status,
                    due_date=due_date.isoformat() if has_due_date else "",
                    details=details,
                    outcome=outcome_map.get(outcome_label, ""),
                    tenant_id=tenant_id,
                )
                if result:
                    show_success_state(f"{emp_name}: follow-through saved.")
                    st.rerun()
                else:
                    show_error_state("Follow-through could not be saved right now.")

    if not rows:
        show_partial_data_state("No follow-through entries are on file for this employee yet.")
        return

    m1, m2 = st.columns(2)
    m1.metric("Recent entries", int(summary.get("total_count", 0) or 0))
    m2.metric("Open items", int(summary.get("open_count", 0) or 0))

    for row in rows[:6]:
        with st.container(border=True):
            details = str(row.get("details") or row.get("notes") or "Follow-through entry")
            st.markdown(f"**{details[:120]}**")
            st.caption(build_follow_through_context_line(row))
            linked_exception_id = str(row.get("linked_exception_id") or "")
            if linked_exception_id and linked_exception_id in exception_lookup:
                st.caption(f"Linked exception: {exception_lookup[linked_exception_id].get('summary', 'Operational exception')}")
            if str(row.get("outcome") or "").strip():
                st.caption(f"Outcome: {row.get('outcome')}")


def _render_activity_comparison_card(comparison: dict, *, show_employee_id: bool = False) -> None:
    with st.container(border=True):
        st.markdown(f"**{comparison.get('outcome_label', 'No clear change yet')}**")
        if show_employee_id and str(comparison.get("employee_id") or "").strip():
            st.caption(f"Employee: {comparison.get('employee_id')}")
        st.caption(
            f"What happened: {comparison.get('what_happened')} | Compared to what: {comparison.get('compared_to_what')}"
        )
        st.caption(f"Why shown: {comparison.get('why_shown')}")
        st.caption(
            f"Confidence: {comparison.get('confidence_label')} | Data supports: {comparison.get('data_supports')}"
        )
        comparison_breakdown = comparison.get("comparison_breakdown") or {}
        for key in ("compared_to_target", "compared_to_recent_performance", "compared_to_recent_average"):
            text = str(comparison_breakdown.get(key) or "").strip()
            if text:
                st.caption(text)
        st.caption(str(comparison.get("time_context") or ""))
        st.caption(str(comparison.get("workload_context") or ""))
        st.caption(str(comparison.get("data_completeness_note") or ""))
        details_text = str(comparison.get("details") or "").strip()
        if details_text:
            with st.expander("Logged activity detail", expanded=False):
                st.write(details_text)
                before_dates = comparison.get("before_dates") or []
                after_dates = comparison.get("after_dates") or []
                st.caption(
                    f"Before dates used: {', '.join(before_dates[:7]) or 'None'} | After dates used: {', '.join(after_dates[:7]) or 'None'}"
                )


def _render_employee_signal_summary(detail_context: dict) -> None:
    summary = detail_context.get("signal_summary") or {}
    st.subheader("Signal Summary")
    with st.container(border=True):
        line_1 = str(summary.get("line_1") or "Employee · Team")
        line_2 = str(summary.get("line_2") or summary.get("current_state") or detail_context.get("current_state") or "No clear change yet")
        line_3 = str(summary.get("line_3") or "Observed: n/a (n/a)")
        line_4 = str(summary.get("line_4") or "Compared to: n/a avg (n/a)")
        line_5 = str(summary.get("line_5") or f"Confidence: {str(summary.get('confidence_label') or detail_context.get('confidence_label') or 'Low')}")

        for idx, line in enumerate((line_1, line_2, line_3, line_4, line_5), start=1):
            text = str(line or "").strip()
            if not text:
                continue
            if idx == 1:
                st.markdown(f"**{text}**")
            else:
                st.write(text)


def _render_employee_signal_explainer(detail_context: dict) -> None:
    why = detail_context.get("why_this_is_showing") or {}
    basis = detail_context.get("what_this_is_based_on") or {}
    summary = detail_context.get("signal_summary") or {}

    why_line = "Recently surfaced"
    basis_line = str(summary.get("line_4") or "").strip().replace("Compared to: ", "")
    data_note = str(
        summary.get("data_completeness_note")
        or basis.get("missing_data_note")
        or detail_context.get("data_completeness_note")
        or ""
    ).strip()

    if bool(summary.get("low_data_state") or detail_context.get("low_data_state")):
        one_line_note = str(summary.get("low_data_note") or detail_context.get("low_data_note") or "Only limited recent records available").strip()
        if one_line_note:
            with st.expander("Signal explanation", expanded=False):
                st.caption(one_line_note)
        return

    has_additional_value = bool(why_line or basis_line or data_note)
    if not has_additional_value:
        return

    with st.expander("Signal explanation", expanded=False):
        if why_line:
            st.write(f"Why: {why_line}")
        if basis_line:
            st.write(f"Based on: {basis_line}")
        if data_note and str(summary.get("data_completeness_label") or "").strip().lower() not in {"", "data mostly complete"}:
            st.caption(f"Data note: {data_note}")


def _render_related_action_events(*, timeline: list[dict]) -> None:
    st.subheader("Related Action Events")
    st.caption("Recent action and follow-through events linked to this employee. Full timeline remains available lower in the page.")
    if not timeline:
        show_partial_data_state("No related action events are on file for this employee yet.")
        return

    for event in timeline[:5]:
        with st.container(border=True):
            event_label = str(event.get("event_type") or "event").replace("_", " ").title()
            event_time = str(event.get("event_at") or "")[:16].replace("T", " ") or "Time not recorded"
            st.markdown(f"**{event_label}**")
            st.caption(event_time)
            context_bits = []
            if str(event.get("action_id") or "").strip():
                context_bits.append(f"Action #{event.get('action_id')}")
            if str(event.get("linked_exception_id") or "").strip():
                context_bits.append(f"Exception #{event.get('linked_exception_id')}")
            if str(event.get("status") or "").strip():
                context_bits.append(str(event.get("status") or "").replace("_", " "))
            if context_bits:
                st.caption(" | ".join(context_bits))
            if str(event.get("outcome") or "").strip():
                st.caption(f"Outcome: {event.get('outcome')}")
            note_text = str(event.get("notes") or "").strip()
            if note_text:
                st.write(note_text[:220])


def _render_employee_activity_comparisons(*, tenant_id: str, emp_id: str, expected_uph: float, history_rows: list[dict]) -> None:
    comparisons = list_recent_activity_comparisons(
        tenant_id=tenant_id,
        history_rows=history_rows,
        expected_uph_by_employee={emp_id: expected_uph},
        employee_id=emp_id,
        include_weak_signals=True,
        limit=4,
    )
    st.subheader("Before/After Summaries")
    st.caption("Deterministic before/after view of whether recent logged activity was followed by improvement, similar conditions, or performance still below expected.")
    if not comparisons:
        show_partial_data_state("No recent logged activity has enough comparable before/after data yet.")
        return
    strong_comparisons = [row for row in comparisons if not bool(row.get("is_weak_signal"))]
    weak_comparisons = [row for row in comparisons if bool(row.get("is_weak_signal"))]
    summary = summarize_activity_comparisons(strong_comparisons)
    m1, m2, m3 = st.columns(3)
    m1.metric("Improved", int(summary.get("improved_count", 0) or 0))
    m2.metric("No clear change yet", int(summary.get("no_clear_change_count", 0) or 0))
    m3.metric("Still below expected", int(summary.get("still_below_expected_count", 0) or 0))
    if not strong_comparisons:
        show_low_confidence_state("Recent comparisons are currently low-confidence and are hidden from primary summary cards until more comparable data arrives.")
    for comparison in strong_comparisons:
        _render_activity_comparison_card(comparison)
    if weak_comparisons:
        with st.expander(f"Low-confidence comparisons ({len(weak_comparisons)})", expanded=False):
            st.caption("These are shown for transparency but excluded from the primary signal summary because of incomplete comparison data.")
            for comparison in weak_comparisons:
                _render_activity_comparison_card(comparison)


def _render_team_activity_comparisons(*, tenant_id: str, history_rows: list[dict], goal_status: list[dict]) -> None:
    expected_uph_by_employee = {
        str(row.get("EmployeeID") or ""): float(row.get("Target UPH") or 0.0)
        for row in goal_status or []
        if str(row.get("EmployeeID") or "").strip()
    }
    comparisons = list_recent_activity_comparisons(
        tenant_id=tenant_id,
        history_rows=history_rows,
        expected_uph_by_employee=expected_uph_by_employee,
        per_employee_latest_only=True,
        include_weak_signals=False,
        limit=6,
    )
    st.subheader("Recent Logged Activity Outcomes")
    st.caption("Latest deterministic before/after comparisons across the team based on recent logged activity.")
    if not comparisons:
        show_partial_data_state("Recent logged activity does not yet have enough comparable before/after data across the team.")
        return
    summary = summarize_activity_comparisons(comparisons)
    m1, m2, m3 = st.columns(3)
    m1.metric("Improved", int(summary.get("improved_count", 0) or 0))
    m2.metric("No clear change yet", int(summary.get("no_clear_change_count", 0) or 0))
    m3.metric("Still below expected", int(summary.get("still_below_expected_count", 0) or 0))
    for comparison in comparisons:
        _render_activity_comparison_card(comparison, show_employee_id=True)


def _render_team_process_view(
    *,
    history_rows: list[dict],
    goal_status: list[dict],
    filtered_emps: list[dict],
) -> None:
    st.subheader("Team / Process Signals")
    st.caption("Use this view to understand whether recent patterns are isolated to one person or systemic across a process.")

    context = build_team_process_contexts(goal_status_rows=goal_status, history_rows=history_rows)
    cards = context.get("cards") or []
    if not cards:
        show_partial_data_state("No team/process signal context is available yet.")
        return

    if not bool(context.get("has_notable_change")):
        show_healthy_state()
        st.caption(str(context.get("healthy_message") or "No meaningful team-level changes from recent performance."))

    employee_name_by_id = {
        str(employee.get("emp_id") or ""): str(employee.get("name") or employee.get("emp_id") or "Unknown")
        for employee in filtered_emps or []
    }

    for card in cards[:6]:
        process_name = str(card.get("process_name") or "Unassigned")
        with st.container(border=True):
            st.markdown(f"**{process_name}**")
            c1, c2, c3, c4 = st.columns(4)
            c1.caption("Current state")
            c1.write(str(card.get("current_state") or "").capitalize())
            c2.caption("Compared to what")
            c2.write(str(card.get("compared_to_what") or ""))
            c3.caption("Confidence")
            c3.write(str(card.get("confidence_label") or "Low").lower())
            c4.caption("Data completeness")
            c4.write(str(card.get("data_completeness_label") or "Limited data").lower())
            st.caption(str(card.get("data_completeness_note") or ""))
            if str(card.get("trend_explanation") or "").strip():
                st.caption(str(card.get("trend_explanation") or ""))
            st.caption(str(card.get("workload_context") or ""))
            comparison_breakdown = card.get("comparison_breakdown") or {}
            for key in ("compared_to_target", "compared_to_recent_performance", "compared_to_recent_average"):
                text = str(comparison_breakdown.get(key) or "").strip()
                if text:
                    st.caption(text)

            pattern_messages = [str(item) for item in (card.get("pattern_messages") or []) if str(item).strip()]
            if pattern_messages:
                st.markdown("**Pattern signals**")
                for message in pattern_messages[:3]:
                    st.write(f"- {message}")

            st.markdown("**Why this is being surfaced**")
            for signal in (card.get("major_signals") or [])[:3]:
                with st.container(border=False):
                    st.caption(f"What happened: {signal.get('what_happened')}")
                    st.caption(f"Compared to what: {signal.get('compared_to_what')}")
                    st.caption(f"Why now: {signal.get('why_showing')}")

            affected_ids = [str(eid) for eid in (card.get("employee_ids") or []) if str(eid).strip()]
            if affected_ids:
                st.caption(f"People affected: {int(card.get('affected_people_count') or 0)}")
                drill_cols = st.columns(min(3, len(affected_ids)))
                for idx, employee_id in enumerate(affected_ids[:3]):
                    employee_label = employee_name_by_id.get(employee_id, employee_id)
                    if drill_cols[idx].button(
                        f"Open {employee_label}",
                        key=f"team_process_open_employee_{process_name}_{employee_id}",
                        use_container_width=True,
                    ):
                        st.session_state["cn_selected_emp"] = employee_id
                        st.rerun()

            with st.expander("Time-based breakdown", expanded=False):
                trend_points = card.get("trend_points") or []
                if not trend_points:
                    st.caption("No recent trend points are available for this process.")
                else:
                    trend_df = pd.DataFrame(trend_points)
                    chart_columns = ["Date", "UPH"]
                    if "Target UPH" in trend_df.columns and trend_df["Target UPH"].notna().any():
                        chart_columns.append("Target UPH")
                    chart_df = trend_df[chart_columns].copy()
                    chart_df["Date"] = pd.to_datetime(chart_df["Date"], errors="coerce")
                    chart_df = chart_df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")
                    st.line_chart(
                        chart_df[[column for column in chart_df.columns if column in {"UPH", "Target UPH"}]],
                        use_container_width=True,
                    )
                    periods = card.get("time_breakdown") or {}
                    st.caption(
                        "Recent comparison windows: "
                        f"trailing {len(periods.get('trailing_dates') or [])} day(s), "
                        f"prior {len(periods.get('prior_dates') or [])} day(s)."
                    )

            with st.expander("Included and excluded supporting data", expanded=False):
                included_records = card.get("included_records") or []
                excluded_records = card.get("excluded_records") or []
                e1, e2 = st.columns(2)
                e1.metric("Included records", len(included_records))
                e2.metric("Excluded records", len(excluded_records))
                if included_records:
                    st.dataframe(pd.DataFrame(included_records), use_container_width=True, hide_index=True)
                else:
                    st.caption("No included records in this recent window.")
                if excluded_records:
                    st.dataframe(pd.DataFrame(excluded_records), use_container_width=True, hide_index=True)
                else:
                    st.caption("No excluded records in this recent window.")

            with st.expander("Source import context", expanded=False):
                source_references = card.get("source_references") or []
                if not source_references:
                    st.caption("No source import/job references were attached to these process records.")
                else:
                    st.dataframe(pd.DataFrame(source_references), use_container_width=True, hide_index=True)

def page_employees():
    st.title("👥 Employees")
    if not require_db(): return
    tenant_id = str(st.session_state.get("tenant_id", "") or "")

    _trace_ctx = st.session_state.get("_drill_traceability_context") or {}
    if _trace_ctx and str(_trace_ctx.get("drill_down_screen", "")) in {"employee_detail", "team_process"}:
        render_traceability_panel(_trace_ctx, heading="Signal source context")

    # Apply requested view switch before employees_view_tab widget is instantiated.
    _pending_emp_view = st.session_state.pop("_employees_set_view", None)
    if _pending_emp_view:
        st.session_state["emp_view"] = _pending_emp_view
        st.session_state["employees_view_tab"] = _pending_emp_view

    _sel_emp_id = st.session_state.get("cn_selected_emp")
    if _sel_emp_id:
        _emps = _cached_employees() or []
        _sel_emp = next((e for e in _emps if str(e.get("emp_id", "")) == str(_sel_emp_id)), None)
        _gs = st.session_state.get("goal_status", [])
        _gs_match = next((r for r in _gs if str(r.get("EmployeeID", "")) == str(_sel_emp_id)), None)
        if _sel_emp:
            _name = _sel_emp.get("name", _sel_emp_id)
            _dept = _sel_emp.get("department", "")
            _status = ""
            _trend = ""
            if _gs_match:
                _status = _gs_match.get("goal_status", "").replace("_", " ").title()
                _trend = {"up": "↑", "down": "↓", "flat": "→"}.get(_gs_match.get("trend", ""), "")
            st.markdown(f"**Selected Employee:** {_name} · {_dept} {_trend}")
            if _status:
                st.caption(f"Status: {_status}")

    try:
        tenant_id = st.session_state.get("tenant_id")
        _views = get_available_employee_views(tenant_id)
        _default_view = st.session_state.get("emp_view", "Performance Journal")
        if _default_view not in _views:
            _default_view = "Performance Journal"
        if "employees_view_tab" not in st.session_state or st.session_state.get("employees_view_tab") not in _views:
            st.session_state["employees_view_tab"] = _default_view
        _selected_view = st.radio(
            "Employees view",
            _views,
            horizontal=True,
            key="employees_view_tab",
            label_visibility="collapsed",
        )
        st.session_state["emp_view"] = _selected_view
        if _selected_view == "Employee History":
            _emp_history()
        elif _selected_view == "Performance Journal":
            _emp_coaching()
        else:
            _emp_ai_coaching()
    except Exception as e:
        show_error_state(f"Employees view could not load cleanly: {e}")
        _log_app_error("employees", f"Employee page error: {e}", detail=traceback.format_exc())



@st.fragment
def _emp_history():
    st.subheader("Employee UPH history")
    emps = _cached_employees()
    if not emps:
        show_no_data_state()
        return

    # ── Department filter → populates employee dropdown ───────────────────────
    depts    = sorted({e.get("department","") for e in emps if e.get("department")})
    dept_sel = st.selectbox("Filter by department", ["All departments"] + depts, key="eh_dept")

    filtered_emps = filter_employees_by_department(emps, dept_sel)

    if not filtered_emps:
        show_partial_data_state("No employees are currently mapped to that department filter.")
        return

    # Employee dropdown: Name — Department — ID
    emp_opts = {
        f"{_normalize_label_text(e.get('name',''))} — {_normalize_label_text(e.get('department','') or 'No dept', max_len=28)} — {e['emp_id']}": e["emp_id"]
        for e in filtered_emps
    }
    chosen = st.selectbox("Select employee", list(emp_opts.keys()), key="eh_emp")
    emp_id = emp_opts[chosen]

    from datetime import timedelta as _tdelta
    dc1, dc2 = st.columns(2)
    _def_from = (date.today() - _tdelta(days=90)).strftime("%m/%d/%Y")
    _def_to   = date.today().strftime("%m/%d/%Y")
    from_str  = dc1.text_input("From", value=st.session_state.get("eh_from", _def_from),
                                key="eh_from_input", placeholder="MM/DD/YYYY")
    to_str    = dc2.text_input("To",   value=st.session_state.get("eh_to",   _def_to),
                                key="eh_to_input",   placeholder="MM/DD/YYYY")
    _range = parse_history_range(from_str, to_str, default_days=90)
    st.session_state["eh_from"] = from_str
    st.session_state["eh_to"]   = to_str
    _hist_result = load_employee_history_workflow(
        filtered_emps,
        emp_id,
        _range["from_iso"],
        _range["to_iso"],
    )
    history = (_hist_result.get("data") or {}).get("history", [])

    if not history:
        show_partial_data_state("No history is available for this employee in the selected date range.")
        return

    _frames = build_employee_history_frames(history)
    _frame_data = _frames.get("data") or {}
    avg_uph = _frame_data.get("avg_uph")
    st.metric(f"Avg UPH ({from_str} – {to_str})", f"{avg_uph:.2f}" if avg_uph else "No data")

    df = _frame_data.get("df")
    df_chart = _frame_data.get("df_chart")
    if not df_chart.empty:
        st.line_chart(df_chart.set_index("Date")[["UPH"]], use_container_width=True)
    else:
        show_low_confidence_state("No reliable pace values were found for this date range.")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("⬇️ Export employee history"):
        show_loading_state("Preparing employee history export.")
        with st.spinner("Generating…"):
            data = export_employee(emp_id)
        st.download_button(f"⬇️ Download {emp_id}_history.xlsx", data,
                           f"employee_{emp_id}_{date.today()}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@st.fragment
def _emp_ai_coaching():
    """Show AI-powered coaching recommendations based on performance data."""
    st.subheader("🤖 Coaching Insights")
    st.caption("Smart recommendations based on employee performance, goals, and trends.")

    if not st.session_state.get("pipeline_done") and not st.session_state.get("_archived_loaded"):
        _build_archived_productivity(st.session_state)

    recs = _build_coaching_recommendations()
    if not recs:
        show_partial_data_state("Coaching insight context is not available yet. Add productivity history and targets to populate this view.")
        return

    # Summary metrics
    _high = sum(1 for r in recs if r["priority"] == "high")
    _med  = sum(1 for r in recs if r["priority"] == "medium")
    _stars = sum(1 for r in recs if r["priority"] == "star")
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("🔴 Urgent", _high)
    mc2.metric("🟡 Monitor", _med)
    mc3.metric("🟢 On Track", sum(1 for r in recs if r["priority"] == "low"))
    mc4.metric("⭐ Stars", _stars)

    st.markdown("---")

    # Filter
    _filter = st.radio("Show", ["All", "🔴 Higher risk", "🟡 Observed risk", "⭐ Top performers"],
                        horizontal=True, key="coaching_filter")

    for rec in recs:
        if _filter == "🔴 Higher risk" and rec["priority"] != "high":
            continue
        if _filter == "🟡 Observed risk" and rec["priority"] not in ("high", "medium"):
            continue
        if _filter == "⭐ Top performers" and rec["priority"] != "star":
            continue

        # Priority badge
        _badge = {"high": "🔴", "medium": "🟡", "low": "🟢", "star": "⭐"}.get(rec["priority"], "")
        _uph_str = f" — {rec['uph']} UPH" if rec["uph"] else ""
        _target_str = f" (target: {rec['target']})" if rec["target"] else ""

        with st.expander(f"{_badge} **{rec['name']}** · {rec['dept']}{_uph_str}{_target_str} · {rec['status']}"):
            for action in rec["actions"]:
                st.markdown(f"→ {action}")

    st.markdown("---")
    st.caption("Recommendations are generated from UPH data, department targets, and performance trends. "
               "Review and adapt based on your direct knowledge of each employee.")


def _emp_coaching():
    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    emps  = _cached_employees()
    flags = _cached_active_flags()
    history_rows = st.session_state.get("history", [])
    if not emps:
        show_no_data_state()
        return

    # ── Build employee list — all employees, annotate who has notes / is flagged
    emp_ids_with_notes = _cached_all_coaching_notes()
    all_depts = sorted({e.get("department","") for e in emps if e.get("department")})
    dept_sel = st.session_state.get("cn_dept", "All departments")
    if dept_sel not in ["All departments", *all_depts]:
        dept_sel = "All departments"
        st.session_state["cn_dept"] = dept_sel

    # ── Manager signal list ───────────────────────────────────────────────────
    # Auto-surfaces employees with below-goal/trending-down signals.
    gs = st.session_state.get("goal_status", [])
    if "dismissed_actions" not in st.session_state:
        st.session_state.dismissed_actions = set()

    action_items = []
    for r in gs:
        eid  = str(r.get("EmployeeID", r.get("Employee Name", "")))
        name = r.get("Employee Name", "")
        dept = r.get("Department", "")
        trend      = normalize_trend_state(r.get("trend", ""))
        goal_st    = r.get("goal_status", "")
        change_pct = r.get("change_pct", 0)
        avg_uph    = r.get("Average UPH", 0)
        target     = r.get("Target UPH", "—")

        reasons = []
        if trend == "declining":
            reasons.append(f"Performance slipping ({change_pct:+.1f}%)")
        elif trend == "inconsistent":
            reasons.append("Recent pace is inconsistent")
        if goal_st == "below_goal":
            reasons.append(f"Below target (UPH {avg_uph:.1f} vs target {target})")

        if reasons:
            action_key = f"{eid}|{'|'.join(reasons)}"
            if action_key not in st.session_state.dismissed_actions:
                action_items.append({
                    "eid": eid, "name": name, "dept": dept,
                    "reasons": reasons, "key": action_key,
                    "trend": trend, "goal_st": goal_st,
                })

    if action_items:
        with st.expander(f"📋 **Manager Signal List** — {len(action_items)} active signal(s)", expanded=True):
            st.caption("Employees currently trending down or below goal in the latest observed data.")
            for ai in action_items:
                ac1, ac2, ac3 = st.columns([3, 5, 1])
                badge = ""
                if ai["trend"] == "declining": badge += " ↓"
                elif ai["trend"] == "improving": badge += " ↑"
                if ai["goal_st"] == "below_goal": badge += " ⚠️"
                ac1.markdown(f"**{ai['name']}**{badge}")
                ac2.caption(f"{ai['dept']} · {' · '.join(ai['reasons'])}")
                if ac3.button("✓", key=f"dismiss_{ai['key']}", help="Mark as done"):
                    st.session_state.dismissed_actions.add(ai["key"])
                    st.rerun()

            if st.button("Clear all completed actions", key="clear_dismissed", type="secondary"):
                st.session_state.dismissed_actions.clear()
                st.rerun()
    else:
        if gs:
            show_healthy_state()

    # ── Top bar: dept filter ──────────────────────────────────────────────────
    _render_breadcrumb("employees", dept_sel if dept_sel != "All departments" else None)
    _render_session_context_bar()
    
    dept_sel = st.selectbox("Department", ["All departments"] + all_depts, key="cn_dept",
                             label_visibility="collapsed")
    filtered_emps = (emps if dept_sel == "All departments"
                     else [e for e in emps if e.get("department","") == dept_sel])

    st.divider()

    # ── Main two-column layout ────────────────────────────────────────────────
    col_list, col_detail = st.columns([2, 3], gap="large")

    with col_list:
        st.caption(f"**{dept_sel}** · {len(filtered_emps)} employee(s)")
        roster = []
        for e in filtered_emps:
            indicators = ""
            if e["emp_id"] in flags:           indicators += "🚩 "
            if e["emp_id"] in emp_ids_with_notes:
                _nc = len(_cached_coaching_notes_for(e["emp_id"]))
                indicators += f"📝{_nc}" if _nc else "📝"
            # Add trend indicator from goal_status
            _gs_match = next((r for r in gs if str(r.get("EmployeeID","")) == e["emp_id"]), None)
            if _gs_match:
                _t = normalize_trend_state(_gs_match.get("trend",""))
                if _t == "declining": indicators += " ↓"
                elif _t == "improving": indicators += " ↑"
                elif _t == "inconsistent": indicators += " ~"
            roster.append({
                " ": indicators.strip(),
                "Name": e["name"],
                "Dept": e.get("department",""),
            })
        df_roster = pd.DataFrame(roster)
        sel = st.dataframe(
            df_roster,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )
        sel_rows = sel.selection.rows if sel and sel.selection else []
        if sel_rows:
            selected_emp = filtered_emps[sel_rows[0]]
            st.session_state["cn_selected_emp"] = selected_emp["emp_id"]
        else:
            selected_emp = None

    with col_detail:
        if not selected_emp:
            _render_team_process_view(
                history_rows=history_rows,
                goal_status=gs,
                filtered_emps=filtered_emps,
            )
            st.divider()
            _render_team_activity_comparisons(
                tenant_id=tenant_id,
                history_rows=history_rows,
                goal_status=gs,
            )
            st.divider()
            show_partial_data_state("Select an employee from the roster to open employee detail and record-level drill-down.")
        else:
            emp_id   = selected_emp["emp_id"]
            emp_name = selected_emp["name"]
            emp_dept = selected_emp.get("department","")

            # ── Post-save feedback (persists across rerun once via session_state) ──
            _cn_fb = st.session_state.get("_cn_feedback")
            if _cn_fb and _cn_fb.get("emp_id") == emp_id:
                st.session_state.pop("_cn_feedback", None)  # show once then clear
                _fb_coached   = _cn_fb["coached_today"]
                _fb_remaining = _cn_fb["remaining"]
                _fb_emp_safe  = str(_cn_fb["emp_name"])[:40]
                if _fb_remaining == 0:
                    show_success_state(f"{_fb_emp_safe}: note saved and current follow-up list is clear.")
                    st.markdown(
                        '<div class="dpd-shift-done">'
                        '<div class="dpd-shift-done-icon">🎉</div>'
                        '<div class="dpd-shift-done-title">All caught up!</div>'
                        '<div class="dpd-shift-done-sub">Every below-goal employee has been coached today.</div>'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("↩ Back to Supervisor", key="fb_done_sup", use_container_width=True):
                        st.session_state["goto_page"] = "supervisor"
                        st.rerun()
                else:
                    show_success_state(f"{_fb_emp_safe}: note saved and timeline updated.")
                    _pl = "employee" if _fb_remaining == 1 else "employees"
                    # Find next highest-risk below-goal employee
                    _nxt_gs = sorted(
                        [r for r in st.session_state.get("goal_status", [])
                         if r.get("goal_status") == "below_goal"
                         and str(r.get("EmployeeID", r.get("Employee Name", ""))) != str(emp_id)],
                        key=lambda x: float(x.get("risk_score", 0) or 0),
                        reverse=True,
                    )
                    _nxt_id   = str(_nxt_gs[0].get("EmployeeID", _nxt_gs[0].get("Employee Name", ""))) if _nxt_gs else None
                    _nxt_name = str(_nxt_gs[0].get("Employee", _nxt_gs[0].get("Employee Name", "next")))[:24] if _nxt_gs else "next"
                    st.markdown(
                        f'<div style="background:linear-gradient(90deg,#E8F5E9 0%,#E3F2FD 100%);'
                        f'border-left:4px solid #43A047;border-radius:8px;padding:14px 16px;margin-bottom:10px;">'
                        f'<span style="font-size:14px;font-weight:700;color:#1B5E20;">'
                        f'✔ Coaching saved for {_html_mod.escape(_fb_emp_safe)}</span><br>'
                        f'<span style="font-size:13px;color:#2E7D32;">'
                        f'⚠ {_fb_remaining} {_pl} remaining &nbsp;·&nbsp; {_fb_coached} coached today</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    _fb_c1, _fb_c2 = st.columns(2)
                    if _nxt_id and _fb_c1.button(
                        f"→ {_nxt_name}", key="fb_next_emp", type="primary", use_container_width=True
                    ):
                        st.session_state["cn_selected_emp"] = _nxt_id
                        st.rerun()
                    if _fb_c2.button("↩ Supervisor", key="fb_to_sup", use_container_width=True):
                        st.session_state["goto_page"] = "supervisor"
                        st.rerun()

            # ── Header ────────────────────────────────────────────────────────
            is_flagged = emp_id in flags
            flag_info  = flags.get(emp_id, {}) if is_flagged else {}
            flag_type  = flag_info.get("flag_type", "followup") if flag_info else "followup"
            hc1, hc2 = st.columns([4, 1])
            hc1.markdown(f"### {emp_name}")
            hc1.caption(emp_dept)

            # UPH status + delta since last view
            _emp_gs = next((r for r in gs if str(r.get("EmployeeID","")) == str(emp_id)), None)
            _detail_context = build_employee_detail_context(
                emp_id=emp_id,
                goal_row=_emp_gs or {},
                history_rows=history_rows,
            )
            _timeline = get_employee_action_timeline(emp_id, tenant_id=tenant_id)
            _recent_exception_rows = list_recent_operational_exceptions(tenant_id=tenant_id, employee_id=emp_id, limit=6)
            _follow_through_summary = summarize_follow_through_events(tenant_id=tenant_id, employee_id=emp_id, limit=6)
            if _emp_gs:
                _trend_icon = {"up": "↑", "down": "↓", "flat": "→"}.get(_emp_gs.get("trend",""), "—")
                _chg = _emp_gs.get("change_pct", 0)
                _chg_str = f"+{_chg:.1f}%" if _chg > 0 else f"{_chg:.1f}%"
                _uph = float(_emp_gs.get("Average UPH") or 0)
                _tgt = _emp_gs.get("Target UPH", "—")

                # Delta since last time this employee was selected
                _uph_cache_key = f"_last_uph_{emp_id}"
                _prev_uph = st.session_state.get(_uph_cache_key)
                _delta_str = ""
                if _prev_uph is not None and _uph != _prev_uph:
                    _d = round(_uph - _prev_uph, 2)
                    _delta_icon = "↑" if _d > 0 else "↓"
                    _delta_str  = f" &nbsp;·&nbsp; <span style='color:{'#1B5E20' if _d > 0 else '#B71C1C'};font-size:12px;'>{_delta_icon} {_d:+.2f} UPH since last viewed</span>"
                st.session_state[_uph_cache_key] = _uph

                st.markdown(
                    f"<span style='font-size:13px;'>"
                    f"Avg UPH: <strong>{_uph:.1f}</strong> · "
                    f"Target: <strong>{_tgt}</strong> · "
                    f"Status: <strong>{translate_to_floor_language(_emp_gs.get('goal_status', ''))}</strong> · "
                    f"Direction: {_trend_icon} {_chg_str}"
                    f"{_delta_str}</span>",
                    unsafe_allow_html=True)

                # ── Coaching impact (big visual card) ─────────────────────────
                _recent_notes = _cached_coaching_notes_for(emp_id)
                _impact = find_coaching_impact(emp_id, _recent_notes, history_rows)
                if _impact:
                    show_coaching_impact(emp_name, _impact)
                elif _recent_notes:
                    _last_date = str(_recent_notes[0].get("created_at", ""))[:10]
                    st.caption(f"Last coaching: {_last_date} · Not enough post-coaching data yet.")
                else:
                    st.caption("No coaching on record yet.")

            _render_employee_signal_summary(_detail_context)
            if (
                not bool(_detail_context.get("has_notable_signal"))
                and not _timeline
                and not _recent_exception_rows
                and not (_follow_through_summary.get("rows") or [])
            ):
                if bool(_detail_context.get("has_minimum_context")):
                    show_healthy_state()
                else:
                    show_partial_data_state("This employee card is waiting for enough recent comparable records to classify trend and before/after impact.")
                if str(_detail_context.get("healthy_state_message") or "").strip():
                    st.caption(str(_detail_context.get("healthy_state_message") or ""))
            _render_employee_signal_explainer(_detail_context)

            st.divider()

            _render_related_action_events(timeline=_timeline)

            st.divider()

            _render_employee_activity_comparisons(
                tenant_id=tenant_id,
                emp_id=emp_id,
                expected_uph=float((_emp_gs or {}).get("Target UPH") or 0),
                history_rows=history_rows,
            )

            st.divider()

            # ── Flag status ───────────────────────────────────────────────────
            if is_flagged:
                _flag_emoji = {"followup": "🚩", "performance": "⚠️"}.get(flag_type, "🚩")
                _flag_label = {"followup": "Follow-up", "performance": "Performance Issue"}.get(flag_type, "Follow-up")
                fc1, fc2 = st.columns([3, 1])
                fc1.warning(f"{_flag_emoji} **{_flag_label}** · Flagged since {flag_info.get('flagged_on','')}")
                if fc2.button("Remove", key="cn_unflag", type="secondary", use_container_width=True):
                    from goals import unflag_employee
                    unflag_employee(emp_id, tenant_id=tenant_id)
                    _raw_cached_active_flags.clear()
                    for r in st.session_state.get("goal_status", []):
                        if str(r.get("EmployeeID","")) == str(emp_id):
                            r["flagged"] = False
                    st.rerun()
            
            st.divider()

            _render_employee_follow_through_panel(
                tenant_id=tenant_id,
                emp_id=emp_id,
                emp_name=emp_name,
            )

            st.divider()

            _render_employee_exception_panel(
                tenant_id=tenant_id,
                emp_id=emp_id,
                emp_name=emp_name,
                emp_dept=emp_dept,
            )

            st.divider()

            # ── Action decision history (new primary profile context) ─────────
            st.subheader("🧭 Action Decision History")
            _emp_actions = get_employee_actions(emp_id, tenant_id=tenant_id)
            _open_emp_actions = [a for a in _emp_actions if str(a.get("status") or "") in {"new", "in_progress", "follow_up_due", "overdue", "escalated"}]
            _closed_emp_actions = [a for a in _emp_actions if str(a.get("status") or "") in {"resolved", "deprioritized", "transferred"}]

            _improved_actions = sum(1 for a in _emp_actions if str(a.get("resolution_type") or "").startswith("improved"))
            _recognition_actions = [
                a for a in _emp_actions
                if str(a.get("issue_type") or "") == "high_performer_ignored"
                or str(a.get("action_type") or "") in {"development_touchpoint", "recognition"}
            ]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Open Actions", len(_open_emp_actions))
            m2.metric("Total Action History", len(_emp_actions))
            m3.metric("Improved Outcomes", _improved_actions)
            m4.metric("Recognition/Development", len(_recognition_actions))

            if _open_emp_actions:
                with st.expander(f"Open actions ({len(_open_emp_actions)})", expanded=True):
                    for _a in _open_emp_actions:
                        _rid = str(_a.get("id") or "")
                        _due = str(_a.get("follow_up_due_at") or "")[:10]
                        _status = str(_a.get("_runtime_status") or _a.get("status") or "new").replace("_", " ").title()
                        _next_step = str(_a.get("action_type") or "").replace("_", " ").title() or "Follow up"
                        st.markdown(f"**#{_rid}** · {_status}")
                        st.caption(
                            f"Issue: {str(_a.get('issue_type') or '').replace('_', ' ')} | "
                            f"Trigger: {str(_a.get('trigger_summary') or '')[:120]}"
                        )
                        st.caption(
                            f"Due: {_due or '—'} | Logged intervention type: {_next_step}"
                        )
                        st.divider()
            else:
                st.caption("No open actions for this employee.")

            # What has been tried (interventions + events)
            _tried_interventions = sorted({
                str(a.get("action_type") or "").replace("_", " ").title()
                for a in _emp_actions if str(a.get("action_type") or "").strip()
            })
            _tried_events = sorted({
                str(ev.get("event_type") or "").replace("_", " ").title()
                for ev in _timeline if str(ev.get("event_type") or "").strip()
            })

            with st.expander("What has been tried", expanded=False):
                if not _tried_interventions and not _tried_events:
                    st.caption("No prior interventions recorded yet.")
                else:
                    if _tried_interventions:
                        st.markdown("**Interventions used**")
                        st.caption(" · ".join(_tried_interventions))
                    if _tried_events:
                        st.markdown("**Actions/events logged**")
                        st.caption(" · ".join(_tried_events))

            # Outcomes over time
            with st.expander("Outcomes over time", expanded=False):
                _outcome_rows = []
                for _a in _closed_emp_actions:
                    _resolved_at = str(_a.get("resolved_at") or _a.get("last_event_at") or "")[:10]
                    _outcome_rows.append(
                        {
                            "Date": _resolved_at,
                            "Outcome": str(_a.get("resolution_type") or "").replace("_", " ").title() or "Unknown",
                            "Delta UPH": float(_a.get("improvement_delta") or 0.0),
                            "Status": str(_a.get("status") or "").replace("_", " ").title(),
                        }
                    )
                if _outcome_rows:
                    _outcome_df = pd.DataFrame(_outcome_rows)
                    st.dataframe(_outcome_df, use_container_width=True, hide_index=True)
                else:
                    st.caption("No completed outcomes yet.")

            # Recognition/development history
            with st.expander("Recognition / development history", expanded=False):
                if not _recognition_actions:
                    st.caption("No recognition/development actions recorded yet.")
                else:
                    for _a in _recognition_actions:
                        st.markdown(
                            f"**{str(_a.get('action_type') or '').replace('_', ' ').title()}** · "
                            f"{str(_a.get('status') or '').replace('_', ' ').title()}"
                        )
                        st.caption(str(_a.get("trigger_summary") or ""))

            # Full follow-through timeline
            with st.expander(f"Follow-through timeline ({len(_timeline)})", expanded=False):
                if not _timeline:
                    st.caption("No timeline events yet.")
                else:
                    for _ev in _timeline[:40]:
                        _ev_label = str(_ev.get("event_type") or "event").replace("_", " ").title()
                        _ev_ts = str(_ev.get("event_at") or "")[:16].replace("T", " ")
                        _ev_outcome = str(_ev.get("outcome") or "")
                        _ev_note = str(_ev.get("notes") or "")
                        _ev_trigger = str(_ev.get("trigger_summary") or "")
                        st.markdown(f"**{_ev_label}** · {_ev_ts}")
                        _context_bits = []
                        if str(_ev.get("action_id") or "").strip():
                            _context_bits.append(f"Action #{_ev.get('action_id')}")
                        else:
                            _context_bits.append("Standalone log")
                        if str(_ev.get("linked_exception_id") or "").strip():
                            _context_bits.append(f"Exception #{_ev.get('linked_exception_id')}")
                        if str(_ev.get("action_type") or "").strip():
                            _context_bits.append(str(_ev.get("action_type") or "").replace("_", " "))
                        if _ev_trigger:
                            _context_bits.append(_ev_trigger[:100])
                        st.caption(" | ".join(_context_bits))
                        if _ev_outcome:
                            st.caption(f"Outcome: {_ev_outcome}")
                        if _ev_note:
                            st.caption(_ev_note[:240])
                        st.divider()

            st.divider()

            # ── Show follow-up scheduler if just saved ────────────────────────
            _fu_key = f"_cn_show_followup_{emp_id}"
            if st.session_state.get(_fu_key):
                _note_prev = st.session_state.get(f"_cn_last_note_{emp_id}", "")
                st.markdown("**📅 Schedule a follow-up?**")
                _today   = date.today()
                _fu_c1, _fu_c2, _fu_c3, _fu_c4 = st.columns(4)
                _fu_date = None
                if _fu_c1.button("In 3 days", key="fu_3d", use_container_width=True):
                    _fu_date = (_today + __import__("datetime").timedelta(days=3)).isoformat()
                if _fu_c2.button("In 7 days", key="fu_7d", use_container_width=True):
                    _fu_date = (_today + __import__("datetime").timedelta(days=7)).isoformat()
                _fu_custom = _fu_c3.text_input("Custom (MM/DD)", key="fu_custom", placeholder="e.g. 04/15",
                                                label_visibility="collapsed")
                if _fu_c4.button("Set date", key="fu_set", use_container_width=True) and _fu_custom.strip():
                    try:
                        _fu_date = datetime.strptime(_fu_custom.strip(), "%m/%d").replace(year=date.today().year).strftime("%Y-%m-%d")
                        if _fu_date < date.today().isoformat():
                            _fu_date = datetime.strptime(_fu_custom.strip(), "%m/%d").replace(year=date.today().year + 1).strftime("%Y-%m-%d")
                    except Exception:
                        st.error("Invalid date format.")
                if _fu_date:
                    try:
                        from followup_manager import add_followup
                        add_followup(emp_id, emp_name, emp_dept, _fu_date, _note_prev)
                        st.success(f"✓ Follow-up scheduled for {_fu_date}")
                    except Exception as _fue:
                        st.error(f"Could not save follow-up: {_fue}")
                    del st.session_state[_fu_key]
                    st.rerun()
                if st.button("Skip — no follow-up needed", key="fu_skip", type="secondary"):
                    del st.session_state[_fu_key]
                    st.rerun()
                st.divider()

            # ── Add entry ────────────────────────────────────────────────────
            # Defer widget clears to the start of a rerun so Streamlit allows state mutation.
            if st.session_state.pop("_cn_clear_inputs", False):
                st.session_state["cn_note"] = ""
                st.session_state["cn_common_issues"] = []
                st.session_state["cn_coaching_reason"] = "Below goal"
                st.session_state["cn_later_outcome"] = "pending"

            _target_action_options = {"Auto (use latest open action or create new)": ""}
            for _oa in _open_emp_actions:
                _oa_id = str(_oa.get("id") or "")
                _oa_label = (
                    f"#{_oa_id} · {str(_oa.get('issue_type') or '').replace('_', ' ')} · "
                    f"{str(_oa.get('_runtime_status') or _oa.get('status') or '').replace('_', ' ')}"
                )
                _target_action_options[_oa_label] = _oa_id

            _target_choice = st.selectbox(
                "Action target",
                list(_target_action_options.keys()),
                key="cn_action_target",
                help="Attach coaching to an open action, or auto-create a new action cycle.",
            )

            coaching_reason = st.selectbox(
                "Reason",
                [
                    "Below goal",
                    "Trend down",
                    "Training gap",
                    "Process blocker",
                    "Quality issue",
                    "Attendance issue",
                    "Recognition/development",
                    "Other",
                ],
                key="cn_coaching_reason",
            )

            note_text = st.text_area(
                "Action taken",
                height=120,
                key="cn_note",
                placeholder="What did you do in coaching and what changed today?",
            )
            _cf1, _cf2 = st.columns(2)
            expected_followup_date = _cf1.date_input(
                "Expected follow-up date",
                value=date.today() + __import__("datetime").timedelta(days=7),
                key="cn_expected_followup",
            )
            later_outcome = _cf2.selectbox(
                "Later outcome",
                ["pending", "improved", "no_change", "worse"],
                key="cn_later_outcome",
                help="Usually pending when logging the initial coaching.",
            )

            _issue_options = [
                "Equipment issue",
                "Staffing",
                "Individual performance",
                "Training gap",
                "Process issue",
                "Quality issue",
                "Attendance",
            ]
            selected_issues = st.multiselect(
                "Common issues observed",
                _issue_options,
                default=[],
                key="cn_common_issues",
                help="Tag the likely cause so we can track patterns over time.",
            )
            current_user_name = (
                st.session_state.get("user_name", "").strip()
                or st.session_state.get("user_email", "").strip()
            )
            st.caption(f"Note will be saved as: {current_user_name or 'Current user'}")

            _sv1, _sv2 = st.columns(2)
            if _sv1.button("💾 Save note", type="primary", use_container_width=True):
                if note_text.strip():
                    _issue_prefix = ""
                    if selected_issues:
                        _issue_prefix = "[Issues: " + ", ".join(selected_issues) + "]\n"
                    _final_note = (
                        f"reason={coaching_reason}\n"
                        f"expected_follow_up_date={expected_followup_date.isoformat()}\n"
                        f"later_outcome={later_outcome}\n"
                        f"{_issue_prefix}{note_text.strip()}"
                    )

                    _cycle_result = log_coaching_lifecycle_entry(
                        employee_id=emp_id,
                        employee_name=emp_name,
                        department=emp_dept,
                        reason=coaching_reason,
                        action_taken=f"{_issue_prefix}{note_text.strip()}",
                        expected_follow_up_date=expected_followup_date.isoformat(),
                        performed_by=current_user_name,
                        later_outcome=later_outcome,
                        existing_action_id=_target_action_options.get(_target_choice, ""),
                        tenant_id=tenant_id,
                        user_role=str(st.session_state.get("user_role", "") or ""),
                    )
                    if not _cycle_result:
                        st.error("Could not save coaching cycle as an action event.")
                        st.stop()

                    # Keep legacy coaching journal populated during transition.
                    add_coaching_note(emp_id, _final_note, current_user_name)
                    _raw_cached_coaching_notes_for.clear()
                    _raw_cached_all_coaching_notes.clear()
                    _preview = note_text.strip()[:80]
                    st.session_state[f"_cn_last_note_{emp_id}"] = _preview
                    st.session_state[_fu_key] = True   # prompt follow-up scheduler
                    st.session_state["_cn_clear_inputs"] = True
                    st.session_state["_employees_set_view"] = "Performance Journal"
                    # Track coaching session progress
                    st.session_state["_coached_today"] = int(st.session_state.get("_coached_today", 0)) + 1
                    st.session_state["_last_coached_emp_id"] = emp_id
                    _remaining_risk = [
                        r for r in st.session_state.get("goal_status", [])
                        if r.get("goal_status") == "below_goal"
                        and str(r.get("EmployeeID", r.get("Employee Name", ""))) != str(emp_id)
                    ]
                    st.session_state["_cn_feedback"] = {
                        "emp_name": emp_name,
                        "emp_id": emp_id,
                        "remaining": len(_remaining_risk),
                        "coached_today": int(st.session_state.get("_coached_today", 0)),
                    }
                    st.rerun()
                else:
                    st.warning("Write something before saving the note.")

            if _sv2.button("Skip for now →", key="cn_skip", use_container_width=True):
                # Advance to next below-goal or trending-down employee
                _skip_candidates = sorted(
                    [r for r in st.session_state.get("goal_status", [])
                     if (
                         r.get("goal_status") == "below_goal"
                         or normalize_trend_state(r.get("trend") or "") in {"declining", "below_expected", "inconsistent"}
                     )
                     and str(r.get("EmployeeID", r.get("Employee Name", ""))) != str(emp_id)],
                    key=lambda x: float(x.get("risk_score", 0) or 0), reverse=True
                )
                if _skip_candidates:
                    _next_id = str(_skip_candidates[0].get("EmployeeID", _skip_candidates[0].get("Employee Name", "")))
                    st.session_state["cn_selected_emp"] = _next_id
                    st.rerun()

            st.divider()

            # ── Flag / unflag actions (below note box) ────────────────────────
            if not is_flagged:
                with st.expander("🚩 Flag this employee", expanded=False):
                    _ft_col1, _ft_col2 = st.columns(2)
                    _new_flag_type = _ft_col1.radio(
                        "Flag type",
                        ["🚩 Follow-up", "⚠️ Performance Issue"],
                        key="cn_flag_type",
                        horizontal=True,
                    )
                    _ft_reason = _ft_col2.text_input("Reason (optional)", key="cn_flag_reason")
                    if st.button("Apply flag", key="cn_flag_btn", type="secondary"):
                        from goals import flag_employee
                        _ft_mapped = "followup" if "Follow-up" in _new_flag_type else "performance"
                        flag_employee(emp_id, emp_name, emp_dept, _ft_reason, flag_type=_ft_mapped, tenant_id=tenant_id)
                        _raw_cached_active_flags.clear()
                        for r in st.session_state.get("goal_status", []):
                            if str(r.get("EmployeeID","")) == str(emp_id):
                                r["flagged"] = True
                        st.rerun()

            # ── Legacy coaching timeline ──────────────────────────────────────
            notes = _cached_coaching_notes_for(emp_id)
            _n_count = len(notes)
            _tl_lbl = f"📋 Legacy coaching history ({_n_count} entries)" if _n_count else "📋 No legacy coaching history yet"
            with st.expander(_tl_lbl, expanded=(_n_count > 0 and _n_count <= 3)):
                st.caption("Older coaching journal entries are preserved here for reference. New quick follow-through entries save above.")
                if notes:
                    # Build per-note UPH impact
                    _all_h = st.session_state.get("history", [])
                    for _ni, n in enumerate(notes):
                        _note_date_str = str(n.get("created_at",""))[:10]
                        _note_text_raw = n.get("note","")
                        _note_by       = n.get("created_by","")
                        _note_id       = n.get("id")

                        # Compute UPH change following this note
                        _uph_change_str = ""
                        try:
                            from datetime import datetime as _dtcls, timedelta as _tdcls
                            _nc_date = _dtcls.fromisoformat(_note_date_str).date()
                            _nc_before = [float(h.get("uph") or 0) for h in _all_h
                                          if str(h.get("emp_id")) == str(emp_id)
                                          and (_nc_date - _tdcls(days=7)) <= _dtcls.fromisoformat(h.get("work_date","")).date() < _nc_date
                                          and float(h.get("uph") or 0) > 0]
                            _nc_after  = [float(h.get("uph") or 0) for h in _all_h
                                          if str(h.get("emp_id")) == str(emp_id)
                                          and _nc_date < _dtcls.fromisoformat(h.get("work_date","")).date() <= (_nc_date + _tdcls(days=7))
                                          and float(h.get("uph") or 0) > 0]
                            if _nc_before and _nc_after:
                                _b_avg = sum(_nc_before) / len(_nc_before)
                                _a_avg = sum(_nc_after)  / len(_nc_after)
                                _delta = round(_a_avg - _b_avg, 1)
                                if _delta > 0.2:
                                    _uph_change_str = f" · <span style='color:#1B5E20;font-size:11px;'>↑ +{_delta} UPH</span>"
                                elif _delta < -0.2:
                                    _uph_change_str = f" · <span style='color:#B71C1C;font-size:11px;'>↓ {_delta} UPH</span>"
                                else:
                                    _uph_change_str = f" · <span style='color:#5A7A9C;font-size:11px;'>→ stable</span>"
                        except Exception:
                            pass

                        # Timeline entry card
                        _nby_safe   = _html_mod.escape(_note_by) if _note_by else ""
                        _ntxt_safe  = _html_mod.escape(_note_text_raw[:160] + ("…" if len(_note_text_raw) > 160 else ""))
                        _ndate_safe = _html_mod.escape(_note_date_str)
                        tl1, tl2 = st.columns([11, 1])
                        tl1.markdown(
                            f"<div style='border-left:3px solid #0F2D52;padding:8px 12px;margin-bottom:6px;'>"
                            f"<span style='color:#5A7A9C;font-size:11px;'>{_ndate_safe}"
                            f"{'  ·  ' + _nby_safe if _nby_safe else ''}{_uph_change_str}</span>"
                            f"<br><span style='color:#1A2D42;font-size:13px;'>{_ntxt_safe}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                        if _note_id and tl2.button("🗑", key=f"del_{_note_id}", help="Delete"):
                            delete_coaching_note(str(_note_id))
                            _raw_cached_coaching_notes_for.clear()
                            _raw_cached_all_coaching_notes.clear()
                            st.rerun()

                    st.divider()
                    ac1, ac2 = st.columns(2)
                    if ac1.button("⬇️ Export journal", key="cn_export", use_container_width=True):
                        buf = io.BytesIO()
                        pd.DataFrame([{
                            "Date": str(n.get("created_at",""))[:10],
                            "Note": n.get("note",""),
                            "By":   n.get("created_by",""),
                        } for n in notes]).to_excel(buf, index=False, sheet_name="Journal")
                        buf.seek(0)
                        ac1.download_button("⬇️ Download", buf.read(),
                                            f"{emp_id}_journal_{date.today()}.xlsx",
                                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                            key="cn_dl", use_container_width=True)
                    if ac2.button("📦 Archive all entries", key="cn_archive",
                                   use_container_width=True, type="secondary"):
                        archive_coaching_notes(emp_id)
                        _raw_cached_coaching_notes_for.clear()
                        _raw_cached_all_coaching_notes.clear()
                        st.session_state.pop("cn_selected_emp", None)
                        st.rerun()
                else:
                    st.caption("No legacy coaching history yet.")




# ──  _build_archived_productivity lives in services/employees_service.py  ──
# Imported at the top of this file.
