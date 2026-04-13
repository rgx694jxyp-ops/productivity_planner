"""Today page.

Queue-first supervisor workflow focused on daily follow-through.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from core.dependencies import _bust_cache, _cached_employees, _log_app_error
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
    TodayQueueCardViewModel,
    TodayValueStripViewModel,
    build_today_queue_card_from_insight_card,
    build_today_value_strip_view_model,
)
from services.signal_traceability_service import traceability_payload_from_card
from services.plain_language_service import signal_wording
from ui.state_panels import (
    show_error_state,
    show_loading_state,
    show_success_state,
)
from ui.traceability_panel import render_traceability_panel


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
            color: #6c8198;
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
            margin-top: -2px;
            margin-bottom: 10px;
            color: #5d7693;
            font-size: 0.92rem;
        }
        .today-value-card {
            background: linear-gradient(180deg, #f9fbfe 0%, #eef4fb 100%);
            border: 1px solid #d9e4f0;
            border-radius: 14px;
            padding: 14px 14px 12px;
            min-height: 132px;
            margin-bottom: 10px;
        }
        .today-value-title {
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #6a8098;
            margin-bottom: 8px;
        }
        .today-value-headline {
            color: #0f2d52;
            font-size: 1rem;
            font-weight: 800;
            line-height: 1.28;
            margin-bottom: 6px;
        }
        .today-value-detail {
            color: #49647f;
            font-size: 0.87rem;
            line-height: 1.38;
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
            color: #6c8198;
            font-size: 0.84rem;
        }
        .today-secondary-note {
            color: #6c8198;
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
        .today-queue-orientation {
            background: #f4f8fc;
            border: 1px solid #dce9f5;
            border-radius: 10px;
            padding: 10px 14px;
            margin-bottom: 12px;
            font-size: 0.9rem;
            color: #335a80;
            line-height: 1.55;
        }
        .today-queue-orientation-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 6px;
        }
        .today-queue-chip {
            display: inline-block;
            background: #e8f0f8;
            color: #335a80;
            border-radius: 999px;
            padding: 2px 10px;
            font-size: 0.8rem;
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
        </style>
        """,
        unsafe_allow_html=True,
    )


def _show_flash_message() -> None:
    message = str(st.session_state.pop("today_flash_message", "") or "")
    if message:
        show_success_state(message)


def _is_demo_upload_row(upload_row: dict[str, Any]) -> bool:
    if not bool(upload_row.get("is_active")):
        return False

    try:
        from services.import_service import _decode_jsonish

        meta = _decode_jsonish(upload_row.get("header_mapping"))
    except Exception:
        meta = {}

    if not isinstance(meta, dict):
        meta = {}

    stats = dict(meta.get("stats") or {})
    source_mode = str(meta.get("source_mode") or stats.get("source_mode") or "").strip().lower()
    if source_mode != "demo":
        return False

    if bool(meta.get("undo_applied_at")):
        return False

    return True


