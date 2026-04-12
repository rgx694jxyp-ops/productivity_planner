from datetime import date

import pytest

from domain.display_signal import DisplaySignal, DisplaySignalState, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.daily_snapshot_service import _confidence_label as daily_confidence_label
from services.display_signal_factory import build_display_signal
from services.employee_detail_service import _confidence_label as employee_confidence_label
from services.signal_formatting_service import (
    SignalDisplayMode,
    format_confidence_line,
    format_signal_label,
    get_signal_display_mode,
    is_display_signal_eligible,
)
from services.signal_interpretation_service import derive_confidence_from_coverage_policy, interpret_follow_up_due
from services.team_process_service import _confidence_label as team_confidence_label
from services.today_view_model_service import build_today_queue_view_model


def _build_metric_signal(*, usable_points: int, confidence: str = "high"):
    return build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.0,
        comparison_start_date=date(2026, 4, 9),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        usable_points=usable_points,
        minimum_trend_points=3,
        confidence=confidence,
        today=date(2026, 4, 11),
    )


@pytest.mark.parametrize(
    "usable_points,expected_state,expected_mode",
    [
        (1, DisplaySignalState.CURRENT, SignalDisplayMode.CURRENT_STATE),
        (2, DisplaySignalState.EARLY_TREND, SignalDisplayMode.FULL),
        (3, DisplaySignalState.STABLE_TREND, SignalDisplayMode.FULL),
    ],
)
def test_contract_minimum_data_ladder_states(usable_points, expected_state, expected_mode):
    signal = _build_metric_signal(usable_points=usable_points, confidence="high")

    assert signal.state == expected_state
    assert get_signal_display_mode(signal) == expected_mode


def test_contract_minimum_data_ladder_full_signal_is_eligible_at_three_plus_points():
    signal = _build_metric_signal(usable_points=3, confidence="high")

    assert signal.state == DisplaySignalState.STABLE_TREND
    assert get_signal_display_mode(signal) == SignalDisplayMode.FULL
    assert is_display_signal_eligible(signal, allow_low_data_case=False, min_confidence_for_full_or_partial="medium") is True


def test_contract_today_queue_can_include_signal_that_fails_strict_display(monkeypatch):
    same_signal = DisplaySignal(
        employee_id="E1",
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=30.0,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=40.0,
        confidence=SignalConfidence.LOW,
        state=DisplaySignalState.STABLE_TREND,
        data_completeness=None,
        flags={},
    )

    assert is_display_signal_eligible(same_signal, allow_low_data_case=False, min_confidence_for_full_or_partial="medium") is False

    item = AttentionItem(
        employee_id="E1",
        process_name="Receiving",
        attention_score=20,
        attention_tier="low",
        attention_reasons=["contract test"],
        attention_summary="contract test",
        factors_applied=[],
        snapshot={"employee_id": "E1", "process_name": "Receiving"},
    )
    summary = AttentionSummary(ranked_items=[item], is_healthy=False, healthy_message="", suppressed_count=0, total_evaluated=1)

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: same_signal)

    queue_vm = build_today_queue_view_model(attention=summary, suppressed_cards=[], today=date(2026, 4, 11))

    assert not queue_vm.suppressed
    assert len(queue_vm.secondary_cards) == 1
    assert queue_vm.secondary_cards[0].employee_id == "E1"


@pytest.mark.parametrize(
    "queue_status_a,queue_status_b",
    [
        ("overdue", "due_today"),
        ("overdue", "pending"),
        ("due_today", "pending"),
    ],
)
def test_contract_confidence_is_not_boosted_by_urgency_status(queue_status_a, queue_status_b):
    base_action = {
        "id": "A1",
        "employee_id": "E1",
        "employee_name": "Alex",
        "department": "Receiving",
        "follow_up_due_at": "2026-04-11",
        "status": "open",
    }

    card_a = interpret_follow_up_due(action={**base_action, "_queue_status": queue_status_a}, today=date(2026, 4, 11))
    card_b = interpret_follow_up_due(action={**base_action, "_queue_status": queue_status_b}, today=date(2026, 4, 11))

    assert card_a.confidence.level == card_b.confidence.level
    assert card_a.confidence.score == card_b.confidence.score


