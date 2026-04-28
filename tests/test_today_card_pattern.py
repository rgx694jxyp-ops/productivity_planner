from datetime import date
import re

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionFactor, AttentionItem, AttentionSummary
from services.today_view_model_service import build_today_queue_view_model, build_what_changed_text, build_why_surfaced_text
from tests.product_posture_assertions import assert_no_prescriptive_language


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
    assert card.what_changed_line == "Down 22% vs 5-day average"
    assert card.line_3 == "Surfaced because: Declining over the last 6 days"
    assert card.line_4 == "Latest snapshot only"


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
    assert card.what_changed_line == "Performance down 25% vs 5-day average"
    assert card.line_3 == "Surfaced because: Overdue follow-up on declining performance"
    assert card.line_4 == "Latest snapshot only"
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
    assert card.what_changed_line == "Limited data: early signal"
    assert card.line_3 == "Surfaced because: Low confidence: limited recent data"
    assert card.line_4 == "Latest snapshot only"
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
    assert card.what_changed_line == "Down 9% vs 2-day average"
    assert card.line_3 == "Surfaced because: Declining over the last 3 days"
    assert card.line_4 == "Latest snapshot only"
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
    assert card.what_changed_line == "Down 9% vs 2-day average"
    assert card.line_3 == "Surfaced because: Declining over the last 3 days"
    assert card.line_4 == "Latest snapshot only"
    assert card.expanded_lines == ["Repeated 3 times this week"]


