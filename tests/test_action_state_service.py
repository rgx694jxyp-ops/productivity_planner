from datetime import date

import services.perf_profile as perf_profile

from services.action_state_service import (
    NormalizedActionState,
    build_employee_action_state_lookup,
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


def _last_lookup_profile_context(events: list[tuple[str, dict]]) -> dict:
    for event_type, payload in reversed(events):
        if event_type != "perf_profile":
            continue
        if str(payload.get("detail") or "") != "action_state.lookup_batched":
            continue
        return dict(payload.get("context") or {})
    return {}


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


def test_build_employee_action_state_lookup_batches_reads_once(monkeypatch):
    monkeypatch.setattr(
        "services.action_state_service.get_employee_actions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("per-employee actions read should not be used")),
    )
    monkeypatch.setattr(
        "services.action_state_service.get_employee_action_timeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("per-employee timeline read should not be used")),
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employee",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("per-employee follow-up read should not be used")),
    )

    monkeypatch.setattr(
        "services.action_state_service.actions_repo.list_actions_for_employee_ids",
        lambda **kwargs: [
            {
                "id": "A1",
                "employee_id": "E1",
                "employee_name": "Alex",
                "department": "Pack",
                "status": "in_progress",
                "follow_up_due_at": "2026-04-12",
                "trigger_summary": "Coaching still open",
                "note": "Initial coaching note",
            },
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_action_ids",
        lambda **kwargs: [
            {
                "action_id": "A1",
                "linked_exception_id": "",
                "event_type": "coached",
                "event_at": "2026-04-11T09:00:00Z",
                "owner": "lead@example.com",
                "performed_by": "lead@example.com",
                "details": "Reviewed after coaching",
                "notes": "Reviewed after coaching",
                "outcome": "",
                "due_date": "2026-04-12",
                "next_follow_up_at": "2026-04-12",
                "status": "pending",
            }
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_employee_ids",
        lambda **kwargs: [
            {
                "action_id": "",
                "employee_id": "E2",
                "linked_exception_id": "",
                "event_type": "follow_through_logged",
                "event_at": "2026-04-12T10:00:00Z",
                "owner": "lead@example.com",
                "performed_by": "lead@example.com",
                "details": "Checked blocker and scheduled revisit",
                "notes": "Checked blocker and scheduled revisit",
                "outcome": "",
                "due_date": "2026-04-16",
                "next_follow_up_at": "2026-04-16",
                "status": "pending",
            }
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employees",
        lambda **kwargs: [
            {
                "emp_id": "E1",
                "name": "Alex",
                "dept": "Pack",
                "followup_date": "2026-04-18",
                "note_preview": "Legacy scheduled check",
            }
        ],
    )

    lookup = build_employee_action_state_lookup(("E1", "E2"), tenant_id="tenant-a", today=TODAY)

    assert lookup["E1"]["state"] == NormalizedActionState.FOLLOW_UP_SCHEDULED
    assert lookup["E1"]["source_type"] == "action"
    assert lookup["E2"]["state"] == NormalizedActionState.FOLLOW_UP_SCHEDULED
    assert lookup["E2"]["source_type"] == "standalone_follow_through"


def test_build_employee_action_state_lookup_skips_standalone_reads_for_invalid_tenant_when_actions_empty(monkeypatch):
    calls = {"generic": 0, "followups": 0}

    monkeypatch.setattr(
        "services.action_state_service.actions_repo.list_actions_for_employee_ids",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_action_ids",
        lambda **kwargs: [],
    )

    def _generic_events(**kwargs):
        calls["generic"] += 1
        return []

    def _followups(**kwargs):
        calls["followups"] += 1
        return []

    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_employee_ids",
        _generic_events,
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employees",
        _followups,
    )

    lookup = build_employee_action_state_lookup(("E1",), tenant_id="not-a-uuid", today=TODAY)

    assert lookup == {}
    assert calls["generic"] == 0
    assert calls["followups"] == 0


def test_build_employee_action_state_lookup_emits_skipped_query_telemetry(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        perf_profile,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    monkeypatch.setattr(
        "services.action_state_service.actions_repo.list_actions_for_employee_ids",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_action_ids",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_employee_ids",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("generic employee-events read should be skipped")),
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employees",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("follow-up read should be skipped")),
    )

    build_employee_action_state_lookup(("E1",), tenant_id="not-a-uuid", today=TODAY)
    context = _last_lookup_profile_context(events)

    assert context["actions_query_skipped"] is False
    assert context["generic_employee_events_query_skipped"] is True
    assert context["followups_query_skipped"] is True
    assert context["generic_employee_events_query_ms"] == 0
    assert context["followups_query_ms"] == 0
    assert context["generic_employee_event_rows"] == 0
    assert context["followup_rows"] == 0
    assert context["query_count"] == 1
    assert context["visible_db_rows"] == 0


def test_build_employee_action_state_lookup_valid_tenant_zero_actions_skips_full_standalone_reads_when_probes_empty(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        perf_profile,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    calls = {"generic": 0, "followups": 0}

    monkeypatch.setattr(
        "services.action_state_service.actions_repo.list_actions_for_employee_ids",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_action_ids",
        lambda **kwargs: [],
    )

    def _generic_events(**kwargs):
        calls["generic"] += 1
        assert int(kwargs.get("limit") or 0) == 1
        return []

    def _followups(**kwargs):
        calls["followups"] += 1
        assert int(kwargs.get("limit") or 0) == 1
        return []

    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_employee_ids",
        _generic_events,
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employees",
        _followups,
    )

    lookup = build_employee_action_state_lookup(("E1",), tenant_id="7bda2683-769d-45a6-ae5f-0e965ae2b593", today=TODAY)
    context = _last_lookup_profile_context(events)

    assert lookup == {}
    assert calls["generic"] == 1
    assert calls["followups"] == 1
    assert context["standalone_probe_ran"] is True
    assert context["needs_followups_probe"] is True
    assert context["needs_generic_employee_events_probe"] is True
    assert context["standalone_probe_generic_rows"] == 0
    assert context["standalone_probe_followup_rows"] == 0
    assert context["generic_employee_events_query_skipped"] is True
    assert context["followups_query_skipped"] is True
    assert context["query_count"] == 3
    assert context["visible_db_rows"] == 0


def test_build_employee_action_state_lookup_valid_tenant_zero_actions_partially_skips_standalone_reads(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        perf_profile,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    calls = {"generic_probe": 0, "generic_full": 0, "followup_probe": 0, "followup_full": 0}

    monkeypatch.setattr(
        "services.action_state_service.actions_repo.list_actions_for_employee_ids",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_action_ids",
        lambda **kwargs: [],
    )

    def _generic_events(**kwargs):
        if int(kwargs.get("limit") or 0) == 1:
            calls["generic_probe"] += 1
            return [{"action_id": "", "employee_id": "E1", "event_type": "follow_through_logged", "status": "pending"}]
        calls["generic_full"] += 1
        return [{"action_id": "", "employee_id": "E1", "event_type": "follow_through_logged", "status": "pending"}]

    def _followups(**kwargs):
        if int(kwargs.get("limit") or 0) == 1:
            calls["followup_probe"] += 1
            return []
        calls["followup_full"] += 1
        return (_ for _ in ()).throw(AssertionError("full follow-up read should be skipped when probe is empty"))

    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_employee_ids",
        _generic_events,
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employees",
        _followups,
    )

    lookup = build_employee_action_state_lookup(("E1",), tenant_id="7bda2683-769d-45a6-ae5f-0e965ae2b593", today=TODAY)
    context = _last_lookup_profile_context(events)

    assert lookup["E1"]["source_type"] == "standalone_follow_through"
    assert calls["generic_probe"] == 1
    assert calls["generic_full"] == 0
    assert calls["followup_probe"] == 1
    assert calls["followup_full"] == 0
    assert context["needs_generic_employee_events_probe"] is True
    assert context["needs_followups_probe"] is True


def test_build_employee_action_state_lookup_singleton_followup_skips_generic_probe_and_read(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        perf_profile,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    calls = {"generic": 0, "followup_probe": 0, "followup_full": 0}

    monkeypatch.setattr(
        "services.action_state_service.actions_repo.list_actions_for_employee_ids",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_action_ids",
        lambda **kwargs: [],
    )

    def _generic_events(**kwargs):
        calls["generic"] += 1
        return (_ for _ in ()).throw(AssertionError("generic probe/read should be skipped for singleton follow-up state"))

    def _followups(**kwargs):
        if int(kwargs.get("limit") or 0) == 1:
            calls["followup_probe"] += 1
            return [{"emp_id": "E1", "name": "Alex", "dept": "Pack", "followup_date": "2026-04-15", "note_preview": "Check in"}]
        calls["followup_full"] += 1
        return [{"emp_id": "E1", "name": "Alex", "dept": "Pack", "followup_date": "2026-04-15", "note_preview": "Check in"}]

    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_employee_ids",
        _generic_events,
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employees",
        _followups,
    )

    lookup = build_employee_action_state_lookup(("E1",), tenant_id="7bda2683-769d-45a6-ae5f-0e965ae2b593", today=TODAY)
    context = _last_lookup_profile_context(events)

    assert lookup["E1"]["source_type"] == "scheduled_only"
    assert calls["generic"] == 0
    assert calls["followup_probe"] == 1
    assert calls["followup_full"] == 0
    assert context["needs_followups_probe"] is True
    assert context["needs_generic_employee_events_probe"] is False
    assert context["generic_employee_events_query_skipped"] is True
    assert context["followups_query_skipped"] is True


def test_build_employee_action_state_lookup_non_empty_shape_and_telemetry_accuracy(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        perf_profile,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    monkeypatch.setattr(
        "services.action_state_service.actions_repo.list_actions_for_employee_ids",
        lambda **kwargs: [
            {
                "id": "A1",
                "employee_id": "E1",
                "employee_name": "Alex",
                "department": "Pack",
                "status": "in_progress",
                "follow_up_due_at": "2026-04-12",
                "trigger_summary": "Coaching still open",
                "note": "Initial coaching note",
            },
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_action_ids",
        lambda **kwargs: [
            {
                "action_id": "A1",
                "event_type": "coached",
                "event_at": "2026-04-11T09:00:00Z",
                "details": "Reviewed after coaching",
                "due_date": "2026-04-12",
                "status": "pending",
            }
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.action_events_repo.list_action_events_for_employee_ids",
        lambda **kwargs: [
            {
                "action_id": "",
                "employee_id": "E2",
                "event_type": "follow_through_logged",
                "event_at": "2026-04-12T10:00:00Z",
                "details": "Checked blocker and scheduled revisit",
                "due_date": "2026-04-16",
                "status": "pending",
            }
        ],
    )
    monkeypatch.setattr(
        "services.action_state_service.get_followups_for_employees",
        lambda **kwargs: [
            {
                "emp_id": "E1",
                "name": "Alex",
                "dept": "Pack",
                "followup_date": "2026-04-18",
                "note_preview": "Legacy scheduled check",
            }
        ],
    )

    lookup = build_employee_action_state_lookup(("E1", "E2"), tenant_id="tenant-a", today=TODAY)
    context = _last_lookup_profile_context(events)

    assert set(lookup["E1"].keys()) == {"state", "state_detail", "title", "is_open", "source_type"}
    assert set(lookup["E2"].keys()) == {"state", "state_detail", "title", "is_open", "source_type"}
    assert lookup["E1"]["source_type"] == "action"
    assert lookup["E2"]["source_type"] == "standalone_follow_through"

    assert context["actions_query_skipped"] is False
    assert context["generic_employee_events_query_skipped"] is False
    assert context["followups_query_skipped"] is False
    assert context["needs_generic_employee_events_probe"] is False
    assert context["needs_followups_probe"] is False
    assert context["query_count"] == 3
    assert context["visible_db_rows"] == (
        int(context["actions_rows"])
        + int(context["generic_employee_event_rows"])
        + int(context["followup_rows"])
    )


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