"""Data access for import/UPH persistence."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Callable

from repositories._common import get_client, get_tenant_id, log_error, require_tenant, tenant_query
from repositories.employees_repo import get_employees
from services.app_logging import log_error as log_app_error
from services.app_logging import log_info, log_warn


def get_all_uph_history(days: int = 30, *, limit: int = 0, tenant_id: str = "") -> list[dict]:
    """All UPH history records with pagination past Supabase default row caps."""
    sb = get_client()
    all_rows = []
    page_size = 1000
    offset = 0
    max_rows = max(0, int(limit or 0))
    tid = str(tenant_id or "").strip()

    while True:
        if tid:
            query = sb.table("uph_history").select(
                "emp_id, work_date, uph, units, hours_worked, department"
            ).eq("tenant_id", tid)
        else:
            query = tenant_query(
                sb.table("uph_history").select("emp_id, work_date, uph, units, hours_worked, department")
            )
        query = query.order("work_date", desc=False).range(offset, offset + page_size - 1)

        if days > 0:
            cutoff = (date.today() - timedelta(days=days)).isoformat()
            query = query.gte("work_date", cutoff)

        result = query.execute()
        batch = result.data or []
        all_rows.extend(batch)
        if max_rows > 0 and len(all_rows) >= max_rows:
            return all_rows[:max_rows]
        if len(batch) < page_size:
            break
        offset += page_size

    return all_rows


def batch_store_uph_history(
    records: list[dict],
    *,
    progress_callback: Callable[..., None] | None = None,
):
    """Insert UPH history records in chunks after resolving employee FK values."""
    if not records:
        return

    tenant_id = get_tenant_id()

    def _to_int_or_none(value) -> int | None:
        try:
            return int(str(value).strip())
        except Exception:
            return None

    all_emp_ids_numeric = all(_to_int_or_none(row.get("emp_id")) is not None for row in records)

    emp_code_to_id: dict[str, int] = {}
    emp_id_to_id: dict[str, int] = {}
    resolver_available = all_emp_ids_numeric
    if not all_emp_ids_numeric:
        resolver_available = True
        try:
            employee_rows = get_employees() or []
        except Exception as error:
            employee_rows = []
            resolver_available = False
            log_warn(
                "repo_uph_employee_resolution_unavailable",
                "Employee resolution lookup failed before UPH batch store.",
                tenant_id=tenant_id,
                context={"record_count": len(records)},
                error=error,
            )

        for employee in employee_rows:
            row_id = employee.get("id")
            code = employee.get("emp_id")
            if row_id is None:
                continue
            try:
                row_id_int = int(row_id)
            except Exception:
                continue
            emp_id_to_id[str(row_id_int)] = row_id_int
            if code not in (None, ""):
                emp_code_to_id[str(code).strip()] = row_id_int

    normalized_records = []
    skipped_unresolved = 0
    unresolved_examples = []
    for row in records:
        raw_emp = row.get("emp_id")
        emp_fk = _to_int_or_none(raw_emp)
        if emp_fk is None and raw_emp not in (None, ""):
            raw_emp_str = str(raw_emp).strip()
            emp_fk = emp_code_to_id.get(raw_emp_str) or emp_id_to_id.get(raw_emp_str)

        if emp_fk is None:
            if resolver_available:
                skipped_unresolved += 1
                if len(unresolved_examples) < 10:
                    unresolved_examples.append(
                        {
                            "emp_id": str(raw_emp or "").strip(),
                            "work_date": str(row.get("work_date", "") or ""),
                            "department": str(row.get("department", "") or ""),
                        }
                    )
                continue
            normalized_records.append(row)
            continue

        normalized_records.append({**row, "emp_id": emp_fk})

    if skipped_unresolved:
        examples_str = ", ".join(
            [
                f"{item['emp_id']}@{item['work_date']}"
                for item in unresolved_examples
                if item.get("emp_id") or item.get("work_date")
            ]
        )
        log_error(
            "uph_history",
            f"Blocked import: {skipped_unresolved} UPH row(s) have unresolved employee IDs",
            detail=f"examples={unresolved_examples}",
            severity="error",
        )
        log_app_error(
            "repo_uph_unresolved_employee_ids",
            "Repository UPH batch store blocked because employee IDs could not be resolved.",
            tenant_id=tenant_id,
            context={"skipped_unresolved": skipped_unresolved, "examples": unresolved_examples},
        )
        raise ValueError(
            "UPH history write blocked: "
            f"{skipped_unresolved} row(s) have unresolved employee IDs. "
            f"Example(s): {examples_str or 'see error log for details'}."
        )

    records = normalized_records
    if not records:
        return

    tid = require_tenant()
    sb = get_client()
    if not records[0].get("tenant_id"):
        records = [{**record, "tenant_id": tid} for record in records]

    chunk_size = 2000
    total_records = len(records)
    chunk_count = max(1, (total_records + chunk_size - 1) // chunk_size)
    for index in range(0, len(records), chunk_size):
        chunk = records[index : index + chunk_size]
        safe_chunk = []
        for row in chunk:
            try:
                uph_val = float(row.get("uph", 0) or 0)
            except (TypeError, ValueError):
                uph_val = 0.0
            if not math.isfinite(uph_val):
                uph_val = 0.0

            try:
                units_val = float(row.get("units", 0) or 0)
            except (TypeError, ValueError):
                units_val = 0.0
            if not math.isfinite(units_val):
                units_val = 0.0

            try:
                hours_val = float(row.get("hours_worked", 0) or 0)
            except (TypeError, ValueError):
                hours_val = 0.0
            if not math.isfinite(hours_val):
                hours_val = 0.0

            safe_chunk.append({
                **row,
                "uph": uph_val,
                "units": units_val,
                "hours_worked": hours_val,
            })

        try:
            sb.table("uph_history").upsert(
                safe_chunk,
                on_conflict="tenant_id,emp_id,work_date,department",
            ).execute()
            if progress_callback:
                try:
                    progress_callback(
                        completed_rows=min(index + len(chunk), total_records),
                        total_rows=total_records,
                        chunk_index=(index // chunk_size) + 1,
                        chunk_count=chunk_count,
                    )
                except Exception:
                    pass
        except Exception as error:
            log_error(
                "uph_history",
                f"UPH batch upsert failed: {error}",
                detail=f"chunk_size={len(safe_chunk)}, sample={safe_chunk[0] if safe_chunk else 'empty'}",
                severity="error",
            )
            log_app_error(
                "repo_uph_batch_upsert_failed",
                "Repository UPH batch upsert failed.",
                tenant_id=tenant_id,
                context={"chunk_index": index // chunk_size, "chunk_size": len(safe_chunk)},
                error=error,
            )
            raise
