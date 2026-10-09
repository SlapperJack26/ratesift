"""
Unit tests for safe ingestion:
- Zip bomb guard
- Merged cell forward filling
- Header normalization (NBSP, zero-width chars)
- Scan caps (500x100)
- Uncached formula detection
"""
import io
import zipfile
import pytest
from openpyxl import Workbook

from app.ingest import (
    IngestionError,
    check_uncached_formulas,
    check_zip_bomb,
    flatten_two_row_headers,
    load_sheet_grid,
    normalize_header,
)


def test_normalize_header_characters():
    # Test zero-width space, non-breaking space, double whitespace, and mixed case
    raw = "  Origin\u00a0City\u200b \r\n (POL)   "
    normalized = normalize_header(raw)
    assert normalized == "origin city (pol)"


def test_flatten_two_row_headers():
    row1 = ["Lanes", "Lanes", "Weight Breaks", "Weight Breaks", "Weight Breaks"]
    row2 = ["Origin", "Destination", "100", "500", "1000"]
    flattened = flatten_two_row_headers(row1, row2)
    assert flattened[0] == "Lanes Origin"
    assert flattened[1] == "Lanes Destination"
    assert flattened[2] == "Weight Breaks 100"
    assert flattened[3] == "Weight Breaks 500"
    assert flattened[4] == "Weight Breaks 1000"


def test_merged_cell_forward_filling(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["ACME Rates"])
    # Row 2: Merged "Break Points" across C2:E2
    ws.append(["Origin", "Destination", "Break Points", None, None])
    ws.merge_cells("C2:E2")
    # Row 3: Sub-headers 100, 500, 1000
    ws.append(["Toronto", "Montreal", 100, 500, 1000])
    file_path = str(tmp_path / "merged.xlsx")
    wb.save(file_path)

    grid, sheet = load_sheet_grid(file_path, ".xlsx")
    # In row 2 (index 1), cells at index 2, 3, 4 should all have "Break Points"
    assert grid[1][2] == "Break Points"
    assert grid[1][3] == "Break Points"
    assert grid[1][4] == "Break Points"


def test_scan_cap_enforcement(tmp_path):
    wb = Workbook()
    ws = wb.active
    # Create 600 rows x 120 columns
    for r in range(550):
        ws.append([f"R{r}C{c}" for c in range(110)])
    file_path = str(tmp_path / "large.xlsx")
    wb.save(file_path)

    grid, _ = load_sheet_grid(file_path, ".xlsx", max_rows=500, max_cols=100)
    assert len(grid) == 500
    assert len(grid[0]) == 100


def test_zip_bomb_detection(tmp_path):
    # Construct a synthetic zip bomb with excessive uncompressed size in metadata
    zip_path = str(tmp_path / "bomb.xlsx")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1 MB of zeros compresses to ~1 KB, repeating to simulate > 100 MB uncompressed
        large_chunk = b"\x00" * (1024 * 1024)
        for i in range(105):  # 105 MB uncompressed
            zf.writestr(f"xl/worksheets/sheet{i}.xml", large_chunk)

    with pytest.raises(IngestionError, match="potential zip bomb"):
        check_zip_bomb(zip_path)


def test_uncached_formula_detection(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Origin", "Destination", "Rate"])
    ws.append(["Toronto", "Montreal", "=SUM(10, 20)"])
    file_path = str(tmp_path / "formula.xlsx")
    wb.save(file_path)

    assert check_uncached_formulas(file_path) is True
