ALTER TABLE daily_employee_snapshots
  DROP CONSTRAINT IF EXISTS daily_employee_snapshots_trend_state_valid;

ALTER TABLE daily_employee_snapshots
  ADD CONSTRAINT daily_employee_snapshots_trend_state_valid
  CHECK (trend_state IN ('stable', 'below_expected', 'declining', 'improving', 'inconsistent', 'insufficient_data'));
