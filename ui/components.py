"""Shared UI components for all pages."""

import streamlit as st
from datetime import datetime, date, timedelta
import pandas as pd
import time

from utils.numeric import safe_float
from ui.floor_language import human_confidence_message
from domain.risk import _get_all_risk_levels
from services.coaching_service import find_coaching_impact


def diagnose_upload(pending_files: list[dict]) -> dict:
    """
    Analyze uploaded data to give friendly diagnosis.
    Returns: {
        "emp_count": int,
        "date_range": (min_date, max_date) or None,
        "days_of_data": int,
        "departments": list,
        "completeness": {"rows_with_hours": int, "rows_total": int},
        "warnings": [str],
        "ready": bool
    }
    """
    total_rows = 0
    all_rows = []
    dates = set()
    depts = set()
    emps = set()
    hours_count = 0
    warnings = []
    malformed_rows_seen = False
    
    for file_info in pending_files:
        rows = file_info.get("rows", [])
        total_rows += len(rows)
        all_rows.extend(rows)
        
        for row in rows:
            if not isinstance(row, dict):
                malformed_rows_seen = True
                continue
            # Extract info
            if row.get("Date") or row.get("work_date") or row.get("date"):
                try:
                    d = row.get("Date") or row.get("work_date") or row.get("date")
                    dates.add(str(d)[:10])  # Extract YYYY-MM-DD
                except:
                    pass
            
            dept = row.get("Department") or row.get("dept") or row.get("Dept") or ""
            if dept:
                depts.add(dept)
            
            emp = row.get("EmployeeID") or row.get("Employee Name") or row.get("employee_id") or ""
            if emp:
                emps.add(emp)
            
            hours = row.get("HoursWorked") or row.get("Hours") or row.get("hours")
            if hours and safe_float(hours, 0.0) > 0:
                hours_count += 1
    
    # Build diagnosis

    if malformed_rows_seen:
        warnings.append("Some uploaded rows could not be parsed cleanly and were skipped during diagnosis")
    
    if total_rows == 0:
        warnings.append("No data rows found")
    elif total_rows < 3:
        warnings.append(f"Only {total_rows} rows — limited insight without more data")
    
    if hours_count < total_rows * 0.8:
        warnings.append(f"Missing hours for {total_rows - hours_count} rows — UPH calculation may be incomplete")
    
    if not dates:
        warnings.append("No date information found — can't calculate trends")
    elif len(dates) < 2:
        warnings.append("Only 1 day of data — can't detect trends yet")
    
    min_date = min(dates) if dates else None
    max_date = max(dates) if dates else None
    date_range = None
    if min_date and max_date:
        try:
            dr = (datetime.strptime(min_date, "%Y-%m-%d").date(), 
                  datetime.strptime(max_date, "%Y-%m-%d").date())
            date_range = dr
        except:
            pass
    
    days_of_data = len(dates) if dates else 0
    
    return {
        "emp_count": len(emps),
        "date_range": date_range,
        "days_of_data": days_of_data,
        "departments": sorted(depts),
        "completeness": {"rows_with_hours": hours_count, "rows_total": total_rows},
        "warnings": warnings,
        "ready": len(warnings) == 0 or hours_count > 0,
    }


def show_diagnosis(diagnosis: dict):
    """
    Display auto-diagnosis in friendly, non-technical language.
    """
    st.markdown("### 📊 Here's what we found")
    
    # Key metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Employees", diagnosis["emp_count"])
    col2.metric("Days of data", diagnosis["days_of_data"])
    col3.metric("Departments", len(diagnosis["departments"]))
    
    # Date range
    if diagnosis["date_range"]:
        min_d, max_d = diagnosis["date_range"]
        st.caption(f"📅 Data spans {min_d.strftime('%b %d')} → {max_d.strftime('%b %d, %Y')}")
    
    # Departments
    if diagnosis["departments"]:
        st.caption(f"📍 {', '.join(diagnosis['departments'])}")
    
    # Completeness
    complete = diagnosis["completeness"]["rows_with_hours"]
    total = diagnosis["completeness"]["rows_total"]
    pct = int(complete / total * 100) if total > 0 else 0
    st.caption(f"✓ {complete}/{total} rows have hours data ({pct}%)")
    
    # Warnings (not errors - we can still work with this)
    if diagnosis["warnings"]:
        st.info("💡 **Important context for this dataset:**")
        for warning in diagnosis["warnings"]:
            st.caption(f"• {warning}")
    
    # Offer reassurance
    if diagnosis["ready"]:
        st.success("✅ Ready to process — we can generate insights from this!")
    else:
        st.warning("⚠️ Limited data, but we can still help. More data = better patterns.")


