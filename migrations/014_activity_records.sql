-- ============================================================================
-- 014_activity_records.sql
-- Normalized operational activity records from imports and derived history flows.
-- ============================================================================

CREATE TABLE IF NOT EXISTS activity_records (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id             uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

  employee_id           text        NOT NULL DEFAULT '',
  activity_date         date        NOT NULL,
  process_name          text        NOT NULL DEFAULT '',

  units                 numeric(14,2) NOT NULL DEFAULT 0,
  hours                 numeric(14,2) NOT NULL DEFAULT 0,
  productivity_value    numeric(14,2) NOT NULL DEFAULT 0,

  source_import_job_id  text        NOT NULL DEFAULT '',
  source_import_file    text        NOT NULL DEFAULT '',
  source_upload_id      text        NOT NULL DEFAULT '',
  source_record_hash    text        NOT NULL DEFAULT '',

  data_quality_status   text        NOT NULL DEFAULT 'partial',
  exclusion_note        text        NOT NULL DEFAULT '',
  handling_choice       text        NOT NULL DEFAULT '',
  handling_note         text        NOT NULL DEFAULT '',

  raw_context           jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  ALTER TABLE activity_records
    ADD CONSTRAINT activity_records_employee_not_blank
    CHECK (btrim(employee_id) <> '');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE activity_records
    ADD CONSTRAINT activity_records_data_quality_status_valid
    CHECK (data_quality_status IN ('valid', 'partial', 'low_confidence', 'invalid', 'excluded'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE activity_records
    ADD CONSTRAINT activity_records_handling_choice_valid
    CHECK (handling_choice IN ('', 'review_details', 'ignore_rows', 'include_low_confidence', 'map_or_correct'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_records_dedupe_key
  ON activity_records (tenant_id, employee_id, activity_date, process_name);

CREATE INDEX IF NOT EXISTS idx_activity_records_tenant_date
  ON activity_records (tenant_id, activity_date DESC);

CREATE INDEX IF NOT EXISTS idx_activity_records_tenant_employee_date
  ON activity_records (tenant_id, employee_id, activity_date DESC);

ALTER TABLE activity_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS activity_records_tenant_isolation ON activity_records;
CREATE POLICY activity_records_tenant_isolation ON activity_records
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

COMMENT ON TABLE activity_records IS 'Normalized operational activity rows used for trend, confidence, pattern, and drill-down logic.';
COMMENT ON COLUMN activity_records.data_quality_status IS 'valid | partial | low_confidence | invalid | excluded';
COMMENT ON COLUMN activity_records.source_record_hash IS 'Optional deterministic hash of source content for traceability.';
