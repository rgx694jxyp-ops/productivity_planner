"""
services/cost_service.py
------------------------
Pure calculations for the Cost Impact page.
All DB access and UPH math lives here so the page only handles display.
"""

_DEFAULT_WAGE = 18.0
_WEEKS_IN_YEAR = 52


def weekly_cost_impact(
    current_uph: float,
    target_uph: float,
    hours_per_week: float,
    hourly_wage: float,
) -> dict:
    """
    Return cost/recovery metrics for one employee.

    Keys:
      lost_uph_gap            — UPH shortfall vs target
      lost_units_per_week     — units not produced per week
      lost_labor_cost_per_week — $ of labour wasted (extra hours needed to match target at current rate)
      recovery_per_week       — same amount, framed as "recoverable value"
      additional_units_per_day
    """
    if target_uph <= 0 or current_uph <= 0:
        return {
            "lost_uph_gap": 0.0,
            "lost_units_per_week": 0.0,
            "lost_labor_cost_per_week": 0.0,
            "recovery_per_week": 0.0,
            "additional_units_per_day": 0.0,
        }

    gap_uph = max(target_uph - current_uph, 0.0)
    lost_units_pw = gap_uph * hours_per_week
    extra_hours_pw = (lost_units_pw / current_uph) if current_uph > 0 else 0.0
    lost_cost_pw = extra_hours_pw * hourly_wage

    return {
        "lost_uph_gap": round(gap_uph, 2),
        "lost_units_per_week": round(lost_units_pw, 0),
        "lost_labor_cost_per_week": round(lost_cost_pw, 2),
        "recovery_per_week": round(lost_cost_pw, 2),
        "additional_units_per_day": round(gap_uph * (hours_per_week / 5), 0),
    }


def get_wage(settings_obj) -> float:
    """Return hourly wage from a settings object, falling back to the default."""
    try:
        return float(settings_obj.get("avg_hourly_wage", _DEFAULT_WAGE) or _DEFAULT_WAGE)
    except (TypeError, ValueError):
        return _DEFAULT_WAGE


def get_coaching_gains_for_employee(
    emp_id: str,
    target_uph: float,
    hours_per_week: float,
    hourly_wage: float,
) -> tuple[float, str]:
    """
    Look up coaching notes with before/after UPH for *emp_id* and return
    (best_gain_dollars_per_week, coaching_action_label).

    Returns (0.0, "") when no useful notes are found.
    """
    try:
        from database import get_coaching_notes as _gcn
        notes = _gcn(emp_id) or []
    except Exception:
        return 0.0, ""

    best_gain = 0.0
    best_action = ""
    for note in notes:
        before = note.get("uph_before")
        after = note.get("uph_after")
        if before is None or after is None:
            continue
        try:
            delta = float(after) - float(before)
            if delta <= 0:
                continue
            imp_before = weekly_cost_impact(float(before), target_uph, hours_per_week, hourly_wage)
            imp_after = weekly_cost_impact(float(after), target_uph, hours_per_week, hourly_wage)
            gain = imp_before["lost_labor_cost_per_week"] - imp_after["lost_labor_cost_per_week"]
            if gain > best_gain:
                best_gain = round(gain, 2)
                best_action = (note.get("action_taken") or "coaching").capitalize()
        except (TypeError, ValueError):
            pass

    return best_gain, best_action
