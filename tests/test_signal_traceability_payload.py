from datetime import datetime

from domain.insight_card_contract import (
    ConfidenceInfo,
    DataCompletenessNote,
    DrillDownTarget,
    InsightCardContract,
    SourceReference,
    TimeContext,
    TraceabilityContext,
    VolumeWorkloadContext,
)
from services.signal_traceability_service import traceability_payload_from_card
from tests.product_posture_assertions import assert_no_prescriptive_language


def _build_card(*, confidence_level: str = "high", included_rows: int | None = 6, sample_size: int | None = 6) -> InsightCardContract:
    return InsightCardContract(
        insight_id="card-1",
        insight_kind="trend_change",
        title="Lower than recent pace",
        what_happened="Lower than recent pace",
        compared_to_what="Compared with the latest 3-day window versus prior 3-day window",
        why_flagged="Below recent baseline vs comparable days.",
        confidence=ConfidenceInfo(
            level=confidence_level,
            score=0.55,
            basis="only part of the comparison window is available",
            sample_size=sample_size,
            minimum_expected_points=3,
            caveat="comparison depth is limited",
        ),
        workload_context=VolumeWorkloadContext(),
        time_context=TimeContext(
            observed_window_label="Latest snapshot",
            compared_window_label="Prior 3-day baseline",
            last_updated_at=datetime(2026, 4, 12, 9, 30),
        ),
        data_completeness=DataCompletenessNote(status="partial", summary="Partial trend history", excluded_rows=2),
        drill_down=DrillDownTarget(screen="employee_detail", label="View details", entity_id="E1"),
        traceability=TraceabilityContext(
            date_range_used="Latest snapshot",
            baseline_or_target_used="Prior 3-day baseline",
            linked_scope="employee",
            linked_entity_id="E1",
            included_rows=included_rows,
            excluded_rows=2,
            warnings=["partial trend history"],
            source_summary="daily performance upload",
        ),
        source_references=[SourceReference(source_type="upload", source_name="daily performance upload")],
        metadata={},
    )


def test_traceability_payload_includes_normalized_drilldown_fields():
    payload = traceability_payload_from_card(_build_card(confidence_level="low", included_rows=2, sample_size=2))

    assert payload["signal_summary"] == "Lower than recent pace"
    assert payload["surfaced_because"]
    assert payload["comparison_statement"].startswith("Compared with")
    assert payload["confidence_level"] == "low"
    assert payload["confidence_sample_size"] == 2
    assert payload["signal_maturity_label"] == "limited-data prompt"
    assert "fewer than 3 usable points" in payload["signal_maturity_reason"]
    assert payload["freshness_statement"].startswith("Latest snapshot")


def test_traceability_payload_marks_early_signal_when_low_confidence_without_low_count():
    payload = traceability_payload_from_card(_build_card(confidence_level="low", included_rows=5, sample_size=5))

    assert payload["signal_maturity_label"] == "early signal"


def test_traceability_payload_marks_stable_signal_when_confidence_and_evidence_are_sufficient():
    payload = traceability_payload_from_card(_build_card(confidence_level="high", included_rows=6, sample_size=6))

    assert payload["signal_maturity_label"] == "stable signal"


def test_traceability_payload_non_prescriptive_language_guard():
    payload = traceability_payload_from_card(_build_card(confidence_level="low", included_rows=2, sample_size=2))

    assert_no_prescriptive_language(
        [
            payload.get("signal_summary"),
            payload.get("surfaced_because"),
            payload.get("confidence_basis"),
            payload.get("confidence_caveat"),
            payload.get("comparison_statement"),
            payload.get("freshness_statement"),
            payload.get("signal_maturity_label"),
            payload.get("signal_maturity_reason"),
        ]
    )


def test_traceability_payload_exposes_process_and_shift_context_fields():
    card = _build_card(confidence_level="high", included_rows=6, sample_size=6)
    card.metadata.update({"process_name": "Receiving", "shift_name": "Night", "is_shift_level": True})

    payload = traceability_payload_from_card(card)

    assert payload["process_context_label"] == "Receiving"
    assert payload["shift_context_label"] == "Night"
    assert payload["is_shift_level"] is True
