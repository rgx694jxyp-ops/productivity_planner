"""Repository access for normalized activity_records."""

from __future__ import annotations

from repositories._common import get_client, get_tenant_id, log_error, tenant_fields, tenant_query


def batch_upsert_activity_records(records: list[dict]) -> None:
    if not records:
        return

    tenant_id = get_tenant_id()
    sb = get_client()
    payload = records
    if not payload[0].get("tenant_id"):
        fields = tenant_fields()
        if fields:
            payload = [{**row, **fields} for row in payload]

    for index in range(0, len(payload), 500):
        chunk = payload[index : index + 500]
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
        from datetime import date, timedelta

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        query = query.gte("activity_date", cutoff)

    result = query.order("activity_date", desc=True).limit(max(1, int(limit or 500))).execute()
    return result.data or []
