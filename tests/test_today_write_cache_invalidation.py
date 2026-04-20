from contextlib import contextmanager
from datetime import date, datetime

import pages.today as today_module

from pages.today import _get_today_more_actions_optional_data, _render_guided_completion_controls
from services.today_view_model_service import TodayQueueCardViewModel


@contextmanager
def _noop_ctx(*args, **kwargs):
    yield


def _card() -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id="E1",
        process_id="Packing",
        state="CURRENT",
        line_1="Alex · Packing",
        line_2="Below expected pace",
        line_3="",
        line_4="",
        line_5="Confidence: Medium",
        signal_key="today-signal:e1:packing:below_expected:stable_trend:2026-04-19",
        expanded_lines=[],
    )


def _card_for(signal_key: str, employee_id: str, process_id: str = "Packing") -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id=employee_id,
        process_id=process_id,
        state="CURRENT",
        line_1=f"{employee_id} · {process_id}",
        line_2="Below expected pace",
        line_3="",
        line_4="",
        line_5="Confidence: Medium",
        signal_key=signal_key,
        expanded_lines=[],
    )


def test_signal_status_write_invalidates_today_caches(monkeypatch):
    async_calls = {"count": 0}
    log_events: list[dict] = []

    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("pages.today.st.text_area", lambda *_args, **_kwargs: "Completed review details")
    monkeypatch.setattr("pages.today.st.selectbox", lambda *_args, **_kwargs: "No")
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.st.session_state", {"tenant_id": "tenant-a", "user_email": "lead@example.com"})
    monkeypatch.setattr("pages.today._render_today_more_actions_fragment", lambda **_kwargs: None)
    monkeypatch.setattr(
        "pages.today._start_today_completion_write_async",
        lambda **_kwargs: async_calls.__setitem__("count", async_calls["count"] + 1),
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *args, **kwargs: log_events.append({"args": args, "kwargs": kwargs}))
    monkeypatch.setattr("pages.today.st.rerun", lambda: None)

    _render_guided_completion_controls(card=_card(), key_prefix="sig", status_map={})

    assert async_calls["count"] == 1
    completed = list(today_module.st.session_state.get("_today_completed_items") or [])
    assert any(str(item or "").startswith("signal:today-signal:e1:packing") for item in completed)
    assert len(list(today_module.st.session_state.get("_today_pending_completion_ids") or [])) == 1
    assert any(str((entry.get("kwargs") or {}).get("context", {}).get("click_to_ui_update_ms", "")).strip() != "" for entry in log_events)


def test_more_actions_optional_data_is_cached_per_card(monkeypatch):
    service_calls = {"count": 0}

    def _list_open_operational_exceptions(**_kwargs):
        service_calls["count"] += 1
        return [{"id": "ex-12345678", "summary": "Scanner outage"}]

    monkeypatch.setattr("pages.today.list_open_operational_exceptions", _list_open_operational_exceptions)
    monkeypatch.setattr("pages.today.st.session_state", {})

    first = _get_today_more_actions_optional_data(card=_card(), tenant_id="tenant-a")
    second = _get_today_more_actions_optional_data(card=_card(), tenant_id="tenant-a")

    assert service_calls["count"] == 1
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["exception_options"]["#ex-12345 - Scanner outage"] == "ex-12345678"


def test_duplicate_click_same_signal_is_prevented(monkeypatch):
    async_calls = {"count": 0}
    events: list[str] = []

    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("pages.today.st.text_area", lambda *_args, **_kwargs: "Completed review details")
    monkeypatch.setattr("pages.today.st.selectbox", lambda *_args, **_kwargs: "No")
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today._render_today_more_actions_fragment", lambda **_kwargs: None)
    monkeypatch.setattr(
        "pages.today._start_today_completion_write_async",
        lambda **_kwargs: async_calls.__setitem__("count", async_calls["count"] + 1),
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda event, **_kwargs: events.append(str(event)))
    monkeypatch.setattr("pages.today.st.rerun", lambda: None)
    monkeypatch.setattr("pages.today.st.session_state", {"tenant_id": "tenant-a", "user_email": "lead@example.com"})

    card = _card()
    today_module._render_guided_completion_controls(card=card, key_prefix="sig", status_map={})
    today_module._render_guided_completion_controls(card=card, key_prefix="sig", status_map={})

    assert async_calls["count"] == 1
    assert "today_mark_complete_duplicate_prevented" in events
    assert len(list(today_module.st.session_state.get("_today_pending_completion_ids") or [])) == 1


