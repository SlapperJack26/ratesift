import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import uuid
from starlette.testclient import TestClient
from main import app
from services.auth_service import register_and_create_session

client = TestClient(app)

def test_new_quote_batch_excel_removed_and_counters_displayed():
    """
    Verify:
    1. Batch Excel option is removed from the new quote page.
    2. Active Rate Sheets and Pending Review number counters are displayed in its space.
    3. Sheet names are NOT listed (only numbers are displayed).
    4. The list of uploaded rate sheets above the quoting information box is removed.
    """
    _, token = register_and_create_session(
        name="Jordan Freight",
        email=f"counters.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Acme Logistics",
        origin_zip="TORONTO, ON",
        password="CountersPassword2026!"
    )
    client.cookies.set("quotelytics_session", token)
    response = client.get("/console/new-quote")
    assert response.status_code == 200
    html = response.text

    # 1. Batch Excel option removed
    assert "tab-batch-btn" not in html
    assert "section-batch" not in html
    assert "Batch Excel" not in html

    # 2. Number counters present in its space
    assert 'id="rate-sheets-counters"' in html
    assert 'id="active-sheets-count"' in html
    assert 'id="pending-sheets-count"' in html
    assert "Active Rate Sheets:" in html
    assert "Pending Review:" in html

    # 3. List of uploaded rate sheets above the quoting information box removed
    assert 'id="loaded-carriers-pills"' not in html
    assert 'id="loaded-tariffs-tray"' not in html
