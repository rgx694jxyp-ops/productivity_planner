_RISK_CACHE_VER: tuple[int, int] | None = None
_RISK_CACHE: dict = {}


def calc_risk_level(emp, history):
    """Calculate performance risk level: high, medium, low."""
    risk_score = 0.0
    details = {
        "trend_score": 0,
        "streak_score": 0,
        "variance_score": 0,
    }

    trend = emp.get("trend", "insufficient_data")
    if trend == "down":
        risk_score += 4
        details["trend_score"] = 4
    elif trend == "flat":
        risk_score += 1
        details["trend_score"] = 1
    elif trend == "up":
        risk_score -= 2
        details["trend_score"] = -2

    emp_id = str(emp.get("EmployeeID", emp.get("Employee Name", "")))
    target_uph = emp.get("Target UPH", "—")
    under_goal_streak = 0

    if history and target_uph != "—":
        try:
            target = float(target_uph)
            emp_history = [
                row for row in history
                if str(row.get("EmployeeID", row.get("Employee Name", ""))) == emp_id
            ]
            if emp_history:
                sorted_hist = sorted(emp_history, key=lambda row: (row.get("Date", "") or row.get("Week", "")))
                for row in reversed(sorted_hist):
                    try:
                        uph_val = float(row.get("UPH", 0) or 0)
                        if uph_val < target:
                            under_goal_streak += 1
                        else:
                            break
                    except (ValueError, TypeError):
                        break
        except (ValueError, TypeError):
            pass

    if under_goal_streak >= 7:
        risk_score += 5
        details["streak_score"] = 5
    elif under_goal_streak >= 5:
        risk_score += 4
        details["streak_score"] = 4
    elif under_goal_streak >= 3:
        risk_score += 2.5
        details["streak_score"] = 2.5
    elif under_goal_streak >= 1:
        risk_score += 0.5
        details["streak_score"] = 0.5

    uph_values = []
    if history:
        emp_history = [
            row for row in history
            if str(row.get("EmployeeID", row.get("Employee Name", ""))) == emp_id
        ]
        for row in emp_history:
            try:
                uph_val = float(row.get("UPH", 0) or 0)
                if uph_val > 0:
                    uph_values.append(uph_val)
            except (ValueError, TypeError):
                pass

    if len(uph_values) >= 3:
        avg_uph = sum(uph_values) / len(uph_values)
        variance = sum((value - avg_uph) ** 2 for value in uph_values) / len(uph_values)
        std_dev = variance ** 0.5
        coeff_variation = (std_dev / avg_uph * 100) if avg_uph > 0 else 0

        if coeff_variation > 30:
            risk_score += 3
            details["variance_score"] = 3
        elif coeff_variation > 20:
            risk_score += 1.5
            details["variance_score"] = 1.5
        elif coeff_variation > 10:
            risk_score += 0.5
            details["variance_score"] = 0.5

        details["variance_pct"] = round(coeff_variation, 1)

    details["under_goal_streak"] = under_goal_streak
    details["total_score"] = round(risk_score, 1)

    if risk_score >= 7:
        return "🔴 High", risk_score, details
    if risk_score >= 4:
        return "🟡 Medium", risk_score, details
    return "🟢 Low", risk_score, details


def get_all_risk_levels(gs: list, history: list) -> dict:
    global _RISK_CACHE_VER, _RISK_CACHE

    ver = (len(gs), len(history))
    if _RISK_CACHE_VER == ver:
        return _RISK_CACHE

    cache = {}
    for row in gs:
        if row.get("goal_status") == "below_goal":
            emp_id = str(row.get("EmployeeID", row.get("Employee Name", "")))
            cache[emp_id] = calc_risk_level(row, history)

    _RISK_CACHE = cache
    _RISK_CACHE_VER = ver
    return cache


_calc_risk_level = calc_risk_level
_get_all_risk_levels = get_all_risk_levels
