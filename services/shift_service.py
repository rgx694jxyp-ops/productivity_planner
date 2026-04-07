"""
services/shift_service.py
--------------------------
Domain logic for Shift Plan:
  - time string ↔ float conversions
  - checkpoint generation
  - expected-output interpolation
  - historical baseline lookup
  - per-department UPH gap attribution

Nothing here imports Streamlit or touches session state.
"""

_CHECKPOINT_INTERVAL_HRS = 2
_AUTO_BASELINES_DAYS = 30


def time_to_float(t: str) -> float:
    """Convert 'HH:MM' string to fractional hours.  '14:30' → 14.5"""
    try:
        h, m = t.split(":")
        return int(h) + int(m) / 60
    except Exception:
        return 8.0


def float_to_time(f: float) -> str:
    """Convert fractional hours to 'HH:MM'.  14.5 → '14:30'"""
    h = int(f)
    m = int(round((f - h) * 60))
    return f"{h:02d}:{m:02d}"


def generate_checkpoints(start: str, end: str) -> list[str]:
    """Build checkpoint time strings between shift start and end, every 2 hours."""
    s = time_to_float(start)
    e = time_to_float(end)
    pts: list[str] = []
    cur = s + _CHECKPOINT_INTERVAL_HRS
    while cur < e - 0.01:
        pts.append(float_to_time(cur))
        cur += _CHECKPOINT_INTERVAL_HRS
    pts.append(end)
    return pts


def expected_at_checkpoint(volume: float, start: str, end: str, checkpoint: str) -> float:
    """
    Linear interpolation: expected cumulative output at *checkpoint*.
    Returns 0 when shift duration is zero.
    """
    total_hrs = max(time_to_float(end) - time_to_float(start), 0.001)
    elapsed = max(time_to_float(checkpoint) - time_to_float(start), 0.0)
    pct = min(elapsed / total_hrs, 1.0)
    return round(volume * pct)


def get_auto_baseline_minutes_per_unit(department: str) -> float:
    """
    Return the average minutes-per-unit for *department* based on recent
    UPH history (last 30 days).  Returns 0.0 when no data is available.
    """
    try:
        from database import get_all_uph_history
        rows = get_all_uph_history(days=_AUTO_BASELINES_DAYS)
        dept_rows = [
            r for r in rows
            if str(r.get("department", "")).lower() == department.lower()
            and float(r.get("uph", 0) or 0) > 0
        ]
        if not dept_rows:
            return 0.0
        avg_uph = sum(float(r["uph"]) for r in dept_rows) / len(dept_rows)
        return round(60.0 / avg_uph, 2)
    except Exception:
        return 0.0


def get_dept_contributors(department: str, goal_status: list[dict]) -> list[dict]:
    """
    Return employees in *department* sorted by UPH gap, largest first.

    Each entry: {"name", "uph", "target", "gap"}
    """
    contribs = []
    for r in goal_status:
        if str(r.get("Department", "")).lower() != department.lower():
            continue
        try:
            uph = float(r.get("Average UPH") or 0)
            target = float(r.get("Target UPH") or 0)
            gap = target - uph if target > 0 else 0.0
        except (TypeError, ValueError):
            gap = 0.0
            uph = 0.0
            target = 0.0
        contribs.append({
            "name": r.get("Employee Name") or r.get("EmployeeName") or "",
            "uph": round(float(r.get("Average UPH") or 0), 1),
            "target": round(float(r.get("Target UPH") or 0), 1),
            "gap": round(gap, 1),
        })
    return sorted(contribs, key=lambda x: x["gap"], reverse=True)
