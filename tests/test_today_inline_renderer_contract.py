from datetime import datetime, date

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
from services.today_view_model_service import build_today_queue_card_from_insight_card
from tests.product_posture_assertions import assert_no_prescriptive_language


def _insight_card(*, confidence_level: str = "high", sample_size: int = 4, included_rows: int = 4) -> InsightCardContract:
    return InsightCardContract(
        insight_id="inline-1",
        insight_kind="trend_change",
        title="Lower than recent pace",
        what_happened="Lower than recent pace",
        compared_to_what="Compared with the latest 3-day window versus prior 3-day window",
        why_flagged="Below recent baseline vs comparable days.",
        confidence=ConfidenceInfo(
            level=confidence_level,
            score=0.6,
            basis="comparison window coverage is partial",
            sample_size=sample_size,
            minimum_expected_points=3,
            caveat="evidence depth can improve with additional records",
        ),
        workload_context=VolumeWorkloadContext(
            impacted_group_label="Receiving",
            observed_volume=31.2,
            observed_volume_unit="UPH",
            baseline_volume=40.0,
            baseline_volume_unit="UPH",
        ),
        time_context=TimeContext(
            observed_window_label="Latest snapshot",
            compared_window_start=datetime(2026, 4, 9, 0, 0),
            compared_window_end=datetime(2026, 4, 11, 0, 0),
            compared_window_label="Prior 3-day baseline",
            last_updated_at=datetime(2026, 4, 12, 9, 30),
            window_start=datetime(2026, 4, 10, 0, 0),
            window_end=datetime(2026, 4, 12, 0, 0),
        ),
        data_completeness=DataCompletenessNote(status="partial", summary="Partial history", excluded_rows=1),
        drill_down=DrillDownTarget(screen="employee_detail", label="View details", entity_id="E-1"),
        traceability=TraceabilityContext(
            date_range_used="Latest snapshot",
            baseline_or_target_used="Prior 3-day baseline",
            linked_scope="employee",
            linked_entity_id="E-1",
            included_rows=included_rows,
            excluded_rows=1,
            source_summary="daily upload",
        ),
        source_references=[SourceReference(source_type="upload", source_name="daily upload")],
        metadata={},
    )


def test_inline_adapter_uses_normalized_today_contract(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.is_display_signal_eligible",
        lambda signal, allow_low_data_case=False, min_confidence_for_full_or_partial="medium": True,
    )
    card = build_today_queue_card_from_insight_card(card=_insight_card(confidence_level="high", sample_size=4, included_rows=4), today=date(2026, 4, 12))

    assert card is not None
    assert " · " in card.line_1
    assert card.line_2
    assert card.line_3
    assert card.line_5.lower().startswith("confidence") or card.line_5.lower() == "low confidence"
    assert str(card.freshness_line or "").startswith("Freshness:")
    assert card.line_4.startswith("Based on") or card.line_4 == "Latest snapshot only"

    assert_no_prescriptive_language(
        [
            card.line_1,
            card.line_2,
            card.line_3,
            card.line_4,
            card.line_5,
            card.freshness_line,
            *list(card.expanded_lines or []),
        ]
    )


def test_inline_adapter_low_data_keeps_non_stable_wording(monkeypatch):
    monkeypatch.setattr(
        "services.today_view_model_service.is_display_signal_eligible",
        lambda signal, allow_low_data_case=False, min_confidence_for_full_or_partial="medium": True,
    )
    card = build_today_queue_card_from_insight_card(card=_insight_card(confidence_level="low", sample_size=2, included_rows=2), today=date(2026, 4, 12))

    assert card is not None
    assert card.line_3
    assert card.line_4 in {"Latest snapshot only", "Based on 2 recent records", "Based on 2 usable records"}
    assert "stable" not in str(card.line_3 or "").lower()
