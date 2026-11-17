"""
services/dispatch_documents_service.py
======================================
1-Click Post-Quote Dispatch Document Generator:
1. Carrier Rate Confirmation ("Rate Con") — Shows the agreed wholesale carrier net rate ($ CAD/USD),
   exact tariff & cell citation (Sheet!Cell), lane FSAs, weight/skids, and carrier signature block
   (strictly hiding the broker's shipper markup and client total).
2. Canadian Straight Bill of Lading (BOL — Non-Negotiable) — Standard Canadian motor carrier
   Straight BOL layout with Shipper, Consignee, Third-Party Freight Charges Bill-To (Brokerage),
   Skid Count, Weight (lbs & kg), Dimensions, Checked Accessorials, and Driver/Shipper signature boxes.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

KG_PER_LB = 0.45359237


def build_carrier_rate_confirmation(
    quote_data: Dict[str, Any],
    broker_info: Optional[Dict[str, Any]] = None,
    carrier_notes: str = "",
) -> Dict[str, Any]:
    """
    Builds a structured Carrier Rate Confirmation ("Rate Con") for tendering a load to the winning carrier.
    Strictly uses the wholesale carrier net rate and never exposes the broker's shipper markup or client total.
    """
    broker = broker_info or {}
    now = datetime.utcnow()
    rate_con_id = f"RC-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    base_rate = round(float(quote_data.get("base_rate") or 0.0), 2)
    surcharges = quote_data.get("surcharges") or []
    total_surcharges = round(
        float(
            quote_data.get("total_surcharges")
            if quote_data.get("total_surcharges") is not None
            else sum(float(s.get("amount") or 0.0) for s in surcharges)
        ),
        2,
    )
    wholesale_total = round(
        float(
            quote_data.get("wholesale_total")
            or quote_data.get("carrier_total")
            or (base_rate + total_surcharges)
        ),
        2,
    )
    currency = (quote_data.get("currency") or "CAD").strip().upper()
    weight_lbs = round(float(quote_data.get("weight_lbs") or quote_data.get("actual_weight") or 1000.0), 1)
    weight_kg = round(weight_lbs * KG_PER_LB, 1)
    skid_count = int(quote_data.get("skid_count") or 1)
    source_coord = (
        quote_data.get("source_coordinate")
        or quote_data.get("coordinate")
        or quote_data.get("source_cell")
        or "Verified Carrier Tariff"
    )

    from services.cargo_liability_and_tdg_service import evaluate_canadian_cargo_liability_and_tdg

    liability_tdg = evaluate_canadian_cargo_liability_and_tdg(
        weight_lbs=weight_lbs,
        declared_value_cad=float(quote_data.get("declared_value_cad") or 0.0),
        is_tdg=bool(quote_data.get("is_tdg") or quote_data.get("un_number")),
        un_number=str(quote_data.get("un_number") or ""),
        tdg_class=str(quote_data.get("tdg_class") or ""),
        packing_group=str(quote_data.get("packing_group") or ""),
    )

    instructions = (
        carrier_notes
        or "Driver must verify skid count at pickup and obtain signed POD upon delivery. Reference Rate Con # on carrier invoice."
    )
    if liability_tdg.get("is_tdg") and liability_tdg.get("bol_tdg_declaration"):
        instructions = f"{instructions} | {liability_tdg['bol_tdg_declaration']}"
    if liability_tdg.get("has_liability_gap"):
        instructions = f"{instructions} | {liability_tdg['bol_liability_clause']}"

    return {
        "document_type": "CARRIER_RATE_CONFIRMATION",
        "rate_con_id": rate_con_id,
        "issue_date": now.strftime("%Y-%m-%d"),
        "broker": {
            "company": broker.get("company") or "Quotelytics Partner Brokerage",
            "dispatcher_name": broker.get("name") or "Dispatch Desk",
            "email": broker.get("email") or "dispatch@quotelytics.ca",
            "phone": broker.get("phone") or "289-929-8565",
        },
        "carrier": {
            "carrier_name": quote_data.get("carrier_name") or quote_data.get("carrier") or "Assigned LTL Carrier",
            "service_name": quote_data.get("service_name") or quote_data.get("service") or "Standard Road LTL",
            "tariff_citation": source_coord,
            "transit_days": int(quote_data.get("transit_days") or 3),
        },
        "shipment": {
            "origin": quote_data.get("origin") or "TORONTO, ON",
            "destination": quote_data.get("destination") or "CALGARY, AB",
            "skid_count": skid_count,
            "weight_lbs": weight_lbs,
            "weight_kg": weight_kg,
            "billable_weight_lbs": round(float(quote_data.get("billable_weight") or weight_lbs), 1),
            "rate_break": quote_data.get("rate_break") or "LTL CWT / Skid",
        },
        "carrier_pay_breakdown": {
            "currency": currency,
            "carrier_base_freight": base_rate,
            "surcharges": [
                {
                    "name": s.get("name") or s.get("code") or "Accessorial",
                    "amount": round(float(s.get("amount") or 0.0), 2),
                }
                for s in surcharges
            ],
            "total_surcharges": total_surcharges,
            "agreed_carrier_net_total": wholesale_total,
        },
        "cargo_liability_and_tdg": liability_tdg,
        "carrier_instructions": instructions,
    }


def build_canadian_straight_bol(
    quote_data: Dict[str, Any],
    broker_info: Optional[Dict[str, Any]] = None,
    shipper_info: Optional[Dict[str, Any]] = None,
    consignee_info: Optional[Dict[str, Any]] = None,
    bol_notes: str = "",
) -> Dict[str, Any]:
    """
    Builds a standard Canadian Straight Bill of Lading (Non-Negotiable) from quote specifications.
    Contains zero pricing/rate figures so it can be handed directly to the shipper's dock and truck driver.
    """
    broker = broker_info or {}
    shipper = shipper_info or {}
    consignee = consignee_info or {}
    now = datetime.utcnow()
    bol_number = f"BOL-CA-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    weight_lbs = round(float(quote_data.get("weight_lbs") or quote_data.get("actual_weight") or 1000.0), 1)
    weight_kg = round(weight_lbs * KG_PER_LB, 1)
    skid_count = int(quote_data.get("skid_count") or 1)
    length_in = float(quote_data.get("length") or 48.0)
    width_in = float(quote_data.get("width") or 40.0)
    height_in = float(quote_data.get("height") or 48.0)

    surcharges = quote_data.get("surcharges") or []
    acc_labels = [
        (s.get("name") or s.get("code") or "").strip()
        for s in surcharges
        if (s.get("name") or s.get("code"))
    ]
    req_acc = quote_data.get("accessorials") or []
    for a in req_acc:
        if str(a).strip() and str(a).strip() not in acc_labels:
            acc_labels.append(str(a).strip().upper())

    from services.cargo_liability_and_tdg_service import evaluate_canadian_cargo_liability_and_tdg

    liability_tdg = evaluate_canadian_cargo_liability_and_tdg(
        weight_lbs=weight_lbs,
        declared_value_cad=float(quote_data.get("declared_value_cad") or 0.0),
        is_tdg=bool(quote_data.get("is_tdg") or quote_data.get("un_number")),
        un_number=str(quote_data.get("un_number") or ""),
        tdg_class=str(quote_data.get("tdg_class") or ""),
        packing_group=str(quote_data.get("packing_group") or ""),
    )

    instructions_parts = [bol_notes.strip()] if bol_notes and bol_notes.strip() else []
    instructions_parts.append(liability_tdg["bol_liability_clause"])
    if liability_tdg.get("bol_tdg_declaration"):
        instructions_parts.append(liability_tdg["bol_tdg_declaration"])

    return {
        "document_type": "CANADIAN_STRAIGHT_BILL_OF_LADING",
        "bol_number": bol_number,
        "issue_date": now.strftime("%Y-%m-%d"),
        "carrier_name": quote_data.get("carrier_name") or quote_data.get("carrier") or "Assigned LTL Carrier",
        "service_level": quote_data.get("service_name") or quote_data.get("service") or "Standard Road LTL",
        "shipper": {
            "company": shipper.get("company") or "Origin Shipper Facility",
            "location": quote_data.get("origin") or "TORONTO, ON",
            "contact": shipper.get("contact") or "Shipping & Receiving Dock",
        },
        "consignee": {
            "company": consignee.get("company") or "Destination Consignee Facility",
            "location": quote_data.get("destination") or "CALGARY, AB",
            "contact": consignee.get("contact") or "Receiving Dock",
        },
        "third_party_bill_to": {
            "brokerage_company": broker.get("company") or "Quotelytics Partner Brokerage",
            "billing_email": broker.get("email") or "ap@quotelytics.ca",
            "freight_charge_terms": "PREPAID — THIRD PARTY BILL TO BROKERAGE",
        },
        "cargo_line": {
            "handling_units": f"{skid_count} Standard Skid(s) / Pallet(s)",
            "skid_count": skid_count,
            "dimensions_in": f"{int(length_in)}x{int(width_in)}x{int(height_in)} in",
            "weight_lbs": weight_lbs,
            "weight_kg": weight_kg,
            "commodity_description": quote_data.get("commodity") or "General Palletized LTL Freight (FAK)",
            "declared_value_cad": liability_tdg["declared_value_cad"],
            "is_tdg": liability_tdg["is_tdg"],
        },
        "checked_accessorials": acc_labels,
        "cargo_liability_and_tdg": liability_tdg,
        "special_instructions": " | ".join(instructions_parts),
    }


def build_tms_and_quickbooks_export(
    quote_data: Dict[str, Any],
    client_name: str = "Valued Shipper",
    markup_pct: float = 15.0,
    min_margin_dollars: float = 45.0,
) -> Dict[str, Any]:
    """
    1-Click TMS (Rose Rocket, Tailwind, McLeod) & QuickBooks Export Builder:
    Generates both a structured clipboard dispatch block and a universal CSV import row.
    """
    import csv
    import io

    carrier = quote_data.get("carrier_name") or quote_data.get("carrier") or "Assigned Carrier"
    service = quote_data.get("service_name") or quote_data.get("service") or "Standard Road LTL"
    origin = quote_data.get("origin") or "TORONTO, ON"
    dest = quote_data.get("destination") or "CALGARY, AB"
    skids = int(quote_data.get("skid_count") or 1)
    weight_lbs = round(float(quote_data.get("weight_lbs") or quote_data.get("actual_weight") or 1000.0), 1)
    currency = (quote_data.get("currency") or "CAD").strip().upper()
    coord = (
        quote_data.get("source_coordinate")
        or quote_data.get("coordinate")
        or quote_data.get("source_cell")
        or "Verified Tariff"
    )

    base_rate = round(float(quote_data.get("base_rate") or 0.0), 2)
    surcharges = quote_data.get("surcharges") or []
    total_sur = round(
        float(
            quote_data.get("total_surcharges")
            if quote_data.get("total_surcharges") is not None
            else sum(float(s.get("amount") or 0.0) for s in surcharges)
        ),
        2,
    )
    wholesale = round(
        float(quote_data.get("wholesale_total") or quote_data.get("final_total") or (base_rate + total_sur)),
        2,
    )

    pct_sell = round(wholesale * (1.0 + max(0.0, float(markup_pct or 0.0)) / 100.0), 2)
    floor_sell = round(wholesale + max(0.0, float(min_margin_dollars or 0.0)), 2)
    client_sell = round(float(quote_data.get("client_total") or max(pct_sell, floor_sell)), 2)
    margin = round(client_sell - wholesale, 2)

    clipboard_text = (
        f"=== QUOTELYTICS TMS DISPATCH SUMMARY ===\n"
        f"Customer / Shipper: {client_name}\n"
        f"Lane:               {origin} -> {dest}\n"
        f"Cargo:              {skids} Skid(s) | {weight_lbs:,.0f} lbs\n"
        f"Winning Carrier:    {carrier} ({service})\n"
        f"Tariff Citation:    {coord}\n"
        f"Carrier Net Cost:   ${wholesale:,.2f} {currency} (Base: ${base_rate:,.2f} + Acc/FSC: ${total_sur:,.2f})\n"
        f"Customer Sell Rate: ${client_sell:,.2f} {currency}\n"
        f"Net Broker Margin:  +${margin:,.2f} {currency}"
    )

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, lineterminator="\n")
    writer.writerow([
        "Customer_Name", "Origin", "Destination", "Skids", "Weight_Lbs",
        "Carrier_Name", "Service_Level", "Tariff_Coordinate",
        "Carrier_Wholesale_Cost", "Customer_Sell_Rate", "Broker_Margin", "Currency"
    ])
    writer.writerow([
        client_name, origin, dest, skids, weight_lbs,
        carrier, service, coord,
        f"{wholesale:.2f}", f"{client_sell:.2f}", f"{margin:.2f}", currency
    ])

    return {
        "clipboard_summary": clipboard_text,
        "universal_tms_csv": csv_buf.getvalue(),
        "wholesale_cost": wholesale,
        "client_sell_rate": client_sell,
        "broker_margin": margin,
        "currency": currency,
    }
