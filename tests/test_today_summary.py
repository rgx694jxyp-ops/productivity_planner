from datetime import date

from pages.today import _render_today_copy_summary_block, _render_today_standup_view
from services.today_view_model_service import TodayQueueCardViewModel, build_today_standup_text, build_today_summary


def _card(
    employee_id: str,
    employee_name: str,
    process_name: str,
    what_changed_line: str,
    *,
    normalized_action_state: str = "",
    normalized_action_state_detail: str = "",
    line_2: str = "Below expected pace",
) -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id=employee_id,
        process_id=process_name,
        state="CURRENT",
        line_1=f"{employee_name} · {process_name}",
        line_2=line_2,
        line_3="Surfaced because: Declining over the last 5 days",
        line_4="Latest snapshot only",
        line_5="Confidence: High",
        expanded_lines=[],
        what_changed_line=what_changed_line,
        normalized_action_state=normalized_action_state,
        normalized_action_state_detail=normalized_action_state_detail,
        signal_key=f"signal:{employee_id}:{process_name}",
    )


def test_build_today_summary_uses_top_three_ranked_items_and_follow_up_bucket():
    cards = [
        _card(
            "E1",
            "Riley",
            "Picking",
            "Performance down 19% vs 5-day average",
            normalized_action_state="Follow-up Scheduled",
            normalized_action_state_detail="Due today",
            line_2="Follow-up due today",
        ),
        _card(
            "E2",
            "Mina",
            "Receiving",
            "Performance down 12% vs 5-day average",
            normalized_action_state="Follow-up Scheduled",
            normalized_action_state_detail="Overdue",
            line_2="Follow-up not completed",
        ),
        _card("E3", "Jules", "Packing", "Down 9% vs 5-day average"),
        _card("E4", "Avery", "Shipping", "Up 8% vs last week"),
        _card("E5", "Taylor", "Loading", "Down 7% vs 5-day average"),
    ]

    summary = build_today_summary(cards)
    lines = summary.splitlines()

    assert lines[1] == "- Riley ↓ 19% vs 5-day avg (Picking)"
    assert lines[2] == "- Mina ↓ 12% vs 5-day avg (Receiving)"
    assert lines[3] == "- Jules ↓ 9% vs 5-day avg (Packing)"
    assert lines[4] == "- 2 follow-ups due today (1 overdue)"
    assert "- Riley ↓ 19% vs 5-day avg (Picking)" in summary
    assert "- Mina ↓ 12% vs 5-day avg (Receiving)" in summary
    assert "- Jules ↓ 9% vs 5-day avg (Packing)" in summary
    assert "Taylor" not in summary


def test_build_today_summary_allows_follow_up_first_when_top_signal_is_follow_up_priority():
    cards = [
        _card(
            "E1",
            "Riley",
            "Picking",
            "",
            normalized_action_state="Follow-up Scheduled",
            normalized_action_state_detail="Overdue",
            line_2="Follow-up not completed",
        ),
        _card("E2", "Mina", "Receiving", "Down 12% vs 5-day average"),
        _card("E3", "Jules", "Packing", "Down 9% vs 5-day average"),
    ]

    summary = build_today_summary(cards)
    lines = summary.splitlines()

    assert lines[1] == "- 1 follow-up due today (1 overdue)"
    assert lines[2] == "- Mina ↓ 12% vs 5-day avg (Receiving)"


def test_build_today_summary_formats_output_and_keeps_focus_on_one_line():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Up 12% vs last week"),
    ]

    summary = build_today_summary(cards)
    lines = summary.splitlines()

    assert lines[0] == "Today Summary:"
    assert lines[1] == "- Riley ↓ 19% vs 5-day avg (Picking)"
    assert lines[2] == "- Sam ↑ 12% vs last week (Receiving)"
    assert lines[3] == "Focus: Picking decline centered on Riley"


def test_build_today_summary_focus_line_prefers_area_then_overdue_follow_up():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Down 12% vs 5-day average"),
        _card(
            "E3",
            "Jordan",
            "Packing",
            "",
            normalized_action_state="Follow-up Scheduled",
            normalized_action_state_detail="Overdue",
            line_2="Follow-up not completed",
        ),
    ]

    summary = build_today_summary(cards)

    assert summary.splitlines()[-1] == "Focus: Picking decline centered on Riley + 1 overdue follow-up"


def test_build_today_summary_focus_line_skips_employee_when_not_dominant():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Down 17% vs 5-day average"),
    ]

    summary = build_today_summary(cards)

    assert summary.splitlines()[-1] == "Focus: Picking decline"


def test_build_today_summary_keeps_positive_signal_from_pushing_out_third_decline():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Up 12% vs last week"),
        _card("E3", "Jordan", "Packing", "Down 9% vs 5-day average"),
        _card("E4", "Avery", "Shipping", "Down 7% vs 5-day average"),
    ]

    summary = build_today_summary(cards)
    lines = summary.splitlines()

    assert lines[1] == "- Riley ↓ 19% vs 5-day avg (Picking)"
    assert lines[2] == "- Jordan ↓ 9% vs 5-day avg (Packing)"
    assert lines[3] == "- Avery ↓ 7% vs 5-day avg (Shipping)"
    assert "Sam ↑ 12%" not in summary


