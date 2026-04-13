"""Helpers for building and serializing signal traceability context."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from domain.insight_card_contract import (
    DataCompletenessNote,
    DrillDownTarget,
    InsightCardContract,
    SourceReference,
    TimeContext,
    TraceabilityContext,
)


def build_traceability_context(
    *,
    date_range_used: str,
    baseline_or_target_used: str,
    linked_scope: str,
    linked_entity_id: str = "",
    linked_entity_label: str = "",
    related_import_job_id: str = "",
    related_import_file: str = "",
    included_rows: int | None = None,
    excluded_rows: int | None = None,
    warnings: list[str] | None = None,
    source_summary: str = "",
) -> TraceabilityContext:
    return TraceabilityContext(
        date_range_used=str(date_range_used or ""),
        baseline_or_target_used=str(baseline_or_target_used or ""),
        linked_scope=str(linked_scope or ""),
        linked_entity_id=str(linked_entity_id or ""),
        linked_entity_label=str(linked_entity_label or ""),
        related_import_job_id=str(related_import_job_id or ""),
        related_import_file=str(related_import_file or ""),
        included_rows=included_rows,
        excluded_rows=excluded_rows,
        warnings=list(warnings or []),
        source_summary=str(source_summary or ""),
    )


def infer_traceability_context(
    *,
    compared_to_what: str,
    time_context: TimeContext,
    data_completeness: DataCompletenessNote,
    drill_down: DrillDownTarget,
    source_references: list[SourceReference],
    metadata: dict | None,
) -> TraceabilityContext:
    meta = dict(metadata or {})
    warnings = []
    if data_completeness.summary:
        warnings.append(str(data_completeness.summary))
    warnings.extend([str(w) for w in (meta.get("trace_warnings") or []) if str(w).strip()])

    import_job_id = str(meta.get("import_job_id") or "")
    import_file = str(meta.get("import_file") or "")

    linked_scope = "employee" if drill_down.screen == "employee_detail" else "team" if drill_down.screen == "team_process" else "process"
    source_summary = ", ".join(sorted({str(s.source_name) for s in (source_references or []) if str(s.source_name).strip()}))

    return build_traceability_context(
        date_range_used=str(time_context.observed_window_label or "Current window"),
        baseline_or_target_used=str(compared_to_what or "Baseline context available in card"),
        linked_scope=linked_scope,
        linked_entity_id=str(drill_down.entity_id or ""),
        linked_entity_label=str(meta.get("linked_entity_label") or ""),
        related_import_job_id=import_job_id,
        related_import_file=import_file,
        included_rows=meta.get("included_rows"),
        excluded_rows=data_completeness.excluded_rows,
        warnings=warnings,
        source_summary=source_summary,
    )


def traceability_payload_from_card(item: InsightCardContract) -> dict:
    sample_size = item.confidence.sample_size
    min_points = item.confidence.minimum_expected_points
    included_rows = item.traceability.included_rows

    maturity_label = "stable signal"
    maturity_reason = "comparison context and evidence coverage are available"
    if isinstance(included_rows, int) and included_rows > 0 and included_rows < 3:
        maturity_label = "limited-data prompt"
        maturity_reason = "fewer than 3 usable points are available"
    elif isinstance(sample_size, int) and sample_size > 0 and sample_size < 3:
        maturity_label = "limited-data prompt"
        maturity_reason = "fewer than 3 usable points are available"
    elif str(item.confidence.level or "").strip().lower() == "low":
        maturity_label = "early signal"
        maturity_reason = "evidence coverage is still limited"
    elif isinstance(min_points, int) and isinstance(sample_size, int) and min_points > 0 and sample_size < min_points:
        maturity_label = "early signal"
        maturity_reason = "usable points are below the stable-window threshold"

    observed_label = str(item.time_context.observed_window_label or "").strip()
    compared_label = str(item.time_context.compared_window_label or "").strip()
    freshness_text = observed_label or "Latest snapshot"
    if item.time_context.last_updated_at:
        try:
            ts = datetime.fromisoformat(str(item.time_context.last_updated_at))
            freshness_text = f"{freshness_text} · Updated {ts.strftime('%Y-%m-%d %H:%M')}"
        except Exception:
            pass

    payload = asdict(item.traceability)
    payload.update(
        {
            "insight_id": item.insight_id,
            "insight_title": item.title,
            "drill_down_screen": item.drill_down.screen,
            "drill_down_section": item.drill_down.section,
            "signal_summary": str(item.what_happened or item.title or "").strip(),
            "surfaced_because": str(item.why_flagged or "").strip(),
            "confidence_level": str(item.confidence.level or "low").strip().lower(),
            "confidence_basis": str(item.confidence.basis or "").strip(),
            "confidence_caveat": str(item.confidence.caveat or "").strip(),
            "confidence_sample_size": sample_size,
            "confidence_minimum_points": min_points,
            "comparison_statement": str(item.compared_to_what or "").strip(),
            "freshness_statement": freshness_text,
            "observed_window_label": observed_label,
            "compared_window_label": compared_label,
            "signal_maturity_label": maturity_label,
            "signal_maturity_reason": maturity_reason,
        }
    )
    return payload
