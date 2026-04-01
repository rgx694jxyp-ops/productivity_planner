#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKER="$ROOT_DIR/scripts/email_scheduler_worker.py"
SERVICE_NAME="dpd-email-scheduler"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_DIR="$ROOT_DIR/logs"

if [[ ! -f "$WORKER" ]]; then
  echo "ERROR: Worker script not found: $WORKER"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Run as root (sudo) for systemd install"
  exit 1
fi

if [[ -x "$ROOT_DIR/venv/bin/python3" ]]; then
  PYTHON_BIN="$ROOT_DIR/venv/bin/python3"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_KEY:-}" ]]; then
  echo "ERROR: SUPABASE_URL and SUPABASE_KEY must be exported before install"
  exit 1
fi

mkdir -p "$LOG_DIR"

cat > "$SERVICE_FILE" <<SERVICE
[Unit]
Description=DPD Email Scheduler Worker
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
ExecStart=$PYTHON_BIN $WORKER --interval 60
Restart=always
RestartSec=5
Environment=SUPABASE_URL=${SUPABASE_URL}
Environment=SUPABASE_KEY=${SUPABASE_KEY}
StandardOutput=append:$LOG_DIR/email_scheduler.out.log
StandardError=append:$LOG_DIR/email_scheduler.err.log

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "Installed and started $SERVICE_NAME"
echo "Status: systemctl status $SERVICE_NAME --no-pager"
echo "Logs: tail -f $LOG_DIR/email_scheduler.out.log"
