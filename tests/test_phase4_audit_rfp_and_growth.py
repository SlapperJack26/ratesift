"""
Automated Verification Suite for Phase 4:
1. 1-Click Carrier Invoice Freight Audit & Overcharge Dispute Generator (/api/quotes/audit-carrier-invoice)
2. Canadian Rural ('0'-Digit FSA) Beyond-Point & Vancouver Island / Newfoundland Ferry Detector (/api/quotes/corridor-surcharge-check)
3. Shipper RFP / Multi-Lane CWT Bid Matrix Generator (/api/quotes/rfp-bid-matrix)
4. Beta Tester 5-Gate Health & Churn-Risk Radar (/api/admin/beta-health-radar)
5. 1-Click TMS / QuickBooks Clipboard & Universal CSV Exporter (/api/quotes/tms-export)
6. 'Give $79, Get $79' Broker Referral Loop (/api/user/referrals) & Viral Shipper Portal Badge
"""
import io
import uuid
import pytest
from fastapi.testclient import TestClient

from main import app


def test_01_carrier_invoice_audit_and_overcharge_dispute_generator():
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "Audit Broker",
        "email": f"audit_{uuid.uuid4().hex[:8]}@canadianltl.ca",
        "password": "Password10CharsMin!",
        "company": "Audit Guard Brokerage Inc.",
        "origin_zip": "L5T 1A1",
        "terms": "true",
    })

    # Carrier billed $562.00 CAD vs confirmed Quotelytics tariff rate of $485.00 CAD (+$77.00 overcharge!)
    res = client.post(
        "/api/quotes/audit-carrier-invoice",
        json={
            "carrier_name": "Manitoulin Transport",
            "invoice_number": "INV-994821",
            "origin": "MISSISSAUGA, ON (L5T)",
            "destination": "WINNIPEG, MB (R3C)",
            "expected_wholesale_cad": 485.0,
            "billed_amount_cad": 562.0,
            "tariff_citation": "Sheet 1 • Row 14, Col D",
            "expected_weight_lbs": 850.0,
            "billed_weight_lbs": 1000.0,
        },
    )
    assert res.status_code == 200
    audit = res.json()["audit"]
    assert audit["audit_status"] == "OVERCHARGE_DETECTED"
    assert audit["variance_cad"] == 77.0
    assert "FORMAL CARRIER FREIGHT INVOICE DISPUTE NOTICE" in audit["dispute_notice_text"]
    assert "Sheet 1 • Row 14, Col D" in audit["dispute_notice_text"]

    # Verify list endpoint totals the $77.00 overcharge caught
    list_res = client.get("/api/quotes/invoice-audits")
    assert list_res.status_code == 200
    ldata = list_res.json()
    assert ldata["overcharges_count"] == 1
    assert ldata["total_overcharges_caught_cad"] == 77.0


def test_02_canadian_rural_beyond_point_and_island_ferry_detector():
    client = TestClient(app)

    # 1. Rural '0'-digit FSA (T0J Drumheller, AB)
    r_rural = client.post(
        "/api/quotes/corridor-surcharge-check",
        json={"origin": "M5V 2T6", "destination": "T0J 0Y0"},
    )
    assert r_rural.status_code == 200
    d_rural = r_rural.json()
    assert d_rural["has_corridor_warnings"] is True
    codes_rural = {w["code"] for w in d_rural["warnings"]}
    assert "RURAL_BEYOND_POINT_FSA" in codes_rural

    # 2. Vancouver Island Ferry Corridor (V6B Vancouver mainland -> V8W Victoria Island)
    r_vi = client.post(
        "/api/quotes/corridor-surcharge-check",
        json={"origin": "V6B 1A1", "destination": "V8W 1N6"},
    )
    assert r_vi.status_code == 200
    codes_vi = {w["code"] for w in r_vi.json()["warnings"]}
    assert "BC_VANCOUVER_ISLAND_FERRY" in codes_vi

    # 3. Newfoundland Gulf Ferry Corridor (M5V Toronto -> A1B St. John's, NL)
    r_nl = client.post(
        "/api/quotes/corridor-surcharge-check",
        json={"origin": "M5V 2T6", "destination": "A1B 3R2"},
    )
    assert r_nl.status_code == 200
    codes_nl = {w["code"] for w in r_nl.json()["warnings"]}
    assert "NL_CABOT_STRAIT_FERRY" in codes_nl


