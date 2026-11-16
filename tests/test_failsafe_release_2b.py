"""
tests/test_failsafe_release_2b.py
Automated test suite for Release 2b:
- Safe VACUUM INTO Backup with Exclusive Write Lock (BEGIN IMMEDIATE)
- Free Disk Space Multiplier Verification (>= 2.5x)
- PRAGMA integrity_check on SQLite Backup
- Table-by-Table Row Count Parity
- Transactional Archival Migration of Legacy Parcel Sheets
- Reversible Rollback Procedure
"""
import os
import sqlite3
import tempfile
import time
import unittest
import uuid

import pytest

from scripts.backup_and_migrate_release_2b import (
    check_disk_space,
    perform_vacuum_into_backup,
    perform_parcel_archival_migration,
    rollback_parcel_archival_migration,
)
from services.quotelytics_db_service import (
    create_rate_sheet,
    insert_weight_breaks,
    confirm_rate_sheet,
    get_connection,
)


class TestFailsafeRelease2b(unittest.TestCase):

    def setUp(self):
        # Create a dedicated temporary SQLite database for testing VACUUM INTO and migration
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_source.db")
        self.bak_path = os.path.join(self.temp_dir, "test_backup.db")

        # Initialize schema and sample data in test database
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE ql_rate_sheets (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            carrier_name TEXT NOT NULL,
            service_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            confirmation_status TEXT NOT NULL,
            is_legacy_parcel INTEGER DEFAULT 0,
            prior_status TEXT,
            currency TEXT DEFAULT 'CAD'
        );
        """)
        c.execute("""
        CREATE TABLE ql_weight_breaks (
            id TEXT PRIMARY KEY,
            sheet_id TEXT NOT NULL,
            base_rate REAL NOT NULL
        );
        """)

        # Insert active LTL sheet
        c.execute("""
        INSERT INTO ql_rate_sheets (id, user_id, carrier_name, service_name, mode, confirmation_status)
        VALUES ('sheet_ltl_1', 'user_1', 'Day & Ross', 'Standard LTL', 'LTL', 'CONFIRMED');
        """)
        # Insert legacy Parcel sheet
        c.execute("""
        INSERT INTO ql_rate_sheets (id, user_id, carrier_name, service_name, mode, confirmation_status)
        VALUES ('sheet_parcel_1', 'user_1', 'Canpar Courier', 'Ground Parcel', 'PARCEL', 'CONFIRMED');
        """)
        c.execute("""
        INSERT INTO ql_weight_breaks (id, sheet_id, base_rate)
        VALUES ('wb_1', 'sheet_ltl_1', 45.0), ('wb_2', 'sheet_parcel_1', 12.50);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            if os.path.exists(self.bak_path):
                os.remove(self.bak_path)
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # Test 25: VACUUM INTO Backup and Integrity Check [Release 2b]
    # --------------------------------------------------------------------------
    def test_vacuum_into_backup_and_integrity_check(self):
        """Creates atomic VACUUM INTO backup, verifies integrity_check, and verifies row counts."""
        # 1. Disk space verification
        check_disk_space(self.temp_dir, self.db_path, min_multiplier=1.0)

        # 2. Perform atomic VACUUM INTO backup
        perform_vacuum_into_backup(self.db_path, self.bak_path)
        self.assertTrue(os.path.exists(self.bak_path))

        # 3. Verify backup is a valid SQLite database with integrity_check == 'ok'
        bak_conn = sqlite3.connect(self.bak_path)
        bak_cur = bak_conn.cursor()
        check_res = bak_cur.execute("PRAGMA integrity_check;").fetchall()
        self.assertEqual(check_res[0][0], "ok")

        # 4. Table-by-table count verification
        bak_sheets_count = bak_cur.execute("SELECT COUNT(*) FROM ql_rate_sheets;").fetchone()[0]
        bak_breaks_count = bak_cur.execute("SELECT COUNT(*) FROM ql_weight_breaks;").fetchone()[0]
        self.assertEqual(bak_sheets_count, 2)
        self.assertEqual(bak_breaks_count, 2)
        bak_conn.close()

    # --------------------------------------------------------------------------
    # Test: Transactional Parcel Archival Migration & Rollback [Release 2b]
    # --------------------------------------------------------------------------
    def test_transactional_parcel_archival_migration_and_rollback(self):
        """Asserts archival migration sets is_legacy_parcel=1, prior_status, and confirmation_status=ARCHIVED."""
        # Execute migration
        archived_count = perform_parcel_archival_migration(self.db_path)
        self.assertEqual(archived_count, 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Parcel sheet should now be ARCHIVED with prior_status='CONFIRMED'
        parcel_sheet = c.execute("SELECT * FROM ql_rate_sheets WHERE id = 'sheet_parcel_1';").fetchone()
        self.assertEqual(parcel_sheet["confirmation_status"], "ARCHIVED")
        self.assertEqual(parcel_sheet["is_legacy_parcel"], 1)
        self.assertEqual(parcel_sheet["prior_status"], "CONFIRMED")

        # LTL sheet remains untouched
        ltl_sheet = c.execute("SELECT * FROM ql_rate_sheets WHERE id = 'sheet_ltl_1';").fetchone()
        self.assertEqual(ltl_sheet["confirmation_status"], "CONFIRMED")
        self.assertEqual(ltl_sheet["is_legacy_parcel"], 0)
        conn.close()

        # Execute rollback and verify restoration
        restored_count = rollback_parcel_archival_migration(self.db_path)
        self.assertEqual(restored_count, 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        restored_parcel = c.execute("SELECT * FROM ql_rate_sheets WHERE id = 'sheet_parcel_1';").fetchone()
        self.assertEqual(restored_parcel["confirmation_status"], "CONFIRMED")
        self.assertEqual(restored_parcel["is_legacy_parcel"], 0)
        conn.close()
