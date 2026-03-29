"""
data_processor.py
-----------------
Chapter two: cleaning and enriching the raw CSV data.

Mirrors the VBA ProcessData sub:
  - Parses dates in almost any format
  - Calculates UPH from Units / HoursWorked when a direct UPH column is absent
  - Adds Month (yyyy-mm) and Week (W##) columns
  - Normalises Department, Shift, and EmployeeName to Proper Case
  - Logs every skipped row to the error log
"""

import re
from datetime import datetime, date

from settings  import Settings
from error_log import ErrorLog


# ── Date formats to attempt, in order of likelihood ─────────────────────────
DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%m-%d-%Y",
]


def process_data(
    rows: list[dict],
    mapping: dict[str, str],
    settings: Settings,
    error_log: ErrorLog,
) -> list[dict]:
    """
    Takes the raw CSV rows and returns enriched rows ready for history.
    Rows that cannot yield a valid date are skipped and logged.
    """
    date_col  = mapping.get("Date", "")
    dept_col  = mapping.get("Department", "")
    shift_col = mapping.get("Shift", "")
    name_col  = mapping.get("EmployeeName", "")
    uph_col   = mapping.get("UPH", "")
    units_col = mapping.get("Units", "")
    hours_col = mapping.get("HoursWorked", "")

    calculate_uph = not uph_col and bool(units_col and hours_col)

    processed   = []
    skipped     = 0
    uph_skipped = 0

    for idx, row in enumerate(rows, start=2):   # row 1 is the header

        # ── Parse the date ────────────────────────────────────────────────
        raw_date = _clean(row.get(date_col, ""))
        parsed_date = _parse_date(raw_date)

        if parsed_date is None:
            skipped += 1
            error_log.log("ProcessData", idx, "invalid date",
                          f"Could not parse date value.", raw_date)
            continue

        # ── Calculate UPH if needed (Option B) ───────────────────────────
        if calculate_uph:
            try:
                units = float(_clean(row.get(units_col, "") or "0"))
                hours = float(_clean(row.get(hours_col, "") or "0"))
                if hours == 0:
                    raise ZeroDivisionError
                row["UPH"] = round(units / hours, 4)
            except (ValueError, ZeroDivisionError):
                uph_skipped += 1
                error_log.log("ProcessData", idx, "zero hours",
                              "Zero or invalid hours — UPH set to blank.", row.get(hours_col, ""))
                row["UPH"] = ""

        # ── Normalise text fields to Proper Case ──────────────────────────
        if dept_col:
            row[dept_col] = _proper(_clean(row.get(dept_col, "")))
        if shift_col:
            row[shift_col] = _proper(_clean(row.get(shift_col, "")))
        if name_col:
            row[name_col] = _clean(row.get(name_col, ""))   # name: trim only, no casing

        # ── Add Month and Week columns ────────────────────────────────────
        row["Month"] = parsed_date.strftime("%Y-%m")
        row["Week"]  = f"W{parsed_date.isocalendar()[1]:02d}"
        row[date_col] = parsed_date.strftime("%Y-%m-%d")   # normalise date format

        processed.append(row)

    # ── Summary ──────────────────────────────────────────────────────────────
    if skipped:
        print(f"  ⚠  {skipped} row(s) skipped (unparseable date)")
    if uph_skipped:
        print(f"  ⚠  {uph_skipped} row(s) had zero/invalid hours (UPH left blank)")
    print(f"  ✓  {len(processed)} row(s) processed successfully")

    return processed


# ── Helpers ──────────────────────────────────────────────────────────────────

def _clean(value) -> str:
    """Strip whitespace and non-printable characters."""
    if value is None:
        return ""
    s = str(value)
    s = re.sub(r"[^\x20-\x7E]", "", s)   # drop non-ASCII printable chars
    return s.strip()


def _parse_date(raw: str) -> date | None:
    """Try every known format, then try Excel serial numbers."""
    if not raw:
        return None

    # Excel serial date (e.g. 45000)
    try:
        serial = float(raw)
        if 1 < serial < 2_958_466:   # 1900-01-01 to 9999-12-31
            from datetime import timedelta
            base = datetime(1899, 12, 30)
            return (base + timedelta(days=int(serial))).date()
    except ValueError:
        pass

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return None


def _proper(text: str) -> str:
    """Title-case a string, collapsing extra spaces."""
    cleaned = " ".join(text.split())   # collapse multiple spaces
    return cleaned.title() if cleaned else ""
