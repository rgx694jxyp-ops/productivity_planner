"""Today page.

Queue-first supervisor workflow focused on daily follow-through.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from services.action_lifecycle_service import run_all_triggers
from services.action_metrics_service import _recent_action_outcomes, get_manager_outcome_stats
from services.action_query_service import get_open_actions
from services.action_recommendation_service import get_ignored_high_performers, get_repeat_offenders
from ui.today_queue import build_action_queue, render_action_queue


st.set_page_config(
    page_title="Today - DPD Supervisor",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)


if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = ""

if "today_queue_filter" not in st.session_state:
    st.session_state.today_queue_filter = "all"

if "today_auto_triggers_run" not in st.session_state:
    st.session_state.today_auto_triggers_run = False


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
        </style>
        """,
        unsafe_allow_html=True,
    )


def _show_flash_message() -> None:
    message = str(st.session_state.pop("today_flash_message", "") or "")
    if message:
        st.success(message)


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


today_value = date.today()

_apply_today_styles()

st.markdown(
    """
    <div class="today-hero">
        <div class="today-hero-kicker">Today Queue</div>
        <div class="today-hero-title">Who needs your attention today?</div>
        <div class="today-hero-copy">In under a minute, see who needs attention, understand why, log the next move, and keep the floor moving.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
_show_flash_message()

if not st.session_state.today_auto_triggers_run:
    with st.spinner("Refreshing the action queue..."):
        run_all_triggers(tenant_id=st.session_state.tenant_id)
    st.session_state.today_auto_triggers_run = True

open_actions = get_open_actions(tenant_id=st.session_state.tenant_id, today=today_value)
repeat_offenders = get_repeat_offenders(
    tenant_id=st.session_state.tenant_id,
    today=today_value,
    open_actions=open_actions,
)
ignored_high_performers = get_ignored_high_performers(
    tenant_id=st.session_state.tenant_id,
    today=today_value,
    open_actions=open_actions,
)
queue_items = build_action_queue(
    open_actions=open_actions,
    repeat_offenders=repeat_offenders,
    recognition_opportunities=ignored_high_performers,
    tenant_id=st.session_state.tenant_id,
    today=today_value,
)
counts = _queue_counts(queue_items)

st.markdown('<div class="today-section-label">Queue Summary</div>', unsafe_allow_html=True)
_render_summary_strip(counts, st.session_state.today_queue_filter)
st.write("")

filtered_queue = _filter_queue(queue_items, st.session_state.today_queue_filter)
recent_outcomes = _recent_action_outcomes(lookback_days=1, tenant_id=st.session_state.tenant_id)

st.markdown('<div class="today-section-label">Action Queue</div>', unsafe_allow_html=True)
st.markdown('<div class="today-supporting-note">Top items stay visible first. Overdue actions float to the top until they are updated.</div>', unsafe_allow_html=True)
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
    _render_empty_state()

st.write("")
st.markdown('<div class="today-section-label">Since Yesterday</div>', unsafe_allow_html=True)
_render_since_yesterday(queue_items, recent_outcomes)

st.write("")
manager_stats = get_manager_outcome_stats(
    tenant_id=st.session_state.tenant_id,
    lookback_days=7,
    today=today_value,
)
st.markdown('<div class="today-section-label">Supporting Context</div>', unsafe_allow_html=True)
_render_bottom_charts(queue_items, manager_stats)