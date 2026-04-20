from pages import today


def test_pre_action_render_plan_page_cache_set_and_get(monkeypatch):
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
        signal_key="sig:E1:P1",
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

    queue_fingerprint = today._today_pre_action_render_plan_input_fingerprint(
        attention=today.AttentionSummary(
            ranked_items=[],
            is_healthy=True,
            healthy_message="No important changes surfaced today.",
            suppressed_count=0,
            total_evaluated=0,
        ),
        decision_items=[],
        suppressed_cards=[],
        snapshot_cards=[],
        last_action_lookup={"E1": "Last action: yesterday"},
        today_iso="2026-04-19",
        is_stale=False,
        weak_data_mode=False,
        show_secondary_open=False,
    )
    cache_key = today._pre_action_render_plan_page_cache_key(
        tenant_id="tenant-a",
        today_iso="2026-04-19",
        context_day_key="2026-04-19",
        queue_fingerprint=queue_fingerprint,
        surface_flags="stale:0|weak:0|secondary:0",
    )

    assert today._get_cached_pre_action_render_plan_page(cache_key=cache_key) is None

    today._set_cached_pre_action_render_plan_page(cache_key=cache_key, plan=plan)

    cached = today._get_cached_pre_action_render_plan_page(cache_key=cache_key)
    assert cached is not None
    assert cached == plan
