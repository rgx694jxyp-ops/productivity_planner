"""
goals.py
--------
Department UPH goals, trend analysis, and employee flagging.

Storage: Supabase tenant_goals table only.
"""

from datetime import datetime, date
from collections import defaultdict

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


def _get_user_timezone_now() -> datetime:
    """Get current datetime in user's configured timezone.
    
    If timezone is configured in settings, returns timezone-aware datetime.
    Otherwise, returns server local time (naive datetime).
    """
    tz_str = ""
    try:
        from settings import Settings
        import streamlit as st
        tenant_id = st.session_state.get("tenant_id", "")
        settings = Settings(tenant_id)
        tz_str = settings.get("timezone", "").strip()
    except Exception:
        pass
    
    if tz_str and ZoneInfo:
        try:
            tz = ZoneInfo(tz_str)
            return datetime.now(tz)
        except Exception:
            return datetime.now()
    else:
        return datetime.now()


def _empty_goals() -> dict:
    return {"dept_targets": {}, "flagged_employees": {}}


def _normalize_goals_payload(data: dict | None) -> dict:
    data = data or {}
    dept_targets = data.get("dept_targets") or {}
    flagged_employees = data.get("flagged_employees") or {}
    if not isinstance(dept_targets, dict):
        dept_targets = {}
    if not isinstance(flagged_employees, dict):
        flagged_employees = {}
    return {
        "dept_targets": dict(dept_targets),
        "flagged_employees": dict(flagged_employees),
    }


# ── Goal store (DB only) ─────────────────────────────────────────────────────

def load_goals(tenant_id: str = "") -> dict:
    """Load goals from tenant_goals only."""
    try:
        from database import load_goals_db
        return _normalize_goals_payload(load_goals_db(tenant_id))
    except Exception:
        return _empty_goals()


def save_goals(data: dict, tenant_id: str = ""):
    """Save goals to tenant_goals only."""
    payload = _normalize_goals_payload(data)
    try:
        from database import save_goals_db
        save_goals_db(payload, tenant_id)
    except Exception:
        pass
    try:
        from cache import bust_cache as _bust_cache
        _bust_cache()
    except Exception:
        pass


def set_dept_target(dept: str, target_uph: float):
    data = load_goals()
    data["dept_targets"][dept] = target_uph
    save_goals(data)


def get_dept_target(dept: str) -> float:
    data = load_goals()
    return float(data["dept_targets"].get(dept, 0) or 0)


def get_all_targets() -> dict[str, float]:
    return dict(load_goals().get("dept_targets", {}))


# ── Employee flagging ──��───────────────────────────���──────────────────────────

def flag_employee(emp_id: str, emp_name: str, dept: str, reason: str = "",
                  flag_type: str = "followup"):
    """Flag an employee for performance tracking and log to coaching notes.

    flag_type: "followup" (🚩 Follow-up) | "performance" (⚠️ Performance Issue)
    Idempotent — re-flagging updates the type and reason.
    """
    data = load_goals()
    already_active = (emp_id in data["flagged_employees"]
                      and data["flagged_employees"][emp_id].get("active"))
    if emp_id not in data["flagged_employees"]:
        data["flagged_employees"][emp_id] = {
            "name":         emp_name,
            "dept":         dept,
            "flagged_on":   _get_user_timezone_now().strftime("%Y-%m-%d"),
            "reason":       reason,
            "flag_type":    flag_type,
            "notes":        [],
            "context_tags": [],
            "active":       True,
        }
    else:
        data["flagged_employees"][emp_id]["active"]    = True
        data["flagged_employees"][emp_id]["flag_type"] = flag_type
        if reason:
            data["flagged_employees"][emp_id]["reason"] = reason
        if "context_tags" not in data["flagged_employees"][emp_id]:
            data["flagged_employees"][emp_id]["context_tags"] = []
    save_goals(data)
    # Auto-log to coaching notes so the flag always appears in the coaching tab
    if not already_active:
        try:
            from database import add_coaching_note
            note = (f"Flagged ({flag_type}). Reason: {reason}"
                    if reason.strip() else f"Flagged for follow-up ({flag_type}).")
            add_coaching_note(emp_id, note, created_by="System")
        except Exception:
            pass   # non-critical — flag is still saved


def unflag_employee(emp_id: str):
    data = load_goals()
    if emp_id in data["flagged_employees"]:
        data["flagged_employees"][emp_id]["active"] = False
        save_goals(data)


