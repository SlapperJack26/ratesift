"""
RateSift Autonomous Dynamic Sheet Detector & Multi-Segment Parsing Engine
Detects rate table headers, classifies disclaimers & company metadata without hardcoded row numbers.
Enforces Rule 1 (Explicit extraction), Rule 4 (Footnote resolution), Rule 6 (Needs review),
Rule 7 (Human confirmation gate), Rule 33 (7-category classification), Rule 34 (Letterhead exclusion),
Rule 35 (Disclaimer quarantine), and Zero-Data-Loss Protection with Total Row Reconciliation.
"""
import re
from typing import List, Dict, Any, Optional, Tuple

ORIGIN_TOKENS = {
    "origin", "from", "orig", "city", "postal", "o-zip", "fsa", "between localities",
    "shipper", "ship from", "pickup", "pickup location", "pickup city", "shipper location",
    "shipper city"
}
DEST_TOKENS = {
    "destination", "dest", "to", "d-zip", "consignee", "delivery", "ship to",
    "delivery location", "delivery city", "consignee location", "consignee city"
}
RATE_TOKENS = {
    "min", "ltl", "cwt", "cwt:1000", "cwt:2000", "cwt:5000", "cwt:10000", "cwt:20000",
    "cwt:500", "flat", "rate", "cwt:ptl", "flat:ptl", "base cost", "declared value"
}
CARGO_TOKENS = {
    "weight", "wt", "lbs", "kg", "dims", "dimensions", "length", "width", "height",
    "cargo", "gross weight", "total weight", "chargeable wt", "billable wt"
}

# Word Doc Training Classification Signals & Patterns
PHONE_PATTERN = re.compile(r'(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})')
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
POSTAL_CODE_PATTERN = re.compile(r'\b[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d\b|\b\d{5}(-\d{4})?\b')
PAGE_NOISE_PATTERN = re.compile(r'\bpage\s+\d+(\s+of\s+\d+)?\b', re.IGNORECASE)
COMPANY_ENTITY_PATTERN = re.compile(r'\b(inc\.|incorporated|ltd\.|limited|corp\.|corporation|llc|co\.)\b', re.IGNORECASE)

LEGAL_KEYWORDS = [
    "subject to change", "terms and conditions", "e&oe", "e. & o.e.",
    "confidential", "proprietary", "null & void", "limitations of liability",
    "reissues thereof", "valid for 30 days", "contras on account", "subject to all rules",
    "payment terms", "without notice", "governed by the laws"
]

COMPANY_INFO_KEYS = [
    "customer", "address", "telephone", "phone", "fax", "email", "contact", "tariff", "revision",
    "d & r acct #", "account #", "effective date", "expiry date", "issue date", "pricing official", "commodity", "currency"
]

CANADIAN_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY"
}
ALL_PROV_STATE_CODES = CANADIAN_PROVINCES | US_STATES

