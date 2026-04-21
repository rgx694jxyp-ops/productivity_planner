#!/usr/bin/env python3
"""Temporary end-to-end import trace for a single row.

Usage:
  python scripts/trace_import_pipeline_row.py --tenant-id <uuid> [--work-date YYYY-MM-DD] [--emp-id E123]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from typing import Any

import database
from jobs.entrypoints import run_import_postprocess_job
from repositories._common import get_client
from services.daily_signals_service import compute_daily_signals, read_precomputed_today_signals
from services.daily_snapshot_service import get_latest_snapshot_goal_status
from services.import_pipeline.orchestrator import confirm_import, preview_import
from services.observability import log_operational_event


def _emit(stage: str, status: str, context: dict[str, Any], tenant_id: str) -> None:
    payload = {
        "stage": stage,
        "status": status,
        "context": context,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    log_operational_event(
        f"import_trace_{stage}",
        status=status,
        tenant_id=tenant_id,
        context=context,
    )


def _pick_employee(*, tenant_id: str, explicit_emp_id: str = "") -> dict[str, Any] | None:
    sb = get_client()
    q = sb.table("employees").select("id,emp_id,name,department").eq("tenant_id", tenant_id)
    if explicit_emp_id:
        q = q.eq("emp_id", explicit_emp_id)
    rows = q.order("id").limit(1).execute().data or []
    return dict(rows[0]) if rows else None


def _query_uph_row(*, tenant_id: str, employee_row_id: int, work_date: str, department: str) -> dict[str, Any] | None:
    sb = get_client()
    q = (
        sb.table("uph_history")
        .select("id,tenant_id,emp_id,work_date,department,uph,units,hours_worked")
        .eq("tenant_id", tenant_id)
        .eq("emp_id", int(employee_row_id))
        .eq("work_date", work_date)
        .eq("department", department)
        .limit(1)
    )
    rows = q.execute().data or []
    return dict(rows[0]) if rows else None


def _query_snapshot_row(*, tenant_id: str, employee_code: str, work_date: str, department: str) -> dict[str, Any] | None:
    sb = get_client()
    q = (
        sb.table("daily_employee_snapshots")
        .select("tenant_id,snapshot_date,employee_id,process_name,performance_uph,expected_uph,goal_status,trend_state")
        .eq("tenant_id", tenant_id)
        .eq("snapshot_date", work_date)
        .eq("employee_id", employee_code)
        .eq("process_name", department)
        .limit(1)
    )
    rows = q.execute().data or []
    return dict(rows[0]) if rows else None


def _in_today_payload(payload: dict[str, Any] | None, employee_code: str) -> tuple[bool, bool, str]:
    if not isinstance(payload, dict):
        return False, False, "today_payload_missing"

    goal_rows = list(payload.get("goal_status") or [])
    queue_rows = list(payload.get("queue_items") or [])

    in_goal = any(str(r.get("EmployeeID") or "").strip() == employee_code for r in goal_rows)

    in_queue = False
    for row in queue_rows:
        rid = str(row.get("employee_id") or row.get("EmployeeID") or "").strip()
        if rid == employee_code:
            in_queue = True
            break

    reason = "visible_in_queue" if in_queue else ("in_today_goal_status_not_in_queue" if in_goal else "not_in_today_payload_rows")
    return in_goal, in_queue, reason


def _in_team_rows(team_rows: list[dict[str, Any]], employee_code: str) -> bool:
    return any(str(r.get("EmployeeID") or "").strip() == employee_code for r in (team_rows or []))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--work-date", default=date.today().isoformat())
    parser.add_argument("--emp-id", default="")
    args = parser.parse_args()

    tenant_id = str(args.tenant_id or "").strip()
    work_date = str(args.work_date or "").strip()[:10]
    explicit_emp_id = str(args.emp_id or "").strip()

    # Ensure repository helpers resolve tenant context in this non-Streamlit script.
    database.get_tenant_id = lambda: tenant_id  # type: ignore[assignment]

    employee = _pick_employee(tenant_id=tenant_id, explicit_emp_id=explicit_emp_id)
    if not employee and explicit_emp_id and str(explicit_emp_id).strip().isdigit():
        employee = {
            "id": int(str(explicit_emp_id).strip()),
            "emp_id": str(explicit_emp_id).strip(),
            "name": f"Trace Employee {str(explicit_emp_id).strip()}",
            "department": "Trace",
        }
    if not employee:
        _emit("setup", "failed", {"reason": "no_employee_found", "tenant_id": tenant_id, "emp_id": explicit_emp_id}, tenant_id)
        return 2

    employee_code = str(employee.get("emp_id") or "").strip()
    employee_row_id = int(employee.get("id"))
    department = str(employee.get("department") or "Unassigned").strip() or "Unassigned"

    units = 123.0
    hours = 3.0
    uph = round(units / hours, 2)

    _emit(
        "setup",
        "ok",
        {
            "tenant_id": tenant_id,
            "employee_code": employee_code,
            "employee_row_id": employee_row_id,
            "department": department,
            "work_date": work_date,
            "units": units,
            "hours_worked": hours,
            "uph": uph,
        },
        tenant_id,
    )

    sessions = [
        {
            "filename": "trace_one_row.csv",
            "mapping": {
                "Date": "Date",
                "EmployeeID": "EmployeeID",
                "EmployeeName": "EmployeeName",
                "Department": "Department",
                "Units": "Units",
                "HoursWorked": "HoursWorked",
                "UPH": "UPH",
            },
            "rows": [
                {
                    "Date": work_date,
                    "EmployeeID": employee_code,
                    "EmployeeName": str(employee.get("name") or employee_code),
                    "Department": department,
                    "Units": str(units),
                    "HoursWorked": str(hours),
                    "UPH": str(uph),
                }
            ],
        }
    ]

    # A. After parsing / preview
    preview = preview_import(
        sessions,
        fallback_date=date.fromisoformat(work_date),
        tenant_id=tenant_id,
        user_role="manager",
    )
    preview_match = next(
        (
            row
            for row in (preview.candidate_rows or [])
            if str(row.get("emp_id") or "").strip() == employee_code
            and str(row.get("work_date") or "").strip()[:10] == work_date
            and str(row.get("department") or "").strip() == department
        ),
        None,
    )
    _emit(
        "preview",
        "ok" if preview_match else "missing",
        {
            "success": bool(preview.success),
            "can_import": bool(preview.can_import),
            "candidate_count": len(preview.candidate_rows or []),
            "issue_count": len(preview.invalid_issues or []),
            "matched_candidate": preview_match,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "row_index": issue.row_index,
                    "field": issue.field,
                    "message": issue.message,
                    "value": issue.value,
                }
                for issue in (preview.invalid_issues or [])
            ],
        },
        tenant_id,
    )

    # B. Before write
    _emit(
        "before_write",
        "ok" if preview_match else "missing",
        {
            "present_in_confirm_candidate_set": bool(preview_match),
            "candidate_key": {
                "emp_id": employee_code,
                "work_date": work_date,
                "department": department,
            },
        },
        tenant_id,
    )

    commit = confirm_import(
        preview,
        tenant_id=tenant_id,
        upload_name=f"trace_one_row_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv",
        user_role="manager",
    )
    _emit(
        "confirm_import",
        "ok" if commit.success else "failed",
        {
            "success": bool(commit.success),
            "inserted_rows": int(commit.summary.inserted_rows or 0),
            "message": str(commit.message or ""),
            "upload_id": str(commit.upload_id or ""),
        },
        tenant_id,
    )

    # C. After write
    written_row = _query_uph_row(
        tenant_id=tenant_id,
        employee_row_id=employee_row_id,
        work_date=work_date,
        department=department,
    )
    _emit(
        "after_write",
        "ok" if written_row else "missing",
        {
            "uph_history_row": written_row,
            "lookup": {
                "tenant_id": tenant_id,
                "emp_id_numeric": employee_row_id,
                "work_date": work_date,
                "department": department,
            },
        },
        tenant_id,
    )

    # D. During postprocess / snapshot
    post: dict[str, Any] = {}
    post_error = ""
    try:
        post = run_import_postprocess_job(
            uph_rows=list(preview.candidate_rows or []),
            tenant_id=tenant_id,
            source_import_job_id=f"trace-job-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            source_import_file="trace_one_row.csv",
            source_upload_id=str(commit.upload_id or ""),
            data_quality_status="partial",
            exclusion_note="trace-run",
            handling_choice="review_details",
            handling_note="trace",
            from_date=work_date,
            to_date=work_date,
            replace_existing_snapshots=True,
            ingest_activity=True,
        )
    except Exception as exc:
        post_error = str(exc)

    snapshot_row = _query_snapshot_row(
        tenant_id=tenant_id,
        employee_code=employee_code,
        work_date=work_date,
        department=department,
    )
    _emit(
        "postprocess_snapshot",
        "ok" if snapshot_row else "missing",
        {
            "postprocess_result": post,
            "postprocess_error": post_error,
            "window_includes_row_date": True,
            "snapshot_row": snapshot_row,
        },
        tenant_id,
    )

    # E. Today/Team read paths
    try:
        compute_daily_signals(signal_date=date.fromisoformat(work_date), tenant_id=tenant_id)
    except Exception as exc:
        _emit("today_compute", "failed", {"error": str(exc)}, tenant_id)

    today_payload = read_precomputed_today_signals(
        tenant_id=tenant_id,
        signal_date=date.fromisoformat(work_date),
    )
    in_goal, in_queue, today_reason = _in_today_payload(today_payload, employee_code)

    team_goal_status, _team_history, team_snapshot_date = get_latest_snapshot_goal_status(
        tenant_id=tenant_id,
        days=30,
        rebuild_if_missing=False,
    )
    in_team = _in_team_rows(team_goal_status, employee_code)

    _emit(
        "today_team_read",
        "ok" if (in_goal or in_queue or in_team) else "filtered_or_missing",
        {
            "today_has_payload": bool(today_payload),
            "today_in_goal_status": bool(in_goal),
            "today_in_queue": bool(in_queue),
            "today_reason": today_reason,
            "team_snapshot_date": team_snapshot_date,
            "team_in_goal_status": bool(in_team),
        },
        tenant_id,
    )

    survived_all = bool(preview_match and written_row and snapshot_row and (in_goal or in_queue or in_team))
    terminal_stage = "complete" if survived_all else (
        "preview" if not preview_match else
        "after_write" if not written_row else
        "postprocess_snapshot" if not snapshot_row else
        "today_team_read"
    )

    _emit(
        "final_verdict",
        "ok" if survived_all else "lost",
        {
            "survives_all_stages": survived_all,
            "lost_stage": "" if survived_all else terminal_stage,
            "loss_classification": (
                "not_read" if terminal_stage == "today_team_read" else
                "not_materialized" if terminal_stage == "postprocess_snapshot" else
                "not_written" if terminal_stage == "after_write" else
                "excluded"
            ) if not survived_all else "",
        },
        tenant_id,
    )

    return 0 if survived_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
