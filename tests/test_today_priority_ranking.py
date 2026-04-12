from datetime import date

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.today_view_model_service import build_today_queue_view_model


def _item(*, employee_id: str, score: int, repeat_count: int = 0, failed_cycles: int = 0, tier: str = "high") -> AttentionItem:
    return AttentionItem(
        employee_id=employee_id,
        process_name="Receiving",
        attention_score=score,
        attention_tier=tier,
        attention_reasons=["reason"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={
            "employee_id": employee_id,
            "process_name": "Receiving",
            "repeat_count": repeat_count,
            "failed_cycles": failed_cycles,
            "snapshot_date": "2026-04-11",
        },
    )


def _summary(items: list[AttentionItem]) -> AttentionSummary:
    return AttentionSummary(
        ranked_items=items,
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=len(items),
    )


def test_overdue_follow_up_outranks_one_off_decline(monkeypatch):
    overdue = _item(employee_id="E1", score=60)
    decline = _item(employee_id="E2", score=90)

    signals = {
        "E1": DisplaySignal(
            employee_name="E1",
            process="Receiving",
            signal_label=SignalLabel.FOLLOW_UP_OVERDUE,
            observed_date=date(2026, 4, 11),
            observed_value=30.0,
            comparison_start_date=date(2026, 4, 6),
            comparison_end_date=date(2026, 4, 10),
            comparison_value=40.0,
            confidence=SignalConfidence.MEDIUM,
            data_completeness=None,
            flags={"overdue": True},
        ),
        "E2": DisplaySignal(
            employee_name="E2",
            process="Receiving",
            signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
            observed_date=date(2026, 4, 11),
            observed_value=30.0,
            comparison_start_date=date(2026, 4, 6),
            comparison_end_date=date(2026, 4, 10),
            comparison_value=40.0,
            confidence=SignalConfidence.HIGH,
            data_completeness=None,
            flags={},
        ),
    }

    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: signals[str(item.employee_id)],
    )

    vm = build_today_queue_view_model(attention=_summary([decline, overdue]), suppressed_cards=[], today=date(2026, 4, 11))
    assert vm.primary_cards[0].employee_id == "E1"


def test_repeat_issue_outranks_mild_new_issue(monkeypatch):
    repeat_issue = _item(employee_id="E3", score=65, repeat_count=3, failed_cycles=1)
    mild_new = _item(employee_id="E4", score=95, repeat_count=0, failed_cycles=0)

    signals = {
        "E3": DisplaySignal(
            employee_name="E3",
            process="Receiving",
            signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
            observed_date=date(2026, 4, 11),
            observed_value=30.0,
            comparison_start_date=date(2026, 4, 6),
            comparison_end_date=date(2026, 4, 10),
            comparison_value=40.0,
            confidence=SignalConfidence.MEDIUM,
            data_completeness=None,
            flags={},
        ),
        "E4": DisplaySignal(
            employee_name="E4",
            process="Receiving",
            signal_label=SignalLabel.BELOW_EXPECTED_PACE,
            observed_date=date(2026, 4, 11),
            observed_value=34.0,
            comparison_start_date=date(2026, 4, 6),
            comparison_end_date=date(2026, 4, 10),
            comparison_value=36.0,
            confidence=SignalConfidence.HIGH,
            data_completeness=None,
            flags={},
        ),
    }

    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: signals[str(item.employee_id)],
    )

    vm = build_today_queue_view_model(attention=_summary([mild_new, repeat_issue]), suppressed_cards=[], today=date(2026, 4, 11))
    assert vm.primary_cards[0].employee_id == "E3"


def test_low_data_does_not_outrank_strong_valid_signal(monkeypatch):
    low_data = _item(employee_id="E5", score=100)
    strong = _item(employee_id="E6", score=70)

    signals = {
        "E5": DisplaySignal(
            employee_name="E5",
            process="Receiving",
            signal_label=SignalLabel.LOW_DATA,
            observed_date=date(2026, 4, 11),
            observed_value=None,
            comparison_start_date=None,
            comparison_end_date=None,
            comparison_value=None,
            confidence=SignalConfidence.LOW,
            data_completeness=None,
            flags={},
        ),
        "E6": DisplaySignal(
            employee_name="E6",
            process="Receiving",
            signal_label=SignalLabel.BELOW_EXPECTED_PACE,
            observed_date=date(2026, 4, 11),
            observed_value=31.0,
            comparison_start_date=date(2026, 4, 6),
            comparison_end_date=date(2026, 4, 10),
            comparison_value=40.0,
            confidence=SignalConfidence.HIGH,
            data_completeness=None,
            flags={},
        ),
    }

    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: signals[str(item.employee_id)],
    )

    vm = build_today_queue_view_model(attention=_summary([low_data, strong]), suppressed_cards=[], today=date(2026, 4, 11))
    assert vm.primary_cards[0].employee_id == "E6"
    assert any(card.employee_id == "E5" for card in vm.secondary_cards)
