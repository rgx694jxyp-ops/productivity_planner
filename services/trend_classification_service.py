"""Deterministic trend classification for trust-first operational views.

Rule order is explicit and intentionally simple:
1. insufficient_data: not enough comparable recent or prior days
2. inconsistent: recent day-to-day span is too wide for a steady label
3. declining: recent average is materially below the prior comparable average
4. improving: recent average is materially above the prior comparable average
5. below_expected: recent average is below expected pace without a stronger trend change
6. stable: none of the above

This service is descriptive only. It classifies what the data suggests and does not
recommend what a user should do.
"""

from __future__ import annotations

from typing import Any

from services.plain_language_service import describe_trend, explain_trend_state

TREND_STATE_STABLE = "stable"
TREND_STATE_BELOW_EXPECTED = "below_expected"
TREND_STATE_DECLINING = "declining"
TREND_STATE_IMPROVING = "improving"
TREND_STATE_INCONSISTENT = "inconsistent"
TREND_STATE_INSUFFICIENT = "insufficient_data"

TREND_STATES = {
    TREND_STATE_STABLE,
    TREND_STATE_BELOW_EXPECTED,
    TREND_STATE_DECLINING,
    TREND_STATE_IMPROVING,
    TREND_STATE_INCONSISTENT,
    TREND_STATE_INSUFFICIENT,
}

LEGACY_TREND_ALIASES = {
    "up": TREND_STATE_IMPROVING,
    "down": TREND_STATE_DECLINING,
    "flat": TREND_STATE_STABLE,
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_trend_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    if state in TREND_STATES:
        return state
    return LEGACY_TREND_ALIASES.get(state, TREND_STATE_INSUFFICIENT)


def classify_trend_state(
    *,
    recent_average_uph: float,
    prior_average_uph: float,
    expected_uph: float = 0.0,
    included_count: int = 0,
    recent_values: list[float] | None = None,
    min_recent_points: int = 2,
    min_prior_points: int = 2,
    min_absolute_change: float = 1.0,
    min_relative_change: float = 0.03,
    inconsistency_floor: float = 8.0,
    inconsistency_ratio: float = 0.12,
) -> dict[str, Any]:
    recent_average_uph = _safe_float(recent_average_uph)
    prior_average_uph = _safe_float(prior_average_uph)
    expected_uph = _safe_float(expected_uph)
    included_count = max(0, int(included_count or 0))
    recent_values = [float(value) for value in (recent_values or []) if _safe_float(value) > 0]

    delta_uph = round(recent_average_uph - prior_average_uph, 2) if recent_average_uph > 0 and prior_average_uph > 0 else 0.0
    change_threshold = max(min_absolute_change, abs(prior_average_uph) * min_relative_change) if prior_average_uph > 0 else min_absolute_change
    volatility_span = round(max(recent_values) - min(recent_values), 2) if len(recent_values) >= 2 else 0.0
    volatility_threshold = max(inconsistency_floor, recent_average_uph * inconsistency_ratio) if recent_average_uph > 0 else inconsistency_floor

    if recent_average_uph <= 0 or included_count < min_recent_points or prior_average_uph <= 0:
        state = TREND_STATE_INSUFFICIENT
        rule = "recent or prior comparison window is too small"
    elif len(recent_values) >= 4 and volatility_span >= volatility_threshold:
        state = TREND_STATE_INCONSISTENT
        rule = "recent day-to-day variation is too wide for a steady label"
    elif delta_uph <= -change_threshold:
        state = TREND_STATE_DECLINING
        rule = "recent average is materially below the prior comparable average"
    elif delta_uph >= change_threshold:
        state = TREND_STATE_IMPROVING
        rule = "recent average is materially above the prior comparable average"
    elif expected_uph > 0 and recent_average_uph < expected_uph:
        state = TREND_STATE_BELOW_EXPECTED
        rule = "recent average is under expected pace without a stronger directional change"
    else:
        state = TREND_STATE_STABLE
        rule = "recent average is close to the prior comparable average"

    return {
        "state": state,
        "label": describe_trend(state),
        "plain_explanation": explain_trend_state(state),
        "rule_applied": rule,
        "delta_uph": delta_uph,
        "change_threshold_uph": round(change_threshold, 2),
        "volatility_span_uph": volatility_span,
        "volatility_threshold_uph": round(volatility_threshold, 2),
        "recent_average_uph": recent_average_uph,
        "prior_average_uph": prior_average_uph,
        "expected_uph": expected_uph,
        "is_notable": state in {TREND_STATE_BELOW_EXPECTED, TREND_STATE_DECLINING, TREND_STATE_IMPROVING, TREND_STATE_INCONSISTENT},
    }
