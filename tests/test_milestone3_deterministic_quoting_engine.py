import unittest
import os
import json
from fastapi.testclient import TestClient

from main import app
from services.auth_service import create_session
from services.import_day_and_ross_guide import import_day_and_ross_tariff
from services.ratesift_engine import (
    calculate_billable_weight,
    calculate_quote_for_sheet,
    quote_all_confirmed_carriers
)
from services.ratesift_db_service import (
    create_rate_sheet,
    get_rate_sheet,
    get_quote_audit_log,
    confirm_rate_sheet
)

class TestMilestone3DeterministicQuotingEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.user_id = "usr_alex_rivers"
        cls.token = create_session(cls.user_id)
        cls.client.cookies.set("shipflow_session", cls.token)

        # Import confirmed Day & Ross Guide Tariff
        cls.sheet_id = import_day_and_ross_tariff(user_id=cls.user_id, auto_confirm=True)

    def test_01_rule8_deterministic_calculation_and_cwt(self):
        """Rule 8: Deterministic pricing with verified code and confirmed data."""
        # Lane: CALGARY, AB -> LINDSAY, ON, 1450 lbs
        # CWT:1000 rate is 27.73
        # Expected base: (1450 / 100) * 27.73 = 402.085 -> 402.08 (or 402.09 half-up)
        quote = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="CALGARY, AB",
            destination="LINDSAY, ON",
            actual_weight=1450.0,
            accessorials=[],
            shipment_date="2024-01-15"
        )
        self.assertEqual(quote["carrier_name"], "Day & Ross")
        self.assertEqual(quote["rate_break"], "CWT:1000")
        self.assertEqual(quote["base_rate"], 402.08)
        self.assertEqual(quote["final_total"], 402.08)
        self.assertEqual(quote["currency"], "CAD")

    def test_02_rule9_dimensional_weight_and_divisor(self):
        """Rule 9: Bill on greater of actual weight and dimensional weight using carrier divisor."""
        # 100 lbs actual, but bulky 60x50x48 inches
        # Volume = 144,000 cu in. Divisor = 139
        # DIM weight = 144,000 / 139 = 1,035.97 lbs
        # Should bill on 1,035.97 lbs in CWT:1000 bracket!
        quote = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="CALGARY, AB",
            destination="LINDSAY, ON",
            actual_weight=100.0,
            length=60,
            width=50,
            height=48,
            accessorials=[],
            shipment_date="2024-01-15"
        )
        self.assertEqual(quote["actual_weight"], 100.0)
        self.assertEqual(quote["billable_weight"], 1035.97)
        self.assertTrue(quote["is_dim_billed"])
        self.assertEqual(quote["rate_break"], "CWT:1000")
        # (1035.97 / 100) * 27.73 = 287.27
        self.assertEqual(quote["base_rate"], 287.27)
        self.assertEqual(quote["final_total"], 287.27)

    def test_03_rule11_conditional_surcharges_and_waived_fees(self):
        """Rule 11: Apply surcharges only when conditions met, and list each separately."""
        # Appointment Delivery ($20.00) + Power Tailgate (Waived $0.00)
        quote = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="CALGARY, AB",
            destination="LINDSAY, ON",
            actual_weight=1450.0,
            accessorials=["appointment", "liftgate"],
            shipment_date="2024-01-15"
        )
        surcharges = {s["code"]: s for s in quote["surcharges"]}
        self.assertIn("APPOINTMENT", surcharges)
        self.assertEqual(surcharges["APPOINTMENT"]["amount"], 20.00)
        self.assertFalse(surcharges["APPOINTMENT"]["is_waived"])

        self.assertIn("POWER_TAILGATE", surcharges)
        self.assertEqual(surcharges["POWER_TAILGATE"]["amount"], 0.00)
        self.assertTrue(surcharges["POWER_TAILGATE"]["is_waived"])

        # Base 402.08 + Surcharges 20.00 = 422.08
        self.assertEqual(quote["total_surcharges"], 20.00)
        self.assertEqual(quote["final_total"], 422.08)

    def test_04_rule12_carrier_minimum_charge_comparison(self):
        """Rule 12: Compare calculated total to carrier minimum charge and use whichever is higher."""
        # Very light shipment: 50 lbs from CALGARY, AB to LINDSAY, ON
        # Base rate: 50 lbs @ LTL (34.51/cwt) = (50/100) * 34.51 = $17.26
        # Lane minimum is $96.89
        # Calculated total < minimum -> final total becomes $96.89!
        quote = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="CALGARY, AB",
            destination="LINDSAY, ON",
            actual_weight=50.0,
            accessorials=[],
            shipment_date="2024-01-15"
        )
        self.assertEqual(quote["base_rate"], 17.25)
        self.assertEqual(quote["carrier_min_charge"], 96.89)
        self.assertGreater(quote["min_charge_adjustment"], 0.0)
        self.assertEqual(quote["final_total"], 96.89)

    def test_05_rule13_full_transparency_never_bare_total(self):
        """Rule 13: Always show base rate, each surcharge and final total. Never a bare total."""
        quote = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="CALGARY, AB",
            destination="LINDSAY, ON",
            actual_weight=1450.0,
            accessorials=["appointment"],
            shipment_date="2024-01-15"
        )
        # Verify required breakdown fields are present and explicit
        self.assertIn("base_rate", quote)
        self.assertIn("surcharges", quote)
        self.assertIn("carrier_min_charge", quote)
        self.assertIn("final_total", quote)
        self.assertIn("calculation_trace", quote)
        self.assertGreater(len(quote["calculation_trace"]), 0)

    def test_06_rule14_deterministic_reproducibility(self):
        """Rule 14: Give the same inputs against the same data the same result every time."""
        results = []
        for _ in range(10):
            res = calculate_quote_for_sheet(
                sheet_id=self.sheet_id,
                user_id=self.user_id,
                origin="CALGARY, AB",
                destination="LINDSAY, ON",
                actual_weight=1450.0,
                accessorials=["appointment", "liftgate"],
                shipment_date="2024-01-15"
            )
            results.append(res["final_total"])

        # All 10 calculations must be identical to the penny
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(results[0], 422.08)

    def test_07_rule19_unconfirmed_sheet_gated(self):
        """Rule 19: Never quote a rate from a sheet that has not passed confirmation."""
        # Create unconfirmed sheet
        unconfirmed_id = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Unconfirmed Carrier",
            service_name="Draft Service",
            confirmation_status="PENDING_REVIEW"
        )
        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(
                sheet_id=unconfirmed_id,
                user_id=self.user_id,
                origin="CALGARY, AB",
                destination="LINDSAY, ON",
                actual_weight=500.0
            )
        self.assertIn("Rule 19 Violation", str(ctx.exception))

    def test_08_quoting_api_endpoint_integration(self):
        """Tests POST /api/ratesift/quotes/calculate and audit logging."""
        payload = {
            "origin": "CALGARY, AB",
            "destination": "LINDSAY, ON",
            "actual_weight": 1450.0,
            "length": 48.0,
            "width": 40.0,
            "height": 60.0,
            "accessorials": ["appointment", "liftgate"],
            "shipment_date": "2024-01-15"
        }
        res = self.client.post("/api/ratesift/quotes/calculate", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("quote_id", data)
        self.assertGreater(data["total_options"], 0)
        
        quote = data["quotes"][0]
        self.assertEqual(quote["carrier_name"], "Day & Ross")
        self.assertEqual(quote["final_total"], 422.08)
        self.assertEqual(quote["base_rate"], 402.08)
        self.assertEqual(len(quote["surcharges"]), 2)

        # Test audit log retrieval via API (Rule 30)
        audit_res = self.client.get(f"/api/ratesift/quotes/audit/{data['quote_id']}")
        self.assertEqual(audit_res.status_code, 200)
        audit_data = audit_res.json()
        self.assertEqual(audit_data["id"], data["quote_id"])
        self.assertEqual(audit_data["shipment_input"]["actual_weight"], 1450.0)

if __name__ == "__main__":
    unittest.main()