def clean_cell(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()

def is_numeric(val: str) -> bool:
    try:
        float(val.replace("$", "").replace(",", "").strip())
        return True
    except (ValueError, AttributeError):
        return False

def is_rate_numeric(val: str, allow_integer: bool = False) -> bool:
    """
    Evaluates if a string value matches real freight rate formatting.
    Rates in tariffs consistently feature decimals (e.g. 96.89, 34.51, 0.00).
    Excludes large bare integers (e.g. account # 158437, revision 336).
    """
    clean = val.replace("$", "").replace(",", "").strip()
    if not clean:
        return False
    try:
        f = float(clean)
        if "." in clean:
            return True
        if val.startswith("$"):
            return True
        if allow_integer or f == 0:
            return True
        if clean.isdigit() and len(clean) >= 3:
            return False
        return True
    except ValueError:
        return False

def is_prose_cell(text: str) -> bool:
    """Detects prose sentences (multiple words, punctuation, sentence casing) vs table cells."""
    words = text.strip().split()
    if len(words) >= 4 and any(punct in text for punct in [".", ":", ";", ","]):
        return True
    return False

def extract_structured_surcharge(text: str) -> Optional[Dict[str, Any]]:
    """
    Extracts structured accessorial/surcharge records from prose cells.
    Hard invariant: these values are never written into the rate matrix grid.
    """
    t_clean = text.strip()
    t_lower = t_clean.lower()

    # 1. Percentage with minimum fee (e.g. Protective service 18.00% not less than $39.50)
    pct_min_match = re.search(r'([0-9.]+)\s*%\s*(?:of the freight charge)?.*?(?:not less than|min|minimum)\s*\$?([0-9.]+)', t_lower)
    if pct_min_match:
        pct = float(pct_min_match.group(1).rstrip('.'))
        min_fee = float(pct_min_match.group(2).rstrip('.'))
        name = "Protective Service / Heated" if "protective" in t_lower or "heat" in t_lower else "Percentage Surcharge"
        return {"name": name, "type": "PCT", "amount": pct, "min_fee": min_fee, "raw_text": t_clean}

    # 2. Flat dollar fee (e.g. charge of $20.00 or $50 flat fee)
    flat_match = re.search(r'(?:charge of|fee of|fee|rate of|\$)\s*\$?([0-9.]+)', t_lower)
    if flat_match and "$" in t_clean:
        amt = float(flat_match.group(1).rstrip('.'))
        name = "Delivery Appointment" if "appointment" in t_lower else ("Tailgate Service" if "tailgate" in t_lower or "liftgate" in t_lower else "Accessorial Fee")
        return {"name": name, "type": "FLAT", "amount": amt, "min_fee": None, "raw_text": t_clean}

    # 3. Waived fee
    if "waived" in t_lower:
        name = "Power Tailgate" if "tailgate" in t_lower or "liftgate" in t_lower else "Waived Accessorial"
        return {"name": name, "type": "WAIVED", "amount": 0.0, "min_fee": None, "raw_text": t_clean}

    return None


class DynamicSheetDetector:
    """
    Autonomous multi-segment detector that scans any spreadsheet layout without hardcoded line numbers.
    Features:
    - Currency and continuous row density weighted header scoring
    - Two-pass global preamble and cell classification
    - Structured prose surcharge extraction (hard invariant: prose never in rate grid)
    - Authoritative column indexing and 2-letter province dictionary pairing
    - Multi-segment scanning ("Between Localities") and zero-data-loss row reconciliation
    - Rich-preview Confusion Gate triggered on scores within 10%
    """
    def __init__(self, confidence_threshold: float = 0.50):
        self.confidence_threshold = confidence_threshold

    def score_header_candidate(self, row_idx: int, row_cells: List[str], all_rows: List[List[str]]) -> Dict[str, Any]:
        """
        Scores how likely a row is to be the starting table header for rate data.
        Enforces Issue 1 fix:
        1. Hard currency requirement: Must have currency formatted or explicit rate columns.
        2. Continuous row density weighting: Counts subsequent contiguous rate data rows.
        """
        row_str = " ".join([clean_cell(c).lower() for c in row_cells if clean_cell(c)])
        if not row_str:
            return {"score": 0.0, "reasons": ["Empty row"], "continuous_rows": 0, "data_preview": []}

        score = 0.0
        reasons = []

        tokens = [clean_cell(c).lower() for c in row_cells if clean_cell(c)]
        
        # 1. Origin match
        has_origin = any(any(o in t for o in ORIGIN_TOKENS) for t in tokens)
        if has_origin:
            score += 0.35
            reasons.append("Contains origin token")

        # 2. Destination match
        has_dest = any(any(d in t for d in DEST_TOKENS) for t in tokens)
        if has_dest:
            score += 0.35
            reasons.append("Contains destination token")

        # 3. Rate break metrics (MIN, LTL, CWT:*, FLAT) and cargo parameters (weight, dims)
        rate_matches = [t for t in tokens if any(r in t for r in RATE_TOKENS)]
        cargo_matches = [t for t in tokens if any(c in t for c in CARGO_TOKENS)]
        metric_matches = rate_matches + cargo_matches
        if metric_matches:
            score += min(0.30, len(metric_matches) * 0.08)
            reasons.append(f"Contains {len(metric_matches)} rate/cargo break tokens: {metric_matches[:4]}")

        # 4. Check subsequent rows for continuous rate data and currency formatting
        subsequent_rows = all_rows[row_idx + 1: row_idx + 45]
        continuous_rate_rows = 0
        has_currency_format = False
        data_preview = []
        allow_integer = bool(cargo_matches)

        for s_idx, s_row in enumerate(subsequent_rows):
            s_cells = [clean_cell(c) for c in s_row if clean_cell(c)]
            if not s_cells:
                break
            
            # Check for geographic lane text in front and numeric rates in back
            num_cells = [c for c in s_cells if is_rate_numeric(c, allow_integer=allow_integer)]
            text_cells = [c for c in s_cells if not is_numeric(c)]

            # Check currency pattern in numbers
            if any("." in c or "$" in c for c in num_cells):
                has_currency_format = True

            if len(text_cells) >= 1 and len(num_cells) >= 1:
                continuous_rate_rows += 1
                if len(data_preview) < 3:
                    data_preview.append([clean_cell(c) for c in s_row if clean_cell(c)][:6])
            elif len(text_cells) >= 1 and allow_integer:
                continuous_rate_rows += 1
                if len(data_preview) < 3:
                    data_preview.append([clean_cell(c) for c in s_row if clean_cell(c)][:6])
            else:
                break

        # Hard Currency / Rate Format Prerequisite (Issue 1)
        # If candidate has no rate/cargo matches and no currency decimals in subsequent rows (e.g. transit schedule with "Est Days: 2")
        if not rate_matches and not cargo_matches and not has_currency_format:
            score = min(score, 0.45)
            reasons.append("Capped <50%: Lacks currency formatted columns or rate/cargo break tokens (transit schedule)")

        # Continuous Row Density Weighting (Issue 1)
        if continuous_rate_rows >= 10:
            score += 0.20
            reasons.append(f"High continuous density: {continuous_rate_rows} contiguous rate rows verified")
        elif continuous_rate_rows >= 3:
            score += 0.10
            reasons.append(f"Verified {continuous_rate_rows} contiguous rate rows beneath")
        elif continuous_rate_rows == 0 and score >= 0.50:
            score -= 0.35
            reasons.append("Penalty: Zero rate data rows beneath candidate")

        return {
            "row_index": row_idx,
            "raw_row": [clean_cell(c) for c in row_cells],
            "score": round(min(1.0, max(0.0, score)), 3),
            "reasons": reasons,
            "continuous_rows": continuous_rate_rows,
            "data_preview": data_preview
        }

    def classify_row(self, row_cells: List[str], row_idx: int = 0, total_rows: int = 100) -> Tuple[str, str, Optional[Dict[str, Any]]]:
        """
        Classifies a non-rate row using the Word Doc 7-category taxonomy & multi-signal detection:
        - Signal 1: Pattern matching (phone, email, postal code, currency, percentages)
        - Signal 2: Keyword triggers (terms, disclaimers, E&OE, company profile, accessorials)
        - Signal 3: Ambiguity routing (prose sentences with numbers routed to surcharges table)
        - Signal 4: Decorative noise filtering (Page 1 of 3, logos)
        """
        first_cell = clean_cell(row_cells[0]).lower() if row_cells else ""
        row_text = " ".join([clean_cell(c) for c in row_cells if clean_cell(c)])
        row_text_lower = row_text.lower()

        # Check Decorative / Page Noise (Word Doc Rule 39)
        if PAGE_NOISE_PATTERN.search(row_text_lower) or row_text_lower in ["page", "logo"]:
            return "DECORATIVE_NOISE", "Ignored decorative/pagination content", None

        # Check Letterhead / Contact Info (Word Doc Rule 34)
        has_phone = bool(PHONE_PATTERN.search(row_text))
        has_email = bool(EMAIL_PATTERN.search(row_text))
        has_entity = bool(COMPANY_ENTITY_PATTERN.search(row_text))
        is_contact_key = any(first_cell == k or first_cell.startswith(k + ":") or first_cell.startswith(k + " ") for k in COMPANY_INFO_KEYS)

        if has_phone or has_email or has_entity or is_contact_key:
            return "NON_CRITICAL_COMPANY_INFO", "Identified letterhead / company contact profile", None

        # Check Prose Surcharges & Accessorial Notes (Issue B & Rule 36)
        # Sentence-structure check: prose cells containing accessorial keywords or monetary symbols
        is_prose = any(is_prose_cell(clean_cell(c)) for c in row_cells)
        has_surcharge_metric = any(sym in row_text for sym in ["$", "%", "waived"])
        accessorial_keywords = [
            "fuel", "appointment", "tailgate", "liftgate", "heated", "dangerous goods",
            "protective service", "residential", "after hour", "reconsignment", "storage"
        ]
        has_acc_keyword = any(acc in row_text_lower for acc in accessorial_keywords)

        if (has_acc_keyword and has_surcharge_metric) or (is_prose and has_acc_keyword):
            struct_acc = extract_structured_surcharge(row_text)
            return "OPERATIONAL_ACCESSORIAL_RULE", "Identified operational surcharge from prose note", struct_acc

        # Check Terms & Legal Disclaimers (Word Doc Rule 35)
        if any(d in row_text_lower for d in LEGAL_KEYWORDS):
            return "NON_CRITICAL_LEGAL_DISCLAIMER", "Identified legal disclaimer / boilerplate term", None

        # Ambiguous numbers in prose without clear accessorial keyword (Rule 37)
        if is_prose and re.search(r'\d+', row_text):
            return "UNKNOWN_NEEDS_REVIEW", "Ambiguous number inside sentence; flagged for review", None

        return "METADATA_ROW", "General spreadsheet metadata", None

    def analyze_header_columns(self, header_row: List[str], data_sample_rows: List[List[str]]) -> Dict[str, Any]:
        """
        Analyzes columns authoritatively without dropping blank header cells (Issue C).
        Identifies:
        - Origin column index
        - Province column index (paired via 2-letter uppercase dictionary validation)
        - Destination column index
        - Destination province column index
        - All Rate Break columns with original header titles preserved.
        """
        cleaned_headers = [clean_cell(h) for h in header_row]
        total_cols = len(cleaned_headers)

        orig_col_idx = None
        orig_prov_col_idx = None
        dest_col_idx = None
        dest_prov_col_idx = None
        ghost_columns_paired = []

        # 1. Detect Origin column
        for c_idx, h in enumerate(cleaned_headers):
            h_lower = h.lower()
            if any(tok in h_lower for tok in ORIGIN_TOKENS):
                orig_col_idx = c_idx
                break
        if orig_col_idx is None and total_cols > 0:
            orig_col_idx = 0

        # Check if column immediately following Origin is a province/state column (Issue C)
        if orig_col_idx is not None and orig_col_idx + 1 < total_cols:
            next_h = cleaned_headers[orig_col_idx + 1]
            if not next_h or "prov" in next_h.lower() or "state" in next_h.lower():
                # Inspect 5-10 rows beneath blank header for 2-letter province codes
                prov_matches = 0
                sample_count = 0
                for r in data_sample_rows[:10]:
                    if orig_col_idx + 1 < len(r):
                        val = clean_cell(r[orig_col_idx + 1]).upper()
                        if val:
                            sample_count += 1
                            if val in ALL_PROV_STATE_CODES or (len(val) == 2 and val.isalpha()):
                                prov_matches += 1
                if (sample_count > 0 and (prov_matches / sample_count) >= 0.6) or not next_h:
                    orig_prov_col_idx = orig_col_idx + 1
                    ghost_columns_paired.append({
                        "col_index": orig_prov_col_idx,
                        "paired_with": "Origin",
                        "assigned_title": "Origin Province"
                    })

        # 2. Detect Destination column
        start_search_dest = (orig_prov_col_idx if orig_prov_col_idx is not None else orig_col_idx) + 1
        for c_idx in range(start_search_dest, total_cols):
            h = cleaned_headers[c_idx]
            h_lower = h.lower()
            if any(tok in h_lower for tok in DEST_TOKENS):
                dest_col_idx = c_idx
                break
        if dest_col_idx is None and total_cols > start_search_dest:
            dest_col_idx = start_search_dest

        # Check if column immediately following Destination is a province/state column (Issue C)
        if dest_col_idx is not None and dest_col_idx + 1 < total_cols:
            next_h = cleaned_headers[dest_col_idx + 1]
            if not next_h or "prov" in next_h.lower() or "state" in next_h.lower():
                prov_matches = 0
                sample_count = 0
                for r in data_sample_rows[:10]:
                    if dest_col_idx + 1 < len(r):
                        val = clean_cell(r[dest_col_idx + 1]).upper()
                        if val:
                            sample_count += 1
                            if val in ALL_PROV_STATE_CODES or (len(val) == 2 and val.isalpha()):
                                prov_matches += 1
                if (sample_count > 0 and (prov_matches / sample_count) >= 0.6) or not next_h:
                    dest_prov_col_idx = dest_col_idx + 1
                    ghost_columns_paired.append({
                        "col_index": dest_prov_col_idx,
                        "paired_with": "Destination",
                        "assigned_title": "Destination Province"
                    })

        # 3. Detect Rate Break columns with original titles preserved
        rate_start_idx = (dest_prov_col_idx if dest_prov_col_idx is not None else dest_col_idx) + 1
        rate_columns = []

        for c_idx in range(rate_start_idx, total_cols):
            raw_title = cleaned_headers[c_idx]
            if raw_title:
                rate_columns.append({
                    "col_index": c_idx,
                    "title": raw_title
                })
            else:
                has_data = any(is_rate_numeric(clean_cell(r[c_idx])) for r in data_sample_rows[:5] if c_idx < len(r))
                if has_data:
                    rate_columns.append({
                        "col_index": c_idx,
                        "title": f"Rate_Col_{c_idx + 1}"
                    })

        return {
            "origin_col": orig_col_idx,
            "origin_prov_col": orig_prov_col_idx,
            "dest_col": dest_col_idx,
            "dest_prov_col": dest_prov_col_idx,
            "rate_columns": rate_columns,
            "ghost_columns_paired": ghost_columns_paired
        }

    def scan_and_parse_sheet(
        self,
        rows: List[List[str]],
        user_confirmed_header_row: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes the two-pass ingestion pipeline:
        Pass 1: Complete preamble classification, noise filtering, and structured prose surcharge extraction.
        Pass 2: Header candidate scoring, 10% threshold Confusion Gate with 2-3 row preview,
                multi-segment extraction, authoritative column pairing, and zero-loss row reconciliation.
        """
        # Pass 1 & Pass 2: Header Candidate Search & Scoring
        candidates = []
        for i, row in enumerate(rows):
            res = self.score_header_candidate(i, row, rows)
            if res["score"] >= 0.50:
                candidates.append(res)

        candidates.sort(key=lambda c: c["score"], reverse=True)

        selected_header_idx = None
        is_confused = False
        clarification_prompt = None

        if user_confirmed_header_row is not None:
            selected_header_idx = user_confirmed_header_row
        elif not candidates:
            is_confused = True
            clarification_prompt = (
                "The agent could not locate a clear freight rate matrix header. "
                "Please specify the row number where your rate columns (Origin, Destination, Rates) begin."
            )
        else:
            top_candidate = candidates[0]
            # Narrowed Confusion Gate Trigger: Scores within 10% (0.10) (Issue 1)
            has_close_runner_up = len(candidates) > 1 and (top_candidate["score"] - candidates[1]["score"]) < 0.10
            
            if top_candidate["score"] < self.confidence_threshold or has_close_runner_up:
                is_confused = True
                cand_list_str = ", ".join([
                    f"Row {c['row_index']+1} ({c['score']*100:.0f}% confidence: '{' | '.join([x for x in c['raw_row'] if x][:4])}' [Rows: {c['continuous_rows']}])"
                    for c in candidates[:3]
                ])
                clarification_prompt = (
                    f"Ambiguity detected: Potential rate table headers found at {cand_list_str}. "
                    "Which row represents your primary freight rate table header?"
                )
            else:
                selected_header_idx = top_candidate["row_index"]

        # Confusion Gate Halt with Rich Preview (Issue 1)
        if is_confused and user_confirmed_header_row is None:
            return {
                "success": False,
                "status": "CONFUSED_NEEDS_CLARIFICATION",
                "message": clarification_prompt,
                "candidates": [
                    {
                        "row_number_1_based": c["row_index"] + 1,
                        "row_index_0_based": c["row_index"],
                        "confidence_score": c["score"],
                        "sample_headers": [x for x in c["raw_row"] if x],
                        "continuous_rows": c.get("continuous_rows", 0),
                        "data_preview": c.get("data_preview", []),
                        "reasons": c["reasons"]
                    } for c in candidates[:4]
                ]
            }

        # Global Row Partitioning & Pass 1 Execution: Rows prior to selected_header_idx
        preamble_rows = []
        company_info = []
        disclaimers = []
        accessorials = []
        structured_surcharges = []
        noise_rows = []
        blank_row_indices = []

        for r_idx in range(selected_header_idx):
            r_cells = rows[r_idx]
            clean_cells = [clean_cell(c) for c in r_cells if clean_cell(c)]
            if not clean_cells:
                blank_row_indices.append(r_idx)
                continue

            cat, desc, struct_acc = self.classify_row(r_cells, r_idx, len(rows))
            entry = {"row": r_idx + 1, "content": clean_cells, "description": desc}
            preamble_rows.append(entry)

            if cat == "DECORATIVE_NOISE":
                noise_rows.append(entry)
            elif cat == "NON_CRITICAL_COMPANY_INFO":
                company_info.append(entry)
            elif cat == "NON_CRITICAL_LEGAL_DISCLAIMER":
                disclaimers.append(entry)
            elif cat == "OPERATIONAL_ACCESSORIAL_RULE":
                accessorials.append(entry)
                if struct_acc:
                    structured_surcharges.append(struct_acc)
            else:
                company_info.append(entry)

        # Ingest Segments starting at selected_header_idx
        header_row = rows[selected_header_idx]
        cleaned_headers = [clean_cell(h) for h in header_row]
        header_row_indices = [selected_header_idx]

        sample_subsequent = rows[selected_header_idx + 1: selected_header_idx + 15]
        col_analysis = self.analyze_header_columns(header_row, sample_subsequent)
        rate_column_titles = [rc["title"] for rc in col_analysis["rate_columns"]]

        segments = []
        current_segment = {
            "segment_id": 1,
            "title": "Primary Rate Matrix",
            "header_row_1_based": selected_header_idx + 1,
            "header_columns": [h for h in cleaned_headers if h],
            "rate_columns": rate_column_titles,
            "rows": []
        }

        rate_data_rows = []
        header_row_indices = [selected_header_idx]
        misaligned_rows = []

        for r_idx in range(selected_header_idx + 1, len(rows)):
            r_cells = rows[r_idx]
            if not any(clean_cell(c) for c in r_cells):
                blank_row_indices.append(r_idx)
                continue

            # Continuous Secondary Header Scanning (Issue D)
            check = self.score_header_candidate(r_idx, r_cells, rows)
            r_text_lower = " ".join([clean_cell(c).lower() for c in r_cells])
            is_secondary_header = (
                (check["score"] >= 0.60 or "between localities" in r_text_lower) and
                any(r in r_text_lower for r in ["min", "ltl", "cwt"])
            )

            if is_secondary_header:
                header_row_indices.append(r_idx)
                # Save previous segment
                if current_segment["rows"]:
                    segments.append(current_segment)

                # Initialize new segment
                sec_subsequent = rows[r_idx + 1: r_idx + 12]
                sec_analysis = self.analyze_header_columns([clean_cell(c) for c in r_cells], sec_subsequent)
                if sec_analysis["rate_columns"]:
                    col_analysis = sec_analysis
                    rate_column_titles = [rc["title"] for rc in col_analysis["rate_columns"]]

                seg_title = clean_cell(r_cells[0]) if clean_cell(r_cells[0]) else f"Segment {len(segments) + 1}"
                current_segment = {
                    "segment_id": len(segments) + 1,
                    "title": seg_title,
                    "header_row_1_based": r_idx + 1,
                    "header_columns": [clean_cell(c) for c in r_cells if clean_cell(c)],
                    "rate_columns": rate_column_titles,
                    "rows": []
                }
                continue

            clean_vals = [clean_cell(c) for c in r_cells]

            # Construct compound Origin and Destination lanes
            orig_idx = col_analysis["origin_col"]
            orig_p_idx = col_analysis["origin_prov_col"]
            if orig_p_idx is not None and orig_p_idx < len(clean_vals) and clean_vals[orig_p_idx]:
                origin_val = f"{clean_vals[orig_idx]}, {clean_vals[orig_p_idx]}" if orig_idx < len(clean_vals) else ""
            else:
                origin_val = clean_vals[orig_idx] if orig_idx is not None and orig_idx < len(clean_vals) else ""

            dest_idx = col_analysis["dest_col"]
            dest_p_idx = col_analysis["dest_prov_col"]
            if dest_p_idx is not None and dest_p_idx < len(clean_vals) and clean_vals[dest_p_idx]:
                dest_val = f"{clean_vals[dest_idx]}, {clean_vals[dest_p_idx]}" if dest_idx < len(clean_vals) else ""
            else:
                dest_val = clean_vals[dest_idx] if dest_idx is not None and dest_idx < len(clean_vals) else ""

            # Extract rate breaks mapped 1-to-1 to original headers
            row_rate_breaks = {}
            row_rate_break_items = []
            is_misaligned = False

            for rc in col_analysis["rate_columns"]:
                c_idx = rc["col_index"]
                title = rc["title"]
                cell_val = clean_vals[c_idx] if c_idx < len(clean_vals) else ""

                # Grid Alignment Check (Issue C)
                if cell_val and not is_rate_numeric(cell_val, allow_integer=True):
                    is_misaligned = True

                row_rate_breaks[title] = cell_val
                row_rate_break_items.append({
                    "header": title,
                    "value": cell_val,
                    "col_index": c_idx
                })

            if is_misaligned:
                misaligned_rows.append(r_idx + 1)

            row_record = {
                "row_number": r_idx + 1,
                "segment_id": current_segment["segment_id"],
                "raw_values": clean_vals,
                "origin": origin_val,
                "destination": dest_val,
                "rate_breaks": row_rate_breaks,
                "rate_break_items": row_rate_break_items,
                "rates": [row_rate_breaks[t] for t in rate_column_titles] if row_rate_breaks else (clean_vals[4:] if len(clean_vals) > 4 else clean_vals[2:]),
                "rate_columns": rate_column_titles,
                "needs_review": is_misaligned
            }

            rate_data_rows.append(row_record)
            current_segment["rows"].append(row_record)

        if current_segment["rows"]:
            segments.append(current_segment)

        # Zero-Data-Loss Row Reconciliation Audit (Issue D)
        total_raw_rows = len(rows)
        counted_preamble = len(preamble_rows)
        counted_blanks = len(blank_row_indices)
        counted_headers = len(header_row_indices)
        counted_data = len(rate_data_rows)
        counted_accessorials = len(accessorials)
        counted_noise = len(noise_rows)
        counted_company = len(company_info)
        counted_disclaimers = len(disclaimers)

        total_reconciled = counted_preamble + counted_blanks + counted_headers + counted_data
        unaccounted_rows = max(0, total_raw_rows - total_reconciled)

        # Composite Sheet Health Confidence Score
        health_score = 100
        if counted_preamble > 25:
            health_score -= 5
        if len(segments) > 1:
            health_score -= 5
        if col_analysis.get("ghost_columns_paired"):
            health_score -= 5
        if misaligned_rows:
            health_score -= 10
        if unaccounted_rows > 0:
            health_score -= 20

        composite_sheet_health = max(10, min(100, health_score))

        return {
            "success": True,
            "status": "CLASSIFICATION_AND_EXTRACTION_COMPLETE",
            "detected_header_row_1_based": selected_header_idx + 1,
            "detected_header_row_0_based": selected_header_idx,
            "header_columns": [h for h in cleaned_headers if h],
            "rate_columns": rate_column_titles,
            "rate_columns_spec": col_analysis["rate_columns"],
            "ghost_columns_paired": col_analysis.get("ghost_columns_paired", []),
            "composite_sheet_health": composite_sheet_health,
            "reconciliation_audit": {
                "total_sheet_rows": total_raw_rows,
                "reconciled_rows": total_reconciled,
                "unaccounted_rows": unaccounted_rows,
                "reconciliation_passed": unaccounted_rows == 0,
                "breakdown": {
                    "preamble_and_terms": counted_preamble,
                    "operational_accessorials": counted_accessorials,
                    "noise_and_pagination": counted_noise,
                    "blank_spacer_rows": counted_blanks,
                    "table_header_rows": counted_headers,
                    "protected_data_rows": counted_data
                }
            },
            "summary": {
                "total_sheet_rows": total_raw_rows,
                "non_critical_company_info_count": len(company_info),
                "non_critical_legal_disclaimers_count": len(disclaimers),
                "active_accessorial_rules_count": len(accessorials),
                "protected_rate_data_rows_extracted": len(rate_data_rows),
                "rows_deleted_or_dropped": 0,
                "table_segments_count": len(segments),
                "rate_headers_count": len(rate_column_titles),
                "misaligned_rows_count": len(misaligned_rows)
            },
            "structured_surcharges": structured_surcharges,
            "disclaimers": disclaimers,
            "company_info": company_info,
            "accessorial_rules": accessorials,
            "rate_data_rows": rate_data_rows,
            "segments": segments
        }
