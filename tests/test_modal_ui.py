import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_failsafe_demo_page_renders(client):
    """Verify that the failsafe UI playground endpoint loads with HTTP 200 and renders modal."""
    resp = client.get("/failsafe/demo")
    assert resp.status_code == 200
    assert "Quotelytics Header Failsafe & Mapping Modal Playground" in resp.text or "Quotelytics Header Failsafe & Mapping Modal Playground" in resp.text
    assert "failsafe-mapping-modal" in resp.text
    assert "FailsafeModal" in resp.text
    assert "Confirm Mapping & Process" in resp.text


def test_cancel_endpoint(client, tmp_path):
    """Rule 9 & Rule 12: Cancel cleanly marks job expired without modifying original file."""
    import openpyxl
    import uuid
    from services.auth_service import register_and_create_session
    _, tok = register_and_create_session(
        name="UI Cancel User",
        email=f"ui.cancel.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Acme UI",
        origin_zip="TORONTO, ON",
        password="UiCancelPassword2026!"
    )
    auth_headers = {"Authorization": f"Bearer {tok}"}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ColA", "ColB", "ColC"])
    ws.append(["Toronto", "Montreal", "150.00"])
    test_path = tmp_path / "cancel_test.xlsx"
    wb.save(test_path)
    with open(test_path, "rb") as f:
        file_bytes = f.read()

    # Upload job
    upload_res = client.post(
        "/jobs",
        files={"file": ("cancel_test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=auth_headers
    )
    assert upload_res.status_code == 200
    job_id = upload_res.json()["job_id"]

    # Call cancel
    cancel_res = client.post(
        f"/jobs/{job_id}/cancel",
        headers=auth_headers
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "expired"

    # Original file must remain byte-identical
    with open(test_path, "rb") as f:
        assert f.read() == file_bytes


def test_modal_workflow_confirmation_and_gated_process(client, tmp_path):
    """
    Test the full frontend modal contract:
    1. Upload ambiguous sheet (triggers needs_mapping).
    2. Attempting process returns 409 (Gate).
    3. User confirms mapping via POST /jobs/{id}/mapping.
    4. Process executes cleanly and job transitions to done.
    """
    import openpyxl
    import uuid
    from services.auth_service import register_and_create_session
    from services.db_service import update_user_tier
    u_modal, tok_modal = register_and_create_session(
        name="UI Modal User",
        email=f"ui.modal.{uuid.uuid4().hex[:6]}@acme-logistics.ca",
        company="Acme Modal UI",
        origin_zip="TORONTO, ON",
        password="UiModalPassword2026!"
    )
    update_user_tier(u_modal["id"], "BUSINESS")
    modal_headers = {"Authorization": f"Bearer {tok_modal}"}

    wb = openpyxl.Workbook()
    ws = wb.active
    # Sheet where Origin and Destination are unmapped / ambiguous, but breaks exist
    ws.append(["Col A", "Col B", "-45", "+100"])
    ws.append(["Toronto", "Montreal", "1.25", "0.95"])
    test_path = tmp_path / "modal_flow.xlsx"
    wb.save(test_path)

    with open(test_path, "rb") as f:
        res = client.post(
            "/jobs",
            files={"file": ("modal_flow.xlsx", f.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=modal_headers
        )
    assert res.status_code == 200
    job = res.json()
    assert job["status"] == "needs_mapping"
    job_id = job["job_id"]

    # Gate check: process returns 409
    proc_blocked = client.post(
        f"/jobs/{job_id}/process",
        headers=modal_headers
    )
    assert proc_blocked.status_code == 409

    # Confirm mapping as submitted by the modal
    mapping_payload = {
        "header_row": 0,
        "mode": "weight",
        "origin": 0,
        "destination": 1,
        "rate_columns": [2, 3],
        "weight_unit": "lb",
        "remember_mapping": True
    }
    map_res = client.post(
        f"/jobs/{job_id}/mapping",
        json=mapping_payload,
        headers=modal_headers
    )
    assert map_res.status_code == 200
    assert map_res.json()["status"] == "ready"

    # Now process succeeds
    proc_ok = client.post(
        f"/jobs/{job_id}/process",
        headers=modal_headers
    )
    assert proc_ok.status_code == 200
    assert proc_ok.json()["status"] == "done"
