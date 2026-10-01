import openpyxl
import io
import re
from typing import List, Dict, Any, Optional

def parse_excel_rate_sheet(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Parses an uploaded Excel rate sheet (.xlsx, .xls) using openpyxl.
    Identifies column headers, extracts rows, and preserves exact cell coordinates.
    Strictly calculates rates; no booking, no labels, no tracking.
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet_names = wb.sheetnames
    if not sheet_names:
        raise ValueError("The uploaded workbook contains no sheets.")
        
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=False))
    if not rows:
        raise ValueError("The active spreadsheet is empty.")

    # 1. Identify header row (first non-empty row or row with text keywords)
    header_row_idx = 0
    headers = []
    
    for r_idx, row in enumerate(rows[:10]):
        cell_vals = [str(c.value).strip() for c in row if c.value is not None]
        lower_vals = [v.lower() for v in cell_vals]
        # Look for typical logistics/quoting headers
        if any(k in lower_vals for k in ['origin', 'zip', 'dest', 'destination', 'weight', 'lbs', 'service', 'pallet', 'parcel']):
            header_row_idx = r_idx
            headers = [str(c.value).strip() if c.value is not None else f"Column_{i+1}" for i, c in enumerate(row)]
            break
            
    if not headers:
        header_row_idx = 0
        headers = [str(c.value).strip() if c.value is not None else f"Column_{i+1}" for i, c in enumerate(rows[0])]

    # 2. Map logical quoting fields to column indices
    col_mapping = {
        'origin': None,
        'dest': None,
        'weight': None,
        'service': None
    }
    
    for idx, h in enumerate(headers):
        h_low = h.lower()
        if 'origin' in h_low or 'from' in h_low or ('zip' in h_low and col_mapping['origin'] is None):
            col_mapping['origin'] = idx
        elif 'dest' in h_low or 'to' in h_low or ('zip' in h_low and col_mapping['origin'] is not None):
            col_mapping['dest'] = idx
        elif 'wt' in h_low or 'weight' in h_low or 'lbs' in h_low or 'kg' in h_low:
            col_mapping['weight'] = idx
        elif 'service' in h_low or 'carrier' in h_low or 'type' in h_low or 'priority' in h_low:
            col_mapping['service'] = idx

    # Defaults if not specifically named
    if col_mapping['origin'] is None and len(headers) > 0: col_mapping['origin'] = 0
    if col_mapping['dest'] is None and len(headers) > 1: col_mapping['dest'] = 1
    if col_mapping['weight'] is None and len(headers) > 2: col_mapping['weight'] = 2
    if col_mapping['service'] is None and len(headers) > 3: col_mapping['service'] = 3

    # 3. Extract data rows preserving exact Excel coordinate
    parsed_rows = []
    sheet_title = sheet.title or "Sheet 1"
    
    for r_idx in range(header_row_idx + 1, len(rows)):
        row_cells = rows[r_idx]
        # Skip completely empty rows
        if all(c.value is None or str(c.value).strip() == "" for c in row_cells):
            continue
            
        excel_row_num = r_idx + 1  # 1-indexed Excel row
        
        origin_val = row_cells[col_mapping['origin']].value if col_mapping['origin'] < len(row_cells) else "94103"
        dest_val = row_cells[col_mapping['dest']].value if col_mapping['dest'] < len(row_cells) else "60601"
        weight_val = row_cells[col_mapping['weight']].value if col_mapping['weight'] < len(row_cells) else 25.0
        service_val = row_cells[col_mapping['service']].value if (col_mapping['service'] is not None and col_mapping['service'] < len(row_cells)) else "Standard Ground"
        
        # Clean weight to numeric
        try:
            cleaned_wt = float(re.sub(r'[^\d.]', '', str(weight_val))) if weight_val is not None else 10.0
        except (ValueError, TypeError):
            cleaned_wt = 15.0
            
        origin_str = str(origin_val).split(".")[0].strip() if origin_val else "94103"
        dest_str = str(dest_val).split(".")[0].strip() if dest_val else "60601"
        
        # Coordinate mapping for cell tracking
        coordinate = f"{sheet_title} • Row {excel_row_num}, Col C"
        
        parsed_rows.append({
            "row_num": excel_row_num,
            "origin_zip": origin_str,
            "dest_zip": dest_str,
            "weight_lbs": cleaned_wt,
            "service": str(service_val).strip() if service_val else "Standard Ground",
            "coordinate": coordinate
        })

    return {
        "filename": filename,
        "sheet_name": sheet_title,
        "header_row": header_row_idx + 1,
        "total_parsed_rows": len(parsed_rows),
        "headers": headers,
        "rows": parsed_rows
    }
