"""
services/rate_redactor_service.py
=================================
RateSift Client-Side Rate Sheet Masker & Redaction Service.

Safeguards broker confidentiality by detecting and scrubbing proprietary account numbers,
client identities, internal contract codes, sales contact details, and commission notes from
freight rate sheets (.xlsx, .csv) prior to engine ingestion.
"""

import io
import re
from typing import Dict, Any, List, Tuple
import openpyxl

# Regular expression patterns for confidential freight data
PATTERNS = {
    "account_number": [
        r"(?i)\b(?:acct|account|acc|billing|shipper)\s*(?:no|num|number|#)?\s*[:=\-]?\s*([A-Z0-9\-]{5,15})\b",
        r"(?i)\b(?:cust(?:omer)?\s*(?:id|no|#)?)\s*[:=\-]?\s*([A-Z0-9\-]{5,15})\b",
        r"\b\d{6,10}\b"  # 6-10 digit standalone numbers that aren't zip codes or weights
    ],
    "email": [
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    ],
    "phone": [
        r"(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
    ],
    "contract_id": [
        r"(?i)\b(?:contract|agreement|tariff\s*id|deal)\s*(?:#|no|id)?\s*[:=\-]?\s*([A-Z0-9\-]{6,20})\b"
    ],
    "broker_margin": [
        r"(?i)\b(?:\d+(?:\.\d+)?%?\s*)?(?:margin|markup|commission|broker\s*cut)(?:\s*[:=\-]?\s*\$?\d+(?:\.\d+)?%?)?\b"
    ]
}

# Sensitive header labels that trigger full column/cell value masking
SENSITIVE_LABELS = {
    "ACCOUNT", "ACCOUNT #", "ACCT NO", "ACCT NUMBER", "CUSTOMER", "CUSTOMER NAME",
    "CLIENT", "CLIENT NAME", "SHIPPER NAME", "SALES REP", "ACCOUNT REP",
    "MARGIN", "COMMISSION", "INTERNAL NOTES", "PROPRIETARY", "CONTACT PHONE", "REP EMAIL"
}

def is_postal_code_or_weight(text: str) -> bool:
    """Ensures postal codes (M5V 2T6) or weights (e.g. 500, 1000, 10000) are NEVER redacted."""
    text_clean = text.strip().upper()
    # Canadian postal code pattern
    if re.search(r"\b[A-Z]\d[A-Z]\s*\d[A-Z]\d\b", text_clean):
        return True
    # US Zip code pattern
    if re.match(r"^\d{5}(?:-\d{4})?$", text_clean):
        return True
    # Weight number
    try:
        val = float(text_clean.replace(",", ""))
        if val in [0, 100, 500, 1000, 2000, 5000, 10000, 20000, 30000, 40000]:
            return True
    except ValueError:
        pass
    return False

def redact_rate_sheet_bytes(file_bytes: bytes, filename: str) -> Tuple[bytes, Dict[str, Any]]:
    """
    Scans and redacts an Excel rate sheet workbook in-memory.
    Returns (redacted_xlsx_bytes, audit_summary).
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    redacted_cells = []
    total_cells_scanned = 0

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            prev_label = None
            for cell in row:
                total_cells_scanned += 1
                val = cell.value
                if val is None:
                    prev_label = None
                    continue

                val_str = str(val).strip()
                if not val_str:
                    prev_label = None
                    continue

                # Protect legitimate freight data
                if is_postal_code_or_weight(val_str):
                    prev_label = None
                    continue

                masked = False
                replacement = val_str

                # Check sensitive header context
                is_curr_label = False
                matched_label = None
                for sl in SENSITIVE_LABELS:
                    if sl in val_str.upper() and len(val_str) < 35:
                        is_curr_label = True
                        matched_label = sl
                        break

                # 1. Emails
                for pat in PATTERNS["email"]:
                    if re.search(pat, replacement):
                        replacement = re.sub(pat, "[REDACTED_EMAIL]", replacement)
                        masked = True

                # 2. Phone Numbers
                for pat in PATTERNS["phone"]:
                    if re.search(pat, replacement):
                        replacement = re.sub(pat, "[REDACTED_PHONE]", replacement)
                        masked = True

                # 3. Contract IDs
                for pat in PATTERNS["contract_id"]:
                    if re.search(pat, replacement):
                        replacement = re.sub(pat, "[REDACTED_CONTRACT_ID]", replacement)
                        masked = True

                # 4. Account Numbers
                for pat in PATTERNS["account_number"]:
                    match = re.search(pat, replacement)
                    if match and not is_postal_code_or_weight(match.group(0)):
                        replacement = re.sub(pat, "[REDACTED_ACCOUNT]", replacement)
                        masked = True

                # 5. Broker Margin Notes
                for pat in PATTERNS["broker_margin"]:
                    if re.search(pat, replacement):
                        replacement = re.sub(pat, "[REDACTED_MARGIN]", replacement)
                        masked = True

                # 6. Fallback: If preceding adjacent cell was a sensitive header, mask remaining value
                if not masked and prev_label and not is_curr_label:
                    if any(k in prev_label for k in ["CUSTOMER", "CLIENT", "SHIPPER"]):
                        replacement = "[REDACTED_CUSTOMER]"
                        masked = True
                    elif any(k in prev_label for k in ["ACCOUNT", "ACCT"]):
                        replacement = "[REDACTED_ACCOUNT]"
                        masked = True
                    elif any(k in prev_label for k in ["MARGIN", "COMMISSION"]):
                        replacement = "[REDACTED_MARGIN]"
                        masked = True
                    elif any(k in prev_label for k in ["REP", "CONTACT"]):
                        replacement = "[REDACTED_CONTACT]"
                        masked = True

                if masked:
                    cell.value = replacement
                    redacted_cells.append({
                        "sheet": sheet_name,
                        "cell": cell.coordinate,
                        "original_type": "Sensitive Data",
                        "mask": replacement
                    })

                prev_label = matched_label if is_curr_label else None

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    redacted_bytes = out.getvalue()

    summary = {
        "filename": filename,
        "total_cells_scanned": total_cells_scanned,
        "total_redactions": len(redacted_cells),
        "redacted_cells": redacted_cells[:50],  # sample coordinates
        "is_scrubbed": len(redacted_cells) > 0,
        "privacy_status": "VERIFIED_SCRUBBED" if len(redacted_cells) > 0 else "CLEAN_NO_CONFIDENTIAL_PATTERNS_DETECTED"
    }

    return redacted_bytes, summary
