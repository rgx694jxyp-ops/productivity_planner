"""
app.py — Productivity Planner
Run with:   streamlit run app.py

╔════════════════════════════════════════════════════════════════════════════════╗
║                         CODE STRUCTURE MAP                                     ║
╚════════════════════════════════════════════════════════════════════════════════╝

IMPORTS & SETUP
  - Standard library imports
  - Streamlit & external dependencies
  - Database & module imports with error handling
  - Data loader imports

CORE CACHE SYSTEM (Lines ~50-120)
  - Tenant ID helpers (_tid)
  - Raw cache functions (_raw_cached_*)
  - Wrapper functions (_cached_*) for clean API

SESSION & AUTH HELPERS (Lines ~120-190)
  - Sign out, cache clearing
  - Success messages, logging
  - Error tracking

EMAIL BACKGROUND SYSTEM (Lines ~190-370)
  - Background email scheduler thread
  - Email logging and sending pipeline

APP INITIALIZATION & STATE (Lines ~370-800)
  - Main setup (_init)
  - Plan management
  - Sidebar navigation (render_sidebar)

CORE BUSINESS LOGIC (Lines ~800-1000)
  - Database availability check
  - Risk calculation (_calc_risk_level_shared) - SHARED ACROSS ALL VIEWS

PAGE FUNCTIONS (Lines ~1000-6000, Ordered by Navigation)
  - page_supervisor()      👔 Supervisor View (daily dashboard)
  - page_dashboard()       📊 Dashboard (risk view)
  - page_import()          📁 Import Data (3-step pipeline)
  - page_employees()       👥 Employees (individual profiles)
  - page_productivity()    📈 Productivity (UPH, trends, coaching, labor cost)
  - page_email()           📧 Email Setup (SMTP, schedules, send)
  - page_settings()        ⚙️ Settings (goals, display, audit)

IMPORT HELPER FUNCTIONS (Lines ~1600-1900)
  - Step 1: Upload CSV files
  - Step 2: Column mapping
  - Step 3: Data pipeline & validation

EMPLOYEE PAGE HELPERS (Lines ~2300-2700)
  - Employee history view
  - AI coaching suggestions
  - Manual coaching notes

REPORT BUILDERS (Lines ~4500-4800)
  - Period report generation
  - HTML email body construction

CRITICAL HELPERS (Lines ~5500-5900)
  - CSV parsing
  - Column auto-detection
  - Access control
  - Login flow

SUBSCRIPTION & CHECKOUT (Lines ~5900-6160)
  - Session timeout checking
  - Stripe integration
  - Subscription page

MAIN ENTRY POINT (Line ~6160)
  - main() function
  - Router logic
  - Startup sequence
"""

import io, os, sys, csv, json, tempfile, traceback, threading, time, math, re, html as _html_mod
from datetime import datetime, date
import pandas as pd

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Temporary product decision: keep manual email only, disable automated schedules.
EMAIL_SCHEDULER_ENABLED = False

# ════════════════════════════════════════════════════════════════════════════════
# IMPORTS FROM INTERNAL MODULES
# ════════════════════════════════════════════════════════════════════════════════

# ── Guard: show friendly error if supabase not installed ─────────────────────
try:
    from database import (
        get_employees, get_employee, upsert_employee,
        get_uph_history, get_avg_uph,
        add_coaching_note, get_coaching_notes, delete_coaching_note, archive_coaching_notes,
        get_client as _get_db_client,
        batch_store_uph_history, get_all_uph_history,
        batch_upsert_employees,
    )
    from export_manager import (export_employee)
    DB_AVAILABLE = True
except RuntimeError as e:
    DB_AVAILABLE = False
    DB_ERROR     = str(e)
except ImportError as e:
    DB_AVAILABLE = False
    _ie = str(e)
    if "supabase" in _ie.lower():
        DB_ERROR = "supabase library not installed. Run:  pip3 install supabase"
    else:
        DB_ERROR = f"Import error: {_ie}"
except Exception as e:
    DB_AVAILABLE = False
    DB_ERROR     = f"Unexpected error loading database module: {type(e).__name__}: {e}"

# Backward-compatible DB client shim. Prevents NameError in production if
# _get_db_client was not imported due to an older deployment/import path.
try:
    _ = _get_db_client  # type: ignore[name-defined]  # assignment suppresses Streamlit magic rendering
except NameError:
    def _get_db_client():
        from database import get_client as _db_get_client
        return _db_get_client()

from data_loader import (REQUIRED_FIELDS,
                         auto_detect as _dl_auto_detect,
                         parse_csv_bytes as _dl_parse_csv)

from ui_improvements import (
    diagnose_upload, show_diagnosis, show_manual_entry_form,
    find_coaching_impact, show_coaching_impact,
    is_simple_mode, toggle_simple_mode, simplified_supervisor_view,
    human_confidence_message, translate_to_floor_language, risk_to_human_language,
    show_start_shift_card, build_operation_status, show_operation_status_header,
    detect_department_patterns, show_pattern_detection_panel,
    summarize_coaching_activity, show_coaching_activity_summary,
    show_resume_session_card, show_shift_complete_state,
    _render_priority_strip, _render_primary_action_rail,
    _render_confidence_ux, _render_session_progress,
    _apply_mode_styling, _render_soft_action_buttons,
    _render_adaptive_action_suggestion, _render_session_context_bar,
    _render_breadcrumb, _enhance_coaching_feedback,
)

