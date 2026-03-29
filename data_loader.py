"""
data_loader.py
--------------
Constants and CSV utilities shared across the app.
The interactive CLI / tkinter flow from the original has been removed —
all column mapping is now handled by the web interface in app.py.
"""

import csv
import io
from datetime import datetime


# ── Field definitions ────────────────────────────────────────────────────────

REQUIRED_FIELDS = ["Date", "Department", "EmployeeID", "EmployeeName"]
OPTIONAL_FIELDS = ["Shift", "UPH", "Units", "HoursWorked"]
AUTO_FIELDS     = ["Month", "Week"]   # computed by ProcessData, never mapped by user
ALL_FIELDS      = REQUIRED_FIELDS + OPTIONAL_FIELDS


# ── Auto-detection aliases ───────────────────────────────────────────────────
# Maps canonical field names to a list of CSV header variations (lowercased,
# spaces and underscores removed) that should be auto-matched.

FIELD_ALIASES: dict = {
    "Date":         ["date", "workdate", "work_date", "transdate", "shift_date",
                     "processdate", "process_date", "entrydate", "entry_date"],
    "Department":   ["department", "dept", "department_name", "team", "area",
                     "division", "group"],
    "EmployeeID":   ["employeeid", "employee_id", "empid", "emp_id", "id",
                     "worker_id", "associate_id", "badge", "badgeid", "badge_id",
                     "associateid", "userid", "user_id"],
    "EmployeeName": ["employeename", "employee_name", "empname", "emp_name",
                     "name", "full_name", "fullname", "worker_name", "workername",
                     "associate", "associatename", "associate_name"],
    "Shift":        ["shift", "shift_name", "shiftname", "shifttype", "shift_type"],
    "UPH":          ["uph", "units_per_hour", "unitsperhour", "rate"],
    "Units":        ["units", "totalunits", "total_units", "qty", "quantity",
                     "output", "pieces", "count", "totalpieces", "total_pieces",
                     "unitsprocessed", "units_processed"],
    "HoursWorked":  ["hoursworked", "hours_worked", "hours", "hrs",
                     "time", "timeworked", "time_worked", "laborhours", "labor_hours"],
}


def auto_detect(headers: list) -> dict:
    """
    Given a list of CSV header names, return a mapping of
    {canonical_field: csv_header} for any headers that match known aliases.
    """
    norm = {h.lower().replace(" ", "").replace("_", ""): h for h in headers}
    result = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            key = alias.replace("_", "")
            if key in norm:
                result[field] = norm[key]
                break
    return result


def parse_csv_bytes(raw: bytes) -> tuple:
    """
    Parse raw CSV bytes (from st.file_uploader) into (headers, rows).
    Tries UTF-8-sig, then UTF-8, then latin-1.
    Returns ([], []) on failure.
    """
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text   = raw.decode(encoding)
            reader = csv.DictReader(io.StringIO(text))
            headers = [str(h).strip() for h in (reader.fieldnames or [])]
            rows    = [dict(row) for row in reader]
            return headers, rows
        except Exception:
            continue
    return [], []


def parse_date(value: str):
    """
    Try to parse a date string in common formats.
    Returns ISO 8601 (YYYY-MM-DD) string or None.
    """
    formats = [
        "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y",
        "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
        "%m/%d/%y", "%d/%m/%y",
    ]
    v = str(value).strip()[:10]
    for fmt in formats:
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
