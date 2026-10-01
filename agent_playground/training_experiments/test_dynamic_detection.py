"""
Automated Test Suite for Dynamic Sheet Detection, Confusion Gate & Zero-Data-Loss Invariant
Tests that the agent autonomously detects rate headers across different row positions
(row 12, row 90, row 140) without hardcoded line numbers, halts to ask the user when confused,
and never deletes or drops any rate data rows under the headers.

Usage:
    python agent_playground/training_experiments/test_dynamic_detection.py
"""
import sys
import os
import csv
import unittest

PLAYGROUND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLAYGROUND_DIR)

from agent.dynamic_sheet_detector import DynamicSheetDetector

DAY_AND_ROSS_CSV_SNIPPET = """Customer,NAFF,,,,,,,,,
Address,375 PENDANT DR,,,,,,,,,
,C O NORTH AMERICAN FREIGH,,,,,,,,,
,Mississauga ON,,,,,,,,,
,L5T2W9,,,,,,,,,
Telephone,,,,,,,,,,
Fax,,,,,,,,,,
,,,,,,,,,,
Tariff,O-33545   ,,,,,,,,,
Revision,336,,,,,,,,,
D & R Acct #,158437,,,,,,,,,
Effective Date,2023-11-15,,,,,,,,,
Expiry Date,2024-04-30,,,,,,,,,
Issue Date,,,,,,,,,,
Pricing Official,Frank Carvell,,,,,,,,,
,,,,,,,,,,
Commodity,,,,,,,,,,
,,,,,,,,,,
Terms And Conditions,,,,,,,,,,
1,Appointment Deliveries:,,,,,,,,,
,"When customer requests via the bill of lading a charge of $20.00 per shipment shall be assessed",,,,,,,,,
8,Power Tailgate:,,,,,,,,,
,waived,,,,,,,,,
14,Payment Terms:,,,,,,,,,
,Freight charges are to paid within 30 days from date of invoicing. Contras on account will not be accepted.,,,,,,,,,
24,Notes:,,,,,,,,,
,"The Customer recognizes the competitive value and proprietary nature of the rates and shall not disclose said Rates",,,,,,,,,
Service Level,General Road LTL ,,,,,,,,,
Origin,,Destination,,MIN,LTL,CWT:1000,CWT:2000,CWT:5000,CWT:10000,CWT:20000
CALGARY, AB,LINDSAY, ON,96.89,34.51,27.73,25.71,23.93,21.38,0
EDMONTON, AB,BARRIE, ON,96.89,34.11,27.32,25.26,23.47,20.91,0
EDMONTON, AB,LINDSAY, ON,96.89,34.51,27.73,25.71,23.88,21.34,0
GRANDE PRAIRIE, AB,CALGARY, AB,159.22,35.76,19.36,17.11,13.92,10.64,0
LLOYDMINSTER, AB,VICTORIA, BC,154.41,36.6,30.43,27.83,24.97,21.66,0
MEDICINE HAT, AB,BEAMSVILLE, ON,112.21,41.74,33.5,31.19,28.68,24.92,0
MEDICINE HAT, AB,MOUNT FOREST, ON,111.29,39.67,31.01,28.97,26.95,18.5,0
RED DEER, AB,BEAMSVILLE, ON,107.52,29.34,21.03,19.02,17.21,14.48,0
Between Localities,,,,MIN,LTL,CWT:1000,CWT:2000,CWT:5000,CWT:10000,CWT:20000
CALGARY, AB,CALGARY, AB,60.32,17.24,7.09,6.94,5.91,3.5,0
CALGARY, AB,COCHRANE, AB,60.32,17.48,7.31,7.2,6.16,3.74,0
CALGARY, AB,EDMONTON, AB,60.32,21.43,10.49,10.21,8.83,5.91,0
"""

def parse_csv_string(raw: str):
    import io
    reader = csv.reader(io.StringIO(raw.strip()))
    return [row for row in reader]

