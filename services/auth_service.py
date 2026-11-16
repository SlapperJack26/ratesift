import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from services.db_service import get_connection

logger = logging.getLogger("quotelytics.auth")

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
    _ARGON2_HASHER = PasswordHasher()
except ImportError:  # pragma: no cover
    _ARGON2_HASHER = None


def hash_password(password: str) -> str:
    """Computes a salted Argon2id cryptographic hash of the password."""
    if _ARGON2_HASHER is not None:
        return _ARGON2_HASHER.hash(password)
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310000)
    return f"pbkdf2_sha256$310000${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> Tuple[bool, bool]:
    """
    Verifies a plaintext password against a stored password hash.
    Returns (is_valid, needs_rehash).
    Legacy unsalted SHA-256 hashes are verified in constant time and flagged for automatic Argon2id upgrade.
    """
    if not stored_hash:
        return False, False

    if stored_hash.startswith("$argon2") and _ARGON2_HASHER is not None:
        try:
            _ARGON2_HASHER.verify(stored_hash, password)
            return True, bool(_ARGON2_HASHER.check_needs_rehash(stored_hash))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False

    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iter_str, salt, digest_hex = stored_hash.split("$", 3)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iter_str))
            ok = hmac.compare_digest(dk.hex(), digest_hex)
            return ok, bool(ok and _ARGON2_HASHER is not None)
        except Exception:
            return False, False

    # Legacy unsalted SHA-256 fallback -> flag for immediate rehash to Argon2id
    legacy_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
    if hmac.compare_digest(stored_hash, legacy_sha256):
        return True, True

    return False, False


def record_marketing_consent(
    user_id: Optional[str],
    email: str,
    consented: bool,
    consent_type: str = "SIGNUP_OPT_IN",
    form_version: str = "v2026.10",
    ip_address: str = "",
    user_agent: str = ""
) -> str:
    """Records an immutable CASL marketing consent / withdrawal event."""
    consent_id = f"mc_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO marketing_consent_logs (
        id, user_id, email, consented, consent_type, form_version, ip_address, user_agent, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        consent_id,
        user_id,
        (email or "").strip().lower(),
        1 if consented else 0,
        consent_type,
        form_version,
        ip_address or "",
        user_agent or "",
        now,
    ))
    if user_id:
        cursor.execute("""
        UPDATE users
        SET marketing_opt_in = ?, marketing_consent_at = ?
        WHERE id = ?
        """, (1 if consented else 0, now, user_id))
    conn.commit()
    conn.close()
    return consent_id


def create_session(user_id: str) -> str:
    """Creates a new session token valid for 30 days."""
    token = f"s_{uuid.uuid4().hex}"
    expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()
    now = datetime.utcnow().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO sessions (token, user_id, expires_at, created_at)
    VALUES (?, ?, ?, ?)
    """, (token, user_id, expires_at, now))
    conn.commit()
    conn.close()
    return token


def validate_session_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Validates session token and returns active user if not expired or closed."""
    if not token:
        return None

    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()

    cursor.execute("""
    SELECT u.id, u.name, u.email, u.company, u.origin_zip, u.tier, u.role, u.closed_at, u.email_verified
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.token = ? AND s.expires_at > ?
    """, (token, now))

    row = cursor.fetchone()
    conn.close()
    if row:
        data = dict(row)
        if data.get("closed_at"):
            return None
        data.pop("closed_at", None)
        data["role"] = data.get("role") or "USER"
        data["email_verified"] = bool(data.get("email_verified", 0))
        return data
    return None


