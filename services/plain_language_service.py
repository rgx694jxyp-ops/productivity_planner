"""Centralized plain-language formatting for user-facing operational copy."""

from __future__ import annotations


SIGNAL_WORDING_MAP: dict[str, str] = {
    "lower_than_recent_pace": "Lower than recent pace",
    "below_expected_pace": "Below expected pace",
    "inconsistent_performance": "Inconsistent performance",
    "follow_up_not_completed": "Follow-up not completed",
    "not_enough_history_yet": "Not enough history yet",
}


def signal_wording(key: str) -> str:
    normalized = str(key or "").strip().lower()
    return SIGNAL_WORDING_MAP.get(normalized, SIGNAL_WORDING_MAP["not_enough_history_yet"])


def signal_wording_from_trend(trend: str) -> str:
    normalized = str(trend or "").strip().lower()
    trend_map = {
        "below_expected": "below_expected_pace",
        "declining": "lower_than_recent_pace",
        "down": "lower_than_recent_pace",
        "inconsistent": "inconsistent_performance",
        "insufficient_data": "not_enough_history_yet",
    }
    return signal_wording(trend_map.get(normalized, "not_enough_history_yet"))


TREND_LABELS: dict[str, str] = {
    "stable": "Worth review",
    "below_expected": signal_wording("below_expected_pace"),
    "declining": signal_wording("lower_than_recent_pace"),
    "improving": "Higher than recent pace",
    "inconsistent": signal_wording("inconsistent_performance"),
    "insufficient_data": signal_wording("not_enough_history_yet"),
    "down": signal_wording("lower_than_recent_pace"),
    "up": "Higher than recent pace",
    "flat": "Worth review",
    "unknown": "Worth review",
}

TREND_EXPLANATIONS: dict[str, str] = {
    "stable": "Recently surfaced with no large change.",
    "below_expected": "Recently surfaced below expected pace.",
    "declining": "Recently surfaced lower than the prior window.",
    "improving": "Recently surfaced higher than the prior window.",
    "inconsistent": "Recently surfaced with uneven day-to-day results.",
    "insufficient_data": "Not enough recent history yet.",
    "down": "Recently surfaced lower than the prior window.",
    "up": "Recently surfaced higher than the prior window.",
    "flat": "Recently surfaced with no large change.",
    "unknown": "Recently surfaced.",
}

GOAL_STATUS_LABELS: dict[str, str] = {
    "below_goal": "below expected pace",
    "on_goal": "meeting expected pace",
    "unknown": "status not available",
}

OUTCOME_LABELS: dict[str, str] = {
    "improved": "Improved",
    "no_change": "No clear change",
    "worse": "Declined",
    "blocked": "Blocked by context",
    "not_applicable": "Not applicable",
}

PRIMARY_ACTION_LABELS: dict[str, str] = {
    "log_check_in": "Log check-in",
    "log_follow_up": "Log follow-up",
    "log_recognition": "Log recognition",
    "mark_for_review": "Mark for review",
    "lower_urgency": "Lower urgency",
}

RECOMMENDATION_TO_ACTION_CODE: dict[str, str] = {
    "coach today": "log_check_in",
    "follow up": "log_follow_up",
    "follow up now": "log_follow_up",
    "recognize": "log_recognition",
    "escalate": "mark_for_review",
    "deprioritize": "lower_urgency",
    "continue": "log_follow_up",
}


def describe_trend(trend: str) -> str:
    return TREND_LABELS.get(str(trend or "").strip().lower(), TREND_LABELS["unknown"])


def explain_trend_state(trend: str) -> str:
    return TREND_EXPLANATIONS.get(str(trend or "").strip().lower(), TREND_EXPLANATIONS["unknown"])


def describe_goal_status(status: str) -> str:
    return GOAL_STATUS_LABELS.get(str(status or "").strip().lower(), GOAL_STATUS_LABELS["unknown"])


def describe_change_pct(change_pct: float) -> str:
    if change_pct <= -10:
        return f"below expected pace ({change_pct:.1f}%)"
    if change_pct < -2:
        return f"slightly below expected pace ({change_pct:.1f}%)"
    if change_pct >= 10:
        return f"above expected pace (+{change_pct:.1f}%)"
    if change_pct > 2:
        return f"slightly above expected pace (+{change_pct:.1f}%)"
    sign = "+" if change_pct > 0 else ""
    return f"near expected pace ({sign}{change_pct:.1f}%)"


def outcome_label(code: str) -> str:
    normalized = str(code or "").strip().lower()
    return OUTCOME_LABELS.get(normalized, normalized.replace("_", " ").title() or "Not specified")


def outcome_code(label: str) -> str:
    text = str(label or "").strip()
    normalized_label_map = {v.lower(): k for k, v in OUTCOME_LABELS.items()}
    if text.lower() in normalized_label_map:
        return normalized_label_map[text.lower()]
    normalized = text.lower().replace(" ", "_")
    return normalized if normalized in OUTCOME_LABELS else "not_applicable"


def action_code_from_recommendation(recommendation: str) -> str:
    normalized = str(recommendation or "").strip().lower()
    return RECOMMENDATION_TO_ACTION_CODE.get(normalized, "log_follow_up")


def action_label(action_code: str) -> str:
    normalized = str(action_code or "").strip().lower()
    return PRIMARY_ACTION_LABELS.get(normalized, "Log follow-up")


def describe_attention_level(risk_level: str) -> str:
    level = str(risk_level or "")
    if "🔴" in level or "High" in level:
        return "Worth review"
    if "🟡" in level or "Medium" in level:
        return "Recently surfaced"
    if "🟢" in level or "Low" in level:
        return "Worth review"
    return "Recently surfaced"
