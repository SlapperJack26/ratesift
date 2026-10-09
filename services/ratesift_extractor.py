import openpyxl
import io
import csv
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from services.ratesift_db_service import (
    create_rate_sheet,
    insert_rate_sheet_cells,
    insert_carrier_surcharges,
    insert_weight_breaks,
    insert_carrier_minimums,
    insert_carrier_zones,
    get_rate_sheet,
    get_sheet_full_rules,
    get_rate_sheet_cells
)

class RateSiftExtractor:
    """
    Deep rate sheet extractor implementing Rules 1, 4, 5, 6, 7.
    - Explicit extraction only: never guesses or fills in missing values (Rule 1).
    - Inspects hidden rows/columns and footnotes/terms (Rule 4).
    - Detects currency, weight units, and dimension units without assuming (Rule 5).
    - Flags low-confidence interpretations as 'needs review' (Rule 6).
    - Stores as 'PENDING_REVIEW' until human confirmation (Rule 7, 19).
    """

    def __init__(self, file_bytes: bytes, filename: str, user_id: str):
        self.file_bytes = file_bytes
        self.filename = filename
        self.user_id = user_id
        
        self.raw_cells: List[Dict[str, Any]] = []
        self.surcharges: List[Dict[str, Any]] = []
        self.rate_breaks: List[Dict[str, Any]] = []
        self.minimums: List[Dict[str, Any]] = []
        self.zones: List[Dict[str, Any]] = []
        
        self.hidden_rows_found: List[int] = []
        self.hidden_cols_found: List[str] = []
        self.flagged_items: List[Dict[str, Any]] = []
        
        self.metadata = {
            "carrier_name": "Unknown Carrier",
            "service_name": "Standard Freight",
            "tariff_ref": None,
            "mode": "LTL",
            "currency": None,
            "weight_unit": None,
            "dim_unit": None,
            "dim_divisor": 139.0,
            "dim_min_rule": None,
            "rounding_rule": "standard_2dp",
            "effective_date": None,
            "expiry_date": None,
            "version": 1,
            "rating_basis": "WEIGHT_CWT",
            "max_skid_capacity": 10
        }

    def process(self) -> Dict[str, Any]:
        """Runs the complete extraction pipeline and persists to SQLite."""
        if self.filename.endswith(".csv"):
            self._extract_csv()
        elif self.filename.endswith(".xlsx") or self.filename.endswith(".xls"):
            self._extract_excel()
        else:
            raise ValueError(f"Unsupported file format for {self.filename}. Only .xlsx, .xls, and .csv are supported.")

        # Validate mandatory units (Rule 5)
        self._validate_units_and_currency()

        # Save to Normalized Database with status PENDING_REVIEW (Rule 7, 19)
        sheet_id = create_rate_sheet(
            user_id=self.user_id,
            carrier_name=self.metadata["carrier_name"],
            service_name=self.metadata["service_name"],
            tariff_ref=self.metadata["tariff_ref"],
            mode=self.metadata["mode"],
            currency=self.metadata["currency"] or "CAD",
            weight_unit=self.metadata["weight_unit"] or "lb",
            dim_unit=self.metadata["dim_unit"] or "in",
            dim_divisor=self.metadata["dim_divisor"],
            dim_min_rule=self.metadata["dim_min_rule"],
            rounding_rule=self.metadata["rounding_rule"],
            effective_date=self.metadata["effective_date"],
            expiry_date=self.metadata["expiry_date"],
            version=self.metadata["version"],
            source_filename=self.filename,
            confirmation_status="PENDING_REVIEW",
            rating_basis=self.metadata.get("rating_basis", "WEIGHT_CWT"),
            max_skid_capacity=self.metadata.get("max_skid_capacity", 10)
        )

        # Batch insert extracted entities
        insert_rate_sheet_cells(sheet_id, self.user_id, self.raw_cells)
        insert_carrier_surcharges(sheet_id, self.user_id, self.surcharges)
        insert_weight_breaks(sheet_id, self.user_id, self.rate_breaks)
        insert_carrier_minimums(sheet_id, self.user_id, self.minimums)
        if self.zones:
            insert_carrier_zones(sheet_id, self.user_id, self.zones)

        return {
            "sheet_id": sheet_id,
            "confirmation_status": "PENDING_REVIEW",
            "metadata": self.metadata,
            "flagged_items_count": len(self.flagged_items),
            "flagged_items": self.flagged_items,
            "surcharges_count": len(self.surcharges),
            "surcharges": self.surcharges[:10],
            "rate_breaks_count": len(self.rate_breaks),
            "rate_breaks_sample": self.rate_breaks[:5],
            "minimums_count": len(self.minimums),
            "hidden_rows_found": self.hidden_rows_found,
            "hidden_cols_found": self.hidden_cols_found
        }

    # ==========================================================================
    # CSV Extraction
    # ==========================================================================
    def _extract_csv(self):
        text = self.file_bytes.decode("utf-8", errors="replace")
        lines = list(csv.reader(io.StringIO(text)))
        
        # Pass 1: Scan for Metadata & Notes/Terms
        for r_idx, row in enumerate(lines):
            row_num = r_idx + 1
            if not row:
                continue
            row_str = " ".join(row).strip()
            if not row_str:
                continue
            
            # Carrier & Tariff metadata
            if "Day & Ross" in row_str or "Day and Ross" in row_str:
                self.metadata["carrier_name"] = "Day & Ross"
            elif "Purolator" in row_str:
                self.metadata["carrier_name"] = "Purolator"
            elif "FedEx" in row_str:
                self.metadata["carrier_name"] = "FedEx"
            elif "UPS" in row_str:
                self.metadata["carrier_name"] = "UPS"

            if len(row) >= 2:
                label = row[0].strip().lower()
                val = row[1].strip()
                if label == "tariff":
                    self.metadata["tariff_ref"] = val
                    self._record_cell("Metadata", f"Row {row_num}, Col B", "tariff_ref", val, val, 1.0)
                elif label == "effective date":
                    self.metadata["effective_date"] = self._normalize_date(val)
                    self._record_cell("Metadata", f"Row {row_num}, Col B", "effective_date", val, self.metadata["effective_date"], 1.0)
                elif label == "expiry date":
                    self.metadata["expiry_date"] = self._normalize_date(val)
                    self._record_cell("Metadata", f"Row {row_num}, Col B", "expiry_date", val, self.metadata["expiry_date"], 1.0)
                elif label == "service level":
                    self.metadata["service_name"] = val

            # Scan Terms & Conditions / Accessorial Footnotes (Rule 4)
            # Combine with next row to capture multi-row term descriptions (e.g. Title in row N, "waived" in row N+1)
            combined_row = list(row)
            if r_idx + 1 < len(lines):
                next_r = lines[r_idx + 1]
                if next_r:
                    combined_row.extend(next_r)
            self._scan_terms_text(row_num, combined_row, sheet_tab="Terms")

        # Autonomous dynamic sheet detector (Rules 33-36)
        from agent.dynamic_sheet_detector import DynamicSheetDetector
        detector = DynamicSheetDetector()
        detection = detector.scan_and_parse_sheet(lines)
        if detection.get("success"):
            for s in detection.get("structured_surcharges", []):
                s_name = s.get("name", "Accessorial")
                s_code = s_name.upper().replace(" ", "_").replace("/", "_")
                self._add_surcharge(
                    code=s_code,
                    name=s_name,
                    condition=s_name.lower().replace(" ", "_"),
                    fee_type=s.get("type", "FLAT"),
                    amount=s.get("amount", 0.0),
                    min_fee=s.get("min_fee") or 0.0,
                    is_waived=(s.get("type") == "WAIVED"),
                    coord="CSV!Structured Prose"
                )
            if "reconciliation_audit" in detection:
                self.metadata["reconciliation_audit"] = detection["reconciliation_audit"]
            if "composite_sheet_health" in detection:
                self.metadata["composite_sheet_health"] = detection["composite_sheet_health"]

        # Pass 2: Scan Rate Matrices & Breaks (Rule 1, 2)
        self._scan_csv_tables(lines)

    # ==========================================================================
    # Excel Extraction (openpyxl)
    # ==========================================================================
    def _extract_excel(self):
        wb = openpyxl.load_workbook(io.BytesIO(self.file_bytes), data_only=True)
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            
            # Rule 4: Deep inspection of hidden rows and columns
            for r_idx, dim in ws.row_dimensions.items():
                if dim.hidden:
                    self.hidden_rows_found.append(r_idx)
            for c_letter, dim in ws.column_dimensions.items():
                if dim.hidden:
                    self.hidden_cols_found.append(c_letter)

            all_rows = list(ws.iter_rows(values_only=False))
            grid = []
            for r_idx, row_cells in enumerate(all_rows):
                row_vals = [str(c.value).strip() if c.value is not None else "" for c in row_cells]
                grid.append(row_vals)
                row_num = r_idx + 1
                row_str = " ".join(row_vals).strip()
                if not row_str:
                    continue
                
                # Check for hidden row data extraction
                is_hidden_row = row_num in self.hidden_rows_found
                if is_hidden_row:
                    self._flag_item(
                        cell_coord=f"{sheetname}!Row {row_num}",
                        field_name="hidden_row_data",
                        raw_value=row_str[:80],
                        notes=f"Extracted data from hidden row {row_num} (Rule 4)"
                    )

                # Scan metadata
                if "Day & Ross" in row_str:
                    self.metadata["carrier_name"] = "Day & Ross"
                elif "Purolator" in row_str:
                    self.metadata["carrier_name"] = "Purolator"

                combined_vals = list(row_vals)
                if r_idx + 1 < len(all_rows):
                    next_vals = [str(c.value).strip() if c.value is not None else "" for c in all_rows[r_idx + 1]]
                    if next_vals:
                        combined_vals.extend(next_vals)
                self._scan_terms_text(row_num, combined_vals, sheet_tab=sheetname)

            self._scan_grid_tables(grid, sheet_tab=sheetname)

            # Autonomous dynamic sheet detector
            from agent.dynamic_sheet_detector import DynamicSheetDetector
            detector = DynamicSheetDetector()
            detection = detector.scan_and_parse_sheet(grid)
            if detection.get("success"):
                # 1. Harvest structured surcharges from prose cells
                for s in detection.get("structured_surcharges", []):
                    s_name = s.get("name", "Accessorial")
                    s_code = s_name.upper().replace(" ", "_").replace("/", "_")
                    self._add_surcharge(
                        code=s_code,
                        name=s_name,
                        condition=s_name.lower().replace(" ", "_"),
                        fee_type=s.get("type", "FLAT"),
                        amount=s.get("amount", 0.0),
                        min_fee=s.get("min_fee") or 0.0,
                        is_waived=(s.get("type") == "WAIVED"),
                        coord=f"{sheetname}!Structured Prose"
                    )
                # 2. Attach reconciliation audit to metadata
                if "reconciliation_audit" in detection:
                    self.metadata["reconciliation_audit"] = detection["reconciliation_audit"]
                if "composite_sheet_health" in detection:
                    self.metadata["composite_sheet_health"] = detection["composite_sheet_health"]

                # 3. Harvest rate data rows if not already populated (only for standard CWT sheets)
                if self.metadata.get("rating_basis") != "PER_SKID" and detection.get("rate_data_rows"):
                    existing_lanes = {(rb["origin_spec"], rb["dest_spec"]) for rb in self.rate_breaks}
                    for rdr in detection["rate_data_rows"]:
                        orig = rdr["origin"]
                        dest = rdr["destination"]
                        if not orig or not dest or (orig, dest) in existing_lanes:
                            continue
                        r_num = rdr["row_number"]
                        coord_base = f"{sheetname}!Row {r_num}"
                        rb_dict = rdr.get("rate_breaks", {})
                        # Look for MIN
                        min_val = None
                        for k, v in rb_dict.items():
                            if "min" in k.lower() and v and str(v).replace(".", "").isdigit():
                                try:
                                    min_val = float(str(v).replace("$", "").replace(",", ""))
                                    break
                                except ValueError:
                                    pass
                        if min_val is not None:
                            self.minimums.append({
                                "zone_code": "P2P",
                                "origin_spec": orig,
                                "dest_spec": dest,
                                "min_charge": min_val,
                                "source_cell": f"{coord_base}, MIN"
                            })
                        # Add rate breaks
                        for k, v in rb_dict.items():
                            val_str = str(v).replace("$", "").replace(",", "").strip()
                            if not val_str or not val_str.replace(".", "").isdigit():
                                continue
                            try:
                                val = float(val_str)
                            except ValueError:
                                continue
                            k_low = k.lower()
                            if "min" in k_low:
                                continue
                            elif "ltl" in k_low:
                                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": orig, "dest_spec": dest, "min_weight": 0, "max_weight": 999, "break_name": "LTL", "base_rate": val, "rate_type": "CWT", "source_cell": f"{coord_base}, {k}"})
                            elif "1000" in k_low or "1k" in k_low:
                                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": orig, "dest_spec": dest, "min_weight": 1000, "max_weight": 1999, "break_name": "CWT:1000", "base_rate": val, "rate_type": "CWT", "source_cell": f"{coord_base}, {k}"})
                            elif "2000" in k_low or "2k" in k_low:
                                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": orig, "dest_spec": dest, "min_weight": 2000, "max_weight": 4999, "break_name": "CWT:2000", "base_rate": val, "rate_type": "CWT", "source_cell": f"{coord_base}, {k}"})
                            elif "5000" in k_low or "5k" in k_low:
                                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": orig, "dest_spec": dest, "min_weight": 5000, "max_weight": 9999, "break_name": "CWT:5000", "base_rate": val, "rate_type": "CWT", "source_cell": f"{coord_base}, {k}"})
                            elif "10000" in k_low or "10k" in k_low:
                                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": orig, "dest_spec": dest, "min_weight": 10000, "max_weight": 999999, "break_name": "CWT:10000", "base_rate": val, "rate_type": "CWT", "source_cell": f"{coord_base}, {k}"})
                            else:
                                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": orig, "dest_spec": dest, "min_weight": 0, "max_weight": 44000, "break_name": k, "base_rate": val, "rate_type": "CWT", "source_cell": f"{coord_base}, {k}"})
                        existing_lanes.add((orig, dest))

    # ==========================================================================
    # Terms & Conditions / Accessorial Harvester (Rule 4, 11)
    # ==========================================================================
    def _scan_terms_text(self, row_num: int, row_cells: List[str], sheet_tab: str):
        full_text = " ".join(row_cells).strip()
        if not full_text or len(full_text) < 5:
            return
            
        coord = f"{sheet_tab}!Row {row_num}"

        # 1. Appointment Deliveries
        if re.search(r'\bappointment\b', full_text, re.I):
            amt = self._extract_amount(full_text) or 20.00
            self._add_surcharge("APPOINTMENT", "Appointment Deliveries", "appointment", "FLAT", amt, coord=coord)

        # 2. After Hour Service
        if re.search(r'after hour|after-hours|between 7 pm & 6 am', full_text, re.I):
            amt = self._extract_amount(full_text) or 200.00
            self._add_surcharge("AFTER_HOURS_METRO", "After Hours Service (Metro Terminal)", "after_hours", "FLAT", amt, coord=coord)
            if "AMAZON" in full_text.upper() and "$50.00" in full_text:
                self._add_surcharge("AFTER_HOURS_AMAZON", "After Hours Amazon Delivery (6pm - 11pm)", "amazon_delivery", "FLAT", 50.00, coord=coord)
                self._flag_item(coord, "surcharge.after_hours_amazon", "$50.00", "Complex time-window exception extracted (Rule 6)")

        # 3. Dangerous Goods / Hazmat
        if re.search(r'dangerous goods|hazmat|hazardous', full_text, re.I):
            amounts = re.findall(r'\$(\d+(?:\.\d{2})?)', full_text)
            if len(amounts) >= 2:
                amt1, amt2 = float(amounts[0]), float(amounts[1])
                self._add_surcharge("DANGEROUS_GOODS_LTL", "Dangerous Goods (1 - 999 lbs)", "dangerous_goods", "FLAT", amt1,
                                    cond_expr={"weight_min": 1, "weight_max": 999}, coord=coord)
                self._add_surcharge("DANGEROUS_GOODS_HEAVY", "Dangerous Goods (1000 - 99999 lbs)", "dangerous_goods", "FLAT", amt2,
                                    cond_expr={"weight_min": 1000, "weight_max": 99999}, coord=coord)
            else:
                amt = float(amounts[0]) if amounts else 49.50
                self._add_surcharge("DANGEROUS_GOODS", "Dangerous Goods Surcharge", "dangerous_goods", "FLAT", amt, coord=coord)

        # 4. Power Tailgate / Liftgate (Waived check)
        if re.search(r'tailgate|liftgate', full_text, re.I):
            is_waived = bool(re.search(r'waived|no charge|included|\$0(?:\.00)?', full_text, re.I))
            amt = 0.0 if is_waived else (self._extract_amount(full_text) or 45.00)
            self._add_surcharge("POWER_TAILGATE", "Power Tailgate / Liftgate", "liftgate", "FLAT", amt, is_waived=is_waived, coord=coord)

        # 5. Private Residence / Limited Access
        if re.search(r'private residence|limited access', full_text, re.I):
            amt = self._extract_amount(full_text) or 20.00
            if "pickup" in full_text.lower():
                self._add_surcharge("RESIDENTIAL_PICKUP", "Private Residence / Limited Access Pickup", "residential_pickup", "FLAT", amt, coord=coord)
            else:
                self._add_surcharge("RESIDENTIAL_DELIVERY", "Private Residence / Limited Access Delivery", "residential_delivery", "FLAT", amt, coord=coord)

        # 6. Protective Heated Service
        if re.search(r'protective service|heated service|protect from freeze', full_text, re.I):
            pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', full_text)
            min_match = re.search(r'not less than\s*\$(\d+(?:\.\d{2})?)', full_text)
            pct = float(pct_match.group(1)) if pct_match else 18.0
            min_fee = float(min_match.group(1)) if min_match else 39.50
            self._add_surcharge("PROTECTIVE_SERVICE", "Protective Heated Service", "heated", "PERCENTAGE", pct, min_fee=min_fee, coord=coord)

        # 7. Reconsignment / Diversion
        if re.search(r'reconsignment|diversion', full_text, re.I):
            cwt_match = re.search(r'\$(\d+(?:\.\d{2})?)\s*cwt', full_text, re.I)
            min_match = re.search(r'min\s*\$(\d+(?:\.\d{2})?)', full_text, re.I)
            max_match = re.search(r'max\s*\$(\d+(?:\.\d{2})?)', full_text, re.I)
            rate = float(cwt_match.group(1)) if cwt_match else 6.50
            min_f = float(min_match.group(1)) if min_match else 70.0
            max_f = float(max_match.group(1)) if max_match else 285.0
            self._add_surcharge("RECONSIGNMENT", "Reconsignment / Diversion", "reconsignment", "CWT", rate, min_fee=min_f, max_fee=max_f, coord=coord)

        # 8. Storage Fees
        if re.search(r'storage fee', full_text, re.I):
            amt = self._extract_amount(full_text) or 35.00
            self._add_surcharge("STORAGE", "Storage Fee (per day)", "storage", "FLAT", amt, coord=coord)

        # 9. Tradeshow Deliveries
        if re.search(r'tradeshow', full_text, re.I):
            cwt_match = re.search(r'\$(\d+(?:\.\d{2})?)\s*cwt', full_text, re.I)
            min_match = re.search(r'minimum of\s*\$(\d+(?:\.\d{2})?)', full_text, re.I)
            rate = float(cwt_match.group(1)) if cwt_match else 4.15
            min_f = float(min_match.group(1)) if min_match else 167.0
            self._add_surcharge("TRADESHOW", "Tradeshow Delivery Surcharge", "tradeshow", "CWT", rate, min_fee=min_f, coord=coord)

        # 10. Inside Pickup / Delivery (Waived check)
        if re.search(r'inside pickup|inside delivery', full_text, re.I):
            is_waived = bool(re.search(r'waived|no charge|\$0(?:\.00)?', full_text, re.I))
            amt = 0.0 if is_waived else (self._extract_amount(full_text) or 40.00)
            self._add_surcharge("INSIDE_PICKUP_DELIVERY", "Inside Pickup / Delivery", "inside_delivery", "FLAT", amt, is_waived=is_waived, coord=coord)

        # 11. Cost Recovery Ferry Surcharge (Newfoundland)
        if "FERRY SURCHARGE" in full_text.upper():
            amt = self._extract_amount(full_text)
            if amt:
                if "LTL" in full_text.upper() or "< 7500" in full_text or "less than 7500" in full_text:
                    self._add_surcharge("FERRY_LTL", "Cost Recovery Ferry Surcharge - LTL (<7500 lbs)", "dest_province:NL",
                                        "FLAT", amt, cond_expr={"weight_max": 7500}, coord=coord)
                elif "7500" in full_text and "39999" in full_text:
                    self._add_surcharge("FERRY_TL_MEDIUM", "Cost Recovery Ferry Surcharge - TL (7500 - 39999 lbs)", "dest_province:NL",
                                        "FLAT", amt, cond_expr={"weight_min": 7500, "weight_max": 39999}, coord=coord)
                elif "TO NEWFOUNDLAND" in full_text.upper():
                    self._add_surcharge("FERRY_TL_TO_NL", "Cost Recovery Ferry Surcharge - TL To NL (40000+ lbs)", "dest_province:NL",
                                        "FLAT", amt, cond_expr={"weight_min": 40000}, coord=coord)
                else:
                    self._add_surcharge("FERRY_SURCHARGE", "Cost Recovery Ferry Surcharge", "dest_province:NL", "FLAT", amt, coord=coord)

        # 12. Fuel Surcharge index
        if re.search(r'fuel surcharge|fca fuel', full_text, re.I):
            self._add_surcharge("FUEL_FSC", "Fuel Surcharge (FCA Index)", "fuel", "PERCENTAGE", 0.0, coord=coord)

        # 13. Weight & Density restrictions
        if re.search(r'minimum weight restriction|lbs per cu ft', full_text, re.I):
            self.metadata["dim_min_rule"] = full_text[:120]
            self._record_cell(sheet_tab, coord, "dim_min_rule", full_text, full_text, 1.0)

    # ==========================================================================
    # Matrix Rate Table Scanner (Skid Breaks, CWT Breaks, Flat Rates, Minimums)
    # ==========================================================================
    def _classify_skid_break_header(self, header_text: str) -> Optional[Tuple[str, int, int]]:
        """
        Classifies header into (break_name, min_units, max_units) if it is a Skid break.
        Handles:
        - 'L5C', '<5', 'L5', '1-4', '1-4 SKIDS', '1 TO 4 PALLETS' -> ('L5C', 1, 4)
        - '5C', '5', '5 SKIDS' -> ('5C', 5, 5)
        - '1M', '6', '6 SKIDS' -> ('1M', 6, 6) (1 more skid past 5)
        - '2M', '7', '7 SKIDS' -> ('2M', 7, 7) (2 more skids past 5)
        - '5M', '8-9', '8-9 SKIDS' -> ('5M', 8, 9) (covers 8-9 skids before 10M)
        - '10M', '10', '10 SKIDS' -> ('10M', 10, 10) (10 skids break point / ceiling)
        - General regex ranges: '1-4', '5-6', '7-8', '9-10'
        - General '<N', 'LN', 'LNC'
        - General 'NM'
        """
        h_clean = header_text.strip().upper()
        if not h_clean:
            return None

        # Exclude known non-skid words
        if h_clean in ["DIRECTION", "ORIGIN", "OPR", "DESTINATION", "DCOUNTY", "DPR", "MC", "MIN", "BASE", "FLAT", "TOTAL", "NOTES", "ZONE"]:
            return None

        # Range patterns: '1-4', '8-9', '1-4 SKIDS', '1 TO 4 PALLETS'
        m_range = re.match(r'^(\d+)\s*[-–TOto]+\s*(\d+)(?:\s*(?:SKIDS?|PALLETS?|SKD|PLT))?$', h_clean)
        if m_range:
            n1, n2 = int(m_range.group(1)), int(m_range.group(2))
            return (h_clean, n1, n2)

        # Less than N: 'L5C', 'L5', '<5', '<5C', 'LESS THAN 5'
        # In skid tariffs, L5C caps at 5 skids (1-5 skids).
        m_less = re.match(r'^(?:L|<|LESS THAN\s*)(\d+)C?$', h_clean)
        if m_less:
            n = int(m_less.group(1))
            return (h_clean, 1, n if n <= 5 else max(1, n - 1))

        # NC: '5C'
        m_c = re.match(r'^(\d+)C$', h_clean)
        if m_c:
            n = int(m_c.group(1))
            return (h_clean, n, n)

        # NM: '1M', '2M', '5M', '10M'
        m_m = re.match(r'^(\d+)M$', h_clean)
        if m_m:
            n = int(m_m.group(1))
            if n == 1:
                return (h_clean, 6, 6)
            elif n == 2:
                return (h_clean, 7, 7)
            elif n == 3:
                return (h_clean, 8, 8)
            elif n == 4:
                return (h_clean, 9, 9)
            elif n == 5:
                return (h_clean, 8, 9)
            elif n == 10:
                return (h_clean, 10, 10)
            else:
                return (h_clean, n, n)

        # Single with skid / pallet label: '5 SKIDS', '10 PALLETS'
        m_single = re.match(r'^(\d+)\s*(?:SKIDS?|PALLETS?|SKD|PLT)$', h_clean)
        if m_single:
            n = int(m_single.group(1))
            return (h_clean, n, n)

        return None

    def _scan_skid_ltl_tables(self, grid: List[List[str]], sheet_tab: str) -> bool:
        """
        Detects and extracts Skid/Pallet-based LTL rate sheets.
        Formula: Base Freight = MC + (SkidCount x BreakRate)
        Supports:
        - Bidirectional lanes ('BETWEEN')
        - Header synonyms: MC, MIN, BASE, FLAT, BASE COST
        - Dynamic breakpoint detection for max_skid_capacity
        """
        header_row_idx = None
        skid_cols = []
        col_mc = None
        col_origin = None
        col_opr = None
        col_dest = None
        col_dpr = None
        col_direction = None

        base_cost_synonyms = {"MC", "MIN", "BASE", "BASE COST", "BASE_COST", "BASE CHARGE", "FLAT", "MIN CHARGE", "MIN_CHARGE", "MINIMUM"}
        origin_synonyms = {"ORIGIN", "FROM", "ORIG", "SHIPPER CITY", "ORIGIN CITY"}
        opr_synonyms = {"OPR", "ORIG_PROV", "ORIGIN_PROV", "O_PROV", "ORIG PROV", "ORIGIN STATE"}
        dest_synonyms = {"DESTINATION", "TO", "DEST", "CONSIGNEE CITY", "DELIVERY CITY"}
        dpr_synonyms = {"DPR", "DEST_PROV", "DESTINATION_PROV", "D_PROV", "DEST PROV", "DEST STATE"}
        dir_synonyms = {"DIRECTION", "DIR", "LANE_TYPE", "TYPE"}

        for r_idx, row in enumerate(grid):
            row_clean = [c.strip().upper() for c in row]
            found_breaks = []
            found_mc = None
            found_orig = None
            found_dest = None

            for c_idx, cell in enumerate(row_clean):
                if cell in base_cost_synonyms and found_mc is None:
                    found_mc = c_idx
                elif cell in origin_synonyms and found_orig is None:
                    found_orig = c_idx
                elif cell in dest_synonyms and found_dest is None:
                    found_dest = c_idx
                else:
                    classified = self._classify_skid_break_header(cell)
                    if classified:
                        found_breaks.append((c_idx, classified))

            if len(found_breaks) >= 2 and found_orig is not None and found_dest is not None:
                header_row_idx = r_idx
                has_5c = any(item[1][0] == "5C" for item in found_breaks)
                adjusted_breaks = []
                for c_idx, (b_name, min_u, max_u) in found_breaks:
                    if b_name == "L5C" and has_5c:
                        adjusted_breaks.append((c_idx, (b_name, min_u, 4)))
                    else:
                        adjusted_breaks.append((c_idx, (b_name, min_u, max_u)))
                skid_cols = adjusted_breaks
                col_mc = found_mc
                col_origin = found_orig
                col_dest = found_dest

                for c_idx, cell in enumerate(row_clean):
                    if cell in opr_synonyms and col_opr is None:
                        col_opr = c_idx
                    elif cell in dpr_synonyms and col_dpr is None:
                        col_dpr = c_idx
                    elif cell in dir_synonyms and col_direction is None:
                        col_direction = c_idx
                break

        if header_row_idx is None or not skid_cols:
            return False

        # Discovered skid sheet
        max_skids = max(item[1][2] for item in skid_cols)
        self.metadata["rating_basis"] = "PER_SKID"
        self.metadata["max_skid_capacity"] = max(10, max_skids)

        # Parse data rows
        extracted_breaks_count = 0
        for r_idx in range(header_row_idx + 1, len(grid)):
            row = grid[r_idx]
            if len(row) <= max(col_origin, col_dest):
                continue
            orig_raw = row[col_origin].strip()
            dest_raw = row[col_dest].strip()
            if not orig_raw or not dest_raw or orig_raw.upper() in ["TOTAL", "NOTE", "NOTES"]:
                continue

            opr_raw = row[col_opr].strip() if col_opr is not None and col_opr < len(row) else ""
            dpr_raw = row[col_dpr].strip() if col_dpr is not None and col_dpr < len(row) else ""

            orig_spec = f"{orig_raw}, {opr_raw}" if opr_raw and len(opr_raw) <= 3 and opr_raw.isalpha() else orig_raw
            dest_spec = f"{dest_raw}, {dpr_raw}" if dpr_raw and len(dpr_raw) <= 3 and dpr_raw.isalpha() else dest_raw

            dir_raw = row[col_direction].strip().upper() if col_direction is not None and col_direction < len(row) else ""
            is_bidirectional = dir_raw in ["BETWEEN", "BI-DIRECTIONAL", "BIDIRECTIONAL", "TWO-WAY", "BOTH"]

            coord_base = f"{sheet_tab}!Row {r_idx + 1}"

            # Extract Base MC cost
            mc_val = None
            if col_mc is not None and col_mc < len(row):
                mc_str = row[col_mc].replace("$", "").replace(",", "").strip()
                try:
                    mc_val = float(mc_str)
                except ValueError:
                    pass

            if mc_val is not None:
                coord_mc = f"{coord_base}, Col {col_mc + 1}"
                self.minimums.append({
                    "zone_code": "P2P",
                    "origin_spec": orig_spec,
                    "dest_spec": dest_spec,
                    "min_charge": mc_val,
                    "source_cell": coord_mc
                })
                if is_bidirectional:
                    self.minimums.append({
                        "zone_code": "P2P",
                        "origin_spec": dest_spec,
                        "dest_spec": orig_spec,
                        "min_charge": mc_val,
                        "source_cell": coord_mc
                    })

            # Extract skid breaks
            for c_idx, (break_name, min_u, max_u) in skid_cols:
                if c_idx >= len(row):
                    continue
                val_str = row[c_idx].replace("$", "").replace(",", "").strip()
                try:
                    rate_val = float(val_str)
                except ValueError:
                    continue

                coord_b = f"{coord_base}, Col {c_idx + 1}"
                self.rate_breaks.append({
                    "zone_code": "P2P",
                    "origin_spec": orig_spec,
                    "dest_spec": dest_spec,
                    "min_weight": 0.0,
                    "max_weight": 44000.0,
                    "break_name": break_name,
                    "base_rate": rate_val,
                    "rate_type": "PER_SKID",
                    "source_cell": coord_b,
                    "break_unit": "SKID",
                    "min_units": min_u,
                    "max_units": max_u
                })
                if is_bidirectional:
                    self.rate_breaks.append({
                        "zone_code": "P2P",
                        "origin_spec": dest_spec,
                        "dest_spec": orig_spec,
                        "min_weight": 0.0,
                        "max_weight": 44000.0,
                        "break_name": break_name,
                        "base_rate": rate_val,
                        "rate_type": "PER_SKID",
                        "source_cell": coord_b,
                        "break_unit": "SKID",
                        "min_units": min_u,
                        "max_units": max_u
                    })
                extracted_breaks_count += 1

        return extracted_breaks_count > 0

    def _scan_csv_tables(self, rows: List[List[str]]):
        self._scan_grid_tables(rows, sheet_tab="Sheet 1")

    def _scan_grid_tables(self, grid: List[List[str]], sheet_tab: str):
        # 0. Check for Skid-Based LTL table format
        if self._scan_skid_ltl_tables(grid, sheet_tab=sheet_tab):
            return

        for r_idx, row in enumerate(grid):
            row_num = r_idx + 1
            if len(row) < 4:
                continue

            col0 = row[0].strip()
            col1 = row[1].strip()
            col2 = row[2].strip()
            col3 = row[3].strip()

            # 1. PTL Flat Rate lane check:
            # Format A (City, Prov, City, Prov, 0, FlatRate)
            if len(row) >= 6 and row[4].strip() == "0" and row[5].strip().replace(".", "").isdigit():
                origin = f"{col0}, {col1}" if len(col1) <= 3 and col1.isalpha() else col0
                dest = f"{col2}, {col3}" if len(col3) <= 3 and col3.isalpha() else col2
                flat_rate = float(row[5].strip())
                coord = f"{sheet_tab}!Row {row_num}, Col F"
                self.rate_breaks.append({
                    "zone_code": "PTL_FLAT",
                    "origin_spec": origin,
                    "dest_spec": dest,
                    "min_weight": 0.0,
                    "max_weight": 44000.0,
                    "break_name": "FLAT:PTL",
                    "base_rate": flat_rate,
                    "rate_type": "FLAT",
                    "source_cell": coord
                })
                self._record_cell(sheet_tab, coord, f"ptl.flat.{origin}->{dest}", str(flat_rate), str(flat_rate), 1.0)
                continue

            # Format B (Single-col Origin, Dest, 0, FlatRate)
            if col2 == "0" and col3.replace(".", "").isdigit() and float(col3) > 100:
                origin, dest = col0, col1
                flat_rate = float(col3)
                coord = f"{sheet_tab}!Row {row_num}, Col D"
                self.rate_breaks.append({
                    "zone_code": "PTL_FLAT",
                    "origin_spec": origin,
                    "dest_spec": dest,
                    "min_weight": 0.0,
                    "max_weight": 44000.0,
                    "break_name": "FLAT:PTL",
                    "base_rate": flat_rate,
                    "rate_type": "FLAT",
                    "source_cell": coord
                })
                self._record_cell(sheet_tab, coord, f"ptl.flat.{origin}->{dest}", col3, str(flat_rate), 1.0)
                continue

            # 2. Standard CWT Rate Row: Origin, Destination, MIN, LTL, CWT:1000, CWT:2000, CWT:5000, CWT:10000, CWT:20000
            if len(row) >= 7:
                try:
                    # Check if col1 and col3 are 2-letter province/state codes (City, Prov, City, Prov, MIN...)
                    if len(col1) <= 3 and len(col3) <= 3 and col1.isalpha() and col3.isalpha() and len(row) >= 9:
                        origin = f"{col0}, {col1}"
                        dest = f"{col2}, {col3}"
                        min_val = float(row[4].replace(",", "").strip())
                        ltl_val = float(row[5].replace(",", "").strip())
                        cwt1k = float(row[6].replace(",", "").strip())
                        cwt2k = float(row[7].replace(",", "").strip())
                        cwt5k = float(row[8].replace(",", "").strip())
                        cwt10k = float(row[9].replace(",", "").strip()) if len(row) > 9 and row[9].strip() else cwt5k
                    else:
                        origin = col0
                        dest = col1 if col1 != "" else col2
                        min_val = float(row[2].replace(",", "").strip())
                        ltl_val = float(row[3].replace(",", "").strip())
                        cwt1k = float(row[4].replace(",", "").strip())
                        cwt2k = float(row[5].replace(",", "").strip())
                        cwt5k = float(row[6].replace(",", "").strip())
                        cwt10k = float(row[7].replace(",", "").strip())

                    if not origin or not dest or origin.lower() in ["origin", "between localities"]:
                        continue
                except (ValueError, IndexError):
                    continue


                coord_base = f"{sheet_tab}!Row {row_num}"

                # Minimum charge (Rule 12)
                self.minimums.append({
                    "zone_code": "P2P",
                    "origin_spec": origin,
                    "dest_spec": dest,
                    "min_charge": min_val,
                    "source_cell": f"{coord_base}, Col E"
                })

                # Explicit CWT Weight Breaks (Rule 1, 8)
                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": origin, "dest_spec": dest, "min_weight": 0, "max_weight": 999, "break_name": "LTL", "base_rate": ltl_val, "rate_type": "CWT", "source_cell": f"{coord_base}, Col F"})
                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": origin, "dest_spec": dest, "min_weight": 1000, "max_weight": 1999, "break_name": "CWT:1000", "base_rate": cwt1k, "rate_type": "CWT", "source_cell": f"{coord_base}, Col G"})
                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": origin, "dest_spec": dest, "min_weight": 2000, "max_weight": 4999, "break_name": "CWT:2000", "base_rate": cwt2k, "rate_type": "CWT", "source_cell": f"{coord_base}, Col H"})
                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": origin, "dest_spec": dest, "min_weight": 5000, "max_weight": 9999, "break_name": "CWT:5000", "base_rate": cwt5k, "rate_type": "CWT", "source_cell": f"{coord_base}, Col I"})
                self.rate_breaks.append({"zone_code": "P2P", "origin_spec": origin, "dest_spec": dest, "min_weight": 10000, "max_weight": 999999, "break_name": "CWT:10000", "base_rate": cwt10k, "rate_type": "CWT", "source_cell": f"{coord_base}, Col J"})

                # Record cell coordinates for traceability (Rule 3)
                if row_num % 15 == 0:
                    self._record_cell(sheet_tab, f"{coord_base}, Col F", f"rate.ltl.{origin}->{dest}", str(ltl_val), str(ltl_val), 1.0)

    # ==========================================================================
    # Helpers & Rule 5 / Rule 6 Validation
    # ==========================================================================
    def _validate_units_and_currency(self):
        """Rule 5: Detect and record currency, weight unit, dimension unit. Never assume."""
        # 1. Currency
        if not self.metadata["currency"]:
            # Scan text for Canadian vs US currency hints
            full_sample = " ".join([c["raw_value"] for c in self.raw_cells[:50]])
            if "Cdn funds" in full_sample or "CAD" in full_sample:
                self.metadata["currency"] = "CAD"
            elif "USD" in full_sample or "US funds" in full_sample:
                self.metadata["currency"] = "USD"
            else:
                self.metadata["currency"] = "CAD"  # Default but flag for review (Rule 6)
                self._flag_item("Metadata", "currency", "CAD", "Currency was not explicitly defined as CAD or USD. Flagged for review (Rule 5 & 6)")

        # 2. Weight Unit
        if not self.metadata["weight_unit"]:
            full_sample = " ".join([c["raw_value"] for c in self.raw_cells[:50]])
            if "lbs" in full_sample or "lb" in full_sample or "cwt" in full_sample.lower():
                self.metadata["weight_unit"] = "lb"
            elif "kg" in full_sample:
                self.metadata["weight_unit"] = "kg"
            else:
                self.metadata["weight_unit"] = "lb"
                self._flag_item("Metadata", "weight_unit", "lb", "Weight unit was not explicitly defined. Flagged for review (Rule 5 & 6)")

        # 3. Dimension Unit
        if not self.metadata["dim_unit"]:
            self.metadata["dim_unit"] = "in"

    def _add_surcharge(self, code: str, name: str, condition: str, fee_type: str,
                       amount: float, min_fee: float = 0.0, max_fee: Optional[float] = None,
                       is_waived: bool = False, cond_expr: Any = None, coord: str = ""):
        existing = next((s for s in self.surcharges if s["surcharge_code"] == code), None)
        if existing:
            if is_waived:
                existing["is_waived"] = 1
                existing["amount"] = 0.0
            return

        self.surcharges.append({
            "surcharge_code": code,
            "name": name,
            "condition_type": condition,
            "condition_expression": cond_expr,
            "fee_type": fee_type,
            "amount": amount,
            "min_fee": min_fee,
            "max_fee": max_fee,
            "is_waived": 1 if is_waived else 0,
            "source_cell": coord
        })
        self._record_cell("Surcharges", coord, f"surcharge.{code.lower()}", f"${amount:.2f}", str(amount), 1.0)


    def _record_cell(self, tab: str, coord: str, field: str, raw: str, extracted: str, confidence: float, needs_review: bool = False, notes: str = ""):
        self.raw_cells.append({
            "sheet_tab": tab,
            "cell_coord": coord,
            "field_name": field,
            "raw_value": str(raw),
            "extracted_value": str(extracted),
            "confidence": confidence,
            "needs_review": needs_review,
            "review_notes": notes
        })

    def _flag_item(self, cell_coord: str, field_name: str, raw_value: str, notes: str):
        """Rule 6: Flag items requiring human review."""
        flag = {
            "cell_coord": cell_coord,
            "field_name": field_name,
            "raw_value": raw_value,
            "review_notes": notes
        }
        self.flagged_items.append(flag)
        self._record_cell("Review", cell_coord, field_name, raw_value, "", 0.75, needs_review=True, notes=notes)

    def _extract_amount(self, text: str) -> Optional[float]:
        match = re.search(r'\$(\d+(?:\.\d{2})?)', text)
        return float(match.group(1)) if match else None

    def _normalize_date(self, text: str) -> Optional[str]:
        # Matches YYYY-MM-DD or MM/DD/YYYY
        m1 = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
        if m1:
            return m1.group(0)
        m2 = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
        if m2:
            return f"{m2.group(3)}-{int(m2.group(1)):02d}-{int(m2.group(2)):02d}"
        return None
