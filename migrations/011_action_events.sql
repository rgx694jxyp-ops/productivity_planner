-- ============================================================================
-- 011_action_events.sql
-- Lifecycle event log for the actions table.
--
-- One action has many events. Events are immutable — never updated,
-- only appended. The parent action row tracks current state; this table
-- answers "what happened and in what order?"
--
-- Safe to re-run: uses IF NOT EXISTS guards.
-- ============================================================================

CREATE TABLE IF NOT EXISTS action_events (
  -- Identity
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id           uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  action_id           bigint      NOT NULL REFERENCES actions(id) ON DELETE CASCADE,

  -- Who this is about (denormalized for fast queries without joins)
  employee_id         text        NOT NULL DEFAULT '',

  -- What happened
  event_type          text        NOT NULL,
  event_at            timestamptz NOT NULL DEFAULT now(),
  performed_by        text        NOT NULL DEFAULT '',
  notes               text        NOT NULL DEFAULT '',

  -- Outcome at time of event (null means event did not produce an outcome yet)
  outcome             text,

  -- Follow-up scheduling
  next_follow_up_at   timestamptz
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_action_events_action
  ON action_events (action_id, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_action_events_tenant_employee
  ON action_events (tenant_id, employee_id, event_at DESC);

-- Row-level security
ALTER TABLE action_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS action_events_tenant_isolation ON action_events;
CREATE POLICY action_events_tenant_isolation ON action_events
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- Column comments
COMMENT ON TABLE  action_events IS 'Immutable lifecycle log for actions. Append-only; never update rows.';
COMMENT ON COLUMN action_events.event_type        IS 'created | coached | follow_up_logged | recognized | escalated | resolved | deprioritized | reopened';
COMMENT ON COLUMN action_events.outcome           IS 'improved | no_change | worse | pending | not_applicable — null until an outcome-producing event occurs.';
COMMENT ON COLUMN action_events.next_follow_up_at IS 'When set, the supervisor committed to a follow-up by this date.';
COMMENT ON COLUMN action_events.notes             IS 'Free-form supervisor note at time of event.';
