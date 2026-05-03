from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from pages import today


@contextmanager
def _noop_ctx(*_args, **_kwargs):
    yield


def test_unified_queue_renders_before_context_blocks_and_context_is_collapsed(monkeypatch):
    render_order: list[str] = []
    markdown_calls: list[str] = []
    expander_calls: list[tuple[str, bool]] = []

    card = SimpleNamespace(employee_id="E1")
    plan = SimpleNamespace(
        section_title="Follow-ups Today",
        start_note="Open loops that need a manager decision, check-in, or closeout.",
        primary_cards=[],
        secondary_cards=[],
        primary_placeholder="",
        suppressed_debug_rows=[],
    )
    prepared = {
        "signal_status_map": {},
        "active_ranked_cards": [card],
        "top_cards": [card],
        "overflow_cards": [],
    }

    monkeypatch.setattr(today.st, "session_state", {})
    monkeypatch.setattr(today.st, "columns", lambda n, **_kwargs: [_noop_ctx() for _ in range(int(n))])
    monkeypatch.setattr(today.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today.st, "markdown", lambda text, **_kwargs: markdown_calls.append(str(text)))

    def _expander(label: str, expanded: bool = False):
        expander_calls.append((str(label), bool(expanded)))
        return _noop_ctx()

    monkeypatch.setattr(today.st, "expander", _expander)
    monkeypatch.setattr(today, "build_today_team_risk_view_model", lambda **_kwargs: SimpleNamespace(bullets=["risk"]))
    monkeypatch.setattr(today, "_render_attention_card", lambda **_kwargs: render_order.append("queue"))
    monkeypatch.setattr(today, "_render_today_standup_view", lambda *_args, **_kwargs: render_order.append("standup"))
    monkeypatch.setattr(today, "_render_today_copy_summary_block", lambda *_args, **_kwargs: render_order.append("copy"))
    monkeypatch.setattr(today, "_render_today_team_risk_block", lambda *_args, **_kwargs: render_order.append("team_snapshot"))

    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
    )

    assert render_order.index("queue") < render_order.index("standup")
    assert render_order.index("queue") < render_order.index("copy")
    assert render_order.index("queue") < render_order.index("team_snapshot")
    assert ("Context", False) in expander_calls


def test_unified_queue_keeps_single_primary_header(monkeypatch):
    markdown_calls: list[str] = []

    card = SimpleNamespace(employee_id="E1")
    plan = SimpleNamespace(
        section_title="Follow-ups Today",
        start_note="Open loops that need a manager decision, check-in, or closeout.",
        primary_cards=[],
        secondary_cards=[],
        primary_placeholder="",
        suppressed_debug_rows=[],
    )
    prepared = {
        "signal_status_map": {},
        "active_ranked_cards": [card],
        "top_cards": [card],
        "overflow_cards": [],
    }

    monkeypatch.setattr(today.st, "session_state", {})
    monkeypatch.setattr(today.st, "columns", lambda n, **_kwargs: [_noop_ctx() for _ in range(int(n))])
    monkeypatch.setattr(today.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today.st, "expander", lambda *_args, **_kwargs: _noop_ctx())
    monkeypatch.setattr(today.st, "markdown", lambda text, **_kwargs: markdown_calls.append(str(text)))
    monkeypatch.setattr(today, "build_today_team_risk_view_model", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_attention_card", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_standup_view", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_copy_summary_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_team_risk_block", lambda *_args, **_kwargs: None)

    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
    )

    payload = "\n".join(markdown_calls)
    assert payload.count("Handle these first") == 1
    assert "today-action-frame-sub" in payload
    assert "Open loops that need a manager decision, check-in, or closeout." in payload
    assert "today-action-instruction" not in payload
    assert "Open a card" not in payload


def test_today_primary_queue_copy_avoids_instructional_phrases(monkeypatch):
    markdown_calls: list[str] = []

    card = SimpleNamespace(employee_id="E1")
    plan = SimpleNamespace(
        section_title="Follow-ups Today",
        start_note="Open loops that need a manager decision, check-in, or closeout.",
        primary_cards=[],
        secondary_cards=[],
        primary_placeholder="",
        suppressed_debug_rows=[],
    )
    prepared = {
        "signal_status_map": {},
        "active_ranked_cards": [card],
        "top_cards": [card],
        "overflow_cards": [],
    }

    monkeypatch.setattr(today.st, "session_state", {})
    monkeypatch.setattr(today.st, "columns", lambda n, **_kwargs: [_noop_ctx() for _ in range(int(n))])
    monkeypatch.setattr(today.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today.st, "expander", lambda *_args, **_kwargs: _noop_ctx())
    monkeypatch.setattr(today.st, "markdown", lambda text, **_kwargs: markdown_calls.append(str(text)))
    monkeypatch.setattr(today, "build_today_team_risk_view_model", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_attention_card", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_standup_view", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_copy_summary_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_team_risk_block", lambda *_args, **_kwargs: None)

    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
    )

    payload = "\n".join(markdown_calls).lower()
    assert "you should" not in payload
    assert "click" not in payload


