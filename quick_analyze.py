#!/usr/bin/env python3
"""
Quick WhatsApp Football Event Analyzer

Fetches messages from the last 14 days, analyzes with regex (no AI),
runs OCR on images, and sends upcoming events to the Termine chat.

Usage:
    python3 quick_analyze.py              # Analyze and send
    python3 quick_analyze.py --dry-run    # Preview only, don't send
    python3 quick_analyze.py --days 7     # Custom days back
    python3 quick_analyze.py --no-ocr     # Skip image OCR processing
"""

import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, date

# Project directory
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

# Configuration
GROUP_NAME = "Jahrgang 2014er Trainer"
NOTIFY_GROUP = "Termine"
DEFAULT_DAYS = 14
MEDIA_DIR = PROJECT_DIR / "data" / "media"


def download_and_ocr_images(client, group_jid, media_messages, sender_phones_map) -> list[str]:
    """
    Download images from messages and extract text using OCR.

    Returns list of OCR text strings with sender phone info.
    """
    if not media_messages:
        return []

    # Ensure media directory exists
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # Check OCR availability
    try:
        from src.ocr import extract_text_from_image, check_ocr, HAS_OCR
        ocr_status = check_ocr()
        if not ocr_status.get("any"):
            print("  ⚠️  No OCR engine available (install tesseract-ocr)")
            return []
    except ImportError:
        print("  ⚠️  OCR module not available")
        return []

    ocr_texts = []
    downloaded = 0
    ocr_extracted = 0

    for wm in media_messages:
        try:
            # Check if already downloaded
            existing = list(MEDIA_DIR.glob(f"*{wm.id}*"))

            if existing:
                img_path = str(existing[0])
            else:
                # Download image
                img_path = client.download_media(group_jid, wm.id, MEDIA_DIR)
                if img_path:
                    downloaded += 1

            if not img_path:
                continue

            # Run OCR on image
            ocr_text = extract_text_from_image(img_path)

            if ocr_text and ocr_text.strip():
                ocr_extracted += 1

                # Get sender phone info and timestamp
                phone = sender_phones_map.get(wm.id)
                if phone:
                    formatted_phone = f"+{phone}" if not phone.startswith("+") else phone
                else:
                    formatted_phone = wm.sender or "Unknown"

                # Get timestamp from original message
                try:
                    ts = datetime.fromisoformat(wm.timestamp.replace("Z", "+00:00"))
                    if ts.tzinfo:
                        ts = ts.replace(tzinfo=None)
                    date_str = ts.strftime("%d/%m/%Y, %H:%M")
                except:
                    date_str = datetime.now().strftime("%d/%m/%Y, %H:%M")

                # Format as WhatsApp-style message so parser can process it
                # Each line of OCR becomes part of the message
                ocr_texts.append(f"{date_str} - {formatted_phone}: [OCR Bild] {ocr_text}")

        except Exception as e:
            print(f"    ⚠️  Error processing {wm.id}: {e}")

    print(f"  ✓ Downloaded {downloaded} new images")
    print(f"  ✓ OCR extracted text from {ocr_extracted} images")

    return ocr_texts


