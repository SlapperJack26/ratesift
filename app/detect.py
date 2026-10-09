"""
Header detection + validation for rate-sheet uploads.
Pure Python (plus openpyxl for .xlsx) so it can be unit-tested without FastAPI.

Rule: Origin + Destination are ALWAYS required, plus EITHER weight breaks OR skid rates.
Anything below the confidence thresholds goes to the user for manual mapping.
"""
import csv
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    HIGH,
    LOW,
    MAX_SCAN_ROWS,
    SKID_COUNT_COL_HDR,
    SKID_HDR,
    SKID_WORD,
    SYNONYMS,
    WEIGHT_BREAK_PATTERN,
    WEIGHT_UNIT_REGEX,
)
from app.ingest import flatten_two_row_headers, normalize_header


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _is_num(v: Any) -> bool:
    try:
        float(str(v).replace("$", "").replace(",", "").strip())
        return True
    except (ValueError, AttributeError):
        return False


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def parse_break_value(h: Any) -> Tuple[Optional[float], Optional[str]]:
    """
    Parses a header cell into (break_value, weight_unit).
    Handles: -45, +100, 100+, 100-499, 45 lb, 45#, 45 kg, 500 cwt, numeric cells.
    Weight break values in freight are positive thresholds (e.g. -45 lbs break point is 45.0).
    """
    raw = _s(h)
    if not raw:
        return None, None

    # Detect unit
    unit: Optional[str] = None
    u_match = WEIGHT_UNIT_REGEX.search(raw)
    if u_match:
        matched = u_match.group(0).lower()
        unit = "lb" if matched in ("lb", "lbs", "#", "cwt") else "kg"

    # Strip prefixes like rate, rates, break(s), ltl, min, and signs -, +, <, >
    cleaned = re.sub(
        r"^\s*(?:[-+<>]|rates?|breaks?|weight\s*breaks?|ltl(?:\s*rates?)?(?:\s*\([^)]*\))?|min)\s*",
        "",
        raw,
        flags=re.I
    )

    # Match break pattern (-45, +100, 100+, 100-499, 45 lb, -45 (lbs), etc.)
    m = re.match(
        r"^\s*(?:[-+<>]|ltl|min)?\s*(\d+(?:\.\d+)?)\s*(?:\+|(?:\(?\s*(?:lbs?|kgs?|#|cwt)\s*\)?))?(?:\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:lbs?|kgs?|#|cwt)?)?\s*$",
        cleaned,
        re.I
    )
    if m:
        val = _to_float(m.group(1))
        if val is not None:
            return abs(val), unit

    # Pure numeric cell (e.g. openpyxl int/float or pure string number)
    if _is_num(cleaned):
        val = _to_float(cleaned)
        if val is not None:
            return abs(val), unit


    return None, None


# ---------------------------------------------------------------- loading
def load_rows(path: str, ext: str, max_rows: int = MAX_SCAN_ROWS) -> List[List[Any]]:
    """Loads spreadsheet rows using safe ingestion with merged cell support."""
    from app.ingest import load_sheet_grid
    grid, _ = load_sheet_grid(path, ext, max_rows=max_rows)
    return grid


# ---------------------------------------------------------------- header row
def find_header_row(rows: List[List[Any]]) -> Optional[int]:
    """Finds the first row (in top 25) with >= 3 text-ish cells followed by data."""
    for i, row in enumerate(rows[:25]):
        cells = [_s(c) for c in row if _s(c)]
        if len(cells) < 3 or i + 1 >= len(rows):
            continue

        texty = 0
        for c in cells:
            b_val, _ = parse_break_value(c)
            # Break pattern headers or non-numeric strings count as text-ish
            if not _is_num(c) or b_val is not None:
                texty += 1

        nxt = [_s(c) for c in rows[i + 1] if _s(c)]
        if texty / len(cells) >= 0.7 and len(nxt) >= 2:
            return i
    return None


