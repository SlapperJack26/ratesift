import sqlite3
import os
import json
import uuid
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

_DEFAULT_DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "quotelytics.db")
DB_FILE = os.environ.get("QUOTELYTICS_DB_PATH") or os.environ.get("FAILSAFE_DB_PATH") or _DEFAULT_DB_FILE
DATA_RESIDENCY_REGION = "CA_CENTRAL_WHC"  # Rule 29: Canadian Hosting (WHC)

_SCHEMA_MIGRATED_DBS = set()


def resolve_db_file() -> str:
    """Resolve active SQLite database path, respecting monkeypatched DB_FILE or env vars."""
    if DB_FILE != _DEFAULT_DB_FILE:
        return DB_FILE
    return os.environ.get("QUOTELYTICS_DB_PATH") or os.environ.get("FAILSAFE_DB_PATH") or DB_FILE


def _ensure_schema_migrated(conn: sqlite3.Connection):
    db_key = os.path.abspath(resolve_db_file())
    if db_key in _SCHEMA_MIGRATED_DBS:
        return
    cursor = conn.cursor()
    # Ensure ql_rate_sheets exists before migrating
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ql_rate_sheets'")
    if not cursor.fetchone():
        return

    cursor.execute("PRAGMA table_info(ql_rate_sheets)")
    rs_info = cursor.fetchall()
    rs_cols = {r["name"]: r for r in rs_info}
    new_rs_cols = [
        ("is_benchmark", "INTEGER DEFAULT 0"),
        ("markup_mode", "TEXT DEFAULT 'PERCENTAGE'"),
        ("markup_value", "REAL DEFAULT 0.0"),
        ("fsc_passthrough", "INTEGER DEFAULT 1"),
        ("accessorial_markup_pct", "REAL DEFAULT 0.0"),
        ("manual_override", "INTEGER DEFAULT 0"),
        ("rating_basis", "TEXT DEFAULT 'WEIGHT_CWT'"),
        ("max_skid_capacity", "INTEGER DEFAULT 10"),
        ("weight_rounding_rule", "TEXT DEFAULT 'CEIL_1LB'"),
        ("allow_deficit_rating", "INTEGER DEFAULT 1"),
        ("fsc_applies_to_accessorials", "INTEGER DEFAULT 0"),
        ("fuel_precedence", "TEXT DEFAULT 'SHEET_FIRST'"),
        ("no_minimum_confirmed", "INTEGER DEFAULT 0"),
        ("failsafe_status", "TEXT DEFAULT 'ready'"),
        ("max_weight_limit", "REAL DEFAULT 44000.0"),
        ("max_piece_weight", "REAL DEFAULT 150.0"),
        ("max_length_in", "REAL DEFAULT 108.0"),
        ("max_girth_in", "REAL DEFAULT 165.0"),
    ]
    for col_name, col_def in new_rs_cols:
        if col_name not in rs_cols:
            cursor.execute(f"ALTER TABLE ql_rate_sheets ADD COLUMN {col_name} {col_def}")

    cursor.execute("PRAGMA table_info(ql_weight_breaks)")
    wb_info = cursor.fetchall()
    wb_cols = {r["name"]: r for r in wb_info}
    for col_name, col_def in [
        ("break_unit", "TEXT DEFAULT 'CWT'"),
        ("min_units", "REAL DEFAULT 0.0"),
        ("max_units", "REAL DEFAULT 999999.0"),
        ("is_open_ended", "INTEGER DEFAULT 0"),
    ]:
        if col_name not in wb_cols:
            cursor.execute(f"ALTER TABLE ql_weight_breaks ADD COLUMN {col_name} {col_def}")

    cursor.execute("PRAGMA table_info(ql_carrier_surcharges)")
    sur_info = cursor.fetchall()
    sur_cols = {r["name"]: r for r in sur_info}
    for col_name, col_def in [
        ("is_included", "INTEGER DEFAULT 0"),
        ("weight_base", "TEXT DEFAULT 'BILLABLE'"),
        ("pct_base", "TEXT DEFAULT 'POST_MIN_FREIGHT'"),
        ("fsc_eligible", "INTEGER DEFAULT 0"),
        ("is_unparsed", "INTEGER DEFAULT 0"),
    ]:
        if col_name not in sur_cols:
            cursor.execute(f"ALTER TABLE ql_carrier_surcharges ADD COLUMN {col_name} {col_def}")

    # Ensure failsafe tables and append-only triggers exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS failsafe_audit_logs (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        decision_type TEXT NOT NULL,
        sheet_sha256 TEXT NOT NULL,
        tab_name TEXT NOT NULL,
        mapping_snapshot_json TEXT NOT NULL,
        warnings_triggered_json TEXT,
        acknowledged_findings_json TEXT,
        timestamp REAL NOT NULL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_failsafe_audit_tenant_job ON failsafe_audit_logs(tenant_id, job_id)")

    cursor.execute("PRAGMA table_info(failsafe_audit_logs)")
    audit_cols = {r["name"]: r for r in cursor.fetchall()}
    for col_name, col_def in [
        ("sheet_sha256", "TEXT DEFAULT ''"),
        ("tab_name", "TEXT DEFAULT ''"),
        ("mapping_snapshot_json", "TEXT DEFAULT '{}'"),
        ("warnings_triggered_json", "TEXT"),
        ("acknowledged_findings_json", "TEXT"),
    ]:
        if col_name not in audit_cols:
            cursor.execute(f"ALTER TABLE failsafe_audit_logs ADD COLUMN {col_name} {col_def}")

    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_failsafe_audit_no_update
    BEFORE UPDATE ON failsafe_audit_logs
    BEGIN
        SELECT RAISE(FAIL, 'failsafe_audit_logs is append-only: UPDATE is prohibited.');
    END
    """)

    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_failsafe_audit_no_delete
    BEFORE DELETE ON failsafe_audit_logs
    BEGIN
        SELECT RAISE(FAIL, 'failsafe_audit_logs is append-only: DELETE is prohibited.');
    END
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS failsafe_override_attributions (
        id TEXT PRIMARY KEY,
        audit_log_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        user_fixed_origin_text TEXT,
        override_notes_json TEXT,
        created_at REAL NOT NULL,
        FOREIGN KEY (audit_log_id) REFERENCES failsafe_audit_logs(id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_override_attr_audit ON failsafe_override_attributions(audit_log_id)")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS failsafe_rejection_counters (
        tenant_id TEXT NOT NULL,
        client_ip TEXT NOT NULL,
        window_start REAL NOT NULL,
        rejection_count INTEGER NOT NULL DEFAULT 1,
        last_blocker_code TEXT,
        PRIMARY KEY (tenant_id, client_ip, window_start)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS failsafe_shadow_logs (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        tab_name TEXT NOT NULL,
        mapping_snapshot_json TEXT NOT NULL,
        findings_json TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_created ON failsafe_shadow_logs(created_at)")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at REAL NOT NULL
    )
    """)

    conn.commit()
    _SCHEMA_MIGRATED_DBS.add(db_key)


