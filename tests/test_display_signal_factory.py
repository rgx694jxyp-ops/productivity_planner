from datetime import date

from domain.display_signal import SignalLabel
from services.display_signal_factory import build_display_signal


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
