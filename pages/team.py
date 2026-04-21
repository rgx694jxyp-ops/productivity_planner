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
    format_status_summary_line,
    format_timeline_description_fallback,
    format_timeline_entry,
    format_timeline_when,
    format_trend_intro,
    format_trend_interpretation_above_target_and_improving,
    format_trend_interpretation_above_target_softening,
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
    format_window_trend,
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
)


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _selected_window_trend_text(row: dict, time_window_days: int) -> str:
    change_pct = _safe_float(row.get("change_pct"))
    return format_window_trend(change_pct, time_window_days)


def _open_follow_up_state_text(row: dict) -> str:
    follow_up_context = _snapshot_follow_up_context(row)
    if follow_up_context:
        return str(follow_up_context.get("summary") or "").strip()
    return format_follow_up_unavailable()


def _selected_employee_summary_sentence(
    *,
    status_bucket: str,
    trend_text: str,
    note_count: int,
    follow_up_text: str,
    target_uph: float | None,
) -> str:
    return format_selected_summary(
        status_bucket=status_bucket,
        trend_text=trend_text,
        note_count=note_count,
        follow_up_text=follow_up_text,
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
                )
            if observed_days >= 5:
                prior_values = uph_values[:-2]
                recent_values = uph_values[-2:]
                if prior_values and (sum(recent_values) / len(recent_values)) < (sum(prior_values) / len(prior_values)):
                    return format_trend_interpretation_recent_dip()
            return format_trend_interpretation_below_target(
                below_count=below_count,
                observed_days=observed_days,
            )
        if change_pct >= 3.0:
            return format_trend_interpretation_above_target_and_improving()
        if change_pct <= -3.0:
            return format_trend_interpretation_above_target_softening()
        return format_trend_interpretation_near_or_above_target()

    if change_pct >= 3.0:
        return format_trend_interpretation_improving()
    if change_pct <= -3.0:
        return format_trend_interpretation_declining()
    return format_trend_interpretation_stable()


def _timeline_when_text(dt: datetime | None, fallback: str = "") -> str:
    return format_timeline_when(dt, fallback=fallback)


