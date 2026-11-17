"""
services/carrier_presets_service.py
===================================
Canadian LTL Carrier Format Presets & Big 6 Accessorial Matrix Service.

Solves:
1. The "Messy Carrier Excel" Trap by providing pre-built parser profiles for major Canadian LTL
   carrier tariff formats (Manitoulin, Day & Ross, Midland, Overland West, Kindersley, Polaris, Skid Spot).
2. The "Accessorial & Winter Heated Surcharge Blind Spot" by providing a 1-click Big 6 Canadian LTL
   Accessorial Matrix (Tailgate, Heated/Freeze Protect, Residential, Appointment, Inside, Limited Access)
   that persists directly into `ql_carrier_surcharges`.
"""

import uuid
from typing import Dict, Any, List, Optional
from services.quotelytics_db_service import get_connection, get_rate_sheet

# ==============================================================================
# 1. CANADIAN LTL CARRIER FORMAT PRESETS
# ==============================================================================

CANADIAN_CARRIER_PRESETS: Dict[str, Dict[str, Any]] = {
    "AUTO_DETECT": {
        "id": "AUTO_DETECT",
        "name": "Auto-Detect Format (Default)",
        "carrier_name": None,
        "rating_basis": "AUTO",
        "currency": "CAD",
        "weight_unit": "lb",
        "allow_deficit_rating": True,
        "description": "Automatically detects CWT vs. Skid columns, FSA/City lanes, and embedded fuel/accessorial notes.",
        "header_aliases": {},
        "default_accessorials": [],
    },
    "MANITOULIN_CWT": {
        "id": "MANITOULIN_CWT",
        "name": "Manitoulin Transport — Standard CWT Tariff",
        "carrier_name": "Manitoulin Transport",
        "rating_basis": "WEIGHT_CWT",
        "currency": "CAD",
        "weight_unit": "lb",
        "allow_deficit_rating": True,
        "description": "Canadian CWT tariff (MIN, L5C, M5C, M1M, M2M, M5M, M10M) with City/FSA origin-destination pairs.",
        "header_aliases": {
            "L5C": "0-499 lbs",
            "M5C": "500-999 lbs",
            "M1M": "1000-1999 lbs",
            "M2M": "2000-4999 lbs",
            "M5M": "5000-9999 lbs",
            "M10M": "10000+ lbs",
        },
        "default_accessorials": [
            {"code": "TAILGATE", "name": "Power Tailgate Delivery", "condition_type": "tailgate", "fee_type": "FLAT", "amount": 65.0, "min_fee": 65.0},
            {"code": "HEATED", "name": "Heated / Protect From Freeze (Nov–Apr)", "condition_type": "heated", "fee_type": "PERCENTAGE", "amount": 15.0, "min_fee": 45.0},
            {"code": "RESIDENTIAL", "name": "Residential / Private Delivery", "condition_type": "residential", "fee_type": "FLAT", "amount": 75.0, "min_fee": 75.0},
            {"code": "APPOINTMENT", "name": "Appointment / Call Before Delivery", "condition_type": "appointment", "fee_type": "FLAT", "amount": 35.0, "min_fee": 35.0},
        ],
    },
    "DAY_AND_ROSS_CWT": {
        "id": "DAY_AND_ROSS_CWT",
        "name": "Day & Ross Freight — Canadian LTL CWT",
        "carrier_name": "Day & Ross Freight",
        "rating_basis": "WEIGHT_CWT",
        "currency": "CAD",
        "weight_unit": "lb",
        "allow_deficit_rating": True,
        "description": "Standard Day & Ross CWT tariff layout (MIN, <500, 500, 1000, 2000, 5000, 10000 lbs) with deficit rating.",
        "header_aliases": {
            "LTL MIN": "Minimum Charge",
            "L500": "0-499 lbs",
        },
        "default_accessorials": [
            {"code": "TAILGATE", "name": "Tailgate / Liftgate Service", "condition_type": "tailgate", "fee_type": "FLAT", "amount": 60.0, "min_fee": 60.0},
            {"code": "HEATED", "name": "Heated Service (Protect From Freeze)", "condition_type": "heated", "fee_type": "PERCENTAGE", "amount": 15.0, "min_fee": 50.0},
            {"code": "RESIDENTIAL", "name": "Residential Delivery", "condition_type": "residential", "fee_type": "FLAT", "amount": 70.0, "min_fee": 70.0},
            {"code": "APPOINTMENT", "name": "Appointment Delivery", "condition_type": "appointment", "fee_type": "FLAT", "amount": 30.0, "min_fee": 30.0},
        ],
    },
    "MIDLAND_ATLANTIC": {
        "id": "MIDLAND_ATLANTIC",
        "name": "Midland Transport — Atlantic & Central LTL",
        "carrier_name": "Midland Transport",
        "rating_basis": "WEIGHT_CWT",
        "currency": "CAD",
        "weight_unit": "lb",
        "allow_deficit_rating": True,
        "description": "Atlantic Canada (NS, NB, PE, NL) to ON/QC CWT rate layout with heated & tailgate defaults.",
        "header_aliases": {},
        "default_accessorials": [
            {"code": "TAILGATE", "name": "Hydraulic Tailgate", "condition_type": "tailgate", "fee_type": "FLAT", "amount": 55.0, "min_fee": 55.0},
            {"code": "HEATED", "name": "Heated / Temp Controlled LTL", "condition_type": "heated", "fee_type": "PERCENTAGE", "amount": 12.0, "min_fee": 40.0},
            {"code": "RESIDENTIAL", "name": "Residential Delivery", "condition_type": "residential", "fee_type": "FLAT", "amount": 65.0, "min_fee": 65.0},
        ],
    },
    "OVERLAND_WEST": {
        "id": "OVERLAND_WEST",
        "name": "Overland West / Western Canada LTL",
        "carrier_name": "Overland West Freight Lines",
        "rating_basis": "WEIGHT_CWT",
        "currency": "CAD",
        "weight_unit": "lb",
        "allow_deficit_rating": True,
        "description": "Western Canada (AB, BC, SK, MB) CWT tariff format supporting city-name and FSA lane matrices.",
        "header_aliases": {},
        "default_accessorials": [
            {"code": "TAILGATE", "name": "Power Tailgate", "condition_type": "tailgate", "fee_type": "FLAT", "amount": 65.0, "min_fee": 65.0},
            {"code": "HEATED", "name": "Heated Service", "condition_type": "heated", "fee_type": "PERCENTAGE", "amount": 15.0, "min_fee": 45.0},
        ],
    },
    "KINDERSLEY_PRAIRIE": {
        "id": "KINDERSLEY_PRAIRIE",
        "name": "Kindersley Transport — Prairie & Trans-Canada LTL",
        "carrier_name": "Kindersley Transport",
        "rating_basis": "WEIGHT_CWT",
        "currency": "CAD",
        "weight_unit": "lb",
        "allow_deficit_rating": True,
        "description": "Prairie & Central Canada CWT tariff with winter heated protection and rural delivery rules.",
        "header_aliases": {},
        "default_accessorials": [
            {"code": "TAILGATE", "name": "Tailgate Delivery", "condition_type": "tailgate", "fee_type": "FLAT", "amount": 60.0, "min_fee": 60.0},
            {"code": "HEATED", "name": "Protect From Freeze", "condition_type": "heated", "fee_type": "PERCENTAGE", "amount": 15.0, "min_fee": 45.0},
        ],
    },
    "GENERIC_SKID_SPOT": {
        "id": "GENERIC_SKID_SPOT",
        "name": "Canadian Skid / Pallet Spot Matrix (1–10 Skids)",
        "carrier_name": None,
        "rating_basis": "SKID_COUNT",
        "currency": "CAD",
        "weight_unit": "lb",
        "allow_deficit_rating": False,
        "description": "Flat per-skid / pallet count matrix (1 Skid, 2 Skids ... 10 Skids) common among regionalGTA/Western LTL fleets.",
        "header_aliases": {},
        "default_accessorials": [
            {"code": "TAILGATE", "name": "Tailgate Service", "condition_type": "tailgate", "fee_type": "FLAT", "amount": 50.0, "min_fee": 50.0},
        ],
    },
}


