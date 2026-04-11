"""Deterministic attention scoring for Today screen prioritization.

Score model (base = 50, capped 0–100):

  Factor                        Points
  ─────────────────────────────────────
  Trend: declining               +25
  Trend: below_expected          +15
  Trend: inconsistent            +10
  Trend: improving                +5
  Repeat pattern ≥ 3             +20
  Repeat pattern = 2             +10
  Repeat pattern = 1              +5
  Overdue follow-up              +20
  Due-today follow-up            +10
  Open exception                 +15
  Variance > 20 % from expected  +15
  Variance 10–19 % from expected  +8
  Confidence high                +10
  Confidence low                 −20
  Completeness complete           +5
  Completeness partial            −5
  Completeness limited           −15

Tier thresholds:
  high        ≥ 75
  medium      50–74
  low         30–49
  suppressed  < 30

Items below the suppression floor are excluded from the ranked list unless
keep_low=True is passed.

Input rows accept either daily-snapshot format (keys: employee_id, trend_state,
confidence_label, data_completeness_status, recent_average_uph, expected_uph,
repeat_count) or goal-status format (keys: EmployeeID, trend, Average UPH,
Target UPH, confidence_label, repeat_count, Department).  Both are handled
natively; the caller does not need to pre-normalise.

This service is descriptive only.  It classifies what the data shows and does
not prescribe what a manager should do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.trend_classification_service import normalize_trend_state

# ---------------------------------------------------------------------------
# Factor weights
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, int] = {
    "trend_declining": 25,
    "trend_below_expected": 15,
    "trend_inconsistent": 10,
    "trend_improving": 5,
    "repeat_3_or_more": 20,
    "repeat_2": 10,
    "repeat_1": 5,
    "overdue_followup": 20,
    "due_today_followup": 10,
    "open_exception": 15,
    "variance_over_20pct": 15,
    "variance_10_to_20pct": 8,
    "confidence_high": 10,
    "confidence_low": -20,
    "completeness_complete": 5,
    "completeness_partial": -5,
    "completeness_limited": -15,
}

_BASE_SCORE = 50
_SUPPRESSION_FLOOR = 30
_HIGH_FLOOR = 75
_MEDIUM_FLOOR = 50


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttentionFactor:
    """A single factor that contributed to an attention score."""

    key: str
    weight: int
    plain_reason: str


@dataclass(frozen=True)
class AttentionItem:
    """Scored and explained attention entry for one employee/process snapshot."""

    employee_id: str
    process_name: str
    attention_score: int          # 0–100
    attention_tier: str           # "high" | "medium" | "low" | "suppressed"
    attention_reasons: list[str]  # plain-language reasons, positive first
    attention_summary: str        # one-sentence "why shown" copy
    factors_applied: list[AttentionFactor]
    snapshot: dict[str, Any]      # source row for drill-down


@dataclass(frozen=True)
class AttentionSummary:
    """Ranked attention list and healthy-state indicator for the Today screen."""

    ranked_items: list[AttentionItem]
    is_healthy: bool
    healthy_message: str
    suppressed_count: int
    total_evaluated: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tier(score: int) -> str:
    if score >= _HIGH_FLOOR:
        return "high"
    if score >= _MEDIUM_FLOOR:
        return "medium"
    if score >= _SUPPRESSION_FLOOR:
        return "low"
    return "suppressed"


def _score_one(
    snapshot: dict[str, Any],
    *,
    overdue_ids: set[str],
    due_today_ids: set[str],
    open_exception_ids: set[str],
) -> tuple[int, list[AttentionFactor]]:
    """Apply all factor rules deterministically and return (raw_score, factors)."""
    factors: list[AttentionFactor] = []
    employee_id = str(snapshot.get("employee_id") or snapshot.get("EmployeeID") or "").strip()

    # --- trend ---
    trend_raw = snapshot.get("trend_state") or snapshot.get("trend") or "insufficient_data"
    trend_state = normalize_trend_state(trend_raw)
    if trend_state == "declining":
        factors.append(AttentionFactor("trend_declining", _WEIGHTS["trend_declining"], "Trend has been declining"))
    elif trend_state == "below_expected":
        factors.append(AttentionFactor("trend_below_expected", _WEIGHTS["trend_below_expected"], "Consistently below expected pace"))
    elif trend_state == "inconsistent":
        factors.append(AttentionFactor("trend_inconsistent", _WEIGHTS["trend_inconsistent"], "Performance has been inconsistent"))
    elif trend_state == "improving":
        factors.append(AttentionFactor("trend_improving", _WEIGHTS["trend_improving"], "Performance is improving"))

    # --- repeat pattern ---
    repeat_count = _safe_int(snapshot.get("repeat_count"))
    if repeat_count >= 3:
        factors.append(AttentionFactor("repeat_3_or_more", _WEIGHTS["repeat_3_or_more"], f"Same pattern seen {repeat_count} times"))
    elif repeat_count == 2:
        factors.append(AttentionFactor("repeat_2", _WEIGHTS["repeat_2"], "Pattern seen twice recently"))
    elif repeat_count == 1:
        factors.append(AttentionFactor("repeat_1", _WEIGHTS["repeat_1"], "Pattern seen once recently"))

    # --- follow-up status ---
    if employee_id in overdue_ids:
        factors.append(AttentionFactor("overdue_followup", _WEIGHTS["overdue_followup"], "Has an overdue follow-up"))
    elif employee_id in due_today_ids:
        factors.append(AttentionFactor("due_today_followup", _WEIGHTS["due_today_followup"], "Has a follow-up due today"))

    # --- open exception ---
    if employee_id in open_exception_ids:
        factors.append(AttentionFactor("open_exception", _WEIGHTS["open_exception"], "Has an unresolved operational exception"))

    # --- variance from expected ---
    # Accept both snapshot keys (expected_uph / recent_average_uph) and goal-status keys (Target UPH / Average UPH)
    raw_target = snapshot.get("expected_uph")
    if raw_target is None or _safe_float(raw_target) <= 0:
        raw_target = snapshot.get("Target UPH")
    raw_recent = snapshot.get("recent_average_uph")
    if raw_recent is None or _safe_float(raw_recent) <= 0:
        raw_recent = snapshot.get("Average UPH")

    expected_uph = _safe_float(raw_target)
    recent_uph = _safe_float(raw_recent)
    if expected_uph > 0 and recent_uph > 0:
        variance_pct = abs(recent_uph - expected_uph) / expected_uph
        if variance_pct >= 0.20:
            factors.append(AttentionFactor("variance_over_20pct", _WEIGHTS["variance_over_20pct"], f"Output is {variance_pct:.0%} from expected pace"))
        elif variance_pct >= 0.10:
            factors.append(AttentionFactor("variance_10_to_20pct", _WEIGHTS["variance_10_to_20pct"], f"Output is {variance_pct:.0%} from expected pace"))

    # --- confidence ---
    confidence_label = str(snapshot.get("confidence_label") or "low").strip().lower()
    if confidence_label == "high":
        factors.append(AttentionFactor("confidence_high", _WEIGHTS["confidence_high"], "High-confidence signal"))
    elif confidence_label not in {"high", "medium"}:
        factors.append(AttentionFactor("confidence_low", _WEIGHTS["confidence_low"], "Low confidence — limited data coverage"))

    # --- completeness ---
    completeness = str(
        snapshot.get("data_completeness_status") or snapshot.get("completeness") or "limited"
    ).strip().lower()
    if completeness == "complete":
        factors.append(AttentionFactor("completeness_complete", _WEIGHTS["completeness_complete"], "Data coverage is complete"))
    elif completeness == "partial":
        factors.append(AttentionFactor("completeness_partial", _WEIGHTS["completeness_partial"], "Data coverage is partial"))
    else:
        factors.append(AttentionFactor("completeness_limited", _WEIGHTS["completeness_limited"], "Data coverage is limited"))

    raw_score = _BASE_SCORE + sum(f.weight for f in factors)
    return max(0, min(100, raw_score)), factors


def _build_explanation(
    score: int,
    factors: list[AttentionFactor],
    snapshot: dict[str, Any],
) -> tuple[list[str], str]:
    """Return (reasons_list, one_sentence_summary)."""
    employee_id = str(snapshot.get("employee_id") or snapshot.get("EmployeeID") or "")
    process_name = str(snapshot.get("process_name") or snapshot.get("Department") or "")
    process_label = f" ({process_name})" if process_name and process_name.lower() not in {"", "unassigned"} else ""

    positive = [f.plain_reason for f in factors if f.weight > 0]
    negative = [f.plain_reason for f in factors if f.weight < 0]
    reasons = positive + negative

    if not positive:
        summary = f"{employee_id}{process_label} — no strong signals currently."
    elif score >= _HIGH_FLOOR:
        summary = f"{employee_id}{process_label} — ranked highly: {positive[0].lower()}."
    elif score >= _MEDIUM_FLOOR:
        summary = f"{employee_id}{process_label} — worth monitoring: {positive[0].lower()}."
    else:
        summary = f"{employee_id}{process_label} — low-priority signal."

    return reasons, summary


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_attention_items(
    *,
    snapshots: list[dict[str, Any]],
    queue_items: list[dict[str, Any]] | None = None,
    open_exception_rows: list[dict[str, Any]] | None = None,
    keep_low: bool = False,
    max_items: int | None = None,
) -> AttentionSummary:
    """Score and rank snapshot rows for Today screen attention prioritization.

    Parameters
    ----------
    snapshots:
        Per-employee performance rows.  Accepts daily-snapshot format or
        goal-status format — both key variants are handled natively.
    queue_items:
        Open action queue items; used to detect overdue / due-today
        follow-ups.  Expected keys: ``employee_id``, ``_queue_status``.
    open_exception_rows:
        Open operational exception rows used to flag unresolved context.
        Expected key: ``employee_id``.
    keep_low:
        When True, suppressed items are appended at the bottom of the list.
    max_items:
        Optional cap on returned list length.
    """
    queue_items = list(queue_items or [])
    open_exception_rows = list(open_exception_rows or [])

    overdue_ids: set[str] = {
        str(item.get("employee_id") or "").strip()
        for item in queue_items
        if str(item.get("_queue_status") or "") == "overdue"
        and str(item.get("employee_id") or "").strip()
    }
    due_today_ids: set[str] = (
        {
            str(item.get("employee_id") or "").strip()
            for item in queue_items
            if str(item.get("_queue_status") or "") == "due_today"
            and str(item.get("employee_id") or "").strip()
        }
        - overdue_ids
    )
    open_exception_ids: set[str] = {
        str(row.get("employee_id") or "").strip()
        for row in open_exception_rows
        if str(row.get("employee_id") or "").strip()
    }

    ranked_pairs: list[tuple[int, AttentionItem]] = []
    suppressed_pairs: list[tuple[int, AttentionItem]] = []

    for snapshot in snapshots or []:
        employee_id = str(snapshot.get("employee_id") or snapshot.get("EmployeeID") or "").strip()
        if not employee_id:
            continue

        raw_score, factors = _score_one(
            snapshot,
            overdue_ids=overdue_ids,
            due_today_ids=due_today_ids,
            open_exception_ids=open_exception_ids,
        )
        tier = _tier(raw_score)
        reasons, summary = _build_explanation(raw_score, factors, snapshot)

        item = AttentionItem(
            employee_id=employee_id,
            process_name=str(snapshot.get("process_name") or snapshot.get("Department") or ""),
            attention_score=raw_score,
            attention_tier=tier,
            attention_reasons=reasons,
            attention_summary=summary,
            factors_applied=factors,
            snapshot=snapshot,
        )
        bucket = suppressed_pairs if tier == "suppressed" else ranked_pairs
        bucket.append((raw_score, item))

    ranked_pairs.sort(key=lambda row: (-row[0], row[1].employee_id, row[1].process_name))
    if keep_low:
        suppressed_pairs.sort(key=lambda row: (-row[0], row[1].employee_id, row[1].process_name))
        ranked_pairs.extend(suppressed_pairs)

    ranked = [row[1] for row in ranked_pairs]
    if isinstance(max_items, int) and max_items > 0:
        ranked = ranked[:max_items]

    has_notable = any(item.attention_tier in {"high", "medium"} for item in ranked)
    return AttentionSummary(
        ranked_items=ranked,
        is_healthy=not has_notable,
        healthy_message="No strong signals need attention right now." if not has_notable else "",
        suppressed_count=len(suppressed_pairs),
        total_evaluated=len(snapshots or []),
    )
