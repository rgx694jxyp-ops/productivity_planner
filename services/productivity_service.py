"""Productivity domain helpers extracted from pages/productivity.py.

Pure calculation / DB / export functions — no Streamlit calls.
"""
import io
from collections import defaultdict
from datetime import date, timedelta

from core.dependencies import _cached_employees, _get_db_client


# ── Priority list risk scoring ─────────────────────────────────────────────

def _calc_priority_risk_level(emp: dict, history: list) -> tuple:
    """Calculate performance risk level."""
    risk_score = 0.0
    details = {"trend_score": 0, "streak_score": 0, "variance_score": 0}

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
            emp_history = [r for r in history if str(r.get("EmployeeID", r.get("Employee Name", ""))) == emp_id]
            if emp_history:
                sorted_hist = sorted(emp_history, key=lambda r: (r.get("Date", "") or r.get("Week", "")))
                for r in reversed(sorted_hist):
                    try:
                        uph_val = float(r.get("UPH", 0) or 0)
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
        emp_history = [r for r in history if str(r.get("EmployeeID", r.get("Employee Name", ""))) == emp_id]
        for r in emp_history:
            try:
                uph_val = float(r.get("UPH", 0) or 0)
                if uph_val > 0:
                    uph_values.append(uph_val)
            except (ValueError, TypeError):
                pass

    if len(uph_values) >= 3:
        avg_uph = sum(uph_values) / len(uph_values)
        variance = sum((x - avg_uph) ** 2 for x in uph_values) / len(uph_values)
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
    elif risk_score >= 4:
        return "🟡 Medium", risk_score, details
    else:
        return "🟢 Low", risk_score, details


# ── Coaching score calculation ─────────────────────────────────────────────

def _calc_coaching_score(emp: dict, context_tags: list, history: list) -> tuple:
    """Score an employee for coaching need. Higher = more urgent.
    Context tags reduce urgency (e.g., new employees need coaching but lower priority).
    Also returns whether they meet strict auto-flag criteria.
    Returns (score, reasons, context_impact, meets_auto_flag_criteria).
    """
    score = 0.0
    reasons = []

    # Factor 1: How far below goal
    target = emp.get("Target UPH") or 0
    avg_uph = emp.get("Average UPH") or 0
    under_goal = False
    if target and target != "—":
        try:
            target = float(target)
            avg_uph = float(avg_uph)
            pct_below = ((target - avg_uph) / target * 100) if target > 0 else 0
            score += abs(pct_below) * 0.5  # 0.5 points per percent below
            reasons.append(f"{pct_below:.1f}% below target")
            under_goal = True
        except (ValueError, TypeError):
            pass

    # Factor 2: Negative trend (direction + magnitude)
    trend = emp.get("trend", "insufficient_data")
    change_pct = emp.get("change_pct", 0.0)
    trending_down = False
    try:
        change_pct = float(change_pct)
    except (ValueError, TypeError):
        change_pct = 0.0

    if trend == "down":
        score += 5  # Declining is a red flag
        reasons.append(f"Declining trend ({change_pct:+.1f}%)")
        trending_down = True
    elif trend == "flat":
        score += 2  # Flat is concerning when below goal
        if change_pct <= -3 or change_pct >= 3:
            reasons.append(f"Flat trend ({change_pct:+.1f}%)")
        else:
            reasons.append("Flat trend")
    elif change_pct < 0:
        score += 1  # Slight decline
        reasons.append(f"Slight decline ({change_pct:+.1f}%)")

    # Factor 3: Streak (consecutive entries below their average)
    emp_id = str(emp.get("EmployeeID", emp.get("Employee Name", "")))
    streak = 0
    emp_avg = avg_uph
    if history and emp_avg:
        emp_history = [r for r in history
                       if str(r.get("EmployeeID", r.get("Employee Name", ""))) == emp_id]
        if emp_history:
            sorted_hist = sorted(emp_history,
                                 key=lambda r: (r.get("Date", "") or r.get("Week", "")))
            for r in reversed(sorted_hist):
                try:
                    uph_val = float(r.get("UPH", 0) or 0)
                    if uph_val < emp_avg:
                        streak += 1
                    else:
                        break
                except (ValueError, TypeError):
                    break
            if streak >= 3:
                score += streak * 0.3
                reasons.append(f"{streak} consecutive entries below avg")

    # Strict auto-flag criteria: under goal AND trending down AND multi-day streak
    meets_auto_flag_criteria = (under_goal and trending_down and streak >= 3)

    # Factor 4: Context modifier — reduce urgency based on situational factors
    context_impact = []
    if "New employee" in context_tags:
        score *= 0.5
        context_impact.append("(New — expect ramp-up period)")
    if "Cross-training" in context_tags:
        score *= 0.6
        context_impact.append("(In cross-training)")
    if "Equipment issues" in context_tags:
        score *= 0.4
        context_impact.append("(Address equipment first)")
    if "Shift change" in context_tags:
        score *= 0.5
        context_impact.append("(Recent shift change)")
    if "Short staffed" in context_tags:
        score *= 0.7
        context_impact.append("(Team capacity issue)")

    return score, reasons, context_impact, meets_auto_flag_criteria