def detect_and_flatten_headers(rows: List[List[Any]], hdr_idx: int) -> Tuple[List[str], int]:
    """
    Detects two-row headers (e.g. category band above break row) and flattens them.
    Returns (flattened_headers, effective_hdr_idx).
    """
    if hdr_idx + 1 >= len(rows):
        return [_s(c) for c in rows[hdr_idx]], hdr_idx

    curr_row = [_s(c) for c in rows[hdr_idx]]
    next_row = [_s(c) for c in rows[hdr_idx + 1]]

    # Check if next row looks like sub-headers (contains weight breaks or skid headers)
    next_has_breaks = any(parse_break_value(c)[0] is not None for c in next_row)
    curr_has_breaks = any(parse_break_value(c)[0] is not None for c in curr_row)
    
    # If current row already contains origin, destination, AND breaks, it's a complete header row
    has_orig = any(_header_score(c, "origin") >= 0.7 for c in curr_row)
    has_dest = any(_header_score(c, "destination") >= 0.7 for c in curr_row)
    if has_orig and has_dest and curr_has_breaks:
        return curr_row, hdr_idx

    # If next row contains breaks (or locations) and row after next has numeric data, flatten them
    next_has_locations = any(_header_score(c, "origin") >= 0.7 or _header_score(c, "destination") >= 0.7 for c in next_row)
    if (next_has_breaks or next_has_locations) and len(rows) > hdr_idx + 2:
        nxt_data = [_s(c) for c in rows[hdr_idx + 2] if _s(c)]
        if len(nxt_data) >= 2 and any(_is_num(c) for c in nxt_data):
            return flatten_two_row_headers(curr_row, next_row), hdr_idx + 1

    return curr_row, hdr_idx



# ---------------------------------------------------------------- scoring
def _header_score(header: str, field: str) -> float:
    norm = normalize_header(header)
    if not norm:
        return 0.0

    synonyms = SYNONYMS.get(field, [])
    best = 0.0
    for syn in synonyms:
        syn_norm = normalize_header(syn)
        if norm == syn_norm:
            return 1.0
        ratio = SequenceMatcher(None, norm, syn_norm).ratio()
        if ratio >= 0.75:
            best = max(best, ratio * 0.9)
        if len(syn_norm) > 3 and syn_norm in norm:
            best = max(best, 0.8)
    return best


def _content_score(values: List[Any], field: str) -> float:
    vals = [_s(v) for v in values if _s(v)]
    if not vals:
        return 0.0
    if field in ("origin", "destination"):
        # Place names / postal codes / port codes: mostly non-numeric strings
        return sum(1 for v in vals if not _is_num(v) or re.match(r"^[A-Za-z]\d[A-Za-z]", v)) / len(vals)
    return 0.5


def _column(rows: List[List[Any]], hdr_row: int, col: int, n: int = 30) -> List[Any]:
    return [r[col] if col < len(r) else None for r in rows[hdr_row + 1: hdr_row + 1 + n]]


def score_single_field(
    rows: List[List[Any]],
    headers: List[str],
    hdr_row: int,
    field: str,
    exclude: Tuple[int, ...] = (),
) -> Tuple[Optional[int], float, List[Tuple[int, float]]]:
    """Scores all candidate columns for a field. Returns (best_col, best_score, all_candidates)."""
    candidates: List[Tuple[int, float]] = []
    best_col, best = None, 0.0
    for c, h in enumerate(headers):
        if c in exclude or not _s(h):
            continue
        hs = _header_score(_s(h), field)
        sc = 0.7 * hs + 0.3 * _content_score(_column(rows, hdr_row, c), field)
        # Content alone must never auto-map a hard-required field
        if hs < 0.4:
            sc = min(sc, LOW - 0.05)
        sc = round(sc, 2)
        if sc >= LOW:
            candidates.append((c, sc))
        if sc > best:
            best_col, best = c, sc

    candidates.sort(key=lambda x: x[1], reverse=True)
    return best_col, best, candidates


