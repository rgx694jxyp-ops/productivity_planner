from datetime import date

from services import import_service
from services.import_pipeline.models import ImportPreviewResult, ImportSummary, MappingReview
from services.import_pipeline import orchestrator


def test_sanitize_employee_name_flags_suspicious_input():
    name, suspicious = import_service._sanitize_employee_name("<script>alert(1)</script>", "E88")

    assert suspicious is True
    assert name == "Employee E88"


def test_build_candidate_uph_rows_aggregates_units_and_hours():
    sessions = [
        {
            "filename": "jan.csv",
            "mapping": {
                "EmployeeID": "EmployeeID",
                "Department": "Department",
                "Date": "Date",
                "Units": "Units",
                "HoursWorked": "HoursWorked",
                "UPH": "UPH",
            },
            "rows": [
                {"EmployeeID": "E1", "Department": "Pick", "Date": "2026-01-10", "Units": 120, "HoursWorked": 2, "UPH": ""},
                {"EmployeeID": "E1", "Department": "Pick", "Date": "2026-01-10", "Units": 80, "HoursWorked": 2, "UPH": ""},
            ],
        }
    ]

    out = import_service._build_candidate_uph_rows(sessions, fallback_date=date(2026, 1, 1))

    assert len(out) == 1
    row = out[0]
    assert row["emp_id"] == "E1"
    assert row["uph"] == 50.0
    assert row["units"] == 200
    assert row["hours_worked"] == 4.0


def test_import_fingerprint_stable_with_row_order_changes():
    rows_a = [
        {"emp_id": "E1", "work_date": "2026-01-01", "department": "Pick", "uph": 20, "units": 100, "hours_worked": 5},
        {"emp_id": "E2", "work_date": "2026-01-01", "department": "Pack", "uph": 30, "units": 120, "hours_worked": 4},
    ]
    rows_b = list(reversed(rows_a))

    fp_a = import_service._build_import_fingerprint(rows_a)
    fp_b = import_service._build_import_fingerprint(rows_b)

    assert fp_a
    assert fp_a == fp_b


def test_confirm_import_returns_safe_error_message(monkeypatch):
    preview = ImportPreviewResult(
        success=True,
        can_import=True,
        summary=ImportSummary(total_rows=1, valid_rows=1),
        mapping_review=MappingReview(),
        candidate_rows=[{"emp_id": "E1"}],
        invalid_issues=[],
        fingerprint="abc",
        message="Ready",
    )

    monkeypatch.setattr(orchestrator, "persist_import_rows", lambda rows, tenant_id: (_ for _ in ()).throw(RuntimeError("password=secret")))

    result = orchestrator.confirm_import(preview, tenant_id="tenant-a", upload_name="batch.csv")

    assert result.success is False
    assert result.issues[0].message == "Import failed while saving data."
    assert "password=secret" not in result.message
