from app import (
    _cached_active_flags,
    _cached_all_coaching_notes,
    _cached_coaching_notes_for,
    _cached_employees,
    _cached_targets,
    _get_current_plan,
    _html_mod,
    _log_app_error,
    _render_breadcrumb,
    _render_session_context_bar,
    date,
    datetime,
    find_coaching_impact,
    io,
    pd,
    require_db,
    show_coaching_impact,
    st,
    time,
    traceback,
    translate_to_floor_language,
)
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

    _plan = _get_current_plan()
    try:
        if _plan in ("pro", "business", "admin"):
            t1, t2, t3 = st.tabs(["Employee History", "Performance Journal", "Coaching Insights"])
            with t1:
                _emp_history()
            with t2:
                _emp_coaching()
            with t3:
                _emp_ai_coaching()
        else:
            t1, t2 = st.tabs(["Employee History", "Performance Journal"])
            with t1:
                _emp_history()
            with t2:
                _emp_coaching()
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

    if dept_sel == "All departments":
        filtered_emps = emps
    else:
        filtered_emps = [e for e in emps if e.get("department","") == dept_sel]

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
    try:
        from_date_h = datetime.strptime(from_str.strip(), "%m/%d/%Y").date()
    except Exception:
        from_date_h = date.today() - _tdelta(days=90)
    try:
        to_date_h = datetime.strptime(to_str.strip(), "%m/%d/%Y").date()
    except Exception:
        to_date_h = date.today()
    st.session_state["eh_from"] = from_str
    st.session_state["eh_to"]   = to_str
    days = max(1, (to_date_h - from_date_h).days)
    from_iso = from_date_h.isoformat()
    to_iso   = to_date_h.isoformat()

    # uph_history stores the numeric employees.id (bigint FK) in emp_id, not the text code.
    # Resolve the text emp_id to the numeric id before querying.
    _this_emp_rec = next((e for e in filtered_emps if e["emp_id"] == emp_id), None)
    _uph_emp_id = int(_this_emp_rec["id"]) if (_this_emp_rec and _this_emp_rec.get("id") is not None) else emp_id

    # Query uph_history within date range
    try:
        _sb_h = _get_db_client()
        _r_h  = _sb_h.table("uph_history").select("*") \
                      .eq("emp_id", _uph_emp_id) \
                      .gte("work_date", from_iso) \
                      .lte("work_date", to_iso) \
                      .order("work_date").execute()
        history = _r_h.data or []
    except Exception:
        history = []

    # Fallback: derive from unit_submissions if uph_history empty
    if not history:
        try:
            from collections import defaultdict as _dh
            _sb3 = _get_db_client()
            _r3  = _sb3.table("unit_submissions").select("*") \
                        .eq("emp_id", emp_id) \
                        .gte("work_date", from_iso) \
                        .lte("work_date", to_iso) \
                        .order("work_date").execute()
            _day = _dh(lambda: {"units": 0.0, "hours": 0.0})
            for _s in (_r3.data or []):
                _dk = _s.get("work_date", "")
                _day[_dk]["units"] += float(_s.get("units") or 0)
                _day[_dk]["hours"] += float(_s.get("hours_worked") or 0)
            history = [{"work_date": _dk,
                        "uph":   round(_v["units"] / _v["hours"], 2) if _v["hours"] > 0 else 0,
                        "units": round(_v["units"]),
                        "hours_worked": round(_v["hours"], 2)}
                       for _dk, _v in sorted(_day.items())]
        except Exception:
            pass

    if not history:
        st.info("No history yet for this employee.")
        return

    uphvals = [float(h.get("uph") or 0) for h in history if h.get("uph")]
    avg_uph = round(sum(uphvals) / len(uphvals), 2) if uphvals else None
    st.metric(f"Avg UPH ({from_str} – {to_str})", f"{avg_uph:.2f}" if avg_uph else "No data")

    df = pd.DataFrame([{
        "Date":  h.get("work_date", ""),
        "UPH":   round(float(h.get("uph") or 0), 2),
        "Units": int(h.get("units", 0) or 0),
        "Hours": round(float(h.get("hours_worked") or 0), 2),
    } for h in history]).sort_values("Date")

    # Remove rows with 0 or non-finite UPH before charting to avoid Infinity warnings
    import math as _math
    df_chart = df[df["UPH"].apply(lambda x: x > 0 and _math.isfinite(x))]
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
@st.fragment
def _emp_ai_coaching():
    """Show AI-powered coaching recommendations based on performance data."""
    st.subheader("🤖 Coaching Insights")
    st.caption("Smart recommendations based on employee performance, goals, and trends.")

    if not st.session_state.get("pipeline_done") and not st.session_state.get("_archived_loaded"):
        _build_archived_productivity()

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
            hc1, hc2 = st.columns([4, 1])
            hc1.markdown(f"### {emp_name}")
            hc1.caption(emp_dept)

            # Show trend + goal summary inline
            _emp_gs = next((r for r in gs if str(r.get("EmployeeID","")) == str(emp_id)), None)
            if _emp_gs:
                _trend_icon = {"up": "↑", "down": "↓", "flat": "→"}.get(_emp_gs.get("trend",""), "—")
                _chg = _emp_gs.get("change_pct", 0)
                _chg_str = f"+{_chg:.1f}%" if _chg > 0 else f"{_chg:.1f}%"
                _uph = _emp_gs.get("Average UPH", 0)
                _tgt = _emp_gs.get("Target UPH", "—")
                st.markdown(
                    f"<span style='font-size:13px;'>"
                    f"Avg UPH: <strong>{_uph:.1f}</strong> · "
                    f"Target: <strong>{_tgt}</strong> · "
                    f"Status: <strong>{translate_to_floor_language(_emp_gs.get('goal_status', ''))}</strong> · "
                    f"Direction: {_trend_icon} {_chg_str}"
                    f"</span>",
                    unsafe_allow_html=True)

                st.markdown("##### ▶ Next Coaching Step")
                _recent_notes = _cached_coaching_notes_for(emp_id)
                if _recent_notes:
                    _last_note = _recent_notes[0]
                    _last_date = str(_last_note.get("created_at", ""))[:10]
                    st.caption(f"Last conversation: {_last_date}")
                    _impact = find_coaching_impact(emp_id, _recent_notes, history_rows)
                    if _impact:
                        show_coaching_impact(emp_name, _impact)
                else:
                    st.caption("No prior coaching note on file yet.")
                if _emp_gs.get("trend", "") == "down" and _emp_gs.get("goal_status", "") == "below_goal":
                    st.warning("Performance is dropping while already below target. Suggested: reset the standard and remove blockers now.")
                elif _emp_gs.get("trend", "") == "down":
                    st.info("Performance is slipping. Suggested: quick check-in and reset one daily focus target.")
                else:
                    st.info("Suggested: confirm what is working and set one measurable next-step target.")

            if is_flagged:
                flag_info = flags.get(emp_id, {})
                st.warning(f"🚩 Flagged for performance tracking since **{flag_info.get('flagged_on','')}**")
                if st.button("✓ Remove flag", key="cn_unflag", type="secondary"):
                    from goals import unflag_employee
                    unflag_employee(emp_id)
                    _raw_cached_active_flags.clear()
                    for r in st.session_state.get("goal_status", []):
                        if str(r.get("EmployeeID","")) == str(emp_id):
                            r["flagged"] = False
                    st.rerun()

            # ── Add entry ────────────────────────────────────────────────────
            if "cn_note_val" not in st.session_state: st.session_state.cn_note_val = ""
            if "cn_by_val"   not in st.session_state: st.session_state.cn_by_val   = ""
            note_text  = st.text_area("Add a journal entry", height=130, key="cn_note",
                                       value=st.session_state.cn_note_val,
                                       placeholder="What did you discuss? What's the plan? Any follow-up needed?")
            nc1, nc2 = st.columns([2, 3])
            created_by = nc2.text_input("Your name (optional)", key="cn_by",
                                         value=st.session_state.cn_by_val,
                                         placeholder="Your name")
            if nc1.button("💾 Save entry", type="primary", use_container_width=True):
                if note_text.strip():
                    add_coaching_note(emp_id, note_text.strip(), created_by.strip())
                    _raw_cached_coaching_notes_for.clear()
                    _raw_cached_all_coaching_notes.clear()
                    st.session_state.cn_note_val = ""
                    st.session_state.cn_by_val   = ""
                    # Increment session count and track last coached employee
                    st.session_state["_coached_today"] = int(st.session_state.get("_coached_today", 0)) + 1
                    st.session_state["_last_coached_emp_id"] = emp_id  # Track for adaptive rail
                    # Count remaining below-goal (excluding current employee)
                    _remaining_risk = [
                        r for r in st.session_state.get("goal_status", [])
                        if r.get("goal_status") == "below_goal"
                        and str(r.get("EmployeeID", r.get("Employee Name", ""))) != str(emp_id)
                    ]
                    _n_rem = len(_remaining_risk)
                    # Store feedback in session_state — survives rerun and shows
                    # on the very next render so the user sees real context.
                    st.session_state["_cn_feedback"] = {
                        "emp_name": emp_name,
                        "emp_id": emp_id,
                        "remaining": _n_rem,
                        "coached_today": int(st.session_state.get("_coached_today", 0)),
                    }
                    st.rerun()
                else:
                    st.warning("Write something before saving the entry.")

            # ── Past entries (collapsed to reduce visual noise, expand on demand) ─
            notes = _cached_coaching_notes_for(emp_id)
            st.divider()
            _n_count = len(notes)
            if _n_count == 1:
                _notes_lbl = "📋 1 past entry — click to view"
            elif _n_count > 1:
                _notes_lbl = f"📋 {_n_count} past entries — click to view"
            else:
                _notes_lbl = "📋 No past entries yet"
            with st.expander(_notes_lbl, expanded=(_n_count > 0 and _n_count <= 2)):
                if notes:
                    for n in notes:
                        with st.container():
                            nc1, nc2 = st.columns([10, 1])
                            _n_date = _html_mod.escape(str(n.get('created_at',''))[:10])
                            _n_by = _html_mod.escape(n.get('created_by',''))
                            _n_text = _html_mod.escape(n.get('note',''))
                            nc1.markdown(
                                f"<div style='background:#F7F9FC;border-left:3px solid #0F2D52;"
                                f"border-radius:4px;padding:8px 12px;margin-bottom:4px;'>"
                                f"<span style='color:#5A7A9C;font-size:11px;'>"
                                f"{_n_date}"
                                f"{'  ·  ' + _n_by if _n_by else ''}</span>"
                                f"<br><span style='color:#1A2D42;font-size:13px;'>{_n_text}</span>"
                                f"</div>",
                                unsafe_allow_html=True)
                            note_id = n.get("id")
                            if note_id and nc2.button("🗑", key=f"del_{note_id}", help="Delete"):
                                delete_coaching_note(str(note_id))
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
                    st.caption("No journal entries yet — add one above.")




