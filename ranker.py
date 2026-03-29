"""
ranker.py
---------
Chapter four: turning raw history into ranked performance reports.

Mirrors the VBA RankEmployees + GenerateDepartmentSheets subs:
  - Aggregates average UPH per employee (respecting the rolling window)
  - Produces a Top Performers list sorted by UPH descending
  - Groups employees by department, then by shift, then by UPH
  - Applies green/amber/red highlighting metadata for the Excel exporter
  - Generates Top-3 / Bottom-3 summary blocks per department
"""

from datetime import datetime, date
from collections import defaultdict

from settings  import Settings
from error_log import ErrorLog


# ── Named tuples / simple records ────────────────────────────────────────────

class EmployeeRecord:
    __slots__ = ("dept", "shift", "emp_id", "name", "total_uph", "count")

    def __init__(self, dept, shift, emp_id, name):
        self.dept      = dept
        self.shift     = shift
        self.emp_id    = emp_id
        self.name      = name
        self.total_uph = 0.0
        self.count     = 0

    @property
    def avg_uph(self) -> float:
        return self.total_uph / self.count if self.count > 0 else 0.0


def rank_employees(
    history: list[dict],
    mapping: dict[str, str],
    settings: Settings,
    error_log: ErrorLog,
) -> list[dict]:
    """
    Aggregates history into one record per employee, then sorts descending by UPH.
    Applies the ChartMonths rolling window.
    Returns a list of dicts ready to write to the Top Performers report.
    """
    cutoff = _get_cutoff_month(settings)

    id_col    = mapping.get("EmployeeID")  or "EmployeeID"
    name_col  = mapping.get("EmployeeName") or "EmployeeName"
    dept_col  = mapping.get("Department")   or "Department"
    shift_col = mapping.get("Shift")        or "Shift"
    # When Option B is used, mapping["UPH"] is "" but ProcessData writes the
    # calculated value under the key "UPH" directly — so fall back to "UPH".
    uph_col   = mapping.get("UPH")          or "UPH"

    employees: dict[str, EmployeeRecord] = {}

    for row in history:
        month = str(row.get("Month", "") or "")
        if cutoff and month and month < cutoff:
            continue

        emp_key = str(row.get(id_col) or row.get("EmployeeID") or "").strip()
        if not emp_key:
            emp_key = str(row.get(name_col) or row.get("EmployeeName") or "").strip()
        if not emp_key:
            continue

        try:
            uph_val = float(row.get(uph_col) or row.get("UPH") or "")
        except (ValueError, TypeError):
            continue

        if emp_key not in employees:
            employees[emp_key] = EmployeeRecord(
                dept  = str(row.get(dept_col)  or row.get("Department")  or "").strip(),
                shift = str(row.get(shift_col) or row.get("Shift")       or "").strip(),
                emp_id= emp_key,
                name  = str(row.get(name_col)  or row.get("EmployeeName") or "").strip(),
            )

        employees[emp_key].total_uph += uph_val
        employees[emp_key].count     += 1

    if not employees:
        error_log.log("RankEmployees", 0, "missing column",
                      "No employee records found after applying the rolling window.", "")
        return []

    ranked = sorted(employees.values(), key=lambda e: e.avg_uph, reverse=True)

    result = []
    for rank, emp in enumerate(ranked, start=1):
        result.append({
            "Rank":          rank,
            "Department":    emp.dept,
            "Shift":         emp.shift,
            "EmployeeID":    emp.emp_id,
            "Employee Name": emp.name,
            "Average UPH":   round(emp.avg_uph, 2),
            "Record Count":  emp.count,
        })

    print(f"  ✓  {len(result)} employee(s) ranked")
    return result


def build_department_report(
    ranked: list[dict],
    settings: Settings,
    error_log: ErrorLog,
) -> dict[str, list[dict]]:
    """
    Groups ranked employees by department and attaches highlight metadata
    (green / amber / red) to each row.

    Returns {dept_name: [row_dict, ...]} where each row_dict has an extra
    '_highlight' key: 'top' | 'bottom' | 'target' | None.
    """
    top_pct    = max(0.0, float(settings.get("top_pct", 10))) / 100.0
    bot_pct    = max(0.0, float(settings.get("bot_pct", 10))) / 100.0

    # Group by department
    dept_groups: dict[str, list[dict]] = defaultdict(list)
    for row in ranked:
        dept_groups[row["Department"]].append(dict(row))

    for dept, rows in dept_groups.items():
        target_uph = settings.get_dept_target_uph(dept)

        # Sort: Shift A→Z, then UPH high→low within each shift
        rows.sort(key=lambda r: (r.get("Shift", ""), -r.get("Average UPH", 0)))

        sorted_uphs = sorted(r["Average UPH"] for r in rows)
        n           = len(sorted_uphs)

        top_cut = sorted_uphs[max(0, int(n * (1 - top_pct)))] if top_pct > 0 and n >= 2 else 0
        bot_cut = sorted_uphs[min(n - 1, max(0, int(n * bot_pct) - 1))] if bot_pct > 0 and n >= 2 else float("inf")

        # Re-rank within each shift group
        shift_rank: dict[str, int] = {}
        for row in rows:
            shift = row.get("Shift", "")
            shift_rank[shift] = shift_rank.get(shift, 0) + 1
            row["Shift Rank"] = shift_rank[shift]

        # Attach highlight metadata — priority: target miss > top > bottom
        for row in rows:
            uph = row["Average UPH"]
            if target_uph > 0 and uph < target_uph:
                row["_highlight"] = "target"
            elif top_pct > 0 and top_cut > 0 and uph >= top_cut:
                row["_highlight"] = "top"
            elif bot_pct > 0 and uph <= bot_cut:
                row["_highlight"] = "bottom"
            else:
                row["_highlight"] = None

    return dict(dept_groups)


def build_top_bottom_summary(dept_rows: list[dict], n: int = 3) -> dict:
    """
    Returns {'top': [row, ...], 'bottom': [row, ...]} for the N best and worst employees
    in a department (by Average UPH).  Ensures no employee appears in both lists.
    """
    if not dept_rows:
        return {"top": [], "bottom": []}

    by_uph   = sorted(dept_rows, key=lambda r: r.get("Average UPH", 0), reverse=True)
    top_rows = by_uph[:n]
    top_ids  = {id(r) for r in top_rows}

    bottom_candidates = [r for r in by_uph if id(r) not in top_ids]
    bottom_rows       = list(reversed(bottom_candidates))[:n]

    return {"top": top_rows, "bottom": bottom_rows}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_cutoff_month(settings: Settings) -> str:
    """Returns 'yyyy-mm' of the oldest month to include, or '' to include all."""
    months = int(settings.get("chart_months") or 0)
    if months <= 0:
        return ""
    now = datetime.now()
    year  = now.year
    month = now.month - months + 1
    while month <= 0:
        month += 12
        year  -= 1
    return f"{year:04d}-{month:02d}"
