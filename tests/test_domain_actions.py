from datetime import date

from domain.actions import (
    IssueType,
    can_transition_status,
    determine_priority,
    is_follow_up_due,
    is_overdue,
    repeat_issue_recommendation,
    runtime_status,
)


def test_is_overdue_and_runtime_status_derives_overdue():
    today = date(2026, 4, 7)

    assert is_overdue("in_progress", "2026-04-06", today=today) is True
    assert runtime_status("in_progress", "2026-04-06", today=today) == "overdue"


def test_follow_up_due_true_when_due_today():
    today = date(2026, 4, 7)

    assert is_follow_up_due("follow_up_due", "2026-04-07", today=today) is True
    assert runtime_status("follow_up_due", "2026-04-07", today=today) == "follow_up_due"


def test_repeat_issue_recommendation_rules():
    assert repeat_issue_recommendation(failed_cycles=3, still_below_goal=True) == "escalated"
    assert repeat_issue_recommendation(failed_cycles=2, still_below_goal=False) == "deprioritized"
    assert repeat_issue_recommendation(failed_cycles=1, still_below_goal=True) == "in_progress"


def test_priority_rules_cover_v1_issue_types():
    assert determine_priority(
        issue_type=IssueType.OVERDUE_UNRESOLVED,
        status="overdue",
        follow_up_due_at="2026-04-01",
        today=date(2026, 4, 7),
    ) == "high"

    assert determine_priority(
        issue_type=IssueType.HIGH_PERFORMER_IGNORED,
        status="new",
        follow_up_due_at="2026-04-20",
        today=date(2026, 4, 7),
    ) == "low"


def test_lifecycle_transition_guards():
    assert can_transition_status("new", "in_progress") is True
    assert can_transition_status("resolved", "in_progress") is True
    assert can_transition_status("resolved", "new") is False
