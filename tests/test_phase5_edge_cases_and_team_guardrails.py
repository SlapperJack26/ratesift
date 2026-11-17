"""
Automated Verification Suite for Phase 5:
1. 1-Click Load 3 Sample Canadian LTL Tariffs (Sandbox Mode) & Purge (/api/quotelytics/sheets/seed-sample-tariffs & purge-sample-tariffs)
2. Mixed-Skid, Non-Stackable (84" Vertical Cube Rule) & Over-Length (>=96" / >=144") Engine (/api/quotes/cube-density-check)
3. Canadian $2.00/lb Statutory Cargo Liability Gap & TDG (Hazmat) BOL Guardrail (/api/quotes/liability-and-tdg-check & /api/quotes/dispatch-documents)
4. 1-Click Carrier Spot-Rate RFQ Blast Generator & Ad-Hoc Spot Quote Logger (/api/quotes/spot-rfq-template & /api/quotes/spot-quote-log)
5. Brokerage Owner Minimum Margin Guardrails & Master Tariff Lock (/api/user/guardrails, /api/quotes/guardrail-check & HTTP 423 Delete Lock)
6. Live Historical Lane Price Intelligence ('Institutional Win/Loss Memory') (/api/quotes/lane-intelligence)
"""
import io
import uuid
import openpyxl
from fastapi.testclient import TestClient

from main import app


