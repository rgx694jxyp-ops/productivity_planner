"""Recommendation service — picks next action based on context."""

from datetime import datetime, date
from services.coaching_service import _get_primary_recommendation


def _render_adaptive_action_suggestion(
    gs: list[dict],
    history: list[dict],
    last_coached_emp_id: str | None = None,
    coached_today: int = 0,
):
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

    coached_today = int(coached_today or 0)
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
