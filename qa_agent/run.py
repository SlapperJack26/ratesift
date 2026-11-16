"""Main CLI Orchestrator for the Quotelytics Automated QA Agent."""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from qa_agent.ai_explorer import run_ai_explorer_pass
from qa_agent.brand import scan_page_for_brand_leaks
from qa_agent.config import (
    BASELINE_FILE,
    DB_PATH,
    DEFAULT_BASE_URL,
    PROJECT_ROOT,
    REPORTS_ROOT,
    VIEWPORT,
    RunConfig,
)
from qa_agent.crawler import run_crawler_phase
from qa_agent.db_tools import backup_database, sweep_orphan_test_accounts
from qa_agent.findings import FindingsCollector
from qa_agent.interactions import test_buttons_on_routes
from qa_agent.report import generate_reports
from qa_agent.safety import SafetyManager
from qa_agent.security_checks import (
    report_code_review_findings,
    run_active_tenant_and_header_security_tests,
    run_security_checks_unauthenticated,
)


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def _ensure_local_server(base_url: str, report_dir: str = "") -> Optional[subprocess.Popen]:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if host not in ("127.0.0.1", "localhost"):
        return None
    if _is_port_open(host, port):
        return None

    log_file = open(os.path.join(report_dir, "server.log"), "w", encoding="utf-8") if report_dir else subprocess.DEVNULL
    proc = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=PROJECT_ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        if _is_port_open(host, port):
            return proc
        time.sleep(0.5)
    return proc


def _git_status_snapshot() -> str:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        ignored_patterns = (
            "qa_agent",
            "reports",
            ".gitignore",
            "scratch",
            "conversation_data",
            "__pycache__",
            ".pytest_cache",
            ".website_snapshots",
        )
        lines = [
            ln
            for ln in res.stdout.splitlines()
            if not any(p in ln for p in ignored_patterns)
        ]
        return "\n".join(lines)
    except Exception:
        return ""


