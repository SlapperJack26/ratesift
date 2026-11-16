"""HTML & JSON report generator with embedded screenshots, baseline diffing, and CI exit codes."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from qa_agent.findings import FindingsCollector


def generate_reports(collector: FindingsCollector, fail_on_medium: bool = False) -> str:
    """Writes findings.json, summary.json, and report.html inside collector.report_dir. Returns path to report.html."""
    collector.metadata["finished_at"] = datetime.now().isoformat(timespec="seconds")
    collector.apply_baseline_and_save()
    
    exit_code = collector.compute_ci_exit_code(fail_on_medium=fail_on_medium)
    collector.metadata["exit_code"] = exit_code
    counts = collector.summary_counts()

    # 1. Write summary.json
    summary_path = os.path.join(collector.report_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump({
            "metadata": collector.metadata,
            "counts": counts,
            "exit_code": exit_code,
        }, fh, indent=2)

    # 2. Write full findings.json
    json_path = os.path.join(collector.report_dir, "findings.json")
    payload = {
        "metadata": collector.metadata,
        "summary": counts,
        "findings": [asdict(f) for f in collector.findings],
        "fixed_since_last_run": collector.fixed_findings,
        "passes": [asdict(p) for p in collector.passes],
        "pages_crawled": collector.pages_crawled,
        "links_checked": collector.links_checked,
        "buttons_tested": collector.buttons_tested,
        "ai_findings": collector.ai_findings,
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    # 3. Render HTML Report
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=True)
    tmpl = env.get_template("report.html")

    html_content = tmpl.render(
        metadata=collector.metadata,
        summary=counts,
        findings=collector.findings,
        fixed_findings=collector.fixed_findings,
        passes=collector.passes,
        pages_crawled=collector.pages_crawled,
        links_checked=collector.links_checked,
        buttons_tested=collector.buttons_tested,
        ai_findings=collector.ai_findings,
    )

    html_path = os.path.join(collector.report_dir, "report.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)

    return html_path
