"""
Unified break-header and column-header parser shared by:
- app/detect.py (failsafe detector & mapping validator)
- services/ratesift_extractor.py (deep tariff extractor)
- services/ratesift_excel_reformatter.py (excel reformatter)

Guarantees 100% parity between failsafe header detection and tariff extraction.
"""
from dataclasses import dataclass
import re
from typing import Any, List, Optional, Tuple

WEIGHT_UNIT_REGEX = re.compile(r"\b(lbs?|kgs?|cwt)\b|#", re.I)

# Headers that contain rate/unit words but must NEVER be treated as a weight break
NON_BREAK_HEADERS = {
    "rate per cwt",
    "rates per cwt",
    "$/cwt",
    "$ / cwt",
    "cwt rate",
    "cwt rates",
    "rate/cwt",
    "rate",
    "rates",
    "cwt",
    "lb",
    "lbs",
    "kg",
    "kgs",
    "weight",
    "weight break",
    "weight breaks",
    "break",
    "breaks",
    "min",
    "minimum",
    "min charge",
    "minimum charge",
    "mc",
    "base",
    "base cost",
    "base charge",
    "flat",
    "flat rate",
    "origin",
    "orig",
    "from",
    "ship from",
    "destination",
    "dest",
    "to",
    "ship to",
    "zone",
    "transit",
    "transit days",
    "days",
    "service",
    "notes",
    "status",
    "currency",
    "direction",
    "opr",
    "dpr",
    "dcounty",
}


@dataclass
class ParsedBreak:
    raw_header: str
    break_name: str
    min_weight: float
    max_weight: Optional[float]
    is_open_ended: bool
    break_value: float
    unit: Optional[str] = None
    is_under: bool = False
    kind: str = "weight"  # "weight" or "skid"

    @property
    def min_val(self) -> float:
        return self.min_weight

    @property
    def max_val(self) -> Optional[float]:
        return self.max_weight


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def detect_unit_in_header(raw: str) -> Optional[str]:
    """Extracts canonical weight unit ('lb' or 'kg') if explicitly present in header text."""
    u_match = WEIGHT_UNIT_REGEX.search(raw)
    if u_match:
        matched = u_match.group(0).lower()
        return "lb" if matched in ("lb", "lbs", "#", "cwt") else "kg"
    return None


def is_numeric_range_header(raw: Any) -> bool:
    """
    Returns True if the header represents a numeric range (e.g. '1,000 to 1,999 lbs' or '500-999').
    Used to prevent 'to' inside a range header from being scored as a Destination column.
    """
    s = _s(raw)
    if not s:
        return False
    decomma = re.sub(r"(?<=\d),(?=\d)", "", s)
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:[-–]|to)\s*\d+(?:\.\d+)?", decomma, re.I))


