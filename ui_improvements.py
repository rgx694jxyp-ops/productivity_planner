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
    
    for file_info in pending_files:
        rows = file_info.get("rows", [])
        total_rows += len(rows)
        all_rows.extend(rows)
        
        for row in rows:
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
            if hours and float(hours or 0) > 0:
                hours_count += 1
    
    # Build diagnosis
    warnings = []
    
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
            before_uph = sum(float(h.get("uph", 0)) for h in before_rows) / len(before_rows)
        
        # Calculate avg UPH after (7 days post)
        after_date_end = coached_date + timedelta(days=7)
        after_rows = [h for h in history 
                     if str(h.get("emp_id")) == str(emp_id)
                     and coached_date < datetime.fromisoformat(h.get("work_date", "")).date() <= after_date_end]
        if after_rows:
            after_uph = sum(float(h.get("uph", 0)) for h in after_rows) / len(after_rows)
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
    Display coaching impact in human-friendly language.
    """
    if not impact:
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.caption(f"**Coaching:** {impact['coached_date'].strftime('%b %d')} ({impact['days_since']}d ago)")
        st.caption(f"*{impact['note']}*")
    
    with col2:
        if impact["improvement"]:
            st.success(f"↑ +{impact['change_uph']} UPH improvement")
            st.caption(f"{impact['before_uph']} → {impact['after_uph']}")
        else:
            st.warning(f"↓ {impact['change_uph']} UPH (pattern may need adjustment)")
            st.caption(f"{impact['before_uph']} → {impact['after_uph']}")


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
