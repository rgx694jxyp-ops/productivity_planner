# 01 — Current Architecture

> End-to-end architecture description of the dpd_web application as of this audit.

---

## Runtime Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| UI Framework | Streamlit ≥1.30 | Python-first, server-side rendering, no SPA |
| Database | Supabase (PostgreSQL) | Hosted Postgres + RLS + auth + edge functions |
| Auth | Supabase Auth (JWT) | Cookie-based session handoff via JS injection |
| Billing | Stripe | Subscription via Checkout; webhook via Supabase Edge Function |
| File I/O | openpyxl, pandas | Excel import/export; no S3 or object store |
| Email | Python smtplib | SMTP with Fernet-encrypted credentials stored in DB |
| Deployment | Render (inferred from `RENDER_EXTERNAL_URL` env var) | Single dyno; Procfile present |

---

## Boot Sequence

```
streamlit run app.py
    └── app.main()
            ├── core.runtime.init_runtime()          # st handle, logging init
            ├── core.session.init_session_state()    # sets SESSION_DEFAULTS
            ├── auth checks (auth.py)                # cookie → supabase JWT → tenant_id
            ├── billing checks (billing.py)          # verify_checkout_and_activate()
            ├── core.navigation.render_app_navigation()   # sidebar + subscription banner
            └── core.page_router.dispatch_page(page)      # route to page handler
```

The entire app executes on every Streamlit re-run (user action or auto-refresh). There is no persistent background server process; threads are spawned from `pages/today.py` for async DB writes only.

---

## Routing

`core/page_router.py` (`dispatch_page`) maps string keys to handler functions via `@lru_cache`:

| Page Key | Handler | File |
|----------|---------|------|
| `today` | `page_today()` | pages/today.py |
| `supervisor` | `page_today()` | pages/today.py (alias) |
| `team` | `page_team()` | pages/team.py |
| `import` | `page_import()` | pages/import_page.py |
| `employees` | *(employee detail)* | pages/employees.py |
| `dashboard` | `page_dashboard()` | pages/dashboard.py |
| `productivity` | `page_productivity()` | pages/productivity.py |
| `shift_plan` | `page_shift_plan()` | pages/shift_plan.py |
| `coaching_intel` | `page_coaching_intel()` | pages/coaching_intel.py |
| `cost_impact` | `page_cost_impact()` | pages/cost_impact.py |
| `email` | `page_email()` | pages/email_page.py |
| `settings` | `page_settings()` | pages/settings_page.py |

Navigation is stored in `st.session_state["_current_page_key"]`. Sidebar is rendered by `core/navigation.py`.

---

## Multi-Tenant Architecture

```
auth.users (Supabase managed)
    └── user_profiles (tenant_id, role)
            └── tenants (id, name)
                    └── ALL data tables (tenant_id FK + RLS)
```

- Every data table has `tenant_id UUID NOT NULL` FK referencing `tenants`.
- Row-Level Security uses a Postgres function `get_my_tenant_id()` which reads the JWT claim, enforced on every Supabase client query.
- Roles: `viewer` (read-only), `manager` (read + write data), `admin` (all + billing + settings). Legacy `member` alias → `manager` via `access_control_service._LEGACY_ALIASES`.
- `database.py` exposes `get_tenant_id()` (reads from `st.session_state`) and `get_user_id()`.
- `repositories/_common.py` provides `get_client()` and `tenant_query()` used by all repository modules.

---

## Session & Auth State

Key session state keys set by `core/session.py` `SESSION_DEFAULTS`:

| Key | Purpose |
|-----|---------|
| `_current_page_key` | Active page (default: `"today"`) |
| `uploaded_sessions` | In-flight CSV import rows |
| `submission_plan` | Import confirmation state |
| `mapping` / `mapping_ready` | Column mapping state |
| `pipeline_done` | Import pipeline completion flag |
| `supabase_session` | JWT access/refresh token dict |

`auth.py` constants:
- `SESSION_TIMEOUT_SECONDS = 28800` (8 hours)
- `MAX_SESSION_LIFETIME_SECONDS = 43200` (12 hours)
- `LOGIN_MAX_ATTEMPTS = 5`; `LOGIN_LOCKOUT_SECONDS = 900` (15 min lockout)

Auth redirect URL resolved from env vars in priority order: `AUTH_REDIRECT_URL` → `APP_BASE_URL` → `PUBLIC_APP_URL` → `RENDER_EXTERNAL_URL`.

---

## Service Layer Architecture

The service layer sits between pages and the DB. It is organized into functional clusters:

**Signal pipeline services** (core product value path):
```
activity_records_service  →  daily_snapshot_service  →  daily_signals_service
                                                               ↓
                                           signal_interpretation_service
                                           signal_formatting_service
                                           signal_quality_service
                                           signal_traceability_service
                                           display_signal_factory
                                           attention_scoring_service
                                                               ↓
                                           today_view_model_service  →  pages/today.py
```

