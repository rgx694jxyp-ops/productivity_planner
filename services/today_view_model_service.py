"""Typed Today view-model builder for render-only page logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from domain.display_signal import DisplaySignal, SignalLabel
from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionSummary
from services.display_signal_factory import build_display_signal_from_attention_item, build_display_signal_from_insight_card
from services.plain_language_service import signal_wording
from services.signal_formatting_service import (
    SignalDisplayMode,
    format_confidence_line,
    format_low_data_collapsed_lines,
    format_low_data_expanded_lines,
    format_observed_line,
    format_signal_label,
    get_signal_display_mode,
    is_signal_display_eligible,
)


@dataclass(frozen=True)
class SuppressedSignalViewModel:
    source: str
    employee: str
    process: str
    label: str


@dataclass(frozen=True)
class TodayQueueCardViewModel:
    employee_name: str
    process_name: str
    employee_id: str
    process_id: str
    primary_signal: str
    context_lines: list[str]
    confidence_line: str
    low_data_collapsed_lines: list[str]
    low_data_expanded_lines: list[str]


@dataclass(frozen=True)
class TodayQueueViewModel:
    primary_cards: list[TodayQueueCardViewModel]
    secondary_cards: list[TodayQueueCardViewModel]
    suppressed: list[SuppressedSignalViewModel]


def _attention_employee_and_process(item: Any, signal: DisplaySignal) -> tuple[str, str]:
    snapshot = dict(getattr(item, "snapshot", {}) or {})
    employee_name = (
        str(snapshot.get("Employee") or snapshot.get("Employee Name") or snapshot.get("employee_name") or "").strip()
        or str(signal.employee_name or "").strip()
        or str(getattr(item, "employee_id", "") or "").strip()
    )
    process_name = (
        str(snapshot.get("process_name") or snapshot.get("Department") or "").strip()
        or str(signal.process or "").strip()
        or str(getattr(item, "process_name", "") or "").strip()
        or "Unassigned"
    )
    return employee_name, process_name


def _attention_primary_signal(item: Any, signal: DisplaySignal) -> str:
    factor_keys = {str(f.key or "") for f in list(getattr(item, "factors_applied", []) or [])}
    if factor_keys.intersection({"overdue_followup", "due_today_followup", "open_exception"}):
        return signal_wording("follow_up_not_completed")
    if factor_keys.intersection({"repeat_1", "repeat_2", "repeat_3_or_more"}):
        return "Seen multiple times"
    if factor_keys.intersection({"trend_declining", "trend_below_expected", "trend_inconsistent"}):
        return signal_wording("lower_than_recent_pace")

    label = format_signal_label(signal)
    if str(label).strip().lower() in {
        "follow-up overdue",
        "follow-up due today",
        "unresolved issue",
        signal_wording("follow_up_not_completed").lower(),
    }:
        return signal_wording("follow_up_not_completed")
    if str(label).strip().lower() == "repeated pattern":
        return "Seen multiple times"
    return str(label or signal_wording("lower_than_recent_pace"))


def _attention_context_lines(item: Any, signal: DisplaySignal, max_lines: int = 2) -> list[str]:
    lines: list[str] = []
    observed = format_observed_line(signal)
    if observed:
        lines.append(observed)

    factor_keys = {str(f.key or "") for f in list(getattr(item, "factors_applied", []) or [])}
    if factor_keys.intersection({"overdue_followup", "due_today_followup", "open_exception"}):
        lines.append(signal_wording("follow_up_not_completed"))
    if factor_keys.intersection({"repeat_1", "repeat_2", "repeat_3_or_more"}):
        lines.append("Seen multiple times")

    if not lines:
        reasons = [str(reason or "").strip() for reason in list(getattr(item, "attention_reasons", []) or [])]
        reasons = [reason for reason in reasons if reason]
        if reasons:
            lines.append(reasons[0])

    unique: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = str(line).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(str(line).strip())
        if len(unique) >= max_lines:
            break
    return unique


def _card_from_pair(item: Any, signal: DisplaySignal) -> TodayQueueCardViewModel:
    employee_name, process_name = _attention_employee_and_process(item, signal)
    mode = get_signal_display_mode(signal)
    low_data_state = mode in {SignalDisplayMode.LOW_DATA, SignalDisplayMode.PARTIAL}

    if low_data_state:
        return TodayQueueCardViewModel(
            employee_name=employee_name,
            process_name=process_name,
            employee_id=str(getattr(item, "employee_id", "") or ""),
            process_id=str(getattr(item, "process_name", "") or ""),
            primary_signal="",
            context_lines=[],
            confidence_line=format_confidence_line(signal),
            low_data_collapsed_lines=format_low_data_collapsed_lines(signal),
            low_data_expanded_lines=format_low_data_expanded_lines(signal),
        )

    return TodayQueueCardViewModel(
        employee_name=employee_name,
        process_name=process_name,
        employee_id=str(getattr(item, "employee_id", "") or ""),
        process_id=str(getattr(item, "process_name", "") or ""),
        primary_signal=_attention_primary_signal(item, signal),
        context_lines=_attention_context_lines(item, signal, max_lines=2),
        confidence_line=format_confidence_line(signal),
        low_data_collapsed_lines=[],
        low_data_expanded_lines=[],
    )


def _card_from_insight_card(card: InsightCardContract, signal: DisplaySignal) -> TodayQueueCardViewModel:
    mode = get_signal_display_mode(signal)
    low_data_state = mode in {SignalDisplayMode.LOW_DATA, SignalDisplayMode.PARTIAL}
    employee_name = str(signal.employee_name)
    process_name = str(signal.process)

    if low_data_state:
        return TodayQueueCardViewModel(
            employee_name=employee_name,
            process_name=process_name,
            employee_id=str(card.drill_down.entity_id or ""),
            process_id=process_name,
            primary_signal="",
            context_lines=[],
            confidence_line=format_confidence_line(signal),
            low_data_collapsed_lines=format_low_data_collapsed_lines(signal),
            low_data_expanded_lines=format_low_data_expanded_lines(signal),
        )

    context_lines: list[str] = []
    observed = format_observed_line(signal)
    if observed:
        context_lines.append(observed)

    return TodayQueueCardViewModel(
        employee_name=employee_name,
        process_name=process_name,
        employee_id=str(card.drill_down.entity_id or ""),
        process_id=process_name,
        primary_signal=_attention_primary_signal(card, signal),
        context_lines=context_lines[:1],
        confidence_line=format_confidence_line(signal),
        low_data_collapsed_lines=[],
        low_data_expanded_lines=[],
    )


def build_today_queue_view_model(
    *,
    attention: AttentionSummary,
    suppressed_cards: list[InsightCardContract] | None = None,
    today: date,
) -> TodayQueueViewModel:
    _ = today
    primary_cards: list[TodayQueueCardViewModel] = []
    secondary_cards: list[TodayQueueCardViewModel] = []
    suppressed: list[SuppressedSignalViewModel] = []

    for item in list(attention.ranked_items or []):
        signal = build_display_signal_from_attention_item(item=item, today=date.today())
        if not is_signal_display_eligible(signal, allow_low_data_case=False, min_confidence_for_full_or_partial="low"):
            suppressed.append(
                SuppressedSignalViewModel(
                    source="attention",
                    employee=str(signal.employee_name),
                    process=str(signal.process),
                    label=str(format_signal_label(signal)),
                )
            )
            continue

        card_vm = _card_from_pair(item, signal)
        if signal.confidence.value == "low" or str(getattr(item, "attention_tier", "")) == "low":
            secondary_cards.append(card_vm)
        else:
            primary_cards.append(card_vm)

    for card in [c for c in list(suppressed_cards or []) if isinstance(c, InsightCardContract)]:
        signal = build_display_signal_from_insight_card(card=card, today=date.today())
        if not is_signal_display_eligible(signal, allow_low_data_case=True):
            continue
        secondary_cards.append(_card_from_insight_card(card, signal))

    return TodayQueueViewModel(
        primary_cards=primary_cards,
        secondary_cards=secondary_cards,
        suppressed=suppressed,
    )
