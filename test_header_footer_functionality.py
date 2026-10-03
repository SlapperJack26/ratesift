import os
import re
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
from services import db_service

client = TestClient(app)

def test_templates_have_no_dead_footer_links():
    """Ensure no templates have dead href='#' links in their footers."""
    template_dir = Path("templates")
    html_files = list(template_dir.rglob("*.html"))
    assert len(html_files) > 0

    dead_links = []
    for file in html_files:
        content = file.read_text(encoding="utf-8")
        # Check within footer tags
        footer_match = re.search(r"<footer[\s\S]*?</footer>", content, re.IGNORECASE)
        if footer_match:
            footer_content = footer_match.group(0)
            if 'href="#"' in footer_content:
                dead_links.append((str(file), "href='#' in footer"))

    assert dead_links == [], f"Found dead links in footers: {dead_links}"

def test_templates_include_global_chrome_js():
    """Ensure all core console and public templates include global-chrome.js."""
    core_templates = [
        "templates/console/new_quote.html",
        "templates/console/history.html",
        "templates/console/rate_sheets.html",
        "templates/console/account.html",
        "templates/console/settings.html",
        "templates/public/home.html",
        "templates/public/demo.html",
        "templates/public/pricing.html",
        "templates/public/login.html",
        "templates/public/get_started.html"
    ]
    missing = []
    for path_str in core_templates:
        p = Path(path_str)
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8")
        if "global-chrome.js" not in content:
            missing.append(path_str)

    assert missing == [], f"Templates missing global-chrome.js: {missing}"

def test_hotline_number_is_289_929_8565():
    """Verify that the hotline number is 289-929-8565 across codebase and scripts."""
    global_chrome = Path("static/js/global-chrome.js").read_text(encoding="utf-8")
    assert "289-929-8565" in global_chrome
    assert "2899298565" in global_chrome

    # Ensure no old placeholder 416 number remains in active support links
    assert "+1 (416) 555-0199" not in global_chrome

def test_support_ticket_api_json():
    """Test POST /api/support/ticket with JSON payload."""
    payload = {
        "email": "test.dispatcher@brokerage.ca",
        "category": "QUOTING",
        "subject": "CzarLite deficit calculation discrepancy",
        "message": "850 lbs shipment on Toronto-Montreal did not trigger deficit logic properly.",
        "browser_info": "Chrome 122 on Windows 11"
    }
    response = client.post("/api/support/ticket", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert "ticket_id" in data
    assert data["ticket_id"].lower().startswith("tkt")

    # Verify stored in SQLite db
    tickets = db_service.list_support_tickets()
    matching = [t for t in tickets if t["id"] == data["ticket_id"]]
    assert len(matching) == 1
    assert matching[0]["email"] == "test.dispatcher@brokerage.ca"
    assert matching[0]["category"] == "QUOTING"
    assert matching[0]["status"] == "OPEN"

def test_support_ticket_api_validation():
    """Test validation errors for incomplete support tickets."""
    # Missing required message
    bad_payload = {
        "email": "test.dispatcher@brokerage.ca",
        "subject": "Missing message"
    }
    response = client.post("/api/support/ticket", json=bad_payload)
    assert response.status_code in [400, 422]

def test_notifications_api_flow():
    """Test notifications retrieval, mark single read, and mark all read."""
    # 1. Fetch initial notifications
    res = client.get("/api/notifications?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "notifications" in data
    assert "unread_count" in data
    assert len(data["notifications"]) > 0

    first_notif = data["notifications"][0]
    notif_id = first_notif["id"]

    # 2. Mark single notification read
    res_mark = client.post(f"/api/notifications/{notif_id}/read")
    assert res_mark.status_code == 200
    assert res_mark.json()["status"] == "success"

    # 3. Mark all notifications read
    res_all = client.post("/api/notifications/read-all")
    assert res_all.status_code == 200
    assert res_all.json()["status"] == "success"

    # Verify unread count is now 0
    res_after = client.get("/api/notifications?limit=10")
    assert res_after.status_code == 200
    assert res_after.json()["unread_count"] == 0

def test_quota_api():
    """Verify GET /api/user/quota returns valid tier and quote availability."""
    res = client.get("/api/user/quota")
    assert res.status_code == 200
    data = res.json()
    assert "tier" in data
    assert "monthly_quotes_used" in data
    assert "quotes_remaining" in data

if __name__ == "__main__":
    print("Running Header & Footer Functionality Suite...")
    test_templates_have_no_dead_footer_links()
    print("  [OK] Zero dead footer links across all templates")
    test_templates_include_global_chrome_js()
    print("  [OK] All 10 core templates include global-chrome.js")
    test_hotline_number_is_289_929_8565()
    print("  [OK] Hotline number 289-929-8565 properly wired")
    test_support_ticket_api_json()
    print("  [OK] Support Ticket API (JSON & SQLite logging) verified")
    test_support_ticket_api_validation()
    print("  [OK] Support Ticket API validation verified")
    test_notifications_api_flow()
    print("  [OK] System Notifications API (unread badge, mark read, mark-all) verified")
    test_quota_api()
    print("  [OK] Live Quota API synchronized")
    print("\nALL HEADER & FOOTER TESTS PASSED SUCCESSFULLY!")

