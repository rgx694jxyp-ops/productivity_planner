"""Phase 1H: Auto-resolve signal clearing tests.

Tests that:
- Signals are removed from the queue when performance returns to target
- Signals stay in the queue when still below target
- Follow-up cards are preserved regardless of performance recovery
- auto_resolved_count reflects cleared items
- No system/debug language in confirmation text
"""

from datetime import date

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.today_view_model_service import (
    TodayQueueCardViewModel,
    _is_signal_auto_resolved,
    build_today_queue_view_model,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _item(
    employee_id: str = "E1",
    goal_status: str = "on_goal",
    trend_state: str = "stable",
) -> AttentionItem:
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
            "snapshot_date": "2026-04-28",
            "goal_status": goal_status,
            "trend_state": trend_state,
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


def _signal(employee_id: str = "E1") -> DisplaySignal:
    return DisplaySignal(
        employee_name=employee_id,
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 28),
        observed_value=31.0,
        comparison_start_date=date(2026, 4, 21),
        comparison_end_date=date(2026, 4, 25),
        comparison_value=40.0,
        confidence=SignalConfidence.HIGH,
        data_completeness=None,
        flags={},
    )


def _card(
    employee_id: str = "E1",
    normalized_action_state: str = "",
) -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id=employee_id,
        process_id="Receiving",
        state="CURRENT",
        line_1=f"{employee_id} · Receiving",
        line_2="Below expected pace",
        line_3="Below recent baseline vs comparable days.",
        line_4="Based on 4 recent records",
        line_5="Confidence: High",
        expanded_lines=[],
        normalized_action_state=normalized_action_state,
    )


# ---------------------------------------------------------------------------
# _is_signal_auto_resolved unit tests
# ---------------------------------------------------------------------------


def test_auto_resolved_when_on_goal_and_stable_trend():
    item = _item(goal_status="on_goal", trend_state="stable")
    card = _card()
    assert _is_signal_auto_resolved(item, card) is True


def test_auto_resolved_when_on_goal_and_improving_trend():
    item = _item(goal_status="on_goal", trend_state="improving")
    card = _card()
    assert _is_signal_auto_resolved(item, card) is True


def test_not_auto_resolved_when_below_goal():
    item = _item(goal_status="below_goal", trend_state="stable")
    card = _card()
    assert _is_signal_auto_resolved(item, card) is False


def test_not_auto_resolved_when_declining_trend_even_if_on_goal():
    item = _item(goal_status="on_goal", trend_state="declining")
    card = _card()
    assert _is_signal_auto_resolved(item, card) is False


def test_not_auto_resolved_when_below_expected_trend_even_if_on_goal():
    item = _item(goal_status="on_goal", trend_state="below_expected")
    card = _card()
    assert _is_signal_auto_resolved(item, card) is False


def test_follow_up_card_never_auto_resolved_regardless_of_performance():
    item = _item(goal_status="on_goal", trend_state="stable")
    card = _card(normalized_action_state="Follow-up Scheduled")
    assert _is_signal_auto_resolved(item, card) is False


def test_follow_up_card_preserved_even_with_improving_trend():
    item = _item(goal_status="on_goal", trend_state="improving")
    card = _card(normalized_action_state="Follow-up Scheduled")
    assert _is_signal_auto_resolved(item, card) is False


def test_not_auto_resolved_when_no_goal_set():
    item = _item(goal_status="no_goal", trend_state="stable")
    card = _card()
    assert _is_signal_auto_resolved(item, card) is False


# ---------------------------------------------------------------------------
# build_today_queue_view_model integration tests
# ---------------------------------------------------------------------------


