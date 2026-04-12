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
    assert "Your data is ready" in rendered
    assert "120" in rendered
    assert "14" in rendered
    assert "You can start reviewing performance now" in rendered


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
    assert "Comparisons will appear after more data is available" in rendered
    assert "Data looks good" in rendered