from datetime import date

from domain.display_signal import SignalLabel
from services.daily_snapshot_service import build_daily_employee_snapshots
from services.display_signal_factory import build_display_signal
from services.signal_formatting_service import (
    SignalDisplayMode,
    format_comparison_line,
    format_confidence_line,
    format_observed_line,
    format_signal_label,
    get_signal_display_mode,
    is_signal_display_eligible,
)
from services.plain_language_service import signal_wording


def _assert_clean_text(*values: str) -> None:
    for value in values:
        text = str(value or "").lower()
        assert "n/a" not in text
        assert "()" not in text


def test_edge_missing_observed_value_uses_low_data_fallback():
    signal = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=None,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=44.0,
        confidence="medium",
        today=date(2026, 4, 11),
    )

    assert get_signal_display_mode(signal) == SignalDisplayMode.LOW_DATA
    assert format_signal_label(signal) == "Not enough history yet"
    assert format_confidence_line(signal) == "Confidence: Low"
    _assert_clean_text(format_signal_label(signal), format_observed_line(signal), format_comparison_line(signal), format_confidence_line(signal))


def test_edge_missing_comparison_value_uses_partial_fallback():
    signal = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.4,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert get_signal_display_mode(signal) == SignalDisplayMode.PARTIAL
    assert format_signal_label(signal) == signal_wording("not_enough_history_yet")
    assert format_observed_line(signal) == "Observed: Apr 11"
    assert format_confidence_line(signal) == "Confidence: Low"
    assert format_comparison_line(signal) == ""
    _assert_clean_text(format_signal_label(signal), format_observed_line(signal), format_confidence_line(signal))


def test_edge_invalid_comparison_dates_downgrades_to_low_data():
    signal = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.4,
        comparison_start_date=date(2026, 4, 12),
        comparison_end_date=date(2026, 4, 13),
        comparison_value=44.0,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert get_signal_display_mode(signal) == SignalDisplayMode.LOW_DATA
    assert format_signal_label(signal) == "Not enough history yet"


def test_edge_only_one_to_two_points_keeps_low_confidence_signal_behavior():
    snapshots = build_daily_employee_snapshots(
        activity_records=[
            {
                "employee_id": "E1",
                "process_name": "Receiving",
                "activity_date": "2026-04-10",
                "productivity_value": 15.0,
                "units": 120,
                "hours": 8,
                "data_quality_status": "complete",
            },
            {
                "employee_id": "E1",
                "process_name": "Receiving",
                "activity_date": "2026-04-11",
                "productivity_value": 14.0,
                "units": 112,
                "hours": 8,
                "data_quality_status": "complete",
            },
        ],
        tenant_id="tenant-test",
        lookback_days=14,
        comparison_days=5,
    )

    latest = snapshots[-1]
    assert str(latest.get("confidence_label") or "").lower() == "low"

    signal = build_display_signal(
        employee_name="E1",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=latest.get("recent_average_uph"),
        comparison_value=latest.get("prior_average_uph") if float(latest.get("prior_average_uph") or 0) > 0 else None,
        confidence=latest.get("confidence_label"),
        today=date(2026, 4, 11),
    )

    assert get_signal_display_mode(signal) in {SignalDisplayMode.PARTIAL, SignalDisplayMode.LOW_DATA}
    assert format_confidence_line(signal) == "Confidence: Low"


def test_edge_duplicate_rows_are_collapsed_in_snapshot_generation():
    snapshots = build_daily_employee_snapshots(
        activity_records=[
            {
                "employee_id": "E2",
                "process_name": "Packing",
                "activity_date": "2026-04-10",
                "productivity_value": 12.0,
                "units": 96,
                "hours": 8,
                "data_quality_status": "complete",
            },
            {
                "employee_id": "E2",
                "process_name": "Packing",
                "activity_date": "2026-04-10",
                "productivity_value": 12.0,
                "units": 96,
                "hours": 8,
                "data_quality_status": "complete",
            },
            {
                "employee_id": "E2",
                "process_name": "Packing",
                "activity_date": "2026-04-11",
                "productivity_value": 13.0,
                "units": 104,
                "hours": 8,
                "data_quality_status": "complete",
            },
        ],
        tenant_id="tenant-test",
        lookback_days=14,
        comparison_days=5,
    )

    dates = [row.get("snapshot_date") for row in snapshots]
    assert sorted(set(dates)) == ["2026-04-10", "2026-04-11"]
    assert len(snapshots) == 2


