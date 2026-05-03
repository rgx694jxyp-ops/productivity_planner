# 11 — Recommended Next Steps

> Phased transformation plan for evolving dpd_web into a professional, sellable "daily warehouse operating clarity" platform.

---

## Guiding Principles

Before the step list: three constraints that must hold throughout any transformation.

1. **Decision layer only.** The platform surfaces what is happening and why. It does not prescribe management actions. Copy must remain descriptive: "surfaced because," "data suggests," "compared with." No "you should," "coach," "take action," or "fix."
2. **Non-breaking evolution.** Each phase must leave a running, deployable app at completion. No big-bang rewrites.
3. **Signal quality is the product.** Every integration, refactor, and UI change should improve the accuracy, confidence, and interpretability of the signals surfaced — not add features for their own sake.

---

## Phase 0 — Immediate / Pre-Review (1–2 weeks)

These are security and stability actions that should be taken before investor or partner demos.

| # | Action | Risk Addressed | Effort |
|---|--------|---------------|--------|
| 0.1 | Audit `dpd_email_config_*.json` and `dpd_goals_*.json` files in root for live SMTP credentials; rotate if found; add to `.gitignore` | R14 | Hours |
| 0.2 | Verify `.streamlit/secrets.toml` is in `.gitignore` and not in git history | R15 | Hours |
| 0.3 | Add `EMAIL_ENCRYPTION_KEY` as a separate secret; migrate Fernet key derivation away from `SUPABASE_KEY` | R3 | 1 day |
| 0.4 | Add a Render log drain (Papertrail or Logtail) so operational logs survive dyno restarts | R2 | 1 day |
| 0.5 | Remove all callers of `exporter.py` disk-write path; consolidate on `export_manager.py` (bytes-based) | R8 | 1 day |
| 0.6 | Add `pytest-cov` to `requirements.txt`; add `.coveragerc`; add a GitHub Actions CI workflow | R9 | 1 day |
| 0.7 | Add `external_id text`, `source_system text` columns to `employees`, `orders`, `activity_records` (migration 020) | R10 | 1 day |

---

## Phase 1 — Architecture Stabilization (4–8 weeks)

Reduce the two biggest monoliths before adding new features. These changes are internal and invisible to users.

### 1.1 — Decompose `pages/today.py`

**Target:** Reduce from 5,817 lines to ~500-line render orchestrator.

Extraction plan:
```
_apply_today_styles()          → ui/today_styles.py
_cached_today_* functions      → services/today_cache_service.py
_start_today_completion_write_async
_drain_today_async_completion_results  → services/today_write_service.py
_attempt_signal_payload_recovery
_schedule_today_snapshot_recompute_async → services/today_init_service.py
```

**Safety net:** The existing 30+ `test_today_*.py` files provide regression coverage. Run them after each extraction step.

### 1.2 — Replace Thread-Based Async Writes

**Target:** Eliminate `threading.Thread` write pattern from `pages/today.py`.

Options (pick one):
- **Option A (simple):** Make completion writes synchronous; add a `st.spinner` for the ~200ms write latency. Acceptable UX for a B2B desktop product.
- **Option B (proper async):** Use a thread-safe `queue.Queue` to pass write payloads to a background thread; drain results into a Supabase-backed write log rather than `session_state`.

### 1.3 — Consolidate Dual Follow-up Systems

1. Audit all calls to `followup_manager.py` and `coaching_followups` table
2. Write migration script to port historical `coaching_followups` rows to `action_events`
3. Update all callers to use `action_events`
4. Drop `coaching_followups` table in migration 021

### 1.4 — Continue `repositories/` Migration

Move remaining direct `database.py` calls for `employees`, `orders`, `unit_submissions`, `coaching_notes`, `shifts` into typed repository files. Deprecate those sections of `database.py` progressively.

---

## Phase 2 — Data Ingestion Expansion (8–16 weeks)

The platform's signal quality is bounded by the data it can receive. Phase 2 expands beyond manual CSV upload.

### 2.1 — Add an Ingestion API

Build a lightweight FastAPI (or Supabase Edge Function) ingestion endpoint:

```
POST /api/v1/ingest/productivity
POST /api/v1/ingest/orders
POST /api/v1/ingest/shifts
```

- JWT-authenticated (reuse Supabase tokens)
- Tenant-scoped (tenant_id from JWT claim)
- Accepts JSON payloads matching the existing `activity_records` / `orders` schema
- Returns job_id for async status polling

This is the prerequisite for all WMS/ERP/TMS connectors.

### 2.2 — Add SFTP / Folder Watch Ingestion

