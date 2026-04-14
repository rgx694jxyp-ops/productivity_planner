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


def test_render_import_trust_summary_shows_warning_summary(monkeypatch):
    info_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_page.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_page.st, "columns", lambda n: [type("Col", (), {"metric": lambda self, *a, **k: None, "caption": lambda self, *a, **k: None})() for _ in range(n)])
    monkeypatch.setattr(import_page.st, "info", lambda body: info_calls.append(body))

    import_page._render_import_trust_summary(
        {
            "status": "partial",
            "confidence_score": 82,
            "accepted_rows": 10,
            "rejected_rows": 1,
            "warnings": 1,
            "duplicates": 0,
            "missing_required_fields": 0,
            "inconsistent_names": 0,
            "suspicious_values": 0,
            "warning_summary": "Some row dates could not be parsed and used the selected work date instead.",
        },
        heading="Projected data quality and trust",
    )

    assert info_calls == ["Some row dates could not be parsed and used the selected work date instead."]


def test_render_import_trust_summary_omits_warning_summary_for_clean_import(monkeypatch):
    info_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_page.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_page.st, "columns", lambda n: [type("Col", (), {"metric": lambda self, *a, **k: None, "caption": lambda self, *a, **k: None})() for _ in range(n)])
    monkeypatch.setattr(import_page.st, "info", lambda body: info_calls.append(body))

    import_page._render_import_trust_summary(
        {
            "status": "valid",
            "confidence_score": 100,
            "accepted_rows": 10,
            "rejected_rows": 0,
            "warnings": 0,
            "duplicates": 0,
            "missing_required_fields": 0,
            "inconsistent_names": 0,
            "suspicious_values": 0,
            "warning_summary": "",
        },
        heading="Projected data quality and trust",
    )

    assert info_calls == []