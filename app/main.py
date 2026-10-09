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

from app.config import ALLOWED_EXT, MAX_BYTES, PREVIEW_ROWS
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
)


# Background TTL cleanup task
async def _periodic_ttl_worker():
    while True:
        try:
            job_store.cleanup_expired()
        except Exception:
            pass
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
    Extracts (user_id, tenant_id) from headers or RateSift auth session.
    Rule 14: Used for strict tenant scoping.
    """
    header_user = request.headers.get("X-User-Id")
    header_tenant = request.headers.get("X-Tenant-Id")
    if header_user or header_tenant:
        return header_user, (header_tenant or header_user)

    # Inspect RateSift session token
    try:
        from services.auth_service import validate_session_token
        token = request.cookies.get("ratesift_session") or request.cookies.get("shipflow_session")
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
        if token:
            user = validate_session_token(token)
            if user:
                uid = str(user.get("id"))
                tid = str(user.get("company") or uid)
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
    user_id, tenant_id = get_current_user_and_tenant(request)

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

        analysis = analyze(rows, sheet_name=sheet_name)
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
    if hdr_idx is not None and 0 <= hdr_idx < len(rows):
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


@router.post("/jobs/{job_id}/mapping", response_model=JobState)
def confirm_mapping(job_id: str, req: MappingRequest, request: Request):
    user_id, tenant_id = get_current_user_and_tenant(request)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    _check_job_access(job, user_id, tenant_id)

    # Load rows for full validation
    from app.ingest import load_sheet_grid
    rows, _ = load_sheet_grid(job["path"], job["ext"])

    errors = validate_mapping(
        rows,
        req.header_row,
        req.mode.value,
        req.origin,
        req.destination,
        req.rate_columns,
        req.weight_unit,
        skid_count_column=req.skid_count_column,
    )
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    mapping_dict = req.model_dump()
    job["mapping"] = mapping_dict
    job["mapping_source"] = "user"
    job["analysis"].update({
        "status": "ready",
        "header_row": req.header_row,
        "sheet_name": req.sheet_name or job.get("sheet_name"),
        "mode": req.mode.value,
        "weight_unit": req.weight_unit,
        "unresolved": [],
        "issues": [],
        "conflicts": [],
    })
    job["status"] = "ready"
    job_store.update(job_id, job)

    record_audit_log(job_id, user_id, tenant_id, "confirmed", mapping_dict)

    # Save mapping fingerprint if requested or confirmed
    if req.remember_mapping and 0 <= req.header_row < len(rows):
        hdr_strings = [str(c or "").strip() for c in rows[req.header_row]]
        fp = compute_fingerprint(hdr_strings, len(hdr_strings), tenant_id=tenant_id)
        save_mapping(
            fp,
            user_id,
            tenant_id,
            req.sheet_name or job.get("sheet_name"),
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


@router.post("/jobs/{job_id}/process")
def process(job_id: str, request: Request):
    """
    Gate: the quoting step can only run once status == ready.
    Atomic compare-and-set ready -> processing. Double-click returns 409.
    Full load limits checked before execution.
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

    # Run formatting agent
    from app.agent_adapter import run_agent
    try:
        output_file = run_agent(job["path"], job["mapping"])
        job_store.update(job_id, {"status": "done", "output_path": output_file})
        return {"job_id": job_id, "status": "done", "output_file": os.path.basename(output_file)}
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
    """Lists saved mappings for the current user/tenant."""
    user_id, tenant_id = get_current_user_and_tenant(request)
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
    """Deletes a saved mapping for the current tenant."""
    user_id, tenant_id = get_current_user_and_tenant(request)
    deleted = delete_saved_mapping(mapping_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(404, "Mapping not found.")
    return {"deleted": True, "id": mapping_id}


# Include router in standalone app
app.include_router(router)

