import sqlite3
import os
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "shipflow.db")
DATA_RESIDENCY_REGION = "CA_CENTRAL_WHC"  # Rule 29: Canadian Hosting (WHC)

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_ratesift_db():
    """
    Initializes the RateSift normalized multi-tenant schema.
    Strictly enforces Rules 2, 3, 28, 29, 30.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # 1. Rate Sheets Table (Rule 2, 5, 7, 16, 17, 28, 29)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_rate_sheets (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        carrier_name TEXT NOT NULL,
        service_name TEXT NOT NULL,
        tariff_ref TEXT,
        mode TEXT NOT NULL DEFAULT 'LTL',
        currency TEXT NOT NULL DEFAULT 'CAD',
        weight_unit TEXT NOT NULL DEFAULT 'lb',
        dim_unit TEXT NOT NULL DEFAULT 'in',
        dim_divisor REAL NOT NULL DEFAULT 139.0,
        dim_min_rule TEXT,
        rounding_rule TEXT NOT NULL DEFAULT 'standard_2dp',
        effective_date TEXT,
        expiry_date TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        is_latest INTEGER NOT NULL DEFAULT 1,
        confirmation_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
        source_filename TEXT NOT NULL,
        storage_region TEXT NOT NULL DEFAULT 'CA_CENTRAL_WHC',
        created_at TEXT NOT NULL,
        confirmed_by TEXT,
        confirmed_at TEXT,
        is_benchmark INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_sheets_user ON rs_rate_sheets (user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_sheets_carrier ON rs_rate_sheets (user_id, carrier_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_sheets_status ON rs_rate_sheets (user_id, confirmation_status)")

    # Auto-migrate columns if table already exists
    cursor.execute("PRAGMA table_info(rs_rate_sheets)")
    rs_cols = [r["name"] for r in cursor.fetchall()]
    if "is_benchmark" not in rs_cols:
        cursor.execute("ALTER TABLE rs_rate_sheets ADD COLUMN is_benchmark INTEGER DEFAULT 0")
    if "markup_mode" not in rs_cols:
        cursor.execute("ALTER TABLE rs_rate_sheets ADD COLUMN markup_mode TEXT DEFAULT 'PERCENTAGE'")
    if "markup_value" not in rs_cols:
        cursor.execute("ALTER TABLE rs_rate_sheets ADD COLUMN markup_value REAL DEFAULT 0.0")
    if "fsc_passthrough" not in rs_cols:
        cursor.execute("ALTER TABLE rs_rate_sheets ADD COLUMN fsc_passthrough INTEGER DEFAULT 1")
    if "accessorial_markup_pct" not in rs_cols:
        cursor.execute("ALTER TABLE rs_rate_sheets ADD COLUMN accessorial_markup_pct REAL DEFAULT 0.0")
    if "manual_override" not in rs_cols:
        cursor.execute("ALTER TABLE rs_rate_sheets ADD COLUMN manual_override INTEGER DEFAULT 0")

    # 2. Rate Sheet Cell Coordinates Traceability Table (Rule 3, 6, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_rate_sheet_cells (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        sheet_tab TEXT NOT NULL DEFAULT 'Sheet 1',
        cell_coord TEXT NOT NULL,
        field_name TEXT NOT NULL,
        raw_value TEXT,
        extracted_value TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        needs_review INTEGER NOT NULL DEFAULT 0,
        review_notes TEXT,
        FOREIGN KEY (sheet_id) REFERENCES rs_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_cells_sheet ON rs_rate_sheet_cells (sheet_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_cells_user ON rs_rate_sheet_cells (user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_cells_review ON rs_rate_sheet_cells (sheet_id, needs_review)")

    # 3. Carrier Zones Mapping Table (Rule 10, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_carrier_zones (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        origin_spec TEXT NOT NULL,
        dest_spec TEXT NOT NULL,
        zone_code TEXT NOT NULL,
        transit_days INTEGER,
        source_cell TEXT,
        FOREIGN KEY (sheet_id) REFERENCES rs_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_zones_lookup ON rs_carrier_zones (sheet_id, origin_spec, dest_spec)")

    # 4. Weight Break Rates Matrix Table (Rule 2, 8, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_weight_breaks (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        zone_code TEXT NOT NULL,
        origin_spec TEXT,
        dest_spec TEXT,
        min_weight REAL NOT NULL DEFAULT 0.0,
        max_weight REAL NOT NULL DEFAULT 999999.0,
        break_name TEXT NOT NULL,
        base_rate REAL NOT NULL,
        rate_type TEXT NOT NULL DEFAULT 'CWT',
        source_cell TEXT,
        FOREIGN KEY (sheet_id) REFERENCES rs_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_breaks_lookup ON rs_weight_breaks (sheet_id, zone_code, min_weight, max_weight)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_breaks_od ON rs_weight_breaks (sheet_id, origin_spec, dest_spec)")

    # 5. Carrier Minimum Charges Table (Rule 12, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_carrier_minimums (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        zone_code TEXT,
        origin_spec TEXT,
        dest_spec TEXT,
        min_charge REAL NOT NULL,
        source_cell TEXT,
        FOREIGN KEY (sheet_id) REFERENCES rs_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_min_lookup ON rs_carrier_minimums (sheet_id, zone_code)")

    # 6. Carrier Surcharges & Accessorials Table (Rule 2, 4, 11, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_carrier_surcharges (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        surcharge_code TEXT NOT NULL,
        name TEXT NOT NULL,
        condition_type TEXT NOT NULL,
        condition_expression TEXT,
        fee_type TEXT NOT NULL DEFAULT 'FLAT',
        amount REAL NOT NULL DEFAULT 0.0,
        min_fee REAL NOT NULL DEFAULT 0.0,
        max_fee REAL,
        is_waived INTEGER NOT NULL DEFAULT 0,
        source_cell TEXT,
        FOREIGN KEY (sheet_id) REFERENCES rs_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_surcharges_sheet ON rs_carrier_surcharges (sheet_id)")

    # 7. Immutable Quote Audit Logs Table (Rule 28, 29, 30)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rs_quote_audit_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        shipment_input_json TEXT NOT NULL,
        sheets_considered_json TEXT NOT NULL,
        sheets_excluded_json TEXT NOT NULL,
        calculation_trace_json TEXT NOT NULL,
        final_results_json TEXT NOT NULL,
        data_residency_region TEXT NOT NULL DEFAULT 'CA_CENTRAL_WHC',
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rs_audit_user ON rs_quote_audit_logs (user_id, timestamp)")

    conn.commit()
    conn.close()

# ==============================================================================
# Multi-Tenant Data Access Layer (Strict user_id enforcement - Rule 28)
# ==============================================================================

def create_rate_sheet(
    user_id: str,
    carrier_name: str,
    service_name: str,
    tariff_ref: Optional[str] = None,
    mode: str = "LTL",

    currency: str = "CAD",
    weight_unit: str = "lb",
    dim_unit: str = "in",
    dim_divisor: float = 139.0,
    dim_min_rule: Optional[str] = None,
    rounding_rule: str = "standard_2dp",
    effective_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    version: int = 1,
    source_filename: str = "",
    confirmation_status: str = "PENDING_REVIEW",
    is_benchmark: int = 0
) -> str:
    """Creates a new rate sheet record strictly scoped to user_id."""
    sheet_id = f"rs_sheet_{uuid.uuid4().hex[:12]}"
    now_ts = datetime.utcnow().isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO rs_rate_sheets (
        id, user_id, carrier_name, service_name, tariff_ref, mode,
        currency, weight_unit, dim_unit, dim_divisor, dim_min_rule,
        rounding_rule, effective_date, expiry_date, version, is_latest,
        confirmation_status, source_filename, storage_region, created_at, is_benchmark
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
    """, (
        sheet_id, user_id, carrier_name.strip(), service_name.strip(),
        tariff_ref.strip() if tariff_ref else None, mode.upper(),
        currency.upper(), weight_unit.lower(), dim_unit.lower(),
        float(dim_divisor), dim_min_rule, rounding_rule,
        effective_date, expiry_date, int(version),
        confirmation_status, source_filename, DATA_RESIDENCY_REGION, now_ts, int(is_benchmark)
    ))
    conn.commit()
    conn.close()
    return sheet_id

