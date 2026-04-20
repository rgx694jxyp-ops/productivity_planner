from pages import today


def test_enriched_render_plan_page_cache_set_and_get(monkeypatch):
    monkeypatch.setattr(today.st, "session_state", {})

    card = today.TodayQueueCardViewModel(
        employee_id="E1",
        process_id="P1",
        state="CURRENT",
        line_1="Employee E1",
        line_2="Observed line",
        line_3="Compared with prior",
        line_4="Data suggests",
        line_5="High confidence",
        expanded_lines=[],
    )
    plan = today.TodayQueueRenderPlan(
        section_title="Signals surfaced",
        weak_data_note="",
        start_note="",
        primary_cards=[card],
        secondary_cards=[],
        primary_placeholder="",
        secondary_caption="",
        secondary_expanded=False,
        suppressed_debug_rows=[],
    )

    fingerprint = today._today_render_plan_fingerprint(plan=plan)
    cache_key = today._enriched_render_plan_page_cache_key(
        tenant_id="tenant-a",
        today_iso="2026-04-19",
        context_day_key="2026-04-19",
        visible_employee_ids=("E1",),
        render_plan_fingerprint=fingerprint,
    )

    assert today._get_cached_enriched_render_plan_page(cache_key=cache_key) is None

    today._set_cached_enriched_render_plan_page(cache_key=cache_key, plan=plan)

    cached = today._get_cached_enriched_render_plan_page(cache_key=cache_key)
    assert cached is not None
    assert cached == plan