def test_two_rapid_completions_enqueue_independently(monkeypatch):
    async_calls = {"count": 0}

    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("pages.today.st.text_area", lambda *_args, **_kwargs: "Completed review details")
    monkeypatch.setattr("pages.today.st.selectbox", lambda *_args, **_kwargs: "No")
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today._render_today_more_actions_fragment", lambda **_kwargs: None)
    monkeypatch.setattr(
        "pages.today._start_today_completion_write_async",
        lambda **_kwargs: async_calls.__setitem__("count", async_calls["count"] + 1),
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.st.rerun", lambda: None)
    monkeypatch.setattr("pages.today.st.session_state", {"tenant_id": "tenant-a", "user_email": "lead@example.com"})

    card1 = _card_for("today-signal:e1:packing:below_expected:stable_trend:2026-04-19", "E1")
    card2 = _card_for("today-signal:e2:packing:below_expected:stable_trend:2026-04-19", "E2")

    today_module._render_guided_completion_controls(card=card1, key_prefix="sig1", status_map={})
    today_module._render_guided_completion_controls(card=card2, key_prefix="sig2", status_map={})

    assert async_calls["count"] == 2
    assert len(list(today_module.st.session_state.get("_today_pending_completion_ids") or [])) == 2
    assert len(list(today_module.st.session_state.get("_today_pending_completion_signal_keys") or [])) == 2


def test_out_of_order_async_results_do_not_corrupt_pending_state(monkeypatch):
    pending1 = "c1"
    pending2 = "c2"
    card1 = _card_for("sig-1", "E1")
    card2 = _card_for("sig-2", "E2")

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "tenant_id": "tenant-a",
            "user_email": "lead@example.com",
            "_today_pending_completion_ids": [pending1, pending2],
            "_today_pending_completion_signal_keys": ["sig-1", "sig-2"],
            "_today_pending_completion_meta": {
                pending1: {
                    "signal_id": "sig-1",
                    "clicked_at": float(1.0),
                    "queue_update_ms": 1,
                    "click_to_ui_update_ms": 1,
                    "card_session_key": today_module._today_card_session_key(card1),
                    "card": today_module.dataclasses.asdict(card1),
                },
                pending2: {
                    "signal_id": "sig-2",
                    "clicked_at": float(1.0),
                    "queue_update_ms": 1,
                    "click_to_ui_update_ms": 1,
                    "card_session_key": today_module._today_card_session_key(card2),
                    "card": today_module.dataclasses.asdict(card2),
                },
            },
            "_today_completed_items": [
                today_module._today_card_session_key(card1),
                today_module._today_card_session_key(card2),
            ],
        },
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)

    with today_module._TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        today_module._TODAY_COMPLETION_ASYNC_RESULTS.clear()
        today_module._TODAY_COMPLETION_ASYNC_RESULTS[pending2] = {"status": "success", "backend_write_ms": 4, "error": ""}

    today_module._drain_today_async_completion_results()
    assert list(today_module.st.session_state.get("_today_pending_completion_ids") or []) == [pending1]
    assert list(today_module.st.session_state.get("_today_pending_completion_signal_keys") or []) == ["sig-1"]

    with today_module._TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        today_module._TODAY_COMPLETION_ASYNC_RESULTS[pending1] = {"status": "success", "backend_write_ms": 5, "error": ""}

    today_module._drain_today_async_completion_results()
    assert list(today_module.st.session_state.get("_today_pending_completion_ids") or []) == []
    assert list(today_module.st.session_state.get("_today_pending_completion_signal_keys") or []) == []


