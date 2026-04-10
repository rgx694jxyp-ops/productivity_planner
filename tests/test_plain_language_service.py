from services.plain_language_service import (
    action_code_from_recommendation,
    action_label,
    describe_change_pct,
    describe_goal_status,
    describe_trend,
    outcome_code,
    outcome_label,
)


def test_describe_change_pct_uses_manager_friendly_phrasing():
    assert "below expected pace" in describe_change_pct(-23.0)
    assert "above expected pace" in describe_change_pct(15.0)
    assert "near expected pace" in describe_change_pct(0.5)


def test_trend_and_status_labels_are_plain_language():
    assert describe_trend("down") == "below expected pace"
    assert describe_trend("insufficient_data") == "not enough history yet"
    assert describe_goal_status("below_goal") == "below expected pace"


def test_outcome_label_roundtrip():
    label = outcome_label("no_change")
    assert label == "No clear change"
    assert outcome_code(label) == "no_change"


def test_action_label_mapping_from_recommendation():
    code = action_code_from_recommendation("escalate")
    assert code == "mark_for_review"
    assert action_label(code) == "Mark for review"
