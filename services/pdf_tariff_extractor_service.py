"""
services/pdf_tariff_extractor_service.py
========================================
Universal Coordinate-Aware PDF Carrier Rate Sheet Extractor & Normalizer.

Supports PDF rate sheets from ANY carrier across five archetypes:
- Archetype A (ltl_lane_weight): Standard Origin/Destination x Weight-Break matrices
- Archetype B (skid_matrix): Skid/Pallet tier columns or Skid Count + Rate rows
- Archetype C (fixed_origin_outbound): Preamble origin banner + Destination grid
- Archetype D (transposed_weight_zone): Inverted Weight-in-Rows x Zone/Dest-in-Columns
  matrices (stitched across vertical/horizontal page splits and transposed)
- Archetype E (reference_notes): Zone Indexes, FSA charts, Accessorials & Rules

Also guarantees descriptive, unambiguous column titles on every extracted table
so FailsafeModal and Excel Re-Formatter never show unlabeled bare numbers.
"""

import csv
import io
import math
import re
import zlib
from typing import Any, Dict, List, Optional, Tuple

from services.break_header_parser import (
    detect_unit_in_header,
    is_numeric_range_header,
    parse_break_header,
    parse_skid_break_from_keywords,
)

# ---------------------------------------------------------------------------
# PDF String Decoding & Content Stream (X, Y) Positioning Engine
# ---------------------------------------------------------------------------

_MONEY_RE = re.compile(r"^\$?\s*-?\d[\d,]*(?:\.\d+)?$")
_ZONE_WORD_RE = re.compile(r"\bzones?\b", re.I)
_MIN_CHARGE_RE = re.compile(r"\b(?:min(?:imum)?(?:\s*charge)?|m\.?c\.?)\b", re.I)
_OVERAGE_ROW_RE = re.compile(
    r"^\s*(\d[\d,]*)\s*(?:lbs?|kgs?|#)?\s*(?:or\s+more|and\s+over|\+|plus)\b",
    re.I,
)
_ORIGIN_PREAMBLE_RE = re.compile(
    r"(?:shipment\s+origin|outbound\s+(?:rates?\s+)?from|originat(?:ing|e)\s+(?:at|from)|rates?\s+from|origin)\s*[:\-]\s*([^\n|;]{2,80})",
    re.I,
)


def _clean_text(text: str) -> str:
    if not text:
        return ""
    s = (
        text.replace("\u00a0", " ")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    # Remove lingering (R) / TM symbols or control noise
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _decode_pdf_literal_bytes(raw: bytes) -> str:
    """Decodes PDF literal string bytes including octal escapes and WinAnsi punctuation."""
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        b = raw[i]
        if b == 92 and i + 1 < n:  # backslash escape
            nxt = raw[i + 1]
            if nxt == 110:  # \n
                out.append(10)
                i += 2
            elif nxt == 114:  # \r
                out.append(13)
                i += 2
            elif nxt == 116:  # \t
                out.append(9)
                i += 2
            elif nxt == 98:  # \b
                out.append(8)
                i += 2
            elif nxt == 102:  # \f
                out.append(12)
                i += 2
            elif nxt in (40, 41, 92):  # \( \) \\
                out.append(nxt)
                i += 2
            elif nxt in (10, 13):  # line continuation \<CR/LF>
                i += 2
                if nxt == 13 and i < n and raw[i] == 10:
                    i += 1
            elif 48 <= nxt <= 55:  # octal \ddd
                oct_digits = bytes([nxt])
                j = i + 2
                while j < n and j < i + 4 and 48 <= raw[j] <= 55:
                    oct_digits += bytes([raw[j]])
                    j += 1
                val = int(oct_digits, 8)
                if val in (0o226, 0o227):
                    out.extend(b"-")
                elif val in (0o221, 0o222):
                    out.extend(b"'")
                elif val in (0o223, 0o224):
                    out.extend(b'"')
                elif val in (0o256, 0o231):
                    pass  # ® / ™ noise
                elif val == 0o240:
                    out.append(32)
                else:
                    out.append(val)
                i = j
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(b)
            i += 1
    return out.decode("latin-1", errors="ignore")


def _decode_pdf_hex_bytes(hex_raw: bytes) -> str:
    cleaned = re.sub(rb"[^0-9A-Fa-f]", b"", hex_raw)
    if not cleaned:
        return ""
    if len(cleaned) % 2 == 1:
        cleaned += b"0"
    try:
        raw = bytes.fromhex(cleaned.decode("ascii"))
    except Exception:
        return ""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="ignore")
    # Filter unmapped CID binary garbage when not printable ASCII/Latin-1
    printable = sum(1 for ch in raw if 32 <= ch <= 126 or ch >= 160)
    if raw and printable / len(raw) < 0.65:
        return ""
    return raw.decode("latin-1", errors="ignore")


