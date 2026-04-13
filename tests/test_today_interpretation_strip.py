from pages.today import _render_today_interpretation_strip


def test_today_interpretation_strip_renders_expected_copy(monkeypatch):
    class _Ctx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    markdown_calls: list[str] = []

    monkeypatch.setattr("pages.today.st.container", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: markdown_calls.append(str(text)))

    _render_today_interpretation_strip()

    assert any("What you are seeing" in text for text in markdown_calls)
    assert any("This queue highlights where current data differs from expected or recent patterns." in text for text in markdown_calls)
    assert any("Each item shows why it surfaced and how reliable the evidence is." in text for text in markdown_calls)
    assert any("Low-confidence items are early signals, not final conclusions." in text for text in markdown_calls)
