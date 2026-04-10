"""Lightweight import job lifecycle helpers.

Keeps pipeline stage tracking explicit without changing UI workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


STAGES = ("upload", "map", "validate", "persist", "summarize")


@dataclass
class ImportJob:
    job_id: str
    tenant_id: str
    upload_name: str
    total_rows: int = 0
    current_stage: str = "upload"
    stage_status: dict[str, str] = field(default_factory=dict)
    stage_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    started_at: str = ""
    completed_at: str = ""
    success: bool = False


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_import_job(*, tenant_id: str, upload_name: str, total_rows: int) -> ImportJob:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    job = ImportJob(
        job_id=f"import-{ts}",
        tenant_id=str(tenant_id or ""),
        upload_name=str(upload_name or "Import"),
        total_rows=max(0, int(total_rows or 0)),
        current_stage="upload",
        stage_status={stage: "pending" for stage in STAGES},
        started_at=_utc_iso(),
    )
    job.stage_status["upload"] = "completed"
    job.stage_meta["upload"] = {"total_rows": job.total_rows}
    return job


def mark_stage_in_progress(job: ImportJob, stage: str, *, meta: dict[str, Any] | None = None) -> None:
    if stage not in STAGES:
        return
    job.current_stage = stage
    job.stage_status[stage] = "in_progress"
    if meta:
        job.stage_meta[stage] = {**job.stage_meta.get(stage, {}), **meta}


def mark_stage_completed(job: ImportJob, stage: str, *, meta: dict[str, Any] | None = None) -> None:
    if stage not in STAGES:
        return
    job.current_stage = stage
    job.stage_status[stage] = "completed"
    if meta:
        job.stage_meta[stage] = {**job.stage_meta.get(stage, {}), **meta}


def mark_stage_failed(job: ImportJob, stage: str, *, error: str) -> None:
    if stage not in STAGES:
        return
    job.current_stage = stage
    job.stage_status[stage] = "failed"
    job.stage_meta[stage] = {**job.stage_meta.get(stage, {}), "error": str(error or "")}


def complete_job(job: ImportJob, *, success: bool) -> None:
    job.success = bool(success)
    job.completed_at = _utc_iso()
    if success:
        for stage in STAGES:
            if job.stage_status.get(stage) == "pending":
                job.stage_status[stage] = "completed"


def serialize_job(job: ImportJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "tenant_id": job.tenant_id,
        "upload_name": job.upload_name,
        "total_rows": job.total_rows,
        "current_stage": job.current_stage,
        "stage_status": dict(job.stage_status),
        "stage_meta": dict(job.stage_meta),
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "success": job.success,
    }
