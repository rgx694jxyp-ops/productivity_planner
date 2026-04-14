from datetime import date

from services.action_state_service import (
    NormalizedActionState,
    build_employee_action_state_summary,
    interpret_follow_through_state,
    interpret_normalized_action_state,
    log_action_event,
    log_coaching_lifecycle_entry,
    log_follow_through_event,
    log_recognition_event,
    mark_action_resolved,
    save_action_touchpoint,
    schedule_follow_up_for_employee,
)


TODAY = date(2026, 4, 13)


def test_interpret_normalized_action_state_maps_legacy_statuses():
    assert interpret_normalized_action_state("new", None, today=TODAY) == NormalizedActionState.OPEN
    assert interpret_normalized_action_state("in_progress", None, today=TODAY) == NormalizedActionState.IN_PROGRESS
    assert (
        interpret_normalized_action_state("follow_up_due", "2026-04-15", today=TODAY)
        == NormalizedActionState.FOLLOW_UP_SCHEDULED
    )
    assert interpret_normalized_action_state("resolved", None, today=TODAY) == NormalizedActionState.RESOLVED
    assert interpret_normalized_action_state("transferred", None, today=TODAY) == NormalizedActionState.RESOLVED


def test_interpret_follow_through_state_uses_due_date_and_done_status():
    assert interpret_follow_through_state("pending", None, today=TODAY) == NormalizedActionState.IN_PROGRESS
    assert (
        interpret_follow_through_state("pending", "2026-04-20", today=TODAY)
        == NormalizedActionState.FOLLOW_UP_SCHEDULED
    )
    assert interpret_follow_through_state("done", None, today=TODAY) == NormalizedActionState.RESOLVED


