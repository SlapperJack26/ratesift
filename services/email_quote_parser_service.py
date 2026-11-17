"""
services/email_quote_parser_service.py
======================================
1-Second Deterministic "Paste Shipper Email / RFQ" Smart Parser.

Zero LLM token cost, zero external API calls (<5ms latency).
Extracts from raw unstructured shipper email text:
- Origin & Destination (Canadian 6-char postal codes, 3-char FSAs, or 150+ Canadian city names)
- Total Weight (in lbs, or auto-converted from kg to lbs)
- Skid / Pallet Count (e.g. '4 skids', '2 pallets', '3 plt')
- Dimensions L x W x H in inches (e.g. '48x40x60', '48 x 40 x 52 in')
- Requested Canadian LTL Accessorials ('tailgate', 'heated', 'residential', 'appointment', 'inside_delivery', 'limited_access')
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from services.fsa_resolver_service import (
    CANADIAN_CITY_TO_FSA_MAP,
    FSA_DATABASE,
    extract_fsa,
    resolve_location,
    strip_accents,
)

KG_TO_LBS = 2.20462262185


def _extract_origin_and_dest(raw_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Finds origin and destination from raw email text using:
    1. Explicit 'from <A> to <B>' or 'origin: <A> ... dest: <B>' patterns
    2. 6-character Canadian postal codes (e.g. M5V 2T6, T2P 1J9)
    3. 3-character FSAs (e.g. L5T, R3C)
    4. Known Canadian city names from CANADIAN_CITY_TO_FSA_MAP
    """
    norm = strip_accents(raw_text)
    upper = norm.upper()

    # 1. Check for 6-character Canadian postal codes first (most specific)
    postal_matches = list(
        re.finditer(r"\b([A-CEGHJ-NPR-TV-Z]\d[A-CEGHJ-NPR-TV-Z])\s*(\d[A-CEGHJ-NPR-TV-Z]\d)\b", upper)
    )
    if len(postal_matches) >= 2:
        orig = f"{postal_matches[0].group(1)} {postal_matches[0].group(2)}"
        dest = f"{postal_matches[1].group(1)} {postal_matches[1].group(2)}"
        return orig, dest

    # 2. Check explicit "FROM <X> TO <Y>" phrasing
    from_to = re.search(
        r"\bFROM\s+([A-Z0-9\-\.\s,]{3,30}?)\s+(?:TO|->|→|INTO)\s+([A-Z0-9\-\.\s,]{3,30}?)(?:\b(?:FOR|WITH|AT|ON|WEIGHT|NEED|TOTAL|\d+)\b|$|[\n\r.;])",
        upper,
    )
    if from_to:
        cand_orig = from_to.group(1).strip(" ,.-")
        cand_dest = from_to.group(2).strip(" ,.-")
        orig_fsa = extract_fsa(cand_orig)
        dest_fsa = extract_fsa(cand_dest)
        if orig_fsa and dest_fsa:
            return orig_fsa, dest_fsa

    # 3. Collect all ordered location tokens (6-char postals, 3-char FSAs, and known Canadian cities)
    found_tokens: List[Tuple[int, str]] = []

    for m in postal_matches:
        found_tokens.append((m.start(), f"{m.group(1)} {m.group(2)}"))

    # Standalone 3-character FSAs
    for m in re.finditer(r"\b([A-CEGHJ-NPR-TV-Z]\d[A-CEGHJ-NPR-TV-Z])\b", upper):
        pos = m.start()
        if not any(abs(pos - existing_pos) < 4 for existing_pos, _ in found_tokens):
            found_tokens.append((pos, m.group(1)))

    # Known Canadian city names (sorted longest first so 'SAINT LAURENT' matches before 'LAURENT')
    for city_name, fsa_code in sorted(CANADIAN_CITY_TO_FSA_MAP.items(), key=lambda x: -len(x[0])):
        if len(city_name) < 4:
            continue
        for m in re.finditer(rf"\b{re.escape(city_name)}\b", upper):
            pos = m.start()
            # Avoid duplicate overlapping matches around the same character span
            if not any(abs(pos - existing_pos) < 12 for existing_pos, _ in found_tokens):
                found_tokens.append((pos, fsa_code))

    found_tokens.sort(key=lambda x: x[0])

    # Deduplicate consecutive identical FSAs (e.g. 'Mississauga L5T 1A1' -> keep 'L5T 1A1')
    deduped: List[str] = []
    for _, tok in found_tokens:
        tok_fsa = tok[:3]
        if deduped and deduped[-1][:3] == tok_fsa:
            # Prefer full 6-char postal code if the second token is 6-char
            if len(tok) > len(deduped[-1]):
                deduped[-1] = tok
            continue
        deduped.append(tok)

    if len(deduped) >= 2:
        return deduped[0], deduped[1]
    if len(deduped) == 1:
        return deduped[0], None
    return None, None


