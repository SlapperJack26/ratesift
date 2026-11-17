"""
services/fsa_resolver_service.py
================================
Quotelytics Canadian Postal Forward Sortation Area (FSA) Resolver Service.

Provides comprehensive mapping and deterministic resolution for Canadian postal codes,
FSAs, and 150+ Canadian freight cities/hubs across all 10 provinces and 3 territories,
mapping them to canonical freight cities, provinces, FSAs, freight zones, and rural/remote classification.
"""

import re
import unicodedata
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
    "L1H": {"city": "Oshawa", "province": "ON", "metro": "Durham", "region": "GTA East", "is_rural": False, "zone": "ON-TOR"},
    "L1N": {"city": "Whitby", "province": "ON", "metro": "Durham", "region": "GTA East", "is_rural": False, "zone": "ON-TOR"},
    "L1S": {"city": "Ajax", "province": "ON", "metro": "Durham", "region": "GTA East", "is_rural": False, "zone": "ON-TOR"},
    "L1V": {"city": "Pickering", "province": "ON", "metro": "Durham", "region": "GTA East", "is_rural": False, "zone": "ON-TOR"},
    "L3R": {"city": "Markham", "province": "ON", "metro": "Toronto", "region": "York", "is_rural": False, "zone": "ON-TOR"},
    "L4B": {"city": "Richmond Hill", "province": "ON", "metro": "Toronto", "region": "York", "is_rural": False, "zone": "ON-TOR"},
    "L4K": {"city": "Concord", "province": "ON", "metro": "Toronto", "region": "Vaughan", "is_rural": False, "zone": "ON-TOR"},
    "L4L": {"city": "Woodbridge", "province": "ON", "metro": "Toronto", "region": "Vaughan", "is_rural": False, "zone": "ON-TOR"},
    "L4N": {"city": "Barrie", "province": "ON", "metro": "Barrie", "region": "Simcoe", "is_rural": False, "zone": "ON-CEN"},
    "L4T": {"city": "Mississauga", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L4W": {"city": "Mississauga", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L5T": {"city": "Mississauga", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L6H": {"city": "Oakville", "province": "ON", "metro": "Toronto", "region": "Halton", "is_rural": False, "zone": "ON-TOR"},
    "L6T": {"city": "Brampton", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L6W": {"city": "Brampton", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L6P": {"city": "Brampton", "province": "ON", "metro": "Toronto", "region": "Peel", "is_rural": False, "zone": "ON-TOR"},
    "L7E": {"city": "Bolton", "province": "ON", "metro": "Toronto", "region": "Caledon", "is_rural": False, "zone": "ON-TOR"},
    "L7L": {"city": "Burlington", "province": "ON", "metro": "Hamilton", "region": "Halton", "is_rural": False, "zone": "ON-HAM"},
    "L8H": {"city": "Hamilton", "province": "ON", "metro": "Hamilton", "region": "Hamilton", "is_rural": False, "zone": "ON-HAM"},
    "L9T": {"city": "Milton", "province": "ON", "metro": "Toronto", "region": "Halton", "is_rural": False, "zone": "ON-TOR"},
    "L2R": {"city": "St. Catharines", "province": "ON", "metro": "Niagara", "region": "Niagara", "is_rural": False, "zone": "ON-HAM"},
    "L2E": {"city": "Niagara Falls", "province": "ON", "metro": "Niagara", "region": "Niagara", "is_rural": False, "zone": "ON-HAM"},
    "L9V": {"city": "Lindsay", "province": "ON", "metro": "Kawartha Lakes", "region": "Central ON", "is_rural": False, "zone": "ON-CEN"},
    "K9V": {"city": "Lindsay", "province": "ON", "metro": "Kawartha Lakes", "region": "Kawartha", "is_rural": False, "zone": "ON-CEN"},

    # --- ONTARIO: Eastern & Ottawa (K) ---
    "K1A": {"city": "Ottawa", "province": "ON", "metro": "Ottawa", "region": "Eastern ON", "is_rural": False, "zone": "ON-OTT"},
    "K1P": {"city": "Ottawa", "province": "ON", "metro": "Ottawa", "region": "Eastern ON", "is_rural": False, "zone": "ON-OTT"},
    "K2E": {"city": "Nepean", "province": "ON", "metro": "Ottawa", "region": "Eastern ON", "is_rural": False, "zone": "ON-OTT"},
    "K6H": {"city": "Cornwall", "province": "ON", "metro": "Cornwall", "region": "Eastern ON", "is_rural": False, "zone": "ON-EAS"},
    "K7L": {"city": "Kingston", "province": "ON", "metro": "Kingston", "region": "Eastern ON", "is_rural": False, "zone": "ON-EAS"},
    "K8N": {"city": "Belleville", "province": "ON", "metro": "Belleville", "region": "Eastern ON", "is_rural": False, "zone": "ON-EAS"},
    "K9H": {"city": "Peterborough", "province": "ON", "metro": "Peterborough", "region": "Central ON", "is_rural": False, "zone": "ON-CEN"},

    # --- ONTARIO: Southwestern (N) ---
    "N1H": {"city": "Guelph", "province": "ON", "metro": "Guelph", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N1R": {"city": "Cambridge", "province": "ON", "metro": "Waterloo Region", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N2G": {"city": "Kitchener", "province": "ON", "metro": "Waterloo Region", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N2L": {"city": "Waterloo", "province": "ON", "metro": "Waterloo Region", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N3R": {"city": "Brantford", "province": "ON", "metro": "Brantford", "region": "SW ON", "is_rural": False, "zone": "ON-WAT"},
    "N4S": {"city": "Woodstock", "province": "ON", "metro": "Woodstock", "region": "SW ON", "is_rural": False, "zone": "ON-LON"},
    "N6A": {"city": "London", "province": "ON", "metro": "London", "region": "SW ON", "is_rural": False, "zone": "ON-LON"},
    "N7T": {"city": "Sarnia", "province": "ON", "metro": "Sarnia", "region": "SW ON", "is_rural": False, "zone": "ON-LON"},
    "N9A": {"city": "Windsor", "province": "ON", "metro": "Windsor", "region": "SW ON", "is_rural": False, "zone": "ON-WIN"},

    # --- ONTARIO: Northern (P) ---
    "P1B": {"city": "North Bay", "province": "ON", "metro": "North Bay", "region": "Northern ON", "is_rural": False, "zone": "ON-NOR"},
    "P3C": {"city": "Sudbury", "province": "ON", "metro": "Greater Sudbury", "region": "Northern ON", "is_rural": False, "zone": "ON-NOR"},
    "P4N": {"city": "Timmins", "province": "ON", "metro": "Timmins", "region": "Northern ON", "is_rural": False, "zone": "ON-NOR"},
    "P6A": {"city": "Sault Ste. Marie", "province": "ON", "metro": "Sault Ste. Marie", "region": "Northern ON", "is_rural": False, "zone": "ON-NOR"},
    "P7B": {"city": "Thunder Bay", "province": "ON", "metro": "Thunder Bay", "region": "NW ON", "is_rural": False, "zone": "ON-THU"},

    # --- QUEBEC: Greater Montreal (H) ---
    "H1A": {"city": "Montreal", "province": "QC", "metro": "Montreal", "region": "Montreal East", "is_rural": False, "zone": "QC-MTL"},
    "H2Y": {"city": "Montreal", "province": "QC", "metro": "Montreal", "region": "Old Montreal", "is_rural": False, "zone": "QC-MTL"},
    "H3B": {"city": "Montreal", "province": "QC", "metro": "Montreal", "region": "Downtown Montreal", "is_rural": False, "zone": "QC-MTL"},
    "H4T": {"city": "Saint-Laurent", "province": "QC", "metro": "Montreal", "region": "Industrial Hub", "is_rural": False, "zone": "QC-MTL"},
    "H8T": {"city": "Lachine", "province": "QC", "metro": "Montreal", "region": "Industrial Hub", "is_rural": False, "zone": "QC-MTL"},
    "H9P": {"city": "Dorval", "province": "QC", "metro": "Montreal", "region": "West Island Hub", "is_rural": False, "zone": "QC-MTL"},
    "H7T": {"city": "Laval", "province": "QC", "metro": "Montreal", "region": "Laval", "is_rural": False, "zone": "QC-MTL"},

    # --- QUEBEC: Quebec City & Eastern (G) ---
    "G1K": {"city": "Quebec", "province": "QC", "metro": "Quebec City", "region": "Capitale-Nationale", "is_rural": False, "zone": "QC-QBC"},
    "G6W": {"city": "Levis", "province": "QC", "metro": "Quebec City", "region": "Chaudiere-Appalaches", "is_rural": False, "zone": "QC-QBC"},
    "G9A": {"city": "Trois-Rivieres", "province": "QC", "metro": "Trois-Rivieres", "region": "Mauricie", "is_rural": False, "zone": "QC-QBC"},
    "G7H": {"city": "Chicoutimi", "province": "QC", "metro": "Saguenay", "region": "Saguenay", "is_rural": False, "zone": "QC-QBC"},

    # --- QUEBEC: Western, South Shore & Gatineau (J) ---
    "J8X": {"city": "Gatineau", "province": "QC", "metro": "Ottawa-Gatineau", "region": "Outaouais", "is_rural": False, "zone": "QC-GAT"},
    "J4B": {"city": "Boucherville", "province": "QC", "metro": "Montreal", "region": "Monteregie", "is_rural": False, "zone": "QC-MTL"},
    "J4G": {"city": "Longueuil", "province": "QC", "metro": "Montreal", "region": "Monteregie", "is_rural": False, "zone": "QC-MTL"},
    "J4Z": {"city": "Brossard", "province": "QC", "metro": "Montreal", "region": "Monteregie", "is_rural": False, "zone": "QC-MTL"},
    "J3B": {"city": "Saint-Jean-sur-Richelieu", "province": "QC", "metro": "Montreal", "region": "Monteregie", "is_rural": False, "zone": "QC-MTL"},
    "J2S": {"city": "Saint-Hyacinthe", "province": "QC", "metro": "Montreal", "region": "Monteregie", "is_rural": False, "zone": "QC-MTL"},
    "J2C": {"city": "Drummondville", "province": "QC", "metro": "Drummondville", "region": "Centre-du-Quebec", "is_rural": False, "zone": "QC-MTL"},
    "J1H": {"city": "Sherbrooke", "province": "QC", "metro": "Sherbrooke", "region": "Estrie", "is_rural": False, "zone": "QC-MTL"},

    # --- ALBERTA (T) ---
    "T2P": {"city": "Calgary", "province": "AB", "metro": "Calgary", "region": "Downtown Calgary", "is_rural": False, "zone": "AB-CAL"},
    "T2C": {"city": "Calgary", "province": "AB", "metro": "Calgary", "region": "SE Industrial", "is_rural": False, "zone": "AB-CAL"},
    "T3Z": {"city": "Redwood Meadows", "province": "AB", "metro": "Calgary", "region": "Calgary Surrounds", "is_rural": False, "zone": "AB-CAL"},
    "T4A": {"city": "Airdrie", "province": "AB", "metro": "Calgary", "region": "Calgary North", "is_rural": False, "zone": "AB-CAL"},
    "T1J": {"city": "Lethbridge", "province": "AB", "metro": "Lethbridge", "region": "Southern AB", "is_rural": False, "zone": "AB-CAL"},
    "T1A": {"city": "Medicine Hat", "province": "AB", "metro": "Medicine Hat", "region": "Southern AB", "is_rural": False, "zone": "AB-CAL"},
    "T5J": {"city": "Edmonton", "province": "AB", "metro": "Edmonton", "region": "Downtown Edmonton", "is_rural": False, "zone": "AB-EDM"},
    "T6B": {"city": "Edmonton", "province": "AB", "metro": "Edmonton", "region": "East Industrial", "is_rural": False, "zone": "AB-EDM"},
    "T9E": {"city": "Leduc", "province": "AB", "metro": "Edmonton", "region": "Nisku Industrial", "is_rural": False, "zone": "AB-EDM"},
    "T8A": {"city": "Sherwood Park", "province": "AB", "metro": "Edmonton", "region": "Strathcona", "is_rural": False, "zone": "AB-EDM"},
    "T4N": {"city": "Red Deer", "province": "AB", "metro": "Red Deer", "region": "Central AB", "is_rural": False, "zone": "AB-RDR"},
    "T8V": {"city": "Grande Prairie", "province": "AB", "metro": "Grande Prairie", "region": "Northern AB", "is_rural": False, "zone": "AB-EDM"},
    "T9H": {"city": "Fort McMurray", "province": "AB", "metro": "Fort McMurray", "region": "Northern AB", "is_rural": False, "zone": "AB-EDM"},

    # --- BRITISH COLUMBIA (V) ---
    "V6B": {"city": "Vancouver", "province": "BC", "metro": "Greater Vancouver", "region": "Downtown Vancouver", "is_rural": False, "zone": "BC-VAN"},
    "V6V": {"city": "Richmond", "province": "BC", "metro": "Greater Vancouver", "region": "Freight Cargo Hub", "is_rural": False, "zone": "BC-VAN"},
    "V5J": {"city": "Burnaby", "province": "BC", "metro": "Greater Vancouver", "region": "Burnaby Industrial", "is_rural": False, "zone": "BC-VAN"},
    "V3S": {"city": "Surrey", "province": "BC", "metro": "Greater Vancouver", "region": "Surrey Logistics", "is_rural": False, "zone": "BC-VAN"},
    "V4G": {"city": "Delta", "province": "BC", "metro": "Greater Vancouver", "region": "Tilbury Industrial", "is_rural": False, "zone": "BC-VAN"},
    "V3M": {"city": "New Westminster", "province": "BC", "metro": "Greater Vancouver", "region": "Metro Vancouver", "is_rural": False, "zone": "BC-VAN"},
    "V3K": {"city": "Coquitlam", "province": "BC", "metro": "Greater Vancouver", "region": "Tri-Cities", "is_rural": False, "zone": "BC-VAN"},
    "V2Y": {"city": "Langley", "province": "BC", "metro": "Greater Vancouver", "region": "Fraser Valley", "is_rural": False, "zone": "BC-VAN"},
    "V2S": {"city": "Abbotsford", "province": "BC", "metro": "Abbotsford", "region": "Fraser Valley", "is_rural": False, "zone": "BC-VAN"},
    "V8W": {"city": "Victoria", "province": "BC", "metro": "Victoria", "region": "Vancouver Island", "is_rural": False, "zone": "BC-VIC"},
    "V9R": {"city": "Nanaimo", "province": "BC", "metro": "Nanaimo", "region": "Vancouver Island", "is_rural": False, "zone": "BC-VIC"},
    "V1Y": {"city": "Kelowna", "province": "BC", "metro": "Kelowna", "region": "Okanagan", "is_rural": False, "zone": "BC-KEL"},
    "V2C": {"city": "Kamloops", "province": "BC", "metro": "Kamloops", "region": "Thompson", "is_rural": False, "zone": "BC-KEL"},
    "V2L": {"city": "Prince George", "province": "BC", "metro": "Prince George", "region": "Northern BC", "is_rural": False, "zone": "BC-VAN"},

    # --- MANITOBA (R) ---
    "R3C": {"city": "Winnipeg", "province": "MB", "metro": "Winnipeg", "region": "Downtown Winnipeg", "is_rural": False, "zone": "MB-WPG"},
    "R2X": {"city": "Winnipeg", "province": "MB", "metro": "Winnipeg", "region": "Inkster Industrial", "is_rural": False, "zone": "MB-WPG"},
    "R7A": {"city": "Brandon", "province": "MB", "metro": "Brandon", "region": "Western MB", "is_rural": False, "zone": "MB-WPG"},

    # --- SASKATCHEWAN (S) ---
    "S4P": {"city": "Regina", "province": "SK", "metro": "Regina", "region": "Southern SK", "is_rural": False, "zone": "SK-REG"},
    "S7K": {"city": "Saskatoon", "province": "SK", "metro": "Saskatoon", "region": "Central SK", "is_rural": False, "zone": "SK-SAS"},
    "S6H": {"city": "Moose Jaw", "province": "SK", "metro": "Moose Jaw", "region": "Southern SK", "is_rural": False, "zone": "SK-REG"},
    "S6V": {"city": "Prince Albert", "province": "SK", "metro": "Prince Albert", "region": "Northern SK", "is_rural": False, "zone": "SK-SAS"},

    # --- NOVA SCOTIA (B) ---
    "B3J": {"city": "Halifax", "province": "NS", "metro": "Halifax", "region": "Downtown Halifax", "is_rural": False, "zone": "NS-HFX"},
    "B3B": {"city": "Dartmouth", "province": "NS", "metro": "Halifax", "region": "Burnside Industrial", "is_rural": False, "zone": "NS-HFX"},
    "B2N": {"city": "Truro", "province": "NS", "metro": "Truro", "region": "Central NS", "is_rural": False, "zone": "NS-HFX"},
    "B1P": {"city": "Sydney", "province": "NS", "metro": "Cape Breton", "region": "Cape Breton", "is_rural": False, "zone": "NS-HFX"},

    # --- NEW BRUNSWICK (E) ---
    "E1C": {"city": "Moncton", "province": "NB", "metro": "Moncton", "region": "Atlantic Hub", "is_rural": False, "zone": "NB-MCT"},
    "E1A": {"city": "Dieppe", "province": "NB", "metro": "Moncton", "region": "Atlantic Hub", "is_rural": False, "zone": "NB-MCT"},
    "E2L": {"city": "Saint John", "province": "NB", "metro": "Saint John", "region": "Southern NB", "is_rural": False, "zone": "NB-STJ"},
    "E3B": {"city": "Fredericton", "province": "NB", "metro": "Fredericton", "region": "Central NB", "is_rural": False, "zone": "NB-MCT"},

    # --- NEWFOUNDLAND & LABRADOR (A) ---
    "A1B": {"city": "St. John's", "province": "NL", "metro": "St. John's", "region": "Avalon Peninsula", "is_rural": False, "zone": "NL-STJ"},
    "A1N": {"city": "Mount Pearl", "province": "NL", "metro": "St. John's", "region": "Avalon Industrial", "is_rural": False, "zone": "NL-STJ"},
    "A2N": {"city": "Corner Brook", "province": "NL", "metro": "Corner Brook", "region": "Western NL", "is_rural": False, "zone": "NL-WES"},

    # --- PRINCE EDWARD ISLAND (C) ---
    "C1A": {"city": "Charlottetown", "province": "PE", "metro": "Charlottetown", "region": "PEI", "is_rural": False, "zone": "PE-CHT"},
    "C1N": {"city": "Summerside", "province": "PE", "metro": "Summerside", "region": "PEI West", "is_rural": False, "zone": "PE-CHT"},

    # --- TERRITORIES (X, Y) ---
    "X1A": {"city": "Yellowknife", "province": "NT", "metro": "Yellowknife", "region": "Northwest Territories", "is_rural": True, "zone": "NT-YWK"},
    "Y1A": {"city": "Whitehorse", "province": "YT", "metro": "Whitehorse", "region": "Yukon", "is_rural": True, "zone": "YT-WHI"},
    "X0A": {"city": "Iqaluit", "province": "NU", "metro": "Iqaluit", "region": "Nunavut", "is_rural": True, "zone": "NU-IQA"},
}

# Comprehensive Canadian City / Municipality / Shorthand -> Canonical FSA Map
# Used when carrier spreadsheets or shipper emails specify city names instead of postal codes.
CANADIAN_CITY_TO_FSA_MAP: Dict[str, str] = {
    # Ontario
    "TORONTO": "M5V", "GTA": "M5V", "YYZ": "L5T", "ETOBICOKE": "M9W", "SCARBOROUGH": "M1P",
    "NORTH YORK": "M3J", "EAST YORK": "M4B", "MISSISSAUGA": "L5T", "BRAMPTON": "L6T",
    "VAUGHAN": "L4K", "CONCORD": "L4K", "WOODBRIDGE": "L4L", "MARKHAM": "L3R",
    "RICHMOND HILL": "L4B", "OAKVILLE": "L6H", "BURLINGTON": "L7L", "MILTON": "L9T",
    "HAMILTON": "L8H", "STONEY CREEK": "L8H", "ANCASTER": "L8H", "BOLTON": "L7E",
    "CALEDON": "L7E", "PICKERING": "L1V", "AJAX": "L1S", "WHITBY": "L1N", "OSHAWA": "L1H",
    "BARRIE": "L4N", "LINDSAY": "K9V", "KAWARTHA LAKES": "K9V", "PETERBOROUGH": "K9H",
    "KINGSTON": "K7L", "BELLEVILLE": "K8N", "CORNWALL": "K6H", "OTTAWA": "K1P",
    "NEPEAN": "K2E", "KANATA": "K2E", "GUELPH": "N1H", "CAMBRIDGE": "N1R",
    "KITCHENER": "N2G", "WATERLOO": "N2L", "BRANTFORD": "N3R", "WOODSTOCK": "N4S",
    "LONDON": "N6A", "SARNIA": "N7T", "WINDSOR": "N9A", "ST CATHARINES": "L2R",
    "ST. CATHARINES": "L2R", "NIAGARA FALLS": "L2E", "SUDBURY": "P3C", "NORTH BAY": "P1B",
    "TIMMINS": "P4N", "SAULT STE MARIE": "P6A", "SAULT STE. MARIE": "P6A", "THUNDER BAY": "P7B",
    # Quebec
    "MONTREAL": "H3B", "MTL": "H3B", "YUL": "H9P", "SAINT LAURENT": "H4T", "SAINT-LAURENT": "H4T",
    "ST LAURENT": "H4T", "ST-LAURENT": "H4T", "DORVAL": "H9P", "LACHINE": "H8T",
    "LAVAL": "H7T", "BOUCHERVILLE": "J4B", "LONGUEUIL": "J4G", "BROSSARD": "J4Z",
    "SAINT JEAN SUR RICHELIEU": "J3B", "SAINT-JEAN-SUR-RICHELIEU": "J3B", "ST JEAN SUR RICHELIEU": "J3B",
    "SAINT HYACINTHE": "J2S", "SAINT-HYACINTHE": "J2S", "DRUMMONDVILLE": "J2C",
    "SHERBROOKE": "J1H", "GATINEAU": "J8X", "QUEBEC": "G1K", "QUEBEC CITY": "G1K",
    "VILLE DE QUEBEC": "G1K", "LEVIS": "G6W", "TROIS RIVIERES": "G9A", "TROIS-RIVIERES": "G9A",
    "CHICOUTIMI": "G7H", "SAGUENAY": "G7H",
    # Alberta
    "CALGARY": "T2P", "CGY": "T2P", "YYC": "T2P", "AIRDRIE": "T4A", "REDWOOD MEADOWS": "T3Z",
    "EDMONTON": "T5J", "EDM": "T5J", "YEG": "T5J", "NISKU": "T9E", "LEDUC": "T9E",
    "SHERWOOD PARK": "T8A", "RED DEER": "T4N", "LETHBRIDGE": "T1J", "MEDICINE HAT": "T1A",
    "GRANDE PRAIRIE": "T8V", "FORT MCMURRAY": "T9H",
    # British Columbia
    "VANCOUVER": "V6B", "VAN": "V6B", "YVR": "V6V", "RICHMOND": "V6V", "BURNABY": "V5J",
    "SURREY": "V3S", "DELTA": "V4G", "NEW WESTMINSTER": "V3M", "COQUITLAM": "V3K",
    "LANGLEY": "V2Y", "ABBOTSFORD": "V2S", "VICTORIA": "V8W", "NANAIMO": "V9R",
    "KELOWNA": "V1Y", "KAMLOOPS": "V2C", "PRINCE GEORGE": "V2L",
    # Manitoba & Saskatchewan
    "WINNIPEG": "R3C", "WPG": "R3C", "YWG": "R3C", "BRANDON": "R7A",
    "REGINA": "S4P", "YQR": "S4P", "SASKATOON": "S7K", "YXE": "S7K",
    "MOOSE JAW": "S6H", "PRINCE ALBERT": "S6V",
    # Atlantic Canada & Territories
    "HALIFAX": "B3J", "HAL": "B3J", "YHZ": "B3J", "DARTMOUTH": "B3B", "BURNSIDE": "B3B",
    "TRURO": "B2N", "SYDNEY": "B1P", "MONCTON": "E1C", "DIEPPE": "E1A",
    "SAINT JOHN": "E2L", "FREDERICTON": "E3B", "ST JOHNS": "A1B", "ST. JOHN'S": "A1B",
    "MOUNT PEARL": "A1N", "CORNER BROOK": "A2N", "CHARLOTTETOWN": "C1A", "SUMMERSIDE": "C1N",
    "YELLOWKNIFE": "X1A", "WHITEHORSE": "Y1A", "IQALUIT": "X0A",
}

# Cross-Border US Major LTL Freight Hubs (ZIP3 & 5-Digit ZIP Support)
US_CROSS_BORDER_ZIP3_DATABASE: Dict[str, Dict[str, Any]] = {
    "606": {"city": "Chicago", "province": "IL", "country": "US", "zone": "US-MW-CHI"},
    "600": {"city": "Elk Grove Village", "province": "IL", "country": "US", "zone": "US-MW-CHI"},
    "482": {"city": "Detroit", "province": "MI", "country": "US", "zone": "US-MW-DET"},
    "481": {"city": "Romulus", "province": "MI", "country": "US", "zone": "US-MW-DET"},
    "142": {"city": "Buffalo", "province": "NY", "country": "US", "zone": "US-NE-BUF"},
    "088": {"city": "Edison", "province": "NJ", "country": "US", "zone": "US-NE-NYC"},
    "071": {"city": "Newark", "province": "NJ", "country": "US", "zone": "US-NE-NYC"},
    "100": {"city": "New York", "province": "NY", "country": "US", "zone": "US-NE-NYC"},
    "191": {"city": "Philadelphia", "province": "PA", "country": "US", "zone": "US-NE-PHL"},
    "021": {"city": "Boston", "province": "MA", "country": "US", "zone": "US-NE-BOS"},
    "441": {"city": "Cleveland", "province": "OH", "country": "US", "zone": "US-MW-CLE"},
    "432": {"city": "Columbus", "province": "OH", "country": "US", "zone": "US-MW-COL"},
    "452": {"city": "Cincinnati", "province": "OH", "country": "US", "zone": "US-MW-CIN"},
    "462": {"city": "Indianapolis", "province": "IN", "country": "US", "zone": "US-MW-IND"},
    "532": {"city": "Milwaukee", "province": "WI", "country": "US", "zone": "US-MW-MKE"},
    "554": {"city": "Minneapolis", "province": "MN", "country": "US", "zone": "US-MW-MSP"},
    "631": {"city": "St. Louis", "province": "MO", "country": "US", "zone": "US-MW-STL"},
    "303": {"city": "Atlanta", "province": "GA", "country": "US", "zone": "US-SE-ATL"},
    "282": {"city": "Charlotte", "province": "NC", "country": "US", "zone": "US-SE-CLT"},
    "381": {"city": "Memphis", "province": "TN", "country": "US", "zone": "US-SE-MEM"},
    "372": {"city": "Nashville", "province": "TN", "country": "US", "zone": "US-SE-BNA"},
    "331": {"city": "Miami", "province": "FL", "country": "US", "zone": "US-SE-MIA"},
    "752": {"city": "Dallas", "province": "TX", "country": "US", "zone": "US-SW-DFW"},
    "770": {"city": "Houston", "province": "TX", "country": "US", "zone": "US-SW-HOU"},
    "780": {"city": "Laredo", "province": "TX", "country": "US", "zone": "US-SW-LRD"},
    "802": {"city": "Denver", "province": "CO", "country": "US", "zone": "US-WE-DEN"},
    "850": {"city": "Phoenix", "province": "AZ", "country": "US", "zone": "US-WE-PHX"},
    "900": {"city": "Los Angeles", "province": "CA", "country": "US", "zone": "US-WE-LAX"},
    "917": {"city": "Ontario", "province": "CA", "country": "US", "zone": "US-WE-LAX"},
    "946": {"city": "Oakland", "province": "CA", "country": "US", "zone": "US-WE-SFO"},
    "981": {"city": "Seattle", "province": "WA", "country": "US", "zone": "US-NW-SEA"},
    "972": {"city": "Portland", "province": "OR", "country": "US", "zone": "US-NW-PDX"},
}

US_CITY_TO_ZIP3_MAP: Dict[str, str] = {
    "CHICAGO": "606", "DETROIT": "482", "BUFFALO": "142", "EDISON": "088",
    "NEWARK": "071", "NEW YORK": "100", "PHILADELPHIA": "191", "BOSTON": "021",
    "CLEVELAND": "441", "COLUMBUS": "432", "CINCINNATI": "452", "INDIANAPOLIS": "462",
    "MILWAUKEE": "532", "MINNEAPOLIS": "554", "ST LOUIS": "631", "ST. LOUIS": "631",
    "ATLANTA": "303", "CHARLOTTE": "282", "MEMPHIS": "381", "NASHVILLE": "372",
    "MIAMI": "331", "DALLAS": "752", "HOUSTON": "770", "LAREDO": "780",
    "DENVER": "802", "PHOENIX": "850", "LOS ANGELES": "900", "SEATTLE": "981",
    "PORTLAND": "972",
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


def strip_accents(text: str) -> str:
    """Removes French/diacritic accents (e.g. Montréal -> Montreal, Lévis -> Levis)."""
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text))
        if unicodedata.category(c) != "Mn"
    )


def clean_postal_code(text: str) -> str:
    """Standardizes postal code by stripping whitespace and non-alphanumeric chars."""
    if not text:
        return ""
    clean = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    return clean


def resolve_city_to_fsa(text: str) -> Optional[str]:
    """
    Resolves a Canadian city name, municipality, or freight hub shorthand
    (e.g. 'Mississauga, ON', 'Montréal', 'Brampton', 'WPG', 'Calgary AB') to its canonical 3-char FSA.
    """
    if not text:
        return None
    norm = strip_accents(text).upper().strip()
    # Strip trailing province code like ", ON" or " ON" or "(ON)"
    norm_city = re.sub(r"[\(\),\.\-]+", " ", norm)
    norm_city = " ".join(norm_city.split())

    if norm_city in CANADIAN_CITY_TO_FSA_MAP:
        return CANADIAN_CITY_TO_FSA_MAP[norm_city]

    # Try stripping trailing 2-letter province or full province name
    for prov_code, prov_name in PROVINCES.items():
        for suffix in (f" {prov_code}", f" {prov_name.upper()}"):
            if norm_city.endswith(suffix):
                candidate = norm_city[: -len(suffix)].strip()
                if candidate in CANADIAN_CITY_TO_FSA_MAP:
                    return CANADIAN_CITY_TO_FSA_MAP[candidate]

    # Substring match for multi-word inputs like "PORT OF MONTREAL" or "MISSISSAUGA TERMINAL"
    for city_key, fsa_val in sorted(CANADIAN_CITY_TO_FSA_MAP.items(), key=lambda x: -len(x[0])):
        if len(city_key) >= 4 and re.search(rf"\b{re.escape(city_key)}\b", norm_city):
            return fsa_val

    return None


def extract_fsa(text: str) -> Optional[str]:
    """
    Extracts a 3-character Canadian Forward Sortation Area (FSA) pattern (e.g. M5V, T2P, H3B),
    or resolves a known Canadian city name to its canonical FSA.
    Pattern: [Letter][Digit][Letter] (excluding D, F, I, O, Q, U as per Canada Post rules).
    """
    if not text:
        return None
    upper_text = strip_accents(text).upper()
    # 1. Explicit 6-char postal code (with or without space) e.g. M5V 2T6 or M5V2T6
    match_6 = re.search(r"\b([A-CEGHJ-NPR-TV-Z]\d[A-CEGHJ-NPR-TV-Z])\s*\d[A-CEGHJ-NPR-TV-Z]\d\b", upper_text)
    if match_6:
        return match_6.group(1)

    # 2. Explicit 3-char FSA token
    match = re.search(r"\b([A-CEGHJ-NPR-TV-Z]\d[A-CEGHJ-NPR-TV-Z])\b", upper_text)
    if match:
        return match.group(1)

    # 3. Starts with 3-char FSA
    clean = clean_postal_code(upper_text)
    if len(clean) in (3, 6):
        candidate = clean[:3]
        if re.match(r"^[A-CEGHJ-NPR-TV-Z]\d[A-CEGHJ-NPR-TV-Z]$", candidate):
            return candidate

    # 4. Fallback: Resolve Canadian city name to canonical FSA
    cdn_city_fsa = resolve_city_to_fsa(upper_text)
    if cdn_city_fsa:
        return cdn_city_fsa

    # 5. Cross-Border US 5-Digit ZIP (e.g. 60601 or 60601-1234) or US City Name -> 3-digit ZIP3
    zip5 = re.search(r"\b(\d{3})\d{2}(?:-\d{4})?\b", upper_text)
    if zip5:
        return zip5.group(1)
    if re.match(r"^\d{3}$", upper_text.strip()):
        return upper_text.strip()
    for us_city, zip3 in US_CITY_TO_ZIP3_MAP.items():
        if re.search(rf"\b{re.escape(us_city)}\b", upper_text):
            return zip3
    return None


def resolve_location(raw_input: str) -> Dict[str, Any]:
    """
    Resolves any Canadian location string, postal code, FSA, city name, or US Cross-Border ZIP
    into a standardized freight location structure with canonical FSA/ZIP3 populated.
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

    raw_clean = " ".join(strip_accents(raw_input).strip().upper().split())
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
            "country": "CA",
            "location_string": f"{city}, {prov}",
            "metro": data.get("metro", city),
            "region": data.get("region", ""),
            "is_rural": data.get("is_rural", False),
            "zone": data.get("zone", f"{prov}-{city[:3]}"),
            "is_resolved": True
        }

    if fsa and fsa in US_CROSS_BORDER_ZIP3_DATABASE:
        us_data = US_CROSS_BORDER_ZIP3_DATABASE[fsa]
        city = us_data["city"].upper()
        state = us_data["province"]
        return {
            "raw_input": raw_input,
            "fsa": fsa,
            "city": city,
            "province": state,
            "country": "US",
            "is_cross_border": True,
            "location_string": f"{city}, {state}",
            "metro": city,
            "region": "US Cross-Border",
            "is_rural": False,
            "zone": us_data["zone"],
            "is_resolved": True
        }

    if fsa:
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
        prov_code = None
        for p in PROVINCES:
            if prov_raw == p or prov_raw == PROVINCES[p].upper():
                prov_code = p
                break
        if not prov_code and len(prov_raw) >= 2:
            prov_code = prov_raw[:2]

        prov_code = prov_code or "ON"
        mapped_fsa = resolve_city_to_fsa(city)
        return {
            "raw_input": raw_input,
            "fsa": mapped_fsa,
            "city": city,
            "province": prov_code,
            "location_string": f"{city}, {prov_code}",
            "metro": city,
            "region": "",
            "is_rural": False,
            "zone": f"{prov_code}-{city[:3]}",
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


def detect_canadian_corridor_warnings(origin_raw: str, dest_raw: str) -> Dict[str, Any]:
    """
    Detects specialized Canadian LTL geographical surcharge triggers:
    1. Rural / Beyond-Point FSAs (2nd character of Canadian FSA is '0', e.g. T0J, B0P, V0J, P0M)
    2. Vancouver Island Ferry Corridors (V8A–V9Z Victoria / Nanaimo / Campbell River)
    3. Newfoundland Gulf Ferry Corridors (A0A–A9Z crossing Cabot Strait)
    4. Northern / Winter Road Corridors (X0/X1 NWT/Nunavut, Y0/Y1 Yukon)
    """
    orig = resolve_location(origin_raw)
    dest = resolve_location(dest_raw)
    orig_fsa = (orig.get("fsa") or "").upper()
    dest_fsa = (dest.get("fsa") or "").upper()

    warnings: List[Dict[str, Any]] = []
    recommended_surcharges: List[str] = []

    # 1. Rural '0'-Digit FSA Beyond-Point Check
    orig_rural = len(orig_fsa) == 3 and orig_fsa[0].isalpha() and orig_fsa[1] == "0"
    dest_rural = len(dest_fsa) == 3 and dest_fsa[0].isalpha() and dest_fsa[1] == "0"
    if orig_rural or dest_rural:
        rural_codes = [c for c, is_r in ((orig_fsa, orig_rural), (dest_fsa, dest_rural)) if is_r]
        warnings.append({
            "code": "RURAL_BEYOND_POINT_FSA",
            "title": f"Rural / Beyond-Point FSA Detected ({', '.join(rural_codes)})",
            "estimated_surcharge_cad": 65.0,
            "message": (
                f"Canada Post '0'-digit rural FSA ({', '.join(rural_codes)}) typically triggers a "
                f"$45–$125 CAD Carrier Beyond-Point / Interline surcharge."
            ),
        })
        recommended_surcharges.append("rural_beyond")

    # 2. Vancouver Island Ferry Check (V8 / V9)
    orig_vi = orig_fsa.startswith(("V8", "V9"))
    dest_vi = dest_fsa.startswith(("V8", "V9"))
    if orig_vi != dest_vi:
        warnings.append({
            "code": "BC_VANCOUVER_ISLAND_FERRY",
            "title": "Vancouver Island Marine Ferry Corridor (V8/V9)",
            "estimated_surcharge_cad": 95.0,
            "message": "Crossing between mainland and Vancouver Island (V8/V9) requires a BC Ferries LTL Marine Surcharge.",
        })
        recommended_surcharges.append("bc_ferry")

    # 3. Newfoundland Gulf Ferry Check (A0–A9)
    orig_nl = orig_fsa.startswith("A") and orig.get("province") == "NL"
    dest_nl = dest_fsa.startswith("A") and dest.get("province") == "NL"
    if orig_nl != dest_nl:
        warnings.append({
            "code": "NL_CABOT_STRAIT_FERRY",
            "title": "Newfoundland Marine Atlantic Ferry Corridor",
            "estimated_surcharge_cad": 185.0,
            "message": "Over-the-road LTL to/from Newfoundland (A-prefix FSA) incurs a Marine Atlantic Gulf Ferry surcharge.",
        })
        recommended_surcharges.append("nl_ferry")

    # 4. Northern Territory Corridor (X / Y)
    if orig_fsa.startswith(("X", "Y")) or dest_fsa.startswith(("X", "Y")):
        warnings.append({
            "code": "NORTHERN_TERRITORY_CORRIDOR",
            "title": "Northern Territory / Remote Corridor (YT / NT / NU)",
            "estimated_surcharge_cad": 150.0,
            "message": "Northern territorial lane—verify seasonal weight restrictions and remote beyond-point rates.",
        })
        recommended_surcharges.append("northern_remote")

    return {
        "origin_fsa": orig_fsa,
        "dest_fsa": dest_fsa,
        "has_corridor_warnings": len(warnings) > 0,
        "warnings": warnings,
        "recommended_surcharges": recommended_surcharges,
    }