def test_unified_queue_renders_manager_loop_strip_when_metrics_provided(monkeypatch):
    markdown_calls: list[str] = []
    caption_calls: list[str] = []

    card = SimpleNamespace(employee_id="E1")
    plan = SimpleNamespace(
        section_title="Follow-ups Today",
        start_note="Open loops that need a manager decision, check-in, or closeout.",
        primary_cards=[],
        secondary_cards=[],
        primary_placeholder="",
        suppressed_debug_rows=[],
    )
    prepared = {
        "signal_status_map": {},
        "active_ranked_cards": [card],
        "top_cards": [card],
        "overflow_cards": [],
    }

    monkeypatch.setattr(today.st, "session_state", {})
    monkeypatch.setattr(today.st, "columns", lambda n, **_kwargs: [_noop_ctx() for _ in range(int(n))])
    monkeypatch.setattr(today.st, "caption", lambda text, **_kwargs: caption_calls.append(str(text)))
    monkeypatch.setattr(today.st, "expander", lambda *_args, **_kwargs: _noop_ctx())
    monkeypatch.setattr(today.st, "container", lambda **_kwargs: _noop_ctx())
    monkeypatch.setattr(today.st, "markdown", lambda text, **_kwargs: markdown_calls.append(str(text)))
    monkeypatch.setattr(today, "build_today_team_risk_view_model", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_attention_card", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_standup_view", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_copy_summary_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_team_risk_block", lambda *_args, **_kwargs: None)

    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
        manager_loop_strip=today.TodayManagerLoopStripViewModel(
            open_loops=7,
            due_today=2,
            overdue=1,
            improved=3,
            no_action_yet=4,
        ),
    )

    assert ["Open loops", "Due today", "Overdue", "Improved", "No action yet"] == caption_calls[-5:]
    assert any("**7**" in line for line in markdown_calls)


def test_unified_queue_completion_feedback_is_one_time_and_not_generic(monkeypatch):
    markdown_calls: list[str] = []
    caption_calls: list[str] = []

    card = SimpleNamespace(employee_id="E1")
    plan = SimpleNamespace(
        section_title="Follow-ups Today",
        start_note="Open loops that need a manager decision, check-in, or closeout.",
        primary_cards=[],
        secondary_cards=[],
        primary_placeholder="",
        suppressed_debug_rows=[],
    )
    prepared = {
        "signal_status_map": {},
        "active_ranked_cards": [card],
        "top_cards": [card],
        "overflow_cards": [],
    }

    session_state = {
        "_today_completion_feedback_message": "Marked complete. Next item moved up.",
    }

    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today.st, "columns", lambda n, **_kwargs: [_noop_ctx() for _ in range(int(n))])
    monkeypatch.setattr(today.st, "caption", lambda text, **_kwargs: caption_calls.append(str(text)))
    monkeypatch.setattr(today.st, "expander", lambda *_args, **_kwargs: _noop_ctx())
    monkeypatch.setattr(today.st, "markdown", lambda text, **_kwargs: markdown_calls.append(str(text)))
    monkeypatch.setattr(today, "build_today_team_risk_view_model", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_attention_card", lambda **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_standup_view", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_copy_summary_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(today, "_render_today_team_risk_block", lambda *_args, **_kwargs: None)

    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
    )
    today._render_unified_attention_queue(
        attention=SimpleNamespace(),
        render_plan=plan,
        prepared_queue_render=prepared,
    )

    assert caption_calls.count("Marked complete. Next item moved up.") == 1
    assert "_today_completion_feedback_message" not in session_state
    assert "Completed." not in caption_calls


def test_non_compact_today_card_shows_core_fields_without_duplicate_phrasing(monkeypatch):
    rendered: list[str] = []

    monkeypatch.setattr(today.st, "container", lambda *args, **kwargs: _noop_ctx())
    monkeypatch.setattr(today.st, "markdown", lambda text, **_kwargs: rendered.append(str(text)))
    monkeypatch.setattr(today.st, "expander", lambda *args, **kwargs: _noop_ctx())

    card = today.TodayQueueCardViewModel(
        employee_id="E1",
        process_id="Picking",
        state="CURRENT",
        line_1="Riley · Picking",
        line_2="Below expected pace",
        line_3="Surfaced because: Declining over recent shifts",
        line_4="Based on recent records",
        line_5="Confidence: Medium",
        what_changed_line="Output changed -12% vs recent baseline",
        expanded_lines=[],
    )

    today._render_attention_card(
        card=card,
        key_prefix="copy-clean-card",
        compact=False,
        show_action=False,
        signal_status_map=None,
    )

    payload = "\n".join(rendered)
    assert "Below expected pace" in payload
    assert "Output changed -12% vs recent baseline" in payload
    assert "Surfaced because: Declining over recent shifts" in payload
    assert "Medium confidence" in payload
    assert payload.count("Output changed -12% vs recent baseline") == 1
