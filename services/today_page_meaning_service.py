"""Today page meaning service.

Owns page-level product meaning decisions so UI modules can render precomputed props.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionSummary
from services.today_view_model_service import TodayQueueCardViewModel, build_today_queue_view_model


@dataclass(frozen=True)
class TodaySurfaceMeaning:
    state_flags: dict[str, Any]
    status_line: str
    stale_banner: str
    freshness_note: str
    weak_data_mode: bool
    import_summary: dict[str, Any]


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

    return TodaySurfaceMeaning(
        state_flags=state_flags,
        status_line=_build_status_line(state_flags=state_flags, has_queue_items=has_queue_items),
        stale_banner=_build_stale_banner(state_flags=state_flags),
        freshness_note=_build_freshness_note(state_flags=state_flags),
        weak_data_mode=is_weak_data_mode(import_summary=summary),
        import_summary=summary,
    )


def build_today_queue_render_plan(
    *,
    attention: AttentionSummary,
    suppressed_cards: list[InsightCardContract] | None,
    today_value: date,
    is_stale: bool,
    weak_data_mode: bool,
    show_secondary_open: bool,
) -> TodayQueueRenderPlan:
    queue_vm = build_today_queue_view_model(
        attention=attention,
        suppressed_cards=suppressed_cards,
        today=today_value,
    )

    section_title = str(queue_vm.main_section_title or "")
    if is_stale:
        section_title = section_title.replace("today", "latest snapshot").replace("Today", "Latest snapshot")

    promoted_secondary = bool(weak_data_mode and not queue_vm.primary_cards and bool(queue_vm.secondary_cards))
    primary_cards_to_render = queue_vm.secondary_cards if promoted_secondary else queue_vm.primary_cards
    secondary_cards_to_render = [] if promoted_secondary else queue_vm.secondary_cards

    primary_placeholder = ""
    if not primary_cards_to_render:
        if secondary_cards_to_render:
            primary_placeholder = "Early signals are shown below. Confidence is limited until more history is available."
        else:
            primary_placeholder = "No items need immediate attention right now."

    suppressed_debug_rows = [
        {
            "source": row.source,
            "employee": row.employee,
            "process": row.process,
            "label": row.label,
        }
        for row in list(queue_vm.suppressed or [])
    ]

    return TodayQueueRenderPlan(
        section_title=section_title,
        weak_data_note="Early signals are shown below. Confidence is limited until more history is available." if weak_data_mode else "",
        start_note="Signals are ranked by current evidence strength and recency.",
        primary_cards=primary_cards_to_render,
        secondary_cards=secondary_cards_to_render,
        primary_placeholder=primary_placeholder,
        secondary_caption="Early signals based on limited data" if secondary_cards_to_render else "",
        secondary_expanded=bool(show_secondary_open),
        suppressed_debug_rows=suppressed_debug_rows,
    )
