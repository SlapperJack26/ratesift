import sqlite3
import os
import json
from datetime import datetime, timedelta

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
        has_api_access INTEGER NOT NULL DEFAULT 0
    )
    """)
    
    # Seed standard tiers
    cursor.executemany("""
    INSERT OR REPLACE INTO subscription_tiers (id, name, price_monthly, max_sheets, max_quotes_per_month, has_api_access)
    VALUES (?, ?, ?, ?, ?, ?)
    """, [
        ("FREE", "Free Starter", 0.0, 3, 50, 0),
        ("PRO", "Broker Pro", 79.0, 10, 2500, 0),
        ("TEAM", "Broker Team", 199.0, -1, 15000, 0),
        ("BUSINESS", "Business", -1.0, -1, -1, 1)  # -1 represents custom / get quote
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
    
    # Auto-migrate password_hash column if table existed from phase 1
    cursor.execute("PRAGMA table_info(users)")
    cols = [r["name"] for r in cursor.fetchall()]
    if "password_hash" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
        import hashlib
        demo_pwd_hash = hashlib.sha256("ShipFlowDemo2026!".encode('utf-8')).hexdigest()
        cursor.execute("UPDATE users SET password_hash = ? WHERE email = 'alex.rivers@techcorp.io'", (demo_pwd_hash,))
    
    # 3. User Settings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id TEXT PRIMARY KEY,
        currency TEXT NOT NULL DEFAULT 'USD',
        units TEXT NOT NULL DEFAULT 'lbs',
        markup_pct REAL NOT NULL DEFAULT 10.0,
        auto_detect_headers INTEGER NOT NULL DEFAULT 1,
        skip_blank_rows INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
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
        FOREIGN KEY (batch_id) REFERENCES quote_batches (id)
    )
    """)
    
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
        VALUES ('usr_alex_rivers', 'Alex Rivers', 'alex.rivers@techcorp.io', ?, 'TechCorp Logistics', '94103', 'FREE', ?)
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
        from services.seed_canadian_benchmarks import seed_canadian_benchmarks_for_user
        seed_canadian_benchmarks_for_user("usr_alex_rivers")
    except Exception as e:
        print(f"[RateSift DB Warning] Could not initialize RateSift schema or seed benchmarks: {e}")

def get_user_quota_info(user_id: str):
    """
    Computes tier limits, monthly quote usage, and uploaded rate sheet count.
    Enforces Free Starter restrictions (1 sheet, 50 monthly quotes).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Fetch user & tier details
    cursor.execute("""
    SELECT u.id, u.name, u.email, u.company, u.tier, t.name as tier_name,
           t.max_sheets, t.max_quotes_per_month, t.has_api_access
    FROM users u
    JOIN subscription_tiers t ON u.tier = t.id
    WHERE u.id = ?
    """, (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
        
    user_info = dict(row)
    
    # 2. Count uploaded sheets (batches)
    cursor.execute("SELECT count(*) as sheet_count FROM quote_batches WHERE user_id = ?", (user_id,))
    sheet_count = cursor.fetchone()["sheet_count"]
    
    # 3. Count quotes created this calendar month
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    cursor.execute("""
    SELECT count(qi.id) as quote_count
    FROM quote_items qi
    JOIN quote_batches qb ON qi.batch_id = qb.id
    WHERE qb.user_id = ? AND qi.created_at >= ?
    """, (user_id, month_start))
    monthly_quotes_used = cursor.fetchone()["quote_count"]
    
    conn.close()
    
    max_sheets = user_info["max_sheets"]
    max_quotes = user_info["max_quotes_per_month"]
    
    sheets_remaining = max(0, max_sheets - sheet_count) if max_sheets > 0 else 999999
    quotes_remaining = max(0, max_quotes - monthly_quotes_used) if max_quotes > 0 else 999999
    
    return {
        "user_id": user_id,
        "tier": user_info["tier"],
        "tier_name": user_info["tier_name"],
        "max_sheets": max_sheets,
        "sheets_uploaded": sheet_count,
        "sheets_remaining": sheets_remaining,
        "max_quotes_per_month": max_quotes,
        "monthly_quotes_used": monthly_quotes_used,
        "quotes_remaining": quotes_remaining,
        "has_api_access": bool(user_info["has_api_access"]),
        "can_upload_sheet": (sheet_count < max_sheets) if max_sheets > 0 else True,
        "can_quote_rows": (monthly_quotes_used < max_quotes) if max_quotes > 0 else True
    }

def update_user_account(user_id: str, name: str, company: str, origin_zip: str):
    """Updates user profile information."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE users
    SET name = ?, company = ?, origin_zip = ?
    WHERE id = ?
    """, (name.strip(), company.strip(), origin_zip.strip(), user_id))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Profile updated successfully."}

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

if __name__ == "__main__":
    init_db()
    print("Database & Tiers initialized. Testing Alex Rivers quota...")
    quota = get_user_quota_info("usr_alex_rivers")
    print("Alex Rivers Quota:", json.dumps(quota, indent=2))
