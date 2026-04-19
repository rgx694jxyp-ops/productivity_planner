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


def test_preview_import_surfaces_fallback_date_warning_summary(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "review_mapping",
        lambda mapping: MappingReview(mapped={"EmployeeID": "EmployeeID", "Date": "Date"}, required_missing=[], optional_unmapped=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "parse_sessions_to_rows",
        lambda sessions, fallback_date: [{
            "emp_id": "E1",
            "work_date": fallback_date.isoformat(),
            "department": "Pack",
            "uph": 80,
            "units": 160,
            "hours_worked": 2,
            "row_index": 1,
            "_used_fallback_date": True,
            "_raw_date_value": "04/10/2026",
        }],
    )
    monkeypatch.setattr(
        orchestrator,
        "validate_rows",
        lambda rows: (
            [{k: v for k, v in rows[0].items() if not str(k).startswith("_")}],
            [
                orchestrator.ImportIssue(
                    code="date_parse_fallback",
                    message="Date missing or unparseable; used selected work date",
                    severity="warning",
                    row_index=1,
                    field="Date",
                    value="04/10/2026",
                )
            ],
            0,
        ),
    )
    monkeypatch.setattr(orchestrator, "_find_matching_upload_by_fingerprint", lambda tenant_id, fingerprint, days=3650: None)

    result = orchestrator.preview_import(
        [{"mapping": {"EmployeeID": "EmployeeID", "Date": "Date"}}],
        fallback_date=date(2026, 4, 10),
        tenant_id="tenant-a",
        user_role="manager",
    )

    assert result.success is True
    assert result.trust_summary.warning_summary == "Some row dates could not be parsed and used the selected work date instead."
