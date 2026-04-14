from pages import today
from services.attention_scoring_service import AttentionSummary


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Column(_Ctx):
    pass


def test_has_today_data_false_when_roster_history_and_signals_are_all_absent(monkeypatch):
    monkeypatch.setattr(today, "_cached_employees", lambda: [])
    monkeypatch.setattr(today.st, "session_state", _SessionState({"tenant_id": "tenant-1"}))

    has_data = today._has_today_data(
        queue_items=[],
        goal_status=[],
        home_sections={"suppressed_signals": []},
        import_summary={"days": 0},
    )

    assert has_data is False


def test_has_today_data_true_when_history_exists_even_without_queue(monkeypatch):
    monkeypatch.setattr(today, "_cached_employees", lambda: [])
    monkeypatch.setattr(today.st, "session_state", _SessionState({"tenant_id": "tenant-1"}))

    has_data = today._has_today_data(
        queue_items=[],
        goal_status=[{"EmployeeID": "E1"}],
        home_sections={"suppressed_signals": []},
        import_summary={"days": 3},
    )

    assert has_data is True


def test_render_first_value_screen_routes_sample_data_to_import(monkeypatch):
    session_state = _SessionState({"tenant_id": "tenant-1"})
    markdown_calls: list[str] = []
    info_calls: list[str] = []
    events: list[str] = []

    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today.st, "container", lambda **kwargs: _Ctx())
    monkeypatch.setattr(today.st, "columns", lambda n: [_Column() for _ in range(n)])
    monkeypatch.setattr(today.st, "markdown", lambda body, **kwargs: markdown_calls.append(str(body)))
    monkeypatch.setattr(today.st, "write", lambda body, **kwargs: markdown_calls.append(str(body)))
    monkeypatch.setattr(today.st, "info", lambda body, **kwargs: info_calls.append(str(body)))
    monkeypatch.setattr(today.st, "button", lambda label, **kwargs: label == "Use sample data")
    monkeypatch.setattr(today, "_log_operational_event", lambda event_type, **kwargs: events.append(event_type))

    class _RerunTriggered(Exception):
        pass

    monkeypatch.setattr(today.st, "rerun", lambda: (_ for _ in ()).throw(_RerunTriggered()))

    try:
        today._render_first_value_screen()
    except _RerunTriggered:
        pass

    assert session_state["goto_page"] == "import"
    assert session_state["import_entry_mode"] == "Try sample data"
    assert any("Get to your first value" in call for call in markdown_calls)
    assert any("Today becomes useful" in call for call in markdown_calls)
    assert any("After import, Today returns to the normal queue automatically." in call for call in info_calls)
    assert "first_value_screen_shown" in events


def test_emit_today_loaded_with_data_once_dedupes(monkeypatch):
    session_state = _SessionState({"tenant_id": "tenant-1", "user_email": "ops@example.com"})
    events: list[str] = []

    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today, "_log_operational_event", lambda event_type, **kwargs: events.append(event_type))

    today._emit_today_loaded_with_data_once(
        tenant_id="tenant-1",
        import_summary={"source_mode": "demo"},
        queue_count=3,
    )
    today._emit_today_loaded_with_data_once(
        tenant_id="tenant-1",
        import_summary={"source_mode": "demo"},
        queue_count=3,
    )

    assert events == ["today_loaded_with_data"]


def test_render_first_value_screen_routes_file_upload_to_import(monkeypatch):
    session_state = _SessionState({"tenant_id": "tenant-1"})

    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today.st, "container", lambda **kwargs: _Ctx())
    monkeypatch.setattr(today.st, "columns", lambda n: [_Column() for _ in range(n)])
    monkeypatch.setattr(today.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "button", lambda label, **kwargs: label == "Upload your file")

    class _RerunTriggered(Exception):
        pass

    monkeypatch.setattr(today.st, "rerun", lambda: (_ for _ in ()).throw(_RerunTriggered()))

    try:
        today._render_first_value_screen()
    except _RerunTriggered:
        pass

    assert session_state["goto_page"] == "import"
    assert session_state["import_entry_mode"] == "Upload file"


def test_page_today_bypasses_queue_rendering_for_no_data_tenant(monkeypatch):
    session_state = _SessionState({"tenant_id": "tenant-1", "today_queue_filter": "all"})
    precomputed = {
        "queue_items": [],
        "goal_status": [],
        "import_summary": {"days": 0, "trust": {"status": "invalid", "confidence_score": 0}},
        "home_sections": {},
        "attention_summary": AttentionSummary(
            ranked_items=[],
            is_healthy=True,
            healthy_message="No important changes surfaced today.",
            suppressed_count=0,
            total_evaluated=0,
        ),
        "as_of_date": "",
    }
    first_value_calls: list[str] = []

    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today.st, "columns", lambda spec: [_Column() for _ in range(len(spec) if isinstance(spec, list) else spec)])
    monkeypatch.setattr(today.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(today.st, "spinner", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr(today.st, "empty", lambda: type("_Empty", (), {"container": lambda self: _Ctx(), "empty": lambda self: None})())
    monkeypatch.setattr(today.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(today.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_apply_today_styles", lambda: None)
    monkeypatch.setattr(today, "render_traceability_panel", lambda *args, **kwargs: None)
    monkeypatch.setattr(today, "_show_flash_message", lambda: None)
    monkeypatch.setattr(today, "get_today_signals", lambda **kwargs: precomputed)
    monkeypatch.setattr(today, "_cached_employees", lambda: [])
    monkeypatch.setattr(today, "_render_first_value_screen", lambda: first_value_calls.append("rendered"))
    monkeypatch.setattr(today, "_render_top_status_area", lambda **kwargs: (_ for _ in ()).throw(AssertionError("top status should not render")))
    monkeypatch.setattr(today, "_render_unified_attention_queue", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("queue should not render")))

    today.page_today()

    assert first_value_calls == ["rendered"]
    assert session_state["_ui_render_guard_active"] is False