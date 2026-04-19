"""Repository access for normalized activity_records."""

from __future__ import annotations

import time

from repositories._common import get_client, log_error, require_tenant, tenant_query
from services.observability import log_operational_event


_ACTIVITY_RECORDS_UPSERT_CHUNK_SIZE = 2000


def batch_upsert_activity_records(records: list[dict], *, tenant_id: str = "") -> None:
    if not records:
        return

    tid = require_tenant(tenant_id)
    sb = get_client()
    payload = [{**row, "tenant_id": tid} for row in records]
    started_at = time.perf_counter()
    chunk_count = 0

    for index in range(0, len(payload), _ACTIVITY_RECORDS_UPSERT_CHUNK_SIZE):
        chunk = payload[index : index + _ACTIVITY_RECORDS_UPSERT_CHUNK_SIZE]
        chunk_count += 1
        try:
            sb.table("activity_records").upsert(
                chunk,
                on_conflict="tenant_id,employee_id,activity_date,process_name",
            ).execute()
        except Exception as error:
            log_error(
                "activity_records",
                f"Activity records upsert failed: {error}",
                detail=f"chunk_size={len(chunk)}, sample={chunk[0] if chunk else 'empty'}",
                severity="error",
            )
            raise

    try:
        log_operational_event(
            "activity_records_batch_upsert_completed",
            status="completed",
            tenant_id=tid,
            context={
                "row_count": len(payload),
                "chunk_count": chunk_count,
                "chunk_size": _ACTIVITY_RECORDS_UPSERT_CHUNK_SIZE,
                "duration_ms": int((time.perf_counter() - started_at) * 1000),
            },
        )
    except Exception:
        pass


def list_activity_records(*, tenant_id: str = "", employee_id: str = "", days: int = 30, limit: int = 500) -> list[dict]:
    sb = get_client()
    columns = (
        "id, tenant_id, employee_id, activity_date, process_name, "
        "units, hours, productivity_value, data_quality_status, "
        "source_import_job_id, source_import_file, source_upload_id, source_record_hash, "
        "exclusion_note, handling_choice, handling_note, raw_context, created_at, updated_at"
    )
    if tenant_id:
        query = sb.table("activity_records").select(columns).eq("tenant_id", tenant_id)
    else:
        query = tenant_query(sb.table("activity_records").select(columns))

    if employee_id:
        query = query.eq("employee_id", str(employee_id or ""))

    if days > 0:
        from datetime import datetime, timedelta

        cutoff = (datetime.utcnow().date() - timedelta(days=days)).isoformat()
        query = query.gte("activity_date", cutoff)

    result = query.order("activity_date", desc=True).limit(max(1, int(limit or 500))).execute()
    return result.data or []
