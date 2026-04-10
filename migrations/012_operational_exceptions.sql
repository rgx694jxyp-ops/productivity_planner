-- ============================================================================
-- 012_operational_exceptions.sql
-- Lightweight operational exception tracking.
--
-- One row = one piece of contextual operating friction that may affect
-- performance interpretation for an employee, shift, date, or process.
-- ============================================================================

CREATE TABLE IF NOT EXISTS operational_exceptions (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id           uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

  employee_id         text        NOT NULL DEFAULT '',
  employee_name       text        NOT NULL DEFAULT '',
  department          text        NOT NULL DEFAULT '',

  exception_date      date        NOT NULL DEFAULT current_date,
  shift               text        NOT NULL DEFAULT '',
  process_name        text        NOT NULL DEFAULT '',
  category            text        NOT NULL DEFAULT 'unknown',

  summary             text        NOT NULL DEFAULT '',
  notes               text        NOT NULL DEFAULT '',
  status              text        NOT NULL DEFAULT 'open',

  created_at          timestamptz NOT NULL DEFAULT now(),
  created_by          text        NOT NULL DEFAULT '',
  resolved_at         timestamptz,
  resolved_by         text        NOT NULL DEFAULT '',
  resolution_note     text        NOT NULL DEFAULT ''
);

DO $$
BEGIN
  ALTER TABLE operational_exceptions
    ADD CONSTRAINT operational_exceptions_summary_not_blank
    CHECK (btrim(summary) <> '');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE operational_exceptions
    ADD CONSTRAINT operational_exceptions_category_valid
    CHECK (category IN ('attendance', 'training', 'system', 'equipment', 'process', 'inventory/replenishment', 'congestion', 'unknown'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE operational_exceptions
    ADD CONSTRAINT operational_exceptions_status_valid
    CHECK (status IN ('open', 'resolved'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_operational_exceptions_tenant_status_date
  ON operational_exceptions (tenant_id, status, exception_date DESC);

CREATE INDEX IF NOT EXISTS idx_operational_exceptions_tenant_employee_date
  ON operational_exceptions (tenant_id, employee_id, exception_date DESC);

ALTER TABLE operational_exceptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS operational_exceptions_tenant_isolation ON operational_exceptions;
CREATE POLICY operational_exceptions_tenant_isolation ON operational_exceptions
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

COMMENT ON TABLE operational_exceptions IS 'Supervisor-entered operational context that may affect performance interpretation.';
COMMENT ON COLUMN operational_exceptions.category IS 'attendance | training | system | equipment | process | inventory/replenishment | congestion | unknown';
COMMENT ON COLUMN operational_exceptions.status IS 'open | resolved';
COMMENT ON COLUMN operational_exceptions.process_name IS 'Optional process or work area label when available.';
