import unittest
import re
import uuid
from fastapi.testclient import TestClient
from main import app
from services.quotelytics_db_service import list_rate_sheets
from services.auth_service import register_and_create_session
from services.db_service import save_proposal_quote_item
from services.import_day_and_ross_guide import import_day_and_ross_tariff

class TestExcelReferenceAndSheetHighlighting(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        user, token = register_and_create_session(
            name="Jordan Freight",
            email=f"excel.ref.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
            company="Acme Logistics",
            origin_zip="TORONTO, ON",
            password="ExcelRefPassword2026!"
        )
        self.user_id = user["id"]
        self.client.cookies.set("quotelytics_session", token)
        import_day_and_ross_tariff(user_id=self.user_id, auto_confirm=True)
        sheets = list_rate_sheets(self.user_id)
        sample_sheet_id = sheets[0]["id"] if sheets else "ql_sheet_sample"
        save_proposal_quote_item(
            user_id=self.user_id,
            proposal={
                "proposal_id": f"PROP-{uuid.uuid4().hex[:6].upper()}",
                "carrier": {"name": "Day & Ross", "service": "Standard LTL"},
                "shipment": {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "weight_lbs": 500.0},
                "pricing": {"carrier_net_cost": 120.0, "effective_markup_pct": 10.0, "client_total": 132.0},
            },
            quote_data={
                "sheet_id": sample_sheet_id,
                "source_coordinate": "Sheet 1 • Row 14, Col C",
            }
        )

    def test_coordinate_parsing_format(self):
        """Validates that coordinate patterns convert strictly to [Column Letter:Row number]."""
        def format_excel_ref(coord, row_num=None):
            if not coord and not row_num:
                return "[C:1]"
            s = str(coord or "").strip()
            
            # 1. Already in [Col:Row]
            m1 = re.search(r"\[([A-Za-z]+)\s*[:,\s]\s*(\d+)\]", s)
            if m1:
                return f"[{m1.group(1).upper()}:{m1.group(2)}]"
                
            # 2. Row X, Col Y
            m2 = re.search(r"Row\s*(\d+)[^\w\d]+Col(?:umn)?\s*([A-Za-z]+)", s, re.IGNORECASE)
            if m2:
                return f"[{m2.group(2).upper()}:{m2.group(1)}]"
                
            m3 = re.search(r"Col(?:umn)?\s*([A-Za-z]+)[^\w\d]+Row\s*(\d+)", s, re.IGNORECASE)
            if m3:
                return f"[{m3.group(1).upper()}:{m3.group(2)}]"
                
            # 3. Cell coordinate like Rates!C2 or C14
            m4 = re.search(r"(?:!|^|\s)([A-Za-z]{1,3})(\d+)(?:\b|$)", s)
            if m4:
                return f"[{m4.group(1).upper()}:{m4.group(2)}]"
                
            # 4. Row X only
            m5 = re.search(r"Row\s*(\d+)", s, re.IGNORECASE)
            if m5:
                return f"[C:{m5.group(1)}]"
                
            if row_num:
                return f"[C:{row_num}]"
                
            return "[C:1]"

        test_cases = [
            ("Sheet 1 • Row 14, Col C", "[C:14]"),
            ("LTL_Pallets • Row 2, Col C", "[C:2]"),
            ("Day_Ross_CSV • Row 96, Col J", "[J:96]"),
            ("Rates!C2", "[C:2]"),
            ("Terms!C14", "[C:14]"),
            ("C14", "[C:14]"),
            ("[C:14]", "[C:14]"),
            ("[d:5]", "[D:5]"),
            ("Col H, Row 133", "[H:133]"),
            ("Proposal • PROP-20261004-9281A", "[C:1]"),
        ]

        for raw, expected in test_cases:
            self.assertEqual(format_excel_ref(raw), expected, f"Failed formatting {raw}")

    def test_api_quotes_history_includes_sheet_id_and_coordinate(self):
        """Verifies that /api/quotes/history returns sheet_id and coordinate for each quote."""
        res = self.client.get("/api/quotes/history")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("quotes", data)
        self.assertTrue(len(data["quotes"]) > 0)
        
        for q in data["quotes"]:
            self.assertIn("coordinate", q)
            self.assertIn("sheet_id", q)
            self.assertIsNotNone(q["sheet_id"])

    def test_api_formatted_matrix_cell_parameter(self):
        """Verifies that /api/quotelytics/sheets/{sheet_id}/formatted-matrix supports cell query param."""
        sheets = list_rate_sheets(self.user_id)
        self.assertTrue(len(sheets) > 0)
        sheet_id = sheets[0]["id"]
        
        res = self.client.get(f"/api/quotelytics/sheets/{sheet_id}/formatted-matrix?cell=C14")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("sheet", data)
        self.assertIn("breaks", data)
        self.assertIn("page", data)
        self.assertIn("total_breaks", data)

    def test_history_html_contains_clickable_reference_and_modal(self):
        """Verifies history.html contains Excel reference formatting, click handlers, and formatted sheet modal."""
        res = self.client.get("/console/history")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Header check
        self.assertIn("Excel Reference", html)
        
        # JS parsing and matching function check
        self.assertIn("function formatExcelReference", html)
        self.assertIn("function matchesHighlightCell", html)
        
        # Click handler check
        self.assertIn("openHistoryFormattedSheet", html)
        self.assertIn("openFormattedSheetModalForHistory", html)
        
        # Formatted matrix modal in history.html
        self.assertIn('id="formatted-sheet-modal"', html)
        self.assertIn('id="fsm-matrix-tbody"', html)
        self.assertIn('id="fsm-highlighted-row"', html)
        self.assertIn("Highlighted Cell", html)
        self.assertIn("fsm-highlight-banner", html)

    def test_rate_sheets_html_contains_cell_highlighting_and_url_opening(self):
        """Verifies rate_sheets.html contains cell highlighting and auto-opening via URL parameters."""
        res = self.client.get("/console/rate-sheets")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # JS functions
        self.assertIn("function formatExcelReference", html)
        self.assertIn("function matchesHighlightCell", html)
        self.assertIn("activeHighlightCell", html)
        
        # Highlighted row & badge
        self.assertIn('id="fsm-highlighted-row"', html)
        self.assertIn("Highlighted Cell", html)
        self.assertIn("fsm-highlight-banner", html)
        self.assertIn("fsm-focused-cell-badge", html)
        
        # URL parameters handling on DOMContentLoaded
        self.assertIn("urlParams.get('sheet_id')", html)
        self.assertIn("urlParams.get('cell')", html)
        self.assertIn("openFormattedSheetModal", html)

if __name__ == "__main__":
    unittest.main()
