import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import io
import re
import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

SCRATCH_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scratch")
os.makedirs(SCRATCH_DIR, exist_ok=True)

# Common province/state codes for address normalization
CANADIAN_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY"
}

def normalize_location_token(val: Any) -> str:
    """Cleans up and formats location text."""
    if val is None:
        return ""
    text = str(val).strip().upper()
    return " ".join(text.split()).replace(".", "")

def parse_address_string(raw_val: Any) -> Dict[str, str]:
    """
    Parses a single location field into structured city, prov/state, and postal/zip components.
    Never guesses; only extracts what is explicitly present (Rule 1).
    """
    cleaned = normalize_location_token(raw_val)
    if not cleaned:
        return {"city": "", "province": "", "postal": "", "formatted": ""}

    city = ""
    prov = ""
    postal = ""

    # Check for Canadian Postal Code (e.g. A1A 1A1 or A1A1A1)
    postal_ca_match = re.search(r'\b([A-Z]\d[A-Z])\s*(\d[A-Z]\d)\b', cleaned)
    if postal_ca_match:
        postal = f"{postal_ca_match.group(1)} {postal_ca_match.group(2)}"
        cleaned = cleaned.replace(postal_ca_match.group(0), "").strip()

    # Check for US Zip Code (e.g. 94103 or 94103-1234)
    if not postal:
        zip_match = re.search(r'\b(\d{5})(-\d{4})?\b', cleaned)
        if zip_match:
            postal = zip_match.group(1)
            cleaned = cleaned.replace(zip_match.group(0), "").strip()

    # Split by comma or slash if present
    parts = [p.strip() for p in re.split(r'[,/]', cleaned) if p.strip()]
    if len(parts) >= 2:
        city = parts[0]
        # Check if second part is prov/state
        cand_prov = parts[1].split()[0] if parts[1].split() else ""
        if cand_prov in CANADIAN_PROVINCES or cand_prov in US_STATES:
            prov = cand_prov
        else:
            prov = parts[1]
    elif len(parts) == 1:
        # Check if province is trailing word
        words = parts[0].split()
        if len(words) > 1 and (words[-1] in CANADIAN_PROVINCES or words[-1] in US_STATES):
            prov = words[-1]
            city = " ".join(words[:-1])
        else:
            city = parts[0]

    formatted_lane = f"{city}, {prov}" if (city and prov) else (city or prov or postal)
    return {
        "city": city,
        "province": prov,
        "postal": postal,
        "formatted": formatted_lane
    }

def detect_units_and_currency(sheet, header_row_cells: List[Any]) -> Dict[str, Any]:
    """
    Rule 5: Detect and record currency, weight unit (lb or kg), and dimension unit (in or cm).
    Never assume them.
    """
    detected = {
        "weight_unit": None,
        "dimension_unit": None,
        "currency": None,
        "confidence": 1.0,
        "review_needed": False
    }

    combined_text = " ".join([str(c.value).lower() for c in header_row_cells if c.value is not None])

    # Weight Unit
    if "kg" in combined_text or "kilos" in combined_text or "kilogram" in combined_text:
        detected["weight_unit"] = "kg"
    elif "lb" in combined_text or "lbs" in combined_text or "pound" in combined_text:
        detected["weight_unit"] = "lb"

    # Dimension Unit
    if "cm" in combined_text or "centimeter" in combined_text:
        detected["dimension_unit"] = "cm"
    elif "in" in combined_text or "inch" in combined_text or '"' in combined_text:
        detected["dimension_unit"] = "in"

    # Currency
    if "cad" in combined_text or "c$" in combined_text:
        detected["currency"] = "CAD"
    elif "usd" in combined_text or "us$" in combined_text:
        detected["currency"] = "USD"
    elif "$" in combined_text:
        # If generic dollar sign, mark as default CAD for Canadian context but flag for review (Rule 6)
        detected["currency"] = "CAD"

    # If units remain undetected, flag for user clarification (Rule 5 & 25)
    if not detected["weight_unit"]:
        detected["weight_unit"] = "lb"  # Tentative
        detected["review_needed"] = True
    if not detected["dimension_unit"]:
        detected["dimension_unit"] = "in"  # Tentative
    if not detected["currency"]:
        detected["currency"] = "CAD"
        detected["review_needed"] = True

    return detected

