import threading
from datetime import date

from core.dependencies import log_app_error, tenant_log_path
from core.runtime import st, time, traceback


EMAIL_SCHEDULER_ENABLED = False
_email_thread_started = False


def email_log(msg: str) -> None:
    try:
        from datetime import datetime as dt

        path = tenant_log_path("dpd_email_scheduler")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{dt.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")
    except Exception:
        pass


def run_scheduled_reports_for_tenant(tenant_id: str = "", force_now: bool = False, schedule_names: list[str] | None = None) -> list[dict]:
    if not EMAIL_SCHEDULER_ENABLED:
        return []

    from database import get_client as sched_client, get_subscription
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

    tid = tenant_id or st.session_state.get("tenant_id", "")
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
        else:
            email_log(f"[{tid[:8]}] FAILED '{schedule.get('name')}': {err}")
        results.append({
            "name": schedule.get("name", ""),
            "ok": ok,
            "error": err,
            "recipients": send_to,
        })
    return results


def _bg_send_scheduled_emails() -> None:
    if not EMAIL_SCHEDULER_ENABLED:
        return

    try:
        from database import SUPABASE_KEY as bg_key, SUPABASE_URL as bg_url
        from supabase import create_client as bg_create

        sb = bg_create(bg_url, bg_key)
        try:
            response = sb.table("tenant_email_config").select("tenant_id, schedules").execute()
            tenant_configs = response.data or []
        except Exception as error:
            email_log(f"Could not fetch tenant email configs: {error}")
            return

        for tenant_cfg in tenant_configs:
            tid = tenant_cfg.get("tenant_id", "")
            schedules = tenant_cfg.get("schedules") or []
            if not tid or not schedules:
                continue
            try:
                results = run_scheduled_reports_for_tenant(tenant_id=tid, force_now=False)
                if not results and schedules:
                    email_log(f"[{tid[:8]}] Has {len(schedules)} schedule(s) but none are due now")
            except Exception as tenant_error:
                email_log(f"[{tid[:8]}] Tenant error: {tenant_error}")
                try:
                    from database import log_error

                    log_error("email", f"Tenant processing error: {tenant_error}", severity="error", tenant_id=tid)
                except Exception:
                    pass
    except Exception as thread_error:
        email_log(f"Thread error: {thread_error}")


def start_email_thread():
    if not EMAIL_SCHEDULER_ENABLED:
        return None

    global _email_thread_started
    if _email_thread_started:
        return None
    _email_thread_started = True

    def _loop():
        time.sleep(30)
        email_log("Background email thread started")
        while True:
            try:
                _bg_send_scheduled_emails()
            except Exception as error:
                email_log(f"Unhandled loop error: {error}")
            time.sleep(60)

    thread = threading.Thread(target=_loop, daemon=True, name="email-scheduler")
    thread.start()
    return thread


def run_page_render_email_check() -> None:
    if not EMAIL_SCHEDULER_ENABLED:
        return
    now = time.time()
    if now - st.session_state.get("_last_email_check", 0) > 60:
        st.session_state["_last_email_check"] = now
        try:
            run_scheduled_reports_for_tenant(force_now=False)
        except Exception as error:
            email_log(f"Page-render email check error: {error}")
            log_app_error("email", f"Schedule check error: {error}", detail=traceback.format_exc())
