"""
followup_manager.py
-------------------
Stores and retrieves coaching follow-up schedules.

Storage: local JSON file per tenant. No DB migration required.
Format:  { "YYYY-MM-DD": [ {emp_id, name, dept, note_preview, added_on}, ... ] }
"""

import json
import os
from datetime import date, timedelta

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _followup_file() -> str:
    try:
        import streamlit as st
        tid = st.session_state.get("tenant_id", "")
        if tid:
            return os.path.join(_BASE_DIR, f"dpd_followups_{tid}.json")
    except Exception:
        pass
    return os.path.join(_BASE_DIR, "dpd_followups.json")


def _load() -> dict:
    fp = _followup_file()
    if not os.path.exists(fp):
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict):
    try:
        with open(_followup_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def add_followup(emp_id: str, name: str, dept: str, followup_date: str, note_preview: str = "") -> None:
    """Schedule a follow-up for an employee on a specific date (YYYY-MM-DD)."""
    data = _load()
    if followup_date not in data:
        data[followup_date] = []
    # Remove any existing follow-up for this employee (avoid duplicates)
    data[followup_date] = [e for e in data[followup_date] if str(e.get("emp_id")) != str(emp_id)]
    data[followup_date].append({
        "emp_id":       str(emp_id),
        "name":         str(name)[:60],
        "dept":         str(dept)[:40],
        "note_preview": str(note_preview)[:80],
        "added_on":     date.today().isoformat(),
    })
    _save(data)


def get_followups_for_range(from_date: str = None, to_date: str = None) -> list[dict]:
    """Return all follow-ups within an inclusive date range, sorted by date."""
    data = _load()
    _from = from_date or date.today().isoformat()
    _to   = to_date   or (date.today() + timedelta(days=30)).isoformat()
    results = []
    for date_str, entries in data.items():
        if _from <= date_str <= _to:
            for e in entries:
                results.append({**e, "followup_date": date_str})
    return sorted(results, key=lambda x: x["followup_date"])


def get_followups_due_today() -> list[dict]:
    return get_followups_for_range(
        from_date=date.today().isoformat(),
        to_date=date.today().isoformat(),
    )


def get_followups_this_week() -> list[dict]:
    today  = date.today()
    sunday = today + timedelta(days=(6 - today.weekday()))
    return get_followups_for_range(
        from_date=today.isoformat(),
        to_date=sunday.isoformat(),
    )


def remove_followup(emp_id: str, followup_date: str) -> None:
    """Remove a follow-up once it has been completed."""
    data = _load()
    if followup_date in data:
        data[followup_date] = [e for e in data[followup_date] if str(e.get("emp_id")) != str(emp_id)]
        if not data[followup_date]:
            del data[followup_date]
    _save(data)


def update_followup(emp_id: str, name: str, dept: str,
                    old_date: str, new_date: str, note_preview: str = "") -> None:
    """Move a follow-up from old_date to new_date."""
    remove_followup(emp_id, old_date)
    add_followup(emp_id, name, dept, new_date, note_preview)


def count_due_today() -> int:
    return len(get_followups_due_today())
