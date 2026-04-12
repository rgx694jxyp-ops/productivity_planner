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
    format_comparison_line,
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
    state: str
    line_1: str
    line_2: str
    line_3: str
    line_4: str
    line_5: str
    expanded_lines: list[str]


@dataclass(frozen=True)
class TodayQueueViewModel:
    main_section_title: str
    primary_cards: list[TodayQueueCardViewModel]
    secondary_cards: list[TodayQueueCardViewModel]
    suppressed: list[SuppressedSignalViewModel]


@dataclass(frozen=True)
class TodayValueBlockViewModel:
    title: str
    headline: str
    detail: str


@dataclass(frozen=True)
class TodayValueStripViewModel:
    cards: list[TodayValueBlockViewModel]


@dataclass(frozen=True)
class _RankedCard:
    card: TodayQueueCardViewModel
    bucket_rank: int
    status_rank: int
    repeat_rank: int
    confidence_rank: int
    severity_rank: int
    recency_rank: int


_ATTENTION_STATES = {"EARLY_TREND", "STABLE_TREND", "PATTERN"}
_REVIEWABLE_STATES = {"CURRENT", *list(_ATTENTION_STATES)}


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _row_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _format_uph_value(value: float | None) -> str:
    if value is None:
        return ""
    rounded = round(float(value), 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}"


def _build_top_performance_block(goal_status: list[dict[str, Any]]) -> TodayValueBlockViewModel | None:
    ranked_rows = []
    for row in goal_status or []:
        employee_name = _row_text(row, "Employee", "Employee Name", "employee_name", "EmployeeID")
        average_uph = _safe_float(row.get("Average UPH"))
        if not employee_name or average_uph is None or average_uph <= 0:
            continue
        ranked_rows.append((average_uph, row))

    if not ranked_rows:
        return None

    _top_uph, top_row = max(ranked_rows, key=lambda pair: pair[0])
    employee_name = _row_text(top_row, "Employee", "Employee Name", "employee_name", "EmployeeID")
    process_name = _row_text(top_row, "Department", "process_name") or "Unassigned"
    average_text = _format_uph_value(_safe_float(top_row.get("Average UPH")))
    target_text = _format_uph_value(_safe_float(top_row.get("Target UPH")))
    detail = process_name if not target_text else f"{process_name} · Target {target_text} UPH"
    return TodayValueBlockViewModel(
        title="Top performance today",
        headline=f"{employee_name} at {average_text} UPH",
        detail=detail,
    )


def _build_biggest_change_block(goal_status: list[dict[str, Any]]) -> TodayValueBlockViewModel | None:
    ranked_rows = []
    for row in goal_status or []:
        employee_name = _row_text(row, "Employee", "Employee Name", "employee_name", "EmployeeID")
        change_pct = _safe_float(row.get("change_pct"))
        confidence_label = str(row.get("confidence_label") or "").strip().lower()
        trend = str(row.get("trend") or "").strip().lower()
        if not employee_name or change_pct is None:
            continue
        if abs(change_pct) < 1.0:
            continue
        if confidence_label == "low" or trend in {"", "insufficient_data"}:
            continue
        ranked_rows.append((abs(change_pct), row))

    if not ranked_rows:
        return None

    _largest_change, top_row = max(ranked_rows, key=lambda pair: pair[0])
    employee_name = _row_text(top_row, "Employee", "Employee Name", "employee_name", "EmployeeID")
    process_name = _row_text(top_row, "Department", "process_name") or "Unassigned"
    change_pct = _safe_float(top_row.get("change_pct")) or 0.0
    direction = "up" if change_pct > 0 else "down"
    observed_text = _format_uph_value(_safe_float(top_row.get("Average UPH")))
    return TodayValueBlockViewModel(
        title="Biggest change today",
        headline=f"{employee_name} {direction} {abs(change_pct):.0f}%",
        detail=f"{process_name} · {observed_text} UPH today",
    )


