ALTER TABLE tenant_goals
  ADD COLUMN IF NOT EXISTS default_target_uph numeric NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS process_targets jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS employee_target_overrides jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS configured_processes jsonb NOT NULL DEFAULT '[]';