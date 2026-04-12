from services.plain_language_service import (
    SIGNAL_WORDING_MAP,
    action_code_from_recommendation,
    action_label,
    describe_change_pct,
    describe_goal_status,
    describe_trend,
    outcome_code,
    outcome_label,
    signal_wording,
    signal_wording_from_trend,
)


def test_describe_change_pct_uses_manager_friendly_phrasing():
    assert "below expected pace" in describe_change_pct(-23.0)
    assert "above expected pace" in describe_change_pct(15.0)
    assert "near expected pace" in describe_change_pct(0.5)


def test_trend_and_status_labels_are_plain_language():
    # "down" is a legacy alias for DECLINING.
    assert describe_trend("down") == "Lower than recent pace"
    assert describe_trend("insufficient_data") == "Not enough history yet"
    assert describe_goal_status("below_goal") == "below expected pace"


def test_outcome_label_roundtrip():
    label = outcome_label("no_change")
    assert label == "No clear change"
    assert outcome_code(label) == "no_change"


def test_action_label_mapping_from_recommendation():
    code = action_code_from_recommendation("escalate")
    assert code == "mark_for_review"
    assert action_label(code) == "Mark for review"


def test_canonical_signal_wording_map_contains_required_phrases():
    assert SIGNAL_WORDING_MAP["lower_than_recent_pace"] == "Lower than recent pace"
    assert SIGNAL_WORDING_MAP["below_expected_pace"] == "Below expected pace"
    assert SIGNAL_WORDING_MAP["inconsistent_performance"] == "Inconsistent performance"
    assert SIGNAL_WORDING_MAP["follow_up_not_completed"] == "Follow-up not completed"
    assert SIGNAL_WORDING_MAP["not_enough_history_yet"] == "Not enough history yet"


def test_signal_wording_accessors_use_canonical_values():
    assert signal_wording("lower_than_recent_pace") == "Lower than recent pace"
    assert signal_wording("below_expected_pace") == "Below expected pace"
    assert signal_wording("inconsistent_performance") == "Inconsistent performance"
    assert signal_wording("follow_up_not_completed") == "Follow-up not completed"
    assert signal_wording("not_enough_history_yet") == "Not enough history yet"
    assert signal_wording_from_trend("inconsistent") == "Inconsistent performance"
    assert signal_wording_from_trend("declining") == "Lower than recent pace"
