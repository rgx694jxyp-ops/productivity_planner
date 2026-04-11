"""Tests for attention_scoring_service.

All tests are deterministic and do not touch the database.
"""

from services.attention_scoring_service import (
    AttentionSummary,
    score_attention_items,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snapshot(
    employee_id: str = "EMP001",
    process_name: str = "Picking",
    trend_state: str = "stable",
    confidence_label: str = "medium",
    data_completeness_status: str = "partial",
    repeat_count: int = 0,
    expected_uph: float = 100.0,
    recent_average_uph: float = 100.0,
) -> dict:
    return {
        "employee_id": employee_id,
        "process_name": process_name,
        "trend_state": trend_state,
        "confidence_label": confidence_label,
        "data_completeness_status": data_completeness_status,
        "repeat_count": repeat_count,
        "expected_uph": expected_uph,
        "recent_average_uph": recent_average_uph,
    }


def _goal_status_row(
    employee_id: str = "EMP001",
    department: str = "Picking",
    trend: str = "stable",
    confidence_label: str = "medium",
    repeat_count: int = 0,
    target_uph: float = 100.0,
    average_uph: float = 100.0,
) -> dict:
    return {
        "EmployeeID": employee_id,
        "Department": department,
        "trend": trend,
        "confidence_label": confidence_label,
        "repeat_count": repeat_count,
        "Target UPH": target_uph,
        "Average UPH": average_uph,
    }


# ---------------------------------------------------------------------------
# Base score neutrality
# ---------------------------------------------------------------------------

def test_stable_medium_confidence_partial_no_extras_is_low_tier():
    """Base (50) + partial completeness (−5) = 45 → below medium floor → low tier."""
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="stable", confidence_label="medium", data_completeness_status="partial")],
    )
    assert len(result.ranked_items) == 1
    item = result.ranked_items[0]
    assert item.attention_tier == "low"
    assert item.attention_score == 45


# ---------------------------------------------------------------------------
# Trend factors
# ---------------------------------------------------------------------------

def test_declining_trend_raises_score_to_high():
    """Base(50) + declining(+25) + medium-conf(0) + partial(−5) = 70 → medium.
    Add high confidence (+10) → 80 → high."""
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="declining", confidence_label="high", data_completeness_status="partial")],
    )
    item = result.ranked_items[0]
    assert item.attention_tier == "high"
    factor_keys = {f.key for f in item.factors_applied}
    assert "trend_declining" in factor_keys
    assert "confidence_high" in factor_keys


def test_below_expected_trend_is_medium():
    """Base(50) + below_expected(+15) + medium(0) + partial(−5) = 60 → medium."""
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="below_expected", confidence_label="medium", data_completeness_status="partial")],
    )
    item = result.ranked_items[0]
    assert item.attention_tier == "medium"
    assert item.attention_score == 60


def test_inconsistent_trend_contributes_points():
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="inconsistent", confidence_label="medium", data_completeness_status="partial")],
    )
    item = result.ranked_items[0]
    assert "trend_inconsistent" in {f.key for f in item.factors_applied}
    assert item.attention_score > 50


def test_improving_trend_adds_soft_points():
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="improving", confidence_label="medium", data_completeness_status="partial")],
    )
    item = result.ranked_items[0]
    # improving trend should add +5 but is not suppressed
    assert "trend_improving" in {f.key for f in item.factors_applied}


# ---------------------------------------------------------------------------
# Confidence down-ranking
# ---------------------------------------------------------------------------

def test_low_confidence_reduces_score():
    low_conf = score_attention_items(
        snapshots=[_snapshot(trend_state="declining", confidence_label="low", data_completeness_status="limited")],
    )
    high_conf = score_attention_items(
        snapshots=[_snapshot(trend_state="declining", confidence_label="high", data_completeness_status="complete")],
    )
    assert low_conf.ranked_items[0].attention_score < high_conf.ranked_items[0].attention_score


