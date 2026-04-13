from datetime import date

from pages.today import _render_top_status_area
from services.today_page_meaning_service import TodaySurfaceMeaning
from services.today_snapshot_signal_service import SignalMode


def test_top_status_area_renders_compact_demo_and_early_signal_context(monkeypatch):
    markdown_calls: list[str] = []
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: markdown_calls.append(str(text)))

    meaning = TodaySurfaceMeaning(
        state_flags={"stale_days": 2},
        status_line="Early-signal mode: limited history, directional evidence only.",
        stale_banner="",
        freshness_note="",
        weak_data_mode=True,
        import_summary={"source_mode": "demo", "source_label": "sample/demo.csv"},
        signal_mode=SignalMode.EARLY_SIGNAL,
    )

    _render_top_status_area(meaning=meaning)

    rendered = "\n".join(markdown_calls)
    assert "Today status" in rendered
    assert "Demo mode" in rendered
    assert "Data 2 days old" in rendered
    assert "Early signal mode" in rendered
    assert "limited history, directional evidence only" in rendered
    assert "sample/demo.csv" in rendered
