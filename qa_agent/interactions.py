"""Phase 4: Interactive button, tab, dropdown, and modal tester with 5-signal dead-click detection."""
from __future__ import annotations

import json
import os
from typing import Any, List
from playwright.sync_api import BrowserContext, Page

from qa_agent.config import ALLOWLISTS_DIR, DESTRUCTIVE_ACTIONS_REGISTRY, RunConfig
from qa_agent.findings import FindingsCollector


def _load_tracking_allowlist() -> List[str]:
    p = os.path.join(ALLOWLISTS_DIR, "tracking_allowlist.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh).get("tracking_request_patterns", [])
        except Exception:
            pass
    return []


def _is_destructive(label: str, onclick: str, href: str) -> bool:
    combined = f"{label} {onclick} {href}".lower()
    for pat in DESTRUCTIVE_ACTIONS_REGISTRY:
        if pat in combined:
            return True
    return False


def test_buttons_on_routes(
    context: BrowserContext,
    cfg: RunConfig,
    collector: FindingsCollector,
    routes: List[str],
    phase_label: str = "interactions",
) -> None:
    """Visits each route and exercises visible controls using a 5-signal reaction detector (Section 10)."""
    base_url = cfg.base_url.rstrip("/")
    tracking_patterns = _load_tracking_allowlist()
    page: Page = context.new_page()

    dialog_messages: List[str] = []

    def on_dialog(dialog: Any) -> None:
        dialog_messages.append(dialog.message)
        try:
            dialog.dismiss()
        except Exception:
            pass

    page.on("dialog", on_dialog)

    for rel_path in routes:
        if rel_path == "/docs":
            continue
        full_url = f"{base_url}{rel_path}"
        try:
            page.goto(full_url, wait_until="networkidle", timeout=15000)
        except Exception:
            continue

        try:
            controls = page.evaluate(
                """() => {
                    const els = Array.from(document.querySelectorAll('button, [role="button"], a[onclick]'));
                    return els.map((el, idx) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        const visible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                        el.setAttribute('data-qa-idx', String(idx));
                        return {
                            idx,
                            tag: el.tagName.toLowerCase(),
                            type: el.getAttribute('type') || '',
                            id: el.id || '',
                            label: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().replace(/\\s+/g, ' ').slice(0, 70),
                            onclick: el.getAttribute('onclick') || '',
                            href: el.getAttribute('href') || '',
                            disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                            visible,
                            ariaHaspopup: el.getAttribute('aria-haspopup') || '',
                            ariaExpanded: el.getAttribute('aria-expanded') || '',
                            ariaSelected: el.getAttribute('aria-selected') || ''
                        };
                    }).filter(c => c.visible);
                }"""
            )
        except Exception:
            controls = []

        for ctrl in controls:
            label = ctrl["label"] or f"<{ctrl['tag']} id='{ctrl['id']}'>"
            onclick = ctrl["onclick"]
            href = ctrl["href"]

            if ctrl["disabled"]:
                collector.buttons_tested.append(
                    {"page": rel_path, "label": label, "status": "SKIPPED", "outcome": "Disabled state"}
                )
                continue

            if _is_destructive(label, onclick, href):
                collector.buttons_tested.append(
                    {"page": rel_path, "label": label, "status": "SKIPPED (DESTRUCTIVE REGISTRY)", "outcome": "On destructive action registry"}
                )
                continue

            if "click()" in onclick and ("input" in onclick or "file" in onclick or "upload" in onclick.lower()):
                collector.buttons_tested.append(
                    {"page": rel_path, "label": label, "status": "DEFERRED", "outcome": "File upload trigger"}
                )
                continue

            if not page.url.startswith(full_url):
                try:
                    page.goto(full_url, wait_until="networkidle", timeout=12000)
                except Exception:
                    break

            js_errors: List[str] = []
            net_requests: List[str] = []
            dialog_messages.clear()

            def on_pageerror(exc: Any) -> None:
                js_errors.append(str(exc))

            def on_request(req: Any) -> None:
                net_requests.append(req.url)

            page.on("pageerror", on_pageerror)
            page.on("request", on_request)

            try:
                # 5-Signal Reaction Monitor setup (Section 10)
                page.evaluate("""() => {
                    window.__qa_mutations = 0;
                    if (window.__qa_observer) window.__qa_observer.disconnect();
                    window.__qa_observer = new MutationObserver(() => { window.__qa_mutations++; });
                    window.__qa_observer.observe(document.body, { childList: true, subtree: true, attributes: true });
                }""")

                before_url = page.url
                selector = f"#{ctrl['id']}" if ctrl["id"] else f"[data-qa-idx='{ctrl['idx']}']"
                loc = page.locator(selector).first
                if loc.count() == 0 or not loc.is_visible():
                    page.evaluate(
                        "() => Array.from(document.querySelectorAll('button, [role=\"button\"], a[onclick]')).forEach((el, i) => el.setAttribute('data-qa-idx', String(i)))"
                    )
                    loc = page.locator(selector).first

                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=4000)
                    page.wait_for_timeout(400)

                    reaction_state = page.evaluate("""() => {
                        const mutations = window.__qa_mutations || 0;
                        if (window.__qa_observer) window.__qa_observer.disconnect();
                        const activeModal = document.querySelector('[role="dialog"]:not(.hidden), [id*="modal"]:not(.hidden)');
                        return {
                            mutations,
                            modalVisible: !!activeModal,
                            activeElement: document.activeElement ? (document.activeElement.id || document.activeElement.tagName) : ''
                        };
                    }""")

                    after_url = page.url
                    url_changed = before_url != after_url
                    dom_mutated = reaction_state.get("mutations", 0) > 0
                    net_called = len(net_requests) > 0
                    modal_opened = reaction_state.get("modalVisible", False) or len(dialog_messages) > 0

                    reacted = url_changed or dom_mutated or net_called or modal_opened or ctrl["type"] == "submit"

                    # Check if only analytics tracking fired
                    only_analytics = False
                    if not (url_changed or dom_mutated or modal_opened) and net_called:
                        if all(any(tp in req for tp in tracking_patterns) for req in net_requests):
                            only_analytics = True

                    if js_errors:
                        collector.add_finding(
                            phase=phase_label,
                            severity="high",
                            category="Button JS Exception",
                            title=f"Clicking '{label}' on {rel_path} threw a JS error",
                            page_url=full_url,
                            element=label,
                            description=f"Click triggered uncaught JavaScript exception(s): {js_errors}",
                            steps_to_reproduce=[f"Open {full_url}", f"Click control '{label}'"],
                            page=page,
                        )
                        outcome = f"CRASH: {js_errors[0][:60]}"
                    elif not reacted:
                        collector.add_finding(
                            phase=phase_label,
                            severity="low",
                            category="Dead Button",
                            title=f"Dead button: '{label}' on {rel_path} produced zero reactions",
                            page_url=full_url,
                            element=label,
                            description=f"Click produced 0 DOM mutations, 0 network calls, 0 modal events, and no URL change within reaction window.",
                            steps_to_reproduce=[f"Open {full_url}", f"Click '{label}'", "Observe no response"],
                            page=page,
                        )
                        outcome = "DEAD (0 signals)"
                    elif only_analytics:
                        outcome = "REACTED (analytics only)"
                    else:
                        outcome = "REACTED"

                    collector.buttons_tested.append(
                        {
                            "page": rel_path,
                            "label": label,
                            "status": "PASSED" if reacted and not js_errors else "FAILED",
                            "outcome": outcome,
                        }
                    )

            except Exception:
                pass
            finally:
                page.remove_listener("pageerror", on_pageerror)
                page.remove_listener("request", on_request)

    page.close()
