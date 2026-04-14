from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from services.action_state_service import build_employee_action_state_lookup
from services.attention_scoring_service import AttentionItem, AttentionSummary, score_attention_items


_HIGH_FLOOR = 75
_MEDIUM_FLOOR = 50
_SUPPRESSION_FLOOR = 30

_QUEUE_STATUS_SCORES = {
    "overdue": 24,
    "due_today": 16,
    "pending": 8,
}

_QUEUE_PRIORITY_SCORES = {
    "high": 12,
    "medium": 6,
    "low": 2,
}


@dataclass(frozen=True)
class DecisionItem:
    employee_id: str
    process_name: str
    final_score: int
    final_tier: str
    attention_score: int
    action_score: int
    action_priority: str
    action_queue_status: str
    primary_reason: str
    confidence_label: str
    confidence_basis: str
    normalized_action_state: str
    normalized_action_state_detail: str
    attention_item: AttentionItem
    source_snapshot: dict[str, Any]

    def to_attention_item(self) -> AttentionItem:
        merged_snapshot = dict(self.source_snapshot or {})
        merged_snapshot.setdefault("employee_id", self.employee_id)
        merged_snapshot.setdefault("EmployeeID", self.employee_id)
        merged_snapshot.setdefault("process_name", self.process_name)
        merged_snapshot.setdefault("Department", self.process_name)
        if self.action_queue_status:
            merged_snapshot["_queue_status"] = self.action_queue_status
        if self.action_priority:
            merged_snapshot["priority"] = self.action_priority
        if self.confidence_label:
            merged_snapshot["confidence_label"] = self.confidence_label
        if self.confidence_basis:
            merged_snapshot["confidence_basis"] = self.confidence_basis
        if self.normalized_action_state:
            merged_snapshot["normalized_action_state"] = self.normalized_action_state
        if self.normalized_action_state_detail:
            merged_snapshot["normalized_action_state_detail"] = self.normalized_action_state_detail
        if self.primary_reason:
            merged_snapshot["primary_decision_reason"] = self.primary_reason

        summary = self.primary_reason or self.attention_item.attention_summary
        reasons = list(self.attention_item.attention_reasons or [])
        if self.primary_reason:
            reasons = [self.primary_reason, *[reason for reason in reasons if str(reason).strip().lower() != self.primary_reason.strip().lower()]]

        return replace(
            self.attention_item,
            attention_score=int(self.final_score),
            attention_tier=self.final_tier,
            attention_reasons=reasons,
            attention_summary=summary,
            snapshot=merged_snapshot,
        )


