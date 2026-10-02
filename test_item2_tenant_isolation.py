"""
Test Suite for Item 2:
- Zero-Sample Access & Strict Tenant Isolation (Rule 28)
- No auto-seeding of benchmark or sample sheets
- Complete cross-tenant quarantine: Accounts only see sheets they upload
- Verification of empty-state response when zero sheets exist
"""
import uuid
import json
from fastapi.testclient import TestClient
from main import app
from services.db_service import get_connection, init_db

def test_item2_tenant_isolation():
    client = TestClient(app)
    init_db()

    # 1. Register User A
    user_a_email = f"broker_a_{uuid.uuid4().hex[:6]}@atlanticlogistics.ca"
    reg_a = client.post("/api/auth/register", data={
        "name": "Alice Broker",
        "email": user_a_email,
        "company": "Atlantic Logistics",
        "origin_zip": "B3H 1A1",
        "password": "Password123!"
    })
    assert reg_a.status_code == 200, reg_a.text
    session_a = reg_a.cookies.get("shipflow_session")
    client_a = TestClient(app, cookies={"shipflow_session": session_a})

    print("\n--- 1. Testing Zero-Sample Seed on Fresh Registration ---")
    res_a_sheets = client_a.get("/api/ratesift/sheets")
    assert res_a_sheets.status_code == 200
    sheets_a = res_a_sheets.json()["sheets"]
    assert len(sheets_a) == 0, f"Expected 0 sheets for fresh user, found {len(sheets_a)}"
    print(f"   [OK] Fresh User A has exactly {len(sheets_a)} rate sheets. No sample/benchmark tariffs seeded!")

    # Check quota for User A
    quota_a = client_a.get("/api/user/quota").json()
    assert quota_a["sheets_uploaded"] == 0
    assert quota_a["can_upload_sheet"] is True
    print("   [OK] Quota shows 0 sheets uploaded.")

    # 2. Register User B
    user_b_email = f"broker_b_{uuid.uuid4().hex[:6]}@pacificfreight.ca"
    reg_b = client.post("/api/auth/register", data={
        "name": "Bob Dispatcher",
        "email": user_b_email,
        "company": "Pacific Freight Hub",
        "origin_zip": "V6B 2W2",
        "password": "Password123!"
    })
    assert reg_b.status_code == 200
    session_b = reg_b.cookies.get("shipflow_session")
    client_b = TestClient(app, cookies={"shipflow_session": session_b})

    res_b_sheets = client_b.get("/api/ratesift/sheets")
    assert len(res_b_sheets.json()["sheets"]) == 0
    print("   [OK] Fresh User B has exactly 0 rate sheets.")

    print("\n--- 2. Testing Tenant Upload Isolation ---")
    # User A uploads a custom rate sheet
    user_a_id = reg_a.json()["user"]["id"]
    sheet_a_id = f"rs_custom_{uuid.uuid4().hex[:8]}"
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO rs_rate_sheets (
        id, user_id, carrier_name, service_name, tariff_ref,
        source_filename, storage_region, created_at, confirmation_status, is_benchmark
    ) VALUES (?, ?, 'Private Carrier X', 'Dedicated LTL', 'PRIV-2026', 'private_contract.xlsx', 'CA_CENTRAL_WHC', '2026-10-02', 'CONFIRMED', 0)
    """, (sheet_a_id, user_a_id))
    
    # Insert zone and break for User A
    c.execute("""
    INSERT INTO rs_carrier_zones (id, sheet_id, user_id, origin_spec, dest_spec, zone_code, transit_days)
    VALUES (?, ?, ?, 'B3H', 'M5V', 'ZONE-1', 2)
    """, (f"zn_{uuid.uuid4().hex[:6]}", sheet_a_id, user_a_id))

    c.execute("""
    INSERT INTO rs_weight_breaks (id, sheet_id, user_id, zone_code, min_weight, max_weight, break_name, base_rate, rate_type)
    VALUES (?, ?, ?, 'ZONE-1', 0.0, 5000.0, '500', 15.50, 'CWT')
    """, (f"wb_{uuid.uuid4().hex[:6]}", sheet_a_id, user_a_id))
    conn.commit()
    conn.close()

    # User A sees 1 sheet
    sheets_a = client_a.get("/api/ratesift/sheets").json()["sheets"]
    assert len(sheets_a) == 1
    assert sheets_a[0]["id"] == sheet_a_id
    assert sheets_a[0]["carrier_name"] == "Private Carrier X"
    print("   [OK] User A sees their uploaded private rate sheet.")

    # User B MUST see 0 sheets!
    sheets_b = client_b.get("/api/ratesift/sheets").json()["sheets"]
    assert len(sheets_b) == 0, f"Cross-tenant leak! User B saw {len(sheets_b)} sheets."
    print("   [OK] User B sees 0 sheets (Strict Tenant Isolation verified).")

    # User B attempts to access User A's sheet details directly
    res_b_direct = client_b.get(f"/api/ratesift/sheets/{sheet_a_id}")
    assert res_b_direct.status_code == 404, f"Expected 404 for cross-tenant sheet inspection, got {res_b_direct.status_code}"
    print("   [OK] User B direct access to User A's sheet blocked with HTTP 404.")

    print("\n--- 3. Testing Quoting Engine Isolation & Empty Message ---")
    # User B calculates quote with 0 uploaded sheets
    res_quote_b = client_b.post("/api/ratesift/quotes/calculate", json={
        "origin": "B3H 1A1",
        "destination": "M5V 2T6",
        "actual_weight": 500.0
    })
    assert res_quote_b.status_code == 200
    quote_data_b = res_quote_b.json()
    assert quote_data_b["total_options"] == 0
    assert len(quote_data_b["quotes"]) == 0
    assert "No rate sheets uploaded yet" in quote_data_b["message"]
    print(f"   [OK] User B received 0 quotes with clear message: '{quote_data_b['message']}'")

    # User A calculates quote against their own sheet
    res_quote_a = client_a.post("/api/ratesift/quotes/calculate", json={
        "origin": "B3H 1A1",
        "destination": "M5V 2T6",
        "actual_weight": 500.0
    })
    assert res_quote_a.status_code == 200
    quote_data_a = res_quote_a.json()
    assert quote_data_a["total_options"] == 1
    assert quote_data_a["quotes"][0]["carrier_name"] == "Private Carrier X"
    print(f"   [OK] User A successfully quoted Private Carrier X: ${quote_data_a['quotes'][0]['final_total']}")

    # 4. Clean up test users
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id IN (?, ?)", (user_a_id, reg_b.json()["user"]["id"]))
    c.execute("DELETE FROM sessions WHERE user_id IN (?, ?)", (user_a_id, reg_b.json()["user"]["id"]))
    c.execute("DELETE FROM rs_rate_sheets WHERE id = ?", (sheet_a_id,))
    c.execute("DELETE FROM rs_carrier_zones WHERE sheet_id = ?", (sheet_a_id,))
    c.execute("DELETE FROM rs_weight_breaks WHERE sheet_id = ?", (sheet_a_id,))
    conn.commit()
    conn.close()

    print("\n======================================================================")
    print("ALL ITEM 2 ZERO-SAMPLE & TENANT ISOLATION TESTS PASSED SUCCESSFULLY!")
    print("======================================================================\n")

if __name__ == "__main__":
    test_item2_tenant_isolation()
