"""Findings collector, baseline diffing (New / Open / Fixed), and screenshot helper."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def normalize_page_path(url_or_path: str) -> str:
    """Normalizes a full URL or relative path to a stable path (e.g. /pricing)."""
    if "://" in url_or_path:
        parsed = urlparse(url_or_path)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return path
    return url_or_path.split("?")[0] if "?" in url_or_path else (url_or_path or "/")


@dataclass
class Finding:
    phase: str
    severity: str  # critical | high | medium | low | info
    category: str
    title: str
    page_url: str
    description: str
    element: str = ""
    steps_to_reproduce: List[str] = field(default_factory=list)
    screenshot_rel: Optional[str] = None
    status_delta: str = "new"  # new | still_open
    fingerprint: str = ""

    def __post_init__(self) -> None:
        self.severity = self.severity.lower()
        if not self.fingerprint:
            norm_page = normalize_page_path(self.page_url)
            norm_elem = (self.element or "").strip().lower()
            # Stable fingerprint: rule/category + normalized page + selector/element
            raw = f"{self.category}|{norm_page}|{norm_elem}"
            self.fingerprint = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class CheckPass:
    phase: str
    name: str
    page_url: str
    details: str = ""
    screenshot_rel: Optional[str] = None


class FindingsCollector:
    def __init__(self, report_dir: str, baseline_path: str) -> None:
        self.report_dir = report_dir
        self.screenshots_dir = os.path.join(report_dir, "screenshots")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        self.baseline_path = baseline_path
        self.findings: List[Finding] = []
        self.passes: List[CheckPass] = []
        self.pages_crawled: List[Dict[str, Any]] = []
        self.links_checked: List[Dict[str, Any]] = []
        self.buttons_tested: List[Dict[str, Any]] = []
        self.fixed_findings: List[Dict[str, Any]] = []
        self.ai_findings: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "cleanup_verified": None,
            "git_clean_verified": None,
            "db_backup": None,
            "harness_status": "ok",
        }
        self._shot_counter = 0
        self._seen_fingerprints: set[str] = set()

    def take_screenshot(self, page: Any, label: str, full_page: bool = False) -> Optional[str]:
        """Captures a browser screenshot into reports/<ts>/screenshots/ and returns its relative path."""
        try:
            self._shot_counter += 1
            safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", label).strip("_")[:50] or "shot"
            filename = f"{self._shot_counter:03d}_{safe}.png"
            abs_path = os.path.join(self.screenshots_dir, filename)
            page.screenshot(path=abs_path, full_page=full_page, timeout=8000)
            return f"screenshots/{filename}"
        except Exception:
            return None

    def add_finding(
        self,
        *,
        phase: str,
        severity: str,
        category: str,
        title: str,
        page_url: str,
        description: str,
        element: str = "",
        steps_to_reproduce: Optional[List[str]] = None,
        page: Any = None,
        screenshot_rel: Optional[str] = None,
    ) -> Finding:
        f = Finding(
            phase=phase,
            severity=severity,
            category=category,
            title=title,
            page_url=page_url,
            description=description,
            element=element,
            steps_to_reproduce=steps_to_reproduce or [],
            screenshot_rel=screenshot_rel,
        )
        if f.fingerprint in self._seen_fingerprints:
            return f
        self._seen_fingerprints.add(f.fingerprint)

        if page is not None and not f.screenshot_rel:
            f.screenshot_rel = self.take_screenshot(page, f"{phase}_{category}_{title[:24]}")

        self.findings.append(f)
        return f

    def add_pass(
        self,
        phase: str,
        name: str,
        page_url: str,
        details: str = "",
        page: Any = None,
        screenshot_rel: Optional[str] = None,
    ) -> None:
        if page is not None and not screenshot_rel:
            screenshot_rel = self.take_screenshot(page, f"pass_{phase}_{name[:24]}")
        self.passes.append(
            CheckPass(
                phase=phase,
                name=name,
                page_url=page_url,
                details=details,
                screenshot_rel=screenshot_rel,
            )
        )

    def apply_baseline_and_save(self) -> None:
        """Marks each finding as 'new' or 'still_open', identifies 'fixed' items, and updates the baseline."""
        previous: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(self.baseline_path):
            try:
                with open(self.baseline_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    for item in data.get("findings", []):
                        previous[item["fingerprint"]] = item
            except Exception:
                previous = {}

        current_map: Dict[str, Dict[str, Any]] = {}
        for f in self.findings:
            if f.fingerprint in previous:
                f.status_delta = "still_open"
            else:
                f.status_delta = "new"
            current_map[f.fingerprint] = asdict(f)

        self.fixed_findings = [
            item for fp, item in previous.items() if fp not in current_map
        ]

        # Sort findings by severity
        self.findings.sort(key=lambda x: SEVERITY_ORDER.get(x.severity, 99))

        try:
            with open(self.baseline_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                        "findings": list(current_map.values()),
                    },
                    fh,
                    indent=2,
                )
        except Exception:
            pass

    def compute_ci_exit_code(self, fail_on_medium: bool = False) -> int:
        """
        Computes CI exit codes according to Section 12:
        0: No new Critical, High or Medium issues (advisory & Low allowed).
        1: New Critical or High issues detected.
        2: New Medium issues detected (if fail_on_medium is enabled).
        3: Harness failure (unreachable server, safety/backup failure).
        """
        if self.metadata.get("harness_status") != "ok":
            return 3

        new_critical_high = [
            f for f in self.findings
            if f.status_delta == "new" and f.severity in ("critical", "high")
        ]
        if new_critical_high:
            return 1

        new_medium = [
            f for f in self.findings
            if f.status_delta == "new" and f.severity == "medium"
        ]
        if new_medium and fail_on_medium:
            return 2

        return 0

    def summary_counts(self) -> Dict[str, int]:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        counts["total_findings"] = len(self.findings)
        counts["new_findings"] = sum(1 for f in self.findings if f.status_delta == "new")
        counts["still_open"] = sum(1 for f in self.findings if f.status_delta == "still_open")
        counts["fixed"] = len(self.fixed_findings)
        counts["passes"] = len(self.passes)
        counts["pages_crawled"] = len(self.pages_crawled)
        counts["links_checked"] = len(self.links_checked)
        counts["buttons_tested"] = len(self.buttons_tested)
        counts["ai_findings"] = len(self.ai_findings)
        return counts
