from contextlib import contextmanager

from pages.today import _render_attention_card
from services.today_view_model_service import TodayQueueCardViewModel


@contextmanager
def _noop_container(*args, **kwargs):
    yield


@contextmanager
def _noop_expander(*args, **kwargs):
    yield


def _card() -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id="E1",
        process_id="Receiving",
        state="CURRENT",
        line_1="Alex · Receiving",
        line_2="Below expected pace",
        line_3="Below recent baseline vs comparable days.",
        line_4="Based on 4 recent records",
        line_5="Confidence: High",
        expanded_lines=[],
    )


def test_today_card_exposes_quick_note_entrypoint(monkeypatch):
    labels: list[str] = []

    monkeypatch.setattr("pages.today.st.container", _noop_container)
    monkeypatch.setattr("pages.today.st.expander", _noop_expander)
    monkeypatch.setattr("pages.today.st.markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr("pages.today.st.text_area", lambda *args, **kwargs: "")

    def _button(label, **kwargs):
        labels.append(str(label))
        return False

    monkeypatch.setattr("pages.today.st.button", _button)

    _render_attention_card(
        card=_card(),
        key_prefix="today_quick_note_entry",
        compact=False,
        show_action=False,
    )

    assert "Save quick note" in labels


def test_today_card_quick_note_saves_without_navigation(monkeypatch):
    flash_messages: list[str] = []
    journal_calls: list[tuple[str, str, str]] = []
    lifecycle_calls: list[dict] = []
    warnings: list[str] = []
    rerun_called = {"value": False}

    monkeypatch.setattr("pages.today.st.container", _noop_container)
    monkeypatch.setattr("pages.today.st.expander", _noop_expander)
    monkeypatch.setattr("pages.today.st.markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr("pages.today.st.warning", lambda msg: warnings.append(str(msg)))
    monkeypatch.setattr("pages.today.st.text_area", lambda *args, **kwargs: "Checked conveyor calibration and reset handoff.")
    monkeypatch.setattr("pages.today.st.button", lambda label, **kwargs: str(label) == "Save quick note")
    monkeypatch.setattr("pages.today.st.session_state", {"user_email": "lead@example.com", "tenant_id": "t1", "goto_page": "today"})

    def _fake_log_coaching_lifecycle_entry(**kwargs):
        lifecycle_calls.append(dict(kwargs))
        return {"action_id": "A1"}

    monkeypatch.setattr("pages.today.log_coaching_lifecycle_entry", _fake_log_coaching_lifecycle_entry)
    monkeypatch.setattr("pages.today.add_coaching_note", lambda emp_id, note, created_by: journal_calls.append((str(emp_id), str(note), str(created_by))))
    monkeypatch.setattr("pages.today.set_flash_message", lambda msg: flash_messages.append(str(msg)))

    def _fake_rerun():
        rerun_called["value"] = True

    monkeypatch.setattr("pages.today.st.rerun", _fake_rerun)

    _render_attention_card(
        card=_card(),
        key_prefix="today_quick_note_save",
        compact=False,
        show_action=False,
    )

    assert rerun_called["value"] is True
    assert flash_messages == ["Quick note saved."]
    assert len(lifecycle_calls) == 1
    assert len(journal_calls) == 1
    assert journal_calls[0][0] == "E1"
    assert "Today queue quick note" in journal_calls[0][1]
    assert "Checked conveyor calibration" in journal_calls[0][1]
    assert warnings == []
