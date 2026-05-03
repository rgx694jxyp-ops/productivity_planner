"""Today page.

Queue-first supervisor workflow focused on daily follow-through.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
import time
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from database import add_coaching_note
from core.dependencies import _bust_cache, _cached_employees, _log_app_error, _log_operational_event
from core.onboarding_intent import build_onboarding_event_context
from domain.display_signal import DisplaySignal, SignalLabel
from domain.insight_card_contract import InsightCardContract
from domain.operational_exceptions import EXCEPTION_CATEGORIES
from services.action_state_service import build_employee_action_state_lookup, log_follow_through_event
from services.action_metrics_service import (
    _recent_action_outcomes,
    get_manager_outcome_stats,
    get_weekly_manager_activity_summary,
)
from services.exception_tracking_service import (
    build_exception_context_line,
    create_operational_exception,
    list_open_operational_exceptions,
    resolve_operational_exception,
    summarize_open_operational_exceptions,
)
from services.attention_scoring_service import AttentionSummary
from services.display_signal_factory import build_display_signal_from_attention_item, build_display_signal_from_insight_card
from services.follow_through_service import FOLLOW_THROUGH_STATUSES
from services.signal_formatting_service import (
    format_comparison_line,
    format_confidence_line,
    format_low_data_collapsed_lines,
    format_low_data_expanded_lines,
    format_observed_line,
    format_signal_label,
    get_signal_display_mode,
    is_signal_display_eligible,
    SignalDisplayMode,
)
from services.today_home_service import get_today_signals
from services.today_page_meaning_service import (
    TodayQueueRenderPlan,
    TodayQueueOrientationModel,
    TodaySurfaceState,
    TodaySurfaceMeaning,
    build_queue_orientation,
    build_today_queue_render_plan,
    build_today_surface_meaning,
)
from services.today_snapshot_signal_service import (
    SignalMode,
    build_snapshot_fallback_cards,
)
from services.today_signal_status_service import (
    SIGNAL_STATUS_LOOKED_AT,
    SIGNAL_STATUS_NEEDS_FOLLOW_UP,
    list_latest_signal_statuses,
    set_signal_status,
)
from services.today_view_model_service import (
    TodayAttentionStripViewModel,
    TodayLowDataFallbackViewModel,
    TodayManagerLoopStripViewModel,
    TodayQueueCardViewModel,
    TodayReturnTriggerViewModel,
    TodayTeamRiskViewModel,
    TodayValueStripViewModel,
    TodayWeeklySummaryViewModel,
    build_today_low_data_fallback_view_model,
    build_today_manager_loop_strip,
    build_today_standup_text,
    build_today_summary,
    build_today_team_risk_view_model,
    build_today_attention_strip,
    build_today_queue_card_from_insight_card,
    build_today_return_trigger,
    build_today_value_strip_view_model,
    build_today_weekly_summary_view_model,
    enrich_today_queue_card_action_context,
)
from services.signal_traceability_service import traceability_payload_from_card
from services.plain_language_service import signal_wording
from services.perf_profile import profile_block
from ui.state_panels import (
    consume_flash_message,
    set_flash_message,
    show_error_state,
    show_loading_state,
    show_success_state,
)
from ui.traceability_panel import render_traceability_panel
from services.demo_data_service import is_demo_upload_row as _is_demo_upload_row, reset_demo_uploads as _reset_demo_uploads


_READ_CACHE_TTL_SECONDS = 300
_TODAY_RECOVERY_LOCK_TTL_SECONDS = 90
_TODAY_ACTION_STATE_LOOKUP_MAX_EMPLOYEE_IDS = 24
_TODAY_ACTION_STATE_LOOKUP_MAX_RANKED_ITEMS = 12
_TODAY_ACTION_STATE_LOOKUP_MAX_DECISION_ITEMS = 18
_TODAY_ACTION_STATE_LOOKUP_MAX_SECTION_ITEMS = 12
_TODAY_ACTION_STATE_LOOKUP_MAX_SNAPSHOT_ITEMS = 12
_TODAY_PHASE1_RANKED_SCAN_LIMIT = 12
_TODAY_QUEUE_DEFAULT_VISIBLE_CARDS = 3
_TODAY_PAYLOAD_SESSION_CACHE_KEY_PREFIX = "_today_payload_session_cache_"
_TODAY_COMPLETED_ITEMS_SESSION_KEY = "_today_completed_items"
_TODAY_COMPLETION_FEEDBACK_MESSAGE_KEY = "_today_completion_feedback_message"
_TODAY_FOCUS_NEXT_CARD_KEY = "_today_focus_next_card"
_TODAY_HANDOFF_FOCUS_RENDERED_KEY_PREFIX = "_today_handoff_focus_rendered_"
_TODAY_TO_TEAM_HANDOFF_KEY = "_today_to_team_handoff"
_TEAM_TO_TODAY_FOCUS_KEY = "_team_to_today_focus"
_TODAY_AUTO_REFRESH_MIN_SECONDS = 60
_TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX = "_today_auto_resolved_shown_"
_TODAY_PENDING_COMPLETION_IDS_KEY = "_today_pending_completion_ids"
_TODAY_PENDING_COMPLETION_META_KEY = "_today_pending_completion_meta"
_TODAY_PENDING_COMPLETION_SIGNAL_KEYS_KEY = "_today_pending_completion_signal_keys"
_TODAY_DEFERRED_WIDGET_RESET_SIGNAL_IDS_KEY = "_today_deferred_widget_reset_signal_ids"

# Cold-load run-id & milestone instrumentation keys
_TODAY_RUN_ID_DATE_KEY_PREFIX = "_today_run_id_for_date_"
_TODAY_RUN_NAV_SOURCE_KEY_PREFIX = "_today_run_nav_source_"
_TODAY_RUN_WALL_START_KEY = "_today_run_wall_start"
_TODAY_RUN_IS_COLD_KEY = "_today_run_is_cold"
_TODAY_RUN_MILESTONES_KEY = "_today_run_milestones"

_TODAY_COMPLETION_ASYNC_RESULTS: dict[str, dict[str, Any]] = {}
_TODAY_COMPLETION_ASYNC_RESULTS_LOCK = threading.Lock()
_TODAY_ASYNC_SNAPSHOT_REFRESH_STATE: dict[str, dict[str, Any]] = {}
_TODAY_ASYNC_SNAPSHOT_REFRESH_LOCK = threading.Lock()


def _today_initial_load_completed_key(today_value: date) -> str:
    return f"_today_initial_load_completed_{today_value.isoformat()}"


def _today_initial_rerun_triggered_key(today_value: date) -> str:
    return f"_today_initial_rerun_triggered_{today_value.isoformat()}"


def _today_initial_load_event_logged_key(today_value: date, event_name: str, marker: str = "") -> str:
    safe_event = str(event_name or "").strip().replace(" ", "_")
    safe_marker = str(marker or "").strip().replace(" ", "_")
    suffix = f"_{safe_marker}" if safe_marker else ""
    return f"_today_initial_load_event_logged_{today_value.isoformat()}_{safe_event}{suffix}"


def _log_today_initial_load_event_once(
    *,
    event_name: str,
    today_value: date,
    tenant_id: str,
    context: dict[str, Any],
    marker: str = "",
) -> None:
    log_key = _today_initial_load_event_logged_key(today_value=today_value, event_name=event_name, marker=marker)
    if bool(st.session_state.get(log_key)):
        return
    _log_operational_event(
        event_name,
        status="info",
        tenant_id=str(tenant_id or ""),
        user_email=str(st.session_state.get("user_email", "") or ""),
        context=dict(context or {}),
    )
    st.session_state[log_key] = True


def _log_today_milestone(
    name: str,
    *,
    tenant_id: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Log a cold-load milestone with run_id and elapsed_ms.

    Unlike the log-once helpers, fires on every run so the full multi-run
    timeline (Run-1, Run-2, Run-3) is captured under one run_id.
    """
    today_iso = date.today().isoformat()
    run_id = str(st.session_state.get(_TODAY_RUN_ID_DATE_KEY_PREFIX + today_iso) or "")
    run_wall_start = float(st.session_state.get(_TODAY_RUN_WALL_START_KEY) or 0.0)
    is_cold = bool(st.session_state.get(_TODAY_RUN_IS_COLD_KEY))
    nav_from = str(st.session_state.get(_TODAY_RUN_NAV_SOURCE_KEY_PREFIX + today_iso) or "")
    elapsed_ms = int((time.time() - run_wall_start) * 1000) if run_wall_start else 0

    milestone: dict[str, Any] = {"name": name, "elapsed_ms": elapsed_ms, "ts": time.time()}
    if context:
        milestone.update(context)
    milestones: list[dict[str, Any]] = list(st.session_state.get(_TODAY_RUN_MILESTONES_KEY) or [])
    milestones.append(milestone)
    st.session_state[_TODAY_RUN_MILESTONES_KEY] = milestones

    _log_operational_event(
        name,
        status="info",
        tenant_id=str(tenant_id or ""),
        user_email=str(st.session_state.get("user_email") or ""),
        context={
            "run_id": run_id,
            "elapsed_ms": elapsed_ms,
            "is_cold_start": is_cold,
            "nav_from": nav_from,
            **(context or {}),
        },
    )


def print_today_run_timeline() -> None:
    """Print the ordered milestone timeline for the current Today run to stderr.

    Call from a debug console or diagnostic view to inspect cold-load timing
    without digging through the full operational log.
    """
    import sys

    today_iso = date.today().isoformat()
    run_id = str(st.session_state.get(_TODAY_RUN_ID_DATE_KEY_PREFIX + today_iso) or "none")
    milestones: list[dict[str, Any]] = list(st.session_state.get(_TODAY_RUN_MILESTONES_KEY) or [])
    lines = ["\n" + "=" * 60, f"Today Run Timeline  run_id={run_id}", "=" * 60]
    prev_elapsed = 0
    for m in milestones:
        elapsed = int(m.get("elapsed_ms") or 0)
        delta = elapsed - prev_elapsed
        mname = str(m.get("name") or "?")
        extra = {k: v for k, v in m.items() if k not in {"name", "elapsed_ms", "ts"}}
        extra_str = f"  {extra}" if extra else ""
        lines.append(f"  +{delta:>6}ms  [{elapsed:>7}ms]  {mname}{extra_str}")
        prev_elapsed = elapsed
    lines.append("=" * 60)
    sys.stderr.write("\n".join(lines) + "\n")


def _today_async_snapshot_refresh_key(*, tenant_id: str, today_value: date) -> str:
    return f"{str(tenant_id or '').strip()}::{today_value.isoformat()}"


def _today_async_snapshot_refresh_consumed_key(*, tenant_id: str, today_value: date) -> str:
    return f"_today_async_snapshot_refresh_consumed::{str(tenant_id or '').strip()}::{today_value.isoformat()}"


def _schedule_today_snapshot_recompute_async(
    *,
    tenant_id: str,
    today_value: date,
    run_id: str,
    snapshot_available: bool,
    latest_snapshot_date: str,
) -> bool:
    refresh_key = _today_async_snapshot_refresh_key(tenant_id=tenant_id, today_value=today_value)
    with _TODAY_ASYNC_SNAPSHOT_REFRESH_LOCK:
        existing = dict(_TODAY_ASYNC_SNAPSHOT_REFRESH_STATE.get(refresh_key) or {})
        if bool(existing.get("in_progress")):
            return False
        token = int(existing.get("token", 0) or 0) + 1
        _TODAY_ASYNC_SNAPSHOT_REFRESH_STATE[refresh_key] = {
            "token": token,
            "in_progress": True,
            "completed": False,
            "completed_token": int(existing.get("completed_token", 0) or 0),
            "started_at": time.time(),
            "error": "",
        }

    def _worker() -> None:
        recompute_ms = 0
        total_ms = 0
        try:
            from services.daily_snapshot_service import recompute_daily_employee_snapshots

            _log_operational_event(
                "today_snapshot_recompute_started_async",
                status="started",
                tenant_id=str(tenant_id or ""),
                user_email="",
                context={
                    "run_id": str(run_id or ""),
                    "today_iso": today_value.isoformat(),
                    "snapshot_available": bool(snapshot_available),
                    "latest_snapshot_date": str(latest_snapshot_date or ""),
                },
            )

            worker_started_at = time.perf_counter()
            recompute_started_at = time.perf_counter()
            recompute_daily_employee_snapshots(tenant_id=tenant_id, days=1)
            recompute_ms = int(max(0.0, (time.perf_counter() - recompute_started_at) * 1000))
            # Note: daily signals are NOT written here — the Supabase JWT auth context
            # required for signals RLS is not available in a background thread. Signals
            # will be recomputed on the next page load after cache invalidation picks up
            # the fresh snapshots written above.
            total_ms = int(max(0.0, (time.perf_counter() - worker_started_at) * 1000))

            with _TODAY_ASYNC_SNAPSHOT_REFRESH_LOCK:
                _TODAY_ASYNC_SNAPSHOT_REFRESH_STATE[refresh_key] = {
                    "token": token,
                    "in_progress": False,
                    "completed": True,
                    "completed_token": token,
                    "started_at": float(existing.get("started_at", time.time()) or time.time()),
                    "completed_at": time.time(),
                    "error": "",
                }

            _log_operational_event(
                "today_snapshot_recompute_completed_async",
                status="completed",
                tenant_id=str(tenant_id or ""),
                user_email="",
                context={
                    "run_id": str(run_id or ""),
                    "today_iso": today_value.isoformat(),
                    "recompute_ms": int(recompute_ms),
                    "total_ms": int(total_ms),
                },
            )
        except Exception as async_err:
            with _TODAY_ASYNC_SNAPSHOT_REFRESH_LOCK:
                _TODAY_ASYNC_SNAPSHOT_REFRESH_STATE[refresh_key] = {
                    "token": token,
                    "in_progress": False,
                    "completed": False,
                    "completed_token": int(existing.get("completed_token", 0) or 0),
                    "started_at": float(existing.get("started_at", time.time()) or time.time()),
                    "completed_at": time.time(),
                    "error": str(async_err or ""),
                }

            _log_app_error(
                "today_snapshot_recompute_async_failed",
                f"Async snapshot recompute failed: {async_err}",
                severity="warning",
            )
            _log_operational_event(
                "today_snapshot_recompute_completed_async",
                status="error",
                tenant_id=str(tenant_id or ""),
                user_email="",
                context={
                    "run_id": str(run_id or ""),
                    "today_iso": today_value.isoformat(),
                    "recompute_ms": int(recompute_ms),
                    "total_ms": int(total_ms),
                    "error": str(async_err or ""),
                },
            )

    worker = threading.Thread(target=_worker, name=f"today-snapshot-refresh-{today_value.isoformat()}", daemon=True)
    worker.start()
    return True


def _consume_today_async_snapshot_refresh_completion(*, tenant_id: str, today_value: date) -> bool:
    refresh_key = _today_async_snapshot_refresh_key(tenant_id=tenant_id, today_value=today_value)
    with _TODAY_ASYNC_SNAPSHOT_REFRESH_LOCK:
        refresh_state = dict(_TODAY_ASYNC_SNAPSHOT_REFRESH_STATE.get(refresh_key) or {})

    if not bool(refresh_state.get("completed")):
        return False

    completed_token = int(refresh_state.get("completed_token", 0) or 0)
    consumed_key = _today_async_snapshot_refresh_consumed_key(tenant_id=tenant_id, today_value=today_value)
    already_consumed_token = int(st.session_state.get(consumed_key, 0) or 0)
    if completed_token <= already_consumed_token:
        return False

    _invalidate_today_write_caches()
    st.session_state[consumed_key] = completed_token
    return True


def _today_payload_ready_for_render(precomputed: dict[str, Any] | None) -> bool:
    payload = dict(precomputed or {}) if isinstance(precomputed, dict) else {}
    required_keys = ("queue_items", "goal_status", "import_summary", "home_sections")
    return bool(payload) and all(key in payload for key in required_keys)


def _today_first_paint_event_logged_key(*, today_value: date, event_name: str, marker: str = "") -> str:
    safe_event = str(event_name or "").strip().replace(" ", "_")
    safe_marker = str(marker or "").strip().replace(" ", "_")
    suffix = f"_{safe_marker}" if safe_marker else ""
    return f"_today_first_paint_event_logged_{today_value.isoformat()}_{safe_event}{suffix}"


def _log_today_first_paint_event_once(
    *,
    event_name: str,
    today_value: date,
    tenant_id: str,
    context: dict[str, Any],
    marker: str = "",
) -> None:
    log_key = _today_first_paint_event_logged_key(today_value=today_value, event_name=event_name, marker=marker)
    if bool(st.session_state.get(log_key)):
        return
    _log_operational_event(
        event_name,
        status="info",
        tenant_id=str(tenant_id or ""),
        user_email=str(st.session_state.get("user_email", "") or ""),
        context=dict(context or {}),
    )
    st.session_state[log_key] = True


def _today_should_show_first_paint_shell(*, entered_from_page: str, today_value: date) -> bool:
    if bool(st.session_state.get(_today_initial_load_completed_key(today_value))):
        return False
    source_page = str(entered_from_page or "").strip().lower()
    if source_page and source_page != "today":
        return True
    return True


def _render_today_loading_shell(*, reason: str | None = None) -> None:
    st.markdown("## Today")
    st.caption(str(reason or _today_loading_placeholder()).strip())


def _today_signal_surface_heading(signal_count: int) -> str:
    count = int(max(0, signal_count))
    label = "signal" if count == 1 else "signals"
    return f"## Today: {count} {label} surfaced"


def _today_queue_intro_label() -> str:
    return "Follow-ups Today"


def _today_loading_placeholder() -> str:
    return "Loading follow-ups for today..."


def _today_phase2_render_ready_key(today_value: date) -> str:
    return f"_today_phase2_render_ready_{today_value.isoformat()}"


def _prepare_today_phase1_top_queue_render(
    *,
    plan: TodayQueueRenderPlan,
    tenant_id: str,
    today_value: date,
) -> dict[str, Any]:
    ranked_cards = list(plan.primary_cards or []) + list(plan.secondary_cards or [])
    if len(ranked_cards) > _TODAY_PHASE1_RANKED_SCAN_LIMIT:
        ranked_cards = ranked_cards[:_TODAY_PHASE1_RANKED_SCAN_LIMIT]

    lightweight_plan = TodayQueueRenderPlan(
        section_title=plan.section_title,
        weak_data_note=plan.weak_data_note,
        start_note=plan.start_note,
        primary_cards=ranked_cards,
        secondary_cards=[],
        primary_placeholder=plan.primary_placeholder,
        secondary_caption=plan.secondary_caption,
        secondary_expanded=False,
        suppressed_debug_rows=list(plan.suppressed_debug_rows or []),
    )

    prepared = _prepare_today_top_queue_render(
        plan=lightweight_plan,
        tenant_id=tenant_id,
        today_value=today_value,
    )
    top_cards = list(prepared.get("top_cards") or [])
    people_needing_attention = len(
        {
            str(getattr(card, "employee_id", "") or "").strip()
            for card in top_cards
            if str(getattr(card, "employee_id", "") or "").strip()
        }
    )
    return {
        "top_cards": top_cards,
        "signal_status_map": dict(prepared.get("signal_status_map") or {}),
        "people_needing_attention": int(people_needing_attention),
        "signal_status_map_ms": int(prepared.get("signal_status_map_ms") or 0),
        "queue_build_ms": int(prepared.get("queue_derivation_ms") or 0),
    }


def _render_today_phase1_top_cards(
    *,
    top_cards: list[TodayQueueCardViewModel],
    signal_status_map: dict[str, dict[str, str]],
    people_needing_attention: int,
    low_data_fallback: TodayLowDataFallbackViewModel | None = None,
) -> None:
    if low_data_fallback is not None:
        _render_today_low_data_fallback(low_data_fallback)
        return

    if not top_cards:
        st.markdown(f'<div class="today-placeholder">{_today_loading_placeholder()}</div>', unsafe_allow_html=True)
        return

    st.markdown('<div class="today-home-title">Follow-ups Today</div>', unsafe_allow_html=True)
    st.markdown('<div class="today-action-frame-heading">Handle these first</div>', unsafe_allow_html=True)
    st.markdown('<div class="today-action-frame-sub">Open loops that need a manager decision, check-in, or closeout.</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="today-update-indicator">{_updated_indicator_text()}</div>', unsafe_allow_html=True)
    _phase1_cards = list(top_cards or [])[:_TODAY_QUEUE_DEFAULT_VISIBLE_CARDS]
    _phase1_cols = st.columns(min(max(len(_phase1_cards), 1), 3))
    for idx, card in enumerate(_phase1_cards):
        with _phase1_cols[idx]:
            # Phase 1 is scan-only; keep action widgets out to avoid duplicate keys
            # before Phase 2 renders the full actionable queue in the same run.
            _render_attention_card(
                card=card,
                key_prefix=f"today_attention_primary_{idx}",
                emphasize=False,
                focused=False,
                signal_status_map=None,
            )


def _run_today_auto_refresh(*, tenant_id: str, today_value: date) -> dict[str, Any]:
    refresh_due = _should_auto_refresh_signals()
    active_interaction, interaction_reasons = _today_has_active_interaction_state()
    initial_completed_key = _today_initial_load_completed_key(today_value)
    initial_load_completed = bool(st.session_state.get(initial_completed_key))

    result: dict[str, Any] = {
        "refresh_due": bool(refresh_due),
        "active_interaction": bool(active_interaction),
        "interaction_reasons": list(interaction_reasons or []),
        "initial_load_completed": bool(initial_load_completed),
        "initial_load_attempted": False,
        "refreshed": False,
    }

    if not initial_load_completed:
        if not str(tenant_id or "").strip():
            _log_today_initial_load_event_once(
                event_name="today_initial_load_skipped",
                today_value=today_value,
                tenant_id=tenant_id,
                marker="tenant_missing",
                context={"reason": "tenant_missing"},
            )
            result["blocked_reason"] = "tenant_missing"
            return result

        _log_today_initial_load_event_once(
            event_name="today_initial_load_started",
            today_value=today_value,
            tenant_id=tenant_id,
            context={
                "refresh_due": bool(refresh_due),
                "active_interaction": bool(active_interaction),
                "interaction_reasons": list(interaction_reasons or []),
            },
        )

        result["initial_load_attempted"] = True
        st.session_state["_today_auto_refresh_running"] = True
        refreshed = _attempt_signal_payload_recovery(tenant_id=tenant_id, today_value=today_value)
        st.session_state["_today_auto_refresh_running"] = False
        st.session_state["_today_last_refresh_success"] = bool(refreshed)
        result["refreshed"] = bool(refreshed)

        if not refreshed:
            _log_today_initial_load_event_once(
                event_name="today_initial_load_blocked_reason",
                today_value=today_value,
                tenant_id=tenant_id,
                marker="recovery_not_completed",
                context={"reason": "recovery_not_completed"},
            )
            result["blocked_reason"] = "recovery_not_completed"

        return result

    _log_today_initial_load_event_once(
        event_name="today_initial_load_skipped",
        today_value=today_value,
        tenant_id=tenant_id,
        marker="already_completed",
        context={"reason": "already_completed"},
    )

    if refresh_due and not active_interaction:
        st.session_state["_today_auto_refresh_running"] = True
        refreshed = _attempt_signal_payload_recovery(tenant_id=tenant_id, today_value=today_value)
        st.session_state["_today_auto_refresh_running"] = False
        st.session_state["last_refresh"] = float(time.time())
        st.session_state["_today_last_refresh_success"] = bool(refreshed)
        result["refreshed"] = bool(refreshed)
    elif refresh_due and active_interaction:
        _log_operational_event(
            "today_refresh_skipped_active_interaction",
            status="info",
            tenant_id=tenant_id,
            user_email=str(st.session_state.get("user_email", "") or ""),
            context={
                "reasons": list(interaction_reasons or []),
                "pending_count": len(list(st.session_state.get(_TODAY_PENDING_COMPLETION_IDS_KEY) or [])),
            },
        )
    else:
        _log_refresh_redundant_prevented(last_refresh_ts=float(st.session_state.get("last_refresh", 0.0) or 0.0))

    return result


def _finalize_today_initial_load_state(*, tenant_id: str, today_value: date, precomputed: dict[str, Any] | None) -> bool:
    completed_key = _today_initial_load_completed_key(today_value)
    if bool(st.session_state.get(completed_key)):
        return True

    if not _today_payload_ready_for_render(precomputed):
        _log_today_initial_load_event_once(
            event_name="today_initial_load_blocked_reason",
            today_value=today_value,
            tenant_id=tenant_id,
            marker="payload_not_ready",
            context={"reason": "payload_not_ready"},
        )
        return False

    queue_items = list((precomputed or {}).get("queue_items") or [])
    goal_status = list((precomputed or {}).get("goal_status") or [])
    st.session_state[completed_key] = True
    st.session_state["_today_initial_load_completed_at"] = float(time.time())
    st.session_state["last_refresh"] = float(time.time())
    st.session_state["_today_last_refresh_success"] = True
    _log_today_initial_load_event_once(
        event_name="today_initial_load_completed",
        today_value=today_value,
        tenant_id=tenant_id,
        context={
            "queue_items": len(queue_items),
            "goal_status_rows": len(goal_status),
        },
    )
    return True


