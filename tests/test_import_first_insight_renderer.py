from pages import import_page


def test_first_import_insight_renderer_tolerates_missing_fields(monkeypatch):
    """Protects against silent loss of first insight when optional keys are missing."""
    markdown_calls: list[str] = []
    info_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "markdown", lambda body, **kwargs: markdown_calls.append(str(body)))
    monkeypatch.setattr(import_page.st, "info", lambda body, **kwargs: info_calls.append(str(body)))

    # Intentionally sparse payload to simulate messy/missing upstream fields.
    partial_insight = {
        "what_happened": "Signal context is available.",
        "compared_to_what": "Compared with recent imported rows.",
        "why_shown": "Shown because confidence context is still building.",
    }

    import_page._render_first_import_insight(partial_insight)

    assert markdown_calls
