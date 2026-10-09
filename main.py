import os
import io
import json
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

from services.ratesift_excel_reformatter import (
    analyze_excel_sheet,
    build_reformatted_excel_workbook,
    SCRATCH_DIR
)


from services.db_service import init_db, get_connection, get_user_quota_info
from services.parser_service import parse_excel_rate_sheet
from services.rating_service import calculate_batch_quotes
from services.auth_service import (
    authenticate_and_create_session,
    register_and_create_session,
    validate_session_token,
    revoke_session,
    get_user_profile
)

from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Initialize database and tables
init_db()

app = FastAPI(
    title="Ratesift Quoting API",
    description="Automated batch shipping rate calculation engine from Excel spreadsheets (.xlsx, .xls). Strictly quoting; no booking or tracking numbers.",
    version="1.0.0"
)

# Active in-memory client proposal drafts: {user_id: proposal_dict}
# Purged automatically when the user calculates their next quote
_active_proposal_memory: Dict[str, Any] = {}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.main import router as failsafe_router
app.include_router(failsafe_router)
app.include_router(failsafe_router, prefix="/api/failsafe")


def get_current_user_from_request(request: Request) -> Optional[dict]:
    """Helper to extract user from session cookie or Authorization header."""
    token = request.cookies.get("ratesift_session") or request.cookies.get("shipflow_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return validate_session_token(token)

def serve_template(template_rel_path: str):
    full_path = os.path.join(TEMPLATES_DIR, template_rel_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"Template {template_rel_path} not found")
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Simple resolver for component includes: {% include "rel/path" %}
    import re
    def _include_replacer(match):
        inc_rel = match.group(1).strip()
        inc_full = os.path.join(TEMPLATES_DIR, inc_rel)
        if os.path.exists(inc_full):
            with open(inc_full, "r", encoding="utf-8") as inc_f:
                return inc_f.read()
        return ""

    content = re.sub(r'\{%\s*include\s+[\'"]([^\'"]+)[\'"]\s*%\}', _include_replacer, content)
    return HTMLResponse(content=content)

# ==========================================
# PUBLIC PAGES (SEO-Optimized & Crawlable)
# ==========================================

@app.get("/", response_class=HTMLResponse, tags=["Public Pages"])
def get_home_page():
    """RateSift SEO Landing Page"""
    return serve_template("public/home.html")

@app.get("/demo", response_class=HTMLResponse, tags=["Public Pages"])
def get_demo_page():
    """Interactive Public Demo with sample rate sheets"""
    return serve_template("public/demo.html")

@app.get("/pricing", response_class=HTMLResponse, tags=["Public Pages"])
def get_pricing_page():
    """Public Pricing Page (4 Tiers with Business Custom)"""
    return serve_template("public/pricing.html")

@app.get("/login", response_class=HTMLResponse, tags=["Public Pages"])
def get_login_page(request: Request):
    """Single-centered Log In screen. If already logged in, redirects to console."""
    user = get_current_user_from_request(request)
    if user:
        return RedirectResponse(url="/console/new-quote", status_code=303)
    return serve_template("public/login.html")

@app.get("/get-started", response_class=HTMLResponse, tags=["Public Pages"])
def get_get_started_page(request: Request):
    """Single-centered Create Your Account screen. If already logged in, redirects to console."""
    user = get_current_user_from_request(request)
    if user:
        return RedirectResponse(url="/console/new-quote", status_code=303)
    return serve_template("public/get_started.html")

# ==========================================
# PRIVATE CONSOLE PAGES (Route Guarded)
# ==========================================

@app.get("/console/new-quote", response_class=HTMLResponse, tags=["Console Pages"])
def get_new_quote_page(request: Request):
    """Default Console View: 'New rate sheet' with 'Process ->'. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/new-quote", status_code=303)
    return serve_template("console/new_quote.html")

@app.get("/console/history", response_class=HTMLResponse, tags=["Console Pages"])
def get_history_page(request: Request):
    """Quotes History Warehouse with cell coordinates. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/history", status_code=303)
    return serve_template("console/history.html")

@app.get("/console/rate-sheets", response_class=HTMLResponse, tags=["Console Pages"])
def get_rate_sheets_page(request: Request):
    """Rate Sheets Warehouse and Human Confirmation Gate. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/rate-sheets", status_code=303)
    return serve_template("console/rate_sheets.html")


@app.get("/console/account", response_class=HTMLResponse, tags=["Console Pages"])
def get_account_page(request: Request):
    """Alex Rivers / TechCorp Logistics Account Profile. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/account", status_code=303)
    return serve_template("console/account.html")

@app.get("/console/settings", response_class=HTMLResponse, tags=["Console Pages"])
def get_settings_page(request: Request):
    """System & Quoting Settings (Currency, Units, Markup, Toggles). Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/settings", status_code=303)
    return serve_template("console/settings.html")

# ==========================================
# ARCHITECTURE & SHOWCASE
# ==========================================

@app.get("/failsafe/demo", response_class=HTMLResponse, tags=["Architecture"])
def get_failsafe_demo_page():
    """Failsafe Header Mapping Modal UI Playground."""
    full_path = os.path.join(TEMPLATES_DIR, "console", "failsafe_demo.html")
    comp_path = os.path.join(TEMPLATES_DIR, "console", "components", "mapping_modal.html")
    with open(full_path, "r", encoding="utf-8") as f:
        demo_html = f.read()
    with open(comp_path, "r", encoding="utf-8") as f:
        comp_html = f.read()
    rendered = demo_html.replace('{% include "console/components/mapping_modal.html" %}', comp_html)
    return HTMLResponse(content=rendered)

@app.get("/flowchart", response_class=HTMLResponse, tags=["Architecture"])
def get_flowchart_page():
    """Interactive Page Architecture & Routing Flowchart"""
    return serve_template("flowchart.html")

@app.get("/showcase", response_class=HTMLResponse, tags=["Architecture"])
def get_showcase_page():
    """Master Design Suite Showcase with 10 Live Tabs"""
    return serve_template("showcase.html")

# ==========================================
# REST API ENDPOINTS
# ==========================================

@app.post("/api/auth/login", tags=["Authentication"])
def api_login(response: Response, email: str = Form(...), password: str = Form(...)):
    """Authenticates credentials and issues an HTTP-only session cookie."""
    user, token = authenticate_and_create_session(email, password)
    if not user or not token:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
        
    response.set_cookie(
        key="ratesift_session",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax"
    )
    response.set_cookie(
        key="shipflow_session",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax"
    )
    return {
        "status": "success",
        "user": user,
        "token": token,
        "redirect": "/console/new-quote"
    }

@app.post("/api/auth/register", tags=["Authentication"])
def api_register(
    response: Response,
    name: str = Form(...),
    email: str = Form(...),
    company: str = Form(...),
    origin_zip: str = Form("TORONTO, ON"),
    password: str = Form("RateSiftDemo2026!")
):
    """Registers account on Free Starter tier and establishes session."""
    user, token = register_and_create_session(name, email, company, origin_zip, password)
    response.set_cookie(
        key="ratesift_session",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax"
    )
    response.set_cookie(
        key="shipflow_session",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax"
    )
    return {
        "status": "success",
        "user": user,
        "token": token,
        "redirect": "/console/new-quote"
    }

@app.get("/api/auth/logout", tags=["Authentication"])
def api_logout(request: Request, response: Response):
    """Revokes session and redirects to public landing page."""
    token = request.cookies.get("ratesift_session") or request.cookies.get("shipflow_session")
    if token:
        revoke_session(token)
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(key="ratesift_session")
    resp.delete_cookie(key="shipflow_session")
    return resp

@app.get("/api/auth/status", tags=["Authentication"])
def api_auth_status(request: Request):
    """Returns currently authenticated user session or null."""
    user = get_current_user_from_request(request)
    return {"authenticated": bool(user), "user": user}

@app.get("/api/user/quota", tags=["Subscription & Quotas"])
def api_user_quota(request: Request):
    """Retrieves subscription tier quota details and quote usage."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    quota = get_user_quota_info(user_id)
    if not quota:
        raise HTTPException(status_code=404, detail="User quota record not found")
    return quota

class UpgradeTierPayload(BaseModel):
    tier: str

@app.post("/api/user/upgrade-tier", tags=["Subscription & Quotas"])
def api_upgrade_tier(payload: UpgradeTierPayload, request: Request):
    """Upgrades or modifies subscription tier (e.g. FREE -> PRO -> TEAM -> BUSINESS)."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.db_service import update_user_tier
    success = update_user_tier(user_id, payload.tier)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid tier or update failed.")
    return {"status": "success", "new_tier": payload.tier.upper(), "quota": get_user_quota_info(user_id)}

@app.get("/api/user/bottlenecks", tags=["Subscription & Quotas"])
def api_user_bottlenecks(request: Request, limit: int = 50):
    """Retrieves logged bottleneck incidents for the active user."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.db_service import list_bottleneck_events
    events = list_bottleneck_events(user_id=user_id, limit=limit)
    return {"bottlenecks": events, "total": len(events)}

@app.get("/api/admin/bottlenecks", tags=["Subscription & Quotas"])
def api_admin_bottlenecks(limit: int = 100):
    """Global bottleneck telemetry across tenants to identify upgrade triggers."""
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.db_service import remove_organization_member
    success = remove_organization_member(user_id, member_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found or unauthorized.")
    return {"status": "success", "message": "Member seat revoked."}

@app.get("/api/user/profile", tags=["User Profile"])
def api_profile(request: Request):
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    return get_user_profile(user_id)

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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.db_service import list_system_notifications
    return list_system_notifications(user_id=user_id, limit=limit)

@app.post("/api/notifications/read-all", tags=["System Notifications"])
def api_mark_all_notifications_read(request: Request):
    """Marks all system notifications as read for current user."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.db_service import mark_all_system_notifications_read
    count = mark_all_system_notifications_read(user_id)
    return {"status": "success", "marked_read": count}

@app.post("/api/notifications/{notification_id}/read", tags=["System Notifications"])
def api_mark_notification_read(notification_id: str, request: Request):
    """Marks a single system notification as read."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    
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
    
    # Purge any previous client proposal from memory upon generating next quote
    _active_proposal_memory.pop(user_id, None)

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

@app.post("/api/quotes/analyze-excel", tags=["RateSift Excel Re-formatter"])
async def api_analyze_excel(
    request: Request,
    file: UploadFile = File(...)
):
    """
    Phase 1: Analyzes an uploaded Excel spreadsheet, detects table boundaries, column semantics,
    and units, identifying any missing or ambiguous fields for user clarification (Rules 1, 3, 5, 6, 25).
    """
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only spreadsheet files (.xlsx, .xls, .csv) are supported.")
        
    content = await file.read()
    try:
        analysis = analyze_excel_sheet(content, file.filename)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel analysis error: {str(e)}")

@app.post("/api/quotes/confirm-reformatted", tags=["RateSift Excel Re-formatter"])
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    user_hq_origin = (user.get("origin_zip") if user else None) or "CALGARY, AB"
    
    token = payload.analysis_token
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
    with open(reformatted_file_path, "wb") as f:
        f.write(reformatted_bytes)
        
    # Rate each shipment deterministically against confirmed tariffs (Rules 8-15)
    from services.ratesift_engine import quote_all_confirmed_carriers
    
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
            
    batch_id = f"rs_batch_{uuid.uuid4().hex[:10]}"
    
    return {
        "status": "success",
        "batch_id": batch_id,
        "analysis_token": token,
        "filename": meta["filename"],
        "total_shipments": len(rows),
        "rated_shipments": rated_results,
        "download_url": f"/api/quotes/download-reformatted/{token}"
    }

@app.get("/api/quotes/download-reformatted/{analysis_token}", tags=["RateSift Excel Re-formatter"])
def api_download_reformatted_excel(analysis_token: str):
    """Downloads the sanitized, reformatted standardized Excel workbook (.xlsx)."""
    file_path = os.path.join(SCRATCH_DIR, f"reformatted_{analysis_token}.xlsx")
    if not os.path.exists(file_path):
        # Check if raw upload was staged and generate on demand
        payload_path = os.path.join(SCRATCH_DIR, f"staged_analysis_{analysis_token}.json")
        if os.path.exists(payload_path):
            with open(payload_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            wb_bytes = build_reformatted_excel_workbook(data["all_rows"], data["meta"]["filename"])
            with open(file_path, "wb") as f:
                f.write(wb_bytes)
        else:
            raise HTTPException(status_code=404, detail="Reformatted spreadsheet not found or expired.")
            
    return FileResponse(
        path=file_path,
        filename=f"reformatted_{analysis_token}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.get("/api/quotes/history", tags=["Quoting Engine"])
def api_get_quotes_history(request: Request, search: Optional[str] = None, sort_by: str = "date"):
    """Fetches historical quotes with exact cell coordinates."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    
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

    from services.ratesift_db_service import list_rate_sheets
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
# RATESIFT CARRIER RATE SHEETS & CONFIRMATION GATE (Rules 1-7, 19)
# ==============================================================================

@app.post("/api/ratesift/sheets/upload", tags=["RateSift Rate Sheets"])
async def api_ratesift_upload_sheet(
    request: Request,
    file: UploadFile = File(...)
):
    """
    Ingests an Excel (.xlsx, .xls) or CSV rate sheet.
    Deep extracts terms, accessorials, hidden rows/cols, units, and rates.
    Flags uncertain cells and requires human confirmation (Rules 1, 4, 5, 6, 7).
    """
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"

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
        from services.ratesift_extractor import RateSiftExtractor
        extractor = RateSiftExtractor(file_bytes=content, filename=file.filename, user_id=user_id)
        result = extractor.process()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Rate sheet extraction error: {str(e)}")

@app.get("/api/ratesift/sheets", tags=["RateSift Rate Sheets"])
def api_ratesift_list_sheets(request: Request, status: Optional[str] = None):
    """Lists rate sheets for the authenticated tenant (Rule 28)."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import list_rate_sheets
    sheets = list_rate_sheets(user_id=user_id, status=status)
    return {"sheets": sheets}

@app.get("/api/ratesift/sheets/{sheet_id}", tags=["RateSift Rate Sheets"])
def api_ratesift_get_sheet(sheet_id: str, request: Request, limit: Optional[int] = None, offset: int = 0):
    """Retrieves sheet rules, accessorials, breaks (optionally paginated for speed), minimums, and review flags."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import get_sheet_full_rules, get_rate_sheet_cells
    full_rules = get_sheet_full_rules(sheet_id, user_id, limit=limit, offset=offset)
    if not full_rules or not full_rules.get("sheet"):
        raise HTTPException(status_code=404, detail="Rate sheet not found or unauthorized.")
    flagged_cells = get_rate_sheet_cells(sheet_id, user_id, needs_review_only=True)
    full_rules["flagged_cells"] = flagged_cells
    return full_rules

@app.get("/api/ratesift/sheets/{sheet_id}/breaks", tags=["RateSift Rate Sheets"])
def api_ratesift_get_sheet_breaks(
    sheet_id: str,
    request: Request,
    page: int = 1,
    limit: int = 50,
    query: Optional[str] = None
):
    """Returns weight breaks with high-performance server-side pagination and real-time search."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import get_sheet_breaks_paginated
    return get_sheet_breaks_paginated(sheet_id, user_id, page=page, limit=limit, query=query)

@app.post("/api/ratesift/sheets/{sheet_id}/confirm", tags=["RateSift Rate Sheets"])
async def api_ratesift_confirm_sheet(sheet_id: str, request: Request):
    """Enforces human confirmation gate (Rule 7, 19) confirming core rules (Rule 5, 15, 16) and broker markup."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    confirmed_by = user["name"] if user else "Alex Rivers"
    
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
        
    from services.ratesift_db_service import confirm_rate_sheet
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

@app.post("/api/ratesift/sheets/{sheet_id}/markup", tags=["RateSift Rate Sheets"])
async def api_ratesift_update_markup(sheet_id: str, request: Request):
    """Updates broker margin markup rules and confirmed rules on a rate sheet."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    
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
    
    from services.ratesift_db_service import update_rate_sheet_markup
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

@app.post("/api/ratesift/sheets/{sheet_id}/surcharges/{surcharge_code}/waive", tags=["RateSift Rate Sheets"])
async def api_ratesift_toggle_surcharge_waive(sheet_id: str, surcharge_code: str, request: Request):
    """Toggles waived fee status for a carrier surcharge (Rule 4 & 11)."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    try:
        body = await request.json()
        is_waived = bool(body.get("is_waived", True))
    except Exception:
        is_waived = True
    from services.ratesift_db_service import toggle_surcharge_waived
    success = toggle_surcharge_waived(sheet_id, user_id, surcharge_code, is_waived)
    if not success:
        raise HTTPException(status_code=404, detail="Surcharge not found.")
    return {"status": "success", "is_waived": is_waived}

@app.post("/api/ratesift/sheets/{sheet_id}/cells/resolve", tags=["RateSift Rate Sheets"])
async def api_ratesift_resolve_cell(sheet_id: str, request: Request):
    """Marks a flagged cell coordinate as verified by human broker (Rule 6)."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    body = await request.json()
    cell_coord = body.get("cell_coord")
    if not cell_coord:
        raise HTTPException(status_code=400, detail="cell_coord required")
    from services.ratesift_db_service import resolve_flagged_cell
    success = resolve_flagged_cell(sheet_id, user_id, cell_coord)
    return {"status": "success", "cell_coord": cell_coord}

@app.get("/api/ratesift/sheets/{sheet_id}/formatted-matrix", tags=["RateSift Rate Sheets"])
def api_ratesift_formatted_matrix(
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import get_rate_sheet, get_sheet_breaks_paginated
    
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

@app.get("/api/ratesift/sheets/{sheet_id}/download-formatted", tags=["RateSift Rate Sheets"])
def api_ratesift_block_download(sheet_id: str):
    """Permanently blocked endpoint for formatted rate sheets."""
    raise HTTPException(
        status_code=403,
        detail="Security Policy Violation: Rate sheet downloads are permanently disabled. Tariffs may only be inspected in-browser (Rule 3 & Invariant)."
    )

@app.post("/api/ratesift/sheets/{sheet_id}/archive", tags=["RateSift Rate Sheets"])
def api_ratesift_archive_sheet(sheet_id: str, request: Request):
    """Archives a rate sheet so it is no longer quoted."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import archive_rate_sheet
    success = archive_rate_sheet(sheet_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rate sheet not found.")
    return {"status": "success", "message": "Rate sheet archived."}

@app.delete("/api/ratesift/sheets/{sheet_id}", tags=["RateSift Rate Sheets"])
def api_ratesift_delete_sheet(sheet_id: str, request: Request):
    """Deletes a rate sheet."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import delete_rate_sheet
    success = delete_rate_sheet(sheet_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rate sheet not found.")
    return {"status": "success", "message": "Rate sheet deleted."}

@app.get("/api/ratesift/sheets/{sheet_id}/cells", tags=["RateSift Rate Sheets"])
def api_ratesift_get_cells(sheet_id: str, request: Request, needs_review_only: bool = False):
    """Returns cell coordinate traceability logs (Rule 3)."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import get_rate_sheet_cells
    cells = get_rate_sheet_cells(sheet_id, user_id, needs_review_only=needs_review_only)
    return {"sheet_id": sheet_id, "cells": cells}

# ==============================================================================
# RATESIFT DETERMINISTIC QUOTING ENGINE (Rules 8-15, 20, 26, 30)
# ==============================================================================

class QuoteRequestPayload(BaseModel):
    origin: str
    destination: str
    actual_weight: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    accessorials: Optional[List[str]] = None
    shipment_date: Optional[str] = None
    skid_count: Optional[int] = None
    shipping_mode: Optional[str] = "STANDARD"

@app.post("/api/ratesift/quotes/calculate", tags=["RateSift Quoting Core"])
def api_ratesift_calculate_quote(
    payload: QuoteRequestPayload,
    request: Request
):
    """
    Calculates shipping rate quotes deterministically from confirmed sheets (Rules 8-15).
    Enforces Rule 9 (DIM divisors), Rule 10 (Zone resolution), Rule 11 (Itemized surcharges),
    Rule 12 (Minimum charge check), Rule 13 (Full line-item breakdown),
    Rule 15 (Final rounding), and Rule 30 (Audit logging).
    """
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"

    # Enforce Monthly Quoting Quotas & Track Bottlenecks
    quota = get_user_quota_info(user_id)
    if quota and not quota["can_quote"]:
        from services.db_service import log_bottleneck_event
        log_bottleneck_event(
            user_id=user_id,
            bottleneck_type="LIMIT_BLOCKED_QUOTES",
            attempted_action=f"Deterministic quote calculation: {payload.origin} -> {payload.destination}",
            current_usage=quota["monthly_quotes_used"],
            max_limit=quota["max_quotes_per_month"],
            details={"origin": payload.origin, "destination": payload.destination, "tier": quota["tier"]}
        )
        raise HTTPException(
            status_code=403,
            detail=f"Quote volume limit exceeded: You have reached your monthly limit of {quota['max_quotes_per_month']} quotes on {quota['tier_name']}. Please upgrade to Pro or Team to continue quoting."
        )

    # Purge any previous client proposal from memory upon generating next quote
    _active_proposal_memory.pop(user_id, None)

    # Derive actual weight if rating by LTL skids without explicit scale weight
    actual_weight = payload.actual_weight
    if (actual_weight is None or actual_weight <= 0) and payload.skid_count and payload.skid_count > 0:
        actual_weight = float(payload.skid_count * 500.0)

    if not actual_weight or actual_weight <= 0:
        raise HTTPException(status_code=400, detail="Shipment weight must be greater than 0.")
    if not payload.origin or not payload.destination:
        raise HTTPException(status_code=400, detail="Origin and Destination locations are required (Rule 25).")

    from services.ratesift_engine import quote_all_confirmed_carriers
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
            skid_count=payload.skid_count
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Rate calculation error: {str(e)}")

@app.get("/api/ratesift/quotes/audit/{quote_id}", tags=["RateSift Quoting Core"])
def api_ratesift_get_audit_log(quote_id: str, request: Request):
    """Retrieves immutable audit log for a quote (Rule 30)."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import get_quote_audit_log
    audit = get_quote_audit_log(quote_id, user_id=user_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit log not found or unauthorized.")
    return audit

@app.get("/api/ratesift/quotes/audit", tags=["RateSift Quoting Core"])
def api_ratesift_list_audit_logs(request: Request, limit: int = 50):
    """Lists recent quote audit logs for the authenticated tenant (Rule 28, 30)."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.ratesift_db_service import list_quote_audit_logs
    logs = list_quote_audit_logs(user_id=user_id, limit=limit)
    return {"audit_logs": logs}

@app.post("/api/settings/update", tags=["System Settings"])
async def api_update_settings(request: Request):
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    
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
        headers={"Content-Disposition": "attachment; filename=RateSift_Quotes_Export.xlsx"}
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.auth_service import get_user_profile
    profile = get_user_profile(user_id) or {}

    markup = payload.markup_pct if payload.markup_pct is not None else float(profile.get("markup_pct", 15.0))
    broker_info = {
        "company": profile.get("company", "TechCorp Logistics"),
        "name": profile.get("name", "Alex Rivers"),
        "email": profile.get("email", "alex.rivers@techcorp.io"),
        "origin_zip": profile.get("origin_zip", payload.origin)
    }

    from services.proposal_service import build_client_proposal_data
    proposal = build_client_proposal_data(
        quote_data=payload.dict(),
        client_name=payload.client_name or "Client Partner",
        broker_info=broker_info,
        markup_pct=markup,
        custom_total=payload.custom_total
    )
    # Cache in active session memory until next quote calculation
    _active_proposal_memory[user_id] = proposal

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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    active = _active_proposal_memory.get(user_id)
    return {
        "status": "success",
        "has_active_proposal": active is not None,
        "proposal": active
    }

@app.delete("/api/quotes/client-proposal/memory", tags=["Client Proposal Generator"])
def api_clear_client_proposal_memory(request: Request):
    """Explicitly purges any client proposal from memory."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    deleted = _active_proposal_memory.pop(user_id, None) is not None
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
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.auth_service import get_user_profile
    profile = get_user_profile(user_id) or {}

    markup = payload.markup_pct if payload.markup_pct is not None else float(profile.get("markup_pct", 15.0))
    broker_info = {
        "company": profile.get("company", "TechCorp Logistics"),
        "name": profile.get("name", "Alex Rivers"),
        "email": profile.get("email", "alex.rivers@techcorp.io"),
        "origin_zip": profile.get("origin_zip", payload.origin)
    }

    from services.proposal_service import build_client_proposal_data, generate_proposal_excel_workbook
    proposal = build_client_proposal_data(
        quote_data=payload.dict(),
        client_name=payload.client_name or "Client Partner",
        broker_info=broker_info,
        markup_pct=markup,
        custom_total=payload.custom_total
    )
    _active_proposal_memory[user_id] = proposal

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
        headers={"Content-Disposition": f"attachment; filename=RateSift_Client_Proposal_{clean_id}.xlsx"}
    )

@app.post("/api/user/account/update", tags=["User Profile"])
async def api_update_account(request: Request):
    """Updates user profile details, contact phone, and quoting origin defaults."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        name = body.get("name", "")
        company = body.get("company", "")
        origin_zip = body.get("origin_zip", "94103")
        origin_address = body.get("origin_address", "")
        phone = body.get("phone", "")
    else:
        form = await request.form()
        name = form.get("name", "")
        company = form.get("company", "")
        origin_zip = form.get("origin_zip", "94103")
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
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters long.")
        
    from services.db_service import update_user_password
    success, message = update_user_password(user_id, str(current_password), str(new_password))
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}

@app.post("/api/user/api-key/generate", tags=["Business API"])
def api_generate_key(request: Request, name: str = Form("Production Key")):
    """Generates a new API Key for Embedded Quoting."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    from services.db_service import create_api_key
    key = create_api_key(user_id, name)
    return {"status": "success", "api_key": key, "name": name}

@app.post("/api/v1/quotes/batch", tags=["Business API"])
def api_v1_embedded_batch_quotes(
    request: Request,
    payload: dict
):
    """
    Embedded Quoting API for Business / 3PL integrations.
    Requires header: 'X-API-Key: sf_live_...' or session.
    Calculates sub-second batch rate quotes.
    """
    from services.db_service import validate_api_key
    api_key = request.headers.get("X-API-Key")
    user = None
    if api_key:
        user = validate_api_key(api_key)
    if not user:
        user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized: Valid X-API-Key required for Business Quoting API.")
        
    shipments = payload.get("shipments", [])
    if not shipments:
        raise HTTPException(status_code=400, detail="Payload must include a non-empty 'shipments' array.")
        
    profile = get_user_profile(user["id"])
    markup = profile.get("markup_pct", 10.0)
    
    # Purge any previous client proposal from memory upon generating next quote
    _active_proposal_memory.pop(user["id"], None)

    parsed_rows = []
    for idx, s in enumerate(shipments):
        parsed_rows.append({
            "row_num": idx + 1,
            "origin_zip": str(s.get("origin_zip", profile.get("origin_zip", "94103"))),
            "dest_zip": str(s.get("dest_zip", "60601")),
            "weight_lbs": float(s.get("weight_lbs", 15.0)),
            "service": str(s.get("service", "Standard Ground")),
            "coordinate": f"API Request • Item {idx + 1}"
        })
        
    quoted_items = calculate_batch_quotes(parsed_rows, markup_pct=markup)
    
    return {
        "status": "success",
        "account": user["company"],
        "total_quotes": len(quoted_items),
        "currency": "USD",
        "quotes": quoted_items
    }

@app.get("/sample-sheets/{filename}", tags=["Sample Data"])
def get_sample_sheet(filename: str):
    sample_path = os.path.join(BASE_DIR, "sample_sheets", filename)
    if not os.path.exists(sample_path):
        raise HTTPException(status_code=404, detail="Sample sheet not found")
    return FileResponse(
        sample_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )

# ==============================================================================
# AGENT SPECIFICATION & DYNAMIC DETECTION CAPABILITIES (36 Rules)
# ==============================================================================

@app.get("/api/agent/rules", tags=["RateSift Agent Specification"])
def api_get_agent_rules():
    """
    Returns the complete 36 rules specification trained on the master rate sheet document,
    enforcing deterministic pricing, zero data loss, autonomous dynamic detection, and human audit.
    """
    from agent.rules_spec import RATESIFT_36_RULES, get_rules_summary
    return {
        "status": "success",
        "total_rules": len(RATESIFT_36_RULES),
        "rules_summary": get_rules_summary(),
        "rules": RATESIFT_36_RULES
    }

@app.get("/api/agent/status", tags=["RateSift Agent Specification"])
def api_get_agent_status():
    """
    Returns the current active status and capabilities of the Document-Trained RateSift Agent.
    """
    return {
        "status": "active",
        "agent_name": "RateSift Autonomous Dynamic Classifier & Pricing Agent",
        "agent_version": "2.0-prod",
        "rules_count": 36,
        "capabilities": [
            "Autonomous Dynamic Sheet Detection (arbitrary line numbers: 90, 140, etc.)",
            "Continuous Row Density Weighting & Currency Prerequisite (Issue 1 fix)",
            "Confusion Gate with Rich Candidate Previews (Scores within 10%)",
            "Authoritative Column Indexing & 2-Letter Province Pairing",
            "Multi-Segment Tariff Matrix Ingestion",
            "Zero-Data-Loss Row Reconciliation Audit (100% accounted)",
            "Prose Surcharge & Accessorial Extraction to Separate Ledger",
            "Human Confirmation Gate (Rules 7, 19)"
        ]
    }


# ==============================================================================
# PRIORITY 2: CANADIAN ENGINE & PRODUCT ENHANCEMENTS (Tasks 2.1 - 2.4)
# ==============================================================================

from services.fsa_resolver_service import resolve_location, extract_fsa, resolve_lane_locations
from services.fuel_index_service import (
    get_available_benchmark_indices,
    get_tenant_fuel_settings,
    update_tenant_fuel_settings,
    resolve_effective_fuel_surcharge
)
from services.rate_redactor_service import redact_rate_sheet_bytes

class FuelSettingsPayload(BaseModel):
    active_index_code: str = "OTA_LTL_STANDARD"
    custom_ltl_percent: Optional[float] = None
    use_carrier_sheet_fsc: bool = True
    auto_update_weekly: bool = True

@app.get("/api/geo/resolve-fsa", tags=["Canadian FSA Resolver"])
def api_resolve_fsa(code: str):
    """Resolves a Canadian Postal Code or Forward Sortation Area (FSA) into city, province, zone, and freight hub."""
    res = resolve_location(code)
    return res

@app.get("/api/geo/resolve-lane", tags=["Canadian FSA Resolver"])
def api_resolve_lane(origin: str, destination: str):
    """Normalizes origin and destination into canonical freight corridor locations."""
    orig, dest, meta = resolve_lane_locations(origin, destination)
    return {
        "origin_canonical": orig,
        "destination_canonical": dest,
        "metadata": meta
    }

@app.get("/api/fuel-indices/benchmarks", tags=["Fuel Surcharge Index Manager"])
def api_get_fuel_benchmarks():
    """Returns available published Canadian diesel benchmark indices (OTA, FCA, Western, Atlantic)."""
    return {
        "status": "success",
        "benchmarks": get_available_benchmark_indices()
    }

@app.get("/api/fuel-indices/settings", tags=["Fuel Surcharge Index Manager"])
def api_get_fuel_settings(request: Request):
    """Returns the authenticated broker's current fuel settings and effective LTL surcharge percentage."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    settings = get_tenant_fuel_settings(user_id)
    return settings

@app.post("/api/fuel-indices/settings", tags=["Fuel Surcharge Index Manager"])
def api_update_fuel_settings(payload: FuelSettingsPayload, request: Request):
    """Updates the broker's active weekly diesel fuel benchmark index or custom percentage."""
    user = get_current_user_from_request(request)
    user_id = user["id"] if user else "usr_alex_rivers"
    updated = update_tenant_fuel_settings(
        user_id=user_id,
        active_index_code=payload.active_index_code,
        custom_ltl_percent=payload.custom_ltl_percent,
        use_carrier_sheet_fsc=payload.use_carrier_sheet_fsc,
        auto_update_weekly=payload.auto_update_weekly
    )
    return {"status": "success", "settings": updated}

@app.post("/api/ratesift/redact-sheet", tags=["Client-Side Redaction Tool"])
async def api_redact_rate_sheet(file: UploadFile = File(...)):
    """
    Scrubs proprietary account numbers, customer identities, rep phone numbers/emails,
    and broker commission notes from an uploaded rate sheet, returning a clean redacted workbook.
    """
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV (.csv) rate sheets are supported.")
    content = await file.read()
    redacted_bytes, audit = redact_rate_sheet_bytes(content, file.filename)
    
    headers = {
        "Content-Disposition": f'attachment; filename="redacted_{file.filename}"',
        "X-Redactions-Count": str(audit["total_redactions"]),
        "X-Privacy-Status": audit["privacy_status"]
    }
    return Response(
        content=redacted_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )

@app.post("/api/ratesift/preview-redaction", tags=["Client-Side Redaction Tool"])
async def api_preview_rate_sheet_redaction(file: UploadFile = File(...)):
    """Previews sensitive data elements detected in the rate sheet without altering the original file."""
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV (.csv) rate sheets are supported.")
    content = await file.read()
    _, audit = redact_rate_sheet_bytes(content, file.filename)
    return {"status": "success", "audit": audit}