def test_build_employee_action_state_summary_merges_actions_and_scheduler_rows(monkeypatch):
    monkeypatch.setattr(
        "services.action_state_service.get_employee_actions",
        lambda employee_id, tenant_id="", today=None: [
            {
                "id": "A1",
                "employee_id": employee_id,
                "employee_name": "Alex",
                "department": "Pack",
                "status": "in_progress",
                "_runtime_status": "overdue",
                "follow_up_due_at": "2026-04-12",
                "trigger_summary": "Coaching still open",
                "note": "Initial coaching note",
            }
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.get_employee_action_timeline",
        lambda employee_id, tenant_id="": [
            {
                "action_id": "A1",
                "event_type": "coached",
                "event_at": "2026-04-11T09:00:00Z",
                "notes": "Reviewed after coaching",
            }
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employee",
        lambda employee_id, from_date=None, to_date=None, tenant_id="": [
            {
                "emp_id": employee_id,
                "name": "Alex",
                "dept": "Pack",
                "followup_date": "2026-04-12",
                "note_preview": "Same action follow-up",
            },
            {
                "emp_id": employee_id,
                "name": "Alex",
                "dept": "Pack",
                "followup_date": "2026-04-18",
                "note_preview": "Legacy scheduled check",
            },
        ],
    )

    summary = build_employee_action_state_summary("E1", tenant_id="tenant-a", today=TODAY)

    assert summary["primary_state"] == NormalizedActionState.FOLLOW_UP_SCHEDULED
    assert summary["summary"]["open_count"] == 2
    assert summary["summary"]["scheduled_count"] == 2
    assert len(summary["states"]) == 2
    assert summary["states"][0]["source_type"] == "action"
    assert summary["states"][0]["state_detail"].startswith("Overdue")
    assert summary["states"][1]["source_type"] == "scheduled_only"


def test_build_employee_action_state_summary_uses_standalone_follow_through_when_no_action(monkeypatch):
    monkeypatch.setattr("services.action_state_service.get_employee_actions", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "services.action_state_service.get_employee_action_timeline",
        lambda employee_id, tenant_id="": [
            {
                "action_id": "",
                "event_type": "follow_through_logged",
                "event_at": "2026-04-12T10:00:00Z",
                "notes": "Checked blocker and scheduled revisit",
                "status": "pending",
                "next_follow_up_at": "2026-04-16",
            }
        ],
    )
    monkeypatch.setattr("services.action_state_service.get_followups_for_employee", lambda *args, **kwargs: [])

    summary = build_employee_action_state_summary("E2", tenant_id="tenant-a", today=TODAY)

    assert summary["summary"]["total_count"] == 1
    assert summary["states"][0]["source_type"] == "standalone_follow_through"
    assert summary["states"][0]["state"] == NormalizedActionState.FOLLOW_UP_SCHEDULED


def test_schedule_follow_up_for_employee_updates_existing_action(monkeypatch):
    monkeypatch.setattr(
        "services.action_state_service.get_employee_actions",
        lambda employee_id, tenant_id="": [
            {
                "id": "A7",
                "employee_id": employee_id,
                "status": "in_progress",
                "_runtime_status": "in_progress",
                "follow_up_due_at": "",
            }
        ],
    )
    captured: dict = {}

    def _update_action(*, action_id, updates, tenant_id=""):
        captured["action_id"] = action_id
        captured["updates"] = dict(updates)
        captured["tenant_id"] = tenant_id
        return {"id": action_id, **updates}

    monkeypatch.setattr("services.action_state_service.actions_repo.update_action", _update_action)
    monkeypatch.setattr(
        "services.action_state_service.add_followup",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy scheduler should not be used")),
    )

    result = schedule_follow_up_for_employee(
        employee_id="E7",
        employee_name="Alex",
        department="Pack",
        follow_up_date="2026-04-17",
        note_preview="Recheck next week",
        tenant_id="tenant-a",
    )

    assert result["mode"] == "action_update"
    assert captured["action_id"] == "A7"
    assert captured["updates"]["status"] == "follow_up_due"
    assert captured["updates"]["follow_up_due_at"] == "2026-04-17"


def test_schedule_follow_up_for_employee_falls_back_to_legacy_scheduler(monkeypatch):
    monkeypatch.setattr("services.action_state_service.get_employee_actions", lambda *args, **kwargs: [])
    captured: dict = {}

    def _add_followup(emp_id, name, dept, followup_date, note_preview="", tenant_id=""):
        captured["emp_id"] = emp_id
        captured["name"] = name
        captured["dept"] = dept
        captured["followup_date"] = followup_date
        captured["note_preview"] = note_preview
        captured["tenant_id"] = tenant_id

    monkeypatch.setattr("services.action_state_service.add_followup", _add_followup)

    result = schedule_follow_up_for_employee(
        employee_id="E9",
        employee_name="Jamie",
        department="Receiving",
        follow_up_date="2026-04-21",
        note_preview="Legacy-only follow-up",
        tenant_id="tenant-a",
    )

    assert result == {
        "mode": "scheduler_only",
        "action_id": "",
        "follow_up_date": "2026-04-21",
    }
    assert captured["emp_id"] == "E9"
    assert captured["tenant_id"] == "tenant-a"


def test_log_coaching_lifecycle_entry_delegates_to_lifecycle_service(monkeypatch):
    captured: dict = {}

    def _delegate(**kwargs):
        captured.update(kwargs)
        return {"action_id": "A12"}

    monkeypatch.setattr("services.action_state_service._log_coaching_lifecycle_entry", _delegate)

    out = log_coaching_lifecycle_entry(
        employee_id="E12",
        employee_name="Taylor",
        department="Packing",
        reason="Below goal",
        action_taken="Reviewed blockers",
        expected_follow_up_date="2026-04-20",
        tenant_id="tenant-a",
    )

    assert out == {"action_id": "A12"}
    assert captured["employee_id"] == "E12"
    assert captured["expected_follow_up_date"] == "2026-04-20"


def test_log_follow_through_event_delegates_to_follow_through_service(monkeypatch):
    captured: dict = {}

    def _delegate(**kwargs):
        captured.update(kwargs)
        return {"id": 31}

    monkeypatch.setattr("services.action_state_service._log_follow_through_event", _delegate)

    out = log_follow_through_event(
        employee_id="E31",
        action_id="A31",
        owner="lead@example.com",
        status="pending",
        due_date="2026-04-18",
        details="Rechecked lane staffing",
        outcome="pending",
        tenant_id="tenant-a",
    )

    assert out == {"id": 31}
    assert captured["employee_id"] == "E31"
    assert captured["action_id"] == "A31"
    assert captured["status"] == "pending"


def test_save_action_touchpoint_and_log_action_event_delegate(monkeypatch):
    touchpoint_calls: list[dict] = []
    event_calls: list[dict] = []

    def _touchpoint_delegate(**kwargs):
        touchpoint_calls.append(dict(kwargs))
        return {"id": "A44"}

    def _event_delegate(**kwargs):
        event_calls.append(dict(kwargs))
        return {"id": "EV44"}

    monkeypatch.setattr("services.action_state_service._save_action_touchpoint", _touchpoint_delegate)
    monkeypatch.setattr("services.action_state_service._log_action_event", _event_delegate)

    touch_out = save_action_touchpoint(
        action_id="A44",
        event_type="follow_up_logged",
        notes="Checked again",
        tenant_id="tenant-a",
    )
    event_out = log_action_event(
        action_id="A44",
        event_type="resolved",
        notes="Closed after recheck",
        tenant_id="tenant-a",
    )

    assert touch_out == {"id": "A44"}
    assert event_out == {"id": "EV44"}
    assert touchpoint_calls[0]["action_id"] == "A44"
    assert event_calls[0]["event_type"] == "resolved"


def test_recognition_and_resolution_delegate_to_lifecycle_service(monkeypatch):
    recognition_calls: list[dict] = []
    resolve_calls: list[dict] = []

    def _recognition_delegate(**kwargs):
        recognition_calls.append(dict(kwargs))
        return {"id": "EV55"}

    def _resolve_delegate(**kwargs):
        resolve_calls.append(dict(kwargs))
        return {"id": "A55", "status": "resolved"}

    monkeypatch.setattr("services.action_state_service._log_recognition_event", _recognition_delegate)
    monkeypatch.setattr("services.action_state_service._mark_action_resolved", _resolve_delegate)

    recognition_out = log_recognition_event(
        action_id="A55",
        employee_id="E55",
        notes="Recognition logged",
        tenant_id="tenant-a",
    )
    resolve_out = mark_action_resolved(
        action_id="A55",
        resolution_type="improved",
        resolution_note="Sustained recovery",
        tenant_id="tenant-a",
    )

    assert recognition_out == {"id": "EV55"}
    assert resolve_out["status"] == "resolved"
    assert recognition_calls[0]["action_id"] == "A55"
    assert resolve_calls[0]["resolution_type"] == "improved"