"""
Verification suite for GTM Plan Header 6 (Item #2, #5, #7):
- Email verification at signup + resend verification + one-time token verification
- Self-serve password reset flow (forgot-password -> hashed token -> reset-password -> session revocation)
- Anti-enumeration & rate limiting on forgot-password (HTTP 429 + Retry-After)
- 10-character password policy & Canadian postal code / CAD defaults
"""
import uuid
from fastapi.testclient import TestClient

from main import app, clear_login_throttle, clear_password_reset_throttle
from services.db_service import get_connection, init_db
from services.email_service import get_sent_emails, clear_sent_emails


def test_01_public_forgot_and_reset_password_pages():
    init_db()
    client = TestClient(app)

    r_login = client.get("/login")
    assert r_login.status_code == 200
    assert 'href="/forgot-password"' in r_login.text

    r_forgot = client.get("/forgot-password")
    assert r_forgot.status_code == 200
    assert "/api/auth/forgot-password" in r_forgot.text

    r_reset = client.get("/reset-password?token=rst_sample")
    assert r_reset.status_code == 200
    assert "/api/auth/reset-password" in r_reset.text

    r_signup = client.get("/get-started")
    assert r_signup.status_code == 200
    assert 'value="M5V 2T6"' in r_signup.text
    assert "At least 10 characters" in r_signup.text


def test_02_signup_email_verification_and_resend_flow():
    init_db()
    clear_sent_emails()
    client = TestClient(app)

    email = f"verify.{uuid.uuid4().hex[:6]}@maple-freight.ca"
    reg = client.post(
        "/api/auth/register",
        data={
            "name": "Claire Dispatcher",
            "email": email,
            "company": "Maple Freight Inc.",
            "origin_zip": "M5V 2T6",
            "password": "ClaireStrongPassword2026!",
        },
    )
    assert reg.status_code == 200, reg.text
    session_token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]
    assert reg.json()["user"]["email_verified"] is False

    # Verify verification email was queued on registration
    sent = get_sent_emails(to_email=email, category="EMAIL_VERIFY")
    assert len(sent) == 1
    first_verify_token = sent[0]["metadata"]["token"]
    assert first_verify_token.startswith("ver_")

    # Ensure raw token is NOT stored in plaintext in SQLite
    conn = get_connection()
    raw_row = conn.execute("SELECT * FROM auth_tokens WHERE token_hash = ?", (first_verify_token,)).fetchone()
    hashed_rows = conn.execute("SELECT * FROM auth_tokens WHERE user_id = ? AND token_type = 'EMAIL_VERIFY'", (user_id,)).fetchall()
    conn.close()
    assert raw_row is None
    assert len(hashed_rows) == 1

    # Logged-out resend -> 401
    anon_client = TestClient(app)
    anon_resend = anon_client.post("/api/auth/resend-verification")
    assert anon_resend.status_code == 401

    # Logged-in resend -> issues fresh token and invalidates prior unused token
    auth_client = TestClient(app, cookies={"quotelytics_session": session_token})
    resend_res = auth_client.post("/api/auth/resend-verification")
    assert resend_res.status_code == 200
    sent_after = get_sent_emails(to_email=email, category="EMAIL_VERIFY")
    assert len(sent_after) == 2
    second_verify_token = sent_after[-1]["metadata"]["token"]
    assert second_verify_token != first_verify_token

    # First token was invalidated by resend
    old_ver = client.get(f"/api/auth/verify-email?token={first_verify_token}")
    assert old_ver.status_code == 400

    # Second token verifies email
    ok_ver = client.get(f"/api/auth/verify-email?token={second_verify_token}")
    assert ok_ver.status_code == 200
    assert ok_ver.json()["email_verified"] is True

    # Profile now reflects email_verified = True
    prof = auth_client.get("/api/user/profile").json()
    assert prof["email_verified"] is True
    assert prof["currency"] == "CAD"

    # Re-using the verification token a second time is rejected
    replay_ver = client.get(f"/api/auth/verify-email?token={second_verify_token}")
    assert replay_ver.status_code == 400


def test_03_password_reset_flow_and_session_revocation():
    init_db()
    clear_sent_emails()
    clear_login_throttle()
    clear_password_reset_throttle()
    client = TestClient(app)

    email = f"reset.{uuid.uuid4().hex[:6]}@maple-freight.ca"
    old_pwd = "OldPassword2026!"
    new_pwd = "NewResetPassword2026!"

    reg = client.post(
        "/api/auth/register",
        data={
            "name": "Marc Broker",
            "email": email,
            "company": "St. Lawrence 3PL",
            "origin_zip": "H3B 4W8",
            "password": old_pwd,
        },
    )
    assert reg.status_code == 200
    old_session = reg.json()["token"]

    # 1. Request password reset for unknown email -> still returns 200 (no enumeration) and sends no email
    unknown_res = client.post("/api/auth/forgot-password", data={"email": "nobody@nonexistent-broker.ca"})
    assert unknown_res.status_code == 200
    assert len(get_sent_emails(to_email="nobody@nonexistent-broker.ca", category="PASSWORD_RESET")) == 0

    # 2. Request password reset for registered user -> returns 200 and sends reset token
    forgot_res = client.post("/api/auth/forgot-password", data={"email": email})
    assert forgot_res.status_code == 200
    reset_emails = get_sent_emails(to_email=email, category="PASSWORD_RESET")
    assert len(reset_emails) == 1
    reset_token = reset_emails[0]["metadata"]["token"]
    assert reset_token.startswith("rst_")

    # 3. Short password (< 10 chars) is rejected without consuming the token
    short_res = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "short123"},
    )
    assert short_res.status_code == 400
    assert "at least 10 characters" in short_res.json()["detail"]

    # 4. Valid password reset succeeds and revokes existing session
    reset_ok = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": new_pwd},
    )
    assert reset_ok.status_code == 200
    assert reset_ok.json()["status"] == "success"

    # 5. Re-using the same reset token is rejected
    replay_res = client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "AnotherPassword2026!"},
    )
    assert replay_res.status_code == 400

    # 6. Old session token was revoked upon password reset
    old_auth_client = TestClient(app, cookies={"quotelytics_session": old_session})
    assert old_auth_client.get("/api/user/profile").status_code == 401

    # 7. Old password no longer logs in; new password logs in cleanly
    assert client.post("/api/auth/login", data={"email": email, "password": old_pwd}).status_code == 401
    new_login = client.post("/api/auth/login", data={"email": email, "password": new_pwd})
    assert new_login.status_code == 200


def test_04_forgot_password_rate_limiting():
    init_db()
    clear_password_reset_throttle()
    try:
        client = TestClient(app)
        target = f"ratelimit.{uuid.uuid4().hex[:6]}@maple-freight.ca"
        for _ in range(5):
            r = client.post("/api/auth/forgot-password", data={"email": target})
            assert r.status_code == 200
        r6 = client.post("/api/auth/forgot-password", data={"email": target})
        assert r6.status_code == 429
        assert "retry-after" in {k.lower() for k in r6.headers.keys()}
    finally:
        clear_password_reset_throttle()
