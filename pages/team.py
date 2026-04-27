"""Team page.

Informational drill-down surface with no operational action controls.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from statistics import median

import pandas as pd
import streamlit as st

from core.dependencies import _cached_coaching_notes_for, require_db
from services.action_query_service import get_employee_action_timeline
from services.daily_snapshot_service import get_employee_snapshot_history, get_latest_snapshot_goal_status
from services.exception_tracking_service import build_exception_context_line, list_recent_operational_exceptions
from services.perf_profile import profile_block
from services.team_page_language_service import (
    format_bridge_helper,
    format_comparison_context_brief,
    format_comparison_section_title,
    format_comparison_text,
    format_confidence_meta,
    format_current_vs_target,
    format_data_completeness_meta,
    format_empty_state,
    format_exception_context_line,
    format_exception_expand_label,
    format_exception_text,
    format_follow_up_roster_overdue,
    format_follow_up_roster_pending,
    format_follow_up_roster_pending_no_date,
    format_follow_up_roster_recent,
    format_follow_up_summary_overdue,
    format_follow_up_summary_pending,
    format_follow_up_summary_pending_no_date,
    format_follow_up_summary_recent,
    format_follow_up_unavailable,
    clean_note_text_for_display,
    format_note_entry,
    format_note_expand_label,
    format_page_hero_caption,
    format_roster_count,
    format_roster_helper_text,
    format_roster_reason_below_baseline,
    format_roster_reason_change_down,
    format_roster_reason_change_up,
    format_roster_reason_improving,
    format_roster_reason_stable,
    format_roster_reason_variable,
    format_selected_employee_subheader,
    format_selected_summary,
    format_show_older_exceptions_label,
    format_show_older_notes_label,
    format_status_filter_option,
    format_timeline_description_fallback,
    format_timeline_entry,
    format_timeline_event_display,
    format_timeline_when,
    format_trend_intro,
    format_trend_interpretation_above_target_and_improving,
    format_trend_interpretation_above_target_declining,
    format_trend_interpretation_below_target,
    format_trend_interpretation_declining,
    format_trend_interpretation_improving,
    format_trend_interpretation_improving_but_below_target,
    format_trend_interpretation_limited_days,
    format_trend_interpretation_near_or_above_target,
    format_trend_interpretation_no_days,
    format_trend_interpretation_recent_dip,
    format_trend_interpretation_stable,
    format_trend_label,
    format_trend_no_history,
    format_trend_no_points,
    format_what_changed_line,
    get_team_filter_labels,
    get_team_section_titles,
    format_bridge_button_label,
    format_chip_current_vs_target,
    format_chip_follow_up,
    format_chip_notes,
    format_chip_trend,
    format_note_preview_text,
    format_timeline_row_heading,
    format_exception_preview_text,
    format_primary_statement,
    format_secondary_context_subline,
    format_sustained_context_line,
)


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _narrative_weight(event_type: str) -> int:
    """Return narrative sort weight (signal → action → follow-up → completion)."""
    base = str(event_type or "").strip()
    if base == "Performance concern identified":
        return 0
    if base == "Note added":
        return 1
    if base == "Follow-up scheduled":
        return 2
    if base == "Reviewed and logged":
        return 3
    return 4


_ALLOWED_TIMELINE_EVENT_TYPES = {
    "Performance concern identified",
    "Note added",
    "Follow-up scheduled",
    "Reviewed and logged",
}

_TODAY_TO_TEAM_HANDOFF_KEY = "_today_to_team_handoff"
_TEAM_TO_TODAY_FOCUS_KEY = "_team_to_today_focus"


def _clean_plain_handoff_reason(text: str) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    lower = clean.lower()
    blocked = (
        "signal_key=",
        "signal_id=",
        "employee_id=",
        "tenant_id=",
        "debug",
        "internal",
        "{",
        "[",
    )
    if any(token in lower for token in blocked):
        return ""
    return clean[:160]


def _canonical_timeline_event_type(*, raw_event_type: str, status: str, title: str, source: str) -> str:
    raw = str(raw_event_type or "").strip().lower()
    status_raw = str(status or "").strip().lower()
    title_clean = str(title or "").strip()
    source_clean = str(source or "").strip().lower()

    if raw in {"resolved"} or status_raw in {"done", "resolved", "completed"} or title_clean.startswith("Issue marked"):
        return "Reviewed and logged"
    if raw in {"follow_up_logged", "follow_through_logged"} or title_clean.startswith("Follow-up scheduled"):
        return "Follow-up scheduled"
    if raw in {"exception_opened"} or title_clean.startswith("Issue logged"):
        return "Performance concern identified"
    if raw in {"coached", "recognized"} or source_clean == "note" or title_clean.startswith("Added note"):
        return "Note added"
    return ""


def _is_internal_timeline_text(text: str) -> bool:
    clean = " ".join(str(text or "").strip().split())
    if not clean:
        return False
    lower = clean.lower()
    if lower in {"bad"}:
        return True
    if clean.startswith("{") or clean.startswith("["):
        return True
    return any(
        marker in lower
        for marker in (
            "reason=",
            "signal_key=",
            "scope=",
            "signal_status=",
            "follow_up_required=",
            "tenant_id=",
            "employee_id=",
            "action_id=",
            "internal",
            "debug",
        )
    )


def _clean_timeline_description(text: str) -> str:
    clean = clean_note_text_for_display(text)
    if not clean:
        return ""
    clean = " ".join(clean.split())
    if _is_internal_timeline_text(clean):
        return ""
    return clean


def _format_display_dt(when_text: str) -> str:
    """Convert ISO datetime string to human-readable: 'Apr 27 at 9:00 AM'."""
    clean = str(when_text or "").strip()
    if not clean:
        return clean
    dt = _parse_dt(clean)
    if dt is None:
        return clean[:16]
    month_day = f"{dt.strftime('%b')} {dt.day}"
    if dt.hour == 0 and dt.minute == 0:
        return month_day
    hour = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{month_day} at {hour}:{minute} {ampm}"


def _parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.fromisoformat(text[:19])
        except Exception:
            return None


def _employee_display_name(row: dict) -> str:
    name = str(row.get("Employee Name") or row.get("Employee") or "Unknown").strip() or "Unknown"
    emp_id = str(row.get("EmployeeID") or row.get("emp_id") or "").strip()
    return f"{name} ({emp_id})" if emp_id else name


def _employee_id(row: dict) -> str:
    return str(row.get("EmployeeID") or row.get("emp_id") or "").strip()


def _team_status_bucket(row: dict) -> str:
    trend_raw = str(row.get("trend") or "").strip().lower()
    goal_raw = str(row.get("goal_status") or "").strip().lower()
    combined = f"{trend_raw} {goal_raw}"

    if any(token in combined for token in ["improv", "recover", "better", "upward"]):
        return "improved recently"
    if any(token in combined for token in ["attention", "risk", "behind", "below", "declin", "regress", "off track"]):
        return "needs attention"
    return "stable"


def _compact_text(value: object, max_len: int = 88) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1].rstrip()}…"


def _roster_reason_text(row: dict) -> str:
    trend_explanation = _compact_text(row.get("trend_explanation"), max_len=96)
    if trend_explanation:
        return trend_explanation

    change_pct = _safe_float(row.get("change_pct"))
    if change_pct is not None and abs(change_pct) >= 1:
        if change_pct < 0:
            return format_roster_reason_change_down(change_pct)
        return format_roster_reason_change_up(change_pct)

    trend = str(row.get("trend") or "").strip().lower()
    if trend in {"inconsistent", "variable"}:
        return format_roster_reason_variable()
    if trend in {"improving", "up"}:
        return format_roster_reason_improving()
    if trend in {"declining", "below_expected", "down"}:
        return format_roster_reason_below_baseline()
    return format_roster_reason_stable()


def _snapshot_follow_up_context(row: dict, *, today: datetime | None = None) -> dict[str, str] | None:
    today_dt = today or datetime.utcnow()
    due_raw = str(
        row.get("follow_up_due_at")
        or row.get("next_follow_up_at")
        or row.get("follow_up_due")
        or ""
    ).strip()
    due_dt = _parse_dt(due_raw)

    if due_dt is not None:
        due_date = due_dt.date()
        day_delta = (due_date - today_dt.date()).days
        due_text = due_date.isoformat()
        if day_delta < 0:
            return {
                "summary": format_follow_up_summary_overdue(due_text),
                "roster": format_follow_up_roster_overdue(due_text),
            }
        return {
            "summary": format_follow_up_summary_pending(due_text),
            "roster": format_follow_up_roster_pending(due_text),
        }

    due_flag = str(row.get("follow_up_due") or "").strip().lower()
    if due_flag in {"true", "yes", "1", "y", "pending", "due"}:
        return {
            "summary": format_follow_up_summary_pending_no_date(),
            "roster": format_follow_up_roster_pending_no_date(),
        }

    recent_raw = str(
        row.get("last_follow_up_at")
        or row.get("last_followup_at")
        or row.get("last_note_at")
        or row.get("last_coached_at")
        or row.get("latest_note_at")
        or ""
    ).strip()
    recent_dt = _parse_dt(recent_raw)
    if recent_dt is not None:
        recent_date = recent_dt.date()
        day_delta = (today_dt.date() - recent_date).days
        if 0 <= day_delta <= 14:
            recent_text = recent_date.isoformat()
            return {
                "summary": format_follow_up_summary_recent(recent_text),
                "roster": format_follow_up_roster_recent(recent_text),
            }

    return None


def _roster_meta_text(row: dict) -> str:
    follow_up_context = _snapshot_follow_up_context(row)
    if follow_up_context:
        return str(follow_up_context.get("roster") or "").strip()

    confidence = str(row.get("confidence_label") or "").strip().lower()
    completeness = str(row.get("data_completeness_status") or "").strip().lower()
    if confidence:
        return format_confidence_meta(confidence)
    if completeness:
        return format_data_completeness_meta(completeness)
    return ""


def _roster_row_label(summary: dict) -> str:
    name = str(summary.get("name") or "Unknown")
    department = str(summary.get("department") or "Unknown")
    trend_label = str(summary.get("trend_label") or "Holding steady")
    reason = _compact_text(summary.get("reason") or "No clear recent shift", max_len=56)
    meta = str(summary.get("meta") or "")
    top_line = name
    bottom_parts = [department, trend_label]
    if meta:
        bottom_parts.append(meta)
    elif reason:
        bottom_parts.append(reason)
    return f"{top_line}\n{' · '.join([part for part in bottom_parts if part])}"


def _current_vs_target_text(avg_uph: float | None, target_uph: float | None) -> str:
    return format_current_vs_target(avg_uph, target_uph)


def _trend_direction_from_slope(slope: float, *, epsilon: float = 1e-6) -> str:
    if slope > epsilon:
        return "positive"
    if slope < -epsilon:
        return "negative"
    return "flat"


def _trend_direction_from_change_pct(change_pct: float | None, *, epsilon: float = 1e-6) -> str | None:
    if change_pct is None:
        return None
    if change_pct > epsilon:
        return "positive"
    if change_pct < -epsilon:
        return "negative"
    return "flat"


def _trend_label_from_direction(direction: str) -> str:
    if direction == "negative":
        return "Declining"
    if direction == "positive":
        return "Improving"
    return "Holding steady"


def _compute_window_trend_metrics(chart_rows: list[dict]) -> dict[str, object]:
    """Compute trend direction from slope and percent change from same chart window."""
    ordered = sorted(chart_rows or [], key=lambda row: str(row.get("Date") or ""))
    if not ordered:
        return {
            "slope": 0.0,
            "slope_direction": "flat",
            "change_pct": None,
            "change_direction": None,
            "label": None,
        }

    y_values: list[float] = []
    for row in ordered:
        uph = _safe_float(row.get("UPH"))
        if uph is None:
            continue
        y_values.append(uph)

    if not y_values:
        return {
            "slope": 0.0,
            "slope_direction": "flat",
            "change_pct": None,
            "change_direction": None,
            "label": None,
        }

    n = len(y_values)
    slope = 0.0
    if n >= 2:
        x_values = list(range(n))
        sum_x = float(sum(x_values))
        sum_y = float(sum(y_values))
        sum_xy = float(sum(x * y for x, y in zip(x_values, y_values)))
        sum_xx = float(sum(x * x for x in x_values))
        denominator = (n * sum_xx) - (sum_x * sum_x)
        if denominator != 0:
            slope = ((n * sum_xy) - (sum_x * sum_y)) / denominator

    first_uph = y_values[0]
    last_uph = y_values[-1]
    change_pct = None
    if first_uph > 0:
        change_pct = ((last_uph - first_uph) / first_uph) * 100.0

    slope_direction = _trend_direction_from_slope(slope)
    change_direction = _trend_direction_from_change_pct(change_pct)

    label: str | None = None
    if change_direction is not None and change_direction == slope_direction:
        label = _trend_label_from_direction(slope_direction)

    return {
        "slope": slope,
        "slope_direction": slope_direction,
        "change_pct": change_pct,
        "change_direction": change_direction,
        "label": label,
    }


def _format_window_trend_summary(metrics: dict[str, object], days: int) -> str:
    """Build trend summary line with mismatch fail-safe (percent-only when needed)."""
    safe_days = max(1, int(days or 1))
    change_pct = _safe_float(metrics.get("change_pct"))
    label = str(metrics.get("label") or "").strip()

    if change_pct is None:
        return f"Not enough data to calculate change over the last {safe_days} days"

    pct_text = f"{change_pct:+.1f}% over the last {safe_days} days"
    if label:
        return f"{label} ({pct_text})"
    return pct_text


def _format_month_day(dt: datetime, *, include_time: bool = False) -> str:
    month_day = f"{dt.strftime('%b')} {dt.day}"
    if not include_time or (dt.hour == 0 and dt.minute == 0):
        return month_day
    hour = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{month_day} at {hour}:{minute} {ampm}"


def _build_follow_up_status_lines(*, row: dict, notes: list[dict], action_rows: list[dict]) -> list[str]:
    due_raw = str(
        row.get("follow_up_due_at")
        or row.get("next_follow_up_at")
        or row.get("follow_up_due")
        or ""
    ).strip()
    due_dt = _parse_dt(due_raw)

    lines: list[str] = []
    if due_dt is not None:
        lines.append(f"Follow-up scheduled for {_format_month_day(due_dt, include_time=True)}")
    else:
        due_flag = str(row.get("follow_up_due") or "").strip().lower()
        if due_flag in {"true", "yes", "1", "y", "pending", "due"}:
            lines.append("Follow-up scheduled")
        else:
            lines.append("No follow-up scheduled")

    latest_review: datetime | None = None
    review_candidates: list[datetime] = []

    row_review_dt = _parse_dt(
        str(
            row.get("last_follow_up_at")
            or row.get("last_followup_at")
            or row.get("last_note_at")
            or row.get("last_coached_at")
            or ""
        ).strip()
    )
    if row_review_dt is not None:
        review_candidates.append(row_review_dt)

    for note in notes or []:
        note_dt = _parse_dt(str(note.get("created_at") or note.get("date") or "").strip())
        if note_dt is not None:
            review_candidates.append(note_dt)

    for ev in action_rows or []:
        event_dt = _parse_dt(str(ev.get("event_at") or "").strip())
        if event_dt is not None:
            review_candidates.append(event_dt)

    if review_candidates:
        latest_review = max(review_candidates)

    if latest_review is not None:
        lines.append(f"Last reviewed {_format_month_day(latest_review)}")

    # Add a concise last-check result from recent follow-up outcome first,
    # then fall back to the most recent human-readable note.
    last_check_text = ""

    sorted_actions = sorted(
        list(action_rows or []),
        key=lambda ev: (_parse_dt(str(ev.get("event_at") or "").strip()) or datetime.min),
        reverse=True,
    )
    for event in sorted_actions:
        event_type = str(event.get("event_type") or "").strip().lower()
        if event_type not in {"follow_up_logged", "follow_through_logged", "resolved"}:
            continue
        for candidate in (
            str(event.get("outcome") or "").strip(),
            str(event.get("result") or "").strip(),
            str(event.get("notes") or "").strip(),
        ):
            clean_candidate = clean_note_text_for_display(candidate)
            if clean_candidate:
                last_check_text = clean_candidate
                break
        if last_check_text:
            break

    if not last_check_text:
        sorted_notes = sorted(
            list(notes or []),
            key=lambda note: (_parse_dt(str(note.get("created_at") or note.get("date") or "").strip()) or datetime.min),
            reverse=True,
        )
        for note in sorted_notes:
            note_text = _note_text(note)
            if note_text:
                last_check_text = note_text
                break

    if last_check_text:
        compact_last_check = " ".join(last_check_text.split())
        if len(compact_last_check) > 88:
            compact_last_check = f"{compact_last_check[:87].rstrip()}..."
        lines.append(f"Last check: {compact_last_check}")

    return lines


def _build_current_situation_lines(*, trend_metrics: dict[str, object], days: int, target_uph: float | None, chart_rows: list[dict]) -> list[str]:
    safe_days = max(1, int(days or 1))
    label = str(trend_metrics.get("label") or "").strip()
    change_pct = _safe_float(trend_metrics.get("change_pct"))

    lines: list[str] = []
    if label:
        lines.append(f"{label} performance over {safe_days} days")
    elif change_pct is not None:
        lines.append(f"{change_pct:+.1f}% change over {safe_days} days")
    else:
        lines.append(f"Not enough data over {safe_days} days")

    if target_uph is not None and target_uph > 0 and chart_rows:
        values = [float(row.get("UPH") or 0.0) for row in chart_rows if _safe_float(row.get("UPH")) is not None]
        observed_days = len(values)
        below_count = sum(1 for value in values if value < target_uph)
        if observed_days > 0:
            if below_count > (observed_days / 2):
                lines.append("Below target on most days")
            elif below_count > 0:
                lines.append(f"Below target on {below_count} of {observed_days} days")
            else:
                lines.append("At or above target on all observed days")

    return lines


def _build_why_happening_lines(*, chart_rows: list[dict], target_uph: float | None, exception_history: list[dict], note_history: list[dict]) -> list[str]:
    lines: list[str] = []
    values = [float(row.get("UPH") or 0.0) for row in chart_rows if _safe_float(row.get("UPH")) is not None]

    if values:
        low = min(values)
        high = max(values)
        if high > low:
            lines.append(f"Daily output ranged from {low:.1f} to {high:.1f} UPH")
        if target_uph is not None and target_uph > 0:
            below_count = sum(1 for value in values if value < target_uph)
            if below_count > 0:
                lines.append(f"{below_count} of {len(values)} observed days were below target")

    if exception_history:
        lines.append(f"{len(exception_history)} recent exception event(s) were recorded")

    if note_history:
        lines.append(f"{len(note_history)} review note(s) were logged")

    return lines[:3]


def _open_follow_up_state_text(row: dict) -> str:
    follow_up_context = _snapshot_follow_up_context(row)
    if follow_up_context:
        return str(follow_up_context.get("summary") or "").strip()
    return format_follow_up_unavailable()


def _follow_up_subline(row: dict, *, today: datetime | None = None) -> str:
    """Compact follow-up timing for summary sub-line. E.g. 'Follow-up due May 4'."""
    today_dt = today or datetime.utcnow()
    due_raw = str(
        row.get("follow_up_due_at")
        or row.get("next_follow_up_at")
        or row.get("follow_up_due")
        or ""
    ).strip()
    due_dt = _parse_dt(due_raw)
    if due_dt is not None:
        day_delta = (due_dt.date() - today_dt.date()).days
        month_day = f"{due_dt.strftime('%b')} {due_dt.day}"
        if day_delta < 0:
            return "Follow-up overdue"
        return f"Follow-up due {month_day}"
    due_flag = str(row.get("follow_up_due") or "").strip().lower()
    if due_flag in {"true", "yes", "1", "y", "pending", "due"}:
        return "Follow-up pending"
    return ""


def _what_changed_line(
    row: dict,
    *,
    change_pct: float | None,
    status_bucket: str,
    time_window_days: int,
    avg_uph: float | None,
    target_uph: float | None,
) -> str:
    """Plain-language sentence explaining what changed for the selected employee."""
    trend = str(row.get("trend") or "").strip().lower()
    return format_what_changed_line(
        change_pct=change_pct,
        status_bucket=status_bucket,
        observed_days=time_window_days,
        avg_uph=avg_uph,
        target_uph=target_uph,
        trend=trend,
    )


def _selected_employee_summary_sentence(
    *,
    status_bucket: str,
    change_pct: float | None,
    avg_uph: float | None,
    target_uph: float | None,
) -> str:
    return format_selected_summary(
        status_bucket=status_bucket,
        change_pct=change_pct,
        avg_uph=avg_uph,
        target_uph=target_uph,
    )


def _primary_summary_line(summary_sentence: str) -> str:
    text = " ".join(str(summary_sentence or "").split()).strip()
    if not text:
        return ""
    first_period = text.find(".")
    if first_period == -1:
        return text
    return text[: first_period + 1].strip()


def _compact_support_line(*parts: str) -> str:
    values = [" ".join(str(part or "").split()).strip() for part in parts]
    compact_values = [value for value in values if value]
    return " | ".join(compact_values)


def _trend_interpretation_sentence(chart_rows: list[dict], target_uph: float | None) -> str:
    observed_days = len(chart_rows)
    if observed_days == 0:
        return format_trend_interpretation_no_days()
    if observed_days < 3:
        return format_trend_interpretation_limited_days(observed_days)

    uph_values = [float(row.get("UPH") or 0.0) for row in chart_rows]
    first_uph = uph_values[0]
    last_uph = uph_values[-1]
    change_pct = ((last_uph - first_uph) / first_uph * 100.0) if first_uph > 0 else 0.0

    if target_uph is not None and target_uph > 0:
        below_count = sum(1 for uph in uph_values if uph < target_uph)
        if below_count > 0:
            if change_pct >= 3.0 and last_uph < target_uph:
                return format_trend_interpretation_improving_but_below_target(
                    below_count=below_count,
                    observed_days=observed_days,
                    change_pct=change_pct,
                )
            if observed_days >= 5:
                prior_values = uph_values[:-2]
                recent_values = uph_values[-2:]
                if prior_values and (sum(recent_values) / len(recent_values)) < (sum(prior_values) / len(prior_values)):
                    return format_trend_interpretation_recent_dip()
            return format_trend_interpretation_below_target(
                below_count=below_count,
                observed_days=observed_days,
                change_pct=change_pct,
            )
        if change_pct >= 3.0:
            return format_trend_interpretation_above_target_and_improving(change_pct=change_pct)
        if change_pct <= -3.0:
            return format_trend_interpretation_above_target_declining(change_pct=change_pct)
        return format_trend_interpretation_near_or_above_target()

    if change_pct >= 3.0:
        return format_trend_interpretation_improving(change_pct=change_pct)
    if change_pct <= -3.0:
        return format_trend_interpretation_declining(change_pct=change_pct)
    return format_trend_interpretation_stable()


def _timeline_when_text(dt: datetime | None, fallback: str = "") -> str:
    return format_timeline_when(dt, fallback=fallback)


def _normalize_recent_activity_timeline(
    *,
    notes: list[dict],
    action_rows: list[dict],
    exception_rows: list[dict],
    limit: int = 5,
) -> list[dict]:
    events: list[dict] = []

    for row in notes or []:
        event_at_raw = str(row.get("created_at") or row.get("date") or "").strip()
        event_at = _parse_dt(event_at_raw)
        if event_at is None:
            continue
        note_text = str(row.get("note") or row.get("notes") or "").strip()
        clean_note = _clean_timeline_description(note_text)
        if not clean_note:
            continue
        entry = format_timeline_event_display({
            "event_type": "coached",
            "notes": note_text,
        })
        canonical_type = _canonical_timeline_event_type(
            raw_event_type="coached",
            status="",
            title=entry["title"],
            source="note",
        )
        if canonical_type not in _ALLOWED_TIMELINE_EVENT_TYPES:
            continue
        events.append(
            {
                "event_at": event_at,
                "event_at_raw": event_at_raw,
                "event_type": canonical_type,
                "description": clean_note,
                "source": "note",
                "dedupe_key": f"{canonical_type}|{event_at.isoformat()}",
            }
        )

    for row in action_rows or []:
        event_at_raw = str(row.get("event_at") or "").strip()
        event_at = _parse_dt(event_at_raw)
        if event_at is None:
            continue
        raw_event_type = str(row.get("event_type") or "").strip().lower()
        raw_status = str(row.get("status") or "").strip().lower()
        entry = format_timeline_event_display({
            "event_type": raw_event_type,
            "status": raw_status,
            "action_id": str(row.get("action_id") or "").strip(),
            "notes": str(row.get("notes") or "").strip(),
            "outcome": str(row.get("outcome") or "").strip(),
            "next_follow_up_at": str(row.get("next_follow_up_at") or "").strip(),
        })
        canonical_type = _canonical_timeline_event_type(
            raw_event_type=raw_event_type,
            status=raw_status,
            title=entry["title"],
            source="action_event",
        )
        if canonical_type not in _ALLOWED_TIMELINE_EVENT_TYPES:
            continue
        description = _clean_timeline_description(str(entry.get("description") or ""))
        if canonical_type == "Note added" and not description:
            continue
        events.append(
            {
                "event_at": event_at,
                "event_at_raw": event_at_raw,
                "event_type": canonical_type,
                "description": description,
                "source": "action_event",
                "dedupe_key": f"{canonical_type}|{event_at.isoformat()}",
            }
        )

    for row in exception_rows or []:
        event_at_raw = str(row.get("created_at") or row.get("exception_date") or "").strip()
        event_at = _parse_dt(event_at_raw)
        if event_at is None:
            continue
        resolved_at = str(row.get("resolved_at") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        is_resolved = bool(resolved_at or status == "resolved")
        raw_event_type = "resolved" if is_resolved else "exception_opened"
        entry = format_timeline_event_display({
            "event_type": raw_event_type,
            "status": status,
            "notes": str(row.get("summary") or row.get("notes") or "").strip(),
        })
        canonical_type = _canonical_timeline_event_type(
            raw_event_type=raw_event_type,
            status=status,
            title=entry["title"],
            source="exception",
        )
        if canonical_type not in _ALLOWED_TIMELINE_EVENT_TYPES:
            continue
        source_text = str(row.get("summary") or row.get("notes") or "").strip()
        description = _clean_timeline_description(str(entry.get("description") or ""))
        if source_text and not description:
            continue
        events.append(
            {
                "event_at": event_at,
                "event_at_raw": event_at_raw,
                "event_type": canonical_type,
                "description": description,
                "source": "exception",
                "dedupe_key": f"{canonical_type}|{event_at.isoformat()}",
            }
        )

    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for event in events:
        key = str(event.get("dedupe_key") or "")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(event)

    deduped.sort(
        key=lambda event: (
            -(float(event["event_at"].timestamp()) if isinstance(event.get("event_at"), datetime) else 0.0),
            _narrative_weight(str(event.get("event_type") or "").strip()),
        ),
    )
    return deduped[:limit]


def _note_datetime(note: dict) -> datetime | None:
    return _parse_dt(str(note.get("created_at") or note.get("date") or "").strip())


def _note_author_text(note: dict) -> str:
    return str(
        note.get("author")
        or note.get("coach")
        or note.get("created_by")
        or note.get("created_by_name")
        or ""
    ).strip()


def _note_text(note: dict) -> str:
    raw_text = str(note.get("note") or note.get("notes") or "")
    return clean_note_text_for_display(raw_text)


def _normalize_notes_history(notes: list[dict], preview_chars: int = 180) -> list[dict]:
    normalized: list[dict] = []
    for note in notes or []:
        text = _note_text(note)
        if not text:
            continue
        note_dt = _note_datetime(note)
        when_text = note_dt.strftime("%Y-%m-%d %H:%M") if note_dt else str(note.get("date") or note.get("created_at") or format_empty_state("unknown_date"))[:16]
        preview = text
        is_truncated = len(text) > preview_chars
        if is_truncated:
            preview = f"{text[:preview_chars].rstrip()}..."
        normalized.append(
            {
                "note_dt": note_dt,
                "when_text": when_text,
                "author": _note_author_text(note),
                "preview": preview,
                "full_text": text,
                "is_truncated": is_truncated,
            }
        )

    normalized.sort(
        key=lambda row: (
            float(row["note_dt"].timestamp()) if isinstance(row.get("note_dt"), datetime) else float("-inf"),
            str(row.get("when_text") or ""),
        ),
        reverse=True,
    )
    return normalized


def _render_note_history_entry(note_row: dict, *, index: int) -> None:
    display_when = _format_display_dt(str(note_row.get("when_text") or ""))
    metadata_text = format_note_entry(display_when)
    preview_text = format_note_preview_text(str(note_row.get("preview") or ""))

    st.markdown(
        "\n".join(
            [
                "<div class='team-notes-entry'>",
                f"<div class='team-notes-body'>{escape(preview_text)}</div>",
                f"<div class='team-notes-meta'>{escape(metadata_text)}</div>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )

    if bool(note_row.get("is_truncated")):
        with st.expander(
            format_note_expand_label(index, when_text=str(note_row.get("when_text") or "")),
            expanded=False,
        ):
            st.write(str(note_row.get("full_text") or ""))


def _render_exception_history_entry(exception_row: dict, *, index: int) -> None:
    context_line = str(exception_row.get("context_line") or "").strip()
    exception_type = str(exception_row.get("exception_type") or "").strip()
    when_text = str(exception_row.get("when_text") or "").strip()
    display_when = _format_display_dt(when_text)
    context_text = context_line if context_line and context_line != exception_type else display_when
    preview_text = format_exception_preview_text(str(exception_row.get("preview") or ""))

    st.markdown(
        "\n".join(
            [
                "<div class='team-exceptions-entry'>",
                f"<div class='team-exceptions-primary'>{escape(format_exception_text(exception_type))}</div>",
                f"<div class='team-exceptions-meta'>{escape(context_text)}</div>",
                (f"<div class='team-exceptions-support'>{escape(preview_text)}</div>" if preview_text else ""),
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )

    if bool(exception_row.get("is_truncated")):
        with st.expander(
            format_exception_expand_label(index, when_text=when_text),
            expanded=False,
        ):
            st.write(str(exception_row.get("full_text") or ""))


def _split_primary_support_text(text: str) -> tuple[str, str]:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return "", ""
    first_period = clean.find(".")
    if first_period == -1:
        return clean, ""
    primary = clean[: first_period + 1].strip()
    support = clean[first_period + 1 :].strip()
    return primary, support


def _exception_datetime(row: dict) -> datetime | None:
    return _parse_dt(
        str(
            row.get("resolved_at")
            or row.get("created_at")
            or row.get("exception_date")
            or ""
        ).strip()
    )


def _exception_type_text(row: dict) -> str:
    category = str(row.get("category") or "").strip()
    text = category.replace("_", " ").title() if category else ""
    return format_exception_text(text)


def _exception_detail_text(row: dict) -> str:
    detail = str(row.get("summary") or row.get("notes") or "").strip()
    return " ".join(detail.split())


def _normalize_exception_history(exception_rows: list[dict], preview_chars: int = 140) -> list[dict]:
    normalized: list[dict] = []
    for row in exception_rows or []:
        event_dt = _exception_datetime(row)
        when_text = event_dt.strftime("%Y-%m-%d %H:%M") if event_dt else str(row.get("exception_date") or row.get("created_at") or format_empty_state("unknown_date"))[:16]
        context_line = build_exception_context_line(row)
        context_line = format_exception_context_line(context_line, fallback_when=when_text)
        exception_type = _exception_type_text(row)
        detail_text = _exception_detail_text(row)
        preview = detail_text
        is_truncated = len(detail_text) > preview_chars
        if is_truncated:
            preview = f"{detail_text[:preview_chars].rstrip()}..."
        normalized.append(
            {
                "event_dt": event_dt,
                "when_text": when_text,
                "exception_type": exception_type,
                "context_line": context_line,
                "preview": preview,
                "full_text": detail_text,
                "is_truncated": is_truncated,
            }
        )

    normalized.sort(
        key=lambda row: (
            float(row["event_dt"].timestamp()) if isinstance(row.get("event_dt"), datetime) else float("-inf"),
            str(row.get("when_text") or ""),
        ),
        reverse=True,
    )
    return normalized


def _department_comparison_context(*, goal_status_rows: list[dict], selected_row: dict, department: str) -> str:
    department_name = str(department or "").strip().lower()
    if not department_name:
        return ""

    selected_average = _safe_float(selected_row.get("Average UPH"))
    if selected_average is None or selected_average <= 0:
        return ""

    department_values: list[float] = []
    below_target_count = 0
    comparable_count = 0
    for row in goal_status_rows or []:
        row_department = str(row.get("Department") or "").strip().lower()
        if row_department != department_name:
            continue

        uph = _safe_float(row.get("Average UPH"))
        if uph is None:
            continue

        department_values.append(float(uph))
        target_uph = _safe_float(row.get("Target UPH"))
        if target_uph is not None and target_uph > 0:
            comparable_count += 1
            if float(uph) < target_uph:
                below_target_count += 1

    if len(department_values) < 3:
        return ""

    department_median = float(median(department_values)) if department_values else 0.0
    if department_median <= 0:
        return ""

    delta_pct = ((selected_average - department_median) / department_median) * 100.0
    share_below_target: float | None = None
    if comparable_count >= 3:
        share_below_target = below_target_count / comparable_count

    return " ".join(format_comparison_text(delta_pct=delta_pct, share_below_target=share_below_target)).strip()


def _load_team_roster_snapshot(*, tenant_id: str, days: int = 30) -> tuple[list[dict], str, str]:
    cached_goal_status = list(st.session_state.get("goal_status") or [])
    cached_tenant = str(st.session_state.get("_goal_history_tenant") or "")
    cached_snapshot_date = str(st.session_state.get("_latest_snapshot_date") or "")

    try:
        snapshot_goal_status, _, snapshot_date = get_latest_snapshot_goal_status(
            tenant_id=tenant_id,
            days=days,
            rebuild_if_missing=False,
        )
    except Exception:
        snapshot_goal_status, snapshot_date = [], ""

    if snapshot_goal_status:
        st.session_state["goal_status"] = snapshot_goal_status
        st.session_state["_latest_snapshot_date"] = snapshot_date
        st.session_state["_goal_history_tenant"] = tenant_id
        st.session_state["_goal_history_loaded_at"] = datetime.now().timestamp()
        return list(snapshot_goal_status), str(snapshot_date or ""), "snapshot"

    if cached_goal_status and cached_tenant == tenant_id:
        return cached_goal_status, cached_snapshot_date, "session"

    return [], "", "empty"


def _render_team_page_styles() -> None:
    st.markdown(
        """
        <style>
        div.block-container {
            padding-top: 1.1rem;
            padding-bottom: 1.4rem;
        }
        div[data-testid="stHorizontalBlock"] {
            gap: 1rem;
        }
        div[data-testid="stRadio"] [role="radiogroup"] {
            gap: 0.25rem;
        }
        div[data-testid="stRadio"] label {
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
        }
        div[data-testid="stExpander"] details {
            border: 0;
            background: transparent;
        }
        div[data-testid="stExpander"] summary {
            font-size: 0.88rem;
        }
        div[data-testid="stMarkdownContainer"] p {
            margin-bottom: 0.25rem;
        }
        .team-roster-anchor {
            height: 0;
            margin: 0;
            padding: 0;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) {
            background: #F8FAFD;
            border: 1px solid #E8EEF7;
            border-radius: 0.62rem;
            padding: 0.75rem 0.82rem;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) h3 {
            font-size: 1.0rem;
            font-weight: 600;
            letter-spacing: 0.01em;
            margin: 0 0 0.125rem 0;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] [role="radiogroup"] {
            gap: 0.3rem;
            margin-top: 0.25rem;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label {
            padding: 0.42rem 0.5rem;
            border-radius: 0.6rem;
            border: 1px solid transparent;
            background: transparent;
            transition: background-color 140ms ease, border-color 140ms ease, box-shadow 140ms ease, transform 120ms ease;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label:hover {
            background: #F1F6FF;
            border-color: #DCE8FA;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label p {
            margin: 0;
            line-height: 1.35;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label:has(input[type="radio"]:checked) {
            background: #EAF2FF;
            border-color: #C8DBF8;
            box-shadow: 0 0 0 1px rgba(99, 136, 199, 0.14);
            transform: translateX(1px);
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label:has(input[type="radio"]:checked) p {
            color: #13335C;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label:has(input[type="radio"]:checked) p::first-line {
            font-weight: 700;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label [data-testid="stMarkdownContainer"] {
            transition: opacity 120ms ease;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label:has(input[type="radio"]:checked) [data-testid="stMarkdownContainer"] {
            opacity: 1;
        }
        div[data-testid="stVerticalBlock"]:has(.team-roster-anchor) div[data-testid="stRadio"] label input[type="radio"] {
            accent-color: #4B74B8;
        }
        .team-section-anchor {
            height: 0;
            margin: 0;
            padding: 0;
        }
        .team-detail-view-anchor {
            height: 0;
            margin: 0;
            padding: 0;
        }
        div[data-testid="stVerticalBlock"]:has(.team-detail-view-anchor) {
            padding-top: 0.15rem;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor) {
            margin-top: 1.35rem;
            padding: 0;
            border: 0;
            border-radius: 0;
            background: transparent;
            box-shadow: none;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--summary) {
            margin-top: 0.1rem;
            padding-top: 0.15rem;
            padding-bottom: 1.05rem;
            margin-bottom: 0.5rem;
            background: transparent;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--comparison) {
            padding-top: 0.2rem;
            padding-bottom: 0.3rem;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor) h4 {
            font-size: 0.84rem;
            font-weight: 550;
            letter-spacing: 0.03em;
            text-transform: uppercase;
            color: var(--dpd-text-muted);
            margin: 0 0 0.35rem 0;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--summary) h3 {
            font-size: 1.22rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            margin: 0 0 0.3rem 0;
        }
        .team-section-divider {
            margin: 1rem 0 0.2rem 0;
            border-top: 1px solid #F1F4F9;
            height: 0;
        }
        .team-summary-context {
            font-size: 0.95rem;
            font-weight: 400;
            color: var(--dpd-text-muted);
            line-height: 1.55;
            margin: 0 0 0.38rem 0;
        }
        .team-focus-banner {
            margin: 0 0 0.6rem 0;
            padding: 0.35rem 0.55rem;
            border-radius: 0.5rem;
            background: #EEF5FF;
            border: 1px solid #D6E6FB;
            color: #214C84;
            font-size: 0.86rem;
            font-weight: 550;
            line-height: 1.35;
        }
        .team-summary-context-highlight {
            background: #F2F8FF;
            border-left: 3px solid #7AA2D8;
            border-radius: 0.35rem;
            padding: 0.2rem 0.45rem;
            color: #244E81;
        }
        .team-summary-primary {
            font-size: 1.62rem;
            font-weight: 680;
            color: var(--dpd-navy-900);
            line-height: 1.24;
            margin: 0.25rem 0 0.6rem 0;
            max-width: 54rem;
        }
        .team-summary-secondary {
            font-size: 1.0rem;
            font-weight: 400;
            line-height: 1.55;
            margin: 0 0 0.55rem 0;
            color: var(--dpd-text);
            max-width: 56rem;
        }
        .team-trend-primary {
            font-size: 0.96rem;
            font-weight: 600;
            color: var(--dpd-navy-900);
            line-height: 1.38;
            margin: 0.125rem 0 0.25rem 0;
        }
        .team-timeline-entry {
            padding: 0.25rem 0 0.45rem 0;
            border-left: 0;
            border-bottom: 0;
        }
        .team-timeline-entry:last-child {
            border-bottom: 0;
            padding-bottom: 0.1rem;
        }
        .team-timeline-event {
            font-size: 0.87rem;
            font-weight: 540;
            color: var(--dpd-text);
            margin: 0 0 0.125rem 0;
            line-height: 1.3;
        }
        .team-timeline-meta {
            font-size: 0.74rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
            opacity: 0.9;
        }
        .team-timeline-detail {
            font-size: 0.82rem;
            color: var(--dpd-text);
            margin: 0.2rem 0 0 0;
            line-height: 1.42;
            opacity: 0.9;
        }
        .team-notes-entry {
            padding: 0.22rem 0 0.45rem 0;
            border-left: 0;
            border-bottom: 0;
        }
        .team-notes-entry:last-child {
            border-bottom: 0;
            padding-bottom: 0.12rem;
        }
        .team-notes-body {
            font-size: 0.85rem;
            font-weight: 400;
            color: var(--dpd-text);
            margin: 0 0 0.125rem 0;
            line-height: 1.38;
            opacity: 0.94;
        }
        .team-notes-meta {
            font-size: 0.74rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
            opacity: 0.86;
        }
        .team-exceptions-entry {
            padding: 0.22rem 0 0.45rem 0;
            border-left: 0;
            border-bottom: 0;
        }
        .team-exceptions-entry:last-child {
            border-bottom: 0;
            padding-bottom: 0.1rem;
        }
        .team-exceptions-primary {
            font-size: 0.85rem;
            font-weight: 540;
            color: var(--dpd-text);
            margin: 0 0 0.125rem 0;
            line-height: 1.35;
        }
        .team-exceptions-meta {
            font-size: 0.74rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
            opacity: 0.86;
        }
        .team-exceptions-support {
            font-size: 0.81rem;
            color: var(--dpd-text);
            margin: 0.2rem 0 0 0;
            line-height: 1.42;
            opacity: 0.9;
        }
        .team-comparison-primary {
            font-size: 0.83rem;
            font-weight: 500;
            color: var(--dpd-text);
            margin: 0.125rem 0;
            line-height: 1.35;
            opacity: 0.9;
        }
        .team-comparison-support {
            font-size: 0.73rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
            opacity: 0.86;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--timeline) div[data-testid="stExpander"] summary,
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--notes) div[data-testid="stExpander"] summary,
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--exceptions) div[data-testid="stExpander"] summary {
            font-size: 0.81rem;
            opacity: 0.8;
            padding-left: 0.625rem;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--timeline) div[data-testid="stExpander"],
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--notes) div[data-testid="stExpander"],
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--exceptions) div[data-testid="stExpander"] {
            margin-top: 0.25rem;
        }
        .team-section-intent {
            font-size: 0.74rem;
            font-weight: 400;
            color: var(--dpd-text-muted);
            opacity: 0.7;
            margin: 0 0 0.375rem 0;
            line-height: 1.2;
            letter-spacing: 0.04em;
            text-transform: lowercase;
        }
        .team-timeline-group {
            font-size: 0.68rem;
            font-weight: 600;
            color: var(--dpd-text-muted);
            text-transform: uppercase;
            letter-spacing: 0.09em;
            margin: 0.56rem 0 0.2rem 0;
            opacity: 0.64;
        }
        .team-timeline-group:first-child {
            margin-top: 0.125rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_team() -> None:
    """Team page product contract.

    Product intent (durable):
    - Today = act.
    - Team = understand.
    - Team is for context, trends, history, notes, exceptions, and follow-through.
    - Team is not a second action queue.
    - Team should remain mostly read-only.
    - Team should avoid dashboard overload.
    - Team should load quickly and only fetch deep detail for the selected employee.
    """
    if not require_db():
        return

    tenant_id = str(st.session_state.get("tenant_id") or "").strip()
    user_email = str(st.session_state.get("user_email") or "").strip()
    section_titles = get_team_section_titles()
    filter_labels = get_team_filter_labels()

    _render_team_page_styles()
    st.markdown(f"## {section_titles['page_title']}")
    st.caption(format_page_hero_caption())

    with profile_block(
        "team.page_render",
        tenant_id=tenant_id,
        user_email=user_email,
        context={"page": "team"},
        execution_key="_perf_profile_team_page_render",
    ) as profile:
        with profile.stage("load_roster_snapshot"):
            goal_status, snapshot_date, roster_source = _load_team_roster_snapshot(tenant_id=tenant_id, days=30)
        profile.set("roster_source", roster_source)
        profile.set("snapshot_date", snapshot_date)
        profile.observe_rows("roster_rows", goal_status)
        if goal_status:
            profile.query(rows=len(goal_status), count=1)

        if not goal_status:
            st.info(format_empty_state("no_team_records"))
            return

        # Lightweight Team filters (durable session keys, compact row).
        st.session_state.setdefault("team_employee_search", "")
        st.session_state.setdefault("team_department_filter", "all")
        st.session_state.setdefault("team_status_filter", "all")
        st.session_state.setdefault("team_time_window_days", 14)

        all_departments = sorted(
            {
                str(row.get("Department") or "").strip() or "Unknown"
                for row in goal_status
            },
            key=lambda value: value.lower(),
        )
        department_options = ["all", *all_departments]
        if st.session_state["team_department_filter"] not in department_options:
            st.session_state["team_department_filter"] = "all"

        status_options = ["all", "needs attention", "stable", "improved recently"]
        if st.session_state["team_status_filter"] not in status_options:
            st.session_state["team_status_filter"] = "all"

        if int(st.session_state["team_time_window_days"]) not in {7, 14, 30}:
            st.session_state["team_time_window_days"] = 14

    filter_col_1, filter_col_2, filter_col_3, filter_col_4 = st.columns([2.2, 1.2, 1.2, 1.0])
    with filter_col_1:
        st.text_input(
            filter_labels["employee_label"],
            key="team_employee_search",
            placeholder=filter_labels["employee_placeholder"],
        )
    with filter_col_2:
        st.selectbox(filter_labels["department_label"], options=department_options, key="team_department_filter")
    with filter_col_3:
        st.selectbox(
            filter_labels["status_label"],
            options=status_options,
            key="team_status_filter",
            format_func=format_status_filter_option,
        )
    with filter_col_4:
        st.radio(filter_labels["window_label"], options=[7, 14, 30], key="team_time_window_days", horizontal=True)

        employee_search = str(st.session_state.get("team_employee_search") or "").strip().lower()
        department_filter = str(st.session_state.get("team_department_filter") or "all").strip().lower()
        status_filter = str(st.session_state.get("team_status_filter") or "all").strip().lower()
        time_window_days = int(st.session_state.get("team_time_window_days") or 14)

        with profile.stage("filter_roster"):
            filtered_employees: list[dict] = []
            for row in goal_status:
                display_name = _employee_display_name(row)
                department_value = str(row.get("Department") or "").strip() or "Unknown"
                status_value = _team_status_bucket(row)
                if employee_search and employee_search not in display_name.lower():
                    continue
                if department_filter != "all" and department_value.lower() != department_filter:
                    continue
                if status_filter != "all" and status_value != status_filter:
                    continue
                filtered_employees.append(row)
        profile.observe_rows("filtered_roster_rows", filtered_employees)

        employees_sorted = sorted(filtered_employees, key=lambda row: str(row.get("Employee Name") or row.get("Employee") or "").lower())
        if not employees_sorted:
            st.caption(format_empty_state("no_filter_match"))
            employees_sorted = sorted(goal_status, key=lambda row: str(row.get("Employee Name") or row.get("Employee") or "").lower())
            if not employees_sorted:
                st.info(format_empty_state("no_team_records"))
                return

    shell_left, shell_right = st.columns([1.0, 2.4], gap="medium")

    # TODO(team-contract): Employee roster section - pick one employee and defer deep detail until selected.
    roster_summaries: list[dict] = []
    row_by_employee_id: dict[str, dict] = {}
    for row in employees_sorted:
        employee_id = _employee_id(row)
        if not employee_id:
            continue
        summary = {
            "employee_id": employee_id,
            "name": str(row.get("Employee Name") or row.get("Employee") or "Unknown").strip() or "Unknown",
            "department": str(row.get("Department") or "").strip() or "Unknown",
            "trend_label": format_trend_label(_team_status_bucket(row)),
            "reason": _roster_reason_text(row),
            "meta": _roster_meta_text(row),
        }
        roster_summaries.append(summary)
        row_by_employee_id[employee_id] = row

    if not roster_summaries:
        st.caption(format_empty_state("no_selectable_roster"))
        return

    employee_ids = [item["employee_id"] for item in roster_summaries]
    summary_by_id = {item["employee_id"]: item for item in roster_summaries}

    handoff_payload_raw = st.session_state.get(_TODAY_TO_TEAM_HANDOFF_KEY)
    handoff_payload = handoff_payload_raw if isinstance(handoff_payload_raw, dict) else {}
    handoff_employee_id = str(handoff_payload.get("employee_id") or "").strip()
    handoff_reason = _clean_plain_handoff_reason(str(handoff_payload.get("reason") or ""))
    handoff_follow_up_status = _clean_plain_handoff_reason(str(handoff_payload.get("follow_up_status") or ""))
    handoff_signal_id = str(handoff_payload.get("signal_id") or "").strip()
    handoff_signal_key = str(handoff_payload.get("signal_key") or "").strip()
    has_today_handoff = bool(handoff_employee_id and handoff_employee_id in employee_ids)

    requested_employee_id = str(
        (handoff_employee_id if has_today_handoff else "")
        or st.session_state.get("team_selected_emp_id")
        or st.session_state.get("cn_selected_emp")
        or ""
    ).strip()
    default_index = 0
    if requested_employee_id:
        for index, employee_id in enumerate(employee_ids):
            if employee_id == requested_employee_id:
                default_index = index
                break
    selected_employee_id = employee_ids[default_index]
    if str(st.session_state.get("team_selected_emp_id") or "").strip() not in employee_ids:
        st.session_state["team_selected_emp_id"] = selected_employee_id

    with shell_left:
        st.markdown("<div class='team-roster-anchor'></div>", unsafe_allow_html=True)
        st.markdown(f"### {section_titles['roster']}")
        roster_support = _compact_support_line(
            format_roster_helper_text(),
            format_roster_count(len(employee_ids)),
        )
        if roster_support:
            st.caption(roster_support)
        st.radio(
            "",
            options=employee_ids,
            key="team_selected_emp_id",
            format_func=lambda employee_id: _roster_row_label(summary_by_id.get(employee_id) or {}),
            label_visibility="collapsed",
        )

        employee_id = str(st.session_state.get("team_selected_emp_id") or "").strip()
        selected_row = row_by_employee_id.get(employee_id)
        if selected_row is None:
            employee_id = employee_ids[0]
            st.session_state["team_selected_emp_id"] = employee_id
            selected_row = row_by_employee_id[employee_id]

        employee_name = str(selected_row.get("Employee Name") or selected_row.get("Employee") or "Unknown").strip() or "Unknown"
        department = str(selected_row.get("Department") or "").strip() or "Unknown"

        avg_uph = _safe_float(selected_row.get("Average UPH"))
        target_uph = _safe_float(selected_row.get("Target UPH"))
        status_bucket = _team_status_bucket(selected_row)
        status_label = ""

        with profile.stage("load_selected_employee_detail"):
            notes = list(_cached_coaching_notes_for(employee_id) or [])
            timeline_rows = list(get_employee_action_timeline(employee_id, tenant_id=tenant_id) or [])[:60]
            exceptions = list_recent_operational_exceptions(tenant_id=tenant_id, employee_id=employee_id, limit=25)
        profile.set("selected_employee_id", employee_id)
        profile.set("notes_rows", len(notes))
        profile.set("timeline_rows", len(timeline_rows))
        profile.set("exception_rows", len(exceptions or []))
        profile.query(rows=len(notes) + len(timeline_rows) + len(exceptions or []), count=3)

        unified_timeline = _normalize_recent_activity_timeline(
            notes=notes,
            action_rows=timeline_rows,
            exception_rows=exceptions,
            limit=5,
        )
        current_vs_target_text = _current_vs_target_text(avg_uph, target_uph)
        comparison_text = _department_comparison_context(
            goal_status_rows=goal_status,
            selected_row=selected_row,
            department=department,
        )
        comparison_brief = format_comparison_context_brief(comparison_text)

        with profile.stage("load_selected_employee_snapshot_history"):
            employee_snapshot_history = list(
                get_employee_snapshot_history(
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    days=max(30, time_window_days),
                )
                or []
            )
        profile.set("selected_history_rows", len(employee_snapshot_history))
        profile.query(rows=len(employee_snapshot_history), count=1)

        window_start: datetime | None = None
        if time_window_days > 0:
            window_start = datetime.utcnow() - timedelta(days=time_window_days)

        employee_history: list[dict] = []
        for row in employee_snapshot_history:
            row_dt = _parse_dt(str(row.get("snapshot_date") or "").strip())
            if window_start is not None and row_dt is not None and row_dt < window_start:
                continue
            employee_history.append(row)

        chart_rows: list[dict] = []
        if employee_history:
            for row in employee_history:
                dt_value = _parse_dt(str(row.get("snapshot_date") or "").strip())
                if dt_value is None:
                    continue
                uph = _safe_float(row.get("performance_uph"))
                if uph is None:
                    continue
                chart_rows.append({"Date": dt_value.date().isoformat(), "UPH": uph})

        trend_metrics = _compute_window_trend_metrics(chart_rows)
        change_pct = _safe_float(trend_metrics.get("change_pct"))
        status_label = str(trend_metrics.get("label") or "").strip()
        selected_window_trend_text = _format_window_trend_summary(trend_metrics, time_window_days)
        what_changed_text = _what_changed_line(
            selected_row,
            change_pct=change_pct,
            status_bucket=status_bucket,
            time_window_days=time_window_days,
            avg_uph=avg_uph,
            target_uph=target_uph,
        )

        primary_statement = format_primary_statement(
            status_bucket=status_bucket,
            change_pct=change_pct,
            avg_uph=avg_uph,
            target_uph=target_uph,
            time_window_days=time_window_days,
        )
        follow_up_subline = _follow_up_subline(selected_row)
        secondary_context = format_secondary_context_subline(
            comparison_brief=comparison_brief,
            follow_up_text=follow_up_subline,
        )
        sustained_context = format_sustained_context_line(
            status_bucket=status_bucket,
            change_pct=change_pct,
            time_window_days=time_window_days,
        )
        note_history = _normalize_notes_history(notes, preview_chars=180)
        exception_history = _normalize_exception_history(exceptions, preview_chars=140)
        follow_up_status_lines = _build_follow_up_status_lines(
            row=selected_row,
            notes=notes,
            action_rows=timeline_rows,
        )
        if handoff_follow_up_status and all(
            handoff_follow_up_status.lower() not in str(line or "").lower()
            for line in follow_up_status_lines
        ):
            follow_up_status_lines.append(handoff_follow_up_status)
        current_situation_lines = _build_current_situation_lines(
            trend_metrics=trend_metrics,
            days=time_window_days,
            target_uph=target_uph,
            chart_rows=chart_rows,
        )
        why_happening_lines = _build_why_happening_lines(
            chart_rows=chart_rows,
            target_uph=target_uph,
            exception_history=exception_history,
            note_history=note_history,
        )

        with shell_right:
            st.markdown("<div class='team-detail-view-anchor'></div>", unsafe_allow_html=True)
            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--summary'></div>", unsafe_allow_html=True)
                st.markdown(f"### {employee_name}")
                st.caption(format_selected_employee_subheader(department, status_label))
                if has_today_handoff and handoff_reason and employee_id == handoff_employee_id:
                    st.markdown(
                        f"<div class='team-focus-banner'>Opened from Today: {escape(handoff_reason)}</div>",
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f"<div class='team-summary-context'>Main state: {escape(selected_window_trend_text)}</div>",
                    unsafe_allow_html=True,
                )
                attention_line = (
                    "Needs attention this week"
                    if status_bucket == "needs attention"
                    else "Monitor this week"
                )
                st.markdown(
                    f"<div class='team-summary-context'>Attention level: {escape(attention_line)}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("#### Follow-up status")
                for line in follow_up_status_lines:
                    st.markdown(f"<div class='team-summary-context'>{escape(line)}</div>", unsafe_allow_html=True)
                if has_today_handoff and handoff_reason and employee_id == handoff_employee_id:
                    st.markdown(
                        f"<div class='team-summary-context team-summary-context-highlight'>{escape(handoff_reason)}</div>",
                        unsafe_allow_html=True,
                    )
                if primary_statement:
                    st.markdown(f"<div class='team-summary-primary'>{escape(primary_statement)}</div>", unsafe_allow_html=True)
                if secondary_context:
                    st.markdown(f"<div class='team-summary-secondary'>{escape(secondary_context)}</div>", unsafe_allow_html=True)
                if what_changed_text:
                    st.markdown(f"<div class='team-summary-context'>{escape(what_changed_text)}</div>", unsafe_allow_html=True)
                if sustained_context:
                    st.markdown(f"<div class='team-summary-context'>{escape(sustained_context)}</div>", unsafe_allow_html=True)
                _row_confidence = str(selected_row.get("confidence_label") or "").strip()
                _row_completeness = str(selected_row.get("data_completeness_status") or "").strip()
                _summary_chips: list[str] = [format_chip_current_vs_target(current_vs_target_text)]
                if _row_confidence:
                    _summary_chips.append(format_confidence_meta(_row_confidence))
                elif _row_completeness:
                    _summary_chips.append(format_data_completeness_meta(_row_completeness))
                st.caption(" | ".join(_summary_chips))

                # Bridge to Today: subtle control to pass employee context and navigate.
                bridge_col_1, bridge_col_2 = st.columns([0.5, 3.0], gap="small")
                with bridge_col_1:
                    if st.button(format_bridge_button_label(), key=f"team_bridge_to_today_{selected_employee_id}"):
                        if selected_employee_id and str(selected_employee_id).strip():
                            st.session_state["cn_selected_emp"] = selected_employee_id
                            st.session_state[_TEAM_TO_TODAY_FOCUS_KEY] = {
                                "employee_id": selected_employee_id,
                                "signal_id": handoff_signal_id if selected_employee_id == handoff_employee_id else "",
                                "signal_key": handoff_signal_key if selected_employee_id == handoff_employee_id else "",
                            }
                            st.session_state["goto_page"] = "today"
                            st.rerun()
                with bridge_col_2:
                    st.caption(format_bridge_helper())

                st.markdown("<div class='team-section-divider'></div>", unsafe_allow_html=True)

            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--situation'></div>", unsafe_allow_html=True)
                st.markdown("#### Current situation")
                for line in current_situation_lines:
                    is_handoff_match = bool(
                        has_today_handoff
                        and handoff_reason
                        and employee_id == handoff_employee_id
                        and (
                            handoff_reason.lower() in str(line or "").lower()
                            or str(line or "").lower() in handoff_reason.lower()
                        )
                    )
                    line_class = "team-summary-context team-summary-context-highlight" if is_handoff_match else "team-summary-context"
                    st.markdown(f"<div class='{line_class}'>{escape(line)}</div>", unsafe_allow_html=True)

                if why_happening_lines:
                    st.markdown("#### What we're seeing")
                    for line in why_happening_lines:
                        st.markdown(f"<div class='team-summary-context'>{escape(line)}</div>", unsafe_allow_html=True)

            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--trend'></div>", unsafe_allow_html=True)
                st.markdown(f"#### {section_titles['trend']}")
                st.markdown("<div class='team-section-intent'>recent direction</div>", unsafe_allow_html=True)

            if employee_history:
                profile.set("chart_rows", len(chart_rows))

                if chart_rows:
                    st.caption(format_trend_intro(time_window_days))

                    # Single analytical chart for selected-employee trend in the selected window.
                    history_df = pd.DataFrame(chart_rows).drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
                    if target_uph is not None and target_uph > 0:
                        history_df["Target"] = float(target_uph)
                        st.line_chart(history_df.set_index("Date")[["UPH", "Target"]], use_container_width=True)
                    else:
                        st.line_chart(history_df.set_index("Date")["UPH"], use_container_width=True)

                    if selected_window_trend_text:
                        st.caption(selected_window_trend_text)
                else:
                    st.markdown(f"<div class='team-trend-primary'>{format_trend_no_points()}</div>", unsafe_allow_html=True)
                    st.caption(format_trend_intro(time_window_days))
            else:
                st.markdown(f"<div class='team-trend-primary'>{format_trend_no_history()}</div>", unsafe_allow_html=True)
                st.caption(format_trend_intro(time_window_days))

            if note_history:
                with st.container():
                    st.markdown("<div class='team-section-anchor team-section-anchor--notes'></div>", unsafe_allow_html=True)
                    st.markdown(f"#### {section_titles['notes']}")
                    st.markdown("<div class='team-section-intent'>follow-up history</div>", unsafe_allow_html=True)
                    # TODO(team-contract): Notes history section - prior notes for selected employee.
                    visible_count = 8
                    for index, note_row in enumerate(note_history[:visible_count], start=1):
                        _render_note_history_entry(note_row, index=index)

                    remaining_count = len(note_history) - visible_count
                    if remaining_count > 0:
                        with st.expander(format_show_older_notes_label(remaining_count), expanded=False):
                            for index, note_row in enumerate(note_history[visible_count:], start=visible_count + 1):
                                _render_note_history_entry(note_row, index=index)

            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--exceptions'></div>", unsafe_allow_html=True)
                st.markdown(f"#### {section_titles['exceptions']}")
                st.markdown("<div class='team-section-intent'>current context</div>", unsafe_allow_html=True)
                if not exception_history:
                    st.caption(format_empty_state("no_exceptions"))
                else:
                    st.caption(f"{len(exception_history)} recent exception item(s)")
                    with st.expander("Show exception details", expanded=False):
                        for index, exception_row in enumerate(exception_history, start=1):
                            _render_exception_history_entry(exception_row, index=index)

            with st.expander("Recent activity (optional)", expanded=False):
                if not unified_timeline:
                    st.caption(format_empty_state("no_timeline"))
                else:
                    _today_date = datetime.utcnow().date()

                    def _is_today_event(ev: dict) -> bool:
                        ev_at = ev.get("event_at")
                        return isinstance(ev_at, datetime) and ev_at.date() == _today_date

                    def _render_timeline_event(ev: dict) -> None:
                        when_iso = _timeline_when_text(ev.get("event_at"), fallback=str(ev.get("event_at_raw") or ""))
                        display_when = _format_display_dt(when_iso)
                        ev_type = str(ev.get("event_type") or "Update added")
                        ev_desc = str(ev.get("description") or "")
                        detail_html = f"<div class='team-timeline-detail'>{escape(ev_desc)}</div>" if ev_desc else ""
                        st.markdown(
                            "\n".join(
                                [
                                    "<div class='team-timeline-entry'>",
                                    f"<div class='team-timeline-event'>{escape(ev_type)}</div>",
                                    f"<div class='team-timeline-meta'>{escape(display_when)}</div>",
                                    detail_html,
                                    "</div>",
                                ]
                            ),
                            unsafe_allow_html=True,
                        )

                    _today_events = [ev for ev in unified_timeline if _is_today_event(ev)]
                    _earlier_events = [ev for ev in unified_timeline if not _is_today_event(ev)]

                    if _today_events:
                        st.markdown("<div class='team-timeline-group'>Today</div>", unsafe_allow_html=True)
                        for ev in _today_events:
                            _render_timeline_event(ev)

                    if _earlier_events:
                        if _today_events:
                            st.markdown("<div class='team-timeline-group'>Earlier</div>", unsafe_allow_html=True)
                        for ev in _earlier_events:
                            _render_timeline_event(ev)

            if comparison_text:
                with st.container():
                    st.markdown("<div class='team-section-anchor team-section-anchor--comparison'></div>", unsafe_allow_html=True)
                    st.markdown(f"#### {format_comparison_section_title()}")
                    comparison_primary, comparison_support = _split_primary_support_text(comparison_text)
                    if comparison_primary:
                        st.markdown(f"<div class='team-comparison-primary'>{escape(comparison_primary)}</div>", unsafe_allow_html=True)
                    if comparison_support:
                        st.markdown(f"<div class='team-comparison-support'>{escape(comparison_support)}</div>", unsafe_allow_html=True)

        if has_today_handoff:
            # One-time Team focus state from Today; consume after first render.
            st.session_state.pop(_TODAY_TO_TEAM_HANDOFF_KEY, None)

    # TODO(team-contract): Optional comparison context section - only if it remains lightweight and non-prescriptive.
