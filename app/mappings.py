"""
Saved mappings fingerprinting, matching, and database storage.
Position-aware, tenant-isolated fingerprinting per Rule 14 and Phase 2C.
"""
from difflib import SequenceMatcher
import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.ingest import normalize_header
from app.jobs import job_store


def compute_fingerprint(
    header_row_values: List[str],
    column_count: int,
    tenant_id: Optional[str] = None,
) -> str:
    """
    Computes an ordered, position-aware fingerprint:
    Hash of ordered ((col_index, normalized_header_text)...) + col_count + tenant_id.
    Swapping columns changes the fingerprint.
    """
    normalized_items: List[str] = []
    for idx, val in enumerate(header_row_values):
        norm = normalize_header(val)
        normalized_items.append(f"{idx}:{norm}")
    key_str = "|".join(normalized_items) + f"|cols:{column_count}|tenant:{tenant_id or 'default'}"
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def save_mapping(
    fingerprint: str,
    user_id: Optional[str],
    tenant_id: Optional[str],
    sheet_name: Optional[str],
    mapping: Dict[str, Any],
    column_count: int,
    header_names: List[str],
) -> str:
    """Saves or updates a confirmed mapping fingerprint in the database."""
    mapping_id = uuid.uuid4().hex
    now = time.time()
    conn = job_store._get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO failsafe_saved_mappings (
        id, fingerprint, user_id, tenant_id, sheet_name, mapping_json,
        column_count, header_names_json, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        mapping_id, fingerprint, user_id, tenant_id, sheet_name,
        json.dumps(mapping), column_count, json.dumps(header_names), now, now
    ))
    conn.commit()
    conn.close()
    return mapping_id


def find_saved_mapping(
    fingerprint: str,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Looks up exact fingerprint match scoped to tenant."""
    conn = job_store._get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM failsafe_saved_mappings
    WHERE fingerprint = ? AND (tenant_id = ? OR (tenant_id IS NULL AND ? IS NULL))
    ORDER BY updated_at DESC LIMIT 1;
    """, (fingerprint, tenant_id, tenant_id))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None

    res = dict(row)
    res["mapping"] = json.loads(res["mapping_json"])
    res["header_names"] = json.loads(res["header_names_json"])
    return res


def find_near_match(
    header_row_values: List[str],
    column_count: int,
    tenant_id: Optional[str] = None,
    threshold: float = 0.85,
) -> Optional[Dict[str, Any]]:
    """
    Finds nearest saved mapping for suggestion banner. Never auto-applies silently.
    """
    conn = job_store._get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM failsafe_saved_mappings
    WHERE tenant_id = ? OR (tenant_id IS NULL AND ? IS NULL)
    ORDER BY updated_at DESC LIMIT 20;
    """, (tenant_id, tenant_id))
    rows = cur.fetchall()
    conn.close()

    curr_str = " ".join(normalize_header(h) for h in header_row_values)
    best_match = None
    best_sim = 0.0

    for r in rows:
        prev_headers = json.loads(r["header_names_json"])
        prev_str = " ".join(normalize_header(h) for h in prev_headers)
        sim = SequenceMatcher(None, curr_str, prev_str).ratio()
        if sim >= threshold and sim > best_sim:
            best_sim = sim
            best_match = dict(r)
            best_match["mapping"] = json.loads(best_match["mapping_json"])
            best_match["similarity"] = round(sim, 2)

    return best_match


def list_saved_mappings(tenant_id: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists saved mappings scoped to tenant/user."""
    conn = job_store._get_connection()
    cur = conn.cursor()
    if tenant_id:
        cur.execute("SELECT * FROM failsafe_saved_mappings WHERE tenant_id = ? ORDER BY updated_at DESC;", (tenant_id,))
    elif user_id:
        cur.execute("SELECT * FROM failsafe_saved_mappings WHERE user_id = ? ORDER BY updated_at DESC;", (user_id,))
    else:
        cur.execute("SELECT * FROM failsafe_saved_mappings ORDER BY updated_at DESC;")
    rows = cur.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        d["mapping"] = json.loads(d["mapping_json"])
        d["header_names"] = json.loads(d["header_names_json"])
        result.append(d)
    return result


def delete_saved_mapping(mapping_id: str, tenant_id: Optional[str] = None) -> bool:
    """Deletes saved mapping with tenant scoping check."""
    conn = job_store._get_connection()
    cur = conn.cursor()
    if tenant_id:
        cur.execute("DELETE FROM failsafe_saved_mappings WHERE id = ? AND tenant_id = ?;", (mapping_id, tenant_id))
    else:
        cur.execute("DELETE FROM failsafe_saved_mappings WHERE id = ?;", (mapping_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ---------------------------------------------------------------- Audit log
def record_audit_log(
    job_id: str,
    user_id: Optional[str],
    tenant_id: Optional[str],
    decision_type: str,
    mapping: Dict[str, Any],
) -> None:
    """
    Records an audit log entry for mapping decisions: 'auto', 'confirmed', 'saved', 'manual'.
    Omit raw rates; records only structural columns and metadata.
    """
    log_id = uuid.uuid4().hex
    now = time.time()
    # Sanitize mapping so no sensitive rate values are recorded
    sanitized_mapping = {
        "header_row": mapping.get("header_row"),
        "mode": mapping.get("mode"),
        "origin_col": mapping.get("origin"),
        "destination_col": mapping.get("destination"),
        "rate_columns": mapping.get("rate_columns"),
        "weight_unit": mapping.get("weight_unit"),
        "sheet_name": mapping.get("sheet_name"),
    }
    conn = job_store._get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO failsafe_audit_logs (
        id, job_id, user_id, tenant_id, decision_type, mapping_summary_json, timestamp
    ) VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (log_id, job_id, user_id, tenant_id, decision_type, json.dumps(sanitized_mapping), now))
    conn.commit()
    conn.close()
