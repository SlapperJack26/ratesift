"""
RateSift Rules Specification & Compliance Auditor (Expanded to 36 Rules)
Provides programmatic definitions, validators, and audit trackers for all RateSift Rules.
Incorporates the 7-tier classification and cell-level distinction specifications.
"""
from typing import Dict, Any, List

RATESIFT_36_RULES = {
    1: {"name": "Explicit extraction & stated surcharge values", "desc": "Never guess or interpolate missing rates/breaks. Only apply surcharge values stated as specific numbers or percentages; never infer surcharge amounts from vague language."},
    2: {"name": "Normalized schema", "desc": "Convert all sheets into standard matrix tables before quoting."},
    3: {"name": "Source traceability", "desc": "Record cell coordinates (Sheet!Row,Col) for every extracted value."},
    4: {"name": "Footnotes, hidden data & marker resolution", "desc": "Read notes, footnotes, multi-row terms, and hidden columns. When rate tables reference footnotes (superscripts, asterisks, letter codes), resolve the full footnote text and attach it to the relevant rate or surcharge before confirmation."},
    5: {"name": "Unit and currency detection", "desc": "Explicitly capture CAD/USD, lb/kg, and in/cm."},
    6: {"name": "Needs review flagging & ambiguity routing", "desc": "Flag low-confidence items as needs_review = 1. If a cell's classification is ambiguous or a number appears inside a prose sentence rather than a table structure, mark it 'needs review' rather than guessing."},
    7: {"name": "Human confirmation gate & category review", "desc": "Require confirmation before any sheet is usable for live quoting. During confirmation, display classified categories alongside raw sheets so reviewers can verify nothing was misfiled (e.g. phone numbers mistaken for rates)."},
    8: {"name": "Deterministic pricing", "desc": "Calculate every quote with deterministic Python code, never LLMs."},
    9: {"name": "Dimensional weight rules", "desc": "Divisors (e.g. 139), density PCF rules, and bill on greater."},
    10: {"name": "Carrier zone resolution", "desc": "Origin/Destination mapping using carrier's own zones."},
    11: {"name": "Conditional surcharges", "desc": "Flat, percentage, CWT, and waived accessorial evaluations."},
    12: {"name": "Minimum charge comparison", "desc": "Enforce carrier minimum charge floor."},
    13: {"name": "Full breakdown transparency", "desc": "Never show bare totals; itemize base, surcharges, minimums."},
    14: {"name": "Deterministic consistency", "desc": "Idempotent calculation guarantees identical results every time."},
    15: {"name": "Final-step rounding", "desc": "Half-up to 2 decimal places at final step only."},
    16: {"name": "Effective date filtering", "desc": "Exclude future/expired sheets with clear warnings."},
    17: {"name": "Version precedence", "desc": "Use highest confirmed tariff version; report older as superceded."},
    18: {"name": "Operational limits", "desc": "Parcel limits (150 lbs, 108 in) & LTL max capacity (44,000 lbs)."},
    19: {"name": "Confirmation enforcement", "desc": "Reject any rating call on unconfirmed sheets."},
    20: {"name": "Multi-tier ranking", "desc": "Default sort: lowest price first, transit time as tie-breaker."},
    21: {"name": "In-memory re-sorting", "desc": "Client-side sorting (Lowest Price, Fastest Transit, Best Value)."},
    22: {"name": "Comprehensive comparison", "desc": "Show all qualifying options, not just a single carrier."},
    23: {"name": "Flagged data indicators", "desc": "Visual caution badge on quote options relying on reviewed data."},
    24: {"name": "Truth in availability", "desc": "Clear lane exclusion messages if lane is not served; no guessing."},
    25: {"name": "Missing detail prompting", "desc": "Prompt for missing origin/destination or weight <= 0."},
    26: {"name": "Non-binding disclaimer", "desc": "Legal notice attached to all calculations and displayed in UI."},
    27: {"name": "Rate shift alerts", "desc": "Detect >25% rate changes vs previous sheet version."},
    28: {"name": "Customer confidentiality", "desc": "Multi-tenant data isolation; customer rates kept confidential."},
    29: {"name": "Canadian residency (WHC)", "desc": "All data residency tagged and stored in Canada (WHC)."},
    30: {"name": "Complete audit logging", "desc": "Immutable audit records with step-by-step trace."},
    31: {"name": "Freight broker terminology", "desc": "Professional terminology (Lane, FSC, Accessorials, Divisor, CWT, Min Charge)."},
    32: {"name": "Concise answers & deep breakdown", "desc": "Concise cards by default with 1-click line-item audit accordion."},
    33: {"name": "7-Category pre-extraction classification", "desc": "Before extracting any rate, classify every populated cell into: rate data, structural label, header/letterhead, metadata, surcharge/accessorial note, terms/disclaimer, or unknown."},
    34: {"name": "Letterhead and contact info exclusion", "desc": "Never treat letterhead, company name, address, phone number, or email content as rate data, even if it appears near or adjacent to the pricing table."},
    35: {"name": "Legal and promotional disclaimer quarantine", "desc": "Treat any cell containing legal or promotional language ('subject to change', 'terms and conditions', 'E&OE', 'confidential') as a disclaimer and store it separately from pricing data; never let it influence a calculated quote."},
    36: {"name": "Decorative and pagination noise filtering", "desc": "Ignore purely decorative, repeated, or pagination content (page numbers, 'Page 1 of 3', logos) with no bearing on price."}
}

# Backward compatibility alias
RATESIFT_32_RULES = RATESIFT_36_RULES

class RuleComplianceAuditor:
    """Tracks which rules were actively verified or executed in an agent run."""
    def __init__(self):
        self.fired_rules: List[int] = []
        self.audit_trace: List[Dict[str, Any]] = []

    def record_rule(self, rule_num: int, context: str, status: str = "PASSED"):
        if rule_num not in self.fired_rules:
            self.fired_rules.append(rule_num)
        self.audit_trace.append({
            "rule_number": rule_num,
            "rule_name": RATESIFT_36_RULES.get(rule_num, {}).get("name", "Unknown"),
            "context": context,
            "status": status
        })

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_rules_fired": len(self.fired_rules),
            "fired_rule_numbers": sorted(self.fired_rules),
            "trace": self.audit_trace
        }

def get_rules_summary() -> Dict[str, Any]:
    return {
        "total_rules": len(RATESIFT_36_RULES),
        "categories": {
            "Reading and parsing rate sheets": [1, 2, 3, 4, 5, 6, 7],
            "Calculating quotes": [8, 9, 10, 11, 12, 13, 14, 15],
            "Filtering and validity": [16, 17, 18, 19],
            "Ranking and output": [20, 21, 22, 23],
            "Honesty and error handling": [24, 25, 26, 27],
            "Data handling and privacy": [28, 29, 30],
            "Communication": [31, 32],
            "Document-Trained Structure Recognition & Layout Quarantine": [33, 34, 35, 36]
        }
    }
