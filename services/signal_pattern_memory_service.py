"""Deterministic pattern-memory helpers for interpreted operational signals.

Pattern memory intentionally stays lightweight:
- only uses explicit recent fields already present in payloads
- avoids forecasting
- returns explainable pattern evidence
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re


@dataclass(frozen=True)
class PatternMemoryResult:
    pattern_detected: bool
    pattern_kind: str = "none"  # none | repeated_decline | recurring_issue | similar_pattern
    repeat_count: int = 0
    recent_window_days: int = 0
    summary: str = ""
    evidence_points: list[str] | None = None


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value: object) -> date | None:
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


def _count_matching(values: list[object], *, expected: str) -> int:
    expected_norm = str(expected or "").strip().lower()
    return sum(1 for value in (values or []) if str(value or "").strip().lower() == expected_norm)


def _extract_repeat_count_from_signals(signals: list[str]) -> int:
    repeat_count = 0
    for signal in signals or []:
        matches = re.findall(r"(\d+)\s*[x×]", str(signal or ""))
        for match in matches:
            try:
                repeat_count = max(repeat_count, int(match))
            except Exception:
                continue
    return repeat_count


def detect_pattern_memory_from_action(
    *,
    action: dict,
    today: date,
    max_recent_days: int = 45,
) -> PatternMemoryResult:
    signals = [str(s) for s in (action.get("_repeat_signals") or []) if str(s).strip()]
    issue_type = str(action.get("issue_type") or "").strip().lower()
    is_repeat_issue = bool(action.get("_is_repeat_issue"))
    baseline = _safe_float(action.get("baseline_uph"), 0.0)
    latest = _safe_float(action.get("latest_uph"), 0.0)

    reference_date = _parse_date(action.get("last_event_at") or action.get("created_at") or action.get("follow_up_due_at"))
    if reference_date is None:
        recent_window_days = 0
    else:
        recent_window_days = max(0, (today - reference_date).days)

    # Keep memory bounded to recent historical context.
    if recent_window_days > max_recent_days:
        return PatternMemoryResult(
            pattern_detected=False,
            repeat_count=0,
            recent_window_days=recent_window_days,
            summary="Pattern memory not surfaced because supporting context is outside the recent window.",
            evidence_points=["recent-window-exceeded"],
        )

    repeat_count = _extract_repeat_count_from_signals(signals)
    if repeat_count <= 0 and is_repeat_issue:
        repeat_count = 2

    if "repeat_no_improvement" in issue_type:
        repeat_count = max(repeat_count, 2)

    if baseline > 0 and latest > 0 and latest < baseline and repeat_count >= 2:
        return PatternMemoryResult(
            pattern_detected=True,
            pattern_kind="repeated_decline",
            repeat_count=repeat_count,
            recent_window_days=recent_window_days,
            summary=f"Repeated decline observed in recent follow-up context ({repeat_count} related cycle(s)).",
            evidence_points=signals or [f"baseline={baseline:.1f}", f"latest={latest:.1f}"],
        )

    if repeat_count >= 2:
        return PatternMemoryResult(
            pattern_detected=True,
            pattern_kind="recurring_issue",
            repeat_count=repeat_count,
            recent_window_days=recent_window_days,
            summary=f"Recurring issue observed in recent context ({repeat_count} similar occurrence(s)).",
            evidence_points=signals,
        )

    if signals:
        return PatternMemoryResult(
            pattern_detected=True,
            pattern_kind="similar_pattern",
            repeat_count=max(1, repeat_count),
            recent_window_days=recent_window_days,
            summary="A similar pattern has been observed recently.",
            evidence_points=signals,
        )

    return PatternMemoryResult(
        pattern_detected=False,
        recent_window_days=recent_window_days,
        summary="No recent repeated pattern detected.",
        evidence_points=[],
    )


def detect_pattern_memory_from_goal_row(
    *,
    row: dict,
    max_recent_points: int = 6,
) -> PatternMemoryResult:
    trend = str(row.get("trend") or "").strip().lower()
    change_pct = _safe_float(row.get("change_pct"), 0.0)
    recent_trend_history = list(row.get("recent_trend_history") or [])[:max_recent_points]
    recent_goal_history = list(row.get("recent_goal_status_history") or [])[:max_recent_points]

    down_count = _count_matching(recent_trend_history, expected="down")
    below_goal_count = _count_matching(recent_goal_history, expected="below_goal")
    repeat_count = max(down_count, below_goal_count)

    if trend == "down" and change_pct <= -5 and repeat_count >= 2:
        return PatternMemoryResult(
            pattern_detected=True,
            pattern_kind="repeated_decline",
            repeat_count=repeat_count,
            recent_window_days=0,
            summary=f"Repeated decline observed across recent trend points ({repeat_count} down classifications).",
            evidence_points=[
                f"trend={trend}",
                f"change_pct={change_pct:.1f}",
                f"recent_down_count={down_count}",
            ],
        )

    if repeat_count >= 2:
        return PatternMemoryResult(
            pattern_detected=True,
            pattern_kind="similar_pattern",
            repeat_count=repeat_count,
            summary=f"Similar pattern observed in recent goal/trend context ({repeat_count} matching points).",
            evidence_points=[
                f"recent_down_count={down_count}",
                f"recent_below_goal_count={below_goal_count}",
            ],
        )

    return PatternMemoryResult(
        pattern_detected=False,
        repeat_count=repeat_count,
        summary="No repeated pattern detected in recent trend context.",
        evidence_points=[],
    )
