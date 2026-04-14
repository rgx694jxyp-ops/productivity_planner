from pages.today import _build_last_action_lookup


def test_last_action_lookup_prefers_last_event_at_over_created_at():
    queue_items = [
        {
            "employee_id": "E1",
            "created_at": "2026-04-01T09:00:00Z",
            "last_event_at": "2026-04-10T12:00:00Z",
        }
    ]

    lookup = _build_last_action_lookup(queue_items)

    assert lookup == {"E1": "2026-04-10"}


def test_last_action_lookup_falls_back_to_created_at_when_last_event_missing():
    queue_items = [
        {
            "employee_id": "E2",
            "created_at": "2026-04-08T09:00:00Z",
        }
    ]

    lookup = _build_last_action_lookup(queue_items)

    assert lookup == {"E2": "2026-04-08"}


def test_last_action_lookup_keeps_most_recent_date_per_employee_across_mixed_sources():
    queue_items = [
        {
            "employee_id": "E3",
            "created_at": "2026-04-01T09:00:00Z",
            "last_event_at": "2026-04-07T12:00:00Z",
        },
        {
            "employee_id": "E3",
            "created_at": "2026-04-09T08:00:00Z",
        },
        {
            "employee_id": "E4",
            "created_at": "2026-04-03T09:00:00Z",
            "last_event_at": "2026-04-05T10:00:00Z",
        },
    ]

    lookup = _build_last_action_lookup(queue_items)

    assert lookup["E3"] == "2026-04-09"
    assert lookup["E4"] == "2026-04-05"


def test_last_action_lookup_skips_rows_without_employee_or_dates():
    queue_items = [
        {},
        {"employee_id": ""},
        {"employee_id": "E5"},
    ]

    lookup = _build_last_action_lookup(queue_items)

    assert lookup == {}
