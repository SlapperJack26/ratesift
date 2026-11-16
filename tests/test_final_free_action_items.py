"""
Automated Verification Suite for the Final Free Action Items:
1. Search Engine Directives (/robots.txt and /sitemap.xml)
2. CASL One-Click Unsubscribe Flow (/unsubscribe & POST /api/auth/unsubscribe)
3. WHC Server Deployment & Backup Package (deployment/)
4. Ontario Technology & IP Assignment Agreement (incorporation_documents/09)
5. Console Billing UI Integration
"""
import os
import pytest
from fastapi.testclient import TestClient

from main import app
from services.quotelytics_db_service import get_connection


# ==============================================================================
# 1. SEO ROBOTS.TXT & SITEMAP.XML
# ==============================================================================

def test_01_robots_txt_spec_compliance():
    client = TestClient(app)
    res = client.get("/robots.txt")
    assert res.status_code == 200
    assert "text/plain" in res.headers.get("content-type", "")
    body = res.text

    # Crawl directives
    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Allow: /pricing" in body
    assert "Allow: /demo" in body
    assert "Allow: /help" in body
    assert "Allow: /terms" in body
    assert "Allow: /privacy" in body
    assert "Disallow: /console/" in body
    assert "Disallow: /api/" in body
    assert "Sitemap: https://quotelytics.ca/sitemap.xml" in body


def test_02_sitemap_xml_spec_compliance():
    client = TestClient(app)
    res = client.get("/sitemap.xml")
    assert res.status_code == 200
    assert "application/xml" in res.headers.get("content-type", "")
    body = res.text

    assert '<?xml version="1.0" encoding="UTF-8"?>' in body
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in body
    assert "<loc>https://quotelytics.ca/</loc>" in body
    assert "<loc>https://quotelytics.ca/pricing</loc>" in body
    assert "<loc>https://quotelytics.ca/demo</loc>" in body
    assert "<loc>https://quotelytics.ca/help</loc>" in body
    assert "<loc>https://quotelytics.ca/terms</loc>" in body
    assert "<loc>https://quotelytics.ca/privacy</loc>" in body
    assert "<loc>https://quotelytics.ca/dpa</loc>" in body
    assert "<loc>https://quotelytics.ca/subprocessors</loc>" in body


# ==============================================================================
# 2. CASL ONE-CLICK UNSUBSCRIBE FLOW
# ==============================================================================

def test_03_unsubscribe_public_page_renders():
    client = TestClient(app)
    res = client.get("/unsubscribe?email=dispatcher@testlogistics.ca")
    assert res.status_code == 200
    html = res.text
    assert "<title>Quotelytics | Unsubscribe from Marketing Emails</title>" in html
    assert "CASL" in html
    assert "dispatcher@testlogistics.ca" in html or "unsub-email" in html
    assert "289-929-8565" in html


def test_04_api_unsubscribe_revokes_consent_and_logs_audit():
    client = TestClient(app)

    # 1. Register a user who initially opts into marketing
    test_email = "opted_in_broker@canadianfreight.ca"
    reg_res = client.post("/api/auth/register", data={
        "name": "Opted In Broker",
        "email": test_email,
        "password": "Password10CharsMin!",
        "company": "Opted In Transport",
        "origin_zip": "M5V 2T6",
        "marketing_opt_in": "true",
        "terms": "true"
    })
    assert reg_res.status_code == 200
    user_id = reg_res.json()["user"]["id"]

    # Verify marketing_opt_in is 1
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT marketing_opt_in FROM users WHERE id = ?", (user_id,))
    assert c.fetchone()["marketing_opt_in"] == 1
    conn.close()

    # 2. Submit one-click unsubscribe
    unsub_res = client.post("/api/auth/unsubscribe", json={"email": test_email})
    assert unsub_res.status_code == 200
    data = unsub_res.json()
    assert data["status"] == "success"
    assert data["consent_id"].startswith("mc_")

    # 3. Verify database flag updated to 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT marketing_opt_in FROM users WHERE id = ?", (user_id,))
    assert c.fetchone()["marketing_opt_in"] == 0

    # 4. Verify CASL audit log recorded
    c.execute("""
    SELECT * FROM marketing_consent_logs
    WHERE email = ? AND consent_type = 'ONE_CLICK_UNSUBSCRIBE'
    ORDER BY created_at DESC
    """, (test_email,))
    log_row = c.fetchone()
    assert log_row is not None
    assert log_row["consented"] == 0
    assert log_row["user_id"] == user_id
    conn.close()


