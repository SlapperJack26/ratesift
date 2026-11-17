"""
services/cargo_liability_and_tdg_service.py
===========================================
Workstream 3: Canadian $2.00/lb Statutory Cargo Liability Gap Calculator &
TDG (Transportation of Dangerous Goods / Hazmat) Guardrail.

Under Canada's Uniform Conditions of Carriage, a carrier's maximum legal liability
for lost or damaged freight is capped at $2.00 CAD per lb ($4.41/kg) of actual weight
unless a higher Declared Value is stated on the Bill of Lading and Excess Valuation
coverage is arranged.
"""

from typing import Any, Dict


STATUTORY_CARRIER_LIMIT_PER_LB_CAD = 2.00
EXCESS_VALUATION_RATE = 0.025
EXCESS_VALUATION_MIN_FEE_CAD = 50.00
DEFAULT_TDG_SURCHARGE_CAD = 85.00
DEFAULT_CANUTEC_EMERGENCY_PHONE = "1-888-CAN-UTEC (226-8832)"


def evaluate_canadian_cargo_liability_and_tdg(
    weight_lbs: float,
    declared_value_cad: float = 0.0,
    is_tdg: bool = False,
    un_number: str = "",
    tdg_class: str = "",
    packing_group: str = "",
    emergency_phone: str = DEFAULT_CANUTEC_EMERGENCY_PHONE,
) -> Dict[str, Any]:
    """
    Evaluates high-value cargo liability exposure above Canada's statutory $2.00/lb limit
    and validates Transportation of Dangerous Goods (TDG / Hazmat) declarations for Rate Cons & BOLs.
    """
    wt = max(0.0, float(weight_lbs or 0.0))
    declared_val = round(max(0.0, float(declared_value_cad or 0.0)), 2)

    statutory_max_cad = round(wt * STATUTORY_CARRIER_LIMIT_PER_LB_CAD, 2)
    uninsured_gap_cad = round(max(0.0, declared_val - statutory_max_cad), 2)
    has_liability_gap = declared_val > statutory_max_cad

    excess_valuation_fee_cad = (
        round(max(EXCESS_VALUATION_MIN_FEE_CAD, uninsured_gap_cad * EXCESS_VALUATION_RATE), 2)
        if has_liability_gap
        else 0.0
    )

    clean_un = str(un_number or "").strip().upper()
    clean_class = str(tdg_class or "").strip().upper()
    clean_pg = str(packing_group or "").strip().upper()
    clean_phone = str(emergency_phone or DEFAULT_CANUTEC_EMERGENCY_PHONE).strip() or DEFAULT_CANUTEC_EMERGENCY_PHONE
    tdg_active = bool(is_tdg or clean_un)

    tdg_missing_fields = []
    if tdg_active:
        if not clean_un:
            tdg_missing_fields.append("un_number")
        if not clean_class:
            tdg_missing_fields.append("tdg_class")

    tdg_surcharge_cad = DEFAULT_TDG_SURCHARGE_CAD if tdg_active else 0.0

    if declared_val > 0.0:
        bol_liability_clause = (
            f"DECLARED VALUE: ${declared_val:,.2f} CAD "
            f"(Carrier statutory cap at $2.00/lb is ${statutory_max_cad:,.2f} CAD; "
            f"Excess Valuation Required: ${uninsured_gap_cad:,.2f} CAD)."
        )
    else:
        bol_liability_clause = (
            f"Subject to Canadian Uniform Conditions of Carriage. Maximum carrier liability $2.00 CAD per lb "
            f"(${statutory_max_cad:,.2f} CAD max for {wt:,.0f} lbs) unless higher value declared."
        )

    bol_tdg_declaration = None
    if tdg_active:
        bol_tdg_declaration = (
            f"TDG DANGEROUS GOODS: {clean_un or 'UN-PENDING'} | "
            f"Class {clean_class or 'PENDING'}"
            + (f" | PG {clean_pg}" if clean_pg else "")
            + f" | 24-Hr Emergency: {clean_phone}"
        )

    warnings = []
    if has_liability_gap:
        warnings.append(
            f"HIGH_VALUE_LIABILITY_GAP: Declared cargo value (${declared_val:,.2f} CAD) exceeds the "
            f"$2.00/lb statutory carrier cap (${statutory_max_cad:,.2f} CAD) by ${uninsured_gap_cad:,.2f} CAD. "
            f"Add est. ${excess_valuation_fee_cad:,.2f} CAD Excess Valuation or Third-Party Cargo Insurance."
        )
    if tdg_active:
        if tdg_missing_fields:
            warnings.append(
                f"TDG_INCOMPLETE_DECLARATION: Dangerous goods flagged but missing: {', '.join(tdg_missing_fields)}."
            )
        else:
            warnings.append(
                f"TDG_HAZMAT_ACTIVE: {bol_tdg_declaration} (est. +${tdg_surcharge_cad:.2f} CAD TDG carrier handling fee)."
            )

    return {
        "weight_lbs": wt,
        "statutory_limit_per_lb_cad": STATUTORY_CARRIER_LIMIT_PER_LB_CAD,
        "statutory_carrier_max_liability_cad": statutory_max_cad,
        "declared_value_cad": declared_val,
        "uninsured_liability_gap_cad": uninsured_gap_cad,
        "has_liability_gap": has_liability_gap,
        "estimated_excess_valuation_fee_cad": excess_valuation_fee_cad,
        "is_tdg": tdg_active,
        "un_number": clean_un,
        "tdg_class": clean_class,
        "packing_group": clean_pg,
        "emergency_phone": clean_phone,
        "tdg_compliant": bool(not tdg_active or not tdg_missing_fields),
        "tdg_missing_fields": tdg_missing_fields,
        "tdg_surcharge_estimate_cad": tdg_surcharge_cad,
        "total_recommended_protection_surcharges_cad": round(excess_valuation_fee_cad + tdg_surcharge_cad, 2),
        "bol_liability_clause": bol_liability_clause,
        "bol_tdg_declaration": bol_tdg_declaration,
        "warnings": warnings,
    }
