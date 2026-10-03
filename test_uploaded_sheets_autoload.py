"""
test_uploaded_sheets_autoload.py
================================
Verification suite for Automatic Rate Sheet Loading on User Login:
- Directive 1: Never auto-load benchmark sheets (only load sheets the user uploaded).
- Directive 2: Never calculate quotes unless explicitly requested by the user.
- Automatic loading of all user-uploaded rate sheets upon login.
- Persistence across logout / login cycles.
"""

import unittest
import io
import uuid
import openpyxl
from starlette.testclient import TestClient
from main import app
from services.auth_service import register_and_create_session, authenticate_and_create_session
from services.ratesift_db_service import list_rate_sheets, confirm_rate_sheet

client = TestClient(app)

class TestUploadedSheetsAutoLoad(unittest.TestCase):

    def test_01_directive1_never_autoload_benchmark_sheets(self):
        """Verify that newly registered users have 0 sheets (no synthetic or benchmark seeding)."""
        test_email = f"autoload_new_{uuid.uuid4().hex[:8]}@example.com"
        user, token = register_and_create_session(
            name="New Broker",
            email=test_email,
            company="New Logistics Inc",
            origin_zip="TORONTO, ON",
            password="SecurePassword123!"
        )
        
        # Check database directly
        db_sheets = list_rate_sheets(user["id"])
        self.assertEqual(len(db_sheets), 0, "Directive 1 Violation: Brand new user must not have benchmark sheets auto-seeded.")

        # Check API endpoint via authenticated session
        res = client.get("/api/ratesift/sheets", cookies={"ratesift_session": token})
        self.assertEqual(res.status_code, 200)
        api_sheets = res.json().get("sheets", [])
        self.assertEqual(len(api_sheets), 0, "Directive 1 Violation: API must return 0 sheets for new user.")

    def test_02_directive2_console_view_does_not_auto_quote(self):
        """Verify that loading console view returns HTML without triggering calculation endpoints."""
        test_email = f"autoload_login_{uuid.uuid4().hex[:8]}@example.com"
        user, token = register_and_create_session(
            name="Silent Quote Broker",
            email=test_email,
            company="Silent Freight Co",
            origin_zip="TORONTO, ON",
            password="SecurePassword123!"
        )

        res = client.get("/console/new-quote", cookies={"ratesift_session": token})
        self.assertEqual(res.status_code, 200)
        self.assertIn("Your Uploaded Rate Sheets:", res.text)
        self.assertIn("loaded-tariffs-tray", res.text)
        # Ensure calculateFreightQuote(true) was removed from DOMContentLoaded
        self.assertNotIn("calculateFreightQuote(true);", res.text, "Directive 2 Violation: calculateFreightQuote(true) must not be present.")

    def test_03_uploaded_sheets_autoload_on_login(self):
        """Verify that when a user uploads sheets, they automatically load on login and persist across sessions."""
        test_email = f"broker_with_sheets_{uuid.uuid4().hex[:8]}@example.com"
        user, token1 = register_and_create_session(
            name="Active Broker",
            email=test_email,
            company="Active Freight Ltd",
            origin_zip="TORONTO, ON",
            password="SecurePassword123!"
        )

        # Upload a recognized carrier rate sheet from sample_sheets
        guide_csv_path = "sample_sheets/day_and_ross_guide_tariff.csv"
        with open(guide_csv_path, "rb") as f:
            file_bytes = f.read()

        client.cookies.set("ratesift_session", token1)
        upload_res = client.post(
            "/api/ratesift/sheets/upload",
            files={"file": ("day_and_ross_custom_upload.csv", file_bytes, "text/csv")}
        )
        self.assertEqual(upload_res.status_code, 200, f"Upload failed: {upload_res.text}")
        sheet_id = upload_res.json()["sheet_id"]

        # Confirm the uploaded sheet
        confirm_rate_sheet(
            sheet_id=sheet_id,
            user_id=user["id"],
            confirmed_by="Active Broker",
            effective_date="2020-01-01",
            expiry_date="2030-12-31"
        )

        # Simulate User Logging Out & Logging In Again
        client.get("/api/auth/logout")

        # Login again
        login_res = client.post(
            "/api/auth/login",
            data={"email": test_email, "password": "SecurePassword123!"}
        )
        self.assertEqual(login_res.status_code, 200)
        token2 = login_res.json().get("token")
        self.assertIsNotNone(token2)

        # Set new session cookie
        client.cookies.set("ratesift_session", token2)

        # Verify that upon login, GET /api/ratesift/sheets automatically returns the user's uploaded sheet
        sheets_res = client.get("/api/ratesift/sheets")
        self.assertEqual(sheets_res.status_code, 200)
        loaded_sheets = sheets_res.json().get("sheets", [])
        self.assertEqual(len(loaded_sheets), 1, "Uploaded rate sheet must automatically load upon login.")
        self.assertEqual(loaded_sheets[0]["carrier_name"], "Day & Ross")
        self.assertEqual(loaded_sheets[0]["confirmation_status"], "CONFIRMED")

    def test_04_explicit_user_quoting_works(self):
        """Verify that quoting only executes when the user explicitly requests it."""
        test_email = f"broker_quoter_{uuid.uuid4().hex[:8]}@example.com"
        user, token = register_and_create_session(
            name="Quoting Broker",
            email=test_email,
            company="Precision Logistics",
            origin_zip="TORONTO, ON",
            password="SecurePassword123!"
        )

        # Upload & confirm a sheet for this user
        guide_csv_path = "sample_sheets/day_and_ross_guide_tariff.csv"
        with open(guide_csv_path, "rb") as f:
            file_bytes = f.read()

        client.cookies.set("ratesift_session", token)
        upload_res = client.post(
            "/api/ratesift/sheets/upload",
            files={"file": ("day_and_ross_quote_sheet.csv", file_bytes, "text/csv")}
        )
        self.assertEqual(upload_res.status_code, 200)
        sheet_id = upload_res.json()["sheet_id"]

        confirm_rate_sheet(
            sheet_id=sheet_id,
            user_id=user["id"],
            confirmed_by="Quoting Broker",
            effective_date="2020-01-01",
            expiry_date="2030-12-31"
        )

        # Explicit user calculation request
        payload = {
            "origin": "CALGARY, AB",
            "destination": "LINDSAY, ON",
            "actual_weight": 850.0,
            "accessorials": ["appointment"],
            "shipment_date": "2026-10-01"
        }
        quote_res = client.post(
            "/api/ratesift/quotes/calculate",
            json=payload
        )
        self.assertEqual(quote_res.status_code, 200, f"Quoting failed: {quote_res.text}")
        quotes = quote_res.json().get("quotes", [])
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]["carrier_name"], "Day & Ross")
        self.assertGreater(quotes[0]["final_total"], 0)

if __name__ == "__main__":
    unittest.main()
