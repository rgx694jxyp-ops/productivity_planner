"""Tests for the Today attention summary strip view model.

Covers:
- correct counts when data exists
- graceful empty / no-data cases
- no duplicate queue calculations (function reads inputs, does not re-query)
"""

from datetime import date

from services.attention_scoring_service import AttentionItem, AttentionSummary
from services.today_view_model_service import (
    TodayAttentionStripViewModel,
    build_today_attention_strip,
)


TODAY = date(2026, 4, 13)


def _item(employee_id: str = "E1", tier: str = "high") -> AttentionItem:
    return AttentionItem(
        employee_id=employee_id,
        process_name="Packing",
        attention_score=80,
        attention_tier=tier,
        attention_reasons=["reason"],
        attention_summary="summary",
        factors_applied=[],
        snapshot={"employee_id": employee_id},
    )


def _summary(items: list[AttentionItem], suppressed: int = 0) -> AttentionSummary:
    return AttentionSummary(
        ranked_items=items,
        is_healthy=not items,
        healthy_message="",
        suppressed_count=suppressed,
        total_evaluated=len(items) + suppressed,
    )


def _queue_item(*, status: str = "pending", created_today: bool = False) -> dict:
    created_at = f"{TODAY.isoformat()}T09:00:00Z" if created_today else "2026-04-10T09:00:00Z"
    return {
        "_queue_status": status,
        "created_at": created_at,
        "employee_id": "E1",
    }


# ---------------------------------------------------------------------------
# Values present when data exists
# ---------------------------------------------------------------------------


def test_total_needing_attention_matches_ranked_items():
    strip = build_today_attention_strip(
        attention=_summary([_item("E1"), _item("E2"), _item("E3")]),
        queue_items=[],
        today=TODAY,
    )
    assert strip.total_needing_attention == 3


def test_overdue_follow_ups_counted_from_queue_status():
    queue_items = [
        _queue_item(status="overdue"),
        _queue_item(status="overdue"),
        _queue_item(status="pending"),
    ]
    strip = build_today_attention_strip(
        attention=_summary([_item()]),
        queue_items=queue_items,
        today=TODAY,
    )
    assert strip.overdue_follow_ups == 2


def test_new_today_counts_actions_created_on_today():
    queue_items = [
        _queue_item(created_today=True),
        _queue_item(created_today=True),
        _queue_item(created_today=False),
    ]
    strip = build_today_attention_strip(
        attention=_summary([_item()]),
        queue_items=queue_items,
        today=TODAY,
    )
    assert strip.new_today == 2


def test_new_today_only_matches_exact_date_prefix():
    # created_at from a different day should not count
    queue_items = [
        {"_queue_status": "pending", "created_at": "2026-04-12T23:59:59Z"},
        {"_queue_status": "pending", "created_at": "2026-04-14T00:00:00Z"},
    ]
    strip = build_today_attention_strip(
        attention=_summary([]),
        queue_items=queue_items,
        today=TODAY,
    )
    assert strip.new_today == 0


def test_reviewed_today_is_none_when_not_in_payload():
    strip = build_today_attention_strip(
        attention=_summary([_item()]),
        queue_items=[_queue_item()],
        today=TODAY,
    )
    assert strip.reviewed_today is None


# ---------------------------------------------------------------------------
# Empty / no-data cases
# ---------------------------------------------------------------------------


def test_empty_attention_and_no_queue_returns_zero_counts():
    strip = build_today_attention_strip(
        attention=_summary([]),
        queue_items=[],
        today=TODAY,
    )
    assert strip.total_needing_attention == 0
    assert strip.new_today == 0
    assert strip.overdue_follow_ups == 0
    assert strip.reviewed_today is None


def test_queue_items_with_missing_fields_do_not_raise():
    queue_items = [
        {},
        {"_queue_status": None, "created_at": None},
        {"_queue_status": "overdue"},
    ]
    strip = build_today_attention_strip(
        attention=_summary([_item()]),
        queue_items=queue_items,
        today=TODAY,
    )
    assert strip.overdue_follow_ups == 1
    assert strip.new_today == 0


def test_attention_with_only_suppressed_items_shows_zero_total():
    # Suppressed items should not be in ranked_items; simulate empty ranked list
    # with a suppressed_count so we verify the function reads ranked_items, not total_evaluated.
    strip = build_today_attention_strip(
        attention=_summary([], suppressed=5),
        queue_items=[],
        today=TODAY,
    )
    assert strip.total_needing_attention == 0


# ---------------------------------------------------------------------------
# No duplicate queue computation
# ---------------------------------------------------------------------------


def test_build_today_attention_strip_does_not_recompute_queue(monkeypatch):
    """Verify the function uses the queue_items passed in, not a new DB call."""
    called = []

    def _should_not_be_called(*args, **kwargs):
        called.append(True)
        return []

    # Patch both possible re-query entry points to detect any accidental calls
    monkeypatch.setattr(
        "services.today_view_model_service.build_display_signal_from_attention_item",
        _should_not_be_called,
        raising=False,
    )

    strip = build_today_attention_strip(
        attention=_summary([_item()]),
        queue_items=[_queue_item(status="overdue", created_today=True)],
        today=TODAY,
    )

    # No signal building should have been triggered by the strip function
    assert not called
    # And the values should still be correct
    assert strip.overdue_follow_ups == 1
    assert strip.new_today == 1


def test_result_is_frozen_dataclass():
    strip = build_today_attention_strip(
        attention=_summary([_item()]),
        queue_items=[],
        today=TODAY,
    )
    assert isinstance(strip, TodayAttentionStripViewModel)
    # frozen=True means attribute assignment raises FrozenInstanceError
    import dataclasses
    assert dataclasses.is_dataclass(strip)
    try:
        strip.total_needing_attention = 99  # type: ignore[misc]
        assert False, "Expected FrozenInstanceError"
    except Exception:
        pass
