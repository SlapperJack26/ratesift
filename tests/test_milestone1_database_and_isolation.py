import unittest
import os
import json
import sqlite3
from datetime import datetime

from services.ratesift_db_service import (
    init_ratesift_db,
    get_connection,
    create_rate_sheet,
    get_rate_sheet,
    list_rate_sheets,
    confirm_rate_sheet,
    archive_rate_sheet,
    delete_rate_sheet,
    insert_rate_sheet_cells,
    get_rate_sheet_cells,
    insert_carrier_zones,
    insert_weight_breaks,
    insert_carrier_minimums,
    insert_carrier_surcharges,
    get_sheet_full_rules,
    log_quote_audit,
    get_quote_audit_log,
    list_quote_audit_logs,
    DATA_RESIDENCY_REGION
)
from services.db_service import init_db

class TestRateSiftMilestone1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize primary and RateSift DB
        init_db()
        init_ratesift_db()
        
        # Ensure test tenants exist in users table
        conn = get_connection()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT OR IGNORE INTO users (id, name, email, password_hash, company, origin_zip, tier, created_at)
        VALUES ('usr_tenant_a', 'Broker Alpha', 'alpha@freight.ca', 'hash', 'Alpha Logistics Canada', 'M5V1A1', 'PRO', ?)
        """, (now,))
        cursor.execute("""
        INSERT OR IGNORE INTO users (id, name, email, password_hash, company, origin_zip, tier, created_at)
        VALUES ('usr_tenant_b', 'Broker Beta', 'beta@cargo.ca', 'hash', 'Beta Transport QC', 'H2Z1A1', 'FREE', ?)
        """, (now,))
        conn.commit()
        conn.close()

    def test_01_schema_tables_exist(self):
        """Verifies that all 7 normalized RateSift tables exist with proper structure."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rs_%'")
        tables = {row["name"] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "rs_rate_sheets",
            "rs_rate_sheet_cells",
            "rs_carrier_zones",
            "rs_weight_breaks",
            "rs_carrier_minimums",
            "rs_carrier_surcharges",
            "rs_quote_audit_logs"
        }
        self.assertTrue(expected.issubset(tables), f"Missing tables: {expected - tables}")

    def test_02_tenant_isolation_rate_sheets(self):
        """Rule 28: Customer data confidentiality & tenant scoping."""
        tenant_a = "usr_tenant_a"
        tenant_b = "usr_tenant_b"

        # Tenant A creates a private rate sheet
        sheet_a_id = create_rate_sheet(
            user_id=tenant_a,
            carrier_name="Day & Ross",
            service_name="General Road LTL",
            tariff_ref="Tariff O-33545 Rev 336",
            currency="CAD",
            weight_unit="lb",
            dim_unit="in",
            dim_divisor=139.0,
            effective_date="2023-11-15",
            expiry_date="2024-04-30",
            source_filename="day_and_ross_guide_tariff.csv"
        )
        self.assertTrue(sheet_a_id.startswith("rs_sheet_"))

        # Tenant A can view their sheet
        sheet_a = get_rate_sheet(sheet_a_id, user_id=tenant_a)
        self.assertIsNotNone(sheet_a)
        self.assertEqual(sheet_a["carrier_name"], "Day & Ross")
        self.assertEqual(sheet_a["storage_region"], DATA_RESIDENCY_REGION)

        # Tenant B CANNOT view Tenant A's sheet
        sheet_for_b = get_rate_sheet(sheet_a_id, user_id=tenant_b)
        self.assertIsNone(sheet_for_b, "CRITICAL: Tenant B was able to access Tenant A's confidential rate sheet!")

        # Tenant B listing sheets should NOT contain Tenant A's sheet
        sheets_b = list_rate_sheets(user_id=tenant_b)
        self.assertFalse(any(s["id"] == sheet_a_id for s in sheets_b), "Tenant B list contained Tenant A's sheet!")

    def test_03_cell_level_traceability_rule3(self):
        """Rule 3: Record source of every extracted value (file, sheet tab, cell coordinate)."""
        tenant_a = "usr_tenant_a"
        sheet_id = create_rate_sheet(
            user_id=tenant_a,
            carrier_name="Purolator",
            service_name="Express Ground",
            tariff_ref="PUR-2026-FSA",
            source_filename="purolator_matrix.xlsx"
        )

        sample_cells = [
            {
                "sheet_tab": "Terms & Conditions",
                "cell_coord": "Terms!C14",
                "field_name": "surcharge.appointment",
                "raw_value": "$20.00",
                "extracted_value": "20.00",
                "confidence": 1.0,
                "needs_review": False
            },
            {
                "sheet_tab": "LTL Rates",
                "cell_coord": "Rates!D12",
                "field_name": "rate.cwt1000.calgary_to_toronto",
                "raw_value": "27.73",
                "extracted_value": "27.73",
                "confidence": 0.98,
                "needs_review": False
            },
            {
                "sheet_tab": "Footnotes",
                "cell_coord": "Footnotes!A28",
                "field_name": "surcharge.amazon_delivery",
                "raw_value": "EXCEPTION: DELIVERIES TO AMAZON BETWEEN 6 PM AND 11 PM $50.00",
                "extracted_value": "50.00",
                "confidence": 0.85,
                "needs_review": True,
                "review_notes": "Needs human verification of Amazon delivery time window rule"
            }
        ]

        insert_rate_sheet_cells(sheet_id, user_id=tenant_a, cells=sample_cells)

        # Retrieve all cells
        cells = get_rate_sheet_cells(sheet_id, user_id=tenant_a)
        self.assertEqual(len(cells), 3)

        # Retrieve needs_review cells (Rule 6)
        review_cells = get_rate_sheet_cells(sheet_id, user_id=tenant_a, needs_review_only=True)
        self.assertEqual(len(review_cells), 1)
        self.assertEqual(review_cells[0]["cell_coord"], "Footnotes!A28")
        self.assertTrue(review_cells[0]["needs_review"])

        # Tenant B CANNOT read Tenant A's cell coordinates
        cells_b = get_rate_sheet_cells(sheet_id, user_id="usr_tenant_b")
        self.assertEqual(len(cells_b), 0)

    def test_04_human_confirmation_gate_rule7(self):
        """Rule 7 & 19: Require human confirmation before live quoting."""
        tenant_a = "usr_tenant_a"
        sheet_id = create_rate_sheet(
            user_id=tenant_a,
            carrier_name="Midland",
            service_name="Atlantic Direct",
            tariff_ref="MID-2026-LTL",
            confirmation_status="PENDING_REVIEW"
        )

        sheet = get_rate_sheet(sheet_id, user_id=tenant_a)
        self.assertEqual(sheet["confirmation_status"], "PENDING_REVIEW")
        self.assertIsNone(sheet["confirmed_at"])

        # Confirm sheet
        success = confirm_rate_sheet(sheet_id, user_id=tenant_a, confirmed_by="Dylan Broker")
        self.assertTrue(success)

        confirmed_sheet = get_rate_sheet(sheet_id, user_id=tenant_a)
        self.assertEqual(confirmed_sheet["confirmation_status"], "CONFIRMED")
        self.assertEqual(confirmed_sheet["confirmed_by"], "Dylan Broker")
        self.assertIsNotNone(confirmed_sheet["confirmed_at"])

    def test_05_normalized_rules_ingestion_and_retrieval(self):
        """Rule 2: Normalized schema (breaks, zones, minimums, surcharges)."""
        tenant_a = "usr_tenant_a"
        sheet_id = create_rate_sheet(
            user_id=tenant_a,
            carrier_name="Day & Ross Test",
            service_name="General Road LTL",
            tariff_ref="Tariff O-33545 Rev 336"
        )

        # Insert Zones
        zones = [
            {"origin_spec": "CALGARY, AB", "dest_spec": "TORONTO, ON", "zone_code": "AB_ON", "transit_days": 4, "source_cell": "Zones!A2"},
            {"origin_spec": "VANCOUVER, BC", "dest_spec": "TORONTO, ON", "zone_code": "BC_ON", "transit_days": 5, "source_cell": "Zones!A3"}
        ]
        insert_carrier_zones(sheet_id, user_id=tenant_a, zones=zones)

        # Insert Weight Breaks
        breaks = [
            {"zone_code": "AB_ON", "min_weight": 0, "max_weight": 999, "break_name": "LTL", "base_rate": 34.51, "rate_type": "CWT", "source_cell": "Rates!C2"},
            {"zone_code": "AB_ON", "min_weight": 1000, "max_weight": 1999, "break_name": "CWT:1000", "base_rate": 27.73, "rate_type": "CWT", "source_cell": "Rates!D2"},
            {"zone_code": "AB_ON", "min_weight": 2000, "max_weight": 4999, "break_name": "CWT:2000", "base_rate": 25.71, "rate_type": "CWT", "source_cell": "Rates!E2"}
        ]
        insert_weight_breaks(sheet_id, user_id=tenant_a, breaks=breaks)

        # Insert Minimums
        minimums = [
            {"zone_code": "AB_ON", "min_charge": 96.89, "source_cell": "Rates!B2"}
        ]
        insert_carrier_minimums(sheet_id, user_id=tenant_a, minimums=minimums)

        # Insert Surcharges
        surcharges = [
            {"surcharge_code": "APPOINTMENT", "name": "Appointment Delivery", "condition_type": "appointment", "fee_type": "FLAT", "amount": 20.0, "source_cell": "Terms!1"},
            {"surcharge_code": "PROTECTIVE_SERVICE", "name": "Protective Heated Service", "condition_type": "heated", "fee_type": "PERCENTAGE", "amount": 18.0, "min_fee": 39.50, "source_cell": "Terms!11"},
            {"surcharge_code": "FERRY_LTL", "name": "Cost Recovery Ferry Surcharge LTL", "condition_type": "dest_province:NL", "condition_expression": {"weight_max": 7500}, "fee_type": "FLAT", "amount": 24.78, "source_cell": "Terms!22"},
            {"surcharge_code": "POWER_TAILGATE", "name": "Power Tailgate", "condition_type": "liftgate", "fee_type": "FLAT", "amount": 0.0, "is_waived": 1, "source_cell": "Terms!8"}
        ]
        insert_carrier_surcharges(sheet_id, user_id=tenant_a, surcharges=surcharges)

        # Fetch Full Sheet Rules
        full_rules = get_sheet_full_rules(sheet_id, user_id=tenant_a)
        self.assertEqual(len(full_rules["zones"]), 2)
        self.assertEqual(len(full_rules["breaks"]), 3)
        self.assertEqual(len(full_rules["minimums"]), 1)
        self.assertEqual(len(full_rules["surcharges"]), 4)
        self.assertEqual(full_rules["minimums"][0]["min_charge"], 96.89)

        # Verify Power Tailgate is recorded as waived
        waived_tailgate = next(s for s in full_rules["surcharges"] if s["surcharge_code"] == "POWER_TAILGATE")
        self.assertEqual(waived_tailgate["is_waived"], 1)

    def test_06_immutable_audit_logging_rule30(self):
        """Rule 30: Complete audit log of every quote with Canadian data residency (Rule 29)."""
        tenant_a = "usr_tenant_a"
        quote_id = f"RS-TEST-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

        shipment_inputs = {
            "origin": "CALGARY, AB",
            "destination": "TORONTO, ON",
            "actual_weight_lbs": 1450.0,
            "dimensions_in": {"length": 48, "width": 40, "height": 60},
            "accessorials": ["appointment", "residential_delivery"]
        }
        sheets_considered = ["rs_sheet_day_ross_01", "rs_sheet_manitoulin_01"]
        sheets_excluded = [
            {"sheet_id": "rs_sheet_expired_01", "carrier": "Old Carrier", "reason": "Rule 16: Sheet expired on 2024-01-01"}
        ]
        calculation_trace = [
            {"step": "DIM Weight Check", "actual_wt": 1450.0, "dim_wt": 828.77, "billable_wt": 1450.0},
            {"step": "Weight Break", "bracket": "CWT:1000", "rate_per_cwt": 27.73, "base_charge": 402.08},
            {"step": "Accessorial", "code": "APPOINTMENT", "amount": 20.00},
            {"step": "Min Charge Check", "subtotal": 422.08, "min_charge": 96.89, "final_charge": 422.08}
        ]
        final_results = [
            {
                "carrier": "Day & Ross",
                "service": "General Road LTL",
                "base_rate": 402.08,
                "surcharges": [{"code": "APPOINTMENT", "name": "Appointment Delivery", "amount": 20.00}],
                "total": 422.08,
                "transit_days": 4,
                "disclaimer": "Calculation from customer uploaded rate sheets. Non-binding quote."
            }
        ]

        log_quote_audit(
            user_id=tenant_a,
            quote_id=quote_id,
            shipment_inputs=shipment_inputs,
            sheets_considered=sheets_considered,
            sheets_excluded=sheets_excluded,
            calculation_trace=calculation_trace,
            final_results=final_results
        )

        # Retrieve and verify audit log
        audit = get_quote_audit_log(quote_id, user_id=tenant_a)
        self.assertIsNotNone(audit)
        self.assertEqual(audit["data_residency_region"], "CA_CENTRAL_WHC")
        self.assertEqual(audit["shipment_input"]["actual_weight_lbs"], 1450.0)
        self.assertEqual(len(audit["calculation_trace"]), 4)
        self.assertEqual(audit["final_results"][0]["total"], 422.08)

        # Verify Tenant B cannot retrieve Tenant A's audit log
        audit_b = get_quote_audit_log(quote_id, user_id="usr_tenant_b")
        self.assertIsNone(audit_b, "CRITICAL: Tenant B was able to access Tenant A's audit log!")

    def test_07_day_and_ross_guide_sheet_imported_and_queried(self):
        """Verifies Guide Template #1 (Day & Ross) normalized data, accessorials, breaks and minimums."""
        from services.import_day_and_ross_guide import import_day_and_ross_tariff
        tenant_alex = "usr_alex_rivers"
        
        sheet_id = import_day_and_ross_tariff(user_id=tenant_alex, auto_confirm=True)
        dnr_sheet = get_rate_sheet(sheet_id, user_id=tenant_alex)
        self.assertIsNotNone(dnr_sheet)
        self.assertEqual(dnr_sheet["carrier_name"], "Day & Ross")
        self.assertEqual(dnr_sheet["currency"], "CAD")
        self.assertEqual(dnr_sheet["weight_unit"], "lb")
        self.assertEqual(dnr_sheet["confirmation_status"], "CONFIRMED")
        self.assertEqual(dnr_sheet["effective_date"], "2023-11-15")
        self.assertEqual(dnr_sheet["expiry_date"], "2024-04-30")

        # Fetch full rules
        full_rules = get_sheet_full_rules(dnr_sheet["id"], user_id=tenant_alex)
        self.assertGreater(len(full_rules["surcharges"]), 10)
        self.assertGreater(len(full_rules["breaks"]), 100)
        self.assertGreater(len(full_rules["minimums"]), 20)

        # Check specific accessorial: Appointment Delivery ($20.00)
        appointment = next((s for s in full_rules["surcharges"] if s["surcharge_code"] == "APPOINTMENT"), None)
        self.assertIsNotNone(appointment)
        self.assertEqual(appointment["amount"], 20.0)
        self.assertIn("Row 20", appointment["source_cell"])

        # Check waived accessorial: Power Tailgate
        tailgate = next((s for s in full_rules["surcharges"] if s["surcharge_code"] == "POWER_TAILGATE"), None)
        self.assertIsNotNone(tailgate)
        self.assertEqual(tailgate["is_waived"], 1)

if __name__ == "__main__":
    unittest.main()

