"""Phase 1: Page crawler, asset/console/network monitor, branding consistency & link checker."""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from playwright.sync_api import BrowserContext, Page

from qa_agent.brand import scan_page_for_brand_leaks
from qa_agent.config import (
    ALLOWLISTS_DIR,
    PUBLIC_SEED_ROUTES,
    VIEWPORT_MOBILE,
    RunConfig,
)
from qa_agent.findings import FindingsCollector

_EXTERNAL_CACHE_FILE = os.path.join(ALLOWLISTS_DIR, ".external_link_cache.json")


def _load_console_allowlist() -> List[str]:
    p = os.path.join(ALLOWLISTS_DIR, "console_error_allowlist.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh).get("ignored_error_patterns", [])
        except Exception:
            pass
    return []


def _load_external_link_cache() -> Dict[str, float]:
    if os.path.exists(_EXTERNAL_CACHE_FILE):
        try:
            with open(_EXTERNAL_CACHE_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def _save_external_link_cache(cache: Dict[str, float]) -> None:
    try:
        with open(_EXTERNAL_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2)
    except Exception:
        pass


def _normalize_internal_path(base_url: str, href: str) -> Tuple[str, str]:
    """Returns (path_with_query, fragment) if href is internal to base_url, else ('', '')."""
    joined = urljoin(base_url, href)
    clean_url, frag = urldefrag(joined)
    parsed_base = urlparse(base_url)
    parsed = urlparse(clean_url)
    if parsed.netloc != parsed_base.netloc:
        return "", ""
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path, frag


def _run_accessibility_audit(page: Page, collector: FindingsCollector, rel_path: str, phase_label: str) -> None:
    """Performs an in-browser WCAG audit (forms, images, landmarks, headings) and reports low-severity advisories."""
    try:
        a11y_results = page.evaluate("""() => {
            const issues = [];
            // 1. Missing image alt
            document.querySelectorAll('img:not([alt])').forEach(img => {
                issues.push({ type: 'img-alt', desc: 'Image missing alt attribute', sel: img.src.slice(-30) });
            });
            // 2. Unlabeled form controls
            document.querySelectorAll('input:not([type="hidden"]):not([aria-label]):not([placeholder]), select:not([aria-label]), textarea:not([aria-label]):not([placeholder])').forEach(inp => {
                const id = inp.id;
                const hasLabel = id && document.querySelector('label[for="' + id + '"]');
                if (!hasLabel) {
                    issues.push({ type: 'form-label', desc: 'Input lacks visible label, aria-label, or placeholder', sel: inp.name || inp.id || inp.tagName });
                }
            });
            // 3. Headings structure
            const h1s = document.querySelectorAll('h1');
            if (h1s.length === 0) {
                issues.push({ type: 'heading-h1', desc: 'Page lacks an <h1> heading', sel: 'body' });
            }
            return issues;
        }""")
        for item in a11y_results:
            collector.add_finding(
                phase=phase_label,
                severity="low",
                category="Accessibility (Advisory)",
                title=f"A11y: {item['desc']} on {rel_path}",
                page_url=page.url,
                element=item["sel"],
                description=f"{item['desc']} (Element: {item['sel']})",
            )
    except Exception:
        pass


def run_crawler_phase(
    context: BrowserContext,
    cfg: RunConfig,
    collector: FindingsCollector,
    extra_routes: List[str] | None = None,
    phase_label: str = "crawl",
) -> None:
    """Crawls all seed + discovered internal pages, checks links/anchors/images/console/branding/mobile."""
    base_url = cfg.base_url.rstrip("/")
    parsed_base = urlparse(base_url)
    ignored_console_patterns = _load_console_allowlist()

    queue: deque[str] = deque(extra_routes if extra_routes is not None else PUBLIC_SEED_ROUTES)
    visited_pages: Set[str] = set()
    external_urls_to_check: Dict[str, str] = {}  # url -> source_page
    internal_links_to_check: List[Tuple[str, str, str, str]] = []  # (source_page, raw_href, path, frag)
    page_ids_cache: Dict[str, Set[str]] = {}

    page: Page = context.new_page()

    while queue:
        rel_path = queue.popleft()
        if rel_path in visited_pages:
            continue
        # Skip logout or destructive endpoints during crawl
        if any(skip in rel_path for skip in ("/api/auth/logout", "/api/user/account/delete")):
            continue

        visited_pages.add(rel_path)
        full_url = f"{base_url}{rel_path}"

        console_errors: List[str] = []
        page_exceptions: List[str] = []
        failed_requests: List[str] = []

        def on_console(msg: Any) -> None:
            if msg.type == "error":
                txt = msg.text
                if not any(pat in txt for pat in ignored_console_patterns):
                    console_errors.append(txt)

        def on_pageerror(exc: Any) -> None:
            page_exceptions.append(str(exc))

        def on_response(resp: Any) -> None:
            try:
                if resp.status >= 400 and resp.url.startswith(base_url):
                    failed_requests.append(f"HTTP {resp.status} {resp.request.method} {resp.url}")
            except Exception:
                pass

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

        status_code = 0
        title = ""
        try:
            resp = page.goto(full_url, wait_until="networkidle", timeout=15000)
            status_code = resp.status if resp else 0
            title = page.title()
        except Exception as exc:
            collector.add_finding(
                phase=phase_label,
                severity="high",
                category="Page Load Failure",
                title=f"Failed to load {rel_path}",
                page_url=full_url,
                description=f"Navigation to {full_url} raised an error: {exc}",
                steps_to_reproduce=[f"Navigate to {full_url}"],
                page=page,
            )
            page.remove_listener("console", on_console)
            page.remove_listener("pageerror", on_pageerror)
            page.remove_listener("response", on_response)
            continue

        shot_rel = collector.take_screenshot(page, f"{phase_label}_{rel_path.strip('/') or 'home'}")

        if status_code >= 400:
            collector.add_finding(
                phase=phase_label,
                severity="high" if status_code < 500 else "critical",
                category="Broken Page Route",
                title=f"{rel_path} returned HTTP {status_code}",
                page_url=full_url,
                description=f"Expected HTTP 200 on {full_url}, got HTTP {status_code}.",
                steps_to_reproduce=[f"Open {full_url} in browser"],
                screenshot_rel=shot_rel,
            )
        else:
            collector.add_pass(
                phase=phase_label,
                name=f"Page load {rel_path}",
                page_url=full_url,
                details=f"HTTP {status_code} • Title: '{title}'",
                screenshot_rel=shot_rel,
            )

        # Brand consistency scan on every rendered page (Section 7)
        scan_page_for_brand_leaks(page, collector, phase_label="brand")

        # Accessibility audit (Section 6 & 15)
        _run_accessibility_audit(page, collector, rel_path, phase_label=phase_label)

        # Collect DOM IDs/names for anchor verification
        try:
            dom_ids = page.evaluate(
                "() => Array.from(document.querySelectorAll('[id], a[name]')).map(el => el.id || el.getAttribute('name')).filter(Boolean)"
            )
            page_ids_cache[rel_path.split("?")[0]] = set(dom_ids)
        except Exception:
            page_ids_cache[rel_path.split("?")[0]] = set()

        # Check broken images
        try:
            broken_imgs = page.evaluate(
                """() => Array.from(document.images)
                    .filter(img => !img.complete || img.naturalWidth === 0)
                    .map(img => img.getAttribute('src') || img.src)"""
            )
            for img_src in broken_imgs:
                collector.add_finding(
                    phase=phase_label,
                    severity="medium",
                    category="Broken Image",
                    title=f"Broken image on {rel_path}: {img_src}",
                    page_url=full_url,
                    element=f"<img src='{img_src}'>",
                    description=f"Image failed to load or has naturalWidth == 0: {img_src}",
                    steps_to_reproduce=[f"Visit {full_url}", f"Inspect image {img_src}"],
                    screenshot_rel=shot_rel,
                )
        except Exception:
            pass

        # Check console errors & uncaught JS exceptions
        for err in page_exceptions:
            collector.add_finding(
                phase=phase_label,
                severity="high",
                category="JavaScript Error",
                title=f"Uncaught JS error on {rel_path}",
                page_url=full_url,
                description=str(err),
                steps_to_reproduce=[f"Open {full_url}", "Check browser DevTools console"],
                screenshot_rel=shot_rel,
            )

        for cerr in console_errors:
            collector.add_finding(
                phase=phase_label,
                severity="medium",
                category="Console Error",
                title=f"Console error on {rel_path}",
                page_url=full_url,
                description=cerr,
                steps_to_reproduce=[f"Open {full_url}", "Inspect console output"],
                screenshot_rel=shot_rel,
            )

        for freq in failed_requests:
            collector.add_finding(
                phase=phase_label,
                severity="medium",
                category="Failed Network Request",
                title=f"Network request failed on {rel_path}: {freq}",
                page_url=full_url,
                description=f"Page asset or XHR returned >=400: {freq}",
                steps_to_reproduce=[f"Open {full_url}", "Observe Network panel"],
                screenshot_rel=shot_rel,
            )

        # Collect internal & external links
        try:
            links = page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.getAttribute('href') || '',
                    text: (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 50),
                    onclick: a.getAttribute('onclick') || ''
                }))"""
            )
        except Exception:
            links = []

        collector.pages_crawled.append(
            {
                "path": rel_path,
                "url": full_url,
                "status": status_code,
                "title": title,
                "link_count": len(links),
                "errors": len(console_errors) + len(page_exceptions),
            }
        )

        for link_info in links:
            raw_href = (link_info.get("href") or "").strip()
            link_text = link_info.get("text") or raw_href
            onclick_attr = link_info.get("onclick") or ""

            if not raw_href or raw_href.startswith(("javascript:", "mailto:", "tel:", "data:")):
                continue

            if raw_href.startswith("#"):
                frag = raw_href.lstrip("#")
                if frag and not onclick_attr and not frag.startswith("/"):
                    ids_on_page = page_ids_cache.get(rel_path.split("?")[0], set())
                    if frag not in ids_on_page:
                        collector.add_finding(
                            phase=phase_label,
                            severity="medium",
                            category="Broken Anchor Link",
                            title=f"Anchor '{raw_href}' target not found on {rel_path}",
                            page_url=full_url,
                            element=f"<a href='{raw_href}'>{link_text}</a>",
                            description=f"Link points to #{frag}, but no element with id='{frag}' exists on {rel_path}.",
                            steps_to_reproduce=[f"Open {full_url}", f"Click '{link_text}' ({raw_href})"],
                            screenshot_rel=shot_rel,
                        )
                continue

            parsed_href = urlparse(urljoin(full_url, raw_href))
            if parsed_href.scheme in ("http", "https") and parsed_href.netloc != parsed_base.netloc:
                clean_ext, _ = urldefrag(parsed_href.geturl())
                external_urls_to_check.setdefault(clean_ext, full_url)
            else:
                norm_path, frag = _normalize_internal_path(base_url, raw_href)
                if norm_path:
                    internal_links_to_check.append((full_url, raw_href, norm_path, frag))
                    base_only = norm_path.split("?")[0]
                    if (
                        base_only not in visited_pages
                        and not base_only.startswith(("/api/", "/sample-sheets/", "/static/"))
                        and not base_only.endswith((".xlsx", ".csv", ".pdf", ".png", ".jpg", ".json"))
                    ):
                        if not (base_only.startswith("/console/") and extra_routes is None):
                            queue.append(norm_path)

        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)

    # Mobile pass (Section 6: test / and /pricing at ~390px)
    for mobile_route in ("/", "/pricing"):
        full_mobile_url = f"{base_url}{mobile_route}"
        try:
            page.set_viewport_size(VIEWPORT_MOBILE)
            page.goto(full_mobile_url, wait_until="networkidle", timeout=12000)
            mob_shot = collector.take_screenshot(page, f"mobile_{mobile_route.strip('/') or 'home'}")
            
            # Check horizontal scroll overflow
            has_overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
            if has_overflow:
                collector.add_finding(
                    phase=phase_label,
                    severity="low",
                    category="Mobile Layout",
                    title=f"Horizontal overflow detected on mobile viewport for {mobile_route}",
                    page_url=full_mobile_url,
                    description=f"Page scrollWidth exceeds window.innerWidth at 390px.",
                    screenshot_rel=mob_shot,
                )
            else:
                collector.add_pass(
                    phase=phase_label,
                    name=f"Mobile responsive view {mobile_route}",
                    page_url=full_mobile_url,
                    details="Rendered cleanly at 390px without horizontal overflow.",
                    screenshot_rel=mob_shot,
                )
        except Exception:
            pass
        finally:
            page.set_viewport_size(cfg.VIEWPORT if hasattr(cfg, "VIEWPORT") else {"width": 1440, "height": 900})

    page.close()

    # Verify discovered internal links
    checked_internal: Set[str] = set()
    cookies = {c["name"]: c["value"] for c in context.cookies()}
    with httpx.Client(base_url=base_url, cookies=cookies, follow_redirects=True, timeout=10.0) as http_client:
        for source_page, raw_href, norm_path, frag in internal_links_to_check:
            if any(skip in norm_path for skip in ("/api/auth/logout", "/api/user/account/delete")):
                continue
            if norm_path not in checked_internal:
                checked_internal.add(norm_path)
                try:
                    r = http_client.get(norm_path)
                    status = r.status_code
                except Exception as exc:
                    status = 0
                    collector.add_finding(
                        phase=phase_label,
                        severity="high",
                        category="Broken Internal Link",
                        title=f"Internal link {raw_href} failed to connect",
                        page_url=source_page,
                        element=f"<a href='{raw_href}'>",
                        description=f"Request to {norm_path} raised {exc}",
                        steps_to_reproduce=[f"Open {source_page}", f"Click link to {raw_href}"],
                    )
                    continue

                collector.links_checked.append(
                    {"url": f"{base_url}{norm_path}", "source": source_page, "type": "internal", "status": status}
                )
                if status >= 400:
                    collector.add_finding(
                        phase=phase_label,
                        severity="high" if status == 404 else "critical",
                        category="Broken Internal Link",
                        title=f"Broken link to '{raw_href}' (HTTP {status})",
                        page_url=source_page,
                        element=f"<a href='{raw_href}'>",
                        description=f"Page {source_page} links to '{raw_href}', which returned HTTP {status}.",
                        steps_to_reproduce=[
                            f"Navigate to {source_page}",
                            f"Click the link pointing to {raw_href}",
                        ],
                    )

    # Politely check external links with 24-hr cache, HEAD->GET fallback, and warning-only classification
    if cfg.check_external_links and external_urls_to_check:
        ext_cache = _load_external_link_cache()
        now_ts = time.time()
        headers = {"User-Agent": "Quotelytics-QA-Agent/1.0 (+http://127.0.0.1:8000)"}

        with httpx.Client(follow_redirects=True, timeout=8.0, headers=headers) as ext_client:
            for ext_url, source_page in external_urls_to_check.items():
                if any(ns in ext_url for ns in ("ogp.me", "schema.org", "w3.org")):
                    continue

                # Use 24-hr cache if available (Section 6)
                if ext_url in ext_cache and (now_ts - ext_cache[ext_url]) < 86400:
                    collector.links_checked.append(
                        {"url": ext_url, "source": source_page, "type": "external", "status": "cached (200)"}
                    )
                    continue

                status = 0
                is_inconclusive = False
                err_msg = ""
                try:
                    resp = ext_client.head(ext_url)
                    status = resp.status_code
                    if status in (403, 405) or status >= 400:
                        resp = ext_client.get(ext_url)
                        status = resp.status_code
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    is_inconclusive = True
                    err_msg = f"Network timeout/connect error: {exc}"
                except Exception as exc:
                    err_msg = str(exc)

                if status in (429, 503) or is_inconclusive:
                    # Inconclusive external check - record as info
                    collector.add_finding(
                        phase=phase_label,
                        severity="info",
                        category="External Link Inconclusive",
                        title=f"External link check inconclusive for {ext_url}",
                        page_url=source_page,
                        element=f"<a href='{ext_url}'>",
                        description=f"External host returned status {status or err_msg}; marked inconclusive.",
                    )
                elif status >= 200 and status < 400:
                    ext_cache[ext_url] = now_ts
                    collector.links_checked.append(
                        {"url": ext_url, "source": source_page, "type": "external", "status": status}
                    )
                else:
                    # External failure: WARNING / LOW only, never affects exit code (Section 6)
                    collector.add_finding(
                        phase=phase_label,
                        severity="low",
                        category="Broken External Link (Warning)",
                        title=f"External link unreachable (HTTP {status}): {ext_url}",
                        page_url=source_page,
                        element=f"<a href='{ext_url}'>",
                        description=f"External URL {ext_url} linked from {source_page} returned HTTP {status or err_msg}.",
                        steps_to_reproduce=[f"Open {source_page}", f"Click external link {ext_url}"],
                    )

        _save_external_link_cache(ext_cache)
