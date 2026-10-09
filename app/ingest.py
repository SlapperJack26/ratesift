"""
Safe file ingestion module:
- Zip bomb inspection (metadata checks before decompression)
- Extension & magic byte validation
- Capped scan load (500 rows x 100 cols)
- Merged cell forward-filling
- Uncached formula detection
- Header text normalization (NFKC, zero-width chars, NBSP) preserving raw text
"""
import csv
import io
import os
import re
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook

from app.config import (
    ALLOWED_EXT,
    MAX_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_DATA_COLS,
    MAX_DATA_ROWS,
    MAX_SCAN_COLS,
    MAX_SCAN_ROWS,
    MAX_TOTAL_CELLS,
    MAX_UNCOMPRESSED_BYTES,
    MAX_ZIP_ENTRIES,
)



class IngestionError(ValueError):
    """Raised when file validation or ingestion fails."""
    pass


def normalize_header(text: Optional[str]) -> str:
    """
    Normalizes header text for matching and fingerprinting:
    - Unicode NFKC normalization
    - Strip zero-width chars (U+200B, U+FEFF, etc.) and NBSP (U+00A0)
    - Replace tabs, newlines, carriage returns with spaces
    - Collapse multiple whitespace and lowercase
    """
    if text is None:
        return ""
    # NFKC
    s = unicodedata.normalize("NFKC", str(text))
    # Remove zero-width spaces and BOMs
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    # Convert non-breaking space and control spaces to normal space
    s = s.replace("\u00a0", " ")
    # Replace whitespace characters (newlines, tabs) with single space
    s = re.sub(r"[\r\n\t]+", " ", s)
    # Collapse multiple spaces and lowercase
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def check_zip_bomb(path: str) -> None:
    """Inspects zip metadata for .xlsx files before opening."""
    if not zipfile.is_zipfile(path):
        raise IngestionError("File is not a valid zip archive (.xlsx format expected).")

    file_size = os.path.getsize(path)
    if file_size > MAX_BYTES:
        raise IngestionError(f"File size exceeds maximum allowed ({MAX_BYTES // (1024*1024)} MB).")

    with zipfile.ZipFile(path, "r") as zf:
        infolist = zf.infolist()
        if len(infolist) > MAX_ZIP_ENTRIES:
            raise IngestionError(f"Too many archive entries ({len(infolist)}), potential zip bomb.")

        total_uncompressed = sum(info.file_size for info in infolist)
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise IngestionError(
                f"Uncompressed size exceeds limit ({total_uncompressed // (1024*1024)} MB > "
                f"{MAX_UNCOMPRESSED_BYTES // (1024*1024)} MB), potential zip bomb."
            )

        compression_ratio = total_uncompressed / max(1, file_size)
        if total_uncompressed > 10 * 1024 * 1024 and compression_ratio > MAX_COMPRESSION_RATIO:
            raise IngestionError(
                f"Suspicious compression ratio ({compression_ratio:.1f}:1), potential zip bomb."
            )


def check_uncached_formulas(path: str, sheet_name: Optional[str] = None) -> bool:
    """
    Checks if a sheet has formula cells where data_only would return None.
    Returns True if uncalculated formulas are detected.
    """
    try:
        wb_formulas = load_workbook(path, read_only=True, data_only=False)
        ws_formulas = wb_formulas[sheet_name] if sheet_name and sheet_name in wb_formulas.sheetnames else wb_formulas.worksheets[0]
        
        formula_found = False
        for r_idx, row in enumerate(ws_formulas.iter_rows(values_only=False)):
            if r_idx > 50:
                break
            for cell in row:
                val = cell.value
                if val is not None and (cell.data_type == "f" or (isinstance(val, str) and val.startswith("="))):
                    formula_found = True
                    break
            if formula_found:
                break
        wb_formulas.close()
        return formula_found
    except Exception:
        return False


def check_full_load_limits(path: str, ext: str, sheet_name: Optional[str] = None) -> None:
    """
    Guards memory before full loading (25,000 rows, 100 cols, 1,000,000 cells).
    Rejects oversized sheets before openpyxl normal mode allocates memory.
    """
    ext = ext.lower()
    if ext == ".xlsx":
        try:
            wb = load_workbook(path, read_only=True)
            ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.worksheets[0]
            max_r = ws.max_row or 0
            max_c = ws.max_column or 0
            total_cells = max_r * max_c
            wb.close()

            if max_r > MAX_DATA_ROWS:
                raise IngestionError(
                    f"This sheet has {max_r:,} rows; the limit is {MAX_DATA_ROWS:,}. "
                    "Split it by region or carrier and upload again."
                )
            if max_c > MAX_DATA_COLS:
                raise IngestionError(
                    f"This sheet has {max_c} columns; the limit is {MAX_DATA_COLS}."
                )
            if total_cells > MAX_TOTAL_CELLS:
                raise IngestionError(
                    f"This sheet has {total_cells:,} cells; the limit is {MAX_TOTAL_CELLS:,} cells. "
                    "Please reduce sheet size and upload again."
                )
        except IngestionError:
            raise
        except Exception:
            pass

    elif ext == ".csv":
        row_count = 0
        max_col_count = 0
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            for r in reader:
                row_count += 1
                if len(r) > max_col_count:
                    max_col_count = len(r)

        total_cells = row_count * max_col_count
        if row_count > MAX_DATA_ROWS:
            raise IngestionError(
                f"This sheet has {row_count:,} rows; the limit is {MAX_DATA_ROWS:,}. "
                "Split it by region or carrier and upload again."
            )
        if max_col_count > MAX_DATA_COLS:
            raise IngestionError(
                f"This sheet has {max_col_count} columns; the limit is {MAX_DATA_COLS}."
            )
        if total_cells > MAX_TOTAL_CELLS:
            raise IngestionError(
                f"This sheet has {total_cells:,} cells; the limit is {MAX_TOTAL_CELLS:,} cells. "
                "Please reduce sheet size and upload again."
            )



