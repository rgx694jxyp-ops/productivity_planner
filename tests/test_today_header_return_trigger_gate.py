from datetime import date

from pages.today import _should_load_previous_payload_for_return_trigger


def test_return_trigger_previous_payload_skips_when_queue_has_no_urgent_or_new_today_items():
    queue_items = [
        {
            "employee_id": "E1",
            "_queue_status": "pending",
            "created_at": "2026-04-18T09:30:00",
        }
    ]

    should_load = _should_load_previous_payload_for_return_trigger(
        queue_items=queue_items,
        today_value=date(2026, 4, 19),
    )

    assert should_load is False


def test_return_trigger_previous_payload_loads_for_urgent_or_new_today_items():
    queue_items = [
        {
            "employee_id": "E2",
            "_queue_status": "overdue",
            "created_at": "2026-04-18T09:30:00",
        },
        {
            "employee_id": "E3",
            "_queue_status": "pending",
            "created_at": "2026-04-19T10:15:00",
        },
    ]

    should_load = _should_load_previous_payload_for_return_trigger(
        queue_items=queue_items,
        today_value=date(2026, 4, 19),
    )

    assert should_load is True
