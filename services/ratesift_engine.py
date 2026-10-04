import math
from datetime import datetime
import uuid
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP




from services.ratesift_db_service import (
    get_rate_sheet,
    get_sheet_full_rules,
    list_rate_sheets,
    get_rate_sheet_cells,
    log_quote_audit
)
from services.fsa_resolver_service import resolve_location, extract_fsa
from services.fuel_index_service import resolve_effective_fuel_surcharge

def round_currency(val: float, rule: str = "standard_2dp") -> float:
    """
    Rule 15: Round only at the final step, and follow each sheet's own rounding rules.
    Standard: Half-up to 2 decimal places.
    """
    d = Decimal(str(val))
    if rule == "ceiling_cent":
        return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:  # standard_2dp
        return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def calculate_billable_weight(
    actual_weight: float,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    dim_divisor: float = 139.0,
    dim_min_pcf: Optional[float] = None
) -> Dict[str, Any]:
    """
    Rule 9: Calculate dimensional weight using the carrier's own divisor and rules,
    and bill on the greater of actual weight and dimensional weight.
    """
    dim_weight = 0.0
    cubic_weight = 0.0
    dim_divisor = dim_divisor if dim_divisor > 0 else 139.0

    if length and width and height and length > 0 and width > 0 and height > 0:
        cubic_inches = float(length) * float(width) * float(height)
        dim_weight = cubic_inches / dim_divisor
        
        # Density check (e.g. 10 lbs per cu ft rule)
        if dim_min_pcf and dim_min_pcf > 0:
            cubic_feet = cubic_inches / 1728.0
            cubic_weight = cubic_feet * dim_min_pcf

    billable_weight = max(actual_weight, dim_weight, cubic_weight)
    
    return {
        "actual_weight": actual_weight,
        "dim_weight": round(dim_weight, 2),
        "cubic_weight": round(cubic_weight, 2),
        "billable_weight": round(billable_weight, 2),
        "is_dim_billed": billable_weight > actual_weight,
        "dim_divisor": dim_divisor
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
    billable_weight: float
) -> Optional[Dict[str, Any]]:
    """
    Rule 8 & 10: Matches exact lane and weight break deterministically.
    Supports Canadian Postal FSA matching and SMC3 Deficit Weight Rating (Bumping Rule).
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

        # Check if lane matches canonical or raw
        origin_matches = (b_orig == norm_origin) or (not b_orig and not b_dest)
        dest_matches = (b_dest == norm_dest) or (not b_orig and not b_dest)

        # Allow FSA direct match (e.g. if tariff specifies 'M5V' or 'T2P')
        if not origin_matches and fsa_orig and (b_orig == fsa_orig or extract_fsa(b_orig) == fsa_orig):
            origin_matches = True
        if not dest_matches and fsa_dest and (b_dest == fsa_dest or extract_fsa(b_dest) == fsa_dest):
            dest_matches = True

        # Allow partial city match if province matches (e.g. 'CALGARY, AB' matches 'CALGARY, AB')
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

    # 2. Select bracket based on billable weight: min_weight <= billable_weight <= max_weight
    matching_break = None
    for b in matched_candidates:
        if b["min_weight"] <= billable_weight <= b["max_weight"]:
            matching_break = b
            break

    # If weight exceeds max break, select the highest available tier break (e.g. CWT:10000 or CWT:20000)
    if not matching_break and matched_candidates:
        sorted_candidates = sorted(matched_candidates, key=lambda x: x["min_weight"], reverse=True)
        if billable_weight >= sorted_candidates[0]["min_weight"]:
            matching_break = sorted_candidates[0]

    if not matching_break:
        return None

    # 3. Deficit Weight Rating (SMC3 / Canadian Freight Bumping Rule):
    # Check if bumping to the minimum weight of a higher bracket produces a lower base charge.
    is_deficit_rated = False
    deficit_savings = 0.0
    deficit_weight = 0.0
    effective_charge = None
    effective_break = matching_break

    if matching_break.get("rate_type", "CWT").upper() == "CWT":
        natural_rate = float(matching_break["base_rate"])
        natural_charge = (billable_weight / 100.0) * natural_rate
        best_charge = natural_charge

        for higher_b in matched_candidates:
            if higher_b["min_weight"] > billable_weight and higher_b.get("rate_type", "CWT").upper() == "CWT":
                bumped_wt = float(higher_b["min_weight"])
                bumped_rate = float(higher_b["base_rate"])
                bumped_charge = (bumped_wt / 100.0) * bumped_rate
                if bumped_charge < best_charge:
                    best_charge = bumped_charge
                    effective_break = higher_b
                    is_deficit_rated = True
                    deficit_weight = round(bumped_wt - billable_weight, 2)
                    deficit_savings = round(natural_charge - bumped_charge, 2)
                    effective_charge = round(bumped_charge, 2)

    result_break = dict(effective_break)
    result_break["is_deficit_rated"] = is_deficit_rated
    result_break["deficit_weight"] = deficit_weight
    result_break["deficit_savings"] = deficit_savings
    result_break["effective_base_charge"] = effective_charge
    return result_break

def match_lane_minimum(
    minimums: List[Dict[str, Any]],
    origin: str,
    destination: str
) -> Optional[Dict[str, Any]]:
    """Rule 12: Finds carrier minimum charge for the matching lane."""
    norm_origin = normalize_location_string(origin)
    norm_dest = normalize_location_string(destination)

    for m in minimums:
        m_orig = normalize_location_string(m.get("origin_spec") or "")
        m_dest = normalize_location_string(m.get("dest_spec") or "")

        if (m_orig == norm_origin or not m_orig) and (m_dest == norm_dest or not m_dest):
            return m
        
        # City/Prov match
        if m_orig and m_dest and "," in norm_origin and "," in norm_dest:
            o_city, o_prov = [x.strip() for x in norm_origin.split(",", 1)]
            d_city, d_prov = [x.strip() for x in norm_dest.split(",", 1)]
            mo_city, mo_prov = [x.strip() for x in m_orig.split(",", 1)] if "," in m_orig else (m_orig, "")
            md_city, md_prov = [x.strip() for x in m_dest.split(",", 1)] if "," in m_dest else (m_dest, "")
            if o_prov == mo_prov and d_prov == md_prov and (o_city in mo_city or mo_city in o_city) and (d_city in md_city or md_city in d_city):
                return m

    return minimums[0] if minimums else None

def evaluate_surcharges(
    surcharges: List[Dict[str, Any]],
    requested_accessorials: List[str],
    destination: str,
    billable_weight: float,
    base_rate: float
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Rule 11: Apply surcharges only when their conditions are met, and list each one separately.
    Handles flat fees, percentage surcharges with minimums, CWT fees, and waived items.
    """
    active_surcharges = []
    total_surcharge_amount = 0.0
    req_set = {a.lower().strip() for a in requested_accessorials}

    # Extract destination province (e.g. 'NL' for ferry surcharges)
    dest_province = ""
    if "," in destination:
        dest_province = destination.split(",")[-1].strip().upper()

    for s in surcharges:
        code = s["surcharge_code"].upper()
        cond_type = s["condition_type"].lower()
        is_waived = bool(s.get("is_waived", 0))
        fee_type = s.get("fee_type", "FLAT").upper()
        rate_amt = float(s.get("amount", 0.0))
        min_fee = float(s.get("min_fee", 0.0))
        max_fee = float(s["max_fee"]) if s.get("max_fee") is not None else None

        triggered = False

        # Condition checks
        if cond_type == "appointment" and ("appointment" in req_set or "notify" in req_set):
            triggered = True
        elif cond_type in ["after_hours", "after_hours_metro"] and "after_hours" in req_set:
            triggered = True
        elif cond_type == "amazon_delivery" and "amazon" in req_set:
            triggered = True
        elif cond_type == "dangerous_goods" and ("dangerous_goods" in req_set or "hazmat" in req_set):
            # Check weight bracket if defined
            cond_expr = s.get("condition_expression")
            if cond_expr:
                import json
                try:
                    expr = json.loads(cond_expr) if isinstance(cond_expr, str) else cond_expr
                    w_min = expr.get("weight_min", 0)
                    w_max = expr.get("weight_max", 999999)
                    if w_min <= billable_weight <= w_max:
                        triggered = True
                except Exception:
                    triggered = True
            else:
                triggered = True
        elif cond_type in ["liftgate", "tailgate", "power_tailgate"] and ("liftgate" in req_set or "tailgate" in req_set):
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
                # Check ferry weight bracket if defined
                cond_expr = s.get("condition_expression")
                if cond_expr:
                    import json
                    try:
                        expr = json.loads(cond_expr) if isinstance(cond_expr, str) else cond_expr
                        w_min = expr.get("weight_min", 0)
                        w_max = expr.get("weight_max", 999999)
                        if w_min <= billable_weight <= w_max:
                            triggered = True
                    except Exception:
                        triggered = True
                else:
                    triggered = True

        if not triggered:
            continue

        # Calculate Fee Amount
        if is_waived:
            calculated_fee = 0.0
        elif fee_type == "FLAT":
            calculated_fee = rate_amt
        elif fee_type == "PERCENTAGE":
            calc = (rate_amt / 100.0) * base_rate
            calculated_fee = max(calc, min_fee)
        elif fee_type == "CWT":
            calc = (billable_weight / 100.0) * rate_amt
            if min_fee > 0:
                calc = max(calc, min_fee)
            if max_fee and max_fee > 0:
                calc = min(calc, max_fee)
            calculated_fee = calc
        else:
            calculated_fee = rate_amt

        calculated_fee = round(calculated_fee, 2)
        total_surcharge_amount += calculated_fee

        active_surcharges.append({
            "code": code,
            "name": s["name"],
            "fee_type": fee_type,
            "amount": calculated_fee,
            "is_waived": is_waived,
            "source_cell": s.get("source_cell", "Terms & Conditions")
        })

    return active_surcharges, round(total_surcharge_amount, 2)

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
    shipment_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Rules 8–15: Core deterministic calculation engine.
    Never uses LLM reasoning for math. Pure deterministic Python code.
    """
    sheet = get_rate_sheet(sheet_id, user_id)
    if not sheet:
        raise ValueError(f"Rate sheet {sheet_id} not found or unauthorized (Rule 28).")

    # Rule 19: Strict confirmation gate check (with manual broker override support)
    if sheet["confirmation_status"] != "CONFIRMED" and not sheet.get("manual_override"):
        raise ValueError(f"Rule 19 Violation: Cannot quote from unconfirmed sheet '{sheet['carrier_name']}' (Status: {sheet['confirmation_status']}). Confirmation required.")

    # Rule 16: Effective Date and Expiry Date validation
    if shipment_date:
        if sheet["effective_date"] and shipment_date < sheet["effective_date"]:
            raise ValueError(f"Rule 16: Sheet not yet effective on {shipment_date} (Effective: {sheet['effective_date']}).")
        if sheet["expiry_date"] and shipment_date > sheet["expiry_date"]:
            raise ValueError(f"Rule 16: Sheet expired on {sheet['expiry_date']} (Shipment Date: {shipment_date}).")

    rules = get_sheet_full_rules(sheet_id, user_id)
    accessorials = accessorials or []
    
    # Trace log steps for complete Rule 30 auditability
    trace_steps = []

    # 1. Billable Weight Calculation (Rule 9)
    # Parse density pcf rule if present (e.g. '10.00 lbs per cu ft')
    dim_min_pcf = 10.0 if (sheet.get("dim_min_rule") and "10" in sheet["dim_min_rule"]) else None
    weight_info = calculate_billable_weight(
        actual_weight=actual_weight,
        length=length,
        width=width,
        height=height,
        dim_divisor=sheet.get("dim_divisor", 139.0),
        dim_min_pcf=dim_min_pcf
    )
    billable_weight = weight_info["billable_weight"]
    trace_steps.append({
        "step": "Weight & DIM Calculation (Rule 9)",
        "actual_weight_lbs": actual_weight,
        "dim_weight_lbs": weight_info["dim_weight"],
        "cubic_weight_lbs": weight_info["cubic_weight"],
        "billable_weight_lbs": billable_weight,
        "divisor_used": weight_info["dim_divisor"],
        "dim_applied": weight_info["is_dim_billed"]
    })

    # Rule 18: Operational Limits & Mode Feasibility Check
    mode = sheet.get("mode", "LTL").upper()
    if mode == "PARCEL":
        if length and width and height:
            if length > 108.0 or width > 108.0 or height > 108.0:
                raise ValueError(f"Rule 18 Exclusion: Package single dimension exceeds parcel limit of 108 inches.")
            girth = 2 * (float(width) + float(height))
            if float(length) + girth > 165.0:
                raise ValueError(f"Rule 18 Exclusion: Package combined length and girth ({float(length) + girth:.1f} in) exceeds maximum parcel limit of 165 inches.")
        if billable_weight > 150.0:
            raise ValueError(f"Rule 18 Exclusion: Shipment weight {billable_weight} lbs exceeds maximum parcel limit of 150 lbs (requires LTL or Freight service).")
    elif mode == "LTL":
        if billable_weight > 44000.0:
            raise ValueError(f"Rule 18 Exclusion: Shipment weight {billable_weight} lbs exceeds legal LTL capacity of 44,000 lbs (requires Dedicated FTL equipment).")

    # 2. Match Lane Rate Break (Rule 8, 10)
    matched_break = match_lane_break(rules["breaks"], origin, destination, billable_weight)
    if not matched_break:
        raise ValueError(f"Rule 18 / Rule 24 Exclusion: Lane not served: {sheet['carrier_name']} does not publish confirmed rates between {origin} and {destination} for weight {billable_weight} lbs.")


    rate_type = matched_break.get("rate_type", "CWT").upper()
    rate_val = float(matched_break["base_rate"])
    
    # Calculate base charge (with Deficit Weight Rating support)
    if matched_break.get("is_deficit_rated") and matched_break.get("effective_base_charge") is not None:
        base_charge = matched_break["effective_base_charge"]
        trace_steps.append({
            "step": "Base Rate Calculation with Deficit Weight Rating (Rule 8 / Deficit Bumping)",
            "lane": f"{origin} -> {destination}",
            "natural_weight": billable_weight,
            "deficit_bumped_weight": billable_weight + matched_break.get("deficit_weight", 0.0),
            "deficit_weight_added": matched_break.get("deficit_weight", 0.0),
            "break_name": f"{matched_break['break_name']} (Deficit Rated)",
            "rate_value": rate_val,
            "rate_type": rate_type,
            "base_charge": base_charge,
            "deficit_savings": matched_break.get("deficit_savings", 0.0),
            "source_coordinate": matched_break.get("source_cell", "")
        })
    else:
        if rate_type == "CWT":
            base_charge_unrounded = (billable_weight / 100.0) * rate_val
        elif rate_type == "FLAT":
            base_charge_unrounded = rate_val
        else:  # PER_UNIT
            base_charge_unrounded = billable_weight * rate_val

        base_charge = round(base_charge_unrounded, 2)
        trace_steps.append({
            "step": "Base Rate Calculation (Rule 8)",
            "lane": f"{origin} -> {destination}",
            "break_name": matched_break["break_name"],
            "rate_value": rate_val,
            "rate_type": rate_type,
            "base_charge": base_charge,
            "source_coordinate": matched_break.get("source_cell", "")
        })

    # 3. Itemized Surcharges (Rule 11)
    applied_surcharges, total_surcharges = evaluate_surcharges(
        surcharges=rules["surcharges"],
        requested_accessorials=accessorials,
        destination=destination,
        billable_weight=billable_weight,
        base_rate=base_charge
    )
    for sur in applied_surcharges:
        trace_steps.append({
            "step": f"Accessorial Surcharge: {sur['name']} (Rule 11)",
            "code": sur["code"],
            "amount": sur["amount"],
            "waived": sur["is_waived"],
            "source_coordinate": sur["source_cell"]
        })

    # Weekly Fuel Surcharge (FSC) Index Evaluation (Task 2.2)
    has_sheet_fuel = any(s.get("code") in ["FSC", "FUEL"] or "fuel" in s.get("name", "").lower() for s in applied_surcharges)
    req_set = {a.lower().strip() for a in accessorials}
    if not has_sheet_fuel and ("fuel" in req_set or "fsc" in req_set):
        fsc_calc = resolve_effective_fuel_surcharge(user_id=user_id, base_freight=base_charge)
        if fsc_calc["fsc_amount"] > 0:
            total_surcharges = round(total_surcharges + fsc_calc["fsc_amount"], 2)
            applied_surcharges.append({
                "code": "FSC",
                "name": f"Fuel Surcharge ({fsc_calc['source']})",
                "fee_type": "PERCENTAGE",
                "amount": fsc_calc["fsc_amount"],
                "is_waived": False,
                "source_cell": "OTA Diesel Fuel Benchmark"
            })
            trace_steps.append({
                "step": f"Fuel Surcharge: {fsc_calc['source']} (Rule 11 / Canadian FSC Index)",
                "code": "FSC",
                "amount": fsc_calc["fsc_amount"],
                "waived": False,
                "source_coordinate": "OTA Diesel Benchmark"
            })

    # 4. Minimum Charge Comparison (Rule 12)
    matched_min = match_lane_minimum(rules["minimums"], origin, destination)
    min_charge = float(matched_min["min_charge"]) if matched_min else 0.0
    
    subtotal_pre_min = base_charge + total_surcharges
    min_charge_adjustment = 0.0
    if subtotal_pre_min < min_charge:
        min_charge_adjustment = round(min_charge - subtotal_pre_min, 2)
        total_amount = min_charge
        trace_steps.append({
            "step": "Minimum Charge Adjustment (Rule 12)",
            "subtotal_pre_min": subtotal_pre_min,
            "carrier_min_charge": min_charge,
            "adjustment_added": min_charge_adjustment,
            "source_coordinate": matched_min.get("source_cell", "")
        })
    else:
        total_amount = subtotal_pre_min

    # 5. Final Step Rounding (Rule 15)
    wholesale_total = round_currency(total_amount, sheet.get("rounding_rule", "standard_2dp"))
    trace_steps.append({
        "step": "Final-Step Rounding (Wholesale Net Total) (Rule 15)",
        "wholesale_total": wholesale_total,
        "rounding_rule": sheet.get("rounding_rule", "standard_2dp")
    })

    # Broker Margin & Markup Calculation
    markup_mode = sheet.get("markup_mode", "PERCENTAGE")
    markup_val = float(sheet.get("markup_value") or 0.0)
    broker_margin = 0.0
    if markup_val > 0:
        if markup_mode == "PERCENTAGE":
            broker_margin = round(base_charge * (markup_val / 100.0), 2)
        elif markup_mode == "FLAT":
            broker_margin = round(markup_val, 2)
        elif markup_mode == "CWT":
            broker_margin = round((billable_weight / 100.0) * markup_val, 2)
        
        trace_steps.append({
            "step": f"Broker Margin Markup ({markup_mode}: {markup_val})",
            "wholesale_base": base_charge,
            "broker_margin": broker_margin,
            "formula": f"{base_charge} x {markup_val}%" if markup_mode == "PERCENTAGE" else f"${markup_val}"
        })

    # Accessorial markup if configured
    acc_markup_pct = float(sheet.get("accessorial_markup_pct") or 0.0)
    if acc_markup_pct > 0 and total_surcharges > 0:
        acc_margin = round(total_surcharges * (acc_markup_pct / 100.0), 2)
        broker_margin = round(broker_margin + acc_margin, 2)
        trace_steps.append({
            "step": f"Accessorial Margin Markup (+{acc_markup_pct}%)",
            "accessorial_margin": acc_margin
        })

    client_total = round_currency(wholesale_total + broker_margin, sheet.get("rounding_rule", "standard_2dp"))
    final_total = client_total if broker_margin > 0 else wholesale_total

    # Transit time resolution
    transit_days = None
    if rules.get("zones"):
        for z in rules["zones"]:
            if normalize_location_string(origin) == normalize_location_string(z["origin_spec"]) and \
               normalize_location_string(destination) == normalize_location_string(z["dest_spec"]):
                transit_days = z.get("transit_days")
                break

    # Rule 23: Flag any quote option that relies on a rate, surcharge or rule that was modified during human review or flagged 'needs review'
    flagged_cells = get_rate_sheet_cells(sheet["id"], user_id, needs_review_only=True)
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

    # Manual broker override flag
    if sheet.get("manual_override"):
        flagged_reasons.append("Manual Broker Override: Sheet enabled prior to agent verification")

    relies_on_flagged = len(flagged_reasons) > 0
    caution_badge = f"Caution: Relies on flagged/reviewed data ({', '.join(flagged_reasons)})" if relies_on_flagged else None

    return {
        "sheet_id": sheet["id"],
        "carrier_name": sheet["carrier_name"],
        "service_name": sheet["service_name"],
        "tariff_ref": sheet.get("tariff_ref"),
        "origin": origin,
        "destination": destination,
        "currency": sheet["currency"],
        "weight_unit": sheet["weight_unit"],
        "actual_weight": actual_weight,
        "billable_weight": billable_weight,
        "is_dim_billed": weight_info["is_dim_billed"],
        "base_rate": base_charge,
        "rate_break": matched_break["break_name"],
        "source_coordinate": matched_break.get("source_cell", ""),
        "source_cell": matched_break.get("source_cell", ""),
        "surcharges": applied_surcharges,
        "total_surcharges": total_surcharges,
        "carrier_min_charge": min_charge,
        "min_charge_adjustment": min_charge_adjustment,
        "is_deficit_rated": matched_break.get("is_deficit_rated", False),
        "deficit_savings": matched_break.get("deficit_savings", 0.0),
        "deficit_weight": matched_break.get("deficit_weight", 0.0),
        "wholesale_total": wholesale_total,
        "broker_margin": broker_margin,
        "final_total": final_total,
        "client_total": final_total,
        "transit_days": transit_days or 3,  # default estimated transit if zone unstated
        "relies_on_flagged_cell": relies_on_flagged,
        "caution_badge": caution_badge,
        "disclaimer": "Calculation from customer uploaded rate sheets. Non-binding quote (Rule 26).",
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
                    "shift_pct": round(shift_pct, 1),
                    "previous_version": prev_sheet.get("version", 1),
                    "previous_total": prev_total,
                    "current_total": current_total,
                    "message": f"Rule 27 Alert: Sharp rate {direction} of {shift_pct:+.1f}% detected compared to Version {prev_sheet.get('version', 1)} (${prev_total:.2f} -> ${current_total:.2f}). Please verify."
                }
    except Exception:
        pass
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
    shipment_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates all confirmed rate sheets for a tenant, calculating quotes deterministically.
    Enforces Rule 16 (Date validity & warning), Rule 17 (Version precedence),
    Rule 18 (Operational limits & mode feasibility), Rule 20 (Ranking),
    Rule 27 (Rate shift anomaly), and Rule 30 (Audit logging).
    """
    all_tenant_sheets = list_rate_sheets(user_id=user_id)
    confirmed_sheets = [s for s in all_tenant_sheets if s.get("confirmation_status") == "CONFIRMED" or s.get("manual_override") == 1]
    
    valid_quotes = []
    excluded_sheets = []
    all_sheet_ids = [s["id"] for s in confirmed_sheets]

    # Reference date for Rule 16
    ref_date = shipment_date or datetime.utcnow().strftime("%Y-%m-%d")

    # Step 1: Rule 16 - Effective & Expiry Date Filtering
    date_valid_sheets = []
    for s in confirmed_sheets:
        eff_date = s.get("effective_date")
        exp_date = s.get("expiry_date")
        
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

    # Step 2: Rule 17 - Version Precedence Resolution
    # Group date-valid sheets by (carrier_name, service_name)
    grouped_by_carrier_service = {}
    for s in date_valid_sheets:
        key = (s["carrier_name"].strip().upper(), s["service_name"].strip().upper())
        grouped_by_carrier_service.setdefault(key, []).append(s)

    sheets_to_quote = []
    for key, sheets in grouped_by_carrier_service.items():
        # Sort by version descending (newest version first)
        sorted_sheets = sorted(sheets, key=lambda x: (x.get("version", 1), x.get("effective_date") or ""), reverse=True)
        newest_sheet = sorted_sheets[0]
        sheets_to_quote.append(newest_sheet)

        # Older superceded versions are excluded with Rule 17 explanation
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
                shipment_date=ref_date
            )

            # Step 4: Rule 27 - Rate Shift Anomaly Detection (>25%)
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
        "shipment_date": ref_date
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

    return {
        "quote_id": quote_id,
        "timestamp": datetime.utcnow().isoformat(),
        "total_options": len(valid_quotes),
        "quotes": valid_quotes,
        "excluded_sheets": excluded_sheets,
        "message": message,
        "disclaimer": "Calculation from customer uploaded rate sheets. Non-binding quote (Rule 26)."
    }

