from pages import import_page


def test_import_success_message_emphasizes_immediate_value(monkeypatch):
    captured: list[str] = []

    monkeypatch.setattr(import_page.st, "markdown", lambda body, unsafe_allow_html=False: captured.append(body))

    import_page._render_import_ready_message(
        {
            "valid_rows": 120,
            "emp_count": 14,
        }
    )

    assert captured
    rendered = captured[0]
    assert "Import complete: first signal view is ready" in rendered
    assert "120" in rendered
    assert "14" in rendered
    assert "Compared using available targets and recent history." in rendered
    assert "Signals are surfaced to establish an initial baseline." in rendered


def test_import_success_message_sets_expectation_for_future_comparisons(monkeypatch):
    captured: list[str] = []

    monkeypatch.setattr(import_page.st, "markdown", lambda body, unsafe_allow_html=False: captured.append(body))

    import_page._render_import_ready_message(
        {
            "rows_processed": 48,
            "emp_count": 6,
        }
    )

    assert captured
    rendered = captured[0]
    assert "Compared using available targets and recent history." in rendered
    assert "Confidence: Low based on available data completeness and sample depth." in rendered