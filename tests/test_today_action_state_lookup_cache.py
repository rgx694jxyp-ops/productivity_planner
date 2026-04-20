from datetime import date

from pages import today
from services.today_page_meaning_service import TodayQueueRenderPlan
from services.today_view_model_service import TodayQueueCardViewModel


def _card(employee_id: str) -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id=employee_id,
        process_id="Pick",
        state="PATTERN",
        line_1="Emp",
        line_2="Signal",
        line_3="",
        line_4="",
        line_5="",
        expanded_lines=[],
    )


def test_action_state_page_cache_hits_on_repeated_lookup(monkeypatch):
    monkeypatch.setattr(today.st, "session_state", {})

    calls = {"count": 0}

    def _fake_cached_lookup(*, tenant_id: str, employee_ids: tuple[str, ...], today_iso: str):
        calls["count"] += 1
        return {employee_ids[0]: {"state": "Open"}}

    monkeypatch.setattr(today, "_cached_today_action_state_lookup", _fake_cached_lookup)

    first, first_hit = today._cached_today_action_state_lookup_page(
        tenant_id="tenant-a",
        employee_ids=("E1",),
        today_iso="2026-04-19",
    )
    second, second_hit = today._cached_today_action_state_lookup_page(
        tenant_id="tenant-a",
        employee_ids=("E1",),
        today_iso="2026-04-19",
    )

    assert first_hit is False
    assert second_hit is True
    assert calls["count"] == 1
    assert first == second


def test_action_state_actionable_card_count_respects_visible_scope():
    plan = TodayQueueRenderPlan(
        section_title="Queue",
        weak_data_note="",
        start_note="",
        primary_cards=[_card("E1"), _card("E2")],
        secondary_cards=[_card("E3"), _card("E4")],
        primary_placeholder="",
        secondary_caption="Other",
        secondary_expanded=False,
        suppressed_debug_rows=[],
    )

    hidden_secondary_count = today._today_action_state_actionable_card_count(plan=plan)
    assert hidden_secondary_count == 2

    expanded_plan = TodayQueueRenderPlan(
        section_title=plan.section_title,
        weak_data_note=plan.weak_data_note,
        start_note=plan.start_note,
        primary_cards=list(plan.primary_cards),
        secondary_cards=list(plan.secondary_cards),
        primary_placeholder=plan.primary_placeholder,
        secondary_caption=plan.secondary_caption,
        secondary_expanded=True,
        suppressed_debug_rows=list(plan.suppressed_debug_rows),
    )
    visible_secondary_count = today._today_action_state_actionable_card_count(plan=expanded_plan)
    assert visible_secondary_count == 4
