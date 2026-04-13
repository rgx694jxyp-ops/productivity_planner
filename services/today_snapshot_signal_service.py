"""Thin-data fallback signal service for the Today page.

When trend history is too shallow for reliable signal classification, this
service derives same-day snapshot cards by comparing employees within the
current snapshot group (group median as reference, not a historical trend
window).

Cards use the existing TodayQueueCardViewModel 5-line contract:
  1. Name · Process
  2. Signal headline (snapshot-specific — no trend wording)
  3. Surfaced because (group-relative, honest)
  4. Confidence + data basis
  5. Evidence basis (record counts / snapshot label)

Three signal modes are defined here so callers can route traffic without
re-examining the raw data:
  STABLE_SIGNAL  — multi-day trend history is available; use the normal queue.
  EARLY_SIGNAL   — 2–3 days or thin coverage; directional signals only.
  LIMITED_DATA   — ≤ 1 day or no usable rows; snapshot comparisons only.

This service is descriptive only.  It never prescribes what a supervisor
should do.
"""

from __future__ import annotations

import statistics
from datetime import date
from enum import Enum
import re
from typing import Any

from services.today_view_model_service import TodayQueueCardViewModel
from services.trend_classification_service import normalize_trend_state


class SignalMode(str, Enum):
    STABLE_SIGNAL = "stable_signal"  # Enough multi-day history for trend classification
    EARLY_SIGNAL = "early_signal"    # 2–3 days or thin coverage; directional only
    LIMITED_DATA = "limited_data"    # ≤ 1 day or no usable rows; snapshot only


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "unknown"


# ---------------------------------------------------------------------------
# Signal mode classifier
# ---------------------------------------------------------------------------


def classify_signal_mode(
    *,
    goal_status: list[dict[str, Any]],
    import_summary: dict[str, Any],
) -> SignalMode:
    """Classify the quality of the current signal dataset.

    Criteria
    --------
    STABLE_SIGNAL  : ≥ 3 import days AND ≥ 25 % of rows have a real trend AND
                     trust confidence score ≥ 60 AND trust status is not degraded.
    EARLY_SIGNAL   : Some usable data, but not enough for stable trends.
    LIMITED_DATA   : ≤ 1 day of data, or no usable rows at all.
    """
    summary = dict(import_summary or {})
    days = int(summary.get("days") or 0)
    trust = dict(summary.get("trust") or {})
    confidence_score = int(trust.get("confidence_score") or 0)
    trust_status = str(trust.get("status") or "").strip().lower()

    rows = list(goal_status or [])
    usable_rows = [
        row for row in rows
        if normalize_trend_state(row.get("trend") or "") not in {"insufficient_data"}
        and _safe_float(row.get("Average UPH")) > 0
    ]

    if not rows or days <= 0:
        return SignalMode.LIMITED_DATA

    if days <= 1:
        return SignalMode.LIMITED_DATA

    usable_fraction = len(usable_rows) / max(len(rows), 1)
    is_degraded_trust = trust_status in {"partial", "low_confidence", "invalid"}
    is_low_score = 0 < confidence_score < 60

    if days <= 2 or usable_fraction < 0.25 or is_degraded_trust or is_low_score:
        return SignalMode.EARLY_SIGNAL

    return SignalMode.STABLE_SIGNAL


# ---------------------------------------------------------------------------
# Snapshot fallback card builder
# ---------------------------------------------------------------------------


