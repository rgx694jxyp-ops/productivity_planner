from datetime import date

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.signal_formatting_service import (
    format_comparison_line,
    format_confidence_line,
    format_observed_line,
    format_signal_label,
    get_signal_display_mode,
    is_signal_display_eligible,
    SignalDisplayMode,
)


def _sample_signal() -> DisplaySignal:
    return DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=45.0,
        confidence=SignalConfidence.HIGH,
        data_completeness=None,
        flags={},
    )


def test_signal_formatting_full_signal_lines():
    signal = _sample_signal()

    assert format_signal_label(signal) == "Below expected pace"
    assert format_observed_line(signal) == "Observed: 2026-04-11 (38.1 UPH)"
    assert format_comparison_line(signal) == "Compared to: 2026-04-06-2026-04-10 avg (45.0 UPH)"
    assert format_confidence_line(signal) == "Confidence: High"


def test_signal_formatting_low_data_fallbacks_are_clean():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=date(2026, 4, 11),
        observed_value=None,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )

    assert format_signal_label(signal) == "Not enough history yet"
    assert format_observed_line(signal) == ""
    assert format_comparison_line(signal) == ""
    assert format_confidence_line(signal) == "Confidence: Low"


def test_signal_display_mode_full_when_observed_and_comparison_exist():
    signal = _sample_signal()
    assert get_signal_display_mode(signal) == SignalDisplayMode.FULL


def test_signal_display_mode_partial_when_no_comparison():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.MEDIUM,
        data_completeness=None,
        flags={},
    )
    assert get_signal_display_mode(signal) == SignalDisplayMode.PARTIAL
    assert format_signal_label(signal) == "Limited data available"
    assert format_observed_line(signal) == "Observed: 2026-04-11"
    assert format_confidence_line(signal) == "Confidence: Low"


def test_signal_display_mode_low_data_when_observed_missing():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=date(2026, 4, 11),
        observed_value=None,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )
    assert get_signal_display_mode(signal) == SignalDisplayMode.LOW_DATA
    assert format_signal_label(signal) == "Not enough history yet"
    assert format_observed_line(signal) == ""
    assert format_confidence_line(signal) == "Confidence: Low"


def test_signal_display_eligible_full_signal_passes():
    signal = _sample_signal()
    assert is_signal_display_eligible(signal) is True


def test_signal_display_eligible_partial_signal_passes():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )
    assert is_signal_display_eligible(signal) is True


def test_signal_display_eligible_low_data_allowed_case_passes():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=date(2026, 4, 11),
        observed_value=None,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )
    assert is_signal_display_eligible(signal, allow_low_data_case=True) is True


def test_signal_display_eligible_low_data_disallowed_case_fails():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=date(2026, 4, 11),
        observed_value=None,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )
    assert is_signal_display_eligible(signal, allow_low_data_case=False) is False


def test_signal_display_eligible_system_artifact_flag_fails():
    signal = _sample_signal()
    flagged = DisplaySignal(
        employee_name=signal.employee_name,
        process=signal.process,
        signal_label=signal.signal_label,
        observed_date=signal.observed_date,
        observed_value=signal.observed_value,
        comparison_start_date=signal.comparison_start_date,
        comparison_end_date=signal.comparison_end_date,
        comparison_value=signal.comparison_value,
        confidence=signal.confidence,
        data_completeness=signal.data_completeness,
        flags={"system_artifact": True},
    )
    assert is_signal_display_eligible(flagged) is False
