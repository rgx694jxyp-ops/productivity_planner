from services.today_signal_status_service import (
    SIGNAL_STATUS_LOOKED_AT,
    SIGNAL_STATUS_NEEDS_FOLLOW_UP,
    list_latest_signal_statuses,
    set_signal_status,
)


def test_set_signal_status_persists_in_action_events(monkeypatch):
    captured = {}

    def _log_action_event(**kwargs):
        captured.update(kwargs)
        return {"id": 9}

    monkeypatch.setattr("services.today_signal_status_service.action_events_repo.log_action_event", _log_action_event)

    out = set_signal_status(
        signal_key="today-signal:e1:packing:below_expected:stable_trend:2026-04-12",
        employee_id="E1",
        signal_status=SIGNAL_STATUS_LOOKED_AT,
        owner="lead@example.com",
        tenant_id="tenant-a",
    )

    assert out == {"id": 9}
    assert captured["event_type"] == "today_signal_status_set"
    assert captured["employee_id"] == "E1"
    assert captured["status"] == "done"
    assert '"signal_status":"looked_at"' in str(captured.get("details") or "")


def test_list_latest_signal_statuses_returns_latest_per_signal(monkeypatch):
    signal_key = "today-signal:e2:pick:lower_than_recent:stable_trend:2026-04-12"
    rows = [
        {
            "event_type": "today_signal_status_set",
            "details": '{"scope":"today_queue_signal_status","signal_key":"%s","signal_status":"needs_follow_up"}' % signal_key,
            "owner": "lead@example.com",
            "event_at": "2026-04-12T10:00:00Z",
        },
        {
            "event_type": "today_signal_status_set",
            "details": '{"scope":"today_queue_signal_status","signal_key":"%s","signal_status":"looked_at"}' % signal_key,
            "owner": "lead@example.com",
            "event_at": "2026-04-12T09:00:00Z",
        },
        {
            "event_type": "follow_up_logged",
            "details": "",
            "owner": "lead@example.com",
            "event_at": "2026-04-12T08:00:00Z",
        },
    ]

    monkeypatch.setattr(
        "services.today_signal_status_service.action_events_repo.list_action_events",
        lambda **kwargs: rows,
    )

    status_map = list_latest_signal_statuses(signal_keys={signal_key}, tenant_id="tenant-a")

    assert status_map[signal_key]["status"] == SIGNAL_STATUS_NEEDS_FOLLOW_UP
    assert status_map[signal_key]["owner"] == "lead@example.com"