def test_rollback_restores_signal_and_inputs_without_duplicates(monkeypatch):
    card = _card_for("sig-rollback", "E9")
    note_key = "note_key"
    follow_up_key = "follow_up_key"
    due_date_key = "due_date_key"
    due_time_key = "due_time_key"
    card_session_key = today_module._today_card_session_key(card)

    queue_item = {
        "signal_key": "sig-rollback",
        "employee_id": "E9",
        "process": "Packing",
        "_queue_status": "due_today",
    }

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "tenant_id": "tenant-a",
            "user_email": "lead@example.com",
            "_today_precomputed_payload": {"queue_items": []},
            "_today_completed_items": [card_session_key],
            "_today_pending_completion_ids": ["c-rollback"],
            "_today_pending_completion_signal_keys": ["sig-rollback"],
            "_today_pending_completion_meta": {
                "c-rollback": {
                    "signal_id": "sig-rollback",
                    "clicked_at": float(1.0),
                    "queue_update_ms": 1,
                    "click_to_ui_update_ms": 1,
                    "card_session_key": card_session_key,
                    "card": today_module.dataclasses.asdict(card),
                    "removed_queue_items": [queue_item],
                    "removed_insert_index": 0,
                    "note_key": note_key,
                    "follow_up_key": follow_up_key,
                    "due_date_key": due_date_key,
                    "due_time_key": due_time_key,
                    "note_text": "retry note",
                    "follow_up_choice": "Yes",
                    "follow_up_at": datetime(2026, 4, 21, 9, 0),
                }
            },
            note_key: "",
            follow_up_key: "Select one",
        },
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)

    with today_module._TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        today_module._TODAY_COMPLETION_ASYNC_RESULTS.clear()
        today_module._TODAY_COMPLETION_ASYNC_RESULTS["c-rollback"] = {"status": "failed", "backend_write_ms": 3, "error": "boom"}

    today_module._drain_today_async_completion_results()

    queue_items = list((today_module.st.session_state.get("_today_precomputed_payload") or {}).get("queue_items") or [])
    assert len(queue_items) == 1
    assert str(queue_items[0].get("signal_key") or "") == "sig-rollback"
    assert card_session_key not in list(today_module.st.session_state.get("_today_completed_items") or [])
    assert str(today_module.st.session_state.get(note_key) or "") == "retry note"
    assert str(today_module.st.session_state.get(follow_up_key) or "") == "Yes"
    assert list(today_module.st.session_state.get("_today_pending_completion_ids") or []) == []


def test_pending_signal_is_not_rendered_during_rerun(monkeypatch):
    card = _card_for("sig-pending-hide", "E4")
    plan = today_module.TodayQueueRenderPlan(
        section_title="Today",
        weak_data_note="",
        start_note="",
        primary_cards=[card],
        secondary_cards=[],
        primary_placeholder="",
        secondary_caption="",
        secondary_expanded=False,
        suppressed_debug_rows=[],
    )

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "_today_completed_items": [],
            "_today_pending_completion_signal_keys": ["sig-pending-hide"],
        },
    )

    prepared = today_module._prepare_today_top_queue_render(
        plan=plan,
        tenant_id="tenant-a",
        today_value=today_module.date(2026, 4, 20),
    )

    assert list(prepared.get("active_ranked_cards") or []) == []


def test_note_text_survives_harmless_rerun(monkeypatch):
    card = _card_for("sig-note-stable", "E11")
    signal_id = today_module._today_card_signal_id(card)
    note_key = today_module._today_completion_widget_key(signal_id=signal_id, field="note")
    observed_keys: list[str] = []

    session_state = {
        "tenant_id": "tenant-a",
        "user_email": "lead@example.com",
        note_key: "persist me",
    }

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("pages.today.st.selectbox", lambda *_args, **_kwargs: "No")
    monkeypatch.setattr("pages.today._render_today_more_actions_fragment", lambda **_kwargs: None)

    def _text_area(_label, *, key, **_kwargs):
        observed_keys.append(str(key))
        return str(session_state.get(key) or "")

    monkeypatch.setattr("pages.today.st.text_area", _text_area)

    today_module._render_guided_completion_controls(card=card, key_prefix="p0", status_map={})
    today_module._render_guided_completion_controls(card=card, key_prefix="p1", status_map={})

    assert str(session_state.get(note_key) or "") == "persist me"
    assert observed_keys == [note_key, note_key]


