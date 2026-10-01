import unittest
import os
import json
from fastapi.testclient import TestClient

from main import app
from services.auth_service import create_session
from services.ratesift_engine import (
    calculate_quote_for_sheet,
    quote_all_confirmed_carriers
)
from services.ratesift_db_service import (
    create_rate_sheet,
    insert_weight_breaks,
    insert_carrier_minimums,
    insert_rate_sheet_cells,
    confirm_rate_sheet
)

class TestMilestone4FilteringVersioningAnomaly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.user_id = "usr_alex_rivers"
        cls.token = create_session(cls.user_id)
        cls.client.cookies.set("shipflow_session", cls.token)

    def test_01_rule16_effective_and_expiry_date_filtering(self):
        """Rule 16: Check effective and expiry dates with clear warnings on expired/future sheets."""
        # Create a time-limited sheet: Effective 2026-10-01 to 2026-12-31
        sheet_id = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Temporal Freight",
            service_name="Standard LTL",
            tariff_ref="TF-2026-Q4",
            mode="LTL",
            currency="CAD",
            effective_date="2026-10-01",
            expiry_date="2026-12-31",
            version=1,
            source_filename="temporal_freight.xlsx"
        )
        insert_weight_breaks(sheet_id, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "break_name": "LTL:FLAT",
            "base_rate": 200.0,
            "rate_type": "FLAT",
            "source_cell": "B5"
        }])
        confirm_rate_sheet(sheet_id, self.user_id, confirmed_by="tester")

        # Case A: Future date (before effective date) -> Excluded with Rule 16 warning
        res_future = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=500.0,
            shipment_date="2026-09-15"
        )
        tf_excluded_future = [x for x in res_future["excluded_sheets"] if x["sheet_id"] == sheet_id]
        self.assertEqual(len(tf_excluded_future), 1)
        self.assertIn("Rule 16 Warning: Rate sheet not yet effective", tf_excluded_future[0]["reason"])

        # Case B: Expired date (after expiry date) -> Excluded with Rule 16 warning
        res_expired = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=500.0,
            shipment_date="2027-01-10"
        )
        tf_excluded_expired = [x for x in res_expired["excluded_sheets"] if x["sheet_id"] == sheet_id]
        self.assertEqual(len(tf_excluded_expired), 1)
        self.assertIn("Rule 16 Warning: Rate sheet expired on 2026-12-31", tf_excluded_expired[0]["reason"])

        # Case C: Active date -> Successfully quoted
        res_active = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=500.0,
            shipment_date="2026-11-15"
        )
        tf_quotes = [q for q in res_active["quotes"] if q["sheet_id"] == sheet_id]
        self.assertEqual(len(tf_quotes), 1)
        self.assertEqual(tf_quotes[0]["final_total"], 200.0)

    def test_02_rule17_version_precedence_resolution(self):
        """Rule 17: Apply highest confirmed version and report older versions as superceded."""
        carrier_name = "Apex Express"
        service_name = "Priority Freight"

        # Version 1 (Confirmed)
        s1 = create_rate_sheet(
            user_id=self.user_id,
            carrier_name=carrier_name,
            service_name=service_name,
            version=1,
            effective_date="2026-01-01",
            expiry_date="2026-12-31"
        )
        insert_weight_breaks(s1, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "CALGARY, AB",
            "dest_spec": "EDMONTON, AB",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "break_name": "FLAT",
            "base_rate": 150.0,
            "rate_type": "FLAT"
        }])
        confirm_rate_sheet(s1, self.user_id, confirmed_by="tester")

        # Version 2 (Confirmed)
        s2 = create_rate_sheet(
            user_id=self.user_id,
            carrier_name=carrier_name,
            service_name=service_name,
            version=2,
            effective_date="2026-06-01",
            expiry_date="2026-12-31"
        )
        insert_weight_breaks(s2, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "CALGARY, AB",
            "dest_spec": "EDMONTON, AB",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "break_name": "FLAT",
            "base_rate": 165.0,
            "rate_type": "FLAT"
        }])
        confirm_rate_sheet(s2, self.user_id, confirmed_by="tester")

        result = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="CALGARY, AB",
            destination="EDMONTON, AB",
            actual_weight=500.0,
            shipment_date="2026-07-01"
        )

        # Version 2 must be in quotes
        quoted_v2 = [q for q in result["quotes"] if q["sheet_id"] == s2]
        self.assertEqual(len(quoted_v2), 1)
        self.assertEqual(quoted_v2[0]["final_total"], 165.0)

        # Version 1 must NOT be in quotes
        quoted_v1 = [q for q in result["quotes"] if q["sheet_id"] == s1]
        self.assertEqual(len(quoted_v1), 0)

        # Version 1 must be in excluded_sheets with Rule 17 superceded reason
        ex_v1 = [x for x in result["excluded_sheets"] if x["sheet_id"] == s1]
        self.assertEqual(len(ex_v1), 1)
        self.assertIn("Rule 17: Superceded by newer confirmed Version 2", ex_v1[0]["reason"])

    def test_03_rule18_operational_limits_parcel_weight(self):
        """Rule 18: Weight > 150 lbs on Parcel mode excludes with clear explanation."""
        parcel_sheet = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Swift Courier",
            service_name="Next Day Air",
            mode="PARCEL",
            currency="CAD",
            version=1
        )
        insert_weight_breaks(parcel_sheet, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "OTTAWA, ON",
            "min_weight": 0.0,
            "max_weight": 150.0,
            "break_name": "PARCEL",
            "base_rate": 50.0,
            "rate_type": "FLAT"
        }])
        confirm_rate_sheet(parcel_sheet, self.user_id, confirmed_by="tester")

        # Shipment weight 160 lbs exceeds parcel 150 lbs
        res = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="OTTAWA, ON",
            actual_weight=160.0
        )
        sc_excluded = [x for x in res["excluded_sheets"] if x["sheet_id"] == parcel_sheet]
        self.assertEqual(len(sc_excluded), 1)
        self.assertIn("Rule 18 Exclusion: Shipment weight 160.0 lbs exceeds maximum parcel limit of 150 lbs", sc_excluded[0]["reason"])

    def test_04_rule18_operational_limits_parcel_dimensions(self):
        """Rule 18: Single dimension > 108 in or length + girth > 165 in on Parcel mode excludes with clear explanation."""
        parcel_sheet = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Parcel Plus",
            service_name="Ground Courier",
            mode="PARCEL",
            currency="CAD",
            version=1
        )
        insert_weight_breaks(parcel_sheet, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "OTTAWA, ON",
            "min_weight": 0.0,
            "max_weight": 150.0,
            "break_name": "PARCEL",
            "base_rate": 45.0,
            "rate_type": "FLAT"
        }])
        confirm_rate_sheet(parcel_sheet, self.user_id, confirmed_by="tester")

        # Exceeds single dimension (110 in > 108 in)
        res_dim = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="OTTAWA, ON",
            actual_weight=40.0,
            length=110.0,
            width=20.0,
            height=20.0
        )
        pp_ex_dim = [x for x in res_dim["excluded_sheets"] if x["sheet_id"] == parcel_sheet]
        self.assertEqual(len(pp_ex_dim), 1)
        self.assertIn("Rule 18 Exclusion: Package single dimension exceeds parcel limit of 108 inches", pp_ex_dim[0]["reason"])

        # Exceeds combined length + girth (100 + 2*(40+35) = 250 in > 165 in)
        res_girth = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="OTTAWA, ON",
            actual_weight=40.0,
            length=100.0,
            width=40.0,
            height=35.0
        )
        pp_ex_girth = [x for x in res_girth["excluded_sheets"] if x["sheet_id"] == parcel_sheet]
        self.assertEqual(len(pp_ex_girth), 1)
        self.assertIn("Rule 18 Exclusion: Package combined length and girth", pp_ex_girth[0]["reason"])

    def test_05_rule18_operational_limits_ltl_weight(self):
        """Rule 18: LTL weight > 44,000 lbs excludes with clear explanation (requires Dedicated FTL)."""
        ltl_sheet = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Heavy Haul LTL",
            service_name="General Freight",
            mode="LTL",
            currency="CAD",
            version=1
        )
        insert_weight_breaks(ltl_sheet, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 50000.0,
            "break_name": "CWT",
            "base_rate": 10.0,
            "rate_type": "CWT"
        }])
        confirm_rate_sheet(ltl_sheet, self.user_id, confirmed_by="tester")

        res = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=46000.0
        )
        hh_ex = [x for x in res["excluded_sheets"] if x["sheet_id"] == ltl_sheet]
        self.assertEqual(len(hh_ex), 1)
        self.assertIn("Rule 18 Exclusion: Shipment weight 46000.0 lbs exceeds legal LTL capacity of 44,000 lbs", hh_ex[0]["reason"])

    def test_06_rule18_unserved_lane_exclusion(self):
        """Rule 18 / 24: Unserved lanes report clear exclusion reason without hallucinating rates."""
        sheet_id = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Maritime Regional",
            service_name="Atlantic LTL",
            mode="LTL",
            currency="CAD",
            version=1
        )
        # Only serves Halifax to Moncton
        insert_weight_breaks(sheet_id, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "HALIFAX, NS",
            "dest_spec": "MONCTON, NB",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "break_name": "CWT",
            "base_rate": 15.0,
            "rate_type": "CWT"
        }])
        confirm_rate_sheet(sheet_id, self.user_id, confirmed_by="tester")

        # Request lane Vancouver, BC -> Calgary, AB
        res = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="VANCOUVER, BC",
            destination="CALGARY, AB",
            actual_weight=1200.0
        )
        mr_ex = [x for x in res["excluded_sheets"] if x["sheet_id"] == sheet_id]
        self.assertEqual(len(mr_ex), 1)
        self.assertIn("Rule 18 / Rule 24 Exclusion: Lane not served: Maritime Regional does not publish confirmed rates", mr_ex[0]["reason"])

    def test_07_rule27_rate_shift_anomaly_detection(self):
        """Rule 27: Rate shift > 25% compared to previous version triggers rate_shift_warning."""
        carrier_name = "Volatile Logistics"
        service_name = "Dry Van"

        # Version 1: $50.00 FLAT
        s1 = create_rate_sheet(
            user_id=self.user_id,
            carrier_name=carrier_name,
            service_name=service_name,
            version=1
        )
        insert_weight_breaks(s1, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "LONDON, ON",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "break_name": "FLAT",
            "base_rate": 100.0,
            "rate_type": "FLAT"
        }])
        confirm_rate_sheet(s1, self.user_id, confirmed_by="tester")

        # Version 2: $150.00 FLAT (+50% shift)
        s2 = create_rate_sheet(
            user_id=self.user_id,
            carrier_name=carrier_name,
            service_name=service_name,
            version=2
        )
        insert_weight_breaks(s2, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "LONDON, ON",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "break_name": "FLAT",
            "base_rate": 150.0,
            "rate_type": "FLAT"
        }])
        confirm_rate_sheet(s2, self.user_id, confirmed_by="tester")

        res = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="LONDON, ON",
            actual_weight=500.0
        )
        v2_quote = next(q for q in res["quotes"] if q["sheet_id"] == s2)
        warning = v2_quote.get("rate_shift_warning")
        self.assertIsNotNone(warning)
        self.assertTrue(warning["flagged"])
        self.assertEqual(warning["shift_pct"], 50.0)
        self.assertEqual(warning["previous_version"], 1)
        self.assertIn("Rule 27 Alert: Sharp rate increase of +50.0% detected", warning["message"])

    def test_08_rule23_flagged_reviewed_cell_caution_badge(self):
        """Rule 23: Flag any quote option that relies on a rate, surcharge or rule that was modified during human review or flagged 'needs review'."""
        sheet_id = create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Review Needed Freight",
            service_name="Expedited",
            version=1
        )
        insert_weight_breaks(sheet_id, self.user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "WINNIPEG, MB",
            "dest_spec": "REGINA, SK",
            "min_weight": 0.0,
            "max_weight": 5000.0,
            "break_name": "FLAT",
            "base_rate": 350.0,
            "rate_type": "FLAT",
            "source_cell": "Tariff!C12"
        }])
        # Insert a flagged cell record for Tariff!C12
        insert_rate_sheet_cells(sheet_id, self.user_id, [{
            "sheet_tab": "Tariff",
            "cell_coord": "Tariff!C12",
            "field_name": "base_rate",
            "raw_value": "350.00*",
            "extracted_value": "350.00",
            "confidence": 0.7,
            "needs_review": 1,
            "review_notes": "Unclear asterisk in sheet"
        }])
        confirm_rate_sheet(sheet_id, self.user_id, confirmed_by="tester")

        res = quote_all_confirmed_carriers(
            user_id=self.user_id,
            origin="WINNIPEG, MB",
            destination="REGINA, SK",
            actual_weight=800.0
        )
        rn_quote = next(q for q in res["quotes"] if q["sheet_id"] == sheet_id)
        self.assertTrue(rn_quote["relies_on_flagged_cell"])
        self.assertIsNotNone(rn_quote["caution_badge"])
        self.assertIn("Caution: Relies on flagged/reviewed data", rn_quote["caution_badge"])
        self.assertIn("Base Rate at Tariff!C12", rn_quote["caution_badge"])

    def test_09_api_calculate_quote_includes_filtering_and_warnings(self):
        """Verifies /api/ratesift/quotes/calculate handles filtering and returns proper structure."""
        resp = self.client.post("/api/ratesift/quotes/calculate", json={
            "origin": "CALGARY, AB",
            "destination": "EDMONTON, AB",
            "actual_weight": 500.0,
            "shipment_date": "2026-07-01"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("quote_id", data)
        self.assertIn("quotes", data)
        self.assertIn("excluded_sheets", data)
        self.assertIn("disclaimer", data)
        self.assertIn("Non-binding", data["disclaimer"])

if __name__ == "__main__":
    unittest.main()