def _register_fresh_broker(client: TestClient, company: str = "Phase5 Test Brokerage"):
    email = f"phase5_{uuid.uuid4().hex[:8]}@canadianltl.ca"
    res = client.post(
        "/api/auth/register",
        data={
            "name": "Dylan Dispatcher",
            "email": email,
            "password": "Password10CharsMin!",
            "company": company,
            "origin_zip": "M5V 2T6",
            "terms": "true",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _make_simple_rate_sheet_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tariff"
    ws.append(["Origin", "Destination", "Min", "L5C", "500-999", "1000-1999", "2000+"])
    ws.append(["TORONTO, ON", "CALGARY, AB", 150.0, 42.0, 36.0, 31.0, 26.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_01_seed_and_purge_sample_canadian_ltl_tariffs():
    client = TestClient(app)
    _register_fresh_broker(client, "Cold Start Freight Inc.")

    # Initially Free Starter has 0 sheets used
    q0 = client.get("/api/user/quota").json()
    assert q0["sheets_uploaded"] == 0

    # 1. Seed 3 Sample Canadian LTL Tariffs
    seed_res = client.post("/api/quotelytics/sheets/seed-sample-tariffs")
    assert seed_res.status_code == 200, seed_res.text
    sdata = seed_res.json()
    assert sdata["seeded_count"] == 3
    assert len(sdata["sheet_ids"]) == 3

    # Verify Free Starter 3-sheet upload quota was NOT consumed by sandbox sample tariffs
    q1 = client.get("/api/user/quota").json()
    assert q1["sheets_uploaded"] == 0

    # 2. Immediately calculate a live quote on M5V 2T6 -> T2P 1J9 across all 3 sample carriers
    calc_res = client.post(
        "/api/quotelytics/quotes/calculate",
        json={
            "origin": "M5V 2T6",
            "destination": "T2P 1J9",
            "actual_weight": 1200.0,
            "skid_count": 2,
            "accessorials": ["liftgate"],
        },
    )
    assert calc_res.status_code == 200, calc_res.text
    cdata = calc_res.json()
    assert cdata["total_options"] == 3
    carrier_names = {q["carrier_name"] for q in cdata["quotes"]}
    assert "[SAMPLE] Manitoulin Transport" in carrier_names
    assert "[SAMPLE] Day & Ross Freight" in carrier_names
    assert "[SAMPLE] Overland West Freight Lines" in carrier_names

    # 3. 1-Click Purge removes all 3 sandbox sample tariffs cleanly
    purge_res = client.delete("/api/quotelytics/sheets/purge-sample-tariffs")
    assert purge_res.status_code == 200, purge_res.text
    assert purge_res.json()["purged_count"] == 3


def test_02_mixed_skid_non_stackable_84in_and_over_length_engine():
    client = TestClient(app)

    # 1. Non-Stackable 84" height penalty on a 36" tall pallet (48x40x36 -> penalized to 48x40x84 = 93.33 cu.ft -> 934 lbs)
    ns_res = client.post(
        "/api/quotes/cube-density-check",
        json={
            "actual_weight_lbs": 400.0,
            "length_in": 48.0,
            "width_in": 40.0,
            "height_in": 36.0,
            "skid_count": 1,
            "non_stackable": True,
        },
    )
    assert ns_res.status_code == 200, ns_res.text
    ns_data = ns_res.json()
    assert ns_data["non_stackable_applied"] is True
    assert ns_data["effective_height_in"] == 84.0
    assert ns_data["density_weight_lbs"] >= 933.0
    assert ns_data["effective_billable_weight_lbs"] >= 933.0

    # 2. Mixed-skid lines containing a 102" Over-Length crate (OVER_LENGTH_8FT: +$125 CAD)
    ol_res = client.post(
        "/api/quotes/cube-density-check",
        json={
            "skid_lines": [
                {"qty": 2, "length_in": 48, "width_in": 40, "height_in": 48, "weight_lbs": 900, "non_stackable": False},
                {"qty": 1, "length_in": 102, "width_in": 44, "height_in": 60, "weight_lbs": 600, "non_stackable": True},
            ]
        },
    )
    assert ol_res.status_code == 200, ol_res.text
    ol_data = ol_res.json()
    assert ol_data["skid_count"] == 3
    assert ol_data["skid_lines_evaluated"] == 2
    assert ol_data["actual_weight_lbs"] == 1500.0
    assert ol_data["is_over_length"] is True
    assert ol_data["over_length_code"] == "OVER_LENGTH_8FT"
    assert ol_data["over_length_surcharge_cad"] == 125.0

    # 3. Extreme-length 148" crate (EXTREME_LENGTH_12FT: +$250 CAD)
    ex_res = client.post(
        "/api/quotes/cube-density-check",
        json={
            "actual_weight_lbs": 1200.0,
            "length_in": 148.0,
            "width_in": 48.0,
            "height_in": 48.0,
            "skid_count": 1,
        },
    )
    assert ex_res.status_code == 200
    assert ex_res.json()["over_length_code"] == "EXTREME_LENGTH_12FT"
    assert ex_res.json()["over_length_surcharge_cad"] == 250.0


def test_03_canadian_2_dollar_lb_liability_gap_and_tdg_bol_guardrail():
    client = TestClient(app)
    _register_fresh_broker(client, "Precision Hazmat & Cargo")

    # 500 lb medical CNC skid worth $40,000 CAD -> Statutory cap = $1,000 -> Uninsured Gap = $39,000 + UN1263 Class 3 TDG
    check_res = client.post(
        "/api/quotes/liability-and-tdg-check",
        json={
            "weight_lbs": 500.0,
            "declared_value_cad": 40000.0,
            "is_tdg": True,
            "un_number": "UN1263",
            "tdg_class": "3",
            "packing_group": "II",
        },
    )
    assert check_res.status_code == 200, check_res.text
    cdata = check_res.json()
    assert cdata["statutory_carrier_max_liability_cad"] == 1000.0
    assert cdata["uninsured_liability_gap_cad"] == 39000.0
    assert cdata["has_liability_gap"] is True
    assert cdata["estimated_excess_valuation_fee_cad"] == 975.0
    assert cdata["tdg_compliant"] is True
    assert cdata["tdg_surcharge_estimate_cad"] == 85.0
    assert "CAN-UTEC" in cdata["bol_tdg_declaration"]

    # Stamp onto Canadian Straight BOL & Carrier Rate Confirmation
    docs_res = client.post(
        "/api/quotes/dispatch-documents",
        json={
            "quote_data": {
                "carrier_name": "Manitoulin Transport",
                "origin": "TORONTO, ON",
                "destination": "CALGARY, AB",
                "weight_lbs": 500.0,
                "skid_count": 1,
                "base_rate": 410.0,
                "wholesale_total": 410.0,
                "declared_value_cad": 40000.0,
                "is_tdg": True,
                "un_number": "UN1263",
                "tdg_class": "3",
                "packing_group": "II",
            }
        },
    )
    assert docs_res.status_code == 200, docs_res.text
    ddata = docs_res.json()
    bol = ddata["straight_bol"]
    rate_con = ddata["rate_confirmation"]
    assert bol["cargo_line"]["declared_value_cad"] == 40000.0
    assert bol["cargo_line"]["is_tdg"] is True
    assert "DECLARED VALUE: $40,000.00 CAD" in bol["special_instructions"]
    assert "UN1263" in bol["special_instructions"]
    assert rate_con["cargo_liability_and_tdg"]["uninsured_liability_gap_cad"] == 39000.0


def test_04_carrier_spot_rfq_blast_and_adhoc_spot_quote_logger():
    client = TestClient(app)
    _register_fresh_broker(client, "Northern Spot Logistics")

    # 1. Generate 1-click Spot RFQ Email Blast for an uncovered remote corridor
    rfq_res = client.post(
        "/api/quotes/spot-rfq-template",
        json={
            "origin": "Sudbury, ON",
            "destination": "Whitehorse, YT",
            "weight_lbs": 800.0,
            "skid_count": 2,
            "length_in": 48.0,
            "width_in": 40.0,
            "height_in": 42.0,
            "non_stackable": True,
            "accessorials": ["tailgate", "heated"],
        },
    )
    assert rfq_res.status_code == 200, rfq_res.text
    rfq = rfq_res.json()
    assert "SUDBURY, ON" in rfq["origin_normalized"]
    assert "WHITEHORSE, YT" in rfq["destination_normalized"]
    assert "NON-STACKABLE" in rfq["email_body"]
    assert "TAILGATE, HEATED" in rfq["email_body"]

    # 2. Log carrier spot quote and get normalized quote + margin
    log_res = client.post(
        "/api/quotes/spot-quote-log",
        json={
            "carrier_name": "Polar Yukon Express",
            "origin": "Sudbury, ON",
            "destination": "Whitehorse, YT",
            "spot_wholesale_cad": 1450.0,
            "weight_lbs": 800.0,
            "skid_count": 2,
            "transit_days": 7,
            "markup_pct": 18.0,
            "spot_reference": "PYX-SPOT-402",
        },
    )
    assert log_res.status_code == 200, log_res.text
    sq = log_res.json()["spot_quote"]
    assert sq["client_total"] == 1711.0
    assert sq["broker_margin"] == 261.0
    assert "PYX-SPOT-402" in sq["source_coordinate"]
    assert sq["normalized_quote"]["is_spot_quote"] is True

    # 3. Verify spot quote appears in list endpoint
    list_res = client.get("/api/quotes/spot-quotes")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1


def test_05_brokerage_owner_margin_guardrails_and_master_tariff_lock():
    client = TestClient(app)
    _register_fresh_broker(client, "Locked Margin Brokerage")

    # Upload a proprietary master tariff
    up_res = client.post(
        "/api/quotelytics/sheets/upload",
        files={
            "file": (
                "master_manitoulin.xlsx",
                _make_simple_rate_sheet_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert up_res.status_code == 200, up_res.text
    sheet_id = up_res.json()["sheet_id"]

    # 1. Configure Owner Margin Guardrails (min 14% or +$55) + Master Tariff Lock ON + PIN "7788"
    set_res = client.post(
        "/api/user/guardrails",
        json={
            "min_allowed_markup_pct": 14.0,
            "min_allowed_margin_dollars": 55.0,
            "enforce_guardrails": True,
            "lock_master_tariffs": True,
            "owner_override_pin": "7788",
        },
    )
    assert set_res.status_code == 200, set_res.text
    assert set_res.json()["guardrails"]["lock_master_tariffs"] is True
    assert "owner_override_pin" not in set_res.json()["guardrails"]

    # 2. Dispatcher quoting at 6% on $500 wholesale ($530 sell) violates owner floor ($570 sell) -> auto-raised
    bad_chk = client.post(
        "/api/quotes/guardrail-check",
        json={"wholesale_cost_cad": 500.0, "proposed_markup_pct": 6.0},
    )
    assert bad_chk.status_code == 200
    ev_bad = bad_chk.json()["evaluation"]
    assert ev_bad["status"] == "AUTO_RAISED_TO_FLOOR"
    assert ev_bad["is_compliant"] is False
    assert ev_bad["approved_sell_cad"] == 570.0

    # 3. With valid Owner Override PIN "7788", 6% quote is approved
    pin_chk = client.post(
        "/api/quotes/guardrail-check",
        json={"wholesale_cost_cad": 500.0, "proposed_markup_pct": 6.0, "override_pin": "7788"},
    )
    assert pin_chk.status_code == 200
    ev_pin = pin_chk.json()["evaluation"]
    assert ev_pin["status"] == "APPROVED_BY_OWNER_PIN"
    assert ev_pin["is_compliant"] is True
    assert ev_pin["approved_sell_cad"] == 530.0

    # 4. Deleting the locked master sheet without PIN returns HTTP 423 Locked
    del_locked = client.delete(f"/api/quotelytics/sheets/{sheet_id}")
    assert del_locked.status_code == 423, del_locked.text

    # 5. Deleting with valid Owner Override PIN succeeds (HTTP 200)
    del_ok = client.delete(f"/api/quotelytics/sheets/{sheet_id}?override_pin=7788")
    assert del_ok.status_code == 200, del_ok.text


def test_06_live_historical_lane_price_intelligence():
    client = TestClient(app)
    _register_fresh_broker(client, "Lane Memory Freight Co.")

    # Create 3 proposals on M5V 2T6 -> T2P 1J9: 2 WON at 18% & 20% markup, 1 LOST at 28% markup
    proposals = [
        (500.0, 590.0, 18.0, "WON"),
        (500.0, 600.0, 20.0, "WON"),
        (500.0, 640.0, 28.0, "LOST"),
    ]
    for wholesale, sell, mk, decision in proposals:
        sh = client.post(
            "/api/proposals/share",
            json={
                "client_name": "Acme Manufacturing",
                "origin": "M5V 2T6",
                "destination": "T2P 1J9",
                "wholesale_cost": wholesale,
                "client_total": sell,
                "markup_pct": mk,
                "currency": "CAD",
            },
        )
        assert sh.status_code == 200, sh.text
        tok = sh.json()["shared_proposal"]["token"]
        resp = client.post(f"/q/{tok}/respond", json={"decision": decision})
        assert resp.status_code == 200, resp.text

    # Query Live Historical Lane Price Intelligence by normalized city names (Toronto -> Calgary)
    intel_res = client.get("/api/quotes/lane-intelligence?origin=Toronto, ON&destination=Calgary, AB")
    assert intel_res.status_code == 200, intel_res.text
    intel = intel_res.json()["intelligence"]
    assert intel["historical_quotes_count"] == 3
    assert intel["won_count"] == 2
    assert intel["lost_count"] == 1
    assert intel["win_rate_pct"] == 66.7
    assert intel["avg_winning_markup_pct"] == 19.0
    assert intel["avg_lost_markup_pct"] == 28.0
    assert intel["recommended_sweet_spot_markup_pct"] == 20.0
    assert "Recommended Sweet-Spot Markup: 20.0%" in intel["guidance_banner"]
