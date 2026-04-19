"""Repository access for daily employee snapshots."""

from __future__ import annotations

from repositories._common import get_client, log_error, require_tenant, tenant_query


def batch_upsert_daily_employee_snapshots(rows: list[dict]) -> None:
    if not rows:
        return

    tid = require_tenant()
    payload = rows
    if not payload[0].get("tenant_id"):
        payload = [{**row, "tenant_id": tid} for row in payload]

    sb = get_client()
    for index in range(0, len(payload), 500):
        chunk = payload[index : index + 500]
        try:
            sb.table("daily_employee_snapshots").upsert(
                chunk,
                on_conflict="tenant_id,snapshot_date,employee_id,process_name",
            ).execute()
        except Exception as error:
            log_error(
                "daily_employee_snapshots",
                f"Daily snapshot upsert failed: {error}",
                detail=f"chunk_size={len(chunk)}, sample={chunk[0] if chunk else 'empty'}",
                severity="error",
            )
            raise


def delete_daily_employee_snapshots(*, tenant_id: str = "", from_date: str = "", to_date: str = "", employee_id: str = "") -> None:
    if not from_date and not to_date and not employee_id:
        raise ValueError(
            "delete_daily_employee_snapshots requires at least one of: from_date, to_date, or employee_id. "
            "An unbounded delete would remove all snapshots for the tenant."
        )
    sb = get_client()
    if tenant_id:
        query = sb.table("daily_employee_snapshots").delete().eq("tenant_id", tenant_id)
    else:
        query = tenant_query(sb.table("daily_employee_snapshots").delete())

    if from_date:
        query = query.gte("snapshot_date", str(from_date)[:10])
    if to_date:
        query = query.lte("snapshot_date", str(to_date)[:10])
    if employee_id:
        query = query.eq("employee_id", str(employee_id or ""))
    query.execute()


def list_daily_employee_snapshots(
    *,
    tenant_id: str = "",
    employee_id: str = "",
    snapshot_date: str = "",
    from_date: str = "",
    to_date: str = "",
    days: int = 0,
    limit: int = 1000,
) -> list[dict]:
    sb = get_client()
    columns = (
        "id, tenant_id, snapshot_date, employee_id, process_name, performance_uph, expected_uph, variance_uph, "
        "recent_average_uph, prior_average_uph, trend_state, goal_status, confidence_label, confidence_score, "
        "data_completeness_status, data_completeness_note, coverage_ratio, included_day_count, excluded_day_count, "
        "repeat_count, pattern_marker, recent_trend_history, recent_goal_status_history, workload_units, workload_hours, raw_metrics, created_at, updated_at"
    )
    if tenant_id:
        query = sb.table("daily_employee_snapshots").select(columns).eq("tenant_id", tenant_id)
    else:
        query = tenant_query(sb.table("daily_employee_snapshots").select(columns))

    if employee_id:
        query = query.eq("employee_id", str(employee_id or ""))
    if snapshot_date:
        query = query.eq("snapshot_date", str(snapshot_date)[:10])
    if from_date:
        query = query.gte("snapshot_date", str(from_date)[:10])
    if to_date:
        query = query.lte("snapshot_date", str(to_date)[:10])
    if days > 0 and not from_date and not snapshot_date:
        from datetime import date, timedelta

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        query = query.gte("snapshot_date", cutoff)

    result = query.order("snapshot_date", desc=True).limit(max(1, int(limit or 1000))).execute()
    return result.data or []