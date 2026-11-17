"""
Automated Verification Suite for Phase 3:
1. Deterministic PDF Carrier Rate Sheet Table Extractor (.pdf upload support)
2. 1-Click Carrier Rate Confirmation ('Rate Con') & Canadian Straight Bill of Lading (BOL) Generator
3. Shipper-Specific Margin Profiles & Minimum Dollar Profit Floor ($ CAD)
4. Day-30 Beta Renewal ROI & Value Captured Scorecard (/api/user/roi-scorecard)
5. In-App Sales Rep CRM Pipeline, Call Logger & $25 Spiff / Class B Equity Leaderboard (/api/admin/sales-leaderboard)
6. Interactive Canadian Brokerage ROI Calculator on /pricing
"""
import io
import pytest
from fastapi.testclient import TestClient

from main import app
from services.proposal_service import build_client_proposal_data


def _build_minimal_test_pdf(lines):
    """Constructs a valid minimal PDF byte stream containing the given text lines in PDF Tj operators."""
    content_ops = ["BT", "/F1 10 Tf", "50 750 Td"]
    for ln in lines:
        safe = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_ops.append(f"({safe}) Tj")
        content_ops.append("0 -14 Td")
    content_ops.append("ET")
    stream_bytes = "\n".join(content_ops).encode("latin-1")

    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /Contents 4 0 R >> endobj\n"
        + f"4 0 obj << /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
        + stream_bytes
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    return pdf


def test_01_pdf_carrier_rate_sheet_upload_and_extraction():
    import uuid
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "PDF Tariff Broker",
        "email": f"pdf_broker_{uuid.uuid4().hex[:8]}@canadianltl.ca",
        "password": "Password10CharsMin!",
        "company": "PDF Tariff Brokerage Inc.",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })

    pdf_bytes = _build_minimal_test_pdf([
        "Carrier,Day & Ross",
        "Currency,CAD",
        "Weight Unit,LB",
        "Origin,Destination,Min,L5C,M5C,M1M",
        "M5V,T2P,130.00,44.00,39.50,33.00",
        "L5T,R3C,115.00,36.00,31.00,27.50",
    ])

    up_res = client.post(
        "/api/quotelytics/sheets/upload",
        files={"file": ("day_and_ross_schedule.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert up_res.status_code == 200
    data = up_res.json()
    assert data["sheet_id"].startswith("ql_sheet_")
    assert data["metadata"]["carrier_name"] == "Day & Ross"
    assert data["rate_breaks_count"] >= 2
    assert data["minimums_count"] >= 1


def test_02_dispatch_documents_rate_con_and_straight_bol_generator():
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "Dispatch Docs Broker",
        "email": "dispatch_docs@ontario3pl.ca",
        "password": "Password10CharsMin!",
        "company": "Dispatch Handoff 3PL",
        "origin_zip": "L5T 1A1",
        "terms": "true",
    })

    payload = {
        "quote_data": {
            "carrier_name": "Manitoulin Transport",
            "service_name": "Standard Road LTL",
            "origin": "MISSISSAUGA, ON (L5T)",
            "destination": "CALGARY, AB (T2P)",
            "skid_count": 4,
            "weight_lbs": 2400.0,
            "base_rate": 480.0,
            "total_surcharges": 65.0,
            "wholesale_total": 545.0,
            "client_total": 685.0,  # Broker's marked-up shipper price — must NOT leak onto Carrier Rate Con or BOL!
            "currency": "CAD",
            "source_coordinate": "Sheet 1 • Row 14, Col E",
            "surcharges": [{"name": "Power Tailgate Delivery", "amount": 65.0}],
        },
        "shipper_info": {"company": "Peel Manufacturing Co.", "contact": "Dock 2"},
        "consignee_info": {"company": "Foothills Industrial Supply", "contact": "Receiving Bay B"},
    }

    res = client.post("/api/quotes/dispatch-documents", json=payload)
    assert res.status_code == 200
    body = res.json()

    # 1. Verify Carrier Rate Confirmation uses wholesale net pay ($545.00) and cites exact cell
    rc = body["rate_confirmation"]
    assert rc["rate_con_id"].startswith("RC-")
    assert rc["carrier_pay_breakdown"]["agreed_carrier_net_total"] == 545.0
    assert rc["carrier"]["tariff_citation"] == "Sheet 1 • Row 14, Col E"
    assert "685" not in str(rc)  # Shipper markup strictly hidden from carrier!

    # 2. Verify Canadian Straight Bill of Lading has zero pricing figures and includes lbs + kg
    bol = body["straight_bol"]
    assert bol["bol_number"].startswith("BOL-CA-")
    assert bol["cargo_line"]["skid_count"] == 4
    assert bol["cargo_line"]["weight_lbs"] == 2400.0
    assert bol["cargo_line"]["weight_kg"] > 1080.0
    assert "Power Tailgate Delivery" in bol["checked_accessorials"]
    assert "545" not in str(bol) and "685" not in str(bol)


def test_03_shipper_margin_profiles_and_minimum_dollar_profit_floor():
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "Margin Floor Broker",
        "email": "margin_floor@canadianbroker.ca",
        "password": "Password10CharsMin!",
        "company": "Profit Guard Brokerage",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })

    # 1. Save a Shipper Margin Profile ("Maple Spot Shipper: +12% markup with $50.00 CAD minimum profit floor")
    prof_res = client.post(
        "/api/shippers/profiles",
        json={
            "shipper_name": "Maple Spot Shipper Ltd.",
            "default_markup_pct": 12.0,
            "min_margin_dollars": 50.0,
            "preferred_currency": "CAD",
            "notes": "Spot LTL account — enforce $50 minimum margin on small 1-skid loads.",
        },
    )
    assert prof_res.status_code == 200
    prof = prof_res.json()["profile"]
    assert prof["min_margin_dollars"] == 50.0

    list_res = client.get("/api/shippers/profiles")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1

    # 2. Test Minimum Dollar Profit Floor on a small $120 minimum-charge skid:
    # +12% markup on $120 is only $14.40 profit (< $50 floor), so min_margin_dollars ($50) kicks in -> $170.00 client total!
    prop = build_client_proposal_data(
        quote_data={
            "origin": "TORONTO, ON",
            "destination": "OTTAWA, ON",
            "base_rate": 120.0,
            "total_surcharges": 0.0,
            "final_total": 120.0,
            "currency": "CAD",
        },
        client_name="Maple Spot Shipper Ltd.",
        markup_pct=12.0,
        min_margin_dollars=50.0,
    )
    assert prop["pricing"]["min_margin_floor_applied"] is True
    assert prop["pricing"]["broker_margin_dollars"] == 50.0
    assert prop["pricing"]["client_total"] == 170.0


