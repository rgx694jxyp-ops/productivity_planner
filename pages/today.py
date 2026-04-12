"""Today page.

Queue-first supervisor workflow focused on daily follow-through.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from core.dependencies import _cached_employees, _log_app_error
from domain.display_signal import DisplaySignal, SignalLabel
from domain.insight_card_contract import InsightCardContract
from domain.operational_exceptions import EXCEPTION_CATEGORIES
from services.action_metrics_service import _recent_action_outcomes, get_manager_outcome_stats
from services.exception_tracking_service import (
    build_exception_context_line,
    create_operational_exception,
    resolve_operational_exception,
    summarize_open_operational_exceptions,
)
from services.attention_scoring_service import AttentionSummary
from services.display_signal_factory import build_display_signal_from_attention_item, build_display_signal_from_insight_card
from services.follow_through_service import FOLLOW_THROUGH_STATUSES, log_follow_through_event
from services.signal_formatting_service import (
    format_comparison_line,
    format_confidence_line,
    format_observed_line,
    format_signal_label,
    get_signal_display_mode,
    is_signal_display_eligible,
    SignalDisplayMode,
)
from services.today_home_service import get_today_signals
from services.signal_traceability_service import traceability_payload_from_card
from ui.state_panels import (
    show_error_state,
    show_healthy_state,
    show_loading_state,
    show_low_confidence_state,
    show_no_data_state,
    show_partial_data_state,
    show_success_state,
)
from ui.traceability_panel import render_traceability_panel
from ui.today_queue import render_action_queue


_READ_CACHE_TTL_SECONDS = 45


def _log_heavy_render_compute(name: str) -> None:
    if not bool(st.session_state.get("_ui_render_guard_active")):
        return
    try:
        _log_app_error(
            "ui_render_guard",
            f"Heavy compute executed during render cache miss: {name}",
            severity="warning",
        )
    except Exception:
        pass


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_recent_action_outcomes(*, tenant_id: str, lookback_days: int) -> list[dict[str, Any]]:
    _log_heavy_render_compute("_recent_action_outcomes")
    return list(_recent_action_outcomes(lookback_days=lookback_days, tenant_id=tenant_id) or [])


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_manager_outcome_stats(*, tenant_id: str, lookback_days: int, today_iso: str) -> dict[str, Any]:
    _log_heavy_render_compute("get_manager_outcome_stats")
    try:
        today_value = date.fromisoformat(str(today_iso or "")[:10])
    except Exception:
        today_value = date.today()
    return dict(get_manager_outcome_stats(tenant_id=tenant_id, lookback_days=lookback_days, today=today_value) or {})


def _apply_today_styles() -> None:
    st.markdown(
        """
        <style>
        .today-hero {
            background: linear-gradient(135deg, #0f2d52 0%, #1f4f87 65%, #d9e8f7 180%);
            border-radius: 18px;
            padding: 22px 24px;
            margin-bottom: 18px;
            color: #ffffff;
            box-shadow: 0 14px 34px rgba(15, 45, 82, 0.16);
        }
        .today-hero-kicker {
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            opacity: 0.78;
            margin-bottom: 6px;
        }
        .today-hero-title {
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.08;
            margin: 0;
        }
        .today-hero-copy {
            margin-top: 8px;
            max-width: 760px;
            font-size: 0.98rem;
            line-height: 1.45;
            color: rgba(255, 255, 255, 0.88);
        }
        .today-section-label {
            display: inline-block;
            margin-bottom: 8px;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #5d7693;
        }
        .today-home-section {
            margin-top: 12px;
            margin-bottom: 10px;
        }
        .today-home-title {
            font-size: 1.12rem;
            font-weight: 800;
            color: #0f2d52;
            margin-bottom: 4px;
        }
        .today-home-desc {
            color: #5d7693;
            font-size: 0.92rem;
            margin-bottom: 10px;
        }
        .today-insight-title {
            font-size: 1rem;
            font-weight: 800;
            color: #0f2d52;
            margin-bottom: 4px;
        }
        .today-insight-line {
            color: #182b40;
            font-size: 0.93rem;
            line-height: 1.38;
            margin: 3px 0;
        }
        .today-insight-meta {
            color: #5d7693;
            font-size: 0.83rem;
            margin-top: 7px;
        }
        .today-placeholder {
            background: #f8fbff;
            border: 1px dashed #c9d9ea;
            border-radius: 12px;
            padding: 10px 12px;
            color: #335a80;
            font-size: 0.9rem;
        }
        .today-supporting-note {
            margin-top: -2px;
            margin-bottom: 10px;
            color: #5d7693;
            font-size: 0.92rem;
        }
        .today-summary-title {
            font-size: 0.88rem;
            font-weight: 700;
            color: #0f2d52;
            margin-bottom: 2px;
        }
        .today-summary-subtitle {
            font-size: 0.82rem;
            color: #5d7693;
            margin-bottom: 8px;
        }
        .attention-item-high {
            border-left: 4px solid #c0392b;
            padding-left: 10px;
            margin-bottom: 4px;
        }
        .attention-item-medium {
            border-left: 4px solid #e67e22;
            padding-left: 10px;
            margin-bottom: 4px;
        }
        .attention-item-low {
            border-left: 4px solid #7f8c8d;
            padding-left: 10px;
            margin-bottom: 4px;
        }
        .attention-score-badge {
            display: inline-block;
            font-size: 0.78rem;
            font-weight: 700;
            padding: 1px 8px;
            border-radius: 10px;
            margin-right: 6px;
        }
        .attention-score-high  { background: #fdecea; color: #c0392b; }
        .attention-score-medium { background: #fef5e7; color: #e67e22; }
        .attention-score-low   { background: #f0f0f0; color: #555; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _show_flash_message() -> None:
    message = str(st.session_state.pop("today_flash_message", "") or "")
    if message:
        show_success_state(message)


def _compute_data_state_flags(goal_status: list[dict], import_summary: dict, home_sections: dict[str, list[InsightCardContract]]) -> dict[str, bool]:
    days = int(import_summary.get("days") or 0)
    has_goal_data = bool(goal_status)
    below_goal_count = sum(1 for row in goal_status if str(row.get("goal_status") or "") == "below_goal")
    low_conf_cards = [
        card
        for section_cards in (home_sections or {}).values()
        for card in section_cards
        if str(card.confidence.level or "") == "low"
    ]
    partial_rows = [row for row in goal_status if str(row.get("trend") or "") == "insufficient_data"]

    return {
        "no_data": not has_goal_data and days == 0,
        "partial_data": bool(partial_rows) or (0 < days < 3),
        "low_confidence": bool(low_conf_cards),
        "healthy": has_goal_data and below_goal_count == 0,
    }


def _queue_counts(queue_items: list[dict]) -> dict[str, int]:
    counts = {
        "all": len(queue_items),
        "overdue": 0,
        "due_today": 0,
        "repeat": 0,
        "recognition": 0,
    }
    for item in queue_items:
        status = str(item.get("_queue_status") or "pending")
        if status == "overdue":
            counts["overdue"] += 1
        if status == "due_today":
            counts["due_today"] += 1
        if item.get("_is_repeat_issue"):
            counts["repeat"] += 1
        if item.get("_is_recognition_opportunity"):
            counts["recognition"] += 1
    return counts


def _filter_queue(queue_items: list[dict], active_filter: str) -> list[dict]:
    if active_filter == "overdue":
        return [item for item in queue_items if item.get("_queue_status") == "overdue"]
    if active_filter == "due_today":
        return [item for item in queue_items if item.get("_queue_status") == "due_today"]
    if active_filter == "repeat":
        return [item for item in queue_items if item.get("_is_repeat_issue")]
    if active_filter == "recognition":
        return [item for item in queue_items if item.get("_is_recognition_opportunity")]
    return queue_items


def _render_summary_strip(counts: dict[str, int], active_filter: str) -> None:
    strip_cols = st.columns(5)
    options = [
        ("all", "All queue", counts["all"]),
        ("overdue", "Overdue follow-ups", counts["overdue"]),
        ("due_today", "Due today", counts["due_today"]),
        ("repeat", "Repeat issues", counts["repeat"]),
        ("recognition", "Recognition opportunities", counts["recognition"]),
    ]

    for column, (filter_key, label, value) in zip(strip_cols, options):
        button_type = "primary" if active_filter == filter_key else "secondary"
        with column:
            if st.button(f"{value}\n{label}", key=f"today_filter_{filter_key}", use_container_width=True, type=button_type):
                st.session_state.today_queue_filter = filter_key
                st.rerun()


def _render_since_yesterday(queue_items: list[dict], recent_outcomes: list[dict]) -> None:
    st.markdown("#### Since yesterday")
    improved_count = sum(1 for item in recent_outcomes if str(item.get("outcome") or "") == "Improved")
    no_change_count = sum(1 for item in recent_outcomes if str(item.get("outcome") or "") == "No Change")
    worse_count = sum(1 for item in recent_outcomes if str(item.get("outcome") or "") == "Worse")
    overdue_count = sum(1 for item in queue_items if item.get("_queue_status") == "overdue")

    strip_cols = st.columns(4)
    with strip_cols[0]:
        st.metric("Improved", improved_count)
    with strip_cols[1]:
        st.metric("No change", no_change_count)
    with strip_cols[2]:
        st.metric("Worse", worse_count)
    with strip_cols[3]:
        st.metric("Still overdue", overdue_count)


def _render_empty_state() -> None:
    with st.container(border=True):
        st.markdown("### No urgent actions right now")
        st.write(
            "That means the queue is clear for the moment. This page becomes valuable when fresh productivity data "
            "turns into a short list of people who need a check-in, a follow-up, or recognition."
        )
        st.info("Import fresh data to refill the queue and surface who needs attention next.")


def _render_first_time_empty_state() -> None:
    """Onboarding-focused empty state for users who just completed first import."""
    with st.container(border=True):
        st.markdown("### Welcome! 🎉")
        st.markdown(
            "You've just imported your team data. The action queue starts filling up once you begin logging "
            "coaching conversations and follow-ups."
        )
        st.info("**Next step:** Go to **👥 Team** to see your employees, pick someone, and log your first coaching note.")
        if st.button("👥 View team →", type="primary", use_container_width=True, key="first_time_view_team"):
            st.session_state["goto_page"] = "team"
            st.rerun()


def _render_filtered_empty_state() -> None:
    with st.container(border=True):
        st.markdown("### Nothing matches this filter")
        st.write("The queue still has open work, but none of it fits the selected summary bucket.")
        if st.button("Show full queue", key="today_clear_filter_empty", type="primary"):
            st.session_state.today_queue_filter = "all"
            st.rerun()


def _render_bottom_charts(queue_items: list[dict], manager_stats: dict) -> None:
    st.markdown("#### Charts")
    chart_cols = st.columns(2)

    queue_chart = pd.DataFrame(
        {
            "items": [
                sum(1 for item in queue_items if item.get("_queue_status") == "overdue"),
                sum(1 for item in queue_items if item.get("_queue_status") == "due_today"),
                sum(1 for item in queue_items if item.get("_is_repeat_issue")),
                sum(1 for item in queue_items if item.get("_is_recognition_opportunity")),
                sum(
                    1
                    for item in queue_items
                    if item.get("_queue_status") not in {"overdue", "due_today"}
                    and not item.get("_is_repeat_issue")
                    and not item.get("_is_recognition_opportunity")
                ),
            ]
        },
        index=["Overdue", "Due today", "Repeat", "Recognition", "Other open"],
    )

    outcomes = manager_stats.get("outcomes", {}) or {}
    outcomes_chart = pd.DataFrame(
        {
            "events": [
                outcomes.get("improved", 0),
                outcomes.get("no_change", 0),
                outcomes.get("worse", 0),
                outcomes.get("blocked", 0),
                outcomes.get("not_applicable", 0),
            ]
        },
        index=["Improved", "No change", "Worse", "Blocked", "N/A"],
    )

    with chart_cols[0]:
        st.caption("Queue mix")
        st.bar_chart(queue_chart)

    with chart_cols[1]:
        st.caption("This week outcomes")
        st.bar_chart(outcomes_chart)


def _employee_option_map() -> tuple[list[str], dict[str, dict]]:
    options = ["Not linked to one employee"]
    option_map: dict[str, dict] = {"Not linked to one employee": {}}
    for employee in (_cached_employees() or []):
        label = f"{employee.get('name', employee.get('emp_id', 'Unknown'))} | {employee.get('department', '')} | {employee.get('emp_id', '')}"
        options.append(label)
        option_map[label] = employee
    return options, option_map


def _go_to_exception_employee(exception_row: dict) -> None:
    employee_id = str(exception_row.get("employee_id") or "")
    if not employee_id:
        return
    st.session_state["goto_page"] = "team"
    st.session_state["emp_view"] = "Performance Journal"
    st.session_state["cn_selected_emp"] = employee_id
    st.rerun()


def _render_exception_create_form(*, tenant_id: str, today_value: date) -> None:
    employee_options, employee_map = _employee_option_map()
    with st.expander("Log operational exception", expanded=False):
        st.caption("Capture context that may affect performance interpretation for today or a recent shift.")
        with st.form("today_operational_exception_form", clear_on_submit=True):
            selected_label = st.selectbox("Employee", employee_options, index=0)
            selected_employee = employee_map.get(selected_label, {})
            c1, c2, c3 = st.columns(3)
            with c1:
                exception_date = st.date_input("Date", value=today_value)
            with c2:
                category = st.selectbox("Category", EXCEPTION_CATEGORIES, index=EXCEPTION_CATEGORIES.index("unknown"))
            with c3:
                shift = st.text_input("Shift", value=str(selected_employee.get("shift", "") or ""))
            process_name = st.text_input("Process", value=str(selected_employee.get("department", "") or ""))
            summary = st.text_input("What happened", placeholder="Example: scanner outage slowed receiving lane")
            notes = st.text_area("Notes (optional)", value="")
            submitted = st.form_submit_button("Save exception", type="primary")
            if submitted:
                _user_role = str(st.session_state.get("user_role", "") or "")
                result = create_operational_exception(
                    exception_date=exception_date.isoformat(),
                    category=category,
                    summary=summary,
                    employee_id=str(selected_employee.get("emp_id", "") or ""),
                    employee_name=str(selected_employee.get("name", "") or ""),
                    department=str(selected_employee.get("department", "") or ""),
                    shift=shift,
                    process_name=process_name,
                    notes=notes,
                    created_by=str(st.session_state.get("user_email", "supervisor") or "supervisor"),
                    tenant_id=tenant_id,
                    user_role=_user_role,
                )
                if result:
                    show_success_state("Operational exception saved.")
                    st.rerun()
                else:
                    show_error_state("Operational exception could not be saved right now.")


def _render_open_exceptions(*, tenant_id: str) -> None:
    summary = summarize_open_operational_exceptions(tenant_id=tenant_id)
    rows = summary.get("rows") or []

    st.markdown('<div class="today-section-label">Operational Exceptions</div>', unsafe_allow_html=True)
    st.markdown('<div class="today-supporting-note">Open operational context that may help explain current performance signals.</div>', unsafe_allow_html=True)
    _render_exception_create_form(tenant_id=tenant_id, today_value=date.today())

    if not rows:
        with st.container(border=True):
            st.markdown("No open operational exceptions are currently logged.")
        return

    m1, m2 = st.columns(2)
    m1.metric("Open exceptions", int(summary.get("open_count", 0) or 0))
    m2.metric("Linked employees", int(summary.get("linked_employee_count", 0) or 0))
    category_bits = [f"{name}: {count}" for name, count in sorted((summary.get("categories") or {}).items())]
    if category_bits:
        st.caption("Categories: " + " | ".join(category_bits[:6]))

    for row in rows[:8]:
        exception_id = str(row.get("id") or "")
        summary_text = str(row.get("summary") or "Operational exception")
        linked_name = str(row.get("employee_name") or row.get("employee_id") or "Team context")
        with st.container(border=True):
            st.markdown(f"<div class=\"today-insight-title\">{summary_text}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class=\"today-insight-line\"><strong>What happened:</strong> {summary_text}</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class=\"today-insight-line\"><strong>Compared to what:</strong> Compared with normal operating conditions for this date, shift, or process context.</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class=\"today-insight-line\"><strong>Why shown:</strong> Shown because this exception is still open and may affect current performance interpretation.</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class=\"today-insight-meta\">Confidence: High (manually logged operational context). Source: {build_exception_context_line(row)} | Linked: {linked_name}</div>",
                unsafe_allow_html=True,
            )
            if str(row.get("notes") or "").strip():
                with st.expander("Context details", expanded=False):
                    st.write(str(row.get("notes") or ""))
                    if str(row.get("resolution_note") or "").strip():
                        st.caption(f"Resolution note: {row.get('resolution_note')}")

            with st.expander("Log follow-through", expanded=False):
                with st.form(f"today_exception_follow_through_{exception_id}", clear_on_submit=True):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        status = st.selectbox("Status", FOLLOW_THROUGH_STATUSES, index=0, key=f"today_exception_status_{exception_id}")
                    with c2:
                        outcome_label = st.selectbox(
                            "Outcome (optional)",
                            ["Not captured", "Improved", "No change", "Worse", "Blocked", "Pending"],
                            index=0,
                            key=f"today_exception_outcome_{exception_id}",
                        )
                    with c3:
                        has_due_date = st.checkbox("Add due date", value=False, key=f"today_exception_due_toggle_{exception_id}")
                    due_date = st.date_input(
                        "Due date",
                        value=date.today(),
                        key=f"today_exception_due_date_{exception_id}",
                        disabled=not has_due_date,
                    )
                    details = st.text_area(
                        "Notes/details",
                        height=90,
                        placeholder="Example: checked outage board, confirmed spare device ETA, recheck after lunch.",
                        key=f"today_exception_details_{exception_id}",
                    )
                    submitted = st.form_submit_button("Save follow-through", type="primary")
                    if submitted:
                        outcome_map = {
                            "Not captured": "",
                            "Improved": "improved",
                            "No change": "no_change",
                            "Worse": "worse",
                            "Blocked": "blocked",
                            "Pending": "pending",
                        }
                        result = log_follow_through_event(
                            employee_id=str(row.get("employee_id") or ""),
                            linked_exception_id=exception_id,
                            owner=str(st.session_state.get("user_email", "supervisor") or "supervisor"),
                            status=status,
                            due_date=due_date.isoformat() if has_due_date else "",
                            details=details,
                            outcome=outcome_map.get(outcome_label, ""),
                            tenant_id=tenant_id,
                        )
                        if result:
                            show_success_state("Exception follow-through saved.")
                            st.rerun()
                        else:
                            show_error_state("Exception follow-through could not be saved right now.")

            c1, c2 = st.columns(2)
            with c1:
                if str(row.get("employee_id") or "") and st.button("Open employee detail", key=f"today_exception_open_{exception_id}", use_container_width=True):
                    _go_to_exception_employee(row)
            with c2:
                if st.button("Resolve exception", key=f"today_exception_resolve_{exception_id}", use_container_width=True):
                    resolved = resolve_operational_exception(
                        exception_id,
                        resolution_note="Resolved from Today screen.",
                        resolved_by=str(st.session_state.get("user_email", "supervisor") or "supervisor"),
                        tenant_id=tenant_id,
                    )
                    if resolved:
                        show_success_state("Operational exception resolved.")
                        st.rerun()
                    else:
                        show_error_state("Operational exception could not be resolved right now.")


def _go_to_drill_down(item: InsightCardContract) -> None:
    screen = str(item.drill_down.screen or "")
    entity_id = str(item.drill_down.entity_id or "")
    st.session_state["_drill_traceability_context"] = traceability_payload_from_card(item)

    if screen == "employee_detail":
        st.session_state["goto_page"] = "team"
        st.session_state["emp_view"] = "Performance Journal"
        if entity_id:
            st.session_state["cn_selected_emp"] = entity_id
    elif screen == "team_process":
        st.session_state["goto_page"] = "team"
    elif screen == "import_data_trust":
        st.session_state["goto_page"] = "import"
    elif screen == "today":
        st.session_state["goto_page"] = "today"
    else:
        st.session_state["goto_page"] = "today"

    st.rerun()


def _build_attention_explanation_lines(signal: DisplaySignal, fallback_summary: str = "") -> list[str]:
    lines: list[str] = []
    mode = get_signal_display_mode(signal)

    if mode == SignalDisplayMode.LOW_DATA:
        lines.append(format_signal_label(signal) + ".")
        lines.append(format_confidence_line(signal))
    else:
        lines.append(format_signal_label(signal) + ".")
        observed_line = format_observed_line(signal)
        if observed_line:
            lines.append(observed_line)
        comparison_line = format_comparison_line(signal)
        if comparison_line:
            lines.append(comparison_line)
        lines.append(format_confidence_line(signal))

    if signal.signal_label in {SignalLabel.LOWER_THAN_RECENT_PACE, SignalLabel.BELOW_EXPECTED_PACE}:
        lines.append("Performance has been lower than usual over recent shifts.")
    elif signal.signal_label == SignalLabel.INCONSISTENT_PACE:
        lines.append("Performance has been inconsistent across recent shifts.")
    elif signal.signal_label == SignalLabel.IMPROVING_PACE:
        lines.append("Performance has been higher than usual in recent shifts.")

    if bool((signal.flags or {}).get("repeat")):
        lines.append("This pattern has appeared repeatedly in recent shifts.")

    if bool((signal.flags or {}).get("overdue")):
        lines.append("A follow-up was logged and is now overdue.")
    elif bool((signal.flags or {}).get("due_today")):
        lines.append("A follow-up is due today.")

    confidence = signal.confidence.value
    completeness = signal.data_completeness.value if signal.data_completeness is not None else "unknown"
    if confidence == "low":
        lines.append("Limited data available, so confidence is lower.")
    elif completeness in {"partial", "limited", "incomplete", "unknown"}:
        lines.append("Some data is missing, which reduces confidence.")

    if not lines:
        fallback = str(fallback_summary or "").strip().replace("—", "-")
        if fallback:
            lines.append(fallback.split(".", 1)[0].strip() + ".")

    unique_lines: list[str] = []
    seen: set[str] = set()
    for line in lines:
        clean = str(line or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_lines.append(clean)
        if len(unique_lines) == 4:
            break
    return unique_lines


def _render_attention_priority_section(attention: AttentionSummary) -> None:
    """Render the ranked priority attention list at the top of the Today screen."""
    st.markdown('<div class="today-section-label">Recently Surfaced</div>', unsafe_allow_html=True)

    if attention.is_healthy:
        st.markdown(
            '<div class="today-supporting-note">No strong signals are recently surfaced right now. '
            "The queue is clear based on current data.</div>",
            unsafe_allow_html=True,
        )
        return

    high_items = [item for item in attention.ranked_items if item.attention_tier == "high"]
    medium_items = [item for item in attention.ranked_items if item.attention_tier == "medium"]
    low_items = [item for item in attention.ranked_items if item.attention_tier == "low"]

    total_shown = len(high_items) + len(medium_items) + len(low_items)
    note_parts = []
    if high_items:
        note_parts.append(f"{len(high_items)} high-priority")
    if medium_items:
        note_parts.append(f"{len(medium_items)} medium-priority")
    if low_items:
        note_parts.append(f"{len(low_items)} low-priority")
    if attention.suppressed_count:
        note_parts.append(f"{attention.suppressed_count} suppressed (weak signal)")

    st.markdown(
        f'<div class="today-supporting-note">{", ".join(note_parts)} item{"s" if total_shown != 1 else ""} '
        f"currently shown from {attention.total_evaluated} evaluated.</div>",
        unsafe_allow_html=True,
    )

    suppressed_debug: list[dict[str, str]] = []
    for item in attention.ranked_items:
        display_signal = build_display_signal_from_attention_item(item=item, today=date.today())
        if not is_signal_display_eligible(display_signal, allow_low_data_case=True):
            suppressed_debug.append(
                {
                    "source": "attention",
                    "employee": str(display_signal.employee_name),
                    "process": str(display_signal.process),
                    "label": str(format_signal_label(display_signal)),
                }
            )
            continue
        tier = item.attention_tier
        tier_css = f"attention-item-{tier}"
        badge_css = f"attention-score-{tier}"
        tier_label = tier.title()

        with st.container(border=True):
            st.markdown(
                f'<div class="{tier_css}">'
                f'<span class="attention-score-badge {badge_css}">{tier_label}</span>'
                f"<strong>{display_signal.employee_name}</strong>"
                + (f" <span style='color:#5d7693;font-size:0.88rem;'>({display_signal.process})</span>" if display_signal.process and display_signal.process.lower() != "unassigned" else "")
                + "</div>",
                unsafe_allow_html=True,
            )
            explanation_lines = _build_attention_explanation_lines(display_signal, fallback_summary=item.attention_summary)
            st.markdown(
                f'<div class="today-insight-line">{(explanation_lines[0] if explanation_lines else item.attention_summary)}</div>',
                unsafe_allow_html=True,
            )
            if explanation_lines:
                with st.expander("Signal explanation", expanded=False):
                    for line in explanation_lines:
                        st.write(line)
            col1, _ = st.columns([1, 3])
            with col1:
                if st.button(
                    "Open employee detail",
                    key=f"attn_drill_{item.employee_id}_{item.process_name}",
                    use_container_width=True,
                ):
                    st.session_state["goto_page"] = "team"
                    st.session_state["emp_view"] = "Performance Journal"
                    st.session_state["cn_selected_emp"] = item.employee_id
                    st.rerun()

    if suppressed_debug:
        st.session_state["_today_suppressed_signals_debug"] = suppressed_debug


def _render_insight_card(item: InsightCardContract, *, key_prefix: str) -> None:
    display_signal = build_display_signal_from_insight_card(card=item, today=date.today())
    if not is_signal_display_eligible(display_signal, allow_low_data_case=True):
        suppressed = list(st.session_state.get("_today_suppressed_signals_debug") or [])
        suppressed.append(
            {
                "source": "home_section",
                "employee": str(display_signal.employee_name),
                "process": str(display_signal.process),
                "label": str(format_signal_label(display_signal)),
            }
        )
        st.session_state["_today_suppressed_signals_debug"] = suppressed
        return
    mode = get_signal_display_mode(display_signal)
    with st.container(border=True):
        if mode == SignalDisplayMode.LOW_DATA:
            line_1 = ""
            line_2 = format_signal_label(display_signal)
            line_3 = ""
            line_4 = ""
        else:
            line_1 = f"{display_signal.employee_name} · {display_signal.process}"
            line_2 = format_signal_label(display_signal)
            line_3 = format_observed_line(display_signal)
            line_4 = format_comparison_line(display_signal)
        line_5 = format_confidence_line(display_signal)

        for idx, text in enumerate((line_1, line_2, line_3, line_4, line_5), start=1):
            line_text = str(text or "").strip()
            if not line_text:
                continue
            if idx == 1:
                st.markdown(f'<div class="today-insight-title">{line_text}</div>', unsafe_allow_html=True)
            elif idx == 5:
                st.markdown(f'<div class="today-insight-meta">{line_text}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="today-insight-line">{line_text}</div>', unsafe_allow_html=True)

        low_data_state = mode == SignalDisplayMode.LOW_DATA

        why_line = str(item.metadata.get("secondary_status") or "").strip()
        basis_line = line_4
        data_note = str(item.data_completeness.summary or "").strip()
        has_extra = bool(low_data_state or why_line or basis_line or (data_note and item.data_completeness.status != "complete"))

        c1, c2 = st.columns([3, 2])
        with c1:
            if has_extra:
                with st.expander("Signal explanation", expanded=False):
                    if low_data_state:
                        st.caption("Only limited recent records available")
                    else:
                        if why_line:
                            st.write(f"Why: {why_line}")
                        if basis_line:
                            st.write(f"Based on: {basis_line.replace('Compared to: ', '')}")
                        if data_note and item.data_completeness.status != "complete":
                            st.caption(f"Data note: {data_note}")

        with c2:
            if st.button(item.drill_down.label, key=f"{key_prefix}_{item.insight_id}", use_container_width=True):
                _go_to_drill_down(item)


def _render_section_placeholder(message: str, todo_note: str, *, key: str) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="today-placeholder">{message}</div>', unsafe_allow_html=True)
        with st.expander("TODO scaffolding", expanded=False):
            st.caption(todo_note)
        if st.button("View Data Trust", key=key, use_container_width=True):
            st.session_state["goto_page"] = "import"
            st.rerun()


def _render_home_section(
    *,
    section_title: str,
    section_description: str,
    items: list[InsightCardContract],
    key_prefix: str,
    placeholder_message: str,
    placeholder_todo: str,
) -> None:
    st.markdown('<div class="today-home-section">', unsafe_allow_html=True)
    st.markdown(f'<div class="today-home-title">{section_title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="today-home-desc">{section_description}</div>', unsafe_allow_html=True)
    if not items:
        _render_section_placeholder(placeholder_message, placeholder_todo, key=f"{key_prefix}_placeholder")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for item in items:
        _render_insight_card(item, key_prefix=key_prefix)
    st.markdown("</div>", unsafe_allow_html=True)


def page_today() -> None:
    st.session_state["_ui_render_guard_active"] = True
    try:
        if "tenant_id" not in st.session_state:
            st.session_state.tenant_id = ""

        if "today_queue_filter" not in st.session_state:
            st.session_state.today_queue_filter = "all"

        today_value = date.today()

        _apply_today_styles()

        _trace_ctx = st.session_state.get("_drill_traceability_context") or {}
        if _trace_ctx and str(_trace_ctx.get("drill_down_screen", "")) in {"today", ""}:
            render_traceability_panel(_trace_ctx, heading="Signal source context")

        st.markdown(
        """
    <div class="today-hero">
        <div class="today-hero-kicker">Today Queue</div>
        <div class="today-hero-title">What recently surfaced today?</div>
        <div class="today-hero-copy">In under a minute, see what recently surfaced, understand context, and record outcomes.</div>
    </div>
    """,
        unsafe_allow_html=True,
    )
        _show_flash_message()

        refresh_col, _ = st.columns([1, 4])
        with refresh_col:
            if st.button("Refresh signals", key="today_refresh_precomputed_signals", use_container_width=True):
            try:
                from services.daily_signals_service import build_transient_today_payload, compute_daily_signals

                loading_slot = st.empty()
                with loading_slot.container():
                    show_loading_state("Refreshing precomputed signals for Today…")
                with st.spinner("Refreshing signals…"):
                    _tenant = str(st.session_state.get("tenant_id", "") or "")
                    try:
                        compute_daily_signals(
                            signal_date=today_value,
                            tenant_id=_tenant,
                        )
                    except Exception as _compute_err:
                        _msg = str(_compute_err or "")
                        if "daily_signals" in _msg or "PGRST205" in _msg:
                            st.session_state["_today_precomputed_payload"] = build_transient_today_payload(
                                signal_date=today_value,
                                tenant_id=_tenant,
                            )
                        else:
                            raise
                loading_slot.empty()
                get_today_signals.clear()
                st.success("Signals refreshed.")
                st.rerun()
            except Exception as _refresh_err:
                show_error_state(f"Signal refresh failed: {_refresh_err}")
                return

        try:
        # Today page is read-only: it renders precomputed signals and summaries
        # and does not run trigger pipelines, trend computation, or scoring.
        precomputed = get_today_signals(
            tenant_id=st.session_state.tenant_id,
            as_of_date=today_value.isoformat(),
        )
        if not precomputed:
            st.info("Signals are being prepared. Refresh shortly.")
            return

        queue_items = list(precomputed.get("queue_items") or [])
        counts = _queue_counts(queue_items)
        goal_status = list(precomputed.get("goal_status") or [])
        import_summary = dict(precomputed.get("import_summary") or {})
        home_sections = dict(precomputed.get("home_sections") or {})
        attention_summary = precomputed.get("attention_summary")
        if not isinstance(attention_summary, AttentionSummary):
            attention_summary = AttentionSummary(
                ranked_items=[],
                is_healthy=True,
                healthy_message="No strong signals are recently surfaced right now.",
                suppressed_count=0,
                total_evaluated=0,
            )

        if not isinstance(home_sections, dict):
            st.info("Signals are being prepared. Refresh shortly.")
            return
        required_sections = {"needs_attention", "changed_from_normal", "unresolved_items", "data_warnings"}
        if not required_sections.issubset(set(home_sections.keys())):
            st.info("Signals are being prepared. Refresh shortly.")
            return

        for section_key in required_sections.union({"suppressed_signals"}):
            home_sections.setdefault(section_key, [])
        for section_key in required_sections.union({"suppressed_signals"}):
            if not isinstance(home_sections.get(section_key), list):
                home_sections[section_key] = []
        for section_key in required_sections.union({"suppressed_signals"}):
            home_sections[section_key] = [
                item
                for item in (home_sections.get(section_key) or [])
                if isinstance(item, InsightCardContract)
            ]

        queue_items = [item for item in queue_items if isinstance(item, dict)]

        counts = _queue_counts(queue_items)
        if not import_summary:
            import_summary = st.session_state.get("_import_complete_summary") or {}
        if not isinstance(import_summary, dict):
            import_summary = {}

        if not goal_status:
            goal_status = []
        except Exception as exc:
            show_error_state(f"Today screen data could not load cleanly: {exc}")
            return

        state_flags = _compute_data_state_flags(goal_status, import_summary, home_sections)
        if state_flags["no_data"]:
            show_no_data_state()
        if state_flags["partial_data"]:
        missing_days = int(import_summary.get("days") or 0)
        partial_note = (
            f"Current history window is {missing_days} day(s). More days improve trend reliability."
            if missing_days > 0
            else "Some trend rows are incomplete and will become more reliable as data coverage grows."
        )
        show_partial_data_state(partial_note)
        if state_flags["low_confidence"]:
            show_low_confidence_state("Low-confidence signals are shown with clear caveats and may update as new data arrives.")
        if state_flags["healthy"] and counts.get("all", 0) == 0:
            show_healthy_state()

        _render_attention_priority_section(attention_summary)
        st.write("")

        st.markdown('<div class="today-section-label">Queue Summary</div>', unsafe_allow_html=True)
        _render_summary_strip(counts, st.session_state.today_queue_filter)
        st.write("")

        _render_home_section(
        section_title="Recently Surfaced",
        section_description="Open items currently visible in recent queue context.",
        items=home_sections.get("needs_attention", []),
        key_prefix="today_needs_attention",
        placeholder_message="No recently surfaced items right now.",
        placeholder_todo="TODO: Keep this section linked to real-time queue trigger refresh cadence.",
    )

        _render_home_section(
        section_title="Changed from Normal",
        section_description="Visible shifts in trend compared with each person's recent baseline context.",
        items=home_sections.get("changed_from_normal", []),
        key_prefix="today_changed_normal",
        placeholder_message="No clear changed-from-normal signals are available yet.",
        placeholder_todo="TODO: Expand trend confidence when enough consecutive observations are present.",
    )

        _render_home_section(
        section_title="Unresolved Items",
        section_description="Items that remain open past expected follow-up timing or appear repeatedly.",
        items=home_sections.get("unresolved_items", []),
        key_prefix="today_unresolved",
        placeholder_message="No unresolved items are currently surfaced.",
        placeholder_todo="TODO: Add issue-type specific unresolved-age benchmarks once service defaults are finalized.",
    )

        _render_home_section(
        section_title="Data Warnings",
        section_description="Data quality and completeness context that may affect signal confidence.",
        items=home_sections.get("data_warnings", []),
        key_prefix="today_data_warnings",
        placeholder_message="No active data warnings from current session context.",
        placeholder_todo="TODO: Wire structured import diagnostics for row-level completeness breakdown.",
    )

        main_signal_count = sum(
        len(home_sections.get(section_key) or [])
        for section_key in ("needs_attention", "changed_from_normal", "unresolved_items")
    )
        if main_signal_count == 0:
            st.markdown('<div class="today-supporting-note"><strong>Nothing important changed today</strong></div>', unsafe_allow_html=True)

        suppressed_signals = list(home_sections.get("suppressed_signals") or [])
        if suppressed_signals:
        with st.expander(f"Suppressed signals ({len(suppressed_signals)})", expanded=False):
            st.caption("Hidden from main view by display eligibility rules.")
            for item in suppressed_signals[:20]:
                signal = build_display_signal_from_insight_card(card=item, today=today_value)
                if not is_signal_display_eligible(signal, allow_low_data_case=True):
                    continue
                title = f"{signal.employee_name} · {signal.process}"
                label = format_signal_label(signal)
                st.write(f"{title}")
                if label:
                    st.caption(label)

        _render_open_exceptions(tenant_id=st.session_state.tenant_id)

        filtered_queue = _filter_queue(queue_items, st.session_state.today_queue_filter)
        recent_outcomes = _cached_recent_action_outcomes(
        lookback_days=1,
        tenant_id=str(st.session_state.tenant_id or ""),
    )

        st.markdown('<div class="today-section-label">Action Queue Details</div>', unsafe_allow_html=True)
        st.markdown('<div class="today-supporting-note">Expanded evidence and logging controls for open queue items.</div>', unsafe_allow_html=True)
        if filtered_queue:
        st.caption(f"Showing {len(filtered_queue)} actionable item{'s' if len(filtered_queue) != 1 else ''}.")
        render_action_queue(
            queue_items=filtered_queue,
            tenant_id=st.session_state.tenant_id,
            performed_by=str(st.session_state.get("user_email", "supervisor") or "supervisor"),
            today=today_value,
        )
        elif counts["all"]:
            _render_filtered_empty_state()
        else:
        # Check if this is first-time user (just completed import)
        is_first_time = st.session_state.get("_first_import_just_completed", False)
        if is_first_time:
            st.session_state["_first_import_just_completed"] = False  # Show first-time state only once
            _render_first_time_empty_state()
        else:
            _render_empty_state()

        st.write("")
        st.markdown('<div class="today-section-label">Since Yesterday</div>', unsafe_allow_html=True)
        _render_since_yesterday(queue_items, recent_outcomes)

        st.write("")
        manager_stats = _cached_manager_outcome_stats(
        tenant_id=str(st.session_state.tenant_id or ""),
        lookback_days=7,
        today_iso=today_value.isoformat(),
    )
        st.markdown('<div class="today-section-label">Supporting Context</div>', unsafe_allow_html=True)
        _render_bottom_charts(queue_items, manager_stats)
    finally:
        st.session_state["_ui_render_guard_active"] = False