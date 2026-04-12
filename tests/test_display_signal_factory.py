from datetime import date

from domain.display_signal import DisplayConfidenceLevel, DisplaySignalState, SignalLabel
from services.display_signal_factory import build_display_signal


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


def test_current_state_generated_when_history_under_3_points():
    signal = _current_candidate_signal(usable_points=2)

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