def test_follow_up_selection_survives_harmless_rerun(monkeypatch):
    card = _card_for("sig-followup-stable", "E12")
    signal_id = today_module._today_card_signal_id(card)
    follow_up_key = today_module._today_completion_widget_key(signal_id=signal_id, field="follow_up_needed")
    due_date_key = today_module._today_completion_widget_key(signal_id=signal_id, field="follow_up_date")
    due_time_key = today_module._today_completion_widget_key(signal_id=signal_id, field="follow_up_time")
    session_state = {
        "tenant_id": "tenant-a",
        "user_email": "lead@example.com",
        follow_up_key: "Yes",
        due_date_key: today_module.date(2026, 4, 21),
        due_time_key: today_module.dt_time(9, 0),
    }

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("pages.today.st.text_area", lambda *_args, **_kwargs: "keep")
    monkeypatch.setattr("pages.today.st.date_input", lambda *_args, **_kwargs: session_state[due_date_key])
    monkeypatch.setattr("pages.today.st.time_input", lambda *_args, **_kwargs: session_state[due_time_key])
    monkeypatch.setattr("pages.today._render_today_more_actions_fragment", lambda **_kwargs: None)

    def _selectbox(_label, *, key, **_kwargs):
        return str(session_state.get(key) or "Select one")

    monkeypatch.setattr("pages.today.st.selectbox", _selectbox)

    today_module._render_guided_completion_controls(card=card, key_prefix="p0", status_map={})
    today_module._render_guided_completion_controls(card=card, key_prefix="p1", status_map={})

    assert str(session_state.get(follow_up_key) or "") == "Yes"
    assert session_state.get(due_date_key) == today_module.date(2026, 4, 21)
    assert session_state.get(due_time_key) == today_module.dt_time(9, 0)


def test_top3_promotion_does_not_remap_inputs_between_cards(monkeypatch):
    card_a = _card_for("sig-a", "EA")
    card_b = _card_for("sig-b", "EB")
    key_a = today_module._today_completion_widget_key(signal_id=today_module._today_card_signal_id(card_a), field="note")
    key_b = today_module._today_completion_widget_key(signal_id=today_module._today_card_signal_id(card_b), field="note")
    seen: list[str] = []

    session_state = {
        "tenant_id": "tenant-a",
        "user_email": "lead@example.com",
        key_a: "note A",
        key_b: "note B",
    }

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("pages.today.st.selectbox", lambda *_args, **_kwargs: "No")
    monkeypatch.setattr("pages.today._render_today_more_actions_fragment", lambda **_kwargs: None)

    def _text_area(_label, *, key, **_kwargs):
        seen.append(str(key))
        return str(session_state.get(key) or "")

    monkeypatch.setattr("pages.today.st.text_area", _text_area)

    today_module._render_guided_completion_controls(card=card_a, key_prefix="today_attention_primary_0_complete", status_map={})
    today_module._render_guided_completion_controls(card=card_b, key_prefix="today_attention_primary_1_complete", status_map={})
    # Simulate promotion: card_b moves into primary_0 slot on rerun.
    today_module._render_guided_completion_controls(card=card_b, key_prefix="today_attention_primary_0_complete", status_map={})

    assert seen == [key_a, key_b, key_b]
    assert str(session_state.get(key_a) or "") == "note A"
    assert str(session_state.get(key_b) or "") == "note B"


def test_refresh_interaction_gate_detects_active_editing(monkeypatch):
    card = _card_for("sig-refresh", "ER")
    signal_id = today_module._today_card_signal_id(card)
    note_key = today_module._today_completion_widget_key(signal_id=signal_id, field="note")

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            note_key: "typing",
            "_today_pending_completion_ids": ["c1"],
            "today_more_actions_open_abc123": True,
        },
    )

    active, reasons = today_module._today_has_active_interaction_state()

    assert active is True
    assert "text_input" in reasons
    assert "pending_completion" in reasons
    assert "more_actions_open" in reasons


