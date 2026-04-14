from datetime import date

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionFactor, AttentionItem, AttentionSummary
from services.decision_engine_service import DecisionItem
from services.today_view_model_service import build_today_queue_view_model


def test_today_queue_view_model_prefers_decision_items(monkeypatch):
    attention_item = AttentionItem(
        employee_id="E1",
        process_name="Receiving",
        attention_score=78,
        attention_tier="high",
        attention_reasons=["Decline compared to recent baseline performance"],
        attention_summary="E1 (Receiving) - ranked highly.",
        factors_applied=[
            AttentionFactor(
                key="trend_declining",
                weight=25,
                plain_reason="Decline compared to recent baseline performance",
            )
        ],
        snapshot={
            "employee_id": "E1",
            "Department": "Receiving",
            "trend": "declining",
            "confidence_label": "high",
            "data_completeness_status": "partial",
            "Average UPH": 35,
            "Target UPH": 50,
            "snapshot_date": "2026-04-13",
        },
    )
    decision_item = DecisionItem(
        employee_id="E1",
        process_name="Receiving",
        final_score=96,
        final_tier="high",
        attention_score=78,
        action_score=18,
        action_priority="high",
        action_queue_status="overdue",
        primary_reason="Decline compared to recent baseline performance",
        confidence_label="High",
        confidence_basis="Based on 3 included day(s) with configured target context.",
        normalized_action_state="overdue_follow_up",
        normalized_action_state_detail="Overdue",
        attention_item=attention_item,
        source_snapshot=dict(attention_item.snapshot),
    )

    vm = build_today_queue_view_model(
        attention=AttentionSummary(ranked_items=[], is_healthy=False, healthy_message="", suppressed_count=0, total_evaluated=1),
        decision_items=[decision_item],
        suppressed_cards=[],
        today=date(2026, 4, 13),
        action_state_lookup={"E1": {"state": "overdue_follow_up", "state_detail": "Overdue"}},
    )

    assert vm.primary_cards[0].employee_id == "E1"
    assert vm.primary_cards[0].normalized_action_state == "overdue_follow_up"
    assert any("configured target context" in line for line in vm.primary_cards[0].expanded_lines)


def test_today_queue_view_model_does_not_use_attention_fallback_when_disabled(monkeypatch):
    attention_item = AttentionItem(
        employee_id="E2",
        process_name="Receiving",
        attention_score=78,
        attention_tier="high",
        attention_reasons=["Decline compared to recent baseline performance"],
        attention_summary="E2 (Receiving) - ranked highly.",
        factors_applied=[
            AttentionFactor(
                key="trend_declining",
                weight=25,
                plain_reason="Decline compared to recent baseline performance",
            )
        ],
        snapshot={
            "employee_id": "E2",
            "Department": "Receiving",
            "trend": "declining",
            "confidence_label": "high",
            "data_completeness_status": "complete",
            "Average UPH": 35,
            "Target UPH": 50,
            "snapshot_date": "2026-04-13",
        },
    )

    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda **kwargs: DisplaySignal(
            employee_name="E2",
            process="Receiving",
            signal_label=SignalLabel.BELOW_EXPECTED_PACE,
            observed_date=date(2026, 4, 13),
            observed_value=35.0,
            comparison_start_date=date(2026, 4, 10),
            comparison_end_date=date(2026, 4, 12),
            comparison_value=50.0,
            confidence=SignalConfidence.HIGH,
            data_completeness=None,
            flags={},
        ),
    )

    vm = build_today_queue_view_model(
        attention=AttentionSummary(ranked_items=[attention_item], is_healthy=False, healthy_message="", suppressed_count=0, total_evaluated=1),
        decision_items=[],
        allow_legacy_attention_fallback=False,
        suppressed_cards=[],
        today=date(2026, 4, 13),
    )

    assert vm.primary_cards == []