# ══════════════════════════════════════════════════════════════════════════════
# PAGE: PRODUCTIVITY (UPH rankings, goals, tracker — existing functionality)
# ══════════════════════════════════════════════════════════════════════════════



def _build_archived_productivity(force: bool = False):
    """
    Build productivity session state from DB. Queries aggregate data directly
    to avoid fetching thousands of raw rows.
    Skips the rebuild if data was loaded recently (within 600 s) unless force=True.
    """
    _last = float(st.session_state.get("_archived_last_refresh_ts", 0.0) or 0.0)
    if not force and st.session_state.get("_archived_loaded") and (time.time() - _last) < 600:
        return True  # already fresh — skip the DB round-trip
    from collections import defaultdict
    from datetime import datetime as _dt

    emps     = {e["emp_id"]: e for e in (_cached_employees() or [])}
    emp_dept = {eid: e.get("department","") for eid, e in emps.items()}
    emp_name = {eid: e.get("name", eid)    for eid, e in emps.items()}

    # Don't bail if employees table is empty — UPH history has dept/emp info
    try:
        sb = _get_db_client()
    except NameError:
        from database import get_client as _db_get_client
        sb = _db_get_client()

    # ── Per-employee aggregates (avg UPH, total units, record count) ──────────
    # Use running sum+count instead of growing lists to keep memory constant.
    emp_agg        = defaultdict(lambda: {"uph_sum": 0.0, "units": 0.0, "count": 0})
    month_dept_agg = defaultdict(lambda: defaultdict(lambda: {"uph_sum": 0.0, "uph_count": 0, "units": 0.0}))
    week_dept_agg  = defaultdict(lambda: defaultdict(lambda: {"units": 0.0, "uph_sum": 0.0, "uph_count": 0}))
    # Per-employee daily UPH for rolling average
    emp_daily      = defaultdict(list)  # eid -> [(date, uph)]
    # Per-employee weekly UPH for trend analysis
    emp_week_uph   = defaultdict(lambda: defaultdict(list))  # emp_id -> week_str -> [uph values]

    page_size = 1000
    offset    = 0
    total_rows = 0
    _last_err  = None
    while True:
        try:
            from database import _tq as _tq_fn
            r = _tq_fn(sb.table("uph_history").select(
                "emp_id, work_date, uph, units, department"
            )).order("work_date").range(offset, offset + page_size - 1).execute()
            batch = r.data or []
        except Exception as _pe:
            _last_err = repr(_pe)
            break
        for row in batch:
            eid   = row.get("emp_id","")
            uph   = float(row.get("uph") or 0)
            units = float(row.get("units") or 0)
            dept  = emp_dept.get(eid) or row.get("department") or "Unknown"
            # Backfill dept/name from UPH history when employees table is empty
            if eid not in emp_dept and dept:
                emp_dept[eid] = dept
            if eid not in emp_name:
                emp_name[eid] = eid  # fallback to ID
            wd    = (row.get("work_date") or "")[:10]
            month = wd[:7]
            if uph > 0:
                emp_agg[eid]["uph_sum"] += uph
                emp_agg[eid]["count"]   += 1
            emp_agg[eid]["units"] += units
            emp_daily[eid].append((wd, uph))
            if month and uph > 0:
                month_dept_agg[month][dept]["uph_sum"]   += uph
                month_dept_agg[month][dept]["uph_count"] += 1
                month_dept_agg[month][dept]["units"]     += units
            if wd:
                try:
                    d  = _dt.strptime(wd, "%Y-%m-%d")
                    wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
                    week_dept_agg[wk][dept]["units"] += units
                    if uph > 0:
                        week_dept_agg[wk][dept]["uph_sum"]   += uph
                        week_dept_agg[wk][dept]["uph_count"] += 1
                        emp_week_uph[eid][wk].append(uph)
                except Exception:
                    pass
        total_rows += len(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    # Fallback to unit_submissions if uph_history empty
    if total_rows == 0:
        offset = 0
        while True:
            try:
                r = _tq_fn(sb.table("unit_submissions").select(
                    "emp_id, work_date, units, hours_worked"
                )).order("work_date").range(offset, offset + page_size - 1).execute()
                batch = r.data or []
            except Exception:
                break
            for row in batch:
                eid   = row.get("emp_id","")
                units = float(row.get("units") or 0)
                hours = float(row.get("hours_worked") or 0)
                uph   = round(units / hours, 2) if hours > 0 else 0
                dept  = emp_dept.get(eid, "Unknown")
                wd    = (row.get("work_date") or "")[:10]
                month = wd[:7]
                if uph > 0:
                    emp_agg[eid]["uph_sum"] += uph
                    emp_agg[eid]["count"]   += 1
                emp_agg[eid]["units"] += units
                emp_daily[eid].append((wd, uph))
                if month and uph > 0:
                    month_dept_agg[month][dept]["uph_sum"]   += uph
                    month_dept_agg[month][dept]["uph_count"] += 1
                    month_dept_agg[month][dept]["units"]     += units
                if wd:
                    try:
                        d  = _dt.strptime(wd, "%Y-%m-%d")
                        wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
                        week_dept_agg[wk][dept]["units"]     += units
                        if uph > 0:
                            week_dept_agg[wk][dept]["uph_sum"]   += uph
                            week_dept_agg[wk][dept]["uph_count"] += 1
                    except Exception:
                        pass
            total_rows += len(batch)
            if len(batch) < page_size:
                break
            offset += page_size

    # Calculate employee rolling averages
    employee_rolling_avg = []
    for eid, dates_uph in emp_daily.items():
        if not dates_uph:
            continue
        df = pd.DataFrame(dates_uph, columns=['Date', 'UPH'])
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        df = df.sort_values('Date')
        df = df.set_index('Date')
        df['7DayRollingAvg'] = df['UPH'].rolling('7D', min_periods=1).mean()
        df['14DayRollingAvg'] = df['UPH'].rolling('14D', min_periods=1).mean()
        df = df.reset_index()
        for _, row in df.iterrows():
            employee_rolling_avg.append({
                'Date': row['Date'].strftime('%Y-%m-%d'),
                'Employee': emp_name.get(eid, eid),
                'UPH': round(row['UPH'], 2) if pd.notna(row['UPH']) else None,
                '7DayRollingAvg': round(row['7DayRollingAvg'], 2),
                '14DayRollingAvg': round(row['14DayRollingAvg'], 2)
            })
    employee_rolling_avg.sort(key=lambda r: (r["Employee"], r["Date"]))

    if not emp_agg:
        st.session_state["_archived_loaded"] = False
        # Show what we found for debugging
        if hasattr(st, "session_state"):
            st.session_state["_arch_debug"] = f"uph_history rows: {total_rows}, unit_submissions fallback ran: {total_rows == 0}"
        return False

    # ── Build ranked list ─────────────────────────────────────────────────────
    ranked = []
    for i, (eid, agg) in enumerate(
            sorted(emp_agg.items(),
                   key=lambda x: x[1]["uph_sum"] / max(x[1]["count"], 1),
                   reverse=True), 1):
        avg_uph = round(agg["uph_sum"] / max(agg["count"], 1), 2)
        ranked.append({
            "Rank":          i,
            "Department":    emp_dept.get(eid, ""),
            "Shift":         "",
            "Employee Name": emp_name.get(eid, eid),
            "Average UPH":   avg_uph,
            "Record Count":  agg["count"],
            "EmployeeID":    eid,
            "goal_status":   "no_goal",
            "trend":         "insufficient_data",
            "flagged":       False,
            "change_pct":    0,
            "Target UPH":    "—",
            "vs Target":     "—",
        })

    # ── dept_trends ───────────────────────────────────────────────────────────
    dept_trends = []
    for month in sorted(month_dept_agg):
        for dept, vals in month_dept_agg[month].items():
            if vals["uph_count"] > 0:
                dept_trends.append({
                    "Month":       month,
                    "Department":  dept,
                    "Average UPH": round(vals["uph_sum"] / vals["uph_count"], 2),
                    "Count":       vals["uph_count"],
                })

    # ── weekly_summary ────────────────────────────────────────────────────────
    weekly_summary = []
    for wk in sorted(week_dept_agg):
        for dept, vals in week_dept_agg[wk].items():
            weekly_summary.append({
                "Week":        wk,
                "Month":       wk[:7],
                "Department":  dept,
                "Total Units": round(vals["units"]),
                "Avg UPH":     round(vals["uph_sum"] / max(vals["uph_count"], 1), 2),
            })

    # ── dept_report ───────────────────────────────────────────────────────────
    dept_report = {}
    for r2 in ranked:
        dept_report.setdefault(r2.get("Department",""), []).append(r2)

    # ── Build trend_data from per-employee weekly UPH ─────────────────────────
    _trend_weeks = 4
    try:
        import streamlit as _st2
        _trend_weeks = _st2.session_state.get("trend_weeks", 4)
    except Exception:
        pass
    all_weeks_sorted = sorted(
        {wk for emp_wks in emp_week_uph.values() for wk in emp_wks}
    )
    recent_weeks = all_weeks_sorted[-_trend_weeks:] if len(all_weeks_sorted) >= _trend_weeks else all_weeks_sorted

    trend_data = {}
    for eid, week_map in emp_week_uph.items():
        week_avgs = []
        for w in recent_weeks:
            vals = week_map.get(w, [])
            if vals:
                week_avgs.append({"week": w, "avg_uph": round(sum(vals) / len(vals), 2)})

        if len(week_avgs) < 2:
            direction  = "insufficient_data"
            change_pct = 0.0
        else:
            first = week_avgs[0]["avg_uph"]
            last  = week_avgs[-1]["avg_uph"]
            change_pct = round(((last - first) / first * 100) if first else 0, 1)
            if change_pct >= 3:
                direction = "up"
            elif change_pct <= -3:
                direction = "down"
            else:
                direction = "flat"

        trend_data[eid] = {
            "name":       emp_name.get(eid, eid),
            "dept":       emp_dept.get(eid, ""),
            "direction":  direction,
            "weeks":      week_avgs,
            "change_pct": change_pct,
        }

    # ── Apply goals ───────────────────────────────────────────────────────────
    try:
        from goals import build_goal_status as _bgs
        _arch_gs = _bgs(ranked, _cached_targets(), trend_data)
    except Exception:
        _arch_gs = ranked

    st.session_state.update({
        "top_performers":  ranked,
        "goal_status":     _arch_gs,
        "dept_report":     dept_report,
        "dept_trends":     dept_trends,
        "weekly_summary":  weekly_summary,
        "employee_rolling_avg": employee_rolling_avg,
        "employee_risk": [],
        "trend_data":      trend_data,
        "pipeline_done":   True,
        "_archived_loaded": True,
        "_archived_last_refresh_ts": time.time(),
    })
    return True