from cache import (
    bust_cache as _bust_cache,
    cached_active_flags as _cached_active_flags,
    cached_all_coaching_notes as _cached_all_coaching_notes,
    cached_coaching_notes_for as _cached_coaching_notes_for,
    cached_employees as _cached_employees,
    cached_targets as _cached_targets,
    cached_uph_history as _cached_uph_history,
)
from auth import (
    check_session_timeout as _auth_check_session_timeout,
    clear_auth_cookies as _clear_auth_cookies,
    full_sign_out as _auth_full_sign_out,
    login_page as _auth_login_page,
    render_sign_out_button as _render_sign_out_button,
    restore_session_from_cookies as _restore_session_from_cookies,
    set_auth_cookies as _set_auth_cookies,
)
from billing import (
    subscription_page as _billing_subscription_page,
    verify_checkout_and_activate as _billing_verify_checkout_and_activate,
)
from styles import apply_global_styles


# ════════════════════════════════════════════════════════════════════════════════
# CACHE & SESSION SYSTEM
# ════════════════════════════════════════════════════════════════════════════════



# ════════════════════════════════════════════════════════════════════════════════
# SESSION & STATE MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════════

def _full_sign_out():
    _auth_full_sign_out(_bust_cache)


def _verify_checkout_and_activate():
    return _billing_verify_checkout_and_activate()


def _subscription_page():
    return _billing_subscription_page(_render_sign_out_button, _full_sign_out)


def _login_page():
    return _auth_login_page(_bust_cache, _log_app_error)


def _check_session_timeout():
    return _auth_check_session_timeout()


def _success_then_rerun(msg: str, delay: float = 0):
    """Show a success toast and rerun immediately."""
    st.toast(msg, icon="✅")
    st.rerun()


def _tenant_log_path(base_name: str) -> str:
    """Return a tenant-specific log file path."""
    import os as _os
    _dir = _os.path.dirname(__file__)
    tid = st.session_state.get("tenant_id", "")
    if tid:
        return _os.path.join(_dir, f"{base_name}_{tid}.log")
    return _os.path.join(_dir, f"{base_name}.log")

def _audit(action: str, detail: str = ""):
    """Append a timestamped entry to tenant-specific audit log."""
    try:
        from datetime import datetime as _dt
        log_path = _tenant_log_path("dpd_audit")
        entry    = f"{_dt.now().strftime('%Y-%m-%d %H:%M:%S')} | {action} | {detail}\n"
        with open(log_path, "a", encoding="utf-8") as _f:
            _f.write(entry)
    except Exception:
        pass


def _log_app_error(category: str, message: str, detail: str = "",
                   severity: str = "error"):
    """Log an error to the DB error_reports table. Never raises."""
    try:
        from database import log_error
        _email = st.session_state.get("user_email", "")
        log_error(
            category=category,
            message=message,
            detail=detail,
            user_email=_email,
            severity=severity,
        )
    except Exception:
        # Last resort: print to server console
        print(f"[APP_ERROR] [{severity}] [{category}] {message}")


# ════════════════════════════════════════════════════════════════════════════════
# EMAIL & BACKGROUND JOBS
# ════════════════════════════════════════════════════════════════════════════════

# ── Background email scheduler ────────────────────────────────────────────────
# Runs in a daemon thread so emails fire at the scheduled time even when no
# user is actively viewing the app. Started only once via a module-level flag.

def _email_log(msg: str):
    """Append a line to tenant-specific email scheduler log."""
    try:
        import os as _eos
        from datetime import datetime as _edt
        _p = _tenant_log_path("dpd_email_scheduler")
        with open(_p, "a", encoding="utf-8") as _f:
            _f.write(f"{_edt.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")
    except Exception:
        pass


def _email_timezone_options() -> list[str]:
    return [
        "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
        "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
        "America/Toronto", "America/Vancouver", "America/Winnipeg", "America/Halifax",
        "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
        "Europe/Rome", "Europe/Amsterdam", "Europe/Zurich", "Europe/Stockholm",
        "Europe/Warsaw", "Europe/Istanbul",
        "Asia/Dubai", "Asia/Kolkata", "Asia/Bangkok", "Asia/Singapore",
        "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
        "Australia/Sydney", "Australia/Melbourne", "Pacific/Auckland",
        "UTC",
    ]


