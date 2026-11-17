"""
services/fuel_index_service.py
==============================
Quotelytics Canadian Weekly Fuel Surcharge (FSC) Index Manager.

Manages Canadian diesel fuel benchmarks (Ontario Trucking Association / OTA,
Freight Carriers Association of Canada / FCA, and Regional Canadian Indices),
tenant-level fuel preferences, and deterministic FSC calculation.
"""

import sqlite3
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from services.quotelytics_db_service import get_connection

# Standard published Canadian Freight Benchmark Indices (October 2026 Baseline)
CANADIAN_BENCHMARK_INDICES = [
    {
        "index_code": "OTA_LTL_STANDARD",
        "index_name": "Ontario Trucking Association (OTA) LTL Index",
        "source": "Ontario Trucking Association Weekly Diesel Survey",
        "diesel_price_cad_litre": 1.685,
        "ltl_surcharge_percent": 31.50,
        "tl_surcharge_percent": 48.20,
        "effective_date": "2026-09-28",
        "is_default": True
    },
    {
        "index_code": "FCA_NATIONAL_LTL",
        "index_name": "Freight Carriers Association of Canada (FCA) Benchmark",
        "source": "Freight Carriers Association of Canada",
        "diesel_price_cad_litre": 1.710,
        "ltl_surcharge_percent": 33.00,
        "tl_surcharge_percent": 49.50,
        "effective_date": "2026-09-28",
        "is_default": False
    },
    {
        "index_code": "WESTERN_CDN_LTL",
        "index_name": "Western Canada Interprovincial Diesel Index",
        "source": "Alberta / BC Motor Transport Association",
        "diesel_price_cad_litre": 1.640,
        "ltl_surcharge_percent": 30.50,
        "tl_surcharge_percent": 46.80,
        "effective_date": "2026-09-28",
        "is_default": False
    },
    {
        "index_code": "ATLANTIC_CDN_LTL",
        "index_name": "Atlantic Provinces Trucking Association (APTA) Index",
        "source": "Atlantic Provinces Trucking Association",
        "diesel_price_cad_litre": 1.745,
        "ltl_surcharge_percent": 34.20,
        "tl_surcharge_percent": 51.00,
        "effective_date": "2026-09-28",
        "is_default": False
    }
]

def init_fuel_indices_table():
    """Initializes the ql_fuel_settings and ql_fuel_history tables."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_fuel_settings (
        user_id TEXT PRIMARY KEY,
        active_index_code TEXT NOT NULL DEFAULT 'OTA_LTL_STANDARD',
        custom_ltl_percent REAL,
        use_carrier_sheet_fsc INTEGER NOT NULL DEFAULT 1,
        auto_update_weekly INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_fuel_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        index_code TEXT NOT NULL,
        diesel_price_cad_litre REAL NOT NULL,
        ltl_surcharge_percent REAL NOT NULL,
        tl_surcharge_percent REAL NOT NULL,
        effective_date TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()

# Ensure table creation on import
init_fuel_indices_table()

def get_available_benchmark_indices() -> List[Dict[str, Any]]:
    """Returns available Canadian benchmark diesel indices."""
    return CANADIAN_BENCHMARK_INDICES

def get_tenant_fuel_settings(user_id: str) -> Dict[str, Any]:
    """Retrieves fuel settings for a tenant, initializing default if not present."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM ql_fuel_settings WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        now_str = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT INTO ql_fuel_settings (user_id, active_index_code, custom_ltl_percent, use_carrier_sheet_fsc, auto_update_weekly, updated_at)
        VALUES (?, 'OTA_LTL_STANDARD', NULL, 1, 1, ?)
        """, (user_id, now_str))
        conn.commit()
        cursor.execute("SELECT * FROM ql_fuel_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

    conn.close()
    settings = dict(row)

    # Attach metadata for active index
    active_code = settings["active_index_code"]
    active_meta = next((idx for idx in CANADIAN_BENCHMARK_INDICES if idx["index_code"] == active_code), CANADIAN_BENCHMARK_INDICES[0])
    settings["active_index_meta"] = active_meta

    effective_pct = settings["custom_ltl_percent"] if settings["custom_ltl_percent"] is not None else active_meta["ltl_surcharge_percent"]
    settings["effective_ltl_percent"] = effective_pct

    return settings

def update_tenant_fuel_settings(
    user_id: str,
    active_index_code: str = "OTA_LTL_STANDARD",
    custom_ltl_percent: Optional[float] = None,
    use_carrier_sheet_fsc: bool = True,
    auto_update_weekly: bool = True
) -> Dict[str, Any]:
    """Updates broker tenant fuel index configuration."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()

    cursor.execute("""
    INSERT INTO ql_fuel_settings (user_id, active_index_code, custom_ltl_percent, use_carrier_sheet_fsc, auto_update_weekly, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        active_index_code = excluded.active_index_code,
        custom_ltl_percent = excluded.custom_ltl_percent,
        use_carrier_sheet_fsc = excluded.use_carrier_sheet_fsc,
        auto_update_weekly = excluded.auto_update_weekly,
        updated_at = excluded.updated_at
    """, (user_id, active_index_code, custom_ltl_percent, 1 if use_carrier_sheet_fsc else 0, 1 if auto_update_weekly else 0, now_str))

    conn.commit()
    conn.close()
    return get_tenant_fuel_settings(user_id)

