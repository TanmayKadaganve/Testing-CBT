#!/usr/bin/env bash
# ==============================================================================
# PyForgeLabs CBT — Stop Local Production Server Stack
# Stops Gunicorn and Execution Worker Daemon cleanly.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="${BASE_DIR}/run"

WEB_PID_FILE="${PID_DIR}/cbt_web.pid"
WORKER_PID_FILE="${PID_DIR}/cbt_worker.pid"

echo "Stopping PyForgeLabs CBT Server Stack..."

if [ -f "$WORKER_PID_FILE" ]; then
    WORKER_PID="$(cat "$WORKER_PID_FILE")"
    if kill -0 "$WORKER_PID" 2>/dev/null; then
        echo "Stopping Execution Worker Daemon (PID: $WORKER_PID)..."
        kill -TERM "$WORKER_PID" || true
        sleep 1
    fi
    rm -f "$WORKER_PID_FILE"
    echo "[OK] Execution Worker Daemon stopped."
fi

if [ -f "$WEB_PID_FILE" ]; then
    WEB_PID="$(cat "$WEB_PID_FILE")"
    if kill -0 "$WEB_PID" 2>/dev/null; then
        echo "Stopping Gunicorn Web Server (PID: $WEB_PID)..."
        kill -TERM "$WEB_PID" || true
        sleep 1
    fi
    rm -f "$WEB_PID_FILE"
    echo "[OK] Web Server stopped."
fi

echo "All services stopped."
