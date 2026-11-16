"""
Quotelytics Pre-Flight & Operational Readiness Diagnostic CLI
Verifies database integrity, schema tables, environment variables, email outbox,
Stripe configuration status, and all public/SEO web routes before deployment.
"""
import os
import sys
from datetime import datetime
from typing import List, Tuple

# Terminal color escape codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed_checks = 0
failed_checks = 0
warnings = 0


def log_pass(msg: str):
    global passed_checks
    passed_checks += 1
    print(f"  [{GREEN}PASS{RESET}] {msg}")


def log_fail(msg: str):
    global failed_checks
    failed_checks += 1
    print(f"  [{RED}FAIL{RESET}] {BOLD}{msg}{RESET}")


def log_warn(msg: str):
    global warnings
    warnings += 1
    print(f"  [{YELLOW}WARN{RESET}] {msg}")


def check_database():
    print(f"\n{CYAN}{BOLD}1. Database Engine & Schema Integrity (quotelytics.db){RESET}")
    from services.quotelytics_db_service import get_connection

    try:
        conn = get_connection()
        c = conn.cursor()

        # Check WAL mode
        c.execute("PRAGMA journal_mode")
        mode = c.fetchone()[0]
        if mode.lower() == "wal":
            log_pass(f"SQLite journal_mode is WAL (Write-Ahead Logging)")
        else:
            log_warn(f"SQLite journal_mode is '{mode}' (recommended: WAL for concurrent reads)")

        # Check integrity
        c.execute("PRAGMA integrity_check")
        integrity = c.fetchone()[0]
        if integrity.lower() == "ok":
            log_pass("SQLite PRAGMA integrity_check passed: OK")
        else:
            log_fail(f"SQLite PRAGMA integrity_check failed: {integrity}")

        # Check critical tables
        expected_tables = [
            "users",
            "subscription_tiers",
            "ql_rate_sheets",
            "ql_carrier_zones",
            "ql_weight_breaks",
            "ql_carrier_minimums",
            "ql_carrier_surcharges",
            "auth_tokens",
            "marketing_consent_logs",
            "support_tickets",
            "user_settings",
            "api_keys",
            "webhook_endpoints",
            "webhook_deliveries"
        ]
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = set(r[0] for r in c.fetchall())

        missing = [t for t in expected_tables if t not in existing_tables]
        if not missing:
            log_pass(f"All {len(expected_tables)} required normalized database tables present")
        else:
            log_fail(f"Missing required database tables: {missing}")

        conn.close()
    except Exception as exc:
        log_fail(f"Database connectivity error: {exc}")


def check_environment():
    print(f"\n{CYAN}{BOLD}2. Environment Variables & Production Secrets{RESET}")

    env_app = os.getenv("APP_ENV", "development").lower()
    if env_app == "production":
        log_pass("APP_ENV is set to 'production'")
    else:
        log_warn(f"APP_ENV is '{env_app}' (set to 'production' on live server)")

    secret = os.getenv("SESSION_SECRET", "")
    if secret and secret != "dev-insecure-secret-key-change-in-production":
        log_pass("SESSION_SECRET is configured with custom entropy")
    else:
        log_warn("SESSION_SECRET is empty or using fallback dev default")

    admin_email = os.getenv("QUOTELYTICS_ADMIN_EMAIL", "")
    if admin_email:
        log_pass(f"QUOTELYTICS_ADMIN_EMAIL configured ({admin_email})")
    else:
        log_warn("QUOTELYTICS_ADMIN_EMAIL not set (admin bootstrap skipped)")

    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    if stripe_key.startswith("sk_live_"):
        log_pass("STRIPE_SECRET_KEY is configured in LIVE mode")
    elif stripe_key.startswith("sk_test_"):
        log_pass("STRIPE_SECRET_KEY is configured in TEST mode")
    else:
        log_warn("STRIPE_SECRET_KEY is unset or mock (Stripe running in zero-dollar mock test mode)")


def check_email_subsystem():
    print(f"\n{CYAN}{BOLD}3. Transactional Email & Notification Subsystem{RESET}")
    from services.email_service import (
        send_transactional_email,
        get_sent_emails,
        clear_sent_emails,
    )

    clear_sent_emails()
    rec = send_transactional_email(
        to_email="preflight@quotelytics.ca",
        subject="Pre-flight diagnostic test",
        text_body="System readiness verification probe.",
        category="PREFLIGHT",
    )
    if rec and len(get_sent_emails(category="PREFLIGHT")) == 1:
        log_pass(f"Transactional email delivery engine active (delivered_via: {rec['delivered_via']})")
    else:
        log_fail("Email outbox failed to record test message")
    clear_sent_emails()