# ── Period report helpers ───────────────────────────────────────────────────

def _resolve_period_dates(period: str) -> tuple:
    """Convert a named period string to (start_date, end_date)."""
    today = date.today()
    if period == "Prior day":
        return today - timedelta(days=1), today - timedelta(days=1)
    elif period == "Current week":
        return today - timedelta(days=today.weekday()), today
    elif period == "Prior week":
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end
    elif period == "Prior month":
        first_of_this = today.replace(day=1)
        end = first_of_this - timedelta(days=1)
        return end.replace(day=1), end
    return today - timedelta(days=1), today - timedelta(days=1)


def _email_risk_level(emp: dict, history_all: list) -> str:
    """Quick risk calculation for email."""
    risk_score = 0.0
    trend = emp.get("trend", "insufficient_data")
    if trend == "down":
        risk_score += 4
    elif trend == "flat":
        risk_score += 1
    elif trend == "up":
        risk_score -= 2

    emp_id = emp.get("EmployeeID", "")
    if history_all and emp.get("Target UPH") != "—":
        try:
            target = float(emp.get("Target UPH"))
            emp_hist = [r for r in history_all if r.get("emp_id") == emp_id]
            streak = 0
            for r in reversed(emp_hist[-10:]):
                try:
                    uph = float(r.get("uph") or 0)
                    if uph < target:
                        streak += 1
                    else:
                        break
                except Exception:
                    break
            if streak >= 3:
                risk_score += 3
        except Exception:
            pass

    if risk_score >= 7:
        return "🔴 High"
    elif risk_score >= 4:
        return "🟡 Medium"
    else:
        return "🟢 Low"


