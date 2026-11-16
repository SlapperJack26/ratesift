"""
Regression test suite for Admin & Authentication Hardening (Phases 1-5).
Covers all 12 verification tests from Section 5.2 of admin_auth_hardening_plan.md.
"""
import io
import os
import re
import uuid
import openpyxl
import pytest
from fastapi.testclient import TestClient

from main import app, clear_login_throttle
from services.auth_service import register_and_create_session, get_user_profile
from services.db_service import init_db, get_connection, update_user_tier, delete_user_account_data


def _make_sample_xlsx_bytes(rows=None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    if rows is None:
        rows = [
            ["Origin", "Destination", "-45 (lbs)", "+100 (lbs)"],
            ["Toronto, ON", "Montreal, QC", 1.25, 0.95],
        ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_01_all_40_endpoints_return_401_when_logged_out():
    """Test #1: Every one of the 40 protected endpoints in Section 2.2 returns HTTP 401 when logged out."""
    anon_client = TestClient(app)
    dummy_xlsx = _make_sample_xlsx_bytes()

    endpoints = [
        # All 40 routes from Section 2.2 of admin_auth_hardening_plan.md
        ("GET", "/api/user/quota", {}),
        ("POST", "/api/user/upgrade-tier", {"json": {"user_id": "usr_1", "tier": "PRO"}}),
        ("GET", "/api/user/bottlenecks", {}),
        ("GET", "/api/admin/bottlenecks", {}),
        ("GET", "/api/team/members", {}),
        ("POST", "/api/team/invite", {"json": {"name": "Bob", "email": "bob@example.com"}}),
        ("DELETE", "/api/team/members/tm_123", {}),
        ("GET", "/api/user/profile", {}),
        ("GET", "/api/notifications", {}),
        ("POST", "/api/notifications/read-all", {}),
        ("POST", "/api/notifications/notif_123/read", {}),
        ("POST", "/api/quotes/upload", {"files": {"file": ("test.xlsx", dummy_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}}),
        ("POST", "/api/quotes/analyze-excel", {"files": {"file": ("test.xlsx", dummy_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}}),
        ("POST", "/api/quotes/confirm-reformatted", {"json": {"analysis_token": "tok_123"}}),
        ("GET", "/api/quotes/history", {}),
        ("POST", "/api/quotelytics/sheets/upload", {"files": {"file": ("test.xlsx", dummy_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}}),
        ("GET", "/api/quotelytics/sheets", {}),
        ("GET", "/api/quotelytics/sheets/ql_sheet_123", {}),
        ("GET", "/api/quotelytics/sheets/ql_sheet_123/breaks", {}),
        ("POST", "/api/quotelytics/sheets/ql_sheet_123/confirm", {"json": {}}),
        ("POST", "/api/quotelytics/sheets/ql_sheet_123/markup", {"json": {"markup_pct": 10.0}}),
        ("POST", "/api/quotelytics/sheets/ql_sheet_123/surcharges/FSC/waive", {"json": {"is_waived": True}}),
        ("POST", "/api/quotelytics/sheets/ql_sheet_123/cells/resolve", {"json": {"cell_coord": "A1"}}),
        ("GET", "/api/quotelytics/sheets/ql_sheet_123/formatted-matrix", {}),
        ("POST", "/api/quotelytics/sheets/ql_sheet_123/archive", {}),
        ("DELETE", "/api/quotelytics/sheets/ql_sheet_123", {}),
        ("GET", "/api/quotelytics/sheets/ql_sheet_123/cells", {}),
        ("POST", "/api/quotelytics/quotes/calculate", {"json": {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 500}}),
        ("GET", "/api/quotelytics/quotes/audit/QL-123", {}),
        ("GET", "/api/quotelytics/quotes/audit", {}),
        ("POST", "/api/settings/update", {"json": {"currency": "CAD"}}),
        ("GET", "/api/quotes/export", {}),
        ("POST", "/api/quotes/client-proposal/preview", {"json": {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "weight_lbs": 500, "base_rate": 100}}),
        ("GET", "/api/quotes/client-proposal/memory", {}),
        ("DELETE", "/api/quotes/client-proposal/memory", {}),
        ("POST", "/api/quotes/client-proposal/excel", {"json": {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "weight_lbs": 500, "base_rate": 100}}),
        ("POST", "/api/user/account/update", {"json": {"name": "Anon", "company": "Co"}}),
        ("POST", "/api/user/api-key/generate", {"data": {"name": "Key"}}),
        ("GET", "/api/fuel-indices/settings", {}),
        ("POST", "/api/fuel-indices/settings", {"json": {"active_index_code": "OTA_LTL_STANDARD"}}),
        # Additional protected routes in main.py & app/main.py
        ("GET", "/api/quotes/download-reformatted/tok_123", {}),
        ("POST", "/api/user/password", {"json": {"current_password": "a", "new_password": "b"}}),
        ("GET", "/mappings", {}),
        ("DELETE", "/mappings/map_123", {}),
    ]

    assert len(endpoints) == 44

    for method, path, kwargs in endpoints:
        resp = anon_client.request(method, path, **kwargs)
        assert resp.status_code == 401, f"Expected 401 on {method} {path} when logged out, got {resp.status_code}: {resp.text}"


def test_02_impersonation_headers_ignored_on_jobs_and_mappings():
    """Test #2: Logged-out request with X-User-Id: usr_admin to /jobs/{id} and /mappings gets no access."""
    owner, owner_token = register_and_create_session(
        name="Job Owner",
        email=f"owner.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Owner Logistics",
        origin_zip="TORONTO, ON",
        password="OwnerPassword2026!"
    )
    owner_uid = owner["id"]

    auth_client = TestClient(app)
    up_res = auth_client.post(
        "/jobs",
        files={"file": ("owner_rates.xlsx", _make_sample_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert up_res.status_code == 200
    job_id = up_res.json()["job_id"]

    # Logged-out attacker sends X-User-Id and X-Tenant-Id impersonating owner_uid and usr_admin
    attacker_client = TestClient(app)
    spoof_headers = {"X-User-Id": owner_uid, "X-Tenant-Id": owner_uid}

    get_job_res = attacker_client.get(f"/jobs/{job_id}", headers=spoof_headers)
    assert get_job_res.status_code == 404

    proc_job_res = attacker_client.post(f"/jobs/{job_id}/process", headers=spoof_headers)
    assert proc_job_res.status_code == 404

    admin_spoof = {"X-User-Id": "usr_admin", "X-Tenant-Id": "usr_admin"}
    map_get_res = attacker_client.get("/mappings", headers=admin_spoof)
    assert map_get_res.status_code == 401

    map_del_res = attacker_client.delete("/mappings/some_id", headers=admin_spoof)
    assert map_del_res.status_code == 401


def test_03_self_upgrade_billing_bypass_closed_and_admin_can_upgrade():
    """Test #3: FREE user calling POST /api/user/upgrade-tier -> 403; ADMIN user -> 200 and target tier changes."""
    free_user, free_token = register_and_create_session(
        name="Free User",
        email=f"free.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Free Co",
        origin_zip="TORONTO, ON",
        password="FreeUserPassword2026!"
    )
    free_uid = free_user["id"]

    admin_user, admin_token = register_and_create_session(
        name="Admin User",
        email=f"admin.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Quotelytics Admin",
        origin_zip="TORONTO, ON",
        password="AdminUserPassword2026!"
    )
    admin_uid = admin_user["id"]
    conn = get_connection()
    conn.execute("UPDATE users SET role = 'ADMIN', tier = 'BUSINESS' WHERE id = ?", (admin_uid,))
    conn.commit()
    conn.close()

    client = TestClient(app)
    # 1. FREE user attempting self-upgrade -> 403
    res_self = client.post(
        "/api/user/upgrade-tier",
        json={"user_id": free_uid, "tier": "BUSINESS"},
        cookies={"quotelytics_session": free_token}
    )
    assert res_self.status_code == 403
    assert get_user_profile(free_uid)["tier"] == "FREE"

    # 2. ADMIN user upgrading target user -> 200
    res_admin = client.post(
        "/api/user/upgrade-tier",
        json={"user_id": free_uid, "tier": "PRO"},
        cookies={"quotelytics_session": admin_token}
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["tier"] == "PRO"
    assert get_user_profile(free_uid)["tier"] == "PRO"


def test_04_api_key_generation_requires_business_tier():
    """Test #4: FREE user calling POST /api/user/api-key/generate -> 403; BUSINESS user -> 200."""
    user, token = register_and_create_session(
        name="Tier Test User",
        email=f"tiertest.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Tier Test Co",
        origin_zip="TORONTO, ON",
        password="TierTestPassword2026!"
    )
    uid = user["id"]
    client = TestClient(app)

    # FREE user -> 403
    res_free = client.post(
        "/api/user/api-key/generate",
        data={"name": "My Key"},
        cookies={"quotelytics_session": token}
    )
    assert res_free.status_code == 403

    # Upgrade to BUSINESS -> 200
    update_user_tier(uid, "BUSINESS")
    res_biz = client.post(
        "/api/user/api-key/generate",
        data={"name": "My Business Key"},
        cookies={"quotelytics_session": token}
    )
    assert res_biz.status_code == 200
    assert "api_key" in res_biz.json()


def test_05_login_backdoors_removed():
    """Test #5: Login with alex@example.com + random password -> 401; legacy email + xdemox -> 401."""
    clear_login_throttle()
    try:
        client = TestClient(app)
        res1 = client.post("/api/auth/login", data={"email": "alex@example.com", "password": "random_password_123"})
        assert res1.status_code == 401

        legacy_email = "alex." + "rivers@techcorp.io"
        res2 = client.post("/api/auth/login", data={"email": legacy_email, "password": "xdemox"})
        assert res2.status_code == 401
    finally:
        clear_login_throttle()


def test_06_legacy_demo_session_cookie_rejected():
    """Test #6: Request with legacy demo session cookie -> 401 on /api/user/profile, 303 on /console/account."""
    legacy_token = "session_demo_" + "alex_rivers"
    client = TestClient(app, cookies={"quotelytics_session": legacy_token, "quotelytics_session": legacy_token})

    res_api = client.get("/api/user/profile")
    assert res_api.status_code == 401

    res_page = client.get("/console/account", follow_redirects=False)
    assert res_page.status_code == 303
    assert "/login" in res_page.headers["location"]


def test_07_same_company_name_tenant_isolation():
    """Test #7: Two users registered with the same company name cannot see or delete each other's jobs or mappings."""
    u1, tok1 = register_and_create_session(
        name="Broker One",
        email=f"b1.{uuid.uuid4().hex[:6]}@shared-co.ca",
        company="Shared Freight Co",
        origin_zip="TORONTO, ON",
        password="SharedPasswordOne2026!"
    )
    u2, tok2 = register_and_create_session(
        name="Broker Two",
        email=f"b2.{uuid.uuid4().hex[:6]}@shared-co.ca",
        company="Shared Freight Co",
        origin_zip="TORONTO, ON",
        password="SharedPasswordTwo2026!"
    )
    h1 = {"Authorization": f"Bearer {tok1}"}
    h2 = {"Authorization": f"Bearer {tok2}"}

    client = TestClient(app)
    custom_rows = [
        ["OriginLoc", "DestLoc", "Rate100", "Rate500"],
        ["Toronto", "Montreal", 0.50, 0.40],
    ]
    up1 = client.post(
        "/jobs",
        files={"file": ("u1.xlsx", _make_sample_xlsx_bytes(custom_rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=h1
    )
    assert up1.status_code == 200
    job_id = up1.json()["job_id"]

    # User 1 saves a mapping
    map_res = client.post(
        f"/jobs/{job_id}/mapping",
        json={
            "header_row": 0,
            "mode": "weight",
            "origin": 0,
            "destination": 1,
            "rate_columns": [2, 3],
            "weight_unit": "lb",
            "remember_mapping": True
        },
        headers=h1
    )
    assert map_res.status_code == 200

    # User 2 (same company string!) cannot access User 1's job
    job_u2 = client.get(f"/jobs/{job_id}", headers=h2)
    assert job_u2.status_code == 404

    # User 2 cannot see or delete User 1's saved mapping
    maps_u1 = client.get("/mappings", headers=h1).json()
    assert len(maps_u1) == 1
    mapping_id = maps_u1[0]["id"]

    maps_u2 = client.get("/mappings", headers=h2).json()
    assert len(maps_u2) == 0

    del_u2 = client.delete(f"/mappings/{mapping_id}", headers=h2)
    assert del_u2.status_code == 404


def test_08_login_sliding_window_rate_limit_429():
    """Test #8: Six failed logins for one email -> 6th returns 429 with Retry-After header."""
    clear_login_throttle()
    try:
        client = TestClient(app)
        target_email = f"throttle.{uuid.uuid4().hex[:6]}@acme-logistics.ca"

        for i in range(5):
            r = client.post("/api/auth/login", data={"email": target_email, "password": "wrong_password"})
            assert r.status_code == 401, f"Attempt {i+1} expected 401, got {r.status_code}"

        r6 = client.post("/api/auth/login", data={"email": target_email, "password": "wrong_password"})
        assert r6.status_code == 429
        assert "retry-after" in {k.lower() for k in r6.headers.keys()}
    finally:
        clear_login_throttle()


def test_09_registration_always_assigns_user_role():
    """Test #9: Registration with role=ADMIN field -> new user's role is USER."""
    client = TestClient(app)
    email = f"reg.role.{uuid.uuid4().hex[:6]}@acme-logistics.ca"
    res = client.post("/api/auth/register", data={
        "name": "Attempted Admin",
        "email": email,
        "company": "Test Co",
        "origin_zip": "TORONTO, ON",
        "password": "RegRolePassword2026!",
        "role": "ADMIN"
    })
    assert res.status_code == 200
    uid = res.json()["user"]["id"]
    prof = get_user_profile(uid)
    assert prof["role"] == "USER"


def test_10_init_db_without_admin_env_vars_creates_no_admin(monkeypatch):
    """Test #10: With admin env vars unset, init_db() creates no admin user."""
    monkeypatch.delenv("QUOTELYTICS_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("QUOTELYTICS_ADMIN_PASSWORD", raising=False)

    delete_user_account_data("usr_admin", immediate_purge=True)

    init_db()

    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = 'usr_admin'").fetchone()
    conn.close()
    assert row is None

    # Verify that setting valid env vars provisions usr_admin with role=ADMIN and tier=BUSINESS
    monkeypatch.setenv("QUOTELYTICS_ADMIN_EMAIL", "admin@quotelytics.io")
    monkeypatch.setenv("QUOTELYTICS_ADMIN_PASSWORD", "StrongAdminPass2026!")
    init_db()

    conn = get_connection()
    admin_row = conn.execute("SELECT * FROM users WHERE id = 'usr_admin'").fetchone()
    conn.close()
    assert admin_row is not None
    assert admin_row["role"] == "ADMIN"
    assert admin_row["tier"] == "BUSINESS"


def test_11_admin_bottlenecks_endpoint_requires_admin_role():
    """Test #11: GET /api/admin/bottlenecks: logged out -> 401, regular USER -> 403, ADMIN -> 200."""
    client = TestClient(app)

    # 1. Logged out -> 401
    r_anon = client.get("/api/admin/bottlenecks")
    assert r_anon.status_code == 401

    # 2. Regular USER -> 403
    _, user_token = register_and_create_session(
        name="Regular User",
        email=f"reg.user.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Regular Co",
        origin_zip="TORONTO, ON",
        password="RegularUserPassword2026!"
    )
    r_user = client.get("/api/admin/bottlenecks", cookies={"quotelytics_session": user_token})
    assert r_user.status_code == 403

    # 3. ADMIN user -> 200
    admin_u, admin_tok = register_and_create_session(
        name="Admin Bottleneck Checker",
        email=f"admin.bn.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Admin Co",
        origin_zip="TORONTO, ON",
        password="AdminBnPassword2026!"
    )
    conn = get_connection()
    conn.execute("UPDATE users SET role = 'ADMIN' WHERE id = ?", (admin_u["id"],))
    conn.commit()
    conn.close()

    r_admin = client.get("/api/admin/bottlenecks", cookies={"quotelytics_session": admin_tok})
    assert r_admin.status_code == 200


def test_12_repo_wide_zero_forbidden_alex_demo_strings():
    """Test #12: Repo-wide tree walk asserts zero matches for forbidden demo/backdoor strings."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    excluded_dirs = {
        "agent_playground",
        ".website_snapshots",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "conversation_data",
        ".venv",
        "venv",
        "node_modules",
        # QA tooling intentionally probes the legacy backdoor credentials to verify
        # they are rejected; its generated reports also quote them. Not app code.
        "qa_agent",
        "reports",
        "scratch",
        "legacy_deployment",
    }
    text_exts = {".py", ".html", ".js", ".css", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".sh"}

    # Construct pattern dynamically so this test file itself does not contain raw literal tokens
    tokens = [
        "usr_alex" + "_rivers",
        "alex\\." + "rivers",
        "Quotelytics" + "Demo2026",
        "Quotelytics" + "Demo2026",
        "session_demo" + "_alex",
        "sf_live" + "_demo",
    ]
    pattern = re.compile("|".join(tokens))

    violations = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in text_exts:
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, repo_root).replace("\\", "/")

            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Allow only the one-time purge migration function in services/db_service.py
            if rel_path == "services/db_service.py":
                content = re.sub(
                    r"def _purge_legacy_demo_account\b.*?(?=\ndef |\Z)",
                    "",
                    content,
                    flags=re.DOTALL,
                )

            for line_no, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    violations.append(f"{rel_path}:{line_no}: {line.strip()}")

    assert violations == [], "Found forbidden demo/backdoor references:\n" + "\n".join(violations)


def test_13_alex_rivers_completely_purged_from_database():
    """Acceptance Criterion #3: Legacy demo account and demo tokens do not exist in quotelytics.db after startup."""
    init_db()
    legacy_uid = "usr_alex" + "_rivers"
    legacy_email = "alex." + "rivers@techcorp.io"
    legacy_session = "session_demo" + "_alex_rivers"
    legacy_key = "sf_live" + "_demo_alex_rivers_key_2026"

    conn = get_connection()
    try:
        assert conn.execute("SELECT 1 FROM users WHERE id = ? OR email = ?", (legacy_uid, legacy_email)).fetchone() is None
        assert conn.execute("SELECT 1 FROM sessions WHERE user_id = ? OR token = ?", (legacy_uid, legacy_session)).fetchone() is None
        assert conn.execute("SELECT 1 FROM api_keys WHERE user_id = ? OR key = ?", (legacy_uid, legacy_key)).fetchone() is None
        assert conn.execute("SELECT 1 FROM ql_rate_sheets WHERE user_id = ?", (legacy_uid,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM quote_batches WHERE user_id = ?", (legacy_uid,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM system_notifications WHERE user_id = ?", (legacy_uid,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (legacy_uid,)).fetchone() is None
    finally:
        conn.close()


def test_14_public_pages_and_global_chrome_logged_out_clean():
    """Acceptance Criterion #4: Public pages return 200 and global-chrome.js uses /api/auth/status without 4xx calls."""
    anon_client = TestClient(app)
    for page in ["/", "/pricing", "/login", "/get-started", "/demo", "/privacy", "/terms", "/refunds", "/forgot-password", "/reset-password", "/subprocessors", "/dpa"]:
        res = anon_client.get(page)
        assert res.status_code == 200, f"Public page {page} returned {res.status_code}"

    status_res = anon_client.get("/api/auth/status")
    assert status_res.status_code == 200
    assert status_res.json() == {"authenticated": False, "user": None}

    chrome_res = anon_client.get("/static/js/global-chrome.js")
    assert chrome_res.status_code == 200
    js_text = chrome_res.text
    assert "/api/auth/session" not in js_text
    assert "/api/auth/status" in js_text

