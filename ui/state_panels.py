"""Reusable polished UI state panels for calm, confidence-building feedback."""

from __future__ import annotations

import streamlit as st


def _apply_state_styles() -> None:
    if st.session_state.get("_state_panel_styles_rendered"):
        return
    st.session_state["_state_panel_styles_rendered"] = True
    st.markdown(
        """
        <style>
        .state-panel {
            border-radius: 12px;
            padding: 10px 12px;
            margin: 8px 0;
        }
        .state-title {
            font-size: 1.0rem;
            font-weight: 800;
            margin-bottom: 4px;
        }
        .state-copy {
            font-size: 0.92rem;
            line-height: 1.4;
            color: #1f2f43;
            margin-bottom: 4px;
        }
        .state-note {
            font-size: 0.84rem;
            color: #5d7693;
        }
        .state-loading { background: #eef5fd; border: 1px solid #d0e2f6; }
        .state-empty { background: #f7fbff; border: 1px solid #d6e7f7; }
        .state-partial { background: #fff9ef; border: 1px solid #f0d9a9; }
        .state-low-confidence { background: #fff6f4; border: 1px solid #f3c6bc; }
        .state-healthy { background: #edf9f0; border: 1px solid #c4e8cd; }
        .state-success { background: #edf9f0; border: 1px solid #c4e8cd; }
        .state-error { background: #fff5f5; border: 1px solid #f0c2c2; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _panel(css_class: str, title: str, message: str, note: str = "") -> None:
    _apply_state_styles()
    note_html = f'<div class="state-note">{note}</div>' if note else ""
    st.markdown(
        f'<div class="state-panel {css_class}">'
        f'<div class="state-title">{title}</div>'
        f'<div class="state-copy">{message}</div>'
        f"{note_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def show_loading_state(message: str = "Loading the latest operating view.") -> None:
    _panel(
        "state-loading",
        "Loading",
        message,
        "This usually takes a few seconds.",
    )


def show_no_data_state() -> None:
    _panel(
        "state-empty",
        "No data yet",
        "There is not enough imported data to build today's operating signals yet.",
        "Import recent data to begin seeing team signals.",
    )


def show_partial_data_state(missing_summary: str) -> None:
    _panel(
        "state-partial",
        "Partial data",
        "Some signals are available, while some sections are still waiting for complete context.",
        missing_summary,
    )


def show_low_confidence_state(reason: str) -> None:
    _panel(
        "state-low-confidence",
        "Low-confidence data",
        "Some visible signals are early and may change as more complete data arrives.",
        reason,
    )


def show_healthy_state() -> None:
    _panel(
        "state-healthy",
        "Healthy status",
        "No major issues are currently surfaced.",
        "The queue will update automatically as new data and follow-up events arrive.",
    )


def show_success_state(message: str) -> None:
    _panel(
        "state-success",
        "Saved",
        message,
        "The update is now reflected in current state views.",
    )


def show_error_state(message: str = "Something unexpected prevented this section from loading.") -> None:
    _panel(
        "state-error",
        "Unable to load this view",
        message,
        "You can refresh data and try again.",
    )


def show_toast_feedback(message: str, *, icon: str = "✔") -> None:
    """Show a brief non-blocking toast notification for completed actions.

    Designed to be called from a flash-message session-state handler so it
    fires in the render that follows st.rerun(), not before it.  Callers
    should NOT call this immediately before st.rerun() — the notification
    would be discarded.  Use set_flash_message() + st.rerun() instead.
    """
    try:
        st.toast(f"{icon} {message}")
    except Exception:
        # Fallback: render a compact success panel if toast is unavailable.
        _panel("state-success", "Saved", message, "")


# Key used by both today.py and employees.py for cross-page flash messages.
_FLASH_KEY = "_action_flash_message"


def set_flash_message(message: str) -> None:
    """Store a flash message to be shown on the next render via consume_flash_message()."""
    st.session_state[_FLASH_KEY] = str(message)


def consume_flash_message() -> None:
    """Render and clear any pending flash message stored by set_flash_message().

    Safe to call even when no message is pending.
    """
    message = str(st.session_state.pop(_FLASH_KEY, "") or "")
    if message:
        show_toast_feedback(message)
