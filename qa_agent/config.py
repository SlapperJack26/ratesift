"""Configuration, environment profiles, safety rules, and limits for the Quotelytics QA Agent."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Set
from urllib.parse import urlparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "quotelytics.db")
SAMPLE_SHEETS_DIR = os.path.join(PROJECT_ROOT, "sample_sheets")
REPORTS_ROOT = os.path.join(PROJECT_ROOT, "reports")
BASELINE_FILE = os.path.join(PROJECT_ROOT, "qa_agent", "baseline.json")
ALLOWLISTS_DIR = os.path.join(PROJECT_ROOT, "qa_agent", "allowlists")

# Target base URL
DEFAULT_BASE_URL = os.getenv("QA_BASE_URL", "http://127.0.0.1:8000")

# Viewports
VIEWPORT_DESKTOP = {"width": 1440, "height": 900}
VIEWPORT_MOBILE = {"width": 390, "height": 844}
VIEWPORT = VIEWPORT_DESKTOP

# Environment Profiles & Gating (Section 4)
STAGING_HOSTS: List[str] = [
    "staging.quotelytics.internal",
    "staging-quotelytics.onrender.com",
]

LOCAL_HOSTS: Set[str] = {"127.0.0.1", "localhost"}

# Free Starter Tier Limits
FREE_TIER_MAX_SHEETS = 3
FREE_TIER_MAX_QUOTES = 50

# Seed Routes
PUBLIC_SEED_ROUTES: List[str] = [
    "/",
    "/demo",
    "/pricing",
    "/privacy",
    "/terms",
    "/refunds",
    "/login",
    "/get-started",
    "/failsafe/demo",
    "/flowchart",
    "/showcase",
    "/docs",
]

CONSOLE_ROUTES: List[str] = [
    "/console/new-quote",
    "/console/history",
    "/console/rate-sheets",
    "/console/account",
    "/console/settings",
]

# Destructive Actions Registry (Section 5.4)
# Generic interaction tester must NEVER click these controls;
# they run strictly in dedicated auth/cleanup phases.
DESTRUCTIVE_ACTIONS_REGISTRY: List[str] = [
    "delete account",
    "delete my account",
    "permanently delete",
    "log out",
    "logout",
    "sign out",
    "change password",
    "update password",
    "upgrade tier",
    "upgrade plan",
    "start 14-day",
    "start free team trial",
    "generate api key",
    "create key",
    "invite member",
    "send invite",
    "remove member",
]

# Network-level Safety: Endpoints blocked via context.route() (Section 5.3)
NETWORK_BLOCKED_ENDPOINT_PATTERNS: List[str] = [
    "/api/user/upgrade-tier",
    "/api/user/api-key/generate",
    "/api/team/invite",
    "/api/team/members/remove",
    "/api/billing",
    "/checkout",
    "stripe.com",
    "api.stripe.com",
]

# Protected read-only GET endpoints to verify 401/403 when unauthenticated (Check S4)
PROTECTED_READ_ENDPOINTS: List[str] = [
    "/api/user/quota",
    "/api/user/bottlenecks",
    "/api/admin/bottlenecks",
    "/api/team/members",
    "/api/user/profile",
    "/api/notifications",
    "/api/quotes/history",
    "/api/quotelytics/sheets",
    "/api/quotelytics/sheets/ql_sheet_test",
    "/api/quotelytics/sheets/ql_sheet_test/breaks",
    "/api/quotelytics/sheets/ql_sheet_test/formatted-matrix",
    "/api/quotelytics/sheets/ql_sheet_test/cells",
    "/api/quotelytics/quotes/audit",
    "/api/quotelytics/quotes/audit/QL-TEST",
    "/api/quotes/export",
    "/api/quotes/client-proposal/memory",
    "/api/fuel-indices/settings",
    "/mappings",
]

# Strings that must never appear on public pages or fresh test accounts (Check S3 & S5)
FORBIDDEN_ADMIN_LEAK_STRINGS: List[str] = [
    "alex.rivers@techcorp.io",
    "QuotelyticsDemo2026!",
    "session_demo_alex_rivers",
    "ql_live_demo_alex_rivers_key_2026",
    "sf_live_demo_alex_rivers_key_2026",
    "usr_alex_rivers",
]

# AI Explorer Configuration (Section 11)
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL_ID = "gemini-2.5-flash"
AI_MAX_STEPS = 15
AI_TEMPERATURE = 0.0
AI_MAX_TOKENS = 40000


def get_environment_profile(base_url: str) -> str:
    """Returns 'local', 'staging', or 'prod-smoke' based on base_url."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    if host in LOCAL_HOSTS:
        return "local"
    if host in STAGING_HOSTS:
        return "staging"
    return "prod-smoke"


@dataclass
class RunConfig:
    base_url: str = DEFAULT_BASE_URL
    headless: bool = True
    browser_name: str = "chromium"  # chromium | firefox | webkit
    check_external_links: bool = True
    staging_confirmed: bool = False
    fail_on_medium: bool = False
    enable_ai_explorer: bool = False
    phases: Set[str] = field(
        default_factory=lambda: {
            "crawl",
            "brand",
            "interactions",
            "security",
            "auth",
            "free_tier",
            "ai_explorer",
        }
    )
    max_quotes_to_run: int = FREE_TIER_MAX_QUOTES
    test_email_domain: str = "quotelytics.test"

    @property
    def profile(self) -> str:
        return get_environment_profile(self.base_url)

    def is_phase_allowed(self, phase_name: str) -> bool:
        """Enforces profile gating (Section 4)."""
        prof = self.profile
        if prof == "local":
            return True
        if prof == "staging":
            return self.staging_confirmed
        # prod-smoke: only read-only phases allowed
        allowed_read_only = {"crawl", "brand", "axe"}
        return phase_name in allowed_read_only
