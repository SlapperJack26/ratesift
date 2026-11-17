"""Quotelytics Test Suite Runner
Executes all unit, integration, security, and compliance tests across the platform.

Usage:
    python run_tests.py
    python run_tests.py -v
"""
import sys
import subprocess
import os

# Allow legacy integration tests that call /api/auth/register directly to set up test fixtures;
# tests/test_beta_proofing_access_control.py explicitly tests the default Private Beta lock (true).
os.environ.setdefault("QUOTELYTICS_BETA_INVITE_ONLY", "false")

TEST_FILES = [
    "tests/test_final_free_action_items.py",
    "tests/test_groups_4_5_6.py",
    "tests/test_server_hardening_group_3.py",
    "tests/test_groups_1_and_2.py",
    "tests/test_no_unauthenticated_fallback.py",
    "tests/test_terms_and_refunds.py",
    "tests/test_password_reset_and_email_verification.py",
    "tests/test_pipeda_privacy_compliance.py",
    "tests/test_survival_and_adoption_upgrades.py",
    "tests/test_margin_protection_and_pipeline.py",
    "tests/test_phase3_workflow_and_roi.py",
    "tests/test_phase4_audit_rfp_and_growth.py",
    "tests/test_phase5_edge_cases_and_team_guardrails.py",
    "tests/test_beta_proofing_access_control.py",
]

def main():
    print("=" * 70)
    print("QUOTELYTICS INC. — AUTOMATED VERIFICATION SUITE")
    print("Running 84 comprehensive automated tests across all platform modules...")
    print("=" * 70)

    args = [sys.executable, "-u", "-m", "pytest"] + TEST_FILES
    if len(sys.argv) > 1:
        args.extend(sys.argv[1:])
    else:
        args.append("-v")

    result = subprocess.run(args)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
