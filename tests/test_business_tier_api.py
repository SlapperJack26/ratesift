"""
tests/test_business_tier_api.py
Comprehensive automated verification suite for the Business Tier Embedded Quoting API & Webhooks Hardening Plan:
1. SHA-256 API key hashing at rest, prefix listing, and instant revocation
2. Active BUSINESS tier gating & immediate downgrade cutoff (403 E_API_TIER_REQUIRED)
3. X-API-Key support on POST /api/quotelytics/quotes/calculate + last_used_at tracking
4. Deterministic LTL tariff batch quoting (canonical & legacy aliases, Decimal ROUND_HALF_UP markup, zero synthetic fallback)
5. Missing field validation (HTTP 422) & Release 2a/2b dual-signal parcel sunset compliance on batch quotes
6. Least-privilege auth scope (API keys rejected on account mutation routes) & per-key rate limiting (HTTP 429)
7. SSRF-hardened webhook URL/DNS validation & HMAC-SHA256 signed batch.quote.completed background delivery
8. Console Developer API UI (panel-api) & synced https://quotelytics.ca documentation
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import time
from typing import Dict, List, Tuple
import unittest
import uuid

from fastapi.testclient import TestClient

import main
from main import app as full_app
from services.auth_service import register_and_create_session
from services.db_service import (
    delete_user_account_data,
    get_connection,
    update_user_tier,
)
from services.quotelytics_db_service import (
    confirm_rate_sheet,
    create_rate_sheet,
    insert_carrier_surcharges,
    insert_weight_breaks,
    set_system_setting,
)
from services import webhook_service

client = TestClient(full_app)
BASE_DIR = Path(__file__).resolve().parent.parent


def _register_tenant(tier: str = "BUSINESS", prefix: str = "biz_api") -> Tuple[Dict[str, str], str]:
    user, token = register_and_create_session(
        name=f"Dispatcher {prefix}",
        email=f"{prefix}.{uuid.uuid4().hex[:8]}@quotelytics-test.ca",
        company=f"FreightCorp {prefix}",
        origin_zip="TORONTO, ON",
        password="StrongTestPassword2026!",
    )
    uid = str(user["id"])
    update_user_tier(uid, tier)
    return {"Authorization": f"Bearer {token}"}, uid


def _seed_confirmed_ltl_sheet(
    user_id: str,
    carrier_name: str = "Polaris LTL",
    service_name: str = "Direct LTL",
    cwt_rate_mtl: float = 35.50,
    cwt_rate_cgy: float = 62.25,
) -> str:
    sheet_id = create_rate_sheet(
        user_id=user_id,
        carrier_name=carrier_name,
        service_name=service_name,
        currency="CAD",
        version=1,
    )
    insert_weight_breaks(
        sheet_id,
        user_id,
        [
            {
                "zone_code": "ON_QC",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 0.0,
                "max_weight": 99999.0,
                "base_rate": cwt_rate_mtl,
                "break_name": "LTL",
                "rate_type": "CWT",
                "source_cell": "Rates!B12",
            },
            {
                "zone_code": "ON_AB",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "CALGARY, AB",
                "min_weight": 0.0,
                "max_weight": 99999.0,
                "base_rate": cwt_rate_cgy,
                "break_name": "LTL",
                "rate_type": "CWT",
                "source_cell": "Rates!C19",
            },
        ],
    )
    insert_carrier_surcharges(
        sheet_id,
        user_id,
        [
            {
                "surcharge_code": "TAILGATE",
                "name": "Tailgate Delivery",
                "condition_type": "tailgate",
                "fee_type": "FLAT",
                "amount": 75.00,
                "source_cell": "Accessorials!B4",
            }
        ],
    )
    confirm_rate_sheet(sheet_id, user_id, "QA Auditor")
    return sheet_id


class TestBusinessTierAPIHardening(unittest.TestCase):

    def setUp(self):
        self._created_users: List[str] = []
        os.environ["FAILSAFE_PARCEL_STRICT"] = "false"
        main.sunset_clock = time.time
        main.api_key_rate_limiter.buckets.clear()
        webhook_service.webhook_transport = None
        webhook_service.dns_resolver = None

    def tearDown(self):
        os.environ["FAILSAFE_PARCEL_STRICT"] = "false"
        main.sunset_clock = time.time
        main.api_key_rate_limiter.buckets.clear()
        webhook_service.webhook_transport = None
        webhook_service.dns_resolver = None
        for uid in self._created_users:
            try:
                delete_user_account_data(uid, immediate_purge=True)
            except Exception:
                pass

    def _new_user(self, tier: str = "BUSINESS", prefix: str = "biz") -> Tuple[Dict[str, str], str]:
        headers, uid = _register_tenant(tier=tier, prefix=prefix)
        self._created_users.append(uid)
        return headers, uid

    # ------------------------------------------------------------------
    # 1. API Key Lifecycle: SHA-256 Hashing at Rest & Instant Revocation
    # ------------------------------------------------------------------
    def test_api_key_lifecycle_hash_storage_and_revocation(self):
        session_headers, uid = self._new_user("BUSINESS", "key_life")
        _seed_confirmed_ltl_sheet(uid)

        gen_res = client.post(
            "/api/user/api-key/generate",
            json={"name": "WMS Production Key"},
            headers=session_headers,
        )
        self.assertEqual(gen_res.status_code, 200)
        gen_body = gen_res.json()
        raw_key = gen_body["api_key"]
        key_id = gen_body["id"]
        self.assertTrue(raw_key.startswith("ql_live_"))
        self.assertEqual(gen_body["key_prefix"], f"{raw_key[:16]}...")

        # Verify raw secret is NEVER stored in SQLite (only SHA-256 hash + REDACTED placeholder)
        expected_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        conn = get_connection()
        row = conn.execute("SELECT key, key_hash, key_prefix FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["key"], raw_key)
        self.assertTrue(row["key"].startswith("REDACTED_"))
        self.assertEqual(row["key_hash"], expected_hash)

        # Listing keys exposes prefix & metadata, never raw secret or hash
        list_res = client.get("/api/user/api-keys", headers=session_headers)
        self.assertEqual(list_res.status_code, 200)
        list_body = list_res.json()
        self.assertTrue(list_body["has_api_access"])
        self.assertEqual(len(list_body["keys"]), 1)
        self.assertEqual(list_body["keys"][0]["id"], key_id)
        self.assertNotIn("api_key", list_body["keys"][0])
        self.assertNotIn("key_hash", list_body["keys"][0])
        self.assertNotIn(raw_key, json.dumps(list_body))

        # Revoke key and verify immediate 401 E_API_KEY_INVALID on batch endpoint
        rev_res = client.delete(f"/api/user/api-keys/{key_id}", headers=session_headers)
        self.assertEqual(rev_res.status_code, 200)
        self.assertEqual(rev_res.json()["status"], "revoked")

        batch_res = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 1000.0, "skid_count": 2}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(batch_res.status_code, 401)
        self.assertEqual(batch_res.json()["error"], "E_API_KEY_INVALID")

    # ------------------------------------------------------------------
    # 2. Tier Gating & Downgrade Immediately Cuts Off API Key Access
    # ------------------------------------------------------------------
    def test_tier_gating_and_downgrade_revokes_access(self):
        for non_biz_tier in ("FREE", "PRO", "TEAM"):
            hdrs, _ = self._new_user(non_biz_tier, f"tier_{non_biz_tier.lower()}")
            res = client.post("/api/user/api-key/generate", json={"name": "Blocked Key"}, headers=hdrs)
            self.assertEqual(res.status_code, 403)
            # Non-business session is also blocked from /api/v1/quotes/batch
            b_res = client.post(
                "/api/v1/quotes/batch",
                json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 500.0, "skid_count": 1}]},
                headers=hdrs,
            )
            self.assertEqual(b_res.status_code, 403)
            self.assertEqual(b_res.json()["error"], "E_API_TIER_REQUIRED")

        # Create active BUSINESS account, generate working key, then downgrade to TEAM
        biz_hdrs, biz_uid = self._new_user("BUSINESS", "downgrade_check")
        _seed_confirmed_ltl_sheet(biz_uid)
        raw_key = client.post("/api/user/api-key/generate", data={"name": "ERP Key"}, headers=biz_hdrs).json()["api_key"]

        ok_res = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 1000.0, "skid_count": 2}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(ok_res.status_code, 200)

        # Downgrade to TEAM -> existing unrevoked API key immediately receives 403 E_API_TIER_REQUIRED
        update_user_tier(biz_uid, "TEAM")
        blocked_batch = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 1000.0, "skid_count": 2}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(blocked_batch.status_code, 403)
        self.assertEqual(blocked_batch.json()["error"], "E_API_TIER_REQUIRED")

        blocked_single = client.post(
            "/api/quotelytics/quotes/calculate",
            json={"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 1000.0, "skid_count": 2},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(blocked_single.status_code, 403)
        self.assertEqual(blocked_single.json()["error"], "E_API_TIER_REQUIRED")

    # ------------------------------------------------------------------
    # 3. Single Deterministic Quote Endpoint Accepts X-API-Key
    # ------------------------------------------------------------------
    def test_single_quote_endpoint_accepts_x_api_key(self):
        session_headers, uid = self._new_user("BUSINESS", "single_key")
        _seed_confirmed_ltl_sheet(uid, cwt_rate_mtl=42.00)
        gen = client.post("/api/user/api-key/generate", json={"name": "Portal Key"}, headers=session_headers).json()
        raw_key = gen["api_key"]

        # Call /api/quotelytics/quotes/calculate with ONLY X-API-Key (no session cookie / Bearer token)
        res = client.post(
            "/api/quotelytics/quotes/calculate",
            json={
                "origin": "TORONTO, ON",
                "destination": "MONTREAL, QC",
                "actual_weight": 1500.0,
                "skid_count": 3,
                "accessorials": ["TAILGATE"],
            },
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["total_options"], 1)
        # 15 CWT * $42.00 = $630.00 + $75.00 tailgate = $705.00
        self.assertEqual(body["quotes"][0]["final_total"], 705.00)
        self.assertEqual(body["quotes"][0]["source_coordinate"], "Rates!B12")

        # Verify last_used_at was populated
        keys_meta = client.get("/api/user/api-keys", headers=session_headers).json()["keys"]
        self.assertIsNotNone(keys_meta[0]["last_used_at"])

    # ------------------------------------------------------------------
    # 4. Batch Quotes Uses Confirmed LTL Sheets, Penny-Exact Decimal Markup, & Zero Synthetic Fallback
    # ------------------------------------------------------------------
    def test_batch_quotes_uses_confirmed_ltl_sheets_not_synthetic(self):
        session_headers, uid = self._new_user("BUSINESS", "batch_det")
        set_res = client.post(
            "/api/settings/update",
            data={"currency": "CAD", "units": "lbs", "markup_pct": 12.5, "auto_detect_headers": 1, "skip_blank_rows": 1},
            headers=session_headers,
        )
        self.assertEqual(set_res.status_code, 200)
        raw_key = client.post("/api/user/api-key/generate", json={"name": "Batch Key"}, headers=session_headers).json()["api_key"]

        # Step A: Before any sheet is uploaded -> Rule 1 zero synthetic fallback ("no_qualifying_carrier")
        empty_res = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 1000.0, "skid_count": 2}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(empty_res.status_code, 200)
        empty_body = empty_res.json()
        self.assertEqual(empty_body["quoted_count"], 0)
        self.assertEqual(empty_body["unmatched_count"], 1)
        self.assertEqual(empty_body["quotes"][0]["status"], "no_qualifying_carrier")
        self.assertIsNone(empty_body["quotes"][0]["final_rate"])
        self.assertEqual(empty_body["quotes"][0]["carrier_options"], [])

        # Step B: Confirm deterministic LTL sheet and test canonical + legacy alias items + unserved lane
        _seed_confirmed_ltl_sheet(uid, cwt_rate_mtl=33.33, cwt_rate_cgy=50.00)
        batch_res = client.post(
            "/api/v1/quotes/batch",
            json={
                "apply_markup": True,
                "shipments": [
                    # Item 1 (canonical keys): 10 CWT * 33.33 = 333.30 + 75.00 = 408.30; * 1.125 = 459.3375 -> 459.34 (ROUND_HALF_UP)
                    {
                        "origin": "TORONTO, ON",
                        "destination": "MONTREAL, QC",
                        "actual_weight": 1000.0,
                        "skid_count": 2,
                        "accessorials": ["TAILGATE"],
                    },
                    # Item 2 (legacy keys + default origin fallback): 20 CWT * 50.00 = 1000.00; * 1.125 = 1125.00
                    {
                        "dest_zip": "CALGARY, AB",
                        "weight_lbs": 2000.0,
                        "skids": 4,
                        "service": "Direct LTL",
                    },
                    # Item 3 (unserved lane -> no synthetic fallback)
                    {
                        "origin": "TORONTO, ON",
                        "destination": "HALIFAX, NS",
                        "actual_weight": 1200.0,
                        "skid_count": 2,
                    },
                ],
            },
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(batch_res.status_code, 200)
        b = batch_res.json()
        self.assertEqual(b["total_quotes"], 3)
        self.assertEqual(b["quoted_count"], 2)
        self.assertEqual(b["unmatched_count"], 1)

        q1, q2, q3 = b["quotes"]
        self.assertEqual(q1["status"], "quoted")
        self.assertEqual(q1["base_rate"], 408.30)
        self.assertEqual(q1["markup_pct"], 12.5)
        self.assertEqual(q1["final_rate"], 459.34)
        self.assertEqual(q1["coordinate"], "Rates!B12")

        self.assertEqual(q2["status"], "quoted")
        self.assertEqual(q2["origin"], "TORONTO, ON")
        self.assertEqual(q2["base_rate"], 1000.00)
        self.assertEqual(q2["final_rate"], 1125.00)
        self.assertEqual(q2["coordinate"], "Rates!C19")

        self.assertEqual(q3["status"], "no_qualifying_carrier")
        self.assertIsNone(q3["final_rate"])
        self.assertTrue(len(q3["excluded_sheets"]) >= 1)

    # ------------------------------------------------------------------
    # 5. Missing Fields Return 422 & Parcel Sunset Rules Respected on Batch
    # ------------------------------------------------------------------
    def test_batch_quotes_rejects_missing_fields_and_respects_parcel_sunset(self):
        session_headers, uid = self._new_user("BUSINESS", "val_sunset")
        _seed_confirmed_ltl_sheet(uid)
        raw_key = client.post("/api/user/api-key/generate", json={"name": "Val Key"}, headers=session_headers).json()["api_key"]

        # Missing destination -> 422 (no silent H3B 4W8 dummy fallback)
        r_no_dest = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "actual_weight": 500.0, "skid_count": 1}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(r_no_dest.status_code, 422)

        # Missing weight & skid_count -> 422 (no silent 15.0 lb dummy fallback)
        r_no_wt = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC"}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(r_no_wt.status_code, 422)

        # Explicit shipping_mode == PARCEL -> 422 E_PARCEL_NOT_SUPPORTED
        r_parcel_mode = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 500.0, "shipping_mode": "PARCEL"}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(r_parcel_mode.status_code, 422)
        self.assertEqual(r_parcel_mode.json()["error"], "E_PARCEL_NOT_SUPPORTED")

        # Over > 100 items -> 422 E_INVALID_BATCH_SIZE
        r_cap = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 500.0, "skid_count": 1}] * 101},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(r_cap.status_code, 422)
        self.assertEqual(r_cap.json()["error"], "E_INVALID_BATCH_SIZE")

        # Pre-sunset < 150 lb unpalletized -> 200 with RFC 8594 Sunset & RFC 9745 Deprecation headers + advisory_warnings
        now_epoch = 1793280000.0
        deploy_epoch = now_epoch - (5 * 86400)
        sunset_epoch = deploy_epoch + (90 * 86400)
        set_system_setting("failsafe_deploy_timestamp", str(deploy_epoch))
        set_system_setting("failsafe_sunset_timestamp", str(sunset_epoch))
        main.sunset_clock = lambda: now_epoch

        pre_res = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 80.0}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(pre_res.status_code, 200)
        self.assertIn("Sunset", pre_res.headers)
        self.assertIn("Deprecation", pre_res.headers)
        self.assertEqual(pre_res.json()["advisory_warnings"][0]["code"], "WARN_PARCEL_DEPRECATION")

        # Post-sunset < 150 lb unpalletized -> 422 E_PARCEL_DEPRECATED_LTL_ONLY
        main.sunset_clock = lambda: sunset_epoch + 60.0
        post_res = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 80.0}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(post_res.status_code, 422)
        self.assertEqual(post_res.json()["error"], "E_PARCEL_DEPRECATED_LTL_ONLY")

    # ------------------------------------------------------------------
    # 6. Least-Privilege Scope & Per-Key Rate Limit Enforcement
    # ------------------------------------------------------------------
    def test_api_key_cannot_access_account_mutation_endpoints(self):
        session_headers, uid = self._new_user("BUSINESS", "scope_check")
        _seed_confirmed_ltl_sheet(uid)
        gen = client.post("/api/user/api-key/generate", json={"name": "Scoped Key"}, headers=session_headers).json()
        raw_key = gen["api_key"]
        key_id = gen["id"]

        # Leaked X-API-Key MUST NOT authenticate password change, account delete, or key generation
        pw_res = client.post(
            "/api/user/password",
            json={"current_password": "StrongTestPassword2026!", "new_password": "HackedPassword999!"},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(pw_res.status_code, 401)

        del_res = client.post(
            "/api/user/account/delete",
            json={"immediate_purge": True},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(del_res.status_code, 401)

        gen2_res = client.post(
            "/api/user/api-key/generate",
            json={"name": "Escalated Key"},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(gen2_res.status_code, 401)

        # Exhaust per-key token bucket and verify HTTP 429 + Retry-After header
        main.api_key_rate_limiter.buckets[key_id] = (0.0, time.time())
        rl_res = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 500.0, "skid_count": 1}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(rl_res.status_code, 429)
        self.assertEqual(rl_res.headers.get("Retry-After"), "1")
        self.assertEqual(rl_res.json()["error"], "E_RATE_LIMITED")

    # ------------------------------------------------------------------
    # 7. Webhooks: SSRF Blocking & HMAC-SHA256 Signed Delivery
    # ------------------------------------------------------------------
    def test_webhook_registration_ssrf_block_and_hmac_signature(self):
        session_headers, uid = self._new_user("BUSINESS", "webhooks")
        _seed_confirmed_ltl_sheet(uid, cwt_rate_mtl=50.00)
        raw_key = client.post("/api/user/api-key/generate", json={"name": "WH Key"}, headers=session_headers).json()["api_key"]

        # Block direct cloud metadata & loopback IPs
        for forbidden_url in (
            "http://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/internal",
            "https://localhost:8080/hook",
            "https://10.0.0.15/private",
        ):
            bad_res = client.post("/api/user/webhooks", json={"url": forbidden_url}, headers=session_headers)
            self.assertEqual(bad_res.status_code, 422, f"Expected 422 for {forbidden_url}")
            self.assertEqual(bad_res.json()["error"], "E_WEBHOOK_INVALID_URL")

        # Block DNS rebinding / hostname resolving to private IP
        webhook_service.dns_resolver = lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", port))
        ]
        dns_bad = client.post(
            "/api/user/webhooks",
            json={"url": "https://evil-rebind.example.com/hook"},
            headers=session_headers,
        )
        self.assertEqual(dns_bad.status_code, 422)

        # Allow public routable IP via injectable DNS resolver & capture outbound POST via injectable transport
        webhook_service.dns_resolver = lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ]
        captured_calls: List[Tuple[str, bytes, Dict[str, str]]] = []

        def fake_transport(url: str, body: bytes, headers: Dict[str, str], timeout: float) -> Tuple[int, str]:
            captured_calls.append((url, body, headers))
            return 200, ""

        webhook_service.webhook_transport = fake_transport

        wh_res = client.post(
            "/api/user/webhooks",
            json={"url": "https://erp.example.com/webhooks/quotelytics", "description": "ERP Listener"},
            headers=session_headers,
        )
        self.assertEqual(wh_res.status_code, 200)
        wh_secret = wh_res.json()["endpoint"]["secret"]
        wh_id = wh_res.json()["endpoint"]["id"]
        self.assertTrue(wh_secret.startswith("whsec_"))

        # Trigger batch calculation -> BackgroundTasks dispatches signed batch.quote.completed webhook
        batch_res = client.post(
            "/api/v1/quotes/batch",
            json={"shipments": [{"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "actual_weight": 1000.0, "skid_count": 2}]},
            headers={"X-API-Key": raw_key},
        )
        self.assertEqual(batch_res.status_code, 200)
        batch_id = batch_res.json()["batch_id"]

        self.assertEqual(len(captured_calls), 1)
        sent_url, sent_body, sent_headers = captured_calls[0]
        self.assertEqual(sent_url, "https://erp.example.com/webhooks/quotelytics")
        self.assertEqual(sent_headers["X-Quotelytics-Event"], "batch.quote.completed")

        # Verify cryptographic HMAC-SHA256 signature
        sig_parts = dict(part.split("=", 1) for part in sent_headers["X-Quotelytics-Signature"].split(","))
        ts_str = sig_parts["t"]
        expected_hmac = hmac.new(
            wh_secret.encode("utf-8"),
            f"{ts_str}.".encode("utf-8") + sent_body,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(sig_parts["v1"], expected_hmac)

        parsed_env = json.loads(sent_body.decode("utf-8"))
        self.assertEqual(parsed_env["event"], "batch.quote.completed")
        self.assertEqual(parsed_env["batch_id"], batch_id)
        self.assertEqual(parsed_env["data"]["quoted_count"], 1)

        # Verify delivery receipt persisted in GET /api/user/webhooks and PIPEDA export omits raw secrets
        wh_list = client.get("/api/user/webhooks", headers=session_headers).json()
        self.assertEqual(len(wh_list["endpoints"]), 1)
        self.assertNotIn("secret", wh_list["endpoints"][0])
        self.assertEqual(len(wh_list["deliveries"]), 1)
        self.assertTrue(wh_list["deliveries"][0]["success"])
        self.assertEqual(wh_list["deliveries"][0]["batch_id"], batch_id)

        export_res = client.get("/api/user/data-export", headers=session_headers)
        self.assertEqual(export_res.status_code, 200)
        export_text = export_res.text
        self.assertNotIn(raw_key, export_text)
        self.assertNotIn(wh_secret, export_text)

        # Test synthetic ping endpoint and endpoint deletion
        ping_res = client.post(f"/api/user/webhooks/{wh_id}/test", headers=session_headers)
        self.assertEqual(ping_res.status_code, 200)
        self.assertEqual(ping_res.json()["receipt"]["event_type"], "batch.quote.test")

        del_wh = client.delete(f"/api/user/webhooks/{wh_id}", headers=session_headers)
        self.assertEqual(del_wh.status_code, 200)

    # ------------------------------------------------------------------
    # 8. Console Developer API Tab & Synced Documentation
    # ------------------------------------------------------------------
    def test_account_ui_renders_developer_api_tab_and_synced_docs(self):
        session_headers, _ = self._new_user("BUSINESS", "ui_docs")
        acc_res = client.get("/console/account", headers=session_headers)
        self.assertEqual(acc_res.status_code, 200)
        html = acc_res.text
        self.assertIn('id="tab-btn-api"', html)
        self.assertIn('id="panel-api"', html)
        self.assertIn("/api/user/api-keys", html)
        self.assertIn("/api/user/webhooks", html)

        chrome_js = (BASE_DIR / "static" / "js" / "global-chrome.js").read_text(encoding="utf-8")
        self.assertIn("https://quotelytics.ca/api/v1/quotes/batch", chrome_js)
        self.assertNotIn("quotelytics.io/api/v1/quotes/batch", chrome_js)
        self.assertIn('"actual_weight"', chrome_js)
        self.assertIn("/api/quotelytics/quotes/calculate", chrome_js)

        pricing_html = (BASE_DIR / "templates" / "public" / "pricing.html").read_text(encoding="utf-8")
        self.assertIn("https://quotelytics.ca/api/v1/quotes/batch", pricing_html)
        self.assertIn("/console/account#api", pricing_html)


if __name__ == "__main__":
    unittest.main()
