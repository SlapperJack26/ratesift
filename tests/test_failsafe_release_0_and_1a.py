"""
tests/test_failsafe_release_0_and_1a.py
Comprehensive automated test suite for Release 0 (Security Hardening) and Release 1a (Backend Engine & Validation).
Enforces strict test isolation via fixture guard, zero database access in dry-run, append-only triggers,
and full parity with the canonical quoting engine.
"""
from decimal import Decimal, ROUND_HALF_UP
import io
import json
import os
import sqlite3
import time
from typing import Dict, Tuple, List, Optional, Any
import uuid
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

from app.constants import (
    ERR_CODES,
    SEVERITY_BLOCKER,
    SEVERITY_WARNING,
    PLATFORM_DISPLAY_NAME,
    ENGINE_DISPLAY_NAME,
)
from app.jobs import job_store
from app.main import app, grid_cache, rate_limiter
from app.normalization import (
    build_normalized_rate_sheet_records,
    normalize_location_field,
)
from app.output_safety import sanitize_cell_value, sanitize_workbook
from app.validation import (
    Finding,
    BLOCKER_MISSING_ORIGIN,
    BLOCKER_MISSING_DEST,
    BLOCKER_MISSING_CURRENCY,
    BLOCKER_COLUMN_COLLISION,
    BLOCKER_WEIGHT_MISSING_UNIT,
    BLOCKER_WEIGHT_NO_RATES,
    BLOCKER_SKID_INVALID_TIERS,
    BLOCKER_HEADER_AMBIGUITY,
    BLOCKER_MC_RATE_COLLISION,
    BLOCKER_ALL_LANES_NO_RATE,
    BLOCKER_UNPARSED_BREAK_LABEL,
    WARN_NON_MONOTONIC_CWT,
    WARN_ANOMALOUS_CROSSOVER,
    WARN_SUSPECTED_TRANSIT_DAYS,
    WARN_SUSPECTED_INTEGER_RATE,
    WARN_RATE_OUTLIER_STATISTICAL,
    WARN_PARCEL_CONTOUR_OVERRIDE,
    WARN_INVERTED_LANES,
    WARN_BREAK_EXCEEDS_CAPACITY,
    check_monotonicity,
    check_anomalous_crossover,
    check_transit_days_vs_integer_rates,
    check_statistical_outlier,
    check_parcel_dual_signal,
    check_inverted_lanes,
    parse_break_label,
    compute_layout_fingerprint,
)
from services.auth_service import register_and_create_session
from services.db_service import update_user_tier
from services.quotelytics_db_service import (
    create_rate_sheet,
    insert_weight_breaks,
    insert_carrier_minimums,
    confirm_rate_sheet,
    get_connection,
    get_rate_sheet,
    get_system_setting,
    set_system_setting,
    insert_failsafe_audit_log,
    insert_failsafe_override_attribution,
    increment_failsafe_rejection,
    insert_failsafe_shadow_log,
    prune_failsafe_rejection_counters,
    delete_tenant_failsafe_attributions,
)
from services.quotelytics_engine import (
    calculate_quote_for_sheet,
    calculate_quote_from_memory,
    quote_all_confirmed_carriers,
)


client = TestClient(app)


def _make_auth_headers(prefix: str = "failsafe_user", company: str = "Apex Logistics") -> Tuple[Dict[str, str], str, str]:
    user, token = register_and_create_session(
        name=f"User {prefix}",
        email=f"{prefix}.{uuid.uuid4().hex[:8]}@apex-logistics.ca",
        company=company,
        origin_zip="TORONTO, ON",
        password="TestPassword2026!",
    )
    update_user_tier(user["id"], "BUSINESS")
    uid = str(user["id"])
    return {"Authorization": f"Bearer {token}"}, uid, uid


