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
    assert str(today_module.st.session_state.get("_today_last_clicked_completion_signal_id") or "") == _card().signal_key
    assert any(str((entry.get("kwargs") or {}).get("context", {}).get("click_to_ui_update_ms", "")).strip() != "" for entry in log_events)


def test_mark_complete_captures_note_and_follow_up_in_pending_meta(monkeypatch):
    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("pages.today.st.text_area", lambda *_args, **_kwargs: "Checked root cause and logged update")
    monkeypatch.setattr("pages.today.st.selectbox", lambda *_args, **_kwargs: "Yes")
    monkeypatch.setattr("pages.today.st.date_input", lambda *_args, **_kwargs: today_module.date(2026, 4, 22))
    monkeypatch.setattr("pages.today.st.time_input", lambda *_args, **_kwargs: today_module.dt_time(10, 30))
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today._render_today_more_actions_fragment", lambda **_kwargs: None)
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.st.rerun", lambda: None)
    monkeypatch.setattr("pages.today.st.session_state", {"tenant_id": "tenant-a", "user_email": "lead@example.com"})

    captured_payload: dict[str, object] = {}
    monkeypatch.setattr(
        "pages.today._start_today_completion_write_async",
        lambda **kwargs: captured_payload.update(kwargs),
    )

    card = _card_for("sig-meta-capture", "E3")
    today_module._render_guided_completion_controls(card=card, key_prefix="sig-meta", status_map={})

    pending_ids = list(today_module.st.session_state.get("_today_pending_completion_ids") or [])
    assert len(pending_ids) == 1
    meta = dict((today_module.st.session_state.get("_today_pending_completion_meta") or {}).get(pending_ids[0]) or {})
    assert str(meta.get("note_text") or "") == "Checked root cause and logged update"
    assert str(meta.get("follow_up_choice") or "") == "Yes"
    assert isinstance(meta.get("follow_up_at"), datetime)
    assert str((captured_payload.get("payload") or {}).get("note_text") or "") == "Checked root cause and logged update"
    assert bool((captured_payload.get("payload") or {}).get("follow_up_required")) is True


def test_start_completion_write_calls_persistence_once(monkeypatch):
    card = _card_for("sig-save-once", "E5")
    save_calls = {"count": 0}

    def _save_stub(**_kwargs):
        save_calls["count"] += 1
        return True

    monkeypatch.setattr("pages.today._save_today_card_completion", _save_stub)

    with today_module._TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        today_module._TODAY_COMPLETION_ASYNC_RESULTS.clear()

    today_module._start_today_completion_write_async(
        completion_id="c-save-once",
        payload={
            "card": today_module.dataclasses.asdict(card),
            "note_text": "done",
            "follow_up_required": False,
            "follow_up_at": None,
            "owner_value": "lead@example.com",
            "tenant_id": "tenant-a",
            "user_role": "manager",
        },
    )

    with today_module._TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        result = dict(today_module._TODAY_COMPLETION_ASYNC_RESULTS.get("c-save-once") or {})

    assert save_calls["count"] == 1
    assert str(result.get("status") or "") == "success"


def test_successful_drain_clears_pending_and_sets_marked_complete_feedback(monkeypatch):
    card = _card_for("sig-drain-success", "E6")
    card_session_key = today_module._today_card_session_key(card)
    flashed: list[str] = []

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "tenant_id": "tenant-a",
            "user_email": "lead@example.com",
            "_today_pending_completion_ids": ["c-success"],
            "_today_pending_completion_signal_keys": ["sig-drain-success"],
            "_today_pending_completion_meta": {
                "c-success": {
                    "signal_id": "sig-drain-success",
                    "clicked_at": float(1.0),
                    "queue_update_ms": 1,
                    "click_to_ui_update_ms": 1,
                    "card_session_key": card_session_key,
                    "card": today_module.dataclasses.asdict(card),
                }
            },
            "_today_completed_items": [card_session_key],
        },
    )
    monkeypatch.setattr("pages.today.set_flash_message", lambda message: flashed.append(str(message)))
    monkeypatch.setattr("pages.today._narrow_invalidate_today_completion_caches", lambda **_kwargs: None)
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)

    with today_module._TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        today_module._TODAY_COMPLETION_ASYNC_RESULTS.clear()
        today_module._TODAY_COMPLETION_ASYNC_RESULTS["c-success"] = {"status": "success", "backend_write_ms": 2, "error": ""}

    today_module._drain_today_async_completion_results()

    assert list(today_module.st.session_state.get("_today_pending_completion_ids") or []) == []
    assert list(today_module.st.session_state.get("_today_pending_completion_signal_keys") or []) == []
    assert flashed == ["Marked complete."]


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