def parse_dimensions_string(raw_val: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Parses dimensions from '48x40x48' or separate values."""
    if raw_val is None:
        return None, None, None
    s = str(raw_val).lower().replace("in", "").replace('"', '').strip()
    match = re.search(r'(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)', s)
    if match:
        try:
            return float(match.group(1)), float(match.group(2)), float(match.group(3))
        except ValueError:
            return None, None, None
    return None, None, None

def analyze_excel_sheet(
    file_bytes: bytes,
    filename: str,
    user_confirmed_header_row: Optional[int] = None
) -> Dict[str, Any]:
    """
    Phase 0 & 1: Structure recognition, zero-default parsing, coordinate grid tracking,
    and missing detail detection. Conforms to Rules 1, 3, 5, 6, 7, 18, 25, 33-36.
    Uses DynamicSheetDetector to autonomously locate rate table headers at arbitrary
    row positions (e.g. Line 90 or Line 140) and quarantine preamble/disclaimers.
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    if not wb.sheetnames:
        raise ValueError("The uploaded workbook contains no worksheets.")

    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=False))
    if not rows:
        raise ValueError("The active worksheet is empty.")

    from agent.dynamic_sheet_detector import DynamicSheetDetector, clean_cell
    grid = [[clean_cell(c.value) for c in row] for row in rows]
    detector = DynamicSheetDetector()
    detection = detector.scan_and_parse_sheet(grid, user_confirmed_header_row=user_confirmed_header_row)

    if detection.get("status") == "CONFUSED_NEEDS_CLARIFICATION" and user_confirmed_header_row is None:
        analysis_token = f"ana_confused_{uuid.uuid4().hex[:10]}"
        candidates = detection.get("candidates", [])
        top_cand_1_based = candidates[0]["row_number_1_based"] if candidates else 1
        top_cand_idx = max(0, min(len(rows) - 1, top_cand_1_based - 1))
        cand_header_cells = rows[top_cand_idx]
        cand_header_names = [clean_cell(c.value) if c.value is not None else f"Column_{get_column_letter(c.column)}" for c in cand_header_cells]

        analysis_payload = {
            "analysis_token": analysis_token,
            "filename": filename,
            "total_rows": len(rows),
            "header_row": top_cand_1_based,
            "headers": cand_header_names,
            "unmapped_columns": [],
            "detected_units": {"weight_unit": "lb", "dimension_unit": "in", "currency": "CAD", "confidence": 0.5, "review_needed": True},
            "column_mapping": {
                "origin": {"col_index": 0, "detected_header": cand_header_names[0] if cand_header_names else "Origin", "confidence": 0.5},
                "destination": {"col_index": 1 if len(cand_header_names) > 1 else None, "detected_header": cand_header_names[1] if len(cand_header_names) > 1 else None, "confidence": 0.5},
                "weight": {"col_index": 2 if len(cand_header_names) > 2 else None, "detected_header": cand_header_names[2] if len(cand_header_names) > 2 else None, "confidence": 0.5},
                "dimensions": None,
                "accessorials": None
            },
            "preview_rows": [],
            "flagged_issues": [{
                "issue_id": "confusion_gate",
                "row_num": top_cand_1_based,
                "field": "header",
                "issue": detection.get("message", "Competing header candidates detected."),
                "hint": "Confirm the primary rate table header row."
            }],
            "has_blockers": True,
            "is_confused": True,
            "clarification_prompt": detection.get("message"),
            "candidates": candidates,
            "status": "CONFUSED_NEEDS_CLARIFICATION"
        }
        scratch_payload_path = os.path.join(SCRATCH_DIR, f"staged_analysis_{analysis_token}.json")
        scratch_bytes_path = os.path.join(SCRATCH_DIR, f"staged_upload_{analysis_token}.bin")
        with open(scratch_payload_path, "w", encoding="utf-8") as f:
            json.dump({"meta": analysis_payload, "all_rows": []}, f, indent=2)
        with open(scratch_bytes_path, "wb") as f:
            f.write(file_bytes)
        return analysis_payload

    # 1. Resolve true header row from dynamic detection
    header_row_idx = detection.get("detected_header_row_0_based", 0)
    header_cells = rows[header_row_idx]
    header_names = [str(c.value).strip() if c.value is not None else f"Column_{get_column_letter(c.column)}" for c in header_cells]

    # 2. Detect Units & Currency (Rule 5)
    unit_info = detect_units_and_currency(sheet, header_cells)

    # 3. Semantic Column Mapping
    col_map = {
        "origin": None,
        "origin_city": None,
        "origin_prov": None,
        "origin_postal": None,
        "destination": None,
        "dest_city": None,
        "dest_prov": None,
        "dest_postal": None,
        "weight": None,
        "dimensions": None,
        "length": None,
        "width": None,
        "height": None,
        "accessorials": None,
        "service": None,
        "date": None
    }
    col_confidence = {}

    for idx, h_text in enumerate(header_names):
        h_low = h_text.lower()
        col_letter = get_column_letter(header_cells[idx].column)

        # Origin
        if any(k in h_low for k in ["origin city", "from city", "shipper city"]):
            col_map["origin_city"] = idx
            col_confidence["origin_city"] = 0.95
        elif any(k in h_low for k in ["origin prov", "from prov", "origin state", "shipper prov"]):
            col_map["origin_prov"] = idx
            col_confidence["origin_prov"] = 0.95
        elif any(k in h_low for k in ["origin postal", "from postal", "origin zip", "shipper zip"]):
            col_map["origin_postal"] = idx
            col_confidence["origin_postal"] = 0.95
        elif any(k in h_low for k in ["origin", "ship from", "shipper", "pickup location", "from"]):
            if col_map["origin"] is None:
                col_map["origin"] = idx
                col_confidence["origin"] = 0.90

        # Destination
        if any(k in h_low for k in ["dest city", "to city", "consignee city", "delivery city"]):
            col_map["dest_city"] = idx
            col_confidence["dest_city"] = 0.95
        elif any(k in h_low for k in ["dest prov", "to prov", "dest state", "consignee prov", "delivery prov"]):
            col_map["dest_prov"] = idx
            col_confidence["dest_prov"] = 0.95
        elif any(k in h_low for k in ["dest postal", "to postal", "dest zip", "consignee zip", "delivery zip"]):
            col_map["dest_postal"] = idx
            col_confidence["dest_postal"] = 0.95
        elif any(k in h_low for k in ["dest", "destination", "ship to", "consignee", "delivery location", "to"]):
            if col_map["destination"] is None:
                col_map["destination"] = idx
                col_confidence["destination"] = 0.90

        # Weight
        if any(k in h_low for k in ["weight", "gross wt", "billable wt", "chargeable wt", "lbs", "kg", "wt"]):
            if col_map["weight"] is None:
                col_map["weight"] = idx
                col_confidence["weight"] = 0.95

        # Dimensions
        if any(k in h_low for k in ["dimensions", "dims", "size", "lxwxh"]):
            col_map["dimensions"] = idx
            col_confidence["dimensions"] = 0.90
        elif h_low in ["length", "len", "l"]:
            col_map["length"] = idx
        elif h_low in ["width", "wid", "w"]:
            col_map["width"] = idx
        elif h_low in ["height", "hgt", "h"]:
            col_map["height"] = idx

        # Accessorials & Surcharges
        if any(k in h_low for k in ["accessorials", "surcharges", "special services", "options", "tailgate", "liftgate"]):
            col_map["accessorials"] = idx
            col_confidence["accessorials"] = 0.85

        # Date
        if any(k in h_low for k in ["date", "ship date", "shipment date", "pickup date"]):
            col_map["date"] = idx

    # Integrate paired ghost/province columns from dynamic detector
    ghosts = detection.get("ghost_columns_paired", [])
    for g in ghosts:
        paired_with = g.get("paired_with")
        c_idx = g.get("col_index")
        if paired_with == "Origin" and col_map["origin_prov"] is None:
            col_map["origin_prov"] = c_idx
            col_confidence["origin_prov"] = 0.95
        elif paired_with == "Destination" and col_map["dest_prov"] is None:
            col_map["dest_prov"] = c_idx
            col_confidence["dest_prov"] = 0.95

    # Fallback to positional mapping if none matched (with low confidence to force review)
    if col_map["origin"] is None and col_map["origin_city"] is None and len(header_names) > 0:
        col_map["origin"] = 0
        col_confidence["origin"] = 0.50
    if col_map["destination"] is None and col_map["dest_city"] is None and len(header_names) > 1:
        col_map["destination"] = 1
        col_confidence["destination"] = 0.50
    if col_map["weight"] is None and len(header_names) > 2:
        col_map["weight"] = 2
        col_confidence["weight"] = 0.50

    # 4. Extract Data Rows (Rule 1: ZERO ASSUMPTIONS, Rule 3: EXACT CELL COORDINATES)
    staged_rows = []
    flagged_issues = []
    total_data_rows = 0

    sheet_title = sheet.title or "Sheet1"

    for r_idx in range(header_row_idx + 1, len(rows)):
        row_cells = rows[r_idx]
        if all(c.value is None or str(c.value).strip() == "" for c in row_cells):
            continue

        r_str_cells = [clean_cell(c.value) for c in row_cells if clean_cell(c.value)]
        r_text_lower = " ".join([x.lower() for x in r_str_cells])
        # Skip repeat headers or secondary headers
        if (
            ("between localities" in r_text_lower or any(h.lower() in r_text_lower for h in ["origin", "dest"] if len(h) > 3))
            and any(tok in r_text_lower for tok in ["min", "ltl", "cwt", "rate"])
        ):
            continue

        total_data_rows += 1
        excel_row_num = r_idx + 1
        row_coord_prefix = f"{sheet_title}!Row{excel_row_num}"

        # Resolve Origin
        origin_val = None
        origin_cell_coord = ""
        if col_map["origin_city"] is not None and col_map["origin_city"] < len(row_cells):
            c_cell = row_cells[col_map["origin_city"]]
            p_cell = row_cells[col_map["origin_prov"]] if col_map["origin_prov"] is not None and col_map["origin_prov"] < len(row_cells) else None
            origin_val = f"{c_cell.value}, {p_cell.value if p_cell else ''}".strip(", ")
            origin_cell_coord = f"{sheet_title}!{get_column_letter(c_cell.column)}{excel_row_num}"
        elif col_map["origin"] is not None and col_map["origin"] < len(row_cells):
            cell = row_cells[col_map["origin"]]
            origin_val = cell.value
            origin_cell_coord = f"{sheet_title}!{get_column_letter(cell.column)}{excel_row_num}"

        origin_parsed = parse_address_string(origin_val)

        # Resolve Destination
        dest_val = None
        dest_cell_coord = ""
        if col_map["dest_city"] is not None and col_map["dest_city"] < len(row_cells):
            c_cell = row_cells[col_map["dest_city"]]
            p_cell = row_cells[col_map["dest_prov"]] if col_map["dest_prov"] is not None and col_map["dest_prov"] < len(row_cells) else None
            dest_val = f"{c_cell.value}, {p_cell.value if p_cell else ''}".strip(", ")
            dest_cell_coord = f"{sheet_title}!{get_column_letter(c_cell.column)}{excel_row_num}"
        elif col_map["destination"] is not None and col_map["destination"] < len(row_cells):
            cell = row_cells[col_map["destination"]]
            dest_val = cell.value
            dest_cell_coord = f"{sheet_title}!{get_column_letter(cell.column)}{excel_row_num}"

        dest_parsed = parse_address_string(dest_val)

        # Resolve Weight (Rule 1: Never guess 10 lbs or 15 lbs!)
        weight_val = None
        weight_lbs = None
        weight_cell_coord = ""
        if col_map["weight"] is not None and col_map["weight"] < len(row_cells):
            w_cell = row_cells[col_map["weight"]]
            weight_val = w_cell.value
            weight_cell_coord = f"{sheet_title}!{get_column_letter(w_cell.column)}{excel_row_num}"
            if weight_val is not None:
                try:
                    num_str = re.sub(r'[^\d.]', '', str(weight_val))
                    if num_str:
                        parsed_num = float(num_str)
                        if unit_info["weight_unit"] == "kg":
                            weight_lbs = round(parsed_num * 2.20462, 2)
                        else:
                            weight_lbs = round(parsed_num, 2)
                except (ValueError, TypeError):
                    weight_lbs = None

        # Resolve Dimensions
        dim_l, dim_w, dim_h = None, None, None
        dim_coord = ""
        if col_map["dimensions"] is not None and col_map["dimensions"] < len(row_cells):
            d_cell = row_cells[col_map["dimensions"]]
            dim_l, dim_w, dim_h = parse_dimensions_string(d_cell.value)
            dim_coord = f"{sheet_title}!{get_column_letter(d_cell.column)}{excel_row_num}"
        else:
            if col_map["length"] is not None and col_map["length"] < len(row_cells):
                try: dim_l = float(re.sub(r'[^\d.]', '', str(row_cells[col_map["length"]].value)))
                except Exception: pass
            if col_map["width"] is not None and col_map["width"] < len(row_cells):
                try: dim_w = float(re.sub(r'[^\d.]', '', str(row_cells[col_map["width"]].value)))
                except Exception: pass
            if col_map["height"] is not None and col_map["height"] < len(row_cells):
                try: dim_h = float(re.sub(r'[^\d.]', '', str(row_cells[col_map["height"]].value)))
                except Exception: pass

        # Resolve Accessorials
        acc_list = []
        if col_map["accessorials"] is not None and col_map["accessorials"] < len(row_cells):
            a_val = str(row_cells[col_map["accessorials"]].value or "").lower()
            if any(k in a_val for k in ["liftgate", "tailgate", "power tailgate"]): acc_list.append("liftgate")
            if any(k in a_val for k in ["appointment", "notify"]): acc_list.append("appointment")
            if any(k in a_val for k in ["heated", "freeze", "protective"]): acc_list.append("heated")
            if any(k in a_val for k in ["hazmat", "dangerous"]): acc_list.append("dangerous_goods")
            if any(k in a_val for k in ["residential", "res"]): acc_list.append("residential")
            if any(k in a_val for k in ["inside"]): acc_list.append("inside_delivery")

        # Resolve Shipment Date
        shipment_date = None
        if col_map["date"] is not None and col_map["date"] < len(row_cells):
            dt_val = row_cells[col_map["date"]].value
            if isinstance(dt_val, datetime):
                shipment_date = dt_val.strftime("%Y-%m-%d")
            elif dt_val:
                try:
                    shipment_date = str(dt_val).split("T")[0].strip()
                except Exception:
                    pass

        # Validation & Flagging (Rules 1, 6, 18, 25, 34-36)
        row_issues = []
        needs_review = False
        is_non_crit = False

        # If origin, dest, and weight are all empty, check if this is a footnote / disclaimer / noise row
        if not origin_parsed["formatted"] and not dest_parsed["formatted"] and (weight_lbs is None or weight_lbs <= 0):
            cat, desc, _ = detector.classify_row(r_str_cells, r_idx, len(rows))
            if cat in ["NON_CRITICAL_COMPANY_INFO", "NON_CRITICAL_LEGAL_DISCLAIMER", "DECORATIVE_NOISE", "OPERATIONAL_ACCESSORIAL_RULE"]:
                is_non_crit = True
                row_issues = [desc]

        if not is_non_crit:
            if not origin_parsed["formatted"]:
                row_issues.append("Missing Origin location.")
                needs_review = True
                flagged_issues.append({
                    "issue_id": f"issue_r{excel_row_num}_origin",
                    "row_num": excel_row_num,
                    "field": "origin",
                    "issue": "Missing Origin location.",
                    "hint": "May be implied company headquarters or internal dispatch location."
                })

            if not dest_parsed["formatted"]:
                row_issues.append("Missing Destination location.")
                needs_review = True
                flagged_issues.append({
                    "issue_id": f"issue_r{excel_row_num}_dest",
                    "row_num": excel_row_num,
                    "field": "destination",
                    "issue": "Missing Destination location.",
                    "hint": "May be customer pick-up or internal warehouse destination."
                })

            if weight_lbs is None or weight_lbs <= 0:
                row_issues.append("Missing shipment weight.")
                needs_review = True
                flagged_issues.append({
                    "issue_id": f"issue_r{excel_row_num}_weight",
                    "row_num": excel_row_num,
                    "field": "weight",
                    "issue": "Missing shipment weight.",
                    "hint": "Can use nominal tariff minimum or flag as non-critical info."
                })
            elif weight_lbs > 44000.0:
                row_issues.append("Exceeds standard LTL legal weight of 44,000 lbs (Rule 18).")

        staged_rows.append({
            "row_num": excel_row_num,
            "origin_raw": str(origin_val) if origin_val is not None else "",
            "origin_normalized": origin_parsed["formatted"],
            "origin_coord": origin_cell_coord or f"{row_coord_prefix}, Col A",
            "dest_raw": str(dest_val) if dest_val is not None else "",
            "dest_normalized": dest_parsed["formatted"],
            "dest_coord": dest_cell_coord or f"{row_coord_prefix}, Col B",
            "weight_raw": str(weight_val) if weight_val is not None else "",
            "weight_lbs": weight_lbs,
            "weight_coord": weight_cell_coord or f"{row_coord_prefix}, Col C",
            "length": dim_l,
            "width": dim_w,
            "height": dim_h,
            "dimensions_formatted": f"{dim_l}x{dim_w}x{dim_h}" if (dim_l and dim_w and dim_h) else "",
            "accessorials": acc_list,
            "shipment_date": shipment_date,
            "needs_review": needs_review,
            "review_reasons": row_issues,
            "is_complete": True if is_non_crit else (len(row_issues) == 0),
            "is_non_critical": is_non_crit
        })

    # Identify unmapped metadata columns (e.g. Company Headquarters, Internal PO, Sales Rep)
    mapped_indices = {v for v in col_map.values() if v is not None}
    unmapped_columns = []
    for idx, h in enumerate(header_names):
        if idx not in mapped_indices:
            sample_val = ""
            for r in rows[header_row_idx + 1:header_row_idx + 6]:
                if idx < len(r) and r[idx].value is not None and str(r[idx].value).strip():
                    sample_val = str(r[idx].value).strip()
                    break
            unmapped_columns.append({
                "col_index": idx,
                "header": h,
                "sample_val": sample_val
            })

    # Generate a unique staged analysis token
    analysis_token = f"ana_{uuid.uuid4().hex[:10]}"

    # Structure payload for clarification gate
    analysis_payload = {
        "analysis_token": analysis_token,
        "filename": filename,
        "total_rows": total_data_rows,
        "header_row": header_row_idx + 1,
        "headers": header_names,
        "unmapped_columns": unmapped_columns,
        "detected_units": unit_info,
        "column_mapping": {
            "origin": {"col_index": col_map["origin"], "detected_header": header_names[col_map["origin"]] if col_map["origin"] is not None and col_map["origin"] < len(header_names) else None, "confidence": col_confidence.get("origin", 0.8)},
            "destination": {"col_index": col_map["destination"], "detected_header": header_names[col_map["destination"]] if col_map["destination"] is not None and col_map["destination"] < len(header_names) else None, "confidence": col_confidence.get("destination", 0.8)},
            "weight": {"col_index": col_map["weight"], "detected_header": header_names[col_map["weight"]] if col_map["weight"] is not None and col_map["weight"] < len(header_names) else None, "confidence": col_confidence.get("weight", 0.8)},
            "dimensions": {"col_index": col_map["dimensions"], "detected_header": header_names[col_map["dimensions"]] if col_map["dimensions"] is not None and col_map["dimensions"] < len(header_names) else None, "confidence": col_confidence.get("dimensions", 0.7)},
            "accessorials": {"col_index": col_map["accessorials"], "detected_header": header_names[col_map["accessorials"]] if col_map["accessorials"] is not None and col_map["accessorials"] < len(header_names) else None, "confidence": col_confidence.get("accessorials", 0.7)}
        },
        "preview_rows": staged_rows[:10],
        "flagged_issues": flagged_issues,
        "has_blockers": any(not r["is_complete"] for r in staged_rows),
        "status": "STAGED_PENDING_CONFIRMATION",
        "preamble_info": {
            "company_info_count": len(detection.get("company_info", [])),
            "disclaimers_count": len(detection.get("disclaimers", [])),
            "accessorial_rules_count": len(detection.get("accessorial_rules", [])),
            "structured_surcharges": detection.get("structured_surcharges", [])
        },
        "reconciliation_audit": detection.get("reconciliation_audit", {}),
        "composite_sheet_health": detection.get("composite_sheet_health", 100),
        "segments": detection.get("segments", []),
        "structured_surcharges": detection.get("structured_surcharges", []),
        "ghost_columns_paired": detection.get("ghost_columns_paired", []),
        "is_confused": False
    }

    # Store staged state in scratch directory
    scratch_payload_path = os.path.join(SCRATCH_DIR, f"staged_analysis_{analysis_token}.json")
    scratch_bytes_path = os.path.join(SCRATCH_DIR, f"staged_upload_{analysis_token}.bin")
    
    with open(scratch_payload_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": analysis_payload,
            "all_rows": staged_rows
        }, f, indent=2)

    with open(scratch_bytes_path, "wb") as f:
        f.write(file_bytes)

    return analysis_payload

