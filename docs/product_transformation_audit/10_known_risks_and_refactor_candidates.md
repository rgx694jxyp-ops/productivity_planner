# 10 — Known Risks & Refactor Candidates

> Prioritized risk register and refactor candidates identified during the architecture review.

---

## Risk Priority Legend

| Priority | Meaning |
|----------|---------|
| 🔴 Critical | Active risk; could cause data loss, security incident, or production outage |
| 🟠 High | Significant technical debt or architectural blocker for platform growth |
| 🟡 Medium | Meaningful improvement; not immediately blocking |
| 🟢 Low | Nice-to-have cleanup |

---

## 🔴 Critical Risks

### R1 — Thread Safety in `pages/today.py` (Async Write Pattern)

**File:** `pages/today.py`

**Description:** Completion writes are offloaded to `threading.Thread` objects. These threads access `st.session_state` directly after the Streamlit re-run cycle may have already mutated or replaced it. Streamlit's session state is not designed to be written from background threads.

**Worst-case outcome:** Silent data corruption — a write thread could overwrite session state set by a concurrent re-run, causing stale UI state or a lost card completion.

**Code excerpt:**
```python
# pages/today.py
thread = threading.Thread(
    target=_start_today_completion_write_async,
    args=(payload, tenant_id, ...)
)
thread.start()
st.session_state["_today_async_write_threads"].append(thread)
```

**Mitigation path:** Replace with a queue-based write pattern: write completions synchronously (with a 200ms user-acceptable wait) or use a proper async framework. If async is required, move results to a thread-safe queue (not session_state) and drain on the next re-run.

---

### R2 — Ephemeral Filesystem Log Loss on Render

**Files:** `services/app_logging.py`, `services/observability.py`, `logs/`

**Description:** All log files (`logs/dpd_app.jsonl`, `logs/dpd_ops_*.log`, `logs/dpd_audit_*.log`) are written to the Render dyno's local filesystem. Render dynos restart on deploy or crash, erasing all local files.

**Worst-case outcome:** Complete loss of operational history on every deploy. Audit logs and error reports in files are not durable.

**Mitigation path:** Add a Render log drain (Papertrail, Logtail, Datadog). Or write operational events directly to a Supabase `operational_events` table. `error_reports` table already provides partial persistence.

---

### R3 — Fernet Key Tied to `SUPABASE_KEY`

**File:** `email_engine.py`

**Description:** SMTP passwords are Fernet-encrypted using a key derived from `SUPABASE_KEY`. Rotating the Supabase key (security best practice) will break decryption of all stored SMTP passwords.

**Code excerpt:**
```python
def _get_fernet_key() -> bytes:
    digest = hashlib.sha256(SUPABASE_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)
```

**Worst-case outcome:** Rotating the Supabase API key silently breaks all tenant email schedules, with no user-visible error until the next scheduled send.

**Mitigation path:** Store a separate `EMAIL_ENCRYPTION_KEY` secret that can be rotated independently. Or migrate SMTP credentials to a secrets manager.

---

## 🟠 High Risks & Refactor Candidates

### R4 — `pages/today.py` Monolith (5,817 Lines)

**File:** `pages/today.py`

**Description:** The entire Today page — CSS (~500 lines), caching logic, async write management, signal recovery orchestration, 110+ rendering functions — lives in a single file. This is the #1 maintainability risk in the codebase.

**Impact:** Any change to the Today page requires navigating 5,817 lines; a bug anywhere in the file can affect unrelated rendering sections; onboarding new engineers is slow; the file is too large for most AI-assisted code tools to process in one context window.

**Refactor targets:**
- Extract `_apply_today_styles()` → `ui/today_styles.py`
- Extract cache functions + `_invalidate_today_write_caches()` → `services/today_cache_service.py`
- Extract async write logic (`_start_today_completion_write_async`, `_drain_*`) → `services/today_write_service.py`
- Extract signal recovery (`_attempt_signal_payload_recovery`, `_schedule_*`) → `services/today_init_service.py`
- Reduce `pages/today.py` to a ~500-line render orchestrator

---

### R5 — `database.py` as Sole DB Layer (2,700 Lines, ~90 Functions)

**File:** `database.py`

**Description:** The entire Supabase interaction surface — clients, orders, employees, UPH, actions, subscriptions, Stripe API calls, billing portal creation, tenant management — is in one file with ~90 functions. The `repositories/` directory is a partial, incomplete refactor.

**Impact:** Adding new data features means extending an already-massive file; circular import risks are growing; testing requires mocking a single monolithic module.

**Refactor path:** Continue migrating functions to `repositories/` by entity, then deprecate `database.py` as a direct import.

---

### R6 — `services/today_view_model_service.py` (2,486 Lines)

**File:** `services/today_view_model_service.py`

**Description:** All Today page view model builders in one file. While it is separated from the page, the file itself is too large to navigate effectively.

**Refactor path:** Split into per-section services: `today_queue_vm_service.py`, `today_strip_vm_service.py`, `today_summary_vm_service.py`, etc.

---

### R7 — Dual Follow-up Systems (No Migration Path)

**Files:** `followup_manager.py`, `services/action_lifecycle_service.py`

**Description:** `coaching_followups` (legacy, migration 007) and `action_events` (current, migration 011) both track follow-ups. Due-today badge counts may differ between the two systems. No cleanup plan or data migration has been defined.

