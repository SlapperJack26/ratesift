"""
Automated Verification Suite for GTM Groups 4, 5, and 6:
- Group 4: Broker Help Centre & Support Desk
- Group 5: Carrier IP Risk Mitigation & Bill 96 Quebec Notice
- Group 6: Stripe Subscriptions & Webhook Code Infrastructure
"""
import json
import pytest
from fastapi.testclient import TestClient

from main import app
from services.email_service import clear_sent_emails, get_sent_emails
from services.db_service import get_connection


@pytest.fixture(autouse=True)
def clean_state():
    clear_sent_emails()
    yield
    clear_sent_emails()


# ==============================================================================
# GROUP 4: BROKER HELP CENTRE & SUPPORT DESK
# ==============================================================================

def test_group_4_help_and_faq_pages():
    client = TestClient(app)
    
    # 1. GET /help
    res_help = client.get("/help")
    assert res_help.status_code == 200
    html = res_help.text
    assert "<title>Quotelytics | Help Centre & Freight Rating Documentation</title>" in html
    assert 'id="sheet-formats"' in html
    assert 'id="cwt-breaks"' in html
    assert 'id="deficit-rating"' in html
    assert 'id="fsa-routing"' in html
    assert 'id="fuel-surcharges"' in html
    assert 'id="billing-quotas"' in html
    assert 'id="faq"' in html
    assert "TechArticle" in html
    assert "FAQPage" in html
    assert "og:locale" in html and "en_CA" in html
    assert "289-929-8565" in html

    # 2. GET /faq
    res_faq = client.get("/faq")
    assert res_faq.status_code == 200
    assert "Help Centre" in res_faq.text


