from datetime import date

from services.signal_pattern_memory_service import (
    detect_pattern_memory_from_action,
    detect_pattern_memory_from_goal_row,
)


def test_detect_pattern_memory_from_action_repeated_decline():
    action = {
        "issue_type": "repeat_no_improvement",
        "baseline_uph": 52,
        "latest_uph": 46,
        "_is_repeat_issue": True,
        "_repeat_signals": ["coached 3x", "2x no improvement"],
        "last_event_at": "2026-04-07T15:00:00Z",
    }

    result = detect_pattern_memory_from_action(action=action, today=date(2026, 4, 9))

    assert result.pattern_detected is True
    assert result.pattern_kind == "repeated_decline"
    assert result.repeat_count >= 2


def test_detect_pattern_memory_from_action_ignores_stale_context():
    action = {
        "issue_type": "repeat_no_improvement",
        "_is_repeat_issue": True,
        "_repeat_signals": ["coached 4x"],
        "last_event_at": "2026-01-01T10:00:00Z",
    }

    result = detect_pattern_memory_from_action(action=action, today=date(2026, 4, 9), max_recent_days=30)

    assert result.pattern_detected is False
    assert result.recent_window_days > 30


def test_detect_pattern_memory_from_goal_row_uses_recent_histories():
    row = {
        "trend": "down",
        "change_pct": -9.0,
        "recent_trend_history": ["down", "down", "flat"],
        "recent_goal_status_history": ["below_goal", "below_goal", "on_goal"],
    }

    result = detect_pattern_memory_from_goal_row(row=row)

    assert result.pattern_detected is True
    assert result.pattern_kind == "repeated_decline"
    assert result.repeat_count == 2