# ==============================================================================
# 2. BIG 6 CANADIAN LTL ACCESSORIALS CATALOG
# ==============================================================================

BIG_6_CANADIAN_ACCESSORIALS: List[Dict[str, Any]] = [
    {
        "code": "TAILGATE",
        "name": "Tailgate / Liftgate Delivery",
        "condition_type": "tailgate",
        "default_fee_type": "FLAT",
        "default_amount": 60.0,
        "default_min_fee": 60.0,
        "description": "Hydraulic power tailgate required at pickup or delivery dock.",
    },
    {
        "code": "HEATED",
        "name": "Heated / Protect From Freeze (Winter)",
        "condition_type": "heated",
        "default_fee_type": "PERCENTAGE",
        "default_amount": 15.0,
        "default_min_fee": 45.0,
        "description": "Heated trailer service (Nov 1 – Apr 30); supports % of base freight with a minimum dollar floor.",
    },
    {
        "code": "RESIDENTIAL",
        "name": "Residential / Private Address Delivery",
        "condition_type": "residential",
        "default_fee_type": "FLAT",
        "default_amount": 75.0,
        "default_min_fee": 75.0,
        "description": "Delivery to a non-commercial residence or home business.",
    },
    {
        "code": "APPOINTMENT",
        "name": "Appointment / Call Before Delivery",
        "condition_type": "appointment",
        "default_fee_type": "FLAT",
        "default_amount": 35.0,
        "default_min_fee": 35.0,
        "description": "Scheduled delivery window or consignee pre-notification required.",
    },
    {
        "code": "INSIDE_DELIVERY",
        "name": "Inside Delivery",
        "condition_type": "inside_delivery",
        "default_fee_type": "FLAT",
        "default_amount": 85.0,
        "default_min_fee": 85.0,
        "description": "Driver moves freight inside threshold beyond the immediate loading dock.",
    },
    {
        "code": "LIMITED_ACCESS",
        "name": "Limited Access / Construction / Mall",
        "condition_type": "limited_access",
        "default_fee_type": "FLAT",
        "default_amount": 75.0,
        "default_min_fee": 75.0,
        "description": "Job site, school, hospital, shopping mall, or restricted-entry facility.",
    },
]


