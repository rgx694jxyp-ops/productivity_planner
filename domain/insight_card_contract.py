"""Reusable insight-card contract for explainable, non-prescriptive signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

InsightKind = Literal[
    "below_expected_performance",
    "trend_change",
    "repeated_pattern",
    "unresolved_issue",
    "follow_up_due",
    "suspicious_import_data",
    "post_activity_outcome",
]

ConfidenceLevel = Literal["high", "medium", "low"]
CompletenessStatus = Literal["complete", "partial", "incomplete", "unknown"]
DrillDownScreen = Literal["today", "employee_detail", "team_process", "import_data_trust", "settings"]
SourceType = Literal["table", "event", "upload", "note", "metric", "calc"]


@dataclass(frozen=True)
class ConfidenceInfo:
    """How strong the signal is and what evidence basis produced it."""

    level: ConfidenceLevel
    score: float | None = None
    basis: str = ""
    sample_size: int | None = None
    minimum_expected_points: int | None = None
    caveat: str = ""


@dataclass(frozen=True)
class VolumeWorkloadContext:
    """Workload and exposure context to prevent de-contextualized signals."""

    impacted_entity_count: int | None = None
    impacted_group_label: str = ""
    observed_volume: float | None = None
    observed_volume_unit: str = ""
    baseline_volume: float | None = None
    baseline_volume_unit: str = ""
    volume_note: str = ""


@dataclass(frozen=True)
class TimeContext:
    """Time window and freshness details for interpretation and trust."""

    observed_window_label: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    compared_window_label: str = ""
    compared_window_start: datetime | None = None
    compared_window_end: datetime | None = None
    last_updated_at: datetime | None = None
    stale_after_hours: int | None = None


@dataclass(frozen=True)
class DataCompletenessNote:
    """Completeness caveat that can be shown directly in UI copy."""

    status: CompletenessStatus
    summary: str
    missing_fields: list[str] = field(default_factory=list)
    missing_ratio: float | None = None
    excluded_rows: int | None = None


@dataclass(frozen=True)
class DrillDownTarget:
    """Where to navigate for context or evidence, without prescribing actions."""

    screen: DrillDownScreen
    label: str
    entity_id: str = ""
    section: str = ""
    filters: dict[str, str] = field(default_factory=dict)
    anchor: str = ""


@dataclass(frozen=True)
class SourceReference:
    """Machine-readable evidence reference for auditability and explainability."""

    source_type: SourceType
    source_name: str
    source_id: str = ""
    field_paths: list[str] = field(default_factory=list)
    evidence_excerpt: str = ""


@dataclass(frozen=True)
class TraceabilityContext:
    """Structured source context for drill-down explainability."""

    date_range_used: str = ""
    baseline_or_target_used: str = ""
    linked_scope: str = ""
    linked_entity_id: str = ""
    linked_entity_label: str = ""
    related_import_job_id: str = ""
    related_import_file: str = ""
    included_rows: int | None = None
    excluded_rows: int | None = None
    warnings: list[str] = field(default_factory=list)
    source_summary: str = ""


@dataclass(frozen=True)
class InsightCardContract:
    """App-wide card contract for rendering explainable operational signals.

    This structure intentionally excludes prescriptive recommendation fields.
    """

    insight_id: str
    insight_kind: InsightKind
    title: str

    what_happened: str
    compared_to_what: str
    why_flagged: str

    confidence: ConfidenceInfo
    workload_context: VolumeWorkloadContext
    time_context: TimeContext
    data_completeness: DataCompletenessNote

    drill_down: DrillDownTarget
    traceability: TraceabilityContext = field(default_factory=TraceabilityContext)
    source_references: list[SourceReference] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return validation errors for required explainability expectations."""
        errors: list[str] = []

        if not self.title.strip():
            errors.append("title is required")
        if not self.what_happened.strip():
            errors.append("what_happened is required")
        if not self.compared_to_what.strip():
            errors.append("compared_to_what is required")
        if not self.why_flagged.strip():
            errors.append("why_flagged is required")
        if not self.drill_down.label.strip():
            errors.append("drill_down.label is required")
        if not self.source_references:
            errors.append("at least one source reference is required")

        if self.confidence.score is not None and not (0.0 <= self.confidence.score <= 1.0):
            errors.append("confidence.score must be between 0.0 and 1.0")

        if self.data_completeness.missing_ratio is not None and not (0.0 <= self.data_completeness.missing_ratio <= 1.0):
            errors.append("data_completeness.missing_ratio must be between 0.0 and 1.0")

        return errors
