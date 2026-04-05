"""
UI Improvements Module
Adds support for:
- Auto-diagnosis after upload
- Manual data entry
- Simple Mode
- Coaching impact tracking
- Human confidence messaging
"""

import streamlit as st
from datetime import datetime, date, timedelta
import pandas as pd
import time


def _safe_float(value, default=0.0):
    """Parse numeric-like values safely; return default for invalid inputs."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ════════════════════════════════════════════════════════════════════════════════
# 1. AUTO-DIAGNOSIS (After CSV Upload)
# ════════════════════════════════════════════════════════════════════════════════

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
            if hours and _safe_float(hours, 0.0) > 0:
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


# ════════════════════════════════════════════════════════════════════════════════
# 2. MANUAL DATA ENTRY (No CSV required)
# ════════════════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════════════════
# 3. COACHING IMPACT TRACKING
# ════════════════════════════════════════════════════════════════════════════════

def find_coaching_impact(emp_id: str, coaching_notes: list[dict], 
                         history: list[dict]) -> dict | None:
    """
    Find the coaching event + subsequent performance change.
    Returns: {
        "coached_date": date,
        "note": str,
        "before_uph": float,
        "after_uph": float,
        "change_uph": float,
        "improvement": bool,
        "days_since": int
    }
    or None if no coaching found
    """
    # Find last coaching note for this employee
    emp_notes = [n for n in coaching_notes if str(n.get("emp_id")) == str(emp_id)]
    if not emp_notes:
        return None
    
    last_note = sorted(emp_notes, key=lambda x: x.get("created_at", ""), reverse=True)[0]
    coached_date_str = last_note.get("created_at", "")
    note_text = last_note.get("note", "")
    
    try:
        coached_date = datetime.fromisoformat(coached_date_str).date()
    except:
        return None
    
    # Get UPH before coaching (7 days prior avg)
    before_date_start = coached_date - timedelta(days=7)
    before_uph = None
    after_uph = None
    
    try:
        # Calculate avg UPH before
        before_rows = [h for h in history 
                      if str(h.get("emp_id")) == str(emp_id)
                      and before_date_start <= datetime.fromisoformat(h.get("work_date", "")).date() < coached_date]
        if before_rows:
            before_uph = sum(_safe_float(h.get("uph", 0), 0.0) for h in before_rows) / len(before_rows)
        
        # Calculate avg UPH after (7 days post)
        after_date_end = coached_date + timedelta(days=7)
        after_rows = [h for h in history 
                     if str(h.get("emp_id")) == str(emp_id)
                     and coached_date < datetime.fromisoformat(h.get("work_date", "")).date() <= after_date_end]
        if after_rows:
            after_uph = sum(_safe_float(h.get("uph", 0), 0.0) for h in after_rows) / len(after_rows)
    except:
        pass
    
    if before_uph is None or after_uph is None:
        return None
    
    change = after_uph - before_uph
    days_since = (date.today() - coached_date).days
    
    return {
        "coached_date": coached_date,
        "note": note_text[:50] + ("..." if len(note_text) > 50 else ""),
        "before_uph": round(before_uph, 1),
        "after_uph": round(after_uph, 1),
        "change_uph": round(change, 1),
        "improvement": change > 0,
        "days_since": days_since,
    }


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


# ════════════════════════════════════════════════════════════════════════════════
# 4. SIMPLE MODE UX
# ════════════════════════════════════════════════════════════════════════════════

def is_simple_mode() -> bool:
    """Check if user has Simple Mode enabled."""
    return st.session_state.get("simple_mode", False)


def toggle_simple_mode():
    """Add toggle to sidebar."""
    if st.sidebar.checkbox("🎯 Simple Mode", value=st.session_state.get("simple_mode", False), key="toggle_simple"):
        st.session_state["simple_mode"] = True
    else:
        st.session_state["simple_mode"] = False


def simplified_supervisor_view(gs: list[dict]):
    """
    Stripped-down supervisor view for Simple Mode.
    Just shows: who needs attention, in plain language, with one action button.
    """
    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    
    if not below:
        st.success("✅ Everyone's on track today")
        return
    
    st.markdown("### 👥 People who need attention")
    
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
        
        if col2.button("Coach", key=f"simple_coach_{emp.get('EmployeeID')}", 
                      help="Start coaching conversation"):
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
        st.caption("Start with the people below target first, then follow up on anyone whose performance is slipping.")
        if st.button("▶ Start coaching", key="start_shift_cta", type="primary", use_container_width=True):
            top_emp = below[0]
            st.session_state["goto_page"] = "employees"
            st.session_state["emp_view"] = "Performance Journal"
            st.session_state["cn_selected_emp"] = str(top_emp.get("EmployeeID", top_emp.get("Employee Name", "")))
            st.rerun()
    else:
        st.success("Everyone is on track right now. Use this shift to follow up and reinforce wins.")


def detect_department_patterns(gs: list[dict]) -> list[dict]:
    """Detect whether issues look isolated or system-wide at the department level."""
    by_dept: dict[str, dict] = {}
    for row in gs:
        dept = row.get("Department", "") or "Unassigned"
        if dept not in by_dept:
            by_dept[dept] = {
                "department": dept,
                "below_goal": 0,
                "trending_down": 0,
                "employees": [],
            }
        if row.get("goal_status") == "below_goal":
            by_dept[dept]["below_goal"] += 1
        if row.get("trend") == "down":
            by_dept[dept]["trending_down"] += 1
        by_dept[dept]["employees"].append(
            row.get("Employee Name", row.get("Employee", "Unknown"))
        )

    patterns = []
    for dept, info in by_dept.items():
        affected = info["below_goal"] + info["trending_down"]
        if info["below_goal"] >= 3 or affected >= 4:
            patterns.append({
                "department": dept,
                "severity": "high",
                "type": "system",
                "summary": f"{max(info['below_goal'], info['trending_down'])} employees in {dept} need attention",
                "likely_cause": "Process or workload issue likely — not isolated to one person.",
            })
        elif info["below_goal"] == 1 and info["trending_down"] <= 1:
            patterns.append({
                "department": dept,
                "severity": "low",
                "type": "individual",
                "summary": f"Issue looks isolated in {dept}",
                "likely_cause": "More likely an individual coaching issue than a department-wide problem.",
            })

    priority = {"high": 0, "low": 1}
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
    """Show whether issues look systemic or isolated."""
    if not patterns:
        st.success("No clear department-wide patterns detected. Current issues look mostly isolated.")
        return

    st.subheader("🧩 Pattern Detection")
    for pattern in patterns[:4]:
        label = "⚠ System pattern" if pattern["type"] == "system" else "👤 Isolated issue"
        st.markdown(f"**{label}: {pattern['department']}**")
        st.caption(pattern["summary"])
        st.caption(f"Likely cause: {pattern['likely_cause']}")


def summarize_coaching_activity(notes_by_emp: dict[str, list[dict]], history: list[dict]) -> dict:
    """Summarize coaching activity and early effectiveness."""
    seven_days_ago = date.today() - timedelta(days=7)
    note_count = 0
    coached_employees = 0
    impacts = []

    for emp_id, notes in notes_by_emp.items():
        if not notes:
            continue
        recent_notes = []
        for note in notes:
            created = str(note.get("created_at", ""))
            try:
                created_date = datetime.fromisoformat(created).date()
            except Exception:
                continue
            if created_date >= seven_days_ago:
                recent_notes.append(note)
        if recent_notes:
            note_count += len(recent_notes)
            coached_employees += 1
            impact = find_coaching_impact(emp_id, recent_notes, history)
            if impact:
                impacts.append(impact)

    improved = sum(1 for impact in impacts if impact.get("improvement"))
    unchanged_or_down = max(0, len(impacts) - improved)
    effectiveness = round((improved / len(impacts)) * 100) if impacts else None

    return {
        "notes_last_7_days": note_count,
        "employees_coached": coached_employees,
        "improved_after_coaching": improved,
        "not_improved": unchanged_or_down,
        "effectiveness_pct": effectiveness,
        "effectiveness_label": (
            "High" if effectiveness is not None and effectiveness >= 70 else
            "Moderate" if effectiveness is not None and effectiveness >= 40 else
            "Developing" if effectiveness is not None else
            "Not enough follow-up data"
        ),
    }


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


# ════════════════════════════════════════════════════════════════════════════════
# 5. HUMAN CONFIDENCE MESSAGING
# ════════════════════════════════════════════════════════════════════════════════

def human_confidence_message(data_age_minutes: int | None, 
                            days_of_data: int,
                            has_trend: bool = False) -> str:
    """
    Convert technical uncertainty into human-friendly guidance.
    """
    if data_age_minutes is None or days_of_data == 0:
        return "Limited data — still enough to guide decisions. Upload more data for stronger patterns."
    
    if data_age_minutes <= 5 and days_of_data >= 7 and has_trend:
        return f"✓ Fresh data with good history — safe to act immediately. (Updated {data_age_minutes}m ago)"
    
    if data_age_minutes <= 60 and days_of_data >= 7:
        return f"✓ Solid data — good basis for decisions. (Updated {data_age_minutes}m ago)"
    
    if data_age_minutes <= 240 and days_of_data >= 3:
        return f"⚠ Reasonable data — validate before major decisions. (Updated {data_age_minutes}m ago)"
    
    if days_of_data < 3:
        return f"Limited history — use as a starting point. Add more days for trend patterns."
    
    if data_age_minutes > 1440:  # > 1 day
        return "Data is getting stale. Refresh to see latest patterns."
    
    return "Data looks good — trends are reliable."


# ════════════════════════════════════════════════════════════════════════════════
# 6. FLOOR LANGUAGE TRANSLATIONS
# ════════════════════════════════════════════════════════════════════════════════

def translate_to_floor_language(technical_term: str, context: dict | None = None) -> str:
    """
    Convert technical jargon to supervisor-friendly language.
    """
    translations = {
        "trend declining": "Performance dropping — 3 days in a row",
        "variance high": "Output is inconsistent day to day",
        "risk score: 7": "Needs attention soon",
        "goal_status": "Performance vs target",
        "below_goal": "Below their target",
        "on_goal": "Meeting their target",
        "streak": "Days in a row below target",
        "change_pct": "Performance change",
        "rolling average": "Average over last week",
    }
    
    return translations.get(technical_term.lower(), technical_term)


def risk_to_human_language(risk_level: str, context: dict | None = None) -> str:
    """
    Convert risk color codes to actionable language.
    """
    if "🔴" in str(risk_level) or "High" in str(risk_level):
        return "Needs coaching ⏰ — performance is well below target"
    elif "🟡" in str(risk_level) or "Medium" in str(risk_level):
        return "Check in soon 💬 — starting to slide or inconsistent"
    elif "🟢" in str(risk_level) or "Low" in str(risk_level):
        return "Doing well ✓ — on track"
    return "Needs attention"


def _compute_priority_summary(gs: list[dict], history: list[dict]) -> dict:
    """Return lightweight action-oriented summary counts for header strips."""
    from app import _get_all_risk_levels

    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    risk_cache = _get_all_risk_levels(gs, history)
    critical = 0
    quick_wins = 0
    for row in below:
        emp_id = str(row.get("EmployeeID", row.get("Employee Name", "")))
        risk_level, _, _ = risk_cache.get(emp_id, ("🟢 Low", 0, {}))
        trend = row.get("trend", "")
        try:
            avg_uph = float(row.get("Average UPH", 0) or 0)
            target = float(row.get("Target UPH", 0) or 0)
        except Exception:
            avg_uph, target = 0.0, 0.0

        if risk_level.startswith("🔴") and trend == "down":
            critical += 1

        if target > 0 and avg_uph >= (target * 0.95) and trend in ("up", "flat"):
            quick_wins += 1

    return {
        "below": len(below),
        "critical": critical,
        "quick_wins": quick_wins,
    }


def _render_priority_strip(gs: list[dict], history: list[dict]):
    """Top-of-page action strip that answers 'what should I do right now?'"""
    p = _compute_priority_summary(gs, history)
    c1, c2, c3 = st.columns(3)
    c1.metric("⚠️ Below Goal", p["below"])
    c2.metric("🔥 Critical Risk", p["critical"])
    c3.metric("📈 Quick Wins", p["quick_wins"])

    a1, a2 = st.columns(2)
    if a1.button("View Priority List", use_container_width=True, key="pri_strip_priority"):
        st.session_state["goto_page"] = "productivity"
        st.session_state["prod_view"] = "📋 Priority List"
        st.rerun()
    if a2.button("Start Coaching", use_container_width=True, key="pri_strip_coaching"):
        st.session_state["goto_page"] = "employees"
        st.session_state["emp_view"] = "Performance Journal"
        st.rerun()


def _get_primary_recommendation(gs: list[dict], history: list[dict]) -> dict | None:
    """Pick one highest-impact coaching action with a rich 'why this person' justification."""
    from app import _get_all_risk_levels

    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    if not below:
        return None

    risk_cache = _get_all_risk_levels(gs, history)
    candidates = []
    for row in below:
        emp_id = str(row.get("EmployeeID", row.get("Employee Name", "")))
        risk_level, risk_score, risk_details = risk_cache.get(emp_id, ("🟢 Low", 0, {}))
        trend = row.get("trend", "")
        name = row.get("Employee", row.get("Employee Name", "Unknown"))
        name = str(name) if name is not None else "Unknown"
        dept = str(row.get("Department", "") or "")

        try:
            change_pct = float(row.get("change_pct", 0) or 0)
        except Exception:
            change_pct = 0.0
        try:
            avg_uph = float(row.get("Average UPH", 0) or 0)
            target = float(row.get("Target UPH", 0) or 0)
        except Exception:
            avg_uph, target = 0.0, 0.0

        why_parts = []
        if trend == "down":
            streak = risk_details.get("under_goal_streak", 0)
            if streak >= 2:
                why_parts.append(f"↓ {streak}-day downward streak")
            else:
                why_parts.append(f"↓ trending down {change_pct:+.0f}%")
        if target > 0 and avg_uph > 0:
            gap = target - avg_uph
            if gap > 0:
                why_parts.append(f"{gap:.1f} UPH below target")
        if risk_level.startswith("🔴"):
            why_parts.append("high risk score")
        if not why_parts:
            why_parts.append("below goal")

        candidates.append(
            {
                "name": name,
                "emp_id": emp_id,
                "department": dept,
                "risk_level": risk_level,
                "risk_score": float(risk_score),
                "why": " · ".join(why_parts),
                "avg_uph": avg_uph,
                "target": target,
            }
        )

    if not candidates:
        return None

    candidates.sort(key=lambda x: x["risk_score"], reverse=True)
    return candidates[0]


def _render_adaptive_action_suggestion(gs: list[dict], history: list[dict], last_coached_emp_id: str | None = None):
    """
    Adaptive recommendation rail logic.
    Evolves from "here's the next person" to context-aware suggestions based on:
    - What just happened (coached, noted, set reminder)
    - Department patterns (multiple failures in same dept?)
    - Time of day (early session = coach more, late = document trends?)
    - Session momentum (how many coached today?)
    """
    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    if not below:
        return None

    last_emp = None
    if last_coached_emp_id:
        last_emp = next((r for r in gs if str(r.get("EmployeeID", "")) == str(last_coached_emp_id)), None)

    rec = _get_primary_recommendation(gs, history)
    if not rec:
        return None

    rec_dept = rec.get("department", "")
    dept_below = [r for r in below if r.get("Department") == rec_dept]
    has_dept_pattern = len(dept_below) >= 2

    same_dept_coaching = False
    if last_emp:
        last_dept = last_emp.get("Department", "")
        same_dept_coaching = (last_dept == rec_dept) and last_emp != rec

    coached_today = int(st.session_state.get("_coached_today", 0))
    momentum_level = "building" if coached_today >= 2 else "starting" if coached_today == 1 else "fresh"

    try:
        if rec.get("risk_score", 0) >= 7:
            rec_below_pct = "critical"
        elif rec.get("risk_score", 0) >= 4:
            rec_below_pct = "high"
        else:
            rec_below_pct = "moderate"
    except Exception:
        rec_below_pct = "moderate"

    if has_dept_pattern and len(dept_below) > 2:
        return {
            "name": rec["name"],
            "emp_id": rec["emp_id"],
            "context": f"🚨 DEPT TREND: {len(dept_below)} employees below goal in {rec_dept}",
            "action": "Coach → Document Pattern",
            "emphasis": "This is a team-level issue, not just individual. After coaching, consider team-wide actions.",
            "priority": "critical",
        }

    if same_dept_coaching:
        return {
            "name": rec["name"],
            "emp_id": rec["emp_id"],
            "context": f"↪️ MOMENTUM: Same dept as {last_emp.get('Employee Name', 'last employee')} · Related issues likely",
            "action": "Continue Coaching",
            "emphasis": f"You found patterns in {rec_dept}. Keep the momentum going.",
            "priority": "high",
        }

    if coached_today >= 1 and momentum_level == "building":
        return {
            "name": rec["name"],
            "emp_id": rec["emp_id"],
            "context": f"✓ Momentum: {coached_today} coached · {len(below)} remaining",
            "action": "Keep Coaching",
            "emphasis": f"Great start! {rec_below_pct.upper()} risk · this won't take long.",
            "priority": "high",
        }

    return {
        "name": rec["name"],
        "emp_id": rec["emp_id"],
        "context": rec.get("why", "Highest risk today"),
        "action": "Start/Continue Coaching",
        "emphasis": f"{rec_below_pct.capitalize()} risk · {len(below)} employees below goal total.",
        "priority": rec_below_pct,
    }


def _render_primary_action_rail(gs: list[dict], history: list[dict], key_prefix: str):
    """Dominant command-bar panel — visually anchors every key page with one clear action."""
    rec = _get_primary_recommendation(gs, history)
    remaining = [r for r in gs if r.get("goal_status") == "below_goal"]

    if not rec:
        st.markdown(
            '<div class="dpd-rail">'
            '<div class="dpd-rail-label">▶ Recommended Action</div>'
            '<div class="dpd-rail-ok">✓ All employees on track — no action needed</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    last_coached_id = st.session_state.get("_last_coached_emp_id", None)
    adaptive = _render_adaptive_action_suggestion(gs, history, last_coached_id)

    import html as _h

    _name_raw = adaptive["name"] if adaptive else rec.get("name", "")
    _dept_raw = rec.get("department", "")
    _context_raw = adaptive["context"] if adaptive and "context" in adaptive else rec.get("why", "")
    _name = _h.escape(str(_name_raw) if _name_raw is not None else "")
    _dept = _h.escape(str(_dept_raw) if _dept_raw is not None else "")
    _context = _h.escape(str(_context_raw) if _context_raw is not None else "")
    _dept_str = f" · {_dept}" if _dept else ""
    _n_remaining = len(remaining)

    rail_style = "color: #FFFFFF;"
    if adaptive and adaptive.get("priority") == "critical":
        rail_style = "background: linear-gradient(90deg, #8B0000 0%, #DC143C 100%); color: #FFFFFF;"
    elif adaptive and adaptive.get("priority") == "high":
        rail_style = "background: linear-gradient(90deg, #FF6347 0%, #FF7F50 100%); color: #FFFFFF;"

    _remaining_note = (
        f"<div class='dpd-rail-label' style='color:#FFFFFF !important;'>⬇ {_n_remaining - 1} more below goal</div>"
        if _n_remaining > 1
        else ""
    )

    st.markdown(
        f'<div class="dpd-rail" style="{rail_style}">'
        f'<div class="dpd-rail-label" style="color:#FFFFFF !important;">▶ Recommended Action</div>'
        f'<div class="dpd-rail-name">{_name}{_dept_str}</div>'
        f'<div class="dpd-rail-why">{_context}</div>'
        f"{_remaining_note}"
        "</div>",
        unsafe_allow_html=True,
    )

    if adaptive and "emphasis" in adaptive:
        st.caption(f"💡 {adaptive['emphasis']}")

    col1, col2 = st.columns(2)
    action_label = adaptive.get("action", "Start Coaching") if adaptive else "Start Coaching"
    if col1.button(f"▶ {action_label}", key=f"{key_prefix}_start_coach", type="primary", use_container_width=True):
        st.session_state["goto_page"] = "employees"
        st.session_state["emp_view"] = "Performance Journal"
        st.session_state["cn_selected_emp"] = rec["emp_id"]
        st.rerun()
    if col2.button("View Context →", key=f"{key_prefix}_view_context", use_container_width=True):
        st.session_state["goto_page"] = "dashboard"
        st.rerun()
    if _n_remaining > 1:
        st.caption(f"{_n_remaining} employee(s) below goal · sorted by highest risk")


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


def _apply_mode_styling(mode: str):
    """Apply visual styling based on Monitor vs Plan mode."""
    mode_class = "dpd-mode-monitor" if mode == "Monitor" else "dpd-mode-plan"
    st.markdown(
        f'<style>.stApp {{ --current-mode: "{mode_class}"; }}</style>',
        unsafe_allow_html=True,
    )
    if mode == "Plan":
        st.markdown(
            "<style>.stApp { background: #FAFBFD !important; }[data-testid=\"stExpander\"] { margin-bottom: 20px !important; }</style>",
            unsafe_allow_html=True,
        )


def _render_soft_action_buttons(emp_id: str, emp_name: str, risk_level: str, context_tags: list[str] | None = None):
    """Render soft action buttons for medium-risk employees."""
    if not risk_level.startswith("🟡"):
        return

    st.markdown("**💡 Quick Actions — No coaching needed**")

    col1, col2, col3 = st.columns(3)

    if col1.button(
        "⏰ Schedule Check-In",
        key=f"soft_checkin_{emp_id}",
        help="Brief conversation to prevent decline (not formal coaching)",
        use_container_width=True,
    ):
        from database import add_coaching_note

        add_coaching_note(
            emp_id,
            "[SCHEDULED] Brief check-in queued — quick conversation to identify trends before they worsen.",
            "System",
        )
        st.success(f"✓ Check-in scheduled for {emp_name}")
        st.rerun()

    if col2.button(
        "📝 Add Note",
        key=f"soft_note_{emp_id}",
        help="Log observation without full coaching",
        use_container_width=True,
    ):
        st.session_state["soft_note_emp_id"] = emp_id
        st.session_state["show_soft_note_input"] = True

    if col3.button(
        "▶ Full Coaching",
        key=f"soft_escalate_{emp_id}",
        help="Move to formal coaching session",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state["goto_page"] = "employees"
        st.session_state["emp_view"] = "Performance Journal"
        st.session_state["cn_selected_emp"] = emp_id
        st.rerun()

    st.caption("📌 **Add context** if applicable:")
    context_tags = context_tags or []

    CONTEXT_OPTIONS = ["Equipment issues", "New employee", "Cross-training", "Shift change", "Short staffed"]

    c1, c2, c3 = st.columns(3)
    cols = [c1, c2, c3]

    for i, ctx_opt in enumerate(CONTEXT_OPTIONS[:3]):
        col_idx = i % 3
        is_selected = ctx_opt in context_tags
        if cols[col_idx].button(
            f"{'✓' if is_selected else '○'} {ctx_opt}",
            key=f"soft_ctx_{emp_id}_{ctx_opt}",
            use_container_width=True,
            type="secondary" if is_selected else "primary",
        ):
            if ctx_opt in context_tags:
                context_tags.remove(ctx_opt)
            else:
                context_tags.append(ctx_opt)

            try:
                from goals import get_active_flags, save_goals

                flags = get_active_flags()
                if emp_id in flags:
                    flags[emp_id]["context_tags"] = context_tags
                    save_goals(flags)
            except Exception:
                pass
            st.rerun()


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


def _enhance_coaching_feedback(emp_name: str, emp_id: str, remaining_below_goal: int):
    """Enhanced feedback after coaching save."""
    coached_today = int(st.session_state.get("_coached_today", 1))

    st.success("✔ Coaching logged and saved")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Coached Today", coached_today)
    with col2:
        st.metric("Remaining", remaining_below_goal)

    if remaining_below_goal > 0:
        if coached_today == 1:
            momentum_msg = (
                f"You're off to a great start — <strong>{remaining_below_goal} more</strong> "
                f"{'employee' if remaining_below_goal == 1 else 'employees'} to help."
            )
        elif coached_today % 5 == 0:
            momentum_msg = f"🔥 {coached_today} coached today! <strong>{remaining_below_goal}</strong> remaining."
        else:
            momentum_msg = (
                f"You're on a roll — <strong>{remaining_below_goal}</strong> "
                f"{'employee' if remaining_below_goal == 1 else 'employees'} left."
            )

        st.markdown(
            f'<div style="background: linear-gradient(90deg, #E3F2FD 0%, #E8F0F9 100%);border-radius: 8px;padding: 14px 16px;margin: 12px 0;font-size: 14px;border-left: 4px solid #4DA3FF;border-top: 1px solid #B3D8FF;">{momentum_msg}</div>',
            unsafe_allow_html=True,
        )

        col_continue, col_return = st.columns(2)
        if col_continue.button("⬇️ Continue Coaching →", key="continue_auto", type="primary", use_container_width=True):
            st.rerun()
        if col_return.button("↩️ Back to Dashboard", key="back_to_dash", use_container_width=True):
            st.session_state["goto_page"] = "dashboard"
            st.rerun()
    else:
        st.markdown(
            '<div style="background: linear-gradient(90deg, #E8F5E9 0%, #F1F8E9 100%);border-radius: 8px;padding: 14px 16px;margin: 12px 0;font-size: 14px;border-left: 4px solid #6FE090;border-top: 1px solid #AED581;">🏆 <strong>All high-risk employees coached today!</strong> Your team is in great shape.</div>',
            unsafe_allow_html=True,
        )