def list_carrier_presets() -> List[Dict[str, Any]]:
    """Returns all available Canadian LTL carrier format presets."""
    return list(CANADIAN_CARRIER_PRESETS.values())


def get_carrier_preset(preset_id: Optional[str]) -> Dict[str, Any]:
    """Returns the requested preset or AUTO_DETECT if not found."""
    key = (preset_id or "AUTO_DETECT").strip().upper()
    return CANADIAN_CARRIER_PRESETS.get(key, CANADIAN_CARRIER_PRESETS["AUTO_DETECT"])


def apply_preset_to_sheet(sheet_id: str, user_id: str, preset_id: str) -> Dict[str, Any]:
    """
    Applies a Canadian Carrier Preset's default accessorials (only for codes not already present on the sheet)
    and updates carrier name if the sheet still has 'Unknown Carrier'.
    """
    preset = get_carrier_preset(preset_id)
    sheet = get_rate_sheet(sheet_id, user_id)
    if not sheet:
        raise ValueError(f"Rate sheet {sheet_id} not found.")

    conn = get_connection()
    cursor = conn.cursor()

    if preset.get("carrier_name") and sheet.get("carrier_name") in ("Unknown Carrier", "", None):
        cursor.execute(
            "UPDATE ql_rate_sheets SET carrier_name = ? WHERE id = ? AND user_id = ?",
            (preset["carrier_name"], sheet_id, user_id),
        )

    cursor.execute(
        "SELECT UPPER(surcharge_code) AS code FROM ql_carrier_surcharges WHERE sheet_id = ? AND user_id = ?",
        (sheet_id, user_id),
    )
    existing_codes = {row["code"] for row in cursor.fetchall()}

    inserted_count = 0
    for acc in preset.get("default_accessorials", []):
        code = acc["code"].upper()
        if code in existing_codes:
            continue
        s_id = f"sur_{uuid.uuid4().hex[:12]}"
        cursor.execute(
            """
            INSERT INTO ql_carrier_surcharges (
                id, sheet_id, user_id, surcharge_code, name, condition_type,
                fee_type, amount, min_fee, max_fee, is_waived, source_cell,
                is_included, weight_base, pct_base, fsc_eligible, is_unparsed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, 0, 'BILLABLE', 'POST_MIN_FREIGHT', 0, 0)
            """,
            (
                s_id,
                sheet_id,
                user_id,
                code,
                acc["name"],
                acc["condition_type"],
                acc["fee_type"],
                float(acc["amount"]),
                float(acc.get("min_fee", 0.0)),
                f"Preset ({preset['id']})",
            ),
        )
        inserted_count += 1

    conn.commit()
    conn.close()
    return {"preset_id": preset["id"], "inserted_accessorials": inserted_count}


