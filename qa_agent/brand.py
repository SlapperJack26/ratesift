"""Phase 1: Brand consistency scanner for legacy RateSift & ShipFlow references."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Set
import openpyxl
from playwright.sync_api import Page

from qa_agent.config import ALLOWLISTS_DIR, PROJECT_ROOT
from qa_agent.findings import FindingsCollector, normalize_page_path

LEGACY_BRAND_PATTERNS = [
    re.compile(r"\bratesift\b", re.IGNORECASE),
    re.compile(r"\bshipflow\b", re.IGNORECASE),
]


def load_brand_allowlist() -> List[Dict[str, str]]:
    """Loads intentional legacy brand mentions (e.g. historical legal notices in privacy policy)."""
    al_path = os.path.join(ALLOWLISTS_DIR, "brand_allowlist.json")
    if os.path.exists(al_path):
        try:
            with open(al_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return data.get("intentional_brand_mentions", [])
        except Exception:
            pass
    return []


def is_brand_mention_allowlisted(page_url: str, text_snippet: str, allowlist: List[Dict[str, str]]) -> bool:
    norm_page = normalize_page_path(page_url)
    for entry in allowlist:
        if entry.get("page") == norm_page:
            exact = entry.get("exact_string", "")
            if exact and exact.lower() in text_snippet.lower():
                return True
    return False


def scan_page_for_brand_leaks(page: Page, collector: FindingsCollector, phase_label: str = "brand") -> None:
    """
    Scans a rendered page's visible text, titles, meta tags, alt/aria attributes,
    and inline scripts for unintended legacy branding (RateSift / ShipFlow).
    """
    allowlist = load_brand_allowlist()
    url = page.url

    # 1. Page Title & Meta Tags
    meta_info = page.evaluate("""() => {
        const metas = Array.from(document.querySelectorAll('meta')).map(m => ({
            name: m.getAttribute('name') || m.getAttribute('property') || '',
            content: m.getAttribute('content') || ''
        }));
        return {
            title: document.title || '',
            metas
        };
    }""")

    title_text = meta_info.get("title", "")
    for pat in LEGACY_BRAND_PATTERNS:
        m = pat.search(title_text)
        if m and not is_brand_mention_allowlisted(url, title_text, allowlist):
            collector.add_finding(
                phase=phase_label,
                severity="medium",
                category="Brand Consistency",
                title=f"Legacy brand '{m.group(0)}' found in <title> on {normalize_page_path(url)}",
                page_url=url,
                description=f"Page <title> contains legacy branding '{m.group(0)}': \"{title_text}\"",
                element="<title>",
                page=page,
            )

    for meta in meta_info.get("metas", []):
        content = meta.get("content", "")
        name = meta.get("name", "")
        for pat in LEGACY_BRAND_PATTERNS:
            m = pat.search(content)
            if m and not is_brand_mention_allowlisted(url, content, allowlist):
                collector.add_finding(
                    phase=phase_label,
                    severity="low",
                    category="Brand Consistency",
                    title=f"Legacy brand '{m.group(0)}' found in meta '{name}'",
                    page_url=url,
                    description=f"Meta tag [{name}] contains legacy brand name: \"{content}\"",
                    element=f"meta[{name}]",
                    page=page,
                )

    # 2. Visible text, tooltips, placeholders, and aria-labels
    dom_findings = page.evaluate("""() => {
        const results = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
        let node;
        while (node = walker.nextNode()) {
            const tag = node.tagName.toLowerCase();
            if (['script', 'style', 'noscript', 'svg'].includes(tag)) continue;
            
            // Check placeholders, alt, title, aria-labels
            const attrs = ['placeholder', 'alt', 'title', 'aria-label'];
            for (const a of attrs) {
                const val = node.getAttribute(a);
                if (val && (val.toLowerCase().includes('ratesift') || val.toLowerCase().includes('shipflow'))) {
                    results.push({
                        type: 'attribute',
                        attr: a,
                        val: val.slice(0, 100),
                        selector: tag + (node.id ? '#' + node.id : '')
                    });
                }
            }
        }
        return results;
    }""")

    for df in dom_findings:
        val = df["val"]
        if not is_brand_mention_allowlisted(url, val, allowlist):
            collector.add_finding(
                phase=phase_label,
                severity="medium",
                category="Brand Consistency",
                title=f"Legacy brand string in {df['attr']} attribute on {normalize_page_path(url)}",
                page_url=url,
                description=f"Element {df['selector']} attribute {df['attr']}=\"{val}\"",
                element=df["selector"],
                page=page,
            )

    # 3. Visible body text
    try:
        body_text = page.inner_text("body")
        for pat in LEGACY_BRAND_PATTERNS:
            for match in pat.finditer(body_text):
                start = max(0, match.start() - 30)
                end = min(len(body_text), match.end() + 30)
                snippet = body_text[start:end].replace("\n", " ")
                if not is_brand_mention_allowlisted(url, snippet, allowlist):
                    collector.add_finding(
                        phase=phase_label,
                        severity="medium",
                        category="Brand Consistency",
                        title=f"Legacy brand '{match.group(0)}' visible on {normalize_page_path(url)}",
                        page_url=url,
                        description=f"Found visible legacy text: \"...{snippet}...\"",
                        element="body",
                        page=page,
                    )
                    break
    except Exception:
        pass


def scan_exported_file_branding(file_path: str, collector: FindingsCollector) -> None:
    """Scans downloaded Excel or CSV export files for legacy brand names in metadata, sheet names, or headers."""
    if not os.path.exists(file_path):
        return

    fname = os.path.basename(file_path).lower()
    for pat in LEGACY_BRAND_PATTERNS:
        m = pat.search(fname)
        if m:
            collector.add_finding(
                phase="brand",
                severity="medium",
                category="Brand Consistency",
                title=f"Exported filename contains legacy brand '{m.group(0)}'",
                page_url="/console/history",
                description=f"Exported file named '{fname}' retains legacy platform branding.",
                element=fname,
            )

    if file_path.endswith(".xlsx"):
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            # 1. Sheet names
            for sname in wb.sheetnames:
                for pat in LEGACY_BRAND_PATTERNS:
                    m = pat.search(sname)
                    if m:
                        collector.add_finding(
                            phase="brand",
                            severity="medium",
                            category="Brand Consistency",
                            title=f"Exported Excel sheet name contains legacy brand '{m.group(0)}'",
                            page_url="/console/history",
                            description=f"Excel workbook contains sheet titled '{sname}'.",
                            element=sname,
                        )
            # 2. Document properties (Title, Subject, Creator, Company)
            props = wb.properties
            prop_values = [
                props.title or "",
                props.subject or "",
                props.creator or "",
                props.company or "",
            ]
            for prop_val in prop_values:
                for pat in LEGACY_BRAND_PATTERNS:
                    m = pat.search(prop_val)
                    if m:
                        collector.add_finding(
                            phase="brand",
                            severity="low",
                            category="Brand Consistency",
                            title=f"Exported Excel document properties contain '{m.group(0)}'",
                            page_url="/console/history",
                            description=f"Document metadata property contains: \"{prop_val}\"",
                            element="xlsx_properties",
                        )
            wb.close()
        except Exception:
            pass
