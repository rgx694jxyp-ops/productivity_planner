"""
email_engine.py
---------------
Manages email recipients, department assignments, and scheduled sending.

Storage: Supabase tenant_email_config table (DB-backed), with local JSON file as fallback.
Actual sending uses Python's built-in smtplib — no extra libraries needed.
"""

import json
import os
import smtplib
import ssl
import io
import csv
import base64
import hashlib
import html as _html_mod
from datetime import datetime, time
from email.mime.multipart  import MIMEMultipart
from email.mime.text       import MIMEText
from email.mime.base       import MIMEBase
from email                 import encoders

try:
    from cryptography.fernet import Fernet
    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_ENC_PREFIX = "enc:"  # marker so we know a value is encrypted


def _get_fernet_key() -> bytes:
    """Derive a Fernet key from the Supabase key (always available)."""
    from database import SUPABASE_KEY
    digest = hashlib.sha256(SUPABASE_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns 'enc:<ciphertext>' or plaintext if Fernet unavailable."""
    if not plaintext or not _HAS_FERNET:
        return plaintext
    try:
        f = Fernet(_get_fernet_key())
        token = f.encrypt(plaintext.encode()).decode()
        return f"{_ENC_PREFIX}{token}"
    except Exception:
        return plaintext


def _decrypt(value: str) -> str:
    """Decrypt an 'enc:...' string. Returns plaintext. Non-encrypted values pass through."""
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    if not _HAS_FERNET:
        return value  # can't decrypt without library
    try:
        f = Fernet(_get_fernet_key())
        token = value[len(_ENC_PREFIX):]
        return f.decrypt(token.encode()).decode()
    except Exception:
        return value  # return as-is if decryption fails (key changed, etc.)


def _email_config_file() -> str:
    """Return a tenant-specific email config path, falling back to the shared file."""
    try:
        import streamlit as st
        tid = st.session_state.get("tenant_id", "")
        if tid:
            return os.path.join(_BASE_DIR, f"dpd_email_config_{tid}.json")
    except Exception:
        pass
    return os.path.join(_BASE_DIR, "dpd_email_config.json")


# ── Config load / save (DB-first, file fallback) ────────────────────────────

def load_email_config(tenant_id: str = "") -> dict:
    """Load email config from DB, falling back to local file."""
    # Try database first
    try:
        from database import load_email_config_db
        data = load_email_config_db(tenant_id)
        if data.get("smtp") or data.get("recipients") or data.get("schedules"):
            data.setdefault("smtp", {})
            data.setdefault("recipients", [])
            data.setdefault("schedules", [])
            return data
    except Exception:
        pass
    # Fallback to file
    ecf = _email_config_file()
    if not os.path.exists(ecf):
        return _empty_config()
    try:
        with open(ecf, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("smtp", {})
        data.setdefault("recipients", [])
        data.setdefault("schedules", [])
        return data
    except (json.JSONDecodeError, IOError):
        return _empty_config()


def save_email_config(data: dict, tenant_id: str = ""):
    """Save email config to DB and local file."""
    # Save to database
    try:
        from database import save_email_config_db
        save_email_config_db(data, tenant_id)
    except Exception:
        pass
    # Also save to file as backup
    try:
        with open(_email_config_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except IOError:
        pass


def _empty_config() -> dict:
    return {
        "smtp": {
            "server":   "",
            "port":     587,
            "username": "",
            "password": "",
            "from":     "",
            "use_tls":  True,
        },
        "recipients": [],
        "schedules":  [],
    }


# ── Recipient management ──────────────────────────────────────────────────────

def add_recipient(name: str, email: str, departments: list[str]):
    """Add or update a recipient. Keyed by email address."""
    cfg = load_email_config()
    # Remove existing entry with same email if present
    cfg["recipients"] = [r for r in cfg["recipients"] if r["email"].lower() != email.lower()]
    cfg["recipients"].append({
        "name":        name.strip(),
        "email":       email.strip().lower(),
        "departments": [d.strip() for d in departments if d.strip()],
    })
    save_email_config(cfg)


def remove_recipient(email: str):
    cfg = load_email_config()
    cfg["recipients"] = [r for r in cfg["recipients"] if r["email"].lower() != email.lower()]
    save_email_config(cfg)


def get_recipients() -> list[dict]:
    return load_email_config().get("recipients", [])


def import_recipients_from_csv(csv_bytes: bytes) -> tuple[int, list[str]]:
    """
    Import recipients from a CSV file with columns: Name, Email, Departments
    Departments column can have multiple depts separated by semicolons.
    Returns (count_added, list_of_errors).
    """
    added  = 0
    errors = []
    try:
        text   = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        for i, row in enumerate(reader, start=2):
            name  = str(row.get("Name", "") or "").strip()
            email = str(row.get("Email", "") or "").strip()
            depts = str(row.get("Departments", "") or "").strip()
            if not email:
                errors.append(f"Row {i}: missing email")
                continue
            dept_list = [d.strip() for d in depts.split(";") if d.strip()]
            add_recipient(name, email, dept_list)
            added += 1
    except Exception as e:
        errors.append(str(e))
    return added, errors


# ── Schedule management ───────────────────────────────────────────────────────

def add_schedule(
    name:          str,
    departments:   list[str],
    days:          list[str],
    send_time:     str,
    subject_tpl:   str = "",
    report_period: str = "Prior day",
    recipients:    list[str] = None,
    date_start:    str = "",
    date_end:      str = "",
):
    """Add a named send schedule. If date_start/date_end are set, uses fixed dates."""
    cfg = load_email_config()
    cfg["schedules"] = [s for s in cfg["schedules"] if s["name"] != name]
    entry = {
        "name":          name,
        "departments":   departments,
        "days":          days,
        "send_time":     send_time,
        "subject_tpl":   subject_tpl or "Performance Report",
        "report_period": report_period,
        "recipients":    recipients or [],
        "active":        True,
    }
    if date_start:
        entry["date_start"] = date_start
    if date_end:
        entry["date_end"] = date_end
    cfg["schedules"].append(entry)
    save_email_config(cfg)


def update_schedule_recipients(name: str, recipients: list[str]):
    """Update the recipient list for an existing schedule."""
    cfg = load_email_config()
    for s in cfg["schedules"]:
        if s["name"] == name:
            s["recipients"] = recipients
            break
    save_email_config(cfg)


def mark_schedule_sent(name: str, timezone: str = "", tenant_id: str = ""):
    """Record when a schedule was last sent (in the configured timezone)."""
    from datetime import datetime as _dt
    if timezone:
        try:
            from zoneinfo import ZoneInfo
            now_str = _dt.now(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            now_str = _dt.now().strftime("%Y-%m-%d %H:%M")
    else:
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M")
    cfg = load_email_config(tenant_id)
    for s in cfg["schedules"]:
        if s["name"] == name:
            s["last_sent"] = now_str
            break
    save_email_config(cfg, tenant_id)


def remove_schedule(name: str):
    cfg = load_email_config()
    cfg["schedules"] = [s for s in cfg["schedules"] if s["name"] != name]
    save_email_config(cfg)


def update_schedule_last_sent(name: str, timestamp: str):
    """Record when a schedule was last sent."""
    cfg = load_email_config()
    for s in cfg["schedules"]:
        if s["name"] == name:
            s["last_sent"] = timestamp
            break
    save_email_config(cfg)


def get_schedules(tenant_id: str = "") -> list[dict]:
    return load_email_config(tenant_id).get("schedules", [])


def get_schedules_due_now(now: datetime | None = None, timezone: str = "",
                          tenant_id: str = "") -> list[dict]:
    """
    Return schedules that should fire now.
    If timezone is given (e.g. "America/Chicago"), times are compared in that zone.
    A schedule is due if its day matches, the current local time is at or after the
    configured send time, and it has not already been sent today.
    """
    if now is None:
        if timezone:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(timezone))
            except Exception:
                now = datetime.now()
        else:
            now = datetime.now()

    day_name = now.strftime("%A")   # e.g. "Monday"
    time_str = now.strftime("%H:%M")
    due      = []

    for schedule in get_schedules(tenant_id):
        if not schedule.get("active"):
            continue

        days = schedule.get("days", [])
        if "Daily" not in days and day_name not in days:
            continue

        sched_time = schedule.get("send_time", "08:00")
        if time_str < sched_time:
            continue

        last_sent = schedule.get("last_sent", "")
        if last_sent:
            try:
                last_dt = datetime.strptime(last_sent, "%Y-%m-%d %H:%M")
                _now_naive = now.replace(tzinfo=None) if now.tzinfo else now
                if last_dt.date() == _now_naive.date() and last_dt.strftime("%H:%M") >= sched_time:
                    continue
            except Exception:
                pass

        due.append(schedule)

    return due


def _add_minutes(time_str: str, minutes: int) -> str:
    try:
        h, m  = map(int, time_str.split(":"))
        total = h * 60 + m + minutes
        return f"{total // 60:02d}:{total % 60:02d}"
    except Exception:
        return time_str


# ── SMTP config ───────────────────────────────────────────────────────────────

def save_smtp_config(server: str, port: int, username: str,
                     password: str, from_addr: str, use_tls: bool):
    cfg = load_email_config()
    cfg["smtp"] = {
        "server":   server,
        "port":     port,
        "username": username,
        "password": _encrypt(password),
        "from":     from_addr or username,
        "use_tls":  use_tls,
    }
    save_email_config(cfg)


def get_smtp_config(tenant_id: str = "") -> dict:
    return load_email_config(tenant_id).get("smtp", {})


# ── Sending ───────────────────────────────────────────────────────────────────

def send_report_email(
    to_addresses: list[str],
    subject:      str,
    body_html:    str,
    attachment_bytes: bytes | None = None,
    attachment_name:  str = "report.xlsx",
    tenant_id:       str = "",
) -> tuple[bool, str]:
    """
    Send an HTML email with an optional .xlsx attachment.
    Returns (success, error_message).
    """
    smtp_cfg = get_smtp_config(tenant_id)
    server   = smtp_cfg.get("server", "")
    if not server:
        return False, "SMTP server not configured. Go to Email Settings to set it up."

    try:
        msg = MIMEMultipart("mixed")
        msg["From"]    = smtp_cfg.get("from") or smtp_cfg.get("username", "")
        msg["To"]      = ", ".join(to_addresses)
        msg["Subject"] = subject

        msg.attach(MIMEText(body_html, "html"))

        if attachment_bytes:
            part = MIMEBase("application",
                            "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part.set_payload(attachment_bytes)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
            msg.attach(part)

        port    = int(smtp_cfg.get("port", 587))
        use_tls = smtp_cfg.get("use_tls", True)
        smtp_pass = _decrypt(smtp_cfg.get("password", ""))

        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(server, port) as s:
                s.ehlo()
                s.starttls(context=context)
                s.login(smtp_cfg.get("username", ""), smtp_pass)
                s.sendmail(msg["From"], to_addresses, msg.as_string())
        else:
            with smtplib.SMTP(server, port) as s:
                s.login(smtp_cfg.get("username", ""), smtp_pass)
                s.sendmail(msg["From"], to_addresses, msg.as_string())

        return True, ""

    except Exception as e:
        # Log to DB if possible
        try:
            from database import log_error
            log_error("email", f"SMTP send failed to {', '.join(to_addresses)}: {e}",
                      detail=f"Server: {server}:{port}, TLS: {use_tls}",
                      severity="error", tenant_id=tenant_id)
        except Exception:
            pass
        return False, str(e)


def build_dept_email_body(
    dept:          str,
    top_performers: list[dict],
    goal_status:    list[dict],
    report_date:    str = "",
) -> str:
    """Build a clean HTML email body for one department."""
    if not report_date:
        report_date = datetime.now().strftime("%B %d, %Y")

    dept_rows = [r for r in goal_status if r.get("Department") == dept]
    top3      = sorted(dept_rows, key=lambda r: r.get("Average UPH", 0), reverse=True)[:3]
    below     = [r for r in dept_rows if r.get("goal_status") == "below_goal"]
    trending_down = [r for r in dept_rows if r.get("trend") == "down"]

    TREND_ICON = {"up": "↑", "down": "↓", "flat": "→", "insufficient_data": "—"}
    GOAL_COLOUR = {"on_goal": "#28a745", "below_goal": "#dc3545", "no_goal": "#6c757d"}

    _esc = _html_mod.escape
    rows_html = ""
    for r in dept_rows:
        trend_icon = TREND_ICON.get(r.get("trend", ""), "—")
        goal_col   = GOAL_COLOUR.get(r.get("goal_status", "no_goal"), "#6c757d")
        change     = r.get("change_pct", 0)
        change_str = f"+{change}%" if change > 0 else f"{change}%"
        rows_html += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">{_esc(str(r.get('Employee Name','')))}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:center;">{_esc(str(r.get('Shift','')))}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:center;font-weight:bold;">{r.get('Average UPH',0):.2f}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:center;">{r.get('Target UPH','—')}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:center;color:{goal_col};font-weight:bold;">{r.get('vs Target','—')}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:center;">{trend_icon} {change_str}</td>
        </tr>"""

    alerts = ""
    if below:
        names = ", ".join(_esc(r.get("Employee Name","")) for r in below)
        alerts += f'<p style="color:#dc3545;margin:4px 0;">⚠ Below goal: <strong>{names}</strong></p>'
    if trending_down:
        names = ", ".join(_esc(r.get("Employee Name","")) for r in trending_down)
        alerts += f'<p style="color:#e67e22;margin:4px 0;">↓ Trending down: <strong>{names}</strong></p>'
    if not below and not trending_down:
        alerts = '<p style="color:#28a745;margin:4px 0;">✓ All employees on track</p>'

    # Supervisor intelligence section
    on_goal_count = len([r for r in dept_rows if r.get("goal_status") == "on_goal"])
    total_count = len(dept_rows)
    health_pct = round((on_goal_count / total_count * 100) if total_count > 0 else 0)

    supervisor_section = f"""
    <div style="background:#fff3cd;border-left:4px solid #ffc107;padding:12px 16px;margin:12px 0;border-radius:4px;">
      <p style="margin:0 0 8px;font-weight:600;color:#856404;">📊 Department Summary</p>
      <p style="margin:4px 0;font-size:13px;color:#333;">
        <strong>{on_goal_count}/{total_count}</strong> employees meeting goals ({health_pct}% health)
      </p>
      {f'<p style="margin:4px 0;font-size:13px;color:#333;"><strong>{len(top3)} top performers:</strong> {", ".join(_esc(e.get("Employee Name","")) for e in top3)}</p>' if top3 else ''}
    </div>
    """

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px;margin:0 auto;">
      <div style="background:#1F497D;padding:20px 24px;border-radius:6px 6px 0 0;">
        <h1 style="color:white;margin:0;font-size:20px;">📊 {_esc(dept)} — Performance Report</h1>
        <p style="color:#BDD7EE;margin:4px 0 0;font-size:13px;">{report_date}</p>
      </div>
      <div style="background:#f8f9fa;padding:16px 24px;border:1px solid #e0e0e0;">
        {alerts}
      </div>
      {supervisor_section}
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr style="background:#f0f4f8;">
          <th style="padding:8px 10px;text-align:left;">Employee</th>
          <th style="padding:8px 10px;text-align:center;">Shift</th>
          <th style="padding:8px 10px;text-align:center;">Avg UPH</th>
          <th style="padding:8px 10px;text-align:center;">Target</th>
          <th style="padding:8px 10px;text-align:center;">vs Target</th>
          <th style="padding:8px 10px;text-align:center;">Trend</th>
        </tr>
        {rows_html}
      </table>
      <div style="padding:16px 24px;font-size:12px;color:#888;border-top:1px solid #e0e0e0;">
        Generated by Productivity Planner · {report_date}
      </div>
    </body></html>"""
