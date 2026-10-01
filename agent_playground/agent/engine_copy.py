"""
Copied Deterministic Rating Engine for Agent Playground
100% faithful copy of RateSift rating math. Operates independently of website services.
Enforces Rules 8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 21, 22, 24, 26.
"""
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP

def round_currency(val: float) -> float:
    """Rule 15: Half-up rounding to 2 decimal places at the final step."""
    d = Decimal(str(val))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def calculate_billable_weight(
    actual_weight: float,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    dim_divisor: float = 139.0
) -> Dict[str, Any]:
    """
    Rule 9: Calculate dimensional weight using divisor (139), and bill on the greater.
    """
    dim_weight = 0.0
    dim_divisor = dim_divisor if dim_divisor > 0 else 139.0

    if length and width and height and length > 0 and width > 0 and height > 0:
        cubic_inches = float(length) * float(width) * float(height)
        dim_weight = cubic_inches / dim_divisor

    billable_weight = max(actual_weight, dim_weight)
    
    return {
        "actual_weight": actual_weight,
        "dim_weight": round(dim_weight, 2),
        "billable_weight": round(billable_weight, 2),
        "is_dim_billed": billable_weight > actual_weight,
        "dim_divisor": dim_divisor
    }

def normalize_loc(loc: str) -> str:
    """Normalizes location strings for consistent lane matching (e.g. 'Calgary, AB')."""
    if not loc:
        return ""
    return " ".join(loc.strip().upper().split()).replace(".", "")

def match_lane_rate(tariff: Dict[str, Any], origin: str, destination: str, billable_weight: float) -> Optional[Dict[str, Any]]:
    """Rule 8 & 10: Match lane and weight bracket deterministically."""
    norm_orig = normalize_loc(origin)
    norm_dest = normalize_loc(destination)

    matched_breaks = []
    for b in tariff.get("breaks", []):
        bo = normalize_loc(b.get("origin", ""))
        bd = normalize_loc(b.get("destination", ""))

        orig_ok = (bo == norm_orig) or (bo == "*") or (bo in norm_orig or norm_orig in bo)
        dest_ok = (bd == norm_dest) or (bd == "*") or (bd in norm_dest or norm_dest in bd)

        if orig_ok and dest_ok:
            matched_breaks.append(b)

    if not matched_breaks:
        return None

    # Find matching weight bracket
    for b in matched_breaks:
        if b["min_w"] <= billable_weight <= b["max_w"]:
            return b

    # If exceeding max, return highest break
    sorted_b = sorted(matched_breaks, key=lambda x: x["min_w"], reverse=True)
    return sorted_b[0]

def match_lane_minimum(tariff: Dict[str, Any], origin: str, destination: str) -> float:
    """Rule 12: Find carrier minimum charge floor."""
    norm_orig = normalize_loc(origin)
    norm_dest = normalize_loc(destination)

    for m in tariff.get("minimum_charges", []):
        mo = normalize_loc(m.get("origin", ""))
        md = normalize_loc(m.get("destination", ""))
        if (mo == norm_orig or mo == "*") and (md == norm_dest or md == "*"):
            return float(m["min_charge"])

    return 150.00

def evaluate_accessorials(
    tariff: Dict[str, Any],
    requested_accessorials: List[str],
    billable_weight: float,
    base_rate: float
) -> Tuple[List[Dict[str, Any]], float]:
    """Rule 11: Apply accessorial surcharges deterministically."""
    active_surcharges = []
    total_acc = 0.0
    req_set = {a.lower().strip() for a in requested_accessorials}

    tariff_accs = tariff.get("accessorials", {})
    for code, spec in tariff_accs.items():
        if code in req_set:
            fee_type = spec.get("type", "FLAT")
            amt = float(spec.get("amount", 0.0))
            min_fee = float(spec.get("min_fee", 0.0))

            calc_fee = 0.0
            if fee_type == "FLAT":
                calc_fee = amt
            elif fee_type == "PERCENTAGE":
                calc_fee = max((amt / 100.0) * base_rate, min_fee)
            elif fee_type == "CWT":
                calc_fee = (billable_weight / 100.0) * amt

            calc_fee = round(calc_fee, 2)
            total_acc += calc_fee
            active_surcharges.append({
                "code": code.upper(),
                "name": spec.get("name", code),
                "type": fee_type,
                "amount": calc_fee,
                "source": spec.get("source", "Tariff Rules")
            })

    return active_surcharges, round(total_acc, 2)

