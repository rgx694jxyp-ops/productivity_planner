"""Typed structures for CSV import preview/commit flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]
DataQualityStatus = Literal["valid", "partial", "low_confidence", "invalid"]


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
class ImportTrustSummary:
    status: DataQualityStatus = "invalid"
    accepted_rows: int = 0
    rejected_rows: int = 0
    warnings: int = 0
    duplicates: int = 0
    missing_required_fields: int = 0
    inconsistent_names: int = 0
    suspicious_values: int = 0
    confidence_score: int = 0
    warning_summary: str = ""


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
    trust_summary: ImportTrustSummary = field(default_factory=ImportTrustSummary)


@dataclass
class ImportCommitResult:
    success: bool
    summary: ImportSummary
    issues: list[ImportIssue] = field(default_factory=list)
    upload_id: Any = None
    message: str = ""
    trust_summary: ImportTrustSummary = field(default_factory=ImportTrustSummary)