For customers who cannot implement API-based feeds:
- Render-compatible: use a scheduled job that polls an SFTP path or S3 prefix
- Reuse the existing `import_pipeline/` package as the parsing/validation layer
- Add `source_system = 'sftp'` to `activity_records`

### 2.3 — First Integration Adapter

Pick the highest-demand integration based on customer interviews. Likely candidates:
- **Fishbowl / DEAR / inFlow** (SMB WMS common in target segment)
- **ShipStation** (common in e-commerce fulfillment)
- **ADP / Paychex** (labor hours from payroll)

Build a thin adapter that: authenticates with the third-party API → pulls daily productivity/labor records → maps to `activity_records` schema → calls the ingestion API.

### 2.4 — Extend Schema for Order Fulfillment Clarity

Add to `orders` table:
- `sku_count int`, `total_picks int`, `total_packs int`
- `carrier text`, `ship_date date`, `expected_ship_date date`
- `external_id text` (already added in Phase 0.7)

This enables order-level signals: "Order X is 60% complete with 2 days to ship date."

---

## Phase 3 — Platform Hardening (12–24 weeks)

For institutional buyers and channel partnerships, the platform needs enterprise-grade infrastructure.

### 3.1 — SSO / Enterprise Auth

Add SAML 2.0 / OIDC login via Supabase Auth providers (Google Workspace, Microsoft Entra). Remove JavaScript cookie injection; use Supabase's server-side session management instead.

### 3.2 — REST API for Partner Integrations

Expose a documented REST API that partners (WMS vendors, SIs) can build against:
- `GET /api/v1/signals` — today's signals for a tenant
- `GET /api/v1/employees/{id}/snapshots` — historical snapshots
- `POST /api/v1/actions` — create an action from an external system
- API keys per tenant stored in a `api_keys` table (hashed)

### 3.3 — Multi-Region / Data Residency

Supabase supports multiple regions. For EU customers, configure a separate Supabase project per data residency zone. Add `data_region` to `tenants` table.

### 3.4 — Webhook Delivery for Outbound Events

Allow customers to register webhook URLs for events:
- `signal.created` — new signal computed for today
- `action.resolved` — action marked complete
- `import.completed` — CSV import finished

Add `webhook_subscriptions` table; add retry/dead-letter queue.

### 3.5 — Centralized Observability

- Add Datadog or Sentry for error aggregation + alerting
- Add `operational_events` Supabase table as persistent event store
- Add structured APM spans for the signal compute pipeline
- Add a `/health` endpoint (FastAPI sidecar or Supabase Edge Function)

---

## Phase 4 — Product Surface Expansion (ongoing)

With a stable architecture and expanding data inputs, new product surfaces become viable.

### 4.1 — Shift / Labor Planning Surface

The `shift_plans` and `shift_checkpoints` tables exist but the shift plan page is minimal. A full shift clarity surface would show:
- Planned vs. actual headcount by department + shift
- UPH target attainment against scheduled hours
- Labor cost estimate vs. actual (requires hourly rate data)

### 4.2 — Order Fulfillment Clarity Surface

Once order schema is extended (Phase 2.4):
- "Orders at risk by ship date" view
- Per-order productivity breakdown
- Department-to-order assignment visibility

### 4.3 — Mobile-Optimized Today Surface

The current Today page is Streamlit desktop. A mobile-first Today view (React Native or PWA) would let supervisors check signals on the floor. The API layer from Phase 3.2 provides the data endpoint.

### 4.4 — Coaching Intel Expansion (Pro/Business)

The `pages/coaching_intel.py` page and `services/coaching_intel_service.py` are already built but plan-gated. Expand with:
- Pattern frequency analysis across notes
- Signal history per employee (multi-week trend)
- Cross-employee pattern surfacing ("3 employees in Dept B show the same trend")

All copy must remain descriptive, not prescriptive — consistent with the non-directive product posture.

---

## Transformation Readiness Summary

| Capability | Current State | Platform-Ready State |
|------------|--------------|---------------------|
| Data ingestion | Manual CSV only | API + SFTP + connectors |
| Auth | Email/password + JS cookies | SSO + server-side sessions |
| Integrations | None | WMS, ERP, TMS adapters |
| Observability | Local file logs | Persistent, aggregated, alerted |
| API surface | None | REST API + webhooks |
| Mobile | Not supported | Mobile-optimized Today view |
| Multi-region | Single region | Per-tenant data residency |
| CI / coverage | Not configured | CI on every PR, coverage tracked |
| Monolith risk | today.py (5,817L), database.py (2,700L) | Decomposed, tested, bounded |

The foundation — multi-tenant RLS, signal pipeline, action workflow, Stripe billing, structured logging — is solid. The transformation is primarily about expanding the data perimeter, hardening the infrastructure, and decomposing the two large monolith files before they become blockers.
