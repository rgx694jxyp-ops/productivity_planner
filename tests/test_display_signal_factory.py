from datetime import date

from domain.display_signal import DisplayConfidenceLevel, DisplaySignalState, SignalLabel
from services.attention_scoring_service import AttentionItem
from services.display_signal_factory import (
    build_display_signal,
    build_display_signal_from_attention_item,
    build_display_signal_from_employee_detail_context,
)
from services.signal_formatting_service import SignalDisplayMode, format_confidence_line, get_signal_display_mode


def _current_candidate_signal(*, usable_points: int = 2):
    return build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        observed_unit="UPH",
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=45.0,
        usable_points=usable_points,
        confidence="high",
        today=date(2026, 4, 11),
    )


def _pattern_signal(*, supporting_text: list[str] | None = None):
    return build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        observed_unit="UPH",
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        usable_points=5,
        minimum_trend_points=5,
        pattern_count=3,
        pattern_window_label="this week",
        supporting_text=supporting_text or ["Repeated decline observed across recent trend points (3 down classifications)."],
        confidence="high",
        today=date(2026, 4, 11),
    )


def test_build_display_signal_accepts_valid_full_signal():
    signal = build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=45.0,
        confidence="high",
        data_completeness="complete",
        flags={"repeat": True},
        today=date(2026, 4, 11),
    )

    assert signal.signal_label == SignalLabel.BELOW_EXPECTED_PACE
    assert signal.observed_value == 38.1
    assert signal.comparison_value == 45.0
    assert signal.flags.get("repeat") is True


def test_build_display_signal_downgrades_when_required_fields_missing():
    signal = build_display_signal(
        employee_name="",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_value=45.0,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert signal.signal_label == SignalLabel.LOW_DATA
    assert signal.flags.get("downgraded_low_data") is True


def test_build_display_signal_downgrades_when_placeholder_values_provided():
    signal = build_display_signal(
        employee_name="n/a",
        process="undefined",
        signal_label="below_expected_pace",
        observed_date="2026-04-11",
        observed_value=38.1,
        comparison_value=45.0,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert signal.signal_label == SignalLabel.LOW_DATA


def test_build_display_signal_downgrades_when_comparison_date_not_before_observed_date():
    signal = build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 11),
        comparison_end_date=date(2026, 4, 12),
        comparison_value=45.0,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert signal.signal_label == SignalLabel.LOW_DATA


def test_build_display_signal_allows_partial_when_observed_has_no_comparison_value():
    signal = build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=None,
        confidence="medium",
        today=date(2026, 4, 11),
    )

    assert signal.signal_label == SignalLabel.LOWER_THAN_RECENT_PACE
    assert signal.observed_value == 38.1
    assert signal.comparison_value is None


def test_current_state_generated_with_one_usable_point():
    signal = _current_candidate_signal(usable_points=1)

    assert signal.state == DisplaySignalState.CURRENT
    assert signal.primary_label == "Current pace"
    assert signal.observed_value == 38.1
    assert signal.observed_unit == "UPH"
    assert signal.observed_date == date(2026, 4, 11)
    assert signal.confidence_level == DisplayConfidenceLevel.LOW
    assert signal.is_low_data is True
    assert signal.comparison_value is None
    assert signal.comparison_start_date is None
    assert signal.comparison_end_date is None


def test_current_state_has_no_comparison_fields():
    signal = _current_candidate_signal(usable_points=1)

    assert signal.state == DisplaySignalState.CURRENT
    assert signal.comparison_value is None
    assert signal.comparison_start_date is None
    assert signal.comparison_end_date is None


def test_early_trend_generated_with_minimal_valid_comparison():
    signal = build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        observed_unit="UPH",
        comparison_start_date=date(2026, 4, 9),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        usable_points=3,
        minimum_trend_points=5,
        confidence="low",
        today=date(2026, 4, 11),
    )

    assert signal.state == DisplaySignalState.EARLY_TREND
    assert signal.primary_label == "Lower than recent pace"
    assert signal.confidence_level == DisplayConfidenceLevel.LOW
    assert signal.comparison_start_date == date(2026, 4, 9)
    assert signal.comparison_end_date == date(2026, 4, 10)
    assert signal.comparison_value == 42.0


