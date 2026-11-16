import sqlite3
import os
import json
import uuid
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("quotelytics.db")

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "quotelytics.db")


def get_connection():
    """Open a SQLite connection configured with WAL mode, foreign keys, and row factory."""
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_session():
    """Context manager that yields a SQLite connection and always closes it."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Subscription Tiers Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subscription_tiers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price_monthly REAL NOT NULL DEFAULT 0.0,
        max_sheets INTEGER NOT NULL,
        max_quotes_per_month INTEGER NOT NULL,
        has_api_access INTEGER NOT NULL DEFAULT 0,
        max_seats INTEGER NOT NULL DEFAULT 1
    )
    """)
    
    # Auto-migrate max_seats column if table already exists
    cursor.execute("PRAGMA table_info(subscription_tiers)")
    tier_cols = [r["name"] for r in cursor.fetchall()]
    if "max_seats" not in tier_cols:
        cursor.execute("ALTER TABLE subscription_tiers ADD COLUMN max_seats INTEGER NOT NULL DEFAULT 1")

    # Seed standard tiers with explicit seat, sheet, and quote limits
    cursor.executemany("""
    INSERT OR REPLACE INTO subscription_tiers (id, name, price_monthly, max_sheets, max_quotes_per_month, has_api_access, max_seats)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [
        ("FREE", "Free Starter", 0.0, 3, 50, 0, 1),
        ("PRO", "Broker Pro", 79.0, 10, 2500, 0, 1),
        ("TEAM", "Broker Team", 199.0, -1, 15000, 0, 5),
        ("BUSINESS", "Business", -1.0, -1, -1, 1, -1)  # -1 represents custom / get quote
    ])
    
    # 2. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        company TEXT NOT NULL,
        origin_zip TEXT NOT NULL DEFAULT 'TORONTO, ON',
        tier TEXT NOT NULL DEFAULT 'FREE',
        role TEXT NOT NULL DEFAULT 'USER',
        created_at TEXT NOT NULL,
        FOREIGN KEY (tier) REFERENCES subscription_tiers (id)
    )
    """)
    
    # Auto-migrate password_hash, role, origin_address, phone, and privacy/CASL columns if table existed from phase 1
    cursor.execute("PRAGMA table_info(users)")
    cols = [r["name"] for r in cursor.fetchall()]
    if "password_hash" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
    if "role" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'USER'")
    if "origin_address" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN origin_address TEXT DEFAULT ''")
    if "phone" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    if "marketing_opt_in" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN marketing_opt_in INTEGER NOT NULL DEFAULT 0")
    if "marketing_consent_at" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN marketing_consent_at TEXT")
    if "terms_accepted_at" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN terms_accepted_at TEXT")
    if "closed_at" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN closed_at TEXT")
    if "email_verified" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
    if "email_verified_at" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
    if "stripe_customer_id" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
    if "stripe_subscription_id" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT")
    if "subscription_status" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN subscription_status TEXT NOT NULL DEFAULT 'active'")
    if "seat_count" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN seat_count INTEGER NOT NULL DEFAULT 1")
    if "current_period_end" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN current_period_end TEXT")
    if "cancel_at_period_end" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN cancel_at_period_end INTEGER NOT NULL DEFAULT 0")

    # 2a. One-Time Auth Tokens Table (Password Reset & Email Verification - hashed tokens only)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auth_tokens (
        id TEXT PRIMARY KEY,
        token_hash TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL,
        token_type TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_lookup ON auth_tokens (token_hash, token_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens (user_id, token_type)")

    # 2b. Marketing Consent Audit Log Table (CASL Compliance - 3 year retention)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS marketing_consent_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        email TEXT NOT NULL,
        consented INTEGER NOT NULL DEFAULT 0,
        consent_type TEXT NOT NULL DEFAULT 'SIGNUP_OPT_IN',
        form_version TEXT NOT NULL DEFAULT 'v2026.10',
        ip_address TEXT,
        user_agent TEXT,
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_marketing_consent_user ON marketing_consent_logs (user_id, created_at)")
    
    # 3. User Settings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id TEXT PRIMARY KEY,
        currency TEXT NOT NULL DEFAULT 'CAD',
        units TEXT NOT NULL DEFAULT 'lbs',
        markup_pct REAL NOT NULL DEFAULT 10.0,
        markup_mode TEXT NOT NULL DEFAULT 'PERCENTAGE',
        fsc_passthrough INTEGER NOT NULL DEFAULT 1,
        auto_detect_headers INTEGER NOT NULL DEFAULT 1,
        skip_blank_rows INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)

    # Auto-migrate user_settings columns
    cursor.execute("PRAGMA table_info(user_settings)")
    s_cols = [r["name"] for r in cursor.fetchall()]
    if "markup_mode" not in s_cols:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN markup_mode TEXT DEFAULT 'PERCENTAGE'")
    if "fsc_passthrough" not in s_cols:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN fsc_passthrough INTEGER DEFAULT 1")

    # 3b. User Keyword Definitions Table (Custom Excel Header / Code Meanings per Tenant)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_keyword_definitions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        keyword TEXT NOT NULL,
        normalized_keyword TEXT NOT NULL,
        definition_text TEXT NOT NULL,
        parsed_category TEXT NOT NULL,
        parsed_rule_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        UNIQUE (user_id, normalized_keyword)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_kw_defs_user ON user_keyword_definitions (user_id)")
    
    # 4. User Sessions Table (Route Guarding & Cookie Auth)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
    # 5. Quote Batches (Rate sheet tracking per user)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quote_batches (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        total_rows INTEGER NOT NULL DEFAULT 0,
        processed_rows INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
    # 6. Quote Items (Exact cell coordinates and calculated rates)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quote_items (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        row_num INTEGER NOT NULL,
        origin_zip TEXT NOT NULL,
        dest_zip TEXT NOT NULL,
        weight_lbs REAL NOT NULL,
        carrier TEXT NOT NULL,
        service TEXT NOT NULL,
        base_rate REAL NOT NULL,
        markup_pct REAL NOT NULL DEFAULT 10.0,
        final_rate REAL NOT NULL,
        coordinate TEXT NOT NULL,
        created_at TEXT NOT NULL,
        sheet_id TEXT,
        formula TEXT,
        calculation_trace TEXT,
        skid_count INTEGER,
        FOREIGN KEY (batch_id) REFERENCES quote_batches (id)
    )
    """)
    
    # Auto-migrate sheet_id, formula, calculation_trace, skid_count on quote_items if table already exists
    cursor.execute("PRAGMA table_info(quote_items)")
    qi_cols = [r["name"] for r in cursor.fetchall()]
    if "sheet_id" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN sheet_id TEXT")
    if "formula" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN formula TEXT")
    if "calculation_trace" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN calculation_trace TEXT")
    if "skid_count" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN skid_count INTEGER")
    
    # 7. API Keys Table (Business Tier Embedded Quoting API)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        key TEXT PRIMARY KEY,
        id TEXT,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT 'Default API Key',
        key_prefix TEXT,
        key_hash TEXT,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("PRAGMA table_info(api_keys)")
    ak_cols = [c["name"] for c in cursor.fetchall()]
    if "id" not in ak_cols:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN id TEXT")
    if "key_prefix" not in ak_cols:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN key_prefix TEXT")
    if "key_hash" not in ak_cols:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN key_hash TEXT")
    if "last_used_at" not in ak_cols:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN last_used_at TEXT")
    if "revoked_at" not in ak_cols:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN revoked_at TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (key_hash)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys (user_id, created_at)")

    # Migrate any legacy plaintext API keys at rest into SHA-256 hashes + prefixes
    import hashlib
    import secrets as _secrets
    cursor.execute("SELECT key, id, key_prefix, key_hash FROM api_keys WHERE key_hash IS NULL")
    legacy_keys = cursor.fetchall()
    for lk in legacy_keys:
        raw_k = lk["key"] or ""
        kid = lk["id"] or f"key_{_secrets.token_hex(6)}"
        if raw_k.startswith("REDACTED_"):
            continue
        khash = hashlib.sha256(raw_k.encode("utf-8")).hexdigest()
        kprefix = f"{raw_k[:16]}..." if len(raw_k) >= 16 else f"{raw_k[:8]}..."
        cursor.execute(
            "UPDATE api_keys SET key = ?, id = ?, key_prefix = ?, key_hash = ? WHERE key = ?",
            (f"REDACTED_{kid}", kid, kprefix, khash, raw_k),
        )

    # 7b. Webhook Endpoints & Deliveries Tables (Business Tier Batch Quoting Events)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS webhook_endpoints (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        url TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        secret TEXT NOT NULL,
        events TEXT NOT NULL DEFAULT 'batch.quote.completed',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_endpoints_user ON webhook_endpoints (user_id, is_active)")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS webhook_deliveries (
        id TEXT PRIMARY KEY,
        endpoint_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        batch_id TEXT,
        response_status INTEGER,
        success INTEGER NOT NULL DEFAULT 0,
        attempt_count INTEGER NOT NULL DEFAULT 1,
        error_message TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (endpoint_id) REFERENCES webhook_endpoints (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_user ON webhook_deliveries (user_id, created_at)")

    # 7a. Active Proposal Drafts Table (replaces process-local _active_proposal_memory)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS proposal_drafts (
        user_id TEXT PRIMARY KEY,
        proposal_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)

    # 8. Organization & Team Members Table (Multi-Seat Scaling)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS organization_members (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        user_id TEXT,
        invited_email TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'DISPATCHER',
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_org_members_org ON organization_members (organization_id)")

    # 9. Bottleneck Events Table (Tracks every quota block & upgrade constraint)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bottleneck_events (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        tier TEXT NOT NULL,
        bottleneck_type TEXT NOT NULL,
        attempted_action TEXT NOT NULL,
        current_usage INTEGER NOT NULL,
        max_limit INTEGER NOT NULL,
        details_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bottleneck_user ON bottleneck_events (user_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bottleneck_type ON bottleneck_events (bottleneck_type, created_at)")
    
    # 10. Support Tickets Table (Footer & Helpdesk Inquiries)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS support_tickets (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        email TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'GENERAL',
        browser_info TEXT,
        status TEXT NOT NULL DEFAULT 'OPEN',
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_support_user ON support_tickets (user_id, created_at)")

    # 11. System Notifications Table (Header Bell & Alerts Popover)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_notifications (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        alert_type TEXT NOT NULL DEFAULT 'INFO',
        link_url TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON system_notifications (user_id, is_read, created_at)")

    conn.commit()
    conn.close()

    # Initialize Quotelytics normalized schema (Rules 2, 3, 28, 29, 30)
    try:
        from services.quotelytics_db_service import init_quotelytics_db
        init_quotelytics_db()
    except Exception as e:
        print(f"[Quotelytics DB Warning] Could not initialize Quotelytics schema: {e}")

    # One-time idempotent purge of legacy demo user & static credentials
    _purge_legacy_demo_account()

    # Bootstrap dedicated Admin account from environment variables if configured
    _bootstrap_admin_account()


def _purge_legacy_demo_account() -> None:
    """
    Idempotent one-time purge migration that completely removes the legacy demo user
    (usr_alex_rivers), all associated rate sheets/quotes/settings/notifications, and
    the static demo session and API key. Short-circuits in <1ms if already purged.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        has_user = cursor.execute(
            "SELECT 1 FROM users WHERE id = 'usr_alex_rivers' OR email = 'alex.rivers@techcorp.io' LIMIT 1"
        ).fetchone() is not None
        has_session = cursor.execute(
            "SELECT 1 FROM sessions WHERE user_id = 'usr_alex_rivers' OR token = 'session_demo_alex_rivers' LIMIT 1"
        ).fetchone() is not None
        has_key = cursor.execute(
            "SELECT 1 FROM api_keys WHERE user_id = 'usr_alex_rivers' OR key IN ('ql_live_demo_alex_rivers_key_2026', 'sf_live_demo_alex_rivers_key_2026') LIMIT 1"
        ).fetchone() is not None
    finally:
        conn.close()

    if not (has_user or has_session or has_key):
        return

    try:
        delete_user_account_data("usr_alex_rivers", immediate_purge=True)
    except Exception as exc:
        logger.warning("Legacy demo purge helper failed (continuing manual cleanup): %s", exc)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM sessions WHERE token = 'session_demo_alex_rivers'")
        cursor.execute("DELETE FROM api_keys WHERE key IN ('ql_live_demo_alex_rivers_key_2026', 'sf_live_demo_alex_rivers_key_2026')")
        cursor.execute("DELETE FROM marketing_consent_logs WHERE user_id = 'usr_alex_rivers' OR email = 'alex.rivers@techcorp.io'")
        cursor.execute("DELETE FROM users WHERE email = 'alex.rivers@techcorp.io'")
        for fs_table in ("failsafe_jobs", "failsafe_saved_mappings", "failsafe_audit_logs"):
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (fs_table,))
            if cursor.fetchone():
                cursor.execute(f"DELETE FROM {fs_table} WHERE user_id = 'usr_alex_rivers' OR tenant_id IN ('usr_alex_rivers', 'TechCorp Logistics')")
        conn.commit()
    finally:
        conn.close()


