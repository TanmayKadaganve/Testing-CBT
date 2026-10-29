#!/usr/bin/env bash
# ==============================================================================
# PyForgeLabs CBT — Start Local Production Server Stack
# Starts Gunicorn application server and the Execution Worker Daemon.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="${BASE_DIR}/run"
LOG_DIR="${BASE_DIR}/logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

WEB_PID_FILE="${PID_DIR}/cbt_web.pid"
WORKER_PID_FILE="${PID_DIR}/cbt_worker.pid"

echo "=========================================================="
echo "Starting PyForgeLabs CBT Production Server Stack..."
echo "=========================================================="

# Check if already running
if [ -f "$WEB_PID_FILE" ] && kill -0 "$(cat "$WEB_PID_FILE")" 2>/dev/null; then
    echo "Warning: CBT Web Server is already running (PID: $(cat "$WEB_PID_FILE"))."
else
    echo "Starting Gunicorn WSGI Web Server..."
    "${BASE_DIR}/venv/bin/gunicorn" \
        -c "${BASE_DIR}/deploy/gunicorn.conf.py" \
        --pid "$WEB_PID_FILE" \
        --daemon \
        config.wsgi:application
    echo "[OK] Web Server started (PID: $(cat "$WEB_PID_FILE"))."
fi

if [ -f "$WORKER_PID_FILE" ] && kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
    echo "Warning: CBT Execution Worker Daemon is already running (PID: $(cat "$WORKER_PID_FILE"))."
else
    echo "Starting Code Execution Worker Daemon..."
    nohup "${BASE_DIR}/venv/bin/python" "${BASE_DIR}/manage.py" run_execution_worker \
        --concurrency=4 \
        >> "${LOG_DIR}/worker.log" 2>&1 &
    echo $! > "$WORKER_PID_FILE"
    echo "[OK] Execution Worker Daemon started (PID: $(cat "$WORKER_PID_FILE"))."
fi

echo ""
echo "Server stack is running!"
echo "- Web portal URL: http://127.0.0.1:8000/"
echo "- Admin dashboard: http://127.0.0.1:8000/admin/dashboard/"
echo "- Worker logs: ${LOG_DIR}/worker.log"
echo "- Server logs: ${LOG_DIR}/cbt_server.log"
