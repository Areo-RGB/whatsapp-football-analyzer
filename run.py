#!/usr/bin/env python3
"""
WhatsApp Football Event Analyzer - Quick Run Script

Syncs messages from the last week, runs OCR on images,
analyzes with AI (or regex), sends results to the Termine group,
and syncs events to Google Calendar.

Usage:
    python run.py              # Sync + AI analyze + send + calendar
    python run.py --regex      # Use regex analyzer (no AI) on wacli messages
    python run.py --regex-file # Use regex analyzer on exported chat file
    python run.py --dry-run    # Sync + analyze, don't send/sync
    python run.py --full       # Force full resync (clears events)
    python run.py --list       # Just list current events
    python run.py --no-calendar  # Skip Google Calendar sync
"""

import subprocess
import sys
import time
import json
from pathlib import Path
from datetime import datetime, timedelta

# Project settings
PROJECT_DIR = Path(__file__).parent
VENV_PYTHON = PROJECT_DIR / "venv" / "bin" / "python"
GROUP_NAME = "Jahrgang 2014er Trainer"
EVENTS_FILE = PROJECT_DIR / "data" / "events.json"
SYNC_FILE = PROJECT_DIR / "data" / "last_sync.txt"
CHAT_EXPORT_FILE = PROJECT_DIR / "WhatsApp Chat with Jahrgang 2014er Trainer.txt"
TEMP_MSGS_FILE = PROJECT_DIR / "temp_msgs.json"


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


def run_regex_analyzer_on_wacli(python: str, full_sync: bool = False) -> bool:
    """
    Fetch messages from wacli and run regex analyzer on them.
    Converts wacli messages to WhatsApp export format for the regex analyzer.
    """
    print(f"\n{'='*60}")
    print("📌 Fetching messages from WhatsApp (wacli)")
    print(f"{'='*60}")

    start = time.time()

    try:
        # Add project to path
        sys.path.insert(0, str(PROJECT_DIR))
        from src.whatsapp import WacliClient, check_wacli, find_group_by_name

        if not check_wacli():
            print("  ❌ wacli not installed")
            return False

        client = WacliClient()
        if not client.is_authenticated():
            print("  ❌ wacli not authenticated. Run 'wacli auth' first.")
            return False

        # Find the group
        target_group = find_group_by_name(client, GROUP_NAME)
        if not target_group:
            print(f"  ❌ Group not found: {GROUP_NAME}")
            return False

        print(f"  Found group: {target_group.name}")

        # Get messages
        print("  Fetching messages...")
        wacli_messages = client.get_messages(target_group.jid, limit=500)
        print(f"  Retrieved {len(wacli_messages)} messages")

        # Filter by date if not full sync
        if not full_sync:
            last_sync = None
            if SYNC_FILE.exists():
                try:
                    ts_str = SYNC_FILE.read_text().strip()
                    last_sync = datetime.fromisoformat(ts_str)
                except:
                    pass

            if last_sync:
                cutoff = last_sync
                print(f"  Filtering since: {cutoff.strftime('%Y-%m-%d %H:%M')}")
            else:
                cutoff = datetime.now() - timedelta(days=30)
                print(f"  First sync: last 30 days")

            filtered = []
            for wm in wacli_messages:
                try:
                    ts = datetime.fromisoformat(wm.timestamp.replace('Z', '+00:00'))
                    if ts.tzinfo:
                        ts = ts.replace(tzinfo=None)
                    if ts >= cutoff:
                        filtered.append(wm)
                except:
                    filtered.append(wm)

            wacli_messages = filtered
            print(f"  Messages after filter: {len(wacli_messages)}")

        if not wacli_messages:
            print("  No new messages to analyze")
            return True

        # Convert to WhatsApp export format for regex analyzer
        print("\n  Converting to export format...")
        export_lines = []
        for wm in wacli_messages:
            try:
                ts = datetime.fromisoformat(wm.timestamp.replace('Z', '+00:00'))
                if ts.tzinfo:
                    ts = ts.replace(tzinfo=None)
                date_str = ts.strftime("%d/%m/%Y, %H:%M")
            except:
                date_str = datetime.now().strftime("%d/%m/%Y, %H:%M")

            sender = wm.sender or "Unknown"
            text = wm.text or ""

            # Handle multi-line messages
            text_lines = text.split('\n')
            export_lines.append(f"{date_str} - {sender}: {text_lines[0]}")
            for extra_line in text_lines[1:]:
                export_lines.append(extra_line)

        # Write temporary export file
        temp_export = PROJECT_DIR / "data" / "wacli_export_temp.txt"
        temp_export.parent.mkdir(parents=True, exist_ok=True)
        temp_export.write_text('\n'.join(export_lines), encoding='utf-8')
        print(f"  Wrote {len(export_lines)} lines to temp file")

        elapsed = time.time() - start
        print(f"⏱️  Took {elapsed:.1f}s")

        # Now run regex analyzer
        print(f"\n{'='*60}")
        print("📌 Running Regex Analyzer (No AI)")
        print(f"{'='*60}")

        start = time.time()

        from regex_analyzer import WhatsAppFootballAnalyzer

        analyzer = WhatsAppFootballAnalyzer()
        events = analyzer.analyze_file(str(temp_export), deduplicate=True)

        # Filter to reasonable confidence
        events = [e for e in events if e.confidence >= 0.4]
        print(f"  High-confidence events: {len(events)}")

        # Filter upcoming only
        from datetime import date
        today = date.today()
        upcoming = [e for e in events if e.date and e.date >= today]
        print(f"  Upcoming events: {len(upcoming)}")

        # Convert to src.extractor.Event format and save
        from src.extractor import Event, EventDatabase

        db = EventDatabase(str(EVENTS_FILE))
        added = 0

        for re_event in upcoming:
            event = Event(
                id=re_event.id,
                event_type=re_event.event_type if re_event.event_type != 'unknown' else 'friendly_match',
                date=re_event.date,
                time_start=re_event.time_start,
                time_end=re_event.time_end,
                location=re_event.location or re_event.address,
                organizer=re_event.organizer,
                skill_level=_convert_skill_level(re_event.skill_level),
                age_group=re_event.age_group,
                status='full' if re_event.status == 'full' else 'open',
                contact_phone=re_event.contact_phone,
                raw_text=re_event.raw_message[:500] if re_event.raw_message else "",
            )

            if db.add(event):
                added += 1
                print(f"  ✓ {event.event_type}: {event.date} - {event.organizer or 'Unknown'}")

        db.save()

        elapsed = time.time() - start
        print(f"\n  Added {added} new events (total: {len(db)})")
        print(f"⏱️  Took {elapsed:.1f}s")

        # Save sync timestamp
        SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
        SYNC_FILE.write_text(datetime.now().isoformat())

        return True

    except Exception as e:
        import traceback
        print(f"  ❌ Error: {e}")
        traceback.print_exc()
        return False


