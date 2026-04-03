-- ============================================================================
-- 001_setup.sql
-- Multi-tenant setup for DPD Web (Streamlit Productivity Planner)
--
-- Safe to run multiple times (uses IF NOT EXISTS / DO $$ blocks throughout).
-- Adds tenant_id columns, RLS policies, new tenant config tables, and
-- the provision_tenant RPC.
-- ============================================================================

-- --------------------------------------------------------------------------
-- 1. CORE TABLES: tenants & user_profiles
--    These must exist before the helper function references them.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_profiles (
  id         uuid PRIMARY KEY,            -- matches auth.users.id
  tenant_id  uuid NOT NULL REFERENCES tenants(id),
  role       text NOT NULL DEFAULT 'viewer',
  name       text,
  created_at timestamptz NOT NULL DEFAULT now()
);


-- --------------------------------------------------------------------------
-- 2. HELPER: get_my_tenant_id()
--    Defined AFTER user_profiles so the SQL-language function can resolve
--    the table reference at creation time.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_my_tenant_id()
RETURNS uuid AS $$
  SELECT tenant_id FROM user_profiles WHERE id = auth.uid()
$$ LANGUAGE sql STABLE SECURITY DEFINER;


-- --------------------------------------------------------------------------
-- 3. EXISTING TABLES: ensure they exist, then add tenant_id column
--    Each block creates the table IF NOT EXISTS, then ALTERs to add
--    tenant_id IF NOT EXISTS.
-- --------------------------------------------------------------------------

