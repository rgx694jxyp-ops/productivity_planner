from pages import import_page
from pages import today
from datetime import date


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def test_load_sample_demo_into_import_state_emits_import_started(monkeypatch):
    session_state = _SessionState(
        {
        "import_entry_mode": "Try sample data",
        "user_email": "ops@example.com",
        "_onboarding_correlation_id": "corr-123",
        }
    )
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(
        import_page,
        "_build_sample_demo_sessions",
        lambda **kwargs: [{"filename": "sample/demo_supervisor_history.csv", "source_mode": "demo", "row_count": 10}],
    )
    monkeypatch.setattr(
        import_page,
        "_log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    loaded = import_page._load_sample_demo_into_import_state(tenant_id="tenant-1", trigger="auto_onboarding")

    assert loaded is True
    assert session_state["import_step"] == 3
    assert events
    assert events[0][0] == "import_started"
    assert events[0][1]["context"]["import_path"] == "sample"
    assert events[0][1]["context"]["trigger"] == "auto_onboarding"
    assert events[0][1]["context"]["onboarding_correlation_id"] == "corr-123"


def test_emit_import_started_once_dedupes_same_sample_session(monkeypatch):
    session_state = _SessionState(
        {
            "uploaded_sessions": [{"filename": "sample/demo.csv", "row_count": 10, "source_mode": "demo", "timestamp": "2026-04-13 23:00"}],
            "import_entry_mode": "Try sample data",
            "user_email": "ops@example.com",
            "_onboarding_correlation_id": "corr-123",
        }
    )
    events: list[str] = []

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(import_page, "_emit_import_funnel_event", lambda event_type, **kwargs: events.append(event_type))

    first = import_page._emit_import_started_once(
        tenant_id="tenant-1",
        trigger="auto_onboarding_resume",
        sessions=session_state["uploaded_sessions"],
        context={"source_mode": "demo"},
    )
    second = import_page._emit_import_started_once(
        tenant_id="tenant-1",
        trigger="auto_onboarding_resume",
        sessions=session_state["uploaded_sessions"],
        context={"source_mode": "demo"},
    )

    assert first is True
    assert second is False
    assert events == ["import_started"]


def test_emit_first_insight_rendered_once_dedupes(monkeypatch):
    session_state = _SessionState({"import_entry_mode": "Try sample data", "user_email": "ops@example.com", "_onboarding_correlation_id": "corr-123"})
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(import_page, "_emit_import_funnel_event", lambda event_type, **kwargs: events.append((event_type, kwargs)))

    summary = {"import_job": {"job_id": "job-123"}, "source_mode": "demo", "rows_processed": 42}
    import_page._emit_first_insight_rendered_once(tenant_id="tenant-1", summary=summary)
    import_page._emit_first_insight_rendered_once(tenant_id="tenant-1", summary=summary)

    assert [event for event, _ in events] == ["first_insight_rendered"]
    assert events[0][1]["context"]["source_mode"] == "demo"


def test_onboarding_sample_auto_load_triggers_once(monkeypatch):
    session_state = {
        import_page._AUTO_LOAD_SAMPLE_ONBOARDING_FLAG: True,
    }
    load_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(
        import_page,
        "_load_sample_demo_into_import_state",
        lambda **kwargs: load_calls.append(str(kwargs.get("tenant_id", ""))) or True,
    )

    first_trigger = import_page._consume_sample_onboarding_auto_load(mode="Try sample data", tenant_id="tenant-1")
    second_trigger = import_page._consume_sample_onboarding_auto_load(mode="Try sample data", tenant_id="tenant-1")

    assert first_trigger is True
    assert second_trigger is False
    assert load_calls == ["tenant-1"]
    assert import_page._AUTO_LOAD_SAMPLE_ONBOARDING_FLAG not in session_state


def test_onboarding_sample_auto_load_sets_auto_pipeline_flag(monkeypatch):
    session_state = _SessionState(
        {
            import_page._AUTO_LOAD_SAMPLE_ONBOARDING_FLAG: True,
        }
    )

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(
        import_page,
        "_build_sample_demo_sessions",
        lambda **kwargs: [{"filename": "sample/demo_supervisor_history.csv", "source_mode": "demo", "row_count": 10}],
    )
    monkeypatch.setattr(import_page, "_emit_import_funnel_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_page, "reset_demo_uploads", lambda **kwargs: {"demo_uploads_reset": 0})
    monkeypatch.setattr(import_page, "_bust_cache", lambda: None)

    triggered = import_page._consume_sample_onboarding_auto_load(mode="Try sample data", tenant_id="tenant-1")

    assert triggered is True
    assert session_state[import_page._AUTO_RUN_SAMPLE_PIPELINE_ONCE_FLAG] is True


def test_consume_auto_run_sample_pipeline_once_sets_confirm_preview(monkeypatch):
    session_state = _SessionState(
        {
            import_page._AUTO_RUN_SAMPLE_PIPELINE_ONCE_FLAG: True,
        }
    )

    monkeypatch.setattr(import_page.st, "session_state", session_state)

    first = import_page._consume_auto_run_sample_pipeline_once()
    second = import_page._consume_auto_run_sample_pipeline_once()

    assert first is True
    assert second is False
    assert session_state["confirm_import_preview"] is True


def test_load_sample_demo_resets_existing_demo_history(monkeypatch):
    session_state = _SessionState({"import_entry_mode": "Try sample data", "user_email": "ops@example.com"})
    reset_calls: list[str] = []
    bust_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(import_page, "reset_demo_uploads", lambda **kwargs: reset_calls.append(str(kwargs.get("tenant_id", ""))) or {"demo_uploads_reset": 1})
    monkeypatch.setattr(import_page, "_bust_cache", lambda: bust_calls.append("bust"))
    monkeypatch.setattr(
        import_page,
        "_build_sample_demo_sessions",
        lambda **kwargs: [{"filename": "sample/demo_supervisor_history.csv", "source_mode": "demo", "row_count": 10}],
    )
    monkeypatch.setattr(import_page, "_log_operational_event", lambda *args, **kwargs: None)

    loaded = import_page._load_sample_demo_into_import_state(tenant_id="tenant-1", trigger="manual")

    assert loaded is True
    assert reset_calls == ["tenant-1"]
    assert bust_calls == ["bust"]


def test_redirect_existing_sample_data_to_today_sets_flash_and_route(monkeypatch):
    session_state = _SessionState({"user_email": "ops@example.com"})
    events: list[str] = []
    flashes: list[str] = []

    class _RerunTriggered(Exception):
        pass

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(import_page, "set_flash_message", lambda msg: flashes.append(str(msg)))
    monkeypatch.setattr(import_page, "_emit_import_funnel_event", lambda event_type, **kwargs: events.append(event_type))
    monkeypatch.setattr(import_page.st, "rerun", lambda: (_ for _ in ()).throw(_RerunTriggered()))

    try:
        import_page._redirect_existing_sample_data_to_today(tenant_id="tenant-1", candidate_rows=576)
    except _RerunTriggered:
        pass

    assert session_state["goto_page"] == "today"
    assert session_state["_first_import_just_completed"] is True
    assert flashes == ["Sample data is already available in this workspace. Reusing 576 prepared rows and opening Today."]
    assert events == ["import_preview_completed"]


def test_today_loaded_with_data_includes_onboarding_correlation(monkeypatch):
    session_state = _SessionState({"user_email": "ops@example.com", "_onboarding_correlation_id": "corr-123"})
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(today.st, "session_state", session_state)
    monkeypatch.setattr(today, "_log_operational_event", lambda event_type, **kwargs: events.append((event_type, kwargs)))

    today._emit_today_loaded_with_data_once(
        tenant_id="tenant-1",
        import_summary={"source_mode": "demo"},
        queue_count=4,
    )

    assert events[0][0] == "today_loaded_with_data"
    assert events[0][1]["context"]["onboarding_correlation_id"] == "corr-123"
    assert events[0][1]["context"]["import_path"] == "sample"


def test_render_first_import_insight_highlight_adds_anchor_style(monkeypatch):
    markdown_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "markdown", lambda body, **kwargs: markdown_calls.append(str(body)))
    monkeypatch.setattr(import_page.st, "container", lambda **kwargs: type("_Ctx", (), {"__enter__": lambda self: self, "__exit__": lambda self, exc_type, exc, tb: False})())
    monkeypatch.setattr(import_page.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_page.st, "divider", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_page.st, "expander", lambda *args, **kwargs: type("_Ctx", (), {"__enter__": lambda self: self, "__exit__": lambda self, exc_type, exc, tb: False})())

    insight = {
        "what_happened": "Signal context is available.",
        "compared_to_what": "Compared with recent imported rows.",
        "why_shown": "Shown because confidence context is still building.",
        "confidence_label": "Low",
        "confidence_score": 45,
        "confidence_basis": "Limited baseline data.",
        "confidence_note": "Confidence improves as more days are imported.",
        "top_item": None,
        "is_healthy": False,
    }

    import_page._render_first_import_insight(insight, highlight=True)

    assert any("first-insight-anchor" in call for call in markdown_calls)
    assert any("background:#eef7ff" in call for call in markdown_calls)


def test_manual_import_users_do_not_auto_load_sample(monkeypatch):
    session_state = {}
    load_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(
        import_page,
        "_load_sample_demo_into_import_state",
        lambda **kwargs: load_calls.append(str(kwargs.get("tenant_id", ""))) or True,
    )

    triggered = import_page._consume_sample_onboarding_auto_load(mode="Try sample data", tenant_id="tenant-2")

    assert triggered is False
    assert load_calls == []


def test_shift_demo_rows_to_current_dates_aligns_latest_seed_day_to_today():
    rows = [
        {"Date": "2026-04-08", "EmployeeID": "EMP001"},
        {"Date": "2026-04-10", "EmployeeID": "EMP002"},
    ]

    shifted = import_page._shift_demo_rows_to_current_dates(
        rows=rows,
        date_column="Date",
        today_value=date(2026, 4, 18),
    )

    assert shifted[0]["Date"] == "2026-04-16"
    assert shifted[1]["Date"] == "2026-04-18"


def test_shift_seed_timestamp_fields_rolls_action_and_event_times_forward():
    actions_seed = [
        {
            "created_at": "2026-04-05T09:00:00Z",
            "follow_up_due_at": "2026-04-10T10:00:00Z",
            "last_event_at": "2026-04-09T11:30:00Z",
        }
    ]
    events_seed = [
        {
            "event_at": "2026-04-09T12:00:00Z",
            "next_follow_up_at": "2026-04-10T10:00:00Z",
        }
    ]

    shift_days = import_page._compute_demo_seed_shift_days(
        actions_seed=actions_seed,
        events_seed=events_seed,
        today_value=date(2026, 4, 18),
    )
    shifted_actions = import_page._shift_seed_timestamp_fields(
        records=actions_seed,
        fields=import_page._DEMO_ACTION_TIMESTAMP_FIELDS,
        shift_days=shift_days,
    )
    shifted_events = import_page._shift_seed_timestamp_fields(
        records=events_seed,
        fields=import_page._DEMO_EVENT_TIMESTAMP_FIELDS,
        shift_days=shift_days,
    )

    assert shift_days == 8
    assert shifted_actions[0]["created_at"] == "2026-04-13T09:00:00Z"
    assert shifted_actions[0]["follow_up_due_at"] == "2026-04-18T10:00:00Z"
    assert shifted_events[0]["event_at"] == "2026-04-17T12:00:00Z"
    assert shifted_events[0]["next_follow_up_at"] == "2026-04-18T10:00:00Z"


def test_non_sample_mode_does_not_auto_load_sample(monkeypatch):
    session_state = {
        import_page._AUTO_LOAD_SAMPLE_ONBOARDING_FLAG: True,
    }
    load_calls: list[str] = []

    monkeypatch.setattr(import_page.st, "session_state", session_state)
    monkeypatch.setattr(
        import_page,
        "_load_sample_demo_into_import_state",
        lambda **kwargs: load_calls.append(str(kwargs.get("tenant_id", ""))) or True,
    )

    triggered = import_page._consume_sample_onboarding_auto_load(mode="Upload file", tenant_id="tenant-3")

    assert triggered is False
    assert load_calls == []
    assert session_state[import_page._AUTO_LOAD_SAMPLE_ONBOARDING_FLAG] is True


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