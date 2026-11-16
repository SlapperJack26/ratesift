#!/usr/bin/env bash
# ==============================================================================
# Quotelytics Production SQLite Backup Script (WHC Cloud VPS)
# Backs up quotelytics.db online using SQLite WAL-safe .backup API,
# verifies integrity, compresses with gzip, and enforces 30-day retention.
# ==============================================================================

set -euo pipefail

DB_PATH="/srv/quotelytics/data/quotelytics.db"
BACKUP_DIR="/srv/quotelytics/backups"
TIMESTAMP="$(date +'%Y-%m-%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/quotelytics_backup_${TIMESTAMP}.db"
LOG_FILE="/var/log/quotelytics_backup.log"

mkdir -p "${BACKUP_DIR}"

log() {
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "${LOG_FILE}"
}

log "Starting online SQLite WAL backup for Quotelytics..."

if [[ ! -f "${DB_PATH}" ]]; then
    log "ERROR: Database file ${DB_PATH} does not exist!"
    exit 1
fi

# 1. Execute online WAL-safe backup using sqlite3 CLI
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"

# 2. Run PRAGMA integrity_check on the generated snapshot
INTEGRITY=$(sqlite3 "${BACKUP_FILE}" "PRAGMA integrity_check;")
if [[ "${INTEGRITY}" != "ok" ]]; then
    log "ERROR: Backup integrity check failed: ${INTEGRITY}"
    rm -f "${BACKUP_FILE}"
    exit 2
fi

# 3. Compress snapshot
gzip -9 "${BACKUP_FILE}"
log "SUCCESS: Created verified compressed backup: ${BACKUP_FILE}.gz ($(du -h "${BACKUP_FILE}.gz" | cut -f1))"

# 4. Prune backups older than 30 days
DELETED_COUNT=$(find "${BACKUP_DIR}" -name "quotelytics_backup_*.db.gz" -type f -mtime +30 -delete -print | wc -l)
log "Retention policy applied: pruned ${DELETED_COUNT} backup(s) older than 30 days."

log "Backup cycle finished successfully."
