from services import upgrade_telemetry_service as telemetry


def test_build_upgrade_event_payload_normalizes_schema():
    payload = telemetry.build_upgrade_event_payload(
        prompt_location="Import",
        prompt_type="Capacity",
        current_plan="Pro",
        employee_count="12",
        employee_limit="100",
        feature_context="import_entry",
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert payload == {
        "prompt_location": "import",
        "prompt_type": "capacity",
        "current_plan": "pro",
        "employee_count": 12,
        "employee_limit": 100,
        "feature_context": "import_entry",
        "tenant_id": "tenant-a",
        "user_id": "user-a",
    }


def test_log_upgrade_event_uses_operational_logger(monkeypatch):
    calls = []

    monkeypatch.setattr(
        telemetry,
        "log_operational_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)),
    )

    payload = telemetry.log_upgrade_event(
        "upgrade_prompt_click",
        prompt_location="productivity",
        prompt_type="feature_locked",
        current_plan="starter",
        employee_count=0,
        employee_limit=0,
        feature_context="advanced_productivity:monitor",
        tenant_id="tenant-a",
        user_id="user-a",
        user_email="lead@example.com",
    )

    assert payload["prompt_location"] == "productivity"
    assert len(calls) == 1
    assert calls[0][0] == "upgrade_prompt_click"
    assert calls[0][1]["tenant_id"] == "tenant-a"
    assert calls[0][1]["user_email"] == "lead@example.com"
    assert calls[0][1]["context"]["feature_context"] == "advanced_productivity:monitor"


def test_log_upgrade_prompt_impression_once_dedupes(monkeypatch):
    calls = []
    session_state = {}

    monkeypatch.setattr(
        telemetry,
        "log_operational_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)),
    )

    first = telemetry.log_upgrade_prompt_impression_once(
        session_state,
        event_key="import_capacity_prompt",
        prompt_location="import",
        prompt_type="capacity",
        current_plan="starter",
        employee_count=22,
        employee_limit=25,
        feature_context="import_entry:info",
        tenant_id="tenant-a",
        user_id="user-a",
        user_email="lead@example.com",
    )
    second = telemetry.log_upgrade_prompt_impression_once(
        session_state,
        event_key="import_capacity_prompt",
        prompt_location="import",
        prompt_type="capacity",
        current_plan="starter",
        employee_count=22,
        employee_limit=25,
        feature_context="import_entry:info",
        tenant_id="tenant-a",
        user_id="user-a",
        user_email="lead@example.com",
    )

    assert first is True
    assert second is False
    assert [name for name, _ in calls] == ["upgrade_prompt_impression"]


def test_log_upgrade_event_once_dedupes_plan_limit_events(monkeypatch):
    calls = []
    session_state = {}

    monkeypatch.setattr(
        telemetry,
        "log_operational_event",
        lambda event_type, **kwargs: calls.append((event_type, kwargs)),
    )

    telemetry.log_upgrade_event_once(
        session_state,
        "plan_limit_reached",
        event_key="header_limit_reached",
        prompt_location="header",
        prompt_type="capacity",
        current_plan="starter",
        employee_count=25,
        employee_limit=25,
        feature_context="plan_usage:at_limit",
        tenant_id="tenant-a",
        user_id="user-a",
    )
    telemetry.log_upgrade_event_once(
        session_state,
        "plan_limit_reached",
        event_key="header_limit_reached",
        prompt_location="header",
        prompt_type="capacity",
        current_plan="starter",
        employee_count=25,
        employee_limit=25,
        feature_context="plan_usage:at_limit",
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert [name for name, _ in calls] == ["plan_limit_reached"]