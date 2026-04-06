-- 003_missing_columns.sql
-- Adds billing columns missing from the initial migration.
-- Safe to run multiple times (uses ADD COLUMN IF NOT EXISTS).
--
-- Run in Supabase SQL Editor.

-- current_period_start is written by the webhook but was not in 002.
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS current_period_start TIMESTAMPTZ;

-- pending_plan / pending_change_at track portal-scheduled downgrades.
-- Written by both the webhook and the app. Without these columns the
-- downgrade banner never appears.
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS pending_plan TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS pending_change_at TIMESTAMPTZ;

-- Fix any rows where employee_limit is 0 but the plan name is known.
-- This corrects bad state from webhook failures or incomplete activation.
UPDATE subscriptions SET employee_limit = 25  WHERE plan = 'starter'  AND employee_limit = 0;
UPDATE subscriptions SET employee_limit = 100 WHERE plan = 'pro'      AND employee_limit = 0;
UPDATE subscriptions SET employee_limit = -1  WHERE plan = 'business' AND employee_limit = 0;
