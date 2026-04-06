"""Coaching service — coaching impact tracking, effectiveness analysis, and recommendations."""

import streamlit as st
from datetime import datetime, date, timedelta
from utils.floor_language import _safe_float


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


def _get_primary_recommendation(gs: list[dict], history: list[dict]) -> dict | None:
    """Pick one highest-impact coaching action with a rich 'why this person' justification."""
    below = [r for r in gs if r.get("goal_status") == "below_goal"]
    if not below:
        return None

    from domain.risk import _get_all_risk_levels
    
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
