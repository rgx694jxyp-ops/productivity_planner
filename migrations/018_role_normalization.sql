-- =============================================================================
-- Migration 018: Role normalization
--
-- Renames the ambiguous "member" role to "manager" for semantic clarity.
-- Roles are now: viewer (read-only), manager (read + write + import), admin (all).
--
-- Safe to run multiple times (idempotent UPDATE).
-- =============================================================================

-- 1. Rename existing "member" rows to "manager"
UPDATE user_profiles
SET role = 'manager'
WHERE role = 'member';

-- 2. Add a CHECK constraint so only valid roles can be stored going forward.
--    Uses ADD CONSTRAINT IF NOT EXISTS (Postgres 9.6+).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'user_profiles_role_check'
      AND conrelid = 'user_profiles'::regclass
  ) THEN
    ALTER TABLE user_profiles
      ADD CONSTRAINT user_profiles_role_check
        CHECK (role IN ('viewer', 'manager', 'admin'));
  END IF;
END $$;

-- 3. Patch the join-tenant RPC so new members land as "manager" by default.
CREATE OR REPLACE FUNCTION join_tenant_by_invite(
  p_user_id   uuid,
  p_invite_code text,
  p_user_name   text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  tenant_row tenants%ROWTYPE;
BEGIN
  SELECT * INTO tenant_row
  FROM tenants
  WHERE invite_code = p_invite_code;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('error', 'invalid_invite_code');
  END IF;

  INSERT INTO user_profiles (id, tenant_id, role, name)
  VALUES (p_user_id, tenant_row.id, 'manager', p_user_name)
  ON CONFLICT (id) DO UPDATE
    SET tenant_id = EXCLUDED.tenant_id,
        role      = 'manager',
        name      = EXCLUDED.name;

  RETURN jsonb_build_object('tenant_id', tenant_row.id, 'role', 'manager');
END;
$$;
