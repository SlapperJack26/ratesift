"""
Comprehensive API and concurrency tests for Phase 2:
- Gated process endpoint
- Atomic compare-and-set transition with concurrent double-submit
- Tenant isolation (Rule 14: non-owner gets 404)
- Position-aware saved mapping reuse and cross-tenant isolation
- Swapped column detection (does not reuse swapped layout)
- TTL sweeper behavior (processing protection, stuck job timeout)
- Saved mappings list and delete endpoints
"""
import concurrent.futures
import io
import time
from fastapi.testclient import TestClient
import openpyxl
from openpyxl import Workbook
import pytest


from app.jobs import job_store
from app.main import app
from app.mappings import compute_fingerprint

client = TestClient(app)


def create_test_excel_bytes(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.getvalue()


def test_upload_excel_job():
    rows = [
        ["ACME Freight Rates 2026 (lbs)"],
        [],
        ["Origin", "Destination", "Min", "-45", "+100", "+500", "+1000"],
        ["Toronto", "Montreal", 85, 0.55, 0.42, 0.35, 0.30],
    ]
    file_bytes = create_test_excel_bytes(rows)
    response = client.post(
        "/jobs",
        files={"file": ("test_rates.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "u1", "X-Tenant-Id": "t1"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "ready"
    assert data["column_count"] == 7

    job_id = data["job_id"]
    get_res = client.get(f"/jobs/{job_id}", headers={"X-User-Id": "u1", "X-Tenant-Id": "t1"})
    assert get_res.status_code == 200
    assert get_res.json()["job_id"] == job_id


def test_process_fails_if_not_ready():
    rows = [
        ["Col A", "Col B", "Col C", "Col D"],
        ["Toronto", "Montreal", 100, 200],
    ]
    file_bytes = create_test_excel_bytes(rows)
    response = client.post(
        "/jobs",
        files={"file": ("test_unmapped.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert response.json()["status"] == "needs_mapping"

    # Process must return 409
    proc_res = client.post(f"/jobs/{job_id}/process")
    assert proc_res.status_code == 409


def test_atomic_transition_concurrent_double_process():
    # Ready job
    rows = [
        ["ACME Freight Rates 2026 (lbs)"],
        [],
        ["Origin", "Destination", "Min", "-45", "+100", "+500", "+1000"],
        ["Toronto", "Montreal", 85, 0.55, 0.42, 0.35, 0.30],
    ]
    file_bytes = create_test_excel_bytes(rows)
    res = client.post(
        "/jobs",
        files={"file": ("ready_rates.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert res.json()["status"] == "ready"

    # Send two concurrent process requests
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(lambda: client.post(f"/jobs/{job_id}/process"))
        f2 = executor.submit(lambda: client.post(f"/jobs/{job_id}/process"))
        results = [f1.result(), f2.result()]

    status_codes = [r.status_code for r in results]
    # Exactly one must succeed (200) and one must get 409
    assert status_codes.count(200) == 1
    assert status_codes.count(409) == 1


def test_tenant_isolation_returns_404():
    # Rule 14: Another user cannot access job and gets 404 (not 403)
    rows = [
        ["ACME Freight Rates 2026 (lbs)"],
        [],
        ["Origin", "Destination", "Min", "-45", "+100", "+500", "+1000"],
        ["Toronto", "Montreal", 85, 0.55, 0.42, 0.35, 0.30],
    ]
    file_bytes = create_test_excel_bytes(rows)
    res = client.post(
        "/jobs",
        files={"file": ("tenant_a.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "user_a", "X-Tenant-Id": "tenant_a"}
    )
    job_id = res.json()["job_id"]

    # Tenant A access succeeds
    res_a = client.get(f"/jobs/{job_id}", headers={"X-User-Id": "user_a", "X-Tenant-Id": "tenant_a"})
    assert res_a.status_code == 200

    # Tenant B access returns 404
    res_b = client.get(f"/jobs/{job_id}", headers={"X-User-Id": "user_b", "X-Tenant-Id": "tenant_b"})
    assert res_b.status_code == 404

    # Processing from Tenant B returns 404
    proc_b = client.post(f"/jobs/{job_id}/process", headers={"X-User-Id": "user_b", "X-Tenant-Id": "tenant_b"})
    assert proc_b.status_code == 404


def test_saved_mapping_reuse_and_swapped_columns():
    # Upload custom sheet requiring mapping
    rows = [
        ["City A", "City B", "Rate 100", "Rate 500"],
        ["Toronto", "Montreal", 0.50, 0.40],
    ]
    file_bytes = create_test_excel_bytes(rows)
    res = client.post(
        "/jobs",
        files={"file": ("custom_layout.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "u1", "X-Tenant-Id": "tenant_corp"}
    )
    job_id = res.json()["job_id"]
    assert res.json()["status"] == "needs_mapping"

    # Confirm mapping with remember_mapping=True
    map_res = client.post(
        f"/jobs/{job_id}/mapping",
        json={
            "header_row": 0,
            "mode": "weight",
            "origin": 0,
            "destination": 1,
            "rate_columns": [2, 3],
            "weight_unit": "lb",
            "remember_mapping": True
        },
        headers={"X-User-Id": "u1", "X-Tenant-Id": "tenant_corp"}
    )
    assert map_res.status_code == 200
    assert map_res.json()["status"] == "ready"

    # Re-upload the EXACT same layout -> should auto-map with mapping_source == 'saved'
    re_upload = client.post(
        "/jobs",
        files={"file": ("custom_layout2.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "u1", "X-Tenant-Id": "tenant_corp"}
    )
    assert re_upload.status_code == 200
    assert re_upload.json()["status"] == "ready"
    assert re_upload.json()["mapping_source"] == "saved"

    # Upload layout where Origin and Destination columns are swapped:
    swapped_rows = [
        ["City B", "City A", "Rate 100", "Rate 500"],
        ["Montreal", "Toronto", 0.50, 0.40],
    ]
    swapped_bytes = create_test_excel_bytes(swapped_rows)
    swapped_upload = client.post(
        "/jobs",
        files={"file": ("swapped.xlsx", swapped_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "u1", "X-Tenant-Id": "tenant_corp"}
    )
    assert swapped_upload.status_code == 200
    # Must NOT auto-apply previous mapping because fingerprint is position-aware!
    assert swapped_upload.json()["status"] == "needs_mapping"
    assert swapped_upload.json()["mapping_source"] != "saved"


def test_cross_tenant_mapping_isolation():
    # Tenant X upload should NOT match Tenant Corp's saved mapping
    rows = [
        ["City A", "City B", "Rate 100", "Rate 500"],
        ["Toronto", "Montreal", 0.50, 0.40],
    ]
    file_bytes = create_test_excel_bytes(rows)
    res = client.post(
        "/jobs",
        files={"file": ("tenant_x.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "ux", "X-Tenant-Id": "tenant_x"}
    )
    assert res.status_code == 200
    # Tenant X does not have this mapping saved, so it must not auto-map
    assert res.json()["status"] == "needs_mapping"


def test_list_and_delete_saved_mappings():
    # List mappings for tenant_corp
    res = client.get("/mappings", headers={"X-User-Id": "u1", "X-Tenant-Id": "tenant_corp"})
    assert res.status_code == 200
    mappings = res.json()
    assert len(mappings) >= 1
    mapping_id = mappings[0]["id"]

    # Delete mapping
    del_res = client.delete(f"/mappings/{mapping_id}", headers={"X-User-Id": "u1", "X-Tenant-Id": "tenant_corp"})
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True


def test_ttl_sweeper_stuck_job_timeout():
    # Create job directly in job_store with status 'processing' and past updated_at
    job_id = "test_hung_job"
    now = time.time()
    job_store.create(job_id, {
        "job_id": job_id,
        "status": "processing",
        "path": "",
        "ext": ".xlsx",
        "analysis": {"status": "processing"},
    })

    # Manually backdate updated_at by 400 seconds (max processing is 300s)
    conn = job_store._get_connection()
    conn.execute("UPDATE failsafe_jobs SET updated_at = ? WHERE id = ?;", (now - 400, job_id))
    conn.commit()
    conn.close()

    # Run cleanup_expired
    job_store.cleanup_expired(now=now, max_processing_seconds=300)

    # Job should now have status 'failed'
    job = job_store.get(job_id)
    assert job is not None
    assert job["status"] == "failed"


def test_upload_zip_bomb_rejected():
    import zipfile
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        large_chunk = b"\x00" * (1024 * 1024)
        for i in range(105):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", large_chunk)
    bio.seek(0)
    res = client.post(
        "/jobs",
        files={"file": ("bomb.xlsx", bio.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res.status_code == 422
    assert "potential zip bomb" in res.json()["detail"].lower()


def test_upload_uncached_formula_rejected():
    wb = Workbook()
    ws = wb.active
    ws.append(["Origin", "Destination", "Rate"])
    ws.append(["=CONCAT('Tor','onto')", "=CONCAT('Mont','real')", "=SUM(10,20)"])
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    res = client.post(
        "/jobs",
        files={"file": ("formula.xlsx", bio.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res.status_code == 422
    assert "without cached calculated values" in res.json()["detail"].lower()


def test_process_and_download_flow():
    rows = [
        ["ACME Freight Rates 2026 (lbs)"],
        [],
        ["Origin", "Destination", "Min", "-45", "+100", "+500", "+1000"],
        ["Toronto", "Montreal", 85, 0.55, 0.42, 0.35, 0.30],
    ]
    file_bytes = create_test_excel_bytes(rows)
    res = client.post(
        "/jobs",
        files={"file": ("process_rates.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "u_proc", "X-Tenant-Id": "t_proc"}
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert res.json()["status"] == "ready"

    # Process job
    proc_res = client.post(f"/jobs/{job_id}/process", headers={"X-User-Id": "u_proc", "X-Tenant-Id": "t_proc"})
    assert proc_res.status_code == 200
    assert proc_res.json()["status"] == "done"

    # Download output workbook
    dl_res = client.get(f"/jobs/{job_id}/download", headers={"X-User-Id": "u_proc", "X-Tenant-Id": "t_proc"})
    assert dl_res.status_code == 200
    assert len(dl_res.content) > 0
    # Must be valid xlsx
    wb_dl = openpyxl.load_workbook(io.BytesIO(dl_res.content))
    assert "Normalized Shipments" in wb_dl.sheetnames

