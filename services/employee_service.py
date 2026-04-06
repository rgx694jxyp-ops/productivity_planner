"""Employee workflow orchestration helpers for page-level history views."""

from datetime import date, datetime, timedelta

import pandas as pd


def filter_employees_by_department(emps: list[dict], dept_sel: str) -> list[dict]:
    if dept_sel == "All departments":
        return emps
    return [e for e in emps if e.get("department", "") == dept_sel]


def parse_history_range(from_str: str, to_str: str, default_days: int = 90) -> dict:
    default_from = date.today() - timedelta(days=default_days)
    default_to = date.today()
    try:
        from_date = datetime.strptime((from_str or "").strip(), "%m/%d/%Y").date()
    except Exception:
        from_date = default_from
    try:
        to_date = datetime.strptime((to_str or "").strip(), "%m/%d/%Y").date()
    except Exception:
        to_date = default_to

    return {
        "from_date": from_date,
        "to_date": to_date,
        "from_iso": from_date.isoformat(),
        "to_iso": to_date.isoformat(),
        "days": max(1, (to_date - from_date).days),
    }


def load_employee_history_workflow(filtered_emps: list[dict], emp_id: str, from_iso: str, to_iso: str) -> dict:
    """Load employee history with bigint-safe uph_history query and fallback to unit_submissions."""
    history = []

    # Resolve text employee code to numeric employees.id for uph_history lookup.
    this_emp_rec = next((e for e in filtered_emps if e.get("emp_id") == emp_id), None)
    uph_emp_id = int(this_emp_rec["id"]) if (this_emp_rec and this_emp_rec.get("id") is not None) else emp_id

    try:
        from database import _tq as tq, get_client
        sb = get_client()
        r = tq(
            sb.table("uph_history")
            .select("*")
            .eq("emp_id", uph_emp_id)
            .gte("work_date", from_iso)
            .lte("work_date", to_iso)
        ).order("work_date").execute()
        history = r.data or []
    except Exception:
        history = []

    if not history:
        try:
            from collections import defaultdict
            from database import _tq as tq, get_client

            sb = get_client()
            r = tq(
                sb.table("unit_submissions")
                .select("*")
                .eq("emp_id", emp_id)
                .gte("work_date", from_iso)
                .lte("work_date", to_iso)
            ).order("work_date").execute()

            by_day = defaultdict(lambda: {"units": 0.0, "hours": 0.0})
            for row in (r.data or []):
                dk = row.get("work_date", "")
                by_day[dk]["units"] += float(row.get("units") or 0)
                by_day[dk]["hours"] += float(row.get("hours_worked") or 0)

            history = [
                {
                    "work_date": dk,
                    "uph": round(vals["units"] / vals["hours"], 2) if vals["hours"] > 0 else 0,
                    "units": round(vals["units"]),
                    "hours_worked": round(vals["hours"], 2),
                }
                for dk, vals in sorted(by_day.items())
            ]
        except Exception:
            pass

    return {
        "success": True,
        "data": {
            "history": history,
        },
        "error": None,
        "warnings": [],
    }


def build_employee_history_frames(history: list[dict]) -> dict:
    uph_vals = [float(h.get("uph") or 0) for h in history if h.get("uph")]
    avg_uph = round(sum(uph_vals) / len(uph_vals), 2) if uph_vals else None

    df = pd.DataFrame(
        [
            {
                "Date": h.get("work_date", ""),
                "UPH": round(float(h.get("uph") or 0), 2),
                "Units": int(h.get("units", 0) or 0),
                "Hours": round(float(h.get("hours_worked") or 0), 2),
            }
            for h in history
        ]
    ).sort_values("Date")

    import math

    df_chart = df[df["UPH"].apply(lambda x: x > 0 and math.isfinite(x))]

    return {
        "success": True,
        "data": {
            "avg_uph": avg_uph,
            "df": df,
            "df_chart": df_chart,
        },
        "error": None,
        "warnings": [],
    }