def _build_new_employee_block(goal_status: list[dict[str, Any]]) -> TodayValueBlockViewModel | None:
    candidates: list[tuple[int, float, dict[str, Any]]] = []
    for row in goal_status or []:
        employee_name = _row_text(row, "Employee", "Employee Name", "employee_name", "EmployeeID")
        record_count = _safe_int(row.get("Record Count"))
        average_uph = _safe_float(row.get("Average UPH")) or 0.0
        if not employee_name or record_count is None or record_count <= 0 or record_count > 2:
            continue
        candidates.append((record_count, -average_uph, row))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1], _row_text(item[2], "Employee", "Employee Name", "employee_name", "EmployeeID")))
    selected = candidates[0][2]
    employee_name = _row_text(selected, "Employee", "Employee Name", "employee_name", "EmployeeID")
    process_name = _row_text(selected, "Department", "process_name") or "Unassigned"
    if len(candidates) == 1:
        detail = f"{candidates[0][0]} recent record(s), so comparisons are still building"
        headline = f"{employee_name} · {process_name}"
    else:
        detail = f"{len(candidates)} people only have 1-2 recent records"
        headline = f"{employee_name} +{len(candidates) - 1} newer employee(s)"
    return TodayValueBlockViewModel(
        title="New employee flag",
        headline=headline,
        detail=detail,
    )


def _build_data_health_block(import_summary: dict[str, Any] | None) -> TodayValueBlockViewModel | None:
    summary = dict(import_summary or {})
    if not summary:
        return None

    trust = dict(summary.get("trust") or {})
    status = str(trust.get("status") or "").strip().lower()
    score = _safe_int(trust.get("confidence_score")) or 0
    days = _safe_int(summary.get("days")) or 0
    emp_count = _safe_int(summary.get("emp_count")) or 0
    valid_rows = _safe_int(summary.get("valid_rows"))
    rows_processed = _safe_int(summary.get("rows_processed"))
    warning_rows = _safe_int(summary.get("warning_rows")) or 0

    if status == "valid" and score >= 80:
        headline = "Data looks good"
    elif status in {"partial", "low_confidence"} or warning_rows > 0 or score >= 50:
        headline = "Some rows were flagged"
    else:
        headline = "Review import details"

    if valid_rows is not None and rows_processed is not None and rows_processed > 0:
        detail = f"{valid_rows}/{rows_processed} rows usable"
    elif days > 0 or emp_count > 0:
        detail = f"{days} day(s) across {emp_count} employees"
    else:
        detail = "Latest import summary is available"

    return TodayValueBlockViewModel(
        title="Data health",
        headline=headline,
        detail=detail,
    )


def build_today_value_strip_view_model(
    *,
    goal_status: list[dict[str, Any]],
    import_summary: dict[str, Any] | None,
) -> TodayValueStripViewModel:
    cards = [
        _build_top_performance_block(goal_status),
        _build_biggest_change_block(goal_status),
        _build_new_employee_block(goal_status),
        _build_data_health_block(import_summary),
    ]
    return TodayValueStripViewModel(cards=[card for card in cards if card is not None])


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
    primary_label = str(getattr(signal, "primary_label", "") or "").strip()
    if primary_label:
        return primary_label

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
    for text in list(getattr(signal, "supporting_text", []) or []):
        clean = str(text or "").strip()
        if clean:
            lines.append(clean)
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


def _normalize_display_key(text: str) -> str:
    value = _humanize_dates_in_text(str(text or "").strip()).lower()
    value = re.sub(r"\s*[–-]\s*", "-", value)
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


def _confidence_level_value(signal: DisplaySignal) -> str:
    value = getattr(signal.confidence_level, "value", signal.confidence_level)
    return str(value or getattr(signal.confidence, "value", "low")).strip().lower()


def _low_data_recent_count(source: Any, signal: DisplaySignal) -> int | None:
    for key in ("recent_record_count", "usable_points", "sample_size", "included_rows"):
        value = (signal.flags or {}).get(key)
        try:
            if value is not None:
                return max(0, int(value))
        except Exception:
            continue

    snapshot = dict(getattr(source, "snapshot", {}) or {})
    for key in ("sample_size", "included_rows", "recent_record_count"):
        try:
            value = snapshot.get(key)
            if value is not None:
                return max(0, int(value))
        except Exception:
            continue

    confidence = getattr(source, "confidence", None)
    try:
        sample_size = getattr(confidence, "sample_size", None)
        if sample_size is not None:
            return max(0, int(sample_size))
    except Exception:
        return None
    return None


def _bucket_rank(item: Any, signal: DisplaySignal) -> int:
    mode = get_signal_display_mode(signal)
    if mode in {SignalDisplayMode.LOW_DATA, SignalDisplayMode.CURRENT_STATE} or _confidence_level_value(signal) == "low":
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
    return mapping.get(_confidence_level_value(signal), 2)


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


