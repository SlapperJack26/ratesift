"""
services/spot_quote_service.py
==============================
Workstream 4: 1-Click Carrier Spot-Rate RFQ Blast Generator & Ad-Hoc Spot Quote Logger.
Eliminates the "No Qualifying Carrier" dead-end when a lane isn't covered by contract sheets.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from services.db_service import db_session
from services.fsa_resolver_service import resolve_location
from services.quotelytics_engine import calculate_canadian_ltl_cube_density


def _ensure_spot_quotes_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS spot_quotes (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            carrier_name TEXT NOT NULL,
            carrier_rep_email TEXT,
            spot_reference TEXT,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            weight_lbs REAL NOT NULL DEFAULT 1000.0,
            skid_count INTEGER NOT NULL DEFAULT 1,
            transit_days INTEGER NOT NULL DEFAULT 3,
            spot_wholesale_cad REAL NOT NULL,
            markup_pct REAL NOT NULL DEFAULT 15.0,
            min_margin_dollars REAL NOT NULL DEFAULT 45.0,
            client_total REAL NOT NULL,
            broker_margin REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'CAD',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spot_quotes_user ON spot_quotes (user_id, created_at)"
    )


def generate_carrier_spot_rfq_blast(
    origin: str,
    destination: str,
    weight_lbs: float,
    skid_count: int = 1,
    length_in: float = 48.0,
    width_in: float = 40.0,
    height_in: float = 48.0,
    non_stackable: bool = False,
    is_tdg: bool = False,
    un_number: str = "",
    accessorials: Optional[List[str]] = None,
    commodity: str = "General Palletized Freight",
) -> Dict[str, Any]:
    """
    Produces a copy-ready Carrier Spot-Rate RFQ Email & Subject Line with normalized FSAs,
    actual vs. cubed billable weight, Non-Stackable/Over-Length notes, and TDG flags.
    """
    orig_res = resolve_location(origin)
    dest_res = resolve_location(destination)
    orig_norm = orig_res.get("location_string") or str(origin or "").strip().upper()
    dest_norm = dest_res.get("location_string") or str(destination or "").strip().upper()

    cube = calculate_canadian_ltl_cube_density(
        actual_weight_lbs=weight_lbs,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        skid_count=skid_count,
        non_stackable=non_stackable,
    )

    acc_list = [str(a).strip().upper() for a in (accessorials or []) if str(a).strip()]
    acc_str = ", ".join(acc_list) if acc_list else "Standard Dock-to-Dock"

    notes = []
    if cube.get("non_stackable_applied"):
        notes.append("NON-STACKABLE (Do Not Double-Stack / 84\" Cube Rule)")
    if cube.get("is_over_length"):
        notes.append(f"OVER-LENGTH CRATE ({cube.get('max_dimension_in'):.0f} in)")
    if is_tdg or un_number:
        notes.append(f"TDG / HAZMAT ({un_number or 'UN Pending'})")

    subject_line = (
        f"SPOT RATE RFQ: {orig_norm} -> {dest_norm} | {int(skid_count)} Skid(s) | "
        f"{float(cube['effective_billable_weight_lbs']):,.0f} lbs Billable"
    )
    email_body = (
        f"Hello Dispatch / Spot Pricing Team,\n\n"
        f"Please provide your all-in spot quote (Linehaul + FSC + Accessorials in CAD) for the following LTL load:\n\n"
        f"- Origin:          {orig_norm} (Input: {origin})\n"
        f"- Destination:     {dest_norm} (Input: {destination})\n"
        f"- Handling Units:  {int(skid_count)} Skid(s) ({int(length_in)}x{int(width_in)}x{int(height_in)} in)\n"
        f"- Actual Weight:   {float(cube['actual_weight_lbs']):,.0f} lbs\n"
        f"- Cubed / Billed:  {float(cube['effective_billable_weight_lbs']):,.0f} lbs ({cube['cubic_feet']} cu.ft @ 10 lb/cu.ft)\n"
        f"- Est. Linear Ft:  {cube['estimated_linear_feet']} ft\n"
        f"- Accessorials:    {acc_str}\n"
        f"- Commodity:       {commodity}\n"
        f"- Special Flags:   {'; '.join(notes) if notes else 'None'}\n\n"
        f"Please reply with Rate + Transit Time + Quote Reference # so we can tender immediately.\n"
        f"Generated via Quotelytics Dispatch Console."
    )

    return {
        "subject_line": subject_line,
        "email_body": email_body,
        "origin_normalized": orig_norm,
        "destination_normalized": dest_norm,
        "actual_weight_lbs": float(cube["actual_weight_lbs"]),
        "effective_billable_weight_lbs": float(cube["effective_billable_weight_lbs"]),
        "cubic_feet": float(cube["cubic_feet"]),
        "requested_accessorials": acc_list,
    }


def create_adhoc_spot_quote(
    user_id: str,
    carrier_name: str,
    origin: str,
    destination: str,
    spot_wholesale_cad: float,
    weight_lbs: float = 1000.0,
    skid_count: int = 1,
    transit_days: int = 3,
    markup_pct: float = 15.0,
    min_margin_dollars: float = 45.0,
    carrier_rep_email: str = "",
    spot_reference: str = "",
    currency: str = "CAD",
) -> Dict[str, Any]:
    """
    Logs an ad-hoc carrier spot quote when no contract sheet covers a lane, returning a normalized
    Quotelytics quote object compatible with Shipper Proposals, /q/{token}, Rate Cons, BOLs & Audits.
    """
    clean_carrier = str(carrier_name or "").strip()
    if not clean_carrier:
        raise ValueError("carrier_name is required.")
    wholesale = round(float(spot_wholesale_cad or 0.0), 2)
    if wholesale <= 0.0:
        raise ValueError("spot_wholesale_cad must be greater than 0.")

    mk_pct = max(0.0, float(markup_pct or 0.0))
    min_dol = max(0.0, float(min_margin_dollars or 0.0))
    pct_sell = round(wholesale * (1.0 + mk_pct / 100.0), 2)
    floor_sell = round(wholesale + min_dol, 2)
    client_total = max(pct_sell, floor_sell)
    margin = round(client_total - wholesale, 2)

    spot_id = f"SPOT-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    ref_str = str(spot_reference or spot_id).strip()
    source_coord = f"SPOT-QUOTE • {ref_str}"
    curr = str(currency or "CAD").strip().upper()
    now_iso = datetime.utcnow().isoformat()

    with db_session() as conn:
        _ensure_spot_quotes_table(conn)
        conn.execute(
            """
            INSERT INTO spot_quotes (
                id, user_id, carrier_name, carrier_rep_email, spot_reference,
                origin, destination, weight_lbs, skid_count, transit_days,
                spot_wholesale_cad, markup_pct, min_margin_dollars,
                client_total, broker_margin, currency, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spot_id,
                str(user_id),
                clean_carrier,
                str(carrier_rep_email or "").strip(),
                ref_str,
                str(origin).strip(),
                str(destination).strip(),
                float(weight_lbs or 1000.0),
                int(skid_count or 1),
                int(transit_days or 3),
                wholesale,
                mk_pct,
                min_dol,
                client_total,
                margin,
                curr,
                now_iso,
            ),
        )
        conn.commit()

    normalized_quote = {
        "quote_id": spot_id,
        "carrier_name": clean_carrier,
        "carrier": clean_carrier,
        "service_name": "Carrier Spot Quote",
        "service": "Carrier Spot Quote",
        "origin": str(origin).strip(),
        "destination": str(destination).strip(),
        "weight_lbs": float(weight_lbs or 1000.0),
        "actual_weight": float(weight_lbs or 1000.0),
        "billable_weight": float(weight_lbs or 1000.0),
        "skid_count": int(skid_count or 1),
        "transit_days": int(transit_days or 3),
        "base_rate": wholesale,
        "total_surcharges": 0.0,
        "surcharges": [],
        "wholesale_total": wholesale,
        "broker_margin": margin,
        "final_total": client_total,
        "client_total": client_total,
        "currency": curr,
        "source_coordinate": source_coord,
        "is_spot_quote": True,
    }

    return {
        "id": spot_id,
        "spot_reference": ref_str,
        "carrier_name": clean_carrier,
        "origin": str(origin).strip(),
        "destination": str(destination).strip(),
        "spot_wholesale_cad": wholesale,
        "client_total": client_total,
        "broker_margin": margin,
        "currency": curr,
        "source_coordinate": source_coord,
        "created_at": now_iso,
        "normalized_quote": normalized_quote,
    }


def list_adhoc_spot_quotes(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Lists all ad-hoc carrier spot quotes logged by `user_id`."""
    with db_session() as conn:
        _ensure_spot_quotes_table(conn)
        rows = conn.execute(
            "SELECT * FROM spot_quotes WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (str(user_id), int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]
