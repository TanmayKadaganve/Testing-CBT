#!/usr/bin/env bash
# ==============================================================================
# PyForgeLabs CBT — Automated Database Backup Script
# Creates verified, timestamped backups of the active CBT database.
# Retains 7 days of backups locally.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BASE_DIR}/backups"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"

mkdir -p "$BACKUP_DIR"

echo "=========================================================="
echo "PyForgeLabs CBT Database Backup — ${TIMESTAMP}"
echo "=========================================================="

# Check if PostgreSQL is configured via environment
if [ -n "${DATABASE_URL:-}" ] && [[ "${DATABASE_URL}" == postgres* ]]; then
    echo "Detected PostgreSQL target. Generating pg_dump..."
    BACKUP_FILE="${BACKUP_DIR}/cbt_postgres_${TIMESTAMP}.sql.gz"
    
    # Extract connection parameters from DATABASE_URL
    pg_dump "$DATABASE_URL" --format=plain --no-owner --clean | gzip > "$BACKUP_FILE"
    echo "[OK] PostgreSQL backup created: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
else
    echo "Using local SQLite database: ${BASE_DIR}/db.sqlite3"
    BACKUP_FILE="${BACKUP_DIR}/cbt_sqlite_${TIMESTAMP}.sqlite3.gz"
    
    if [ -f "${BASE_DIR}/db.sqlite3" ]; then
        gzip -c "${BASE_DIR}/db.sqlite3" > "$BACKUP_FILE"
        echo "[OK] SQLite backup created: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
    else
        echo "[ERROR] ${BASE_DIR}/db.sqlite3 does not exist!"
        exit 1
    fi
fi

# Verify backup file size is greater than 100 bytes
if [ "$(wc -c < "$BACKUP_FILE")" -lt 100 ]; then
    echo "[CRITICAL] Backup verification failed: file size is suspiciously small!"
    exit 1
fi

echo "[OK] Backup integrity check passed."

# Prune backups older than 7 days
echo "Pruning backups older than 7 days..."
find "$BACKUP_DIR" -type f \( -name "cbt_*.gz" -o -name "db.sqlite3.pre_*" \) -mtime +7 -delete

echo "Backup routine completed successfully."