def parse_break_header(
    h: Any,
    mode_hint: Optional[str] = None,
    rating_basis: Optional[str] = None,
) -> Optional[ParsedBreak]:
    """
    Parses a spreadsheet column header into a structured ParsedBreak.

    Supported formats:
    - Canadian/US LTL codes: L5C (0..499), M5C (500+), M1M (1000+), M2M (2000+), M5M (5000+), M10M (10000+)
    - Range headers with commas/hyphens/'to': '1,000 to 1,999 lbs', '500-999', '100 - 499 kg'
    - Leading hyphen / less-than ('under' syntax): '-45', '<45', 'Under 45 lbs' -> (0..45, break_value=45)
    - Colon/label prefixes: 'CWT:2000', 'CWT: 1,000', 'WT:500'
    - Plus / open-ended syntax: '+100', '100+', '10,000+ lbs'
    - Unit-suffixed or numeric headers: '45 lb', '45#', '500 kgs', 100
    - Explicitly rejects rate-unit labels like 'Rate per CWT', '$/CWT', 'Min', 'To'.
    """
    if mode_hint is None and rating_basis:
        if rating_basis.upper() in ("WEIGHT_CWT", "WEIGHT"):
            mode_hint = "weight"
        elif rating_basis.upper() in ("PER_SKID", "PALLET_TIER", "SKID"):
            mode_hint = "skid"

    raw = _s(h)
    if not raw:
        return None

    norm_lower = " ".join(raw.lower().split())
    if norm_lower in NON_BREAK_HEADERS:
        return None

    # Reject any header that has no digits and isn't a recognized LTL code
    if not re.search(r"\d", raw):
        return None

    # Reject prose headers like "Rate per CWT" or "Charge per 100 lbs" if they aren't actual break headers
    if re.search(r"\b(?:rate|charge|cost|price)s?\s+per\b", norm_lower):
        return None

    # If explicitly a skid/pallet header (e.g. "1 PL", "2 SKIDS"), do not classify as weight break
    if mode_hint != "weight" and re.match(
        r"^\s*\d+\s*(?:[-–]|to)?\s*\d*\s*[- ]?(?:pl|plt|plts|pallets?|skids?|skd)\s*$",
        raw,
        re.I,
    ):
        return None

    unit = detect_unit_in_header(raw)
    upper_clean = raw.strip().upper()

    # 1. Standard Canadian/US LTL CWT codes: L5C, M5C, M1M, M2M, M5M, M10M
    m_lc = re.match(r"^L(\d+)C$", upper_clean)
    if m_lc:
        n = int(m_lc.group(1))
        cap = float(n * 100 - 1)
        return ParsedBreak(
            raw_header=raw,
            break_name=upper_clean,
            min_weight=0.0,
            max_weight=cap,
            is_open_ended=False,
            break_value=cap,
            unit=unit,
            is_under=True,
        )

    m_mc = re.match(r"^M(\d+)C$", upper_clean)
    if m_mc:
        val = float(int(m_mc.group(1)) * 100)
        return ParsedBreak(
            raw_header=raw,
            break_name=upper_clean,
            min_weight=val,
            max_weight=None,
            is_open_ended=True,
            break_value=val,
            unit=unit,
        )

    m_mm = re.match(r"^M(\d+)M$", upper_clean)
    if m_mm:
        val = float(int(m_mm.group(1)) * 1000)
        return ParsedBreak(
            raw_header=raw,
            break_name=upper_clean,
            min_weight=val,
            max_weight=None,
            is_open_ended=True,
            break_value=val,
            unit=unit,
        )

    # Also support weight mode 5C, 1M, 2M, 5M, 10M when mode_hint == "weight"
    if mode_hint == "weight":
        m_c_only = re.match(r"^(\d+)C$", upper_clean)
        if m_c_only:
            val = float(int(m_c_only.group(1)) * 100)
            return ParsedBreak(
                raw_header=raw,
                break_name=upper_clean,
                min_weight=val,
                max_weight=None,
                is_open_ended=True,
                break_value=val,
                unit=unit,
            )
        m_m_only = re.match(r"^(\d+)M$", upper_clean)
        if m_m_only:
            val = float(int(m_m_only.group(1)) * 1000)
            return ParsedBreak(
                raw_header=raw,
                break_name=upper_clean,
                min_weight=val,
                max_weight=None,
                is_open_ended=True,
                break_value=val,
                unit=unit,
            )

    # Remove thousands-separator commas between digits (e.g., "1,000" -> "1000")
    decomma = re.sub(r"(?<=\d),(?=\d)", "", raw).strip()

    # Strip known prefixes like "CWT:", "WT:", "Weight Break:", "Rate:", "LTL:"
    # Preserve leading '-', '+', '<', '>' on the number itself!
    stripped = re.sub(
        r"^\s*(?:cwt|wt|weight(?:\s*breaks?)?|breaks?|rates?|ltl(?:\s*rates?)?(?:\s*\([^)]*\))?)\s*[:\-]?\s*",
        "",
        decomma,
        flags=re.I,
    ).strip()

    # Wait: if the original started with "-45", the regex above must not strip the leading "-"!
    # Check if decomma started with '-' or '<'
    if decomma.startswith("-") or decomma.startswith("<"):
        stripped = decomma

    # 2. Explicit Range: "500-999", "1000 to 1999 lbs", "100 - 499 (kg)"
    m_range = re.match(
        r"^(\d+(?:\.\d+)?)\s*(?:lbs?|kgs?|#|cwt)?\s*(?:[-–]|\bto\b)\s*(\d+(?:\.\d+)?)\s*(?:\(?\s*(?:lbs?|kgs?|#|cwt)\s*\)?)?$",
        stripped,
        re.I,
    )
    if m_range:
        v1 = float(m_range.group(1))
        v2 = float(m_range.group(2))
        if v2 >= v1:
            return ParsedBreak(
                raw_header=raw,
                break_name=raw,
                min_weight=v1,
                max_weight=v2,
                is_open_ended=False,
                break_value=v1,
                unit=unit,
            )

    # 3. Leading Hyphen / Less-Than ("Under X"): "-45", "<45", "Under 45 lbs", "-45 (lbs)"
    m_under = re.match(
        r"^(?:[-<]|under\s+|less\s+than\s+)\s*(\d+(?:\.\d+)?)\s*(?:\(?\s*(?:lbs?|kgs?|#|cwt)\s*\)?)?$",
        stripped,
        re.I,
    )
    if m_under:
        val = abs(float(m_under.group(1)))
        return ParsedBreak(
            raw_header=raw,
            break_name=raw,
            min_weight=0.0,
            max_weight=val,
            is_open_ended=False,
            break_value=val,
            unit=unit,
            is_under=True,
        )

    # 4. K-suffix shorthand: "1K", "2K+", "10K lbs"
    m_k = re.match(
        r"^(?:[+>]\s*)?(\d+(?:\.\d+)?)K\s*\+?\s*(?:\(?\s*(?:lbs?|kgs?|#|cwt)\s*\)?)?$",
        stripped,
        re.I,
    )
    if m_k:
        val = float(m_k.group(1)) * 1000.0
        return ParsedBreak(
            raw_header=raw,
            break_name=raw,
            min_weight=val,
            max_weight=None,
            is_open_ended=True,
            break_value=val,
            unit=unit,
        )

    # 5. Open-ended / threshold / numeric break: "+100", "100+", "10,000+ lbs", "CWT:2000", "45 lb", "45#", "100"
    m_open = re.match(
        r"^(?:[+>]\s*)?(\d+(?:\.\d+)?)\s*\+?\s*(?:\(?\s*(?:lbs?|kgs?|#|cwt)\s*\)?)?\s*\+?$",
        stripped,
        re.I,
    )
    if m_open:
        val = abs(float(m_open.group(1)))
        return ParsedBreak(
            raw_header=raw,
            break_name=raw,
            min_weight=val,
            max_weight=None,
            is_open_ended=True,
            break_value=val,
            unit=unit,
        )

    return None


