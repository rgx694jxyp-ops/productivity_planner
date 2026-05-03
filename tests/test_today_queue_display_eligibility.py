from datetime import date
from pathlib import Path

from domain.display_signal import DisplaySignal, DisplaySignalState, SignalConfidence, SignalLabel
from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.today_queue_service import build_action_queue
from services.today_view_model_service import build_today_queue_view_model, build_today_value_strip_view_model


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


def test_today_page_shows_follow_ups_today_when_only_current_signals_exist(monkeypatch):
    current_item = _attention_item(employee_id="E4", tier="high")
    summary = AttentionSummary(
        ranked_items=[current_item],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=1,
    )

    def _fake_build_signal(item, today):
        return DisplaySignal(
            employee_name="E4",
            process="Receiving",
            signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
            observed_date=date(2026, 4, 11),
            observed_value=38.1,
            comparison_start_date=None,
            comparison_end_date=None,
            comparison_value=None,
            confidence=SignalConfidence.LOW,
            state=DisplaySignalState.CURRENT,
            primary_label="Current pace",
            data_completeness=None,
            flags={},
        )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", _fake_build_signal)

    queue_vm = build_today_queue_view_model(attention=summary, suppressed_cards=[], today=date(2026, 4, 11))

    assert queue_vm.main_section_title == "Follow-ups Today"
    assert len(queue_vm.primary_cards) == 1
    assert str(queue_vm.primary_cards[0].employee_id) == "E4"
    assert queue_vm.primary_cards[0].state == "CURRENT"
    assert len(queue_vm.secondary_cards) == 0


def test_today_page_shows_follow_ups_today_heading_when_trend_signals_exist(monkeypatch):
    trend_item = _attention_item(employee_id="E5", tier="high")
    summary = AttentionSummary(
        ranked_items=[trend_item],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=1,
    )

    def _fake_build_signal(item, today):
        return DisplaySignal(
            employee_name="E5",
            process="Receiving",
            signal_label=SignalLabel.LOWER_THAN_RECENT_PACE,
            observed_date=date(2026, 4, 11),
            observed_value=31.0,
            comparison_start_date=date(2026, 4, 9),
            comparison_end_date=date(2026, 4, 10),
            comparison_value=38.0,
            confidence=SignalConfidence.LOW,
            state=DisplaySignalState.EARLY_TREND,
            primary_label="Lower than recent pace",
            data_completeness=None,
            flags={},
        )

    monkeypatch.setattr("services.today_view_model_service.build_display_signal_from_attention_item", _fake_build_signal)

    queue_vm = build_today_queue_view_model(attention=summary, suppressed_cards=[], today=date(2026, 4, 11))

    assert queue_vm.main_section_title == "Follow-ups Today"
    assert len(queue_vm.primary_cards) == 0
    assert len(queue_vm.secondary_cards) == 1
    assert queue_vm.secondary_cards[0].state == "EARLY_TREND"


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


def test_legacy_ui_queue_wrapper_delegates_to_canonical_service(monkeypatch):
    captured = {}

    def _fake_build_action_queue(**kwargs):
        captured.update(kwargs)
        return [{"id": "A9", "_display_bucket": "primary"}]

    monkeypatch.setattr("ui.today_queue.build_action_queue_service", _fake_build_action_queue)

    from ui.today_queue import build_action_queue as build_action_queue_legacy

    result = build_action_queue_legacy(
        open_actions=[{"id": "A9"}],
        repeat_offenders=[{"employee_id": "E9"}],
        recognition_opportunities=[{"action_id": "A9"}],
        tenant_id="tenant-test",
        today=date(2026, 4, 11),
    )

    assert result == [{"id": "A9", "_display_bucket": "primary"}]
    assert captured["open_actions"] == [{"id": "A9"}]
    assert captured["repeat_offenders"] == [{"employee_id": "E9"}]
    assert captured["recognition_opportunities"] == [{"action_id": "A9"}]
    assert captured["tenant_id"] == "tenant-test"


def test_legacy_ui_queue_module_does_not_redefine_canonical_queue_helpers():
    source = Path("ui/today_queue.py").read_text()

    banned_defs = [
        "def _queue_status(",
        "def _short_reason(",
        "def _good_looks_like(",
        "def _build_repeat_lookup(",
        "def _build_recognition_lookup(",
        "def _why_this_is_here(",
        "def _surfaced_factors(",
        "def _is_queue_item_display_eligible(",
        "def _display_bucket(",
        "def _sort_key(",
    ]

    for marker in banned_defs:
        assert marker not in source, f"Legacy ui/today_queue.py reintroduced duplicate helper: {marker}"


def test_today_value_strip_prefers_existing_goal_status_and_import_summary_data():
    value_strip = build_today_value_strip_view_model(
        goal_status=[
            {
                "EmployeeID": "E1",
                "Employee": "Alex",
                "Department": "Packing",
                "Average UPH": 118,
                "Target UPH": 100,
                "change_pct": 4.0,
                "trend": "up",
                "confidence_label": "high",
                "Record Count": 5,
            },
            {
                "EmployeeID": "E2",
                "Employee": "Blair",
                "Department": "Receiving",
                "Average UPH": 56,
                "Target UPH": 60,
                "change_pct": -14.2,
                "trend": "declining",
                "confidence_label": "medium",
                "Record Count": 4,
            },
            {
                "EmployeeID": "E3",
                "Employee": "Casey",
                "Department": "Dock",
                "Average UPH": 72,
                "Target UPH": 70,
                "change_pct": 0.0,
                "trend": "insufficient_data",
                "confidence_label": "low",
                "Record Count": 1,
            },
        ],
        import_summary={
            "days": 1,
            "emp_count": 3,
            "rows_processed": 40,
            "valid_rows": 38,
            "warning_rows": 2,
            "trust": {"status": "partial", "confidence_score": 72},
        },
    )

    assert [card.title for card in value_strip.cards] == [
        "Top performance today",
        "Biggest change today",
        "New employee flag",
        "Data health",
    ]
    assert value_strip.cards[0].headline == "Alex at 118 UPH"
    assert value_strip.cards[1].headline == "Blair down 14%"
    assert value_strip.cards[2].headline == "Casey · Dock"
    assert value_strip.cards[3].headline == "Data needs a quick double-check"
    assert value_strip.cards[3].detail == "38/40 rows usable · Confidence: Medium"


def test_today_value_strip_omits_blocks_without_clear_supporting_data():
    value_strip = build_today_value_strip_view_model(
        goal_status=[
            {
                "EmployeeID": "E1",
                "Employee": "Alex",
                "Department": "Packing",
                "Average UPH": 94,
                "Target UPH": 100,
                "change_pct": 0.0,
                "trend": "insufficient_data",
                "confidence_label": "low",
                "Record Count": 5,
            }
        ],
        import_summary={},
    )

    assert [card.title for card in value_strip.cards] == ["Top performance today"]