@pytest.mark.parametrize(
    "coverage_ratio,included_count,expected_level",
    [
        (0.8, 8, "high"),
        (0.5, 5, "medium"),
        (0.2, 2, "low"),
    ],
)
def test_contract_confidence_depends_on_evidence_inputs_only(coverage_ratio, included_count, expected_level):
    confidence = derive_confidence_from_coverage_policy(
        coverage_ratio=coverage_ratio,
        included_count=included_count,
        high_min_coverage=0.7,
        high_min_count=7,
        medium_min_coverage=0.4,
        medium_min_count=4,
        allow_high=True,
    )

    assert confidence.level == expected_level


@pytest.mark.parametrize(
    "signal,expected_mode,expected_label,expected_confidence_line",
    [
        (
            DisplaySignal(
                employee_name="Alex",
                process="Receiving",
                signal_label=SignalLabel.BELOW_EXPECTED_PACE,
                observed_date=date(2026, 4, 11),
                observed_value=30.0,
                comparison_start_date=date(2026, 4, 6),
                comparison_end_date=date(2026, 4, 10),
                comparison_value=40.0,
                confidence=SignalConfidence.HIGH,
                state=DisplaySignalState.STABLE_TREND,
                data_completeness=None,
                flags={},
            ),
            SignalDisplayMode.FULL,
            "Below expected pace",
            "Confidence: High",
        ),
        (
            DisplaySignal(
                employee_name="Alex",
                process="Receiving",
                signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
                observed_date=date(2026, 4, 11),
                observed_value=35.0,
                comparison_start_date=date(2026, 4, 9),
                comparison_end_date=date(2026, 4, 10),
                comparison_value=40.0,
                confidence=SignalConfidence.MEDIUM,
                state=DisplaySignalState.EARLY_TREND,
                data_completeness=None,
                flags={},
            ),
            SignalDisplayMode.FULL,
            "Lower than recent pace",
            "Confidence: Medium",
        ),
        (
            DisplaySignal(
                employee_name="Alex",
                process="Receiving",
                signal_label=SignalLabel.LOW_DATA,
                observed_date=date(2026, 4, 11),
                observed_value=None,
                comparison_start_date=None,
                comparison_end_date=None,
                comparison_value=None,
                confidence=SignalConfidence.LOW,
                state=DisplaySignalState.LOW_DATA,
                data_completeness=None,
                flags={},
            ),
            SignalDisplayMode.LOW_DATA,
            "Not enough history yet",
            "Low confidence",
        ),
    ],
)
def test_contract_confidence_and_maturity_copy_matrix(signal, expected_mode, expected_label, expected_confidence_line):
    assert get_signal_display_mode(signal) == expected_mode
    assert format_signal_label(signal) == expected_label
    assert format_confidence_line(signal) == expected_confidence_line


@pytest.mark.parametrize(
    "coverage_ratio,included_count,expected_uph,affected_people,expected_daily,expected_employee,expected_team",
    [
        (0.5, 5, 100.0, 3, "Medium", "Medium", "Medium"),
        (0.2, 2, 100.0, 3, "Low", "Low", "Low"),
    ],
)
def test_contract_duplicate_confidence_consistency_without_context_gate(
    coverage_ratio,
    included_count,
    expected_uph,
    affected_people,
    expected_daily,
    expected_employee,
    expected_team,
):
    assert daily_confidence_label(coverage_ratio, included_count, expected_uph)[0] == expected_daily
    assert employee_confidence_label(coverage_ratio, included_count) == expected_employee
    assert team_confidence_label(coverage_ratio, included_count, affected_people) == expected_team


def test_contract_duplicate_confidence_explicit_context_gates_are_intentional():
    # Daily gate: high requires configured expected pace.
    assert daily_confidence_label(0.8, 8, 0.0)[0] == "Medium"

    # Team gate: high requires at least two affected people.
    assert team_confidence_label(0.8, 8, 1) == "Medium"

    # Baseline policy without those gates is still high.
    assert employee_confidence_label(0.8, 8) == "High"
