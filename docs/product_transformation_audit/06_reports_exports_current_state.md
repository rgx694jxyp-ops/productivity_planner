# 06 — Reports, Exports & Email: Current State

> Assessment of the Excel/PDF export system, scheduled email reports, and the email configuration page.

---

## Overview

The app has three output pathways:
1. **On-demand Excel exports** — `st.download_button()` on various pages
2. **On-demand PDF exports** — `exporter.py` via matplotlib (less commonly used)
3. **Scheduled email reports** — configured via `pages/email_page.py`, sent by `services/email_service.py` via SMTP

There is no in-app report viewer, no saved report templates, and no cloud file delivery (S3, Google Drive, etc.).

---

## Excel Export: `export_manager.py`

Provides raw `bytes` output for `st.download_button()`. All sheets are styled with openpyxl (navy headers, auto-fit columns).

**Entry points:**

| Function | Output | Contents |
|----------|--------|---------|
| `export_order(order_id)` | `.xlsx bytes` | Summary sheet + daily submissions + employee breakdown |
| `export_client(client_id)` | `.xlsx bytes` | Client summary + order history + trends |
| `export_employees(tenant_id)` | `.xlsx bytes` | Full roster with performance metrics |
| `export_productivity_report(...)` | `.xlsx bytes` | Period productivity: top performers, dept breakdown, weekly summary, historical |

Dependencies: `database.py` for data fetch; openpyxl for workbook construction.

---

## Excel + PDF Export: `exporter.py` (Legacy)

The older export module, still imported by some paths:

```python
export_excel(
    top_performers, dept_report, dept_trends,
    weekly_summary, history,
    settings, error_log
) -> str   # returns file path on disk (not bytes)
```

Sheets produced:
1. Top Performers
2. Department Performance
3. Department Trends (with embedded BarChart)
4. Weekly Summary (with embedded LineChart)
5. Historical Data

`export_pdf()` in the same file generates a matplotlib-based PDF with the same data. Output is written to `settings.get_output_dir()` on the server filesystem — not returned as bytes for download.

**Note:** `exporter.py` writes files to disk, which does not work correctly on stateless cloud deployments (Render ephemeral filesystem). `export_manager.py` (bytes-based) is the correct pattern.

---

## Scheduled Email Reports: `email_engine.py`

### Configuration Storage

Email config is stored per-tenant in the `tenant_email_config` Supabase table as a JSON blob. SMTP credentials (password) are **Fernet-encrypted** using a key derived from `SUPABASE_KEY`:

```python
def _get_fernet_key() -> bytes:
    digest = hashlib.sha256(SUPABASE_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)
```

**Security note:** The encryption key is derived from the Supabase API key. Rotating the Supabase key will invalidate all stored SMTP passwords unless re-entered.

### Schedule Configuration

Schedules are stored as a JSON array within `tenant_email_config.schedules`. Each schedule object:

```json
{
  "name": "Daily Summary",
  "active": true,
  "report_period": "Prior day",
  "send_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
  "send_time": "07:00",
  "recipients": ["ops@example.com"],
  "departments": ["All departments"]
}
```

`report_period` values: `"Prior day"`, `"This week"`, `"Last week"`, `"Custom"` (with `date_start`/`date_end`).

### Sending Mechanism

`email_engine.send_report_email()` uses `smtplib` + `ssl` (stdlib only, no sendgrid/mailgun):

1. Builds `MIMEMultipart` with HTML body (`email/templates.py`) + attached `.xlsx` file
2. Connects to SMTP server (SSL on port 465 or STARTTLS on 587)
3. Authenticates with decrypted credentials
4. Sends to recipient list

### Scheduling / Trigger

`services/email_service.run_scheduled_reports_for_tenant()`:
- Called from `jobs/runner.py` (batch job runner)
- Or called with `force_now=True` from the email page for manual test sends
- `get_schedules_due_now(timezone, tenant_id)` checks current time against schedule config
- `mark_schedule_sent()` updates `last_sent_at` to prevent duplicate sends

---

## Email Configuration Page: `pages/email_page.py` (405 lines)

Provides the tenant-admin UI for:
- SMTP server settings (host, port, TLS mode, username, password)
- Recipient management (add/remove email addresses)
- Schedule creation and editing
- Manual "Send now" test trigger
- Last-sent timestamp display per schedule

Plan-gated: email scheduling is available on pro/business plans.

---

## Email Templates: `email/templates.py`

Renders HTML email body. Template variables:
- Report period label
- Department filter
- Summary metrics (employee count, avg UPH, goal status distribution)
- Excel attachment is always included

No Jinja2 or template engine — HTML is assembled via Python string formatting.

---

## Productivity Report Builder: `services/productivity_service.py`

Called by `email_service` and `export_manager` to build the data payload for both email and Excel:

```python
_build_period_report(start_date, end_date, dept_filter, all_depts, targets, plan_name, tenant_id)
    → (xl_data_dict, default_subject, html_body)
```

Period resolution: `_resolve_period_dates(period)` converts "Prior day", "This week", "Last week" → `(start_date, end_date)`.

---

## Current Gaps

| Gap | Impact |
|-----|--------|
| `exporter.py` writes to disk — broken on Render ephemeral filesystem | Legacy export path is non-functional in production |
| No saved report templates | Every scheduled report uses the same fixed layout |
| No in-app report viewer | Exported data is only accessible via download or email |
| No cloud file delivery | No S3/Google Drive/Dropbox output |
| Email SMTP only — no transactional email service (SendGrid, SES, Postmark) | SMTP deliverability depends entirely on tenant's own mail server; no bounce handling |
| Fernet key tied to Supabase key | Key rotation breaks all stored SMTP passwords |
| No PDF export from web UI (only from legacy `exporter.py` CLI path) | PDF is effectively unavailable for web users |
| Reports cover productivity data only | No order fulfillment, inventory, cost, or labor cost reports |
| No report delivery to Slack, Teams, or webhook | Email is the only delivery channel |
