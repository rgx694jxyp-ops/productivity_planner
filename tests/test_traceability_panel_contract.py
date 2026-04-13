from ui import traceability_panel as panel
from tests.product_posture_assertions import assert_no_prescriptive_language


class _FakeContainer:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeStreamlit:
    def __init__(self):
        self.markdowns: list[str] = []
        self.writes: list[str] = []
        self.captions: list[str] = []

    def container(self, border: bool = False):
        return _FakeContainer()

    def markdown(self, text: str):
        self.markdowns.append(str(text))

    def write(self, text: str):
        self.writes.append(str(text))

    def caption(self, text: str):
        self.captions.append(str(text))


def _base_context() -> dict:
    return {
        "signal_summary": "Lower than recent pace",
        "surfaced_because": "Surfaced because recent output is below the comparison range.",
        "confidence_level": "low",
        "confidence_basis": "only 2 usable points are available",
        "confidence_caveat": "comparison depth is limited",
        "confidence_sample_size": 2,
        "confidence_minimum_points": 3,
        "included_rows": 2,
        "comparison_statement": "Compared with the latest 3-day window versus prior 3-day window",
        "freshness_statement": "Freshness: Latest snapshot only",
        "signal_maturity_label": "limited-data prompt",
        "signal_maturity_reason": "fewer than 3 usable points are available",
        "linked_scope": "employee",
        "linked_entity_id": "E1",
        "warnings": ["partial trend history"],
    }


def test_traceability_panel_helpers_cover_fallbacks_and_maturity_rules():
    assert panel._maturity_label_from_context({"included_rows": 2, "confidence_level": "high"}) == "limited-data prompt"
    assert panel._maturity_label_from_context({"included_rows": 5, "confidence_level": "low"}) == "early signal"
    assert panel._maturity_label_from_context({"included_rows": 5, "confidence_level": "high"}) == "stable signal"

    comp_fallback = panel._comparison_statement({})
    fresh_fallback = panel._freshness_statement({"date_range_used": "Latest snapshot"})
    basis_fallback = panel._data_basis_statement({})

    assert comp_fallback.startswith("Compared with")
    assert "limited or missing" in comp_fallback
    assert fresh_fallback == "Freshness: Latest snapshot"
    assert basis_fallback == "Latest snapshot only"


def test_traceability_panel_renders_normalized_drilldown_contract(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(panel, "st", fake_st)

    context = _base_context()
    panel.render_traceability_panel(context, heading="Signal source context")

    writes = list(fake_st.writes)
    assert len(writes) >= 6
    assert writes[0].startswith("Surfaced because")
    assert writes[1].startswith("Confidence is")
    assert writes[2].startswith("Based on") or writes[2] == "Latest snapshot only"
    assert writes[3].startswith("Compared with")
    assert writes[4].startswith("Freshness:")
    maturity_lower = writes[5].lower()
    assert any(token in maturity_lower for token in ["stable signal", "early signal", "limited-data prompt"])

    joined_markdown = "\n".join(fake_st.markdowns)
    assert "### Lower than recent pace" in joined_markdown

    assert_no_prescriptive_language([*fake_st.markdowns, *fake_st.writes, *fake_st.captions])


def test_maturity_under_three_points_never_uses_stable_signal_wording(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(panel, "st", fake_st)

    context = _base_context()
    context["included_rows"] = 1
    context["confidence_sample_size"] = 1
    context["signal_maturity_label"] = ""
    context["signal_maturity_reason"] = ""

    panel.render_traceability_panel(context, heading="Signal source context")

    maturity_line = fake_st.writes[5].lower()
    assert "limited-data prompt" in maturity_line
    assert "stable signal" not in maturity_line


def test_traceability_basis_line_includes_process_and_shift_context_when_present():
    context = _base_context()
    context["process_context_label"] = "Receiving"
    context["shift_context_label"] = "Night"

    line = panel._data_basis_statement(context)

    assert line.startswith("Based on")
    assert "Process context: Receiving" in line
    assert "Shift context: Night" in line


def test_traceability_basis_line_calls_out_missing_shift_for_process_scope():
    context = _base_context()
    context["linked_scope"] = "process"
    context["process_context_label"] = "Packing"
    context["shift_context_label"] = ""
    context["is_shift_level"] = False

    line = panel._data_basis_statement(context)

    assert "Process context: Packing" in line
    assert "Shift context unavailable in this snapshot" in line