def get_rate_sheet(sheet_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a rate sheet by ID, strictly verifying ownership and excluding sample/benchmark sheets (Rule 28)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM rs_rate_sheets 
    WHERE id = ? AND user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL)
    """, (sheet_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def list_rate_sheets(user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists all rate sheets uploaded by user_id, strictly excluding benchmark/sample sheets (Rule 28)."""
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
        SELECT * FROM rs_rate_sheets 
        WHERE user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL) AND confirmation_status = ? 
        ORDER BY created_at DESC
        """, (user_id, status.upper()))
    else:
        cursor.execute("""
        SELECT * FROM rs_rate_sheets 
        WHERE user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL) 
        ORDER BY created_at DESC
        """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def confirm_rate_sheet(
    sheet_id: str,
    user_id: str,
    confirmed_by: str,
    currency: Optional[str] = None,
    weight_unit: Optional[str] = None,
    dim_divisor: Optional[float] = None,
    effective_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    rounding_rule: Optional[str] = None,
    markup_mode: str = "PERCENTAGE",
    markup_value: float = 0.0,
    fsc_passthrough: bool = True,
    accessorial_markup_pct: float = 0.0,
    manual_override: bool = False,
    resolve_flags: bool = False
) -> bool:
    """Enforces human confirmation gate (Rule 7, 19), confirms core rules (Rule 5, 15, 16), and stores broker markup settings."""
    now_ts = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build dynamic update query to preserve existing values if not explicitly overwritten
    updates = [
        "confirmation_status = 'CONFIRMED'",
        "confirmed_by = ?",
        "confirmed_at = ?",
        "markup_mode = ?",
        "markup_value = ?",
        "fsc_passthrough = ?",
        "accessorial_markup_pct = ?",
        "manual_override = ?"
    ]
    params = [
        confirmed_by,
        now_ts,
        markup_mode,
        float(markup_value or 0.0),
        1 if fsc_passthrough else 0,
        float(accessorial_markup_pct or 0.0),
        1 if manual_override else 0
    ]
    
    if currency:
        updates.append("currency = ?")
        params.append(currency.strip().upper())
    if weight_unit:
        updates.append("weight_unit = ?")
        params.append(weight_unit.strip().lower())
    if dim_divisor is not None and float(dim_divisor) > 0:
        updates.append("dim_divisor = ?")
        params.append(float(dim_divisor))
    if effective_date is not None:
        updates.append("effective_date = ?")
        params.append(effective_date.strip() if effective_date else None)
    if expiry_date is not None:
        updates.append("expiry_date = ?")
        params.append(expiry_date.strip() if expiry_date else None)
    if rounding_rule:
        updates.append("rounding_rule = ?")
        params.append(rounding_rule.strip())

    params.extend([sheet_id, user_id])
    sql = f"UPDATE rs_rate_sheets SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
    cursor.execute(sql, params)
    affected = cursor.rowcount > 0
    
    # Resolve review flags if requested
    if resolve_flags and affected:
        cursor.execute("UPDATE rs_rate_sheet_cells SET needs_review = 0 WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))

    conn.commit()
    conn.close()
    return affected

def update_rate_sheet_markup(
    sheet_id: str,
    user_id: str,
    currency: Optional[str] = None,
    weight_unit: Optional[str] = None,
    dim_divisor: Optional[float] = None,
    effective_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    rounding_rule: Optional[str] = None,
    markup_mode: str = "PERCENTAGE",
    markup_value: float = 0.0,
    fsc_passthrough: bool = True,
    accessorial_markup_pct: float = 0.0,
    manual_override: bool = False
) -> bool:
    """Updates markup rules and confirmed rules on a rate sheet without changing confirmation status."""
    conn = get_connection()
    cursor = conn.cursor()
    updates = [
        "markup_mode = ?",
        "markup_value = ?",
        "fsc_passthrough = ?",
        "accessorial_markup_pct = ?",
        "manual_override = ?"
    ]
    params = [
        markup_mode,
        float(markup_value or 0.0),
        1 if fsc_passthrough else 0,
        float(accessorial_markup_pct or 0.0),
        1 if manual_override else 0
    ]
    if currency:
        updates.append("currency = ?")
        params.append(currency.strip().upper())
    if weight_unit:
        updates.append("weight_unit = ?")
        params.append(weight_unit.strip().lower())
    if dim_divisor is not None and float(dim_divisor) > 0:
        updates.append("dim_divisor = ?")
        params.append(float(dim_divisor))
    if effective_date is not None:
        updates.append("effective_date = ?")
        params.append(effective_date.strip() if effective_date else None)
    if expiry_date is not None:
        updates.append("expiry_date = ?")
        params.append(expiry_date.strip() if expiry_date else None)
    if rounding_rule:
        updates.append("rounding_rule = ?")
        params.append(rounding_rule.strip())

    params.extend([sheet_id, user_id])
    sql = f"UPDATE rs_rate_sheets SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
    cursor.execute(sql, params)
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def toggle_surcharge_waived(sheet_id: str, user_id: str, surcharge_code: str, is_waived: bool) -> bool:
    """Toggles waived fee status for a surcharge (Rule 4 & 11)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE rs_carrier_surcharges
    SET is_waived = ?
    WHERE sheet_id = ? AND user_id = ? AND surcharge_code = ?
    """, (1 if is_waived else 0, sheet_id, user_id, surcharge_code))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def resolve_flagged_cell(sheet_id: str, user_id: str, cell_coord: str) -> bool:
    """Marks a flagged coordinate as verified and resolved by human broker (Rule 6)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE rs_rate_sheet_cells
    SET needs_review = 0, review_notes = review_notes || ' [Verified by broker]'
    WHERE sheet_id = ? AND user_id = ? AND cell_coord = ?
    """, (sheet_id, user_id, cell_coord))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def archive_rate_sheet(sheet_id: str, user_id: str) -> bool:
    """Archives a rate sheet so it is no longer quoted."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE rs_rate_sheets
    SET confirmation_status = 'ARCHIVED', is_latest = 0
    WHERE id = ? AND user_id = ?
    """, (sheet_id, user_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def delete_rate_sheet(sheet_id: str, user_id: str) -> bool:
    """Deletes a rate sheet and cascades to its child records."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("DELETE FROM rs_rate_sheets WHERE id = ? AND user_id = ?", (sheet_id, user_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

