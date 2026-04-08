-- 009_rename_actions_table.sql
-- Rename supervisor_actions → actions.
-- Safe to re-run: uses IF EXISTS / IF NOT EXISTS guards.

ALTER TABLE IF EXISTS supervisor_actions RENAME TO actions;

-- Rename indexes
ALTER INDEX IF EXISTS idx_supervisor_actions_tenant_status RENAME TO idx_actions_tenant_status;
ALTER INDEX IF EXISTS idx_supervisor_actions_tenant_emp RENAME TO idx_actions_tenant_emp;

-- Drop old RLS policy and recreate under new table name
DROP POLICY IF EXISTS supervisor_actions_tenant_isolation ON actions;
CREATE POLICY actions_tenant_isolation ON actions
    USING (tenant_id = get_my_tenant_id());

-- Update trigger_source default value comment (column default stays as-is;
-- application code now uses 'today' as trigger_source value)
COMMENT ON TABLE actions IS 'Supervisor follow-through actions. Primary output of the Today screen.';
