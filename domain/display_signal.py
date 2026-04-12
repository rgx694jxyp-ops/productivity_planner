"""Strict display-ready signal contract for UI rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import math


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
    data_completeness: DataCompleteness | None = None
    flags: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _is_placeholder_text(self.employee_name):
            raise ValueError("employee_name is required and cannot be a placeholder")
        if _is_placeholder_text(self.process):
            raise ValueError("process is required and cannot be a placeholder")

        if self.observed_value is not None:
            if not math.isfinite(float(self.observed_value)):
                raise ValueError("observed_value must be a finite number")

        if self.signal_label != SignalLabel.LOW_DATA and self.observed_value is None:
            raise ValueError("observed_value is required for non-low-data signals")

        if self.comparison_value is not None and not math.isfinite(float(self.comparison_value)):
            raise ValueError("comparison_value must be a finite number")

        for maybe_date in (self.comparison_start_date, self.comparison_end_date):
            if maybe_date is not None and maybe_date >= self.observed_date:
                raise ValueError("comparison dates must be before observed_date")
