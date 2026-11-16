"""
Business Tier Batch Calculation Webhook Service for Quotelytics Inc.
Provides SSRF-hardened outbound URL/IP validation, HMAC-SHA256 payload signing,
endpoint CRUD helpers, and background delivery logging with injectable transport.
"""
from datetime import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from services.db_service import get_connection

# Injectable transport for deterministic unit/integration testing without live sockets:
# Callable[[url, body_bytes, headers_dict, timeout_sec], Tuple[http_status, error_str]]
webhook_transport: Optional[Callable[[str, bytes, Dict[str, str], float], Tuple[int, str]]] = None

# Injectable DNS resolver for deterministic SSRF testing:
# Callable[[hostname, port], List[Tuple]] matching socket.getaddrinfo
dns_resolver: Optional[Callable[..., List[Any]]] = None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Blocks HTTP 3xx redirects so outbound webhooks cannot be redirected to internal/SSRF targets."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, f"Webhook redirects are prohibited (HTTP {code})", headers, fp
        )


def _ensure_webhook_tables(cursor) -> None:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS webhook_endpoints (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        url TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        secret TEXT NOT NULL,
        events TEXT NOT NULL DEFAULT 'batch.quote.completed',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)
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
        created_at TEXT NOT NULL
    )
    """)


def _is_forbidden_ip(ip_str: str) -> bool:
    ip_obj = ipaddress.ip_address(ip_str)
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        ip_obj = ip_obj.ipv4_mapped
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def validate_webhook_target_url(url: str, allow_http_dev: Optional[bool] = None) -> str:
    """
    Validates a webhook destination URL and resolves DNS to block SSRF against
    loopback, private RFC1918, link-local / cloud metadata (169.254.169.254), and reserved ranges.
    """
    clean_url = (url or "").strip()
    if not clean_url or len(clean_url) > 1024:
        raise ValueError("Webhook URL must be a valid non-empty URL (max 1024 characters).")

    parsed = urllib.parse.urlparse(clean_url)
    scheme = (parsed.scheme or "").lower()
    is_prod = os.getenv("APP_ENV", "").strip().lower() == "production"
    http_ok = (not is_prod) if allow_http_dev is None else bool(allow_http_dev)

    if scheme == "https":
        default_port = 443
    elif scheme == "http" and http_ok:
        default_port = 80
    elif scheme == "http":
        raise ValueError("Webhook URL must use HTTPS in production.")
    else:
        raise ValueError("Webhook URL scheme must be https://.")

    if parsed.username or parsed.password:
        raise ValueError("Webhook URL must not include embedded credentials.")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname or hostname in ("localhost", "localhost.localdomain"):
        raise ValueError("Webhook URL cannot target localhost or internal hosts.")

    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise ValueError("Webhook URL contains an invalid port.") from exc

    # Direct IP literal check before DNS lookup
    try:
        if _is_forbidden_ip(hostname):
            raise ValueError("Webhook URL cannot target private, loopback, or metadata IP addresses.")
        return clean_url
    except ValueError as exc:
        if "cannot target" in str(exc):
            raise
        # Not an IP literal; proceed to DNS resolution

    resolver_fn = dns_resolver or socket.getaddrinfo
    try:
        addr_infos = resolver_fn(hostname, port, type=socket.SOCK_STREAM)
    except Exception as exc:
        raise ValueError(f"Could not resolve webhook hostname '{hostname}'.") from exc

    if not addr_infos:
        raise ValueError(f"Webhook hostname '{hostname}' resolved to no addresses.")

    for info in addr_infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        if _is_forbidden_ip(ip_str):
            raise ValueError("Webhook URL resolves to a restricted private, loopback, or link-local IP address.")

    return clean_url


def sign_webhook_payload(secret: str, timestamp: int, raw_body: bytes) -> str:
    """Computes X-Quotelytics-Signature header value: t=<timestamp>,v1=<hmac_sha256>."""
    signed_input = f"{timestamp}.".encode("utf-8") + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_input, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def create_webhook_endpoint(
    user_id: str,
    url: str,
    description: str = "",
    events: str = "batch.quote.completed",
    max_endpoints: int = 10,
) -> Dict[str, Any]:
    """Validates URL (SSRF check) and registers a new Business tier webhook endpoint."""
    validated_url = validate_webhook_target_url(url)
    clean_desc = (description or "").strip()[:120]
    clean_events = (events or "batch.quote.completed").strip()[:120]
    endpoint_id = f"whe_{secrets.token_hex(6)}"
    signing_secret = f"whsec_{secrets.token_hex(16)}"
    now = datetime.utcnow().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_webhook_tables(cursor)
        cursor.execute(
            "SELECT count(*) AS cnt FROM webhook_endpoints WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )
        if cursor.fetchone()["cnt"] >= max_endpoints:
            raise ValueError(f"Maximum limit of {max_endpoints} active webhook endpoints reached.")

        cursor.execute(
            """
            INSERT INTO webhook_endpoints (id, user_id, url, description, secret, events, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (endpoint_id, user_id, validated_url, clean_desc, signing_secret, clean_events, now),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "id": endpoint_id,
        "url": validated_url,
        "description": clean_desc,
        "secret": signing_secret,
        "secret_preview": f"{signing_secret[:12]}...",
        "events": clean_events,
        "is_active": True,
        "created_at": now,
    }


