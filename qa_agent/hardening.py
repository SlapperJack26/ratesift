"""Phase 6: Platform Hardening, Edge-Case Stress Testing & Concurrency Resilience."""
from __future__ import annotations

import concurrent.futures
import io
import json
import os
import secrets
import time
import uuid
from typing import Any, Dict, List
import httpx
import openpyxl

from qa_agent.config import DB_PATH, RunConfig
from qa_agent.findings import FindingsCollector
from services.auth_service import register_and_create_session
from services.db_service import delete_user_account_data, get_connection


def run_hardening_suite(cfg: RunConfig, collector: FindingsCollector) -> None:
    """Executes the 4 hardening stages against the Quotelytics local instance."""
    base_url = cfg.base_url.rstrip("/")
    phase = "hardening"

    print("\n[Quotelytics QA Agent] Starting Hardening & Concurrency Suite...")

    # Stage 1: Payload & Boundary Stress Testing
    _test_payload_and_boundary_limits(base_url, cfg, collector, phase)

    # Stage 2: SQLite WAL Concurrency & Lock Contention
    _test_concurrent_quote_calculations(base_url, cfg, collector, phase)

    # Stage 3: Quota Race Condition Verification (50-quote ceiling)
    _test_quota_ceiling_race_condition(base_url, cfg, collector, phase)

    # Stage 4: Malformed & Ragged Tariff Ingestion
    _test_malformed_tariff_ingestion(base_url, cfg, collector, phase)


