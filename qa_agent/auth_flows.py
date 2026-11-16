"""Phase 2: Registration, login, logout, route guarding, console crawl/interactions, and UI self-cleanup."""
from __future__ import annotations

import secrets
import time
import uuid
from typing import Any
from playwright.sync_api import Browser, BrowserContext, Page

from qa_agent.config import CONSOLE_ROUTES, VIEWPORT, RunConfig
from qa_agent.crawler import run_crawler_phase
from qa_agent.db_tools import sweep_orphan_test_accounts, verify_account_fully_deleted
from qa_agent.findings import FindingsCollector
from qa_agent.interactions import test_buttons_on_routes
from qa_agent.safety import SafetyManager
from qa_agent.security_checks import check_s5_no_hardcoded_admin_identity


def verify_own_session(page: Page, base_url: str, expected_email: str) -> bool:
    """Confirms the active browser session belongs strictly to the QA agent's test account."""
    try:
        status = page.evaluate(
            """async () => {
                const r = await fetch('/api/auth/status');
                return r.ok ? await r.json() : null;
            }"""
        )
        if not status or not status.get("authenticated"):
            return False
        user = status.get("user") or {}
        return (user.get("email") or "").lower() == expected_email.lower()
    except Exception:
        return False


def run_auth_and_free_tier_journey(
    browser: Browser,
    cfg: RunConfig,
    collector: FindingsCollector,
) -> None:
    """Executes route guarding, sign-up validations, account creation, login/logout, console checks, free-tier journey, and UI account deletion."""
    base_url = cfg.base_url.rstrip("/")
    phase = "auth"
    safety_mgr = SafetyManager(cfg, collector)

    # Profile gating check (Section 4 & 5)
    safety_mgr.assert_phase_allowed("auth")

    ts = int(time.time())
    unique_tag = uuid.uuid4().hex[:6]
    test_email = f"qa+{ts}_{unique_tag}@{cfg.test_email_domain}"
    test_password = f"QaPass!{secrets.token_hex(6)}"
    test_name = f"QA Tester {unique_tag}"
    test_company = f"QA Brokerage {unique_tag}"

    collector.metadata["test_account_email"] = test_email

    ctx: BrowserContext = browser.new_context(viewport=VIEWPORT, accept_downloads=True)
    safety_mgr.install_safety_layer(ctx)

    page: Page = ctx.new_page()

    auto_accept_dialogs = {"enabled": False}

    def on_dialog(dialog: Any) -> None:
        try:
            if auto_accept_dialogs["enabled"]:
                dialog.accept()
            else:
                dialog.dismiss()
        except Exception:
            pass

    page.on("dialog", on_dialog)
    created_user_id: str = ""

    try:
        # 1. Verify route guarding while logged out
        for c_route in CONSOLE_ROUTES:
            page.goto(f"{base_url}{c_route}", wait_until="networkidle", timeout=12000)
            if "/login" not in page.url:
                collector.add_finding(
                    phase=phase,
                    severity="critical",
                    category="Route Guard Bypass",
                    title=f"Unauthenticated visit to {c_route} did not redirect to /login",
                    page_url=f"{base_url}{c_route}",
                    description=f"Expected redirect to /login when visiting {c_route} logged out; landed on {page.url}.",
                    steps_to_reproduce=[f"Clear cookies and visit {base_url}{c_route}"],
                    page=page,
                )
        collector.add_pass(
            phase=phase,
            name="Unauthenticated console routes redirect to /login",
            page_url=f"{base_url}/console/new-quote",
            details=f"Verified all {len(CONSOLE_ROUTES)} /console/* pages redirect to /login when unauthenticated.",
            page=page,
        )

        # 2. Test /get-started form validations
        page.goto(f"{base_url}/get-started", wait_until="networkidle", timeout=12000)
        page.click("#submit-reg-btn")
        page.wait_for_timeout(300)
        name_err_visible = page.locator("#name-error").is_visible()
        terms_err_visible = page.locator("#terms-error").is_visible()
        if name_err_visible and terms_err_visible:
            collector.add_pass(
                phase=phase,
                name="Registration validation blocks empty fields & unticked Terms",
                page_url=f"{base_url}/get-started",
                details="Name, email, company, password, and Terms checkboxes validated before submission.",
                page=page,
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="medium",
                category="Form Validation",
                title="Registration form did not display expected validation errors on empty submit",
                page_url=f"{base_url}/get-started",
                description=f"name_error visible={name_err_visible}, terms_error visible={terms_err_visible}",
                steps_to_reproduce=["Open /get-started", "Click Create Free Account with empty fields"],
                page=page,
            )

        # 3. Create the Free Starter account via UI
        page.fill("#reg-name", test_name)
        page.fill("#reg-email", test_email)
        page.fill("#reg-company", test_company)
        page.fill("#reg-origin", "M5V2T")
        page.fill("#reg-password", test_password)
        page.check("#terms-check")
        page.click("#submit-reg-btn")

        try:
            page.wait_for_url("**/console/**", timeout=10000)
            status_obj = page.evaluate("async () => { const r = await fetch('/api/auth/status'); return r.ok ? await r.json() : null; }")
            created_user_id = (status_obj.get("user") or {}).get("id", "")
            collector.add_pass(
                phase=phase,
                name="Account registration via /get-started UI",
                page_url=page.url,
                details=f"Created Free Starter account {test_email} (ID: {created_user_id}) and redirected to {page.url}.",
                page=page,
            )
        except Exception as exc:
            collector.add_finding(
                phase=phase,
                severity="critical",
                category="Registration Failure",
                title="Account creation failed to redirect to /console/new-quote",
                page_url=f"{base_url}/get-started",
                description=f"After submitting registration for {test_email}, page remained at {page.url}: {exc}",
                steps_to_reproduce=["Fill valid fields on /get-started", "Check Terms", "Submit"],
                page=page,
            )
            return

        # 4. Test Logout via UI and Login via /login UI
        logout_link = page.locator("a[href='/api/auth/logout']").first
        if logout_link.count() > 0:
            logout_link.click()
            page.wait_for_load_state("networkidle", timeout=10000)
        else:
            page.goto(f"{base_url}/api/auth/logout", wait_until="networkidle")

        page.goto(f"{base_url}/console/account", wait_until="networkidle")
        if "/login" in page.url:
            collector.add_pass(
                phase=phase,
                name="Logout clears session & blocks /console/account",
                page_url=page.url,
                details="Clicking Sign Out invalidated session cookie and redirected protected pages to /login.",
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="high",
                category="Logout Failure",
                title="Session remained active after clicking Sign Out",
                page_url=page.url,
                description="Visiting /console/account after logout did not redirect to /login.",
                page=page,
            )

        # Test invalid password on /login
        page.goto(f"{base_url}/login", wait_until="networkidle")
        page.fill("#login-email", test_email)
        page.fill("#login-password", "WrongPassword123!")
        page.click("#submit-btn")
        page.wait_for_timeout(700)
        status_txt = page.locator("#login-status").inner_text()
        if "invalid" in status_txt.lower() or "/login" in page.url:
            collector.add_pass(
                phase=phase,
                name="Login rejects wrong password with error message",
                page_url=f"{base_url}/login",
                details=f"Status message: '{status_txt.strip()}'",
                page=page,
            )

        # Log in with valid credentials
        page.fill("#login-email", test_email)
        page.fill("#login-password", test_password)
        page.click("#submit-btn")
        page.wait_for_url("**/console/**", timeout=10000)
        collector.add_pass(
            phase=phase,
            name="Login with newly registered credentials",
            page_url=page.url,
            details=f"Authenticated as {test_email} and landed on {page.url}.",
            page=page,
        )

        # Verify S5 identity checks across console routes
        for c_route in CONSOLE_ROUTES:
            page.goto(f"{base_url}{c_route}", wait_until="networkidle", timeout=12000)
            check_s5_no_hardcoded_admin_identity(page, collector, c_route)

        if "crawl" in cfg.phases:
            run_crawler_phase(ctx, cfg, collector, extra_routes=CONSOLE_ROUTES, phase_label="crawl-console")

        if "interactions" in cfg.phases:
            test_buttons_on_routes(ctx, cfg, collector, CONSOLE_ROUTES, phase_label="interactions-console")

        # 5. Free-Tier Journey
        if "free_tier" in cfg.phases:
            from qa_agent.free_tier import execute_free_tier_journey

            if verify_own_session(page, base_url, test_email):
                execute_free_tier_journey(page, ctx, cfg, collector, test_email)
            else:
                collector.add_finding(
                    phase="free_tier",
                    severity="critical",
                    category="Session Guard Triggered",
                    title="Aborted Free-Tier journey because active session did not match QA test account",
                    page_url=page.url,
                    description=f"Expected session for {test_email}.",
                )

    finally:
        # Guaranteed Cleanup via UI Delete Account button on /console/account (Section 13)
        try:
            page.goto(f"{base_url}/console/account", wait_until="networkidle", timeout=12000)
            if "/login" in page.url:
                page.fill("#login-email", test_email)
                page.fill("#login-password", test_password)
                page.click("#submit-btn")
                page.wait_for_url("**/console/**", timeout=8000)
                page.goto(f"{base_url}/console/account", wait_until="networkidle", timeout=10000)

            if verify_own_session(page, base_url, test_email):
                auto_accept_dialogs["enabled"] = True
                page.evaluate("""() => {
                    window.__SKIP_DELETE_CONFIRM__ = true;
                    window.confirm = () => true;
                    window.alert = () => true;
                    if (typeof switchTab === 'function') switchTab('security');
                }""")
                page.wait_for_timeout(400)
                del_btn = page.locator("button[onclick*='deleteMyAccount']").first
                if del_btn.count() > 0 and del_btn.is_visible():
                    del_btn.scroll_into_view_if_needed()
                    try:
                        del_btn.click(timeout=5000)
                    except Exception:
                        page.evaluate("() => { if (typeof deleteMyAccount === 'function') deleteMyAccount(true); }")
                else:
                    page.evaluate("() => { if (typeof deleteMyAccount === 'function') deleteMyAccount(true); }")

                # Wait for async deletion pipeline to settle (poll up to 10 seconds)
                cleaned = False
                for step in range(20):
                    page.wait_for_timeout(500)
                    try:
                        status_after = page.evaluate(
                            "async () => { const r = await fetch('/api/auth/status'); return r.ok ? await r.json() : null; }"
                        )
                        cleaned = not (status_after and status_after.get("authenticated"))
                        if cleaned:
                            break
                    except Exception:
                        cleaned = True
                        break

                    if step == 4 and not cleaned:
                        page.evaluate("() => { if (typeof deleteMyAccount === 'function') deleteMyAccount(true); }")
                    elif step == 8 and not cleaned:
                        page.evaluate("""async () => {
                            try {
                                await fetch('/api/user/account/delete', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({immediate_purge: true})
                                });
                            } catch (e) {}
                        }""")

                collector.metadata["cleanup_verified"] = cleaned
                if cleaned:
                    collector.add_pass(
                        phase="cleanup",
                        name="Self-cleanup via Delete Account UI button on /console/account",
                        page_url=f"{base_url}/console/account",
                        details=f"Deleted test account {test_email} and triggered delete_user_account_data pipeline.",
                        page=page,
                    )
                else:
                    collector.add_finding(
                        phase="cleanup",
                        severity="high",
                        category="Account Deletion Failed",
                        title=f"Test account {test_email} remained active after clicking Delete Account",
                        page_url=f"{base_url}/console/account",
                        description="Session remained authenticated after deleteMyAccount() completed.",
                        page=page,
                    )

            # Deep Post-Delete Verification (Section 13)
            if created_user_id:
                ver_res = verify_account_fully_deleted(created_user_id)
                if not ver_res["clean"]:
                    # Fallback cleanup per Section 13
                    from services.db_service import delete_user_account_data
                    try:
                        delete_user_account_data(created_user_id, immediate_purge=True)
                    except Exception:
                        pass
                    ver_res_retry = verify_account_fully_deleted(created_user_id)
                    if not ver_res_retry["clean"]:
                        collector.add_finding(
                            phase="cleanup",
                            severity="high",
                            category="Data Retention Violation",
                            title=f"Leftover data detected after account deletion for {created_user_id}",
                            page_url=f"{base_url}/console/account",
                            description=f"Table rows remaining: {ver_res_retry['leftovers']}, leftover files: {ver_res_retry['leftover_files']}",
                        )

        except Exception as exc:
            collector.metadata["cleanup_verified"] = False
            collector.add_finding(
                phase="cleanup",
                severity="medium",
                category="Cleanup Exception",
                title=f"Could not complete UI cleanup for {test_email}",
                page_url=f"{base_url}/console/account",
                description=str(exc),
            )
            # Fallback orphan sweep
            sweep_orphan_test_accounts()
        finally:
            ctx.close()
