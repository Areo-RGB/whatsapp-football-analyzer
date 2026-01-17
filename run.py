#!/usr/bin/env python3
"""
WhatsApp Football Event Analyzer - Quick Run Script

Syncs messages from the last week, runs OCR on images,
analyzes with AI, sends results to the Termine group,
and syncs events to Google Calendar.

Usage:
    python run.py              # Sync + analyze + send + calendar
    python run.py --dry-run    # Sync + analyze, don't send/sync
    python run.py --full       # Force full resync (clears events)
    python run.py --list       # Just list current events
    python run.py --no-calendar  # Skip Google Calendar sync
"""

import subprocess
import sys
import time
from pathlib import Path

# Project settings
PROJECT_DIR = Path(__file__).parent
VENV_PYTHON = PROJECT_DIR / "venv" / "bin" / "python"
GROUP_NAME = "Jahrgang 2014er Trainer"
EVENTS_FILE = PROJECT_DIR / "data" / "events.json"
SYNC_FILE = PROJECT_DIR / "data" / "last_sync.txt"


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and print status."""
    print(f"\n{'='*60}")
    print(f"📌 {description}")
    print(f"{'='*60}")
    
    start = time.time()
    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    elapsed = time.time() - start
    
    print(f"⏱️  Took {elapsed:.1f}s")
    return result.returncode == 0


def sync_to_calendar(python: str) -> bool:
    """Sync events to Google Calendar."""
    print(f"\n{'='*60}")
    print("📌 Syncing to Google Calendar 'Spiele'")
    print(f"{'='*60}")
    
    start = time.time()
    
    # Import and run calendar sync
    import json
    try:
        # Add project to path
        sys.path.insert(0, str(PROJECT_DIR))
        from src.calendar_sync import sync_events_to_calendar
        from src.extractor import Event
        
        # Load events
        if not EVENTS_FILE.exists():
            print("  No events to sync")
            return True
        
        with open(EVENTS_FILE, 'r') as f:
            events_data = json.load(f)
        
        events = [Event.from_dict(e) for e in events_data]
        
        # Filter events with dates
        events_with_dates = [e for e in events if e.date]
        
        if not events_with_dates:
            print("  No events with dates to sync")
            return True
        
        # Sync to calendar
        results = sync_events_to_calendar(events_with_dates)
        
        elapsed = time.time() - start
        print(f"⏱️  Took {elapsed:.1f}s")
        
        return results.get('success', False)
        
    except Exception as e:
        print(f"  ❌ Calendar sync error: {e}")
        elapsed = time.time() - start
        print(f"⏱️  Took {elapsed:.1f}s")
        return False


def main():
    # Parse args
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    full_sync = "--full" in args
    list_only = "--list" in args
    no_calendar = "--no-calendar" in args
    
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"
    
    print("\n⚽ WhatsApp Football Event Analyzer")
    print("=" * 60)
    
    if list_only:
        run_command([python, "-m", "src.main", "list"], "Current events")
        return
    
    # Clear events for full sync
    if full_sync:
        print("\n🗑️  Clearing events for full resync...")
        EVENTS_FILE.write_text("[]")
        if SYNC_FILE.exists():
            SYNC_FILE.unlink()
    
    # Step 1: Sync + OCR + AI
    sync_cmd = [python, "-m", "src.main", "sync", "--group", GROUP_NAME]
    if full_sync:
        sync_cmd.append("--full")
    
    if not run_command(sync_cmd, "Sync WhatsApp → OCR → AI Analysis"):
        print("\n❌ Sync failed!")
        sys.exit(1)
    
    # Step 2: List events
    run_command([python, "-m", "src.main", "list", "--format", "compact"], "Events found")
    
    # Step 3: Send to Termine
    if dry_run:
        print("\n🔸 Dry run mode - not sending")
        run_command(
            [python, "-m", "src.main", "notify", "--filter", "week", "--dry-run"],
            "Preview: This week"
        )
    else:
        run_command(
            [python, "-m", "src.main", "notify", "--filter", "week"],
            "Sending to Termine"
        )
    
    # Step 4: Sync to Google Calendar
    if not dry_run and not no_calendar:
        sync_to_calendar(python)
    elif no_calendar:
        print("\n🔸 Skipping Google Calendar sync")
    
    print("\n" + "=" * 60)
    print("✅ Done!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
