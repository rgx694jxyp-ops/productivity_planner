"""Strict display-ready signal contract for UI rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import math
from typing import Optional


class SignalLabel(str, Enum):
    BELOW_EXPECTED_PACE = "below_expected_pace"
    LOWER_THAN_RECENT_PACE = "lower_than_recent_pace"
    INCONSISTENT_PACE = "inconsistent_pace"
    IMPROVING_PACE = "improving_pace"
    FOLLOW_UP_OVERDUE = "follow_up_overdue"
    FOLLOW_UP_DUE_TODAY = "follow_up_due_today"
    UNRESOLVED_ISSUE = "unresolved_issue"
    REPEATED_PATTERN = "repeated_pattern"
    LOW_DATA = "low_data"


class SignalConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DisplaySignalState(str, Enum):
    CURRENT = "CURRENT"
    EARLY_TREND = "EARLY_TREND"
    STABLE_TREND = "STABLE_TREND"
    PATTERN = "PATTERN"
    LOW_DATA = "LOW_DATA"


class DisplayConfidenceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DataCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"
    LIMITED = "limited"
    UNKNOWN = "unknown"


_PLACEHOLDERS = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "undefined",
    "nan",
    "-",
    "--",
    "—",
}


def _is_placeholder_text(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in _PLACEHOLDERS


@dataclass(frozen=True)
class DisplaySignal:
    """Validated signal contract consumed by UI components."""

    employee_name: str
    process: str
    signal_label: SignalLabel
    observed_date: date
    observed_value: float | None
    comparison_start_date: date | None
    comparison_end_date: date | None
    comparison_value: float | None
    confidence: SignalConfidence
    employee_id: str = ""
    state: Optional[DisplaySignalState] = None
    primary_label: str = ""
    observed_unit: str | None = "UPH"
    pattern_count: int | None = None
    pattern_window_label: str | None = None
    confidence_level: Optional[DisplayConfidenceLevel] = None
    is_low_data: bool = False
    is_new_employee: bool = False
    is_actionable: bool = True
    supporting_text: list[str] = field(default_factory=list)
    delta_percent: float | None = None
    data_completeness: DataCompleteness | None = None
    flags: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Backward-compatible canonicalization for legacy constructors.
        if _is_placeholder_text(self.employee_id):
            object.__setattr__(self, "employee_id", str(self.employee_name or "unknown-employee").strip())

        if _is_placeholder_text(self.employee_name):
            raise ValueError("employee_name is required and cannot be a placeholder")
        if _is_placeholder_text(self.process):
            raise ValueError("process is required and cannot be a placeholder")
        if _is_placeholder_text(self.primary_label):
            if self.signal_label == SignalLabel.LOW_DATA or self.observed_value is None:
                object.__setattr__(self, "primary_label", "Not enough history yet")
            elif self.comparison_value is None:
                object.__setattr__(self, "primary_label", "Current pace")
            elif self.signal_label == SignalLabel.BELOW_EXPECTED_PACE:
                object.__setattr__(self, "primary_label", "Below expected pace")
            elif self.signal_label == SignalLabel.LOWER_THAN_RECENT_PACE:
                object.__setattr__(self, "primary_label", "Lower than recent pace")
            elif self.signal_label == SignalLabel.INCONSISTENT_PACE:
                object.__setattr__(self, "primary_label", "Inconsistent performance")
            elif self.signal_label == SignalLabel.IMPROVING_PACE:
                object.__setattr__(self, "primary_label", "Improving pace")
            elif self.signal_label == SignalLabel.REPEATED_PATTERN:
                object.__setattr__(self, "primary_label", "Repeated pattern")
            else:
                object.__setattr__(self, "primary_label", "Follow-up not completed")

        if self.observed_value is not None:
            if not math.isfinite(float(self.observed_value)):
                raise ValueError("observed_value must be a finite number")

        if self.signal_label != SignalLabel.LOW_DATA and self.observed_value is None:
            raise ValueError("observed_value is required for non-low-data signals")

        if self.observed_unit is not None and _is_placeholder_text(self.observed_unit):
            raise ValueError("observed_unit cannot be a placeholder")

        if self.pattern_count is not None and int(self.pattern_count) < 0:
            raise ValueError("pattern_count cannot be negative")
        if self.pattern_window_label is not None and _is_placeholder_text(self.pattern_window_label):
            raise ValueError("pattern_window_label cannot be a placeholder")

        if self.comparison_value is not None and not math.isfinite(float(self.comparison_value)):
            raise ValueError("comparison_value must be a finite number")

        has_any_comparison = any(value is not None for value in (self.comparison_start_date, self.comparison_end_date, self.comparison_value))
        has_baseline_only = self.comparison_value is not None and self.comparison_start_date is None and self.comparison_end_date is None
        has_full_comparison = all(value is not None for value in (self.comparison_start_date, self.comparison_end_date, self.comparison_value))
        if has_any_comparison and not (has_baseline_only or has_full_comparison):
            raise ValueError("comparison fields are malformed")
        if has_full_comparison:
            if self.comparison_start_date > self.comparison_end_date:
                raise ValueError("comparison_start_date must be before or equal to comparison_end_date")
            if self.comparison_start_date >= self.observed_date or self.comparison_end_date >= self.observed_date:
                raise ValueError("comparison dates must be before observed_date")

        if len(self.supporting_text) > 3:
            raise ValueError("supporting_text must contain at most 3 lines")
        cleaned_supporting: list[str] = []
        for line in list(self.supporting_text or []):
            text = " ".join(str(line or "").strip().split())
            if not text or _is_placeholder_text(text):
                continue
            cleaned_supporting.append(text)
        object.__setattr__(self, "supporting_text", cleaned_supporting[:3])

        if self.delta_percent is not None and not math.isfinite(float(self.delta_percent)):
            raise ValueError("delta_percent must be a finite number")

        # Keep legacy confidence field and new display confidence_level aligned.
        expected_conf_level = DisplayConfidenceLevel[str(self.confidence.value or "low").upper()]
        object.__setattr__(self, "confidence_level", self.confidence_level or expected_conf_level)

        derived_state = self.state
        if derived_state is None:
            if self.signal_label == SignalLabel.LOW_DATA or self.observed_value is None:
                derived_state = DisplaySignalState.LOW_DATA
            elif self.signal_label in {SignalLabel.REPEATED_PATTERN, SignalLabel.UNRESOLVED_ISSUE, SignalLabel.FOLLOW_UP_OVERDUE, SignalLabel.FOLLOW_UP_DUE_TODAY}:
                derived_state = DisplaySignalState.PATTERN
            elif self.comparison_value is None:
                derived_state = DisplaySignalState.CURRENT
            elif self.confidence == SignalConfidence.HIGH:
                derived_state = DisplaySignalState.STABLE_TREND
            else:
                derived_state = DisplaySignalState.EARLY_TREND
        object.__setattr__(self, "state", derived_state)

        resolved_is_low_data = bool(self.is_low_data or self.state == DisplaySignalState.LOW_DATA)
        object.__setattr__(self, "is_low_data", resolved_is_low_data)
        if self.signal_label == SignalLabel.IMPROVING_PACE:
            object.__setattr__(self, "is_actionable", False)

        if self.is_low_data and self.state not in {DisplaySignalState.LOW_DATA, DisplaySignalState.CURRENT}:
            raise ValueError("is_low_data can only be true when state is LOW_DATA or CURRENT")

    @property
    def comparison_is_valid(self) -> bool:
        return all(value is not None for value in (self.comparison_start_date, self.comparison_end_date, self.comparison_value))
