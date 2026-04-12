from datetime import date

from services.signal_interpretation_service import (
    format_comparison_window,
    format_observed_label,
    interpret_below_expected_performance,
    interpret_changed_from_normal,
    interpret_employee_detail_view_signals,
    interpret_follow_up_due,
    interpret_team_process_view_signals,
    interpret_import_data_trust_view_signals,
    interpret_today_view_signals,
)


def test_format_observed_label_uses_yesterday_and_date_rules():
    today = date(2026, 4, 11)
    assert format_observed_label(date(2026, 4, 10), today=today) == "Yesterday"
    assert format_observed_label(date(2026, 4, 10), today=today, is_shift_level=True) == "Previous shift"
    assert format_observed_label(date(2026, 4, 4), today=today) == "Apr 4"


def test_format_comparison_window_supports_filtered_days_label():
    dates = [date(2026, 4, 2), date(2026, 4, 4), date(2026, 4, 6)]
    assert format_comparison_window(dates, 3) == "3 similar days between Apr 2–Apr 6"


def test_interpret_below_expected_performance_is_deterministic():
    row = {
        "EmployeeID": "E1",
        "Employee": "Alex",
        "Department": "Picking",
        "Average UPH": 42,
        "Target UPH": 55,
        "trend": "down",
        "goal_status": "below_goal",
    }
    today = date(2026, 4, 9)

    card_a = interpret_below_expected_performance(row=row, today=today)
    card_b = interpret_below_expected_performance(row=row, today=today)

    assert card_a == card_b
    assert card_a.what_happened
    assert card_a.compared_to_what
    assert card_a.why_flagged
    assert card_a.validate() == []


def test_interpret_follow_up_due_contains_expected_explainability():
    action = {
        "id": "a-1",
        "employee_id": "E2",
        "employee_name": "Blair",
        "department": "Pack",
        "follow_up_due_at": "2026-04-08",
        "_queue_status": "overdue",
        "status": "new",
    }

    card = interpret_follow_up_due(action=action, today=date(2026, 4, 9))

    assert "overdue" in card.what_happened.lower()
    assert card.drill_down.screen == "today"
    assert card.confidence.level in {"high", "medium", "low"}
    assert card.validate() == []


def test_interpret_follow_up_due_includes_pattern_memory_metadata_when_repeat_signals_exist():
    action = {
        "id": "a-9",
        "employee_id": "E9",
        "employee_name": "Casey",
        "department": "Receiving",
        "follow_up_due_at": "2026-04-08",
        "_queue_status": "overdue",
        "status": "new",
        "_is_repeat_issue": True,
        "_repeat_signals": ["coached 3x", "2x no improvement"],
        "last_event_at": "2026-04-07T15:30:00Z",
        "issue_type": "repeat_no_improvement",
        "baseline_uph": 48,
        "latest_uph": 43,
    }

    card = interpret_follow_up_due(action=action, today=date(2026, 4, 9))

    assert card.metadata.get("pattern_detected") is True
    assert card.metadata.get("repeat_count", 0) >= 2
    assert "repeated" in str(card.metadata.get("pattern_summary", "")).lower()
    assert card.metadata.get("pattern_window_label") == "this week"


def test_interpret_below_expected_exposes_repeat_metadata_without_overriding_main_signal_meaning():
    row = {
        "EmployeeID": "E1",
        "Employee": "Alex",
        "Department": "Picking",
        "Average UPH": 42,
        "Target UPH": 55,
        "trend": "down",
        "goal_status": "below_goal",
        "recent_trend_history": ["down", "declining", "below_expected"],
        "recent_goal_status_history": ["below_goal", "below_goal"],
    }

    card = interpret_below_expected_performance(row=row, today=date(2026, 4, 9))

    assert card.metadata.get("repeat_count", 0) >= 2
    assert card.metadata.get("pattern_window_label") == "this week"


def test_today_view_signal_sections_are_present():
    queue_items = [
        {
            "id": "a-1",
            "employee_id": "E2",
            "employee_name": "Blair",
            "department": "Pack",
            "follow_up_due_at": "2026-04-08",
            "created_at": "2026-04-06",
            "_queue_status": "overdue",
            "status": "new",
            "_is_repeat_issue": True,
        }
    ]
    goal_status = [
        {
            "EmployeeID": "E2",
            "Employee": "Blair",
            "Department": "Pack",
            "Average UPH": 50,
            "Target UPH": 60,
            "trend": "declining",
            "change_pct": -12.5,
            "goal_status": "below_goal",
        }
    ]
    out = interpret_today_view_signals(
        queue_items=queue_items,
        goal_status=goal_status,
        import_summary={"days": 1, "emp_count": 20, "below": 5, "risks": 2},
        today=date(2026, 4, 9),
    )

    assert set(out.keys()) == {"needs_attention", "changed_from_normal", "unresolved_items", "data_warnings"}
    assert len(out["needs_attention"]) == 1
    assert len(out["changed_from_normal"]) == 1
    assert len(out["unresolved_items"]) == 1
    assert len(out["data_warnings"]) >= 1