# ---------------------------------------------------------------- break & unit detection
def detect_weight_unit(rows: List[List[Any]], hdr_row: int, break_units: List[str]) -> Optional[str]:
    """Detects weight unit from break headers, header row, or title rows above."""
    # 1. From break headers
    for u in break_units:
        if u:
            return u

    # 2. From header row cells
    if 0 <= hdr_row < len(rows):
        for cell in rows[hdr_row]:
            m = WEIGHT_UNIT_REGEX.search(_s(cell))
            if m:
                matched = m.group(0).lower()
                return "lb" if matched in ("lb", "lbs", "#", "cwt") else "kg"

    # 3. From title rows above header row
    for r in range(min(hdr_row, 10)):
        for cell in rows[r]:
            m = WEIGHT_UNIT_REGEX.search(_s(cell))
            if m:
                matched = m.group(0).lower()
                return "lb" if matched in ("lb", "lbs", "#", "cwt") else "kg"

    return None


def detect_break_columns(rows: List[List[Any]], headers: List[str], hdr_row: int) -> Dict[str, Any]:
    """Finds weight-break columns, skid columns, and skid-row layouts."""
    weight_cols, skid_cols, weight_vals, break_units = [], [], [], []
    skid_count_col, skid_rate_col = None, None

    for c, h in enumerate(headers):
        h_str = _s(h)
        if not h_str:
            continue
        data = [v for v in _column(rows, hdr_row, c) if _s(v)]
        numeric_data = bool(data) and sum(_is_num(v) for v in data) / len(data) >= 0.8

        b_val, b_unit = parse_break_value(h_str)

        if SKID_HDR.match(h_str):
            skid_cols.append(c)
        elif b_val is not None and numeric_data:
            weight_cols.append(c)
            weight_vals.append(b_val)
            if b_unit:
                break_units.append(b_unit)
        elif SKID_COUNT_COL_HDR.match(h_str) or (SKID_WORD.search(h_str) and numeric_data):
            # Potential skid row layout count column (1, 2, 3...)
            # Verify data contains small sequential numbers
            int_data = [_to_float(v) for v in data if _to_float(v) is not None]
            if int_data and all(0 < x <= 50 for x in int_data[:10]):
                skid_count_col = c

    # Find rate column if skid count column was found
    if skid_count_col is not None and not skid_cols:
        for c, h in enumerate(headers):
            if c == skid_count_col:
                continue
            norm = normalize_header(h)
            if any(term in norm for term in ("rate", "price", "cost", "charge", "amount")):
                data = [v for v in _column(rows, hdr_row, c) if _s(v)]
                if data and sum(_is_num(v) for v in data) / len(data) >= 0.8:
                    skid_rate_col = c
                    break

    skid_label_col = next((c for c, h in enumerate(headers) if SKID_WORD.search(_s(h)) and c not in skid_cols), None)

    return {
        "weight_cols": weight_cols if len(weight_cols) >= 2 else [],
        "weight_vals": weight_vals if len(weight_cols) >= 2 else [],
        "break_units": break_units,
        "skid_cols": skid_cols,
        "skid_label_col": skid_label_col,
        "skid_count_col": skid_count_col,
        "skid_rate_col": skid_rate_col,
    }


