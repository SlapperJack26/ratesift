"""
Quotelytics Autonomous Freight Rating Agent & Dynamic Sheet Ingestion Package
Provides deterministic rating, 36-rule compliance auditing, 7-category cell classification,
dynamic multi-segment sheet detection, and zero-data-loss row reconciliation.
"""
from .rate_agent import QuotelyticsAgent
from .dynamic_sheet_detector import (
    DynamicSheetDetector,
    clean_cell,
    is_numeric,
    is_rate_numeric,
    is_prose_cell,
    extract_structured_surcharge,
    ALL_PROV_STATE_CODES
)
from .rules_spec import (
    QUOTELYTICS_36_RULES,
    QUOTELYTICS_32_RULES,
    RuleComplianceAuditor
)
from .agent_prompts import AGENT_TRAINING_VARIANTS

__all__ = [
    "QuotelyticsAgent",
    "DynamicSheetDetector",
    "QUOTELYTICS_36_RULES",
    "QUOTELYTICS_32_RULES",
    "RuleComplianceAuditor",
    "clean_cell",
    "is_numeric",
    "is_rate_numeric",
    "is_prose_cell",
    "extract_structured_surcharge",
    "ALL_PROV_STATE_CODES",
    "AGENT_TRAINING_VARIANTS"
]