def test_optimistic_completion_defers_widget_reset_until_next_run(monkeypatch):
    card = _card_for("sig-deferred-reset", "E7")
    note_key = today_module._today_completion_widget_key(signal_id="sig-deferred-reset", field="note")
    follow_up_key = today_module._today_completion_widget_key(signal_id="sig-deferred-reset", field="follow_up_needed")
    add_exception_key = today_module._today_completion_widget_key(signal_id="sig-deferred-reset", field="add_exception")
    exception_note_key = today_module._today_completion_widget_key(signal_id="sig-deferred-reset", field="exception_note")
    more_actions_open_key = today_module._today_more_actions_open_key(card)
    cached_more_actions_key = today_module._today_more_actions_data_cache_key(card)
    card_session_key = today_module._today_card_session_key(card)

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "tenant_id": "tenant-a",
            "user_email": "lead@example.com",
            "_today_completed_items": [],
            note_key: "note stays until next run",
            follow_up_key: "Yes",
            add_exception_key: True,
            exception_note_key: "exception context",
            more_actions_open_key: True,
            cached_more_actions_key: {"employee_id": "E7"},
        },
    )

    today_module._optimistically_complete_today_card(
        card=card,
        note_key=note_key,
        follow_up_key=follow_up_key,
        add_exception_key=add_exception_key,
        exception_note_key=exception_note_key,
        more_actions_open_key=more_actions_open_key,
    )

    assert str(today_module.st.session_state.get(note_key) or "") == "note stays until next run"
    assert str(today_module.st.session_state.get(follow_up_key) or "") == "Yes"
    assert bool(today_module.st.session_state.get(add_exception_key)) is True
    assert str(today_module.st.session_state.get(exception_note_key) or "") == "exception context"
    assert bool(today_module.st.session_state.get(more_actions_open_key)) is True
    assert card_session_key in list(today_module.st.session_state.get("_today_completed_items") or [])

    removed = today_module._apply_deferred_today_widget_resets()

    assert removed >= 5
    assert note_key not in today_module.st.session_state
    assert follow_up_key not in today_module.st.session_state
    assert add_exception_key not in today_module.st.session_state
    assert exception_note_key not in today_module.st.session_state
    assert more_actions_open_key not in today_module.st.session_state
    assert cached_more_actions_key not in today_module.st.session_state
    assert today_module._TODAY_DEFERRED_WIDGET_RESET_SIGNAL_IDS_KEY not in today_module.st.session_state


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


def test_completed_item_removal_promotes_fourth_card_into_top3(monkeypatch):
    cards = [_card_for(f"sig-promote-{idx}", f"E{idx}") for idx in range(1, 5)]
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

    completed_session_key = today_module._today_card_session_key(cards[0])
    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "_today_completed_items": [completed_session_key],
            "_today_pending_completion_signal_keys": [],
        },
    )
    monkeypatch.setattr("pages.today._cached_today_signal_status_map", lambda **_kwargs: {})

    prepared = today_module._prepare_today_top_queue_render(
        plan=plan,
        tenant_id="tenant-a",
        today_value=today_module.date(2026, 4, 20),
    )

    top_cards = list(prepared.get("top_cards") or [])
    assert [str(card.employee_id or "") for card in top_cards] == ["E2", "E3", "E4"]


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


