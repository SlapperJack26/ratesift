from datetime import datetime
import json
import uuid
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from services.ratesift_db_service import (
    get_rate_sheet,
    get_sheet_full_rules,
    list_rate_sheets,
    get_rate_sheet_cells,
    log_quote_audit
)
from services.fsa_resolver_service import resolve_location, extract_fsa
from services.fuel_index_service import resolve_effective_fuel_surcharge

KG_TO_LBS_FACTOR = Decimal("2.20462262185")


def to_decimal(val: Any) -> Decimal:
    """Safely converts any numeric/string value to a Decimal without binary float artifacts."""
    if isinstance(val, Decimal):
        return val
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def round_money(val: Any, rule: str = "standard_2dp") -> Decimal:
    """
    Quantizes a monetary value to 2 decimal places using Decimal ROUND_HALF_UP (or ROUND_CEILING).
    """
    d = to_decimal(val)
    if rule == "ceiling_cent":
        return d.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_currency(val: Any, rule: str = "standard_2dp") -> float:
    """
    Rule 15: Quantize currency using each sheet's own rounding rules.
    Standard: Half-up to 2 decimal places via Decimal.
    """
    return float(round_money(val, rule))


def quantize_2dp(val: Any) -> float:
    """Quantizes a numeric value to 0.01 using Decimal ROUND_HALF_UP and returns a float."""
    return float(to_decimal(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def quantize_1dp(val: Any) -> float:
    """Quantizes a numeric value to 0.1 using Decimal ROUND_HALF_UP and returns a float."""
    return float(to_decimal(val).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _normalize_weight_unit(unit: Optional[str]) -> str:
    u = (unit or "LB").strip().upper()
    if u in ("KG", "KGS", "KILOGRAM", "KILOGRAMS"):
        return "KG"
    return "LB"


def convert_weight_unit(weight: Any, from_unit: str, to_unit: str) -> Decimal:
    """
    Converts weight between LBS and KG using exact Decimal arithmetic (1 kg = 2.20462262185 lb).
    """
    w = to_decimal(weight)
    src = _normalize_weight_unit(from_unit)
    dst = _normalize_weight_unit(to_unit)
    if src == dst:
        return w
    if src == "KG" and dst == "LB":
        return w * KG_TO_LBS_FACTOR
    if src == "LB" and dst == "KG":
        return w / KG_TO_LBS_FACTOR
    return w


def round_weight(weight: Any, rule: str = "CEIL_1LB") -> Decimal:
    """
    Applies the tariff's weight rounding rule:
    - CEIL_1LB (default): Ceiling to next whole unit (1 lb / 1 kg).
    - CEIL_5LB: Ceiling to next multiple of 5 units.
    - EXACT: Preserves fractional weight quantized to 0.01 (ROUND_HALF_UP).
    """
    w = to_decimal(weight)
    if w <= Decimal("0"):
        return Decimal("0.00")
    r = (rule or "CEIL_1LB").strip().upper()
    if r == "EXACT":
        return w.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if r == "CEIL_5LB":
        five = Decimal("5")
        return ((w / five).to_integral_value(rounding=ROUND_CEILING) * five).quantize(Decimal("0.01"))
    # Default: CEIL_1LB
    return w.to_integral_value(rounding=ROUND_CEILING).quantize(Decimal("0.01"))


def _unpack_piece(p: Any) -> Tuple[Decimal, Decimal, Decimal, Decimal, int]:
    """Unpacks a piece dict or tuple into (weight, length, width, height, qty)."""
    if isinstance(p, dict):
        w = to_decimal(p.get("weight", p.get("actual_weight", 0)))
        l_in = to_decimal(p.get("length", p.get("l", 0)))
        w_in = to_decimal(p.get("width", p.get("w", 0)))
        h_in = to_decimal(p.get("height", p.get("h", 0)))
        qty = int(p.get("qty", p.get("quantity", 1)) or 1)
        return w, l_in, w_in, h_in, qty
    if isinstance(p, (list, tuple)):
        if len(p) >= 5:
            return to_decimal(p[0]), to_decimal(p[1]), to_decimal(p[2]), to_decimal(p[3]), int(p[4])
        if len(p) == 4:
            return to_decimal(p[0]), to_decimal(p[1]), to_decimal(p[2]), to_decimal(p[3]), 1
    raise ValueError(f"Unsupported piece format: {p!r}")


def calculate_billable_weight(
    actual_weight: float,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    dim_divisor: Optional[float] = 139.0,
    dim_min_pcf: Optional[float] = None,
    mode: str = "LTL",
    weight_rounding_rule: str = "EXACT",
    pieces: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Rule 9: Calculate dimensional weight using the carrier's own divisor and mode-specific rules,
    and bill on the greater of actual weight and dimensional/cubic weight.
    Supports per-piece (weight, L, W, H, qty) calculation and explicit weight rounding.
    """
    mode_up = (mode or "LTL").strip().upper()
    has_divisor = dim_divisor is not None and float(dim_divisor) > 0

    if mode_up == "PARCEL" and not has_divisor:
        raise ValueError("MISSING_PARCEL_DIM_DIVISOR: Parcel rate sheet requires an explicit DIM divisor.")

    divisor_dec = to_decimal(dim_divisor) if has_divisor else None
    pcf_dec = to_decimal(dim_min_pcf) if (dim_min_pcf is not None and float(dim_min_pcf) > 0) else None

    if pieces:
        total_actual = Decimal("0")
        total_dim = Decimal("0")
        total_cubic = Decimal("0")
        total_billable = Decimal("0")
        piece_breakdowns = []

        for p in pieces:
            p_wt, p_l, p_w, p_h, p_qty = _unpack_piece(p)
            qty_dec = to_decimal(p_qty)
            p_dim = Decimal("0")
            p_cubic = Decimal("0")
            if p_l > 0 and p_w > 0 and p_h > 0:
                cu_in = p_l * p_w * p_h
                if divisor_dec is not None and divisor_dec > 0:
                    p_dim = cu_in / divisor_dec
                if pcf_dec is not None and pcf_dec > 0:
                    cu_ft = cu_in / Decimal("1728")
                    p_cubic = cu_ft * pcf_dec

            p_raw_billable = max(p_wt, p_dim, p_cubic)
            p_rounded_billable = round_weight(p_raw_billable, weight_rounding_rule)

            total_actual += p_wt * qty_dec
            total_dim += p_dim * qty_dec
            total_cubic += p_cubic * qty_dec
            total_billable += p_rounded_billable * qty_dec
            piece_breakdowns.append({
                "actual_weight": float(p_wt),
                "length": float(p_l),
                "width": float(p_w),
                "height": float(p_h),
                "qty": p_qty,
                "piece_dim_weight": quantize_2dp(p_dim),
                "piece_billable_weight": float(p_rounded_billable),
            })

        billable_dec = round_weight(total_billable, weight_rounding_rule)
        actual_out = quantize_2dp(total_actual) if total_actual > 0 else quantize_2dp(actual_weight)
        return {
            "actual_weight": actual_out,
            "dim_weight": quantize_2dp(total_dim),
            "cubic_weight": quantize_2dp(total_cubic),
            "billable_weight": float(billable_dec),
            "is_dim_billed": billable_dec > to_decimal(actual_out),
            "dim_divisor": float(divisor_dec) if divisor_dec is not None else None,
            "pieces": piece_breakdowns,
        }

    actual_dec = to_decimal(actual_weight)
    dim_dec = Decimal("0")
    cubic_dec = Decimal("0")

    if length and width and height and float(length) > 0 and float(width) > 0 and float(height) > 0:
        cubic_inches = to_decimal(length) * to_decimal(width) * to_decimal(height)
        if divisor_dec is not None and divisor_dec > 0:
            dim_dec = cubic_inches / divisor_dec

        if pcf_dec is not None and pcf_dec > 0:
            cubic_feet = cubic_inches / Decimal("1728")
            cubic_dec = cubic_feet * pcf_dec

    raw_billable = max(actual_dec, dim_dec, cubic_dec)
    billable_dec = round_weight(raw_billable, weight_rounding_rule)

    return {
        "actual_weight": float(actual_dec),
        "dim_weight": quantize_2dp(dim_dec),
        "cubic_weight": quantize_2dp(cubic_dec),
        "billable_weight": float(billable_dec),
        "is_dim_billed": raw_billable > actual_dec,
        "dim_divisor": float(divisor_dec) if divisor_dec is not None else None,
    }


def normalize_location_string(loc: str) -> str:
    """Normalizes location strings for consistent lane matching (e.g. 'Calgary, AB' -> 'CALGARY, AB', 'M5V 2T6' -> 'TORONTO, ON')."""
    if not loc:
        return ""
    loc_clean = " ".join(loc.strip().upper().split()).replace(".", "")
    res = resolve_location(loc_clean)
    if res.get("is_resolved") and res.get("location_string"):
        return res["location_string"]
    return loc_clean


def match_lane_break(
    breaks: List[Dict[str, Any]],
    origin: str,
    destination: str,
    billable_weight: float,
    skid_count: Optional[int] = None,
    allow_deficit_rating: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Rule 8 & 10: Matches exact lane and weight break deterministically.
    Supports Canadian Postal FSA matching, continuous interval bracket matching
    (min_weight <= w < next_min_weight), closed/open top-tier checks, and SMC3 Deficit Weight Rating
    across all higher brackets.
    """
    norm_origin = normalize_location_string(origin)
    norm_dest = normalize_location_string(destination)
    fsa_orig = extract_fsa(origin)
    fsa_dest = extract_fsa(destination)

    # 1. Exact Origin & Destination Match
    matched_candidates = []
    for b in breaks:
        b_orig = normalize_location_string(b.get("origin_spec") or "")
        b_dest = normalize_location_string(b.get("dest_spec") or "")

        origin_matches = (b_orig == norm_origin) or (not b_orig and not b_dest)
        dest_matches = (b_dest == norm_dest) or (not b_orig and not b_dest)

        if not origin_matches and fsa_orig and (b_orig == fsa_orig or extract_fsa(b_orig) == fsa_orig):
            origin_matches = True
        if not dest_matches and fsa_dest and (b_dest == fsa_dest or extract_fsa(b_dest) == fsa_dest):
            dest_matches = True

        if not origin_matches and b_orig and "," in norm_origin and "," in b_orig:
            o_city, o_prov = [x.strip() for x in norm_origin.split(",", 1)]
            bo_city, bo_prov = [x.strip() for x in b_orig.split(",", 1)]
            if o_prov == bo_prov and (o_city in bo_city or bo_city in o_city):
                origin_matches = True

        if not dest_matches and b_dest and "," in norm_dest and "," in b_dest:
            d_city, d_prov = [x.strip() for x in norm_dest.split(",", 1)]
            bd_city, bd_prov = [x.strip() for x in b_dest.split(",", 1)]
            if d_prov == bd_prov and (d_city in bd_city or bd_city in d_city):
                dest_matches = True

        if origin_matches and dest_matches:
            matched_candidates.append(b)

    if not matched_candidates:
        return None

    # When rating in skid mode, map skid tiers directly and bypass CWT bumping
    if skid_count is not None and skid_count > 0:
        tier_break = None
        if 1 <= skid_count <= 5:
            tier_break = next(
                (b for b in matched_candidates if b.get("break_name") in ["LTL", "L5C", "<5C", "L5"] or b["min_weight"] < 1000),
                None
            )
        elif skid_count == 6:
            tier_break = next(
                (b for b in matched_candidates if b.get("break_name") in ["1M", "CWT:1000"] or b["min_weight"] == 1000),
                None
            )
        elif skid_count == 7:
            tier_break = next(
                (b for b in matched_candidates if b.get("break_name") in ["2M", "CWT:2000"] or b["min_weight"] == 2000),
                None
            )
        elif 8 <= skid_count <= 9:
            tier_break = next((b for b in matched_candidates if b.get("break_name") in ["3M", "4M"]), None)
            if not tier_break:
                tier_break = next((b for b in matched_candidates if b.get("break_name") in ["5M", "CWT:5000"] or (2000 < b["min_weight"] <= 5000)), None)
        elif skid_count == 10:
            tier_break = next((b for b in matched_candidates if b.get("break_name") in ["10M", "CWT:10000"]), None)
            if not tier_break:
                tier_break = next((b for b in matched_candidates if b.get("break_name") in ["5M", "CWT:5000"] or b["min_weight"] >= 5000), None)

        if tier_break:
            result_break = dict(tier_break)
            result_break["is_deficit_rated"] = False
            result_break["deficit_weight"] = 0.0
            result_break["deficit_savings"] = 0.0
            result_break["effective_base_charge"] = None
            result_break["natural_break"] = dict(tier_break)
            result_break["natural_charge"] = None
            return result_break

    # Separate CWT brackets from FLAT/other brackets if CWT brackets exist on this lane
    cwt_candidates = [b for b in matched_candidates if (b.get("rate_type") or "CWT").upper() == "CWT"]
    active_pool = sorted(cwt_candidates, key=lambda x: float(x["min_weight"])) if cwt_candidates else sorted(matched_candidates, key=lambda x: float(x["min_weight"]))

    w_dec = to_decimal(billable_weight)
    matching_break = None
    n = len(active_pool)

    for idx, b in enumerate(active_pool):
        b_min = to_decimal(b["min_weight"])
        b_max_raw = b.get("max_weight")
        b_max = to_decimal(b_max_raw) if b_max_raw is not None else None
        is_open = bool(b.get("is_open_ended", 0)) or b_max is None or b_max >= Decimal("999999")

        if idx < n - 1:
            next_min = to_decimal(active_pool[idx + 1]["min_weight"])
            # Check if there is an explicit gap (> 1 unit) between b_max and next_min
            if b_max is not None and not is_open and (next_min - b_max) > Decimal("1.0001"):
                if b_min <= w_dec <= b_max:
                    matching_break = b
                    break
                if b_max < w_dec < next_min:
                    raise ValueError(
                        f"BRACKET_GAP_DETECTED: Billable weight {billable_weight} lbs falls into an uncovered gap "
                        f"between {float(b_max)} and {float(next_min)} lbs."
                    )
            else:
                if b_min <= w_dec < next_min:
                    matching_break = b
                    break
        else:
            # Final (top) bracket
            if is_open:
                if w_dec >= b_min:
                    matching_break = b
                    break
            else:
                if b_min <= w_dec <= b_max:
                    matching_break = b
                    break
                if w_dec > b_max:
                    raise ValueError(
                        f"Rule 18 / Bracket Cap Exclusion: Billable weight {billable_weight} lbs exceeds "
                        f"closed top weight bracket maximum of {float(b_max)} lbs ({b.get('break_name')})."
                    )

    if not matching_break:
        return None

    # 3. Deficit Weight Rating (SMC3 / Canadian Freight Bumping Rule across ALL higher brackets)
    is_deficit_rated = False
    deficit_savings = 0.0
    deficit_weight = 0.0
    effective_charge = None
    effective_break = matching_break
    natural_charge_float = None

    if skid_count is None and (matching_break.get("rate_type") or "CWT").upper() == "CWT":
        natural_rate_dec = to_decimal(matching_break["base_rate"])
        natural_charge_dec = round_money((w_dec / Decimal("100")) * natural_rate_dec)
        natural_charge_float = float(natural_charge_dec)
        best_charge_dec = natural_charge_dec

        if allow_deficit_rating:
            for higher_b in active_pool:
                higher_min_dec = to_decimal(higher_b["min_weight"])
                if higher_min_dec > w_dec and (higher_b.get("rate_type") or "CWT").upper() == "CWT":
                    bumped_rate_dec = to_decimal(higher_b["base_rate"])
                    bumped_charge_dec = round_money((higher_min_dec / Decimal("100")) * bumped_rate_dec)
                    # Strict '<' ensures ties stay at the natural weight bracket (is_deficit_rated = False)
                    if bumped_charge_dec < best_charge_dec:
                        best_charge_dec = bumped_charge_dec
                        effective_break = higher_b
                        is_deficit_rated = True
                        deficit_weight = quantize_2dp(higher_min_dec - w_dec)
                        deficit_savings = float(round_money(natural_charge_dec - bumped_charge_dec))
                        effective_charge = float(bumped_charge_dec)

    result_break = dict(effective_break)
    result_break["is_deficit_rated"] = is_deficit_rated
    result_break["deficit_weight"] = deficit_weight
    result_break["deficit_savings"] = deficit_savings
    result_break["effective_base_charge"] = effective_charge
    result_break["natural_break"] = dict(matching_break)
    result_break["natural_charge"] = natural_charge_float
    return result_break


def match_skid_break(
    breaks: List[Dict[str, Any]],
    origin: str,
    destination: str,
    skid_count: int
) -> Optional[Dict[str, Any]]:
    """
    Rule 8 & 10: Matches exact lane and skid break deterministically for PER_SKID rating.
    """
    norm_origin = normalize_location_string(origin)
    norm_dest = normalize_location_string(destination)
    fsa_orig = extract_fsa(origin)
    fsa_dest = extract_fsa(destination)

    matched_candidates = []
    for b in breaks:
        b_unit = (b.get("break_unit") or "").upper()
        b_type = (b.get("rate_type") or "").upper()
        if b_unit != "SKID" and b_type != "PER_SKID":
            continue

        b_orig = normalize_location_string(b.get("origin_spec") or "")
        b_dest = normalize_location_string(b.get("dest_spec") or "")

        origin_matches = (b_orig == norm_origin) or (not b_orig and not b_dest)
        dest_matches = (b_dest == norm_dest) or (not b_orig and not b_dest)

        if not origin_matches and fsa_orig and (b_orig == fsa_orig or extract_fsa(b_orig) == fsa_orig):
            origin_matches = True
        if not dest_matches and fsa_dest and (b_dest == fsa_dest or extract_fsa(b_dest) == fsa_dest):
            dest_matches = True

        if not origin_matches and b_orig and "," in norm_origin and "," in b_orig:
            o_city, o_prov = [x.strip() for x in norm_origin.split(",", 1)]
            bo_city, bo_prov = [x.strip() for x in b_orig.split(",", 1)]
            if o_prov == bo_prov and (o_city in bo_city or bo_city in o_city):
                origin_matches = True
        elif not origin_matches and b_orig and "," in b_orig and "," not in norm_origin:
            bo_city = b_orig.split(",", 1)[0].strip()
            if norm_origin == bo_city or norm_origin in bo_city:
                origin_matches = True

        if not dest_matches and b_dest and "," in norm_dest and "," in b_dest:
            d_city, d_prov = [x.strip() for x in norm_dest.split(",", 1)]
            bd_city, bd_prov = [x.strip() for x in b_dest.split(",", 1)]
            if d_prov == bd_prov and (d_city in bd_city or bd_city in d_city):
                dest_matches = True
        elif not dest_matches and b_dest and "," in b_dest and "," not in norm_dest:
            bd_city = b_dest.split(",", 1)[0].strip()
            if norm_dest == bd_city or norm_dest in bd_city:
                dest_matches = True

        if origin_matches and dest_matches:
            matched_candidates.append(b)

    if not matched_candidates:
        return None

    if 1 <= skid_count <= 5:
        if skid_count == 5:
            cand_5c = next((c for c in matched_candidates if c.get("break_name") == "5C"), None)
            if cand_5c:
                return cand_5c
        cand_l5c = next((c for c in matched_candidates if c.get("break_name") in ["L5C", "<5C", "L5", "<5"]), None)
        if cand_l5c:
            return cand_l5c
    elif skid_count == 6:
        cand_1m = next((c for c in matched_candidates if c.get("break_name") == "1M"), None)
        if cand_1m:
            return cand_1m
    elif skid_count == 7:
        cand_2m = next((c for c in matched_candidates if c.get("break_name") == "2M"), None)
        if cand_2m:
            return cand_2m
    elif skid_count == 8:
        cand_3m = next((c for c in matched_candidates if c.get("break_name") == "3M"), None)
        if not cand_3m:
            cand_3m = next((c for c in matched_candidates if c.get("break_name") == "5M"), None)
        if cand_3m:
            return cand_3m
    elif skid_count == 9:
        cand_4m = next((c for c in matched_candidates if c.get("break_name") == "4M"), None)
        if not cand_4m:
            cand_4m = next((c for c in matched_candidates if c.get("break_name") == "5M"), None)
        if cand_4m:
            return cand_4m
    elif skid_count == 10:
        cand_10m = next((c for c in matched_candidates if c.get("break_name") == "10M"), None)
        if not cand_10m:
            cand_10m = next((c for c in matched_candidates if c.get("break_name") == "5M"), None)
        if cand_10m:
            return cand_10m

    for c in matched_candidates:
        min_u = float(c.get("min_units") or 0.0)
        max_u = float(c.get("max_units") or 999999.0)
        if min_u <= skid_count <= max_u:
            return c

    return None


def match_lane_minimum(
    minimums: List[Dict[str, Any]],
    origin: str,
    destination: str
) -> Optional[Dict[str, Any]]:
    """Rule 12: Finds carrier minimum charge for the matching lane."""
    norm_origin = normalize_location_string(origin)
    norm_dest = normalize_location_string(destination)
    fsa_orig = extract_fsa(origin)
    fsa_dest = extract_fsa(destination)

    for m in minimums:
        m_orig = normalize_location_string(m.get("origin_spec") or "")
        m_dest = normalize_location_string(m.get("dest_spec") or "")

        if (m_orig == norm_origin or not m_orig) and (m_dest == norm_dest or not m_dest):
            return m

        if fsa_orig and fsa_dest:
            orig_ok = (m_orig == norm_origin) or (m_orig == fsa_orig) or (extract_fsa(m_orig) == fsa_orig)
            dest_ok = (m_dest == norm_dest) or (m_dest == fsa_dest) or (extract_fsa(m_dest) == fsa_dest)
            if orig_ok and dest_ok:
                return m

        if m_orig and m_dest and "," in norm_origin and "," in norm_dest:
            o_city, o_prov = [x.strip() for x in norm_origin.split(",", 1)]
            d_city, d_prov = [x.strip() for x in norm_dest.split(",", 1)]
            mo_city, mo_prov = [x.strip() for x in m_orig.split(",", 1)] if "," in m_orig else (m_orig, "")
            md_city, md_prov = [x.strip() for x in m_dest.split(",", 1)] if "," in m_dest else (m_dest, "")
            if o_prov == mo_prov and d_prov == md_prov and (o_city in mo_city or mo_city in o_city) and (d_city in md_city or md_city in d_city):
                return m
        elif m_orig and m_dest:
            mo_city = m_orig.split(",", 1)[0].strip() if "," in m_orig else m_orig
            md_city = m_dest.split(",", 1)[0].strip() if "," in m_dest else m_dest
            if (norm_origin == mo_city or norm_origin in mo_city) and (norm_dest == md_city or norm_dest in md_city):
                return m

    return minimums[0] if minimums else None


def _is_fuel_surcharge_row(s: Dict[str, Any]) -> bool:
    code = (s.get("surcharge_code") or "").strip().upper()
    cond = (s.get("condition_type") or "").strip().lower()
    return code in ("FSC", "FUEL") or cond in ("fuel", "fsc")


def evaluate_surcharges(
    surcharges: List[Dict[str, Any]],
    requested_accessorials: List[str],
    destination: str,
    billable_weight: float,
    base_rate: float,
    actual_weight: Optional[float] = None,
    rated_weight: Optional[float] = None,
    pre_min_freight: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Rule 11: Apply surcharges only when their conditions are met, and list each one separately.
    Handles flat fees, percentage surcharges (POST_MIN_FREIGHT vs PRE_MIN_FREIGHT) with min/max caps,
    CWT fees (ACTUAL, BILLABLE, or RATED weight base) with min/max caps, waived items,
    and blocks incomplete quotes when a triggered accessorial has an unparsed/null amount.
    """
    active_surcharges = []
    total_surcharge_dec = Decimal("0.00")
    req_set = {a.lower().strip() for a in requested_accessorials}

    dest_province = ""
    if "," in destination:
        dest_province = destination.split(",")[-1].strip().upper()

    actual_wt_dec = to_decimal(actual_weight if actual_weight is not None else billable_weight)
    billable_wt_dec = to_decimal(billable_weight)
    rated_wt_dec = to_decimal(rated_weight if rated_weight is not None else billable_weight)
    post_min_dec = to_decimal(base_rate)
    pre_min_dec = to_decimal(pre_min_freight if pre_min_freight is not None else base_rate)

    for s in surcharges:
        if _is_fuel_surcharge_row(s):
            continue

        code = (s.get("surcharge_code") or "").upper()
        cond_type = (s.get("condition_type") or "").lower()
        is_waived = bool(s.get("is_waived", 0))
        fee_type = (s.get("fee_type") or "FLAT").upper()
        raw_amount = s.get("amount")
        is_unparsed = bool(s.get("is_unparsed", 0)) or (raw_amount is None and not is_waived)

        min_fee_dec = to_decimal(s.get("min_fee") or 0.0)
        max_fee_dec = to_decimal(s["max_fee"]) if s.get("max_fee") is not None and float(s["max_fee"]) > 0 else None

        weight_base_mode = (s.get("weight_base") or "BILLABLE").strip().upper()
        if weight_base_mode == "ACTUAL":
            selected_weight_dec = actual_wt_dec
        elif weight_base_mode == "RATED":
            selected_weight_dec = rated_wt_dec
        else:
            selected_weight_dec = billable_wt_dec

        pct_base_mode = (s.get("pct_base") or "POST_MIN_FREIGHT").strip().upper()
        selected_pct_base_dec = pre_min_dec if pct_base_mode in ("PRE_MIN", "PRE_MIN_FREIGHT") else post_min_dec

        triggered = False

        if cond_type == "appointment" and ("appointment" in req_set or "notify" in req_set):
            triggered = True
        elif cond_type in ["after_hours", "after_hours_metro"] and "after_hours" in req_set:
            triggered = True
        elif cond_type == "amazon_delivery" and "amazon" in req_set:
            triggered = True
        elif cond_type == "dangerous_goods" and ("dangerous_goods" in req_set or "hazmat" in req_set):
            cond_expr = s.get("condition_expression")
            if cond_expr:
                try:
                    expr = json.loads(cond_expr) if isinstance(cond_expr, str) else cond_expr
                    w_min = to_decimal(expr.get("weight_min", 0))
                    w_max = to_decimal(expr.get("weight_max", 999999))
                    if w_min <= selected_weight_dec <= w_max:
                        triggered = True
                except Exception:
                    triggered = True
            else:
                triggered = True
        elif cond_type in ["liftgate", "tailgate", "power_tailgate"] and ("liftgate" in req_set or "tailgate" in req_set or "power_tailgate" in req_set):
            triggered = True
        elif cond_type == "residential_delivery" and ("residential" in req_set or "residential_delivery" in req_set):
            triggered = True
        elif cond_type == "residential_pickup" and "residential_pickup" in req_set:
            triggered = True
        elif cond_type in ["heated", "protective_service", "protect_from_freeze"] and ("heated" in req_set or "protective_service" in req_set):
            triggered = True
        elif cond_type == "reconsignment" and "reconsignment" in req_set:
            triggered = True
        elif cond_type == "storage" and "storage" in req_set:
            triggered = True
        elif cond_type == "tradeshow" and "tradeshow" in req_set:
            triggered = True
        elif cond_type == "inside_delivery" and "inside_delivery" in req_set:
            triggered = True
        elif cond_type == "expedited_monday" and "expedited_monday" in req_set:
            triggered = True
        elif cond_type in req_set or code.lower() in req_set:
            triggered = True
        elif cond_type.startswith("dest_province:"):
            target_prov = cond_type.split(":")[-1].strip().upper()
            if dest_province == target_prov:
                cond_expr = s.get("condition_expression")
                if cond_expr:
                    try:
                        expr = json.loads(cond_expr) if isinstance(cond_expr, str) else cond_expr
                        w_min = to_decimal(expr.get("weight_min", 0))
                        w_max = to_decimal(expr.get("weight_max", 999999))
                        if w_min <= selected_weight_dec <= w_max:
                            triggered = True
                    except Exception:
                        triggered = True
                else:
                    triggered = True

        if not triggered:
            continue

        if is_unparsed:
            raise ValueError(
                f"INCOMPLETE_QUOTE_UNPARSED_ACCESSORIAL: Requested accessorial '{s.get('name', code)}' ({code}) "
                f"has an unverified/missing price on this tariff."
            )

        rate_amt_dec = to_decimal(raw_amount or 0.0)

        if is_waived:
            calc_dec = Decimal("0.00")
        elif fee_type == "FLAT":
            calc_dec = rate_amt_dec
        elif fee_type == "PERCENTAGE":
            calc_dec = (rate_amt_dec / Decimal("100")) * selected_pct_base_dec
            if min_fee_dec > Decimal("0"):
                calc_dec = max(calc_dec, min_fee_dec)
            if max_fee_dec is not None:
                calc_dec = min(calc_dec, max_fee_dec)
        elif fee_type in ("CWT", "PER_CWT"):
            calc_dec = (selected_weight_dec / Decimal("100")) * rate_amt_dec
            if min_fee_dec > Decimal("0"):
                calc_dec = max(calc_dec, min_fee_dec)
            if max_fee_dec is not None:
                calc_dec = min(calc_dec, max_fee_dec)
        else:
            calc_dec = rate_amt_dec

        fee_rounded_dec = round_money(calc_dec)
        total_surcharge_dec += fee_rounded_dec

        active_surcharges.append({
            "code": code,
            "name": s["name"],
            "fee_type": fee_type,
            "amount": float(fee_rounded_dec),
            "is_waived": is_waived,
            "fsc_eligible": bool(s.get("fsc_eligible", 0)),
            "weight_base": weight_base_mode,
            "pct_base": pct_base_mode,
            "source_cell": s.get("source_cell", "Terms & Conditions")
        })

    return active_surcharges, float(round_money(total_surcharge_dec))


def calculate_quote_for_sheet(
    sheet_id: str,
    user_id: str,
    origin: str,
    destination: str,
    actual_weight: float,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    accessorials: Optional[List[str]] = None,
    shipment_date: Optional[str] = None,
    skid_count: Optional[int] = None,
    shipment_weight_unit: Optional[str] = None,
    pieces: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Rules 8–15: Core deterministic calculation engine.
    Never uses LLM reasoning for math. Pure deterministic Decimal Python code.
    Supports both CWT weight breaks and Skid-based LTL rating (MC + S x RateBreak).
    """
    sheet = get_rate_sheet(sheet_id, user_id)
    if not sheet:
        raise ValueError(f"Rate sheet {sheet_id} not found or unauthorized (Rule 28).")

    # Failsafe mapping gate: manual_override cannot bypass an unmapped failsafe sheet
    failsafe_status = (sheet.get("failsafe_status") or "ready").strip().lower()
    if failsafe_status in ("needs_mapping", "needs_user_input"):
        raise ValueError(
            f"Failsafe Gate (needs_mapping): Cannot quote from sheet '{sheet['carrier_name']}' "
            f"before column mapping is confirmed."
        )

    # Rule 19: Strict confirmation gate check (with manual broker override support after mapping is complete)
    if sheet["confirmation_status"] != "CONFIRMED" and not sheet.get("manual_override"):
        raise ValueError(
            f"Rule 19 Violation: Cannot quote from unconfirmed sheet '{sheet['carrier_name']}' "
            f"(Status: {sheet['confirmation_status']}). Confirmation required."
        )

    # Check unresolved critical structural flags on the sheet (bracket gaps, missing parcel divisor, missing min column)
    flagged_cells = get_rate_sheet_cells(sheet["id"], user_id, needs_review_only=True)
    for fc in flagged_cells:
        fname = (fc.get("field_name") or "").strip().upper()
        if fname == "BRACKET_GAP_DETECTED":
            raise ValueError(
                f"BRACKET_GAP_DETECTED: Cannot quote from sheet '{sheet['carrier_name']}' because weight brackets have an unresolved gap."
            )
        if fname == "MISSING_PARCEL_DIM_DIVISOR":
            raise ValueError(
                f"MISSING_PARCEL_DIM_DIVISOR: Cannot quote from parcel sheet '{sheet['carrier_name']}' without a confirmed DIM divisor."
            )
        if fname == "MISSING_MINIMUM_COLUMN" and not sheet.get("no_minimum_confirmed"):
            raise ValueError(
                f"MISSING_MINIMUM_COLUMN: Cannot quote from sheet '{sheet['carrier_name']}' until missing minimum column ($0.00 minimum) is explicitly confirmed."
            )

    if failsafe_status == "missing_minimum_column" and not sheet.get("no_minimum_confirmed"):
        raise ValueError(
            f"MISSING_MINIMUM_COLUMN: Cannot quote from sheet '{sheet['carrier_name']}' until missing minimum column ($0.00 minimum) is explicitly confirmed."
        )

    # Rule 16: Effective Date and Expiry Date validation (inclusive boundaries, blank expiry supported)
    if shipment_date:
        eff_date = (sheet.get("effective_date") or "").strip()
        exp_date = (sheet.get("expiry_date") or "").strip()
        if eff_date and shipment_date < eff_date:
            raise ValueError(f"Rule 16: Sheet not yet effective on {shipment_date} (Effective: {eff_date}).")
        if exp_date and shipment_date > exp_date:
            raise ValueError(f"Rule 16: Sheet expired on {exp_date} (Shipment Date: {shipment_date}).")

    rules = get_sheet_full_rules(sheet_id, user_id)
    accessorials = accessorials or []
    trace_steps = []

    mode = (sheet.get("mode") or "LTL").upper()
    sheet_weight_unit = sheet.get("weight_unit") or "lb"
    input_weight_unit = shipment_weight_unit or sheet_weight_unit
    weight_rounding_rule = (sheet.get("weight_rounding_rule") or "CEIL_1LB").upper()

    # Convert shipment weight into sheet's native weight unit if needed
    converted_actual_dec = convert_weight_unit(actual_weight, input_weight_unit, sheet_weight_unit)
    converted_actual_float = float(converted_actual_dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    converted_pieces = None
    if pieces:
        converted_pieces = []
        for p in pieces:
            p_wt, p_l, p_w, p_h, p_qty = _unpack_piece(p)
            p_wt_conv = convert_weight_unit(p_wt, input_weight_unit, sheet_weight_unit)
            converted_pieces.append((p_wt_conv, p_l, p_w, p_h, p_qty))

    # 1. Billable Weight Calculation (Rule 9)
    dim_min_pcf = None
    if sheet.get("dim_min_rule"):
        import re
        m_pcf = re.search(r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\s*(?:per|/)\s*(?:cu\.?\s*ft|cubic\s*foot|pcf)", str(sheet["dim_min_rule"]), re.IGNORECASE)
        if m_pcf:
            dim_min_pcf = float(m_pcf.group(1))
        elif "10" in str(sheet["dim_min_rule"]):
            dim_min_pcf = 10.0

    weight_info = calculate_billable_weight(
        actual_weight=converted_actual_float,
        length=length,
        width=width,
        height=height,
        dim_divisor=sheet.get("dim_divisor"),
        dim_min_pcf=dim_min_pcf,
        mode=mode,
        weight_rounding_rule=weight_rounding_rule,
        pieces=converted_pieces,
    )
    billable_weight = weight_info["billable_weight"]
    effective_actual_weight = weight_info["actual_weight"]

    trace_steps.append({
        "step": "Weight & DIM Calculation (Rule 9)",
        "input_weight": actual_weight,
        "input_weight_unit": input_weight_unit,
        "sheet_weight_unit": sheet_weight_unit,
        "actual_weight_lbs": effective_actual_weight,
        "dim_weight_lbs": weight_info["dim_weight"],
        "cubic_weight_lbs": weight_info["cubic_weight"],
        "billable_weight_lbs": billable_weight,
        "weight_rounding_rule": weight_rounding_rule,
        "divisor_used": weight_info["dim_divisor"],
        "dim_applied": weight_info["is_dim_billed"]
    })

    # Rule 18: Operational Limits & Mode Feasibility Check (Configurable per sheet)
    max_length_in = float(sheet.get("max_length_in") or 108.0)
    max_girth_in = float(sheet.get("max_girth_in") or 165.0)
    max_piece_weight = float(sheet.get("max_piece_weight") or 150.0)
    max_weight_limit = float(sheet.get("max_weight_limit") or 44000.0)

    if mode == "PARCEL":
        if converted_pieces:
            for idx_p, (p_wt, p_l, p_w, p_h, _p_qty) in enumerate(converted_pieces):
                if float(p_l) > max_length_in or float(p_w) > max_length_in or float(p_h) > max_length_in:
                    raise ValueError(f"Rule 18 Exclusion: Package single dimension exceeds parcel limit of {max_length_in:.0f} inches.")
                girth = 2.0 * (float(p_w) + float(p_h))
                if float(p_l) + girth > max_girth_in:
                    raise ValueError(
                        f"Rule 18 Exclusion: Package combined length and girth ({float(p_l) + girth:.1f} in) "
                        f"exceeds maximum parcel limit of {max_girth_in:.0f} inches."
                    )
                if float(p_wt) > max_piece_weight:
                    raise ValueError(
                        f"Rule 18 Exclusion: Piece actual weight {float(p_wt)} lbs exceeds maximum parcel limit of "
                        f"{max_piece_weight:.0f} lbs (requires LTL or Freight service)."
                    )
        else:
            if length and width and height:
                if float(length) > max_length_in or float(width) > max_length_in or float(height) > max_length_in:
                    raise ValueError(f"Rule 18 Exclusion: Package single dimension exceeds parcel limit of {max_length_in:.0f} inches.")
                girth = 2.0 * (float(width) + float(height))
                if float(length) + girth > max_girth_in:
                    raise ValueError(
                        f"Rule 18 Exclusion: Package combined length and girth ({float(length) + girth:.1f} in) "
                        f"exceeds maximum parcel limit of {max_girth_in:.0f} inches."
                    )
            # Check parcel weight limit against actual physical weight (allowing DIM weight > 150 lb when physical weight <= 150 lb)
            if effective_actual_weight > max_piece_weight:
                raise ValueError(
                    f"Rule 18 Exclusion: Shipment weight {effective_actual_weight} lbs exceeds maximum parcel limit of "
                    f"{max_piece_weight:.0f} lbs (requires LTL or Freight service)."
                )
    elif mode == "LTL":
        if billable_weight > max_weight_limit:
            raise ValueError(
                f"Rule 18 Exclusion: Shipment weight {billable_weight} lbs exceeds legal LTL capacity of "
                f"{max_weight_limit:,.0f} lbs (requires Dedicated FTL equipment)."
            )

    rating_basis = (sheet.get("rating_basis") or "WEIGHT_CWT").upper()
    max_skid_cap = int(sheet.get("max_skid_capacity") or 10)
    allow_deficit = bool(sheet.get("allow_deficit_rating", 1))
    matched_min = None
    skid_charge = None
    mc_charge = 0.0
    is_deficit_rated = False
    deficit_savings = 0.0
    deficit_weight = 0.0
    rated_weight = float(billable_weight)
    min_applied = False

    if rating_basis in ("PER_SKID", "PALLET_TIER"):
        # Rule 18 & 25: Skid-based LTL rating
        if skid_count is None or skid_count <= 0:
            raise ValueError(f"Rule 25 Exclusion: Rate sheet '{sheet['carrier_name']}' rates on a per-skid basis, but no skid count was provided.")
        if skid_count > max_skid_cap:
            raise ValueError(f"Rule 18 Exclusion: Skid count ({skid_count}) exceeds maximum carrier LTL capacity of {max_skid_cap} skids (requires Dedicated FTL equipment).")

        matched_break = match_skid_break(rules["breaks"], origin, destination, skid_count)
        if not matched_break:
            raise ValueError(f"Rule 18 / Rule 24 Exclusion: Lane not served: {sheet['carrier_name']} does not publish confirmed skid rates between {origin} and {destination} for {skid_count} skids.")

        matched_min = match_lane_minimum(rules["minimums"], origin, destination)
        mc_dec = round_money(matched_min["min_charge"]) if matched_min else Decimal("0.00")
        mc_charge = float(mc_dec)
        rate_val_dec = to_decimal(matched_break["base_rate"])
        rate_val = float(rate_val_dec)
        rate_type = (matched_break.get("rate_type") or "PER_SKID").upper()

        if rate_type == "FLAT":
            skid_dec = round_money(rate_val_dec)
            base_dec = round_money(mc_dec + skid_dec)
            skid_charge = float(skid_dec)
            base_charge = float(base_dec)
            base_formula = f"${mc_charge:.2f} (MC) + Flat Rate ${rate_val:.2f} [{matched_break['break_name']}] = ${base_charge:.2f}" if mc_charge > 0 else f"Flat Rate ${rate_val:.2f} [{matched_break['break_name']}] = ${base_charge:.2f}"
        else:
            skid_dec = round_money(to_decimal(skid_count) * rate_val_dec)
            base_dec = round_money(mc_dec + skid_dec)
            skid_charge = float(skid_dec)
            base_charge = float(base_dec)
            base_formula = f"${mc_charge:.2f} (MC) + ({skid_count} skid{'s' if skid_count != 1 else ''} x ${rate_val:.2f} [{matched_break['break_name']}]) = ${base_charge:.2f}" if mc_charge > 0 else f"{skid_count} skid{'s' if skid_count != 1 else ''} x ${rate_val:.2f} [{matched_break['break_name']}] = ${base_charge:.2f}"

        min_charge = mc_charge
        min_charge_adjustment = 0.0
        effective_freight_dec = base_dec
        natural_charge_dec = base_dec

        trace_steps.append({
            "step": f"Skid-Based LTL Base Rate Calculation ({'Flat' if rate_type == 'FLAT' else 'Per-Skid'} Formula: MC + SkidCharge)",
            "lane": f"{origin} -> {destination}",
            "skid_count": skid_count,
            "break_name": matched_break["break_name"],
            "rate_value": rate_val,
            "rate_type": rate_type,
            "skid_charge": skid_charge,
            "base_cost_mc": mc_charge,
            "base_charge": base_charge,
            "formula": base_formula,
            "source_coordinate": matched_break.get("source_cell", "")
        })
    else:
        # 2. Match Lane Rate Break (Rule 8, 10)
        if skid_count is not None and skid_count > max_skid_cap:
            raise ValueError(f"Rule 18 Exclusion: Skid count ({skid_count}) exceeds maximum carrier LTL capacity of {max_skid_cap} skids (requires Dedicated FTL equipment).")

        matched_break = match_lane_break(
            rules["breaks"],
            origin,
            destination,
            billable_weight,
            skid_count=skid_count,
            allow_deficit_rating=allow_deficit,
        )
        if not matched_break:
            raise ValueError(f"Rule 18 / Rule 24 Exclusion: Lane not served: {sheet['carrier_name']} does not publish confirmed rates between {origin} and {destination} for weight {billable_weight} lbs.")

        matched_min = match_lane_minimum(rules["minimums"], origin, destination)
        min_charge_dec = round_money(matched_min["min_charge"]) if matched_min else Decimal("0.00")
        min_charge = float(min_charge_dec)

        natural_break = matched_break.get("natural_break") or matched_break
        rate_type = (natural_break.get("rate_type") or "CWT").upper()
        natural_rate_dec = to_decimal(natural_break["base_rate"])
        billable_dec = to_decimal(billable_weight)

        if rate_type == "CWT":
            natural_charge_dec = round_money((billable_dec / Decimal("100")) * natural_rate_dec)
        elif rate_type == "FLAT":
            natural_charge_dec = round_money(natural_rate_dec)
        else:
            natural_charge_dec = round_money(billable_dec * natural_rate_dec)

        # Check candidate deficit rating vs Carrier Minimum Floor on Freight Alone
        cand_deficit = bool(matched_break.get("is_deficit_rated")) and matched_break.get("effective_base_charge") is not None
        if cand_deficit:
            bumped_charge_dec = round_money(matched_break["effective_base_charge"])
            pre_min_best_dec = min(natural_charge_dec, bumped_charge_dec)
        else:
            bumped_charge_dec = natural_charge_dec
            pre_min_best_dec = natural_charge_dec

        # Carrier Minimum Floor applies to freight alone before fuel and accessorials
        effective_freight_dec = max(pre_min_best_dec, min_charge_dec)
        realized_savings_dec = max(Decimal("0.00"), max(natural_charge_dec, min_charge_dec) - effective_freight_dec)

        if cand_deficit and realized_savings_dec > Decimal("0.00"):
            is_deficit_rated = True
            deficit_savings = float(realized_savings_dec)
            deficit_weight = float(to_decimal(matched_break.get("deficit_weight", 0.0)))
            rated_weight = float(billable_dec + to_decimal(deficit_weight))
            base_dec = bumped_charge_dec
            rate_val = float(to_decimal(matched_break["base_rate"]))
            base_charge = float(base_dec)
            base_formula = f"Deficit Bumped ({rated_weight:,.0f} lbs / 100) x ${rate_val:.2f} [{matched_break['break_name']}] = ${base_charge:.2f}"
            trace_steps.append({
                "step": "Base Rate Calculation with Deficit Weight Rating (Rule 8 / Deficit Bumping)",
                "lane": f"{origin} -> {destination}",
                "natural_weight": billable_weight,
                "deficit_bumped_weight": rated_weight,
                "deficit_weight_added": deficit_weight,
                "break_name": f"{matched_break['break_name']} (Deficit Rated)",
                "rate_value": rate_val,
                "rate_type": rate_type,
                "base_charge": base_charge,
                "deficit_savings": deficit_savings,
                "source_coordinate": matched_break.get("source_cell", ""),
                "formula": base_formula
            })
        else:
            # Either no deficit candidate or minimum floor overrode both (realized_savings == 0)
            is_deficit_rated = False
            deficit_savings = 0.0
            deficit_weight = 0.0
            rated_weight = float(billable_weight)
            matched_break = dict(natural_break)
            matched_break["is_deficit_rated"] = False
            matched_break["deficit_weight"] = 0.0
            matched_break["deficit_savings"] = 0.0
            rate_val = float(natural_rate_dec)
            base_dec = natural_charge_dec
            base_charge = float(base_dec)

            if rate_type == "CWT":
                if skid_count is not None and skid_count > 0:
                    base_formula = f"{skid_count} skid{'s' if skid_count != 1 else ''} ({billable_weight:,.0f} lbs / 100) x ${rate_val:.2f} [{matched_break['break_name']}] = ${base_charge:.2f}"
                else:
                    base_formula = f"({billable_weight:,.0f} lbs / 100) x ${rate_val:.2f} [{matched_break['break_name']}] = ${base_charge:.2f}"
            elif rate_type == "FLAT":
                base_formula = f"Flat Rate [{matched_break['break_name']}] = ${base_charge:.2f}"
            else:
                base_formula = f"{billable_weight:,.0f} units x ${rate_val:.2f} [{matched_break['break_name']}] = ${base_charge:.2f}"

            trace_steps.append({
                "step": "Base Rate Calculation (Rule 8)",
                "lane": f"{origin} -> {destination}",
                "break_name": matched_break["break_name"],
                "rate_value": rate_val,
                "rate_type": rate_type,
                "base_charge": base_charge,
                "source_coordinate": matched_break.get("source_cell", ""),
                "formula": base_formula
            })

        # Stage 7: Carrier Minimum Floor on Freight Alone (Rule 12)
        min_charge_adjustment_dec = max(Decimal("0.00"), min_charge_dec - base_dec)
        min_charge_adjustment = float(min_charge_adjustment_dec)
        min_applied = min_charge_adjustment_dec > Decimal("0.00")
        if min_applied:
            trace_steps.append({
                "step": "Minimum Charge Floor on Freight (Rule 12)",
                "freight_pre_min": base_charge,
                "carrier_min_charge": min_charge,
                "adjustment_added": min_charge_adjustment,
                "effective_freight": float(effective_freight_dec),
                "source_coordinate": matched_min.get("source_cell", "") if matched_min else ""
            })

    # Stage 8a: Itemized Non-Fuel Accessorial Surcharges (Rule 11)
    applied_surcharges, non_fuel_surcharges_total = evaluate_surcharges(
        surcharges=rules["surcharges"],
        requested_accessorials=accessorials,
        destination=destination,
        billable_weight=billable_weight,
        base_rate=float(effective_freight_dec),
        actual_weight=effective_actual_weight,
        rated_weight=rated_weight,
        pre_min_freight=float(natural_charge_dec),
    )
    for sur in applied_surcharges:
        trace_steps.append({
            "step": f"Accessorial Surcharge: {sur['name']} (Rule 11)",
            "code": sur["code"],
            "amount": sur["amount"],
            "waived": sur["is_waived"],
            "source_coordinate": sur["source_cell"]
        })

    # Stage 8b: Three-State Fuel Surcharge (FSC) Evaluation on Effective Freight (+ Eligible Accessorials if configured)
    fuel_rows = [s for s in rules["surcharges"] if _is_fuel_surcharge_row(s)]
    req_set = {a.lower().strip() for a in accessorials}
    fsc_applies_to_acc = bool(sheet.get("fsc_applies_to_accessorials", 0))
    fuel_precedence = (sheet.get("fuel_precedence") or "SHEET_FIRST").upper()

    if fsc_applies_to_acc:
        # When fsc_applies_to_accessorials is enabled on the sheet, include non-waived accessorials
        # (either all non-fuel accessorials or those marked fsc_eligible if any have fsc_eligible=True)
        any_explicit_eligible = any(s.get("fsc_eligible") for s in applied_surcharges)
        acc_for_fsc_dec = sum(
            (to_decimal(s["amount"]) for s in applied_surcharges if (s.get("fsc_eligible") if any_explicit_eligible else not s.get("is_waived"))),
            Decimal("0.00")
        )
        fsc_base_dec = effective_freight_dec + acc_for_fsc_dec
    else:
        fsc_base_dec = effective_freight_dec

    fsc_amount_dec = Decimal("0.00")
    if fuel_rows:
        frow = fuel_rows[0]
        f_included = bool(frow.get("is_included", 0)) or bool(frow.get("is_waived", 0))
        f_raw_amt = frow.get("amount")
        f_unparsed = bool(frow.get("is_unparsed", 0)) or (f_raw_amt is None and not f_included)
        f_fee_type = (frow.get("fee_type") or "PERCENTAGE").upper()

        if f_included:
            # State 1: Fuel Included (0% FSC) -> $0.00, never query benchmark index
            fsc_amount_dec = Decimal("0.00")
            applied_surcharges.append({
                "code": "FSC",
                "name": frow.get("name", "Fuel Surcharge (Included)"),
                "fee_type": f_fee_type,
                "amount": 0.0,
                "is_waived": True,
                "is_included": True,
                "source_cell": frow.get("source_cell", "Terms & Conditions")
            })
        elif f_unparsed:
            if sheet.get("fsc_passthrough") or "fuel" in req_set or "fsc" in req_set:
                fsc_calc = resolve_effective_fuel_surcharge(
                    user_id=user_id,
                    base_freight=float(fsc_base_dec),
                    sheet_fsc_pct=None,
                    is_fuel_included=False,
                    fuel_precedence=fuel_precedence,
                    shipment_date=shipment_date,
                    mode=mode,
                )
                fsc_amount_dec = round_money(fsc_calc["fsc_amount"])
                if fsc_amount_dec > Decimal("0.00"):
                    applied_surcharges.append({
                        "code": "FSC",
                        "name": f"Fuel Surcharge ({fsc_calc['source']})",
                        "fee_type": "PERCENTAGE",
                        "amount": float(fsc_amount_dec),
                        "is_waived": False,
                        "source_cell": "OTA Diesel Fuel Benchmark"
                    })
            else:
                raise ValueError("UNPARSED_FUEL_SURCHARGE: Tariff mentions a fuel surcharge with an unverified/missing rate.")
        else:
            # State 2: Published sheet fuel rate
            if f_fee_type == "FLAT":
                fsc_amount_dec = round_money(f_raw_amt)
                fsc_source = frow.get("name", "Sheet Fuel Surcharge")
            else:
                fsc_calc = resolve_effective_fuel_surcharge(
                    user_id=user_id,
                    base_freight=float(fsc_base_dec),
                    sheet_fsc_pct=float(f_raw_amt),
                    is_fuel_included=False,
                    fuel_precedence=fuel_precedence,
                    shipment_date=shipment_date,
                    mode=mode,
                )
                fsc_amount_dec = round_money(fsc_calc["fsc_amount"])
                fsc_source = fsc_calc["source"]

            if fsc_amount_dec > Decimal("0.00"):
                applied_surcharges.append({
                    "code": "FSC",
                    "name": f"Fuel Surcharge ({fsc_source})",
                    "fee_type": f_fee_type,
                    "amount": float(fsc_amount_dec),
                    "is_waived": False,
                    "source_cell": frow.get("source_cell", "Sheet FSC")
                })
                trace_steps.append({
                    "step": f"Fuel Surcharge: {fsc_source} (Rule 11)",
                    "code": "FSC",
                    "fsc_base": float(fsc_base_dec),
                    "amount": float(fsc_amount_dec),
                    "waived": False,
                    "source_coordinate": frow.get("source_cell", "Sheet FSC")
                })
    elif "fuel" in req_set or "fsc" in req_set or fuel_precedence == "BENCHMARK_FIRST":
        # State 3: No sheet fuel row, benchmark fallback requested
        fsc_calc = resolve_effective_fuel_surcharge(
            user_id=user_id,
            base_freight=float(fsc_base_dec),
            sheet_fsc_pct=None,
            is_fuel_included=False,
            fuel_precedence=fuel_precedence,
            shipment_date=shipment_date,
            mode=mode,
        )
        fsc_amount_dec = round_money(fsc_calc["fsc_amount"])
        if fsc_amount_dec > Decimal("0.00"):
            applied_surcharges.append({
                "code": "FSC",
                "name": f"Fuel Surcharge ({fsc_calc['source']})",
                "fee_type": "PERCENTAGE",
                "amount": float(fsc_amount_dec),
                "is_waived": False,
                "source_cell": "OTA Diesel Fuel Benchmark"
            })
            trace_steps.append({
                "step": f"Fuel Surcharge: {fsc_calc['source']} (Rule 11 / Canadian FSC Index)",
                "code": "FSC",
                "fsc_base": float(fsc_base_dec),
                "amount": float(fsc_amount_dec),
                "waived": False,
                "source_coordinate": "OTA Diesel Benchmark"
            })

    total_surcharges_dec = round_money(to_decimal(non_fuel_surcharges_total) + fsc_amount_dec)
    total_surcharges = float(total_surcharges_dec)

    # 5. Final Step Rounding (Rule 15)
    total_amount_dec = effective_freight_dec + total_surcharges_dec
    wholesale_total_dec = round_money(total_amount_dec, sheet.get("rounding_rule", "standard_2dp"))
    wholesale_total = float(wholesale_total_dec)
    trace_steps.append({
        "step": "Final-Step Rounding (Wholesale Net Total) (Rule 15)",
        "wholesale_total": wholesale_total,
        "rounding_rule": sheet.get("rounding_rule", "standard_2dp")
    })

    # Broker Margin & Markup Calculation
    markup_mode = sheet.get("markup_mode", "PERCENTAGE")
    markup_val_dec = to_decimal(sheet.get("markup_value") or 0.0)
    markup_val = float(markup_val_dec)
    broker_margin_dec = Decimal("0.00")
    if markup_val_dec > Decimal("0"):
        if markup_mode == "PERCENTAGE":
            broker_margin_dec = round_money(to_decimal(base_charge) * (markup_val_dec / Decimal("100")))
        elif markup_mode == "FLAT":
            broker_margin_dec = round_money(markup_val_dec)
        elif markup_mode == "CWT":
            broker_margin_dec = round_money((to_decimal(billable_weight) / Decimal("100")) * markup_val_dec)

        trace_steps.append({
            "step": f"Broker Margin Markup ({markup_mode}: {markup_val})",
            "wholesale_base": base_charge,
            "broker_margin": float(broker_margin_dec),
            "formula": f"{base_charge} x {markup_val}%" if markup_mode == "PERCENTAGE" else f"${markup_val}"
        })

    acc_markup_pct_dec = to_decimal(sheet.get("accessorial_markup_pct") or 0.0)
    acc_markup_pct = float(acc_markup_pct_dec)
    if acc_markup_pct_dec > Decimal("0") and total_surcharges_dec > Decimal("0"):
        acc_margin_dec = round_money(total_surcharges_dec * (acc_markup_pct_dec / Decimal("100")))
        broker_margin_dec = round_money(broker_margin_dec + acc_margin_dec)
        trace_steps.append({
            "step": f"Accessorial Margin Markup (+{acc_markup_pct}%)",
            "accessorial_margin": float(acc_margin_dec)
        })

    broker_margin = float(broker_margin_dec)
    client_total = round_currency(wholesale_total_dec + broker_margin_dec, sheet.get("rounding_rule", "standard_2dp"))
    final_total = client_total if broker_margin_dec > Decimal("0") else wholesale_total

    # Transit time resolution
    transit_days = None
    if rules.get("zones"):
        for z in rules["zones"]:
            if normalize_location_string(origin) == normalize_location_string(z["origin_spec"]) and \
               normalize_location_string(destination) == normalize_location_string(z["dest_spec"]):
                transit_days = z.get("transit_days")
                break

    # Rule 23: Flag any quote option that relies on a rate, surcharge or rule that was modified during human review or flagged 'needs review'
    flagged_coords = {c["cell_coord"].strip().upper() for c in flagged_cells if c.get("cell_coord")}

    flagged_reasons = []
    used_coords = []
    if matched_break.get("source_cell"):
        used_coords.append(("Base Rate", matched_break["source_cell"]))
    if matched_min and matched_min.get("source_cell"):
        used_coords.append(("Minimum Charge", matched_min["source_cell"]))
    for sur in applied_surcharges:
        if sur.get("source_cell"):
            used_coords.append((f"Surcharge ({sur['name']})", sur["source_cell"]))

    for label, coord in used_coords:
        clean_c = coord.strip().upper()
        for fc in flagged_coords:
            if fc in clean_c or clean_c in fc:
                flagged_reasons.append(f"{label} at {coord}")
                break

    if sheet.get("manual_override"):
        flagged_reasons.append("Manual Broker Override: Sheet enabled prior to agent verification")

    relies_on_flagged = len(flagged_reasons) > 0
    caution_badge = f"Caution: Relies on flagged/reviewed data ({', '.join(flagged_reasons)})" if relies_on_flagged else None

    formula_parts = [f"Base Freight: {base_formula} {sheet['currency']}"]
    if min_applied:
        formula_parts.append(f"Carrier Min Floor: ${ float(effective_freight_dec):.2f} (+${min_charge_adjustment:.2f})")
    if total_surcharges > 0:
        surcharge_strs = [f"{s['name']}: ${s['amount']:.2f}" for s in applied_surcharges]
        formula_parts.append(f"Surcharges: +${total_surcharges:.2f} ({', '.join(surcharge_strs)})")
    formula_parts.append(f"Wholesale: ${wholesale_total:.2f} {sheet['currency']}")
    if broker_margin > 0:
        formula_parts.append(f"Broker Markup (+{markup_val}%): +${broker_margin:.2f} → Client Quoted Rate: ${client_total:.2f} {sheet['currency']}")
    full_formula_str = " | ".join(formula_parts)

    return {
        "sheet_id": sheet["id"],
        "carrier_name": sheet["carrier_name"],
        "service_name": sheet["service_name"],
        "tariff_ref": sheet.get("tariff_ref"),
        "origin": origin,
        "destination": destination,
        "currency": sheet["currency"],
        "weight_unit": sheet["weight_unit"],
        "actual_weight": effective_actual_weight,
        "billable_weight": billable_weight,
        "rated_weight": rated_weight,
        "is_dim_billed": weight_info["is_dim_billed"],
        "base_rate": base_charge,
        "base_charge": base_charge,
        "effective_freight": float(effective_freight_dec),
        "rate_break": matched_break["break_name"],
        "source_coordinate": matched_break.get("source_cell", ""),
        "source_cell": matched_break.get("source_cell", ""),
        "surcharges": applied_surcharges,
        "fsc_amount": float(fsc_amount_dec),
        "accessorial_total": float(round_money(non_fuel_surcharges_total)),
        "total_surcharges": total_surcharges,
        "carrier_min_charge": min_charge,
        "min_charge_adjustment": min_charge_adjustment,
        "min_applied": min_applied,
        "is_deficit_rated": is_deficit_rated,
        "deficit_savings": deficit_savings,
        "deficit_weight": deficit_weight,
        "deficit_weight_added": deficit_weight,
        "wholesale_total": wholesale_total,
        "broker_margin": broker_margin,
        "final_total": final_total,
        "client_total": final_total,
        "rating_basis": rating_basis,
        "skid_count": skid_count,
        "skid_charge": skid_charge if rating_basis in ("PER_SKID", "PALLET_TIER") else None,
        "mc_base_cost": mc_charge if rating_basis in ("PER_SKID", "PALLET_TIER") else None,
        "transit_days": transit_days or 3,
        "relies_on_flagged_cell": relies_on_flagged,
        "caution_badge": caution_badge,
        "disclaimer": "Calculation from customer uploaded rate sheets. Non-binding quote (Rule 26).",
        "formula": full_formula_str,
        "calculation_work": trace_steps,
        "calculation_trace": trace_steps
    }


def check_rate_shift_anomaly(
    current_sheet: Dict[str, Any],
    user_id: str,
    origin: str,
    destination: str,
    actual_weight: float,
    length: Optional[float],
    width: Optional[float],
    height: Optional[float],
    accessorials: Optional[List[str]],
    current_total: float
) -> Optional[Dict[str, Any]]:
    """
    Rule 27: When a rate changes sharply from the previous version of a sheet
    (for example over 25%), flag it for the user to verify.
    """
    from services.ratesift_db_service import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM rs_rate_sheets
    WHERE user_id = ? AND carrier_name = ? AND service_name = ?
      AND version < ? AND confirmation_status = 'CONFIRMED'
      AND (is_benchmark = 0 OR is_benchmark IS NULL)
    ORDER BY version DESC LIMIT 1
    """, (user_id, current_sheet["carrier_name"], current_sheet["service_name"], current_sheet.get("version", 1)))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    prev_sheet = dict(row)
    try:
        prev_quote = calculate_quote_for_sheet(
            sheet_id=prev_sheet["id"],
            user_id=user_id,
            origin=origin,
            destination=destination,
            actual_weight=actual_weight,
            length=length,
            width=width,
            height=height,
            accessorials=accessorials,
            shipment_date=prev_sheet.get("effective_date")
        )
        prev_total = prev_quote["final_total"]
        if prev_total > 0:
            shift_pct = ((current_total - prev_total) / prev_total) * 100.0
            if abs(shift_pct) >= 25.0:
                direction = "increase" if shift_pct > 0 else "decrease"
                return {
                    "flagged": True,
                    "shift_pct": quantize_1dp(shift_pct),
                    "previous_version": prev_sheet.get("version", 1),
                    "previous_total": prev_total,
                    "current_total": current_total,
                    "message": f"Rule 27 Alert: Sharp rate {direction} of {shift_pct:+.1f}% detected compared to Version {prev_sheet.get('version', 1)} (${prev_total:.2f} -> ${current_total:.2f}). Please verify."
                }
    except Exception:
        pass
    return None


def _normalize_carrier_service_key(carrier_name: str, service_name: str) -> Tuple[str, str]:
    c_norm = " ".join((carrier_name or "").strip().split()).upper()
    s_norm = " ".join((service_name or "").strip().split()).upper()
    return (c_norm, s_norm)


def _lookup_fx_rate(fx_rates: Dict[str, Any], from_curr: str, to_curr: str) -> Optional[Decimal]:
    if not fx_rates:
        return None
    f_up = from_curr.upper()
    t_up = to_curr.upper()
    for candidate_key in (f"{f_up}_{t_up}", f"{f_up}/{t_up}", f"{f_up}-{t_up}", f_up):
        if candidate_key in fx_rates and fx_rates[candidate_key] is not None:
            return to_decimal(fx_rates[candidate_key])
    # Check inverse rate if provided
    for inv_key in (f"{t_up}_{f_up}", f"{t_up}/{f_up}", f"{t_up}-{f_up}"):
        if inv_key in fx_rates and fx_rates[inv_key] is not None:
            inv_val = to_decimal(fx_rates[inv_key])
            if inv_val > Decimal("0"):
                return Decimal("1") / inv_val
    return None


def quote_all_confirmed_carriers(
    user_id: str,
    origin: str,
    destination: str,
    actual_weight: float,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    accessorials: Optional[List[str]] = None,
    shipment_date: Optional[str] = None,
    skid_count: Optional[int] = None,
    shipment_weight_unit: Optional[str] = None,
    pieces: Optional[List[Any]] = None,
    target_currency: Optional[str] = None,
    fx_rates: Optional[Dict[str, Any]] = None,
    fx_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluates all confirmed rate sheets for a tenant, calculating quotes deterministically.
    Enforces Rule 16 (Date validity & warning), Rule 17 (Version precedence with name normalization),
    Rule 18 (Operational limits & mode feasibility), Rule 20 (Ranking & Mixed-Currency Guard),
    Rule 27 (Rate shift anomaly), and Rule 30 (Audit logging).
    """
    all_tenant_sheets = list_rate_sheets(user_id=user_id)
    confirmed_sheets = [
        s for s in all_tenant_sheets
        if (s.get("confirmation_status") == "CONFIRMED" or s.get("manual_override") == 1)
    ]

    valid_quotes = []
    excluded_sheets = []
    all_sheet_ids = [s["id"] for s in confirmed_sheets]

    ref_date = shipment_date or datetime.utcnow().strftime("%Y-%m-%d")

    # Step 1: Rule 16 - Effective & Expiry Date Filtering (inclusive boundaries, blank expiry allowed)
    date_valid_sheets = []
    for s in confirmed_sheets:
        eff_date = (s.get("effective_date") or "").strip()
        exp_date = (s.get("expiry_date") or "").strip()

        if eff_date and ref_date < eff_date:
            excluded_sheets.append({
                "sheet_id": s["id"],
                "carrier": s["carrier_name"],
                "service": s["service_name"],
                "version": s.get("version", 1),
                "reason": f"Rule 16 Warning: Rate sheet not yet effective for shipment date {ref_date} (Effective: {eff_date})."
            })
            continue

        if exp_date and ref_date > exp_date:
            excluded_sheets.append({
                "sheet_id": s["id"],
                "carrier": s["carrier_name"],
                "service": s["service_name"],
                "version": s.get("version", 1),
                "reason": f"Rule 16 Warning: Rate sheet expired on {exp_date} (Shipment date: {ref_date})."
            })
            continue

        date_valid_sheets.append(s)

    # Step 2: Rule 17 - Version Precedence Resolution (normalized carrier & service names)
    grouped_by_carrier_service: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for s in date_valid_sheets:
        key = _normalize_carrier_service_key(s["carrier_name"], s["service_name"])
        grouped_by_carrier_service.setdefault(key, []).append(s)

    sheets_to_quote = []
    for key, sheets in grouped_by_carrier_service.items():
        sorted_sheets = sorted(sheets, key=lambda x: (int(x.get("version") or 1), x.get("effective_date") or ""), reverse=True)
        newest_sheet = sorted_sheets[0]
        sheets_to_quote.append(newest_sheet)

        for old_sheet in sorted_sheets[1:]:
            excluded_sheets.append({
                "sheet_id": old_sheet["id"],
                "carrier": old_sheet["carrier_name"],
                "service": old_sheet["service_name"],
                "version": old_sheet.get("version", 1),
                "reason": f"Rule 17: Superceded by newer confirmed Version {newest_sheet.get('version', 1)} of {newest_sheet['carrier_name']}."
            })

    # Step 3: Quoting Loop with Rule 18 and Rule 27
    for sheet in sheets_to_quote:
        sid = sheet["id"]
        try:
            quote_res = calculate_quote_for_sheet(
                sheet_id=sid,
                user_id=user_id,
                origin=origin,
                destination=destination,
                actual_weight=actual_weight,
                length=length,
                width=width,
                height=height,
                accessorials=accessorials,
                shipment_date=ref_date,
                skid_count=skid_count,
                shipment_weight_unit=shipment_weight_unit,
                pieces=pieces,
            )

            shift_warning = check_rate_shift_anomaly(
                current_sheet=sheet,
                user_id=user_id,
                origin=origin,
                destination=destination,
                actual_weight=actual_weight,
                length=length,
                width=width,
                height=height,
                accessorials=accessorials,
                current_total=quote_res["final_total"]
            )
            quote_res["rate_shift_warning"] = shift_warning

            valid_quotes.append(quote_res)
        except Exception as e:
            excluded_sheets.append({
                "sheet_id": sid,
                "carrier": sheet["carrier_name"],
                "service": sheet["service_name"],
                "version": sheet.get("version", 1),
                "reason": str(e)
            })

    # Step 4: Multi-Currency Guard & Target-Currency FX Conversion
    if target_currency and valid_quotes:
        target_curr = target_currency.strip().upper()
        for q in valid_quotes:
            src_curr = (q.get("currency") or "CAD").strip().upper()
            if src_curr != target_curr:
                fx_dec = _lookup_fx_rate(fx_rates or {}, src_curr, target_curr)
                if fx_dec is None:
                    raise ValueError(
                        f"Missing FX rate to convert {src_curr} to {target_curr}. Provide fx_rates['{src_curr}_{target_curr}']."
                    )
                q["original_currency"] = src_curr
                q["original_final_total"] = q["final_total"]
                q["fx_rate_applied"] = float(fx_dec)
                q["fx_date"] = fx_date or ref_date
                q["currency"] = target_curr
                q["base_rate"] = float(round_money(to_decimal(q["base_rate"]) * fx_dec))
                q["base_charge"] = q["base_rate"]
                q["effective_freight"] = float(round_money(to_decimal(q["effective_freight"]) * fx_dec))
                q["total_surcharges"] = float(round_money(to_decimal(q["total_surcharges"]) * fx_dec))
                q["wholesale_total"] = float(round_money(to_decimal(q["wholesale_total"]) * fx_dec))
                q["final_total"] = float(round_money(to_decimal(q["final_total"]) * fx_dec))
                q["client_total"] = q["final_total"]

    distinct_currencies = {(q.get("currency") or "CAD").strip().upper() for q in valid_quotes}
    mixed_currencies_detected = len(distinct_currencies) > 1

    quotes_by_currency: Dict[str, List[Dict[str, Any]]] = {}
    for q in valid_quotes:
        curr_key = (q.get("currency") or "CAD").strip().upper()
        quotes_by_currency.setdefault(curr_key, []).append(q)
    for curr_key, q_list in quotes_by_currency.items():
        q_list.sort(key=lambda q: (q["final_total"], q.get("transit_days") or 99))

    # Rule 20: Default Multi-Tier Ranking (Lowest Price -> Transit Time)
    valid_quotes.sort(key=lambda q: (q["final_total"], q.get("transit_days") or 99))

    # Log Immutable Audit Trail (Rule 30)
    quote_id = f"RS-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    shipment_inputs = {
        "origin": origin,
        "destination": destination,
        "actual_weight": actual_weight,
        "length": length,
        "width": width,
        "height": height,
        "accessorials": accessorials,
        "shipment_date": ref_date,
        "skid_count": skid_count,
        "target_currency": target_currency,
    }

    combined_trace = [q["calculation_trace"] for q in valid_quotes]

    log_quote_audit(
        user_id=user_id,
        quote_id=quote_id,
        shipment_inputs=shipment_inputs,
        sheets_considered=all_sheet_ids,
        sheets_excluded=excluded_sheets,
        calculation_trace=combined_trace,
        final_results=valid_quotes
    )

    message = None
    if len(all_tenant_sheets) == 0:
        message = "No rate sheets uploaded yet. Please upload your carrier tariffs in Carrier Tariffs to calculate quotes."
    elif len(valid_quotes) == 0:
        message = "No valid rates found for this lane across your uploaded sheets."
    elif mixed_currencies_detected:
        message = (
            f"Multiple currencies detected ({', '.join(sorted(distinct_currencies))}). "
            f"Quotes are grouped by currency in quotes_by_currency; supply target_currency and fx_rates for unified ranking."
        )

    return {
        "quote_id": quote_id,
        "timestamp": datetime.utcnow().isoformat(),
        "total_options": len(valid_quotes),
        "quotes": valid_quotes,
        "quotes_by_currency": quotes_by_currency,
        "mixed_currencies_detected": mixed_currencies_detected,
        "excluded_sheets": excluded_sheets,
        "message": message,
        "disclaimer": "Calculation from customer uploaded rate sheets. Non-binding quote (Rule 26)."
    }
