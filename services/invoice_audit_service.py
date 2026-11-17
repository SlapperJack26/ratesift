"""
services/invoice_audit_service.py
=================================
1-Click Carrier Invoice Freight Audit & Overcharge Dispute Generator.

Compares a carrier's billed AP invoice against Quotelytics' deterministic wholesale rate
and exact Excel tariff cell citation (Sheet!Cell), flags overcharges > $1.00 CAD,
identifies the root cause (Deficit Rating missed, Weight/Cube discrepancy, FSC overbill,
or Base CWT overcharge), and generates a ready-to-send Formal Carrier Tariff Dispute Notice.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from services.db_service import db_session


def _ensure_invoice_audits_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS carrier_invoice_audits (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            carrier_name TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            tariff_citation TEXT,
            expected_wholesale_cad REAL NOT NULL,
            billed_amount_cad REAL NOT NULL,
            variance_cad REAL NOT NULL,
            variance_pct REAL NOT NULL,
            audit_status TEXT NOT NULL,
            root_cause TEXT,
            dispute_notice_text TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inv_audit_user ON carrier_invoice_audits (user_id, created_at)"
    )


def audit_carrier_invoice_against_quote(
    user_id: str,
    carrier_name: str,
    invoice_number: str,
    origin: str,
    destination: str,
    expected_wholesale_cad: float,
    billed_amount_cad: float,
    tariff_citation: str = "Verified Carrier Tariff Cell",
    expected_weight_lbs: float = 1000.0,
    billed_weight_lbs: Optional[float] = None,
    expected_fsc_cad: float = 0.0,
    billed_fsc_cad: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Audits a carrier invoice against the confirmed Quotelytics wholesale rate and persists the audit record.
    """
    exp_amt = round(float(expected_wholesale_cad or 0.0), 2)
    bil_amt = round(float(billed_amount_cad or 0.0), 2)
    variance_cad = round(bil_amt - exp_amt, 2)
    variance_pct = round((variance_cad / exp_amt) * 100.0, 2) if exp_amt > 0 else 0.0

    reasons: List[str] = []
    if billed_weight_lbs is not None and float(billed_weight_lbs) > float(expected_weight_lbs) + 5.0:
        reasons.append(
            f"Weight / Deficit Discrepancy (Billed at {float(billed_weight_lbs):,.0f} lbs vs. Quoted {float(expected_weight_lbs):,.0f} lbs)"
        )
    if billed_fsc_cad is not None and float(billed_fsc_cad) > float(expected_fsc_cad) + 1.0:
        fsc_diff = round(float(billed_fsc_cad) - float(expected_fsc_cad), 2)
        reasons.append(f"Fuel Surcharge Overbill (+${fsc_diff:.2f} CAD above contracted FSC table)")

    if variance_cad > 1.00:
        status = "OVERCHARGE_DETECTED"
        if not reasons:
            reasons.append("Contracted CWT / Skid Base Rate or Deficit Bracket Not Applied")
    elif variance_cad < -1.00:
        status = "UNDERBILLED"
        reasons.append("Carrier billed below contracted tariff rate")
    else:
        status = "MATCHED_VERIFIED"
        reasons.append("Invoice matches confirmed tariff within $1.00 tolerance")

    root_cause_str = "; ".join(reasons)
    audit_id = f"aud_{uuid.uuid4().hex[:10]}"
    now_iso = datetime.utcnow().isoformat()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    dispute_notice = ""
    if status == "OVERCHARGE_DETECTED":
        dispute_notice = (
            f"FORMAL CARRIER FREIGHT INVOICE DISPUTE NOTICE ({today_str})\n"
            f"To: {carrier_name} — Accounts Receivable / Freight Rating Adjustment Desk\n"
            f"Carrier Invoice #: {invoice_number}\n"
            f"Lane: {origin} -> {destination}\n"
            f"----------------------------------------------------------------------\n"
            f"1. Billed Invoice Amount:         ${bil_amt:,.2f} CAD\n"
            f"2. Contracted Tariff Net Rate:    ${exp_amt:,.2f} CAD\n"
            f"3. Overcharge Disputed Amount:    +${variance_cad:,.2f} CAD (+{variance_pct:.1f}%)\n"
            f"4. Exact Tariff Cell Citation:    {tariff_citation}\n"
            f"5. Identified Rating Variance:    {root_cause_str}\n"
            f"----------------------------------------------------------------------\n"
            f"Please issue a revised invoice or credit memo in the amount of ${variance_cad:,.2f} CAD "
            f"reflecting the contracted rate at {tariff_citation}. Short-pay remittance of ${exp_amt:,.2f} CAD "
            f"is approved pending adjustment."
        )

    with db_session() as conn:
        _ensure_invoice_audits_table(conn)
        conn.execute(
            """
            INSERT INTO carrier_invoice_audits (
                id, user_id, carrier_name, invoice_number, origin, destination,
                tariff_citation, expected_wholesale_cad, billed_amount_cad,
                variance_cad, variance_pct, audit_status, root_cause,
                dispute_notice_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                str(user_id),
                str(carrier_name).strip(),
                str(invoice_number).strip(),
                str(origin).strip(),
                str(destination).strip(),
                str(tariff_citation).strip(),
                exp_amt,
                bil_amt,
                variance_cad,
                variance_pct,
                status,
                root_cause_str,
                dispute_notice,
                now_iso,
            ),
        )
        conn.commit()

    return {
        "audit_id": audit_id,
        "carrier_name": carrier_name,
        "invoice_number": invoice_number,
        "origin": origin,
        "destination": destination,
        "tariff_citation": tariff_citation,
        "expected_wholesale_cad": exp_amt,
        "billed_amount_cad": bil_amt,
        "variance_cad": variance_cad,
        "variance_pct": variance_pct,
        "audit_status": status,
        "root_cause": root_cause_str,
        "dispute_notice_text": dispute_notice,
        "created_at": now_iso,
    }


def list_carrier_invoice_audits(user_id: str) -> Dict[str, Any]:
    """Lists all carrier invoice audits for a brokerage and totals overcharges caught ($ CAD)."""
    with db_session() as conn:
        _ensure_invoice_audits_table(conn)
        rows = conn.execute(
            "SELECT * FROM carrier_invoice_audits WHERE user_id = ? ORDER BY created_at DESC",
            (str(user_id),),
        ).fetchall()

    items = [dict(r) for r in rows]
    overcharges = [x for x in items if x.get("audit_status") == "OVERCHARGE_DETECTED"]
    total_overcharge_cad = round(sum(float(x.get("variance_cad") or 0.0) for x in overcharges), 2)

    return {
        "total_audits": len(items),
        "overcharges_count": len(overcharges),
        "total_overcharges_caught_cad": total_overcharge_cad,
        "audits": items,
    }
