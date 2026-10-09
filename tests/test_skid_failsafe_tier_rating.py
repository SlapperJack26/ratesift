import io
import pytest
import openpyxl
from starlette.testclient import TestClient
from main import app
from services.ratesift_engine import quote_all_confirmed_carriers

client = TestClient(app)

def create_sample_skid_excel() -> bytes:
    """
    Creates an Excel sheet with:
    Col A (0): Origin
    Col B (1): Destination
    Col C (2): Base Cost / MC
    Col D (3): 1-2 Skids
    Col E (4): 3-4 Skids
    Col F (5): 5-8 Skids
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Direct Skid Carrier"
    ws.append(["Origin", "Destination", "Min Charge", "1-2 Skids", "3-4 Skids", "5-8 Skids"])
    ws.append(["Toronto, ON", "Montreal, QC", "50.00", "75.00", "65.00", "55.00"])
    ws.append(["Toronto, ON", "Winnipeg, MB", "85.00", "140.00", "125.00", "110.00"])
    
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

def test_skid_tier_mapping_and_rating():
    # 1. Upload workbook
    content = create_sample_skid_excel()
    up_res = client.post(
        "/jobs",
        files={"file": ("Direct_Skid_Carrier.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "usr_alex_rivers", "X-Tenant-Id": "usr_alex_rivers"}
    )
    assert up_res.status_code == 200
    job_id = up_res.json()["job_id"]

    # 2. Confirm Mapping with Skid mode, Base Cost column (Col C / idx 2), and 3 skid tiers
    mapping_payload = {
        "header_row": 0,
        "sheet_name": "Direct Skid Carrier",
        "mode": "skid",
        "origin": 0,
        "destination": 1,
        "base_cost_column": 2,
        "max_skid_capacity": 8,
        "rate_columns": [3, 4, 5],
        "skid_tiers": [
            {"column": 3, "skid_range": "1-2", "min_units": 1.0, "max_units": 2.0, "rate_type": "PER_SKID"},
            {"column": 4, "skid_range": "3-4", "min_units": 3.0, "max_units": 4.0, "rate_type": "PER_SKID"},
            {"column": 5, "skid_range": "5-8", "min_units": 5.0, "max_units": 8.0, "rate_type": "PER_SKID"},
        ],
        "remember_mapping": False
    }

    map_res = client.post(
        f"/jobs/{job_id}/mapping",
        json=mapping_payload,
        headers={"X-User-Id": "usr_alex_rivers", "X-Tenant-Id": "usr_alex_rivers"}
    )
    assert map_res.status_code == 200
    assert map_res.json()["status"] == "ready"

    # 3. Process job (Gated process triggers ingestion into rs_rate_sheets & rs_weight_breaks & rs_carrier_minimums)
    proc_res = client.post(
        f"/jobs/{job_id}/process",
        headers={"X-User-Id": "usr_alex_rivers", "X-Tenant-Id": "usr_alex_rivers"}
    )
    assert proc_res.status_code == 200
    assert proc_res.json()["status"] in ("done", "processed")
    assert proc_res.json().get("sheet_id") is not None

    # 4. Verify RateSift Engine quotes accurately based on Skid Tiers and Base Cost MC
    # Scenario A: 2 skids Toronto -> Montreal
    # Base Cost = $50.00 MC, 1-2 Skids rate = $75.00/skid -> 2 * 75 = 150 + 50 MC = 200.00 base charge
    res_2skids = quote_all_confirmed_carriers(
        user_id="usr_alex_rivers",
        origin="Toronto, ON",
        destination="Montreal, QC",
        actual_weight=2000.0,
        skid_count=2,
    )
    quotes_2skids = res_2skids.get("quotes", [])
    assert len(quotes_2skids) >= 1
    carrier_q = next((q for q in quotes_2skids if "Direct Skid Carrier" in q["carrier_name"]), None)
    assert carrier_q is not None
    # Verify base charge calculation: 50 MC + 2 * 75 = 200.00
    assert carrier_q["base_charge"] == 200.00

    # Scenario B: 4 skids Toronto -> Montreal
    # Base Cost = $50.00 MC, 3-4 Skids rate = $65.00/skid -> 4 * 65 = 260 + 50 MC = 310.00 base charge
    res_4skids = quote_all_confirmed_carriers(
        user_id="usr_alex_rivers",
        origin="Toronto, ON",
        destination="Montreal, QC",
        actual_weight=4000.0,
        skid_count=4,
    )
    quotes_4skids = res_4skids.get("quotes", [])
    carrier_q4 = next((q for q in quotes_4skids if "Direct Skid Carrier" in q["carrier_name"]), None)
    assert carrier_q4 is not None
    assert carrier_q4["base_charge"] == 310.00

    # Scenario C: 7 skids Toronto -> Montreal
    # Base Cost = $50.00 MC, 5-8 Skids rate = $55.00/skid -> 7 * 55 = 385 + 50 MC = 435.00 base charge
    res_7skids = quote_all_confirmed_carriers(
        user_id="usr_alex_rivers",
        origin="Toronto, ON",
        destination="Montreal, QC",
        actual_weight=7000.0,
        skid_count=7,
    )
    quotes_7skids = res_7skids.get("quotes", [])
    carrier_q7 = next((q for q in quotes_7skids if "Direct Skid Carrier" in q["carrier_name"]), None)
    assert carrier_q7 is not None
    assert carrier_q7["base_charge"] == 435.00

    # Scenario D: 9 skids Toronto -> Montreal (Exceeds max_skid_capacity = 8)
    # Must be excluded under Rule 18 (Exceeds maximum carrier LTL capacity)
    res_9skids = quote_all_confirmed_carriers(
        user_id="usr_alex_rivers",
        origin="Toronto, ON",
        destination="Montreal, QC",
        actual_weight=9000.0,
        skid_count=9,
    )
    quotes_9skids = res_9skids.get("quotes", [])
    carrier_q9 = next((q for q in quotes_9skids if "Direct Skid Carrier" in q["carrier_name"]), None)
    assert carrier_q9 is None  # Excluded!