def test_04_day30_roi_scorecard_and_sales_rep_leaderboard():
    client = TestClient(app)
    client.post("/api/auth/register", data={
        "name": "ROI & Leaderboard Admin",
        "email": "roi_leaderboard@quotelytics.ca",
        "password": "Password10CharsMin!",
        "company": "Quotelytics Test Brokerage",
        "origin_zip": "M5V 2T6",
        "terms": "true",
    })

    # Create a won shared quote so the ROI scorecard has won margin
    share_res = client.post(
        "/api/proposals/share",
        json={
            "client_name": "Scorecard Shipper",
            "origin": "M5V",
            "destination": "T2P",
            "wholesale_cost": 400.0,
            "client_total": 520.0,
        },
    )
    tok = share_res.json()["shared_proposal"]["token"]
    client.post(f"/q/{tok}/respond", json={"decision": "WON"})

    # 1. Check Day-30 Renewal ROI Scorecard
    roi_res = client.get("/api/user/roi-scorecard")
    assert roi_res.status_code == 200
    sc = roi_res.json()["scorecard"]
    assert sc["won_margin_cad"] >= 120.0
    assert sc["total_value_captured_cad"] > sc["beta50_plan_cost_cad"]
    assert sc["roi_multiple_on_beta50"] >= 3.0

    # 2. Log Sales Rep activities (2 qualified live demos with real sheets + 1 closed Business Tier deal at $5,000 ARR)
    client.post(
        "/api/admin/sales-activity",
        json={
            "rep_name": "Rep 1",
            "prospect_company": "Polaris Transportation Group",
            "activity_type": "QUALIFIED_DEMO",
            "province": "ON",
            "sheet_uploaded": True,
        },
    )
    client.post(
        "/api/admin/sales-activity",
        json={
            "rep_name": "Rep 1",
            "prospect_company": "Kriska Logistics",
            "activity_type": "QUALIFIED_DEMO",
            "province": "ON",
            "sheet_uploaded": True,
        },
    )
    lb_res = client.post(
        "/api/admin/sales-activity",
        json={
            "rep_name": "Rep 1",
            "prospect_company": "Polaris Transportation Group",
            "activity_type": "PAID_CLOSED",
            "province": "ON",
            "arr_value_cad": 5000.0,
        },
    )
    assert lb_res.status_code == 200
    rep1 = [r for r in lb_res.json()["leaderboard"] if r["rep_name"] == "Rep 1"][0]
    assert rep1["qualified_demos_count"] >= 2
    assert rep1["demo_spiff_earned_cad"] >= 50.0  # 2 qualified demos * $25 CAD spiff
    assert rep1["verified_arr_cad"] >= 5000.0
    assert rep1["milestone_1_unlocked"] is True  # $5,000 ARR unlocks Milestone 1 (250,000 Class B Shares)!


def test_05_public_pricing_interactive_roi_calculator_renders():
    client = TestClient(app)
    res = client.get("/pricing")
    assert res.status_code == 200
    html = res.text
    assert 'id="brokerage-roi-calculator"' in html
    assert "Calculate Your Dispatch Desk's Monthly Savings" in html
    assert "recalcPublicRoi()" in html
