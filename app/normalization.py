"""
app/normalization.py
Shared rate sheet normalization function: single source of truth for converting
raw spreadsheet grid rows + user mapping dictionary into canonical rate sheet structures.
Used identically by both in-memory dry-run calculations and persistent database ingestion.
"""
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
from openpyxl.utils import get_column_letter

from services.break_header_parser import (
    ParsedBreak,
    parse_break_header,
    resolve_contiguous_weight_brackets,
)
from app.validation import parse_break_label


def normalize_location_field(city: Optional[str], region: Optional[str] = None) -> str:
    """Combines and normalizes city and region into canonical location string."""
    city_str = str(city or "").strip()
    # Normalize abbreviations
    city_str = re.sub(r"\bSt\.?\s+", "Saint ", city_str, flags=re.IGNORECASE)
    city_str = re.sub(r"\bFt\.?\s+", "Fort ", city_str, flags=re.IGNORECASE)
    city_str = re.sub(r"\bMt\.?\s+", "Mount ", city_str, flags=re.IGNORECASE)
    # Strip French accents
    city_str = unicodedata.normalize("NFKD", city_str).encode("ascii", "ignore").decode("ascii")
    city_str = re.sub(r"\s+", " ", city_str).strip()

    region_str = str(region or "").strip().upper()
    if region_str:
        region_str = unicodedata.normalize("NFKD", region_str).encode("ascii", "ignore").decode("ascii")
        return f"{city_str}, {region_str}" if city_str else region_str
    return city_str


