from services.action_query_service import get_employee_action_timeline
from services.follow_through_service import (
    build_follow_through_context_line,
    log_follow_through_event,
    summarize_follow_through_events,
)


def test_log_follow_through_event_maps_generic_entry_to_action_events_repo(monkeypatch):
    captured = {}

    def _log_action_event(**kwargs):
        captured.update(kwargs)
        return {"id": 11}

    monkeypatch.setattr("services.follow_through_service.action_events_repo.log_action_event", _log_action_event)

    out = log_follow_through_event(
        employee_id="E1",
        linked_exception_id="7",
        owner="lead@example.com",
        status="pending",
        due_date="2026-04-12",
        details="Checked scanner lane and queued replacement.",
        outcome="improved",
        tenant_id="tenant-a",
    )

    assert out == {"id": 11}
    assert captured["event_type"] == "follow_through_logged"
    assert captured["employee_id"] == "E1"
    assert captured["linked_exception_id"] == "7"
    assert captured["status"] == "pending"
    assert captured["due_date"] == "2026-04-12"
    assert captured["outcome"] == "improved"


def test_summarize_follow_through_events_filters_noise_and_counts_open(monkeypatch):
    rows = [
        {"id": 1, "event_type": "created", "status": "logged"},
        {"id": 2, "event_type": "follow_through_logged", "status": "pending"},
        {"id": 3, "event_type": "resolved", "status": "done"},
    ]

    monkeypatch.setattr(
        "services.follow_through_service.action_events_repo.list_action_events",
        lambda **kwargs: rows,
    )

    summary = summarize_follow_through_events(tenant_id="tenant-a", employee_id="E1")

    assert summary["total_count"] == 2
    assert summary["open_count"] == 1


def test_build_follow_through_context_line_uses_status_owner_and_due_date():
    line = build_follow_through_context_line(
        {
            "status": "pending",
            "owner": "lead@example.com",
            "due_date": "2026-04-12T00:00:00Z",
        }
    )

    assert line == "Pending | lead@example.com | Due 2026-04-12"


def test_get_employee_action_timeline_includes_generic_follow_through_entries(monkeypatch):
    monkeypatch.setattr("services.action_query_service.actions_repo.list_actions", lambda **kwargs: [])
    monkeypatch.setattr(
        "services.action_query_service.action_events_repo.list_action_events",
        lambda **kwargs: [
            {
                "action_id": None,
                "linked_exception_id": 7,
                "event_type": "follow_through_logged",
                "event_at": "2026-04-09T08:00:00Z",
                "owner": "lead@example.com",
                "details": "Checked line and logged blocker.",
                "outcome": "pending",
                "due_date": "2026-04-10T00:00:00Z",
                "status": "pending",
            }
        ],
    )

    timeline = get_employee_action_timeline("E1", tenant_id="tenant-a")

    assert len(timeline) == 1
    assert timeline[0]["action_id"] == ""
    assert timeline[0]["linked_exception_id"] == 7
    assert timeline[0]["notes"] == "Checked line and logged blocker."