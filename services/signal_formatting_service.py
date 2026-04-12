"""Centralized formatting for user-facing signal strings."""

from __future__ import annotations

from datetime import date
from enum import Enum

from domain.display_signal import DisplaySignal, DisplaySignalState, SignalLabel
from services.plain_language_service import signal_wording


class SignalDisplayMode(str, Enum):
    FULL = "FULL"
    CURRENT_STATE = "CURRENT_STATE"
    LOW_DATA = "LOW_DATA"


_SYSTEM_ARTIFACT_LABELS = {
    "recently surfaced",
    "status",
    "system",
    "artifact",
}

_AMBIGUOUS_SIGNAL_LABELS = {
    "",
    "unknown",
    "status not available",
    "worth review",
    "needs review",
}

_LOW_DATA_BLOCKED_PHRASES = {
    "system",
    "artifact",
    "missing baseline",
    "baseline missing",
    "insufficient comparison window",
    "trend reliability",
    "clear caveats",
}


def format_friendly_date(value: date) -> str:
    return f"{value.strftime('%b')} {value.day}"


def _sanitize_low_data_line(text: str) -> str:
    clean = " ".join(str(text or "").strip().split())
    lowered = clean.lower()
    for phrase in _LOW_DATA_BLOCKED_PHRASES:
        if phrase in lowered:
            return ""
    return clean


def _sanitize_low_data_support_line(text: str) -> str:
    clean = _sanitize_low_data_line(text)
    lowered = clean.lower()
    if "low confidence" in lowered or "compared to:" in lowered:
        return ""
    return clean


def _recent_record_count_from_signal(signal: DisplaySignal, recent_record_count: int | None) -> int | None:
    if recent_record_count is not None:
        return max(0, int(recent_record_count))
    for key in ("recent_record_count", "usable_points", "sample_size", "included_rows"):
        value = (signal.flags or {}).get(key)
        try:
            if value is not None:
                return max(0, int(value))
        except Exception:
            continue
    return None


def _low_data_supporting_lines(signal: DisplaySignal, *, recent_record_count: int | None = None) -> list[str]:
    lines: list[str] = []
    fallback_lines: list[str] = []
    for text in list(getattr(signal, "supporting_text", []) or []):
        clean = _sanitize_low_data_support_line(str(text or ""))
        if clean:
            lines.append(clean)

    has_count_line = any(line.lower().startswith("only ") for line in lines)
    has_observed_line = any(line.lower().startswith("observed:") for line in lines)

    count = _recent_record_count_from_signal(signal, recent_record_count)
    if count is not None and not has_count_line:
        fallback_lines.append(f"Only {count} recent record(s) available")
    if signal.observed_date is not None and not has_observed_line:
        observed_line = _sanitize_low_data_support_line(f"Observed: {format_friendly_date(signal.observed_date)}")
        if observed_line:
            fallback_lines.append(observed_line)

    unique: list[str] = []
    seen: set[str] = set()
    for line in [*lines, *fallback_lines]:
        key = line.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(line)
        if len(unique) >= 2:
            break
    return unique


def format_low_data_collapsed_lines(signal: DisplaySignal) -> list[str]:
    """Return strict low-data collapsed copy.

    Always returns at most two non-empty lines.
    """
    mode = get_signal_display_mode(signal)
    if mode != SignalDisplayMode.LOW_DATA:
        return []
    lines = [
        _sanitize_low_data_line(signal_wording("not_enough_history_yet")),
        _sanitize_low_data_line("Low confidence"),
    ]
    return [line for line in lines if line][:2]


def format_low_data_expanded_lines(signal: DisplaySignal, *, recent_record_count: int | None = None) -> list[str]:
    """Return strict low-data expanded copy.

    Always returns at most two non-empty lines.
    """
    mode = get_signal_display_mode(signal)
    if mode != SignalDisplayMode.LOW_DATA:
        return []
    return _low_data_supporting_lines(signal, recent_record_count=recent_record_count)


