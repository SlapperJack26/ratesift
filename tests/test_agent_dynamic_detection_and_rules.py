import unittest
import io
import openpyxl
from fastapi.testclient import TestClient

from main import app
from services.auth_service import create_session
from agent.dynamic_sheet_detector import DynamicSheetDetector
from agent.rules_spec import RATESIFT_36_RULES
from services.ratesift_excel_reformatter import analyze_excel_sheet

class TestAgentDynamicDetectionAndRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.user_id = "usr_alex_rivers"
        cls.token = create_session(cls.user_id)
        cls.client.cookies.set("shipflow_session", cls.token)

    def _create_sample_excel(self, preamble_rows, headers, data_rows):
        """Helper to create an in-memory workbook with preamble metadata and tables."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Tariff"

        for r in preamble_rows:
            ws.append(r)
        if headers:
            ws.append(headers)
        for r in data_rows:
            ws.append(r)

        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)
        return stream.getvalue()

    def test_01_thirty_six_rules_api_and_status(self):
        """Rule 1-36: Verify complete 36 rules specification endpoint."""
        resp = self.client.get("/api/agent/rules")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["total_rules"], 36)
        self.assertIn("33", data["rules"])
        self.assertIn("34", data["rules"])
        self.assertIn("35", data["rules"])
        self.assertIn("36", data["rules"])

        status_resp = self.client.get("/api/agent/status")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertEqual(status_data["status"], "active")
        self.assertEqual(status_data["rules_count"], 36)

    def test_02_dynamic_detection_row_90_without_hardcoded_lines(self):
        """Autonomous Detection: Detects rate table at Row 90 dynamically with 0 rows deleted."""
        # 89 rows of company preamble & disclaimers
        preamble = [
            ["DAY & ROSS FREIGHT TARIFF", "ACCOUNT: 158437", "PHONE: 1-800-561-0013"],
            ["TERMS AND CONDITIONS", "Subject to change without notice. All rates in CAD."],
            ["PROTECTIVE HEATED SERVICE: 18.00% not less than $39.50 fee applies."],
            ["DELIVERY APPOINTMENT: Flat charge of $20.00."],
            ["POWER TAILGATE SERVICE: Waived on customer account."]
        ]
        for i in range(84):
            preamble.append([f"Company Policy Note {i+6}: Inquiries email pricing@dayross.com"])

        headers = ["Origin", "Province", "Destination", "Province", "MIN", "LTL", "CWT:1000", "CWT:2000", "CWT:5000", "CWT:10000"]
        data = [
            ["CALGARY", "AB", "LINDSAY", "ON", "96.89", "34.51", "28.32", "24.15", "19.80", "16.45"],
            ["TORONTO", "ON", "MONTREAL", "QC", "75.00", "22.50", "18.00", "15.20", "12.80", "10.50"],
            ["EDMONTON", "AB", "WINNIPEG", "MB", "88.00", "29.40", "25.10", "21.00", "17.50", "14.20"]
        ]

        excel_bytes = self._create_sample_excel(preamble, headers, data)
        analysis = analyze_excel_sheet(excel_bytes, "dayross_line90.xlsx")

        self.assertFalse(analysis.get("is_confused", False))
        self.assertEqual(analysis["header_row"], 90)
        self.assertEqual(analysis["total_rows"], 3)
        self.assertIn("preamble_info", analysis)
        self.assertGreaterEqual(analysis["preamble_info"]["company_info_count"], 1)

        # Zero-loss reconciliation audit passed
        reconciliation = analysis.get("reconciliation_audit", {})
        self.assertTrue(reconciliation.get("reconciliation_passed", False))
        self.assertEqual(reconciliation.get("unaccounted_rows", -1), 0)

        # Structured surcharges harvested from prose notes
        surcharges = analysis.get("structured_surcharges", [])
        self.assertGreaterEqual(len(surcharges), 2)
        surcharge_names = [s["name"] for s in surcharges]
        self.assertTrue(any("Protective" in n or "Percentage" in n for n in surcharge_names))
        self.assertTrue(any("Appointment" in n or "Tailgate" in n for n in surcharge_names))

    def test_03_confusion_gate_halts_and_resumes_with_confirmation(self):
        """Confusion Gate: Halts with rich candidate preview when competing candidates are within 10%."""
        preamble = [
            ["CUSTOMER PROFILE: GLOBAL LOGISTICS", "EXPIRY: 2026-12-31"],
            ["Zone 1", "Zone 2", "Est Days: 2", "Transit Reference Only"]
        ]
        # Two header candidates with similar structures
        table1_header = ["Origin Local", "Destination Local", "Base Cost", "Rate Level"]
        data1 = [
            ["CALGARY, AB", "LINDSAY, ON", "1450.00", "STANDARD"]
        ]
        excel_bytes = self._create_sample_excel(preamble, table1_header, data1)

        # Initial pass without user confirmation
        detector = DynamicSheetDetector(confidence_threshold=0.85)
        grid = [
            ["CUSTOMER PROFILE: GLOBAL LOGISTICS", "EXPIRY: 2026-12-31"],
            ["Origin Local", "Destination Local", "Est Cost", "Rate Level"],
            ["CALGARY, AB", "LINDSAY, ON", "1450.00", "STANDARD"],
            ["From Zone", "To Zone", "Base Cost", "Flat Fee"],
            ["TORONTO, ON", "MONTREAL, QC", "850.00", "FLAT"]
        ]
        det_result = detector.scan_and_parse_sheet(grid)
        self.assertEqual(det_result["status"], "CONFUSED_NEEDS_CLARIFICATION")
        self.assertIn("candidates", det_result)
        self.assertGreaterEqual(len(det_result["candidates"]), 2)

        # User confirms Row 2 (0-indexed 1)
        resumed = detector.scan_and_parse_sheet(grid, user_confirmed_header_row=1)
        self.assertTrue(resumed["success"])
        self.assertEqual(resumed["detected_header_row_1_based"], 2)
        self.assertEqual(resumed["reconciliation_audit"]["unaccounted_rows"], 0)

    def test_04_ghost_columns_paired_without_column_shift(self):
        """Issue C: Unnamed province columns are paired via 2-letter code dictionary."""
        grid = [
            ["Origin", "", "Destination", "", "MIN", "LTL", "CWT:1000"],
            ["CALGARY", "AB", "LINDSAY", "ON", "96.89", "34.51", "28.32"],
            ["EDMONTON", "AB", "WINNIPEG", "MB", "88.00", "29.40", "25.10"]
        ]
        detector = DynamicSheetDetector()
        res = detector.scan_and_parse_sheet(grid)
        self.assertTrue(res["success"])
        ghosts = res.get("ghost_columns_paired", [])
        self.assertEqual(len(ghosts), 2)
        self.assertEqual(ghosts[0]["paired_with"], "Origin")
        self.assertEqual(ghosts[1]["paired_with"], "Destination")

        # Verify compound lanes
        rows = res["rate_data_rows"]
        self.assertEqual(rows[0]["origin"], "CALGARY, AB")
        self.assertEqual(rows[0]["destination"], "LINDSAY, ON")

if __name__ == "__main__":
    unittest.main()
