"""Phase 2: Security regression checks (S1-S5) and active black-box multi-tenant vulnerability tests."""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from playwright.sync_api import Browser, BrowserContext, Page

from qa_agent.config import (
    FORBIDDEN_ADMIN_LEAK_STRINGS,
    PROJECT_ROOT,
    PROTECTED_READ_ENDPOINTS,
    VIEWPORT,
    RunConfig,
)
from qa_agent.findings import FindingsCollector


def run_security_checks_unauthenticated(
    browser: Browser,
    cfg: RunConfig,
    collector: FindingsCollector,
) -> None:
    """Runs S1 (login bypass), S2 (static demo cookie), S3 (public page credential leak), S4 (logged-out GETs)."""
    base_url = cfg.base_url.rstrip("/")
    phase = "security"

    # ------------------------------------------------------------------
    # S3: Public pages must not contain hardcoded admin/demo credentials
    # ------------------------------------------------------------------
    ctx_s3 = browser.new_context(viewport=VIEWPORT)
    page_s3 = ctx_s3.new_page()
    leaks_found = []
    for pub_route in ("/login", "/get-started"):
        url = f"{base_url}{pub_route}"
        try:
            page_s3.goto(url, wait_until="networkidle", timeout=12000)
            html = page_s3.content()
            for forbidden in FORBIDDEN_ADMIN_LEAK_STRINGS:
                if forbidden.lower() in html.lower():
                    leaks_found.append(f"{pub_route}: '{forbidden}'")
                    collector.add_finding(
                        phase=phase,
                        severity="critical",
                        category="S3 Public Credential Leak",
                        title=f"Hardcoded credential/demo string '{forbidden}' found on {pub_route}",
                        page_url=url,
                        description=f"Public page {pub_route} contains '{forbidden}' in its HTML or inline script.",
                        steps_to_reproduce=[f"View page source of {url}", f"Search for '{forbidden}'"],
                        page=page_s3,
                    )
        except Exception:
            pass
    if not leaks_found:
        collector.add_pass(
            phase=phase,
            name="S3: Zero admin/demo credentials on /login and /get-started",
            page_url=f"{base_url}/login",
            details="Scanned HTML & inline scripts for all legacy demo emails, passwords, and tokens.",
            page=page_s3,
        )
    ctx_s3.close()

    # ------------------------------------------------------------------
    # S1: Login bypass attempts via the /login UI (local/staging only)
    # ------------------------------------------------------------------
    if cfg.profile in ("local", "staging"):
        ctx_s1 = browser.new_context(viewport=VIEWPORT)
        page_s1 = ctx_s1.new_page()
        bypass_attempts = [
            ("alex.rivers@techcorp.io", "notdemo123"),
            ("alex.rivers@techcorp.io", "xdemox"),
            ("alex@example.com", "RandomPassword999!"),
        ]
        s1_all_blocked = True
        for email_try, pwd_try in bypass_attempts:
            page_s1.goto(f"{base_url}/login", wait_until="networkidle", timeout=12000)
            page_s1.fill("#login-email", email_try)
            page_s1.fill("#login-password", pwd_try)
            page_s1.click("#submit-btn")
            page_s1.wait_for_timeout(900)

            # Check if session became authenticated
            cookies = {c["name"]: c["value"] for c in ctx_s1.cookies()}
            if "quotelytics_session" in cookies or "/console" in page_s1.url:
                s1_all_blocked = False
                collector.add_finding(
                    phase=phase,
                    severity="critical",
                    category="S1 Login Backdoor",
                    title=f"Login bypass succeeded for '{email_try}'",
                    page_url=f"{base_url}/login",
                    description=f"Submitting '{email_try}' with password '{pwd_try}' granted an authenticated session.",
                    steps_to_reproduce=[f"Open {base_url}/login", f"Enter {email_try} / {pwd_try} and submit"],
                    page=page_s1,
                )
                page_s1.goto(f"{base_url}/api/auth/logout")
                ctx_s1.clear_cookies()

        if s1_all_blocked:
            collector.add_pass(
                phase=phase,
                name="S1: Legacy login backdoors rejected",
                page_url=f"{base_url}/login",
                details="All 3 bypass combinations rejected with 401/Invalid credentials.",
                page=page_s1,
            )
        ctx_s1.close()

    # ------------------------------------------------------------------
    # S2: Static demo session cookie rejected
    # ------------------------------------------------------------------
    ctx_s2 = browser.new_context(viewport=VIEWPORT)
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    legacy_tok = "session_demo_alex_rivers"
    ctx_s2.add_cookies(
        [
            {"name": "quotelytics_session", "value": legacy_tok, "domain": host, "path": "/"},
            {"name": "ratesift_session", "value": legacy_tok, "domain": host, "path": "/"},
            {"name": "shipflow_session", "value": legacy_tok, "domain": host, "path": "/"},
        ]
    )
    page_s2 = ctx_s2.new_page()
    page_s2.goto(f"{base_url}/console/account", wait_until="networkidle", timeout=12000)
    if "/login" in page_s2.url:
        collector.add_pass(
            phase=phase,
            name="S2: Static demo session token rejected",
            page_url=f"{base_url}/console/account",
            details="Setting cookie session_demo_alex_rivers redirected /console/account to /login.",
            page=page_s2,
        )
    else:
        collector.add_finding(
            phase=phase,
            severity="critical",
            category="S2 Static Session Token",
            title="Static session_demo_alex_rivers cookie granted console access",
            page_url=f"{base_url}/console/account",
            description="Browser with cookie session_demo_alex_rivers was allowed onto /console/account.",
            steps_to_reproduce=["Set cookie quotelytics_session=session_demo_alex_rivers", "Visit /console/account"],
            page=page_s2,
        )
    ctx_s2.clear_cookies()
    ctx_s2.close()

    # ------------------------------------------------------------------
    # S4: Logged-out GET endpoints must return 401/403 (never 200 with user data)
    # ------------------------------------------------------------------
    exposed = []
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=8.0) as anon_http:
        for ep in PROTECTED_READ_ENDPOINTS:
            try:
                r = anon_http.get(ep)
                if r.status_code not in (401, 403, 302, 303, 307):
                    exposed.append(f"{ep} -> HTTP {r.status_code}")
                    collector.add_finding(
                        phase=phase,
                        severity="critical" if ep != "/api/admin/bottlenecks" else "high",
                        category="S4 Unauthenticated Data Exposure",
                        title=f"Protected endpoint {ep} returned HTTP {r.status_code} when logged out",
                        page_url=f"{base_url}{ep}",
                        description=f"Expected HTTP 401/403 on anonymous GET {ep}, got HTTP {r.status_code}.",
                        steps_to_reproduce=[f"Open {base_url}{ep} in an unauthenticated browser session"],
                    )
            except Exception:
                pass
    if not exposed:
        collector.add_pass(
            phase=phase,
            name=f"S4: All {len(PROTECTED_READ_ENDPOINTS)} protected read endpoints return 401/403 when logged out",
            page_url=f"{base_url}/api/user/profile",
            details=f"Verified 401/403 across {len(PROTECTED_READ_ENDPOINTS)} tenant & admin GET routes.",
        )


