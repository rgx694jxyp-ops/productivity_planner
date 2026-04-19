"""Service layer for normalized activity_records ingestion and compatibility reads.

TODO: Move legacy UPH fallback off this service once all analytics flows read
directly from activity_records.
"""

from __future__ import annotations

import hashlib
from typing import Any

from domain.activity_records import normalize_data_quality_status, normalize_handling_choice
from repositories import activity_records_repo, import_repo


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _record_hash(*, employee_id: str, activity_date: str, process_name: str, units: float, hours: float, productivity_value: float) -> str:
    material = "|".join(
        [
            str(employee_id or "").strip(),
            str(activity_date or "").strip(),
            str(process_name or "").strip(),
            f"{float(units):.4f}",
            f"{float(hours):.4f}",
            f"{float(productivity_value):.4f}",
        ]
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def build_activity_records_from_import_rows(
    *,
    uph_rows: list[dict],
    source_import_job_id: str = "",
    source_import_file: str = "",
    source_upload_id: str = "",
    data_quality_status: str = "partial",
    exclusion_note: str = "",
    handling_choice: str = "",
    handling_note: str = "",
) -> list[dict]:
    status = normalize_data_quality_status(data_quality_status)
    choice = normalize_handling_choice(handling_choice)

    records: list[dict] = []
    for row in uph_rows or []:
        employee_id = str(row.get("emp_id") or row.get("employee_id") or "").strip()
        activity_date = str(row.get("work_date") or row.get("activity_date") or "").strip()[:10]
        process_name = str(row.get("department") or row.get("process") or row.get("process_name") or "").strip()
        units = _safe_float(row.get("units"))
        hours = _safe_float(row.get("hours_worked") if row.get("hours_worked") is not None else row.get("hours"))
        productivity_value = _safe_float(row.get("uph") if row.get("uph") is not None else row.get("productivity_value"))
        if not (employee_id and activity_date):
            continue

        records.append(
            {
                "employee_id": employee_id,
                "activity_date": activity_date,
                "process_name": process_name,
                "units": units,
                "hours": hours,
                "productivity_value": productivity_value,
                "source_import_job_id": str(source_import_job_id or "").strip(),
                "source_import_file": str(source_import_file or "").strip(),
                "source_upload_id": str(source_upload_id or "").strip(),
                "source_record_hash": _record_hash(
                    employee_id=employee_id,
                    activity_date=activity_date,
                    process_name=process_name,
                    units=units,
                    hours=hours,
                    productivity_value=productivity_value,
                ),
                "data_quality_status": status,
                "exclusion_note": str(exclusion_note or "").strip(),
                "handling_choice": choice,
                "handling_note": str(handling_note or "").strip(),
                "raw_context": {
                    "legacy_source": "uph_history_import",
                    "employee_name": str(row.get("employee_name") or "").strip(),
                    "work_date": activity_date,
                },
            }
        )

    return records


def ingest_activity_records_from_import(
    *,
    uph_rows: list[dict],
    source_import_job_id: str = "",
    source_import_file: str = "",
    source_upload_id: str = "",
    data_quality_status: str = "partial",
    exclusion_note: str = "",
    handling_choice: str = "",
    handling_note: str = "",
) -> int:
    records = build_activity_records_from_import_rows(
        uph_rows=uph_rows,
        source_import_job_id=source_import_job_id,
        source_import_file=source_import_file,
        source_upload_id=source_upload_id,
        data_quality_status=data_quality_status,
        exclusion_note=exclusion_note,
        handling_choice=handling_choice,
        handling_note=handling_note,
    )
    if not records:
        return 0
    activity_records_repo.batch_upsert_activity_records(records)
    return len(records)


def get_recent_activity_records(*, tenant_id: str = "", employee_id: str = "", days: int = 30, limit: int = 500) -> list[dict]:
    rows = activity_records_repo.list_activity_records(
        tenant_id=tenant_id,
        employee_id=employee_id,
        days=days,
        limit=limit,
    )
    if rows:
        try:
            from core.dependencies import _log_operational_event
            _log_operational_event(
                "activity_records_query",
                status="success",
                tenant_id=tenant_id,
                detail="Activity records found",
                context={"row_count": len(rows), "source": "activity_records_table"},
            )
        except Exception:
            pass
        return rows

    # Legacy compatibility fallback while older rows remain only in uph_history.
    try:
        from core.dependencies import _log_operational_event
        _log_operational_event(
            "activity_records_fallback",
            status="started",
            tenant_id=tenant_id,
            detail="Activity records table empty, falling back to uph_history",
            context={"tenant_id": tenant_id},
        )
    except Exception:
        pass
    
    fetch_limit = 0 if employee_id else max(1, int(limit or 500))
    legacy_rows = import_repo.get_all_uph_history(days=days, limit=fetch_limit)
    
    try:
        from core.dependencies import _log_operational_event
        _log_operational_event(
            "activity_records_fallback",
            status="completed",
            tenant_id=tenant_id,
            detail="Legacy uph_history query completed",
            context={"row_count": len(legacy_rows), "source": "uph_history_fallback"},
        )
    except Exception:
        pass
    
    out: list[dict] = []
    for row in legacy_rows:
        legacy_emp_id = str(row.get("emp_id") or "").strip()
        if employee_id and legacy_emp_id != str(employee_id or "").strip():
            continue
        out.append(
            {
                "employee_id": legacy_emp_id,
                "activity_date": str(row.get("work_date") or "")[:10],
                "process_name": str(row.get("department") or "").strip(),
                "units": _safe_float(row.get("units")),
                "hours": _safe_float(row.get("hours_worked")),
                "productivity_value": _safe_float(row.get("uph")),
                "data_quality_status": "partial",
                "source_import_job_id": "",
                "source_import_file": "",
                "source_upload_id": "",
                "source_record_hash": "",
                "exclusion_note": "",
                "handling_choice": "",
                "handling_note": "",
                "raw_context": {"legacy_source": "uph_history"},
            }
        )
    return out[: max(1, int(limit or 500))]
