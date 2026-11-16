from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class Mode(str, Enum):
    weight = "weight"
    skid = "skid"


class JobStatus(str, Enum):
    uploaded = "uploaded"
    parsed = "parsed"
    needs_mapping = "needs_mapping"   # user must act
    ready = "ready"                   # mapping complete (auto or confirmed)
    processing = "processing"         # running quote agent
    done = "done"
    failed = "failed"
    expired = "expired"


class FieldGuess(BaseModel):
    field: str
    columns: List[int]
    confidence: float
    needs_confirmation: bool
    break_values: Optional[List[float]] = None


class JobConflict(BaseModel):
    field: str
    columns: List[int]
    reason: str


class JobState(BaseModel):
    job_id: str
    status: JobStatus
    header_row: Optional[int] = None
    sheet_name: Optional[str] = None
    mode: Optional[Mode] = None
    weight_unit: Optional[str] = None
    guesses: List[FieldGuess] = []
    conflicts: List[JobConflict] = []
    unresolved: List[str] = []
    suggestions: Dict[str, int] = {}
    issues: List[str] = []
    preview: List[List[str]] = []
    column_count: int = 0
    mapping_source: Optional[str] = None
    saved_mapping_suggestion: Optional[Dict[str, Any]] = None
    expires_at: Optional[float] = None


class CompoundLocationMapping(BaseModel):
    city_column: int = Field(ge=0)
    region_column: Optional[int] = Field(default=None, ge=0)
    postal_fsa_column: Optional[int] = Field(default=None, ge=0)


class SkidTierMapping(BaseModel):
    column: int = Field(ge=0)
    skid_range: str = "1"
    min_units: float = Field(default=1.0, ge=1.0)
    max_units: float = Field(default=1.0, ge=1.0)
    rate_type: str = "PER_SKID"


class MappingRequest(BaseModel):
    header_row: int = Field(ge=0)
    header_row_confirmed: bool = False
    sheet_name: Optional[str] = None
    table_segment_id: Optional[str] = None
    mode: Mode = Mode.weight
    rate_basis: str = "PER_CWT"
    currency: Optional[str] = None
    weight_unit: Optional[str] = None
    origin_type: str = "column"
    origin: Optional[Any] = None
    fixed_origin_value: Optional[str] = None
    destination: Optional[Any] = None
    rate_columns: List[int] = []
    base_cost_column: Optional[int] = None
    user_break_weights: Optional[Dict[Any, float]] = None
    max_skid_capacity: Optional[int] = None
    skid_tiers: Optional[List[SkidTierMapping]] = None
    skid_count_column: Optional[int] = None
    allow_deficit_rating: Optional[bool] = None
    carrier_max_weight: Optional[float] = None
    acknowledged_finding_ids: List[str] = []
    override_notes: Optional[Dict[str, str]] = None
    remember_mapping: bool = False


class DryRunRequest(BaseModel):
    seq_id: int = 1
    mapping: Dict[str, Any]
    selected_row_index: Optional[int] = None


class SavedMappingResponse(BaseModel):
    id: str
    sheet_name: Optional[str] = None
    column_count: int
    header_names: List[str]
    mapping: Dict[str, Any]
    created_at: float


class Suggestions(BaseModel):
    mapping: Dict[str, int]
