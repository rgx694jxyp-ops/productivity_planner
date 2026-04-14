from datetime import date

from domain.insight_card_contract import (
    ConfidenceInfo,
    DataCompletenessNote,
    DrillDownTarget,
    InsightCardContract,
    TimeContext,
    TraceabilityContext,
    VolumeWorkloadContext,
)
from services.attention_scoring_service import AttentionSummary
from services.attention_scoring_service import AttentionFactor, AttentionItem
from services import daily_signals_service as dss
from services.decision_engine_service import DecisionItem, build_decision_summary
from services.today_page_meaning_service import is_weak_data_mode


def test_empty_eligible_employee_ids_aligns_between_persistent_and_transient(monkeypatch):
    captured: list[set[str] | None] = []

    monkeypatch.setattr(dss, "get_open_actions", lambda **kwargs: [])
    monkeypatch.setattr(dss, "get_repeat_offenders", lambda **kwargs: [])
    monkeypatch.setattr(dss, "get_ignored_high_performers", lambda **kwargs: [])
    monkeypatch.setattr(dss, "build_action_queue", lambda **kwargs: [])
    monkeypatch.setattr(
        dss,
        "get_latest_snapshot_goal_status",
        lambda **kwargs: (
            [
                {
                    "EmployeeID": "E1",
                    "Department": "Packing",
                    "trend": "declining",
                    "confidence_label": "high",
                    "repeat_count": 0,
                    "Target UPH": 50,
                    "Average UPH": 40,
                }
            ],
            [],
            "2026-04-13",
        ),
    )
    monkeypatch.setattr(dss, "_build_import_summary", lambda **kwargs: {"days": 5})
    monkeypatch.setattr(
        dss,
        "build_today_home_sections",
        lambda **kwargs: {
            "needs_attention": [],
            "changed_from_normal": [],
            "unresolved_items": [],
        },
    )
    monkeypatch.setattr(dss, "list_open_operational_exceptions", lambda **kwargs: [])

    def _fake_build_today_attention_summary(**kwargs):
        captured.append(kwargs.get("eligible_employee_ids"))
        return AttentionSummary(
            ranked_items=[],
            is_healthy=True,
            healthy_message="",
            suppressed_count=0,
            total_evaluated=1,
        )

    monkeypatch.setattr(dss, "build_today_attention_summary", _fake_build_today_attention_summary)
    monkeypatch.setattr(dss, "build_decision_items", lambda **kwargs: [])
    monkeypatch.setattr(dss, "delete_daily_signals", lambda **kwargs: None)
    monkeypatch.setattr(dss, "batch_upsert_daily_signals", lambda rows: None)

    dss.compute_daily_signals(signal_date=date(2026, 4, 13), tenant_id="tenant-1")
    dss.build_transient_today_payload(signal_date=date(2026, 4, 13), tenant_id="tenant-1")

    assert captured == [None, None]


def test_daily_signals_weak_data_mode_matches_today_meaning_service() -> None:
    samples = [
        {"days": 5, "trust": {"status": "valid", "confidence_score": 88}},
        {"days": 2, "trust": {"status": "valid", "confidence_score": 88}},
        {"days": 5, "trust": {"status": "partial", "confidence_score": 88}},
        {"days": 5, "trust": {"status": "valid", "confidence_score": 70}},
    ]

    assert [dss._is_weak_data_mode(sample) for sample in samples] == [
        is_weak_data_mode(import_summary=sample) for sample in samples
    ]


