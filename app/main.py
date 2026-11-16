"""
FastAPI service: upload -> analyze -> (needs_mapping) -> confirm mapping -> ready -> process.
With Relational SQLite storage, atomic compare-and-set transitions, position-aware saved mappings,
tenant access isolation (Rule 14), and background TTL sweeping.

Run:  uvicorn app.main:app --reload
"""
import asyncio
from contextlib import asynccontextmanager
import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

import hashlib
import hmac
import json
import logging
import re
import threading
import time

logger = logging.getLogger("quotelytics.failsafe")

from app.config import ALLOWED_EXT, MAX_BYTES, PREVIEW_ROWS, MAX_DATA_COLS, MAX_DATA_ROWS
from app.detect import analyze, validate_mapping
from app.ingest import IngestionError, check_uncached_formulas, load_sheet_grid
from app.jobs import job_store
from app.mappings import (
    compute_fingerprint,
    delete_saved_mapping,
    find_near_match,
    find_saved_mapping,
    list_saved_mappings,
    record_audit_log,
    save_mapping,
)
from app.models import (
    FieldGuess,
    JobConflict,
    JobState,
    JobStatus,
    MappingRequest,
    Mode,
    SavedMappingResponse,
    DryRunRequest,
    CompoundLocationMapping,
)
from app.constants import (
    ERR_CODES,
    SEVERITY_BLOCKER,
    SEVERITY_WARNING,
)
from app.validation import (
    Finding,
    BLOCKER_MISSING_ORIGIN,
    BLOCKER_MISSING_DEST,
    BLOCKER_MISSING_CURRENCY,
    BLOCKER_COLUMN_COLLISION,
    BLOCKER_WEIGHT_MISSING_UNIT,
    BLOCKER_WEIGHT_NO_RATES,
    BLOCKER_SKID_INVALID_TIERS,
    BLOCKER_HEADER_AMBIGUITY,
    BLOCKER_MC_RATE_COLLISION,
    BLOCKER_RATE_COL_NON_NUMERIC,
    BLOCKER_ALL_LANES_NO_RATE,
    BLOCKER_UNPARSED_BREAK_LABEL,
    WARN_NON_MONOTONIC_CWT,
    WARN_ANOMALOUS_CROSSOVER,
    WARN_SUSPECTED_TRANSIT_DAYS,
    WARN_SUSPECTED_INTEGER_RATE,
    WARN_RATE_OUTLIER_STATISTICAL,
    WARN_PARCEL_CONTOUR_OVERRIDE,
    WARN_INVERTED_LANES,
    WARN_BREAK_EXCEEDS_CAPACITY,
    check_monotonicity,
    check_anomalous_crossover,
    check_transit_days_vs_integer_rates,
    check_statistical_outlier,
    check_parcel_dual_signal,
    check_inverted_lanes,
    parse_break_label,
    compute_layout_fingerprint,
)
from app.normalization import (
    build_normalized_rate_sheet_records,
    normalize_location_field,
)
from services.quotelytics_engine import calculate_quote_from_memory
from services.quotelytics_db_service import (
    get_system_setting,
    set_system_setting,
    insert_failsafe_audit_log,
    insert_failsafe_override_attribution,
    increment_failsafe_rejection,
    insert_failsafe_shadow_log,
    prune_failsafe_rejection_counters,
)

# ------------------------------------------------------------------------------
# Security, Caching & Rate Limiting Infrastructure
# ------------------------------------------------------------------------------

def verify_csrf(request: Request) -> None:
    if os.environ.get("ENABLE_FAILSAFE_CSRF", "false").lower() != "true":
        return
    cookie_token = request.cookies.get("quotelytics_csrf") or ""
    header_token = request.headers.get("X-CSRF-Token") or ""
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(403, "CSRF verification failed.")


class GridCache:
    def __init__(self, max_bytes: int = 50 * 1024 * 1024, ttl_seconds: float = 900.0):
        self.max_bytes = max_bytes
        self.ttl = ttl_seconds
        self.cache: Dict[str, Tuple[List[List[Any]], str, float, int]] = {}
        self.total_bytes = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Tuple[List[List[Any]], str]]:
        now = time.time()
        with self._lock:
            if key in self.cache:
                rows, ext, ts, size = self.cache[key]
                if now - ts <= self.ttl:
                    return rows, ext
                else:
                    self._remove_key(key)
        return None

    def set(self, key: str, rows: List[List[Any]], ext: str) -> None:
        now = time.time()
        row_count = len(rows)
        col_count = max((len(r) for r in rows), default=0)
        approx_bytes = row_count * col_count * 32 + 1024
        with self._lock:
            if key in self.cache:
                self._remove_key(key)
            while self.total_bytes + approx_bytes > self.max_bytes and self.cache:
                oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][2])
                self._remove_key(oldest_key)
            self.cache[key] = (rows, ext, now, approx_bytes)
            self.total_bytes += approx_bytes

    def _remove_key(self, key: str):
        if key in self.cache:
            _, _, _, size = self.cache.pop(key)
            self.total_bytes = max(0, self.total_bytes - size)

    def clear(self):
        with self._lock:
            self.cache.clear()
            self.total_bytes = 0


grid_cache = GridCache()


class TokenBucketRateLimiter:
    def __init__(self, rate_per_minute: float = 60.0, burst_capacity: float = 20.0, clock_fn=None):
        self.rate_per_second = rate_per_minute / 60.0
        self.capacity = burst_capacity
        self.buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()
        self.clock_fn = clock_fn or time.time

    def check_and_consume(self, user_id: str, tokens: float = 1.0) -> bool:
        now = self.clock_fn()
        with self._lock:
            current_tokens, last_update = self.buckets.get(user_id, (self.capacity, now))
            elapsed = max(0.0, now - last_update)
            current_tokens = min(self.capacity, current_tokens + (elapsed * self.rate_per_second))
            if current_tokens >= tokens:
                self.buckets[user_id] = (current_tokens - tokens, now)
                return True
            else:
                self.buckets[user_id] = (current_tokens, now)
                return False


rate_limiter = TokenBucketRateLimiter()

monotonic_clock = time.monotonic


def get_effective_failsafe_mode(tenant_id: Optional[str] = None) -> str:
    env_mode = os.environ.get("FAILSAFE_MODE", "off").lower()
    allowlist_str = os.environ.get("FAILSAFE_TENANT_ALLOWLIST", "")
    allowed = set()
    if allowlist_str:
        allowed.update([t.strip() for t in allowlist_str.split(",") if t.strip()])
    try:
        db_allowlist = get_system_setting("failsafe_tenant_allowlist", "")
        if db_allowlist:
            allowed.update(json.loads(db_allowlist))
    except Exception:
        pass
    if tenant_id and tenant_id in allowed:
        return "enforce"
    return env_mode


# Background TTL cleanup task
async def _periodic_ttl_worker():
    while True:
        try:
            job_store.cleanup_expired()
        except Exception as exc:
            logger.warning("Failsafe TTL cleanup failed: %s", exc)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: sweep orphaned temp files
    job_store.sweep_orphaned_files()
    worker_task = asyncio.create_task(_periodic_ttl_worker())
    yield
    worker_task.cancel()


from fastapi import APIRouter
router = APIRouter(tags=["Rate Sheet Failsafe"])
app = FastAPI(title="Quote sheet header failsafe", lifespan=lifespan)



