from jobs.entrypoints import run_import_postprocess_job, run_import_postprocess_job_deferred
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
    assert calls[0][1]["tenant_id"] == "tenant-a"


def test_import_postprocess_job_deferred_queues_and_runs(monkeypatch):
    calls = []

    def _fake_postprocess(**kwargs):
        calls.append(kwargs)
        return {"ingested_count": 2, "snapshot_result": {}}

    class _InlineThread:
        def __init__(self, target=None, name=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    monkeypatch.setattr("jobs.entrypoints.run_import_postprocess_job", _fake_postprocess)
    monkeypatch.setattr("jobs.entrypoints.threading.Thread", _InlineThread)

    out = run_import_postprocess_job_deferred(
        uph_rows=[{"emp_id": "E1", "work_date": "2026-04-01"}],
        tenant_id="tenant-a",
        source_import_job_id="job-1",
        source_import_file="batch.csv",
        source_upload_id="upload-1",
        data_quality_status="partial",
        exclusion_note="",
        handling_choice="review_details",
        handling_note="note",
        from_date="",
        to_date="",
    )

    assert out["deferred"] is True
    assert out["queued"] is True
    assert len(calls) == 1


def test_import_postprocess_job_deferred_retries_sync_after_failure(monkeypatch):
    calls = {"postprocess": 0, "states": []}

    def _flaky_postprocess(**kwargs):
        calls["postprocess"] += 1
        if calls["postprocess"] == 1:
            raise RuntimeError("transient")
        return {"ingested_count": 2, "snapshot_result": {}}

    def _capture_state(**kwargs):
        calls["states"].append(str(kwargs.get("state") or ""))
        return True

    class _InlineThread:
        def __init__(self, target=None, name=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    monkeypatch.setattr("jobs.entrypoints.run_import_postprocess_job", _flaky_postprocess)
    monkeypatch.setattr("jobs.entrypoints.threading.Thread", _InlineThread)
    monkeypatch.setattr("jobs.entrypoints._persist_postprocess_state", _capture_state)

    out = run_import_postprocess_job_deferred(
        uph_rows=[{"emp_id": "E1", "work_date": "2026-04-01"}],
        tenant_id="tenant-a",
        source_import_job_id="job-1",
        source_import_file="batch.csv",
        source_upload_id="upload-1",
        data_quality_status="partial",
        exclusion_note="",
        handling_choice="review_details",
        handling_note="note",
        from_date="",
        to_date="",
    )

    assert out["deferred"] is True
    assert out["queued"] is True
    assert calls["postprocess"] == 2
    assert "queued" in calls["states"]
    assert "retrying" in calls["states"]
    assert "completed_after_retry" in calls["states"]


def test_import_postprocess_job_deferred_start_failure_persists_sync_fallback_states(monkeypatch):
    calls = {"postprocess": 0, "states": []}

    def _ok_postprocess(**kwargs):
        calls["postprocess"] += 1
        return {"ingested_count": 2, "snapshot_result": {}}

    def _capture_state(**kwargs):
        calls["states"].append(str(kwargs.get("state") or ""))
        return True

    class _BrokenThread:
        def __init__(self, target=None, name=None, daemon=None):
            self._target = target

        def start(self):
            raise RuntimeError("thread-start-failed")

    monkeypatch.setattr("jobs.entrypoints.run_import_postprocess_job", _ok_postprocess)
    monkeypatch.setattr("jobs.entrypoints.threading.Thread", _BrokenThread)
    monkeypatch.setattr("jobs.entrypoints._persist_postprocess_state", _capture_state)

    out = run_import_postprocess_job_deferred(
        uph_rows=[{"emp_id": "E1", "work_date": "2026-04-01"}],
        tenant_id="tenant-a",
        source_import_job_id="job-1",
        source_import_file="batch.csv",
        source_upload_id="upload-1",
        data_quality_status="partial",
        exclusion_note="",
        handling_choice="review_details",
        handling_note="note",
        from_date="",
        to_date="",
    )

    assert out["deferred"] is False
    assert out["fallback_sync"] is True
    assert calls["postprocess"] == 1
    assert "deferred_start_failed" in calls["states"]
    assert "running_sync_fallback" in calls["states"]
    assert "completed_sync_fallback" in calls["states"]


def test_import_postprocess_job_deferred_uses_persisted_state_for_cross_process_dedupe(monkeypatch):
    calls = {"postprocess": 0}

    def _ok_postprocess(**kwargs):
        calls["postprocess"] += 1
        return {"ingested_count": 2, "snapshot_result": {}}

    monkeypatch.setattr("jobs.entrypoints.run_import_postprocess_job", _ok_postprocess)
    monkeypatch.setattr(
        "jobs.entrypoints._read_persisted_postprocess_state",
        lambda **kwargs: {
            "state": "running",
            "dedupe_key": "tenant-a|job-1|upload-1|1|||1",
        },
    )

    out = run_import_postprocess_job_deferred(
        uph_rows=[{"emp_id": "E1", "work_date": "2026-04-01"}],
        tenant_id="tenant-a",
        source_import_job_id="job-1",
        source_import_file="batch.csv",
        source_upload_id="upload-1",
        data_quality_status="partial",
        exclusion_note="",
        handling_choice="review_details",
        handling_note="note",
        from_date="",
        to_date="",
    )

    assert out["deferred"] is True
    assert out["queued"] is False
    assert out["reason"] == "already_recorded"
    assert calls["postprocess"] == 0


def test_import_postprocess_job_deferred_start_fallback_failure_persists_failed_state(monkeypatch):
    calls = {"states": []}

    def _boom_postprocess(**kwargs):
        raise RuntimeError("fallback-failed")

    def _capture_state(**kwargs):
        calls["states"].append(str(kwargs.get("state") or ""))
        return True

    class _BrokenThread:
        def __init__(self, target=None, name=None, daemon=None):
            self._target = target

        def start(self):
            raise RuntimeError("thread-start-failed")

    monkeypatch.setattr("jobs.entrypoints.run_import_postprocess_job", _boom_postprocess)
    monkeypatch.setattr("jobs.entrypoints.threading.Thread", _BrokenThread)
    monkeypatch.setattr("jobs.entrypoints._persist_postprocess_state", _capture_state)

    out = run_import_postprocess_job_deferred(
        uph_rows=[{"emp_id": "E1", "work_date": "2026-04-01"}],
        tenant_id="tenant-a",
        source_import_job_id="job-1",
        source_import_file="batch.csv",
        source_upload_id="upload-1",
        data_quality_status="partial",
        exclusion_note="",
        handling_choice="review_details",
        handling_note="note",
        from_date="",
        to_date="",
    )

    assert out["deferred"] is False
    assert out["fallback_sync"] is True
    assert out["failed"] is True
    assert "failed" in calls["states"]
