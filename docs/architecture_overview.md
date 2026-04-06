# Productivity Planner — Architecture Overview

**Last updated:** April 2026  
**Branch:** stabilization-architecture-pass  
**Stack:** Python · Streamlit · Supabase (PostgreSQL + Auth) · Stripe · Deno Edge Functions

---

## 1. Folder Structure

```
dpd_web/
│
├── app.py                   # Entry point, router, shared helpers (1,411 lines — NEEDS SPLIT)
├── auth.py                  # All Supabase auth: login, logout, JWT refresh, cookies
├── database.py              # Single source of truth for all DB operations (2,156 lines)
├── billing.py               # Stripe checkout + subscription verification
├── cache.py                 # @st.cache_data TTL wrappers + bust_cache()
├── ranker.py                # UPH ranking engine (ported from VBA)
├── data_loader.py           # CSV field auto-detection
├── data_processor.py        # CSV row cleaning + UPH calculation
├── ui_improvements.py       # UI components, risk math, coaching helpers (1,298 lines — NEEDS SPLIT)
├── email_engine.py          # SMTP sending, schedule mgmt, config encryption
├── error_log.py             # Row-level error logging (for import pipeline)
├── goals.py                 # UPH targets + employee flagging (DB-first, JSON fallback)
├── settings.py              # Tenant config reader (DB-backed, JSON fallback)
├── export_manager.py        # Excel/PDF export helpers
├── history_manager.py       # Archived data management
├── styles.py                # Global CSS injected via st.markdown
├── trends.py                # Trend analysis helpers
├── requirements.txt
├── .streamlit/secrets.toml  # Credentials (NOT in git)
│
├── pages/
│   ├── common.py            # Shared bootstrap + _normalize_label_text (canonical)
│   ├── supervisor.py        # Daily ops dashboard (primary daily-use screen)
│   ├── dashboard.py         # Risk overview
│   ├── import_page.py       # 3-step CSV import pipeline (2,041 lines)
│   ├── employees.py         # Employee profiles + coaching notes
│   ├── productivity.py      # UPH trends, coaching, labor cost (1,793 lines)
│   ├── shift_plan.py        # Shift planning + live checkpoints
│   ├── coaching_intel.py    # Coaching note tagging + pattern analysis
│   ├── cost_impact.py       # UPH gap → dollar cost calculator
│   ├── settings_page.py     # Account, billing, team settings
│   └── email_page.py        # Email setup UI (SMTP, schedules, send)
│
├── migrations/
│   ├── 001_setup.sql        # Core tables, RLS policies, provision_tenant() RPC
│   ├── 002_subscriptions.sql
│   ├── 003_subscription_events.sql
│   ├── 004_pending_plan_changes.sql
│   └── 005_operations_features.sql  # shift_plans, shift_checkpoints, coaching columns
│
├── supabase/
│   └── functions/stripe-webhook/index.ts  # Deno Edge Function for Stripe events
│
└── docs/
    └── architecture_overview.md  # This file
```

**Total Python:** ~17,150 lines across 27 files.

---

## 2. What Each Module Owns

| Module | Owns | Does NOT own |
|---|---|---|
| `app.py` | Startup, auth gate, nav, route dispatch, shared state helpers | Page logic (should not) |
| `auth.py` | Login UI, JWT, cookies, session restore, token refresh, lockout | Database writes other than auth |
| `database.py` | All Supabase SDK calls, multi-tenant query helpers | Business logic |
| `billing.py` | Stripe checkout verification, subscription sync | UI (calls into Streamlit minimally) |
| `cache.py` | All `@st.cache_data` TTL wrappers, `bust_cache()` | DB calls directly |
| `ranker.py` | UPH ranking algorithm, green/amber/red classification | UI rendering |
| `data_loader.py` | CSV parsing, header auto-detection | Data transformation |
| `data_processor.py` | Row cleaning, date parsing, UPH calculation from units/hours | Storage |
| `ui_improvements.py` | Risk display helpers, coaching UX, operation status, floor language | Should be broken up (see §8) |
| `email_engine.py` | SMTP send, schedule logic, config en/decryption | Scheduling triggers (should move to Supabase) |
| `goals.py` | UPH targets, employee flagging, trend analysis | UI rendering |
| `settings.py` | Tenant settings read/write (DB-backed) | Auth |
| `styles.py` | Global CSS string injection | Logic |
| `pages/common.py` | `require_db()`, `_normalize_label_text()` — shared by all pages | Page-specific logic |

---

## 3. What Each Page Does

