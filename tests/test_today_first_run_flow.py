from datetime import date

from services.attention_scoring_service import AttentionItem, AttentionSummary
from pages.today import _render_unified_attention_queue


def _summary_with_secondary_only() -> AttentionSummary:
    return AttentionSummary(
        ranked_items=[
            AttentionItem(
                employee_id="E1",
                process_name="Packing",
                attention_score=35,
                attention_tier="low",
                attention_reasons=["Low confidence signal"],
                attention_summary="Early signal",
                factors_applied=[],
                snapshot={"employee_id": "E1", "process_name": "Packing"},
            )
        ],
        is_healthy=False,
        healthy_message="",
        suppressed_count=0,
        total_evaluated=1,
    )


def test_first_run_secondary_only_shows_early_signal_placeholder(monkeypatch):
    class _Ctx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Expander:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Plan:
        section_title = "What needs attention today"
        weak_data_note = ""
        start_note = "Start here."
        primary_cards = []
        secondary_cards = [
            type(
                "Card",
                (),
                {
                    "employee_id": "E1",
                    "process_id": "Packing",
                    "state": "EARLY_TREND",
                    "line_1": "E1 · Packing",
                    "line_2": "Not enough history yet",
                    "line_3": "",
                    "line_4": "",
                    "line_5": "Low confidence",
                    "expanded_lines": [],
                    "freshness_line": "Data age: current shift/day. Safe for live review.",
                },
            )()
        ]
        primary_placeholder = "Early signals are available below. They are lower confidence, but still useful for triage."
        secondary_caption = "Early signals based on limited data"
        secondary_expanded = True
        suppressed_debug_rows = []

    markdown_calls: list[str] = []

    monkeypatch.setattr("pages.today.build_today_queue_render_plan", lambda *args, **kwargs: _Plan())
    monkeypatch.setattr("pages.today.st.container", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr("pages.today.st.expander", lambda *args, **kwargs: _Expander())
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: markdown_calls.append(str(text)))
    monkeypatch.setattr("pages.today.st.write", lambda *args, **kwargs: None)
    monkeypatch.setattr("pages.today.st.button", lambda *args, **kwargs: False)
    monkeypatch.setattr("pages.today.st.session_state", {})

    _render_unified_attention_queue(
        _summary_with_secondary_only(),
        suppressed_cards=[],
        is_stale=False,
        show_secondary_open=True,
    )

    assert any("Early signals are available below" in text for text in markdown_calls)
