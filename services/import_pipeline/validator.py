"""Validation and duplicate checks for import rows."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from services.import_pipeline.models import ImportIssue


def validate_rows(parsed_rows: list[dict], *, max_reasonable_uph: float = 500.0) -> tuple[list[dict], list[ImportIssue], int]:
    """Validate parsed rows and aggregate valid rows by (emp_id, work_date, department).

    Returns: (candidate_rows, issues, duplicate_rows_in_file)
    """
    issues: list[ImportIssue] = []
    aggregate: dict[tuple[str, str, str], dict] = defaultdict(lambda: {"units": 0.0, "hours": 0.0, "uphs": [], "employee_name": ""})
    seen_keys: dict[tuple[str, str, str], int] = defaultdict(int)

    for row in parsed_rows or []:
        row_idx = int(row.get("row_index") or 0)
        emp_id = str(row.get("emp_id") or "").strip()
        work_date = str(row.get("work_date") or "").strip()[:10]
        dept = str(row.get("department") or "").strip()

        if not emp_id:
            issues.append(ImportIssue(code="missing_emp_id", message="Missing Employee ID", row_index=row_idx, field="EmployeeID"))
            continue

        units = row.get("units")
        hours = row.get("hours_worked")
        if units is None:
            issues.append(ImportIssue(code="invalid_units", message="Units must be numeric", row_index=row_idx, field="Units", value=str(row.get("units"))))
            continue
        if hours is None:
            issues.append(ImportIssue(code="invalid_hours", message="Hours worked must be numeric", row_index=row_idx, field="HoursWorked", value=str(row.get("hours_worked"))))
            continue

        if units < 0:
            issues.append(ImportIssue(code="negative_units", message="Units cannot be negative", row_index=row_idx, field="Units", value=str(units)))
            continue
        if hours < 0:
            issues.append(ImportIssue(code="negative_hours", message="Hours worked cannot be negative", row_index=row_idx, field="HoursWorked", value=str(hours)))
            continue

        if not work_date:
            work_date = date.today().isoformat()
            issues.append(ImportIssue(code="missing_date", message="Missing date; defaulted to today", severity="warning", row_index=row_idx, field="Date"))

        key = (emp_id, work_date, dept)
        seen_keys[key] += 1

        uph_val = row.get("uph")
        if uph_val is not None:
            if 0 <= uph_val <= max_reasonable_uph:
                aggregate[key]["uphs"].append(float(uph_val))
            else:
                issues.append(
                    ImportIssue(
                        code="invalid_uph",
                        message=f"UPH out of expected range (0-{max_reasonable_uph})",
                        severity="warning",
                        row_index=row_idx,
                        field="UPH",
                        value=str(uph_val),
                    )
                )

        aggregate[key]["units"] += float(units)
        aggregate[key]["hours"] += float(hours)
        if row.get("employee_name"):
            aggregate[key]["employee_name"] = str(row.get("employee_name"))

    duplicate_rows = sum(max(0, count - 1) for count in seen_keys.values())

    candidate_rows: list[dict] = []
    for (emp_id, work_date, dept), agg in aggregate.items():
        if agg["uphs"]:
            uph = round(sum(agg["uphs"]) / len(agg["uphs"]), 2)
        elif agg["hours"] > 0:
            uph = round(agg["units"] / agg["hours"], 2)
        else:
            uph = 0.0

        candidate_rows.append(
            {
                "emp_id": emp_id,
                "work_date": work_date,
                "department": dept,
                "employee_name": agg["employee_name"] or emp_id,
                "uph": uph,
                "units": round(agg["units"]),
                "hours_worked": round(agg["hours"], 2),
            }
        )

    return candidate_rows, issues, duplicate_rows