def list_webhook_endpoints(user_id: str) -> Dict[str, Any]:
    """Returns registered webhook endpoints (masked secrets) and recent delivery receipts."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_webhook_tables(cursor)
        cursor.execute(
            """
            SELECT id, url, description, secret, events, is_active, created_at
            FROM webhook_endpoints
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        endpoints = []
        for r in cursor.fetchall():
            sec = r["secret"] or ""
            endpoints.append({
                "id": r["id"],
                "url": r["url"],
                "description": r["description"],
                "secret_preview": f"{sec[:12]}..." if sec else "whsec_***",
                "events": r["events"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"],
            })

        cursor.execute(
            """
            SELECT id, endpoint_id, event_type, batch_id, response_status, success, attempt_count, error_message, created_at
            FROM webhook_deliveries
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 15
            """,
            (user_id,),
        )
        deliveries = [
            {
                "id": d["id"],
                "endpoint_id": d["endpoint_id"],
                "event_type": d["event_type"],
                "batch_id": d["batch_id"],
                "response_status": d["response_status"],
                "success": bool(d["success"]),
                "attempt_count": d["attempt_count"],
                "error_message": d["error_message"],
                "created_at": d["created_at"],
            }
            for d in cursor.fetchall()
        ]
        return {"endpoints": endpoints, "deliveries": deliveries}
    finally:
        conn.close()


def delete_webhook_endpoint(user_id: str, endpoint_id: str) -> bool:
    """Deletes a webhook endpoint and its delivery logs for the owning tenant."""
    if not endpoint_id:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_webhook_tables(cursor)
        clean_id = endpoint_id.strip()
        cursor.execute(
            "DELETE FROM webhook_deliveries WHERE endpoint_id = ? AND user_id = ?",
            (clean_id, user_id),
        )
        cursor.execute(
            "DELETE FROM webhook_endpoints WHERE id = ? AND user_id = ?",
            (clean_id, user_id),
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def _send_single_http_post(url: str, body_bytes: bytes, headers: Dict[str, str], timeout: float = 5.0) -> Tuple[int, str]:
    """Executes one SSRF-revalidated outbound webhook POST without following redirects."""
    if webhook_transport is not None:
        return webhook_transport(url, body_bytes, headers, timeout)

    validate_webhook_target_url(url)
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(url=url, data=body_bytes, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=timeout) as resp:
            status_code = int(getattr(resp, "status", None) or resp.getcode() or 200)
            return status_code, ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def dispatch_batch_webhook_event(
    user_id: str,
    event_type: str,
    batch_id: str,
    payload_data: Dict[str, Any],
    target_endpoint_id: Optional[str] = None,
    max_attempts: int = 3,
) -> List[Dict[str, Any]]:
    """
    Signs and dispatches an event payload to all active webhook endpoints for user_id
    (or a specific target_endpoint_id for test pings), recording delivery receipts.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_webhook_tables(cursor)
        if target_endpoint_id:
            cursor.execute(
                "SELECT id, url, secret, events FROM webhook_endpoints WHERE id = ? AND user_id = ? AND is_active = 1",
                (target_endpoint_id, user_id),
            )
        else:
            cursor.execute(
                "SELECT id, url, secret, events FROM webhook_endpoints WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
        targets = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

    if not targets:
        return []

    envelope = {
        "event": event_type,
        "batch_id": batch_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "data": payload_data,
    }
    raw_body = json.dumps(envelope, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")

    receipts: List[Dict[str, Any]] = []
    for ep in targets:
        ep_events = [e.strip() for e in (ep.get("events") or "").split(",") if e.strip()]
        if event_type != "batch.quote.test" and ep_events and event_type not in ep_events and "*" not in ep_events:
            continue

        delivery_id = f"whd_{secrets.token_hex(6)}"
        ts = int(time.time())
        sig_header = sign_webhook_payload(ep["secret"], ts, raw_body)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Quotelytics-Webhook/2.1",
            "X-Quotelytics-Event": event_type,
            "X-Quotelytics-Delivery-Id": delivery_id,
            "X-Quotelytics-Signature": sig_header,
        }

        status_code = 0
        err_msg = ""
        attempts_used = 0
        succeeded = False
        effective_max = 1 if event_type == "batch.quote.test" else max(1, max_attempts)

        for attempt_idx in range(effective_max):
            attempts_used = attempt_idx + 1
            try:
                status_code, err_msg = _send_single_http_post(ep["url"], raw_body, headers, timeout=5.0)
            except Exception as exc:
                status_code = 0
                err_msg = str(exc)

            if 200 <= status_code < 300:
                succeeded = True
                err_msg = ""
                break

            # Do not retry deterministic 4xx client rejections (except 429)
            if 400 <= status_code < 500 and status_code != 429:
                break

            if attempt_idx + 1 < effective_max and webhook_transport is None:
                time.sleep(0.2 * (attempt_idx + 1))

        now_iso = datetime.utcnow().isoformat()
        conn = get_connection()
        cursor = conn.cursor()
        try:
            _ensure_webhook_tables(cursor)
            cursor.execute(
                """
                INSERT INTO webhook_deliveries (
                    id, endpoint_id, user_id, event_type, batch_id,
                    response_status, success, attempt_count, error_message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery_id,
                    ep["id"],
                    user_id,
                    event_type,
                    batch_id,
                    status_code if status_code > 0 else None,
                    1 if succeeded else 0,
                    attempts_used,
                    err_msg[:300] if err_msg else None,
                    now_iso,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        receipts.append({
            "delivery_id": delivery_id,
            "endpoint_id": ep["id"],
            "event_type": event_type,
            "batch_id": batch_id,
            "response_status": status_code if status_code > 0 else None,
            "success": succeeded,
            "attempt_count": attempts_used,
            "error_message": err_msg or None,
            "created_at": now_iso,
        })

    return receipts
