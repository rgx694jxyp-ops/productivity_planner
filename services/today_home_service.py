"""Today-home section adapter built on centralized signal interpretation helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

from domain.insight_card_contract import InsightCardContract
from services.attention_scoring_service import AttentionSummary, score_attention_items
from services.signal_interpretation_service import interpret_today_view_signals


def build_today_home_sections(
    *,
    queue_items: list[dict],
    goal_status: list[dict],
    import_summary: dict | None,
    today: date,
) -> dict[str, list[InsightCardContract]]:
    """Build sectioned insight cards for the Today home screen.

    Centralized interpretation logic lives in signal_interpretation_service.
    """
    return interpret_today_view_signals(
        queue_items=queue_items,
        goal_status=goal_status,
        import_summary=import_summary,
        today=today,
    )


def build_today_attention_summary(
    *,
    goal_status: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
    open_exception_rows: list[dict[str, Any]] | None = None,
    max_items: int = 10,
) -> AttentionSummary:
    """Score and rank Today screen items by attention priority.

    Accepts goal-status rows in the format returned by
    ``load_goal_status_history`` / ``snapshots_to_goal_status_rows``.
    The ``employee_id`` key is populated from ``EmployeeID`` when missing so
    that the scorer's lookup sets work correctly.

    Parameters
    ----------
    goal_status:
        Rows with keys: EmployeeID, Average UPH, Target UPH, trend,
        confidence_label, repeat_count, Department.
    queue_items:
        Open action queue items enriched with ``_queue_status``.
    open_exception_rows:
        Open operational exception rows (key: ``employee_id``).
    max_items:
        Maximum number of items to return in the ranked list.
    """
    normalized: list[dict[str, Any]] = []
    for row in goal_status or []:
        employee_id = str(row.get("EmployeeID") or row.get("employee_id") or "").strip()
        if not employee_id:
            continue
        normalized.append({**row, "employee_id": employee_id})

    return score_attention_items(
        snapshots=normalized,
        queue_items=queue_items,
        open_exception_rows=open_exception_rows,
        max_items=max_items,
    )
