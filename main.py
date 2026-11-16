import os
import io
import json
import uuid
import re
import time
import email.utils
import openpyxl
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response, Request, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel

# Injectable clock for RFC 8594 Sunset & RFC 9745 Deprecation testing
sunset_clock = time.time

from app.output_safety import sanitize_workbook
from services.quotelytics_excel_reformatter import (
    analyze_excel_sheet,
    build_reformatted_excel_workbook,
    SCRATCH_DIR
)


from services.db_service import (
    init_db,
    get_connection,
    get_user_quota_info,
    save_active_proposal,
    get_active_proposal,
    clear_active_proposal,
)
from services.parser_service import parse_excel_rate_sheet
from services.rating_service import calculate_batch_quotes
from services.auth_service import (
    authenticate_and_create_session,
    register_and_create_session,
    validate_session_token,
    revoke_session,
    get_user_profile
)

import logging
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("quotelytics.app")

BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Ensure database schema exists at import time for TestClient/CLI callers (idempotent)
init_db()

from app.main import router as failsafe_router, TokenBucketRateLimiter, verify_csrf, lifespan as failsafe_lifespan


@asynccontextmanager
async def app_lifespan(fastapi_app: FastAPI):
    """Run startup DB retention policies and the failsafe TTL sweeper."""
    try:
        from services.db_service import enforce_retention_policies
        enforce_retention_policies()
    except Exception as exc:
        logger.warning("PIPEDA retention enforcement failed at startup: %s", exc)
    async with failsafe_lifespan(fastapi_app):
        yield


from fastapi.openapi.docs import get_swagger_ui_html

app = FastAPI(
    title="Quotelytics Quoting API",
    description="Automated batch shipping rate calculation engine from Excel spreadsheets (.xlsx, .xls). Strictly quoting; no booking or tracking numbers.",
    version="1.0.0",
    docs_url=None,
    redoc_url=None if os.getenv("APP_ENV", "").lower() == "production" else "/redoc",
    openapi_url=None if os.getenv("APP_ENV", "").lower() == "production" else "/openapi.json",
    lifespan=app_lifespan,
)