def upsert_sheet_accessorial_matrix(
    sheet_id: str,
    user_id: str,
    accessorials: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Creates or updates per-carrier accessorial rules (e.g. TAILGATE, HEATED, RESIDENTIAL,
    APPOINTMENT, INSIDE_DELIVERY, LIMITED_ACCESS) on a specific rate sheet.
    Each item in `accessorials` supports:
      - code: str (e.g. 'TAILGATE', 'HEATED')
      - name: Optional[str]
      - condition_type: Optional[str]
      - fee_type: 'FLAT' | 'PERCENTAGE' | 'CWT'
      - amount: float
      - min_fee: Optional[float]
      - max_fee: Optional[float]
      - is_waived: Optional[bool]
      - enabled: Optional[bool] (if False, removes the accessorial from the sheet)
    """
    sheet = get_rate_sheet(sheet_id, user_id)
    if not sheet:
        raise ValueError(f"Rate sheet '{sheet_id}' not found or unauthorized.")

    catalog_by_code = {item["code"]: item for item in BIG_6_CANADIAN_ACCESSORIALS}

    conn = get_connection()
    cursor = conn.cursor()

    for item in accessorials:
        code = str(item.get("code") or "").strip().upper()
        if not code:
            continue

        enabled = item.get("enabled", True)
        # Remove existing row for this surcharge_code on this sheet
        cursor.execute(
            "DELETE FROM ql_carrier_surcharges WHERE sheet_id = ? AND user_id = ? AND UPPER(surcharge_code) = ?",
            (sheet_id, user_id, code),
        )
        if not enabled:
            continue

        cat = catalog_by_code.get(code, {})
        name = str(item.get("name") or cat.get("name") or code).strip()
        cond_type = str(item.get("condition_type") or cat.get("condition_type") or code.lower()).strip().lower()
        fee_type = str(item.get("fee_type") or cat.get("default_fee_type") or "FLAT").strip().upper()
        if fee_type == "PCT":
            fee_type = "PERCENTAGE"

        amount = float(item.get("amount") if item.get("amount") is not None else cat.get("default_amount", 0.0))
        min_fee = float(item.get("min_fee") if item.get("min_fee") is not None else cat.get("default_min_fee", 0.0))
        max_fee = float(item["max_fee"]) if item.get("max_fee") not in (None, "", 0, "0") else None
        is_waived = 1 if item.get("is_waived") else 0

        s_id = f"sur_{uuid.uuid4().hex[:12]}"
        cursor.execute(
            """
            INSERT INTO ql_carrier_surcharges (
                id, sheet_id, user_id, surcharge_code, name, condition_type,
                fee_type, amount, min_fee, max_fee, is_waived, source_cell,
                is_included, weight_base, pct_base, fsc_eligible, is_unparsed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'BILLABLE', 'POST_MIN_FREIGHT', 0, 0)
            """,
            (
                s_id,
                sheet_id,
                user_id,
                code,
                name,
                cond_type,
                fee_type,
                amount,
                min_fee,
                max_fee,
                is_waived,
                "Broker Accessorial Matrix",
            ),
        )

    conn.commit()
    cursor.execute(
        "SELECT * FROM ql_carrier_surcharges WHERE sheet_id = ? AND user_id = ? ORDER BY surcharge_code ASC",
        (sheet_id, user_id),
    )
    updated_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return updated_rows
