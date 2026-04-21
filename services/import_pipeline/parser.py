"""CSV session parsing and normalization for import pipeline."""

from __future__ import annotations

from datetime import date
from typing import Any

from services.import_date_service import parse_work_date


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    text = _safe_str(value)
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_sessions_to_rows(sessions: list[dict], fallback_date: date) -> list[dict]:
    """Parse uploaded session rows into normalized row dicts.

    Output row keys:
      - source_file
      - row_index (1-based within source file)
      - emp_id, employee_name, department, work_date
      - units, hours_worked, uph
    """
    out: list[dict] = []
    fallback_date_str = fallback_date.isoformat()
    date_parse_cache: dict[str, str | None] = {}

    for session in sessions or []:
        mapping = session.get("mapping") or {}
        rows = session.get("rows") or []
        filename = _safe_str(session.get("filename")) or "Upload"

        id_col = mapping.get("EmployeeID", "EmployeeID")
        name_col = mapping.get("EmployeeName", "EmployeeName")
        dept_col = mapping.get("Department", "Department")
        date_col = mapping.get("Date", "")
        units_col = mapping.get("Units", "Units")
        hours_col = mapping.get("HoursWorked", "HoursWorked")
        uph_col = mapping.get("UPH", "UPH")

        for idx, row in enumerate(rows, start=1):
            work_date = fallback_date_str
            date_parse_error = ""
            raw_date_value = ""
            raw_units_value = _safe_str(row.get(units_col, ""))
            raw_hours_value = _safe_str(row.get(hours_col, ""))
            raw_uph_value = _safe_str(row.get(uph_col, ""))
            if date_col:
                raw_date_value = _safe_str(row.get(date_col, ""))
                if raw_date_value:
                    cached_date = date_parse_cache.get(raw_date_value)
                    if raw_date_value not in date_parse_cache:
                        cached_date = parse_work_date(raw_date_value)
                        date_parse_cache[raw_date_value] = cached_date
                    if cached_date:
                        work_date = cached_date
                    else:
                        work_date = ""
                        date_parse_error = "unparseable"
                else:
                    work_date = ""
                    date_parse_error = "missing"

            out.append(
                {
                    "source_file": filename,
                    "row_index": idx,
                    "emp_id": _safe_str(row.get(id_col, "")),
                    "employee_name": _safe_str(row.get(name_col, "")),
                    "department": _safe_str(row.get(dept_col, "")),
                    "work_date": work_date,
                    "units": _safe_float(raw_units_value),
                    "hours_worked": _safe_float(raw_hours_value),
                    "uph": _safe_float(raw_uph_value),
                    "_date_parse_error": date_parse_error,
                    "_raw_date_value": raw_date_value,
                    "_raw_units_value": raw_units_value,
                    "_raw_hours_worked_value": raw_hours_value,
                    "_raw_uph_value": raw_uph_value,
                }
            )

    return out
