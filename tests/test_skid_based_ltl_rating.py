import unittest
import os
import io
import openpyxl
from datetime import datetime

from services.ratesift_extractor import RateSiftExtractor
from services.ratesift_engine import calculate_quote_for_sheet, quote_all_confirmed_carriers
from services.ratesift_db_service import (
    init_ratesift_db,
    confirm_rate_sheet,
    delete_rate_sheet,
    get_sheet_full_rules,
    get_rate_sheet
)
from services.ratesift_excel_reformatter import analyze_excel_sheet

class TestSkidBasedLTLRating(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_ratesift_db()
        cls.user_id = f"usr_test_skid_{int(datetime.utcnow().timestamp())}"
        cls.created_sheet_ids = []

    @classmethod
    def tearDownClass(cls):
        for sid in cls.created_sheet_ids:
            try:
                delete_rate_sheet(sid, cls.user_id)
            except Exception:
                pass

    def create_mock_skid_excel(self, base_cost_header="MC", skid_headers=None) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Rates"

        # Row 1-3: Blank / Metadata
        ws.append([])
        ws.append([])
        ws.append([])

        # Row 4: Header
        headers = ["DIRECTION", "ORIGIN", "OPR", "DESTINATION", "DCOUNTY", "DPR", base_cost_header]
        if skid_headers is None:
            skid_headers = ["L5C", "5C", "1M", "2M", "5M", "10M"]
        headers.extend(skid_headers)
        ws.append(headers)

        # Row 5: Agincourt Lane
        # MC: 71.98, L5C: 15.23, 5C: 13.24, 1M: 7.92, 2M: 5.63, 5M: 3.46, 10M: 2.25
        ws.append(["BETWEEN", "TORONTO", "ON", "AGINCOURT", None, "ON", 71.98, 15.23, 13.24, 7.92, 5.63, 3.46, 2.25])
        # Row 6: Barrie Lane
        ws.append(["BETWEEN", "TORONTO", "ON", "BARRIE", None, "ON", 73.58, 22.61, 16.89, 10.68, 8.46, 6.17, 3.99])

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_skid_sheet_extraction_and_classification(self):
        """Phase 2: Verifies extractor identifies PER_SKID basis, 10M max capacity, and bidirectional rates."""
        file_bytes = self.create_mock_skid_excel()
        extractor = RateSiftExtractor(file_bytes, "test_tariff.xlsx", self.user_id)
        result = extractor.process()
        sheet_id = result["sheet_id"]
        self.created_sheet_ids.append(sheet_id)

        meta = result["metadata"]
        self.assertEqual(meta["rating_basis"], "PER_SKID")
        self.assertEqual(meta["max_skid_capacity"], 10)

        sheet = get_rate_sheet(sheet_id, self.user_id)
        self.assertEqual(sheet["rating_basis"], "PER_SKID")
        self.assertEqual(sheet["max_skid_capacity"], 10)

        rules = get_sheet_full_rules(sheet_id, self.user_id)
        # Should have breaks for both directions (TORONTO -> AGINCOURT and AGINCOURT -> TORONTO)
        fwd_breaks = [b for b in rules["breaks"] if "TORONTO" in b["origin_spec"] and "AGINCOURT" in b["dest_spec"]]
        rev_breaks = [b for b in rules["breaks"] if "AGINCOURT" in b["origin_spec"] and "TORONTO" in b["dest_spec"]]
        self.assertEqual(len(fwd_breaks), 6)
        self.assertEqual(len(rev_breaks), 6)

        # Check break brackets
        l5c = next(b for b in fwd_breaks if b["break_name"] == "L5C")
        self.assertEqual(l5c["min_units"], 1.0)
        self.assertEqual(l5c["max_units"], 4.0)
        self.assertEqual(l5c["base_rate"], 15.23)

        ten_m = next(b for b in fwd_breaks if b["break_name"] == "10M")
        self.assertEqual(ten_m["min_units"], 10.0)
        self.assertEqual(ten_m["max_units"], 10.0)
        self.assertEqual(ten_m["base_rate"], 2.25)

    def test_synonym_headers_recognition(self):
        """Phase 2: Verifies extractor recognizes MIN/BASE and '1-4 Skids' / '5 Skids' synonyms."""
        synonym_skid_headers = ["1-4 Skids", "5 Skids", "6 Skids", "7 Skids", "8-9 Skids", "10 Skids"]
        file_bytes = self.create_mock_skid_excel(base_cost_header="MIN", skid_headers=synonym_skid_headers)
        extractor = RateSiftExtractor(file_bytes, "synonym_tariff.xlsx", self.user_id)
        result = extractor.process()
        sheet_id = result["sheet_id"]
        self.created_sheet_ids.append(sheet_id)

        meta = result["metadata"]
        self.assertEqual(meta["rating_basis"], "PER_SKID")
        self.assertEqual(meta["max_skid_capacity"], 10)

        rules = get_sheet_full_rules(sheet_id, self.user_id)
        self.assertTrue(len(rules["breaks"]) > 0)

    def test_skid_quote_additive_mc_formula(self):
        """Phase 3: Verifies exact formula Base Freight = MC + (S x RateBreak)."""
        file_bytes = self.create_mock_skid_excel()
        extractor = RateSiftExtractor(file_bytes, "test_tariff.xlsx", self.user_id)
        result = extractor.process()
        sheet_id = result["sheet_id"]
        self.created_sheet_ids.append(sheet_id)

        confirm_rate_sheet(
            sheet_id=sheet_id,
            user_id=self.user_id,
            confirmed_by="Test Tester",
            currency="CAD",
            weight_unit="lb"
        )

        # 2 skids from Toronto to Agincourt:
        # MC = $71.98, L5C = $15.23
        # Expected = 71.98 + (2 * 15.23) = 102.44
        quote = calculate_quote_for_sheet(
            sheet_id=sheet_id,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="AGINCOURT, ON",
            actual_weight=1000.0,
            skid_count=2
        )

        self.assertEqual(quote["rating_basis"], "PER_SKID")
        self.assertEqual(quote["skid_count"], 2)
        self.assertEqual(quote["mc_base_cost"], 71.98)
        self.assertEqual(quote["skid_charge"], 30.46)
        self.assertEqual(quote["base_rate"], 102.44)
        self.assertEqual(quote["final_total"], 102.44)

        # Bidirectional test: Agincourt to Toronto should also equal 102.44
        rev_quote = calculate_quote_for_sheet(
            sheet_id=sheet_id,
            user_id=self.user_id,
            origin="AGINCOURT, ON",
            destination="TORONTO, ON",
            actual_weight=1000.0,
            skid_count=2
        )
        self.assertEqual(rev_quote["base_rate"], 102.44)

    def test_multi_tier_skid_break_calculations(self):
        """Phase 3: Verifies each break tier calculates accurately."""
        file_bytes = self.create_mock_skid_excel()
        extractor = RateSiftExtractor(file_bytes, "test_tariff.xlsx", self.user_id)
        result = extractor.process()
        sheet_id = result["sheet_id"]
        self.created_sheet_ids.append(sheet_id)

        confirm_rate_sheet(
            sheet_id=sheet_id,
            user_id=self.user_id,
            confirmed_by="Test Tester",
            currency="CAD",
            weight_unit="lb"
        )

        # Tier breakdown for Agincourt (MC = 71.98):
        # 1 skid (L5C: 15.23) -> 71.98 + 15.23 = 87.21
        q1 = calculate_quote_for_sheet(sheet_id=sheet_id, user_id=self.user_id, origin="TORONTO, ON", destination="AGINCOURT, ON", actual_weight=500, skid_count=1)
        self.assertEqual(q1["base_rate"], 87.21)

        # 5 skids (5C: 13.24) -> 71.98 + (5 * 13.24) = 138.18
        q5 = calculate_quote_for_sheet(sheet_id=sheet_id, user_id=self.user_id, origin="TORONTO, ON", destination="AGINCOURT, ON", actual_weight=2500, skid_count=5)
        self.assertEqual(q5["base_rate"], 138.18)

        # 6 skids (1M: 7.92) -> 71.98 + (6 * 7.92) = 119.50
        q6 = calculate_quote_for_sheet(sheet_id=sheet_id, user_id=self.user_id, origin="TORONTO, ON", destination="AGINCOURT, ON", actual_weight=3000, skid_count=6)
        self.assertEqual(q6["base_rate"], 119.50)

        # 7 skids (2M: 5.63) -> 71.98 + (7 * 5.63) = 111.39
        q7 = calculate_quote_for_sheet(sheet_id=sheet_id, user_id=self.user_id, origin="TORONTO, ON", destination="AGINCOURT, ON", actual_weight=3500, skid_count=7)
        self.assertEqual(q7["base_rate"], 111.39)

        # 8 skids (5M: 3.46) -> 71.98 + (8 * 3.46) = 99.66
        q8 = calculate_quote_for_sheet(sheet_id=sheet_id, user_id=self.user_id, origin="TORONTO, ON", destination="AGINCOURT, ON", actual_weight=4000, skid_count=8)
        self.assertEqual(q8["base_rate"], 99.66)

        # 10 skids (10M: 2.25) -> 71.98 + (10 * 2.25) = 94.48
        q10 = calculate_quote_for_sheet(sheet_id=sheet_id, user_id=self.user_id, origin="TORONTO, ON", destination="AGINCOURT, ON", actual_weight=5000, skid_count=10)
        self.assertEqual(q10["base_rate"], 94.48)

    def test_rule_18_skid_capacity_limit_enforcement(self):
        """Phase 3: Verifies Rule 18 rejects shipments exceeding max_skid_capacity."""
        file_bytes = self.create_mock_skid_excel()
        extractor = RateSiftExtractor(file_bytes, "test_tariff.xlsx", self.user_id)
        result = extractor.process()
        sheet_id = result["sheet_id"]
        self.created_sheet_ids.append(sheet_id)

        confirm_rate_sheet(
            sheet_id=sheet_id,
            user_id=self.user_id,
            confirmed_by="Test Tester",
            currency="CAD",
            weight_unit="lb"
        )

        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(
                sheet_id=sheet_id,
                user_id=self.user_id,
                origin="TORONTO, ON",
                destination="AGINCOURT, ON",
                actual_weight=6000,
                skid_count=11
            )
        self.assertIn("Rule 18 Exclusion", str(ctx.exception))
        self.assertIn("exceeds maximum carrier LTL capacity of 10 skids", str(ctx.exception))

    def test_reformatter_detects_skids_column(self):
        """Phase 4: Verifies the drop box reformatter identifies Skid / Pallet columns."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Shipments"
        ws.append(["Ship Date", "Origin City", "Dest City", "Skid Count", "Weight"])
        ws.append(["2026-10-15", "Toronto", "Montreal", 3, 1200])

        buf = io.BytesIO()
        wb.save(buf)
        analysis = analyze_excel_sheet(buf.getvalue(), "shipments.xlsx")

        self.assertIn("skid_count", analysis["column_mapping"])
        self.assertEqual(analysis["column_mapping"]["skid_count"]["detected_header"], "Skid Count")
        self.assertEqual(analysis["preview_rows"][0]["skid_count"], 3)

    def test_live_user_uploaded_media_spreadsheet(self):
        """Tests parsing and quoting against the actual user uploaded rate sheet file."""
        uploaded_path = r"C:\Users\Dylan\.gemini\antigravity\brain\1791d861-b6ec-4261-b573-0598e4a8a562\.user_uploaded\media_1791401358135.xlsx"
        if not os.path.exists(uploaded_path):
            self.skipTest("User uploaded file not available on local path")
        with open(uploaded_path, "rb") as f:
            file_bytes = f.read()

        extractor = RateSiftExtractor(file_bytes, "media_1791401358135.xlsx", self.user_id)
        result = extractor.process()
        sheet_id = result["sheet_id"]
        self.created_sheet_ids.append(sheet_id)

        self.assertEqual(result["metadata"]["rating_basis"], "PER_SKID")
        self.assertEqual(result["metadata"]["max_skid_capacity"], 10)

        confirm_rate_sheet(
            sheet_id=sheet_id,
            user_id=self.user_id,
            confirmed_by="Test Tester",
            currency="CAD",
            weight_unit="lb"
        )

        # Quote 2 skids from Toronto to Agincourt:
        # MC = $71.98, L5C = $15.23 -> Base Freight = $71.98 + (2 * $15.23) = $102.44
        quote = calculate_quote_for_sheet(
            sheet_id=sheet_id,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="AGINCOURT, ON",
            actual_weight=1000.0,
            skid_count=2
        )
        self.assertEqual(quote["base_rate"], 102.44)
        self.assertEqual(quote["final_total"], 102.44)

if __name__ == "__main__":
    unittest.main()
