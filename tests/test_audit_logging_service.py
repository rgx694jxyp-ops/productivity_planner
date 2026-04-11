from datetime import date


def test_import_job_entrypoints_emit_started_and_completed_events(monkeypatch):
    from jobs import entrypoints

    events = []

    monkeypatch.setattr(
        entrypoints,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    class _PreviewResult:
        can_import = True

        class summary:
            valid_rows = 12
            invalid_rows = 1

    monkeypatch.setattr(entrypoints, "preview_import", lambda *args, **kwargs: _PreviewResult())

    preview = entrypoints.run_import_preview_job(
        sessions=[{"rows": []}],
        fallback_date=date(2026, 4, 10),
        tenant_id="tenant-a",
        user_role="manager",
    )
    assert preview.can_import is True

    event_names = [name for name, _ in events]
    assert event_names.count("import_started") == 1
    assert event_names.count("import_completed") == 1


def test_import_postprocess_emits_issue_and_excluded_decision_events(monkeypatch):
    from jobs import entrypoints

    events = []
    monkeypatch.setattr(
        entrypoints,
        "log_operational_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )
    monkeypatch.setattr(entrypoints, "ingest_activity_records_from_import", lambda **kwargs: 3)
    monkeypatch.setattr(entrypoints, "recompute_daily_employee_snapshots", lambda **kwargs: {"inserted": 2})

    out = entrypoints.run_import_postprocess_job(
        uph_rows=[{"emp_id": "E1", "work_date": "2026-04-10"}],
        tenant_id="tenant-a",
        source_import_job_id="job-1",
        source_import_file="batch.csv",
        source_upload_id="upload-1",
        data_quality_status="partial",
        exclusion_note="duplicates_skipped=1",
        handling_choice="ignore_rows",
        handling_note="reviewed",
        from_date="2026-04-10",
        to_date="2026-04-10",
    )

    assert out["ingested_count"] == 3
    event_names = [name for name, _ in events]
    assert "import_issue_handling_choice" in event_names
    assert "import_excluded_data_decision" in event_names


def test_target_changes_emit_audit_events(monkeypatch):
    import goals

    data = goals._empty_goals()
    events = []

    monkeypatch.setattr(goals, "load_goals", lambda tenant_id="": dict(data))
    monkeypatch.setattr(goals, "save_goals", lambda payload, tenant_id="": data.update(payload))
    monkeypatch.setattr(goals, "_log_target_change", lambda event_type, **kwargs: events.append((event_type, kwargs)))

    goals.set_default_target(90, tenant_id="tenant-a")
    goals.set_process_target("Packing", 95, tenant_id="tenant-a")
    goals.set_employee_target_override("E1", 100, process_name="Packing", tenant_id="tenant-a")

    assert len(events) == 3
    assert all(name == "target_changed" for name, _ in events)


def test_exception_create_and_resolve_emit_audit_events(monkeypatch):
    from services import exception_tracking_service as svc

    events = []
    monkeypatch.setattr(svc, "log_operational_event", lambda event_type, **kwargs: events.append((event_type, kwargs)))
    monkeypatch.setattr(
        svc.operational_exceptions_repo,
        "create_operational_exception",
        lambda **kwargs: {"id": 7, **kwargs},
    )
    monkeypatch.setattr(
        svc.operational_exceptions_repo,
        "resolve_operational_exception",
        lambda *args, **kwargs: {"id": args[0], "status": "resolved"},
    )

    created = svc.create_operational_exception(
        exception_date="2026-04-10",
        category="equipment",
        summary="Scanner downtime",
        tenant_id="tenant-a",
        user_role="manager",
    )
    assert created.get("id") == 7

    resolved = svc.resolve_operational_exception("7", tenant_id="tenant-a", resolved_by="lead@example.com")
    assert resolved.get("status") == "resolved"

    event_names = [name for name, _ in events]
    assert "exception_created" in event_names
    assert "exception_resolved" in event_names


def test_action_event_and_completion_emit_audit_events(monkeypatch):
    from services import action_lifecycle_service as svc

    events = []
    monkeypatch.setattr(svc, "log_operational_event", lambda event_type, **kwargs: events.append((event_type, kwargs)))
    monkeypatch.setattr(svc.action_events_repo, "log_action_event", lambda **kwargs: {"id": 11, **kwargs})
    monkeypatch.setattr(svc.actions_repo, "update_action", lambda **kwargs: {"id": kwargs.get("action_id"), "status": "resolved"})

    event = svc.log_action_event(
        action_id="a-1",
        event_type="coached",
        employee_id="E1",
        tenant_id="tenant-a",
    )
    assert event.get("id") == 11

    resolved = svc.mark_action_resolved(
        action_id="a-1",
        resolution_type="improved",
        tenant_id="tenant-a",
    )
    assert resolved.get("status") == "resolved"

    event_names = [name for name, _ in events]
    assert "action_event_created" in event_names
    assert "action_completed" in event_names