def build_snapshot_fallback_cards(
    *,
    goal_status: list[dict[str, Any]],
    today: date,
    max_items: int = 4,
) -> list[TodayQueueCardViewModel]:
    """Build same-day snapshot cards when trend history is too thin.

    Generates cards for:
    - The employee furthest below the group median (gap ≥ 10 %).
    - The employee furthest above the group median (gap ≥ 15 %).
    - A wide-spread signal if the group UPH range spans > 25 %.

    Returns an empty list when fewer than 2 employees have usable UPH data.
    Cards are returned in a deterministic order (bottom outlier first).
    """
    rows_with_uph = [
        row for row in (goal_status or [])
        if _safe_float(row.get("Average UPH")) > 0
        and str(row.get("EmployeeID") or row.get("Employee") or "").strip()
    ]

    if len(rows_with_uph) < 2:
        return []

    uphs = [_safe_float(row.get("Average UPH")) for row in rows_with_uph]
    median_uph = statistics.median(uphs)
    max_uph = max(uphs)
    min_uph = min(uphs)
    spread_pct = ((max_uph - min_uph) / median_uph * 100) if median_uph > 0 else 0.0

    sorted_rows = sorted(rows_with_uph, key=lambda r: _safe_float(r.get("Average UPH")))
    group_count = len(rows_with_uph)
    cards: list[TodayQueueCardViewModel] = []
    used_emp_ids: set[str] = set()

    def _emp_id(row: dict[str, Any]) -> str:
        return str(row.get("EmployeeID") or row.get("Employee") or "").strip()

    def _name(row: dict[str, Any]) -> str:
        return str(
            row.get("Employee") or row.get("Employee Name") or _emp_id(row) or "Unknown"
        ).strip()

    def _dept(row: dict[str, Any]) -> str:
        return str(row.get("Department") or row.get("process_name") or "Unassigned").strip()

    # --- Bottom outlier ---
    bottom_row = sorted_rows[0]
    bottom_uph = _safe_float(bottom_row.get("Average UPH"))
    gap_pct = (median_uph - bottom_uph) / median_uph * 100 if median_uph > 0 else 0.0

    if gap_pct >= 10.0:
        emp = _emp_id(bottom_row)
        name = _name(bottom_row)
        dept = _dept(bottom_row)
        used_emp_ids.add(emp)
        target_uph = _safe_float(bottom_row.get("Target UPH"))
        record_count = max(1, int(_safe_float(bottom_row.get("Record Count")) or 1))
        target_note = (
            f"Target on file: {target_uph:.1f} UPH."
            if target_uph > 0
            else "No target on file."
        )
        cards.append(
            TodayQueueCardViewModel(
                employee_id=emp,
                process_id=dept,
                state="CURRENT",
                line_1=f"{name} · {dept}",
                line_2="Lower in today's snapshot",
                line_3=(
                    f"Surfaced because output is {gap_pct:.0f}% below the current group median "
                    f"({median_uph:.1f} UPH, {group_count} employees). "
                    "Early signal — no multi-day trend available yet."
                ),
                line_4=f"Confidence: Low · {record_count} record(s) in today's snapshot",
                line_5=f"Evidence basis: today's snapshot only. {target_note}",
                expanded_lines=[
                    f"Today's value: {bottom_uph:.1f} UPH",
                    f"Group median today: {median_uph:.1f} UPH  ({group_count} employees)",
                    f"Gap from median: {gap_pct:.0f}%",
                    target_note,
                    "No multi-day history available yet. Confidence will increase as more shifts are imported.",
                ],
                freshness_line="Freshness: Current shift/day snapshot",
                signal_key=f"today-snapshot:{_slug(emp)}:{_slug(dept)}:{today.isoformat()}:lower",
            )
        )

    if len(cards) >= max_items:
        return cards

    # --- Top outlier ---
    top_row = sorted_rows[-1]
    top_uph = _safe_float(top_row.get("Average UPH"))
    top_emp = _emp_id(top_row)
    top_gap_pct = (top_uph - median_uph) / median_uph * 100 if median_uph > 0 else 0.0

    if top_gap_pct >= 15.0 and top_emp not in used_emp_ids:
        name = _name(top_row)
        dept = _dept(top_row)
        used_emp_ids.add(top_emp)
        record_count = max(1, int(_safe_float(top_row.get("Record Count")) or 1))
        cards.append(
            TodayQueueCardViewModel(
                employee_id=top_emp,
                process_id=dept,
                state="CURRENT",
                line_1=f"{name} · {dept}",
                line_2="Higher in today's snapshot",
                line_3=(
                    f"Surfaced because output is {top_gap_pct:.0f}% above the current group median "
                    f"({median_uph:.1f} UPH, {group_count} employees). "
                    "Early signal — no multi-day trend available yet."
                ),
                line_4=f"Confidence: Low · {record_count} record(s) in today's snapshot",
                line_5="Evidence basis: today's snapshot only.",
                expanded_lines=[
                    f"Today's value: {top_uph:.1f} UPH",
                    f"Group median today: {median_uph:.1f} UPH  ({group_count} employees)",
                    f"Gap above median: {top_gap_pct:.0f}%",
                    "No multi-day history available yet. Confidence will increase as more shifts are imported.",
                ],
                freshness_line="Freshness: Current shift/day snapshot",
                signal_key=f"today-snapshot:{_slug(top_emp)}:{_slug(dept)}:{today.isoformat()}:higher",
            )
        )

    if len(cards) >= max_items:
        return cards

    # --- High spread signal (group-level) ---
    if spread_pct >= 25.0:
        dept_set: set[str] = {_dept(row) for row in rows_with_uph}
        process_note = (
            f" Spread is visible across {len(dept_set)} process(es)."
            if len(dept_set) > 1
            else ""
        )
        cards.append(
            TodayQueueCardViewModel(
                employee_id="",
                process_id="Group",
                state="CURRENT",
                line_1="Group · Today's snapshot",
                line_2="Wide performance spread today",
                line_3=(
                    f"Surfaced because the group UPH range spans {spread_pct:.0f}% "
                    f"({min_uph:.1f} to {max_uph:.1f} UPH).{process_note} "
                    "Early signal — no multi-day trend available yet."
                ),
                line_4="Confidence: Low · Today's snapshot",
                line_5=f"Evidence basis: {group_count} employee(s) in today's snapshot.",
                expanded_lines=[
                    f"Lowest today: {min_uph:.1f} UPH",
                    f"Highest today: {max_uph:.1f} UPH",
                    f"Median today: {median_uph:.1f} UPH",
                    f"Spread: {spread_pct:.0f}% range across {group_count} employee(s).",
                    "Wide spread can reflect uneven workload, process mix, or import variability. No trend comparison is available yet.",
                ],
                freshness_line="Freshness: Current shift/day snapshot",
                signal_key=f"today-snapshot:group:all:{today.isoformat()}:spread",
            )
        )

    return cards[:max_items]
