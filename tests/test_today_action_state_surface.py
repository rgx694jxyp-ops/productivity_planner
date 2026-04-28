from contextlib import contextmanager
from datetime import date

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from pages.today import _action_state_chip, _render_attention_card, _today_follow_up_status_text
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.today_view_model_service import TodayQueueCardViewModel, build_today_queue_view_model


@contextmanager
def _noop_container(*args, **kwargs):
    yield


def _item(employee_id: str = "E1") -> AttentionItem:
    return AttentionItem(
        employee_id=employee_id,
        process_name="Receiving",
        attention_score=80,
        attention_tier="high",
        attention_reasons=["reason"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={
            "employee_id": employee_id,
            "process_name": "Receiving",
            "snapshot_date": "2026-04-13",
        },
    )


def _summary(items: list[AttentionItem]) -> AttentionSummary:
    return AttentionSummary(
        ranked_items=items,
        is_healthy=not items,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=len(items),
    )


def _signal(employee_id: str) -> DisplaySignal:
    return DisplaySignal(
        employee_name=employee_id,
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 13),
        observed_value=31.0,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=40.0,
        confidence=SignalConfidence.HIGH,
        data_completeness=None,
        flags={},
    )


def _card(*, normalized_action_state: str = "") -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id="E1",
        process_id="Receiving",
        state="CURRENT",
        line_1="Alex · Receiving",
        line_2="Below expected pace",
        line_3="Below recent baseline vs comparable days.",
        line_4="Based on 4 recent records",
        line_5="Confidence: High",
        expanded_lines=[],
        normalized_action_state=normalized_action_state,
    )


def test_today_queue_cards_receive_normalized_open_state(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    vm = build_today_queue_view_model(
        attention=_summary([_item("E1")]),
        suppressed_cards=[],
        today=date(2026, 4, 13),
        action_state_lookup={"E1": {"state": "Open", "state_detail": "Underlying: New"}},
    )

    assert vm.primary_cards[0].normalized_action_state == "Open"


def test_today_queue_cards_receive_normalized_in_progress_state(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    vm = build_today_queue_view_model(
        attention=_summary([_item("E2")]),
        suppressed_cards=[],
        today=date(2026, 4, 13),
        action_state_lookup={"E2": {"state": "In Progress", "state_detail": "Underlying: In Progress"}},
    )

    assert vm.primary_cards[0].normalized_action_state == "In Progress"


def test_today_queue_cards_receive_normalized_follow_up_scheduled_state(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    vm = build_today_queue_view_model(
        attention=_summary([_item("E3")]),
        suppressed_cards=[],
        today=date(2026, 4, 13),
        action_state_lookup={"E3": {"state": "Follow-up Scheduled", "state_detail": "Due 2026-04-17"}},
    )

    assert vm.primary_cards[0].normalized_action_state == "Follow-up Scheduled"


def test_today_queue_cards_receive_normalized_resolved_state(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    vm = build_today_queue_view_model(
        attention=_summary([_item("E4")]),
        suppressed_cards=[],
        today=date(2026, 4, 13),
        action_state_lookup={"E4": {"state": "Resolved", "state_detail": "Underlying: Resolved"}},
    )

    assert vm.primary_cards[0].normalized_action_state == "Resolved"


def test_today_queue_cards_stay_uncluttered_without_action_context(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    vm = build_today_queue_view_model(
        attention=_summary([_item("E5")]),
        suppressed_cards=[],
        today=date(2026, 4, 13),
        action_state_lookup={},
    )

    assert vm.primary_cards[0].normalized_action_state == ""


def test_today_renderer_shows_action_state_chip_when_present(monkeypatch):
    payload = _action_state_chip(_card(normalized_action_state="Follow-up Scheduled"))

    assert "Follow-up Scheduled" in payload
    assert "today-action-state-chip" in payload


def test_today_follow_up_status_text_handles_due_today_overdue_and_none():
    due_today = _card(normalized_action_state="Follow-up Scheduled")
    due_today = TodayQueueCardViewModel(**{**due_today.__dict__, "normalized_action_state_detail": "Due today"})

    overdue = _card(normalized_action_state="Follow-up Scheduled")
    overdue = TodayQueueCardViewModel(**{**overdue.__dict__, "normalized_action_state_detail": "Overdue"})

    none = _card(normalized_action_state="")

    assert _today_follow_up_status_text(due_today, today_value=date(2026, 4, 13)) == "Follow-up due today"
    assert _today_follow_up_status_text(overdue, today_value=date(2026, 4, 13)) == "Follow-up overdue"
    assert _today_follow_up_status_text(none, today_value=date(2026, 4, 13)) == "No follow-up scheduled"


def test_today_renderer_omits_action_state_chip_without_context(monkeypatch):
    rendered: list[str] = []
    monkeypatch.setattr("pages.today.st.container", _noop_container)
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: rendered.append(str(text)))

    _render_attention_card(
        card=_card(normalized_action_state=""),
        key_prefix="action_state_none",
        compact=True,
        show_action=False,
    )

    payload = "\n".join(rendered)
    assert "today-action-state-chip" not in payload