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

init_runtime()
from services.coaching_service import find_coaching_impact
from services.employee_service import (
    build_employee_history_frames,
    filter_employees_by_department,
    load_employee_history_workflow,
    parse_history_range,
)
from services.action_service import (
    get_employee_actions,
    get_employee_action_timeline,
    log_coaching_lifecycle_entry,
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

def page_employees():
    st.title("👥 Employees")
    if not require_db(): return
    tenant_id = str(st.session_state.get("tenant_id", "") or "")

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
        st.error(f"Error: {e}")
        _log_app_error("employees", f"Employee page error: {e}", detail=traceback.format_exc())



@st.fragment
def _emp_history():
    st.subheader("Employee UPH history")
    emps = _cached_employees()
    if not emps:
        st.info("No employees yet. Go to **Import Data** to upload a CSV — employees are created automatically from your data.")
        return

    # ── Department filter → populates employee dropdown ───────────────────────
    depts    = sorted({e.get("department","") for e in emps if e.get("department")})
    dept_sel = st.selectbox("Filter by department", ["All departments"] + depts, key="eh_dept")

    filtered_emps = filter_employees_by_department(emps, dept_sel)

    if not filtered_emps:
        st.info("No employees in that department.")
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
        st.info("No history yet for this employee.")
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
        st.info("No valid UPH data to chart for this date range.")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("⬇️ Export employee history"):
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
        st.info("No coaching data available. Import productivity data and set department goals first.")
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
    _filter = st.radio("Show", ["All", "🔴 Urgent only", "🟡 Needs attention", "⭐ Top performers"],
                        horizontal=True, key="coaching_filter")

    for rec in recs:
        if _filter == "🔴 Urgent only" and rec["priority"] != "high":
            continue
        if _filter == "🟡 Needs attention" and rec["priority"] not in ("high", "medium"):
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
    emps  = _cached_employees()
    flags = _cached_active_flags()
    history_rows = st.session_state.get("history", [])
    if not emps:
        st.info("No employees yet. Go to **Import Data** to upload a CSV — employees are created automatically from your data.")
        return

    # ── Build employee list — all employees, annotate who has notes / is flagged
    emp_ids_with_notes = _cached_all_coaching_notes()
    all_depts = sorted({e.get("department","") for e in emps if e.get("department")})
    dept_sel = st.session_state.get("cn_dept", "All departments")
    if dept_sel not in ["All departments", *all_depts]:
        dept_sel = "All departments"
        st.session_state["cn_dept"] = dept_sel

    # ── Manager Action List ──────────────────────────────────────────────────
    # Auto-generates follow-up actions for trending-down or below-goal employees
    gs = st.session_state.get("goal_status", [])
    if "dismissed_actions" not in st.session_state:
        st.session_state.dismissed_actions = set()

    action_items = []
    for r in gs:
        eid  = str(r.get("EmployeeID", r.get("Employee Name", "")))
        name = r.get("Employee Name", "")
        dept = r.get("Department", "")
        trend      = r.get("trend", "")
        goal_st    = r.get("goal_status", "")
        change_pct = r.get("change_pct", 0)
        avg_uph    = r.get("Average UPH", 0)
        target     = r.get("Target UPH", "—")

        reasons = []
        if trend == "down":
            reasons.append(f"Performance dropping ({change_pct:+.1f}%)")
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
        with st.expander(f"📋 **Manager Action List** — {len(action_items)} follow-up(s) needed", expanded=True):
            st.caption("Employees trending down or below goal. Complete the follow-up, then dismiss the action.")
            for ai in action_items:
                ac1, ac2, ac3 = st.columns([3, 5, 1])
                badge = ""
                if ai["trend"] == "down": badge += " ↓"
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
            st.success("✓ No follow-ups needed — all employees are on track.")

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
                _t = _gs_match.get("trend","")
                if _t == "down": indicators += " ↓"
                elif _t == "up": indicators += " ↑"
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
            st.info("← Select an employee from the list")
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

                # ── Next step suggestion ──────────────────────────────────────
                if _emp_gs.get("trend") == "down" and _emp_gs.get("goal_status") == "below_goal":
                    st.warning("⚠ Performance is dropping while already below target. Reset the standard and remove blockers today.")
                elif _emp_gs.get("trend") == "down":
                    st.info("Performance is slipping. Suggested: quick check-in and reset one daily focus target.")
                elif not _impact:
                    st.info("Suggested: confirm what is working and set one measurable next-step target.")

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
                            f"Due: {_due or '—'} | Recommended next step: {_next_step}"
                        )
                        st.divider()
            else:
                st.caption("No open actions for this employee.")

            # What has been tried (interventions + events)
            _timeline = get_employee_action_timeline(emp_id, tenant_id=tenant_id)
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

            # Full action timeline
            with st.expander(f"Action timeline ({len(_timeline)})", expanded=False):
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
                        st.caption(
                            f"Action #{_ev.get('action_id')} | "
                            f"{str(_ev.get('action_type') or '').replace('_', ' ')} | "
                            f"{_ev_trigger[:100]}"
                        )
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
                     if (r.get("goal_status") == "below_goal" or r.get("trend") == "down")
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

            # ── Coaching timeline ─────────────────────────────────────────────
            notes = _cached_coaching_notes_for(emp_id)
            _n_count = len(notes)
            _tl_lbl = f"📋 Coaching Timeline ({_n_count} entries)" if _n_count else "📋 No coaching history yet"
            with st.expander(_tl_lbl, expanded=(_n_count > 0 and _n_count <= 3)):
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
                    st.caption("No coaching history yet — add a note above.")




# ──  _build_archived_productivity lives in services/employees_service.py  ──
# Imported at the top of this file.
