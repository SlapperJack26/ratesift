"""Phase 0: Network-level safety enforcement, profile gating, and destructive action registry."""
from __future__ import annotations

import re
from typing import Any, List, Set
from urllib.parse import urlparse
from playwright.sync_api import BrowserContext, Route, Request

from qa_agent.config import (
    DESTRUCTIVE_ACTIONS_REGISTRY,
    NETWORK_BLOCKED_ENDPOINT_PATTERNS,
    RunConfig,
)
from qa_agent.findings import FindingsCollector


class SafetyManager:
    """Manages browser request filtering, domain boundaries, and destructive action checks."""

    def __init__(self, cfg: RunConfig, collector: FindingsCollector) -> None:
        self.cfg = cfg
        self.collector = collector
        self.blocked_requests: List[dict] = []
        parsed = urlparse(cfg.base_url)
        self.allowed_host: str = parsed.hostname or "127.0.0.1"

    def install_safety_layer(self, context: BrowserContext) -> None:
        """Installs context.route() handlers once per browser context (Section 5.3)."""
        def route_handler(route: Route) -> None:
            req: Request = route.request
            url = req.url
            parsed_req = urlparse(url)
            req_host = parsed_req.hostname or ""

            # 1. Deny requests to external hosts (except data:, blob:, or localhost test target)
            if parsed_req.scheme in ("http", "https"):
                is_target_host = (
                    req_host == self.allowed_host
                    or (self.allowed_host in ("127.0.0.1", "localhost") and req_host in ("127.0.0.1", "localhost"))
                )
                if not is_target_host:
                    # Abort external navigation/fetch by browser
                    self.blocked_requests.append({
                        "url": url,
                        "method": req.method,
                        "reason": f"External domain '{req_host}' aborted by safety layer"
                    })
                    route.abort("blockedbyclient")
                    return

            # 2. Block billing, payment, upgrade, and API key generation endpoints
            url_lower = url.lower()
            for pattern in NETWORK_BLOCKED_ENDPOINT_PATTERNS:
                if pattern in url_lower:
                    self.blocked_requests.append({
                        "url": url,
                        "method": req.method,
                        "reason": f"Network blocked endpoint pattern '{pattern}'"
                    })
                    # Log as skipped (unsafe)
                    self.collector.add_finding(
                        phase="safety",
                        severity="info",
                        category="Safety Denylist",
                        title=f"Blocked attempt to access sensitive endpoint: {pattern}",
                        page_url=url,
                        description=f"Network safety layer intercepted and aborted {req.method} request to {url}.",
                    )
                    route.abort("blockedbyclient")
                    return

            # Allow safe requests to proceed
            route.continue_()

        context.route("**/*", route_handler)

    def is_action_destructive(self, label: str, onclick: str = "", href: str = "") -> bool:
        """Determines if a DOM control matches the destructive action registry (Section 5.4)."""
        combined = f"{label} {onclick} {href}".lower()
        for pattern in DESTRUCTIVE_ACTIONS_REGISTRY:
            if pattern in combined:
                return True
        return False

    def assert_phase_allowed(self, phase_name: str) -> bool:
        """Enforces profile gating before executing potentially destructive phases."""
        if not self.cfg.is_phase_allowed(phase_name):
            msg = (
                f"Phase '{phase_name}' is not permitted under environment profile '{self.cfg.profile}'. "
                f"Destructive or mutating tests require local or confirmed staging hosts."
            )
            self.collector.add_finding(
                phase="safety",
                severity="critical",
                category="Profile Gating Violation",
                title=f"Phase '{phase_name}' blocked by environment profile '{self.cfg.profile}'",
                page_url=self.cfg.base_url,
                description=msg,
            )
            raise PermissionError(msg)
        return True
