import unittest
from fastapi.testclient import TestClient
from main import app
from services.db_service import get_connection, save_proposal_quote_item

class TestQuoteHistoryPaginationAndSorting(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Login with test credentials
        res = self.client.post("/api/auth/login", data={"email": "alex.rivers@techcorp.io", "password": "RateSiftDemo2026!"})
        self.assertEqual(res.status_code, 200)

    def test_save_proposal_quote_and_persistence(self):
        # 1. Preview a client proposal
        prop_payload = {
            "quote_id": None,
            "carrier_name": "Midland Transport",
            "service_name": "Expedited Road LTL",
            "origin": "TORONTO, ON",
            "destination": "HALIFAX, NS",
            "weight_lbs": 1500.0,
            "base_rate": 420.00,
            "total_surcharges": 45.00,
            "surcharges": [{"code": "FSC", "name": "Fuel Surcharge", "amount": 45.00}],
            "transit_days": 2,
            "currency": "CAD",
            "client_name": "Atlantic Maritime Logistics",
            "markup_pct": 20.0
        }
        res = self.client.post("/api/quotes/client-proposal/preview", json=prop_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        proposal = data["proposal"]
        proposal_id = proposal["proposal_id"]

        # 2. Check quote history returns this quote
        hist_res = self.client.get("/api/quotes/history")
        self.assertEqual(hist_res.status_code, 200)
        hist_quotes = hist_res.json()["quotes"]
        quote_ids = [q["id"] for q in hist_quotes]
        self.assertIn(proposal_id, quote_ids)

        saved = next(q for q in hist_quotes if q["id"] == proposal_id)
        self.assertEqual(saved["carrier"], "Midland Transport")
        self.assertEqual(saved["service"], "Expedited Road LTL")
        self.assertEqual(saved["origin_zip"], "TORONTO, ON")
        self.assertEqual(saved["dest_zip"], "HALIFAX, NS")
        self.assertEqual(saved["weight_lbs"], 1500.0)
        self.assertAlmostEqual(saved["final_rate"], proposal["pricing"]["client_total"], places=2)
        self.assertIn(proposal_id, saved["coordinate"])

        # 3. Simulate user logout and re-login
        self.client.get("/api/auth/logout")
        login_res = self.client.post("/api/auth/login", data={"email": "alex.rivers@techcorp.io", "password": "RateSiftDemo2026!"})
        self.assertEqual(login_res.status_code, 200)

        # 4. Quotes History data loaded every time user logs in
        hist_res_2 = self.client.get("/api/quotes/history")
        self.assertEqual(hist_res_2.status_code, 200)
        reloaded_ids = [q["id"] for q in hist_res_2.json()["quotes"]]
        self.assertIn(proposal_id, reloaded_ids)

    def test_history_page_markup_pagination_and_sorting(self):
        res = self.client.get("/console/history")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Verify 10-quote pagination capping
        self.assertIn("pageSize = 10", html)
        self.assertIn("btn-prev-page", html)
        self.assertIn("btn-next-page", html)
        self.assertIn("page-indicator", html)
        self.assertIn("page-start", html)
        self.assertIn("page-end", html)
        self.assertIn("total-quotes-count", html)

        # Verify next page & previous page functions
        self.assertIn("function prevPage()", html)
        self.assertIn("function nextPage()", html)

        # Verify sorting on every header
        headers = ["id", "carrier", "route", "sheet", "date", "rate", "proposal"]
        for h in headers:
            self.assertIn(f"toggleSort('{h}')", html)
            self.assertIn(f"sort-icon-{h}", html)

        # Verify sort indicators update logic
        self.assertIn("function updateSortIndicators()", html)

if __name__ == "__main__":
    unittest.main()
