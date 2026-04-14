from datetime import date

from services import action_metrics_service as ams
from services.today_view_model_service import build_today_weekly_summary_view_model


TODAY = date(2026, 4, 13)


def test_weekly_manager_activity_summary_counts_existing_events(monkeypatch):
    def _list_actions(*, tenant_id="", statuses=None, employee_id=""):
        if statuses == ["resolved", "deprioritized"]:
            return [
                {
                    "id": "A1",
                    "employee_id": "E1",
                    "employee_name": "Alex",
                    "department": "Packing",
                    "resolution_type": "improved",
                    "resolved_at": "2026-04-12T09:00:00Z",
                },
                {
                    "id": "A2",
                    "employee_id": "E2",
                    "employee_name": "Jamie",
                    "department": "Packing",
                    "resolution_type": "no_change",
                    "resolved_at": "2026-03-30T09:00:00Z",
                },
            ]
        return [
            {"id": "A1", "issue_type": "pace_drop"},
            {"id": "A2", "issue_type": "quality_issue"},
        ]

    def _list_action_events(action_id="", tenant_id="", **kwargs):
        if not action_id:
            return [
                {
                    "event_type": "today_signal_status_set",
                    "event_at": "2026-04-13T09:00:00Z",
                    "details": '{"scope":"today_queue_signal_status","signal_key":"sig-1","signal_status":"looked_at"}',
                },
                {
                    "event_type": "today_signal_status_set",
                    "event_at": "2026-04-12T10:00:00Z",
                    "details": '{"scope":"today_queue_signal_status","signal_key":"sig-1","signal_status":"looked_at"}',
                },
                {
                    "event_type": "today_signal_status_set",
                    "event_at": "2026-04-11T10:00:00Z",
                    "details": '{"scope":"today_queue_signal_status","signal_key":"sig-2","signal_status":"looked_at"}',
                },
                {
                    "event_type": "coached",
                    "event_at": "2026-04-10T10:00:00Z",
                    "details": "",
                },
                {
                    "event_type": "follow_up_logged",
                    "event_at": "2026-04-09T10:00:00Z",
                    "details": "",
                },
                {
                    "event_type": "follow_through_logged",
                    "event_at": "2026-04-01T10:00:00Z",
                    "details": "",
                },
            ]
        if action_id == "A1":
            return [
                {
                    "event_type": "coached",
                    "event_at": "2026-04-12T10:00:00Z",
                    "outcome": "improved",
                }
            ]
        if action_id == "A2":
            return [
                {
                    "event_type": "follow_up_logged",
                    "event_at": "2026-04-12T10:00:00Z",
                    "outcome": "pending",
                }
            ]
        return []

    monkeypatch.setattr(ams.actions_repo, "list_actions", _list_actions)
    monkeypatch.setattr(ams.action_events_repo, "list_action_events", _list_action_events)

    summary = ams.get_weekly_manager_activity_summary(
        tenant_id="tenant-a",
        lookback_days=7,
        today=TODAY,
    )

    assert summary == {
        "reviewed_issues": 2,
        "follow_up_touchpoints": 2,
        "closed_issues": 1,
        "improved_outcomes": 1,
        "reviewed_today": 1,
        "touchpoints_logged_today": 0,
        "follow_ups_scheduled_today": 0,
    }



def test_weekly_manager_activity_summary_handles_no_data(monkeypatch):
    monkeypatch.setattr(ams.actions_repo, "list_actions", lambda **kwargs: [])
    monkeypatch.setattr(ams.action_events_repo, "list_action_events", lambda *args, **kwargs: [])

    summary = ams.get_weekly_manager_activity_summary(
        tenant_id="tenant-a",
        lookback_days=7,
        today=TODAY,
    )

    assert summary == {
        "reviewed_issues": 0,
        "follow_up_touchpoints": 0,
        "closed_issues": 0,
        "improved_outcomes": 0,
        "reviewed_today": 0,
        "touchpoints_logged_today": 0,
        "follow_ups_scheduled_today": 0,
    }


def test_weekly_manager_activity_summary_includes_same_day_touchpoints(monkeypatch):
    monkeypatch.setattr(ams.actions_repo, "list_actions", lambda **kwargs: [])

    def _list_action_events(action_id="", tenant_id="", **kwargs):
        if action_id:
            return []
        return [
            {
                "event_type": "coached",
                "event_at": "2026-04-13T08:00:00Z",
                "details": "",
                "next_follow_up_at": "2026-04-15",
                "due_date": "2026-04-15",
            },
            {
                "event_type": "follow_up_logged",
                "event_at": "2026-04-13T10:00:00Z",
                "details": "",
                "next_follow_up_at": "",
                "due_date": "",
            },
            {
                "event_type": "follow_through_logged",
                "event_at": "2026-04-12T10:00:00Z",
                "details": "",
                "next_follow_up_at": "",
                "due_date": "",
            },
        ]

    monkeypatch.setattr(ams.action_events_repo, "list_action_events", _list_action_events)

    summary = ams.get_weekly_manager_activity_summary(
        tenant_id="tenant-a",
        lookback_days=7,
        today=TODAY,
    )

    assert summary["touchpoints_logged_today"] == 2
    assert summary["follow_ups_scheduled_today"] == 1



def test_today_weekly_summary_view_model_builds_operational_sentences():
    vm = build_today_weekly_summary_view_model(
        reviewed_issues=6,
        follow_up_touchpoints=3,
        closed_issues=2,
        improved_outcomes=1,
    )

    assert [item.headline for item in vm.items] == [
        "6 issues reviewed this week",
        "3 follow-up touchpoints logged this week",
        "2 issues closed this week",
        "1 improved outcome logged this week",
    ]



def test_today_weekly_summary_view_model_omits_zero_metrics_for_no_data_state():
    vm = build_today_weekly_summary_view_model(
        reviewed_issues=0,
        follow_up_touchpoints=0,
        closed_issues=0,
        improved_outcomes=0,
    )

    assert vm.items == []