def test_stale_widget_state_cleanup_preserves_active_card_keys(monkeypatch):
    active_signal = "sig-active"
    stale_signal = "sig-stale"
    active_note = today_module._today_completion_widget_key(signal_id=active_signal, field="note")
    stale_note = today_module._today_completion_widget_key(signal_id=stale_signal, field="note")
    active_toggle = f"today_more_actions_open_{today_module._today_signal_scope_token(active_signal)}"
    stale_toggle = f"today_more_actions_open_{today_module._today_signal_scope_token(stale_signal)}"

    session_state = {
        "tenant_id": "tenant-a",
        "user_email": "lead@example.com",
        active_note: "keep",
        stale_note: "drop",
        active_toggle: True,
        stale_toggle: True,
        "_today_pending_completion_signal_keys": [],
    }
    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)

    removed = today_module._cleanup_today_widget_state(active_signal_ids={active_signal})

    assert removed >= 2
    assert active_note in session_state
    assert active_toggle in session_state
    assert stale_note not in session_state
    assert stale_toggle not in session_state


def test_first_entry_triggers_initial_load_refresh(monkeypatch):
    calls = {"recovery": 0}
    events: list[str] = []
    today_value = date(2026, 4, 20)

    monkeypatch.setattr("pages.today.st.session_state", {"tenant_id": "tenant-a", "user_email": "lead@example.com"})
    monkeypatch.setattr("pages.today._should_auto_refresh_signals", lambda: False)
    monkeypatch.setattr("pages.today._today_has_active_interaction_state", lambda: (False, []))
    monkeypatch.setattr(
        "pages.today._attempt_signal_payload_recovery",
        lambda **_kwargs: calls.__setitem__("recovery", calls["recovery"] + 1) or True,
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda event, **_kwargs: events.append(str(event)))

    outcome = today_module._run_today_auto_refresh(tenant_id="tenant-a", today_value=today_value)

    assert calls["recovery"] == 1
    assert outcome.get("initial_load_attempted") is True
    assert "today_initial_load_started" in events


def test_first_entry_not_blocked_by_refresh_throttle(monkeypatch):
    calls = {"recovery": 0}
    now_ts = float(today_module.time.time())
    today_value = date(2026, 4, 20)

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "tenant_id": "tenant-a",
            "user_email": "lead@example.com",
            "last_refresh": now_ts,
        },
    )
    monkeypatch.setattr("pages.today._should_auto_refresh_signals", lambda: False)
    monkeypatch.setattr("pages.today._today_has_active_interaction_state", lambda: (False, []))
    monkeypatch.setattr(
        "pages.today._attempt_signal_payload_recovery",
        lambda **_kwargs: calls.__setitem__("recovery", calls["recovery"] + 1) or True,
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)

    outcome = today_module._run_today_auto_refresh(tenant_id="tenant-a", today_value=today_value)

    assert calls["recovery"] == 1
    assert outcome.get("initial_load_attempted") is True


def test_first_entry_not_blocked_by_active_interaction_gate(monkeypatch):
    calls = {"recovery": 0}
    today_value = date(2026, 4, 20)

    monkeypatch.setattr("pages.today.st.session_state", {"tenant_id": "tenant-a", "user_email": "lead@example.com"})
    monkeypatch.setattr("pages.today._should_auto_refresh_signals", lambda: True)
    monkeypatch.setattr("pages.today._today_has_active_interaction_state", lambda: (True, ["text_input"]))
    monkeypatch.setattr(
        "pages.today._attempt_signal_payload_recovery",
        lambda **_kwargs: calls.__setitem__("recovery", calls["recovery"] + 1) or True,
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)

    outcome = today_module._run_today_auto_refresh(tenant_id="tenant-a", today_value=today_value)

    assert calls["recovery"] == 1
    assert outcome.get("active_interaction") is True
    assert outcome.get("initial_load_attempted") is True