def show_manual_entry_form() -> list[dict] | None:
    """
    Lightweight manual entry form for users without a CSV file.
    Returns list of rows or None if not submitted.
    """
    st.markdown("### Quick Entry")
    st.caption("Type in today's or this week's data. We'll figure out the rest.")
    
    # How much data to enter?
    entry_span = st.radio("I want to add:", 
                          ["Today's data", "This week", "Multiple days"],
                          help="Choose how much data you have ready")
    
    entry_date = date.today()
    if entry_span == "Multiple days":
        entry_date = st.date_input("Work date for these entries", value=date.today(), key="manual_entry_date")

    # Simple form
    st.markdown("#### Add Production Data")
    
    entries = []
    
    for i in range(5):  # Show 5 rows by default
        cols = st.columns([2, 1, 1, 1, 1])
        
        name = cols[0].text_input("Employee name", key=f"me_name_{i}", placeholder="John")
        dept = cols[1].text_input("Dept", key=f"me_dept_{i}", placeholder="Picking")
        units = cols[2].number_input("Units", key=f"me_units_{i}", min_value=0.0, step=1.0)
        hours = cols[3].number_input("Hours", key=f"me_hours_{i}", min_value=0.0, step=0.5)
        
        if name and units and hours:
            entries.append({
                "EmployeeID": name.strip().lower().replace(" ", "_"),
                "EmployeeName": name,
                "Department": dept or "Unassigned",
                "Units": units,
                "HoursWorked": hours,
                "Date": entry_date.isoformat(),
            })
    
    if entries:
        st.success(f"✓ {len(entries)} entries ready")
        if st.button("Continue with this data →", type="primary", use_container_width=True):
            return entries
    
    return None


