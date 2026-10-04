import unittest
import os
import io
import json
from fastapi.testclient import TestClient

from main import app
from services.ratesift_extractor import RateSiftExtractor
from services.ratesift_db_service import (
    get_rate_sheet,
    get_sheet_full_rules,
    get_rate_sheet_cells,
    confirm_rate_sheet,
    list_rate_sheets
)

class TestMilestone2ExtractorAndConfirmationGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from services.auth_service import create_session
        from services.db_service import update_user_tier
        cls.client = TestClient(app)
        cls.user_id = "usr_alex_rivers"
        update_user_tier(cls.user_id, "TEAM")
        cls.token = create_session(cls.user_id)
        cls.client.cookies.set("shipflow_session", cls.token)
        cls.guide_csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample_sheets", "day_and_ross_guide_tariff.csv")

    def test_01_extractor_rules_on_day_and_ross_sheet(self):
        """Rules 1, 4, 5, 6, 7: Deep extraction and confirmation gating on Guide Template #1."""
        self.assertTrue(os.path.exists(self.guide_csv_path))
        with open(self.guide_csv_path, "rb") as f:
            file_bytes = f.read()

        extractor = RateSiftExtractor(
            file_bytes=file_bytes,
            filename="day_and_ross_guide_tariff.csv",
            user_id=self.user_id
        )
        result = extractor.process()

        sheet_id = result["sheet_id"]
        self.assertTrue(sheet_id.startswith("rs_sheet_"))
        
        # Rule 7 & 19: Starts in PENDING_REVIEW status
        self.assertEqual(result["confirmation_status"], "PENDING_REVIEW")

        # Rule 5: Units & Currency detection
        metadata = result["metadata"]
        self.assertEqual(metadata["carrier_name"], "Day & Ross")
        self.assertEqual(metadata["currency"], "CAD")
        self.assertEqual(metadata["weight_unit"], "lb")
        self.assertEqual(metadata["effective_date"], "2023-11-15")
        self.assertEqual(metadata["expiry_date"], "2024-04-30")

        # Rule 4 & 11: Textual Footnote and Accessorial Extraction
        self.assertGreaterEqual(result["surcharges_count"], 15)
        
        # Rule 6: Items flagged for review
        self.assertGreater(result["flagged_items_count"], 0)
        flagged_fields = [f["field_name"] for f in result["flagged_items"]]
        self.assertTrue(any("after_hours" in f or "currency" in f or "hidden" in f for f in flagged_fields))

        # Check DB State
        sheet_db = get_rate_sheet(sheet_id, user_id=self.user_id)
        self.assertEqual(sheet_db["confirmation_status"], "PENDING_REVIEW")

        # Check cells traceability (Rule 3)
        cells = get_rate_sheet_cells(sheet_id, user_id=self.user_id)
        self.assertGreater(len(cells), 10)
        self.assertTrue(all(c["cell_coord"] != "" for c in cells))

    def test_02_human_confirmation_gate_api(self):
        """Rule 7 & 19: Human confirmation workflow via API."""
        # 1. Upload new sheet via API
        with open(self.guide_csv_path, "rb") as f:
            response = self.client.post(
                "/api/ratesift/sheets/upload",
                files={"file": ("day_and_ross_guide_tariff.csv", f, "text/csv")}
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        sheet_id = data["sheet_id"]
        self.assertEqual(data["confirmation_status"], "PENDING_REVIEW")

        # 2. Get Sheet Details via API
        detail_res = self.client.get(f"/api/ratesift/sheets/{sheet_id}")
        self.assertEqual(detail_res.status_code, 200)
        detail_data = detail_res.json()
        self.assertEqual(detail_data["sheet"]["id"], sheet_id)
        self.assertEqual(detail_data["sheet"]["confirmation_status"], "PENDING_REVIEW")
        self.assertGreater(len(detail_data["surcharges"]), 10)
        self.assertGreater(len(detail_data["breaks"]), 50)

        # 3. Confirm Sheet via API (Rule 7)
        confirm_res = self.client.post(f"/api/ratesift/sheets/{sheet_id}/confirm")
        self.assertEqual(confirm_res.status_code, 200)
        self.assertEqual(confirm_res.json()["status"], "success")

        # 4. Verify status updated to CONFIRMED
        after_res = self.client.get(f"/api/ratesift/sheets/{sheet_id}")
        self.assertEqual(after_res.json()["sheet"]["confirmation_status"], "CONFIRMED")
        self.assertIsNotNone(after_res.json()["sheet"]["confirmed_at"])

    def test_03_cell_traceability_api(self):
        """Rule 3: Cell coordinates queryable via API."""
        sheets = list_rate_sheets(user_id=self.user_id)
        self.assertGreater(len(sheets), 0)
        sheet_id = sheets[0]["id"]

        cell_res = self.client.get(f"/api/ratesift/sheets/{sheet_id}/cells")
        self.assertEqual(cell_res.status_code, 200)
        cell_data = cell_res.json()
        self.assertIn("cells", cell_data)
        self.assertGreater(len(cell_data["cells"]), 0)
        
        # Verify coordinate structure (e.g. contains Sheet/Tab & Row)
        first_cell = cell_data["cells"][0]
        self.assertIn("cell_coord", first_cell)
        self.assertIn("field_name", first_cell)

    def test_04_rule1_no_made_up_or_inferred_rates(self):
        """Rule 1: Only extract values explicitly present. No inferred rates."""
        # Create CSV with missing cell in matrix
        mock_csv = (
            "Origin,Destination,MIN,LTL,CWT:1000\n"
            "CALGARY, AB,TORONTO, ON,96.89,34.51,27.73\n"
            "EDMONTON, AB,MONTREAL, QC,96.89,,25.26\n"  # missing LTL rate!
        )
        extractor = RateSiftExtractor(
            file_bytes=mock_csv.encode("utf-8"),
            filename="mock_missing_rate.csv",
            user_id=self.user_id
        )
        result = extractor.process()
        sheet_id = result["sheet_id"]

        full_rules = get_sheet_full_rules(sheet_id, user_id=self.user_id)
        edmonton_breaks = [b for b in full_rules["breaks"] if b["origin_spec"] == "EDMONTON, AB"]
        
        # Verify that for EDMONTON, AB missing LTL rate was NOT filled with a guess/default
        # Only CWT:1000 should exist, NO made-up LTL break!
        break_names = [b["break_name"] for b in edmonton_breaks]
        self.assertNotIn("LTL", break_names, "Rule 1 Violation: Missing rate was filled in or inferred!")

    def test_05_console_rate_sheets_page_accessible(self):
        """Verifies GET /console/rate-sheets serves HTML console template when authenticated."""
        res = self.client.get("/console/rate-sheets")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Carrier Rate Sheets", res.text)
        self.assertIn("Human Confirmation Gate", res.text)



if __name__ == "__main__":
    unittest.main()