def run_qa_suite(cfg: RunConfig) -> int:
    """Executes the full QA suite (Phases 0 through 6) and returns the CI exit code."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = os.path.join(REPORTS_ROOT, ts)
    os.makedirs(report_dir, exist_ok=True)

    collector = FindingsCollector(report_dir=report_dir, baseline_path=BASELINE_FILE)
    collector.metadata["base_url"] = cfg.base_url
    collector.metadata["profile"] = cfg.profile

    # ------------------------------------------------------------------
    # Phase 0: Harness & Safety Verification (Section 5)
    # ------------------------------------------------------------------
    # 1. Clean orphan test accounts from previous runs
    purged = sweep_orphan_test_accounts()
    if purged:
        collector.metadata["pre_run_purged_orphans"] = purged

    # 2. Backup database via SQLite backup API (WAL-safe)
    if cfg.profile in ("local", "staging") and os.path.exists(DB_PATH):
        bak_name = os.path.basename(DB_PATH) + ".bak"
        bak_path = os.path.join(report_dir, bak_name)
        success = backup_database(dest_path=bak_path, src_path=DB_PATH)
        if success:
            collector.metadata["db_backup"] = bak_path
        else:
            collector.metadata["harness_status"] = "backup_failed"
            collector.add_finding(
                phase="safety",
                severity="critical",
                category="DB Backup Failed",
                title="Failed to create safe SQLite backup prior to run",
                page_url=cfg.base_url,
                description="Database snapshot failed. Halting suite to prevent data corruption.",
            )
            generate_reports(collector, fail_on_medium=cfg.fail_on_medium)
            return 3

    # 3. Server health check
    server_proc = _ensure_local_server(cfg.base_url, report_dir=report_dir)
    parsed = urlparse(cfg.base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not _is_port_open(host, port):
        collector.metadata["harness_status"] = "server_unreachable"
        collector.add_finding(
            phase="safety",
            severity="critical",
            category="Server Unreachable",
            title=f"Could not connect to {cfg.base_url}",
            page_url=cfg.base_url,
            description=f"Server port {port} is closed. Please start the Quotelytics server.",
        )
        generate_reports(collector, fail_on_medium=cfg.fail_on_medium)
        return 3

    git_before = _git_status_snapshot()

    try:
        with sync_playwright() as pw:
            browser_launcher = getattr(pw, cfg.browser_name)
            browser = browser_launcher.launch(headless=cfg.headless)

            # Phase 1: Public Crawler, Link & Brand Checker
            if "crawl" in cfg.phases or "brand" in cfg.phases:
                ctx_crawl = browser.new_context(viewport=VIEWPORT)
                safety = SafetyManager(cfg, collector)
                safety.install_safety_layer(ctx_crawl)
                run_crawler_phase(ctx_crawl, cfg, collector, phase_label="crawl-public")
                ctx_crawl.close()

            # Phase 4a: Public Interactive Controls Tester
            if "interactions" in cfg.phases:
                ctx_int = browser.new_context(viewport=VIEWPORT)
                safety = SafetyManager(cfg, collector)
                safety.install_safety_layer(ctx_int)
                pub_routes = [p["path"] for p in collector.pages_crawled if not p["path"].startswith("/console")]
                if not pub_routes:
                    pub_routes = ["/", "/demo", "/pricing", "/login", "/get-started"]
                test_buttons_on_routes(ctx_int, cfg, collector, pub_routes, phase_label="interactions-public")
                ctx_int.close()

            # Phase 2a: Unauthenticated Security Regression Checks (S1-S4)
            if "security" in cfg.phases:
                run_security_checks_unauthenticated(browser, cfg, collector)
                report_code_review_findings(collector)

                # Phase 2b: Active Black-Box Multi-Tenant IDOR and Header Tests (local/staging)
                if cfg.profile in ("local", "staging"):
                    run_active_tenant_and_header_security_tests(cfg.base_url, cfg, collector)

            # Phase 2c & Phase 3: Auth Flows, Route Guarding, Free-Tier Journey & UI Account Deletion
            if ("auth" in cfg.phases or "free_tier" in cfg.phases) and cfg.profile in ("local", "staging"):
                from qa_agent.auth_flows import run_auth_and_free_tier_journey

                run_auth_and_free_tier_journey(browser, cfg, collector)

            # Phase 5: AI Explorer Pass (Advisory)
            if "ai_explorer" in cfg.phases:
                run_ai_explorer_pass(browser, cfg, collector)

            # Phase 6: Platform Hardening & Concurrency Resilience
            if "hardening" in cfg.phases and cfg.profile in ("local", "staging"):
                from qa_agent.hardening import run_hardening_suite

                run_hardening_suite(cfg, collector)

            browser.close()
    finally:
        if server_proc is not None:
            try:
                server_proc.terminate()
            except Exception:
                pass
        # End-of-run orphan sweep (Section 5.6 & 13)
        sweep_orphan_test_accounts()

    # Verify project worktree remained intact
    git_after = _git_status_snapshot()
    collector.metadata["git_clean_verified"] = git_before == git_after
    if git_before != git_after:
        collector.add_finding(
            phase="safety",
            severity="critical",
            category="Worktree Modified",
            title="Project files outside qa_agent/ changed during the QA run",
            page_url=cfg.base_url,
            description="git status before and after the QA run differed.",
        )

    html_path = generate_reports(collector, fail_on_medium=cfg.fail_on_medium)
    exit_code = collector.metadata.get("exit_code", 0)
    print(f"\n[Quotelytics QA Agent] Run completed. Report generated at:\n  {html_path}")
    print(f"[Quotelytics QA Agent] Exit Code: {exit_code}")
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Quotelytics Automated QA Agent")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Target URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser in headless mode")
    parser.add_argument("--headed", dest="headless", action="store_false", help="Run browser in headed mode")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"], help="Browser engine")
    parser.add_argument("--i-understand-this-is-staging", action="store_true", dest="staging_confirmed", help="Confirmation flag for staging runs")
    parser.add_argument("--fail-on-medium", action="store_true", help="Return non-zero exit code on Medium severity issues")
    parser.add_argument("--enable-ai", action="store_true", dest="enable_ai_explorer", help="Enable the AI Explorer pass")
    parser.add_argument("--hardening", action="store_true", dest="enable_hardening", help="Enable the Platform Hardening & Concurrency suite")
    parser.add_argument("--phases", default="all", help="Comma-separated list of phases to execute")

    args = parser.parse_args()

    phases_set = {
        "crawl",
        "brand",
        "interactions",
        "security",
        "auth",
        "free_tier",
    }
    if args.enable_ai_explorer:
        phases_set.add("ai_explorer")
    if args.enable_hardening:
        phases_set.add("hardening")

    if args.phases != "all":
        phases_set = set(p.strip() for p in args.phases.split(",") if p.strip())

    cfg = RunConfig(
        base_url=args.base_url,
        headless=args.headless,
        browser_name=args.browser,
        staging_confirmed=args.staging_confirmed,
        fail_on_medium=args.fail_on_medium,
        enable_ai_explorer=args.enable_ai_explorer,
        phases=phases_set,
    )

    exit_code = run_qa_suite(cfg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