def _run_scheduled_reports_for_tenant(tenant_id: str = "", force_now: bool = False,
                                      schedule_names: list[str] | None = None) -> list[dict]:
    """Send scheduled reports for one tenant and return per-schedule results."""
    if not EMAIL_SCHEDULER_ENABLED:
        return []

    from email_engine import (
        get_schedules_due_now, get_schedules, send_report_email,
        mark_schedule_sent, load_email_config,
    )
    from settings import Settings
    from goals import load_goals
    from database import get_subscription, get_client as _sched_client

    tid = tenant_id or st.session_state.get("tenant_id", "")
    if not tid:
        return []

    schedule_filter = set(schedule_names or [])
    tz = Settings(tenant_id=tid).get("timezone", "")
    schedules = get_schedules(tid)
    due = [s for s in schedules if s.get("active")] if force_now else get_schedules_due_now(timezone=tz, tenant_id=tid)
    if schedule_filter:
        due = [s for s in due if s.get("name", "") in schedule_filter]
    if not due:
        return []

    tenant_cfg = load_email_config(tenant_id=tid)
    global_recips = [
        r.get("email", "").strip()
        for r in (tenant_cfg.get("recipients") or [])
        if r.get("email")
    ]
    try:
        sb = _sched_client()
        emp_resp = sb.table("employees").select("department").eq("tenant_id", tid).execute()
        depts = sorted({(row.get("department") or "").strip() for row in (emp_resp.data or []) if row.get("department")})
    except Exception:
        depts = []
    targets = (load_goals(tenant_id=tid) or {}).get("dept_targets", {})
    plan_name = ((get_subscription(tid) or {}).get("plan") or "starter").lower()

    results = []
    for sched in due:
        send_to = sched.get("recipients", []) or global_recips
        if not send_to:
            results.append({"name": sched.get("name", ""), "ok": False, "error": "No recipients configured", "recipients": []})
            continue

        period = sched.get("report_period", "Prior day")
        if period == "Custom":
            try:
                d_start = date.fromisoformat(sched.get("date_start", date.today().isoformat()))
                d_end = date.fromisoformat(sched.get("date_end", d_start.isoformat()))
            except Exception:
                d_start, d_end = _resolve_period_dates("Prior day")
        else:
            d_start, d_end = _resolve_period_dates(period)

        xl_data, default_subject, body = _build_period_report(
            d_start, d_end, "All departments", depts, [], targets,
            tenant_id=tid, plan_name=plan_name,
        )
        subject = (sched.get("subject_tpl") or "").strip() or default_subject
        ok, err = send_report_email(send_to, subject, body, xl_data, tenant_id=tid)
        if ok:
            mark_schedule_sent(sched.get("name", ""), timezone=tz, tenant_id=tid)
            _email_log(f"[{tid[:8]}] SENT '{sched.get('name')}' to {send_to} (tz={tz or 'not set'})")
        else:
            _email_log(f"[{tid[:8]}] FAILED '{sched.get('name')}': {err}")
        results.append({
            "name": sched.get("name", ""),
            "ok": ok,
            "error": err,
            "recipients": send_to,
        })
    return results


def _bg_send_scheduled_emails():
    """Called by the background thread every 60 s to fire due email schedules.
    Iterates over ALL tenants with email configs — no st.session_state needed."""
    if not EMAIL_SCHEDULER_ENABLED:
        return

    try:
        from database    import SUPABASE_URL as _BG_URL, SUPABASE_KEY as _BG_KEY
        from supabase    import create_client as _bg_create

        # Create a fresh Supabase client (can't use session-cached one in bg thread)
        sb = _bg_create(_BG_URL, _BG_KEY)

        # Get all tenant email configs that have schedules
        try:
            r = sb.table("tenant_email_config").select("tenant_id, schedules").execute()
            tenant_configs = r.data or []
        except Exception as _e:
            _email_log(f"Could not fetch tenant email configs: {_e}")
            return

        for tc in tenant_configs:
            tid = tc.get("tenant_id", "")
            scheds = tc.get("schedules") or []
            if not tid or not scheds:
                continue

            try:
                results = _run_scheduled_reports_for_tenant(tenant_id=tid, force_now=False)
                if not results and scheds:
                    _email_log(f"[{tid[:8]}] Has {len(scheds)} schedule(s) but none are due now")
            except Exception as _te2:
                _email_log(f"[{tid[:8]}] Tenant error: {_te2}")
                try:
                    from database import log_error
                    log_error("email", f"Tenant processing error: {_te2}",
                              severity="error", tenant_id=tid)
                except Exception:
                    pass
    except Exception as _te:
        _email_log(f"Thread error: {_te}")


_email_thread_started = False

def _start_email_thread():
    """Start a background thread that checks email schedules every 60 s. Idempotent."""
    if not EMAIL_SCHEDULER_ENABLED:
        return None

    global _email_thread_started
    if _email_thread_started:
        return
    _email_thread_started = True

    import time as _time

    def _loop():
        _time.sleep(30)   # brief startup delay so the app finishes loading first
        _email_log("Background email thread started")
        while True:
            try:
                _bg_send_scheduled_emails()
            except Exception as _e:
                _email_log(f"Unhandled loop error: {_e}")
            _time.sleep(60)

    t = threading.Thread(target=_loop, daemon=True, name="email-scheduler")
    t.start()
    return t


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title = "Productivity Planner",
    page_icon  = "📦",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

apply_global_styles()



# ── Session state ─────────────────────────────────────────────────────────────

def _roll_coached_yesterday():
    """Carry yesterday's coaching count into _coached_yesterday when the date changes.
    Called once per session on startup so the 'Welcome back' message has real context."""
    _last_date = st.session_state.get("_coached_date", "")
    _today     = date.today().isoformat()
    if _last_date and _last_date != _today:
        # Date rolled over — preserve count for welcome message, reset today counter
        st.session_state["_coached_yesterday"] = int(st.session_state.get("_coached_today", 0))
        st.session_state["_coached_today"]     = 0
        st.session_state.pop("_welcome_shown", None)  # re-show welcome on new day
    st.session_state["_coached_date"] = _today


