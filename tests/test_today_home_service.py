from datetime import date

from services.today_home_service import (
    build_today_attention_summary,
    build_today_home_sections,
    is_insight_card_display_eligible,
)
from services.signal_interpretation_service import interpret_suspicious_or_incomplete_data


def test_is_insight_card_display_eligible_rejects_non_meaningful_warning_card():
    card = interpret_suspicious_or_incomplete_data(
        import_summary={"days": 1, "emp_count": 4, "below": 1, "risks": 1},
        today=date(2026, 4, 11),
    )

    assert is_insight_card_display_eligible(card, today=date(2026, 4, 11)) is False


def test_build_today_home_sections_keeps_main_signals_and_suppresses_noise():
    sections = build_today_home_sections(
        queue_items=[],
        goal_status=[
            {
                "EmployeeID": "E1",
                "Employee": "Alex",
                "Department": "Packing",
                "Average UPH": 41,
                "Target UPH": 50,
                "trend": "declining",
                "change_pct": -12.0,
                "goal_status": "below_goal",
            }
        ],
        import_summary={"days": 1, "emp_count": 4, "below": 1, "risks": 1},
        today=date(2026, 4, 11),
    )

    assert len(sections.get("changed_from_normal") or []) == 1
    assert len(sections.get("data_warnings") or []) == 0
    suppressed = sections.get("suppressed_signals") or []
    assert any(item.insight_kind == "suspicious_import_data" for item in suppressed)


def test_build_today_attention_summary_filters_to_eligible_employee_ids():
    summary = build_today_attention_summary(
        goal_status=[
            {
                "EmployeeID": "E1",
                "Department": "Packing",
                "trend": "declining",
                "confidence_label": "high",
                "repeat_count": 0,
                "Target UPH": 50,
                "Average UPH": 40,
            },
            {
                "EmployeeID": "E2",
                "Department": "Packing",
                "trend": "declining",
                "confidence_label": "high",
                "repeat_count": 0,
                "Target UPH": 50,
                "Average UPH": 40,
            },
        ],
        queue_items=[],
        open_exception_rows=[],
        eligible_employee_ids={"E1"},
    )

    assert summary.ranked_items
    assert all(item.employee_id == "E1" for item in summary.ranked_items)


def test_build_today_attention_summary_keeps_low_tier_when_weak_data_mode_enabled():
    summary = build_today_attention_summary(
        goal_status=[
            {
                "EmployeeID": "E9",
                "Department": "Packing",
                "trend": "insufficient_data",
                "confidence_label": "low",
                "repeat_count": 0,
                "Target UPH": 0,
                "Average UPH": 0,
            },
        ],
        queue_items=[],
        open_exception_rows=[],
        weak_data_mode=True,
        max_items=10,
    )

    assert summary.total_evaluated == 1
    assert len(summary.ranked_items) == 1