def _final_tier(score: int) -> str:
    if score >= _HIGH_FLOOR:
        return "high"
    if score >= _MEDIUM_FLOOR:
        return "medium"
    if score >= _SUPPRESSION_FLOOR:
        return "low"
    return "suppressed"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _snapshot_name(row: dict[str, Any], queue_item: dict[str, Any] | None) -> str:
    for value in (
        row.get("Employee"),
        row.get("Employee Name"),
        row.get("employee_name"),
        (queue_item or {}).get("employee_name"),
        row.get("EmployeeID"),
        row.get("employee_id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_snapshot(row: dict[str, Any], queue_item: dict[str, Any] | None) -> dict[str, Any]:
    queue_item = dict(queue_item or {})
    employee_id = str(row.get("EmployeeID") or row.get("employee_id") or queue_item.get("employee_id") or "").strip()
    process_name = str(row.get("Department") or row.get("process_name") or queue_item.get("department") or queue_item.get("process_name") or "Unassigned").strip() or "Unassigned"
    normalized = dict(row or {})
    normalized["employee_id"] = employee_id
    normalized.setdefault("EmployeeID", employee_id)
    normalized.setdefault("Employee", _snapshot_name(row, queue_item) or employee_id)
    normalized.setdefault("Employee Name", _snapshot_name(row, queue_item) or employee_id)
    normalized["process_name"] = process_name
    normalized.setdefault("Department", process_name)
    if queue_item:
        normalized["_queue_status"] = str(queue_item.get("_queue_status") or "").strip().lower()
        normalized["priority"] = str(queue_item.get("priority") or "").strip().lower()
        normalized["follow_up_due_at"] = str(queue_item.get("follow_up_due_at") or "").strip()
        normalized["failed_cycles"] = _safe_int(queue_item.get("failed_cycles"), _safe_int(normalized.get("failed_cycles"), 0))
        if bool(queue_item.get("_is_repeat_issue")) and _safe_int(normalized.get("repeat_count"), 0) < 2:
            normalized["repeat_count"] = 2
        normalized["queue_short_reason"] = str(queue_item.get("_short_reason") or "").strip()
        normalized["queue_why_this_is_here"] = str(queue_item.get("_why_this_is_here") or "").strip()
    return normalized


def _build_snapshot_population(goal_status: list[dict[str, Any]], queue_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue_by_employee: dict[str, dict[str, Any]] = {}
    for item in list(queue_items or []):
        employee_id = str(item.get("employee_id") or "").strip()
        if employee_id and employee_id not in queue_by_employee:
            queue_by_employee[employee_id] = dict(item)

    population: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in list(goal_status or []):
        employee_id = str(row.get("EmployeeID") or row.get("employee_id") or "").strip()
        if not employee_id:
            continue
        seen.add(employee_id)
        population.append(_normalize_snapshot(row, queue_by_employee.get(employee_id)))

    for employee_id, queue_item in queue_by_employee.items():
        if employee_id in seen:
            continue
        population.append(
            _normalize_snapshot(
                {
                    "EmployeeID": employee_id,
                    "Employee": _snapshot_name({}, queue_item) or employee_id,
                    "Employee Name": _snapshot_name({}, queue_item) or employee_id,
                    "Department": str(queue_item.get("department") or queue_item.get("process_name") or "Unassigned"),
                    "trend": "insufficient_data",
                    "goal_status": "no_goal",
                    "confidence_label": "Low",
                    "data_completeness_status": "limited",
                    "data_completeness_note": "Open queue item without enough recent history for a stronger comparison.",
                    "repeat_count": 2 if bool(queue_item.get("_is_repeat_issue")) else 0,
                    "snapshot_date": str(queue_item.get("follow_up_due_at") or "")[:10],
                },
                queue_item,
            )
        )

    return population


def _queue_score(queue_item: dict[str, Any] | None) -> tuple[int, str, str]:
    queue_item = dict(queue_item or {})
    queue_status = str(queue_item.get("_queue_status") or "").strip().lower()
    priority = str(queue_item.get("priority") or "").strip().lower()
    score = _QUEUE_STATUS_SCORES.get(queue_status, 0) + _QUEUE_PRIORITY_SCORES.get(priority, 0)
    return score, priority, queue_status


def _confidence_basis(snapshot: dict[str, Any]) -> str:
    for value in (
        snapshot.get("confidence_basis"),
        snapshot.get("data_completeness_note"),
        snapshot.get("trend_explanation"),
    ):
        text = str(value or "").strip()
        if text:
            return text

    included_days = _safe_int(
        snapshot.get("included_day_count")
        or snapshot.get("Record Count")
        or snapshot.get("sample_size")
        or snapshot.get("record_count"),
        0,
    )
    has_target = bool(snapshot.get("expected_uph") or snapshot.get("Target UPH"))
    if included_days > 0 and has_target:
        return f"Based on {included_days} included day(s) with configured target context."
    if included_days > 0:
        return f"Based on {included_days} recent record(s) with limited target context."
    if str(snapshot.get("_queue_status") or "").strip():
        return "Open queue item with limited comparable performance history."
    return "Based on the currently available recent records."


def _primary_reason(item: AttentionItem, snapshot: dict[str, Any]) -> str:
    reasons = [str(reason or "").strip() for reason in list(item.attention_reasons or []) if str(reason or "").strip()]
    if reasons:
        return reasons[0]
    for value in (snapshot.get("queue_short_reason"), snapshot.get("queue_why_this_is_here"), item.attention_summary):
        text = str(value or "").strip()
        if text:
            return text
    return "Current evidence did not produce a stronger explanatory reason."


def build_decision_items(
    *,
    goal_status: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
    open_exception_rows: list[dict[str, Any]] | None = None,
    tenant_id: str = "",
    today: date | None = None,
    weak_data_mode: bool = False,
) -> list[DecisionItem]:
    snapshots = _build_snapshot_population(goal_status, queue_items)
    attention = score_attention_items(
        snapshots=snapshots,
        queue_items=queue_items,
        open_exception_rows=open_exception_rows,
        keep_low=bool(weak_data_mode),
        max_items=None,
    )
    action_state_lookup = build_employee_action_state_lookup(
        [str(snapshot.get("employee_id") or "").strip() for snapshot in snapshots],
        tenant_id=tenant_id,
        today=today,
    )
    queue_by_employee = {
        str(item.get("employee_id") or "").strip(): dict(item)
        for item in list(queue_items or [])
        if str(item.get("employee_id") or "").strip()
    }

    decision_items: list[DecisionItem] = []
    for attention_item in list(attention.ranked_items or []):
        snapshot = dict(attention_item.snapshot or {})
        employee_id = str(attention_item.employee_id or snapshot.get("employee_id") or "").strip()
        queue_item = queue_by_employee.get(employee_id, {})
        action_score, action_priority, queue_status = _queue_score(queue_item)
        final_score = max(0, min(140, int(attention_item.attention_score) + action_score))
        final_tier = _final_tier(final_score)
        action_state = dict(action_state_lookup.get(employee_id) or {})
        primary_reason = _primary_reason(attention_item, snapshot)
        confidence_label = str(snapshot.get("confidence_label") or "Low").strip().title() or "Low"
        confidence_basis = _confidence_basis(snapshot)

        decision_items.append(
            DecisionItem(
                employee_id=employee_id,
                process_name=str(attention_item.process_name or snapshot.get("Department") or snapshot.get("process_name") or "Unassigned"),
                final_score=final_score,
                final_tier=final_tier,
                attention_score=int(attention_item.attention_score),
                action_score=action_score,
                action_priority=action_priority,
                action_queue_status=queue_status,
                primary_reason=primary_reason,
                confidence_label=confidence_label,
                confidence_basis=confidence_basis,
                normalized_action_state=str(action_state.get("state") or "").strip(),
                normalized_action_state_detail=str(action_state.get("state_detail") or "").strip(),
                attention_item=attention_item,
                source_snapshot=snapshot,
            )
        )

    decision_items.sort(
        key=lambda item: (
            -int(item.final_score),
            str(item.action_queue_status or ""),
            str(item.employee_id or "").lower(),
            str(item.process_name or "").lower(),
        )
    )
    return decision_items


def build_decision_summary(decision_items: list[DecisionItem]) -> AttentionSummary:
    ranked = [item.to_attention_item() for item in list(decision_items or []) if item.final_tier != "suppressed"]
    suppressed_count = sum(1 for item in list(decision_items or []) if item.final_tier == "suppressed")
    return AttentionSummary(
        ranked_items=ranked,
        is_healthy=not ranked,
        healthy_message="" if ranked else "No strong signals currently surfaced.",
        suppressed_count=suppressed_count,
        total_evaluated=len(list(decision_items or [])),
    )