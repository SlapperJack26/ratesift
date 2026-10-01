"""
RateSift Playground Snapshot & Revert Manager
Provides single-command snapshot creation, listing, and rollback for agent_playground.
Guarantees you can safely test experiments and revert changes immediately if anything fails.

Usage:
    python agent_playground/snapshot_manager.py --save baseline
    python agent_playground/snapshot_manager.py --restore baseline
    python agent_playground/snapshot_manager.py --list
"""
import os
import sys
import shutil
import zipfile
import datetime

PLAYGROUND_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(PLAYGROUND_DIR, ".snapshots")

def ensure_snapshot_dir():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

def create_snapshot(name: str = None) -> str:
    ensure_snapshot_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = name.strip() if name else f"snapshot_{timestamp}"
    zip_filename = f"{tag}.zip"
    zip_filepath = os.path.join(SNAPSHOT_DIR, zip_filename)

    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PLAYGROUND_DIR):
            # Ignore .snapshots directory and __pycache__
            if ".snapshots" in root or "__pycache__" in root:
                continue
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, PLAYGROUND_DIR)
                zipf.write(full_path, rel_path)

    print(f"+ Snapshot created successfully: {zip_filename}")
    print(f"  Path: {zip_filepath}")
    return zip_filepath

def list_snapshots():
    ensure_snapshot_dir()
    files = [f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".zip")]
    if not files:
        print("No snapshots found in agent_playground/.snapshots/")
        return

    print("=" * 70)
    print(" Available RateSift Playground Snapshots:")
    print("=" * 70)
    for f in sorted(files, reverse=True):
        f_path = os.path.join(SNAPSHOT_DIR, f)
        size_kb = os.path.getsize(f_path) / 1024.0
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f_path)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  * {f:<30} | {size_kb:>8.1f} KB | {mtime}")
    print("-" * 70)

def restore_snapshot(tag: str):
    ensure_snapshot_dir()
    target_zip = tag if tag.endswith(".zip") else f"{tag}.zip"
    target_path = os.path.join(SNAPSHOT_DIR, target_zip)

    if not os.path.exists(target_path):
        print(f"[ERROR] Snapshot '{target_zip}' does not exist in {SNAPSHOT_DIR}")
        list_snapshots()
        sys.exit(1)

    print(f"Reverting agent_playground to snapshot: {target_zip}...")

    # Extract all files over PLAYGROUND_DIR
    with zipfile.ZipFile(target_path, "r") as zipf:
        zipf.extractall(PLAYGROUND_DIR)

    print(f"+ Successfully reverted agent_playground to '{target_zip}'!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="RateSift Playground Snapshot & Rollback Utility")
    parser.add_argument("--save", type=str, nargs="?", const="baseline", help="Create a snapshot with given tag (default: baseline)")
    parser.add_argument("--restore", type=str, help="Restore playground to specified snapshot tag")
    parser.add_argument("--list", action="store_true", help="List all available snapshots")

    args = parser.parse_args()

    if args.list:
        list_snapshots()
    elif args.restore:
        restore_snapshot(args.restore)
    elif args.save:
        create_snapshot(args.save)
    else:
        # Default action: create baseline snapshot
        create_snapshot("baseline")