def get_connection():
    conn = sqlite3.connect(resolve_db_file(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema_migrated(conn)
    except Exception:
        pass
    return conn


def init_quotelytics_db():
    """
    Initializes the Quotelytics normalized multi-tenant schema.
    Strictly enforces Rules 2, 3, 28, 29, 30.
    """
    conn = sqlite3.connect(resolve_db_file(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # 1. Rate Sheets Table (Rule 2, 5, 7, 16, 17, 28, 29)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_rate_sheets (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        carrier_name TEXT NOT NULL,
        service_name TEXT NOT NULL,
        tariff_ref TEXT,
        mode TEXT NOT NULL DEFAULT 'LTL',
        currency TEXT NOT NULL DEFAULT 'CAD',
        weight_unit TEXT NOT NULL DEFAULT 'lb',
        dim_unit TEXT NOT NULL DEFAULT 'in',
        dim_divisor REAL DEFAULT 139.0,
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_sheets_user ON ql_rate_sheets (user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_sheets_carrier ON ql_rate_sheets (user_id, carrier_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_sheets_status ON ql_rate_sheets (user_id, confirmation_status)")

    # 2. Rate Sheet Cell Coordinates Traceability Table (Rule 3, 6, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_rate_sheet_cells (
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
        FOREIGN KEY (sheet_id) REFERENCES ql_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_cells_sheet ON ql_rate_sheet_cells (sheet_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_cells_user ON ql_rate_sheet_cells (user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_cells_review ON ql_rate_sheet_cells (sheet_id, needs_review)")

    # 3. Carrier Zones Mapping Table (Rule 10, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_carrier_zones (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        origin_spec TEXT NOT NULL,
        dest_spec TEXT NOT NULL,
        zone_code TEXT NOT NULL,
        transit_days INTEGER,
        source_cell TEXT,
        FOREIGN KEY (sheet_id) REFERENCES ql_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_zones_lookup ON ql_carrier_zones (sheet_id, origin_spec, dest_spec)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_zones_user ON ql_carrier_zones (user_id)")

    # 4. Weight Break Rates Matrix Table (Rule 2, 8, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_weight_breaks (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        zone_code TEXT NOT NULL,
        origin_spec TEXT,
        dest_spec TEXT,
        min_weight REAL NOT NULL DEFAULT 0.0,
        max_weight REAL DEFAULT NULL,
        break_name TEXT NOT NULL,
        base_rate REAL NOT NULL,
        rate_type TEXT NOT NULL DEFAULT 'CWT',
        source_cell TEXT,
        is_open_ended INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (sheet_id) REFERENCES ql_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_breaks_lookup ON ql_weight_breaks (sheet_id, zone_code, min_weight, max_weight)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_breaks_od ON ql_weight_breaks (sheet_id, origin_spec, dest_spec)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_breaks_user ON ql_weight_breaks (user_id)")

    # 5. Carrier Minimum Charges Table (Rule 12, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_carrier_minimums (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        zone_code TEXT,
        origin_spec TEXT,
        dest_spec TEXT,
        min_charge REAL NOT NULL,
        source_cell TEXT,
        FOREIGN KEY (sheet_id) REFERENCES ql_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_min_lookup ON ql_carrier_minimums (sheet_id, zone_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_min_user ON ql_carrier_minimums (user_id)")

    # 6. Carrier Surcharges & Accessorials Table (Rule 2, 4, 11, 28)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_carrier_surcharges (
        id TEXT PRIMARY KEY,
        sheet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        surcharge_code TEXT NOT NULL,
        name TEXT NOT NULL,
        condition_type TEXT NOT NULL,
        condition_expression TEXT,
        fee_type TEXT NOT NULL DEFAULT 'FLAT',
        amount REAL DEFAULT 0.0,
        min_fee REAL NOT NULL DEFAULT 0.0,
        max_fee REAL,
        is_waived INTEGER NOT NULL DEFAULT 0,
        source_cell TEXT,
        is_included INTEGER NOT NULL DEFAULT 0,
        weight_base TEXT NOT NULL DEFAULT 'BILLABLE',
        pct_base TEXT NOT NULL DEFAULT 'POST_MIN_FREIGHT',
        fsc_eligible INTEGER NOT NULL DEFAULT 0,
        is_unparsed INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (sheet_id) REFERENCES ql_rate_sheets (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_surcharges_sheet ON ql_carrier_surcharges (sheet_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_surcharges_user ON ql_carrier_surcharges (user_id)")

    # 7. Immutable Quote Audit Logs Table (Rule 28, 29, 30)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ql_quote_audit_logs (
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_audit_user ON ql_quote_audit_logs (user_id, timestamp)")

    _SCHEMA_MIGRATED_DBS.discard(os.path.abspath(resolve_db_file()))
    _ensure_schema_migrated(conn)
    conn.commit()
    conn.close()

# ==============================================================================
# Multi-Tenant Data Access Layer (Strict user_id enforcement - Rule 28)
# ==============================================================================

_UNSET_DIVISOR = object()

def create_rate_sheet(
    user_id: str,
    carrier_name: str,
    service_name: str,
    tariff_ref: Optional[str] = None,
    mode: str = "LTL",
    currency: str = "CAD",
    weight_unit: str = "lb",
    dim_unit: str = "in",
    dim_divisor: Any = _UNSET_DIVISOR,
    dim_min_rule: Optional[str] = None,
    rounding_rule: str = "standard_2dp",
    effective_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    version: int = 1,
    source_filename: str = "",
    confirmation_status: str = "PENDING_REVIEW",
    is_benchmark: int = 0,
    rating_basis: str = "WEIGHT_CWT",
    max_skid_capacity: int = 10,
    weight_rounding_rule: str = "CEIL_1LB",
    allow_deficit_rating: int = 1,
    fsc_applies_to_accessorials: int = 0,
    fuel_precedence: str = "SHEET_FIRST",
    no_minimum_confirmed: int = 0,
    failsafe_status: str = "ready",
    max_weight_limit: float = 44000.0,
    max_piece_weight: float = 150.0,
    max_length_in: float = 108.0,
    max_girth_in: float = 165.0,
) -> str:
    """Creates a new rate sheet record strictly scoped to user_id."""
    sheet_id = f"ql_sheet_{uuid.uuid4().hex[:12]}"
    now_ts = datetime.utcnow().isoformat()
    if dim_divisor is _UNSET_DIVISOR:
        effective_divisor = 139.0 if mode.upper() == "PARCEL" else None
    else:
        effective_divisor = dim_divisor
    # Store 0.0 when dim_divisor is None so legacy NOT NULL constraint on ql_rate_sheets.dim_divisor is satisfied;
    # engine and get_rate_sheet treat dim_divisor <= 0 as None ('no divisor specified').
    db_dim_divisor = float(effective_divisor) if (effective_divisor is not None and float(effective_divisor) > 0) else 0.0
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO ql_rate_sheets (
        id, user_id, carrier_name, service_name, tariff_ref, mode,
        currency, weight_unit, dim_unit, dim_divisor, dim_min_rule,
        rounding_rule, effective_date, expiry_date, version, is_latest,
        confirmation_status, source_filename, storage_region, created_at, is_benchmark,
        rating_basis, max_skid_capacity, weight_rounding_rule, allow_deficit_rating,
        fsc_applies_to_accessorials, fuel_precedence, no_minimum_confirmed, failsafe_status,
        max_weight_limit, max_piece_weight, max_length_in, max_girth_in
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sheet_id, user_id, carrier_name.strip(), service_name.strip(),
        tariff_ref.strip() if tariff_ref else None, mode.upper(),
        currency.upper(), weight_unit.lower(), dim_unit.lower(),
        db_dim_divisor, dim_min_rule, rounding_rule,
        effective_date, expiry_date, int(version),
        confirmation_status, source_filename, DATA_RESIDENCY_REGION, now_ts, int(is_benchmark),
        rating_basis.upper(), int(max_skid_capacity), weight_rounding_rule.upper(), int(allow_deficit_rating),
        int(fsc_applies_to_accessorials), fuel_precedence.upper(), int(no_minimum_confirmed), failsafe_status,
        float(max_weight_limit), float(max_piece_weight), float(max_length_in), float(max_girth_in)
    ))
    conn.commit()
    conn.close()
    return sheet_id

def get_rate_sheet(sheet_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a rate sheet by ID, strictly verifying ownership and excluding sample/benchmark sheets (Rule 28)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM ql_rate_sheets 
    WHERE id = ? AND user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL)
    """, (sheet_id, user_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("dim_divisor") is not None and float(d["dim_divisor"]) <= 0:
        d["dim_divisor"] = None
    return d

def list_rate_sheets(user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists all rate sheets uploaded by user_id, strictly excluding benchmark/sample sheets (Rule 28)."""
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
        SELECT * FROM ql_rate_sheets 
        WHERE user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL) AND confirmation_status = ? 
        ORDER BY created_at DESC
        """, (user_id, status.upper()))
    else:
        cursor.execute("""
        SELECT * FROM ql_rate_sheets 
        WHERE user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL) 
        ORDER BY created_at DESC
        """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("dim_divisor") is not None and float(d["dim_divisor"]) <= 0:
            d["dim_divisor"] = None
        results.append(d)
    return results

def confirm_no_minimum_column(sheet_id: str, user_id: str, confirmed_by: str = "User") -> bool:
    """Explicitly confirms that a rate sheet has no minimum charge column ($0.00 minimum) and resolves MISSING_MINIMUM_COLUMN flags."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE ql_rate_sheets
    SET no_minimum_confirmed = 1,
        failsafe_status = CASE WHEN failsafe_status = 'missing_minimum_column' THEN 'ready' ELSE failsafe_status END
    WHERE id = ? AND user_id = ?
    """, (sheet_id, user_id))
    updated = cursor.rowcount > 0
    if updated:
        cursor.execute("""
        UPDATE ql_rate_sheet_cells
        SET needs_review = 0, review_notes = ?
        WHERE sheet_id = ? AND user_id = ? AND field_name = 'MISSING_MINIMUM_COLUMN'
        """, (f"No minimum charge ($0.00) explicitly confirmed by {confirmed_by}", sheet_id, user_id))
    conn.commit()
    conn.close()
    if updated:
        insert_carrier_minimums(sheet_id, user_id, [{
            "zone_code": "CONFIRMED_NO_MIN",
            "origin_spec": "",
            "dest_spec": "",
            "min_charge": 0.0,
            "source_cell": f"Confirmed $0.00 Minimum ({confirmed_by})"
        }])
    return updated

def set_sheet_manual_override(sheet_id: str, user_id: str, manual_override: bool = True) -> bool:
    """Sets or clears the manual_override flag on a rate sheet without changing failsafe_status."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE ql_rate_sheets
    SET manual_override = ?
    WHERE id = ? AND user_id = ?
    """, (1 if manual_override else 0, sheet_id, user_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

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
    resolve_flags: bool = False,
    no_minimum_confirmed: Optional[bool] = None,
    weight_rounding_rule: Optional[str] = None,
    allow_deficit_rating: Optional[bool] = None,
    failsafe_status: Optional[str] = None,
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
    if no_minimum_confirmed is not None:
        updates.append("no_minimum_confirmed = ?")
        params.append(1 if no_minimum_confirmed else 0)
    if weight_rounding_rule:
        updates.append("weight_rounding_rule = ?")
        params.append(weight_rounding_rule.strip().upper())
    if allow_deficit_rating is not None:
        updates.append("allow_deficit_rating = ?")
        params.append(1 if allow_deficit_rating else 0)
    if failsafe_status is not None:
        updates.append("failsafe_status = ?")
        params.append(failsafe_status.strip())

    params.extend([sheet_id, user_id])
    sql = f"UPDATE ql_rate_sheets SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
    cursor.execute(sql, params)
    affected = cursor.rowcount > 0
    
    # Resolve review flags if requested
    if resolve_flags and affected:
        cursor.execute("UPDATE ql_rate_sheet_cells SET needs_review = 0 WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))

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
    sql = f"UPDATE ql_rate_sheets SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
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
    UPDATE ql_carrier_surcharges
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
    UPDATE ql_rate_sheet_cells
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
    UPDATE ql_rate_sheets
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
    cursor.execute("DELETE FROM ql_rate_sheets WHERE id = ? AND user_id = ?", (sheet_id, user_id))
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
            f"ql_cell_{uuid.uuid4().hex[:12]}",
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
    INSERT INTO ql_rate_sheet_cells (
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
        SELECT * FROM ql_rate_sheet_cells WHERE sheet_id = ? AND user_id = ? AND needs_review = 1
        """, (sheet_id, user_id))
    else:
        cursor.execute("""
        SELECT * FROM ql_rate_sheet_cells WHERE sheet_id = ? AND user_id = ?
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
            f"ql_zn_{uuid.uuid4().hex[:12]}",
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
    INSERT INTO ql_carrier_zones (
        id, sheet_id, user_id, origin_spec, dest_spec, zone_code, transit_days, source_cell
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()

def insert_weight_breaks(sheet_id: str, user_id: str, breaks: List[Dict[str, Any]]):
    """Inserts normalized matrix rate breaks with explicit is_open_ended tracking."""
    if not breaks:
        return
    conn = get_connection()
    cursor = conn.cursor()
    records = []
    for b in breaks:
        raw_max = b.get("max_weight")
        if "is_open_ended" in b and b["is_open_ended"] is not None:
            is_open = 1 if b["is_open_ended"] else 0
        else:
            is_open = 1 if (raw_max is None or float(raw_max) >= 999999.0) else 0
        db_max = 999999.0 if raw_max is None else float(raw_max)
        records.append((
            f"ql_wb_{uuid.uuid4().hex[:12]}",
            sheet_id,
            user_id,
            b.get("zone_code", "DEFAULT").strip().upper(),
            b.get("origin_spec", "").strip().upper() if b.get("origin_spec") else None,
            b.get("dest_spec", "").strip().upper() if b.get("dest_spec") else None,
            float(b.get("min_weight", 0.0)),
            db_max,
            (b.get("break_name") or "DEFAULT").strip(),
            float(b["base_rate"]),
            b.get("rate_type", "CWT").upper(),
            b.get("source_cell", ""),
            b.get("break_unit", "CWT").upper(),
            float(b.get("min_units", 0.0)),
            float(b.get("max_units", 999999.0)),
            is_open,
        ))
    cursor.executemany("""
    INSERT INTO ql_weight_breaks (
        id, sheet_id, user_id, zone_code, origin_spec, dest_spec,
        min_weight, max_weight, break_name, base_rate, rate_type, source_cell,
        break_unit, min_units, max_units, is_open_ended
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            f"ql_min_{uuid.uuid4().hex[:12]}",
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
    INSERT INTO ql_carrier_minimums (
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
    records = []
    for s in surcharges:
        raw_amt = s.get("amount")
        is_unparsed = 1 if (raw_amt is None or s.get("is_unparsed")) else 0
        db_amt = 0.0 if raw_amt is None else float(raw_amt)
        records.append((
            f"ql_sur_{uuid.uuid4().hex[:12]}",
            sheet_id,
            user_id,
            s["surcharge_code"].strip().upper(),
            s["name"].strip(),
            s["condition_type"].strip().lower(),
            json.dumps(s.get("condition_expression", {})) if isinstance(s.get("condition_expression"), (dict, list)) else s.get("condition_expression"),
            s.get("fee_type", "FLAT").upper(),
            db_amt,
            float(s.get("min_fee", 0.0)),
            float(s["max_fee"]) if s.get("max_fee") is not None else None,
            1 if s.get("is_waived") else 0,
            s.get("source_cell", ""),
            1 if s.get("is_included") else 0,
            (s.get("weight_base") or "BILLABLE").upper(),
            (s.get("pct_base") or "POST_MIN_FREIGHT").upper(),
            1 if s.get("fsc_eligible") else 0,
            is_unparsed,
        ))
    cursor.executemany("""
    INSERT INTO ql_carrier_surcharges (
        id, sheet_id, user_id, surcharge_code, name, condition_type,
        condition_expression, fee_type, amount, min_fee, max_fee, is_waived, source_cell,
        is_included, weight_base, pct_base, fsc_eligible, is_unparsed
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    
    cursor.execute("SELECT * FROM ql_carrier_zones WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    zones = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT COUNT(*) FROM ql_weight_breaks WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    total_breaks_count = cursor.fetchone()[0]
    
    if limit is not None:
        cursor.execute("SELECT * FROM ql_weight_breaks WHERE sheet_id = ? AND user_id = ? ORDER BY id ASC LIMIT ? OFFSET ?", (sheet_id, user_id, limit, offset))
    else:
        cursor.execute("SELECT * FROM ql_weight_breaks WHERE sheet_id = ? AND user_id = ? ORDER BY id ASC", (sheet_id, user_id))
    breaks = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM ql_carrier_minimums WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    minimums = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM ql_carrier_surcharges WHERE sheet_id = ? AND user_id = ?", (sheet_id, user_id))
    surcharges = []
    for r in cursor.fetchall():
        d = dict(r)
        if d.get("is_unparsed"):
            d["amount"] = None
        surcharges.append(d)
    
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
    
    base_sql = "FROM ql_weight_breaks WHERE sheet_id = ? AND user_id = ?"
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
    INSERT INTO ql_quote_audit_logs (
        id, user_id, timestamp, shipment_input_json, sheets_considered_json,
        sheets_excluded_json, calculation_trace_json, final_results_json, data_residency_region
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        shipment_input_json=excluded.shipment_input_json,
        sheets_considered_json=excluded.sheets_considered_json,
        sheets_excluded_json=excluded.sheets_excluded_json,
        calculation_trace_json=excluded.calculation_trace_json,
        final_results_json=excluded.final_results_json,
        timestamp=excluded.timestamp
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

def reserve_user_quote_slot(
    user_id: str,
    shipment_inputs: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Atomically checks quota ceiling and reserves a quote slot inside an immediate transaction,
    preventing Time-of-Check to Time-of-Use (TOCTOU) race conditions under high concurrency.
    Returns (allowed, quote_id, quota_info).
    """
    conn = get_connection()
    conn.isolation_level = None  # Autocommit mode for explicit transaction control
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")

        # 1. Fetch user & subscription tier limits
        cursor.execute("""
        SELECT u.id, u.name, u.email, u.company, u.tier, t.name as tier_name,
               t.max_sheets, t.max_quotes_per_month, t.has_api_access, t.max_seats
        FROM users u
        JOIN subscription_tiers t ON u.tier = t.id
        WHERE u.id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("ROLLBACK")
            return False, None, None

        user_info = dict(row)
        max_quotes = user_info["max_quotes_per_month"]

        # 2. Count quotes created this calendar month
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        cursor.execute("""
        SELECT count(id) as count 
        FROM ql_quote_audit_logs 
        WHERE user_id = ? AND timestamp >= ?
        """, (user_id, month_start))
        rs_quote_count = cursor.fetchone()["count"]

        cursor.execute("""
        SELECT count(qi.id) as count
        FROM quote_items qi
        JOIN quote_batches qb ON qi.batch_id = qb.id
        WHERE qb.user_id = ? AND qi.created_at >= ?
        """, (user_id, month_start))
        batch_quote_count = cursor.fetchone()["count"]

        monthly_quotes_used = rs_quote_count + batch_quote_count

        can_quote = (monthly_quotes_used < max_quotes) if max_quotes > 0 else True
        if not can_quote:
            cursor.execute("ROLLBACK")
            quota_info = {
                "user_id": user_id,
                "tier": user_info["tier"],
                "tier_name": user_info["tier_name"],
                "max_quotes_per_month": max_quotes,
                "monthly_quotes_used": monthly_quotes_used,
                "can_quote": False,
            }
            return False, None, quota_info

        # 3. Atomically reserve quote slot by generating ID and inserting reserved audit record
        quote_id = f"QL-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        now_ts = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT INTO ql_quote_audit_logs (
            id, user_id, timestamp, shipment_input_json, sheets_considered_json,
            sheets_excluded_json, calculation_trace_json, final_results_json, data_residency_region
        ) VALUES (?, ?, ?, ?, '[]', '[]', '[]', '[]', ?)
        """, (
            quote_id,
            user_id,
            now_ts,
            json.dumps(shipment_inputs or {}),
            DATA_RESIDENCY_REGION
        ))
        cursor.execute("COMMIT")
        quota_info = {
            "user_id": user_id,
            "tier": user_info["tier"],
            "tier_name": user_info["tier_name"],
            "max_quotes_per_month": max_quotes,
            "monthly_quotes_used": monthly_quotes_used + 1,
            "can_quote": True,
        }
        return True, quote_id, quota_info
    except Exception:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

def release_quote_reservation(quote_id: str, user_id: str) -> None:
    """Releases an in-flight reserved quote slot if calculation failed before completion."""
    if not quote_id:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ql_quote_audit_logs WHERE id = ? AND user_id = ?", (quote_id, user_id))
        conn.commit()
    finally:
        conn.close()

def get_quote_audit_log(quote_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves an immutable audit log by Quote ID, strictly checking user_id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM ql_quote_audit_logs WHERE id = ? AND user_id = ?
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
    FROM ql_quote_audit_logs
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

# ==============================================================================
# Failsafe Audit Logs & Settings Layer (Release 1a)
# ==============================================================================

def get_system_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default


def set_system_setting(key: str, value: str) -> None:
    now_ts = time.time()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO system_settings (key, value, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
    """, (key, str(value), now_ts))
    conn.commit()
    conn.close()


def get_or_initialize_sunset_timestamps(clock_fn=None) -> Tuple[float, float]:
    """
    Retrieves the persisted deploy_timestamp and sunset_timestamp from system_settings.
    If not present, initializes once as (now, now + 90 days) and persists them.
    Ensures that server restarts NEVER shift the sunset window.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT key, value FROM system_settings WHERE key IN ('failsafe_deploy_timestamp', 'failsafe_sunset_timestamp')")
    rows = dict(c.fetchall())
    conn.close()

    if "failsafe_deploy_timestamp" in rows and "failsafe_sunset_timestamp" in rows:
        return float(rows["failsafe_deploy_timestamp"]), float(rows["failsafe_sunset_timestamp"])

    now_ts = clock_fn() if clock_fn else time.time()
    deploy_ts = float(now_ts)
    sunset_ts = float(deploy_ts + (90 * 86400))  # 90 days

    set_system_setting("failsafe_deploy_timestamp", str(deploy_ts))
    set_system_setting("failsafe_sunset_timestamp", str(sunset_ts))
    return deploy_ts, sunset_ts


def insert_failsafe_audit_log(
    job_id: str,
    tenant_id: str,
    decision_type: str,
    sheet_sha256: str,
    tab_name: str,
    mapping_snapshot_json: str,
    warnings_triggered_json: Optional[str] = None,
    acknowledged_findings_json: Optional[str] = None,
    log_id: Optional[str] = None,
) -> str:
    lid = log_id or str(uuid.uuid4())
    now_ts = time.time()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(failsafe_audit_logs)")
    cols = {r["name"] for r in cursor.fetchall()}
    if "mapping_summary_json" in cols:
        cursor.execute("""
        INSERT INTO failsafe_audit_logs (
            id, job_id, tenant_id, decision_type, sheet_sha256,
            tab_name, mapping_snapshot_json, mapping_summary_json, warnings_triggered_json,
            acknowledged_findings_json, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lid, job_id, tenant_id, decision_type, sheet_sha256,
            tab_name, mapping_snapshot_json, mapping_snapshot_json, warnings_triggered_json,
            acknowledged_findings_json, now_ts
        ))
    else:
        cursor.execute("""
        INSERT INTO failsafe_audit_logs (
            id, job_id, tenant_id, decision_type, sheet_sha256,
            tab_name, mapping_snapshot_json, warnings_triggered_json,
            acknowledged_findings_json, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lid, job_id, tenant_id, decision_type, sheet_sha256,
            tab_name, mapping_snapshot_json, warnings_triggered_json,
            acknowledged_findings_json, now_ts
        ))
    conn.commit()
    conn.close()
    return lid


def insert_failsafe_override_attribution(
    audit_log_id: str,
    tenant_id: str,
    user_id: str,
    user_email: str,
    user_fixed_origin_text: Optional[str] = None,
    override_notes_json: Optional[str] = None,
) -> str:
    attr_id = str(uuid.uuid4())
    now_ts = time.time()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO failsafe_override_attributions (
        id, audit_log_id, tenant_id, user_id, user_email,
        user_fixed_origin_text, override_notes_json, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        attr_id, audit_log_id, tenant_id, user_id, user_email,
        user_fixed_origin_text, override_notes_json, now_ts
    ))
    conn.commit()
    conn.close()
    return attr_id


def increment_failsafe_rejection(
    tenant_id: str,
    client_ip: str,
    blocker_code: str,
    window_seconds: int = 3600,
) -> None:
    now_ts = time.time()
    window_start = float(int(now_ts / window_seconds) * window_seconds)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO failsafe_rejection_counters (
        tenant_id, client_ip, window_start, rejection_count, last_blocker_code
    ) VALUES (?, ?, ?, 1, ?)
    ON CONFLICT(tenant_id, client_ip, window_start) DO UPDATE SET
        rejection_count = rejection_count + 1,
        last_blocker_code = excluded.last_blocker_code
    """, (tenant_id, client_ip, window_start, blocker_code))
    conn.commit()
    conn.close()


def prune_failsafe_rejection_counters(older_than_seconds: int = 604800) -> int:
    cutoff = time.time() - older_than_seconds
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM failsafe_rejection_counters WHERE window_start < ?", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted


def insert_failsafe_shadow_log(
    job_id: str,
    tenant_id: str,
    tab_name: str,
    mapping_snapshot_json: str,
    findings_json: str,
) -> str:
    shadow_id = str(uuid.uuid4())
    now_ts = time.time()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO failsafe_shadow_logs (
        id, job_id, tenant_id, tab_name, mapping_snapshot_json, findings_json, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (shadow_id, job_id, tenant_id, tab_name, mapping_snapshot_json, findings_json, now_ts))
    conn.commit()
    conn.close()
    return shadow_id


def delete_tenant_failsafe_attributions(tenant_id: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM failsafe_override_attributions WHERE tenant_id = ?", (tenant_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_expiring_or_expired_sheets(user_id: str, within_days: int = 14) -> List[Dict[str, Any]]:
    """
    Returns carrier rate sheets owned by `user_id` that are already expired or expiring
    within `within_days` calendar days, preventing silent margin bleed from outdated tariffs.
    """
    from datetime import timedelta

    sheets = list_rate_sheets(user_id=user_id)
    today = datetime.utcnow().date()
    horizon = today + timedelta(days=int(within_days))
    alerts: List[Dict[str, Any]] = []

    for s in sheets:
        exp_raw = (s.get("expiry_date") or "").strip()
        if not exp_raw:
            continue
        try:
            exp_date = datetime.strptime(exp_raw[:10], "%Y-%m-%d").date()
        except Exception:
            continue

        days_left = (exp_date - today).days
        if days_left <= within_days:
            alerts.append({
                "sheet_id": s["id"],
                "carrier_name": s.get("carrier_name"),
                "service_name": s.get("service_name"),
                "expiry_date": exp_raw[:10],
                "days_remaining": days_left,
                "expiry_status": "EXPIRED" if days_left < 0 else "EXPIRING_SOON",
                "confirmation_status": s.get("confirmation_status"),
            })

    alerts.sort(key=lambda x: x["days_remaining"])
    return alerts


def apply_gri_percentage_to_sheet(
    sheet_id: str,
    user_id: str,
    gri_percent: float,
    new_effective_date: Optional[str] = None,
    new_expiry_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    1-Click General Rate Increase (GRI) Bumper:
    Applies a uniform percentage adjustment (e.g. +5.5%) across all CWT/Skid weight breaks
    and minimum charges on a carrier rate sheet using exact Decimal rounding, and bumps version.
    """
    from decimal import Decimal, ROUND_HALF_UP

    sheet = get_rate_sheet(sheet_id, user_id)
    if not sheet:
        raise ValueError(f"Rate sheet '{sheet_id}' not found or unauthorized.")

    pct_dec = Decimal(str(float(gri_percent)))
    mult_dec = Decimal("1") + (pct_dec / Decimal("100"))
    if mult_dec <= Decimal("0"):
        raise ValueError("GRI percentage must leave rates positive.")

    conn = get_connection()
    cursor = conn.cursor()

    # 1. Update all weight breaks
    cursor.execute(
        "SELECT id, base_rate FROM ql_weight_breaks WHERE sheet_id = ? AND user_id = ?",
        (sheet_id, user_id),
    )
    breaks = cursor.fetchall()
    for b in breaks:
        old_r = Decimal(str(b["base_rate"] or 0.0))
        new_r = float((old_r * mult_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        cursor.execute(
            "UPDATE ql_weight_breaks SET base_rate = ? WHERE id = ? AND user_id = ?",
            (new_r, b["id"], user_id),
        )

    # 2. Update all carrier minimum charges
    cursor.execute(
        "SELECT id, min_charge FROM ql_carrier_minimums WHERE sheet_id = ? AND user_id = ?",
        (sheet_id, user_id),
    )
    mins = cursor.fetchall()
    for m in mins:
        old_m = Decimal(str(m["min_charge"] or 0.0))
        new_m = float((old_m * mult_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        cursor.execute(
            "UPDATE ql_carrier_minimums SET min_charge = ? WHERE id = ? AND user_id = ?",
            (new_m, m["id"], user_id),
        )

    # 3. Bump sheet version and optional dates
    new_ver = int(sheet.get("version") or 1) + 1
    eff_dt = new_effective_date or sheet.get("effective_date")
    exp_dt = new_expiry_date or sheet.get("expiry_date")
    cursor.execute(
        """
        UPDATE ql_rate_sheets
        SET version = ?, effective_date = ?, expiry_date = ?
        WHERE id = ? AND user_id = ?
        """,
        (new_ver, eff_dt, exp_dt, sheet_id, user_id),
    )

    conn.commit()
    conn.close()
    return {
        "sheet_id": sheet_id,
        "carrier_name": sheet.get("carrier_name"),
        "gri_percent_applied": float(gri_percent),
        "updated_breaks_count": len(breaks),
        "updated_minimums_count": len(mins),
        "new_version": new_ver,
        "effective_date": eff_dt,
        "expiry_date": exp_dt,
    }


SAMPLE_SANDBOX_TARIFF_REF = "SAMPLE-SANDBOX-2026"


def seed_sample_canadian_ltl_tariffs(user_id: str) -> Dict[str, Any]:
    """
    1-Click Sandbox Mode: Seeds 3 realistic, immediately CONFIRMED Canadian LTL sample tariffs
    ('[SAMPLE] Manitoulin Transport', '[SAMPLE] Day & Ross Freight', '[SAMPLE] Overland West Freight Lines')
    with tariff_ref = 'SAMPLE-SANDBOX-2026' across major Canadian corridors so new brokers can test
    the entire console workflow within 3 seconds without consuming uploaded-sheet quotas.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, carrier_name, service_name
        FROM ql_rate_sheets
        WHERE user_id = ? AND tariff_ref = ?
        ORDER BY created_at ASC
        """,
        (str(user_id), SAMPLE_SANDBOX_TARIFF_REF),
    )
    existing = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if existing:
        return {
            "seeded_count": len(existing),
            "sheet_ids": [r["id"] for r in existing],
            "carriers": [r["carrier_name"] for r in existing],
            "tariff_ref": SAMPLE_SANDBOX_TARIFF_REF,
            "already_seeded": True,
        }

    carrier_specs = [
        {
            "carrier_name": "[SAMPLE] Manitoulin Transport",
            "service_name": "Standard Road LTL",
            "filename": "SAMPLE_SANDBOX_Manitoulin_LTL_2026.xlsx",
            "cell_prefix": "Sample_Manitoulin!",
            "fsc_pct": 31.5,
            "tailgate": 75.0,
            "residential": 85.0,
            "appointment": 35.0,
            "heated_pct": 15.0,
            "lanes": [
                ("TORONTO, ON", "CALGARY, AB", "ON-AB", 4, 145.0, [42.50, 36.80, 31.20, 26.40, 21.90], "D14"),
                ("TORONTO, ON", "MONTREAL, QC", "ON-QC", 1, 98.0, [21.50, 18.40, 15.20, 12.80, 10.50], "D18"),
                ("TORONTO, ON", "VANCOUVER, BC", "ON-BC", 5, 165.0, [48.90, 42.10, 35.80, 29.50, 24.80], "D22"),
                ("TORONTO, ON", "WINNIPEG, MB", "ON-MB", 3, 128.0, [32.40, 27.90, 23.10, 19.40, 16.20], "D26"),
                ("CALGARY, AB", "LINDSAY, ON", "AB-ON", 4, 148.0, [41.20, 35.50, 30.10, 25.60, 21.10], "D30"),
            ],
        },
        {
            "carrier_name": "[SAMPLE] Day & Ross Freight",
            "service_name": "Domestic LTL CWT",
            "filename": "SAMPLE_SANDBOX_DayAndRoss_LTL_2026.xlsx",
            "cell_prefix": "Sample_DayRoss!",
            "fsc_pct": 32.0,
            "tailgate": 80.0,
            "residential": 90.0,
            "appointment": 40.0,
            "heated_pct": 16.0,
            "lanes": [
                ("TORONTO, ON", "CALGARY, AB", "ON-AB", 4, 140.0, [40.90, 35.20, 29.90, 25.10, 20.80], "E12"),
                ("TORONTO, ON", "MONTREAL, QC", "ON-QC", 1, 95.0, [20.80, 17.90, 14.80, 12.30, 10.10], "E16"),
                ("TORONTO, ON", "VANCOUVER, BC", "ON-BC", 5, 160.0, [47.20, 40.80, 34.60, 28.90, 24.10], "E20"),
                ("TORONTO, ON", "WINNIPEG, MB", "ON-MB", 3, 125.0, [31.50, 27.10, 22.60, 18.90, 15.80], "E24"),
                ("CALGARY, AB", "LINDSAY, ON", "AB-ON", 4, 142.0, [39.90, 34.40, 29.20, 24.70, 20.40], "E28"),
            ],
        },
        {
            "carrier_name": "[SAMPLE] Overland West Freight Lines",
            "service_name": "Western Express LTL",
            "filename": "SAMPLE_SANDBOX_OverlandWest_LTL_2026.xlsx",
            "cell_prefix": "Sample_OverlandWest!",
            "fsc_pct": 30.5,
            "tailgate": 70.0,
            "residential": 80.0,
            "appointment": 30.0,
            "heated_pct": 14.0,
            "lanes": [
                ("TORONTO, ON", "CALGARY, AB", "ON-AB", 3, 150.0, [43.80, 38.10, 32.50, 27.20, 22.70], "C9"),
                ("TORONTO, ON", "MONTREAL, QC", "ON-QC", 2, 102.0, [22.40, 19.20, 16.00, 13.50, 11.20], "C13"),
                ("TORONTO, ON", "VANCOUVER, BC", "ON-BC", 4, 158.0, [46.50, 39.90, 33.90, 28.40, 23.60], "C17"),
                ("TORONTO, ON", "WINNIPEG, MB", "ON-MB", 3, 130.0, [33.10, 28.50, 23.80, 19.90, 16.70], "C21"),
                ("CALGARY, AB", "LINDSAY, ON", "AB-ON", 3, 149.0, [42.60, 37.00, 31.40, 26.50, 22.00], "C25"),
            ],
        },
    ]

    weight_tiers = [
        (0.0, 500.0, "L5C", False),
        (500.0, 1000.0, "5C", False),
        (1000.0, 2000.0, "1M", False),
        (2000.0, 5000.0, "2M", False),
        (5000.0, None, "5M", True),
    ]

    seeded_ids: List[str] = []
    seeded_carriers: List[str] = []

    for spec in carrier_specs:
        sid = create_rate_sheet(
            user_id=str(user_id),
            carrier_name=spec["carrier_name"],
            service_name=spec["service_name"],
            tariff_ref=SAMPLE_SANDBOX_TARIFF_REF,
            mode="LTL",
            currency="CAD",
            weight_unit="lb",
            dim_unit="in",
            dim_divisor=139.0,
            dim_min_rule="10 lbs/cu.ft",
            effective_date="2026-01-01",
            expiry_date="2027-12-31",
            source_filename=spec["filename"],
            confirmation_status="CONFIRMED",
            is_benchmark=0,
            rating_basis="WEIGHT_CWT",
            max_skid_capacity=12,
            weight_rounding_rule="CEIL_1LB",
            allow_deficit_rating=1,
            failsafe_status="ready",
        )
        confirm_rate_sheet(
            sheet_id=sid,
            user_id=str(user_id),
            confirmed_by="Sandbox Sample Seeder",
            currency="CAD",
            weight_unit="lb",
            dim_divisor=139.0,
            effective_date="2026-01-01",
            expiry_date="2027-12-31",
            markup_mode="PERCENTAGE",
            markup_value=15.0,
            fsc_passthrough=True,
            resolve_flags=True,
            allow_deficit_rating=True,
            failsafe_status="ready",
        )

        zones_payload = []
        breaks_payload = []
        minimums_payload = []

        for orig, dest, zcode, tdays, min_chg, rates, base_cell in spec["lanes"]:
            cell_ref = f"{spec['cell_prefix']}{base_cell}"
            zones_payload.append({
                "origin_spec": orig,
                "dest_spec": dest,
                "zone_code": zcode,
                "transit_days": tdays,
                "source_cell": cell_ref,
            })
            minimums_payload.append({
                "zone_code": zcode,
                "origin_spec": orig,
                "dest_spec": dest,
                "min_charge": min_chg,
                "source_cell": cell_ref,
            })
            for idx, (wmin, wmax, bname, is_open) in enumerate(weight_tiers):
                breaks_payload.append({
                    "zone_code": zcode,
                    "origin_spec": orig,
                    "dest_spec": dest,
                    "min_weight": wmin,
                    "max_weight": wmax,
                    "break_name": bname,
                    "base_rate": rates[idx],
                    "rate_type": "CWT",
                    "source_cell": cell_ref,
                    "is_open_ended": is_open,
                })

        insert_carrier_zones(sid, str(user_id), zones_payload)
        insert_carrier_minimums(sid, str(user_id), minimums_payload)
        insert_weight_breaks(sid, str(user_id), breaks_payload)
        insert_carrier_surcharges(sid, str(user_id), [
            {
                "surcharge_code": "FSC",
                "name": "Canadian LTL Fuel Surcharge",
                "condition_type": "always",
                "fee_type": "PERCENTAGE",
                "amount": spec["fsc_pct"],
                "source_cell": f"{spec['cell_prefix']}FSC",
            },
            {
                "surcharge_code": "LIFTGATE",
                "name": "Power Tailgate / Liftgate",
                "condition_type": "accessorial",
                "fee_type": "FLAT",
                "amount": spec["tailgate"],
                "source_cell": f"{spec['cell_prefix']}ACC_TG",
            },
            {
                "surcharge_code": "TAILGATE",
                "name": "Power Tailgate Service",
                "condition_type": "accessorial",
                "fee_type": "FLAT",
                "amount": spec["tailgate"],
                "source_cell": f"{spec['cell_prefix']}ACC_TG2",
            },
            {
                "surcharge_code": "RESIDENTIAL",
                "name": "Residential Delivery",
                "condition_type": "accessorial",
                "fee_type": "FLAT",
                "amount": spec["residential"],
                "source_cell": f"{spec['cell_prefix']}ACC_RES",
            },
            {
                "surcharge_code": "APPOINTMENT",
                "name": "Delivery Appointment",
                "condition_type": "accessorial",
                "fee_type": "FLAT",
                "amount": spec["appointment"],
                "source_cell": f"{spec['cell_prefix']}ACC_APPT",
            },
            {
                "surcharge_code": "HEATED",
                "name": "Protect From Freeze / Heated",
                "condition_type": "accessorial",
                "fee_type": "PERCENTAGE",
                "amount": spec["heated_pct"],
                "min_fee": 35.0,
                "source_cell": f"{spec['cell_prefix']}ACC_HEAT",
            },
        ])

        seeded_ids.append(sid)
        seeded_carriers.append(spec["carrier_name"])

    return {
        "seeded_count": len(seeded_ids),
        "sheet_ids": seeded_ids,
        "carriers": seeded_carriers,
        "tariff_ref": SAMPLE_SANDBOX_TARIFF_REF,
        "already_seeded": False,
    }


def purge_sample_canadian_ltl_tariffs(user_id: str) -> Dict[str, Any]:
    """Deletes all '[SAMPLE]' Sandbox Canadian LTL tariffs owned by `user_id`."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute(
        "DELETE FROM ql_rate_sheets WHERE user_id = ? AND tariff_ref = ?",
        (str(user_id), SAMPLE_SANDBOX_TARIFF_REF),
    )
    purged_count = cursor.rowcount
    conn.commit()
    conn.close()
    return {
        "purged_count": int(purged_count),
        "tariff_ref": SAMPLE_SANDBOX_TARIFF_REF,
    }


if __name__ == "__main__":
    init_quotelytics_db()
    print("Quotelytics Normalized Database initialized successfully.")
