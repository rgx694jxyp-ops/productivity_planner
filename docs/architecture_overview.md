# Pulse Ops — Architecture Overview

Last updated: 2026-04-10
Branch: stabilization-architecture-pass
Stack: Python, Streamlit, Supabase (Postgres/Auth), Stripe, Supabase Edge Functions (Deno)

## Purpose

This document is the high-level map of how the app works today.
Use it to onboard quickly, reason about system behavior, and understand where changes belong.

Product framing lives in docs/product_definition.md.
Architecture should support that product direction: follow-through first, analytics second.

## Ownership Model

Authoritative ownership rules are in docs/module_ownership.md.

- app.py: shell only
- pages/: UI orchestration
- services/: workflows and integration coordination
- domain/: pure business logic
- ui/: reusable components/presenters
- core/: app infrastructure/runtime/bootstrap
- utils/: generic helpers only

## Runtime Entry Flow

1. app.py initializes runtime and session.
2. core.app_flow handles:
   - logout/query actions
   - auth/session restoration
   - session timeout checks
   - billing portal return sync
   - subscription access gate
   - background workflows
3. core.navigation renders sidebar and top subscription banner.
4. core.page_router dispatches to page handlers.

Key files:
- app.py
- core/app_flow.py
- core/navigation.py
- core/page_router.py
- core/session.py

## Navigation Flow

Navigation is key-driven and centralized.

- Sidebar options are declared in core/navigation.py (nav_items list).
- The `supervisor` route is the Today screen / execution queue.
- Current page key is stored in st.session_state["_current_page_key"].
- Router mapping lives in core/page_router.py (handlers dict).
- Unknown route fallback: page_import.

Operational note: Add/remove pages by updating both nav_items and handlers together.

## Access Gating Flow

Primary gate: core.app_flow.enforce_subscription_access.

Decision path:
1. Admin allowlist bypass from secrets.ADMIN_EMAILS.
2. Cached entitlement check (short TTL via core/billing_cache.py).
3. Fresh entitlement read from services.billing_service.get_subscription_entitlement.
4. If denied, attempt checkout verification sync (billing.verify_checkout_and_activate).
5. If still denied, route to billing subscription page.

Observability:
- Structured events logged for allow/deny outcomes.

Key files:
- core/app_flow.py
- services/billing_service.py
- billing.py
- core/billing_cache.py

## Billing Flow

### Entitlements and dashboard

- services/billing_service.py builds canonical entitlement object used by gates/UI.
- Handles status semantics (active/trialing/past_due grace/unpaid/incomplete/canceled).
- Supports pending downgrade banner fields.

### Checkout verification

- billing.verify_checkout_and_activate verifies Stripe state and waits for DB webhook sync.
- Requires DB confirmation of active/trialing and matching subscription id/plan.
- Emits structured operational events for attempt/result.

### Webhook processing

- supabase/functions/stripe-webhook/index.ts is lifecycle authority for mirrored subscription state.
- Uses idempotency table: stripe_webhook_events.
- Writes full subscription snapshots to subscriptions table.
- Subscription events are authoritative; invoice events are supplemental.
- Emits structured webhook lifecycle logs.

### DB layer

- database.py provides Stripe helpers and mirrored subscription CRUD.
- Shared price-id -> plan mapping is centralized.

## Import Flow

UI orchestration:
- pages/import_page.py

Workflow/data layer:
- services/import_service.py
- data_loader.py
- data_processor.py
- database.py

High-level steps:
1. Upload/manual entry.
2. Header mapping and validation.
3. Derive/normalize rows and candidate UPH batch.
4. Enforce plan/import limits.
5. Persist history and upload metadata, with rollback support.
6. Bust caches and refresh derived views.

Failure handling:
- User-safe messages with next steps.
- Technical details in hidden expanders.
- Structured import_failure events + app error logs.

Jobs scaffolding:
- jobs/runner.py executes heavy operations synchronously today.
- jobs/entrypoints.py wraps preview and postprocess operations with stable job interfaces.
- Request metadata already models run mode/backend to support async workers later without changing call sites.

## Email Jobs Flow

Service orchestration:
- services/email_service.py

Worker runtime:
- scripts/email_scheduler_worker.py
- OS scheduler wrappers in scripts/install_scheduler_*.{sh,ps1}

Delivery/config:
- email_engine.py

Current behavior:
- Scheduled jobs run in a standalone worker process (cron/launchd/systemd/Task Scheduler).
- App runtime does not start recurring job threads.
- Manual send path remains active from pages/email_page.py.
- Tenant-scoped schedules and recipients.
- Structured email_delivery/email_failure events are logged.

## Data Access and Tenancy

Single DB access layer:
- database.py (authoritative Supabase integration layer).

Tenant isolation patterns:
- _tq(query): appends tenant filter when tenant context exists.
- _tenant_fields(): injects tenant_id on inserts.
- Subscription/billing reads are tenant-scoped.
- Today screen actions are stored in actions and tenant-scoped.
- Tests cover cross-tenant leak scenarios.

## Today Screen Flow

- Route key: `supervisor`
- UI entrypoint: pages/today.py
- Decision logic: services/action_service.py
- Persistence: actions table
- Goal: surface unhandled actions, overdue follow-ups, repeat no-improvement cycles, and ignored high performers.

Product note:
- rankings, risk, and trends are signal inputs
- the primary output is the action queue

## Logging and Diagnostics

Application errors:
- core.dependencies.log_app_error -> database log_error (with fallback print).

Operational events (JSONL):
- core.dependencies.log_operational_event -> dpd_ops_<tenant>.log
- Event classes include billing changes, checkout verification, webhook processing, import/email failures, plan/access denials.

Service-layer observability:
- services/observability.py provides Streamlit-free logging adapters used by services.
- This keeps business workflows reusable by non-Streamlit runtimes (workers/APIs).

Audit-oriented operational events now cover:
- import lifecycle (started/completed/failed)
- import issue-handling and excluded-data decisions
- target changes
- exception created/resolved
- action events created/completed

User-safe failures:
- core.dependencies.show_user_error used by critical workflows.
- Clean user guidance shown first; technical details hidden in expanders.

## Test Coverage Baseline

Test suite enforces:
- Billing entitlement status matrix
- Plan/feature/limit enforcement
- Domain formula behavior (risk/ranking/threshold logic)
- Tenant isolation boundaries
- Module ownership boundaries
- Smoke architecture checks

Run all tests:
- /Users/joeschloemer/Desktop/dpd_web/venv/bin/python -m pytest -q

## Keep This Document Current

Update this file in the same PR whenever any of these flows change:

- Billing lifecycle logic or webhook semantics
- Access gating decision path or cache semantics
- Import pipeline stages, rollback, or limit checks
- Email scheduler/manual send architecture
- Navigation keys/routes/dispatch ownership

Minimum update checklist for such PRs:
1. Update the relevant flow section(s) above.
2. Update key file references if moved/renamed.
3. Add one short "what changed" line in the modified section.
4. Ensure tests still represent the documented behavior.
