#!/usr/bin/env bash
# ==============================================================================
# PyForgeLabs CBT — Disaster Recovery Database Restoration Script
# Restores the examination database from a verified local backup archive.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BASE_DIR}/backups"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <path_to_backup_file.gz>"
    echo ""
    echo "Available backups in ${BACKUP_DIR}:"
    ls -lh "${BACKUP_DIR}" || true
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file '$BACKUP_FILE' not found."
    exit 1
fi

echo "=========================================================="
echo "WARNING: You are about to restore the database from:"
echo "         ${BACKUP_FILE}"
echo "=========================================================="

if [[ "$BACKUP_FILE" == *postgres* ]]; then
    if [ -z "${DATABASE_URL:-}" ]; then
        echo "Error: DATABASE_URL environment variable must be set to restore PostgreSQL."
        exit 1
    fi
    echo "Restoring to PostgreSQL: ${DATABASE_URL}..."
    gunzip -c "$BACKUP_FILE" | psql "$DATABASE_URL"
    echo "[OK] PostgreSQL restored successfully."
else
    TARGET_DB="${BASE_DIR}/db.sqlite3"
    PRE_RESTORE_BACKUP="${TARGET_DB}.pre_restore_$(date +"%Y%m%d_%H%M%S")"
    if [ -f "$TARGET_DB" ]; then
        echo "Safety snapshot of active db.sqlite3 -> ${PRE_RESTORE_BACKUP}"
        cp "$TARGET_DB" "$PRE_RESTORE_BACKUP"
    fi
    gunzip -c "$BACKUP_FILE" > "$TARGET_DB"
    echo "[OK] SQLite database restored to ${TARGET_DB}."
fi

# Run Django checks after restoration
echo "Verifying restored database with Django check..."
"${BASE_DIR}/venv/bin/python" "${BASE_DIR}/manage.py" check
echo "[SUCCESS] Database restoration complete and operational!"
