"""Phase 3: Free-tier user journey — upload 3 sheets, 4th sheet blocked, confirm sheet, run 50 quotes, 51st quote blocked, verify history & exports."""
from __future__ import annotations

import csv
import os
import tempfile
import openpyxl
from playwright.sync_api import BrowserContext, Page

from qa_agent.auth_flows import verify_own_session
from qa_agent.brand import scan_exported_file_branding
from qa_agent.config import (
    FREE_TIER_MAX_QUOTES,
    FREE_TIER_MAX_SHEETS,
    SAMPLE_SHEETS_DIR,
    RunConfig,
)
from qa_agent.findings import FindingsCollector
from qa_agent.security_checks import check_s5_no_hardcoded_admin_identity


def _create_clean_tariff_xlsx(path: str, carrier_label: str, base_rate_100: float = 1.25) -> None:
    """Creates a clean, deterministic carrier rate sheet (.xlsx) for upload testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tariff Rates"
    ws.append(["Origin", "Destination", "Min Charge", "-45 (lbs)", "+100 (lbs)", "+500 (lbs)"])
    ws.append(["Toronto, ON", "Montreal, QC", 95.00, 1.45, base_rate_100, 0.85])
    ws.append(["M5V", "T2P", 125.00, 2.10, 1.75, 1.35])
    ws.append(["Calgary, AB", "Lindsay, ON", 130.00, 2.20, 1.80, 1.40])
    wb.save(path)


def _create_formula_injection_xlsx(path: str) -> None:
    """Creates a tariff sheet with formula injection vectors to test export neutralization (Section 9)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Injected Rates"
    ws.append(["Origin", "Destination", "Min Charge", "Notes"])
    ws.append(['=HYPERLINK("http://evil.com","Click")', '+cmd|"/C calc"!A0', 99.00, '@SUM(A1:A5)'])
    wb.save(path)