def parse_break_value(h: Any, mode_hint: Optional[str] = None) -> Tuple[Optional[float], Optional[str]]:
    """
    Backward-compatible helper returning (break_value, unit) for app/detect.py.
    """
    parsed = parse_break_header(h, mode_hint=mode_hint)
    if parsed is None:
        return None, None
    return parsed.break_value, parsed.unit


def resolve_contiguous_weight_brackets(parsed_breaks: List[ParsedBreak]) -> Tuple[List[ParsedBreak], List[str]]:
    """
    Given a sequence of ParsedBreak objects across a header row (sorted by min_weight),
    infers upper bounds for open-ended intermediate brackets from the next bracket's min_weight,
    and validates contiguity (flagging any gaps > 1.0 unit, e.g. 500-899 followed by 1000).

    Returns (resolved_breaks, gap_errors).
    """
    if not parsed_breaks:
        return [], []

    resolved: List[ParsedBreak] = []
    gap_errors: List[str] = []

    for i, b in enumerate(parsed_breaks):
        is_last = (i == len(parsed_breaks) - 1)
        if not is_last:
            next_b = parsed_breaks[i + 1]
            if not b.is_open_ended and b.max_weight is not None and not b.is_under:
                gap = next_b.min_weight - b.max_weight
                if gap > 1.0:
                    gap_errors.append(
                        f"Weight bracket gap detected between '{b.raw_header}' "
                        f"(max {b.max_weight}) and '{next_b.raw_header}' (min {next_b.min_weight}): "
                        f"weights {b.max_weight} to {next_b.min_weight} are uncovered."
                    )
                resolved.append(
                    ParsedBreak(
                        raw_header=b.raw_header,
                        break_name=b.break_name,
                        min_weight=b.min_weight,
                        max_weight=b.max_weight,
                        is_open_ended=False,
                        break_value=b.break_value,
                        unit=b.unit,
                        is_under=b.is_under,
                        kind=b.kind,
                    )
                )
            else:
                # Intermediate open-ended threshold (e.g. M5C=500 followed by M1M=1000):
                # Bounds are [500, 999] (continuous up to next_b.min_weight)
                inferred_max = max(b.min_weight, next_b.min_weight - 1.0)
                resolved.append(
                    ParsedBreak(
                        raw_header=b.raw_header,
                        break_name=b.break_name,
                        min_weight=b.min_weight,
                        max_weight=inferred_max,
                        is_open_ended=False,
                        break_value=b.break_value,
                        unit=b.unit,
                        is_under=b.is_under,
                        kind=b.kind,
                    )
                )
        else:
            # Final (highest) bracket preserves its open-ended or closed status!
            resolved.append(
                ParsedBreak(
                    raw_header=b.raw_header,
                    break_name=b.break_name,
                    min_weight=b.min_weight,
                    max_weight=None if b.is_open_ended else b.max_weight,
                    is_open_ended=b.is_open_ended,
                    break_value=b.break_value,
                    unit=b.unit,
                    is_under=b.is_under,
                    kind=b.kind,
                )
            )

    return resolved, gap_errors
