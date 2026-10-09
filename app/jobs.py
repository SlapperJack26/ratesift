"""
Relational SQLite JobStore implementation for RateSift platform.
Provides atomic status transitions, TTL sweeping, and orphan cleanup.
Designed to be compatible with PostgreSQL by utilizing standard ANSI SQL queries.
"""
from abc import ABC, abstractmethod
import glob
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

DB_PATH_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "shipflow.db")
DB_PATH = os.environ.get("FAILSAFE_DB_PATH", DB_PATH_DEFAULT)


class JobStore(ABC):
    @abstractmethod
    def create(self, job_id: str, data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def update(self, job_id: str, updates: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    def delete(self, job_id: str) -> bool:
        pass

    @abstractmethod
    def transition(self, job_id: str, from_status: str, to_status: str) -> bool:
        pass

    @abstractmethod
    def cleanup_expired(self, now: Optional[float] = None, max_processing_seconds: float = 300) -> int:
        pass

    @abstractmethod
    def sweep_orphaned_files(self, temp_dir: Optional[str] = None) -> int:
        pass


class RelationalJobStore(JobStore):
    def __init__(self, db_path: str = DB_PATH, default_ttl_seconds: int = 3600):
        self.db_path = db_path
        self.default_ttl = default_ttl_seconds
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for high concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS failsafe_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                tenant_id TEXT,
                status TEXT NOT NULL,
                path TEXT NOT NULL,
                ext TEXT NOT NULL,
                sheet_name TEXT,
                column_count INTEGER NOT NULL DEFAULT 0,
                analysis_json TEXT NOT NULL,
                mapping_json TEXT,
                mapping_source TEXT,
                output_path TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            """)
            try:
                cur.execute("ALTER TABLE failsafe_jobs ADD COLUMN output_path TEXT;")
            except Exception:
                pass
            cur.execute("CREATE INDEX IF NOT EXISTS idx_failsafe_jobs_status ON failsafe_jobs(status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_failsafe_jobs_user ON failsafe_jobs(user_id, tenant_id);")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS failsafe_saved_mappings (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                user_id TEXT,
                tenant_id TEXT,
                sheet_name TEXT,
                mapping_json TEXT NOT NULL,
                column_count INTEGER NOT NULL,
                header_names_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_failsafe_mappings_fp ON failsafe_saved_mappings(fingerprint, tenant_id);")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS failsafe_audit_logs (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                user_id TEXT,
                tenant_id TEXT,
                decision_type TEXT NOT NULL,
                mapping_summary_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_failsafe_audit_job ON failsafe_audit_logs(job_id);")

            conn.commit()
            conn.close()

    def create(self, job_id: str, data: Dict[str, Any]) -> None:
        now = time.time()
        expires_at = now + self.default_ttl
        user_id = data.get("user_id")
        tenant_id = data.get("tenant_id")
        status = data.get("status", "needs_mapping")
        path = data.get("path", "")
        ext = data.get("ext", "")
        sheet_name = data.get("sheet_name")
        column_count = data.get("column_count", 0)
        analysis_json = json.dumps(data.get("analysis", {}))
        mapping_json = json.dumps(data.get("mapping")) if data.get("mapping") else None
        mapping_source = data.get("mapping_source")
        output_path = data.get("output_path")

        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO failsafe_jobs (
                id, user_id, tenant_id, status, path, ext, sheet_name, column_count,
                analysis_json, mapping_json, mapping_source, output_path, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                job_id, user_id, tenant_id, status, path, ext, sheet_name, column_count,
                analysis_json, mapping_json, mapping_source, output_path, now, now, expires_at
            ))
            conn.commit()
            conn.close()

        data["created_at"] = now
        data["updated_at"] = now
        data["expires_at"] = expires_at

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM failsafe_jobs WHERE id = ?;", (job_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return None

            now = time.time()
            new_expires = now + self.default_ttl
            # Refresh TTL on activity
            cur.execute("UPDATE failsafe_jobs SET updated_at = ?, expires_at = ? WHERE id = ?;", (now, new_expires, job_id))
            conn.commit()
            conn.close()

            job_dict = dict(row)
            job_dict["analysis"] = json.loads(job_dict["analysis_json"])
            job_dict["mapping"] = json.loads(job_dict["mapping_json"]) if job_dict["mapping_json"] else None
            job_dict["rows"] = job_dict["analysis"].get("preview", [])
            job_dict["expires_at"] = new_expires
            return job_dict

    def update(self, job_id: str, updates: Dict[str, Any]) -> bool:
        now = time.time()
        new_expires = now + self.default_ttl

        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM failsafe_jobs WHERE id = ?;", (job_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return False

            status = updates.get("status", row["status"])
            sheet_name = updates.get("sheet_name", row["sheet_name"])
            mapping = updates.get("mapping")
            mapping_json = json.dumps(mapping) if mapping is not None else row["mapping_json"]
            mapping_source = updates.get("mapping_source", row["mapping_source"])
            output_path = updates.get("output_path", row["output_path"] if "output_path" in row.keys() else None)

            analysis = updates.get("analysis")
            if analysis is not None:
                analysis_json = json.dumps(analysis)
            else:
                analysis_json = row["analysis_json"]

            cur.execute("""
            UPDATE failsafe_jobs SET
                status = ?, sheet_name = ?, analysis_json = ?, mapping_json = ?,
                mapping_source = ?, output_path = ?, updated_at = ?, expires_at = ?
            WHERE id = ?;
            """, (status, sheet_name, analysis_json, mapping_json, mapping_source, output_path, now, new_expires, job_id))
            conn.commit()
            conn.close()
            return True

            conn.commit()
            conn.close()
            return True

    def delete(self, job_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT path FROM failsafe_jobs WHERE id = ?;", (job_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return False

            file_path = row["path"]
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass

            cur.execute("DELETE FROM failsafe_jobs WHERE id = ?;", (job_id,))
            conn.commit()
            conn.close()
            return True

    def transition(self, job_id: str, from_status: str, to_status: str) -> bool:
        """
        Atomic compare-and-set transition:
        UPDATE failsafe_jobs SET status = to_status WHERE id = job_id AND status = from_status
        Returns True if and only if exactly 1 row was updated.
        """
        now = time.time()
        new_expires = now + self.default_ttl
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
            UPDATE failsafe_jobs
            SET status = ?, updated_at = ?, expires_at = ?
            WHERE id = ? AND status = ?;
            """, (to_status, now, new_expires, job_id, from_status))
            updated_count = cur.rowcount

            if updated_count == 1:
                # Also update internal analysis_json status
                cur.execute("SELECT analysis_json FROM failsafe_jobs WHERE id = ?;", (job_id,))
                row = cur.fetchone()
                if row:
                    try:
                        an = json.loads(row["analysis_json"])
                        an["status"] = to_status
                        cur.execute("UPDATE failsafe_jobs SET analysis_json = ? WHERE id = ?;", (json.dumps(an), job_id))
                    except Exception:
                        pass
                conn.commit()
                conn.close()
                return True

            conn.commit()
            conn.close()
            return False

    def cleanup_expired(self, now: Optional[float] = None, max_processing_seconds: float = 300) -> int:
        """
        Sweeper for job lifecycle:
        1. Stuck jobs: status == 'processing' with updated_at < (now - max_processing_seconds) -> status = 'failed'
        2. Expired jobs: status != 'processing' with expires_at < now -> delete job & purge file.
        """
        if now is None:
            now = time.time()

        purged_count = 0
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()

            # 1. Mark hung processing jobs as failed
            hung_threshold = now - max_processing_seconds
            cur.execute("""
            UPDATE failsafe_jobs
            SET status = 'failed', updated_at = ?
            WHERE status = 'processing' AND updated_at < ?;
            """, (now, hung_threshold))

            # 2. Find expired jobs (excluding processing)
            cur.execute("""
            SELECT id, path FROM failsafe_jobs
            WHERE status != 'processing' AND expires_at < ?;
            """, (now,))
            expired_rows = cur.fetchall()

            for r in expired_rows:
                job_id = r["id"]
                file_path = r["path"]
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                cur.execute("DELETE FROM failsafe_jobs WHERE id = ?;", (job_id,))
                purged_count += 1

            conn.commit()
            conn.close()

        return purged_count

    def sweep_orphaned_files(self, temp_dir: Optional[str] = None) -> int:
        """Sweeps orphaned files on startup."""
        import tempfile
        target_dir = temp_dir or tempfile.gettempdir()
        swept = 0
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT path FROM failsafe_jobs;")
            active_paths = {row["path"] for row in cur.fetchall() if row["path"]}
            conn.close()

        # Find .xlsx and .csv files created in temp
        for ext in (".xlsx", ".csv"):
            for f in glob.glob(os.path.join(target_dir, f"tmp*{ext}")):
                if f not in active_paths:
                    try:
                        # If file was modified more than 10 minutes ago, delete
                        if time.time() - os.path.getmtime(f) > 600:
                            os.remove(f)
                            swept += 1
                    except OSError:
                        pass
        return swept


# Global Relational SQLite Store instance
job_store = RelationalJobStore()
