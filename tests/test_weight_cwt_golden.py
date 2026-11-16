import ast
import io
import os
import unittest
import uuid
import openpyxl

from app.detect import analyze, parse_break_value
from app.models import JobStatus
from services.break_header_parser import parse_break_header
from services.fuel_index_service import record_fuel_index_history
from services.quotelytics_db_service import (
    init_quotelytics_db,
    create_rate_sheet,
    confirm_rate_sheet,
    confirm_no_minimum_column,
    delete_rate_sheet,
    get_rate_sheet,
    get_rate_sheet_cells,
    insert_weight_breaks,
    insert_carrier_minimums,
    insert_carrier_surcharges,
    insert_rate_sheet_cells,
    set_sheet_manual_override,
)
from services.quotelytics_engine import (
    calculate_billable_weight,
    calculate_quote_for_sheet,
    quote_all_confirmed_carriers,
)
from services.quotelytics_extractor import QuotelyticsExtractor


def _build_golden_cwt_sheet(
    user_id: str,
    fsc_pct: float = 15.0,
    weight_rounding_rule: str = "CEIL_1LB",
    allow_deficit_rating: int = 1,
    fsc_applies_to_accessorials: int = 0,
    top_open_ended: int = 0,
) -> str:
    """
    Creates the Canonical Golden LTL Carrier — Standard CWT fixture:
    - Mode: LTL, Rating Basis: WEIGHT_CWT, Currency: CAD, Unit: lb
    - Effective: 2026-01-01 to 2026-12-31
    - Lane: TORONTO, ON -> MONTREAL, QC
    - MIN: $85.00
    - Brackets:
      L5C (0..499): $36.00/CWT
      M5C (500..999): $30.00/CWT
      M1M (1000..1999): $25.00/CWT
      M2M (2000..4999): $20.00/CWT
      M5M (5000..10000): $16.00/CWT (closed top cap unless top_open_ended=1)
    """
    sheet_id = create_rate_sheet(
        user_id=user_id,
        carrier_name="Golden LTL Carrier",
        service_name="Standard CWT",
        mode="LTL",
        currency="CAD",
        weight_unit="lb",
        dim_unit="in",
        dim_divisor=None,
        effective_date="2026-01-01",
        expiry_date="2026-12-31",
        version=1,
        confirmation_status="CONFIRMED",
        rating_basis="WEIGHT_CWT",
        weight_rounding_rule=weight_rounding_rule,
        allow_deficit_rating=allow_deficit_rating,
        fsc_applies_to_accessorials=fsc_applies_to_accessorials,
    )
    confirm_rate_sheet(sheet_id, user_id, confirmed_by="Golden Suite")

    insert_carrier_minimums(sheet_id, user_id, [{
        "zone_code": "P2P",
        "origin_spec": "TORONTO, ON",
        "dest_spec": "MONTREAL, QC",
        "min_charge": 85.00,
        "source_cell": "Golden!C5",
    }])

    insert_weight_breaks(sheet_id, user_id, [
        {
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 499.0,
            "is_open_ended": 0,
            "break_name": "L5C",
            "base_rate": 36.00,
            "rate_type": "CWT",
            "source_cell": "Golden!D5",
        },
        {
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 500.0,
            "max_weight": 999.0,
            "is_open_ended": 0,
            "break_name": "M5C",
            "base_rate": 30.00,
            "rate_type": "CWT",
            "source_cell": "Golden!E5",
        },
        {
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 1000.0,
            "max_weight": 1999.0,
            "is_open_ended": 0,
            "break_name": "M1M",
            "base_rate": 25.00,
            "rate_type": "CWT",
            "source_cell": "Golden!F5",
        },
        {
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 2000.0,
            "max_weight": 4999.0,
            "is_open_ended": 0,
            "break_name": "M2M",
            "base_rate": 20.00,
            "rate_type": "CWT",
            "source_cell": "Golden!G5",
        },
        {
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 5000.0,
            "max_weight": None if top_open_ended else 10000.0,
            "is_open_ended": top_open_ended,
            "break_name": "M5M",
            "base_rate": 16.00,
            "rate_type": "CWT",
            "source_cell": "Golden!H5",
        },
    ])

    surcharges = [
        {
            "surcharge_code": "TAILGATE",
            "name": "Tailgate Delivery",
            "condition_type": "tailgate",
            "fee_type": "FLAT",
            "amount": 30.00,
            "fsc_eligible": 1,
            "source_cell": "Golden!Terms1",
        }
    ]
    if fsc_pct > 0:
        surcharges.append({
            "surcharge_code": "FSC",
            "name": "Sheet Fuel Surcharge",
            "condition_type": "fuel",
            "fee_type": "PERCENTAGE",
            "amount": fsc_pct,
            "is_included": 0,
            "source_cell": "Golden!FSC",
        })
    insert_carrier_surcharges(sheet_id, user_id, surcharges)
    return sheet_id


