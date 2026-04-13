from pages.today import _render_demo_source_banner


def test_today_demo_source_banner_renders_for_demo_mode(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: captured.append(str(text)))

    _render_demo_source_banner({"source_mode": "demo", "source_label": "sample/demo_supervisor_history.csv"})

    assert captured
    rendered = "\n".join(captured)
    assert "Demo mode: Today queue is based on sample history" in rendered
    assert "sample/demo_supervisor_history.csv" in rendered


def test_today_demo_source_banner_skips_non_demo_mode(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: captured.append(str(text)))

    _render_demo_source_banner({"source_mode": "real"})

    assert not captured
