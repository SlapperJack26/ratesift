"""
tests/test_pdf_rate_sheet_failsafe.py
=====================================
Comprehensive test suite for universal carrier PDF rate sheet ingestion,
mandatory column title preservation, multi-tab Failsafe modal jobs,
openManualEntryFailsafe (/jobs/from-sheet/{sheet_id}), and PDF-to-Excel
reformatting.
"""
import io
import json
import os
import re
import uuid
import zlib
from typing import Dict, List, Optional, Tuple

import pytest
from starlette.requests import Request

from app.config import ALLOWED_EXT, MAX_BYTES, MAX_DATA_COLS, MAX_SCAN_COLS
from app.detect import analyze
from app.ingest import list_sheet_names, load_sheet_grid
from app.main import (
    confirm_mapping,
    create_job_from_sheet,
    dry_run,
    get_job,
    ingest_job_to_quotelytics,
    job_store,
    upload,
)
from app.models import DryRunRequest, MappingRequest
from app.validation import parse_break_label
from services.auth_service import register_and_create_session
from services.db_service import update_user_tier
from services.pdf_tariff_extractor_service import (
    convert_pdf_tariff_bytes_to_csv_text,
    extract_pdf_tariff_tables,
)
from services.quotelytics_db_service import (
    create_rate_sheet,
    get_sheet_full_rules,
    insert_carrier_minimums,
    insert_weight_breaks,
)
from services.quotelytics_excel_reformatter import analyze_excel_sheet


# ---------------------------------------------------------------------------
# Minimal Pure-Python Multi-Page Positioned PDF Builder for Tests
# ---------------------------------------------------------------------------

