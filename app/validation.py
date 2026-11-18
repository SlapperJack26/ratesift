"""
app/validation.py
Deterministic rule validation engine, heuristic detectors, finding code matrices,
and layout fingerprinting for Quotelytics Failsafe Mapping.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
import unicodedata

from app.constants import SEVERITY_BLOCKER, SEVERITY_WARNING

# Finding Codes
BLOCKER_MISSING_ORIGIN = "BLOCKER_MISSING_ORIGIN"
BLOCKER_MISSING_DEST = "BLOCKER_MISSING_DEST"
BLOCKER_MISSING_CURRENCY = "BLOCKER_MISSING_CURRENCY"
BLOCKER_COLUMN_COLLISION = "BLOCKER_COLUMN_COLLISION"
BLOCKER_WEIGHT_MISSING_UNIT = "BLOCKER_WEIGHT_MISSING_UNIT"
BLOCKER_WEIGHT_NO_RATES = "BLOCKER_WEIGHT_NO_RATES"
BLOCKER_SKID_INVALID_TIERS = "BLOCKER_SKID_INVALID_TIERS"
BLOCKER_HEADER_AMBIGUITY = "BLOCKER_HEADER_AMBIGUITY"
BLOCKER_MC_RATE_COLLISION = "BLOCKER_MC_RATE_COLLISION"
BLOCKER_RATE_COL_NON_NUMERIC = "BLOCKER_RATE_COL_NON_NUMERIC"
BLOCKER_ALL_LANES_NO_RATE = "BLOCKER_ALL_LANES_NO_RATE"
BLOCKER_UNPARSED_BREAK_LABEL = "BLOCKER_UNPARSED_BREAK_LABEL"

WARN_NON_MONOTONIC_CWT = "WARN_NON_MONOTONIC_CWT"
WARN_ANOMALOUS_CROSSOVER = "WARN_ANOMALOUS_CROSSOVER"
WARN_SUSPECTED_TRANSIT_DAYS = "WARN_SUSPECTED_TRANSIT_DAYS"
WARN_SUSPECTED_INTEGER_RATE = "WARN_SUSPECTED_INTEGER_RATE"
WARN_RATE_OUTLIER_STATISTICAL = "WARN_RATE_OUTLIER_STATISTICAL"
WARN_PARCEL_CONTOUR_OVERRIDE = "WARN_PARCEL_CONTOUR_OVERRIDE"
WARN_INVERTED_LANES = "WARN_INVERTED_LANES"
WARN_BREAK_EXCEEDS_CAPACITY = "WARN_BREAK_EXCEEDS_CAPACITY"


class Finding:
    def __init__(
        self,
        code: str,
        severity: str,
        message: str,
        affected_columns: Optional[List[int]] = None,
        sheet_sha256: str = "",
        params: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.severity = severity
        self.message = message
        self.affected_columns = sorted(affected_columns or [])
        self.params = params or {}
        cols_str = ",".join(map(str, self.affected_columns))
        self.finding_id = f"{code}:{cols_str}:{sheet_sha256}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "affected_columns": self.affected_columns,
            "finding_id": self.finding_id,
            "params": self.params,
        }

    def __repr__(self) -> str:
        return f"<Finding {self.code} [{self.severity}] cols={self.affected_columns}>"


# ------------------------------------------------------------------------------
# Normalization & Fingerprinting
# ------------------------------------------------------------------------------

def normalize_text_token(text: Any) -> str:
    """Case-folds, strips accents (NFKD), removes punctuation, and collapses whitespace."""
    if text is None:
        return ""
    norm = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").lower()
    norm = re.sub(r"[^\w\s]", "", norm)
    return re.sub(r"\s+", " ", norm).strip()


def compute_layout_fingerprint(col_count: int, raw_headers: List[str]) -> str:
    """
    Computes deterministic SHA-256 layout fingerprint across normalized headers and column count.
    Excludes transient tab name so weekly renamed tabs match saved mappings.
    """
    norm_headers = []
    for idx, h in enumerate(raw_headers):
        norm_headers.append((idx, normalize_text_token(h)))
    payload = json.dumps({"cols": col_count, "headers": norm_headers}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------
# Break Label Parsing
# ------------------------------------------------------------------------------

def parse_break_label(label: str, user_weight_fallback: Optional[float] = None) -> Optional[float]:
    """
    Deterministically parses Day & Ross and North American commercial LTL break labels.
    Returns numeric break weight in pounds (or user_weight_fallback if unparsed).
    """
    if user_weight_fallback is not None and user_weight_fallback >= 0:
        return float(user_weight_fallback)

    clean = str(label or "").strip().upper()
    if not clean:
        return None

    # Minimum charge / Floor markers
    if clean in ("MIN", "MC", "MINIMUM", "FLAT MIN", "FLAT_MIN", "BASE"):
        return -1.0  # Marker for minimum floor

    # Default CWT base breaks
    if clean in ("LTL", "DEFAULT", "BASE CWT"):
        return 0.0

    # L5C bracket ([0, 499.99 lbs], threshold 0)
    if clean in ("L5C", "LT5C", "<500", "0-499"):
        return 0.0

    # M5C bracket (>= 500 lbs)
    if clean in ("M5C", "5C", "500", "500#", "500LBS"):
        return 500.0

    # Exact CWT syntax: CWT:1000, CWT:2000, etc.
    m_cwt = re.match(r"^CWT:(\d+(?:\.\d+)?)$", clean)
    if m_cwt:
        return float(m_cwt.group(1))

    # 1M, 2M, 5M, 10M, 20M, 40M
    m_m = re.match(r"^(?:M)?(\d+(?:\.\d+)?)\s*M$", clean)
    if m_m:
        return float(m_m.group(1)) * 1000.0

    # 1K, 2K, 5K, 10K
    m_k = re.match(r"^(\d+(?:\.\d+)?)\s*K$", clean)
    if m_k:
        return float(m_k.group(1)) * 1000.0

    # Pure numeric strings (e.g. "1000", "2000", "5000")
    m_num = re.match(r"^(\d+(?:\.\d+)?)(?:\s*(?:LBS?|LB|#))?$", clean)
    if m_num:
        val = float(m_num.group(1))
        # If numbers like 1, 2, 5, 10 are used as thousands shorthand in weight context
        if val in (1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 40.0) and "M" in clean:
            return val * 1000.0
        return val

    # Delegate composite labels ("151 to 299 lbs", "100+ lbs", "Weight Breaks 500") to shared parser
    try:
        from services.break_header_parser import parse_break_header
        pb = parse_break_header(label, mode_hint="weight")
        if pb is not None:
            return float(pb.break_value)
    except Exception:
        pass

    return None


# ------------------------------------------------------------------------------
# Heuristic Detectors
# ------------------------------------------------------------------------------

def check_monotonicity(
    active_rows: List[List[Any]],
    rate_columns_with_breaks: List[Tuple[int, float]],
    rate_basis: str = "PER_CWT",
    sheet_sha256: str = "",
) -> List[Finding]:
    """
    Evaluates adjacent rate columns for monotonic progression.
    In PER_CWT: rates should decrease as weight break increases (R_k <= R_{k-1}).
    In FLAT_BREAK: totals should increase (F_k >= F_{k-1}).
    """
    if len(rate_columns_with_breaks) < 2:
        return []

    # Sort columns by break weight ascending
    sorted_pairs = sorted(rate_columns_with_breaks, key=lambda x: x[1])
    findings = []
    is_per_cwt = (rate_basis or "PER_CWT").upper() == "PER_CWT"

    for i in range(1, len(sorted_pairs)):
        prev_col, prev_wt = sorted_pairs[i - 1]
        curr_col, curr_wt = sorted_pairs[i]
        if prev_wt == curr_wt:
            continue

        violations = 0
        valid_pairs = 0

        for row in active_rows:
            v_prev = _to_float(row[prev_col] if prev_col < len(row) else None)
            v_curr = _to_float(row[curr_col] if curr_col < len(row) else None)
            if v_prev is not None and v_curr is not None and v_prev > 0 and v_curr > 0:
                valid_pairs += 1
                if is_per_cwt:
                    # In PER_CWT, current rate should be <= previous rate + 0.05
                    if v_curr > (v_prev + 0.05):
                        violations += 1
                else:
                    # In FLAT_BREAK, current flat charge should be >= previous charge - 0.05
                    if v_curr < (v_prev - 0.05):
                        violations += 1

        if valid_pairs > 0 and (violations / valid_pairs) > 0.10:
            msg = (
                f"Rate progression is non-monotonic across weight breaks ({prev_wt:.0f} -> {curr_wt:.0f}). "
                f"{violations} of {valid_pairs} sampled lanes violate expected rate progression."
            )
            findings.append(
                Finding(
                    code=WARN_NON_MONOTONIC_CWT,
                    severity=SEVERITY_WARNING,
                    message=msg,
                    affected_columns=[prev_col, curr_col],
                    sheet_sha256=sheet_sha256,
                    params={"violations": violations, "valid_pairs": valid_pairs, "rate_basis": rate_basis},
                )
            )

    return findings


def check_anomalous_crossover(
    break_pairs: List[Tuple[float, float, float, float]],  # (B_k, B_{k+1}, R_k, R_{k+1})
    affected_columns: List[int],
    sheet_sha256: str = "",
) -> List[Finding]:
    """
    Checks if deficit crossover weight W_cross <= B_k for any adjacent break pair in PER_CWT.
    """
    findings = []
    for b_k, b_next, r_k, r_next in break_pairs:
        if r_k > r_next > 0 and b_next > b_k:
            w_cross = (b_next * r_next) / r_k
            if w_cross <= b_k:
                findings.append(
                    Finding(
                        code=WARN_ANOMALOUS_CROSSOVER,
                        severity=SEVERITY_WARNING,
                        message=(
                            f"Anomalous deficit crossover weight ({w_cross:.1f} lbs) is at or below the lower break boundary "
                            f"({b_k:.0f} lbs) between {b_k:.0f} and {b_next:.0f}. Verify rate discounts."
                        ),
                        affected_columns=affected_columns,
                        sheet_sha256=sheet_sha256,
                        params={"b_k": b_k, "b_next": b_next, "w_cross": w_cross},
                    )
                )
    return findings


def check_transit_days_vs_integer_rates(
    header_text: str,
    column_values: List[Any],
    col_idx: int,
    sheet_sha256: str = "",
) -> Optional[Finding]:
    """
    Evaluates whether a mapped rate column is actually a transit days column.
    - Transit keywords + integers <= 14 -> WARN_SUSPECTED_TRANSIT_DAYS
    - No keywords + 100% integers <= 7 -> WARN_SUSPECTED_INTEGER_RATE
    - Values 8..14 without keywords are treated as valid rate candidates.
    """
    populated = [_to_float(v) for v in column_values if v is not None and str(v).strip() != ""]
    if len(populated) < 1:
        return None

    # Check if all values are positive integers
    all_integers = all(v is not None and v.is_integer() and v > 0 for v in populated)
    if not all_integers:
        return None

    norm_hdr = normalize_text_token(header_text)
    transit_keywords = ("days", "day", "transit", "del", "service", "delai", "transit time", "tt")
    has_transit_keyword = any(kw in norm_hdr.split() or kw == norm_hdr for kw in transit_keywords)

    max_val = max(populated)
    min_val = min(populated)

    if has_transit_keyword and max_val <= 14:
        return Finding(
            code=WARN_SUSPECTED_TRANSIT_DAYS,
            severity=SEVERITY_WARNING,
            message=(
                f"Column '{header_text}' contains transit day keywords and integers ({int(min_val)}–{int(max_val)}). "
                f"Confirm this is not a service transit days column."
            ),
            affected_columns=[col_idx],
            sheet_sha256=sheet_sha256,
            params={"min": int(min_val), "max": int(max_val)},
        )

    if not has_transit_keyword and max_val <= 7:
        return Finding(
            code=WARN_SUSPECTED_INTEGER_RATE,
            severity=SEVERITY_WARNING,
            message=(
                f"Column '{header_text}' contains 100% small integers (<= 7) without transit keywords. "
                f"Verify this column contains freight rates and not estimated transit days."
            ),
            affected_columns=[col_idx],
            sheet_sha256=sheet_sha256,
            params={"min": int(min_val), "max": int(max_val)},
        )

    return None


def check_statistical_outlier(
    column_values: List[Any],
    col_idx: int,
    col_name: str = "",
    rate_basis: str = "PER_CWT",
    break_weight: Optional[float] = None,
    sheet_sha256: str = "",
) -> Optional[Finding]:
    """
    Statistical outlier check: Q3 + 3.0 * IQR_effective with IQR floor rule.
    Requires at least 10 valid numeric rows.
    """
    populated = []
    for v in column_values:
        num = _to_float(v)
        if num is not None and num > 0:
            if rate_basis.upper() == "FLAT_BREAK" and break_weight and break_weight > 0:
                populated.append(num / (break_weight / 100.0))
            else:
                populated.append(num)

    if len(populated) < 10:
        return None

    sorted_vals = sorted(populated)
    n = len(sorted_vals)

    def _percentile(p: float) -> float:
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        d = k - f
        return sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f])

    q1 = _percentile(0.25)
    median = _percentile(0.50)
    q3 = _percentile(0.75)
    raw_iqr = q3 - q1

    # IQR Floor Rule: IQR_effective = max(raw_iqr, 0.05 * median)
    iqr_effective = max(raw_iqr, 0.05 * median)
    high_threshold = q3 + (3.0 * iqr_effective)
    low_threshold = max(0.0, q1 - (3.0 * iqr_effective))

    outliers = [v for v in sorted_vals if v > high_threshold or v < low_threshold]
    if outliers:
        return Finding(
            code=WARN_RATE_OUTLIER_STATISTICAL,
            severity=SEVERITY_WARNING,
            message=(
                f"Column '{col_name}' contains {len(outliers)} statistical rate outlier(s) "
                f"outside 3x IQR bounds ([{low_threshold:.2f}, {high_threshold:.2f}]). "
                f"Extreme values: min={min(outliers):.2f}, max={max(outliers):.2f}."
            ),
            affected_columns=[col_idx],
            sheet_sha256=sheet_sha256,
            params={
                "outlier_count": len(outliers),
                "q1": q1,
                "median": median,
                "q3": q3,
                "iqr_effective": iqr_effective,
                "high_threshold": high_threshold,
                "low_threshold": low_threshold,
            },
        )
    return None


def check_parcel_dual_signal(
    break_weights: List[float],
    headers: List[str],
    preamble_text: str = "",
    mode: str = "weight",
) -> bool:
    """
    Dual-signal parcel detection:
    Requires weight signal (all breaks <= 150 lbs) AND at least one courier signal.
    Excludes mode == 'skid' or skid brackets.
    """
    if mode.lower() == "skid":
        return False

    valid_breaks = [w for w in break_weights if w > 0]
    if not valid_breaks or any(w > 150.0 for w in valid_breaks):
        return False

    # Check courier keywords in headers or preamble
    courier_terms = {"pkg", "box", "parcel", "carton", "courier", "pack", "ground courier", "express pack"}
    all_text = " ".join([normalize_text_token(h) for h in headers] + [normalize_text_token(preamble_text)])

    words = set(all_text.split())
    has_courier_signal = bool(words.intersection(courier_terms)) or "ground courier" in all_text or "express pack" in all_text
    return has_courier_signal


def check_inverted_lanes(
    origin_hdr: str,
    dest_hdr: str,
    fixed_origin: Optional[str] = None,
    sheet_sha256: str = "",
    origin_col: Optional[int] = None,
    dest_col: Optional[int] = None,
) -> Optional[Finding]:
    """
    Evaluates whether origin and destination columns appear inverted.
    """
    norm_orig = normalize_text_token(origin_hdr)
    norm_dest = normalize_text_token(dest_hdr)

    orig_synonyms = {"from", "orig", "origin", "shipper", "pickup"}
    dest_synonyms = {"to", "dest", "destination", "consignee", "delivery"}

    orig_matches_dest = any(syn in norm_orig.split() or syn == norm_orig for syn in dest_synonyms)
    dest_matches_orig = any(syn in norm_dest.split() or syn == norm_dest for syn in orig_synonyms)

    if orig_matches_dest or dest_matches_orig:
        cols = [c for c in (origin_col, dest_col) if c is not None]
        return Finding(
            code=WARN_INVERTED_LANES,
            severity=SEVERITY_WARNING,
            message=f"Origin header '{origin_hdr}' scores higher against destination terms than origin terms. Verify lanes are not inverted.",
            affected_columns=cols,
            sheet_sha256=sheet_sha256,
        )
    return None


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    clean = re.sub(r"[^\d.-]", "", str(val).strip())
    try:
        return float(clean) if clean else None
    except ValueError:
        return None
