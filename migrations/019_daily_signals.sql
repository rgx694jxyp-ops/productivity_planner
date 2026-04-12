-- ============================================================================
-- 019_daily_signals.sql
-- Precomputed daily signals used by Today read-only rendering.
-- ============================================================================

CREATE TABLE IF NOT EXISTS daily_signals (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id       uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  signal_date     date        NOT NULL,
  signal_key      text        NOT NULL DEFAULT '',
  employee_id     text        NOT NULL DEFAULT '',
  signal_type     text        NOT NULL DEFAULT '',
  section         text        NOT NULL DEFAULT '',

  observed_value  numeric(14,4) NOT NULL DEFAULT 0,
  baseline_value  numeric(14,4) NOT NULL DEFAULT 0,
  confidence      text          NOT NULL DEFAULT 'low',
  completeness    text          NOT NULL DEFAULT 'limited',
  pattern_count   integer       NOT NULL DEFAULT 0,
  flags           jsonb         NOT NULL DEFAULT '{}'::jsonb,
  payload         jsonb         NOT NULL DEFAULT '{}'::jsonb,

  created_at      timestamptz   NOT NULL DEFAULT now(),
  updated_at      timestamptz   NOT NULL DEFAULT now()
);

DO $$
BEGIN
  ALTER TABLE daily_signals
    ADD CONSTRAINT daily_signals_signal_key_not_blank
    CHECK (btrim(signal_key) <> '');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_signals_dedupe
  ON daily_signals (tenant_id, signal_date, signal_key);

CREATE INDEX IF NOT EXISTS idx_daily_signals_tenant_date
  ON daily_signals (tenant_id, signal_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_signals_tenant_employee_date
  ON daily_signals (tenant_id, employee_id, signal_date DESC);

ALTER TABLE daily_signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS daily_signals_tenant_isolation ON daily_signals;
CREATE POLICY daily_signals_tenant_isolation ON daily_signals
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

COMMENT ON TABLE daily_signals IS 'Precomputed daily signal rows and payloads for read-only Today rendering.';
