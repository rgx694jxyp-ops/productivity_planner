from datetime import date

from services.attention_scoring_service import AttentionItem
from services.decision_engine_service import build_decision_items, build_decision_summary


def _goal_row(
    employee_id: str,
    *,
    trend: str = "declining",
    confidence: str = "high",
    avg: float = 40,
    target: float = 50,
    repeat_count: int = 0,
    completeness: str = "partial",
) -> dict:
    return {
        "EmployeeID": employee_id,
        "Employee": employee_id,
        "Department": "Packing",
        "trend": trend,
        "confidence_label": confidence,
        "Average UPH": avg,
        "Target UPH": target,
        "goal_status": "below_goal",
        "repeat_count": repeat_count,
        "data_completeness_status": completeness,
        "data_completeness_note": "Partial history.",
        "included_day_count": 3,
        "snapshot_date": "2026-04-13",
    }


def _queue_item(employee_id: str, *, status: str = "overdue", priority: str = "high") -> dict:
    return {
        "employee_id": employee_id,
        "employee_name": employee_id,
        "department": "Packing",
        "_queue_status": status,
        "priority": priority,
        "_short_reason": "Follow-up pending",
        "_why_this_is_here": "Open follow-up remains unresolved.",
    }


def test_decision_engine_scores_full_population_not_filtered(monkeypatch):
    monkeypatch.setattr(
        "services.decision_engine_service.build_employee_action_state_lookup",
        lambda employee_ids, **kwargs: {employee_id: {"state": "", "state_detail": ""} for employee_id in employee_ids},
    )

    decision_items = build_decision_items(
        goal_status=[_goal_row("E1"), _goal_row("E2", trend="improving", confidence="medium", avg=48, target=50)],
        queue_items=[],
        open_exception_rows=[],
        tenant_id="tenant-1",
        today=date(2026, 4, 13),
    )

    assert [item.employee_id for item in decision_items] == ["E1", "E2"]


def test_decision_engine_merges_queue_priority_into_final_score(monkeypatch):
    monkeypatch.setattr(
        "services.decision_engine_service.build_employee_action_state_lookup",
        lambda employee_ids, **kwargs: {employee_id: {"state": "follow_up_scheduled", "state_detail": "Due today"} for employee_id in employee_ids},
    )

    decision_items = build_decision_items(
        goal_status=[_goal_row("E1", trend="declining"), _goal_row("E2", trend="declining")],
        queue_items=[_queue_item("E2", status="overdue", priority="high")],
        open_exception_rows=[],
        tenant_id="tenant-1",
        today=date(2026, 4, 13),
    )

    assert decision_items[0].employee_id == "E2"
    assert decision_items[0].final_score > decision_items[0].attention_score
    assert decision_items[0].normalized_action_state == "follow_up_scheduled"


def test_decision_engine_includes_action_only_employee(monkeypatch):
    monkeypatch.setattr(
        "services.decision_engine_service.build_employee_action_state_lookup",
        lambda employee_ids, **kwargs: {employee_id: {"state": "overdue_follow_up", "state_detail": "Overdue"} for employee_id in employee_ids},
    )

    decision_items = build_decision_items(
        goal_status=[_goal_row("E1")],
        queue_items=[_queue_item("E9", status="overdue", priority="high")],
        open_exception_rows=[],
        tenant_id="tenant-1",
        today=date(2026, 4, 13),
    )

    assert {item.employee_id for item in decision_items} == {"E1", "E9"}
    action_only = next(item for item in decision_items if item.employee_id == "E9")
    assert action_only.action_queue_status == "overdue"
    assert action_only.confidence_basis


def test_decision_summary_uses_final_score_and_preserves_confidence_basis(monkeypatch):
    monkeypatch.setattr(
        "services.decision_engine_service.build_employee_action_state_lookup",
        lambda employee_ids, **kwargs: {employee_id: {"state": "in_progress", "state_detail": "Underlying: Logged"} for employee_id in employee_ids},
    )

    decision_items = build_decision_items(
        goal_status=[_goal_row("E1", repeat_count=2)],
        queue_items=[_queue_item("E1", status="due_today", priority="medium")],
        open_exception_rows=[],
        tenant_id="tenant-1",
        today=date(2026, 4, 13),
    )

    summary = build_decision_summary(decision_items)

    assert summary.total_evaluated == 1
    assert isinstance(summary.ranked_items[0], AttentionItem)
    assert summary.ranked_items[0].attention_score == decision_items[0].final_score
    assert summary.ranked_items[0].snapshot["confidence_basis"] == decision_items[0].confidence_basis