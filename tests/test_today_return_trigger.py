from datetime import date

from pages.today import _render_return_trigger
from services.today_view_model_service import TodayReturnTriggerViewModel, build_today_return_trigger


TODAY = date(2026, 4, 13)


def test_return_trigger_shows_changed_state_when_yesterday_exists():
    trigger = build_today_return_trigger(
        queue_items=[
            {"employee_id": "E1", "_queue_status": "overdue", "created_at": "2026-04-10T09:00:00Z"},
            {"employee_id": "E2", "_queue_status": "due_today", "created_at": "2026-04-13T08:00:00Z"},
        ],
        today=TODAY,
        previous_queue_items=[
            {"employee_id": "E1", "_queue_status": "overdue", "created_at": "2026-04-10T09:00:00Z"},
        ],
        previous_as_of_date="2026-04-12",
    )

    assert trigger is not None
    assert trigger.headline == "What changed since yesterday"
    assert trigger.show_cue is True
    assert trigger.cue_label == "Update"
    assert trigger.messages == [
        "1 new urgent item surfaced since yesterday",
        "1 follow-up is due today",
    ]


def test_return_trigger_shows_quiet_no_change_state_when_comparison_exists():
    trigger = build_today_return_trigger(
        queue_items=[
            {"employee_id": "E1", "_queue_status": "overdue", "created_at": "2026-04-10T09:00:00Z"},
        ],
        today=TODAY,
        previous_queue_items=[
            {"employee_id": "E1", "_queue_status": "overdue", "created_at": "2026-04-10T09:00:00Z"},
        ],
        previous_as_of_date="2026-04-12",
    )

    assert trigger is not None
    assert trigger.show_cue is True
    assert trigger.messages == [
        "No new urgent issues since yesterday",
        "1 overdue follow-up remains unchanged since yesterday",
    ]


def test_return_trigger_shows_quiet_state_with_comparison_even_without_urgent_items():
    trigger = build_today_return_trigger(
        queue_items=[],
        today=TODAY,
        previous_queue_items=[],
        previous_as_of_date="2026-04-12",
    )

    assert trigger is not None
    assert trigger.show_cue is False
    assert trigger.messages == ["No new urgent issues since yesterday"]


def test_return_trigger_stays_clean_without_comparison_or_today_signal():
    trigger = build_today_return_trigger(
        queue_items=[
            {"employee_id": "E1", "_queue_status": "pending", "created_at": "2026-04-10T09:00:00Z"},
        ],
        today=TODAY,
        previous_queue_items=[],
        previous_as_of_date="",
    )

    assert trigger is None


def test_return_trigger_render_outputs_compact_block_with_cue(monkeypatch):
    markdown_calls: list[str] = []
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: markdown_calls.append(str(text)))

    _render_return_trigger(
        TodayReturnTriggerViewModel(
            headline="What changed since yesterday",
            messages=["No new urgent issues since yesterday", "2 follow-ups are due today"],
            comparison_basis="compared with 2026-04-12",
            show_cue=True,
            cue_label="Update",
        )
    )

    rendered = "\n".join(markdown_calls)
    assert "What changed since yesterday" in rendered
    assert "Update" in rendered
    assert "border-left:3px solid #1f4f87" in rendered
    assert "No new urgent issues since yesterday" in rendered
    assert "2 follow-ups are due today" in rendered
    assert "compared with 2026-04-12" in rendered


def test_return_trigger_render_stays_neutral_without_cue(monkeypatch):
    markdown_calls: list[str] = []
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: markdown_calls.append(str(text)))

    _render_return_trigger(
        TodayReturnTriggerViewModel(
            headline="What changed since yesterday",
            messages=["No new urgent issues since yesterday"],
            comparison_basis="compared with 2026-04-12",
            show_cue=False,
            cue_label="",
        )
    )

    rendered = "\n".join(markdown_calls)
    assert "What changed since yesterday" in rendered
    assert "No new urgent issues since yesterday" in rendered
    assert "Update" not in rendered
    assert "border-left:3px solid #1f4f87" not in rendered