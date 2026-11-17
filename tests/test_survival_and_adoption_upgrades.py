"""
Automated Verification Suite for Startup Survival & Broker Adoption Upgrades:
1. Canadian City-to-FSA Auto-Mapper (150+ Canadian cities, French accents, shorthand)
2. Canadian LTL Carrier Format Presets & Big 6 Accessorial Matrix (Tailgate, Heated/Freeze Protect, Residential, etc.)
3. 1-Second 'Paste Shipper Email / RFQ' Smart Parser (/api/quotes/parse-email-text)
4. 24-Hour Concierge 'Done-For-You' Tariff Drop-Box (/api/quotelytics/concierge-upload)
5. Sales Outreach Upgrade (60-Second Loom Video Script & Schedule A $25 Demo Spiff)
"""
import io
import os
import pytest
from fastapi.testclient import TestClient

from main import app
from services.fsa_resolver_service import resolve_city_to_fsa, resolve_location
from services.quotelytics_engine import evaluate_surcharges


def test_01_canadian_city_to_fsa_auto_mapper():
    # Direct city names, French accents, and shorthand codes
    assert resolve_city_to_fsa("Mississauga, ON") == "L5T"
    assert resolve_city_to_fsa("BRAMPTON") == "L6T"
    assert resolve_city_to_fsa("Montréal, QC") == "H3B"
    assert resolve_city_to_fsa("Saint-Laurent, QC") == "H4T"
    assert resolve_city_to_fsa("Calgary, Alberta") == "T2P"
    assert resolve_city_to_fsa("WPG") == "R3C"
    assert resolve_city_to_fsa("Dartmouth, NS") == "B3B"

    # Verify resolve_location populates canonical FSA even when given city/province text
    loc_miss = resolve_location("Mississauga, ON")
    assert loc_miss["is_resolved"] is True
    assert loc_miss["fsa"] == "L5T"
    assert loc_miss["province"] == "ON"

    loc_mtl = resolve_location("Montréal, QC")
    assert loc_mtl["is_resolved"] is True
    assert loc_mtl["fsa"] == "H3B"
    assert loc_mtl["province"] == "QC"


def test_02_smart_shipper_email_parser_endpoint():
    client = TestClient(app)

    # 1. Postal codes + skids + lbs + tailgate + heated
    sample_1 = (
        "Hi dispatch, need a quick LTL quote for 4 skids, 2,450 lbs, 48x40x60 "
        "from Mississauga L5T 1A1 to Calgary T2P 2M5, needs tailgate and heated service."
    )
    res1 = client.post("/api/quotes/parse-email-text", json={"text": sample_1})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["origin"] == "L5T 1A1"
    assert d1["destination"] == "T2P 2M5"
    assert d1["origin_fsa"] == "L5T"
    assert d1["dest_fsa"] == "T2P"
    assert d1["skid_count"] == 4
    assert d1["weight_lbs"] == 2450.0
    assert d1["length"] == 48.0 and d1["width"] == 40.0 and d1["height"] == 60.0
    assert "tailgate" in d1["accessorials"]
    assert "heated" in d1["accessorials"]

    # 2. City names (no postal codes) + kg auto-conversion + residential + appointment
    sample_2 = (
        "Good morning, please quote 2 pallets (1,000 kg total) from Brampton to Winnipeg. "
        "This is a residential delivery and requires a delivery appointment."
    )
    res2 = client.post("/api/quotes/parse-email-text", json={"text": sample_2})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["origin_fsa"] == "L6T"
    assert d2["dest_fsa"] == "R3C"
    assert d2["skid_count"] == 2
    assert d2["weight_unit_source"] == "kg_converted_to_lb"
    assert 2204.0 <= d2["weight_lbs"] <= 2205.0
    assert "residential" in d2["accessorials"]
    assert "appointment" in d2["accessorials"]


