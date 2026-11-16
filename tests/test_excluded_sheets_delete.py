import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import uuid
from starlette.testclient import TestClient
from main import app
from services.auth_service import register_and_create_session
from services.quotelytics_db_service import create_rate_sheet, get_rate_sheet

client = TestClient(app)

def test_new_quote_contains_excluded_sheets_delete_controls():
    """Verify that /console/new-quote renders the Select All checkbox and Delete button in the excluded sheets drawer."""
    _, token = register_and_create_session(
        name="Jordan Freight",
        email=f"excl.ui.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Acme Logistics",
        origin_zip="TORONTO, ON",
        password="ExclUiPassword2026!"
    )
    client.cookies.set("quotelytics_session", token)
    response = client.get("/console/new-quote")
    assert response.status_code == 200
    html = response.text

    # Verify Excluded Sheets Drawer structure and toolbar controls
    assert 'id="excluded-sheets-box"' in html
    assert 'id="excluded-select-all"' in html
    assert 'toggleSelectAllExcluded' in html
    assert 'id="btn-delete-excluded"' in html
    assert 'deleteSelectedExcludedSheets' in html
    assert 'id="excluded-selected-count"' in html
    assert 'id="excluded-list-container"' in html

    # Verify JavaScript handler functions exist
    assert 'function renderExcludedSheets(' in html
    assert 'function toggleSelectAllExcluded(' in html
    assert 'function updateExcludedSelectionState(' in html
    assert 'function deleteSingleExcludedSheet(' in html
    assert 'function deleteSelectedExcludedSheets(' in html

    # Verify per-row delete and checkbox attributes in renderExcludedSheets
    assert 'excluded-sheet-item-cb' in html
    assert 'deleteSingleExcludedSheet' in html
    assert '/api/quotelytics/sheets/' in html


def test_delete_rate_sheet_api():
    """Verify that DELETE /api/quotelytics/sheets/{sheet_id} removes a sheet successfully."""
    user, token = register_and_create_session(
        name="Jordan Freight",
        email=f"excl.del.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Acme Logistics",
        origin_zip="TORONTO, ON",
        password="ExclDelPassword2026!"
    )
    user_id = user["id"]
    client.cookies.set("quotelytics_session", token)

    # Insert a dummy sheet to delete
    sheet_id = create_rate_sheet(
        user_id=user_id,
        carrier_name="Test Delete Carrier",
        service_name="Standard LTL",
        confirmation_status="CONFIRMED",
        source_filename="test_delete_tariff.xlsx"
    )

    # Verify sheet exists
    sheet_before = get_rate_sheet(sheet_id, user_id)
    assert sheet_before is not None
    assert sheet_before["id"] == sheet_id

    # Call DELETE endpoint
    del_resp = client.delete(f"/api/quotelytics/sheets/{sheet_id}")
    assert del_resp.status_code == 200
    del_json = del_resp.json()
    assert del_json["status"] == "success"

    # Verify sheet is deleted
    sheet_after = get_rate_sheet(sheet_id, user_id)
    assert sheet_after is None