def test_suppressed_item_excluded_from_ranked_list_by_default():
    """Low confidence + limited completeness + no signals → score < 30 (suppressed)."""
    result = score_attention_items(
        snapshots=[
            _snapshot(
                trend_state="stable",
                confidence_label="low",
                data_completeness_status="limited",
                expected_uph=0.0,
                recent_average_uph=0.0,
            )
        ],
    )
    assert result.suppressed_count >= 1
    assert all(item.attention_tier != "suppressed" for item in result.ranked_items)


def test_keep_low_includes_suppressed_items():
    result = score_attention_items(
        snapshots=[
            _snapshot(
                trend_state="stable",
                confidence_label="low",
                data_completeness_status="limited",
                expected_uph=0.0,
                recent_average_uph=0.0,
            )
        ],
        keep_low=True,
    )
    assert len(result.ranked_items) >= 1
    assert any(item.attention_tier == "suppressed" for item in result.ranked_items)


# ---------------------------------------------------------------------------
# Repeat pattern factor
# ---------------------------------------------------------------------------

def test_repeat_count_3_adds_high_bonus():
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="below_expected", confidence_label="high", data_completeness_status="complete", repeat_count=3)],
    )
    item = result.ranked_items[0]
    assert "repeat_3_or_more" in {f.key for f in item.factors_applied}
    assert item.attention_tier == "high"


def test_repeat_count_2_adds_moderate_bonus():
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="stable", confidence_label="high", data_completeness_status="complete", repeat_count=2)],
    )
    item = result.ranked_items[0]
    assert "repeat_2" in {f.key for f in item.factors_applied}


# ---------------------------------------------------------------------------
# Queue status factors
# ---------------------------------------------------------------------------

def test_overdue_followup_raises_score():
    queue = [{"employee_id": "EMP001", "_queue_status": "overdue"}]
    result = score_attention_items(
        snapshots=[_snapshot(employee_id="EMP001", trend_state="stable", confidence_label="medium", data_completeness_status="partial")],
        queue_items=queue,
    )
    item = result.ranked_items[0]
    factor_keys = {f.key for f in item.factors_applied}
    assert "overdue_followup" in factor_keys


def test_due_today_not_added_when_also_overdue():
    """An employee in both overdue and due-today should only get overdue credit."""
    queue = [
        {"employee_id": "EMP001", "_queue_status": "overdue"},
        {"employee_id": "EMP001", "_queue_status": "due_today"},
    ]
    result = score_attention_items(
        snapshots=[_snapshot(employee_id="EMP001")],
        queue_items=queue,
    )
    factor_keys = {f.key for f in result.ranked_items[0].factors_applied}
    assert "overdue_followup" in factor_keys
    assert "due_today_followup" not in factor_keys


# ---------------------------------------------------------------------------
# Open exception factor
# ---------------------------------------------------------------------------

def test_open_exception_adds_points():
    exceptions = [{"employee_id": "EMP001"}]
    result = score_attention_items(
        snapshots=[_snapshot(employee_id="EMP001", trend_state="stable", confidence_label="medium", data_completeness_status="partial")],
        open_exception_rows=exceptions,
    )
    factor_keys = {f.key for f in result.ranked_items[0].factors_applied}
    assert "open_exception" in factor_keys


# ---------------------------------------------------------------------------
# Variance factor
# ---------------------------------------------------------------------------

def test_variance_over_20pct_adds_points():
    result = score_attention_items(
        snapshots=[_snapshot(expected_uph=100.0, recent_average_uph=75.0, trend_state="stable",
                             confidence_label="medium", data_completeness_status="partial")],
    )
    factor_keys = {f.key for f in result.ranked_items[0].factors_applied}
    assert "variance_over_20pct" in factor_keys


def test_variance_under_10pct_no_variance_factor():
    result = score_attention_items(
        snapshots=[_snapshot(expected_uph=100.0, recent_average_uph=96.0, trend_state="stable",
                             confidence_label="medium", data_completeness_status="partial")],
    )
    factor_keys = {f.key for f in result.ranked_items[0].factors_applied}
    assert "variance_over_20pct" not in factor_keys
    assert "variance_10_to_20pct" not in factor_keys


