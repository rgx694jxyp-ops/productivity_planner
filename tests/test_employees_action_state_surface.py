from pathlib import Path


def test_employees_page_uses_normalized_action_state_service():
    source = Path("pages/employees.py").read_text(encoding="utf-8")

    assert "build_employee_action_state_summary" in source
    assert "schedule_follow_up_for_employee" in source
    assert "log_coaching_lifecycle_entry" in source
    assert "log_follow_through_event" in source
    assert "add_coaching_note" in source
    assert "Normalized action state" in source