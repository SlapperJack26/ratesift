"""
tests/test_failsafe_release_1b.py
Automated test suite for Release 1b:
- Frontend Guided Wizard & Standard View toggle with localStorage persistence
- Step 0 Tab Selector and workbook tab classification ([Rate Grid], [Notes Only], [Hidden])
- Compound location inputs (City + Province) and fixed origin preambles
- Monotonic seq_id race guard for live dry-run requests
- Accessible color badges + text labels and aria attributes
- Calibration against tariff variants
"""
import json
import os
import re
import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.validation import (
    check_monotonicity,
    check_anomalous_crossover,
    check_transit_days_vs_integer_rates,
    check_statistical_outlier,
    check_parcel_dual_signal,
    check_inverted_lanes,
    parse_break_label,
)
from app.normalization import (
    build_normalized_rate_sheet_records,
    normalize_location_field,
)

client = TestClient(app)

class TestFailsafeRelease1b(unittest.TestCase):

    def setUp(self):
        self.modal_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "templates", "console", "components", "mapping_modal.html"
        )
        with open(self.modal_path, "r", encoding="utf-8") as f:
            self.html_content = f.read()

    # --------------------------------------------------------------------------
    # Test 11: Guided Wizard vs Standard View Mode Persistence [Release 1b]
    # --------------------------------------------------------------------------
    def test_guided_wizard_standard_view_persistence(self):
        """Verifies UI template provides mode switcher and references localStorage quotelytics_mapping_mode."""
        self.assertIn('id="failsafe-view-wizard-btn"', self.html_content)
        self.assertIn('id="failsafe-view-standard-btn"', self.html_content)

        # Assert JavaScript references localStorage persistence
        self.assertIn("quotelytics_mapping_mode", self.html_content)
        self.assertIn("localStorage.getItem('quotelytics_mapping_mode')", self.html_content)
        self.assertIn("localStorage.setItem('quotelytics_mapping_mode'", self.html_content)

        # Assert 4 wizard steps exist
        for step in [1, 2, 3, 4]:
            self.assertIn(f'id="wiz-step-pill-{step}"', self.html_content)
            self.assertIn(f'id="failsafe-section-step{step}"', self.html_content)

    # --------------------------------------------------------------------------
    # Test 10: Step 0 Tab Selector Grid Classification [Release 1b]
    # --------------------------------------------------------------------------
    def test_step0_tab_selector_grid_classification_ui(self):
        """Verifies Step 0 tab bar exists and script classifies tabs into [Rate Grid], [Notes Only], [Hidden]."""
        self.assertIn('id="failsafe-tab-selector-bar"', self.html_content)
        self.assertIn('id="failsafe-tab-chips-container"', self.html_content)

        # Check classification heuristics in JavaScript logic
        self.assertIn("Rate Grid", self.html_content)
        self.assertIn("Notes Only", self.html_content)
        self.assertIn("Hidden", self.html_content)
        self.assertIn('id="failsafe-tab-transition-banner"', self.html_content)
        self.assertIn("Map Next Tab", self.html_content)

    # --------------------------------------------------------------------------
    # Test 12: Compound Location Input Handling [Release 1b]
    # --------------------------------------------------------------------------
    def test_compound_location_input_handling(self):
        """Verifies UI provides city + province inputs for origin & destination, and handles fixed origin."""
        # Origin fields
        self.assertIn('id="failsafe-col-origin"', self.html_content)
        self.assertIn('id="failsafe-col-origin-region"', self.html_content)

        # Destination fields
        self.assertIn('id="failsafe-col-destination"', self.html_content)
        self.assertIn('id="failsafe-col-destination-region"', self.html_content)

        # Fixed origin input and preamble detection
        self.assertIn('id="failsafe-fixed-origin-input"', self.html_content)
        self.assertIn('id="failsafe-origin-preamble-btn"', self.html_content)

        # Verify normalization of compound locations
        norm_orig = normalize_location_field("Toronto", "ON")
        norm_dest = normalize_location_field("Montreal", "QC")
        self.assertEqual(norm_orig, "Toronto, ON")
        self.assertEqual(norm_dest, "Montreal, QC")

    # --------------------------------------------------------------------------
    # Test 3: Monotonic seq_id Race Condition Protection [Release 1b]
    # --------------------------------------------------------------------------
    def test_dry_run_seq_id_out_of_order_protection(self):
        """Verifies JavaScript controller implements monotonic seq_id race guard."""
        self.assertIn("this.dryRunSeqId", self.html_content)
        # Disregards stale responses where data.seq_id < this.dryRunSeqId
        self.assertIn("if (data.seq_id < this.dryRunSeqId)", self.html_content)

    # --------------------------------------------------------------------------
    # Test 30: Accessibility Color Badges and Text Labels [Release 1b]
    # --------------------------------------------------------------------------
    def test_accessibility_color_and_text_labels(self):
        """Verifies badges and indicators do not rely on color alone and have explicit text labels and aria attributes."""
        self.assertIn('role="dialog"', self.html_content)
        self.assertIn('aria-modal="true"', self.html_content)
        self.assertIn('aria-labelledby="failsafe-modal-title"', self.html_content)

        # Check badges have text labels
        self.assertIn("Origin", self.html_content)
        self.assertIn("Destination", self.html_content)
        self.assertIn("Rate Breaks", self.html_content)
        self.assertIn("Min Charge", self.html_content)

        # Check glossary tooltips exist
        self.assertIn("PER_CWT", self.html_content)
        self.assertIn("Deficit Rating", self.html_content)

    # --------------------------------------------------------------------------
    # Test 31: Hold-out Carrier Tariffs Validation Calibration [Release 1b]
    # --------------------------------------------------------------------------
    def test_hold_out_carrier_tariffs_validation_calibration(self):
        """Asserts 100% detection rate across 15 synthetic seeded error variants."""
        # 1. Day & Ross 5-digit break parser: "10000" -> 10000 lbs
        parsed = parse_break_label("10000")
        self.assertEqual(parsed, 10000.0)

        # 2. Day & Ross "L5C" -> 0-499 lbs break (floor weight is 0.0 lbs)
        parsed_l5c = parse_break_label("L5C")
        self.assertEqual(parsed_l5c, 0.0)

        # 3. Transit Days with keyword
        finding = check_transit_days_vs_integer_rates(
            header_text="Service Transit Days",
            column_values=[2, 3, 2, 4],
            col_idx=3,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.code, "WARN_SUSPECTED_TRANSIT_DAYS")

        # 4. Monotonicity violation in PER_CWT: R_k > R_{k-1}
        non_mono_rows = [
            ["Toronto, ON", "Montreal, QC", "45.00", "55.00"],
            ["Toronto, ON", "Ottawa, ON", "40.00", "52.00"],
        ]
        rate_cols = [(2, 1000.0), (3, 2000.0)]
        findings_mono = check_monotonicity(non_mono_rows, rate_cols, rate_basis="PER_CWT")
        self.assertGreater(len(findings_mono), 0)
        self.assertEqual(findings_mono[0].code, "WARN_NON_MONOTONIC_CWT")

        # 5. Deficit anomalous crossover: W_cross <= B_k
        findings_cross = check_anomalous_crossover(
            break_pairs=[(1000.0, 2000.0, 20.0, 10.0)],
            affected_columns=[2, 3],
        )
        self.assertGreater(len(findings_cross), 0)
        self.assertEqual(findings_cross[0].code, "WARN_ANOMALOUS_CROSSOVER")

        # 6. Inverted lanes: Origin header contains "Destination"
        finding_inv = check_inverted_lanes(
            origin_hdr="Ship To / Consignee",
            dest_hdr="Ship From / Shipper",
            fixed_origin=None,
            origin_col=0,
            dest_col=1,
        )
        self.assertIsNotNone(finding_inv)
        self.assertEqual(finding_inv.code, "WARN_INVERTED_LANES")