def test_03_carrier_presets_and_big_6_accessorial_matrix():
    import uuid
    client = TestClient(app)

    # Register & authenticate a fresh broker
    reg_res = client.post("/api/auth/register", data={
        "name": "Adoption Upgrade Broker",
        "email": f"adoption_{uuid.uuid4().hex[:8]}@canadianltl.ca",
        "password": "Password10CharsMin!",
        "company": "Adoption LTL Brokerage Inc.",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })
    assert reg_res.status_code == 200

    # 1. Fetch carrier presets & Big 6 catalog
    presets_res = client.get("/api/quotelytics/carrier-presets")
    assert presets_res.status_code == 200
    pdata = presets_res.json()
    preset_ids = {p["id"] for p in pdata["presets"]}
    assert "MANITOULIN_CWT" in preset_ids
    assert "DAY_AND_ROSS_CWT" in preset_ids
    big6_codes = {a["code"] for a in pdata["big_6_accessorials"]}
    assert {"TAILGATE", "HEATED", "RESIDENTIAL", "APPOINTMENT", "INSIDE_DELIVERY", "LIMITED_ACCESS"} == big6_codes

    # 2. Upload a CSV rate sheet and configure its Big 6 Accessorial Matrix
    csv_bytes = (
        "Carrier,Manitoulin Transport\n"
        "Currency,CAD\n"
        "Weight Unit,LB\n"
        "Origin,Destination,Min,L5C,M5C,M1M\n"
        "M5V,T2P,125.00,42.50,38.00,32.00\n"
    ).encode("utf-8")
    up_res = client.post(
        "/api/quotelytics/sheets/upload",
        files={"file": ("manitoulin_test.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert up_res.status_code == 200
    sheet_id = up_res.json()["sheet_id"]

    # Upsert custom Big 6 Canadian accessorials on this sheet (including Winter Heated 15% w/ $50 min floor)
    acc_res = client.post(
        f"/api/quotelytics/sheets/{sheet_id}/accessorials",
        json={
            "accessorials": [
                {"code": "TAILGATE", "fee_type": "FLAT", "amount": 65.0},
                {"code": "HEATED", "fee_type": "PERCENTAGE", "amount": 15.0, "min_fee": 50.0},
                {"code": "LIMITED_ACCESS", "fee_type": "FLAT", "amount": 80.0},
            ]
        },
    )
    assert acc_res.status_code == 200
    surcharges = acc_res.json()["surcharges"]
    assert len(surcharges) == 3

    # Verify deterministic surcharge evaluation (Base freight $200 -> 15% Heated = $30, floored at $50 min_fee!)
    active_list, total_sur = evaluate_surcharges(
        surcharges=surcharges,
        requested_accessorials=["tailgate", "heated", "limited_access"],
        destination="CALGARY, AB",
        billable_weight=1000.0,
        base_rate=200.0,
    )
    assert len(active_list) == 3
    by_code = {item["code"]: item["amount"] for item in active_list}
    assert by_code["TAILGATE"] == 65.0
    assert by_code["HEATED"] == 50.0  # 15% of $200 is $30, so the $50 minimum floor applies!
    assert by_code["LIMITED_ACCESS"] == 80.0
    assert total_sur == 195.0


def test_04_concierge_24h_tariff_dropbox_workflow():
    client = TestClient(app)

    client.post("/api/auth/register", data={
        "name": "Concierge Broker",
        "email": "concierge_broker@ontario3pl.ca",
        "password": "Password10CharsMin!",
        "company": "Busy Dispatch 3PL",
        "origin_zip": "L5T 1A1",
        "terms": "true",
    })

    csv_1 = b"Origin,Destination,Min,L5C\nL5T,R3C,110.00,35.00\n"
    csv_2 = b"Origin,Destination,Min,L5C\nL5T,T2P,140.00,45.00\n"

    res = client.post(
        "/api/quotelytics/concierge-upload",
        files=[
            ("files", ("carrier_a_messy.csv", io.BytesIO(csv_1), "text/csv")),
            ("files", ("carrier_b_messy.csv", io.BytesIO(csv_2), "text/csv")),
        ],
        data={
            "carrier_preset": "MANITOULIN_CWT",
            "notes": "Please calibrate our 2 Western Canada sheets with 12% default markup.",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    req_obj = data["concierge_request"]
    assert req_obj["id"].startswith("cnr_")
    assert req_obj["status"] == "PENDING_CALIBRATION"
    assert req_obj["sla_hours"] == 24
    assert len(req_obj["filenames"]) == 2

    # List concierge requests for this broker
    list_res = client.get("/api/quotelytics/concierge-requests")
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1


def test_05_loom_script_and_demo_spiff_documents_exist():
    repo_root = os.path.dirname(os.path.dirname(__file__))
    loom_md = os.path.join(repo_root, "marketing", "LOOM_60_SECOND_VIDEO_SCRIPT.md")
    assert os.path.isfile(loom_md)
    with open(loom_md, "r", encoding="utf-8") as f:
        loom_text = f.read()
    assert "60-SECOND LOOM VIDEO SCRIPT" in loom_text
    assert "24-Hour Concierge" in loom_text

    rep_md = os.path.join(repo_root, "incorporation_documents", "10_Independent_Sales_Rep_and_Milestone_Equity_Agreement.md")
    assert os.path.isfile(rep_md)
    with open(rep_md, "r", encoding="utf-8") as f:
        rep_text = f.read()
    assert "SCHEDULE \"A\" — GRANT-FUNDED QUALIFIED LIVE DEMO SPIFF" in rep_text
    assert "$25.00 CAD" in rep_text
