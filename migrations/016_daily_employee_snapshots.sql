-- ============================================================================
-- 016_daily_employee_snapshots.sql
-- Daily employee summaries for fast interpreted views and recent trend tracking.
-- ============================================================================

CREATE TABLE IF NOT EXISTS daily_employee_snapshots (
  id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id                uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  snapshot_date            date        NOT NULL,
  employee_id              text        NOT NULL DEFAULT '',
  process_name             text        NOT NULL DEFAULT '',

  performance_uph          numeric(14,2) NOT NULL DEFAULT 0,
  expected_uph             numeric(14,2) NOT NULL DEFAULT 0,
  variance_uph             numeric(14,2) NOT NULL DEFAULT 0,
  recent_average_uph       numeric(14,2) NOT NULL DEFAULT 0,
  prior_average_uph        numeric(14,2) NOT NULL DEFAULT 0,

  trend_state              text        NOT NULL DEFAULT 'insufficient_data',
  goal_status              text        NOT NULL DEFAULT 'no_goal',
  confidence_label         text        NOT NULL DEFAULT 'Low',
  confidence_score         numeric(8,4) NOT NULL DEFAULT 0,

  data_completeness_status text        NOT NULL DEFAULT 'limited',
  data_completeness_note   text        NOT NULL DEFAULT '',
  coverage_ratio           numeric(8,4) NOT NULL DEFAULT 0,
  included_day_count       integer     NOT NULL DEFAULT 0,
  excluded_day_count       integer     NOT NULL DEFAULT 0,

  repeat_count             integer     NOT NULL DEFAULT 0,
  pattern_marker           text        NOT NULL DEFAULT '',
  recent_trend_history     jsonb       NOT NULL DEFAULT '[]'::jsonb,
  recent_goal_status_history jsonb     NOT NULL DEFAULT '[]'::jsonb,

  workload_units           numeric(14,2) NOT NULL DEFAULT 0,
  workload_hours           numeric(14,2) NOT NULL DEFAULT 0,
  raw_metrics              jsonb       NOT NULL DEFAULT '{}'::jsonb,

  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  ALTER TABLE daily_employee_snapshots
    ADD CONSTRAINT daily_employee_snapshots_employee_not_blank
    CHECK (btrim(employee_id) <> '');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE daily_employee_snapshots
    ADD CONSTRAINT daily_employee_snapshots_trend_state_valid
    CHECK (trend_state IN ('up', 'down', 'flat', 'insufficient_data'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE daily_employee_snapshots
    ADD CONSTRAINT daily_employee_snapshots_goal_status_valid
    CHECK (goal_status IN ('on_goal', 'below_goal', 'no_goal'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_employee_snapshots_dedupe
  ON daily_employee_snapshots (tenant_id, snapshot_date, employee_id, process_name);

CREATE INDEX IF NOT EXISTS idx_daily_employee_snapshots_tenant_date
  ON daily_employee_snapshots (tenant_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_employee_snapshots_tenant_employee_date
  ON daily_employee_snapshots (tenant_id, employee_id, snapshot_date DESC);

ALTER TABLE daily_employee_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS daily_employee_snapshots_tenant_isolation ON daily_employee_snapshots;
CREATE POLICY daily_employee_snapshots_tenant_isolation ON daily_employee_snapshots
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

COMMENT ON TABLE daily_employee_snapshots IS 'Daily summary rows used for fast Today, employee detail, and team/process interpretation.';