def test_group_4_support_ticket_email_dispatch():
    client = TestClient(app)
    payload = {
        "email": "dispatcher_g4@ontariofreight.ca",
        "category": "TARIFF_INGESTION",
        "subject": "Question regarding 10M CWT weight break column format",
        "message": "Does Quotelytics support multi-tab workbooks where the second tab contains fuel accessorial tables?",
        "browser_info": "Chrome 122 on Windows 11 | Screen: 1920x1080 | Severity: NORMAL"
    }

    res = client.post("/api/support/ticket", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    ticket_id = data["ticket_id"]
    assert ticket_id.startswith("tkt_")

    # Verify user confirmation email
    user_emails = get_sent_emails(to_email="dispatcher_g4@ontariofreight.ca", category="SUPPORT_CONFIRMATION")
    assert len(user_emails) == 1
    assert ticket_id in user_emails[0]["subject"]
    assert "4 business hours" in user_emails[0]["text_body"]
    assert "289-929-8565" in user_emails[0]["text_body"]

    # Verify admin internal alert email
    admin_emails = get_sent_emails(category="SUPPORT_ALERT")
    assert len(admin_emails) == 1
    assert ticket_id in admin_emails[0]["subject"]
    assert "dispatcher_g4@ontariofreight.ca" in admin_emails[0]["text_body"]
    assert "TARIFF_INGESTION" in admin_emails[0]["text_body"]


# ==============================================================================
# GROUP 5: CARRIER IP RISK MITIGATION & QUEBEC NOTICE
# ==============================================================================

def test_group_5_public_demo_synthetic_carriers_and_disclaimer():
    client = TestClient(app)
    res = client.get("/demo")
    assert res.status_code == 200
    html = res.text

    # Synthetic demo carrier names
    assert "Apex Canadian LTL (Synthetic)" in html
    assert "Northland Logistics (Synthetic)" in html
    assert "Trans-Provincial (Synthetic)" in html

    # Synthetic benchmark disclaimer
    assert "Synthetic Benchmark Tariffs" in html
    assert "PIPEDA tenant isolation" in html

    # Verify no unconsented carrier trademarks in demo description
    assert "Compare Day & Ross, Manitoulin, and Midland rates" not in html


def test_group_5_pricing_fuel_index_and_fleet_copy():
    client = TestClient(app)
    res = client.get("/pricing")
    assert res.status_code == 200
    html = res.text

    # Fleet compatibility wording
    assert "Canadian LTL Fleets" in html
    assert "Compatible with major Canadian carrier tariff formats" in html

    # Fuel index attribution wording
    assert "Weekly Fuel Index Manager" in html
    assert "Canadian Benchmarks & Custom FSC" in html
    assert "Deficit Rating (CzarLite®-Compatible)" in html


def test_group_5_get_started_quebec_notice():
    client = TestClient(app)
    res = client.get("/get-started")
    assert res.status_code == 200
    html = res.text

    assert "Notice for Quebec operations" in html
    assert "Bill 96" in html
    assert "en_CA" in html


# ==============================================================================
# GROUP 6: STRIPE SUBSCRIPTIONS & WEBHOOK CODE INFRASTRUCTURE
# ==============================================================================

def test_group_6_billing_endpoints_authentication():
    client = TestClient(app)

    # 1. Anonymous access should be rejected with 401
    res_checkout = client.post("/api/billing/checkout", json={"plan": "PRO"})
    assert res_checkout.status_code == 401

    res_portal = client.post("/api/billing/portal", json={})
    assert res_portal.status_code == 401

    res_info = client.get("/api/billing/info")
    assert res_info.status_code == 401


def test_group_6_checkout_and_portal_lifecycle():
    client = TestClient(app)

    # Register a new broker
    reg_email = "stripe_tester@logistics-broker.ca"
    reg_res = client.post("/api/auth/register", data={
        "name": "Stripe Tester",
        "email": reg_email,
        "password": "SecurePassword2026!",
        "company": "Stripe Testing Logistics",
        "origin_zip": "M5V 2T6",
        "terms": "true"
    })
    assert reg_res.status_code == 200
    user_id = reg_res.json()["user"]["id"]

    # 1. Check initial billing info
    info_res = client.get("/api/billing/info")
    assert info_res.status_code == 200
    info_data = info_res.json()
    assert info_data["billing"]["tier"] == "FREE"
    assert info_data["quota"]["tier"] == "FREE"
    assert info_data["quota"]["max_sheets"] == 3
    assert info_data["quota"]["max_quotes_per_month"] == 50

    # 2. Reject invalid plan
    bad_checkout = client.post("/api/billing/checkout", json={"plan": "SUPER_ULTRA_TIER"})
    assert bad_checkout.status_code == 400

    # 3. Create checkout session for Broker Pro
    checkout_res = client.post("/api/billing/checkout", json={"plan": "PRO"})
    assert checkout_res.status_code == 200
    checkout_data = checkout_res.json()
    assert "checkout_url" in checkout_data
    assert "session_id" in checkout_data
    assert checkout_data["plan"] == "PRO"
    assert checkout_data["effective_monthly_cad"] == 79.0

    # 3b. Verify BETA50 promo code (50% off Broker Pro -> $39.50 CAD/mo) and FOUNDING25 (30% off -> $55.30 CAD/mo)
    beta50_res = client.post("/api/billing/checkout", json={"plan": "PRO", "promo_code": "beta50"})
    assert beta50_res.status_code == 200
    beta50_data = beta50_res.json()
    assert beta50_data["promo_code"] == "BETA50"
    assert beta50_data["percent_off"] == 50.0
    assert beta50_data["effective_monthly_cad"] == 39.5

    founding_res = client.post("/api/billing/checkout", json={"plan": "PRO", "promo_code": "FOUNDING25"})
    assert founding_res.status_code == 200
    founding_data = founding_res.json()
    assert founding_data["promo_code"] == "FOUNDING25"
    assert founding_data["percent_off"] == 30.0
    assert founding_data["effective_monthly_cad"] == 55.3

    bad_promo_res = client.post("/api/billing/checkout", json={"plan": "PRO", "promo_code": "FAKECODE99"})
    assert bad_promo_res.status_code == 400

    # 4. Generate portal session
    portal_res = client.post("/api/billing/portal", json={})
    assert portal_res.status_code == 200
    assert "portal_url" in portal_res.json()


def test_group_6_webhook_processing_and_quota_lifecycle():
    client = TestClient(app)

    # Register user to test webhook lifecycle
    broker_email = "webhook_lifecycle@cadlogistics.ca"
    reg_res = client.post("/api/auth/register", data={
        "name": "Webhook Broker",
        "email": broker_email,
        "password": "Password10CharsMin!",
        "company": "Webhook Transport Corp",
        "origin_zip": "M5V 2T6",
        "terms": "true"
    })
    assert reg_res.status_code == 200
    user_id = reg_res.json()["user"]["id"]

    mock_cust_id = f"cus_test_{user_id[:8]}"
    mock_sub_id = f"sub_test_{user_id[:8]}"

    # 1. Invalid payload rejected with 400
    bad_webhook = client.post("/api/stripe/webhook", content="not-a-json-payload", headers={"Content-Type": "application/json"})
    assert bad_webhook.status_code == 400

    # 2. Simulate checkout.session.completed -> Upgrades user to PRO
    checkout_event = {
        "id": "evt_test_checkout_completed",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": user_id,
                "customer": mock_cust_id,
                "subscription": mock_sub_id,
                "metadata": {
                    "user_id": user_id,
                    "plan": "PRO"
                }
            }
        }
    }
    hook_res = client.post("/api/stripe/webhook", json=checkout_event)
    assert hook_res.status_code == 200
    hook_data = hook_res.json()
    assert hook_data["handled"] is True
    assert hook_data["details"]["plan"] == "PRO"

    # Verify DB & billing info reflects PRO tier (10 sheets, 2500 quotes)
    info_res = client.get("/api/billing/info")
    info_data = info_res.json()
    assert info_data["billing"]["tier"] == "PRO"
    assert info_data["billing"]["subscription_status"] == "active"
    assert info_data["billing"]["stripe_customer_id"] == mock_cust_id
    assert info_data["quota"]["tier"] == "PRO"
    assert info_data["quota"]["max_sheets"] == 10
    assert info_data["quota"]["max_quotes_per_month"] == 2500

    # 3. Simulate invoice.payment_failed -> Sets status to past_due (7-day grace period, no data loss)
    failed_invoice_event = {
        "id": "evt_test_payment_failed",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "customer": mock_cust_id
            }
        }
    }
    fail_res = client.post("/api/stripe/webhook", json=failed_invoice_event)
    assert fail_res.status_code == 200
    assert fail_res.json()["details"]["action"] == "grace_period_marked_past_due"

    info_past_due = client.get("/api/billing/info").json()
    assert info_past_due["billing"]["subscription_status"] == "past_due"
    # Quota remains intact during grace period
    assert info_past_due["billing"]["tier"] == "PRO"

    # 4. Simulate customer.subscription.deleted -> Downgrades to FREE (no deletion of rate sheets)
    cancel_event = {
        "id": "evt_test_sub_canceled",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "customer": mock_cust_id
            }
        }
    }
    cancel_res = client.post("/api/stripe/webhook", json=cancel_event)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["details"]["action"] == "downgraded_to_free"

    info_canceled = client.get("/api/billing/info").json()
    assert info_canceled["billing"]["tier"] == "FREE"
    assert info_canceled["billing"]["subscription_status"] == "canceled"
    assert info_canceled["quota"]["max_sheets"] == 3
    assert info_canceled["quota"]["max_quotes_per_month"] == 50
