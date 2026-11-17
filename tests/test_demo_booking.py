import os
import re
import unittest
import uuid
from fastapi.testclient import TestClient

from main import app
from services.auth_service import register_and_create_session
from services.db_service import get_connection, init_db


class TestLiveDemoBookingAndROI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_01_availability_booking_double_book_guard_and_ics(self):
        """Verifies availability lookup, booking creation, 409 double-booking guard, and .ics download."""
        avail_res = self.client.get("/api/demo/availability?days=10")
        self.assertEqual(avail_res.status_code, 200)
        avail_data = avail_res.json()
        self.assertEqual(avail_data["status"], "success")
        self.assertTrue(len(avail_data["days"]) >= 5)

        first_day = next((d for d in avail_data["days"] if d["slots"]), None)
        self.assertIsNotNone(first_day)
        target_date = first_day["date"]
        target_time = first_day["slots"][-1]

        # Book the slot with ROI snapshot
        book_payload = {
            "full_name": "Jordan Blake",
            "email": f"jordan.{uuid.uuid4().hex[:6]}@maplefreight.ca",
            "company": "Maple Freight Logistics",
            "scheduled_date": target_date,
            "scheduled_time": target_time,
            "timezone": "America/Toronto",
            "duration_minutes": 15,
            "carrier_sheet_count": "6-15",
            "notes": "Want to test L5C skid sheets",
            "roi_estimate": {
                "quotes_per_week": 60,
                "total_monthly_value_cad": 2150,
            },
        }
        res = self.client.post("/api/demo/book", json=book_payload)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "success")
        booking = body["booking"]
        self.assertTrue(booking["id"].startswith("ql_demo_"))
        self.assertEqual(booking["scheduled_date"], target_date)
        self.assertEqual(booking["scheduled_time"], target_time)

        # Verify slot is no longer available
        avail_after = self.client.get("/api/demo/availability?days=10").json()
        day_after = next((d for d in avail_after["days"] if d["date"] == target_date), None)
        self.assertIsNotNone(day_after)
        self.assertNotIn(target_time, day_after["slots"])

        # Attempting to double-book the exact same slot must return 409 Conflict
        dup_res = self.client.post("/api/demo/book", json=book_payload)
        self.assertEqual(dup_res.status_code, 409)

        # Verify .ics calendar invite download
        ics_res = self.client.get(body["ics_url"])
        self.assertEqual(ics_res.status_code, 200)
        self.assertIn("text/calendar", ics_res.headers.get("content-type", ""))
        self.assertIn("BEGIN:VCALENDAR", ics_res.text)
        self.assertIn("Maple Freight Logistics", ics_res.text)

    def test_02_admin_demo_bookings_requires_admin_role(self):
        """Verifies /api/admin/demo-bookings is strictly protected by ADMIN role."""
        # Unauthenticated -> 401
        unauth = self.client.get("/api/admin/demo-bookings")
        self.assertEqual(unauth.status_code, 401)

        # Regular user -> 403
        user, token = register_and_create_session(
            name="Regular User",
            email=f"reg.{uuid.uuid4().hex[:6]}@quotelytics.ca",
            company="Regular Co",
            origin_zip="M5V 2T6",
            password="RegularUserPass2026!",
        )
        c_user = TestClient(app)
        c_user.cookies.set("quotelytics_session", token)
        self.assertEqual(c_user.get("/api/admin/demo-bookings").status_code, 403)

        # Promote to ADMIN -> 200
        conn = get_connection()
        conn.execute("UPDATE users SET role = 'ADMIN' WHERE id = ?", (user["id"],))
        conn.commit()
        conn.close()
        admin_res = c_user.get("/api/admin/demo-bookings")
        self.assertEqual(admin_res.status_code, 200)
        self.assertEqual(admin_res.json()["status"], "success")

    def test_03_demo_html_no_video_no_emojis_and_consistent_headers(self):
        """Verifies demo.html has ROI + Calendar, zero video/emojis, and all public headers match."""
        root = os.path.dirname(os.path.dirname(__file__))
        demo_path = os.path.join(root, "templates", "public", "demo.html")
        with open(demo_path, "r", encoding="utf-8") as fh:
            demo_html = fh.read()

        self.assertNotIn("<video", demo_html.lower())
        self.assertNotIn("<iframe", demo_html.lower())
        self.assertIn("Freight Quoting ROI Calculator", demo_html)
        self.assertIn("Book Your 15-Min Live Demo", demo_html)
        self.assertIn("/api/demo/availability", demo_html)
        self.assertIn("/api/demo/book", demo_html)
        # Ensure zero emoji characters (U+1F300..U+1FAFF or U+2139 info symbol)
        self.assertIsNone(re.search(r"[\U0001F300-\U0001FAFF\u2139]", demo_html))

        for fname in ("home.html", "demo.html", "pricing.html", "login.html", "get_started.html", "privacy.html"):
            p = os.path.join(root, "templates", "public", fname)
            with open(p, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn(">Live Demo</a>", content, f"{fname} missing 'Live Demo' nav link")
            self.assertIn("Request Beta Access", content, f"{fname} missing 'Request Beta Access' CTA")


if __name__ == "__main__":
    unittest.main()
