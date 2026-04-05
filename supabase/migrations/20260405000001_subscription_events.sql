-- 003_subscription_events.sql
-- Adds subscription_events debug table + current_period_start column
-- Run in Supabase SQL Editor (safe to re-run)

-- 1. subscription_events: raw Stripe event log for debugging
--    Written exclusively by the webhook (service role, bypasses RLS).
--    Invaluable when "why didn't the subscription activate?" questions arise.
CREATE TABLE IF NOT EXISTS subscription_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID REFERENCES tenants(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    raw_json    JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sub_events_tenant
    ON subscription_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sub_events_type
    ON subscription_events(event_type);
CREATE INDEX IF NOT EXISTS idx_sub_events_created
    ON subscription_events(created_at DESC);

-- RLS: tenants can see their own events (read-only for app users)
ALTER TABLE subscription_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Tenant can view own subscription events" ON subscription_events;
CREATE POLICY "Tenant can view own subscription events"
    ON subscription_events FOR SELECT
    USING (tenant_id = get_my_tenant_id());

-- 2. Add current_period_start to subscriptions (if not already present)
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS current_period_start TIMESTAMPTZ;
