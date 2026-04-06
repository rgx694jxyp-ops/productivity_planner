"""Risk scoring and priority computation."""

from domain.risk import _get_all_risk_levels


def _compute_priority_summary(gs: list[dict], history: list[dict]) -> dict:
    """Return lightweight action-oriented summary counts for header strips."""
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