def build_normalized_rate_sheet_records(
    mapping: Dict[str, Any],
    rows: List[List[Any]],
    filename: str = "tariff.xlsx",
    sheet_name: str = "Sheet1",
    carrier_name_override: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """
    Transforms raw spreadsheet grid rows and mapping instructions into:
    1. sheet_dict (metadata conforming to ql_rate_sheets schema)
    2. rules_dict ({"breaks": List[Dict], "minimums": List[Dict], "surcharges": List[Dict]})
    3. cell_trace_records (List[Dict] for cell coordinate auditing)
    """
    header_row_idx = int(mapping.get("header_row", 0))
    mode = str(mapping.get("mode") or "weight").lower()
    rate_basis = str(mapping.get("rate_basis") or "PER_CWT").upper()
    currency = str(mapping.get("currency") or "CAD").upper()
    weight_unit = str(mapping.get("weight_unit") or "lb").lower()
    max_skid_cap = int(mapping.get("max_skid_capacity") or 10)
    allow_deficit = bool(mapping.get("allow_deficit_rating", True))
    carrier_max_wt = mapping.get("carrier_max_weight")
    carrier_max_wt = float(carrier_max_wt) if carrier_max_wt is not None else 44000.0

    # Clean carrier name and qualify service name with sheet tab
    base_name = os.path.splitext(os.path.basename(filename))[0]
    raw_carrier = carrier_name_override or sheet_name or base_name
    if raw_carrier in ("Sheet1", "Sheet 1", "Sheet"):
        raw_carrier = base_name
    carrier_name = re.sub(r"[_]+", " ", str(raw_carrier)).strip()

    base_service = "Standard LTL" if mode == "weight" else "Skid / Pallet Freight"
    service_name = f"{base_service} ({sheet_name})" if sheet_name and sheet_name != "Sheet1" else base_service

    base_cost_col = mapping.get("base_cost_column")
    rate_cols = mapping.get("rate_columns") or []
    skid_tiers = mapping.get("skid_tiers") or []
    user_break_weights = mapping.get("user_break_weights") or {}

    # Determine headers
    headers = []
    if 0 <= header_row_idx < len(rows):
        headers = [str(c or "").strip() for c in rows[header_row_idx]]

    # Parse and resolve break boundaries for rate columns
    resolved_weight_by_col: Dict[int, ParsedBreak] = {}
    if mode == "weight":
        col_pbs = []
        for c_idx in rate_cols:
            h_txt = headers[c_idx] if c_idx < len(headers) else f"Col {c_idx + 1}"
            u_wt = user_break_weights.get(c_idx) or user_break_weights.get(str(c_idx))
            parsed_w = parse_break_label(h_txt, user_weight_fallback=u_wt)
            if parsed_w is not None and parsed_w >= 0:
                pb = ParsedBreak(
                    raw_header=h_txt,
                    break_name=h_txt,
                    min_weight=parsed_w,
                    max_weight=None,
                    is_open_ended=True,
                    break_value=parsed_w,
                )
            else:
                pb = parse_break_header(h_txt, mode_hint="weight")
                if pb is None:
                    pb = ParsedBreak(
                        raw_header=h_txt,
                        break_name=h_txt,
                        min_weight=0.0,
                        max_weight=None,
                        is_open_ended=True,
                        break_value=0.0,
                    )
            col_pbs.append((c_idx, pb))

        col_pbs.sort(key=lambda item: item[1].min_weight)
        res_pbs, _ = resolve_contiguous_weight_brackets([item[1] for item in col_pbs])
        for (c_idx, _), r_pb in zip(col_pbs, res_pbs):
            resolved_weight_by_col[c_idx] = r_pb

    tier_map_by_col: Dict[int, Dict[str, Any]] = {}
    if mode == "skid" and skid_tiers:
        for t in skid_tiers:
            c = t.get("column") or t.get("rate_column")
            if c is not None:
                tier_map_by_col[int(c)] = t

    extracted_breaks: List[Dict[str, Any]] = []
    extracted_minimums: List[Dict[str, Any]] = []
    cell_trace_records: List[Dict[str, Any]] = []
    current_section = ""

    # Origin and Destination mapping extraction (supports compound dict or int)
    origin_type = mapping.get("origin_type", "column")
    fixed_origin_val = mapping.get("fixed_origin_value")

    orig_map = mapping.get("origin")
    dest_map = mapping.get("destination")

    def _extract_loc(loc_spec: Any, row_data: List[Any]) -> str:
        if isinstance(loc_spec, dict):
            c_idx = loc_spec.get("city_column")
            r_idx = loc_spec.get("region_column")
            city = row_data[c_idx] if c_idx is not None and c_idx < len(row_data) else ""
            reg = row_data[r_idx] if r_idx is not None and r_idx < len(row_data) else ""
            return normalize_location_field(city, reg)
        elif isinstance(loc_spec, int) and loc_spec < len(row_data):
            return normalize_location_field(row_data[loc_spec])
        return ""

    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        excel_row_num = r_idx + 1

        # Check section header
        row_str_values = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
        if len(row_str_values) == 1 and ("to" in row_str_values[0].lower() or "lane" in row_str_values[0].lower()):
            current_section = row_str_values[0]
            continue

        # Origin
        if origin_type == "fixed" and fixed_origin_val:
            origin_val = normalize_location_field(fixed_origin_val)
        else:
            origin_val = _extract_loc(orig_map, row)

        # Destination
        dest_val = _extract_loc(dest_map, row)

        if not origin_val and current_section:
            origin_val = current_section
        if not dest_val and current_section:
            dest_val = current_section

        if not origin_val and not dest_val:
            continue

        # Extract Minimum Charge
        if base_cost_col is not None and base_cost_col < len(row):
            mc_val = row[base_cost_col]
            if mc_val is not None:
                clean_mc = re.sub(r"[^\d.]", "", str(mc_val).strip())
                try:
                    mc_num = float(clean_mc)
                    if mc_num > 0:
                        mc_cell = f"{get_column_letter(base_cost_col + 1)}{excel_row_num}"
                        extracted_minimums.append({
                            "zone_code": "DEFAULT",
                            "origin_spec": origin_val,
                            "dest_spec": dest_val,
                            "min_charge": mc_num,
                            "source_cell": f"[{mc_cell}]",
                        })
                except ValueError:
                    pass

        # Extract Rate Breaks
        if mode == "weight":
            for c_idx in rate_cols:
                if c_idx >= len(row):
                    continue
                val = row[c_idx]
                if val is None or str(val).strip() == "":
                    continue
                clean_val = re.sub(r"[^\d.]", "", str(val).strip())
                try:
                    rate_num = float(clean_val)
                except ValueError:
                    continue

                cell_ref = f"{get_column_letter(c_idx + 1)}{excel_row_num}"
                pb = resolved_weight_by_col.get(c_idx)
                b_name = pb.break_name if pb else (headers[c_idx] if c_idx < len(headers) else f"Break {c_idx}")
                min_w = pb.min_weight if pb else 0.0
                max_w = pb.max_weight if (pb and pb.max_weight is not None) else 999999.0

                extracted_breaks.append({
                    "zone_code": "DEFAULT",
                    "origin_spec": origin_val,
                    "dest_spec": dest_val,
                    "min_weight": min_w,
                    "max_weight": max_w,
                    "break_name": b_name,
                    "base_rate": rate_num,
                    "rate_type": "FLAT" if rate_basis == "FLAT_BREAK" else "CWT",
                    "source_cell": f"[{cell_ref}]",
                    "break_unit": "CWT" if rate_basis == "PER_CWT" else "FLAT",
                    "min_units": min_w,
                    "max_units": max_w,
                    "is_open_ended": 1 if max_w >= 999999.0 else 0,
                })

        elif mode == "skid":
            for c_idx in rate_cols:
                if c_idx >= len(row):
                    continue
                val = row[c_idx]
                if val is None or str(val).strip() == "":
                    continue
                clean_val = re.sub(r"[^\d.]", "", str(val).strip())
                try:
                    rate_num = float(clean_val)
                except ValueError:
                    continue

                cell_ref = f"{get_column_letter(c_idx + 1)}{excel_row_num}"
                tier_info = tier_map_by_col.get(c_idx, {})
                min_s = float(tier_info.get("min_units") if tier_info.get("min_units") is not None else (tier_info.get("min_skids") or 1.0))
                max_s = float(tier_info.get("max_units") if tier_info.get("max_units") is not None else (tier_info.get("max_skids") or min_s))
                t_name = tier_info.get("skid_range") or tier_info.get("name") or (f"{int(min_s)}-{int(max_s)} Skids" if min_s != max_s else f"{int(min_s)} Skid")
                if "skid" not in t_name.lower():
                    t_name = f"{t_name} Skids"

                extracted_breaks.append({
                    "zone_code": "DEFAULT",
                    "origin_spec": origin_val,
                    "dest_spec": dest_val,
                    "min_weight": min_s,
                    "max_weight": max_s,
                    "break_name": t_name,
                    "base_rate": rate_num,
                    "rate_type": tier_info.get("rate_type") or ("FLAT" if rate_basis == "FLAT_BREAK" else "PER_SKID"),
                    "source_cell": f"[{cell_ref}]",
                    "break_unit": "SKID",
                    "min_units": min_s,
                    "max_units": max_s,
                    "is_open_ended": 0,
                })

    sheet_dict = {
        "carrier_name": carrier_name,
        "service_name": service_name,
        "tariff_ref": "Failsafe Mapped Tariff",
        "mode": "LTL",
        "currency": currency,
        "weight_unit": weight_unit,
        "dim_unit": "in",
        "dim_divisor": None,
        "rounding_rule": "standard_2dp",
        "confirmation_status": "CONFIRMED",
        "source_filename": filename,
        "rating_basis": "WEIGHT_CWT" if mode == "weight" else "PALLET_TIER",
        "max_skid_capacity": max_skid_cap,
        "allow_deficit_rating": 1 if allow_deficit else 0,
        "no_minimum_confirmed": 1 if base_cost_col is None else 0,
        "failsafe_status": "ready",
        "max_weight_limit": carrier_max_wt,
        "max_piece_weight": 150.0,
        "max_length_in": 108.0,
        "max_girth_in": 165.0,
        "weight_rounding_rule": "CEIL_1LB",
    }

    rules_dict = {
        "breaks": extracted_breaks,
        "minimums": extracted_minimums,
        "surcharges": [],
    }

    return sheet_dict, rules_dict, cell_trace_records