def revoke_session(token: Optional[str]):
    """Revokes / destroys a session token upon logout."""
    if not token:
        return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def authenticate_and_create_session(email: str, password: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Validates user credentials using salted Argon2id hashes (with automatic rehash of legacy SHA-256).
    If valid, generates a new session token.
    """
    email_clean = (email or "").strip().lower()
    if not email_clean or not password:
        return None, None

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email_clean,))
    user_row = cursor.fetchone()

    if user_row:
        user_dict = dict(user_row)
        if user_dict.get("closed_at"):
            conn.close()
            return None, None
        stored_hash = user_dict.get("password_hash", "")
        is_valid, needs_rehash = verify_password(password, stored_hash)
        if is_valid:
            if needs_rehash:
                try:
                    cursor.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ?",
                        (hash_password(password), user_dict["id"])
                    )
                    conn.commit()
                except Exception as exc:
                    logger.warning("Password rehash upgrade failed for user %s: %s", user_dict["id"], exc)
            conn.close()
            user_dict["role"] = user_dict.get("role") or "USER"
            token = create_session(user_dict["id"])
            return user_dict, token

    conn.close()
    return None, None


def register_and_create_session(
    name: str,
    email: str,
    company: str,
    origin_zip: str = "TORONTO, ON",
    password: str = "",
    marketing_opt_in: bool = False,
    ip_address: str = "",
    user_agent: str = "",
    form_version: str = "v2026.10",
) -> Tuple[Dict[str, Any], str]:
    """
    Registers a new user, hashes password with salted Argon2id, logs CASL marketing consent,
    assigns Free Starter tier and USER role, and returns user info with a live session token.
    """
    if not password or len(password) < 10:
        raise ValueError("A password of at least 10 characters is required.")

    conn = get_connection()
    cursor = conn.cursor()
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    pwd_hash = hash_password(password)
    email_clean = email.strip().lower()

    try:
        cursor.execute("""
        INSERT INTO users (
            id, name, email, password_hash, company, origin_zip, tier, role, created_at,
            marketing_opt_in, marketing_consent_at, terms_accepted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'FREE', 'USER', ?, ?, ?, ?)
        """, (
            user_id,
            name.strip(),
            email_clean,
            pwd_hash,
            company.strip(),
            origin_zip.strip(),
            now,
            1 if marketing_opt_in else 0,
            now if marketing_opt_in else None,
            now,
        ))

        cursor.execute("""
        INSERT INTO user_settings (user_id, currency, units, markup_pct, auto_detect_headers, skip_blank_rows)
        VALUES (?, 'CAD', 'lbs', 10.0, 1, 1)
        """, (user_id,))

        conn.commit()
        user_data = {
            "id": user_id,
            "name": name.strip(),
            "email": email_clean,
            "company": company.strip(),
            "origin_zip": origin_zip.strip(),
            "tier": "FREE",
            "role": "USER",
            "email_verified": False,
            "marketing_opt_in": bool(marketing_opt_in),
        }
    except Exception:
        cursor.execute("SELECT id, name, email, company, origin_zip, tier, role, email_verified, marketing_opt_in FROM users WHERE email = ?", (email_clean,))
        existing = cursor.fetchone()
        user_data = dict(existing)
        user_data["role"] = user_data.get("role") or "USER"
        user_data["email_verified"] = bool(user_data.get("email_verified", 0))

    conn.close()

    try:
        record_marketing_consent(
            user_id=user_data["id"],
            email=email_clean,
            consented=bool(marketing_opt_in),
            consent_type="SIGNUP_OPT_IN" if marketing_opt_in else "SIGNUP_DECLINED",
            form_version=form_version,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as exc:
        logger.warning("Failed to record marketing consent for %s: %s", user_data["id"], exc)

    try:
        if not user_data.get("email_verified"):
            verify_tok = create_email_verification_token(user_data["id"])
            from services.email_service import send_email_verification_email
            send_email_verification_email(email_clean, user_data.get("name", ""), verify_tok)
    except Exception as exc:
        logger.warning("Failed to send verification email for %s: %s", user_data["id"], exc)

    token = create_session(user_data["id"])
    return user_data, token


def _hash_auth_token(raw_token: str) -> str:
    """Computes SHA-256 hex digest of a one-time auth token so raw tokens are never stored in DB."""
    return hashlib.sha256((raw_token or "").strip().encode("utf-8")).hexdigest()


def create_password_reset_token(email: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """
    Generates a single-use 1-hour password reset token for an active user account.
    Invalidates any prior unused PASSWORD_RESET tokens for that user.
    Returns (user_dict, raw_token) or None if email does not match an active account.
    """
    email_clean = (email or "").strip().lower()
    if not email_clean:
        return None

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, closed_at FROM users WHERE email = ?", (email_clean,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    user_dict = dict(row)
    if user_dict.get("closed_at"):
        conn.close()
        return None

    now_dt = datetime.utcnow()
    now_iso = now_dt.isoformat()
    expires_iso = (now_dt + timedelta(hours=1)).isoformat()
    raw_token = f"rst_{secrets.token_urlsafe(32)}"
    token_hash = _hash_auth_token(raw_token)
    tok_id = f"at_{uuid.uuid4().hex[:12]}"

    cursor.execute(
        "DELETE FROM auth_tokens WHERE user_id = ? AND token_type = 'PASSWORD_RESET' AND used_at IS NULL",
        (user_dict["id"],),
    )
    cursor.execute("""
    INSERT INTO auth_tokens (id, token_hash, user_id, token_type, expires_at, used_at, created_at)
    VALUES (?, ?, ?, 'PASSWORD_RESET', ?, NULL, ?)
    """, (tok_id, token_hash, user_dict["id"], expires_iso, now_iso))
    conn.commit()
    conn.close()
    return user_dict, raw_token


def reset_password_with_token(raw_token: str, new_password: str) -> Tuple[bool, str]:
    """
    Validates a single-use PASSWORD_RESET token, enforces the 10-character password policy,
    updates the user's password hash with salted Argon2id, marks the token used, and revokes
    all active sessions for that user.
    """
    if not raw_token or not raw_token.strip():
        return False, "Invalid or expired password reset token."
    if not new_password or len(new_password) < 10:
        return False, "New password must be at least 10 characters long."

    token_hash = _hash_auth_token(raw_token)
    now_iso = datetime.utcnow().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, user_id, expires_at, used_at
    FROM auth_tokens
    WHERE token_hash = ? AND token_type = 'PASSWORD_RESET'
    """, (token_hash,))
    tok_row = cursor.fetchone()

    if not tok_row:
        conn.close()
        return False, "Invalid or expired password reset token."

    if tok_row["used_at"] is not None or tok_row["expires_at"] <= now_iso:
        conn.close()
        return False, "Invalid or expired password reset token."

    user_id = tok_row["user_id"]
    new_hash = hash_password(new_password)

    cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
    cursor.execute("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (now_iso, tok_row["id"]))
    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True, "Password has been reset successfully. Please log in with your new password."


def create_email_verification_token(user_id: str) -> str:
    """
    Generates a single-use 24-hour EMAIL_VERIFY token for the specified user_id,
    invalidating any prior unused verification tokens.
    """
    now_dt = datetime.utcnow()
    now_iso = now_dt.isoformat()
    expires_iso = (now_dt + timedelta(hours=24)).isoformat()
    raw_token = f"ver_{secrets.token_urlsafe(32)}"
    token_hash = _hash_auth_token(raw_token)
    tok_id = f"at_{uuid.uuid4().hex[:12]}"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM auth_tokens WHERE user_id = ? AND token_type = 'EMAIL_VERIFY' AND used_at IS NULL",
        (user_id,),
    )
    cursor.execute("""
    INSERT INTO auth_tokens (id, token_hash, user_id, token_type, expires_at, used_at, created_at)
    VALUES (?, ?, ?, 'EMAIL_VERIFY', ?, NULL, ?)
    """, (tok_id, token_hash, user_id, expires_iso, now_iso))
    conn.commit()
    conn.close()
    return raw_token


