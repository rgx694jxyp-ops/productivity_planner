from datetime import date

from services.signal_interpretation_service import (
    interpret_below_expected_performance,
    interpret_repeated_decline,
)
from services.signal_quality_service import evaluate_signal_quality, rank_and_filter_signals


def test_quality_suppresses_weak_incomplete_signal():
    weak_row = {
        "EmployeeID": "E1",
        "Employee": "Alex",
        "Department": "Picking",
        "Average UPH": 0,
        "Target UPH": 0,
        "trend": "unknown",
        "goal_status": "unknown",
    }
    card = interpret_below_expected_performance(row=weak_row, today=date(2026, 4, 9))

    decision = evaluate_signal_quality(card)
    assert decision.include is False
    assert decision.tier == "weak"


def test_quality_promotes_repeated_complete_pattern():
    action = {
        "id": "a-99",
        "employee_id": "E9",
        "employee_name": "Casey",
        "department": "Receiving",
        "_short_reason": "Repeated decline pattern",
        "baseline_uph": 48,
        "latest_uph": 42,
    }
    card = interpret_repeated_decline(action=action, today=date(2026, 4, 9))

    decision = evaluate_signal_quality(card)
    assert decision.include is True
    assert decision.tier in {"usable", "strong"}


def test_rank_and_filter_keeps_stronger_first():
    strong_row = {
        "EmployeeID": "E2",
        "Employee": "Blair",
        "Department": "Pack",
        "Average UPH": 45,
        "Target UPH": 57,
        "trend": "down",
        "goal_status": "below_goal",
    }
    weak_row = {
        "EmployeeID": "E3",
        "Employee": "Drew",
        "Department": "Pack",
        "Average UPH": 0,
        "Target UPH": 0,
        "trend": "unknown",
        "goal_status": "unknown",
    }
    strong_card = interpret_below_expected_performance(row=strong_row, today=date(2026, 4, 9))
    weak_card = interpret_below_expected_performance(row=weak_row, today=date(2026, 4, 9))

    ranked = rank_and_filter_signals([weak_card, strong_card])
    assert len(ranked) == 1
    assert ranked[0].insight_id == strong_card.insight_id
    assert ranked[0].metadata.get("quality_score", 0) >= 45
