"""Today page meaning service.

Owns page-level product meaning decisions so UI modules can render precomputed props.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import os
from typing import Any

from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionSummary
from services.decision_engine_service import DecisionItem
from services.decision_surfacing_policy_service import build_decision_surfacing_policy
from services.today_snapshot_signal_service import (
    SignalMode,
    classify_signal_mode,
)
from services.today_view_model_service import TodayQueueCardViewModel, build_today_queue_view_model


@dataclass(frozen=True)
class TodayQueueOrientationModel:
    """Compact summary derived from the ranked attention items.

    Counts are derived directly from AttentionItem.factors_applied so the
    orientation block always reflects the same evidence the queue cards show.
    """

    total_shown: int
    declining_count: int
    repeat_count: int
    limited_confidence_count: int
    distinct_processes: int
    total_evaluated: int


class TodaySurfaceState(str, Enum):
    """Top-level Today surface state used by page rendering.

    STRONG_SIGNALS      : Stable queue items surfaced with multi-day support.
    EARLY_SIGNAL        : Signals surfaced, but confidence/history is still thin.
    NO_STRONG_SIGNALS   : Data was checked, but no signals crossed queue thresholds.
    NO_USABLE_DATA      : No usable imported data yet for meaningful queueing.
    """

    STRONG_SIGNALS = "strong_signals"
    EARLY_SIGNAL = "early_signal"
    NO_STRONG_SIGNALS = "no_strong_signals"
    NO_USABLE_DATA = "no_usable_data"


@dataclass(frozen=True)
class TodaySurfaceMeaning:
    state_flags: dict[str, Any]
    status_line: str
    stale_banner: str
    freshness_note: str
    weak_data_mode: bool
    import_summary: dict[str, Any]
    signal_mode: SignalMode = SignalMode.STABLE_SIGNAL
    surface_state: TodaySurfaceState = TodaySurfaceState.STRONG_SIGNALS


@dataclass(frozen=True)
class TodayQueueRenderPlan:
    section_title: str
    weak_data_note: str
    start_note: str
    primary_cards: list[TodayQueueCardViewModel]
    secondary_cards: list[TodayQueueCardViewModel]
    primary_placeholder: str
    secondary_caption: str
    secondary_expanded: bool
    suppressed_debug_rows: list[dict[str, str]]
    auto_resolved_count: int = 0


def compute_data_age_days(*, as_of_date: str, today_value: date) -> int:
    try:
        as_of = date.fromisoformat(str(as_of_date or "")[:10])
    except Exception:
        return 0
    return max(0, (today_value - as_of).days)


def is_weak_data_mode(*, import_summary: dict[str, Any]) -> bool:
    summary = dict(import_summary or {})
    days = int(summary.get("days") or 0)
    trust = dict(summary.get("trust") or {})
    trust_status = str(trust.get("status") or "").strip().lower()
    score = int(trust.get("confidence_score") or 0)

    if 0 < days <= 2:
        return True
    if trust_status in {"partial", "low_confidence", "invalid"}:
        return True
    if score > 0 and score < 75:
        return True
    return False


def _compute_data_state_flags(
    *,
    goal_status: list[dict[str, Any]],
    import_summary: dict[str, Any],
    home_sections: dict[str, list[InsightCardContract]],
) -> dict[str, Any]:
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
    stale_days = int(import_summary.get("data_age_days") or 0)
    has_data = has_goal_data or days > 0

    return {
        "no_data": not has_data,
        "low_data": has_data and days <= 1,
        "partial_data": bool(partial_rows) or (0 < days < 3),
        "low_confidence": bool(low_conf_cards),
        "healthy": has_goal_data and below_goal_count == 0,
        "stale_data": stale_days > 0,
        "stale_days": stale_days,
    }


def _build_status_line(*, state_flags: dict[str, Any], has_queue_items: bool) -> str:
    if bool(state_flags.get("stale_data")):
        stale_days = int(state_flags.get("stale_days") or 0)
        day_word = "day" if stale_days == 1 else "days"
        return f"Status: Latest data is {stale_days} {day_word} old. Queue reflects the most recent available snapshot."
    if bool(state_flags.get("no_data")):
        return "Status: No imported records yet. Import data to start the queue."
    if bool(state_flags.get("low_data")) or bool(state_flags.get("partial_data")) or bool(state_flags.get("low_confidence")):
        return "Early-signal mode: limited history, directional evidence only."
    if not has_queue_items and bool(state_flags.get("healthy")):
        return "Status: No important changes surfaced today."
    return ""


def _build_stale_banner(*, state_flags: dict[str, Any]) -> str:
    if not bool(state_flags.get("stale_data")):
        return ""
    stale_days = int(state_flags.get("stale_days") or 0)
    day_word = "day" if stale_days == 1 else "days"
    return f"Showing the latest available queue from {stale_days} {day_word} ago."


def _build_freshness_note(*, state_flags: dict[str, Any]) -> str:
    stale_days = int(state_flags.get("stale_days") or 0)
    if stale_days > 0:
        day_word = "day" if stale_days == 1 else "days"
        return f"Latest data snapshot: {stale_days} {day_word} old."
    if not bool(state_flags.get("no_data")):
        return "Latest data snapshot: current shift/day."
    return ""


def _classify_surface_state(
    *,
    state_flags: dict[str, Any],
    signal_mode: SignalMode,
    has_queue_items: bool,
) -> TodaySurfaceState:
    if bool(state_flags.get("no_data")):
        return TodaySurfaceState.NO_USABLE_DATA
    if has_queue_items and signal_mode in {SignalMode.EARLY_SIGNAL, SignalMode.LIMITED_DATA}:
        return TodaySurfaceState.EARLY_SIGNAL
    if has_queue_items:
        return TodaySurfaceState.STRONG_SIGNALS
    return TodaySurfaceState.NO_STRONG_SIGNALS


def build_today_surface_meaning(
    *,
    goal_status: list[dict[str, Any]],
    import_summary: dict[str, Any],
    home_sections: dict[str, list[InsightCardContract]],
    has_queue_items: bool,
    as_of_date: str,
    today_value: date,
) -> TodaySurfaceMeaning:
    summary = dict(import_summary or {})
    summary["data_age_days"] = compute_data_age_days(as_of_date=as_of_date, today_value=today_value)

    state_flags = _compute_data_state_flags(
        goal_status=goal_status,
        import_summary=summary,
        home_sections=home_sections,
    )
    signal_mode = classify_signal_mode(goal_status=goal_status, import_summary=summary)

    return TodaySurfaceMeaning(
        state_flags=state_flags,
        status_line=_build_status_line(state_flags=state_flags, has_queue_items=has_queue_items),
        stale_banner=_build_stale_banner(state_flags=state_flags),
        freshness_note=_build_freshness_note(state_flags=state_flags),
        weak_data_mode=is_weak_data_mode(import_summary=summary),
        import_summary=summary,
        signal_mode=signal_mode,
        surface_state=_classify_surface_state(
            state_flags=state_flags,
            signal_mode=signal_mode,
            has_queue_items=has_queue_items,
        ),
    )


def build_today_queue_render_plan(
    *,
    attention: AttentionSummary,
    decision_items: list[DecisionItem] | None = None,
    suppressed_cards: list[InsightCardContract] | None,
    today_value: date,
    is_stale: bool,
    weak_data_mode: bool,
    show_secondary_open: bool,
    snapshot_cards: list[TodayQueueCardViewModel] | None = None,
    last_action_lookup: dict[str, str] | None = None,
    action_state_lookup: dict[str, dict[str, object]] | None = None,
) -> TodayQueueRenderPlan:
    legacy_fallback_enabled = str(os.getenv("DPD_TODAY_ENABLE_LEGACY_RANKING_FALLBACK", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    decision_policy = build_decision_surfacing_policy(list(decision_items or []), primary_cap=8) if decision_items else None
    queue_vm = build_today_queue_view_model(
        attention=attention,
        decision_items=decision_items,
        decision_policy=decision_policy,
        allow_legacy_attention_fallback=legacy_fallback_enabled,
        suppressed_cards=suppressed_cards,
        today=today_value,
        last_action_lookup=last_action_lookup,
        action_state_lookup=action_state_lookup,
    )

    section_title = "Follow-ups Today"

    promoted_secondary = bool(weak_data_mode and not queue_vm.primary_cards and bool(queue_vm.secondary_cards))
    primary_cards_to_render = queue_vm.secondary_cards if promoted_secondary else queue_vm.primary_cards
    secondary_cards_to_render = [] if promoted_secondary else queue_vm.secondary_cards

    # Snapshot fallback: when the regular queue is empty and same-day snapshot
    # cards are available, surface them as the primary set.
    snapshot_active = False
    if not primary_cards_to_render and snapshot_cards:
        primary_cards_to_render = list(snapshot_cards)
        secondary_cards_to_render = []
        snapshot_active = True

    primary_placeholder = ""
    if not primary_cards_to_render:
        if secondary_cards_to_render:
            primary_placeholder = "Open loops that need a manager decision, check-in, or closeout."
        else:
            primary_placeholder = "No urgent performance issues today. Keep momentum by closing open follow-ups, recognizing recent improvement, or checking limited-data items."

    suppressed_debug_rows = [
        {
            "source": row.source,
            "employee": row.employee,
            "process": row.process,
            "label": row.label,
        }
        for row in list(queue_vm.suppressed or [])
    ]

    if snapshot_active:
        weak_data_note = ""
        start_note = "Open loops that need a manager decision, check-in, or closeout."
    elif weak_data_mode:
        weak_data_note = ""
        start_note = "Open loops that need a manager decision, check-in, or closeout."
    elif decision_policy is not None:
        weak_data_note = ""
        start_note = "Open loops that need a manager decision, check-in, or closeout."
    else:
        weak_data_note = ""
        start_note = "Open loops that need a manager decision, check-in, or closeout."

    return TodayQueueRenderPlan(
        section_title=section_title,
        weak_data_note=weak_data_note,
        start_note=start_note,
        primary_cards=primary_cards_to_render,
        secondary_cards=secondary_cards_to_render,
        primary_placeholder=primary_placeholder,
        secondary_caption=("Follow-through and watchlist" if decision_policy is not None else "Other early signals") if secondary_cards_to_render else "",
        secondary_expanded=bool(show_secondary_open),
        suppressed_debug_rows=suppressed_debug_rows,
        auto_resolved_count=int(queue_vm.auto_resolved_count or 0),
    )


# ---------------------------------------------------------------------------
# Queue orientation model
# ---------------------------------------------------------------------------

_DECLINING_FACTOR_KEYS: frozenset[str] = frozenset({"trend_declining", "trend_below_expected"})
_REPEAT_FACTOR_KEYS: frozenset[str] = frozenset({"repeat_1", "repeat_2", "repeat_3_or_more"})
_LIMITED_CONFIDENCE_FACTOR_KEYS: frozenset[str] = frozenset({"confidence_low", "completeness_limited"})


def build_queue_orientation(attention: AttentionSummary) -> TodayQueueOrientationModel:
    """Derive a compact summary model from the ranked attention items.

    Classification criteria:
    - declining: item has factor key ``trend_declining`` or ``trend_below_expected``
    - repeat: item has factor key ``repeat_1``, ``repeat_2``, or ``repeat_3_or_more``
    - limited confidence: item has factor key ``confidence_low`` or ``completeness_limited``
    - distinct_processes: count of unique non-empty process_name values across all items
    """
    items = list(attention.ranked_items or [])
    declining = 0
    repeat = 0
    limited = 0
    processes: set[str] = set()

    for item in items:
        factor_keys = {str(f.key) for f in (item.factors_applied or [])}
        if factor_keys & _DECLINING_FACTOR_KEYS:
            declining += 1
        if factor_keys & _REPEAT_FACTOR_KEYS:
            repeat += 1
        if factor_keys & _LIMITED_CONFIDENCE_FACTOR_KEYS:
            limited += 1
        proc = str(item.process_name or "").strip()
        if proc:
            processes.add(proc)

    return TodayQueueOrientationModel(
        total_shown=len(items),
        declining_count=declining,
        repeat_count=repeat,
        limited_confidence_count=limited,
        distinct_processes=len(processes),
        total_evaluated=int(attention.total_evaluated or 0),
    )