@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    if os.getenv("APP_ENV", "").lower() == "production":
        raise HTTPException(status_code=404, detail="Not Found")
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Quotelytics Quoting API — Swagger UI",
        swagger_js_url="/static/vendor/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/vendor/swagger-ui/swagger-ui.css",
        swagger_favicon_url="/static/images/quotelytics-logo.jpg",
    )

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
_allowed_origins = (
    [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
    if _allowed_origins_env
    else ["http://127.0.0.1:8000", "http://localhost:8000"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(failsafe_router)
app.include_router(failsafe_router, prefix="/api/failsafe")

from routers.pages import router as pages_router
from routers.geo_and_agent import router as geo_agent_router
app.include_router(pages_router)
app.include_router(geo_agent_router)

api_key_rate_limiter = TokenBucketRateLimiter(rate_per_minute=120.0, burst_capacity=40.0)


class _StructuredAPIError(Exception):
    """Structured JSON API error with explicit error code, detail message, and optional headers."""

    def __init__(self, status_code: int, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}


@app.exception_handler(_StructuredAPIError)
async def _handle_structured_api_error(request: Request, exc: _StructuredAPIError):
    return JSONResponse(status_code=exc.status_code, content=exc.payload, headers=exc.headers)


from routers.deps import (
    SESSION_COOKIE_NAMES,
    should_set_secure_cookie as _should_set_secure_cookie,
    set_session_cookies as _set_session_cookies,
    clear_session_cookies as _clear_session_cookies,
    get_current_user_from_request,
    require_user,
    ensure_dev_or_admin as _ensure_dev_or_admin,
    serve_template,
)


def require_quoting_user(request: Request, require_business_session: bool = False) -> dict:
    """
    Least-privilege authentication for deterministic quoting endpoints.
    - When X-API-Key header is supplied: authenticates strictly via SHA-256 hashed key,
      enforces active BUSINESS tier & non-revoked status, and applies per-key rate limiting.
      Never silently falls back to browser cookies if X-API-Key was supplied.
    - Otherwise: authenticates via session cookie or Bearer session token.
    """
    if "x-api-key" in request.headers:
        from services.db_service import authenticate_api_key
        raw_key = request.headers.get("X-API-Key", "")
        user, err = authenticate_api_key(raw_key)
        if err == "TIER_REQUIRED":
            raise _StructuredAPIError(
                status_code=403,
                payload={
                    "error": "E_API_TIER_REQUIRED",
                    "detail": "Active Business tier subscription required for API key usage.",
                },
            )
        if err is not None or not user:
            raise _StructuredAPIError(
                status_code=401,
                payload={
                    "error": "E_API_KEY_INVALID",
                    "detail": "Unauthorized: Invalid or revoked X-API-Key.",
                },
            )
        if not api_key_rate_limiter.check_and_consume(user["api_key_id"]):
            raise _StructuredAPIError(
                status_code=429,
                payload={
                    "error": "E_RATE_LIMITED",
                    "detail": "API key rate limit exceeded (120 requests/minute). Please retry shortly.",
                },
                headers={"Retry-After": "1"},
            )
        return user

    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if require_business_session and (user.get("tier") or "").upper() != "BUSINESS":
        raise _StructuredAPIError(
            status_code=403,
            payload={
                "error": "E_API_TIER_REQUIRED",
                "detail": "Embedded Batch Quoting API requires an active Business tier subscription.",
            },
        )
    return user


def require_admin_user(request: Request) -> dict:
    """Requires a valid authenticated ADMIN session; raises 401 if logged out, 403 if not ADMIN."""
    user = require_user(request)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Administrator privileges required.")
    return user


_LOGIN_WINDOW_SECONDS = 900
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_FAILED_BY_EMAIL: Dict[str, List[float]] = {}
_LOGIN_FAILED_BY_IP: Dict[str, List[float]] = {}


def clear_login_throttle() -> None:
    """Clears in-memory login rate-limiting state."""
    _LOGIN_FAILED_BY_EMAIL.clear()
    _LOGIN_FAILED_BY_IP.clear()

# ==========================================
# REST API ENDPOINTS
# ==========================================

@app.post("/api/auth/login", tags=["Authentication"])
def api_login(request: Request, response: Response, email: str = Form(...), password: str = Form(...)):
    """Authenticates credentials with 5-attempt/15-min throttling and issues a session cookie."""
    import time
    now_ts = time.time()
    cutoff = now_ts - _LOGIN_WINDOW_SECONDS
    email_key = (email or "").strip().lower()
    ip_key = request.client.host if request.client and request.client.host else "unknown"

    email_attempts = [t for t in _LOGIN_FAILED_BY_EMAIL.get(email_key, []) if t > cutoff]
    ip_attempts = [t for t in _LOGIN_FAILED_BY_IP.get(ip_key, []) if t > cutoff]
    _LOGIN_FAILED_BY_EMAIL[email_key] = email_attempts
    _LOGIN_FAILED_BY_IP[ip_key] = ip_attempts

    if len(email_attempts) >= _LOGIN_MAX_ATTEMPTS or len(ip_attempts) >= _LOGIN_MAX_ATTEMPTS:
        oldest = min(email_attempts + ip_attempts) if (email_attempts or ip_attempts) else now_ts
        retry_after = max(1, int(_LOGIN_WINDOW_SECONDS - (now_ts - oldest)))
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please wait 15 minutes before trying again.",
            headers={"Retry-After": str(retry_after)},
        )

    user, token = authenticate_and_create_session(email, password)
    if not user or not token:
        _LOGIN_FAILED_BY_EMAIL.setdefault(email_key, []).append(now_ts)
        _LOGIN_FAILED_BY_IP.setdefault(ip_key, []).append(now_ts)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    _LOGIN_FAILED_BY_EMAIL.pop(email_key, None)
    _LOGIN_FAILED_BY_IP.pop(ip_key, None)

    _set_session_cookies(response, token, request)
    return {
        "status": "success",
        "user": user,
        "token": token,
        "redirect": "/console/new-quote"
    }

@app.post("/api/auth/register", tags=["Authentication"])
def api_register(
    request: Request,
    response: Response,
    name: str = Form(...),
    email: str = Form(...),
    company: str = Form(...),
    origin_zip: str = Form("TORONTO, ON"),
    password: str = Form(...),
    terms_accepted: bool = Form(True),
    marketing_opt_in: bool = Form(False),
    form_version: str = Form("v2026.10"),
):
    """Registers account on Free Starter tier with role='USER', records CASL consent, and establishes session."""
    if not terms_accepted:
        raise HTTPException(status_code=400, detail="You must accept the Terms of Service and Privacy Policy to register.")
    if not password or len(password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters long.")
    ip_addr = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    user, token = register_and_create_session(
        name=name,
        email=email,
        company=company,
        origin_zip=origin_zip,
        password=password,
        marketing_opt_in=bool(marketing_opt_in),
        ip_address=ip_addr,
        user_agent=user_agent,
        form_version=form_version,
    )
    _set_session_cookies(response, token, request)
    return {
        "status": "success",
        "user": user,
        "token": token,
        "redirect": "/console/new-quote"
    }

@app.get("/api/auth/logout", tags=["Authentication"])
def api_logout(request: Request, response: Response):
    """Revokes session and redirects to public landing page."""
    token = request.cookies.get("quotelytics_session")
    if token:
        revoke_session(token)
    resp = RedirectResponse(url="/", status_code=303)
    _clear_session_cookies(resp)
    return resp

@app.get("/api/auth/status", tags=["Authentication"])
def api_auth_status(request: Request):
    """Returns currently authenticated user session or null."""
    user = get_current_user_from_request(request)
    return {"authenticated": bool(user), "user": user}


_RESET_MAX_ATTEMPTS = 5
_RESET_FAILED_BY_IP: Dict[str, List[float]] = {}
_RESET_FAILED_BY_EMAIL: Dict[str, List[float]] = {}


def clear_password_reset_throttle() -> None:
    """Clears in-memory password reset rate-limiting state."""
    _RESET_FAILED_BY_IP.clear()
    _RESET_FAILED_BY_EMAIL.clear()


@app.post("/api/auth/forgot-password", tags=["Authentication"])
async def api_forgot_password(request: Request):
    """
    Issues a 1-hour single-use password reset token and sends a reset link via email.
    Always returns HTTP 200 for valid email syntax (unless rate-limited) to prevent email enumeration.
    """
    import time
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
    else:
        form = await request.form()
        email = str(form.get("email", "")).strip().lower()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    now_ts = time.time()
    cutoff = now_ts - _LOGIN_WINDOW_SECONDS
    ip_key = request.client.host if request.client and request.client.host else "unknown"

    email_reqs = [t for t in _RESET_FAILED_BY_EMAIL.get(email, []) if t > cutoff]
    ip_reqs = [t for t in _RESET_FAILED_BY_IP.get(ip_key, []) if t > cutoff]
    _RESET_FAILED_BY_EMAIL[email] = email_reqs
    _RESET_FAILED_BY_IP[ip_key] = ip_reqs

    if len(email_reqs) >= _RESET_MAX_ATTEMPTS or len(ip_reqs) >= _RESET_MAX_ATTEMPTS:
        oldest = min(email_reqs + ip_reqs) if (email_reqs or ip_reqs) else now_ts
        retry_after = max(1, int(_LOGIN_WINDOW_SECONDS - (now_ts - oldest)))
        raise HTTPException(
            status_code=429,
            detail="Too many password reset requests. Please wait 15 minutes before trying again.",
            headers={"Retry-After": str(retry_after)},
        )

    _RESET_FAILED_BY_EMAIL.setdefault(email, []).append(now_ts)
    _RESET_FAILED_BY_IP.setdefault(ip_key, []).append(now_ts)

    from services.auth_service import create_password_reset_token
    from services.email_service import send_password_reset_email

    res = create_password_reset_token(email)
    if res is not None:
        user_dict, raw_token = res
        send_password_reset_email(user_dict["email"], user_dict.get("name", ""), raw_token)

    return {
        "status": "success",
        "message": "If an account exists for that email address, a password reset link has been sent.",
    }


@app.post("/api/auth/reset-password", tags=["Authentication"])
async def api_reset_password(request: Request, response: Response):
    """
    Validates a single-use password reset token, updates the user's password with salted Argon2id,
    and revokes all existing sessions for the account.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        token = str(body.get("token", "")).strip()
        new_password = str(body.get("new_password", ""))
    else:
        form = await request.form()
        token = str(form.get("token", "")).strip()
        new_password = str(form.get("new_password", ""))

    from services.auth_service import reset_password_with_token
    ok, msg = reset_password_with_token(token, new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    _clear_session_cookies(response)
    return {"status": "success", "message": msg}


@app.get("/api/auth/verify-email", tags=["Authentication"])
@app.post("/api/auth/verify-email", tags=["Authentication"])
async def api_verify_email(request: Request, token: Optional[str] = None):
    """
    Verifies a user's email address using a 24-hour single-use verification token.
    """
    raw_token = (token or "").strip()
    if not raw_token and request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
            raw_token = str(body.get("token", "")).strip()
        else:
            form = await request.form()
            raw_token = str(form.get("token", "")).strip()

    from services.auth_service import verify_email_with_token
    ok, msg, user_id = verify_email_with_token(raw_token)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "status": "success",
        "email_verified": True,
        "user_id": user_id,
        "message": msg,
    }


@app.post("/api/auth/resend-verification", tags=["Authentication"])
def api_resend_verification(request: Request):
    """Generates a fresh 24-hour email verification token and sends it to the authenticated user."""
    user = require_user(request)
    profile = get_user_profile(user["id"])
    if profile.get("email_verified"):
        return {
            "status": "success",
            "email_verified": True,
            "message": "Your email address is already verified.",
        }

    from services.auth_service import create_email_verification_token
    from services.email_service import send_email_verification_email

    raw_token = create_email_verification_token(user["id"])
    send_email_verification_email(user["email"], user.get("name", ""), raw_token)
    return {
        "status": "success",
        "email_verified": False,
        "message": f"A new verification link has been sent to {user['email']}.",
    }


class UnsubscribePayload(BaseModel):
    email: str
    reason: Optional[str] = "USER_REQUESTED"


@app.post("/api/auth/unsubscribe", tags=["Authentication"])
async def api_unsubscribe(payload: UnsubscribePayload, request: Request):
    """
    CASL Marketing Unsubscribe Endpoint (One-click commercial unsubscribe).
    Records withdrawal in marketing_consent_logs and sets marketing_opt_in = 0 on user record if present.
    """
    clean_email = (payload.email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        raise HTTPException(status_code=400, detail="A valid email address is required.")

    ip_addr = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")

    # Lookup user if account exists
    from services.quotelytics_db_service import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE LOWER(email) = ?", (clean_email,))
    u_row = cursor.fetchone()
    user_id = u_row["id"] if u_row else None

    if user_id:
        cursor.execute("UPDATE users SET marketing_opt_in = 0 WHERE id = ?", (user_id,))
        conn.commit()
    conn.close()

    from services.auth_service import record_marketing_consent
    consent_id = record_marketing_consent(
        user_id=user_id,
        email=clean_email,
        consented=False,
        consent_type="ONE_CLICK_UNSUBSCRIBE",
        form_version="v2026.10",
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    return {
        "status": "success",
        "email": clean_email,
        "consent_id": consent_id,
        "message": f"{clean_email} has been unsubscribed from all Quotelytics commercial marketing distributions.",
    }


@app.get("/api/user/quota", tags=["Subscription & Quotas"])
def api_user_quota(request: Request):
    """Retrieves subscription tier quota details and quote usage."""
    user = require_user(request)
    user_id = user["id"]
    quota = get_user_quota_info(user_id)
    if not quota:
        raise HTTPException(status_code=404, detail="User quota record not found")
    return quota

class UpgradeTierPayload(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    tier: str


@app.get("/api/admin/customers", tags=["Subscription & Quotas"])
def api_admin_search_customers(request: Request, q: str = "", limit: int = 25):
    """Admin-only customer lookup returning Business API onboarding readiness counts (never raw secrets or rates)."""
    require_admin_user(request)
    from services.db_service import search_customers_for_admin
    customers = search_customers_for_admin(query=q, limit=limit)
    return {"customers": customers, "total": len(customers)}


@app.post("/api/user/upgrade-tier", tags=["Subscription & Quotas"])
def api_upgrade_tier(payload: UpgradeTierPayload, request: Request):
    """Admin-only endpoint to modify a user's subscription tier (FREE, PRO, TEAM, BUSINESS) by user_id or email."""
    require_admin_user(request)
    verify_csrf(request)
    tier_clean = (payload.tier or "").strip().upper()
    if tier_clean not in ("FREE", "PRO", "TEAM", "BUSINESS"):
        raise HTTPException(status_code=400, detail="Invalid subscription tier.")

    from services.db_service import (
        create_system_notification,
        get_active_user_by_email,
        update_user_tier,
    )

    target_uid = (payload.user_id or "").strip()
    if not target_uid and payload.email:
        matched = get_active_user_by_email(payload.email)
        if not matched:
            raise HTTPException(status_code=404, detail="Customer account not found for that email.")
        target_uid = matched["id"]

    if not target_uid:
        raise HTTPException(status_code=400, detail="Either 'user_id' or 'email' is required.")

    success = update_user_tier(target_uid, tier_clean)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid tier or target user not found.")

    if tier_clean == "BUSINESS":
        try:
            create_system_notification(
                user_id=target_uid,
                title="Business Tier & Developer API Unlocked",
                message="Your account is now active on the Quotelytics Business Tier. Open Account Center -> Developer API to generate your API key.",
                alert_type="SUCCESS",
                link_url="/console/account#api",
            )
        except Exception:
            pass

    return {
        "status": "success",
        "user_id": target_uid,
        "tier": tier_clean,
        "new_tier": tier_clean,
        "quota": get_user_quota_info(target_uid),
    }


class CheckoutPayload(BaseModel):
    plan: str = "PRO"
    interval: Optional[str] = "month"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    promo_code: Optional[str] = None


class PortalPayload(BaseModel):
    return_url: Optional[str] = None


@app.get("/api/billing/info", tags=["Stripe Billing"])
def api_billing_info(request: Request):
    """Returns active billing details, Stripe subscription status, and quotas."""
    user = require_user(request)
    from services.db_service import get_user_billing_info
    billing = get_user_billing_info(user["id"])
    quota = get_user_quota_info(user["id"])
    return {
        "billing": billing,
        "quota": quota,
    }


@app.post("/api/billing/checkout", tags=["Stripe Billing"])
def api_billing_checkout(payload: CheckoutPayload, request: Request):
    """Initializes a Stripe Checkout session for subscription purchase."""
    user = require_user(request)
    from services.stripe_service import create_checkout_session
    try:
        session_info = create_checkout_session(
            user_id=user["id"],
            email=user["email"],
            plan=payload.plan,
            interval=payload.interval or "month",
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
            promo_code=payload.promo_code,
        )
        return session_info
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Billing checkout error: {exc}")
        raise HTTPException(status_code=500, detail=f"Checkout creation failed: {exc}")


@app.post("/api/billing/portal", tags=["Stripe Billing"])
def api_billing_portal(payload: PortalPayload, request: Request):
    """Generates a Stripe Customer Portal redirect URL for managing cards and subscriptions."""
    user = require_user(request)
    from services.stripe_service import create_customer_portal_session
    try:
        portal_info = create_customer_portal_session(
            user_id=user["id"],
            return_url=payload.return_url,
        )
        return portal_info
    except Exception as exc:
        logger.error(f"Billing portal error: {exc}")
        raise HTTPException(status_code=500, detail=f"Portal creation failed: {exc}")


@app.post("/api/stripe/webhook", tags=["Stripe Billing"])
async def api_stripe_webhook(request: Request):
    """Handles signed incoming Stripe billing webhooks."""
    payload_bytes = await request.body()
    sig_header = request.headers.get("stripe-signature")
    from services.stripe_service import process_stripe_webhook
    try:
        result = process_stripe_webhook(payload_bytes, sig_header)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Webhook processing error: {exc}")
        raise HTTPException(status_code=500, detail="Internal webhook processing error")

@app.get("/api/user/bottlenecks", tags=["Subscription & Quotas"])
def api_user_bottlenecks(request: Request, limit: int = 50):
    """Retrieves logged bottleneck incidents for the active user."""
    user = require_user(request)
    user_id = user["id"]
    from services.db_service import list_bottleneck_events
    events = list_bottleneck_events(user_id=user_id, limit=limit)
    return {"bottlenecks": events, "total": len(events)}

@app.get("/api/admin/bottlenecks", tags=["Subscription & Quotas"])
def api_admin_bottlenecks(request: Request, limit: int = 100):
    """Global bottleneck telemetry across tenants to identify upgrade triggers. Requires ADMIN role."""
    require_admin_user(request)
    from services.db_service import list_bottleneck_events
    events = list_bottleneck_events(user_id=None, limit=limit)
    return {"bottlenecks": events, "total": len(events)}

class TeamInvitePayload(BaseModel):
    email: str
    name: Optional[str] = ""
    role: Optional[str] = "DISPATCHER"

@app.get("/api/team/members", tags=["Team & Seats"])
def api_list_team_members(request: Request):
    """Lists team dispatcher seats for this organization."""
    user = require_user(request)
    user_id = user["id"]
    from services.db_service import list_organization_members
    members = list_organization_members(user_id)
    quota = get_user_quota_info(user_id)
    return {
        "members": members,
        "max_seats": quota["max_seats"] if quota else 1,
        "active_seats": quota["active_seats"] if quota else 1,
        "seats_remaining": quota["seats_remaining"] if quota else 0,
        "can_invite_seat": quota["can_invite_seat"] if quota else False
    }

@app.post("/api/team/invite", tags=["Team & Seats"])
def api_invite_team_member(payload: TeamInvitePayload, request: Request):
    """Invites a new team member/dispatcher if seats are available."""
    user = require_user(request)
    user_id = user["id"]
    from services.db_service import add_organization_member
    success, msg, member_data = add_organization_member(
        organization_id=user_id,
        email=payload.email,
        name=payload.name or "",
        role=payload.role or "DISPATCHER"
    )
    if not success:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TIER_SEAT_LIMIT_EXCEEDED",
                "message": msg
            }
        )
    return {"status": "success", "message": msg, "member": member_data}

@app.delete("/api/team/members/{member_id}", tags=["Team & Seats"])
def api_remove_team_member(member_id: str, request: Request):
    """Revokes a seat / removes a team member."""
    user = require_user(request)
    user_id = user["id"]
    from services.db_service import remove_organization_member
    success = remove_organization_member(user_id, member_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found or unauthorized.")
    return {"status": "success", "message": "Member seat revoked."}

@app.get("/api/user/profile", tags=["User Profile"])
def api_profile(request: Request):
    user = require_user(request)
    return get_user_profile(user["id"])

@app.post("/api/support/ticket", tags=["Support Desk"])
async def api_submit_support_ticket(request: Request):
    """Submits a tenant support ticket / inquiry."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else None
    
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        email = body.get("email", "")
        subject = body.get("subject", "")
        message = body.get("message", "")
        category = body.get("category", "GENERAL")
        browser_info = body.get("browser_info", "")
    else:
        form = await request.form()
        email = form.get("email", "")
        subject = form.get("subject", "")
        message = form.get("message", "")
        category = form.get("category", "GENERAL")
        browser_info = form.get("browser_info", "")
        
    if not email or "@" not in str(email):
        raise HTTPException(status_code=400, detail="A valid contact email is required.")
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Subject and message are required.")
        
    from services.db_service import create_support_ticket
    return create_support_ticket(
        email=str(email),
        subject=str(subject),
        message=str(message),
        user_id=user_id,
        category=str(category),
        browser_info=str(browser_info)
    )

@app.get("/api/notifications", tags=["System Notifications"])
def api_get_notifications(request: Request, limit: int = 20):
    """Returns system notifications and unread alert count for the active tenant."""
    user = require_user(request)
    user_id = user["id"]
    from services.db_service import list_system_notifications
    return list_system_notifications(user_id=user_id, limit=limit)

@app.post("/api/notifications/read-all", tags=["System Notifications"])
def api_mark_all_notifications_read(request: Request):
    """Marks all system notifications as read for current user."""
    user = require_user(request)
    user_id = user["id"]
    from services.db_service import mark_all_system_notifications_read
    count = mark_all_system_notifications_read(user_id)
    return {"status": "success", "marked_read": count}

@app.post("/api/notifications/{notification_id}/read", tags=["System Notifications"])
def api_mark_notification_read(notification_id: str, request: Request):
    """Marks a single system notification as read."""
    user = require_user(request)
    user_id = user["id"]
    from services.db_service import mark_system_notification_read
    success = mark_system_notification_read(notification_id, user_id)
    return {"status": "success" if success else "not_found", "marked_read": success}


@app.post("/api/quotes/upload", tags=["Quoting Engine"])
async def api_upload_rate_sheet(
    request: Request,
    file: UploadFile = File(...)
):
    """
    Ingests an Excel (.xlsx, .xls) spreadsheet, verifies tier limits,
    parses line items, calculates quotes with broker markup, and saves to history.
    """
    user = require_user(request)
    user_id = user["id"]
    
    # 1. Enforce Subscription Quotas
    quota = get_user_quota_info(user_id)
    if quota and not quota["can_upload_sheet"]:
        from services.db_service import log_bottleneck_event
        log_bottleneck_event(
            user_id=user_id,
            bottleneck_type="LIMIT_BLOCKED_SHEETS",
            attempted_action=f"Upload batch sheet: {file.filename}",
            current_usage=quota["sheets_uploaded"],
            max_limit=quota["max_sheets"],
            details={"filename": file.filename, "tier": quota["tier"]}
        )
        raise HTTPException(
            status_code=403, 
            detail=f"Tier limit exceeded: {quota['tier_name']} allows a maximum of {quota['max_sheets']} uploaded rate sheet. Please upgrade to Pro for additional sheets."
        )

    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="Only Excel files (.xlsx, .xls) are supported.")
        
    content = await file.read()
    try:
        parsed_data = parse_excel_rate_sheet(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel parsing error: {str(e)}")
        
    if quota and quota["max_quotes_per_month"] > 0:
        if quota["monthly_quotes_used"] + parsed_data["total_parsed_rows"] > quota["max_quotes_per_month"]:
            from services.db_service import log_bottleneck_event
            log_bottleneck_event(
                user_id=user_id,
                bottleneck_type="LIMIT_BLOCKED_QUOTES",
                attempted_action=f"Batch quote batch ({parsed_data['total_parsed_rows']} rows)",
                current_usage=quota["monthly_quotes_used"],
                max_limit=quota["max_quotes_per_month"],
                details={"batch_rows": parsed_data["total_parsed_rows"], "tier": quota["tier"]}
            )
            raise HTTPException(
                status_code=403,
                detail=f"Quote volume limit exceeded: This batch requires {parsed_data['total_parsed_rows']} quotes, but you only have {quota['quotes_remaining']} quotes remaining this month on {quota['tier_name']}."
            )

    profile = get_user_profile(user_id)
    markup = profile.get("markup_pct", 10.0)
    
    # Purge any previous client proposal draft upon generating next quote
    clear_active_proposal(user_id)

    quoted_items = calculate_batch_quotes(parsed_data["rows"], markup_pct=markup)
    
    # Save to SQLite
    conn = get_connection()
    cursor = conn.cursor()
    batch_id = f"qb_{int(datetime.utcnow().timestamp())}"
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
    INSERT INTO quote_batches (id, user_id, filename, total_rows, processed_rows, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (batch_id, user_id, file.filename, len(quoted_items), len(quoted_items), now))
    
    insert_items = [
        (q["quote_id"], batch_id, q["row_num"], q["origin_zip"], q["dest_zip"],
         q["weight_lbs"], q["carrier"], q["service"], q["base_rate"], q["markup_pct"],
         q["final_rate"], q["coordinate"], now)
        for q in quoted_items
    ]
    
    cursor.executemany("""
    INSERT OR REPLACE INTO quote_items (id, batch_id, row_num, origin_zip, dest_zip, weight_lbs, carrier, service, base_rate, markup_pct, final_rate, coordinate, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, insert_items)
    
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "batch_id": batch_id,
        "filename": file.filename,
        "total_quotes": len(quoted_items),
        "quotes": quoted_items
    }

class ConfirmReformattedPayload(BaseModel):
    analysis_token: str
    confirmed_mapping: Optional[Dict[str, Any]] = None
    row_corrections: Optional[Dict[str, Dict[str, Any]]] = None
    ignored_exceptions: Optional[List[Dict[str, Any]]] = None
    non_critical_rows: Optional[List[int]] = None
    non_critical_columns: Optional[List[str]] = None
    flag_all_exceptions_non_critical: Optional[bool] = False

@app.post("/api/quotes/analyze-excel", tags=["Quotelytics Excel Re-formatter"])
async def api_analyze_excel(
    request: Request,
    file: UploadFile = File(...)
):
    """
    Phase 1: Analyzes an uploaded Excel spreadsheet, detects table boundaries, column semantics,
    and units, identifying any missing or ambiguous fields for user clarification (Rules 1, 3, 5, 6, 25).
    """
    user = require_user(request)
    user_id = user["id"]
    
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only spreadsheet files (.xlsx, .xls, .csv) are supported.")
        
    content = await file.read()
    try:
        analysis = analyze_excel_sheet(content, file.filename)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel analysis error: {str(e)}")

@app.post("/api/quotes/confirm-reformatted", tags=["Quotelytics Excel Re-formatter"])
def api_confirm_reformatted_batch(
    payload: ConfirmReformattedPayload,
    request: Request
):
    """
    Phase 2: Receives user-confirmed column mappings and row clarifications, generates the standardized
    reformatted Excel file, executes deterministic rating against confirmed tariffs, and logs audit.
    Supports user flagging of exceptions as non-critical business info (e.g. company headquarters, internal codes)
    to bypass strict input requirements safely. (Rules 7, 8-15, 18, 19, 25, 30).
    """
    user = require_user(request)
    user_id = user["id"]
    user_hq_origin = user.get("origin_zip") or "CALGARY, AB"
    
    safe_token = os.path.basename(payload.analysis_token)
    if not re.match(r"^[A-Za-z0-9_-]+$", safe_token) or safe_token != payload.analysis_token:
        raise HTTPException(400, "Invalid analysis token")
    token = safe_token
    payload_path = os.path.join(SCRATCH_DIR, f"staged_analysis_{token}.json")
    if not os.path.exists(payload_path):
        raise HTTPException(status_code=404, detail="Staged analysis expired or not found. Please re-upload.")
        
    with open(payload_path, "r", encoding="utf-8") as f:
        staged_data = json.load(f)
        
    meta = staged_data["meta"]
    rows = staged_data["all_rows"]

    # Collect row numbers flagged as non-critical information / ignored by broker
    non_crit_row_nums = set(payload.non_critical_rows or [])
    if payload.ignored_exceptions:
        for item in payload.ignored_exceptions:
            if "row_num" in item and item["row_num"] is not None:
                try:
                    non_crit_row_nums.add(int(item["row_num"]))
                except (ValueError, TypeError):
                    pass

    if payload.flag_all_exceptions_non_critical:
        for r in rows:
            if not r.get("is_complete", False):
                non_crit_row_nums.add(r["row_num"])
    
    # 1. Apply row corrections if provided (Rule 25)
    corrections = payload.row_corrections or {}
    for r in rows:
        r_str = str(r["row_num"])
        if r_str in corrections:
            cor = corrections[r_str]
            if "weight_lbs" in cor and cor["weight_lbs"] is not None and str(cor["weight_lbs"]).strip() != "":
                try:
                    r["weight_lbs"] = float(cor["weight_lbs"])
                    r["weight_raw"] = str(cor["weight_lbs"])
                except ValueError:
                    pass
            if "origin_normalized" in cor and cor["origin_normalized"]:
                r["origin_normalized"] = cor["origin_normalized"].strip().upper()
                r["origin_raw"] = r["origin_normalized"]
            if "dest_normalized" in cor and cor["dest_normalized"]:
                r["dest_normalized"] = cor["dest_normalized"].strip().upper()
                r["dest_raw"] = r["dest_normalized"]

        # 2. Process non-critical info flags (bypasses strict input requirement)
        if r["row_num"] in non_crit_row_nums:
            r["is_non_critical"] = True
            # Resolve missing origin with company headquarters / account dispatch location
            if not r.get("origin_normalized"):
                r["origin_normalized"] = user_hq_origin
                r["origin_raw"] = f"Company HQ ({user_hq_origin})"
            # Resolve missing destination if omitted
            if not r.get("dest_normalized"):
                r["dest_normalized"] = "TORONTO, ON"
                r["dest_raw"] = "Toronto Hub (Non-critical default)"
            # Supply nominal rating baseline if weight was omitted
            if r.get("weight_lbs") is None or r.get("weight_lbs", 0) <= 0:
                r["weight_lbs"] = 100.0
                r["weight_raw"] = "100.0 lbs (Non-critical nominal wt)"
            r["is_complete"] = True
            r["needs_review"] = False
            r["review_reasons"] = ["Flagged as non-critical business info (e.g. company headquarters / internal dispatch) - strict input bypassed."]
        else:
            # Recalculate completeness
            r["is_complete"] = bool(r["origin_normalized"] and r["dest_normalized"] and r["weight_lbs"] and r["weight_lbs"] > 0)
            if r["is_complete"]:
                r["needs_review"] = False
                r["review_reasons"] = []
                
    # Strict validation: Check for any remaining missing mandatory fields that were NOT flagged as non-critical
    unresolved = [r for r in rows if not r.get("is_complete", False) and not r.get("is_non_critical", False)]
    if unresolved:
        unresolved_rows = [r["row_num"] for r in unresolved]
        raise HTTPException(
            status_code=400,
            detail=f"Rule 25 Requirement: Cannot quote shipments with missing mandatory details. Missing parameters on rows: {unresolved_rows}. Please clarify or flag as non-critical info before confirming."
        )
        
    # Generate the pristine standardized Excel workbook
    reformatted_bytes = build_reformatted_excel_workbook(rows, meta["filename"])
    reformatted_file_path = os.path.join(SCRATCH_DIR, f"reformatted_{token}.xlsx")
    wb_out = openpyxl.load_workbook(io.BytesIO(reformatted_bytes))
    sanitize_workbook(wb_out)
    wb_out.save(reformatted_file_path)
        
    # Rate each shipment deterministically against confirmed tariffs (Rules 8-15)
    from services.quotelytics_engine import quote_all_confirmed_carriers
    
    rated_results = []
    for r in rows:
        try:
            res = quote_all_confirmed_carriers(
                user_id=user_id,
                origin=r["origin_normalized"],
                destination=r["dest_normalized"],
                actual_weight=r["weight_lbs"],
                length=r.get("length"),
                width=r.get("width"),
                height=r.get("height"),
                accessorials=r.get("accessorials", []),
                shipment_date=r.get("shipment_date"),
                skid_count=r.get("skid_count")
            )
            rated_results.append({
                "row_num": r["row_num"],
                "origin": r["origin_normalized"],
                "destination": r["dest_normalized"],
                "weight_lbs": r["weight_lbs"],
                "quote_id": res["quote_id"],
                "options_count": len(res["quotes"]),
                "quotes": res["quotes"],
                "excluded_sheets": res.get("excluded_sheets", []),
                "source_coordinate": r.get("origin_coord", "")
            })
        except Exception as e:
            rated_results.append({
                "row_num": r["row_num"],
                "origin": r["origin_normalized"],
                "destination": r["dest_normalized"],
                "weight_lbs": r["weight_lbs"],
                "error": str(e),
                "quotes": [],
                "source_coordinate": r.get("origin_coord", "")
            })
            
    batch_id = f"ql_batch_{uuid.uuid4().hex[:10]}"
    
    return {
        "status": "success",
        "batch_id": batch_id,
        "analysis_token": token,
        "filename": meta["filename"],
        "total_shipments": len(rows),
        "rated_shipments": rated_results,
        "download_url": f"/api/quotes/download-reformatted/{token}"
    }

@app.get("/api/quotes/download-reformatted/{analysis_token:path}", tags=["Quotelytics Excel Re-formatter"])
def api_download_reformatted_excel(analysis_token: str, request: Request):
    """Downloads the sanitized, reformatted standardized Excel workbook (.xlsx)."""
    require_user(request)
    safe_token = os.path.basename(analysis_token)
    if not re.match(r"^[A-Za-z0-9_-]+$", safe_token) or safe_token != analysis_token:
        raise HTTPException(400, "Invalid analysis token")
    file_path = os.path.join(SCRATCH_DIR, f"reformatted_{safe_token}.xlsx")
    if not os.path.exists(file_path):
        # Check if raw upload was staged and generate on demand
        payload_path = os.path.join(SCRATCH_DIR, f"staged_analysis_{safe_token}.json")
        if os.path.exists(payload_path):
            with open(payload_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            wb_bytes = build_reformatted_excel_workbook(data["all_rows"], data["meta"]["filename"])
            wb_out = openpyxl.load_workbook(io.BytesIO(wb_bytes))
            sanitize_workbook(wb_out)
            wb_out.save(file_path)
        else:
            raise HTTPException(status_code=404, detail="Reformatted spreadsheet not found or expired.")
            
    return FileResponse(
        path=file_path,
        filename=f"reformatted_{safe_token}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.get("/api/quotes/history", tags=["Quoting Engine"])
def api_get_quotes_history(request: Request, search: Optional[str] = None, sort_by: str = "date"):
    """Fetches historical quotes with exact cell coordinates."""
    user = require_user(request)
    user_id = user["id"]
    
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT q.*, b.filename
    FROM quote_items q
    JOIN quote_batches b ON q.batch_id = b.id
    WHERE b.user_id = ?
    """
    params = [user_id]
    
    if search:
        query += " AND (q.id LIKE ? OR q.dest_zip LIKE ? OR q.carrier LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])
        
    if sort_by == "rate_asc":
        query += " ORDER BY q.final_rate ASC"
    elif sort_by == "rate_desc":
        query += " ORDER BY q.final_rate DESC"
    else:
        query += " ORDER BY q.created_at DESC"
        
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    from services.quotelytics_db_service import list_rate_sheets
    user_sheets = list_rate_sheets(user_id=user_id)
    default_sheet_id = user_sheets[0]["id"] if user_sheets else None

    import json
    for r in rows:
        if not r.get("sheet_id"):
            matched_sid = None
            carrier_clean = (r.get("carrier") or "").lower()
            for s in user_sheets:
                s_carrier = (s.get("carrier_name") or "").lower()
                if s_carrier in carrier_clean or carrier_clean in s_carrier:
                    matched_sid = s["id"]
                    break
            r["sheet_id"] = matched_sid or default_sheet_id

        # Parse calculation trace if JSON string
        trace_raw = r.get("calculation_trace")
        if trace_raw and isinstance(trace_raw, str):
            try:
                r["calculation_work"] = json.loads(trace_raw)
            except Exception:
                r["calculation_work"] = []
        elif isinstance(trace_raw, list):
            r["calculation_work"] = trace_raw
        else:
            r["calculation_work"] = []

        # Ensure formula is always present
        if not r.get("formula"):
            base = float(r.get("base_rate") or 0.0)
            final = float(r.get("final_rate") or 0.0)
            markup = float(r.get("markup_pct") or 15.0)
            margin = round(final - base, 2)
            skids = r.get("skid_count")
            if skids and skids > 0:
                per_skid = round(base / max(1, skids), 2)
                r["formula"] = f"Base Freight: {skids} skid{'s' if skids != 1 else ''} x ${per_skid:.2f} = ${base:.2f} | Markup (+{markup}%): +${margin:.2f} → Final Quoted Rate: ${final:.2f}"
            else:
                wt = r.get("weight_lbs") or 0
                r["formula"] = f"Base Freight: ${base:.2f} (Weight: {wt:,.0f} lbs) | Markup (+{markup}%): +${margin:.2f} → Final Quoted Rate: ${final:.2f}"

    return {"total": len(rows), "quotes": rows}

# ==============================================================================
# QUOTELYTICS CARRIER RATE SHEETS & CONFIRMATION GATE (Rules 1-7, 19)
# ==============================================================================

@app.post("/api/quotelytics/sheets/upload", tags=["Quotelytics Rate Sheets"])
async def api_quotelytics_upload_sheet(
    request: Request,
    file: UploadFile = File(...)
):
    """
    Ingests an Excel (.xlsx, .xls) or CSV rate sheet.
    Deep extracts terms, accessorials, hidden rows/cols, units, and rates.
    Flags uncertain cells and requires human confirmation (Rules 1, 4, 5, 6, 7).
    """
    user = require_user(request)
    user_id = user["id"]

    # Enforce Subscription Tier Sheet Limits & Track Bottlenecks
    quota = get_user_quota_info(user_id)
    if quota and not quota["can_upload_sheet"]:
        from services.db_service import log_bottleneck_event
        log_bottleneck_event(
            user_id=user_id,
            bottleneck_type="LIMIT_BLOCKED_SHEETS",
            attempted_action=f"Upload rate sheet: {file.filename}",
            current_usage=quota["sheets_uploaded"],
            max_limit=quota["max_sheets"],
            details={"filename": file.filename, "tier": quota["tier"]}
        )
        raise HTTPException(
            status_code=403,
            detail=f"Tier limit exceeded: {quota['tier_name']} allows a maximum of {quota['max_sheets']} uploaded rate sheets ({quota['sheets_uploaded']} active). Please upgrade to Pro or Team for additional sheets."
        )

    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV (.csv) rate sheets are supported.")

    content = await file.read()
    try:
        from services.quotelytics_extractor import QuotelyticsExtractor
        extractor = QuotelyticsExtractor(file_bytes=content, filename=file.filename, user_id=user_id)
        result = extractor.process()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Rate sheet extraction error: {str(e)}")

@app.get("/api/quotelytics/sheets", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_list_sheets(request: Request, status: Optional[str] = None):
    """Lists rate sheets for the authenticated tenant (Rule 28)."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import list_rate_sheets
    sheets = list_rate_sheets(user_id=user_id, status=status)
    return {"sheets": sheets}

@app.get("/api/quotelytics/sheets/{sheet_id}", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_get_sheet(sheet_id: str, request: Request, limit: Optional[int] = None, offset: int = 0):
    """Retrieves sheet rules, accessorials, breaks (optionally paginated for speed), minimums, and review flags."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import get_sheet_full_rules, get_rate_sheet_cells
    full_rules = get_sheet_full_rules(sheet_id, user_id, limit=limit, offset=offset)
    if not full_rules or not full_rules.get("sheet"):
        raise HTTPException(status_code=404, detail="Rate sheet not found or unauthorized.")
    flagged_cells = get_rate_sheet_cells(sheet_id, user_id, needs_review_only=True)
    full_rules["flagged_cells"] = flagged_cells
    return full_rules

@app.get("/api/quotelytics/sheets/{sheet_id}/breaks", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_get_sheet_breaks(
    sheet_id: str,
    request: Request,
    page: int = 1,
    limit: int = 50,
    query: Optional[str] = None
):
    """Returns weight breaks with high-performance server-side pagination and real-time search."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import get_sheet_breaks_paginated
    return get_sheet_breaks_paginated(sheet_id, user_id, page=page, limit=limit, query=query)

@app.post("/api/quotelytics/sheets/{sheet_id}/confirm", tags=["Quotelytics Rate Sheets"])
async def api_quotelytics_confirm_sheet(sheet_id: str, request: Request):
    """Enforces human confirmation gate (Rule 7, 19) confirming core rules (Rule 5, 15, 16) and broker markup."""
    user = require_user(request)
    user_id = user["id"]
    confirmed_by = user.get("name") or user["id"]
    
    markup_mode = "PERCENTAGE"
    markup_value = 0.0
    fsc_passthrough = True
    accessorial_markup_pct = 0.0
    manual_override = False
    currency = None
    weight_unit = None
    dim_divisor = None
    effective_date = None
    expiry_date = None
    rounding_rule = None
    resolve_flags = False
    
    try:
        body = await request.json()
        if isinstance(body, dict):
            markup_mode = body.get("markup_mode", "PERCENTAGE")
            markup_value = float(body.get("markup_value", 0.0) or 0.0)
            fsc_passthrough = bool(body.get("fsc_passthrough", True))
            accessorial_markup_pct = float(body.get("accessorial_markup_pct", 0.0) or 0.0)
            manual_override = bool(body.get("manual_override", False))
            currency = body.get("currency")
            weight_unit = body.get("weight_unit")
            dim_divisor = float(body["dim_divisor"]) if body.get("dim_divisor") is not None else None
            effective_date = body.get("effective_date")
            expiry_date = body.get("expiry_date")
            rounding_rule = body.get("rounding_rule")
            resolve_flags = bool(body.get("resolve_flags", False))
    except Exception:
        pass
        
    from services.quotelytics_db_service import confirm_rate_sheet
    success = confirm_rate_sheet(
        sheet_id=sheet_id,
        user_id=user_id,
        confirmed_by=confirmed_by,
        currency=currency,
        weight_unit=weight_unit,
        dim_divisor=dim_divisor,
        effective_date=effective_date,
        expiry_date=expiry_date,
        rounding_rule=rounding_rule,
        markup_mode=markup_mode,
        markup_value=markup_value,
        fsc_passthrough=fsc_passthrough,
        accessorial_markup_pct=accessorial_markup_pct,
        manual_override=manual_override,
        resolve_flags=resolve_flags
    )
    if not success:
        raise HTTPException(status_code=404, detail="Rate sheet not found or confirmation failed.")
    return {
        "status": "success",
        "message": "Rate sheet and tariff rules confirmed successfully. It is now enabled for live quoting.",
        "manual_override": manual_override,
        "markup_mode": markup_mode,
        "markup_value": markup_value,
        "currency": currency
    }

@app.post("/api/quotelytics/sheets/{sheet_id}/markup", tags=["Quotelytics Rate Sheets"])
async def api_quotelytics_update_markup(sheet_id: str, request: Request):
    """Updates broker margin markup rules and confirmed rules on a rate sheet."""
    user = require_user(request)
    user_id = user["id"]
    
    try:
        body = await request.json()
    except Exception:
        body = {}
        
    markup_mode = body.get("markup_mode", "PERCENTAGE")
    markup_value = float(body.get("markup_value", 0.0) or 0.0)
    fsc_passthrough = bool(body.get("fsc_passthrough", True))
    accessorial_markup_pct = float(body.get("accessorial_markup_pct", 0.0) or 0.0)
    manual_override = bool(body.get("manual_override", False))
    currency = body.get("currency")
    weight_unit = body.get("weight_unit")
    dim_divisor = float(body["dim_divisor"]) if body.get("dim_divisor") is not None else None
    effective_date = body.get("effective_date")
    expiry_date = body.get("expiry_date")
    rounding_rule = body.get("rounding_rule")
    
    from services.quotelytics_db_service import update_rate_sheet_markup
    success = update_rate_sheet_markup(
        sheet_id=sheet_id,
        user_id=user_id,
        currency=currency,
        weight_unit=weight_unit,
        dim_divisor=dim_divisor,
        effective_date=effective_date,
        expiry_date=expiry_date,
        rounding_rule=rounding_rule,
        markup_mode=markup_mode,
        markup_value=markup_value,
        fsc_passthrough=fsc_passthrough,
        accessorial_markup_pct=accessorial_markup_pct,
        manual_override=manual_override
    )
    if not success:
        raise HTTPException(status_code=404, detail="Rate sheet not found or markup update failed.")
    return {
        "status": "success",
        "message": "Rate sheet rules updated successfully.",
        "manual_override": manual_override
    }

@app.post("/api/quotelytics/sheets/{sheet_id}/surcharges/{surcharge_code}/waive", tags=["Quotelytics Rate Sheets"])
async def api_quotelytics_toggle_surcharge_waive(sheet_id: str, surcharge_code: str, request: Request):
    """Toggles waived fee status for a carrier surcharge (Rule 4 & 11)."""
    user = require_user(request)
    user_id = user["id"]
    try:
        body = await request.json()
        is_waived = bool(body.get("is_waived", True))
    except Exception:
        is_waived = True
    from services.quotelytics_db_service import toggle_surcharge_waived
    success = toggle_surcharge_waived(sheet_id, user_id, surcharge_code, is_waived)
    if not success:
        raise HTTPException(status_code=404, detail="Surcharge not found.")
    return {"status": "success", "is_waived": is_waived}

@app.post("/api/quotelytics/sheets/{sheet_id}/cells/resolve", tags=["Quotelytics Rate Sheets"])
async def api_quotelytics_resolve_cell(sheet_id: str, request: Request):
    """Marks a flagged cell coordinate as verified by human broker (Rule 6)."""
    user = require_user(request)
    user_id = user["id"]
    body = await request.json()
    cell_coord = body.get("cell_coord")
    if not cell_coord:
        raise HTTPException(status_code=400, detail="cell_coord required")
    from services.quotelytics_db_service import resolve_flagged_cell
    success = resolve_flagged_cell(sheet_id, user_id, cell_coord)
    return {"status": "success", "cell_coord": cell_coord}

@app.get("/api/quotelytics/sheets/{sheet_id}/formatted-matrix", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_formatted_matrix(
    sheet_id: str,
    request: Request,
    page: int = 1,
    limit: int = 50,
    query: Optional[str] = None,
    cell: Optional[str] = None,
    highlight: Optional[str] = None
):
    """
    Returns normalized matrix data for in-browser visual inspection only.
    Downloads are permanently disabled per strict security policy (Rule 3 & Invariant).
    """
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import get_rate_sheet, get_sheet_breaks_paginated
    
    sheet = get_rate_sheet(sheet_id, user_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Rate sheet not found or unauthorized.")
        
    target_cell = cell or highlight
    breaks_res = get_sheet_breaks_paginated(sheet_id, user_id, page=page, limit=limit, query=query, target_cell=target_cell)
    return {
        "sheet": sheet,
        "breaks": breaks_res["breaks"],
        "total_breaks": breaks_res["total_count"],
        "page": breaks_res["page"],
        "limit": breaks_res["limit"],
        "total_pages": breaks_res["total_pages"],
        "download_disabled": True,
        "security_badge": "🔒 In-Browser Inspection Only • Downloads Disabled"
    }

@app.get("/api/quotelytics/sheets/{sheet_id}/download-formatted", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_block_download(sheet_id: str):
    """Permanently blocked endpoint for formatted rate sheets."""
    raise HTTPException(
        status_code=403,
        detail="Security Policy Violation: Rate sheet downloads are permanently disabled. Tariffs may only be inspected in-browser (Rule 3 & Invariant)."
    )

@app.post("/api/quotelytics/sheets/{sheet_id}/archive", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_archive_sheet(sheet_id: str, request: Request):
    """Archives a rate sheet so it is no longer quoted."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import archive_rate_sheet
    success = archive_rate_sheet(sheet_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rate sheet not found.")
    return {"status": "success", "message": "Rate sheet archived."}

@app.delete("/api/quotelytics/sheets/{sheet_id}", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_delete_sheet(sheet_id: str, request: Request):
    """Deletes a rate sheet."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import delete_rate_sheet
    success = delete_rate_sheet(sheet_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rate sheet not found.")
    return {"status": "success", "message": "Rate sheet deleted."}

@app.get("/api/quotelytics/sheets/{sheet_id}/cells", tags=["Quotelytics Rate Sheets"])
def api_quotelytics_get_cells(sheet_id: str, request: Request, needs_review_only: bool = False):
    """Returns cell coordinate traceability logs (Rule 3)."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import get_rate_sheet_cells
    cells = get_rate_sheet_cells(sheet_id, user_id, needs_review_only=needs_review_only)
    return {"sheet_id": sheet_id, "cells": cells}

# ==============================================================================
# QUOTELYTICS DETERMINISTIC QUOTING ENGINE (Rules 8-15, 20, 26, 30)
# ==============================================================================

class QuoteRequestPayload(BaseModel):
    origin: str
    destination: str
    actual_weight: Optional[float] = None
    weight: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    accessorials: Optional[List[str]] = None
    shipment_date: Optional[str] = None
    skid_count: Optional[int] = None
    skids: Optional[int] = None
    shipping_mode: Optional[str] = "LTL"

@app.post("/api/quotelytics/quotes/calculate", tags=["Quotelytics Quoting Core"])
@app.post("/api/quotes/calculate", tags=["Quotelytics Quoting Core"])
def api_quotelytics_calculate_quote(
    payload: QuoteRequestPayload,
    request: Request
):
    """
    Calculates shipping rate quotes deterministically from confirmed sheets (Rules 8-15).
    Enforces Rule 9 (DIM divisors), Rule 10 (Zone resolution), Rule 11 (Itemized surcharges),
    Rule 12 (Minimum charge check), Rule 13 (Full line-item breakdown),
    Rule 15 (Final rounding), and Rule 30 (Audit logging).
    """
    user = require_quoting_user(request, require_business_session=False)
    user_id = user["id"]

    if (payload.shipping_mode or "LTL").strip().upper() == "PARCEL":
        raise _StructuredAPIError(
            status_code=422,
            payload={
                "error": "E_PARCEL_NOT_SUPPORTED",
                "detail": "Quotelytics supports Skid/LTL freight only. Parcel mode is not supported.",
            },
        )

    # Purge any previous client proposal draft upon generating next quote
    clear_active_proposal(user_id)

    # Derive actual weight from LTL skids if explicit weight was omitted (supporting canonical & alias fields)
    skid_count = payload.skid_count if payload.skid_count is not None else payload.skids
    actual_weight = payload.actual_weight if payload.actual_weight is not None else payload.weight
    if actual_weight is None:
        skid_count = skid_count or 1
        actual_weight = float(skid_count * 500.0)
    elif actual_weight <= 0:
        if skid_count and skid_count > 0:
            actual_weight = float(skid_count * 500.0)
        else:
            raise HTTPException(status_code=400, detail="Shipment weight must be greater than 0.")
    else:
        # actual_weight > 0
        if not skid_count:
            skid_count = None

    if not actual_weight or actual_weight <= 0:
        raise HTTPException(status_code=400, detail="Shipment weight must be greater than 0.")
    if not payload.origin or not payload.destination:
        raise HTTPException(status_code=400, detail="Origin and Destination locations are required (Rule 25).")

    # Dual-Signal Parcel Detection (Release 2a & 2b)
    from services.quotelytics_db_service import get_or_initialize_sunset_timestamps
    is_small_weight = (actual_weight < 150.0)
    is_unpalletized = (skid_count is None or skid_count == 0)
    is_dual_signal_parcel = is_small_weight and is_unpalletized

    deploy_ts, sunset_ts = get_or_initialize_sunset_timestamps(sunset_clock)
    now_ts = sunset_clock()
    is_post_sunset = (now_ts >= sunset_ts)
    is_strict = os.environ.get("FAILSAFE_PARCEL_STRICT", "false").lower() == "true"

    if is_dual_signal_parcel and (is_post_sunset or is_strict):
        return JSONResponse(
            status_code=422,
            content={
                "error": "E_PARCEL_DEPRECATED_LTL_ONLY",
                "message": "Quotelytics supports Skid/LTL freight only. Individual package quotes under 150 lbs are no longer supported. Please palletize or specify skid count.",
                "documentation_url": "https://api.quotelytics.ca/docs/ltl-transition"
            }
        )

    # Enforce Monthly Quoting Quotas & Track Bottlenecks Atomically (Rule 30 + Concurrency Shield)
    from services.quotelytics_db_service import reserve_user_quote_slot, release_quote_reservation
    allowed, quote_id, quota = reserve_user_quote_slot(user_id, shipment_inputs={
        "origin": payload.origin,
        "destination": payload.destination,
        "actual_weight": actual_weight,
        "skid_count": skid_count,
    })
    if not allowed:
        from services.db_service import log_bottleneck_event
        log_bottleneck_event(
            user_id=user_id,
            bottleneck_type="LIMIT_BLOCKED_QUOTES",
            attempted_action=f"Deterministic quote calculation: {payload.origin} -> {payload.destination}",
            current_usage=quota["monthly_quotes_used"] if quota else 0,
            max_limit=quota["max_quotes_per_month"] if quota else 50,
            details={"origin": payload.origin, "destination": payload.destination, "tier": quota["tier"] if quota else "free"}
        )
        raise HTTPException(
            status_code=403,
            detail=f"Quote volume limit exceeded: You have reached your monthly limit of {quota['max_quotes_per_month']} quotes on {quota['tier_name']}. Please upgrade to Pro or Team to continue quoting."
        )

    from services.quotelytics_engine import quote_all_confirmed_carriers
    try:
        result = quote_all_confirmed_carriers(
            user_id=user_id,
            origin=payload.origin,
            destination=payload.destination,
            actual_weight=actual_weight,
            length=payload.length,
            width=payload.width,
            height=payload.height,
            accessorials=payload.accessorials or [],
            shipment_date=payload.shipment_date,
            skid_count=skid_count,
            quote_id=quote_id
        )

        if is_dual_signal_parcel and isinstance(result, dict):
            sunset_imf = email.utils.formatdate(sunset_ts, usegmt=True)
            deprecation_hdr = f"@{int(deploy_ts)}"
            link_hdr = '<https://api.quotelytics.ca/docs/ltl-transition>; rel="sunset"; type="text/html"'
            result["advisory_warnings"] = [
                {
                    "code": "WARN_PARCEL_DEPRECATION",
                    "message": "Quotelytics is transitioning exclusively to Skid/LTL freight. Quotes under 150 lbs unpalletized will be discontinued after the sunset date. Minimum LTL floor applies.",
                    "sunset_date": datetime.utcfromtimestamp(sunset_ts).isoformat() + "Z",
                }
            ]
            response = JSONResponse(content=result)
            response.headers["Sunset"] = sunset_imf
            response.headers["Deprecation"] = deprecation_hdr
            response.headers["Link"] = link_hdr
            return response

        return result
    except Exception as e:
        release_quote_reservation(quote_id, user_id)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail=f"Rate calculation error: {str(e)}")

@app.get("/api/quotelytics/quotes/audit/{quote_id}", tags=["Quotelytics Quoting Core"])
def api_quotelytics_get_audit_log(quote_id: str, request: Request):
    """Retrieves immutable audit log for a quote (Rule 30)."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import get_quote_audit_log
    audit = get_quote_audit_log(quote_id, user_id=user_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit log not found or unauthorized.")
    return audit

@app.get("/api/quotelytics/quotes/audit", tags=["Quotelytics Quoting Core"])
def api_quotelytics_list_audit_logs(request: Request, limit: int = 50):
    """Lists recent quote audit logs for the authenticated tenant (Rule 28, 30)."""
    user = require_user(request)
    user_id = user["id"]
    from services.quotelytics_db_service import list_quote_audit_logs
    logs = list_quote_audit_logs(user_id=user_id, limit=limit)
    return {"audit_logs": logs}

@app.post("/api/settings/update", tags=["System Settings"])
async def api_update_settings(request: Request):
    user = require_user(request)
    user_id = user["id"]
    
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        currency = body.get("currency", "CAD")
        units = body.get("units", "lbs")
        markup_pct = float(body.get("markup_pct", 10.0))
        markup_mode = body.get("markup_mode", "percent")
        fsc_passthrough = int(body.get("fsc_passthrough", 1))
        auto_detect_headers = int(body.get("auto_detect_headers", 1))
        skip_blank_rows = int(body.get("skip_blank_rows", 1))
    else:
        form = await request.form()
        currency = form.get("currency", "CAD")
        units = form.get("units", "lbs")
        markup_pct = float(form.get("markup_pct", 10.0))
        markup_mode = form.get("markup_mode", "percent")
        fsc_passthrough = int(form.get("fsc_passthrough", 1))
        auto_detect_headers = int(form.get("auto_detect_headers", 1))
        skip_blank_rows = int(form.get("skip_blank_rows", 1))
        
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE user_settings
    SET currency = ?, units = ?, markup_pct = ?, markup_mode = ?, fsc_passthrough = ?, auto_detect_headers = ?, skip_blank_rows = ?
    WHERE user_id = ?
    """, (currency, units, markup_pct, markup_mode, fsc_passthrough, auto_detect_headers, skip_blank_rows, user_id))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Settings updated successfully."}

@app.get("/api/quotes/export", tags=["Quoting Engine"])
def api_export_quotes_excel(request: Request):
    """
    Exports historical quotes into an Excel workbook (.xlsx)
    with original cell coordinates and calculated rates.
    """
    import openpyxl
    user = require_user(request)
    user_id = user["id"]
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT q.*, b.filename
    FROM quote_items q
    JOIN quote_batches b ON q.batch_id = b.id
    WHERE b.user_id = ?
    ORDER BY q.created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calculated_Quotes"
    
    headers = [
        "Quote_ID", "Source_File", "Excel_Row", "Origin_ZIP", "Destination_ZIP", 
        "Weight_Lbs", "Skids", "Assigned_Carrier", "Service_Level", "Base_Rate_USD", 
        "Markup_Pct", "Final_Rate_USD", "Applied_Formula", "Exact_Cell_Coordinate", "Timestamp"
    ]
    ws.append(headers)
    
    for r in rows:
        ws.append([
            r["id"], r["filename"], r["row_num"], r["origin_zip"], r["dest_zip"],
            r["weight_lbs"], r["skid_count"] if "skid_count" in r.keys() else "",
            r["carrier"], r["service"], r["base_rate"],
            r["markup_pct"], r["final_rate"],
            r["formula"] if "formula" in r.keys() else "",
            r["coordinate"], r["created_at"]
        ])
        
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Quotelytics_Quotes_Export.xlsx"}
    )

# ==============================================================================
# CLIENT QUOTE PROPOSAL GENERATOR (1-Click Branded Excel / Printable Proposal)
# ==============================================================================

class ProposalRequestPayload(BaseModel):
    quote_id: Optional[str] = None
    carrier_name: Optional[str] = "Standard Carrier"
    service_name: Optional[str] = "Standard Road LTL"
    origin: str
    destination: str
    weight_lbs: float
    base_rate: float
    total_surcharges: float = 0.0
    surcharges: Optional[List[Dict[str, Any]]] = None
    transit_days: Optional[int] = 3
    currency: Optional[str] = "CAD"
    client_name: Optional[str] = "Client Partner"
    markup_pct: Optional[float] = None
    custom_total: Optional[float] = None
    source_coordinate: Optional[str] = None
    sheet_id: Optional[str] = None
    formula: Optional[str] = None
    skid_count: Optional[int] = None
    calculation_trace: Optional[Any] = None

@app.post("/api/quotes/client-proposal/preview", tags=["Client Proposal Generator"])
def api_quote_client_proposal_preview(
    payload: ProposalRequestPayload,
    request: Request
):
    """
    Constructs a client-facing quote proposal preview with broker margin markups.
    Hides internal carrier wholesale rates and formats clean all-in proposal lines.
    """
    user = require_user(request)
    user_id = user["id"]
    from services.auth_service import get_user_profile
    profile = get_user_profile(user_id) or {}

    markup = payload.markup_pct if payload.markup_pct is not None else float(profile.get("markup_pct", 15.0))
    broker_info = {
        "company": profile.get("company") or user.get("company") or "",
        "name": profile.get("name") or user.get("name") or "",
        "email": profile.get("email") or user.get("email") or "",
        "origin_zip": profile.get("origin_zip") or user.get("origin_zip") or payload.origin
    }

    from services.proposal_service import build_client_proposal_data
    proposal = build_client_proposal_data(
        quote_data=payload.dict(),
        client_name=payload.client_name or "Client Partner",
        broker_info=broker_info,
        markup_pct=markup,
        custom_total=payload.custom_total
    )
    # Persist active proposal draft until next quote calculation
    save_active_proposal(user_id, proposal)

    # Persist the quote to the database table (Quotes History)
    from services.db_service import save_proposal_quote_item
    save_proposal_quote_item(
        user_id=user_id,
        proposal=proposal,
        quote_data=payload.dict()
    )

    return {"status": "success", "proposal": proposal}

@app.get("/api/quotes/client-proposal/memory", tags=["Client Proposal Generator"])
def api_get_client_proposal_memory(request: Request):
    """
    Returns the currently active client proposal stored in memory for the user session, if any.
    Will return has_active_proposal: false once the user calculates their next quote.
    """
    user = require_user(request)
    user_id = user["id"]
    active = get_active_proposal(user_id)
    return {
        "status": "success",
        "has_active_proposal": active is not None,
        "proposal": active
    }

@app.delete("/api/quotes/client-proposal/memory", tags=["Client Proposal Generator"])
def api_clear_client_proposal_memory(request: Request):
    """Explicitly purges any client proposal from memory."""
    user = require_user(request)
    user_id = user["id"]
    deleted = clear_active_proposal(user_id)
    return {
        "status": "success",
        "purged": deleted,
        "message": "Client proposal purged from memory"
    }

@app.post("/api/quotes/client-proposal/excel", tags=["Client Proposal Generator"])
def api_quote_client_proposal_excel(
    payload: ProposalRequestPayload,
    request: Request
):
    """
    Generates and downloads a branded client freight quote proposal Excel workbook (.xlsx).
    Features navy executive styling, formatted CAD currency, and standard commercial terms.
    """
    user = require_user(request)
    user_id = user["id"]
    from services.auth_service import get_user_profile
    profile = get_user_profile(user_id) or {}

    markup = payload.markup_pct if payload.markup_pct is not None else float(profile.get("markup_pct", 15.0))
    broker_info = {
        "company": profile.get("company") or user.get("company") or "",
        "name": profile.get("name") or user.get("name") or "",
        "email": profile.get("email") or user.get("email") or "",
        "origin_zip": profile.get("origin_zip") or user.get("origin_zip") or payload.origin
    }

    from services.proposal_service import build_client_proposal_data, generate_proposal_excel_workbook
    proposal = build_client_proposal_data(
        quote_data=payload.dict(),
        client_name=payload.client_name or "Client Partner",
        broker_info=broker_info,
        markup_pct=markup,
        custom_total=payload.custom_total
    )
    save_active_proposal(user_id, proposal)

    from services.db_service import save_proposal_quote_item
    save_proposal_quote_item(
        user_id=user_id,
        proposal=proposal,
        quote_data=payload.dict()
    )

    wb_bytes = generate_proposal_excel_workbook(proposal)
    clean_id = proposal["proposal_id"].replace(" ", "_")

    return Response(
        content=wb_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Quotelytics_Client_Proposal_{clean_id}.xlsx"}
    )

@app.post("/api/user/account/update", tags=["User Profile"])
async def api_update_account(request: Request):
    """Updates user profile details, contact phone, and quoting origin defaults."""
    user = require_user(request)
    user_id = user["id"]
    
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        name = body.get("name", "")
        company = body.get("company", "")
        origin_zip = body.get("origin_zip", "TORONTO, ON")
        origin_address = body.get("origin_address", "")
        phone = body.get("phone", "")
    else:
        form = await request.form()
        name = form.get("name", "")
        company = form.get("company", "")
        origin_zip = form.get("origin_zip", "TORONTO, ON")
        origin_address = form.get("origin_address", "")
        phone = form.get("phone", "")
        
    if not name or not company:
        raise HTTPException(status_code=400, detail="Name and company are required.")
        
    from services.db_service import update_user_account
    return update_user_account(user_id, str(name), str(company), str(origin_zip), str(origin_address or ""), str(phone or ""))

@app.post("/api/user/password", tags=["User Profile"])
async def api_update_password(request: Request):
    """Updates user password after verifying current password hash."""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user_id = user["id"]
    
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        current_password = body.get("current_password", "")
        new_password = body.get("new_password", "")
    else:
        form = await request.form()
        current_password = form.get("current_password", "")
        new_password = form.get("new_password", "")
        
    if not current_password:
        raise HTTPException(status_code=400, detail="Current password is required.")
    if not new_password or len(new_password) < 10:
        raise HTTPException(status_code=400, detail="New password must be at least 10 characters long.")
        
    from services.db_service import update_user_password
    success, message = update_user_password(user_id, str(current_password), str(new_password))
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.get("/api/user/data-export", tags=["User Profile"])
@app.get("/api/pipeda/export", tags=["User Profile"])
def api_export_user_data(request: Request):
    """PIPEDA Principle 9 Individual Access & Data Portability export."""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user_id = user["id"]
    from services.db_service import export_user_data
    export_payload = export_user_data(user_id)
    filename = f"quotelytics_data_export_{user_id}.json"
    return Response(
        content=json.dumps(export_payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/user/account/delete", tags=["User Profile"])
@app.delete("/api/user/account", tags=["User Profile"])
async def api_delete_user_account(request: Request, response: Response):
    """PIPEDA §10 Account & Data Deletion endpoint."""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user_id = user["id"]

    immediate_purge = True
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict) and "immediate_purge" in body:
                immediate_purge = bool(body["immediate_purge"])
        except Exception:
            pass

    clear_active_proposal(user_id)
    from services.db_service import delete_user_account_data
    result = delete_user_account_data(user_id, immediate_purge=immediate_purge)
    _clear_session_cookies(response)
    return result


@app.post("/api/user/marketing-consent", tags=["User Profile"])
async def api_update_marketing_consent(request: Request):
    """CASL Marketing Consent opt-in / withdrawal endpoint."""
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        consented = bool(body.get("marketing_opt_in", False))
        form_version = str(body.get("form_version", "v2026.10"))
    else:
        form = await request.form()
        val = str(form.get("marketing_opt_in", "false")).lower()
        consented = val in ("1", "true", "yes", "on")
        form_version = str(form.get("form_version", "v2026.10"))

    from services.auth_service import record_marketing_consent
    consent_id = record_marketing_consent(
        user_id=user["id"],
        email=user.get("email", ""),
        consented=consented,
        consent_type="ACCOUNT_OPT_IN" if consented else "ACCOUNT_WITHDRAWN",
        form_version=form_version,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    return {
        "status": "success",
        "consent_id": consent_id,
        "marketing_opt_in": consented,
        "message": "Marketing communication preferences updated.",
    }

class WebhookCreatePayload(BaseModel):
    url: str
    description: Optional[str] = ""
    events: Optional[str] = "batch.quote.completed"


class BatchQuoteShipmentItem(BaseModel):
    origin: Optional[str] = None
    origin_zip: Optional[str] = None
    destination: Optional[str] = None
    dest_zip: Optional[str] = None
    actual_weight: Optional[float] = None
    weight_lbs: Optional[float] = None
    weight: Optional[float] = None
    skid_count: Optional[int] = None
    skids: Optional[int] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    accessorials: Optional[List[str]] = None
    shipment_date: Optional[str] = None
    shipping_mode: Optional[str] = "LTL"
    service: Optional[str] = None


class BatchQuoteRequestPayload(BaseModel):
    shipments: List[BatchQuoteShipmentItem]
    apply_markup: bool = True


def _extract_sample_lane_for_sheet(sheet: Dict[str, Any], user_id: str, fallback_origin: str) -> Tuple[str, str]:
    """Selects a concrete (origin, destination) lane from a confirmed sheet's breaks or zones for readiness verification."""
    from services.quotelytics_db_service import get_sheet_full_rules
    rules = get_sheet_full_rules(sheet["id"], user_id, limit=30)
    wildcards = {"", "*", "ALL", "ANY", "DEFAULT"}
    for brk in rules.get("breaks", []):
        o_spec = (brk.get("origin_spec") or "").strip()
        d_spec = (brk.get("dest_spec") or "").strip()
        if o_spec.upper() not in wildcards and d_spec.upper() not in wildcards:
            return o_spec, d_spec
    for z in rules.get("zones", []):
        o_spec = (z.get("origin_spec") or "").strip()
        d_spec = (z.get("dest_spec") or "").strip()
        if o_spec.upper() not in wildcards and d_spec.upper() not in wildcards:
            return o_spec, d_spec
    return (fallback_origin or "TORONTO, ON"), "MONTREAL, QC"


def _build_user_api_onboarding_summary(user_id: str, keys: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Builds plain-English readiness counts for the Console Developer API guided checklist."""
    from services.quotelytics_db_service import list_rate_sheets
    profile = get_user_profile(user_id) or {}
    all_sheets = list_rate_sheets(user_id=user_id)
    confirmed_sheets = [
        s for s in all_sheets
        if s.get("confirmation_status") != "ARCHIVED"
        and (s.get("confirmation_status") == "CONFIRMED" or s.get("manual_override") == 1)
    ]
    active_keys = [k for k in keys if not k.get("revoked_at") and k.get("status") != "REVOKED"]
    default_origin = (profile.get("origin_zip") or "").strip()

    sample_lane = None
    if confirmed_sheets:
        top_sheet = confirmed_sheets[0]
        s_orig, s_dest = _extract_sample_lane_for_sheet(top_sheet, user_id, default_origin)
        sample_lane = {
            "sheet_id": top_sheet["id"],
            "carrier": top_sheet["carrier_name"],
            "service": top_sheet["service_name"],
            "origin": s_orig,
            "destination": s_dest,
        }

    return {
        "confirmed_sheets_count": len(confirmed_sheets),
        "active_keys_count": len(active_keys),
        "active_key_prefix": active_keys[0]["key_prefix"] if active_keys else None,
        "default_origin": default_origin,
        "markup_pct": float(profile.get("markup_pct", 0.0)),
        "currency": profile.get("currency", "CAD"),
        "company": profile.get("company", ""),
        "sample_lane": sample_lane,
    }


@app.get("/api/user/api-keys", tags=["Business API"])
def api_list_user_keys(request: Request):
    """Lists API key metadata and 3-step onboarding readiness for the authenticated user."""
    user = require_user(request)
    from services.db_service import list_api_keys
    tier = (user.get("tier") or "FREE").upper()
    keys = list_api_keys(user["id"])
    return {
        "tier": tier,
        "has_api_access": tier == "BUSINESS",
        "keys": keys,
        "onboarding": _build_user_api_onboarding_summary(user["id"], keys),
    }


@app.post("/api/user/api-readiness-check", tags=["Business API"])
def api_check_user_api_readiness(request: Request):
    """
    1-Click Non-Technical Setup Verification:
    Executes a read-only in-memory sample quote against the tenant's confirmed LTL tariff
    without writing audit rows or consuming monthly quote counters.
    """
    user = require_user(request)
    verify_csrf(request)
    if (user.get("tier") or "").upper() != "BUSINESS":
        raise HTTPException(
            status_code=403,
            detail="Business tier subscription required to run API readiness verification.",
        )

    user_id = user["id"]
    profile = get_user_profile(user_id) or {}
    default_origin = (profile.get("origin_zip") or "TORONTO, ON").strip() or "TORONTO, ON"
    markup_dec = Decimal(str(profile.get("markup_pct", 0.0)))
    markup_mult = Decimal("1") + (markup_dec / Decimal("100"))

    from services.quotelytics_db_service import list_rate_sheets
    from services.quotelytics_engine import calculate_quote_for_sheet

    all_sheets = list_rate_sheets(user_id=user_id)
    confirmed_sheets = [
        s for s in all_sheets
        if s.get("confirmation_status") != "ARCHIVED"
        and (s.get("confirmation_status") == "CONFIRMED" or s.get("manual_override") == 1)
    ]

    if not confirmed_sheets:
        return {
            "ready": False,
            "reason": "NO_CONFIRMED_SHEETS",
            "message": "Step 2 Incomplete: Please upload and confirm at least one LTL carrier rate sheet in Carrier Tariffs first.",
        }

    t0 = time.perf_counter()
    last_err = ""
    for sheet in confirmed_sheets:
        s_orig, s_dest = _extract_sample_lane_for_sheet(sheet, user_id, default_origin)
        try:
            q_res = calculate_quote_for_sheet(
                sheet_id=sheet["id"],
                user_id=user_id,
                origin=s_orig,
                destination=s_dest,
                actual_weight=1000.0,
                skid_count=2,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            base_dec = Decimal(str(q_res["final_total"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            final_dec = (base_dec * markup_mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return {
                "ready": True,
                "elapsed_ms": elapsed_ms,
                "confirmed_sheets_count": len(confirmed_sheets),
                "sample_quote": {
                    "carrier": q_res["carrier_name"],
                    "service": q_res["service_name"],
                    "origin": s_orig,
                    "destination": s_dest,
                    "actual_weight": 1000.0,
                    "skid_count": 2,
                    "base_rate": float(base_dec),
                    "markup_pct": float(markup_dec),
                    "final_rate": float(final_dec),
                    "currency": q_res.get("currency") or profile.get("currency", "CAD"),
                    "coordinate": q_res.get("source_coordinate") or q_res.get("source_cell") or "",
                },
            }
        except Exception as exc:
            last_err = str(exc)

    return {
        "ready": False,
        "reason": "SAMPLE_QUOTE_FAILED",
        "message": f"Confirmed sheet found, but sample lane check could not complete: {last_err}",
    }


@app.post("/api/user/api-key/generate", tags=["Business API"])
async def api_generate_key(request: Request):
    """Generates a new API Key for Embedded Quoting. Requires BUSINESS tier; returns raw secret once."""
    user = require_user(request)
    verify_csrf(request)
    if (user.get("tier") or "").upper() != "BUSINESS":
        raise HTTPException(
            status_code=403,
            detail="Embedded Quoting API keys require an active Business tier subscription.",
        )

    content_type = (request.headers.get("content-type") or "").lower()
    key_name = "Production Key"
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("name"):
                key_name = str(body["name"])
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            if form.get("name"):
                key_name = str(form.get("name"))
        except Exception:
            pass

    from services.db_service import create_api_key_record
    try:
        record = create_api_key_record(user["id"], key_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "success",
        "id": record["id"],
        "name": record["name"],
        "api_key": record["api_key"],
        "key_prefix": record["key_prefix"],
        "created_at": record["created_at"],
    }


@app.delete("/api/user/api-keys/{key_id}", tags=["Business API"])
def api_revoke_user_key(key_id: str, request: Request):
    """Revokes an API key owned by the authenticated session user."""
    user = require_user(request)
    verify_csrf(request)
    from services.db_service import revoke_api_key
    revoked = revoke_api_key(user["id"], key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found or already revoked.")
    return {"status": "revoked", "id": key_id}


@app.get("/api/user/webhooks", tags=["Business API"])
def api_list_user_webhooks(request: Request):
    """Lists configured webhook endpoints and recent delivery receipts for Business tenants."""
    user = require_user(request)
    tier = (user.get("tier") or "FREE").upper()
    if tier != "BUSINESS":
        return {"tier": tier, "has_api_access": False, "endpoints": [], "deliveries": []}
    from services.webhook_service import list_webhook_endpoints
    data = list_webhook_endpoints(user["id"])
    return {
        "tier": tier,
        "has_api_access": True,
        "endpoints": data["endpoints"],
        "deliveries": data["deliveries"],
    }


@app.post("/api/user/webhooks", tags=["Business API"])
def api_create_user_webhook(payload: WebhookCreatePayload, request: Request):
    """Registers an SSRF-validated outbound webhook endpoint for Business batch completion events."""
    user = require_user(request)
    verify_csrf(request)
    if (user.get("tier") or "").upper() != "BUSINESS":
        raise HTTPException(
            status_code=403,
            detail="Batch calculation webhooks require an active Business tier subscription.",
        )
    from services.webhook_service import create_webhook_endpoint
    try:
        endpoint = create_webhook_endpoint(
            user_id=user["id"],
            url=payload.url,
            description=payload.description or "",
            events=payload.events or "batch.quote.completed",
        )
    except ValueError as exc:
        raise _StructuredAPIError(
            status_code=422,
            payload={"error": "E_WEBHOOK_INVALID_URL", "detail": str(exc)},
        )
    return {"status": "success", "endpoint": endpoint}


@app.delete("/api/user/webhooks/{endpoint_id}", tags=["Business API"])
def api_delete_user_webhook(endpoint_id: str, request: Request):
    """Deletes a webhook endpoint owned by the authenticated Business user."""
    user = require_user(request)
    verify_csrf(request)
    from services.webhook_service import delete_webhook_endpoint
    deleted = delete_webhook_endpoint(user["id"], endpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found.")
    return {"status": "deleted", "id": endpoint_id}


@app.post("/api/user/webhooks/{endpoint_id}/test", tags=["Business API"])
def api_test_user_webhook(endpoint_id: str, request: Request):
    """Sends a signed synthetic batch.quote.test ping to a registered Business webhook endpoint."""
    user = require_user(request)
    verify_csrf(request)
    if (user.get("tier") or "").upper() != "BUSINESS":
        raise HTTPException(status_code=403, detail="Active Business tier subscription required.")
    from services.webhook_service import dispatch_batch_webhook_event
    test_batch_id = f"BCH-TEST-{uuid.uuid4().hex[:6].upper()}"
    receipts = dispatch_batch_webhook_event(
        user_id=user["id"],
        event_type="batch.quote.test",
        batch_id=test_batch_id,
        payload_data={
            "status": "success",
            "batch_id": test_batch_id,
            "account": user.get("company") or "",
            "total_quotes": 1,
            "test": True,
        },
        target_endpoint_id=endpoint_id,
        max_attempts=1,
    )
    if not receipts:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found or inactive.")
    return {"status": "sent", "receipt": receipts[0]}


@app.post("/api/v1/quotes/batch", tags=["Business API"])
def api_v1_embedded_batch_quotes(
    payload: BatchQuoteRequestPayload,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Deterministic Embedded Batch Quoting API for Business / 3PL integrations.
    Requires header 'X-API-Key: ql_live_...' (or an active BUSINESS session).
    Evaluates up to 100 LTL shipments per call against confirmed tenant rate sheets (Rule 1, Rules 8-15, Rule 30).
    """
    user = require_quoting_user(request, require_business_session=True)
    user_id = user["id"]

    if not payload.shipments or len(payload.shipments) > 100:
        raise _StructuredAPIError(
            status_code=422,
            payload={
                "error": "E_INVALID_BATCH_SIZE",
                "detail": "Payload 'shipments' array must contain between 1 and 100 items.",
            },
        )

    profile = get_user_profile(user_id)
    origin_fallback = (profile.get("origin_zip") or "").strip()
    effective_markup_dec = (
        Decimal(str(profile.get("markup_pct", 0.0))) if payload.apply_markup else Decimal("0.0")
    )

    from services.quotelytics_db_service import (
        get_or_initialize_sunset_timestamps,
        reserve_user_quote_slot,
        release_quote_reservation,
    )
    from services.quotelytics_engine import quote_all_confirmed_carriers
    from services.webhook_service import dispatch_batch_webhook_event

    deploy_ts, sunset_ts = get_or_initialize_sunset_timestamps(sunset_clock)
    now_ts = sunset_clock()
    is_post_sunset = now_ts >= sunset_ts
    is_strict = os.environ.get("FAILSAFE_PARCEL_STRICT", "false").lower() == "true"

    validated_items: List[Dict[str, Any]] = []
    any_dual_signal_parcel = False

    for idx, s in enumerate(payload.shipments):
        mode_upper = (s.shipping_mode or "LTL").strip().upper()
        if mode_upper == "PARCEL":
            raise _StructuredAPIError(
                status_code=422,
                payload={
                    "error": "E_PARCEL_NOT_SUPPORTED",
                    "detail": f"Item {idx + 1}: Quotelytics supports Skid/LTL freight only. Parcel mode is not supported.",
                },
            )

        origin = (s.origin or s.origin_zip or origin_fallback or "").strip()
        if not origin:
            raise _StructuredAPIError(
                status_code=422,
                payload={
                    "error": "E_MISSING_ORIGIN",
                    "detail": f"Item {idx + 1}: 'origin' is required (or configure a default origin in Account settings).",
                },
            )

        destination = (s.destination or s.dest_zip or "").strip()
        if not destination:
            raise _StructuredAPIError(
                status_code=422,
                payload={
                    "error": "E_MISSING_DESTINATION",
                    "detail": f"Item {idx + 1}: 'destination' is required.",
                },
            )

        skid_count = s.skid_count if s.skid_count is not None else s.skids
        if skid_count is not None and skid_count < 0:
            raise _StructuredAPIError(
                status_code=422,
                payload={
                    "error": "E_INVALID_SKID_COUNT",
                    "detail": f"Item {idx + 1}: 'skid_count' cannot be negative.",
                },
            )

        raw_weight = (
            s.actual_weight
            if s.actual_weight is not None
            else (s.weight_lbs if s.weight_lbs is not None else s.weight)
        )
        if raw_weight is not None and raw_weight > 0:
            actual_weight = float(raw_weight)
            effective_skids = skid_count if (skid_count and skid_count > 0) else None
        elif raw_weight is None and skid_count is not None and skid_count > 0:
            actual_weight = float(skid_count * 500.0)
            effective_skids = skid_count
        else:
            raise _StructuredAPIError(
                status_code=422,
                payload={
                    "error": "E_MISSING_WEIGHT",
                    "detail": f"Item {idx + 1}: Positive 'actual_weight' (or positive 'skid_count') is required.",
                },
            )

        is_small_weight = actual_weight < 150.0
        is_unpalletized = effective_skids is None or effective_skids == 0
        is_dual_signal_parcel = is_small_weight and is_unpalletized

        if is_dual_signal_parcel and (is_post_sunset or is_strict):
            return JSONResponse(
                status_code=422,
                content={
                    "error": "E_PARCEL_DEPRECATED_LTL_ONLY",
                    "message": (
                        f"Item {idx + 1}: Quotelytics supports Skid/LTL freight only. Individual package quotes "
                        "under 150 lbs are no longer supported. Please palletize or specify skid count."
                    ),
                    "documentation_url": "https://api.quotelytics.ca/docs/ltl-transition",
                },
            )

        if is_dual_signal_parcel:
            any_dual_signal_parcel = True

        validated_items.append({
            "row_num": idx + 1,
            "origin": origin,
            "destination": destination,
            "actual_weight": actual_weight,
            "skid_count": effective_skids,
            "length": s.length,
            "width": s.width,
            "height": s.height,
            "accessorials": s.accessorials or [],
            "shipment_date": s.shipment_date,
            "requested_service": s.service,
        })

    # Purge any previous client proposal draft upon generating next quote
    clear_active_proposal(user_id)

    quoted_items: List[Dict[str, Any]] = []
    markup_multiplier = Decimal("1") + (effective_markup_dec / Decimal("100"))

    for v in validated_items:
        allowed, quote_id, quota = reserve_user_quote_slot(
            user_id,
            shipment_inputs={
                "origin": v["origin"],
                "destination": v["destination"],
                "actual_weight": v["actual_weight"],
                "skid_count": v["skid_count"],
            },
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Quote volume limit exceeded: You have reached your monthly limit of "
                    f"{quota['max_quotes_per_month'] if quota else 0} quotes."
                ),
            )

        try:
            engine_res = quote_all_confirmed_carriers(
                user_id=user_id,
                origin=v["origin"],
                destination=v["destination"],
                actual_weight=v["actual_weight"],
                length=v["length"],
                width=v["width"],
                height=v["height"],
                accessorials=v["accessorials"],
                shipment_date=v["shipment_date"],
                skid_count=v["skid_count"],
                quote_id=quote_id,
            )
        except Exception as exc:
            release_quote_reservation(quote_id, user_id)
            if isinstance(exc, HTTPException):
                raise exc
            raise HTTPException(status_code=400, detail=f"Item {v['row_num']} calculation error: {str(exc)}")

        carrier_options: List[Dict[str, Any]] = []
        for opt in engine_res.get("quotes", []):
            carrier_base_dec = Decimal(str(opt["final_total"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            marked_up_dec = (carrier_base_dec * markup_multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            coord = opt.get("source_coordinate") or opt.get("source_cell") or ""
            carrier_options.append({
                "sheet_id": opt.get("sheet_id"),
                "carrier": opt.get("carrier_name"),
                "service": opt.get("service_name"),
                "currency": opt.get("currency", profile.get("currency", "CAD")),
                "base_rate": float(carrier_base_dec),
                "carrier_total": float(carrier_base_dec),
                "markup_pct": float(effective_markup_dec),
                "final_rate": float(marked_up_dec),
                "coordinate": coord,
                "billable_weight": opt.get("billable_weight"),
                "rated_weight": opt.get("rated_weight"),
                "rate_break": opt.get("rate_break"),
                "surcharges": opt.get("surcharges", []),
                "transit_days": opt.get("transit_days"),
                "formula": opt.get("formula"),
            })

        if carrier_options:
            best = carrier_options[0]
            item_out: Dict[str, Any] = {
                "row_num": v["row_num"],
                "quote_id": engine_res["quote_id"],
                "status": "quoted",
                "origin": v["origin"],
                "destination": v["destination"],
                "origin_zip": v["origin"],
                "dest_zip": v["destination"],
                "actual_weight": v["actual_weight"],
                "weight_lbs": v["actual_weight"],
                "skid_count": v["skid_count"],
                "carrier": best["carrier"],
                "service": best["service"],
                "currency": best["currency"],
                "base_rate": best["base_rate"],
                "carrier_total": best["carrier_total"],
                "markup_pct": best["markup_pct"],
                "final_rate": best["final_rate"],
                "coordinate": best["coordinate"],
                "carrier_options": carrier_options,
                "excluded_sheets": engine_res.get("excluded_sheets", []),
            }
        else:
            item_out = {
                "row_num": v["row_num"],
                "quote_id": engine_res["quote_id"],
                "status": "no_qualifying_carrier",
                "origin": v["origin"],
                "destination": v["destination"],
                "origin_zip": v["origin"],
                "dest_zip": v["destination"],
                "actual_weight": v["actual_weight"],
                "weight_lbs": v["actual_weight"],
                "skid_count": v["skid_count"],
                "carrier": None,
                "service": None,
                "currency": profile.get("currency", "CAD"),
                "base_rate": None,
                "carrier_total": None,
                "markup_pct": float(effective_markup_dec),
                "final_rate": None,
                "coordinate": None,
                "message": engine_res.get("message"),
                "carrier_options": [],
                "excluded_sheets": engine_res.get("excluded_sheets", []),
            }

        if v["requested_service"]:
            item_out["requested_service"] = v["requested_service"]

        quoted_items.append(item_out)

    batch_id = f"BCH-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    response_data: Dict[str, Any] = {
        "status": "success",
        "batch_id": batch_id,
        "account": user.get("company") or profile.get("company", ""),
        "total_quotes": len(quoted_items),
        "quoted_count": sum(1 for item in quoted_items if item["status"] == "quoted"),
        "unmatched_count": sum(1 for item in quoted_items if item["status"] != "quoted"),
        "markup_pct": float(effective_markup_dec),
        "currency": profile.get("currency", "CAD"),
        "quotes": quoted_items,
        "disclaimer": "Calculation from customer uploaded rate sheets. Non-binding quote (Rule 26).",
    }

    background_tasks.add_task(
        dispatch_batch_webhook_event,
        user_id,
        "batch.quote.completed",
        batch_id,
        response_data,
    )

    if any_dual_signal_parcel:
        sunset_imf = email.utils.formatdate(sunset_ts, usegmt=True)
        deprecation_hdr = f"@{int(deploy_ts)}"
        link_hdr = '<https://api.quotelytics.ca/docs/ltl-transition>; rel="sunset"; type="text/html"'
        response_data["advisory_warnings"] = [
            {
                "code": "WARN_PARCEL_DEPRECATION",
                "message": (
                    "Quotelytics is transitioning exclusively to Skid/LTL freight. Quotes under 150 lbs "
                    "unpalletized will be discontinued after the sunset date. Minimum LTL floor applies."
                ),
                "sunset_date": datetime.utcfromtimestamp(sunset_ts).isoformat() + "Z",
            }
        ]
        resp = JSONResponse(content=response_data, background=background_tasks)
        resp.headers["Sunset"] = sunset_imf
        resp.headers["Deprecation"] = deprecation_hdr
        resp.headers["Link"] = link_hdr
        return resp

    return response_data


# ==============================================================================
# CUSTOM KEYWORD DEFINITIONS FOR AI SHEET MAPPING (Settings API)
# ==============================================================================

class KeywordDefinitionPayload(BaseModel):
    keyword: str
    definition_text: str


@app.get("/api/settings/keywords", tags=["System Settings"])
def api_list_keyword_definitions(request: Request):
    """Returns all custom Excel header keyword definitions for the authenticated user."""
    user = require_user(request)
    from services.db_service import list_user_keyword_definitions
    items = list_user_keyword_definitions(user["id"])
    return {"status": "success", "keywords": items}


@app.post("/api/settings/keywords", tags=["System Settings"])
async def api_upsert_keyword_definition(request: Request):
    """Creates or updates a custom Excel header keyword definition (e.g. L5C -> 'less than 5 skids')."""
    user = require_user(request)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        keyword = str(body.get("keyword") or "").strip()
        definition_text = str(body.get("definition_text") or "").strip()
    else:
        form = await request.form()
        keyword = str(form.get("keyword") or "").strip()
        definition_text = str(form.get("definition_text") or "").strip()

    if not keyword or not definition_text:
        raise HTTPException(status_code=400, detail="Both keyword and definition_text are required.")

    from services.db_service import upsert_user_keyword_definition
    saved = upsert_user_keyword_definition(
        user_id=user["id"],
        keyword=keyword,
        definition_text=definition_text,
    )
    return {"status": "success", "keyword_definition": saved}


@app.delete("/api/settings/keywords/{keyword_id}", tags=["System Settings"])
def api_delete_keyword_definition(keyword_id: str, request: Request):
    """Deletes a custom keyword definition owned by the authenticated user."""
    user = require_user(request)
    from services.db_service import delete_user_keyword_definition
    deleted = delete_user_keyword_definition(user["id"], keyword_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Keyword definition not found.")
    return {"status": "success", "deleted_id": keyword_id}