def run_regex_on_export_file(python: str) -> bool:
    """Run regex analyzer directly on the exported chat file."""
    print(f"\n{'='*60}")
    print("📌 Running Regex Analyzer on Chat Export")
    print(f"{'='*60}")

    if not CHAT_EXPORT_FILE.exists():
        print(f"  ❌ Chat export not found: {CHAT_EXPORT_FILE}")
        return False

    start = time.time()

    try:
        sys.path.insert(0, str(PROJECT_DIR))
        from regex_analyzer import WhatsAppFootballAnalyzer
        from src.extractor import Event, EventDatabase
        from datetime import date

        analyzer = WhatsAppFootballAnalyzer()
        events = analyzer.analyze_file(str(CHAT_EXPORT_FILE), deduplicate=True)

        print(f"  Extracted: {len(events)} events")

        # Filter by confidence and upcoming
        events = [e for e in events if e.confidence >= 0.4]
        print(f"  High-confidence: {len(events)}")

        today = date.today()
        upcoming = [e for e in events if e.date and e.date >= today]
        print(f"  Upcoming: {len(upcoming)}")

        # Save to database
        db = EventDatabase(str(EVENTS_FILE))
        added = 0

        for re_event in upcoming:
            event = Event(
                id=re_event.id,
                event_type=re_event.event_type if re_event.event_type != 'unknown' else 'friendly_match',
                date=re_event.date,
                time_start=re_event.time_start,
                time_end=re_event.time_end,
                location=re_event.location or re_event.address,
                organizer=re_event.organizer,
                skill_level=_convert_skill_level(re_event.skill_level),
                age_group=re_event.age_group,
                status='full' if re_event.status == 'full' else 'open',
                contact_phone=re_event.contact_phone,
                raw_text=re_event.raw_message[:500] if re_event.raw_message else "",
            )

            if db.add(event):
                added += 1

        db.save()

        elapsed = time.time() - start
        print(f"\n  Added {added} new events (total: {len(db)})")
        print(f"⏱️  Took {elapsed:.1f}s")

        return True

    except Exception as e:
        import traceback
        print(f"  ❌ Error: {e}")
        traceback.print_exc()
        return False


def _convert_skill_level(level_str: str) -> int | None:
    """Convert skill level string to numeric (1-10 scale)."""
    if not level_str:
        return None

    level_str = level_str.lower()

    if 'spielschwach' in level_str and 'spielstark' in level_str:
        return 5  # Mixed range
    elif 'mittelstark' in level_str and 'spielstark' in level_str:
        return 7
    elif 'spielschwach' in level_str and 'mittelstark' in level_str:
        return 4
    elif 'spielstark' in level_str:
        return 8
    elif 'mittelstark' in level_str:
        return 5
    elif 'spielschwach' in level_str:
        return 3

    return None


def sync_to_calendar(python: str) -> bool:
    """Sync events to Google Calendar."""
    print(f"\n{'='*60}")
    print("📌 Syncing to Google Calendar 'Spiele'")
    print(f"{'='*60}")

    start = time.time()

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
    use_regex = "--regex" in args
    use_regex_file = "--regex-file" in args

    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"

    print("\n⚽ WhatsApp Football Event Analyzer")
    print("=" * 60)

    if use_regex:
        print("🔧 Mode: Regex Analyzer (no AI) on wacli messages")
    elif use_regex_file:
        print("🔧 Mode: Regex Analyzer (no AI) on chat export file")
    else:
        print("🔧 Mode: AI Analysis (default)")

    if list_only:
        run_command([python, "-m", "src.main", "list"], "Current events")
        return

    # Clear events for full sync
    if full_sync:
        print("\n🗑️  Clearing events for full resync...")
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        EVENTS_FILE.write_text("[]")
        if SYNC_FILE.exists():
            SYNC_FILE.unlink()

    # Run analysis based on mode
    if use_regex_file:
        # Run regex analyzer on exported chat file
        if not run_regex_on_export_file(python):
            print("\n❌ Regex analysis failed!")
            sys.exit(1)
    elif use_regex:
        # Fetch from wacli and run regex analyzer
        if not run_regex_analyzer_on_wacli(python, full_sync):
            print("\n❌ Regex analysis failed!")
            sys.exit(1)
    else:
        # Default: Sync + OCR + AI
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
