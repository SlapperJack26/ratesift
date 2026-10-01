"""
RateSift Agent Training Ideas & Benchmark Runner
Runs the isolated copied agent against test scenarios, compares prompt variants,
audits rule compliance, and optionally exports run JSON for the standalone HTML simulator.

Usage:
    python agent_playground/run_agent_training.py
    python agent_playground/run_agent_training.py --variant variant_2_flexible_broker
    python agent_playground/run_agent_training.py --compare-all
"""
import sys
import json
import argparse
from typing import Dict, Any

from agent.rate_agent import RateSiftAgent
from agent.agent_prompts import AGENT_TRAINING_VARIANTS, TRAINING_TEST_SCENARIOS

def print_banner():
    print("=" * 80)
    print(" [TEST] RateSift Agent Training Ideas & Ideation Playground")
    print(" 100% Isolated Copy - IDE Native - Zero Website Launch Required")
    print("=" * 80)

def run_single_variant_benchmarks(variant_key: str):
    agent = RateSiftAgent(variant_key)
    print(f"\n--- Testing Training Variant: {agent.config['name']} ---")
    print(f"Description: {agent.config['description']}\n")

    passed_count = 0
    total_count = len(TRAINING_TEST_SCENARIOS)

    for s in TRAINING_TEST_SCENARIOS:
        print(f"> Running Scenario [{s['id']}]: {s['name']}")
        res = agent.run_benchmark_scenario(s["id"])

        if res.get("success"):
            passed_count += 1
            best_quote = res["quotes"][0] if res["quotes"] else None
            rules_fired = res["audit"]["total_rules_fired"]
            print(f"  + Calculated: {res['lane']} | Billable: {res['actual_weight']} lbs")
            if best_quote:
                print(f"    Best Carrier: {best_quote['carrier_name']} - ${best_quote['total_amount']:.2f} CAD ({best_quote['transit_days']} days)")
            print(f"    Rules Audited ({rules_fired}): {res['audit']['fired_rule_numbers']}")
            if res.get("decision_log"):
                for note in res["decision_log"]:
                    print(f"    [LOG] {note}")
        else:
            print(f"  [ALERT] Agent Validation: {res.get('error')}")
            print(f"    Rules Audited: {res['audit']['fired_rule_numbers']}")
        print()

    print(f"Summary for {agent.config['name']}: {passed_count}/{total_count} scenarios executed successfully.")

def compare_all_variants():
    print("\n--- Comparative Evaluation Across All Training Variants ---")
    table = []
    for v_key, v_info in AGENT_TRAINING_VARIANTS.items():
        agent = RateSiftAgent(v_key)
        total_price = 0.0
        successes = 0
        rules_set = set()

        for s in TRAINING_TEST_SCENARIOS:
            res = agent.run_benchmark_scenario(s["id"])
            if res.get("success"):
                successes += 1
                if res["quotes"]:
                    total_price += res["quotes"][0]["total_amount"]
                rules_set.update(res["audit"]["fired_rule_numbers"])

        table.append({
            "variant": v_info["name"],
            "success_rate": f"{successes}/{len(TRAINING_TEST_SCENARIOS)}",
            "unique_rules_fired": len(rules_set),
            "priority": v_info.get("rank_priority")
        })

    print(f"{'Variant Name':<42} | {'Success':<8} | {'Rules Fired':<12} | {'Priority':<8}")
    print("-" * 78)
    for row in table:
        print(f"{row['variant']:<42} | {row['success_rate']:<8} | {row['unique_rules_fired']:<12} | {row['priority']:<8}")
    print()

def main():
    parser = argparse.ArgumentParser(description="RateSift Agent Training Playground CLI")
    parser.add_argument("--variant", choices=list(AGENT_TRAINING_VARIANTS.keys()), default="variant_1_strict_32_rules", help="Select training variant to test")
    parser.add_argument("--compare-all", action="store_true", help="Compare all training variants side by side")
    parser.add_argument("--export-json", type=str, default=None, help="Export benchmark run as JSON file for HTML simulator")

    args = parser.parse_args()
    print_banner()

    if args.compare_all:
        compare_all_variants()
    else:
        run_single_variant_benchmarks(args.variant)

    if args.export_json:
        agent = RateSiftAgent(args.variant)
        runs = []
        for s in TRAINING_TEST_SCENARIOS:
            res = agent.run_benchmark_scenario(s["id"])
            runs.append({"scenario": s, "result": res})
        with open(args.export_json, "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=2)
        print(f"+ Exported {len(runs)} benchmark runs to {args.export_json}")

if __name__ == "__main__":
    main()