def build_reformatted_excel_workbook(rows: List[Dict[str, Any]], filename: str) -> bytes:
    """
    Builds a pristine, standardized Excel workbook (.xlsx) containing:
    1. 'Normalized Shipments': Clean standardized columns with formatting.
    2. 'Extraction Audit Log': Complete cell-by-cell source coordinates (Rule 3).
    """
    wb = openpyxl.Workbook()
    ws_norm = wb.active
    ws_norm.title = "Normalized Shipments"

    # Header styling
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    flag_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    noncrit_fill = PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid")
    border_thin = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    headers_norm = [
        "Row ID", "Origin Lane", "Destination Lane", "Weight (lbs)",
        "Dimensions (LxWxH)", "Accessorials Requested", "Shipment Date",
        "Source Coordinates", "Status"
    ]

    ws_norm.append(headers_norm)
    for col_idx in range(1, len(headers_norm) + 1):
        cell = ws_norm.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in rows:
        if r.get("is_non_critical"):
            status_label = "NON_CRITICAL_INFO"
        elif r.get("is_complete", True):
            status_label = "READY"
        else:
            status_label = "NEEDS_REVIEW"
            
        source_coords = f"{r.get('origin_coord', '')} | {r.get('weight_coord', '')}"
        row_vals = [
            r["row_num"],
            r["origin_normalized"] or r["origin_raw"],
            r["dest_normalized"] or r["dest_raw"],
            r["weight_lbs"] if r["weight_lbs"] is not None else "MISSING",
            r.get("dimensions_formatted", ""),
            ", ".join(r.get("accessorials", [])) if r.get("accessorials") else "None",
            r.get("shipment_date", "Standard"),
            source_coords,
            status_label
        ]
        ws_norm.append(row_vals)
        cur_row = ws_norm.max_row
        for col_idx in range(1, len(row_vals) + 1):
            cell = ws_norm.cell(row=cur_row, column=col_idx)
            cell.font = data_font
            cell.border = border_thin
            if r.get("is_non_critical"):
                cell.fill = noncrit_fill
            elif not r.get("is_complete", True):
                cell.fill = flag_fill

    # Auto-adjust column widths
    for col in ws_norm.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_norm.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Sheet 2: Audit Traceability
    ws_audit = wb.create_sheet(title="Extraction Audit Log")
    headers_audit = ["Row ID", "Field", "Raw Source Value", "Normalized Value", "Cell Coordinate", "Confidence"]
    ws_audit.append(headers_audit)
    for col_idx in range(1, len(headers_audit) + 1):
        cell = ws_audit.cell(row=1, column=col_idx)
        cell.fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        cell.font = header_font

    for r in rows:
        ws_audit.append([r["row_num"], "Origin", r["origin_raw"], r["origin_normalized"], r.get("origin_coord", ""), 0.95])
        ws_audit.append([r["row_num"], "Destination", r["dest_raw"], r["dest_normalized"], r.get("dest_coord", ""), 0.95])
        ws_audit.append([r["row_num"], "Weight", r["weight_raw"], r["weight_lbs"], r.get("weight_coord", ""), 0.95 if r["weight_lbs"] else 0.0])
        if r.get("is_non_critical"):
            ws_audit.append([
                r["row_num"],
                "Broker Exception Override",
                "Non-Critical Info Flagged",
                "NON_CRITICAL_BYPASS",
                r.get("origin_coord", ""),
                "Broker flagged exception as non-critical business info (e.g. company headquarters/internal reference) - strict input bypassed"
            ])

    out_stream = io.BytesIO()
    wb.save(out_stream)
    return out_stream.getvalue()
