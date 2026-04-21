"""Centralized wording helpers for the Team page.

This module is presentation-only. It must not change business logic,
query behavior, or state semantics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


_SECTION_TITLES = {
    "page_title": "Team",
    "roster": "Roster",
    "trend": "Trend",
    "timeline": "Timeline",
    "notes": "Notes",
    "exceptions": "Exceptions",
    "comparison": "Department comparison",
}

_FILTER_LABELS = {
    "employee_label": "Employee",
    "employee_placeholder": "Search by name or ID",
    "department_label": "Department",
    "status_label": "Status",
    "window_label": "Time range (days)",
}

_STATUS_LABELS = {
    "all": "All statuses",
    "needs attention": "Needs review",
    "stable": "Holding steady",
    "improved recently": "Improving",
}


def get_team_section_titles() -> dict[str, str]:
    """Return Team page section titles for consistent scanning."""
    return dict(_SECTION_TITLES)


def get_team_filter_labels() -> dict[str, str]:
    """Return Team filter labels and placeholders."""
    return dict(_FILTER_LABELS)


def format_status_filter_option(option: str) -> str:
    """Map internal status filter values to user-facing labels."""
    key = str(option or "").strip().lower()
    return _STATUS_LABELS.get(key, (key.title() if key else "Status"))


def format_trend_label(status_bucket: str) -> str:
    """Format internal trend buckets into concise display labels."""
    key = str(status_bucket or "").strip().lower()
    if key == "needs attention":
        return "Needs review"
    if key == "improved recently":
        return "Improving"
    return "Holding steady"


def format_page_hero_caption() -> str:
    """Describe Team role with clear Team vs Today split."""
    return "Review recent performance, follow-up timing, and history for each employee."


def format_roster_helper_text() -> str:
    """Small helper caption above roster picker."""
    return "Showing employees that match the current filters"


def format_roster_count(count: int) -> str:
    """Format roster count in a short, scanable form."""
    return f"{max(0, int(count))} employees"


def format_bridge_helper() -> str:
    """Explain Team-to-Today bridge without directive tone."""
    return "Today shows active follow-up cards for this employee"


def format_bridge_button_label() -> str:
    """Return compact Team-to-Today bridge button text."""
    return "-> Today"


def format_chip_current_vs_target(value_text: str) -> str:
    """Format current-vs-target chip label and value."""
    return f"Performance vs target: {str(value_text or '').strip()}"


def format_chip_trend(value_text: str) -> str:
    """Format trend chip label and value."""
    return f"Recent direction: {str(value_text or '').strip()}"


def format_chip_notes(note_count: int) -> str:
    """Format notes chip in a short scanable form."""
    count = max(0, int(note_count or 0))
    if count <= 0:
        return "Notes: none"
    return f"Notes: {count} recent"


def format_chip_follow_up(value_text: str) -> str:
    """Format follow-up chip label and value."""
    return f"Follow-up: {str(value_text or '').strip()}"


def format_timeline_row_heading(when_text: str, event_type: str) -> str:
    """Format timeline row heading consistently."""
    when_clean = str(when_text or "").strip() or format_empty_state("unknown_time")
    event_clean = str(event_type or "").strip() or "Update"
    return f"**{when_clean}** | {event_clean}"


def format_current_vs_target(avg_uph: float | None, target_uph: float | None) -> str:
    """Format output-vs-target chip text."""
    if avg_uph is None and target_uph is None:
        return "Performance and target are not available yet"
    if avg_uph is None:
        return f"Target: {target_uph:.1f} UPH" if target_uph is not None else "Performance and target are not available yet"
    if target_uph is None:
        return f"Recent output: {avg_uph:.1f} UPH"
    return f"{avg_uph:.1f} vs {target_uph:.1f} UPH"


def format_window_trend(change_pct: float | None, days: int) -> str:
    """Format trend chip text using plain language."""
    safe_days = max(1, int(days or 1))
    if change_pct is None:
        return f"Not enough data to show a {safe_days}-day direction"

    if abs(change_pct) < 1.0:
        return f"Holding steady over the last {safe_days} days"

    if change_pct > 0:
        if abs(change_pct) >= 3.0:
            return f"Improving over the last {safe_days} days ({change_pct:+.1f}%)"
        return f"Improving over the last {safe_days} days"

    if abs(change_pct) >= 3.0:
        return f"Slipping over the last {safe_days} days ({change_pct:+.1f}%)"
    return f"Slipping over the last {safe_days} days"


def format_follow_up_summary_overdue(due_iso: str) -> str:
    """Format follow-up summary for overdue timing."""
    return f"Follow-up overdue since {due_iso}."


def format_follow_up_summary_pending(due_iso: str) -> str:
    """Format follow-up summary for pending timing."""
    return f"Follow-up pending (due {due_iso})."


def format_follow_up_summary_pending_no_date() -> str:
    """Format follow-up summary when due date is not available."""
    return "Follow-up pending."


def format_follow_up_summary_recent(recent_iso: str) -> str:
    """Format follow-up summary for recent activity."""
    return f"Recent follow-up activity on {recent_iso}."


def format_follow_up_roster_overdue(due_iso: str) -> str:
    """Format compact roster follow-up tag for overdue status."""
    return f"Follow-up overdue ({due_iso})"


def format_follow_up_roster_pending(due_iso: str) -> str:
    """Format compact roster follow-up tag for pending status."""
    return f"Follow-up pending ({due_iso})"


def format_follow_up_roster_pending_no_date() -> str:
    """Format compact roster follow-up tag without due date."""
    return "Follow-up pending"


def format_follow_up_roster_recent(recent_iso: str) -> str:
    """Format compact roster follow-up tag for recent activity."""
    return f"Recent follow-up ({recent_iso})"


def format_follow_up_unavailable() -> str:
    """Format fallback text when follow-up timing is missing."""
    return "Follow-up timing is not available yet"


def format_roster_reason_change_down(change_pct: float) -> str:
    """Format roster reason for negative change percent."""
    return f"Below recent pattern ({abs(change_pct):.1f}% lower)"


def format_roster_reason_change_up(change_pct: float) -> str:
    """Format roster reason for positive change percent."""
    return f"Above recent pattern ({change_pct:.1f}% higher)"


def format_roster_reason_variable() -> str:
    """Format roster reason for variable trend."""
    return "Recent pattern varies day to day"


def format_roster_reason_improving() -> str:
    """Format roster reason for improving trend."""
    return "Recent pattern is improving"


def format_roster_reason_below_baseline() -> str:
    """Format roster reason for below-baseline trend."""
    return "Recent pattern is below usual level"


def format_roster_reason_stable() -> str:
    """Format roster reason for stable trend."""
    return "Recent pattern is steady"


def format_confidence_meta(confidence: str) -> str:
    """Format confidence metadata chip text."""
    return f"Data confidence: {confidence}"


def format_data_completeness_meta(status: str) -> str:
    """Format data completeness metadata chip text."""
    return f"Data coverage: {status}"


def format_selected_employee_subheader(department: str, trend_label: str) -> str:
    """Format selected employee subheader line."""
    return f"{department} | {trend_label}"


def format_selected_summary(*, status_bucket: str, trend_text: str, note_count: int, follow_up_text: str, target_uph: float | None) -> str:
    """Build selected-employee summary sentence using descriptive tone."""
    normalized = str(status_bucket or "").strip().lower()
    base = "Recent performance is steady."
    if normalized == "needs attention":
        base = "Recent performance is below target." if target_uph is not None else "Recent performance needs review."
    elif normalized == "improved recently":
        base = "Recent performance is improving."

    if note_count <= 0:
        note_part = "No recent notes."
    elif note_count == 1:
        note_part = "1 recent note."
    else:
        note_part = f"{note_count} recent notes."

    follow_up_part = str(follow_up_text or "").strip()
    return " ".join(part for part in [base, f"{trend_text}.", note_part, follow_up_part] if part).strip()


def format_trend_intro(days: int) -> str:
    """Format trend section intro line."""
    safe_days = max(1, int(days or 1))
    return f"Daily performance for the last {safe_days} days."


def format_trend_no_points() -> str:
    """Format trend empty-state message when chart rows are empty."""
    return format_empty_state("no_trend_points")


def format_trend_no_history() -> str:
    """Format trend empty-state message when no history rows exist."""
    return format_empty_state("no_history_points")


def format_trend_interpretation_no_days() -> str:
    """Format trend interpretation when zero days are available."""
    return "No daily performance records in this time range yet."


def format_trend_interpretation_limited_days(observed_days: int) -> str:
    """Format trend interpretation for low-confidence sample sizes."""
    return f"Only {max(0, int(observed_days))} day(s) are available, so this direction may change."


def format_trend_interpretation_improving_but_below_target(*, below_count: int, observed_days: int) -> str:
    """Format interpretation for improving-but-below-target pattern."""
    return f"Performance is improving, but stayed below target on {below_count} of the last {observed_days} days."


def format_trend_interpretation_recent_dip() -> str:
    """Format interpretation for short recent dip signal."""
    return "Performance dipped in the last 2 days."


def format_trend_interpretation_below_target(*, below_count: int, observed_days: int) -> str:
    """Format interpretation for sustained below-target pattern."""
    return f"Performance stayed below target on {below_count} of the last {observed_days} days."


def format_trend_interpretation_above_target_and_improving() -> str:
    """Format interpretation for above-target improving trend."""
    return "Performance is above target and still improving."


def format_trend_interpretation_above_target_softening() -> str:
    """Format interpretation for above-target but declining trend."""
    return "Performance is above target, but momentum has softened."


def format_trend_interpretation_near_or_above_target() -> str:
    """Format interpretation for stable near/above-target trend."""
    return "Performance stayed near or above target in this time range."


def format_trend_interpretation_improving() -> str:
    """Format interpretation for non-target improving trend."""
    return "Performance is improving in this time range."


def format_trend_interpretation_declining() -> str:
    """Format interpretation for non-target declining trend."""
    return "Performance is slipping in this time range."


def format_trend_interpretation_stable() -> str:
    """Format interpretation for non-target stable trend."""
    return "Performance is mostly steady in this time range."


def format_timeline_event(event_type: str, *, status: str = "", action_id: str = "") -> str:
    """Map raw event types to concise operational labels.

    Mapping reference for future event types:
    - Follow-up lifecycle: follow_up_logged, follow_through_logged, resolved
    - Coaching/recognition: coached, recognized
    - Priority/escalation: escalated, reopened, deprioritized
    - Signal/status updates: today_signal_status_set
    Unknown values fall back to neutral wording to preserve trust.
    """
    raw = str(event_type or "").strip().lower()
    status_raw = str(status or "").strip().lower()

    event_labels = {
        "follow_up_logged": "Follow-up created",
        "follow_through_logged": "Follow-up created",
        "coached": "Coaching note added",
        "recognized": "Recognition shared",
        "escalated": "Escalation opened",
        "reopened": "Escalation reopened",
        "deprioritized": "Priority lowered",
        "today_signal_status_set": "Status updated",
        "exception_opened": "Exception opened",
        "resolved": "Follow-up completed",
        "created": "Update added",
    }

    if raw in {"resolved"} or status_raw in {"done", "resolved", "completed"}:
        return "Follow-up completed" if str(action_id or "").strip() else "Completed"

    if raw in event_labels:
        return event_labels[raw]
    return "Update added"


def format_timeline_description_fallback(source: str) -> str:
    """Provide plain fallback description for timeline rows."""
    _ = str(source or "").strip().lower()
    return ""


def format_timeline_description(
    *,
    source: str,
    event_label: str,
    raw_description: str,
    event_type: str = "",
) -> str:
    """Normalize optional timeline detail text.

    Keeps details short and useful. Avoids duplicate noise when detail text
    just repeats the event label or raw system event type.
    """
    text = " ".join(str(raw_description or "").strip().split())
    if not text:
        return format_timeline_description_fallback(source)

    label_norm = str(event_label or "").strip().lower()
    text_norm = text.lower()
    raw_type_norm = str(event_type or "").strip().lower().replace("_", " ")
    if text_norm == label_norm:
        return ""
    if raw_type_norm and text_norm == raw_type_norm:
        return ""
    if text_norm in {"activity logged", "activity recorded", "recorded", "logged"}:
        return format_timeline_description_fallback(source)
    if text_norm in {"done", "resolved", "completed", "open", "closed"}:
        return ""
    return text


def format_timeline_entry(
    *,
    source: str,
    event_type: str,
    status: str = "",
    action_id: str = "",
    raw_description: str = "",
) -> dict[str, str]:
    """Single formatting path for Team timeline rows.

    Returns:
    - label: primary event label
    - description: optional supporting detail (may be empty)
    """
    label = format_timeline_event(event_type, status=status, action_id=action_id)
    description = format_timeline_description(
        source=source,
        event_label=label,
        raw_description=raw_description,
        event_type=event_type,
    )
    return {"label": label, "description": description}


def format_timeline_when(dt: datetime | None, *, fallback: str = "") -> str:
    """Format timeline timestamp with a clear fallback."""
    if dt is None:
        return (str(fallback or "").strip()[:16] if str(fallback or "").strip() else format_empty_state("unknown_time"))
    return dt.strftime("%Y-%m-%d %H:%M")


def format_note_entry(when_text: str, *, author: str = "") -> str:
    """Format note row header for easy scanning."""
    when_clean = str(when_text or "").strip() or format_empty_state("unknown_time")
    author_clean = str(author or "").strip()
    return f"{when_clean} - {author_clean}" if author_clean else when_clean


def format_note_preview_text(preview_text: str) -> str:
    """Normalize note preview text for display."""
    return str(preview_text or "").strip()


def format_note_expand_label(index: int, *, when_text: str = "") -> str:
    """Format note expander label with semantic reference."""
    when_clean = str(when_text or "").strip()
    if when_clean:
        return f"Show full note from {when_clean[:10]}"
    return "Show full note"


def format_show_older_notes_label(remaining: int) -> str:
    """Format notes pagination expander label."""
    return f"Show older notes ({max(0, int(remaining or 0))})"


def format_exception_text(exception_type: str) -> str:
    """Format exception type into user-facing label."""
    text = str(exception_type or "").strip()
    return text if text else "Exception"


def format_exception_preview_text(preview_text: str) -> str:
    """Normalize exception preview text for display."""
    return str(preview_text or "").strip()


def format_exception_context_line(raw_context_line: str, *, fallback_when: str = "") -> str:
    """Convert raw exception context metadata into readable text."""
    raw = str(raw_context_line or "").strip()
    if not raw:
        return str(fallback_when or "").strip()
    if "|" not in raw:
        return raw
    parts = [part.strip() for part in raw.split("|") if part.strip()]
    return ", ".join(parts)


def format_exception_expand_label(index: int, *, when_text: str = "") -> str:
    """Format exception detail expander label with semantic reference."""
    when_clean = str(when_text or "").strip()
    if when_clean:
        return f"Show exception detail from {when_clean[:10]}"
    return "Show exception detail"


def format_show_older_exceptions_label(remaining: int) -> str:
    """Format exceptions pagination expander label."""
    return f"Show older exceptions ({max(0, int(remaining or 0))})"


def format_comparison_text(*, delta_pct: float, share_below_target: float | None = None) -> list[str]:
    """Format department comparison lines while preserving factual meaning."""
    if delta_pct <= -6.0:
        primary = f"Performance is below the department midpoint ({abs(delta_pct):.0f}% lower)."
    elif delta_pct >= 6.0:
        primary = f"Performance is above the department midpoint ({abs(delta_pct):.0f}% higher)."
    else:
        primary = "Performance is in line with the department midpoint."

    secondary = ""
    if share_below_target is not None:
        if share_below_target >= 0.5:
            secondary = "This pattern appears across much of the department."
        elif share_below_target <= 0.2:
            secondary = "Most of the department is at or above target."

    return [line for line in [primary, secondary] if line]


def format_empty_state(kind: str, **kwargs: object) -> str:
    """Return centralized empty-state wording for Team surfaces."""
    key = str(kind or "").strip().lower()
    if key == "no_team_records":
        return "No team records are available for this period yet."
    if key == "no_filter_match":
        return "No employees match these filters. Showing the full team list."
    if key == "no_selectable_roster":
        return "No employee records are available to review right now."
    if key == "no_trend_points":
        return "This time range has too little daily detail to draw a trend line."
    if key == "no_history_points":
        return "No performance history is available in this time range."
    if key == "no_timeline":
        return "No recent timeline updates for this employee."
    if key == "no_notes":
        return "No notes for this employee yet."
    if key == "no_exceptions":
        return "No recent exceptions are recorded for this employee."
    if key == "unknown_date":
        return "Date not available"
    if key == "unknown_time":
        return "Time not available"
    return "Nothing to show here yet."


def format_status_summary_line(*, trend_state: str, goal_state: str) -> str:
    """Format compact status summary under chip row."""
    trend_clean = str(trend_state or "").strip()
    goal_clean = str(goal_state or "").strip()
    return f"Direction: {trend_clean} | Target: {goal_clean}"


def format_comparison_section_title() -> str:
    """Return comparison section title."""
    return _SECTION_TITLES["comparison"]
