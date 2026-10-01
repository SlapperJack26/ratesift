from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_phase2():
    print("1. Testing Route Guarding (Unauthenticated Access)...")
    # Test unauthenticated access to /console/new-quote
    res = client.get("/console/new-quote", follow_redirects=False)
    assert res.status_code == 303, f"Expected 303 redirect, got {res.status_code}"
    assert "/login" in res.headers["location"], f"Expected redirect to /login, got {res.headers['location']}"
    print("   [OK] /console/new-quote correctly redirected unauthenticated request to /login")

    # Test unauthenticated access to /console/history
    res = client.get("/console/history", follow_redirects=False)
    assert res.status_code == 303
    assert "/login" in res.headers["location"]
    print("   [OK] /console/history correctly redirected unauthenticated request to /login")

    print("\n2. Testing Authentication & Session Cookie Generation...")
    login_data = {
        "email": "alex.rivers@techcorp.io",
        "password": "ShipFlowDemo2026!"
    }
    res = client.post("/api/auth/login", data=login_data)
    assert res.status_code == 200, f"Login failed: {res.text}"
    body = res.json()
    assert body["status"] == "success"
    assert "ratesift_session" in res.cookies
    token = res.cookies["ratesift_session"]
    print(f"   [OK] Login successful! Session token issued: {token[:12]}...")

    print("\n3. Testing Authenticated Route Access...")
    # Use session cookie
    auth_client = TestClient(main.app, cookies={"ratesift_session": token})
    res = auth_client.get("/console/new-quote")
    assert res.status_code == 200
    assert "Freight Rating Engine" in res.text or "New Quote" in res.text
    print("   [OK] /console/new-quote accessible with session cookie (HTTP 200)")

    res = auth_client.get("/console/history")
    assert res.status_code == 200
    print("   [OK] /console/history accessible with session cookie (HTTP 200)")

    print("\n4. Testing Session Status Endpoint...")
    res = auth_client.get("/api/auth/status")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["authenticated"] is True
    assert status_data["user"]["name"] == "Alex Rivers"
    assert status_data["user"]["company"] == "TechCorp Logistics"
    print(f"   [OK] Session active for {status_data['user']['name']} ({status_data['user']['company']})")

    print("\n5. Testing Subscription Quota Tracking...")
    res = auth_client.get("/api/user/quota")
    assert res.status_code == 200
    quota = res.json()
    assert quota["tier"] == "FREE"
    assert quota["max_sheets"] == 3
    assert quota["max_quotes_per_month"] == 50
    print(f"   [OK] Quota verified: Tier={quota['tier_name']}, Max Sheets={quota['max_sheets']}, Monthly Quotes Max={quota['max_quotes_per_month']}, Used={quota['monthly_quotes_used']}")

    print("\n6. Testing User Registration & Auto-Session Creation...")
    reg_data = {
        "name": "Jordan Case",
        "email": "jordan.case@premierfreight.com",
        "company": "Premier Freight Partners",
        "origin_zip": "60601",
        "password": "Password123!"
    }
    res = client.post("/api/auth/register", data=reg_data)
    assert res.status_code == 200
    reg_body = res.json()
    assert reg_body["status"] == "success"
    assert reg_body["user"]["name"] == "Jordan Case"
    assert "shipflow_session" in res.cookies
    print(f"   [OK] Registered new user {reg_body['user']['name']} with session cookie")

    print("\n7. Testing Logout & Session Revocation...")
    res = auth_client.get("/api/auth/logout", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/"
    print("   [OK] Logout revoked session and redirected to public home page")

    print("\nALL PHASE 2 AUTHENTICATION & QUOTA TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_phase2()
