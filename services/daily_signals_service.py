"""Precompute and persist daily signals for read-only Today rendering."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

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
from repositories.daily_signals_repo import (
    batch_upsert_daily_signals,
    delete_daily_signals,
    list_daily_signals,
)
from services.action_query_service import get_open_actions
from services.action_recommendation_service import get_ignored_high_performers, get_repeat_offenders
from services.attention_scoring_service import AttentionFactor, AttentionItem, AttentionSummary
from services.daily_snapshot_service import get_latest_snapshot_goal_status
from services.decision_engine_service import DecisionItem, build_decision_items, build_decision_summary
from services.exception_tracking_service import list_open_operational_exceptions
from services.today_home_service import build_today_attention_summary, build_today_home_sections
from services.today_page_meaning_service import is_weak_data_mode as _canonical_is_weak_data_mode
from services.today_queue_service import build_action_queue


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _infer_days_from_goal_status(goal_status: list[dict[str, Any]]) -> int:
    counts: list[int] = []
    for row in goal_status or []:
        value = _safe_int(row.get("Record Count"), 0)
        if value > 0:
            counts.append(value)
    if counts:
        return max(counts)
    if goal_status:
        return 1
    return 0


def _build_import_summary(*, tenant_id: str, goal_status: list[dict[str, Any]]) -> dict[str, Any]:
    emp_count = len({str(row.get("EmployeeID") or "").strip() for row in goal_status if str(row.get("EmployeeID") or "").strip()})
    below_count = sum(1 for row in goal_status if str(row.get("goal_status") or "") == "below_goal")
    inferred_days = _infer_days_from_goal_status(goal_status)

    base_summary: dict[str, Any] = {
        "days": inferred_days,
        "emp_count": emp_count,
        "below": below_count,
        "risks": 0,
        "source_mode": "real",
        "source_label": "",
    }

    try:
        from services.import_service import _decode_jsonish, _list_recent_uploads

        uploads = _list_recent_uploads(tenant_id=tenant_id, days=30)
        if not uploads:
            return base_summary

        latest = next((row for row in uploads if bool(row.get("is_active"))), uploads[0])
        meta = _decode_jsonish(latest.get("header_mapping")) if latest else {}
        stats = dict(meta.get("stats") or {}) if isinstance(meta, dict) else {}

        rows_processed = _safe_int(stats.get("candidate_rows"), 0)
        valid_rows = _safe_int(stats.get("accepted_rows"), _safe_int(stats.get("inserted_rows"), 0))
        warning_rows = _safe_int(stats.get("warnings"), 0)
        rejected_rows = _safe_int(stats.get("rejected_rows"), max(0, rows_processed - valid_rows))
        confidence_score = _safe_int(stats.get("confidence_score"), 0)
        trust_status = str(stats.get("trust_status") or "").strip().lower()
        inferred_days_from_stats = inferred_days
        if inferred_days_from_stats <= 0 and (rows_processed > 0 or valid_rows > 0):
            # When snapshot goal rows are not yet materialized, preserve imported
            # presence so Today does not incorrectly present "no imported records yet".
            inferred_days_from_stats = 1

        trust_payload = {
            "status": trust_status,
            "confidence_score": confidence_score,
        } if trust_status else {}

        source_mode_raw = str(
            meta.get("source_mode")
            or stats.get("source_mode")
            or "real"
        ).strip().lower()
        source_mode = "demo" if source_mode_raw == "demo" else "real"
        source_label = str(latest.get("filename") or "").strip()

        return {
            **base_summary,
            "days": int(inferred_days_from_stats),
            "rows_processed": rows_processed,
            "valid_rows": valid_rows,
            "warning_rows": warning_rows,
            "rejected_rows": rejected_rows,
            "trust": trust_payload,
            "source_mode": source_mode,
            "source_label": source_label,
        }
    except Exception:
        return base_summary


def _is_weak_data_mode(import_summary: dict[str, Any]) -> bool:
    # Canonical product-facing weak-data classification lives in
    # today_page_meaning_service. Keep this wrapper so persisted/transient Today
    # signal computation stays aligned with the UI-facing interpretation.
    return bool(_canonical_is_weak_data_mode(import_summary=dict(import_summary or {})))


def _serialize_insight_card(card: InsightCardContract) -> dict[str, Any]:
    return {
        "insight_id": card.insight_id,
        "insight_kind": card.insight_kind,
        "title": card.title,
        "what_happened": card.what_happened,
        "compared_to_what": card.compared_to_what,
        "why_flagged": card.why_flagged,
        "confidence": asdict(card.confidence),
        "workload_context": asdict(card.workload_context),
        "time_context": {
            "observed_window_label": card.time_context.observed_window_label,
            "window_start": card.time_context.window_start.isoformat() if card.time_context.window_start else "",
            "window_end": card.time_context.window_end.isoformat() if card.time_context.window_end else "",
            "compared_window_label": card.time_context.compared_window_label,
            "compared_window_start": card.time_context.compared_window_start.isoformat() if card.time_context.compared_window_start else "",
            "compared_window_end": card.time_context.compared_window_end.isoformat() if card.time_context.compared_window_end else "",
            "last_updated_at": card.time_context.last_updated_at.isoformat() if card.time_context.last_updated_at else "",
            "stale_after_hours": card.time_context.stale_after_hours,
        },
        "data_completeness": asdict(card.data_completeness),
        "drill_down": asdict(card.drill_down),
        "traceability": asdict(card.traceability),
        "source_references": [asdict(ref) for ref in card.source_references],
        "metadata": dict(card.metadata or {}),
    }


def _deserialize_insight_card(payload: dict[str, Any]) -> InsightCardContract:
    time_payload = payload.get("time_context") or {}
    return InsightCardContract(
        insight_id=str(payload.get("insight_id") or ""),
        insight_kind=str(payload.get("insight_kind") or "suspicious_import_data"),
        title=str(payload.get("title") or ""),
        what_happened=str(payload.get("what_happened") or ""),
        compared_to_what=str(payload.get("compared_to_what") or ""),
        why_flagged=str(payload.get("why_flagged") or ""),
        confidence=ConfidenceInfo(**(payload.get("confidence") or {"level": "low"})),
        workload_context=VolumeWorkloadContext(**(payload.get("workload_context") or {})),
        time_context=TimeContext(
            observed_window_label=str(time_payload.get("observed_window_label") or ""),
            window_start=_to_dt(time_payload.get("window_start")),
            window_end=_to_dt(time_payload.get("window_end")),
            compared_window_label=str(time_payload.get("compared_window_label") or ""),
            compared_window_start=_to_dt(time_payload.get("compared_window_start")),
            compared_window_end=_to_dt(time_payload.get("compared_window_end")),
            last_updated_at=_to_dt(time_payload.get("last_updated_at")),
            stale_after_hours=time_payload.get("stale_after_hours"),
        ),
        data_completeness=DataCompletenessNote(**(payload.get("data_completeness") or {"status": "unknown", "summary": ""})),
        drill_down=DrillDownTarget(**(payload.get("drill_down") or {"screen": "today", "label": "Open details"})),
        traceability=TraceabilityContext(**(payload.get("traceability") or {})),
        source_references=[SourceReference(**ref) for ref in (payload.get("source_references") or [])],
        metadata=dict(payload.get("metadata") or {}),
    )


def _serialize_attention_item(item: AttentionItem) -> dict[str, Any]:
    return {
        "employee_id": item.employee_id,
        "process_name": item.process_name,
        "attention_score": int(item.attention_score),
        "attention_tier": item.attention_tier,
        "attention_reasons": list(item.attention_reasons or []),
        "attention_summary": item.attention_summary,
        "factors_applied": [asdict(factor) for factor in (item.factors_applied or [])],
        "snapshot": dict(item.snapshot or {}),
    }


def _deserialize_attention_item(payload: dict[str, Any]) -> AttentionItem:
    return AttentionItem(
        employee_id=str(payload.get("employee_id") or ""),
        process_name=str(payload.get("process_name") or ""),
        attention_score=int(payload.get("attention_score") or 0),
        attention_tier=str(payload.get("attention_tier") or "low"),
        attention_reasons=[str(reason) for reason in (payload.get("attention_reasons") or [])],
        attention_summary=str(payload.get("attention_summary") or ""),
        factors_applied=[AttentionFactor(**factor) for factor in (payload.get("factors_applied") or [])],
        snapshot=dict(payload.get("snapshot") or {}),
    )


def _serialize_decision_item(item: DecisionItem) -> dict[str, Any]:
    return {
        "employee_id": item.employee_id,
        "process_name": item.process_name,
        "final_score": int(item.final_score),
        "final_tier": item.final_tier,
        "attention_score": int(item.attention_score),
        "action_score": int(item.action_score),
        "action_priority": item.action_priority,
        "action_queue_status": item.action_queue_status,
        "primary_reason": item.primary_reason,
        "confidence_label": item.confidence_label,
        "confidence_basis": item.confidence_basis,
        "normalized_action_state": item.normalized_action_state,
        "normalized_action_state_detail": item.normalized_action_state_detail,
        "attention_item": _serialize_attention_item(item.attention_item),
        "source_snapshot": dict(item.source_snapshot or {}),
    }


def _deserialize_decision_item(payload: dict[str, Any]) -> DecisionItem:
    return DecisionItem(
        employee_id=str(payload.get("employee_id") or ""),
        process_name=str(payload.get("process_name") or ""),
        final_score=int(payload.get("final_score") or 0),
        final_tier=str(payload.get("final_tier") or "suppressed"),
        attention_score=int(payload.get("attention_score") or 0),
        action_score=int(payload.get("action_score") or 0),
        action_priority=str(payload.get("action_priority") or ""),
        action_queue_status=str(payload.get("action_queue_status") or ""),
        primary_reason=str(payload.get("primary_reason") or ""),
        confidence_label=str(payload.get("confidence_label") or "Low"),
        confidence_basis=str(payload.get("confidence_basis") or ""),
        normalized_action_state=str(payload.get("normalized_action_state") or ""),
        normalized_action_state_detail=str(payload.get("normalized_action_state_detail") or ""),
        attention_item=_deserialize_attention_item(dict(payload.get("attention_item") or {})),
        source_snapshot=dict(payload.get("source_snapshot") or {}),
    )


def compute_daily_signals(*, signal_date: date, tenant_id: str) -> dict[str, Any]:
    """Compute and persist all Today signals for a single date.

    This function centralizes signal interpretation and attention scoring into a
    pre-processing step so the Today screen can remain read-only.
    """
    open_actions = get_open_actions(tenant_id=tenant_id, today=signal_date)
    repeat_offenders = get_repeat_offenders(tenant_id=tenant_id, today=signal_date, open_actions=open_actions)
    recognition_opportunities = get_ignored_high_performers(tenant_id=tenant_id, today=signal_date, open_actions=open_actions)
    queue_items = build_action_queue(
        open_actions=open_actions,
        repeat_offenders=repeat_offenders,
        recognition_opportunities=recognition_opportunities,
        tenant_id=tenant_id,
        today=signal_date,
    )

    goal_status, _history_rows, _snapshot_date = get_latest_snapshot_goal_status(
        tenant_id=tenant_id,
        days=30,
        rebuild_if_missing=False,
    )
    goal_status = goal_status or []

    import_summary = _build_import_summary(tenant_id=tenant_id, goal_status=goal_status)

    home_sections = build_today_home_sections(
        queue_items=queue_items,
        goal_status=goal_status,
        import_summary=import_summary,
        today=signal_date,
    )
    eligible_employee_ids = {
        str(item.drill_down.entity_id or "").strip()
        for section_key in ("needs_attention", "changed_from_normal", "unresolved_items")
        for item in (home_sections.get(section_key) or [])
        if str(item.drill_down.entity_id or "").strip()
    }
    if not eligible_employee_ids:
        # If all interpreted cards were filtered/suppressed, do not block
        # attention ranking for every employee. Allow scorer to evaluate full
        # goal_status so Today can still surface meaningful signals.
        eligible_employee_ids = None
    open_exception_rows = list_open_operational_exceptions(tenant_id=tenant_id, limit=200)
    attention_summary = build_today_attention_summary(
        goal_status=goal_status,
        queue_items=queue_items,
        open_exception_rows=open_exception_rows,
        eligible_employee_ids=eligible_employee_ids,
        weak_data_mode=_is_weak_data_mode(import_summary),
    )
    decision_items = build_decision_items(
        goal_status=goal_status,
        queue_items=queue_items,
        open_exception_rows=open_exception_rows,
        tenant_id=tenant_id,
        today=signal_date,
        weak_data_mode=_is_weak_data_mode(import_summary),
    )
    decision_summary = build_decision_summary(decision_items)

    rows: list[dict[str, Any]] = []
    for section_key in ("needs_attention", "changed_from_normal", "unresolved_items", "data_warnings", "suppressed_signals"):
        for card in (home_sections.get(section_key) or []):
            pattern_count = int((card.metadata or {}).get("repeat_count") or 0)
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "signal_date": signal_date.isoformat(),
                    "signal_key": f"card:{section_key}:{card.insight_id}",
                    "employee_id": str(card.drill_down.entity_id or (card.metadata or {}).get("employee_id") or ""),
                    "signal_type": str(card.insight_kind or ""),
                    "section": section_key,
                    "observed_value": _safe_float(card.workload_context.observed_volume),
                    "baseline_value": _safe_float(card.workload_context.baseline_volume),
                    "confidence": str(card.confidence.level or "low"),
                    "completeness": str(card.data_completeness.status or "limited"),
                    "pattern_count": pattern_count,
                    "flags": {
                        "repeat": pattern_count > 0,
                        "overdue": bool((card.metadata or {}).get("is_overdue") or str((card.metadata or {}).get("queue_status") or "") == "overdue"),
                    },
                    "payload": {"card": _serialize_insight_card(card)},
                }
            )

    for index, item in enumerate(attention_summary.ranked_items):
        snapshot = item.snapshot or {}
        rows.append(
            {
                "tenant_id": tenant_id,
                "signal_date": signal_date.isoformat(),
                "signal_key": f"attention:{index}:{item.employee_id}:{item.process_name}",
                "employee_id": item.employee_id,
                "signal_type": "attention",
                "section": "attention",
                "observed_value": _safe_float(snapshot.get("recent_average_uph") or snapshot.get("Average UPH")),
                "baseline_value": _safe_float(snapshot.get("expected_uph") or snapshot.get("Target UPH")),
                "confidence": str(snapshot.get("confidence_label") or "low").lower(),
                "completeness": str(snapshot.get("data_completeness_status") or snapshot.get("completeness") or "limited").lower(),
                "pattern_count": int(snapshot.get("repeat_count") or 0),
                "flags": {
                    "repeat": int(snapshot.get("repeat_count") or 0) > 0,
                    "overdue": str(snapshot.get("_queue_status") or "") == "overdue",
                    "due_today": str(snapshot.get("_queue_status") or "") == "due_today",
                },
                "payload": {"attention_item": _serialize_attention_item(item)},
            }
        )

    # Store a compact full payload row for fast Today read hydration.
    rows.append(
        {
            "tenant_id": tenant_id,
            "signal_date": signal_date.isoformat(),
            "signal_key": "today:payload",
            "employee_id": "__today__",
            "signal_type": "today_payload",
            "section": "meta",
            "observed_value": 0,
            "baseline_value": 0,
            "confidence": "low",
            "completeness": "complete",
            "pattern_count": 0,
            "flags": {},
            "payload": {
                "queue_items": queue_items,
                "goal_status": goal_status,
                "import_summary": import_summary,
                "home_sections": {
                    key: [_serialize_insight_card(card) for card in value]
                    for key, value in (home_sections or {}).items()
                },
                "attention_summary": {
                    "ranked_items": [_serialize_attention_item(item) for item in attention_summary.ranked_items],
                    "is_healthy": bool(attention_summary.is_healthy),
                    "healthy_message": str(attention_summary.healthy_message or ""),
                    "suppressed_count": int(attention_summary.suppressed_count or 0),
                    "total_evaluated": int(attention_summary.total_evaluated or 0),
                },
                "decision_items": [_serialize_decision_item(item) for item in decision_items],
            },
        }
    )

    delete_daily_signals(tenant_id=tenant_id, signal_date=signal_date.isoformat())
    batch_upsert_daily_signals(rows)
    try:
        from services.today_home_service import clear_today_read_caches

        clear_today_read_caches()
    except Exception:
        pass
    return {
        "signal_date": signal_date.isoformat(),
        "tenant_id": tenant_id,
        "row_count": len(rows),
    }


def build_transient_today_payload(*, signal_date: date, tenant_id: str) -> dict[str, Any]:
    """Build a non-persistent Today payload.

    Compatibility fallback when the ``daily_signals`` table is unavailable.
    This computes the same read model but does not write to the database.
    """
    open_actions = get_open_actions(tenant_id=tenant_id, today=signal_date)
    repeat_offenders = get_repeat_offenders(tenant_id=tenant_id, today=signal_date, open_actions=open_actions)
    recognition_opportunities = get_ignored_high_performers(tenant_id=tenant_id, today=signal_date, open_actions=open_actions)
    queue_items = build_action_queue(
        open_actions=open_actions,
        repeat_offenders=repeat_offenders,
        recognition_opportunities=recognition_opportunities,
        tenant_id=tenant_id,
        today=signal_date,
    )

    goal_status, _history_rows, _snapshot_date = get_latest_snapshot_goal_status(
        tenant_id=tenant_id,
        days=30,
        rebuild_if_missing=False,
    )
    goal_status = goal_status or []

    import_summary = _build_import_summary(tenant_id=tenant_id, goal_status=goal_status)

    home_sections = build_today_home_sections(
        queue_items=queue_items,
        goal_status=goal_status,
        import_summary=import_summary,
        today=signal_date,
    )
    eligible_employee_ids = {
        str(item.drill_down.entity_id or "").strip()
        for section_key in ("needs_attention", "changed_from_normal", "unresolved_items")
        for item in (home_sections.get(section_key) or [])
        if str(item.drill_down.entity_id or "").strip()
    }
    if not eligible_employee_ids:
        # Keep transient fallback semantics aligned with persisted signal
        # computation so empty interpreted-card sets do not suppress all rows.
        eligible_employee_ids = None
    open_exception_rows = list_open_operational_exceptions(tenant_id=tenant_id, limit=200)
    attention_summary = build_today_attention_summary(
        goal_status=goal_status,
        queue_items=queue_items,
        open_exception_rows=open_exception_rows,
        eligible_employee_ids=eligible_employee_ids,
        weak_data_mode=_is_weak_data_mode(import_summary),
    )
    decision_items = build_decision_items(
        goal_status=goal_status,
        queue_items=queue_items,
        open_exception_rows=open_exception_rows,
        tenant_id=tenant_id,
        today=signal_date,
        weak_data_mode=_is_weak_data_mode(import_summary),
    )
    decision_summary = build_decision_summary(decision_items)

    return {
        "tenant_id": tenant_id,
        "as_of_date": signal_date.isoformat(),
        "queue_items": queue_items,
        "goal_status": goal_status,
        "import_summary": import_summary,
        "home_sections": home_sections,
        "attention_summary": attention_summary,
        "decision_items": decision_items,
        "decision_summary": decision_summary,
    }


def read_precomputed_today_signals(*, tenant_id: str, signal_date: date) -> dict[str, Any] | None:
    rows = list_daily_signals(
        tenant_id=tenant_id,
        signal_date=signal_date.isoformat(),
        signal_type="today_payload",
        limit=5,
    )
    if not rows:
        return None

    payload = dict((rows[0].get("payload") or {}))
    home_sections_payload = dict(payload.get("home_sections") or {})
    home_sections: dict[str, list[InsightCardContract]] = {}
    for key, cards in home_sections_payload.items():
        home_sections[str(key)] = [_deserialize_insight_card(card) for card in (cards or [])]

    attention_payload = dict(payload.get("attention_summary") or {})
    attention_summary = AttentionSummary(
        ranked_items=[_deserialize_attention_item(item) for item in (attention_payload.get("ranked_items") or [])],
        is_healthy=bool(attention_payload.get("is_healthy")),
        healthy_message=str(attention_payload.get("healthy_message") or ""),
        suppressed_count=int(attention_payload.get("suppressed_count") or 0),
        total_evaluated=int(attention_payload.get("total_evaluated") or 0),
    )
    decision_items = [_deserialize_decision_item(item) for item in (payload.get("decision_items") or [])]

    return {
        "tenant_id": tenant_id,
        "as_of_date": signal_date.isoformat(),
        "queue_items": list(payload.get("queue_items") or []),
        "goal_status": list(payload.get("goal_status") or []),
        "import_summary": dict(payload.get("import_summary") or {}),
        "home_sections": home_sections,
        "attention_summary": attention_summary,
        "decision_items": decision_items,
        "decision_summary": build_decision_summary(decision_items) if decision_items else attention_summary,
    }
