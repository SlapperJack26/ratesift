"""
services/fsa_resolver_service.py
================================
RateSift Canadian Postal Forward Sortation Area (FSA) Resolver Service.

Provides comprehensive mapping and deterministic resolution for Canadian postal codes
and FSAs across all 10 provinces and 3 territories, mapping them to canonical freight cities,
provinces, freight zones, and rural/remote classification.
"""

import re
from typing import Optional, Dict, Any, Tuple, List

# Canadian Province/Territory standard 2-letter codes and names
PROVINCES = {
    "ON": "Ontario",
    "QC": "Quebec",
    "BC": "British Columbia",
    "AB": "Alberta",
    "MB": "Manitoba",
    "SK": "Saskatchewan",
    "NS": "Nova Scotia",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island",
    "YT": "Yukon",
    "NT": "Northwest Territories",
    "NU": "Nunavut"
}

# Major Canadian Freight Hubs & Forward Sortation Area (FSA) Clusters
# Letter 1 defines the postal district. Number 2 defines rural (0) vs urban (1-9).
FSA_DATABASE: Dict[str, Dict[str, Any]] = {
    # --- ONTARIO: GTA & Metro Toronto (M) ---
    "M1B": {"city": "Scarborough", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M1C": {"city": "Scarborough", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M1E": {"city": "Scarborough", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M1G": {"city": "Scarborough", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M1H": {"city": "Scarborough", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M1P": {"city": "Scarborough", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M2H": {"city": "North York", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M2J": {"city": "North York", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M2N": {"city": "North York", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M3A": {"city": "North York", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M3J": {"city": "North York", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M4B": {"city": "East York", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M4W": {"city": "Toronto", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M5A": {"city": "Toronto", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M5B": {"city": "Toronto", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M5H": {"city": "Toronto", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M5J": {"city": "Toronto", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M5V": {"city": "Toronto", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M6A": {"city": "North York", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M6K": {"city": "Toronto", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M8Z": {"city": "Etobicoke", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},
    "M9W": {"city": "Etobicoke", "province": "ON", "metro": "Toronto", "region": "GTA", "is_rural": False, "zone": "ON-TOR"},

    # --- ONTARIO: Central & Suburban GTA (L) ---
    "L3R": {"city": "Markham", "province": "ON", "metro": "Toronto", "region": "York", "is_rural": False, "zone": "ON-TOR"},
    "L4K": {"city": "Concord", "province": "ON", "metro": "Toronto", "region": "Vaughan", "is_rural": False, "zone": "ON-TOR"},
    "L4T": {"city": "Mississauga", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L4W": {"city": "Mississauga", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L5T": {"city": "Mississauga", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L6T": {"city": "Brampton", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L6W": {"city": "Brampton", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L6P": {"city": "Brampton", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L7L": {"city": "Burlington", "province": "ON", "metro": "Hamilton", "region": "Halton", "is_rural": False, "zone": "ON-HAM"},
    "L8H": {"city": "Hamilton", "province": "ON", "metro": "Hamilton", "region": "Hamilton", "is_rural": False, "zone": "ON-HAM"},
    "L9V": {"city": "Lindsay", "province": "ON", "metro": "Kawartha Lakes", "region": "Central ON", "is_rural": False, "zone": "ON-CEN"},
    "K9V": {"city": "Lindsay", "province": "ON", "metro": "Kawartha Lakes", "region": "Kawartha", "is_rural": False, "zone": "ON-CEN"},

    # --- ONTARIO: Eastern & Ottawa (K) ---
    "K1A": {"city": "Ottawa", "province": "ON", "metro": "Ottawa", "region": "Eastern ON", "is_rural": False, "zone": "ON-OTT"},
    "K1P": {"city": "Ottawa", "province": "ON", "metro": "Ottawa", "region": "Eastern ON", "is_rural": False, "zone": "ON-OTT"},
    "K2E": {"city": "Nepean", "province": "ON", "metro": "Ottawa", "region": "Eastern ON", "is_rural": False, "zone": "ON-OTT"},
    "K7L": {"city": "Kingston", "province": "ON", "metro": "Kingston", "region": "Eastern ON", "is_rural": False, "zone": "ON-EAS"},
    "K9H": {"city": "Peterborough", "province": "ON", "metro": "Peterborough", "region": "Central ON", "is_rural": False, "zone": "ON-CEN"},

    # --- ONTARIO: Southwestern (N) ---
    "N2G": {"city": "Kitchener", "province": "ON", "metro": "Waterloo Region", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N2L": {"city": "Waterloo", "province": "ON", "metro": "Waterloo Region", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N1H": {"city": "Guelph", "province": "ON", "metro": "Guelph", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N6A": {"city": "London", "province": "ON", "metro": "London", "region": "SW ON", "is_rural": False, "zone": "ON-LON"},
    "N9A": {"city": "Windsor", "province": "ON", "metro": "Windsor", "region": "SW ON", "is_rural": False, "zone": "ON-WIN"},

    # --- ONTARIO: Northern (P) ---
    "P3C": {"city": "Sudbury", "province": "ON", "metro": "Greater Sudbury", "region": "Northern ON", "is_rural": False, "zone": "ON-NOR"},
    "P7B": {"city": "Thunder Bay", "province": "ON", "metro": "Thunder Bay", "region": "NW ON", "is_rural": False, "zone": "ON-THU"},

    # --- QUEBEC: Greater Montreal (H) ---
    "H1A": {"city": "Montreal", "province": "QC", "metro": "Montreal", "region": "Montreal East", "is_rural": False, "zone": "QC-MTL"},
    "H2Y": {"city": "Montreal", "province": "QC", "metro": "Montreal", "region": "Old Montreal", "is_rural": False, "zone": "QC-MTL"},
    "H3B": {"city": "Montreal", "province": "QC", "metro": "Montreal", "region": "Downtown Montreal", "is_rural": False, "zone": "QC-MTL"},
    "H4T": {"city": "Saint-Laurent", "province": "QC", "metro": "Montreal", "region": "Industrial Hub", "is_rural": False, "zone": "QC-MTL"},
    "H9P": {"city": "Dorval", "province": "QC", "metro": "Montreal", "region": "West Island Hub", "is_rural": False, "zone": "QC-MTL"},
    "H7T": {"city": "Laval", "province": "QC", "metro": "Montreal", "region": "Laval", "is_rural": False, "zone": "QC-MTL"},

    # --- QUEBEC: Quebec City & Eastern (G) ---
    "G1K": {"city": "Quebec", "province": "QC", "metro": "Quebec City", "region": "Capitale-Nationale", "is_rural": False, "zone": "QC-QBC"},
    "G6W": {"city": "Levis", "province": "QC", "metro": "Quebec City", "region": "Chaudiere-Appalaches", "is_rural": False, "zone": "QC-QBC"},

    # --- QUEBEC: Western & Gatineau (J) ---
    "J8X": {"city": "Gatineau", "province": "QC", "metro": "Ottawa-Gatineau", "region": "Outaouais", "is_rural": False, "zone": "QC-GAT"},
    "J4B": {"city": "Boucherville", "province": "QC", "metro": "Montreal", "region": "Monteregie", "is_rural": False, "zone": "QC-MTL"},

    # --- ALBERTA (T) ---
    "T2P": {"city": "Calgary", "province": "AB", "metro": "Calgary", "region": "Downtown Calgary", "is_rural": False, "zone": "AB-CAL"},
    "T2C": {"city": "Calgary", "province": "AB", "metro": "Calgary", "region": "SE Industrial", "is_rural": False, "zone": "AB-CAL"},
    "T3Z": {"city": "Redwood Meadows", "province": "AB", "metro": "Calgary", "region": "Calgary Surrounds", "is_rural": False, "zone": "AB-CAL"},
    "T5J": {"city": "Edmonton", "province": "AB", "metro": "Edmonton", "region": "Downtown Edmonton", "is_rural": False, "zone": "AB-EDM"},
    "T6B": {"city": "Edmonton", "province": "AB", "metro": "Edmonton", "region": "East Industrial", "is_rural": False, "zone": "AB-EDM"},
    "T4N": {"city": "Red Deer", "province": "AB", "metro": "Red Deer", "region": "Central AB", "is_rural": False, "zone": "AB-RDR"},

    # --- BRITISH COLUMBIA (V) ---
    "V6B": {"city": "Vancouver", "province": "BC", "metro": "Greater Vancouver", "region": "Downtown Vancouver", "is_rural": False, "zone": "BC-VAN"},
    "V6V": {"city": "Richmond", "province": "BC", "metro": "Greater Vancouver", "region": "Freight Cargo Hub", "is_rural": False, "zone": "BC-VAN"},
    "V5J": {"city": "Burnaby", "province": "BC", "metro": "Greater Vancouver", "region": "Burnaby Industrial", "is_rural": False, "zone": "BC-VAN"},
    "V3S": {"city": "Surrey", "province": "BC", "metro": "Greater Vancouver", "region": "Surrey Logistics", "is_rural": False, "zone": "BC-VAN"},
    "V8W": {"city": "Victoria", "province": "BC", "metro": "Victoria", "region": "Vancouver Island", "is_rural": False, "zone": "BC-VIC"},
    "V1Y": {"city": "Kelowna", "province": "BC", "metro": "Kelowna", "region": "Okanagan", "is_rural": False, "zone": "BC-KEL"},

    # --- MANITOBA (R) ---
    "R3C": {"city": "Winnipeg", "province": "MB", "metro": "Winnipeg", "region": "Downtown Winnipeg", "is_rural": False, "zone": "MB-WPG"},
    "R2X": {"city": "Winnipeg", "province": "MB", "metro": "Winnipeg", "region": "Inkster Industrial", "is_rural": False, "zone": "MB-WPG"},

    # --- SASKATCHEWAN (S) ---
    "S4P": {"city": "Regina", "province": "SK", "metro": "Regina", "region": "Southern SK", "is_rural": False, "zone": "SK-REG"},
    "S7K": {"city": "Saskatoon", "province": "SK", "metro": "Saskatoon", "region": "Central SK", "is_rural": False, "zone": "SK-SAS"},

    # --- NOVA SCOTIA (B) ---
    "B3J": {"city": "Halifax", "province": "NS", "metro": "Halifax", "region": "Downtown Halifax", "is_rural": False, "zone": "NS-HFX"},
    "B3B": {"city": "Dartmouth", "province": "NS", "metro": "Halifax", "region": "Burnside Industrial", "is_rural": False, "zone": "NS-HFX"},

    # --- NEW BRUNSWICK (E) ---
    "E1C": {"city": "Moncton", "province": "NB", "metro": "Moncton", "region": "Atlantic Hub", "is_rural": False, "zone": "NB-MCT"},
    "E2L": {"city": "Saint John", "province": "NB", "metro": "Saint John", "region": "Southern NB", "is_rural": False, "zone": "NB-STJ"},

    # --- NEWFOUNDLAND & LABRADOR (A) ---
    "A1B": {"city": "St. John's", "province": "NL", "metro": "St. John's", "region": "Avalon Peninsula", "is_rural": False, "zone": "NL-STJ"},
    "A2N": {"city": "Corner Brook", "province": "NL", "metro": "Corner Brook", "region": "Western NL", "is_rural": False, "zone": "NL-WES"},

    # --- PRINCE EDWARD ISLAND (C) ---
    "C1A": {"city": "Charlottetown", "province": "PE", "metro": "Charlottetown", "region": "PEI", "is_rural": False, "zone": "PE-CHT"},

    # --- TERRITORIES (X, Y) ---
    "X1A": {"city": "Yellowknife", "province": "NT", "metro": "Yellowknife", "region": "Northwest Territories", "is_rural": True, "zone": "NT-YWK"},
    "Y1A": {"city": "Whitehorse", "province": "YT", "metro": "Whitehorse", "region": "Yukon", "is_rural": True, "zone": "YT-WHI"},
    "X0A": {"city": "Iqaluit", "province": "NU", "metro": "Iqaluit", "region": "Nunavut", "is_rural": True, "zone": "NU-IQA"},
}

# District First Letter to Province Mapping
DISTRICT_PROVINCE_MAP = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB",
    "G": "QC", "H": "QC", "J": "QC",
    "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON",
    "R": "MB", "S": "SK", "T": "AB", "V": "BC",
    "X": "NT", "Y": "YT"
}

# Province Major Hub Fallbacks
PROVINCE_HUB_MAP = {
    "ON": "TORONTO, ON",
    "QC": "MONTREAL, QC",
    "BC": "VANCOUVER, BC",
    "AB": "CALGARY, AB",
    "MB": "WINNIPEG, MB",
    "SK": "REGINA, SK",
    "NS": "HALIFAX, NS",
    "NB": "MONCTON, NB",
    "NL": "ST. JOHN'S, NL",
    "PE": "CHARLOTTETOWN, PE",
    "YT": "WHITEHORSE, YT",
    "NT": "YELLOWKNIFE, NT",
    "NU": "IQALUIT, NU"
}

def clean_postal_code(text: str) -> str:
    """Standardizes postal code by stripping whitespace and non-alphanumeric chars."""
    if not text:
        return ""
    clean = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    return clean

def extract_fsa(text: str) -> Optional[str]:
    """
    Extracts a 3-character Canadian Forward Sortation Area (FSA) pattern (e.g. M5V, T2P, H3B).
    Pattern: [Letter][Digit][Letter] (excluding D, F, I, O, Q, U as per Canada Post rules).
    """
    if not text:
        return None
    match = re.search(r"\b([A-CEGHJ-NPR-TV-Z]\d[A-CEGHJ-NPR-TV-Z])\b", text.upper())
    if match:
        return match.group(1)
    
    # Also check if text starts with FSA
    clean = clean_postal_code(text)
    if len(clean) >= 3:
        candidate = clean[:3]
        if re.match(r"^[A-CEGHJ-NPR-TV-Z]\d[A-CEGHJ-NPR-TV-Z]$", candidate):
            return candidate
            
    return None

def resolve_location(raw_input: str) -> Dict[str, Any]:
    """
    Resolves any Canadian location string, postal code, or FSA into a standardized
    freight location structure.
    
    Examples:
      - "M5V 2T6" -> {"fsa": "M5V", "city": "Toronto", "province": "ON", "location_string": "TORONTO, ON", ...}
      - "T2P" -> {"fsa": "T2P", "city": "Calgary", "province": "AB", "location_string": "CALGARY, AB", ...}
      - "Calgary, AB" -> {"city": "Calgary", "province": "AB", "location_string": "CALGARY, AB", ...}
      - "Lindsay, ON" -> {"city": "Lindsay", "province": "ON", "location_string": "LINDSAY, ON", ...}
    """
    if not raw_input or not raw_input.strip():
        return {
            "raw_input": raw_input,
            "fsa": None,
            "city": "",
            "province": "",
            "location_string": "",
            "is_rural": False,
            "zone": "",
            "is_resolved": False
        }

    raw_clean = " ".join(raw_input.strip().upper().split())
    fsa = extract_fsa(raw_clean)

    if fsa and fsa in FSA_DATABASE:
        data = FSA_DATABASE[fsa]
        city = data["city"].upper()
        prov = data["province"]
        return {
            "raw_input": raw_input,
            "fsa": fsa,
            "city": city,
            "province": prov,
            "location_string": f"{city}, {prov}",
            "metro": data.get("metro", city),
            "region": data.get("region", ""),
            "is_rural": data.get("is_rural", False),
            "zone": data.get("zone", f"{prov}-{city[:3]}"),
            "is_resolved": True
        }

    if fsa:
        # FSA exists in Canadian standard but not in top 50 table
        dist_char = fsa[0]
        prov = DISTRICT_PROVINCE_MAP.get(dist_char, "ON")
        is_rural = (fsa[1] == "0")
        hub_city = PROVINCE_HUB_MAP.get(prov, f"{prov} HUB").split(",")[0].strip()
        return {
            "raw_input": raw_input,
            "fsa": fsa,
            "city": hub_city,
            "province": prov,
            "location_string": f"{hub_city}, {prov}",
            "metro": hub_city,
            "region": "Regional District",
            "is_rural": is_rural,
            "zone": f"{prov}-{hub_city[:3]}",
            "is_resolved": True
        }

    # Standard "City, Province" or "City, Prov" check
    if "," in raw_clean:
        parts = [p.strip() for p in raw_clean.split(",", 1)]
        city = parts[0]
        prov_raw = parts[1].replace(".", "").strip()
        # Find 2-letter prov
        prov_code = None
        for p in PROVINCES:
            if prov_raw == p or prov_raw == PROVINCES[p].upper():
                prov_code = p
                break
        if not prov_code and len(prov_raw) >= 2:
            prov_code = prov_raw[:2]

        prov_code = prov_code or "ON"
        return {
            "raw_input": raw_input,
            "fsa": None,
            "city": city,
            "province": prov_code,
            "location_string": f"{city}, {prov_code}",
            "metro": city,
            "region": "",
            "is_rural": False,
            "zone": f"{prov_code}-{city[:3]}",
            "is_resolved": True
        }

    # Single city string check (e.g. "CALGARY", "TORONTO", "MONTREAL", "VANCOUVER")
    for prov, hub in PROVINCE_HUB_MAP.items():
        hub_city = hub.split(",")[0].strip().upper()
        if raw_clean == hub_city or hub_city in raw_clean:
            return {
                "raw_input": raw_input,
                "fsa": None,
                "city": hub_city,
                "province": prov,
                "location_string": f"{hub_city}, {prov}",
                "metro": hub_city,
                "region": "",
                "is_rural": False,
                "zone": f"{prov}-{hub_city[:3]}",
                "is_resolved": True
            }

    # Fallback default
    return {
        "raw_input": raw_input,
        "fsa": None,
        "city": raw_clean,
        "province": "ON",
        "location_string": f"{raw_clean}, ON",
        "metro": raw_clean,
        "region": "",
        "is_rural": False,
        "zone": "ON-GEN",
        "is_resolved": False
    }

def resolve_lane_locations(origin_raw: str, dest_raw: str) -> Tuple[str, str, Dict[str, Any]]:
    """
    Normalizes origin and destination inputs using the FSA Resolver, returning
    canonical corridor location strings suitable for tariff matching.
    """
    orig_res = resolve_location(origin_raw)
    dest_res = resolve_location(dest_raw)

    canonical_origin = orig_res["location_string"]
    canonical_dest = dest_res["location_string"]

    meta = {
        "origin_fsa": orig_res.get("fsa"),
        "origin_city": orig_res.get("city"),
        "origin_prov": orig_res.get("province"),
        "origin_zone": orig_res.get("zone"),
        "origin_is_rural": orig_res.get("is_rural", False),
        "dest_fsa": dest_res.get("fsa"),
        "dest_city": dest_res.get("city"),
        "dest_prov": dest_res.get("province"),
        "dest_zone": dest_res.get("zone"),
        "dest_is_rural": dest_res.get("is_rural", False),
        "corridor_code": f"{orig_res.get('province')}-{dest_res.get('province')}"
    }

    return canonical_origin, canonical_dest, meta
