"""
1-Click Rollback Script for RateSift Agent Playground
Immediately reverts agent_playground to the latest 'baseline' snapshot.

Usage:
    python agent_playground/revert.py
"""
import sys
import os

PLAYGROUND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLAYGROUND_DIR)

from snapshot_manager import restore_snapshot

if __name__ == "__main__":
    print("=" * 70)
    print(" [ROLLBACK] Reverting Agent Playground to baseline snapshot...")
    print("=" * 70)
    restore_snapshot("baseline")
