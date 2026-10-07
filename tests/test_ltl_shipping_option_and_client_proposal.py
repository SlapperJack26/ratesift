import unittest
from fastapi.testclient import TestClient
from main import app
from services.auth_service import create_session
from services.db_service import update_user_tier

class TestLTLShippingOptionAndClientProposal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.user_id = "usr_alex_rivers"
        update_user_tier(cls.user_id, "TEAM")
        cls.token = create_session(cls.user_id)
        cls.client.cookies.set("shipflow_session", cls.token)

    def test_01_new_quote_page_structure(self):
        """Verifies original header, footer, LTL mode selector, and client proposal modal."""
        resp = self.client.get("/console/new-quote")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        # 1. Original Logo, Header & Navigation Intact
        self.assertIn("/static/images/ratesift-logo.png", html)
        self.assertIn("New Quote", html)
        self.assertIn("Quotes History", html)
        self.assertIn("Carrier Tariffs", html)
        self.assertIn("Settings", html)
        self.assertIn("Hosted in Canada (WHC)", html)
        self.assertIn("Free Starter", html)

        # 2. Original Footer Intact
        self.assertIn("RateSift Quoting Engine • Canadian Residency (WHC)", html)
        self.assertIn("openSupportModal", html)

        # 3. LTL Option & Dynamic 3-Card Inputs
        self.assertIn("service-tab-standard", html)
        self.assertIn("service-tab-ltl", html)
        self.assertIn("card-cargo-weight", html)
        self.assertIn("card-cargo-skids", html)
        self.assertIn("input-origin", html)
        self.assertIn("input-destination", html)
        self.assertIn("input-weight", html)
        self.assertIn("input-skids", html)
        self.assertIn("setShippingServiceMode", html)

        # 4. Client Proposal Option Preserved
        self.assertIn("Create Client Proposal", html)
        self.assertIn("proposal-modal", html)
        self.assertIn("openProposalModal", html)

    def test_02_calculate_quote_with_ltl_skid_count(self):
        """Calculates quote using LTL mode (skid_count) and generates client proposal."""
        calc_payload = {
            "origin": "CALGARY, AB",
            "destination": "LINDSAY, ON",
            "skid_count": 2,
            "shipping_mode": "LTL",
            "shipment_date": "2024-06-01",
            "accessorials": ["liftgate"]
        }
        res = self.client.post("/api/ratesift/quotes/calculate", json=calc_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("quotes", data)
        quotes = data["quotes"]
        self.assertGreater(len(quotes), 0)

        # Verify quote properties
        first_quote = quotes[0]
        self.assertGreater(first_quote["final_total"], 0)
        self.assertEqual(first_quote["origin"], "CALGARY, AB")
        self.assertEqual(first_quote["destination"], "LINDSAY, ON")

        # Create Client Proposal for this LTL quote
        prop_payload = {
            "quote_id": first_quote.get("proposal_id") or first_quote.get("sheet_id") or "test_quote_ltl",
            "carrier_name": first_quote["carrier_name"],
            "service_name": first_quote.get("service_name", "Standard Road LTL"),
            "origin": first_quote["origin"],
            "destination": first_quote["destination"],
            "weight_lbs": first_quote["actual_weight"],
            "base_rate": first_quote["base_rate"],
            "total_surcharges": first_quote.get("total_surcharges", 0.0),
            "surcharges": first_quote.get("surcharges", []),
            "transit_days": first_quote.get("transit_days", 3),
            "currency": first_quote.get("currency", "CAD"),
            "client_name": "Acme Logistics LTL Client",
            "markup_pct": 15.0,
            "source_coordinate": first_quote.get("source_coordinate") or "[C:14]",
            "sheet_id": first_quote.get("sheet_id")
        }
        prop_res = self.client.post("/api/quotes/client-proposal/preview", json=prop_payload)
        self.assertEqual(prop_res.status_code, 200)
        prop_data = prop_res.json()["proposal"]

        self.assertIn("PROP-", prop_data["proposal_id"])
        self.assertGreater(prop_data["pricing"]["client_total"], first_quote["final_total"])
        self.assertIn("Acme Logistics LTL Client", prop_data["client"]["name"])
        self.assertIn("email", prop_data)
        self.assertIn("subject", prop_data["email"])

        # Verify saved in Quotes History
        hist_res = self.client.get("/api/quotes/history")
        self.assertEqual(hist_res.status_code, 200)
        hist_ids = [q["id"] for q in hist_res.json()["quotes"]]
        self.assertIn(prop_data["proposal_id"], hist_ids)

if __name__ == "__main__":
    unittest.main()