def _mul_mat(m1: List[float], m2: List[float]) -> List[float]:
    """Multiplies two 3x3 affine PDF matrices [a, b, c, d, e, f]."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return [
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    ]


def _tokenize_content_stream(stream_bytes: bytes) -> List[Tuple[str, Any]]:
    """Lexes a decompressed PDF content stream into typed tokens for positioning."""
    tokens: List[Tuple[str, Any]] = []
    n = len(stream_bytes)
    i = 0

    while i < n:
        ch = stream_bytes[i]
        # Skip whitespace
        if ch in (9, 10, 12, 13, 32):
            i += 1
            continue
        # Comment
        if ch == 37:  # %
            while i < n and stream_bytes[i] not in (10, 13):
                i += 1
            continue
        # Dictionary << ... >> (handle nested <<...>> and inner <hex> strings like << /ActualText<FEFF0009> >>)
        if ch == 60 and i + 1 < n and stream_bytes[i + 1] == 60:
            depth = 1
            i += 2
            while i < n and depth > 0:
                if stream_bytes[i] == 40:  # inner (...) literal
                    i += 1
                    ld = 1
                    while i < n and ld > 0:
                        if stream_bytes[i] == 92:
                            i += 2
                            continue
                        if stream_bytes[i] == 40:
                            ld += 1
                        elif stream_bytes[i] == 41:
                            ld -= 1
                        i += 1
                elif stream_bytes[i] == 60 and i + 1 < n and stream_bytes[i + 1] == 60:
                    depth += 1
                    i += 2
                elif stream_bytes[i] == 60:  # single <hex> inside dict
                    i += 1
                    while i < n and stream_bytes[i] != 62:
                        i += 1
                    if i < n:
                        i += 1
                elif stream_bytes[i] == 62 and i + 1 < n and stream_bytes[i + 1] == 62:
                    depth -= 1
                    i += 2
                else:
                    i += 1
            tokens.append(("dict", None))
            continue
        # Stray unmatched delimiter guard (e.g. '>' or ')')
        if ch in (62, 41):
            i += 1
            continue
        # Hex string <...>
        if ch == 60:
            j = i + 1
            while j < n and stream_bytes[j] != 62:
                j += 1
            tokens.append(("hex", stream_bytes[i + 1 : j]))
            i = j + 1
            continue
        # Literal string (...)
        if ch == 40:
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                c = stream_bytes[j]
                if c == 92:  # backslash
                    j += 2
                    continue
                if c == 40:
                    depth += 1
                elif c == 41:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            tokens.append(("str", stream_bytes[i + 1 : j]))
            i = j + 1
            continue
        # Array markers [ ... ]
        if ch == 91:
            tokens.append(("[", "["))
            i += 1
            continue
        if ch == 93:
            tokens.append(("]", "]"))
            i += 1
            continue
        # Name /...
        if ch == 47:
            j = i + 1
            while j < n and stream_bytes[j] not in (9, 10, 12, 13, 32, 47, 60, 62, 91, 93, 40, 41):
                j += 1
            tokens.append(("name", stream_bytes[i + 1 : j].decode("latin-1", errors="ignore")))
            i = j
            continue

        # Number or keyword operator
        j = i
        while j < n and stream_bytes[j] not in (9, 10, 12, 13, 32, 47, 60, 62, 91, 93, 40, 41, 37):
            j += 1
        if j == i:
            i += 1
            continue
        word = stream_bytes[i:j].decode("latin-1", errors="ignore")
        if word:
            try:
                if any(c in word for c in (".",)):
                    tokens.append(("num", float(word)))
                elif word[0].isdigit() or (word[0] in ("-", "+") and len(word) > 1 and (word[1].isdigit() or word[1] == ".")):
                    tokens.append(("num", float(word)))
                else:
                    tokens.append(("op", word))
            except ValueError:
                tokens.append(("op", word))
        i = j

    return tokens


def _parse_stream_positioned_tokens(stream_bytes: bytes, page_height: float = 792.0) -> List[Dict[str, Any]]:
    """
    Executes PDF text positioning operators (BT/ET, cm, q/Q, Tm, Td, TD, TL, T*, Tf, Tj, TJ)
    and returns visual top-down tokens [{x, top, x1, text, font_size}].
    """
    toks = _tokenize_content_stream(stream_bytes)
    out: List[Dict[str, Any]] = []

    ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    ctm_stack: List[List[float]] = []
    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    tlm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    tl = 0.0
    tc = 0.0
    tw = 0.0
    font_size = 10.0

    operands: List[Tuple[str, Any]] = []
    in_array = False
    arr_items: List[Tuple[str, Any]] = []

    def _emit_run(text_raw: str, x_shift_text_units: float = 0.0) -> None:
        nonlocal tm
        if x_shift_text_units:
            tm[4] += x_shift_text_units * tm[0]
            tm[5] += x_shift_text_units * tm[1]
        cleaned = _clean_text(text_raw)
        n_spaces = text_raw.count(" ")
        adv_len = max(len(cleaned), len(text_raw))
        base_adv = (adv_len * font_size * 0.48) + (adv_len * tc) + (n_spaces * tw)
        if cleaned:
            eff_scale = math.hypot(tm[0], tm[1]) or 1.0
            eff_size = max(4.0, abs(font_size * eff_scale))
            vx = ctm[0] * tm[4] + ctm[2] * tm[5] + ctm[4]
            vy = ctm[1] * tm[4] + ctm[3] * tm[5] + ctm[5]
            top = page_height - vy
            est_width = max(2.0, len(cleaned) * eff_size * 0.48)
            out.append({
                "x": vx,
                "top": top,
                "x1": vx + est_width,
                "text": cleaned,
                "font_size": eff_size,
            })
        # Always advance text matrix even for pure whitespace / Tw tab spacing runs
        if adv_len > 0 or tw != 0.0:
            tm[4] += base_adv * tm[0]
            tm[5] += base_adv * tm[1]

    for kind, val in toks:
        if kind == "[":
            in_array = True
            arr_items = []
            continue
        if kind == "]":
            in_array = False
            operands.append(("arr", arr_items))
            arr_items = []
            continue
        if in_array:
            arr_items.append((kind, val))
            continue

        if kind != "op":
            operands.append((kind, val))
            continue

        op = val
        if op == "q":
            ctm_stack.append(list(ctm))
        elif op == "Q":
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == "cm" and len(operands) >= 6:
            nums = [float(o[1]) for o in operands[-6:] if o[0] == "num"]
            if len(nums) == 6:
                ctm = _mul_mat(nums, ctm)
        elif op == "BT":
            tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            tlm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            tl = 0.0
            tc = 0.0
            tw = 0.0
        elif op == "ET":
            pass
        elif op == "Tc" and operands:
            if operands[-1][0] == "num":
                tc = float(operands[-1][1])
        elif op == "Tw" and operands:
            if operands[-1][0] == "num":
                tw = float(operands[-1][1])
        elif op == "Tf" and len(operands) >= 2:
            if operands[-1][0] == "num":
                font_size = float(operands[-1][1])
        elif op == "TL" and len(operands) >= 1:
            if operands[-1][0] == "num":
                tl = float(operands[-1][1])
        elif op == "Tm" and len(operands) >= 6:
            nums = [float(o[1]) for o in operands[-6:] if o[0] == "num"]
            if len(nums) == 6:
                tm = list(nums)
                tlm = list(nums)
        elif op in ("Td", "TD") and len(operands) >= 2:
            nums = [float(o[1]) for o in operands[-2:] if o[0] == "num"]
            if len(nums) == 2:
                tx, ty = nums
                if op == "TD":
                    tl = -ty
                new_e = tlm[4] + tx * tlm[0] + ty * tlm[2]
                new_f = tlm[5] + tx * tlm[1] + ty * tlm[3]
                tlm[4] = new_e
                tlm[5] = new_f
                tm = list(tlm)
        elif op == "T*":
            new_e = tlm[4] + (-tl) * tlm[2]
            new_f = tlm[5] + (-tl) * tlm[3]
            tlm[4] = new_e
            tlm[5] = new_f
            tm = list(tlm)
        elif op in ("Tj", "'", '"') and operands:
            if op in ("'", '"'):
                new_e = tlm[4] + (-tl) * tlm[2]
                new_f = tlm[5] + (-tl) * tlm[3]
                tlm[4] = new_e
                tlm[5] = new_f
                tm = list(tlm)
            last_k, last_v = operands[-1]
            if last_k == "str":
                _emit_run(_decode_pdf_literal_bytes(last_v))
            elif last_k == "hex":
                _emit_run(_decode_pdf_hex_bytes(last_v))
        elif op == "TJ" and operands and operands[-1][0] == "arr":
            buf: List[str] = []
            for ak, av in operands[-1][1]:
                if ak == "str":
                    buf.append(_decode_pdf_literal_bytes(av))
                elif ak == "hex":
                    buf.append(_decode_pdf_hex_bytes(av))
                elif ak == "num":
                    kern = float(av)
                    if kern < -350.0:
                        if buf:
                            _emit_run("".join(buf))
                            buf = []
                        tm[4] += (-kern / 1000.0) * font_size * tm[0]
                    elif kern < -120.0:
                        buf.append(" ")
            if buf:
                _emit_run("".join(buf))

        operands.clear()

    return out


def _extract_pages_pure_python(pdf_bytes: bytes) -> List[List[Dict[str, Any]]]:
    """
    Pure-Python fallback extractor that walks Catalog -> Pages -> Kids in document
    page order and decodes every page content stream with (X, Y) positioning.
    """
    objs: Dict[Tuple[int, int], bytes] = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b(.*?)endobj", pdf_bytes, re.DOTALL):
        key = (int(m.group(1)), int(m.group(2)))
        objs[key] = m.group(3)

    # Also decompress any /ObjStm object streams (PDF 1.5+)
    for body in list(objs.values()):
        if b"/ObjStm" in body:
            sm = re.search(rb"stream[\r\n]+(.*?)[\r\n]+endstream", body, re.DOTALL)
            first_m = re.search(rb"/First\s+(\d+)", body)
            n_m = re.search(rb"/N\s+(\d+)", body)
            if sm and first_m and n_m:
                try:
                    raw = zlib.decompress(sm.group(1))
                    first = int(first_m.group(1))
                    n_cnt = int(n_m.group(1))
                    header_nums = [int(x) for x in raw[:first].decode("latin-1", errors="ignore").split()]
                    pairs = [(header_nums[2 * k], header_nums[2 * k + 1]) for k in range(min(n_cnt, len(header_nums) // 2))]
                    body_data = raw[first:]
                    for idx, (obj_id, off) in enumerate(pairs):
                        end_off = pairs[idx + 1][1] if idx + 1 < len(pairs) else len(body_data)
                        objs.setdefault((obj_id, 0), body_data[off:end_off])
                except Exception:
                    pass

    def _get_mediabox_height(body: bytes, inherited_h: float = 792.0) -> float:
        mb = re.search(
            rb"/MediaBox\s*\[\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\]",
            body,
        )
        if mb:
            return abs(float(mb.group(4)) - float(mb.group(2))) or inherited_h
        return inherited_h

    pages_tokens: List[List[Dict[str, Any]]] = []
    roots = list(re.finditer(rb"/Root\s+(\d+)\s+(\d+)\s+R", pdf_bytes))
    walked_refs: List[Tuple[Tuple[int, int], float]] = []

    if roots:
        root_m = roots[-1]
        cat_body = objs.get((int(root_m.group(1)), int(root_m.group(2))), b"")
        pages_m = re.search(rb"/Pages\s+(\d+)\s+(\d+)\s+R", cat_body)
        if pages_m:
            visited = set()

            def _walk(ref: Tuple[int, int], parent_h: float) -> None:
                if ref in visited:
                    return
                visited.add(ref)
                body = objs.get(ref, b"")
                cur_h = _get_mediabox_height(body, parent_h)
                if re.search(rb"/Type\s*/Page(?![a-zA-Z])", body):
                    walked_refs.append((ref, cur_h))
                    return
                kids_m = re.search(rb"/Kids\s*\[(.*?)\]", body, re.DOTALL)
                if kids_m:
                    for km in re.finditer(rb"(\d+)\s+(\d+)\s+R", kids_m.group(1)):
                        _walk((int(km.group(1)), int(km.group(2))), cur_h)

            _walk((int(pages_m.group(1)), int(pages_m.group(2))), 792.0)

    def _decode_stream_obj(body: bytes) -> bytes:
        sm = re.search(rb"stream[\r\n]+(.*?)[\r\n]+endstream", body, re.DOTALL)
        if not sm:
            return b""
        raw = sm.group(1)
        try:
            return zlib.decompress(raw)
        except Exception:
            return raw

    if walked_refs:
        for page_ref, page_h in walked_refs:
            pbody = objs.get(page_ref, b"")
            content_refs: List[Tuple[int, int]] = []
            arr_m = re.search(rb"/Contents\s*\[(.*?)\]", pbody, re.DOTALL)
            if arr_m:
                for cm_ref in re.finditer(rb"(\d+)\s+(\d+)\s+R", arr_m.group(1)):
                    content_refs.append((int(cm_ref.group(1)), int(cm_ref.group(2))))
            else:
                sgl_m = re.search(rb"/Contents\s+(\d+)\s+(\d+)\s+R", pbody)
                if sgl_m:
                    content_refs.append((int(sgl_m.group(1)), int(sgl_m.group(2))))
            combined_stream = b"\n".join(_decode_stream_obj(objs.get(r, b"")) for r in content_refs)
            toks = _parse_stream_positioned_tokens(combined_stream, page_height=page_h)
            if toks:
                pages_tokens.append(toks)

    # Fallback: synthetic PDFs without a Catalog/Pages tree
    if not pages_tokens:
        stream_pattern = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
        for m in stream_pattern.finditer(pdf_bytes):
            raw = m.group(1)
            try:
                dec = zlib.decompress(raw)
            except Exception:
                dec = raw
            if b"Tj" in dec or b"TJ" in dec or b"Tm" in dec or b"Td" in dec:
                toks = _parse_stream_positioned_tokens(dec, page_height=792.0)
                if toks:
                    pages_tokens.append(toks)
            elif b"%PDF" not in dec:
                # Plain text test fallback
                txt = dec.decode("latin-1", errors="ignore")
                fake_toks: List[Dict[str, Any]] = []
                for idx, ln in enumerate(txt.splitlines()):
                    s = ln.strip()
                    if s and not s.startswith(("obj", "endobj", "xref", "trailer", "<<", ">>")):
                        fake_toks.append({"x": 36.0, "top": 40.0 + idx * 14.0, "x1": 200.0, "text": s, "font_size": 10.0})
                if fake_toks:
                    pages_tokens.append(fake_toks)

    return pages_tokens


def _extract_positioned_tokens_from_pdf_bytes(pdf_bytes: bytes) -> List[List[Dict[str, Any]]]:
    """
    Extracts visually positioned word/span tokens page-by-page:
    1. Prefers `pdfplumber` when installed in the runtime environment.
    2. Falls back to `pypdf` / `PyPDF2` visitor extraction when installed.
    3. Uses deterministic built-in pure-Python PDF stream (X, Y) positioning engine.
    """
    # 1. Try pdfplumber
    try:
        import pdfplumber  # type: ignore

        pages_tokens: List[List[Dict[str, Any]]] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                words = page.extract_words(
                    x_tolerance=3,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=False,
                )
                toks = [
                    {
                        "x": float(w["x0"]),
                        "top": float(w["top"]),
                        "x1": float(w["x1"]),
                        "text": _clean_text(w["text"]),
                        "font_size": max(4.0, float(w.get("bottom", w["top"] + 10.0)) - float(w["top"])),
                    }
                    for w in words
                    if _clean_text(w.get("text", ""))
                ]
                if toks:
                    pages_tokens.append(toks)
        if pages_tokens:
            return pages_tokens
    except Exception:
        pass

    # 2. Try pypdf / PyPDF2 visitor_text
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
            reader = mod.PdfReader(io.BytesIO(pdf_bytes))
            pages_tokens = []
            for page in reader.pages:
                page_h = float(page.mediabox.height) if getattr(page, "mediabox", None) else 792.0
                collected: List[Dict[str, Any]] = []

                def _visitor(text: str, cm: List[float], tm: List[float], font_dict: Any, font_size: float) -> None:
                    cleaned = _clean_text(text)
                    if not cleaned:
                        return
                    x = float(tm[4])
                    vy = float(tm[5])
                    top = page_h - vy
                    eff = max(4.0, float(font_size or 10.0) * (abs(float(tm[0])) or 1.0))
                    collected.append({
                        "x": x,
                        "top": top,
                        "x1": x + max(3.0, len(cleaned) * eff * 0.48),
                        "text": cleaned,
                        "font_size": eff,
                    })

                try:
                    page.extract_text(visitor_text=_visitor)
                except TypeError:
                    collected = []
                if collected:
                    pages_tokens.append(collected)
            if pages_tokens:
                return pages_tokens
        except Exception:
            pass

    # 3. Pure-Python deterministic PDF stream (X, Y) extractor
    return _extract_pages_pure_python(pdf_bytes)


# ---------------------------------------------------------------------------
# Visual Row Clustering & Column Alignment
# ---------------------------------------------------------------------------

def _cluster_tokens_into_visual_rows(tokens: List[Dict[str, Any]], y_tol: float = 3.2) -> List[Dict[str, Any]]:
    """
    Groups tokens across a page into horizontal Y rows, sorting left-to-right
    regardless of raw PDF emission order (re-attaching detached columns).
    """
    if not tokens:
        return []

    sorted_toks = sorted(tokens, key=lambda t: (round(t["top"], 2), t["x"]))
    row_groups: List[List[Dict[str, Any]]] = []
    cur_y: Optional[float] = None

    for tok in sorted_toks:
        if cur_y is None or abs(tok["top"] - cur_y) > y_tol:
            row_groups.append([tok])
            cur_y = tok["top"]
        else:
            row_groups[-1].append(tok)
            cur_y = sum(t["top"] for t in row_groups[-1]) / len(row_groups[-1])

    visual_rows: List[Dict[str, Any]] = []
    for grp in row_groups:
        grp.sort(key=lambda t: t["x"])
        cells: List[Dict[str, Any]] = []
        for t in grp:
            txt = t["text"]
            if not txt:
                continue
            if not cells:
                cells.append({
                    "x": t["x"],
                    "x1": t["x1"],
                    "text": txt,
                    "font_size": t["font_size"],
                })
                continue
            prev = cells[-1]
            gap = t["x"] - prev["x1"]
            merge_thresh = max(5.5, 0.7 * max(prev["font_size"], t["font_size"]))
            # Merge currency sign "$" with adjacent price, OR adjacent words inside one cell
            prev_is_currency = prev["text"] in ("$", "C$", "US$")
            # Never merge two distinct decimal prices together (e.g., "10.50" and "12.00")
            both_prices = bool(re.match(r"^\$?\s*\d[\d,]*\.\d{2}$", prev["text"]) and _MONEY_RE.match(txt))
            # Never merge separate short numeric/zone column header tokens (e.g., "1" and "2" and "3")
            both_short_tokens = (
                gap >= 1.8
                and len(prev["text"]) <= 3
                and len(txt) <= 3
                and bool(re.match(r"^(?:\d{1,3}|[A-Z]{1,2})$", prev["text"]))
                and bool(re.match(r"^(?:\d{1,3}|[A-Z]{1,2})$", txt))
            )
            if (prev_is_currency and gap < 22.0) or (gap <= merge_thresh and not both_prices and not both_short_tokens):
                # When merging "$" with price, anchor cell box near the price so column centers align!
                if prev_is_currency:
                    prev["x"] = min(prev["x"], t["x"]) if (t["x"] - prev["x"]) <= 12.0 else (t["x"] - 4.0)
                prev["text"] = f"{prev['text']} {txt}".strip()
                prev["x1"] = max(prev["x1"], t["x1"])
            else:
                cells.append({
                    "x": t["x"],
                    "x1": t["x1"],
                    "text": txt,
                    "font_size": t["font_size"],
                })

        if cells:
            avg_y = sum(t["top"] for t in grp) / len(grp)
            # Clean spaces between "$" and amount (e.g. "$ 166.17" -> "$166.17")
            for c in cells:
                c["text"] = re.sub(r"\$\s+(\d)", r"$\1", c["text"])
            visual_rows.append({"top": avg_y, "cells": cells})

    return visual_rows


def _row_text(vr: Dict[str, Any]) -> str:
    return " ".join(c["text"] for c in vr["cells"]).strip()


def _is_multi_col_data_or_header_row(vr: Dict[str, Any]) -> bool:
    cells = vr["cells"]
    if len(cells) >= 3:
        return True
    if len(cells) == 2:
        t0, t1 = cells[0]["text"], cells[1]["text"]
        if _MONEY_RE.match(t1) or _ZONE_WORD_RE.search(t0) or _MIN_CHARGE_RE.search(t0):
            return True
    return False


def _looks_like_interior_subtable_header(vr: Dict[str, Any]) -> bool:
    """Detects an interior repeating Zone/Weight/Origin header band inside a stacked page."""
    cells = [c["text"].strip() for c in vr["cells"] if c["text"].strip()]
    if len(cells) < 3:
        return False
    joined = " ".join(cells).lower()
    if "zone" in joined and sum(1 for c in cells if _is_zone_token(c)) >= 2:
        return True
    if any(k in joined for k in ("origin", "destination", "weight break", "minimum charge")) and sum(
        1 for c in cells if _MONEY_RE.match(c)
    ) == 0:
        return True
    return False


def _segment_page_sections(visual_rows: List[Dict[str, Any]], page_num: int) -> List[Dict[str, Any]]:
    """
    Splits a single PDF page into logical table/prose sections using Y-gaps,
    section title headers, interior sub-table header rows, and column transitions.
    """
    if not visual_rows:
        return []

    sections: List[Dict[str, Any]] = []
    cur_preamble: List[str] = []
    cur_rows: List[Dict[str, Any]] = []
    prev_top: Optional[float] = None

    def _flush() -> None:
        nonlocal cur_rows, cur_preamble
        if cur_rows:
            sections.append({
                "page": page_num,
                "preamble": list(cur_preamble),
                "rows": list(cur_rows),
            })
            cur_rows = []

    for vr in visual_rows:
        txt = _row_text(vr)
        n_cells = len(vr["cells"])
        y_gap = (vr["top"] - prev_top) if prev_top is not None else 0.0
        prev_top = vr["top"]

        # Skip page footer numbers alone (e.g. "23") near bottom margin
        if n_cells == 1 and re.match(r"^\d{1,3}$", txt) and vr["top"] > 720.0:
            continue

        is_table_row = _is_multi_col_data_or_header_row(vr)
        is_title_like = (
            not is_table_row
            and len(txt) >= 3
            and not txt.startswith("*")
        )

        # Split stacked freight sub-tables when a Minimum Charge row is followed by a restarted weight series
        if cur_rows and len(cur_rows) >= 3:
            prev_txt = _row_text(cur_rows[-1])
            if _MIN_CHARGE_RE.search(prev_txt) and _is_weight_row_label(vr["cells"][0]["text"]):
                # Inherit the top header row of the current stacked page for the new sub-table
                hdr_vr = cur_rows[0] if any(_is_zone_token(c["text"]) for c in cur_rows[0]["cells"]) else None
                _flush()
                if hdr_vr is not None:
                    cur_rows.append(hdr_vr)
                cur_rows.append(vr)
                continue

        # Split when encountering a second header band inside stacked tables (e.g., DTD / DTA / ATA)
        if cur_rows and len(cur_rows) >= 2 and _looks_like_interior_subtable_header(vr):
            _flush()
            cur_rows.append(vr)
            continue

        # Large vertical gap or explicit section heading starts a new sub-table block
        if cur_rows and (y_gap > 26.0 or (is_title_like and _looks_like_section_title(txt))):
            _flush()
            if is_title_like:
                cur_preamble.append(txt)
                if len(cur_preamble) > 8:
                    cur_preamble = cur_preamble[-8:]
            continue

        if is_title_like:
            cur_preamble.append(txt)
            if len(cur_preamble) > 8:
                cur_preamble = cur_preamble[-8:]
        elif is_table_row or cur_rows:
            # Avoid absorbing legal footnotes at bottom into a finished rate table
            if txt.startswith("*") and len(txt) > 35 and cur_rows:
                _flush()
                cur_preamble.append(txt)
                continue
            cur_rows.append(vr)

    _flush()
    if not sections and cur_preamble:
        # Fallback if a page has comma/pipe/2-space delimiter lines rendered as 1 cell each
        parsed_fallback: List[Dict[str, Any]] = []
        for idx, ln in enumerate(cur_preamble):
            parts = _split_pdf_table_line_into_cells(ln)
            if len(parts) >= 2:
                parsed_fallback.append({
                    "top": 50.0 + idx * 12.0,
                    "cells": [{"x": 36.0 + k * 70.0, "x1": 96.0 + k * 70.0, "text": p, "font_size": 10.0} for k, p in enumerate(parts)],
                })
        if parsed_fallback:
            sections.append({"page": page_num, "preamble": [], "rows": parsed_fallback})

    return sections


def _looks_like_section_title(txt: str) -> bool:
    low = txt.lower()
    if any(
        kw in low
        for kw in (
            "door-to-door",
            "door-to-airport",
            "airport-to-",
            "overnight",
            "2day",
            "economy",
            "priority",
            "freight",
            "ground",
            "zone chart",
            "zone index",
            "rates for shipments",
            "surcharges",
            "additional fees",
            "ltl tariff",
            "skid tariff",
            "pallet tariff",
            "outbound rates",
        )
    ):
        return True
    return len(txt) <= 65 and not _MONEY_RE.match(txt)


def _cell_anchor_x(c: Dict[str, Any]) -> float:
    """
    Uses right-edge anchor for right-aligned money values (so '$' on row 1 aligns
    cleanly with non-'$' numbers on row 2), midpoint for zones, and x0 for text labels.
    """
    if _MONEY_RE.match(c["text"]):
        return c["x1"] - 4.0
    if _is_zone_token(c["text"]):
        return (c["x"] + c["x1"]) / 2.0
    return c["x"]


def _align_section_to_grid(section_rows: List[Dict[str, Any]]) -> List[List[str]]:
    """
    Projects visual cells with (x, text) into a rectangular 2D grid by clustering
    X-coordinates into column anchors so missing cells do not left-shift neighbors.
    """
    if not section_rows:
        return []

    all_x: List[float] = []
    for vr in section_rows:
        for c in vr["cells"]:
            all_x.append(_cell_anchor_x(c))

    if not all_x:
        return []

    sorted_x = sorted(all_x)
    anchors: List[float] = []
    cluster: List[float] = [sorted_x[0]]
    for x in sorted_x[1:]:
        if x - (sum(cluster) / len(cluster)) <= 20.0:
            cluster.append(x)
        else:
            anchors.append(sum(cluster) / len(cluster))
            cluster = [x]
    anchors.append(sum(cluster) / len(cluster))

    max_raw_cols = max(len(vr["cells"]) for vr in section_rows)
    if len(anchors) < max_raw_cols:
        return [[c["text"] for c in vr["cells"]] + [""] * (max_raw_cols - len(vr["cells"])) for vr in section_rows]

    # If the dense majority of rows all share the exact same cell count (e.g. 9 cols across
    # Zone header + data rows), direct sequential column assignment prevents cumulative Tw width drift
    # from creating false empty columns inside dense rows while still using X-anchors for sparse rows.
    from collections import Counter
    counts = Counter(len(vr["cells"]) for vr in section_rows if len(vr["cells"]) >= 3)
    if counts:
        dominant_w, dom_freq = counts.most_common(1)[0]
        if dom_freq >= max(2, len(section_rows) // 2) and len(anchors) >= dominant_w:
            # Build refined anchors directly from the dense rows' cell positions
            dense_x_sums = [0.0] * dominant_w
            dense_cnt = 0
            for vr in section_rows:
                if len(vr["cells"]) == dominant_w:
                    for k, c in enumerate(vr["cells"]):
                        dense_x_sums[k] += _cell_anchor_x(c)
                    dense_cnt += 1
            if dense_cnt > 0:
                anchors = [s / dense_cnt for s in dense_x_sums]

    grid: List[List[str]] = []
    for vr in section_rows:
        if counts and len(vr["cells"]) == len(anchors):
            row_arr = [c["text"] for c in vr["cells"]]
            if any(cell.strip() for cell in row_arr):
                grid.append(row_arr)
            continue
        row_arr = [""] * len(anchors)
        for c in vr["cells"]:
            cx = _cell_anchor_x(c)
            best_idx = min(range(len(anchors)), key=lambda idx: abs(cx - anchors[idx]))
            idx = best_idx
            while idx < len(row_arr) and row_arr[idx]:
                idx += 1
            if idx < len(row_arr):
                row_arr[idx] = c["text"]
            else:
                idx = best_idx - 1
                while idx >= 0 and row_arr[idx]:
                    idx -= 1
                if idx >= 0:
                    row_arr[idx] = c["text"]
        if any(cell.strip() for cell in row_arr):
            grid.append(row_arr)

    if not grid:
        return []
    keep_cols = [c for c in range(len(grid[0])) if any(row[c].strip() for row in grid)]
    return [[row[c] for c in keep_cols] for row in grid]


# ---------------------------------------------------------------------------
# Archetype Classification, Page Stitching & Column Title Preservation
# ---------------------------------------------------------------------------

def _is_zone_token(val: str) -> bool:
    s = val.strip()
    if not s:
        return False
    if re.match(r"^zone\s+[A-Z0-9]{1,4}$", s, re.I):
        return True
    if re.match(r"^[0-9]{1,2}$", s) and 0 <= int(s) <= 60:
        return True
    if re.match(r"^[A-Z]{1,2}$", s):
        return True
    return False


def _is_weight_row_label(val: str) -> bool:
    s = val.strip().rstrip(".")
    if not s:
        return False
    if _MIN_CHARGE_RE.search(s) or _OVERAGE_ROW_RE.match(s):
        return True
    if re.match(r"^\d[\d,]*\s*(?:to|[-–])\s*\d[\d,]*\s*(?:lbs?|kgs?|#)?$", s, re.I):
        return True
    if re.match(r"^\d[\d,]*\s+to$", s, re.I):
        return True
    if parse_break_header(s, mode_hint="weight") is not None:
        return True
    if re.match(r"^\d+(?:\.\d+)?\s*(?:lbs?|kgs?)?$", s, re.I):
        return True
    return False


def _normalize_weight_break_label(raw_label: str, default_unit: Optional[str] = None) -> str:
    """Normalizes weight labels into clean title strings compatible with break_header_parser."""
    s = _clean_text(raw_label).rstrip(".")
    if not s:
        return ""
    if _MIN_CHARGE_RE.search(s):
        return "Minimum Charge"

    # Handle "100 lbs. or more" / "2000 or more"
    m_over = _OVERAGE_ROW_RE.match(s)
    if m_over:
        num = m_over.group(1).replace(",", "")
        unit = detect_unit_in_header(s) or default_unit or "lb"
        unit_str = "lbs" if unit == "lb" else "kgs"
        return f"{num}+ {unit_str}"

    # Handle "151 to 299 lbs"
    m_rng = re.match(r"^(\d[\d,]*)\s*(?:to|[-–])\s*(\d[\d,]*)\s*(?:(lbs?|kgs?|#))?$", s, re.I)
    if m_rng:
        n1 = m_rng.group(1).replace(",", "")
        n2 = m_rng.group(2).replace(",", "")
        unit = detect_unit_in_header(s) or default_unit or "lb"
        unit_str = "lbs" if unit == "lb" else "kgs"
        return f"{n1} to {n2} {unit_str}"

    # Handle bare integer weight step (e.g. "1 lb" or "2") when default_unit exists
    m_single = re.match(r"^(\d[\d,]*(?:\.\d+)?)\s*(lbs?|kgs?|#)?$", s, re.I)
    if m_single and default_unit:
        num = m_single.group(1).replace(",", "")
        u = m_single.group(2)
        if u:
            unit_str = "lbs" if u.lower().startswith("lb") or u == "#" else "kgs"
        else:
            unit_str = "lbs" if default_unit == "lb" else "kgs"
        if num == "1" and unit_str == "lbs":
            return "1 lb"
        return f"{num} {unit_str}"

    return s


def _propagate_unit_or_prefix(labels: List[str], kind_hint: Optional[str] = None, banner: str = "") -> List[str]:
    """
    Propagates unit ('lbs', 'kgs') or category prefix ('Zone', 'Skid') across
    bare numeric sibling labels so no column/axis shows unlabeled numbers.
    """
    if not labels:
        return labels

    banner_low = banner.lower()
    detected_unit: Optional[str] = None
    for lbl in labels:
        u = detect_unit_in_header(lbl)
        if u:
            detected_unit = u
            break
    if not detected_unit:
        if "kg" in banner_low or "kilogram" in banner_low:
            detected_unit = "kg"
        elif "lb" in banner_low or "pound" in banner_low:
            detected_unit = "lb"

    has_zone_cue = kind_hint == "zone" or (
        kind_hint is None and (any("zone" in l.lower() for l in labels) or "zone" in banner_low)
    )
    has_skid_cue = kind_hint == "skid" or (
        kind_hint is None and (
            any(re.search(r"\b(?:skids?|pallets?|pl)\b", l, re.I) for l in labels)
            or "skid" in banner_low
            or "pallet" in banner_low
        )
    )

    out: List[str] = []
    for lbl in labels:
        s = _clean_text(lbl).rstrip(".")
        if not s:
            out.append("")
            continue
        if _MIN_CHARGE_RE.search(s):
            out.append("Minimum Charge")
            continue

        # Bare number or short zone letter under Zone banner
        if has_zone_cue and re.match(r"^[0-9]{1,2}$|^[A-Z]{1,2}$", s):
            if not re.match(r"^Zone\b", s, re.I):
                out.append(f"Zone {s}")
                continue

        if has_skid_cue and re.match(r"^\d+(?:\s*[-–]\s*\d+)?$", s):
            unit_lbl = "Skid" if s == "1" else "Skids"
            out.append(f"{s} {unit_lbl}")
            continue

        if kind_hint == "weight" or detected_unit:
            norm_w = _normalize_weight_break_label(s, default_unit=detected_unit or "lb")
            if norm_w != s or re.match(r"^\d+(?:\.\d+)?$", s):
                out.append(norm_w)
                continue

        out.append(s)
    return out


def _expand_compound_zone_headers(header_row: List[str], sample_data_rows: List[List[str]]) -> List[str]:
    """
    Splits fused space-separated short zone headers (e.g. '0 1 2 3' or '1 2 3') into
    individual column headers aligned over the data columns below.
    """
    if not header_row or not sample_data_rows:
        return header_row

    has_compound = any(
        len(c.strip().split()) >= 2
        and all(re.match(r"^(?:[0-9]{1,2}|[A-Z])$", tok) for tok in c.strip().split())
        for c in header_row[1:]
        if c.strip()
    )
    if not has_compound:
        return header_row

    # Expand multi-token zone cells sequentially while preserving column width
    width = max(len(header_row), max((len(r) for r in sample_data_rows), default=0))
    # First identify how many trailing rate/zone columns actually contain data
    # Keep col 0 (+ optional col 1 if metric weight column) aligned, expand zone tokens into remaining slots
    prefix_cols = 1
    if len(sample_data_rows[0]) > 2 and any("kg" in str(r[1]).lower() for r in sample_data_rows[:5] if len(r) > 1):
        prefix_cols = 2

    expanded_tail: List[str] = []
    # Also check header_row[0] in case "Zones" or "1 2" appeared after Weight/kg
    for c in header_row[prefix_cols:]:
        s = c.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 2 and all(re.match(r"^(?:[0-9]{1,2}|[A-Z])$", tok) for tok in parts):
            expanded_tail.extend(parts)
        else:
            expanded_tail.append(s)

    target_tail_len = max(0, width - prefix_cols)
    if target_tail_len > 0 and len(expanded_tail) == target_tail_len:
        return list(header_row[:prefix_cols]) + expanded_tail

    # Fallback: fill each multi-token header cell into adjacent blank slots in header_row
    out = list(header_row) + [""] * (width - len(header_row))
    i = 0
    while i < len(out):
        s = out[i].strip()
        parts = s.split()
        if i >= 1 and len(parts) >= 2 and all(re.match(r"^(?:[0-9]{1,2}|[A-Z])$", tok) for tok in parts):
            blanks = 0
            while i + blanks + 1 < len(out) and not out[i + blanks + 1].strip():
                blanks += 1
            if blanks + 1 >= len(parts):
                for k, tok in enumerate(parts):
                    out[i + k] = tok
        i += 1
    return out


def _collapse_multi_row_header(grid: List[List[str]], preamble: List[str]) -> Tuple[List[str], List[List[str]]]:
    """
    Flattens stacked 2-row PDF headers (e.g., super-header ['Weight (lbs)', ...]
    above ['1', '2', ...] or ['Zone', 'Zone'] above ['1', '2']) and returns
    (headers, data_rows).
    """
    if not grid:
        return [], []
    if len(grid) == 1:
        return list(grid[0]), []

    r0 = [c.strip() for c in grid[0]]
    r1 = [c.strip() for c in grid[1]]

    # Check if Row 0 looks like a super-header band above Row 1 sub-headers (before numeric money data in Row 2)
    row1_has_money = any(_MONEY_RE.match(c) and "$" in c or (re.match(r"^\d+\.\d{2}$", c)) for c in r1[1:])
    row0_has_money = any(re.match(r"^\d+\.\d{2}$", c) or "$" in c for c in r0[1:])

    banner_text = " ".join(preamble)
    if len(grid) >= 3 and not row0_has_money and not row1_has_money:
        r2_has_money = any(_MONEY_RE.match(c) for c in grid[2] if c.strip())
        if r2_has_money or any(w in " ".join(r0).lower() for w in ("weight", "zone", "skid", "pallet", "break", "cwt")):
            # Forward-fill super-header labels across spans cleanly
            filled_r0: List[str] = []
            last_super = ""
            for cell in r0:
                if cell:
                    last_super = cell
                    filled_r0.append(cell)
                else:
                    filled_r0.append(last_super if len(r0) > 2 else "")

            combined: List[str] = []
            for idx in range(max(len(filled_r0), len(r1))):
                s0 = filled_r0[idx] if idx < len(filled_r0) else ""
                s1 = r1[idx] if idx < len(r1) else ""
                if s0 and s1 and s0.lower() != s1.lower():
                    # Avoid awkward "Weight Zone 1" or "Zone 1" duplication
                    if "zone" in s0.lower() and not s1.lower().startswith("zone"):
                        combined.append(f"Zone {s1}")
                    elif "weight" in s0.lower() and re.match(r"^\d", s1):
                        unit = detect_unit_in_header(s0) or detect_unit_in_header(banner_text) or "lb"
                        combined.append(_normalize_weight_break_label(s1, unit))
                    elif "skid" in s0.lower() or "pallet" in s0.lower():
                        unit_lbl = "Skid" if s1 == "1" else "Skids"
                        combined.append(f"{s1} {unit_lbl}" if re.match(r"^\d+$", s1) else f"{s0} {s1}")
                    else:
                        combined.append(f"{s0} {s1}".strip())
                else:
                    combined.append(s1 or s0)
            return _expand_compound_zone_headers(combined, grid[2:]), grid[2:]

    return _expand_compound_zone_headers(r0, grid[1:]), grid[1:]


def _infer_currency_and_unit(text_blob: str) -> Tuple[Optional[str], Optional[str]]:
    low = text_blob.lower()
    curr = None
    if "usd" in low or "us$" in low or "u.s. dollar" in low:
        curr = "USD"
    elif "cad" in low or "c$" in low or "canadian dollar" in low or "fedex.ca" in low or "canada" in low:
        curr = "CAD"

    unit = None
    if re.search(r"\b(kgs?|kilograms?)\b", low) and not re.search(r"\blbs?\b", low):
        unit = "kg"
    elif re.search(r"\b(lbs?|pounds?)\b", low):
        unit = "lb"
    return curr, unit


def _detect_fixed_origin_from_preamble(preamble: List[str]) -> Optional[str]:
    joined = " | ".join(preamble)
    # Match explicit outbound/origin preambles including Zone Chart headers
    m = _ORIGIN_PREAMBLE_RE.search(joined)
    if m:
        cand = _clean_text(m.group(1))
        # Avoid false positives like "Origin Index" or "Origin Zone DA"
        if cand and not re.match(r"^(?:zone|index|country|countries|us|u\.s\.)$", cand, re.I):
            return cand
    m_out = re.search(r"\b(?:outbound|originating)\s+from\s+([A-Za-z0-9,\s-]{2,50})", joined, re.I)
    if m_out:
        return _clean_text(m_out.group(1))
    return None


def _is_reference_or_notes_table(headers: List[str], data_rows: List[List[str]], preamble: List[str]) -> bool:
    if len(headers) <= 2:
        return True

    hdr_join = " ".join(headers).lower()
    pre_join = " ".join(preamble).lower()
    all_cells = headers + [c for r in data_rows[:12] for c in r]
    all_join = " ".join(all_cells).lower()

    # Table of contents / dot-leader indexes ("....")
    if "...." in all_join or ". . ." in all_join:
        return True

    # Two-column or paragraph instruction / prose text without >= 2 numeric rate columns
    cols_with_rates = 0
    width = max(len(headers), max((len(r) for r in data_rows[:15]), default=0))
    for col_i in range(1, width):
        col_vals = [r[col_i].strip() for r in data_rows[:15] if col_i < len(r) and r[col_i].strip()]
        rate_hits = sum(
            1 for c in col_vals
            if re.match(r"^\$?\s*\d[\d,]*\.\d{2}$", c)
            or ("$" in c and _MONEY_RE.match(c))
            or (re.match(r"^\d[\d,]*$", c) and float(c.replace(",", "")) >= 20)
        )
        if rate_hits >= 1:
            cols_with_rates += 1
    if cols_with_rates < 2:
        return True

    if any(k in hdr_join or k in pre_join for k in (
        "definition", "applicable services", "surcharge", "additional fee",
        "postal code", "fsa", "zone index", "origin zone da", "zone chart",
        "terms and conditions", "declared value", "dimensional weight",
    )):
        money_count = sum(1 for r in data_rows[:10] for c in r[1:] if _MONEY_RE.match(c.strip()) and "." in c)
        if money_count < 4 or "surcharge" in pre_join or "definition" in hdr_join or "additional fee" in pre_join:
            return True
    if data_rows and len(headers) >= 4:
        has_decimals = any("." in c for r in data_rows[:12] for c in r[1:])
        all_small_ints_or_letters = all(
            re.match(r"^(?:[A-Z]{1,2}|\d{1,2}|–|-|\*+)$", c.strip())
            for r in data_rows[:10] for c in r[1:] if c.strip()
        )
        if not has_decimals and all_small_ints_or_letters and ("zone" in pre_join or "zone" in hdr_join or "chart" in pre_join):
            return True
    return False


def _ensure_descriptive_column_titles(
    headers: List[str],
    data_rows: List[List[str]],
    archetype: str,
    preamble: List[str],
    unit_hint: Optional[str] = None,
) -> List[str]:
    """
    Mandatory Column Title Preservation & Synthesis Pass:
    Guarantees every column header is meaningful and never leaves bare unlabeled
    numbers ('2', '3', '500') or empty titles in FailsafeModal.
    """
    banner = " ".join(preamble)
    width = max(len(headers), max((len(r) for r in data_rows), default=0))
    padded = [headers[i] if i < len(headers) else "" for i in range(width)]

    # Determine dominant table mode for propagating bare numeric column headers
    if archetype == "skid_matrix":
        propagated = _propagate_unit_or_prefix(padded, kind_hint="skid", banner=banner)
    elif archetype == "transposed_weight_zone":
        propagated = _propagate_unit_or_prefix(padded, kind_hint="weight", banner=banner)
    else:
        propagated = _propagate_unit_or_prefix(padded, kind_hint=None, banner=banner)

    final_headers: List[str] = []
    for idx, h in enumerate(propagated):
        title = _clean_text(h)
        col_vals = [r[idx].strip() for r in data_rows[:15] if idx < len(r) and r[idx].strip()]

        # If blank or bare number without unit, synthesize contextual title
        if not title or title.lower() in ("column", "col", "-"):
            if idx == 0:
                if col_vals and all(_is_zone_token(v) for v in col_vals):
                    title = "Destination Zone"
                elif archetype == "fixed_origin_outbound":
                    title = "Destination"
                else:
                    title = "Origin"
            elif idx == 1 and final_headers and "origin" in final_headers[0].lower():
                title = "Destination Zone" if (col_vals and all(_is_zone_token(v) for v in col_vals)) else "Destination"
            elif col_vals and all(_is_zone_token(v) for v in col_vals):
                title = f"Zone Column {idx + 1}"
            elif col_vals and all(_MONEY_RE.match(v) for v in col_vals):
                title = f"Rate Column {idx + 1}"
            else:
                col_letter = chr(65 + (idx % 26))
                title = f"Field {col_letter}"
        elif re.match(r"^\d+(?:\.\d+)?$", title):
            # Bare numeric column header left without unit or category
            if col_vals and all(_MONEY_RE.match(v) for v in col_vals):
                u_str = "kgs" if unit_hint == "kg" else "lbs"
                if "skid" in banner.lower() or "pallet" in banner.lower():
                    title = f"{title} {'Skid' if title == '1' else 'Skids'}"
                elif "zone" in banner.lower() and archetype != "transposed_weight_zone":
                    title = f"Zone {title}"
                else:
                    title = f"{title} {u_str}"
            elif "zone" in banner.lower():
                title = f"Zone {title}"

        final_headers.append(title)

    return final_headers


def _repair_split_ranges_and_prune_empty(headers: List[str], data_rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """
    Repairs weight ranges split across Col 0 + Col 1 (e.g. '300 to' | '499' -> '300 to 499'),
    then prunes sparse phantom gap columns created by currency symbol left-offsets.
    """
    if len(headers) >= 3:
        for r in data_rows:
            if len(r) >= 2 and re.search(r"\b(?:to|[-–])$", r[0].strip(), re.I) and re.match(r"^\d[\d,]*\s*(?:lbs?|kgs?)?\.?$", r[1].strip(), re.I):
                r[0] = f"{r[0].strip()} {r[1].strip()}".strip()
                r[1] = ""

    width = len(headers)
    # Identify phantom empty header columns whose values can fold into empty neighbor slot
    for col_i in range(width - 1, -1, -1):
        h_empty = not headers[col_i].strip()
        col_vals = [r[col_i].strip() for r in data_rows if col_i < len(r) and r[col_i].strip()]
        if h_empty and not col_vals:
            headers.pop(col_i)
            for r in data_rows:
                if col_i < len(r):
                    r.pop(col_i)
        elif h_empty and col_i > 0 and len(col_vals) <= max(2, len(data_rows) // 3):
            # Try folding sparse values into empty right or left neighbor when mutually exclusive
            folded = False
            for adj in (col_i + 1, col_i - 1):
                if 0 <= adj < len(headers) and all(
                    not (
                        (col_i < len(r) and r[col_i].strip())
                        and (adj < len(r) and r[adj].strip())
                    )
                    for r in data_rows
                ):
                    for r in data_rows:
                        if col_i < len(r) and r[col_i].strip():
                            r[adj] = r[col_i].strip()
                            r[col_i] = ""
                    headers.pop(col_i)
                    for r in data_rows:
                        if col_i < len(r):
                            r.pop(col_i)
                    folded = True
                    break
            if folded:
                continue

    return headers, data_rows


def _classify_and_normalize_table(raw_grid: List[List[str]], preamble: List[str], base_title: str) -> Dict[str, Any]:
    """
    Classifies any raw PDF table across the 5 universal carrier archetypes,
    transposes inverted matrices if needed, and synthesizes labeled column titles.
    """
    banner_blob = " ".join(preamble + ([ " ".join(raw_grid[0]) ] if raw_grid else []))
    curr_hint, unit_hint = _infer_currency_and_unit(banner_blob)

    headers, data_rows = _collapse_multi_row_header(raw_grid, preamble)
    if not headers:
        return {}

    # Normalize width
    width = max(len(headers), max((len(r) for r in data_rows), default=0))
    headers = [headers[i] if i < len(headers) else "" for i in range(width)]
    data_rows = [[r[i] if i < len(r) else "" for i in range(width)] for r in data_rows]

    headers, data_rows = _repair_split_ranges_and_prune_empty(headers, data_rows)
    if not headers:
        return {}

    # Normalize embedded comma/non-money markers in cells (e.g. dash "–" means no rate -> "")
    for r in data_rows:
        for idx, val in enumerate(r):
            if val.strip() in ("–", "—", "-"):
                r[idx] = ""

    # Check Archetype E (Reference / Zone Index / Accessorials)
    if _is_reference_or_notes_table(headers, data_rows, preamble):
        clean_hdrs = _ensure_descriptive_column_titles(headers, data_rows, "reference_notes", preamble, unit_hint)
        return {
            "sheet_name": base_title,
            "section_type": "reference",
            "archetype": "reference_notes",
            "currency_hint": curr_hint,
            "unit_hint": unit_hint or "lb",
            "preamble": preamble,
            "headers": clean_hdrs,
            "rows": data_rows,
            "grid": [clean_hdrs] + data_rows,
        }

    # Detect Archetype D: Inverted Weight-in-Rows x Zone/Dest-in-Columns
    col0_vals = [r[0].strip() for r in data_rows if r and r[0].strip()]
    weight_row_hits = sum(1 for v in col0_vals if _is_weight_row_label(v))
    hdr_rest = [h.strip() for h in headers[1:] if h.strip()]
    zone_hdr_hits = sum(1 for h in hdr_rest if _is_zone_token(h))
    # Ensure col0 header isn't already Origin/Destination lane matrix
    hdr0_low = headers[0].lower() if headers else ""
    hdr0_is_lane = any(k in hdr0_low for k in ("origin", "from", "city", "lane", "skid", "pallet"))

    is_inverted_weight_zone = (
        not hdr0_is_lane
        and len(col0_vals) >= 3
        and (weight_row_hits / len(col0_vals)) >= 0.6
        and len(hdr_rest) >= 2
        and (
            zone_hdr_hits >= max(2, len(hdr_rest) // 2)
            or "weight" in hdr0_low
            or "zone" in " ".join(hdr_rest).lower()
            or "zone" in " ".join(preamble).lower()
        )
    )

    if is_inverted_weight_zone:
        # Detect and skip secondary metric equivalent column (e.g. Col 1 = '0.5 kg', '1', '1.5', '2')
        first_rate_col = 1
        if len(headers) > 2:
            col1_vals = [r[1].strip() for r in data_rows[:10] if len(r) > 1 and r[1].strip()]
            col1_hdr_low = headers[1].lower()
            has_kg_unit = any("kg" in v.lower() for v in col1_vals) or "kg" in col1_hdr_low
            is_metric_half_steps = bool(col1_vals) and all(re.match(r"^\d+(?:\.\d+)?(?:\s*kgs?)?$", v, re.I) for v in col1_vals) and any("." in v for v in col1_vals)
            has_no_money_in_col1 = not any("$" in v for v in col1_vals)
            if (has_kg_unit or is_metric_half_steps) and has_no_money_in_col1:
                first_rate_col = 2

        # Propagate Zone prefix onto Zone columns BEFORE transposing into rows
        zone_labels = _propagate_unit_or_prefix(
            headers[first_rate_col:], kind_hint="zone", banner=" ".join(preamble + [headers[0]])
        )
        # Detect weight unit from first weight rows or preamble
        weight_unit = unit_hint
        for v in col0_vals:
            u = detect_unit_in_header(v)
            if u:
                weight_unit = u
                break
        weight_unit = weight_unit or "lb"

        # Normalize weight break column titles (separating Minimum Charge cleanly)
        min_row_indices = [idx for idx, r in enumerate(data_rows) if _MIN_CHARGE_RE.search(r[0])]
        rate_row_indices = [idx for idx, r in enumerate(data_rows) if not _MIN_CHARGE_RE.search(r[0])]

        raw_wt_labels = [data_rows[idx][0].strip() for idx in rate_row_indices]
        norm_wt_headers = _propagate_unit_or_prefix(raw_wt_labels, kind_hint="weight", banner=" ".join(preamble))

        # If stacked freight sub-tables (e.g. DTD / DTA / ATA) share one page block and repeat the same
        # weight tier sequence after Minimum Charge, deduplicate by slicing cleanly to the first sub-table cycle
        # or splitting repeated weight headers so duplicate weight-break names never collide in FailsafeModal
        if min_row_indices and len(min_row_indices) >= 1:
            first_min = min_row_indices[0]
            first_cycle_rates = [idx for idx in rate_row_indices if idx < first_min]
            if first_cycle_rates and len(rate_row_indices) > len(first_cycle_rates):
                rate_row_indices = first_cycle_rates
                min_row_indices = [first_min]
                norm_wt_headers = norm_wt_headers[:len(first_cycle_rates)]

        fixed_orig = _detect_fixed_origin_from_preamble(preamble)
        trans_headers: List[str] = []
        if fixed_orig:
            trans_headers.append("Origin")
        trans_headers.append("Destination Zone")
        if min_row_indices:
            trans_headers.append("Minimum Charge")
        trans_headers.extend(norm_wt_headers)

        trans_rows: List[List[str]] = []
        for z_idx, z_label in enumerate(zone_labels):
            if not z_label.strip():
                continue
            col_c = z_idx + first_rate_col
            row_vals = [fixed_orig] if fixed_orig else []
            row_vals.append(z_label)
            if min_row_indices:
                mc_val = data_rows[min_row_indices[0]][col_c] if col_c < len(data_rows[min_row_indices[0]]) else ""
                row_vals.append(mc_val)
            for r_i in rate_row_indices:
                cell_v = data_rows[r_i][col_c] if col_c < len(data_rows[r_i]) else ""
                row_vals.append(cell_v)
            # Keep row if at least one rate cell is populated
            if any(v.strip() for v in row_vals[1 if not fixed_orig else 2 :]):
                trans_rows.append(row_vals)

        clean_hdrs = _ensure_descriptive_column_titles(
            trans_headers, trans_rows, "transposed_weight_zone", preamble, weight_unit
        )
        return {
            "sheet_name": base_title,
            "section_type": "rate_grid",
            "archetype": "transposed_weight_zone",
            "currency_hint": curr_hint,
            "unit_hint": weight_unit,
            "fixed_origin": fixed_orig,
            "preamble": preamble,
            "headers": clean_hdrs,
            "rows": trans_rows,
            "grid": [clean_hdrs] + trans_rows,
        }

    # Detect Archetype B: Skid / Pallet Matrix or Row-Based Skid Tariff
    pre_skid_cue = any(re.search(r"\b(?:skids?|pallets?)\b", ln, re.I) for ln in preamble)
    skid_hdr_hits = sum(
        1 for h in headers
        if re.search(r"\b(?:skids?|pallets?|pl|plt)\b", h, re.I) or parse_skid_break_from_keywords(h) is not None
    )
    large_weight_hdr = False
    for h in headers:
        if not re.search(r"\b(?:skids?|pallets?|pl|plt)\b", h, re.I):
            pb_w = parse_break_header(h, mode_hint="weight")
            if pb_w is not None and pb_w.break_value >= 100:
                large_weight_hdr = True
                break
    small_int_hdrs = sum(1 for h in headers if re.match(r"^\d{1,2}$", h.strip()) and 1 <= int(h.strip()) <= 28)
    if (skid_hdr_hits >= 1 or (pre_skid_cue and small_int_hdrs >= 2)) and not large_weight_hdr:
        clean_hdrs = _ensure_descriptive_column_titles(headers, data_rows, "skid_matrix", preamble, unit_hint)
        return {
            "sheet_name": base_title,
            "section_type": "rate_grid",
            "archetype": "skid_matrix",
            "currency_hint": curr_hint,
            "unit_hint": unit_hint or "lb",
            "preamble": preamble,
            "headers": clean_hdrs,
            "rows": data_rows,
            "grid": [clean_hdrs] + data_rows,
        }

    # Detect Archetype C: Fixed-Origin Outbound Tariff (no Origin column, preamble has Origin)
    fixed_orig = _detect_fixed_origin_from_preamble(preamble)
    has_orig_col = any(
        any(k in h.lower() for k in ("origin", "orig", "from", "ship from", "pickup"))
        for h in headers
    )
    has_dest_col = any(
        any(k in h.lower() for k in ("dest", "destination", "to", "zone", "postal", "city"))
        for h in headers
    )
    if fixed_orig and not has_orig_col and has_dest_col:
        # Prepend explicit 'Origin' column populated from preamble banner so headers & lanes are unambiguous
        out_headers = ["Origin"] + list(headers)
        out_rows = [[fixed_orig] + list(r) for r in data_rows]
        clean_hdrs = _ensure_descriptive_column_titles(out_headers, out_rows, "fixed_origin_outbound", preamble, unit_hint)
        return {
            "sheet_name": base_title,
            "section_type": "rate_grid",
            "archetype": "fixed_origin_outbound",
            "currency_hint": curr_hint,
            "unit_hint": unit_hint or "lb",
            "fixed_origin": fixed_orig,
            "preamble": preamble,
            "headers": clean_hdrs,
            "rows": out_rows,
            "grid": [clean_hdrs] + out_rows,
        }

    # Default Archetype A: Standard LTL Lane x Weight-Break Grid
    # Propagate weight units if headers have bare numeric breaks ("500", "1000")
    normalized_hdrs = []
    for h in headers:
        pb = parse_break_header(h, mode_hint="weight")
        if pb and re.match(r"^\d[\d,]*$", h.strip()):
            u_str = "kgs" if unit_hint == "kg" else "lbs"
            normalized_hdrs.append(f"{h.strip()} {u_str}")
        else:
            normalized_hdrs.append(h)

    clean_hdrs = _ensure_descriptive_column_titles(normalized_hdrs, data_rows, "ltl_lane_weight", preamble, unit_hint)
    return {
        "sheet_name": base_title,
        "section_type": "rate_grid",
        "archetype": "ltl_lane_weight",
        "currency_hint": curr_hint,
        "unit_hint": unit_hint or "lb",
        "preamble": preamble,
        "headers": clean_hdrs,
        "rows": data_rows,
        "grid": [clean_hdrs] + data_rows,
    }


def _service_family_key(preamble: List[str]) -> str:
    """Normalizes section title banner for detecting multi-page horizontal/vertical continuations."""
    if not preamble:
        return ""
    for line in preamble:
        low = line.lower()
        if any(k in low for k in (
            "overnight", "2day", "economy", "priority", "freight", "ground",
            "door-to-", "airport-to-", "tariff", "rate schedule", "rates",
        )):
            # Strip weight-band sub-notes so adjacent weight/zone splits match
            cleaned = re.sub(r"\*?for shipments.*$", "", low).strip()
            cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned).strip()
            if cleaned:
                return cleaned
    return re.sub(r"[^a-z0-9]+", " ", preamble[0].lower()).strip()


def _stitch_raw_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Stitches adjacent PDF table sections that represent:
    1. Horizontal page splits (same service banner & identical vertical weight/lane axis,
       disjoint Zone/Destination columns such as Zones 1-8 + Zones 9-16).
    2. Vertical page continuations (identical header row continuing onto next page).
    """
    stitched: List[Dict[str, Any]] = []

    for sec in sections:
        grid = _align_section_to_grid(sec["rows"])
        if not grid or len(grid) < 2:
            continue

        sec_entry = {
            "page": sec["page"],
            "preamble": sec["preamble"],
            "grid": grid,
            "family_key": _service_family_key(sec["preamble"]),
        }

        if not stitched:
            stitched.append(sec_entry)
            continue

        prev = stitched[-1]
        p_grid = prev["grid"]
        c_grid = sec_entry["grid"]

        # Case 1: Vertical continuation — exact same header row repeated across page break
        p_hdr = [c.strip().lower() for c in p_grid[0]]
        c_hdr = [c.strip().lower() for c in c_grid[0]]
        if p_hdr == c_hdr and len(p_hdr) >= 3:
            p_grid.extend(c_grid[1:])
            continue

        # Case 1b: Single-row overage/minimum footer banner (e.g. "100 lbs. or more $1.32 ...")
        # belonging to the preceding weight matrix on the same page
        if (
            sec_entry["page"] == prev["page"]
            and len(c_grid) <= 2
            and any(_OVERAGE_ROW_RE.match(r[0]) or _MIN_CHARGE_RE.search(r[0]) for r in c_grid if r)
        ):
            target_row = c_grid[-1]
            # Align into prev grid if col count matches (accounting for optional kg column)
            if len(target_row) <= len(p_grid[0]) and any(_MONEY_RE.match(c) for c in target_row[1:]):
                pad_w = len(p_grid[0]) - len(target_row)
                if pad_w == 1:
                    # Insert empty secondary-kg cell right after col 0 so rate columns line up
                    p_grid.append([target_row[0], ""] + target_row[1:])
                elif pad_w == 0:
                    p_grid.append(target_row)
                continue

        # Case 2: Horizontal split — adjacent pages sharing service family & identical row-axis keys
        # (e.g. Zones 1-8 on odd page, Zones 9-16 on even page with same Weight rows)
        if (
            abs(sec_entry["page"] - prev["page"]) <= 1
            and sec_entry["family_key"]
            and sec_entry["family_key"] == prev["family_key"]
            and len(p_grid) == len(c_grid)
            and len(p_grid) >= 3
        ):
            p_axis = [r[0].strip().lower() for r in p_grid[1:]]
            c_axis = [r[0].strip().lower() for r in c_grid[1:]]
            # Compare axes ignoring empty cells or unit variation ("1 lb" == "1 lb")
            if p_axis == c_axis and p_hdr[1:] != c_hdr[1:]:
                merged_grid: List[List[str]] = []
                for idx in range(len(p_grid)):
                    merged_grid.append(p_grid[idx] + c_grid[idx][1:])
                prev["grid"] = merged_grid
                continue

        stitched.append(sec_entry)

    return stitched


