"""
Scheduled PIPEDA Retention & Purge Runner (§8 of Quotelytics Privacy Policy).
Can be executed nightly via cron/systemd timer on WHC:
    python scripts/run_retention_cleanup.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db_service import init_db, enforce_retention_policies


def main() -> None:
    init_db()
    summary = enforce_retention_policies()
    print(json.dumps({"status": "ok", "retention_cleanup": summary}, indent=2))


if __name__ == "__main__":
    main()
