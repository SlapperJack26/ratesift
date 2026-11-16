import io
import uuid
import openpyxl
import pytest
from starlette.testclient import TestClient
from main import app
from services.quotelytics_db_service import get_connection, list_rate_sheets
from services.quotelytics_engine import quote_all_confirmed_carriers
from services.auth_service import register_and_create_session
from services.db_service import update_user_tier

client = TestClient(app)

def make_test_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Carrier Tariff"
    # Header row
    ws.append(["Origin", "Destination", "500 lbs", "1000 lbs", "2000 lbs"])
    # Data rows
    ws.append(["TORONTO, ON", "MONTREAL, QC", 1.25, 0.95, 0.75])
    ws.append(["TORONTO, ON", "CALGARY, AB", 2.80, 2.10, 1.85])
    ws.append(["VANCOUVER, BC", "CALGARY, AB", 1.85, 1.45, 1.20])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

def test_failsafe_sheet_persists_and_becomes_quotable():
    user, token = register_and_create_session(
        name="Jordan Freight",
        email=f"failsafe.persist.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Acme Logistics",
        origin_zip="TORONTO, ON",
        password="FailsafePersistPassword2026!"
    )
    user_id = user["id"]
    update_user_tier(user_id, "BUSINESS")
    auth_cookies = {"quotelytics_session": token}
    content = make_test_workbook()

    # 1. Upload sheet to /jobs
    res = client.post(
        "/jobs",
        files={"file": ("test_tariff_failsafe.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        cookies=auth_cookies
    )
    assert res.status_code == 200
    job_data = res.json()
    job_id = job_data["job_id"]
    assert job_id is not None

    # 2. Confirm mapping
    map_payload = {
        "header_row": 0,
        "sheet_name": "Atlas Freight Express",
        "mode": "weight",
        "origin": 0,
        "destination": 1,
        "rate_columns": [2, 3, 4],
        "weight_unit": "lb",
        "remember_mapping": False
    }
    map_res = client.post(
        f"/jobs/{job_id}/mapping",
        json=map_payload,
        cookies=auth_cookies
    )
    assert map_res.status_code == 200
    assert map_res.json()["status"] == "ready"

    # 3. Process via gate
    proc_res = client.post(
        f"/jobs/{job_id}/process",
        cookies=auth_cookies
    )
    assert proc_res.status_code == 200
    proc_data = proc_res.json()
    assert proc_data["status"] == "done"
    sheet_id = proc_data.get("sheet_id")
    assert sheet_id is not None
    assert sheet_id.startswith("ql_sheet_")

    # 4. Verify sheet is returned by list_rate_sheets
    sheets = list_rate_sheets(user_id=user_id)
    sheet_ids = [s["id"] for s in sheets]
    assert sheet_id in sheet_ids

    matching_sheet = next(s for s in sheets if s["id"] == sheet_id)
    assert matching_sheet["carrier_name"] == "Atlas Freight Express"
    assert matching_sheet["confirmation_status"] == "CONFIRMED"

    # 5. Verify weight breaks are stored in the database
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM ql_weight_breaks WHERE sheet_id = ?", (sheet_id,))
    cnt = c.fetchone()["cnt"]
    conn.close()
    assert cnt >= 6  # 3 rows x 2-3 rate columns

    # 6. Verify sheet is quotable deterministically
    quote_res = quote_all_confirmed_carriers(
        user_id=user_id,
        origin="TORONTO, ON",
        destination="MONTREAL, QC",
        actual_weight=750.0
    )
    assert "quotes" in quote_res
    atlas_quotes = [q for q in quote_res["quotes"] if q.get("carrier_name") == "Atlas Freight Express"]
    assert len(atlas_quotes) > 0, "Newly mapped failsafe sheet must appear in quotes!"
    print("[PASS] Failsafe sheet successfully persisted, listed, and quoted!")
