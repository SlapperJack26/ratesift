"""
Automated Verification Suite for Private Beta-Proofing:
1. Public self-registration (POST /api/auth/register) is blocked (HTTP 403) when BETA_INVITE_ONLY is active (default).
2. Online payments & subscriptions (POST /api/billing/checkout, POST /api/billing/portal) are blocked (HTTP 403).
3. Public 'Request Beta Access' intake (POST /api/beta/request-access) stores requests as PENDING.
4. Admin-only account provisioning (POST /api/admin/users/provision) requires ADMIN role (401/403 otherwise),
   creates the user on the requested tier, marks the beta request PROVISIONED, and allows login.
5. Public pages (/, /pricing, /get-started, /demo, /login) display 'Request Beta Access'.
"""
import uuid
from fastapi.testclient import TestClient

from main import app
from services.auth_service import register_and_create_session
from services.db_service import get_connection, init_db


def test_01_public_self_registration_blocked_in_beta(monkeypatch):
    monkeypatch.delenv("QUOTELYTICS_BETA_INVITE_ONLY", raising=False)
    client = TestClient(app)
    res = client.post(
        "/api/auth/register",
        data={
            "name": "Unauthorized Signup",
            "email": f"blocked_{uuid.uuid4().hex[:8]}@brokerage.ca",
            "company": "Blocked Co",
            "origin_zip": "M5V 2T6",
            "password": "StrongPassword2026!",
            "terms_accepted": "true",
        },
    )
    assert res.status_code == 403
    assert "Private Beta" in res.json()["detail"]


def test_02_billing_checkout_and_portal_blocked_in_beta(monkeypatch):
    monkeypatch.delenv("QUOTELYTICS_BETA_INVITE_ONLY", raising=False)
    init_db()
    _, token = register_and_create_session(
        name="Beta Broker",
        email=f"betabroker_{uuid.uuid4().hex[:8]}@brokerage.ca",
        company="Beta Freight",
        origin_zip="M5V 2T6",
        password="StrongPassword2026!",
    )
    client = TestClient(app, cookies={"quotelytics_session": token})

    chk = client.post("/api/billing/checkout", json={"plan": "PRO", "interval": "month"})
    assert chk.status_code == 403
    assert "Private Beta" in chk.json()["detail"]

    portal = client.post("/api/billing/portal", json={})
    assert portal.status_code == 403
    assert "Private Beta" in portal.json()["detail"]


def test_03_request_beta_access_and_admin_only_provisioning(monkeypatch):
    monkeypatch.delenv("QUOTELYTICS_BETA_INVITE_ONLY", raising=False)
    init_db()
    anon = TestClient(app)
    prospect_email = f"prospect_{uuid.uuid4().hex[:8]}@canadianltl.ca"

    # 1. Public visitor submits Request Beta Access
    req_res = anon.post(
        "/api/beta/request-access",
        json={
            "name": "Sarah Dispatch",
            "email": prospect_email,
            "company": "NorthStar Logistics Ltd.",
            "origin_zip": "L5T 1A1",
            "requested_tier": "TEAM",
            "notes": "Manitoulin + Day & Ross sheets",
            "terms_accepted": True,
        },
    )
    assert req_res.status_code == 200, req_res.text
    beta_req = req_res.json()["request"]
    assert beta_req["status"] == "PENDING"
    assert beta_req["requested_tier"] == "TEAM"

    # 2. Logged-out & regular USER cannot call admin provision or beta-requests list
    assert anon.get("/api/admin/beta-requests").status_code == 401
    assert anon.post("/api/admin/users/provision", json={
        "name": "Hack", "email": "hack@x.ca", "company": "Hack", "tier": "PRO"
    }).status_code == 401

    _, user_tok = register_and_create_session(
        name="Regular User",
        email=f"reg_{uuid.uuid4().hex[:8]}@brokerage.ca",
        company="Reg Co",
        origin_zip="M5V 2T6",
        password="StrongPassword2026!",
    )
    reg_client = TestClient(app, cookies={"quotelytics_session": user_tok})
    assert reg_client.get("/api/admin/beta-requests").status_code == 403
    assert reg_client.post("/api/admin/users/provision", json={
        "name": "Hack", "email": "hack@x.ca", "company": "Hack", "tier": "PRO"
    }).status_code == 403

    # 3. Admin lists pending requests and provisions the prospect on TEAM tier
    admin_u, admin_tok = register_and_create_session(
        name="Dylan Admin",
        email=f"admin_{uuid.uuid4().hex[:8]}@quotelytics.ca",
        company="Quotelytics Inc.",
        origin_zip="M5V 2T6",
        password="AdminStrongPassword2026!",
    )
    conn = get_connection()
    conn.execute("UPDATE users SET role = 'ADMIN', tier = 'BUSINESS' WHERE id = ?", (admin_u["id"],))
    conn.commit()
    conn.close()

    admin_client = TestClient(app, cookies={"quotelytics_session": admin_tok})
    list_res = admin_client.get("/api/admin/beta-requests")
    assert list_res.status_code == 200
    assert any(r["id"] == beta_req["id"] for r in list_res.json()["requests"])

    prov_res = admin_client.post(
        "/api/admin/users/provision",
        json={
            "request_id": beta_req["id"],
            "name": "Sarah Dispatch",
            "email": prospect_email,
            "company": "NorthStar Logistics Ltd.",
            "origin_zip": "L5T 1A1",
            "tier": "TEAM",
        },
    )
    assert prov_res.status_code == 200, prov_res.text
    pdata = prov_res.json()
    assert pdata["tier"] == "TEAM"
    assert len(pdata["temporary_password"]) >= 10

    # Verify the provisioned beta user can log in immediately
    login_res = anon.post(
        "/api/auth/login",
        data={"email": prospect_email, "password": pdata["temporary_password"]},
    )
    assert login_res.status_code == 200

    # Verify beta request is now marked PROVISIONED
    after_list = admin_client.get("/api/admin/beta-requests?status=PROVISIONED").json()["requests"]
    assert any(r["id"] == beta_req["id"] for r in after_list)