def test_transient_payload_matches_precomputed_round_trip(monkeypatch):
    captured_rows = []
    signal_date = date(2026, 4, 13)

    home_card = InsightCardContract(
        insight_id="card-1",
        insight_kind="below_expected_performance",
        title="Lower than expected",
        what_happened="Observed pace came in below target.",
        compared_to_what="Compared with configured target.",
        why_flagged="Surfaced because the gap was material.",
        confidence=ConfidenceInfo(level="medium"),
        workload_context=VolumeWorkloadContext(observed_volume=40.0, baseline_volume=50.0),
        time_context=TimeContext(observed_window_label="Today"),
        data_completeness=DataCompletenessNote(status="partial", summary="Partial history"),
        drill_down=DrillDownTarget(screen="team", entity_id="E1", label="Open details"),
        traceability=TraceabilityContext(),
        source_references=[],
        metadata={"employee_id": "E1", "repeat_count": 1},
    )
    attention_summary = AttentionSummary(
        ranked_items=[
            AttentionItem(
                employee_id="E1",
                process_name="Packing",
                attention_score=78,
                attention_tier="high",
                attention_reasons=["Decline compared to recent baseline performance"],
                attention_summary="E1 (Packing) — ranked highly: decline compared to recent baseline performance.",
                factors_applied=[
                    AttentionFactor(
                        key="trend_declining",
                        weight=25,
                        plain_reason="Decline compared to recent baseline performance",
                    )
                ],
                snapshot={
                    "employee_id": "E1",
                    "Department": "Packing",
                    "Average UPH": 40,
                    "Target UPH": 50,
                    "confidence_label": "high",
                    "data_completeness_status": "partial",
                    "repeat_count": 1,
                },
            )
        ],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=1,
    )

    monkeypatch.setattr(dss, "get_open_actions", lambda **kwargs: [{"employee_id": "E1", "_queue_status": "overdue"}])
    monkeypatch.setattr(dss, "get_repeat_offenders", lambda **kwargs: [])
    monkeypatch.setattr(dss, "get_ignored_high_performers", lambda **kwargs: [])
    monkeypatch.setattr(dss, "build_action_queue", lambda **kwargs: [{"employee_id": "E1", "_queue_status": "overdue"}])
    monkeypatch.setattr(
        dss,
        "get_latest_snapshot_goal_status",
        lambda **kwargs: (
            [
                {
                    "EmployeeID": "E1",
                    "Employee": "Alex",
                    "Department": "Packing",
                    "Average UPH": 40,
                    "Target UPH": 50,
                    "trend": "declining",
                    "goal_status": "below_goal",
                    "confidence_label": "high",
                    "repeat_count": 1,
                }
            ],
            [],
            "2026-04-13",
        ),
    )
    monkeypatch.setattr(
        dss,
        "_build_import_summary",
        lambda **kwargs: {"days": 5, "trust": {"status": "valid", "confidence_score": 88}},
    )
    monkeypatch.setattr(
        dss,
        "build_today_home_sections",
        lambda **kwargs: {
            "needs_attention": [home_card],
            "changed_from_normal": [],
            "unresolved_items": [],
            "data_warnings": [],
            "suppressed_signals": [],
        },
    )
    monkeypatch.setattr(dss, "list_open_operational_exceptions", lambda **kwargs: [])
    monkeypatch.setattr(dss, "build_today_attention_summary", lambda **kwargs: attention_summary)
    decision_items = [
        DecisionItem(
            employee_id="E1",
            process_name="Packing",
            final_score=90,
            final_tier="high",
            attention_score=78,
            action_score=12,
            action_priority="high",
            action_queue_status="overdue",
            primary_reason="Decline compared to recent baseline performance",
            confidence_label="High",
            confidence_basis="Based on 3 included day(s) with configured target context.",
            normalized_action_state="overdue_follow_up",
            normalized_action_state_detail="Overdue",
            attention_item=attention_summary.ranked_items[0],
            source_snapshot=dict(attention_summary.ranked_items[0].snapshot or {}),
        )
    ]
    monkeypatch.setattr(dss, "build_decision_items", lambda **kwargs: decision_items)
    monkeypatch.setattr(dss, "delete_daily_signals", lambda **kwargs: None)
    monkeypatch.setattr(dss, "batch_upsert_daily_signals", lambda rows: captured_rows.extend(rows))

    transient = dss.build_transient_today_payload(signal_date=signal_date, tenant_id="tenant-1")
    dss.compute_daily_signals(signal_date=signal_date, tenant_id="tenant-1")

    today_payload_row = next(row for row in captured_rows if row.get("signal_type") == "today_payload")
    monkeypatch.setattr(dss, "list_daily_signals", lambda **kwargs: [today_payload_row])

    precomputed = dss.read_precomputed_today_signals(tenant_id="tenant-1", signal_date=signal_date)

    assert precomputed is not None
    assert precomputed["queue_items"] == transient["queue_items"]
    assert precomputed["goal_status"] == transient["goal_status"]
    assert precomputed["import_summary"] == transient["import_summary"]
    assert sorted(precomputed["home_sections"].keys()) == sorted(transient["home_sections"].keys())
    assert [card.insight_id for card in precomputed["home_sections"]["needs_attention"]] == [
        card.insight_id for card in transient["home_sections"]["needs_attention"]
    ]
    assert [item.employee_id for item in precomputed["attention_summary"].ranked_items] == [
        item.employee_id for item in transient["attention_summary"].ranked_items
    ]
    assert [item.attention_score for item in precomputed["attention_summary"].ranked_items] == [
        item.attention_score for item in transient["attention_summary"].ranked_items
    ]
    assert precomputed["attention_summary"].suppressed_count == transient["attention_summary"].suppressed_count
    assert precomputed["attention_summary"].total_evaluated == transient["attention_summary"].total_evaluated
    assert [item.employee_id for item in precomputed["decision_items"]] == [item.employee_id for item in transient["decision_items"]]
    assert [item.final_score for item in precomputed["decision_items"]] == [item.final_score for item in transient["decision_items"]]
    assert precomputed["decision_summary"].total_evaluated == transient["decision_summary"].total_evaluated