def cleanup_calendar_duplicates(dry_run: bool = False) -> dict:
    """
    Remove all duplicate calendar events (keeping only one per date+time+title).
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from src.calendar_sync import (
            get_calendar_service,
            find_or_create_calendar,
            CALENDAR_NAME
        )
    except ImportError as e:
        print(f"  ❌ Calendar import error: {e}")
        return {'success': False, 'error': str(e)}

    try:
        service = get_calendar_service()
        calendar_id = find_or_create_calendar(service, CALENDAR_NAME)
        print(f"  📅 Found calendar: {CALENDAR_NAME}")
    except Exception as e:
        print(f"  ❌ Calendar auth failed: {e}")
        return {'success': False, 'error': str(e)}

    # Get all events from now to 6 months ahead
    now = datetime.now()
    time_min = now.isoformat() + 'Z'
    time_max = (now + timedelta(days=180)).isoformat() + 'Z'

    all_events = []
    page_token = None

    while True:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            maxResults=250,
            pageToken=page_token
        ).execute()
        all_events.extend(events_result.get('items', []))
        page_token = events_result.get('nextPageToken')
        if not page_token:
            break

    print(f"  📊 Found {len(all_events)} calendar events")

    # Group events by date + time + normalized title
    from collections import defaultdict
    event_groups = defaultdict(list)

    for event in all_events:
        # Get start date/time
        start = event.get('start', {})
        start_key = start.get('dateTime', start.get('date', ''))

        # Normalize title for comparison
        title = event.get('summary', '').lower()
        # Remove emojis and extra spaces
        title_clean = ''.join(c for c in title if c.isalnum() or c.isspace()).strip()
        title_clean = ' '.join(title_clean.split())

        # Create key
        key = f"{start_key}|{title_clean}"
        event_groups[key].append(event)

    # Find and remove duplicates
    removed = 0
    for key, group in event_groups.items():
        if len(group) > 1:
            # Keep the first, delete the rest
            for dup in group[1:]:
                if dry_run:
                    print(f"  🔸 Would remove: {dup.get('summary', '')} ({dup['start'].get('dateTime', dup['start'].get('date'))})")
                else:
                    try:
                        service.events().delete(
                            calendarId=calendar_id,
                            eventId=dup['id']
                        ).execute()
                        print(f"  🗑️  Removed: {dup.get('summary', '')}")
                        removed += 1
                    except HttpError as e:
                        print(f"  ⚠️  Failed to remove: {dup.get('summary', '')} - {e}")

    if dry_run:
        print(f"\n  📊 Would remove {removed + len([g for g in event_groups.values() if len(g) > 1]) - len([g for g in event_groups.values() if len(g) > 1])} duplicates")
        # Count properly for dry run
        total_dups = sum(len(g) - 1 for g in event_groups.values() if len(g) > 1)
        print(f"  📊 Found {total_dups} duplicate events to remove")
    else:
        print(f"\n  📊 Removed {removed} duplicate events")

    return {'success': True, 'removed': removed}


def main():
    parser = argparse.ArgumentParser(description="Quick Football Event Analyzer")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Days to look back")
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR image processing")
    parser.add_argument("--force", action="store_true", help="Send all events even if already posted")
    parser.add_argument("--hours", type=int, default=2, help="Hours to check for duplicates (default: 2)")
    parser.add_argument("--calendar", action="store_true", help="Sync events to Google Calendar")
    parser.add_argument("--no-whatsapp", action="store_true", help="Skip WhatsApp sending (use with --calendar)")
    parser.add_argument("--cleanup-calendar", action="store_true", help="Remove duplicate calendar events")
    args = parser.parse_args()

    # Handle cleanup-only mode
    if args.cleanup_calendar:
        print("\n🧹 Calendar Duplicate Cleanup")
        print("=" * 60)
        cleanup_calendar_duplicates(dry_run=args.dry_run)
        print("\n✅ Done!")
        return 0

    print("\n⚽ Quick Football Event Analyzer (No AI)")
    print("=" * 60)

    # Step 1: Fetch messages from WhatsApp
    print(f"\n📱 Fetching messages from last {args.days} days...")

    try:
        from src.whatsapp import WacliClient, check_wacli, find_group_by_name, get_sender_phones
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1

    if not check_wacli():
        print("❌ wacli not installed. Install from: https://github.com/steipete/wacli")
        return 1

    client = WacliClient()
    if not client.is_authenticated():
        print("❌ Not authenticated. Run 'wacli auth' first.")
        return 1

    # Refresh groups cache to ensure all groups are available
    print("  🔄 Refreshing groups cache...")
    subprocess.run(["wacli", "groups", "refresh"], capture_output=True)

    # Find source group
    source_group = find_group_by_name(client, GROUP_NAME)
    if not source_group:
        print(f"❌ Group not found: {GROUP_NAME}")
        return 1

    print(f"  ✓ Found group: {source_group.name}")

    # Fetch messages
    wacli_messages = client.get_messages(source_group.jid, limit=500)
    print(f"  ✓ Retrieved {len(wacli_messages)} messages")

    # Filter by date
    cutoff = datetime.now() - timedelta(days=args.days)
    filtered = []
    for wm in wacli_messages:
        try:
            ts = datetime.fromisoformat(wm.timestamp.replace("Z", "+00:00"))
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            if ts >= cutoff:
                filtered.append(wm)
        except:
            filtered.append(wm)

    print(f"  ✓ Messages in last {args.days} days: {len(filtered)}")

    if not filtered:
        print("\n⚠️  No new messages to analyze")
        return 0

    # Look up actual sender phone numbers from whatsmeow database
    message_ids = [wm.id for wm in filtered if wm.id]
    sender_phones_map = get_sender_phones(message_ids)
    print(f"  ✓ Resolved {len(sender_phones_map)} sender phones")

    # Step 2: Download and OCR images
    ocr_texts = []
    if not args.no_ocr:
        # Find messages with images
        media_messages = [
            wm for wm in filtered
            if wm.has_media and wm.media_type in ('image', 'image/jpeg', 'image/png', 'image/webp')
        ]

        if media_messages:
            print(f"\n🖼️  Processing {len(media_messages)} images...")
            ocr_texts = download_and_ocr_images(
                client, source_group.jid, media_messages, sender_phones_map
            )
        else:
            print("\n🖼️  No images found in messages")
    else:
        print("\n🖼️  OCR skipped (--no-ocr)")

    # Step 3: Convert to export format with proper phone numbers
    print("\n🔄 Converting messages...")
    export_lines = []

    for wm in filtered:
        try:
            ts = datetime.fromisoformat(wm.timestamp.replace("Z", "+00:00"))
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            date_str = ts.strftime("%d/%m/%Y, %H:%M")
        except:
            date_str = datetime.now().strftime("%d/%m/%Y, %H:%M")

        # Get actual phone number from lookup, or format sender
        phone = sender_phones_map.get(wm.id, "")
        if phone:
            sender = f"+{phone}" if not phone.startswith("+") else phone
        else:
            sender = wm.sender or "Unknown"
            # Try to extract phone from JID if it's a personal JID
            if "@s.whatsapp.net" in sender:
                phone_part = sender.split("@")[0]
                if phone_part.isdigit():
                    sender = f"+{phone_part}"

        text = wm.text or ""
        text_lines = text.split("\n")
        export_lines.append(f"{date_str} - {sender}: {text_lines[0]}")
        for extra_line in text_lines[1:]:
            export_lines.append(extra_line)

    # Write temp file
    temp_file = PROJECT_DIR / "data" / "quick_export.txt"
    temp_file.parent.mkdir(parents=True, exist_ok=True)

    # Combine text messages and OCR content
    # OCR texts are already formatted as WhatsApp messages
    all_content = "\n".join(export_lines)
    if ocr_texts:
        all_content += "\n" + "\n".join(ocr_texts)

    temp_file.write_text(all_content, encoding="utf-8")
    print(f"  ✓ Total content: {len(all_content)} chars")

    # Step 4: Run regex analyzer
    print("\n🔍 Analyzing with regex patterns...")

    from regex_analyzer import WhatsAppFootballAnalyzer

    analyzer = WhatsAppFootballAnalyzer()
    events = analyzer.analyze_file(str(temp_file), deduplicate=True)

    # Filter high confidence events
    high_conf_events = [e for e in events if e.confidence >= 0.4]
    print(f"  ✓ High-confidence events: {len(high_conf_events)}")

    today = date.today()
    upcoming = [e for e in high_conf_events if e.date and e.date >= today]
    upcoming = sorted(upcoming, key=lambda x: x.date)
    print(f"  ✓ Upcoming events: {len(upcoming)}")

    # Filter only open events
    open_events = [e for e in upcoming if e.status == "open"]
    print(f"  ✓ Open events: {len(open_events)}")

    # Also collect OCR events that couldn't be fully parsed (low conf or no date)
    ocr_events = [e for e in events
                  if "[OCR Bild]" in e.raw_message
                  and (e.confidence < 0.4 or not e.date)
                  and e.status == "open"]
    if ocr_events:
        print(f"  ✓ Partial OCR events (no date): {len(ocr_events)}")

    if not open_events and not ocr_events:
        print("\n⚠️  No upcoming open events found")
        return 0

    all_events = open_events + (ocr_events or [])

    # Step 5: Check for already posted events in Termine chat
    if args.force:
        print("\n🔍 Skipping duplicate check (--force)")
        new_events = all_events
        notify_group = find_group_by_name(client, NOTIFY_GROUP)
        if not notify_group:
            print(f"❌ Notify group not found: {NOTIFY_GROUP}")
            return 1
    else:
        print("\n🔍 Checking for already posted events...")
        notify_group = find_group_by_name(client, NOTIFY_GROUP)
        if not notify_group:
            print(f"❌ Notify group not found: {NOTIFY_GROUP}")
            return 1

        already_posted = get_posted_events(client, notify_group.jid, hours_back=args.hours)
        print(f"  ✓ Found {len(already_posted)} events posted in last {args.hours}h")

        # Filter out already posted events
        new_events = []
        skipped = 0

        for e in all_events:
            event_key = get_event_key(e)
            if event_key in already_posted:
                skipped += 1
            else:
                new_events.append(e)

        if skipped > 0:
            print(f"  ✓ Skipping {skipped} already posted events")

        if not new_events:
            print("\n✅ All events already posted - nothing new to send")
            return 0

    # Step 6: Format messages (one per event)
    print("\n📝 Formatting messages...")

    messages = format_event_messages(new_events)
    print(f"  ✓ {len(messages)} new messages prepared")

    print("\n" + "=" * 60)
    print("📋 MESSAGE PREVIEW:")
    print("=" * 60)
    for i, msg in enumerate(messages, 1):
        print(f"\n--- Message {i} ---")
        print(msg)
    print("\n" + "=" * 60)

    # Step 7: Send to Termine (unless --no-whatsapp)
    if args.no_whatsapp:
        print("\n📱 WhatsApp sending skipped (--no-whatsapp)")
    elif args.dry_run:
        print("\n🔸 Dry run - messages NOT sent")
    else:
        print(f"\n📤 Sending {len(messages)} messages to '{NOTIFY_GROUP}'...")

        import time
        sent = 0
        for i, msg in enumerate(messages, 1):
            success = client.send_to_group(notify_group.jid, msg)
            if success:
                sent += 1
                print(f"  ✓ Message {i}/{len(messages)} sent")
            else:
                print(f"  ❌ Message {i} failed")
            # Small delay between messages to avoid rate limiting
            if i < len(messages):
                time.sleep(1)

        print(f"\n  ✓ {sent}/{len(messages)} messages sent successfully!")

    # Step 8: Sync to Google Calendar (if enabled)
    if args.calendar:
        print("\n📅 Syncing to Google Calendar...")
        if args.dry_run:
            print("  🔸 Dry run - calendar NOT updated")
            print(f"  Would sync {len(new_events)} events")
        else:
            sync_to_calendar(new_events)

    print("\n✅ Done!")
    return 0


def get_event_key(event) -> str:
    """Generate a unique key for an event based on date and organizer."""
    date_str = event.date.strftime("%d.%m.%Y") if event.date else "unknown"
    org = (event.organizer or "").lower().strip()
    # Normalize organizer name for matching
    org = org.replace(".", "").replace(" ", "")
    return f"{date_str}|{org}"


def get_posted_events(client, group_jid: str, hours_back: int = 24) -> set:
    """
    Fetch recent messages from Termine chat and extract posted event keys.
    Only looks at messages from the last N hours to avoid false positives.

    Returns set of event keys (date|organizer) that have already been posted.
    """
    posted = set()
    cutoff = datetime.now() - timedelta(hours=hours_back)

    try:
        # Fetch recent messages from Termine chat
        messages = client.get_messages(group_jid, limit=100)

        for msg in messages:
            # Check message timestamp - only consider recent messages
            try:
                ts = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
                if ts.tzinfo:
                    ts = ts.replace(tzinfo=None)
                if ts < cutoff:
                    continue  # Skip older messages
            except:
                pass  # If can't parse timestamp, include it to be safe

            text = msg.text or ""
            if not text:
                continue

            # Look for date pattern in posted messages: *DD.MM.YYYY*
            import re
            date_match = re.search(r'\*(\d{2}\.\d{2}\.\d{4})\*', text)
            if not date_match:
                continue

            date_str = date_match.group(1)

            # Look for organizer pattern: 🏆  *NAME* or ⚽  *NAME*
            org_match = re.search(r'[🏆⚽]\s+\*([^*]+)\*', text)
            if org_match:
                org = org_match.group(1).lower().strip()
                org = org.replace(".", "").replace(" ", "")
                event_key = f"{date_str}|{org}"
                posted.add(event_key)

    except Exception as e:
        print(f"  ⚠️  Error checking posted events: {e}")

    return posted


def sync_to_calendar(events: list) -> dict:
    """
    Sync events to Google Calendar with duplicate detection and removal.

    Returns dict with sync results.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from src.calendar_sync import (
            get_calendar_service,
            find_or_create_calendar,
            CALENDAR_NAME
        )
    except ImportError as e:
        print(f"  ❌ Calendar import error: {e}")
        return {'success': False, 'error': str(e)}

    try:
        service = get_calendar_service()
        calendar_id = find_or_create_calendar(service, CALENDAR_NAME)
    except Exception as e:
        print(f"  ❌ Calendar auth failed: {e}")
        return {'success': False, 'error': str(e)}

    results = {
        'success': True,
        'added': 0,
        'updated': 0,
        'skipped': 0,
        'duplicates_removed': 0,
        'failed': 0
    }

    for event in events:
        if not event.date:
            results['skipped'] += 1
            continue

        try:
            # Build search key from date and organizer
            org_normalized = (event.organizer or "").lower().strip()

            # Search for existing events on same date with similar title
            date_start = f"{event.date.isoformat()}T00:00:00Z"
            date_end = f"{event.date.isoformat()}T23:59:59Z"

            existing_events = service.events().list(
                calendarId=calendar_id,
                timeMin=date_start,
                timeMax=date_end,
                singleEvents=True,
                maxResults=50
            ).execute().get('items', [])

            # Check for duplicates (same date + similar organizer in title)
            duplicates = []
            for existing in existing_events:
                existing_title = existing.get('summary', '').lower()
                if org_normalized and org_normalized in existing_title.replace(".", "").replace(" ", ""):
                    duplicates.append(existing)

            # Remove duplicates except the first one
            if len(duplicates) > 1:
                for dup in duplicates[1:]:
                    try:
                        service.events().delete(
                            calendarId=calendar_id,
                            eventId=dup['id']
                        ).execute()
                        results['duplicates_removed'] += 1
                        print(f"  🗑️  Removed duplicate: {dup.get('summary', '')[:40]}")
                    except HttpError:
                        pass

            # If event already exists, update it
            if duplicates:
                existing_event = duplicates[0]
                cal_event = build_calendar_event(event)
                if cal_event:
                    service.events().update(
                        calendarId=calendar_id,
                        eventId=existing_event['id'],
                        body=cal_event
                    ).execute()
                    results['updated'] += 1
                    print(f"  🔄 Updated: {event.date} - {event.organizer or 'Event'}")
            else:
                # Create new event
                cal_event = build_calendar_event(event)
                if cal_event:
                    service.events().insert(
                        calendarId=calendar_id,
                        body=cal_event
                    ).execute()
                    results['added'] += 1
                    print(f"  ✅ Added: {event.date} - {event.organizer or 'Event'}")

        except HttpError as e:
            results['failed'] += 1
            print(f"  ❌ Failed: {event.date} - {e.reason}")
        except Exception as e:
            results['failed'] += 1
            print(f"  ❌ Failed: {event.date} - {str(e)}")

    print(f"\n  📊 Calendar: {results['added']} added, {results['updated']} updated, "
          f"{results['duplicates_removed']} duplicates removed, {results['failed']} failed")

    return results


