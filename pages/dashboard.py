from core.runtime import date, pd, st
from domain.risk import _get_all_risk_levels
from pages.common import load_goal_status_history
from ui_improvements import (
    _render_breadcrumb,
    _render_confidence_ux,
    _render_priority_strip,
    _render_session_context_bar,
    _render_session_progress,
)

def page_dashboard():
    """Dashboard: At-a-glance risk view of all employees."""
    st.title("📊 Dashboard")
    st.caption("See who needs attention first. Filter by urgency or department.")

    gs, history = load_goal_status_history("Loading dashboard data…")
    if gs is None:
        return
    
    if not gs:
        st.info("No productivity data. Run Import Data to get started.")
        return

    # Session context and breadcrumbs
    _render_breadcrumb("dashboard", "High Risk View")
    _render_session_context_bar()

    _render_session_progress(gs)
    _render_priority_strip(gs, history)

    # Read active filter state for confidence cue (uses previous rerun values)
    _active_risk = st.session_state.get("dash_risk_filter", ["🔴 High"])
    _active_dept_raw = st.session_state.get("dash_dept_filter", ["All departments"])
    _active_dept = [d for d in _active_dept_raw if d != "All departments"]
    _conf_filters: dict = {}
    if _active_risk and set(_active_risk) != {"🔴 High", "🟡 Medium", "🟢 Low"}:
        _conf_filters["Risk"] = ", ".join(_active_risk)
    if _active_dept:
        _conf_filters["Dept"] = ", ".join(_active_dept)
    _render_confidence_ux(history, active_filters=_conf_filters if _conf_filters else None)
    st.divider()

    # Filter for below_goal employees
    below_goal = [r for r in gs if r.get("goal_status") == "below_goal"]
    
    if not below_goal:
        st.success("✅ All employees are meeting their goals!")
        st.divider()
        # Show summary of on-goal employees
        on_goal = [r for r in gs if r.get("goal_status") != "below_goal"]
        if on_goal:
            st.subheader("On Target")
            st.metric("Employees meeting goals", len(on_goal))
        return

    # Score all below-goal employees using shared risk calculator
    _risk_cache_all = _get_all_risk_levels(gs, history)
    risk_list = []
    for emp in below_goal:
        emp_id = str(emp.get("EmployeeID", emp.get("Employee Name", "")))
        risk_level, risk_score, risk_details = _risk_cache_all.get(emp_id, ("🟢 Low", 0, {}))
        risk_list.append({
            "name": emp.get("Employee", emp.get("Employee Name", "Unknown")),
            "department": emp.get("Department", ""),
            "emp_id": emp_id,
            "avg_uph": round(float(emp.get("Average UPH", 0) or 0), 2),
            "target_uph": emp.get("Target UPH", "—"),
            "trend": emp.get("trend", "—"),
            "change_pct": emp.get("change_pct", 0.0),
            "risk_level": risk_level,
            "risk_score": risk_score,
            "risk_details": risk_details,
        })

    # Filter controls
    with st.expander("⚙️ Filters", expanded=False):
        col1, col2, col3 = st.columns([2, 2, 1])
        risk_filter = col1.multiselect(
            "Filter by risk level",
            ["🔴 High", "🟡 Medium", "🟢 Low"],
            default=["🔴 High"],
            key="dash_risk_filter"
        )

        dept_options = sorted(set(r["department"] for r in risk_list if r["department"]))
        dept_filter = col2.multiselect(
            "Filter by department",
            ["All departments"] + dept_options,
            default=["All departments"],
            key="dash_dept_filter"
        )

        sort_by = col3.selectbox(
            "Sort by",
            ["Risk (High → Low)", "UPH (Low → High)", "Streak (Longest)"],
            key="dash_sort"
        )

    # Apply filters
    filtered = [r for r in risk_list if r["risk_level"] in risk_filter]
    if "All departments" not in dept_filter:
        filtered = [r for r in filtered if r["department"] in dept_filter]

    # Active filter chips (persistent visible state: show what's active, allow quick clear)
    _chip_parts = []
    for chip in risk_filter:
        _chip_parts.append(f'<span class="dpd-chip-label">{chip}</span>')
    for dep in dept_filter:
        if dep != "All departments":
            _chip_parts.append(f'<span class="dpd-chip-label">{dep}</span>')
    if _chip_parts:
        st.markdown(
            '<div class="dpd-chip-row">Active filters:&nbsp;' + "".join(_chip_parts) + "</div>",
            unsafe_allow_html=True,
        )

    # Sort
    if sort_by == "Risk (High → Low)":
        filtered.sort(key=lambda x: x["risk_score"], reverse=True)
    elif sort_by == "UPH (Low → High)":
        filtered.sort(key=lambda x: x["avg_uph"])
    elif sort_by == "Streak (Longest)":
        filtered.sort(key=lambda x: x["risk_details"]["under_goal_streak"], reverse=True)

    # Summary metrics
    st.divider()
    high_risk = len([r for r in filtered if r["risk_level"] == "🔴 High"])
    med_risk = len([r for r in filtered if r["risk_level"] == "🟡 Medium"])
    low_risk = len([r for r in filtered if r["risk_level"] == "🟢 Low"])
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Need attention", len(filtered))
    m2.metric("🔴 Coach now", high_risk)
    m3.metric("🟡 Check in soon", med_risk)
    m4.metric("🟢 Lower urgency", low_risk)

    st.divider()

    # Display as scrollable table
    st.subheader("Performance Priority List")
    
    if not filtered:
        st.info("No employees match the selected filters.")
        return

    # Create table data
    table_data = []
    for r in filtered:
        table_data.append({
            "Risk": r["risk_level"],
            "Name": r["name"],
            "Dept": r["department"],
            "Current UPH": r["avg_uph"],
            "Target": r["target_uph"],
            "Trend": r["trend"],
            "Streak": f"{r['risk_details']['under_goal_streak']} days",
            "Score": r["risk_score"],
        })

    df = pd.DataFrame(table_data)
    
    # Color code by risk
    def _color_risk(val):
        if "🔴" in str(val):
            return "background-color: #ffcccc; color: #8b0000"
        elif "🟡" in str(val):
            return "background-color: #fff9e6; color: #ff6600"
        elif "🟢" in str(val):
            return "background-color: #e6ffe6; color: #008000"
        return ""

    styled = df.style.map(_color_risk, subset=["Risk"])
    # Row selection — drives the sticky action bar below
    _sel_result = st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        key="dash_row_sel",
    )
    _sel_rows   = _sel_result.selection.rows if _sel_result and _sel_result.selection else []
    _sel_items  = [filtered[i] for i in _sel_rows if i < len(filtered)]
    _sel_names  = [r["name"] for r in _sel_items]

    # Sticky bottom action bar — appears when rows are selected
    if _sel_items:
        _ns = len(_sel_items)
        _nh = sum(1 for r in _sel_items if r["risk_level"].startswith("🔴"))
        st.markdown(
            f'<div class="dpd-sticky-wrap">'
            f'<span class="dpd-sticky-label">⚡ {_ns} selected'
            f'{" · " + str(_nh) + " high-risk" if _nh else ""}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        _sb1, _sb2, _sb3 = st.columns(3)
        if _sb1.button("▶ Coach first selected", key="dash_sel_coach", type="primary", use_container_width=True):
            st.session_state["goto_page"] = "employees"
            st.session_state["emp_view"] = "Performance Journal"
            st.session_state["cn_selected_emp"] = _sel_items[0]["emp_id"]
            st.rerun()
        if _sb2.button("📝 Add note to first", key="dash_sel_note", use_container_width=True):
            st.session_state["goto_page"] = "employees"
            st.session_state["emp_view"] = "Performance Journal"
            st.session_state["cn_selected_emp"] = _sel_items[0]["emp_id"]
            st.rerun()
        # Export selected
        _sel_df = df[df["Name"].isin(_sel_names)]
        _sb3.download_button(
            f"⬇️ Export {_ns}",
            _sel_df.to_csv(index=False),
            f"selected_{date.today()}.csv",
            "text/csv",
            key="dash_sel_export",
            use_container_width=True,
        )
        st.markdown('<div class="dpd-sticky-spacer"></div>', unsafe_allow_html=True)
    else:
        # Export full list when nothing selected
        with st.expander("⬇️ Export / bulk actions", expanded=False):
            st.download_button(
                "Download full priority list",
                df.to_csv(index=False),
                f"priority_list_{date.today()}.csv",
                "text/csv",
                key="dash_export_all",
                use_container_width=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: IMPORT DATA
# ══════════════════════════════════════════════════════════════════════════════

