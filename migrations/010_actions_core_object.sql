-- ============================================================================
-- 010_actions_core_object.sql
-- Defines the v1 actions table — the core workflow object of the
-- Supervisor Execution System.
--
-- One row = one active or historical issue that required supervisor action.
--
-- NOTE: This supersedes 008_supervisor_actions.sql and
--       009_rename_actions_table.sql. On a fresh deployment, skip 008
--       and 009 and run this migration instead.
--
-- Safe to re-run: drops and recreates the table cleanly.
-- ============================================================================

-- Remove any partial state from earlier migration attempts
DROP TABLE IF EXISTS actions CASCADE;
DROP TABLE IF EXISTS supervisor_actions CASCADE;

CREATE TABLE actions (
  -- Identity
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id           uuid    NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

  -- Who this is about
  employee_id         text    NOT NULL,
  employee_name       text    NOT NULL DEFAULT '',
  department          text    NOT NULL DEFAULT '',

  -- What the problem is
  issue_type          text    NOT NULL DEFAULT '',
  trigger_source      text    NOT NULL DEFAULT 'today',
  trigger_summary     text    NOT NULL DEFAULT '',

  -- Workflow state
  status              text    NOT NULL DEFAULT 'new',
  priority            text    NOT NULL DEFAULT 'medium',

  -- What the supervisor is doing about it
  action_type         text    NOT NULL DEFAULT '',
  success_metric      text    NOT NULL DEFAULT '',
  note                text    NOT NULL DEFAULT '',

  -- UPH tracking (for outcome measurement)
  baseline_uph        numeric,
  latest_uph          numeric,
  improvement_delta   numeric,

  -- Resolution
  resolution_type     text    NOT NULL DEFAULT '',
  resolution_note     text    NOT NULL DEFAULT '',

  -- Timestamps
  follow_up_due_at    timestamptz,
  last_event_at       timestamptz NOT NULL DEFAULT now(),
  resolved_at         timestamptz,
  escalated_at        timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  created_by          text    NOT NULL DEFAULT ''
);

-- Indexes
CREATE INDEX idx_actions_tenant_status
  ON actions (tenant_id, status, follow_up_due_at);

CREATE INDEX idx_actions_tenant_employee
  ON actions (tenant_id, employee_id, created_at DESC);

-- Row-level security
ALTER TABLE actions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS actions_tenant_isolation ON actions;
CREATE POLICY actions_tenant_isolation ON actions
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

COMMENT ON TABLE  actions IS 'Supervisor follow-through actions. Primary output of the Today screen.';
COMMENT ON COLUMN actions.issue_type        IS 'What the problem is — see domain/actions.py IssueType.';
COMMENT ON COLUMN actions.trigger_source    IS 'What created this action: today (auto-generated) or manual.';
COMMENT ON COLUMN actions.trigger_summary   IS 'Human-readable reason the action was opened.';
COMMENT ON COLUMN actions.action_type       IS 'What the supervisor is doing — see domain/actions.py ACTION_TYPES.';
COMMENT ON COLUMN actions.status            IS 'new | in_progress | follow_up_due | overdue | escalated | resolved | deprioritized';
COMMENT ON COLUMN actions.priority          IS 'high | medium | low';
COMMENT ON COLUMN actions.resolution_type   IS 'improved | no_change | worse | blocked';
COMMENT ON COLUMN actions.last_event_at     IS 'Updated on every write — used to sort the active queue.';
COMMENT ON COLUMN actions.resolved_at       IS 'Set when status moves to resolved.';
