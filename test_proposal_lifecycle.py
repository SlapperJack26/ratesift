import unittest
from fastapi.testclient import TestClient
from main import app, _active_proposal_memory

class TestProposalEmailLifecycle(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Login
        res = self.client.post("/api/auth/login", data={"email": "alex.rivers@techcorp.io", "password": "RateSiftDemo2026!"})
        self.assertEqual(res.status_code, 200)

    def test_full_proposal_email_lifecycle(self):
        # 1. Calculate Quote 1
        calc1 = self.client.post("/api/ratesift/quotes/calculate", json={
            "origin": "TORONTO, ON",
            "destination": "MONTREAL, QC",
            "actual_weight": 1250,
            "accessorials": ["TAILGATE_DELIVERY"]
        })
        self.assertEqual(calc1.status_code, 200)
        q1_data = calc1.json()
        self.assertTrue(len(q1_data.get("quotes", [])) > 0)
        first_quote = q1_data["quotes"][0]

        # 2. Check proposal memory is empty after quote generation
        mem1 = self.client.get("/api/quotes/client-proposal/memory").json()
        self.assertFalse(mem1["has_active_proposal"])
        self.assertIsNone(mem1["proposal"])

        # 3. User clicks 'Create Client Proposal' -> Preview & Email generated
        prop_res = self.client.post("/api/quotes/client-proposal/preview", json={
            "quote_id": first_quote.get("quote_id"),
            "carrier_name": first_quote.get("carrier_name"),
            "service_name": first_quote.get("service_name"),
            "origin": first_quote.get("origin"),
            "destination": first_quote.get("destination"),
            "weight_lbs": first_quote.get("billable_weight"),
            "base_rate": first_quote.get("base_rate"),
            "total_surcharges": first_quote.get("total_surcharges"),
            "surcharges": first_quote.get("surcharges"),
            "transit_days": first_quote.get("transit_days"),
            "currency": first_quote.get("currency"),
            "client_name": "Apex Manufacturing Ltd",
            "markup_pct": 18.0
        })
        self.assertEqual(prop_res.status_code, 200)
        prop = prop_res.json()["proposal"]

        # Verify email contents
        self.assertIn("email", prop)
        email = prop["email"]
        self.assertIn("subject", email)
        self.assertIn("body_text", email)
        self.assertIn("body_html", email)
        self.assertIn("TORONTO, ON", email["subject"])
        self.assertIn("MONTREAL, QC", email["subject"])
        self.assertIn("Rate Lock Guarantee", email["body_text"])
        self.assertIn("Apex Manufacturing Ltd", email["body_text"])
        self.assertIn("CAD", email["body_text"])

        # 4. Check proposal is in memory
        mem2 = self.client.get("/api/quotes/client-proposal/memory").json()
        self.assertTrue(mem2["has_active_proposal"])
        self.assertEqual(mem2["proposal"]["proposal_id"], prop["proposal_id"])

        # 5. User generates their next quote
        calc2 = self.client.post("/api/ratesift/quotes/calculate", json={
            "origin": "CALGARY, AB",
            "destination": "VANCOUVER, BC",
            "actual_weight": 850,
            "accessorials": []
        })
        self.assertEqual(calc2.status_code, 200)

        # 6. Verify proposal was DELETED from memory upon generating next quote
        mem3 = self.client.get("/api/quotes/client-proposal/memory").json()
        self.assertFalse(mem3["has_active_proposal"])
        self.assertIsNone(mem3["proposal"])

        # 7. Verify the quote was PERSISTENTLY saved to Quotes History
        hist_res = self.client.get("/api/quotes/history")
        self.assertEqual(hist_res.status_code, 200)
        hist_data = hist_res.json()
        saved_ids = [q["id"] for q in hist_data["quotes"]]
        self.assertIn(prop["proposal_id"], saved_ids)

        saved_quote = next(q for q in hist_data["quotes"] if q["id"] == prop["proposal_id"])
        self.assertEqual(saved_quote["origin_zip"], "TORONTO, ON")
        self.assertEqual(saved_quote["dest_zip"], "MONTREAL, QC")
        self.assertAlmostEqual(saved_quote["final_rate"], prop["pricing"]["client_total"], places=2)
        self.assertIn("Proposal •", saved_quote["coordinate"])

        # 8. Verify persistent across login: logout and log back in
        self.client.get("/api/auth/logout")
        login_res = self.client.post("/api/auth/login", data={"email": "alex.rivers@techcorp.io", "password": "RateSiftDemo2026!"})
        self.assertEqual(login_res.status_code, 200)

        # Quotes history still contains the saved proposal quote after login
        hist_after_login = self.client.get("/api/quotes/history").json()
        saved_after_login_ids = [q["id"] for q in hist_after_login["quotes"]]
        self.assertIn(prop["proposal_id"], saved_after_login_ids)

        # 9. Verify /console/history page renders capped 10 per page pagination and all-header sorting
        page_res = self.client.get("/console/history")
        self.assertEqual(page_res.status_code, 200)
        page_html = page_res.text
        self.assertIn("btn-prev-page", page_html)
        self.assertIn("btn-next-page", page_html)
        self.assertIn("page-indicator", page_html)
        self.assertIn("pageSize = 10", page_html)
        self.assertIn("sort-icon-id", page_html)
        self.assertIn("sort-icon-carrier", page_html)
        self.assertIn("sort-icon-route", page_html)
        self.assertIn("sort-icon-sheet", page_html)
        self.assertIn("sort-icon-date", page_html)
        self.assertIn("sort-icon-rate", page_html)
        self.assertIn("sort-icon-proposal", page_html)

if __name__ == "__main__":
    unittest.main()