def _trigger_today_initial_ready_rerun_if_needed(
    *,
    tenant_id: str,
    today_value: date,
    was_initially_ready: bool,
    is_ready_now: bool,
) -> bool:
    if not is_ready_now:
        _log_today_initial_load_event_once(
            event_name="today_rerun_skipped_reason",
            today_value=today_value,
            tenant_id=tenant_id,
            marker="not_ready",
            context={"reason": "not_ready"},
        )
        return False

    if was_initially_ready:
        _log_today_initial_load_event_once(
            event_name="today_rerun_skipped_reason",
            today_value=today_value,
            tenant_id=tenant_id,
            marker="already_ready",
            context={"reason": "already_ready"},
        )
        return False

    rerun_key = _today_initial_rerun_triggered_key(today_value)
    if bool(st.session_state.get(rerun_key)):
        _log_today_initial_load_event_once(
            event_name="today_rerun_skipped_reason",
            today_value=today_value,
            tenant_id=tenant_id,
            marker="already_triggered",
            context={"reason": "already_triggered"},
        )
        return False

    _log_today_initial_load_event_once(
        event_name="today_data_ready_detected",
        today_value=today_value,
        tenant_id=tenant_id,
        context={
            "was_initially_ready": bool(was_initially_ready),
            "is_ready_now": bool(is_ready_now),
        },
    )
    st.session_state[rerun_key] = True
    _log_today_initial_load_event_once(
        event_name="today_rerun_triggered",
        today_value=today_value,
        tenant_id=tenant_id,
        context={"reason": "initial_data_became_ready"},
    )
    _log_today_milestone(
        "today_rerun_triggered",
        tenant_id=tenant_id,
        context={"reason": "initial_data_became_ready"},
    )
    st.rerun()
    return True


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


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_weekly_manager_activity_summary(*, tenant_id: str, lookback_days: int, today_iso: str) -> dict[str, int]:
    with profile_block(
        "today.cache_miss.weekly_activity_summary",
        tenant_id=str(tenant_id or ""),
        context={"lookback_days": int(lookback_days or 0), "today_iso": str(today_iso or "")},
    ) as profile:
        _log_heavy_render_compute("get_weekly_manager_activity_summary")
        profile.cache_miss("weekly_activity_summary")
        try:
            today_value = date.fromisoformat(str(today_iso or "")[:10])
        except Exception:
            today_value = date.today()
        result = dict(get_weekly_manager_activity_summary(tenant_id=tenant_id, lookback_days=lookback_days, today=today_value) or {})
        profile.set("reviewed_issues", int(result.get("reviewed_issues", 0) or 0))
        return result


def _weekly_activity_page_cache_key(*, tenant_id: str, lookback_days: int, today_iso: str) -> str:
    return "|".join([
        str(tenant_id or "").strip(),
        str(int(lookback_days or 0)),
        str(today_iso or "").strip()[:10],
    ])


def _cached_weekly_manager_activity_summary_page(
    *,
    tenant_id: str,
    lookback_days: int,
    today_iso: str,
) -> tuple[dict[str, int], bool]:
    cache_key = _weekly_activity_page_cache_key(
        tenant_id=tenant_id,
        lookback_days=lookback_days,
        today_iso=today_iso,
    )
    now_ts = float(time.time())
    try:
        page_cache = st.session_state.get("_today_weekly_activity_page_cache")
        if not isinstance(page_cache, dict):
            page_cache = {}
            st.session_state["_today_weekly_activity_page_cache"] = page_cache
        cached = page_cache.get(cache_key)
        if isinstance(cached, dict):
            expires_at = float(cached.get("expires_at", 0.0) or 0.0)
            payload = cached.get("payload")
            if expires_at >= now_ts and isinstance(payload, dict):
                return dict(payload), True
            page_cache.pop(cache_key, None)
    except Exception:
        page_cache = None

    result = dict(
        _cached_weekly_manager_activity_summary(
            tenant_id=tenant_id,
            lookback_days=lookback_days,
            today_iso=today_iso,
        )
        or {}
    )

    if isinstance(page_cache, dict):
        if len(page_cache) >= 16:
            try:
                oldest_key = next(iter(page_cache))
                page_cache.pop(oldest_key, None)
            except Exception:
                pass
        page_cache[cache_key] = {
            "expires_at": now_ts + float(_READ_CACHE_TTL_SECONDS),
            "payload": dict(result),
        }

    return result, False


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_today_action_state_lookup(
    *,
    tenant_id: str,
    employee_ids: tuple[str, ...],
    today_iso: str,
) -> dict[str, dict[str, Any]]:
    with profile_block(
        "today.cache_miss.action_state_lookup",
        tenant_id=str(tenant_id or ""),
        context={"employee_ids": len(employee_ids or ()), "today_iso": str(today_iso or "")},
    ) as profile:
        with profile.stage("render_guard_log"):
            _log_heavy_render_compute("build_employee_action_state_lookup")
        profile.cache_miss("today_action_state_lookup")
        with profile.stage("today_iso_parse"):
            try:
                today_value = date.fromisoformat(str(today_iso or "")[:10])
            except Exception:
                today_value = date.today()
        with profile.stage("action_state_lookup_service"):
            lookup_payload = build_employee_action_state_lookup(
                employee_ids,
                tenant_id=tenant_id,
                today=today_value,
            )
        with profile.stage("lookup_result_materialize"):
            result = dict(lookup_payload or {})
        service_ms = int(profile.metrics.get("stage_action_state_lookup_service_ms", 0) or 0)
        elapsed_ms = int(max(0.0, (time.perf_counter() - profile.started_at) * 1000))
        profile.set("non_lookup_work_ms", int(max(0, elapsed_ms - service_ms)))
        profile.set("action_state_rows", len(result or {}))
        return result


def _action_state_page_cache_key(*, tenant_id: str, employee_ids: tuple[str, ...], today_iso: str) -> str:
    return "|".join([
        str(tenant_id or "").strip(),
        str(today_iso or "").strip()[:10],
        ",".join(str(emp or "").strip() for emp in (employee_ids or ())),
    ])


def _cached_today_action_state_lookup_page(
    *,
    tenant_id: str,
    employee_ids: tuple[str, ...],
    today_iso: str,
) -> tuple[dict[str, dict[str, Any]], bool]:
    cache_key = _action_state_page_cache_key(
        tenant_id=tenant_id,
        employee_ids=employee_ids,
        today_iso=today_iso,
    )
    try:
        page_cache = st.session_state.get("_today_action_state_page_cache")
        if not isinstance(page_cache, dict):
            page_cache = {}
            st.session_state["_today_action_state_page_cache"] = page_cache
        cached = page_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached), True
    except Exception:
        page_cache = None

    result = dict(
        _cached_today_action_state_lookup(
            tenant_id=tenant_id,
            employee_ids=employee_ids,
            today_iso=today_iso,
        )
        or {}
    )

    if isinstance(page_cache, dict):
        if len(page_cache) >= 32:
            try:
                oldest_key = next(iter(page_cache))
                page_cache.pop(oldest_key, None)
            except Exception:
                pass
        page_cache[cache_key] = dict(result)

    return result, False


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_today_signals_payload(*, tenant_id: str, as_of_date: str) -> dict[str, Any] | None:
    with profile_block(
        "today.cache_miss.signals_payload",
        tenant_id=str(tenant_id or ""),
        context={"as_of_date": str(as_of_date or "")},
    ) as profile:
        profile.cache_miss("today_signals_payload")
        result = get_today_signals(tenant_id=tenant_id, as_of_date=as_of_date)
        if isinstance(result, dict):
            profile.set("queue_items", len(result.get("queue_items") or []))
            profile.set("goal_status_rows", len(result.get("goal_status") or []))
        return result


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_today_signal_status_map(
    *,
    tenant_id: str,
    signal_keys_sorted: tuple[str, ...],
    today_iso: str,
) -> dict[str, dict[str, str]]:
    with profile_block(
        "today.cache_miss.signal_status_map",
        tenant_id=str(tenant_id or ""),
        context={"signal_keys": len(signal_keys_sorted or ()), "today_iso": str(today_iso or "")},
    ) as profile:
        profile.cache_miss("today_signal_status_map")
        result = list_latest_signal_statuses(
            signal_keys=set(signal_keys_sorted or ()),
            tenant_id=str(tenant_id or "").strip(),
        )
        profile.set("found_signal_keys", len(result or {}))
        return dict(result or {})


def _invalidate_today_write_caches() -> None:
    """Clear Today read caches after a successful write-side mutation."""
    for func in [
        _cached_today_action_state_lookup,
        _cached_today_signals_payload,
        _cached_today_signal_status_map,
        get_today_signals,
    ]:
        for method_name in ["cache_clear", "clear"]:
            if hasattr(func, method_name):
                try:
                    getattr(func, method_name)()
                except Exception:
                    pass
    try:
        page_cache = st.session_state.get("_today_action_state_page_cache")
        if isinstance(page_cache, dict):
            page_cache.clear()
    except Exception:
        pass
    try:
        weekly_page_cache = st.session_state.get("_today_weekly_activity_page_cache")
        if isinstance(weekly_page_cache, dict):
            weekly_page_cache.clear()
    except Exception:
        pass
    try:
        enriched_render_plan_cache = st.session_state.get("_today_enriched_render_plan_page_cache")
        if isinstance(enriched_render_plan_cache, dict):
            enriched_render_plan_cache.clear()
    except Exception:
        pass
    try:
        pre_action_render_plan_cache = st.session_state.get("_today_pre_action_render_plan_page_cache")
        if isinstance(pre_action_render_plan_cache, dict):
            pre_action_render_plan_cache.clear()
    except Exception:
        pass
    try:
        more_actions_cache = st.session_state.get("_today_more_actions_optional_data_cache")
        if isinstance(more_actions_cache, dict):
            more_actions_cache.clear()
    except Exception:
        pass
    try:
        stale_keys = [
            k for k in st.session_state
            if str(k or "").startswith(_TODAY_PAYLOAD_SESSION_CACHE_KEY_PREFIX)
        ]
        for k in stale_keys:
            st.session_state.pop(k, None)
    except Exception:
        pass


def _tenant_today_value(tenant_id: str = "") -> date:
    try:
        from services.settings_service import get_tenant_local_now

        return get_tenant_local_now(str(tenant_id or "")).date()
    except Exception as exc:
        raise RuntimeError("Tenant-local date is unavailable.") from exc


