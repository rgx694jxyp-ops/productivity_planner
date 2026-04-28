from __future__ import annotations

from types import SimpleNamespace

from pages import today


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_today_click_stores_team_handoff_payload(monkeypatch):
    session_state: dict = {}
    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today, "traceability_payload_from_card", lambda _item: {})
    monkeypatch.setattr(today.st, "rerun", lambda: None)

    item = SimpleNamespace(
        drill_down=SimpleNamespace(screen="employee_detail", entity_id="E2", label="Open Team"),
        what_happened="Declining performance over 14 days",
        why_flagged="Shown because output is lower than recent baseline",
        metadata={
            "signal_id": "sig-2",
            "signal_key": "signal-key-2",
            "follow_up_status": "Follow-up due May 4",
        },
    )

    today._go_to_drill_down(item)

    assert session_state["goto_page"] == "team"
    assert session_state["cn_selected_emp"] == "E2"
    payload = session_state[today._TODAY_TO_TEAM_HANDOFF_KEY]
    assert payload["employee_id"] == "E2"
    assert payload["signal_id"] == "sig-2"
    assert payload["signal_key"] == "signal-key-2"
    assert payload["reason"] == "Declining performance over 14 days"
    assert payload["follow_up_status"] == "Follow-up due May 4"


def test_today_consumes_return_focus_state_once(monkeypatch):
    session_state: dict = {
        today._TEAM_TO_TODAY_FOCUS_KEY: {
            "employee_id": "E2",
            "signal_id": "sig-2",
            "signal_key": "signal-key-2",
        }
    }
    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "columns", lambda n, **kwargs: [_Ctx() for _ in range(int(n))])
    monkeypatch.setattr(today.st, "expander", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr(today, "_render_today_standup_view", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_render_today_copy_summary_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_render_today_team_risk_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "build_today_team_risk_view_model", lambda **kwargs: None)

    focused_values: list[bool] = []

    def _fake_render_attention_card(*, card, focused=False, **kwargs):
        focused_values.append(bool(focused))

    monkeypatch.setattr(today, "_render_attention_card", _fake_render_attention_card)

    plan = SimpleNamespace(primary_cards=[], secondary_cards=[], primary_placeholder="", suppressed_debug_rows=[])
    card = SimpleNamespace(employee_id="E2")
    prepared = {
        "signal_status_map": {},
        "active_ranked_cards": [card],
        "top_cards": [card],
        "overflow_cards": [],
    }

    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
    )

    assert focused_values == [True]
    assert today._TEAM_TO_TODAY_FOCUS_KEY not in session_state

    focused_values.clear()
    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
    )

    assert focused_values == [False]