def test_build_today_summary_uses_positive_signal_only_when_fewer_than_three_declines_exist():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Up 12% vs last week"),
        _card("E3", "Jordan", "Packing", "Down 9% vs 5-day average"),
    ]

    summary = build_today_summary(cards)

    assert "- Riley ↓ 19% vs 5-day avg (Picking)" in summary
    assert "- Jordan ↓ 9% vs 5-day avg (Packing)" in summary
    assert "- Sam ↑ 12% vs last week (Receiving)" in summary


def test_build_today_summary_avoids_banned_words_and_stays_under_six_lines():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Up 12% vs last week"),
        _card("E3", "Jordan", "Packing", "Down 9% vs 5-day average"),
        _card("E4", "Avery", "Shipping", "Up 8% vs last week"),
    ]

    summary = build_today_summary(cards)
    lowered = summary.lower()

    assert "debug" not in lowered
    assert "system" not in lowered
    assert len(summary.splitlines()) <= 6


def test_build_today_standup_text_formats_for_reading_aloud():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Mina", "Receiving", "Down 12% vs 5-day average"),
        _card("E3", "Jules", "Packing", "Down 9% vs 5-day average"),
        _card(
            "E4",
            "Jordan",
            "Packing",
            "",
            normalized_action_state="Follow-up Scheduled",
            normalized_action_state_detail="Overdue",
            line_2="Follow-up not completed",
        ),
    ]

    standup = build_today_standup_text(cards)
    lines = standup.splitlines()

    assert lines[0] == "Today:"
    assert lines[1] == "- Riley down 19% in Picking"
    assert lines[2] == "- Mina down 12% in Receiving"
    assert lines[3] == "- Jules down 9% in Packing"
    assert lines[4] == "- 1 overdue follow-up"
    assert lines[5] == "Focus: Riley in Picking + 1 overdue follow-up"


def test_build_today_standup_text_avoids_banned_words_and_stays_under_seven_lines():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Up 12% vs last week"),
        _card("E3", "Jordan", "Packing", "Down 9% vs 5-day average"),
        _card("E4", "Avery", "Shipping", "Down 7% vs 5-day average"),
    ]

    standup = build_today_standup_text(cards)
    lowered = standup.lower()

    assert "debug" not in lowered
    assert "system" not in lowered
    assert "centered on" not in lowered
    assert len(standup.splitlines()) <= 6


def test_build_today_standup_text_uses_area_when_employee_is_not_dominant():
    cards = [
        _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
        _card("E2", "Sam", "Receiving", "Down 17% vs 5-day average"),
        _card(
            "E3",
            "Jordan",
            "Packing",
            "",
            normalized_action_state="Follow-up Scheduled",
            normalized_action_state_detail="Due today",
            line_2="Follow-up due today",
        ),
    ]

    standup = build_today_standup_text(cards)

    assert standup.splitlines()[-1] == "Focus: Picking performance + follow-ups"


def test_render_today_copy_summary_block_shows_summary_text_area(monkeypatch):
    rendered: dict[str, str] = {}
    session_state: dict[str, object] = {}
    component_payload: dict[str, object] = {}

    monkeypatch.setattr("pages.today.st.session_state", session_state)
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "pages.today.components.html",
        lambda html, **kwargs: component_payload.update({"html": html, **kwargs}),
    )
    monkeypatch.setattr("pages.today.st.button", lambda label, **_kwargs: label == "Show summary text")

    def _text_area(label: str, value: str, **_kwargs) -> str:
        rendered["label"] = label
        rendered["value"] = value
        return value

    monkeypatch.setattr("pages.today.st.text_area", _text_area)

    _render_today_copy_summary_block(
        [
            _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
            _card("E2", "Sam", "Receiving", "Up 12% vs last week"),
        ],
        today_value=date(2026, 4, 28),
    )

    assert "Copy summary" in str(component_payload.get("html") or "")
    assert "navigator.clipboard.writeText" in str(component_payload.get("html") or "")
    assert "Copied" in str(component_payload.get("html") or "")
    assert rendered["label"] == "Today summary"
    assert rendered["value"].startswith("Today Summary:\n- Riley ↓ 19% vs 5-day avg (Picking)")


def test_render_today_standup_view_shows_read_only_summary(monkeypatch):
    rendered: list[str] = []

    monkeypatch.setattr("pages.today.st.markdown", lambda text, **_kwargs: rendered.append(str(text)))
    monkeypatch.setattr("pages.today.st.button", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no buttons expected")))

    _render_today_standup_view(
        [
            _card("E1", "Riley", "Picking", "Down 19% vs 5-day average"),
            _card("E2", "Mina", "Receiving", "Down 12% vs 5-day average"),
            _card("E3", "Jules", "Packing", "Down 9% vs 5-day average"),
        ]
    )

    payload = "\n".join(rendered)
    assert "Standup view" in payload
    assert "Riley down 19% in Picking" in payload
    assert "Focus: Riley in Picking" in payload