def _apply_today_styles() -> None:
    st.markdown(
        """
        <style>
                div.block-container {
                    padding-top: 1rem;
                    padding-bottom: 1.2rem;
                    max-width: min(1800px, 95vw) !important;
                }
                div[data-testid="stExpander"] details {
                    border: 0;
                    background: transparent;
                }
                div[data-testid="stExpander"] summary {
                    font-size: 0.88rem;
                }
                .today-page-header {
                    background: #FCFDFF;
                    border: 1px solid #E8EEF7;
                    border-radius: 0.62rem;
                    padding: 1rem 1.125rem;
                    margin-bottom: 1.5rem;
                }
                .today-page-header-kicker {
                    font-size: 0.75rem;
                    font-weight: 700;
                    letter-spacing: 0.08em;
                    text-transform: uppercase;
                    color: #5d7693;
                    margin-bottom: 0.375rem;
                }
                .today-page-header-headline {
                    font-size: 1.25rem;
                    font-weight: 800;
                    color: #0f2d52;
                    line-height: 1.2;
                    margin: 0 0 0.375rem 0;
                    letter-spacing: -0.01em;
                }
                .today-page-header-detail {
                    font-size: 0.88rem;
                    color: #5d7693;
                    line-height: 1.4;
                    margin: 0;
                }
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
                .today-section-container {
                    background: #FCFDFF;
                    border: 1px solid #E8EEF7;
                    border-radius: 0.62rem;
                    padding: 0.875rem 1rem;
                    margin-bottom: 1rem;
                }
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
            color: #0f2d52;
            font-weight: 700;
            margin-bottom: 0.25rem;
            letter-spacing: -0.005em;
        }
        .today-insight-title-priority {
            font-size: 1.08rem;
                        font-weight: 800;
                        letter-spacing: -0.01em;
            margin-bottom: 6px;
        }
        .today-insight-line {
            color: #182b40;
            font-size: 0.91rem;
            line-height: 1.42;
            margin: 0.25rem 0;
        }
        .today-insight-line-priority {
            font-size: 0.97rem;
            line-height: 1.42;
            margin: 4px 0;
        }
        .today-insight-meta {
            color: #5d7693;
            font-size: 0.82rem;
            margin-top: 0.375rem;
            line-height: 1.3;
        }
        .today-card-department {
            color: #5d7693;
            font-size: 0.81rem;
            margin-top: 0.125rem;
            margin-bottom: 0.25rem;
            font-weight: 500;
        }
        .today-card-meta-row {
            color: #60778f;
            font-size: 0.79rem;
            margin-top: 0.375rem;
            margin-bottom: 0;
            font-weight: 500;
            letter-spacing: 0.005em;
        }
        .today-card-next-check {
            color: #7a90a8;
            font-size: 0.81rem;
            margin-top: 0.5rem;
            margin-bottom: 0;
            font-style: italic;
            line-height: 1.35;
        }
        .today-action-instruction {
            font-size: 0.84rem;
            color: #7a90a8;
            margin-top: 0.25rem;
            margin-bottom: 0.75rem;
        }
        .today-card-handle-cue {
            font-size: 0.78rem;
            font-weight: 600;
            color: #1e4f82;
            margin-bottom: 4px;
            letter-spacing: 0.02em;
        }
        .today-priority-card-gap {
            height: 6px;
        }
        .today-action-frame-heading {
            font-size: 1.35rem;
            font-weight: 700;
            color: #0f2d52;
            margin-bottom: 3px;
            margin-top: 0;
        }
        .today-action-frame-sub {
            font-size: 0.86rem;
            color: #5d7693;
            margin-bottom: 12px;
            margin-top: 0;
        }
        .today-card-focus {
            border: 2px solid #9bc2e8;
            border-radius: 10px;
            padding: 6px;
            margin: 2px 0 10px;
            background: #f4f9ff;
        }
        .today-completed-state {
            border: 1px solid #b9e0be;
            background: #f0fbf2;
            color: #20603a;
            border-radius: 10px;
            padding: 8px 10px;
            margin-bottom: 8px;
            font-size: 0.9rem;
        }
        .today-focus-chip {
            display: inline-block;
            background: #e7f1fc;
            color: #1e4f82;
            border: 1px solid #c9dff4;
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 0.74rem;
            font-weight: 700;
            margin-bottom: 6px;
        }
        .today-confidence-badge-low {
            display: inline-block;
            background: #eef3f8;
            color: #49647f;
            border: 1px solid #d4e0ec;
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 0.78rem;
            font-weight: 600;
            margin-top: 7px;
        }
        .today-confidence-chip {
            display: inline-block;
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 0.74rem;
            font-weight: 700;
            margin-top: 4px;
            margin-bottom: 2px;
        }
        .today-confidence-chip-low {
            background: #eef3f8;
            color: #49647f;
            border: 1px solid #d4e0ec;
        }
        .today-confidence-chip-medium {
            background: #fff3df;
            color: #8a5a00;
            border: 1px solid #efd3a4;
        }
        .today-confidence-chip-high {
            background: #e8f5e9;
            color: #1f6f2a;
            border: 1px solid #b9e0be;
        }
        .today-freshness-meta {
            color: #5d7693;
            font-size: 0.8rem;
            margin-top: 4px;
        }
        .today-stale-banner {
            background: #fff7e8;
            border: 1px solid #f0d9a7;
            border-radius: 10px;
            padding: 10px 12px;
            margin-bottom: 10px;
            color: #7a5600;
            font-size: 0.9rem;
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
            margin-top: 0;
            margin-bottom: 0.625rem;
            color: #5d7693;
            font-size: 0.88rem;
            line-height: 1.4;
        }
        .today-update-indicator {
            margin-top: -6px;
            margin-bottom: 0.75rem;
                        line-height: 1.3;
            color: #5d7693;
            font-size: 0.8rem;
        }
        .today-action-helper {
            margin-top: -4px;
            margin-bottom: 0.5rem;
                        line-height: 1.35;
            color: #5d7693;
            font-size: 0.82rem;
        }
        .today-value-card {
            background: linear-gradient(180deg, #f9fbfe 0%, #eef4fb 100%);
            border: 1px solid #d9e4f0;
            border-radius: 14px;
            padding: 14px 14px 12px;
            min-height: 132px;
            margin-bottom: 10px;
        }
        .today-value-card-subtle {
            background: #fbfdff;
            border: 1px solid #e4ecf4;
            border-radius: 12px;
            padding: 12px 12px 10px;
            min-height: 118px;
            margin-bottom: 8px;
            box-shadow: none;
        }
        .today-value-title {
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #6a8098;
            margin-bottom: 8px;
        }
        .today-value-title-subtle {
            font-size: 0.69rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            color: #5d7693;
            margin-bottom: 6px;
        }
        .today-value-headline {
            color: #0f2d52;
            font-size: 1rem;
            font-weight: 800;
            line-height: 1.28;
            margin-bottom: 6px;
        }
        .today-value-headline-subtle {
            color: #214463;
            font-size: 0.95rem;
            font-weight: 700;
            line-height: 1.25;
            margin-bottom: 5px;
        }
        .today-value-detail {
            color: #49647f;
            font-size: 0.87rem;
            line-height: 1.38;
        }
        .today-value-detail-subtle {
            color: #607b95;
            font-size: 0.84rem;
            line-height: 1.34;
        }
        .today-secondary-context-label {
            display: inline-block;
            margin-bottom: 4px;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #5d7693;
        }
        .today-secondary-context-note {
            margin-top: -1px;
            margin-bottom: 8px;
            color: #5d7693;
            font-size: 0.86rem;
        }
        .today-secondary-label {
            margin-top: 10px;
            margin-bottom: 2px;
            color: #5d7693;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            text-transform: uppercase;
        }
        .today-secondary-subcaption {
            margin-top: 0;
            margin-bottom: 6px;
            color: #5d7693;
            font-size: 0.84rem;
        }
        .today-secondary-note {
            color: #5d7693;
            font-size: 0.82rem;
            margin-bottom: 8px;
        }
        .today-summary-title {
            font-size: 0.88rem;
            font-weight: 700;
            color: #0f2d52;
            margin-bottom: 2px;
        }
        .today-summary-subtitle {
                    .today-section-divider {
                        margin: 0.625rem 0;
                        border-top: 1px solid #EDF2F8;
                        height: 0;
                    }
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
        .attention-score-medium { background: #fef5e7; color: #7a4500; }
        .attention-score-low   { background: #f0f0f0; color: #555; }
        .today-queue-orientation {
            background: #FCFDFF;
            border: 1px solid #E8EEF7;
            border-radius: 10px;
            padding: 0.875rem 1rem;
            margin-bottom: 1rem;
            font-size: 0.88rem;
            color: #335a80;
            line-height: 1.5;
        }
        .today-queue-orientation-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 0.5rem;
        }
        .today-queue-chip {
            display: inline-block;
            background: #e8f0f8;
            color: #335a80;
            border-radius: 999px;
            padding: 2px 10px;
            font-size: 0.79rem;
            font-weight: 600;
        }
        .today-signal-status-chip {
            display: inline-block;
            color: #5d7693;
            font-size: 0.78rem;
            border: 1px solid #d8e3ef;
            border-radius: 999px;
            padding: 1px 8px;
            margin-bottom: 6px;
        }
        .today-action-state-chip {
            display: inline-block;
            font-size: 0.76rem;
            font-weight: 700;
            border-radius: 999px;
            padding: 2px 8px;
            margin-top: 2px;
            margin-bottom: 6px;
            border: 1px solid #d8e3ef;
        }
        .today-action-state-open {
            background: #eef3fa;
            color: #36506d;
            border-color: #d4e0ec;
        }
        .today-action-state-in-progress {
            background: #fff3e4;
            color: #8a5a00;
            border-color: #efd3a4;
        }
        .today-action-state-follow-up-scheduled {
            background: #e9f4ff;
            color: #19527c;
            border-color: #c8def1;
        }
        .today-action-state-resolved {
            background: #e8f5e9;
            color: #20603a;
            border-color: #b9e0be;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _show_flash_message() -> None:
    # Legacy key kept so existing callers (signal status) still work.
    legacy_msg = str(st.session_state.pop("today_flash_message", "") or "")
    if legacy_msg:
        set_flash_message(legacy_msg)
    consume_flash_message()


def _render_demo_reset_controls(*, import_summary: dict[str, Any], tenant_id: str) -> None:
    source_mode = str((import_summary or {}).get("source_mode") or "").strip().lower()
    if source_mode != "demo":
        return

    with st.container(border=True):
        st.markdown("**Reset demo data**")
        st.caption(
            "This removes demo-imported history from this workspace and keeps real uploaded data unchanged."
        )

        confirm_key = "confirm_reset_demo_data"
        confirmed = st.checkbox(
            "I understand this clears demo data only.",
            key=confirm_key,
        )
        if st.button(
            "Reset demo data",
            type="secondary",
            use_container_width=True,
            key="today_reset_demo_data",
            disabled=not bool(confirmed),
        ):
            try:
                with st.spinner("Resetting demo data and restoring history..."):
                    outcome = _reset_demo_uploads(tenant_id=tenant_id)
                    _bust_cache()
                    if hasattr(get_today_signals, "cache_clear"):
                        get_today_signals.cache_clear()
                    elif hasattr(get_today_signals, "clear"):
                        get_today_signals.clear()
                    st.session_state.pop("_today_precomputed_payload", None)
                    st.session_state.pop("_post_import_refresh_pending", None)
                    st.session_state.pop("_import_step3_preview_cache", None)
                    for _key in list(st.session_state.keys()):
                        if str(_key).startswith("_today_recovery_attempted_"):
                            st.session_state.pop(_key, None)
                    st.session_state[confirm_key] = False

                reset_count = int(outcome.get("demo_uploads_reset", 0) or 0)
                if reset_count > 0:
                    st.success(
                        "Demo data reset complete. "
                        f"Removed {reset_count} demo upload(s) from active history."
                    )
                else:
                    st.info("No active demo uploads were found to reset.")

                skipped = int(outcome.get("skipped_without_snapshot", 0) or 0)
                if skipped > 0:
                    st.warning(
                        f"{skipped} demo upload(s) had no rollback snapshot and were left unchanged."
                    )
                st.rerun()
            except Exception as exc:
                show_error_state(f"Demo reset failed: {exc}")


def _has_today_data(
    *,
    queue_items: list[dict[str, Any]],
    goal_status: list[dict[str, Any]],
    home_sections: dict[str, Any],
    import_summary: dict[str, Any],
) -> bool:
    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    employee_rows = []
    for row in list(_cached_employees() or []):
        if not isinstance(row, dict):
            continue
        row_tenant_id = str(row.get("tenant_id") or "")
        if tenant_id and row_tenant_id and row_tenant_id != tenant_id:
            continue
        employee_rows.append(row)

    has_employees = any(
        str(row.get("emp_id") or row.get("employee_id") or row.get("EmployeeID") or "").strip()
        for row in employee_rows
    )
    has_history = bool(goal_status) or int((import_summary or {}).get("days") or 0) > 0
    has_signals = bool(queue_items) or any(
        bool(cards)
        for section_key, cards in dict(home_sections or {}).items()
        if section_key != "suppressed_signals"
    )
    return bool(has_employees or has_history or has_signals)


def _render_first_value_screen() -> None:
    if not bool(st.session_state.get("_first_value_screen_shown_logged", False)):
        _log_operational_event(
            "first_value_screen_shown",
            status="success",
            tenant_id=str(st.session_state.get("tenant_id", "") or ""),
            user_email=str(st.session_state.get("user_email", "") or ""),
            context=build_onboarding_event_context({"entry": "today", "import_path": "upload"}),
        )
        st.session_state["_first_value_screen_shown_logged"] = True

    with st.container(border=True):
        st.markdown("### Get to your first value")
        st.write(
            "Today becomes useful after the app has roster or shift history to compare. "
            "This workspace is still waiting for an initial operating data set."
        )
        st.info(
            "Load sample data to see the full workflow in demo mode, or upload a file to start from your own history. "
            "After import, Today returns to the normal queue automatically."
        )

        sample_col, upload_col = st.columns(2)
        with sample_col:
            if st.button("Use sample data", type="primary", use_container_width=True, key="today_first_value_sample"):
                st.session_state["import_entry_mode"] = "Try sample data"
                st.session_state["_auto_load_sample_on_import_once"] = True
                st.session_state["goto_page"] = "import"
                st.rerun()
        with upload_col:
            if st.button("Upload your file", type="secondary", use_container_width=True, key="today_first_value_upload"):
                st.session_state["import_entry_mode"] = "Upload file"
                st.session_state["goto_page"] = "import"
                st.rerun()


def _render_today_interpretation_strip() -> None:
    with st.container(border=True):
        st.markdown('<div class="today-section-label">What you are seeing</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="today-supporting-note">This queue highlights where current data differs from expected or recent patterns.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="today-supporting-note">Each item shows why it surfaced and how reliable the evidence is.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="today-supporting-note">Low-confidence items are early signals, not final conclusions.</div>',
            unsafe_allow_html=True,
        )


def _render_top_status_area(*, meaning: TodaySurfaceMeaning) -> None:
    summary = dict(meaning.import_summary or {})
    source_mode = str(summary.get("source_mode") or "").strip().lower()
    source_label = str(summary.get("source_label") or "").strip()
    stale_days = int(meaning.state_flags.get("stale_days") or 0)

    status_parts: list[str] = []
    if stale_days <= 0:
        status_parts.append("Updated today")
    elif stale_days == 1:
        status_parts.append("Updated 1 day ago")
    else:
        status_parts.append(f"Updated {stale_days} days ago")

    if meaning.signal_mode == SignalMode.LIMITED_DATA:
        status_parts.append("Limited history")
    elif meaning.signal_mode == SignalMode.EARLY_SIGNAL:
        status_parts.append("Early signal mode")
    else:
        status_parts.append("Standard signal mode")

    if source_mode == "demo":
        status_parts.append("Demo mode")

    status_line = " | ".join(part for part in status_parts if str(part or "").strip())
    if status_line:
        st.caption(status_line)
    if source_mode == "demo" and source_label:
        st.caption(f"Source: {source_label}")


def _emit_today_loaded_with_data_once(*, tenant_id: str, import_summary: dict, queue_count: int) -> None:
    source_mode = str((import_summary or {}).get("source_mode") or "").strip().lower()
    path = "sample" if source_mode == "demo" else "upload"
    marker = f"{str(tenant_id or '')}:{path}:{int(queue_count)}"
    if str(st.session_state.get("_today_loaded_with_data_marker", "") or "") == marker:
        return

    _log_operational_event(
        "today_loaded_with_data",
        status="success",
        tenant_id=str(tenant_id or ""),
        user_email=str(st.session_state.get("user_email", "") or ""),
        context=build_onboarding_event_context(
            {
                "import_path": path,
                "queue_items": int(queue_count),
                "source_mode": source_mode or "upload",
            }
        ),
    )
    st.session_state["_today_loaded_with_data_marker"] = marker


def _render_return_trigger(trigger: TodayReturnTriggerViewModel | None) -> None:
    if trigger is None or not list(trigger.messages or []):
        return

    cue_html = ""
    block_style = ""
    if bool(trigger.show_cue):
        cue_label = str(trigger.cue_label or "Update").strip() or "Update"
        cue_html = f'<span class="today-queue-chip" aria-label="Update available">{cue_label}</span>'
        block_style = (
            ' style="border-left:3px solid #1f4f87;'
            'background:linear-gradient(90deg, rgba(31,79,135,0.08) 0%, rgba(31,79,135,0.03) 100%);"'
        )

    message_html = "".join(
        f'<span class="today-queue-chip">{message}</span>'
        for message in list(trigger.messages or [])[:3]
    )
    basis_html = ""
    if str(trigger.comparison_basis or "").strip():
        basis_html = (
            f'<div style="color:#5d7693;font-size:0.79rem;margin-top:6px;">{trigger.comparison_basis}</div>'
        )

    cue_block = f'<div class="today-queue-orientation-chips">{cue_html}</div>' if cue_html else ""
    message_block = f'<div class="today-queue-orientation-chips">{message_html}</div>'

    st.markdown(
        (
            f'<div class="today-queue-orientation"{block_style}>'
            f'<strong>{trigger.headline}</strong>'
            f'{cue_block}'
            f'{message_block}'
            f'{basis_html}'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


def _attempt_signal_payload_recovery(*, tenant_id: str, today_value: date) -> bool:
    """Compute today's signals without blocking on snapshot recompute.
    
    Uses per-date recovery lock to prevent concurrent rebuilds during Streamlit reruns.
    Returns True if recovery completed successfully, False if skipped or failed.
    """
    recovery_lock_key = f"_today_recovery_in_progress_{today_value.isoformat()}"
    recovery_started_at_key = f"_today_recovery_started_at_{today_value.isoformat()}"

    now_ts = time.time()
    started_at = float(st.session_state.get(recovery_started_at_key, 0.0) or 0.0)

    # If recovery is already in progress and not expired, skip
    if bool(st.session_state.get(recovery_lock_key)) and (now_ts - started_at) < _TODAY_RECOVERY_LOCK_TTL_SECONDS:
        return False

    # Acquire lock before any work
    st.session_state[recovery_lock_key] = True
    st.session_state[recovery_started_at_key] = now_ts
    cold_start_at = time.perf_counter()

    try:
        from services.daily_signals_service import build_transient_today_payload, compute_daily_signals
        from services.daily_snapshot_service import get_latest_snapshot_goal_status

        _log_today_milestone(
            "today_recovery_started",
            tenant_id=tenant_id,
            context={"today_iso": today_value.isoformat()},
        )

        # Check if snapshots need recomputation
        snapshot_check_at = time.perf_counter()
        latest_snapshot_date = ""
        try:
            _, _, latest_snapshot_date = get_latest_snapshot_goal_status(
                tenant_id=tenant_id,
                days=30,
                rebuild_if_missing=False,
            )
        except Exception as e:
            _log_app_error(
                "recovery_snapshot_check",
                f"Failed to check snapshot date: {e}",
                severity="warning",
            )
            latest_snapshot_date = ""
        snapshot_check_ms = int(max(0.0, (time.perf_counter() - snapshot_check_at) * 1000))

        post_import_refresh_pending = bool(st.session_state.get("_post_import_refresh_pending"))
        should_recompute_snapshots = bool(
            post_import_refresh_pending
            or latest_snapshot_date != today_value.isoformat()
        )
        has_snapshot_data = bool(str(latest_snapshot_date or "").strip())
        _log_today_milestone(
            "today_snapshot_check_done",
            tenant_id=tenant_id,
            context={
                "snapshot_check_ms": int(snapshot_check_ms),
                "latest_snapshot_date": str(latest_snapshot_date or ""),
                "snapshot_current": bool(latest_snapshot_date == today_value.isoformat()),
                "should_recompute": bool(should_recompute_snapshots),
            },
        )

        snapshot_recompute_ms = 0
        if should_recompute_snapshots:
            if post_import_refresh_pending:
                try:
                    from services.daily_snapshot_service import recompute_daily_employee_snapshots

                    recompute_started_at = time.perf_counter()
                    recompute_daily_employee_snapshots(tenant_id=tenant_id, days=1)
                    snapshot_recompute_ms = int(max(0.0, (time.perf_counter() - recompute_started_at) * 1000))
                    _log_today_milestone(
                        "today_snapshot_recompute_completed_sync",
                        tenant_id=tenant_id,
                        context={
                            "snapshot_recompute_ms": int(snapshot_recompute_ms),
                            "snapshot_available": bool(has_snapshot_data),
                            "latest_snapshot_date": str(latest_snapshot_date or ""),
                            "reason": "post_import_pending",
                        },
                    )
                except Exception as recompute_err:
                    _log_app_error(
                        "today_snapshot_recompute_sync_failed",
                        f"Sync snapshot recompute failed: {recompute_err}",
                        severity="warning",
                    )
                    async_started = _schedule_today_snapshot_recompute_async(
                        tenant_id=tenant_id,
                        today_value=today_value,
                        run_id=str(st.session_state.get(_TODAY_RUN_ID_DATE_KEY_PREFIX + today_value.isoformat()) or ""),
                        snapshot_available=bool(has_snapshot_data),
                        latest_snapshot_date=str(latest_snapshot_date or ""),
                    )
                    _log_today_milestone(
                        "today_snapshot_recompute_skipped_for_ui",
                        tenant_id=tenant_id,
                        context={
                            "async_started": bool(async_started),
                            "snapshot_available": bool(has_snapshot_data),
                            "latest_snapshot_date": str(latest_snapshot_date or ""),
                            "reason": "post_import_sync_failed",
                        },
                    )
            else:
                async_started = _schedule_today_snapshot_recompute_async(
                    tenant_id=tenant_id,
                    today_value=today_value,
                    run_id=str(st.session_state.get(_TODAY_RUN_ID_DATE_KEY_PREFIX + today_value.isoformat()) or ""),
                    snapshot_available=bool(has_snapshot_data),
                    latest_snapshot_date=str(latest_snapshot_date or ""),
                )
                _log_today_milestone(
                    "today_snapshot_recompute_skipped_for_ui",
                    tenant_id=tenant_id,
                    context={
                        "async_started": bool(async_started),
                        "snapshot_available": bool(has_snapshot_data),
                        "latest_snapshot_date": str(latest_snapshot_date or ""),
                        "reason": ("stale_snapshot_available" if has_snapshot_data else "snapshot_missing"),
                    },
                )

        # Compute daily signals
        signal_compute_at = time.perf_counter()
        try:
            compute_daily_signals(
                signal_date=today_value,
                tenant_id=tenant_id,
            )
            st.session_state["_post_import_refresh_pending"] = False
        except Exception as compute_err:
            message = str(compute_err or "")
            if "daily_signals" in message or "PGRST205" in message:
                # Fallback to transient payload
                st.session_state["_today_precomputed_payload"] = build_transient_today_payload(
                    signal_date=today_value,
                    tenant_id=tenant_id,
                )
            else:
                raise
        signal_compute_ms = int(max(0.0, (time.perf_counter() - signal_compute_at) * 1000))
        recovery_total_ms = int(max(0.0, (time.perf_counter() - cold_start_at) * 1000))
        _log_today_milestone(
            "today_signal_compute_done",
            tenant_id=tenant_id,
            context={
                "signal_compute_ms": int(signal_compute_ms),
                "recovery_total_ms": int(recovery_total_ms),
            },
        )

        _log_operational_event(
            "today_cold_load_signal_fetch_ms",
            status="info",
            tenant_id=str(tenant_id or ""),
            user_email=str(st.session_state.get("user_email", "") or ""),
            context={
                "snapshot_check_ms": int(snapshot_check_ms),
                "snapshot_recomputed": bool(should_recompute_snapshots),
                "snapshot_recompute_ms": int(snapshot_recompute_ms),
                "signal_compute_ms": int(signal_compute_ms),
                "recovery_total_ms": int(recovery_total_ms),
                "today_iso": today_value.isoformat(),
            },
        )

        # Clear session and in-process caches to force re-read of fresh payloads.
        try:
            stale_session_payload_keys = [
                k for k in st.session_state
                if str(k or "").startswith(_TODAY_PAYLOAD_SESSION_CACHE_KEY_PREFIX)
            ]
            for k in stale_session_payload_keys:
                st.session_state.pop(k, None)
        except Exception:
            pass

        # Clear caches to force re-read
        for func in [get_today_signals, _cached_today_signals_payload]:
            for method_name in ["cache_clear", "clear"]:
                if hasattr(func, method_name):
                    try:
                        getattr(func, method_name)()
                    except Exception as e:
                        _log_app_error(
                            "recovery_cache_clear",
                            f"Failed to clear cache: {e}",
                            severity="warning",
                        )

        return True

    except Exception as recovery_err:
        st.session_state["_post_import_refresh_pending"] = False
        _log_app_error(
            "recovery_failed",
            f"Signal recovery failed: {recovery_err}",
            severity="error",
        )
        show_error_state(f"Signal recovery failed: {recovery_err}")
        return False

    finally:
        # Clear lock to allow future attempts
        st.session_state[recovery_lock_key] = False


def _today_has_active_text_area_input() -> bool:
    # Streamlit doesn't expose focused-widget state directly, so treat non-empty
    # in-progress note fields as active editing and skip background refresh.
    for key, value in dict(st.session_state).items():
        key_text = str(key or "")
        if not key_text:
            continue
        if (
            key_text.endswith("_completion_note")
            or key_text.endswith("_exception_note")
            or key_text.endswith("_follow_through_note")
            or key_text.startswith("today_complete_") and key_text.endswith("_note")
        ):
            if bool(str(value or "").strip()):
                return True
    return False


def _should_auto_refresh_signals() -> bool:
    last_refresh = float(st.session_state.get("last_refresh", 0.0) or 0.0)
    time_since = float(time.time()) - last_refresh
    if "last_refresh" not in st.session_state or time_since > _TODAY_AUTO_REFRESH_MIN_SECONDS:
        return True
    return False


def _updated_indicator_text() -> str:
    last_refresh = float(st.session_state.get("last_refresh", 0.0) or 0.0)
    if last_refresh <= 0:
        return "Updated just now"
    elapsed = max(0, int((time.time() - last_refresh) // 60))
    if elapsed <= 0:
        return "Updated just now"
    if elapsed == 1:
        return "Updated 1 min ago"
    return f"Updated {elapsed} min ago"


def _precomputed_payload_looks_stale(*, precomputed: dict[str, Any] | None, tenant_id: str, today_value: date) -> bool:
    """Detect broken demo payloads where summary is inconsistent with imported rows.
    
    Returns True if:
    - Demo mode + substantial rows (>100) + payload summary is suspiciously empty
    - AND valid snapshots exist for today but aren't reflected in payload
    """
    payload = dict(precomputed or {})
    import_summary = dict(payload.get("import_summary") or {})
    source_mode = str(import_summary.get("source_mode") or "").strip().lower()
    if source_mode != "demo":
        return False

    # Use explicit None checks for numeric fields
    rows_processed = int(
        import_summary.get("valid_rows")
        if import_summary.get("valid_rows") is not None
        else (import_summary.get("rows_processed") or 0)
    )
    emp_count = int(import_summary.get("emp_count") or 0)
    days = int(import_summary.get("days") or 0)
    queue_items = list(payload.get("queue_items") or [])

    # Only check for substantial imports where inconsistency is obvious
    if rows_processed < 100:
        return False
    if queue_items:
        return False  # Has queue content

    # Check consistency: with this many rows, emp_count and days must be reasonable
    # Heuristic: expect minimum 2 rows/employee/day (conservative for demo)
    min_expected_rows = emp_count * max(days, 1) * 2
    if emp_count > 0 and days > 0 and rows_processed >= min_expected_rows:
        return False  # Summary looks consistent

    # Summary looks broken; check if today's snapshots actually exist
    try:
        from services.daily_snapshot_service import get_latest_snapshot_goal_status

        goal_status, _, snapshot_date = get_latest_snapshot_goal_status(
            tenant_id=tenant_id,
            days=30,
            rebuild_if_missing=False,
        )
        # If snapshots for today exist but payload is broken, payload is stale
        if snapshot_date == today_value.isoformat() and len(goal_status) > 0:
            return True
    except Exception as e:
        _log_app_error(
            "stale_detection_snapshot_check",
            f"Error checking snapshots during stale detection: {e}",
            severity="warning",
        )
        # Conservative: if we can't verify snapshots, treat as potentially stale
        # so recovery can be attempted (safer than showing broken state)

    return False


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


def _should_load_previous_payload_for_return_trigger(*, queue_items: list[dict], today_value: date) -> bool:
    """Return True when return-trigger comparison needs previous-day payload.

    This keeps header behavior for meaningful queue states while skipping
    low-value previous-day reads when no trigger-relevant signals are present.
    """
    today_iso = today_value.isoformat()
    for item in list(queue_items or []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("_queue_status") or "").strip().lower()
        if status in {"overdue", "due_today"}:
            return True
        created_at_prefix = str(item.get("created_at") or "").strip()[:10]
        if created_at_prefix == today_iso:
            return True
    return False


def _build_last_action_lookup(queue_items: list[dict]) -> dict[str, str]:
    """Build {employee_id: iso_date_str} from precomputed queue items.

    Uses ``last_event_at`` as the primary date — this is updated by Supabase
    every time a coaching event, follow-through log, or status change is
    recorded against the action, which makes it the most product-correct
    proxy for "last time a manager touched this employee's case".

    Falls back to ``created_at`` when ``last_event_at`` is absent (can happen
    on brand-new actions before any follow-on event has been logged).

    Only the most-recent date per employee is kept. Employees with no queue
    item produce no entry (caller treats missing key as "no data").
    """
    best: dict[str, str] = {}
    for item in list(queue_items or []):
        emp_id = str(item.get("employee_id") or "").strip()
        if not emp_id:
            continue
        raw = str(item.get("last_event_at") or item.get("created_at") or "").strip()
        if not raw:
            continue
        date_prefix = raw[:10]
        if emp_id not in best or date_prefix > best[emp_id]:
            best[emp_id] = date_prefix
    return best


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


def _render_queue_orientation_block(
    orientation: TodayQueueOrientationModel,
    *,
    meaning: TodaySurfaceMeaning,
    surface_state: TodaySurfaceState,
    signal_mode: SignalMode | None = None,
) -> None:
    """Render a compact framing line directly above the Today queue.

    Describes what stands out without recommending or prescribing anything.
    For zero-signal states, renders a calm trust-oriented placeholder instead.
    In early/limited signal mode, labels the queue accordingly.
    """
    in_early = surface_state == TodaySurfaceState.EARLY_SIGNAL or signal_mode in {
        SignalMode.EARLY_SIGNAL,
        SignalMode.LIMITED_DATA,
    }
    total = orientation.total_shown

    if total == 0:
        if surface_state == TodaySurfaceState.NO_USABLE_DATA:
            st.markdown(
                (
                    '<div class="today-queue-orientation">'
                    "<strong>Initial data setup is in progress.</strong><br>"
                    '<span style="color:#5d7693;font-size:0.86rem;">'
                    "Today will surface comparison signals once uploaded history is processed."
                    "</span>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            return

        evaluated = int(orientation.total_evaluated or 0)
        if evaluated > 0:
            checked_line = f"{evaluated} snapshot record{'s' if evaluated != 1 else ''} checked."
        elif bool((meaning.state_flags or {}).get("low_data")) or bool((meaning.state_flags or {}).get("partial_data")):
            checked_line = "Imported records were detected, but comparable history is still building."
        else:
            checked_line = "Available records were checked."

        if in_early:
            mode_label = "Limited history" if signal_mode == SignalMode.LIMITED_DATA else "Early signal mode"
        else:
            mode_label = "Coverage stable"

        secondary_lines: list[str] = []
        if in_early:
            secondary_lines.append("Coverage is limited, so smaller changes may not be visible yet.")
        else:
            secondary_lines.append("Coverage and history were sufficient for normal threshold checks.")

        if orientation.repeat_count <= 0:
            secondary_lines.append("No clear repeat patterns were detected in the checked records.")

        if bool((meaning.state_flags or {}).get("partial_data")) and not in_early:
            secondary_lines.append("Some comparisons remain partial in this snapshot.")

        details_html = "".join(
            f'<div style="color:#5d7693;font-size:0.85rem;margin-top:4px;">{line}</div>'
            for line in secondary_lines[:3]
        )

        st.markdown(
            (
                '<div class="today-queue-orientation">'
                "<strong>No strong signals surfaced today.</strong>"
                f'<div class="today-queue-orientation-chips"><span class="today-queue-chip">{mode_label}</span></div>'
                f'<div style="margin-top:6px;color:#5d7693;font-size:0.86rem;">{checked_line} The system checked today\'s available performance and history and did not find a clear issue that stood out.</div>'
                f"{details_html}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        return

    # Non-empty queue
    if total == 1:
        heading = "1 signal surfaced now"
    elif total <= 3:
        heading = "A few signals surfaced now"
    else:
        heading = f"{total} signals surfaced now"

    if in_early:
        mode_label = (
            "Limited history" if signal_mode == SignalMode.LIMITED_DATA else "Early signal mode"
        )
        chips: list[str] = [mode_label]
        # For snapshot-only mode, chips just identify mode — no trend chips
        if not in_early or orientation.declining_count > 0:
            n = orientation.declining_count
            if n:
                chips.append(f"{n} declining trend{'s' if n != 1 else ''}")
        if orientation.repeat_count > 0:
            n = orientation.repeat_count
            chips.append(f"{n} repeat issue{'s' if n != 1 else ''}")
        if orientation.limited_confidence_count > 0:
            n = orientation.limited_confidence_count
            chips.append(f"{n} with limited data confidence")
    else:
        chips = []
        if orientation.declining_count > 0:
            n = orientation.declining_count
            chips.append(f"{n} declining trend{'s' if n != 1 else ''}")
        if orientation.repeat_count > 0:
            n = orientation.repeat_count
            chips.append(f"{n} repeat issue{'s' if n != 1 else ''}")
        if orientation.limited_confidence_count > 0:
            n = orientation.limited_confidence_count
            chips.append(f"{n} with limited data confidence")

    chips.append(f"{total} total in queue")

    chips_html = "".join(f'<span class="today-queue-chip">{c}</span>' for c in chips)
    chips_block = (
        f'<div class="today-queue-orientation-chips">{chips_html}</div>' if chips else ""
    )
    st.markdown(
        (
            '<div class="today-queue-orientation">'
            f"<strong>{heading}</strong>"
            f"{chips_block}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_attention_summary_strip(strip: TodayAttentionStripViewModel) -> None:
    """Render compact metric tiles above the queue.

    Uses st.metric for operational density. Same-day reinforcement metrics are
    only shown when precomputed values are positive so quiet states stay quiet.
    """
    metric_tiles: list[tuple[str, int]] = [
        ("Needing attention", strip.total_needing_attention),
        ("New today", strip.new_today),
        ("Overdue follow-ups", strip.overdue_follow_ups),
    ]
    if strip.reviewed_today is not None:
        metric_tiles.append(("Reviewed today", strip.reviewed_today))
    if strip.touchpoints_logged_today is not None:
        metric_tiles.append(("Touchpoints logged", strip.touchpoints_logged_today))
    if strip.follow_ups_scheduled_today is not None:
        metric_tiles.append(("Follow-ups set", strip.follow_ups_scheduled_today))

    cols = st.columns(len(metric_tiles))
    for idx, (label, value) in enumerate(metric_tiles):
        with cols[idx]:
            st.metric(label, value)


def _render_manager_loop_strip(strip: TodayManagerLoopStripViewModel | None) -> None:
    """Render compact manager follow-through counts above Today cards."""
    if strip is None:
        return

    tiles: list[tuple[str, int]] = [
        ("Open loops", int(strip.open_loops or 0)),
        ("Due today", int(strip.due_today or 0)),
        ("Overdue", int(strip.overdue or 0)),
        ("Improved", int(strip.improved or 0)),
        ("No action yet", int(strip.no_action_yet or 0)),
    ]

    st.markdown('<div class="today-secondary-context-label">Manager loop</div>', unsafe_allow_html=True)
    cols = st.columns(len(tiles))
    for idx, (label, value) in enumerate(tiles):
        with cols[idx]:
            with st.container(border=True):
                st.caption(label)
                st.markdown(f"**{value}**")


def _render_weekly_summary_block(summary: TodayWeeklySummaryViewModel) -> None:
    if not list(summary.items or []):
        return

    st.markdown('<div class="today-secondary-context-label">This week</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="today-secondary-context-note">Recent management activity and logged outcomes.</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(min(4, max(1, len(summary.items))))
    for idx, item in enumerate(summary.items[:4]):
        with cols[idx]:
            with st.container(border=True):
                st.caption(item.headline)


def _render_empty_state() -> None:
    with st.container(border=True):
        st.markdown("### No strong signals surfaced today")
        st.write(
            "That means the queue is clear for the moment. This page becomes valuable when fresh productivity data "
            "turns into a short list of surfaced signals with noteworthy changes, follow-up context, or recognition patterns."
        )
        st.info("The queue updates when newer data snapshots are available.")


def _render_first_time_empty_state() -> None:
    """Onboarding-focused empty state for users who just completed first import."""
    with st.container(border=True):
        st.markdown("### Early signals are ready")
        st.markdown(
            "You have enough data for early signal visibility. Some signals may be low confidence until "
            "more shifts are imported."
        )
        st.info("Early signals are shown below. Confidence is limited until more history is available.")
        if st.button("📁 Import more shifts", type="secondary", use_container_width=True, key="first_time_import_more"):
            st.session_state["goto_page"] = "import"
            st.rerun()


def _render_filtered_empty_state() -> None:
    with st.container(border=True):
        st.markdown("### Nothing matches this filter")
        st.write("The queue still has active work, but none of it fits the selected summary bucket.")
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
    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    return _cached_employee_option_map(tenant_id=tenant_id)


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_employee_option_map(*, tenant_id: str) -> tuple[list[str], dict[str, dict]]:
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
                    set_flash_message("Exception logged.")
                    st.rerun()
                else:
                    show_error_state("Operational exception could not be saved right now.")


def _render_open_exceptions(*, tenant_id: str) -> None:
    summary = summarize_open_operational_exceptions(tenant_id=tenant_id)
    rows = summary.get("rows") or []

    st.markdown('<div class="today-section-label">Operational Exceptions</div>', unsafe_allow_html=True)
    st.markdown('<div class="today-supporting-note">Active operational context that may help explain current performance signals.</div>', unsafe_allow_html=True)
    _render_exception_create_form(tenant_id=tenant_id, today_value=date.today())

    if not rows:
        with st.container(border=True):
            st.markdown("No active operational exceptions are currently logged.")
        return

    m1, m2 = st.columns(2)
    m1.metric("Active exceptions", int(summary.get("open_count", 0) or 0))
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
                "<div class=\"today-insight-line\"><strong>Why shown:</strong> Shown because this exception is still active and may affect current performance interpretation.</div>",
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
                            _invalidate_today_write_caches()
                            set_flash_message("Follow-through saved.")
                            st.rerun()
                        else:
                            show_error_state("Exception follow-through could not be saved right now.")

            c1, c2 = st.columns(2)
            with c1:
                if str(row.get("employee_id") or "") and st.button("Employee detail", key=f"today_exception_open_{exception_id}", use_container_width=True):
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
                        set_flash_message("Issue resolved.")
                        st.rerun()
                    else:
                        show_error_state("Operational exception could not be resolved right now.")


def _go_to_drill_down(item: InsightCardContract) -> None:
    def _clean_handoff_text(value: str) -> str:
        clean = " ".join(str(value or "").split()).strip()
        if not clean:
            return ""
        lowered = clean.lower()
        blocked_tokens = (
            "signal_key=",
            "signal_id=",
            "employee_id=",
            "tenant_id=",
            "debug",
            "internal",
            "{",
            "[",
        )
        if any(token in lowered for token in blocked_tokens):
            return ""
        return clean[:140]

    def _build_handoff_payload(card: InsightCardContract, employee_id: str) -> dict[str, str]:
        metadata = dict(getattr(card, "metadata", {}) or {})
        reason = _clean_handoff_text(str(getattr(card, "what_happened", "") or ""))
        if not reason:
            reason = _clean_handoff_text(str(getattr(card, "why_flagged", "") or ""))
        follow_up_status = _clean_handoff_text(
            str(
                metadata.get("follow_up_status")
                or metadata.get("follow_up_due")
                or metadata.get("follow_up_due_at")
                or ""
            )
        )
        signal_id = str(
            metadata.get("signal_id")
            or metadata.get("today_signal_id")
            or ""
        ).strip()
        signal_key = str(
            metadata.get("signal_key")
            or metadata.get("today_signal_key")
            or ""
        ).strip()
        return {
            "employee_id": str(employee_id or "").strip(),
            "signal_id": signal_id,
            "signal_key": signal_key,
            "reason": reason,
            "follow_up_status": follow_up_status,
        }

    screen = str(item.drill_down.screen or "")
    entity_id = str(item.drill_down.entity_id or "")
    st.session_state["_drill_traceability_context"] = traceability_payload_from_card(item)

    if screen == "employee_detail":
        st.session_state["goto_page"] = "team"
        st.session_state["emp_view"] = "Performance Journal"
        if entity_id:
            st.session_state["cn_selected_emp"] = entity_id
            st.session_state[_TODAY_TO_TEAM_HANDOFF_KEY] = _build_handoff_payload(item, entity_id)
            st.session_state.pop(_TEAM_TO_TODAY_FOCUS_KEY, None)
    elif screen == "team_process":
        st.session_state["goto_page"] = "team"
    elif screen == "import_data_trust":
        st.session_state["goto_page"] = "import"
    elif screen == "today":
        st.session_state["goto_page"] = "today"
    else:
        st.session_state["goto_page"] = "today"

    st.rerun()


def _estimate_recent_record_count(item: InsightCardContract) -> int:
    candidates: list[Any] = [
        item.confidence.sample_size,
        item.traceability.included_rows,
        item.metadata.get("sample_size"),
        item.metadata.get("included_rows"),
        item.metadata.get("recent_record_count"),
    ]
    for candidate in candidates:
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 1


def _build_attention_explanation_lines(signal: DisplaySignal, fallback_summary: str = "") -> list[str]:
    lines: list[str] = []
    mode = get_signal_display_mode(signal)

    if mode == SignalDisplayMode.LOW_DATA:
        lines.append("History is still building for this signal.")
        lines.append(format_confidence_line(signal))
    elif mode == SignalDisplayMode.CURRENT_STATE:
        lines.append(format_signal_label(signal))
        observed_line = format_observed_line(signal)
        if observed_line:
            lines.append(observed_line)
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
        if len(unique_lines) == 3:
            break
    return unique_lines


def _confidence_chip(line_5_text: str) -> str:
    text = str(line_5_text or "").strip()
    lowered = text.lower()
    if not lowered:
        return ""
    if "confidence: high" in lowered:
        return '<div class="today-confidence-chip today-confidence-chip-high">High confidence</div>'
    if "confidence: medium" in lowered:
        return '<div class="today-confidence-chip today-confidence-chip-medium">Medium confidence</div>'
    return ""


def _is_low_confidence_overdue_card(card: TodayQueueCardViewModel, line_5_text: str) -> bool:
    lowered_confidence = str(line_5_text or "").strip().lower()
    is_low_confidence = "low confidence" in lowered_confidence or "confidence: low" in lowered_confidence
    if not is_low_confidence:
        return False

    state = str(getattr(card, "normalized_action_state", "") or "").strip().lower()
    state_detail = str(getattr(card, "normalized_action_state_detail", "") or "").strip().lower()
    line_3 = str(getattr(card, "line_3", "") or "").strip().lower()
    line_4 = str(getattr(card, "line_4", "") or "").strip().lower()
    return any("overdue" in value for value in (state, state_detail, line_3, line_4))


def _format_signal_status_label(signal_status: str) -> str:
    normalized = str(signal_status or "").strip().lower()
    if normalized == SIGNAL_STATUS_LOOKED_AT:
        return "Completed"
    if normalized == SIGNAL_STATUS_NEEDS_FOLLOW_UP:
        return "Pending follow-up"
    return ""


def _format_follow_up_month_day(value: date) -> str:
    return f"{value.strftime('%b')} {value.day}"


def _today_follow_up_status_text(card: TodayQueueCardViewModel, *, today_value: date | None = None) -> str:
    today_value = today_value or date.today()
    state = str(getattr(card, "normalized_action_state", "") or "").strip().lower()
    detail = str(getattr(card, "normalized_action_state_detail", "") or "").strip()
    detail_lower = detail.lower()

    if "overdue" in detail_lower or "overdue" in state:
        return "Follow-up overdue"
    if "due today" in detail_lower:
        return "Follow-up due today"
    if detail_lower.startswith("due "):
        due_text = detail[4:].strip()[:10]
        try:
            due_date = date.fromisoformat(due_text)
        except Exception:
            due_date = None
        if due_date is not None:
            if due_date < today_value:
                return "Follow-up overdue"
            if due_date == today_value:
                return "Follow-up due today"
            return f"Follow-up scheduled for {_format_follow_up_month_day(due_date)}"
    if "follow-up scheduled" in state:
        return "Follow-up scheduled"
    return "No follow-up scheduled"


def _build_today_last_check_result(*, note_text: str, follow_up_choice: str, follow_up_at: datetime | None) -> str:
    clean_note = " ".join(str(note_text or "").split()).strip()
    if clean_note:
        return clean_note[:160]

    choice = str(follow_up_choice or "").strip()
    if choice == "No follow-up needed":
        return "No follow-up needed"
    if follow_up_at is not None:
        return f"Follow-up scheduled for {_format_follow_up_month_day(follow_up_at.date())}"
    return "Reviewed and logged"


def _action_state_chip(card: TodayQueueCardViewModel) -> str:
    state = str(getattr(card, "normalized_action_state", "") or "").strip()
    if not state:
        return ""
    css_suffix = state.lower().replace(" ", "-").replace("/", "-")
    return (
        f'<div class="today-action-state-chip today-action-state-{css_suffix}">{state}</div>'
    )


def _today_card_signal_id(card: TodayQueueCardViewModel) -> str:
    signal_id = str(getattr(card, "signal_key", "") or "").strip()
    if signal_id:
        return signal_id
    return _today_card_session_key(card)


def _today_more_actions_open_key(card: TodayQueueCardViewModel) -> str:
    return f"today_more_actions_open_{_today_signal_scope_token(_today_card_signal_id(card))}"


def _today_signal_scope_token(signal_id: str) -> str:
    raw = str(signal_id or "").strip()
    if not raw:
        return "unknown"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _today_completion_widget_key(*, signal_id: str, field: str) -> str:
    return f"today_complete_{_today_signal_scope_token(signal_id)}_{str(field or '').strip()}"


def _today_has_active_interaction_state() -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if _today_has_active_text_area_input():
        reasons.append("text_input")

    pending_ids = list(st.session_state.get(_TODAY_PENDING_COMPLETION_IDS_KEY) or [])
    if pending_ids:
        reasons.append("pending_completion")

    for key, value in dict(st.session_state).items():
        key_text = str(key or "")
        if not key_text:
            continue
        if key_text.startswith("today_more_actions_open_") and bool(value):
            reasons.append("more_actions_open")
            break

    for key, value in dict(st.session_state).items():
        key_text = str(key or "")
        if not key_text.startswith("today_complete_"):
            continue
        if key_text.endswith("_follow_up_needed") and str(value or "") in {"Yes", "No"}:
            reasons.append("follow_up_selected")
            break

    unique_reasons = sorted({reason for reason in reasons if str(reason or "").strip()})
    return bool(unique_reasons), unique_reasons


def _log_refresh_redundant_prevented(*, last_refresh_ts: float) -> None:
    now_ts = float(time.time())
    last_log_ts = float(st.session_state.get("_today_refresh_interval_skip_logged_at", 0.0) or 0.0)
    if now_ts - last_log_ts < 60.0:
        return

    elapsed_seconds = max(0.0, now_ts - float(last_refresh_ts or 0.0)) if last_refresh_ts > 0 else 0.0
    _log_operational_event(
        "today_refresh_redundant_prevented",
        status="info",
        tenant_id=str(st.session_state.get("tenant_id", "") or ""),
        user_email=str(st.session_state.get("user_email", "") or ""),
        context={
            "elapsed_seconds": int(elapsed_seconds),
            "min_interval_seconds": int(_TODAY_AUTO_REFRESH_MIN_SECONDS),
        },
    )
    st.session_state["_today_refresh_interval_skip_logged_at"] = now_ts


def _cleanup_today_widget_state(*, active_signal_ids: set[str]) -> int:
    active_tokens = {
        _today_signal_scope_token(signal_id)
        for signal_id in active_signal_ids
        if str(signal_id or "").strip()
    }
    active_tokens.update(_today_signal_scope_token(signal_id) for signal_id in _get_pending_completion_signal_keys())

    removed = 0
    for key in list(st.session_state.keys()):
        key_text = str(key or "")
        if key_text.startswith("today_complete_"):
            suffix = key_text[len("today_complete_"):]
            token = suffix.split("_", 1)[0]
            if token and token not in active_tokens:
                st.session_state.pop(key, None)
                removed += 1
                continue

        if key_text.startswith("today_more_actions_open_"):
            token = key_text[len("today_more_actions_open_"):]
            if token and token not in active_tokens:
                st.session_state.pop(key, None)
                removed += 1
                continue

        if key_text.startswith("today_more_actions_data_"):
            token = key_text[len("today_more_actions_data_"):]
            if token and token not in active_tokens:
                st.session_state.pop(key, None)
                removed += 1

    if removed > 0:
        _log_operational_event(
            "today_widget_state_cleanup",
            status="info",
            tenant_id=str(st.session_state.get("tenant_id", "") or ""),
            user_email=str(st.session_state.get("user_email", "") or ""),
            context={"removed_keys": int(removed), "active_signals": len(active_signal_ids)},
        )
    return int(removed)


def _today_more_actions_data_cache_key(card: TodayQueueCardViewModel) -> str:
    return f"today_more_actions_data_{_today_signal_scope_token(_today_card_signal_id(card))}"


def _get_today_more_actions_optional_data(*, card: TodayQueueCardViewModel, tenant_id: str) -> dict[str, Any]:
    cache_key = _today_more_actions_data_cache_key(card)
    employee_id = str(card.employee_id or "").strip()
    signal_id = _today_card_signal_id(card)
    page_cache = st.session_state.get("_today_more_actions_optional_data_cache")
    if not isinstance(page_cache, dict):
        page_cache = {}
        st.session_state["_today_more_actions_optional_data_cache"] = page_cache

    cached = page_cache.get(cache_key)
    if isinstance(cached, dict):
        if str(cached.get("tenant_id") or "") == str(tenant_id or "") and str(cached.get("employee_id") or "") == employee_id:
            _log_operational_event(
                "today_more_actions_optional_data_cache_hit",
                status="info",
                detail="reused cached optional data",
                tenant_id=str(tenant_id or ""),
                user_email=str(st.session_state.get("user_email", "") or ""),
                context={
                    "signal_id": signal_id,
                    "employee_id": employee_id,
                    "exception_rows": len(cached.get("exception_rows") or []),
                },
            )
            return {**cached, "cache_hit": True}

    with profile_block(
        "today.more_actions_optional_data",
        tenant_id=str(tenant_id or ""),
        user_email=str(st.session_state.get("user_email", "") or ""),
        context={"signal_id": signal_id, "employee_id": employee_id},
    ) as profile:
        profile.cache_miss("today_more_actions_optional_data")
        with profile.stage("load_open_exceptions"):
            exception_rows = list(
                list_open_operational_exceptions(
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    limit=25,
                )
                or []
            )
        profile.set("exception_rows", len(exception_rows or []))

    exception_options = {"Select exception": ""}
    for row in exception_rows:
        row_id = str(row.get("id") or "").strip()
        row_summary = str(row.get("summary") or "Operational exception").strip()
        if not row_id:
            continue
        exception_options[f"#{row_id[:8]} - {row_summary[:70]}"] = row_id

    payload = {
        "tenant_id": str(tenant_id or ""),
        "employee_id": employee_id,
        "exception_rows": exception_rows,
        "exception_options": exception_options,
    }
    page_cache[cache_key] = dict(payload)
    return {**payload, "cache_hit": False}


@st.fragment
def _render_today_more_actions_fragment(
    *,
    card: TodayQueueCardViewModel,
    key_prefix: str,
    tenant_id: str,
    add_exception_key: str,
    exception_type_key: str,
    exception_note_key: str,
) -> None:
    employee_id = str(card.employee_id or "").strip()
    signal_id = _today_card_signal_id(card)
    open_key = _today_more_actions_open_key(card)
    is_open = bool(st.session_state.get(open_key, False))

    toggle_label = "Hide more actions" if is_open else "More actions"
    if st.button(
        toggle_label,
        key=_today_completion_widget_key(signal_id=signal_id, field="more_actions_toggle"),
        type="secondary",
        use_container_width=False,
    ):
        is_open = not is_open
        st.session_state[open_key] = is_open
        _log_operational_event(
            "today_more_actions_toggle",
            status="info",
            detail="opened" if is_open else "closed",
            tenant_id=str(tenant_id or ""),
            user_email=str(st.session_state.get("user_email", "") or ""),
            context={
                "signal_id": signal_id,
                "employee_id": employee_id,
                "open": bool(is_open),
                "interaction_scope": "fragment",
            },
        )

    if not is_open:
        return

    optional_data = _get_today_more_actions_optional_data(card=card, tenant_id=tenant_id)
    exception_options = dict(optional_data.get("exception_options") or {"Select exception": ""})
    cache_hit = bool(optional_data.get("cache_hit"))
    st.caption("Optional exception and follow-through details for this signal.")
    st.caption("Loaded from cache." if cache_hit else "Loaded for this signal.")

    add_operational_exception = st.checkbox(
        "Add operational exception",
        value=bool(st.session_state.get(add_exception_key, False)),
        key=add_exception_key,
    )
    if add_operational_exception:
        st.selectbox(
            "Exception type",
            options=list(EXCEPTION_CATEGORIES),
            key=exception_type_key,
        )
        st.text_area(
            "Exception note",
            value=str(st.session_state.get(exception_note_key) or ""),
            key=exception_note_key,
            height=70,
            placeholder="Brief context for the exception.",
        )

    link_existing_exception_key = _today_completion_widget_key(signal_id=signal_id, field="link_existing_exception")
    existing_exception_choice_key = _today_completion_widget_key(signal_id=signal_id, field="existing_exception_choice")
    add_follow_through_key = _today_completion_widget_key(signal_id=signal_id, field="add_follow_through")
    follow_through_status_key = _today_completion_widget_key(signal_id=signal_id, field="follow_through_status")
    follow_through_note_key = _today_completion_widget_key(signal_id=signal_id, field="follow_through_note")
    link_follow_through_key = _today_completion_widget_key(signal_id=signal_id, field="link_follow_through_to_exception")

    link_existing_exception = st.checkbox(
        "Link to existing exception",
        value=bool(st.session_state.get(link_existing_exception_key, False)),
        key=link_existing_exception_key,
    )
    if link_existing_exception:
        if len(exception_options) <= 1:
                st.caption("No active exceptions are currently available to link for this employee.")
        st.selectbox(
            "Existing exception",
            options=list(exception_options.keys()),
            key=existing_exception_choice_key,
        )

    add_follow_through = st.checkbox(
        "Add follow-through",
        value=bool(st.session_state.get(add_follow_through_key, False)),
        key=add_follow_through_key,
    )
    if add_follow_through:
        st.selectbox(
            "Follow-through status",
            options=list(FOLLOW_THROUGH_STATUSES),
            index=0,
            key=follow_through_status_key,
        )
        st.text_area(
            "Follow-through note",
            value=str(st.session_state.get(follow_through_note_key) or ""),
            key=follow_through_note_key,
            height=70,
            placeholder="Add a short follow-through update.",
        )
        st.checkbox(
            "Link follow-through to exception",
            value=bool(st.session_state.get(link_follow_through_key, False)),
            key=link_follow_through_key,
        )


def _save_today_card_completion(
    *,
    card: TodayQueueCardViewModel,
    note_text: str,
    follow_up_choice: str = "",
    follow_up_required: bool,
    follow_up_at: datetime | None,
    add_operational_exception: bool = False,
    exception_type: str = "",
    exception_note: str = "",
    linked_existing_exception_id: str = "",
    add_follow_through: bool = False,
    follow_through_status: str = "logged",
    follow_through_note: str = "",
    link_follow_through_to_exception: bool = False,
    owner_value: str = "",
    tenant_id: str = "",
    user_role: str = "",
) -> bool:
    signal_id = _today_card_signal_id(card)
    signal_key = str(getattr(card, "signal_key", "") or "").strip()
    employee_id = str(card.employee_id or "").strip()
    clean_note = str(note_text or "").strip()
    owner_value = str(owner_value or st.session_state.get("user_email") or st.session_state.get("user_name") or "").strip()
    tenant_id = str(tenant_id or st.session_state.get("tenant_id") or "").strip()
    user_role = str(user_role or st.session_state.get("user_role") or "").strip()

    if not signal_id:
        signal_id = signal_key or employee_id
    if not signal_id:
        raise ValueError("signal_id is required for completion persistence.")
    if not employee_id:
        raise ValueError("employee_id is required for completion persistence.")
    if not tenant_id:
        raise ValueError("tenant_id is required for completion persistence.")

    follow_up_due_date = follow_up_at.date().isoformat() if follow_up_required and follow_up_at else ""
    due_at_label = follow_up_at.isoformat(timespec="minutes") if follow_up_required and follow_up_at else ""
    last_check_result = _build_today_last_check_result(
        note_text=clean_note,
        follow_up_choice=follow_up_choice,
        follow_up_at=follow_up_at,
    )
    linked_exception_id = ""
    linked_existing_exception_id = str(linked_existing_exception_id or "").strip()

    _log_operational_event(
        "today_mark_complete_persistence_payload",
        status="info",
        tenant_id=tenant_id,
        user_email=owner_value,
        context={
            "signal_id": signal_id,
            "signal_key": signal_key,
            "employee_id": employee_id,
            "tenant_id": tenant_id,
            "note": clean_note,
            "follow_up_choice": str(follow_up_choice or ""),
            "follow_up_required": bool(follow_up_required),
            "follow_up_at": due_at_label,
            "add_operational_exception": bool(add_operational_exception),
            "exception_type": str(exception_type or ""),
            "link_existing_exception": bool(linked_existing_exception_id),
            "add_follow_through": bool(add_follow_through),
            "follow_through_status": str(follow_through_status or "logged"),
        },
    )
    try:
        if add_operational_exception:
            category = str(exception_type or "").strip()
            exception_note_clean = str(exception_note or "").strip()
            if not category or not exception_note_clean:
                raise ValueError("exception_type and exception_note are required when add_operational_exception is selected.")

            line_1 = str(getattr(card, "line_1", "") or "").strip()
            line_1_parts = [part.strip() for part in line_1.split("·") if str(part or "").strip()]
            employee_name = line_1_parts[0] if line_1_parts else str(card.employee_id or "").strip()
            department = str(getattr(card, "process_id", "") or "").strip()

            summary_text = exception_note_clean.split("\n", 1)[0].strip() or "Operational exception linked from Today card"
            created_exception = create_operational_exception(
                exception_date=date.today().isoformat(),
                category=category,
                summary=summary_text,
                employee_id=str(card.employee_id or "").strip(),
                employee_name=employee_name,
                department=department,
                shift="",
                process_name=department,
                notes=exception_note_clean,
                created_by=owner_value or "supervisor",
                tenant_id=tenant_id,
                user_role=user_role,
            )
            linked_exception_id = str((created_exception or {}).get("id") or "").strip()
            if not linked_exception_id:
                raise RuntimeError("Operational exception write returned no id.")

        resolved_exception_id = linked_exception_id or linked_existing_exception_id

        details_lines = ["Reviewed and logged", f"Last check result: {last_check_result}"]
        if due_at_label:
            details_lines.append(f"Next follow-up: {_format_follow_up_month_day(follow_up_at.date())}")
        if clean_note and clean_note.lower() != last_check_result.lower():
            details_lines.append(f"Note: {clean_note}")
        details_payload = "\n".join(details_lines)

        follow_through_saved = log_follow_through_event(
            employee_id=employee_id,
            linked_exception_id=resolved_exception_id,
            owner=owner_value or "supervisor",
            status="pending" if follow_up_required else "done",
            due_date=follow_up_due_date,
            details=details_payload,
            outcome=last_check_result,
            tenant_id=tenant_id,
        )
        if not follow_through_saved:
            raise RuntimeError("Primary follow-through write returned no row.")

        if follow_up_required and due_at_label:
            _log_operational_event(
                "today_follow_up_created",
                status="success",
                tenant_id=tenant_id,
                user_email=owner_value,
                context={
                    "signal_id": signal_id,
                    "signal_key": signal_key,
                    "employee_id": employee_id,
                    "follow_up_due_date": follow_up_due_date,
                    "follow_up_due_at": due_at_label,
                    "source": "today_mark_complete",
                },
            )

        clean_follow_through_note = str(follow_through_note or "").strip()
        if add_follow_through and clean_follow_through_note:
            secondary_follow_through_saved = log_follow_through_event(
                employee_id=employee_id,
                linked_exception_id=(resolved_exception_id if link_follow_through_to_exception else ""),
                owner=owner_value or "supervisor",
                status=str(follow_through_status or "logged"),
                due_date=follow_up_due_date,
                details=clean_follow_through_note,
                outcome=last_check_result,
                tenant_id=tenant_id,
            )
            if not secondary_follow_through_saved:
                raise RuntimeError("Secondary follow-through write returned no row.")

        # Preserve existing coaching journal history used by employee timelines.
        try:
            coaching_note = (
                f"Last check result: {last_check_result}"
                + (f"\nNext follow-up: {_format_follow_up_month_day(follow_up_at.date())}" if due_at_label else "")
                + (f"\nNote: {clean_note}" if clean_note and clean_note.lower() != last_check_result.lower() else "")
            )
            add_coaching_note(employee_id, coaching_note, owner_value or "supervisor")
        except Exception:
            pass

        if signal_key:
            status_saved = bool(
                set_signal_status(
                    signal_key=signal_key,
                    employee_id=employee_id,
                    signal_status=SIGNAL_STATUS_LOOKED_AT,
                    owner=owner_value,
                    tenant_id=tenant_id,
                )
            )
            if not status_saved:
                raise RuntimeError("Signal status write returned false.")

        return True
    except Exception as error:
        _log_operational_event(
            "today_mark_complete_error",
            status="error",
            tenant_id=tenant_id,
            user_email=owner_value,
            context={
                "signal_id": signal_id,
                "signal_key": signal_key,
                "employee_id": employee_id,
                "tenant_id": tenant_id,
                "note": clean_note,
                "follow_up_required": bool(follow_up_required),
                "follow_up": due_at_label,
                "error": str(error),
            },
        )
        raise


def _narrow_invalidate_today_completion_caches(*, card: TodayQueueCardViewModel) -> None:
    employee_id = str(getattr(card, "employee_id", "") or "").strip()
    signal_key = str(getattr(card, "signal_key", "") or "").strip()

    try:
        action_state_page_cache = st.session_state.get("_today_action_state_page_cache")
        if isinstance(action_state_page_cache, dict) and employee_id:
            stale_keys = [
                key
                for key in list(action_state_page_cache.keys())
                if employee_id in str(key or "").split("|", 2)[-1].split(",")
            ]
            for key in stale_keys:
                action_state_page_cache.pop(key, None)
    except Exception:
        pass

    try:
        more_actions_cache = st.session_state.get("_today_more_actions_optional_data_cache")
        if isinstance(more_actions_cache, dict):
            stale_keys = [
                key
                for key in list(more_actions_cache.keys())
                if (signal_key and signal_key in str(key or ""))
                or (employee_id and employee_id in str((more_actions_cache.get(key) or {}).get("employee_id") or ""))
            ]
            for key in stale_keys:
                more_actions_cache.pop(key, None)
    except Exception:
        pass


def _get_pending_completion_signal_keys() -> set[str]:
    values = st.session_state.get(_TODAY_PENDING_COMPLETION_SIGNAL_KEYS_KEY)
    return {
        str(value or "").strip()
        for value in list(values or [])
        if str(value or "").strip()
    }


def _set_pending_completion_signal_keys(values: set[str]) -> None:
    st.session_state[_TODAY_PENDING_COMPLETION_SIGNAL_KEYS_KEY] = sorted(
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    )


def _defer_today_completion_widget_reset(*, card: TodayQueueCardViewModel) -> None:
    signal_id = _today_card_signal_id(card)
    if not signal_id:
        return

    pending_signal_ids = {
        str(value or "").strip()
        for value in list(st.session_state.get(_TODAY_DEFERRED_WIDGET_RESET_SIGNAL_IDS_KEY) or [])
        if str(value or "").strip()
    }
    pending_signal_ids.add(signal_id)
    st.session_state[_TODAY_DEFERRED_WIDGET_RESET_SIGNAL_IDS_KEY] = sorted(pending_signal_ids)


def _apply_deferred_today_widget_resets() -> int:
    signal_ids = [
        str(value or "").strip()
        for value in list(st.session_state.get(_TODAY_DEFERRED_WIDGET_RESET_SIGNAL_IDS_KEY) or [])
        if str(value or "").strip()
    ]
    if not signal_ids:
        return 0

    removed = 0
    for signal_id in signal_ids:
        token = _today_signal_scope_token(signal_id)
        widget_prefix = f"today_complete_{token}_"
        more_actions_key = f"today_more_actions_open_{token}"
        more_actions_data_key = f"today_more_actions_data_{token}"

        for key in list(st.session_state.keys()):
            key_text = str(key or "")
            if key_text.startswith(widget_prefix) or key_text == more_actions_key or key_text == more_actions_data_key:
                st.session_state.pop(key, None)
                removed += 1

    st.session_state.pop(_TODAY_DEFERRED_WIDGET_RESET_SIGNAL_IDS_KEY, None)
    return int(removed)


def _optimistically_complete_today_card(
    *,
    card: TodayQueueCardViewModel,
    note_key: str,
    follow_up_key: str,
    add_exception_key: str,
    exception_note_key: str,
    more_actions_open_key: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    card_session_key = _today_card_session_key(card)
    completed_items = list(st.session_state.get(_TODAY_COMPLETED_ITEMS_SESSION_KEY) or [])
    if card_session_key and card_session_key not in completed_items:
        completed_items.append(card_session_key)
    st.session_state[_TODAY_COMPLETED_ITEMS_SESSION_KEY] = completed_items
    st.session_state[_TODAY_FOCUS_NEXT_CARD_KEY] = True
    _defer_today_completion_widget_reset(card=card)

    # Keep queue projection in memory aligned so next visible card promotes without waiting for a reload.
    removed_queue_items: list[dict[str, Any]] = []
    removed_insert_index = -1
    try:
        payload = st.session_state.get("_today_precomputed_payload")
        if isinstance(payload, dict):
            queue_items = list(payload.get("queue_items") or [])
            signal_key = str(getattr(card, "signal_key", "") or "").strip()
            employee_id = str(getattr(card, "employee_id", "") or "").strip()
            process_id = str(getattr(card, "process_id", "") or "").strip()
            filtered_items: list[dict[str, Any]] = []
            for idx, item in enumerate(queue_items):
                if not isinstance(item, dict):
                    continue
                item_signal_key = str(item.get("signal_key") or "").strip()
                item_employee_id = str(item.get("employee_id") or "").strip()
                item_process_id = str(item.get("process") or item.get("process_id") or "").strip()
                is_match = False
                if signal_key and item_signal_key:
                    is_match = item_signal_key == signal_key
                elif employee_id:
                    is_match = item_employee_id == employee_id and (not process_id or item_process_id == process_id)
                if is_match:
                    if removed_insert_index < 0:
                        removed_insert_index = int(idx)
                    removed_queue_items.append(dict(item))
                    continue
                filtered_items.append(item)
            payload["queue_items"] = filtered_items
            st.session_state["_today_precomputed_payload"] = payload
    except Exception:
        pass

    return {
        "queue_update_ms": int(max(0.0, (time.perf_counter() - started) * 1000)),
        "removed_queue_items": removed_queue_items,
        "removed_insert_index": int(removed_insert_index),
    }


def _start_today_completion_write_async(*, completion_id: str, payload: dict[str, Any]) -> None:
    write_started = time.perf_counter()
    result_payload: dict[str, Any]
    try:
        card_payload = dict(payload.get("card") or {})
        card = TodayQueueCardViewModel(**card_payload)
        _log_operational_event(
            "today_mark_complete_write_payload",
            status="info",
            tenant_id=str(payload.get("tenant_id") or ""),
            user_email=str(payload.get("owner_value") or ""),
            context={
                "completion_id": str(completion_id),
                "signal_id": _today_card_signal_id(card),
                "signal_key": str(getattr(card, "signal_key", "") or ""),
                "employee_id": str(getattr(card, "employee_id", "") or ""),
                "tenant_id": str(payload.get("tenant_id") or ""),
                "note": str(payload.get("note_text") or "").strip(),
                "follow_up": bool(payload.get("follow_up_required", False)),
                "follow_up_at": str(payload.get("follow_up_at") or ""),
            },
        )
        write_ok = _save_today_card_completion(
            card=card,
            note_text=str(payload.get("note_text") or ""),
            follow_up_required=bool(payload.get("follow_up_required", False)),
            follow_up_at=payload.get("follow_up_at"),
            add_operational_exception=bool(payload.get("add_operational_exception", False)),
            exception_type=str(payload.get("exception_type") or ""),
            exception_note=str(payload.get("exception_note") or ""),
            linked_existing_exception_id=str(payload.get("linked_existing_exception_id") or ""),
            add_follow_through=bool(payload.get("add_follow_through", False)),
            follow_through_status=str(payload.get("follow_through_status") or "logged"),
            follow_through_note=str(payload.get("follow_through_note") or ""),
            link_follow_through_to_exception=bool(payload.get("link_follow_through_to_exception", False)),
            owner_value=str(payload.get("owner_value") or ""),
            tenant_id=str(payload.get("tenant_id") or ""),
            user_role=str(payload.get("user_role") or ""),
        )
        if not write_ok:
            raise RuntimeError("Completion write returned false.")
        result_payload = {
            "status": "success",
            "backend_write_ms": int(max(0.0, (time.perf_counter() - write_started) * 1000)),
            "error": "",
        }
    except Exception as exc:
        result_payload = {
            "status": "failed",
            "backend_write_ms": int(max(0.0, (time.perf_counter() - write_started) * 1000)),
            "error": str(exc or "write failed"),
        }

    with _TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        _TODAY_COMPLETION_ASYNC_RESULTS[completion_id] = result_payload


def _drain_today_async_completion_results() -> None:
    pending_ids = list(st.session_state.get(_TODAY_PENDING_COMPLETION_IDS_KEY) or [])
    if not pending_ids:
        return

    meta_map = dict(st.session_state.get(_TODAY_PENDING_COMPLETION_META_KEY) or {})
    pending_signal_keys = _get_pending_completion_signal_keys()
    remaining_ids: list[str] = []
    completed_ok = 0
    completed_failed = 0
    failed_errors: list[str] = []
    completion_feedback_message = ""

    def _feedback_message_from_meta(meta: dict[str, Any]) -> str:
        follow_up_choice = str(meta.get("follow_up_choice") or "").strip()
        follow_up_at = meta.get("follow_up_at")
        if follow_up_choice in {"Follow up tomorrow", "Pick a date"} or isinstance(follow_up_at, datetime):
            return "Marked complete. Follow-up scheduled."
        if follow_up_choice == "No follow-up needed":
            return "Marked complete."
        return "Marked complete. Next item moved up."

    for completion_id in pending_ids:
        with _TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
            result = _TODAY_COMPLETION_ASYNC_RESULTS.pop(str(completion_id), None)
        if not isinstance(result, dict):
            remaining_ids.append(str(completion_id))
            continue

        meta = dict(meta_map.pop(str(completion_id), {}) or {})
        status = str(result.get("status") or "failed").strip().lower()
        signal_id = str(meta.get("signal_id") or "").strip()
        if signal_id:
            pending_signal_keys.discard(signal_id)
        card_payload = dict(meta.get("card") or {})
        try:
            card = TodayQueueCardViewModel(**card_payload)
        except Exception:
            card = None

        queue_update_ms = int(meta.get("queue_update_ms", 0) or 0)
        click_to_ui_update_ms = int(meta.get("click_to_ui_update_ms", 0) or 0)
        backend_write_ms = int(result.get("backend_write_ms", 0) or 0)
        end_to_end_ms = int(max(0.0, (time.time() - float(meta.get("clicked_at", time.time()) or time.time())) * 1000))

        _log_operational_event(
            "today_mark_complete_timing",
            status="info" if status == "success" else "warning",
            tenant_id=str(st.session_state.get("tenant_id", "") or ""),
            user_email=str(st.session_state.get("user_email", "") or ""),
            context={
                "completion_id": str(completion_id),
                "click_to_ui_update_ms": int(click_to_ui_update_ms),
                "queue_update_ms": int(queue_update_ms),
                "backend_write_ms": int(backend_write_ms),
                "end_to_end_ms": int(end_to_end_ms),
                "result": status,
            },
        )

        if status == "success" and card is not None:
            completed_ok += 1
            completion_feedback_message = _feedback_message_from_meta(meta)
            _narrow_invalidate_today_completion_caches(card=card)
            _log_operational_event(
                "today_mark_complete_persisted",
                status="success",
                tenant_id=str(st.session_state.get("tenant_id", "") or ""),
                user_email=str(st.session_state.get("user_email", "") or ""),
                context={
                    "completion_id": str(completion_id),
                    "signal_id": signal_id,
                },
            )
            continue

        completed_failed += 1
        failed_errors.append(str(result.get("error") or "write failed"))
        card_session_key = str(meta.get("card_session_key") or "").strip()
        if card_session_key:
            completed_items = [
                str(item or "").strip()
                for item in list(st.session_state.get(_TODAY_COMPLETED_ITEMS_SESSION_KEY) or [])
                if str(item or "").strip()
            ]
            st.session_state[_TODAY_COMPLETED_ITEMS_SESSION_KEY] = [
                item for item in completed_items if item != card_session_key
            ]

        # Restore optimistic queue removal without introducing duplicates.
        try:
            payload = st.session_state.get("_today_precomputed_payload")
            if isinstance(payload, dict):
                queue_items = list(payload.get("queue_items") or [])
                removed_items = [
                    dict(item)
                    for item in list(meta.get("removed_queue_items") or [])
                    if isinstance(item, dict)
                ]
                insert_at = int(meta.get("removed_insert_index", -1) or -1)
                for restored in removed_items:
                    restored_signal = str(restored.get("signal_key") or "").strip()
                    restored_emp = str(restored.get("employee_id") or "").strip()
                    restored_process = str(restored.get("process") or restored.get("process_id") or "").strip()
                    duplicate = False
                    for existing in queue_items:
                        if not isinstance(existing, dict):
                            continue
                        existing_signal = str(existing.get("signal_key") or "").strip()
                        existing_emp = str(existing.get("employee_id") or "").strip()
                        existing_process = str(existing.get("process") or existing.get("process_id") or "").strip()
                        if restored_signal and existing_signal and restored_signal == existing_signal:
                            duplicate = True
                            break
                        if (not restored_signal) and restored_emp and existing_emp == restored_emp and existing_process == restored_process:
                            duplicate = True
                            break
                    if duplicate:
                        continue
                    safe_insert_at = max(0, min(int(insert_at if insert_at >= 0 else len(queue_items)), len(queue_items)))
                    queue_items.insert(safe_insert_at, restored)
                    insert_at = safe_insert_at + 1

                payload["queue_items"] = queue_items
                st.session_state["_today_precomputed_payload"] = payload
        except Exception:
            pass

        # Restore user-entered values so failed writes can be retried without retyping.
        restore_note_key = str(meta.get("note_key") or "").strip()
        restore_follow_up_key = str(meta.get("follow_up_key") or "").strip()
        restore_due_date_key = str(meta.get("due_date_key") or "").strip()
        restore_due_time_key = str(meta.get("due_time_key") or "").strip()
        restore_note_value = str(meta.get("note_text") or "")
        restore_follow_up_value = str(meta.get("follow_up_choice") or "")
        restore_due_at = meta.get("follow_up_at")

        if restore_note_key and not str(st.session_state.get(restore_note_key) or "").strip():
            st.session_state[restore_note_key] = restore_note_value
        if restore_follow_up_key and str(st.session_state.get(restore_follow_up_key) or "") in {"", "Select one"}:
            st.session_state[restore_follow_up_key] = restore_follow_up_value or "Select one"
        if isinstance(restore_due_at, datetime):
            if restore_due_date_key and not st.session_state.get(restore_due_date_key):
                st.session_state[restore_due_date_key] = restore_due_at.date()
            if restore_due_time_key and not st.session_state.get(restore_due_time_key):
                st.session_state[restore_due_time_key] = restore_due_at.time()

        _log_operational_event(
            "today_mark_complete_rollback",
            status="warning",
            tenant_id=str(st.session_state.get("tenant_id", "") or ""),
            user_email=str(st.session_state.get("user_email", "") or ""),
            context={
                "completion_id": str(completion_id),
                "signal_id": signal_id,
                "error": str(result.get("error") or "write failed"),
            },
        )

    st.session_state[_TODAY_PENDING_COMPLETION_IDS_KEY] = remaining_ids
    st.session_state[_TODAY_PENDING_COMPLETION_META_KEY] = meta_map
    _set_pending_completion_signal_keys(pending_signal_keys)
    _log_operational_event(
        "today_mark_complete_pending_queue",
        status="info",
        tenant_id=str(st.session_state.get("tenant_id", "") or ""),
        user_email=str(st.session_state.get("user_email", "") or ""),
        context={"pending_count": len(remaining_ids)},
    )

    if completed_ok > 0 and completion_feedback_message:
        st.session_state[_TODAY_COMPLETION_FEEDBACK_MESSAGE_KEY] = completion_feedback_message
    if completed_failed > 0:
        first_error = next((err for err in failed_errors if str(err or "").strip()), "write failed")
        show_error_state(f"Save failed: {first_error}")


def _render_guided_completion_controls(*, card: TodayQueueCardViewModel, key_prefix: str, status_map: dict[str, dict[str, str]]) -> None:
    signal_key = str(getattr(card, "signal_key", "") or "").strip()
    employee_id = str(card.employee_id or "").strip()
    if not employee_id:
        return

    signal_id = _today_card_signal_id(card)
    note_key = _today_completion_widget_key(signal_id=signal_id, field="note")
    follow_up_key = _today_completion_widget_key(signal_id=signal_id, field="follow_up_needed")
    due_date_key = _today_completion_widget_key(signal_id=signal_id, field="follow_up_date")
    add_exception_key = _today_completion_widget_key(signal_id=signal_id, field="add_exception")
    exception_type_key = _today_completion_widget_key(signal_id=signal_id, field="exception_type")
    exception_note_key = _today_completion_widget_key(signal_id=signal_id, field="exception_note")
    submit_key = _today_completion_widget_key(signal_id=signal_id, field="submit")

    follow_up_status_text = _today_follow_up_status_text(card)
    if follow_up_status_text:
        st.caption(follow_up_status_text)

    add_operational_exception = False
    selected_exception_type = ""
    operational_exception_note = ""
    linked_existing_exception_id = ""
    add_follow_through = False
    selected_follow_through_status = "logged"
    follow_through_note = ""
    link_follow_through_to_exception = False

    tenant_id = str(st.session_state.get("tenant_id") or "").strip()
    more_actions_open_key = _today_more_actions_open_key(card)
    _render_today_more_actions_fragment(
        card=card,
        key_prefix=key_prefix,
        tenant_id=tenant_id,
        add_exception_key=add_exception_key,
        exception_type_key=exception_type_key,
        exception_note_key=exception_note_key,
    )

    add_operational_exception = bool(st.session_state.get(add_exception_key, False))
    selected_exception_type = str(st.session_state.get(exception_type_key) or "")
    operational_exception_note = str(st.session_state.get(exception_note_key) or "")
    link_existing_exception_key = _today_completion_widget_key(signal_id=signal_id, field="link_existing_exception")
    existing_exception_choice_key = _today_completion_widget_key(signal_id=signal_id, field="existing_exception_choice")
    add_follow_through_key = _today_completion_widget_key(signal_id=signal_id, field="add_follow_through")
    follow_through_status_key = _today_completion_widget_key(signal_id=signal_id, field="follow_through_status")
    follow_through_note_key = _today_completion_widget_key(signal_id=signal_id, field="follow_through_note")
    link_follow_through_key = _today_completion_widget_key(signal_id=signal_id, field="link_follow_through_to_exception")

    link_existing_exception = bool(st.session_state.get(link_existing_exception_key, False))
    add_follow_through = bool(st.session_state.get(add_follow_through_key, False))
    selected_follow_through_status = str(st.session_state.get(follow_through_status_key) or "logged")
    follow_through_note = str(st.session_state.get(follow_through_note_key) or "")
    link_follow_through_to_exception = bool(st.session_state.get(link_follow_through_key, False))

    linked_exception_label = str(st.session_state.get(existing_exception_choice_key) or "")
    linked_existing_exception_id = ""
    if link_existing_exception:
        optional_data = _get_today_more_actions_optional_data(card=card, tenant_id=tenant_id)
        linked_existing_exception_id = str((optional_data.get("exception_options") or {}).get(linked_exception_label) or "").strip()

    pending_signal_keys = _get_pending_completion_signal_keys()
    is_signal_pending = bool(signal_id and signal_id in pending_signal_keys)

    quick_reviewed_key = _today_completion_widget_key(signal_id=signal_id, field="quick_reviewed")
    quick_follow_tomorrow_key = _today_completion_widget_key(signal_id=signal_id, field="quick_follow_tomorrow")

    def _queue_completion_submission(
        *,
        submit_note_text: str,
        submit_follow_up_choice: str,
        submit_follow_up_due_at: datetime | None,
        submit_add_operational_exception: bool,
        submit_exception_type: str,
        submit_operational_exception_note: str,
        submit_link_existing_exception: bool,
        submit_linked_existing_exception_id: str,
        submit_add_follow_through: bool,
        submit_follow_through_status: str,
        submit_follow_through_note: str,
        submit_link_follow_through_to_exception: bool,
    ) -> None:
        if is_signal_pending:
            _log_operational_event(
                "today_mark_complete_duplicate_prevented",
                status="info",
                tenant_id=str(st.session_state.get("tenant_id", "") or ""),
                user_email=str(st.session_state.get("user_email", "") or ""),
                context={
                    "signal_id": signal_id,
                    "reason": "signal_already_pending",
                },
            )
            return

        if submit_add_operational_exception and not str(submit_operational_exception_note or "").strip():
            st.warning("Add an exception note before completing.")
            return
        if submit_link_existing_exception and not submit_linked_existing_exception_id:
            st.warning("Select an existing exception to link.")
            return
        if submit_add_follow_through and not str(submit_follow_through_note or "").strip():
            st.warning("Add a follow-through note before completing.")
            return
        if submit_link_follow_through_to_exception and not (submit_linked_existing_exception_id or submit_add_operational_exception):
            st.warning("Create or link an exception before linking follow-through.")
            return

        click_started = time.perf_counter()
        optimistic_state = _optimistically_complete_today_card(
            card=card,
            note_key=note_key,
            follow_up_key=follow_up_key,
            add_exception_key=add_exception_key,
            exception_note_key=exception_note_key,
            more_actions_open_key=more_actions_open_key,
        )
        queue_update_ms = int(optimistic_state.get("queue_update_ms", 0) or 0)

        completion_id = uuid4().hex
        card_session_key = _today_card_session_key(card)
        owner_value = str(st.session_state.get("user_email") or st.session_state.get("user_name") or "").strip()
        tenant_id = str(st.session_state.get("tenant_id") or "").strip()
        user_role = str(st.session_state.get("user_role") or "").strip()
        st.session_state["_today_last_clicked_completion_signal_id"] = signal_id
        write_payload = {
            "card": dataclasses.asdict(card),
            "note_text": str(submit_note_text or ""),
            "follow_up_choice": str(submit_follow_up_choice or "Select one"),
            "follow_up_required": bool(submit_follow_up_choice in {"Follow up tomorrow", "Pick a date"}),
            "follow_up_at": submit_follow_up_due_at,
            "add_operational_exception": bool(submit_add_operational_exception),
            "exception_type": str(submit_exception_type or ""),
            "exception_note": str(submit_operational_exception_note or ""),
            "linked_existing_exception_id": str(submit_linked_existing_exception_id or ""),
            "add_follow_through": bool(submit_add_follow_through),
            "follow_through_status": str(submit_follow_through_status or "logged"),
            "follow_through_note": str(submit_follow_through_note or ""),
            "link_follow_through_to_exception": bool(submit_link_follow_through_to_exception),
            "owner_value": owner_value,
            "tenant_id": tenant_id,
            "user_role": user_role,
        }

        pending_ids = list(st.session_state.get(_TODAY_PENDING_COMPLETION_IDS_KEY) or [])
        pending_ids.append(completion_id)
        st.session_state[_TODAY_PENDING_COMPLETION_IDS_KEY] = pending_ids
        pending_signal_keys.add(signal_id)
        _set_pending_completion_signal_keys(pending_signal_keys)
        pending_meta = dict(st.session_state.get(_TODAY_PENDING_COMPLETION_META_KEY) or {})
        click_to_ui_update_ms = int(max(0.0, (time.perf_counter() - click_started) * 1000))
        pending_meta[completion_id] = {
            "clicked_at": float(time.time()),
            "click_to_ui_update_ms": int(click_to_ui_update_ms),
            "queue_update_ms": int(queue_update_ms),
            "signal_id": signal_id,
            "card_session_key": card_session_key,
            "card": dataclasses.asdict(card),
            "removed_queue_items": list(optimistic_state.get("removed_queue_items") or []),
            "removed_insert_index": int(optimistic_state.get("removed_insert_index", -1) or -1),
            "note_key": note_key,
            "follow_up_key": follow_up_key,
            "due_date_key": due_date_key,
            "note_text": str(submit_note_text or ""),
            "follow_up_choice": str(submit_follow_up_choice or "Select one"),
            "follow_up_at": submit_follow_up_due_at,
        }
        st.session_state[_TODAY_PENDING_COMPLETION_META_KEY] = pending_meta

        _log_operational_event(
            "today_mark_complete_ui_update",
            status="info",
            tenant_id=tenant_id,
            user_email=owner_value,
            context={
                "completion_id": completion_id,
                "click_to_ui_update_ms": int(click_to_ui_update_ms),
                "queue_update_ms": int(queue_update_ms),
                "pending_count": len(pending_ids),
            },
        )

        _log_operational_event(
            "today_mark_complete_pending_queue",
            status="info",
            tenant_id=tenant_id,
            user_email=owner_value,
            context={"pending_count": len(pending_ids)},
        )

        _start_today_completion_write_async(completion_id=completion_id, payload=write_payload)
        st.rerun()

    quick_actions_enabled = (
        not bool(str(st.session_state.get(note_key) or "").strip())
        and str(st.session_state.get(follow_up_key) or "Select one") == "Select one"
    )
    if not is_signal_pending:
        st.caption("Quick actions")
        quick_cols = st.columns([1, 1])
        with quick_cols[0]:
            quick_reviewed_clicked = st.button(
                "Review done",
                key=quick_reviewed_key,
                type="secondary",
                use_container_width=True,
                disabled=not quick_actions_enabled,
            )
        with quick_cols[1]:
            quick_follow_tomorrow_clicked = st.button(
                "Check tomorrow",
                key=quick_follow_tomorrow_key,
                type="secondary",
                use_container_width=True,
                disabled=not quick_actions_enabled,
            )

        if quick_reviewed_clicked and quick_actions_enabled:
            _queue_completion_submission(
                submit_note_text="Reviewed — no follow-up needed",
                submit_follow_up_choice="No follow-up needed",
                submit_follow_up_due_at=None,
                submit_add_operational_exception=False,
                submit_exception_type="",
                submit_operational_exception_note="",
                submit_link_existing_exception=False,
                submit_linked_existing_exception_id="",
                submit_add_follow_through=False,
                submit_follow_through_status="logged",
                submit_follow_through_note="",
                submit_link_follow_through_to_exception=False,
            )
            return

        if quick_follow_tomorrow_clicked and quick_actions_enabled:
            _queue_completion_submission(
                submit_note_text="Reviewed — follow-up tomorrow",
                submit_follow_up_choice="Follow up tomorrow",
                submit_follow_up_due_at=datetime.combine(date.today() + timedelta(days=1), dt_time(hour=9, minute=0)),
                submit_add_operational_exception=False,
                submit_exception_type="",
                submit_operational_exception_note="",
                submit_link_existing_exception=False,
                submit_linked_existing_exception_id="",
                submit_add_follow_through=False,
                submit_follow_through_status="logged",
                submit_follow_through_note="",
                submit_link_follow_through_to_exception=False,
            )
            return

    st.caption("Add note / choose follow-up")

    note_text = st.text_area(
        "Short note (optional)",
        value=str(st.session_state.get(note_key) or ""),
        key=note_key,
        height=90,
        placeholder="Add a short check-in note if helpful.",
    )

    follow_up_choice = st.selectbox(
        "Next step",
        options=["Select one", "No follow-up needed", "Follow up tomorrow", "Pick a date"],
        index=0,
        key=follow_up_key,
    )

    follow_up_due_at: datetime | None = None
    if follow_up_choice == "Follow up tomorrow":
        follow_up_due_at = datetime.combine(date.today() + timedelta(days=1), dt_time(hour=9, minute=0))
    elif follow_up_choice == "Pick a date":
        due_date = st.date_input(
            "Follow-up date",
            value=date.today() + timedelta(days=7),
            key=due_date_key,
        )
        follow_up_due_at = datetime.combine(due_date, dt_time(hour=9, minute=0))

    has_follow_up_selection = follow_up_choice in {"No follow-up needed", "Follow up tomorrow", "Pick a date"}
    can_submit = has_follow_up_selection

    if st.button(
        "Mark as complete",
        key=submit_key,
        use_container_width=True,
        type="primary",
        disabled=not can_submit or is_signal_pending,
    ):
        if not has_follow_up_selection:
            st.warning("Choose the next step before completing.")
            return
        _queue_completion_submission(
            submit_note_text=str(note_text or ""),
            submit_follow_up_choice=str(follow_up_choice or "Select one"),
            submit_follow_up_due_at=follow_up_due_at,
            submit_add_operational_exception=bool(add_operational_exception),
            submit_exception_type=str(selected_exception_type or ""),
            submit_operational_exception_note=str(operational_exception_note or ""),
            submit_link_existing_exception=bool(link_existing_exception),
            submit_linked_existing_exception_id=str(linked_existing_exception_id or ""),
            submit_add_follow_through=bool(add_follow_through),
            submit_follow_through_status=str(selected_follow_through_status or "logged"),
            submit_follow_through_note=str(follow_through_note or ""),
            submit_link_follow_through_to_exception=bool(link_follow_through_to_exception),
        )


def _today_card_next_check_cue(card: TodayQueueCardViewModel, line_5_text: str) -> str:
    """Return a short, non-prescriptive next-check cue derived from card fields only."""
    state = str(card.state or "").strip().upper()
    norm_state = str(card.normalized_action_state or "").strip().lower()
    norm_detail = str(card.normalized_action_state_detail or "").strip().lower()
    line_3_lower = str(card.line_3 or "").strip().lower()
    line_4_lower = str(card.line_4 or "").strip().lower()
    line_5_lower = str(line_5_text or "").strip().lower()

    overdue_fields = (norm_state, norm_detail, line_3_lower, line_4_lower)
    if any("overdue" in f for f in overdue_fields):
        return "Check whether the follow-up is still open."

    if state == "PATTERN" or int(card.repeat_count or 0) > 0:
        return "Check for shift changes, assignment changes, or missing context."

    if state == "LOW_DATA" or "low confidence" in line_5_lower or "confidence: low" in line_5_lower:
        return "Confirm with floor context before acting."

    if "limited" in line_5_lower and "data" in line_5_lower:
        return "Confirm with floor context before acting."

    if state == "EARLY_TREND":
        return "Review what changed since the recent baseline."

    if state == "STABLE_TREND":
        return "Review whether the trend reflects a structural change."

    # CURRENT state with no specific signal: suppress generic fallback noise
    if state == "CURRENT":
        return ""

    return "Review the context before marking complete."


def _render_attention_card(
    *,
    card: TodayQueueCardViewModel,
    key_prefix: str,
    compact: bool = False,
    emphasize: bool = False,
    focused: bool = False,
    is_lead: bool = False,
    show_action: bool = True,
    signal_status_map: dict[str, dict[str, str]] | None = None,
) -> None:
    del show_action
    title_class = "today-insight-title"
    line_class = "today-insight-line"

    # When focused (e.g., navigating from Team with preselected employee),
    # render an anchor to support browser scroll, and add a subtle visual cue.
    if focused:
        card_anchor = f"today_card_{str(card.employee_id or '').replace(' ', '_')}"
        st.markdown(f'<a id="{card_anchor}"></a>', unsafe_allow_html=True)

    with st.container(border=True):
        line_1_text = str(card.line_1 or "").strip()
        employee_name, department_name = (line_1_text.split("·", 1) + [""])[:2] if "·" in line_1_text else (line_1_text, "")
        employee_name = str(employee_name or "").strip()
        department_name = str(department_name or "").strip()

        if focused:
            st.markdown(f'<div class="today-focused-indicator">← Team handoff</div>', unsafe_allow_html=True)

        st.markdown(f'<div class="{title_class}">{employee_name or line_1_text}</div>', unsafe_allow_html=True)
        if department_name:
            st.markdown(f'<div class="today-card-department">{department_name}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="{line_class}">{card.line_2}</div>', unsafe_allow_html=True)
        if not compact:
            what_changed_text = str(getattr(card, "what_changed_line", "") or "").strip()
            surfaced_because_text = str(card.line_3 or "").strip()
            line_2_text = str(card.line_2 or "").strip().lower()
            if what_changed_text and what_changed_text.lower() != line_2_text:
                st.markdown(f'<div class="{line_class}">{what_changed_text}</div>', unsafe_allow_html=True)
            if surfaced_because_text and surfaced_because_text.lower() not in {line_2_text, what_changed_text.lower() if what_changed_text else ""}:
                st.markdown(f'<div class="{line_class}">{surfaced_because_text}</div>', unsafe_allow_html=True)

        line_5_text = str(card.line_5 or "").strip()
        freshness_text = str(card.freshness_line or "").strip()
        confidence_label = ""
        if line_5_text:
            lower_line_5 = line_5_text.lower()
            if lower_line_5.startswith("confidence:"):
                confidence_value = line_5_text.split(":", 1)[1].strip()
                if confidence_value:
                    confidence_label = f"{confidence_value} confidence"
            else:
                confidence_label = line_5_text

        metadata_parts: list[str] = []
        if confidence_label:
            metadata_parts.append(confidence_label)
        if freshness_text:
            metadata_parts.append(freshness_text)
        if _is_low_confidence_overdue_card(card, line_5_text):
            metadata_parts.append("Overdue follow-up")

        metadata_row = " · ".join(part for part in metadata_parts if str(part or "").strip())
        if metadata_row:
            st.markdown(f'<div class="today-card-meta-row">{metadata_row}</div>', unsafe_allow_html=True)

        if not compact:
            next_check = _today_card_next_check_cue(card, line_5_text)
            if next_check:
                st.markdown(f'<div class="today-card-next-check">{next_check}</div>', unsafe_allow_html=True)

        if compact:
            detail_text = str(card.line_3 or "").strip()
            evidence_text = str(card.line_4 or "").strip()
            what_changed_text = str(getattr(card, "what_changed_line", "") or "").strip()
            if what_changed_text:
                st.markdown(f'<div class="today-insight-meta">{what_changed_text}</div>', unsafe_allow_html=True)
            if detail_text:
                st.markdown(f'<div class="today-insight-meta">{detail_text}</div>', unsafe_allow_html=True)
            if evidence_text:
                st.markdown(f'<div class="today-insight-meta">{evidence_text}</div>', unsafe_allow_html=True)
            if _is_low_confidence_overdue_card(card, line_5_text):
                st.markdown(
                    '<div class="today-insight-meta">Overdue follow-up shown with limited confidence.</div>',
                    unsafe_allow_html=True,
                )

        if signal_status_map is not None and not compact:
            with st.expander("Handle this", expanded=is_lead):
                _render_guided_completion_controls(
                    card=card,
                    key_prefix=f"{key_prefix}_complete",
                    status_map=signal_status_map,
                )

    if emphasize:
        pass


def _prepare_today_top_queue_render(
    *,
    plan: TodayQueueRenderPlan,
    tenant_id: str,
    today_value: date,
) -> dict[str, Any]:
    queue_started = time.perf_counter()
    ranked_cards = list(plan.primary_cards or []) + list(plan.secondary_cards or [])
    queue_derivation_ms = int(max(0.0, (time.perf_counter() - queue_started) * 1000))

    completed_items = {
        str(item or "").strip()
        for item in list(st.session_state.get(_TODAY_COMPLETED_ITEMS_SESSION_KEY) or [])
        if str(item or "").strip()
    }
    pending_signal_keys = _get_pending_completion_signal_keys()

    unresolved_started = time.perf_counter()
    unresolved_cards: list[TodayQueueCardViewModel] = []
    unresolved_signal_keys: set[str] = set()
    for card in ranked_cards:
        if _today_card_session_key(card) in completed_items:
            continue
        signal_key = str(getattr(card, "signal_key", "") or "").strip()
        if signal_key and signal_key in pending_signal_keys:
            continue
        unresolved_cards.append(card)
        if signal_key:
            unresolved_signal_keys.add(signal_key)
    queue_filter_ms = int(max(0.0, (time.perf_counter() - unresolved_started) * 1000))

    status_started = time.perf_counter()
    signal_status_map = _cached_today_signal_status_map(
        tenant_id=str(tenant_id or "").strip(),
        signal_keys_sorted=tuple(sorted(unresolved_signal_keys)),
        today_iso=today_value.isoformat(),
    )
    signal_status_map_ms = int(max(0.0, (time.perf_counter() - status_started) * 1000))

    top3_started = time.perf_counter()
    active_ranked_cards: list[TodayQueueCardViewModel] = []
    for card in unresolved_cards:
        signal_key = str(getattr(card, "signal_key", "") or "").strip()
        if signal_key:
            persisted_status = str((signal_status_map.get(signal_key) or {}).get("status") or "").strip().lower()
            if persisted_status == SIGNAL_STATUS_LOOKED_AT:
                continue
        active_ranked_cards.append(card)

    top_cards = active_ranked_cards[:_TODAY_QUEUE_DEFAULT_VISIBLE_CARDS]
    overflow_cards = active_ranked_cards[_TODAY_QUEUE_DEFAULT_VISIBLE_CARDS:]
    top3_derivation_ms = int(max(0.0, (time.perf_counter() - top3_started) * 1000))

    people_needing_attention = len(
        {
            str(getattr(card, "employee_id", "") or "").strip()
            for card in active_ranked_cards
            if str(getattr(card, "employee_id", "") or "").strip()
        }
    )

    return {
        "ranked_cards": ranked_cards,
        "signal_status_map": signal_status_map,
        "active_ranked_cards": active_ranked_cards,
        "top_cards": top_cards,
        "overflow_cards": overflow_cards,
        "people_needing_attention": int(people_needing_attention),
        "queue_derivation_ms": int(queue_derivation_ms),
        "queue_filter_ms": int(queue_filter_ms),
        "signal_status_map_ms": int(signal_status_map_ms),
        "top3_derivation_ms": int(top3_derivation_ms),
    }


def _today_card_session_key(card: TodayQueueCardViewModel) -> str:
    signal_key = str(getattr(card, "signal_key", "") or "").strip()
    if signal_key:
        return f"signal:{signal_key}"
    employee_id = str(getattr(card, "employee_id", "") or "").strip()
    process_id = str(getattr(card, "process_id", "") or "").strip()
    state = str(getattr(card, "state", "") or "").strip()
    line_1 = str(getattr(card, "line_1", "") or "").strip()
    return f"card:{employee_id}:{process_id}:{state}:{line_1}".strip(":")


def _render_today_standup_view(cards: list[TodayQueueCardViewModel]) -> None:
    standup_text = build_today_standup_text(cards)
    st.markdown('<div class="today-section-label">Standup view</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="today-supporting-note">Read-only shift standup summary.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(standup_text.replace("\n", "  \n"))


def _render_today_low_data_fallback(fallback: TodayLowDataFallbackViewModel) -> None:
    st.markdown(
        f'<div class="today-action-frame-heading">Today ({fallback.mode_label})</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="today-action-frame-sub">{fallback.explanation_line}</div>',
        unsafe_allow_html=True,
    )
    fallback_lines = [f"- {line}" for line in list(fallback.bullets or [])[:3]]
    if fallback_lines:
        st.markdown("  \n".join(fallback_lines))


def _render_today_team_risk_block(team_risk: TodayTeamRiskViewModel | None) -> None:
    if team_risk is None or not list(team_risk.bullets or []):
        return
    with st.expander("Team snapshot", expanded=False):
        for bullet in list(team_risk.bullets or [])[:3]:
            st.markdown(f"- {bullet}")


def _render_today_copy_summary_block(cards: list[TodayQueueCardViewModel], *, today_value: date) -> None:
        summary_text = build_today_summary(cards)
        reveal_key = f"_today_copy_summary_visible_{today_value.isoformat()}"
        text_key = f"_today_copy_summary_text_{today_value.isoformat()}"
        button_id = f"today-copy-summary-button-{today_value.isoformat()}"
        status_id = f"today-copy-summary-status-{today_value.isoformat()}"
        payload = json.dumps(summary_text)

        st.markdown('<div class="today-section-label">Copy-ready summary</div>', unsafe_allow_html=True)
        st.markdown(
                '<div class="today-supporting-note">Short queue summary for export or handoff.</div>',
                unsafe_allow_html=True,
        )

        components.html(
                f"""
                <div style=\"display:flex;align-items:center;gap:0.6rem;margin:0.15rem 0 0.35rem 0;\">
                    <button
                        id=\"{button_id}\"
                        type=\"button\"
                        style=\"background:#1f6feb;color:#fff;border:0;border-radius:999px;padding:0.42rem 0.9rem;font-size:0.9rem;font-weight:600;cursor:pointer;\"
                    >
                        Copy summary
                    </button>
                    <span id=\"{status_id}\" style=\"font-size:0.82rem;color:#4b647d;min-height:1rem;\"></span>
                </div>
                <script>
                const copyText = {payload};
                const button = document.getElementById({json.dumps(button_id)});
                const status = document.getElementById({json.dumps(status_id)});

                async function copySummaryText() {{
                    try {{
                        if (navigator.clipboard && navigator.clipboard.writeText) {{
                            await navigator.clipboard.writeText(copyText);
                        }} else {{
                            const helper = document.createElement('textarea');
                            helper.value = copyText;
                            helper.style.position = 'fixed';
                            helper.style.opacity = '0';
                            document.body.appendChild(helper);
                            helper.focus();
                            helper.select();
                            document.execCommand('copy');
                            document.body.removeChild(helper);
                        }}
                        status.textContent = 'Copied';
                    }} catch (_error) {{
                        status.textContent = 'Copy failed';
                    }}
                    window.setTimeout(() => {{
                        status.textContent = '';
                    }}, 1800);
                }}

                if (button) {{
                    button.addEventListener('click', copySummaryText);
                }}
                </script>
                """,
                height=44,
        )

        if st.button("Show summary text", key=f"today_copy_summary_toggle_{today_value.isoformat()}"):
                st.session_state[reveal_key] = True

        if bool(st.session_state.get(reveal_key)):
                st.text_area(
                        "Today summary",
                        value=summary_text,
                        height=140,
                        key=text_key,
                )



def _render_unified_attention_queue(
    attention: AttentionSummary,
    *,
    decision_items: list[Any] | None = None,
    suppressed_cards: list[InsightCardContract] | None = None,
    goal_status: list[dict[str, Any]] | None = None,
    is_stale: bool = False,
    show_secondary_open: bool = False,
    weak_data_mode: bool = False,
    snapshot_cards: list[TodayQueueCardViewModel] | None = None,
    last_action_lookup: dict[str, str] | None = None,
    action_state_lookup: dict[str, dict[str, Any]] | None = None,
    low_data_fallback: TodayLowDataFallbackViewModel | None = None,
    manager_loop_strip: TodayManagerLoopStripViewModel | None = None,
    render_plan: TodayQueueRenderPlan | None = None,
    prepared_queue_render: dict[str, Any] | None = None,
) -> None:
    plan: TodayQueueRenderPlan = render_plan or build_today_queue_render_plan(
        attention=attention,
        decision_items=decision_items,
        suppressed_cards=suppressed_cards,
        today_value=date.today(),
        is_stale=is_stale,
        weak_data_mode=weak_data_mode,
        show_secondary_open=show_secondary_open,
        snapshot_cards=snapshot_cards,
        last_action_lookup=last_action_lookup,
        action_state_lookup=action_state_lookup,
    )

    prepared = dict(prepared_queue_render or {})
    signal_status_map = dict(prepared.get("signal_status_map") or {})
    active_ranked_cards = list(prepared.get("active_ranked_cards") or [])
    top_cards = list(prepared.get("top_cards") or [])
    overflow_cards = list(prepared.get("overflow_cards") or [])

    if not prepared:
        # Compatibility fallback for call sites that do not pass precomputed queue data.
        fallback_prepared = _prepare_today_top_queue_render(
            plan=plan,
            tenant_id=str(st.session_state.get("tenant_id") or "").strip(),
            today_value=date.today(),
        )
        signal_status_map = dict(fallback_prepared.get("signal_status_map") or {})
        active_ranked_cards = list(fallback_prepared.get("active_ranked_cards") or [])
        top_cards = list(fallback_prepared.get("top_cards") or [])
        overflow_cards = list(fallback_prepared.get("overflow_cards") or [])

    if low_data_fallback is not None:
        _render_today_low_data_fallback(low_data_fallback)
        return

    completion_feedback = str(st.session_state.pop(_TODAY_COMPLETION_FEEDBACK_MESSAGE_KEY, "") or "").strip()
    if completion_feedback:
        st.caption(completion_feedback)

    team_risk = build_today_team_risk_view_model(
        goal_status=list(goal_status or []),
        cards=active_ranked_cards,
    )

    if not active_ranked_cards and plan.primary_placeholder:
        st.markdown(f'<div class="today-placeholder">{plan.primary_placeholder}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="today-home-title">{str(plan.section_title or "Follow-ups Today")}</div>', unsafe_allow_html=True)
        st.markdown('<div class="today-action-frame-heading">Handle these first</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="today-action-frame-sub">{str(plan.start_note or "Open loops that need a manager decision, check-in, or closeout.")}</div>', unsafe_allow_html=True)
        _render_manager_loop_strip(manager_loop_strip)
        st.session_state.pop(_TODAY_FOCUS_NEXT_CARD_KEY, None)

        # Honor one-time Team return focus payload first, then legacy cn_selected_emp behavior.
        # Track per-day whether we've already rendered the handoff focus to avoid sticky behavior on reruns.
        today_value = date.today()
        handoff_rendered_key = _TODAY_HANDOFF_FOCUS_RENDERED_KEY_PREFIX + today_value.isoformat()
        handoff_focus_already_rendered = bool(st.session_state.get(handoff_rendered_key))

        focus_payload = st.session_state.get(_TEAM_TO_TODAY_FOCUS_KEY)
        focus_payload = focus_payload if isinstance(focus_payload, dict) else {}
        payload_employee_id = str(focus_payload.get("employee_id") or "").strip()

        focused_employee_id = str(st.session_state.get("cn_selected_emp") or "").strip()
        is_first_handoff_render = bool(
            (payload_employee_id or focused_employee_id)
            and not handoff_focus_already_rendered
        )
        consumed_payload = False

        _top_cols = st.columns(min(max(len(top_cards), 1), 3))
        for idx, card in enumerate(top_cards):
            card_employee_id = str(card.employee_id or "").strip()
            payload_match = bool(payload_employee_id and card_employee_id == payload_employee_id)
            fallback_match = bool((not payload_employee_id) and focused_employee_id and card_employee_id == focused_employee_id)
            is_focused = bool(is_first_handoff_render and (payload_match or fallback_match))
            with _top_cols[idx]:
                _render_attention_card(
                    card=card,
                    key_prefix=f"today_attention_primary_{idx}",
                    emphasize=False,
                    focused=is_focused,
                    is_lead=(idx == 0),
                    signal_status_map=signal_status_map,
                )
            # Mark handoff as rendered after the first matching card is rendered.
            if is_focused and not handoff_focus_already_rendered:
                st.session_state[handoff_rendered_key] = True
                if payload_match:
                    consumed_payload = True

        if payload_employee_id:
            # Consume return-focus payload once per render cycle to prevent sticky highlighting.
            st.session_state.pop(_TEAM_TO_TODAY_FOCUS_KEY, None)
            if consumed_payload:
                st.session_state["cn_selected_emp"] = payload_employee_id

    if overflow_cards:
        st.markdown(
            '<div style="margin-top:1.5rem;margin-bottom:0.25rem;">'
            '<span style="font-size:0.88rem;font-weight:600;color:#5d7693;letter-spacing:0.03em;text-transform:uppercase;">Review if time</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div style="font-size:0.82rem;color:#8097b0;margin-bottom:0.75rem;">Lower-priority signals from the same data set.</div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"{len(overflow_cards)} additional signal{'s' if len(overflow_cards) != 1 else ''}", expanded=False):
            for idx, card in enumerate(overflow_cards):
                _render_attention_card(
                    card=card,
                    key_prefix=f"today_attention_other_{idx}",
                    compact=True,
                    signal_status_map=signal_status_map,
                )

    if active_ranked_cards:
        _render_today_copy_summary_block(active_ranked_cards, today_value=date.today())

    auto_resolved_count = int(getattr(plan, "auto_resolved_count", 0) or 0)
    if auto_resolved_count > 0:
        _shown_key = _TODAY_AUTO_RESOLVED_SHOWN_KEY_PREFIX + date.today().isoformat()
        if not st.session_state.get(_shown_key):
            _item_word = "item" if auto_resolved_count == 1 else "items"
            st.caption(f"{auto_resolved_count} {_item_word} back to target \u2014 no action needed")
            st.session_state[_shown_key] = True

    with st.expander("Context", expanded=False):
        _render_today_standup_view(active_ranked_cards)
        _render_today_team_risk_block(team_risk)

    if plan.suppressed_debug_rows:
        st.session_state["_today_suppressed_signals_debug"] = list(plan.suppressed_debug_rows)


def _render_today_value_strip(
    value_strip: TodayValueStripViewModel,
    *,
    freshness_note: str = "",
    is_stale: bool = False,
    subdued: bool = False,
) -> None:
    if not value_strip.cards:
        return

    if subdued:
        st.markdown('<div class="today-secondary-context-label">Secondary context</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="today-secondary-context-note">Secondary snapshot context, shown beneath the main queue.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="today-section-label">Quick read</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="today-supporting-note">A compact interpretation of the current snapshot before queue details.</div>',
            unsafe_allow_html=True,
        )
    if str(freshness_note or "").strip():
        st.caption(freshness_note)

    columns = st.columns(len(value_strip.cards))
    for column, card in zip(columns, value_strip.cards):
        with column:
            display_title = str(card.title or "")
            if is_stale and "today" in display_title.lower():
                display_title = display_title.replace("today", "latest snapshot").replace("Today", "Latest snapshot")
            card_class = "today-value-card-subtle" if subdued else "today-value-card"
            title_class = "today-value-title-subtle" if subdued else "today-value-title"
            headline_class = "today-value-headline-subtle" if subdued else "today-value-headline"
            detail_class = "today-value-detail-subtle" if subdued else "today-value-detail"
            st.markdown(
                (
                    f'<div class="{card_class}">'
                    f'<div class="{title_class}">{display_title}</div>'
                    f'<div class="{headline_class}">{card.headline}</div>'
                    f'<div class="{detail_class}">{card.detail}</div>'
                    '</div>'
                ),
                unsafe_allow_html=True,
            )


def _render_insight_card(
    item: InsightCardContract,
    *,
    key_prefix: str,
    last_action_lookup: dict[str, str] | None = None,
    action_state_lookup: dict[str, dict[str, Any]] | None = None,
) -> None:
    card_vm = build_today_queue_card_from_insight_card(
        card=item,
        today=date.today(),
        last_action_lookup=last_action_lookup,
        action_state_lookup=action_state_lookup,
    )
    if card_vm is None:
        display_signal = build_display_signal_from_insight_card(card=item, today=date.today())
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

    with st.container(border=True):
        st.markdown(f'<div class="today-insight-title">{card_vm.line_1}</div>', unsafe_allow_html=True)
        action_state_chip = _action_state_chip(card_vm)
        if action_state_chip:
            st.markdown(action_state_chip, unsafe_allow_html=True)
        st.markdown(f'<div class="today-insight-line">{card_vm.line_2}</div>', unsafe_allow_html=True)
        if str(getattr(card_vm, "what_changed_line", "") or "").strip():
            st.markdown(f'<div class="today-insight-line">{card_vm.what_changed_line}</div>', unsafe_allow_html=True)
        if str(card_vm.line_3 or "").strip():
            st.markdown(f'<div class="today-insight-line">{card_vm.line_3}</div>', unsafe_allow_html=True)

        line_5_text = str(card_vm.line_5 or "").strip()
        freshness_text = str(card_vm.freshness_line or "").strip()
        chip_html = _confidence_chip(line_5_text)
        if chip_html:
            st.markdown(chip_html, unsafe_allow_html=True)
        if line_5_text.lower() == "low confidence":
            st.markdown(f'<div class="today-confidence-badge-low">{line_5_text}</div>', unsafe_allow_html=True)
            if _is_low_confidence_overdue_card(card_vm, line_5_text):
                st.markdown(
                    '<div class="today-freshness-meta">Overdue follow-up shown with limited confidence.</div>',
                    unsafe_allow_html=True,
                )
            if freshness_text:
                st.markdown(f'<div class="today-freshness-meta">{freshness_text}</div>', unsafe_allow_html=True)
        elif line_5_text:
            confidence_freshness = (
                f"{line_5_text} · {freshness_text}" if freshness_text else line_5_text
            )
            st.markdown(f'<div class="today-insight-meta">{confidence_freshness}</div>', unsafe_allow_html=True)
        elif freshness_text:
            st.markdown(f'<div class="today-insight-meta">{freshness_text}</div>', unsafe_allow_html=True)

        if str(card_vm.line_4 or "").strip():
            st.markdown(f'<div class="today-insight-line">{card_vm.line_4}</div>', unsafe_allow_html=True)

        collapsed_hint = str(getattr(card_vm, "collapsed_hint", "") or "").strip()
        if collapsed_hint:
            st.markdown(f'<div class="today-insight-meta">{collapsed_hint}</div>', unsafe_allow_html=True)
        collapsed_evidence = str(getattr(card_vm, "collapsed_evidence", "") or "").strip()
        line_4_text = str(card_vm.line_4 or "").strip().lower()
        if collapsed_evidence and collapsed_evidence.strip().lower() != line_4_text:
            st.markdown(f'<div class="today-insight-meta">{collapsed_evidence}</div>', unsafe_allow_html=True)
        collapsed_issue = str(getattr(card_vm, "collapsed_issue", "") or "").strip()
        if collapsed_issue:
            st.markdown(f'<div class="today-insight-meta">{collapsed_issue}</div>', unsafe_allow_html=True)

        if card_vm.expanded_lines:
            with st.expander("Why this is shown", expanded=False):
                for line in list(card_vm.expanded_lines or [])[:3]:
                    st.write(line)

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
    last_action_lookup: dict[str, str] | None = None,
    action_state_lookup: dict[str, dict[str, Any]] | None = None,
) -> None:
    st.markdown('<div class="today-home-section">', unsafe_allow_html=True)
    st.markdown(f'<div class="today-home-title">{section_title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="today-home-desc">{section_description}</div>', unsafe_allow_html=True)
    eligible_items: list[InsightCardContract] = []
    for item in items:
        display_signal = build_display_signal_from_insight_card(card=item, today=date.today())
        if is_signal_display_eligible(display_signal, allow_low_data_case=False):
            eligible_items.append(item)

    if not eligible_items:
        st.markdown(f'<div class="today-placeholder">{placeholder_message}</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for item in eligible_items:
        _render_insight_card(
            item,
            key_prefix=key_prefix,
            last_action_lookup=last_action_lookup,
            action_state_lookup=action_state_lookup,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _today_action_state_employee_ids(
    *,
    plan: TodayQueueRenderPlan,
) -> tuple[str, ...]:
    employee_ids: list[str] = []
    seen: set[str] = set()

    def _append_employee_id(raw_value: Any) -> None:
        if len(employee_ids) >= _TODAY_ACTION_STATE_LOOKUP_MAX_EMPLOYEE_IDS:
            return
        employee_id = str(raw_value or "").strip()
        if not employee_id or employee_id in seen:
            return
        seen.add(employee_id)
        employee_ids.append(employee_id)

    for card in list(plan.primary_cards or []):
        _append_employee_id(getattr(card, "employee_id", ""))

    if bool(plan.secondary_expanded):
        for card in list(plan.secondary_cards or [])[:20]:
            _append_employee_id(getattr(card, "employee_id", ""))

    return tuple(sorted(employee_ids))


def _today_action_state_actionable_card_count(*, plan: TodayQueueRenderPlan) -> int:
    actionable_count = 0
    for card in list(plan.primary_cards or []):
        if str(getattr(card, "employee_id", "") or "").strip():
            actionable_count += 1

    if bool(plan.secondary_expanded):
        for card in list(plan.secondary_cards or [])[:20]:
            if str(getattr(card, "employee_id", "") or "").strip():
                actionable_count += 1

    return int(actionable_count)


def _today_rendered_card_count(*, plan: TodayQueueRenderPlan) -> int:
    return int(len(list(plan.primary_cards or [])) + len(list(plan.secondary_cards or [])[:20]))


def _fingerprintable_payload(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _fingerprintable_payload(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _fingerprintable_payload(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_fingerprintable_payload(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_fingerprintable_payload(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _payload_fingerprint(value: Any) -> str:
    serialized = json.dumps(
        _fingerprintable_payload(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:24]


def _today_pre_action_render_plan_input_fingerprint(
    *,
    attention: AttentionSummary,
    decision_items: list[Any] | None,
    suppressed_cards: list[InsightCardContract] | None,
    snapshot_cards: list[Any] | None,
    last_action_lookup: dict[str, str] | None,
    today_iso: str,
    is_stale: bool,
    weak_data_mode: bool,
    show_secondary_open: bool,
) -> str:
    return _payload_fingerprint(
        {
            "attention": attention,
            "decision_items": list(decision_items or []),
            "suppressed_cards": list(suppressed_cards or []),
            "snapshot_cards": list(snapshot_cards or []),
            "last_action_lookup": dict(last_action_lookup or {}),
            "today_iso": str(today_iso or "")[:10],
            "is_stale": bool(is_stale),
            "weak_data_mode": bool(weak_data_mode),
            "show_secondary_open": bool(show_secondary_open),
        }
    )


def _pre_action_render_plan_page_cache_key(
    *,
    tenant_id: str,
    today_iso: str,
    context_day_key: str,
    queue_fingerprint: str,
    surface_flags: str,
) -> str:
    return "|".join(
        [
            str(tenant_id or "").strip(),
            str(today_iso or "").strip()[:10],
            str(context_day_key or "").strip()[:10],
            str(queue_fingerprint or "").strip(),
            str(surface_flags or "").strip(),
        ]
    )


def _get_cached_pre_action_render_plan_page(*, cache_key: str) -> TodayQueueRenderPlan | None:
    now_ts = float(time.time())
    try:
        page_cache = st.session_state.get("_today_pre_action_render_plan_page_cache")
        if not isinstance(page_cache, dict):
            return None
        cached = page_cache.get(str(cache_key or ""))
        if not isinstance(cached, dict):
            return None
        expires_at = float(cached.get("expires_at", 0.0) or 0.0)
        payload = cached.get("payload")
        if expires_at >= now_ts and isinstance(payload, TodayQueueRenderPlan):
            return payload
        page_cache.pop(str(cache_key or ""), None)
    except Exception:
        return None
    return None


def _set_cached_pre_action_render_plan_page(*, cache_key: str, plan: TodayQueueRenderPlan) -> None:
    try:
        page_cache = st.session_state.get("_today_pre_action_render_plan_page_cache")
        if not isinstance(page_cache, dict):
            page_cache = {}
            st.session_state["_today_pre_action_render_plan_page_cache"] = page_cache
        if len(page_cache) >= 16:
            try:
                oldest_key = next(iter(page_cache))
                page_cache.pop(oldest_key, None)
            except Exception:
                pass
        page_cache[str(cache_key or "")] = {
            "expires_at": float(time.time()) + float(_READ_CACHE_TTL_SECONDS),
            "payload": plan,
        }
    except Exception:
        pass


def _today_render_plan_fingerprint(*, plan: TodayQueueRenderPlan) -> str:
    parts: list[str] = [
        str(plan.section_title or ""),
        str(plan.weak_data_note or ""),
        str(plan.start_note or ""),
        str(plan.primary_placeholder or ""),
        str(plan.secondary_caption or ""),
        str(bool(plan.secondary_expanded)),
    ]

    for card in list(plan.primary_cards or []):
        parts.extend(
            [
                str(getattr(card, "employee_id", "") or ""),
                str(getattr(card, "process_id", "") or ""),
                str(getattr(card, "state", "") or ""),
                str(getattr(card, "signal_key", "") or ""),
                str(getattr(card, "line_1", "") or ""),
                str(getattr(card, "line_2", "") or ""),
                str(getattr(card, "what_changed_line", "") or ""),
                str(getattr(card, "line_3", "") or ""),
                str(getattr(card, "line_4", "") or ""),
                str(getattr(card, "line_5", "") or ""),
            ]
        )

    for card in list(plan.secondary_cards or []):
        parts.extend(
            [
                str(getattr(card, "employee_id", "") or ""),
                str(getattr(card, "process_id", "") or ""),
                str(getattr(card, "state", "") or ""),
                str(getattr(card, "signal_key", "") or ""),
                str(getattr(card, "line_1", "") or ""),
                str(getattr(card, "line_2", "") or ""),
                str(getattr(card, "what_changed_line", "") or ""),
                str(getattr(card, "line_3", "") or ""),
                str(getattr(card, "line_4", "") or ""),
                str(getattr(card, "line_5", "") or ""),
            ]
        )

    digest = hashlib.sha1("\x1e".join(parts).encode("utf-8")).hexdigest()
    return str(digest[:24])


def _enriched_render_plan_page_cache_key(
    *,
    tenant_id: str,
    today_iso: str,
    context_day_key: str,
    visible_employee_ids: tuple[str, ...],
    render_plan_fingerprint: str,
) -> str:
    return "|".join(
        [
            str(tenant_id or "").strip(),
            str(today_iso or "").strip()[:10],
            str(context_day_key or "").strip()[:10],
            ",".join(str(emp or "").strip() for emp in (visible_employee_ids or ())),
            str(render_plan_fingerprint or "").strip(),
        ]
    )


def _get_cached_enriched_render_plan_page(*, cache_key: str) -> TodayQueueRenderPlan | None:
    now_ts = float(time.time())
    try:
        page_cache = st.session_state.get("_today_enriched_render_plan_page_cache")
        if not isinstance(page_cache, dict):
            return None
        cached = page_cache.get(str(cache_key or ""))
        if not isinstance(cached, dict):
            return None
        expires_at = float(cached.get("expires_at", 0.0) or 0.0)
        payload = cached.get("payload")
        if expires_at >= now_ts and isinstance(payload, TodayQueueRenderPlan):
            return payload
        page_cache.pop(str(cache_key or ""), None)
    except Exception:
        return None
    return None


def _set_cached_enriched_render_plan_page(*, cache_key: str, plan: TodayQueueRenderPlan) -> None:
    try:
        page_cache = st.session_state.get("_today_enriched_render_plan_page_cache")
        if not isinstance(page_cache, dict):
            page_cache = {}
            st.session_state["_today_enriched_render_plan_page_cache"] = page_cache
        if len(page_cache) >= 16:
            try:
                oldest_key = next(iter(page_cache))
                page_cache.pop(oldest_key, None)
            except Exception:
                pass
        page_cache[str(cache_key or "")] = {
            "expires_at": float(time.time()) + float(_READ_CACHE_TTL_SECONDS),
            "payload": plan,
        }
    except Exception:
        pass


def _enrich_render_plan_action_state(
    *,
    plan: TodayQueueRenderPlan,
    today_value: date,
    last_action_lookup: dict[str, str] | None,
    action_state_lookup: dict[str, dict[str, Any]] | None,
) -> TodayQueueRenderPlan:
    if not action_state_lookup:
        return plan

    enriched_primary = [
        enrich_today_queue_card_action_context(
            card=card,
            today=today_value,
            last_action_lookup=last_action_lookup,
            action_state_lookup=action_state_lookup,
        )
        for card in list(plan.primary_cards or [])
    ]
    enriched_secondary = [
        enrich_today_queue_card_action_context(
            card=card,
            today=today_value,
            last_action_lookup=last_action_lookup,
            action_state_lookup=action_state_lookup,
        )
        for card in list(plan.secondary_cards or [])
    ]

    return TodayQueueRenderPlan(
        section_title=plan.section_title,
        weak_data_note=plan.weak_data_note,
        start_note=plan.start_note,
        primary_cards=enriched_primary,
        secondary_cards=enriched_secondary,
        primary_placeholder=plan.primary_placeholder,
        secondary_caption=plan.secondary_caption,
        secondary_expanded=plan.secondary_expanded,
        suppressed_debug_rows=list(plan.suppressed_debug_rows or []),
    )


def _page_today_impl(*, root_placeholder: Any) -> None:
    st.session_state["_ui_render_guard_active"] = True
    try:
        if "tenant_id" not in st.session_state:
            st.session_state.tenant_id = ""

        if "today_queue_filter" not in st.session_state:
            st.session_state.today_queue_filter = "all"

        today_value = date.today()
        page_started_at = time.perf_counter()
        tenant_id = str(st.session_state.get("tenant_id", "") or "")
        is_cold_start = not bool(st.session_state.get(_today_initial_load_completed_key(today_value)))
        entered_from_page = str(st.session_state.get("_entered_from_page_key", "") or "")
        phase2_ready_key = _today_phase2_render_ready_key(today_value)
        if entered_from_page and entered_from_page.strip().lower() != "today":
            st.session_state[phase2_ready_key] = False

        _consume_today_async_snapshot_refresh_completion(
            tenant_id=tenant_id,
            today_value=today_value,
        )

        # --- Run-id: create once per navigation, preserved across same-session reruns ---
        _today_iso = today_value.isoformat()
        _run_id_key = _TODAY_RUN_ID_DATE_KEY_PREFIX + _today_iso
        _run_nav_src_key = _TODAY_RUN_NAV_SOURCE_KEY_PREFIX + _today_iso
        _existing_run_id = str(st.session_state.get(_run_id_key) or "")
        _last_nav_source = str(st.session_state.get(_run_nav_src_key) or "")
        _entered_from_normalized = entered_from_page.strip().lower()
        _is_new_navigation = (
            not _existing_run_id
            or (
                bool(_entered_from_normalized)
                and _entered_from_normalized != "today"
                and entered_from_page != _last_nav_source
            )
        )
        if _is_new_navigation:
            today_run_id = str(uuid4())
            st.session_state[_run_id_key] = today_run_id
            st.session_state[_run_nav_src_key] = entered_from_page
            st.session_state[_TODAY_RUN_WALL_START_KEY] = time.time()
            st.session_state[_TODAY_RUN_MILESTONES_KEY] = []
            st.session_state[_TODAY_RUN_IS_COLD_KEY] = is_cold_start
        else:
            today_run_id = _existing_run_id

        _log_today_first_paint_event_once(
            event_name="today_first_paint_started",
            today_value=today_value,
            tenant_id=tenant_id,
            context={
                "entered_from_page": entered_from_page,
                "initial_load_completed": bool(st.session_state.get(_today_initial_load_completed_key(today_value))),
            },
        )

        _log_today_milestone(
            "today_page_entered",
            tenant_id=tenant_id,
            context={
                "is_cold_start": bool(is_cold_start),
                "nav_from": entered_from_page,
                "phase2_ready": bool(st.session_state.get(phase2_ready_key)),
                "is_new_navigation": bool(_is_new_navigation),
            },
        )
        if not _is_new_navigation and not is_cold_start:
            _log_today_milestone(
                "today_page_reentered_after_rerun",
                tenant_id=tenant_id,
                context={
                    "phase2_ready": bool(st.session_state.get(phase2_ready_key)),
                    "rerun_triggered_previously": bool(
                        st.session_state.get(_today_initial_rerun_triggered_key(today_value))
                    ),
                },
            )

        if is_cold_start:
            _log_today_first_paint_event_once(
                event_name="today_cold_start_begin",
                today_value=today_value,
                tenant_id=tenant_id,
                context={
                    "today_iso": today_value.isoformat(),
                    "entered_from_page": entered_from_page,
                },
            )

        if _today_should_show_first_paint_shell(entered_from_page=entered_from_page, today_value=today_value):
            _render_today_loading_shell()
            _log_today_first_paint_event_once(
                event_name="today_first_paint_loading_shell",
                today_value=today_value,
                tenant_id=tenant_id,
                context={
                    "entered_from_page": entered_from_page,
                    "initial_load_completed": bool(st.session_state.get(_today_initial_load_completed_key(today_value))),
                },
            )
            if entered_from_page and entered_from_page.strip().lower() != "today":
                _log_today_first_paint_event_once(
                    event_name="today_previous_screen_cleared",
                    today_value=today_value,
                    tenant_id=tenant_id,
                    marker=entered_from_page,
                    context={"entered_from_page": entered_from_page},
                )
                _log_today_milestone(
                    "today_previous_screen_cleared",
                    tenant_id=tenant_id,
                    context={"entered_from_page": entered_from_page},
                )
            _log_today_milestone(
                "today_loading_shell_painted",
                tenant_id=tenant_id,
                context={
                    "entered_from_page": entered_from_page,
                    "previous_screen_cleared": bool(
                        entered_from_page and entered_from_page.strip().lower() != "today"
                    ),
                },
            )

        with profile_block(
            "today.page_today",
            tenant_id=tenant_id,
            user_email=str(st.session_state.get("user_email", "") or ""),
            context={"today_iso": today_value.isoformat()},
            execution_key=f"_perf_profile_today_page_today_{today_value.isoformat()}",
        ) as profile:
            with profile.stage("init_ui"):
                _apply_today_styles()
                profile.set("deferred_widget_resets", int(_apply_deferred_today_widget_resets()))
                _drain_today_async_completion_results()

            with profile.stage("auto_refresh"):
                refresh_outcome = _run_today_auto_refresh(tenant_id=tenant_id, today_value=today_value)
                profile.set("auto_refresh_due", bool(refresh_outcome.get("refresh_due")))
                profile.set("auto_refresh_skipped_active_input", bool(refresh_outcome.get("active_interaction")))
                profile.set("auto_refresh_skip_reason_count", int(len(list(refresh_outcome.get("interaction_reasons") or []))))
                profile.set("initial_load_completed", bool(refresh_outcome.get("initial_load_completed")))
                profile.set("initial_load_attempted", bool(refresh_outcome.get("initial_load_attempted")))
                profile.set("auto_refresh_performed", bool(refresh_outcome.get("refreshed")))

            try:
                profile.set("tenant_id_present", bool(tenant_id))
                recovery_attempted = False

                def _load_today_signals() -> dict[str, Any] | None:
                    profile.increment("today_signals_request_count", 1)
                    _session_key = f"{_TODAY_PAYLOAD_SESSION_CACHE_KEY_PREFIX}{tenant_id}_{today_value.isoformat()}"
                    _cached_payload = st.session_state.get(_session_key)
                    if isinstance(_cached_payload, dict) and _cached_payload.get("queue_items") is not None:
                        profile.increment("today_signals_session_cache_hit", 1)
                        return _cached_payload
                    result = get_today_signals(
                        tenant_id=tenant_id,
                        as_of_date=today_value.isoformat(),
                    )
                    if isinstance(result, dict):
                        st.session_state[_session_key] = result
                    return result

                with profile.stage("load_precomputed"):
                    precomputed = _load_today_signals()
                    initial_load_completed_before_finalize = bool(
                        st.session_state.get(_today_initial_load_completed_key(today_value))
                    )
                    force_recompute = bool(st.session_state.get("_post_import_refresh_pending"))
                    needs_recovery = (
                        force_recompute
                        or not bool(st.session_state.get("_today_recovery_attempted_" + today_value.isoformat()))
                    )
                    profile.set("force_recompute", bool(force_recompute))
                    profile.set("needs_recovery", bool(needs_recovery))
                    if needs_recovery:
                        payload_stale = _precomputed_payload_looks_stale(
                            precomputed=precomputed,
                            tenant_id=tenant_id,
                            today_value=today_value,
                        )
                        if not precomputed or force_recompute or payload_stale:
                            profile.increment("recovery_attempt_count", 1)
                            with st.spinner(_today_loading_placeholder()):
                                recovery_succeeded = _attempt_signal_payload_recovery(tenant_id=tenant_id, today_value=today_value)
                            profile.set("initial_recovery_succeeded", bool(recovery_succeeded))
                            if recovery_succeeded:
                                precomputed = _load_today_signals()
                            st.session_state["_today_recovery_attempted_" + today_value.isoformat()] = True
                            recovery_attempted = recovery_succeeded
                        else:
                            st.session_state["_today_recovery_attempted_" + today_value.isoformat()] = True
                    if _precomputed_payload_looks_stale(
                        precomputed=precomputed,
                        tenant_id=tenant_id,
                        today_value=today_value,
                    ):
                        profile.increment("recovery_attempt_count", 1)
                        with st.spinner(_today_loading_placeholder()):
                            recovery_succeeded = _attempt_signal_payload_recovery(tenant_id=tenant_id, today_value=today_value)
                        profile.set("stale_recovery_succeeded", bool(recovery_succeeded))
                        if recovery_succeeded:
                            precomputed = _load_today_signals()
                    if not precomputed:
                        if not recovery_attempted:
                            profile.increment("recovery_attempt_count", 1)
                            with st.spinner(_today_loading_placeholder()):
                                recovery_succeeded = _attempt_signal_payload_recovery(tenant_id=tenant_id, today_value=today_value)
                                recovery_attempted = recovery_succeeded
                            profile.set("fallback_recovery_succeeded", bool(recovery_succeeded))
                            if recovery_attempted:
                                precomputed = _load_today_signals()

                        if not precomputed:
                            _log_today_first_paint_event_once(
                                event_name="today_first_paint_blocked_reason",
                                today_value=today_value,
                                tenant_id=tenant_id,
                                marker="precomputed_missing",
                                context={"reason": "precomputed_missing"},
                            )
                            _render_today_loading_shell()
                            return

                    if not _finalize_today_initial_load_state(
                        tenant_id=tenant_id,
                        today_value=today_value,
                        precomputed=precomputed,
                    ):
                        _log_today_first_paint_event_once(
                            event_name="today_first_paint_blocked_reason",
                            today_value=today_value,
                            tenant_id=tenant_id,
                            marker="initial_load_not_ready",
                            context={"reason": "initial_load_not_ready"},
                        )
                        _render_today_loading_shell()
                        return

                    if _trigger_today_initial_ready_rerun_if_needed(
                        tenant_id=tenant_id,
                        today_value=today_value,
                        was_initially_ready=initial_load_completed_before_finalize,
                        is_ready_now=True,
                    ):
                        return

                    _log_today_milestone(
                        "today_payload_ready",
                        tenant_id=tenant_id,
                        context={
                            "queue_items": len(list(precomputed.get("queue_items") or [])),
                            "goal_status_rows": len(list(precomputed.get("goal_status") or [])),
                        },
                    )

                    queue_items = list(precomputed.get("queue_items") or [])
                    goal_status = list(precomputed.get("goal_status") or [])
                    import_summary = dict(precomputed.get("import_summary") or {})
                    home_sections = dict(precomputed.get("home_sections") or {})
                    attention_summary = precomputed.get("attention_summary")
                    if not isinstance(attention_summary, AttentionSummary):
                        attention_summary = AttentionSummary(
                            ranked_items=[],
                            is_healthy=True,
                            healthy_message="No important changes surfaced today.",
                            suppressed_count=0,
                            total_evaluated=0,
                        )

                    if not isinstance(home_sections, dict):
                        home_sections = {}
                    suppressed_cards = home_sections.get("suppressed_signals") or []
                    if not isinstance(suppressed_cards, list):
                        suppressed_cards = []
                    home_sections["suppressed_signals"] = [
                        item for item in suppressed_cards if isinstance(item, InsightCardContract)
                    ]

                    queue_items = [item for item in queue_items if isinstance(item, dict)]
                    counts = _queue_counts(queue_items)
                    profile.set("queue_items", len(queue_items or []))
                    profile.set("goal_status_rows", len(goal_status or []))
                    profile.set("suppressed_cards", len(home_sections.get("suppressed_signals") or []))
                    if not import_summary:
                        import_summary = st.session_state.get("_import_complete_summary") or {}
                    if not isinstance(import_summary, dict):
                        import_summary = {}

                    if not goal_status:
                        goal_status = []
            except Exception as exc:
                show_error_state(f"Today screen data could not load cleanly: {exc}")
                return

            _log_today_first_paint_event_once(
                event_name="today_first_paint_main_render",
                today_value=today_value,
                tenant_id=tenant_id,
                context={
                    "entered_from_page": entered_from_page,
                    "initial_load_completed": bool(st.session_state.get(_today_initial_load_completed_key(today_value))),
                },
            )

            _trace_ctx = st.session_state.get("_drill_traceability_context") or {}
            if _trace_ctx and str(_trace_ctx.get("drill_down_screen", "")) in {"today", ""}:
                render_traceability_panel(_trace_ctx, heading="Signal source context")

            _show_flash_message()

            with profile.stage("build_meaning"):
                meaning = build_today_surface_meaning(
                    goal_status=goal_status,
                    import_summary=import_summary,
                    home_sections=home_sections,
                    has_queue_items=counts.get("all", 0) > 0,
                    as_of_date=str(precomputed.get("as_of_date") or ""),
                    today_value=today_value,
                )

            low_data_fallback = build_today_low_data_fallback_view_model(
                goal_status=goal_status,
                import_summary=import_summary,
            )

            if not _has_today_data(
                queue_items=queue_items,
                goal_status=goal_status,
                home_sections=home_sections,
                import_summary=import_summary,
            ):
                _render_first_value_screen()
                return

            _emit_today_loaded_with_data_once(
                tenant_id=tenant_id,
                import_summary=import_summary,
                queue_count=int(counts.get("all", 0) or 0),
            )

            _render_top_status_area(meaning=meaning)

            phase2_ready = bool(st.session_state.get(phase2_ready_key))
            if not phase2_ready:
                phase1_started_at = time.perf_counter()
                _log_today_milestone(
                    "today_phase1_started",
                    tenant_id=tenant_id,
                    context={"phase2_ready": False},
                )
                decision_items = list(precomputed.get("decision_items") or [])
                decision_summary = precomputed.get("decision_summary") or attention_summary
                suppressed_cards = home_sections.get("suppressed_signals", [])
                is_stale = bool(meaning.state_flags.get("stale_data"))
                weak_data_mode = bool(meaning.weak_data_mode)
                show_secondary_open = bool(st.session_state.get("_first_import_just_completed"))
                with profile.stage("phase1_top3"):
                    phase1_plan = build_today_queue_render_plan(
                        attention=decision_summary,
                        decision_items=decision_items,
                        suppressed_cards=suppressed_cards,
                        today_value=today_value,
                        is_stale=is_stale,
                        weak_data_mode=weak_data_mode,
                        show_secondary_open=show_secondary_open,
                        snapshot_cards=None,
                        last_action_lookup=None,
                        action_state_lookup=None,
                    )
                    phase1_prepared = _prepare_today_phase1_top_queue_render(
                        plan=phase1_plan,
                        tenant_id=tenant_id,
                        today_value=today_value,
                    )
                    _render_today_phase1_top_cards(
                        top_cards=list(phase1_prepared.get("top_cards") or []),
                        signal_status_map=dict(phase1_prepared.get("signal_status_map") or {}),
                        people_needing_attention=int(phase1_prepared.get("people_needing_attention") or 0),
                        low_data_fallback=low_data_fallback,
                    )
                    if list(phase1_prepared.get("top_cards") or []):
                        _log_today_milestone(
                            "today_first_top3_card_written",
                            tenant_id=tenant_id,
                            context={
                                "top3_count": len(list(phase1_prepared.get("top_cards") or [])),
                            },
                        )

                _log_today_milestone(
                    "today_top3_ready",
                    tenant_id=tenant_id,
                    context={
                        "top3_count": len(list(phase1_prepared.get("top_cards") or [])),
                        "queue_build_ms": int(phase1_prepared.get("queue_build_ms") or 0),
                        "status_map_ms": int(phase1_prepared.get("signal_status_map_ms") or 0),
                    },
                )

                top3_ready_ms = int(max(0.0, (time.perf_counter() - page_started_at) * 1000))
                phase1_render_ms = int(max(0.0, (time.perf_counter() - phase1_started_at) * 1000))
                profile.set("today_phase1_render_ms", int(phase1_render_ms))
                profile.set("today_top3_ready_ms", int(top3_ready_ms))
                _log_operational_event(
                    "today_phase1_render_timing",
                    status="info",
                    tenant_id=str(tenant_id or ""),
                    user_email=str(st.session_state.get("user_email", "") or ""),
                    context={
                        "today_phase1_render_ms": int(phase1_render_ms),
                        "today_top3_ready_ms": int(top3_ready_ms),
                        "today_cold_load_phase1_total_ms": int(phase1_render_ms),
                        "today_cold_load_top3_ready_ms": int(top3_ready_ms),
                        "today_cold_load_queue_build_ms": int(phase1_prepared.get("queue_build_ms") or 0),
                        "today_cold_load_status_map_ms": int(phase1_prepared.get("signal_status_map_ms") or 0),
                        "today_cold_load_action_state_ms": 0,
                        "top3_count": len(list(phase1_prepared.get("top_cards") or [])),
                        "is_cold_start": bool(is_cold_start),
                        "is_warm": not bool(is_cold_start),
                    },
                )
                st.session_state[phase2_ready_key] = True
                # Phase 1 has rendered the initial scan-only cards.
                # Rerun immediately so Phase 2 renders the action-ready queue.
                st.rerun()

            phase2_started_at = time.perf_counter()
            _log_today_milestone(
                "today_phase2_started",
                tenant_id=tenant_id,
                context={"phase2_ready": True},
            )

            return_trigger = None
            with profile.stage("render_header"):
                should_load_previous_payload = _should_load_previous_payload_for_return_trigger(
                    queue_items=queue_items,
                    today_value=today_value,
                )
                profile.set("header_return_trigger_candidate", bool(should_load_previous_payload))
                if should_load_previous_payload:
                    previous_precomputed = _cached_today_signals_payload(
                        tenant_id=tenant_id,
                        as_of_date=(today_value - timedelta(days=1)).isoformat(),
                    )
                    profile.set("header_previous_payload_loaded", bool(previous_precomputed))
                    return_trigger = build_today_return_trigger(
                        queue_items=queue_items,
                        today=today_value,
                        previous_queue_items=list((previous_precomputed or {}).get("queue_items") or []),
                        previous_as_of_date=str((previous_precomputed or {}).get("as_of_date") or ""),
                    )
                else:
                    profile.set("header_previous_payload_skipped", True)

            signal_mode = meaning.signal_mode
            snapshot_cards = None
            if signal_mode in (SignalMode.EARLY_SIGNAL, SignalMode.LIMITED_DATA):
                with profile.stage("build_snapshot_fallback"):
                    snapshot_cards = build_snapshot_fallback_cards(
                        goal_status=goal_status,
                        today=today_value,
                    ) or None
                profile.set("snapshot_cards", len(snapshot_cards or []))

            with profile.stage("build_action_state_context"):
                with profile_block(
                    "today.action_state_wrapper",
                    tenant_id=str(tenant_id or ""),
                    user_email=str(st.session_state.get("user_email", "") or ""),
                    context={
                        "today_iso": today_value.isoformat(),
                        "queue_items": len(queue_items or []),
                    },
                ) as action_wrapper_profile:
                    with action_wrapper_profile.stage("build_action_state_context"):
                        last_action_lookup = _build_last_action_lookup(queue_items)
                        decision_items = list(precomputed.get("decision_items") or [])
                        decision_summary = precomputed.get("decision_summary") or attention_summary
                        suppressed_cards = home_sections.get("suppressed_signals", [])
                        is_stale = bool(meaning.state_flags.get("stale_data"))
                        weak_data_mode = bool(meaning.weak_data_mode)
                        show_secondary_open = bool(st.session_state.get("_first_import_just_completed"))
                        render_plan_build_count = 0
                        render_plan_build_ms = 0
                        render_plan_enrich_ms = 0
                        render_plan_second_build_count = 0
                        pre_action_render_plan_cache_hit = 0
                        pre_action_render_plan_cache_miss = 0
                        pre_action_render_plan_cache_skipped = 0
                        enriched_render_plan_cache_hit = 0
                        enriched_render_plan_cache_miss = 0
                        enriched_render_plan_cache_skipped = 0
                        pre_action_queue_fingerprint = _today_pre_action_render_plan_input_fingerprint(
                            attention=decision_summary,
                            decision_items=decision_items,
                            suppressed_cards=suppressed_cards,
                            snapshot_cards=snapshot_cards,
                            last_action_lookup=last_action_lookup,
                            today_iso=today_value.isoformat(),
                            is_stale=is_stale,
                            weak_data_mode=weak_data_mode,
                            show_secondary_open=show_secondary_open,
                        )
                        pre_action_cache_key = _pre_action_render_plan_page_cache_key(
                            tenant_id=tenant_id,
                            today_iso=today_value.isoformat(),
                            context_day_key=str(precomputed.get("as_of_date") or today_value.isoformat()),
                            queue_fingerprint=pre_action_queue_fingerprint,
                            surface_flags="|".join(
                                [
                                    f"stale:{int(is_stale)}",
                                    f"weak:{int(weak_data_mode)}",
                                    f"secondary:{int(show_secondary_open)}",
                                ]
                            ),
                        )
                        pre_action_render_plan = _get_cached_pre_action_render_plan_page(cache_key=pre_action_cache_key)
                        if isinstance(pre_action_render_plan, TodayQueueRenderPlan):
                            pre_action_render_plan_cache_hit = 1
                        else:
                            pre_action_render_plan_cache_miss = 1
                            render_plan_build_started = time.perf_counter()
                            pre_action_render_plan = build_today_queue_render_plan(
                                attention=decision_summary,
                                decision_items=decision_items,
                                suppressed_cards=suppressed_cards,
                                today_value=today_value,
                                is_stale=is_stale,
                                weak_data_mode=weak_data_mode,
                                show_secondary_open=show_secondary_open,
                                snapshot_cards=snapshot_cards,
                                last_action_lookup=last_action_lookup,
                                action_state_lookup=None,
                            )
                            render_plan_build_ms += int(max(0.0, (time.perf_counter() - render_plan_build_started) * 1000))
                            render_plan_build_count += 1
                            _set_cached_pre_action_render_plan_page(cache_key=pre_action_cache_key, plan=pre_action_render_plan)

                        with action_wrapper_profile.stage("visible_employee_ids_build"):
                            action_state_employee_ids = _today_action_state_employee_ids(
                                plan=pre_action_render_plan,
                            )
                            actionable_card_count = _today_action_state_actionable_card_count(plan=pre_action_render_plan)
                            should_load_action_state_lookup = bool(actionable_card_count > 0 and action_state_employee_ids)

                        profile.set("action_state_employee_ids", len(action_state_employee_ids or ()))
                        profile.set("action_state_actionable_cards", int(actionable_card_count))
                        action_wrapper_profile.set("employee_ids_count", len(action_state_employee_ids or ()))

                        action_state_lookup: dict[str, dict[str, Any]] = {}
                        action_state_lookup_skipped = 0
                        action_state_lookup_cache_hit = 0
                        action_state_lookup_cache_miss = 0
                        render_plan = pre_action_render_plan
                        render_plan_cache_key = ""
                        cached_enriched_plan: TodayQueueRenderPlan | None = None

                        with action_wrapper_profile.stage("action_state_lookup_call"):
                            if not should_load_action_state_lookup:
                                action_state_lookup_skipped = 1
                                enriched_render_plan_cache_skipped = 1
                            else:
                                render_plan_cache_key = _enriched_render_plan_page_cache_key(
                                    tenant_id=tenant_id,
                                    today_iso=today_value.isoformat(),
                                    context_day_key=str(precomputed.get("as_of_date") or today_value.isoformat()),
                                    visible_employee_ids=action_state_employee_ids,
                                    render_plan_fingerprint=_today_render_plan_fingerprint(plan=pre_action_render_plan),
                                )
                                cached_enriched_plan = _get_cached_enriched_render_plan_page(cache_key=render_plan_cache_key)
                                if isinstance(cached_enriched_plan, TodayQueueRenderPlan):
                                    render_plan = cached_enriched_plan
                                    enriched_render_plan_cache_hit = 1
                                else:
                                    enriched_render_plan_cache_miss = 1
                                    action_state_lookup, page_cache_hit = _cached_today_action_state_lookup_page(
                                        tenant_id=tenant_id,
                                        employee_ids=action_state_employee_ids,
                                        today_iso=today_value.isoformat(),
                                    )
                                    if page_cache_hit:
                                        action_state_lookup_cache_hit = 1
                                    else:
                                        action_state_lookup_cache_miss = 1

                        action_wrapper_profile.set("lookup_rows_count", len(action_state_lookup or {}))

                        with action_wrapper_profile.stage("post_lookup_state_transform"):
                            if should_load_action_state_lookup and not isinstance(cached_enriched_plan, TodayQueueRenderPlan):
                                if action_state_lookup:
                                    render_plan_enrich_started = time.perf_counter()
                                    render_plan = _enrich_render_plan_action_state(
                                        plan=pre_action_render_plan,
                                        today_value=today_value,
                                        last_action_lookup=last_action_lookup,
                                        action_state_lookup=action_state_lookup,
                                    )
                                    render_plan_enrich_ms = int(max(0.0, (time.perf_counter() - render_plan_enrich_started) * 1000))
                                _set_cached_enriched_render_plan_page(cache_key=render_plan_cache_key, plan=render_plan)

                        with action_wrapper_profile.stage("final_state_attach"):
                            profile.set("action_state_lookup_skipped", int(action_state_lookup_skipped))
                            profile.set("action_state_lookup_cache_hit", int(action_state_lookup_cache_hit))
                            profile.set("action_state_lookup_cache_miss", int(action_state_lookup_cache_miss))
                            profile.set("pre_action_render_plan_cache_hit", int(pre_action_render_plan_cache_hit))
                            profile.set("pre_action_render_plan_cache_miss", int(pre_action_render_plan_cache_miss))
                            profile.set("pre_action_render_plan_cache_skipped", int(pre_action_render_plan_cache_skipped))
                            profile.set("enriched_render_plan_cache_hit", int(enriched_render_plan_cache_hit))
                            profile.set("enriched_render_plan_cache_miss", int(enriched_render_plan_cache_miss))
                            profile.set("enriched_render_plan_cache_skipped", int(enriched_render_plan_cache_skipped))
                            profile.set("render_plan_build_count", int(render_plan_build_count))
                            profile.set("render_plan_build_ms", int(render_plan_build_ms))
                            profile.set("render_plan_second_build_count", int(render_plan_second_build_count))
                            profile.set("render_plan_enrich_ms", int(render_plan_enrich_ms))

            orientation_state = meaning.surface_state
            if (
                orientation_state == TodaySurfaceState.NO_STRONG_SIGNALS
                and signal_mode in {SignalMode.EARLY_SIGNAL, SignalMode.LIMITED_DATA}
                and snapshot_cards
            ):
                orientation_state = TodaySurfaceState.EARLY_SIGNAL

            orientation_model = build_queue_orientation(attention_summary)
            with profile.stage("render_queue_orientation"):
                if decision_summary.ranked_items:
                    orientation_model = build_queue_orientation(decision_summary)
                if snapshot_cards and orientation_model.total_shown <= 0:
                    orientation_model = TodayQueueOrientationModel(
                        total_shown=len(snapshot_cards),
                        declining_count=orientation_model.declining_count,
                        repeat_count=orientation_model.repeat_count,
                        limited_confidence_count=orientation_model.limited_confidence_count,
                        distinct_processes=orientation_model.distinct_processes,
                        total_evaluated=orientation_model.total_evaluated,
                    )

            attention_strip = TodayAttentionStripViewModel(
                total_needing_attention=0,
                new_today=0,
                overdue_follow_ups=0,
                reviewed_today=0,
                touchpoints_logged_today=0,
                follow_ups_scheduled_today=0,
            )
            manager_loop_strip: TodayManagerLoopStripViewModel | None = None
            with profile.stage("weekly_activity"):
                rendered_card_count = _today_rendered_card_count(plan=render_plan)
                profile.set("weekly_activity_rendered_cards", int(rendered_card_count))
                weekly_activity_skipped = 0
                weekly_activity_cache_hit = 0
                weekly_activity_cache_miss = 0
                if rendered_card_count > 0:
                    weekly_activity, weekly_cache_hit = _cached_weekly_manager_activity_summary_page(
                        tenant_id=tenant_id,
                        lookback_days=7,
                        today_iso=today_value.isoformat(),
                    )
                    if weekly_cache_hit:
                        weekly_activity_cache_hit = 1
                    else:
                        weekly_activity_cache_miss = 1
                else:
                    weekly_activity_skipped = 1
                    weekly_activity = {
                        "reviewed_issues": 0,
                        "follow_up_touchpoints": 0,
                        "closed_issues": 0,
                        "improved_outcomes": 0,
                        "reviewed_today": 0,
                        "touchpoints_logged_today": 0,
                        "follow_ups_scheduled_today": 0,
                    }
                profile.set("weekly_activity_skipped", int(weekly_activity_skipped))
                profile.set("weekly_activity_cache_hit", int(weekly_activity_cache_hit))
                profile.set("weekly_activity_cache_miss", int(weekly_activity_cache_miss))

                attention_strip = build_today_attention_strip(
                    attention=decision_summary,
                    queue_items=queue_items,
                    today=today_value,
                    same_day_activity=weekly_activity,
                )
                manager_loop_strip = build_today_manager_loop_strip(
                    queue_items=queue_items,
                    weekly_activity=weekly_activity,
                )

            weekly_summary = TodayWeeklySummaryViewModel(items=[])
            with profile.stage("render_weekly_summary"):
                weekly_summary = build_today_weekly_summary_view_model(
                    reviewed_issues=int(weekly_activity.get("reviewed_issues", 0) or 0),
                    follow_up_touchpoints=int(weekly_activity.get("follow_up_touchpoints", 0) or 0),
                    closed_issues=int(weekly_activity.get("closed_issues", 0) or 0),
                    improved_outcomes=int(weekly_activity.get("improved_outcomes", 0) or 0),
                )

            with profile.stage("render_queue"):
                render_prep_started = time.perf_counter()
                prepared_queue_render = _prepare_today_top_queue_render(
                    plan=render_plan,
                    tenant_id=tenant_id,
                    today_value=today_value,
                )
                base_card_render_prep_ms = int(max(0.0, (time.perf_counter() - render_prep_started) * 1000))
                active_signal_ids = {
                    str(getattr(card, "signal_key", "") or "").strip()
                    for card in list(render_plan.primary_cards or []) + list(render_plan.secondary_cards or [])
                    if str(getattr(card, "signal_key", "") or "").strip()
                }
                cleaned_widget_keys = _cleanup_today_widget_state(active_signal_ids=active_signal_ids)
                profile.set("queue_derivation_ms", int(prepared_queue_render.get("queue_derivation_ms") or 0))
                profile.set("queue_filter_ms", int(prepared_queue_render.get("queue_filter_ms") or 0))
                profile.set("visible_top3_derivation_ms", int(prepared_queue_render.get("top3_derivation_ms") or 0))
                profile.set("signal_status_map_ms", int(prepared_queue_render.get("signal_status_map_ms") or 0))
                profile.set("base_card_render_prep_ms", int(base_card_render_prep_ms))
                profile.set("widget_state_cleaned_keys", int(cleaned_widget_keys))

                people_needing_attention = int(prepared_queue_render.get("people_needing_attention") or 0)

                _log_operational_event(
                    "today_top3_render_timing",
                    status="info",
                    tenant_id=str(tenant_id or ""),
                    user_email=str(st.session_state.get("user_email", "") or ""),
                    context={
                        "queue_derivation_ms": int(prepared_queue_render.get("queue_derivation_ms") or 0),
                        "queue_filter_ms": int(prepared_queue_render.get("queue_filter_ms") or 0),
                        "visible_top3_derivation_ms": int(prepared_queue_render.get("top3_derivation_ms") or 0),
                        "signal_status_map_ms": int(prepared_queue_render.get("signal_status_map_ms") or 0),
                        "base_card_render_prep_ms": int(base_card_render_prep_ms),
                        "active_queue_count": len(list(prepared_queue_render.get("active_ranked_cards") or [])),
                        "visible_top3_count": len(list(prepared_queue_render.get("top_cards") or [])),
                        "overflow_count": len(list(prepared_queue_render.get("overflow_cards") or [])),
                    },
                )

                _render_unified_attention_queue(
                    decision_summary,
                    decision_items=decision_items,
                    suppressed_cards=home_sections.get("suppressed_signals", []),
                    goal_status=goal_status,
                    is_stale=bool(meaning.state_flags.get("stale_data")),
                    show_secondary_open=bool(st.session_state.get("_first_import_just_completed")),
                    weak_data_mode=bool(meaning.weak_data_mode),
                    snapshot_cards=snapshot_cards,
                    last_action_lookup=last_action_lookup,
                    action_state_lookup=action_state_lookup,
                    manager_loop_strip=manager_loop_strip,
                    low_data_fallback=low_data_fallback,
                    render_plan=render_plan,
                    prepared_queue_render=prepared_queue_render,
                )

                phase2_top3_ready_ms = int(max(0.0, (time.perf_counter() - page_started_at) * 1000))
                profile.set("today_top3_ready_ms", int(phase2_top3_ready_ms))

            profile.set("supporting_context_cards", 0)

            phase2_render_ms = int(max(0.0, (time.perf_counter() - phase2_started_at) * 1000))
            profile.set("today_phase2_render_ms", int(phase2_render_ms))
            _log_operational_event(
                "today_phase2_render_timing",
                status="info",
                tenant_id=str(tenant_id or ""),
                user_email=str(st.session_state.get("user_email", "") or ""),
                context={
                    "today_phase2_render_ms": int(phase2_render_ms),
                    "today_top3_ready_ms": int(profile.metrics.get("today_top3_ready_ms", 0) or 0),
                },
            )

            _log_today_milestone(
                "today_main_body_complete",
                tenant_id=tenant_id,
                context={"phase2_render_ms": int(phase2_render_ms)},
            )

            # Emit one consolidated run summary event
            _milestones_snap = list(st.session_state.get(_TODAY_RUN_MILESTONES_KEY) or [])
            _ms_by_name = {str(m.get("name") or ""): int(m.get("elapsed_ms") or 0) for m in _milestones_snap}
            _log_today_milestone(
                "today_run_summary",
                tenant_id=tenant_id,
                context={
                    "total_to_shell_ms": int(_ms_by_name.get("today_loading_shell_painted") or 0),
                    "total_to_recovery_start_ms": int(_ms_by_name.get("today_recovery_started") or 0),
                    "total_to_snapshot_check_ms": int(_ms_by_name.get("today_snapshot_check_done") or 0),
                    "total_to_snapshot_recompute_ms": int(_ms_by_name.get("today_snapshot_recompute_done") or 0),
                    "total_to_signal_compute_ms": int(_ms_by_name.get("today_signal_compute_done") or 0),
                    "total_to_payload_ready_ms": int(_ms_by_name.get("today_payload_ready") or 0),
                    "total_to_rerun_ms": int(_ms_by_name.get("today_rerun_triggered") or 0),
                    "total_to_phase1_start_ms": int(_ms_by_name.get("today_phase1_started") or 0),
                    "total_to_top3_ms": int(_ms_by_name.get("today_top3_ready") or 0),
                    "total_to_phase2_start_ms": int(_ms_by_name.get("today_phase2_started") or 0),
                    "total_to_main_body_ms": int(_ms_by_name.get("today_main_body_complete") or 0),
                    "old_screen_cleared_before_shell": (
                        bool(_ms_by_name.get("today_loading_shell_painted"))
                        and bool(_ms_by_name.get("today_page_entered"))
                        and int(_ms_by_name.get("today_loading_shell_painted") or 0)
                        <= int(_ms_by_name.get("today_recovery_started") or 0)
                    ),
                    "rerun_happened": bool(_ms_by_name.get("today_rerun_triggered")),
                    "milestone_count": len(_milestones_snap),
                },
            )

            if bool(st.session_state.get("_first_import_just_completed")):
                st.session_state["_first_import_just_completed"] = False
    finally:
        st.session_state["_ui_render_guard_active"] = False


def page_today() -> None:
    root_placeholder = st.empty()
    with root_placeholder.container():
        _page_today_impl(root_placeholder=root_placeholder)