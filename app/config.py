import re
from typing import Dict, List, Set

# Confidence thresholds
HIGH: float = 0.85   # auto-map silently
LOW: float = 0.50    # below this -> must ask the user

# File & scan limits
MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB compressed limit
ALLOWED_EXT: Set[str] = {".xlsx", ".csv"}
PREVIEW_ROWS: int = 12
MAX_SCAN_ROWS: int = 500
MAX_SCAN_COLS: int = 100

# Full load limits (post-confirmation quoting)
MAX_DATA_ROWS: int = 25000
MAX_DATA_COLS: int = 100
MAX_TOTAL_CELLS: int = 1000000


# Zip-bomb protection limits
MAX_UNCOMPRESSED_BYTES: int = 100 * 1024 * 1024  # 100 MB
MAX_ZIP_ENTRIES: int = 10000
MAX_COMPRESSION_RATIO: float = 100.0

# Synonyms for header detection
SYNONYMS: Dict[str, List[str]] = {
    "origin": [
        "origin", "orig", "from", "ship from", "pickup", "pick up",
        "pol", "origin city", "origin zip", "origin postal", "port of loading",
        "origin state", "origin st", "orig city", "orig zip", "orig state"
    ],
    "destination": [
        "destination", "dest", "to", "ship to", "consignee", "delivery",
        "pod", "dest city", "dest zip", "destination postal", "port of discharge",
        "dest state", "dest st", "destination city", "destination zip"
    ],
    "min_charge": ["min", "minimum", "min charge", "minimum charge", "mc"],
    "currency": ["currency", "cur", "ccy"],
}

# Regex patterns for weight breaks
# Handles: -45, +100, 100+, 100-499, 45 lb, 45 lbs, -45 (lbs), 45 kg, 45#, cwt, etc.
WEIGHT_BREAK_PATTERN = re.compile(
    r"^\s*(?:[-+<>]\s*)?(\d+(?:\.\d+)?)\s*(?:\+|(?:(?:\(?\s*(?:lbs?|kgs?|#|cwt)\s*\)?)))?\s*(?:[-–]\s*(\d+(?:\.\d+)?)\s*(?:lbs?|kgs?|#|cwt)?)?\s*$",
    re.I
)

# Explicit weight unit detector
WEIGHT_UNIT_REGEX = re.compile(r"\b(lbs?|kgs?|cwt)\b|#", re.I)

# Skid header patterns
SKID_HDR = re.compile(r"^\s*(\d+)\s*[- ]?(pl|plt|plts|pallets?|skids?)\s*$", re.I)
SKID_WORD = re.compile(r"\b(pallets?|skids?|plts?|pl)\b", re.I)
SKID_COUNT_COL_HDR = re.compile(r"^\s*(?:#\s*of\s*)?(?:skids?|pallets?|plts?)(?:\s*count)?\s*$", re.I)
