-- ============================================================================
-- 013_action_events_follow_through.sql
-- Expand action_events so it can also serve as a lightweight follow-through log.
--
-- Keeps existing action-linked lifecycle history intact while allowing quick,
-- immutable entries tied only to an employee and/or an operational exception.
-- ============================================================================

ALTER TABLE action_events
  ALTER COLUMN action_id DROP NOT NULL;

ALTER TABLE action_events
  ADD COLUMN IF NOT EXISTS linked_exception_id bigint REFERENCES operational_exceptions(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS owner text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'logged',
  ADD COLUMN IF NOT EXISTS due_date timestamptz,
  ADD COLUMN IF NOT EXISTS details text NOT NULL DEFAULT '';

UPDATE action_events
SET owner = COALESCE(NULLIF(owner, ''), performed_by, ''),
    details = COALESCE(NULLIF(details, ''), notes, ''),
    due_date = COALESCE(due_date, next_follow_up_at),
    status = CASE
      WHEN COALESCE(status, '') <> '' THEN status
      WHEN event_type IN ('resolved', 'recognized', 'deprioritized') THEN 'done'
      WHEN event_type = 'escalated' THEN 'blocked'
      ELSE 'logged'
    END;

DO $$
BEGIN
  ALTER TABLE action_events
    ADD CONSTRAINT action_events_status_valid
    CHECK (status IN ('logged', 'pending', 'done', 'blocked'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_action_events_tenant_exception
  ON action_events (tenant_id, linked_exception_id, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_action_events_tenant_status_due
  ON action_events (tenant_id, status, due_date);

COMMENT ON TABLE action_events IS 'Immutable follow-through log for action-linked and lightweight supervisor notes.';
COMMENT ON COLUMN action_events.action_id IS 'Nullable. When present, this event belongs to a tracked action.';
COMMENT ON COLUMN action_events.linked_exception_id IS 'Optional operational_exceptions.id link when the log entry follows through on a known blocker.';
COMMENT ON COLUMN action_events.owner IS 'Who owns or logged the follow-through item.';
COMMENT ON COLUMN action_events.status IS 'logged | pending | done | blocked';
COMMENT ON COLUMN action_events.due_date IS 'Optional follow-through due date for lightweight items.';
COMMENT ON COLUMN action_events.details IS 'Free-form follow-through details. Mirrors notes for compatibility.';