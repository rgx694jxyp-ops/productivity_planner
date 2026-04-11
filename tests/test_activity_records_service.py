from services.activity_records_service import (
    build_activity_records_from_import_rows,
    get_recent_activity_records,
    ingest_activity_records_from_import,
)


def test_build_activity_records_from_import_rows_maps_import_context():
    rows = [
        {
            "tenant_id": "tenant-a",
            "emp_id": "E1",
            "work_date": "2026-04-10",
            "department": "Packing",
            "units": 450,
            "hours_worked": 5,
            "uph": 90,
            "employee_name": "Alex",
        }
    ]

    out = build_activity_records_from_import_rows(
        uph_rows=rows,
        source_import_job_id="import-1",
        source_import_file="batch.csv",
        source_upload_id="44",
        data_quality_status="valid",
    )

    assert len(out) == 1
    assert out[0]["employee_id"] == "E1"
    assert out[0]["activity_date"] == "2026-04-10"
    assert out[0]["process_name"] == "Packing"
    assert out[0]["source_import_job_id"] == "import-1"
    assert out[0]["data_quality_status"] == "valid"
    assert out[0]["source_record_hash"]


def test_ingest_activity_records_from_import_calls_repo(monkeypatch):
    captured = {}

    def _batch_upsert(records):
        captured["records"] = records

    monkeypatch.setattr("services.activity_records_service.activity_records_repo.batch_upsert_activity_records", _batch_upsert)

    count = ingest_activity_records_from_import(
        uph_rows=[{"tenant_id": "tenant-a", "emp_id": "E1", "work_date": "2026-04-10", "department": "Packing", "uph": 88}],
        source_import_job_id="import-2",
        data_quality_status="partial",
    )

    assert count == 1
    assert len(captured["records"]) == 1
    assert captured["records"][0]["source_import_job_id"] == "import-2"


def test_get_recent_activity_records_falls_back_to_legacy_history(monkeypatch):
    monkeypatch.setattr("services.activity_records_service.activity_records_repo.list_activity_records", lambda **kwargs: [])
    monkeypatch.setattr(
        "services.activity_records_service.import_repo.get_all_uph_history",
        lambda days=30: [
            {
                "emp_id": "E9",
                "work_date": "2026-04-01",
                "department": "Shipping",
                "units": 300,
                "hours_worked": 4,
                "uph": 75,
            }
        ],
    )

    rows = get_recent_activity_records(days=14)

    assert len(rows) == 1
    assert rows[0]["employee_id"] == "E9"
    assert rows[0]["process_name"] == "Shipping"
    assert rows[0]["raw_context"]["legacy_source"] == "uph_history"
