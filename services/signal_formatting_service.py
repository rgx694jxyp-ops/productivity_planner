"""Centralized formatting for user-facing signal strings."""

from __future__ import annotations

from enum import Enum

from domain.display_signal import DisplaySignal, SignalLabel


class SignalDisplayMode(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    LOW_DATA = "LOW_DATA"


_SYSTEM_ARTIFACT_LABELS = {
    "recently surfaced",
    "status",
    "system",
    "artifact",
}


def is_signal_display_eligible(
    signal: DisplaySignal,
    *,
    allow_low_data_case: bool = True,
    min_confidence_for_full_or_partial: str = "medium",
) -> bool:
    """Return True only for meaningful, display-safe signals.

    Rules enforced:
    - Valid signal label (non-artifact/status-only)
    - Valid data OR valid low-data fallback
    - Valid date relationships
    - Minimum confidence for FULL/PARTIAL, or explicit low-data allow
    - Suppress obvious system artifacts
    """
    label_text = format_signal_label(signal).strip().lower()
    if not label_text or label_text in _SYSTEM_ARTIFACT_LABELS:
        return False

    mode = get_signal_display_mode(signal)

    # Date ordering safety guard (DisplaySignal already validates this, but keep
    # this check at display boundary as defense-in-depth).
    if signal.comparison_start_date is not None and signal.comparison_start_date >= signal.observed_date:
        return False
    if signal.comparison_end_date is not None and signal.comparison_end_date >= signal.observed_date:
        return False

    # Guard obvious system-artifact flags.
    if bool((signal.flags or {}).get("system_artifact")):
        return False

    confidence_rank = {
        "low": 1,
        "medium": 2,
        "high": 3,
    }
    min_rank = confidence_rank.get(str(min_confidence_for_full_or_partial or "medium").strip().lower(), 2)
    signal_rank = confidence_rank.get(signal.confidence.value, 1)

    if mode == SignalDisplayMode.LOW_DATA:
        return bool(allow_low_data_case) and signal.signal_label == SignalLabel.LOW_DATA

    if mode == SignalDisplayMode.PARTIAL:
        if signal.observed_value is None:
            return False
        # Partial mode is valid readable fallback; keep confidence gate light.
        return True

    # FULL mode
    if signal.observed_value is None or signal.comparison_value is None:
        return False
    if signal_rank < min_rank:
        return False
    return True


def get_signal_display_mode(signal: DisplaySignal) -> SignalDisplayMode:
    """Return strict display mode for consistent fallback behavior.

    Rules:
    - LOW_DATA: no usable observed data
    - PARTIAL: observed data exists but no comparison basis
    - FULL: observed + comparison are both present
    """
    if signal.signal_label == SignalLabel.LOW_DATA or signal.observed_value is None:
        return SignalDisplayMode.LOW_DATA
    if signal.comparison_value is None:
        return SignalDisplayMode.PARTIAL
    return SignalDisplayMode.FULL


def format_signal_label(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode == SignalDisplayMode.LOW_DATA:
        return "Not enough history yet"
    if mode == SignalDisplayMode.PARTIAL:
        return "Limited data available"

    if signal.signal_label == SignalLabel.BELOW_EXPECTED_PACE:
        return "Below expected pace"
    if signal.signal_label == SignalLabel.LOWER_THAN_RECENT_PACE:
        return "Lower than recent pace"
    if signal.signal_label == SignalLabel.INCONSISTENT_PACE:
        return "Inconsistent pace"
    if signal.signal_label == SignalLabel.IMPROVING_PACE:
        return "Improving pace"
    if signal.signal_label == SignalLabel.FOLLOW_UP_OVERDUE:
        return "Follow-up overdue"
    if signal.signal_label == SignalLabel.FOLLOW_UP_DUE_TODAY:
        return "Follow-up due today"
    if signal.signal_label == SignalLabel.UNRESOLVED_ISSUE:
        return "Unresolved issue"
    if signal.signal_label == SignalLabel.REPEATED_PATTERN:
        return "Repeated pattern"
    return "Limited data available"


def format_observed_line(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode == SignalDisplayMode.LOW_DATA:
        return ""
    if mode == SignalDisplayMode.PARTIAL:
        return f"Observed: {signal.observed_date.isoformat()}"
    return f"Observed: {signal.observed_date.isoformat()} ({signal.observed_value:.1f} UPH)"


def format_comparison_line(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode != SignalDisplayMode.FULL:
        return ""
    if signal.comparison_value is None:
        return ""
    if signal.comparison_start_date is not None and signal.comparison_end_date is not None:
        return (
            f"Compared to: {signal.comparison_start_date.isoformat()}-{signal.comparison_end_date.isoformat()} "
            f"avg ({signal.comparison_value:.1f} UPH)"
        )
    return f"Compared to: baseline ({signal.comparison_value:.1f} UPH)"


def format_confidence_line(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode in {SignalDisplayMode.LOW_DATA, SignalDisplayMode.PARTIAL}:
        return "Confidence: Low"
    return f"Confidence: {signal.confidence.value.title()}"
