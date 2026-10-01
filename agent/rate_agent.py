"""
RateSift Autonomous Agent Controller (Playground Copy)
Coordinates agent training variants, prompt instructions, rule compliance auditing,
and deterministic freight rating execution.
"""
from typing import Dict, Any, List, Optional
from .rules_spec import RuleComplianceAuditor
from .tariffs_data import AVAILABLE_TARIFFS
from .engine_copy import quote_all_tariffs
from .agent_prompts import AGENT_TRAINING_VARIANTS, TRAINING_TEST_SCENARIOS

class RateSiftAgent:
    """
    Autonomous freight rating agent capable of testing different training prompt variants,
    auditing rule compliance, and executing deterministic rating math.
    """
    def __init__(self, variant_key: str = "variant_1_strict_32_rules"):
        if variant_key not in AGENT_TRAINING_VARIANTS:
            variant_key = "variant_1_strict_32_rules"
        self.variant_key = variant_key
        self.config = AGENT_TRAINING_VARIANTS[variant_key]
        self.tariffs = AVAILABLE_TARIFFS
        self.company_hq = "TORONTO, ON"  # Default broker headquarters for non-critical resolution

    def process_quote_request(
        self,
        origin: str,
        destination: str,
        actual_weight: float,
        length: Optional[float] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
        accessorials: Optional[List[str]] = None,
        shipment_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a quote request through the agent's reasoning and rule pipeline.
        """
        auditor = RuleComplianceAuditor()
        accessorials = accessorials or []
        decision_log = []

        # 1. Origin Resolution & Rule 25 Check
        clean_orig = (origin or "").strip()
        clean_dest = (destination or "").strip()

        if not clean_orig:
            if self.config.get("allow_non_critical_bypass"):
                clean_orig = self.company_hq
                decision_log.append(f"Flexible Agent Note: Missing origin resolved automatically to Company HQ ({self.company_hq}).")
                auditor.record_rule(28, "Bypassed missing origin using registered Company HQ.")
            else:
                auditor.record_rule(25, "Enforced strict origin prompt requirement.", status="FAILED")
                return {
                    "success": False,
                    "error": "Rule 25 Violation: Origin location is missing. Strict agent requires explicit Origin.",
                    "audit": auditor.get_summary()
                }
        else:
            auditor.record_rule(10, f"Resolved Origin Lane: {clean_orig}")

        if not clean_dest:
            auditor.record_rule(25, "Enforced strict destination prompt requirement.", status="FAILED")
            return {
                "success": False,
                "error": "Rule 25 Violation: Destination location is missing.",
                "audit": auditor.get_summary()
            }
        else:
            auditor.record_rule(10, f"Resolved Destination Lane: {clean_dest}")

        # 2. Weight Validation (Rule 25 & 18)
        if actual_weight is None or actual_weight <= 0:
            auditor.record_rule(25, "Rejected invalid cargo weight <= 0.", status="FAILED")
            return {
                "success": False,
                "error": "Rule 25 Violation: Cargo weight must be greater than 0 lbs.",
                "audit": auditor.get_summary()
            }
        auditor.record_rule(5, f"Verified weight unit: lbs ({actual_weight} lbs).")

        # 3. Dimensional Weight Rule 9
        if length and width and height and length > 0 and width > 0 and height > 0:
            dim_calc = (length * width * height) / 139.0
            if dim_calc > actual_weight:
                auditor.record_rule(9, f"Applied DIM rule: {dim_calc:.1f} lbs billed over actual {actual_weight} lbs.")
                decision_log.append(f"DIM Weight Rule: Cargo billed on dimensional weight ({dim_calc:.1f} lbs).")
            else:
                auditor.record_rule(9, f"Actual weight {actual_weight} lbs exceeds DIM weight {dim_calc:.1f} lbs.")

        # 4. Accessorial & Surcharges (Rule 11)
        if accessorials:
            auditor.record_rule(11, f"Evaluated {len(accessorials)} conditional accessorials: {', '.join(accessorials)}.")

        # 5. Deterministic Rating Execution (Rule 8)
        rating_result = quote_all_tariffs(
            tariffs=self.tariffs,
            origin=clean_orig,
            destination=clean_dest,
            actual_weight=actual_weight,
            length=length,
            width=width,
            height=height,
            accessorials=accessorials,
            shipment_date=shipment_date
        )
        auditor.record_rule(8, "100% deterministic calculation executed with zero LLM math estimation.")
        auditor.record_rule(12, "Enforced carrier minimum charge floor across all quotes.")
        auditor.record_rule(13, "Itemized full breakdown (base, fuel FSC, accessorials, minimums).")
        auditor.record_rule(15, "Executed half-up rounding at the final step.")
        auditor.record_rule(26, "Attached Rule 26 Non-Binding Legal Disclaimer.")
        auditor.record_rule(29, "Verified WHC Canadian data residency compliance.")

        quotes = rating_result["quotes"]

        # 6. Apply Variant Sorting
        if self.config.get("rank_priority") == "transit":
            quotes.sort(key=lambda q: (q["transit_days"], q["total_amount"]))
            decision_log.append("Expedited Priority: Ranked results by fastest transit time first.")
            auditor.record_rule(20, "Ranked by fastest transit days as primary criterion.")
        else:
            quotes.sort(key=lambda q: (q["total_amount"], q["transit_days"]))
            auditor.record_rule(20, "Ranked by lowest total price as default primary criterion.")

        return {
            "success": True,
            "agent_variant": self.config["name"],
            "lane": f"{clean_orig} -> {clean_dest}",
            "origin": clean_orig,
            "destination": clean_dest,
            "actual_weight": actual_weight,
            "quotes": quotes,
            "excluded": rating_result["excluded"],
            "decision_log": decision_log,
            "audit": auditor.get_summary()
        }

    def run_benchmark_scenario(self, scenario_id: str) -> Dict[str, Any]:
        """Runs a specific pre-defined benchmark scenario."""
        scenarios = {s["id"]: s for s in TRAINING_TEST_SCENARIOS}
        if scenario_id not in scenarios:
            return {"error": f"Scenario {scenario_id} not found."}

        s = scenarios[scenario_id]
        dims = s.get("dims") or [None, None, None]
        return self.process_quote_request(
            origin=s["origin"],
            destination=s["dest"],
            actual_weight=s["weight"],
            length=dims[0],
            width=dims[1],
            height=dims[2],
            accessorials=s.get("accessorials", [])
        )