def record_fuel_index_history(
    index_code_or_date: str,
    diesel_price_cad_litre: float,
    ltl_surcharge_percent: float,
    tl_surcharge_percent: float,
    effective_date: Optional[str] = None,
    source: Optional[str] = None,
    index_code: Optional[str] = None,
) -> None:
    """Inserts a dated benchmark fuel index record into ql_fuel_history."""
    # Support calling with (effective_date, diesel, ltl_pct, tl_pct, source=...) or (index_code, diesel, ltl_pct, tl_pct, effective_date)
    if effective_date is None and len(index_code_or_date.strip()) == 10 and index_code_or_date.strip()[4] == "-":
        eff_date_str = index_code_or_date.strip()
        idx_code_str = (index_code or "OTA_LTL_STANDARD").strip().upper()
    else:
        idx_code_str = (index_code or index_code_or_date).strip().upper()
        eff_date_str = (effective_date or datetime.utcnow().strftime("%Y-%m-%d")).strip()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO ql_fuel_history (
            index_code, diesel_price_cad_litre, ltl_surcharge_percent,
            tl_surcharge_percent, effective_date, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            idx_code_str,
            float(diesel_price_cad_litre),
            float(ltl_surcharge_percent),
            float(tl_surcharge_percent),
            eff_date_str,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def resolve_effective_fuel_surcharge(
    user_id: str,
    carrier_sheet_fsc: Optional[float] = None,
    base_freight: float = 0.0,
    is_fuel_included: bool = False,
    fuel_precedence: str = "SHEET_FIRST",
    shipment_date: Optional[str] = None,
    sheet_fsc_pct: Optional[float] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Deterministically computes the active Fuel Surcharge (FSC) percentage and dollar amount.
    - If is_fuel_included is True (e.g. tariff states 'Fuel Included'), returns 0.0% ($0.00).
    - If fuel_precedence == 'SHEET_FIRST' and carrier_sheet_fsc is present (>0), uses sheet's FSC.
    - Otherwise (or when fuel_precedence == 'BENCHMARK_FIRST'), looks up the benchmark index
      at shipment_date in ql_fuel_history (falling back to tenant active index).
    - Uses Decimal ROUND_HALF_UP for monetary quantization.
    """
    from decimal import Decimal, ROUND_HALF_UP

    if carrier_sheet_fsc is None and sheet_fsc_pct is not None:
        carrier_sheet_fsc = sheet_fsc_pct

    if is_fuel_included:
        return {
            "fsc_percent": 0.0,
            "fsc_amount": 0.0,
            "source": "Fuel Included in Tariff (0%)",
            "diesel_benchmark": None,
            "index_code": "INCLUDED",
            "effective_date": shipment_date,
        }

    settings = get_tenant_fuel_settings(user_id)
    active_code = settings["active_index_code"]
    prec = (fuel_precedence or "SHEET_FIRST").upper()
    use_sheet = (
        prec != "BENCHMARK_FIRST"
        and carrier_sheet_fsc is not None
        and float(carrier_sheet_fsc) > 0
        and bool(settings.get("use_carrier_sheet_fsc", 1))
    )

    eff_date_used = settings["active_index_meta"].get("effective_date")

    if use_sheet:
        fsc_pct = float(carrier_sheet_fsc)
        source = "Carrier Published Tariff FSC"
    else:
        hist_pct = None
        if shipment_date and settings.get("custom_ltl_percent") is None:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT ltl_surcharge_percent, effective_date
                FROM ql_fuel_history
                WHERE index_code = ? AND effective_date <= ?
                ORDER BY effective_date DESC, id DESC
                LIMIT 1
                """,
                (active_code, shipment_date),
            )
            h_row = cursor.fetchone()
            conn.close()
            if h_row:
                hist_pct = float(h_row["ltl_surcharge_percent"])
                eff_date_used = h_row["effective_date"]

        if hist_pct is not None:
            fsc_pct = hist_pct
        else:
            fsc_pct = float(settings["effective_ltl_percent"])
        source = f"{settings['active_index_meta']['index_name']} ({fsc_pct:.1f}%)"

    d_base = Decimal(str(base_freight))
    d_pct = Decimal(str(fsc_pct))
    d_amt = ((d_base * d_pct) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "fsc_percent": fsc_pct,
        "fsc_amount": float(d_amt),
        "source": source,
        "diesel_benchmark": settings["active_index_meta"].get("diesel_price_cad_litre"),
        "index_code": active_code,
        "effective_date": eff_date_used,
    }


def calculate_fsc_from_diesel_price(
    diesel_price_cad_litre: float,
    mode: str = "LTL",
) -> Dict[str, Any]:
    """
    Calculates the standard Canadian FCA / OTA LTL and TL Fuel Surcharge % directly from
    the current weekly Canadian retail diesel price ($ CAD / litre).
    Formula (Canadian LTL Benchmark Scale):
      - Base threshold: $1.050 CAD/litre -> 15.625% LTL base
      - Every $0.01/L above $1.050/L adds +0.25% to LTL FSC (and +0.42% to TL FSC).
      (At $1.685/L -> 31.50% LTL FSC, matching OTA_LTL_STANDARD).
    """
    from decimal import Decimal, ROUND_HALF_UP

    price = max(0.50, float(diesel_price_cad_litre or 1.685))
    delta_cents = max(0.0, (price - 1.050) * 100.0)

    ltl_pct = round(15.625 + (delta_cents * 0.25), 2)
    tl_pct = round(21.53 + (delta_cents * 0.42), 2)
    selected_mode = (mode or "LTL").strip().upper()
    effective_pct = tl_pct if selected_mode in ("TL", "FTL", "TRUCKLOAD") else ltl_pct

    return {
        "diesel_price_cad_litre": round(price, 3),
        "mode": selected_mode,
        "ltl_surcharge_percent": ltl_pct,
        "tl_surcharge_percent": tl_pct,
        "effective_surcharge_percent": effective_pct,
        "formula_note": f"Canadian FCA/OTA Diesel Bracket Scale at ${price:.3f} CAD/L -> {effective_pct:.2f}% {selected_mode} FSC",
    }

