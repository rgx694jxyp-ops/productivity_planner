from services.trend_classification_service import classify_trend_state, normalize_trend_state


def test_classify_trend_state_returns_insufficient_data_first():
    result = classify_trend_state(
        recent_average_uph=82,
        prior_average_uph=0,
        expected_uph=95,
        included_count=1,
        recent_values=[82],
    )

    assert result["state"] == "insufficient_data"
    assert "too small" in result["rule_applied"]


def test_classify_trend_state_returns_inconsistent_before_directional_change():
    result = classify_trend_state(
        recent_average_uph=90,
        prior_average_uph=86,
        expected_uph=95,
        included_count=5,
        recent_values=[72, 101, 84, 98, 95],
    )

    assert result["state"] == "inconsistent"
    assert result["is_notable"] is True


def test_classify_trend_state_returns_declining_when_recent_average_drops():
    result = classify_trend_state(
        recent_average_uph=82,
        prior_average_uph=90,
        expected_uph=95,
        included_count=5,
        recent_values=[81, 82, 83, 82, 82],
    )

    assert result["state"] == "declining"
    assert result["label"] == "slipping from recent pace"


def test_classify_trend_state_returns_improving_when_recent_average_rises():
    result = classify_trend_state(
        recent_average_uph=94,
        prior_average_uph=86,
        expected_uph=95,
        included_count=5,
        recent_values=[93, 94, 95, 94, 94],
    )

    assert result["state"] == "improving"
    assert result["label"] == "moving up from recent pace"


def test_classify_trend_state_returns_below_expected_when_under_target_without_strong_direction():
    result = classify_trend_state(
        recent_average_uph=88,
        prior_average_uph=88.5,
        expected_uph=95,
        included_count=5,
        recent_values=[87, 88, 89, 88, 88],
    )

    assert result["state"] == "below_expected"
    assert result["label"] == "below expected pace"


def test_classify_trend_state_returns_stable_when_no_other_rule_applies():
    result = classify_trend_state(
        recent_average_uph=92,
        prior_average_uph=91.5,
        expected_uph=90,
        included_count=5,
        recent_values=[91, 92, 93, 92, 92],
    )

    assert result["state"] == "stable"
    assert result["label"] == "holding steady"


def test_normalize_trend_state_maps_legacy_values():
    assert normalize_trend_state("up") == "improving"
    assert normalize_trend_state("down") == "declining"
    assert normalize_trend_state("flat") == "stable"
