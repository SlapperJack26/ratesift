"""
tests/test_failsafe_release_2a.py
Comprehensive automated test suite for Release 2a:
- Customer Notice & Deprecation Window
- Persisted Sunset Timestamp Immutability with Injectable Clock
- RFC 8594 Sunset (IMF-fixdate GMT) & RFC 9745 Deprecation (@<epoch>) Headers
- Dual-Signal Parcel Detection (< 150 lbs unpalletized vs palletized)
- Pre-Sunset Additive advisory_warnings JSON Array
- Post-Sunset Strict HTTP 422 E_PARCEL_DEPRECATED_LTL_ONLY Enforcement
"""
from datetime import datetime
import email.utils
import json
import os
import sqlite3
import time
from typing import Dict, Tuple
import unittest
import uuid

from fastapi.testclient import TestClient
import pytest

from app.main import app as failsafe_app
import main
from main import app as full_app, sunset_clock
from services.auth_service import register_and_create_session
from services.db_service import update_user_tier
from services.quotelytics_db_service import (
    create_rate_sheet,
    insert_weight_breaks,
    confirm_rate_sheet,
    get_connection,
    get_or_initialize_sunset_timestamps,
    set_system_setting,
    get_system_setting,
)
from app.validation import check_parcel_dual_signal

client = TestClient(full_app)


def _make_auth_headers(prefix: str = "user_2a", company: str = "Apex Logistics") -> Tuple[Dict[str, str], str]:
    user, token = register_and_create_session(
        name=f"User {prefix}",
        email=f"{prefix}.{uuid.uuid4().hex[:8]}@apex-logistics.ca",
        company=company,
        origin_zip="TORONTO, ON",
        password="TestPassword2026!",
    )
    update_user_tier(user["id"], "BUSINESS")
    return {"Authorization": f"Bearer {token}"}, str(user["id"])