def _build_period_report(d_start, d_end, dept_choice: str, depts: list,
                          gs: list, targets: dict, tenant_id: str = "",
                          plan_name: str = "starter") -> tuple:
    """
    Build Excel report bytes, subject, and HTML body for a date range.
    d_start / d_end are date objects. Returns (xl_bytes, subj, body).
    """
    today = date.today()

    from_iso     = d_start.isoformat()
    to_iso       = d_end.isoformat()
    period_label = from_iso if from_iso == to_iso else f"{from_iso} – {to_iso}"
    dept_label   = dept_choice if dept_choice != "All departments" else "All Departments"
    subj         = f"Performance Report — {dept_label} — {period_label}"

    try:
        _sb = _get_db_client()
        _uph_q = _sb.table("uph_history").select(
            "emp_id, units, hours_worked, uph, work_date, department"
        ).gte("work_date", from_iso).lte("work_date", to_iso)
        _emp_q = _sb.table("employees").select("emp_id, name, department")
        if tenant_id:
            _uph_q = _uph_q.eq("tenant_id", tenant_id)
            _emp_q = _emp_q.eq("tenant_id", tenant_id)
        else:
            from database import _tq as _tq3
            _uph_q = _tq3(_uph_q)
            _emp_q = _tq3(_emp_q)
        subs = (_uph_q.execute().data or [])
        emps_lookup = {e["emp_id"]: e for e in (_emp_q.execute().data or [])}
    except Exception:
        subs = []
        emps_lookup = {e["emp_id"]: e for e in (_cached_employees() or [])}
    # Fallback to unit_submissions if uph_history returned nothing for that range
    if not subs:
        try:
            _sb2 = _get_db_client()
            _us_q = _sb2.table("unit_submissions").select(
                "emp_id, units, hours_worked, work_date, department"
            ).gte("work_date", from_iso).lte("work_date", to_iso)
            if tenant_id:
                _us_q = _us_q.eq("tenant_id", tenant_id)
            else:
                from database import _tq as _tq_us
                _us_q = _tq_us(_us_q)
            _us_rows = _us_q.execute().data or []
            for row in _us_rows:
                h = float(row.get("hours_worked") or 0)
                u = float(row.get("units") or 0)
                row["uph"] = round(u / h, 2) if h > 0 else 0.0
            subs = _us_rows
        except Exception:
            pass

    if dept_choice != "All departments":
        subs = [s for s in subs
                if (s.get("department", "") == dept_choice or
                    emps_lookup.get(s.get("emp_id", ""), {}).get("department", "") == dept_choice)]

    if not subs:
        body = (f"<h2>{dept_label} — {period_label}</h2>"
                f"<p>No work data was found for <strong>{dept_label}</strong> "
                f"between <strong>{from_iso}</strong> and <strong>{to_iso}</strong>.</p>"
                f"<p>Employees may not have had submissions during this period, "
                f"or the date range falls outside your imported data.</p>")
        return None, subj, body

    emp_agg = defaultdict(lambda: {"units": 0.0, "hours": 0.0, "dept": ""})
    for s in subs:
        eid = s.get("emp_id", "")
        emp_agg[eid]["units"] += float(s.get("units") or 0)
        emp_agg[eid]["hours"] += float(s.get("hours_worked") or 0)
        emp_agg[eid]["dept"]   = emps_lookup.get(eid, {}).get("department", "")

    try:
        _sb = _get_db_client()
        _recent = (d_end - timedelta(days=30)).isoformat()
        _hist_q = _sb.table("uph_history").select("emp_id, uph, work_date").gte("work_date", _recent)
        if tenant_id:
            _hist_q = _hist_q.eq("tenant_id", tenant_id)
        else:
            from database import _tq as _tq_hist
            _hist_q = _tq_hist(_hist_q)
        _email_hist = _hist_q.execute().data or []
    except Exception:
        _email_hist = []

    gs_by_emp = {str(r.get("EmployeeID", "")): r for r in (gs or []) if r.get("EmployeeID")}

    def _trend_snapshot(emp_id: str) -> tuple:
        if emp_id in gs_by_emp:
            _row = gs_by_emp[emp_id]
            return _row.get("trend", "insufficient_data"), float(_row.get("change_pct", 0) or 0)
        emp_hist = []
        for row in _email_hist:
            if row.get("emp_id") == emp_id:
                try:
                    emp_hist.append((row.get("work_date", ""), float(row.get("uph") or 0)))
                except Exception:
                    pass
        if len(emp_hist) < 4:
            return "insufficient_data", 0.0
        emp_hist.sort(key=lambda item: item[0])
        recent = [v for _, v in emp_hist[-3:]]
        previous = [v for _, v in emp_hist[-6:-3]]
        if not previous:
            return "insufficient_data", 0.0
        prev_avg = sum(previous) / len(previous)
        recent_avg = sum(recent) / len(recent)
        if prev_avg <= 0:
            return "insufficient_data", 0.0
        pct = round(((recent_avg - prev_avg) / prev_avg) * 100, 1)
        if pct >= 5:
            return "up", pct
        if pct <= -5:
            return "down", pct
        return "flat", pct

    scope_gs = []
    for eid, agg in emp_agg.items():
        emp_info = emps_lookup.get(eid, {})
        dept     = agg["dept"]
        uph      = round(agg["units"] / agg["hours"], 2) if agg["hours"] > 0 else 0
        tgt      = float(targets.get(dept, 0) or 0)
        trend, change_pct = _trend_snapshot(eid)
        scope_gs.append({
            "Employee Name": emp_info.get("name", eid),
            "EmployeeID":    eid,
            "Department":    dept,
            "Average UPH":   uph,
            "Total Units":   round(agg["units"]),
            "Hours Worked":  round(agg["hours"], 2),
            "Target UPH":    tgt if tgt else "—",
            "goal_status":   ("on_goal" if tgt and uph >= tgt
                              else "below_goal" if tgt else "no_goal"),
            "trend":         trend,
            "change_pct":    change_pct,
            "flagged":       False,
        })
    scope_gs.sort(key=lambda r: float(r.get("Average UPH", 0) or 0), reverse=True)

    on_g  = sum(1 for r in scope_gs if r["goal_status"] == "on_goal")
    below = sum(1 for r in scope_gs if r["goal_status"] == "below_goal")

    # Top 3 performers
    _top3 = scope_gs[:3]
    _top3_html = ""
    if _top3:
        _top3_html = "<h3>🏆 Top Performers</h3><ol>"
        for t in _top3:
            _top3_html += f"<li><strong>{t['Employee Name']}</strong> ({t['Department']}) — {t['Average UPH']} UPH</li>"
        _top3_html += "</ol>"

    # Bottom 3 performers (with targets & risk)
    _bottom = [r for r in reversed(scope_gs) if r["goal_status"] == "below_goal"][:3]
    _bottom_html = ""
    if _bottom:
        _bottom_html = "<h3>⚠️ Needs Coaching</h3><table style='width:100%; border-collapse: collapse;'>"
        _bottom_html += "<tr style='background: #f5f5f5;'><th style='padding: 8px; text-align: left; border: 1px solid #ddd;'>Employee</th><th style='text-align: center; border: 1px solid #ddd;'>Risk</th><th style='text-align: right; border: 1px solid #ddd;'>UPH</th></tr>"
        for b in _bottom:
            _risk = _email_risk_level(b, _email_hist)
            _tgt = b.get('Target UPH', '—')
            _diff = ""
            try:
                _diff = f" (vs {_tgt})"
            except (ValueError, TypeError):
                pass
            _bottom_html += f"<tr><td style='padding: 8px; border: 1px solid #ddd;'><strong>{b['Employee Name']}</strong><br/><span style='font-size: 0.9em; color: #666;'>{b['Department']}</span></td><td style='text-align: center; border: 1px solid #ddd;'>{_risk}</td><td style='text-align: right; border: 1px solid #ddd;'>{b['Average UPH']}{_diff}</td></tr>"
        _bottom_html += "</table>"

    # ACTION SECTION 1: TODAY's critical attention (🔴 High risk)
    _critical_html = ""
    _critical_list = []
    for r in scope_gs:
        if r["goal_status"] == "below_goal":
            _risk = _email_risk_level(r, _email_hist)
            if "🔴" in _risk:
                _critical_list.append(r)

    if _critical_list:
        _critical_html = "<h3 style='color: #8b0000;'>🔴 PRIORITY: Needs Attention TODAY</h3>"
        _critical_html += "<div style='background: #ffe6e6; border-left: 4px solid #8b0000; padding: 12px; margin-bottom: 16px;'>"
        for c in _critical_list[:3]:
            _action = ""
            try:
                _cur = float(c.get("Average UPH") or 0)
                _tgt = float(c.get("Target UPH") or 0)
                _gap = _tgt - _cur
                if _gap > 5:
                    _action = "👉 <strong>Action:</strong> Schedule 1-on-1. Discuss specific goals & support needed."
                else:
                    _action = "👉 <strong>Action:</strong> Check in on any blockers or issues."
            except Exception:
                _action = "👉 <strong>Action:</strong> Check in immediately."
            _critical_html += f"<div style='margin-bottom: 12px;'><strong>{c['Employee Name']}</strong> ({c['Department']}) — {c['Average UPH']} UPH<br/>{_action}</div>"
        _critical_html += "</div>"

    # ACTION SECTION 2: Who improved this week (trend = up)
    _improved_html = ""
    _improved_list = [r for r in scope_gs if r.get("trend") == "up" and r.get("change_pct", 0) > 0]
    if _improved_list:
        _improved_html = "<h3 style='color: #008000;'>🟢 Recognition: Who Improved This Week</h3>"
        _improved_html += "<div style='background: #e6ffe6; border-left: 4px solid #008000; padding: 12px; margin-bottom: 16px;'>"
        for imp in _improved_list[:3]:
            _pct = imp.get("change_pct", 0)
            _improved_html += f"<div style='margin-bottom: 8px;'><strong>✓ {imp['Employee Name']}</strong> ({imp['Department']}) — <span style='color: green;'>+{_pct:.1f}%</span> trending up<br/>👉 <strong>Action:</strong> Recognize this improvement. Ask what's working & how to sustain it.</div>"
        _improved_html += "</div>"

    # ACTION SECTION 3: Who is trending down (early warning)
    _trending_down_html = ""
    _trending_down = [r for r in scope_gs if r.get("trend") == "down" and r.get("goal_status") != "no_goal"]
    if _trending_down:
        _trending_down_html = "<h3 style='color: #ff6600;'>⚠️ Early Warning: Trending Down</h3>"
        _trending_down_html += "<div style='background: #fff9e6; border-left: 4px solid #ff6600; padding: 12px; margin-bottom: 16px;'>"
        _trending_down_html += f"<p><strong>{len(_trending_down)} employee(s) showing declining performance:</strong></p>"
        for td in _trending_down[:5]:
            _pct = td.get("change_pct", 0)
            _status = "at risk" if td.get("goal_status") == "below_goal" else "still on track"
            _trending_down_html += f"<div style='margin-bottom: 8px;'><strong>• {td['Employee Name']}</strong> ({td['Department']}) — {_pct:.1f}% down ({_status})<br/>👉 <strong>Action:</strong> Proactive check-in. Address trend early before it worsens.</div>"
        _trending_down_html += "</div>"

    # Average UPH across all employees
    _avg_all = round(sum(r["Average UPH"] for r in scope_gs) / len(scope_gs), 1) if scope_gs else 0

    _dept_health_rows = []
    for _dept in sorted({r.get("Department", "") for r in scope_gs if r.get("Department")}):
        _dept_rows = [r for r in scope_gs if r.get("Department") == _dept]
        _dept_on = sum(1 for r in _dept_rows if r.get("goal_status") == "on_goal")
        _dept_total = len(_dept_rows)
        _dept_pct = round((_dept_on / _dept_total) * 100) if _dept_total else 0
        _dept_health_rows.append(
            f"<tr><td style='padding:8px;border:1px solid #ddd;'><strong>{_dept}</strong></td>"
            f"<td style='padding:8px;border:1px solid #ddd;text-align:center;'>{_dept_on}/{_dept_total}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;text-align:center;'>{_dept_pct}%</td></tr>"
        )
    _dept_health_html = ""
    if _dept_health_rows:
        _dept_health_html = (
            "<h3>📊 Department Health</h3>"
            "<table style='width:100%; border-collapse: collapse;'>"
            "<tr style='background: #f5f5f5;'><th style='padding: 8px; text-align: left; border: 1px solid #ddd;'>Department</th>"
            "<th style='text-align: center; border: 1px solid #ddd;'>On Goal</th>"
            "<th style='text-align: center; border: 1px solid #ddd;'>Health</th></tr>"
            + "".join(_dept_health_rows)
            + "</table>"
        )

    _top_risks_html = ""
    if plan_name in ("pro", "business"):
        _risk_rows = []
        for _row in [r for r in scope_gs if r.get("goal_status") == "below_goal"][:5]:
            _risk_rows.append(
                f"<tr><td style='padding:8px;border:1px solid #ddd;'><strong>{_row['Employee Name']}</strong></td>"
                f"<td style='padding:8px;border:1px solid #ddd;'>{_row['Department']}</td>"
                f"<td style='padding:8px;border:1px solid #ddd;text-align:right;'>{_row['Average UPH']}</td>"
                f"<td style='padding:8px;border:1px solid #ddd;text-align:center;'>{_email_risk_level(_row, _email_hist)}</td></tr>"
            )
        if _risk_rows:
            _top_risks_html = (
                "<h3>🔴 Top Risks — Action Required Today</h3>"
                "<table style='width:100%; border-collapse: collapse;'>"
                "<tr style='background: #f5f5f5;'><th style='padding: 8px; text-align: left; border: 1px solid #ddd;'>Employee</th>"
                "<th style='padding: 8px; text-align: left; border: 1px solid #ddd;'>Dept</th>"
                "<th style='padding: 8px; text-align: right; border: 1px solid #ddd;'>UPH</th>"
                "<th style='padding: 8px; text-align: center; border: 1px solid #ddd;'>Risk</th></tr>"
                + "".join(_risk_rows)
                + "</table>"
            )

    _cost_html = ""
    if plan_name in ("pro", "business"):
        try:
            from settings import Settings as _ImpactS
            _impact_settings = _ImpactS(tenant_id=tenant_id) if tenant_id else _ImpactS()
            _avg_wage = float(_impact_settings.get("avg_hourly_wage", 18.0))
        except Exception:
            _avg_wage = 18.0
        _cost_total = 0.0
        for _row in scope_gs:
            try:
                _target = float(_row.get("Target UPH") or 0)
                _avg = float(_row.get("Average UPH") or 0)
                _hours = float(_row.get("Hours Worked") or 0)
                if _target > 0 and 0 < _avg < _target:
                    _cost_total += max(((_target - _avg) / _target) * _hours * _avg_wage, 0)
            except Exception:
                pass
        _cost_html = f"<h3>💰 Cost Impact</h3><p>Estimated labor cost impact for below-goal performance in this period: <strong>${_cost_total:,.0f}</strong></p>"

    body = (f"<h2>{dept_label} — {period_label}</h2>"
            f"<p><strong>{len(scope_gs)}</strong> employees · "
            f"Avg UPH: <strong>{_avg_all}</strong> · "
            f"<strong style='color:green'>{on_g} on goal</strong> · "
            f"<strong style='color:red'>{below} below goal</strong></p>"
            f"<hr/>"
            f"{_dept_health_html}"
            f"{_top3_html}"
            f"{_top_risks_html}"
            f"{_critical_html}"
            f"{_improved_html}"
            f"{_trending_down_html}"
            f"{_bottom_html}"
            f"{_cost_html}"
            f"<hr/>"
            f"<p style='font-size: 0.9em; color: #666;'>See the attached Excel report for full details and department breakdown.</p>")

    xl_data = None
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.chart import BarChart, Reference
        HDR_FILL  = PatternFill("solid", fgColor="FF0F2D52")
        HDR_FONT  = Font(bold=True, color="FFFFFFFF", size=10, name="Arial")
        GRN_FILL  = PatternFill("solid", fgColor="FFD4EDDA")
        RED_FILL  = PatternFill("solid", fgColor="FFF8D7DA")
        DARK_FONT = Font(color="FF1A2D42", size=10, name="Arial")
        STATUS_LABELS = {"on_goal": "On Goal", "below_goal": "Below Goal", "no_goal": "No Target"}

        wb = openpyxl.Workbook()
        ws = wb.active; ws.title = "Summary"
        ws["A1"] = f"{dept_label} — {period_label}"
        ws["A1"].font = Font(bold=True, size=13, name="Arial", color="FF0F2D52")
        ws["A2"] = f"Generated: {today.isoformat()}   |   {on_g} on goal · {below} below goal"
        ws["A2"].font = Font(size=10, name="Arial", color="FF5A7A9C")

        hdrs = ["Employee", "Department", "Total Units", "Hours Worked", "Avg UPH", "Target UPH", "Status"]
        for ci, h in enumerate(hdrs, 1):
            c = ws.cell(4, ci, h); c.fill = HDR_FILL; c.font = HDR_FONT
            c.alignment = Alignment(horizontal="center")
        for ri, r in enumerate(scope_gs, 5):
            fill = (GRN_FILL if r["goal_status"] == "on_goal"
                    else RED_FILL if r["goal_status"] == "below_goal" else None)
            for ci, v in enumerate([r["Employee Name"], r["Department"],
                                     r["Total Units"], r["Hours Worked"],
                                     r["Average UPH"], r["Target UPH"],
                                     STATUS_LABELS.get(r["goal_status"], "—")], 1):
                c = ws.cell(ri, ci, v); c.font = DARK_FONT
                c.alignment = Alignment(horizontal="left" if ci <= 2 else "center")
                if fill: c.fill = fill

        if scope_gs:
            chart = BarChart(); chart.type = "bar"; chart.style = 10
            chart.title = f"Avg UPH — {period_label}"
            chart.width = 20; chart.height = max(8, len(scope_gs) * 0.55)
            last_r = 4 + len(scope_gs)
            chart.add_data(Reference(ws, min_col=5, min_row=4, max_row=last_r), titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=5, max_row=last_r))
            chart.series[0].graphicalProperties.solidFill = "0F2D52"
            ws.add_chart(chart, "I5")

        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(
                max((len(str(c.value or "")) for c in col), default=8) + 3, 40)

        buf = io.BytesIO(); wb.save(buf); buf.seek(0); xl_data = buf.read()
    except Exception:
        pass

    return xl_data, subj, body