def test_stable_trend_generated_with_sufficient_history():
    signal = build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        observed_unit="UPH",
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        usable_points=5,
        minimum_trend_points=5,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert signal.state == DisplaySignalState.STABLE_TREND
    assert signal.primary_label == "Lower than recent pace"
    assert signal.confidence_level == DisplayConfidenceLevel.HIGH
    assert signal.comparison_start_date == date(2026, 4, 6)
    assert signal.comparison_end_date == date(2026, 4, 10)
    assert signal.comparison_value == 42.0


def test_pattern_props_populated_when_signal_repeats():
    signal = _pattern_signal()

    assert signal.state == DisplaySignalState.STABLE_TREND
    assert signal.pattern_count == 3
    assert signal.pattern_window_label == "this week"
    assert signal.supporting_text == ["Seen 3 times this week"]


def test_pattern_supporting_text_added_once_only():
    signal = _pattern_signal(supporting_text=["Seen 3 times this week", "Repeated decline observed across recent trend points."])

    assert signal.supporting_text == ["Seen 3 times this week"]


def test_low_data_used_when_no_valid_current_or_comparison_signal_exists():
    signal = build_display_signal(
        employee_name="Alex Torres",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=None,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=45.0,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert signal.signal_label == SignalLabel.LOW_DATA
    assert signal.state == DisplaySignalState.LOW_DATA
    assert signal.is_low_data is True


def test_attention_item_uses_prior_average_baseline_before_target_baseline():
    item = AttentionItem(
        employee_id="EMP1",
        process_name="Picking",
        attention_score=81,
        attention_tier="high",
        attention_reasons=["Declining pace"],
        attention_summary="Recent pace dropped.",
        factors_applied=[],
        snapshot={
            "snapshot_date": "2026-04-12",
            "recent_average_uph": 52.0,
            "prior_average_uph": 60.0,
            "expected_uph": 40.0,
            "Record Count": 5,
            "confidence_label": "High",
            "data_completeness_status": "partial",
            "repeat_count": 0,
            "trend_state": "declining",
        },
    )

    signal = build_display_signal_from_attention_item(item=item, today=date(2026, 4, 12))

    assert signal.comparison_value == 60.0
    assert get_signal_display_mode(signal) == SignalDisplayMode.FULL
    assert format_confidence_line(signal) == "Confidence: High"


def test_employee_detail_signal_uses_has_pattern_flag_for_repeat_context():
    """Protects against repeat-pattern drift when detail context uses has_pattern."""
    detail_context = {
        "employee_id": "E7",
        "trend_state": "declining",
        "confidence_label": "Medium",
        "signal_summary": {
            "signal_state": "STABLE_TREND",
            "data_completeness_label": "partial",
        },
        "contributing_periods": {
            "trailing_dates": ["2026-04-10", "2026-04-11"],
            "prior_dates": ["2026-04-08", "2026-04-09"],
        },
        "before_after_summary": {
            "trailing_avg_uph": 42.0,
            "prior_avg_uph": 49.0,
        },
        "pattern_history": {
            "has_pattern": True,
            "repeat_count": 3,
        },
        "why_this_is_showing": {
            "why_now": "Shown now because recent direction is declining.",
        },
    }

    signal = build_display_signal_from_employee_detail_context(
        detail_context=detail_context,
        employee_name="Taylor Reed",
        process="Picking",
    )

    assert signal.flags.get("repeat") is True


def test_employee_detail_signal_supporting_text_includes_compared_to_what():
    """Protects against lost comparison rationale in employee detail explainer lines."""
    detail_context = {
        "employee_id": "E8",
        "trend_state": "declining",
        "confidence_label": "Medium",
        "compared_to_what": "Compared with the prior 5 comparable days and configured target.",
        "signal_summary": {
            "signal_state": "STABLE_TREND",
            "data_completeness_label": "partial",
        },
        "contributing_periods": {
            "trailing_dates": ["2026-04-10", "2026-04-11"],
            "prior_dates": ["2026-04-08", "2026-04-09"],
        },
        "before_after_summary": {
            "trailing_avg_uph": 41.0,
            "prior_avg_uph": 48.0,
        },
        "pattern_history": {
            "has_pattern": False,
            "repeat_count": 0,
        },
        "why_this_is_showing": {
            "why_now": "Shown now because current output is below expected range.",
        },
    }

    signal = build_display_signal_from_employee_detail_context(
        detail_context=detail_context,
        employee_name="Avery Cruz",
        process="Receiving",
    )

    assert any("Compared with the prior 5 comparable days" in line for line in list(signal.supporting_text or []))
