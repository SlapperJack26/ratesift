"""
Verification suite for Quotelytics Terms of Service & Refund Policy (GTM Plan §3.1 & §6.3):
- /terms route renders complete SaaS Agreement
- /refunds route renders dedicated Refund & Cancellation Policy
- Customer rate data ownership, carrier tariff upload warranty, and pure SaaS disclaimer
- Non-binding quote disclaimer (Rule 26) and Human Confirmation Gate (Rules 7, 19)
- Limitation of liability cap (12 months of fees / CAD $100)
- Canadian data residency (WHC / CA_CENTRAL_WHC) and Ontario governing law
"""
from fastapi.testclient import TestClient
from main import app
from services.db_service import init_db


def test_01_terms_of_service_page_and_provisions():
    init_db()
    client = TestClient(app)

    res = client.get("/terms")
    assert res.status_code == 200
    html = res.text

    # Title & Legal Entity
    assert "Quotelytics Terms of Service" in html
    assert "Quotelytics Inc." in html

    # Section 2: Freight Intermediary Disclaimer
    assert "not a motor carrier, freight broker, freight forwarder" in html

    # Section 3: Data Ownership & Tariff Warranty
    assert "Customer Owns All Uploaded Data" in html
    assert "Customer Warranty on Carrier Tariffs" in html
    assert "Zero AI Model Training" in html

    # Section 4: Accuracy & Human Confirmation Gate
    assert "Non-Binding Calculations" in html
    assert "Human Confirmation Gate" in html
    assert "AS IS" in html

    # Section 6: Liability Cap
    assert "twelve (12)" in html or "12" in html
    assert "CAD $100.00" in html

    # Section 8: WHC Canadian Residency & Ontario Law
    assert "CA_CENTRAL_WHC" in html
    assert "Province of Ontario" in html


def test_02_refund_policy_page_and_provisions():
    init_db()
    client = TestClient(app)

    res = client.get("/refunds")
    assert res.status_code == 200
    html = res.text

    assert 'id="refunds"' in html
    assert "Refund &amp; Cancellation Policy" in html
    # Monthly cancellation terms
    assert "Monthly Subscriptions:" in html
    assert "non-refundable" in html
    # Annual 14-day guarantee
    assert "14-Day Satisfaction Guarantee" in html
    # Grace period without data deletion
    assert "7-day grace period" in html
    assert "never delete customer rate sheets" in html


def test_03_signup_page_links_to_terms_and_privacy():
    client = TestClient(app)
    res = client.get("/get-started")
    assert res.status_code == 200
    html = res.text

    assert 'href="/terms"' in html
    assert 'href="/privacy"' in html
    assert 'id="terms-check"' in html
