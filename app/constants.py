"""
app/constants.py
Central brand constants, internal storage paths, and standardized error codes for Quotelytics.
Rule: Zero magic strings for branding, paths, or localization keys.
"""

# User-Facing Brand Display
PLATFORM_DISPLAY_NAME = "Quotelytics"
ENGINE_DISPLAY_NAME = "Quotelytics LTL Engine"

# Internal System & Storage Identifiers (Immutable)
STORAGE_DIR_NAME = "quotelytics"
DB_FILE_NAME = "shipflow.db"

# Standardized Error Codes for UI Localization and API Responses
ERR_CODES = {
    "E_PARCEL_NOT_SUPPORTED": "E_PARCEL_NOT_SUPPORTED",
    "E_BLOCKER_VIOLATION": "E_BLOCKER_VIOLATION",
    "E_UNACKNOWLEDGED_WARNING": "E_UNACKNOWLEDGED_WARNING",
    "E_INSUFFICIENT_DISK_FOR_MIGRATION": "E_INSUFFICIENT_DISK_FOR_MIGRATION",
    "E_CSRF_INVALID": "E_CSRF_INVALID",
    "E_DRY_RUN_TIMEOUT": "E_DRY_RUN_TIMEOUT",
    "E_RATE_LIMIT_EXCEEDED": "E_RATE_LIMIT_EXCEEDED",
}

# Finding Severity Constants
SEVERITY_BLOCKER = "BLOCKER"
SEVERITY_WARNING = "WARNING"