def _derive_sheet_tab_name(preamble: List[str], page: int, idx: int, section_type: str, used_names: set) -> str:
    raw = ""
    # Prefer capitalized title lines mentioning service / rates / tariff / freight over lowercase prose tails
    for ln in preamble:
        if (
            any(k in ln.lower() for k in ("rates", "tariff", "freight", "overnight", "2day", "economy", "ground", "zone chart", "door-to-"))
            and not ln.lower().startswith("rate per")
            and not ln.lower().startswith("for shipments")
        ):
            raw = ln
            break
    if not raw:
        for ln in preamble:
            if _looks_like_section_title(ln) and ln[:1].isupper() and not ln.lower().startswith("rate per"):
                raw = ln
                break
    if not raw:
        raw = f"Notes Page {page}" if section_type == "reference" else f"Tariff Page {page}"

    # Shorten long carrier prefixes while keeping distinguishable names
    cleaned = re.sub(r"[\[\]:*?/\\]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if section_type == "reference" and "note" not in cleaned.lower() and "rule" not in cleaned.lower() and "zone" not in cleaned.lower():
        cleaned = f"Notes - {cleaned}"

    base = cleaned[:26].strip() or f"Sheet {idx + 1}"
    candidate = base[:31]
    suffix = 2
    while candidate.lower() in used_names:
        tag = f" ({suffix})"
        candidate = f"{base[:31 - len(tag)]}{tag}"
        suffix += 1
    used_names.add(candidate.lower())
    return candidate


def _extract_raw_text_from_pdf_bytes(pdf_bytes: bytes) -> List[str]:
    """
    Extracts visually ordered text lines page-by-page using the coordinate-aware
    positioning engine (preserving visual row alignment across columns).
    """
    pages_tokens = _extract_positioned_tokens_from_pdf_bytes(pdf_bytes)
    lines: List[str] = []
    for toks in pages_tokens:
        vrows = _cluster_tokens_into_visual_rows(toks)
        for vr in vrows:
            line = "  ".join(c["text"] for c in vr["cells"] if c["text"].strip())
            if line:
                lines.append(line)
    return lines


def _split_pdf_table_line_into_cells(line: str) -> List[str]:
    """Splits a single PDF text line into cells when delimiter- or multi-space-separated."""
    s = line.strip()
    if "," in s and len(s.split(",")) >= 2:
        return [c.strip() for c in next(csv.reader([s]))]
    if "|" in s and len(s.split("|")) >= 2:
        return [c.strip() for c in s.strip("|").split("|")]
    if "\t" in s:
        return [c.strip() for c in s.split("\t") if c.strip()]
    if re.search(r"\s{2,}", s):
        return [c.strip() for c in re.split(r"\s{2,}", s) if c.strip()]

    tokens = s.split()
    if len(tokens) >= 4:
        return tokens
    if len(tokens) == 2 and tokens[0].lower() in ("carrier", "currency", "tariff", "mode"):
        return tokens
    return [s]


def extract_pdf_tariff_tables(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Extracts structured, normalized, fully-labeled tables from any carrier's PDF rate sheet.

    Returns a list of dicts, each containing:
    - sheet_name: Unique tab name (<= 31 chars, Excel/Failsafe compatible)
    - section_type: 'rate_grid' | 'reference'
    - archetype: 'ltl_lane_weight' | 'skid_matrix' | 'fixed_origin_outbound' | 'transposed_weight_zone' | 'reference_notes'
    - currency_hint: 'CAD' | 'USD' | None
    - unit_hint: 'lb' | 'kg'
    - headers: List[str] (guaranteed descriptive non-empty titles)
    - rows: List[List[str]]
    - grid: List[List[str]] ([headers] + rows)
    - preamble: List[str]
    """
    if not pdf_bytes or not pdf_bytes.lstrip().startswith(b"%PDF"):
        raise ValueError("Invalid PDF file: missing %PDF header signature.")

    pages_tokens = _extract_positioned_tokens_from_pdf_bytes(pdf_bytes)
    if not pages_tokens:
        raise ValueError("Could not extract any readable text or table rows from PDF rate sheet.")

    raw_sections: List[Dict[str, Any]] = []
    all_lines_fallback: List[str] = []

    for page_idx, toks in enumerate(pages_tokens, start=1):
        vrows = _cluster_tokens_into_visual_rows(toks)
        for vr in vrows:
            all_lines_fallback.append("  ".join(c["text"] for c in vr["cells"]))
        raw_sections.extend(_segment_page_sections(vrows, page_num=page_idx))

    stitched = _stitch_raw_sections(raw_sections)
    tables: List[Dict[str, Any]] = []
    used_names: set = set()

    for idx, sec in enumerate(stitched):
        temp_title = f"Section {idx + 1}"
        norm = _classify_and_normalize_table(sec["grid"], sec["preamble"], temp_title)
        if not norm or not norm.get("headers"):
            continue
        tab_name = _derive_sheet_tab_name(
            sec["preamble"],
            page=sec["page"],
            idx=idx,
            section_type=norm["section_type"],
            used_names=used_names,
        )
        norm["sheet_name"] = tab_name
        tables.append(norm)

    # Sort primary rate grids before reference/notes tabs so Sheet[0] is immediately usable
    tables.sort(key=lambda t: (0 if t.get("section_type") == "rate_grid" else 1))

    # Ultimate fallback: return a structured line grid if PDF had purely single-column prose
    if not tables and all_lines_fallback:
        split_rows = [_split_pdf_table_line_into_cells(ln) for ln in all_lines_fallback if ln.strip()]
        split_rows = [r for r in split_rows if r]
        if split_rows:
            max_w = max(len(r) for r in split_rows)
            hdrs = _ensure_descriptive_column_titles(split_rows[0], split_rows[1:], "ltl_lane_weight", [])
            padded = [r + [""] * (max_w - len(r)) for r in split_rows[1:]]
            tables.append({
                "sheet_name": "PDF Rate Sheet",
                "section_type": "rate_grid",
                "archetype": "ltl_lane_weight",
                "currency_hint": None,
                "unit_hint": "lb",
                "preamble": [],
                "headers": hdrs,
                "rows": padded,
                "grid": [hdrs] + padded,
            })

    if not tables:
        raise ValueError("PDF rate sheet contained no extractable rate rows.")

    return tables


def convert_pdf_tariff_bytes_to_csv_text(pdf_bytes: bytes) -> str:
    """
    Converts any native carrier PDF rate sheet into normalized CSV text with
    labeled headers, suitable for deterministic parsing by `QuotelyticsExtractor._extract_csv()`.
    """
    tables = extract_pdf_tariff_tables(pdf_bytes)
    out_buf = io.StringIO()
    writer = csv.writer(out_buf, lineterminator="\n")

    # Emit detected top-level Currency / Weight Unit metadata first
    first_rate = next((t for t in tables if t.get("section_type") == "rate_grid"), tables[0])
    if first_rate.get("currency_hint"):
        writer.writerow(["Currency", first_rate["currency_hint"]])
    if first_rate.get("unit_hint"):
        writer.writerow(["Weight Unit", first_rate["unit_hint"]])

    for t in tables:
        for pre_line in t.get("preamble") or []:
            if _ORIGIN_PREAMBLE_RE.search(pre_line) or "fedex" in pre_line.lower() or "day & ross" in pre_line.lower() or "purolator" in pre_line.lower():
                writer.writerow([pre_line])
        if t.get("headers"):
            writer.writerow(t["headers"])
        for row in t.get("rows") or []:
            writer.writerow(row)
        writer.writerow([])

    csv_text = out_buf.getvalue()
    if not csv_text.strip():
        raise ValueError("PDF rate sheet contained no extractable rate rows.")
    return csv_text