def is_display_signal_eligible(
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
    - Minimum confidence for FULL/CURRENT_STATE, or explicit low-data allow
    - Suppress obvious system artifacts
    """
    label_text = format_signal_label(signal).strip().lower()
    if not label_text:
        return False
    if label_text in _SYSTEM_ARTIFACT_LABELS:
        return False
    if label_text in _AMBIGUOUS_SIGNAL_LABELS:
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
    signal_rank = confidence_rank.get(str(getattr(signal.confidence_level, "value", signal.confidence_level) or "LOW").lower(), 1)

    if mode == SignalDisplayMode.LOW_DATA:
        return bool(allow_low_data_case) and bool(signal.is_low_data)

    if mode == SignalDisplayMode.CURRENT_STATE:
        if signal.observed_value is None:
            return False
        # Current-state mode is a valid readable fallback when no baseline exists.
        return True

    # FULL mode
    if signal.observed_value is None or signal.comparison_value is None:
        return False
    if signal_rank < min_rank:
        return False
    return True


def is_signal_display_eligible(
    signal: DisplaySignal,
    *,
    allow_low_data_case: bool = True,
    min_confidence_for_full_or_partial: str = "medium",
) -> bool:
    """Backward-compatible alias for display-signal eligibility checks.

    Preferred name: is_display_signal_eligible.
    """
    return is_display_signal_eligible(
        signal,
        allow_low_data_case=allow_low_data_case,
        min_confidence_for_full_or_partial=min_confidence_for_full_or_partial,
    )


def get_signal_display_mode(signal: DisplaySignal) -> SignalDisplayMode:
    """Return strict display mode for consistent fallback behavior.

    Rules:
    - LOW_DATA: no usable observed data
    - CURRENT_STATE: observed data exists but no comparison basis
    - FULL: observed + comparison are both present
    """
    if signal.state == DisplaySignalState.LOW_DATA or signal.observed_value is None:
        return SignalDisplayMode.LOW_DATA
    if signal.state == DisplaySignalState.CURRENT or signal.comparison_value is None:
        return SignalDisplayMode.CURRENT_STATE
    return SignalDisplayMode.FULL


def format_signal_label(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode == SignalDisplayMode.LOW_DATA:
        return signal_wording("not_enough_history_yet")
    if mode == SignalDisplayMode.CURRENT_STATE:
        prefix = str(signal.primary_label or "Current pace").strip() or "Current pace"
        if signal.observed_value is None:
            return prefix
        observed_unit = str(signal.observed_unit or "UPH").strip() or "UPH"
        if prefix.lower().startswith("current pace:"):
            return prefix
        return f"{prefix}: {signal.observed_value:.1f} {observed_unit}"

    if str(signal.primary_label or "").strip() and signal.primary_label not in {"Current pace", "Current pace: 0.0 UPH"}:
        # For non-current states, respect canonical precomputed primary label when available.
        return str(signal.primary_label)

    if signal.signal_label == SignalLabel.BELOW_EXPECTED_PACE:
        return signal_wording("below_expected_pace")
    if signal.signal_label == SignalLabel.LOWER_THAN_RECENT_PACE:
        return signal_wording("lower_than_recent_pace")
    if signal.signal_label == SignalLabel.INCONSISTENT_PACE:
        return signal_wording("inconsistent_performance")
    if signal.signal_label == SignalLabel.IMPROVING_PACE:
        return "Improving pace"
    if signal.signal_label == SignalLabel.FOLLOW_UP_OVERDUE:
        return signal_wording("follow_up_not_completed")
    if signal.signal_label == SignalLabel.FOLLOW_UP_DUE_TODAY:
        return signal_wording("follow_up_not_completed")
    if signal.signal_label == SignalLabel.UNRESOLVED_ISSUE:
        return signal_wording("follow_up_not_completed")
    if signal.signal_label == SignalLabel.REPEATED_PATTERN:
        return "Repeated pattern"
    return signal_wording("not_enough_history_yet")


def format_observed_line(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode == SignalDisplayMode.LOW_DATA:
        return ""
    observed_text = format_friendly_date(signal.observed_date)
    if mode == SignalDisplayMode.CURRENT_STATE:
        return observed_text
    observed_unit = str(signal.observed_unit or "UPH").strip() or "UPH"
    return f"Observed: {observed_text} ({signal.observed_value:.1f} {observed_unit})"


def format_comparison_line(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode != SignalDisplayMode.FULL:
        return ""
    if signal.comparison_value is None:
        return ""
    if signal.comparison_start_date is not None and signal.comparison_end_date is not None:
        start_text = format_friendly_date(signal.comparison_start_date)
        end_text = format_friendly_date(signal.comparison_end_date)
        range_text = start_text if start_text == end_text else f"{start_text}–{end_text}"
        return (
            f"Compared to: {range_text} "
            f"avg ({signal.comparison_value:.1f} UPH)"
        )
    return f"Compared to: baseline ({signal.comparison_value:.1f} UPH)"


def format_confidence_line(signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode in {SignalDisplayMode.LOW_DATA, SignalDisplayMode.CURRENT_STATE}:
        return "Low confidence"
    level_text = str(getattr(signal.confidence_level, "value", signal.confidence_level) or "LOW").title()
    return f"Confidence: {level_text}"
