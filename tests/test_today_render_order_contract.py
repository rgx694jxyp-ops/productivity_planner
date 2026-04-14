from contextlib import contextmanager

from pages.today import _render_attention_card
from services.today_view_model_service import TodayQueueCardViewModel


@contextmanager
def _noop_container(*args, **kwargs):
    yield


def _build_card(*, line_5: str, freshness: str) -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id="E-1",
        process_id="P-1",
        state="CURRENT",
        line_1="Alex · Receiving",
        line_2="Below expected pace",
        line_3="Below recent baseline vs comparable days.",
        line_4="Based on 4 recent records",
        line_5=line_5,
        freshness_line=freshness,
        expanded_lines=[],
    )


def test_today_card_render_order_keeps_confidence_and_freshness_before_evidence(monkeypatch):
    rendered: list[str] = []
    monkeypatch.setattr("pages.today.st.container", _noop_container)
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: rendered.append(str(text)))

    _render_attention_card(
        card=_build_card(line_5="Confidence: High", freshness="Freshness: Updated 2h ago"),
        key_prefix="order_high",
        compact=True,
        show_action=False,
    )

    payload = "\n".join(rendered)
    freshness_index = payload.index("Freshness: Updated 2h ago")
    evidence_index = payload.index("Based on 4 recent records")

    assert freshness_index < evidence_index


def test_today_card_render_order_keeps_low_confidence_branch_before_evidence(monkeypatch):
    rendered: list[str] = []
    monkeypatch.setattr("pages.today.st.container", _noop_container)
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: rendered.append(str(text)))

    _render_attention_card(
        card=_build_card(line_5="Low confidence", freshness="Freshness: Updated 1h ago"),
        key_prefix="order_low",
        compact=True,
        show_action=False,
    )

    payload = "\n".join(rendered)
    low_confidence_index = payload.index("Low confidence")
    freshness_index = payload.index("Freshness: Updated 1h ago")
    evidence_index = payload.index("Based on 4 recent records")

    assert low_confidence_index < evidence_index
    assert freshness_index < evidence_index


def test_today_card_low_confidence_renders_single_confidence_marker(monkeypatch):
    """Protects against duplicate confidence messaging that creates conflicting emphasis."""
    rendered: list[str] = []
    monkeypatch.setattr("pages.today.st.container", _noop_container)
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: rendered.append(str(text)))

    _render_attention_card(
        card=_build_card(line_5="Low confidence", freshness="Freshness: Updated 1h ago"),
        key_prefix="confidence_dup_guard",
        compact=True,
        show_action=False,
    )

    payload = "\n".join(rendered).lower()
    assert payload.count("low confidence") == 1
