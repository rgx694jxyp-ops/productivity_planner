from datetime import date

from domain.display_signal import DisplaySignal, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.today_view_model_service import build_today_queue_view_model
from ui.today_queue import build_action_queue


def _attention_item(*, employee_id: str, tier: str = "high") -> AttentionItem:
    return AttentionItem(
        employee_id=employee_id,
        process_name="Receiving",
        attention_score=80,
        attention_tier=tier,
        attention_reasons=["test"],
        attention_summary="test summary",
        factors_applied=[],
        snapshot={"employee_id": employee_id, "process_name": "Receiving"},
    )


def _display_signal(*, employee_name: str, confidence: SignalConfidence = SignalConfidence.HIGH, flags: dict | None = None) -> DisplaySignal:
    return DisplaySignal(
        employee_name=employee_name,
        process="Receiving",
        signal_label=SignalLabel.BELOW_EXPECTED_PACE,
        observed_date=date(2026, 4, 11),
        observed_value=30.0,
        comparison_start_date=date(2026, 4, 6),
        comparison_end_date=date(2026, 4, 10),
        comparison_value=40.0,
        confidence=confidence,
        data_completeness=None,
        flags=flags or {},
    )


def test_invalid_cards_never_appear_in_primary_today_queue(monkeypatch):
    valid_item = _attention_item(employee_id="E1")
    invalid_item = _attention_item(employee_id="E2")
    summary = AttentionSummary(
        ranked_items=[valid_item, invalid_item],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=2,
    )

    def _fake_build_signal(item, today):
        if str(item.employee_id) == "E2":
            return _display_signal(employee_name="E2", flags={"system_artifact": True})
        return _display_signal(employee_name="E1")

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", _fake_build_signal)

    queue_vm = build_today_queue_view_model(attention=summary, suppressed_cards=[], today=date(2026, 4, 11))

    assert len(queue_vm.primary_cards) == 1
    assert str(queue_vm.primary_cards[0].employee_id) == "E1"
    assert len(queue_vm.secondary_cards) == 0
    assert len(queue_vm.suppressed) == 1
    assert queue_vm.suppressed[0].employee == "E2"


def test_low_confidence_cards_go_to_secondary_today_queue(monkeypatch):
    low_conf_item = _attention_item(employee_id="E3", tier="high")
    summary = AttentionSummary(
        ranked_items=[low_conf_item],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=1,
    )

    def _fake_build_signal(item, today):
        return _display_signal(employee_name="E3", confidence=SignalConfidence.LOW)

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", _fake_build_signal)

    queue_vm = build_today_queue_view_model(attention=summary, suppressed_cards=[], today=date(2026, 4, 11))

    assert len(queue_vm.primary_cards) == 0
    assert len(queue_vm.secondary_cards) == 1
    assert str(queue_vm.secondary_cards[0].employee_id) == "E3"
    assert len(queue_vm.suppressed) == 0


def test_build_action_queue_suppresses_invalid_items_from_primary_flow():
    queue_items = build_action_queue(
        open_actions=[
            {
                "id": "A1",
                "employee_id": "E1",
                "employee_name": "Alex",
                "issue_type": "low_performance",
                "priority": "high",
                "_system_artifact": True,
            },
            {
                "id": "A2",
                "employee_id": "E2",
                "employee_name": "Taylor",
                "issue_type": "low_performance",
                "priority": "high",
            },
        ],
        repeat_offenders=[],
        recognition_opportunities=[],
        tenant_id="tenant-test",
        today=date(2026, 4, 11),
    )

    ids = {str(row.get("id") or "") for row in queue_items}
    assert "A1" not in ids
    assert "A2" in ids


def test_build_action_queue_routes_low_confidence_to_secondary_bucket():
    queue_items = build_action_queue(
        open_actions=[
            {
                "id": "A3",
                "employee_id": "E3",
                "employee_name": "Jordan",
                "issue_type": "low_performance",
                "priority": "medium",
                "confidence_label": "low",
            }
        ],
        repeat_offenders=[],
        recognition_opportunities=[],
        tenant_id="tenant-test",
        today=date(2026, 4, 11),
    )

    assert len(queue_items) == 1
    assert queue_items[0]["_display_bucket"] == "secondary"