-- clients
CREATE TABLE IF NOT EXISTS clients (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name       text,
  contact    text,
  email      text,
  notes      text,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE clients ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- orders
CREATE TABLE IF NOT EXISTS orders (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  client_id        bigint REFERENCES clients(id),
  order_number     text,
  description      text,
  total_units      numeric,
  units_completed  numeric DEFAULT 0,
  target_uph       numeric,
  target_date      date,
  shift_length_hrs numeric,
  status           text DEFAULT 'open',
  notes            text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  completed_at     timestamptz
);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- employees
CREATE TABLE IF NOT EXISTS employees (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  emp_id     text,
  name       text,
  department text,
  shift      text,
  is_new     boolean DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE employees ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- order_assignments
CREATE TABLE IF NOT EXISTS order_assignments (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id    bigint REFERENCES orders(id),
  emp_id      bigint REFERENCES employees(id),
  active      boolean DEFAULT true,
  assigned_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE order_assignments ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- unit_submissions
CREATE TABLE IF NOT EXISTS unit_submissions (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id    bigint REFERENCES orders(id),
  emp_id      bigint REFERENCES employees(id),
  units       numeric,
  uph         numeric,
  hours_worked numeric,
  work_date   date,
  source_file text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE unit_submissions ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- uph_history
CREATE TABLE IF NOT EXISTS uph_history (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  emp_id       bigint REFERENCES employees(id),
  work_date    date,
  uph          numeric,
  units        numeric,
  hours_worked numeric,
  department   text,
  order_id     bigint,
  created_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE uph_history ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- coaching_notes
CREATE TABLE IF NOT EXISTS coaching_notes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  emp_id     bigint REFERENCES employees(id),
  note       text,
  created_by text,
  archived   boolean DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE coaching_notes ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- shifts
CREATE TABLE IF NOT EXISTS shifts (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  shift_name   text,
  shift_date   date,
  shift_length numeric,
  created_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE shifts ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- uploaded_files
CREATE TABLE IF NOT EXISTS uploaded_files (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  filename       text,
  row_count      integer,
  header_mapping jsonb,
  is_active      boolean DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);

-- client_trends
CREATE TABLE IF NOT EXISTS client_trends (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  client_id        bigint REFERENCES clients(id),
  period           text,
  avg_uph          numeric,
  total_units      numeric,
  orders_completed integer,
  created_at       timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE client_trends ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);


-- --------------------------------------------------------------------------
-- 4. NEW TABLES: tenant-scoped configuration
-- --------------------------------------------------------------------------

-- tenant_goals: department UPH targets and flagged employees per tenant
CREATE TABLE IF NOT EXISTS tenant_goals (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id         uuid NOT NULL UNIQUE REFERENCES tenants(id),
  dept_targets      jsonb NOT NULL DEFAULT '{}',
  flagged_employees jsonb NOT NULL DEFAULT '{}',
  created_at        timestamptz NOT NULL DEFAULT now()
);

-- tenant_settings: general app settings per tenant
CREATE TABLE IF NOT EXISTS tenant_settings (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id  uuid NOT NULL UNIQUE REFERENCES tenants(id),
  config     jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

-- tenant_email_config: SMTP + recipients + schedules per tenant
CREATE TABLE IF NOT EXISTS tenant_email_config (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id  uuid NOT NULL UNIQUE REFERENCES tenants(id),
  smtp       jsonb NOT NULL DEFAULT '{}',
  recipients jsonb NOT NULL DEFAULT '[]',
  schedules  jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now()
);


-- --------------------------------------------------------------------------
-- 5. ENABLE ROW LEVEL SECURITY on every table
-- --------------------------------------------------------------------------
ALTER TABLE tenants             ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients             ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders              ENABLE ROW LEVEL SECURITY;
ALTER TABLE employees           ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_assignments   ENABLE ROW LEVEL SECURITY;
ALTER TABLE unit_submissions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE uph_history         ENABLE ROW LEVEL SECURITY;
ALTER TABLE coaching_notes      ENABLE ROW LEVEL SECURITY;
ALTER TABLE shifts              ENABLE ROW LEVEL SECURITY;
ALTER TABLE uploaded_files      ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_trends       ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_goals        ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_settings     ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_email_config ENABLE ROW LEVEL SECURITY;


-- --------------------------------------------------------------------------
-- 6. RLS POLICIES
--    Each policy gates SELECT/INSERT/UPDATE/DELETE so that users can only
--    touch rows where tenant_id = get_my_tenant_id().
--
--    DROP POLICY IF EXISTS + CREATE POLICY makes this idempotent.
-- --------------------------------------------------------------------------

-- ---- tenants ----
-- Users can only see their own tenant row.
DROP POLICY IF EXISTS tenant_isolation ON tenants;
CREATE POLICY tenant_isolation ON tenants
  FOR ALL USING (id = get_my_tenant_id())
  WITH CHECK (id = get_my_tenant_id());

-- ---- user_profiles ----
-- Users can see profiles within their tenant.
DROP POLICY IF EXISTS tenant_isolation ON user_profiles;
CREATE POLICY tenant_isolation ON user_profiles
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- clients ----
DROP POLICY IF EXISTS tenant_isolation ON clients;
CREATE POLICY tenant_isolation ON clients
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- orders ----
DROP POLICY IF EXISTS tenant_isolation ON orders;
CREATE POLICY tenant_isolation ON orders
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- employees ----
DROP POLICY IF EXISTS tenant_isolation ON employees;
CREATE POLICY tenant_isolation ON employees
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- order_assignments ----
DROP POLICY IF EXISTS tenant_isolation ON order_assignments;
CREATE POLICY tenant_isolation ON order_assignments
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- unit_submissions ----
DROP POLICY IF EXISTS tenant_isolation ON unit_submissions;
CREATE POLICY tenant_isolation ON unit_submissions
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- uph_history ----
DROP POLICY IF EXISTS tenant_isolation ON uph_history;
CREATE POLICY tenant_isolation ON uph_history
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- coaching_notes ----
DROP POLICY IF EXISTS tenant_isolation ON coaching_notes;
CREATE POLICY tenant_isolation ON coaching_notes
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- shifts ----
DROP POLICY IF EXISTS tenant_isolation ON shifts;
CREATE POLICY tenant_isolation ON shifts
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- uploaded_files ----
DROP POLICY IF EXISTS tenant_isolation ON uploaded_files;
CREATE POLICY tenant_isolation ON uploaded_files
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- client_trends ----
DROP POLICY IF EXISTS tenant_isolation ON client_trends;
CREATE POLICY tenant_isolation ON client_trends
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- tenant_goals ----
DROP POLICY IF EXISTS tenant_isolation ON tenant_goals;
CREATE POLICY tenant_isolation ON tenant_goals
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- tenant_settings ----
DROP POLICY IF EXISTS tenant_isolation ON tenant_settings;
CREATE POLICY tenant_isolation ON tenant_settings
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());

-- ---- tenant_email_config ----
DROP POLICY IF EXISTS tenant_isolation ON tenant_email_config;
CREATE POLICY tenant_isolation ON tenant_email_config
  FOR ALL USING (tenant_id = get_my_tenant_id())
  WITH CHECK (tenant_id = get_my_tenant_id());


-- --------------------------------------------------------------------------
-- 7. INDEXES on tenant_id for performance
--    CREATE INDEX IF NOT EXISTS makes these safe to re-run.
-- --------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_user_profiles_tenant   ON user_profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_clients_tenant          ON clients(tenant_id);
CREATE INDEX IF NOT EXISTS idx_orders_tenant            ON orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_employees_tenant         ON employees(tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_assignments_tenant ON order_assignments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_unit_submissions_tenant  ON unit_submissions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_uph_history_tenant       ON uph_history(tenant_id);
CREATE INDEX IF NOT EXISTS idx_coaching_notes_tenant    ON coaching_notes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_shifts_tenant            ON shifts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_tenant    ON uploaded_files(tenant_id);
CREATE INDEX IF NOT EXISTS idx_client_trends_tenant     ON client_trends(tenant_id);
CREATE INDEX IF NOT EXISTS idx_uph_history_tenant_work_date ON uph_history(tenant_id, work_date);
CREATE INDEX IF NOT EXISTS idx_uph_history_tenant_emp_work_date ON uph_history(tenant_id, emp_id, work_date);
CREATE INDEX IF NOT EXISTS idx_employees_tenant_department ON employees(tenant_id, department);
CREATE INDEX IF NOT EXISTS idx_coaching_notes_tenant_emp_created_at ON coaching_notes(tenant_id, emp_id, created_at);


-- --------------------------------------------------------------------------
-- 8. RPC: provision_tenant
--    Creates a new tenant and its first admin user_profile in one call.
--    Marked SECURITY DEFINER so it can insert into tenants/user_profiles
--    even before the user has a tenant_id (bypasses RLS).
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION provision_tenant(
  p_user_id    uuid,
  p_tenant_name text,
  p_user_name  text
)
RETURNS uuid AS $$
DECLARE
  new_tid uuid;
BEGIN
  new_tid := gen_random_uuid();
  INSERT INTO tenants (id, name) VALUES (new_tid, p_tenant_name);
  INSERT INTO user_profiles (id, tenant_id, role, name)
    VALUES (p_user_id, new_tid, 'admin', p_user_name);
  RETURN new_tid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- --------------------------------------------------------------------------
-- 8. UNIQUE CONSTRAINT on uph_history to prevent duplicate rows
--    Keyed on (tenant_id, emp_id, work_date, department) — the natural key
--    for one employee's UPH on one date in one department.
-- --------------------------------------------------------------------------
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uph_history_tenant_emp_date_dept_uq'
  ) THEN
    ALTER TABLE uph_history
      ADD CONSTRAINT uph_history_tenant_emp_date_dept_uq
      UNIQUE (tenant_id, emp_id, work_date, department);
  END IF;
END $$;


-- --------------------------------------------------------------------------
-- 9. ERROR REPORTS TABLE — structured error logging for debugging
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_reports (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id  uuid REFERENCES tenants(id),
  category   text NOT NULL,           -- e.g. 'login', 'pipeline', 'email', 'database'
  message    text NOT NULL,
  detail     text,                     -- stack trace or extra context
  user_email text,
  severity   text DEFAULT 'error',     -- 'error', 'warning', 'info'
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Index for fast tenant + time queries
CREATE INDEX IF NOT EXISTS idx_error_reports_tenant_time
  ON error_reports (tenant_id, created_at DESC);

-- RLS: each tenant sees only their own errors
ALTER TABLE error_reports ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation' AND tablename = 'error_reports'
  ) THEN
    CREATE POLICY tenant_isolation ON error_reports
      USING (tenant_id = get_my_tenant_id())
      WITH CHECK (tenant_id = get_my_tenant_id());
  END IF;
END $$;


-- --------------------------------------------------------------------------
-- 10. UNIQUE CONSTRAINT on employees to enable upsert by (emp_id, tenant_id)
-- --------------------------------------------------------------------------
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'employees_tenant_emp_id_uq'
  ) THEN
    -- Remove any duplicates first (keep the most recently created row)
    DELETE FROM employees a
      USING employees b
      WHERE a.emp_id = b.emp_id
        AND a.tenant_id IS NOT DISTINCT FROM b.tenant_id
        AND a.id < b.id;

    ALTER TABLE employees
      ADD CONSTRAINT employees_tenant_emp_id_uq
      UNIQUE (tenant_id, emp_id);
  END IF;
END $$;


-- ============================================================================
-- Done. All tables have tenant_id, RLS is enabled, and policies restrict
-- every table to the authenticated user's tenant.
-- ============================================================================
