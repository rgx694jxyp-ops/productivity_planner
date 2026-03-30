"""
app.py — Productivity Planner
Run with:   streamlit run app.py
"""

import io, os, sys, csv, json, tempfile, traceback, threading, time, html as _html_mod
from datetime import datetime, date
import pandas as pd

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Guard: show friendly error if supabase not installed ─────────────────────
try:
    from database import (
        get_clients, create_client_record, update_client, delete_client,
        get_employees, get_employee, upsert_employee, mark_employee_not_new,
        get_uph_history, get_avg_uph,
        add_coaching_note, get_coaching_notes, delete_coaching_note, archive_coaching_notes,
        create_shift, get_shifts,
        log_uploaded_file, get_active_uploaded_files, deactivate_uploaded_file,
        get_client as _get_db_client,
        batch_store_uph_history, get_all_uph_history,
        batch_upsert_employees,
    )
    from export_manager import (export_client, export_employee)
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

from data_loader import (REQUIRED_FIELDS,
                         auto_detect as _dl_auto_detect,
                         parse_csv_bytes as _dl_parse_csv)


# ── Cached DB reads — TTL of 30s means no DB call on every keystroke ─────────
# Only reading functions are cached. Writes always go direct to DB.
# Every cache includes _tid (tenant_id) so tenants never share cached data.

def _tid() -> str:
    return st.session_state.get("tenant_id", "")

@st.cache_data(ttl=120, show_spinner=False)
def _raw_cached_clients(_tid_key: str = ""):
    if not DB_AVAILABLE: return []
    try:
        result = get_clients()
        return result or []
    except Exception: return []

@st.cache_data(ttl=120, show_spinner=False)
def _raw_cached_employees(_tid_key: str = ""):
    if not DB_AVAILABLE: return []
    try:
        result = get_employees()
        return result or []
    except Exception: return []

@st.cache_data(ttl=300, show_spinner=False)
def _raw_cached_targets(_tid_key: str = "") -> dict:
    try:
        from goals import get_all_targets
        return get_all_targets()
    except Exception: return {}

@st.cache_data(ttl=60, show_spinner=False)
def _raw_cached_active_flags(_tid_key: str = "") -> dict:
    try:
        from goals import get_active_flags
        return get_active_flags()
    except Exception: return {}

@st.cache_data(ttl=60, show_spinner=False)
def _raw_cached_uph_history(_tid_key: str = ""):
    try: return get_all_uph_history(days=0)
    except Exception: return []

@st.cache_data(ttl=60, show_spinner=False)
def _raw_cached_all_coaching_notes(_tid_key: str = ""):
    try:
        from database import get_client as _get_sb, _tq
        sb = _get_sb()
        r  = _tq(sb.table("coaching_notes").select("emp_id").eq("archived", False)).execute()
        return {row["emp_id"] for row in (r.data or [])}
    except Exception:
        return set()

@st.cache_data(ttl=30, show_spinner=False)
def _raw_cached_coaching_notes_for(emp_id: str, _tid_key: str = "") -> list:
    try: return get_coaching_notes(emp_id)
    except Exception: return []

# ── Tenant-aware wrappers (call these everywhere) ────────────────────────────
def _cached_clients():          return _raw_cached_clients(_tid())
def _cached_employees():        return _raw_cached_employees(_tid())
def _cached_targets():          return _raw_cached_targets(_tid())
def _cached_active_flags():     return _raw_cached_active_flags(_tid())
def _cached_uph_history():      return _raw_cached_uph_history(_tid())
def _cached_all_coaching_notes(): return _raw_cached_all_coaching_notes(_tid())
def _cached_coaching_notes_for(emp_id: str): return _raw_cached_coaching_notes_for(emp_id, _tid())

def _full_sign_out():
    """Wipe ALL session state so the next user starts completely fresh."""
    _bust_cache()
    # Preserve only Streamlit internal keys (prefixed with _ from Streamlit itself)
    # Clear everything else — pipeline data, navigation, uploads, etc.
    keys_to_keep = set()  # nothing to keep
    for k in list(st.session_state.keys()):
        if k not in keys_to_keep:
            del st.session_state[k]


def _bust_cache():
    """Call after any write to force fresh data on next render."""
    _raw_cached_clients.clear()
    _raw_cached_employees.clear()
    _raw_cached_targets.clear()
    _raw_cached_uph_history.clear()
    _raw_cached_all_coaching_notes.clear()
    _raw_cached_active_flags.clear()
    _raw_cached_coaching_notes_for.clear()


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


# ── Background email scheduler ────────────────────────────────────────────────
# Runs in a daemon thread so emails fire at the scheduled time even when no
# user is actively viewing the app.  Uses st.cache_resource so the thread
# starts exactly once for the lifetime of the Streamlit process.

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


def _bg_send_scheduled_emails():
    """Called by the background thread every 60 s to fire due email schedules.
    Iterates over ALL tenants with email configs — no st.session_state needed."""
    try:
        from email_engine import get_schedules_due_now, send_report_email, mark_schedule_sent
        from settings    import Settings
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

        from datetime import date as _date, timedelta as _td
        from collections import defaultdict as _dc

        for tc in tenant_configs:
            tid = tc.get("tenant_id", "")
            scheds = tc.get("schedules") or []
            if not tid or not scheds:
                continue

            try:
                s  = Settings(tenant_id=tid)
                tz = s.get("timezone", "")
                due = get_schedules_due_now(timezone=tz, tenant_id=tid)
                if not due:
                    continue

                _email_log(f"[{tid[:8]}] Found {len(due)} schedule(s) due (tz={tz})")

                # Employee lookup for this tenant
                try:
                    er = sb.table("employees").select("emp_id, name, department").eq("tenant_id", tid).execute()
                    emps_lookup = {e["emp_id"]: e for e in (er.data or [])}
                except Exception:
                    emps_lookup = {}

                for sched in due:
                    try:
                        period  = sched.get("report_period", "Prior day")
                        send_to = sched.get("recipients", [])
                        if not send_to:
                            continue

                        today = _date.today()
                        if period == "Custom":
                            try:
                                d_start = _date.fromisoformat(sched.get("date_start", ""))
                                d_end   = _date.fromisoformat(sched.get("date_end", d_start.isoformat()))
                            except (ValueError, TypeError):
                                d_start = d_end = today - _td(days=1)
                        elif period == "Prior day":
                            d_start = d_end = today - _td(days=1)
                        elif period == "Current week":
                            d_start = today - _td(days=today.weekday())
                            d_end   = today
                        elif period == "Prior week":
                            d_end   = today - _td(days=today.weekday() + 1)
                            d_start = d_end - _td(days=6)
                        elif period == "Prior month":
                            first_of_this = today.replace(day=1)
                            d_end   = first_of_this - _td(days=1)
                            d_start = d_end.replace(day=1)
                        else:
                            d_start = d_end = today - _td(days=1)

                        # Fetch UPH history filtered by THIS tenant and date range
                        _r = sb.table("uph_history").select(
                            "emp_id, units, hours_worked, uph, work_date, department"
                        ).eq("tenant_id", tid).gte(
                            "work_date", d_start.isoformat()
                        ).lte("work_date", d_end.isoformat()).execute()
                        subs = _r.data or []

                        if not subs:
                            body = (f"<h2>Performance Report — {d_start} – {d_end}</h2>"
                                    f"<p>No work data found for this period.</p>")
                            send_report_email(send_to, f"Performance Report — {d_start}", body,
                                              tenant_id=tid)
                            mark_schedule_sent(sched["name"], timezone=tz, tenant_id=tid)
                            continue

                        emp_agg = _dc(lambda: {"units": 0.0, "hours": 0.0})
                        for sub in subs:
                            eid = sub.get("emp_id", "")
                            emp_agg[eid]["units"] += float(sub.get("units") or 0)
                            emp_agg[eid]["hours"] += float(sub.get("hours_worked") or 0)

                        rows_html = ""
                        for eid, agg in sorted(emp_agg.items(),
                                               key=lambda x: x[1]["units"] / max(x[1]["hours"], 0.01),
                                               reverse=True):
                            uph  = round(agg["units"] / agg["hours"], 2) if agg["hours"] > 0 else 0
                            name = emps_lookup.get(eid, {}).get("name", eid)
                            dept = emps_lookup.get(eid, {}).get("department", "")
                            rows_html += (
                                f"<tr><td style='padding:5px 10px;'>{name}</td>"
                                f"<td style='padding:5px 10px;'>{dept}</td>"
                                f"<td style='padding:5px 10px;text-align:right;'>{agg['units']:,.0f}</td>"
                                f"<td style='padding:5px 10px;text-align:right;font-weight:bold;'>{uph:.2f}</td></tr>"
                            )
                        label = d_start.isoformat() if d_start == d_end else f"{d_start} – {d_end}"
                        body  = (
                            f"<html><body style='font-family:Arial,sans-serif;color:#333;max-width:700px;'>"
                            f"<div style='background:#0F2D52;padding:20px;border-radius:6px 6px 0 0;'>"
                            f"<h2 style='color:#fff;margin:0;'>📊 Performance Report</h2>"
                            f"<p style='color:#BDD7EE;margin:4px 0 0;font-size:13px;'>{label}</p></div>"
                            f"<table style='width:100%;border-collapse:collapse;font-size:13px;margin-top:0;'>"
                            f"<tr style='background:#f0f4f8;'>"
                            f"<th style='padding:8px 10px;text-align:left;'>Employee</th>"
                            f"<th style='padding:8px 10px;text-align:left;'>Dept</th>"
                            f"<th style='padding:8px 10px;text-align:right;'>Units</th>"
                            f"<th style='padding:8px 10px;text-align:right;'>UPH</th></tr>"
                            f"{rows_html}"
                            f"</table></body></html>"
                        )
                        ok, err = send_report_email(send_to, f"Performance Report — {label}", body,
                                                    tenant_id=tid)
                        if ok:
                            mark_schedule_sent(sched["name"], timezone=tz, tenant_id=tid)
                            _email_log(f"[{tid[:8]}] SENT '{sched.get('name')}' to {send_to}")
                        else:
                            _email_log(f"[{tid[:8]}] FAILED '{sched.get('name')}': {err}")
                            try:
                                from database import log_error
                                log_error("email", f"Scheduled send failed: {sched.get('name')}: {err}",
                                          severity="error", tenant_id=tid)
                            except Exception:
                                pass
                    except Exception as _se:
                        _email_log(f"[{tid[:8]}] ERROR in '{sched.get('name','?')}': {_se}")
                        try:
                            from database import log_error
                            log_error("email", f"Schedule error: {sched.get('name','?')}: {_se}",
                                      detail=str(_se), severity="error", tenant_id=tid)
                        except Exception:
                            pass
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

st.html("""<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* ── Global font ── */
  html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif !important; }

  /* ── Hide Streamlit chrome ── */
  #MainMenu, footer,
  [data-testid="stDecoration"], [data-testid="stStatusWidget"] { visibility: hidden !important; display: none !important; }
  /* Keep header visible so the sidebar toggle button works */
  header[data-testid="stHeader"] { background: transparent !important; }

  /* ── Page background ── */
  .stApp { background: #F7F9FC !important; }
  .main .block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1200px; }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] { background: #0F2D52 !important; border-right: none !important; }
  [data-testid="stSidebar"] > div { background: #0F2D52 !important; }
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] div { color: #CBD8E8 !important; }
  [data-testid="stSidebar"] .stRadio label { font-size: 13px !important; padding: 6px 0 !important; font-weight: 500 !important; }
  [data-testid="stSidebar"] hr { border-color: #1A4A8A !important; opacity: 0.6; }

  /* ── Headings ── */
  h1 { color: #0F2D52 !important; font-weight: 600 !important; font-size: 1.6rem !important; letter-spacing: -0.02em; }
  h2 { color: #0F2D52 !important; font-weight: 600 !important; }
  h3 { color: #1A4A8A !important; font-weight: 500 !important; }
  /* Subheader (used heavily in the app) */
  [data-testid="stHeading"] { color: #0F2D52 !important; }

  /* ── Body text — force dark readable colour everywhere outside sidebar ── */
  .main p, .main span, .main label, .main div,
  .block-container p, .block-container span, .block-container label {
    color: #1A2D42;
  }
  .main .stCaption, .main small, .main caption { color: #5A7A9C !important; }

  /* ── Buttons — covers both st.button and st.form_submit_button ── */
  .stButton > button,
  [data-testid="stFormSubmitButton"] > button {
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    transition: background 0.15s, color 0.15s;
  }
  /* ── ALL buttons: force readable text regardless of Streamlit version ── */
  /* Targets every possible button selector Streamlit uses */
  .stButton > button,
  [data-testid="stFormSubmitButton"] > button,
  [data-testid="stBaseButton-primary"],
  [data-testid="stBaseButton-secondary"] {
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    transition: background 0.15s, color 0.15s;
  }

  /* Primary: navy bg, ALWAYS white text */
  .stButton > button[kind="primary"],
  [data-testid="stFormSubmitButton"] > button,
  [data-testid="stFormSubmitButton"] > button[kind="primary"],
  button[data-testid="stBaseButton-primary"] {
    background-color: #0F2D52 !important;
    color: #ffffff !important;
    border: none !important;
  }
  .stButton > button[kind="primary"]:hover,
  [data-testid="stFormSubmitButton"] > button:hover,
  button[data-testid="stBaseButton-primary"]:hover {
    background-color: #1A4A8A !important;
    color: #ffffff !important;
  }
  /* Force white on the inner p/span inside primary buttons */
  .stButton > button[kind="primary"] p,
  .stButton > button[kind="primary"] span,
  [data-testid="stFormSubmitButton"] > button p,
  [data-testid="stFormSubmitButton"] > button span,
  button[data-testid="stBaseButton-primary"] p,
  button[data-testid="stBaseButton-primary"] span {
    color: #ffffff !important;
  }

  /* Secondary: white bg, navy text */
  .stButton > button[kind="secondary"],
  .stButton > button:not([kind="primary"]),
  button[data-testid="stBaseButton-secondary"] {
    background-color: #ffffff !important;
    color: #0F2D52 !important;
    border: 1px solid #C5D4E8 !important;
  }
  .stButton > button[kind="secondary"]:hover,
  .stButton > button:not([kind="primary"]):hover,
  button[data-testid="stBaseButton-secondary"]:hover {
    background-color: #E8F0F9 !important;
    color: #0F2D52 !important;
    border-color: #1A4A8A !important;
  }
  .stButton > button:not([kind="primary"]) p,
  .stButton > button:not([kind="primary"]) span,
  button[data-testid="stBaseButton-secondary"] p,
  button[data-testid="stBaseButton-secondary"] span {
    color: #0F2D52 !important;
  }

  /* ── Tabs ── */
  .stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid #E2EBF4 !important; gap: 2px; }
  .stTabs [data-baseweb="tab"] {
    font-size: 12px !important; font-weight: 500 !important;
    color: #5A7A9C !important; padding: 7px 14px !important;
    border-radius: 4px 4px 0 0 !important; background: transparent !important;
  }
  .stTabs [aria-selected="true"] {
    color: #0F2D52 !important; border-bottom: 2px solid #0F2D52 !important;
    background: transparent !important;
  }

  /* ── Metrics ── */
  [data-testid="stMetric"] { background: #ffffff; border: 1px solid #E2EBF4; border-radius: 8px; padding: 14px 18px; }
  [data-testid="stMetricLabel"] > div { font-size: 11px !important; font-weight: 600 !important; color: #5A7A9C !important; text-transform: uppercase; letter-spacing: 0.05em; }
  [data-testid="stMetricValue"] > div { font-size: 26px !important; font-weight: 600 !important; color: #0F2D52 !important; }
  [data-testid="stMetricDelta"] { font-size: 12px !important; }

  /* ── Alert / notification boxes ── */
  /* SUCCESS — green background, dark green text */
  [data-testid="stAlert"][data-baseweb="notification"][kind="positive"],
  div.stSuccess, div.element-container div.stAlert.stSuccess,
  [data-testid="stNotification"][kind="success"] {
    background-color: #EAF4EC !important;
    border-left: 4px solid #2E7D32 !important;
    border-radius: 0 8px 8px 0 !important;
  }
  div.stSuccess *, div.stSuccess p, div.stSuccess span,
  [data-testid="stAlert"][data-baseweb="notification"][kind="positive"] *,
  [data-testid="stAlert"][data-baseweb="notification"][kind="positive"] p { color: #1B5E20 !important; }

  /* WARNING — pale orange background, dark orange text — NO yellow-on-yellow */
  [data-testid="stAlert"][data-baseweb="notification"][kind="warning"],
  div.stWarning, div.element-container div.stAlert.stWarning,
  [data-testid="stNotification"][kind="warning"] {
    background-color: #FFF3E0 !important;
    border-left: 4px solid #E65100 !important;
    border-radius: 0 8px 8px 0 !important;
  }
  div.stWarning *, div.stWarning p, div.stWarning span,
  [data-testid="stAlert"][data-baseweb="notification"][kind="warning"] *,
  [data-testid="stAlert"][data-baseweb="notification"][kind="warning"] p { color: #BF360C !important; }

  /* ERROR — pale red background, dark red text */
  [data-testid="stAlert"][data-baseweb="notification"][kind="error"],
  div.stError, div.element-container div.stAlert.stError,
  [data-testid="stNotification"][kind="error"] {
    background-color: #FDECEA !important;
    border-left: 4px solid #C62828 !important;
    border-radius: 0 8px 8px 0 !important;
  }
  div.stError *, div.stError p, div.stError span,
  [data-testid="stAlert"][data-baseweb="notification"][kind="error"] *,
  [data-testid="stAlert"][data-baseweb="notification"][kind="error"] p { color: #7F0000 !important; }

  /* INFO — pale blue background, dark navy text */
  [data-testid="stAlert"][data-baseweb="notification"][kind="info"],
  div.stInfo, div.element-container div.stAlert.stInfo,
  [data-testid="stNotification"][kind="info"] {
    background-color: #E8F0F9 !important;
    border-left: 4px solid #0F2D52 !important;
    border-radius: 0 8px 8px 0 !important;
  }
  div.stInfo *, div.stInfo p, div.stInfo span,
  [data-testid="stAlert"][data-baseweb="notification"][kind="info"] *,
  [data-testid="stAlert"][data-baseweb="notification"][kind="info"] p { color: #0D2440 !important; }

  /* Broad fallback: any alert icon or text should never be invisible */
  [data-testid="stAlert"] svg { opacity: 0.8; }

  /* ── Inputs — white background, dark text, no yellow tint ── */
  .stTextInput input, .stTextInput textarea,
  .stNumberInput input,
  .stTextArea textarea {
    background: #ffffff !important;
    color: #1A2D42 !important;
    border: 1px solid #C5D4E8 !important;
    border-radius: 6px !important;
  }
  .stTextInput input::placeholder,
  .stTextArea textarea::placeholder { color: #8AAAC4 !important; }
  .stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
    border-color: #1A4A8A !important;
    box-shadow: 0 0 0 2px rgba(26,74,138,0.12) !important;
    caret-color: #0F2D52 !important;
  }
  .stTextInput input, .stNumberInput input {
    caret-color: #0F2D52 !important;
  }

  /* ── Selectbox ── */
  [data-baseweb="select"] > div {
    background: #ffffff !important;
    border-color: #C5D4E8 !important;
    border-radius: 6px !important;
    color: #1A2D42 !important;
  }
  [data-baseweb="select"] span { color: #1A2D42 !important; }
  [data-baseweb="popover"] { background: #ffffff !important; }
  [data-baseweb="menu"] li { color: #1A2D42 !important; background: #ffffff !important; }
  [data-baseweb="menu"] li:hover { background: #E8F0F9 !important; }

  /* ── Radio buttons ── */
  .stRadio > label { color: #1A2D42 !important; }
  .stRadio [data-baseweb="radio"] span { color: #1A2D42 !important; }

  /* ── Checkbox / Toggle ── */
  .stCheckbox label, .stToggle label { color: #1A2D42 !important; }

  /* ── Slider ── */
  .stSlider label { color: #1A2D42 !important; }
  .stSlider [data-baseweb="slider"] [role="slider"] { background: #0F2D52 !important; }

  /* ── Number input label ── */
  .stNumberInput label { color: #1A2D42 !important; }

  /* ── Expander ── */
  [data-testid="stExpander"] {
    border: 1px solid #E2EBF4 !important;
    border-radius: 8px !important;
    background: #ffffff !important;
  }
  /* Collapsed header */
  [data-testid="stExpander"] summary,
  [data-testid="stExpander"] summary span,
  [data-testid="stExpander"] summary p { color: #0F2D52 !important; font-weight: 500 !important; }
  [data-testid="stExpander"] summary:hover { background: #F0F5FB !important; }
  /* Hover on open expander: keep light blue bg but force text BLACK (not white) */
  [data-testid="stExpander"][open] summary:hover,
  [data-testid="stExpander"][open] summary:hover *,
  [data-testid="stExpander"][open] summary:hover span,
  [data-testid="stExpander"][open] summary:hover p,
  [data-testid="stExpander"][open] summary:hover strong,
  [data-testid="stExpander"][open] summary:hover b { color: #0F2D52 !important; }
  details[open] > summary:hover,
  details[open] > summary:hover * { color: #0F2D52 !important; }
  /* Open state — header row goes dark blue; force its text white */
  [data-testid="stExpander"][open] summary,
  [data-testid="stExpander"][open] summary span,
  [data-testid="stExpander"][open] summary p,
  [data-testid="stExpander"][open] summary strong,
  [data-testid="stExpander"][open] summary b,
  [data-testid="stExpander"][open] summary *,
  details[open] > summary,
  details[open] > summary * { color: #ffffff !important; }
  /* ALL content inside expanders — always dark readable text */
  [data-testid="stExpander"] p,
  [data-testid="stExpander"] span,
  [data-testid="stExpander"] td,
  [data-testid="stExpander"] th,
  [data-testid="stExpander"] li,
  [data-testid="stExpander"] code,
  [data-testid="stExpander"] .stMarkdown p,
  [data-testid="stExpander"] .stMarkdown span { color: #1A2D42 !important; }
  /* Markdown tables inside expanders */
  [data-testid="stExpander"] table td,
  [data-testid="stExpander"] table th { color: #1A2D42 !important; background: transparent !important; }

  /* ── File uploader ── */
  [data-testid="stFileUploader"] {
    background: #ffffff !important;
    border: 2px dashed #C5D4E8 !important;
    border-radius: 8px !important;
  }
  [data-testid="stFileUploader"] span,
  [data-testid="stFileUploader"] p,
  [data-testid="stFileUploader"] small,
  [data-testid="stFileUploader"] div { color: #1A2D42 !important; }
  [data-testid="stFileUploaderDropzoneInstructions"],
  [data-testid="stFileUploaderDropzoneInstructions"] * { color: #5A7A9C !important; }
  /* Dropzone instruction text — "Drag and drop files here · Limit 200MB" */
  [data-testid="stFileUploaderDropzone"],
  [data-testid="stFileUploaderDropzone"] small,
  [data-testid="stFileUploaderDropzone"] span,
  [data-testid="stFileUploaderDropzone"] p,
  [data-testid="stFileUploaderDropzone"] div,
  [data-testid="stFileUploaderDropzone"] label,
  [data-testid="stFileUploaderDropzone"] button span { color: #5A7A9C !important; }
  /* The specific "Drag and drop" + "Limit" lines use these internal classes */
  .stFileUploaderDropzone span { color: #5A7A9C !important; }
  [data-baseweb="file-uploader"] span,
  [data-baseweb="file-uploader"] p,
  [data-baseweb="file-uploader"] small { color: #5A7A9C !important; }
  /* Uploaded file list — filename and size text */
  [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"],
  [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] span,
  [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] p,
  [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] small { color: #0F2D52 !important; }
  /* The file name specifically */
  [data-testid="stFileUploaderFileName"] { color: #0F2D52 !important; font-weight: 500 !important; }
  [data-testid="stFileUploaderFileSize"] { color: #5A7A9C !important; }
  /* Catch-all: any text inside the uploader that might go white */
  section[data-testid="stFileUploader"] * { color: #1A2D42 !important; }
  section[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] * { color: #5A7A9C !important; }

  /* ── Dataframe ── */
  [data-testid="stDataFrame"] { border: 1px solid #E2EBF4 !important; border-radius: 8px !important; }

  /* ── Progress bar ── */
  .stProgress > div > div { background: #0F2D52 !important; border-radius: 4px; }
  /* Progress bar status text */
  [data-testid="stProgress"] p,
  [data-testid="stProgress"] span,
  .stProgress p,
  .stProgress span,
  .stProgress ~ div p,
  .stProgress ~ div span { color: #ffffff !important; }
  /* The text label that sits above/below the bar */
  [data-testid="stProgressBar"] + div,
  [data-testid="stProgressBar"] + div p,
  [data-testid="stProgressBar"] + div span { color: #ffffff !important; }

  /* ── Date input ── */
  .stDateInput input { background: #ffffff !important; color: #1A2D42 !important; border: 1px solid #C5D4E8 !important; border-radius: 6px !important; }
  .stDateInput label { color: #1A2D42 !important; }

  /* ── Divider ── */
  hr { border-color: #E2EBF4 !important; }

  /* ── Caption text everywhere outside sidebar ── */
  .main .stCaption p { color: #5A7A9C !important; }

  /* ── Multiselect ── */
  [data-baseweb="tag"] { background: #E8F0F9 !important; }
  [data-baseweb="tag"] span { color: #0F2D52 !important; }

  /* ── Time input ── */
  .stTimeInput input { background: #ffffff !important; color: #1A2D42 !important; }
</style>
""")