# ---------------------------------------------------------------- analyze
def analyze(rows: List[List[Any]], sheet_name: Optional[str] = None) -> Dict[str, Any]:
    """Analyzes spreadsheet rows. Returns analysis dictionary for JobState."""
    issues: List[str] = []
    guesses: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    suggestions: Dict[str, int] = {}
    conflicts: List[Dict[str, Any]] = []

    raw_hdr = find_header_row(rows)
    if raw_hdr is None:
        return {
            "status": "needs_mapping",
            "header_row": None,
            "sheet_name": sheet_name,
            "mode": None,
            "weight_unit": None,
            "guesses": [],
            "conflicts": [],
            "unresolved": ["header_row"],
            "issues": ["Couldn't find the header row - please click it."],
            "suggestions": suggestions,
        }

    # Flatten two-row headers if present
    headers, hdr = detect_and_flatten_headers(rows, raw_hdr)

    # Score origin and destination
    candidates_by_field: Dict[str, List[Tuple[int, float]]] = {}
    best_by_field: Dict[str, Tuple[Optional[int], float]] = {}

    for fld in ("origin", "destination"):
        col, conf, cands = score_single_field(rows, headers, hdr, fld)
        best_by_field[fld] = (col, conf)
        candidates_by_field[fld] = cands

    orig_col, orig_conf = best_by_field["origin"]
    dest_col, dest_conf = best_by_field["destination"]

    # Conflict check 1: Same column claimed by both fields
    if orig_col is not None and dest_col is not None and orig_col == dest_col:
        conflicts.append({
            "field": "origin/destination",
            "columns": [orig_col],
            "reason": f"Column {orig_col + 1} matches both Origin and Destination.",
        })
        unresolved.extend(["origin", "destination"])
        issues.append(f"Column {orig_col + 1} ('{headers[orig_col]}') matches both Origin and Destination - please map manually.")
    else:
        # Check Origin
        if orig_col is None or orig_conf < LOW:
            unresolved.append("origin")
            issues.append("Couldn't identify the origin column.")
            if orig_col is not None:
                suggestions["origin"] = orig_col
        else:
            # Check for competing candidates
            cands = candidates_by_field["origin"]
            if len(cands) >= 2 and cands[1][1] >= 0.70 and (cands[0][1] - cands[1][1] < 0.15):
                comp_cols = [cands[0][0], cands[1][0]]
                conflicts.append({
                    "field": "origin",
                    "columns": comp_cols,
                    "reason": "Multiple columns strongly match Origin.",
                })
                unresolved.append("origin")
                issues.append(f"Multiple columns look like Origin (columns {comp_cols[0]+1} and {comp_cols[1]+1}) - please pick one.")
                suggestions["origin"] = orig_col
            else:
                guesses.append({
                    "field": "origin",
                    "columns": [orig_col],
                    "confidence": orig_conf,
                    "needs_confirmation": orig_conf < HIGH,
                })

        # Check Destination
        if dest_col is None or dest_conf < LOW:
            unresolved.append("destination")
            issues.append("Couldn't identify the destination column.")
            if dest_col is not None:
                suggestions["destination"] = dest_col
        else:
            # Check for competing candidates
            cands = candidates_by_field["destination"]
            if len(cands) >= 2 and cands[1][1] >= 0.70 and (cands[0][1] - cands[1][1] < 0.15):
                comp_cols = [cands[0][0], cands[1][0]]
                conflicts.append({
                    "field": "destination",
                    "columns": comp_cols,
                    "reason": "Multiple columns strongly match Destination.",
                })
                unresolved.append("destination")
                issues.append(f"Multiple columns look like Destination (columns {comp_cols[0]+1} and {comp_cols[1]+1}) - please pick one.")
                suggestions["destination"] = dest_col
            else:
                guesses.append({
                    "field": "destination",
                    "columns": [dest_col],
                    "confidence": dest_conf,
                    "needs_confirmation": dest_conf < HIGH,
                })

    # Break columns & mode detection
    br = detect_break_columns(rows, headers, hdr)
    has_w = bool(br["weight_cols"])
    has_s = bool(br["skid_cols"] or (br["skid_count_col"] is not None and br["skid_rate_col"] is not None) or br["skid_label_col"] is not None)

    mode: Optional[str] = None
    weight_unit: Optional[str] = None

    if has_w and has_s:
        issues.append("Sheet looks like it has both weight breaks and skid rates - which should be quoted?")
        unresolved.append("mode")
    elif has_w:
        mode = "weight"
        weight_unit = detect_weight_unit(rows, hdr, br["break_units"])
        guesses.append({
            "field": "weight_breaks",
            "columns": br["weight_cols"],
            "confidence": 0.9,
            "needs_confirmation": False,
            "break_values": br["weight_vals"],
        })
        # Rule 8: Weight unit is required in weight mode.
        if not weight_unit:
            unresolved.append("weight_unit")
            issues.append("Weight unit (lb or kg) could not be detected. Please select one.")
    elif has_s:
        mode = "skid"
        if br["skid_count_col"] is not None and br["skid_rate_col"] is not None:
            # Row layout skid rates
            guesses.append({
                "field": "skid_rates",
                "columns": [br["skid_count_col"], br["skid_rate_col"]],
                "confidence": 0.85,
                "needs_confirmation": True,
            })
        else:
            cols = br["skid_cols"] or ([br["skid_label_col"]] if br["skid_label_col"] is not None else [])
            guesses.append({
                "field": "skid_rates",
                "columns": cols,
                "confidence": 0.8,
                "needs_confirmation": True,
            })
    else:
        issues.append("No weight breaks or skid/pallet columns found - is this priced by weight or by skid?")
        unresolved.append("mode")

    # Obvious missing rate data check:
    # If the sheet has no numeric rate values across data rows, flag as missing data
    data_rows = rows[hdr + 1:] if hdr is not None and hdr + 1 < len(rows) else []
    total_numeric_cells = sum(
        1 for r in data_rows for c in r if _is_num(c)
    )
    if not total_numeric_cells and data_rows:
        issues.append("No numeric freight rates found in data rows. The sheet appears to be an equipment/routing matrix or is missing rate values.")
        if "rates" not in unresolved:
            unresolved.append("rates")

    # Status determination: Rule 4, Rule 8, and Rule 6
    needs_conf = any(g.get("needs_confirmation") for g in guesses)
    status = "ready" if (not unresolved and not conflicts and not needs_conf) else "needs_mapping"

    return {
        "status": status,
        "header_row": hdr,
        "sheet_name": sheet_name,
        "mode": mode,
        "weight_unit": weight_unit,
        "guesses": guesses,
        "conflicts": conflicts,
        "unresolved": unresolved,
        "issues": issues,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------- validation of user choices
def validate_mapping(
    rows: List[List[Any]],
    header_row: int,
    mode: str,
    origin: int,
    destination: int,
    rate_columns: List[int],
    weight_unit: Optional[str] = None,
    skid_count_column: Optional[int] = None,
) -> List[str]:
    """Return a list of human-readable problems; empty list = OK."""
    errs: List[str] = []
    width = max((len(r) for r in rows), default=0)
    if not (0 <= header_row < len(rows)):
        return ["Header row is out of range."]

    all_cols = [("Origin", origin), ("Destination", destination)]
    for c in rate_columns:
        all_cols.append(("Rate column", c))
    if skid_count_column is not None:
        all_cols.append(("Skid count column", skid_count_column))

    for name, c in all_cols:
        if not (0 <= c < width):
            errs.append(f"{name} column {c} is outside the sheet.")
    if errs:
        return errs

    if origin == destination:
        errs.append("Origin and Destination can't be the same column.")
    if set(rate_columns) & {origin, destination}:
        errs.append("A rate column overlaps with Origin/Destination.")
    if skid_count_column is not None and skid_count_column in {origin, destination}:
        errs.append("Skid count column overlaps with Origin/Destination.")

    if not rate_columns:
        errs.append("Select at least one weight-break or skid rate column.")

    if mode == "weight":
        if not weight_unit or weight_unit.lower() not in ("lb", "kg"):
            errs.append("Choose a valid weight unit (lb or kg).")
        vals: List[float] = []
        for c in rate_columns:
            val, _ = parse_break_value(_s(rows[header_row][c]))
            if val is None:
                errs.append(f"Column {c + 1} header '{_s(rows[header_row][c])}' doesn't look like a weight break.")
            else:
                vals.append(val)
        if vals and vals != sorted(vals):
            errs.append("Weight breaks must be in ascending order left to right.")
        if len(set(vals)) != len(vals):
            errs.append("Duplicate weight breaks found.")

    for c in rate_columns:
        data = [v for v in _column(rows, header_row, c) if _s(v)]
        if data and sum(_is_num(v) for v in data) / len(data) < 0.8:
            errs.append(f"Column {c + 1} ('{_s(rows[header_row][c])}') isn't mostly numeric - is it a rate column?")

    return errs
