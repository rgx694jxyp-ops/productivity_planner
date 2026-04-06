-- ============================================================================
-- 005_operations_features.sql
-- Shift Plan, Coaching Intelligence, and Cost Impact tables.
-- Safe to run multiple times (IF NOT EXISTS throughout).
-- ============================================================================

-- --------------------------------------------------------------------------
-- shift_plans: daily plans set by managers
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shift_plans (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id      uuid REFERENCES tenants(id),
  plan_date      date NOT NULL,
  shift_start    text NOT NULL DEFAULT '08:00',   -- HH:MM local
  shift_end      text NOT NULL DEFAULT '16:00',
  departments    jsonb NOT NULL DEFAULT '[]',      -- [{name, staff, volume}]
  task_baselines jsonb NOT NULL DEFAULT '{}',      -- {dept: {task: minutes}}
  notes          text DEFAULT '',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, plan_date)
);

-- --------------------------------------------------------------------------
-- coaching_note_tags: auto/manual tags on coaching notes
-- --------------------------------------------------------------------------
ALTER TABLE coaching_notes
  ADD COLUMN IF NOT EXISTS issue_type   text DEFAULT '',   -- speed|accuracy|process|attendance|training
  ADD COLUMN IF NOT EXISTS action_taken text DEFAULT '',   -- coaching|retraining|reassignment|reminder
  ADD COLUMN IF NOT EXISTS tone         text DEFAULT '',   -- warning|neutral|positive
  ADD COLUMN IF NOT EXISTS uph_before   numeric,
  ADD COLUMN IF NOT EXISTS uph_after    numeric;

-- --------------------------------------------------------------------------
-- shift_checkpoints: actual output captured at checkpoint times
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shift_checkpoints (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id    uuid REFERENCES tenants(id),
  plan_date    date NOT NULL,
  department   text NOT NULL,
  checkpoint   text NOT NULL,               -- e.g. "10:00"
  expected     numeric NOT NULL DEFAULT 0,
  actual       numeric NOT NULL DEFAULT 0,
  recorded_at  timestamptz NOT NULL DEFAULT now()
);