def _section_title(primary_cards: list[TodayQueueCardViewModel], secondary_cards: list[TodayQueueCardViewModel]) -> str:
    all_cards = [*list(primary_cards or []), *list(secondary_cards or [])]
    if any(str(card.state or "") in _ATTENTION_STATES for card in all_cards):
        return "What needs attention today"
    if any(str(card.state or "") == "CURRENT" for card in primary_cards):
        return "What you can review today"
    if any(str(card.state or "") == "CURRENT" for card in all_cards):
        return "What you can review today"
    return "What needs attention today"


def _dedupe_expanded(*, primary: str, lines: list[str], excluded: list[str] | None = None, max_lines: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    primary_key = _normalize_display_key(primary)
    excluded_keys = {
        _normalize_display_key(str(value or ""))
        for value in list(excluded or [])
        if str(value or "").strip()
    }
    banned_parts = {"score", "rank", "factor", "n/a"}
    for line in lines:
        text = " ".join(str(line or "").strip().split())
        text = _humanize_dates_in_text(text)
        if not text:
            continue
        key = _normalize_display_key(text)
        if key == primary_key or key in excluded_keys or key in seen:
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
        expanded = format_low_data_expanded_lines(signal, recent_record_count=_low_data_recent_count(item, signal))
        return TodayQueueCardViewModel(
            employee_id=str(getattr(item, "employee_id", "") or ""),
            process_id=str(getattr(item, "process_name", "") or ""),
            state=str(signal.state.value),
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
            state=str(signal.state.value),
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
        expanded = _dedupe_expanded(primary=line_2, lines=expanded_candidates, excluded=[line_3, line_4], max_lines=3)
    else:
        line_3 = format_observed_line(signal)
        line_4 = format_comparison_line(signal)
        expanded = _dedupe_expanded(
            primary=line_2,
            lines=_attention_context_lines(item, signal, max_lines=4),
            excluded=[line_3, line_4],
            max_lines=3,
        )

    return TodayQueueCardViewModel(
        employee_id=str(getattr(item, "employee_id", "") or ""),
        process_id=str(getattr(item, "process_name", "") or ""),
        state=str(signal.state.value),
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
        expanded = format_low_data_expanded_lines(signal, recent_record_count=_low_data_recent_count(card, signal))
        return TodayQueueCardViewModel(
            employee_id=str(card.drill_down.entity_id or ""),
            process_id=process_name,
            state=str(signal.state.value),
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
            state=str(signal.state.value),
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
        expanded = _dedupe_expanded(primary=line_2, lines=[], excluded=[line_3, line_4], max_lines=3)
    else:
        line_3 = format_observed_line(signal)
        line_4 = format_comparison_line(signal)
        expanded = _dedupe_expanded(primary=line_2, lines=[], excluded=[line_3, line_4], max_lines=3)

    return TodayQueueCardViewModel(
        employee_id=str(card.drill_down.entity_id or ""),
        process_id=process_name,
        state=str(signal.state.value),
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
    primary_ranked: list[_RankedCard] = []
    secondary_ranked: list[_RankedCard] = []
    suppressed: list[SuppressedSignalViewModel] = []

    for item in list(attention.ranked_items or []):
        signal = build_display_signal_from_attention_item(item=item, today=today)
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
        if (not eligible_primary) or mode == SignalDisplayMode.CURRENT_STATE or _confidence_level_value(signal) == "low" or str(getattr(item, "attention_tier", "")) == "low":
            secondary_ranked.append(ranked)
        else:
            primary_ranked.append(ranked)

    for card in [c for c in list(suppressed_cards or []) if isinstance(c, InsightCardContract)]:
        signal = build_display_signal_from_insight_card(card=card, today=today)
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

    if not primary_cards:
        promoted_current = [card for card in secondary_cards if str(card.state or "") == "CURRENT"]
        if promoted_current:
            primary_cards = promoted_current
            secondary_cards = [card for card in secondary_cards if str(card.state or "") != "CURRENT"]

    return TodayQueueViewModel(
        main_section_title=_section_title(primary_cards, secondary_cards),
        primary_cards=primary_cards,
        secondary_cards=secondary_cards,
        suppressed=suppressed,
    )
