"""
revert_to_dual_mode.py
Restores Quotelytics to the dual-mode quoting state (Standard by Weight + Ship by LTL by Skids).
Run directly anytime with:
    python revert_to_dual_mode.py
"""
import os
import shutil
import subprocess

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(REPO_DIR, ".website_snapshots", "snapshot_current_dual_mode")

FILES_TO_RESTORE = [
    (
        os.path.join(SNAPSHOT_DIR, "templates", "console", "new_quote.html"),
        os.path.join(REPO_DIR, "templates", "console", "new_quote.html"),
    ),
    (
        os.path.join(SNAPSHOT_DIR, "main.py"),
        os.path.join(REPO_DIR, "main.py"),
    ),
    (
        os.path.join(SNAPSHOT_DIR, "tests", "test_ltl_shipping_option_and_client_proposal.py"),
        os.path.join(REPO_DIR, "tests", "test_ltl_shipping_option_and_client_proposal.py"),
    ),
]

def revert():
    print("=" * 60)
    print("REVERTING TO DUAL-MODE QUOTING STATE")
    print("=" * 60)

    # 1. First attempt restore from physical snapshot directory
    restored_from_snapshot = True
    for src, dst in FILES_TO_RESTORE:
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            rel_dst = os.path.relpath(dst, REPO_DIR)
            print(f" [OK] Restored from snapshot: {rel_dst}")
        else:
            restored_from_snapshot = False
            break

    # 2. If snapshot files were missing, restore from git tag
    if not restored_from_snapshot:
        print(" Snapshot files missing, restoring via git tag 'checkpoint-dual-mode-20261015'...")
        try:
            subprocess.run(
                ["git", "checkout", "checkpoint-dual-mode-20261015", "--",
                 "templates/console/new_quote.html", "main.py", "tests/test_ltl_shipping_option_and_client_proposal.py"],
                cwd=REPO_DIR,
                check=True
            )
            print(" [OK] Restored via git checkout.")
        except Exception as e:
            print(f" [ERROR] Could not restore from git: {e}")
            return False

    print("\nSUCCESS: Quotelytics has been reverted to the dual-mode quoting state!")
    print("Both 'Standard (by Weight)' and 'Ship by LTL (by Skids)' are active.")
    print("=" * 60)
    return True

if __name__ == "__main__":
    revert()
