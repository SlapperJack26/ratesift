#!/usr/bin/env bash
# ==============================================================================
# Quotelytics WHC Cutover Verification Script
# Validates systemd services, Nginx config & TLS headers, /healthz GET/HEAD,
# and SQLite WAL integrity on the WHC Cloud VPS.
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

echo "=========================================================="
echo " Verifying Quotelytics WHC Cutover Status"
echo "=========================================================="

echo "[1/6] Checking systemd service quotelytics..."
systemctl is-active --quiet quotelytics
echo "  PASS: quotelytics is active"

if systemctl list-unit-files | grep -q "quotelytics-discord-bot.service"; then
    if systemctl is-active --quiet quotelytics-discord-bot; then
        echo "  PASS: quotelytics-discord-bot is active"
    else
        echo "  WARN: quotelytics-discord-bot is installed but not active"
    fi
fi

echo "[2/6] Validating Nginx configuration..."
nginx -t

echo "[3/6] Checking upstream GET /healthz on 127.0.0.1:8000..."
curl -fsS http://127.0.0.1:8000/healthz
echo ""

echo "[4/6] Checking upstream HEAD /healthz on 127.0.0.1:8000..."
curl -fsSI http://127.0.0.1:8000/healthz | head -n 5

echo "[5/6] Checking Nginx HTTPS proxy & X-Data-Residency header..."
curl -ksSI -H "Host: quotelytics.ca" https://127.0.0.1/healthz | grep -i "X-Data-Residency: CA_CENTRAL_WHC"

echo "[6/6] Checking SQLite WAL integrity at ${DB_PATH}..."
if [[ ! -f "${DB_PATH}" ]]; then
    echo "  FAIL: Database file missing at ${DB_PATH}" >&2
    exit 1
fi
INTEGRITY="$(sqlite3 "${DB_PATH}" "PRAGMA integrity_check;")"
if [[ "${INTEGRITY}" != "ok" ]]; then
    echo "  FAIL: SQLite integrity_check returned: ${INTEGRITY}" >&2
    exit 1
fi
echo "  PASS: SQLite integrity_check = ok"

echo "=========================================================="
echo " WHC Cutover Verification PASSED!"
echo "=========================================================="
