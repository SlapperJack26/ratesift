#!/usr/bin/env bash
# ==============================================================================
# Quotelytics WHC Cloud VPS Automated Server Setup Runbook
# Target OS: Ubuntu 24.04 LTS (Web Hosting Canada - Canadian Data Centre)
# Automates hardening, bootstrap SSL, dependencies, firewall, and services.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/srv/quotelytics/app"
DATA_DIR="/srv/quotelytics/data"
BACKUP_DIR="/srv/quotelytics/backups"
CERTBOT_WEBROOT="/var/www/certbot"
LIVE_CERT_DIR="/etc/letsencrypt/live/quotelytics.ca"

echo "=========================================================="
echo " Starting Quotelytics WHC Server Provisioning Runbook"
echo " Source Deployment Templates: ${SCRIPT_DIR}"
echo "=========================================================="

# 1. Update OS and Install Base Toolchain (Supports Ubuntu 24.04 LTS python3.12 & python3.11)
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get upgrade -y
apt-get install -y \
    python3 python3-venv python3-pip \
    nginx sqlite3 git curl openssl rsync ufw fail2ban \
    certbot python3-certbot-nginx unattended-upgrades || \
apt-get install -y \
    python3.11 python3.11-venv python3.11-pip \
    nginx sqlite3 git curl openssl rsync ufw fail2ban \
    certbot python3-certbot-nginx unattended-upgrades

# 2. Configure Non-Root Deploy User
if ! id "deploy" &>/dev/null; then
    echo "Creating deploy user..."
    useradd -m -s /bin/bash deploy
    usermod -aG sudo deploy
fi

# 3. Create Application Directory Hierarchy
mkdir -p "${APP_DIR}" "${DATA_DIR}" "${BACKUP_DIR}" "${CERTBOT_WEBROOT}"
chown -R deploy:deploy /srv/quotelytics

# 4. Configure Uncomplicated Firewall (UFW)
echo "Configuring UFW firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# 5. Configure Fail2ban for SSH & Nginx
systemctl enable fail2ban
systemctl start fail2ban

# 6. Ensure Bootstrap TLS Files Exist for Day-1 Nginx / Pre-DNS IP Testing
mkdir -p /etc/letsencrypt "${LIVE_CERT_DIR}"

if [[ ! -f /etc/letsencrypt/options-ssl-nginx.conf ]]; then
    echo "Creating bootstrap /etc/letsencrypt/options-ssl-nginx.conf..."
    cat > /etc/letsencrypt/options-ssl-nginx.conf <<'EOF'
ssl_session_cache shared:le_nginx_SSL:10m;
ssl_session_timeout 1440m;
ssl_session_tickets off;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384";
EOF
fi

if [[ ! -f /etc/letsencrypt/ssl-dhparams.pem ]]; then
    echo "Generating Diffie-Hellman parameters (/etc/letsencrypt/ssl-dhparams.pem)..."
    openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048
fi

if [[ ! -f "${LIVE_CERT_DIR}/fullchain.pem" || ! -f "${LIVE_CERT_DIR}/privkey.pem" ]]; then
    echo "Generating 365-day self-signed bootstrap SSL certificate for Phase 5 IP testing..."
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -subj "/CN=quotelytics.ca" \
        -keyout "${LIVE_CERT_DIR}/privkey.pem" \
        -out "${LIVE_CERT_DIR}/fullchain.pem"
fi

# 7. Install Systemd Services & Nginx VHost from ${SCRIPT_DIR}
echo "Installing systemd services and Nginx virtual host..."
cp "${SCRIPT_DIR}/quotelytics.service" /etc/systemd/system/quotelytics.service
cp "${SCRIPT_DIR}/quotelytics-discord-bot.service" /etc/systemd/system/quotelytics-discord-bot.service
cp "${SCRIPT_DIR}/nginx_quotelytics.conf" /etc/nginx/sites-available/quotelytics

ln -sf /etc/nginx/sites-available/quotelytics /etc/nginx/sites-enabled/quotelytics
rm -f /etc/nginx/sites-enabled/default

chmod +x "${SCRIPT_DIR}/backup_db.sh" "${SCRIPT_DIR}/verify_whc_cutover.sh"

nginx -t
systemctl enable nginx
systemctl reload nginx
systemctl daemon-reload

# 8. Configure Automated Nightly Backup Cron (3:00 AM server time)
CRON_JOB="0 3 * * * ${APP_DIR}/deployment/backup_db.sh >> /var/log/quotelytics_backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "backup_db.sh" ; echo "${CRON_JOB}") | crontab -

echo "=========================================================="
echo " Base Server Provisioning Complete!"
echo " Next Steps:"
echo " 1. Ensure code is cloned in ${APP_DIR} with Python .venv"
echo " 2. Populate ${APP_DIR}/.env with production secrets"
echo " 3. Copy production SQLite database to ${DATA_DIR}/quotelytics.db"
echo " 4. Start services: sudo systemctl enable --now quotelytics quotelytics-discord-bot"
echo " 5. Verify pre-DNS: bash ${APP_DIR}/deployment/verify_whc_cutover.sh"
echo " 6. Point DNS and issue SSL: sudo certbot --nginx -d quotelytics.ca -d www.quotelytics.ca"
echo "=========================================================="