# ==============================================================================
# Cell Traceability Layer (Rule 3 & 6)
# ==============================================================================

def insert_rate_sheet_cells(sheet_id: str, user_id: str, cells: List[Dict[str, Any]]):
    """Batch-inserts cell coordinate traceability logs."""
    if not cells:
        return
    conn = get_connection()
    cursor = conn.cursor()
    records = []
    for c in cells:
        records.append((
            f"rs_cell_{uuid.uuid4().hex[:12]}",
            sheet_id,
            user_id,
            c.get("sheet_tab", "Sheet 1"),
            c["cell_coord"],
            c["field_name"],
            str(c.get("raw_value", "")),
            str(c.get("extracted_value", "")),
            float(c.get("confidence", 1.0)),
            1 if c.get("needs_review") else 0,
            c.get("review_notes", "")
        ))
    cursor.executemany("""
    INSERT INTO rs_rate_sheet_cells (
        id, sheet_id, user_id, sheet_tab, cell_coord, field_name,
        raw_value, extracted_value, confidence, needs_review, review_notes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()

def get_rate_sheet_cells(sheet_id: str, user_id: str, needs_review_only: bool = False) -> List[Dict[str, Any]]:
    """Retrieves cell audit records with coordinates, strictly verified by user_id."""
    conn = get_connection()
    cursor = conn.cursor()
    if needs_review_only:
        cursor.execute("""
        SELECT * FROM rs_rate_sheet_cells WHERE sheet_id = ? AND user_id = ? AND needs_review = 1
        """, (sheet_id, user_id))
    else:
        cursor.execute("""
        SELECT * FROM rs_rate_sheet_cells WHERE sheet_id = ? AND user_id = ?
        """, (sheet_id, user_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ==============================================================================
# Zones, Weight Breaks, Minimums & Surcharges (Rule 2, 8, 10, 11, 12)
# ==============================================================================

def insert_carrier_zones(sheet_id: str, user_id: str, zones: List[Dict[str, Any]]):
    """Inserts carrier-specific origin/dest to zone mappings."""
    if not zones:
        return
    conn = get_connection()
    cursor = conn.cursor()
    records = [
        (
            f"rs_zn_{uuid.uuid4().hex[:12]}",
            sheet_id,
            user_id,
            z["origin_spec"].strip().upper(),
            z["dest_spec"].strip().upper(),
            z["zone_code"].strip().upper(),
            z.get("transit_days"),
            z.get("source_cell", "")
        )
        for z in zones
    ]
    cursor.executemany("""
    INSERT INTO rs_carrier_zones (
        id, sheet_id, user_id, origin_spec, dest_spec, zone_code, transit_days, source_cell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()

def insert_weight_breaks(sheet_id: str, user_id: str, breaks: List[Dict[str, Any]]):
    """Inserts normalized matrix rate breaks."""
    if not breaks:
        return
    conn = get_connection()
    cursor = conn.cursor()
    records = [
        (
            f"rs_wb_{uuid.uuid4().hex[:12]}",
            sheet_id,
            user_id,
            b.get("zone_code", "DEFAULT").strip().upper(),
            b.get("origin_spec", "").strip().upper() if b.get("origin_spec") else None,
            b.get("dest_spec", "").strip().upper() if b.get("dest_spec") else None,
            float(b.get("min_weight", 0.0)),
            float(b.get("max_weight", 999999.0)),
            b["break_name"].strip(),
            float(b["base_rate"]),
            b.get("rate_type", "CWT").upper(),
            b.get("source_cell", "")
        )
        for b in breaks
    ]
    cursor.executemany("""
    INSERT INTO rs_weight_breaks (
        id, sheet_id, user_id, zone_code, origin_spec, dest_spec,
        min_weight, max_weight, break_name, base_rate, rate_type, source_cell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()

def insert_carrier_minimums(sheet_id: str, user_id: str, minimums: List[Dict[str, Any]]):
    """Inserts carrier minimum charge rules."""
    if not minimums:
        return
    conn = get_connection()
    cursor = conn.cursor()
    records = [
        (
            f"rs_min_{uuid.uuid4().hex[:12]}",
            sheet_id,
            user_id,
            m.get("zone_code", "").strip().upper() if m.get("zone_code") else None,
            m.get("origin_spec", "").strip().upper() if m.get("origin_spec") else None,
            m.get("dest_spec", "").strip().upper() if m.get("dest_spec") else None,
            float(m["min_charge"]),
            m.get("source_cell", "")
        )
        for m in minimums
    ]
    cursor.executemany("""
    INSERT INTO rs_carrier_minimums (
        id, sheet_id, user_id, zone_code, origin_spec, dest_spec, min_charge, source_cell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()

def insert_carrier_surcharges(sheet_id: str, user_id: str, surcharges: List[Dict[str, Any]]):
    """Inserts itemized conditional surcharges and accessorials."""
    if not surcharges:
        return
    conn = get_connection()
    cursor = conn.cursor()
    records = [
        (
            f"rs_sur_{uuid.uuid4().hex[:12]}",
            sheet_id,
            user_id,
            s["surcharge_code"].strip().upper(),
            s["name"].strip(),
            s["condition_type"].strip().lower(),
            json.dumps(s.get("condition_expression", {})) if isinstance(s.get("condition_expression"), (dict, list)) else s.get("condition_expression"),
            s.get("fee_type", "FLAT").upper(),
            float(s.get("amount", 0.0)),
            float(s.get("min_fee", 0.0)),
            float(s["max_fee"]) if s.get("max_fee") is not None else None,
            1 if s.get("is_waived") else 0,
            s.get("source_cell", "")
        )
        for s in surcharges
    ]
    cursor.executemany("""
    INSERT INTO rs_carrier_surcharges (
        id, sheet_id, user_id, surcharge_code, name, condition_type,
        condition_expression, fee_type, amount, min_fee, max_fee, is_waived, source_cell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()

def get_sheet_full_rules(sheet_id: str, user_id: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
    """Retrieves all associated rules for a rate sheet (breaks, zones, surcharges, minimums). Supports optional break pagination."""
    sheet = get_rate_sheet(sheet_id, user_id)
    if not sheet:
        return {}
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM rs_carrier_zones WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    zones = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT COUNT(*) FROM rs_weight_breaks WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    total_breaks_count = cursor.fetchone()[0]
    
    if limit is not None:
        cursor.execute("SELECT * FROM rs_weight_breaks WHERE sheet_id = ? AND user_id = ? ORDER BY id ASC LIMIT ? OFFSET ?", (sheet_id, user_id, limit, offset))
    else:
        cursor.execute("SELECT * FROM rs_weight_breaks WHERE sheet_id = ? AND user_id = ? ORDER BY id ASC", (sheet_id, user_id))
    breaks = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM rs_carrier_minimums WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    minimums = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM rs_carrier_surcharges WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    surcharges = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return {
        "sheet": sheet,
        "zones": zones,
        "breaks": breaks,
        "total_breaks_count": total_breaks_count,
        "minimums": minimums,
        "surcharges": surcharges
    }

def get_sheet_breaks_paginated(
    sheet_id: str,
    user_id: str,
    page: int = 1,
    limit: int = 50,
    query: Optional[str] = None,
    target_cell: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves weight breaks with high-performance server-side pagination, search, and target cell auto-jump."""
    conn = get_connection()
    cursor = conn.cursor()
    
    base_sql = "FROM rs_weight_breaks WHERE sheet_id = ? AND user_id = ?"
    params = [sheet_id, user_id]
    
    if query and query.strip():
        q_wild = f"%{query.strip().upper()}%"
        base_sql += " AND (origin_spec LIKE ? OR dest_spec LIKE ? OR zone_code LIKE ? OR break_name LIKE ? OR source_cell LIKE ?)"
        params.extend([q_wild, q_wild, q_wild, q_wild, q_wild])
        
    cursor.execute(f"SELECT COUNT(*) {base_sql}", params)
    total_count = cursor.fetchone()[0]
    
    # If target_cell is specified without an explicit query, locate the break's page
    if target_cell and target_cell.strip() and not query:
        tc = target_cell.strip().upper()
        # Clean [C:14] into C14 and also check for "14" or "C"
        tc_clean = tc.replace("[", "").replace("]", "").replace(" ", "").replace(":", "")
        cursor.execute(f"SELECT id, source_cell {base_sql} ORDER BY id ASC", params)
        all_breaks = cursor.fetchall()
        for idx, brk in enumerate(all_breaks):
            sc = (brk["source_cell"] or "").strip().upper()
            sc_clean = sc.replace("[", "").replace("]", "").replace(" ", "").replace(":", "").replace("•", "").replace("ROW", "").replace("COL", "")
            if tc_clean in sc_clean or sc_clean in tc_clean or tc in sc:
                page = (idx // limit) + 1
                break

    offset = max(0, (page - 1) * limit)
    cursor.execute(f"SELECT * {base_sql} ORDER BY id ASC LIMIT ? OFFSET ?", params + [limit, offset])
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    total_pages = max(1, (total_count + limit - 1) // limit)
    return {
        "breaks": rows,
        "total_count": total_count,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }

# ==============================================================================
# Immutable Quote Audit Logging Layer (Rule 28, 29, 30)
# ==============================================================================

def log_quote_audit(
    user_id: str,
    quote_id: str,
    shipment_inputs: Dict[str, Any],
    sheets_considered: List[str],
    sheets_excluded: List[Dict[str, Any]],
    calculation_trace: List[Dict[str, Any]],
    final_results: List[Dict[str, Any]]
) -> str:
    """Logs every quote calculation immutably with full trace details."""
    now_ts = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO rs_quote_audit_logs (
        id, user_id, timestamp, shipment_input_json, sheets_considered_json,
        sheets_excluded_json, calculation_trace_json, final_results_json, data_residency_region
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        quote_id,
        user_id,
        now_ts,
        json.dumps(shipment_inputs),
        json.dumps(sheets_considered),
        json.dumps(sheets_excluded),
        json.dumps(calculation_trace),
        json.dumps(final_results),
        DATA_RESIDENCY_REGION
    ))
    conn.commit()
    conn.close()
    return quote_id

def get_quote_audit_log(quote_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves an immutable audit log by Quote ID, strictly checking user_id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM rs_quote_audit_logs WHERE id = ? AND user_id = ?
    """, (quote_id, user_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["quote_id"] = d["id"]
    d["shipment_input"] = json.loads(d["shipment_input_json"])
    d["shipment_inputs"] = d["shipment_input"]
    d["sheets_considered"] = json.loads(d["sheets_considered_json"])
    d["sheets_excluded"] = json.loads(d["sheets_excluded_json"])
    d["calculation_trace"] = json.loads(d["calculation_trace_json"])
    d["final_results"] = json.loads(d["final_results_json"])
    return d

def list_quote_audit_logs(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Lists audit logs for a tenant in descending chronological order."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, user_id, timestamp, final_results_json, data_residency_region
    FROM rs_quote_audit_logs
    WHERE user_id = ?
    ORDER BY timestamp DESC
    LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["final_results"] = json.loads(d["final_results_json"])
        results.append(d)
    return results

if __name__ == "__main__":
    init_ratesift_db()
    print("RateSift Normalized Database initialized successfully.")
