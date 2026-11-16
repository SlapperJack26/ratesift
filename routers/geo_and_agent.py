"""Agent specification, Canadian FSA geo resolver, fuel index manager, and redaction endpoints."""
from typing import Optional
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from routers.deps import require_user
from services.fsa_resolver_service import resolve_lane_locations, resolve_location
from services.fuel_index_service import (
    get_available_benchmark_indices,
    get_tenant_fuel_settings,
    update_tenant_fuel_settings,
)
from services.rate_redactor_service import redact_rate_sheet_bytes

router = APIRouter()


# ==============================================================================
# AGENT SPECIFICATION & DYNAMIC DETECTION CAPABILITIES (36 Rules)
# ==============================================================================

@router.get("/api/agent/rules", tags=["Quotelytics Agent Specification"])
def api_get_agent_rules():
    """
    Returns the complete 36 rules specification trained on the master rate sheet document,
    enforcing deterministic pricing, zero data loss, autonomous dynamic detection, and human audit.
    """
    from agent.rules_spec import QUOTELYTICS_36_RULES, get_rules_summary
    return {
        "status": "success",
        "total_rules": len(QUOTELYTICS_36_RULES),
        "rules_summary": get_rules_summary(),
        "rules": QUOTELYTICS_36_RULES,
    }


@router.get("/api/agent/status", tags=["Quotelytics Agent Specification"])
def api_get_agent_status():
    """
    Returns the current active status and capabilities of the Document-Trained Quotelytics Agent.
    """
    return {
        "status": "active",
        "agent_name": "Quotelytics Autonomous Dynamic Classifier & Pricing Agent",
        "agent_version": "2.0-prod",
        "rules_count": 36,
        "capabilities": [
            "Autonomous Dynamic Sheet Detection (arbitrary line numbers: 90, 140, etc.)",
            "Continuous Row Density Weighting & Currency Prerequisite (Issue 1 fix)",
            "Confusion Gate with Rich Candidate Previews (Scores within 10%)",
            "Authoritative Column Indexing & 2-Letter Province Pairing",
            "Multi-Segment Tariff Matrix Ingestion",
            "Zero-Data-Loss Row Reconciliation Audit (100% accounted)",
            "Prose Surcharge & Accessorial Extraction to Separate Ledger",
            "Human Confirmation Gate (Rules 7, 19)",
        ],
    }


# ==============================================================================
# CANADIAN FSA RESOLVER, FUEL INDICES & REDACTION TOOL
# ==============================================================================

class FuelSettingsPayload(BaseModel):
    active_index_code: str = "OTA_LTL_STANDARD"
    custom_ltl_percent: Optional[float] = None
    use_carrier_sheet_fsc: bool = True
    auto_update_weekly: bool = True


@router.get("/api/geo/resolve-fsa", tags=["Canadian FSA Resolver"])
def api_resolve_fsa(code: str):
    """Resolves a Canadian Postal Code or Forward Sortation Area (FSA) into city, province, zone, and freight hub."""
    return resolve_location(code)


@router.get("/api/geo/resolve-lane", tags=["Canadian FSA Resolver"])
def api_resolve_lane(origin: str, destination: str):
    """Normalizes origin and destination into canonical freight corridor locations."""
    orig, dest, meta = resolve_lane_locations(origin, destination)
    return {
        "origin_canonical": orig,
        "destination_canonical": dest,
        "metadata": meta,
    }


@router.get("/api/fuel-indices/benchmarks", tags=["Fuel Surcharge Index Manager"])
def api_get_fuel_benchmarks():
    """Returns available published Canadian diesel benchmark indices (OTA, FCA, Western, Atlantic)."""
    return {
        "status": "success",
        "benchmarks": get_available_benchmark_indices(),
    }


@router.get("/api/fuel-indices/settings", tags=["Fuel Surcharge Index Manager"])
def api_get_fuel_settings(request: Request):
    """Returns the authenticated broker's current fuel settings and effective LTL surcharge percentage."""
    user = require_user(request)
    return get_tenant_fuel_settings(user["id"])


@router.post("/api/fuel-indices/settings", tags=["Fuel Surcharge Index Manager"])
def api_update_fuel_settings(payload: FuelSettingsPayload, request: Request):
    """Updates the broker's active weekly diesel fuel benchmark index or custom percentage."""
    user = require_user(request)
    updated = update_tenant_fuel_settings(
        user_id=user["id"],
        active_index_code=payload.active_index_code,
        custom_ltl_percent=payload.custom_ltl_percent,
        use_carrier_sheet_fsc=payload.use_carrier_sheet_fsc,
        auto_update_weekly=payload.auto_update_weekly,
    )
    return {"status": "success", "settings": updated}


@router.post("/api/quotelytics/redact-sheet", tags=["Client-Side Redaction Tool"])
async def api_redact_rate_sheet(file: UploadFile = File(...)):
    """
    Scrubs proprietary account numbers, customer identities, rep phone numbers/emails,
    and broker commission notes from an uploaded rate sheet, returning a clean redacted workbook.
    """
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV (.csv) rate sheets are supported.")
    content = await file.read()
    redacted_bytes, audit = redact_rate_sheet_bytes(content, file.filename)

    headers = {
        "Content-Disposition": f'attachment; filename="redacted_{file.filename}"',
        "X-Redactions-Count": str(audit["total_redactions"]),
        "X-Privacy-Status": audit["privacy_status"],
    }
    return Response(
        content=redacted_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/api/quotelytics/preview-redaction", tags=["Client-Side Redaction Tool"])
async def api_preview_rate_sheet_redaction(file: UploadFile = File(...)):
    """Previews sensitive data elements detected in the rate sheet without altering the original file."""
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV (.csv) rate sheets are supported.")
    content = await file.read()
    _, audit = redact_rate_sheet_bytes(content, file.filename)
    return {"status": "success", "audit": audit}
