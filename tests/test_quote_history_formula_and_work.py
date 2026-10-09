import unittest
import io
import openpyxl
from fastapi.testclient import TestClient
from main import app
from services.auth_service import create_session
from services.db_service import update_user_tier
from services.ratesift_extractor import RateSiftExtractor
from services.ratesift_db_service import init_ratesift_db, confirm_rate_sheet, delete_rate_sheet
from services.ratesift_engine import calculate_quote_for_sheet

class TestQuoteHistoryFormulaAndWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_ratesift_db()
        cls.client = TestClient(app)
        cls.user_id = "usr_alex_rivers"
        update_user_tier(cls.user_id, "TEAM")
        cls.token = create_session(cls.user_id)
        cls.client.cookies.set("shipflow_session", cls.token)

        # Create mock skid rate sheet
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Rates"
        ws.append([])
        ws.append([])
        ws.append([])
        ws.append(["DIRECTION", "ORIGIN", "OPR", "DESTINATION", "DCOUNTY", "DPR", "MC", "L5C", "5C", "1M", "2M", "5M", "10M"])
        # Row 5: MC=71.98, L5C=15.23, 5C=13.24, 1M=7.92, 2M=5.63, 5M=3.46, 10M=2.25
        ws.append(["BETWEEN", "TORONTO", "ON", "AGINCOURT", None, "ON", 71.98, 15.23, 13.24, 7.92, 5.63, 3.46, 2.25])
        buf = io.BytesIO()
        wb.save(buf)

        extractor = RateSiftExtractor(buf.getvalue(), "tariff_formula_test.xlsx", cls.user_id)
        res = extractor.process()
        cls.sheet_id = res["sheet_id"]
        confirm_rate_sheet(
            sheet_id=cls.sheet_id,
            user_id=cls.user_id,
            confirmed_by="Test Tester",
            currency="CAD",
            weight_unit="lb"
        )

    @classmethod
    def tearDownClass(cls):
        try:
            delete_rate_sheet(cls.sheet_id, cls.user_id)
        except Exception:
            pass

    def test_01_skid_tiers_deterministic_breaks(self):
        """Verifies 1 skid uses L5C, 6 skids uses 1M, and 7 skids uses 2M."""
        # 1 skid -> L5C (15.23)
        q1 = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="AGINCOURT, ON",
            actual_weight=500.0,
            skid_count=1
        )
        self.assertEqual(q1["rate_break"], "L5C")
        self.assertEqual(q1["base_rate"], 87.21)  # 71.98 + (1 * 15.23)
        self.assertIn("L5C", q1["formula"])
        self.assertIn("71.98", q1["formula"])

        # 6 skids -> 1M (7.92) - 1 on top of 5-skid cap
        q6 = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="AGINCOURT, ON",
            actual_weight=3000.0,
            skid_count=6
        )
        self.assertEqual(q6["rate_break"], "1M")
        self.assertEqual(q6["base_rate"], 119.50)  # 71.98 + (6 * 7.92)
        self.assertIn("1M", q6["formula"])

        # 7 skids -> 2M (5.63) - 2 on top of 5-skid cap
        q7 = calculate_quote_for_sheet(
            sheet_id=self.sheet_id,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="AGINCOURT, ON",
            actual_weight=3500.0,
            skid_count=7
        )
        self.assertEqual(q7["rate_break"], "2M")
        self.assertEqual(q7["base_rate"], 111.39)  # 71.98 + (7 * 5.63)
        self.assertIn("2M", q7["formula"])

    def test_02_quote_history_stores_and_returns_formula_and_work(self):
        """Creates proposal for 1-skid LTL quote and verifies formula & work in history."""
        # Calculate quote
        calc_payload = {
            "origin": "TORONTO, ON",
            "destination": "AGINCOURT, ON",
            "skid_count": 1,
            "shipping_mode": "LTL"
        }
        res_calc = self.client.post("/api/ratesift/quotes/calculate", json=calc_payload)
        self.assertEqual(res_calc.status_code, 200)
        quotes = res_calc.json()["quotes"]
        self.assertGreater(len(quotes), 0)
        target_quote = next(q for q in quotes if q["sheet_id"] == self.sheet_id)
        self.assertEqual(target_quote["rate_break"], "L5C")
        self.assertEqual(target_quote["skid_count"], 1)

        # Generate Proposal
        prop_payload = {
            "quote_id": target_quote["sheet_id"],
            "carrier_name": target_quote["carrier_name"],
            "service_name": target_quote["service_name"],
            "origin": target_quote["origin"],
            "destination": target_quote["destination"],
            "weight_lbs": target_quote["actual_weight"],
            "base_rate": target_quote["base_rate"],
            "total_surcharges": target_quote.get("total_surcharges", 0.0),
            "surcharges": target_quote.get("surcharges", []),
            "currency": "CAD",
            "client_name": "Formula Verification Client",
            "markup_pct": 15.0,
            "formula": target_quote["formula"],
            "skid_count": target_quote["skid_count"],
            "calculation_trace": target_quote["calculation_trace"],
            "source_coordinate": target_quote["source_coordinate"],
            "sheet_id": target_quote["sheet_id"]
        }
        prop_res = self.client.post("/api/quotes/client-proposal/preview", json=prop_payload)
        self.assertEqual(prop_res.status_code, 200)
        prop_id = prop_res.json()["proposal"]["proposal_id"]

        # Verify in /api/quotes/history
        hist_res = self.client.get("/api/quotes/history")
        self.assertEqual(hist_res.status_code, 200)
        hist_quotes = hist_res.json()["quotes"]
        saved = next((q for q in hist_quotes if q["id"] == prop_id), None)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["skid_count"], 1)
        self.assertIn("L5C", saved["formula"])
        self.assertIn("Base Freight", saved["formula"])
        self.assertTrue(len(saved["calculation_work"]) > 0)

    def test_03_history_page_ui_contains_formula_elements(self):
        """Verifies /console/history HTML includes the work toggle and drawer structure."""
        resp = self.client.get("/console/history")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        # Header, logo, and footer remain intact
        self.assertIn("/static/images/ratesift-logo.png", html)
        self.assertIn("New Quote", html)
        self.assertIn("Quotes History", html)
        self.assertIn("RateSift Quoting Engine • Canadian Residency (WHC)", html)

        # Formula & Work elements
        self.assertIn("toggleQuoteWorkDrawer", html)
        self.assertIn("renderWorkStepsHtml", html)
        self.assertIn("work-drawer-", html)

if __name__ == "__main__":
    unittest.main()
