"""Data quality payload models for import trust and issue grouping flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LatestImportSummary:
    rows_processed: int
    valid_rows: int
    warning_rows: int
    rejected_rows: int
    ignored_or_excluded_rows: int


@dataclass(frozen=True)
class IssueGroup:
    key: str
    label: str
    count: int
    effect: str
    default_choice: str
    rows: list[dict[str, Any]] = field(default_factory=list)
