"""Deterministic signal interpretation helpers for manager-friendly explanations."""

from __future__ import annotations

from datetime import date, datetime, time
from dataclasses import replace

from domain.insight_card_contract import (
    ConfidenceInfo,
    DataCompletenessNote,
    DrillDownTarget,
    InsightCardContract,
    SourceReference,
    TimeContext,
    TraceabilityContext,
    VolumeWorkloadContext,
)
from services.plain_language_service import (
    describe_change_pct,
    describe_goal_status,
    describe_trend,
)
from services.signal_traceability_service import infer_traceability_context
from services.signal_quality_service import rank_and_filter_signals
from services.signal_pattern_memory_service import (
    detect_pattern_memory_from_action,
    detect_pattern_memory_from_goal_row,
)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        try:
            return date.fromisoformat(text[:10])
        except Exception:
            return None


def _ref_ts(today: date) -> datetime:
    """Use deterministic reference timestamp derived from provided date."""
    return datetime.combine(today, time(hour=12, minute=0))


def _confidence_from_inputs(
    *,
    sample_size: int,
    min_expected: int,
    missing_ratio: float | None,
    has_core_pair: bool,
) -> ConfidenceInfo:
    ratio = 0.0 if missing_ratio is None else max(0.0, min(1.0, float(missing_ratio)))

    if has_core_pair and sample_size >= max(2, min_expected) and ratio <= 0.1:
        return ConfidenceInfo(
            level="high",
            score=0.9,
            basis=f"Core fields available with sample size {sample_size}",
            sample_size=sample_size,
            minimum_expected_points=min_expected,
        )

    if sample_size >= max(1, min_expected // 2) and ratio <= 0.35:
        return ConfidenceInfo(
            level="medium",
            score=0.72,
            basis=f"Partial support with sample size {sample_size}",
            sample_size=sample_size,
            minimum_expected_points=min_expected,
            caveat="Signal confidence increases as more complete observations are added.",
        )

    return ConfidenceInfo(
        level="low",
        score=0.48,
        basis="Limited supporting observations",
        sample_size=sample_size,
        minimum_expected_points=min_expected,
        caveat="Treat as an early signal until additional data is available.",
    )


def _build_goal_status_workload_context(
    *,
    group_label: str,
    avg_uph: float,
    target_uph: float,
    total_units: float,
    hours_worked: float,
    trend_text: str,
) -> tuple[VolumeWorkloadContext, str, list[str]]:
    """Build workload context for goal-status based rows.

    Uses units + hours when available so interpretation can compare performance
    against expected volume at the same workload exposure.
    """
    missing_fields: list[str] = []
    if total_units <= 0:
        missing_fields.append("Total Units")
    if hours_worked <= 0:
        missing_fields.append("Hours Worked")

    note_parts: list[str] = []
    compared_note = ""

    if total_units > 0 and hours_worked > 0:
        note_parts.append(f"Observed workload: {total_units:.0f} units across {hours_worked:.1f} hour(s).")
        if target_uph > 0:
            expected_units = target_uph * hours_worked
            unit_gap = total_units - expected_units
            if abs(unit_gap) < max(1.0, expected_units * 0.01):
                compared_note = (
                    f"At this workload volume, output is approximately aligned with the normal-volume baseline "
                    f"({target_uph:.1f} UPH target)."
                )
            elif unit_gap < 0:
                compared_note = (
                    f"At this workload volume, processed volume is {abs(unit_gap):.0f} unit(s) below the "
                    f"normal-volume expectation for {hours_worked:.1f} hour(s)."
                )
            else:
                compared_note = (
                    f"At this workload volume, processed volume is {unit_gap:.0f} unit(s) above the "
                    f"normal-volume expectation for {hours_worked:.1f} hour(s)."
                )
        else:
            compared_note = "Workload exposure is available, but target baseline is missing for a normal-volume comparison."
    else:
        compared_note = "Workload volume fields are incomplete, so this comparison relies mostly on UPH trend context."

    note_parts.append(f"Trend context: {trend_text}.")

    return (
        VolumeWorkloadContext(
            impacted_entity_count=1,
            impacted_group_label=group_label,
            observed_volume=avg_uph if avg_uph > 0 else None,
            observed_volume_unit="UPH" if avg_uph > 0 else "",
            baseline_volume=target_uph if target_uph > 0 else None,
            baseline_volume_unit="UPH" if target_uph > 0 else "",
            volume_note=" ".join(note_parts).strip(),
        ),
        compared_note,
        missing_fields,
    )


def _card(
    *,
    insight_id: str,
    insight_kind: str,
    title: str,
    what_happened: str,
    compared_to_what: str,
    why_flagged: str,
    confidence: ConfidenceInfo,
    workload_context: VolumeWorkloadContext,
    time_context: TimeContext,
    data_completeness: DataCompletenessNote,
    drill_down: DrillDownTarget,
    source_references: list[SourceReference],
    traceability: TraceabilityContext | None = None,
    optional_review_areas: list[str] | None = None,
    metadata: dict | None = None,
) -> InsightCardContract:
    merged_metadata = dict(metadata or {})
    merged_metadata["optional_review_areas"] = list(optional_review_areas or [])
    trace_ctx = traceability or infer_traceability_context(
        compared_to_what=compared_to_what,
        time_context=time_context,
        data_completeness=data_completeness,
        drill_down=drill_down,
        source_references=source_references,
        metadata=merged_metadata,
    )

    return InsightCardContract(
        insight_id=insight_id,
        insight_kind=insight_kind,
        title=title,
        what_happened=what_happened,
        compared_to_what=compared_to_what,
        why_flagged=why_flagged,
        confidence=confidence,
        workload_context=workload_context,
        time_context=time_context,
        data_completeness=data_completeness,
        drill_down=drill_down,
        traceability=trace_ctx,
        source_references=source_references,
        metadata=merged_metadata,
    )


def interpret_below_expected_performance(*, row: dict, today: date) -> InsightCardContract:
    emp_id = str(row.get("EmployeeID") or "")
    name = str(row.get("Employee") or row.get("Employee Name") or emp_id or "Unknown")
    dept = str(row.get("Department") or "Team")
    avg_uph = _safe_float(row.get("Average UPH"), 0.0)
    target_uph = _safe_float(row.get("Target UPH"), 0.0)
    total_units = _safe_float(row.get("Total Units"), 0.0)
    hours_worked = _safe_float(row.get("Hours Worked"), 0.0)
    trend = str(row.get("trend") or "unknown")
    trend_text = describe_trend(trend)
    status_text = describe_goal_status(str(row.get("goal_status") or "unknown"))

    missing_fields: list[str] = []
    if avg_uph <= 0:
        missing_fields.append("Average UPH")
    if target_uph <= 0:
        missing_fields.append("Target UPH")

    workload_context, workload_note, workload_missing_fields = _build_goal_status_workload_context(
        group_label=dept,
        avg_uph=avg_uph,
        target_uph=target_uph,
        total_units=total_units,
        hours_worked=hours_worked,
        trend_text=trend_text,
    )
    pattern_memory = detect_pattern_memory_from_goal_row(row=row)
    all_missing_fields = [*missing_fields, *workload_missing_fields]

    compared_text = (
        (
            f"Compared with target {target_uph:.1f} UPH."
            if target_uph > 0
            else "Compared with this role's expected output context when targets are available."
        )
        + f" {workload_note}"
    )
    if pattern_memory.pattern_detected:
        compared_text = f"{compared_text} {pattern_memory.summary}"

    sample_size = 2 if avg_uph > 0 and target_uph > 0 else 1
    confidence = _confidence_from_inputs(
        sample_size=sample_size,
        min_expected=2,
        missing_ratio=(len(missing_fields) / 2.0),
        has_core_pair=avg_uph > 0 and target_uph > 0,
    )

    return _card(
        insight_id=f"below_expected:{emp_id or name}",
        insight_kind="below_expected_performance",
        title=f"Below expected performance: {name}",
        what_happened=f"Current average output is {avg_uph:.1f} UPH.",
        compared_to_what=compared_text,
        why_flagged="Surfaced because output is below expected range in the current performance snapshot.",
        confidence=confidence,
        workload_context=replace(
            workload_context,
            volume_note=f"{workload_context.volume_note} Goal status context: {status_text}.",
        ),
        time_context=TimeContext(
            observed_window_label="Current performance snapshot",
            compared_window_label="Expected output baseline",
            window_end=_ref_ts(today),
            last_updated_at=_ref_ts(today),
            stale_after_hours=6,
        ),
        data_completeness=DataCompletenessNote(
            status="partial" if all_missing_fields else "complete",
            summary="Some baseline or workload fields are missing." if all_missing_fields else "Baseline and workload fields available.",
            missing_fields=all_missing_fields,
            missing_ratio=(len(all_missing_fields) / 4.0) if all_missing_fields else 0.0,
        ),
        drill_down=DrillDownTarget(
            screen="employee_detail",
            label="Open employee detail",
            entity_id=emp_id,
            section="performance_timeline",
            filters={"source": "interpreted_signal", "signal": "below_expected_performance"},
        ),
        source_references=[
            SourceReference(
                source_type="metric",
                source_name="goal_status",
                source_id=emp_id,
                field_paths=["Average UPH", "Target UPH", "trend", "goal_status", "recent_trend_history", "recent_goal_status_history"],
                evidence_excerpt=f"{name} | avg={avg_uph:.1f} | target={target_uph:.1f}",
            )
        ],
        optional_review_areas=["Recent shift context", "Workload distribution"],
        metadata={
            "department": dept,
            "trend": trend,
            "pattern_detected": pattern_memory.pattern_detected,
            "pattern_kind": pattern_memory.pattern_kind,
            "repeat_count": pattern_memory.repeat_count,
            "pattern_summary": pattern_memory.summary,
        },
    )


def interpret_changed_from_normal(*, row: dict, today: date) -> InsightCardContract:
    emp_id = str(row.get("EmployeeID") or "")
    name = str(row.get("Employee") or row.get("Employee Name") or emp_id or "Unknown")
    dept = str(row.get("Department") or "Team")
    change_pct = _safe_float(row.get("change_pct"), 0.0)
    trend = str(row.get("trend") or "flat")
    trend_text = describe_trend(trend)
    avg_uph = _safe_float(row.get("Average UPH"), 0.0)
    target_uph = _safe_float(row.get("Target UPH"), 0.0)
    total_units = _safe_float(row.get("Total Units"), 0.0)
    hours_worked = _safe_float(row.get("Hours Worked"), 0.0)

    workload_context, workload_note, workload_missing_fields = _build_goal_status_workload_context(
        group_label=dept,
        avg_uph=avg_uph,
        target_uph=target_uph,
        total_units=total_units,
        hours_worked=hours_worked,
        trend_text=trend_text,
    )
    pattern_memory = detect_pattern_memory_from_goal_row(row=row)

    compared_text = (
        (
            f"Compared with target {target_uph:.1f} UPH."
            if target_uph > 0
            else "Compared with this person's recent trend baseline."
        )
        + f" {workload_note}"
    )
    if pattern_memory.pattern_detected:
        compared_text = f"{compared_text} {pattern_memory.summary}"

    confidence = _confidence_from_inputs(
        sample_size=1,
        min_expected=2,
        missing_ratio=0.0 if avg_uph > 0 else 0.5,
        has_core_pair=avg_uph > 0,
    )

    return _card(
        insight_id=f"changed_normal:{emp_id or name}",
        insight_kind="trend_change",
        title=f"Changed from normal: {name}",
        what_happened=f"Current pace is {trend_text} ({describe_change_pct(change_pct)}).",
        compared_to_what=compared_text,
        why_flagged="Surfaced because trend direction and percent change cross visibility thresholds.",
        confidence=confidence,
        workload_context=workload_context,
        time_context=TimeContext(
            observed_window_label="Current trend window",
            compared_window_label="Prior trend window",
            window_end=_ref_ts(today),
            last_updated_at=_ref_ts(today),
            stale_after_hours=6,
        ),
        data_completeness=DataCompletenessNote(
            status="partial" if target_uph <= 0 else "complete",
            summary=(
                "Target baseline is incomplete for this row."
                if target_uph <= 0
                else "Trend baseline fields available; workload-volume context is best effort."
            ),
            missing_fields=["Target UPH"] if target_uph <= 0 else [],
        ),
        drill_down=DrillDownTarget(
            screen="employee_detail",
            label="Open trend details",
            entity_id=emp_id,
            section="performance_timeline",
            filters={"source": "interpreted_signal", "signal": "trend_change"},
        ),
        source_references=[
            SourceReference(
                source_type="metric",
                source_name="goal_status",
                source_id=emp_id,
                field_paths=["trend", "change_pct", "Average UPH", "Target UPH", "recent_trend_history", "recent_goal_status_history"],
                evidence_excerpt=f"trend={trend_text} | change={change_pct:.1f}%",
            )
        ],
        optional_review_areas=["Recent schedule change", "Volume mix"],
        metadata={
            "department": dept,
            "change_pct": change_pct,
            "pattern_detected": pattern_memory.pattern_detected,
            "pattern_kind": pattern_memory.pattern_kind,
            "repeat_count": pattern_memory.repeat_count,
            "pattern_summary": pattern_memory.summary,
        },
    )


def interpret_repeated_decline(*, action: dict, today: date) -> InsightCardContract:
    action_id = str(action.get("id") or "")
    emp_id = str(action.get("employee_id") or "")
    name = str(action.get("employee_name") or emp_id or "Unknown")
    dept = str(action.get("department") or "Team")
    reason = str(action.get("_short_reason") or action.get("trigger_summary") or "Repeated decline pattern")
    baseline = _safe_float(action.get("baseline_uph"), 0.0)
    latest = _safe_float(action.get("latest_uph"), 0.0)
    pattern_memory = detect_pattern_memory_from_action(action=action, today=today)

    confidence = _confidence_from_inputs(
        sample_size=2 if baseline > 0 and latest > 0 else 1,
        min_expected=2,
        missing_ratio=0.0 if baseline > 0 and latest > 0 else 0.5,
        has_core_pair=baseline > 0 and latest > 0,
    )

    return _card(
        insight_id=f"repeated_decline:{action_id or emp_id}",
        insight_kind="repeated_pattern",
        title=f"Repeated decline: {name}",
        what_happened=(f"{reason} {pattern_memory.summary}" if pattern_memory.pattern_detected else reason),
        compared_to_what=(
            f"Compared with baseline {baseline:.1f} UPH and latest {latest:.1f} UPH."
            if baseline > 0 and latest > 0
            else "Compared with the employee's prior action context."
        ),
        why_flagged="Surfaced because repeated decline indicators remained open across follow-up cycles.",
        confidence=confidence,
        workload_context=VolumeWorkloadContext(
            impacted_entity_count=1,
            impacted_group_label=dept,
            volume_note="Tracked within repeated-pattern cohort.",
        ),
        time_context=TimeContext(
            observed_window_label="Current open-action window",
            compared_window_label="Prior follow-up window",
            window_end=_ref_ts(today),
            last_updated_at=_ref_ts(today),
            stale_after_hours=6,
        ),
        data_completeness=DataCompletenessNote(
            status="partial" if baseline <= 0 or latest <= 0 else "complete",
            summary="Performance pair is incomplete for this pattern." if baseline <= 0 or latest <= 0 else "Pattern fields complete.",
            missing_fields=[
                name
                for name, value in {"baseline_uph": baseline, "latest_uph": latest}.items()
                if value <= 0
            ],
        ),
        drill_down=DrillDownTarget(
            screen="employee_detail",
            label="Open pattern history",
            entity_id=emp_id,
            section="active_issues",
            filters={"source": "interpreted_signal", "signal": "repeated_pattern", "action_id": action_id},
        ),
        source_references=[
            SourceReference(
                source_type="table",
                source_name="actions",
                source_id=action_id,
                field_paths=["trigger_summary", "issue_type", "baseline_uph", "latest_uph", "_repeat_signals", "_is_repeat_issue", "last_event_at"],
                evidence_excerpt=reason,
            )
        ],
        optional_review_areas=["Recent coaching notes", "Follow-up timing"],
        metadata={
            "pattern_detected": pattern_memory.pattern_detected,
            "pattern_kind": pattern_memory.pattern_kind,
            "repeat_count": pattern_memory.repeat_count,
            "pattern_summary": pattern_memory.summary,
            "pattern_recent_window_days": pattern_memory.recent_window_days,
        },
    )


def interpret_unresolved_issue(*, action: dict, today: date) -> InsightCardContract:
    action_id = str(action.get("id") or "")
    emp_id = str(action.get("employee_id") or "")
    name = str(action.get("employee_name") or emp_id or "Unknown")
    dept = str(action.get("department") or "Team")
    created_on = _parse_iso_date(action.get("created_at") or action.get("last_event_at"))
    days_open = (today - created_on).days if created_on else 0
    due_text = str(action.get("follow_up_due_at") or "unspecified")
    pattern_memory = detect_pattern_memory_from_action(action=action, today=today)

    happened_text = f"This item remains open for {days_open} day(s)."
    if pattern_memory.pattern_detected:
        happened_text = f"{happened_text} {pattern_memory.summary}"

    return _card(
        insight_id=f"unresolved:{action_id or emp_id}",
        insight_kind="unresolved_issue",
        title=f"Unresolved item: {name}",
        what_happened=happened_text,
        compared_to_what="Compared with expected closure timing for active follow-up items.",
        why_flagged="Surfaced because the item is still open and remains in unresolved monitoring.",
        confidence=_confidence_from_inputs(
            sample_size=1,
            min_expected=1,
            missing_ratio=0.0 if created_on else 0.4,
            has_core_pair=bool(created_on),
        ),
        workload_context=VolumeWorkloadContext(
            impacted_entity_count=1,
            impacted_group_label=dept,
            volume_note="Part of unresolved issue tracking.",
        ),
        time_context=TimeContext(
            observed_window_label="Open issue lifespan",
            compared_window_label="Expected follow-up window",
            window_start=datetime.combine(created_on, time(hour=0, minute=0)) if created_on else None,
            window_end=_ref_ts(today),
            last_updated_at=_ref_ts(today),
            stale_after_hours=6,
        ),
        data_completeness=DataCompletenessNote(
            status="partial" if created_on is None else "complete",
            summary="Created date missing; duration is approximate." if created_on is None else "Lifecycle timestamps available.",
            missing_fields=["created_at"] if created_on is None else [],
        ),
        drill_down=DrillDownTarget(
            screen="employee_detail",
            label="Open unresolved timeline",
            entity_id=emp_id,
            section="active_issues",
            filters={"source": "interpreted_signal", "signal": "unresolved_issue", "action_id": action_id},
        ),
        source_references=[
            SourceReference(
                source_type="table",
                source_name="actions",
                source_id=action_id,
                field_paths=["status", "follow_up_due_at", "created_at", "issue_type", "_repeat_signals", "_is_repeat_issue", "last_event_at"],
                evidence_excerpt=f"due={due_text}",
            )
        ],
        optional_review_areas=["Open duration", "Issue history"],
        metadata={
            "days_open": days_open,
            "pattern_detected": pattern_memory.pattern_detected,
            "pattern_kind": pattern_memory.pattern_kind,
            "repeat_count": pattern_memory.repeat_count,
            "pattern_summary": pattern_memory.summary,
            "pattern_recent_window_days": pattern_memory.recent_window_days,
        },
    )


def interpret_follow_up_due(*, action: dict, today: date) -> InsightCardContract:
    action_id = str(action.get("id") or "")
    emp_id = str(action.get("employee_id") or "")
    name = str(action.get("employee_name") or emp_id or "Unknown")
    dept = str(action.get("department") or "Team")
    due_date = _parse_iso_date(action.get("follow_up_due_at"))
    queue_status = str(action.get("_queue_status") or "pending")
    queue_status_text = {
        "overdue": "overdue",
        "due_today": "due today",
        "pending": "open",
    }.get(queue_status, "open")
    due_delta = (due_date - today).days if due_date else None
    pattern_memory = detect_pattern_memory_from_action(action=action, today=today)

    if due_delta is None:
        happened = "Follow-up timing is open and due-date metadata is missing."
    elif due_delta < 0:
        happened = f"Follow-up is overdue by {abs(due_delta)} day(s)."
    elif due_delta == 0:
        happened = "Follow-up is due today."
    else:
        happened = f"Follow-up is due in {due_delta} day(s)."

    if pattern_memory.pattern_detected:
        happened = f"{happened} {pattern_memory.summary}"

    return _card(
        insight_id=f"follow_up_due:{action_id or emp_id}",
        insight_kind="follow_up_due",
        title=f"Follow-up timing: {name}",
        what_happened=happened,
        compared_to_what="Compared with scheduled follow-up date and open-action status.",
        why_flagged="Surfaced because this item is active in due-date monitoring.",
        confidence=_confidence_from_inputs(
            sample_size=1,
            min_expected=1,
            missing_ratio=0.0 if due_date else 0.5,
            has_core_pair=due_date is not None,
        ),
        workload_context=VolumeWorkloadContext(
            impacted_entity_count=1,
            impacted_group_label=dept,
            volume_note=f"Queue status is {queue_status_text}.",
        ),
        time_context=TimeContext(
            observed_window_label="Follow-up schedule window",
            compared_window_label="Current date",
            window_end=_ref_ts(today),
            last_updated_at=_ref_ts(today),
            stale_after_hours=6,
        ),
        data_completeness=DataCompletenessNote(
            status="complete" if due_date else "partial",
            summary="Due-date metadata available." if due_date else "Due-date metadata is missing.",
            missing_fields=[] if due_date else ["follow_up_due_at"],
        ),
        drill_down=DrillDownTarget(
            screen="today",
            label="Open queue details",
            entity_id=emp_id,
            section="action_queue_details",
            filters={"source": "interpreted_signal", "signal": "follow_up_due", "action_id": action_id},
        ),
        source_references=[
            SourceReference(
                source_type="table",
                source_name="actions",
                source_id=action_id,
                field_paths=["follow_up_due_at", "status", "priority", "_repeat_signals", "_is_repeat_issue", "last_event_at"],
                evidence_excerpt=f"queue_status={queue_status_text}",
            )
        ],
        optional_review_areas=["Schedule consistency", "Recent updates"],
        metadata={
            "pattern_detected": pattern_memory.pattern_detected,
            "pattern_kind": pattern_memory.pattern_kind,
            "repeat_count": pattern_memory.repeat_count,
            "pattern_summary": pattern_memory.summary,
            "pattern_recent_window_days": pattern_memory.recent_window_days,
        },
    )


def interpret_suspicious_or_incomplete_data(*, import_summary: dict, today: date) -> InsightCardContract:
    days = _safe_int(import_summary.get("days"), 0)
    emp_count = _safe_int(import_summary.get("emp_count"), 0)
    below = _safe_int(import_summary.get("below"), 0)

    missing_fields: list[str] = []
    if days <= 0:
        missing_fields.append("days")
    if emp_count <= 0:
        missing_fields.append("emp_count")

    return _card(
        insight_id="suspicious_data:import_summary",
        insight_kind="suspicious_import_data",
        title="Data warning: import completeness",
        what_happened=f"Current import window contains {days} day(s) across {emp_count} employee(s).",
        compared_to_what="Compared with minimum trend window of 3 days for stable signal confidence.",
        why_flagged="Surfaced because limited import history can lower interpretation confidence.",
        confidence=_confidence_from_inputs(
            sample_size=max(days, 1),
            min_expected=3,
            missing_ratio=(len(missing_fields) / 2.0),
            has_core_pair=days > 0 and emp_count > 0,
        ),
        workload_context=VolumeWorkloadContext(
            impacted_entity_count=emp_count if emp_count > 0 else None,
            impacted_group_label="Imported team",
            volume_note=f"{below} employee(s) currently below goal in this import window.",
        ),
        time_context=TimeContext(
            observed_window_label="Latest import summary",
            compared_window_label="Minimum trend baseline",
            window_end=_ref_ts(today),
            last_updated_at=_ref_ts(today),
            stale_after_hours=12,
        ),
        data_completeness=DataCompletenessNote(
            status="incomplete" if days <= 1 else "partial" if missing_fields else "complete",
            summary="Limited history may reduce trend reliability." if days <= 1 else "Import summary available.",
            missing_fields=missing_fields,
            missing_ratio=(len(missing_fields) / 2.0) if missing_fields else 0.0,
        ),
        drill_down=DrillDownTarget(
            screen="import_data_trust",
            label="Open import data trust",
            section="data_quality",
            filters={"source": "interpreted_signal", "signal": "suspicious_import_data"},
        ),
        source_references=[
            SourceReference(
                source_type="upload",
                source_name="import_complete_summary",
                field_paths=["days", "emp_count", "below", "risks"],
                evidence_excerpt=f"days={days} | employees={emp_count}",
            )
        ],
        optional_review_areas=["Date coverage", "Missing-field diagnostics"],
        metadata={"days": days, "emp_count": emp_count},
    )


def interpret_outcome_after_logged_activity(*, action: dict, today: date) -> InsightCardContract:
    action_id = str(action.get("id") or "")
    emp_id = str(action.get("employee_id") or "")
    name = str(action.get("employee_name") or emp_id or "Unknown")
    dept = str(action.get("department") or "Team")
    baseline = _safe_float(action.get("baseline_uph"), 0.0)
    latest = _safe_float(action.get("latest_uph"), 0.0)
    delta = latest - baseline if baseline > 0 and latest > 0 else 0.0

    if baseline > 0 and latest > 0 and delta > 0:
        happened = f"Output is up by {delta:.1f} UPH after prior logged activity."
    elif baseline > 0 and latest > 0 and delta == 0:
        happened = "Output is unchanged after prior logged activity."
    elif baseline > 0 and latest > 0:
        happened = f"Output is down by {abs(delta):.1f} UPH after prior logged activity."
    else:
        happened = "Outcome window exists, but before/after performance pair is incomplete."

    return _card(
        insight_id=f"post_activity:{action_id or emp_id}",
        insight_kind="post_activity_outcome",
        title=f"Post-activity outcome: {name}",
        what_happened=happened,
        compared_to_what="Compared with pre-activity baseline window and latest observed value.",
        why_flagged="Surfaced to show measured change after logged follow-up activity.",
        confidence=_confidence_from_inputs(
            sample_size=2 if baseline > 0 and latest > 0 else 1,
            min_expected=2,
            missing_ratio=0.0 if baseline > 0 and latest > 0 else 0.5,
            has_core_pair=baseline > 0 and latest > 0,
        ),
        workload_context=VolumeWorkloadContext(
            impacted_entity_count=1,
            impacted_group_label=dept,
            observed_volume=latest if latest > 0 else None,
            observed_volume_unit="UPH" if latest > 0 else "",
            baseline_volume=baseline if baseline > 0 else None,
            baseline_volume_unit="UPH" if baseline > 0 else "",
            volume_note="Outcome measured against available UPH context.",
        ),
        time_context=TimeContext(
            observed_window_label="Post-activity window",
            compared_window_label="Pre-activity baseline",
            window_end=_ref_ts(today),
            last_updated_at=_ref_ts(today),
            stale_after_hours=6,
        ),
        data_completeness=DataCompletenessNote(
            status="complete" if baseline > 0 and latest > 0 else "partial",
            summary="Before/after values available." if baseline > 0 and latest > 0 else "Before/after pair is incomplete.",
            missing_fields=[
                name
                for name, value in {"baseline_uph": baseline, "latest_uph": latest}.items()
                if value <= 0
            ],
        ),
        drill_down=DrillDownTarget(
            screen="employee_detail",
            label="Open outcome timeline",
            entity_id=emp_id,
            section="coaching_impact",
            filters={"source": "interpreted_signal", "signal": "post_activity_outcome", "action_id": action_id},
        ),
        source_references=[
            SourceReference(
                source_type="table",
                source_name="actions",
                source_id=action_id,
                field_paths=["baseline_uph", "latest_uph", "last_event_at", "success_metric"],
                evidence_excerpt=f"baseline={baseline:.1f} | latest={latest:.1f}",
            )
        ],
        optional_review_areas=["Recent notes", "Shift context changes"],
        metadata={"delta_uph": delta},
    )


def interpret_today_view_signals(
    *,
    queue_items: list[dict],
    goal_status: list[dict],
    import_summary: dict | None,
    today: date,
) -> dict[str, list[InsightCardContract]]:
    """Build deterministic interpreted cards for Today sections."""
    needs_attention = [
        interpret_follow_up_due(action=item, today=today)
        for item in (queue_items or [])[:4]
    ]

    changed_from_normal_rows = [
        row
        for row in (goal_status or [])
        if str(row.get("trend") or "") in {"down", "up"}
    ]
    changed_from_normal_rows.sort(key=lambda row: abs(_safe_float(row.get("change_pct"), 0.0)), reverse=True)
    changed_from_normal = [
        interpret_changed_from_normal(row=row, today=today)
        for row in changed_from_normal_rows[:3]
    ]

    unresolved_actions = [
        item
        for item in (queue_items or [])
        if str(item.get("_queue_status") or "") == "overdue" or bool(item.get("_is_repeat_issue"))
    ]
    unresolved_items = [
        interpret_unresolved_issue(action=item, today=today)
        for item in unresolved_actions[:4]
    ]

    data_warnings: list[InsightCardContract] = []
    if import_summary:
        summary_card = interpret_suspicious_or_incomplete_data(import_summary=import_summary, today=today)
        if _safe_int(import_summary.get("days"), 0) <= 1 or summary_card.data_completeness.status != "complete":
            data_warnings.append(summary_card)

    insufficient_rows = [row for row in (goal_status or []) if str(row.get("trend") or "") == "insufficient_data"]
    if insufficient_rows:
        missing_ratio = len(insufficient_rows) / max(len(goal_status or []), 1)
        data_warnings.append(
            _card(
                insight_id="data_warning:insufficient_trend_rows",
                insight_kind="suspicious_import_data",
                title="Data warning: some trend rows are incomplete",
                what_happened=f"{len(insufficient_rows)} trend rows do not yet have enough points for full classification.",
                compared_to_what="Compared with rows that have enough observations to classify trend direction.",
                why_flagged="Surfaced because incomplete trend rows can reduce changed-from-normal confidence.",
                confidence=_confidence_from_inputs(
                    sample_size=len(insufficient_rows),
                    min_expected=1,
                    missing_ratio=missing_ratio,
                    has_core_pair=True,
                ),
                workload_context=VolumeWorkloadContext(
                    impacted_entity_count=len(insufficient_rows),
                    impacted_group_label="Goal status rows",
                    volume_note="Rows with insufficient trend context are down-ranked.",
                ),
                time_context=TimeContext(
                    observed_window_label="Current goal-status snapshot",
                    compared_window_label="Complete trend rows",
                    window_end=_ref_ts(today),
                    last_updated_at=_ref_ts(today),
                    stale_after_hours=12,
                ),
                data_completeness=DataCompletenessNote(
                    status="partial",
                    summary="Trend classification is incomplete for part of the dataset.",
                    missing_fields=["trend_points"],
                    missing_ratio=missing_ratio,
                ),
                drill_down=DrillDownTarget(
                    screen="import_data_trust",
                    label="Inspect data quality details",
                    section="trend_completeness",
                    filters={"source": "interpreted_signal", "signal": "suspicious_import_data"},
                ),
                source_references=[
                    SourceReference(
                        source_type="metric",
                        source_name="goal_status",
                        field_paths=["trend", "change_pct", "Average UPH"],
                        evidence_excerpt=f"insufficient_rows={len(insufficient_rows)}",
                    )
                ],
                optional_review_areas=["Date coverage", "Trend-window settings"],
                metadata={"insufficient_rows": len(insufficient_rows)},
            )
        )

    import_job_id = str((import_summary or {}).get("import_job", {}).get("job_id", "") or "")
    import_file = str((import_summary or {}).get("import_file", "") or "")

    def _enrich(card: InsightCardContract) -> InsightCardContract:
        warning_text = card.data_completeness.summary if card.data_completeness.summary else ""
        return replace(
            card,
            traceability=replace(
                card.traceability,
                related_import_job_id=import_job_id,
                related_import_file=import_file,
                warnings=[w for w in [warning_text, *card.traceability.warnings] if str(w).strip()],
            ),
            metadata={
                **card.metadata,
                "import_job_id": import_job_id,
                "import_file": import_file,
                "linked_entity_label": card.title,
            },
        )

    needs_attention = rank_and_filter_signals([_enrich(card) for card in needs_attention], max_items=4)
    changed_from_normal = rank_and_filter_signals([_enrich(card) for card in changed_from_normal], max_items=3)
    unresolved_items = rank_and_filter_signals([_enrich(card) for card in unresolved_items], max_items=4)
    data_warnings = rank_and_filter_signals([_enrich(card) for card in data_warnings], keep_weak=True, max_items=4)

    return {
        "needs_attention": needs_attention,
        "changed_from_normal": changed_from_normal,
        "unresolved_items": unresolved_items,
        "data_warnings": data_warnings,
    }


def interpret_employee_detail_view_signals(*, action_rows: list[dict], today: date) -> list[InsightCardContract]:
    """Reusable interpretation entry point for Employee Detail view."""
    cards: list[InsightCardContract] = []
    for action in (action_rows or [])[:5]:
        cards.append(interpret_follow_up_due(action=action, today=today))
        cards.append(interpret_outcome_after_logged_activity(action=action, today=today))
    return rank_and_filter_signals(cards, max_items=8)


def interpret_team_process_view_signals(*, goal_status: list[dict], today: date) -> list[InsightCardContract]:
    """Reusable interpretation entry point for Team / Process view."""
    rows = [row for row in (goal_status or []) if str(row.get("goal_status") or "") == "below_goal"]
    rows.sort(key=lambda row: abs(_safe_float(row.get("change_pct"), 0.0)), reverse=True)
    cards = [interpret_below_expected_performance(row=row, today=today) for row in rows[:8]]
    return rank_and_filter_signals(cards, max_items=8)


def interpret_import_data_trust_view_signals(
    *,
    import_summary: dict | None,
    goal_status: list[dict],
    today: date,
) -> list[InsightCardContract]:
    """Reusable interpretation entry point for Import / Data Trust view."""
    cards: list[InsightCardContract] = []
    if import_summary:
        cards.append(interpret_suspicious_or_incomplete_data(import_summary=import_summary, today=today))

    insufficient_rows = [row for row in (goal_status or []) if str(row.get("trend") or "") == "insufficient_data"]
    if insufficient_rows:
        cards.append(
            _card(
                insight_id="import_trust:trend_incomplete",
                insight_kind="suspicious_import_data",
                title="Trend completeness requires more observations",
                what_happened=f"{len(insufficient_rows)} row(s) have insufficient trend data.",
                compared_to_what="Compared with rows that meet trend classification minimums.",
                why_flagged="Surfaced because these rows lower interpretation confidence.",
                confidence=_confidence_from_inputs(
                    sample_size=len(insufficient_rows),
                    min_expected=1,
                    missing_ratio=(len(insufficient_rows) / max(len(goal_status or []), 1)),
                    has_core_pair=True,
                ),
                workload_context=VolumeWorkloadContext(
                    impacted_entity_count=len(insufficient_rows),
                    impacted_group_label="Goal status rows",
                    volume_note="Rows with insufficient trend points are identified for transparency.",
                ),
                time_context=TimeContext(
                    observed_window_label="Current import-backed snapshot",
                    compared_window_label="Trend-ready rows",
                    window_end=_ref_ts(today),
                    last_updated_at=_ref_ts(today),
                    stale_after_hours=12,
                ),
                data_completeness=DataCompletenessNote(
                    status="partial",
                    summary="Trend context is incomplete for some rows.",
                    missing_fields=["trend_points"],
                    missing_ratio=(len(insufficient_rows) / max(len(goal_status or []), 1)),
                ),
                drill_down=DrillDownTarget(
                    screen="import_data_trust",
                    label="View completeness details",
                    section="trend_completeness",
                    filters={"source": "interpreted_signal", "signal": "suspicious_import_data"},
                ),
                source_references=[
                    SourceReference(
                        source_type="metric",
                        source_name="goal_status",
                        field_paths=["trend", "change_pct"],
                        evidence_excerpt=f"insufficient_rows={len(insufficient_rows)}",
                    )
                ],
                optional_review_areas=["Import date coverage", "Missing key columns"],
            )
        )

    return rank_and_filter_signals(cards, keep_weak=True, max_items=6)
