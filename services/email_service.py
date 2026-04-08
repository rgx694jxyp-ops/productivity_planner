from datetime import date

from services.observability import log_operational_event, tenant_log_path


def email_log(msg: str) -> None:
    try:
        from datetime import datetime as dt

        path = tenant_log_path("dpd_email_scheduler")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{dt.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")
    except Exception:
        pass


def run_scheduled_reports_for_tenant(tenant_id: str, force_now: bool = False, schedule_names: list[str] | None = None) -> list[dict]:
    from repositories._common import get_client as sched_client
    from repositories.billing_repo import get_subscription
    from email_engine import (
        get_schedules,
        get_schedules_due_now,
        load_email_config,
        mark_schedule_sent,
        send_report_email,
    )
    from goals import load_goals
    from services.productivity_service import _build_period_report, _resolve_period_dates
    from settings import Settings

    tid = str(tenant_id or "").strip()
    if not tid:
        return []

    schedule_filter = set(schedule_names or [])
    tz = Settings(tenant_id=tid).get("timezone", "")
    schedules = get_schedules(tid)
    due = [schedule for schedule in schedules if schedule.get("active")] if force_now else get_schedules_due_now(timezone=tz, tenant_id=tid)
    if schedule_filter:
        due = [schedule for schedule in due if schedule.get("name", "") in schedule_filter]
    if not due:
        return []

    tenant_cfg = load_email_config(tenant_id=tid)
    global_recips = [
        recipient.get("email", "").strip()
        for recipient in (tenant_cfg.get("recipients") or [])
        if recipient.get("email")
    ]
    try:
        sb = sched_client()
        emp_resp = sb.table("employees").select("department").eq("tenant_id", tid).execute()
        depts = sorted({(row.get("department") or "").strip() for row in (emp_resp.data or []) if row.get("department")})
    except Exception:
        depts = []
    targets = (load_goals(tenant_id=tid) or {}).get("dept_targets", {})
    plan_name = ((get_subscription(tid) or {}).get("plan") or "starter").lower()

    results = []
    for schedule in due:
        send_to = schedule.get("recipients", []) or global_recips
        if not send_to:
            results.append({"name": schedule.get("name", ""), "ok": False, "error": "No recipients configured", "recipients": []})
            continue

        period = schedule.get("report_period", "Prior day")
        if period == "Custom":
            try:
                start_date = date.fromisoformat(schedule.get("date_start", date.today().isoformat()))
                end_date = date.fromisoformat(schedule.get("date_end", start_date.isoformat()))
            except Exception:
                start_date, end_date = _resolve_period_dates("Prior day")
        else:
            start_date, end_date = _resolve_period_dates(period)

        xl_data, default_subject, body = _build_period_report(
            start_date,
            end_date,
            "All departments",
            depts,
            [],
            targets,
            tenant_id=tid,
            plan_name=plan_name,
        )
        subject = (schedule.get("subject_tpl") or "").strip() or default_subject
        ok, err = send_report_email(send_to, subject, body, xl_data, tenant_id=tid)
        if ok:
            mark_schedule_sent(schedule.get("name", ""), timezone=tz, tenant_id=tid)
            email_log(f"[{tid[:8]}] SENT '{schedule.get('name')}' to {send_to} (tz={tz or 'not set'})")
            log_operational_event(
                "email_delivery",
                status="success",
                tenant_id=tid,
                detail="Scheduled report sent",
                context={"schedule": schedule.get("name", ""), "recipient_count": len(send_to)},
            )
        else:
            email_log(f"[{tid[:8]}] FAILED '{schedule.get('name')}': {err}")
            log_operational_event(
                "email_failure",
                status="failed",
                tenant_id=tid,
                detail="Scheduled report send failed",
                context={"schedule": schedule.get("name", ""), "error": str(err or "")},
            )
        results.append({
            "name": schedule.get("name", ""),
            "ok": ok,
            "error": err,
            "recipients": send_to,
        })
    return results
