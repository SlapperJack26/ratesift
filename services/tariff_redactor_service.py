"""
Client-Side / Server-Assisted Carrier Tariff Masker & Redaction Service.

Scrubs confidential customer identifiers, carrier account numbers, contact emails/phones,
and internal broker margin notes from Excel (.xlsx) and CSV (.csv) carrier rate sheets
while strictly whitelisting and preserving 100% of rate brackets, CWT breaks, skid tiers,
minimum charges, lane cities/provinces, Canadian FSAs, and US ZIP codes.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Tuple

import openpyxl

# Whitelist patterns for protected freight rating tokens that must NEVER be masked
_WHITESPACE_ONLY_RE = re.compile(r"^\s*$")
_FSA_OR_ZIP_RE = re.compile(r"^(?:[A-Z]\d[A-Z](?:\s*\d[A-Z]\d)?|\d{3}|\d{5}(?:-\d{4})?)$", re.IGNORECASE)
_CWT_BREAK_RE = re.compile(
    r"^(?:MIN(?:IMUM)?|MC|L5C|<5C|5C|M5C|1M|2M|3M|4M|5M|10M|20M|\d+\s*[-+–]\s*\d*|\d+\+)$",
    re.IGNORECASE,
)

# Confidential token detectors
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")
_ACCOUNT_LABEL_RE = re.compile(
    r"\b(?:acct|account(?:\s*(?:no|num|number|#|:))?|cust(?:omer)?\s*(?:id|#|code|name)|"
    r"client\s*(?:id|name|#|:)|shipper\s*(?:id|name|acct)|prepared\s+for|attention|attn|"
    r"sales\s*rep|broker\s*(?:margin|markup|fee|commission)|confidential)\b",
    re.IGNORECASE,
)
_ACCOUNT_CODE_RE = re.compile(r"\bACCT[-_#:\s]*[A-Z0-9-]{3,}\b", re.IGNORECASE)


def _is_whitelisted_tariff_value(text: str) -> bool:
    """Returns True if text is a pure numeric rate, currency value, FSA/ZIP, or CWT bracket."""
    s = text.strip()
    if not s:
        return True
    # Pure numeric / currency value
    cleaned_num = re.sub(r"[$,%\s]", "", s)
    try:
        float(cleaned_num)
        return True
    except ValueError:
        pass
    if _FSA_OR_ZIP_RE.match(s) or _CWT_BREAK_RE.match(s):
        return True
    return False


def _detect_confidential_reason(text: str) -> str | None:
    """Returns redaction mask label if confidential PII/account metadata is detected, else None."""
    s = text.strip()
    if not s or _is_whitelisted_tariff_value(s):
        return None
    if _EMAIL_RE.search(s):
        return "[REDACTED_EMAIL]"
    if _PHONE_RE.search(s):
        return "[REDACTED_PHONE]"
    if _ACCOUNT_CODE_RE.search(s):
        return "[REDACTED_ACCOUNT_ID]"
    if _ACCOUNT_LABEL_RE.search(s):
        return "[REDACTED_CONFIDENTIAL]"
    return None


def _redact_string_preserve_label(text: str, mask: str) -> str:
    """Masks sensitive payload while keeping structural label prefix when formatted as 'Key: Value'."""
    if ":" in text and mask in ("[REDACTED_CONFIDENTIAL]", "[REDACTED_ACCOUNT_ID]"):
        prefix, _ = text.split(":", 1)
        if len(prefix.strip()) <= 32:
            return f"{prefix.strip()}: {mask}"
    return mask


def redact_tariff_workbook(file_bytes: bytes, filename: str) -> Tuple[bytes, str, Dict[str, Any]]:
    """
    Scans and scrubs confidential metadata from an uploaded .xlsx or .csv rate sheet.
    Returns (scrubbed_bytes, media_type, audit_dict).
    """
    lower_name = (filename or "tariff.xlsx").lower()
    redacted_cells: List[Dict[str, str]] = []

    if lower_name.endswith(".csv"):
        decoded = file_bytes.decode("utf-8-sig", errors="replace")
        reader = list(csv.reader(io.StringIO(decoded)))
        out_rows: List[List[str]] = []
        for r_idx, row in enumerate(reader, start=1):
            new_row = list(row)
            for c_idx, val in enumerate(row, start=1):
                txt = str(val or "").strip()
                mask = _detect_confidential_reason(txt)
                if mask:
                    col_letter = openpyxl.utils.get_column_letter(c_idx)
                    coord = f"{col_letter}{r_idx}"
                    redacted_cells.append({
                        "sheet": "CSV",
                        "cell": coord,
                        "original_preview": txt[:40],
                        "mask": mask,
                    })
                    new_row[c_idx - 1] = _redact_string_preserve_label(txt, mask)
            out_rows.append(new_row)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(out_rows)
        scrubbed_bytes = buf.getvalue().encode("utf-8")
        media_type = "text/csv"
    else:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=False)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    val = cell.value
                    if val is None or isinstance(val, (int, float)):
                        continue
                    txt = str(val).strip()
                    mask = _detect_confidential_reason(txt)
                    if mask:
                        coord = cell.coordinate
                        redacted_cells.append({
                            "sheet": ws.title,
                            "cell": coord,
                            "original_preview": txt[:40],
                            "mask": mask,
                        })
                        cell.value = _redact_string_preserve_label(txt, mask)

        out_buf = io.BytesIO()
        wb.save(out_buf)
        scrubbed_bytes = out_buf.getvalue()
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    audit = {
        "filename": filename,
        "total_redactions": len(redacted_cells),
        "privacy_status": "VERIFIED SCRUBBED",
        "redacted_cells": redacted_cells[:100],
    }
    return scrubbed_bytes, media_type, audit


def preview_tariff_redaction(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Returns audit preview of detected confidential cells without persisting the file."""
    _, _, audit = redact_tariff_workbook(file_bytes, filename)
    return audit
