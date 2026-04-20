from types import SimpleNamespace

import services.perf_profile as perf_profile
from pages import today
from services.attention_scoring_service import AttentionSummary


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Empty:
    def container(self):
        return _Ctx()

    def empty(self):
        return None


def test_page_today_action_state_wrapper_event_emits_when_lookup_empty(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        perf_profile,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    session_state = _SessionState({"tenant_id": "tenant-1", "today_queue_filter": "all"})
    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today.st, "columns", lambda spec: [_Ctx() for _ in range(len(spec) if isinstance(spec, list) else int(spec))])
    monkeypatch.setattr(today.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(today.st, "spinner", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr(today.st, "empty", lambda: _Empty())
    monkeypatch.setattr(today.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "expander", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr(today.st, "rerun", lambda: None)

    monkeypatch.setattr(today, "_apply_today_styles", lambda: None)
    monkeypatch.setattr(today, "render_traceability_panel", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_show_flash_message", lambda: None)
    monkeypatch.setattr(today, "_has_today_data", lambda **kwargs: True)
    monkeypatch.setattr(today, "_emit_today_loaded_with_data_once", lambda **kwargs: None)
    monkeypatch.setattr(today, "_render_top_status_area", lambda **kwargs: None)
    monkeypatch.setattr(today, "_render_return_trigger", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_render_queue_orientation_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_render_attention_summary_strip", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_render_unified_attention_queue", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_render_weekly_summary_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "build_today_attention_strip", lambda **kwargs: SimpleNamespace(cards=[]))
    monkeypatch.setattr(today, "build_today_weekly_summary_view_model", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(today, "_cached_weekly_manager_activity_summary_page", lambda **kwargs: ({}, False))

    monkeypatch.setattr(
        today,
        "build_today_surface_meaning",
        lambda **kwargs: SimpleNamespace(
            signal_mode=today.SignalMode.STABLE_SIGNAL,
            state_flags={},
            weak_data_mode=False,
            surface_state=today.TodaySurfaceState.NO_STRONG_SIGNALS,
            import_summary={},
            freshness_note="",
        ),
    )

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
    monkeypatch.setattr(today, "build_today_queue_render_plan", lambda **kwargs: plan)
    monkeypatch.setattr(today, "_cached_today_action_state_lookup_page", lambda **kwargs: ({}, False))

    precomputed = {
        "queue_items": [{"employee_id": "E1", "_queue_status": "pending", "created_at": "2026-04-18T00:00:00Z"}],
        "goal_status": [{"EmployeeID": "E1"}],
        "import_summary": {"days": 3, "trust": {"status": "valid", "confidence_score": 90}},
        "home_sections": {"suppressed_signals": []},
        "attention_summary": AttentionSummary(
            ranked_items=[],
            is_healthy=True,
            healthy_message="No important changes surfaced today.",
            suppressed_count=0,
            total_evaluated=0,
        ),
        "as_of_date": "2026-04-19",
        "decision_items": [],
    }
    monkeypatch.setattr(today, "get_today_signals", lambda **kwargs: precomputed)

    today.page_today()

    wrapper_context = {}
    for event_type, payload in events:
        if event_type != "perf_profile":
            continue
        if str(payload.get("detail") or "") != "today.action_state_wrapper":
            continue
        wrapper_context = dict(payload.get("context") or {})

    assert wrapper_context
    assert "duration_ms" in wrapper_context
    assert "stage_build_action_state_context_ms" in wrapper_context
    assert "stage_action_state_lookup_call_ms" in wrapper_context
    assert wrapper_context.get("lookup_rows_count") == 0