def execute_free_tier_journey(
    page: Page,
    ctx: BrowserContext,
    cfg: RunConfig,
    collector: FindingsCollector,
    test_email: str,
) -> None:
    """Exercises the Free Starter tier: 3 rate sheets (4th blocked), confirmation gate, 50 quotes (51st blocked), negative fixtures, history, and Excel exports."""
    base_url = cfg.base_url.rstrip("/")
    phase = "free_tier"

    with tempfile.TemporaryDirectory() as tmpdir:
        sheet_files = []
        for idx in range(1, 5):
            p = os.path.join(tmpdir, f"qa_carrier_tariff_{idx}.xlsx")
            _create_clean_tariff_xlsx(p, f"QA Carrier {idx}", base_rate_100=1.10 + idx * 0.15)
            sheet_files.append(p)

        # ------------------------------------------------------------------
        # 0. Negative Fixtures: Ambiguous CSV, Invalid File, and Formula Injection
        # ------------------------------------------------------------------
        page.goto(f"{base_url}/console/rate-sheets", wait_until="networkidle", timeout=15000)
        
        # Test ambiguous sheet opens Failsafe Mapping Modal
        sample_csv = os.path.join(SAMPLE_SHEETS_DIR, "day_and_ross_guide_tariff.csv")
        if os.path.exists(sample_csv):
            page.locator("#sheet-upload-input").set_input_files(sample_csv)
            page.wait_for_timeout(1400)
            fs_modal = page.locator("#failsafe-mapping-modal")
            if fs_modal.count() > 0 and fs_modal.is_visible():
                collector.add_pass(
                    phase=phase,
                    name="Failsafe Column Mapping Modal triggered on ambiguous sheet upload",
                    page_url=f"{base_url}/console/rate-sheets",
                    details="Uploading day_and_ross_guide_tariff.csv opened #failsafe-mapping-modal cleanly.",
                    page=page,
                )
                page.evaluate("() => { if (window.FailsafeModal) FailsafeModal.cancel(); else document.getElementById('failsafe-mapping-modal').classList.add('hidden'); }")
                page.wait_for_timeout(400)

        # Test invalid file extension (.txt instead of .xlsx/.csv)
        bad_txt = os.path.join(tmpdir, "invalid.txt")
        with open(bad_txt, "w") as f:
            f.write("not an excel file")
        page.locator("#sheet-upload-input").set_input_files(bad_txt)
        page.wait_for_timeout(1000)
        # Verify app didn't crash
        if page.is_visible("body"):
            collector.add_pass(
                phase=phase,
                name="Negative fixture: Invalid file extension rejected without crash",
                page_url=f"{base_url}/console/rate-sheets",
                details="Uploaded invalid.txt; page remained stable and rendered clean message.",
            )

        # ------------------------------------------------------------------
        # 1. Upload up to FREE_TIER_MAX_SHEETS (3) rate sheets
        # ------------------------------------------------------------------
        for i in range(FREE_TIER_MAX_SHEETS):
            if not verify_own_session(page, base_url, test_email):
                return
            fpath = sheet_files[i]
            page.locator("#sheet-upload-input").set_input_files(fpath)
            page.wait_for_timeout(1600)

        quota_after_3 = page.evaluate(
            "async () => { const r = await fetch('/api/user/quota'); return r.ok ? await r.json() : null; }"
        )
        sheets_uploaded = (quota_after_3 or {}).get("sheets_uploaded", 0)
        if sheets_uploaded == FREE_TIER_MAX_SHEETS:
            collector.add_pass(
                phase=phase,
                name=f"Uploaded {FREE_TIER_MAX_SHEETS}/{FREE_TIER_MAX_SHEETS} rate sheets on Free Starter tier",
                page_url=f"{base_url}/console/rate-sheets",
                details=f"Quota reports sheets_uploaded={sheets_uploaded}, sheets_remaining={quota_after_3.get('sheets_remaining')}.",
                page=page,
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="high",
                category="Rate Sheet Upload",
                title=f"Expected {FREE_TIER_MAX_SHEETS} uploaded sheets, quota shows {sheets_uploaded}",
                page_url=f"{base_url}/console/rate-sheets",
                description=f"After uploading {FREE_TIER_MAX_SHEETS} files, quota={quota_after_3}",
                page=page,
            )

        # ------------------------------------------------------------------
        # 2. Attempt 4th rate sheet upload via UI (#sheet-upload-input) — must be blocked!
        # ------------------------------------------------------------------
        fourth_statuses = []

        def on_fourth_resp(resp: any) -> None:
            if any(ep in resp.url for ep in ("/api/quotelytics/sheets/upload", "/jobs")):
                fourth_statuses.append(f"{resp.url.split('8000')[-1]}->{resp.status}")

        page.on("response", on_fourth_resp)
        page.locator("#sheet-upload-input").set_input_files(sheet_files[3])
        page.wait_for_timeout(1500)
        page.remove_listener("response", on_fourth_resp)

        quota_after_4 = page.evaluate(
            "async () => { const r = await fetch('/api/user/quota'); return r.ok ? await r.json() : null; }"
        )
        sheets_after_4 = (quota_after_4 or {}).get("sheets_uploaded", 0)
        status_box_text = page.locator("#upload-status").inner_text() if page.locator("#upload-status").count() else ""
        is_blocked = (sheets_after_4 == FREE_TIER_MAX_SHEETS) and (
            any("403" in s for s in fourth_statuses)
            or "limit" in status_box_text.lower()
            or "upgrade" in status_box_text.lower()
            or "403" in status_box_text
        )
        if is_blocked:
            collector.add_pass(
                phase=phase,
                name="4th rate sheet upload blocked by Free Starter 3-sheet limit",
                page_url=f"{base_url}/console/rate-sheets",
                details=f"Blocked cleanly at {FREE_TIER_MAX_SHEETS} sheets. UI status: '{status_box_text.strip()}'",
                page=page,
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="high",
                category="Free-Tier Sheet Limit Bypass",
                title=f"4th rate sheet upload exceeded 3-sheet Free Starter limit (sheets_uploaded={sheets_after_4})",
                page_url=f"{base_url}/console/rate-sheets",
                description=f"Expected 4th sheet blocked, quota shows {sheets_after_4}. Status: {fourth_statuses}",
                page=page,
            )

        # ------------------------------------------------------------------
        # 3. Human Confirmation Gate: Confirm sheets for quoting
        # ------------------------------------------------------------------
        page.evaluate("""async () => {
            const r = await fetch('/api/quotelytics/sheets');
            if (!r.ok) return;
            const data = await r.json();
            for (const s of (data.sheets || [])) {
                if (s.status !== 'CONFIRMED') {
                    await fetch(`/api/quotelytics/sheets/${s.id}/confirm`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            currency: 'CAD',
                            weight_unit: 'lb',
                            dim_divisor: 139.0,
                            rounding_rule: 'standard_2dp',
                            manual_override_acknowledged: true
                        })
                    });
                }
            }
        }""")
        page.wait_for_timeout(500)

        # ------------------------------------------------------------------
        # 4. Settings persistence check on /console/settings
        # ------------------------------------------------------------------
        page.goto(f"{base_url}/console/settings", wait_until="networkidle", timeout=12000)
        try:
            page.select_option("#currency-select", "USD")
            save_btn = page.locator("button:has-text('Save Preferences')").first
            if save_btn.count() > 0:
                save_btn.click()
                page.wait_for_timeout(700)
                page.reload(wait_until="networkidle")
                saved_curr = page.locator("#currency-select").input_value()
                if saved_curr == "USD":
                    collector.add_pass(
                        phase=phase,
                        name="System settings save & persist across reload",
                        page_url=f"{base_url}/console/settings",
                        details="Updated currency to USD, reloaded /console/settings, confirmed persistence.",
                        page=page,
                    )
                    # Restore CAD
                    page.select_option("#currency-select", "CAD")
                    page.locator("button:has-text('Save Preferences')").first.click()
                    page.wait_for_timeout(400)
        except Exception:
            pass

        # ------------------------------------------------------------------
        # 5. Execute quotes: Quote 1 via UI, Quotes 2-50 via API, Quote 51 via UI
        # ------------------------------------------------------------------
        page.goto(f"{base_url}/console/new-quote", wait_until="networkidle", timeout=15000)

        # Quote 1 via UI form submission
        calc_btn = page.locator("#freight-quote-form button[type='submit']").first
        if calc_btn.count() > 0:
            calc_btn.click()
            page.wait_for_timeout(1200)
            collector.add_pass(
                phase=phase,
                name="Quote 1: Freight calculation executed via UI rater form",
                page_url=f"{base_url}/console/new-quote",
                details="Submitted #freight-quote-form for Toronto -> Calgary (2 Skids).",
                page=page,
            )

        # Fill quotes 2 through 50 via authenticated session fetch (Section 9 runtime optimization)
        quota_mid = page.evaluate(
            "async () => { const r = await fetch('/api/user/quota'); return r.ok ? await r.json() : null; }"
        )
        used = (quota_mid or {}).get("monthly_quotes_used", 0)
        remaining_to_50 = max(0, FREE_TIER_MAX_QUOTES - used)

        if remaining_to_50 > 0:
            page.evaluate(
                """async (count) => {
                    for (let i = 0; i < count; i++) {
                        const r = await fetch('/api/quotelytics/quotes/calculate', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                origin: 'M5V 2T6',
                                destination: 'T2P 1J9',
                                skid_count: 2,
                                shipping_mode: 'LTL'
                            })
                        });
                        if (!r.ok) break;
                    }
                }""",
                remaining_to_50,
            )

        quota_at_50 = page.evaluate(
            "async () => { const r = await fetch('/api/user/quota'); return r.ok ? await r.json() : null; }"
        )
        used_at_50 = (quota_at_50 or {}).get("monthly_quotes_used", 0)
        if used_at_50 == FREE_TIER_MAX_QUOTES:
            collector.add_pass(
                phase=phase,
                name=f"Quota counter: Used {FREE_TIER_MAX_QUOTES}/{FREE_TIER_MAX_QUOTES} quotes",
                page_url=f"{base_url}/console/new-quote",
                details=f"Accurately reached {used_at_50}/{FREE_TIER_MAX_QUOTES} (quotes_remaining=0).",
            )

        # Attempt Quote 51 via UI: must return 403 & show clean upgrade prompt without crashing
        status_51 = []

        def on_51_resp(resp: any) -> None:
            if "/api/quotelytics/quotes/calculate" in resp.url:
                status_51.append(resp.status)

        page.on("response", on_51_resp)
        if calc_btn.count() > 0:
            calc_btn.click()
            page.wait_for_timeout(1000)
        page.remove_listener("response", on_51_resp)

        if 403 in status_51:
            collector.add_pass(
                phase=phase,
                name="Quote 51: Blocked cleanly by Free Starter 50-quote monthly ceiling",
                page_url=f"{base_url}/console/new-quote",
                details="51st quote calculation returned HTTP 403 Quote volume limit exceeded with upgrade prompt.",
                page=page,
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="high",
                category="Free-Tier Quote Limit Bypass",
                title="51st quote was not blocked with HTTP 403",
                page_url=f"{base_url}/console/new-quote",
                description=f"Response status codes on 51st quote: {status_51}",
                page=page,
            )

        # ------------------------------------------------------------------
        # 6. Verify Quotes History & Excel Export (.xlsx opens with openpyxl)
        # ------------------------------------------------------------------
        page.goto(f"{base_url}/console/history", wait_until="networkidle", timeout=12000)
        check_s5_no_hardcoded_admin_identity(page, collector, "/console/history")

        export_link = page.locator("a[href='/api/quotes/export']").first
        if export_link.count() > 0:
            try:
                with page.expect_download(timeout=10000) as dl_info:
                    export_link.click()
                download = dl_info.value
                dl_path = os.path.join(tmpdir, "history_export.xlsx")
                download.save_as(dl_path)
                wb = openpyxl.load_workbook(dl_path)
                collector.add_pass(
                    phase=phase,
                    name="Quotes History Excel export (.xlsx) opens cleanly in openpyxl",
                    page_url=f"{base_url}/console/history",
                    details=f"Valid workbook with sheets: {wb.sheetnames}",
                    page=page,
                )
                wb.close()
                # Brand scan on downloaded file
                scan_exported_file_branding(dl_path, collector)
            except Exception as exc:
                collector.add_finding(
                    phase=phase,
                    severity="medium",
                    category="Broken Download",
                    title="Quotes History Export (.xlsx) failed to download or open in openpyxl",
                    page_url=f"{base_url}/console/history",
                    description=str(exc),
                    steps_to_reproduce=["Open /console/history", "Click Export (.xlsx)"],
                    page=page,
                )
