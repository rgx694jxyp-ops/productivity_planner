from datetime import date

from pages.today import _render_queue_orientation_block, _render_top_status_area
from services.today_page_meaning_service import TodayQueueOrientationModel, TodaySurfaceMeaning, TodaySurfaceState
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


def test_queue_orientation_emphasizes_attention_now_and_keeps_total_as_secondary(monkeypatch):
    markdown_calls: list[str] = []
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: markdown_calls.append(str(text)))

    orientation = TodayQueueOrientationModel(
        total_shown=3,
        declining_count=1,
        repeat_count=1,
        limited_confidence_count=1,
        distinct_processes=2,
        total_evaluated=10,
    )
    meaning = TodaySurfaceMeaning(
        state_flags={},
        status_line="",
        stale_banner="",
        freshness_note="",
        weak_data_mode=False,
        import_summary={},
        signal_mode=SignalMode.STABLE_SIGNAL,
        surface_state=TodaySurfaceState.STRONG_SIGNALS,
    )

    _render_queue_orientation_block(
        orientation,
        meaning=meaning,
        surface_state=TodaySurfaceState.STRONG_SIGNALS,
        signal_mode=SignalMode.STABLE_SIGNAL,
    )

    rendered = "\n".join(markdown_calls)
    assert "A few signals need attention now" in rendered
    assert "1 declining trend" in rendered
    assert "1 repeat issue" in rendered
    assert "1 with limited data confidence" in rendered
    assert "3 total in queue" in rendered
