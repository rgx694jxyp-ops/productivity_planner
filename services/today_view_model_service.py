"""Typed Today view-model builder for render-only page logic."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from domain.display_signal import DisplaySignal, SignalLabel
from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionSummary
from services.decision_engine_service import DecisionItem
from services.decision_surfacing_policy_service import DecisionSurfacingPolicy
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
    is_display_signal_eligible,
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
    normalized_action_state: str = ""
    normalized_action_state_detail: str = ""
    freshness_line: str = ""
    collapsed_hint: str = ""
    collapsed_evidence: str = ""
    collapsed_issue: str = ""
    signal_key: str = ""
    repeat_count: int = 0
    repeat_window_label: str = ""
    # Last manager action date label, e.g. "Last action: 5 days ago".
    # Derived from last_event_at on the open action (falls back to created_at).
    # Empty string when no action data is available for this employee.
    last_action_date_label: str = ""


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
class TodayWeeklySummaryItemViewModel:
    headline: str


@dataclass(frozen=True)
class TodayWeeklySummaryViewModel:
    items: list[TodayWeeklySummaryItemViewModel]


@dataclass(frozen=True)
class TodayReturnTriggerViewModel:
    headline: str
    messages: list[str]
    comparison_basis: str
    show_cue: bool = False
    cue_label: str = ""


@dataclass(frozen=True)
class _RankedCard:
    card: TodayQueueCardViewModel
    bucket_rank: int
    status_rank: int
    repeat_rank: int
    confidence_rank: int
    attention_priority_rank: int
    recency_rank: int
    tie_breaker: tuple[str, str, str, str]


_ATTENTION_STATES = {"EARLY_TREND", "STABLE_TREND", "PATTERN"}
_REVIEWABLE_STATES = {"CURRENT", *list(_ATTENTION_STATES)}


def _days_ago_label(iso_date: str, today: date) -> str:
    """Return a compact relative-date string, e.g. 'Last action: 5 days ago'.

    Returns an empty string when the date is unparseable or in the future.
    Uses 'today' for same-day actions so the label is unambiguous.
    """
    if not str(iso_date or "").strip():
        return ""
    try:
        action_date = date.fromisoformat(str(iso_date).strip()[:10])
        delta = (today - action_date).days
        if delta < 0:
            return ""
        if delta == 0:
            return "Last action: today"
        if delta == 1:
            return "Last action: 1 day ago"
        return f"Last action: {delta} days ago"
    except Exception:
        return ""


def _iso_prefix(value: Any) -> str:
    return str(value or "").strip()[:10]


def _count_with_noun(count: int, singular: str, plural: str | None = None) -> str:
    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {noun}"


def build_today_return_trigger(
    *,
    queue_items: list[dict[str, Any]],
    today: date,
    previous_queue_items: list[dict[str, Any]] | None = None,
    previous_as_of_date: str = "",
) -> TodayReturnTriggerViewModel | None:
    """Build a compact 'what changed' trigger for the top of Today.

    The trigger stays factual and only uses current queue data plus a prior
    precomputed queue snapshot when available.
    """
    today_iso = today.isoformat()
    current_items = [item for item in list(queue_items or []) if isinstance(item, dict)]

    new_today_count = sum(1 for item in current_items if _iso_prefix(item.get("created_at")) == today_iso)
    due_today_count = sum(1 for item in current_items if str(item.get("_queue_status") or "") == "due_today")

    prev_items = [item for item in list(previous_queue_items or []) if isinstance(item, dict)]
    if _iso_prefix(previous_as_of_date) == "":
        if new_today_count <= 0 and due_today_count <= 0:
            return None

        messages: list[str] = []
        if new_today_count > 0:
            messages.append(f"{_count_with_noun(new_today_count, 'new item')} entered today's queue")
        if due_today_count > 0:
            verb = "is" if due_today_count == 1 else "are"
            messages.append(f"{_count_with_noun(due_today_count, 'follow-up')} {verb} due today")
        return TodayReturnTriggerViewModel(
            headline="Today at a glance",
            messages=messages[:2],
            comparison_basis="based on today's queue",
            show_cue=False,
            cue_label="",
        )

    current_urgent_ids = {
        str(item.get("employee_id") or "").strip()
        for item in current_items
        if str(item.get("employee_id") or "").strip()
        and str(item.get("_queue_status") or "") in {"overdue", "due_today"}
    }
    previous_urgent_ids = {
        str(item.get("employee_id") or "").strip()
        for item in prev_items
        if str(item.get("employee_id") or "").strip()
        and str(item.get("_queue_status") or "") in {"overdue", "due_today"}
    }
    current_overdue_ids = {
        str(item.get("employee_id") or "").strip()
        for item in current_items
        if str(item.get("employee_id") or "").strip()
        and str(item.get("_queue_status") or "") == "overdue"
    }
    previous_overdue_ids = {
        str(item.get("employee_id") or "").strip()
        for item in prev_items
        if str(item.get("employee_id") or "").strip()
        and str(item.get("_queue_status") or "") == "overdue"
    }

    new_urgent_count = len(current_urgent_ids - previous_urgent_ids)
    unchanged_overdue_count = len(current_overdue_ids & previous_overdue_ids)

    messages = []
    if new_urgent_count > 0:
        messages.append(f"{_count_with_noun(new_urgent_count, 'new urgent item')} surfaced since yesterday")
    else:
        messages.append("No new urgent issues since yesterday")

    if due_today_count > 0:
        verb = "is" if due_today_count == 1 else "are"
        messages.append(f"{_count_with_noun(due_today_count, 'follow-up')} {verb} due today")
    elif unchanged_overdue_count > 0:
        verb = "remains" if unchanged_overdue_count == 1 else "remain"
        messages.append(
            f"{_count_with_noun(unchanged_overdue_count, 'overdue follow-up')} {verb} unchanged since yesterday"
        )

    if not messages:
        return None

    has_meaningful_change = new_urgent_count > 0 or due_today_count > 0 or unchanged_overdue_count > 0

    return TodayReturnTriggerViewModel(
        headline="What changed since yesterday",
        messages=messages[:2],
        comparison_basis=f"compared with {str(previous_as_of_date)[:10]}",
        show_cue=has_meaningful_change,
        cue_label="Update" if has_meaningful_change else "",
    )


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
        headline = "Data confidence is high"
    elif status in {"partial", "low_confidence"} or warning_rows > 0 or score >= 50:
        headline = "Data needs a quick double-check"
    else:
        headline = "Data confidence is limited"

    if valid_rows is not None and rows_processed is not None and rows_processed > 0:
        detail = f"{valid_rows}/{rows_processed} rows usable"
    elif days > 0 or emp_count > 0:
        detail = f"{days} day(s) across {emp_count} employees"
    else:
        detail = "Latest import summary is available"

    trust_level = ""
    if status == "valid" and score >= 80:
        trust_level = "Confidence: High"
    elif status in {"partial", "low_confidence"} or warning_rows > 0 or score >= 50:
        trust_level = "Confidence: Medium"
    elif status:
        trust_level = "Confidence: Low"
    if trust_level:
        detail = f"{detail} · {trust_level}"

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


def _source_scope_label(source: Any) -> str:
    snapshot = dict(getattr(source, "snapshot", {}) or {})
    metadata = dict(getattr(source, "metadata", {}) or {})
    traceability = getattr(source, "traceability", None)
    drill_down = getattr(source, "drill_down", None)

    raw_scope = str(
        metadata.get("linked_scope")
        or snapshot.get("linked_scope")
        or getattr(traceability, "linked_scope", "")
        or ""
    ).strip().lower()

    if raw_scope in {"team", "process"}:
        return "Process-level signal"
    if raw_scope == "employee":
        return ""

    screen = str(getattr(drill_down, "screen", "") or "").strip().lower()
    if screen == "team_process":
        return "Process-level signal"
    return ""


def _source_shift_context_line(source: Any, signal: DisplaySignal) -> str:
    snapshot = dict(getattr(source, "snapshot", {}) or {})
    metadata = dict(getattr(source, "metadata", {}) or {})

    shift_name = ""
    for key in ("shift_name", "shift_label", "shift", "work_shift", "Shift"):
        shift_name = str(metadata.get(key) or snapshot.get(key) or "").strip()
        if shift_name:
            break

    if shift_name:
        return f"Shift context: {shift_name}"

    is_shift_level = bool(
        metadata.get("is_shift_level")
        or snapshot.get("is_shift_level")
        or (signal.flags or {}).get("is_shift_level")
    )
    if is_shift_level:
        return "Shift context: shift-level comparison"

    if _source_scope_label(source):
        return "Shift context unavailable in this snapshot"

    return ""


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
    snapshot = dict(getattr(item, "snapshot", {}) or {})

    def _normalized_support_line(text: str) -> str:
        clean = str(text or "").strip()
        if not clean:
            return ""
        lowered = clean.lower()
        if lowered.startswith("watch for"):
            return ""
        if lowered.startswith("compared to:") or lowered.startswith("compared with"):
            return "Compared against recent baseline"
        if lowered.startswith("signal source:"):
            source = clean.split(":", 1)[1].strip() if ":" in clean else ""
            return f"Source: {source}" if source else "Source available"
        if lowered.startswith("seen ") and " times " in lowered:
            parts = clean.split(" ", 1)
            return f"Repeated {parts[1]}" if len(parts) > 1 else clean
        if lowered == "open operational exception is still unresolved":
            return "Open operational exception remains unresolved"
        if lowered == signal_wording("follow_up_not_completed").lower():
            return "Follow-up remains open"
        return clean

    for text in list(getattr(signal, "supporting_text", []) or []):
        clean = _normalized_support_line(str(text or ""))
        if clean:
            lines.append(clean)

    source_label = str(
        snapshot.get("source_summary")
        or snapshot.get("source_name")
        or snapshot.get("source")
        or snapshot.get("dataset_name")
        or ""
    ).strip()
    if source_label:
        lines.append(f"Source: {source_label}")

    factor_keys = {str(f.key or "") for f in list(getattr(item, "factors_applied", []) or [])}
    if "open_exception" in factor_keys:
        lines.append("Open operational exception remains unresolved")

    import_job = str(snapshot.get("import_job_id") or "").strip()
    if import_job:
        lines.append(f"Import job: {import_job}")

    included_rows = _safe_int(snapshot.get("included_rows"))
    if included_rows is not None and included_rows > 0:
        lines.append(f"Included rows: {included_rows}")

    observed = format_observed_line(signal)
    if observed:
        lines.append(observed)

    if factor_keys.intersection({"overdue_followup", "due_today_followup", "open_exception"}):
        lines.append("Follow-up remains open")

    label = str(format_signal_label(signal) or "").strip().lower()
    if label in {
        signal_wording("lower_than_recent_pace").lower(),
        signal_wording("below_expected_pace").lower(),
    }:
        lines.append("Performance has declined compared to recent baseline")
    elif label == signal_wording("inconsistent_performance").lower():
        lines.append("Recent pace has varied day to day")
    elif label == signal_wording("improving_pace").lower():
        lines.append("Trend has improved across recent days")

    if signal.comparison_start_date is not None and signal.comparison_end_date is not None:
        lines.append("Compared against recent baseline")

    repeat_count, repeat_window_label = _repeat_context(item, signal)
    if repeat_count >= 2:
        window = str(repeat_window_label or "recent history").strip()
        if window == "this week":
            lines.append(f"Repeated {repeat_count} times this week")
        elif window.startswith("last "):
            lines.append(f"Repeated {repeat_count} times in the {window}")
        else:
            lines.append(f"Repeated {repeat_count} times in {window}")

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


def _has_open_exception(item: Any, signal: DisplaySignal) -> bool:
    factor_keys = {str(f.key or "") for f in list(getattr(item, "factors_applied", []) or [])}
    if "open_exception" in factor_keys:
        return True
    flags = dict(signal.flags or {})
    return bool(flags.get("open_exception"))


def _collapsed_evidence_line(item: Any, signal: DisplaySignal) -> str:
    snapshot = dict(getattr(item, "snapshot", {}) or {})
    source_label = str(
        snapshot.get("source_summary")
        or snapshot.get("source_name")
        or snapshot.get("source")
        or snapshot.get("dataset_name")
        or ""
    ).strip()
    if source_label:
        return f"Source: {source_label}"

    included_rows = _safe_int(snapshot.get("included_rows"))
    if included_rows is not None and included_rows > 0:
        return f"Evidence: {included_rows} rows in latest snapshot"

    import_job = str(snapshot.get("import_job_id") or "").strip()
    if import_job:
        return f"Evidence: import job {import_job}"

    observed = format_observed_line(signal)
    return observed or ""


def _ranking_hint(item: Any, signal: DisplaySignal) -> str:
    factor_keys = {str(f.key or "") for f in list(getattr(item, "factors_applied", []) or [])}
    flags = dict(signal.flags or {})

    # Show one strongest reason only so the collapsed hint stays concise.
    if factor_keys.intersection({"overdue_followup", "due_today_followup"}) or bool(flags.get("overdue")) or bool(flags.get("due_today")):
        return "Follow-up still open"
    if "open_exception" in factor_keys:
        return "Active operational issue"
    if factor_keys.intersection({"repeat_1", "repeat_2", "repeat_3_or_more"}):
        return ""
    if "trend_below_expected" in factor_keys:
        return "Below expected range vs peers"
    if factor_keys.intersection({"trend_declining", "trend_inconsistent"}):
        return "Declining vs recent baseline"

    label = str(format_signal_label(signal) or "").strip().lower()
    if label == signal_wording("below_expected_pace").lower():
        return "Below expected range vs peers"
    if label in {
        signal_wording("lower_than_recent_pace").lower(),
        signal_wording("inconsistent_performance").lower(),
    }:
        return "Declining vs recent baseline"
    if label == "repeated pattern":
        return ""
    if label == signal_wording("follow_up_not_completed").lower():
        return "Follow-up still open"
    return ""


def _is_follow_up_signal(signal: DisplaySignal) -> bool:
    label = str(format_signal_label(signal) or "").strip().lower()
    if label == signal_wording("follow_up_not_completed").lower():
        return True
    flags = dict(signal.flags or {})
    return bool(flags.get("overdue") or flags.get("due_today"))


def _repeat_context(source: Any, signal: DisplaySignal, *, include_signal_fallback: bool = True) -> tuple[int, str]:
    snapshot = dict(getattr(source, "snapshot", {}) or {})
    metadata = dict(getattr(source, "metadata", {}) or {})

    repeat_count = 0
    values: list[Any] = [
        snapshot.get("repeat_count"),
        metadata.get("repeat_count"),
    ]
    if include_signal_fallback:
        values.append(getattr(signal, "pattern_count", None))

    for raw_value in values:
        try:
            if raw_value is not None:
                repeat_count = max(repeat_count, int(raw_value))
        except Exception:
            continue

    if repeat_count < 2:
        return 0, ""

    window_label = str(
        snapshot.get("pattern_window_label")
        or metadata.get("pattern_window_label")
        or ""
    ).strip()
    if not window_label:
        recent_history = snapshot.get("recent_goal_status_history") or metadata.get("recent_goal_status_history")
        if isinstance(recent_history, list) and len(recent_history) >= 2:
            window_label = f"last {len(recent_history)} snapshots"
    if not window_label:
        try:
            window_days = int(metadata.get("pattern_recent_window_days") or 0)
        except Exception:
            window_days = 0
        if window_days > 0:
            window_label = f"last {window_days} days"
    if not window_label:
        window_label = "recent history"

    return repeat_count, window_label


def _repeat_summary_line(*, repeat_count: int, repeat_window_label: str) -> str:
    window = str(repeat_window_label or "recent history").strip()
    if window == "this week":
        return f"Seen {repeat_count} times this week"
    if window.startswith("last "):
        return f"Seen {repeat_count} times in the {window}"
    return f"Seen {repeat_count} times in {window}"


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


def _build_signal_instance_key(*, employee_id: str, process_name: str, signal: DisplaySignal) -> str:
    """Build a deterministic key for one rendered Today signal instance."""
    employee = _normalize_display_key(str(employee_id or "")) or "unknown-employee"
    process = _normalize_display_key(str(process_name or "")) or "unassigned"
    label = _normalize_display_key(str(getattr(signal.signal_label, "value", signal.signal_label) or "")) or "unknown"
    state = _normalize_display_key(str(getattr(signal.state, "value", signal.state) or "")) or "unknown"
    observed = str(getattr(signal, "observed_date", "") or "")[:10] or "unknown-date"
    return f"today-signal:{employee}:{process}:{label}:{state}:{observed}"


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
    factor_keys = {str(f.key or "") for f in list(getattr(item, "factors_applied", []) or [])}
    if "open_exception" in factor_keys:
        return "Active issue linked"
    repeat_count, repeat_window_label = _repeat_context(item, signal)
    if repeat_count >= 2:
        return _repeat_summary_line(repeat_count=repeat_count, repeat_window_label=repeat_window_label)

    return ""


def _confidence_level_value(signal: DisplaySignal) -> str:
    value = getattr(signal.confidence_level, "value", signal.confidence_level)
    return str(value or getattr(signal.confidence, "value", "low")).strip().lower()


def _freshness_line(signal: DisplaySignal) -> str:
    observed = getattr(signal, "observed_date", None)
    if observed is None:
        return ""
    age_days = max(0, (date.today() - observed).days)
    if age_days == 0:
        return "Freshness: Current shift/day snapshot"
    if age_days == 1:
        return "Freshness: 1 day old snapshot"
    return f"Freshness: {age_days} days old snapshot"


def _why_surfaced_line(source: Any, signal: DisplaySignal) -> str:
    mode = get_signal_display_mode(signal)
    if mode == SignalDisplayMode.LOW_DATA:
        base = "Surfaced because limited recent history is available for comparison."
        scope_label = _source_scope_label(source)
        return f"{base} Scope: {scope_label}." if scope_label else base

    flags = dict(signal.flags or {})
    if bool(flags.get("overdue")):
        base = "Surfaced because this follow-up is still open past its due date."
        scope_label = _source_scope_label(source)
        return f"{base} Scope: {scope_label}." if scope_label else base
    if bool(flags.get("due_today")):
        base = "Surfaced because this follow-up is due in the current snapshot."
        scope_label = _source_scope_label(source)
        return f"{base} Scope: {scope_label}." if scope_label else base

    label = str(format_signal_label(signal) or "").strip().lower()
    if label in {
        signal_wording("lower_than_recent_pace").lower(),
        signal_wording("below_expected_pace").lower(),
    }:
        base = "Below recent baseline vs comparable days."
        scope_label = _source_scope_label(source)
        return f"{base} Scope: {scope_label}." if scope_label else base
    if label == signal_wording("inconsistent_performance").lower():
        base = "Surfaced because recent output has been more variable than usual."
        scope_label = _source_scope_label(source)
        return f"{base} Scope: {scope_label}." if scope_label else base
    if label == signal_wording("improving_pace").lower():
        base = "Surfaced because recent output is above the recent baseline (prior comparable days and target context when available)."
        scope_label = _source_scope_label(source)
        return f"{base} Scope: {scope_label}." if scope_label else base

    base = "Surfaced because this pattern differs from recent operating context."
    scope_label = _source_scope_label(source)
    return f"{base} Scope: {scope_label}." if scope_label else base


def _evidence_basis_line(source: Any, signal: DisplaySignal) -> str:
    label = str(format_signal_label(signal) or "").strip().lower()
    headline_already_repeat = label == "repeated pattern"

    repeat_count, repeat_window_label = _repeat_context(source, signal, include_signal_fallback=False)
    repeat_evidence = ""
    if repeat_count >= 2 and not headline_already_repeat:
        repeat_evidence = _repeat_summary_line(repeat_count=repeat_count, repeat_window_label=repeat_window_label)

    shift_context = _source_shift_context_line(source, signal)

    recent_count = _low_data_recent_count(source, signal)
    if recent_count is not None and recent_count > 1:
        base = f"Based on {recent_count} recent records"
        segments = [base]
        if repeat_evidence:
            segments.append(repeat_evidence)
        if shift_context:
            segments.append(shift_context)
        return " · ".join(segments)

    observed = getattr(signal, "observed_date", None)
    if observed is not None:
        base = "Latest snapshot only"
        segments = [base]
        if repeat_evidence:
            segments.append(repeat_evidence)
        if shift_context:
            segments.append(shift_context)
        return " · ".join(segments)

    if repeat_evidence and shift_context:
        return f"{repeat_evidence} · {shift_context}"
    return repeat_evidence or shift_context


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


def _attention_priority_rank(item: Any) -> int:
    score = int(getattr(item, "attention_score", 0) or 0)
    return -score


def _severity_rank(item: Any) -> int:
    """Backward-compatible alias for attention-priority ranking semantics."""
    return _attention_priority_rank(item)


def _recency_rank(signal: DisplaySignal) -> int:
    return -int(signal.observed_date.toordinal())


def _tie_breaker(item: Any, signal: DisplaySignal) -> tuple[str, str, str, str]:
    snapshot = dict(getattr(item, "snapshot", {}) or {})
    employee_key = str(getattr(item, "employee_id", "") or snapshot.get("employee_id") or snapshot.get("EmployeeID") or "").strip().lower()
    process_key = str(getattr(item, "process_name", "") or snapshot.get("process_name") or snapshot.get("Department") or "").strip().lower()
    label_key = str(format_signal_label(signal) or "").strip().lower()
    summary_key = str(getattr(item, "attention_summary", "") or "").strip().lower()
    return (employee_key, process_key, label_key, summary_key)


def _sort_ranked_cards(rows: list[_RankedCard]) -> list[_RankedCard]:
    return sorted(
        rows,
        key=lambda row: (
            row.bucket_rank,
            row.status_rank,
            row.repeat_rank,
            row.confidence_rank,
            row.attention_priority_rank,
            row.recency_rank,
            row.tie_breaker,
        ),
    )


def _merge_lines(existing: list[str], incoming: list[str], *, max_lines: int = 3) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for line in [*list(existing or []), *list(incoming or [])]:
        clean = str(line or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(clean)
        if len(merged) >= max_lines:
            break
    return merged


def _merge_ranked_cards(preferred: _RankedCard, incoming: _RankedCard) -> _RankedCard:
    additional_reason = ""
    incoming_reason = str(incoming.card.line_2 or "").strip()
    preferred_reason = str(preferred.card.line_2 or "").strip()
    if incoming_reason and preferred_reason and incoming_reason.lower() != preferred_reason.lower():
        additional_reason = f"Additional signal: {incoming_reason}"

    merged_lines = _merge_lines(
        list(preferred.card.expanded_lines or []),
        [additional_reason, *list(incoming.card.expanded_lines or [])],
        max_lines=3,
    )

    return _RankedCard(
        card=TodayQueueCardViewModel(
            employee_id=preferred.card.employee_id,
            process_id=preferred.card.process_id,
            state=preferred.card.state,
            line_1=preferred.card.line_1,
            line_2=preferred.card.line_2,
            line_3=preferred.card.line_3,
            line_4=preferred.card.line_4,
            line_5=preferred.card.line_5,
            expanded_lines=merged_lines,
            normalized_action_state=preferred.card.normalized_action_state or incoming.card.normalized_action_state,
            normalized_action_state_detail=preferred.card.normalized_action_state_detail or incoming.card.normalized_action_state_detail,
            freshness_line=preferred.card.freshness_line or incoming.card.freshness_line,
            collapsed_hint=preferred.card.collapsed_hint or incoming.card.collapsed_hint,
            collapsed_evidence=preferred.card.collapsed_evidence or incoming.card.collapsed_evidence,
            collapsed_issue=preferred.card.collapsed_issue or incoming.card.collapsed_issue,
            signal_key=preferred.card.signal_key or incoming.card.signal_key,
            repeat_count=max(int(preferred.card.repeat_count or 0), int(incoming.card.repeat_count or 0)),
            repeat_window_label=preferred.card.repeat_window_label or incoming.card.repeat_window_label,
            last_action_date_label=preferred.card.last_action_date_label or incoming.card.last_action_date_label,
        ),
        bucket_rank=preferred.bucket_rank,
        status_rank=preferred.status_rank,
        repeat_rank=preferred.repeat_rank,
        confidence_rank=preferred.confidence_rank,
        attention_priority_rank=preferred.attention_priority_rank,
        recency_rank=preferred.recency_rank,
        tie_breaker=preferred.tie_breaker,
    )


def _dedupe_ranked_cards(rows: list[_RankedCard]) -> list[_RankedCard]:
    deduped: list[_RankedCard] = []
    index_by_key: dict[tuple[str, str], int] = {}

    for row in rows:
        card = row.card
        key = (str(card.employee_id or "").strip().lower(), str(card.process_id or "").strip().lower())
        if key not in index_by_key:
            index_by_key[key] = len(deduped)
            deduped.append(row)
            continue

        current_index = index_by_key[key]
        current = deduped[current_index]

        deduped[current_index] = _merge_ranked_cards(current, row)

    return deduped


def _merge_secondary_into_primary_duplicates(
    primary_rows: list[_RankedCard],
    secondary_rows: list[_RankedCard],
) -> tuple[list[_RankedCard], list[_RankedCard]]:
    merged_primary = list(primary_rows)
    merged_secondary: list[_RankedCard] = []
    primary_index: dict[tuple[str, str], int] = {
        (str(row.card.employee_id or "").strip().lower(), str(row.card.process_id or "").strip().lower()): idx
        for idx, row in enumerate(merged_primary)
    }

    for row in list(secondary_rows or []):
        key = (str(row.card.employee_id or "").strip().lower(), str(row.card.process_id or "").strip().lower())
        if key in primary_index:
            idx = primary_index[key]
            merged_primary[idx] = _merge_ranked_cards(merged_primary[idx], row)
            continue
        merged_secondary.append(row)

    return merged_primary, merged_secondary


def _should_force_primary(item: Any, signal: DisplaySignal) -> bool:
    factor_keys = {str(f.key or "") for f in list(getattr(item, "factors_applied", []) or [])}
    flags = dict(signal.flags or {})
    if bool(flags.get("overdue")) or bool(flags.get("due_today")):
        return True
    return bool(factor_keys.intersection({"overdue_followup", "due_today_followup", "open_exception"}))


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
    line_3 = _why_surfaced_line(item, signal)
    line_4 = _evidence_basis_line(item, signal)
    line_5 = format_confidence_line(signal)
    employee_id = str(getattr(item, "employee_id", "") or "")
    process_id = str(getattr(item, "process_name", "") or "")
    signal_key = _build_signal_instance_key(
        employee_id=employee_id,
        process_name=process_id or process_name,
        signal=signal,
    )
    repeat_count, repeat_window_label = _repeat_context(item, signal)

    if low_data_state:
        collapsed = format_low_data_collapsed_lines(signal)
        line_2 = collapsed[0] if collapsed else signal_wording("not_enough_history_yet")
        expanded = format_low_data_expanded_lines(signal, recent_record_count=_low_data_recent_count(item, signal))
        return TodayQueueCardViewModel(
            employee_id=employee_id,
            process_id=process_id,
            state=str(signal.state.value),
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=line_4,
            line_5=line_5,
            expanded_lines=_dedupe_expanded(primary=line_2, lines=expanded, excluded=[line_3, line_4], max_lines=3),
            collapsed_hint=_ranking_hint(item, signal),
            collapsed_evidence=_collapsed_evidence_line(item, signal),
            collapsed_issue="Active issue linked" if _has_open_exception(item, signal) else "",
            signal_key=signal_key,
            repeat_count=repeat_count,
            repeat_window_label=repeat_window_label,
        )

    if current_state_mode:
        line_2 = format_signal_label(signal)
        return TodayQueueCardViewModel(
            employee_id=employee_id,
            process_id=process_id,
            state=str(signal.state.value),
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=line_4,
            line_5=format_confidence_line(signal),
            expanded_lines=[],
            freshness_line=_freshness_line(signal),
            collapsed_hint=_ranking_hint(item, signal),
            collapsed_evidence=_collapsed_evidence_line(item, signal),
            collapsed_issue="Active issue linked" if _has_open_exception(item, signal) else "",
            signal_key=signal_key,
            repeat_count=repeat_count,
            repeat_window_label=repeat_window_label,
        )

    if _is_follow_up_signal(signal):
        expanded_candidates = _attention_context_lines(item, signal, max_lines=4)
        expanded = _dedupe_expanded(
            primary=line_2,
            lines=expanded_candidates,
            excluded=[line_3, line_4, _follow_up_due_line(item, signal), _short_follow_up_context(item, signal)],
            max_lines=3,
        )
    else:
        expanded = _dedupe_expanded(
            primary=line_2,
            lines=_attention_context_lines(item, signal, max_lines=4),
            excluded=[line_3, line_4, format_observed_line(signal), format_comparison_line(signal)],
            max_lines=3,
        )

    line_3_lower = line_3.strip().lower()
    line_4_lower = line_4.strip().lower()
    if "baseline" in line_3_lower:
        expanded = [line for line in list(expanded or []) if "compared against recent baseline" not in str(line).lower()]
    if (" seen " in f" {line_4_lower} " and " times " in line_4_lower) or ("repeat" in line_4_lower and "times" in line_4_lower):
        expanded = [
            line
            for line in list(expanded or [])
            if "repeated " not in str(line).lower() or " times " not in str(line).lower()
        ]
    if any("repeated " in str(line).lower() and " times " in str(line).lower() for line in list(expanded or [])):
        expanded = [
            line
            for line in list(expanded or [])
            if "performance has declined compared to recent baseline" not in str(line).lower()
        ]

    if line_2.strip().lower() == "seen multiple times":
        expanded = [
            line
            for line in list(expanded or [])
            if "seen " not in str(line).lower() or " times " not in str(line).lower()
        ]

    return TodayQueueCardViewModel(
        employee_id=employee_id,
        process_id=process_id,
        state=str(signal.state.value),
        line_1=line_1,
        line_2=line_2,
        line_3=line_3,
        line_4=line_4,
        line_5=line_5,
        expanded_lines=expanded,
        freshness_line=_freshness_line(signal),
        collapsed_hint=_ranking_hint(item, signal),
        collapsed_evidence=_collapsed_evidence_line(item, signal),
        collapsed_issue="Active issue linked" if _has_open_exception(item, signal) else "",
        signal_key=signal_key,
        repeat_count=repeat_count,
        repeat_window_label=repeat_window_label,
    )


def _card_from_insight_card(card: InsightCardContract, signal: DisplaySignal) -> TodayQueueCardViewModel:
    mode = get_signal_display_mode(signal)
    low_data_state = mode == SignalDisplayMode.LOW_DATA
    current_state_mode = mode == SignalDisplayMode.CURRENT_STATE
    employee_name = str(signal.employee_name)
    process_name = str(signal.process)
    line_1 = f"{employee_name} · {process_name}"
    line_2 = _attention_primary_signal(card, signal)
    line_3 = _why_surfaced_line(card, signal)
    line_4 = _evidence_basis_line(card, signal)
    line_5 = format_confidence_line(signal)
    employee_id = str(card.drill_down.entity_id or "")
    signal_key = _build_signal_instance_key(
        employee_id=employee_id,
        process_name=process_name,
        signal=signal,
    )
    repeat_count, repeat_window_label = _repeat_context(card, signal)

    if low_data_state:
        collapsed = format_low_data_collapsed_lines(signal)
        line_2 = collapsed[0] if collapsed else signal_wording("not_enough_history_yet")
        expanded = format_low_data_expanded_lines(signal, recent_record_count=_low_data_recent_count(card, signal))
        return TodayQueueCardViewModel(
            employee_id=employee_id,
            process_id=process_name,
            state=str(signal.state.value),
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=line_4,
            line_5=line_5,
            expanded_lines=_dedupe_expanded(primary=line_2, lines=expanded, excluded=[line_3, line_4], max_lines=3),
            signal_key=signal_key,
            repeat_count=repeat_count,
            repeat_window_label=repeat_window_label,
        )

    if current_state_mode:
        line_2 = format_signal_label(signal)
        return TodayQueueCardViewModel(
            employee_id=employee_id,
            process_id=process_name,
            state=str(signal.state.value),
            line_1=line_1,
            line_2=line_2,
            line_3=line_3,
            line_4=line_4,
            line_5=format_confidence_line(signal),
            expanded_lines=[],
            freshness_line=_freshness_line(signal),
            signal_key=signal_key,
            repeat_count=repeat_count,
            repeat_window_label=repeat_window_label,
        )

    expanded = _dedupe_expanded(
        primary=line_2,
        lines=[],
        excluded=[line_3, line_4, format_observed_line(signal), format_comparison_line(signal), _follow_up_due_line(card, signal), _short_follow_up_context(card, signal)],
        max_lines=3,
    )

    line_3_lower = line_3.strip().lower()
    line_4_lower = line_4.strip().lower()
    if "baseline" in line_3_lower:
        expanded = [line for line in list(expanded or []) if "compared against recent baseline" not in str(line).lower()]
    if (" seen " in f" {line_4_lower} " and " times " in line_4_lower) or ("repeat" in line_4_lower and "times" in line_4_lower):
        expanded = [
            line
            for line in list(expanded or [])
            if "repeated " not in str(line).lower() or " times " not in str(line).lower()
        ]
    if any("repeated " in str(line).lower() and " times " in str(line).lower() for line in list(expanded or [])):
        expanded = [
            line
            for line in list(expanded or [])
            if "performance has declined compared to recent baseline" not in str(line).lower()
        ]

    if line_2.strip().lower() == "seen multiple times":
        expanded = [
            line
            for line in list(expanded or [])
            if "seen " not in str(line).lower() or " times " not in str(line).lower()
        ]

    return TodayQueueCardViewModel(
        employee_id=employee_id,
        process_id=process_name,
        state=str(signal.state.value),
        line_1=line_1,
        line_2=line_2,
        line_3=line_3,
        line_4=line_4,
        line_5=line_5,
        expanded_lines=expanded,
        freshness_line=_freshness_line(signal),
        signal_key=signal_key,
        repeat_count=repeat_count,
        repeat_window_label=repeat_window_label,
    )


def enrich_today_queue_card_action_context(
    *,
    card: TodayQueueCardViewModel,
    today: date,
    last_action_lookup: dict[str, str] | None = None,
    action_state_lookup: dict[str, dict[str, Any]] | None = None,
) -> TodayQueueCardViewModel:
    employee_id = str(card.employee_id or "").strip()
    updates: dict[str, Any] = {}

    if employee_id and last_action_lookup and str(last_action_lookup.get(employee_id) or "").strip():
        label = _days_ago_label(str(last_action_lookup[employee_id]), today)
        if label:
            updates["last_action_date_label"] = label

    if employee_id and action_state_lookup:
        state_payload = dict(action_state_lookup.get(employee_id) or {})
        state_value = str(state_payload.get("state") or "").strip()
        if state_value:
            updates["normalized_action_state"] = state_value
            updates["normalized_action_state_detail"] = str(state_payload.get("state_detail") or "").strip()

    if not updates:
        return card
    return dataclasses.replace(card, **updates)


def build_today_queue_card_from_insight_card(
    *,
    card: InsightCardContract,
    today: date,
    last_action_lookup: dict[str, str] | None = None,
    action_state_lookup: dict[str, dict[str, Any]] | None = None,
) -> TodayQueueCardViewModel | None:
    """Public thin adapter so legacy renderers can consume normalized card semantics."""
    signal = build_display_signal_from_insight_card(card=card, today=today)
    if not is_display_signal_eligible(signal, allow_low_data_case=False):
        return None
    return enrich_today_queue_card_action_context(
        card=_card_from_insight_card(card, signal),
        today=today,
        last_action_lookup=last_action_lookup,
        action_state_lookup=action_state_lookup,
    )


def build_today_queue_view_model(
    attention: AttentionSummary,
    *,
    decision_items: list[DecisionItem] | None = None,
    decision_policy: DecisionSurfacingPolicy | None = None,
    allow_legacy_attention_fallback: bool = True,
    suppressed_cards: list[InsightCardContract] | None = None,
    today: date,
    last_action_lookup: dict[str, str] | None = None,
    action_state_lookup: dict[str, dict[str, Any]] | None = None,
) -> TodayQueueViewModel:
    # last_action_lookup: {employee_id: iso_date_str} where the date is the
    # most recent last_event_at (or created_at fallback) from open action queue
    # items.  Absent entries mean no action data exists for that employee.
    primary_ranked: list[_RankedCard] = []
    secondary_ranked: list[_RankedCard] = []
    suppressed: list[SuppressedSignalViewModel] = []

    ranked_sources: list[tuple[Any, DisplaySignal, TodayQueueCardViewModel]] = []
    if decision_items:
        for decision in list(decision_items or []):
            item = decision.to_attention_item()
            signal = build_display_signal_from_attention_item(item=item, today=today)
            card_vm = _card_from_pair(item, signal)
            confidence_basis = str(decision.confidence_basis or "").strip()
            expanded_lines = _merge_lines([decision.primary_reason, confidence_basis], list(card_vm.expanded_lines or []), max_lines=3)
            card_vm = dataclasses.replace(card_vm, expanded_lines=expanded_lines)
            ranked_sources.append((item, signal, card_vm))
    elif allow_legacy_attention_fallback:
        # Legacy fallback retained for emergency rollback only.
        # Active Today runtime should pass allow_legacy_attention_fallback=False.
        for item in list(attention.ranked_items or []):
            signal = build_display_signal_from_attention_item(item=item, today=today)
            ranked_sources.append((item, signal, _card_from_pair(item, signal)))

    for item, signal, base_card in ranked_sources:
        signal = build_display_signal_from_attention_item(item=item, today=today)
        eligible_primary = is_display_signal_eligible(
            signal,
            allow_low_data_case=False,
            min_confidence_for_full_or_partial="low",
        )
        eligible_low_data = is_display_signal_eligible(
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

        card_vm = enrich_today_queue_card_action_context(
            card=base_card,
            today=today,
            last_action_lookup=last_action_lookup,
            action_state_lookup=action_state_lookup,
        )
        ranked = _RankedCard(
            card=card_vm,
            bucket_rank=_bucket_rank(item, signal),
            status_rank=_status_rank(signal),
            repeat_rank=_repeat_rank(item),
            confidence_rank=_confidence_rank(signal),
            attention_priority_rank=_attention_priority_rank(item),
            recency_rank=_recency_rank(signal),
            tie_breaker=_tie_breaker(item, signal),
        )

        employee_id = str(getattr(item, "employee_id", "") or "").strip()
        if decision_policy and employee_id:
            if employee_id in set(decision_policy.primary_employee_ids):
                primary_ranked.append(ranked)
                continue
            if employee_id in set(decision_policy.secondary_employee_ids):
                secondary_ranked.append(ranked)
                continue

        mode = get_signal_display_mode(signal)
        force_primary = _should_force_primary(item, signal)
        if ((not eligible_primary) and (not force_primary)) or mode == SignalDisplayMode.CURRENT_STATE or (_confidence_level_value(signal) == "low" and (not force_primary)) or (str(getattr(item, "attention_tier", "")) == "low" and (not force_primary)):
            secondary_ranked.append(ranked)
        else:
            primary_ranked.append(ranked)

    for card in [c for c in list(suppressed_cards or []) if isinstance(c, InsightCardContract)]:
        signal = build_display_signal_from_insight_card(card=card, today=today)
        if not is_display_signal_eligible(signal, allow_low_data_case=True):
            continue
        card_vm = enrich_today_queue_card_action_context(
            card=_card_from_insight_card(card, signal),
            today=today,
            last_action_lookup=last_action_lookup,
            action_state_lookup=action_state_lookup,
        )
        secondary_ranked.append(
            _RankedCard(
                card=card_vm,
                bucket_rank=2,
                status_rank=_status_rank(signal),
                repeat_rank=0,
                confidence_rank=_confidence_rank(signal),
                attention_priority_rank=0,
                recency_rank=_recency_rank(signal),
                tie_breaker=(
                    str(card.drill_down.entity_id or "").strip().lower(),
                    str(signal.process or "").strip().lower(),
                    str(format_signal_label(signal) or "").strip().lower(),
                    str(card.title or "").strip().lower(),
                ),
            )
        )

    secondary_deduped = _dedupe_ranked_cards(_sort_ranked_cards(secondary_ranked))
    primary_deduped = _dedupe_ranked_cards(_sort_ranked_cards(primary_ranked))
    primary_deduped, secondary_deduped = _merge_secondary_into_primary_duplicates(primary_deduped, secondary_deduped)

    primary_cards = [row.card for row in primary_deduped]
    secondary_cards = [row.card for row in secondary_deduped]

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


# ---------------------------------------------------------------------------
# Attention summary strip view model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TodayAttentionStripViewModel:
    """Compact top-of-queue counts for the Today attention summary strip.

    Fields
    ------
    total_needing_attention
        Count of attention items that passed the display threshold (non-suppressed).
        Derived from ``AttentionSummary.ranked_items`` so it matches the queue exactly.
    new_today
        Count of queue action items whose ``created_at`` date equals *today*.
        Approximation: reflects newly-opened actions, not every newly-fired signal.
        Signals whose underlying action predates today are not counted here.
    overdue_follow_ups
        Count of queue items with ``_queue_status == "overdue"``.
        Derived from the same ``queue_items`` list the queue renders.
    reviewed_today
        Count of items resolved or reviewed today.  Set to ``None`` when this
        information is not available from the precomputed payload.
    touchpoints_logged_today
        Count of coaching/follow-up touchpoints logged today.  Hidden when zero
        to keep the strip compact in no-activity states.
    follow_ups_scheduled_today
        Count of today's touchpoints that explicitly set a next follow-up date.
        Hidden when zero to avoid implying planning activity that did not occur.
    """

    total_needing_attention: int
    new_today: int
    overdue_follow_ups: int
    reviewed_today: int | None
    touchpoints_logged_today: int | None
    follow_ups_scheduled_today: int | None


def _positive_metric_or_none(value: Any) -> int | None:
    try:
        resolved = int(value or 0)
    except Exception:
        return None
    return resolved if resolved > 0 else None


def build_today_attention_strip(
    *,
    attention: AttentionSummary,
    queue_items: list[dict[str, Any]],
    today: date,
    same_day_activity: dict[str, Any] | None = None,
) -> TodayAttentionStripViewModel:
    """Derive the attention summary strip values from already-computed data.

    Does not query any service or database; all inputs must be pre-loaded by
    the caller (typically from the precomputed Today payload).
    """
    total = len(list(attention.ranked_items or []))

    overdue = 0
    new_today = 0
    today_iso = today.isoformat()

    for item in list(queue_items or []):
        if str(item.get("_queue_status") or "") == "overdue":
            overdue += 1
        # new_today: action was first created on today's date.
        # Approximation — actions opened before today whose signal fires fresh
        # are not counted; only truly new actions are.
        raw_created = str(item.get("created_at") or "").strip()
        if raw_created and raw_created[:10] == today_iso:
            new_today += 1

    return TodayAttentionStripViewModel(
        total_needing_attention=total,
        new_today=new_today,
        overdue_follow_ups=overdue,
        reviewed_today=_positive_metric_or_none((same_day_activity or {}).get("reviewed_today")),
        touchpoints_logged_today=_positive_metric_or_none((same_day_activity or {}).get("touchpoints_logged_today")),
        follow_ups_scheduled_today=_positive_metric_or_none((same_day_activity or {}).get("follow_ups_scheduled_today")),
    )


def build_today_weekly_summary_view_model(
    *,
    reviewed_issues: int,
    follow_up_touchpoints: int,
    closed_issues: int,
    improved_outcomes: int,
) -> TodayWeeklySummaryViewModel:
    """Build a compact weekly impact summary for the Today page.

    Only includes metrics backed by existing action/signal event logs.
    Zero-value items are omitted to keep the block quiet when no weekly
    activity has been recorded.
    """
    items: list[TodayWeeklySummaryItemViewModel] = []

    if int(reviewed_issues or 0) > 0:
        count = int(reviewed_issues)
        noun = "issue" if count == 1 else "issues"
        items.append(TodayWeeklySummaryItemViewModel(headline=f"{count} {noun} reviewed this week"))

    if int(follow_up_touchpoints or 0) > 0:
        count = int(follow_up_touchpoints)
        noun = "touchpoint" if count == 1 else "touchpoints"
        items.append(TodayWeeklySummaryItemViewModel(headline=f"{count} follow-up {noun} logged this week"))

    if int(closed_issues or 0) > 0:
        count = int(closed_issues)
        noun = "issue" if count == 1 else "issues"
        items.append(TodayWeeklySummaryItemViewModel(headline=f"{count} {noun} closed this week"))

    if int(improved_outcomes or 0) > 0:
        count = int(improved_outcomes)
        noun = "outcome" if count == 1 else "outcomes"
        items.append(TodayWeeklySummaryItemViewModel(headline=f"{count} improved {noun} logged this week"))

    return TodayWeeklySummaryViewModel(items=items)