def _extract_weight_lbs(raw_text: str) -> Tuple[Optional[float], str]:
    """
    Extracts shipment weight in lbs (converting kg -> lbs if kg is specified).
    Handles e.g. '2,450 lbs', '1850 lb', '1,000 kg', 'weight: 3200#'.
    """
    # Check lbs first
    lb_match = re.search(
        r"\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:lbs?|pounds?|#)\b",
        raw_text,
        re.IGNORECASE,
    )
    if lb_match:
        val = float(lb_match.group(1).replace(",", ""))
        if 1.0 <= val <= 100000.0:
            return round(val, 2), "lb"

    # Check kg and convert to lbs
    kg_match = re.search(
        r"\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:kgs?|kilograms?|kilos?)\b",
        raw_text,
        re.IGNORECASE,
    )
    if kg_match:
        kg_val = float(kg_match.group(1).replace(",", ""))
        if 1.0 <= kg_val <= 50000.0:
            return round(kg_val * KG_TO_LBS, 2), "kg_converted_to_lb"

    return None, "lb"


def _extract_skid_count(raw_text: str) -> Optional[int]:
    """Extracts skid or pallet count (e.g. '4 skids', '2 pallets', '3 plts')."""
    m = re.search(
        r"\b(\d{1,2})\s*(?:skids?|pallets?|plts?|skds?)\b",
        raw_text,
        re.IGNORECASE,
    )
    if m:
        cnt = int(m.group(1))
        if 1 <= cnt <= 30:
            return cnt
    return None


def _extract_dimensions(raw_text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Extracts L x W x H dimensions (e.g. '48x40x60', '48\" x 40\" x 52\"')."""
    m = re.search(
        r"\b(\d{2,3}(?:\.\d+)?)\s*[\"']?\s*[xX×*]\s*(\d{2,3}(?:\.\d+)?)\s*[\"']?\s*[xX×*]\s*(\d{2,3}(?:\.\d+)?)\b",
        raw_text,
    )
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    return None, None, None


def _extract_accessorials(raw_text: str) -> List[str]:
    """Detects requested Canadian LTL accessorials from unstructured text."""
    lower = raw_text.lower()
    acc: List[str] = []

    if any(k in lower for k in ("tailgate", "tail gate", "liftgate", "lift gate", "power gate")):
        acc.append("tailgate")
    if any(k in lower for k in ("heated", "heat", "freeze", "temp control", "protective service", "protect from freeze")):
        acc.append("heated")
    if any(k in lower for k in ("residential", "home delivery", "private address", "house")):
        acc.append("residential")
    if any(k in lower for k in ("appointment", "appt", "call before", "booked delivery", "time window")):
        acc.append("appointment")
    if any(k in lower for k in ("inside delivery", "inside pickup", "bring inside")):
        acc.append("inside_delivery")
    if any(k in lower for k in ("limited access", "construction site", "job site", "mall", "school")):
        acc.append("limited_access")

    return acc


def parse_shipper_email_text(raw_text: str) -> Dict[str, Any]:
    """
    Parses a pasted shipper email / RFQ snippet into structured quote fields.
    """
    if not raw_text or not str(raw_text).strip():
        raise ValueError("Please paste a shipper email or quote request snippet.")

    text = str(raw_text).strip()
    origin, destination = _extract_origin_and_dest(text)
    weight_lbs, weight_source = _extract_weight_lbs(text)
    skid_count = _extract_skid_count(text)
    length, width, height = _extract_dimensions(text)
    accessorials = _extract_accessorials(text)

    orig_info = resolve_location(origin) if origin else {}
    dest_info = resolve_location(destination) if destination else {}

    fields_detected = sum(
        1 for v in (origin, destination, weight_lbs, skid_count, length, accessorials) if v
    )

    return {
        "status": "success",
        "origin": origin or "",
        "destination": destination or "",
        "origin_fsa": orig_info.get("fsa") or "",
        "origin_label": orig_info.get("location_string") or "",
        "dest_fsa": dest_info.get("fsa") or "",
        "dest_label": dest_info.get("location_string") or "",
        "weight_lbs": weight_lbs,
        "weight_unit_source": weight_source,
        "skid_count": skid_count or 1,
        "length": length or 48.0,
        "width": width or 40.0,
        "height": height or 48.0,
        "dimensions_detected": bool(length and width and height),
        "accessorials": accessorials,
        "fields_detected": fields_detected,
    }
