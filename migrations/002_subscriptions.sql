-- 002_subscriptions.sql
-- Adds Stripe subscription tracking for plan gating
-- Run this in Supabase SQL Editor

-- 1. Create subscriptions table
CREATE TABLE IF NOT EXISTS subscriptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    stripe_customer_id      TEXT NOT NULL,
    stripe_subscription_id  TEXT,
    plan            TEXT NOT NULL DEFAULT 'starter',
    status          TEXT NOT NULL DEFAULT 'incomplete',
    employee_limit  INT NOT NULL DEFAULT 25,
    current_period_end  TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT subscriptions_tenant_uq UNIQUE (tenant_id)
);

-- Add user_id column if not exists (for existing tables)
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- 2. Add stripe_customer_id to tenants table for quick lookup
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;

-- 3. RLS policies
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own subscription" ON subscriptions;
CREATE POLICY "Users can view own subscription"
    ON subscriptions FOR SELECT
    USING (user_id = auth.uid() OR tenant_id = (
        SELECT tenant_id FROM user_profiles
        WHERE id = auth.uid()
        LIMIT 1
    ));

-- Service role (webhook) can do anything — no policy needed, bypasses RLS

-- 4. Index for webhook lookups
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer
    ON subscriptions(stripe_customer_id);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant
    ON subscriptions(tenant_id);
