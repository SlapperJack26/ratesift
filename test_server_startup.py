import sys
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_routes():
    print("Testing GET / (Home)...")
    r = client.get("/")
    assert r.status_code == 200
    assert "Ratesift" in r.text
    print("[OK] Home OK")

    print("Testing GET /demo (Demo)...")
    r = client.get("/demo")
    assert r.status_code == 200
    assert "Interactive Demo" in r.text or "rAtesift" in r.text
    print("[OK] Demo OK")

    print("Testing GET /pricing (Pricing)...")
    r = client.get("/pricing")
    assert r.status_code == 200
    assert "Business" in r.text
    print("[OK] Pricing OK")

    print("Testing GET /login (Login)...")
    r = client.get("/login")
    assert r.status_code == 200
    print("[OK] Login OK")

    print("Testing GET /get-started (Get Started)...")
    r = client.get("/get-started")
    assert r.status_code == 200
    assert "Create your account" in r.text
    print("[OK] Get Started OK")

    # Authenticate to access console screens
    login_res = client.post("/api/auth/login", data={"email": "alex.rivers@techcorp.io", "password": "ShipFlowDemo2026!"})
    assert login_res.status_code == 200

    print("Testing GET /console/new-quote (New Rate Sheet / Quote)...")
    r = client.get("/console/new-quote")
    assert r.status_code == 200
    assert "New Quote" in r.text or "RateSift" in r.text
    print("[OK] Console New Rate Sheet OK")

    print("Testing GET /console/history (Quotes History)...")
    r = client.get("/console/history")
    assert r.status_code == 200
    print("[OK] Console History OK")

    print("Testing GET /api/quotes/history (REST API)...")
    r = client.get("/api/quotes/history")
    assert r.status_code == 200
    data = r.json()
    assert "quotes" in data
    print(f"[OK] Quotes API OK (found {data['total']} seeded quotes with cell coordinates)")

    print("\nALL 8 CORE ENDPOINTS VERIFIED & ROUTING TEST PASSED!")

if __name__ == "__main__":
    test_routes()