def test_05_api_unsubscribe_handles_unregistered_email():
    client = TestClient(app)
    unregistered = "cold_lead@randombrokerage.ca"
    res = client.post("/api/auth/unsubscribe", json={"email": unregistered})
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # Verify audit log captures unregistered email revocation
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM marketing_consent_logs WHERE email = ?", (unregistered,))
    row = c.fetchone()
    assert row is not None
    assert row["consented"] == 0
    assert row["user_id"] is None
    conn.close()


# ==============================================================================
# 3. DEPLOYMENT PACKAGE SPECIFICATION VERIFICATION
# ==============================================================================

def test_06_deployment_package_files_exist_and_valid():
    repo_root = os.path.dirname(os.path.dirname(__file__))

    # 1. Systemd unit
    service_file = os.path.join(repo_root, "deployment", "quotelytics.service")
    assert os.path.isfile(service_file)
    with open(service_file, "r", encoding="utf-8") as f:
        svc_content = f.read()
    assert "gunicorn main:app" in svc_content
    assert "UvicornWorker" in svc_content
    assert "EnvironmentFile=/srv/quotelytics/app/.env" in svc_content

    # 2. Nginx configuration
    nginx_file = os.path.join(repo_root, "deployment", "nginx_quotelytics.conf")
    assert os.path.isfile(nginx_file)
    with open(nginx_file, "r", encoding="utf-8") as f:
        nginx_content = f.read()
    assert "server_name quotelytics.ca www.quotelytics.ca;" in nginx_content
    assert "client_max_body_size 25M;" in nginx_content
    assert "proxy_pass http://127.0.0.1:8000;" in nginx_content
    assert "X-Data-Residency" in nginx_content
    assert "CA_CENTRAL_WHC" in nginx_content

    # 3. Database backup script
    backup_file = os.path.join(repo_root, "deployment", "backup_db.sh")
    assert os.path.isfile(backup_file)
    with open(backup_file, "r", encoding="utf-8") as f:
        bak_content = f.read()
    assert ".backup" in bak_content
    assert "PRAGMA integrity_check;" in bak_content
    assert "gzip -9" in bak_content
    assert "-mtime +30" in bak_content

    # 4. Setup runbook
    setup_file = os.path.join(repo_root, "deployment", "setup_whc_server.sh")
    assert os.path.isfile(setup_file)
    with open(setup_file, "r", encoding="utf-8") as f:
        setup_content = f.read()
    assert "python3.11" in setup_content
    assert "ufw allow OpenSSH" in setup_content
    assert "fail2ban" in setup_content


# ==============================================================================
# 4. TECHNOLOGY & IP ASSIGNMENT AGREEMENT
# ==============================================================================

def test_07_ip_assignment_agreement_document_structure():
    repo_root = os.path.dirname(os.path.dirname(__file__))
    doc_path = os.path.join(repo_root, "incorporation_documents", "09_Technology_and_IP_Assignment_Agreement.md")
    assert os.path.isfile(doc_path)
    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "TECHNOLOGY AND INTELLECTUAL PROPERTY ASSIGNMENT AGREEMENT" in content
    assert "Province of Ontario" in content
    assert "WAIVER OF MORAL RIGHTS" in content
    assert "Section 14.1 of the *Copyright Act* (Canada)" in content
    assert "quotelytics.ca" in content
    assert "Schedule \"A\"" in content


# ==============================================================================
# 5. CONSOLE BILLING UI INTEGRATION
# ==============================================================================

def test_08_console_account_billing_ui_wired():
    repo_root = os.path.dirname(os.path.dirname(__file__))
    account_path = os.path.join(repo_root, "templates", "console", "account.html")
    assert os.path.isfile(account_path)
    with open(account_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Customer Portal button and handler
    assert "Customer Portal" in content
    assert "openCustomerPortal" in content
    assert "/api/billing/portal" in content

    # Checkout session handler
    assert "/api/billing/checkout" in content
    assert "switchPlanTo" in content