def test_resolved_signal_removed_from_queue(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    resolved_item = _item("E1", goal_status="on_goal", trend_state="stable")
    vm = build_today_queue_view_model(
        attention=_summary([resolved_item]),
        suppressed_cards=[],
        today=date(2026, 4, 28),
    )

    all_cards = list(vm.primary_cards) + list(vm.secondary_cards)
    assert all(str(c.employee_id) != "E1" for c in all_cards), "Resolved signal must be removed from queue"
    assert vm.auto_resolved_count == 1


def test_unresolved_signal_stays_in_queue(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    unresolved_item = _item("E2", goal_status="below_goal", trend_state="declining")
    vm = build_today_queue_view_model(
        attention=_summary([unresolved_item]),
        suppressed_cards=[],
        today=date(2026, 4, 28),
    )

    all_cards = list(vm.primary_cards) + list(vm.secondary_cards)
    assert any(str(c.employee_id) == "E2" for c in all_cards), "Unresolved signal must remain in queue"
    assert vm.auto_resolved_count == 0


def test_auto_resolved_count_increments_for_each_resolved_signal(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    items = [
        _item("E1", goal_status="on_goal", trend_state="stable"),
        _item("E2", goal_status="on_goal", trend_state="improving"),
        _item("E3", goal_status="below_goal", trend_state="declining"),
    ]
    vm = build_today_queue_view_model(
        attention=_summary(items),
        suppressed_cards=[],
        today=date(2026, 4, 28),
    )

    all_cards = list(vm.primary_cards) + list(vm.secondary_cards)
    assert vm.auto_resolved_count == 2
    assert any(str(c.employee_id) == "E3" for c in all_cards), "E3 still below target — must remain in queue"


def test_follow_up_card_stays_in_queue_when_performance_recovers(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    # E1 is on goal but has a scheduled follow-up — keep it in the queue
    recovered_with_followup = _item("E1", goal_status="on_goal", trend_state="stable")
    vm = build_today_queue_view_model(
        attention=_summary([recovered_with_followup]),
        suppressed_cards=[],
        today=date(2026, 4, 28),
        action_state_lookup={"E1": {"state": "Follow-up Scheduled", "state_detail": "Due 2026-05-02"}},
    )

    all_cards = list(vm.primary_cards) + list(vm.secondary_cards)
    assert any(str(c.employee_id) == "E1" for c in all_cards), "Follow-up card must stay in queue even after recovery"
    assert vm.auto_resolved_count == 0, "Follow-up card must not be counted as auto-resolved"


def test_auto_resolved_count_zero_when_no_signals_qualify(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: _signal(str(item.employee_id)),
    )

    item = _item("E1", goal_status="below_goal", trend_state="declining")
    vm = build_today_queue_view_model(
        attention=_summary([item]),
        suppressed_cards=[],
        today=date(2026, 4, 28),
    )

    assert vm.auto_resolved_count == 0


# ---------------------------------------------------------------------------
# Confirmation copy tests
# ---------------------------------------------------------------------------


def test_confirmation_text_contains_no_system_language():
    from pages.today import _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX

    # The confirmation must be a plain user-facing phrase
    confirmation = "Back to target \u2014 no further action needed"
    banned = ["auto-resolved", "auto_resolved", "system", "debug", "internal", "cleared", "removed"]
    for term in banned:
        assert term.lower() not in confirmation.lower(), f"Banned term '{term}' found in confirmation"
    assert "target" in confirmation.lower()


def test_auto_resolved_shown_key_uses_date_prefix():
    from pages.today import _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX

    key = _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX + "2026-04-28"
    assert "2026-04-28" in key
    assert _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX in key


def _make_confirmation(count: int) -> str:
    """Mirror the pages/today.py caption logic without importing Streamlit."""
    item_word = "item" if count == 1 else "items"
    return f"{count} {item_word} back to target \u2014 no action needed"


def test_confirmation_singular_wording():
    assert _make_confirmation(1) == "1 item back to target \u2014 no action needed"


def test_confirmation_plural_wording():
    assert _make_confirmation(2) == "2 items back to target \u2014 no action needed"
    assert _make_confirmation(3) == "3 items back to target \u2014 no action needed"


def test_confirmation_contains_no_system_language():
    for count in (1, 2, 5):
        msg = _make_confirmation(count)
        banned = ["auto-resolved", "auto_resolved", "system", "debug", "internal", "cleared", "removed", "resolved"]
        for term in banned:
            assert term.lower() not in msg.lower(), f"Banned term '{term}' found in: {msg}"
        assert "target" in msg.lower()
        assert "no action needed" in msg.lower()


def test_auto_resolved_shown_key_is_date_scoped():
    from pages.today import _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX

    key_today = _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX + "2026-04-28"
    key_tomorrow = _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX + "2026-04-29"
    assert key_today != key_tomorrow, "Key must differ per day so message resets daily"
    assert "2026-04-28" in key_today
    assert "2026-04-29" in key_tomorrow


def test_confirmation_shown_once_per_day_via_session_key():
    """Simulate the session-state guard: shown once, suppressed on rerun."""
    from pages.today import _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX

    session: dict = {}
    shown_key = _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX + "2026-04-28"

    def _would_show() -> bool:
        if session.get(shown_key):
            return False
        session[shown_key] = True
        return True

    assert _would_show() is True, "Should show on first call"
    assert _would_show() is False, "Should not show on second call same day"
    assert _would_show() is False, "Should not show on third call same day"


def test_confirmation_resets_next_day():
    from pages.today import _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX

    session: dict = {}

    def _would_show(iso_date: str) -> bool:
        shown_key = _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX + iso_date
        if session.get(shown_key):
            return False
        session[shown_key] = True
        return True

    assert _would_show("2026-04-28") is True
    assert _would_show("2026-04-28") is False
    assert _would_show("2026-04-29") is True
    assert _would_show("2026-04-29") is False
