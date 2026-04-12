from datetime import date
import re

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionFactor, AttentionItem, AttentionSummary
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
    assert card.line_4 == ""
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
        supporting_text=[
            "Only 1 recent record(s) available",
            "Low confidence",
            "Missing baseline",
        ],
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)

    vm = build_today_queue_view_model(attention=_summary(_item("E3")), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.secondary_cards[0]

    assert card.line_1 == "Jordan · Receiving"
    assert card.line_2 == "Not enough history yet"
    assert card.line_3 == ""
    assert card.line_4 == ""
    assert card.line_5 == "Low confidence"
    assert card.expanded_lines == ["Only 1 recent record(s) available", "Observed: Apr 11"]


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


def test_today_card_trend_lines_use_canonical_short_window_and_no_repeated_meaning(monkeypatch):
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 9),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        confidence=SignalConfidence.LOW,
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)
    monkeypatch.setattr(
        "services.today_view_model_service._attention_context_lines",
        lambda item, signal, max_lines=2: [
            "Observed: Apr 11 (38.1 UPH)",
            "Compared to: Apr 9-Apr 10 avg (42.0 UPH)",
            "Watch for continued drift",
        ],
    )

    vm = build_today_queue_view_model(attention=_summary(_item()), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.secondary_cards[0]

    assert card.line_2 == "Lower than recent pace"
    assert card.line_3 == "Observed: Apr 11 (38.1 UPH)"
    assert card.line_4 == "Compared to: Apr 9–Apr 10 avg (42.0 UPH)"
    assert card.line_5 == "Confidence: Low"
    assert card.expanded_lines == ["Watch for continued drift"]


def test_today_card_pattern_shows_one_repeat_support_line_without_overriding_trend_headline(monkeypatch):
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 9),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        confidence=SignalConfidence.LOW,
        pattern_count=3,
        pattern_window_label="this week",
        supporting_text=["Seen 3 times this week"],
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)

    vm = build_today_queue_view_model(attention=_summary(_item()), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.secondary_cards[0]

    assert card.line_2 == "Lower than recent pace"
    assert card.line_3 == "Observed: Apr 11 (38.1 UPH)"
    assert card.line_4 == "Compared to: Apr 9–Apr 10 avg (42.0 UPH)"
    assert card.expanded_lines == ["Seen 3 times this week"]


def test_today_card_expanded_lines_humanize_iso_dates(monkeypatch):
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
            "Observed: 2026-04-11 (31.2 UPH)",
            "Compared to: 2026-04-06-2026-04-10 avg (40.0 UPH)",
        ],
    )

    vm = build_today_queue_view_model(attention=_summary(_item()), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    iso_pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    assert all(not iso_pattern.search(line) for line in card.expanded_lines)


def test_today_card_expanded_lines_include_source_and_exception_context(monkeypatch):
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

    item = AttentionItem(
        employee_id="E9",
        process_name="Receiving",
        attention_score=85,
        attention_tier="high",
        attention_reasons=["Context line"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={
            "employee_id": "E9",
            "process_name": "Receiving",
            "source_summary": "daily performance upload",
        },
    )
    item = AttentionItem(
        employee_id=item.employee_id,
        process_name=item.process_name,
        attention_score=item.attention_score,
        attention_tier=item.attention_tier,
        attention_reasons=item.attention_reasons,
        attention_summary=item.attention_summary,
        factors_applied=[AttentionFactor("open_exception", 15, "Has unresolved operational exception")],
        snapshot=item.snapshot,
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)

    vm = build_today_queue_view_model(attention=_summary(item), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    joined = " | ".join(card.expanded_lines).lower()
    assert "signal source:" in joined
    assert "open operational exception is still unresolved" in joined
    assert card.collapsed_hint.startswith("Flagged due to")
    assert card.collapsed_evidence.startswith("Source: ")
    assert card.collapsed_issue == "Active issue linked"