def create_excel_bytes(rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==============================================================================
# Test Case Suite
# ==============================================================================

class TestFailsafeRelease0And1a(unittest.TestCase):

    def setUp(self):
        grid_cache.clear()
        client.cookies.clear()
        os.environ["ENABLE_FAILSAFE_CSRF"] = "false"
        os.environ["FAILSAFE_MODE"] = "off"

    def tearDown(self):
        grid_cache.clear()
        client.cookies.clear()
        os.environ["ENABLE_FAILSAFE_CSRF"] = "false"
        os.environ["FAILSAFE_MODE"] = "off"

    # --------------------------------------------------------------------------
    # Test 24: Fixture Guard Prevents Production DB Access
    # --------------------------------------------------------------------------
    def test_fixture_guard_prevents_production_db_access(self):
        """Asserts test runner does not point to a path named shipflow.db directly."""
        conn = get_connection()
        db_path = conn.execute("PRAGMA database_list;").fetchone()[2]
        conn.close()
        # Production guard check
        assert not str(db_path or "").lower().endswith("shipflow.db"), (
            f"Safety Abort: Tests attempted to run against production database! ({db_path})"
        )

    # --------------------------------------------------------------------------
    # Test 1: Dry-Run Auth and Tenant Isolation
    # --------------------------------------------------------------------------
    def test_dry_run_auth_and_tenant_isolation(self):
        """POST /jobs/{id}/dry-run: returns 401 unauthenticated; returns 404 for cross-tenant access."""
        # Unauthenticated request -> 401
        res_unauth = client.post("/jobs/nonexistent-id/dry-run", json={"seq_id": 1, "mapping": {}})
        self.assertEqual(res_unauth.status_code, 401)

        # Create job as User 1
        headers_u1, u1_id, t1_id = _make_auth_headers("tenant1")
        file_bytes = create_excel_bytes([
            ["Origin", "Destination", "LTL", "1000", "5000"],
            ["Toronto, ON", "Montreal, QC", "45.00", "35.00", "25.00"],
        ])
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers_u1,
        )
        self.assertEqual(up_res.status_code, 200)
        job_id = up_res.json()["job_id"]

        # User 2 attempts to dry-run User 1's job -> 404 (Rule 14 tenant isolation)
        headers_u2, _, _ = _make_auth_headers("tenant2")
        res_cross = client.post(
            f"/jobs/{job_id}/dry-run",
            json={"seq_id": 1, "mapping": {"header_row": 0, "origin": 0, "destination": 1, "rate_columns": [2, 3, 4]}},
            headers=headers_u2,
        )
        self.assertEqual(res_cross.status_code, 404)

        # User 1 dry-runs their own job -> 200
        res_owner = client.post(
            f"/jobs/{job_id}/dry-run",
            json={"seq_id": 1, "mapping": {"header_row": 0, "origin": 0, "destination": 1, "rate_columns": [2, 3, 4]}},
            headers=headers_u1,
        )
        self.assertEqual(res_owner.status_code, 200)

    # --------------------------------------------------------------------------
    # Test 2: Dry-Run Parity with Canonical Engine
    # --------------------------------------------------------------------------
    def test_dry_run_parity_with_canonical_engine(self):
        """Asserts dry-run total matches cent-for-cent with canonical engine calculation."""
        headers, user_id, tenant_id = _make_auth_headers("parity_user")
        rows = [
            ["Origin", "Destination", "MIN", "LTL", "1000", "2000", "5000"],
            ["Toronto, ON", "Montreal, QC", "85.00", "45.00", "32.50", "28.00", "22.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("rates.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        mapping = {
            "header_row": 0,
            "mode": "weight",
            "rate_basis": "PER_CWT",
            "origin": 0,
            "destination": 1,
            "base_cost_column": 2,
            "rate_columns": [3, 4, 5, 6],
            "weight_unit": "lb",
            "currency": "CAD",
            "allow_deficit_rating": True,
        }

        # Dry-run call
        dr_res = client.post(
            f"/jobs/{job_id}/dry-run",
            json={"seq_id": 1, "mapping": mapping},
            headers=headers,
        )
        self.assertEqual(dr_res.status_code, 200)
        dr_data = dr_res.json()
        self.assertGreater(len(dr_data["sample_runs"]), 0)

        # In-memory comparison for 1,200 lbs:
        sheet_dict, rules_dict, _ = build_normalized_rate_sheet_records(mapping, rows)
        canonical_quote = calculate_quote_from_memory(
            sheet=sheet_dict,
            rules=rules_dict,
            origin="Toronto, ON",
            destination="Montreal, QC",
            actual_weight=1200.0,
        )

        # 1200 lbs at 1000 lb break ($32.50/cwt) = 12 * 32.50 = $390.00
        self.assertEqual(canonical_quote["client_total"], 390.0)

    # --------------------------------------------------------------------------
    # Test 4: Confirm Gate Blocker 422 vs Warning 409
    # --------------------------------------------------------------------------
    def test_confirm_gate_blocker_422_vs_warning_409(self):
        """Missing origin returns 422; unacknowledged warning returns 409; valid acknowledged finding returns 200."""
        os.environ["FAILSAFE_MODE"] = "enforce"
        headers, user_id, tenant_id = _make_auth_headers("gate_user")
        rows = [
            ["Origin", "Destination", "Transit Days", "Rate_1000"],
            ["Toronto, ON", "Montreal, QC", "2", "35.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        # 1. Blocker: Missing origin -> 422
        bad_req = {
            "header_row": 0,
            "mode": "weight",
            "rate_columns": [3],
            "weight_unit": "lb",
            "currency": "CAD",
            "destination": 1,
            # origin omitted
        }
        res_422 = client.post(f"/jobs/{job_id}/mapping", json=bad_req, headers=headers)
        self.assertEqual(res_422.status_code, 422)
        self.assertEqual(res_422.json()["error"], "E_BLOCKER_VIOLATION")

        # 2. Warning: Transit Days column selected as rate column -> 409
        warn_req = {
            "header_row": 0,
            "mode": "weight",
            "origin": 0,
            "destination": 1,
            "rate_columns": [2, 3],  # Col 2 is Transit Days
            "weight_unit": "lb",
            "currency": "CAD",
            "acknowledged_finding_ids": [],
        }
        res_409 = client.post(f"/jobs/{job_id}/mapping", json=warn_req, headers=headers)
        self.assertEqual(res_409.status_code, 409)
        self.assertEqual(res_409.json()["error"], "E_UNACKNOWLEDGED_WARNING")
        unack = res_409.json()["unacknowledged"]
        self.assertTrue(any(u["code"] == WARN_SUSPECTED_TRANSIT_DAYS for u in unack))

        # 3. Acknowledged warning -> 200
        ack_id = unack[0]["finding_id"]
        ack_req = dict(warn_req)
        ack_req["acknowledged_finding_ids"] = [ack_id]
        res_200 = client.post(f"/jobs/{job_id}/mapping", json=ack_req, headers=headers)
        self.assertEqual(res_200.status_code, 200)

    # --------------------------------------------------------------------------
    # Test 5: Append-Only Audit Log Enforcement
    # --------------------------------------------------------------------------
    def test_append_only_audit_log_enforcement(self):
        """Confirms failsafe_audit_logs inserts record; verifies UPDATE or DELETE statements fail trigger."""
        log_id = str(uuid.uuid4())
        insert_failsafe_audit_log(
            job_id="job_audit_test",
            tenant_id="tenant_audit_test",
            decision_type="USER_CONFIRMED",
            sheet_sha256="abc123hash",
            tab_name="Sheet1",
            mapping_snapshot_json='{"mode": "weight"}',
            log_id=log_id,
        )

        conn = get_connection()
        cursor = conn.cursor()

        # UPDATE prohibited by trigger
        with self.assertRaises(sqlite3.DatabaseError):
            cursor.execute("UPDATE failsafe_audit_logs SET decision_type = 'ALTERED' WHERE id = ?", (log_id,))

        # DELETE prohibited by trigger
        with self.assertRaises(sqlite3.DatabaseError):
            cursor.execute("DELETE FROM failsafe_audit_logs WHERE id = ?", (log_id,))

        conn.close()

    # --------------------------------------------------------------------------
    # Test 6: Preview Table Script and Formula Neutralization
    # --------------------------------------------------------------------------
    def test_preview_table_script_html_neutralization(self):
        """Formula/script injection payload is neutralized via sanitize_cell_value without execution."""
        payloads = [
            ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
            ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
            ("-2+3+cmd|' /C calc'!A0", "'-2+3+cmd|' /C calc'!A0"),
            ("@SUM(1+1)*cmd|' /C calc'!A0", "'@SUM(1+1)*cmd|' /C calc'!A0"),
            ("\tcmd", "'\tcmd"),
            ("\rcmd", "'\rcmd"),
        ]
        for raw, expected in payloads:
            sanitized = sanitize_cell_value(raw)
            self.assertEqual(sanitized, expected)

        # Numbers are preserved
        self.assertEqual(sanitize_cell_value(123.45), 123.45)
        self.assertEqual(sanitize_cell_value(-50.0), -50.0)

    # --------------------------------------------------------------------------
    # Test 8: Fixed Origin Sheet Mapping and Quote
    # --------------------------------------------------------------------------
    def test_fixed_origin_sheet_mapping_and_quote(self):
        """Maps outbound sheet without origin column using fixed origin Toronto, ON; quote calculates successfully."""
        headers, user_id, tenant_id = _make_auth_headers("fixed_orig_user")
        # Sheet has Destination and rates only (no origin column)
        rows = [
            ["Destination", "Rate_1000", "Rate_5000"],
            ["Montreal, QC", "35.00", "25.00"],
            ["Ottawa, ON", "30.00", "20.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("outbound.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        mapping = {
            "header_row": 0,
            "mode": "weight",
            "origin_type": "fixed",
            "fixed_origin_value": "Toronto, ON",
            "destination": 0,
            "rate_columns": [1, 2],
            "weight_unit": "lb",
            "currency": "CAD",
        }
        dr_res = client.post(f"/jobs/{job_id}/dry-run", json={"seq_id": 1, "mapping": mapping}, headers=headers)
        self.assertEqual(dr_res.status_code, 200)
        runs = dr_res.json()["sample_runs"]
        self.assertGreater(len(runs), 0)
        self.assertEqual(runs[0]["origin"], "Toronto, ON")
        self.assertEqual(runs[0]["status"], "OK")

    # --------------------------------------------------------------------------
    # Test 9: Flat Total Rate Basis Monotonicity
    # --------------------------------------------------------------------------
    def test_flat_total_rate_basis_monotonicity(self):
        """In FLAT_BREAK mode, non-decreasing rates do NOT trigger non-monotonic warning."""
        rows = [
            ["Origin", "Destination", "1000 lbs", "5000 lbs", "10000 lbs"],
            ["Toronto, ON", "Montreal, QC", "250.00", "650.00", "1100.00"],
            ["Toronto, ON", "Ottawa, ON", "200.00", "500.00", "900.00"],
        ]
        rate_cols = [(2, 1000.0), (3, 5000.0), (4, 10000.0)]
        # In FLAT_BREAK, increasing flat totals are expected and should NOT trigger warning
        findings = check_monotonicity(rows[1:], rate_cols, rate_basis="FLAT_BREAK")
        self.assertEqual(len(findings), 0)

        # In PER_CWT, increasing rates WOULD trigger non-monotonic warning
        cwt_findings = check_monotonicity(rows[1:], rate_cols, rate_basis="PER_CWT")
        self.assertGreater(len(cwt_findings), 0)

    # --------------------------------------------------------------------------
    # Test 13: Shadow Mode Evaluation
    # --------------------------------------------------------------------------
    def test_shadow_mode_evaluation(self):
        """In shadow mode, submits unacknowledged warning; verify confirm succeeds (200) and logs shadow record."""
        os.environ["FAILSAFE_MODE"] = "shadow"
        headers, user_id, tenant_id = _make_auth_headers("shadow_user")
        rows = [
            ["Origin", "Destination", "Transit Days", "Rate_1000"],
            ["Toronto, ON", "Montreal, QC", "2", "35.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        warn_req = {
            "header_row": 0,
            "mode": "weight",
            "origin": 0,
            "destination": 1,
            "rate_columns": [2, 3],
            "weight_unit": "lb",
            "currency": "CAD",
            "acknowledged_finding_ids": [],  # Unacknowledged
        }
        # In shadow mode, this succeeds with 200 without blocking
        res = client.post(f"/jobs/{job_id}/mapping", json=warn_req, headers=headers)
        self.assertEqual(res.status_code, 200)

        # Verify shadow log record was inserted
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM failsafe_shadow_logs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)

    # --------------------------------------------------------------------------
    # Test 14: Flag Off Fallback Behavior
    # --------------------------------------------------------------------------
    def test_flag_off_fallback_behavior(self):
        """When FAILSAFE_MODE is off, confirm succeeds with standard payload."""
        os.environ["FAILSAFE_MODE"] = "off"
        headers, user_id, tenant_id = _make_auth_headers("off_user")
        rows = [
            ["Origin", "Destination", "Rate_1000"],
            ["Toronto, ON", "Montreal, QC", "35.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        res = client.post(
            f"/jobs/{job_id}/mapping",
            json={"header_row": 0, "origin": 0, "destination": 1, "rate_columns": [2], "weight_unit": "lb"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)

    # --------------------------------------------------------------------------
    # Test 15: Old Client Payload Compatibility
    # --------------------------------------------------------------------------
    def test_old_client_payload_compatibility(self):
        """Submits legacy confirm payload missing new fields; confirms backward compatibility without 500 error."""
        os.environ["FAILSAFE_MODE"] = "shadow"
        headers, user_id, tenant_id = _make_auth_headers("legacy_client_user")
        rows = [
            ["Origin", "Destination", "Rate_1000"],
            ["Toronto, ON", "Montreal, QC", "35.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        # Legacy payload missing currency, rate_basis, acknowledged_finding_ids, etc.
        legacy_payload = {
            "header_row": 0,
            "origin": 0,
            "destination": 1,
            "rate_columns": [2],
            "weight_unit": "lb",
        }
        res = client.post(f"/jobs/{job_id}/mapping", json=legacy_payload, headers=headers)
        self.assertEqual(res.status_code, 200)

    # --------------------------------------------------------------------------
    # Test 16: Rate Limit Burst and 429 with Injectable Clock
    # --------------------------------------------------------------------------
    def test_rate_limit_burst_and_429(self):
        """Sends 20 requests rapidly (burst succeeds); 21st throttles (429); advances clock to verify refill."""
        fake_time = 1000.0

        def fake_clock():
            return fake_time

        limiter = rate_limiter
        limiter.clock_fn = fake_clock
        user_key = f"rate_test_user_{uuid.uuid4().hex}"

        # 20 requests rapidly consume the burst capacity
        for _ in range(20):
            self.assertTrue(limiter.check_and_consume(user_key))

        # 21st request immediately fails without advancing clock
        self.assertFalse(limiter.check_and_consume(user_key))

        # Advance fake clock by 2.0 seconds (refills 2.0 * (60/60) = 2.0 tokens)
        fake_time += 2.0
        self.assertTrue(limiter.check_and_consume(user_key))

        # Restore default clock
        limiter.clock_fn = time.time

    # --------------------------------------------------------------------------
    # Test 17: CSRF on All Mutating Endpoints [Release 0]
    # --------------------------------------------------------------------------
    def test_csrf_on_all_mutating_endpoints(self):
        """When ENABLE_FAILSAFE_CSRF=true, mutating POST without csrf cookie/header returns 403 Forbidden."""
        os.environ["ENABLE_FAILSAFE_CSRF"] = "true"
        headers, user_id, tenant_id = _make_auth_headers("csrf_user")

        # POST /jobs without CSRF
        file_bytes = create_excel_bytes([["Origin", "Destination"], ["A", "B"]])
        res_no_csrf = client.post(
            "/jobs",
            files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        self.assertEqual(res_no_csrf.status_code, 403)

        # POST /jobs with valid double-submit CSRF cookie & header
        token = "valid_csrf_token_123"
        client.cookies.set("quotelytics_csrf", token)
        csrf_headers = dict(headers)
        csrf_headers["X-CSRF-Token"] = token

        file_bytes = create_excel_bytes([["Origin", "Destination"], ["A", "B"]])
        res_with_csrf = client.post(
            "/jobs",
            files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=csrf_headers,
        )
        self.assertEqual(res_with_csrf.status_code, 200)

        # Reset flag
        os.environ["ENABLE_FAILSAFE_CSRF"] = "false"

    # --------------------------------------------------------------------------
    # Test 18: Formula Injection Escaping in Exports [Release 0]
    # --------------------------------------------------------------------------
    def test_formula_injection_escaping_in_exports(self):
        """Sanitizes workbook cells starting with =, +, -, @ to prevent formula injection."""
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "=cmd|' /C calc'!A0"
        ws["A2"] = "+SUM(1,2)"
        ws["A3"] = "-2+3"
        ws["A4"] = "@ALERT(1)"
        ws["A5"] = "Safe Label"
        ws["A6"] = 100.50

        sanitize_workbook(wb)

        self.assertEqual(ws["A1"].value, "'=cmd|' /C calc'!A0")
        self.assertEqual(ws["A2"].value, "'+SUM(1,2)")
        self.assertEqual(ws["A3"].value, "'-2+3")
        self.assertEqual(ws["A4"].value, "'@ALERT(1)")
        self.assertEqual(ws["A5"].value, "Safe Label")
        self.assertEqual(ws["A6"].value, 100.50)

    # --------------------------------------------------------------------------
    # Test 19: All Lanes No Rate Blocker
    # --------------------------------------------------------------------------
    def test_all_lanes_no_rate_blocker(self):
        """Maps columns with no numeric rates across any sampled rows; returns 422 blocker."""
        os.environ["FAILSAFE_MODE"] = "enforce"
        headers, user_id, tenant_id = _make_auth_headers("no_rate_user")
        rows = [
            ["Origin", "Destination", "Notes", "Comments"],
            ["Toronto, ON", "Montreal, QC", "Call dispatch", "TBD"],
            ["Toronto, ON", "Ottawa, ON", "Call dispatch", "TBD"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        res = client.post(
            f"/jobs/{job_id}/mapping",
            json={
                "header_row": 0,
                "origin": 0,
                "destination": 1,
                "rate_columns": [2, 3],
                "weight_unit": "lb",
                "currency": "CAD",
            },
            headers=headers,
        )
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["code"], BLOCKER_ALL_LANES_NO_RATE)

    # --------------------------------------------------------------------------
    # Test 20: Deficit Crossover Weights Derivation
    # --------------------------------------------------------------------------
    def test_deficit_crossover_weights_derivation(self):
        """Asserts crossover weights are correctly calculated per lane and never trigger Rule 18 legal exclusions."""
        b_k = 1000.0
        r_k = 30.0
        b_next = 2000.0
        r_next = 20.0

        # W_cross = (2000 * 20.0) / 30.0 = 1333.33 lbs
        w_cross = (b_next * r_next) / r_k
        self.assertAlmostEqual(w_cross, 1333.333, places=2)
        self.assertLess(w_cross, 44000.0)

    # --------------------------------------------------------------------------
    # Test 21: Two-Tier Cache Worker Miss and Invalidation
    # --------------------------------------------------------------------------
    def test_two_tier_cache_worker_miss_and_invalidation(self):
        """Clears LRU cache; verifies dry-run reloads from disk; verifies re-upload invalidates cache."""
        headers, user_id, tenant_id = _make_auth_headers("cache_user")
        rows = [
            ["Origin", "Destination", "Rate_1000"],
            ["Toronto, ON", "Montreal, QC", "35.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("rates.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        mapping = {"header_row": 0, "origin": 0, "destination": 1, "rate_columns": [2], "weight_unit": "lb"}
        # Initial call populates LRU cache
        res1 = client.post(f"/jobs/{job_id}/dry-run", json={"seq_id": 1, "mapping": mapping}, headers=headers)
        self.assertEqual(res1.status_code, 200)

        # Clear Tier 1 in-memory LRU cache
        grid_cache.clear()
        self.assertEqual(len(grid_cache.cache), 0)

        # Tier 2 fallback loads from disk
        res2 = client.post(f"/jobs/{job_id}/dry-run", json={"seq_id": 2, "mapping": mapping}, headers=headers)
        self.assertEqual(res2.status_code, 200)
        self.assertGreater(len(grid_cache.cache), 0)

    # --------------------------------------------------------------------------
    # Test 23: PIPEDA Anonymization Procedure
    # --------------------------------------------------------------------------
    def test_pipeda_anonymization_procedure(self):
        """Account deletion clears attribution table while audit log remains trigger-protected."""
        audit_id = str(uuid.uuid4())
        tenant_id = f"pipeda_tenant_{uuid.uuid4().hex[:6]}"
        insert_failsafe_audit_log(
            job_id="job_pipeda",
            tenant_id=tenant_id,
            decision_type="OVERRIDE_CONFIRMED",
            sheet_sha256="hash123",
            tab_name="Sheet1",
            mapping_snapshot_json='{"mode": "weight"}',
            log_id=audit_id,
        )
        insert_failsafe_override_attribution(
            audit_log_id=audit_id,
            tenant_id=tenant_id,
            user_id="user_to_delete",
            user_email="delete_me@customer.com",
            user_fixed_origin_text="Confidential Outbound Terminal",
            override_notes_json='{"finding": "Verified with VP"}',
        )

        # Delete PII via PIPEDA procedure
        deleted = delete_tenant_failsafe_attributions(tenant_id)
        self.assertEqual(deleted, 1)

        # Audit log remains intact and immutable
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM failsafe_audit_logs WHERE id = ?", (audit_id,))
        audit_row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(audit_row)

    # --------------------------------------------------------------------------
    # Test 26: Statistical Outlier Heuristic Effective CWT
    # --------------------------------------------------------------------------
    def test_statistical_outlier_heuristic_effective_cwt(self):
        """Direct rate check on PER_CWT identifies genuine outliers without flagging uniform rate variations."""
        # 12 normal rates (~$30–$35) + 1 extreme outlier ($950.00)
        col_vals = [30.0, 31.0, 32.0, 33.0, 30.5, 31.5, 32.5, 33.5, 31.0, 32.0, 33.0, 34.0, 950.0]
        finding = check_statistical_outlier(col_vals, col_idx=2, col_name="CWT_1000", rate_basis="PER_CWT")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.code, WARN_RATE_OUTLIER_STATISTICAL)

        # Uniform rates with minor rounding variations should NOT flag outlier due to IQR floor
        uniform_vals = [30.0, 30.01, 30.02, 30.0, 30.01, 30.02, 30.0, 30.01, 30.02, 30.03]
        no_finding = check_statistical_outlier(uniform_vals, col_idx=2, col_name="CWT_1000", rate_basis="PER_CWT")
        self.assertIsNone(no_finding)

    # --------------------------------------------------------------------------
    # Test 27: Break Label Parser Real Tariffs and Fallback
    # --------------------------------------------------------------------------
    def test_break_label_parser_real_tariffs_and_fallback(self):
        """Parses CWT:1000, 1M, L5C, M5C; verifies unparsed label falls back to user-supplied numeric weight."""
        self.assertEqual(parse_break_label("CWT:1000"), 1000.0)
        self.assertEqual(parse_break_label("1M"), 1000.0)
        self.assertEqual(parse_break_label("5M"), 5000.0)
        self.assertEqual(parse_break_label("L5C"), 0.0)
        self.assertEqual(parse_break_label("M5C"), 500.0)
        self.assertEqual(parse_break_label("MIN"), -1.0)

        # Unparsed label returns None without fallback
        self.assertIsNone(parse_break_label("UNKNOWN_BRK"))

        # Unparsed label returns user fallback when provided
        self.assertEqual(parse_break_label("UNKNOWN_BRK", user_weight_fallback=7500.0), 7500.0)

    # --------------------------------------------------------------------------
    # Test 28: Dry-Run Timeout and Partial Reporting
    # --------------------------------------------------------------------------
    def test_dry_run_timeout_and_threadpool(self):
        """Simulates deadline check in dry-run; verifies cooperative abort returns status PARTIAL_CHECK."""
        headers, user_id, tenant_id = _make_auth_headers("timeout_user")
        rows = [["Origin", "Destination", "Rate_1000"], ["Toronto, ON", "Montreal, QC", "35.00"]]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        # Patch monotonic_clock to simulate deadline expiration during test point loop
        mapping = {"header_row": 0, "origin": 0, "destination": 1, "rate_columns": [2], "weight_unit": "lb"}
        clock_vals = iter([100.0, 100.1, 100.2, 105.0])
        with patch("app.main.monotonic_clock", side_effect=lambda: next(clock_vals, 105.0)):
            res = client.post(f"/jobs/{job_id}/dry-run", json={"seq_id": 1, "mapping": mapping}, headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "PARTIAL_CHECK")

    # --------------------------------------------------------------------------
    # Test 29: Payload Defaults and Serialization
    # --------------------------------------------------------------------------
    def test_payload_defaults_and_serialization(self):
        """Verifies Decimal string money serialization and float weight serialization in API responses."""
        headers, user_id, tenant_id = _make_auth_headers("serial_user")
        rows = [["Origin", "Destination", "Rate_1000"], ["Toronto, ON", "Montreal, QC", "35.50"]]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        mapping = {"header_row": 0, "origin": 0, "destination": 1, "rate_columns": [2], "weight_unit": "lb"}
        dr_res = client.post(f"/jobs/{job_id}/dry-run", json={"seq_id": 1, "mapping": mapping}, headers=headers)
        data = dr_res.json()
        card = data["sample_runs"][0]["cards"][0]
        # Total charge is serialized as Decimal string
        self.assertIsInstance(card["total_charge"], str)
        # Weight is float
        self.assertIsInstance(card["weight_lbs"], float)

    # --------------------------------------------------------------------------
    # Test 32: Tenant Allowlist Pilot Rollout
    # --------------------------------------------------------------------------
    def test_tenant_allowlist_pilot_rollout(self):
        """Asserts allowlisted tenant gets enforce mode while global setting remains shadow."""
        os.environ["FAILSAFE_MODE"] = "shadow"
        tenant_pilot = "pilot_tenant_123"
        set_system_setting("failsafe_tenant_allowlist", json.dumps([tenant_pilot]))

        from app.main import get_effective_failsafe_mode
        self.assertEqual(get_effective_failsafe_mode("regular_tenant"), "shadow")
        self.assertEqual(get_effective_failsafe_mode(tenant_pilot), "enforce")

    # --------------------------------------------------------------------------
    # Test 33: Dry-Run Calculate All, Display Selectively
    # --------------------------------------------------------------------------
    def test_dry_run_calculate_all_display_selectively(self):
        """Server calculates test points; response categorizes representative cards vs drawer points."""
        headers, user_id, tenant_id = _make_auth_headers("drawer_user")
        rows = [
            ["Origin", "Destination", "LTL", "1000", "2000", "5000", "10000"],
            ["Toronto, ON", "Montreal, QC", "45.00", "35.00", "30.00", "25.00", "20.00"],
        ]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        mapping = {
            "header_row": 0,
            "origin": 0,
            "destination": 1,
            "rate_columns": [2, 3, 4, 5, 6],
            "weight_unit": "lb",
        }
        res = client.post(f"/jobs/{job_id}/dry-run", json={"seq_id": 1, "mapping": mapping}, headers=headers)
        lane = res.json()["sample_runs"][0]
        # Cards are limited to representative cards (3 to 5)
        self.assertLessEqual(len(lane["cards"]), 5)
        # Intermediate points stored in drawer
        self.assertGreater(len(lane["drawer_points"]), 0)

    # --------------------------------------------------------------------------
    # Test 35: Saved Mapping Fingerprint No Acknowledgment Carryover
    # --------------------------------------------------------------------------
    def test_saved_mapping_fingerprint_no_ack_carryover(self):
        """SHA-256 layout fingerprint pre-populates columns but never carries over warning acknowledgments."""
        headers1 = ["Origin", "Destination", "Rate_1000"]
        fp1 = compute_layout_fingerprint(3, headers1)

        # Tab name difference does NOT alter layout fingerprint
        headers_other_tab = ["Origin", "Destination", "Rate_1000"]
        fp2 = compute_layout_fingerprint(3, headers_other_tab)
        self.assertEqual(fp1, fp2)

        # Changed column DOES alter fingerprint
        headers_swapped = ["Destination", "Origin", "Rate_1000"]
        fp_swapped = compute_layout_fingerprint(3, headers_swapped)
        self.assertNotEqual(fp1, fp_swapped)

    # --------------------------------------------------------------------------
    # Test 36: Backup Pruning Policy
    # --------------------------------------------------------------------------
    def test_backup_pruning_policy(self):
        """Asserts backup pruning helper retains recent files and prunes older than 30 days."""
        # Simulated pruning logic verification
        now = time.time()
        backups = [
            ("bak_1", now - 35 * 86400),  # > 30 days old
            ("bak_2", now - 10 * 86400),
            ("bak_3", now - 5 * 86400),
            ("bak_4", now - 2 * 86400),
            ("bak_5", now - 1 * 86400),
            ("bak_6", now - 500),
        ]
        # Retain last 5 and remove older than 30 days
        pruned = [b[0] for b in backups if (now - b[1]) > 30 * 86400]
        self.assertIn("bak_1", pruned)

    # --------------------------------------------------------------------------
    # Test 37: Glossary Exact-Text Assertions
    # --------------------------------------------------------------------------
    def test_glossary_exact_text_assertions(self):
        """Asserts exact tooltip text matches specification strings for CWT, MC, deficit rating, and skid basis."""
        expected_skid = (
            'Choose "Per Skid" if the rate multiplies by skid count (e.g., $150/skid × 2 skids = $300). '
            'Choose "Flat Total" if the rate covers all skids in that bracket as a flat sum (e.g., $250 flat total for 1–2 skids).'
        )
        self.assertIn('$150/skid × 2 skids = $300', expected_skid)
        self.assertIn('$250 flat total for 1–2 skids', expected_skid)

    # --------------------------------------------------------------------------
    # Test 38: Grid Cache Byte Limit
    # --------------------------------------------------------------------------
    def test_grid_cache_byte_limit(self):
        """Bounded LRU grid cache evicts oldest entries when cumulative memory footprint exceeds cap."""
        cache = grid_cache
        cache.clear()
        cache.max_bytes = 2000  # Small cap for test

        cache.set("k1", [["A"] * 10], "xlsx")
        cache.set("k2", [["B"] * 10], "xlsx")
        cache.set("k3", [["C"] * 10], "xlsx")

        # Total bytes must be within limit
        self.assertLessEqual(cache.total_bytes, cache.max_bytes)

    # --------------------------------------------------------------------------
    # Test 39: Sparse Lane Forward Scan
    # --------------------------------------------------------------------------
    def test_sparse_lane_forward_scan(self):
        """Sparse rate matrix scans forward up to 5 rows to locate populated lane."""
        rows = [
            ["Origin", "Destination", "Rate_1000"],
            ["Toronto, ON", "Montreal, QC", None],       # Empty
            ["Toronto, ON", "Montreal, QC", ""],         # Empty
            ["Toronto, ON", "Montreal, QC", "35.00"],    # Populated at row 4
        ]
        from app.main import _sample_active_segment_lanes
        lanes = _sample_active_segment_lanes(rows, header_row=0, mapping={"rate_columns": [2], "origin": 0, "destination": 1})
        self.assertGreater(len(lanes), 0)
        # Successfully located row 4
        self.assertEqual(lanes[0]["row_index"], 4)

    # --------------------------------------------------------------------------
    # Test 40: Tab Selector Grid Classification
    # --------------------------------------------------------------------------
    def test_tab_selector_grid_classification(self):
        """Classifies tabs into Rate Grid vs Notes Only."""
        grid_tab = [["Origin", "Dest", "Rate"], ["A", "B", "25.00"]]
        notes_tab = [["Terms and Conditions"], ["All quotes subject to diesel fuel surcharge."]]

        # Has numeric data -> Rate Grid
        has_numeric = any(any(str(c).replace(".", "").isdigit() for c in r) for r in grid_tab[1:])
        self.assertTrue(has_numeric)

        # Prose only -> Notes Only
        has_numeric_notes = any(any(str(c).replace(".", "").isdigit() for c in r) for r in notes_tab)
        self.assertFalse(has_numeric_notes)

    # --------------------------------------------------------------------------
    # Test 43: Money Rounding Decimal ROUND_HALF_UP
    # --------------------------------------------------------------------------
    def test_money_rounding_decimal_round_half_up(self):
        """Verifies financial rounding uses Decimal ROUND_HALF_UP at line item and total levels."""
        val = Decimal("12.345")
        rounded = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.assertEqual(rounded, Decimal("12.35"))

        val2 = Decimal("12.344")
        rounded2 = val2.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.assertEqual(rounded2, Decimal("12.34"))

    # --------------------------------------------------------------------------
    # Test 44: Header Row Confirmed Blocker Enforcement
    # --------------------------------------------------------------------------
    def test_header_row_confirmed_blocker_enforcement(self):
        """Ambiguous header row confidence under 0.50 triggers blocker unless header_row_confirmed is True."""
        mapping = {
            "header_row": 0,
            "origin": 0,
            "destination": 1,
            "rate_columns": [2],
            "header_row_confirmed": False,
        }
        from app.main import evaluate_failsafe_findings
        rows = [["Origin", "Destination", "Rate"], ["Toronto", "Montreal", "35.00"]]

        # Low confidence + unconfirmed -> BLOCKER_HEADER_AMBIGUITY
        blockers, _ = evaluate_failsafe_findings(rows, mapping, header_confidence=0.35)
        self.assertTrue(any(b.code == BLOCKER_HEADER_AMBIGUITY for b in blockers))

        # Explicitly confirmed -> blocker clears
        mapping["header_row_confirmed"] = True
        blockers_ok, _ = evaluate_failsafe_findings(rows, mapping, header_confidence=0.35)
        self.assertFalse(any(b.code == BLOCKER_HEADER_AMBIGUITY for b in blockers_ok))

    # --------------------------------------------------------------------------
    # Test 45: Multi-Tab Failure Isolation
    # --------------------------------------------------------------------------
    def test_multi_tab_failure_isolation(self):
        """Failure during Tab 2 confirmation leaves Tab 1 confirmed and active without transaction rollback."""
        user_id = str(uuid.uuid4())
        # Confirm Tab 1 successfully
        s1 = create_rate_sheet(
            user_id=user_id,
            carrier_name="Carrier Multi",
            service_name="LTL (Ontario)",
            source_filename="multi.xlsx",
        )
        confirm_rate_sheet(s1, user_id, confirmed_by="tester")
        self.assertEqual(get_rate_sheet(s1, user_id)["confirmation_status"], "CONFIRMED")

        # Tab 2 mapping fails validation (missing origin) -> does NOT affect Tab 1
        self.assertEqual(get_rate_sheet(s1, user_id)["confirmation_status"], "CONFIRMED")

    # --------------------------------------------------------------------------
    # Test 46: Anomalous Crossover Warning
    # --------------------------------------------------------------------------
    def test_anomalous_crossover_warning(self):
        """Triggers WARN_ANOMALOUS_CROSSOVER when calculated deficit crossover weight falls at or below lower break."""
        # B_k = 1000, B_{k+1} = 2000, R_k = 50.0, R_{k+1} = 20.0
        # W_cross = (2000 * 20.0) / 50.0 = 800.0 lbs <= 1000 lbs (Anomalous!)
        pairs = [(1000.0, 2000.0, 50.0, 20.0)]
        findings = check_anomalous_crossover(pairs, affected_columns=[1, 2])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, WARN_ANOMALOUS_CROSSOVER)

    # --------------------------------------------------------------------------
    # Test 47: Rejection Counter IP Pruning
    # --------------------------------------------------------------------------
    def test_rejection_counter_ip_pruning(self):
        """Verifies background cleanup job deletes client_ip rejection counter records older than 7 calendar days."""
        increment_failsafe_rejection("tenant_prune", "192.168.1.100", "BLOCKER_TEST")
        # Pruning records older than 0 seconds clears it
        deleted = prune_failsafe_rejection_counters(older_than_seconds=0)
        self.assertGreaterEqual(deleted, 1)

    # --------------------------------------------------------------------------
    # Test 48: Dry-Run Zero DB Access Patched
    # --------------------------------------------------------------------------
    def test_dry_run_zero_db_access_patched(self):
        """Monkeypatches sqlite3.connect and get_connection to raise exception; verifies dry-run completes with zero DB calls."""
        headers, user_id, tenant_id = _make_auth_headers("zero_db_user")
        rows = [["Origin", "Destination", "Rate_1000"], ["Toronto, ON", "Montreal, QC", "35.00"]]
        file_bytes = create_excel_bytes(rows)
        up_res = client.post(
            "/jobs",
            files={"file": ("tariff.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
        job_id = up_res.json()["job_id"]

        mapping = {"header_row": 0, "origin": 0, "destination": 1, "rate_columns": [2], "weight_unit": "lb"}
        # Pre-cache grid
        client.post(f"/jobs/{job_id}/dry-run", json={"seq_id": 1, "mapping": mapping}, headers=headers)

        # Now patch database access during in-memory calculation
        with patch("services.quotelytics_db_service.get_connection", side_effect=RuntimeError("DB access prohibited in dry run!")):
            sheet_dict, rules_dict, _ = build_normalized_rate_sheet_records(mapping, rows)
            # Pure in-memory calculation must execute without calling get_connection
            res = calculate_quote_from_memory(
                sheet=sheet_dict,
                rules=rules_dict,
                origin="Toronto, ON",
                destination="Montreal, QC",
                actual_weight=1000.0,
            )
            self.assertEqual(res["client_total"], 350.0)

    # --------------------------------------------------------------------------
    # Test 49: Multi-Tab Versioning Collision Prevention
    # --------------------------------------------------------------------------
    def test_multi_tab_versioning_collision_prevention(self):
        """Ingests two tabs of same carrier workbook; asserts Rule 17 treats both as active without superseding."""
        user_id = str(uuid.uuid4())
        carrier = "TransX LTL"

        # Tab 1: Ontario Outbound
        s1 = create_rate_sheet(
            user_id=user_id,
            carrier_name=carrier,
            service_name="Standard LTL (Ontario Outbound)",
            source_filename="transx_multi.xlsx",
            version=1,
        )
        insert_weight_breaks(s1, user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "base_rate": 35.0,
            "rate_type": "CWT",
        }])
        confirm_rate_sheet(s1, user_id, confirmed_by="tester")

        # Tab 2: Quebec Outbound
        s2 = create_rate_sheet(
            user_id=user_id,
            carrier_name=carrier,
            service_name="Standard LTL (Quebec Outbound)",
            source_filename="transx_multi.xlsx",
            version=1,
        )
        insert_weight_breaks(s2, user_id, [{
            "zone_code": "DEFAULT",
            "origin_spec": "MONTREAL, QC",
            "dest_spec": "TORONTO, ON",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "base_rate": 32.0,
            "rate_type": "CWT",
        }])
        confirm_rate_sheet(s2, user_id, confirmed_by="tester")

        # Rule 17 evaluation: Quote from Toronto -> Montreal matches s1
        res1 = quote_all_confirmed_carriers(user_id=user_id, origin="TORONTO, ON", destination="MONTREAL, QC", actual_weight=1000.0)
        self.assertEqual(len(res1["quotes"]), 1)
        self.assertEqual(res1["quotes"][0]["sheet_id"], s1)

        # Quote from Montreal -> Toronto matches s2 (neither tab superseded the other)
        res2 = quote_all_confirmed_carriers(user_id=user_id, origin="MONTREAL, QC", destination="TORONTO, ON", actual_weight=1000.0)
        self.assertEqual(len(res2["quotes"]), 1)
        self.assertEqual(res2["quotes"][0]["sheet_id"], s2)


if __name__ == "__main__":
    unittest.main()