def add_note(emp_id: str, note_text: str):
    """Append a timestamped note to a flagged employee's record."""
    data = load_goals()
    if emp_id not in data["flagged_employees"]:
        return
    data["flagged_employees"][emp_id]["notes"].append({
        "date": _get_user_timezone_now().strftime("%Y-%m-%d %H:%M"),
        "text": note_text.strip(),
    })
    save_goals(data)


def get_flagged_employees() -> dict:
    return load_goals().get("flagged_employees", {})


def get_active_flags() -> dict:
    return {k: v for k, v in get_flagged_employees().items() if v.get("active")}


# ── Trend analysis ───��────────────────────────────────────────────────────────

def analyse_trends(
    history:    list[dict],
    mapping:    dict[str, str],
    weeks:      int = 4,
) -> dict[str, dict]:
    """
    For each employee, calculate their UPH trend over the last N weeks.

    Returns:
        {
            emp_id: {
                "name":      str,
                "dept":      str,
                "direction": "up" | "down" | "flat" | "insufficient_data",
                "weeks":     [{"week": "W12", "avg_uph": 14.2}, ...],
                "change_pct": float,   # % change from first to last week
            }
        }
    """
    id_col   = mapping.get("EmployeeID")   or "EmployeeID"
    name_col = mapping.get("EmployeeName") or "EmployeeName"
    dept_col = mapping.get("Department")   or "Department"
    uph_col  = mapping.get("UPH")          or "UPH"

    # Group UPH values by (emp_id, week)
    weekly: dict[tuple, list[float]] = defaultdict(list)
    emp_meta: dict[str, dict] = {}

    for row in history:
        emp_id = str(row.get(id_col) or "").strip()
        week   = str(row.get("Week") or "").strip()
        if not emp_id or not week:
            continue

        try:
            uph = float(row.get(uph_col) or row.get("UPH") or "")
        except (ValueError, TypeError):
            continue

        weekly[(emp_id, week)].append(uph)

        if emp_id not in emp_meta:
            emp_meta[emp_id] = {
                "name": str(row.get(name_col) or "").strip(),
                "dept": str(row.get(dept_col) or "").strip(),
            }

    # Find the N most recent weeks across all data
    all_weeks = sorted(
        {w for _, w in weekly.keys()},
        key=lambda w: int(w.lstrip("Ww")) if w.lstrip("Ww").isdigit() else 0,
    )
    recent_weeks = all_weeks[-weeks:] if len(all_weeks) >= weeks else all_weeks

    results = {}
    for emp_id, meta in emp_meta.items():
        week_avgs = []
        for w in recent_weeks:
            vals = weekly.get((emp_id, w), [])
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

        results[emp_id] = {
            "name":       meta["name"],
            "dept":       meta["dept"],
            "direction":  direction,
            "weeks":      week_avgs,
            "change_pct": change_pct,
        }

    return results


def build_goal_status(
    ranked:       list[dict],
    dept_targets: dict[str, float],
    trend_data:   dict[str, dict],
) -> list[dict]:
    """
    Combine ranked employees with their goal status and trend.

    Returns each employee row enriched with:
        goal_status:  "on_goal" | "below_goal" | "no_goal"
        trend:        "up" | "down" | "flat" | "insufficient_data"
        change_pct:   float
        flagged:      bool
    """
    active_flags = get_active_flags()
    results      = []

    for emp in ranked:
        dept        = emp.get("Department", "")
        avg_uph     = float(emp.get("Average UPH", 0) or 0)
        target      = float(dept_targets.get(dept, 0) or 0)
        emp_id      = str(emp.get("EmployeeID", emp.get("Employee Name", "")))
        trend_info  = trend_data.get(emp_id, {})

        if target > 0:
            goal_status = "on_goal" if avg_uph >= target else "below_goal"
        else:
            goal_status = "no_goal"

        results.append({
            **emp,
            "Target UPH":  target if target > 0 else "—",
            "vs Target":   f"+{avg_uph - target:.1f}" if target > 0 and avg_uph >= target
                           else (f"{avg_uph - target:.1f}" if target > 0 else "—"),
            "goal_status": goal_status,
            "trend":       trend_info.get("direction", "insufficient_data"),
            "change_pct":  trend_info.get("change_pct", 0.0),
            "flagged":     emp_id in active_flags,
        })

    return results
