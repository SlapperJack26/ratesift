"""
Semantic interpreter and normalization utilities for user-defined Keyword Definitions.
Translates natural-language keyword meanings (e.g., "less than 5 skids", "500 to 999 lbs",
"Origin City", "Minimum Charge") into deterministic mapping rules consumed by:
- services/break_header_parser.py
- app/detect.py & app/main.py
- services/quotelytics_extractor.py
- agent/dynamic_sheet_detector.py & app/agent_adapter.py
"""
import re
from typing import Any, Dict, Optional


def normalize_keyword_key(keyword: Any) -> str:
    """Normalizes a header keyword for case-insensitive, whitespace-collapsed matching."""
    if keyword is None:
        return ""
    return " ".join(str(keyword).strip().upper().split())


def _parse_number(num_str: str) -> float:
    return float(num_str.replace(",", "").strip())


def interpret_keyword_definition(keyword: str, definition_text: str) -> Dict[str, Any]:
    """
    Parses a user's plain-English definition into a structured rule dictionary:
    {
        "parsed_category": "SKID_BREAK" | "WEIGHT_BREAK" | "COLUMN_ROLE" | "SURCHARGE_SYNONYM" | "CUSTOM_GLOSSARY",
        "parsed_rule": { ... },
        "badge_label": str
    }
    """
    kw_clean = str(keyword or "").strip()
    raw_def = str(definition_text or "").strip()
    norm = " ".join(raw_def.lower().split())
    decomma = re.sub(r"(?<=\d),(?=\d)", "", norm)

    # -------------------------------------------------------------------------
    # 1. SKID / PALLET BREAK DEFINITIONS
    # -------------------------------------------------------------------------
    skid_unit_pat = r"(?:skids?|pallets?|skd|plts?|pl)\b"
    if re.search(skid_unit_pat, decomma, re.I):
        # First check if it's a column role like "skid count" / "number of skids" (no numbers)
        if not re.search(r"\d", decomma) and any(
            phrase in decomma
            for phrase in ("count", "number of", "num of", "qty", "quantity", "total skids", "total pallets", "column")
        ):
            return {
                "parsed_category": "COLUMN_ROLE",
                "parsed_rule": {
                    "role": "skid_count",
                    "raw_meaning": raw_def,
                    "badge_label": "Column Role: Skid Count",
                },
                "badge_label": "Column Role: Skid Count",
            }

        # 1a. Range: "1 to 4 skids", "1-4 skids", "between 2 and 5 pallets"
        m_skid_range = re.search(
            r"(?:between\s+)?(\d+)\s*(?:[-–]|\bto\b|\band\b)\s*(\d+)\s*" + skid_unit_pat,
            decomma,
            re.I,
        )
        if m_skid_range:
            n1 = max(1, int(m_skid_range.group(1)))
            n2 = max(n1, int(m_skid_range.group(2)))
            badge = f"Skid Tier: {n1}–{n2} Skids" if n1 != n2 else f"Skid Tier: {n1} Skid{'s' if n1 != 1 else ''}"
            return {
                "parsed_category": "SKID_BREAK",
                "parsed_rule": {
                    "mode": "skid",
                    "min_units": n1,
                    "max_units": n2,
                    "is_open_ended": False,
                    "is_under": False,
                    "break_unit": "SKID",
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

        # 1b. Strict Less Than: "less than 5 skids", "under 5 skids", "< 5 skids", "fewer than 5 pallets", "below 5 skids"
        m_skid_less = re.search(
            r"(?:less\s+than|under|fewer\s+than|below|<(?!=))\s*(\d+)\s*" + skid_unit_pat,
            decomma,
            re.I,
        )
        if m_skid_less:
            n = int(m_skid_less.group(1))
            max_u = max(1, n - 1) if n > 1 else 1
            badge = f"Skid Tier: 1–{max_u} Skids" if max_u > 1 else "Skid Tier: 1 Skid"
            return {
                "parsed_category": "SKID_BREAK",
                "parsed_rule": {
                    "mode": "skid",
                    "min_units": 1,
                    "max_units": max_u,
                    "threshold_units": n,
                    "is_open_ended": False,
                    "is_under": True,
                    "break_unit": "SKID",
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

        # 1c. Inclusive Upper Bound: "up to 5 skids", "<= 5 skids", "5 skids or less", "5 or fewer skids", "max 5 skids"
        m_skid_upto = re.search(
            r"(?:(?:up\s+to|<=|max(?:imum)?(?:\s+of)?|at\s+most)\s*(\d+)\s*" + skid_unit_pat
            + r"|(\d+)\s*(?:or\s+less|or\s+fewer|or\s+under)\s*" + skid_unit_pat
            + r"|(\d+)\s*" + skid_unit_pat + r"\s*(?:or\s+less|or\s+fewer|or\s+under))",
            decomma,
            re.I,
        )
        if m_skid_upto:
            num_str = m_skid_upto.group(1) or m_skid_upto.group(2) or m_skid_upto.group(3)
            n = max(1, int(num_str))
            badge = f"Skid Tier: 1–{n} Skids" if n > 1 else "Skid Tier: 1 Skid"
            return {
                "parsed_category": "SKID_BREAK",
                "parsed_rule": {
                    "mode": "skid",
                    "min_units": 1,
                    "max_units": n,
                    "is_open_ended": False,
                    "is_under": True,
                    "break_unit": "SKID",
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

        # 1d. Strict Greater Than: "more than 5 skids", "over 5 skids", "> 5 skids", "above 5 skids"
        m_skid_gt = re.search(
            r"(?:more\s+than|greater\s+than|over|above|>(?!=))\s*(\d+)\s*" + skid_unit_pat,
            decomma,
            re.I,
        )
        if m_skid_gt:
            n = int(m_skid_gt.group(1))
            min_u = n + 1
            badge = f"Skid Tier: {min_u}+ Skids"
            return {
                "parsed_category": "SKID_BREAK",
                "parsed_rule": {
                    "mode": "skid",
                    "min_units": min_u,
                    "max_units": 10,
                    "is_open_ended": True,
                    "is_under": False,
                    "break_unit": "SKID",
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

        # 1e. Inclusive Lower Bound: "5+ skids", "5 or more skids", ">= 5 skids", "at least 5 skids"
        m_skid_gte = re.search(
            r"(?:(?:>=|at\s+least|minimum\s+of)\s*(\d+)\s*" + skid_unit_pat
            + r"|(\d+)\s*(?:\+|\bor\s+more)\s*" + skid_unit_pat
            + r"|(\d+)\s*" + skid_unit_pat + r"\s*(?:\+|\bor\s+more))",
            decomma,
            re.I,
        )
        if m_skid_gte:
            num_str = m_skid_gte.group(1) or m_skid_gte.group(2) or m_skid_gte.group(3)
            n = max(1, int(num_str))
            badge = f"Skid Tier: {n}+ Skids"
            return {
                "parsed_category": "SKID_BREAK",
                "parsed_rule": {
                    "mode": "skid",
                    "min_units": n,
                    "max_units": max(10, n),
                    "is_open_ended": True,
                    "is_under": False,
                    "break_unit": "SKID",
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

        # 1f. Exact Skid Count: "5 skids", "1 pallet", "exactly 3 skids"
        m_skid_exact = re.search(r"(?:exactly\s+)?(\d+)\s*" + skid_unit_pat, decomma, re.I)
        if m_skid_exact:
            n = max(1, int(m_skid_exact.group(1)))
            badge = f"Skid Tier: {n} Skid{'s' if n != 1 else ''}"
            return {
                "parsed_category": "SKID_BREAK",
                "parsed_rule": {
                    "mode": "skid",
                    "min_units": n,
                    "max_units": n,
                    "is_open_ended": False,
                    "is_under": False,
                    "break_unit": "SKID",
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

    # -------------------------------------------------------------------------
    # 2. WEIGHT BREAK DEFINITIONS
    # -------------------------------------------------------------------------
    wt_unit_pat = r"(lbs?|pounds?|kgs?|kilograms?|cwt|#)"
    m_wt_unit = re.search(wt_unit_pat, decomma, re.I)
    if m_wt_unit and re.search(r"\d", decomma):
        raw_u = m_wt_unit.group(1).lower()
        is_cwt = raw_u == "cwt"
        unit = "kg" if raw_u.startswith("kg") or raw_u.startswith("kilo") else "lb"
        mult = 100.0 if is_cwt else 1.0

        # 2a. Range: "500 to 999 lbs", "100-499 kg"
        m_wt_range = re.search(
            r"(?:between\s+)?(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?|kgs?|kilograms?|cwt|#)?\s*(?:[-–]|\bto\b|\band\b)\s*(\d+(?:\.\d+)?)",
            decomma,
            re.I,
        )
        if m_wt_range:
            v1 = _parse_number(m_wt_range.group(1)) * mult
            v2 = _parse_number(m_wt_range.group(2)) * mult
            if v2 >= v1:
                badge = f"Weight Break: {int(v1)}–{int(v2)} {unit}s"
                return {
                    "parsed_category": "WEIGHT_BREAK",
                    "parsed_rule": {
                        "mode": "weight",
                        "min_weight": v1,
                        "max_weight": v2,
                        "is_open_ended": False,
                        "is_under": False,
                        "break_value": v1,
                        "unit": unit,
                        "raw_meaning": raw_def,
                        "badge_label": badge,
                    },
                    "badge_label": badge,
                }

        # 2b. Less than / under: "less than 500 lbs", "under 500 lbs", "< 500 lbs"
        m_wt_less = re.search(
            r"(?:less\s+than|under|fewer\s+than|below|<(?!=))\s*(\d+(?:\.\d+)?)",
            decomma,
            re.I,
        )
        if m_wt_less:
            val = _parse_number(m_wt_less.group(1)) * mult
            cap = val - 1.0 if val >= 100 else val
            badge = f"Weight Break: 0–{int(cap)} {unit}s"
            return {
                "parsed_category": "WEIGHT_BREAK",
                "parsed_rule": {
                    "mode": "weight",
                    "min_weight": 0.0,
                    "max_weight": cap,
                    "is_open_ended": False,
                    "is_under": True,
                    "break_value": cap,
                    "unit": unit,
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

        # 2c. Up to / inclusive upper bound: "up to 500 lbs", "<= 500 lbs"
        m_wt_upto = re.search(
            r"(?:up\s+to|<=|max(?:imum)?(?:\s+of)?)\s*(\d+(?:\.\d+)?)",
            decomma,
            re.I,
        )
        if m_wt_upto:
            val = _parse_number(m_wt_upto.group(1)) * mult
            badge = f"Weight Break: 0–{int(val)} {unit}s"
            return {
                "parsed_category": "WEIGHT_BREAK",
                "parsed_rule": {
                    "mode": "weight",
                    "min_weight": 0.0,
                    "max_weight": val,
                    "is_open_ended": False,
                    "is_under": True,
                    "break_value": val,
                    "unit": unit,
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

        # 2d. Open-ended / threshold weight break: "1000+ lbs", "over 1000 lbs", "500 lbs"
        m_wt_open = re.search(r"(\d+(?:\.\d+)?)", decomma)
        if m_wt_open:
            val = _parse_number(m_wt_open.group(1)) * mult
            badge = f"Weight Break: {int(val)}+ {unit}s"
            return {
                "parsed_category": "WEIGHT_BREAK",
                "parsed_rule": {
                    "mode": "weight",
                    "min_weight": val,
                    "max_weight": None,
                    "is_open_ended": True,
                    "is_under": False,
                    "break_value": val,
                    "unit": unit,
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

    # -------------------------------------------------------------------------
    # 3. COLUMN ROLE DEFINITIONS (Origin, Destination, Minimum Charge, etc.)
    # -------------------------------------------------------------------------
    if norm in (
        "origin", "origin city", "ship from", "pickup", "pickup city", "pickup location",
        "from", "shipper", "shipper city", "origin postal", "origin postal code", "origin zip",
        "origin location", "shipping point"
    ):
        badge = "Column Role: Origin"
        return {
            "parsed_category": "COLUMN_ROLE",
            "parsed_rule": {"role": "origin", "raw_meaning": raw_def, "badge_label": badge},
            "badge_label": badge,
        }

    if norm in (
        "destination", "destination city", "ship to", "delivery", "delivery city", "delivery location",
        "to", "consignee", "consignee city", "dest", "destination postal", "destination postal code",
        "destination zip", "destination location", "receiving point"
    ):
        badge = "Column Role: Destination"
        return {
            "parsed_category": "COLUMN_ROLE",
            "parsed_rule": {"role": "destination", "raw_meaning": raw_def, "badge_label": badge},
            "badge_label": badge,
        }

    if norm in ("origin province", "origin state", "orig prov", "opr", "origin region", "pickup province"):
        badge = "Column Role: Origin Province/State"
        return {
            "parsed_category": "COLUMN_ROLE",
            "parsed_rule": {"role": "origin_region", "raw_meaning": raw_def, "badge_label": badge},
            "badge_label": badge,
        }

    if norm in ("destination province", "destination state", "dest prov", "dpr", "destination region", "delivery province"):
        badge = "Column Role: Destination Province/State"
        return {
            "parsed_category": "COLUMN_ROLE",
            "parsed_rule": {"role": "dest_region", "raw_meaning": raw_def, "badge_label": badge},
            "badge_label": badge,
        }

    if norm in (
        "minimum charge", "min charge", "minimum", "min", "base cost", "base charge",
        "flat rate", "mc", "floor charge", "minimum rate", "min rate"
    ):
        badge = "Column Role: Minimum / Base Charge"
        return {
            "parsed_category": "COLUMN_ROLE",
            "parsed_rule": {"role": "base_cost", "raw_meaning": raw_def, "badge_label": badge},
            "badge_label": badge,
        }

    if norm in (
        "skid count", "number of skids", "pallet count", "number of pallets",
        "skids column", "total skids", "skid qty"
    ):
        badge = "Column Role: Skid Count"
        return {
            "parsed_category": "COLUMN_ROLE",
            "parsed_rule": {"role": "skid_count", "raw_meaning": raw_def, "badge_label": badge},
            "badge_label": badge,
        }

    if norm in ("transit days", "transit time", "service days", "delivery days", "est days", "transit"):
        badge = "Column Role: Transit Days"
        return {
            "parsed_category": "COLUMN_ROLE",
            "parsed_rule": {"role": "transit_days", "raw_meaning": raw_def, "badge_label": badge},
            "badge_label": badge,
        }

    # -------------------------------------------------------------------------
    # 4. SURCHARGE / ACCESSORIAL SYNONYMS
    # -------------------------------------------------------------------------
    surcharge_map = {
        "liftgate": ("POWER_TAILGATE", "Power Tailgate / Liftgate"),
        "tailgate": ("POWER_TAILGATE", "Power Tailgate / Liftgate"),
        "power tailgate": ("POWER_TAILGATE", "Power Tailgate / Liftgate"),
        "appointment": ("APPOINTMENT", "Appointment Delivery"),
        "delivery appointment": ("APPOINTMENT", "Appointment Delivery"),
        "residential": ("RESIDENTIAL_DELIVERY", "Residential / Private Delivery"),
        "private residence": ("RESIDENTIAL_DELIVERY", "Residential / Private Delivery"),
        "limited access": ("RESIDENTIAL_DELIVERY", "Limited Access Delivery"),
        "heated": ("PROTECTIVE_SERVICE", "Protective / Heated Service"),
        "protective service": ("PROTECTIVE_SERVICE", "Protective / Heated Service"),
        "protect from freeze": ("PROTECTIVE_SERVICE", "Protective / Heated Service"),
        "hazmat": ("DANGEROUS_GOODS", "Dangerous Goods / Hazmat"),
        "dangerous goods": ("DANGEROUS_GOODS", "Dangerous Goods / Hazmat"),
        "inside delivery": ("INSIDE_PICKUP_DELIVERY", "Inside Pickup / Delivery"),
        "fuel surcharge": ("FUEL_FSC", "Fuel Surcharge (FSC)"),
        "fsc": ("FUEL_FSC", "Fuel Surcharge (FSC)"),
    }
    for s_key, (s_code, s_label) in surcharge_map.items():
        if norm == s_key or f"{s_key} surcharge" == norm or f"{s_key} fee" == norm:
            badge = f"Accessorial: {s_label}"
            return {
                "parsed_category": "SURCHARGE_SYNONYM",
                "parsed_rule": {
                    "surcharge_code": s_code,
                    "surcharge_name": s_label,
                    "raw_meaning": raw_def,
                    "badge_label": badge,
                },
                "badge_label": badge,
            }

    # -------------------------------------------------------------------------
    # 5. FALLBACK: CUSTOM AI GLOSSARY RULE
    # -------------------------------------------------------------------------
    badge = f"AI Mapping Rule: {raw_def[:40]}"
    return {
        "parsed_category": "CUSTOM_GLOSSARY",
        "parsed_rule": {
            "keyword": kw_clean,
            "raw_meaning": raw_def,
            "badge_label": badge,
        },
        "badge_label": badge,
    }
