#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/6] Python syntax compile"
python3 -m py_compile app.py database.py goals.py ranker.py trends.py settings.py

echo "[2/6] Required files present"
test -f migrations/001_setup.sql
test -f migrations/002_subscriptions.sql
test -f supabase/functions/stripe-webhook/index.ts

echo "[3/6] Known bad character scan (replacement chars)"
if command -v rg >/dev/null 2>&1; then
  if rg -n "�" app.py database.py >/dev/null 2>&1; then
    echo "ERROR: Replacement character found in core files"
    rg -n "�" app.py database.py || true
    exit 1
  fi
else
  if grep -n "�" app.py database.py >/dev/null 2>&1; then
    echo "ERROR: Replacement character found in core files"
    grep -n "�" app.py database.py || true
    exit 1
  fi
fi

echo "[4/6] Env var check"
if [[ -z "${SUPABASE_URL:-}" ]] || [[ -z "${SUPABASE_KEY:-}" ]]; then
  echo "WARN: SUPABASE_URL/SUPABASE_KEY are not set in current shell"
fi

echo "[5/6] Git status summary"
git status --short

echo "[6/7] Core sanity grep"
if command -v rg >/dev/null 2>&1; then
  rg -n "_current_page_key|goto_page = \"productivity\"|def get_tenant_id\(|def batch_store_uph_history" app.py database.py >/dev/null
else
  grep -n "_current_page_key\|goto_page = \"productivity\"\|def get_tenant_id(\|def batch_store_uph_history" app.py database.py >/dev/null
fi

echo "[7/7] Runtime smoke tests"
python3 scripts/smoke_test.py

echo "Predeploy check passed"
