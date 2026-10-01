"""
services/fuel_index_service.py
==============================
RateSift Canadian Weekly Fuel Surcharge (FSC) Index Manager.

Manages Canadian diesel fuel benchmarks (Ontario Trucking Association / OTA,
Freight Carriers Association of Canada / FCA, and Regional Canadian Indices),
tenant-level fuel preferences, and deterministic FSC calculation.
"""

import sqlite3
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from services.ratesift_db_service import get_connection

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
    """Initializes the rs_fuel_settings and rs_fuel_history tables."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_fuel_settings (
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
    CREATE TABLE IF NOT EXISTS rs_fuel_history (
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

    cursor.execute("SELECT * FROM rs_fuel_settings WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        now_str = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT INTO rs_fuel_settings (user_id, active_index_code, custom_ltl_percent, use_carrier_sheet_fsc, auto_update_weekly, updated_at)
        VALUES (?, 'OTA_LTL_STANDARD', NULL, 1, 1, ?)
        """, (user_id, now_str))
        conn.commit()
        cursor.execute("SELECT * FROM rs_fuel_settings WHERE user_id = ?", (user_id,))
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
    INSERT INTO rs_fuel_settings (user_id, active_index_code, custom_ltl_percent, use_carrier_sheet_fsc, auto_update_weekly, updated_at)
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

def resolve_effective_fuel_surcharge(
    user_id: str,
    carrier_sheet_fsc: Optional[float] = None,
    base_freight: float = 0.0
) -> Dict[str, Any]:
    """
    Deterministically computes the active Fuel Surcharge (FSC) percentage and dollar amount.
    - If sheet has its own explicit FSC and tenant has use_carrier_sheet_fsc=True, uses sheet's FSC.
    - Otherwise, falls back to broker's active Canadian benchmark index (e.g. OTA 31.5%).
    """
    settings = get_tenant_fuel_settings(user_id)

    if carrier_sheet_fsc is not None and carrier_sheet_fsc > 0 and settings.get("use_carrier_sheet_fsc", 1):
        fsc_pct = float(carrier_sheet_fsc)
        source = "Carrier Published Tariff FSC"
    else:
        fsc_pct = float(settings["effective_ltl_percent"])
        source = f"{settings['active_index_meta']['index_name']} ({fsc_pct:.1f}%)"

    fsc_amount = round((fsc_pct / 100.0) * base_freight, 2)

    return {
        "fsc_percent": fsc_pct,
        "fsc_amount": fsc_amount,
        "source": source,
        "diesel_benchmark": settings["active_index_meta"].get("diesel_price_cad_litre")
    }
