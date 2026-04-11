"""Centralized plain-language formatting for user-facing operational copy."""

from __future__ import annotations


TREND_LABELS: dict[str, str] = {
    "stable": "holding steady",
    "below_expected": "below expected pace",
    "declining": "slipping from recent pace",
    "improving": "moving up from recent pace",
    "inconsistent": "moving around from day to day",
    "insufficient_data": "not enough recent history yet",
    "down": "slipping from recent pace",
    "up": "moving up from recent pace",
    "flat": "holding steady",
    "unknown": "trend not available",
}

TREND_EXPLANATIONS: dict[str, str] = {
    "stable": "Recent performance looks similar to the recent average.",
    "below_expected": "Recent performance is under the expected pace, but not changing enough to call it improving or declining.",
    "declining": "Recent performance is lower than the prior comparable window.",
    "improving": "Recent performance is higher than the prior comparable window.",
    "inconsistent": "Recent performance moves around enough that the pattern is not steady yet.",
    "insufficient_data": "There are not enough comparable days yet to classify the pattern confidently.",
    "down": "Recent performance is lower than the prior comparable window.",
    "up": "Recent performance is higher than the prior comparable window.",
    "flat": "Recent performance looks similar to the recent average.",
    "unknown": "Trend details are not available.",
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
        return "Needs attention soon"
    if "🟡" in level or "Medium" in level:
        return "Watch closely"
    if "🟢" in level or "Low" in level:
        return "Looks steady"
    return "Needs attention"
