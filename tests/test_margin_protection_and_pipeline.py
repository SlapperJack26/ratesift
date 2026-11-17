"""
Automated Verification Suite for Phase 2: Margin Protection, Retention & Pipeline Plan:
1. 105-Brokerage Canadian LTL Target Directory & Cold Call Playbook
2. Canadian LTL 10 lb/cu.ft Cube-Out & Linear-Foot Calculator (/api/quotes/cube-density-check)
3. Cross-Border US ZIP / ZIP3 Resolver & USD-to-CAD Proposal FX Converter (/api/proposals/convert-currency)
4. Interactive Shareable Shipper Quote Links (/q/{token}) & Won/Lost Margin Analytics (/api/quotes/win-loss-analytics)
5. Weekly Diesel Price ($/L) -> Carrier FSC Bracket Calculator (/api/fuel-index/calculate-from-diesel)
6. Automated Tariff Expiry Alerts & 1-Click % General Rate Increase (GRI) Bumper (/api/quotelytics/sheets/{id}/apply-gri)
"""
import io
import os
import pytest
from fastapi.testclient import TestClient

from main import app
from services.fsa_resolver_service import resolve_location, extract_fsa
from services.proposal_service import build_client_proposal_data


def test_01_105_canadian_prospects_and_cold_call_playbook():
    from scripts.build_100_canadian_prospects import RAW_PROSPECTS, build_105_prospects_directory

    assert len(RAW_PROSPECTS) >= 100
    xlsx_path, csv_path = build_105_prospects_directory()
    assert os.path.isfile(xlsx_path)
    assert os.path.isfile(csv_path)

    repo_root = os.path.dirname(os.path.dirname(__file__))
    playbook_md = os.path.join(repo_root, "marketing", "COLD_CALL_AND_VOICEMAIL_PLAYBOOK.md")
    assert os.path.isfile(playbook_md)
    with open(playbook_md, "r", encoding="utf-8") as f:
        text = f.read()
    assert "COLD CALL, GATEKEEPER & VOICEMAIL PLAYBOOK" in text
    assert "24-Hour Concierge" in text


def test_02_canadian_10lb_cuft_cube_out_and_linear_foot_calculator():
    client = TestClient(app)

    # 2 bulky skids (48x40x72 in each = 160.0 cu.ft total) weighing only 600 lbs actual weight
    # At 10 lbs/cu.ft Canadian LTL density rule -> 1,600 lbs billable density weight (+1,000 lbs delta!)
    res = client.post(
        "/api/quotes/cube-density-check",
        json={
            "actual_weight_lbs": 600.0,
            "length_in": 48.0,
            "width_in": 40.0,
            "height_in": 72.0,
            "skid_count": 2,
            "density_rule_lbs_per_cuft": 10.0,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_cubed_out"] is True
    assert data["cubic_feet"] == 160.0
    assert data["density_weight_lbs"] == 1600.0
    assert data["effective_billable_weight_lbs"] == 1600.0
    assert data["weight_delta_lbs"] == 1000.0
    assert "Cube-Out Alert" in data["warning_message"]

    # Heavy dense skid (2,000 lbs on 1 skid 48x40x48 = 53.33 cu.ft -> 534 lbs density weight -> NOT cubed out)
    res_dense = client.post(
        "/api/quotes/cube-density-check",
        json={
            "actual_weight_lbs": 2000.0,
            "length_in": 48.0,
            "width_in": 40.0,
            "height_in": 48.0,
            "skid_count": 1,
            "density_rule_lbs_per_cuft": 10.0,
        },
    )
    assert res_dense.status_code == 200
    assert res_dense.json()["is_cubed_out"] is False
    assert res_dense.json()["effective_billable_weight_lbs"] == 2000.0


def test_03_cross_border_us_zip_resolver_and_usd_to_cad_proposal_converter():
    # 1. Verify US 5-digit ZIP and city name resolution
    assert extract_fsa("60601") == "606"
    assert extract_fsa("Chicago, IL 60601") == "606"
    loc_chi = resolve_location("60601")
    assert loc_chi["is_resolved"] is True
    assert loc_chi["country"] == "US"
    assert loc_chi["city"] == "CHICAGO"
    assert loc_chi["province"] == "IL"

    # 2. Verify USD -> CAD proposal conversion with Broker FX Buffer (+1.5% on 1.3850 spot)
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "Cross Border Broker",
        "email": "crossborder_fx@canadian3pl.ca",
        "password": "Password10CharsMin!",
        "company": "Cross Border LTL Corp",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })

    usd_proposal = build_client_proposal_data(
        quote_data={
            "origin": "TORONTO, ON",
            "destination": "CHICAGO, IL",
            "base_rate": 400.0,
            "total_surcharges": 50.0,
            "final_total": 450.0,
            "currency": "USD",
            "surcharges": [{"name": "Cross-Border Customs Clearance", "amount": 50.0}],
        },
        client_name="Maple Manufacturing Inc.",
        markup_pct=15.0,
    )
    assert usd_proposal["pricing"]["currency"] == "USD"
    assert usd_proposal["pricing"]["client_total"] == 510.0  # $400 * 1.15 + $50

    conv_res = client.post(
        "/api/proposals/convert-currency",
        json={
            "proposal_data": usd_proposal,
            "target_currency": "CAD",
            "fx_rate": 1.3850,
            "broker_fx_buffer_pct": 1.5,
        },
    )
    assert conv_res.status_code == 200
    cad_prop = conv_res.json()["proposal"]
    assert cad_prop["pricing"]["currency"] == "CAD"
    assert cad_prop["pricing"]["original_currency"] == "USD"
    assert cad_prop["fx_conversion"]["effective_fx_rate"] > 1.3850
    assert cad_prop["pricing"]["client_total"] > 700.0