def test_edge_low_confidence_full_signal_fails_eligibility_by_default_threshold():
    signal = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.0,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=45.0,
        confidence="low",
        today=date(2026, 4, 11),
    )

    assert get_signal_display_mode(signal) == SignalDisplayMode.FULL
    assert is_signal_display_eligible(signal) is False


def test_edge_mixed_valid_and_invalid_rows_filter_cleanly():
    rows = [
        {
            "employee_name": "Alex",
            "process": "Receiving",
            "signal_label": "below_expected_pace",
            "observed_date": date(2026, 4, 11),
            "observed_value": 38.0,
            "comparison_start_date": date(2026, 4, 6),
            "comparison_end_date": date(2026, 4, 10),
            "comparison_value": 45.0,
            "confidence": "high",
        },
        {
            "employee_name": "n/a",
            "process": "Receiving",
            "signal_label": "below_expected_pace",
            "observed_date": date(2026, 4, 11),
            "observed_value": 38.0,
            "comparison_value": 45.0,
            "confidence": "high",
        },
        {
            "employee_name": "Taylor",
            "process": "Packing",
            "signal_label": "lower_than_recent_pace",
            "observed_date": date(2026, 4, 11),
            "observed_value": 39.2,
            "comparison_value": None,
            "confidence": "medium",
        },
    ]

    built = [
        build_display_signal(
            employee_name=row.get("employee_name"),
            process=row.get("process"),
            signal_label=row.get("signal_label"),
            observed_date=row.get("observed_date"),
            observed_value=row.get("observed_value"),
            comparison_start_date=row.get("comparison_start_date"),
            comparison_end_date=row.get("comparison_end_date"),
            comparison_value=row.get("comparison_value"),
            confidence=row.get("confidence"),
            today=date(2026, 4, 11),
        )
        for row in rows
    ]

    eligible = [signal for signal in built if is_signal_display_eligible(signal, allow_low_data_case=False)]
    assert len(eligible) == 2
    for signal in eligible:
        _assert_clean_text(format_signal_label(signal), format_observed_line(signal), format_comparison_line(signal), format_confidence_line(signal))


def test_edge_no_data_returns_empty_renderable_set():
    rows: list[dict] = []
    built = [
        build_display_signal(
            employee_name=row.get("employee_name"),
            process=row.get("process"),
            signal_label=row.get("signal_label"),
            observed_date=row.get("observed_date"),
            observed_value=row.get("observed_value"),
            comparison_value=row.get("comparison_value"),
            confidence=row.get("confidence"),
            today=date(2026, 4, 11),
        )
        for row in rows
    ]

    assert built == []


def test_signal_formatting_consistency_across_modes():
    full = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.0,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=45.0,
        confidence="high",
        today=date(2026, 4, 11),
    )
    partial = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="lower_than_recent_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.0,
        comparison_value=None,
        confidence="medium",
        today=date(2026, 4, 11),
    )

    assert format_observed_line(full).startswith("Observed:")
    assert format_observed_line(partial).startswith("Observed:")
    assert format_confidence_line(full).startswith("Confidence:")
    assert format_confidence_line(partial).startswith("Confidence:")


def test_comparison_labeling_is_clear_for_range_and_baseline():
    ranged = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.0,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=45.0,
        confidence="high",
        today=date(2026, 4, 11),
    )
    baseline = build_display_signal(
        employee_name="Alex",
        process="Receiving",
        signal_label="below_expected_pace",
        observed_date=date(2026, 4, 11),
        observed_value=38.0,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=45.0,
        confidence="high",
        today=date(2026, 4, 11),
    )

    assert format_comparison_line(ranged).startswith("Compared to:")
    assert "avg" in format_comparison_line(ranged)
    assert format_comparison_line(baseline).startswith("Compared to:")
    assert "baseline" in format_comparison_line(baseline)