| Page | File | Primary purpose |
|---|---|---|
| Supervisor | `pages/supervisor.py` | Daily one-screen view: dept health, top risks, trending alerts, action rail |
| Dashboard | `pages/dashboard.py` | Risk overview grid, pattern detection, breadcrumb + confidence UX |
| Import Data | `pages/import_page.py` | 3-step CSV pipeline: upload → map columns → validate + commit |
| Employees | `pages/employees.py` | Individual employee profiles, coaching note entry, performance history |
| Productivity | `pages/productivity.py` | UPH trends, period reports, coaching analysis, labor cost |
| Shift Plan | `pages/shift_plan.py` | Intra-day shift planning, live checkpoint entry, 7-day history |
| Coaching Intel | `pages/coaching_intel.py` | Auto-tag coaching notes, surface patterns, coaching ROI |
| Cost Impact | `pages/cost_impact.py` | UPH gap → dollar loss calculator, top-3 opportunity cards |
| Email Setup | `pages/email_page.py` | SMTP config, recipient management, schedule setup, send now |
| Settings | `pages/settings_page.py` | Account, team invite/management, billing/subscription, advanced |

---

## 4. Current Data Flow

```
User (browser)
    │
    ▼
Streamlit (app.py → page handler)
    │
    ├── Read path:
    │   cache.py (@st.cache_data, 2-5 min TTL, keyed by tenant_id)
    │       └── database.py (supabase-py SDK → Supabase PostgreSQL)
    │
    ├── Write path:
    │   page → database.py function → Supabase PostgreSQL
    │               └── bust_cache() clears all TTL caches
    │
    ├── Import path:
    │   CSV bytes → data_loader.py (detect headers)
    │           → data_processor.py (clean rows, calculate UPH)
    │           → database.py bulk_submit_units() (3 round-trips)
    │           → bust_cache()
    │
    └── Export path:
        database.py → export_manager.py → Excel/PDF bytes → st.download_button
```

**Multi-tenancy:** every table has `tenant_id uuid`. All queries go through:
- `_tq(query)` in `database.py` — appends `.eq("tenant_id", tid)` to every read
- `_tenant_fields()` — injects `{"tenant_id": tid}` into every insert
- Supabase Row-Level Security policies enforce the same constraint at DB level

---

## 5. Auth Flow

```
Page load
    │
    ├── restore_session_from_cookies()     # reads sb_access_token / sb_refresh_token cookies
    │       │
    │       └── if found: set supabase_session in st.session_state
    │
    ├── refresh_session_if_needed()        # JWT expires in 1h; refresh 5 min before expiry
    │
    ├── check_session_timeout()            # 8h idle timeout; clears session if exceeded
    │
    ├── if no session:
    │       └── show show_landing_page() or login_page() (from auth.py)
    │
    ├── login_page() — tabs: Sign in | Create account
    │       Sign in:   supabase.auth.sign_in_with_password()
    │                  → read user_profiles table for tenant_id + role
    │                  → if no profile: check invite code → join_tenant_by_invite()
    │                                   else: provision_tenant() RPC (creates tenant + profile)
    │                  → set_auth_cookies() (JS injection via st.components.v1.html)
    │       Signup:    supabase.auth.sign_up()
    │       Reset:     supabase.auth.reset_password_email()
    │                  → paste-link flow → verify token → update password
    │
    └── full_sign_out()
            supabase.auth.sign_out()       # server-side JWT revocation
            clear_auth_cookies()           # JS cookie deletion
            st.session_state clear
```

**Key auth state keys in `st.session_state`:**

| Key | Value |
|---|---|
| `supabase_session` | `{"access_token": str, "refresh_token": str}` |
| `tenant_id` | UUID string |
| `user_id` | Supabase auth UUID |
| `user_email` | string |
| `user_role` | `"admin"` / `"member"` |
| `user_name` | display name |
| `_sb_token_expires_at` | Unix timestamp |

---

## 6. Billing Flow

```
New user signs up
    │
    └── provision_tenant() RPC → creates tenant row with plan="starter"

User upgrades (in Settings → Billing)
    │
    └── create_billing_portal_url() → Stripe Billing Portal link
            User completes in Stripe
            Stripe fires webhook → supabase/functions/stripe-webhook/index.ts
                                → updates tenants.plan, status, period_end in DB
            User redirected back to app (?portal=return)
                → verify_checkout_and_activate() → re-reads Stripe subscription
                → syncs to DB → busts plan cache

Plan downgrades (scheduled)
    │
    └── pending_plan + pending_change_at columns on tenants table
            At next billing period: Stripe webhook fires → plan column updated

Plan enforcement in app
    │
    ├── _get_current_plan()  → reads DB, caches in session for 5 min
    ├── _has_plan(min_plan)  → rank comparison (starter=1, pro=2, business=3)
    └── _plan_gate(min_plan, feature_name) → shows upgrade prompt if below threshold
```

---

## 7. Email Flow

```
Current architecture (TEMPORARY — should be moved to Supabase scheduled function):

app.py _start_email_thread()
    → daemon thread wakes every 60s
    → _bg_send_scheduled_emails()
        → queries tenant_email_config for all tenants with schedules
        → for each: _run_scheduled_reports_for_tenant()
            → get_schedules_due_now() (compares schedule time vs now in tenant tz)
            → _build_period_report() (from pages/productivity.py)
            → send_report_email() (email_engine.py → smtplib)
            → mark_schedule_sent()

Manual send (from Email Setup page):
    email_page.py → send_report_email() → smtplib → recipient inbox

NOTE: EMAIL_SCHEDULER_ENABLED = False in app.py
      Background thread is currently disabled. Manual send still works.
      Recommended replacement: Supabase pg_cron or external cron job.
```

