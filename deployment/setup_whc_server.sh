#!/usr/bin/env bash
# ==============================================================================
# Quotelytics WHC Cloud VPS Automated Server Setup Runbook
# Target OS: Ubuntu 24.04 LTS (Web Hosting Canada - Canadian Data Centre)
# Automates hardening, dependencies, directories, firewall, and services.
# ==============================================================================

set -euo pipefail

echo "=========================================================="
echo " Starting Quotelytics WHC Server Provisioning Runbook"
echo "=========================================================="

# 1. Update OS and Install Base Toolchain (Supports Ubuntu 24.04 LTS python3.12 & python3.11)
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get upgrade -y
apt-get install -y \
    python3 python3-venv python3-pip \
    nginx sqlite3 git curl ufw fail2ban \
    certbot python3-certbot-nginx unattended-upgrades || \
apt-get install -y \
    python3.11 python3.11-venv python3-pip \
    nginx sqlite3 git curl ufw fail2ban \
    certbot python3-certbot-nginx unattended-upgrades

# 2. Configure Non-Root Deploy User
if ! id "deploy" &>/dev/null; then
    echo "Creating deploy user..."
    useradd -m -s /bin/bash deploy
    usermod -aG sudo deploy
fi

# 3. Create Application Directory Hierarchy
mkdir -p /srv/quotelytics/app
mkdir -p /srv/quotelytics/data
mkdir -p /srv/quotelytics/backups
mkdir -p /var/www/certbot
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

# 6. Install Systemd Service & Nginx VHost
echo "Installing service and web server templates..."
cp /srv/quotelytics/app/deployment/quotelytics.service /etc/systemd/system/quotelytics.service
cp /srv/quotelytics/app/deployment/nginx_quotelytics.conf /etc/nginx/sites-available/quotelytics

# Enable site if not already enabled
if [[ ! -f /etc/nginx/sites-enabled/quotelytics ]]; then
    ln -s /etc/nginx/sites-available/quotelytics /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
fi

# 7. Configure Automated Nightly Backup Cron
CRON_JOB="0 3 * * * /srv/quotelytics/app/deployment/backup_db.sh >> /var/log/quotelytics_backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "backup_db.sh" ; echo "${CRON_JOB}") | crontab -

echo "=========================================================="
echo " Base Server Provisioning Complete!"
echo " Next Steps:"
echo " 1. Clone repo into /srv/quotelytics/app as deploy user"
echo " 2. Populate /srv/quotelytics/app/.env with production secrets"
echo " 3. Copy production SQLite database to /srv/quotelytics/data/quotelytics.db"
echo " 4. Run certbot: sudo certbot --nginx -d quotelytics.ca -d www.quotelytics.ca"
echo " 5. Start app: sudo systemctl daemon-reload && sudo systemctl enable --now quotelytics"
echo "=========================================================="
