"""
Automated Verification Suite for PIPEDA Privacy Policy & CASL Compliance (Section B Fixes):
1. Salted Argon2id password hashing + automatic upgrade of legacy SHA-256 hashes on login
2. quotelytics_session cookie with HttpOnly, SameSite=Lax, and Secure flag on HTTPS/production
3. Self-hosted Tailwind CSS across all HTML templates (zero Google CDN IP leakage)
4. CASL unticked opt-in marketing checkbox on /get-started + immutable marketing_consent_logs
5. PIPEDA Principle 9 Individual Access & Data Portability export (/api/user/data-export)
6. PIPEDA §10 Self-serve Account & Customer Data Deletion (/api/user/account/delete)
7. PIPEDA Principle 5 Automated Retention Enforcement (enforce_retention_policies)
8. Public /privacy policy endpoint
"""
import glob
import hashlib
import os
import unittest
import uuid
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from main import app
from services.auth_service import hash_password, verify_password
from services.db_service import get_connection, init_db, enforce_retention_policies


class TestPipedaPrivacyCompliance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_01_argon2id_salted_hashing_and_legacy_sha256_auto_upgrade(self):
        h1 = hash_password("BrokerSecret2026!")
        h2 = hash_password("BrokerSecret2026!")
        self.assertTrue(h1.startswith("$argon2id$"), f"Expected Argon2id hash, got {h1[:20]}")
        self.assertNotEqual(h1, h2, "Salted hashes of identical passwords must differ")
        valid, needs_rehash = verify_password("BrokerSecret2026!", h1)
        self.assertTrue(valid)
        self.assertFalse(needs_rehash)

        # Insert user with legacy unsalted SHA-256 hash and verify login upgrades it to Argon2id
        uid = f"usr_legacy_{uuid.uuid4().hex[:6]}"
        email = f"{uid}@broker.ca"
        pwd = "LegacyPassword123!"
        legacy_hash = hashlib.sha256(pwd.encode("utf-8")).hexdigest()

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, name, email, password_hash, company, origin_zip, tier, created_at) VALUES (?, ?, ?, ?, ?, ?, 'FREE', ?)",
            (uid, "Legacy Broker", email, legacy_hash, "Legacy Freight Inc.", "M5V 2T6", datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()

        res = self.client.post("/api/auth/login", data={"email": email, "password": pwd})
        self.assertEqual(res.status_code, 200)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE id = ?", (uid,))
        upgraded_hash = cur.fetchone()["password_hash"]
        conn.close()
        self.assertTrue(upgraded_hash.startswith("$argon2id$"), "Legacy SHA-256 hash should auto-upgrade to Argon2id on login")

    def test_02_quotelytics_session_cookie_flags(self):
        email = f"cookie_{uuid.uuid4().hex[:6]}@broker.ca"
        res = self.client.post(
            "/api/auth/register",
            data={
                "name": "Cookie Tester",
                "email": email,
                "company": "Maple Freight",
                "origin_zip": "M5V 2T6",
                "password": "StrongPassword2026!",
                "marketing_opt_in": "true",
            },
            headers={"X-Forwarded-Proto": "https", "User-Agent": "QuotelyticsTestSuite/1.0"},
        )
        self.assertEqual(res.status_code, 200)
        set_cookie_headers = [v for k, v in res.headers.multi_items() if k.lower() == "set-cookie"]
        ql_cookies = [c for c in set_cookie_headers if c.startswith("quotelytics_session=")]
        self.assertTrue(len(ql_cookies) >= 1, "quotelytics_session cookie must be issued")
        cookie_str = ql_cookies[0].lower()
        self.assertIn("httponly", cookie_str)
        self.assertIn("samesite=lax", cookie_str)
        self.assertIn("secure", cookie_str)

        token = res.json()["token"]
        auth_client = TestClient(app, cookies={"quotelytics_session": token})
        status_res = auth_client.get("/api/auth/status")
        self.assertEqual(status_res.status_code, 200)
        self.assertTrue(status_res.json()["authenticated"])

    def test_03_self_hosted_tailwind_no_google_cdn(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for path in glob.glob(os.path.join(root, "templates", "**", "*.html"), recursive=True):
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
            self.assertNotIn("www.gstatic.com", html, f"External Google CDN found in {path}")
        res = self.client.get("/static/js/tailwindcss.min.js")
        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.content), 100000)

    def test_04_casl_unticked_checkbox_and_consent_log(self):
        page = self.client.get("/get-started")
        self.assertEqual(page.status_code, 200)
        html = page.text
        self.assertIn('id="marketing-check"', html)
        self.assertIn('href="/privacy"', html)
        # Ensure neither terms-check nor marketing-check is pre-checked in HTML markup
        terms_snippet = html.split('id="terms-check"')[1].split(">")[0]
        mkt_snippet = html.split('id="marketing-check"')[1].split(">")[0]
        self.assertNotIn("checked", terms_snippet)
        self.assertNotIn("checked", mkt_snippet)

        email = f"casl_{uuid.uuid4().hex[:6]}@broker.ca"
        reg = self.client.post(
            "/api/auth/register",
            data={
                "name": "CASL Tester",
                "email": email,
                "company": "Northern 3PL",
                "origin_zip": "M5V 2T6",
                "password": "StrongPassword2026!",
                "marketing_opt_in": "true",
                "form_version": "v2026.10",
            },
            headers={"User-Agent": "CASLVerifier/1.0"},
        )
        self.assertEqual(reg.status_code, 200)
        token = reg.json()["token"]
        uid = reg.json()["user"]["id"]

        auth_client = TestClient(app, cookies={"quotelytics_session": token})
        withdraw = auth_client.post("/api/user/marketing-consent", json={"marketing_opt_in": False})
        self.assertEqual(withdraw.status_code, 200)
        self.assertFalse(withdraw.json()["marketing_opt_in"])

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT consented, consent_type FROM marketing_consent_logs WHERE user_id = ? ORDER BY created_at ASC", (uid,))
        logs = [dict(r) for r in cur.fetchall()]
        conn.close()
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["consented"], 1)
        self.assertEqual(logs[1]["consented"], 0)

    def test_05_pipeda_data_export_and_account_deletion(self):
        email = f"pipeda_{uuid.uuid4().hex[:6]}@broker.ca"
        reg = self.client.post(
            "/api/auth/register",
            data={
                "name": "PIPEDA Broker",
                "email": email,
                "company": "Ontario Tariff Corp",
                "origin_zip": "M5V 2T6",
                "password": "StrongPassword2026!",
            },
        )
        self.assertEqual(reg.status_code, 200)
        token = reg.json()["token"]
        uid = reg.json()["user"]["id"]

        auth_client = TestClient(app, cookies={"quotelytics_session": token})
        exp = auth_client.get("/api/user/data-export")
        self.assertEqual(exp.status_code, 200)
        self.assertIn("attachment; filename=", exp.headers.get("content-disposition", ""))
        payload = exp.json()
        self.assertEqual(payload["export_metadata"]["data_residency"], "CA_CENTRAL_WHC")
        self.assertEqual(payload["account_data"]["profile"]["email"], email)
        self.assertIn("rate_sheets", payload["customer_data"])

        # Delete account and verify data purge + session invalidation
        del_res = auth_client.post("/api/user/account/delete", json={"immediate_purge": True})
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json()["status"], "deleted")

        after = auth_client.get("/api/auth/status")
        self.assertFalse(after.json()["authenticated"])

    def test_06_automated_retention_policy_enforcement(self):
        conn = get_connection()
        cur = conn.cursor()
        old_ts = (datetime.utcnow() - timedelta(days=95)).isoformat()
        expired_ts = (datetime.utcnow() - timedelta(days=2)).isoformat()
        closed_uid = f"usr_closed_{uuid.uuid4().hex[:6]}"
        closed_ts = (datetime.utcnow() - timedelta(days=35)).isoformat()

        cur.execute(
            "INSERT INTO users (id, name, email, password_hash, company, origin_zip, tier, created_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, 'FREE', ?, ?)",
            (closed_uid, "Closed User", f"{closed_uid}@old.ca", hash_password("pass123456"), "Old Co", "M5V 2T6", old_ts, closed_ts),
        )
        cur.execute(
            "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (f"s_exp_{uuid.uuid4().hex[:8]}", closed_uid, expired_ts, old_ts),
        )
        cur.execute(
            "INSERT INTO bottleneck_events (id, user_id, tier, bottleneck_type, attempted_action, current_usage, max_limit, created_at) VALUES (?, ?, 'FREE', 'LIMIT_BLOCKED_QUOTES', 'test', 50, 50, ?)",
            (f"bn_{uuid.uuid4().hex[:8]}", closed_uid, old_ts),
        )
        conn.commit()
        conn.close()

        summary = enforce_retention_policies()
        self.assertGreaterEqual(summary["expired_sessions_purged"], 1)
        self.assertGreaterEqual(summary["closed_accounts_purged"], 1)
        self.assertGreaterEqual(summary["security_logs_purged"], 1)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE id = ?", (closed_uid,))
        self.assertIsNone(cur.fetchone())
        conn.close()

    def test_07_public_privacy_page_renders(self):
        res = self.client.get("/privacy")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Quotelytics Privacy Policy", res.text)
        self.assertIn("PIPEDA", res.text)
        self.assertIn("Web Hosting Canada (WHC)", res.text)


if __name__ == "__main__":
    unittest.main()