def get_current_user_and_tenant(request: Request) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts (user_id, tenant_id) strictly from a validated session cookie or Authorization: Bearer token.
    Rule 14: Used for strict tenant scoping. Never trusts request headers such as X-User-Id or X-Tenant-Id.
    """
    try:
        from services.auth_service import validate_session_token
        token = request.cookies.get("quotelytics_session")
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
        if token:
            user = validate_session_token(token)
            if user:
                uid = str(user.get("id"))
                tid = uid
                return uid, tid
    except Exception:
        pass

    return None, None


def _check_job_access(job: Dict[str, Any], user_id: Optional[str], tenant_id: Optional[str]) -> None:
    """
    Rule 14: Verifies job ownership. Returns HTTP 404 (not 403) to avoid confirming existence.
    """
    job_user = job.get("user_id")
    job_tenant = job.get("tenant_id")
    # If job has owner, enforce matching
    if job_user and user_id and job_user != user_id:
        raise HTTPException(404, "Unknown job.")
    if job_tenant and tenant_id and job_tenant != tenant_id:
        raise HTTPException(404, "Unknown job.")
    if (job_user or job_tenant) and not (user_id or tenant_id):
        raise HTTPException(404, "Unknown job.")


def _state(job_id: str, job_dict: Optional[Dict[str, Any]] = None) -> JobState:
    j = job_dict or job_store.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job.")
    a = j.get("analysis", {})
    rows = j.get("rows", a.get("preview", []))

    guesses = [FieldGuess(**g) for g in a.get("guesses", [])]
    conflicts = [JobConflict(**c) for c in a.get("conflicts", [])]

    status_str = a.get("status", "needs_mapping")
    try:
        status_enum = JobStatus(status_str)
    except ValueError:
        status_enum = JobStatus.needs_mapping

    mode_val = a.get("mode")
    mode_enum = Mode(mode_val) if mode_val in ("weight", "skid") else None

    return JobState(
        job_id=job_id,
        status=status_enum,
        header_row=a.get("header_row"),
        sheet_name=a.get("sheet_name") or j.get("sheet_name"),
        mode=mode_enum,
        weight_unit=a.get("weight_unit") or (j.get("mapping") or {}).get("weight_unit"),
        guesses=guesses,
        conflicts=conflicts,
        unresolved=a.get("unresolved", []),
        suggestions=a.get("suggestions", {}),
        issues=a.get("issues", []),
        preview=[[("" if c is None else str(c)) for c in r] for r in rows[:PREVIEW_ROWS]],
        column_count=j.get("column_count") or max((len(r) for r in rows), default=0),
        mapping_source=j.get("mapping_source"),
        saved_mapping_suggestion=j.get("saved_mapping_suggestion"),
        expires_at=j.get("expires_at"),
    )


@router.post("/jobs", response_model=JobState)
async def upload(request: Request, file: UploadFile = File(...)):
    verify_csrf(request)
    user_id, tenant_id = get_current_user_and_tenant(request)

    # 1. Enforce Free-Tier 3-Sheet Limit & Fail-Closed Guard
    if user_id:
        from services.db_service import get_user_quota_info, log_bottleneck_event
        quota = get_user_quota_info(user_id)
        if quota is None:
            raise HTTPException(status_code=503, detail="Unable to verify subscription plan limits.")
        if not quota.get("can_upload_sheet", True):
            log_bottleneck_event(
                user_id=user_id,
                bottleneck_type="LIMIT_BLOCKED_SHEETS",
                attempted_action=f"Upload rate sheet: {file.filename}",
                current_usage=quota.get("sheets_uploaded", 3),
                max_limit=quota.get("max_sheets", 3),
                details={"filename": file.filename, "tier": quota.get("tier", "FREE")},
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "SHEET_LIMIT_REACHED",
                    "message": "Free Starter is limited to 3 rate sheets. Upgrade to Broker Pro or remove an existing sheet.",
                },
            )

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Upload .xlsx or .csv.")

    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (10 MB max).")

    job_id = uuid.uuid4().hex
    fd, path = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(data)

    try:
        rows, sheet_name = load_sheet_grid(path, ext)
        if ext == ".xlsx" and check_uncached_formulas(path, sheet_name):
            sample_data = [v for r in rows[1:10] for v in r if v is not None]
            if not sample_data:
                raise IngestionError(
                    "Spreadsheet contains formulas without cached calculated values. "
                    "Please open the file in Excel, save it, and re-upload."
                )

        from services.db_service import get_user_keyword_map
        custom_keywords = get_user_keyword_map(user_id)
        analysis = analyze(rows, sheet_name=sheet_name, custom_keywords=custom_keywords)
    except IngestionError as ie:
        if os.path.exists(path):
            os.remove(path)
        raise HTTPException(422, str(ie))
    except Exception as e:
        if os.path.exists(path):
            os.remove(path)
        raise HTTPException(422, f"Couldn't read that file. Is it a valid, unprotected .xlsx or .csv? Details: {e}")

    column_count = max((len(r) for r in rows), default=0)
    mapping = None
    mapping_source = None
    saved_suggestion = None

    hdr_idx = analysis.get("header_row")
    if tenant_id and hdr_idx is not None and 0 <= hdr_idx < len(rows):
        hdr_row_strings = [str(c or "").strip() for c in rows[hdr_idx]]
        fp = compute_fingerprint(hdr_row_strings, column_count, tenant_id=tenant_id)

        # 1. Check exact saved mapping match
        saved_match = find_saved_mapping(fp, tenant_id=tenant_id)
        if saved_match:
            candidate_m = saved_match["mapping"]
            val_errs = validate_mapping(
                rows,
                candidate_m.get("header_row", hdr_idx),
                candidate_m.get("mode", ""),
                candidate_m.get("origin", 0),
                candidate_m.get("destination", 1),
                candidate_m.get("rate_columns", []),
                candidate_m.get("weight_unit"),
                skid_count_column=candidate_m.get("skid_count_column"),
                custom_keywords=custom_keywords,
            )
            if not val_errs:
                mapping = candidate_m
                mapping_source = "saved"
                analysis.update({
                    "status": "ready",
                    "mode": candidate_m.get("mode"),
                    "weight_unit": candidate_m.get("weight_unit"),
                    "unresolved": [],
                    "issues": [],
                    "conflicts": [],
                })
                record_audit_log(job_id, user_id, tenant_id, "saved", mapping)

        # 2. Check near match for suggestion banner
        if not mapping:
            near_match = find_near_match(hdr_row_strings, column_count, tenant_id=tenant_id)
            if near_match:
                saved_suggestion = {
                    "mapping_id": near_match["id"],
                    "similarity": near_match.get("similarity"),
                    "mapping": near_match["mapping"],
                }

    # Standard auto-mapping fallback if status is ready
    if not mapping and analysis.get("status") == "ready":
        g = {x["field"]: x for x in analysis["guesses"]}
        rate = g.get("weight_breaks") or g.get("skid_rates")
        rate_cols = rate["columns"] if rate else []
        mapping = {
            "header_row": analysis["header_row"],
            "sheet_name": sheet_name,
            "mode": analysis["mode"],
            "origin": g["origin"]["columns"][0],
            "destination": g["destination"]["columns"][0],
            "rate_columns": rate_cols,
            "weight_unit": analysis.get("weight_unit"),
        }
        if analysis.get("skid_tiers"):
            mapping["skid_tiers"] = analysis["skid_tiers"]
        if analysis.get("base_cost_column") is not None:
            mapping["base_cost_column"] = analysis["base_cost_column"]
        mapping_source = "auto"
        record_audit_log(job_id, user_id, tenant_id, "auto", mapping)

    job_data = {
        "job_id": job_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "path": path,
        "ext": ext,
        "sheet_name": sheet_name,
        "column_count": column_count,
        "rows": rows[:PREVIEW_ROWS],
        "analysis": analysis,
        "mapping": mapping,
        "mapping_source": mapping_source,
        "saved_mapping_suggestion": saved_suggestion,
        "status": analysis.get("status", "needs_mapping"),
    }
    job_store.create(job_id, job_data)
    return _state(job_id, job_data)


@router.get("/jobs/{job_id}", response_model=JobState)
def get_job(job_id: str, request: Request):
    user_id, tenant_id = get_current_user_and_tenant(request)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    _check_job_access(job, user_id, tenant_id)
    return _state(job_id, job)


def _extract_lane_loc(loc_spec: Any, row_data: List[Any]) -> str:
    if isinstance(loc_spec, dict):
        c_idx = loc_spec.get("city_column")
        r_idx = loc_spec.get("region_column")
        city = row_data[c_idx] if c_idx is not None and c_idx < len(row_data) else ""
        reg = row_data[r_idx] if r_idx is not None and r_idx < len(row_data) else ""
        return normalize_location_field(city, reg)
    elif isinstance(loc_spec, int) and loc_spec < len(row_data):
        return normalize_location_field(row_data[loc_spec])
    return ""


def _sample_active_segment_lanes(
    rows: List[List[Any]],
    header_row: int,
    mapping: Dict[str, Any],
    user_selected_row: Optional[int] = None,
) -> List[Dict[str, Any]]:
    active_rows_start = header_row + 1
    total_data_rows = len(rows) - active_rows_start
    if total_data_rows <= 0:
        return []

    rate_cols = mapping.get("rate_columns") or []
    origin_type = mapping.get("origin_type", "column")
    fixed_origin = mapping.get("fixed_origin_value")
    orig_spec = mapping.get("origin")
    dest_spec = mapping.get("destination")

    def _is_populated(r: List[Any]) -> bool:
        for c in rate_cols:
            if c < len(r) and r[c] is not None:
                clean = re.sub(r"[^\d.]", "", str(r[c]).strip())
                try:
                    if float(clean) > 0:
                        return True
                except ValueError:
                    pass
        return False

    def _row_locations(r: List[Any]) -> Tuple[str, str]:
        if origin_type == "fixed" and fixed_origin:
            orig = normalize_location_field(fixed_origin)
        else:
            orig = _extract_lane_loc(orig_spec, r)
        dest = _extract_lane_loc(dest_spec, r)
        return orig, dest

    candidate_indices = []
    fallback_indices = []
    for idx in range(active_rows_start, len(rows)):
        r = rows[idx]
        if not r:
            continue
        orig, dest = _row_locations(r)
        if not orig or not dest:
            continue
        fallback_indices.append(idx)
        if not rate_cols or _is_populated(r):
            candidate_indices.append(idx)

    valid_indices = candidate_indices if candidate_indices else fallback_indices
    if not valid_indices:
        valid_indices = list(range(active_rows_start, min(len(rows), active_rows_start + 5)))

    picked_indices = []
    if user_selected_row is not None and 1 <= user_selected_row <= len(rows):
        zero_idx = user_selected_row - 1
        if zero_idx in valid_indices:
            picked_indices.append(zero_idx)

    num_needed = 5 - len(picked_indices)
    if num_needed > 0 and valid_indices:
        n = len(valid_indices)
        if n <= num_needed:
            for idx in valid_indices:
                if idx not in picked_indices:
                    picked_indices.append(idx)
        else:
            for i in range(num_needed):
                pos = int(round(i * (n - 1) / float(max(1, num_needed - 1))))
                target_idx = valid_indices[pos]
                if target_idx not in picked_indices:
                    picked_indices.append(target_idx)
            for idx in valid_indices:
                if len(picked_indices) >= 5:
                    break
                if idx not in picked_indices:
                    picked_indices.append(idx)

    results = []
    seen_lanes: Set[Tuple[str, str]] = set()

    for idx in picked_indices:
        if idx >= len(rows):
            continue
        r = rows[idx]
        orig, dest = _row_locations(r)

        lane_key = (orig.lower(), dest.lower())
        if lane_key in seen_lanes and len(picked_indices) > 5:
            continue
        seen_lanes.add(lane_key)

        results.append({
            "row_index": idx + 1,
            "origin": orig,
            "destination": dest,
            "row_data": r,
        })

    return results


def _derive_test_points_for_lane(
    lane_info: Dict[str, Any],
    mapping: Dict[str, Any],
    sheet_dict: Dict[str, Any],
    rules_dict: Dict[str, Any],
    lane_index: int = 0,
) -> List[Dict[str, Any]]:
    mode = (mapping.get("mode") or "weight").lower()
    rate_basis = (mapping.get("rate_basis") or "PER_CWT").upper()
    allow_deficit = bool(sheet_dict.get("allow_deficit_rating", 1))

    test_points = []
    if mode == "skid":
        max_skid = int(sheet_dict.get("max_skid_capacity") or mapping.get("max_skid_capacity") or 10)
        skid_tiers = mapping.get("skid_tiers") or []

        tier_targets = []
        if skid_tiers:
            for t in skid_tiers:
                m_u = int(t.get("min_units") if t.get("min_units") is not None else (t.get("min_skids") or 1))
                if m_u not in tier_targets and 1 <= m_u <= max_skid:
                    tier_targets.append(m_u)
                mx_u = int(t.get("max_units") if t.get("max_units") is not None else (t.get("max_skids") or m_u))
                if mx_u not in tier_targets and 1 <= mx_u <= max_skid:
                    tier_targets.append(mx_u)
        elif rules_dict.get("breaks"):
            for b in rules_dict["breaks"]:
                cnt = int(b.get("min_weight", 1))
                if cnt not in tier_targets and 1 <= cnt <= max_skid:
                    tier_targets.append(cnt)

        tier_targets = sorted(list(set(tier_targets)))
        if not tier_targets:
            tier_targets = [1, 2, 4, 6, 8]

        target_skid = tier_targets[lane_index % len(tier_targets)]
        break_num = (lane_index % len(tier_targets)) + 1

        test_points.append({
            "type": "tier_break",
            "label": f"{target_skid} Skid{'s' if target_skid != 1 else ''} (Break #{break_num})",
            "weight": float(target_skid * 1000),
            "skid_count": target_skid,
            "is_card": True,
        })

        if target_skid != 1 and 1 not in [p.get("skid_count") for p in test_points]:
            test_points.append({
                "type": "floor",
                "label": "1 Skid (Floor)",
                "weight": 1000.0,
                "skid_count": 1,
                "is_card": False,
            })
        top_skid = min(tier_targets[-1], max_skid)
        if top_skid != target_skid and top_skid not in [p.get("skid_count") for p in test_points]:
            test_points.append({
                "type": "top",
                "label": f"{top_skid} Skids (Top Tier)",
                "weight": float(top_skid * 1000),
                "skid_count": top_skid,
                "is_card": False,
            })
        return test_points

    breaks = rules_dict.get("breaks") or []
    orig = lane_info["origin"]
    dest = lane_info["destination"]
    lane_breaks = [
        b for b in breaks
        if (b.get("origin_spec", "").strip().lower() == orig.strip().lower() and
            b.get("dest_spec", "").strip().lower() == dest.strip().lower())
    ]
    if not lane_breaks:
        lane_breaks = breaks

    unique_weights = sorted(list({float(b["min_weight"]) for b in lane_breaks if float(b.get("min_weight", 0)) >= 0}))
    if not unique_weights:
        unique_weights = [500.0, 1000.0, 2000.0, 5000.0, 10000.0]

    b_1 = unique_weights[0] if unique_weights else 500.0
    w_floor = max(1.0, b_1 - 100.0) if b_1 > 100.0 else max(1.0, b_1 * 0.5)

    median_idx = len(unique_weights) // 2
    b_median = unique_weights[median_idx]

    b_n = unique_weights[-1]
    effective_max = float(sheet_dict.get("max_weight_limit") or 44000.0)
    w_top = min(b_n, effective_max - 100.0)

    test_points.append({
        "type": "floor",
        "label": f"Minimum Floor ({int(w_floor)} lbs)",
        "weight": float(w_floor),
        "is_card": True,
    })
    test_points.append({
        "type": "median",
        "label": f"Median Break ({int(b_median)} lbs)",
        "weight": float(b_median),
        "is_card": True,
    })
    test_points.append({
        "type": "top",
        "label": f"Top Break ({int(w_top)} lbs)",
        "weight": float(w_top),
        "is_card": True,
    })

    for w in unique_weights:
        if w not in (w_floor, b_median, w_top):
            test_points.append({
                "type": "break_boundary",
                "label": f"Break Boundary ({int(w)} lbs)",
                "weight": float(w),
                "is_card": False,
            })

    if allow_deficit and rate_basis == "PER_CWT":
        crossover_cards_added = False
        wt_to_rate: Dict[float, float] = {}
        for b in lane_breaks:
            wt_to_rate[float(b["min_weight"])] = float(b["base_rate"])

        for i in range(len(unique_weights) - 1):
            bk = unique_weights[i]
            b_next = unique_weights[i + 1]
            rk = wt_to_rate.get(bk)
            r_next = wt_to_rate.get(b_next)
            if rk and r_next and rk > r_next > 0 and b_next > bk:
                w_cross = (b_next * r_next) / rk
                if w_cross > bk:
                    w_below = max(bk, int(w_cross) - 1)
                    w_above = min(b_next, int(w_cross) + 1)
                    is_first = not crossover_cards_added
                    test_points.append({
                        "type": "deficit_savings",
                        "label": f"Deficit Opportunity ({int(w_above)} lbs)",
                        "weight": float(w_above),
                        "is_card": is_first,
                    })
                    if is_first:
                        crossover_cards_added = True
                    test_points.append({
                        "type": "crossover_point",
                        "label": f"Below Crossover ({int(w_below)} lbs)",
                        "weight": float(w_below),
                        "is_card": False,
                    })

    return test_points


def evaluate_failsafe_findings(
    rows: List[List[Any]],
    mapping: Dict[str, Any],
    sheet_sha256: str = "",
    is_enforced: bool = False,
    header_confidence: float = 1.0,
) -> Tuple[List[Finding], List[Finding]]:
    blockers: List[Finding] = []
    warnings: List[Finding] = []

    header_row = int(mapping.get("header_row", 0))
    mode = str(mapping.get("mode") or "weight").lower()
    rate_basis = str(mapping.get("rate_basis") or "PER_CWT").upper()
    origin_type = mapping.get("origin_type", "column")
    fixed_origin = mapping.get("fixed_origin_value")
    orig_spec = mapping.get("origin")
    dest_spec = mapping.get("destination")
    rate_cols = mapping.get("rate_columns") or []
    base_cost_col = mapping.get("base_cost_column")
    weight_unit = mapping.get("weight_unit")
    currency = mapping.get("currency")
    user_break_weights = mapping.get("user_break_weights") or {}
    skid_tiers = mapping.get("skid_tiers") or []
    header_confirmed = bool(mapping.get("header_row_confirmed", False))
    carrier_max_wt = mapping.get("carrier_max_weight")

    # 1. Origin
    if origin_type == "fixed":
        if not fixed_origin or not str(fixed_origin).strip():
            blockers.append(Finding(BLOCKER_MISSING_ORIGIN, SEVERITY_BLOCKER, "Fixed origin value must be provided.", sheet_sha256=sheet_sha256))
    else:
        orig_col = orig_spec.get("city_column") if isinstance(orig_spec, dict) else orig_spec
        if orig_col is None:
            blockers.append(Finding(BLOCKER_MISSING_ORIGIN, SEVERITY_BLOCKER, "Origin column must be mapped.", sheet_sha256=sheet_sha256))

    # 2. Destination
    dest_col = dest_spec.get("city_column") if isinstance(dest_spec, dict) else dest_spec
    if dest_col is None:
        blockers.append(Finding(BLOCKER_MISSING_DEST, SEVERITY_BLOCKER, "Destination column must be mapped.", sheet_sha256=sheet_sha256))

    # 3. Currency (Mandatory once enforced)
    if is_enforced and (not currency or str(currency).strip().upper() not in ("CAD", "USD")):
        blockers.append(Finding(BLOCKER_MISSING_CURRENCY, SEVERITY_BLOCKER, "Currency is required (CAD or USD).", sheet_sha256=sheet_sha256))

    # 4. Weight Unit
    if mode == "weight" and (not weight_unit or str(weight_unit).strip().lower() not in ("lb", "kg")):
        blockers.append(Finding(BLOCKER_WEIGHT_MISSING_UNIT, SEVERITY_BLOCKER, "Weight unit is required (lb or kg).", sheet_sha256=sheet_sha256))

    # 5. Rate columns
    if mode == "weight" and not rate_cols:
        blockers.append(Finding(BLOCKER_WEIGHT_NO_RATES, SEVERITY_BLOCKER, "At least one rate column must be selected.", sheet_sha256=sheet_sha256))
    elif mode == "skid" and not rate_cols and not skid_tiers:
        blockers.append(Finding(BLOCKER_SKID_INVALID_TIERS, SEVERITY_BLOCKER, "Skid tiers or rate columns must be specified.", sheet_sha256=sheet_sha256))

    # 6. Column collision
    orig_idx = orig_spec.get("city_column") if isinstance(orig_spec, dict) else orig_spec
    dest_idx = dest_spec.get("city_column") if isinstance(dest_spec, dict) else dest_spec
    if origin_type == "column" and orig_idx is not None and dest_idx is not None and orig_idx == dest_idx:
        blockers.append(Finding(BLOCKER_COLUMN_COLLISION, SEVERITY_BLOCKER, f"Origin and Destination mapped to the same column ({orig_idx}).", affected_columns=[orig_idx], sheet_sha256=sheet_sha256))
    if base_cost_col is not None and base_cost_col in rate_cols:
        blockers.append(Finding(BLOCKER_MC_RATE_COLLISION, SEVERITY_BLOCKER, f"Minimum Charge column ({base_cost_col}) cannot be mapped as a rate break column.", affected_columns=[base_cost_col], sheet_sha256=sheet_sha256))

    # 7. Header Ambiguity
    if header_confidence < 0.50 and not header_confirmed:
        blockers.append(Finding(BLOCKER_HEADER_AMBIGUITY, SEVERITY_BLOCKER, "Header row confidence is low. Explicit confirmation required.", sheet_sha256=sheet_sha256))

    headers = [str(c or "").strip() for c in rows[header_row]] if 0 <= header_row < len(rows) else []
    active_rows = rows[header_row + 1:] if header_row + 1 < len(rows) else []

    # 8. Rate Column Non-Numeric check
    for c_idx in rate_cols:
        text_count = 0
        pop_count = 0
        for r in active_rows:
            if c_idx < len(r) and r[c_idx] is not None and str(r[c_idx]).strip() != "":
                pop_count += 1
                try:
                    float(re.sub(r"[^\d.-]", "", str(r[c_idx]).strip()))
                except ValueError:
                    text_count += 1
        if pop_count >= 10 and (text_count / pop_count) > 0.05:
            blockers.append(Finding(BLOCKER_RATE_COL_NON_NUMERIC, SEVERITY_BLOCKER, f"Column {c_idx} contains >5% text values.", affected_columns=[c_idx], sheet_sha256=sheet_sha256))

    # 9. Break label parsing check
    rate_col_break_pairs = []
    if mode == "weight":
        for c_idx in rate_cols:
            h_text = headers[c_idx] if c_idx < len(headers) else f"Col {c_idx}"
            u_wt = user_break_weights.get(c_idx) or user_break_weights.get(str(c_idx))
            parsed_w = parse_break_label(h_text, user_weight_fallback=u_wt)
            if parsed_w is None:
                blockers.append(Finding(BLOCKER_UNPARSED_BREAK_LABEL, SEVERITY_BLOCKER, f"Unrecognized weight break label '{h_text}'. Provide numeric weight fallback.", affected_columns=[c_idx], sheet_sha256=sheet_sha256))
            else:
                rate_col_break_pairs.append((c_idx, max(0.0, parsed_w)))

    # 10. All lanes no rate check
    if active_rows and rate_cols:
        populated_lanes = 0
        for r in active_rows[:50]:
            for c in rate_cols:
                if c < len(r) and r[c] is not None:
                    try:
                        if float(re.sub(r"[^\d.]", "", str(r[c]).strip())) > 0:
                            populated_lanes += 1
                            break
                    except ValueError:
                        pass
        if populated_lanes == 0:
            blockers.append(Finding(BLOCKER_ALL_LANES_NO_RATE, SEVERITY_BLOCKER, "No numeric freight rates found across sampled lanes.", sheet_sha256=sheet_sha256))

    if blockers:
        return blockers, warnings

    # HEURISTICS & WARNINGS
    if mode == "weight" and len(rate_col_break_pairs) >= 2:
        warnings.extend(check_monotonicity(active_rows, rate_col_break_pairs, rate_basis=rate_basis, sheet_sha256=sheet_sha256))

    for c_idx in rate_cols:
        h_text = headers[c_idx] if c_idx < len(headers) else ""
        col_vals = [r[c_idx] if c_idx < len(r) else None for r in active_rows]

        td_warn = check_transit_days_vs_integer_rates(h_text, col_vals, c_idx, sheet_sha256=sheet_sha256)
        if td_warn:
            warnings.append(td_warn)

        b_wt = dict(rate_col_break_pairs).get(c_idx) if mode == "weight" else None
        outlier_warn = check_statistical_outlier(col_vals, c_idx, col_name=h_text, rate_basis=rate_basis, break_weight=b_wt, sheet_sha256=sheet_sha256)
        if outlier_warn:
            warnings.append(outlier_warn)

    h_orig = headers[orig_idx] if orig_idx is not None and orig_idx < len(headers) else ""
    h_dest = headers[dest_idx] if dest_idx is not None and dest_idx < len(headers) else ""
    inv_warn = check_inverted_lanes(h_orig, h_dest, fixed_origin=fixed_origin, sheet_sha256=sheet_sha256, origin_col=orig_idx, dest_col=dest_idx)
    if inv_warn:
        warnings.append(inv_warn)

    break_wts = [bw for _, bw in rate_col_break_pairs]
    if check_parcel_dual_signal(break_wts, headers, mode=mode):
        warnings.append(Finding(WARN_PARCEL_CONTOUR_OVERRIDE, SEVERITY_WARNING, "Courier parcel packaging or weight contour detected (<= 150 lbs).", sheet_sha256=sheet_sha256))

    if carrier_max_wt and rate_col_break_pairs:
        top_wt = max(bw for _, bw in rate_col_break_pairs)
        if top_wt > float(carrier_max_wt):
            warnings.append(Finding(WARN_BREAK_EXCEEDS_CAPACITY, SEVERITY_WARNING, f"Top weight break ({top_wt:.0f} lbs) exceeds carrier capacity ({carrier_max_wt:.0f} lbs).", sheet_sha256=sheet_sha256))

    return blockers, warnings


@router.post("/jobs/{job_id}/dry-run")
def dry_run(job_id: str, req: DryRunRequest, request: Request):
    user_id, tenant_id = get_current_user_and_tenant(request)
    if not user_id:
        raise HTTPException(401, "Authentication required for dry-run verification.")
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    _check_job_access(job, user_id, tenant_id)

    # Rate limiting (60 req/min, 20 burst per user)
    if not rate_limiter.check_and_consume(user_id):
        return JSONResponse(
            status_code=429,
            content={"error": "E_RATE_LIMIT_EXCEEDED", "message": "Dry-run rate limit exceeded. Please wait a moment."}
        )

    deadline = monotonic_clock() + 3.0
    mapping = req.mapping
    target_sheet = mapping.get("sheet_name") or job.get("sheet_name")
    sheet_sha256 = job.get("sheet_sha256") or hashlib.sha256(job["path"].encode()).hexdigest()
    cache_key = f"{job_id}:{sheet_sha256}:{target_sheet}"

    cached = grid_cache.get(cache_key)
    if cached:
        rows, ext = cached
    else:
        if not os.path.exists(job["path"]):
            raise HTTPException(410, "Spreadsheet file is no longer available.")
        if monotonic_clock() > deadline:
            return JSONResponse(status_code=504, content={"error": "DRY_RUN_TIMEOUT", "message": "Grid load deadline exceeded."})
        rows, ext = load_sheet_grid(
            job["path"],
            job["ext"],
            sheet_name=target_sheet,
            max_rows=MAX_DATA_ROWS,
            max_cols=MAX_DATA_COLS,
        )
        grid_cache.set(cache_key, rows, ext)

    if monotonic_clock() > deadline:
        return JSONResponse(status_code=504, content={"error": "DRY_RUN_TIMEOUT", "message": "Calculation deadline exceeded."})

    sheet_dict, rules_dict, _ = build_normalized_rate_sheet_records(
        mapping=mapping,
        rows=rows,
        filename=job.get("filename") or os.path.basename(job["path"]),
        sheet_name=target_sheet or "Sheet1",
    )

    header_row_idx = int(mapping.get("header_row", 0))
    sampled_lanes = _sample_active_segment_lanes(
        rows=rows,
        header_row=header_row_idx,
        mapping=mapping,
        user_selected_row=req.selected_row_index,
    )

    sample_runs = []
    total_checks = 0
    checked_count = 0
    timed_out = False

    for lane_idx, lane_info in enumerate(sampled_lanes):
        row_idx_1_based = lane_info["row_index"]
        origin = lane_info["origin"]
        destination = lane_info["destination"]

        if not origin or not destination:
            sample_runs.append({
                "lane_idx": lane_idx,
                "row_index": row_idx_1_based,
                "origin": origin,
                "destination": destination,
                "status": "NO_RATE_FOR_LANE",
                "result": "no rate for this lane",
                "client_total": None,
                "cards": [],
                "drawer_points": [],
            })
            continue

        test_points = _derive_test_points_for_lane(
            lane_info=lane_info,
            mapping=mapping,
            sheet_dict=sheet_dict,
            rules_dict=rules_dict,
            lane_index=lane_idx,
        )

        lane_cards = []
        lane_drawer = []

        for tp in test_points:
            total_checks += 1
            if monotonic_clock() > deadline:
                timed_out = True
                break

            checked_count += 1
            wt = tp["weight"]
            skids = tp.get("skid_count")

            try:
                calc_res = calculate_quote_from_memory(
                    sheet=sheet_dict,
                    rules=rules_dict,
                    origin=origin,
                    destination=destination,
                    actual_weight=wt,
                    skid_count=skids,
                )
                pt_data = {
                    "type": tp["type"],
                    "label": tp["label"],
                    "weight_lbs": wt,
                    "skid_count": skids,
                    "total_charge": str(calc_res.get("client_total", "0.00")),
                    "base_freight": str(calc_res.get("base_freight", "0.00")),
                    "is_deficit_rated": calc_res.get("is_deficit_rated", False),
                    "deficit_savings": str(calc_res.get("deficit_savings", "0.00")),
                    "min_applied": calc_res.get("min_applied", False),
                    "surcharges": calc_res.get("surcharges", []),
                    "fuel_provenance": "FCA_BENCHMARK" if calc_res.get("surcharges") else "NOT_APPLIED",
                    "status": "OK",
                }
            except Exception as e:
                pt_data = {
                    "type": tp["type"],
                    "label": tp["label"],
                    "weight_lbs": wt,
                    "skid_count": skids,
                    "status": "ERROR",
                    "error_message": str(e),
                }

            if tp.get("is_card", False):
                lane_cards.append(pt_data)
            else:
                lane_drawer.append(pt_data)

        primary_card = lane_cards[0] if lane_cards else (lane_drawer[0] if lane_drawer else {})
        has_rate = (primary_card.get("status") == "OK" and primary_card.get("total_charge") is not None)
        client_tot = primary_card.get("total_charge") if has_rate else None

        sample_runs.append({
            "lane_idx": lane_idx,
            "row_index": row_idx_1_based,
            "origin": origin,
            "destination": destination,
            "status": "OK" if (lane_cards or lane_drawer) else "NO_RATE_FOR_LANE",
            "result": "rated" if has_rate else "no rate for this lane",
            "client_total": client_tot,
            "test_point_label": primary_card.get("label"),
            "skids": primary_card.get("skid_count"),
            "weight": primary_card.get("weight_lbs"),
            "is_deficit_rated": primary_card.get("is_deficit_rated", False),
            "min_applied": primary_card.get("min_applied", False),
            "cards": lane_cards,
            "drawer_points": lane_drawer,
        })

        if timed_out:
            break

    drawer_rows = []
    for run in sample_runs:
        all_pts = (run.get("cards") or []) + (run.get("drawer_points") or [])
        for pt in all_pts:
            if pt.get("status") == "OK":
                drawer_rows.append({
                    "lane_idx": run.get("lane_idx", 0),
                    "origin": run.get("origin", ""),
                    "destination": run.get("destination", ""),
                    "weight": pt.get("weight_lbs"),
                    "skids": pt.get("skid_count"),
                    "rate_break": pt.get("label", ""),
                    "formula": f"Base: ${pt.get('base_freight', '0.00')}",
                    "client_total": pt.get("total_charge", "0.00"),
                    "currency": sheet_dict.get("currency", "CAD"),
                })

    status_str = "PARTIAL_CHECK" if timed_out else "COMPLETE"
    return {
        "seq_id": req.seq_id,
        "status": status_str,
        "checked_count": checked_count,
        "total_count": total_checks if not timed_out else (total_checks + 10),
        "sample_runs": sample_runs,
        "drawer_rows": drawer_rows,
        "currency": sheet_dict.get("currency", "CAD"),
        "weight_unit": sheet_dict.get("weight_unit", "lb"),
    }


@router.post("/jobs/{job_id}/mapping", response_model=JobState)
def confirm_mapping(job_id: str, req: MappingRequest, request: Request):
    user_id, tenant_id = get_current_user_and_tenant(request)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    _check_job_access(job, user_id, tenant_id)

    # CSRF Check
    verify_csrf(request)

    # Load rows for validation
    target_sheet = req.sheet_name or job.get("sheet_name")
    rows, _ = load_sheet_grid(
        job["path"],
        job["ext"],
        sheet_name=target_sheet,
    )

    sheet_sha256 = job.get("sheet_sha256") or hashlib.sha256(job["path"].encode()).hexdigest()
    failsafe_mode = get_effective_failsafe_mode(tenant_id)
    is_enforced = (failsafe_mode == "enforce")

    # Evaluate failsafe findings
    mapping_dict = req.model_dump()
    blockers, warnings = evaluate_failsafe_findings(
        rows=rows,
        mapping=mapping_dict,
        sheet_sha256=sheet_sha256,
        is_enforced=is_enforced,
    )

    client_ip = request.client.host if request.client else "127.0.0.1"

    # SHADOW MODE EVALUATION
    if failsafe_mode == "shadow":
        try:
            shadow_findings = [f.to_dict() for f in blockers + warnings]
            structured_snapshot = json.dumps({
                k: v for k, v in mapping_dict.items()
                if k not in ("override_notes", "fixed_origin_value")
            })
            insert_failsafe_shadow_log(
                job_id=job_id,
                tenant_id=tenant_id or "default",
                tab_name=target_sheet or "Sheet1",
                mapping_snapshot_json=structured_snapshot,
                findings_json=json.dumps(shadow_findings),
            )
        except Exception as e:
            logger.warning(f"Shadow mode logging failed open: {e}")

    # ENFORCE MODE EVALUATION
    elif failsafe_mode == "enforce":
        if blockers:
            increment_failsafe_rejection(
                tenant_id=tenant_id or "default",
                client_ip=client_ip,
                blocker_code=blockers[0].code,
            )
            return JSONResponse(
                status_code=422,
                content={
                    "error": "E_BLOCKER_VIOLATION",
                    "code": blockers[0].code,
                    "message": blockers[0].message,
                    "blockers": [b.to_dict() for b in blockers],
                }
            )

        if warnings:
            ack_set = set(req.acknowledged_finding_ids or [])
            unacknowledged = [w for w in warnings if w.finding_id not in ack_set]
            if unacknowledged:
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "E_UNACKNOWLEDGED_WARNING",
                        "unacknowledged": [w.to_dict() for w in unacknowledged],
                        "warnings": [w.to_dict() for w in warnings],
                    }
                )

            # All warnings acknowledged: write audit log and clearable attribution
            audit_id = str(uuid.uuid4())
            structured_snapshot = json.dumps({
                k: v for k, v in mapping_dict.items()
                if k not in ("override_notes", "fixed_origin_value")
            })
            insert_failsafe_audit_log(
                job_id=job_id,
                tenant_id=tenant_id or "default",
                decision_type="OVERRIDE_CONFIRMED",
                sheet_sha256=sheet_sha256,
                tab_name=target_sheet or "Sheet1",
                mapping_snapshot_json=structured_snapshot,
                warnings_triggered_json=json.dumps([w.to_dict() for w in warnings]),
                acknowledged_findings_json=json.dumps(req.acknowledged_finding_ids),
                log_id=audit_id,
            )
            insert_failsafe_override_attribution(
                audit_log_id=audit_id,
                tenant_id=tenant_id or "default",
                user_id=user_id or "anonymous",
                user_email="user@quotelytics.internal",
                user_fixed_origin_text=req.fixed_origin_value,
                override_notes_json=json.dumps(req.override_notes or {}),
            )
        else:
            # Clean confirmation
            audit_id = str(uuid.uuid4())
            structured_snapshot = json.dumps({
                k: v for k, v in mapping_dict.items()
                if k not in ("override_notes", "fixed_origin_value")
            })
            insert_failsafe_audit_log(
                job_id=job_id,
                tenant_id=tenant_id or "default",
                decision_type="USER_CONFIRMED",
                sheet_sha256=sheet_sha256,
                tab_name=target_sheet or "Sheet1",
                mapping_snapshot_json=structured_snapshot,
                log_id=audit_id,
            )

    job["mapping"] = mapping_dict
    job["mapping_source"] = "user"
    job["analysis"].update({
        "status": "ready",
        "header_row": req.header_row,
        "sheet_name": target_sheet,
        "mode": req.mode.value if hasattr(req.mode, "value") else str(req.mode),
        "weight_unit": req.weight_unit,
        "unresolved": [],
        "issues": [],
        "conflicts": [],
    })
    job["status"] = "ready"
    job_store.update(job_id, job)

    # Saved mapping layout fingerprint (tab-agnostic, SHA-256)
    if req.remember_mapping and user_id and tenant_id and 0 <= req.header_row < len(rows):
        hdr_strings = [str(c or "").strip() for c in rows[req.header_row]]
        fp = compute_fingerprint(hdr_strings, len(hdr_strings), tenant_id=tenant_id)
        save_mapping(
            fp,
            user_id,
            tenant_id,
            target_sheet,
            mapping_dict,
            len(hdr_strings),
            hdr_strings,
        )

    return _state(job_id, job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    """
    Cancels a job and marks it as expired/cancelled without modifying or processing the original file (Rule 9 & Rule 12).
    """
    user_id, tenant_id = get_current_user_and_tenant(request)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    _check_job_access(job, user_id, tenant_id)

    job_store.update(job_id, {"status": "expired"})
    record_audit_log(job_id, user_id, tenant_id, "cancelled", {})
    return {"job_id": job_id, "status": "expired", "message": "Job cancelled safely. Uploaded file remains untouched."}


def ingest_job_to_quotelytics(job: Dict[str, Any], user_id: str) -> Optional[str]:
    """
    Ingests the confirmed mapping into the Quotelytics quote database (ql_rate_sheets and ql_weight_breaks).
    Makes the newly uploaded and confirmed sheet immediately visible in the console and quotable.
    """
    from services.quotelytics_db_service import (
        create_rate_sheet,
        insert_weight_breaks,
        insert_rate_sheet_cells,
        insert_carrier_minimums,
    )
    from app.ingest import load_sheet_grid
    import re
    from openpyxl.utils import get_column_letter

    mapping = job.get("mapping") or {}
    target_sheet = mapping.get("sheet_name") or job.get("sheet_name")
    rows, ext = load_sheet_grid(
        job["path"],
        job["ext"],
        sheet_name=target_sheet,
        max_rows=MAX_DATA_ROWS,
        max_cols=MAX_DATA_COLS,
    )
    header_row_idx = int(mapping.get("header_row", 0))
    origin_col = mapping.get("origin")
    dest_col = mapping.get("destination")
    rate_cols = mapping.get("rate_columns") or []
    mode = mapping.get("mode", "weight")
    weight_unit = mapping.get("weight_unit") or "lb"
    skid_col = mapping.get("skid_count_column")
    base_cost_col = mapping.get("base_cost_column")
    max_skid_cap = int(mapping.get("max_skid_capacity") or 10)
    skid_tiers = mapping.get("skid_tiers") or []
    raw_sheet_name = mapping.get("sheet_name") or job.get("sheet_name") or "Carrier Tariff"

    # Derive clean carrier and service names
    filename = job.get("filename") or os.path.basename(job["path"])
    base_name = os.path.splitext(filename)[0]
    carrier_name = raw_sheet_name if raw_sheet_name and raw_sheet_name != "Sheet1" else base_name
    carrier_name = re.sub(r'[_]+', ' ', carrier_name).strip()
    base_service = "Standard LTL" if mode == "weight" else "Skid / Pallet Freight"
    service_name = f"{base_service} ({target_sheet})" if target_sheet and target_sheet not in ("Sheet1", "Sheet 1") else base_service

    if not user_id:
        return None

    # Create sheet record with CONFIRMED status
    sheet_id = create_rate_sheet(
        user_id=user_id,
        carrier_name=carrier_name,
        service_name=service_name,
        tariff_ref="Failsafe Mapped Tariff",
        mode="LTL",
        currency="CAD",
        weight_unit=weight_unit,
        dim_unit="in",
        dim_divisor=None,
        rounding_rule="standard_2dp",
        confirmation_status="CONFIRMED",
        source_filename=filename,
        rating_basis="WEIGHT_CWT" if mode == "weight" else "PALLET_TIER",
        max_skid_capacity=max_skid_cap,
        no_minimum_confirmed=1 if base_cost_col is None else 0,
        failsafe_status="ready",
    )

    # Get header names
    headers = []
    if 0 <= header_row_idx < len(rows):
        headers = [str(c or "").strip() for c in rows[header_row_idx]]

    from services.break_header_parser import (
        ParsedBreak,
        parse_break_header,
        parse_skid_break_from_keywords,
        resolve_contiguous_weight_brackets,
    )
    from services.db_service import get_user_keyword_map

    custom_keywords = get_user_keyword_map(user_id)

    # Pre-resolve weight break bounds across rate_cols using the shared parser
    resolved_weight_by_col: Dict[int, ParsedBreak] = {}
    if mode == "weight":
        col_pbs = []
        for c_idx in rate_cols:
            h_txt = headers[c_idx] if c_idx < len(headers) else f"Col {c_idx + 1}"
            pb = parse_break_header(h_txt, mode_hint="weight", custom_keywords=custom_keywords)
            if pb is None:
                pb = ParsedBreak(
                    raw_header=h_txt,
                    break_name=h_txt,
                    min_weight=0.0,
                    max_weight=None,
                    is_open_ended=True,
                    break_value=0.0,
                )
            col_pbs.append((c_idx, pb))
        col_pbs.sort(key=lambda item: item[1].min_weight)
        res_pbs, _ = resolve_contiguous_weight_brackets([item[1] for item in col_pbs])
        for (c_idx, _), r_pb in zip(col_pbs, res_pbs):
            resolved_weight_by_col[c_idx] = r_pb

    extracted_breaks = []
    cell_trace_records = []
    extracted_minimums = []
    current_section = ""

    # Build quick lookup dictionary for skid tier mappings by column index
    tier_map_by_col = {}
    if mode == "skid" and skid_tiers:
        for t in skid_tiers:
            c = t.get("column") if t.get("column") is not None else t.get("col")
            if c is not None:
                tier_map_by_col[int(c)] = t

    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        excel_row_num = r_idx + 1

        # Check for section header row (e.g. "Toronto to Winnipeg")
        row_str_values = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
        if len(row_str_values) == 1 and ("to" in row_str_values[0].lower() or "lane" in row_str_values[0].lower()):
            current_section = row_str_values[0]
            continue

        # Origin
        origin_val = ""
        origin_cell = ""
        if isinstance(origin_col, dict):
            c_idx = origin_col.get("city_column")
            r_idx = origin_col.get("region_column")
            c_val = str(row[c_idx]).strip() if c_idx is not None and c_idx < len(row) and row[c_idx] is not None else ""
            r_val = str(row[r_idx]).strip() if r_idx is not None and r_idx < len(row) and row[r_idx] is not None else ""
            origin_val = f"{c_val}, {r_val}".strip(", ") if r_val else c_val
            origin_cell = f"{get_column_letter(c_idx + 1)}{excel_row_num}" if c_idx is not None else ""
        elif origin_col is not None and isinstance(origin_col, int) and origin_col < len(row) and row[origin_col] is not None:
            origin_val = str(row[origin_col]).strip()
            origin_cell = f"{get_column_letter(origin_col + 1)}{excel_row_num}"

        # Destination
        dest_val = ""
        dest_cell = ""
        if isinstance(dest_col, dict):
            c_idx = dest_col.get("city_column")
            r_idx = dest_col.get("region_column")
            c_val = str(row[c_idx]).strip() if c_idx is not None and c_idx < len(row) and row[c_idx] is not None else ""
            r_val = str(row[r_idx]).strip() if r_idx is not None and r_idx < len(row) and row[r_idx] is not None else ""
            dest_val = f"{c_val}, {r_val}".strip(", ") if r_val else c_val
            dest_cell = f"{get_column_letter(c_idx + 1)}{excel_row_num}" if c_idx is not None else ""
        elif dest_col is not None and isinstance(dest_col, int) and dest_col < len(row) and row[dest_col] is not None:
            dest_val = str(row[dest_col]).strip()
            dest_cell = f"{get_column_letter(dest_col + 1)}{excel_row_num}"

        # Fallback to section header if origin/dest are blank
        if not origin_val and current_section:
            origin_val = current_section
        if not dest_val and current_section:
            dest_val = current_section

        if not origin_val and not dest_val:
            continue

        # Skid count if specified in a row column
        row_skid_count = None
        if skid_col is not None and skid_col < len(row) and row[skid_col] is not None:
            try:
                row_skid_count = int(float(str(row[skid_col]).strip()))
            except Exception:
                pass

        # Traceability for origin & destination
        if origin_val:
            cell_trace_records.append({
                "cell_coord": origin_cell or f"Row{excel_row_num}",
                "field_name": "origin",
                "raw_value": origin_val,
                "extracted_value": origin_val,
                "confidence": 1.0,
            })
        if dest_val:
            cell_trace_records.append({
                "cell_coord": dest_cell or f"Row{excel_row_num}",
                "field_name": "destination",
                "raw_value": dest_val,
                "extracted_value": dest_val,
                "confidence": 1.0,
            })

        # Base Cost / Minimum charge column for this row/lane (if mapped)
        if base_cost_col is not None and base_cost_col < len(row) and row[base_cost_col] is not None:
            raw_base = str(row[base_cost_col]).strip()
            base_cleaned = re.sub(r'[^0-9.]', '', raw_base)
            if base_cleaned:
                try:
                    base_val = float(base_cleaned)
                    base_cell = f"{get_column_letter(base_cost_col + 1)}{excel_row_num}"
                    extracted_minimums.append({
                        "origin_spec": origin_val,
                        "dest_spec": dest_val,
                        "min_charge": base_val,
                        "source_cell": base_cell,
                    })
                    cell_trace_records.append({
                        "cell_coord": base_cell,
                        "field_name": "base_cost_minimum",
                        "raw_value": raw_base,
                        "extracted_value": str(base_val),
                        "confidence": 1.0,
                    })
                except ValueError:
                    pass

        # Process each rate column
        for c_idx in rate_cols:
            if c_idx >= len(row) or row[c_idx] is None:
                continue
            raw_rate = str(row[c_idx]).strip()
            if not raw_rate:
                continue

            cleaned_num = re.sub(r'[^0-9.]', '', raw_rate)
            rate_val = 0.0
            if cleaned_num:
                try:
                    rate_val = float(cleaned_num)
                except ValueError:
                    rate_val = 0.0

            header_text = headers[c_idx] if c_idx < len(headers) else f"Col {get_column_letter(c_idx + 1)}"
            source_cell = f"{get_column_letter(c_idx + 1)}{excel_row_num}"

            # Weight brackets or pallet count
            min_weight = 0.0
            max_weight = None
            is_open_ended = 1
            min_units = 0.0
            max_units = 999999.0
            rate_type = "CWT" if mode == "weight" else "PER_SKID"
            break_unit = "CWT" if mode == "weight" else "SKID"

            if mode == "skid":
                max_weight = 999999.0
                skid_kw = parse_skid_break_from_keywords(header_text, custom_keywords=custom_keywords)
                if c_idx in tier_map_by_col:
                    t_info = tier_map_by_col[c_idx]
                    min_units = float(
                        t_info.get("min_units")
                        if t_info.get("min_units") is not None
                        else t_info.get("min_skids", 1.0)
                    )
                    max_units = float(
                        t_info.get("max_units")
                        if t_info.get("max_units") is not None
                        else t_info.get("max_skids", min_units)
                    )
                    rate_type = (t_info.get("rate_type") or "PER_SKID").upper()
                    break_name = t_info.get("skid_range") or header_text
                    if "skid" not in break_name.lower():
                        break_name = f"{break_name} Skids"
                elif skid_kw is not None:
                    min_units = float(skid_kw.min_weight)
                    max_units = float(skid_kw.max_weight if skid_kw.max_weight is not None else max_skid_cap)
                    break_name = header_text
                else:
                    pallet_num = row_skid_count
                    if pallet_num is None:
                        m_pl = re.search(r'(\d+)', header_text)
                        if m_pl:
                            pallet_num = int(m_pl.group(1))
                    if pallet_num is not None:
                        min_units = float(pallet_num)
                        max_units = float(pallet_num)
                    break_name = header_text
            else:
                r_pb = resolved_weight_by_col.get(c_idx)
                if r_pb is not None:
                    break_name = r_pb.break_name
                    min_weight = r_pb.min_weight
                    max_weight = r_pb.max_weight
                    is_open_ended = 1 if r_pb.is_open_ended else 0
                else:
                    break_name = header_text

            extracted_breaks.append({
                "zone_code": "DEFAULT",
                "origin_spec": origin_val,
                "dest_spec": dest_val,
                "min_weight": min_weight,
                "max_weight": max_weight,
                "is_open_ended": is_open_ended,
                "break_name": break_name,
                "base_rate": rate_val,
                "rate_type": rate_type,
                "source_cell": source_cell,
                "break_unit": break_unit,
                "min_units": min_units,
                "max_units": max_units,
            })

            cell_trace_records.append({
                "cell_coord": source_cell,
                "field_name": f"rate_{break_name}",
                "raw_value": raw_rate,
                "extracted_value": str(rate_val),
                "confidence": 1.0,
            })

    if extracted_breaks:
        insert_weight_breaks(sheet_id, user_id, extracted_breaks)
    if extracted_minimums:
        insert_carrier_minimums(sheet_id, user_id, extracted_minimums)
    if cell_trace_records:
        insert_rate_sheet_cells(sheet_id, user_id, cell_trace_records)

    return sheet_id


@router.post("/jobs/{job_id}/process")
def process(job_id: str, request: Request):
    """
    Gate: the quoting step can only run once status == ready.
    Atomic compare-and-set ready -> processing. Double-click returns 409.
    Full load limits checked before execution.
    Ingests confirmed sheet into Quotelytics database for instant quoting.
    """
    user_id, tenant_id = get_current_user_and_tenant(request)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    _check_job_access(job, user_id, tenant_id)

    current_status = job.get("analysis", {}).get("status") or job.get("status")
    if current_status != "ready":
        raise HTTPException(409, "Mapping not confirmed. Resolve the header mapping first.")

    # Atomic compare-and-set transition from ready to processing
    if not job_store.transition(job_id, "ready", "processing"):
        raise HTTPException(409, "Job is already being processed or not in ready state.")

    # Check full load limits
    from app.ingest import IngestionError, check_full_load_limits
    try:
        check_full_load_limits(job["path"], job["ext"], job.get("sheet_name"))
    except IngestionError as ie:
        job_store.update(job_id, {"status": "failed"})
        raise HTTPException(422, str(ie))

    # Verify quota limits before processing and committing sheet to database
    if user_id:
        from services.db_service import get_user_quota_info, log_bottleneck_event
        quota = get_user_quota_info(user_id)
        if quota and not quota.get("can_upload_sheet", True):
            job_store.update(job_id, {"status": "failed"})
            log_bottleneck_event(
                user_id=user_id,
                bottleneck_type="LIMIT_BLOCKED_SHEETS",
                attempted_action=f"Process rate sheet: {job.get('filename')}",
                current_usage=quota.get("sheets_uploaded", 3),
                max_limit=quota.get("max_sheets", 3),
                details={"job_id": job_id, "tier": quota.get("tier", "FREE")},
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "SHEET_LIMIT_REACHED",
                    "message": "Free Starter is limited to 3 rate sheets. Upgrade to Broker Pro or remove an existing sheet.",
                },
            )

    # Run formatting agent
    from app.agent_adapter import run_agent
    try:
        output_file = run_agent(job["path"], job["mapping"])

        # Persist confirmed sheet and its rate breaks into Quotelytics quoting database only when authenticated
        sheet_id = None
        if user_id:
            try:
                sheet_id = ingest_job_to_quotelytics(job, user_id)
            except Exception as db_err:
                print(f"[Quotelytics DB Ingest Warning]: {db_err}")

        job_store.update(job_id, {
            "status": "done",
            "output_path": output_file,
            "sheet_id": sheet_id
        })
        return {
            "job_id": job_id,
            "status": "done",
            "sheet_id": sheet_id,
            "output_file": os.path.basename(output_file)
        }
    except Exception as e:
        job_store.update(job_id, {"status": "failed"})
        raise HTTPException(500, f"Error processing quote formatting: {e}")


@router.get("/jobs/{job_id}/download")
def download(job_id: str, request: Request):
    """Downloads the newly formatted output workbook (Rule 12 & Rule 13)."""
    user_id, tenant_id = get_current_user_and_tenant(request)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    _check_job_access(job, user_id, tenant_id)

    current_status = job.get("status")
    output_path = job.get("output_path")
    if current_status != "done" or not output_path or not os.path.exists(output_path):
        raise HTTPException(409, "Output file is not ready for download.")

    from fastapi.responses import FileResponse
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"reformatted_{job_id}.xlsx",
    )



# ---------------------------------------------------------------- Saved Mappings API
@router.get("/mappings", response_model=List[SavedMappingResponse])
def get_user_mappings(request: Request):
    """Lists saved mappings for the current authenticated user/tenant."""
    user_id, tenant_id = get_current_user_and_tenant(request)
    if not user_id or not tenant_id:
        raise HTTPException(401, "Authentication required.")
    mappings = list_saved_mappings(tenant_id=tenant_id, user_id=user_id)
    return [
        SavedMappingResponse(
            id=m["id"],
            sheet_name=m.get("sheet_name"),
            column_count=m["column_count"],
            header_names=m["header_names"],
            mapping=m["mapping"],
            created_at=m["created_at"],
        )
        for m in mappings
    ]


@router.delete("/mappings/{mapping_id}")
def remove_mapping(mapping_id: str, request: Request):
    """Deletes a saved mapping for the current authenticated tenant."""
    user_id, tenant_id = get_current_user_and_tenant(request)
    if not user_id or not tenant_id:
        raise HTTPException(401, "Authentication required.")
    deleted = delete_saved_mapping(mapping_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(404, "Mapping not found.")
    return {"deleted": True, "id": mapping_id}


# Include router in standalone app
app.include_router(router)