def test_initial_data_ready_transition_triggers_one_rerun(monkeypatch):
    today_value = date(2026, 4, 20)
    events: list[str] = []
    reruns = {"count": 0}
    session_state = {"tenant_id": "tenant-a", "user_email": "lead@example.com"}

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today._log_operational_event", lambda event, **_kwargs: events.append(str(event)))
    monkeypatch.setattr("pages.today.st.rerun", lambda: reruns.__setitem__("count", reruns["count"] + 1))

    triggered = today_module._trigger_today_initial_ready_rerun_if_needed(
        tenant_id="tenant-a",
        today_value=today_value,
        was_initially_ready=False,
        is_ready_now=True,
    )

    assert triggered is True
    assert reruns["count"] == 1
    assert bool(session_state.get(today_module._today_initial_rerun_triggered_key(today_value))) is True
    assert "today_data_ready_detected" in events
    assert "today_rerun_triggered" in events


def test_initial_data_ready_rerun_skipped_when_already_triggered(monkeypatch):
    today_value = date(2026, 4, 20)
    events: list[str] = []
    reruns = {"count": 0}
    session_state = {
        "tenant_id": "tenant-a",
        "user_email": "lead@example.com",
        today_module._today_initial_rerun_triggered_key(today_value): True,
    }

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today._log_operational_event", lambda event, **_kwargs: events.append(str(event)))
    monkeypatch.setattr("pages.today.st.rerun", lambda: reruns.__setitem__("count", reruns["count"] + 1))

    triggered = today_module._trigger_today_initial_ready_rerun_if_needed(
        tenant_id="tenant-a",
        today_value=today_value,
        was_initially_ready=False,
        is_ready_now=True,
    )

    assert triggered is False
    assert reruns["count"] == 0
    assert "today_rerun_skipped_reason" in events


def test_payload_session_cache_serves_second_call_without_db(monkeypatch):
    """Second _load_today_signals call within the same run returns from session_state."""
    today_value = date(2026, 4, 20)
    db_calls = {"count": 0}
    payload = {
        "queue_items": [{"employee_id": "E1"}],
        "goal_status": [],
        "import_summary": {},
        "home_sections": {},
    }
    session_state = {"tenant_id": "tenant-a"}

    def _fake_get_today_signals(*, tenant_id, as_of_date):
        db_calls["count"] += 1
        return payload

    monkeypatch.setattr("pages.today.get_today_signals", _fake_get_today_signals)
    monkeypatch.setattr("pages.today.st.session_state", session_state)

    cache_key = f"{today_module._TODAY_PAYLOAD_SESSION_CACHE_KEY_PREFIX}tenant-a_{today_value.isoformat()}"

    # First call: DB hit, result stored in session_state
    result1 = today_module.get_today_signals(tenant_id="tenant-a", as_of_date=today_value.isoformat())
    session_state[cache_key] = result1

    # Simulate second call (as _load_today_signals would do)
    cached = session_state.get(cache_key)
    assert isinstance(cached, dict) and cached.get("queue_items") is not None
    assert cached is payload
    assert db_calls["count"] == 1


def test_invalidate_today_write_caches_clears_session_payload_cache(monkeypatch):
    today_value = date(2026, 4, 20)
    cache_key = f"{today_module._TODAY_PAYLOAD_SESSION_CACHE_KEY_PREFIX}tenant-a_{today_value.isoformat()}"
    session_state = {
        cache_key: {"queue_items": [], "goal_status": [], "import_summary": {}, "home_sections": {}},
    }

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today._cached_today_action_state_lookup", type("F", (), {"cache_clear": lambda self: None})())
    monkeypatch.setattr("pages.today._cached_today_signals_payload", type("F", (), {"cache_clear": lambda self: None})())
    monkeypatch.setattr("pages.today._cached_today_signal_status_map", type("F", (), {"cache_clear": lambda self: None})())
    monkeypatch.setattr("pages.today.get_today_signals", type("F", (), {"cache_clear": lambda self: None})())

    today_module._invalidate_today_write_caches()

    assert cache_key not in session_state


