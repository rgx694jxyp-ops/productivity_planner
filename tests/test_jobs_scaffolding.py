from jobs.entrypoints import run_import_postprocess_job
from jobs.runner import execute_job_with_meta
from jobs.types import JobRequest


def test_job_runner_executes_sync_mode_inline():
    value, meta = execute_job_with_meta(
        JobRequest(name="test.sync", run_mode="sync"),
        lambda: 42,
    )

    assert value == 42
    assert meta.name == "test.sync"
    assert meta.requested_mode == "sync"
    assert meta.executed_mode == "sync"
    assert meta.backend == "inline"


def test_job_runner_accepts_async_request_but_executes_sync_for_now():
    value, meta = execute_job_with_meta(
        JobRequest(name="test.async", run_mode="async"),
        lambda: "ok",
    )

    assert value == "ok"
    assert meta.requested_mode == "async"
    assert meta.executed_mode == "sync"


def test_import_postprocess_job_runs_ingest_and_snapshot(monkeypatch):
    calls = []

    def _fake_ingest(**kwargs):
        calls.append(("ingest", kwargs))
        return 7

    def _fake_recompute(**kwargs):
        calls.append(("snapshot", kwargs))
        return {"inserted": 3}

    monkeypatch.setattr("jobs.entrypoints.ingest_activity_records_from_import", _fake_ingest)
    monkeypatch.setattr("jobs.entrypoints.recompute_daily_employee_snapshots", _fake_recompute)

    out = run_import_postprocess_job(
        uph_rows=[{"emp_id": "E1", "work_date": "2026-04-01"}],
        tenant_id="tenant-a",
        source_import_job_id="job-1",
        source_import_file="batch.csv",
        source_upload_id="upload-1",
        data_quality_status="partial",
        exclusion_note="",
        handling_choice="review_details",
        handling_note="note",
        from_date="2026-04-01",
        to_date="2026-04-01",
    )

    assert out["ingested_count"] == 7
    assert out["snapshot_result"]["inserted"] == 3
    assert [name for name, _ in calls] == ["ingest", "snapshot"]
