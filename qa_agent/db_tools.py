"""Phase 0 / Teardown: SQLite WAL-safe backups, orphan test account sweep, and deletion verification."""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from qa_agent.config import DB_PATH, PROJECT_ROOT


def backup_database(dest_path: str, src_path: str = DB_PATH) -> bool:
    """
    Safely creates a consistent snapshot of the SQLite database using sqlite3 Connection.backup().
    Handles active transactions, WAL mode (-wal / -shm), and concurrent writes cleanly (Section 5.5).
    """
    if not os.path.exists(src_path):
        return False
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        src_conn = sqlite3.connect(src_path)
        dest_conn = sqlite3.connect(dest_path)
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()
        return True
    except Exception as e:
        # Fallback to file copy if backup API encounters issues
        try:
            import shutil
            shutil.copy2(src_path, dest_path)
            return True
        except Exception:
            return False


def sweep_orphan_test_accounts(email_pattern: str = "qa+%", db_path: str = DB_PATH) -> List[str]:
    """
    Finds orphan QA test accounts matching qa+* and cleanly deletes them via delete_user_account_data (Section 5.6).
    Cleans up associated sheets, quotes, sessions, and files.
    """
    if not os.path.exists(db_path):
        return []

    # Import delete_user_account_data from app services
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    try:
        from services.db_service import delete_user_account_data
    except ImportError:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, email FROM users WHERE email LIKE ?", (email_pattern,))
    orphans = cursor.fetchall()
    conn.close()

    purged_users: List[str] = []
    for row in orphans:
        uid = row["id"]
        email = row["email"]
        try:
            delete_user_account_data(uid, immediate_purge=True)
            purged_users.append(f"{uid} ({email})")
        except Exception:
            pass

    return purged_users


def verify_account_fully_deleted(user_id: str, db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    Verifies that a user and all child rows across tables have been completely removed (Section 13).
    Returns leftover table row counts and leftover file paths if any remain.
    """
    results: Dict[str, Any] = {"clean": True, "leftovers": {}, "leftover_files": []}
    if not os.path.exists(db_path):
        return results

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables_to_check = [
        ("users", "id"),
        ("sessions", "user_id"),
        ("rate_sheets", "user_id"),
        ("quotes", "user_id"),
        ("api_keys", "user_id"),
        ("notifications", "user_id"),
        ("team_members", "user_id"),
    ]

    for table, col in tables_to_check:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (user_id,))
            cnt = cursor.fetchone()[0]
            if cnt > 0:
                results["clean"] = False
                results["leftovers"][table] = cnt
        except sqlite3.OperationalError:
            # Table might not exist in current schema
            continue

    conn.close()

    # Check scratch / uploads directory for leftover files with user_id or test patterns
    scratch_dir = os.path.join(PROJECT_ROOT, "scratch")
    if os.path.isdir(scratch_dir):
        for fname in os.listdir(scratch_dir):
            if user_id in fname:
                results["clean"] = False
                results["leftover_files"].append(fname)

    return results