# ---------------------------------------------------------------------------
# Goal-status row format (key variant acceptance)
# ---------------------------------------------------------------------------

def test_accepts_goal_status_format_rows():
    """Rows using EmployeeID / Average UPH / Target UPH / trend should score."""
    row = _goal_status_row(
        employee_id="EMP042",
        trend="declining",
        confidence_label="medium",
        repeat_count=2,
        target_uph=90.0,
        average_uph=70.0,
    )
    result = score_attention_items(snapshots=[row])
    assert len(result.ranked_items) == 1
    item = result.ranked_items[0]
    assert item.employee_id == "EMP042"
    factor_keys = {f.key for f in item.factors_applied}
    assert "trend_declining" in factor_keys
    assert "repeat_2" in factor_keys
    assert "variance_over_20pct" in factor_keys


# ---------------------------------------------------------------------------
# Ranking and ordering
# ---------------------------------------------------------------------------

def test_higher_score_ranks_first():
    snapshots = [
        _snapshot("EMP001", trend_state="stable", confidence_label="medium", data_completeness_status="partial"),
        _snapshot("EMP002", trend_state="declining", confidence_label="high", data_completeness_status="complete", repeat_count=3),
    ]
    result = score_attention_items(snapshots=snapshots)
    assert result.ranked_items[0].employee_id == "EMP002"


def test_tie_breaks_by_employee_id():
    """Two identical snapshots must break ties by employee_id alphabetically."""
    snapshots = [
        _snapshot("EMPZ", trend_state="declining", confidence_label="medium", data_completeness_status="partial"),
        _snapshot("EMPA", trend_state="declining", confidence_label="medium", data_completeness_status="partial"),
    ]
    result = score_attention_items(snapshots=snapshots)
    assert result.ranked_items[0].employee_id == "EMPA"


def test_max_items_caps_output():
    snapshots = [_snapshot(f"EMP{i:03d}", trend_state="declining") for i in range(20)]
    result = score_attention_items(snapshots=snapshots, max_items=5)
    assert len(result.ranked_items) <= 5


# ---------------------------------------------------------------------------
# Healthy state
# ---------------------------------------------------------------------------

def test_healthy_state_when_all_items_suppressed():
    """All suppressed items → is_healthy=True and healthy_message is set."""
    result = score_attention_items(
        snapshots=[
            _snapshot(
                trend_state="stable",
                confidence_label="low",
                data_completeness_status="limited",
                expected_uph=0.0,
                recent_average_uph=0.0,
            )
        ],
    )
    assert result.is_healthy is True
    assert result.healthy_message != ""


def test_not_healthy_when_high_tier_item_present():
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="declining", confidence_label="high", data_completeness_status="complete", repeat_count=3)],
    )
    assert result.is_healthy is False
    assert result.healthy_message == ""


def test_empty_snapshots_is_healthy():
    result = score_attention_items(snapshots=[])
    assert result.is_healthy is True
    assert result.total_evaluated == 0


# ---------------------------------------------------------------------------
# Explanation content
# ---------------------------------------------------------------------------

def test_attention_reasons_are_non_empty_for_notable_items():
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="declining", confidence_label="high", data_completeness_status="complete")],
    )
    item = result.ranked_items[0]
    assert len(item.attention_reasons) > 0
    assert item.attention_summary != ""


def test_attention_summary_not_prescriptive():
    """Summary text must not contain directive verbs that prescribe action."""
    prescriptive_words = {"coach", "talk to", "address", "fix", "improve", "must", "should"}
    result = score_attention_items(
        snapshots=[_snapshot(trend_state="declining", confidence_label="high", data_completeness_status="complete", repeat_count=3)],
    )
    for item in result.ranked_items:
        summary_lower = item.attention_summary.lower()
        for word in prescriptive_words:
            assert word not in summary_lower, f"Prescriptive word '{word}' found in summary: {item.attention_summary}"