def _bootstrap_admin_account() -> None:
    """
    Provisions or updates the ADMIN account from QUOTELYTICS_ADMIN_EMAIL and
    QUOTELYTICS_ADMIN_PASSWORD. If either env var is missing or password < 12 chars,
    creates no admin and logs a warning. Never downgrades an existing ADMIN's role.
    """
    import logging
    logger = logging.getLogger("quotelytics.admin_bootstrap")

    admin_email = (os.getenv("QUOTELYTICS_ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.getenv("QUOTELYTICS_ADMIN_PASSWORD") or ""

    if not admin_email or not admin_password:
        logger.warning(
            "QUOTELYTICS_ADMIN_EMAIL or QUOTELYTICS_ADMIN_PASSWORD not set; skipping admin account bootstrap."
        )
        return

    if len(admin_password) < 12:
        logger.warning(
            "QUOTELYTICS_ADMIN_PASSWORD must be at least 12 characters long; skipping admin account bootstrap."
        )
        return

    from services.auth_service import hash_password, verify_password

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, email, password_hash, role, tier FROM users WHERE email = ? OR id = 'usr_admin'",
            (admin_email,),
        )
        row = cursor.fetchone()
        now = datetime.utcnow().isoformat()

        if not row:
            pwd_hash = hash_password(admin_password)
            cursor.execute(
                """
                INSERT INTO users (id, name, email, password_hash, company, origin_zip, tier, role, created_at)
                VALUES ('usr_admin', 'System Administrator', ?, ?, 'Quotelytics', 'TORONTO, ON', 'BUSINESS', 'ADMIN', ?)
                """,
                (admin_email, pwd_hash, now),
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO user_settings (user_id, currency, units, markup_pct, auto_detect_headers, skip_blank_rows)
                VALUES ('usr_admin', 'CAD', 'lbs', 10.0, 1, 1)
                """
            )
        else:
            uid = row["id"]
            stored_hash = row["password_hash"] or ""
            is_valid, needs_rehash = verify_password(admin_password, stored_hash)
            if not is_valid or needs_rehash:
                cursor.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(admin_password), uid),
                )
            if row["role"] != "ADMIN":
                cursor.execute("UPDATE users SET role = 'ADMIN' WHERE id = ?", (uid,))
            if row["email"] != admin_email:
                cursor.execute("UPDATE users SET email = ? WHERE id = ?", (admin_email, uid))

        conn.commit()
    finally:
        conn.close()

def get_user_quota_info(user_id: str):
    """
    Computes tier limits, monthly quote usage, uploaded rate sheet count, and seat allocations.
    Strictly tracks bottlenecks for:
      - Max sheets connected (Free: 3, Pro: 10, Team: Unlimited, Business: Unlimited)
      - Monthly quotes generated (Free: 50, Pro: 2,500, Team: 15,000, Business: Custom)
      - Dispatcher seats (Free: 1, Pro: 1, Team: 5, Business: Custom)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Fetch user & tier details
    cursor.execute("""
    SELECT u.id, u.name, u.email, u.company, u.tier, t.name as tier_name,
           t.max_sheets, t.max_quotes_per_month, t.has_api_access, t.max_seats
    FROM users u
    JOIN subscription_tiers t ON u.tier = t.id
    WHERE u.id = ?
    """, (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
        
    user_info = dict(row)
    
    # 2. Count uploaded rate sheets
    # Count Quotelytics normalized sheets uploaded by this user (excluding benchmark/demo seeds)
    try:
        cursor.execute("""
        SELECT count(*) as count 
        FROM ql_rate_sheets 
        WHERE user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL)
        """, (user_id,))
        ql_sheet_count = cursor.fetchone()["count"]
    except Exception:
        ql_sheet_count = 0

    # Count batch spreadsheet uploads
    cursor.execute("SELECT count(*) as count FROM quote_batches WHERE user_id = ?", (user_id,))
    batch_sheet_count = cursor.fetchone()["count"]
    total_sheets = ql_sheet_count + batch_sheet_count
    
    # 3. Count quotes created this calendar month
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    
    # Quotelytics deterministic quote audit logs
    try:
        cursor.execute("""
        SELECT count(id) as count 
        FROM ql_quote_audit_logs 
        WHERE user_id = ? AND timestamp >= ?
        """, (user_id, month_start))
        rs_quote_count = cursor.fetchone()["count"]
    except Exception:
        rs_quote_count = 0
        
    # Batch spreadsheet quote items
    cursor.execute("""
    SELECT count(qi.id) as count
    FROM quote_items qi
    JOIN quote_batches qb ON qi.batch_id = qb.id
    WHERE qb.user_id = ? AND qi.created_at >= ?
    """, (user_id, month_start))
    batch_quote_count = cursor.fetchone()["count"]
    
    monthly_quotes_used = rs_quote_count + batch_quote_count
    
    # 4. Count team seats allocated
    cursor.execute("""
    SELECT count(*) as count
    FROM organization_members
    WHERE organization_id = ? AND status != 'REVOKED'
    """, (user_id,))
    invited_seats = cursor.fetchone()["count"]
    active_seats = 1 + invited_seats  # Primary owner counts as 1 seat
    
    conn.close()
    
    max_sheets = user_info["max_sheets"]
    max_quotes = user_info["max_quotes_per_month"]
    max_seats = user_info.get("max_seats", 1)
    
    sheets_remaining = max(0, max_sheets - total_sheets) if max_sheets > 0 else -1
    quotes_remaining = max(0, max_quotes - monthly_quotes_used) if max_quotes > 0 else -1
    seats_remaining = max(0, max_seats - active_seats) if max_seats > 0 else -1
    
    can_upload_sheet = (total_sheets < max_sheets) if max_sheets > 0 else True
    can_quote = (monthly_quotes_used < max_quotes) if max_quotes > 0 else True
    can_invite_seat = (active_seats < max_seats) if max_seats > 0 else True
    
    return {
        "user_id": user_id,
        "tier": user_info["tier"],
        "tier_name": user_info["tier_name"],
        "max_sheets": max_sheets,
        "sheets_uploaded": total_sheets,
        "sheets_remaining": sheets_remaining,
        "max_quotes_per_month": max_quotes,
        "monthly_quotes_used": monthly_quotes_used,
        "quotes_remaining": quotes_remaining,
        "max_seats": max_seats,
        "active_seats": active_seats,
        "seats_remaining": seats_remaining,
        "has_api_access": bool(user_info["has_api_access"]),
        "can_upload_sheet": can_upload_sheet,
        "can_quote": can_quote,
        "can_quote_rows": can_quote,
        "can_invite_seat": can_invite_seat
    }

def log_bottleneck_event(
    user_id: str,
    bottleneck_type: str,
    attempted_action: str,
    current_usage: int,
    max_limit: int,
    details: Optional[Dict[str, Any]] = None
) -> str:
    """
    Logs an encounter with a subscription or operational bottleneck.
    Supports tracking across:
      - LIMIT_BLOCKED_SHEETS
      - LIMIT_BLOCKED_QUOTES
      - LIMIT_BLOCKED_SEATS
      - LIMIT_BLOCKED_API
    """
    event_id = f"btn_{uuid.uuid4().hex[:10]}"
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT tier FROM users WHERE id = ?", (user_id,))
    u_row = cursor.fetchone()
    tier = u_row["tier"] if u_row else "UNKNOWN"
    
    details_str = json.dumps(details or {})
    cursor.execute("""
    INSERT INTO bottleneck_events (
        id, user_id, tier, bottleneck_type, attempted_action,
        current_usage, max_limit, details_json, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id, user_id, tier, bottleneck_type, attempted_action,
        current_usage, max_limit, details_str, now
    ))
    conn.commit()
    conn.close()
    return event_id

def list_bottleneck_events(user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves logged bottleneck incidents for analysis and telemetry."""
    conn = get_connection()
    cursor = conn.cursor()
    if user_id:
        cursor.execute("""
        SELECT * FROM bottleneck_events
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """, (user_id, limit))
    else:
        cursor.execute("""
        SELECT * FROM bottleneck_events
        ORDER BY created_at DESC
        LIMIT ?
        """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    events = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details_json") or "{}")
        except Exception:
            d["details"] = {}
        events.append(d)
    return events

def list_organization_members(organization_id: str) -> List[Dict[str, Any]]:
    """Retrieves all team members and dispatchers under this organization."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM organization_members
    WHERE organization_id = ?
    ORDER BY created_at ASC
    """, (organization_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_organization_member(
    organization_id: str,
    email: str,
    name: str = "",
    role: str = "DISPATCHER"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Invites or adds a team member if seat quota permits.
    Returns (success, message, member_dict).
    """
    quota = get_user_quota_info(organization_id)
    if not quota:
        return False, "Organization not found.", None
        
    if not quota["can_invite_seat"]:
        log_bottleneck_event(
            user_id=organization_id,
            bottleneck_type="LIMIT_BLOCKED_SEATS",
            attempted_action=f"Invite seat: {email}",
            current_usage=quota["active_seats"],
            max_limit=quota["max_seats"],
            details={"email": email, "role": role}
        )
        return False, f"Seat limit reached: {quota['tier_name']} includes {quota['max_seats']} seat(s). Upgrade to Broker Team for 5 seats.", None

    member_id = f"mem_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO organization_members (id, organization_id, user_id, invited_email, name, role, status, created_at)
    VALUES (?, ?, NULL, ?, ?, ?, 'ACTIVE', ?)
    """, (member_id, organization_id, email.strip().lower(), name.strip(), role, now))
    conn.commit()
    conn.close()
    
    return True, "Member invited successfully.", {
        "id": member_id,
        "organization_id": organization_id,
        "invited_email": email.strip().lower(),
        "name": name.strip(),
        "role": role,
        "status": "ACTIVE",
        "created_at": now
    }

def remove_organization_member(organization_id: str, member_id: str) -> bool:
    """Removes a team member / frees up a seat."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE organization_members
    SET status = 'REVOKED'
    WHERE id = ? AND organization_id = ?
    """, (member_id, organization_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def update_user_tier(user_id: str, new_tier: str) -> bool:
    """Updates user subscription tier (e.g. FREE -> PRO -> TEAM -> BUSINESS)."""
    valid_tiers = ["FREE", "PRO", "TEAM", "BUSINESS"]
    tier_upper = new_tier.strip().upper()
    if tier_upper not in valid_tiers:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET tier = ? WHERE id = ? AND closed_at IS NULL", (tier_upper, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_active_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Looks up an active (non-closed) user record by case-insensitive email address."""
    clean_email = (email or "").strip().lower()
    if not clean_email:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, name, email, company, tier, role, origin_zip, created_at FROM users WHERE LOWER(email) = ? AND closed_at IS NULL",
            (clean_email,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def search_customers_for_admin(query: str = "", limit: int = 25) -> List[Dict[str, Any]]:
    """
    Searches active customer accounts by email, company, or name for the Sales/Admin Onboarding Desk.
    Returns strictly onboarding readiness metadata and aggregate counts — never tariff rates or raw secrets.
    """
    clean_q = (query or "").strip().lower()
    safe_limit = max(1, min(int(limit or 25), 50))
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_api_keys_schema(cursor)
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {r[0] for r in cursor.fetchall()}
        has_ql_sheets = "ql_rate_sheets" in tables
        has_webhooks = "webhook_endpoints" in tables

        sheets_subq = (
            "(SELECT count(*) FROM ql_rate_sheets s WHERE s.user_id = u.id "
            "AND (s.is_benchmark = 0 OR s.is_benchmark IS NULL) "
            "AND s.confirmation_status != 'ARCHIVED' "
            "AND (s.confirmation_status = 'CONFIRMED' OR s.manual_override = 1))"
            if has_ql_sheets
            else "0"
        )
        webhooks_subq = (
            "(SELECT count(*) FROM webhook_endpoints w WHERE w.user_id = u.id AND w.is_active = 1)"
            if has_webhooks
            else "0"
        )

        sql = f"""
            SELECT u.id, u.name, u.email, u.company, u.tier, u.role, u.origin_zip,
                   COALESCE(u.email_verified, 0) AS email_verified,
                   u.created_at,
                   {sheets_subq} AS confirmed_sheets_count,
                   (SELECT count(*) FROM api_keys k WHERE k.user_id = u.id AND k.revoked_at IS NULL) AS active_api_keys_count,
                   {webhooks_subq} AS active_webhooks_count
            FROM users u
            WHERE u.closed_at IS NULL
        """
        params: List[Any] = []
        if clean_q:
            like_pat = f"%{clean_q}%"
            sql += " AND (LOWER(u.email) LIKE ? OR LOWER(u.company) LIKE ? OR LOWER(u.name) LIKE ?)"
            params.extend([like_pat, like_pat, like_pat])

        sql += " ORDER BY u.created_at DESC LIMIT ?"
        params.append(safe_limit)

        cursor.execute(sql, tuple(params))
        results: List[Dict[str, Any]] = []
        for r in cursor.fetchall():
            tier_up = (r["tier"] or "FREE").upper()
            sheets_cnt = int(r["confirmed_sheets_count"] or 0)
            keys_cnt = int(r["active_api_keys_count"] or 0)
            results.append({
                "id": r["id"],
                "name": r["name"],
                "email": r["email"],
                "company": r["company"],
                "tier": tier_up,
                "has_api_access": tier_up == "BUSINESS",
                "role": r["role"] or "USER",
                "origin_zip": r["origin_zip"] or "",
                "email_verified": bool(r["email_verified"]),
                "created_at": r["created_at"],
                "confirmed_sheets_count": sheets_cnt,
                "active_api_keys_count": keys_cnt,
                "active_webhooks_count": int(r["active_webhooks_count"] or 0),
                "api_ready": (tier_up == "BUSINESS" and sheets_cnt > 0 and keys_cnt > 0),
            })
        return results
    finally:
        conn.close()

def update_user_account(user_id: str, name: str, company: str, origin_zip: str, origin_address: str = "", phone: str = ""):
    """Updates user profile and default quoting origin information."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE users
    SET name = ?, company = ?, origin_zip = ?, origin_address = ?, phone = ?
    WHERE id = ?
    """, (name.strip(), company.strip(), origin_zip.strip(), origin_address.strip(), phone.strip(), user_id))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Profile and origin defaults updated successfully."}

def update_user_password(user_id: str, current_password: str, new_password: str) -> Tuple[bool, str]:
    """Updates user password after verifying current password hash using salted Argon2id."""
    from services.auth_service import hash_password, verify_password
    if len(new_password) < 10:
        return False, "New password must be at least 10 characters long."
        
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "User not found."
        
    stored_hash = row["password_hash"]
    is_valid, _ = verify_password(current_password, stored_hash)
    
    if not is_valid:
        conn.close()
        return False, "Current password incorrect."
        
    new_hash = hash_password(new_password)
    cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
    conn.commit()
    conn.close()
    return True, "Password updated successfully."

def _ensure_api_keys_schema(cursor) -> None:
    """Idempotently ensures hashed API key and webhook columns/tables exist on any connection."""
    cursor.execute("PRAGMA table_info(api_keys)")
    ak_cols = {c[1] for c in cursor.fetchall()}
    if ak_cols:
        if "id" not in ak_cols:
            cursor.execute("ALTER TABLE api_keys ADD COLUMN id TEXT")
        if "key_prefix" not in ak_cols:
            cursor.execute("ALTER TABLE api_keys ADD COLUMN key_prefix TEXT")
        if "key_hash" not in ak_cols:
            cursor.execute("ALTER TABLE api_keys ADD COLUMN key_hash TEXT")
        if "last_used_at" not in ak_cols:
            cursor.execute("ALTER TABLE api_keys ADD COLUMN last_used_at TEXT")
        if "revoked_at" not in ak_cols:
            cursor.execute("ALTER TABLE api_keys ADD COLUMN revoked_at TEXT")


def create_api_key_record(
    user_id: str,
    name: str = "Production Quoting Key",
    max_active_keys: int = 25,
) -> Dict[str, Any]:
    """
    Generates an embedded quoting API key for Business tier users.
    Stores only a SHA-256 hash and display prefix at rest; returns the raw secret once.
    """
    import hashlib
    import secrets

    clean_name = (name or "Production Quoting Key").strip()[:80] or "Production Quoting Key"
    key_id = f"key_{secrets.token_hex(6)}"
    raw_key = f"ql_live_{secrets.token_hex(16)}"
    key_prefix = f"{raw_key[:16]}..."
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    now = datetime.utcnow().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_api_keys_schema(cursor)
        cursor.execute(
            "SELECT count(*) as cnt FROM api_keys WHERE user_id = ? AND revoked_at IS NULL",
            (user_id,),
        )
        active_cnt = cursor.fetchone()["cnt"]
        if active_cnt >= max_active_keys:
            raise ValueError(
                f"Maximum limit of {max_active_keys} active API keys reached. Please revoke an unused key first."
            )

        cursor.execute(
            """
            INSERT INTO api_keys (key, id, user_id, name, key_prefix, key_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"REDACTED_{key_id}", key_id, user_id, clean_name, key_prefix, key_hash, now),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "id": key_id,
        "name": clean_name,
        "api_key": raw_key,
        "key_prefix": key_prefix,
        "created_at": now,
    }


def create_api_key(user_id: str, name: str = "Production Quoting Key") -> str:
    """Generates an embedded quoting API key for Business tier users and returns the raw key string."""
    return create_api_key_record(user_id=user_id, name=name)["api_key"]


def list_api_keys(user_id: str) -> List[Dict[str, Any]]:
    """Lists API key metadata for a user without ever exposing raw secrets or hashes."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_api_keys_schema(cursor)
        cursor.execute(
            """
            SELECT id, key, name, key_prefix, created_at, last_used_at, revoked_at
            FROM api_keys
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            prefix = r["key_prefix"]
            if not prefix:
                raw = r["key"] or ""
                prefix = f"{raw[:16]}..." if not raw.startswith("REDACTED_") else "ql_live_********..."
            out.append({
                "id": r["id"] or "",
                "name": r["name"],
                "key_prefix": prefix,
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
                "revoked_at": r["revoked_at"],
                "status": "REVOKED" if r["revoked_at"] else "ACTIVE",
            })
        return out
    finally:
        conn.close()


def revoke_api_key(user_id: str, key_id: str) -> bool:
    """Revokes an API key owned by user_id."""
    if not key_id:
        return False
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_api_keys_schema(cursor)
        cursor.execute(
            """
            UPDATE api_keys
            SET revoked_at = ?
            WHERE id = ? AND user_id = ? AND revoked_at IS NULL
            """,
            (now, key_id.strip(), user_id),
        )
        updated = cursor.rowcount > 0
        conn.commit()
        return updated
    finally:
        conn.close()


def authenticate_api_key(api_key: str):
    """
    Authenticates an X-API-Key header using SHA-256 hash comparison.
    Returns (user_dict, error_code) where error_code is:
      - None: valid key belonging to an active BUSINESS account
      - 'INVALID': missing, unknown, revoked, or closed account (HTTP 401)
      - 'TIER_REQUIRED': key belongs to an account no longer on BUSINESS tier (HTTP 403)
    """
    import hashlib
    import hmac

    if not api_key or not api_key.strip():
        return None, "INVALID"

    clean_key = api_key.strip()
    candidate_hash = hashlib.sha256(clean_key.encode("utf-8")).hexdigest()

    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_api_keys_schema(cursor)
        cursor.execute(
            """
            SELECT k.id AS key_id, k.key AS raw_col, k.key_hash, k.revoked_at,
                   u.id, u.name, u.email, u.company, u.origin_zip, u.tier, u.role, u.closed_at,
                   COALESCE(t.has_api_access, 0) AS has_api_access
            FROM api_keys k
            JOIN users u ON k.user_id = u.id
            LEFT JOIN subscription_tiers t ON u.tier = t.id
            WHERE k.key_hash = ? OR (k.key_hash IS NULL AND k.key = ?)
            """,
            (candidate_hash, clean_key),
        )
        row = cursor.fetchone()
        if not row:
            return None, "INVALID"

        d = dict(row)
        stored_hash = d.get("key_hash")
        if stored_hash:
            if not hmac.compare_digest(stored_hash, candidate_hash):
                return None, "INVALID"
        else:
            if not hmac.compare_digest(d.get("raw_col") or "", clean_key):
                return None, "INVALID"

        if d.get("revoked_at") or d.get("closed_at"):
            return None, "INVALID"

        if (d.get("tier") or "").upper() != "BUSINESS" or not int(d.get("has_api_access") or 0):
            return None, "TIER_REQUIRED"

        now = datetime.utcnow().isoformat()
        if d.get("key_id"):
            cursor.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, d["key_id"]))
        else:
            cursor.execute("UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?", (now, candidate_hash))
        conn.commit()

        return {
            "id": d["id"],
            "name": d["name"],
            "email": d["email"],
            "company": d["company"],
            "origin_zip": d["origin_zip"],
            "tier": d["tier"],
            "role": d.get("role") or "USER",
            "auth_via": "api_key",
            "api_key_id": d.get("key_id") or candidate_hash[:16],
        }, None
    finally:
        conn.close()


def validate_api_key(api_key: str):
    """Validates an API key and returns associated active BUSINESS user, or None."""
    user, err = authenticate_api_key(api_key)
    if err is not None:
        return None
    return user

def create_support_ticket(
    email: str,
    subject: str,
    message: str,
    user_id: Optional[str] = None,
    category: str = "GENERAL",
    browser_info: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a new user support ticket."""
    import uuid
    ticket_id = f"tkt_{uuid.uuid4().hex[:10]}"
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO support_tickets (id, user_id, email, subject, message, category, browser_info, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
    """, (ticket_id, user_id, email.strip(), subject.strip(), message.strip(), category, browser_info or "", now))
    conn.commit()
    conn.close()

    # Trigger automated transactional emails (user confirmation + support inbox alert)
    try:
        from services.email_service import (
            send_support_ticket_confirmation,
            send_support_ticket_admin_notification,
        )
        send_support_ticket_confirmation(
            to_email=email.strip(),
            ticket_id=ticket_id,
            subject=subject.strip(),
            message=message.strip(),
            category=category,
        )
        send_support_ticket_admin_notification(
            ticket_id=ticket_id,
            user_email=email.strip(),
            category=category,
            subject=subject.strip(),
            message=message.strip(),
            browser_info=browser_info,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(f"Could not dispatch support ticket emails for {ticket_id}: {exc}")

    return {
        "status": "success",
        "ticket_id": ticket_id,
        "message": "Support ticket created successfully. Our dispatch engineering desk will respond within 4 business hours."
    }

def list_support_tickets(user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Lists support tickets for admin or specific tenant."""
    conn = get_connection()
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT * FROM support_tickets WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    else:
        cursor.execute("SELECT * FROM support_tickets ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_system_notification(
    user_id: str,
    title: str,
    message: str,
    alert_type: str = "INFO",
    link_url: Optional[str] = None
) -> str:
    """Inserts a system notification for a tenant."""
    import uuid
    notif_id = f"notif_{uuid.uuid4().hex[:10]}"
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO system_notifications (id, user_id, title, message, alert_type, link_url, is_read, created_at)
    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    """, (notif_id, user_id, title.strip(), message.strip(), alert_type, link_url, now))
    conn.commit()
    conn.close()
    return notif_id

def list_system_notifications(user_id: str, limit: int = 20) -> Dict[str, Any]:
    """Retrieves notifications and unread count for a tenant."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM system_notifications 
    WHERE user_id = ? 
    ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    
    cursor.execute("""
    SELECT count(*) as unread_count FROM system_notifications
    WHERE user_id = ? AND is_read = 0
    """, (user_id,))
    unread = cursor.fetchone()["unread_count"]
    conn.close()
    return {
        "notifications": [dict(r) for r in rows],
        "unread_count": int(unread)
    }

def mark_system_notification_read(notification_id: str, user_id: str) -> bool:
    """Marks a single notification as read."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE system_notifications SET is_read = 1
    WHERE id = ? AND user_id = ?
    """, (notification_id, user_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def mark_all_system_notifications_read(user_id: str) -> int:
    """Marks all notifications as read for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE system_notifications SET is_read = 1
    WHERE user_id = ? AND is_read = 0
    """, (user_id,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def save_proposal_quote_item(user_id: str, proposal: Dict[str, Any], quote_data: Optional[Dict[str, Any]] = None) -> str:
    """
    Saves a client proposal quote to the persistent quote history table (quote_items).
    Ensures a client proposals batch exists for the user and persists the proposal quote across logins.
    """
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.utcnow().isoformat()
    
    batch_id = f"qb_proposals_{user_id}"
    cursor.execute("SELECT id FROM quote_batches WHERE id = ?", (batch_id,))
    if not cursor.fetchone():
        cursor.execute("""
        INSERT INTO quote_batches (id, user_id, filename, total_rows, processed_rows, created_at)
        VALUES (?, ?, 'Client Proposals', 0, 0, ?)
        """, (batch_id, user_id, now_iso))
        
    proposal_id = proposal.get("proposal_id") or f"PROP-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"
    qd = quote_data or {}
    
    origin = proposal.get("shipment", {}).get("origin") or qd.get("origin") or "TORONTO, ON"
    dest = proposal.get("shipment", {}).get("destination") or qd.get("destination") or "MONTREAL, QC"
    weight = float(proposal.get("shipment", {}).get("billable_weight") or qd.get("weight_lbs") or 1000.0)
    
    carrier = (proposal.get("carrier", {}).get("name") or 
               qd.get("carrier_name") or 
               proposal.get("broker", {}).get("company") or 
               "Standard Carrier")
    service = (proposal.get("carrier", {}).get("service") or 
               qd.get("service_name") or 
               proposal.get("shipment", {}).get("service_level") or 
               "Standard Road LTL")
               
    base_rate = float(proposal.get("pricing", {}).get("wholesale_cost") or 
                      proposal.get("pricing", {}).get("client_base_freight") or 
                      qd.get("base_rate") or 0.0)
    markup_pct = float(proposal.get("pricing", {}).get("effective_markup_pct") or 
                       qd.get("markup_pct") or 15.0)
    final_rate = float(proposal.get("pricing", {}).get("client_total") or 
                       qd.get("final_total") or 0.0)
                       
    sheet_id = qd.get("sheet_id") or proposal.get("sheet_id")
    source_coord = (
        qd.get("source_coordinate") or 
        qd.get("source_cell") or 
        qd.get("coordinate") or 
        proposal.get("source_coordinate") or 
        proposal.get("source_cell")
    )
    if source_coord:
        coordinate = str(source_coord)
    else:
        coordinate = f"Proposal • {proposal_id}"
    
    # Extract formula, skid_count, and calculation trace
    formula = (
        qd.get("formula") or 
        proposal.get("formula") or 
        proposal.get("pricing", {}).get("formula")
    )
    skid_count = (
        qd.get("skid_count") or 
        proposal.get("skid_count") or 
        proposal.get("shipment", {}).get("skid_count")
    )
    calculation_trace = (
        qd.get("calculation_trace") or 
        qd.get("calculation_work") or 
        proposal.get("calculation_trace") or 
        proposal.get("calculation_work") or 
        proposal.get("trace_steps")
    )
    if calculation_trace and not isinstance(calculation_trace, str):
        import json
        calculation_trace_str = json.dumps(calculation_trace)
    else:
        calculation_trace_str = calculation_trace or ""

    if not formula:
        margin = round(final_rate - base_rate, 2)
        if skid_count and skid_count > 0:
            per_skid = round(base_rate / max(1, skid_count), 2)
            formula = f"Base Freight: {skid_count} skid{'s' if skid_count != 1 else ''} x ${per_skid:.2f} = ${base_rate:.2f} | Markup (+{markup_pct}%): +${margin:.2f} → Final Quoted Rate: ${final_rate:.2f}"
        else:
            formula = f"Base Freight: ${base_rate:.2f} (Weight: {weight:,.0f} lbs) | Markup (+{markup_pct}%): +${margin:.2f} → Final Quoted Rate: ${final_rate:.2f}"

    # Ensure required columns exist on quote_items table
    cursor.execute("PRAGMA table_info(quote_items)")
    qi_cols = [r["name"] for r in cursor.fetchall()]
    if "sheet_id" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN sheet_id TEXT")
    if "formula" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN formula TEXT")
    if "calculation_trace" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN calculation_trace TEXT")
    if "skid_count" not in qi_cols:
        cursor.execute("ALTER TABLE quote_items ADD COLUMN skid_count INTEGER")

    cursor.execute("""
    INSERT OR REPLACE INTO quote_items 
    (id, batch_id, row_num, origin_zip, dest_zip, weight_lbs, carrier, service, base_rate, markup_pct, final_rate, coordinate, created_at, sheet_id, formula, calculation_trace, skid_count)
    VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        proposal_id,
        batch_id,
        origin,
        dest,
        weight,
        carrier,
        service,
        base_rate,
        markup_pct,
        final_rate,
        coordinate,
        now_iso,
        sheet_id,
        formula,
        calculation_trace_str,
        skid_count
    ))
    
    # Update total_rows and processed_rows on batch
    cursor.execute("SELECT count(*) as count FROM quote_items WHERE batch_id = ?", (batch_id,))
    cnt = cursor.fetchone()["count"]
    cursor.execute("UPDATE quote_batches SET total_rows = ?, processed_rows = ? WHERE id = ?", (cnt, cnt, batch_id))
    
    conn.commit()
    conn.close()
    return proposal_id


def export_user_data(user_id: str) -> Dict[str, Any]:
    """
    PIPEDA Principle 9 (Individual Access) & Law 25 Data Portability:
    Returns a complete, structured export of all Account Data and Customer Data
    belonging to the specified user_id. Never includes any other tenant's data.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, name, email, company, origin_zip, origin_address, phone, tier,
           email_verified, email_verified_at,
           marketing_opt_in, marketing_consent_at, terms_accepted_at, created_at
    FROM users WHERE id = ?
    """, (user_id,))
    user_row = cursor.fetchone()
    account_profile = dict(user_row) if user_row else {"id": user_id}

    cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
    settings_row = cursor.fetchone()
    settings = dict(settings_row) if settings_row else {}

    cursor.execute("SELECT * FROM marketing_consent_logs WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    marketing_consents = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM organization_members WHERE organization_id = ? ORDER BY created_at DESC", (user_id,))
    team_seats = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM quote_batches WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    batches = [dict(r) for r in cursor.fetchall()]

    batch_ids = [b["id"] for b in batches]
    quote_items: List[Dict[str, Any]] = []
    if batch_ids:
        placeholders = ",".join("?" for _ in batch_ids)
        cursor.execute(f"SELECT * FROM quote_items WHERE batch_id IN ({placeholders}) ORDER BY created_at DESC", batch_ids)
        quote_items = [dict(r) for r in cursor.fetchall()]

    rate_sheets: List[Dict[str, Any]] = []
    weight_breaks: List[Dict[str, Any]] = []
    minimums: List[Dict[str, Any]] = []
    surcharges: List[Dict[str, Any]] = []
    audit_logs: List[Dict[str, Any]] = []

    def _table_exists(name: str) -> bool:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return cursor.fetchone() is not None

    api_key_summaries: List[Dict[str, Any]] = []
    webhook_endpoints_export: List[Dict[str, Any]] = []
    webhook_deliveries_export: List[Dict[str, Any]] = []

    if _table_exists("api_keys"):
        _ensure_api_keys_schema(cursor)
        cursor.execute(
            "SELECT id, name, key_prefix, created_at, last_used_at, revoked_at FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        api_key_summaries = [dict(r) for r in cursor.fetchall()]
    if _table_exists("webhook_endpoints"):
        cursor.execute(
            "SELECT id, url, description, events, is_active, created_at FROM webhook_endpoints WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        webhook_endpoints_export = [dict(r) for r in cursor.fetchall()]
    if _table_exists("webhook_deliveries"):
        cursor.execute(
            "SELECT id, endpoint_id, event_type, batch_id, response_status, success, attempt_count, error_message, created_at FROM webhook_deliveries WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        webhook_deliveries_export = [dict(r) for r in cursor.fetchall()]
    if _table_exists("ql_rate_sheets"):
        cursor.execute("SELECT * FROM ql_rate_sheets WHERE user_id = ?", (user_id,))
        rate_sheets = [dict(r) for r in cursor.fetchall()]
    if _table_exists("ql_weight_breaks"):
        cursor.execute("SELECT * FROM ql_weight_breaks WHERE user_id = ?", (user_id,))
        weight_breaks = [dict(r) for r in cursor.fetchall()]
    if _table_exists("ql_carrier_minimums"):
        cursor.execute("SELECT * FROM ql_carrier_minimums WHERE user_id = ?", (user_id,))
        minimums = [dict(r) for r in cursor.fetchall()]
    if _table_exists("ql_carrier_surcharges"):
        cursor.execute("SELECT * FROM ql_carrier_surcharges WHERE user_id = ?", (user_id,))
        surcharges = [dict(r) for r in cursor.fetchall()]
    if _table_exists("ql_quote_audit_logs"):
        cursor.execute("SELECT * FROM ql_quote_audit_logs WHERE user_id = ?", (user_id,))
        audit_logs = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "export_metadata": {
            "platform": "Quotelytics Inc.",
            "standard": "PIPEDA Principle 9 Individual Access & Data Portability",
            "data_residency": "CA_CENTRAL_WHC",
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
        },
        "account_data": {
            "profile": account_profile,
            "settings": settings,
            "team_seats": team_seats,
            "api_keys": api_key_summaries,
            "webhook_endpoints": webhook_endpoints_export,
            "marketing_consent_history": marketing_consents,
        },
        "customer_data": {
            "rate_sheets": rate_sheets,
            "weight_breaks": weight_breaks,
            "carrier_minimums": minimums,
            "carrier_surcharges": surcharges,
            "quote_batches": batches,
            "quote_items": quote_items,
            "quote_audit_logs": audit_logs,
            "webhook_deliveries": webhook_deliveries_export,
        },
    }


def delete_user_account_data(user_id: str, immediate_purge: bool = True) -> Dict[str, Any]:
    """
    PIPEDA Principle 5 & §10 Deletion Rights:
    Deletes a user's Account Data and Customer Data (uploaded rate sheets, cells, zones,
    weight breaks, minimums, surcharges, quote batches/items, audit logs, sessions, API keys,
    webhooks, notifications, and team seats).
    Preserves anonymised/statutory CASL consent audit records as required by law (§8).
    """
    conn = get_connection()
    cursor = conn.cursor()
    deleted_counts: Dict[str, int] = {}

    def _table_exists(name: str) -> bool:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return cursor.fetchone() is not None

    # 1. Always revoke active sessions, one-time auth tokens, API keys & webhooks immediately
    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    deleted_counts["sessions"] = cursor.rowcount
    if _table_exists("auth_tokens"):
        cursor.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        deleted_counts["auth_tokens"] = cursor.rowcount
    cursor.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
    deleted_counts["api_keys"] = cursor.rowcount
    if _table_exists("webhook_deliveries"):
        cursor.execute("DELETE FROM webhook_deliveries WHERE user_id = ?", (user_id,))
        deleted_counts["webhook_deliveries"] = cursor.rowcount
    if _table_exists("webhook_endpoints"):
        cursor.execute("DELETE FROM webhook_endpoints WHERE user_id = ?", (user_id,))
        deleted_counts["webhook_endpoints"] = cursor.rowcount
    if _table_exists("proposal_drafts"):
        cursor.execute("DELETE FROM proposal_drafts WHERE user_id = ?", (user_id,))
        deleted_counts["proposal_drafts"] = cursor.rowcount

    if not immediate_purge:
        now_iso = datetime.utcnow().isoformat()
        cursor.execute("UPDATE users SET closed_at = ?, marketing_opt_in = 0 WHERE id = ?", (now_iso, user_id))
        conn.commit()
        conn.close()
        return {
            "status": "scheduled_for_deletion",
            "user_id": user_id,
            "closed_at": now_iso,
            "purge_after_days": 30,
            "deleted_counts": deleted_counts,
        }

    # 2. Purge Customer Data across all tables
    for rs_table in (
        "ql_rate_sheet_cells",
        "ql_carrier_zones",
        "ql_weight_breaks",
        "ql_carrier_minimums",
        "ql_carrier_surcharges",
        "ql_quote_audit_logs",
        "ql_rate_sheets",
        "ql_fuel_settings",
    ):
        if _table_exists(rs_table):
            cursor.execute(f"DELETE FROM {rs_table} WHERE user_id = ?", (user_id,))
            deleted_counts[rs_table] = cursor.rowcount

    cursor.execute("SELECT id FROM quote_batches WHERE user_id = ?", (user_id,))
    batch_ids = [r["id"] for r in cursor.fetchall()]
    if batch_ids:
        placeholders = ",".join("?" for _ in batch_ids)
        cursor.execute(f"DELETE FROM quote_items WHERE batch_id IN ({placeholders})", batch_ids)
        deleted_counts["quote_items"] = cursor.rowcount
    else:
        deleted_counts["quote_items"] = 0

    cursor.execute("DELETE FROM quote_batches WHERE user_id = ?", (user_id,))
    deleted_counts["quote_batches"] = cursor.rowcount

    for aux_table, col in (
        ("organization_members", "organization_id"),
        ("bottleneck_events", "user_id"),
        ("system_notifications", "user_id"),
        ("support_tickets", "user_id"),
        ("user_settings", "user_id"),
    ):
        if _table_exists(aux_table):
            cursor.execute(f"DELETE FROM {aux_table} WHERE {col} = ?", (user_id,))
            deleted_counts[aux_table] = cursor.rowcount

    for fs_table in ("failsafe_jobs", "failsafe_saved_mappings"):
        if _table_exists(fs_table):
            cursor.execute(f"DELETE FROM {fs_table} WHERE user_id = ? OR tenant_id = ?", (user_id, user_id))
            deleted_counts[fs_table] = cursor.rowcount

    # Record withdrawal on marketing_consent_logs (retained for 3 years per CASL §8)
    if _table_exists("marketing_consent_logs"):
        cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
        u_row = cursor.fetchone()
        if u_row:
            cursor.execute("""
            INSERT INTO marketing_consent_logs (
                id, user_id, email, consented, consent_type, form_version, ip_address, user_agent, created_at
            ) VALUES (?, ?, ?, 0, 'ACCOUNT_DELETED_WITHDRAWAL', 'v2026.10', '', '', ?)
            """, (f"mc_{uuid.uuid4().hex[:12]}", user_id, u_row["email"], datetime.utcnow().isoformat()))

    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    deleted_counts["users"] = cursor.rowcount

    conn.commit()
    conn.close()
    return {
        "status": "deleted",
        "user_id": user_id,
        "deleted_at": datetime.utcnow().isoformat() + "Z",
        "deleted_counts": deleted_counts,
    }


def enforce_retention_policies(
    closed_account_days: int = 30,
    security_log_days: int = 90,
    marketing_consent_years: int = 3,
    scratch_file_days: int = 1,
) -> Dict[str, int]:
    """
    PIPEDA Principle 5 & Privacy Policy §8 Automated Retention Enforcement:
      - Purges expired sessions immediately
      - Permanently deletes soft-closed accounts older than `closed_account_days` (default 30 days)
      - Purges operational/security telemetry older than `security_log_days` (default 90 days)
      - Purges withdrawn marketing consent logs older than `marketing_consent_years` (default 3 years)
      - Cleans temporary staged upload files in `scratch/` older than `scratch_file_days`
    """
    now = datetime.utcnow()
    now_iso = now.isoformat()
    closed_cutoff = (now - timedelta(days=closed_account_days)).isoformat()
    log_cutoff = (now - timedelta(days=security_log_days)).isoformat()
    consent_cutoff = (now - timedelta(days=365 * marketing_consent_years)).isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    summary: Dict[str, int] = {}

    def _table_exists(name: str) -> bool:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return cursor.fetchone() is not None

    # 1. Expired sessions & one-time auth tokens
    if _table_exists("sessions"):
        cursor.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso,))
        summary["expired_sessions_purged"] = cursor.rowcount
    if _table_exists("auth_tokens"):
        cursor.execute("DELETE FROM auth_tokens WHERE expires_at < ? OR used_at IS NOT NULL", (now_iso,))
        summary["expired_auth_tokens_purged"] = cursor.rowcount

    # 2. Closed accounts past 30-day reactivation window
    closed_user_ids: List[str] = []
    if _table_exists("users"):
        cursor.execute(
            "SELECT id FROM users WHERE closed_at IS NOT NULL AND closed_at != '' AND closed_at < ?",
            (closed_cutoff,)
        )
        closed_user_ids = [r["id"] for r in cursor.fetchall()]

    # 3. Security & operational logs older than 90 days
    if _table_exists("bottleneck_events"):
        cursor.execute("DELETE FROM bottleneck_events WHERE created_at < ?", (log_cutoff,))
        summary["security_logs_purged"] = cursor.rowcount
    else:
        summary["security_logs_purged"] = 0

    # 4. Withdrawn CASL consent logs older than 3 years
    if _table_exists("marketing_consent_logs"):
        cursor.execute(
            "DELETE FROM marketing_consent_logs WHERE consented = 0 AND created_at < ?",
            (consent_cutoff,)
        )
        summary["expired_consent_logs_purged"] = cursor.rowcount
    else:
        summary["expired_consent_logs_purged"] = 0

    conn.commit()
    conn.close()

    for uid in closed_user_ids:
        delete_user_account_data(uid, immediate_purge=True)
    summary["closed_accounts_purged"] = len(closed_user_ids)

    # 5. Scratch directory staged upload cleanup
    scratch_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scratch")
    scratch_purged = 0
    if os.path.isdir(scratch_dir):
        cutoff_ts = (now - timedelta(days=scratch_file_days)).timestamp()
        for fname in os.listdir(scratch_dir):
            if fname.startswith("staged_upload_") or fname.startswith("Reformatted_Rate_Sheet_"):
                fpath = os.path.join(scratch_dir, fname)
                try:
                    if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff_ts:
                        os.remove(fpath)
                        scratch_purged += 1
                except OSError as exc:
                    logger.debug("Could not purge scratch file %s: %s", fpath, exc)
    summary["scratch_files_purged"] = scratch_purged
    return summary


def update_user_billing_subscription(
    user_id: str,
    plan: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    subscription_status: Optional[str] = None,
    current_period_end: Optional[str] = None,
    cancel_at_period_end: Optional[int] = None,
    seat_count: Optional[int] = None,
) -> bool:
    """Updates Stripe subscription fields and active tier for a user account."""
    if not user_id:
        return False
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []
    if plan is not None:
        valid_tier = plan.upper()
        if valid_tier in ("FREE", "PRO", "TEAM", "BUSINESS"):
            updates.append("tier = ?")
            params.append(valid_tier)
    if stripe_customer_id is not None:
        updates.append("stripe_customer_id = ?")
        params.append(stripe_customer_id)
    if stripe_subscription_id is not None:
        updates.append("stripe_subscription_id = ?")
        params.append(stripe_subscription_id)
    if subscription_status is not None:
        updates.append("subscription_status = ?")
        params.append(subscription_status.lower())
    if current_period_end is not None:
        updates.append("current_period_end = ?")
        params.append(current_period_end)
    if cancel_at_period_end is not None:
        updates.append("cancel_at_period_end = ?")
        params.append(int(bool(cancel_at_period_end)))
    if seat_count is not None and seat_count > 0:
        updates.append("seat_count = ?")
        params.append(int(seat_count))

    if not updates:
        conn.close()
        return True

    params.append(user_id)
    sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(sql, tuple(params))
    conn.commit()
    conn.close()
    return True


def get_user_by_stripe_customer_id(stripe_customer_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves user record by their Stripe customer ID."""
    if not stripe_customer_id:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE stripe_customer_id = ?", (stripe_customer_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_billing_info(user_id: str) -> Dict[str, Any]:
    """Retrieves full subscription and billing status for a user."""
    if not user_id:
        return {}
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.id, u.email, u.company, u.tier, u.stripe_customer_id, u.stripe_subscription_id,
           u.subscription_status, u.seat_count, u.current_period_end, u.cancel_at_period_end,
           t.name AS tier_name, t.price_monthly, t.max_sheets, t.max_quotes_per_month, t.has_api_access
    FROM users u
    LEFT JOIN subscription_tiers t ON u.tier = t.id
    WHERE u.id = ?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {}
    d = dict(row)
    d["cancel_at_period_end"] = bool(d.get("cancel_at_period_end", 0))
    d["has_api_access"] = bool(d.get("has_api_access", 0))
    return d


def save_active_proposal(user_id: str, proposal: Dict[str, Any]) -> None:
    """Persists the user's active client proposal draft in SQLite."""
    if not user_id:
        return
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO proposal_drafts (user_id, proposal_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                proposal_json = excluded.proposal_json,
                updated_at = excluded.updated_at
            """,
            (user_id, json.dumps(proposal), datetime.utcnow().isoformat()),
        )
        conn.commit()


def get_active_proposal(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves the user's active client proposal draft from SQLite, if any."""
    if not user_id:
        return None
    with db_session() as conn:
        row = conn.execute(
            "SELECT proposal_json FROM proposal_drafts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["proposal_json"])
        except Exception as exc:
            logger.warning("Corrupt proposal draft for user %s: %s", user_id, exc)
            return None


def clear_active_proposal(user_id: str) -> bool:
    """Clears the user's active client proposal draft from SQLite."""
    if not user_id:
        return False
    with db_session() as conn:
        cur = conn.execute("DELETE FROM proposal_drafts WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


# ==============================================================================
# Custom Keyword Definitions for AI Sheet Mapping (Scoped by user_id)
# ==============================================================================

def _ensure_keyword_definitions_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS user_keyword_definitions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        keyword TEXT NOT NULL,
        normalized_keyword TEXT NOT NULL,
        definition_text TEXT NOT NULL,
        parsed_category TEXT NOT NULL,
        parsed_rule_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        UNIQUE (user_id, normalized_keyword)
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_kw_defs_user ON user_keyword_definitions (user_id)")


def list_user_keyword_definitions(user_id: Optional[str]) -> List[Dict[str, Any]]:
    """Returns all saved keyword definitions for a user, ordered by keyword."""
    if not user_id:
        return []
    with db_session() as conn:
        _ensure_keyword_definitions_table(conn)
        rows = conn.execute(
            """
            SELECT id, user_id, keyword, normalized_keyword, definition_text,
                   parsed_category, parsed_rule_json, created_at, updated_at
            FROM user_keyword_definitions
            WHERE user_id = ?
            ORDER BY normalized_keyword ASC
            """,
            (str(user_id),),
        ).fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                rule_obj = json.loads(d.get("parsed_rule_json") or "{}")
            except Exception:
                rule_obj = {}
            d["parsed_rule"] = rule_obj
            d["badge_label"] = rule_obj.get("badge_label") or d.get("parsed_category", "AI Mapping Rule")
            results.append(d)
        return results


def get_user_keyword_map(user_id: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """
    Returns an O(1) lookup dictionary keyed by normalized_keyword (uppercase, trimmed)
    for use in break_header_parser, app/detect.py, and QuotelyticsExtractor.
    """
    if not user_id:
        return {}
    items = list_user_keyword_definitions(user_id)
    return {item["normalized_keyword"]: item for item in items if item.get("normalized_keyword")}


def upsert_user_keyword_definition(
    user_id: str,
    keyword: str,
    definition_text: str,
) -> Dict[str, Any]:
    """
    Interprets and persists a user's keyword definition (creating or updating on conflict).
    """
    from services.keyword_definition_service import (
        interpret_keyword_definition,
        normalize_keyword_key,
    )

    if not user_id:
        raise ValueError("user_id is required")
    kw_clean = str(keyword or "").strip()
    def_clean = str(definition_text or "").strip()
    norm_kw = normalize_keyword_key(kw_clean)
    if not norm_kw:
        raise ValueError("Keyword cannot be empty.")
    if not def_clean:
        raise ValueError("Definition text cannot be empty.")

    interpreted = interpret_keyword_definition(kw_clean, def_clean)
    parsed_category = interpreted["parsed_category"]
    parsed_rule = interpreted["parsed_rule"]
    now_iso = datetime.utcnow().isoformat()

    with db_session() as conn:
        _ensure_keyword_definitions_table(conn)
        existing = conn.execute(
            "SELECT id, created_at FROM user_keyword_definitions WHERE user_id = ? AND normalized_keyword = ?",
            (str(user_id), norm_kw),
        ).fetchone()

        if existing:
            kw_id = existing["id"]
            created_at = existing["created_at"]
            conn.execute(
                """
                UPDATE user_keyword_definitions
                SET keyword = ?, definition_text = ?, parsed_category = ?, parsed_rule_json = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    kw_clean,
                    def_clean,
                    parsed_category,
                    json.dumps(parsed_rule),
                    now_iso,
                    kw_id,
                    str(user_id),
                ),
            )
        else:
            kw_id = f"ql_kw_{uuid.uuid4().hex[:12]}"
            created_at = now_iso
            conn.execute(
                """
                INSERT INTO user_keyword_definitions (
                    id, user_id, keyword, normalized_keyword, definition_text,
                    parsed_category, parsed_rule_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kw_id,
                    str(user_id),
                    kw_clean,
                    norm_kw,
                    def_clean,
                    parsed_category,
                    json.dumps(parsed_rule),
                    created_at,
                    now_iso,
                ),
            )
        conn.commit()

    return {
        "id": kw_id,
        "user_id": str(user_id),
        "keyword": kw_clean,
        "normalized_keyword": norm_kw,
        "definition_text": def_clean,
        "parsed_category": parsed_category,
        "parsed_rule": parsed_rule,
        "badge_label": interpreted["badge_label"],
        "created_at": created_at,
        "updated_at": now_iso,
    }


def delete_user_keyword_definition(user_id: str, keyword_id: str) -> bool:
    """Deletes a keyword definition strictly owned by user_id."""
    if not user_id or not keyword_id:
        return False
    with db_session() as conn:
        _ensure_keyword_definitions_table(conn)
        cur = conn.execute(
            "DELETE FROM user_keyword_definitions WHERE id = ? AND user_id = ?",
            (str(keyword_id), str(user_id)),
        )
        conn.commit()
        return cur.rowcount > 0


if __name__ == "__main__":
    init_db()
    print("Database & Tiers initialized.")
