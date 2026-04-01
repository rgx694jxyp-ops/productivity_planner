#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKER="$ROOT_DIR/scripts/email_scheduler_worker.py"
PLIST="$HOME/Library/LaunchAgents/com.dpd.email-scheduler.plist"
LOG_DIR="$ROOT_DIR/logs"

if [[ ! -f "$WORKER" ]]; then
  echo "ERROR: Worker script not found at $WORKER"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR"

if [[ -x "$ROOT_DIR/venv/bin/python3" ]]; then
  PYTHON_BIN="$ROOT_DIR/venv/bin/python3"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_KEY:-}" ]]; then
  echo "ERROR: SUPABASE_URL and SUPABASE_KEY must be exported before install."
  echo "Example:"
  echo "  export SUPABASE_URL='https://xxxx.supabase.co'"
  echo "  export SUPABASE_KEY='eyJ...'
"
  exit 1
fi

if [[ "$SUPABASE_URL" == *"YOUR_PROJECT_REF"* || "$SUPABASE_URL" == *"localhost"* || "$SUPABASE_URL" != https://*.supabase.co* ]]; then
  echo "ERROR: SUPABASE_URL looks invalid: '$SUPABASE_URL'"
  echo "Expected format: https://<project-ref>.supabase.co"
  exit 1
fi

if [[ "$SUPABASE_KEY" == *"YOUR_"* || ${#SUPABASE_KEY} -lt 40 ]]; then
  echo "ERROR: SUPABASE_KEY looks invalid (placeholder or too short)."
  exit 1
fi

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dpd.email-scheduler</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$WORKER</string>
    <string>--interval</string>
    <string>60</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$ROOT_DIR</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>EnvironmentVariables</key>
  <dict>
    <key>SUPABASE_URL</key>
    <string>${SUPABASE_URL}</string>
    <key>SUPABASE_KEY</key>
    <string>${SUPABASE_KEY}</string>
  </dict>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/email_scheduler.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/email_scheduler.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"

echo "Installed and started launch agent: com.dpd.email-scheduler"
echo "Plist: $PLIST"
echo "Logs:  $LOG_DIR/email_scheduler.out.log"
echo "       $LOG_DIR/email_scheduler.err.log"
echo "Status: launchctl list | grep com.dpd.email-scheduler"
