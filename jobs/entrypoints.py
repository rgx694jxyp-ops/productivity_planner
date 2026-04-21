"""Job entrypoints for heavy operational processing.

These wrappers centralize job naming, payload shaping, and runner invocation.
Execution is synchronous today.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from datetime import date
from typing import Any

from jobs.runner import execute_job
from jobs.types import JobRequest
from repositories._common import get_client
from services.activity_records_service import ingest_activity_records_from_import
from services.daily_snapshot_service import recompute_daily_employee_snapshots
from services.import_pipeline.models import ImportPreviewResult
from services.import_pipeline.orchestrator import preview_import
from services.observability import log_operational_event
from services.perf_profile import profile_block


_POSTPROCESS_DEFER_LOCK = threading.Lock()
_POSTPROCESS_IN_FLIGHT: set[str] = set()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _persist_postprocess_state(
    *,
    tenant_id: str,
    source_upload_id: str,
    state: str,
    source_import_job_id: str,
    row_count: int,
    dedupe_key: str = "",
    error: str = "",
) -> bool:
    tid = str(tenant_id or "").strip()
    upload_id = str(source_upload_id or "").strip()
    if not tid or not upload_id:
        return False

    try:
        sb = get_client()
        for _ in range(3):
            read_result = (
                sb.table("uploaded_files")
                .select("header_mapping")
                .eq("id", upload_id)
                .eq("tenant_id", tid)
                .limit(1)
                .execute()
            )
            rows = read_result.data or []
            if not rows:
                return False
            original_payload = dict(rows[0].get("header_mapping") or {})
            next_payload = dict(original_payload)
            postprocess_meta = dict(next_payload.get("postprocess") or {})
            attempt_count = int(postprocess_meta.get("attempt_count") or 0)
            if state in {"running", "retrying", "running_sync_fallback"}:
                attempt_count += 1

            postprocess_meta.update(
                {
                    "state": str(state or "unknown"),
                    "source_import_job_id": str(source_import_job_id or ""),
                    "row_count": int(row_count or 0),
                    "updated_at": _utc_iso(),
                    "attempt_count": attempt_count,
                }
            )
            if dedupe_key:
                postprocess_meta["dedupe_key"] = str(dedupe_key)
            if error:
                postprocess_meta["error"] = str(error)
            elif "error" in postprocess_meta:
                postprocess_meta.pop("error", None)

            next_payload["postprocess"] = postprocess_meta
            write_result = (
                sb.table("uploaded_files")
                .update({"header_mapping": next_payload})
                .eq("id", upload_id)
                .eq("tenant_id", tid)
                .eq("header_mapping", original_payload)
                .execute()
            )
            write_rows = list(write_result.data or []) if hasattr(write_result, "data") else []
            if write_rows:
                return True
        return False
    except Exception:
        return False


def _read_persisted_postprocess_state(*, tenant_id: str, source_upload_id: str) -> dict[str, Any]:
    tid = str(tenant_id or "").strip()
    upload_id = str(source_upload_id or "").strip()
    if not tid or not upload_id:
        return {}

    try:
        sb = get_client()
        result = (
            sb.table("uploaded_files")
            .select("header_mapping")
            .eq("id", upload_id)
            .eq("tenant_id", tid)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return {}
        payload = dict(rows[0].get("header_mapping") or {})
        state_payload = dict(payload.get("postprocess") or {})
        if not state_payload:
            return {}
        return state_payload
    except Exception:
        return {}


def _postprocess_dedupe_key(
    *,
    tenant_id: str,
    source_import_job_id: str,
    source_upload_id: str,
    row_count: int,
    from_date: str,
    to_date: str,
    ingest_activity: bool,
) -> str:
    return "|".join(
        [
            str(tenant_id or "").strip(),
            str(source_import_job_id or "").strip(),
            str(source_upload_id or "").strip(),
            str(int(row_count or 0)),
            str(from_date or "").strip(),
            str(to_date or "").strip(),
            "1" if ingest_activity else "0",
        ]
    )


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
    tenant_id: str,
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
            tenant_id=tenant_id,
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
    replace_existing: bool = True,
    source_limit: int = 5000,
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
            replace_existing=bool(replace_existing),
            source_limit=int(source_limit or 5000),
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
    replace_existing_snapshots: bool = True,
    ingest_activity: bool = True,
    snapshot_source_limit: int = 5000,
    run_mode: str = "sync",
) -> dict[str, Any]:
    with profile_block(
        "import.postprocess",
        tenant_id=str(tenant_id or ""),
        context={
            "uph_rows": len(uph_rows or []),
            "ingest_activity": bool(ingest_activity),
            "has_snapshot_window": bool(str(from_date or "").strip() and str(to_date or "").strip()),
        },
        execution_key=f"_perf_profile_import_postprocess_{str(tenant_id or '').strip()}",
    ) as profile:
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

        ingested_count = 0
        if ingest_activity:
            with profile.stage("activity_ingest"):
                ingested_count = run_activity_ingest_job(
                    uph_rows=uph_rows,
                    tenant_id=tenant_id,
                    source_import_job_id=source_import_job_id,
                    source_import_file=source_import_file,
                    source_upload_id=source_upload_id,
                    data_quality_status=data_quality_status,
                    exclusion_note=exclusion_note,
                    handling_choice=handling_choice,
                    handling_note=handling_note,
                    run_mode=run_mode,
                )
            profile.set("ingested_count", int(ingested_count or 0))

        snapshot_result: dict[str, Any] = {}
        if str(from_date or "").strip() and str(to_date or "").strip():
            with profile.stage("snapshot_recompute"):
                snapshot_result = run_snapshot_recompute_job(
                    tenant_id=tenant_id,
                    from_date=from_date,
                    to_date=to_date,
                    replace_existing=bool(replace_existing_snapshots),
                    source_limit=int(snapshot_source_limit or 5000),
                    run_mode=run_mode,
                )
            profile.set("snapshot_rows_inserted", int(snapshot_result.get("inserted") or 0))
            profile.set("snapshot_source_rows", int(snapshot_result.get("source_rows") or 0))

        return {
            "ingested_count": int(ingested_count or 0),
            "snapshot_result": snapshot_result,
        }


def run_import_postprocess_job_deferred(
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
    replace_existing_snapshots: bool = True,
    ingest_activity: bool = True,
    snapshot_source_limit: int = 5000,
) -> dict[str, Any]:
    payload_rows = [dict(row or {}) for row in (uph_rows or [])]
    dedupe_key = _postprocess_dedupe_key(
        tenant_id=tenant_id,
        source_import_job_id=source_import_job_id,
        source_upload_id=source_upload_id,
        row_count=len(payload_rows),
        from_date=from_date,
        to_date=to_date,
        ingest_activity=ingest_activity,
    )

    persisted_state = _read_persisted_postprocess_state(
        tenant_id=tenant_id,
        source_upload_id=source_upload_id,
    )
    persisted_dedupe_key = str(persisted_state.get("dedupe_key") or "").strip()
    persisted_status = str(persisted_state.get("state") or "").strip().lower()
    if persisted_dedupe_key and persisted_dedupe_key == dedupe_key and persisted_status in {
        "queued",
        "running",
        "retrying",
        "running_sync_fallback",
        "completed",
        "completed_after_retry",
        "completed_sync_fallback",
    }:
        log_operational_event(
            "import_postprocess_deferred_duplicate",
            status="ignored",
            tenant_id=tenant_id,
            context={"dedupe_key": dedupe_key[:120], "row_count": len(payload_rows), "source": "persisted_state"},
        )
        return {
            "deferred": True,
            "queued": False,
            "reason": "already_recorded",
            "dedupe_key": dedupe_key,
        }

    with _POSTPROCESS_DEFER_LOCK:
        if dedupe_key in _POSTPROCESS_IN_FLIGHT:
            log_operational_event(
                "import_postprocess_deferred_duplicate",
                status="ignored",
                tenant_id=tenant_id,
                context={"dedupe_key": dedupe_key[:120], "row_count": len(payload_rows)},
            )
            return {"deferred": True, "queued": False, "reason": "already_in_flight", "dedupe_key": dedupe_key}
        _POSTPROCESS_IN_FLIGHT.add(dedupe_key)
    _persist_postprocess_state(
        tenant_id=tenant_id,
        source_upload_id=source_upload_id,
        state="queued",
        source_import_job_id=source_import_job_id,
        row_count=len(payload_rows),
        dedupe_key=dedupe_key,
    )

    def _run() -> None:
        try:
            _persist_postprocess_state(
                tenant_id=tenant_id,
                source_upload_id=source_upload_id,
                state="running",
                source_import_job_id=source_import_job_id,
                row_count=len(payload_rows),
                dedupe_key=dedupe_key,
            )
            log_operational_event(
                "import_postprocess_deferred_started",
                status="started",
                tenant_id=tenant_id,
                context={"row_count": len(payload_rows), "has_snapshot_window": bool(str(from_date or "").strip() and str(to_date or "").strip())},
            )
            run_import_postprocess_job(
                uph_rows=payload_rows,
                tenant_id=tenant_id,
                source_import_job_id=source_import_job_id,
                source_import_file=source_import_file,
                source_upload_id=source_upload_id,
                data_quality_status=data_quality_status,
                exclusion_note=exclusion_note,
                handling_choice=handling_choice,
                handling_note=handling_note,
                from_date=from_date,
                to_date=to_date,
                replace_existing_snapshots=replace_existing_snapshots,
                ingest_activity=ingest_activity,
                snapshot_source_limit=snapshot_source_limit,
                run_mode="sync",
            )
            log_operational_event(
                "import_postprocess_deferred_completed",
                status="completed",
                tenant_id=tenant_id,
                context={"row_count": len(payload_rows)},
            )
            _persist_postprocess_state(
                tenant_id=tenant_id,
                source_upload_id=source_upload_id,
                state="completed",
                source_import_job_id=source_import_job_id,
                row_count=len(payload_rows),
                dedupe_key=dedupe_key,
            )
        except Exception as error:
            log_operational_event(
                "import_postprocess_deferred_failed",
                status="failed",
                tenant_id=tenant_id,
                detail="Deferred import postprocess failed.",
                context={"error": str(error), "row_count": len(payload_rows)},
            )
            _persist_postprocess_state(
                tenant_id=tenant_id,
                source_upload_id=source_upload_id,
                state="retrying",
                source_import_job_id=source_import_job_id,
                row_count=len(payload_rows),
                dedupe_key=dedupe_key,
                error=str(error),
            )
            try:
                run_import_postprocess_job(
                    uph_rows=payload_rows,
                    tenant_id=tenant_id,
                    source_import_job_id=source_import_job_id,
                    source_import_file=source_import_file,
                    source_upload_id=source_upload_id,
                    data_quality_status=data_quality_status,
                    exclusion_note=exclusion_note,
                    handling_choice=handling_choice,
                    handling_note=handling_note,
                    from_date=from_date,
                    to_date=to_date,
                    replace_existing_snapshots=replace_existing_snapshots,
                    ingest_activity=ingest_activity,
                    snapshot_source_limit=snapshot_source_limit,
                    run_mode="sync",
                )
                _persist_postprocess_state(
                    tenant_id=tenant_id,
                    source_upload_id=source_upload_id,
                    state="completed_after_retry",
                    source_import_job_id=source_import_job_id,
                    row_count=len(payload_rows),
                    dedupe_key=dedupe_key,
                )
                log_operational_event(
                    "import_postprocess_deferred_recovered",
                    status="completed",
                    tenant_id=tenant_id,
                    context={"row_count": len(payload_rows), "recovery_mode": "sync_retry"},
                )
            except Exception as retry_error:
                _persist_postprocess_state(
                    tenant_id=tenant_id,
                    source_upload_id=source_upload_id,
                    state="failed",
                    source_import_job_id=source_import_job_id,
                    row_count=len(payload_rows),
                    dedupe_key=dedupe_key,
                    error=str(retry_error),
                )
                log_operational_event(
                    "import_postprocess_deferred_permanent_failure",
                    status="failed",
                    tenant_id=tenant_id,
                    detail="Deferred import postprocess failed and immediate retry also failed.",
                    context={"error": str(retry_error), "row_count": len(payload_rows)},
                )
                log_operational_event(
                    "import_postprocess_needs_manual_recovery",
                    status="failed",
                    tenant_id=tenant_id,
                    detail="Manual recovery required for import postprocess.",
                    context={
                        "error": str(retry_error),
                        "row_count": len(payload_rows),
                        "source_upload_id": str(source_upload_id or ""),
                        "source_import_job_id": str(source_import_job_id or ""),
                        "dedupe_key": dedupe_key[:120],
                    },
                )
        finally:
            with _POSTPROCESS_DEFER_LOCK:
                _POSTPROCESS_IN_FLIGHT.discard(dedupe_key)

    # Execute inline to preserve the authenticated request/session context.
    # Background threads can lose Streamlit auth state and fall back to anon key,
    # which then fails RLS-protected writes in postprocess tables.
    _run()
    return {"deferred": False, "queued": False, "executed_sync": True, "dedupe_key": dedupe_key}