---

## 8. Cache Flow

```python
# cache.py — all caches keyed by tenant_id, TTL 120–300 seconds

@st.cache_data(ttl=300)
def cached_employees(_tid_key): ...        # employee list

@st.cache_data(ttl=120)
def cached_uph_history(_tid_key): ...      # all UPH history rows

@st.cache_data(ttl=300)
def cached_targets(_tid_key): ...          # dept UPH targets

@st.cache_data(ttl=120)
def cached_coaching_notes_for(_tid_key, emp_id): ...

@st.cache_data(ttl=120)
def cached_all_coaching_notes(_tid_key): ...

@st.cache_data(ttl=120)
def cached_active_flags(_tid_key): ...     # flagged employees

def bust_cache():
    st.cache_data.clear()                  # clears ALL of the above
```

`bust_cache()` is called after every write (import, coaching note, flag, goal save). Pages call `_cached_*` wrappers which prepend the current `tenant_id` as a cache key to prevent cross-tenant contamination.

---

## 9. Known Technical Debt (Priority Order)

### P1 — Structural risks

| Issue | Location | Risk |
|---|---|---|
| `app.py` is a shared dependency module | `app.py` | Every page re-imports app.py at module level; circular dependency risk; any app.py change breaks all pages |
| `ui_improvements.py` mixes concerns | `ui_improvements.py` | Risk math, coaching helpers, HTML templates, and floor-language translations all in one file |
| Email runs in Streamlit app thread | `app.py` | Unreliable in multi-worker deployments; disabled by flag as a workaround |

### P2 — Dead code removed this pass

| Removed | Was in | Lines removed |
|---|---|---|
| `_login_page()` | `settings_page.py` | ~360 lines |
| `_check_session_timeout()` | `settings_page.py` | 13 lines |
| `_check_login_lockout()` + `_record_failed_login()` | `settings_page.py` | 27 lines |
| `_check_access()` | `settings_page.py` | 29 lines |
| `_normalize_label_text()` + `_sanitize_employee_name()` | `settings_page.py` | 22 lines (canonical copy in `pages/common.py`) |
| `_parse_csv()` + `_auto_detect()` | `settings_page.py` | 11 lines (wrappers for `data_loader`, never called) |
| Dead imports `_dl_auto_detect`, `_dl_parse_csv` | `settings_page.py` | 2 lines |
| **Total** | | **~464 lines** |

### P3 — Dual-storage legacy

| Issue | Location |
|---|---|
| JSON file fallback for goals | `goals.py` — `load_goals()` / `save_goals()` |
| JSON file fallback for email config | `email_engine.py` |
| JSON file fallback for settings | `settings.py` |

These are safe to retire once all tenants are confirmed DB-migrated (run all migrations first).

### P4 — Oversized files (split candidates)

| File | Lines | Recommended split |
|---|---|---|
| `database.py` | 2,156 | Split by domain: `db/employees.py`, `db/history.py`, `db/subscriptions.py`, etc. |
| `pages/import_page.py` | 2,041 | Step functions are already isolated; extract to `services/import_service.py` |
| `pages/productivity.py` | 1,793 | Report builder + trend analysis could move to `services/` |
| `ui_improvements.py` | 1,298 | See split plan below |
| `app.py` | 1,411 | Once helpers extracted, app.py target: <200 lines |

**Recommended `ui_improvements.py` split:**
```
domain/risk.py          — _calc_risk_level, _get_all_risk_levels
domain/benchmarks.py    — human_confidence_message, detect_department_patterns
services/coaching.py    — find_coaching_impact, summarize_coaching_activity, coaching UX helpers
ui/components.py        — show_* render functions, _render_* display helpers
utils/translations.py   — translate_to_floor_language, risk_to_human_language
```

---

## 10. Planned Refactor Sequence

1. ✅ **Branch:** `stabilization-architecture-pass`
2. ✅ **Kill dead code** — done (settings_page.py cleaned, -464 lines)
3. ⬜ **Extract shared helpers from app.py** — move to `core/`, `domain/`, `utils/`
4. ⬜ **Split `ui_improvements.py`** — per §9 table above
5. ⬜ **Build service layer** — `services/import_service.py`, `services/employee_service.py`, etc.
6. ⬜ **Move email scheduler** — to Supabase pg_cron or external cron
7. ⬜ **Add tests** — ranking engine, import pipeline, plan enforcement, tenant scoping, billing
8. ⬜ **Kill JSON fallback storage** — after verifying all tenants on DB
9. ⬜ **Reduce oversized files** — `database.py`, `import_page.py`, `productivity.py`