# ── Session state ─────────────────────────────────────────────────────────────

def _init():
    defaults = {
        "uploaded_sessions":  [],   # list of {filename, rows, mapping, timestamp}
        "submission_plan":    None, # pending plan awaiting confirmation
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
    # Check cached plan
    if st.session_state.get("_current_plan"):
        return st.session_state["_current_plan"]
    try:
        from database import get_subscription
        sub = get_subscription()
        plan = sub.get("plan", "starter") if sub else "starter"
        st.session_state["_current_plan"] = plan
        return plan
    except Exception:
        return "starter"


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

        # Build nav based on plan
        NAV_OPTS = [
            "📁  Import Data",
            "👥  Employees",
            "📈  Productivity",
        ]
        # Pro+ gets email setup
        if _plan in ("pro", "business", "admin"):
            NAV_OPTS.append("📧  Email Setup")
        NAV_OPTS.append("⚙️  Settings")
        # Allow programmatic navigation via st.session_state.goto_page
        goto = st.session_state.pop("goto_page", None)
        if goto and goto in NAV_OPTS:
            st.session_state["_current_page"] = goto
        # Persist the last-selected page so it survives reruns
        current = st.session_state.get("_current_page", NAV_OPTS[0])
        default_idx = NAV_OPTS.index(current) if current in NAV_OPTS else 0
        page = st.radio("Navigation", NAV_OPTS,
                        index=default_idx,
                        label_visibility="collapsed")
        st.session_state["_current_page"] = page

        st.divider()
        if st.button("↺ Refresh data", use_container_width=True, key="sb_refresh"):
            _bust_cache()
            st.rerun()

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
            _emp_count = get_employee_count()
            _emp_limit = get_employee_limit()
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
        if st.button("Sign out", use_container_width=True, key="sb_signout"):
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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: IMPORT & SUBMIT
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: IMPORT DATA
# Clean 3-step flow. Each step only runs when active — no tab lag.
# Step 1: Upload CSV(s)
# Step 2: Map columns (per file, auto-detected)
# Step 3: Run pipeline — employees registered, UPH calculated, data ready
# ══════════════════════════════════════════════════════════════════════════════

def page_import():
    st.title("📁 Import Data")

    if not require_db(): return

    step = st.session_state.import_step

    # ── Reset button — shown whenever something is in progress ───────────────
    if (step > 1 or st.session_state.get("uploaded_sessions") or
            st.session_state.get("alloc_rows") or st.session_state.pipeline_done):
        if st.button("↺ Start over", key="import_reset", type="secondary"):
            keys_to_clear = [
                "uploaded_sessions", "import_step", "alloc_rows",
                "pipeline_done", "top_performers", "goal_status", "dept_report",
                "dept_trends", "weekly_summary", "history", "mapping",
                "_archived_loaded",
            ]
            for k in keys_to_clear:
                st.session_state.pop(k, None)
            # Clear all au_ / ao_ / snap_ widget keys
            for k in list(st.session_state.keys()):
                if k.startswith(("au_", "ao_", "snap_", "alloc_sel_")):
                    del st.session_state[k]
            st.session_state.import_step = 1
            _bust_cache()
            st.rerun()

    # ── Step indicator ────────────────────────────────────────────────────────
    s1c = "#0F2D52" if step >= 1 else "#C5D4E8"
    s2c = "#2E7D32" if step >= 3 else ("#0F2D52" if step >= 2 else "#C5D4E8")
    st.markdown(f"""
<div style="display:flex;gap:8px;align-items:center;margin-bottom:1.5rem;">
  <div style="background:{s1c};color:#fff;border-radius:50%;width:28px;height:28px;
              display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;">1</div>
  <span style="color:{s1c};font-size:13px;font-weight:500;">Upload</span>
  <span style="color:#C5D4E8;margin:0 4px;">──────</span>
  <div style="background:{s2c};color:#fff;border-radius:50%;width:28px;height:28px;
              display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;">2</div>
  <span style="color:{s2c};font-size:13px;font-weight:500;">Process</span>
</div>""", unsafe_allow_html=True)

    if step == 1:
        _import_step1()
    elif step == 2:
        _import_step2()
    elif step == 3:
        _import_step3()


def _import_step1():
    """Step 1 — upload one or more CSV files."""
    st.subheader("Upload your CSV file(s)")
    st.caption("Upload one or more CSV files. Columns are auto-detected — you'll only see the mapping step if we can't find required fields.")

    files = st.file_uploader(
        "Drag files here or click Browse",
        type=["csv"],
        accept_multiple_files=True,
        key="import_uploader",
    )

    if not files:
        st.info("Waiting for files…")
        return

    _MAX_FILE_MB = 50
    pending = []
    for f in files:
        # ── File size guard ───────────────────────────────────────────
        f.seek(0, 2)
        size_mb = f.tell() / (1024 * 1024)
        f.seek(0)
        if size_mb > _MAX_FILE_MB:
            st.error(f"**{f.name}** is {size_mb:.1f} MB — max allowed is {_MAX_FILE_MB} MB. Split into smaller files.")
            continue

        try:
            raw_bytes = f.read()
        except Exception as _read_err:
            st.error(f"Could not read **{f.name}**: {_read_err}")
            _log_app_error("import", f"File read error ({f.name}): {_read_err}")
            continue

        rows, headers = _parse_csv(raw_bytes)
        if not rows:
            st.error(f"Could not parse **{f.name}** — check that it's a valid CSV with column headers.")
            continue
        if not headers:
            st.error(f"**{f.name}** has no column headers. Make sure the first row contains column names.")
            continue
        pending.append({
            "filename":  f.name,
            "rows":      rows,
            "headers":   headers,
            "row_count": len(rows),
        })
        st.success(f"✓ **{f.name}** — {len(rows):,} rows, {len(headers)} columns")

    if pending:
        if st.button("Continue →", type="primary", use_container_width=True):
            sessions = [
                {**p, "mapping": {}, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")}
                for p in pending
            ]
            # Auto-detect columns for each file
            all_auto = True
            for s in sessions:
                headers = s.get("headers", list(s.get("rows",[{}])[0].keys()) if s.get("rows") else [])
                auto = _auto_detect(headers)
                has_id   = bool(auto.get("EmployeeID"))
                has_name = bool(auto.get("EmployeeName"))
                has_uph  = bool(auto.get("UPH")) or (bool(auto.get("Units")) and bool(auto.get("HoursWorked")))
                if has_id and has_name and has_uph:
                    s["mapping"] = {
                        "Date":        auto.get("Date", ""),
                        "EmployeeID":  auto.get("EmployeeID", ""),
                        "EmployeeName":auto.get("EmployeeName", ""),
                        "Department":  auto.get("Department", ""),
                        "Shift":       auto.get("Shift", ""),
                        "UPH":         auto.get("UPH", ""),
                        "Units":       auto.get("Units", ""),
                        "HoursWorked": auto.get("HoursWorked", ""),
                    }
                else:
                    all_auto = False

            st.session_state.uploaded_sessions = sessions
            st.session_state.submission_plan  = None
            st.session_state.split_overrides  = {}
            if all_auto:
                # Skip mapping — go straight to pipeline
                st.session_state.import_step = 3
            else:
                st.session_state.import_step = 2
            st.rerun()


def _import_step2():
    """Step 2 — map columns for each file."""
    sessions = st.session_state.uploaded_sessions
    if not sessions:
        st.session_state.import_step = 1
        st.rerun()
        return

    st.subheader("Map your columns")
    st.caption("We've auto-detected the best match for each field. Check them and adjust anything that looks wrong.")

    all_mapped = True

    for idx, s in enumerate(sessions):
        headers = s.get("headers", list(s.get("rows",[{}])[0].keys()) if s.get("rows") else [])
        auto    = _auto_detect(headers)
        options = ["— not in this file —"] + headers

        with st.container():
            _safe_fn = _html_mod.escape(s["filename"])
            st.markdown(
                f'<div style="background:#F0F5FB;border-radius:8px;padding:14px 16px;margin-bottom:8px;">'
                f'<span style="font-size:14px;font-weight:600;color:#0F2D52;">{_safe_fn}</span>'
                f'<span style="font-size:12px;color:#5A7A9C;margin-left:12px;">{s["row_count"]:,} rows</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            with st.form(f"mapping_form_{idx}"):
                ca, cb = st.columns(2)
                m = s.get("mapping") or {}

                def _sel(label, field, req, col, extra=""):
                    cur = m.get(field) or auto.get(field, "")
                    idx2 = options.index(cur) if cur in options else 0
                    dot  = "🔴" if req else "⚪"
                    v    = col.selectbox(f"{dot} {label}", options, index=idx2,
                                         key=f"fm_{idx}_{field}_{extra}")
                    return "" if v.startswith("—") else v

                with ca:
                    d_date = _sel("Date (optional — use work date picker if absent)",
                                  "Date",         False, ca)
                    d_eid  = _sel("Employee ID",  "EmployeeID",   True,  ca)
                    d_name = _sel("Employee Name","EmployeeName", True,  ca)
                    d_dept = _sel("Department",   "Department",   False, ca)

                with cb:
                    d_shift = _sel("Shift",                    "Shift",       False, cb)

                    # Read saved radio choice so it persists across rerenders
                    uph_src_key = f"uph_src_{idx}"
                    saved_src   = st.session_state.get(uph_src_key, "Calculate: Units ÷ Hours")
                    uph_src     = cb.radio(
                        "UPH source",
                        ["Calculate: Units ÷ Hours", "Already have UPH column"],
                        index=1 if "Already" in saved_src else 0,
                        key=uph_src_key,
                    )

                    if "Already" in uph_src:
                        d_uph   = _sel("UPH column",   "UPH",         True,  cb, "u")
                        d_units = ""
                        d_hrs   = ""
                    else:
                        d_uph   = ""
                        d_units = _sel("Units",        "Units",       True,  cb, "un")
                        d_hrs   = _sel("Hours Worked", "HoursWorked", True,  cb, "h")

                # Validation — Date is optional (falls back to work date picker)
                missing = [
                    f for f, v in [
                        ("Employee ID", d_eid),
                        ("Employee Name", d_name),
                    ] if not v
                ]

                if "Already" in uph_src:
                    uph_ok = bool(d_uph)
                    if not uph_ok:
                        uph_msg = "Select your UPH column above."
                    else:
                        uph_msg = ""
                else:
                    uph_ok = bool(d_units and d_hrs)
                    if not d_units and not d_hrs:
                        uph_msg = "Select both Units and Hours Worked columns."
                    elif not d_units:
                        uph_msg = "Select the Units column."
                    elif not d_hrs:
                        uph_msg = "Select the Hours Worked column."
                    else:
                        uph_msg = ""

                can_confirm = not missing and uph_ok

                if missing:
                    st.warning(f"Still needed: {', '.join(missing)}")
                if uph_msg:
                    st.warning(uph_msg)
                # Auto-confirm if all fields detected with no conflicts
                _auto_confirmed = (can_confirm and
                                   not s.get("mapping") and
                                   all(auto.get(f) for f in ["EmployeeID","EmployeeName","Units"]) and
                                   len([v for v in auto.values() if v]) >= 4)
                if _auto_confirmed:
                    sessions[idx]["mapping"] = {
                        "Date": d_date, "EmployeeID": d_eid, "EmployeeName": d_name,
                        "Department": d_dept, "Shift": d_shift,
                        "UPH": d_uph, "Units": d_units, "HoursWorked": d_hrs,
                    }
                    st.session_state.uploaded_sessions = sessions
                    st.success(f"✓ Auto-confirmed: {s['filename']}")
                    st.rerun()

                if can_confirm and not _auto_confirmed:
                    st.info("✓ All fields mapped — ready to confirm.")

                confirmed = st.form_submit_button(
                    f"Confirm mapping for {s['filename']}",
                    type="primary",
                    use_container_width=True,
                    disabled=_auto_confirmed,
                )

                if confirmed:
                    if not can_confirm:
                        st.warning("Fix the issues above before confirming.")
                    else:
                        sessions[idx]["mapping"] = {
                            "Date":        d_date,
                            "EmployeeID":  d_eid,
                            "EmployeeName":d_name,
                            "Department":  d_dept,
                            "Shift":       d_shift,
                            "UPH":         d_uph,
                            "Units":       d_units,
                            "HoursWorked": d_hrs,
                        }
                        st.session_state.uploaded_sessions = sessions
                        st.rerun()

            # Show confirmation tick if mapping saved
            if s.get("mapping") and s["mapping"].get("EmployeeID"):
                st.success(f"✓ Mapping confirmed for {s['filename']}")
            else:
                all_mapped = False

    st.divider()
    col1, col2 = st.columns(2)

    if col1.button("← Back to upload", use_container_width=True):
        st.session_state.import_step = 1
        st.rerun()

    if all_mapped:
        if col2.button("Continue to pipeline →", type="primary", use_container_width=True):
            st.session_state.import_step = 3
            st.rerun()
    else:
        col2.info("Confirm all file mappings above to continue.")


def _import_step3():
    """Step 3 — run the pipeline. Registers employees, calculates UPH, stores history."""
    sessions = st.session_state.uploaded_sessions
    if not sessions:
        st.session_state.import_step = 1
        st.rerun()
        return

    st.subheader("Run the pipeline")

    # Summary of what's loaded
    total_rows = sum(s["row_count"] for s in sessions)
    st.markdown(
        f'<div style="background:#E8F0F9;border-radius:8px;padding:14px 16px;margin-bottom:1rem;">'
        f'<span style="color:#0F2D52;font-weight:600;">{len(sessions)} file(s) ready</span>'
        f'<span style="color:#5A7A9C;font-size:12px;margin-left:12px;">{total_rows:,} total rows</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    for s in sessions:
        m = s.get("mapping",{})
        st.caption(f"📄 **{s['filename']}** — {s['row_count']:,} rows · mapped to {sum(1 for v in m.values() if v)} fields")

    st.divider()

    # Check if any session has a Date column mapped
    _has_date_col = any(s.get("mapping",{}).get("Date") for s in sessions)

    if _has_date_col:
        st.info("📅 Date column detected — work dates come from your CSV. No date picker needed.")
        work_date = date.today()   # placeholder only; rows use their own date
    else:
        st.markdown("**Work date for this import**")
        st.caption("Your CSV has no Date column mapped — all rows will be recorded under this date.")
        work_date = st.date_input("Work date", value=date.today(), label_visibility="collapsed")

    if st.button("▶  Run pipeline now", type="primary", use_container_width=True):
        all_rows    = []
        all_mapping = {}
        for s in sessions:
            all_rows.extend(s["rows"])
            if not all_mapping and s.get("mapping"):
                all_mapping = s["mapping"]

        bar = st.progress(0, text="Registering employees…")

        # Register all employees — one batch upsert instead of N individual calls
        id_col    = all_mapping.get("EmployeeID","EmployeeID")
        name_col  = all_mapping.get("EmployeeName","EmployeeName")
        dept_col  = all_mapping.get("Department","Department")
        shift_col = all_mapping.get("Shift","Shift")
        seen_emps = {}
        for row in all_rows:
            eid = str(row.get(id_col,"")).strip()
            if eid and eid not in seen_emps:
                seen_emps[eid] = {
                    "emp_id":     eid,
                    "name":       str(row.get(name_col,"")).strip(),
                    "department": str(row.get(dept_col,"")).strip(),
                    "shift":      str(row.get(shift_col,"")).strip(),
                }
        if seen_emps:
            # Check employee limit before importing
            try:
                from database import can_add_employees, get_employee_count, get_employee_limit
                _el = get_employee_limit()
                if _el != -1:  # not unlimited
                    _existing = get_employee_count()
                    _new_unique = len(seen_emps)
                    if _existing + _new_unique > _el and _el > 0:
                        _plan = _get_current_plan()
                        st.error(
                            f"Employee limit reached. Your **{_plan.capitalize()}** plan allows "
                            f"**{_el}** employees and you have **{_existing}**. "
                            f"This import has **{_new_unique}** unique employees. "
                            f"Upgrade your plan in Settings → Subscription."
                        )
            except Exception:
                pass  # don't block import if limit check fails
            try:
                batch_upsert_employees(list(seen_emps.values()))
            except Exception as _e:
                st.warning(f"Employee sync warning: {_e} — allocation will continue.")
                _log_app_error("pipeline", f"Employee sync error: {_e}", detail=traceback.format_exc(), severity="warning")
            _bust_cache()

        bar.progress(25, text="Processing rows…")

        # Run productivity pipeline
        try:
            from data_processor import process_data
            from ranker         import rank_employees, build_department_report
            from trends         import calculate_department_trends, build_weekly_summary
            from error_log      import ErrorLog
            from goals          import analyse_trends, build_goal_status, get_all_targets

            class _PS:
                def get(self, k, d=None): return st.session_state.get(k, d)
                def get_output_dir(self): return tempfile.gettempdir()
                def get_dept_target_uph(self, d):
                    t = _cached_targets().get(d, 0)
                    return float(t) if t else float(st.session_state.get("target_uph",0) or 0)
                def all_mappings(self): return all_mapping

            ps  = _PS()
            log = ErrorLog(tempfile.gettempdir())

            processed = process_data(all_rows, all_mapping, ps, log)
            bar.progress(40, text="Ranking employees…")

            existing = st.session_state.history
            existing.extend(processed)
            st.session_state.history = existing

            ranked = rank_employees(existing, all_mapping, ps, log)
            bar.progress(60, text="Calculating goals…")

            targets     = _cached_targets()
            trend_data  = analyse_trends(existing, all_mapping, weeks=st.session_state.trend_weeks)
            goal_status = build_goal_status(ranked, targets, trend_data)
            dept_report = build_department_report(ranked, ps, log)
            dept_trends = calculate_department_trends(existing, all_mapping, ps, log)
            weekly      = build_weekly_summary(existing, all_mapping, ps, log)

            bar.progress(85, text="Storing UPH history…")

            # Aggregate per employee — handle multiple files with different column names
            # Aggregate per (emp_id, order_number, date) so that:
            # - employees who worked on multiple orders get pre-split rows
            # - employees who worked across multiple dates get per-date rows
            # - if no order/date columns are mapped we fall back to one row per emp
            from collections import defaultdict

            # key = (emp_id, order_number_or_"", date_str)
            combo_agg = defaultdict(lambda: {
                "units": 0.0, "hours": 0.0, "uphs": [], "dept": "", "name": ""
            })

            # Track per (employee, date) for UPH history — one record per day per employee
            emp_date_totals = defaultdict(lambda: {
                "units": 0.0, "hours": 0.0, "uphs": [], "dept": "", "name": ""
            })

            # Determine whether any session has a date column mapped
            has_date_col  = any(s.get("mapping",{}).get("Date")  for s in sessions)

            for sess in sessions:
                s_mapping  = sess.get("mapping") or all_mapping
                s_rows     = sess.get("rows", [])
                s_id_col   = s_mapping.get("EmployeeID",   "EmployeeID")
                s_name_col = s_mapping.get("EmployeeName", "EmployeeName")
                s_dept_col = s_mapping.get("Department",   "Department")
                s_date_col = s_mapping.get("Date",         "")
                s_u_col    = s_mapping.get("Units",        "Units")
                s_h_col    = s_mapping.get("HoursWorked",  "HoursWorked")
                s_uph_col  = s_mapping.get("UPH",          "UPH")

                for row in s_rows:
                    eid = str(row.get(s_id_col, "")).strip()
                    if not eid:
                        continue

                    try: units_val = float(row.get(s_u_col, 0) or 0)
                    except (ValueError, TypeError): units_val = 0.0
                    try: hours_val = float(row.get(s_h_col, 0) or 0)
                    except (ValueError, TypeError): hours_val = 0.0
                    raw_uph = row.get(s_uph_col, None)

                    # Date: use mapped column value, fall back to work_date picker
                    row_date = work_date.isoformat()
                    if s_date_col and row.get(s_date_col):
                        raw_d = str(row[s_date_col]).strip()[:10]
                        try:
                            datetime.strptime(raw_d, "%Y-%m-%d")
                            row_date = raw_d
                        except ValueError:
                            pass

                    key = (eid, "", row_date)
                    combo_agg[key]["units"] += units_val
                    combo_agg[key]["hours"] += hours_val
                    if raw_uph:
                        try: combo_agg[key]["uphs"].append(float(raw_uph))
                        except (ValueError, TypeError): pass

                    name_val = str(row.get(s_name_col, "")).strip()
                    dept_val = str(row.get(s_dept_col, "")).strip()
                    if name_val:
                        combo_agg[key]["name"]                    = name_val
                        emp_date_totals[(eid, row_date)]["name"]  = name_val
                    if dept_val:
                        combo_agg[key]["dept"]                    = dept_val
                        emp_date_totals[(eid, row_date)]["dept"]  = dept_val

                    emp_date_totals[(eid, row_date)]["units"] += units_val
                    emp_date_totals[(eid, row_date)]["hours"] += hours_val
                    if raw_uph:
                        try: emp_date_totals[(eid, row_date)]["uphs"].append(float(raw_uph))
                        except (ValueError, TypeError): pass

            # Build alloc_rows — one entry per (emp, date) combo
            alloc_rows = []
            for (eid, _unused, row_date), agg in combo_agg.items():
                if agg["uphs"]:
                    uph = round(sum(agg["uphs"]) / len(agg["uphs"]), 2)
                elif agg["hours"] > 0:
                    uph = round(agg["units"] / agg["hours"], 2)
                else:
                    uph = 0.0
                alloc_rows.append({
                    "emp_id":    eid,
                    "name":      agg["name"] or eid,
                    "dept":      agg["dept"],
                    "units":     float(round(agg["units"])),
                    "hours":     round(agg["hours"], 2),
                    "uph":       uph,
                    "date":      row_date,
                })
            alloc_rows.sort(key=lambda r: (r.get("dept",""), r.get("name",""), r.get("date","")))

            # Canonical date for the alloc page
            wd_str    = work_date.isoformat()
            csv_dates = sorted({r["date"] for r in alloc_rows if r["date"]})
            canon_date = csv_dates[0] if (has_date_col and csv_dates) else wd_str

            # Resolve any blank departments from the employees table
            _emp_dept_map = {e["emp_id"]: e.get("department","") for e in (_cached_employees() or [])}

            # Store UPH history in background thread so user doesn't wait
            uph_batch = []
            for (eid, uph_date), agg in emp_date_totals.items():
                if agg["uphs"]:
                    uph = round(sum(agg["uphs"]) / len(agg["uphs"]), 2)
                elif agg["hours"] > 0:
                    uph = round(min(agg["units"] / agg["hours"], 9999), 2)
                else:
                    uph = 0.0
                dept = agg["dept"] or _emp_dept_map.get(eid, "")
                uph_batch.append({
                    "emp_id":       eid,
                    "work_date":    uph_date,
                    "uph":          uph,
                    "units":        round(agg["units"]),
                    "hours_worked": round(agg["hours"], 2),
                    "department":   dept,
                })
            # Store UPH history synchronously so data is in DB before pipeline completes
            try:
                _bg_tid = st.session_state.get("tenant_id", "")
                if _bg_tid:
                    uph_batch = [{**r, "tenant_id": _bg_tid} for r in uph_batch]
                batch_store_uph_history(uph_batch)
            except Exception as _uph_err:
                st.warning(f"UPH history storage warning: {_uph_err}")
                _log_app_error("pipeline", f"UPH history storage failed: {_uph_err}",
                               detail=traceback.format_exc(), severity="warning")

            _bust_cache()

            # Rebuild productivity from full DB (includes all past imports)
            # so that a second import doesn't lose the first import's data.
            bar.progress(90, text="Rebuilding full productivity view…")
            _full_ok = _build_archived_productivity()
            if not _full_ok:
                # Fallback: use only current import's data
                st.session_state.update({
                    "top_performers":    ranked,
                    "dept_report":       dept_report,
                    "dept_trends":       dept_trends,
                    "weekly_summary":    weekly,
                    "goal_status":       goal_status,
                    "trend_data":        trend_data,
                    "pipeline_done":     True,
                    "_archived_loaded":  False,
                })

            st.session_state.update({
                "mapping":           all_mapping,
                "alloc_rows":        alloc_rows,
                "alloc_date":        canon_date,
                "alloc_has_date":    has_date_col,
            })
            bar.progress(100, text="Done!")
            _unique_emp_count = len({r["emp_id"] for r in alloc_rows})
            st.toast(f"✓ {len(ranked)} employees ranked · {_unique_emp_count} employees processed", icon="✅")
            st.session_state.goto_page = "📈  Productivity"
            st.rerun()

        except Exception as _pipe_err:
            _tb = traceback.format_exc()
            st.error("Pipeline error:")
            st.code(_tb)
            _log_app_error("pipeline", str(_pipe_err), detail=_tb)

    st.divider()
    col1, col2 = st.columns(2)

    if col1.button("← Back to mapping", use_container_width=True):
        st.session_state.import_step = 2
        st.rerun()

    if st.session_state.pipeline_done and st.session_state.alloc_rows:
        _uc = len({r["emp_id"] for r in st.session_state.alloc_rows})
        col2.success(f"✓ {_uc} employees processed — view **📈 Productivity**")

    if st.button("↺ Start fresh import", use_container_width=True):
        st.session_state.uploaded_sessions = []
        st.session_state.import_step       = 1
        st.session_state.alloc_rows        = []
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: EMPLOYEES
# ══════════════════════════════════════════════════════════════════════════════

def _build_coaching_recommendations():
    """Generate smart coaching recommendations based on employee performance data."""
    gs = st.session_state.get("goal_status", [])
    if not gs:
        return []

    recommendations = []
    for r in gs:
        name = r.get("Employee", "")
        dept = r.get("Department", "")
        uph = r.get("Avg UPH")
        target = r.get("Target UPH")
        trend_dir = r.get("Trend", "")
        vs_target = r.get("vs Target")

        if not name:
            continue

        try:
            uph = float(uph) if uph and uph not in ("—", None, "") else None
        except (ValueError, TypeError):
            uph = None
        try:
            target = float(target) if target and target not in ("—", None, "", 0) else None
        except (ValueError, TypeError):
            target = None

        if uph is None:
            continue

        rec = {"name": name, "dept": dept, "uph": uph, "target": target,
               "priority": "low", "actions": [], "status": ""}

        # Determine gap
        gap_pct = 0
        if target and target > 0:
            gap_pct = round(((uph - target) / target) * 100, 1)

        # Rule-based coaching logic
        if target and gap_pct < -20:
            rec["priority"] = "high"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Schedule one-on-one coaching session — {name} is significantly below the {dept} target of {target} UPH.")
            rec["actions"].append("Review workstation setup and process efficiency for immediate improvements.")
            rec["actions"].append("Consider pairing with a top performer for peer mentoring.")
            if trend_dir and "declining" in str(trend_dir).lower():
                rec["actions"].append("URGENT: Performance is declining. Investigate potential issues (equipment, training, engagement).")
        elif target and gap_pct < -10:
            rec["priority"] = "medium"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Monitor closely — {name} is moderately below the {target} UPH target.")
            rec["actions"].append("Provide targeted training on efficiency techniques.")
            if trend_dir and "improving" in str(trend_dir).lower():
                rec["actions"].append("Positive sign: trend is improving. Continue current support.")
            else:
                rec["actions"].append("Set a 2-week improvement checkpoint to track progress.")
        elif target and gap_pct < 0:
            rec["priority"] = "low"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Slightly below target. Encourage {name} and recognize effort.")
            rec["actions"].append("Small adjustments to workflow may close the gap.")
        elif target and gap_pct >= 20:
            rec["priority"] = "star"
            rec["status"] = f"+{gap_pct}% above target"
            rec["actions"].append(f"Top performer! Consider {name} for peer mentor or team lead role.")
            rec["actions"].append("Recognize achievement publicly to boost team morale.")
        elif target and gap_pct >= 0:
            rec["priority"] = "low"
            rec["status"] = f"+{gap_pct}% above target"
            rec["actions"].append("Meeting or exceeding target. Keep up the good work!")
        else:
            rec["status"] = "No target set"
            rec["actions"].append(f"Set a department target for {dept} to enable performance tracking.")

        # Trend-based additions
        if trend_dir and "declining" in str(trend_dir).lower() and rec["priority"] != "high":
            rec["priority"] = "medium" if rec["priority"] == "low" else rec["priority"]
            rec["actions"].append("Note: Performance trend is declining — check in with employee.")

        recommendations.append(rec)

    # Sort: high first, then medium, then low, then star
    priority_order = {"high": 0, "medium": 1, "low": 2, "star": 3}
    recommendations.sort(key=lambda x: priority_order.get(x["priority"], 99))
    return recommendations


def page_employees():
    st.title("👥 Employees")
    if not require_db(): return

    _plan = _get_current_plan()
    EMP_OPTS = ["Employee History", "Performance Journal"]
    if _plan in ("pro", "business", "admin"):
        EMP_OPTS.append("🤖 Coaching Insights")
    if "emp_view" not in st.session_state or st.session_state.emp_view not in EMP_OPTS:
        st.session_state.emp_view = "Employee History"

    chosen = st.session_state.emp_view
    cols   = st.columns(len(EMP_OPTS))
    for i, opt in enumerate(EMP_OPTS):
        if cols[i].button(opt, key=f"ev_{opt}", use_container_width=True,
                           type="primary" if chosen == opt else "secondary"):
            st.session_state.emp_view = opt
            st.rerun()

    st.divider()
    try:
        if   chosen == "Employee History": _emp_history()
        elif chosen == "Performance Journal":   _emp_coaching()
        elif chosen == "🤖 Coaching Insights":  _emp_ai_coaching()
    except Exception as e:
        st.error(f"Error: {e}")
        _log_app_error("employees", f"Employee page error: {e}", detail=traceback.format_exc())



@st.fragment
def _emp_history():
    st.subheader("Employee UPH history")
    emps = _cached_employees()
    if not emps:
        st.info("No employees yet. Go to **Import Data** to upload a CSV — employees are created automatically from your data.")
        return

    # ── Department filter → populates employee dropdown ───────────────────────
    depts    = sorted({e.get("department","") for e in emps if e.get("department")})
    dept_sel = st.selectbox("Filter by department", ["All departments"] + depts, key="eh_dept")

    if dept_sel == "All departments":
        filtered_emps = emps
    else:
        filtered_emps = [e for e in emps if e.get("department","") == dept_sel]

    if not filtered_emps:
        st.info("No employees in that department.")
        return

    # Employee dropdown: Name — Department — ID
    emp_opts = {
        f"{e['name']} — {e.get('department','') or 'No dept'} — {e['emp_id']}": e["emp_id"]
        for e in filtered_emps
    }
    chosen = st.selectbox("Select employee", list(emp_opts.keys()), key="eh_emp")
    emp_id = emp_opts[chosen]

    from datetime import timedelta as _tdelta
    dc1, dc2 = st.columns(2)
    _def_from = (date.today() - _tdelta(days=90)).strftime("%m/%d/%Y")
    _def_to   = date.today().strftime("%m/%d/%Y")
    from_str  = dc1.text_input("From", value=st.session_state.get("eh_from", _def_from),
                                key="eh_from_input", placeholder="MM/DD/YYYY")
    to_str    = dc2.text_input("To",   value=st.session_state.get("eh_to",   _def_to),
                                key="eh_to_input",   placeholder="MM/DD/YYYY")
    try:
        from_date_h = datetime.strptime(from_str.strip(), "%m/%d/%Y").date()
    except Exception:
        from_date_h = date.today() - _tdelta(days=90)
    try:
        to_date_h = datetime.strptime(to_str.strip(), "%m/%d/%Y").date()
    except Exception:
        to_date_h = date.today()
    st.session_state["eh_from"] = from_str
    st.session_state["eh_to"]   = to_str
    days = max(1, (to_date_h - from_date_h).days)
    from_iso = from_date_h.isoformat()
    to_iso   = to_date_h.isoformat()

    # Query uph_history within date range
    try:
        _sb_h = _get_db_client()
        _r_h  = _sb_h.table("uph_history").select("*") \
                      .eq("emp_id", emp_id) \
                      .gte("work_date", from_iso) \
                      .lte("work_date", to_iso) \
                      .order("work_date").execute()
        history = _r_h.data or []
    except Exception:
        history = []

    # Fallback: derive from unit_submissions if uph_history empty
    if not history:
        try:
            from collections import defaultdict as _dh
            _sb3 = _get_db_client()
            _r3  = _sb3.table("unit_submissions").select("*") \
                        .eq("emp_id", emp_id) \
                        .gte("work_date", from_iso) \
                        .lte("work_date", to_iso) \
                        .order("work_date").execute()
            _day = _dh(lambda: {"units": 0.0, "hours": 0.0})
            for _s in (_r3.data or []):
                _dk = _s.get("work_date", "")
                _day[_dk]["units"] += float(_s.get("units") or 0)
                _day[_dk]["hours"] += float(_s.get("hours_worked") or 0)
            history = [{"work_date": _dk,
                        "uph":   round(_v["units"] / _v["hours"], 2) if _v["hours"] > 0 else 0,
                        "units": round(_v["units"]),
                        "hours_worked": round(_v["hours"], 2)}
                       for _dk, _v in sorted(_day.items())]
        except Exception:
            pass

    if not history:
        st.info("No history yet for this employee.")
        return

    uphvals = [float(h.get("uph") or 0) for h in history if h.get("uph")]
    avg_uph = round(sum(uphvals) / len(uphvals), 2) if uphvals else None
    st.metric(f"Avg UPH ({from_str} – {to_str})", f"{avg_uph:.2f}" if avg_uph else "No data")

    df = pd.DataFrame([{
        "Date":  h.get("work_date", ""),
        "UPH":   round(float(h.get("uph") or 0), 2),
        "Units": int(h.get("units", 0) or 0),
        "Hours": round(float(h.get("hours_worked") or 0), 2),
    } for h in history]).sort_values("Date")

    # Remove rows with 0 or non-finite UPH before charting to avoid Infinity warnings
    import math as _math
    df_chart = df[df["UPH"].apply(lambda x: x > 0 and _math.isfinite(x))]
    if not df_chart.empty:
        st.line_chart(df_chart.set_index("Date")[["UPH"]], use_container_width=True)
    else:
        st.info("No valid UPH data to chart for this date range.")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("⬇️ Export employee history"):
        with st.spinner("Generating…"):
            data = export_employee(emp_id)
        st.download_button(f"⬇️ Download {emp_id}_history.xlsx", data,
                           f"employee_{emp_id}_{date.today()}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@st.fragment
@st.fragment
def _emp_ai_coaching():
    """Show AI-powered coaching recommendations based on performance data."""
    st.subheader("🤖 Coaching Insights")
    st.caption("Smart recommendations based on employee performance, goals, and trends.")

    if not st.session_state.get("pipeline_done") and not st.session_state.get("_archived_loaded"):
        _build_archived_productivity()

    recs = _build_coaching_recommendations()
    if not recs:
        st.info("No coaching data available. Import productivity data and set department goals first.")
        return

    # Summary metrics
    _high = sum(1 for r in recs if r["priority"] == "high")
    _med  = sum(1 for r in recs if r["priority"] == "medium")
    _stars = sum(1 for r in recs if r["priority"] == "star")
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("🔴 Urgent", _high)
    mc2.metric("🟡 Monitor", _med)
    mc3.metric("🟢 On Track", sum(1 for r in recs if r["priority"] == "low"))
    mc4.metric("⭐ Stars", _stars)

    st.markdown("---")

    # Filter
    _filter = st.radio("Show", ["All", "🔴 Urgent only", "🟡 Needs attention", "⭐ Top performers"],
                        horizontal=True, key="coaching_filter")

    for rec in recs:
        if _filter == "🔴 Urgent only" and rec["priority"] != "high":
            continue
        if _filter == "🟡 Needs attention" and rec["priority"] not in ("high", "medium"):
            continue
        if _filter == "⭐ Top performers" and rec["priority"] != "star":
            continue

        # Priority badge
        _badge = {"high": "🔴", "medium": "🟡", "low": "🟢", "star": "⭐"}.get(rec["priority"], "")
        _uph_str = f" — {rec['uph']} UPH" if rec["uph"] else ""
        _target_str = f" (target: {rec['target']})" if rec["target"] else ""

        with st.expander(f"{_badge} **{rec['name']}** · {rec['dept']}{_uph_str}{_target_str} · {rec['status']}"):
            for action in rec["actions"]:
                st.markdown(f"→ {action}")

    st.markdown("---")
    st.caption("Recommendations are generated from UPH data, department targets, and performance trends. "
               "Review and adapt based on your direct knowledge of each employee.")


def _emp_coaching():
    emps  = _cached_employees()
    flags = _cached_active_flags()
    if not emps:
        st.info("No employees yet. Go to **Import Data** to upload a CSV — employees are created automatically from your data.")
        return

    # ── Build employee list — all employees, annotate who has notes / is flagged
    emp_ids_with_notes = _cached_all_coaching_notes()
    all_depts = sorted({e.get("department","") for e in emps if e.get("department")})

    # ── Manager Action List ──────────────────────────────────────────────────
    # Auto-generates follow-up actions for trending-down or below-goal employees
    gs = st.session_state.get("goal_status", [])
    if "dismissed_actions" not in st.session_state:
        st.session_state.dismissed_actions = set()

    action_items = []
    for r in gs:
        eid  = str(r.get("EmployeeID", r.get("Employee Name", "")))
        name = r.get("Employee Name", "")
        dept = r.get("Department", "")
        trend      = r.get("trend", "")
        goal_st    = r.get("goal_status", "")
        change_pct = r.get("change_pct", 0)
        avg_uph    = r.get("Average UPH", 0)
        target     = r.get("Target UPH", "—")

        reasons = []
        if trend == "down":
            reasons.append(f"Trending down ({change_pct:+.1f}%)")
        if goal_st == "below_goal":
            reasons.append(f"Below goal (UPH {avg_uph:.1f} vs target {target})")

        if reasons:
            action_key = f"{eid}|{'|'.join(reasons)}"
            if action_key not in st.session_state.dismissed_actions:
                action_items.append({
                    "eid": eid, "name": name, "dept": dept,
                    "reasons": reasons, "key": action_key,
                    "trend": trend, "goal_st": goal_st,
                })

    if action_items:
        with st.expander(f"📋 **Manager Action List** — {len(action_items)} follow-up(s) needed", expanded=True):
            st.caption("Employees trending down or below goal. Complete the follow-up, then dismiss the action.")
            for ai in action_items:
                ac1, ac2, ac3 = st.columns([3, 5, 1])
                badge = ""
                if ai["trend"] == "down": badge += " ↓"
                if ai["goal_st"] == "below_goal": badge += " ⚠️"
                ac1.markdown(f"**{ai['name']}**{badge}")
                ac2.caption(f"{ai['dept']} · {' · '.join(ai['reasons'])}")
                if ac3.button("✓", key=f"dismiss_{ai['key']}", help="Mark as done"):
                    st.session_state.dismissed_actions.add(ai["key"])
                    st.rerun()

            if st.button("Clear all completed actions", key="clear_dismissed", type="secondary"):
                st.session_state.dismissed_actions.clear()
                st.rerun()
    else:
        if gs:
            st.success("✓ No follow-ups needed — all employees are on track.")

    # ── Top bar: dept filter ──────────────────────────────────────────────────
    dept_sel = st.selectbox("Department", ["All departments"] + all_depts, key="cn_dept",
                             label_visibility="collapsed")
    filtered_emps = (emps if dept_sel == "All departments"
                     else [e for e in emps if e.get("department","") == dept_sel])

    st.divider()

    # ── Main two-column layout ────────────────────────────────────────────────
    col_list, col_detail = st.columns([2, 3], gap="large")

    with col_list:
        st.caption(f"**{dept_sel}** · {len(filtered_emps)} employee(s)")
        roster = []
        for e in filtered_emps:
            indicators = ""
            if e["emp_id"] in flags:           indicators += "🚩 "
            if e["emp_id"] in emp_ids_with_notes:
                _nc = len(_cached_coaching_notes_for(e["emp_id"]))
                indicators += f"📝{_nc}" if _nc else "📝"
            # Add trend indicator from goal_status
            _gs_match = next((r for r in gs if str(r.get("EmployeeID","")) == e["emp_id"]), None)
            if _gs_match:
                _t = _gs_match.get("trend","")
                if _t == "down": indicators += " ↓"
                elif _t == "up": indicators += " ↑"
            roster.append({
                " ": indicators.strip(),
                "Name": e["name"],
                "Dept": e.get("department",""),
            })
        df_roster = pd.DataFrame(roster)
        sel = st.dataframe(
            df_roster,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )
        sel_rows = sel.selection.rows if sel and sel.selection else []
        if sel_rows:
            selected_emp = filtered_emps[sel_rows[0]]
            st.session_state["cn_selected_emp"] = selected_emp["emp_id"]
        else:
            st.session_state.pop("cn_selected_emp", None)
            selected_emp = None

    with col_detail:
        if not selected_emp:
            st.info("← Select an employee from the list")
        else:
            emp_id   = selected_emp["emp_id"]
            emp_name = selected_emp["name"]
            emp_dept = selected_emp.get("department","")

            # ── Header ────────────────────────────────────────────────────────
            is_flagged = emp_id in flags
            hc1, hc2 = st.columns([4, 1])
            hc1.markdown(f"### {emp_name}")
            hc1.caption(emp_dept)

            # Show trend + goal summary inline
            _emp_gs = next((r for r in gs if str(r.get("EmployeeID","")) == str(emp_id)), None)
            if _emp_gs:
                _trend_icon = {"up": "↑", "down": "↓", "flat": "→"}.get(_emp_gs.get("trend",""), "—")
                _chg = _emp_gs.get("change_pct", 0)
                _chg_str = f"+{_chg:.1f}%" if _chg > 0 else f"{_chg:.1f}%"
                _uph = _emp_gs.get("Average UPH", 0)
                _tgt = _emp_gs.get("Target UPH", "—")
                _gs_color = {"on_goal": "green", "below_goal": "red"}.get(_emp_gs.get("goal_status",""), "gray")
                st.markdown(
                    f"<span style='font-size:13px;'>"
                    f"Avg UPH: <strong>{_uph:.1f}</strong> · "
                    f"Target: <strong>{_tgt}</strong> · "
                    f"Trend: {_trend_icon} {_chg_str}"
                    f"</span>",
                    unsafe_allow_html=True)

            if is_flagged:
                flag_info = flags.get(emp_id, {})
                st.warning(f"🚩 Flagged for performance tracking since **{flag_info.get('flagged_on','')}**")
                if st.button("✓ Remove flag", key="cn_unflag", type="secondary"):
                    from goals import unflag_employee
                    unflag_employee(emp_id)
                    _raw_cached_active_flags.clear()
                    for r in st.session_state.get("goal_status", []):
                        if str(r.get("EmployeeID","")) == str(emp_id):
                            r["flagged"] = False
                    st.rerun()

            # ── Add entry ────────────────────────────────────────────────────
            if "cn_note_val" not in st.session_state: st.session_state.cn_note_val = ""
            if "cn_by_val"   not in st.session_state: st.session_state.cn_by_val   = ""
            note_text  = st.text_area("Add a journal entry", height=90, key="cn_note",
                                       value=st.session_state.cn_note_val,
                                       placeholder="Performance observation, coaching session, follow-up…")
            nc1, nc2 = st.columns([2, 3])
            created_by = nc2.text_input("Your name (optional)", key="cn_by",
                                         value=st.session_state.cn_by_val,
                                         placeholder="Your name")
            if nc1.button("💾 Save entry", type="primary", use_container_width=True):
                if note_text.strip():
                    add_coaching_note(emp_id, note_text.strip(), created_by.strip())
                    _raw_cached_coaching_notes_for.clear()
                    _raw_cached_all_coaching_notes.clear()
                    st.session_state.cn_note_val = ""
                    st.session_state.cn_by_val   = ""
                    st.success("✓ Entry saved.")
                    st.rerun()
                else:
                    st.warning("Write something before saving the entry.")

            # ── Past entries ─────────────────────────────────────────────────
            notes = _cached_coaching_notes_for(emp_id)
            st.divider()
            if notes:
                st.caption(f"{len(notes)} journal entry/entries on file")
                for n in notes:
                    with st.container():
                        nc1, nc2 = st.columns([10, 1])
                        _n_date = _html_mod.escape(str(n.get('created_at',''))[:10])
                        _n_by = _html_mod.escape(n.get('created_by',''))
                        _n_text = _html_mod.escape(n.get('note',''))
                        nc1.markdown(
                            f"<div style='background:#F7F9FC;border-left:3px solid #0F2D52;"
                            f"border-radius:4px;padding:8px 12px;margin-bottom:4px;'>"
                            f"<span style='color:#5A7A9C;font-size:11px;'>"
                            f"{_n_date}"
                            f"{'  ·  ' + _n_by if _n_by else ''}</span>"
                            f"<br><span style='color:#1A2D42;font-size:13px;'>{_n_text}</span>"
                            f"</div>",
                            unsafe_allow_html=True)
                        note_id = n.get("id")
                        if note_id and nc2.button("🗑", key=f"del_{note_id}", help="Delete"):
                            delete_coaching_note(str(note_id))
                            _raw_cached_coaching_notes_for.clear()
                            _raw_cached_all_coaching_notes.clear()
                            st.rerun()

                # Actions row
                st.divider()
                ac1, ac2 = st.columns(2)
                if ac1.button("⬇️ Export journal", key="cn_export", use_container_width=True):
                    buf = io.BytesIO()
                    pd.DataFrame([{
                        "Date": str(n.get("created_at",""))[:10],
                        "Note": n.get("note",""),
                        "By":   n.get("created_by",""),
                    } for n in notes]).to_excel(buf, index=False, sheet_name="Journal")
                    buf.seek(0)
                    ac1.download_button(f"⬇️ Download", buf.read(),
                                        f"{emp_id}_journal_{date.today()}.xlsx",
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        key="cn_dl", use_container_width=True)
                if ac2.button("📦 Archive all entries", key="cn_archive",
                               use_container_width=True, type="secondary"):
                    archive_coaching_notes(emp_id)
                    _raw_cached_coaching_notes_for.clear()
                    _raw_cached_all_coaching_notes.clear()
                    st.session_state.pop("cn_selected_emp", None)
                    st.rerun()
            else:
                st.caption("No journal entries yet — add one above.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: CLIENTS
# ══════════════════════════════════════════════════════════════════════════════

def page_clients():
    st.title("🏢 Clients")
    if not require_db(): return

    CL_OPTS = ["All Clients", "Add Client"]
    if "clients_view" not in st.session_state:
        st.session_state.clients_view = "All Clients"

    chosen = st.session_state.clients_view
    cols   = st.columns(len(CL_OPTS))
    for i, opt in enumerate(CL_OPTS):
        if cols[i].button(opt, key=f"clv_{opt}", use_container_width=True,
                           type="primary" if chosen == opt else "secondary"):
            st.session_state.clients_view = opt
            st.rerun()

    st.divider()
    try:
        if   chosen == "All Clients":   _clients_list()
        elif chosen == "Add Client":    _client_create()
    except Exception as e:
        st.error(f"Error: {e}")
        _log_app_error("clients", f"Clients page error: {e}", detail=traceback.format_exc())


def _clients_list():
    clients = _cached_clients()
    if not clients:
        st.info("No clients yet. Click the **Add Client** tab above to add your first client.")
        return

    for c in clients:
        with st.expander(f"**{c['name']}**"):
            cid = c["id"]

            # ── View / Edit toggle ────────────────────────────────────────────
            edit_key = f"cl_edit_{cid}"
            if st.session_state.get(edit_key):
                # Edit mode
                new_name  = st.text_input("Company name", value=c.get("name",""), key=f"cl_nm_{cid}")
                new_notes = st.text_area("Notes", value=c.get("notes","") or "", height=68, key=f"cl_nt_{cid}")
                st.markdown("**Contacts**")

                # Parse existing contacts (stored as semicolon-separated)
                ec_key = f"cl_contacts_{cid}"
                if ec_key not in st.session_state:
                    names  = [n.strip() for n in (c.get("contact","") or "").split(";") if n.strip()]
                    emails = [e.strip() for e in (c.get("email","")   or "").split(";") if e.strip()]
                    max_len = max(len(names), len(emails), 1)
                    st.session_state[ec_key] = [
                        {"name": names[i] if i < len(names) else "",
                         "email": emails[i] if i < len(emails) else ""}
                        for i in range(max_len)
                    ]

                for ci2, ct in enumerate(st.session_state[ec_key]):
                    ec1, ec2, ec3 = st.columns([3, 3, 1])
                    ct["name"]  = ec1.text_input("Name",  value=ct["name"],  key=f"ecn_{cid}_{ci2}",
                                                  placeholder="Jane Smith",    label_visibility="visible" if ci2==0 else "collapsed")
                    ct["email"] = ec2.text_input("Email", value=ct["email"], key=f"ece_{cid}_{ci2}",
                                                  placeholder="jane@acme.com", label_visibility="visible" if ci2==0 else "collapsed")
                    if ec3.button("✕", key=f"ecr_{cid}_{ci2}") and len(st.session_state[ec_key]) > 1:
                        st.session_state[ec_key].pop(ci2); st.rerun()

                if st.button("+ Add contact", key=f"ec_add_{cid}"):
                    st.session_state[ec_key].append({"name":"","email":""}); st.rerun()

                sv1, sv2 = st.columns(2)
                if sv1.button("💾 Save", type="primary", key=f"cl_save_{cid}"):
                    contacts  = st.session_state[ec_key]
                    c_str = "; ".join(ct["name"]  for ct in contacts if ct["name"].strip())
                    e_str = "; ".join(ct["email"] for ct in contacts if ct["email"].strip())
                    update_client(cid, name=new_name.strip(), contact=c_str,
                                  email=e_str, notes=new_notes.strip())
                    _bust_cache()
                    st.session_state.pop(ec_key, None)
                    st.session_state[edit_key] = False
                    st.success("✓ Saved.")
                    st.rerun()
                if sv2.button("Cancel", key=f"cl_cancel_{cid}"):
                    st.session_state.pop(ec_key, None)
                    st.session_state[edit_key] = False
                    st.rerun()
            else:
                # View mode
                contacts_raw = c.get("contact","") or "—"
                emails_raw   = c.get("email","")   or "—"
                col1, col2 = st.columns(2)
                col1.caption(f"Contact: {contacts_raw}")
                col2.caption(f"Email: {emails_raw}")
                if c.get("notes"):
                    st.caption(c["notes"])
                if st.button("✏️ Edit client", key=f"cl_edit_btn_{cid}"):
                    st.session_state[edit_key] = True
                    st.rerun()

            st.divider()
            bc1, bc2 = st.columns(2)
            if bc1.button("⬇️ Export history", key=f"exp_cl_{cid}"):
                with st.spinner("Generating…"):
                    data = export_client(cid)
                st.download_button(f"⬇️ Download {c['name']}.xlsx", data,
                                   f"client_{c['name']}_{date.today()}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   key=f"dl_cl_{cid}")
            with bc2.expander("🗑 Delete client"):
                st.warning(f"Permanently deletes **{c['name']}**.")
                dc_confirm = st.text_input("Type client name to confirm", key=f"dc_{cid}", placeholder=c['name'])
                if st.button("Delete permanently", key=f"del_cl_{cid}"):
                    if dc_confirm.strip().lower() == c["name"].strip().lower():
                        try:
                            delete_client(cid)
                            _bust_cache()
                            st.success(f"✓ {c['name']} deleted.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Delete failed: {e}")
                            _log_app_error("clients", f"Client delete failed ({c['name']}): {e}", detail=traceback.format_exc())
                    else:
                        st.error("Name doesn't match.")


def _client_create():
    st.subheader("Add new client")

    if "cc_ver" not in st.session_state:
        st.session_state.cc_ver = 0
    v = st.session_state.cc_ver

    name  = st.text_input("Company name*", placeholder="e.g. Acme Logistics", key=f"cc_name_{v}")
    notes = st.text_area("Notes", height=68, key=f"cc_notes_{v}")
    st.markdown("**Contacts** *(add as many as needed)*")
    if "cc_contacts" not in st.session_state:
        st.session_state.cc_contacts = [{"name":"","email":""}]
    for ci, ct in enumerate(st.session_state.cc_contacts):
        cc1, cc2, cc3 = st.columns([3, 3, 1])
        ct["name"]  = cc1.text_input("Name",  value=ct["name"],  key=f"ccn_{v}_{ci}", placeholder="Jane Smith",    label_visibility="visible" if ci == 0 else "collapsed")
        ct["email"] = cc2.text_input("Email", value=ct["email"], key=f"cce_{v}_{ci}", placeholder="jane@acme.com", label_visibility="visible" if ci == 0 else "collapsed")
        if cc3.button("✕", key=f"ccr_{v}_{ci}") and len(st.session_state.cc_contacts) > 1:
            st.session_state.cc_contacts.pop(ci); st.rerun()
    if st.button("+ Add contact", key=f"cc_addrow_{v}"):
        st.session_state.cc_contacts.append({"name":"","email":""}); st.rerun()
    st.divider()
    if st.button("Add client", type="primary", use_container_width=True, key=f"cc_submit_{v}"):
        if not name.strip():
            st.error("Company name is required.")
        else:
            contacts = st.session_state.cc_contacts
            contact_str = "; ".join(c["name"]  for c in contacts if c["name"].strip())
            email_str   = "; ".join(c["email"] for c in contacts if c["email"].strip())
            with st.spinner("Saving…"):
                create_client_record(name.strip(), contact_str, email_str, notes.strip())
            _bust_cache()
            _saved_name = name.strip()
            st.session_state.cc_contacts = [{"name":"","email":""}]
            st.session_state.cc_ver += 1   # bump version → all widgets get fresh keys → fields clear
            st.toast(f"✅ {_saved_name} added successfully.", icon="✅")
            st.rerun()




# ══════════════════════════════════════════════════════════════════════════════
# PAGE: PRODUCTIVITY (UPH rankings, goals, tracker — existing functionality)
# ══════════════════════════════════════════════════════════════════════════════



def _build_archived_productivity():
    """
    Build productivity session state from DB. Queries aggregate data directly
    to avoid fetching thousands of raw rows.
    """
    from collections import defaultdict
    from datetime import datetime as _dt

    emps     = {e["emp_id"]: e for e in (_cached_employees() or [])}
    emp_dept = {eid: e.get("department","") for eid, e in emps.items()}
    emp_name = {eid: e.get("name", eid)    for eid, e in emps.items()}

    # Don't bail if employees table is empty — UPH history has dept/emp info
    sb = _get_db_client()

    # ── Per-employee aggregates (avg UPH, total units, record count) ──────────
    # Use running sum+count instead of growing lists to keep memory constant.
    emp_agg        = defaultdict(lambda: {"uph_sum": 0.0, "units": 0.0, "count": 0})
    month_dept_agg = defaultdict(lambda: defaultdict(lambda: {"uph_sum": 0.0, "uph_count": 0, "units": 0.0}))
    week_dept_agg  = defaultdict(lambda: defaultdict(lambda: {"units": 0.0, "uph_sum": 0.0, "uph_count": 0}))
    # Per-employee weekly UPH for trend analysis
    emp_week_uph   = defaultdict(lambda: defaultdict(list))  # emp_id -> week_str -> [uph values]

    page_size = 1000
    offset    = 0
    total_rows = 0
    _last_err  = None
    while True:
        try:
            from database import _tq as _tq_fn
            r = _tq_fn(sb.table("uph_history").select(
                "emp_id, work_date, uph, units, department"
            )).order("work_date").range(offset, offset + page_size - 1).execute()
            batch = r.data or []
        except Exception as _pe:
            _last_err = repr(_pe)
            break
        for row in batch:
            eid   = row.get("emp_id","")
            uph   = float(row.get("uph") or 0)
            units = float(row.get("units") or 0)
            dept  = emp_dept.get(eid) or row.get("department") or "Unknown"
            # Backfill dept/name from UPH history when employees table is empty
            if eid not in emp_dept and dept:
                emp_dept[eid] = dept
            if eid not in emp_name:
                emp_name[eid] = eid  # fallback to ID
            wd    = (row.get("work_date") or "")[:10]
            month = wd[:7]
            if uph > 0:
                emp_agg[eid]["uph_sum"] += uph
                emp_agg[eid]["count"]   += 1
            emp_agg[eid]["units"] += units
            if month and uph > 0:
                month_dept_agg[month][dept]["uph_sum"]   += uph
                month_dept_agg[month][dept]["uph_count"] += 1
                month_dept_agg[month][dept]["units"]     += units
            if wd:
                try:
                    d  = _dt.strptime(wd, "%Y-%m-%d")
                    wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
                    week_dept_agg[wk][dept]["units"] += units
                    if uph > 0:
                        week_dept_agg[wk][dept]["uph_sum"]   += uph
                        week_dept_agg[wk][dept]["uph_count"] += 1
                        emp_week_uph[eid][wk].append(uph)
                except Exception:
                    pass
        total_rows += len(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    # Fallback to unit_submissions if uph_history empty
    if total_rows == 0:
        offset = 0
        while True:
            try:
                r = _tq_fn(sb.table("unit_submissions").select(
                    "emp_id, work_date, units, hours_worked"
                )).order("work_date").range(offset, offset + page_size - 1).execute()
                batch = r.data or []
            except Exception:
                break
            for row in batch:
                eid   = row.get("emp_id","")
                units = float(row.get("units") or 0)
                hours = float(row.get("hours_worked") or 0)
                uph   = round(units / hours, 2) if hours > 0 else 0
                dept  = emp_dept.get(eid, "Unknown")
                wd    = (row.get("work_date") or "")[:10]
                month = wd[:7]
                if uph > 0:
                    emp_agg[eid]["uph_sum"] += uph
                    emp_agg[eid]["count"]   += 1
                emp_agg[eid]["units"] += units
                if month and uph > 0:
                    month_dept_agg[month][dept]["uph_sum"]   += uph
                    month_dept_agg[month][dept]["uph_count"] += 1
                    month_dept_agg[month][dept]["units"]     += units
                if wd:
                    try:
                        d  = _dt.strptime(wd, "%Y-%m-%d")
                        wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
                        week_dept_agg[wk][dept]["units"]     += units
                        if uph > 0:
                            week_dept_agg[wk][dept]["uph_sum"]   += uph
                            week_dept_agg[wk][dept]["uph_count"] += 1
                    except Exception:
                        pass
            total_rows += len(batch)
            if len(batch) < page_size:
                break
            offset += page_size

    if not emp_agg:
        st.session_state["_archived_loaded"] = False
        # Show what we found for debugging
        if hasattr(st, "session_state"):
            st.session_state["_arch_debug"] = f"uph_history rows: {total_rows}, unit_submissions fallback ran: {total_rows == 0}"
        return False

    # ── Build ranked list ─────────────────────────────────────────────────────
    ranked = []
    for i, (eid, agg) in enumerate(
            sorted(emp_agg.items(),
                   key=lambda x: x[1]["uph_sum"] / max(x[1]["count"], 1),
                   reverse=True), 1):
        avg_uph = round(agg["uph_sum"] / max(agg["count"], 1), 2)
        ranked.append({
            "Rank":          i,
            "Department":    emp_dept.get(eid, ""),
            "Shift":         "",
            "Employee Name": emp_name.get(eid, eid),
            "Average UPH":   avg_uph,
            "Record Count":  agg["count"],
            "EmployeeID":    eid,
            "goal_status":   "no_goal",
            "trend":         "insufficient_data",
            "flagged":       False,
            "change_pct":    0,
            "Target UPH":    "—",
            "vs Target":     "—",
        })

    # ── dept_trends ───────────────────────────────────────────────────────────
    dept_trends = []
    for month in sorted(month_dept_agg):
        for dept, vals in month_dept_agg[month].items():
            if vals["uph_count"] > 0:
                dept_trends.append({
                    "Month":       month,
                    "Department":  dept,
                    "Average UPH": round(vals["uph_sum"] / vals["uph_count"], 2),
                    "Count":       vals["uph_count"],
                })

    # ── weekly_summary ────────────────────────────────────────────────────────
    weekly_summary = []
    for wk in sorted(week_dept_agg):
        for dept, vals in week_dept_agg[wk].items():
            weekly_summary.append({
                "Week":        wk,
                "Month":       wk[:7],
                "Department":  dept,
                "Total Units": round(vals["units"]),
                "Avg UPH":     round(vals["uph_sum"] / max(vals["uph_count"], 1), 2),
            })

    # ── dept_report ───────────────────────────────────────────────────────────
    dept_report = {}
    for r2 in ranked:
        dept_report.setdefault(r2.get("Department",""), []).append(r2)

    # ── Build trend_data from per-employee weekly UPH ─────────────────────────
    _trend_weeks = 4
    try:
        import streamlit as _st2
        _trend_weeks = _st2.session_state.get("trend_weeks", 4)
    except Exception:
        pass
    all_weeks_sorted = sorted(
        {wk for emp_wks in emp_week_uph.values() for wk in emp_wks}
    )
    recent_weeks = all_weeks_sorted[-_trend_weeks:] if len(all_weeks_sorted) >= _trend_weeks else all_weeks_sorted

    trend_data = {}
    for eid, week_map in emp_week_uph.items():
        week_avgs = []
        for w in recent_weeks:
            vals = week_map.get(w, [])
            if vals:
                week_avgs.append({"week": w, "avg_uph": round(sum(vals) / len(vals), 2)})

        if len(week_avgs) < 2:
            direction  = "insufficient_data"
            change_pct = 0.0
        else:
            first = week_avgs[0]["avg_uph"]
            last  = week_avgs[-1]["avg_uph"]
            change_pct = round(((last - first) / first * 100) if first else 0, 1)
            if change_pct >= 3:
                direction = "up"
            elif change_pct <= -3:
                direction = "down"
            else:
                direction = "flat"

        trend_data[eid] = {
            "name":       emp_name.get(eid, eid),
            "dept":       emp_dept.get(eid, ""),
            "direction":  direction,
            "weeks":      week_avgs,
            "change_pct": change_pct,
        }

    # ── Apply goals ───────────────────────────────────────────────────────────
    try:
        from goals import build_goal_status as _bgs
        _arch_gs = _bgs(ranked, _cached_targets(), trend_data)
    except Exception:
        _arch_gs = ranked

    st.session_state.update({
        "top_performers":  ranked,
        "goal_status":     _arch_gs,
        "dept_report":     dept_report,
        "dept_trends":     dept_trends,
        "weekly_summary":  weekly_summary,
        "trend_data":      trend_data,
        "pipeline_done":   True,
        "_archived_loaded": True,
    })
    return True


def page_productivity():
    st.title("📈 Productivity")
    st.caption("UPH rankings, department goals, trend charts, and performance tracking.")

    try:
        from goals          import (analyse_trends, build_goal_status, get_all_targets,
                                    set_dept_target, flag_employee, unflag_employee,
                                    add_note, get_active_flags, load_goals, save_goals)
        from ranker         import build_department_report
        from error_log      import ErrorLog
        from exporter       import export_excel
    except ImportError as e:
        st.error(f"Productivity module error: {e}"); return

    # Nav buttons (no tabs — avoids running all content simultaneously)
    PROD_OPTS = ["🎯 Dept Goals", "📊 Goal Status", "📈 Trends", "📅 Weekly", "💰 Labor Cost"]
    if "prod_view" not in st.session_state:
        st.session_state.prod_view = "🎯 Dept Goals"

    chosen_prod = st.session_state.prod_view
    cols = st.columns(len(PROD_OPTS))
    for i, opt in enumerate(PROD_OPTS):
        if cols[i].button(opt, key=f"pv_{i}", use_container_width=True,
                          type="primary" if chosen_prod == opt else "secondary"):
            st.session_state.prod_view = opt
            st.rerun()

    st.divider()

    class _PS:
        def get(self, k, d=None): return st.session_state.get(k, d)
        def get_output_dir(self): return tempfile.gettempdir()
        def get_dept_target_uph(self, d):
            t = get_all_targets().get(d, 0)
            return float(t) if t else 0.0
        def all_mappings(self): return st.session_state.get("mapping", {})

    # ── Helper: re-apply goals to current pipeline data ──────────────────────
    def _reapply_goals():
        if not st.session_state.pipeline_done:
            return
        try:
            targets  = _cached_targets()
            tw       = st.session_state.get("trend_weeks", 4)
            history  = st.session_state.get("history", [])
            mapping  = st.session_state.get("mapping", {})
            trend_data = analyse_trends(history, mapping, weeks=tw) if history else {}
            goal_status = build_goal_status(
                st.session_state.get("top_performers", []), targets, trend_data)
            ps  = _PS()
            log = ErrorLog(tempfile.gettempdir())
            dept_report = build_department_report(
                st.session_state.get("top_performers", []), ps, log)
            st.session_state.goal_status = goal_status
            st.session_state.dept_report = dept_report
            st.session_state.trend_data  = trend_data
        except Exception as _e:
            pass   # silently skip — archived data may lack history

    # Load archived data from DB if pipeline hasn't run this session
    if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
        with st.spinner("Loading archived productivity data…"):
            try:
                ok = _build_archived_productivity()
                if not ok:
                    _dbg = st.session_state.get("_arch_debug", "")
                    st.warning(f"No productivity data found in the database. Run Import Data to get started. {_dbg}")
            except BaseException as _ae:
                try:    st.error(f"Archive load error: {repr(_ae)[:300]}")
                except Exception: st.error("Could not load archived data — check DB connection.")
                _log_app_error("productivity", f"Archive load error: {repr(_ae)[:500]}", detail=traceback.format_exc())

    if st.session_state.get("_archived_loaded"):
        _tp_count = len(st.session_state.get("top_performers", []))
        _dt_count = len(st.session_state.get("dept_trends", []))
        st.info(f"📂 Showing archived data — {_tp_count} employees, {_dt_count} trend records. Run Import Data to load fresh results.")

    # Reapply goals only when targets changed (not every click)
    _fresh_targets = _cached_targets()
    _prev_targets  = st.session_state.get("_last_applied_targets")
    if st.session_state.pipeline_done and st.session_state.get("top_performers") and _fresh_targets != _prev_targets:
        try:
            _fresh_td      = st.session_state.get("trend_data", {})
            _fresh_gs      = build_goal_status(
                st.session_state.top_performers, _fresh_targets, _fresh_td)
            st.session_state.goal_status = _fresh_gs
            st.session_state["_last_applied_targets"] = dict(_fresh_targets)
            # Only rebuild dept_report for live data — archived version is already correct
            if not st.session_state.get("_archived_loaded"):
                _ps2  = _PS()
                _log2 = ErrorLog(tempfile.gettempdir())
                st.session_state.dept_report = build_department_report(
                    st.session_state.top_performers, _ps2, _log2)
        except Exception:
            pass

    # ── DEPT GOALS ────────────────────────────────────────────────────────────
    if chosen_prod == "🎯 Dept Goals":
        st.subheader("Department UPH targets")
        st.caption("Set a UPH target for each department. Type a value and press Enter — it saves immediately and updates all charts.")

        # Trend window slider lives here
        tw = st.slider("Trend window (weeks)", 2, 12,
                       st.session_state.get("trend_weeks", 4), key="prod_tw")
        if tw != st.session_state.get("trend_weeks", 4):
            st.session_state.trend_weeks = tw
            _reapply_goals()
            st.rerun()

        st.divider()

        # Top / bottom highlight thresholds
        hc1, hc2 = st.columns(2)
        st.session_state.top_pct = hc1.slider(
            "Top % highlighted green", 0, 50,
            st.session_state.get("top_pct", 10), key="goals_top_pct"
        )
        st.session_state.bot_pct = hc2.slider(
            "Bottom % highlighted red", 0, 50,
            st.session_state.get("bot_pct", 10), key="goals_bot_pct"
        )

        st.divider()

        targets   = _cached_targets()
        goals_obj = load_goals()

        # Auto-populate departments from all available sources
        if st.session_state.pipeline_done:
            all_depts = set()
            # From goal_status
            for r in st.session_state.get("goal_status", []):
                if r.get("Department"): all_depts.add(r["Department"])
            # From top_performers
            for r in st.session_state.get("top_performers", []):
                if r.get("Department"): all_depts.add(r["Department"])
            # From employees table (catches archived data with blank uph_history dept)
            for e in (_cached_employees() or []):
                if e.get("department"): all_depts.add(e["department"])
            for d in all_depts:
                if d and d not in targets:
                    set_dept_target(d, 0.0)
                    _raw_cached_targets.clear()
            targets = _cached_targets()

        dept_list  = sorted(targets.keys())
        goal_changed = False

        if not dept_list:
            st.info("No departments yet. Run Import Data first — departments are detected automatically from your CSV.")
        else:
            # Header row
            hc1, hc2, hc3 = st.columns([3, 2, 1])
            hc1.markdown("**Department**")
            hc2.markdown("**UPH Target** *(press Enter to save)*")
            hc3.markdown("")
            st.divider()

            for dept in dept_list:
                cur = float(targets.get(dept, 0) or 0)
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f"**{dept}**")

                # Seed text input once — don't overwrite after user changes it
                seed_key = f"goal_seed_{dept}"
                txt_key  = f"goal_txt_{dept}"
                if seed_key not in st.session_state:
                    st.session_state[seed_key] = True
                    # Seed from persisted JSON value — this runs on every fresh session
                    st.session_state[txt_key] = str(int(cur)) if cur else ""
                elif txt_key not in st.session_state:
                    # Key was cleared somehow — re-seed from JSON
                    st.session_state[txt_key] = str(int(cur)) if cur else ""

                c2.text_input("UPH", key=txt_key,
                              label_visibility="collapsed",
                              placeholder="e.g. 18")

                # Parse and save on every render — if value changed, store it
                raw = st.session_state.get(txt_key, "")
                try:
                    new_val = float(raw.strip()) if raw.strip() else 0.0
                except (ValueError, TypeError):
                    new_val = cur

                if abs(new_val - cur) > 0.001:
                    set_dept_target(dept, new_val)
                    _audit("GOAL_TARGET", f"{dept} | {cur} → {new_val}")
                    _raw_cached_targets.clear()
                    goal_changed = True

                if c3.button("✕", key=f"rm_dept_{dept}", help="Remove department"):
                    goals_obj["dept_targets"].pop(dept, None)
                    save_goals(goals_obj)
                    _raw_cached_targets.clear()
                    st.session_state.pop(seed_key, None)
                    st.session_state.pop(txt_key,  None)
                    goal_changed = True

        # Departments are added automatically from the pipeline — no manual add form

        # Reapply goals to all charts after any change
        if goal_changed and st.session_state.pipeline_done:
            _reapply_goals()
            st.toast("✓ Goals updated", icon="🎯")
            st.rerun()

    # ── GOAL STATUS ───────────────────────────────────────────────────────────
    elif chosen_prod == "📊 Goal Status":
        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            _build_archived_productivity()
        gs = st.session_state.get("goal_status", [])
        # If goal_status is empty but we have top_performers, rebuild it
        if not gs and st.session_state.get("top_performers"):
            try:
                gs = build_goal_status(
                    st.session_state.top_performers, _cached_targets(),
                    st.session_state.get("trend_data", {}))
                st.session_state.goal_status = gs
            except Exception:
                pass
        if not gs:
            st.info("No data yet — run Import Data or check that UPH history exists.")
            return

        total    = len(gs)
        on_goal  = sum(1 for r in gs if r.get("goal_status") == "on_goal")
        below    = sum(1 for r in gs if r.get("goal_status") == "below_goal")
        trending = sum(1 for r in gs if r.get("trend") == "down")
        flagged  = sum(1 for r in gs if r.get("flagged"))
        m1,m2,m3,m4,m5 = st.columns(5)
        m1.metric("Employees", total)
        m2.metric("On goal 🟢", on_goal)
        m3.metric("Below goal 🔴", below)
        m4.metric("Trending ↓", trending)
        m5.metric("Flagged 🚩", flagged)
        st.divider()

        depts  = sorted({r.get("Department","") for r in gs if r.get("Department")})
        fc1,fc2 = st.columns(2)
        dept_f  = fc1.selectbox("Filter by department", ["All departments"] + depts, key="gs_dept")
        stat_f  = fc2.multiselect("Filter by status",
                    ["On goal","Below goal","No target set"],
                    default=["On goal","Below goal","No target set"], key="gs_stat")
        stat_map = {"On goal":"on_goal","Below goal":"below_goal","No target set":"no_goal"}
        allowed  = {stat_map[s] for s in stat_f}
        filtered = [r for r in gs
                    if (dept_f == "All departments" or r.get("Department") == dept_f)
                    and r.get("goal_status") in allowed]

        TREND  = {"up":"↑ Improving","down":"↓ Declining","flat":"→ Stable","insufficient_data":"—"}
        STATUS = {"on_goal":"🟢","below_goal":"🔴","no_goal":"⚪"}
        rows   = [{
            "🚩":        "🚩" if r.get("flagged") else "",
            "Dept":      r.get("Department",""),
            "Shift":     r.get("Shift",""),
            "Employee":  r.get("Employee Name",""),
            "Avg UPH":   round(float(r.get("Average UPH",0) or 0),2),
            "Target":    r.get("Target UPH") if r.get("Target UPH") not in ("—", None, "", 0) else None,
            "vs Target": r.get("vs Target") if r.get("vs Target") not in ("—", None, "") else None,
            "Status":    STATUS.get(r.get("goal_status",""),""),
            "Trend":     TREND.get(r.get("trend",""),"—"),
            "Change":    f"{r.get('change_pct',0):+.1f}%",
        } for r in filtered]

        df = pd.DataFrame(rows)
        hl_map = {"🟢":"#1a6b3a","🔴":"#8b1a1a","⚪":"#2a3a4a"}
        def hl(s):
            row = rows[s.name]
            clr = hl_map.get(row.get("Status",""), "#2a3a4a")
            if row.get("Trend","").startswith("↓") and clr == "#1a6b3a": clr = "#7a5c00"
            return [f"background-color:{clr}; color:#ffffff" for _ in s]
        st.dataframe(
            df.style.apply(hl, axis=1),
            use_container_width=True, hide_index=True)
        st.caption("Employees are compared against the UPH target set in Dept Goals. 🟢 Avg UPH ≥ target · 🔴 Avg UPH < target · 🟡 On goal but UPH is declining week-over-week · ⚪ No target set for this department")
        _gs_buf = io.BytesIO()
        df.to_excel(_gs_buf, index=False, engine="openpyxl")
        _gs_buf.seek(0)
        st.download_button("⬇️ Download Goal Status.xlsx", _gs_buf.read(),
                           f"Goal_Status_{date.today()}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="dl_goal_status")

        st.divider()
        st.subheader("🚩 Flag employees for performance tracking")
        emp_labels      = [f"{r.get('Employee Name','')} — {r.get('Department','')} ({r.get('Shift','')})" for r in filtered]
        active_flag_ids = set(_cached_active_flags().keys())
        if emp_labels:
            _flag_tab1, _flag_tab2 = st.tabs(["Flag individual", "Bulk flag / unflag"])
            with _flag_tab1:
                if "flag_reason_val" not in st.session_state:
                    st.session_state.flag_reason_val = ""
                fc3, fc4, fc5 = st.columns([3,2,1])
                _below_labels = [l for l, r in zip(emp_labels, filtered) if r.get("goal_status") == "below_goal"]
                _flag_default  = emp_labels.index(_below_labels[0]) if _below_labels else 0
                sel_emp = fc3.selectbox("Employee", emp_labels, index=_flag_default, key="flag_sel")
                reason  = fc4.text_input("Reason", value=st.session_state.flag_reason_val,
                                          key="flag_reason", placeholder="Optional reason")
                if fc5.button("Flag", type="primary", use_container_width=True):
                    idx    = emp_labels.index(sel_emp)
                    emp    = filtered[idx]
                    emp_id = str(emp.get("EmployeeID", emp.get("Employee Name","")))
                    flag_employee(emp_id, emp.get("Employee Name",""), emp.get("Department",""), reason.strip())
                    _audit("FLAG", f"{emp.get('Employee Name','')} | dept={emp.get('Department','')} | reason={reason.strip()}")
                    _raw_cached_active_flags.clear()
                    _raw_cached_all_coaching_notes.clear()
                    _raw_cached_coaching_notes_for.clear()
                    st.session_state.flag_reason_val = ""
                    st.session_state.pop("flag_reason", None)
                    st.toast(f"✓ {emp.get('Employee Name','')} flagged", icon="🚩")
                    st.rerun()
            with _flag_tab2:
                # ── Currently flagged summary ──────────────────────────────
                _currently_flagged = [
                    (_lbl, _r) for _lbl, _r in zip(emp_labels, filtered)
                    if str(_r.get("EmployeeID", _r.get("Employee Name",""))) in active_flag_ids
                ]
                if _currently_flagged:
                    st.markdown(
                        f"<div style='background:#FFF3E0;border-left:4px solid #E65100;"
                        f"border-radius:0 6px 6px 0;padding:10px 14px;margin-bottom:12px;'>"
                        f"<b style='color:#BF360C;font-size:12px;text-transform:uppercase;"
                        f"letter-spacing:.05em;'>🚩 {len(_currently_flagged)} Active Flag(s)</b><br>"
                        + "".join(
                            f"<span style='color:#BF360C;font-size:13px;'>• {_html_mod.escape(_lbl)}</span><br>"
                            for _lbl, _ in _currently_flagged
                        )
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("No employees currently flagged.")

                st.caption("Select employees below — 🚩 marks those already flagged.")
                # Build display labels with 🚩 prefix for already-flagged employees
                _bulk_display = []
                for _lbl, _r in zip(emp_labels, filtered):
                    _eid = str(_r.get("EmployeeID", _r.get("Employee Name", "")))
                    _bulk_display.append(f"🚩 {_lbl}" if _eid in active_flag_ids else _lbl)

                bulk_sel_disp = st.multiselect("Select employees", _bulk_display, key="bulk_flag_sel")
                # Strip the 🚩 prefix to recover the plain label for lookup
                bulk_sel      = [l.removeprefix("🚩 ") for l in bulk_sel_disp]

                bulk_reason = st.text_input("Reason (applies to all)", key="bulk_flag_reason", placeholder="Optional")
                bc1, bc2    = st.columns(2)
                if bc1.button("🚩 Flag all selected", type="primary", use_container_width=True, key="bulk_flag_btn"):
                    if bulk_sel:
                        for lbl in bulk_sel:
                            _bi = emp_labels.index(lbl)
                            _be = filtered[_bi]
                            _beid = str(_be.get("EmployeeID", _be.get("Employee Name","")))
                            flag_employee(_beid, _be.get("Employee Name",""), _be.get("Department",""), bulk_reason.strip())
                        _raw_cached_active_flags.clear(); _raw_cached_all_coaching_notes.clear(); _raw_cached_coaching_notes_for.clear()
                        st.toast(f"✓ {len(bulk_sel)} employee(s) flagged", icon="🚩"); st.rerun()
                if bc2.button("✓ Unflag all selected", type="secondary", use_container_width=True, key="bulk_unflag_btn"):
                    if bulk_sel:
                        for lbl in bulk_sel:
                            _bi = emp_labels.index(lbl)
                            _be = filtered[_bi]
                            _beid = str(_be.get("EmployeeID", _be.get("Employee Name","")))
                            if _beid in active_flag_ids:
                                unflag_employee(_beid)
                        _raw_cached_active_flags.clear()
                        st.toast(f"✓ {len(bulk_sel)} employee(s) unflagged", icon="✅"); st.rerun()

    # ── TRENDS ────────────────────────────────────────────────────────────────
    elif chosen_prod == "📈 Trends":
        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            _build_archived_productivity()
        trends = st.session_state.dept_trends
        if not trends: st.info("No trend data yet."); return
        df_t = pd.DataFrame(trends)
        # Date range filter
        months = sorted(df_t["Month"].unique()) if "Month" in df_t.columns else []
        if months:
            import re as _re
            min_m, max_m = months[0], months[-1]
            # Persist applied range in session state
            # Reset range if data was refreshed (new pipeline run)
            _data_key = f"trends_data_key_{min_m}_{max_m}"
            if st.session_state.get("_trends_data_key") != _data_key:
                st.session_state.trend_applied_from = min_m
                st.session_state.trend_applied_to   = max_m
                st.session_state["_trends_data_key"] = _data_key
            elif "trend_applied_from" not in st.session_state:
                st.session_state.trend_applied_from = min_m
            if "trend_applied_to" not in st.session_state:
                st.session_state.trend_applied_to   = max_m

            tr1, tr2, tr3 = st.columns([3, 3, 1])
            from_raw = tr1.text_input("From (YYYY-MM)", value=st.session_state.trend_applied_from,
                                       key="trend_from", placeholder="e.g. 2024-03")
            to_raw   = tr2.text_input("To (YYYY-MM)",   value=st.session_state.trend_applied_to,
                                       key="trend_to",   placeholder="e.g. 2025-03")
            if tr3.button("Apply", type="primary", use_container_width=True, key="trend_apply"):
                fm = from_raw.strip()
                tm = to_raw.strip()
                st.session_state.trend_applied_from = fm if _re.match(r"\d{4}-\d{2}", fm) else min_m
                st.session_state.trend_applied_to   = tm if _re.match(r"\d{4}-\d{2}", tm) else max_m
                st.rerun()

            from_month = st.session_state.trend_applied_from
            to_month   = st.session_state.trend_applied_to
            mask = (df_t["Month"] >= from_month) & (df_t["Month"] <= to_month)
            df_t = df_t[mask]
        st.subheader("Average UPH over time by department")
        st.caption("Each line shows the average UPH for that department across all employees for each month. Use From/To to zoom into a date range.")
        try:
            import math as _math2
            df_t_clean = df_t[df_t["Average UPH"].apply(
                lambda x: _math2.isfinite(float(x)) if x is not None else False)]
            if not df_t_clean.empty:
                st.line_chart(df_t_clean.pivot(index="Month", columns="Department", values="Average UPH"),
                              use_container_width=True)
        except Exception: pass
        st.dataframe(df_t, use_container_width=True, hide_index=True)
        _tr_buf = io.BytesIO()
        df_t.to_excel(_tr_buf, index=False, engine="openpyxl")
        _tr_buf.seek(0)
        st.download_button("⬇️ Download Trends.xlsx", _tr_buf.read(),
                           f"Trends_{date.today()}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="dl_trends_prod")

    # ── WEEKLY ────────────────────────────────────────────────────────────────
    elif chosen_prod == "📅 Weekly":
        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            _build_archived_productivity()
        weekly = st.session_state.weekly_summary
        if not weekly: st.info("No weekly data yet."); return
        df_w = pd.DataFrame(weekly)

        # Date range filter
        all_from = sorted(df_w["From"].dropna().unique()) if "From" in df_w.columns else []
        all_to   = sorted(df_w["To"].dropna().unique())   if "To"   in df_w.columns else []
        all_dates = sorted(set(all_from + all_to))

        wk1, wk2 = st.columns(2)
        if all_dates:
            d_from = wk1.date_input("From", value=datetime.strptime(all_dates[0], "%Y-%m-%d").date(),
                                    key="wk_from")
            d_to   = wk2.date_input("To",   value=datetime.strptime(all_dates[-1], "%Y-%m-%d").date(),
                                    key="wk_to")
            mask = pd.Series([True] * len(df_w))
            if "From" in df_w.columns:
                mask &= df_w["From"] >= d_from.isoformat()
            if "To" in df_w.columns:
                mask &= df_w["To"] <= d_to.isoformat()
            df_w = df_w[mask]

        st.subheader("Total units per week by department")
        st.caption("Each row represents one department's output for a given week. Use the date range to filter.")

        # Chart
        try:
            df_w_clean = df_w.dropna(subset=["Total Units"])
            if not df_w_clean.empty:
                chart_label = df_w_clean["Week Range"] if "Week Range" in df_w_clean.columns else df_w_clean["Week"]
                chart_df = df_w_clean.copy()
                chart_df["Period"] = chart_label
                st.line_chart(chart_df.pivot(index="Period", columns="Department", values="Total Units"),
                              use_container_width=True)
        except Exception: pass

        # Table grouped by week
        display_cols = [c for c in ["Week Range", "Department", "Avg UPH", "Total Units", "Record Count"]
                        if c in df_w.columns]
        if not display_cols:
            display_cols = [c for c in df_w.columns if c not in ("From", "To")]

        weeks_sorted = sorted(df_w["Week"].unique()) if "Week" in df_w.columns else []
        for wk in weeks_sorted:
            wk_slice = df_w[df_w["Week"] == wk]
            if wk_slice.empty:
                continue
            wk_range = wk_slice["Week Range"].iloc[0] if "Week Range" in wk_slice.columns else wk
            st.markdown(f"**{wk}** &nbsp;&nbsp; {wk_range}")
            show_cols = [c for c in display_cols if c != "Week Range"]
            st.dataframe(wk_slice[show_cols], use_container_width=True, hide_index=True)

        _wk_buf = io.BytesIO()
        df_w[display_cols].to_excel(_wk_buf, index=False, engine="openpyxl")
        _wk_buf.seek(0)
        st.download_button("⬇️ Download Weekly.xlsx", _wk_buf.read(),
                           f"Weekly_{date.today()}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="dl_weekly")

    elif chosen_prod == "💰 Labor Cost":
        _plan = _get_current_plan()
        if _plan not in ("pro", "business", "admin"):
            st.info("💰 Labor Cost Impact is available on **Pro** and **Business** plans.")
            st.caption("Upgrade in Settings → Subscription to unlock this feature.")
            return

        st.subheader("Labor Cost Impact Analysis")
        st.caption("See the dollar impact of employee performance vs targets. Enter your average hourly wage to calculate.")

        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            _build_archived_productivity()

        gs = st.session_state.get("goal_status", [])
        if not gs:
            st.info("No productivity data. Import data first.")
            return

        _hourly_wage = st.number_input("Average hourly wage ($)", min_value=0.0, value=18.0, step=0.50, key="labor_wage")

        # Build labor cost table
        _lc_rows = []
        for r in gs:
            name = r.get("Employee", "")
            dept = r.get("Department", "")
            uph  = r.get("Avg UPH")
            target = r.get("Target UPH")
            hours = r.get("Hours Worked") or r.get("HoursWorked")

            if not uph or not target or target in ("—", None, "", 0):
                continue
            try:
                uph = float(uph)
                target = float(target)
            except (ValueError, TypeError):
                continue

            # Estimate hours from data or default to 40
            try:
                hours = float(hours) if hours and hours not in ("—", None, "") else 40.0
            except (ValueError, TypeError):
                hours = 40.0

            expected_units = target * hours
            actual_units = uph * hours
            unit_diff = actual_units - expected_units
            # Cost per unit = wage / target_uph
            cost_per_unit = _hourly_wage / target if target > 0 else 0
            dollar_impact = unit_diff * cost_per_unit

            _lc_rows.append({
                "Employee": name,
                "Department": dept,
                "Avg UPH": round(uph, 1),
                "Target": round(target, 1),
                "UPH Diff": round(uph - target, 1),
                "Est. Hours": round(hours, 1),
                "Unit Diff": round(unit_diff, 0),
                "$ Impact": round(dollar_impact, 2),
            })

        if not _lc_rows:
            st.info("No employees with both UPH and targets set.")
            return

        df_lc = pd.DataFrame(_lc_rows).sort_values("$ Impact")

        # Summary metrics
        total_loss = sum(r["$ Impact"] for r in _lc_rows if r["$ Impact"] < 0)
        total_gain = sum(r["$ Impact"] for r in _lc_rows if r["$ Impact"] > 0)
        net_impact = total_loss + total_gain

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Lost from Underperformance", f"-${abs(total_loss):,.0f}", delta_color="inverse")
        mc2.metric("Gained from Overperformance", f"+${total_gain:,.0f}")
        mc3.metric("Net Impact", f"${net_impact:,.0f}",
                    delta=f"${net_impact:,.0f}", delta_color="normal")

        st.markdown("---")

        # Color code: red for negative, green for positive
        st.subheader("Employee Breakdown")
        st.caption("Negative = costing you money vs target. Positive = saving you money.")

        def _color_impact(val):
            try:
                v = float(val)
                if v < 0: return "color: #FF4444"
                if v > 0: return "color: #44AA44"
            except: pass
            return ""

        styled = df_lc.style.applymap(_color_impact, subset=["$ Impact", "UPH Diff"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # Department summary
        st.subheader("Department Summary")
        dept_summary = {}
        for r in _lc_rows:
            d = r["Department"]
            if d not in dept_summary:
                dept_summary[d] = {"Department": d, "Employees": 0, "Total $ Impact": 0}
            dept_summary[d]["Employees"] += 1
            dept_summary[d]["Total $ Impact"] += r["$ Impact"]
        df_dept = pd.DataFrame(dept_summary.values())
        df_dept["Total $ Impact"] = df_dept["Total $ Impact"].round(2)
        st.dataframe(df_dept, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: EMAIL SETUP (preserved from previous version)
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_period_dates(period: str):
    """Convert a named period string to (start_date, end_date)."""
    from datetime import timedelta
    today = date.today()
    if period == "Prior day":
        return today - timedelta(days=1), today - timedelta(days=1)
    elif period == "Current week":
        return today - timedelta(days=today.weekday()), today
    elif period == "Prior week":
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end
    elif period == "Prior month":
        first_of_this = today.replace(day=1)
        end = first_of_this - timedelta(days=1)
        return end.replace(day=1), end
    return today - timedelta(days=1), today - timedelta(days=1)


def _build_period_report(d_start, d_end, dept_choice: str, depts: list,
                          gs: list, targets: dict):
    """
    Build Excel report bytes, subject, and HTML body for a date range.
    d_start / d_end are date objects. Returns (xl_bytes, subj, body).
    """
    from collections import defaultdict as _dc
    today = date.today()

    from_iso     = d_start.isoformat()
    to_iso       = d_end.isoformat()
    period_label = from_iso if from_iso == to_iso else f"{from_iso} – {to_iso}"
    dept_label   = dept_choice if dept_choice != "All departments" else "All Departments"
    subj         = f"Performance Report — {dept_label} — {period_label}"

    try:
        _sb = _get_db_client()
        from database import _tq as _tq3
        _r  = _tq3(_sb.table("uph_history").select(
            "emp_id, units, hours_worked, uph, work_date, department"
        ).gte("work_date", from_iso).lte("work_date", to_iso)).execute()
        subs = _r.data or []
    except Exception:
        subs = []

    emps_lookup = {e["emp_id"]: e for e in (_cached_employees() or [])}
    if dept_choice != "All departments":
        subs = [s for s in subs
                if (s.get("department","") == dept_choice or
                    emps_lookup.get(s.get("emp_id",""),{}).get("department","") == dept_choice)]

    if not subs:
        body = (f"<h2>{dept_label} — {period_label}</h2>"
                f"<p>No work data was found for <strong>{dept_label}</strong> "
                f"between <strong>{from_iso}</strong> and <strong>{to_iso}</strong>.</p>"
                f"<p>Employees may not have had submissions during this period, "
                f"or the date range falls outside your imported data.</p>")
        return None, subj, body

    emp_agg = _dc(lambda: {"units": 0.0, "hours": 0.0, "dept": ""})
    for s in subs:
        eid = s.get("emp_id","")
        emp_agg[eid]["units"] += float(s.get("units") or 0)
        emp_agg[eid]["hours"] += float(s.get("hours_worked") or 0)
        emp_agg[eid]["dept"]   = emps_lookup.get(eid,{}).get("department","")

    scope_gs = []
    for eid, agg in emp_agg.items():
        emp_info = emps_lookup.get(eid, {})
        dept     = agg["dept"]
        uph      = round(agg["units"] / agg["hours"], 2) if agg["hours"] > 0 else 0
        tgt      = float(targets.get(dept, 0) or 0)
        scope_gs.append({
            "Employee Name": emp_info.get("name", eid),
            "EmployeeID":    eid,
            "Department":    dept,
            "Average UPH":   uph,
            "Total Units":   round(agg["units"]),
            "Hours Worked":  round(agg["hours"], 2),
            "Target UPH":    tgt if tgt else "—",
            "goal_status":   ("on_goal" if tgt and uph >= tgt
                              else "below_goal" if tgt else "no_goal"),
            "flagged":       False,
        })
    scope_gs.sort(key=lambda r: float(r.get("Average UPH", 0) or 0), reverse=True)

    on_g  = sum(1 for r in scope_gs if r["goal_status"] == "on_goal")
    below = sum(1 for r in scope_gs if r["goal_status"] == "below_goal")

    # Top 3 performers
    _top3 = scope_gs[:3]
    _top3_html = ""
    if _top3:
        _top3_html = "<h3>🏆 Top Performers</h3><ol>"
        for t in _top3:
            _top3_html += f"<li><strong>{t['Employee Name']}</strong> ({t['Department']}) — {t['Average UPH']} UPH</li>"
        _top3_html += "</ol>"

    # Bottom 3 performers (with targets)
    _bottom = [r for r in reversed(scope_gs) if r["goal_status"] == "below_goal"][:3]
    _bottom_html = ""
    if _bottom:
        _bottom_html = "<h3>⚠️ Needs Coaching</h3><ol>"
        for b in _bottom:
            _tgt = b.get('Target UPH', '—')
            _diff = ""
            try:
                _diff = f" ({round(float(b['Average UPH']) - float(_tgt), 1)} vs target)"
            except (ValueError, TypeError):
                pass
            _bottom_html += f"<li><strong>{b['Employee Name']}</strong> ({b['Department']}) — {b['Average UPH']} UPH{_diff}</li>"
        _bottom_html += "</ol>"

    # Average UPH across all employees
    _avg_all = round(sum(r["Average UPH"] for r in scope_gs) / len(scope_gs), 1) if scope_gs else 0

    body  = (f"<h2>{dept_label} — {period_label}</h2>"
             f"<p><strong>{len(scope_gs)}</strong> employees · "
             f"Avg UPH: <strong>{_avg_all}</strong> · "
             f"<strong style='color:green'>{on_g} on goal</strong> · "
             f"<strong style='color:red'>{below} below goal</strong></p>"
             f"{_top3_html}"
             f"{_bottom_html}"
             f"<p>See the attached Excel report for full details.</p>")

    xl_data = None
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.chart import BarChart, Reference
        HDR_FILL  = PatternFill("solid", fgColor="FF0F2D52")
        HDR_FONT  = Font(bold=True, color="FFFFFFFF", size=10, name="Arial")
        GRN_FILL  = PatternFill("solid", fgColor="FFD4EDDA")
        RED_FILL  = PatternFill("solid", fgColor="FFF8D7DA")
        DARK_FONT = Font(color="FF1A2D42", size=10, name="Arial")
        STATUS_LABELS = {"on_goal":"On Goal","below_goal":"Below Goal","no_goal":"No Target"}

        wb = openpyxl.Workbook()
        ws = wb.active; ws.title = "Summary"
        ws["A1"] = f"{dept_label} — {period_label}"
        ws["A1"].font = Font(bold=True, size=13, name="Arial", color="FF0F2D52")
        ws["A2"] = f"Generated: {today.isoformat()}   |   {on_g} on goal · {below} below goal"
        ws["A2"].font = Font(size=10, name="Arial", color="FF5A7A9C")

        hdrs = ["Employee","Department","Total Units","Hours Worked","Avg UPH","Target UPH","Status"]
        for ci, h in enumerate(hdrs, 1):
            c = ws.cell(4, ci, h); c.fill = HDR_FILL; c.font = HDR_FONT
            c.alignment = Alignment(horizontal="center")
        for ri, r in enumerate(scope_gs, 5):
            fill = (GRN_FILL if r["goal_status"] == "on_goal"
                    else RED_FILL if r["goal_status"] == "below_goal" else None)
            for ci, v in enumerate([r["Employee Name"], r["Department"],
                                     r["Total Units"], r["Hours Worked"],
                                     r["Average UPH"], r["Target UPH"],
                                     STATUS_LABELS.get(r["goal_status"],"—")], 1):
                c = ws.cell(ri, ci, v); c.font = DARK_FONT
                c.alignment = Alignment(horizontal="left" if ci <= 2 else "center")
                if fill: c.fill = fill

        if scope_gs:
            chart = BarChart(); chart.type = "bar"; chart.style = 10
            chart.title = f"Avg UPH — {period_label}"
            chart.width = 20; chart.height = max(8, len(scope_gs) * 0.55)
            last_r = 4 + len(scope_gs)
            chart.add_data(Reference(ws, min_col=5, min_row=4, max_row=last_r), titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=5, max_row=last_r))
            chart.series[0].graphicalProperties.solidFill = "0F2D52"
            ws.add_chart(chart, "I5")

        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(
                max((len(str(c.value or "")) for c in col), default=8) + 3, 40)

        buf = io.BytesIO(); wb.save(buf); buf.seek(0); xl_data = buf.read()
    except Exception:
        pass

    return xl_data, subj, body


def page_email():
    st.title("📧 Email Setup")
    st.caption("Configure who receives reports, when they are sent, and send manual reports.")
    try:
        from email_engine import (save_smtp_config, get_smtp_config, add_recipient,
                                   remove_recipient, get_recipients, add_schedule,
                                   remove_schedule, get_schedules, send_report_email,
                                   build_dept_email_body, DAY_NAMES,
                                   import_recipients_from_csv)
    except ImportError:
        st.error("Email module not found."); return

    tab_smtp, tab_recip, tab_sched, tab_send = st.tabs([
        "1️⃣ SMTP Setup", "2️⃣ Recipients", "3️⃣ Schedules", "📤 Send Now"
    ])

    # ── SMTP ─────────────────────────────────────────────────────────────────
    with tab_smtp:
        st.subheader("Email server settings")
        st.caption("Pick your email provider below and we'll fill in the server details automatically.")

        cfg = get_smtp_config()

        # Provider quick-select
        providers = {
            "Gmail":            ("smtp.gmail.com",      587),
            "Outlook / Office 365": ("smtp.office365.com", 587),
            "Yahoo":            ("smtp.mail.yahoo.com", 587),
            "Custom":           ("", 587),
        }
        # Detect current provider from saved server
        cur_server = cfg.get("server","")
        detected = next((k for k,v in providers.items() if v[0] == cur_server), "Custom")
        pcols = st.columns(len(providers))
        for i,(pname,pvals) in enumerate(providers.items()):
            active = (detected == pname)
            if pcols[i].button(pname, key=f"prov_{i}",
                               type="primary" if active else "secondary",
                               use_container_width=True):
                st.session_state["smtp_server_override"] = pvals[0]
                st.session_state["smtp_port_override"]   = pvals[1]
                st.rerun()

        # App password help
        with st.expander("❓ How to get an App Password"):
            st.markdown("""
#### Gmail

**Before you start:** You must have 2-Step Verification turned on — App Passwords won't appear without it.

1. Go to **myaccount.google.com**
2. Click **Security** in the left sidebar
3. Under *"How you sign in to Google"*, click **2-Step Verification** and turn it on if it's off
4. Go back to the Security page and type **"App passwords"** in the search bar at the top — it won't appear in the menu, search is the only way to find it
5. Click **App passwords** in the results
6. Type a name like **Productivity Planner** and click **Create**
7. Google shows you a **16-character password** — copy it immediately, you won't see it again
8. Paste it into the **App password** field below

> ⚠️ If App Passwords doesn't appear even after enabling 2-Step Verification, your account may be managed by a Google Workspace admin who needs to enable it.

---

#### Outlook / Office 365

**Before you start:** You must have 2-Step Verification turned on for your Microsoft account.

1. Go to **account.microsoft.com** and sign in
2. Click **Security** at the top of the page
3. Click **Advanced security options** (under "Security basics")
4. Scroll down to the *"App passwords"* section
5. Click **Create a new app password**
6. Microsoft shows you a password — copy it immediately, you won't see it again
7. Paste it into the **App password** field below

> ⚠️ If you don't see the App passwords section, your organization's admin may need to enable it. Work and school accounts managed by an IT department may require admin approval first.

---

#### Yahoo

**Before you start:** You must have 2-Step Verification turned on for your Yahoo account.

1. Go to **login.yahoo.com** and sign in
2. Click your **profile icon** (top-right) and select **Account Info**
3. Click **Account Security** in the left sidebar
4. Make sure **Two-step verification** is turned on — if it's off, click it and follow the prompts to enable it
5. Scroll down and click **Generate app password** (or "Manage app passwords")
6. Select **Other app** from the dropdown and type **Productivity Planner**
7. Click **Generate**
8. Yahoo shows you a **16-character password** — copy it immediately, you won't see it again
9. Paste it into the **App password** field below

> ⚠️ If Generate app password doesn't appear, make sure Two-step verification is fully enabled and you've refreshed the page.

---

#### Custom SMTP Server

If your email provider isn't listed above, select **Custom** and fill in the Advanced server settings:

1. Ask your email provider or IT team for the **SMTP server address** (e.g. `mail.yourcompany.com`)
2. Ask for the **SMTP port** — usually **587** (TLS) or **465** (SSL)
3. Enter your **full email address** in the "Your email address" field
4. Enter your **email password** or app-specific password in the "App password" field
5. Open **Advanced server settings**, enter the server address and port, and make sure **Use TLS encryption** is checked (recommended)
6. Click **Save settings** and then **Send test email to myself** to verify

> ⚠️ Some corporate servers require a VPN connection or only allow sending from within the company network.

---

You **cannot** use your regular login password for Gmail, Outlook, or Yahoo — they block it for third-party apps.
App passwords are typically 16 characters and look like: **abcd efgh ijkl mnop**
            """)

        # Use override if provider button was just pressed
        server_val = st.session_state.get("smtp_server_override", cfg.get("server",""))
        port_val   = st.session_state.get("smtp_port_override",   int(cfg.get("port",587)))

        with st.form("smtp_form"):
            username = st.text_input("Your email address", value=cfg.get("username",""),
                                      placeholder="you@gmail.com")
            password = st.text_input("App password", value=cfg.get("password",""),
                                      type="password", placeholder="16-character app password")
            # Advanced — collapsed by default
            with st.expander("Advanced server settings"):
                c1, c2 = st.columns(2)
                server  = c1.text_input("SMTP server", value=server_val, placeholder="smtp.gmail.com")
                port    = c2.number_input("Port", value=port_val, min_value=1, max_value=65535)
                use_tls = st.checkbox("Use TLS encryption (recommended)", value=bool(cfg.get("use_tls",True)))

            if st.form_submit_button("Save settings", type="primary", use_container_width=True):
                save_smtp_config(server, port, username, password, username, use_tls)
                # Clear overrides now that they are saved
                st.session_state.pop("smtp_server_override", None)
                st.session_state.pop("smtp_port_override", None)
                st.success("✓ Settings saved.")
                st.rerun()

        if st.button("Send test email to myself", use_container_width=True):
            cfg2 = get_smtp_config()
            if not cfg2.get("username"):
                st.warning("Save your email address first.")
            else:
                with st.spinner("Sending test…"):
                    ok, err = send_report_email(
                        [cfg2["username"]],
                        "Productivity Planner — Test Email",
                        "<p>Your email configuration is working correctly! 🎉</p>",
                    )
                if ok: st.success(f"✓ Test email sent to {cfg2['username']}")
                else:  st.error(f"Failed: {err}")

    # ── Recipients ────────────────────────────────────────────────────────────
    with tab_recip:
        st.subheader("Who receives reports")

        recipients = get_recipients()
        if recipients:
            # Show each recipient with an inline remove button
            for r in recipients:
                rc1, rc2, rc3 = st.columns([3, 4, 1])
                rc1.markdown(f"**{r['name']}**")
                rc2.caption(r["email"])
                if rc3.button("✕", key=f"rm_recip_{r['email']}", help="Remove"):
                    remove_recipient(r["email"])
                    _success_then_rerun(f"✓ {r['email']} removed.")
            st.divider()
        else:
            st.info("No recipients yet.")

        st.subheader("Add recipients")
        st.caption("Add one or more at a time. Press **+ Add row** then **Save all** when done.")

        # Dynamic multi-row add form
        if "new_recips" not in st.session_state:
            st.session_state.new_recips = [{"name": "", "email": ""}]

        for ni, nr in enumerate(st.session_state.new_recips):
            nr1, nr2, nr3 = st.columns([3, 4, 1])
            nr["name"]  = nr1.text_input("Name",  value=nr["name"],  key=f"nrn_{ni}",
                                          placeholder="Jane Smith",    label_visibility="visible" if ni == 0 else "collapsed")
            nr["email"] = nr2.text_input("Email", value=nr["email"], key=f"nre_{ni}",
                                          placeholder="jane@acme.com", label_visibility="visible" if ni == 0 else "collapsed")
            if nr3.button("✕", key=f"nrr_{ni}") and len(st.session_state.new_recips) > 1:
                st.session_state.new_recips.pop(ni); st.rerun()

        ba1, ba2 = st.columns(2)
        if ba1.button("+ Add row"):
            st.session_state.new_recips.append({"name": "", "email": ""}); st.rerun()

        if ba2.button("💾 Save all", type="primary", use_container_width=True):
            saved = 0
            for nr in st.session_state.new_recips:
                if nr["name"].strip() and nr["email"].strip():
                    add_recipient(nr["name"].strip(), nr["email"].strip(), [])
                    saved += 1
            if saved:
                st.session_state.new_recips = [{"name": "", "email": ""}]
                _success_then_rerun(f"✓ {saved} recipient(s) added.")
            else:
                st.warning("Enter at least one name and email before saving.")

    # ── Schedules ─────────────────────────────────────────────────────────────
    with tab_sched:
        st.subheader("Automated send schedules")

        _all_recips = get_recipients()
        _recip_labels = [f"{r['name']} <{r['email']}>" for r in _all_recips]
        _recip_emails = {f"{r['name']} <{r['email']}>": r["email"] for r in _all_recips}

        schedules = get_schedules()
        if schedules:
            for s in schedules:
                _last = s.get("last_sent","Never")
                _sper = s.get("report_period", "Prior day")
                if _sper == "Custom":
                    _ds = s.get("date_start", "?")
                    _de = s.get("date_end", "?")
                    _period_lbl = _ds if _ds == _de else f"{_ds} → {_de}"
                else:
                    _period_lbl = _sper
                with st.expander(f"**{s['name']}** · {', '.join(s.get('days',[]))} at {s.get('send_time','')} · {_period_lbl} · Last sent: {_last}"):
                    # Show assigned recipients
                    assigned = s.get("recipients", [])
                    if assigned:
                        st.caption(f"Recipients: {', '.join(assigned)}")
                    else:
                        st.caption("No recipients assigned — all recipients will receive this.")
                    # Edit recipients inline
                    cur_labels = [lbl for lbl, em in _recip_emails.items() if em in assigned]
                    new_labels = st.multiselect("Recipients for this schedule",
                                                _recip_labels, default=cur_labels,
                                                key=f"sched_recips_{s['name']}")
                    sc1, sc2, sc3 = st.columns(3)
                    if sc1.button("💾 Save recipients", key=f"sched_save_{s['name']}", use_container_width=True):
                        new_emails = [_recip_emails[lbl] for lbl in new_labels if lbl in _recip_emails]
                        from email_engine import update_schedule_recipients
                        update_schedule_recipients(s["name"], new_emails)
                        st.toast("✓ Recipients updated", icon="✅")
                        st.rerun()
                    if sc2.button("▶ Test now", key=f"sched_test_{s['name']}", use_container_width=True):
                        _test_to = assigned or [r["email"] for r in _all_recips]
                        if not _test_to:
                            st.warning("No recipients to send to.")
                        else:
                            _gs  = st.session_state.get("goal_status", [])
                            _tgts = _cached_targets()
                            _depts = sorted({r.get("Department","") for r in _gs if r.get("Department")})
                            _per  = s.get("report_period", "Prior day")
                            if _per == "Custom":
                                _ds = date.fromisoformat(s.get("date_start", date.today().isoformat()))
                                _de = date.fromisoformat(s.get("date_end", _ds.isoformat()))
                            else:
                                _ds, _de = _resolve_period_dates(_per)
                            with st.spinner("Building and sending test report…"):
                                _xl, _subj, _body = _build_period_report(_ds, _de, "All departments", _depts, _gs, _tgts)
                                _ok, _err = send_report_email(_test_to, f"[TEST] {_subj}", _body, _xl)
                            if _ok:
                                st.success(f"Test sent to {', '.join(_test_to)}")
                                from email_engine import mark_schedule_sent as _mss2
                                _mss2(s["name"])
                            else:
                                st.error(f"Send failed: {_err}")
                    if sc3.button("🗑 Remove", key=f"sched_rm_{s['name']}", type="secondary", use_container_width=True):
                        remove_schedule(s["name"])
                        st.rerun()
            st.divider()

        st.subheader("Create new schedule")
        with st.form("add_sched_form", clear_on_submit=True):
            sname   = st.text_input("Schedule name", placeholder="e.g. Monday Morning Summary")

            # Date range: pick custom dates or a rolling period
            from datetime import timedelta as _sch_td
            _sch_today = date.today()
            speriod_mode = st.radio("Report covers",
                                     ["Custom date range", "Rolling period"],
                                     horizontal=True, key="sched_period_mode")
            if speriod_mode == "Custom date range":
                _sd1, _sd2 = st.columns(2)
                _sch_start = _sd1.date_input("Start date", value=_sch_today - _sch_td(days=1),
                                              key="sched_date_start")
                _sch_end   = _sd2.date_input("End date (same for single day)",
                                              value=_sch_start, key="sched_date_end")
                speriod = "Custom"
            else:
                speriod = st.selectbox("Report period",
                                        ["Prior day", "Prior week", "Prior month", "Current week"])
                _sch_start = _sch_end = None

            srecips = st.multiselect("Recipients", _recip_labels)
            st.caption("**Send on these days**")
            daily   = st.checkbox("Every day")
            if not daily:
                day_cols = st.columns(7)
                sel_days = [d for i,d in enumerate(DAY_NAMES)
                            if day_cols[i].checkbox(d[:3], key=f"sd_{d}")]
            else:
                sel_days = ["Daily"]
            send_time = st.time_input("Send time",
                                      value=datetime.strptime("08:00","%H:%M").time())
            subj = st.text_input("Email subject (optional)",
                                 placeholder="Weekly Performance Report")
            if st.form_submit_button("Create schedule", type="primary"):
                if not sname.strip():
                    st.warning("Give the schedule a name.")
                elif not sel_days:
                    st.warning("Select at least one day.")
                elif speriod == "Custom" and _sch_end < _sch_start:
                    st.warning("End date cannot be before start date.")
                else:
                    sel_emails = [_recip_emails[lbl] for lbl in srecips if lbl in _recip_emails]
                    _ds_str = _sch_start.isoformat() if _sch_start else ""
                    _de_str = _sch_end.isoformat() if _sch_end else ""
                    add_schedule(sname.strip(), [], sel_days,
                                 send_time.strftime("%H:%M"), subj, speriod,
                                 sel_emails, _ds_str, _de_str)
                    _success_then_rerun(f"✓ Schedule '{sname}' created.")

        # ── Scheduler log viewer ─────────────────────────────────────────────
        st.divider()
        with st.expander("📄 Scheduler log"):
            st.caption("Background email scheduler activity. Useful for debugging missed sends.")
            try:
                _log_path = _tenant_log_path("dpd_email_scheduler")
                import os as _slos
                if _slos.path.exists(_log_path):
                    _lines = open(_log_path, encoding="utf-8").readlines()
                    _recent = _lines[-30:] if len(_lines) > 30 else _lines
                    st.code("".join(reversed(_recent)), language=None)
                    if st.button("Clear log", key="clear_sched_log", type="secondary"):
                        open(_log_path, "w").close()
                        st.rerun()
                else:
                    st.info("No scheduler log yet — it will appear after the email background thread runs.")
            except Exception as _sle:
                st.warning(f"Could not read log: {_sle}")

    # ── Send Now ──────────────────────────────────────────────────────────────
    with tab_send:
        st.subheader("Send a report now")
        st.caption("Manually send a department performance report without waiting for a schedule.")

        # Load archived data if pipeline hasn't run this session
        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            _build_archived_productivity()

        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            st.info("No productivity data available yet.")
        else:
            gs         = st.session_state.goal_status
            depts      = sorted({r.get("Department","") for r in gs if r.get("Department")})
            recipients = get_recipients()

            if not recipients:
                st.warning("No recipients set up yet. Add them in the Recipients tab.")
            else:
                recip_labels = [f"{r['name']} <{r['email']}>" for r in recipients]
                chosen = st.multiselect("Send to", recip_labels,
                                        default=recip_labels[:1] if recip_labels else [])

                from datetime import timedelta as _sn_td
                _sn_today = date.today()
                dc1, dc2 = st.columns(2)
                _sn_start = dc1.date_input("Start date", value=_sn_today - _sn_td(days=1),
                                            key="send_now_start")
                # Reset end date when start changes so they stay in sync
                _prev_start = st.session_state.get("_sn_prev_start")
                if _prev_start and _sn_start != _prev_start:
                    st.session_state.pop("send_now_end", None)
                st.session_state["_sn_prev_start"] = _sn_start
                _sn_end   = dc2.date_input("End date (same as start for a single day)",
                                            value=_sn_start, key="send_now_end")
                if _sn_end < _sn_start:
                    st.warning("End date cannot be before start date.")

                dept_choice = st.selectbox("Department", ["All departments"] + depts)

                if st.button("Send report now", type="primary", use_container_width=True):
                    if not chosen:
                        st.warning("Select at least one recipient.")
                    elif _sn_end < _sn_start:
                        st.warning("Fix the date range first.")
                    else:
                        to_addrs = [r.split("<")[1].rstrip(">") for r in chosen]
                        with st.spinner("Building report…"):
                            xl_data, subj, body = _build_period_report(
                                _sn_start, _sn_end, dept_choice, depts, gs, _cached_targets())
                        with st.spinner("Sending…"):
                            ok, err = send_report_email(to_addrs, subj, body, xl_data)
                        if ok:
                            if xl_data is None:
                                st.info(f"ℹ️ No data for period — notification sent to {len(to_addrs)} recipient(s).")
                            else:
                                st.success(f"✓ Report sent to {len(to_addrs)} recipient(s).")
                        else:
                            st.error(f"Send failed: {err}")






# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

def page_settings():
    st.title("⚙️ Settings")

    tab_app, tab_sub, tab_access, tab_errors = st.tabs(["App Settings", "💳 Subscription", "🔐 Access Control", "🔴 Error Log"])

    # ── Subscription tab ──────────────────────────────────────────────────
    with tab_sub:
        st.subheader("Your Subscription")
        try:
            from database import get_subscription, get_employee_count, get_employee_limit, create_billing_portal_url
            sub = get_subscription()
            if sub:
                _plan = sub.get("plan", "unknown").capitalize()
                _status = sub.get("status", "unknown")
                _limit = sub.get("employee_limit", 0)
                _limit_str = "Unlimited" if _limit == -1 else str(_limit)
                _emp_count = get_employee_count()
                _period_end = sub.get("current_period_end", "")

                col1, col2, col3 = st.columns(3)
                col1.metric("Plan", _plan)
                col2.metric("Status", _status.replace("_", " ").title())
                col3.metric("Employees", f"{_emp_count} / {_limit_str}")

                if _period_end:
                    try:
                        from datetime import datetime
                        _pe = datetime.fromisoformat(_period_end.replace("Z", "+00:00"))
                        st.caption(f"Current period ends: {_pe.strftime('%B %d, %Y')}")
                    except Exception:
                        pass

                if sub.get("cancel_at_period_end"):
                    st.warning("Your subscription will cancel at the end of the current period.")

                st.markdown("---")
                _app_url = st.context.headers.get("Origin", "http://localhost:8501")
                _portal_url = create_billing_portal_url(return_url=_app_url)
                if _portal_url:
                    st.link_button("Manage Subscription (upgrade, cancel, update card)", _portal_url,
                                    use_container_width=True, type="primary")
                else:
                    st.info("Billing portal not available. Contact support.")
            else:
                st.info("No active subscription found.")
        except Exception as _sub_err:
            st.error(f"Could not load subscription info: {_sub_err}")

    st.caption("Productivity Planner · Powered by Supply Chain Automation Co")

    with tab_app:
        st.session_state.chart_months = st.slider("Rolling window (months)", 0, 60, st.session_state.chart_months)
        st.session_state.smart_merge  = True   # always on

        st.divider()
        st.subheader("🕐 Timezone")
        st.caption("Used for scheduled email delivery — ensures emails fire at the right local time.")
        from settings import Settings as _TzS
        _tzs    = _TzS()
        _cur_tz = _tzs.get("timezone", "")
        _tz_options = [
            # ── United States ──
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Phoenix",
            "America/Los_Angeles",
            "America/Anchorage",
            "Pacific/Honolulu",
            # ── Canada ──
            "America/Toronto",
            "America/Vancouver",
            "America/Winnipeg",
            "America/Halifax",
            # ── Europe ──
            "Europe/London",
            "Europe/Paris",
            "Europe/Berlin",
            "Europe/Madrid",
            "Europe/Rome",
            "Europe/Amsterdam",
            "Europe/Zurich",
            "Europe/Stockholm",
            "Europe/Warsaw",
            "Europe/Istanbul",
            # ── Asia / Pacific ──
            "Asia/Dubai",
            "Asia/Kolkata",
            "Asia/Bangkok",
            "Asia/Singapore",
            "Asia/Shanghai",
            "Asia/Tokyo",
            "Asia/Seoul",
            "Australia/Sydney",
            "Australia/Melbourne",
            "Pacific/Auckland",
            # ── UTC ──
            "UTC",
        ]
        _tz_display = ["(Server local time — no timezone set)"] + _tz_options
        _cur_idx    = (_tz_options.index(_cur_tz) + 1) if _cur_tz in _tz_options else 0
        _sel_tz     = st.selectbox(
            "Timezone", _tz_display, index=_cur_idx, key="settings_timezone",
        )
        if st.button("Save timezone", key="save_tz"):
            _save_val = "" if _sel_tz.startswith("(") else _sel_tz
            _tzs.set("timezone", _save_val)
            st.success(f"✓ Timezone set to '{_save_val or 'server local time'}'.")

        st.divider()
        st.info("Shift comparison and attendance tracking — coming in a future release.")

        st.divider()
        st.subheader("📋 Audit log")
        st.caption("Recent changes to goals, flags, and journal entries.")
        if st.button("View recent activity", key="view_audit"):
            try:
                import os as _os
                log_path = _tenant_log_path("dpd_audit")
                if _os.path.exists(log_path):
                    lines = open(log_path, encoding="utf-8").readlines()
                    recent = lines[-50:] if len(lines) > 50 else lines
                    st.code("".join(reversed(recent)), language=None)
                else:
                    st.info("No audit log yet — changes will appear here after goals or flags are modified.")
            except Exception as _ae:
                st.error(f"Could not read audit log: {_ae}")

        st.divider()
        st.subheader("🧹 Data cleanup")
        st.caption("Remove duplicate UPH history rows created by running the pipeline multiple times on the same data.")
        if "confirm_cleanup" not in st.session_state:
            st.session_state.confirm_cleanup = False
        if not st.session_state.confirm_cleanup:
            if st.button("Remove duplicate UPH history rows", type="secondary"):
                st.session_state.confirm_cleanup = True
                st.rerun()
        else:
            st.warning("⚠️ This will permanently delete duplicate rows. Are you sure?")
            cc1, cc2 = st.columns(2)
            if cc1.button("Yes, delete duplicates", type="primary", use_container_width=True):
                with st.spinner("Scanning and removing duplicates…"):
                    try:
                        from database import delete_duplicate_uph_history
                        deleted = delete_duplicate_uph_history()
                        _raw_cached_uph_history.clear()
                        st.session_state.confirm_cleanup = False
                        if deleted:
                            st.success(f"✓ Removed {deleted:,} duplicate row(s).")
                        else:
                            st.success("✓ No duplicates found — data is clean.")
                    except BaseException as _ce:
                        st.session_state.confirm_cleanup = False
                        try:    st.error(f"Cleanup error: {repr(_ce)[:200]}")
                        except Exception: st.error("Cleanup failed.")
                        _log_app_error("cleanup", f"Duplicate cleanup failed: {repr(_ce)[:500]}", detail=traceback.format_exc())
            if cc2.button("Cancel", use_container_width=True):
                st.session_state.confirm_cleanup = False
                st.rerun()

    with tab_access:
        st.subheader("Account")
        _uname = st.session_state.get("user_name", "")
        _urole = st.session_state.get("user_role", "member")
        if _uname:
            st.caption(f"Signed in as **{_uname}** · {_urole}")

        # ── Change password ──────────────────────────────────────────────
        st.markdown("**Change password**")
        with st.form("change_pw_form", clear_on_submit=True):
            cur_pw   = st.text_input("Current password", type="password")
            new_pw   = st.text_input("New password", type="password",
                                      placeholder="Min 6 characters")
            conf_pw  = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Update password", type="primary"):
                if not cur_pw:
                    st.warning("Enter your current password.")
                elif len(new_pw) < 6:
                    st.warning("New password must be at least 6 characters.")
                elif new_pw != conf_pw:
                    st.warning("Passwords don't match.")
                else:
                    try:
                        from database import SUPABASE_URL, SUPABASE_KEY
                        from supabase import create_client as _sc
                        _sb = _sc(SUPABASE_URL, SUPABASE_KEY)
                        sess = st.session_state.get("supabase_session", {})
                        # Re-authenticate with current password to verify identity
                        _sb.auth.sign_in_with_password({
                            "email": st.session_state.get("user_email", _uname),
                            "password": cur_pw,
                        })
                        # Set session and update password
                        _sb.auth.set_session(sess["access_token"], sess["refresh_token"])
                        _sb.auth.update_user({"password": new_pw})
                        st.success("✓ Password updated.")
                    except Exception as _cpe:
                        st.error(f"Failed: {_cpe}")
                        _log_app_error("auth", f"Password change failed: {_cpe}")

        # ── Data export (GDPR) ────────────────────────────────────────────
        st.divider()
        st.markdown("**Your data**")
        st.caption("Download a copy of all your data, or permanently delete your account.")

        if st.button("📥 Export all my data", key="gdpr_export"):
            with st.spinner("Collecting your data…"):
                try:
                    from database import export_all_tenant_data
                    _export = export_all_tenant_data()
                    if _export:
                        _json_bytes = json.dumps(_export, indent=2, default=str).encode("utf-8")
                        st.download_button(
                            "⬇️ Download JSON",
                            data=_json_bytes,
                            file_name="my_data_export.json",
                            mime="application/json",
                            key="gdpr_download",
                        )
                    else:
                        st.info("No data found for your account.")
                except Exception as _gdpr_e:
                    st.error(f"Export failed: {_gdpr_e}")
                    _log_app_error("gdpr", f"Data export failed: {_gdpr_e}", detail=traceback.format_exc())

        # ── Account deletion ─────────────────────────────────────────────
        if "confirm_delete_account" not in st.session_state:
            st.session_state.confirm_delete_account = False

        if not st.session_state.confirm_delete_account:
            if st.button("🗑️ Delete my account and all data", type="secondary", key="gdpr_delete_start"):
                st.session_state.confirm_delete_account = True
                st.rerun()
        else:
            st.error("⚠️ This will **permanently delete** your account, all employees, UPH history, goals, settings, and email config. This cannot be undone.")
            _del_confirm = st.text_input(
                "Type DELETE to confirm", key="gdpr_delete_confirm",
                placeholder="DELETE",
            )
            dc1, dc2 = st.columns(2)
            if dc1.button("Permanently delete everything", type="primary", use_container_width=True, key="gdpr_delete_go"):
                if _del_confirm == "DELETE":
                    with st.spinner("Deleting all data…"):
                        try:
                            from database import delete_all_tenant_data
                            delete_all_tenant_data()
                            _full_sign_out()
                            st.rerun()
                        except Exception as _del_e:
                            st.error(f"Deletion failed: {_del_e}")
                            _log_app_error("gdpr", f"Account deletion failed: {_del_e}", detail=traceback.format_exc())
                else:
                    st.warning("Type DELETE exactly to confirm.")
            if dc2.button("Cancel", use_container_width=True, key="gdpr_delete_cancel"):
                st.session_state.confirm_delete_account = False
                st.rerun()

        # ── Sign out ─────────────────────────────────────────────────────
        st.divider()
        if st.button("Sign out", type="secondary"):
            _full_sign_out()
            st.rerun()

    # ── Error Log tab ─────────────────────────────────────────────────────
    with tab_errors:
        st.subheader("Error Log")
        st.caption("Recent errors and warnings logged by the application. Use this to diagnose issues.")

        # Filters
        fc1, fc2, fc3 = st.columns(3)
        _err_cat = fc1.selectbox("Category", ["All", "login", "pipeline", "email", "employees",
                                               "clients", "productivity", "gdpr", "auth",
                                               "cleanup", "import", "database", "password_reset"],
                                 key="err_cat_filter")
        _err_sev = fc2.selectbox("Severity", ["All", "error", "warning", "info"], key="err_sev_filter")
        _err_limit = fc3.number_input("Show last N", min_value=10, max_value=500, value=50, step=10, key="err_limit")

        try:
            from database import get_error_reports, clear_error_reports
            _cat_arg = "" if _err_cat == "All" else _err_cat
            _sev_arg = "" if _err_sev == "All" else _err_sev
            errors = get_error_reports(limit=_err_limit, category=_cat_arg, severity=_sev_arg)

            if errors:
                st.markdown(f"**{len(errors)}** error(s) found")

                # Summary badges
                _err_count = sum(1 for e in errors if e.get("severity") == "error")
                _warn_count = sum(1 for e in errors if e.get("severity") == "warning")
                _info_count = sum(1 for e in errors if e.get("severity") == "info")
                bc1, bc2, bc3 = st.columns(3)
                bc1.metric("Errors", _err_count)
                bc2.metric("Warnings", _warn_count)
                bc3.metric("Info", _info_count)

                st.divider()

                _SEV_ICON = {"error": "🔴", "warning": "🟡", "info": "🔵"}
                for err in errors:
                    sev = err.get("severity", "error")
                    icon = _SEV_ICON.get(sev, "⚪")
                    cat = err.get("category", "unknown")
                    msg = err.get("message", "")
                    ts = err.get("created_at", "")[:19].replace("T", " ")
                    user = err.get("user_email", "")

                    with st.expander(f"{icon} **[{cat}]** {msg[:120]}{'…' if len(msg) > 120 else ''} — {ts}"):
                        st.markdown(f"**Category:** {cat}")
                        st.markdown(f"**Severity:** {sev}")
                        st.markdown(f"**Time:** {ts}")
                        if user:
                            st.markdown(f"**User:** {user}")
                        st.markdown(f"**Message:** {msg}")
                        detail = err.get("detail", "")
                        if detail:
                            st.markdown("**Detail / Stack trace:**")
                            st.code(detail, language=None)

                st.divider()
                if st.button("🗑️ Clear all error logs", type="secondary", key="clear_errors"):
                    clear_error_reports()
                    st.success("✓ Error log cleared.")
                    st.rerun()
            else:
                st.success("No errors logged. Everything is running smoothly.")
        except Exception as _err_ui_err:
            st.warning(f"Could not load error reports: {_err_ui_err}")
            st.caption("The error_reports table may not exist yet. Run the migration in migrations/001_setup.sql.")


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_csv(raw: bytes) -> tuple[list[dict], list[str]]:
    """Parse CSV bytes → (rows, headers). Delegates to data_loader."""
    hdrs, rows = _dl_parse_csv(raw)
    return rows, hdrs


def _auto_detect(headers: list) -> dict:
    """Auto-detect CSV column mapping. Delegates to data_loader."""
    return _dl_auto_detect(headers)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

# ── Access control ────────────────────────────────────────────────────────────
# Set APP_PASSWORD in Settings page. Leave blank to disable the gate.

def _check_access() -> bool:
    """Return True if the user is authenticated (or no password is set)."""
    pw = st.session_state.get("app_password_set", "")
    if not pw:
        return True   # no password configured — open access
    if st.session_state.get("authenticated"):
        return True   # already logged in this session

    st.markdown("""
    <div style="max-width:400px;margin:80px auto;background:#fff;
                border:1px solid #E2EBF4;border-radius:12px;padding:36px;">
      <div style="font-size:22px;font-weight:700;color:#0F2D52;
                  margin-bottom:24px;">📦 Productivity Planner</div>
    </div>""", unsafe_allow_html=True)

    entered = st.text_input("Password", type="password",
                             placeholder="Enter your access password",
                             key="login_input")
    if st.button("Sign in", type="primary"):
        if entered == pw:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 900  # 15 minutes


def _check_login_lockout() -> bool:
    """Return True if the user is locked out from too many failed login attempts."""
    attempts = st.session_state.get("_login_attempts", 0)
    lockout_until = st.session_state.get("_login_lockout_until", 0)
    if lockout_until and time.time() < lockout_until:
        remaining = int(lockout_until - time.time())
        mins = remaining // 60
        secs = remaining % 60
        st.error(f"Too many failed attempts. Try again in {mins}m {secs}s.")
        return True
    # Reset lockout if time has passed
    if lockout_until and time.time() >= lockout_until:
        st.session_state["_login_attempts"] = 0
        st.session_state["_login_lockout_until"] = 0
    return False


def _record_failed_login():
    """Increment failed login counter and lock out if threshold reached."""
    attempts = st.session_state.get("_login_attempts", 0) + 1
    st.session_state["_login_attempts"] = attempts
    if attempts >= _LOGIN_MAX_ATTEMPTS:
        st.session_state["_login_lockout_until"] = time.time() + _LOGIN_LOCKOUT_SECONDS
        st.error(f"Account locked for 15 minutes after {_LOGIN_MAX_ATTEMPTS} failed attempts.")
    else:
        remaining = _LOGIN_MAX_ATTEMPTS - attempts
        st.error(f"Invalid email or password. {remaining} attempt(s) remaining.")


def _login_page():
    """Supabase Auth login screen — shown when no valid session exists."""

    st.markdown("""
    <div style="max-width:400px;margin:80px auto 0;text-align:center;">
      <div style="background:#0F2D52;border-radius:12px;padding:32px 36px;">
        <div style="font-size:28px;margin-bottom:4px;">📦</div>
        <div style="font-size:20px;font-weight:700;color:#fff;letter-spacing:-.02em;">
          Productivity Planner
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Password reset mode ───────────────────────────────────────────
    if st.session_state.get("_show_reset_pw"):
        st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)

        # Sub-mode: paste reset link ────────────────────────────────────
        if st.session_state.get("_show_paste_link"):
            # If we already verified, show password form directly
            if st.session_state.get("_recovery_access_token"):
                st.subheader("Set new password")
                new_pw  = st.text_input("New password", type="password", key="paste_new_pw")
                conf_pw = st.text_input("Confirm password", type="password", key="paste_conf_pw")
                if st.button("Update password", type="primary", use_container_width=True, key="paste_update_pw"):
                    if not new_pw or len(new_pw) < 6:
                        st.warning("Password must be at least 6 characters.")
                    elif new_pw != conf_pw:
                        st.warning("Passwords do not match.")
                    else:
                        try:
                            import requests as _req
                            from database import SUPABASE_URL, SUPABASE_KEY
                            _upd_resp = _req.put(
                                f"{SUPABASE_URL}/auth/v1/user",
                                json={"password": new_pw},
                                headers={
                                    "apikey": SUPABASE_KEY,
                                    "Authorization": f"Bearer {st.session_state['_recovery_access_token']}",
                                    "Content-Type": "application/json",
                                },
                                timeout=10,
                            )
                            if _upd_resp.status_code == 200:
                                st.session_state.pop("_recovery_access_token", None)
                                st.session_state.pop("_show_paste_link", None)
                                st.session_state.pop("_show_reset_pw", None)
                                st.success("Password updated! Redirecting to sign in...")
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error(f"Failed to update password: {_upd_resp.text}")
                        except Exception as _upe:
                            st.error(f"Failed to update password: {_upe}")
                st.markdown("</div>", unsafe_allow_html=True)
                st.stop()

            # Step 1: paste the link
            st.subheader("Paste your reset link")
            st.caption("Open the reset email, copy the full link, and paste it below.")
            _paste_url = st.text_input("Reset link from email", placeholder="Paste the full URL from your email", key="paste_reset_url")
            pc1, pc2 = st.columns(2)
            if pc1.button("Continue", type="primary", use_container_width=True):
                if not _paste_url.strip():
                    st.warning("Paste the link from your reset email.")
                else:
                    from urllib.parse import parse_qs, urlparse
                    _parsed = urlparse(_paste_url.strip())
                    _at, _rt = "", ""
                    _paste_err = ""

                    # Case 1: URL fragment has access_token (redirected URL)
                    if _parsed.fragment:
                        _fp = parse_qs(_parsed.fragment)
                        _at = (_fp.get("access_token") or [""])[0]
                        _rt = (_fp.get("refresh_token") or [""])[0]

                    # Case 2: Supabase verify URL with ?token=...&type=recovery
                    if not _at and _parsed.query:
                        _qp2 = parse_qs(_parsed.query)
                        _verify_token = (_qp2.get("token") or [""])[0]
                        _verify_type  = (_qp2.get("type") or [""])[0]
                        if _verify_token and _verify_type == "recovery":
                            try:
                                import requests as _req
                                from database import SUPABASE_URL, SUPABASE_KEY
                                _vresp = _req.post(
                                    f"{SUPABASE_URL}/auth/v1/verify",
                                    json={"token_hash": _verify_token, "type": "recovery"},
                                    headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
                                    timeout=10,
                                )
                                if _vresp.status_code == 200:
                                    _vdata = _vresp.json()
                                    _at = _vdata.get("access_token", "")
                                    _rt = _vdata.get("refresh_token", "")
                                else:
                                    _paste_err = f"Supabase returned {_vresp.status_code}: {_vresp.text[:150]}"
                            except Exception as _ve:
                                _paste_err = f"Verify failed: {_ve}"
                                _log_app_error("password_reset", f"Verify API error: {_ve}")
                        elif not _verify_token:
                            _paste_err = "No token found in the URL."
                        elif _verify_type != "recovery":
                            _paste_err = f"Wrong link type: '{_verify_type}' (expected 'recovery')."

                    if _at:
                        # Store token and rerun to show password form
                        st.session_state["_recovery_access_token"] = _at
                        st.rerun()
                    else:
                        st.error(_paste_err or "Could not find a reset token in that link.")
            if pc2.button("Back", use_container_width=True):
                st.session_state["_show_paste_link"] = False
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            return

        # Sub-mode: request reset email ─────────────────────────────────
        st.subheader("Reset your password")
        st.caption("Enter your email address and we'll send you a password reset link.")
        reset_email = st.text_input("Email", placeholder="you@company.com", key="reset_email")
        rc1, rc2 = st.columns(2)
        if rc1.button("Send reset link", type="primary", use_container_width=True):
            if not reset_email.strip():
                st.warning("Enter your email address.")
            else:
                try:
                    from database import SUPABASE_URL, SUPABASE_KEY
                    from supabase import create_client as _sc
                    _sb = _sc(SUPABASE_URL, SUPABASE_KEY)
                    # Pass redirect URL so Supabase sends user back here with PKCE code
                    _redirect = st.context.headers.get("Origin", "http://localhost:8501")
                    _sb.auth.reset_password_email(reset_email.strip(), {
                        "redirect_to": _redirect,
                    })
                    st.success("Reset link sent! Check your inbox (and spam folder).")
                    st.info("After you get the email, click **\"I have a reset link\"** below and paste the link.")
                except Exception as _re:
                    # Don't reveal whether email exists
                    st.success("If that email exists, a reset link has been sent. Check your inbox (and spam folder).")
                    _log_app_error("password_reset", f"Reset request for {reset_email.strip()}: {_re}")
        st.markdown("---")
        rc3, rc4 = st.columns(2)
        if rc3.button("I have a reset link", use_container_width=True):
            st.session_state["_show_paste_link"] = True
            st.rerun()
        if rc4.button("Back to sign in", use_container_width=True):
            st.session_state["_show_reset_pw"] = False
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── Sign in mode ──────────────────────────────────────────────────
    st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)

    if _check_login_lockout():
        st.markdown("</div>", unsafe_allow_html=True)
        return

    email    = st.text_input("Email",    placeholder="you@company.com",  key="login_email")
    password = st.text_input("Password", placeholder="••••••••••••",      key="login_password", type="password")

    if st.button("Sign in", type="primary", use_container_width=True):
        if not email.strip() or not password.strip():
            st.error("Enter your email and password.")
        else:
            try:
                from database import SUPABASE_URL, SUPABASE_KEY
                from supabase import create_client as _sc
                _sb   = _sc(SUPABASE_URL, SUPABASE_KEY)
                resp  = _sb.auth.sign_in_with_password({"email": email.strip(), "password": password})

                # ── Email verification check ──────────────────────────
                _user = resp.user
                _email_confirmed = getattr(_user, "email_confirmed_at", None)
                if not _email_confirmed:
                    st.warning("Your email has not been verified. Check your inbox for a confirmation link.")
                    _log_app_error("login", f"Unverified email login attempt: {email.strip()}")
                    st.markdown("</div>", unsafe_allow_html=True)
                    return

                _at = resp.session.access_token
                _rt = resp.session.refresh_token
                # Store session tokens + expiry for auto-refresh
                st.session_state["supabase_session"] = {
                    "access_token": _at, "refresh_token": _rt,
                }
                st.session_state["_sb_token_expires_at"] = (
                    resp.session.expires_at
                    if hasattr(resp.session, "expires_at") and resp.session.expires_at
                    else time.time() + 3600
                )
                # Create a fresh client with the auth session baked in
                _sb2 = _sc(SUPABASE_URL, SUPABASE_KEY)
                _sb2.auth.set_session(_at, _rt)

                _uid = resp.user.id
                prof_resp = _sb2.table("user_profiles").select("tenant_id, role, name") \
                               .eq("id", _uid).execute()
                if prof_resp.data:
                    _prof = prof_resp.data[0]
                else:
                    # First login — provision tenant + profile
                    import uuid as _uuid
                    _new_tid = str(_uuid.uuid4())
                    _display = email.strip().split("@")[0]
                    # Use RPC to bypass RLS — falls back to direct insert
                    try:
                        _rpc_result = _sb2.rpc("provision_tenant", {
                            "p_user_id":     _uid,
                            "p_tenant_name": _display,
                            "p_user_name":   _display,
                        }).execute()
                        # RPC returns the generated tenant_id
                        if _rpc_result.data:
                            _new_tid = _rpc_result.data
                    except Exception as _rpc_err:
                        # RPC doesn't exist yet — try direct insert
                        _log_app_error("provision_tenant", f"RPC failed for {_uid}: {_rpc_err}, trying direct insert")
                        _sb2.table("tenants").insert({
                            "id": _new_tid, "name": _display,
                        }).execute()
                        _sb2.table("user_profiles").insert({
                            "id": _uid, "tenant_id": _new_tid,
                            "role": "admin", "name": _display,
                        }).execute()
                    _prof = {"tenant_id": _new_tid, "role": "admin",
                             "name": _display}
                st.session_state["tenant_id"] = _prof["tenant_id"]
                st.session_state["user_role"] = _prof.get("role", "member")
                st.session_state["user_name"]  = _prof.get("name") or email.strip()
                st.session_state["user_email"] = email.strip()
                # Clear login attempt counter on success
                st.session_state["_login_attempts"] = 0
                st.session_state["_login_lockout_until"] = 0
                _bust_cache()
                st.rerun()
            except Exception as _le:
                _record_failed_login()
                _log_app_error("login", f"Failed login for {email.strip()}: {_le}")

    # Forgot password link
    if st.button("Forgot password?", type="secondary", use_container_width=True, key="forgot_pw_btn"):
        st.session_state["_show_reset_pw"] = True
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


_SESSION_TIMEOUT_SECONDS = 3600  # 1 hour idle timeout


def _check_session_timeout():
    """Auto-logout if user has been idle for more than 1 hour."""
    now = time.time()
    last_activity = st.session_state.get("_last_activity", now)
    if now - last_activity > _SESSION_TIMEOUT_SECONDS:
        # Clear session
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        return True  # timed out
    st.session_state["_last_activity"] = now
    return False


def _verify_checkout_and_activate():
    """After Stripe checkout, verify payment and create subscription in DB."""
    import requests as _req
    from database import get_tenant_id, get_client, _get_config, PLAN_LIMITS
    _debug = []
    stripe_key = _get_config("STRIPE_SECRET_KEY")
    tid = get_tenant_id()
    if not stripe_key:
        _debug.append("no STRIPE_SECRET_KEY")
        st.session_state["_verify_debug"] = _debug
        return False
    if not tid:
        _debug.append("no tenant_id")
        st.session_state["_verify_debug"] = _debug
        return False

    _debug.append(f"tenant_id={tid[:8]}...")

    # Get the tenant's Stripe customer ID
    sb = get_client()
    try:
        t_resp = sb.table("tenants").select("stripe_customer_id").eq("id", tid).execute()
        cust_id = t_resp.data[0].get("stripe_customer_id") if t_resp.data else None
    except Exception as e:
        _debug.append(f"tenant lookup err: {e}")
        st.session_state["_verify_debug"] = _debug
        return False
    if not cust_id:
        _debug.append("no stripe_customer_id on tenant")
        st.session_state["_verify_debug"] = _debug
        return False

    _debug.append(f"stripe_customer={cust_id[:12]}...")

    # List recent subscriptions for this customer
    try:
        sub_resp = _req.get(
            "https://api.stripe.com/v1/subscriptions",
            auth=(stripe_key, ""),
            params={"customer": cust_id, "status": "active", "limit": 1},
            timeout=10,
        )
        if sub_resp.status_code != 200:
            _debug.append(f"stripe list subs: {sub_resp.status_code} {sub_resp.text[:100]}")
            st.session_state["_verify_debug"] = _debug
            return False
        subs = sub_resp.json().get("data", [])
        if not subs:
            _debug.append("no active subscriptions in Stripe")
            st.session_state["_verify_debug"] = _debug
            return False
        stripe_sub = subs[0]
    except Exception as e:
        _debug.append(f"stripe API err: {e}")
        st.session_state["_verify_debug"] = _debug
        return False

    _debug.append(f"found stripe sub {stripe_sub['id'][:16]}...")

    # Determine plan from price metadata
    plan = "starter"
    try:
        price_meta = stripe_sub["items"]["data"][0]["price"].get("metadata", {})
        plan = price_meta.get("plan", "starter")
    except Exception:
        pass
    limit = PLAN_LIMITS.get(plan, 25)
    _debug.append(f"plan={plan} limit={limit}")

    # Upsert subscription in our DB
    try:
        _sub_row = {
            "tenant_id": tid,
            "stripe_customer_id": cust_id,
            "stripe_subscription_id": stripe_sub["id"],
            "plan": plan,
            "status": "active",
            "employee_limit": limit,
            "cancel_at_period_end": stripe_sub.get("cancel_at_period_end", False),
        }
        _cpe = stripe_sub.get("current_period_end")
        if _cpe:
            from datetime import datetime, timezone
            _sub_row["current_period_end"] = datetime.fromtimestamp(_cpe, tz=timezone.utc).isoformat()
        sb.table("subscriptions").upsert(_sub_row, on_conflict="tenant_id").execute()
        _debug.append("DB upsert SUCCESS")
        st.session_state["_verify_debug"] = _debug
        return True
    except Exception as e:
        _debug.append(f"DB upsert FAILED: {e}")
        st.session_state["_verify_debug"] = _debug
        return False


def _subscription_page():
    """Show pricing page for users without an active subscription."""
    from database import (create_stripe_checkout_url, get_subscription,
                          get_employee_count, create_billing_portal_url)

    # Handle checkout return
    _qp = st.query_params
    if _qp.get("checkout") == "success":
        # Verify with Stripe and activate subscription
        with st.spinner("Activating your subscription..."):
            activated = _verify_checkout_and_activate()
        if activated:
            st.balloons()
            st.success("Welcome! Your subscription is now active.")
            st.query_params.clear()
            st.session_state.pop("_sub_active", None)
            st.session_state.pop("_checkout_url", None)
            st.session_state.pop("_checkout_plan", None)
            time.sleep(2)
            st.rerun()
        else:
            st.warning("Payment received! It may take a moment to activate. Please refresh.")
            st.query_params.clear()
    if _qp.get("checkout") == "canceled":
        st.info("Checkout canceled. Choose a plan below to get started.")
        st.query_params.clear()

    st.markdown("""
    <div style="max-width:800px;margin:40px auto 0;text-align:center;">
      <div style="background:#0F2D52;border-radius:12px;padding:32px 36px;margin-bottom:8px;">
        <div style="font-size:28px;margin-bottom:4px;">📦</div>
        <div style="font-size:22px;font-weight:700;color:#fff;letter-spacing:-.02em;">
          Productivity Planner
        </div>
      </div>
      <h2 style="margin-top:24px;color:#000;">Choose Your Plan</h2>
      <p style="color:#555;">Start optimizing your warehouse productivity today.</p>
    </div>
    """, unsafe_allow_html=True)

    # Check if user has an expired/canceled subscription
    existing_sub = get_subscription()
    if existing_sub and existing_sub.get("status") == "past_due":
        st.warning("Your payment is past due. Please update your payment method to continue.")
        _portal_url = create_billing_portal_url(
            return_url=st.context.headers.get("Origin", "http://localhost:8501")
        )
        if _portal_url:
            st.link_button("Update Payment Method", _portal_url, use_container_width=True)
        st.stop()

    # Get price IDs from secrets
    try:
        _price_starter  = st.secrets.get("STRIPE_PRICE_STARTER", "")
        _price_pro      = st.secrets.get("STRIPE_PRICE_PRO", "")
        _price_business = st.secrets.get("STRIPE_PRICE_BUSINESS", "")
    except Exception:
        _price_starter = _price_pro = _price_business = ""

    _app_url = st.context.headers.get("Origin", "http://localhost:8501")
    _success = _app_url + "/?checkout=success"
    _cancel  = _app_url + "/?checkout=canceled"

    # ── If checkout URL already generated, show just the link ────────
    if st.session_state.get("_checkout_url"):
        _plan_name = st.session_state.get("_checkout_plan", "your plan")
        st.subheader(f"Ready to checkout: {_plan_name}")
        st.link_button("Complete checkout on Stripe →", st.session_state["_checkout_url"],
                        use_container_width=True, type="primary")
        if st.button("← Choose a different plan"):
            st.session_state.pop("_checkout_url", None)
            st.session_state.pop("_checkout_plan", None)
            st.rerun()
        st.stop()

    # ── Pricing cards ──────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)

    with c1:
        st.subheader("Starter")
        st.markdown("### $49/mo")
        st.caption("For small teams getting started with productivity tracking.")
        st.markdown("---")
        st.markdown("**What's included:**")
        st.markdown("- Up to **25** employees")
        st.markdown("- CSV upload & auto-detection")
        st.markdown("- Productivity dashboard & rankings")
        st.markdown("- Department-level UPH tracking")
        st.markdown("- Weekly email reports")
        st.markdown("- Excel & PDF exports")
        if _price_starter:
            if st.button("Get Starter", use_container_width=True, key="btn_starter"):
                with st.spinner("Connecting to Stripe..."):
                    url, err = create_stripe_checkout_url(_price_starter, _success, _cancel)
                if url:
                    st.session_state["_checkout_url"] = url
                    st.session_state["_checkout_plan"] = "Starter"
                    st.rerun()
                else:
                    st.error(f"Checkout failed: {err}")

    with c2:
        st.markdown(":blue[**MOST POPULAR**]")
        st.subheader("Pro")
        st.markdown("### $149/mo")
        st.caption("For growing operations that need deeper insights and automation.")
        st.markdown("---")
        st.markdown("**Everything in Starter, plus:**")
        st.markdown("- Up to **100** employees")
        st.markdown("- Goal setting & UPH targets")
        st.markdown("- Employee trend analysis (improving/declining)")
        st.markdown("- Underperformer flagging & alerts")
        st.markdown("- Automated scheduled reports")
        st.markdown("- Custom date range reports")
        st.markdown("- Coaching notes per employee")
        if _price_pro:
            if st.button("Get Pro", type="primary", use_container_width=True, key="btn_pro"):
                with st.spinner("Connecting to Stripe..."):
                    url, err = create_stripe_checkout_url(_price_pro, _success, _cancel)
                if url:
                    st.session_state["_checkout_url"] = url
                    st.session_state["_checkout_plan"] = "Pro"
                    st.rerun()
                else:
                    st.error(f"Checkout failed: {err}")

    with c3:
        st.subheader("Business")
        st.markdown("### $299/mo")
        st.caption("For large warehouses and multi-site operations.")
        st.markdown("---")
        st.markdown("**Everything in Pro, plus:**")
        st.markdown("- **Unlimited** employees")
        st.markdown("- Order & client tracking")
        st.markdown("- Submission plans & progress")
        st.markdown("- Client trend recording")
        st.markdown("- Multi-department management")
        st.markdown("- Priority email support")
        if _price_business:
            if st.button("Get Business", use_container_width=True, key="btn_business"):
                with st.spinner("Connecting to Stripe..."):
                    url, err = create_stripe_checkout_url(_price_business, _success, _cancel)
                if url:
                    st.session_state["_checkout_url"] = url
                    st.session_state["_checkout_plan"] = "Business"
                    st.rerun()
                else:
                    st.error(f"Checkout failed: {err}")

    if not (_price_starter or _price_pro or _price_business):
        st.info("Payment system is being configured. Check back soon.")

    st.markdown("---")
    if st.button("Sign out", use_container_width=False):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


def main():
    # ── Auth gate ──────────────────────────────────────────────────────────
    if "supabase_session" not in st.session_state:
        _login_page()
        st.stop()

    # ── Idle timeout ──────────────────────────────────────────────────────
    if _check_session_timeout():
        st.info("Session expired due to inactivity. Please sign in again.")
        _login_page()
        st.stop()

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

    if not st.session_state.get("_sub_active"):
        try:
            from database import has_active_subscription
            if has_active_subscription():
                st.session_state["_sub_active"] = True
            else:
                # No local subscription — try syncing from Stripe in case
                # payment was completed but webhook/verification missed it
                _synced = False
                try:
                    _synced = _verify_checkout_and_activate()
                except Exception:
                    pass
                if _synced and has_active_subscription():
                    st.session_state["_sub_active"] = True
                else:
                    _subscription_page()
                    st.stop()
        except Exception as _sub_err:
            # If subscription check fails (table missing, etc.), let user through
            st.session_state["_sub_active"] = True

    # Start background email thread (idempotent — only creates once per process)
    _start_email_thread()

    # Check email schedules at most once per 60 seconds (not every click)
    _now = time.time()
    if _now - st.session_state.get("_last_email_check", 0) > 60:
        st.session_state["_last_email_check"] = _now
        try:
            from email_engine import get_schedules_due_now, send_report_email
            from settings    import Settings as _S
            _tz  = _S().get("timezone", "")
            _due = get_schedules_due_now(timezone=_tz)
            if _due:
                _gs      = st.session_state.get("goal_status", [])
                _targets = _cached_targets()
                _depts   = sorted({r.get("Department","") for r in _gs if r.get("Department")})
                for _sched in _due:
                    _send_to = _sched.get("recipients", [])
                    if not _send_to:
                        continue
                    _xl, _subj, _body = _build_period_report(
                        _sched.get("report_period", "Prior day"),
                        "All departments", _depts, _gs, _targets)
                    send_report_email(_send_to, _subj, _body, _xl)
                    from email_engine import mark_schedule_sent as _mss
                    _mss(_sched.get("name", ""), timezone=_tz)
        except Exception as _eml_err:
            _email_log(f"Page-render email check error: {_eml_err}")
            _log_app_error("email", f"Schedule check error: {_eml_err}", detail=traceback.format_exc())

    page = render_sidebar()
    if   page.startswith("📁"): page_import()
    elif page.startswith("👥"): page_employees()
    elif page.startswith("📈"): page_productivity()
    elif page.startswith("📧"): page_email()
    elif page.startswith("⚙️"): page_settings()


main()