**Impact:** UI inconsistency; potential for phantom "due today" counts from the legacy table; developers must know which system to write to.

**Mitigation path:** Migrate remaining uses of `coaching_followups` to `action_events`; backfill historical data if needed; drop the `coaching_followups` table.

---

### R8 — Legacy Disk-Based Export in `exporter.py`

**File:** `exporter.py`

**Description:** `export_excel()` writes to `settings.get_output_dir()` on disk and returns a file path. On Render's ephemeral filesystem, this path is not downloadable by the user and is erased on restart.

**Impact:** The PDF export and any caller still using the old `exporter.py` path is silently non-functional in production.

**Mitigation path:** Remove `exporter.py` callers and consolidate on `export_manager.py` (bytes-based). Add a `test_export_manager.py` to prevent regression.

---

### R9 — No Coverage Tooling or CI

**Description:** `pytest-cov` is not in `requirements.txt`. No `.coveragerc`. No CI configuration (GitHub Actions, etc.). Coverage is unknown.

**Impact:** 683 tests exist but their coverage of the ~15,000 lines of production code is unmeasured. Regressions in uncovered areas go undetected.

**Mitigation path:** Add `pytest-cov` to `requirements.txt`; add `.coveragerc`; add a GitHub Actions workflow that runs tests + coverage on every PR.

---

### R10 — No `external_id` / `source_system` Columns on Core Tables

**Tables:** `employees`, `orders`, `activity_records`

**Description:** When WMS/ERP integrations are added, imported records will need to store the originating system's ID. No schema slots exist for this today.

**Impact:** Integration work will require schema migrations on the highest-write tables (`activity_records` may grow to millions of rows), which is high-risk without a migration strategy.

**Mitigation path:** Add `external_id text`, `source_system text` to `employees`, `orders`, and `activity_records` in a forward-looking migration now, before volume grows.

---

## 🟡 Medium Risks

### R11 — Cookie-Based Session Management (JavaScript Injection)

**File:** `auth.py` (`set_auth_cookies()`, `clear_auth_cookies()`)

**Description:** Auth tokens are stored in browser cookies via injected JavaScript `<script>` tags. This is a common Streamlit workaround but is fragile across browser security models (strict CSP, Safari ITP, incognito mode).

**Mitigation path:** For a re-platform, move to a proper session management layer (e.g., FastAPI + httpOnly cookies, or Supabase's server-side auth).

---

### R12 — No Health Check Endpoint

**Description:** No `/health` or `/ping` route exists for load balancer health checks or uptime monitoring.

**Mitigation path:** Streamlit doesn't natively support HTTP routes; add a lightweight FastAPI sidecar or configure Render's health check to validate the Streamlit homepage HTTP 200.

---

### R13 — `action_state_service.py` at 1,095 Lines

**File:** `services/action_state_service.py`

**Description:** The action state machine, bulk lookup, and state-read logic are all in one service. Growing the action workflow (new states, new trigger sources) will make this harder to maintain.

---

## 🟢 Low Risk / Cleanup

### R14 — Multiple `dpd_email_config_*.json` and `dpd_goals_*.json` Files in Root

**Files:** `dpd_email_config_*.json`, `dpd_goals_*.json` (7 files in root)

**Description:** These appear to be per-tenant config snapshots or developer test artifacts. They may contain real SMTP credentials if they were exported from a live tenant.

**Risk:** If committed to git, credentials could be exposed in repository history.

**Immediate action:** Confirm whether these files contain real SMTP passwords. Add `dpd_email_config_*.json` and `dpd_goals_*.json` to `.gitignore`. Rotate any credentials found.

---

### R15 — `.streamlit/secrets.toml` May Be Present in Repo

**Description:** `.streamlit/secrets.toml` contains Supabase URL/key and Stripe key. If this file is not in `.gitignore`, it may have been committed to the repository.

**Immediate action:** Verify `.gitignore` includes `.streamlit/secrets.toml`. Run `git log --all --full-history -- .streamlit/secrets.toml` to check history.

---

## Risk Summary Matrix

| Risk | Priority | File(s) | Effort to Fix |
|------|----------|---------|--------------|
| R1 Thread safety (async writes) | 🔴 Critical | pages/today.py | Medium |
| R2 Ephemeral log loss | 🔴 Critical | logs/, observability.py | Low |
| R3 Fernet key = Supabase key | 🔴 Critical | email_engine.py | Low |
| R4 today.py monolith | 🟠 High | pages/today.py | High |
| R5 database.py monolith | 🟠 High | database.py | High |
| R6 today_view_model_service.py size | 🟠 High | services/ | Medium |
| R7 Dual follow-up systems | 🟠 High | followup_manager.py | Medium |
| R8 Disk-based export | 🟠 High | exporter.py | Low |
| R9 No coverage tooling / CI | 🟠 High | requirements.txt | Low |
| R10 No external_id columns | 🟠 High | migrations/ | Low (schema) |
| R11 Cookie JS injection | 🟡 Medium | auth.py | High (re-platform) |
| R12 No health check | 🟡 Medium | — | Low |
| R13 action_state_service.py size | 🟡 Medium | services/ | Medium |
| R14 JSON files in root with credentials | 🟢 Low | root/*.json | Immediate |
| R15 secrets.toml in git | 🟢 Low | .gitignore | Immediate |
