import os
import unittest
import uuid
from fastapi.testclient import TestClient

from main import app
from app.detect import analyze
from services.break_header_parser import (
    parse_break_header,
    parse_skid_break_from_keywords,
)
from services.db_service import (
    delete_user_keyword_definition,
    get_user_keyword_map,
    init_db,
    list_user_keyword_definitions,
    upsert_user_keyword_definition,
)
from services.keyword_definition_service import interpret_keyword_definition
from services.quotelytics_db_service import get_sheet_full_rules, init_quotelytics_db
from services.quotelytics_extractor import QuotelyticsExtractor


class TestKeywordDefinitions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        init_quotelytics_db()

    def test_01_semantic_interpreter_variations(self):
        """Verifies natural-language interpretation for skid breaks, weight breaks, and column roles."""
        # 1. "less than 5 skids" -> 1..4 skids
        res_l5c = interpret_keyword_definition("L5C", "less than 5 skids")
        self.assertEqual(res_l5c["parsed_category"], "SKID_BREAK")
        self.assertEqual(res_l5c["parsed_rule"]["min_units"], 1)
        self.assertEqual(res_l5c["parsed_rule"]["max_units"], 4)
        self.assertEqual(res_l5c["badge_label"], "Skid Tier: 1–4 Skids")

        # 2. "up to 5 skids" -> 1..5 skids
        res_upto = interpret_keyword_definition("UP5", "up to 5 skids")
        self.assertEqual(res_upto["parsed_category"], "SKID_BREAK")
        self.assertEqual(res_upto["parsed_rule"]["min_units"], 1)
        self.assertEqual(res_upto["parsed_rule"]["max_units"], 5)

        # 3. "5 to 8 skids" -> 5..8 skids
        res_range = interpret_keyword_definition("M_SKID", "5 to 8 skids")
        self.assertEqual(res_range["parsed_category"], "SKID_BREAK")
        self.assertEqual(res_range["parsed_rule"]["min_units"], 5)
        self.assertEqual(res_range["parsed_rule"]["max_units"], 8)

        # 4. "5 skids" -> 5..5 skids
        res_exact = interpret_keyword_definition("5C", "5 skids")
        self.assertEqual(res_exact["parsed_category"], "SKID_BREAK")
        self.assertEqual(res_exact["parsed_rule"]["min_units"], 5)
        self.assertEqual(res_exact["parsed_rule"]["max_units"], 5)

        # 5. "500 to 999 lbs" -> weight break
        res_wt = interpret_keyword_definition("BRK_A", "500 to 999 lbs")
        self.assertEqual(res_wt["parsed_category"], "WEIGHT_BREAK")
        self.assertEqual(res_wt["parsed_rule"]["min_weight"], 500.0)
        self.assertEqual(res_wt["parsed_rule"]["max_weight"], 999.0)
        self.assertEqual(res_wt["parsed_rule"]["unit"], "lb")

        # 6. Column roles
        res_orig = interpret_keyword_definition("SHIP_PT", "Origin City")
        self.assertEqual(res_orig["parsed_category"], "COLUMN_ROLE")
        self.assertEqual(res_orig["parsed_rule"]["role"], "origin")

        res_min = interpret_keyword_definition("FLOOR_CHG", "Minimum Charge")
        self.assertEqual(res_min["parsed_category"], "COLUMN_ROLE")
        self.assertEqual(res_min["parsed_rule"]["role"], "base_cost")

    def test_02_break_header_parser_override(self):
        """Verifies that L5C defaults to 0-499 lbs weight break, but overrides to 1-4 skids when defined by user."""
        # Default behavior without custom keywords
        default_pb = parse_break_header("L5C")
        self.assertIsNotNone(default_pb)
        self.assertEqual(default_pb.kind, "weight")
        self.assertEqual(default_pb.min_weight, 0.0)
        self.assertEqual(default_pb.max_weight, 499.0)

        # User defines L5C -> "less than 5 skids"
        user_id = f"usr_kw_{uuid.uuid4().hex[:8]}"
        from services.auth_service import register_and_create_session
        user, _ = register_and_create_session(
            name="Keyword Tester",
            email=f"kw.{uuid.uuid4().hex[:6]}@quotelytics.ca",
            company="Quotelytics Freight",
            origin_zip="TORONTO, ON",
            password="KwTestPassword2026!",
        )
        user_id = user["id"]
        upsert_user_keyword_definition(user_id, "L5C", "less than 5 skids")
        kw_map = get_user_keyword_map(user_id)

        # Weight parser must NOT treat L5C as a weight break now
        weight_pb = parse_break_header("L5C", custom_keywords=kw_map)
        self.assertIsNone(weight_pb)

        # Skid parser must resolve L5C to 1..4 skids
        skid_pb = parse_skid_break_from_keywords("L5C", custom_keywords=kw_map)
        self.assertIsNotNone(skid_pb)
        self.assertEqual(skid_pb.kind, "skid")
        self.assertEqual(skid_pb.min_weight, 1.0)
        self.assertEqual(skid_pb.max_weight, 4.0)

    def test_03_detector_and_extractor_auto_understand_custom_keywords(self):
        """Verifies app/detect.py and QuotelyticsExtractor automatically understand custom headers across sheets."""
        from services.auth_service import register_and_create_session
        user, _ = register_and_create_session(
            name="Skid Mapper",
            email=f"skidmap.{uuid.uuid4().hex[:6]}@quotelytics.ca",
            company="Quotelytics LTL",
            origin_zip="TORONTO, ON",
            password="SkidMapPassword2026!",
        )
        user_id = user["id"]

        # Define company-wide custom keywords in Settings
        upsert_user_keyword_definition(user_id, "L5C", "less than 5 skids")
        upsert_user_keyword_definition(user_id, "5PLUS_SKD", "5 to 10 skids")
        upsert_user_keyword_definition(user_id, "SHIP_PT", "Origin City")
        upsert_user_keyword_definition(user_id, "DELIV_PT", "Destination City")
        upsert_user_keyword_definition(user_id, "FLOOR_CHG", "Minimum Charge")

        kw_map = get_user_keyword_map(user_id)

        rows = [
            ["SHIP_PT", "DELIV_PT", "FLOOR_CHG", "L5C", "5PLUS_SKD"],
            ["TORONTO, ON", "MONTREAL, QC", "150.00", "125.00", "110.00"],
            ["TORONTO, ON", "OTTAWA, ON", "140.00", "115.00", "100.00"],
            ["CALGARY, AB", "VANCOUVER, BC", "210.00", "185.00", "165.00"],
        ]

        # 1. Verify failsafe detector (app/detect.py)
        analysis = analyze(rows, sheet_name="CustomSkidSheet", custom_keywords=kw_map)
        self.assertEqual(analysis["status"], "ready")
        self.assertEqual(analysis["mode"], "skid")
        self.assertEqual(analysis["base_cost_column"], 2)
        self.assertEqual(
            analysis["skid_tiers"],
            [
                {"col": 3, "header": "L5C", "min_skids": 1, "max_skids": 4},
                {"col": 4, "header": "5PLUS_SKD", "min_skids": 5, "max_skids": 10},
            ],
        )

        # 2. Verify deep tariff extractor (QuotelyticsExtractor)
        import csv
        import io
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf)
        writer.writerows(rows)
        extractor = QuotelyticsExtractor(
            file_bytes=csv_buf.getvalue().encode("utf-8"),
            filename="company_custom_skid_sheet.csv",
            user_id=user_id,
        )
        res = extractor.process()
        self.assertEqual(res["metadata"]["rating_basis"], "PER_SKID")

        rules = get_sheet_full_rules(res["sheet_id"], user_id=user_id)
        breaks = rules["breaks"]
        l5c_breaks = [b for b in breaks if b["break_name"] == "L5C"]
        self.assertTrue(len(l5c_breaks) >= 3)
        for b in l5c_breaks:
            self.assertEqual(b["rate_type"], "PER_SKID")
            self.assertEqual(float(b["min_units"]), 1.0)
            self.assertEqual(float(b["max_units"]), 4.0)

    def test_04_settings_keywords_api_and_tenant_isolation(self):
        """Verifies GET/POST/DELETE /api/settings/keywords and strict tenant isolation."""
        from services.auth_service import register_and_create_session
        user_a, token_a = register_and_create_session(
            name="Tenant A",
            email=f"tenanta.kw.{uuid.uuid4().hex[:6]}@quotelytics.ca",
            company="Tenant A Corp",
            origin_zip="TORONTO, ON",
            password="TenantAPassword2026!",
        )
        user_b, token_b = register_and_create_session(
            name="Tenant B",
            email=f"tenantb.kw.{uuid.uuid4().hex[:6]}@quotelytics.ca",
            company="Tenant B Corp",
            origin_zip="MONTREAL, QC",
            password="TenantBPassword2026!",
        )

        client_a = TestClient(app)
        client_a.cookies.set("quotelytics_session", token_a)

        client_b = TestClient(app)
        client_b.cookies.set("quotelytics_session", token_b)

        # Tenant A adds L5C -> "less than 5 skids"
        post_res = client_a.post(
            "/api/settings/keywords",
            json={"keyword": "L5C", "definition_text": "less than 5 skids"},
        )
        self.assertEqual(post_res.status_code, 200)
        kw_obj = post_res.json()["keyword_definition"]
        self.assertEqual(kw_obj["keyword"], "L5C")
        self.assertEqual(kw_obj["parsed_category"], "SKID_BREAK")
        self.assertEqual(kw_obj["badge_label"], "Skid Tier: 1–4 Skids")
        kw_id = kw_obj["id"]

        # Tenant A lists keywords
        list_a = client_a.get("/api/settings/keywords").json()["keywords"]
        self.assertEqual(len(list_a), 1)
        self.assertEqual(list_a[0]["id"], kw_id)

        # Tenant B cannot see or delete Tenant A's keyword
        list_b = client_b.get("/api/settings/keywords").json()["keywords"]
        self.assertEqual(len(list_b), 0)
        del_b = client_b.delete(f"/api/settings/keywords/{kw_id}")
        self.assertEqual(del_b.status_code, 404)

        # Tenant A deletes their keyword
        del_a = client_a.delete(f"/api/settings/keywords/{kw_id}")
        self.assertEqual(del_a.status_code, 200)
        self.assertEqual(len(client_a.get("/api/settings/keywords").json()["keywords"]), 0)

    def test_05_settings_html_template_contains_keyword_definitions_ui(self):
        """Verifies templates/console/settings.html renders the Keyword Definitions UI section."""
        settings_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates",
            "console",
            "settings.html",
        )
        with open(settings_path, "r", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("keyword-definitions-section", html)
        self.assertIn("AI Mapping &amp; Header Keyword Definitions", html)
        self.assertIn("/api/settings/keywords", html)
        self.assertIn("less than 5 skids", html)


if __name__ == "__main__":
    unittest.main()
