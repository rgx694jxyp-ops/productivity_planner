"""
orders.py
---------
Order management, shift setup, and the daily unit submission workflow.

Key concepts:
  - An Order belongs to a Client and tracks units toward completion
  - Employees can be split across multiple orders in one shift
  - Submission = confirming that today's uploaded file units go to specific orders
  - New employees are detected and flagged before submission is allowed
"""

from datetime import date, datetime
from database import (
    get_orders, get_order, create_order, update_order, complete_order,
    get_assignments, assign_employee_to_order, assign_employee_split,
    get_unassigned_employees, submit_units, get_submissions,
    get_order_hours_worked, get_avg_uph, get_employee, upsert_employee,
    suggest_employees_for_order, get_employees, store_client_trend,
    get_client_trends, get_clients,
)


# ── Order calculations ────────────────────────────────────────────────────────

def get_order_progress(order_id: str) -> dict:
    """
    Returns a rich progress snapshot for one order.
    Safe to call frequently — does minimal DB queries.
    """
    order        = get_order(order_id)
    if not order:
        return {}

    total        = float(order.get("total_units") or 0)
    completed    = float(order.get("units_completed") or 0)
    remaining    = max(0, total - completed)
    pct          = round((completed / total * 100), 1) if total > 0 else 0
    hours_worked = get_order_hours_worked(order_id)

    # Get currently assigned employees and their combined UPH
    assignments  = get_assignments(order_id=order_id, active_only=True)
    emp_uphs     = []
    for a in assignments:
        avg = get_avg_uph(a["emp_id"], days=30)
        emp_uphs.append(avg if avg is not None else 10.0)  # 10 UPH default for new employees

    combined_uph    = sum(emp_uphs)
    shift_length    = float(order.get("shift_length_hrs") or 8)
    target_uph      = float(order.get("target_uph") or 0)

    # Hours to completion at current team pace
    hrs_to_complete = round(remaining / combined_uph, 1) if combined_uph > 0 else None
    shifts_to_complete = round(hrs_to_complete / shift_length, 1) if hrs_to_complete else None

    # Is it on track vs target date?
    on_track = None
    if order.get("target_date") and hrs_to_complete is not None:
        days_left     = (date.fromisoformat(order["target_date"]) - date.today()).days
        shifts_avail  = max(0, days_left)
        on_track      = shifts_to_complete <= shifts_avail if shifts_to_complete else None

    return {
        "order":            order,
        "total_units":      total,
        "units_completed":  completed,
        "units_remaining":  remaining,
        "pct_complete":     pct,
        "hours_worked":     round(hours_worked, 1),
        "combined_uph":     round(combined_uph, 2),
        "hrs_to_complete":  hrs_to_complete,
        "shifts_to_complete": shifts_to_complete,
        "assigned_count":   len(assignments),
        "on_track":         on_track,
        "status":           order.get("status", "open"),
    }


def get_all_open_order_progress() -> list[dict]:
    """Dashboard view — progress for every open order."""
    orders = get_orders(status="open")
    return [get_order_progress(o["id"]) for o in orders if o.get("id")]


# ── Split-day assignment ──────────────────────────────────────────────────────

