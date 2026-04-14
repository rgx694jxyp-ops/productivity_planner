"""Tests for the action feedback / flash-message system.

Verifies:
- set_flash_message stores in session state
- consume_flash_message clears the key and fires show_toast_feedback
- consume_flash_message is a no-op when no message is pending
- show_toast_feedback falls back gracefully if st.toast raises
- today.py and employees.py use set_flash_message (not show_success_state + rerun)
  after successful quick-actions, so the message survives the rerun
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_st_session(data: dict | None = None):
    """Minimal dict-backed mock of st.session_state with pop() support."""
    session = dict(data or {})
    mock = MagicMock()
    mock.__setitem__ = lambda self, k, v: session.__setitem__(k, v)
    mock.__getitem__ = lambda self, k: session.__getitem__(k)
    mock.__contains__ = lambda self, k: k in session
    mock.get = lambda k, d=None: session.get(k, d)
    mock.pop = lambda k, *args: session.pop(k, *args)
    return mock, session


# ---------------------------------------------------------------------------
# set_flash_message / consume_flash_message
# ---------------------------------------------------------------------------


def test_set_flash_message_stores_in_session_state(monkeypatch):
    _mock_st = MagicMock()
    session_data = {}
    _mock_st.session_state = session_data
    monkeypatch.setitem(sys.modules, "streamlit", _mock_st)

    # Reload to pick up mocked streamlit
    if "ui.state_panels" in sys.modules:
        del sys.modules["ui.state_panels"]

    from ui.state_panels import _FLASH_KEY, set_flash_message

    set_flash_message("Note saved")
    assert session_data[_FLASH_KEY] == "Note saved"


def test_consume_flash_message_clears_key_and_calls_toast(monkeypatch):
    _mock_st = MagicMock()
    session_data = {}

    class _SessionProxy(dict):
        """dict subclass that routes pop() correctly."""
        pass

    proxy = _SessionProxy()
    proxy["_action_flash_message"] = "Follow-through saved."
    _mock_st.session_state = proxy
    monkeypatch.setitem(sys.modules, "streamlit", _mock_st)

    if "ui.state_panels" in sys.modules:
        del sys.modules["ui.state_panels"]

    from ui.state_panels import consume_flash_message

    consume_flash_message()

    # session_state key must be cleared
    assert "_action_flash_message" not in proxy
    # st.toast should have been called with the message
    _mock_st.toast.assert_called_once()
    call_args = _mock_st.toast.call_args[0][0]
    assert "Follow-through saved." in call_args


def test_consume_flash_message_is_noop_when_empty(monkeypatch):
    _mock_st = MagicMock()

    class _SessionProxy(dict):
        pass

    _mock_st.session_state = _SessionProxy()
    monkeypatch.setitem(sys.modules, "streamlit", _mock_st)

    if "ui.state_panels" in sys.modules:
        del sys.modules["ui.state_panels"]

    from ui.state_panels import consume_flash_message

    consume_flash_message()  # should not raise
    _mock_st.toast.assert_not_called()


def test_show_toast_feedback_falls_back_gracefully_if_toast_raises(monkeypatch):
    _mock_st = MagicMock()
    _mock_st.toast.side_effect = AttributeError("toast not available")
    _mock_st.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", _mock_st)

    if "ui.state_panels" in sys.modules:
        del sys.modules["ui.state_panels"]

    from ui.state_panels import show_toast_feedback

    # Should not raise; falls back to _panel()
    show_toast_feedback("Issue resolved.")
    # _panel calls st.markdown — verify it was called as the fallback
    _mock_st.markdown.assert_called()


# ---------------------------------------------------------------------------
# Verify today.py quick-actions write to session state (not direct render)
# ---------------------------------------------------------------------------


def test_today_signal_status_sets_flash_not_show_success(monkeypatch):
    """set_signal_status success path must call set_flash_message, not show_success_state."""
    import ast
    import pathlib

    source = pathlib.Path("pages/today.py").read_text()
    tree = ast.parse(source)

    # Find all Call nodes where show_success_state is called immediately before st.rerun()
    # Strategy: look for Expr(Call(show_success_state)) patterns in function bodies
    show_success_direct = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "show_success_state":
                show_success_direct.append(node)

    # There should be zero direct show_success_state calls remaining in today.py
    # (they've all been replaced by set_flash_message)
    assert len(show_success_direct) == 0, (
        f"today.py still has {len(show_success_direct)} direct show_success_state() "
        "call(s); these should use set_flash_message() so the message survives st.rerun()."
    )


def test_employees_follow_through_sets_flash_not_show_success(monkeypatch):
    """In employees.py the follow-through save path must use set_flash_message."""
    import ast
    import pathlib

    source = pathlib.Path("pages/employees.py").read_text()
    tree = ast.parse(source)

    # Collect all show_success_state call sites with their line numbers
    show_success_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "show_success_state":
                show_success_calls.append(getattr(node, "lineno", "?"))

    # The only remaining show_success_state calls in employees.py should be
    # the legitimate _cn_feedback coaching-note banner (not the quick-action paths).
    # Those are the ones that render AFTER a rerun (read from session state), not before.
    # If a test fails here, a new direct-call was introduced before a rerun.
    # We allow up to 3 remaining calls (the coaching-note banner has 2 + the exception-saved one).
    assert len(show_success_calls) <= 3, (
        f"employees.py has {len(show_success_calls)} show_success_state() calls "
        f"at lines {show_success_calls}. Quick-action feedback should use set_flash_message()."
    )
