from datetime import date

from domain.display_signal import DisplaySignal, DisplaySignalState, SignalConfidence, SignalLabel
from services.signal_formatting_service import (
    format_comparison_line,
    format_confidence_line,
    format_low_data_collapsed_lines,
    format_low_data_expanded_lines,
    format_observed_line,
    format_signal_label,
    get_signal_display_mode,
    is_signal_display_eligible,
    SignalDisplayMode,
)
from services.plain_language_service import signal_wording


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
    assert format_observed_line(signal) == "Observed: Apr 11 (38.1 UPH)"
    assert format_comparison_line(signal) == "Compared to: Apr 6–Apr 10 avg (45.0 UPH)"
    assert format_confidence_line(signal) == "Confidence: High"


def test_early_trend_renders_short_comparison_window():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 9),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        confidence=SignalConfidence.LOW,
        state=DisplaySignalState.EARLY_TREND,
        primary_label="Lower than recent pace",
        data_completeness=None,
        flags={},
    )

    assert format_signal_label(signal) == "Lower than recent pace"
    assert format_observed_line(signal) == "Observed: Apr 11 (38.1 UPH)"
    assert format_comparison_line(signal) == "Compared to: Apr 9–Apr 10 avg (42.0 UPH)"
    assert format_confidence_line(signal) == "Confidence: Low"


def test_stable_trend_renders_full_comparison_window():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        confidence=SignalConfidence.HIGH,
        state=DisplaySignalState.STABLE_TREND,
        primary_label="Lower than recent pace",
        data_completeness=None,
        flags={},
    )

    assert format_signal_label(signal) == "Lower than recent pace"
    assert format_observed_line(signal) == "Observed: Apr 11 (38.1 UPH)"
    assert format_comparison_line(signal) == "Compared to: Apr 6–Apr 10 avg (42.0 UPH)"
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
    assert format_confidence_line(signal) == "Low confidence"


def test_signal_display_mode_full_when_observed_and_comparison_exist():
    signal = _sample_signal()
    assert get_signal_display_mode(signal) == SignalDisplayMode.FULL


def test_signal_display_mode_current_state_when_no_comparison():
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
    assert get_signal_display_mode(signal) == SignalDisplayMode.CURRENT_STATE
    assert format_signal_label(signal) == "Current pace: 38.1 UPH"
    assert format_observed_line(signal) == "Apr 11"
    assert format_confidence_line(signal) == "Low confidence"


def test_current_state_renders_current_pace_with_date_and_low_confidence():
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.HIGH,
        state=DisplaySignalState.CURRENT,
        primary_label="Current pace",
        observed_unit="UPH",
        is_low_data=True,
        data_completeness=None,
        flags={},
    )

    assert format_signal_label(signal) == "Current pace: 38.1 UPH"
    assert format_observed_line(signal) == "Apr 11"
    assert format_confidence_line(signal) == "Low confidence"


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
    assert format_confidence_line(signal) == "Low confidence"


def test_signal_formatting_uses_canonical_wording_for_core_signals():
    observed_date = date(2026, 4, 11)
    full_kwargs = {
        "employee_name": "Alex",
        "process": "Receiving",
        "observed_date": observed_date,
        "observed_value": 30.0,
        "comparison_start_date": date(2026, 4, 6),
        "comparison_end_date": date(2026, 4, 10),
        "comparison_value": 40.0,
        "confidence": SignalConfidence.HIGH,
        "data_completeness": None,
        "flags": {},
    }

    assert format_signal_label(DisplaySignal(signal_label=SignalLabel.LOWER_THAN_RECENT_PACE, **full_kwargs)) == signal_wording("lower_than_recent_pace")
    assert format_signal_label(DisplaySignal(signal_label=SignalLabel.BELOW_EXPECTED_PACE, **full_kwargs)) == signal_wording("below_expected_pace")
    assert format_signal_label(DisplaySignal(signal_label=SignalLabel.INCONSISTENT_PACE, **full_kwargs)) == signal_wording("inconsistent_performance")
    assert format_signal_label(DisplaySignal(signal_label=SignalLabel.FOLLOW_UP_OVERDUE, **full_kwargs)) == signal_wording("follow_up_not_completed")

    low_data = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=observed_date,
        observed_value=None,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )
    assert format_signal_label(low_data) == signal_wording("not_enough_history_yet")


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


def test_low_data_collapsed_format_is_strict_and_clean():
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

    lines = format_low_data_collapsed_lines(signal)
    assert lines == ["Not enough history yet", "Low confidence"]


def test_low_data_expanded_format_is_strict_and_friendly():
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

    lines = format_low_data_expanded_lines(signal, recent_record_count=2)
    assert lines == ["Only 2 recent record(s) available", "Observed: Apr 11"]


def test_low_data_expanded_format_prefers_sanitized_supporting_text():
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
        supporting_text=[
            "Only 1 recent record(s) available",
            "Low confidence",
            "Missing baseline",
        ],
        data_completeness=None,
        flags={},
    )

    lines = format_low_data_expanded_lines(signal, recent_record_count=3)
    assert lines == ["Only 1 recent record(s) available", "Observed: Apr 11"]


def test_low_data_has_max_two_supporting_lines():
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

    expanded = format_low_data_expanded_lines(signal, recent_record_count=3)
    assert len(expanded) <= 2


def test_low_data_contains_no_system_phrases():
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

    lines = format_low_data_collapsed_lines(signal) + format_low_data_expanded_lines(signal, recent_record_count=1)
    banned = ("system", "artifact", "missing baseline", "insufficient comparison window", "trend reliability", "clear caveats")
    for line in lines:
        text = line.lower()
        for phrase in banned:
            assert phrase not in text
