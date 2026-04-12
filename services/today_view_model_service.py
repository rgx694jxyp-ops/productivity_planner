"""Typed Today view-model builder for render-only page logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from domain.display_signal import DisplaySignal, SignalLabel
from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionSummary
from services.display_signal_factory import build_display_signal_from_attention_item, build_display_signal_from_insight_card
from services.plain_language_service import signal_wording
from services.signal_formatting_service import (
    SignalDisplayMode,
    format_confidence_line,
    format_friendly_date,
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
    employee_id: str
    process_id: str
    line_1: str
    line_2: str
    line_3: str
    line_4: str
    line_5: str
    expanded_lines: list[str]


@dataclass(frozen=True)
class TodayQueueViewModel:
    primary_cards: list[TodayQueueCardViewModel]
    secondary_cards: list[TodayQueueCardViewModel]
    suppressed: list[SuppressedSignalViewModel]


@dataclass(frozen=True)
class _RankedCard:
    card: TodayQueueCardViewModel
    bucket_rank: int
    status_rank: int
    repeat_rank: int
    confidence_rank: int
    severity_rank: int
    recency_rank: int


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


def _is_follow_up_signal(signal: DisplaySignal) -> bool:
    label = str(format_signal_label(signal) or "").strip().lower()
    if label == signal_wording("follow_up_not_completed").lower():
        return True
    flags = dict(signal.flags or {})
    return bool(flags.get("overdue") or flags.get("due_today"))


def _observed_value_text(signal: DisplaySignal) -> str:
    if signal.observed_value is None:
        return ""
    return f"{signal.observed_value:.1f} UPH"


def _comparison_range_text(signal: DisplaySignal) -> str:
    start = signal.comparison_start_date
    end = signal.comparison_end_date
    if start is not None and end is not None:
        if start == end:
            return format_friendly_date(start)
        return f"{format_friendly_date(start)}–{format_friendly_date(end)}"
    return "Recent range"


def _humanize_dates_in_text(text: str) -> str:
    value = str(text or "")

    def _replace_range(match: re.Match[str]) -> str:
        start_text = str(match.group(1) or "")
        end_text = str(match.group(2) or "")
        try:
            start_date = date.fromisoformat(start_text)
            end_date = date.fromisoformat(end_text)
        except Exception:
            return match.group(0)
        if start_date == end_date:
            return format_friendly_date(start_date)
        return f"{format_friendly_date(start_date)}–{format_friendly_date(end_date)}"

    def _replace_single(match: re.Match[str]) -> str:
        date_text = str(match.group(1) or "")
        try:
            parsed = date.fromisoformat(date_text)
        except Exception:
            return match.group(0)
        return format_friendly_date(parsed)

    value = re.sub(r"(\d{4}-\d{2}-\d{2})\s*[-–]\s*(\d{4}-\d{2}-\d{2})", _replace_range, value)
    value = re.sub(r"\b(\d{4}-\d{2}-\d{2})\b", _replace_single, value)
    return value


def _follow_up_due_line(item: Any, signal: DisplaySignal) -> str:
    snapshot = dict(getattr(item, "snapshot", {}) or {})
    due_raw = snapshot.get("follow_up_due_at") or snapshot.get("due_date")
    due_date: date | None = None
    try:
        due_date = date.fromisoformat(str(due_raw or "")[:10])
    except Exception:
        due_date = None

    flags = dict(signal.flags or {})
    if bool(flags.get("overdue")):
        if due_date is not None:
            return f"Due: Overdue since {format_friendly_date(due_date)}"
        return "Due: Overdue"
    if bool(flags.get("due_today")):
        return "Due: Today"
    if due_date is not None:
        return f"Due: {format_friendly_date(due_date)}"
    return "Due: Open"


def _short_follow_up_context(item: Any, signal: DisplaySignal) -> str:
    snapshot = dict(getattr(item, "snapshot", {}) or {})
    repeat_count = int(snapshot.get("repeat_count") or 0)
    if repeat_count >= 2:
        return f"Seen {repeat_count} times this week"

    return ""


def _bucket_rank(item: Any, signal: DisplaySignal) -> int:
    mode = get_signal_display_mode(signal)
    if mode in {SignalDisplayMode.LOW_DATA, SignalDisplayMode.CURRENT_STATE} or signal.confidence.value == "low":
        return 2

    flags = dict(signal.flags or {})
    if bool(flags.get("overdue")):
        return 0

    snapshot = dict(getattr(item, "snapshot", {}) or {})
    repeat_count = int(snapshot.get("repeat_count") or 0)
    failed_cycles = int(snapshot.get("failed_cycles") or 0)
    if repeat_count >= 2 and failed_cycles >= 1:
        return 0
    if repeat_count >= 2 and _is_follow_up_signal(signal):
        return 0

    label = str(format_signal_label(signal) or "").strip().lower()
    bucket_b = {
        signal_wording("lower_than_recent_pace").lower(),
        signal_wording("below_expected_pace").lower(),
        signal_wording("inconsistent_performance").lower(),
    }
    if label in bucket_b:
        return 1
    return 1


def _status_rank(signal: DisplaySignal) -> int:
    flags = dict(signal.flags or {})
    if bool(flags.get("overdue")):
        return 0
    if bool(flags.get("due_today")):
        return 1
    return 2


def _repeat_rank(item: Any) -> int:
    snapshot = dict(getattr(item, "snapshot", {}) or {})
    repeat_count = int(snapshot.get("repeat_count") or 0)
    return -repeat_count


def _confidence_rank(signal: DisplaySignal) -> int:
    mapping = {"high": 0, "medium": 1, "low": 2}
    return mapping.get(signal.confidence.value, 2)


def _severity_rank(item: Any) -> int:
    score = int(getattr(item, "attention_score", 0) or 0)
    return -score


def _recency_rank(signal: DisplaySignal) -> int:
    return -int(signal.observed_date.toordinal())


def _sort_ranked_cards(rows: list[_RankedCard]) -> list[_RankedCard]:
    return sorted(
        rows,
        key=lambda row: (
            row.bucket_rank,
            row.status_rank,
            row.repeat_rank,
            row.confidence_rank,
            row.severity_rank,
            row.recency_rank,
        ),
    )


def _dedupe_expanded(*, primary: str, lines: list[str], max_lines: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    primary_key = str(primary or "").strip().lower()
    banned_parts = {"score", "rank", "factor", "n/a"}
    for line in lines:
        text = " ".join(str(line or "").strip().split())
        text = _humanize_dates_in_text(text)
        if not text:
            continue
        key = text.lower()
        if key == primary_key or key in seen:
            continue
        if any(part in key for part in banned_parts):
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_lines:
            break
    return out


def _card_from_pair(item: Any, signal: DisplaySignal) -> TodayQueueCardViewModel:
    employee_name, process_name = _attention_employee_and_process(item, signal)
    mode = get_signal_display_mode(signal)
    low_data_state = mode == SignalDisplayMode.LOW_DATA
    current_state_mode = mode == SignalDisplayMode.CURRENT_STATE
    line_1 = f"{employee_name} · {process_name}"
    line_2 = _attention_primary_signal(item, signal)
    line_5 = format_confidence_line(signal)

    if low_data_state:
        collapsed = format_low_data_collapsed_lines(signal)
        line_2 = collapsed[0] if collapsed else signal_wording("not_enough_history_yet")
        line_3 = ""
        line_4 = ""
        expanded = format_low_data_expanded_lines(signal)
        return TodayQueueCardViewModel(
            employee_id=str(getattr(item, "employee_id", "") or ""),
            process_id=str(getattr(item, "process_name", "") or ""),
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=line_4,
            line_5=line_5,
            expanded_lines=_dedupe_expanded(primary=line_2, lines=expanded, max_lines=3),
        )

    if current_state_mode:
        line_2 = format_signal_label(signal)
        line_3 = format_observed_line(signal)
        line_4 = format_confidence_line(signal)
        return TodayQueueCardViewModel(
            employee_id=str(getattr(item, "employee_id", "") or ""),
            process_id=str(getattr(item, "process_name", "") or ""),
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=line_4,
            line_5="",
            expanded_lines=[],
        )

    if _is_follow_up_signal(signal):
        line_3 = _follow_up_due_line(item, signal)
        line_4 = _short_follow_up_context(item, signal)
        expanded_candidates = _attention_context_lines(item, signal, max_lines=4)
        if line_4:
            expanded_candidates = [line for line in expanded_candidates if str(line).strip().lower() != line_4.lower()]
        expanded = _dedupe_expanded(primary=line_2, lines=expanded_candidates, max_lines=3)
    else:
        observed_value = _observed_value_text(signal)
        line_3 = f"Observed: {format_friendly_date(signal.observed_date)}"
        if observed_value:
            line_3 += f" ({observed_value})"
        baseline = f"{signal.comparison_value:.1f} UPH" if signal.comparison_value is not None else ""
        line_4 = f"Compared to: {_comparison_range_text(signal)} avg"
        if baseline:
            line_4 += f" ({baseline})"
        expanded = _dedupe_expanded(
            primary=line_2,
            lines=_attention_context_lines(item, signal, max_lines=4),
            max_lines=3,
        )

    return TodayQueueCardViewModel(
        employee_id=str(getattr(item, "employee_id", "") or ""),
        process_id=str(getattr(item, "process_name", "") or ""),
        line_1=line_1,
        line_2=line_2,
        line_3=line_3,
        line_4=line_4,
        line_5=line_5,
        expanded_lines=expanded,
    )


def _card_from_insight_card(card: InsightCardContract, signal: DisplaySignal) -> TodayQueueCardViewModel:
    mode = get_signal_display_mode(signal)
    low_data_state = mode == SignalDisplayMode.LOW_DATA
    current_state_mode = mode == SignalDisplayMode.CURRENT_STATE
    employee_name = str(signal.employee_name)
    process_name = str(signal.process)
    line_1 = f"{employee_name} · {process_name}"
    line_2 = _attention_primary_signal(card, signal)
    line_5 = format_confidence_line(signal)

    if low_data_state:
        collapsed = format_low_data_collapsed_lines(signal)
        line_2 = collapsed[0] if collapsed else signal_wording("not_enough_history_yet")
        expanded = format_low_data_expanded_lines(signal)
        return TodayQueueCardViewModel(
            employee_id=str(card.drill_down.entity_id or ""),
            process_id=process_name,
            line_1=line_1,
            line_2=line_2,
            line_3="",
            line_4="",
            line_5=line_5,
            expanded_lines=_dedupe_expanded(primary=line_2, lines=expanded, max_lines=3),
        )

    if current_state_mode:
        line_2 = format_signal_label(signal)
        line_3 = format_observed_line(signal)
        line_4 = format_confidence_line(signal)
        return TodayQueueCardViewModel(
            employee_id=str(card.drill_down.entity_id or ""),
            process_id=process_name,
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=line_4,
            line_5="",
            expanded_lines=[],
        )

    if _is_follow_up_signal(signal):
        line_3 = _follow_up_due_line(card, signal)
        line_4 = _short_follow_up_context(card, signal)
        expanded = _dedupe_expanded(primary=line_2, lines=[], max_lines=3)
    else:
        observed_value = _observed_value_text(signal)
        line_3 = f"Observed: {format_friendly_date(signal.observed_date)}"
        if observed_value:
            line_3 += f" ({observed_value})"
        baseline = f"{signal.comparison_value:.1f} UPH" if signal.comparison_value is not None else ""
        line_4 = f"Compared to: {_comparison_range_text(signal)} avg"
        if baseline:
            line_4 += f" ({baseline})"
        expanded = _dedupe_expanded(primary=line_2, lines=[], max_lines=3)

    return TodayQueueCardViewModel(
        employee_id=str(card.drill_down.entity_id or ""),
        process_id=process_name,
        line_1=line_1,
        line_2=line_2,
        line_3=line_3,
        line_4=line_4,
        line_5=line_5,
        expanded_lines=expanded,
    )


def build_today_queue_view_model(
    attention: AttentionSummary,
    *,
    suppressed_cards: list[InsightCardContract] | None = None,
    today: date,
) -> TodayQueueViewModel:
    _ = today
    primary_ranked: list[_RankedCard] = []
    secondary_ranked: list[_RankedCard] = []
    suppressed: list[SuppressedSignalViewModel] = []

    for item in list(attention.ranked_items or []):
        signal = build_display_signal_from_attention_item(item=item, today=date.today())
        eligible_primary = is_signal_display_eligible(
            signal,
            allow_low_data_case=False,
            min_confidence_for_full_or_partial="low",
        )
        eligible_low_data = is_signal_display_eligible(
            signal,
            allow_low_data_case=True,
            min_confidence_for_full_or_partial="low",
        )

        if not eligible_low_data:
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
        ranked = _RankedCard(
            card=card_vm,
            bucket_rank=_bucket_rank(item, signal),
            status_rank=_status_rank(signal),
            repeat_rank=_repeat_rank(item),
            confidence_rank=_confidence_rank(signal),
            severity_rank=_severity_rank(item),
            recency_rank=_recency_rank(signal),
        )
        mode = get_signal_display_mode(signal)
        if (not eligible_primary) or mode == SignalDisplayMode.CURRENT_STATE or signal.confidence.value == "low" or str(getattr(item, "attention_tier", "")) == "low":
            secondary_ranked.append(ranked)
        else:
            primary_ranked.append(ranked)

    for card in [c for c in list(suppressed_cards or []) if isinstance(c, InsightCardContract)]:
        signal = build_display_signal_from_insight_card(card=card, today=date.today())
        if not is_signal_display_eligible(signal, allow_low_data_case=True):
            continue
        card_vm = _card_from_insight_card(card, signal)
        secondary_ranked.append(
            _RankedCard(
                card=card_vm,
                bucket_rank=2,
                status_rank=_status_rank(signal),
                repeat_rank=0,
                confidence_rank=_confidence_rank(signal),
                severity_rank=0,
                recency_rank=_recency_rank(signal),
            )
        )

    primary_cards = [row.card for row in _sort_ranked_cards(primary_ranked)]
    secondary_cards = [row.card for row in _sort_ranked_cards(secondary_ranked)]

    return TodayQueueViewModel(
        primary_cards=primary_cards,
        secondary_cards=secondary_cards,
        suppressed=suppressed,
    )
