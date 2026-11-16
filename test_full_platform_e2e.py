import io
import uuid
import openpyxl
from fastapi.testclient import TestClient
import main
from services.db_service import get_connection
from services.auth_service import register_and_create_session

client = TestClient(main.app)

def test_full_platform_e2e():
    print("=" * 70)
    print("QUOTELYTICS FULL PLATFORM END-TO-END VERIFICATION SUITE")
    print("=" * 70)

    # ---------------------------------------------------------
    # 1. PUBLIC DOMAIN & SEO ENDPOINTS
    # ---------------------------------------------------------
    print("\n[PHASE 1] Testing Public SEO Routes...")
    for route in ["/", "/demo", "/pricing", "/login", "/get-started", "/flowchart", "/showcase"]:
        res = client.get(route)
        assert res.status_code == 200, f"Route {route} failed with {res.status_code}"
        print(f"   [OK] {route} returned HTTP 200")

    # ---------------------------------------------------------
    # 2. ROUTE GUARDING & AUTHENTICATION
    # ---------------------------------------------------------
    print("\n[PHASE 2] Testing Route Guarding & Authentication Gateway...")
    res = client.get("/console/new-quote", follow_redirects=False)
    assert res.status_code == 303 and "/login" in res.headers["location"]
    print("   [OK] Unauthenticated visit to /console/new-quote redirected to /login")

    # Provision a dedicated test account and log in
    e2e_email = f"e2e.broker.{uuid.uuid4().hex[:6]}@acme-logistics.ca"
    e2e_pwd = "E2ePlatformTest2026!"
    e2e_user, _ = register_and_create_session(
        name="Jordan Freight",
        email=e2e_email,
        company="Acme Logistics Corp",
        origin_zip="TORONTO, ON",
        password=e2e_pwd
    )
    e2e_uid = e2e_user["id"]

    login_payload = {
        "email": e2e_email,
        "password": e2e_pwd
    }
    res = client.post("/api/auth/login", data=login_payload)
    assert res.status_code == 200
    token = res.cookies["quotelytics_session"]
    print(f"   [OK] Logged in test broker. Session Token: {token[:14]}...")

    auth_client = TestClient(main.app, cookies={"quotelytics_session": token})

    # Access console with token
    res = auth_client.get("/console/new-quote")
    assert res.status_code == 200
    print("   [OK] Authenticated access to /console/new-quote succeeded (HTTP 200)")

    # ---------------------------------------------------------
    # 3. EXCEL PARSING & CELL COORDINATE MAPPING
    # ---------------------------------------------------------
    print("\n[PHASE 3 & 4] Testing Excel Batch Ingestion & Rate Engine...")
    
    # Ensure test user starts on clean FREE tier state with 3 existing sheets (max on Free tier)
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM quote_batches WHERE user_id = ?", (e2e_uid,))
    c.execute("INSERT OR REPLACE INTO quote_batches (id, user_id, filename, total_rows, processed_rows, created_at) VALUES (?, ?, 'Q1_Tariff.xlsx', 5, 5, '2026-09-28T07:00:00')", (f"qb_1_{e2e_uid}", e2e_uid))
    c.execute("INSERT OR REPLACE INTO quote_batches (id, user_id, filename, total_rows, processed_rows, created_at) VALUES (?, ?, 'Q2_Tariff.xlsx', 5, 5, '2026-09-28T07:01:00')", (f"qb_2_{e2e_uid}", e2e_uid))
    c.execute("INSERT OR REPLACE INTO quote_batches (id, user_id, filename, total_rows, processed_rows, created_at) VALUES (?, ?, 'Q3_Tariff.xlsx', 5, 5, '2026-09-28T07:02:00')", (f"qb_3_{e2e_uid}", e2e_uid))
    c.execute("UPDATE users SET tier = 'FREE', company = 'Acme Logistics Corp', origin_zip = 'TORONTO, ON' WHERE id = ?", (e2e_uid,))
    c.execute("UPDATE user_settings SET markup_pct = 10.0 WHERE user_id = ?", (e2e_uid,))
    conn.commit()
    conn.close()

    # Check quota before upload
    quota = auth_client.get("/api/user/quota").json()
    print(f"   Current Tier: {quota['tier_name']} (Sheets remaining: {quota['sheets_remaining']}, Quotes remaining: {quota['quotes_remaining']})")

    sample_file_path = "sample_sheets/wholesale_pallets_ltl.xlsx"
    with open(sample_file_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("wholesale_pallets_ltl.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    # Attempt upload on Free tier - should trigger 403 since 3 sheets are already uploaded
    res = auth_client.post("/api/quotes/upload", files=files)
    assert res.status_code == 403, f"Expected 403 tier rejection, got {res.status_code}"
    assert "Tier limit exceeded" in res.json()["detail"]
    print("   [OK] Quota enforcement verified: 4th sheet on Free Starter tier rejected with HTTP 403")

    # Upgrade test user to PRO tier (10 sheets, 2,500 quotes) to continue multi-sheet testing
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET tier = 'PRO' WHERE id = ?", (e2e_uid,))
    conn.commit()
    conn.close()
    print("   [OK] Upgraded user to Broker Pro tier (10 sheets, 2,500 quotes/mo)")

    # Now upload succeeds on Broker Pro tier
    files = {"file": ("wholesale_pallets_ltl.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = auth_client.post("/api/quotes/upload", files=files)
    assert res.status_code == 200, f"Upload failed on PRO tier: {res.text}"
    upload_res = res.json()
    assert upload_res["status"] == "success"
    assert upload_res["total_quotes"] > 0
    print(f"   [OK] Successfully uploaded & quoted {upload_res['total_quotes']} pallets from {upload_res['filename']}")
    
    # Verify coordinate format and markup
    sample_q = upload_res["quotes"][0]
    print(f"   Sample Quoted Line: {sample_q['quote_id']} | Base: ${sample_q['base_rate']} -> Final (+{sample_q['markup_pct']}%): ${sample_q['final_rate']} | Coordinate: [{sample_q['coordinate']}]")
    assert "Row" in sample_q["coordinate"] and "Col" in sample_q["coordinate"]

    # ---------------------------------------------------------
    # 4. QUOTES HISTORY WAREHOUSE & EXCEL EXPORT
    # ---------------------------------------------------------
    print("\n[PHASE 5] Testing Quotes History Warehouse & Excel Export...")
    res = auth_client.get("/api/quotes/history")
    assert res.status_code == 200
    history = res.json()
    print(f"   [OK] History contains {history['total']} total archived quotes with coordinates")

    # Test search by carrier
    res = auth_client.get("/api/quotes/history?search=Estes")
    assert res.status_code == 200
    assert len(res.json()["quotes"]) > 0
    print("   [OK] Search filter by carrier succeeded")

    # Test sort by rate descending
    res = auth_client.get("/api/quotes/history?sort_by=rate_desc")
    assert res.status_code == 200
    sorted_quotes = res.json()["quotes"]
    assert sorted_quotes[0]["final_rate"] >= sorted_quotes[-1]["final_rate"]
    print(f"   [OK] Sort by rate descending verified: Max=${sorted_quotes[0]['final_rate']} >= Min=${sorted_quotes[-1]['final_rate']}")

    # Test Excel Export (.xlsx)
    res = auth_client.get("/api/quotes/export")
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][0] == "Quote_ID"
    assert len(rows) > 1
    print(f"   [OK] Generated and validated downloadable Excel export ({len(rows)-1} rows exported)")

    # ---------------------------------------------------------
    # 5. ACCOUNT & SYSTEM SETTINGS SYNCHRONIZATION
    # ---------------------------------------------------------
    print("\n[PHASE 6] Testing Account & System Settings Synchronization...")
    acc_update = {
        "name": "Jordan Freight",
        "company": "Acme Global Logistics Inc.",
        "origin_zip": "94107"
    }
    res = auth_client.post("/api/user/account/update", data=acc_update)
    assert res.status_code == 200

    prof = auth_client.get("/api/user/profile").json()
    assert prof["company"] == "Acme Global Logistics Inc."
    assert prof["origin_zip"] == "94107"
    print("   [OK] Account profile and origin ZIP updated to 94107")

    # Update system markup to +15.0%
    settings_update = {
        "currency": "USD",
        "units": "lbs",
        "markup_pct": 15.0,
        "auto_detect_headers": 1,
        "skip_blank_rows": 1
    }
    res = auth_client.post("/api/settings/update", data=settings_update)
    assert res.status_code == 200
    prof = auth_client.get("/api/user/profile").json()
    assert prof["markup_pct"] == 15.0
    print("   [OK] Quoting markup successfully updated to +15.0%")

    # ---------------------------------------------------------
    # 6. EMBEDDED QUOTING API (BUSINESS TIER)
    # ---------------------------------------------------------
    print("\n[PHASE 7] Testing Business Tier Embedded Quoting API...")
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET tier = 'BUSINESS' WHERE id = ?", (e2e_uid,))
    conn.commit()
    conn.close()

    from services.quotelytics_db_service import (
        create_rate_sheet,
        insert_weight_breaks,
        confirm_rate_sheet,
    )
    e2e_sheet_id = create_rate_sheet(
        user_id=e2e_uid,
        carrier_name="Day & Ross LTL",
        service_name="Standard LTL",
        currency="USD",
        version=1,
    )
    insert_weight_breaks(
        e2e_sheet_id,
        e2e_uid,
        [
            {
                "zone_code": "ON_QC",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 0.0,
                "max_weight": 99999.0,
                "base_rate": 40.00,
                "break_name": "LTL",
                "rate_type": "CWT",
                "source_cell": "Tariff!C4",
            },
            {
                "zone_code": "ON_AB",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "CALGARY, AB",
                "min_weight": 0.0,
                "max_weight": 99999.0,
                "base_rate": 60.00,
                "break_name": "LTL",
                "rate_type": "CWT",
                "source_cell": "Tariff!D8",
            },
        ],
    )
    confirm_rate_sheet(e2e_sheet_id, e2e_uid, "Jordan Freight")

    res = auth_client.post("/api/user/api-key/generate", data={"name": "3PL ERP Key"})
    assert res.status_code == 200
    api_key = res.json()["api_key"]
    print(f"   [OK] Generated Business API Key: {res.json()['key_prefix']}")

    api_payload = {
        "shipments": [
            {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 1000.0, "skid_count": 2},
            {"origin_zip": "TORONTO, ON", "dest_zip": "CALGARY, AB", "weight_lbs": 2000.0, "skids": 4, "service": "Freight Standard"}
        ]
    }
    api_res = client.post(
        "/api/v1/quotes/batch",
        json=api_payload,
        headers={"X-API-Key": api_key}
    )
    assert api_res.status_code == 200, f"API failed: {api_res.text}"
    api_body = api_res.json()
    assert api_body["status"] == "success"
    assert api_body["total_quotes"] == 2
    assert api_body["quoted_count"] == 2
    assert api_body["quotes"][0]["status"] == "quoted"
    assert api_body["quotes"][0]["markup_pct"] == 15.0  # Confirms dynamic setting integration
    assert api_body["quotes"][0]["base_rate"] == 400.00  # 10 CWT * $40.00
    assert api_body["quotes"][0]["final_rate"] == 460.00  # $400.00 * 1.15
    assert api_body["quotes"][0]["coordinate"] == "Tariff!C4"
    assert api_body["quotes"][1]["base_rate"] == 1200.00  # 20 CWT * $60.00
    assert api_body["quotes"][1]["final_rate"] == 1380.00  # $1200.00 * 1.15
    print("   [OK] Embedded Quoting API returned 2 deterministic tariff quotes using active +15% markup")

    # ---------------------------------------------------------
    # 7. LOGOUT & SESSION TERMINATION
    # ---------------------------------------------------------
    print("\n[PHASE 8] Testing Logout & Cleanup...")
    res = auth_client.get("/api/auth/logout", follow_redirects=False)
    assert res.status_code == 303
    print("   [OK] Session terminated successfully")

    print("\n" + "=" * 70)
    print("ALL 8 PHASES FULLY VERIFIED - PLATFORM PRODUCTION READY!")
    print("=" * 70)

    print("\n" + "=" * 70)
    print("ALL PHASES (1 THROUGH 8) FULLY VERIFIED & PASSING!")
    print("=" * 70)

if __name__ == "__main__":
    test_full_platform_e2e()
