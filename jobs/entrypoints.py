"""Job entrypoints for heavy operational processing.

These wrappers centralize job naming, payload shaping, and runner invocation.
Execution is synchronous today.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from jobs.runner import execute_job
from jobs.types import JobRequest
from services.activity_records_service import ingest_activity_records_from_import
from services.daily_snapshot_service import recompute_daily_employee_snapshots
from services.import_pipeline.models import ImportPreviewResult
from services.import_pipeline.orchestrator import preview_import
from services.observability import log_operational_event


def run_import_preview_job(
    *,
    sessions: list[dict],
    fallback_date: date,
    tenant_id: str,
    user_role: str,
    run_mode: str = "sync",
) -> ImportPreviewResult:
    log_operational_event(
        "import_started",
        status="started",
        tenant_id=tenant_id,
        context={"phase": "preview", "session_count": len(sessions or [])},
    )
    request = JobRequest(
        name="import.preview",
        run_mode=run_mode,
        payload={"tenant_id": tenant_id, "session_count": len(sessions or [])},
    )
    try:
        result = execute_job(
            request,
            lambda: preview_import(
                sessions,
                fallback_date=fallback_date,
                tenant_id=tenant_id,
                user_role=user_role,
            ),
        )
        log_operational_event(
            "import_completed",
            status="completed",
            tenant_id=tenant_id,
            context={
                "phase": "preview",
                "can_import": bool(getattr(result, "can_import", False)),
                "valid_rows": int(getattr(getattr(result, "summary", None), "valid_rows", 0) or 0),
                "invalid_rows": int(getattr(getattr(result, "summary", None), "invalid_rows", 0) or 0),
            },
        )
        return result
    except Exception as error:
        log_operational_event(
            "import_failed",
            status="failed",
            tenant_id=tenant_id,
            detail="Import preview failed.",
            context={"phase": "preview", "error": str(error)},
        )
        raise


def run_activity_ingest_job(
    *,
    uph_rows: list[dict],
    source_import_job_id: str,
    source_import_file: str,
    source_upload_id: str,
    data_quality_status: str,
    exclusion_note: str,
    handling_choice: str,
    handling_note: str,
    run_mode: str = "sync",
) -> int:
    request = JobRequest(
        name="import.activity_records_ingest",
        run_mode=run_mode,
        payload={
            "row_count": len(uph_rows or []),
            "source_import_job_id": source_import_job_id,
        },
    )
    return execute_job(
        request,
        lambda: ingest_activity_records_from_import(
            uph_rows=uph_rows,
            source_import_job_id=source_import_job_id,
            source_import_file=source_import_file,
            source_upload_id=source_upload_id,
            data_quality_status=data_quality_status,
            exclusion_note=exclusion_note,
            handling_choice=handling_choice,
            handling_note=handling_note,
        ),
    )


def run_snapshot_recompute_job(
    *,
    tenant_id: str,
    from_date: str,
    to_date: str,
    run_mode: str = "sync",
) -> dict[str, Any]:
    request = JobRequest(
        name="snapshots.recompute",
        run_mode=run_mode,
        payload={"tenant_id": tenant_id, "from_date": from_date, "to_date": to_date},
    )
    return execute_job(
        request,
        lambda: recompute_daily_employee_snapshots(
            tenant_id=tenant_id,
            from_date=from_date,
            to_date=to_date,
        ),
    )


def run_import_postprocess_job(
    *,
    uph_rows: list[dict],
    tenant_id: str,
    source_import_job_id: str,
    source_import_file: str,
    source_upload_id: str,
    data_quality_status: str,
    exclusion_note: str,
    handling_choice: str,
    handling_note: str,
    from_date: str = "",
    to_date: str = "",
    run_mode: str = "sync",
) -> dict[str, Any]:
    log_operational_event(
        "import_issue_handling_choice",
        status="recorded",
        tenant_id=tenant_id,
        context={
            "handling_choice": str(handling_choice or ""),
            "handling_note": str(handling_note or ""),
        },
    )
    log_operational_event(
        "import_excluded_data_decision",
        status="recorded",
        tenant_id=tenant_id,
        context={"exclusion_note": str(exclusion_note or "")},
    )

    ingested_count = run_activity_ingest_job(
        uph_rows=uph_rows,
        source_import_job_id=source_import_job_id,
        source_import_file=source_import_file,
        source_upload_id=source_upload_id,
        data_quality_status=data_quality_status,
        exclusion_note=exclusion_note,
        handling_choice=handling_choice,
        handling_note=handling_note,
        run_mode=run_mode,
    )

    snapshot_result: dict[str, Any] = {}
    if str(from_date or "").strip() and str(to_date or "").strip():
        snapshot_result = run_snapshot_recompute_job(
            tenant_id=tenant_id,
            from_date=from_date,
            to_date=to_date,
            run_mode=run_mode,
        )

    return {
        "ingested_count": int(ingested_count or 0),
        "snapshot_result": snapshot_result,
    }