def test_today_card_pattern_adds_repeat_evidence_when_snapshot_history_repeats(monkeypatch):
    signal = DisplaySignal(
        employee_name="Alex",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=38.1,
        comparison_start_date=date(2026, 4, 9),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=42.0,
        confidence=SignalConfidence.MEDIUM,
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", lambda item, today: signal)

    base = _item("E9")
    repeated_item = AttentionItem(
        employee_id=base.employee_id,
        process_name=base.process_name,
        attention_score=base.attention_score,
        attention_tier=base.attention_tier,
        attention_reasons=base.attention_reasons,
        attention_summary=base.attention_summary,
        factors_applied=base.factors_applied,
        snapshot={
            "employee_id": "E9",
            "process_name": "Receiving",
            "repeat_count": 3,
            "recent_goal_status_history": ["below_goal", "below_goal", "on_goal", "below_goal", "below_goal"],
        },
    )

    vm = build_today_queue_view_model(attention=_summary(repeated_item), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    assert card.what_changed_line == "Down 9% vs 2-day average"
    assert card.line_3 == "Surfaced because: Below target on 4 of last 5 shifts"
    assert "Seen 3 times in the last 5 snapshots" in card.line_4
    assert card.repeat_count == 3
    assert card.repeat_window_label == "last 5 snapshots"


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
    assert "source:" in joined
    assert "open operational exception remains unresolved" in joined
    assert card.collapsed_hint == "Active operational issue"
    assert card.collapsed_evidence.startswith("Source: ")
    assert card.collapsed_issue == "Active issue linked"


def test_today_card_contract_non_prescriptive_and_required_fields(monkeypatch):
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
    vm = build_today_queue_view_model(attention=_summary(_item("E10")), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    assert " · " in card.line_1
    assert card.line_2
    assert card.what_changed_line
    assert card.line_3
    assert card.line_5.lower().startswith("confidence") or card.line_5.lower() == "low confidence"
    assert str(card.freshness_line or "").startswith("Freshness:")
    assert card.line_4 in {"Latest snapshot only"} or card.line_4.startswith("Based on")

    assert_no_prescriptive_language(
        [
            card.line_1,
            card.line_2,
            card.what_changed_line,
            card.line_3,
            card.line_4,
            card.line_5,
            card.freshness_line,
            *list(card.expanded_lines or []),
            card.collapsed_hint,
            card.collapsed_evidence,
            card.collapsed_issue,
        ]
    )


def test_today_card_process_scope_adds_scope_and_shift_fallback(monkeypatch):
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

    scoped_item = AttentionItem(
        employee_id="E20",
        process_name="Receiving",
        attention_score=80,
        attention_tier="high",
        attention_reasons=["Context line"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={"employee_id": "E20", "process_name": "Receiving", "linked_scope": "process"},
    )

    vm = build_today_queue_view_model(attention=_summary(scoped_item), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    assert card.what_changed_line == "Down 22% vs 5-day average"
    assert card.line_3 == "Surfaced because: Declining over the last 6 days"
    assert "Shift context unavailable in this snapshot" in card.line_4


def test_today_card_shift_context_uses_named_shift_when_present(monkeypatch):
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

    shift_item = AttentionItem(
        employee_id="E21",
        process_name="Receiving",
        attention_score=80,
        attention_tier="high",
        attention_reasons=["Context line"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={"employee_id": "E21", "process_name": "Receiving", "shift_name": "Night"},
    )

    vm = build_today_queue_view_model(attention=_summary(shift_item), suppressed_cards=[], today=date(2026, 4, 11))
    card = vm.primary_cards[0]

    assert "Shift context: Night" in card.line_4


def test_build_why_surfaced_text_prefers_follow_up_due_today():
    result = build_why_surfaced_text(
        {
            "follow_up_status": "due_today",
            "signal_label": "below_expected_pace",
            "decline_pct": -12.0,
            "window_days": 14,
            "below_target_count": 4,
            "below_target_total": 5,
            "confidence_level": "low",
            "limited_recent_data": True,
        }
    )

    assert result == "Surfaced because: Follow-up due today for below-target performance"


def test_build_what_changed_text_calculates_down_percent_against_recent_average():
    result = build_what_changed_text(
        {
            "observed_value": 32.4,
            "comparison_value": 40.0,
            "comparison_start_date": date(2026, 4, 6),
            "comparison_end_date": date(2026, 4, 10),
        }
    )

    assert result == "Down 19% vs 5-day average"


def test_build_what_changed_text_maps_up_direction_to_last_week():
    result = build_what_changed_text(
        {
            "observed_value": 44.8,
            "comparison_value": 40.0,
            "comparison_start_date": date(2026, 4, 4),
            "comparison_end_date": date(2026, 4, 10),
        }
    )

    assert result == "Up 12% vs last week"


def test_build_what_changed_text_prefixes_follow_up_delta_as_performance_change():
    result = build_what_changed_text(
        {
            "follow_up_status": "overdue",
            "observed_value": 30.0,
            "comparison_value": 40.0,
            "comparison_start_date": date(2026, 4, 6),
            "comparison_end_date": date(2026, 4, 10),
        }
    )

    assert result == "Performance down 25% vs 5-day average"


def test_build_what_changed_text_handles_no_significant_change_and_limited_data():
    stable = build_what_changed_text(
        {
            "observed_value": 39.2,
            "comparison_value": 40.0,
            "comparison_start_date": date(2026, 4, 6),
            "comparison_end_date": date(2026, 4, 10),
        }
    )
    limited = build_what_changed_text({"limited_recent_data": True})

    assert stable == "No significant change (2%) vs 5-day average"
    assert limited == "Limited data: early signal"


def test_build_what_changed_text_avoids_banned_words():
    outputs = [
        build_what_changed_text(
            {
                "observed_value": 32.4,
                "comparison_value": 40.0,
                "comparison_start_date": date(2026, 4, 6),
                "comparison_end_date": date(2026, 4, 10),
            }
        ),
        build_what_changed_text(
            {
                "observed_value": 44.8,
                "comparison_value": 40.0,
                "comparison_start_date": date(2026, 4, 4),
                "comparison_end_date": date(2026, 4, 10),
            }
        ),
        build_what_changed_text(
            {
                "observed_value": 39.2,
                "comparison_value": 40.0,
                "comparison_start_date": date(2026, 4, 6),
                "comparison_end_date": date(2026, 4, 10),
            }
        ),
    ]

    banned_words = ["slightly", "softening", "debug", "json", "id="]
    for output in outputs:
        lowered = output.lower()
        assert not any(word in lowered for word in banned_words)


def test_build_why_surfaced_text_combines_overdue_follow_up_with_declining_context():
    result = build_why_surfaced_text(
        {
            "follow_up_status": "overdue",
            "signal_label": "lower_than_recent_pace",
            "decline_pct": -6.7,
            "window_days": 14,
        }
    )

    assert result == "Surfaced because: Overdue follow-up on declining performance"


def test_build_why_surfaced_text_keeps_follow_up_isolated_without_context():
    result = build_why_surfaced_text({"follow_up_status": "overdue"})

    assert result == "Surfaced because: Overdue follow-up"


def test_build_why_surfaced_text_chooses_decline_before_frequency():
    result = build_why_surfaced_text(
        {
            "signal_label": "lower_than_recent_pace",
            "decline_pct": -6.7,
            "window_days": 14,
            "below_target_count": 4,
            "below_target_total": 5,
            "confidence_level": "high",
        }
    )

    assert result == "Surfaced because: Below target on 4 of last 5 shifts"


def test_build_why_surfaced_text_uses_shift_history_before_recent_shift():
    result = build_why_surfaced_text(
        {
            "signal_label": "below_expected_pace",
            "below_target_count": 1,
            "below_target_total": 1,
        }
    )

    assert result == "Surfaced because: Below target on 1 of last 1 shifts"


def test_build_why_surfaced_text_uses_recent_shift_only_without_history():
    result = build_why_surfaced_text({"signal_label": "below_expected_pace"})

    assert result == "Surfaced because: Below target on recent shift"


def test_build_why_surfaced_text_avoids_banned_words_and_keeps_prefix():
    outputs = [
        build_why_surfaced_text({"follow_up_status": "overdue"}),
        build_why_surfaced_text({"follow_up_status": "due_today", "signal_label": "below_expected_pace"}),
        build_why_surfaced_text({"signal_label": "lower_than_recent_pace", "decline_pct": -5.0, "window_days": 14}),
        build_why_surfaced_text({"below_target_count": 4, "below_target_total": 5}),
        build_why_surfaced_text({"confidence_level": "low", "limited_recent_data": True}),
    ]

    banned_words = ["slightly", "softening", "debug", "json", "id="]
    for output in outputs:
        lowered = output.lower()
        assert output.startswith("Surfaced because:")
        assert not any(word in lowered for word in banned_words)