def _escape_pdf_lit(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_synthetic_pdf(pages_ops: List[List[Tuple[float, float, str, float]]]) -> bytes:
    """
    Constructs a valid PDF 1.4 binary with FlateDecode page content streams.
    Each page is a list of (x, pdf_y_bottom_up, text, font_size) draw operations
    emitted in arbitrary order (allowing out-of-order detached-column testing).
    """
    objects: Dict[int, bytes] = {}
    # Object 1: Catalog, Object 2: Pages, Object 3: Helvetica Font
    font_obj_id = 3
    page_ids: List[int] = []
    next_id = 4

    for ops in pages_ops:
        stream_lines = ["BT", f"/F1 10 Tf"]
        for x, y, txt, fs in ops:
            stream_lines.append(f"/F1 {fs:.1f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape_pdf_lit(txt)}) Tj")
        stream_lines.append("ET")
        raw_stream = "\n".join(stream_lines).encode("latin-1")
        comp_stream = zlib.compress(raw_stream)

        content_id = next_id
        page_id = next_id + 1
        next_id += 2

        objects[content_id] = (
            f"<< /Length {len(comp_stream)} /Filter /FlateDecode >>\nstream\n".encode("ascii")
            + comp_stream
            + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        page_ids.append(page_id)

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [ {kids_str} ] /Count {len(page_ids)} >>".encode("ascii")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets: Dict[int, int] = {}
    for oid in sorted(objects.keys()):
        offsets[oid] = len(out)
        out.extend(f"{oid} 0 obj\n".encode("ascii"))
        out.extend(objects[oid])
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    max_id = max(objects.keys())
    out.extend(f"xref\n0 {max_id + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for oid in range(1, max_id + 1):
        out.extend(f"{offsets[oid]:010d} 00000 n \n".encode("ascii"))

    out.extend(
        f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def _make_mock_request(token: Optional[str] = None) -> Request:
    headers = []
    if token:
        headers.append((b"cookie", f"quotelytics_session={token}".encode("utf-8")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/jobs",
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class _SyncUploadFile:
    """In-memory UploadFile double whose async read() completes without spawning a socketpair event loop."""
    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self._payload = payload

    async def read(self, size: int = -1) -> bytes:
        if size is not None and size >= 0:
            return self._payload[:size]
        return self._payload


def _run_coro_no_loop(coro):
    """Drives a single-step coroutine to completion without ProactorEventLoop/socketpair."""
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise RuntimeError("Coroutine yielded unexpectedly outside mock read()")
def _create_test_user(prefix: str = "pdf_test") -> Tuple[Dict, str]:
    user, token = register_and_create_session(
        name="PDF Test Broker",
        email=f"{prefix}.{uuid.uuid4().hex[:8]}@quotelytics.test",
        company="Quotelytics Test Corp",
        origin_zip="TORONTO, ON",
        password="PdfTestPassword2026!",
    )
    update_user_tier(user["id"], "BUSINESS")
    return user, token


# ---------------------------------------------------------------------------
# 1. Universal Carrier Archetypes & Coordinate-Aware PDF Extractor Tests
# ---------------------------------------------------------------------------

def test_archetype_a_standard_ltl_multipage_vertical_stitch():
    """Archetype A: Standard LTL Lane x Weight-Break PDF across 2 pages stitches cleanly with labeled headers."""
    p1 = [
        (36, 740, "Apex Regional LTL Tariff (Rates per CWT, CAD, lbs)", 14),
        (36, 700, "Origin", 10), (140, 700, "Destination", 10),
        (250, 700, "Minimum Charge", 10), (350, 700, "500", 10), (420, 700, "1000", 10), (490, 700, "2000", 10),
        (36, 680, "Toronto, ON", 10), (140, 680, "Montreal, QC", 10),
        (250, 680, "$95.00", 10), (350, 680, "24.50", 10), (420, 680, "19.25", 10), (490, 680, "15.10", 10),
    ]
    p2 = [
        (36, 740, "Apex Regional LTL Tariff (Continued)", 14),
        (36, 700, "Origin", 10), (140, 700, "Destination", 10),
        (250, 700, "Minimum Charge", 10), (350, 700, "500", 10), (420, 700, "1000", 10), (490, 700, "2000", 10),
        (36, 680, "Toronto, ON", 10), (140, 680, "Calgary, AB", 10),
        (250, 680, "$185.00", 10), (350, 680, "48.00", 10), (420, 680, "39.50", 10), (490, 680, "31.20", 10),
    ]
    pdf_bytes = build_synthetic_pdf([p1, p2])
    tables = extract_pdf_tariff_tables(pdf_bytes)
    rate_tables = [t for t in tables if t["section_type"] == "rate_grid"]
    assert len(rate_tables) == 1
    t = rate_tables[0]
    assert t["archetype"] == "ltl_lane_weight"
    # Bare break numbers get 'lbs' unit propagated so no unlabeled numbers appear
    assert t["headers"] == ["Origin", "Destination", "Minimum Charge", "500 lbs", "1000 lbs", "2000 lbs"]
    assert len(t["rows"]) == 2
    assert t["rows"][0][1] == "Montreal, QC"
    assert t["rows"][1][1] == "Calgary, AB"


def test_archetype_b_skid_matrix_two_row_header_unit_propagation():
    """Archetype B: Stacked Skid super-header + bare numeric skid columns normalize to 1 Skid, 2 Skids, 3 Skids."""
    p1 = [
        (36, 740, "Northern Pallet Line Tariff", 14),
        (240, 712, "Skids", 10),
        (36, 696, "Origin", 10), (130, 696, "Destination", 10),
        (240, 696, "1", 10), (310, 696, "2", 10), (380, 696, "3", 10),
        (36, 676, "Hamilton, ON", 10), (130, 676, "Ottawa, ON", 10),
        (240, 676, "$210.00", 10), (310, 676, "$380.00", 10), (380, 676, "$540.00", 10),
        (36, 658, "Hamilton, ON", 10), (130, 658, "Windsor, ON", 10),
        (240, 658, "$180.00", 10), (310, 658, "$330.00", 10), (380, 658, "$470.00", 10),
    ]
    tables = extract_pdf_tariff_tables(build_synthetic_pdf([p1]))
    t = tables[0]
    assert t["archetype"] == "skid_matrix"
    assert t["headers"] == ["Origin", "Destination", "1 Skid", "2 Skids", "3 Skids"]


def test_archetype_c_fixed_origin_outbound_pdf():
    """Archetype C: Preamble banner origin ('Outbound from: Mississauga, ON') injects explicit labeled Origin column."""
    p1 = [
        (36, 740, "Custom Distribution Schedule", 14),
        (36, 720, "Outbound from: Mississauga, ON", 11),
        (36, 695, "Destination", 10), (180, 695, "Minimum Charge", 10), (290, 695, "500 lbs", 10), (380, 695, "1000 lbs", 10),
        (36, 675, "Kingston, ON", 10), (180, 675, "$85.00", 10), (290, 675, "18.50", 10), (380, 675, "14.20", 10),
        (36, 657, "London, ON", 10), (180, 657, "$79.00", 10), (290, 657, "16.00", 10), (380, 657, "12.80", 10),
    ]
    tables = extract_pdf_tariff_tables(build_synthetic_pdf([p1]))
    t = tables[0]
    assert t["archetype"] == "fixed_origin_outbound"
    assert t["fixed_origin"] == "Mississauga, ON"
    assert t["headers"] == ["Origin", "Destination", "Minimum Charge", "500 lbs", "1000 lbs"]
    assert t["rows"][0][0] == "Mississauga, ON"


def test_archetype_d_detached_weight_and_odd_even_horizontal_stitch_and_transpose():
    """
    Archetype D benchmark:
    - Price columns emitted BEFORE detached Weight column in PDF stream
    - Zones 1-4 on Page 1 (odd), Zones 5-8 on Page 2 (even) under same service banner
    - Stacked Accessorial table on Page 3 isolated as reference_notes
    - Transposes into Destination Zone rows x Minimum Charge + labeled Weight-Break columns
    """
    # Notice: dollar values emitted FIRST in PDF stream, Weight column emitted LAST!
    page_odd = [
        (36, 740, "Express Courier 1Day Freight Rates (CAD)", 14),
        (200, 705, "Zone 1", 10), (280, 705, "Zone 2", 10), (360, 705, "Zone 3", 10), (440, 705, "Zone 4", 10),
        (200, 680, "$1.50", 10), (280, 680, "$1.75", 10), (360, 680, "$2.10", 10), (440, 680, "$2.50", 10),
        (200, 660, "1.40", 10), (280, 660, "1.65", 10), (360, 660, "1.95", 10), (440, 660, "2.35", 10),
        (200, 640, "1.25", 10), (280, 640, "1.50", 10), (360, 640, "1.80", 10), (440, 640, "2.15", 10),
        (200, 620, "166.17", 10), (280, 620, "172.00", 10), (360, 620, "185.50", 10), (440, 620, "210.00", 10),
        # Detached Weight axis emitted LAST in PDF stream!
        (36, 705, "Weight", 10),
        (36, 680, "151 to 299 lbs.", 10),
        (36, 660, "300 to 499", 10),
        (36, 640, "500 or more", 10),
        (36, 620, "Minimum Charge", 10),
    ]
    page_even = [
        (36, 740, "Express Courier 1Day Freight Rates (CAD)", 14),
        (200, 705, "Zone 5", 10), (280, 705, "Zone 6", 10), (360, 705, "Zone 7", 10), (440, 705, "Zone 8", 10),
        (200, 680, "$2.90", 10), (280, 680, "$3.20", 10), (360, 680, "$3.85", 10), (440, 680, "$4.15", 10),
        (200, 660, "2.75", 10), (280, 660, "3.05", 10), (360, 660, "3.65", 10), (440, 660, "3.95", 10),
        (200, 640, "2.55", 10), (280, 640, "2.85", 10), (360, 640, "3.45", 10), (440, 640, "3.75", 10),
        (200, 620, "235.00", 10), (280, 620, "260.00", 10), (360, 620, "295.00", 10), (440, 620, "320.00", 10),
        (36, 705, "Weight", 10),
        (36, 680, "151 to 299 lbs.", 10),
        (36, 660, "300 to 499", 10),
        (36, 640, "500 or more", 10),
        (36, 620, "Minimum Charge", 10),
    ]
    page_notes = [
        (36, 740, "Additional Fees/Surcharges and Information", 14),
        (36, 700, "Definition", 10), (220, 700, "Applicable Services", 10), (420, 700, "Charges", 10),
        (36, 680, "Residential Delivery", 10), (220, 680, "All Express Freight", 10), (420, 680, "$50.00", 10),
    ]

    pdf_bytes = build_synthetic_pdf([page_odd, page_even, page_notes])
    tables = extract_pdf_tariff_tables(pdf_bytes)

    rate_tabs = [t for t in tables if t["section_type"] == "rate_grid"]
    ref_tabs = [t for t in tables if t["section_type"] == "reference"]
    assert len(rate_tabs) == 1
    assert len(ref_tabs) >= 1

    rt = rate_tabs[0]
    assert rt["archetype"] == "transposed_weight_zone"
    # Corner label 'Weight' must be replaced, never left on Destination Zone
    assert rt["headers"] == ["Destination Zone", "Minimum Charge", "151 to 299 lbs", "300 to 499 lbs", "500+ lbs"]
    # Horizontally stitched odd+even zones 1..8
    zones = [r[0] for r in rt["rows"]]
    assert zones == [f"Zone {i}" for i in range(1, 9)]
    # Detached weights aligned to exact rows
    assert rt["rows"][0] == ["Zone 1", "166.17", "$1.50", "1.40", "1.25"]
    assert rt["rows"][7] == ["Zone 8", "320.00", "$4.15", "3.95", "3.75"]

    # Backward-compatible CSV text output
    csv_txt = convert_pdf_tariff_bytes_to_csv_text(pdf_bytes)
    assert "Destination Zone,Minimum Charge,151 to 299 lbs,300 to 499 lbs,500+ lbs" in csv_txt


# ---------------------------------------------------------------------------
# 2. Header Preservation, Break Parser Parity, Config & Sidecar Cache Tests
# ---------------------------------------------------------------------------

def test_config_limits_and_break_label_parity():
    assert ".pdf" in ALLOWED_EXT
    assert MAX_BYTES == 25 * 1024 * 1024
    assert MAX_SCAN_COLS >= 200
    assert MAX_DATA_COLS >= 200
    assert parse_break_label("151 to 299 lbs") == 151.0
    assert parse_break_label("500+ lbs") == 500.0
    assert parse_break_label("Weight Breaks 1000") == 1000.0


def test_detect_writes_flattened_headers_back_into_grid():
    rows = [
        ["Lanes", "Lanes", "Weight (lbs)", "Weight (lbs)", "Weight (lbs)"],
        ["Origin", "Destination", "500", "1000", "2000"],
        ["Toronto", "Montreal", 22.5, 18.0, 14.5],
        ["Toronto", "Ottawa", 18.0, 15.0, 12.0],
    ]
    res = analyze(rows, sheet_name="Sheet1")
    hdr_idx = res["header_row"]
    assert hdr_idx == 1
    # Must persist full flattened titles into rows[hdr_idx], not leave bare "500", "1000"
    assert rows[hdr_idx][2] == "Weight (lbs) 500"
    assert rows[hdr_idx][3] == "Weight (lbs) 1000"
    assert rows[hdr_idx][4] == "Weight (lbs) 2000"
    assert res["flattened_headers"] == rows[hdr_idx]


def test_pdf_ingest_and_tables_json_cache(tmp_path):
    p1 = [
        (36, 740, "Western Carrier Tariff (CAD)", 14),
        (36, 700, "Origin", 10), (140, 700, "Destination", 10), (260, 700, "500 lbs", 10), (340, 700, "1000 lbs", 10),
        (36, 680, "Vancouver, BC", 10), (140, 680, "Calgary, AB", 10), (260, 680, "32.00", 10), (340, 680, "26.00", 10),
    ]
    p2 = [
        (36, 740, "Accessory Surcharge Schedule", 14),
        (36, 700, "Code", 10), (180, 700, "Description", 10), (360, 700, "Fee", 10),
        (36, 680, "TAILGATE", 10), (180, 680, "Power Liftgate", 10), (360, 680, "$85.00", 10),
    ]
    pdf_path = str(tmp_path / "western_carrier.pdf")
    with open(pdf_path, "wb") as f:
        f.write(build_synthetic_pdf([p1, p2]))

    sheets = list_sheet_names(pdf_path, ".pdf")
    assert len(sheets) == 2
    assert os.path.exists(f"{pdf_path}.tables.json")

    grid, selected = load_sheet_grid(pdf_path, ".pdf", sheet_name=sheets[0])
    assert selected == sheets[0]
    assert grid[0] == ["Origin", "Destination", "500 lbs", "1000 lbs"]

    # Mutate sidecar cache marker to confirm subsequent loads hit cache without re-parsing PDF bytes
    with open(f"{pdf_path}.tables.json", "r", encoding="utf-8") as cf:
        cached_tables = json.load(cf)
    cached_tables[0]["grid"][1][2] = "33.33"
    with open(f"{pdf_path}.tables.json", "w", encoding="utf-8") as cf:
        json.dump(cached_tables, cf)

    grid_cached, _ = load_sheet_grid(pdf_path, ".pdf", sheet_name=sheets[0])
    assert grid_cached[1][2] == "33.33"


# ---------------------------------------------------------------------------
# 3. End-to-End Failsafe Jobs, Tab Switching, from-sheet & Ingestion Tests
# ---------------------------------------------------------------------------

def test_pdf_upload_tab_switch_dry_run_and_fixed_origin_flat_break_ingest():
    user, token = _create_test_user("pdf_e2e")
    req = _make_mock_request(token)

    p1 = [
        (36, 740, "Atlantic Parcel & Freight Tariff (USD)", 14),
        (36, 720, "Outbound from: Moncton, NB", 11),
        (36, 695, "Destination Zone", 10), (200, 695, "151 to 299 lbs", 10), (320, 695, "300 to 499 lbs", 10),
        (36, 675, "Zone 1", 10), (200, 675, "210.00", 10), (320, 675, "315.00", 10),
        (36, 657, "Zone 2", 10), (200, 657, "250.00", 10), (320, 657, "375.00", 10),
    ]
    p2 = [
        (36, 740, "Standard LTL Rates (CAD)", 14),
        (36, 700, "Origin", 10), (140, 700, "Destination", 10), (260, 700, "500 lbs", 10), (340, 700, "1000 lbs", 10),
        (36, 680, "Moncton, NB", 10), (140, 680, "Halifax, NS", 10), (260, 680, "21.00", 10), (340, 680, "16.50", 10),
    ]
    pdf_bytes = build_synthetic_pdf([p1, p2])
    up_file = _SyncUploadFile("atlantic_carrier.pdf", pdf_bytes)

    state = _run_coro_no_loop(upload(req, file=up_file))
    assert state.job_id
    assert len(state.sheets) == 2
    assert state.preview[state.header_row or 0] == ["Origin", "Destination Zone", "151 to 299 lbs", "300 to 499 lbs"]

    # Test GET /jobs/{job_id}?sheet_name=... tab switching
    second_tab = state.sheets[1]
    switched = get_job(state.job_id, req, sheet_name=second_tab)
    assert switched.sheet_name == second_tab
    assert switched.preview[switched.header_row or 0] == ["Origin", "Destination", "500 lbs", "1000 lbs"]

    # Switch back to tab 0 for Fixed Origin + USD + FLAT_BREAK confirmation & ingestion
    get_job(state.job_id, req, sheet_name=state.sheets[0])
    map_payload = {
        "header_row": 0,
        "header_row_confirmed": True,
        "sheet_name": state.sheets[0],
        "mode": "weight",
        "rate_basis": "FLAT_BREAK",
        "currency": "USD",
        "weight_unit": "lb",
        "origin_type": "fixed",
        "fixed_origin_value": "Moncton, NB",
        "origin": None,
        "destination": 1,
        "rate_columns": [2, 3],
    }

    dr_res = dry_run(state.job_id, DryRunRequest(seq_id=1, mapping=map_payload), req)
    assert dr_res["seq_id"] == 1
    assert dr_res["status"] == "COMPLETE"
    assert dr_res["currency"] == "USD"

    conf_state = confirm_mapping(state.job_id, MappingRequest(**map_payload), req)
    assert conf_state.status.value == "ready"

    job_dict = job_store.get(state.job_id)
    sheet_id = ingest_job_to_quotelytics(job_dict, user["id"])
    assert sheet_id is not None

    rules = get_sheet_full_rules(sheet_id, user["id"])
    assert rules["sheet"]["currency"] == "USD"
    assert len(rules["breaks"]) == 4
    assert all(b["origin_spec"] == "MONCTON, NB" for b in rules["breaks"])
    assert all(b["rate_type"] == "FLAT" for b in rules["breaks"])


def test_open_manual_entry_failsafe_from_sheet_workflow():
    """POST /jobs/from-sheet/{sheet_id} hydrates a real backed job so dry-run and confirm succeed (no 404)."""
    user, token = _create_test_user("from_sheet")
    req = _make_mock_request(token)

    # Test both an empty-break sheet and a populated sheet
    empty_sheet_id = create_rate_sheet(
        user_id=user["id"],
        carrier_name="Failed PDF Sheet",
        service_name="Standard LTL",
        confirmation_status="PENDING_REVIEW",
        source_filename="unparsed.pdf",
        weight_unit="lb",
    )
    job_empty = create_job_from_sheet(empty_sheet_id, req)
    assert job_empty.status.value == "needs_mapping"
    assert job_empty.preview[0] == ["Origin", "Destination", "Minimum Charge", "500 lbs", "1000 lbs", "2000 lbs", "5000 lbs"]

    # Populated sheet with persisted breaks + minimums
    pop_sheet_id = create_rate_sheet(
        user_id=user["id"],
        carrier_name="Regional Freight",
        service_name="LTL",
        confirmation_status="PENDING_REVIEW",
        source_filename="regional.pdf",
        weight_unit="lb",
    )
    insert_carrier_minimums(pop_sheet_id, user["id"], [
        {"origin_spec": "TORONTO, ON", "dest_spec": "OTTAWA, ON", "min_charge": 90.0}
    ])
    insert_weight_breaks(pop_sheet_id, user["id"], [
        {"origin_spec": "TORONTO, ON", "dest_spec": "OTTAWA, ON", "min_weight": 500.0, "max_weight": 999.0, "break_name": "500 lbs", "base_rate": 24.0},
        {"origin_spec": "TORONTO, ON", "dest_spec": "OTTAWA, ON", "min_weight": 1000.0, "max_weight": 999999.0, "break_name": "1000 lbs", "base_rate": 19.5},
    ])

    job_pop = create_job_from_sheet(pop_sheet_id, req)
    assert job_pop.job_id.isalnum()
    assert job_pop.preview[0] == ["Origin", "Destination", "Minimum Charge", "500 lbs", "1000 lbs"]

    # Downstream dry-run and mapping confirmation must NOT 404
    mapping_cfg = {
        "header_row": 0,
        "header_row_confirmed": True,
        "sheet_name": job_pop.sheet_name,
        "mode": "weight",
        "rate_basis": "PER_CWT",
        "currency": "CAD",
        "weight_unit": "lb",
        "origin_type": "column",
        "origin": 0,
        "destination": 1,
        "base_cost_column": 2,
        "rate_columns": [3, 4],
    }
    dr_res = dry_run(job_pop.job_id, DryRunRequest(seq_id=2, mapping=mapping_cfg), req)
    assert dr_res["status"] == "COMPLETE"
    assert len(dr_res["sample_runs"]) == 1

    confirmed = confirm_mapping(job_pop.job_id, MappingRequest(**mapping_cfg), req)
    assert confirmed.status.value == "ready"


# ---------------------------------------------------------------------------
# 4. PDF & CSV Re-Formatter Coercion Tests
# ---------------------------------------------------------------------------

def test_reformatter_coerces_pdf_and_csv_without_openpyxl_crash():
    p1 = [
        (36, 740, "Carrier Shipment Manifest (lbs, CAD)", 14),
        (36, 700, "Origin", 10), (140, 700, "Destination", 10), (260, 700, "Weight (lbs)", 10), (360, 700, "500 lbs", 10),
        (36, 680, "Toronto, ON", 10), (140, 680, "Montreal, QC", 10), (260, 680, "1250", 10), (360, 680, "24.50", 10),
        (36, 660, "Toronto, ON", 10), (140, 660, "Ottawa, ON", 10), (260, 660, "850", 10), (360, 660, "19.00", 10),
    ]
    pdf_bytes = build_synthetic_pdf([p1])
    res_pdf = analyze_excel_sheet(pdf_bytes, "carrier_rate.pdf")
    assert res_pdf["filename"] == "carrier_rate.pdf"
    assert res_pdf["total_rows"] == 2
    assert "Origin" in res_pdf["headers"]
    assert "Destination" in res_pdf["headers"]

    csv_bytes = b"Origin,Destination,Weight (lbs),Rate\nToronto ON,Montreal QC,1200,24.50\n"
    res_csv = analyze_excel_sheet(csv_bytes, "carrier_rate.csv")
    assert res_csv["filename"] == "carrier_rate.csv"
    assert res_csv["total_rows"] == 1
    assert res_csv["column_mapping"]["origin"]["col_index"] == 0


# ---------------------------------------------------------------------------
# 5. Optional Benchmark Verification Against Uploaded FedEx PDFs
# ---------------------------------------------------------------------------

def test_fedex_benchmark_pdfs_when_present():
    express_path = r"C:/Users/Dylan/.gemini/antigravity/brain/ec698020-a512-4f06-ab67-4069143a572d/.user_uploaded/media_1795028362465_27d9ff45.pdf"
    ground_path = r"C:/Users/Dylan/.gemini/antigravity/brain/ec698020-a512-4f06-ab67-4069143a572d/.user_uploaded/media_1795028362465_4c628b83.pdf"
    if not (os.path.exists(express_path) and os.path.exists(ground_path)):
        pytest.skip("Benchmark FedEx PDF fixtures not present in workspace")

    with open(express_path, "rb") as f:
        express_tables = extract_pdf_tariff_tables(f.read())
    freight_tab = next(
        t for t in express_tables if "1Day" in t["sheet_name"] and t["archetype"] == "transposed_weight_zone"
    )
    assert freight_tab["headers"] == [
        "Destination Zone", "Minimum Charge", "151 to 299 lbs", "300 to 499 lbs",
        "500 to 999 lbs", "1000 to 1999 lbs", "2000+ lbs",
    ]
    assert freight_tab["rows"][0][:3] == ["Zone 9", "351.38", "$3.58"]
    assert freight_tab["rows"][-1][:3] == ["Zone 16", "595.78", "$6.07"]
    # Ensure no primary rate table has a bare unlabeled numeric column header
    for t in express_tables:
        if t["section_type"] == "rate_grid":
            for h in t["headers"]:
                assert not re.match(r"^\d+(?:\.\d+)?$", h.strip()), f"Unlabeled numeric header {h!r} in {t['sheet_name']}"

    with open(ground_path, "rb") as f:
        ground_tables = extract_pdf_tariff_tables(f.read())
    ground_tab = next(
        t for t in ground_tables if t["sheet_name"] == "FedEx Ground Rates" and t["section_type"] == "rate_grid"
    )
    assert ground_tab["archetype"] == "transposed_weight_zone"
    assert ground_tab["headers"][:4] == ["Destination Zone", "1 lb", "2 lbs", "3 lbs"]
    assert ground_tab["rows"][0][:2] == ["Zone 0", "$6.80"]
