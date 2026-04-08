"""Action domain definitions and lifecycle rules.

Pure domain logic only. No UI, database, or framework dependencies.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Issue types — what the problem IS (the trigger / diagnosis)
class IssueType:
    LOW_PERFORMANCE_UNADDRESSED = "low_performance_unaddressed"
    FOLLOW_UP_DUE               = "follow_up_due"
    REPEAT_NO_IMPROVEMENT       = "repeat_no_improvement"
    HIGH_PERFORMER_IGNORED      = "high_performer_ignored"
    OVERDUE_UNRESOLVED          = "overdue_unresolved"

ISSUE_TYPES: list[str] = [
    IssueType.LOW_PERFORMANCE_UNADDRESSED,
    IssueType.FOLLOW_UP_DUE,
    IssueType.REPEAT_NO_IMPROVEMENT,
    IssueType.HIGH_PERFORMER_IGNORED,
    IssueType.OVERDUE_UNRESOLVED,
]

# Action types — what you DO about the issue (the intervention)
ACTION_TYPES: list[str] = [
    "coaching_followup",
    "process_retraining",
    "workstation_check",
    "escalate",
    "development_touchpoint",
]

STATUSES: list[str] = [
    "new",
    "in_progress",
    "follow_up_due",
    "overdue",
    "escalated",
    "resolved",
    "deprioritized",
]

OPEN_STATUSES: set[str] = {"new", "in_progress", "follow_up_due", "overdue", "escalated"}
TERMINAL_STATUSES: set[str] = {"resolved", "deprioritized"}

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "new": {"in_progress", "follow_up_due", "escalated", "deprioritized", "resolved"},
    "in_progress": {"follow_up_due", "escalated", "deprioritized", "resolved"},
    "follow_up_due": {"in_progress", "escalated", "deprioritized", "resolved"},
    "overdue": {"in_progress", "escalated", "deprioritized", "resolved"},
    "escalated": {"in_progress", "resolved", "deprioritized"},
    "resolved": {"in_progress"},  # reopened flow
    "deprioritized": {"in_progress"},  # reopened flow
}

OUTCOME_OPTIONS: list[str] = [
    "improved",
    "no_change",
    "worse",
    "blocked",
]

NO_IMPROVEMENT_OUTCOMES: set[str] = {"no_change", "worse", "blocked"}

TRIGGER_SOURCES: list[str] = [
    "today",
    "manual",
]

PRIORITIES: list[str] = ["high", "medium", "low"]

# Urgency scores used by action_service to sort the queue
URGENCY_OVERDUE: int = 100
URGENCY_DUE_TODAY: int = 90
URGENCY_ESCALATED: int = 85
URGENCY_IN_PROGRESS: int = 70
URGENCY_GENERATED_BASE: int = 80

DB_TABLE: str = "actions"
DB_EVENTS_TABLE: str = "action_events"

# Event types — things that happen TO an action over its lifetime
class EventType:
    CREATED          = "created"
    COACHED          = "coached"
    FOLLOW_UP_LOGGED = "follow_up_logged"
    RECOGNIZED       = "recognized"
    ESCALATED        = "escalated"
    RESOLVED         = "resolved"
    DEPRIORITIZED    = "deprioritized"
    REOPENED         = "reopened"

EVENT_TYPES: list[str] = [
    EventType.CREATED,
    EventType.COACHED,
    EventType.FOLLOW_UP_LOGGED,
    EventType.RECOGNIZED,
    EventType.ESCALATED,
    EventType.RESOLVED,
    EventType.DEPRIORITIZED,
    EventType.REOPENED,
]

# Event-level outcome values (distinct from resolution_type on the parent action)
class EventOutcome:
    IMPROVED        = "improved"
    NO_CHANGE       = "no_change"
    WORSE           = "worse"
    PENDING         = "pending"
    NOT_APPLICABLE  = "not_applicable"

EVENT_OUTCOMES: list[str] = [
    EventOutcome.IMPROVED,
    EventOutcome.NO_CHANGE,
    EventOutcome.WORSE,
    EventOutcome.PENDING,
    EventOutcome.NOT_APPLICABLE,
]


def parse_action_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        try:
            return date.fromisoformat(text[:10])
        except Exception:
            return None


def normalize_status(status: str, *, default: str = "new") -> str:
    normalized = str(status or "").strip().lower()
    return normalized if normalized in STATUSES else default


def can_transition_status(current_status: str, next_status: str) -> bool:
    current = normalize_status(current_status)
    nxt = normalize_status(next_status)
    return nxt in STATUS_TRANSITIONS.get(current, set())


def is_overdue(status: str, follow_up_due_at: Any, *, today: date | None = None) -> bool:
    today = today or date.today()
    normalized = normalize_status(status)
    if normalized not in OPEN_STATUSES:
        return False
    due = parse_action_date(follow_up_due_at)
    return bool(due and due < today)


def is_follow_up_due(status: str, follow_up_due_at: Any, *, today: date | None = None) -> bool:
    today = today or date.today()
    normalized = normalize_status(status)
    if normalized not in OPEN_STATUSES:
        return False
    due = parse_action_date(follow_up_due_at)
    return bool(due and due <= today)


def runtime_status(status: str, follow_up_due_at: Any, *, today: date | None = None) -> str:
    """Return normalized runtime status, deriving overdue when due date has passed."""
    normalized = normalize_status(status)
    if normalized in TERMINAL_STATUSES:
        return normalized
    if is_overdue(normalized, follow_up_due_at, today=today):
        return "overdue"
    return normalized


def repeat_issue_recommendation(*, failed_cycles: int, still_below_goal: bool) -> str:
    """Return suggested status for repeat no-improvement cases.

    Rules:
    - >=3 failed cycles while still below goal: escalate
    - >=2 failed cycles and no longer below goal: deprioritize
    - otherwise: continue in progress
    """
    if failed_cycles >= 3 and still_below_goal:
        return "escalated"
    if failed_cycles >= 2 and not still_below_goal:
        return "deprioritized"
    return "in_progress"


def determine_priority(
    *,
    issue_type: str,
    status: str,
    failed_cycles: int = 0,
    follow_up_due_at: Any = None,
    today: date | None = None,
) -> str:
    """Return `high|medium|low` using v1 priority rules."""
    normalized_status = runtime_status(status, follow_up_due_at, today=today)
    issue = str(issue_type or "").strip().lower()

    if normalized_status in {"escalated", "overdue"}:
        return "high"
    if issue == IssueType.REPEAT_NO_IMPROVEMENT and failed_cycles >= 2:
        return "high"
    if issue == IssueType.LOW_PERFORMANCE_UNADDRESSED:
        return "high" if failed_cycles >= 2 else "medium"
    if issue == IssueType.FOLLOW_UP_DUE:
        return "medium"
    if issue == IssueType.HIGH_PERFORMER_IGNORED:
        return "low"
    return "medium"


def urgency_score(*, status: str, due_date: Any, issue_type: str = "", failed_cycles: int = 0, today: date | None = None) -> int:
    """Queue sort score that keeps urgency behavior centralized in domain logic."""
    today = today or date.today()
    normalized = runtime_status(status, due_date, today=today)
    if normalized == "overdue":
        due = parse_action_date(due_date) or today
        return URGENCY_OVERDUE + max((today - due).days, 0)
    if normalized == "follow_up_due":
        return URGENCY_DUE_TODAY
    if normalized == "escalated":
        return URGENCY_ESCALATED
    base = URGENCY_IN_PROGRESS
    if issue_type == IssueType.LOW_PERFORMANCE_UNADDRESSED:
        base = URGENCY_GENERATED_BASE + max(failed_cycles, 0)
    return base


def status_label(status: str, follow_up_due_at: Any, *, today: date | None = None) -> str:
    normalized = runtime_status(status, follow_up_due_at, today=today)
    if normalized == "overdue":
        return "Overdue"
    if normalized == "follow_up_due":
        return "Due Today"
    return normalized.replace("_", " ").title()
