from datetime import date

from domain.display_signal import DisplaySignal, DisplaySignalState, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.daily_signals_service import _build_import_summary
from services.today_view_model_service import build_today_queue_view_model, build_today_value_strip_view_model


def _attention_item(employee_id: str = "E1") -> AttentionItem:
    return AttentionItem(
        employee_id=employee_id,
        process_name="Receiving",
        attention_score=70,
        attention_tier="medium",
        attention_reasons=["reason"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={"employee_id": employee_id, "process_name": "Receiving"},
    )


def test_current_state_card_keeps_confidence_and_freshness_visible(monkeypatch):
    summary = AttentionSummary(
        ranked_items=[_attention_item("E9")],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=1,
    )

    current_signal = DisplaySignal(
        employee_name="E9",
        process="Receiving",
        signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
        observed_date=date.today(),
        observed_value=36.0,
        comparison_start_date=None,
        comparison_end_date=None,
        comparison_value=None,
        confidence=SignalConfidence.LOW,
        state=DisplaySignalState.CURRENT,
        primary_label="Current pace",
        data_completeness=None,
        flags={},
    )

    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        lambda item, today: current_signal,
    )

    vm = build_today_queue_view_model(attention=summary, suppressed_cards=[], today=date.today())

    assert vm.primary_cards
    card = vm.primary_cards[0]
    assert card.line_5 == "Low confidence"
    assert card.freshness_line.startswith("Freshness:")


def test_value_strip_data_health_includes_confidence_label():
    strip = build_today_value_strip_view_model(
        goal_status=[
            {
                "EmployeeID": "E1",
                "Employee": "Alex",
                "Department": "Pack",
                "Average UPH": 100,
                "Target UPH": 110,
                "change_pct": -3.0,
                "trend": "declining",
                "confidence_label": "medium",
                "Record Count": 4,
            }
        ],
        import_summary={
            "days": 2,
            "emp_count": 1,
            "rows_processed": 20,
            "valid_rows": 18,
            "warning_rows": 2,
            "trust": {"status": "partial", "confidence_score": 62},
        },
    )

    data_health = next((card for card in strip.cards if card.title == "Data health"), None)
    assert data_health is not None
    assert "Confidence:" in str(data_health.detail)


def test_build_import_summary_prefers_latest_upload_trust(monkeypatch):
    def _fake_uploads(tenant_id: str, days: int = 30):
        return [
            {
                "is_active": True,
                "header_mapping": {
                    "stats": {
                        "candidate_rows": 120,
                        "accepted_rows": 108,
                        "warnings": 7,
                        "rejected_rows": 12,
                        "trust_status": "partial",
                        "confidence_score": 64,
                    }
                },
            }
        ]

    monkeypatch.setattr("services.import_service._list_recent_uploads", _fake_uploads)
    monkeypatch.setattr("services.import_service._decode_jsonish", lambda raw: raw if isinstance(raw, dict) else {})

    out = _build_import_summary(
        tenant_id="tenant-1",
        goal_status=[
            {"EmployeeID": "E1", "goal_status": "below_goal", "Record Count": 2},
            {"EmployeeID": "E2", "goal_status": "on_goal", "Record Count": 2},
        ],
    )

    assert out["rows_processed"] == 120
    assert out["valid_rows"] == 108
    assert out["warning_rows"] == 7
    assert out["rejected_rows"] == 12
    assert out["trust"]["status"] == "partial"
    assert out["trust"]["confidence_score"] == 64