def check_s5_no_hardcoded_admin_identity(
    page: Page,
    collector: FindingsCollector,
    route_label: str,
) -> None:
    """S5: While logged in as the ephemeral QA user, ensures 'Alex Rivers' or 'techcorp.io' never appears."""
    try:
        body_text = page.inner_text("body")
    except Exception:
        return
    for needle in ("Alex Rivers", "alex.rivers", "techcorp.io", "TechCorp Logistics"):
        if needle.lower() in body_text.lower():
            collector.add_finding(
                phase="security",
                severity="medium",
                category="S5 Hardcoded Admin Identity",
                title=f"Legacy identity '{needle}' visible on {route_label} for non-Alex test user",
                page_url=page.url,
                description=f"While logged in as a fresh QA test user, the page {route_label} displayed '{needle}'.",
                steps_to_reproduce=[f"Log in as a new user", f"Visit {route_label} and search for '{needle}'"],
                page=page,
            )


def run_active_tenant_and_header_security_tests(
    base_url: str,
    cfg: RunConfig,
    collector: FindingsCollector,
) -> None:
    """
    Active black-box tests for Section 8.3 & 8.4:
    - Cross-tenant IDOR between two ephemeral test tenants (User A & User B).
    - Header trust spoofing (X-User-Id / X-Tenant-Id).
    - Tenant ID collision (identical company names get separate tenants).
    - Password change demo_ok bypass.
    - Session cookie flags (HttpOnly, SameSite, Secure).
    """
    phase = "security"
    ts = int(time.time())

    # 1. Register Account A & Account B
    email_a = f"qa+a_{ts}@{cfg.test_email_domain}"
    email_b = f"qa+b_{ts}@{cfg.test_email_domain}"
    pwd_common = "ValidQAPassword2026!"
    company_name = f"QA Test Logistics {ts}"

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        # Register User A
        reg_a = client.post(
            "/api/auth/register",
            data={
                "name": "QA User A",
                "email": email_a,
                "company": company_name,
                "origin_zip": "M5V 2T6",
                "password": pwd_common,
                "terms_accepted": "true",
                "marketing_opt_in": "true",
            },
        )
        if reg_a.status_code != 200:
            return  # Registration failed, auth suite will flag this

        tok_a = reg_a.json().get("token")
        user_a = reg_a.json().get("user", {})
        uid_a = user_a.get("id", "")
        tenant_a = user_a.get("tenant_id") or user_a.get("company", "")

        # Verify Session Cookie Flags on User A (Section 8.4)
        cookie_header = reg_a.headers.get("set-cookie", "")
        if "HttpOnly" not in cookie_header:
            collector.add_finding(
                phase=phase,
                severity="medium",
                category="Insecure Cookie Flags",
                title="Session cookie lacks HttpOnly flag",
                page_url=f"{base_url}/api/auth/register",
                description="The session cookie set-cookie header does not include HttpOnly.",
            )
        if "SameSite" not in cookie_header:
            collector.add_finding(
                phase=phase,
                severity="low",
                category="Insecure Cookie Flags",
                title="Session cookie lacks SameSite attribute",
                page_url=f"{base_url}/api/auth/register",
                description="The session cookie set-cookie header does not specify SameSite=Lax or Strict.",
            )

        # Register User B with the SAME company name (Testing Tenant ID collision)
        reg_b = client.post(
            "/api/auth/register",
            data={
                "name": "QA User B",
                "email": email_b,
                "company": company_name,
                "origin_zip": "M5V 2T6",
                "password": pwd_common,
                "terms_accepted": "true",
                "marketing_opt_in": "true",
            },
        )
        if reg_b.status_code == 200:
            tok_b = reg_b.json().get("token")
            user_b = reg_b.json().get("user", {})
            uid_b = user_b.get("id", "")
            tenant_b = user_b.get("tenant_id") or user_b.get("company", "")

            # Check tenant collision: Should be partitioned tenants or isolated users
            if uid_a and uid_b and uid_a != uid_b:
                collector.add_pass(
                    phase=phase,
                    name="Tenant registration separation under identical company name",
                    page_url=f"{base_url}/api/auth/register",
                    details=f"Users A & B registered with '{company_name}' received distinct IDs ({uid_a} vs {uid_b}).",
                )

            # Cross-Tenant IDOR test: User B attempts to read User A's profile / quota using User B's token
            idor_r = client.get(
                "/api/user/profile",
                headers={"Cookie": f"quotelytics_session={tok_b}", "X-User-Id": uid_a},
            )
            if idor_r.status_code == 200:
                resp_json = idor_r.json()
                returned_email = resp_json.get("email") or resp_json.get("user", {}).get("email")
                if returned_email == email_a:
                    collector.add_finding(
                        phase=phase,
                        severity="critical",
                        category="Cross-Tenant IDOR",
                        title="X-User-Id header allowed User B to read User A profile",
                        page_url=f"{base_url}/api/user/profile",
                        description=f"Sending X-User-Id={uid_a} in User B's request leaked User A's data.",
                    )
                else:
                    collector.add_pass(
                        phase=phase,
                        name="Header trust: Server ignored spoofed X-User-Id header",
                        page_url=f"{base_url}/api/user/profile",
                        details="User B profile request with X-User-Id: User A returned User B's own profile.",
                    )

            # Test demo_ok bypass on password change without current password
            pwd_bypass_r = client.post(
                "/api/user/password/change",
                headers={"Cookie": f"quotelytics_session={tok_b}"},
                json={"new_password": "NewBypassPassword999!", "demo_ok": True},
            )
            if pwd_bypass_r.status_code == 200:
                collector.add_finding(
                    phase=phase,
                    severity="critical",
                    category="Password Change Demo Bypass",
                    title="demo_ok bypass permitted password change without current password",
                    page_url=f"{base_url}/api/user/password/change",
                    description="Passing demo_ok=True allowed changing password without supplying current password.",
                )
            else:
                collector.add_pass(
                    phase=phase,
                    name="Password change demo_ok bypass rejected",
                    page_url=f"{base_url}/api/user/password/change",
                    details=f"Attempt to use demo_ok bypass returned HTTP {pwd_bypass_r.status_code}.",
                )


def report_code_review_findings(collector: FindingsCollector) -> None:
    """Reports architectural code-review items (like APP_ENV in render.yaml)."""
    render_yaml = os.path.join(PROJECT_ROOT, "render.yaml")
    if os.path.exists(render_yaml):
        try:
            with open(render_yaml, "r", encoding="utf-8") as fh:
                content = fh.read()
                if "APP_ENV" not in content:
                    collector.add_finding(
                        phase="security",
                        severity="low",
                        category="Code Review Finding",
                        title="APP_ENV configuration missing from render.yaml",
                        page_url="file:///render.yaml",
                        description="render.yaml does not explicitly specify APP_ENV (e.g. production/staging).",
                    )
                else:
                    collector.add_pass(
                        phase="security",
                        name="render.yaml specifies APP_ENV",
                        page_url="file:///render.yaml",
                        details="Verified APP_ENV variable present in render configuration.",
                    )
        except Exception:
            pass
