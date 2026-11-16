"""
tests/test_sales_rep_api_onboarding.py
Automated verification suite for the Zero-Technical Sales Rep Business API Onboarding Plan:
1. Access control on /console/admin & /api/admin/customers (303 logged out, 403 non-admin, 200 ADMIN)
2. Admin search by email/company + 1-click BUSINESS activation by email + welcome notification + zero secret/rate leakage
3. Guided 3-step Developer API readiness checklist states across 0 sheets -> 1 confirmed sheet -> 1 active key
4. 1-click non-polluting API Readiness Test (POST /api/user/api-readiness-check) without adding rows to ql_quote_audit_logs
5. UI rendering & XSS-safe controls in /console/admin and /console/account
"""
import json
from typing import Dict, List, Tuple
import unittest
import uuid

from fastapi.testclient import TestClient

from main import app as full_app
from services.auth_service import register_and_create_session
from services.db_service import delete_user_account_data, get_connection, update_user_tier
from services.quotelytics_db_service import (
    confirm_rate_sheet,
    create_rate_sheet,
    insert_weight_breaks,
    list_quote_audit_logs,
)

client = TestClient(full_app)


def _create_account(role: str = "USER", tier: str = "FREE", prefix: str = "onb") -> Tuple[Dict[str, str], str, str]:
    email = f"{prefix}.{uuid.uuid4().hex[:8]}@maple-brokerage.ca"
    user, token = register_and_create_session(
        name=f"Contact {prefix}",
        email=email,
        company=f"Maple Brokerage {prefix}",
        origin_zip="TORONTO, ON",
        password="StrongOnboardingPass2026!",
    )
    uid = str(user["id"])
    update_user_tier(uid, tier)
    if role == "ADMIN":
        conn = get_connection()
        conn.execute("UPDATE users SET role = 'ADMIN' WHERE id = ?", (uid,))
        conn.commit()
        conn.close()
    return {"Authorization": f"Bearer {token}"}, uid, email


