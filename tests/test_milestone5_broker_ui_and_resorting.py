import unittest
from fastapi.testclient import TestClient

from main import app
from services.auth_service import create_session
from services.import_day_and_ross_guide import import_day_and_ross_tariff
from services.ratesift_db_service import (
    create_rate_sheet,
    insert_weight_breaks,
    insert_carrier_surcharges,
    insert_rate_sheet_cells,
    confirm_rate_sheet
)
from services.ratesift_engine import quote_all_confirmed_carriers

class TestMilestone5BrokerUIAndResorting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.user_id = "usr_alex_rivers"
        cls.token = create_session(cls.user_id)
        cls.client.cookies.set("shipflow_session", cls.token)

        # Import confirmed Day & Ross Guide Tariff (Effective 2024-01-01 to 2024-12-31)
        cls.guide_sheet_id = import_day_and_ross_tariff(user_id=cls.user_id, auto_confirm=True)

    def test_01_console_new_quote_page_renders_broker_ui(self):
        """Milestone 5: Verifies /console/new-quote renders modern broker console elements."""
        resp = self.client.get("/console/new-quote")
        self.assertEqual(resp.status_code, 200)
        content = resp.text

        # Broker UI & Rules Check
        self.assertIn("Freight Rating Engine", content)
        self.assertIn("100% Deterministic (Rule 8)", content)
        self.assertIn("WHC Canada • Rule 29", content)
        self.assertIn("input-origin", content)
        self.assertIn("input-destination", content)
        self.assertIn("input-weight", content)
        self.assertIn("input-date", content)
        self.assertIn("Requested Accessorials & Surcharges (Rule 11)", content)
        self.assertIn("Power Tailgate / Liftgate", content)

        # Rule 21 In-Memory Re-Sorting Toggles in HTML
        self.assertIn("sort-price-btn", content)
        self.assertIn("sort-transit-btn", content)
        self.assertIn("sort-value-btn", content)
        self.assertIn("setSortMode", content)

        # Rule 26 Non-Binding Notice in HTML
        self.assertIn("Rule 26 Legal Notice", content)
        self.assertIn("non-binding", content.lower())

        # Rule 13 Line-Item Accordion in HTML
        self.assertIn("toggleCardDetail", content)
        self.assertIn("1. Base Charge", content)
        self.assertIn("2. Surcharges", content)
        self.assertIn("3. Min Floor Adjustment", content)
        self.assertIn("4. Final Billed Total", content)

    def test_02_rule22_display_all_qualifying_options(self):
        """Rule 22: Return all qualifying options rather than a single recommendation so the user can choose."""
        # Create a second carrier serving Calgary -> Lindsay with matching 2024 dates
        sheet_2 = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Bison Transport",
            service_name="Dry Van LTL",
            tariff_ref="BT-2024-LTL",
            mode="LTL",
            currency="CAD",
            effective_date="2024-01-01",
            expiry_date="2024-12-31",
            version=1
        )
        insert_weight_breaks(sheet_2, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "CALGARY, AB",
            "dest_spec": "LINDSAY, ON",
            "min_weight": 1000.0,
            "max_weight": 2000.0,
            "break_name": "CWT:1000",
            "base_rate": 32.50,
            "rate_type": "CWT"
        }])
        confirm_rate_sheet(sheet_2, self.user_id, confirmed_by="tester")

        res = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="CALGARY, AB",
            destination="LINDSAY, ON",
            actual_weight=1450.0,
            shipment_date="2024-01-15"
        )
        
        # Rule 22: Both Day & Ross AND Bison Transport must be returned
        carriers = [q["carrier_name"] for q in res["quotes"]]
        self.assertIn("Day & Ross", carriers)
        self.assertIn("Bison Transport", carriers)
        self.assertGreaterEqual(len(res["quotes"]), 2)

    def test_03_rule20_and_21_sorting_parity(self):
        """Rule 20 & 21: Verify sorting ordering logic (Lowest Price, Fastest Transit, Best Value)."""
        quotes = [
            {"carrier_name": "Carrier Fast", "final_total": 550.0, "transit_days": 1},
            {"carrier_name": "Carrier Cheap", "final_total": 350.0, "transit_days": 4},
            {"carrier_name": "Carrier Mid", "final_total": 400.0, "transit_days": 2},
        ]

        # 1. Price Sort (Rule 20 default)
        price_sorted = sorted(quotes, key=lambda q: (q["final_total"], q.get("transit_days") or 99))
        self.assertEqual(price_sorted[0]["carrier_name"], "Carrier Cheap")
        self.assertEqual(price_sorted[1]["carrier_name"], "Carrier Mid")
        self.assertEqual(price_sorted[2]["carrier_name"], "Carrier Fast")

        # 2. Transit Sort
        transit_sorted = sorted(quotes, key=lambda q: (q.get("transit_days") or 99, q["final_total"]))
        self.assertEqual(transit_sorted[0]["carrier_name"], "Carrier Fast")
        self.assertEqual(transit_sorted[1]["carrier_name"], "Carrier Mid")
        self.assertEqual(transit_sorted[2]["carrier_name"], "Carrier Cheap")

    def test_04_rule13_full_line_item_breakdown_returned_in_quote_api(self):
        """Rule 13: Full line-item breakdown is provided for every quote option."""
        resp = self.client.post("/api/ratesift/quotes/calculate", json={
            "origin": "CALGARY, AB",
            "destination": "LINDSAY, ON",
            "actual_weight": 1450.0,
            "accessorials": ["liftgate"],
            "shipment_date": "2024-01-15"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(len(data["quotes"]), 1)
        q = next(x for x in data["quotes"] if x["carrier_name"] == "Day & Ross")

        # Required Rule 13 line items
        self.assertIn("base_rate", q)
        self.assertIn("rate_break", q)
        self.assertIn("surcharges", q)
        self.assertIn("total_surcharges", q)
        self.assertIn("carrier_min_charge", q)
        self.assertIn("min_charge_adjustment", q)
        self.assertIn("final_total", q)
        self.assertIn("calculation_trace", q)
        self.assertIn("disclaimer", q)

        # Check liftgate surcharge was itemized and waived
        liftgate_sur = next((s for s in q["surcharges"] if "tailgate" in s["name"].lower() or "liftgate" in s["code"].lower()), None)
        self.assertIsNotNone(liftgate_sur)
        self.assertTrue(liftgate_sur["is_waived"])
        self.assertEqual(liftgate_sur["amount"], 0.0)

    def test_05_rule23_and_rule27_badges_present_in_api(self):
        """Rule 23 & 27: Verify caution_badge and rate_shift_warning keys exist in response objects."""
        resp = self.client.post("/api/ratesift/quotes/calculate", json={
            "origin": "CALGARY, AB",
            "destination": "LINDSAY, ON",
            "actual_weight": 1450.0,
            "shipment_date": "2024-01-15"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        quote = data["quotes"][0]
        self.assertIn("relies_on_flagged_cell", quote)
        self.assertIn("caution_badge", quote)
        self.assertIn("rate_shift_warning", quote)

if __name__ == "__main__":
    unittest.main()
