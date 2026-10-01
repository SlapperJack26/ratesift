"""
RateSift Main Website Rollback & Revert Utility
Quickly restores the website codebase to a snapshot backup.

Usage:
    python revert_website.py                         # Reverts to pre_agent_upgrade_baseline.zip
    python revert_website.py --snapshot <name.zip>   # Reverts to a specific snapshot
    python revert_website.py --list                  # Lists available website snapshots
"""
import os
import sys
import zipfile
import shutil

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(ROOT_DIR, ".website_snapshots")

def list_snapshots():
    if not os.path.exists(SNAP_DIR):
        print("No snapshots directory found.")
        return
    files = [f for f in os.listdir(SNAP_DIR) if f.endswith(".zip")]
    if not files:
        print("No website snapshots found.")
        return
    print("=" * 60)
    print("Available Main Website Snapshots:")
    print("=" * 60)
    for f in sorted(files, reverse=True):
        fp = os.path.join(SNAP_DIR, f)
        kb = os.path.getsize(fp) / 1024.0
        print(f"  * {f:<35} ({kb:>6.1f} KB)")
    print("-" * 60)

def restore_snapshot(filename="pre_agent_upgrade_baseline.zip"):
    if not filename.endswith(".zip"):
        filename += ".zip"
    zip_path = os.path.join(SNAP_DIR, filename)
    if not os.path.exists(zip_path):
        print(f"Error: Snapshot not found at {zip_path}")
        list_snapshots()
        sys.exit(1)

    print(f"Restoring main website from: {zip_path}...")
    with zipfile.ZipFile(zip_path, "r") as zipf:
        zipf.extractall(ROOT_DIR)

    print("Success: Main website files successfully restored to snapshot state.")

if __name__ == "__main__":
    if "--list" in sys.argv:
        list_snapshots()
    elif "--snapshot" in sys.argv:
        idx = sys.argv.index("--snapshot")
        if idx + 1 < len(sys.argv):
            restore_snapshot(sys.argv[idx + 1])
        else:
            print("Please specify a snapshot filename.")
    else:
        restore_snapshot("pre_agent_upgrade_baseline.zip")
