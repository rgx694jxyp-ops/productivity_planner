#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_FILE="$ROOT_DIR/.streamlit/secrets.toml"

trim() {
  local s="$1"
  s="${s#${s%%[![:space:]]*}}"
  s="${s%${s##*[![:space:]]}}"
  echo "$s"
}

extract_secret() {
  local key="$1"
  local file="$2"
  [[ -f "$file" ]] || return 1
  local line
  line=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | head -n 1 || true)
  [[ -n "$line" ]] || return 1
  local value
  value=$(echo "$line" | sed -E 's/^[^=]+=[[:space:]]*//')
  value=$(echo "$value" | sed -E 's/^["\x27]//; s/["\x27][[:space:]]*$//')
  trim "$value"
}

is_valid_url() {
  [[ "$1" =~ ^https://[A-Za-z0-9-]+\.supabase\.co/?$ ]]
}

is_valid_key() {
  local key="$1"
  [[ ${#key} -ge 40 ]] && [[ "$key" != *"YOUR_"* ]]
}

SUPABASE_URL="${SUPABASE_URL:-}"
SUPABASE_SERVICE_ROLE_KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"
SUPABASE_KEY="${SUPABASE_KEY:-}"
USED_SERVICE_ROLE=0

if [[ -z "$SUPABASE_URL" ]]; then
  SUPABASE_URL="$(extract_secret "SUPABASE_URL" "$SECRETS_FILE" || true)"
fi
if [[ -z "$SUPABASE_KEY" ]]; then
  if [[ -n "$SUPABASE_SERVICE_ROLE_KEY" ]]; then
    SUPABASE_KEY="$SUPABASE_SERVICE_ROLE_KEY"
    USED_SERVICE_ROLE=1
  fi
fi
if [[ -z "$SUPABASE_KEY" ]]; then
  SUPABASE_KEY="$(extract_secret "SUPABASE_SERVICE_ROLE_KEY" "$SECRETS_FILE" || true)"
  if [[ -n "$SUPABASE_KEY" ]]; then
    USED_SERVICE_ROLE=1
  fi
fi
if [[ -z "$SUPABASE_KEY" ]]; then
  SUPABASE_KEY="$(extract_secret "SUPABASE_KEY" "$SECRETS_FILE" || true)"
fi

if ! is_valid_url "$SUPABASE_URL"; then
  echo "Enter SUPABASE_URL (https://<project-ref>.supabase.co):"
  read -r SUPABASE_URL
fi
if ! is_valid_key "$SUPABASE_KEY"; then
  echo "Enter SUPABASE_KEY (anon or service role key):"
  read -r SUPABASE_KEY
fi

if ! is_valid_url "$SUPABASE_URL"; then
  echo "ERROR: Invalid SUPABASE_URL: $SUPABASE_URL"
  exit 1
fi
if ! is_valid_key "$SUPABASE_KEY"; then
  echo "ERROR: SUPABASE_KEY looks invalid (placeholder or too short)."
  exit 1
fi

export SUPABASE_URL
export SUPABASE_KEY

echo "Using project URL: $SUPABASE_URL"
if [[ "$USED_SERVICE_ROLE" -ne 1 ]]; then
  echo "WARNING: Using fallback SUPABASE_KEY, not SUPABASE_SERVICE_ROLE_KEY."
  echo "The background scheduler may not be able to read tenant email configs unless you provide a service role key."
fi

case "$(uname -s)" in
  Darwin)
    "$ROOT_DIR/scripts/install_scheduler_launchd.sh"
    echo "Done. Verify with: launchctl list | grep com.dpd.email-scheduler"
    ;;
  Linux)
    echo "Installing Linux systemd service (may prompt for sudo password)..."
    sudo -E "$ROOT_DIR/scripts/install_scheduler_systemd.sh"
    echo "Done. Verify with: systemctl status dpd-email-scheduler --no-pager"
    ;;
  *)
    echo "Unsupported OS in this script: $(uname -s)"
    echo "For Windows, run scripts/install_scheduler_windows.ps1"
    exit 1
    ;;
esac

echo "Logs: $ROOT_DIR/logs/email_scheduler.out.log"
