"""Today-home section adapter built on centralized signal interpretation helpers."""

from __future__ import annotations

from datetime import date

from domain.insight_card_contract import InsightCardContract
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
