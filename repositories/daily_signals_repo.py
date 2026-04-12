"""Repository access for precomputed daily signals."""

from __future__ import annotations

from repositories._common import get_client, log_error, tenant_fields, tenant_query


def batch_upsert_daily_signals(rows: list[dict]) -> None:
    if not rows:
        return

    payload = rows
    if not payload[0].get("tenant_id"):
        fields = tenant_fields()
        if fields:
            payload = [{**row, **fields} for row in payload]

    sb = get_client()
    for index in range(0, len(payload), 500):
        chunk = payload[index : index + 500]
        try:
            sb.table("daily_signals").upsert(
                chunk,
                on_conflict="tenant_id,signal_date,signal_key",
            ).execute()
        except Exception as error:
            log_error(
                "daily_signals",
                f"Daily signals upsert failed: {error}",
                detail=f"chunk_size={len(chunk)}, sample={chunk[0] if chunk else 'empty'}",
                severity="error",
            )
            raise


def delete_daily_signals(*, tenant_id: str = "", signal_date: str = "") -> None:
    sb = get_client()
    if tenant_id:
        query = sb.table("daily_signals").delete().eq("tenant_id", tenant_id)
    else:
        query = tenant_query(sb.table("daily_signals").delete())

    if signal_date:
        query = query.eq("signal_date", str(signal_date)[:10])
    query.execute()


def list_daily_signals(
    *,
    tenant_id: str = "",
    signal_date: str = "",
    employee_id: str = "",
    signal_type: str = "",
    limit: int = 5000,
) -> list[dict]:
    sb = get_client()
    columns = (
        "id, tenant_id, signal_date, signal_key, employee_id, signal_type, section, observed_value, baseline_value, "
        "confidence, completeness, pattern_count, flags, payload, created_at, updated_at"
    )
    if tenant_id:
        query = sb.table("daily_signals").select(columns).eq("tenant_id", tenant_id)
    else:
        query = tenant_query(sb.table("daily_signals").select(columns))

    if signal_date:
        query = query.eq("signal_date", str(signal_date)[:10])
    if employee_id:
        query = query.eq("employee_id", str(employee_id or ""))
    if signal_type:
        query = query.eq("signal_type", str(signal_type or ""))

    result = query.order("signal_date", desc=True).limit(max(1, int(limit or 5000))).execute()
    return result.data or []