def show_coaching_impact(emp_name: str, impact: dict):
    """
    Display coaching impact as a prominent before/after card.
    """
    if not impact:
        return

    before = impact["before_uph"]
    after  = impact["after_uph"]
    change = impact["change_uph"]
    days   = impact["days_since"]
    date_fmt = impact["coached_date"].strftime("%b %d")
    improved = impact["improvement"]

    if improved:
        pct = round((change / before) * 100, 1) if before else 0
        arrow = "📈"
        status_txt = "Improving 👍"
        bg  = "linear-gradient(90deg,#E8F5E9 0%,#E3F2FD 100%)"
        brd = "#43A047"
        clr = "#1B5E20"
        chg_str = f"+{change} (+{pct}%)"
    else:
        pct = round((change / before) * 100, 1) if before else 0
        arrow = "📉"
        status_txt = "No improvement ⚠️"
        bg  = "linear-gradient(90deg,#FFF8E1 0%,#FFF1EC 100%)"
        brd = "#E65100"
        clr = "#7F3606"
        chg_str = f"{change} ({pct}%)"

    st.markdown(
        f"<div style='background:{bg};border-left:4px solid {brd};border-radius:8px;"
        f"padding:12px 16px;margin:8px 0 12px;'>"
        f"<div style='font-size:11px;font-weight:700;text-transform:uppercase;"
        f"letter-spacing:.06em;color:#666;margin-bottom:4px;'>"
        f"{arrow} After Last Coaching · {date_fmt} ({days}d ago)</div>"
        f"<div style='font-size:18px;font-weight:800;color:{clr};'>"
        f"UPH: {before} → {after} &nbsp; <span style='font-size:14px;'>{chg_str}</span></div>"
        f"<div style='font-size:13px;color:{clr};margin-top:2px;'>Status: {status_txt}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def is_simple_mode() -> bool:
    """Check if user has Simple Mode enabled."""
    return st.session_state.get("simple_mode", False)


def toggle_simple_mode():
    """Legacy compatibility hook; Simple Mode toggle is no longer shown."""
    st.session_state["simple_mode"] = False

    # Keep the app on the light theme regardless of mode toggles.
    st.markdown(
        """
        <style>
        html, body, .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewContainer"] > .main,
        [data-testid="stAppViewContainer"] > .main > div,
        section.main,
        .main,
        .main .block-container {
            background: #F7F9FC !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def simplified_supervisor_view(gs: list[dict]):
    """
    Stripped-down supervisor view for Simple Mode.
    Just shows where signals are surfacing, in plain language, with quick drill-down.
    """
    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    
    if not below:
        st.success("✅ Everyone's on track today")
        return
    
    st.markdown("### 👥 People with surfaced signals")
    
    for emp in below[:5]:  # Show top 5
        name = emp.get("Employee Name", emp.get("Employee", "Unknown"))
        dept = emp.get("Department", "")
        status = ""
        
        if emp.get("trend") == "down":
            status = "Performance dropping"
        elif emp.get("goal_status") == "below_goal":
            status = "Below target"
        
        col1, col2 = st.columns([3, 1])
        col1.markdown(f"**{name}** · {dept}\n*{status}*")
        
        if col2.button("View details", key=f"simple_coach_{emp.get('EmployeeID')}", 
                  help="Open performance context"):
            st.session_state["goto_page"] = "employees"
            st.session_state["emp_view"] = "Performance Journal"
            st.session_state["cn_selected_emp"] = str(emp.get("EmployeeID", ""))
            st.rerun()


def show_start_shift_card(gs: list[dict], follow_up_due: int = 0):
    """Simple start-of-shift summary to create a daily usage habit."""
    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    trending = [r for r in gs if r.get("trend") == "down" and r.get("goal_status") != "below_goal"]

    st.markdown("### Start of Shift")
    c1, c2, c3 = st.columns(3)
    c1.metric("Need attention", len(below))
    c2.metric("Watch list", len(trending))
    c3.metric("Follow-up due", follow_up_due)

    if below:
        st.caption("Signals are surfaced for below-target output and downward trend movement.")
        if st.button("▶ Open review", key="start_shift_cta", type="primary", use_container_width=True):
            top_emp = below[0]
            st.session_state["goto_page"] = "employees"
            st.session_state["emp_view"] = "Performance Journal"
            st.session_state["cn_selected_emp"] = str(top_emp.get("EmployeeID", top_emp.get("Employee Name", "")))
            st.rerun()
    else:
        st.success("Everyone is on track right now based on current data.")


def detect_department_patterns(gs: list[dict]) -> list[dict]:
    """Detect whether issues look isolated or system-wide at the department level."""
    by_dept: dict[str, dict] = {}
    for row in gs:
        dept = row.get("Department", "") or "Unassigned"
        if dept not in by_dept:
            by_dept[dept] = {
                "department": dept,
                "total": 0,
                "below_goal": 0,
                "trending_down": 0,
                "affected_names": [],
                "employees": [],
            }
        by_dept[dept]["total"] += 1
        name = row.get("Employee Name", row.get("Employee", "Unknown"))
        by_dept[dept]["employees"].append(name)
        if row.get("goal_status") == "below_goal" or row.get("trend") == "down":
            if name not in by_dept[dept]["affected_names"]:
                by_dept[dept]["affected_names"].append(name)
        if row.get("goal_status") == "below_goal":
            by_dept[dept]["below_goal"] += 1
        if row.get("trend") == "down":
            by_dept[dept]["trending_down"] += 1

    patterns = []
    for dept, info in by_dept.items():
        affected = info["below_goal"] + info["trending_down"]
        total = info["total"] or 1
        dept_pct = round((info["below_goal"] / total) * 100)
        if info["below_goal"] >= 3 or affected >= 4 or dept_pct >= 50:
            patterns.append({
                "department": dept,
                "severity": "high",
                "type": "system",
                "below_goal": info["below_goal"],
                "trending_down": info["trending_down"],
                "total": total,
                "dept_pct": dept_pct,
                "affected_names": info["affected_names"][:6],
                "summary": f"{info['below_goal']} of {total} employees in {dept} are below target",
                "likely_cause": "Multiple employees affected — likely a process, equipment, or workload issue rather than individual performance.",
                "check_list": ["Equipment / station availability", "Workload balance or scheduling gap", "Recent process or standard change", "New hires pulling down averages"],
            })
        elif info["below_goal"] == 2 and total >= 4:
            patterns.append({
                "department": dept,
                "severity": "medium",
                "type": "mixed",
                "below_goal": info["below_goal"],
                "trending_down": info["trending_down"],
                "total": total,
                "dept_pct": dept_pct,
                "affected_names": info["affected_names"][:6],
                "summary": f"2 employees below target in {dept} — worth watching",
                "likely_cause": "May be more than one individual issue — watch for a shared root cause.",
                "check_list": ["Check if the two employees share a station or shift", "Look for any common supervisor or process change"],
            })
        elif info["below_goal"] == 1 and info["trending_down"] <= 1:
            patterns.append({
                "department": dept,
                "severity": "low",
                "type": "individual",
                "below_goal": info["below_goal"],
                "trending_down": info["trending_down"],
                "total": total,
                "dept_pct": dept_pct,
                "affected_names": info["affected_names"][:6],
                "summary": f"Issue looks isolated in {dept}",
                "likely_cause": "Likely an individual coaching opportunity — not a department-wide problem.",
                "check_list": [],
            })

    priority = {"high": 0, "medium": 1, "low": 2}
    patterns.sort(key=lambda item: priority.get(item["severity"], 99))
    return patterns


def build_operation_status(gs: list[dict]) -> dict:
    """Summarize overall operating health for leaders who want a quick answer."""
    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    trending = [r for r in gs if r.get("trend") == "down"]
    depts = sorted({r.get("Department", "") for r in gs if r.get("Department")})
    patterns = detect_department_patterns(gs)
    high_patterns = [p for p in patterns if p["severity"] == "high"]

    if high_patterns or len(below) >= 4:
        status = "At Risk"
        icon = "⚠"
    elif below or len(trending) >= 3:
        status = "Watch"
        icon = "🟡"
    else:
        status = "Stable"
        icon = "✅"

    reasons = []
    if high_patterns:
        reasons.append(high_patterns[0]["summary"])
    if below:
        reasons.append(f"{len(below)} employees below target")
    if len(trending) >= 2:
        reasons.append(f"{len(trending)} employees slipping")
    if not reasons:
        reasons.append("No major issues detected")

    top_risk_area = None
    if depts:
        dept_scores = []
        for dept in depts:
            dept_below = sum(1 for r in gs if r.get("Department") == dept and r.get("goal_status") == "below_goal")
            dept_trending = sum(1 for r in gs if r.get("Department") == dept and r.get("trend") == "down")
            dept_scores.append((dept_below + dept_trending, dept))
        top_risk_area = sorted(dept_scores, reverse=True)[0][1] if dept_scores else None

    return {
        "status": status,
        "icon": icon,
        "reasons": reasons[:3],
        "top_risk_area": top_risk_area,
    }


def show_operation_status_header(status: dict):
    """Render an operations-level status banner."""
    bg = {
        "At Risk": "linear-gradient(90deg, #FFF1EC 0%, #FFD7D0 100%)",
        "Watch": "linear-gradient(90deg, #FFF7E6 0%, #FFE6B3 100%)",
        "Stable": "linear-gradient(90deg, #ECFFF4 0%, #D8F5E5 100%)",
    }.get(status.get("status"), "#F5F7FA")
    border = {
        "At Risk": "#E76F51",
        "Watch": "#E9C46A",
        "Stable": "#4CAF50",
    }.get(status.get("status"), "#CBD5E1")

    st.markdown(
        f"<div style='background:{bg};border-left:4px solid {border};border-radius:10px;padding:14px 16px;margin:8px 0 14px;'>"
        f"<div style='font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#5A6472;'>Operation Status</div>"
        f"<div style='font-size:22px;font-weight:800;color:#16202A;margin:4px 0 6px;'>{status.get('icon')} {status.get('status')}</div>"
        f"<div style='font-size:13px;color:#334155;'>Reason: {' · '.join(status.get('reasons', []))}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if status.get("top_risk_area"):
        st.caption(f"Top risk area: {status['top_risk_area']}")


def show_pattern_detection_panel(patterns: list[dict]):
    """Show whether issues look systemic or isolated — with visual prominence."""
    high = [p for p in patterns if p["severity"] == "high"]
    medium = [p for p in patterns if p["severity"] == "medium"]
    low = [p for p in patterns if p["severity"] == "low"]

    st.markdown(
        "<div style='font-size:13px;font-weight:700;letter-spacing:.06em;"
        "text-transform:uppercase;color:#5A6472;margin:0 0 8px;'>🧩 Is This a System Issue?</div>",
        unsafe_allow_html=True,
    )

    if not patterns:
        st.markdown(
            "<div style='background:linear-gradient(90deg,#ECFFF4,#D8F5E5);border-left:4px solid #4CAF50;"
            "border-radius:8px;padding:12px 16px;'>"
            "<strong style='color:#1B5E20;'>✅ No system-wide patterns detected</strong>"
            "<div style='color:#2E7D32;font-size:13px;margin-top:4px;'>Current issues look individual — coach one-on-one.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    for pattern in high:
        _names = ", ".join(pattern.get("affected_names", []))
        _checks = "".join(
            f"<li style='margin:2px 0;'>{c}</li>" for c in pattern.get("check_list", [])
        )
        st.markdown(
            f"<div style='background:linear-gradient(90deg,#FFF1EC,#FFD7D0);border-left:5px solid #E63946;"
            f"border-radius:8px;padding:14px 16px;margin-bottom:10px;'>"
            f"<div style='font-size:15px;font-weight:800;color:#7B1F1F;'>🚨 Likely System Issue — {pattern['department']}</div>"
            f"<div style='font-size:13px;color:#4A1515;margin:6px 0;'>{pattern['summary']} ({pattern['dept_pct']}% of team)</div>"
            f"<div style='font-size:12px;color:#7B2D2D;margin-bottom:6px;'>{pattern['likely_cause']}</div>"
            f"{'<div style=\"font-size:12px;font-weight:700;color:#7B1F1F;margin-bottom:4px;\">Before coaching individuals, investigate:</div><ul style=\"margin:0;padding-left:20px;color:#4A1515;font-size:12px;\">' + _checks + '</ul>' if _checks else ''}"
            f"{'<div style=\"font-size:12px;color:#7B2D2D;margin-top:8px;\">Affected: ' + _names + '</div>' if _names else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )

    for pattern in medium:
        _names = ", ".join(pattern.get("affected_names", []))
        _checks = "".join(
            f"<li style='margin:2px 0;'>{c}</li>" for c in pattern.get("check_list", [])
        )
        st.markdown(
            f"<div style='background:linear-gradient(90deg,#FFF8E6,#FFF0C0);border-left:4px solid #F4A223;"
            f"border-radius:8px;padding:12px 16px;margin-bottom:10px;'>"
            f"<div style='font-size:14px;font-weight:700;color:#7A4500;'>⚠ Worth Watching — {pattern['department']}</div>"
            f"<div style='font-size:13px;color:#5A3300;margin:4px 0;'>{pattern['summary']}</div>"
            f"<div style='font-size:12px;color:#7A5A00;'>{pattern['likely_cause']}</div>"
            f"{'<ul style=\"margin:6px 0 0;padding-left:20px;color:#5A3300;font-size:12px;\">' + _checks + '</ul>' if _checks else ''}"
            f"{'<div style=\"font-size:12px;color:#7A4500;margin-top:6px;\">Affected: ' + _names + '</div>' if _names else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )

    if low and not high and not medium:
        for pattern in low[:3]:
            _names = ", ".join(pattern.get("affected_names", []))
            st.markdown(
                f"<div style='background:#F7F9FC;border-left:3px solid #5A7A9C;"
                f"border-radius:6px;padding:10px 14px;margin-bottom:6px;'>"
                f"<div style='font-size:13px;font-weight:700;color:#1A2D42;'>👤 Individual Issue — {pattern['department']}</div>"
                f"<div style='font-size:12px;color:#5A7A9C;margin-top:4px;'>{pattern['likely_cause']}</div>"
                f"{'<div style=\"font-size:12px;color:#5A7A9C;\">Affected: ' + _names + '</div>' if _names else ''}"
                f"</div>",
                unsafe_allow_html=True,
            )
    elif low:
        # Collapse individual isolateds when system alerts visible
        with st.expander(f"👤 {len(low)} isolated individual issue(s)", expanded=False):
            for pattern in low:
                _names = ", ".join(pattern.get("affected_names", []))
                st.caption(f"**{pattern['department']}**: {pattern['likely_cause']}")
                if _names: st.caption(f"Affected: {_names}")


def show_coaching_activity_summary(activity: dict):
    """Render recent coaching activity for supervisors and managers."""
    st.subheader("🗂 Coaching Activity")
    c1, c2, c3 = st.columns(3)
    c1.metric("Last 7 days", activity.get("notes_last_7_days", 0))
    c2.metric("People coached", activity.get("employees_coached", 0))
    c3.metric("Effectiveness", f"{activity['effectiveness_pct']}%" if activity.get("effectiveness_pct") is not None else "—")
    st.caption(
        f"Coaching effectiveness: {activity.get('effectiveness_label', '—')}"
        f" · {activity.get('improved_after_coaching', 0)} improved"
        f" · {activity.get('not_improved', 0)} still need follow-up"
    )


def show_resume_session_card(next_emp_name: str, next_context: str, next_emp_id: str):
    """Help the user continue where they left off when they return."""
    st.markdown("### Resume Session")
    st.caption(f"Pick up where you left off: next is {next_emp_name}")
    st.caption(next_context)
    if st.button("▶ Continue where I left off", key="resume_session_cta", use_container_width=True):
        st.session_state["goto_page"] = "employees"
        st.session_state["emp_view"] = "Performance Journal"
        st.session_state["cn_selected_emp"] = next_emp_id
        st.rerun()


def show_shift_complete_state(high_priority_remaining: int, medium_priority_remaining: int, coached_today: int):
    """Create a satisfying end-of-shift moment when the urgent work is done."""
    if coached_today <= 0:
        return
    if high_priority_remaining == 0:
        st.success("✔ All high-priority employees coached")
        if medium_priority_remaining > 0:
            st.caption(f"⚠ {medium_priority_remaining} medium-risk employee(s) to monitor")
        else:
            st.caption("No urgent follow-up left for this shift.")
        st.markdown("**Shift status:** Under control")


def _render_session_progress(gs: list[dict]):
    """Render a small session progress tracker for coaching momentum."""
    if not gs:
        return
    coached_today = int(st.session_state.get("_coached_today", 0))
    below_total = len([r for r in gs if r.get("goal_status") == "below_goal"])
    remaining = max(0, below_total - coached_today)

    if coached_today == 0 and below_total == 0:
        return

    done_part = f'<span class="dpd-progress-done">✔ {coached_today} coached</span>' if coached_today > 0 else ""
    left_part = (
        f'<span class="dpd-progress-left">⚠ {remaining} remaining</span>'
        if remaining > 0
        else '<span class="dpd-progress-done">✔ All coached today</span>'
    )
    sep = " &nbsp;|&nbsp; " if coached_today > 0 else ""

    st.markdown(
        f'<div class="dpd-progress-bar">Today:&nbsp;&nbsp;{done_part}{sep}{left_part}</div>',
        unsafe_allow_html=True,
    )


def _render_session_context_bar():
    """Render a persistent session context bar at the top of major pages."""
    gs = st.session_state.get("goal_status", [])
    if not gs:
        return

    coached_today = int(st.session_state.get("_coached_today", 0))
    below_total = len([r for r in gs if r.get("goal_status") == "below_goal"])
    remaining = max(0, below_total - coached_today)

    focus_dept = st.session_state.get("dash_dept_filter", ["All departments"])
    focus_dept = [d for d in focus_dept if d != "All departments"]
    focus_label = focus_dept[0] if focus_dept else "Overall"

    if coached_today == 0 and remaining == 0:
        return

    progress_text = f"✔ {coached_today} coached" if coached_today > 0 else "Starting session"
    remaining_text = f"⚠ {remaining} remaining" if remaining > 0 else "✔ All complete"
    focus_text = f"Focus: {focus_label}"

    st.markdown(
        f'<div style="background: linear-gradient(90deg, #E8F0F9 0%, #F0F7FF 100%);border-left: 4px solid #4DA3FF;padding: 12px 16px;border-radius: 6px;margin-bottom: 14px;font-size: 13px;color: #000000;">'
        f"<strong style=\"color:#000000;\">Today's Session</strong>&nbsp;&nbsp;"
        f"{progress_text} &nbsp;•&nbsp; "
        f"{remaining_text} &nbsp;•&nbsp; "
        f"{focus_text}"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_breadcrumb(current_page: str, subcontext: str | None = None):
    """Render a lightweight breadcrumb showing current location and context."""
    _page_labels = {
        "supervisor": "👔 Supervisor",
        "dashboard": "📊 Dashboard",
        "employees": "👥 Employees",
        "productivity": "📈 Productivity",
        "import": "📁 Import",
        "email": "📧 Email",
        "settings": "⚙️ Settings",
    }

    label = _page_labels.get(current_page, current_page)

    breadcrumb_html = f'<span style="font-size:12px; color:#5A7A9C;">{label}'
    if subcontext:
        breadcrumb_html += f' • <span style="color:#1A2D42; font-weight:500;">{subcontext}</span>'
    breadcrumb_html += "</span>"

    st.markdown(breadcrumb_html, unsafe_allow_html=True)


def _apply_mode_styling(mode: str):
    """Apply visual styling based on Monitor vs Plan mode."""
    mode_class = "dpd-mode-monitor" if mode == "Monitor" else "dpd-mode-plan"
    st.markdown(
        f'<style>.stApp {{ --current-mode: "{mode_class}"; }}</style>',
        unsafe_allow_html=True,
    )
    if mode == "Plan":
        st.markdown(
            """
            <style>
            html, body, .stApp,
            [data-testid="stAppViewContainer"],
            [data-testid="stAppViewContainer"] > .main,
            [data-testid="stAppViewContainer"] > .main > div,
            section.main,
            .main,
            .main .block-container {
                background: #FAFBFD !important;
            }
            [data-testid="stExpander"] { margin-bottom: 20px !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <style>
            html, body, .stApp,
            [data-testid="stAppViewContainer"],
            [data-testid="stAppViewContainer"] > .main,
            [data-testid="stAppViewContainer"] > .main > div,
            section.main,
            .main,
            .main .block-container {
                background: #F7F9FC !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )


def _render_confidence_ux(history: list[dict] | None = None, active_filters: dict | None = None):
    """Show data trust cues that answer 'Should I act on this?'"""
    last_ts = float(st.session_state.get("_archived_last_refresh_ts", 0.0) or 0.0)
    age_min = max(0, int((time.time() - last_ts) // 60)) if last_ts else None
    date_range_str = ""
    days_of_data = 0
    if history:
        dates = [
            str(row.get("Date") or row.get("work_date") or row.get("Week") or "")
            for row in history
            if row.get("Date") or row.get("work_date") or row.get("Week")
        ]
        if dates:
            date_range_str = f"based on {min(dates)} → {max(dates)}"
            days_of_data = len(set(dates))

    filter_str = ""
    if active_filters:
        parts = []
        for k, v in active_filters.items():
            if v and v != "All departments":
                parts.append(f"{k}: {v}")
        if parts:
            filter_str = f"applies to {', '.join(parts)}"

    conf_label = human_confidence_message(age_min, days_of_data, has_trend=days_of_data >= 3)

    parts = [conf_label]
    if date_range_str and days_of_data:
        parts.append(f"Based on {days_of_data} day(s) of data")
    if filter_str:
        parts.append(filter_str)

    st.caption(" · ".join(parts))