def _normalize_recent_activity_timeline(
    *,
    notes: list[dict],
    action_rows: list[dict],
    exception_rows: list[dict],
    limit: int = 40,
) -> list[dict]:
    events: list[dict] = []

    for row in notes or []:
        event_at_raw = str(row.get("created_at") or row.get("date") or "").strip()
        event_at = _parse_dt(event_at_raw)
        entry = format_timeline_entry(
            source="note",
            event_type="coached",
            raw_description=_compact_text(row.get("note") or row.get("notes") or "", max_len=140),
        )
        events.append(
            {
                "event_at": event_at,
                "event_at_raw": event_at_raw,
                "event_type": entry["label"],
                "description": entry["description"],
                "source": "note",
                "dedupe_key": f"note|{event_at_raw}|{entry['description'].lower()}",
            }
        )

    for row in action_rows or []:
        event_at_raw = str(row.get("event_at") or "").strip()
        event_at = _parse_dt(event_at_raw)
        action_id = str(row.get("action_id") or "").strip()
        raw_event_type = str(row.get("event_type") or "").strip().lower()
        raw_status = str(row.get("status") or "").strip().lower()
        entry = format_timeline_entry(
            source="action_event",
            event_type=raw_event_type,
            status=raw_status,
            action_id=action_id,
            raw_description=_compact_text(
                row.get("notes")
                or row.get("outcome")
                or row.get("trigger_summary")
                or row.get("status")
                or format_timeline_description_fallback("action_event"),
                max_len=140,
            ),
        )
        events.append(
            {
                "event_at": event_at,
                "event_at_raw": event_at_raw,
                "event_type": entry["label"],
                "description": entry["description"],
                "source": "action_event",
                "dedupe_key": f"action|{action_id}|{raw_event_type}|{event_at_raw}|{entry['description'].lower()}",
            }
        )

    for row in exception_rows or []:
        event_at_raw = str(row.get("created_at") or row.get("exception_date") or "").strip()
        event_at = _parse_dt(event_at_raw)
        resolved_at = str(row.get("resolved_at") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        entry = format_timeline_entry(
            source="exception",
            event_type=("resolved" if (resolved_at or status == "resolved") else "exception_opened"),
            status=status,
            raw_description=_compact_text(
                row.get("summary") or row.get("notes") or row.get("category") or format_timeline_description_fallback("exception"),
                max_len=140,
            ),
        )
        exception_id = str(row.get("id") or "").strip()
        events.append(
            {
                "event_at": event_at,
                "event_at_raw": event_at_raw,
                "event_type": entry["label"],
                "description": entry["description"],
                "source": "exception",
                "dedupe_key": f"exception|{exception_id}|{entry['label'].lower()}|{event_at_raw}|{entry['description'].lower()}",
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
            float(event["event_at"].timestamp()) if isinstance(event.get("event_at"), datetime) else float("-inf"),
            str(event.get("event_at_raw") or ""),
        ),
        reverse=True,
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
    return " ".join(str(note.get("note") or note.get("notes") or "").split()).strip()


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
    author_text = str(note_row.get("author") or "").strip()
    metadata_text = format_note_entry(str(note_row.get("when_text") or ""), author=author_text)
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
    context_text = context_line if context_line and context_line != exception_type else when_text
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
        .team-section-anchor {
            height: 0;
            margin: 0;
            padding: 0;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor) {
            margin-top: 1.125rem;
            padding: 0.75rem 0.82rem;
            border: 1px solid #E8EEF7;
            border-radius: 0.62rem;
            background: #FCFDFF;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--summary) {
            margin-top: 0.25rem;
            padding-top: 0.75rem;
            padding-bottom: 0.75rem;
            background: #FBFDFF;
            border-color: #E5ECF6;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--comparison) {
            background: #FEFFFF;
            border-color: #EBF1F8;
            padding-top: 0.625rem;
            padding-bottom: 0.75rem;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor) h4 {
            font-size: 0.97rem;
            font-weight: 600;
            letter-spacing: 0.01em;
            margin: 0 0 0.25rem 0;
        }
        div[data-testid="stVerticalBlock"]:has(.team-section-anchor--summary) h3 {
            font-size: 1.18rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            margin: 0 0 0.25rem 0;
        }
        .team-section-divider {
            margin: 0.5rem 0 0.25rem 0;
            border-top: 1px solid #EDF2F8;
            height: 0;
        }
        .team-summary-primary {
            font-size: 1.04rem;
            font-weight: 600;
            color: var(--dpd-navy-900);
            line-height: 1.38;
            margin: 0.125rem 0 0.25rem 0;
        }
        .team-summary-secondary {
            font-size: 0.91rem;
            font-weight: 400;
            line-height: 1.42;
            margin: 0 0 0.125rem 0;
            color: var(--dpd-text);
        }
        .team-trend-primary {
            font-size: 0.96rem;
            font-weight: 600;
            color: var(--dpd-navy-900);
            line-height: 1.38;
            margin: 0.125rem 0 0.25rem 0;
        }
        .team-timeline-entry {
            padding: 0.5rem 0;
            border-bottom: 1px solid #ECF1F8;
        }
        .team-timeline-entry:last-child {
            border-bottom: 0;
        }
        .team-timeline-event {
            font-size: 0.92rem;
            font-weight: 500;
            color: var(--dpd-navy-900);
            margin: 0 0 0.125rem 0;
            line-height: 1.35;
        }
        .team-timeline-meta {
            font-size: 0.78rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
        }
        .team-timeline-detail {
            font-size: 0.86rem;
            color: var(--dpd-text);
            margin: 0.125rem 0 0 0;
            line-height: 1.42;
        }
        .team-notes-entry {
            padding: 0.5rem 0;
            border-bottom: 1px solid #ECF1F8;
        }
        .team-notes-entry:last-child {
            border-bottom: 0;
        }
        .team-notes-body {
            font-size: 0.91rem;
            font-weight: 400;
            color: var(--dpd-text);
            margin: 0 0 0.125rem 0;
            line-height: 1.42;
        }
        .team-notes-meta {
            font-size: 0.78rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
        }
        .team-exceptions-entry {
            padding: 0.5rem 0;
            border-bottom: 1px solid #ECF1F8;
        }
        .team-exceptions-entry:last-child {
            border-bottom: 0;
        }
        .team-exceptions-primary {
            font-size: 0.91rem;
            font-weight: 500;
            color: var(--dpd-navy-900);
            margin: 0 0 0.125rem 0;
            line-height: 1.35;
        }
        .team-exceptions-meta {
            font-size: 0.78rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
        }
        .team-exceptions-support {
            font-size: 0.86rem;
            color: var(--dpd-text);
            margin: 0.125rem 0 0 0;
            line-height: 1.42;
        }
        .team-comparison-primary {
            font-size: 0.89rem;
            font-weight: 500;
            color: var(--dpd-navy-900);
            margin: 0.125rem 0;
            line-height: 1.35;
        }
        .team-comparison-support {
            font-size: 0.79rem;
            color: var(--dpd-text-muted);
            margin: 0;
            line-height: 1.28;
        }
        .team-section-intent {
            font-size: 0.74rem;
            font-weight: 400;
            color: var(--dpd-text-muted);
            opacity: 0.82;
            margin: 0 0 0.375rem 0;
            line-height: 1.2;
            letter-spacing: 0.02em;
            text-transform: lowercase;
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

    requested_employee_id = str(
        st.session_state.get("team_selected_emp_id")
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
        trend_state = str(selected_row.get("trend") or "stable").replace("_", " ").title()
        goal_state = str(selected_row.get("goal_status") or "unknown").replace("_", " ").title()
        status_bucket = _team_status_bucket(selected_row)
        status_label = format_trend_label(status_bucket)

        with profile.stage("load_selected_employee_detail"):
            notes = list(_cached_coaching_notes_for(employee_id) or [])
            timeline_rows = list(get_employee_action_timeline(employee_id, tenant_id=tenant_id) or [])[:60]
            exceptions = list_recent_operational_exceptions(tenant_id=tenant_id, employee_id=employee_id, limit=25)
        profile.set("selected_employee_id", employee_id)
        profile.set("notes_rows", len(notes))
        profile.set("timeline_rows", len(timeline_rows))
        profile.set("exception_rows", len(exceptions or []))
        profile.query(rows=len(notes) + len(timeline_rows) + len(exceptions or []), count=3)

        note_count = len(notes)
        unified_timeline = _normalize_recent_activity_timeline(
            notes=notes,
            action_rows=timeline_rows,
            exception_rows=exceptions,
            limit=40,
        )
        current_vs_target_text = _current_vs_target_text(avg_uph, target_uph)
        selected_window_trend_text = _selected_window_trend_text(selected_row, time_window_days)
        follow_up_state_text = _open_follow_up_state_text(selected_row)
        summary_sentence = _selected_employee_summary_sentence(
            status_bucket=status_bucket,
            trend_text=selected_window_trend_text,
            note_count=note_count,
            follow_up_text=follow_up_state_text,
            target_uph=target_uph,
        )
        primary_summary_line = _primary_summary_line(summary_sentence)
        secondary_summary_line = format_status_summary_line(trend_state=trend_state, goal_state=goal_state)

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

        with shell_right:
            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--summary'></div>", unsafe_allow_html=True)
                st.markdown(f"### {employee_name}")
                if primary_summary_line:
                    st.markdown(f"<div class='team-summary-primary'>{primary_summary_line}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='team-summary-secondary'>{secondary_summary_line}</div>", unsafe_allow_html=True)
                metadata_line = " | ".join(
                    [
                        format_chip_current_vs_target(current_vs_target_text),
                        format_chip_trend(selected_window_trend_text),
                        format_chip_notes(note_count),
                        format_chip_follow_up(follow_up_state_text),
                    ]
                )
                selected_support = _compact_support_line(
                    format_selected_employee_subheader(department, status_label),
                    metadata_line,
                )
                if selected_support:
                    st.caption(selected_support)

                # Bridge to Today: subtle control to pass employee context and navigate.
                bridge_col_1, bridge_col_2 = st.columns([0.5, 3.0], gap="small")
                with bridge_col_1:
                    if st.button(format_bridge_button_label(), key=f"team_bridge_to_today_{selected_employee_id}"):
                        if selected_employee_id and str(selected_employee_id).strip():
                            st.session_state["cn_selected_emp"] = selected_employee_id
                            st.session_state["goto_page"] = "today"
                            st.rerun()
                with bridge_col_2:
                    st.caption(format_bridge_helper())

                st.markdown("<div class='team-section-divider'></div>", unsafe_allow_html=True)

            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--trend'></div>", unsafe_allow_html=True)
                st.markdown(f"#### {section_titles['trend']}")
                st.markdown("<div class='team-section-intent'>recent direction</div>", unsafe_allow_html=True)
            window_start: datetime | None = None
            if time_window_days > 0:
                window_start = datetime.utcnow() - timedelta(days=time_window_days)

            employee_history = []
            for row in employee_snapshot_history:
                row_dt = _parse_dt(str(row.get("snapshot_date") or "").strip())
                if window_start is not None and row_dt is not None and row_dt < window_start:
                    continue
                employee_history.append(row)

            if employee_history:
                with profile.stage("build_selected_trend_chart"):
                    chart_rows: list[dict] = []
                    for row in employee_history:
                        dt_value = _parse_dt(str(row.get("snapshot_date") or "").strip())
                        if dt_value is None:
                            continue
                        uph = _safe_float(row.get("performance_uph"))
                        if uph is None:
                            continue
                        chart_rows.append({"Date": dt_value.date().isoformat(), "UPH": uph})
                profile.set("chart_rows", len(chart_rows))

                if chart_rows:
                    trend_primary_text = selected_window_trend_text
                    trend_support_parts: list[str] = []
                    trend_intro_text = format_trend_intro(time_window_days)

                    interpretation = _trend_interpretation_sentence(chart_rows, target_uph)
                    interpretation_clean = str(interpretation or "").strip()
                    primary_clean = str(trend_primary_text or "").strip()
                    if interpretation_clean and interpretation_clean.lower() != primary_clean.lower():
                        trend_support_parts.append(interpretation_clean)
                    if trend_intro_text:
                        trend_support_parts.append(trend_intro_text)

                    if primary_clean:
                        st.markdown(f"<div class='team-trend-primary'>{primary_clean}</div>", unsafe_allow_html=True)
                    if trend_support_parts:
                        st.caption(" | ".join(trend_support_parts), help=None)

                    # Single analytical chart for selected-employee trend in the selected window.
                    history_df = pd.DataFrame(chart_rows).drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
                    if target_uph is not None and target_uph > 0:
                        history_df["Target"] = float(target_uph)
                        st.line_chart(history_df.set_index("Date")[["UPH", "Target"]], use_container_width=True)
                    else:
                        st.line_chart(history_df.set_index("Date")["UPH"], use_container_width=True)
                else:
                    st.markdown(f"<div class='team-trend-primary'>{format_trend_no_points()}</div>", unsafe_allow_html=True)
                    st.caption(format_trend_intro(time_window_days))
            else:
                st.markdown(f"<div class='team-trend-primary'>{format_trend_no_history()}</div>", unsafe_allow_html=True)
                st.caption(format_trend_intro(time_window_days))

            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--timeline'></div>", unsafe_allow_html=True)
                st.markdown(f"#### {section_titles['timeline']}")
                st.markdown("<div class='team-section-intent'>recent activity</div>", unsafe_allow_html=True)
                if not unified_timeline:
                    st.caption(format_empty_state("no_timeline"))
                else:
                    for event in unified_timeline:
                        when_text = _timeline_when_text(event.get("event_at"), fallback=str(event.get("event_at_raw") or ""))
                        event_type = str(event.get("event_type") or format_timeline_description_fallback("action_event"))
                        description = str(event.get("description") or "")
                        detail_html = ""
                        if description:
                            detail_html = f"<div class='team-timeline-detail'>{escape(description)}</div>"
                        st.markdown(
                            "\n".join(
                                [
                                    "<div class='team-timeline-entry'>",
                                    f"<div class='team-timeline-event'>{escape(event_type)}</div>",
                                    f"<div class='team-timeline-meta'>{escape(when_text)}</div>",
                                    detail_html,
                                    "</div>",
                                ]
                            ),
                            unsafe_allow_html=True,
                        )

            with st.container():
                st.markdown("<div class='team-section-anchor team-section-anchor--notes'></div>", unsafe_allow_html=True)
                st.markdown(f"#### {section_titles['notes']}")
                st.markdown("<div class='team-section-intent'>follow-up history</div>", unsafe_allow_html=True)
                # TODO(team-contract): Notes history section - prior notes for selected employee.
                note_history = _normalize_notes_history(notes, preview_chars=180)
                if not note_history:
                    st.caption(format_empty_state("no_notes"))
                else:
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
                # TODO(team-contract): Exception history section - read-only context for selected employee.
                exception_history = _normalize_exception_history(exceptions, preview_chars=140)
                if not exception_history:
                    st.caption(format_empty_state("no_exceptions"))
                else:
                    visible_count = 6
                    for index, exception_row in enumerate(exception_history[:visible_count], start=1):
                        _render_exception_history_entry(exception_row, index=index)

                    remaining_count = len(exception_history) - visible_count
                    if remaining_count > 0:
                        with st.expander(format_show_older_exceptions_label(remaining_count), expanded=False):
                            for index, exception_row in enumerate(exception_history[visible_count:], start=visible_count + 1):
                                _render_exception_history_entry(exception_row, index=index)

            comparison_text = _department_comparison_context(
                goal_status_rows=goal_status,
                selected_row=selected_row,
                department=department,
            )
            if comparison_text:
                with st.container():
                    st.markdown("<div class='team-section-anchor team-section-anchor--comparison'></div>", unsafe_allow_html=True)
                    st.markdown(f"#### {format_comparison_section_title()}")
                    comparison_primary, comparison_support = _split_primary_support_text(comparison_text)
                    if comparison_primary:
                        st.markdown(f"<div class='team-comparison-primary'>{escape(comparison_primary)}</div>", unsafe_allow_html=True)
                    if comparison_support:
                        st.markdown(f"<div class='team-comparison-support'>{escape(comparison_support)}</div>", unsafe_allow_html=True)

    # TODO(team-contract): Optional comparison context section - only if it remains lightweight and non-prescriptive.
