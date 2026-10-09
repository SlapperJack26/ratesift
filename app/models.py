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


class MappingRequest(BaseModel):
    header_row: int = Field(ge=0)
    sheet_name: Optional[str] = None
    mode: Mode
    origin: int = Field(ge=0)
    destination: int = Field(ge=0)
    rate_columns: List[int] = Field(min_length=1)
    skid_count_column: Optional[int] = Field(default=None, ge=0)
    weight_unit: Optional[str] = Field(default=None, pattern="^(lb|kg)$")
    remember_mapping: bool = False

    @model_validator(mode="after")
    def _mode_needs_unit(self):
        if self.mode == Mode.weight and not self.weight_unit:
            raise ValueError("weight_unit is required when mode is 'weight'")
        return self


class SavedMappingResponse(BaseModel):
    id: str
    sheet_name: Optional[str] = None
    column_count: int
    header_names: List[str]
    mapping: Dict[str, Any]
    created_at: float


class Suggestions(BaseModel):
    mapping: Dict[str, int]