def test_03_shipper_rfp_multi_lane_bid_matrix_generator():
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "RFP Broker",
        "email": f"rfp_{uuid.uuid4().hex[:8]}@ontario3pl.ca",
        "password": "Password10CharsMin!",
        "company": "RFP Bid Desk 3PL",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })

    # Upload and confirm a carrier rate sheet with 2 lanes (M5V->T2P and M5V->R3C)
    csv_bytes = (
        "Carrier,Day & Ross\n"
        "Currency,CAD\n"
        "Weight Unit,LB\n"
        "Origin,Destination,Min,L5C,M5C,M1M,M2M,M5M\n"
        "M5V,T2P,130.00,45.00,40.00,34.00,29.00,24.00\n"
        "M5V,R3C,110.00,35.00,30.00,26.00,22.00,18.00\n"
    ).encode("utf-8")
    up_res = client.post(
        "/api/quotelytics/sheets/upload",
        files={"file": ("rfp_carrier.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    sheet_id = up_res.json()["sheet_id"]
    client.post(f"/api/quotelytics/sheets/{sheet_id}/confirm", json={"no_minimum_confirmed": False})

    # Generate Multi-Lane RFP Bid Matrix across both lanes
    rfp_res = client.post(
        "/api/quotes/rfp-bid-matrix",
        json={
            "lanes": [
                {"origin": "M5V", "destination": "T2P"},
                {"origin": "M5V", "destination": "R3C"},
            ],
            "markup_pct": 15.0,
            "min_margin_dollars": 45.0,
        },
    )
    assert rfp_res.status_code == 200
    rdata = rfp_res.json()
    assert rdata["total_lanes"] == 2
    assert len(rdata["shipper_bid_matrix"]) == 2
    assert len(rdata["internal_award_cheat_sheet"]) == 2


def test_04_beta_cohort_5_gate_health_and_churn_radar():
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "Radar Admin",
        "email": f"radar_{uuid.uuid4().hex[:8]}@quotelytics.ca",
        "password": "Password10CharsMin!",
        "company": "Radar Monitoring Corp",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })

    res = client.get("/api/admin/beta-health-radar")
    assert res.status_code == 200
    body = res.json()
    assert body["total_monitored"] >= 1
    first_acct = body["accounts"][0]
    assert 1 <= first_acct["activation_gate"] <= 5
    assert "Subject: Quick check-in" in first_acct["checkin_email_snippet"]


def test_05_tms_quickbooks_export_and_broker_referral_loop():
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "TMS & Referral Broker",
        "email": f"tms_ref_{uuid.uuid4().hex[:8]}@canadianbroker.ca",
        "password": "Password10CharsMin!",
        "company": "Northern Star Logistics",
        "origin_zip": "L5T 1A1",
        "terms": "true",
    })

    # 1. Test 1-Click TMS / QuickBooks Clipboard & CSV Export
    tms_res = client.post(
        "/api/quotes/tms-export",
        json={
            "quote_data": {
                "carrier_name": "Manitoulin Transport",
                "service_name": "Standard Road LTL",
                "origin": "MISSISSAUGA, ON (L5T)",
                "destination": "CALGARY, AB (T2P)",
                "skid_count": 3,
                "weight_lbs": 1850.0,
                "base_rate": 420.0,
                "total_surcharges": 65.0,
                "wholesale_total": 485.0,
                "currency": "CAD",
                "source_coordinate": "Sheet 1 • Row 12, Col D",
            },
            "client_name": "Apex Industrial Mfg",
            "markup_pct": 15.0,
            "min_margin_dollars": 45.0,
        },
    )
    assert tms_res.status_code == 200
    exp = tms_res.json()["export"]
    assert "QUOTELYTICS TMS DISPATCH SUMMARY" in exp["clipboard_summary"]
    assert "Customer_Name,Origin,Destination" in exp["universal_tms_csv"]
    assert exp["broker_margin"] > 0

    # 2. Test 'Give $79, Get $79' Broker Referral Loop
    ref_info = client.get("/api/user/referrals")
    assert ref_info.status_code == 200
    r_data = ref_info.json()
    assert r_data["referral_code"].startswith("REF-NORTHERN-")
    assert r_data["reward_per_referral_cad"] == 79.0

    inv_res = client.post(
        "/api/user/referrals/invite",
        json={
            "invited_email": "friend_broker@westernltl.ca",
            "invited_company": "Western LTL Freight Brokers",
        },
    )
    assert inv_res.status_code == 200
    assert inv_res.json()["referral"]["reward_credit_cad"] == 79.0