def _reset_demo_uploads(*, tenant_id: str) -> dict[str, int]:
    from services.import_service import _decode_jsonish, _deactivate_upload, _list_recent_uploads, _restore_uph_snapshot

    summary = {
        "demo_uploads_found": 0,
        "demo_uploads_reset": 0,
        "restored_rows": 0,
        "verified_deleted_rows": 0,
        "skipped_without_snapshot": 0,
    }

    # Look back 90 days max for demo uploads (not 10 years).
    # Most demo resets happen within days of import; older data is unlikely to be demo.
    uploads = list(_list_recent_uploads(tenant_id=tenant_id, days=90) or [])
    for upload in uploads:
        if not _is_demo_upload_row(upload):
            continue

        summary["demo_uploads_found"] += 1
        meta = _decode_jsonish(upload.get("header_mapping"))
        if not isinstance(meta, dict):
            meta = {}

        undo = meta.get("undo", {}) if isinstance(meta, dict) else {}
        new_row_ids = list(undo.get("new_row_ids", []) or [])
        previous_rows = list(undo.get("previous_rows", []) or [])
        touched_keys = list(undo.get("touched_keys", []) or [])

        if not new_row_ids and not previous_rows and not touched_keys:
            summary["skipped_without_snapshot"] += 1
            continue

        restored_rows, _attempted_deletes, verified_deleted = _restore_uph_snapshot(
            tenant_id,
            new_row_ids,
            previous_rows,
            touched_keys,
        )
        summary["restored_rows"] += int(restored_rows)
        summary["verified_deleted_rows"] += int(verified_deleted)

        meta["undo_applied_at"] = date.today().isoformat()
        meta["undo_result"] = {
            "source": "today_demo_reset",
            "restored_rows": int(restored_rows),
            "verified_deleted": int(verified_deleted),
        }
        _deactivate_upload(tenant_id, upload.get("id"), meta)
        summary["demo_uploads_reset"] += 1

    return summary


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

    chips: list[str] = []
    if source_mode == "demo":
        chips.append("Demo mode")
    if stale_days > 0:
        day_word = "day" if stale_days == 1 else "days"
        chips.append(f"Data {stale_days} {day_word} old")
    if meaning.signal_mode == SignalMode.LIMITED_DATA:
        chips.append("Limited history")
    elif meaning.signal_mode == SignalMode.EARLY_SIGNAL:
        chips.append("Early signal mode")

    if meaning.status_line:
        primary_line = meaning.status_line
    else:
        primary_line = "Signals are ranked by current evidence strength and recency."

    detail_line = ""
    if source_mode == "demo":
        detail_line = "Demo mode is active: the queue is based on sample history, not live uploaded operations data."
        if source_label:
            detail_line += f" Source: {source_label}."

    chips_html = "".join(f'<span class="today-queue-chip">{chip}</span>' for chip in chips)
    chips_block = f'<div class="today-queue-orientation-chips">{chips_html}</div>' if chips else ""
    detail_block = (
        f'<div style="color:#5d7693;font-size:0.86rem;margin-top:6px;">{detail_line}</div>' if detail_line else ""
    )

    st.markdown(
        (
            '<div class="today-queue-orientation">'
            '<strong>Today status</strong>'
            f'{chips_block}'
            f'<div style="margin-top:6px;">{primary_line}</div>'
            f'{detail_block}'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


def _attempt_signal_payload_recovery(*, tenant_id: str, today_value: date) -> bool:
    """Try to rebuild today's payload once when it is missing or deferred."""
    try:
        from services.daily_signals_service import build_transient_today_payload, compute_daily_signals

        try:
            compute_daily_signals(
                signal_date=today_value,
                tenant_id=tenant_id,
            )
            st.session_state["_post_import_refresh_pending"] = False
        except Exception as compute_err:
            message = str(compute_err or "")
            if "daily_signals" in message or "PGRST205" in message:
                st.session_state["_today_precomputed_payload"] = build_transient_today_payload(
                    signal_date=today_value,
                    tenant_id=tenant_id,
                )
            else:
                raise

        if hasattr(get_today_signals, "cache_clear"):
            get_today_signals.cache_clear()
        elif hasattr(get_today_signals, "clear"):
            get_today_signals.clear()
        return True
    except Exception as recovery_err:
        # Avoid retry loops that can make Today appear stuck after a failed recovery.
        st.session_state["_post_import_refresh_pending"] = False
        show_error_state(f"Today signal recovery failed: {recovery_err}")
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
                    "<strong>No usable data is available yet.</strong><br>"
                    '<span style="color:#5d7693;font-size:0.86rem;">'
                    "The system could not evaluate today against recent performance because imported history is not available yet."
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
    if in_early:
        mode_label = (
            "Limited history" if signal_mode == SignalMode.LIMITED_DATA else "Early signal mode"
        )
        heading = "What needs attention today"
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
        signal_word = "signal" if total == 1 else "signals"
        heading = f"{total} {signal_word} in today's queue"
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


def _render_empty_state() -> None:
    with st.container(border=True):
        st.markdown("### No priority signals right now")
        st.write(
            "That means the queue is clear for the moment. This page becomes valuable when fresh productivity data "
            "turns into a short list of people with noteworthy changes, follow-up context, or recognition signals."
        )
        st.info("The queue updates when newer data snapshots are available.")


def _render_first_time_empty_state() -> None:
    """Onboarding-focused empty state for users who just completed first import."""
    with st.container(border=True):
        st.markdown("### First signals are ready")
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
        lines.append(signal_wording("not_enough_history_yet"))
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


def _format_signal_status_label(signal_status: str) -> str:
    normalized = str(signal_status or "").strip().lower()
    if normalized == SIGNAL_STATUS_LOOKED_AT:
        return "Looked at"
    if normalized == SIGNAL_STATUS_NEEDS_FOLLOW_UP:
        return "Needs follow-up"
    return ""


def _render_signal_status_controls(*, card: TodayQueueCardViewModel, key_prefix: str, status_map: dict[str, dict[str, str]]) -> None:
    signal_key = str(getattr(card, "signal_key", "") or "").strip()
    employee_id = str(card.employee_id or "").strip()
    if not signal_key or not employee_id:
        return

    current = dict(status_map.get(signal_key) or {})
    current_status = _format_signal_status_label(str(current.get("status") or ""))
    owner = str(current.get("owner") or "").strip()
    if current_status:
        owner_suffix = f" - {owner}" if owner else ""
        st.markdown(
            f'<div class="today-signal-status-chip">Status: {current_status}{owner_suffix}</div>',
            unsafe_allow_html=True,
        )

    left, right, _ = st.columns([1.05, 1.4, 2.8])
    with left:
        looked_at_clicked = st.button(
            "Looked at",
            key=f"{key_prefix}_{signal_key}_looked_at",
            use_container_width=True,
            type="secondary",
        )
    with right:
        follow_up_clicked = st.button(
            "Needs follow-up",
            key=f"{key_prefix}_{signal_key}_needs_follow_up",
            use_container_width=True,
            type="secondary",
        )

    selected = ""
    if looked_at_clicked:
        selected = SIGNAL_STATUS_LOOKED_AT
    elif follow_up_clicked:
        selected = SIGNAL_STATUS_NEEDS_FOLLOW_UP

    if not selected:
        return

    owner_value = str(st.session_state.get("user_email") or st.session_state.get("user_name") or "").strip()
    tenant_id = str(st.session_state.get("tenant_id") or "").strip()
    saved = set_signal_status(
        signal_key=signal_key,
        employee_id=employee_id,
        signal_status=selected,
        owner=owner_value,
        tenant_id=tenant_id,
    )
    if saved:
        st.session_state["today_flash_message"] = "Signal status saved."
        st.rerun()


def _render_attention_card(
    *,
    card: TodayQueueCardViewModel,
    key_prefix: str,
    compact: bool = False,
    show_action: bool = True,
    signal_status_map: dict[str, dict[str, str]] | None = None,
) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="today-insight-title">{card.line_1}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="today-insight-line">{card.line_2}</div>', unsafe_allow_html=True)
        if str(card.line_3 or "").strip():
            st.markdown(f'<div class="today-insight-line">{card.line_3}</div>', unsafe_allow_html=True)

        line_5_text = str(card.line_5 or "").strip()
        freshness_text = str(card.freshness_line or "").strip()
        chip_html = _confidence_chip(line_5_text)
        if chip_html:
            st.markdown(chip_html, unsafe_allow_html=True)
        if line_5_text.lower() == "low confidence":
            st.markdown(f'<div class="today-confidence-badge-low">{line_5_text}</div>', unsafe_allow_html=True)
            if freshness_text:
                st.markdown(f'<div class="today-freshness-meta">{freshness_text}</div>', unsafe_allow_html=True)
        else:
            confidence_freshness = line_5_text
            if freshness_text:
                confidence_freshness = (
                    f"{line_5_text} · {freshness_text}" if line_5_text else freshness_text
                )
            if confidence_freshness:
                st.markdown(f'<div class="today-insight-meta">{confidence_freshness}</div>', unsafe_allow_html=True)

        if str(card.line_4 or "").strip():
            st.markdown(f'<div class="today-insight-line">{card.line_4}</div>', unsafe_allow_html=True)

        collapsed_hint = str(getattr(card, "collapsed_hint", "") or "").strip()
        if collapsed_hint:
            st.markdown(f'<div class="today-insight-meta">{collapsed_hint}</div>', unsafe_allow_html=True)
        collapsed_evidence = str(getattr(card, "collapsed_evidence", "") or "").strip()
        line_4_text = str(card.line_4 or "").strip().lower()
        if collapsed_evidence and collapsed_evidence.strip().lower() != line_4_text:
            st.markdown(f'<div class="today-insight-meta">{collapsed_evidence}</div>', unsafe_allow_html=True)
        collapsed_issue = str(getattr(card, "collapsed_issue", "") or "").strip()
        if collapsed_issue:
            st.markdown(f'<div class="today-insight-meta">{collapsed_issue}</div>', unsafe_allow_html=True)

        if not compact and card.expanded_lines:
            with st.expander("Why this is shown", expanded=False):
                for line in card.expanded_lines[:3]:
                    st.write(line)

        if signal_status_map is not None:
            _render_signal_status_controls(
                card=card,
                key_prefix=f"{key_prefix}_status",
                status_map=signal_status_map,
            )

        if show_action:
            if st.button(
                "View details →",
                key=f"{key_prefix}_{card.employee_id}_{card.process_id}",
                use_container_width=False,
                type="secondary",
            ):
                st.session_state["goto_page"] = "team"
                st.session_state["emp_view"] = "Performance Journal"
                st.session_state["cn_selected_emp"] = card.employee_id
                st.rerun()


def _render_unified_attention_queue(
    attention: AttentionSummary,
    *,
    suppressed_cards: list[InsightCardContract] | None = None,
    is_stale: bool = False,
    show_secondary_open: bool = False,
    weak_data_mode: bool = False,
    snapshot_cards: list[TodayQueueCardViewModel] | None = None,
) -> None:
    plan: TodayQueueRenderPlan = build_today_queue_render_plan(
        attention=attention,
        suppressed_cards=suppressed_cards,
        today_value=date.today(),
        is_stale=is_stale,
        weak_data_mode=weak_data_mode,
        show_secondary_open=show_secondary_open,
        snapshot_cards=snapshot_cards,
    )

    st.markdown(f'<div class="today-section-label">{plan.section_title}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="today-supporting-note">{plan.start_note}</div>',
        unsafe_allow_html=True,
    )

    all_signal_keys = {
        str(getattr(card, "signal_key", "") or "").strip()
        for card in (list(plan.primary_cards) + list(plan.secondary_cards))
        if str(getattr(card, "signal_key", "") or "").strip()
    }
    signal_status_map = list_latest_signal_statuses(
        signal_keys=all_signal_keys,
        tenant_id=str(st.session_state.get("tenant_id") or "").strip(),
    )

    if plan.primary_placeholder:
        st.markdown(f'<div class="today-placeholder">{plan.primary_placeholder}</div>', unsafe_allow_html=True)
    else:
        for idx, card in enumerate(plan.primary_cards):
            _render_attention_card(
                card=card,
                key_prefix=f"today_attention_primary_{idx}",
                signal_status_map=signal_status_map,
            )

    if plan.secondary_cards:
        st.markdown(f'<div class="today-secondary-subcaption">{plan.secondary_caption}</div>', unsafe_allow_html=True)
        with st.expander("Other items", expanded=bool(plan.secondary_expanded)):
            for idx, card in enumerate(plan.secondary_cards[:20]):
                _render_attention_card(
                    card=card,
                    key_prefix=f"today_attention_other_{idx}",
                    compact=True,
                    show_action=False,
                    signal_status_map=signal_status_map,
                )

    if plan.suppressed_debug_rows:
        st.session_state["_today_suppressed_signals_debug"] = list(plan.suppressed_debug_rows)


def _render_today_value_strip(value_strip: TodayValueStripViewModel, *, freshness_note: str = "", is_stale: bool = False) -> None:
    if not value_strip.cards:
        return

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
            st.markdown(
                (
                    '<div class="today-value-card">'
                    f'<div class="today-value-title">{display_title}</div>'
                    f'<div class="today-value-headline">{card.headline}</div>'
                    f'<div class="today-value-detail">{card.detail}</div>'
                    '</div>'
                ),
                unsafe_allow_html=True,
            )


def _render_insight_card(item: InsightCardContract, *, key_prefix: str) -> None:
    card_vm = build_today_queue_card_from_insight_card(card=item, today=date.today())
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
        st.markdown(f'<div class="today-insight-line">{card_vm.line_2}</div>', unsafe_allow_html=True)
        if str(card_vm.line_3 or "").strip():
            st.markdown(f'<div class="today-insight-line">{card_vm.line_3}</div>', unsafe_allow_html=True)

        line_5_text = str(card_vm.line_5 or "").strip()
        freshness_text = str(card_vm.freshness_line or "").strip()
        chip_html = _confidence_chip(line_5_text)
        if chip_html:
            st.markdown(chip_html, unsafe_allow_html=True)
        if line_5_text.lower() == "low confidence":
            st.markdown(f'<div class="today-confidence-badge-low">{line_5_text}</div>', unsafe_allow_html=True)
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
                    if hasattr(get_today_signals, "cache_clear"):
                        get_today_signals.cache_clear()
                    elif hasattr(get_today_signals, "clear"):
                        get_today_signals.clear()
                    st.success("Signals refreshed.")
                    st.rerun()
                except Exception as _refresh_err:
                    show_error_state(f"Signal refresh failed: {_refresh_err}")
                    return

        try:
            tenant_id = str(st.session_state.get("tenant_id", "") or "")
            recovery_attempted = False

            # If large-import refresh was deferred, recover payload here so Today never stalls.
            if bool(st.session_state.get("_post_import_refresh_pending")):
                with st.spinner("Finalizing imported signals for Today…"):
                    _attempt_signal_payload_recovery(tenant_id=tenant_id, today_value=today_value)
                recovery_attempted = True

            # Today page is read-only: it renders precomputed signals and summaries
            # and does not run trigger pipelines, trend computation, or scoring.
            precomputed = get_today_signals(
                tenant_id=tenant_id,
                as_of_date=today_value.isoformat(),
            )
            if not precomputed:
                if not recovery_attempted:
                    with st.spinner("Preparing today's queue…"):
                        recovery_attempted = _attempt_signal_payload_recovery(tenant_id=tenant_id, today_value=today_value)
                    if recovery_attempted:
                        precomputed = get_today_signals(
                            tenant_id=tenant_id,
                            as_of_date=today_value.isoformat(),
                        )

                if not precomputed:
                    st.info("Today's queue is still preparing. Use Refresh signals if this does not clear shortly.")
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
            if not import_summary:
                import_summary = st.session_state.get("_import_complete_summary") or {}
            if not isinstance(import_summary, dict):
                import_summary = {}

            if not goal_status:
                goal_status = []
        except Exception as exc:
            show_error_state(f"Today screen data could not load cleanly: {exc}")
            return

        meaning = build_today_surface_meaning(
            goal_status=goal_status,
            import_summary=import_summary,
            home_sections=home_sections,
            has_queue_items=counts.get("all", 0) > 0,
            as_of_date=str(precomputed.get("as_of_date") or ""),
            today_value=today_value,
        )

        _render_top_status_area(meaning=meaning)

        # Build snapshot fallback cards when trend history is too thin.
        signal_mode = meaning.signal_mode
        snapshot_cards = None
        if signal_mode in (SignalMode.EARLY_SIGNAL, SignalMode.LIMITED_DATA):
            snapshot_cards = build_snapshot_fallback_cards(
                goal_status=goal_status,
                today=today_value,
            ) or None

        orientation_state = meaning.surface_state
        if (
            orientation_state == TodaySurfaceState.NO_STRONG_SIGNALS
            and signal_mode in {SignalMode.EARLY_SIGNAL, SignalMode.LIMITED_DATA}
            and snapshot_cards
        ):
            orientation_state = TodaySurfaceState.EARLY_SIGNAL

        orientation_model = build_queue_orientation(attention_summary)
        if snapshot_cards and orientation_model.total_shown <= 0:
            orientation_model = TodayQueueOrientationModel(
                total_shown=len(snapshot_cards),
                declining_count=orientation_model.declining_count,
                repeat_count=orientation_model.repeat_count,
                limited_confidence_count=orientation_model.limited_confidence_count,
                distinct_processes=orientation_model.distinct_processes,
                total_evaluated=orientation_model.total_evaluated,
            )

        _render_queue_orientation_block(
            orientation_model,
            meaning=meaning,
            surface_state=orientation_state,
            signal_mode=signal_mode,
        )

        _render_unified_attention_queue(
            attention_summary,
            suppressed_cards=home_sections.get("suppressed_signals", []),
            is_stale=bool(meaning.state_flags.get("stale_data")),
            show_secondary_open=bool(st.session_state.get("_first_import_just_completed")),
            weak_data_mode=bool(meaning.weak_data_mode),
            snapshot_cards=snapshot_cards,
        )

        _supporting_context_key = "_today_supporting_context_loaded"
        if bool(st.session_state.get("_first_import_just_completed")):
            st.session_state[_supporting_context_key] = True

        _show_supporting_context = bool(st.session_state.get(_supporting_context_key, False))
        if _show_supporting_context:
            value_strip = build_today_value_strip_view_model(
                goal_status=goal_status,
                import_summary=meaning.import_summary,
            )
            if value_strip.cards:
                with st.expander("Supporting context", expanded=bool(st.session_state.get("_first_import_just_completed"))):
                    _render_today_value_strip(
                        value_strip,
                        freshness_note=meaning.freshness_note,
                        is_stale=bool(meaning.state_flags.get("stale_data")),
                    )
                    if st.button("Hide supporting context", key="today_hide_supporting_context", type="secondary"):
                        st.session_state[_supporting_context_key] = False
                        st.rerun()
        else:
            st.info("Supporting context is available on demand to keep Today reruns responsive.")
            if st.button("Load supporting context", key="today_load_supporting_context", type="secondary"):
                st.session_state[_supporting_context_key] = True
                st.rerun()

        if bool(st.session_state.get("_first_import_just_completed")):
            st.session_state["_first_import_just_completed"] = False
    finally:
        st.session_state["_ui_render_guard_active"] = False