#!/usr/bin/env bash
# ==============================================================================
# Quotelytics Production SQLite Backup Script (WHC Cloud VPS)
# Backs up quotelytics.db online using SQLite WAL-safe .backup API,
# verifies integrity, compresses with gzip, optionally syncs off-site,
# and enforces 30-day retention.
# ==============================================================================

set -euo pipefail

ENV_FILE="/srv/quotelytics/app/.env"
if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

DB_PATH="${QUOTELYTICS_DB_PATH:-${FAILSAFE_DB_PATH:-/srv/quotelytics/data/quotelytics.db}}"
BACKUP_DIR="${QUOTELYTICS_BACKUP_DIR:-/srv/quotelytics/backups}"
TIMESTAMP="$(date +'%Y-%m-%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/quotelytics_backup_${TIMESTAMP}.db"
LOG_FILE="/var/log/quotelytics_backup.log"

mkdir -p "${BACKUP_DIR}"

log() {
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "${LOG_FILE}"
}

log "Starting online SQLite WAL backup for Quotelytics (${DB_PATH})..."

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
ARCHIVE_PATH="${BACKUP_FILE}.gz"
log "SUCCESS: Created verified compressed backup: ${ARCHIVE_PATH} ($(du -h "${ARCHIVE_PATH}" | cut -f1))"

# 4. Optional off-site replication (rsync or custom CLI hook)
if [[ -n "${OFFSITE_BACKUP_RSYNC_TARGET:-}" && "${OFFSITE_BACKUP_RSYNC_TARGET}" != ReplaceWith* ]]; then
    rsync -az "${ARCHIVE_PATH}" "${OFFSITE_BACKUP_RSYNC_TARGET}"
    log "OFFSITE: Synced ${ARCHIVE_PATH} to ${OFFSITE_BACKUP_RSYNC_TARGET}"
fi

if [[ -n "${OFFSITE_BACKUP_CMD:-}" && "${OFFSITE_BACKUP_CMD}" != ReplaceWith* ]]; then
    BACKUP_ARCHIVE="${ARCHIVE_PATH}" bash -c "${OFFSITE_BACKUP_CMD}"
    log "OFFSITE: Executed custom off-site backup command for ${ARCHIVE_PATH}"
fi

# 5. Prune local backups older than 30 days
DELETED_COUNT=$(find "${BACKUP_DIR}" -name "quotelytics_backup_*.db.gz" -type f -mtime +30 -delete -print | wc -l)
log "Retention policy applied: pruned ${DELETED_COUNT} backup(s) older than 30 days."

log "Backup cycle finished successfully."
