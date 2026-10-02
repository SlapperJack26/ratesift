"""
Test Suite for Item 3:
- Subscription tier limits (Free, Pro, Team, Business)
- Sheet counters & hard blocks
- Quote counters & hard blocks
- Number of seats & hard blocks
- Bottleneck tracking & telemetry
"""
import uuid
import json
from fastapi.testclient import TestClient
from main import app
from services.db_service import (
    get_connection,
    init_db,
    get_user_quota_info,
    log_bottleneck_event,
    list_bottleneck_events,
    update_user_tier
)

def test_item3_subscription_blocks():
    client = TestClient(app)
    init_db()

    # 1. Setup isolated test user on FREE tier
    test_user_id = f"usr_test_{uuid.uuid4().hex[:8]}"
    test_email = f"test_{uuid.uuid4().hex[:6]}@brokerage.ca"
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO users (id, name, email, password_hash, company, origin_zip, tier, created_at)
    VALUES (?, 'Test Broker', ?, 'dummy_hash', 'Test 3PL Inc', 'M5V 2T6', 'FREE', '2026-10-01T00:00:00')
    """, (test_user_id, test_email))
    
    token = f"s_test_{uuid.uuid4().hex[:8]}"
    c.execute("""
    INSERT INTO sessions (token, user_id, expires_at, created_at)
    VALUES (?, ?, '2026-11-01T00:00:00', '2026-10-01T00:00:00')
    """, (token, test_user_id))
    conn.commit()
    conn.close()

    auth_client = TestClient(app, cookies={"shipflow_session": token})

    print("\n--- 1. Testing Quota Profile & Counters ---")
    res = auth_client.get("/api/user/quota")
    assert res.status_code == 200, res.text
    quota = res.json()
    assert quota["tier"] == "FREE"
    assert quota["max_sheets"] == 3
    assert quota["max_quotes_per_month"] == 50
    assert quota["max_seats"] == 1
    assert quota["active_seats"] == 1
    assert quota["seats_remaining"] == 0
    assert quota["can_upload_sheet"] is True
    assert quota["can_quote"] is True
    assert quota["can_invite_seat"] is False
    print("   [OK] Free Starter limits verified: 3 Sheets, 50 Quotes, 1 Seat.")

    print("\n--- 2. Testing Seat Limit Enforcement & Bottleneck Logging ---")
    # Attempt to invite a second seat on Free Starter tier (max 1 seat)
    res = auth_client.post("/api/team/invite", json={"email": "dispatcher2@brokerage.ca", "role": "DISPATCHER"})
    assert res.status_code == 403, f"Expected 403 seat limit block, got {res.status_code}"
    err = res.json()
    assert "detail" in err
    print(f"   [OK] Seat invitation blocked: {err['detail']}")

    # Verify bottleneck was logged
    res = auth_client.get("/api/user/bottlenecks")
    assert res.status_code == 200
    b_data = res.json()
    assert b_data["total"] >= 1
    seat_event = b_data["bottlenecks"][0]
    assert seat_event["bottleneck_type"] == "LIMIT_BLOCKED_SEATS"
    assert seat_event["user_id"] == test_user_id
    print(f"   [OK] Bottleneck recorded in telemetry: {seat_event['bottleneck_type']} on {seat_event['attempted_action']}")

    print("\n--- 3. Testing Tier Upgrade to Broker Team (5 Seats, Unlimited Sheets) ---")
    res = auth_client.post("/api/user/upgrade-tier", json={"tier": "TEAM"})
    assert res.status_code == 200
    upgraded_quota = res.json()["quota"]
    assert upgraded_quota["tier"] == "TEAM"
    assert upgraded_quota["max_seats"] == 5
    assert upgraded_quota["active_seats"] == 1
    assert upgraded_quota["seats_remaining"] == 4
    assert upgraded_quota["can_invite_seat"] is True
    assert upgraded_quota["max_sheets"] == -1
    assert upgraded_quota["can_upload_sheet"] is True
    print("   [OK] Upgraded to Broker Team: 5 Seats available, Unlimited sheets.")

    print("\n--- 4. Testing Multi-Seat Invitation on Team Tier ---")
    res = auth_client.post("/api/team/invite", json={"email": "dispatcher2@brokerage.ca", "name": "Sarah Connor", "role": "DISPATCHER"})
    assert res.status_code == 200, res.text
    inv_data = res.json()
    assert inv_data["status"] == "success"
    member_id = inv_data["member"]["id"]
    print("   [OK] Successfully invited Dispatcher Sarah Connor")

    # Check team members list
    res = auth_client.get("/api/team/members")
    assert res.status_code == 200
    team_data = res.json()
    assert team_data["active_seats"] == 2
    assert team_data["seats_remaining"] == 3
    assert len(team_data["members"]) == 1
    print(f"   [OK] Team members query: {team_data['active_seats']}/{team_data['max_seats']} seats occupied.")

    # Revoke seat
    res = auth_client.delete(f"/api/team/members/{member_id}")
    assert res.status_code == 200
    res = auth_client.get("/api/team/members")
    assert res.json()["active_seats"] == 1
    print("   [OK] Successfully revoked team member seat; seat freed.")

    print("\n--- 5. Testing Rate Sheet Hard Block on Quota Exceeded ---")
    # Downgrade back to FREE tier
    auth_client.post("/api/user/upgrade-tier", json={"tier": "FREE"})
    # Seed 3 sheets to fill quota
    conn = get_connection()
    c = conn.cursor()
    for i in range(3):
        c.execute("""
        INSERT INTO rs_rate_sheets (
            id, user_id, carrier_name, service_name, tariff_ref,
            source_filename, storage_region, created_at, confirmation_status, is_benchmark
        ) VALUES (?, ?, 'Carrier Test', 'LTL', 'TAR-1', 'test.xlsx', 'CA_CENTRAL_WHC', '2026-10-01', 'CONFIRMED', 0)
        """, (f"rs_test_{uuid.uuid4().hex[:6]}", test_user_id))
    conn.commit()
    conn.close()

    q_full = auth_client.get("/api/user/quota").json()
    assert q_full["sheets_uploaded"] == 3
    assert q_full["can_upload_sheet"] is False
    print(f"   [OK] Filled 3/3 rate sheets on Free Starter: can_upload_sheet={q_full['can_upload_sheet']}")

    # Attempt to upload 4th sheet
    dummy_xlsx = b"PK\x03\x04" + b"\x00" * 50
    files = {"file": ("excess_tariff.xlsx", dummy_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = auth_client.post("/api/ratesift/sheets/upload", files=files)
    assert res.status_code == 403, f"Expected 403 sheet quota rejection, got {res.status_code}"
    print(f"   [OK] 4th Rate Sheet upload rejected: {res.json()['detail']}")

    # Verify bottleneck event logged
    b_events = auth_client.get("/api/user/bottlenecks").json()["bottlenecks"]
    sheet_btn = [e for e in b_events if e["bottleneck_type"] == "LIMIT_BLOCKED_SHEETS"]
    assert len(sheet_btn) > 0
    print(f"   [OK] Telemetry logged SHEET bottleneck: {sheet_btn[0]['attempted_action']}")

    print("\n--- 6. Testing Monthly Quoting Hard Block ---")
    # Exhaust quotes for test user
    conn = get_connection()
    c = conn.cursor()
    month_now = "2026-10-02T12:00:00"
    for i in range(50):
        c.execute("""
        INSERT INTO rs_quote_audit_logs (
            id, user_id, timestamp, shipment_input_json, sheets_considered_json,
            sheets_excluded_json, calculation_trace_json, final_results_json
        ) VALUES (?, ?, ?, '{}', '[]', '[]', '[]', '[]')
        """, (f"audit_{uuid.uuid4().hex[:8]}", test_user_id, month_now))
    conn.commit()
    conn.close()

    q_quotes_full = auth_client.get("/api/user/quota").json()
    assert q_quotes_full["monthly_quotes_used"] == 50
    assert q_quotes_full["can_quote"] is False
    print(f"   [OK] Exhausted 50/50 quotes for this month: can_quote={q_quotes_full['can_quote']}")

    # Attempt deterministic calculation
    res = auth_client.post("/api/ratesift/quotes/calculate", json={
        "origin": "Toronto, ON",
        "destination": "Montreal, QC",
        "actual_weight": 500.0
    })
    assert res.status_code == 403, f"Expected 403 quote volume rejection, got {res.status_code}"
    print(f"   [OK] Calculation rejected when quote quota full: {res.json()['detail']}")

    # Verify quote bottleneck in telemetry
    b_events = auth_client.get("/api/user/bottlenecks").json()["bottlenecks"]
    quote_btn = [e for e in b_events if e["bottleneck_type"] == "LIMIT_BLOCKED_QUOTES"]
    assert len(quote_btn) > 0
    print(f"   [OK] Telemetry logged QUOTE bottleneck: {quote_btn[0]['attempted_action']}")

    # Admin telemetry check
    res = client.get("/api/admin/bottlenecks")
    assert res.status_code == 200
    assert res.json()["total"] >= 3
    print(f"   [OK] Admin telemetry confirmed {res.json()['total']} system-wide bottlenecks logged.")

    # Cleanup test user data
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id = ?", (test_user_id,))
    c.execute("DELETE FROM sessions WHERE user_id = ?", (test_user_id,))
    c.execute("DELETE FROM organization_members WHERE organization_id = ?", (test_user_id,))
    c.execute("DELETE FROM rs_rate_sheets WHERE user_id = ?", (test_user_id,))
    c.execute("DELETE FROM rs_quote_audit_logs WHERE user_id = ?", (test_user_id,))
    c.execute("DELETE FROM bottleneck_events WHERE user_id = ?", (test_user_id,))
    conn.commit()
    conn.close()
    print("   [OK] Test cleanup complete.")

    print("\n======================================================================")
    print("ALL ITEM 3 SUBSCRIPTION LIMITS, BLOCKS & BOTTLENECKS VERIFIED!")
    print("======================================================================\n")

if __name__ == "__main__":
    test_item3_subscription_blocks()