**Action/workflow services:**
```
action_service  →  action_lifecycle_service  →  action_state_service
action_query_service, action_metrics_service, action_recommendation_service
follow_through_service, exception_tracking_service
```

**Import services:**
```
import_service  →  import_pipeline/orchestrator  →  parser → mapper → validator → importer
import_quality_service, import_trust_service, import_date_service
```

**Cross-cutting services:**
- `app_logging.py` — structured JSONL logging with sensitive-key redaction
- `observability.py` — `log_app_error()`, `log_operational_event()`
- `perf_profile.py` — `PerfProfile` context manager with stage timing
- `billing_service.py` — `get_subscription_entitlement()` unified access truth
- `plan_service.py` — plan limit enforcement (`PLAN_RANKS`, `PLAN_FEATURES`)
- `access_control_service.py` — `require_write()`, `require_admin()`

---

## Repository Layer

`repositories/` provides thin typed wrappers over the Supabase Python client. Each file mirrors a logical entity group:

| Repository | Entity |
|-----------|--------|
| `_common.py` | Supabase client factory, `tenant_query()` |
| `actions_repo.py` | `actions` table |
| `action_events_repo.py` | `action_events` table |
| `activity_records_repo.py` | `activity_records` table |
| `billing_repo.py` | `subscriptions` table |
| `daily_employee_snapshots_repo.py` | `daily_employee_snapshots` table |
| `daily_signals_repo.py` | `daily_signals` table |
| `employees_repo.py` | `employees` table |
| `import_repo.py` | `uploaded_files` + import job tables |
| `operational_exceptions_repo.py` | `operational_exceptions` table |
| `tenant_repo.py` | `tenants`, `user_profiles` |

**Note:** `database.py` (2,700 lines, ~90 functions) predates the repository pattern and is still the primary DB access point for many modules. The repositories are a partial refactor that is not yet complete.

---

## Domain Model

`domain/` holds canonical domain objects passed between services and pages:

| Object | File | Purpose |
|--------|------|---------|
| `DisplaySignal` | display_signal.py | View-ready signal: type, label, value, baseline, confidence, flags |
| `InsightCard` | insight_card_contract.py | Today queue card contract |
| `Action` | actions.py | Workflow action domain object |
| `ActivityRecord` | activity_records.py | Normalized import row |
| `OperationalException` | operational_exceptions.py | Operating context exception |
| `Risk` / `RiskScore` | risk.py, risk_scoring.py | Employee risk assessment |

---

## Caching Strategy

Three caching mechanisms are in use:

1. **`@st.cache_data` with TTL** — used in `pages/today.py` for signal payloads, action state, signal status map. TTL = `_READ_CACHE_TTL_SECONDS = 300` (5 minutes). Cache keyed by tenant_id + date.
2. **`core/billing_cache.py`** — TTL-based in-process dict cache for billing entitlement. TTL from `BILLING_CACHE_TTL_SECONDS`.
3. **`@lru_cache`** — used in `core/page_router.py` for handler dict; prevents repeated dict construction.

Cache invalidation after write operations is handled by `_invalidate_today_write_caches()` in `pages/today.py`, which calls `st.cache_data.clear()` selectively.

---

## Async Write Pattern

`pages/today.py` spawns `threading.Thread` for card completion writes to avoid blocking the UI re-render:

```python
# Simplified from pages/today.py
thread = threading.Thread(target=_start_today_completion_write_async, ...)
thread.start()
st.session_state["_today_async_write_threads"].append(thread)
# On next rerun:
_drain_today_async_completion_results()  # checks thread.done + surfaces errors
```

**Risk:** Streamlit `st.session_state` is not thread-safe. If a Streamlit re-run occurs while a thread holds a reference to session state objects, race conditions are possible. See file 10 (risks) for full discussion.

---

## Secrets & Configuration

Credentials are read by `database._get_config()` from:
1. Environment variables (checked first)
2. `.streamlit/secrets.toml` (Streamlit managed)

Required secrets:
- `SUPABASE_URL`, `SUPABASE_KEY`
- `STRIPE_SECRET_KEY`

Email SMTP credentials are stored **encrypted** in the `tenant_email_config` Supabase table, encrypted with Fernet using a key derived from `SUPABASE_KEY` via SHA-256. This means losing the Supabase key also invalidates all stored SMTP passwords.

`database.py` raises `RuntimeError` on startup if `SUPABASE_URL` or `SUPABASE_KEY` is missing — providing a clear failure message rather than silent misbehavior.

---

## What Is Not Present

- No REST API or GraphQL layer — the app is UI-only
- No background worker process — email/signal compute is triggered on-demand or via cron shell scripts
- No WebSocket or real-time push — auto-refresh polls on a `_TODAY_AUTO_REFRESH_MIN_SECONDS = 60` timer via Streamlit re-run
- No object storage (S3/GCS) — uploads are parsed in memory and discarded
- No CDN or static asset pipeline
- No container definition (Docker/Compose)
