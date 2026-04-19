from contextlib import contextmanager

from pages.today import _render_signal_status_controls
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


def test_signal_status_write_invalidates_today_caches(monkeypatch):
    button_calls = {"count": 0}
    invalidation_calls = {"count": 0}

    def _button(*_args, **_kwargs):
        button_calls["count"] += 1
        return button_calls["count"] == 1

    monkeypatch.setattr("pages.today.st.columns", lambda *_args, **_kwargs: (_noop_ctx(), _noop_ctx(), _noop_ctx()))
    monkeypatch.setattr("pages.today.st.button", _button)
    monkeypatch.setattr("pages.today.st.markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pages.today.st.session_state", {"tenant_id": "tenant-a", "user_email": "lead@example.com"})
    monkeypatch.setattr("pages.today.set_signal_status", lambda **kwargs: {"id": "evt-1"})
    monkeypatch.setattr("pages.today._invalidate_today_write_caches", lambda: invalidation_calls.__setitem__("count", invalidation_calls["count"] + 1))
    monkeypatch.setattr("pages.today.set_flash_message", lambda _msg: None)
    monkeypatch.setattr("pages.today.st.rerun", lambda: None)

    _render_signal_status_controls(card=_card(), key_prefix="sig", status_map={})

    assert invalidation_calls["count"] == 1