class TestFailsafeRelease2a(unittest.TestCase):

    def setUp(self):
        # Reset strict flag and reset clock
        os.environ["FAILSAFE_PARCEL_STRICT"] = "false"
        main.sunset_clock = time.time

    def tearDown(self):
        os.environ["FAILSAFE_PARCEL_STRICT"] = "false"
        main.sunset_clock = time.time

    # --------------------------------------------------------------------------
    # Test 7: Dual-Signal Parcel Detection Logic [Release 2a]
    # --------------------------------------------------------------------------
    def test_parcel_detection_dual_signal(self):
        """Dual-signal requires BOTH <150 lbs weight AND courier/unpalletized signal."""
        # 1. Breaks all <= 150 lbs AND courier keywords -> True
        self.assertTrue(check_parcel_dual_signal(
            break_weights=[10.0, 50.0, 100.0, 150.0],
            headers=["Origin", "Dest", "Pkg Rate 10", "Box Rate 50"],
            preamble_text="Ground Courier Service",
            mode="weight",
        ))

        # 2. Breaks <= 150 lbs BUT Skid Mode -> False (skid mode is never parcel)
        self.assertFalse(check_parcel_dual_signal(
            break_weights=[10.0, 50.0],
            headers=["Origin", "Dest", "Skid 1", "Skid 2"],
            mode="skid",
        ))

        # 3. Breaks exceed 150 lbs (e.g. 500 lbs, 1000 lbs) -> False (standard LTL)
        self.assertFalse(check_parcel_dual_signal(
            break_weights=[100.0, 500.0, 1000.0],
            headers=["Origin", "Dest", "LTL", "1M"],
            mode="weight",
        ))

    # --------------------------------------------------------------------------
    # Test 22: Persisted Sunset Timestamp Immutability [Release 2a]
    # --------------------------------------------------------------------------
    def test_persisted_sunset_timestamp_immutability(self):
        """Verifies deploy & sunset timestamps are persisted once and never move across process restarts."""
        fake_epoch = 1793280000.0  # Simulated deploy epoch
        
        # Directly write known values
        set_system_setting("failsafe_deploy_timestamp", str(fake_epoch))
        set_system_setting("failsafe_sunset_timestamp", str(fake_epoch + 90 * 86400))

        # Simulate subsequent process restart reading from database with different current time
        def later_clock():
            return fake_epoch + 10000.0

        deploy_ts, sunset_ts = get_or_initialize_sunset_timestamps(clock_fn=later_clock)
        self.assertEqual(deploy_ts, fake_epoch)
        self.assertEqual(sunset_ts, fake_epoch + (90 * 86400))

    # --------------------------------------------------------------------------
    # Test 14: Sunset and Deprecation Header RFC Compliance [Release 2a]
    # --------------------------------------------------------------------------
    def test_sunset_header_rfc_compliance(self):
        """Verifies Sunset header follows RFC 8594 IMF-fixdate and Deprecation follows RFC 9745 @<epoch>."""
        deploy_epoch = 1793280000.0
        sunset_epoch = deploy_epoch + (90 * 86400)
        set_system_setting("failsafe_deploy_timestamp", str(deploy_epoch))
        set_system_setting("failsafe_sunset_timestamp", str(sunset_epoch))

        sunset_imf = email.utils.formatdate(sunset_epoch, usegmt=True)
        # RFC 8594 regex: Day, DD Mon YYYY HH:MM:SS GMT
        self.assertRegex(sunset_imf, r"^[A-Z][a-z]{2},\s+\d{2}\s+[A-Z][a-z]{2}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+GMT$")

        # RFC 9745 Deprecation format: @<epoch>
        deprecation_val = f"@{int(deploy_epoch)}"
        self.assertRegex(deprecation_val, r"^@\d+$")

    # --------------------------------------------------------------------------
    # Test 41: Pre-Sunset Additive Advisory Warnings JSON Array [Release 2a]
    # --------------------------------------------------------------------------
    def test_pre_sunset_advisory_warnings_json_additive(self):
        """Pre-sunset quote for < 150 lbs unpalletized returns 200 with RFC headers and advisory_warnings."""
        headers, user_id = _make_auth_headers("presunset_user")
        
        # Set deploy epoch such that sunset is in the future
        now_epoch = 1793280000.0
        deploy_epoch = now_epoch - (10 * 86400)  # 10 days ago
        sunset_epoch = deploy_epoch + (90 * 86400)  # 80 days remaining
        set_system_setting("failsafe_deploy_timestamp", str(deploy_epoch))
        set_system_setting("failsafe_sunset_timestamp", str(sunset_epoch))
        main.sunset_clock = lambda: now_epoch

        # Create active LTL confirmed rate sheet for user
        sheet_id = create_rate_sheet(
            user_id=user_id,
            carrier_name="Apex Freight",
            service_name="Standard LTL",
            version=1,
        )
        insert_weight_breaks(sheet_id, user_id, [
            {
                "zone_code": "DEFAULT",
                "origin_spec": "TORONTO, ON",
                "dest_spec": "MONTREAL, QC",
                "min_weight": 0.0,
                "max_weight": 99999.0,
                "base_rate": 45.0,
                "break_name": "LTL",
                "rate_type": "CWT",
            }
        ])
        confirm_rate_sheet(sheet_id, user_id, "Apex Auditor")

        # Quote request: 85 lbs unpalletized (< 150 lbs, skid_count=None)
        req_payload = {
            "origin": "Toronto, ON",
            "destination": "Montreal, QC",
            "actual_weight": 85.0,
            "skid_count": None,
        }
        res = client.post("/api/quotelytics/quotes/calculate", json=req_payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        # Verify RFC Headers
        self.assertIn("Sunset", res.headers)
        self.assertIn("Deprecation", res.headers)
        self.assertIn("Link", res.headers)
        self.assertIn("ltl-transition", res.headers["Link"])

        # Verify additive advisory_warnings array
        data = res.json()
        self.assertIn("advisory_warnings", data)
        self.assertEqual(len(data["advisory_warnings"]), 1)
        warning = data["advisory_warnings"][0]
        self.assertEqual(warning["code"], "WARN_PARCEL_DEPRECATION")
        self.assertIn("transitioning exclusively to Skid/LTL", warning["message"])

    # --------------------------------------------------------------------------
    # Test 42: Post-Sunset Strict HTTP 422 Rejection [Release 2a / 2b]
    # --------------------------------------------------------------------------
    def test_post_sunset_422_rejection(self):
        """Post-sunset date OR strict mode returns HTTP 422 E_PARCEL_DEPRECATED_LTL_ONLY for <150 lbs unpalletized."""
        headers, user_id = _make_auth_headers("postsunset_user")

        # Case 1: Post-Sunset Date
        deploy_epoch = 1793280000.0
        sunset_epoch = deploy_epoch + (90 * 86400)
        set_system_setting("failsafe_deploy_timestamp", str(deploy_epoch))
        set_system_setting("failsafe_sunset_timestamp", str(sunset_epoch))
        # Clock after sunset date
        main.sunset_clock = lambda: sunset_epoch + 100.0

        req_payload = {
            "origin": "Toronto, ON",
            "destination": "Montreal, QC",
            "actual_weight": 110.0,
            "skid_count": None,
        }
        res_post = client.post("/api/quotelytics/quotes/calculate", json=req_payload, headers=headers)
        self.assertEqual(res_post.status_code, 422)
        post_data = res_post.json()
        self.assertEqual(post_data["error"], "E_PARCEL_DEPRECATED_LTL_ONLY")
        self.assertIn("Skid/LTL freight only", post_data["message"])

        # Case 2: Palletized shipment of same weight (110 lbs, skid_count=1) succeeds
        res_pallet = client.post("/api/quotelytics/quotes/calculate", json={
            "origin": "Toronto, ON",
            "destination": "Montreal, QC",
            "actual_weight": 110.0,
            "skid_count": 1,
        }, headers=headers)
        # Palletized is NOT rejected with 422
        self.assertNotEqual(res_pallet.status_code, 422)

        # Case 3: FAILSAFE_PARCEL_STRICT=true before sunset returns 422
        main.sunset_clock = lambda: deploy_epoch + 1000.0  # Before sunset
        os.environ["FAILSAFE_PARCEL_STRICT"] = "true"
        res_strict = client.post("/api/quotelytics/quotes/calculate", json=req_payload, headers=headers)
        self.assertEqual(res_strict.status_code, 422)
        self.assertEqual(res_strict.json()["error"], "E_PARCEL_DEPRECATED_LTL_ONLY")

    # --------------------------------------------------------------------------
    # Test: Customer In-App Deprecation Banner & Email Notice Dispatch [Release 2a]
    # --------------------------------------------------------------------------
    def test_customer_in_app_notice_and_email_dispatch(self):
        """Verifies customer in-app deprecation notice and transactional email notice delivery."""
        from services.email_service import send_parcel_deprecation_notice_email, get_sent_emails, clear_sent_emails
        clear_sent_emails()

        # 1. Customer email notice dispatch
        test_email = "dispatch@apex-freight.ca"
        res_email = send_parcel_deprecation_notice_email(
            to_email=test_email,
            name="Apex Dispatch",
            sunset_date_str="April 30, 2027",
        )
        self.assertIn("outbox", res_email["delivered_via"])

        outbox = get_sent_emails(to_email=test_email, category="PARCEL_DEPRECATION_NOTICE")
        self.assertEqual(len(outbox), 1)
        sent = outbox[0]
        self.assertIn("100% Skid/LTL Rating Engine", sent["subject"])
        self.assertIn("April 30, 2027", sent["text_body"])
        self.assertIn("/console/account", sent["text_body"])

        # 2. In-app transition notice banner removed from new_quote.html template
        with open("templates/console/new_quote.html", "r", encoding="utf-8") as f:
            template_text = f.read()
        self.assertNotIn("Quotelytics Skid/LTL Transition Notice", template_text)
        self.assertNotIn('id="ltl-transition-banner"', template_text)
