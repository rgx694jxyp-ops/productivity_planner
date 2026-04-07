"""
followup_manager.py
-------------------
Stores and retrieves coaching follow-up schedules.

Storage: Supabase coaching_followups table only.
"""

from datetime import date, timedelta


def add_followup(emp_id: str, name: str, dept: str, followup_date: str, note_preview: str = "") -> None:
    """Schedule a follow-up for an employee on a specific date (YYYY-MM-DD)."""
    from database import add_followup_db

    add_followup_db(emp_id, name, dept, followup_date, note_preview)


def get_followups_for_range(from_date: str = None, to_date: str = None) -> list[dict]:
    """Return all follow-ups within an inclusive date range, sorted by date."""
    _from = from_date or date.today().isoformat()
    _to   = to_date   or (date.today() + timedelta(days=30)).isoformat()
    from database import get_followups_db

    return list(get_followups_db(_from, _to))


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
    from database import remove_followup_db

    remove_followup_db(emp_id, followup_date)


def update_followup(emp_id: str, name: str, dept: str,
                    old_date: str, new_date: str, note_preview: str = "") -> None:
    """Move a follow-up from old_date to new_date."""
    remove_followup(emp_id, old_date)
    add_followup(emp_id, name, dept, new_date, note_preview)


def count_due_today() -> int:
    return len(get_followups_due_today())