def build_calendar_event(event) -> dict:
    """Convert event to Google Calendar format."""
    if not event.date:
        return None

    # Build title
    emoji = "🏆" if event.event_type == "tournament" else "⚽"
    title = f"{emoji} {event.organizer or 'Fußball Event'}"

    # Build description
    desc_parts = []
    if event.event_type == "tournament":
        desc_parts.append("🏆 TURNIER")
    else:
        desc_parts.append("⚽ TESTSPIEL")

    if event.play_format:
        desc_parts.append(f"Format: {event.play_format}")
    if event.entry_fee:
        desc_parts.append(f"Startgebühr: {event.entry_fee}")
    if event.contact_phone:
        desc_parts.append(f"📞 {event.contact_phone}")
    if event.location:
        desc_parts.append(f"📍 {event.location}")
    if event.address:
        desc_parts.append(f"   {event.address}")

    description = "\n".join(desc_parts)

    # Build time
    date_str = event.date.isoformat()

    if event.time_start:
        start_time = f"{date_str}T{event.time_start}:00"
        if event.time_end:
            end_time = f"{date_str}T{event.time_end}:00"
        else:
            # Default 3 hour duration for tournaments, 2 for matches
            from datetime import datetime as dt, timedelta
            start_dt = dt.fromisoformat(start_time)
            duration = 3 if event.event_type == "tournament" else 2
            end_dt = start_dt + timedelta(hours=duration)
            end_time = end_dt.isoformat()

        start = {'dateTime': start_time, 'timeZone': 'Europe/Berlin'}
        end = {'dateTime': end_time, 'timeZone': 'Europe/Berlin'}
    else:
        # All-day event
        start = {'date': date_str}
        end = {'date': date_str}

    cal_event = {
        'summary': title,
        'description': description,
        'start': start,
        'end': end,
    }

    if event.location:
        loc = event.location
        if event.address and event.address != event.location:
            loc += f", {event.address}"
        cal_event['location'] = loc

    # Color based on event type
    if event.event_type == "tournament":
        cal_event['colorId'] = '9'  # Blue
    else:
        cal_event['colorId'] = '10'  # Green

    return cal_event