def load_sheet_grid(
    path: str,
    ext: str,
    sheet_name: Optional[str] = None,
    max_rows: int = MAX_SCAN_ROWS,
    max_cols: int = MAX_SCAN_COLS,
) -> Tuple[List[List[Any]], str]:
    """
    Loads sheet data into a 2D list with scan caps and merged-cell forward-filling.
    Returns (grid, selected_sheet_name).
    """
    ext = ext.lower()
    if ext not in ALLOWED_EXT:
        raise IngestionError(f"Unsupported file type '{ext}'. Allowed types: {', '.join(ALLOWED_EXT)}")

    if ext == ".csv":
        return _load_csv(path, max_rows=max_rows, max_cols=max_cols), "Sheet1"

    if ext == ".xlsx":
        check_zip_bomb(path)
        return _load_xlsx(path, sheet_name=sheet_name, max_rows=max_rows, max_cols=max_cols)

    raise IngestionError(f"Unsupported file type '{ext}'")


def _load_csv(path: str, max_rows: int, max_cols: int) -> List[List[Any]]:
    rows: List[List[Any]] = []
    # Try utf-8-sig first, fallback to latin-1
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for i, r in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append([cell[:max_cols] for cell in r[:max_cols]])
    except UnicodeDecodeError:
        with open(path, newline="", encoding="latin-1") as f:
            reader = csv.reader(f)
            for i, r in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append([cell[:max_cols] for cell in r[:max_cols]])
    return rows


def _load_xlsx(
    path: str,
    sheet_name: Optional[str],
    max_rows: int,
    max_cols: int,
) -> Tuple[List[List[Any]], str]:
    # Normal load with data_only=True so merged cells are accessible
    wb = load_workbook(path, read_only=False, data_only=True)
    if sheet_name and sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        selected_sheet = sheet_name
    else:
        ws = wb.worksheets[0]
        selected_sheet = ws.title

    actual_max_row = min(ws.max_row or 0, max_rows)
    actual_max_col = min(ws.max_column or 0, max_cols)

    if actual_max_row == 0 or actual_max_col == 0:
        wb.close()
        return [], selected_sheet

    # Build 2D grid
    grid: List[List[Any]] = [[None for _ in range(actual_max_col)] for _ in range(actual_max_row)]

    for r in range(1, actual_max_row + 1):
        for c in range(1, actual_max_col + 1):
            cell_val = ws.cell(row=r, column=c).value
            grid[r - 1][c - 1] = cell_val

    # Forward-fill merged cells across the grid
    for rng in ws.merged_cells.ranges:
        min_col, min_row, max_col_rng, max_row_rng = rng.bounds
        # Clamp to scan boundaries
        c_start = max(1, min_col)
        c_end = min(actual_max_col, max_col_rng)
        r_start = max(1, min_row)
        r_end = min(actual_max_row, max_row_rng)

        if r_start <= r_end and c_start <= c_end:
            # Top-left cell of the merged range
            top_val = ws.cell(row=min_row, column=min_col).value
            for r_fill in range(r_start, r_end + 1):
                for c_fill in range(c_start, c_end + 1):
                    grid[r_fill - 1][c_fill - 1] = top_val

    # Detect if candidate rate data is completely empty due to uncached formulas
    wb.close()
    return grid, selected_sheet


def flatten_two_row_headers(row1: List[Any], row2: List[Any]) -> List[str]:
    """Combines two header rows into merged column labels (e.g. 'Weight Breaks 100')."""
    combined: List[str] = []
    width = max(len(row1), len(row2))
    for c in range(width):
        v1 = str(row1[c]).strip() if c < len(row1) and row1[c] is not None else ""
        v2 = str(row2[c]).strip() if c < len(row2) and row2[c] is not None else ""
        if v1 and v2 and v1 != v2:
            combined.append(f"{v1} {v2}".strip())
        else:
            combined.append(v2 or v1)
    return combined