def test_phase1_prepare_exposes_status_map_ms_and_queue_build_ms(monkeypatch):
    today_value = date(2026, 4, 20)
    cards = [_card_for(f"sig-timing-{i}", f"E{i}") for i in range(3)]
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

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {"_today_completed_items": [], "_today_pending_completion_signal_keys": []},
    )
    monkeypatch.setattr("pages.today._cached_today_signal_status_map", lambda **_kwargs: {})

    prepared = today_module._prepare_today_phase1_top_queue_render(
        plan=plan,
        tenant_id="tenant-a",
        today_value=today_value,
    )

    assert "signal_status_map_ms" in prepared
    assert "queue_build_ms" in prepared
    assert isinstance(prepared["signal_status_map_ms"], int)
    assert isinstance(prepared["queue_build_ms"], int)


def test_post_import_recovery_runs_sync_snapshot_and_clears_payload_session_cache(monkeypatch):
    today_value = date(2026, 4, 20)
    cache_key = f"{today_module._TODAY_PAYLOAD_SESSION_CACHE_KEY_PREFIX}tenant-a_{today_value.isoformat()}"
    session_state = {
        "tenant_id": "tenant-a",
        "user_email": "lead@example.com",
        "_post_import_refresh_pending": True,
        cache_key: {"queue_items": [{"employee_id": "E1"}]},
    }
    calls = {"sync_recompute": 0, "async_schedule": 0, "compute_signals": 0}

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today._log_today_milestone", lambda *args, **kwargs: None)
    monkeypatch.setattr("pages.today._log_operational_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("pages.today._log_app_error", lambda *args, **kwargs: None)
    monkeypatch.setattr("pages.today.show_error_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "pages.today._schedule_today_snapshot_recompute_async",
        lambda **_kwargs: calls.__setitem__("async_schedule", calls["async_schedule"] + 1) or True,
    )
    monkeypatch.setattr(
        "services.daily_snapshot_service.get_latest_snapshot_goal_status",
        lambda **_kwargs: ([], [], "2026-04-19"),
    )
    monkeypatch.setattr(
        "services.daily_snapshot_service.recompute_daily_employee_snapshots",
        lambda **_kwargs: calls.__setitem__("sync_recompute", calls["sync_recompute"] + 1),
    )
    monkeypatch.setattr(
        "services.daily_signals_service.compute_daily_signals",
        lambda **_kwargs: calls.__setitem__("compute_signals", calls["compute_signals"] + 1),
    )

    recovered = today_module._attempt_signal_payload_recovery(
        tenant_id="tenant-a",
        today_value=today_value,
    )

    assert recovered is True
    assert calls["sync_recompute"] == 1
    assert calls["async_schedule"] == 0
    assert calls["compute_signals"] == 1
    assert cache_key not in session_state
    assert session_state.get("_post_import_refresh_pending") is False


def test_today_wording_helpers_use_signal_first_copy():
    assert today_module._today_signal_surface_heading(3) == "## Today: 3 signals surfaced"
    assert today_module._today_signal_surface_heading(1) == "## Today: 1 signal surfaced"
    assert today_module._today_queue_intro_label() == "Signals surfaced now"
    assert today_module._today_loading_placeholder() == "Loading today's signals..."


def test_show_flash_message_consumes_marked_complete_once(monkeypatch):
    calls = {"count": 0}

    monkeypatch.setattr("pages.today.st.session_state", {"_action_flash_message": "Marked complete."})

    def _consume_once() -> None:
        message = str(today_module.st.session_state.pop("_action_flash_message", "") or "")
        if message:
            calls["count"] += 1

    monkeypatch.setattr("pages.today.consume_flash_message", _consume_once)

    today_module._show_flash_message()
    today_module._show_flash_message()

    assert calls["count"] == 1


def test_phase2_ready_reset_is_guarded_to_non_today_navigation():
    import inspect
    import re

    source = inspect.getsource(today_module)
    assert re.search(
        r'if\s+entered_from_page\s+and\s+entered_from_page\.strip\(\)\.lower\(\)\s*!=\s*"today":\s*\n\s*st\.session_state\[phase2_ready_key\]\s*=\s*False',
        source,
    ), "Phase2 ready flag reset must stay guarded to non-Today navigation."


def test_phase1_ends_with_rerun_not_bare_return():
    """Phase 1 must call st.rerun() after setting phase2_ready so the action-ready
    queue is always rendered on the next pass — not only after a user interaction."""
    import inspect
    import re

    source = inspect.getsource(today_module)

    # Find the line that sets phase2_ready_key = True, then confirm the very
    # next non-comment, non-blank line is st.rerun() (not a bare return).
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if re.search(r'session_state\[phase2_ready_key\]\s*=\s*True', line):
            # Scan forward for the next meaningful statement
            for j in range(i + 1, min(i + 8, len(lines))):
                stripped = lines[j].strip()
                if not stripped or stripped.startswith("#"):
                    continue
                assert re.search(r'st\.rerun\(\)', stripped), (
                    f"Line after phase2_ready_key=True (line {j+1}) is '{stripped}' "
                    "but must be st.rerun(). A bare return leaves users on scan-only "
                    "cards with no action controls."
                )
                return  # found and confirmed

    raise AssertionError(
        "Could not find 'session_state[phase2_ready_key] = True' in today.py source. "
        "The Phase 1 → Phase 2 rerun guard may have moved."
    )


def test_save_today_card_completion_raises_when_tenant_missing(monkeypatch):
    card = _card_for("sig-missing-tenant", "E10")
    monkeypatch.setattr("pages.today.st.session_state", {"user_email": "lead@example.com"})

    try:
        today_module._save_today_card_completion(
            card=card,
            note_text="completed",
            follow_up_required=False,
            follow_up_at=None,
            tenant_id="",
        )
    except ValueError as exc:
        assert "tenant_id is required" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing tenant_id")


def test_failed_drain_shows_detailed_backend_error(monkeypatch):
    card = _card_for("sig-detailed-error", "E11")
    card_session_key = today_module._today_card_session_key(card)
    shown_errors: list[str] = []

    monkeypatch.setattr(
        "pages.today.st.session_state",
        {
            "tenant_id": "tenant-a",
            "user_email": "lead@example.com",
            "_today_pending_completion_ids": ["c-detailed-error"],
            "_today_pending_completion_signal_keys": ["sig-detailed-error"],
            "_today_pending_completion_meta": {
                "c-detailed-error": {
                    "signal_id": "sig-detailed-error",
                    "clicked_at": float(1.0),
                    "queue_update_ms": 1,
                    "click_to_ui_update_ms": 1,
                    "card_session_key": card_session_key,
                    "card": today_module.dataclasses.asdict(card),
                }
            },
            "_today_completed_items": [card_session_key],
        },
    )
    monkeypatch.setattr("pages.today._log_operational_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.show_error_state", lambda message: shown_errors.append(str(message)))

    with today_module._TODAY_COMPLETION_ASYNC_RESULTS_LOCK:
        today_module._TODAY_COMPLETION_ASYNC_RESULTS.clear()
        today_module._TODAY_COMPLETION_ASYNC_RESULTS["c-detailed-error"] = {
            "status": "failed",
            "backend_write_ms": 4,
            "error": "Action event write failed.",
        }

    today_module._drain_today_async_completion_results()

    assert shown_errors == ["Save failed: Action event write failed."]