def test_04_public_pages_display_request_beta_access():
    client = TestClient(app)
    for path in ("/", "/pricing", "/get-started", "/demo", "/login"):
        res = client.get(path)
        assert res.status_code == 200, f"{path} failed"
        assert "Request Beta Access" in res.text, f"{path} missing 'Request Beta Access'"

    pricing_html = client.get("/pricing").text
    assert "Start 14-Day Free Trial" not in pricing_html
    assert "Start Free Team Trial" not in pricing_html
    assert "Start Free (No Card)" not in pricing_html


def test_05_admin_provisioned_otp_forces_password_change_on_first_login(monkeypatch):
    monkeypatch.delenv("QUOTELYTICS_BETA_INVITE_ONLY", raising=False)
    init_db()
    anon = TestClient(app)

    admin_u, admin_tok = register_and_create_session(
        name="OTP Admin",
        email=f"otp_admin_{uuid.uuid4().hex[:8]}@quotelytics.ca",
        company="Quotelytics Inc.",
        origin_zip="M5V 2T6",
        password="AdminStrongPassword2026!",
    )
    conn = get_connection()
    conn.execute("UPDATE users SET role = 'ADMIN', tier = 'BUSINESS' WHERE id = ?", (admin_u["id"],))
    conn.commit()
    conn.close()

    admin_client = TestClient(app, cookies={"quotelytics_session": admin_tok})
    user_email = f"otp_user_{uuid.uuid4().hex[:8]}@canadianltl.ca"

    # 1. Admin provisions user -> generates OTP & sets must_change_password = True
    prov = admin_client.post(
        "/api/admin/users/provision",
        json={
            "name": "First Login Broker",
            "email": user_email,
            "company": "OTP Freight Inc.",
            "origin_zip": "M5V 2T6",
            "tier": "PRO",
        },
    )
    assert prov.status_code == 200, prov.text
    pdata = prov.json()
    otp = pdata["one_time_password"]
    assert pdata["must_change_password"] is True
    assert otp.startswith("OTP-")

    # 2. First login with OTP returns redirect -> /console/change-password
    login_res = anon.post("/api/auth/login", data={"email": user_email, "password": otp})
    assert login_res.status_code == 200
    ldata = login_res.json()
    assert ldata["must_change_password"] is True
    assert ldata["redirect"] == "/console/change-password"

    user_client = TestClient(app, cookies={"quotelytics_session": ldata["token"]})

    # 3. Visiting /console/new-quote redirects to /console/change-password, and workspace APIs return 403
    console_res = user_client.get("/console/new-quote", follow_redirects=False)
    assert console_res.status_code in (302, 303, 307)
    assert console_res.headers["location"] == "/console/change-password"

    chg_page = user_client.get("/console/change-password")
    assert chg_page.status_code == 200
    assert "Set Your Permanent Password" in chg_page.text

    sheets_blocked = user_client.get("/api/quotelytics/sheets")
    assert sheets_blocked.status_code == 403

    # 4. Cannot reuse the OTP as the new password
    reuse_res = user_client.post(
        "/api/user/password",
        json={"current_password": otp, "new_password": otp},
    )
    assert reuse_res.status_code == 400

    # 5. Setting a new permanent password clears must_change_password and unlocks console + normal login
    perm_pwd = "MyPermanentBrokerPass2026!"
    ok_res = user_client.post(
        "/api/user/password",
        json={"current_password": otp, "new_password": perm_pwd},
    )
    assert ok_res.status_code == 200, ok_res.text

    unlocked_console = user_client.get("/console/new-quote", follow_redirects=False)
    assert unlocked_console.status_code == 200

    unlocked_sheets = user_client.get("/api/quotelytics/sheets")
    assert unlocked_sheets.status_code == 200

    login2 = anon.post("/api/auth/login", data={"email": user_email, "password": perm_pwd}).json()
    assert login2["must_change_password"] is False
    assert login2["redirect"] == "/console/new-quote"

