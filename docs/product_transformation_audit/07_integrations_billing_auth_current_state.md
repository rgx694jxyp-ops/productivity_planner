# 07 — Integrations, Billing & Auth: Current State

> Assessment of Stripe billing, Supabase auth, and the absence of third-party data integrations.

---

## Auth: Supabase Auth + Session Management (`auth.py`, 721 lines)

### Mechanism

- Auth is handled entirely by **Supabase Auth** (email/password by default)
- On successful login, Supabase returns a JWT (access_token + refresh_token)
- Tokens are injected into browser cookies via JavaScript injection (`set_auth_cookies()`)
- On page load, `auth.py` reads cookies, restores the session to `st.session_state["supabase_session"]`
- The Supabase client is re-hydrated with the stored access/refresh tokens on every re-run

### Session Constants

```python
SESSION_TIMEOUT_SECONDS     = 28800   # 8 hours inactivity timeout
MAX_SESSION_LIFETIME_SECONDS = 43200  # 12 hours hard cap (even with activity)
LOGIN_MAX_ATTEMPTS          = 5       # Before lockout
LOGIN_LOCKOUT_SECONDS       = 900     # 15 minutes
```

### Auth Redirect URL Resolution

Priority order for OAuth/email confirmation redirects:
```
AUTH_REDIRECT_URL → APP_BASE_URL → PUBLIC_APP_URL → RENDER_EXTERNAL_URL
```

### Multi-tenant Join Flow

New users join a tenant by invite code (from `tenants.invite_code`):
```python
join_tenant_by_invite(user_id, invite_code, user_name)
    → validates invite code → upserts user_profiles with tenant_id + role='viewer'
```

Invite code regeneration: `regenerate_invite_code(tenant_id)` → new random UUID.

### RLS Enforcement

Every tenant-scoped table has RLS policies using:
```sql
get_my_tenant_id()  -- Postgres function reading auth.jwt() claim
```

This means the Supabase client **must** have a valid JWT in context for any RLS-protected query to succeed. Queries made without a session token will return empty results or permission errors.

### Known Auth Risks

- Cookie-based token storage via JavaScript injection is fragile across browsers and is incompatible with strict CSP headers
- `st.session_state` is not shared across browser tabs in Streamlit — each tab gets an independent session
- No SSO / SAML / OAuth social login (Google, Microsoft) — email/password only

---

## Billing: Stripe + Supabase Edge Function

### Subscription Architecture

```
User → Stripe Checkout → stripe-webhook Edge Function → subscriptions table
                                                       → subscription_events table
                                                       → pending_plan_changes table
```

Plans: `starter`, `pro`, `business` (plus internal `admin`, `enterprise` ranks for plan enforcement).

### `billing.py` (624 lines)

`verify_checkout_and_activate(session_id, tenant_id)`:
1. Calls Stripe API to fetch checkout session
2. Verifies payment status
3. Updates `subscriptions` table via `database.update_subscription_state()`
4. Appends to `subscription_events` audit log

### `services/billing_service.py` (340 lines)

`get_subscription_entitlement(tenant_id)` — the single source of truth for access:

```python
{
  "plan": "pro",
  "status": "active",
  "employee_limit": 100,
  "is_active": True,
  "is_trialing": False,
  "is_past_due": False,
  "features": { "advanced": True, "coaching_insights": True, ... }
}
```

Statuses handled: `active`, `trialing`, `past_due`, `canceled`.

### Stripe Webhook: `supabase/functions/stripe-webhook/index.ts` (Deno)

Handles Stripe events and writes to Supabase:

```typescript
// Plan resolution priority:
// 1. sub.metadata.plan
// 2. sub.items.data[0].price.metadata.plan
// 3. STRIPE_PRICE_STARTER / STRIPE_PRICE_PRO / STRIPE_PRICE_BUSINESS secrets

const PLAN_LIMITS: Record<string, number> = {
  starter: 25,
  pro: 100,
  business: -1   // unlimited
};
```

Events handled: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`, `invoice.payment_succeeded`.

Idempotency: `stripe_webhook_events` table deduplicates by `stripe_event_id`.

### Required Stripe Secrets (Supabase Functions secrets)

```
STRIPE_WEBHOOK_SECRET    = whsec_xxx
STRIPE_SECRET_KEY        = sk_xxx
STRIPE_PRICE_STARTER     = price_xxx
STRIPE_PRICE_PRO         = price_xxx
STRIPE_PRICE_BUSINESS    = price_xxx
SUPABASE_URL
SERVICE_ROLE_KEY
```

### Billing Cache (`core/billing_cache.py`)

In-process TTL dict cache for entitlement lookups — avoids hitting the subscriptions table on every Streamlit re-run. TTL configured via `BILLING_CACHE_TTL_SECONDS` env var.

---

## Plan Enforcement

`services/plan_service.py` defines `PLAN_FEATURES` and `PLAN_RANKS`:

```python
PLAN_RANKS = { "starter": 1, "pro": 2, "business": 3, "admin": 99, "enterprise": 100 }
```

`core/navigation.py` exposes `plan_gate(min_plan, feature_name)` — called from page render functions to show upgrade prompts for plan-gated features.

---

## External Integrations: Current State

| Integration | Status | Notes |
|-------------|--------|-------|
| **Supabase (PostgreSQL)** | ✅ Live | Full: DB, auth, RLS, edge functions |
| **Stripe** | ✅ Live | Checkout, webhooks, subscription management |
| **SMTP email** | ✅ Live | Via smtplib; tenant-configured server |
| **WMS (HighJump, Manhattan, etc.)** | ❌ None | No adapter exists |
| **ERP (SAP, Oracle, NetSuite)** | ❌ None | No adapter exists |
| **TMS (FedEx, UPS, McLeod)** | ❌ None | No adapter exists |
| **QuickBooks / Xero** | ❌ None | No adapter exists |
| **Shopify / WooCommerce** | ❌ None | No adapter exists |
| **ShipStation / ShipBob** | ❌ None | No adapter exists |
| **Time-tracking (ADP, Kronos, UKG)** | ❌ None | No adapter exists |
| **Slack / Microsoft Teams** | ❌ None | No notification webhook |
| **SFTP / folder watch** | ❌ None | No automated file ingestion |
| **S3 / cloud storage** | ❌ None | No file storage adapter |
| **Twilio / SMS** | ❌ None | No mobile alerts |

**Summary:** The only external integrations are Supabase (data + auth), Stripe (billing), and tenant-configured SMTP (email). All data enters via manual CSV upload. All integration work is greenfield.

---

## Integration Readiness Assessment

| Readiness Factor | Current State |
|-----------------|--------------|
| Tenant isolation model | ✅ Solid — UUID tenant_id + RLS on all tables |
| Auth tokens compatible with API layer | ✅ Supabase JWT is API-compatible |
| Data model extensible for integration IDs | ⚠️ Tables lack `external_id` / `source_system` columns |
| Webhook receiver | ❌ No webhook ingestion endpoint |
| API key management for integrations | ❌ No integration credential store |
| Event log for integration events | ❌ No `integration_events` table |
| Rate limiting / retry logic | ❌ Not present |