def format_event_messages(events: list) -> list[str]:
    """Format each event as a separate WhatsApp message."""
    messages = []

    weekdays_de = {
        0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
        4: "Freitag", 5: "Samstag", 6: "Sonntag"
    }

    for e in events:
        lines = []

        # Header with date
        if e.date:
            weekday = weekdays_de[e.date.weekday()]
            lines.append(f"*{e.date.strftime('%d.%m.%Y')}* _({weekday})_")
        else:
            lines.append("*Datum unbekannt*")

        # Event type icon and organizer
        icon = "🏆" if e.event_type == "tournament" else "⚽"
        org = e.organizer or "Unbekannt"
        lines.append(f"{icon}  *{org}*")

        # Time
        if e.time_start:
            time_str = e.time_start
            if e.time_end:
                time_str += f" - {e.time_end}"
            lines.append(f"⏰  {time_str}")

        # Location (clean up OCR artifacts)
        if e.location:
            loc = e.location.strip().lstrip("-").strip()
            loc = loc[:50] + "..." if len(loc) > 50 else loc
            if loc:
                lines.append(f"📍  {loc}")

        # Address - only show if different from location
        if e.address:
            addr = e.address.strip().lstrip("-").strip()
            # Clean and compare
            loc_clean = (e.location or "").strip().lstrip("-").strip().lower()
            addr_clean = addr.lower()
            # Only show address if it's different from location
            if addr_clean and addr_clean != loc_clean and addr_clean not in loc_clean:
                addr = addr[:60] + "..." if len(addr) > 60 else addr
                lines.append(f"    {addr}")

        # Contact phone
        if e.contact_phone and "@" not in e.contact_phone:
            phone = e.contact_phone
            if phone.startswith("+49"):
                phone = phone.replace("+49", "+49 ")
            lines.append(f"📞  {phone}")

        # Play format
        if e.play_format:
            lines.append(f"👥  {e.play_format}")

        # Entry fee
        if e.entry_fee:
            lines.append(f"💰  {e.entry_fee}")

        messages.append("\n".join(lines))

    return messages


