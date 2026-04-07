-- ============================================================================
-- 008_supervisor_actions.sql
-- Persistence for Today Screen action cycles.
-- Safe to run multiple times.
-- ============================================================================

CREATE TABLE IF NOT EXISTS supervisor_actions (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         uuid REFERENCES tenants(id) ON DELETE CASCADE,
  emp_id            text NOT NULL,
  employee_name     text NOT NULL DEFAULT '',
  department        text NOT NULL DEFAULT '',
  issue_type        text NOT NULL DEFAULT '',
  reason            text NOT NULL DEFAULT '',
  trigger_source    text NOT NULL DEFAULT 'today_screen',
  status            text NOT NULL DEFAULT 'new',
  action_type       text NOT NULL DEFAULT '',
  success_metric    text NOT NULL DEFAULT '',
  note              text NOT NULL DEFAULT '',
  due_date          date,
  baseline_uph      numeric,
  latest_uph        numeric,
  improvement_delta numeric,
  outcome           text NOT NULL DEFAULT '',
  outcome_note      text NOT NULL DEFAULT '',
  created_by        text NOT NULL DEFAULT '',
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  completed_at      timestamptz,
  escalated_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_supervisor_actions_tenant_status
  ON supervisor_actions (tenant_id, status, due_date);

CREATE INDEX IF NOT EXISTS idx_supervisor_actions_tenant_emp
  ON supervisor_actions (tenant_id, emp_id, created_at DESC);

ALTER TABLE supervisor_actions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS supervisor_actions_tenant_isolation ON supervisor_actions;
CREATE POLICY supervisor_actions_tenant_isolation ON supervisor_actions
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());
