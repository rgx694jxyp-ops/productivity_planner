from core.dependencies import (
    _cached_all_coaching_notes,
    _cached_coaching_notes_for,
    _cached_employees,
)
from core.runtime import _html_mod, date, st
from domain.risk import _get_all_risk_levels
from pages.common import load_goal_status_history
from services.coaching_service import summarize_coaching_activity
from services.recommendation_service import _render_adaptive_action_suggestion
from ui.components import (
    _render_breadcrumb,
    _render_confidence_ux,
    _render_session_context_bar,
    _render_session_progress,
    build_operation_status,
    detect_department_patterns,
    is_simple_mode,
    show_coaching_activity_summary,
    show_operation_status_header,
    show_pattern_detection_panel,
    show_resume_session_card,
    show_shift_complete_state,
    show_start_shift_card,
    simplified_supervisor_view,
)
from ui.coaching_components import (
    _render_primary_action_rail,
    _render_priority_strip,
)

def page_supervisor():
    """One-screen supervisor view: risks, trends, context, actions. Daily-use focused."""
    st.title("👔 Supervisor View")
    st.caption("One-screen daily overview: team health, top risks, and next steps.")

    gs, history = load_goal_status_history("Loading supervisor data…")
    if gs is None:
        return
    
    if not gs:
        st.info("No productivity data. Run Import Data to get started.")
        return

    # ── Welcome back / daily continuity message (shown once per session) ─────────
    if not st.session_state.get("_welcome_shown"):
        st.session_state["_welcome_shown"] = True
        _user   = st.session_state.get("user_name", "").split("@")[0].split(" ")[0]
        _greet  = f"Welcome back{', ' + _user if _user else ''}"
        _below  = len([r for r in gs if r.get("goal_status") == "below_goal"])
        _risk_c = _get_all_risk_levels(gs, history)
        _high   = sum(1 for v in _risk_c.values() if v[0].startswith("🔴"))
        _coached_yesterday = int(st.session_state.get("_coached_yesterday", 0))
        _lines  = []
        if _coached_yesterday > 0:
            _pl = "employee" if _coached_yesterday == 1 else "employees"
            _lines.append(f"✔ You coached {_coached_yesterday} {_pl} last session")
        if _below > 0:
            _lines.append(f"⚠ {_below} employee{'s' if _below != 1 else ''} still below goal ({_high} high-risk)")
        else:
            _lines.append("✔ All employees on target — great shape")
        _body = "<br>".join(f"<span style='font-size:13px;color:#1B5E20;'>{l}</span>" for l in _lines)
        st.markdown(
            f'<div style="background:linear-gradient(135deg,#E8F5E9 0%,#E3F2FD 100%);'
            f'border:1.5px solid #43A047;border-radius:10px;padding:16px 20px;margin-bottom:18px;">'
            f'<div style="font-size:15px;font-weight:800;color:#1B5E20;margin-bottom:8px;">{_html_mod.escape(_greet)}</div>'
            f'{_body}'
            f'</div>',
            unsafe_allow_html=True,
        )


    # Session context and breadcrumbs
    _render_breadcrumb("supervisor")
    _render_session_context_bar()

    _coachable_emp_ids = _cached_all_coaching_notes()
    _notes_by_emp = {
        emp_id: _cached_coaching_notes_for(emp_id)
        for emp_id in _coachable_emp_ids
    }
    _op_status = build_operation_status(gs)
    _patterns = detect_department_patterns(gs)
    _coaching_activity = summarize_coaching_activity(_notes_by_emp, history)

    _risk_cache_all = _get_all_risk_levels(gs, history)
    risk_summary = []
    for row in [r for r in gs if r.get("goal_status") == "below_goal"]:
        _eid = str(row.get("EmployeeID", row.get("Employee Name", "")))
        _level, _score, _details = _risk_cache_all.get(_eid, ("🟢 Low", 0, {}))
        risk_summary.append({"level": _level, "score": _score})
    high_priority_remaining = sum(1 for item in risk_summary if str(item["level"]).startswith("🔴"))
    medium_priority_remaining = sum(1 for item in risk_summary if str(item["level"]).startswith("🟡"))
    coached_today = int(st.session_state.get("_coached_today", 0))

    show_operation_status_header(_op_status)
    
    _render_session_progress(gs)
    _render_primary_action_rail(gs, history, key_prefix="sup_primary")
    _render_priority_strip(gs, history)
    _render_confidence_ux(history)

    follow_up_due = 0
    for e in (_cached_employees() or []):
        try:
            emp_notes = _cached_coaching_notes_for(e.get("emp_id", ""))
            if emp_notes:
                last_dt = str(emp_notes[0].get("created_at", ""))[:10]
                if last_dt == date.today().isoformat():
                    continue
                follow_up_due += 1
        except Exception:
            pass

    show_start_shift_card(gs, follow_up_due)
    adaptive = _render_adaptive_action_suggestion(gs, history, st.session_state.get("_last_coached_emp_id"))
    if adaptive and coached_today > 0 and adaptive.get("emp_id"):
        show_resume_session_card(adaptive["name"], adaptive.get("context", "Next up"), adaptive["emp_id"])
    show_shift_complete_state(high_priority_remaining, medium_priority_remaining, coached_today)
    st.divider()

    # ── SIMPLE MODE: Stripped-down view for quick daily use ───────────────────
    if is_simple_mode():
        simplified_supervisor_view(gs)
        show_coaching_activity_summary(_coaching_activity)
        return
    
    # ────────────────────────────────────────────────────────────────────────────
    # SECTION 1: DEPARTMENT HEALTH SUMMARY (Exception-Only By Default)
    # ────────────────────────────────────────────────────────────────────────────
    
    st.subheader("📊 Team Health Snapshot")

    # System issue detection — shown first so it's not buried
    _high_patterns = [p for p in _patterns if p["severity"] == "high"]
    if _high_patterns:
        show_pattern_detection_panel(_patterns)
        st.divider()

    depts = sorted(set(r.get("Department", "") for r in gs if r.get("Department")))
    
    dept_summary = {}
    for dept in depts:
        dept_emps = [r for r in gs if r.get("Department") == dept]
        on_goal = len([r for r in dept_emps if r.get("goal_status") == "on_goal"])
        below_goal = len([r for r in dept_emps if r.get("goal_status") == "below_goal"])
        total = len(dept_emps)
        health_pct = round((on_goal / total * 100) if total > 0 else 0)
        
        dept_summary[dept] = {
            "on_goal": on_goal,
            "below_goal": below_goal,
            "total": total,
            "health_pct": health_pct,
        }
    
    exception_depts = [d for d in depts if dept_summary[d]["below_goal"] > 0]
    shown_depts = exception_depts or depts
    
    # Display exception departments prominently
    if exception_depts:
        st.caption(f"🔴 **{len(exception_depts)} exception department(s)** — at least one below-goal employee")
        dept_cols = st.columns(len(exception_depts))
        for col, dept in zip(dept_cols, exception_depts):
            s = dept_summary[dept]
            col.metric(
                f"**{dept}**",
                f"{s['on_goal']}/{s['total']} on goal",
                f"{s['health_pct']}%",
                label_visibility="visible"
            )
        
        # Collapsible full team health for all-clear departments
        with st.expander("View all departments (including on-target)"):
            all_cols = st.columns(len(depts))
            for col, dept in zip(all_cols, depts):
                s = dept_summary[dept]
                col.metric(
                    f"**{dept}**",
                    f"{s['on_goal']}/{s['total']} on goal",
                    f"{s['health_pct']}%",
                    label_visibility="visible"
                )
    else:
        st.success("✅ All departments healthy — no exceptions")
        st.caption("All employees are meeting or exceeding goals.")
        dept_cols = st.columns(len(shown_depts) if shown_depts else 1)
        for col, dept in zip(dept_cols, shown_depts):
            s = dept_summary[dept]
            col.metric(
                f"**{dept}**",
                f"{s['on_goal']}/{s['total']} on goal",
                f"{s['health_pct']}%",
                label_visibility="visible"
            )
    
    # Show non-high patterns (medium/individual) after the dept snapshot
    _non_high_patterns = [p for p in _patterns if p["severity"] != "high"]
    if _non_high_patterns:
        show_pattern_detection_panel(_non_high_patterns)
    elif not _high_patterns:
        show_pattern_detection_panel([])  # shows the "no system patterns" success card

    st.divider()
    
    # ────────────────────────────────────────────────────────────────────────────
    # SECTION 2: TOP RISKS (5-10 employees)
    # ────────────────────────────────────────────────────────────────────────────
    
    st.subheader("🔴 Top Risks — Action Required Today")
    
    # Filter for below_goal and calculate risk
    below_goal = [r for r in gs if r.get("goal_status") == "below_goal"]
    
    if not below_goal:
        st.success("✅ All employees meeting goals!")
    else:
        risk_list = []
        _risk_cache_all = _get_all_risk_levels(gs, history)
        for emp in below_goal:
            emp_id = str(emp.get("EmployeeID", emp.get("Employee Name", "")))
            risk_level, risk_score, risk_details = _risk_cache_all.get(emp_id, ("🟢 Low", 0, {}))
            
            # Get flagged info for context tags
            flagged_info = {}
            try:
                from goals import get_employee_flags
                all_flags = get_employee_flags()
                flagged_info = next((f for f in all_flags if f.get("emp_id") == emp_id), {})
            except Exception:
                pass
            
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
                "context_tags": flagged_info.get("context_tags", []),
            })
        
        # Sort by risk score (highest first) and take top 5
        risk_list.sort(key=lambda x: x["risk_score"], reverse=True)
        top_risks = risk_list[:5]
        
        # Display each top risk
        for i, emp in enumerate(top_risks, 1):
            try:
                target = float(emp["target_uph"]) if emp["target_uph"] != "—" else 0
                gap = target - emp["avg_uph"]
                gap_str = f"-{gap:.1f} UPH" if gap > 0 else "—"
            except (ValueError, TypeError):
                gap_str = "—"
            
            # Build summary row
            col1, col2, col3, col4, col5 = st.columns([1, 2, 1.5, 1, 2])
            col1.write(f"**#{i}**")
            col2.write(f"**{emp['name']}** · {emp['department']}")
            col3.write(f"{emp['risk_level']} ({emp['risk_score']:.1f})")
            col4.write(f"{emp['avg_uph']:.1f} / {emp['target_uph']}")
            col5.write(f"{emp['trend']} {emp['change_pct']:+.0f}%")
            
            # Expandable details
            with st.expander(f"View context & actions for {emp['name']}", expanded=False):
                # Context tags
                if emp['context_tags']:
                    tag_cols = st.columns(len(emp['context_tags']))
                    for tag_col, tag in zip(tag_cols, emp['context_tags']):
                        tag_col.markdown(f"📌 {tag}")
                    st.write("")
                
                # Risk breakdown
                d = emp['risk_details']
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("Trend", f"{d.get('trend_score', 0):+.0f}pt", "down trend" if d.get("trend_score", 0) >= 4 else "")
                rc2.metric("Streak", f"{d.get('streak_score', 0):.1f}pt", f"{d.get('under_goal_streak', 0)} days below")
                rc3.metric("Variance", f"{d.get('variance_score', 0):.1f}pt", f"{d.get('variance_pct', 0):.0f}% CV")
                
                st.write("")
                st.markdown("**👉 Suggested Next Actions:**")
                
                # Build context-aware actions
                actions = []
                
                # Context-specific actions (take priority)
                if "Equipment issues" in emp['context_tags']:
                    actions.append("🔧 **Fix the equipment first** — Resolve tool/system issues before coaching.")
                if "New employee" in emp['context_tags']:
                    actions.append("📋 **Structured onboarding check** — Ensure proper training & mentoring.")
                if "Cross-training" in emp['context_tags']:
                    actions.append("🎓 **Support transition** — Provide extra mentoring during skill-building.")
                if "Shift change" in emp['context_tags']:
                    actions.append("⏰ **Allow adjustment time** — Follow up in 2 weeks for impact.")
                if "Short staffed" in emp['context_tags']:
                    actions.append("👥 **Increase capacity** — Hiring or redistribution may help faster.")
                
                # Trend-based actions
                if not any(tag in emp['context_tags'] for tag in ["Equipment issues", "Short staffed"]):
                    if emp["trend"] == "down":
                        actions.append("💬 **Identify obstacles** — Ask what's changed. Check for workload/personal issues.")
                    elif emp["trend"] == "flat":
                        actions.append("📈 **Break the plateau** — Try different task rotation or side-by-side work with a high performer.")
                
                # Gap-based actions
                try:
                    target = float(emp["target_uph"]) if emp["target_uph"] != "—" else 0
                    if target > 0:
                        gap = target - emp["avg_uph"]
                        if gap > 5 and "New employee" not in emp['context_tags']:
                            actions.append("📊 **Major gap** — Structured improvement plan with weekly check-ins.")
                        elif gap > 2 and "New employee" not in emp['context_tags']:
                            actions.append("🤝 **1-on-1 coaching** — Discuss goals and what support they need.")
                except (ValueError, TypeError):
                    pass
                
                # Default if no actions were generated
                if not actions:
                    actions.append("🤝 **1-on-1 conversation** — Discuss performance, barriers, and support.")
                
                for action in actions:
                    st.write(action)
    
    st.divider()
    
    # ────────────────────────────────────────────────────────────────────────────
    # SECTION 3: TRENDING DOWN ALERTS
    # ────────────────────────────────────────────────────────────────────────────
    
    with st.expander("📉 Trends (collapsed by default)", expanded=False):
        st.subheader("⚠️ Trending Down — Proactive Check-In Recommended")
        trending_down = [r for r in gs if r.get("trend") == "down" and r.get("goal_status") != "below_goal"]
        
        if trending_down:
            st.caption(f"⚠️ {len(trending_down)} employee(s) showing downward trend but NOT yet below goal.")
            for emp in trending_down[:5]:  # Show top 5 only
                col1, col2, col3 = st.columns([2, 1, 2])
                col1.write(f"**{emp.get('Employee Name', 'Unknown')}** ({emp.get('Department', '')})")
                col2.write(f"↓ {emp.get('change_pct', 0):+.0f}%")
                col3.write(f"{emp.get('Average UPH', 0):.1f} / {emp.get('Target UPH', '—')}")
        else:
            st.success("✅ No concerning trends detected.")
    
    st.divider()
    
    # ────────────────────────────────────────────────────────────────────────────
    # SECTION 4: BUSINESS IMPACT (What it costs to not coach)
    # ────────────────────────────────────────────────────────────────────────────
    
    st.subheader("💰 This Week's Cost Impact")
    
    # Try to get hourly wage from settings
    try:
        from settings import Settings as _ImpactS
        _avg_wage = _ImpactS().get("avg_hourly_wage", 18.0)
    except Exception:
        _avg_wage = 18.0
    
    # Calculate labor cost for below-goal employees
    cost_by_emp = []
    for emp in below_goal:
        emp_name = emp.get("Employee Name", emp.get("Employee", "Unknown"))
        target = emp.get("Target UPH", "—")
        avg_uph = emp.get("Average UPH", 0)
        
        if target == "—" or target is None or not avg_uph:
            continue
        
        try:
            target = float(target)
            avg_uph = float(avg_uph)
        except (ValueError, TypeError):
            continue
        
        if target <= 0:
            continue
        
        # Assume 40-hour work week
        hours_week = 40.0
        expected_units = target * hours_week
        actual_units = avg_uph * hours_week
        unit_diff = actual_units - expected_units
        
        if unit_diff >= 0:  # Only negative impacts count
            continue
        
        cost_per_unit = _avg_wage / target if target > 0 else 0
        weekly_cost = abs(unit_diff * cost_per_unit)
        
        cost_by_emp.append({
            "name": emp_name,
            "department": emp.get("Department", ""),
            "weekly_cost": weekly_cost,
            "gap": target - avg_uph,
        })
    
    if cost_by_emp:
        cost_by_emp.sort(key=lambda x: x["weekly_cost"], reverse=True)
        top_3_cost = cost_by_emp[:3]
        total_top_3_cost = sum(e["weekly_cost"] for e in top_3_cost)
        
        st.error(f"🔴 **Top 3 underperformers costing ${total_top_3_cost:,.0f} this week**")
        
        for i, emp in enumerate(top_3_cost, 1):
            c1, c2, c3 = st.columns([2, 1, 1.5])
            c1.write(f"**{i}. {emp['name']}** ({emp['department']})")
            c2.metric("Gap", f"-{emp['gap']:.1f} UPH")
            c3.metric("Weekly Cost", f"${emp['weekly_cost']:,.0f}")
        
        st.caption(f"📣 **Key insight:** Improving these 3 people alone would save ${total_top_3_cost:,.0f}/week (${ total_top_3_cost * 52:,.0f}/year).")
    else:
        st.success("✅ No significant labor cost impact detected.")
    
    st.divider()

    # ── Department Trends Chart ──────────────────────────────────────────────
    st.subheader("📈 Department UPH Trends")
    try:
        import pandas as pd
        import math as _math
        dept_trends = st.session_state.get("dept_trends", [])
        if dept_trends:
            df_trends = pd.DataFrame(dept_trends)
            df_trends_clean = df_trends[df_trends["Average UPH"].apply(
                lambda x: _math.isfinite(float(x)) if x is not None else False
            )].copy()
            if not df_trends_clean.empty:
                st.caption("Average UPH by department across all employees each month.")
                st.line_chart(
                    df_trends_clean.pivot(index="Month", columns="Department", values="Average UPH"),
                    use_container_width=True
                )
            else:
                st.info("No department trend data available yet.")
        else:
            st.info("No department trend data available yet.")
    except Exception:
        pass

    st.divider()

    show_coaching_activity_summary(_coaching_activity)

    st.divider()
    
    # ────────────────────────────────────────────────────────────────────────────
    # SECTION 5: QUICK COACHING TIPS (Generic)
    # ────────────────────────────────────────────────────────────────────────────
    
    st.subheader("💡 Quick Coaching Tips")
    with st.expander("How to approach coaching conversations", expanded=False):
        st.markdown("""
**For High Risk (🔴):**
- Schedule immediate 1-on-1
- Ask: "What obstacles are you facing?"
- Identify specific, measurable targets
- Plan weekly check-in reviews

**For Medium Risk (🟡):**
- Proactive check-in within 3-5 days
- Discuss trends: "I've noticed a dip the last few days"
- Offer support: extra training, side-by-side observation, additional resources
- Set clear improvement goals

**For Trending Down (but still on goal):**
- Friendly conversation to prevent further decline
- Ask about workload, personal factors, team dynamics
- Recognize effort while addressing trend

**Universal best practices:**
- Focus on behaviors & solutions, not blame
- Use data to support conversation
- Celebrate wins when they happen
- Make support concrete: training, tools, time
""")
    
    st.divider()
    
    # Footer with quick links
    st.caption("📚 Want to dive deeper? Visit **📈 Productivity** page for detailed analytics and risk breakdown.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: IMPORT DATA
# Clean 3-step flow. Each step only runs when active — no tab lag.
# Step 1: Upload CSV(s)
# Step 2: Map columns (per file, auto-detected)
# Step 3: Run pipeline — employees registered, UPH calculated, data ready
# ══════════════════════════════════════════════════════════════════════════════

def _render_adaptive_rows(items: list[dict], item_key: str = "name", 
                          show_fields: list[str] | None = None, 
                          action_buttons: dict | None = None):
    """
    Render items in an adaptive row layout that adjusts based on:
    - Count of items (few = 2 cols, many = 3-5 cols)
    - Available space (responsive)
    - User preferences (card vs table already shown above)
    
    Args:
        items: List of dicts to display
        item_key: Which field to use as primary display (name, employee, etc)
        show_fields: Which fields to show in each row (default: auto)
        action_buttons: Dict of {button_label: callback_fn}
    """
    if not items:
        st.info("No items to display")
        return
    
    # Auto-determine optimal columns based on count
    item_count = len(items)
    if item_count <= 3:
        cols_per_row = 2
    elif item_count <= 8:
        cols_per_row = 3
    else:
        cols_per_row = 4
    
    # Default fields if none specified
    if show_fields is None:
        if "avg_uph" in items[0]:
            show_fields = ["name", "department", "avg_uph", "risk_level"]
        elif "employee" in items[0]:
            show_fields = ["employee", "department", "score"]
        else:
            show_fields = list(items[0].keys())[:3]
    
    # Render in rows
    for row_idx in range(0, len(items), cols_per_row):
        row_items = items[row_idx:row_idx + cols_per_row]
        cols = st.columns(cols_per_row)
        
        for col_idx, item in enumerate(row_items):
            with cols[col_idx]:
                st.markdown(f"### {item.get(item_key, 'Unknown')}")
                
                # Show selected fields as compact info
                for field in show_fields:
                    if field in item and field != item_key:
                        val = item[field]
                        field_label = field.replace("_", " ").title()
                        st.caption(f"{field_label}: {val}")
                
                # Action buttons
                if action_buttons:
                    btn_cols = st.columns(len(action_buttons))
                    for btn_col, (btn_label, btn_handler) in zip(btn_cols, action_buttons.items()):
                        if btn_col.button(btn_label, key=f"adaptive_{row_idx}_{col_idx}_{btn_label}"):
                            btn_handler(item)


