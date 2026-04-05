#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v supabase >/dev/null 2>&1; then
  echo "ERROR: Supabase CLI not found. Install it first." >&2
  exit 1
fi

echo "Checking required Supabase function secrets..."
SECRETS_OUT="$(supabase secrets list 2>/dev/null || true)"
if [[ -z "$SECRETS_OUT" ]]; then
  echo "ERROR: Could not read Supabase secrets. Make sure you are logged in and linked to the right project." >&2
  exit 1
fi

required=(
  "STRIPE_WEBHOOK_SECRET"
  "STRIPE_SECRET_KEY"
  "SUPABASE_URL"
  "STRIPE_PRICE_STARTER"
  "STRIPE_PRICE_PRO"
  "STRIPE_PRICE_BUSINESS"
)

for key in "${required[@]}"; do
  if ! grep -q "${key}" <<<"$SECRETS_OUT"; then
    echo "ERROR: Missing required secret: ${key}" >&2
    exit 1
  fi
done

if ! grep -q "SERVICE_ROLE_KEY" <<<"$SECRETS_OUT" && ! grep -q "SUPABASE_SERVICE_ROLE_KEY" <<<"$SECRETS_OUT"; then
  echo "ERROR: Missing service role secret. Set SERVICE_ROLE_KEY or SUPABASE_SERVICE_ROLE_KEY." >&2
  exit 1
fi

echo "Deploying stripe-webhook with JWT verification disabled for Stripe callbacks..."
# The Supabase CLI resolves its workdir by walking up from cwd to find supabase/config.toml.
# We created supabase/config.toml in this project directory (zcreqyglrrvlbiduvbto).
# If the CLI still resolves to the home-dir supabase project, sync the function file there too.
SUPABASE_HOME_FUNC="${HOME}/supabase/functions/stripe-webhook"
PROJECT_FUNC="supabase/functions/stripe-webhook"
if [[ -d "$SUPABASE_HOME_FUNC" ]]; then
  cp "${PROJECT_FUNC}/index.ts" "${SUPABASE_HOME_FUNC}/index.ts"
  cp "${PROJECT_FUNC}/deno.json" "${SUPABASE_HOME_FUNC}/deno.json"
fi
supabase functions deploy stripe-webhook --no-verify-jwt

echo "Success: stripe-webhook deployed with --no-verify-jwt"