def test_read_precomputed_rebuilds_missing_decision_items(monkeypatch):
    signal_date = date(2026, 4, 13)
    attention_summary = {
        "ranked_items": [],
        "is_healthy": True,
        "healthy_message": "",
        "suppressed_count": 0,
        "total_evaluated": 1,
    }

    payload_row = {
        "payload": {
            "queue_items": [{"employee_id": "E1", "_queue_status": "overdue"}],
            "goal_status": [
                {
                    "EmployeeID": "E1",
                    "Department": "Packing",
                    "Average UPH": 40,
                    "Target UPH": 50,
                    "trend": "declining",
                    "goal_status": "below_goal",
                    "confidence_label": "high",
                    "repeat_count": 1,
                }
            ],
            "import_summary": {"days": 5, "trust": {"status": "valid", "confidence_score": 88}},
            "home_sections": {},
            "attention_summary": attention_summary,
            "decision_items": [],
        }
    }

    rebuilt_item = DecisionItem(
        employee_id="E1",
        process_name="Packing",
        final_score=91,
        final_tier="high",
        attention_score=79,
        action_score=12,
        action_priority="high",
        action_queue_status="overdue",
        primary_reason="Decline compared to recent baseline performance",
        confidence_label="High",
        confidence_basis="Based on 3 included day(s) with configured target context.",
        normalized_action_state="overdue_follow_up",
        normalized_action_state_detail="Overdue",
        attention_item=AttentionItem(
            employee_id="E1",
            process_name="Packing",
            attention_score=79,
            attention_tier="high",
            attention_reasons=["Decline compared to recent baseline performance"],
            attention_summary="E1 (Packing) - ranked highly.",
            factors_applied=[],
            snapshot={"employee_id": "E1", "Department": "Packing"},
        ),
        source_snapshot={"employee_id": "E1", "Department": "Packing"},
    )

    monkeypatch.setattr(dss, "list_daily_signals", lambda **kwargs: [payload_row])
    monkeypatch.setattr(dss, "list_open_operational_exceptions", lambda **kwargs: [])
    monkeypatch.setattr(dss, "build_decision_items", lambda **kwargs: [rebuilt_item])

    precomputed = dss.read_precomputed_today_signals(tenant_id="tenant-1", signal_date=signal_date)

    assert precomputed is not None
    assert [item.employee_id for item in precomputed["decision_items"]] == ["E1"]
    assert precomputed["decision_summary"].total_evaluated == 1
