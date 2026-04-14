from services.attention_scoring_service import AttentionFactor, AttentionItem
from services.decision_engine_service import DecisionItem
from services.decision_surfacing_policy_service import (
    BUCKET_FOLLOW_THROUGH_SOON,
    BUCKET_NEEDS_ATTENTION_NOW,
    BUCKET_WATCHLIST,
    build_decision_surfacing_policy,
)


def _decision(
    employee_id: str,
    *,
    final_score: int,
    reason: str,
    confidence: str = "High",
    queue_status: str = "",
    normalized_action_state: str = "",
    repeat_count: int = 0,
    trend_key: str = "",
    completeness: str = "complete",
    tier: str = "high",
) -> DecisionItem:
    factors = [
        AttentionFactor(key=trend_key, weight=20, plain_reason=reason)
    ] if trend_key else []
    attention = AttentionItem(
        employee_id=employee_id,
        process_name="Receiving",
        attention_score=max(0, final_score - 10),
        attention_tier=tier,
        attention_reasons=[reason],
        attention_summary=reason,
        factors_applied=factors,
        snapshot={
            "employee_id": employee_id,
            "Department": "Receiving",
            "repeat_count": repeat_count,
            "data_completeness_status": completeness,
        },
    )
    return DecisionItem(
        employee_id=employee_id,
        process_name="Receiving",
        final_score=final_score,
        final_tier=tier,
        attention_score=max(0, final_score - 10),
        action_score=10,
        action_priority="high" if queue_status else "",
        action_queue_status=queue_status,
        primary_reason=reason,
        confidence_label=confidence,
        confidence_basis="Policy test basis",
        normalized_action_state=normalized_action_state,
        normalized_action_state_detail="",
        attention_item=attention,
        source_snapshot={
            "repeat_count": repeat_count,
            "data_completeness_status": completeness,
            "employee_id": employee_id,
            "Department": "Receiving",
        },
    )


def test_limited_data_action_heavy_keeps_overdue_primary_and_low_conf_secondary():
    overdue_low_conf = _decision(
        "E1",
        final_score=82,
        reason="Has an overdue follow-up",
        confidence="Low",
        queue_status="overdue",
        normalized_action_state="In Progress",
        completeness="limited",
        tier="low",
    )
    queue_only_low_conf = _decision(
        "E2",
        final_score=48,
        reason="Open follow-up without enough support",
        confidence="Low",
        queue_status="pending",
        normalized_action_state="In Progress",
        completeness="limited",
        tier="low",
    )

    policy = build_decision_surfacing_policy([overdue_low_conf, queue_only_low_conf], primary_cap=8)

    assert "E1" in policy.primary_employee_ids
    assert "E2" in policy.secondary_employee_ids
    assert policy.bucket_by_employee_id["E1"] == BUCKET_NEEDS_ATTENTION_NOW


def test_broad_dataset_primary_cap_limits_primary_volume():
    items = [
        _decision(
            f"E{i:02d}",
            final_score=120 - i,
            reason="Decline compared to recent baseline performance",
            confidence="High",
            trend_key="trend_declining",
            completeness="complete",
        )
        for i in range(1, 13)
    ]

    policy = build_decision_surfacing_policy(items, primary_cap=5)

    assert len(policy.primary_employee_ids) == 5
    assert len(policy.secondary_employee_ids) == 7
    assert policy.primary_employee_ids[0] == "E01"
    assert policy.reason_by_employee_id["E06"] == "Urgent signal retained in secondary due to primary cap"


def test_improving_but_overdue_is_still_primary():
    improving_overdue = _decision(
        "E3",
        final_score=88,
        reason="Performance is improving",
        confidence="High",
        queue_status="overdue",
        normalized_action_state="Follow-up Scheduled",
        completeness="partial",
    )

    policy = build_decision_surfacing_policy([improving_overdue], primary_cap=8)

    assert policy.bucket_by_employee_id["E3"] == BUCKET_NEEDS_ATTENTION_NOW
    assert "E3" in policy.primary_employee_ids


def test_low_confidence_queue_only_moves_to_watchlist_bucket():
    low_conf_info = _decision(
        "E4",
        final_score=34,
        reason="Output is 27% from expected pace",
        confidence="Low",
        queue_status="",
        normalized_action_state="",
        completeness="limited",
        tier="low",
    )

    policy = build_decision_surfacing_policy([low_conf_info], primary_cap=8)

    assert policy.bucket_by_employee_id["E4"] == BUCKET_WATCHLIST
    assert "E4" in policy.secondary_employee_ids
    assert "E4" not in policy.primary_employee_ids


def test_due_today_with_open_state_goes_follow_through_soon():
    due_today = _decision(
        "E5",
        final_score=70,
        reason="Follow-up due in current snapshot",
        confidence="Medium",
        queue_status="due_today",
        normalized_action_state="Follow-up Scheduled",
        completeness="partial",
    )

    policy = build_decision_surfacing_policy([due_today], primary_cap=8)

    assert policy.bucket_by_employee_id["E5"] == BUCKET_FOLLOW_THROUGH_SOON
    assert "E5" in policy.secondary_employee_ids


def test_mixed_confidence_overdue_ranks_high_confidence_before_low_confidence():
    overdue_low_conf = _decision(
        "E6",
        final_score=98,
        reason="Overdue follow-up with limited support",
        confidence="Low",
        queue_status="overdue",
        normalized_action_state="Overdue",
        completeness="limited",
        tier="low",
    )
    overdue_high_conf = _decision(
        "E7",
        final_score=85,
        reason="Overdue follow-up with strong support",
        confidence="High",
        queue_status="overdue",
        normalized_action_state="Overdue",
        completeness="complete",
        tier="high",
    )

    policy = build_decision_surfacing_policy([overdue_low_conf, overdue_high_conf], primary_cap=8)

    assert policy.primary_employee_ids[:2] == ("E7", "E6")


def test_overdue_bucket_classification_unchanged_for_mixed_confidence():
    overdue_low_conf = _decision(
        "E8",
        final_score=62,
        reason="Overdue follow-up with limited support",
        confidence="Low",
        queue_status="overdue",
        normalized_action_state="In Progress",
        completeness="limited",
        tier="low",
    )
    overdue_high_conf = _decision(
        "E9",
        final_score=74,
        reason="Overdue follow-up with strong support",
        confidence="High",
        queue_status="overdue",
        normalized_action_state="In Progress",
        completeness="complete",
        tier="high",
    )

    policy = build_decision_surfacing_policy([overdue_low_conf, overdue_high_conf], primary_cap=8)

    assert policy.bucket_by_employee_id["E8"] == BUCKET_NEEDS_ATTENTION_NOW
    assert policy.bucket_by_employee_id["E9"] == BUCKET_NEEDS_ATTENTION_NOW