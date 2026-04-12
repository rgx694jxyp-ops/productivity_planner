from datetime import date

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.today_view_model_service import build_today_queue_view_model


def _item(employee_id: str = "E1") -> AttentionItem:
    return AttentionItem(
        employee_id=employee_id,
        process_name="Receiving",
        attention_score=80,
        attention_tier="high",
        attention_reasons=["Context line"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={"employee_id": employee_id, "process_name": "Receiving"},
    )


def _summary(item: AttentionItem) -> AttentionSummary:
    return AttentionSummary(
        ranked_items=[item],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=1,
    )


def test_today_card_pattern_performance_signal(monkeypatch):
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=31.2,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=40.0,
        confidence=SignalConfidence.HIGH,
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)

    vm = build_today_queue_view_model(attention=_summary(_item()), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    assert card.line_1 == "Alex · Receiving"
    assert card.line_2 == "Below expected pace"
    assert card.line_3.startswith("Observed: ")
    assert "(" in card.line_3 and "UPH" in card.line_3
    assert card.line_4.startswith("Compared to: ") and "avg" in card.line_4
    assert card.line_5 == "Confidence: High"


def test_today_card_pattern_follow_up_signal(monkeypatch):
    signal = DisplaySignal(
        employee_name="Taylor",
        process="Packing",
        signal_label=SignalLabel.FOLLOW_UP_OVERDUE,
        observed_date=date(2026, 4, 11),
        observed_value=30.0,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=40.0,
        confidence=SignalConfidence.MEDIUM,
        data_completeness=None,
        flags={"overdue": True},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)

    vm = build_today_queue_view_model(attention=_summary(_item("E2")), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    assert card.line_1 == "Taylor · Receiving"
    assert card.line_2 == "Follow-up not completed"
    assert card.line_3 == "Due: Overdue"
    assert card.line_4 != ""
    assert card.line_5 == "Confidence: Medium"


def test_today_card_pattern_low_data_signal(monkeypatch):
    signal = DisplaySignal(
        employee_name="Jordan",
        process="Shipping",
        signal_label=SignalLabel.LOW_DATA,
        observed_date=date(2026, 4, 11),
        observed_value=None,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)

    vm = build_today_queue_view_model(attention=_summary(_item("E3")), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.secondary_cards[0]

    assert card.line_1 == "Jordan · Receiving"
    assert card.line_2 == "Not enough history yet"
    assert card.line_3 == "Confidence: Low"
    assert card.line_4 == ""
    assert card.line_5 == "Confidence: Low"


def test_today_card_expanded_lines_max_3_and_not_repeated(monkeypatch):
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=31.2,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=40.0,
        confidence=SignalConfidence.HIGH,
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)
    monkeypatch.setattr(
        "services.today_view_model_service._attention_context_lines",
        lambda item, signal, max_lines=2: [
            "Below expected pace",
            "Observed variance persisted",
            "Compared window was stable",
            "No system artifact",
            "Extra line should be trimmed",
        ],
    )

    vm = build_today_queue_view_model(attention=_summary(_item()), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    assert len(card.expanded_lines) <= 3
    assert all(line.strip().lower() != card.line_2.strip().lower() for line in card.expanded_lines)