def test_import_data_trust_view_signals_include_summary_warning():
    cards = interpret_import_data_trust_view_signals(
        import_summary={"days": 1, "emp_count": 7, "below": 2, "risks": 1},
        goal_status=[],
        today=date(2026, 4, 9),
    )

    assert cards
    assert cards[0].insight_kind == "suspicious_import_data"
    assert "minimum trend window" in cards[0].compared_to_what.lower()


def test_employee_detail_view_signals_builds_follow_up_and_outcome_cards():
    action_rows = [
        {
            "id": "a-2",
            "employee_id": "E3",
            "employee_name": "Casey",
            "department": "Dock",
            "follow_up_due_at": "2026-04-09",
            "_queue_status": "due_today",
            "baseline_uph": 48,
            "latest_uph": 50,
        }
    ]

    cards = interpret_employee_detail_view_signals(action_rows=action_rows, today=date(2026, 4, 9))

    assert len(cards) == 2
    assert all(card.drill_down.screen in {"today", "employee_detail"} for card in cards)
    assert {card.insight_kind for card in cards} == {"follow_up_due", "post_activity_outcome"}


def test_team_process_view_signals_builds_below_expected_cards():
    goal_status = [
        {
            "EmployeeID": "E7",
            "Employee": "Drew",
            "Department": "Pack",
            "Average UPH": 45,
            "Target UPH": 57,
            "trend": "below_expected",
            "change_pct": -8.0,
            "goal_status": "below_goal",
        }
    ]

    cards = interpret_team_process_view_signals(goal_status=goal_status, today=date(2026, 4, 9))

    assert len(cards) == 1
    assert cards[0].insight_kind == "below_expected_performance"
    assert cards[0].validate() == []


def test_below_expected_includes_workload_volume_context_when_available():
    row = {
        "EmployeeID": "E11",
        "Employee": "Jordan",
        "Department": "Pack",
        "Average UPH": 48,
        "Target UPH": 60,
        "Total Units": 420,
        "Hours Worked": 8,
        "trend": "down",
        "goal_status": "below_goal",
    }

    card = interpret_below_expected_performance(row=row, today=date(2026, 4, 9))

    assert "workload volume" in card.compared_to_what.lower()
    assert "observed workload" in card.workload_context.volume_note.lower()
    assert card.data_completeness.status == "complete"


def test_changed_from_normal_marks_workload_fields_missing_when_unavailable():
    row = {
        "EmployeeID": "E12",
        "Employee": "Riley",
        "Department": "Dock",
        "Average UPH": 52,
        "Target UPH": 58,
        "trend": "down",
        "change_pct": -7.4,
    }

    card = interpret_changed_from_normal(row=row, today=date(2026, 4, 9))

    assert "workload volume fields are incomplete" in card.compared_to_what.lower()
    assert "workload-volume context is best effort" in card.data_completeness.summary.lower()


def test_low_data_signal_compact_output_is_minimal():
    row = {
        "EmployeeID": "E12",
        "Employee": "Riley",
        "Department": "Dock",
        "Average UPH": 0,
        "Target UPH": 0,
        "trend": "insufficient_data",
        "change_pct": 0,
    }

    card = interpret_changed_from_normal(row=row, today=date(2026, 4, 9))
    compact = card.metadata.get("compact_lines") or {}

    assert compact.get("line_2") == "Not enough history yet"
    assert compact.get("line_3") == "Only 1 recent record(s) available"
    assert compact.get("line_4") == "Observed: Apr 8"
    assert compact.get("line_5") == "Low confidence"
    assert compact.get("line_1") == ""
    assert compact.get("expanded_line") == ""


def test_below_expected_low_history_uses_current_snapshot_compact_output():
    row = {
        "EmployeeID": "E12",
        "Employee": "Riley",
        "Department": "Dock",
        "Average UPH": 52,
        "Target UPH": 58,
        "trend": "down",
        "goal_status": "below_goal",
    }

    card = interpret_below_expected_performance(row=row, today=date(2026, 4, 9))
    compact = card.metadata.get("compact_lines") or {}

    assert compact.get("line_1") == "Riley · Dock"
    assert compact.get("line_2") == "Below expected pace"
    assert compact.get("line_3") == "Observed: Apr 8 (52.0 UPH)"
    assert compact.get("line_4") == "Compared to: Apr 3–Apr 7 avg (58.0 UPH)"
    assert compact.get("line_5") == "Confidence: High"
    assert compact.get("expanded_line") == ""