def format_events_message(events: list, ocr_events: list = None) -> str:
    """Format events into a WhatsApp-friendly message (legacy, single message)."""
    lines = []
    lines.append("⚽ *Kommende Fußball-Events*")
    lines.append(f"📅 Stand: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    lines.append("")

    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)
    for e in events:
        by_date[e.date].append(e)

    weekdays_de = {
        0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
        4: "Freitag", 5: "Samstag", 6: "Sonntag"
    }

    for event_date in sorted(by_date.keys()):
        weekday = weekdays_de[event_date.weekday()]
        # Date in bold, day in parentheses and italic
        lines.append(f"*{event_date.strftime('%d.%m.%Y')}* _({weekday})_")

        for e in by_date[event_date]:
            icon = "🏆" if e.event_type == "tournament" else "⚽"
            org = e.organizer or "Unbekannt"

            # Build event line with aligned emoji
            lines.append(f"{icon}  *{org}*")

            # Time - aligned emoji column
            if e.time_start:
                time_str = e.time_start
                if e.time_end:
                    time_str += f" - {e.time_end}"
                lines.append(f"⏰  {time_str}")

            # Location - aligned emoji column
            if e.location:
                loc = e.location[:50] + "..." if len(e.location) > 50 else e.location
                lines.append(f"📍  {loc}")

            # Address - show full address if available
            if e.address:
                addr = e.address[:60] + "..." if len(e.address) > 60 else e.address
                lines.append(f"    {addr}")

            # Contact - aligned emoji column
            if e.contact_phone and "@" not in e.contact_phone:
                phone = e.contact_phone
                if phone.startswith("+49"):
                    phone = phone.replace("+49", "+49 ")
                lines.append(f"📞  {phone}")

            # Play format - aligned emoji column
            if e.play_format:
                lines.append(f"⚽  {e.play_format}")

            lines.append("")

    # Add OCR events without dates (potential events)
    if ocr_events:
        lines.append("─" * 30)
        lines.append("📸 *Aus Bildern erkannt (Datum unklar):*")
        lines.append("")

        for e in ocr_events:
            icon = "🏆" if e.event_type == "tournament" else "⚽"
            org = e.organizer or "Turnier"

            lines.append(f"{icon}  *{org}*")

            if e.location:
                # Clean up OCR artifacts in location
                loc = e.location.strip().lstrip("-").strip()
                loc = loc[:50] + "..." if len(loc) > 50 else loc
                if loc:
                    lines.append(f"📍  {loc}")

            if e.address and e.address != e.location:
                addr = e.address.strip().lstrip("-").strip()
                addr = addr[:60] + "..." if len(addr) > 60 else addr
                if addr:
                    lines.append(f"    {addr}")

            if e.entry_fee:
                lines.append(f"💰  {e.entry_fee}")

            if e.contact_phone and "@" not in e.contact_phone:
                phone = e.contact_phone
                if phone.startswith("+49"):
                    phone = phone.replace("+49", "+49 ")
                lines.append(f"📞  {phone}")

            lines.append("")

    # Footer
    lines.append("─" * 30)
    total = len(events) + (len(ocr_events) if ocr_events else 0)
    lines.append(f"📊 {total} Events gefunden")
    lines.append("_Automatisch analysiert (Regex)_")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