class TestWeightCwtGoldenSuite(unittest.TestCase):
    """
    Ship-by-Weight (WEIGHT_CWT) 20 Golden Tests + Monotonicity Property Test (GT-01 through GT-20).
    """

    @classmethod
    def setUpClass(cls):
        init_quotelytics_db()
        cls.user_id = f"usr_golden_{uuid.uuid4().hex[:8]}"
        cls.created_sheets = []

    @classmethod
    def tearDownClass(cls):
        for sid, uid in cls.created_sheets:
            try:
                delete_rate_sheet(sid, uid)
            except Exception:
                pass

    def _track(self, sheet_id: str, user_id: str = None) -> str:
        self.created_sheets.append((sheet_id, user_id or self.user_id))
        return sheet_id

    # =========================================================================
    # GT-01: Minimum Floor vs. Fuel & Accessorial Ordering
    # =========================================================================
    def test_gt01_minimum_floor_before_fuel_and_accessorials(self):
        sid = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=15.0))
        quote = calculate_quote_for_sheet(
            sheet_id=sid,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=200.0,
            accessorials=["TAILGATE"],
            shipment_date="2026-06-15",
        )
        # Natural: 2.00 * $36.00 = $72.00
        # Min floor raises freight to $85.00 (+13.00 adjustment)
        # FSC: 15% of $85.00 = $12.75
        # Accessorial: $30.00
        # Final total: $85.00 + $12.75 + $30.00 = $127.75
        self.assertEqual(quote["base_rate"], 72.00)
        self.assertEqual(quote["carrier_min_charge"], 85.00)
        self.assertEqual(quote["min_charge_adjustment"], 13.00)
        self.assertTrue(quote["min_applied"])
        self.assertEqual(quote["effective_freight"], 85.00)
        self.assertEqual(quote["fsc_amount"], 12.75)
        self.assertEqual(quote["accessorial_total"], 30.00)
        self.assertEqual(quote["total_surcharges"], 42.75)
        self.assertEqual(quote["final_total"], 127.75)
        self.assertFalse(quote["is_deficit_rated"])

    # =========================================================================
    # GT-02: Deficit Rating + FSC on Bumped Freight
    # =========================================================================
    def test_gt02_deficit_rating_and_fsc_on_bumped_freight(self):
        sid = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=15.0))
        quote = calculate_quote_for_sheet(
            sheet_id=sid,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=920.0,
            accessorials=[],
            shipment_date="2026-06-15",
        )
        # Natural (M5C @ $30): 9.20 * 30 = $276.00
        # Bumped (M1M 1000 lbs @ $25): 10.00 * 25 = $250.00
        # FSC: 15% * $250.00 = $37.50 -> Total = $287.50
        self.assertTrue(quote["is_deficit_rated"])
        self.assertEqual(quote["rated_weight"], 1000.0)
        self.assertEqual(quote["deficit_weight_added"], 80.0)
        self.assertEqual(quote["deficit_savings"], 26.00)
        self.assertEqual(quote["effective_freight"], 250.00)
        self.assertEqual(quote["fsc_amount"], 37.50)
        self.assertEqual(quote["final_total"], 287.50)

    # =========================================================================
    # GT-03: Deficit Floor Override (is_deficit_rated = False when savings == 0)
    # =========================================================================
    def test_gt03_deficit_floor_override_zero_realized_savings(self):
        sid = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Floor Override LTL",
            service_name="Standard",
            mode="LTL",
            currency="CAD",
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid, self.user_id, confirmed_by="Golden Suite")
        insert_carrier_minimums(sid, self.user_id, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_charge": 85.00,
        }])
        insert_weight_breaks(sid, self.user_id, [
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 0.0,
                "max_weight": 499.0,
                "break_name": "L5C",
                "base_rate": 55.00,
                "rate_type": "CWT",
            },
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 500.0,
                "max_weight": 999.0,
                "break_name": "M5C",
                "base_rate": 16.00,
                "rate_type": "CWT",
            },
        ])
        # 150 lbs: Natural = 1.50 * 55 = $82.50; Bumped (500 lbs) = 5.00 * 16 = $80.00
        # Min charge ($85.00) floors both -> realized savings = $0.00!
        quote = calculate_quote_for_sheet(
            sheet_id=sid,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=150.0,
        )
        self.assertTrue(quote["min_applied"])
        self.assertEqual(quote["effective_freight"], 85.00)
        self.assertEqual(quote["final_total"], 85.00)
        self.assertFalse(quote["is_deficit_rated"])
        self.assertEqual(quote["deficit_weight_added"], 0.0)
        self.assertEqual(quote["rated_weight"], 150.0)
        self.assertEqual(quote["deficit_savings"], 0.00)

    # =========================================================================
    # GT-04: Weight Rounding Rules (CEIL_1LB vs CEIL_5LB vs EXACT)
    # =========================================================================
    def test_gt04_weight_rounding_rules(self):
        # 1. CEIL_1LB (Default): 999.4 lbs -> 1000.0 lbs -> lands directly in M1M ($25/CWT) = $250.00, is_deficit_rated=False
        sid_ceil1 = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0, weight_rounding_rule="CEIL_1LB"))
        q_ceil1 = calculate_quote_for_sheet(
            sheet_id=sid_ceil1,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=999.4,
        )
        self.assertEqual(q_ceil1["billable_weight"], 1000.0)
        self.assertEqual(q_ceil1["rate_break"], "M1M")
        self.assertEqual(q_ceil1["final_total"], 250.00)
        self.assertFalse(q_ceil1["is_deficit_rated"])

        # 2. CEIL_5LB: 995.2 lbs -> 1000.0 lbs -> lands directly in M1M = $250.00
        sid_ceil5 = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0, weight_rounding_rule="CEIL_5LB"))
        q_ceil5 = calculate_quote_for_sheet(
            sheet_id=sid_ceil5,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=995.2,
        )
        self.assertEqual(q_ceil5["billable_weight"], 1000.0)
        self.assertEqual(q_ceil5["rate_break"], "M1M")
        self.assertEqual(q_ceil5["final_total"], 250.00)
        self.assertFalse(q_ceil5["is_deficit_rated"])

        # 3. EXACT: 999.4 lbs stays 999.4, matches M5C (500 <= 999.4 < 1000), natural = 9.994 * 30 = 299.82,
        # deficit-rated to 1000 lbs = $250.00 (is_deficit_rated=True, deficit_savings=49.82)
        sid_exact = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0, weight_rounding_rule="EXACT"))
        q_exact = calculate_quote_for_sheet(
            sheet_id=sid_exact,
            user_id=self.user_id,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=999.4,
        )
        self.assertEqual(q_exact["billable_weight"], 999.4)
        self.assertTrue(q_exact["is_deficit_rated"])
        self.assertEqual(q_exact["rated_weight"], 1000.0)
        self.assertEqual(q_exact["deficit_savings"], 49.82)
        self.assertEqual(q_exact["final_total"], 250.00)

    # =========================================================================
    # GT-05: Exact Bracket Boundaries & Closed Top Cap
    # =========================================================================
    def test_gt05_exact_bracket_boundaries_and_closed_top_cap(self):
        sid_ceil = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0, weight_rounding_rule="CEIL_1LB", top_open_ended=0))
        sid_exact = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0, weight_rounding_rule="EXACT", top_open_ended=0))

        # 499.99 with CEIL_1LB -> 500 -> M5C ($150.00, not deficit rated)
        q_499_ceil = calculate_quote_for_sheet(sid_ceil, self.user_id, "TORONTO, ON", "MONTREAL, QC", 499.99)
        self.assertEqual(q_499_ceil["billable_weight"], 500.0)
        self.assertEqual(q_499_ceil["rate_break"], "M5C")
        self.assertEqual(q_499_ceil["final_total"], 150.00)
        self.assertFalse(q_499_ceil["is_deficit_rated"])

        # 499.99 with EXACT -> L5C natural $180.00, deficit-bumped to 500 ($150.00)
        q_499_exact = calculate_quote_for_sheet(sid_exact, self.user_id, "TORONTO, ON", "MONTREAL, QC", 499.99)
        self.assertEqual(q_499_exact["billable_weight"], 499.99)
        self.assertTrue(q_499_exact["is_deficit_rated"])
        self.assertEqual(q_499_exact["final_total"], 150.00)

        # 500.00 -> M5C ($150.00, is_deficit_rated=False)
        q_500 = calculate_quote_for_sheet(sid_exact, self.user_id, "TORONTO, ON", "MONTREAL, QC", 500.00)
        self.assertEqual(q_500["rate_break"], "M5C")
        self.assertEqual(q_500["final_total"], 150.00)
        self.assertFalse(q_500["is_deficit_rated"])

        # 1000.00 -> M1M ($250.00, is_deficit_rated=False)
        q_1000 = calculate_quote_for_sheet(sid_exact, self.user_id, "TORONTO, ON", "MONTREAL, QC", 1000.00)
        self.assertEqual(q_1000["rate_break"], "M1M")
        self.assertEqual(q_1000["final_total"], 250.00)
        self.assertFalse(q_1000["is_deficit_rated"])

        # 10000.00 (inclusive closed cap) -> M5M (100 * $16 = $1600.00)
        q_10000 = calculate_quote_for_sheet(sid_exact, self.user_id, "TORONTO, ON", "MONTREAL, QC", 10000.00)
        self.assertEqual(q_10000["rate_break"], "M5M")
        self.assertEqual(q_10000["final_total"], 1600.00)

        # 10000.01 -> exceeds closed 10,000.0 cap -> rejected!
        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(sid_exact, self.user_id, "TORONTO, ON", "MONTREAL, QC", 10000.01)
        self.assertIn("exceeds closed top weight bracket maximum", str(ctx.exception))

    # =========================================================================
    # GT-06: Decimal ROUND_HALF_UP & No-round() AST Guard
    # =========================================================================
    def test_gt06_decimal_round_half_up_and_no_builtin_round_ast_guard(self):
        sid = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Decimal Carrier",
            service_name="Precision LTL",
            mode="LTL",
            currency="CAD",
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid, self.user_id, confirmed_by="Golden Suite")
        insert_carrier_minimums(sid, self.user_id, [{
            "zone_code": "P2P",
            "origin_spec": "CALGARY, AB",
            "dest_spec": "LINDSAY, ON",
            "min_charge": 0.00,
        }])
        insert_weight_breaks(sid, self.user_id, [
            {
                "zone_code": "P2P",
                "origin_spec": "CALGARY, AB",
                "dest_spec": "LINDSAY, ON",
                "min_weight": 0.0,
                "max_weight": 999.0,
                "break_name": "LTL",
                "base_rate": 34.51,
                "rate_type": "CWT",
            },
            {
                "zone_code": "P2P",
                "origin_spec": "CALGARY, AB",
                "dest_spec": "LINDSAY, ON",
                "min_weight": 1000.0,
                "max_weight": 9999.0,
                "is_open_ended": 1,
                "break_name": "CWT:1000",
                "base_rate": 27.73,
                "rate_type": "CWT",
            },
        ])

        # 1450 lbs @ $27.73/CWT = 14.5 * 27.73 = 402.085 -> $402.09 (ROUND_HALF_UP)
        q_1450 = calculate_quote_for_sheet(sid, self.user_id, "CALGARY, AB", "LINDSAY, ON", 1450.0)
        self.assertEqual(q_1450["base_rate"], 402.09)
        self.assertEqual(q_1450["final_total"], 402.09)

        # 50 lbs @ $34.51/CWT = 0.5 * 34.51 = 17.255 -> $17.26 (ROUND_HALF_UP)
        q_50 = calculate_quote_for_sheet(sid, self.user_id, "CALGARY, AB", "LINDSAY, ON", 50.0)
        self.assertEqual(q_50["base_rate"], 17.26)
        self.assertEqual(q_50["final_total"], 17.26)

        # AST Guard: verify services/quotelytics_engine.py contains ZERO calls to built-in round()
        engine_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "services", "quotelytics_engine.py")
        with open(engine_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=engine_path)
        round_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "round"
        ]
        self.assertEqual(len(round_calls), 0, "services/quotelytics_engine.py must not call built-in round()")

    # =========================================================================
    # GT-07: Mode-Specific & Per-Piece DIM Weight
    # =========================================================================
    def test_gt07_mode_specific_and_per_piece_dim_weight(self):
        # Case A: LTL with no divisor and no cubic rule -> 100 lbs, 60x50x48 bills at 100.0 lbs
        sid_ltl_none = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="LTL No Divisor",
            service_name="Standard",
            mode="LTL",
            dim_divisor=None,
            dim_min_rule=None,
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid_ltl_none, self.user_id, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_ltl_none, self.user_id, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "is_open_ended": 1,
            "break_name": "LTL",
            "base_rate": 20.00,
            "rate_type": "CWT",
        }])
        qa = calculate_quote_for_sheet(
            sid_ltl_none, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=100.0, length=60.0, width=50.0, height=48.0,
        )
        self.assertEqual(qa["billable_weight"], 100.0)
        self.assertFalse(qa["is_dim_billed"])

        # Case B: LTL with 10 lbs/cu ft rule -> 60*50*48 / 1728 * 10 = 833.33 -> CEIL_1LB -> 834.0 lbs
        sid_ltl_cubic = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="LTL Cubic Rule",
            service_name="Standard",
            mode="LTL",
            dim_divisor=None,
            dim_min_rule="10.00 lbs per cu ft",
            weight_rounding_rule="CEIL_1LB",
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid_ltl_cubic, self.user_id, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_ltl_cubic, self.user_id, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "is_open_ended": 1,
            "break_name": "LTL",
            "base_rate": 20.00,
            "rate_type": "CWT",
        }])
        qb = calculate_quote_for_sheet(
            sid_ltl_cubic, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=100.0, length=60.0, width=50.0, height=48.0,
        )
        self.assertEqual(qb["billable_weight"], 834.0)
        self.assertTrue(qb["is_dim_billed"])

        # Case C: LTL with divisor 139, 2 pieces:
        # Piece 1: (40 lb, 30x20x20 in, qty=1) -> DIM = 12000/139 = 86.33 -> 87 lb (max(40, 87)=87)
        # Piece 2: (95 lb, 20x20x20 in, qty=1) -> DIM = 8000/139 = 57.55 -> 58 lb (max(95, 58)=95)
        # Total billable = 87 + 95 = 182.0 lbs (NOT rejected by 150 lb per-piece actual weight limit!)
        sid_parcel = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="LTL Multi-Piece",
            service_name="Standard",
            mode="LTL",
            dim_divisor=139.0,
            weight_rounding_rule="CEIL_1LB",
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid_parcel, self.user_id, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_parcel, self.user_id, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 500.0,
            "is_open_ended": 1,
            "break_name": "LTL_CWT",
            "base_rate": 50.00,
            "rate_type": "CWT",
        }])
        qc = calculate_quote_for_sheet(
            sid_parcel, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=135.0,
            pieces=[
                (40.0, 30.0, 20.0, 20.0, 1),
                (95.0, 20.0, 20.0, 20.0, 1),
            ],
        )
        self.assertEqual(qc["billable_weight"], 182.0)
        self.assertEqual(qc["final_total"], 91.00)  # 1.82 * 50.00

        # Case D: PARCEL mode decommissioned -> E_PARCEL_DEPRECATED_LTL_ONLY
        sid_parcel_no_div = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Parcel Decommissioned",
            service_name="Ground",
            mode="PARCEL",
            dim_divisor=None,
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid_parcel_no_div, self.user_id, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_parcel_no_div, self.user_id, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 500.0,
            "is_open_ended": 1,
            "break_name": "PARCEL_CWT",
            "base_rate": 50.00,
            "rate_type": "CWT",
        }])
        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(
                sid_parcel_no_div, self.user_id, "TORONTO, ON", "MONTREAL, QC",
                actual_weight=20.0, length=10.0, width=10.0, height=10.0,
            )
        self.assertIn("E_PARCEL_DEPRECATED_LTL_ONLY", str(ctx.exception))

    # =========================================================================
    # GT-08: Mixed-Currency Guard & Target-Currency FX Conversion
    # =========================================================================
    def test_gt08_mixed_currency_guard_and_target_currency_fx(self):
        uid = f"usr_gt08_{uuid.uuid4().hex[:6]}"
        # Carrier A: $200.00 USD
        sid_usd = self._track(create_rate_sheet(
            user_id=uid,
            carrier_name="Carrier A USD",
            service_name="CrossBorder",
            currency="USD",
            confirmation_status="CONFIRMED",
        ), uid)
        confirm_rate_sheet(sid_usd, uid, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_usd, uid, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "is_open_ended": 1,
            "break_name": "FLAT",
            "base_rate": 200.00,
            "rate_type": "FLAT",
        }])

        # Carrier B: $250.00 CAD
        sid_cad = self._track(create_rate_sheet(
            user_id=uid,
            carrier_name="Carrier B CAD",
            service_name="Domestic",
            currency="CAD",
            confirmation_status="CONFIRMED",
        ), uid)
        confirm_rate_sheet(sid_cad, uid, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_cad, uid, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "is_open_ended": 1,
            "break_name": "FLAT",
            "base_rate": 250.00,
            "rate_type": "FLAT",
        }])

        # 1. Without target_currency -> mixed_currencies_detected=True, grouped in quotes_by_currency
        res_mixed = quote_all_confirmed_carriers(
            user_id=uid,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=1000.0,
        )
        self.assertTrue(res_mixed["mixed_currencies_detected"])
        self.assertIn("USD", res_mixed["quotes_by_currency"])
        self.assertIn("CAD", res_mixed["quotes_by_currency"])
        self.assertEqual(res_mixed["quotes_by_currency"]["USD"][0]["final_total"], 200.00)
        self.assertEqual(res_mixed["quotes_by_currency"]["CAD"][0]["final_total"], 250.00)

        # 2. With target_currency="CAD", fx_rates={"USD_CAD": "1.3600"}, fx_date="2026-10-11":
        # Carrier A = 200.00 * 1.36 = $272.00 CAD, so Carrier B ($250.00 CAD) ranks #1!
        res_conv = quote_all_confirmed_carriers(
            user_id=uid,
            origin="TORONTO, ON",
            destination="MONTREAL, QC",
            actual_weight=1000.0,
            target_currency="CAD",
            fx_rates={"USD_CAD": "1.3600"},
            fx_date="2026-10-11",
        )
        self.assertFalse(res_conv["mixed_currencies_detected"])
        self.assertEqual(res_conv["quotes"][0]["carrier_name"], "Carrier B CAD")
        self.assertEqual(res_conv["quotes"][0]["final_total"], 250.00)
        self.assertEqual(res_conv["quotes"][1]["carrier_name"], "Carrier A USD")
        self.assertEqual(res_conv["quotes"][1]["final_total"], 272.00)
        self.assertEqual(res_conv["quotes"][1]["original_currency"], "USD")
        self.assertEqual(res_conv["quotes"][1]["original_final_total"], 200.00)
        self.assertEqual(res_conv["quotes"][1]["fx_date"], "2026-10-11")

    # =========================================================================
    # GT-09: Shared Break-Header Parser & Failsafe Parity
    # =========================================================================
    def test_gt09_shared_break_header_parser_and_failsafe_parity(self):
        # Verify single shared parser behavior across all required header formats
        p_l5c = parse_break_header("L5C", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_l5c)
        self.assertEqual((p_l5c.min_val, p_l5c.max_val, p_l5c.is_open_ended), (0.0, 499.0, False))

        p_m5c = parse_break_header("M5C", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_m5c)
        self.assertEqual((p_m5c.min_val, p_m5c.is_open_ended), (500.0, True))

        p_m1m = parse_break_header("M1M", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_m1m)
        self.assertEqual((p_m1m.min_val, p_m1m.is_open_ended), (1000.0, True))

        p_range = parse_break_header("1,000 to 1,999 lbs", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_range)
        self.assertEqual((p_range.min_val, p_range.max_val, p_range.is_open_ended), (1000.0, 1999.0, False))

        p_cwt = parse_break_header("CWT:2000", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_cwt)
        self.assertEqual((p_cwt.min_val, p_cwt.is_open_ended), (2000.0, True))

        p_plus = parse_break_header("10,000+ lbs", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_plus)
        self.assertEqual((p_plus.min_val, p_plus.is_open_ended), (10000.0, True))

        # Leading hyphen "-45" -> under 45 (0 to 45, closed) vs "500-999" -> 500 to 999
        p_under = parse_break_header("-45", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_under)
        self.assertEqual((p_under.min_val, p_under.max_val, p_under.is_open_ended), (0.0, 45.0, False))

        p_hyphen = parse_break_header("500-999", rating_basis="WEIGHT_CWT")
        self.assertIsNotNone(p_hyphen)
        self.assertEqual((p_hyphen.min_val, p_hyphen.max_val, p_hyphen.is_open_ended), (500.0, 999.0, False))

        # Pure unit label "Rate per CWT" must NOT be treated as a weight break
        self.assertIsNone(parse_break_header("Rate per CWT", rating_basis="WEIGHT_CWT"))
        self.assertEqual(parse_break_value("Rate per CWT"), (None, None))

        # Parity with app/detect.py: "1,000 to 1,999 lbs" is NEVER proposed as Destination, while standalone "To" IS Destination
        rows = [
            ["Origin", "To", "Min", "L5C", "500-999", "1,000 to 1,999 lbs", "CWT:2000", "10,000+ lbs"],
            ["TORONTO", "MONTREAL", 85.0, 36.0, 30.0, 25.0, 20.0, 16.0],
            ["TORONTO", "OTTAWA", 75.0, 32.0, 28.0, 22.0, 18.0, 14.0],
            ["CALGARY", "EDMONTON", 65.0, 28.0, 24.0, 20.0, 16.0, 12.0],
        ]
        analysis = analyze(rows, sheet_name="Rates")
        guesses_by_field = {g["field"]: g for g in analysis["guesses"]}
        self.assertIn("origin", guesses_by_field)
        self.assertEqual(guesses_by_field["origin"]["columns"], [0])
        self.assertIn("destination", guesses_by_field)
        self.assertEqual(guesses_by_field["destination"]["columns"], [1])  # "To" column is index 1, NOT index 5
        self.assertNotIn(5, guesses_by_field["destination"]["columns"])
        self.assertIn("weight_breaks", guesses_by_field)
        wb_guess = guesses_by_field["weight_breaks"]
        wb_map = dict(zip(wb_guess["columns"], wb_guess["break_values"]))
        self.assertEqual(wb_map[5], 1000.0)
        self.assertEqual(wb_map[6], 2000.0)
        self.assertEqual(wb_map[7], 10000.0)

    # =========================================================================
    # GT-10: Failsafe needs_mapping vs. manual_override Gate
    # =========================================================================
    def test_gt10_failsafe_needs_mapping_blocks_manual_override(self):
        self.assertEqual(JobStatus.needs_mapping.value, "needs_mapping")
        sid = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Unmapped Carrier",
            service_name="LTL",
            confirmation_status="PENDING_REVIEW",
            failsafe_status=JobStatus.needs_mapping.value,
        ))
        insert_weight_breaks(sid, self.user_id, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 5000.0,
            "is_open_ended": 1,
            "break_name": "LTL",
            "base_rate": 25.00,
            "rate_type": "CWT",
        }])
        # Set manual_override = 1 BEFORE mapping is confirmed
        set_sheet_manual_override(sid, self.user_id, True)
        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(sid, self.user_id, "TORONTO, ON", "MONTREAL, QC", 1000.0)
        self.assertIn("needs_mapping", str(ctx.exception))

    # =========================================================================
    # GT-11: Deficit Rating Tie, Non-Adjacent Bracket Jump & Top Bracket
    # =========================================================================
    def test_gt11_deficit_rating_tie_and_non_adjacent_jump_and_top_bracket(self):
        # 1. Tie: 800 lbs @ $31.25/CWT ($250.00) vs 1000 lbs @ $25.00/CWT ($250.00) -> is_deficit_rated=False
        sid_tie = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Tie Carrier",
            service_name="LTL",
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid_tie, self.user_id, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_tie, self.user_id, [
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 500.0,
                "max_weight": 999.0,
                "break_name": "M5C",
                "base_rate": 31.25,
                "rate_type": "CWT",
            },
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 1000.0,
                "max_weight": 5000.0,
                "is_open_ended": 1,
                "break_name": "M1M",
                "base_rate": 25.00,
                "rate_type": "CWT",
            },
        ])
        q_tie = calculate_quote_for_sheet(sid_tie, self.user_id, "TORONTO, ON", "MONTREAL, QC", 800.0)
        self.assertEqual(q_tie["final_total"], 250.00)
        self.assertFalse(q_tie["is_deficit_rated"])
        self.assertEqual(q_tie["rated_weight"], 800.0)
        self.assertEqual(q_tie["deficit_savings"], 0.00)

        # 2. Non-adjacent jump: 900 lbs where 500=$30 ($270), 1000=$28 ($280), 2000=$13 ($260) -> jumps to 2000!
        sid_jump = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Jump Carrier",
            service_name="LTL",
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid_jump, self.user_id, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_jump, self.user_id, [
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 500.0,
                "max_weight": 999.0,
                "break_name": "M5C",
                "base_rate": 30.00,
                "rate_type": "CWT",
            },
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 1000.0,
                "max_weight": 1999.0,
                "break_name": "M1M",
                "base_rate": 28.00,
                "rate_type": "CWT",
            },
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 2000.0,
                "max_weight": 10000.0,
                "is_open_ended": 0,
                "break_name": "M2M",
                "base_rate": 13.00,
                "rate_type": "CWT",
            },
        ])
        q_jump = calculate_quote_for_sheet(sid_jump, self.user_id, "TORONTO, ON", "MONTREAL, QC", 900.0)
        self.assertTrue(q_jump["is_deficit_rated"])
        self.assertEqual(q_jump["rated_weight"], 2000.0)
        self.assertEqual(q_jump["effective_freight"], 260.00)
        self.assertEqual(q_jump["deficit_savings"], 10.00)

        # 3. Top bracket (8000 lbs in 2000-10000 tier): nothing higher to bump to -> stays at 8000 lbs
        q_top = calculate_quote_for_sheet(sid_jump, self.user_id, "TORONTO, ON", "MONTREAL, QC", 8000.0)
        self.assertFalse(q_top["is_deficit_rated"])
        self.assertEqual(q_top["rated_weight"], 8000.0)
        self.assertEqual(q_top["effective_freight"], 1040.00)

    # =========================================================================
    # GT-12: Property Test — Freight Charge Monotonicity
    # =========================================================================
    def test_gt12_property_freight_charge_monotonicity(self):
        sid = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0, weight_rounding_rule="EXACT"))
        # Sweep across brackets 1 lb to 10,000 lbs including fractional boundaries around every break
        test_weights = []
        for w in range(1, 10001, 25):
            test_weights.append(float(w))
        for boundary in (499, 500, 999, 1000, 1999, 2000, 4999, 5000, 9999, 10000):
            for offset in (-0.99, -0.50, -0.01, 0.0, 0.01, 0.50, 0.99):
                cand = round(boundary + offset, 2)
                if 1.0 <= cand <= 10000.0:
                    test_weights.append(cand)
        test_weights = sorted(set(test_weights))

        prev_freight = 0.0
        prev_w = 0.0
        for w in test_weights:
            q = calculate_quote_for_sheet(sid, self.user_id, "TORONTO, ON", "MONTREAL, QC", w)
            freight = q["effective_freight"]
            self.assertGreaterEqual(
                freight,
                prev_freight,
                f"Monotonicity violated: weight {w} lbs produced freight ${freight:.2f} < ${prev_freight:.2f} at {prev_w} lbs",
            )
            prev_freight = freight
            prev_w = w

    # =========================================================================
    # GT-13: Accessorial Caps, Weight Bases & Percentage Bases
    # =========================================================================
    def test_gt13_accessorial_caps_weight_bases_and_pct_bases(self):
        sid = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0))
        insert_carrier_surcharges(sid, self.user_id, [
            # 10% fee with min_fee=$30, max_fee=$40 on POST_MIN_FREIGHT ($250 -> $25 -> clamped to $30.00)
            {
                "surcharge_code": "HEATED_POST",
                "name": "Heated Post-Min",
                "condition_type": "heated_post",
                "fee_type": "PERCENTAGE",
                "amount": 10.0,
                "min_fee": 30.00,
                "max_fee": 40.00,
                "pct_base": "POST_MIN_FREIGHT",
            },
            # 10% fee on PRE_MIN_FREIGHT (natural $276 -> $27.60, no min_fee)
            {
                "surcharge_code": "INS_PRE",
                "name": "Insurance Pre-Min",
                "condition_type": "ins_pre",
                "fee_type": "PERCENTAGE",
                "amount": 10.0,
                "min_fee": 0.00,
                "max_fee": 40.00,
                "pct_base": "PRE_MIN_FREIGHT",
            },
            # $2.00/CWT on BILLABLE weight (920 lbs -> 9.20 * $2 = $18.40)
            {
                "surcharge_code": "CWT_BILLABLE",
                "name": "Sorting Billable",
                "condition_type": "cwt_billable",
                "fee_type": "CWT",
                "amount": 2.00,
                "max_fee": 19.00,
                "weight_base": "BILLABLE",
            },
            # $2.00/CWT on RATED weight (1000 lbs -> 10.00 * $2 = $20.00 -> capped at max_fee=$19.00)
            {
                "surcharge_code": "CWT_RATED",
                "name": "Sorting Rated",
                "condition_type": "cwt_rated",
                "fee_type": "CWT",
                "amount": 2.00,
                "max_fee": 19.00,
                "weight_base": "RATED",
            },
        ])
        q = calculate_quote_for_sheet(
            sid, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=920.0,
            accessorials=["heated_post", "ins_pre", "cwt_billable", "cwt_rated"],
        )
        sur_map = {s["code"]: s["amount"] for s in q["surcharges"]}
        self.assertEqual(sur_map["HEATED_POST"], 30.00)
        self.assertEqual(sur_map["INS_PRE"], 27.60)
        self.assertEqual(sur_map["CWT_BILLABLE"], 18.40)
        self.assertEqual(sur_map["CWT_RATED"], 19.00)

    # =========================================================================
    # GT-14: Fuel Scope, Precedence, Included (0%) & Index Date
    # =========================================================================
    def test_gt14_fuel_scope_precedence_included_and_index_date(self):
        # Record two dated fuel index entries
        record_fuel_index_history("2026-03-01", 1.75, 18.0, 9.0, source="OTA Q1 2026")
        record_fuel_index_history("2026-06-01", 2.05, 22.0, 11.0, source="OTA Q2 2026")

        # Case A: is_included = 1 ("Fuel Included") ignores benchmark index -> $0.00 FSC
        sid_inc = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0))
        insert_carrier_surcharges(sid_inc, self.user_id, [{
            "surcharge_code": "FSC",
            "name": "Fuel Included",
            "condition_type": "fuel",
            "fee_type": "PERCENTAGE",
            "amount": 0.0,
            "is_included": 1,
        }])
        qa = calculate_quote_for_sheet(
            sid_inc, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=1000.0, accessorials=["fuel"], shipment_date="2026-06-15",
        )
        self.assertEqual(qa["fsc_amount"], 0.00)
        self.assertEqual(qa["final_total"], 250.00)

        # Case B: fsc_applies_to_accessorials = 1 ($250 freight + $30 tailgate, 15% FSC = $42.00)
        sid_acc_fsc = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=15.0, fsc_applies_to_accessorials=1))
        qb = calculate_quote_for_sheet(
            sid_acc_fsc, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=1000.0, accessorials=["TAILGATE"], shipment_date="2026-06-15",
        )
        self.assertEqual(qb["fsc_amount"], 42.00)
        self.assertEqual(qb["final_total"], 322.00)  # 250 + 30 + 42

        # Case C: Benchmark index date lookup (2026-03-15 uses 18.0% = $45.00; 2026-06-15 uses 22.0% = $55.00)
        sid_bench = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0))
        qc_mar = calculate_quote_for_sheet(
            sid_bench, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=1000.0, accessorials=["fuel"], shipment_date="2026-03-15",
        )
        self.assertEqual(qc_mar["fsc_amount"], 45.00)

        qc_jun = calculate_quote_for_sheet(
            sid_bench, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=1000.0, accessorials=["fuel"], shipment_date="2026-06-15",
        )
        self.assertEqual(qc_jun["fsc_amount"], 55.00)

    # =========================================================================
    # GT-15: Unparsed Requested Accessorial Blocks Incomplete Quote
    # =========================================================================
    def test_gt15_unparsed_requested_accessorial_blocks_incomplete_quote(self):
        sid = self._track(_build_golden_cwt_sheet(self.user_id, fsc_pct=0.0))
        insert_carrier_surcharges(sid, self.user_id, [{
            "surcharge_code": "INSIDE_DELIVERY",
            "name": "Inside Delivery (Call for Quote)",
            "condition_type": "inside_delivery",
            "fee_type": "FLAT",
            "amount": None,
            "is_unparsed": 1,
        }])

        # When inside_delivery is NOT requested -> quotable = True
        q_ok = calculate_quote_for_sheet(
            sid, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=1000.0, accessorials=[],
        )
        self.assertEqual(q_ok["final_total"], 250.00)

        # When inside_delivery IS requested -> quotable = False (raises explicit error instead of returning incomplete total)
        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(
                sid, self.user_id, "TORONTO, ON", "MONTREAL, QC",
                actual_weight=1000.0, accessorials=["inside_delivery"],
            )
        self.assertIn("INCOMPLETE_QUOTE_UNPARSED_ACCESSORIAL", str(ctx.exception))

    # =========================================================================
    # GT-16: Extraction-Time Bracket Gap Rejection
    # =========================================================================
    def test_gt16_extraction_time_bracket_gap_rejection(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "GapSheet"
        ws.append(["Origin", "Destination", "MIN", "500-899", "1000-1999"])
        ws.append(["TORONTO, ON", "MONTREAL, QC", 85.00, 30.00, 25.00])
        buf = io.BytesIO()
        wb.save(buf)

        extractor = QuotelyticsExtractor(buf.getvalue(), "gap_tariff.xlsx", self.user_id)
        res = extractor.process()
        sid = self._track(res["sheet_id"])

        flagged = get_rate_sheet_cells(sid, self.user_id, needs_review_only=True)
        gap_flags = [c for c in flagged if c["field_name"] == "BRACKET_GAP_DETECTED"]
        self.assertGreater(len(gap_flags), 0)

        # Even if manual_override is set, quoting is blocked until the bracket gap is resolved
        set_sheet_manual_override(sid, self.user_id, True)
        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(sid, self.user_id, "TORONTO, ON", "MONTREAL, QC", 700.0)
        self.assertIn("BRACKET_GAP_DETECTED", str(ctx.exception))

    # =========================================================================
    # GT-17: Column Override Conflict Priority & Audit Log
    # =========================================================================
    def test_gt17_column_override_conflict_priority_and_audit_log(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "OverrideSheet"
        # Col 0: Origin, Col 1: Destination, Col 2: MIN, Col 3: L5C, Col 4: M1M (auto-detects 1000 lbs)
        ws.append(["Origin", "Destination", "MIN", "L5C", "M1M"])
        ws.append(["TORONTO, ON", "MONTREAL, QC", 85.00, 36.00, 22.00])
        buf = io.BytesIO()
        wb.save(buf)

        # User's column_overrides maps col 4 to 1500 lbs instead of 1000 lbs
        overrides = {
            "OverrideSheet": {
                "origin_col": 0,
                "destination_col": 1,
                "min_charge_col": 2,
                "rate_breaks": [
                    {"col": 3, "header": "L5C", "break_value": 0.0},
                    {"col": 4, "header": "M1M", "break_value": 1500.0},
                ],
            }
        }
        extractor = QuotelyticsExtractor(buf.getvalue(), "override_tariff.xlsx", self.user_id, column_overrides=overrides)
        res = extractor.process()
        sid = self._track(res["sheet_id"])

        # Verify override won (min_weight = 1500.0) and MAPPING_OVERRIDE_CONFLICT was logged
        cells = get_rate_sheet_cells(sid, self.user_id, needs_review_only=False)
        conflict_logs = [c for c in cells if c["field_name"] == "MAPPING_OVERRIDE_CONFLICT"]
        self.assertEqual(len(conflict_logs), 1)
        self.assertEqual(conflict_logs[0]["extracted_value"], "1500.0")

    # =========================================================================
    # GT-18: Governance — Date Boundaries, Blank Expiry & Version Normalization
    # =========================================================================
    def test_gt18_governance_date_boundaries_blank_expiry_and_version_normalization(self):
        uid = f"usr_gt18_{uuid.uuid4().hex[:6]}"
        # v1: "ABC Freight"
        sid_v1 = self._track(create_rate_sheet(
            user_id=uid,
            carrier_name="ABC Freight",
            service_name="Standard LTL",
            effective_date="2026-01-01",
            expiry_date="2026-12-31",
            version=1,
            confirmation_status="CONFIRMED",
        ), uid)
        confirm_rate_sheet(sid_v1, uid, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_v1, uid, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "is_open_ended": 1,
            "break_name": "FLAT",
            "base_rate": 300.00,
            "rate_type": "FLAT",
        }])

        # v2: "  abc   freight " with extra whitespace and lowercase -> must normalize & supercede v1!
        sid_v2 = self._track(create_rate_sheet(
            user_id=uid,
            carrier_name="  abc   freight ",
            service_name=" standard   ltl ",
            effective_date="2026-01-01",
            expiry_date="2026-12-31",
            version=2,
            confirmation_status="CONFIRMED",
        ), uid)
        confirm_rate_sheet(sid_v2, uid, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_v2, uid, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "is_open_ended": 1,
            "break_name": "FLAT",
            "base_rate": 240.00,
            "rate_type": "FLAT",
        }])

        # Exact effective_date (2026-01-01) and exact expiry_date (2026-12-31) are inclusive & quotable
        q_start = calculate_quote_for_sheet(sid_v2, uid, "TORONTO, ON", "MONTREAL, QC", 500.0, shipment_date="2026-01-01")
        self.assertEqual(q_start["final_total"], 240.00)

        q_end = calculate_quote_for_sheet(sid_v2, uid, "TORONTO, ON", "MONTREAL, QC", 500.0, shipment_date="2026-12-31")
        self.assertEqual(q_end["final_total"], 240.00)

        # expiry_date + 1 day (2027-01-01) is rejected
        with self.assertRaises(ValueError):
            calculate_quote_for_sheet(sid_v2, uid, "TORONTO, ON", "MONTREAL, QC", 500.0, shipment_date="2027-01-01")

        # Multi-carrier call deduplicates v1 and v2 via whitespace/case normalization, quoting only v2
        res_all = quote_all_confirmed_carriers(uid, "TORONTO, ON", "MONTREAL, QC", 500.0, shipment_date="2026-06-15")
        self.assertEqual(len(res_all["quotes"]), 1)
        self.assertEqual(res_all["quotes"][0]["sheet_id"], sid_v2)

        # Blank expiry_date is quotable
        sid_blank_exp = self._track(create_rate_sheet(
            user_id=uid,
            carrier_name="Evergreen LTL",
            service_name="Open Ended",
            effective_date="2026-01-01",
            expiry_date=None,
            version=1,
            confirmation_status="CONFIRMED",
        ), uid)
        confirm_rate_sheet(sid_blank_exp, uid, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_blank_exp, uid, [{
            "zone_code": "P2P",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 10000.0,
            "is_open_ended": 1,
            "break_name": "FLAT",
            "base_rate": 210.00,
            "rate_type": "FLAT",
        }])
        q_blank = calculate_quote_for_sheet(sid_blank_exp, uid, "TORONTO, ON", "MONTREAL, QC", 500.0, shipment_date="2029-05-01")
        self.assertEqual(q_blank["final_total"], 210.00)

    # =========================================================================
    # GT-19: KG Sheet with LBS Shipment (and vice versa)
    # =========================================================================
    def test_gt19_kg_sheet_with_lbs_shipment_conversion(self):
        sid_kg = self._track(create_rate_sheet(
            user_id=self.user_id,
            carrier_name="Metric Freight",
            service_name="KG Tariff",
            mode="LTL",
            currency="CAD",
            weight_unit="kg",
            weight_rounding_rule="CEIL_1LB",
            confirmation_status="CONFIRMED",
        ))
        confirm_rate_sheet(sid_kg, self.user_id, confirmed_by="Golden Suite")
        insert_weight_breaks(sid_kg, self.user_id, [
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 0.0,
                "max_weight": 999.0,
                "break_name": "UNDER_1000KG",
                "base_rate": 60.00,
                "rate_type": "CWT",
            },
            {
                "zone_code": "P2P",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 1000.0,
                "max_weight": 10000.0,
                "is_open_ended": 1,
                "break_name": "1000KG_PLUS",
                "base_rate": 50.00,
                "rate_type": "CWT",
            },
        ])
        # Shipment input: 2,200 lbs -> 2200 / 2.20462262185 = 997.9032 kg -> CEIL_1LB -> 998.0 kg
        # Natural (9.98 * 60 = $598.80) vs Bumped 1000 kg (10.00 * 50 = $500.00) -> $500.00!
        q = calculate_quote_for_sheet(
            sid_kg, self.user_id, "TORONTO, ON", "MONTREAL, QC",
            actual_weight=2200.0,
            shipment_weight_unit="LBS",
        )
        self.assertEqual(q["billable_weight"], 998.0)
        self.assertTrue(q["is_deficit_rated"])
        self.assertEqual(q["rated_weight"], 1000.0)
        self.assertEqual(q["final_total"], 500.00)

    # =========================================================================
    # GT-20: Missing Minimum Column Explicit Confirmation Gate
    # =========================================================================
    def test_gt20_missing_minimum_column_requires_explicit_confirmation(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "NoMinSheet"
        # No MIN column present
        ws.append(["Origin", "Destination", "L5C", "M1M"])
        ws.append(["TORONTO, ON", "MONTREAL, QC", 36.00, 25.00])
        buf = io.BytesIO()
        wb.save(buf)

        extractor = QuotelyticsExtractor(buf.getvalue(), "no_min_tariff.xlsx", self.user_id)
        res = extractor.process()
        sid = self._track(res["sheet_id"])

        sheet_before = get_rate_sheet(sid, self.user_id)
        self.assertEqual(sheet_before["failsafe_status"], "missing_minimum_column")
        self.assertEqual(sheet_before["no_minimum_confirmed"], 0)

        # Even if confirmed or manual_override=1, quoting is blocked until no_minimum_confirmed is explicitly set
        set_sheet_manual_override(sid, self.user_id, True)
        with self.assertRaises(ValueError) as ctx:
            calculate_quote_for_sheet(sid, self.user_id, "TORONTO, ON", "MONTREAL, QC", 1000.0)
        self.assertIn("MISSING_MINIMUM_COLUMN", str(ctx.exception))

        # Explicitly confirm $0.00 minimum -> now quotable!
        confirm_no_minimum_column(sid, self.user_id, confirmed_by="Broker Reviewer")
        confirm_rate_sheet(sid, self.user_id, confirmed_by="Broker Reviewer")
        q = calculate_quote_for_sheet(sid, self.user_id, "TORONTO, ON", "MONTREAL, QC", 1000.0)
        self.assertEqual(q["carrier_min_charge"], 0.00)
        self.assertEqual(q["final_total"], 250.00)


if __name__ == "__main__":
    unittest.main()