def _init():
    defaults = {
        "uploaded_sessions":  [],   # list of {filename, rows, mapping, timestamp}
        "submission_plan":    None, # pending plan awaiting continuation
        "split_overrides":    {},   # emp_id -> list of split assignments
        # Step navigation
        "import_step":        1,    # 1=upload 2=map(optional) 3=pipeline
        "alloc_rows":         [],   # processed rows from pipeline
        "alloc_date":         None, # work date from pipeline
        "chart_months":       12,
        "trend_weeks":        4,
        "target_uph":         0.0,
        "top_pct":            10,
        "bot_pct":            10,
        "smart_merge":        True,
        # Productivity pipeline state (kept for backward compat)
        "raw_rows":           [],
        "csv_headers":        [],
        "mapping":            {},
        "mapping_ready":      False,
        "history":            [],
        "top_performers":     [],
        "dept_report":        {},
        "dept_trends":        [],
        "weekly_summary":     [],
        "employee_rolling_avg": [],
        "employee_risk":       [],
        "goal_status":        [],
        "trend_data":         {},
        "pipeline_done":      False,
        "pipeline_error":     "",
        "warnings":           [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()
_roll_coached_yesterday()


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _get_current_plan() -> str:
    """Return current subscription plan: 'starter', 'pro', 'business', or 'admin'."""
    # Check admin bypass first
    _user_email = st.session_state.get("user_email", "").lower()
    try:
        _admin_emails = [e.strip().lower() for e in st.secrets.get("ADMIN_EMAILS", "").split(",") if e.strip()]
        if _user_email in _admin_emails:
            return "admin"
    except Exception:
        pass
    # Refresh cached plan periodically so open tabs don't retain stale access.
    _cached_plan = st.session_state.get("_current_plan")
    _cached_ts = float(st.session_state.get("_current_plan_ts", 0) or 0)
    if _cached_plan and (time.time() - _cached_ts) < 300:
        return _cached_plan
    try:
        from database import get_subscription
        sub = get_subscription()
        plan = sub.get("plan", "starter") if sub else "starter"
        st.session_state["_current_plan"] = plan
        st.session_state["_current_plan_ts"] = time.time()
        return plan
    except Exception:
        return "starter"


def _plan_rank(plan: str) -> int:
    return {"starter": 1, "pro": 2, "business": 3, "admin": 99}.get((plan or "").lower(), 1)


def _has_plan(min_plan: str) -> bool:
    return _plan_rank(_get_current_plan()) >= _plan_rank(min_plan)


def _plan_gate(min_plan: str, feature_name: str) -> bool:
    if _has_plan(min_plan):
        return True
    st.info(f"{feature_name} is available on **{min_plan.capitalize()}** and above.")
    st.caption("Upgrade in Settings → Subscription to unlock this feature.")
    return False


def render_sidebar() -> str:
    _plan = _get_current_plan()

    with st.sidebar:
        st.markdown("""
<div style="padding:8px 0 20px;">
  <div style="font-size:19px;font-weight:700;color:#fff;letter-spacing:-.02em;line-height:1.15;">
    📦 Productivity<br>Planner
  </div>
</div>""", unsafe_allow_html=True)

        st.divider()

        # Build nav with stable internal keys so routing does not depend on
        # emoji rendering/encoding.
        nav_items = [
            ("supervisor", "👔  Supervisor"),
            ("dashboard", "📊  Dashboard"),
            ("import", "📁  Import Data"),
            ("employees", "👥  Employees"),
            ("productivity", "📈  Productivity"),
            ("email", "📧  Email Setup"),
        ]
        nav_items.append(("settings", "⚙️  Settings"))

        nav_keys = [k for k, _ in nav_items]
        nav_labels = {k: lbl for k, lbl in nav_items}

        goto = str(st.session_state.pop("goto_page", "") or "").lower()
        if goto:
            if goto in nav_keys:
                st.session_state["_current_page_key"] = goto
            elif "supervisor" in goto:
                st.session_state["_current_page_key"] = "supervisor"
            elif "dashboard" in goto:
                st.session_state["_current_page_key"] = "dashboard"
            elif "import" in goto:
                st.session_state["_current_page_key"] = "import"
            elif "employee" in goto:
                st.session_state["_current_page_key"] = "employees"
            elif "productivity" in goto:
                st.session_state["_current_page_key"] = "productivity"
            elif "email" in goto:
                st.session_state["_current_page_key"] = "email"
            elif "setting" in goto:
                st.session_state["_current_page_key"] = "settings"

        # One-click nav: let the radio own its state via key= instead of resetting
        # with index= on every rerun (which causes the double-click bug).
        # The goto_page resolver above pre-sets _current_page_key when needed.
        if st.session_state.get("_current_page_key") not in nav_keys:
            st.session_state["_current_page_key"] = nav_keys[0]

        page = st.radio(
            "Navigation",
            nav_keys,
            format_func=lambda k: nav_labels.get(k, k.title()),
            label_visibility="collapsed",
            key="_current_page_key",
        )

        st.divider()
        if st.button("↺ Refresh data", use_container_width=True, key="sb_refresh"):
            _bust_cache()
            st.rerun()

        toggle_simple_mode()
        if st.session_state.get("simple_mode"):
            st.caption("Simple Mode keeps the app focused on who needs attention right now.")

        # ── Plan badge ──────────────────────────────────────────────────
        _plan_display = _plan.capitalize() if _plan != "admin" else "Admin"
        _plan_color = {"starter": "#888", "pro": "#1E90FF", "business": "#FFD700", "admin": "#FF6347"}.get(_plan, "#888")
        st.markdown(
            f'<div style="font-size:10px;color:{_plan_color};font-weight:700;margin-bottom:4px;">'
            f'Plan: {_plan_display}</div>',
            unsafe_allow_html=True,
        )
        try:
            from database import get_employee_count, get_employee_limit
            _ec_ts = float(st.session_state.get("_emp_count_ts", 0) or 0)
            if (time.time() - _ec_ts) > 300 or "_emp_count_cache" not in st.session_state:
                st.session_state["_emp_count_cache"] = get_employee_count()
                st.session_state["_emp_limit_cache"] = get_employee_limit()
                st.session_state["_emp_count_ts"] = time.time()
            _emp_count = st.session_state["_emp_count_cache"]
            _emp_limit = st.session_state["_emp_limit_cache"]
            _limit_str = "unlimited" if _emp_limit == -1 else str(_emp_limit)
            st.markdown(
                f'<div style="font-size:10px;color:#7FA8CC;margin-bottom:8px;">'
                f'Employees: {_emp_count}/{_limit_str}</div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass

        # ── User info + logout ─────────────────────────────────────────────
        user_name = st.session_state.get("user_name", "")
        if user_name:
            _safe_name = _html_mod.escape(user_name)
            st.markdown(
                f'<div style="font-size:11px;color:#7FA8CC;margin-bottom:4px;">'
                f'Signed in as<br><b style="color:#CBD8E8;">{_safe_name}</b></div>',
                unsafe_allow_html=True,
            )
        if _render_sign_out_button("sidebar", type="secondary", use_container_width=True):
            _full_sign_out()
            st.rerun()

        st.markdown(
            '<div style="font-size:10px;color:#3D5A7A;line-height:1.7;">'
            'Productivity Planner · v3.0</div>',
            unsafe_allow_html=True,
        )
    return page


# ── DB gate ───────────────────────────────────────────────────────────────────

def require_db() -> bool:
    if not DB_AVAILABLE:
        st.error(f"Database not available: {DB_ERROR}")
        st.info("Run `pip3 install supabase` in your terminal then restart the app.")
        return False
    return True


# ── Risk calculation (shared by Supervisor View and Dashboard) ────────────────

def _calc_risk_level(emp, history):
    """Calculate performance risk level: 🔴 High, 🟡 Medium, 🟢 Low.
    Combines: trend + under-goal streak + variance.
    Returns: (risk_level, risk_score, details_dict)
    
    Used by: page_supervisor, page_dashboard, page_productivity.
    """
    risk_score = 0.0
    details = {
        "trend_score": 0,
        "streak_score": 0,
        "variance_score": 0,
    }
    
    trend = emp.get("trend", "insufficient_data")
    if trend == "down":
        risk_score += 4
        details["trend_score"] = 4
    elif trend == "flat":
        risk_score += 1
        details["trend_score"] = 1
    elif trend == "up":
        risk_score -= 2
        details["trend_score"] = -2
    
    emp_id = str(emp.get("EmployeeID", emp.get("Employee Name", "")))
    target_uph = emp.get("Target UPH", "—")
    under_goal_streak = 0
    
    if history and target_uph != "—":
        try:
            target = float(target_uph)
            emp_history = [r for r in history
                           if str(r.get("EmployeeID", r.get("Employee Name", ""))) == emp_id]
            if emp_history:
                sorted_hist = sorted(emp_history,
                                    key=lambda r: (r.get("Date", "") or r.get("Week", "")))
                for r in reversed(sorted_hist):
                    try:
                        uph_val = float(r.get("UPH", 0) or 0)
                        if uph_val < target:
                            under_goal_streak += 1
                        else:
                            break
                    except (ValueError, TypeError):
                        break
        except (ValueError, TypeError):
            pass
    
    if under_goal_streak >= 7:
        risk_score += 5
        details["streak_score"] = 5
    elif under_goal_streak >= 5:
        risk_score += 4
        details["streak_score"] = 4
    elif under_goal_streak >= 3:
        risk_score += 2.5
        details["streak_score"] = 2.5
    elif under_goal_streak >= 1:
        risk_score += 0.5
        details["streak_score"] = 0.5
    
    variance = 0.0
    uph_values = []
    if history:
        emp_history = [r for r in history
                       if str(r.get("EmployeeID", r.get("Employee Name", ""))) == emp_id]
        for r in emp_history:
            try:
                uph_val = float(r.get("UPH", 0) or 0)
                if uph_val > 0:
                    uph_values.append(uph_val)
            except (ValueError, TypeError):
                pass
    
    if len(uph_values) >= 3:
        avg_uph = sum(uph_values) / len(uph_values)
        variance = sum((x - avg_uph) ** 2 for x in uph_values) / len(uph_values)
        std_dev = variance ** 0.5
        coeff_variation = (std_dev / avg_uph * 100) if avg_uph > 0 else 0
        
        if coeff_variation > 30:
            risk_score += 3
            details["variance_score"] = 3
        elif coeff_variation > 20:
            risk_score += 1.5
            details["variance_score"] = 1.5
        elif coeff_variation > 10:
            risk_score += 0.5
            details["variance_score"] = 0.5
        
        details["variance_pct"] = round(coeff_variation, 1)
    
    details["under_goal_streak"] = under_goal_streak
    details["total_score"] = round(risk_score, 1)
    
    if risk_score >= 7:
        return "🔴 High", risk_score, details
    elif risk_score >= 4:
        return "🟡 Medium", risk_score, details
    else:
        return "🟢 Low", risk_score, details


# Alias: some code paths call this as _calc_risk_level_shared
_calc_risk_level_shared = _calc_risk_level


def _get_all_risk_levels(gs: list, history: list) -> dict:
    """Compute risk levels for all below-goal employees once per render cycle."""
    _ver = (len(gs), len(history))
    if st.session_state.get("_risk_cache_ver") == _ver:
        return st.session_state.get("_risk_cache", {})
    cache = {}
    for row in gs:
        if row.get("goal_status") == "below_goal":
            emp_id = str(row.get("EmployeeID", row.get("Employee Name", "")))
            cache[emp_id] = _calc_risk_level(row, history)
    st.session_state["_risk_cache"] = cache
    st.session_state["_risk_cache_ver"] = _ver
    return cache


# ════════════════════════════════════════════════════════════════════════════════
# PAGE: SUPERVISOR VIEW
# Daily one-screen view: department health, top risks, trending alerts, actions
# CRITICAL: This is the primary daily-use screen
# ════════════════════════════════════════════════════════════════════════════════

def page_supervisor():
    from pages.supervisor import page_supervisor as _impl
    return _impl()


def page_dashboard():
    from pages.dashboard import page_dashboard as _impl
    return _impl()


def page_import():
    from pages.import_page import page_import as _impl
    return _impl()


def page_employees():
    from pages.employees import page_employees as _impl
    return _impl()


def page_productivity():
    from pages.productivity import page_productivity as _impl
    return _impl()


def page_email():
    from pages.email_page import page_email as _impl
    return _impl()


def page_settings():
    from pages.settings_page import page_settings as _impl
    return _impl()


def _track_landing_event(event: str, detail: str = ""):
    """Best-effort landing page event tracking via tenant-aware audit log."""
    try:
        _audit(f"landing:{event}", detail)
    except Exception:
        pass


def show_landing_page():
    """Public landing page for unauthenticated visitors (no free-trial messaging)."""
    if not st.session_state.get("_lp_view_logged"):
        st.session_state["_lp_view_logged"] = True
        _track_landing_event("view")

    st.markdown(
        """
        <style>
        .lp-sticky {
            position: fixed;
            bottom: 12px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 9999;
            background: rgba(15, 45, 82, 0.96);
            border: 1px solid #4DA3FF;
            box-shadow: 0 8px 24px rgba(15,45,82,0.35);
            border-radius: 999px;
            padding: 8px 10px;
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .lp-sticky a {
            text-decoration: none;
            font-size: 12px;
            font-weight: 700;
            border-radius: 999px;
            padding: 8px 12px;
        }
        .lp-sticky .lp-primary {
            background: #4DA3FF;
            color: #01223F;
        }
        .lp-sticky .lp-ghost {
            background: rgba(77,163,255,0.16);
            color: #E8F0F9;
            border: 1px solid rgba(77,163,255,0.35);
        }
        .lp-hero {
            text-align: center;
            padding: 40px 16px 16px;
        }
        .lp-eyebrow {
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
            color: #1A4A8A;
            background: #E8F0F9;
            border: 1px solid #C5D4E8;
            border-radius: 999px;
            padding: 5px 10px;
            margin-bottom: 10px;
        }
        .lp-title {
            font-size: 2.2rem;
            font-weight: 800;
            color: #0F2D52;
            letter-spacing: -0.02em;
            margin-bottom: 6px;
        }
        .lp-sub {
            font-size: 1.05rem;
            color: #39506A;
            margin-bottom: 8px;
        }
        .lp-note {
            font-size: 0.95rem;
            color: #5A7A9C;
            margin-bottom: 10px;
        }
        .lp-section {
            margin-top: 28px;
        }
        .lp-card {
            background: #ffffff;
            border: 1px solid #E2EBF4;
            border-radius: 10px;
            padding: 16px;
            height: 100%;
        }
        .lp-list {
            color: #1A2D42;
            line-height: 1.8;
            margin: 0;
            padding-left: 18px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="lp-sticky">'
        '<a class="lp-primary" href="?start=1">Get Started</a>'
        '<a class="lp-ghost" href="?demo=1">See Demo</a>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="lp-hero">', unsafe_allow_html=True)
    st.markdown('<div class="lp-eyebrow">Built for small warehouses</div>', unsafe_allow_html=True)
    st.markdown('<div class="lp-title">Run your warehouse without guesswork</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="lp-sub">Know who needs coaching, what to say, and what to do next — using data you already have.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="lp-note">No setup required. Works with spreadsheets or manual entry.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    if c1.button("Get Started", type="primary", use_container_width=True, key="lp_get_started_top"):
        _track_landing_event("cta_click", "hero_get_started")
        st.session_state["show_login"] = True
        st.rerun()
    if c2.button("See How It Works", use_container_width=True, key="lp_how_it_works"):
        _track_landing_event("cta_click", "hero_see_how")
        st.session_state["lp_show_demo"] = True
        st.rerun()

    if st.session_state.get("_pending_invite"):
        st.info(f"Team invite detected: {st.session_state.get('_pending_invite')} — continue to sign in to join.")

    st.markdown("### See what you get instantly")
    _shot_cfg = os.getenv("LANDING_SCREENSHOT_PATH", "")
    try:
        _shot_cfg = _shot_cfg or str(st.secrets.get("LANDING_SCREENSHOT_PATH", "") or "")
    except Exception:
        pass
    _shot = _shot_cfg.strip() or os.path.join(os.path.dirname(__file__), "assets", "landing-supervisor-screenshot.png")
    if _shot and os.path.exists(_shot):
        st.image(_shot, use_container_width=True)
    else:
        st.info("Add a screenshot at assets/landing-supervisor-screenshot.png to boost conversions.")
    st.caption("Start your shift knowing exactly who needs attention.")

    _demo_url = os.getenv("LANDING_DEMO_URL", "").strip()
    try:
        _demo_url = _demo_url or str(st.secrets.get("LANDING_DEMO_URL", "") or "").strip()
    except Exception:
        pass
    if st.session_state.get("lp_show_demo") or _demo_url:
        st.markdown("### Watch how it works")
        if _demo_url:
            st.video(_demo_url)
            st.caption("30-second product walkthrough")
        else:
            st.info("Add LANDING_DEMO_URL in environment or secrets to embed your Loom/video.")

    st.markdown("### The problem")
    st.markdown(
        """
        - Teams rely on spreadsheets and memory
        - Coaching is inconsistent shift to shift
        - Priorities are unclear when things get busy
        """
    )

    st.markdown("### The solution")
    st.markdown(
        """
        - See who needs attention now
        - Understand likely causes quickly
        - Take action and track improvement over time
        """
    )

    st.markdown("### How it works")
    st.markdown(
        """
        1. Upload CSV/Excel or enter data manually
        2. Get a prioritized action list
        3. Coach, document, and monitor results
        """
    )

    st.markdown("### What changes after using this")
    b1, b2 = st.columns(2)
    with b1:
        st.markdown('<div class="lp-card"><strong>Before</strong><ul class="lp-list"><li>Guess who needs help</li><li>React too late</li><li>No consistent tracking</li></ul></div>', unsafe_allow_html=True)
    with b2:
        st.markdown('<div class="lp-card"><strong>After</strong><ul class="lp-list"><li>Clear daily priorities</li><li>Faster coaching conversations</li><li>Measurable improvement</li></ul></div>', unsafe_allow_html=True)

    st.markdown("### Simple pricing")
    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown('<div class="lp-card"><strong>Starter</strong><br>$29/month<br><span style="color:#5A7A9C;">Get control of your team</span></div>', unsafe_allow_html=True)
    with p2:
        st.markdown('<div class="lp-card"><strong>Pro</strong><br>$59/month<br><span style="color:#5A7A9C;">Run with deeper insights</span></div>', unsafe_allow_html=True)
    with p3:
        st.markdown('<div class="lp-card"><strong>Business</strong><br>$99/month<br><span style="color:#5A7A9C;">Full operational visibility</span></div>', unsafe_allow_html=True)
    st.caption("Cancel anytime. No contracts.")
    _track_landing_event("view_section", "pricing")

    st.success(
        "✔ No setup required\n"
        "✔ Works with spreadsheets or manual entry\n"
        "✔ Takes minutes to get started\n"
        "✔ Cancel anytime"
    )
    st.info("Not sure if it will fit your team? Reach out and we can help you get set up quickly.")

    st.markdown("---")
    st.markdown("### Start running your warehouse with clarity")
    if st.button("Get Started", type="primary", use_container_width=True, key="lp_get_started_bottom"):
        _track_landing_event("cta_click", "bottom_get_started")
        st.session_state["show_login"] = True
        st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════════

def main():
    if st.query_params.get("logout") == "1":
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        _clear_auth_cookies()
        try:
            del st.query_params["logout"]
        except Exception:
            st.query_params.clear()
        st.session_state["show_login"] = False
        show_landing_page()
        st.stop()

    # ── Landing CTA query actions ─────────────────────────────────────────
    if st.query_params.get("start") == "1":
        st.session_state["show_login"] = True
        _track_landing_event("cta_click", "sticky_get_started")
        try:
            del st.query_params["start"]
        except Exception:
            st.query_params.clear()
    if st.query_params.get("demo") == "1":
        st.session_state["lp_show_demo"] = True
        _track_landing_event("cta_click", "sticky_see_demo")
        try:
            del st.query_params["demo"]
        except Exception:
            st.query_params.clear()

    # ── Capture invite code from URL before auth gate ─────────────────────
    _url_invite = st.query_params.get("invite", "")
    if _url_invite and not st.session_state.get("_pending_invite"):
        st.session_state["_pending_invite"] = _url_invite.strip().lower()
        st.query_params.clear()

    # ── Auth gate ──────────────────────────────────────────────────────────
    if "supabase_session" not in st.session_state and not _restore_session_from_cookies():
        if not st.session_state.get("show_login", False):
            show_landing_page()
            st.stop()
        if st.button("← Back", key="lp_back_to_landing"):
            st.session_state["show_login"] = False
            st.rerun()
        _login_page()
        st.stop()

    # ── Idle timeout ──────────────────────────────────────────────────────
    if _check_session_timeout():
        st.info("Session expired due to inactivity. Please sign in again.")
        _login_page()
        st.stop()

    # ── Billing portal return — force subscription re-sync ────────────────
    if st.query_params.get("portal") == "return":
        st.query_params.clear()
        st.session_state.pop("_sub_active", None)
        st.session_state.pop("_portal_synced_plan", None)
        _bust_cache()
        with st.spinner("Refreshing your subscription…"):
            try:
                _synced_ok = _verify_checkout_and_activate()
            except Exception:
                _synced_ok = False
        if _synced_ok:
            # Read back what was written so we can show a confirmation
            try:
                from database import get_subscription as _gs
                _new_sub = _gs()
                if _new_sub:
                    st.session_state["_portal_synced_plan"] = _new_sub.get("plan", "").capitalize()
            except Exception:
                pass
        st.rerun()

    # ── Subscription gate ─────────────────────────────────────────────────
    # Admin bypass: add ADMIN_EMAILS in secrets to skip subscription check
    _admin_emails = []
    try:
        _admin_emails = [e.strip().lower() for e in st.secrets.get("ADMIN_EMAILS", "").split(",") if e.strip()]
    except Exception:
        pass
    _user_email = st.session_state.get("user_email", "").lower()
    if _user_email and _user_email in _admin_emails:
        st.session_state["_sub_active"] = True
    else:
        # Revalidate periodically so long-lived sessions cannot keep stale access.
        _sub_check_ts = float(st.session_state.get("_sub_check_ts", 0) or 0)
        _sub_cached = st.session_state.get("_sub_check_result")
        if _sub_cached is None or (time.time() - _sub_check_ts) > 300:
            try:
                from database import has_active_subscription
                _sub_cached = has_active_subscription()
            except Exception:
                _sub_cached = True  # let through on transient check errors
            st.session_state["_sub_check_result"] = _sub_cached
            st.session_state["_sub_check_ts"] = time.time()

        st.session_state["_sub_active"] = bool(_sub_cached)
        if not _sub_cached:
            _subscription_page()
            st.stop()

    # Start background email thread only when scheduling is enabled.
    if EMAIL_SCHEDULER_ENABLED:
        _start_email_thread()

    # Show confirmation if we just synced a plan from the billing portal
    if st.session_state.get("_portal_synced_plan"):
        _synced_label = st.session_state.pop("_portal_synced_plan")
        st.toast(f"Subscription updated — you're now on the {_synced_label} plan.", icon="✅")

    # Check schedules only when scheduler is enabled.
    if EMAIL_SCHEDULER_ENABLED:
        _now = time.time()
        if _now - st.session_state.get("_last_email_check", 0) > 60:
            st.session_state["_last_email_check"] = _now
            try:
                _run_scheduled_reports_for_tenant(force_now=False)
            except Exception as _eml_err:
                _email_log(f"Page-render email check error: {_eml_err}")
                _log_app_error("email", f"Schedule check error: {_eml_err}", detail=traceback.format_exc())

    page = render_sidebar()
    _prev_page = str(st.session_state.get("_last_rendered_page_key", "") or "")
    st.session_state["_entered_from_page_key"] = _prev_page
    st.session_state["_last_rendered_page_key"] = page
    handlers = {
        "supervisor": page_supervisor,
        "dashboard": page_dashboard,
        "import": page_import,
        "employees": page_employees,
        "productivity": page_productivity,
        "email": page_email,
        "settings": page_settings,
    }
    handler = handlers.get(page, page_import)
    try:
        handler()
    except Exception as _page_err:
        _tb = traceback.format_exc()
        _log_app_error(
            "page",
            f"Page render failed ({page}): {_page_err}",
            detail=_tb,
            severity="error",
        )
        st.error("This page encountered an unexpected error.")
        with st.expander("Technical details"):
            st.code(_tb)


if __name__ == "__main__":
    try:
        main()
    except Exception as _fatal_err:
        _fatal_tb = traceback.format_exc()
        try:
            _log_app_error("fatal", f"Unhandled app error: {_fatal_err}", detail=_fatal_tb)
        except Exception:
            pass
        st.error("A fatal app error occurred. Please refresh or contact support.")
        with st.expander("Technical details"):
            st.code(_fatal_tb)
