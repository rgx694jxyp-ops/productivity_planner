import pytest

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

    def _batch_upsert(records, *, tenant_id=""):
        captured["records"] = records
        captured["tenant_id"] = tenant_id

    monkeypatch.setattr("services.activity_records_service.activity_records_repo.batch_upsert_activity_records", _batch_upsert)

    count = ingest_activity_records_from_import(
        uph_rows=[{"tenant_id": "tenant-a", "emp_id": "E1", "work_date": "2026-04-10", "department": "Packing", "uph": 88}],
        tenant_id="tenant-a",
        source_import_job_id="import-2",
        data_quality_status="partial",
    )

    assert count == 1
    assert len(captured["records"]) == 1
    assert captured["tenant_id"] == "tenant-a"
    assert captured["records"][0]["source_import_job_id"] == "import-2"


def test_get_recent_activity_records_falls_back_to_legacy_history(monkeypatch):
    monkeypatch.setattr("services.activity_records_service.activity_records_repo.list_activity_records", lambda **kwargs: [])
    monkeypatch.setattr(
        "services.activity_records_service.import_repo.get_all_uph_history",
        lambda days=30, limit=0: [
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


# --------------------------------------------------------------------------- #
# CI-2: build_activity_records_from_import_rows must NOT forward tenant_id     #
#        from import-row data into the output payload                           #
# --------------------------------------------------------------------------- #

def test_build_activity_records_does_not_forward_row_tenant_id():
    """tenant_id from the CSV row must not be forwarded; repo stamps it from session."""
    rows = [
        {
            "tenant_id": "tenant-evil",
            "emp_id": "E1",
            "work_date": "2026-04-10",
            "department": "Packing",
            "uph": 90,
        }
    ]
    out = build_activity_records_from_import_rows(uph_rows=rows)
    assert len(out) == 1
    # The builder must not propagate an arbitrary tenant_id from row data
    assert "tenant_id" not in out[0] or out[0].get("tenant_id") == ""


# --------------------------------------------------------------------------- #
# CI-1: batch_upsert_activity_records must always stamp tenant_id from         #
#        session, ignoring any tenant_id already present in the records         #
# --------------------------------------------------------------------------- #

def test_batch_upsert_stamps_tenant_id_from_session(monkeypatch):
    """Records with a foreign tenant_id in payload[0] must be overwritten."""
    captured = {}

    def _fake_upsert(chunk, on_conflict=None):
        captured["chunk"] = chunk

        class _R:
            pass

        return type("Q", (), {"execute": lambda self: _R()})()

    class _FakeTable:
        def upsert(self, chunk, on_conflict=None):
            captured["chunk"] = chunk

            class _Q:
                def execute(self):
                    pass

            return _Q()

    class _FakeSB:
        def table(self, name):
            return _FakeTable()

    monkeypatch.setattr("repositories.activity_records_repo.get_client", lambda: _FakeSB())
    monkeypatch.setattr("repositories.activity_records_repo.require_tenant", lambda tenant_id="": "session-tenant")

    from repositories.activity_records_repo import batch_upsert_activity_records

    batch_upsert_activity_records([
        {"tenant_id": "tenant-evil", "employee_id": "E1", "activity_date": "2026-04-10", "process_name": "Pack"},
        {"tenant_id": "tenant-evil", "employee_id": "E2", "activity_date": "2026-04-10", "process_name": "Ship"},
    ])

    for row in captured["chunk"]:
        assert row["tenant_id"] == "session-tenant", (
            f"Expected session-tenant but got {row['tenant_id']!r}"
        )


def test_batch_upsert_uses_large_chunks_for_commit_path(monkeypatch):
    captured_chunks = []

    class _FakeTable:
        def upsert(self, chunk, on_conflict=None):
            captured_chunks.append((len(chunk), on_conflict))

            class _Q:
                def execute(self):
                    pass

            return _Q()

    class _FakeSB:
        def table(self, name):
            assert name == "activity_records"
            return _FakeTable()

    monkeypatch.setattr("repositories.activity_records_repo.get_client", lambda: _FakeSB())
    monkeypatch.setattr("repositories.activity_records_repo.require_tenant", lambda tenant_id="": "session-tenant")

    from repositories.activity_records_repo import batch_upsert_activity_records

    records = [
        {
            "employee_id": f"E{index}",
            "activity_date": "2026-04-10",
            "process_name": "Pack",
        }
        for index in range(2501)
    ]

    batch_upsert_activity_records(records)

    assert captured_chunks == [
        (2000, "tenant_id,employee_id,activity_date,process_name"),
        (501, "tenant_id,employee_id,activity_date,process_name"),
    ]


# --------------------------------------------------------------------------- #
# CI-3: legacy fallback with employee_id filter must use unbounded fetch        #
# --------------------------------------------------------------------------- #

def test_legacy_fallback_uses_unbounded_fetch_when_employee_id_given(monkeypatch):
    """When employee_id is specified, limit=0 is passed so employee rows past
    position 500 in the full result are not silently truncated."""
    captured = {}

    monkeypatch.setattr(
        "services.activity_records_service.activity_records_repo.list_activity_records",
        lambda **kwargs: [],
    )

    def _fake_uph_history(days=30, limit=0):
        captured["limit"] = limit
        return [{"emp_id": "E99", "work_date": "2026-04-01", "department": "Pack", "units": 1, "hours_worked": 1, "uph": 1}]

    monkeypatch.setattr("services.activity_records_service.import_repo.get_all_uph_history", _fake_uph_history)

    rows = get_recent_activity_records(employee_id="E99", days=14)
    assert captured["limit"] == 0, "Expected unbounded fetch (limit=0) when employee_id is specified"
    assert len(rows) == 1
    assert rows[0]["employee_id"] == "E99"


def test_legacy_fallback_uses_bounded_fetch_without_employee_id(monkeypatch):
    """Without employee_id, the limit cap is preserved to avoid over-fetching."""
    captured = {}

    monkeypatch.setattr(
        "services.activity_records_service.activity_records_repo.list_activity_records",
        lambda **kwargs: [],
    )

    def _fake_uph_history(days=30, limit=0):
        captured["limit"] = limit
        return []

    monkeypatch.setattr("services.activity_records_service.import_repo.get_all_uph_history", _fake_uph_history)

    get_recent_activity_records(days=14, limit=200)
    assert captured["limit"] == 200