def test_04_interactive_shareable_shipper_link_and_win_loss_analytics():
    import uuid
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "Win Rate Broker",
        "email": f"winrate_{uuid.uuid4().hex[:8]}@ontariofreight.ca",
        "password": "Password10CharsMin!",
        "company": "WinRate Logistics Inc.",
        "origin_zip": "L5T 1A1",
        "terms": "true",
    })

    # 1. Create a shareable shipper quote link
    share_res = client.post(
        "/api/proposals/share",
        json={
            "client_name": "Northern Industrial Shippers",
            "origin": "MISSISSAUGA, ON (L5T)",
            "destination": "CALGARY, AB (T2P)",
            "carrier_name": "Manitoulin Transport",
            "service_name": "Standard Road LTL",
            "transit_days": 4,
            "weight_lbs": 2400.0,
            "skid_count": 3,
            "wholesale_cost": 500.0,
            "client_total": 625.0,
            "currency": "CAD",
            "markup_pct": 25.0,
        },
    )
    assert share_res.status_code == 200
    shared = share_res.json()["shared_proposal"]
    token = shared["token"]
    assert token.startswith("q_tok_")
    assert shared["margin_dollars"] == 125.0

    # 2. Shipper opens the public link /q/{token} (no login required, wholesale cost hidden!)
    page_res = client.get(f"/q/{token}")
    assert page_res.status_code == 200
    html = page_res.text
    assert "Northern Industrial Shippers" in html
    assert "$625.00" in html
    assert "500.00" not in html  # Wholesale cost is strictly hidden from shipper!

    # 3. Shipper clicks "Approve Quote & Request Pickup" ('WON')
    resp_res = client.post(
        f"/q/{token}/respond",
        json={
            "decision": "WON",
            "shipper_contact_name": "Sarah Jenkins",
            "shipper_notes": "PO #88412 - Ready at Dock 4 by 2:00 PM",
        },
    )
    assert resp_res.status_code == 200
    assert resp_res.json()["proposal"]["status"] == "WON"

    # 4. Broker checks Won/Lost Margin Analytics
    an_res = client.get("/api/quotes/win-loss-analytics")
    assert an_res.status_code == 200
    an = an_res.json()["analytics"]
    assert an["won_count"] == 1
    assert an["win_rate_pct"] == 100.0
    assert an["won_revenue_cad"] == 625.0
    assert an["won_margin_cad"] == 125.0


def test_05_weekly_diesel_to_fsc_and_tariff_expiry_gri_bumper():
    import uuid
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "GRI & Fuel Broker",
        "email": f"gri_fuel_{uuid.uuid4().hex[:8]}@canadianltl.ca",
        "password": "Password10CharsMin!",
        "company": "GRI Margin Guard 3PL",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })

    # 1. Calculate Canadian LTL FSC % from weekly retail diesel price ($1.685/L -> 31.50% LTL FSC)
    fsc_res = client.post(
        "/api/fuel-index/calculate-from-diesel",
        json={"diesel_price_cad_litre": 1.685, "mode": "LTL"},
    )
    assert fsc_res.status_code == 200
    fsc_data = fsc_res.json()
    assert fsc_data["ltl_surcharge_percent"] == 31.5

    # 2. Upload a rate sheet expiring soon (2026-11-20) and test expiry alert + 1-click +5.0% GRI bumper
    csv_bytes = (
        "Carrier,Midland Transport\n"
        "Effective Date,2026-01-01\n"
        "Expiry Date,2026-11-20\n"
        "Currency,CAD\n"
        "Weight Unit,LB\n"
        "Origin,Destination,Min,L5C,M5C\n"
        "M5V,B3J,100.00,40.00,30.00\n"
    ).encode("utf-8")
    up_res = client.post(
        "/api/quotelytics/sheets/upload",
        files={"file": ("midland_expiring.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert up_res.status_code == 200
    sheet_id = up_res.json()["sheet_id"]

    # Check expiry alerts (within 365 days so it always catches 2026-11-20)
    alert_res = client.get("/api/quotelytics/sheets-expiry-alerts?within_days=365")
    assert alert_res.status_code == 200
    alerts = alert_res.json()["alerts"]
    assert any(a["sheet_id"] == sheet_id for a in alerts)

    # Apply +5.0% General Rate Increase (GRI) in 1 click -> Min $100.00 becomes $105.00, L5C $40.00 becomes $42.00
    gri_res = client.post(
        f"/api/quotelytics/sheets/{sheet_id}/apply-gri",
        json={
            "gri_percent": 5.0,
            "new_effective_date": "2026-11-21",
            "new_expiry_date": "2027-11-21",
        },
    )
    assert gri_res.status_code == 200
    g_data = gri_res.json()["gri_result"]
    assert g_data["gri_percent_applied"] == 5.0
    assert g_data["new_version"] == 2
    assert g_data["expiry_date"] == "2027-11-21"

    # Verify updated rates on the sheet
    sheet_detail = client.get(f"/api/quotelytics/sheets/{sheet_id}").json()
    mins = sheet_detail["minimums"]
    assert mins[0]["min_charge"] == 105.0
