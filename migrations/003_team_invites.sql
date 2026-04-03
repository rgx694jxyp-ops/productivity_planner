-- ============================================================================
-- 003_team_invites.sql
-- Adds invite-code-based team membership to DPD Web
--
-- Safe to run multiple times (uses IF NOT EXISTS / DO $$ blocks throughout).
-- ============================================================================

-- --------------------------------------------------------------------------
-- 1. Add invite_code column to tenants
--    Each tenant gets a unique, short hex code that admins can share.
--    regenerate_invite_code() will rotate it on demand.
-- --------------------------------------------------------------------------
ALTER TABLE tenants
  ADD COLUMN IF NOT EXISTS invite_code text UNIQUE;

-- Back-fill existing rows with a random 6-byte hex code
UPDATE tenants
SET    invite_code = encode(gen_random_bytes(6), 'hex')
WHERE  invite_code IS NULL;

-- --------------------------------------------------------------------------
-- 2. Add role column to user_profiles if missing
--    Allows 'admin' and 'member' roles within a tenant.
-- --------------------------------------------------------------------------
ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'member';

-- --------------------------------------------------------------------------
-- 3. RPC: regenerate_invite_code(p_tenant_id)
--    Generates a new random invite code for the tenant.
--    Only admins within that tenant should call this; enforce in app logic.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION regenerate_invite_code(p_tenant_id uuid)
RETURNS text AS $$
DECLARE
  new_code text;
BEGIN
  new_code := encode(gen_random_bytes(6), 'hex');
  UPDATE tenants SET invite_code = new_code WHERE id = p_tenant_id;
  RETURN new_code;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- --------------------------------------------------------------------------
-- 4. RPC: join_tenant_by_invite(p_user_id, p_invite_code, p_user_name)
--    Looks up the tenant by invite code and inserts a user_profile row.
--    Returns the tenant_id on success, raises exception on invalid code.
--    SECURITY DEFINER so it can insert user_profiles before the user exists
--    in the profiles table (i.e. new signups don't have a tenant yet).
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION join_tenant_by_invite(
  p_user_id    uuid,
  p_invite_code text,
  p_user_name  text DEFAULT ''
)
RETURNS uuid AS $$
DECLARE
  target_tid uuid;
BEGIN
  -- Look up the tenant by invite code (case-insensitive)
  SELECT id INTO target_tid
  FROM   tenants
  WHERE  lower(trim(invite_code)) = lower(trim(p_invite_code));

  IF target_tid IS NULL THEN
    RAISE EXCEPTION 'Invalid invite code: %', p_invite_code;
  END IF;

  -- Upsert user_profile so re-inviting the same user is idempotent
  INSERT INTO user_profiles (id, tenant_id, role, name)
  VALUES (p_user_id, target_tid, 'member', p_user_name)
  ON CONFLICT (id) DO UPDATE
    SET tenant_id = target_tid,
        name      = COALESCE(NULLIF(p_user_name, ''), user_profiles.name);

  RETURN target_tid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
