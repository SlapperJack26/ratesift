"""
Test Suite for Item 1: Account Settings
- Account profile details update (Name, Company, Direct Phone)
- Origin defaults persistence (Origin Address, Origin City / Postal FSA)
- Form and JSON support for profile updates
- Quoting & calculation preferences update (Currency CAD/USD, Units kg/lbs, Markup %, Markup Mode, Fuel Surcharge Passthrough)
- Secure password change flow (current password verification, length requirement, hash update, re-login verification)
"""
import uuid
from fastapi.testclient import TestClient
from main import app
from services.db_service import get_connection, init_db
from services.auth_service import hash_password

def run_tests():
    init_db()
    client = TestClient(app)

    print("==================================================")
    print("Testing Item 1: Account Settings & Preferences")
    print("==================================================")

    # Register a fresh dedicated user for testing
    user_email = f"settings_user_{uuid.uuid4().hex[:6]}@techcorp.io"
    user_pwd = "InitialPassword2026!"
    reg = client.post("/api/auth/register", data={
        "name": "Alex Rivers",
        "email": user_email,
        "company": "TechCorp Logistics",
        "origin_zip": "M5V 2T6",
        "password": user_pwd
    })
    assert reg.status_code == 200, f"Registration failed: {reg.text}"
    session = reg.cookies.get("shipflow_session")
    auth_client = TestClient(app, cookies={"shipflow_session": session})

    print("\n--- 1. Testing Profile & Origin Defaults Update via Form Data ---")
    form_data = {
        "name": "Alexander Rivers",
        "company": "TechCorp Logistics Canada Inc.",
        "origin_zip": "M5V 2T6",
        "origin_address": "100 King St W, Suite 400",
        "phone": "+1 (416) 555-9876"
    }
    res = auth_client.post("/api/user/account/update", data=form_data)
    assert res.status_code == 200, f"Form update failed: {res.text}"
    assert res.json()["status"] == "success"

    # Verify profile reflects changes
    prof = auth_client.get("/api/user/profile").json()
    assert prof["name"] == "Alexander Rivers"
    assert prof["company"] == "TechCorp Logistics Canada Inc."
    assert prof["origin_zip"] == "M5V 2T6"
    assert prof["origin_address"] == "100 King St W, Suite 400"
    assert prof["phone"] == "+1 (416) 555-9876"
    print("   [OK] Form update successfully persisted name, company, origin_zip, origin_address, and phone")

    print("\n--- 2. Testing Profile & Origin Defaults Update via JSON Payload ---")
    json_data = {
        "name": "Alex Rivers",
        "company": "TechCorp Logistics",
        "origin_zip": "TORONTO, ON",
        "origin_address": "5500 Logistics Way, Bay 12",
        "phone": "+1 (416) 555-0199"
    }
    res = auth_client.post("/api/user/account/update", json=json_data)
    assert res.status_code == 200, f"JSON update failed: {res.text}"
    assert res.json()["status"] == "success"

    prof = auth_client.get("/api/user/profile").json()
    assert prof["name"] == "Alex Rivers"
    assert prof["company"] == "TechCorp Logistics"
    assert prof["origin_zip"] == "TORONTO, ON"
    assert prof["origin_address"] == "5500 Logistics Way, Bay 12"
    assert prof["phone"] == "+1 (416) 555-0199"
    print("   [OK] JSON update successfully persisted updated profile and origin defaults")

    print("\n--- 3. Testing Calculation Settings Update via Form Data ---")
    settings_form = {
        "currency": "CAD",
        "units": "kg",
        "markup_pct": 14.5,
        "markup_mode": "flat",
        "fsc_passthrough": 0,
        "auto_detect_headers": 1,
        "skip_blank_rows": 1
    }
    res = auth_client.post("/api/settings/update", data=settings_form)
    assert res.status_code == 200, f"Settings form update failed: {res.text}"

    prof = auth_client.get("/api/user/profile").json()
    assert prof["currency"] == "CAD"
    assert prof["units"] == "kg"
    assert prof["markup_pct"] == 14.5
    assert prof["markup_mode"] == "flat"
    assert prof["fsc_passthrough"] == 0
    print("   [OK] Form settings update successfully persisted CAD, kg, markup 14.5%, flat mode, fsc 0")

    print("\n--- 4. Testing Calculation Settings Update via JSON ---")
    settings_json = {
        "currency": "USD",
        "units": "lbs",
        "markup_pct": 12.0,
        "markup_mode": "percent",
        "fsc_passthrough": 1,
        "auto_detect_headers": 1,
        "skip_blank_rows": 1
    }
    res = auth_client.post("/api/settings/update", json=settings_json)
    assert res.status_code == 200, f"Settings JSON update failed: {res.text}"

    prof = auth_client.get("/api/user/profile").json()
    assert prof["currency"] == "USD"
    assert prof["units"] == "lbs"
    assert prof["markup_pct"] == 12.0
    assert prof["markup_mode"] == "percent"
    assert prof["fsc_passthrough"] == 1
    print("   [OK] JSON settings update successfully persisted USD, lbs, markup 12.0%, percent mode, fsc 1")

    print("\n--- 5. Testing Password Security Flow ---")
    new_pwd = "UpgradedPassword2026!"

    # 5a. Incorrect current password rejected
    bad_res = auth_client.post("/api/user/password", json={
        "current_password": "WrongPassword999!",
        "new_password": new_pwd
    })
    assert bad_res.status_code == 400
    assert "Current password incorrect" in bad_res.json().get("detail", "")
    print("   [OK] Rejection of incorrect current password verified (HTTP 400)")

    # 5b. Short new password rejected
    short_res = auth_client.post("/api/user/password", json={
        "current_password": user_pwd,
        "new_password": "abc"
    })
    assert short_res.status_code == 400
    assert "at least 6 characters" in short_res.json().get("detail", "")
    print("   [OK] Rejection of short password verified (HTTP 400)")

    # 5c. Valid password update
    pwd_res = auth_client.post("/api/user/password", json={
        "current_password": user_pwd,
        "new_password": new_pwd
    })
    assert pwd_res.status_code == 200, f"Password update failed: {pwd_res.text}"
    assert pwd_res.json()["status"] == "success"
    print("   [OK] Password successfully updated to new password")

    # 5d. Old password cannot authenticate
    old_login = client.post("/api/auth/login", data={"email": user_email, "password": user_pwd})
    assert old_login.status_code == 401
    print("   [OK] Old password rejected after update")

    # 5e. New password authenticates successfully
    new_login = client.post("/api/auth/login", data={"email": user_email, "password": new_pwd})
    assert new_login.status_code == 200
    print("   [OK] New password authenticates successfully")

    print("\n==================================================")
    print("ALL ITEM 1 ACCOUNT SETTINGS TESTS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