def calculate_single_quote(
    tariff: Dict[str, Any],
    origin: str,
    destination: str,
    actual_weight: float,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    accessorials: Optional[List[str]] = None,
    shipment_date: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Calculates quote for a single carrier tariff following all rules."""
    accessorials = accessorials or []

    # Rule 18: Operational Limits
    max_w = tariff.get("max_weight_limit")
    if max_w and actual_weight > max_w:
        return {"error": f"Rule 18: Shipment weight ({actual_weight} lbs) exceeds carrier operational limit ({max_w} lbs)."}

    min_w = tariff.get("min_weight_limit")
    if min_w and actual_weight < min_w:
        return {"error": f"Rule 18: Shipment weight ({actual_weight} lbs) below carrier minimum limit ({min_w} lbs)."}

    # Rule 9: DIM Weight
    w_info = calculate_billable_weight(actual_weight, length, width, height, tariff.get("dim_divisor", 139.0))
    billable_w = w_info["billable_weight"]

    # Rule 8 & 10: Match Rate
    break_match = match_lane_rate(tariff, origin, destination, billable_w)
    if not break_match:
        return {"error": f"Rule 24: Lane not served ({origin} → {destination})."}

    # Base Calculation
    rate_val = float(break_match["rate"])
    if break_match["rate_type"] == "CWT":
        raw_base = (billable_w / 100.0) * rate_val
    else:  # FLAT
        raw_base = rate_val

    # Rule 12: Minimum Charge
    min_floor = match_lane_minimum(tariff, origin, destination)
    min_charge_adjustment = 0.0
    if raw_base < min_floor:
        min_charge_adjustment = round(min_floor - raw_base, 2)
        base_rate = min_floor
    else:
        base_rate = round(raw_base, 2)

    # Fuel Surcharge
    fsc_pct = tariff.get("fuel_surcharge_pct", 0.0)
    fuel_surcharge = round((fsc_pct / 100.0) * base_rate, 2)

    # Rule 11: Accessorials
    active_accs, total_acc = evaluate_accessorials(tariff, accessorials, billable_w, base_rate)

    # Final Total (Rule 15)
    total_amount = round_currency(base_rate + fuel_surcharge + total_acc)

    return {
        "carrier_name": tariff["carrier_name"],
        "service_type": tariff["service_type"],
        "currency": tariff.get("currency", "CAD"),
        "origin": origin,
        "destination": destination,
        "actual_weight": actual_weight,
        "billable_weight": billable_w,
        "is_dim_billed": w_info["is_dim_billed"],
        "dim_weight": w_info["dim_weight"],
        "transit_days": break_match.get("transit_days", 3),
        "base_rate": base_rate,
        "raw_base_rate": round(raw_base, 2),
        "rate_per_cwt": rate_val if break_match["rate_type"] == "CWT" else None,
        "rate_type": break_match["rate_type"],
        "min_charge_floor": min_floor,
        "min_charge_adjustment": min_charge_adjustment,
        "fuel_surcharge": fuel_surcharge,
        "fuel_surcharge_pct": fsc_pct,
        "accessorials": active_accs,
        "total_accessorials": total_acc,
        "total_amount": total_amount,
        "rate_source": break_match.get("source", "Tariff Matrix"),
        "disclaimer": "Rule 26 Notice: Derived deterministically from customer uploaded rate sheets. Non-binding estimate."
    }

def quote_all_tariffs(
    tariffs: List[Dict[str, Any]],
    origin: str,
    destination: str,
    actual_weight: float,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    accessorials: Optional[List[str]] = None,
    shipment_date: Optional[str] = None
) -> Dict[str, Any]:
    """Rule 20, 21, 22: Rates all eligible tariffs and returns options and exclusions."""
    quotes = []
    excluded = []

    for t in tariffs:
        res = calculate_single_quote(t, origin, destination, actual_weight, length, width, height, accessorials, shipment_date)
        if "error" in res:
            excluded.append({
                "carrier_name": t["carrier_name"],
                "reason": res["error"]
            })
        else:
            quotes.append(res)

    # Rule 20: Default sort by lowest price first, transit time tie-breaker
    quotes.sort(key=lambda q: (q["total_amount"], q["transit_days"]))

    return {
        "quotes": quotes,
        "excluded": excluded,
        "total_options": len(quotes)
    }
