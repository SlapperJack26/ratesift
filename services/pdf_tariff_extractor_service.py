"""
services/pdf_tariff_extractor_service.py
========================================
Deterministic PDF Carrier Rate Sheet Table Extractor.

Extracts structured tabular rate rows, metadata (Carrier, Currency, Weight Unit, Effective/Expiry Dates),
and accessorial footnotes from native PDF carrier rate sheets (.pdf) and converts them into
canonical CSV table rows for `QuotelyticsExtractor` without any LLM guessing.
"""

import csv
import io
import re
import zlib
from typing import List, Tuple


def _extract_raw_text_from_pdf_bytes(pdf_bytes: bytes) -> List[str]:
    """
    Extracts text lines page-by-page from a PDF byte stream.
    1. Uses `pypdf` / `PyPDF2` / `pdfplumber` if installed in the environment.
    2. Falls back to a built-in deterministic PDF stream parser (supporting raw and FlateDecode streams)
       so extraction succeeds with zero external dependencies.
    """
    # Try pypdf / PyPDF2 first if available
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
            reader = mod.PdfReader(io.BytesIO(pdf_bytes))
            pages_text: List[str] = []
            for page in reader.pages:
                txt = page.extract_text() or ""
                if txt.strip():
                    pages_text.extend(txt.splitlines())
            if pages_text:
                return pages_text
        except Exception:
            pass

    # Built-in deterministic PDF stream & text-operator parser
    lines: List[str] = []

    # 1. Inspect all stream ... endstream blocks (decompressing FlateDecode if needed)
    stream_pattern = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    chunks: List[bytes] = []
    for m in stream_pattern.finditer(pdf_bytes):
        raw_stream = m.group(1)
        try:
            decompressed = zlib.decompress(raw_stream)
            chunks.append(decompressed)
        except Exception:
            chunks.append(raw_stream)

    if not chunks:
        chunks.append(pdf_bytes)

    for chunk in chunks:
        text_chunk = chunk.decode("latin-1", errors="ignore")
        # Extract PDF literal strings inside parentheses (...) used in Tj / TJ operators
        literal_matches = re.findall(r"\(([^()]*)\)\s*(?:Tj|'|\"|\])?", text_chunk)
        if literal_matches:
            for lit in literal_matches:
                cleaned = (
                    lit.replace(r"\(", "(")
                    .replace(r"\)", ")")
                    .replace(r"\n", "\n")
                    .replace(r"\r", "\n")
                )
                for sub_line in cleaned.splitlines():
                    if sub_line.strip():
                        lines.append(sub_line.strip())
        else:
            # Plain text lines embedded in uncompressed PDF streams
            for raw_ln in text_chunk.splitlines():
                s = raw_ln.strip()
                if s and not s.startswith(("%PDF", "obj", "endobj", "xref", "trailer", "startxref", "<<", ">>")):
                    lines.append(s)

    return lines


def _split_pdf_table_line_into_cells(line: str) -> List[str]:
    """
    Splits a single PDF table line into columns:
    - If comma-separated or pipe-separated or tab-separated, splits on that delimiter.
    - If whitespace-aligned (e.g. 'M5V   T2P   125.00   42.50   38.00   32.00'), splits on 2+ spaces or whitespace tokens.
    """
    s = line.strip()
    if "," in s and len(s.split(",")) >= 2:
        return [c.strip() for c in next(csv.reader([s]))]
    if "|" in s and len(s.split("|")) >= 2:
        return [c.strip() for c in s.strip("|").split("|")]
    if "\t" in s:
        return [c.strip() for c in s.split("\t") if c.strip()]
    if re.search(r"\s{2,}", s):
        return [c.strip() for c in re.split(r"\s{2,}", s) if c.strip()]

    # Single-space separated rate matrix row e.g. "M5V T2P 120.00 40.00 35.00" or "Origin Destination Min L5C M5C"
    tokens = s.split()
    if len(tokens) >= 4:
        return tokens
    if len(tokens) == 2 and tokens[0].lower() in ("carrier", "currency", "tariff", "mode"):
        return tokens
    return [s]


def convert_pdf_tariff_bytes_to_csv_text(pdf_bytes: bytes) -> str:
    """
    Converts a native PDF carrier rate sheet (.pdf) into normalized CSV text
    suitable for deterministic parsing by `QuotelyticsExtractor._extract_csv()`.
    """
    if not pdf_bytes or not pdf_bytes.lstrip().startswith(b"%PDF"):
        raise ValueError("Invalid PDF file: missing %PDF header signature.")

    raw_lines = _extract_raw_text_from_pdf_bytes(pdf_bytes)
    if not raw_lines:
        raise ValueError("Could not extract any readable text or table rows from PDF rate sheet.")

    out_buf = io.StringIO()
    writer = csv.writer(out_buf, lineterminator="\n")

    for ln in raw_lines:
        cells = _split_pdf_table_line_into_cells(ln)
        if cells and any(c.strip() for c in cells):
            writer.writerow(cells)

    csv_text = out_buf.getvalue()
    if not csv_text.strip():
        raise ValueError("PDF rate sheet contained no extractable rate rows.")
    return csv_text
