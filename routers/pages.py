"""Public HTML pages, SEO endpoints, console pages, healthz, and architecture views."""
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from services.db_service import get_connection
from routers.deps import (
    BASE_DIR,
    ensure_dev_or_admin,
    get_current_user_from_request,
    serve_template,
)

router = APIRouter()


# ==========================================
# PUBLIC PAGES (SEO-Optimized & Crawlable)
# ==========================================

@router.get("/", response_class=HTMLResponse, tags=["Public Pages"])
def get_home_page():
    """Quotelytics SEO Landing Page"""
    return serve_template("public/home.html")


@router.get("/demo", response_class=HTMLResponse, tags=["Public Pages"])
def get_demo_page():
    """Interactive Public Demo with sample rate sheets"""
    return serve_template("public/demo.html")


@router.get("/pricing", response_class=HTMLResponse, tags=["Public Pages"])
def get_pricing_page():
    """Public Pricing Page (4 Tiers with Business Custom)"""
    return serve_template("public/pricing.html")


@router.get("/login", response_class=HTMLResponse, tags=["Public Pages"])
def get_login_page(request: Request):
    """Single-centered Log In screen. If already logged in, redirects to console."""
    user = get_current_user_from_request(request)
    if user:
        return RedirectResponse(url="/console/new-quote", status_code=303)
    return serve_template("public/login.html")


@router.get("/get-started", response_class=HTMLResponse, tags=["Public Pages"])
def get_get_started_page(request: Request):
    """Single-centered Create Your Account screen. If already logged in, redirects to console."""
    user = get_current_user_from_request(request)
    if user:
        return RedirectResponse(url="/console/new-quote", status_code=303)
    return serve_template("public/get_started.html")


@router.get("/privacy", response_class=HTMLResponse, tags=["Public Pages"])
def get_privacy_page():
    """Public PIPEDA Privacy Policy Page"""
    return serve_template("public/privacy.html")


@router.get("/terms", response_class=HTMLResponse, tags=["Public Pages"])
def get_terms_page():
    """Public Terms of Service & SaaS Agreement Page"""
    return serve_template("public/terms.html")


@router.get("/refunds", response_class=HTMLResponse, tags=["Public Pages"])
def get_refunds_page():
    """Public Refund & Cancellation Policy Page"""
    return serve_template("public/terms.html")


@router.get("/subprocessors", response_class=HTMLResponse, tags=["Public Pages"])
def get_subprocessors_page():
    """Public Authorized Sub-processors Directory Page"""
    return serve_template("public/subprocessors.html")


@router.get("/dpa", response_class=HTMLResponse, tags=["Public Pages"])
def get_dpa_page():
    """Public B2B Data Processing Addendum (DPA) Page"""
    return serve_template("public/dpa.html")


@router.get("/help", response_class=HTMLResponse, tags=["Public Pages"])
def get_help_page():
    """Public Broker Help Centre & Tariff Documentation Page"""
    return serve_template("public/help.html")


@router.get("/faq", response_class=HTMLResponse, tags=["Public Pages"])
def get_faq_page():
    """Public FAQ & Documentation Page"""
    return serve_template("public/help.html")


@router.get("/unsubscribe", response_class=HTMLResponse, tags=["Public Pages"])
def get_unsubscribe_page():
    """Public CASL Marketing Unsubscribe Page"""
    return serve_template("public/unsubscribe.html")


@router.get("/robots.txt", response_class=PlainTextResponse, tags=["SEO & Crawlers"])
def get_robots_txt():
    """Search engine crawling instructions for quotelytics.ca."""
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /demo\n"
        "Allow: /pricing\n"
        "Allow: /help\n"
        "Allow: /faq\n"
        "Allow: /terms\n"
        "Allow: /privacy\n"
        "Allow: /refunds\n"
        "Allow: /subprocessors\n"
        "Allow: /dpa\n"
        "Allow: /login\n"
        "Allow: /get-started\n"
        "Disallow: /console/\n"
        "Disallow: /api/\n"
        "Disallow: /static/\n"
        "Disallow: /reset-password\n"
        "Disallow: /forgot-password\n"
        "Disallow: /unsubscribe\n\n"
        "Sitemap: https://quotelytics.ca/sitemap.xml\n"
    )


