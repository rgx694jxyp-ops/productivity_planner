"""Typed structures for CSV import preview/commit flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]


@dataclass
class ImportIssue:
    code: str
    message: str
    severity: Severity = "error"
    row_index: int | None = None
    field: str = ""
    value: str = ""


@dataclass
class MappingReview:
    required_missing: list[str] = field(default_factory=list)
    optional_unmapped: list[str] = field(default_factory=list)
    mapped: dict[str, str] = field(default_factory=dict)


@dataclass
class ImportSummary:
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_rows_in_file: int = 0
    duplicate_rows_existing: int = 0
    inserted_rows: int = 0
    skipped_rows: int = 0


@dataclass
class ImportPreviewResult:
    success: bool
    can_import: bool
    summary: ImportSummary
    mapping_review: MappingReview
    candidate_rows: list[dict[str, Any]] = field(default_factory=list)
    invalid_issues: list[ImportIssue] = field(default_factory=list)
    exact_duplicate_import: bool = False
    fingerprint: str = ""
    message: str = ""


@dataclass
class ImportCommitResult:
    success: bool
    summary: ImportSummary
    issues: list[ImportIssue] = field(default_factory=list)
    upload_id: Any = None
    message: str = ""
