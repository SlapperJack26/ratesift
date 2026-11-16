"""Quotelytics Test Suite Runner
Executes all unit, integration, security, and compliance tests across the platform.

Usage:
    python run_tests.py
    python run_tests.py -v
"""
import sys
import subprocess
import os

TEST_FILES = [
    "tests/test_final_free_action_items.py",
    "tests/test_groups_4_5_6.py",
    "tests/test_server_hardening_group_3.py",
    "tests/test_groups_1_and_2.py",
    "tests/test_no_unauthenticated_fallback.py",
    "tests/test_terms_and_refunds.py",
    "tests/test_password_reset_and_email_verification.py",
    "tests/test_pipeda_privacy_compliance.py"
]

def main():
    print("=" * 70)
    print("QUOTELYTICS INC. — AUTOMATED VERIFICATION SUITE")
    print("Running 53 comprehensive automated tests across all platform modules...")
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
