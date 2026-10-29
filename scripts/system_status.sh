#!/usr/bin/env bash
# ==============================================================================
# PyForgeLabs CBT — System Status & Health Reporter
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="${BASE_DIR}/run"

WEB_PID_FILE="${PID_DIR}/cbt_web.pid"
WORKER_PID_FILE="${PID_DIR}/cbt_worker.pid"

echo "=========================================================="
echo "PyForgeLabs CBT Process & Service Status"
echo "=========================================================="

if [ -f "$WEB_PID_FILE" ] && kill -0 "$(cat "$WEB_PID_FILE")" 2>/dev/null; then
    echo "Gunicorn Web Server: RUNNING (PID: $(cat "$WEB_PID_FILE"))"
else
    echo "Gunicorn Web Server: STOPPED"
fi

if [ -f "$WORKER_PID_FILE" ] && kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
    echo "Execution Worker:   RUNNING (PID: $(cat "$WORKER_PID_FILE"))"
else
    echo "Execution Worker:   STOPPED"
fi

echo ""
echo "Running Django System Health Check..."
"${BASE_DIR}/venv/bin/python" -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from portal.services.system_health import check_system_health
from portal.services.execution_queue import get_queue_metrics

health = check_system_health()
qm = get_queue_metrics()

print(f'Overall Health:     {health[\"overall_status\"]}')
for c in health['checks']:
    print(f' - {c[\"name\"]}: [{c[\"status\"]}] {c[\"detail\"]}')

print(f'\nExecution Queue:')
print(f' - Queued:          {qm[\"queued_count\"]}')
print(f' - Running:         {qm[\"running_count\"]}')
print(f' - Completed (24h): {qm[\"completed_today\"]}')
print(f' - Timed out (24h): {qm[\"timed_out_today\"]}')
"
