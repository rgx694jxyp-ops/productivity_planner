-- ============================================================================
-- 007_coaching_followups.sql
-- DB-backed follow-up schedule store. Replaces legacy local JSON follow-up files.
-- Safe to run multiple times.
-- ============================================================================

CREATE TABLE IF NOT EXISTS coaching_followups (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id      uuid REFERENCES tenants(id) ON DELETE CASCADE,
  emp_id         text NOT NULL,
  name           text NOT NULL DEFAULT '',
  dept           text NOT NULL DEFAULT '',
  followup_date  date NOT NULL,
  note_preview   text NOT NULL DEFAULT '',
  added_on       date NOT NULL DEFAULT CURRENT_DATE,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, emp_id, followup_date)
);

CREATE INDEX IF NOT EXISTS idx_coaching_followups_tenant_date
  ON coaching_followups (tenant_id, followup_date);