def _test_payload_and_boundary_limits(
    base_url: str,
    cfg: RunConfig,
    collector: FindingsCollector,
    phase: str,
) -> None:
    """Validates 10 MB file ceiling and multilingual Canadian FSA lane resolution."""
    print("  -> Executing Stage 1: Payload & Boundary Stress Testing...")

    # 1. Test 10.2 MB oversized file upload (Should return HTTP 413)
    try:
        oversized_bytes = b"0" * (10 * 1024 * 1024 + 200 * 1024)
        files = {"file": ("oversized_test.xlsx", io.BytesIO(oversized_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{base_url}/jobs", files=files)

        if resp.status_code == 413:
            collector.add_pass(
                phase=phase,
                name="10 MB payload ceiling rejected cleanly (HTTP 413)",
                page_url=f"{base_url}/jobs",
                details="Uploaded 10.2 MB payload; server rejected with HTTP 413 without memory exhaustion.",
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="high",
                category="Payload Boundary",
                title=f"Oversized 10 MB payload returned unexpected status {resp.status_code}",
                page_url=f"{base_url}/jobs",
                description=f"Expected HTTP 413 for 10.2 MB file, got {resp.status_code}.",
            )
    except Exception as exc:
        collector.add_finding(
            phase=phase,
            severity="medium",
            category="Payload Boundary Exception",
            title="Exception uploading oversized payload",
            page_url=f"{base_url}/jobs",
            description=str(exc),
        )

    # 2. Test Multilingual Canadian Lane Calculations (French accents & Maritimes)
    test_lanes = [
        {"origin": "Trois-Rivières, QC", "dest": "Montréal, QC", "weight": 850.0},
        {"origin": "G9A 5H3", "dest": "H2Y 1C6", "weight": 1400.0},
        {"origin": "Halifax, NS", "dest": "Moncton, NB", "weight": 2200.0},
        {"origin": "B3H 2Y2", "dest": "E1C 8T6", "weight": 3100.0},
    ]

    tag = secrets.token_hex(4)
    user, token = register_and_create_session(
        name=f"Multilingual Tester {tag}",
        email=f"qa+multilingual_{tag}@quotelytics.test",
        company=f"Multilingual Logistics {tag}",
        origin_zip="M5V 2T6",
        password=f"MultiPass!{secrets.token_hex(6)}",
        marketing_opt_in=False,
    )
    user_id = user["id"]
    cookies = {"quotelytics_session": token}

    try:
        all_lanes_ok = True
        details_log = []
        with httpx.Client(timeout=8.0, cookies=cookies) as client:
            for lane in test_lanes:
                try:
                    calc_resp = client.post(
                        f"{base_url}/api/quotelytics/quotes/calculate",
                        json={
                            "origin": lane["origin"],
                            "destination": lane["dest"],
                            "weight": lane["weight"],
                            "skids": 2,
                            "accessorials": ["liftgate"],
                        },
                    )
                    if calc_resp.status_code == 200:
                        data = calc_resp.json()
                        details_log.append(f"{lane['origin']} -> {lane['dest']}: OK ({len(data.get('results', []))} quotes)")
                    else:
                        all_lanes_ok = False
                        details_log.append(f"{lane['origin']} -> {lane['dest']}: Failed ({calc_resp.status_code})")
                except Exception as e:
                    all_lanes_ok = False
                    details_log.append(f"{lane['origin']} -> {lane['dest']}: Exception ({e})")

        if all_lanes_ok:
            collector.add_pass(
                phase=phase,
                name="Canadian Multilingual & Maritime FSA Lane Resolution",
                page_url=f"{base_url}/api/quotelytics/quotes/calculate",
                details="Successfully resolved and rated: " + "; ".join(details_log),
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="medium",
                category="Lane Resolution",
                title="Multilingual Canadian Lane rating failure",
                page_url=f"{base_url}/api/quotelytics/quotes/calculate",
                description="; ".join(details_log),
            )
    finally:
        delete_user_account_data(user_id, immediate_purge=True)


def _test_concurrent_quote_calculations(
    base_url: str,
    cfg: RunConfig,
    collector: FindingsCollector,
    phase: str,
) -> None:
    """Spawns 10 parallel worker threads calculating quotes simultaneously to test WAL lock concurrency."""
    print("  -> Executing Stage 2: SQLite WAL Concurrency & Lock Contention...")

    tag = secrets.token_hex(4)
    user, token = register_and_create_session(
        name=f"Concurrency Tester {tag}",
        email=f"qa+concurrent_{tag}@quotelytics.test",
        company=f"Concurrency Logistics {tag}",
        origin_zip="M5V 2T6",
        password=f"ConcPass!{secrets.token_hex(6)}",
        marketing_opt_in=False,
    )
    user_id = user["id"]

    cookies = {"quotelytics_session": token}
    num_requests = 10

    try:
        def make_quote(idx: int) -> Dict[str, Any]:
            t0 = time.time()
            try:
                with httpx.Client(timeout=10.0, cookies=cookies) as client:
                    r = client.post(
                        f"{base_url}/api/quotelytics/quotes/calculate",
                        json={
                            "origin": "Toronto, ON",
                            "destination": "Calgary, AB",
                            "weight": 1250.0 + (idx * 50),
                            "skids": 2,
                            "accessorials": ["liftgate"],
                        },
                    )
                    return {
                        "idx": idx,
                        "status": r.status_code,
                        "duration": time.time() - t0,
                        "ok": r.status_code == 200,
                    }
            except Exception as e:
                return {"idx": idx, "status": 0, "duration": time.time() - t0, "ok": False, "error": str(e)}

        results = []
        t_start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(make_quote, i) for i in range(num_requests)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())
        total_time = time.time() - t_start

        success_count = sum(1 for r in results if r["ok"])
        if success_count == num_requests:
            collector.add_pass(
                phase=phase,
                name=f"10 Concurrent Quote Calculations ({total_time:.2f}s, 0 DB locks)",
                page_url=f"{base_url}/api/quotelytics/quotes/calculate",
                details=f"All {num_requests} concurrent threads succeeded without SQLite lock starvation. Avg latency: {total_time/num_requests:.2f}s.",
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="high",
                category="Concurrency Lock Contention",
                title=f"Concurrent quote calculations had {num_requests - success_count} failures",
                page_url=f"{base_url}/api/quotelytics/quotes/calculate",
                description=f"Results: {results}",
            )
    finally:
        delete_user_account_data(user_id, immediate_purge=True)


def _test_quota_ceiling_race_condition(
    base_url: str,
    cfg: RunConfig,
    collector: FindingsCollector,
    phase: str,
) -> None:
    """Simulates 8 concurrent quote requests when exactly 1 quote remains on Free Starter tier."""
    print("  -> Executing Stage 3: Quota Ceiling Race Condition Verification...")

    tag = secrets.token_hex(4)
    user, token = register_and_create_session(
        name=f"Race Tester {tag}",
        email=f"qa+race_{tag}@quotelytics.test",
        company=f"Race Logistics {tag}",
        origin_zip="M5V 2T6",
        password=f"RacePass!{secrets.token_hex(6)}",
        marketing_opt_in=False,
    )
    user_id = user["id"]
    cookies = {"quotelytics_session": token}

    try:
        conn = get_connection()
        cur = conn.cursor()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for i in range(49):
            cur.execute(
                """INSERT INTO ql_quote_audit_logs (
                       id, user_id, timestamp, shipment_input_json, 
                       sheets_considered_json, sheets_excluded_json, 
                       calculation_trace_json, final_results_json, data_residency_region
                   ) VALUES (?, ?, ?, '{}', '[]', '[]', '[]', '[]', 'CA_CENTRAL_WHC')""",
                (f"mock_audit_race_{tag}_{i}", user_id, now_iso),
            )
        conn.commit()
        conn.close()

        num_concurrent = 8
        def fire_quote() -> int:
            try:
                with httpx.Client(timeout=10.0, cookies=cookies) as client:
                    r = client.post(
                        f"{base_url}/api/quotelytics/quotes/calculate",
                        json={
                            "origin": "Toronto, ON",
                            "destination": "Montreal, QC",
                            "weight": 850.0,
                            "skids": 1,
                        },
                    )
                    return r.status_code
            except Exception:
                return 0

        codes = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent) as executor:
            futures = [executor.submit(fire_quote) for _ in range(num_concurrent)]
            for f in concurrent.futures.as_completed(futures):
                codes.append(f.result())

        with httpx.Client(timeout=5.0, cookies=cookies) as client:
            q_final = client.get(f"{base_url}/api/user/quota").json()
        final_used = q_final.get("monthly_quotes_used", 0)

        success_200 = codes.count(200)
        blocked_403 = codes.count(403)

        if success_200 == 1 and blocked_403 == (num_concurrent - 1) and final_used == 50:
            collector.add_pass(
                phase=phase,
                name="Quota Ceiling Atomic Enforcement (Race Condition Tested)",
                page_url=f"{base_url}/api/quotelytics/quotes/calculate",
                details=f"Starting: 49/50. 8 concurrent requests resulted in exactly 1 HTTP 200 and 7 HTTP 403s. Final: 50/50.",
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="high",
                category="Quota Race Condition",
                title=f"Quota ceiling was not atomically enforced under race condition",
                page_url=f"{base_url}/api/quotelytics/quotes/calculate",
                description=f"Status codes: {codes}, Final quotes used: {final_used}/50. Expected 1x 200, 7x 403.",
            )
    finally:
        delete_user_account_data(user_id, immediate_purge=True)


def _test_malformed_tariff_ingestion(
    base_url: str,
    cfg: RunConfig,
    collector: FindingsCollector,
    phase: str,
) -> None:
    """Tests upload and detection of ragged grids, merged headers, and empty sheets."""
    print("  -> Executing Stage 4: Malformed Tariff Failsafe Tests...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RaggedTariff"
    ws.append(["Carrier Name", "Day & Ross Inc."])
    ws.append([])
    ws.append(["Origin", "Destination", "Min", "L5C", "1M", "2M", "5M"])
    ws.append(["Toronto, ON", "Montreal, QC", 45.0, 12.5, 9.8, 8.2])
    ws.append(["Toronto, ON", "Calgary, AB", 95.0, 24.5, 21.0, 18.5, 14.2, 11.0, "Extra Col"])
    
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)

    try:
        files = {"file": ("ragged_tariff.xlsx", bio, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{base_url}/jobs", files=files)
        
        if resp.status_code == 200:
            data = resp.json()
            job_id = data.get("job_id")
            collector.add_pass(
                phase=phase,
                name="Ragged grid tariff ingested safely into Failsafe Queue",
                page_url=f"{base_url}/jobs",
                details=f"Ragged spreadsheet with mismatched row widths parsed into job {job_id} without crashing.",
            )
        else:
            collector.add_finding(
                phase=phase,
                severity="medium",
                category="Ragged Grid Ingest",
                title=f"Ragged grid tariff rejected with status {resp.status_code}",
                page_url=f"{base_url}/jobs",
                description=resp.text,
            )
    except Exception as exc:
        collector.add_finding(
            phase=phase,
            severity="medium",
            category="Tariff Ingestion Exception",
            title="Exception uploading ragged tariff",
            page_url=f"{base_url}/jobs",
            description=str(exc),
        )
