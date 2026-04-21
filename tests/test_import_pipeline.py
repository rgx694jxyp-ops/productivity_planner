from datetime import date

from services import import_service
from services.import_pipeline.models import ImportPreviewResult, ImportSummary, MappingReview
from services.import_pipeline import orchestrator
from services.import_pipeline.parser import parse_sessions_to_rows
from services.import_pipeline.validator import validate_rows


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

    result = orchestrator.confirm_import(preview, tenant_id="tenant-a", upload_name="batch.csv", user_role="manager")

    assert result.success is False
    assert result.issues[0].message == "Import failed while saving data."
    assert "password=secret" not in result.message


def test_preview_import_blocks_exact_duplicate_file(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "review_mapping",
        lambda mapping: MappingReview(mapped={"EmployeeID": "EmployeeID"}, required_missing=[], optional_unmapped=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "parse_sessions_to_rows",
        lambda sessions, fallback_date: [{"emp_id": "E1", "work_date": "2026-04-10", "department": "Pack", "uph": 80, "units": 160, "hours_worked": 2}],
    )
    monkeypatch.setattr(
        orchestrator,
        "validate_rows",
        lambda rows: (rows, [], 0),
    )
    monkeypatch.setattr(
        orchestrator,
        "_find_matching_upload_by_fingerprint",
        lambda tenant_id, fingerprint, days=3650: {"id": 99},
    )

    result = orchestrator.preview_import(
        [{"mapping": {"EmployeeID": "EmployeeID"}}],
        fallback_date=date(2026, 4, 10),
        tenant_id="tenant-a",
        user_role="manager",
    )

    assert result.success is True
    assert result.can_import is False
    assert result.exact_duplicate_import is True
    assert "identical to a previous import" in result.message.lower()


def test_preview_import_has_no_warning_summary_for_clean_rows(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "review_mapping",
        lambda mapping: MappingReview(mapped={"EmployeeID": "EmployeeID"}, required_missing=[], optional_unmapped=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "parse_sessions_to_rows",
        lambda sessions, fallback_date: [{
            "emp_id": "E1",
            "work_date": "2026-04-10",
            "department": "Pack",
            "uph": 80,
            "units": 160,
            "hours_worked": 2,
        }],
    )
    monkeypatch.setattr(orchestrator, "validate_rows", lambda rows: (rows, [], 0))
    monkeypatch.setattr(orchestrator, "_find_matching_upload_by_fingerprint", lambda tenant_id, fingerprint, days=3650: None)

    result = orchestrator.preview_import(
        [{"mapping": {"EmployeeID": "EmployeeID"}}],
        fallback_date=date(2026, 4, 10),
        tenant_id="tenant-a",
        user_role="manager",
    )

    assert result.success is True
    assert result.trust_summary.warning_summary == ""


def test_find_matching_upload_by_fingerprint_reuses_cached_result(monkeypatch):
    calls = {"execute": 0}

    class _UploadedFilesQuery:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def gte(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def execute(self):
            calls["execute"] += 1

            class _Resp:
                data = [
                    {
                        "id": 101,
                        "header_mapping": {"data_fingerprint": "fp-1"},
                        "is_active": True,
                        "created_at": "2026-04-10T12:00:00",
                    }
                ]

            return _Resp()

    class _FakeClient:
        def table(self, name):
            assert name == "uploaded_files"
            return _UploadedFilesQuery()

    monkeypatch.setattr(orchestrator, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(orchestrator, "tenant_query", lambda query: query)
    monkeypatch.setattr("services.settings_service.get_tenant_local_now", lambda tenant_id: date(2026, 4, 10))
    monkeypatch.setattr(orchestrator, "_UPLOAD_FINGERPRINT_CACHE", {})

    first = orchestrator._find_matching_upload_by_fingerprint("tenant-a", "fp-1")
    second = orchestrator._find_matching_upload_by_fingerprint("tenant-a", "fp-1")

    assert first["id"] == 101
    assert second["id"] == 101
    assert calls["execute"] == 1


def test_parse_sessions_to_rows_normalizes_common_non_iso_date_values():
    sessions = [
        {
            "filename": "batch.csv",
            "mapping": {
                "EmployeeID": "EmployeeID",
                "EmployeeName": "EmployeeName",
                "Department": "Department",
                "Date": "Date",
                "Units": "Units",
                "HoursWorked": "HoursWorked",
            },
            "rows": [
                {
                    "EmployeeID": "E1",
                    "EmployeeName": "Alex",
                    "Department": "Pick",
                    "Date": "04/10/2026",
                    "Units": "120",
                    "HoursWorked": "2",
                }
            ],
        }
    ]

    parsed = parse_sessions_to_rows(sessions, fallback_date=date(2026, 1, 1))

    assert len(parsed) == 1
    assert parsed[0]["work_date"] == "2026-04-10"


def test_parse_sessions_to_rows_invalid_mapped_dates_do_not_fallback_to_selected_date():
    sessions = [
        {
            "filename": "batch.csv",
            "mapping": {
                "EmployeeID": "EmployeeID",
                "EmployeeName": "EmployeeName",
                "Department": "Department",
                "Date": "Date",
                "Units": "Units",
                "HoursWorked": "HoursWorked",
            },
            "rows": [
                {
                    "EmployeeID": "E1",
                    "EmployeeName": "Alex",
                    "Department": "Pick",
                    "Date": "not-a-date",
                    "Units": "120",
                    "HoursWorked": "2",
                }
            ],
        }
    ]

    parsed = parse_sessions_to_rows(sessions, fallback_date=date(2026, 4, 10))
    candidates, issues, duplicate_rows = validate_rows(parsed)

    assert candidates == []
    assert duplicate_rows == 0
    assert any(issue.code == "invalid_date" for issue in issues)


def test_validate_rows_mixed_valid_invalid_rows_has_deterministic_exclusions_and_candidates():
    parsed_rows = [
        {
            "row_index": 1,
            "emp_id": "E1",
            "employee_name": "Alex",
            "department": "Pick",
            "work_date": "2026-04-10",
            "units": 100.0,
            "hours_worked": 2.0,
            "uph": None,
            "_date_parse_error": "",
            "_raw_date_value": "2026-04-10",
            "_raw_units_value": "100",
            "_raw_hours_worked_value": "2",
            "_raw_uph_value": "",
        },
        {
            "row_index": 2,
            "emp_id": "E1",
            "employee_name": "Alex",
            "department": "Pick",
            "work_date": "2026-04-10",
            "units": 100.0,
            "hours_worked": 2.0,
            "uph": 55.0,
            "_date_parse_error": "",
            "_raw_date_value": "2026-04-10",
            "_raw_units_value": "100",
            "_raw_hours_worked_value": "2",
            "_raw_uph_value": "55",
        },
        {
            "row_index": 3,
            "emp_id": "",
            "employee_name": "No ID",
            "department": "Pick",
            "work_date": "2026-04-10",
            "units": 100.0,
            "hours_worked": 2.0,
            "uph": None,
            "_date_parse_error": "",
            "_raw_date_value": "2026-04-10",
            "_raw_units_value": "100",
            "_raw_hours_worked_value": "2",
            "_raw_uph_value": "",
        },
        {
            "row_index": 4,
            "emp_id": "E2",
            "employee_name": "Missing Date",
            "department": "Pick",
            "work_date": "",
            "units": 100.0,
            "hours_worked": 2.0,
            "uph": None,
            "_date_parse_error": "missing",
            "_raw_date_value": "",
            "_raw_units_value": "100",
            "_raw_hours_worked_value": "2",
            "_raw_uph_value": "",
        },
        {
            "row_index": 5,
            "emp_id": "E3",
            "employee_name": "Bad Date",
            "department": "Pick",
            "work_date": "",
            "units": 100.0,
            "hours_worked": 2.0,
            "uph": None,
            "_date_parse_error": "unparseable",
            "_raw_date_value": "not-a-date",
            "_raw_units_value": "100",
            "_raw_hours_worked_value": "2",
            "_raw_uph_value": "",
        },
        {
            "row_index": 6,
            "emp_id": "E4",
            "employee_name": "Bad Units",
            "department": "Pick",
            "work_date": "2026-04-10",
            "units": None,
            "hours_worked": 2.0,
            "uph": None,
            "_date_parse_error": "",
            "_raw_date_value": "2026-04-10",
            "_raw_units_value": "abc",
            "_raw_hours_worked_value": "2",
            "_raw_uph_value": "",
        },
    ]

    candidates, issues, duplicate_rows = validate_rows(parsed_rows)

    assert duplicate_rows == 1
    assert len(candidates) == 1
    assert candidates[0]["emp_id"] == "E1"
    assert candidates[0]["work_date"] == "2026-04-10"
    assert candidates[0]["units"] == 200
    assert candidates[0]["hours_worked"] == 4.0
    assert candidates[0]["uph"] == 55.0

    issue_codes = [issue.code for issue in issues]
    assert "missing_emp_id" in issue_codes
    assert "missing_date" in issue_codes
    assert "invalid_date" in issue_codes
    assert "invalid_units" in issue_codes


def test_validate_rows_invalid_numeric_reason_preserves_raw_value():
    parsed_rows = [
        {
            "row_index": 1,
            "emp_id": "E9",
            "employee_name": "Raw Value",
            "department": "Pack",
            "work_date": "2026-04-10",
            "units": None,
            "hours_worked": 3.0,
            "uph": None,
            "_date_parse_error": "",
            "_raw_date_value": "2026-04-10",
            "_raw_units_value": "not_a_number",
            "_raw_hours_worked_value": "3",
            "_raw_uph_value": "",
        }
    ]

    candidates, issues, duplicate_rows = validate_rows(parsed_rows)

    assert candidates == []
    assert duplicate_rows == 0
    assert len(issues) == 1
    assert issues[0].code == "invalid_units"
    assert issues[0].value == "not_a_number"
