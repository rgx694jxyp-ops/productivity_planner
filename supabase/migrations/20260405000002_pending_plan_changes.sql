-- 20260405000002_pending_plan_changes.sql
-- Adds pending plan-change tracking to subscriptions

ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS pending_plan TEXT;

ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS pending_change_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_subscriptions_pending_plan
    ON subscriptions(pending_plan)
    WHERE pending_plan IS NOT NULL;
