"""Employee domain helpers extracted from pages/employees.py.

Pure calculation / DB functions — no Streamlit calls except session_state writes
inside _build_archived_productivity (which is intentional — it populates state).
"""
import time
from collections import defaultdict
from datetime import datetime as _dt

import pandas as pd
from database import get_client as _get_db_client
from database import get_employees as _get_employees
from goals import get_all_targets as _get_all_targets


def _build_archived_productivity(session_state: dict, force: bool = False) -> bool:
    """
    Build productivity session state from DB. Queries aggregate data directly
    to avoid fetching thousands of raw rows.
    Skips the rebuild if data was loaded recently (within 600 s) unless force=True.
    """
    _last = float(session_state.get("_archived_last_refresh_ts", 0.0) or 0.0)
    if not force and session_state.get("_archived_loaded") and (time.time() - _last) < 600:
        return True  # already fresh — skip the DB round-trip

    _emp_rows = _get_employees() or []
    _id_to_emp_code = {}
    emp_dept = {}
    emp_name = {}
    for _e in _emp_rows:
        _emp_code = str(_e.get("emp_id", "")).strip()
        _row_id = _e.get("id")
        _row_id_key = str(_row_id).strip() if _row_id is not None else ""
        if not _emp_code:
            continue
        emp_dept[_emp_code] = _e.get("department", "")
        emp_name[_emp_code] = _e.get("name", _emp_code)
        _id_to_emp_code[_emp_code] = _emp_code
        if _row_id_key:
            _id_to_emp_code[_row_id_key] = _emp_code

    # Don't bail if employees table is empty — UPH history has dept/emp info
    try:
        sb = _get_db_client()
    except Exception:
        from database import get_client as _db_get_client
        sb = _db_get_client()

    # ── Per-employee aggregates (avg UPH, total units, record count) ──────────
    emp_agg        = defaultdict(lambda: {"uph_sum": 0.0, "units": 0.0, "count": 0})
    month_dept_agg = defaultdict(lambda: defaultdict(lambda: {"uph_sum": 0.0, "uph_count": 0, "units": 0.0}))
    week_dept_agg  = defaultdict(lambda: defaultdict(lambda: {"units": 0.0, "uph_sum": 0.0, "uph_count": 0}))
    emp_daily      = defaultdict(list)   # eid -> [(date, uph)]
    emp_week_uph   = defaultdict(lambda: defaultdict(list))  # emp_id -> week_str -> [uph values]
    week_key_cache: dict[str, str] = {}

    page_size  = 1000
    offset     = 0
    total_rows = 0
    _last_err  = None
    while True:
        try:
            from database import _tq as _tq_fn
            r = _tq_fn(sb.table("uph_history").select(
                "emp_id, work_date, uph, units, department"
            )).order("work_date").range(offset, offset + page_size - 1).execute()
            batch = r.data or []
        except Exception as _pe:
            _last_err = repr(_pe)
            break
        for row in batch:
            _raw_eid = str(row.get("emp_id", "")).strip()
            eid   = _id_to_emp_code.get(_raw_eid, _raw_eid)
            uph   = float(row.get("uph") or 0)
            units = float(row.get("units") or 0)
            dept  = emp_dept.get(eid) or row.get("department") or "Unknown"
            if eid not in emp_dept and dept:
                emp_dept[eid] = dept
            if eid not in emp_name:
                emp_name[eid] = eid
            wd    = (row.get("work_date") or "")[:10]
            month = wd[:7]
            if uph > 0:
                emp_agg[eid]["uph_sum"] += uph
                emp_agg[eid]["count"]   += 1
            emp_agg[eid]["units"] += units
            emp_daily[eid].append((wd, uph))
            if month and uph > 0:
                month_dept_agg[month][dept]["uph_sum"]   += uph
                month_dept_agg[month][dept]["uph_count"] += 1
                month_dept_agg[month][dept]["units"]     += units
            if wd:
                wk = week_key_cache.get(wd)
                if wk is None:
                    try:
                        d = _dt.strptime(wd, "%Y-%m-%d")
                        wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
                    except Exception:
                        wk = ""
                    week_key_cache[wd] = wk
                if wk:
                    week_dept_agg[wk][dept]["units"] += units
                    if uph > 0:
                        week_dept_agg[wk][dept]["uph_sum"] += uph
                        week_dept_agg[wk][dept]["uph_count"] += 1
                        emp_week_uph[eid][wk].append(uph)
        total_rows += len(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    # Fallback to unit_submissions if uph_history empty
    if total_rows == 0:
        offset = 0
        while True:
            try:
                r = _tq_fn(sb.table("unit_submissions").select(
                    "emp_id, work_date, units, hours_worked"
                )).order("work_date").range(offset, offset + page_size - 1).execute()
                batch = r.data or []
            except Exception:
                break
            for row in batch:
                _raw_eid = str(row.get("emp_id", "")).strip()
                eid   = _id_to_emp_code.get(_raw_eid, _raw_eid)
                units = float(row.get("units") or 0)
                hours = float(row.get("hours_worked") or 0)
                uph   = round(units / hours, 2) if hours > 0 else 0
                dept  = emp_dept.get(eid, "Unknown")
                wd    = (row.get("work_date") or "")[:10]
                month = wd[:7]
                if uph > 0:
                    emp_agg[eid]["uph_sum"] += uph
                    emp_agg[eid]["count"]   += 1
                emp_agg[eid]["units"] += units
                emp_daily[eid].append((wd, uph))
                if month and uph > 0:
                    month_dept_agg[month][dept]["uph_sum"]   += uph
                    month_dept_agg[month][dept]["uph_count"] += 1
                    month_dept_agg[month][dept]["units"]     += units
                if wd:
                    wk = week_key_cache.get(wd)
                    if wk is None:
                        try:
                            d = _dt.strptime(wd, "%Y-%m-%d")
                            wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
                        except Exception:
                            wk = ""
                        week_key_cache[wd] = wk
                    if wk:
                        week_dept_agg[wk][dept]["units"] += units
                        if uph > 0:
                            week_dept_agg[wk][dept]["uph_sum"] += uph
                            week_dept_agg[wk][dept]["uph_count"] += 1
            total_rows += len(batch)
            if len(batch) < page_size:
                break
            offset += page_size

    # Calculate employee rolling averages
    employee_rolling_avg = []
    for eid, dates_uph in emp_daily.items():
        if not dates_uph:
            continue
        df = pd.DataFrame(dates_uph, columns=["Date", "UPH"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])
        if df.empty:
            continue
        df = df.groupby("Date", as_index=False)["UPH"].mean()
        df = df.sort_values("Date").set_index("Date")
        df["7DayRollingAvg"]  = df["UPH"].rolling("7D",  min_periods=7).mean()
        df["14DayRollingAvg"] = df["UPH"].rolling("14D", min_periods=14).mean()
        df = df.reset_index()
        for row in df.to_dict("records"):
            row_date = row.get("Date")
            uph_value = row.get("UPH")
            employee_rolling_avg.append({
                "Date":           row_date.strftime("%Y-%m-%d") if hasattr(row_date, "strftime") else "",
                "Employee":       emp_name.get(eid, eid),
                "UPH":            round(uph_value, 2) if pd.notna(uph_value) else None,
                "7DayRollingAvg": round(row.get("7DayRollingAvg"), 2),
                "14DayRollingAvg": round(row.get("14DayRollingAvg"), 2),
            })
    employee_rolling_avg.sort(key=lambda r: (r["Employee"], r["Date"]))

    if not emp_agg:
        session_state["_archived_loaded"] = False
        session_state["_arch_debug"] = (
            f"uph_history rows: {total_rows}, unit_submissions fallback ran: {total_rows == 0}"
        )
        return False

    # ── Build ranked list ─────────────────────────────────────────────────────
    ranked = []
    for i, (eid, agg) in enumerate(
            sorted(emp_agg.items(),
                   key=lambda x: x[1]["uph_sum"] / max(x[1]["count"], 1),
                   reverse=True), 1):
        avg_uph = round(agg["uph_sum"] / max(agg["count"], 1), 2)
        ranked.append({
            "Rank":          i,
            "Department":    emp_dept.get(eid, ""),
            "Shift":         "",
            "Employee Name": emp_name.get(eid, eid),
            "Average UPH":   avg_uph,
            "Record Count":  agg["count"],
            "EmployeeID":    eid,
            "goal_status":   "no_goal",
            "trend":         "insufficient_data",
            "flagged":       False,
            "change_pct":    0,
            "Target UPH":    "—",
            "vs Target":     "—",
        })

    # ── dept_trends ───────────────────────────────────────────────────────────
    dept_trends = []
    for month in sorted(month_dept_agg):
        for dept, vals in month_dept_agg[month].items():
            if vals["uph_count"] > 0:
                dept_trends.append({
                    "Month":       month,
                    "Department":  dept,
                    "Average UPH": round(vals["uph_sum"] / vals["uph_count"], 2),
                    "Count":       vals["uph_count"],
                })

    # ── weekly_summary ────────────────────────────────────────────────────────
    weekly_summary = []
    for wk in sorted(week_dept_agg):
        for dept, vals in week_dept_agg[wk].items():
            weekly_summary.append({
                "Week":        wk,
                "Month":       wk[:7],
                "Department":  dept,
                "Total Units": round(vals["units"]),
                "Avg UPH":     round(vals["uph_sum"] / max(vals["uph_count"], 1), 2),
            })

    # ── dept_report ───────────────────────────────────────────────────────────
    dept_report = {}
    for r2 in ranked:
        dept_report.setdefault(r2.get("Department", ""), []).append(r2)

    # ── Build trend_data from per-employee weekly UPH ─────────────────────────
    _trend_weeks = session_state.get("trend_weeks", 4)
    all_weeks_sorted = sorted(
        {wk for emp_wks in emp_week_uph.values() for wk in emp_wks}
    )
    recent_weeks = (all_weeks_sorted[-_trend_weeks:]
                    if len(all_weeks_sorted) >= _trend_weeks
                    else all_weeks_sorted)

    trend_data = {}
    for eid, week_map in emp_week_uph.items():
        week_avgs = []
        for w in recent_weeks:
            vals = week_map.get(w, [])
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

        trend_data[eid] = {
            "name":       emp_name.get(eid, eid),
            "dept":       emp_dept.get(eid, ""),
            "direction":  direction,
            "weeks":      week_avgs,
            "change_pct": change_pct,
        }

    # ── Apply goals ───────────────────────────────────────────────────────────
    try:
        from goals import build_goal_status as _bgs
        _arch_gs = _bgs(ranked, _get_all_targets(), trend_data)
    except Exception:
        _arch_gs = ranked

    session_state.update({
        "top_performers":       ranked,
        "goal_status":          _arch_gs,
        "dept_report":          dept_report,
        "dept_trends":          dept_trends,
        "weekly_summary":       weekly_summary,
        "employee_rolling_avg": employee_rolling_avg,
        "employee_risk":        [],
        "trend_data":           trend_data,
        "pipeline_done":        True,
        "_archived_loaded":     True,
        "_archived_last_refresh_ts": time.time(),
    })
    return True