@router.get("/sitemap.xml", tags=["SEO & Crawlers"])
def get_sitemap_xml():
    """Generates standard XML sitemap for search engines."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    base_url = "https://quotelytics.ca"
    urls = [
        {"loc": f"{base_url}/", "priority": "1.0", "changefreq": "weekly"},
        {"loc": f"{base_url}/pricing", "priority": "0.9", "changefreq": "weekly"},
        {"loc": f"{base_url}/demo", "priority": "0.9", "changefreq": "weekly"},
        {"loc": f"{base_url}/help", "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{base_url}/faq", "priority": "0.7", "changefreq": "monthly"},
        {"loc": f"{base_url}/terms", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{base_url}/privacy", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{base_url}/refunds", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{base_url}/subprocessors", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{base_url}/dpa", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{base_url}/get-started", "priority": "0.8", "changefreq": "monthly"},
        {"loc": f"{base_url}/login", "priority": "0.6", "changefreq": "monthly"},
    ]
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in urls:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{u['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{today}</lastmod>")
        xml_lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{u['priority']}</priority>")
        xml_lines.append("  </url>")
    xml_lines.append("</urlset>")
    return Response(content="\n".join(xml_lines), media_type="application/xml")


@router.get("/api/sample-sheets/download", tags=["Public Resources"])
def api_download_sample_sheet(format: str = "xlsx"):
    """Provides standard synthetic Canadian LTL tariff sample for instant onboarding."""
    clean_format = format.lower().strip()
    if clean_format == "csv":
        file_path = os.path.join(BASE_DIR, "sample_sheets", "Quotelytics_Canadian_LTL_Sample_Tariff.csv")
        filename = "Quotelytics_Canadian_LTL_Sample_Tariff.csv"
        media_type = "text/csv"
    else:
        file_path = os.path.join(BASE_DIR, "sample_sheets", "Quotelytics_Canadian_LTL_Sample_Tariff.xlsx")
        filename = "Quotelytics_Canadian_LTL_Sample_Tariff.xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Sample tariff file not found.")

    return FileResponse(path=file_path, filename=filename, media_type=media_type)


@router.get("/sample-sheets/{filename}", tags=["Sample Data"])
def get_sample_sheet(filename: str):
    """Serve a sample rate sheet from sample_sheets/ safely."""
    safe_name = os.path.basename(filename)
    sample_dir = os.path.abspath(os.path.join(BASE_DIR, "sample_sheets"))
    sample_path = os.path.abspath(os.path.join(sample_dir, safe_name))
    if not sample_path.startswith(sample_dir) or not os.path.exists(sample_path):
        raise HTTPException(status_code=404, detail="Sample sheet not found")
    return FileResponse(
        sample_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=safe_name,
    )


@router.get("/forgot-password", response_class=HTMLResponse, tags=["Public Pages"])
def get_forgot_password_page():
    """Public Forgot Password request screen."""
    return serve_template("public/forgot_password.html")


@router.get("/reset-password", response_class=HTMLResponse, tags=["Public Pages"])
def get_reset_password_page():
    """Public Reset Password screen (consumes ?token=...)."""
    return serve_template("public/reset_password.html")


# ==========================================
# PRIVATE CONSOLE PAGES (Route Guarded)
# ==========================================

@router.get("/console/new-quote", response_class=HTMLResponse, tags=["Console Pages"])
def get_new_quote_page(request: Request):
    """Default Console View: 'New rate sheet' with 'Process ->'. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/new-quote", status_code=303)
    return serve_template("console/new_quote.html")


@router.get("/console/history", response_class=HTMLResponse, tags=["Console Pages"])
def get_history_page(request: Request):
    """Quotes History Warehouse with cell coordinates. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/history", status_code=303)
    return serve_template("console/history.html")


@router.get("/console/rate-sheets", response_class=HTMLResponse, tags=["Console Pages"])
def get_rate_sheets_page(request: Request):
    """Rate Sheets Warehouse and Human Confirmation Gate. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/rate-sheets", status_code=303)
    return serve_template("console/rate_sheets.html")


@router.get("/console/account", response_class=HTMLResponse, tags=["Console Pages"])
def get_account_page(request: Request):
    """Account Profile & Subscription Management. Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/account", status_code=303)
    return serve_template("console/account.html")


@router.get("/console/settings", response_class=HTMLResponse, tags=["Console Pages"])
def get_settings_page(request: Request):
    """System & Quoting Settings (Currency, Units, Markup, Toggles). Requires Authentication."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/settings", status_code=303)
    return serve_template("console/settings.html")


@router.get("/console/admin", response_class=HTMLResponse, tags=["Console Pages"])
def get_admin_onboarding_page(request: Request):
    """Sales & Admin Business API Onboarding Desk. Strictly limited to ADMIN accounts."""
    user = get_current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login?next=/console/admin", status_code=303)
    if (user.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Administrator privileges required.")
    return serve_template("console/admin_onboarding.html")


# ==========================================
# OPERATIONS & UPTIME MONITORING
# ==========================================

@router.api_route("/healthz", methods=["GET", "HEAD"], tags=["Operations"])
def get_healthz():
    """Uptime probe endpoint for monitoring services (e.g. UptimeRobot, load balancers)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        db_healthy = True
    except Exception:
        db_healthy = False

    if not db_healthy:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "app": "Quotelytics Quoting Engine",
                "database": "disconnected",
                "region": "CA_CENTRAL_WHC",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        )

    return {
        "status": "healthy",
        "app": "Quotelytics Quoting Engine",
        "version": "1.0.0",
        "database": "connected",
        "region": "CA_CENTRAL_WHC",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ==========================================
# ARCHITECTURE & SHOWCASE (Gated in Production)
# ==========================================

@router.get("/failsafe/demo", response_class=HTMLResponse, tags=["Architecture"])
def get_failsafe_demo_page(request: Request):
    """Failsafe Header Mapping Modal UI Playground."""
    ensure_dev_or_admin(request)
    return serve_template("console/failsafe_demo.html")


@router.get("/flowchart", response_class=HTMLResponse, tags=["Architecture"])
def get_flowchart_page(request: Request):
    """Interactive Page Architecture & Routing Flowchart"""
    ensure_dev_or_admin(request)
    return serve_template("flowchart.html")


@router.get("/showcase", response_class=HTMLResponse, tags=["Architecture"])
def get_showcase_page(request: Request):
    """Master Design Suite Showcase with 10 Live Tabs"""
    ensure_dev_or_admin(request)
    return serve_template("showcase.html")