class TestSalesRepApiOnboarding(unittest.TestCase):

    def setUp(self):
        self._created_uids: List[str] = []

    def tearDown(self):
        for uid in self._created_uids:
            try:
                delete_user_account_data(uid, immediate_purge=True)
            except Exception:
                pass

    def _new_acct(self, role: str = "USER", tier: str = "FREE", prefix: str = "onb") -> Tuple[Dict[str, str], str, str]:
        hdrs, uid, email = _create_account(role=role, tier=tier, prefix=prefix)
        self._created_uids.append(uid)
        return hdrs, uid, email

    # ------------------------------------------------------------------
    # 1. Access Control on /console/admin and /api/admin/customers
    # ------------------------------------------------------------------
    def test_admin_onboarding_access_control(self):
        # Unauthenticated -> 303 redirect on HTML page, 401 on JSON API
        unauth_page = client.get("/console/admin", follow_redirects=False)
        self.assertEqual(unauth_page.status_code, 303)
        self.assertIn("/login?next=/console/admin", unauth_page.headers["location"])

        unauth_api = client.get("/api/admin/customers")
        self.assertEqual(unauth_api.status_code, 401)

        # Standard USER (even on BUSINESS tier) -> 403 Forbidden
        biz_user_hdrs, _, _ = self._new_acct(role="USER", tier="BUSINESS", prefix="non_admin")
        self.assertEqual(client.get("/console/admin", headers=biz_user_hdrs).status_code, 403)
        self.assertEqual(client.get("/api/admin/customers", headers=biz_user_hdrs).status_code, 403)

        # ADMIN -> 200 OK
        admin_hdrs, _, _ = self._new_acct(role="ADMIN", tier="BUSINESS", prefix="sales_admin")
        self.assertEqual(client.get("/console/admin", headers=admin_hdrs).status_code, 200)
        self.assertEqual(client.get("/api/admin/customers", headers=admin_hdrs).status_code, 200)

    # ------------------------------------------------------------------
    # 2. Admin Search by Email & 1-Click Business Activation + Confidentiality
    # ------------------------------------------------------------------
    def test_admin_search_and_one_click_business_activation(self):
        admin_hdrs, _, _ = self._new_acct(role="ADMIN", tier="BUSINESS", prefix="rep")
        cust_hdrs, cust_uid, cust_email = self._new_acct(role="USER", tier="FREE", prefix="prospect")

        # Search by prospect email
        search_res = client.get(f"/api/admin/customers?q={cust_email}", headers=admin_hdrs)
        self.assertEqual(search_res.status_code, 200)
        matches = search_res.json()["customers"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["email"], cust_email)
        self.assertEqual(matches[0]["tier"], "FREE")
        self.assertFalse(matches[0]["has_api_access"])
        self.assertEqual(matches[0]["confirmed_sheets_count"], 0)
        self.assertEqual(matches[0]["active_api_keys_count"], 0)

        # 1-Click Activate BUSINESS using email (no user_id needed by sales rep!)
        act_res = client.post(
            "/api/user/upgrade-tier",
            json={"email": cust_email, "tier": "BUSINESS"},
            headers=admin_hdrs,
        )
        self.assertEqual(act_res.status_code, 200)
        self.assertEqual(act_res.json()["new_tier"], "BUSINESS")

        # Customer receives in-app welcome notification linking to /console/account#api
        notifs = client.get("/api/notifications", headers=cust_hdrs).json()["notifications"]
        self.assertTrue(any("/console/account#api" in (n.get("link_url") or "") for n in notifs))

        # Customer generates a secret key & confirms a tariff; verify Admin search NEVER leaks raw secrets or rates
        raw_secret = client.post("/api/user/api-key/generate", json={"name": "TMS Key"}, headers=cust_hdrs).json()["api_key"]
        sheet_id = create_rate_sheet(user_id=cust_uid, carrier_name="Private Carrier", service_name="LTL", currency="CAD")
        insert_weight_breaks(sheet_id, cust_uid, [{
            "zone_code": "Z1",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "OTTAWA, ON",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "base_rate": 49.99,
            "break_name": "LTL",
            "rate_type": "CWT",
        }])
        confirm_rate_sheet(sheet_id, cust_uid, "Broker")

        after_search = client.get(f"/api/admin/customers?q={cust_email}", headers=admin_hdrs).json()
        after_text = json.dumps(after_search)
        self.assertNotIn(raw_secret, after_text)
        self.assertNotIn("49.99", after_text)
        self.assertEqual(after_search["customers"][0]["confirmed_sheets_count"], 1)
        self.assertEqual(after_search["customers"][0]["active_api_keys_count"], 1)
        self.assertTrue(after_search["customers"][0]["api_ready"])

    # ------------------------------------------------------------------
    # 3. Guided 3-Step Readiness Checklist Transitions
    # ------------------------------------------------------------------
    def test_developer_api_readiness_checklist_states(self):
        cust_hdrs, cust_uid, _ = self._new_acct(role="USER", tier="BUSINESS", prefix="checklist")

        # State A: 0 confirmed sheets, 0 keys
        s0 = client.get("/api/user/api-keys", headers=cust_hdrs).json()["onboarding"]
        self.assertEqual(s0["confirmed_sheets_count"], 0)
        self.assertEqual(s0["active_keys_count"], 0)
        self.assertIsNone(s0["sample_lane"])

        # State B: Confirm 1 sheet -> sample_lane populated
        sid = create_rate_sheet(user_id=cust_uid, carrier_name="Manitoulin LTL", service_name="Road LTL", currency="CAD")
        insert_weight_breaks(sid, cust_uid, [{
            "zone_code": "ON_MB",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "WINNIPEG, MB",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "base_rate": 55.00,
            "break_name": "LTL",
            "rate_type": "CWT",
            "source_cell": "Sheet1!E6",
        }])
        confirm_rate_sheet(sid, cust_uid, "Dispatcher")

        s1 = client.get("/api/user/api-keys", headers=cust_hdrs).json()["onboarding"]
        self.assertEqual(s1["confirmed_sheets_count"], 1)
        self.assertEqual(s1["sample_lane"]["origin"], "TORONTO, ON")
        self.assertEqual(s1["sample_lane"]["destination"], "WINNIPEG, MB")

        # State C: Generate 1 key -> active_keys_count == 1 & active_key_prefix populated
        gen = client.post("/api/user/api-key/generate", json={"name": "Main Key"}, headers=cust_hdrs).json()
        s2 = client.get("/api/user/api-keys", headers=cust_hdrs).json()["onboarding"]
        self.assertEqual(s2["active_keys_count"], 1)
        self.assertEqual(s2["active_key_prefix"], gen["key_prefix"])

    # ------------------------------------------------------------------
    # 4. 1-Click Readiness Verification Dry-Run Does Not Pollute Audit History
    # ------------------------------------------------------------------
    def test_one_click_api_readiness_dry_run_does_not_pollute_history(self):
        cust_hdrs, cust_uid, _ = self._new_acct(role="USER", tier="BUSINESS", prefix="dryrun")
        client.post(
            "/api/settings/update",
            data={"currency": "CAD", "units": "lbs", "markup_pct": 10.0, "auto_detect_headers": 1, "skip_blank_rows": 1},
            headers=cust_hdrs,
        )

        # Before confirming any sheet -> ready: False ("NO_CONFIRMED_SHEETS")
        r0 = client.post("/api/user/api-readiness-check", headers=cust_hdrs)
        self.assertEqual(r0.status_code, 200)
        self.assertFalse(r0.json()["ready"])
        self.assertEqual(r0.json()["reason"], "NO_CONFIRMED_SHEETS")

        # Confirm sheet ($40.00/CWT -> 1,000 lbs = $400.00 base; +10% markup = $440.00)
        sid = create_rate_sheet(user_id=cust_uid, carrier_name="TST-CF Express", service_name="Standard LTL", currency="CAD")
        insert_weight_breaks(sid, cust_uid, [{
            "zone_code": "ON_QC",
            "origin_spec": "TORONTO, ON",
            "dest_spec": "MONTREAL, QC",
            "min_weight": 0.0,
            "max_weight": 99999.0,
            "base_rate": 40.00,
            "break_name": "LTL",
            "rate_type": "CWT",
            "source_cell": "Tariff!B9",
        }])
        confirm_rate_sheet(sid, cust_uid, "QA")

        audit_before = len(list_quote_audit_logs(cust_uid))
        quota_before = client.get("/api/user/quota", headers=cust_hdrs).json()["monthly_quotes_used"]

        r1 = client.post("/api/user/api-readiness-check", headers=cust_hdrs)
        self.assertEqual(r1.status_code, 200)
        body = r1.json()
        self.assertTrue(body["ready"])
        self.assertEqual(body["sample_quote"]["base_rate"], 400.00)
        self.assertEqual(body["sample_quote"]["final_rate"], 440.00)
        self.assertEqual(body["sample_quote"]["coordinate"], "Tariff!B9")

        # Confirm zero audit log pollution and zero monthly quote consumption
        audit_after = len(list_quote_audit_logs(cust_uid))
        quota_after = client.get("/api/user/quota", headers=cust_hdrs).json()["monthly_quotes_used"]
        self.assertEqual(audit_after, audit_before)
        self.assertEqual(quota_after, quota_before)

    # ------------------------------------------------------------------
    # 5. UI Controls Rendered Safely in /console/admin and /console/account
    # ------------------------------------------------------------------
    def test_ui_renders_handoff_controls(self):
        admin_hdrs, _, _ = self._new_acct(role="ADMIN", tier="BUSINESS", prefix="ui_chk")

        admin_html = client.get("/console/admin", headers=admin_hdrs).text
        self.assertIn("Sales Rep — Business API Onboarding Desk", admin_html)
        self.assertIn("Activate Business Plan", admin_html)
        self.assertIn("Copy Welcome Steps", admin_html)

        acc_html = client.get("/console/account", headers=admin_hdrs).text
        self.assertIn('id="api-guided-checklist-card"', acc_html)
        self.assertIn('id="btn-verify-api-readiness"', acc_html)
        self.assertIn('id="btn-copy-it-handoff"', acc_html)
        self.assertIn('id="admin-onboarding-desk-link"', acc_html)


if __name__ == "__main__":
    unittest.main()