def verify_email_with_token(raw_token: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validates a single-use EMAIL_VERIFY token and marks the user's email address as verified.
    Returns (success, message, user_id).
    """
    if not raw_token or not raw_token.strip():
        return False, "Invalid or expired email verification token.", None

    token_hash = _hash_auth_token(raw_token)
    now_iso = datetime.utcnow().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, user_id, expires_at, used_at
    FROM auth_tokens
    WHERE token_hash = ? AND token_type = 'EMAIL_VERIFY'
    """, (token_hash,))
    tok_row = cursor.fetchone()

    if not tok_row:
        conn.close()
        return False, "Invalid or expired email verification token.", None

    if tok_row["used_at"] is not None or tok_row["expires_at"] <= now_iso:
        conn.close()
        return False, "Invalid or expired email verification token.", None

    user_id = tok_row["user_id"]
    cursor.execute(
        "UPDATE users SET email_verified = 1, email_verified_at = ? WHERE id = ?",
        (now_iso, user_id),
    )
    cursor.execute("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (now_iso, tok_row["id"]))
    conn.commit()
    conn.close()
    return True, "Email address verified successfully.", user_id


def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Helper for authenticating a user directly."""
    user, _ = authenticate_and_create_session(email, password)
    return user


def get_user_profile(user_id: str) -> Dict[str, Any]:
    """Retrieves user profile and current settings for an authenticated user_id."""
    if not user_id:
        return {}
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.id, u.name, u.email, u.company, u.origin_zip, u.origin_address, u.phone, u.tier, u.role,
           u.email_verified, u.email_verified_at,
           u.marketing_opt_in, u.marketing_consent_at,
           s.currency, s.units, s.markup_pct, s.markup_mode, s.fsc_passthrough, s.auto_detect_headers, s.skip_blank_rows
    FROM users u
    LEFT JOIN user_settings s ON u.id = s.user_id
    WHERE u.id = ?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        d = dict(row)
        d["marketing_opt_in"] = bool(d.get("marketing_opt_in", 0))
        d["email_verified"] = bool(d.get("email_verified", 0))
        d["role"] = d.get("role") or "USER"
        return d

    return {}
