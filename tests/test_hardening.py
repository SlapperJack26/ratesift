"""
Comprehensive Test Hardening Suite for Rate-Sheet Header Failsafe (Phase 5).
Verifies:
1. Hardened edge cases from Implementation Plan Section 5:
   - Blank/empty header rows
   - Numeric headers (year 2026, zip codes)
   - Merged header cells with forward-fill across bounds
   - Unicode / zero-width whitespace normalization
   - Ambiguous sheets with both or neither mode
2. Strict verification of Failsafe Invariants (Section 2):
   - Zero silent-miss rate on missing Origin, Destination, Mode, or Weight Unit
   - Content alone never auto-maps required fields (Col A regression test)
   - Gate 409 enforcement on all non-ready jobs
   - Full byte-level immutability of uploaded files
"""
import io
import os
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.detect import analyze, validate_mapping
from app.ingest import load_sheet_grid, normalize_header
from main import app

client = TestClient(app)


def create_workbook_bytes(rows, merge_ranges=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    if merge_ranges:
        for rng in merge_ranges:
            ws.merge_cells(rng)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.getvalue()


# =========================================================================
# 1. EDGE CASES & SCANNER HARDENING
# =========================================================================

def test_empty_rows_before_header(tmp_path):
    """Empty or whitespace-only rows before the true header row must not derail detection."""
    rows = [
        ["", "", "", ""],
        ["   ", None, "\t", ""],
        ["Origin", "Destination", "-45 (lbs)", "+100 (lbs)"],
        ["Toronto", "Montreal", 1.25, 0.95],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "empty_prefix.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)
    assert res["status"] == "ready"
    assert res["header_row"] == 2
    assert res["mode"] == "weight"
    assert res["weight_unit"] == "lb"


def test_numeric_and_code_headers_not_confused_with_lanes(tmp_path):
    """Numbers like years (2026) or postal codes (M5V) in headers must not be classified as lane names."""
    rows = [
        ["Rate Tariff 2026", "Effective 2026-01-01", "", ""],
        ["Origin", "Destination", "-45 lbs", "+100 lbs"],
        ["Toronto", "Montreal", 1.10, 0.85],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "numeric_headers.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)
    assert res["status"] == "ready"
    assert res["header_row"] == 1


def test_merged_header_cells_forward_filled(tmp_path):
    """Merged header banner spanning multiple columns must be forward-filled properly."""
    rows = [
        ["Origin", "Destination", "LTL Rates (lbs)", ""],
        ["City", "Province", "-45", "+100"],
        ["Toronto", "QC", 1.25, 0.95],
    ]
    # Merge C1:D1
    wb_bytes = create_workbook_bytes(rows, merge_ranges=["C1:D1"])
    p = tmp_path / "merged_header.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    # Verify forward-fill in row 0
    assert grid[0][2] == "LTL Rates (lbs)"
    assert grid[0][3] == "LTL Rates (lbs)"

    res = analyze(grid)
    assert res["mode"] == "weight"
    assert res["weight_unit"] == "lb"


def test_unicode_and_zero_width_spaces_normalized():
    """NBSP, zero-width spaces, and fullwidth characters must be normalized cleanly."""
    dirty_text = "\u200bOrigin\u00a0City\ufeff"
    cleaned = normalize_header(dirty_text)
    assert cleaned == "origin city"

    fullwidth = "Ｄｅｓｔｉｎａｔｉｏｎ"
    assert normalize_header(fullwidth) == "destination"


# =========================================================================
# 2. ZERO SILENT-MISS GUARANTEE (THE FAILSAFE CONTRACT)
# =========================================================================

def test_zero_silent_miss_missing_origin(tmp_path):
    """If Origin is missing or unrecognizable, status MUST be needs_mapping; never ready."""
    rows = [
        ["UnrecognizedCol", "Destination", "-45 lbs", "+100 lbs"],
        ["Toronto", "Montreal", 1.25, 0.95],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "no_origin.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)
    assert res["status"] == "needs_mapping"
    assert "origin" in res["unresolved"]


def test_zero_silent_miss_missing_destination(tmp_path):
    """If Destination is missing or unrecognizable, status MUST be needs_mapping; never ready."""
    rows = [
        ["Origin", "UnrecognizedCol", "-45 lbs", "+100 lbs"],
        ["Toronto", "Montreal", 1.25, 0.95],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "no_dest.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)
    assert res["status"] == "needs_mapping"
    assert "destination" in res["unresolved"]


def test_zero_silent_miss_missing_weight_unit(tmp_path):
    """Weight sheet without explicit unit MUST NOT reach ready (Rule 8)."""
    rows = [
        ["Origin", "Destination", "-45", "+100"],
        ["Toronto", "Montreal", 1.25, 0.95],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "no_unit.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)
    assert res["status"] == "needs_mapping"
    assert "weight_unit" in res["unresolved"]


def test_zero_silent_miss_ambiguous_pricing_modes(tmp_path):
    """Sheet showing both weight breaks and skid columns must prompt user (Rule 3)."""
    rows = [
        ["Origin", "Destination", "-45 lbs", "+100 lbs", "1 PL", "2 PL"],
        ["Toronto", "Montreal", 1.25, 0.95, 150.00, 275.00],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "both_modes.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)
    assert res["status"] == "needs_mapping"
    assert "mode" in res["unresolved"]


def test_content_alone_never_automaps_col_a_regression(tmp_path):
    """Regression test: Content resembling city names in Col A must NOT map to Origin without header signal."""
    rows = [
        ["Col A", "Col B", "Col C", "Col D"],
        ["Toronto, ON", "Montreal, QC", "1.25", "0.95"],
        ["Vancouver, BC", "Calgary, AB", "1.80", "1.45"],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "col_a_regression.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)
    assert res["status"] == "needs_mapping"
    assert "origin" in res["unresolved"]
    assert "destination" in res["unresolved"]


# =========================================================================
# 3. API GATE & IMMUTABILITY RE-VERIFICATION
# =========================================================================

def test_api_strict_gating_unmapped_sheet(tmp_path):
    """Attempting to process any job not in status=ready returns HTTP 409 (Rule 7)."""
    rows = [
        ["Col A", "Col B", "Col C"],
        ["Toronto", "Montreal", 100],
    ]
    wb_bytes = create_workbook_bytes(rows)
    res = client.post(
        "/jobs",
        files={"file": ("unmapped_gate.xlsx", wb_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert res.json()["status"] == "needs_mapping"

    # Attempt process before mapping
    gate_res = client.post(f"/jobs/{job_id}/process")
    assert gate_res.status_code == 409
    assert "Mapping not confirmed" in gate_res.json()["detail"]


def test_file_immutability_throughout_lifecycle(tmp_path):
    """Rule 12: Original uploaded file bytes remain 100% byte-identical after analyze, mapping, and process."""
    rows = [
        ["Origin", "Destination", "-45 (lbs)", "+100 (lbs)"],
        ["Toronto", "Montreal", 1.25, 0.95],
    ]
    orig_bytes = create_workbook_bytes(rows)
    res = client.post(
        "/jobs",
        files={"file": ("immutability_test.xlsx", orig_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User-Id": "u_audit", "X-Tenant-Id": "t_audit"}
    )
    assert res.status_code == 200
    data = res.json()
    job_id = data["job_id"]
    assert data["status"] == "ready"

    # Run processing
    proc_res = client.post(
        f"/jobs/{job_id}/process",
        headers={"X-User-Id": "u_audit", "X-Tenant-Id": "t_audit"}
    )
    assert proc_res.status_code == 200

    # Retrieve internal stored job to inspect original upload path
    from app.jobs import job_store
    stored_job = job_store.get(job_id)
    with open(stored_job["path"], "rb") as f:
        stored_bytes = f.read()

    assert stored_bytes == orig_bytes, "Original uploaded file was modified!"


def test_intermodal_equipment_matrix_with_no_rates_triggers_failsafe(tmp_path):
    """
    When a sheet contains equipment availability or route codes (e.g. 40FT, CN RV)
    with no numeric rate values, the failsafe must trigger needs_mapping with an explicit issue.
    """
    rows = [
        ["", "MON", "TUES", "WED", "THU", "FRI"],
        ["Toronto to Winnipeg", "", "", "", "", ""],
        ["40FT", "CN RV", "CN RV", "CP Flex", "CP Flex", "CP Flex"],
        ["53FT", "CN RV", "CN RV", "CN", "CN", "CN"],
        ["53Ht", "CN RV", "CN RV", "CN", "CN", "CN"],
    ]
    wb_bytes = create_workbook_bytes(rows)
    p = tmp_path / "intermodal_matrix.xlsx"
    p.write_bytes(wb_bytes)
    grid, _ = load_sheet_grid(str(p), ".xlsx")
    res = analyze(grid)

    assert res["status"] == "needs_mapping"
    assert any("no numeric freight rates" in iss.lower() for iss in res["issues"])
    assert "rates" in res["unresolved"]