def build_submission_plan(
    rows: list[dict],
    mapping: dict[str, str],
    work_date: str,
    source_file: str = "",
) -> dict:
    """
    Given a list of processed CSV rows for one day, build a submission plan:
      - Detect new employees (not in DB yet)
      - For each employee, look up their active order assignment
      - If the row already has an order column, use that instead
      - Return a plan dict the user can review and confirm

    Returns:
    {
      "ready":        [{"emp_id", "name", "order_id", "order_number", "units", "uph", "hours"}],
      "unassigned":   [{"emp_id", "name", "units"}],       # no order assigned
      "new_employees":[{"emp_id", "name", "units"}],       # never seen before
      "warnings":     [str],
    }
    """
    id_col    = mapping.get("EmployeeID")   or "EmployeeID"
    name_col  = mapping.get("EmployeeName") or "EmployeeName"
    uph_col   = mapping.get("UPH")          or "UPH"
    units_col = mapping.get("Units")        or "Units"
    hours_col = mapping.get("HoursWorked")  or "HoursWorked"
    order_col = mapping.get("OrderNumber")  or ""   # optional — may not exist

    # Aggregate by employee (a file may have multiple rows per employee)
    from collections import defaultdict
    emp_totals: dict[str, dict] = defaultdict(lambda: {
        "units": 0.0, "hours": 0.0, "uph_vals": [], "name": "", "order_number": ""
    })

    for row in rows:
        emp_id = str(row.get(id_col) or "").strip()
        if not emp_id:
            continue
        emp_totals[emp_id]["name"]  = str(row.get(name_col) or "").strip()
        emp_totals[emp_id]["units"] += _safe_float(row.get(units_col))
        emp_totals[emp_id]["hours"] += _safe_float(row.get(hours_col))
        if row.get(uph_col):
            emp_totals[emp_id]["uph_vals"].append(_safe_float(row.get(uph_col)))
        if order_col and row.get(order_col):
            emp_totals[emp_id]["order_number"] = str(row.get(order_col) or "").strip()

    ready        = []
    unassigned   = []
    new_employees= []
    warnings     = []

    # Fetch all open orders once for lookup
    open_orders = {o["order_number"]: o for o in get_orders(status="open") if o.get("order_number")}

    for emp_id, data in emp_totals.items():
        units = data["units"]
        hours = data["hours"]
        uph   = (sum(data["uph_vals"]) / len(data["uph_vals"])
                 if data["uph_vals"] else
                 round(units / hours, 2) if hours > 0 else 0.0)

        existing = get_employee(emp_id)
        is_new   = existing is None

        if is_new:
            new_employees.append({
                "emp_id": emp_id, "name": data["name"],
                "units": units, "hours": hours, "uph": uph,
            })
            continue

        # Determine order: CSV column > app assignment
        order_id = None
        order_number = ""
        if data["order_number"] and data["order_number"] in open_orders:
            order_id     = open_orders[data["order_number"]]["id"]
            order_number = data["order_number"]
        else:
            assigned = get_assignments(emp_id=emp_id, active_only=True)
            if assigned:
                order_id     = assigned[0]["order_id"]
                order_info   = get_order(order_id)
                order_number = order_info.get("order_number", "")

        if not order_id:
            unassigned.append({
                "emp_id": emp_id, "name": data["name"],
                "units": units, "hours": hours, "uph": uph,
            })
            continue

        ready.append({
            "emp_id":       emp_id,
            "name":         data["name"],
            "order_id":     order_id,
            "order_number": order_number,
            "units":        units,
            "hours":        hours,
            "uph":          uph,
            "source_file":  source_file,
            "work_date":    work_date,
        })

    if unassigned:
        warnings.append(f"{len(unassigned)} employee(s) have no order assignment — assign them before submitting.")
    if new_employees:
        warnings.append(f"{len(new_employees)} new employee(s) detected — add them to the system before submitting.")

    return {
        "ready":         ready,
        "unassigned":    unassigned,
        "new_employees": new_employees,
        "warnings":      warnings,
        "work_date":     work_date,
    }


def commit_submission_plan(plan: dict) -> tuple[int, list[str]]:
    """
    Execute a confirmed submission plan.
    Returns (rows_committed, list_of_errors).
    """
    committed = 0
    errors    = []

    for item in plan.get("ready", []):
        try:
            submit_units(
                order_id     = item["order_id"],
                emp_id       = item["emp_id"],
                units        = item["units"],
                uph          = item["uph"],
                hours_worked = item["hours"],
                work_date    = item["work_date"],
                source_file  = item.get("source_file", ""),
            )
            committed += 1
        except Exception as e:
            errors.append(f"{item.get('name','?')}: {e}")

    return committed, errors


# ── Client trend recording ────────────────────────────────────────────────────

def record_client_trend_on_complete(order_id: str):
    """
    Called when an order is marked complete.
    Calculates period stats and stores them in client_trends.
    """
    order = get_order(order_id)
    if not order or not order.get("client_id"):
        return

    subs       = get_submissions(order_id=order_id)
    total_units= sum(float(s.get("units") or 0) for s in subs)
    uph_vals   = [float(s["uph"]) for s in subs if s.get("uph")]
    avg_uph    = round(sum(uph_vals) / len(uph_vals), 2) if uph_vals else 0

    period = date.today().strftime("%Y-%m")  # store by month

    # Count completed orders this month for this client
    all_orders = get_orders(client_id=order["client_id"], status="complete")
    completed_this_month = sum(
        1 for o in all_orders
        if (o.get("completed_at") or "").startswith(period)
    )

    store_client_trend(
        client_id        = order["client_id"],
        period           = period,
        avg_uph          = avg_uph,
        total_units      = total_units,
        orders_completed = completed_this_month,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val or 0)
    except (ValueError, TypeError):
        return default
