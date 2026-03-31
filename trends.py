"""
trends.py
---------
Aggregates historical data into the trend tables that feed the charts.

Mirrors the VBA CalculateDepartmentTrends + BuildWeeklySummary subs:
  - Monthly UPH averages per department  → department_trends
  - Weekly UPH + unit totals per dept    → weekly_summary
Both respect the ChartMonths rolling window from settings.
"""

from collections import defaultdict
import pandas as pd
from ranker import _get_cutoff_month   # reuse the same cutoff logic

from settings  import Settings
from error_log import ErrorLog


def calculate_department_trends(
    history:  list[dict],
    mapping:  dict[str, str],
    settings: Settings,
    error_log: ErrorLog,
) -> list[dict]:
    """
    Aggregates average UPH by Month + Department.
    Returns rows sorted by Department, then Month.
    """
    cutoff   = _get_cutoff_month(settings)
    dept_col = mapping.get("Department") or "Department"
    uph_col  = mapping.get("UPH")        or "UPH"

    # key = (month, dept) → [count, total_uph]
    agg: dict[tuple, list] = defaultdict(lambda: [0, 0.0])

    for row in history:
        month = str(row.get("Month", "") or "").strip()
        dept  = str(row.get(dept_col)  or row.get("Department", "") or "").strip()

        if not month or not dept:
            continue
        if cutoff and month < cutoff:
            continue

        try:
            uph = float(row.get(uph_col) or row.get("UPH") or "")
        except (ValueError, TypeError):
            continue

        agg[(month, dept)][0] += 1
        agg[(month, dept)][1] += uph

    if not agg:
        error_log.log("DepartmentTrends", 0, "missing column",
                      "No data found after applying the rolling window.", "")
        return []

    results = []
    for (month, dept), (count, total) in agg.items():
        results.append({
            "Month":        month,
            "Department":   dept,
            "Average UPH":  round(total / count, 2) if count > 0 else 0,
            "Record Count": count,
        })

    results.sort(key=lambda r: (r["Department"], r["Month"]))
    print(f"  ✓  {len(results)} month/department combination(s) calculated")
    return results


def build_weekly_summary(
    history:  list[dict],
    mapping:  dict[str, str],
    settings: Settings,
    error_log: ErrorLog,
) -> list[dict]:
    """
    Aggregates by Week + Department.
    Returns rows sorted by Department, then week number.
    """
    cutoff    = _get_cutoff_month(settings)
    dept_col  = mapping.get("Department") or "Department"
    date_col  = mapping.get("Date")       or "Date"
    uph_col   = mapping.get("UPH")        or "UPH"
    units_col = mapping.get("Units")       or "Units"

    # key = (dept, zero_padded_week) → aggregation bucket
    agg: dict[tuple, dict] = {}

    for row in history:
        month = str(row.get("Month", "") or "").strip()
        dept  = str(row.get(dept_col) or row.get("Department", "") or "").strip()
        week  = str(row.get("Week",   "") or "").strip()

        if not dept or not week:
            continue
        if cutoff and month and month < cutoff:
            continue

        # Zero-pad the week number so W1 < W10 when sorting as strings
        week_num = 0
        try:
            week_num = int(week.lstrip("Ww"))
        except ValueError:
            pass
        week_padded = f"W{week_num:02d}"

        # Track actual date for range display
        row_date = str(row.get(date_col) or row.get("Date", "") or "").strip()[:10]

        key = (dept, week_padded)
        if key not in agg:
            agg[key] = {"dept": dept, "week_label": week,
                        "count": 0, "total_uph": 0.0, "total_units": 0.0,
                        "min_date": row_date, "max_date": row_date}

        try:
            agg[key]["total_uph"] += float(row.get(uph_col) or row.get("UPH") or 0)
        except (ValueError, TypeError):
            pass

        try:
            agg[key]["total_units"] += float(row.get(units_col) or row.get("Units") or 0)
        except (ValueError, TypeError):
            pass

        agg[key]["count"] += 1
        if row_date:
            if row_date < agg[key]["min_date"] or not agg[key]["min_date"]:
                agg[key]["min_date"] = row_date
            if row_date > agg[key]["max_date"] or not agg[key]["max_date"]:
                agg[key]["max_date"] = row_date

    if not agg:
        error_log.log("WeeklySummary", 0, "missing column",
                      "No weekly data found — ensure ProcessData has been run.", "")
        return []

    results = []
    for (dept, week_padded), data in sorted(agg.items()):
        avg_uph = round(data["total_uph"] / data["count"], 2) if data["count"] > 0 else 0
        min_d = data.get("min_date", "")
        max_d = data.get("max_date", "")
        week_range = f"{min_d} – {max_d}" if min_d and max_d and min_d != max_d else min_d
        results.append({
            "Department":   data["dept"],
            "Week":         data["week_label"],
            "Week Range":   week_range,
            "From":         min_d,
            "To":           max_d,
            "Avg UPH":      avg_uph,
            "Total Units":  round(data["total_units"], 0),
            "Record Count": data["count"],
        })

    print(f"  ✓  {len(results)} department/week combination(s) built")
    return results


def calculate_employee_rolling_average(
    history: list[dict],
    mapping: dict[str, str],
    settings: Settings,
    error_log: ErrorLog,
) -> list[dict]:
    """
    Calculates 7-day rolling average UPH for each employee.
    Returns rows sorted by Employee, then Date.
    """
    date_col = mapping.get("Date", "Date")
    emp_col = mapping.get("EmployeeName", "EmployeeName")
    uph_col = mapping.get("UPH", "UPH")

    if not history:
        return []

    df = pd.DataFrame(history)

    # Ensure date is datetime
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

    # Drop rows with invalid dates
    df = df.dropna(subset=[date_col])

    # Ensure UPH is numeric
    df[uph_col] = pd.to_numeric(df[uph_col], errors='coerce')

    results = []

    for emp, group in df.groupby(emp_col):
        if group.empty:
            continue

        group = group.sort_values(date_col).set_index(date_col)

        # Calculate 7-day and 14-day rolling averages
        group['7DayRollingAvg'] = group[uph_col].rolling('7D', min_periods=1).mean()
        group['14DayRollingAvg'] = group[uph_col].rolling('14D', min_periods=1).mean()

        # Reset index to get date back
        group = group.reset_index()

        for _, row in group.iterrows():
            results.append({
                "Date": row[date_col].strftime("%Y-%m-%d"),
                "Employee": emp,
                "UPH": round(row[uph_col], 2) if pd.notna(row[uph_col]) else None,
                "7DayRollingAvg": round(row['7DayRollingAvg'], 2),
                "14DayRollingAvg": round(row['14DayRollingAvg'], 2),
            })

    results.sort(key=lambda r: (r["Employee"], r["Date"]))
    print(f"  ✓  {len(results)} employee/day rolling average(s) calculated")
    return results
