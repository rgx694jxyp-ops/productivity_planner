from services.exception_tracking_service import (
    build_exception_context_line,
    summarize_open_operational_exceptions,
)


def test_summarize_open_operational_exceptions_groups_categories(monkeypatch):
    rows = [
        {"id": 1, "category": "equipment", "employee_id": "E1"},
        {"id": 2, "category": "equipment", "employee_id": "E1"},
        {"id": 3, "category": "training", "employee_id": "E2"},
        {"id": 4, "category": "training", "employee_id": ""},
    ]

    monkeypatch.setattr(
        "services.exception_tracking_service.list_open_operational_exceptions",
        lambda tenant_id="", employee_id="", limit=100: rows,
    )

    summary = summarize_open_operational_exceptions(tenant_id="tenant-a")

    assert summary["open_count"] == 4
    assert summary["linked_employee_count"] == 2
    assert summary["categories"]["equipment"] == 2
    assert summary["categories"]["training"] == 2


def test_create_operational_exception_rejects_blank_summary():
    created = []

    def _create(**kwargs):
        created.append(kwargs)
        return {"id": 1}

    from services import exception_tracking_service

    original = exception_tracking_service.operational_exceptions_repo.create_operational_exception
    exception_tracking_service.operational_exceptions_repo.create_operational_exception = _create
    try:
        out = exception_tracking_service.create_operational_exception(
            exception_date="2026-04-09",
            category="equipment",
            summary="   ",
            tenant_id="tenant-a",
            user_role="manager",
        )
    finally:
        exception_tracking_service.operational_exceptions_repo.create_operational_exception = original

    assert out == {}
    assert created == []


def test_build_exception_context_line_joins_available_context():
    line = build_exception_context_line(
        {
            "exception_date": "2026-04-09",
            "shift": "Day",
            "process_name": "Receiving",
            "category": "equipment",
        }
    )

    assert line == "2026-04-09 | Day | Receiving | equipment"
