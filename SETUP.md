# Productivity Planner — Setup Guide

## Prerequisites

- Python 3.10+
- A Supabase project (free tier works)

## 1. Install dependencies

```bash
pip install streamlit supabase openpyxl matplotlib pandas
```

## 2. Create your Supabase project

1. Go to [supabase.com](https://supabase.com) and create a new project
2. Note your **Project URL** and **anon/public API key** from Settings > API

## 3. Run the database migrations

1. In your Supabase dashboard, go to **SQL Editor**
2. Open `migrations/001_setup.sql` from this repo
3. Paste the entire contents into the SQL Editor and click **Run**
4. Open `migrations/002_subscriptions.sql` from this repo
5. Paste the entire contents into the SQL Editor and click **Run**

This creates all tables, enables row-level security, sets up tenant isolation policies, provisions subscription storage, and creates the `provision_tenant` function for automatic user onboarding.

## 4. Configure credentials

**Option A — Environment variables** (recommended):
```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-anon-key-here"
```

**Option B — Streamlit secrets** (for Streamlit Cloud):

Create `.streamlit/secrets.toml`:
```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-anon-key-here"
```

**Option C — `.env` file** (for local dev):

Copy `.env.example` to `.env` and fill in your values. Use a library like `python-dotenv` to load them.

## 5. Configure Supabase Auth

1. In Supabase dashboard, go to **Authentication > Providers**
2. Make sure **Email** provider is enabled
3. Go to **Authentication > URL Configuration**
4. Set **Site URL** to where your app runs (e.g., `http://localhost:8501`)

## 6. Create your first user

1. In Supabase dashboard, go to **Authentication > Users**
2. Click **Add user > Create new user**
3. Enter an email and password
4. Click **Create user** and confirm the email if required

## 7. Run the app

```bash
streamlit run app.py
```

## 8. Reliable Scheduled Emails (Cross-platform Worker)

For guaranteed schedule delivery (even with no active browser/session), run the standalone worker.

Worker script:
```bash
python3 scripts/email_scheduler_worker.py --once
python3 scripts/email_scheduler_worker.py --interval 60
```

### macOS (launchd)
```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-anon-key-here"
./scripts/install_scheduler_launchd.sh
```

### Linux (systemd)
```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-anon-key-here"
sudo ./scripts/install_scheduler_systemd.sh
```

### Windows (Task Scheduler)
Open PowerShell in the repo root and run:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_scheduler_windows.ps1 -SupabaseUrl "https://your-project.supabase.co" -SupabaseKey "your-anon-key-here"
```

Log files are written under `logs/`.

Sign in with the email/password you created. On first login, the app automatically:
- Creates a tenant (organization) for you
- Sets you as admin
- Gives you a completely isolated workspace

## How multi-tenancy works

- Every user gets their own **tenant** (organization)
- All data (employees, UPH history, goals, email config, settings) is isolated per tenant
- Data is stored in Supabase with row-level security — users can only see their own tenant's data
- Goals, settings, and email configuration are stored in the database (not local files), so they persist across deployments

## Adding more users to the same tenant

Currently, each new login creates a new tenant. To add a user to an **existing** tenant:

1. Create the user in Supabase Authentication
2. In SQL Editor, run:
```sql
INSERT INTO user_profiles (id, tenant_id, role, name)
VALUES (
  'the-user-auth-uuid',
  'the-existing-tenant-uuid',
  'member',
  'Their Name'
);
```

## Deploying to Streamlit Cloud

1. Push your code to GitHub (make sure `.env` and `dpd_*.json` are in `.gitignore`)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repo and select `app.py`
4. Add your `SUPABASE_URL` and `SUPABASE_KEY` in **Advanced settings > Secrets**
5. Deploy

## File structure

```
app.py              — Main Streamlit UI
database.py         — All Supabase interactions
data_loader.py      — CSV parsing and auto-detect
data_processor.py   — Row cleaning and UPH calculation
history_manager.py  — Historical data dedup/merge
ranker.py           — Employee UPH ranking
trends.py           — Monthly/weekly trend aggregation
goals.py            — Department targets and employee flagging
settings.py         — User preferences
email_engine.py     — Email recipients, schedules, SMTP sending
exporter.py         — Excel/PDF export
charts.py           — Matplotlib charts
error_log.py        — Pipeline error logging
migrations/         — SQL setup scripts for Supabase
```