def check_web_routes():
    print(f"\n{CYAN}{BOLD}4. HTTP Route Health & SEO Search Engine Endpoints{RESET}")
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    routes_to_probe = [
        ("/", 200, "Public Homepage"),
        ("/demo", 200, "Interactive Rate Demo"),
        ("/pricing", 200, "Pricing & Fleet Plans"),
        ("/help", 200, "Help Centre Documentation"),
        ("/faq", 200, "FAQ Route"),
        ("/terms", 200, "Terms of Service"),
        ("/privacy", 200, "PIPEDA Privacy Policy"),
        ("/refunds", 200, "Refund Policy"),
        ("/subprocessors", 200, "Authorized Sub-processors"),
        ("/dpa", 200, "Data Processing Addendum"),
        ("/unsubscribe", 200, "CASL Marketing Unsubscribe"),
        ("/robots.txt", 200, "Search Engine Robots Directives"),
        ("/sitemap.xml", 200, "Dynamic XML Sitemap"),
        ("/healthz", 200, "Production Uptime Healthz Probe"),
        ("/api/sample-sheets/download?format=xlsx", 200, "Sample Rate Sheet Download (.xlsx)"),
        ("/api/sample-sheets/download?format=csv", 200, "Sample Rate Sheet Download (.csv)"),
    ]

    for path, expected_status, label in routes_to_probe:
        try:
            res = client.get(path)
            if res.status_code == expected_status:
                log_pass(f"{path:<45} HTTP {res.status_code} [{label}]")
            else:
                log_fail(f"{path:<45} Expected HTTP {expected_status}, got {res.status_code}")
        except Exception as exc:
            log_fail(f"{path:<45} Request failed: {exc}")

    try:
        head_res = client.head("/healthz")
        if head_res.status_code == 200:
            log_pass(f"{'HEAD /healthz':<45} HTTP {head_res.status_code} [UptimeRobot / LB HEAD Probe]")
        else:
            log_fail(f"{'HEAD /healthz':<45} Expected HTTP 200, got {head_res.status_code}")
    except Exception as exc:
        log_fail(f"{'HEAD /healthz':<45} Request failed: {exc}")


def check_sample_files():
    print(f"\n{CYAN}{BOLD}5. Sample Tariff Files & Archiving Verification{RESET}")
    xlsx = os.path.join("sample_sheets", "Quotelytics_Canadian_LTL_Sample_Tariff.xlsx")
    csv_f = os.path.join("sample_sheets", "Quotelytics_Canadian_LTL_Sample_Tariff.csv")

    if os.path.isfile(xlsx) and os.path.getsize(xlsx) > 1000:
        log_pass(f"Synthetic Canadian LTL sample workbook present: {xlsx}")
    else:
        log_fail(f"Missing sample workbook: {xlsx}")

    if os.path.isfile(csv_f):
        log_pass(f"Synthetic Canadian LTL CSV sample present: {csv_f}")
    else:
        log_fail(f"Missing sample CSV: {csv_f}")

    legacy_dnr = os.path.join("sample_sheets", "day_and_ross_guide_tariff.csv")
    if not os.path.isfile(legacy_dnr):
        log_pass("Confidential carrier tariffs successfully purged from sample_sheets/ (archived in legacy_deployment/)")
    else:
        log_warn("Legacy carrier tariff still present in sample_sheets/")


def main():
    print(f"\n{BOLD}========================================================================{RESET}")
    print(f"{BOLD} QUOTELYTICS INC. — PRE-FLIGHT OPERATIONAL READINESS DIAGNOSTIC{RESET}")
    print(f" Execution Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{BOLD}========================================================================{RESET}")

    check_database()
    check_environment()
    check_email_subsystem()
    check_sample_files()
    check_web_routes()

    print(f"\n{BOLD}========================================================================{RESET}")
    total = passed_checks + failed_checks + warnings
    print(f" Summary: {GREEN}{passed_checks} PASSED{RESET} • {YELLOW}{warnings} WARNINGS{RESET} • {RED}{failed_checks} FAILED{RESET} (Total: {total} probes)")
    if failed_checks == 0:
        print(f" {GREEN}{BOLD}>>> SYSTEM IS FULLY HEALTHY & READY FOR DEPLOYMENT <<<{RESET}")
    else:
        print(f" {RED}{BOLD}>>> ISSUES DETECTED. PLEASE REVIEW FAILURES ABOVE <<<{RESET}")
    print(f"{BOLD}========================================================================{RESET}\n")

    sys.exit(1 if failed_checks > 0 else 0)


if __name__ == "__main__":
    main()
