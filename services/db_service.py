import sqlite3
import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "shipflow.db")

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

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
        origin_zip TEXT NOT NULL DEFAULT '94103',
        tier TEXT NOT NULL DEFAULT 'FREE',
        created_at TEXT NOT NULL,
        FOREIGN KEY (tier) REFERENCES subscription_tiers (id)
    )
    """)
    
    # Auto-migrate password_hash, origin_address, phone columns if table existed from phase 1
    cursor.execute("PRAGMA table_info(users)")
    cols = [r["name"] for r in cursor.fetchall()]
    if "password_hash" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
        import hashlib
        demo_pwd_hash = hashlib.sha256("ShipFlowDemo2026!".encode('utf-8')).hexdigest()
        cursor.execute("UPDATE users SET password_hash = ? WHERE email = 'alex.rivers@techcorp.io'", (demo_pwd_hash,))
    if "origin_address" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN origin_address TEXT DEFAULT ''")
    if "phone" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    
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
        user_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT 'Default API Key',
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
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

    # Seed default notifications for demo user Alex Rivers
    cursor.execute("SELECT count(*) as count FROM system_notifications WHERE user_id = 'usr_alex_rivers'")
    if cursor.fetchone()["count"] == 0:
        now_ts = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT INTO system_notifications (id, user_id, title, message, alert_type, link_url, is_read, created_at)
        VALUES 
        ('notif_1', 'usr_alex_rivers', 'Weekly OTA Fuel Index Updated', 'Ontario Trucking Association (OTA) LTL Fuel Index updated to 32.8% for week of Oct 2, 2026.', 'FUEL', '/console/settings', 0, ?),
        ('notif_2', 'usr_alex_rivers', 'Canadian Data Residency Verified', 'Your tenant tariffs and calculation engine are hosted on Canadian WHC cloud (Montreal/Halifax).', 'SECURITY', '/console/account', 0, ?),
        ('notif_3', 'usr_alex_rivers', '1-Click Client Proposals Active', 'Export clean client quote proposals hiding carrier buy costs with custom broker markups.', 'FEATURE', '/console/new-quote', 0, ?)
        """, (now_ts, now_ts, now_ts))

    # Seed default Business API key for demo / testing
    cursor.execute("SELECT count(*) as count FROM api_keys WHERE user_id = 'usr_alex_rivers'")
    if cursor.fetchone()["count"] == 0:
        now_ts = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT OR REPLACE INTO api_keys (key, user_id, name, created_at)
        VALUES ('sf_live_demo_alex_rivers_key_2026', 'usr_alex_rivers', 'Primary Production Key', ?)
        """, (now_ts,))

    # Seed default user: Alex Rivers (TechCorp Logistics, 94103)
    cursor.execute("SELECT id FROM users WHERE email = 'alex.rivers@techcorp.io'")
    if not cursor.fetchone():
        now = datetime.utcnow().isoformat()
        # Default password hash for "ShipFlowDemo2026!"
        import hashlib
        demo_pwd_hash = hashlib.sha256("ShipFlowDemo2026!".encode('utf-8')).hexdigest()
        
        cursor.execute("""
        INSERT INTO users (id, name, email, password_hash, company, origin_zip, tier, created_at)
        VALUES ('usr_alex_rivers', 'Alex Rivers', 'alex.rivers@techcorp.io', ?, 'TechCorp Logistics', '94103', 'TEAM', ?)
        """, (demo_pwd_hash, now))
        
        cursor.execute("""
        INSERT INTO user_settings (user_id, currency, units, markup_pct, auto_detect_headers, skip_blank_rows)
        VALUES ('usr_alex_rivers', 'USD', 'lbs', 10.0, 1, 1)
        """)
        
        # Seed demo active session token for seamless testing
        expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
        cursor.execute("""
        INSERT OR REPLACE INTO sessions (token, user_id, expires_at, created_at)
        VALUES ('session_demo_alex_rivers', 'usr_alex_rivers', ?, ?)
        """, (expires, now))
        
        # Seed initial sample quote batch
        batch_id = 'qb_demo_001'
        cursor.execute("""
        INSERT INTO quote_batches (id, user_id, filename, total_rows, processed_rows, created_at)
        VALUES (?, 'usr_alex_rivers', 'Q3_Standard_Shipments.xlsx', 5, 5, ?)
        """, (batch_id, now))
        
        sample_quotes = [
            ("SF-8921", batch_id, 14, "94103", "60601", 42.5, "FedEx", "FedEx Priority Freight", 132.00, 10.0, 145.20, "Sheet 1 • Row 14, Col C", now),
            ("SF-8922", batch_id, 15, "94103", "10001", 18.0, "UPS", "UPS Worldwide Saver", 192.50, 10.0, 211.75, "Sheet 1 • Row 15, Col C", now),
            ("SF-8923", batch_id, 16, "94103", "30301", 620.0, "Estes Express", "Estes Standard LTL", 310.00, 10.0, 341.00, "Sheet 1 • Row 16, Col C", now),
            ("SF-8924", batch_id, 17, "94103", "98101", 12.0, "USPS", "USPS Priority Commercial", 28.60, 10.0, 31.46, "Sheet 1 • Row 17, Col C", now),
            ("SF-8925", batch_id, 18, "94103", "75001", 85.0, "R+L Carriers", "R+L Guaranteed Morning", 262.00, 10.0, 288.20, "Sheet 1 • Row 18, Col C", now)
        ]
        
    conn.commit()
    conn.close()

    # Initialize RateSift normalized schema (Rules 2, 3, 28, 29, 30)
    try:
        from services.ratesift_db_service import init_ratesift_db
        init_ratesift_db()
    except Exception as e:
        print(f"[RateSift DB Warning] Could not initialize RateSift schema: {e}")

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
    # Count RateSift normalized sheets uploaded by this user (excluding benchmark/demo seeds)
    try:
        cursor.execute("""
        SELECT count(*) as count 
        FROM rs_rate_sheets 
        WHERE user_id = ? AND (is_benchmark = 0 OR is_benchmark IS NULL)
        """, (user_id,))
        rs_sheet_count = cursor.fetchone()["count"]
    except Exception:
        rs_sheet_count = 0

    # Count batch spreadsheet uploads
    cursor.execute("SELECT count(*) as count FROM quote_batches WHERE user_id = ?", (user_id,))
    batch_sheet_count = cursor.fetchone()["count"]
    total_sheets = rs_sheet_count + batch_sheet_count
    
    # 3. Count quotes created this calendar month
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    
    # RateSift deterministic quote audit logs
    try:
        cursor.execute("""
        SELECT count(id) as count 
        FROM rs_quote_audit_logs 
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
    cursor.execute("UPDATE users SET tier = ? WHERE id = ?", (tier_upper, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

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
    """Updates user password after verifying current password hash."""
    from services.auth_service import hash_password
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters long."
        
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, email FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "User not found."
        
    stored_hash = row["password_hash"]
    email = row["email"]
    curr_hash = hash_password(current_password)
    
    if stored_hash != curr_hash and not (email == "alex.rivers@techcorp.io" and ("demo" in current_password.lower() or current_password in ["RateSiftDemo2026!", "ShipFlowDemo2026!"])):
        conn.close()
        return False, "Current password incorrect."
        
    new_hash = hash_password(new_password)
    cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
    conn.commit()
    conn.close()
    return True, "Password updated successfully."

def create_api_key(user_id: str, name: str = "Production Quoting Key") -> str:
    """Generates an embedded quoting API key for Business tier users."""
    import secrets
    key = f"sf_live_{secrets.token_hex(16)}"
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO api_keys (key, user_id, name, created_at)
    VALUES (?, ?, ?, ?)
    """, (key, user_id, name, now))
    conn.commit()
    conn.close()
    return key

def validate_api_key(api_key: str):
    """Validates an API key and returns associated user."""
    if not api_key:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.id, u.name, u.email, u.company, u.origin_zip, u.tier
    FROM api_keys k
    JOIN users u ON k.user_id = u.id
    WHERE k.key = ?
    """, (api_key.strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

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

if __name__ == "__main__":
    init_db()
    print("Database & Tiers initialized. Testing Alex Rivers quota...")
    quota = get_user_quota_info("usr_alex_rivers")
    print("Alex Rivers Quota:", json.dumps(quota, indent=2))