class TestDynamicSheetDetection(unittest.TestCase):
    def setUp(self):
        self.detector = DynamicSheetDetector(confidence_threshold=0.85)

    def test_01_dynamic_detection_on_day_and_ross_layout(self):
        """Test 1: Agent finds header autonomously without hardcoded line 90."""
        rows = parse_csv_string(DAY_AND_ROSS_CSV_SNIPPET)
        res = self.detector.scan_and_parse_sheet(rows)

        self.assertTrue(res["success"], "Expected successful dynamic parsing")
        # Ensure detected header contains 'Origin' and 'Destination'
        self.assertIn("Origin", res["header_columns"])
        self.assertIn("Destination", res["header_columns"])
        self.assertIn("MIN", res["header_columns"])

        # Rule Invariant: 0 rows deleted or dropped
        self.assertEqual(res["summary"]["rows_deleted_or_dropped"], 0)
        self.assertGreater(res["summary"]["protected_rate_data_rows_extracted"], 0)

        # Non-critical disclaimers & company info recognized
        self.assertGreater(res["summary"]["non_critical_company_info_count"], 0)
        self.assertGreater(res["summary"]["non_critical_legal_disclaimers_count"], 0)
        print("\n+ Test 1 Passed: Day & Ross sheet detected dynamically. 0 rows deleted.")

    def test_02_alternate_sheet_headers_at_row_12(self):
        """Test 2: Alternate carrier sheet where headers start at Row 12."""
        rows = [
            ["Carrier", "FastFreight Canada"],
            ["Effective Date", "2026-01-01"],
            ["Customer", "Acme Logistics"],
            ["Address", "100 Bay St, Toronto ON"],
            ["Notes", "Subject to all rules and reissues thereof."],
            ["Payment Terms", "Net 30 days. Contras on account will not be accepted."],
            [],
            [],
            ["Accessorial", "Tailgate fee $50"],
            [],
            [],
            # Row 12 (index 11) is the rate table header
            ["Origin", "Destination", "MIN", "LTL", "CWT:1000", "CWT:5000"],
            ["TORONTO, ON", "MONTREAL, QC", "120.00", "22.50", "18.00", "14.50"],
            ["TORONTO, ON", "OTTAWA, ON", "110.00", "20.00", "16.50", "13.00"],
            ["TORONTO, ON", "CALGARY, AB", "210.00", "42.00", "34.00", "28.00"],
            ["TORONTO, ON", "VANCOUVER, BC", "240.00", "48.00", "39.00", "32.00"]
        ]
        res = self.detector.scan_and_parse_sheet(rows)
        self.assertTrue(res["success"])
        self.assertEqual(res["detected_header_row_1_based"], 12, "Should dynamically identify row 12 as header")
        self.assertEqual(res["summary"]["protected_rate_data_rows_extracted"], 4)
        self.assertEqual(res["summary"]["rows_deleted_or_dropped"], 0)
        print("+ Test 2 Passed: Alternate carrier sheet at Row 12 detected dynamically. 0 rows deleted.")

    def test_03_alternate_sheet_headers_at_row_140(self):
        """Test 3: Alternate carrier sheet where headers start at Row 140."""
        rows = []
        for i in range(1, 139):
            if i % 5 == 0:
                rows.append(["Notes", f"Legal disclaimer clause #{i} - confidential and proprietary."])
            else:
                rows.append([f"Term {i}", f"General shipping conditions and terms #{i}"])

        # Row 140 (index 139) is the header
        rows.append(["Origin Lane", "Destination Lane", "MIN", "CWT:500", "CWT:1000", "CWT:2000"])
        # Add 10 rate rows
        for j in range(10):
            rows.append([f"CITY_{j}, ON", f"DEST_{j}, QC", "95.00", "25.00", "20.00", "17.00"])

        res = self.detector.scan_and_parse_sheet(rows)
        self.assertTrue(res["success"])
        self.assertEqual(res["detected_header_row_1_based"], 139, "Should dynamically identify row 139/140 as header")
        self.assertEqual(res["summary"]["protected_rate_data_rows_extracted"], 10)
        self.assertEqual(res["summary"]["rows_deleted_or_dropped"], 0)
        print("+ Test 3 Passed: Alternate carrier sheet at Row 139/140 detected dynamically. 0 rows deleted.")

    def test_04_confusion_gate_halts_and_asks_user(self):
        """Test 4: When confused or ambiguous, the agent halts and prompts the user."""
        # Create an ambiguous sheet with 2 competing, unverified header structures
        rows = [
            ["Shipment Overview", "Estimated Transit"],
            ["From Zone", "To Zone", "Est Days"],  # Candidate A (score ~0.55)
            ["Toronto", "Montreal", "2"],
            [],
            ["Tariff Matrix", "Secondary Table"],
            ["Origin", "Destination", "Base Cost"],  # Candidate B (score ~0.60)
            ["Toronto", "Ottawa", "150.00"],
            []
        ]

        # Scan with default threshold (0.85) -> Should trigger Confusion Gate
        res = self.detector.scan_and_parse_sheet(rows)
        self.assertFalse(res["success"], "Ambiguous sheet must NOT proceed silently")
        self.assertEqual(res["status"], "CONFUSED_NEEDS_CLARIFICATION")
        self.assertTrue(
            "Ambiguity detected" in res["message"] or "could not locate a clear freight rate matrix header" in res["message"],
            "Agent must halt and ask the user for clarification"
        )
        print(f"+ Test 4 Part A Passed: Agent halted on confusion and asked user:\n  '{res['message']}'")

        # Now simulate User Confirmation: User says "Use Candidate row index 5" (Row 6)
        user_choice = 5
        resolved_res = self.detector.scan_and_parse_sheet(rows, user_confirmed_header_row=user_choice)
        self.assertTrue(resolved_res["success"], "Once user confirms, parsing must succeed")
        self.assertEqual(resolved_res["detected_header_row_0_based"], 5)
        self.assertEqual(resolved_res["summary"]["rows_deleted_or_dropped"], 0)
        print("+ Test 4 Part B Passed: Agent successfully resumed with user's confirmation and 0 rows deleted.")

    def test_05_rate_breaks_mapped_to_original_table_headers(self):
        """Test 5: Enforce that all rate breaks & values are mapped 1-to-1 to original table headers without dropping titles."""
        rows = parse_csv_string(DAY_AND_ROSS_CSV_SNIPPET)
        res = self.detector.scan_and_parse_sheet(rows)
        self.assertTrue(res["success"])

        expected_headers = ["MIN", "LTL", "CWT:1000", "CWT:2000", "CWT:5000", "CWT:10000", "CWT:20000"]
        self.assertEqual(res["rate_columns"], expected_headers, "Must preserve all original rate break header titles")

        # Verify Row 1: CALGARY, AB -> LINDSAY, ON
        r0 = res["rate_data_rows"][0]
        self.assertEqual(r0["origin"], "CALGARY, AB")
        self.assertEqual(r0["destination"], "LINDSAY, ON")
        self.assertIn("rate_breaks", r0)
        
        # Verify 1-to-1 mapping
        self.assertEqual(r0["rate_breaks"]["MIN"], "96.89")
        self.assertEqual(r0["rate_breaks"]["LTL"], "34.51")
        self.assertEqual(r0["rate_breaks"]["CWT:1000"], "27.73")
        self.assertEqual(r0["rate_breaks"]["CWT:2000"], "25.71")
        self.assertEqual(r0["rate_breaks"]["CWT:5000"], "23.93")
        self.assertEqual(r0["rate_breaks"]["CWT:10000"], "21.38")
        self.assertEqual(r0["rate_breaks"]["CWT:20000"], "0")

        # Verify rate_break_items carries header title and column index
        self.assertEqual(len(r0["rate_break_items"]), 7)
        self.assertEqual(r0["rate_break_items"][0]["header"], "MIN")
        self.assertEqual(r0["rate_break_items"][0]["value"], "96.89")
        self.assertEqual(r0["rate_break_items"][2]["header"], "CWT:1000")
        self.assertEqual(r0["rate_break_items"][2]["value"], "27.73")

        # Verify secondary table row (Row 9 in extracted rows, CALGARY -> COCHRANE)
        # 8 rows in table 1 + 3 rows in table 2 = 11 rows total
        self.assertEqual(len(res["rate_data_rows"]), 11)
        r9 = res["rate_data_rows"][9]
        self.assertEqual(r9["origin"], "CALGARY, AB")
        self.assertEqual(r9["destination"], "COCHRANE, AB")
        self.assertEqual(r9["rate_breaks"]["MIN"], "60.32")
        self.assertEqual(r9["rate_breaks"]["LTL"], "17.48")
        self.assertEqual(r9["rate_breaks"]["CWT:1000"], "7.31")

        print("+ Test 5 Passed: All 7 rate break titles preserved and mapped 1-to-1 to original table headers.")

    def test_06_issue_1_currency_and_continuous_row_density_scoring(self):
        """Test 6 (Issue 1): Non-currency transit table scores <50%; density boost applies to long table."""
        # Non-currency transit table
        transit_table = [
            ["From Zone", "To Zone", "Est Days"],
            ["Zone 1", "Zone 2", "2"],
            ["Zone 1", "Zone 3", "3"]
        ]
        transit_score = self.detector.score_header_candidate(0, transit_table[0], transit_table)
        self.assertLess(transit_score["score"], 0.50, "Transit schedule without currency/rates must score < 50%")
        self.assertTrue(any("Capped <50%" in r for r in transit_score["reasons"]))

        # Real rate matrix with currency format & continuous rows
        rate_table = [["Origin", "Destination", "MIN", "LTL", "CWT:1000"]]
        for k in range(12):
            rate_table.append([f"CITY_{k}", f"DEST_{k}", "95.50", "22.10", "18.40"])
        rate_score = self.detector.score_header_candidate(0, rate_table[0], rate_table)
        self.assertGreaterEqual(rate_score["score"], 0.85, "Rate matrix with continuous rows must score >= 85%")
        self.assertEqual(rate_score["continuous_rows"], 12)
        self.assertEqual(len(rate_score["data_preview"]), 3)
        print("+ Test 6 Passed (Issue 1): Currency requirement filters transit tables; density boosts rate matrix.")

    def test_07_issue_a_b_integer_exclusion_and_prose_surcharges(self):
        """Test 7 (Issues A & B): Preamble integers excluded; prose sentences extracted as structured surcharges."""
        sheet_text = """Customer,NAFF INC
Address,375 PENDANT DR, Mississauga ON
Telephone,905-555-1234
D & R Acct #,158437
Revision,336
Terms And Conditions
1,Appointment Deliveries: When customer requests via BOL a charge of $20.00 shall be assessed
8,Power Tailgate: waived
11,Protective Service: Subject to a surcharge of 18.00 % of the freight charge but not less than $39.50
Page,Page 1 of 3
Origin,Destination,MIN,LTL
CALGARY,LINDSAY,96.89,34.51
EDMONTON,BARRIE,96.89,34.11"""
        rows = parse_csv_string(sheet_text)
        res = self.detector.scan_and_parse_sheet(rows)
        self.assertTrue(res["success"])

        # Preamble numbers (158437, 336) must NOT be rates
        for r in res["rate_data_rows"]:
            self.assertNotIn("158437", r["raw_values"])
            self.assertNotIn("336", r["raw_values"])

        # Prose surcharges structured extraction
        struct_accs = res["structured_surcharges"]
        self.assertGreaterEqual(len(struct_accs), 2)
        
        # Verify Appointment $20 flat
        appt = next((a for a in struct_accs if a["name"] == "Delivery Appointment"), None)
        self.assertIsNotNone(appt)
        self.assertEqual(appt["type"], "FLAT")
        self.assertEqual(appt["amount"], 20.0)

        # Verify Protective Service 18% min $39.50
        prot = next((a for a in struct_accs if "Protective" in a["name"]), None)
        self.assertIsNotNone(prot)
        self.assertEqual(prot["type"], "PCT")
        self.assertEqual(prot["amount"], 18.0)
        self.assertEqual(prot["min_fee"], 39.50)

        # Hard invariant: Prose values ($20.00, 18%, $39.50) NEVER in rate grid
        for r in res["rate_data_rows"]:
            for rate_val in r["rate_breaks"].values():
                self.assertNotIn("20.00", str(rate_val))
                self.assertNotIn("39.50", str(rate_val))

        print("+ Test 7 Passed (Issues A & B): Integers excluded from rates; prose surcharges structured cleanly.")

    def test_08_issue_c_ghost_columns_and_province_dictionary(self):
        """Test 8 (Issue C): Merged province columns paired with Origin/Destination without column shifting."""
        rows = [
            ["Origin", "", "Destination", "", "MIN", "LTL", "CWT:1000"],
            ["CALGARY", "AB", "LINDSAY", "ON", "96.89", "34.51", "27.73"],
            ["EDMONTON", "AB", "BARRIE", "ON", "96.89", "34.11", "27.32"],
            ["VANCOUVER", "BC", "MONTREAL", "QC", "154.00", "42.00", "36.00"]
        ]
        res = self.detector.scan_and_parse_sheet(rows)
        self.assertTrue(res["success"])

        # Check ghost column pairing
        ghosts = res["ghost_columns_paired"]
        self.assertEqual(len(ghosts), 2)
        self.assertEqual(ghosts[0]["paired_with"], "Origin")
        self.assertEqual(ghosts[1]["paired_with"], "Destination")

        # Check compounds
        r0 = res["rate_data_rows"][0]
        self.assertEqual(r0["origin"], "CALGARY, AB")
        self.assertEqual(r0["destination"], "LINDSAY, ON")
        self.assertEqual(r0["rate_breaks"]["MIN"], "96.89")
        self.assertEqual(r0["rate_breaks"]["LTL"], "34.51")
        self.assertEqual(r0["rate_breaks"]["CWT:1000"], "27.73")
        print("+ Test 8 Passed (Issue C): Ghost columns paired via province dictionary with 0 column shift.")

    def test_09_issue_d_multi_segment_and_zero_loss_reconciliation(self):
        """Test 9 (Issue D): Multi-segment scanning and zero-data-loss row reconciliation audit."""
        rows = parse_csv_string(DAY_AND_ROSS_CSV_SNIPPET)
        res = self.detector.scan_and_parse_sheet(rows)
        self.assertTrue(res["success"])

        # Multi-segment detection
        segments = res["segments"]
        self.assertEqual(len(segments), 2, "Expected 2 table segments (Primary and Between Localities)")
        self.assertEqual(segments[0]["title"], "Primary Rate Matrix")
        self.assertEqual(segments[1]["title"], "Between Localities")
        self.assertEqual(len(segments[0]["rows"]), 8)
        self.assertEqual(len(segments[1]["rows"]), 3)

        # Zero-loss row reconciliation
        audit = res["reconciliation_audit"]
        self.assertTrue(audit["reconciliation_passed"], "Reconciliation audit must pass with 0 unaccounted rows")
        self.assertEqual(audit["unaccounted_rows"], 0)
        self.assertEqual(audit["reconciled_rows"], audit["total_sheet_rows"])
        self.assertGreater(res["composite_sheet_health"], 70)
        print(f"+ Test 9 Passed (Issue D): Multi-segment scanning ({len(segments)} segments) & Zero-loss reconciliation (100% accounted).")

if __name__ == "__main__":
    unittest.main()

