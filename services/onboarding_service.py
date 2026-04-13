"""Onboarding helpers for first-import insight generation.

Builds the structured first-insight payload that is displayed on the
post-import completion screen.  The payload answers the five trust-first
questions for a user seeing interpreted data for the first time:

  - what happened
  - compared to what
  - why it is being shown
  - how confident the signal is
  - what data supports it

This service is descriptive only.  It never prescribes action.
"""

from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_first_import_insight(
    *,
    import_summary: dict[str, Any],
    goal_status: list[dict[str, Any]],
    queue_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a trust-first first-insight payload for the post-import screen.

    Parameters
    ----------
    import_summary:
        The ``_import_complete_summary`` dict set by the import pipeline.
        Required keys: emp_count, days, below, trust (dict).
    goal_status:
        Rows returned by ``snapshots_to_goal_status_rows`` or session-state
        ``goal_status``.  Accepts empty list gracefully.
    queue_items:
        Optional open action queue items used to enrich attention scoring.

    Returns
    -------
    dict with keys:
        what_happened, compared_to_what, confidence_label, confidence_score,
        confidence_basis, confidence_note, why_shown, has_targets, days,
        emp_count, below, top_item (AttentionItem | None),
        is_healthy, healthy_message.
    """
    emp_count = int(import_summary.get("emp_count") or 0)
    days = int(import_summary.get("days") or 1)
    trust = dict(import_summary.get("trust") or {})
    confidence_score = int(trust.get("confidence_score") or 0)

    # ── What happened ────────────────────────────────────────────────────────
    day_label = "today only" if days <= 1 else f"{days} days"
    emp_label = "1 employee" if emp_count == 1 else f"{emp_count} employees"
    what_happened = f"Performance data loaded for {emp_label}, covering {day_label}."

    # ── Compared to what ─────────────────────────────────────────────────────
    has_targets = any(
        _safe_float(row.get("Target UPH") or row.get("expected_uph")) > 0
        for row in (goal_status or [])
    )

    if has_targets:
        compared_to_what = "Compared against configured performance targets."
    elif days > 3:
        compared_to_what = (
            "Compared against each employee's own recent average "
            "(targets are not configured for this data yet)."
        )
    else:
        compared_to_what = (
            "Not enough history for a reliable trend baseline yet. "
            "Import a few more days to unlock trend and average comparisons."
        )

    # ── Confidence ───────────────────────────────────────────────────────────
    if confidence_score >= 75:
        confidence_label = "High"
        confidence_basis = "Most rows passed validation and are ready for reliable comparisons."
        confidence_note = ""
    elif confidence_score >= 50:
        confidence_label = "Medium"
        confidence_basis = (
            "Some rows have quality issues — comparisons are usable "
            "but should be viewed with some caution."
        )
        confidence_note = "You can continue now and review data quality details below."
    else:
        confidence_label = "Low"
        confidence_basis = "Several quality issues were found. Comparisons may shift after cleanup."
        confidence_note = "You can still continue — insights will note where confidence is limited."

    # ── Why shown ────────────────────────────────────────────────────────────
    why_shown = (
        "This is the first performance summary from your imported data, "
        "generated immediately after the pipeline completed."
    )

    # ── Top attention item ───────────────────────────────────────────────────
    top_item = None
    is_healthy = True
    healthy_message = (
        "No strong signals detected yet — "
        "add more data to build reliable trend context."
    )

    if goal_status:
        try:
            from services.attention_scoring_service import score_attention_items

            normalized = [
                {
                    **row,
                    "employee_id": str(
                        row.get("EmployeeID") or row.get("employee_id") or ""
                    ).strip(),
                }
                for row in goal_status
                if str(
                    row.get("EmployeeID") or row.get("employee_id") or ""
                ).strip()
            ]
            attention = score_attention_items(
                snapshots=normalized,
                queue_items=list(queue_items or []),
                max_items=1,
            )
            is_healthy = attention.is_healthy
            if attention.healthy_message:
                healthy_message = attention.healthy_message
            if attention.ranked_items:
                top_item = attention.ranked_items[0]
        except Exception:
            pass

    return {
        "what_happened": what_happened,
        "compared_to_what": compared_to_what,
        "confidence_label": confidence_label,
        "confidence_score": confidence_score,
        "confidence_basis": confidence_basis,
        "confidence_note": confidence_note,
        "why_shown": why_shown,
        "has_targets": has_targets,
        "days": days,
        "emp_count": emp_count,
        "below": int(import_summary.get("below") or 0),
        "top_item": top_item,
        "is_healthy": is_healthy,
        "healthy_message": healthy_message,
    }