def test_successful_initial_load_sets_session_flags(monkeypatch):
    events: list[str] = []
    today_value = date(2026, 4, 20)
    payload = {
        "queue_items": [],
        "goal_status": [],
        "import_summary": {},
        "home_sections": {},
    }
    session_state = {"tenant_id": "tenant-a", "user_email": "lead@example.com"}

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today._log_operational_event", lambda event, **_kwargs: events.append(str(event)))

    completed = today_module._finalize_today_initial_load_state(
        tenant_id="tenant-a",
        today_value=today_value,
        precomputed=payload,
    )

    assert completed is True
    assert bool(session_state.get(today_module._today_initial_load_completed_key(today_value))) is True
    assert float(session_state.get("last_refresh", 0.0) or 0.0) > 0.0
    assert bool(session_state.get("_today_last_refresh_success")) is True
    assert "today_initial_load_completed" in events


def test_first_entry_can_populate_without_second_navigation(monkeypatch):
    calls = {"recovery": 0}
    today_value = date(2026, 4, 20)
    session_state = {"tenant_id": "tenant-a", "user_email": "lead@example.com"}
    payload = {
        "queue_items": [{"employee_id": "E1"}],
        "goal_status": [{"EmployeeID": "E1"}],
        "import_summary": {"days": 1},
        "home_sections": {},
    }

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today._should_auto_refresh_signals", lambda: False)
    monkeypatch.setattr("pages.today._today_has_active_interaction_state", lambda: (False, []))
    monkeypatch.setattr(
        "pages.today._attempt_signal_payload_recovery",
        lambda **_kwargs: calls.__setitem__("recovery", calls["recovery"] + 1) or True,
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)

    first_outcome = today_module._run_today_auto_refresh(tenant_id="tenant-a", today_value=today_value)
    finalized = today_module._finalize_today_initial_load_state(
        tenant_id="tenant-a",
        today_value=today_value,
        precomputed=payload,
    )
    second_outcome = today_module._run_today_auto_refresh(tenant_id="tenant-a", today_value=today_value)

    assert calls["recovery"] == 1
    assert first_outcome.get("initial_load_attempted") is True
    assert finalized is True
    assert second_outcome.get("initial_load_completed") is True
    assert second_outcome.get("initial_load_attempted") is False


def test_first_paint_shell_shows_before_initial_payload_ready(monkeypatch):
    today_value = date(2026, 4, 20)
    monkeypatch.setattr("pages.today.st.session_state", {"_entered_from_page_key": "team"})

    should_show = today_module._today_should_show_first_paint_shell(
        entered_from_page="team",
        today_value=today_value,
    )

    assert should_show is True


def test_main_body_payload_gate_requires_valid_payload_keys():
    assert today_module._today_payload_ready_for_render(None) is False
    assert today_module._today_payload_ready_for_render({"queue_items": []}) is False
    assert (
        today_module._today_payload_ready_for_render(
            {
                "queue_items": [],
                "goal_status": [],
                "import_summary": {},
                "home_sections": {},
            }
        )
        is True
    )


def test_first_paint_shell_not_required_after_today_is_initialized(monkeypatch):
    today_value = date(2026, 4, 20)
    monkeypatch.setattr(
        "pages.today.st.session_state",
        {today_module._today_initial_load_completed_key(today_value): True},
    )

    should_show = today_module._today_should_show_first_paint_shell(
        entered_from_page="today",
        today_value=today_value,
    )

    assert should_show is False


def test_phase1_top_queue_render_limits_to_fast_top3(monkeypatch):
    cards = [_card_for(f"sig-phase1-{idx}", f"E{idx}") for idx in range(20)]
    plan = today_module.TodayQueueRenderPlan(
        section_title="Today",
        weak_data_note="",
        start_note="",
        primary_cards=cards,
        secondary_cards=[],
        primary_placeholder="",
        secondary_caption="",
        secondary_expanded=False,
        suppressed_debug_rows=[],
    )

    monkeypatch.setattr("pages.today.st.session_state", {"_today_completed_items": [], "_today_pending_completion_signal_keys": []})
    monkeypatch.setattr("pages.today._cached_today_signal_status_map", lambda **_kwargs: {})

    prepared = today_module._prepare_today_phase1_top_queue_render(
        plan=plan,
        tenant_id="tenant-a",
        today_value=today_module.date(2026, 4, 20),
    )

    assert len(list(prepared.get("top_cards") or [])) <= 3
    assert int(prepared.get("people_needing_attention") or 0) <= 3
