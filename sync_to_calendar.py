#!/usr/bin/env python3
"""
WhatsApp to Google Calendar Sync (AI-powered)

Fetches messages from WhatsApp, uses AI (Google Gemini) to analyze
and extract football events, then adds them to Google Calendar.

Usage:
    python3 sync_to_calendar.py                    # Sync events
    python3 sync_to_calendar.py --dry-run          # Preview only
    python3 sync_to_calendar.py --days 7           # Custom days back
    python3 sync_to_calendar.py --cleanup          # Delete past events
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
DEFAULT_GROUP = "Jahrgang 2014er Trainer"
NOTIFY_GROUP = "Termine"
DEFAULT_DAYS = 7  # Last week
CALENDAR_NAME = "Spiele"

# German weekday names
WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def format_messages_for_ai(messages, sender_phones: dict = None) -> str:
    """Format WhatsApp messages for AI analysis."""
    formatted = []
    sender_phones = sender_phones or {}
    
    for msg in messages:
        try:
            ts = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            date_str = ts.strftime("%d.%m.%Y %H:%M")
        except:
            date_str = "Unknown"
        
        # Get actual sender phone number
        phone = sender_phones.get(msg.id)
        if phone:
            sender = f"+{phone}" if not phone.startswith("+") else phone
        else:
            sender = "Unknown"
        
        formatted.append(f"[{date_str}] [Von: {sender}]\n{msg.text}\n")
    
    return "\n---\n".join(formatted)


def get_calendar_service():
    """Get Google Calendar service."""
    from src.gcalendar import get_calendar_service as _get_service
    return _get_service()


def get_or_create_calendar(service, name: str) -> str | None:
    """Get or create calendar by name."""
    from src.gcalendar import get_or_create_calendar as _get_or_create
    return _get_or_create(service, name)


def get_existing_events(service, calendar_id: str, start_date: date, end_date: date) -> list[dict]:
    """Get existing events in date range."""
    from googleapiclient.errors import HttpError
    
    try:
        time_min = datetime.combine(start_date, datetime.min.time()).isoformat() + 'Z'
        time_max = datetime.combine(end_date, datetime.max.time()).isoformat() + 'Z'
        
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=500,
            singleEvents=True
        ).execute()
        
        return result.get('items', [])
    except HttpError as e:
        print(f"  ⚠️  Error fetching events: {e}")
        return []


def is_duplicate(event, existing_events: list[dict]) -> bool:
    """Check if event already exists in calendar."""
    if not event.date:
        return False
    
    event_date_str = event.date.isoformat()
    
    for existing in existing_events:
        existing_start = existing.get('start', {})
        existing_date = existing_start.get('date') or existing_start.get('dateTime', '')[:10]
        
        if existing_date != event_date_str:
            continue
        
        existing_title = existing.get('summary', '').lower()
        existing_desc = existing.get('description', '').lower()
        
        # Match by organizer
        if event.organizer:
            org_lower = event.organizer.lower()
            if org_lower in existing_title or org_lower in existing_desc:
                return True
            # Check individual words
            for word in org_lower.split():
                if len(word) > 3 and word in existing_title:
                    return True
        
        # Match by contact phone
        if event.contact_phone and existing_desc:
            phone_clean = event.contact_phone.replace(' ', '').replace('-', '')[-8:]
            if phone_clean in existing_desc.replace(' ', '').replace('-', ''):
                return True
        
        # Match by location
        if event.location and existing.get('location'):
            if event.location.lower()[:20] in existing.get('location', '').lower():
                return True
    
    return False


def create_calendar_event(event) -> dict:
    """Create Google Calendar event from extracted Event."""
    # Title
    emoji = "🏆" if event.event_type == "tournament" else "⚽"
    title = f"{emoji} {event.organizer or 'Fußball Event'}"
    if event.age_group:
        title += f" ({event.age_group})"
    
    # Description - use AI summary
    desc_parts = []
    
    # Add AI summary at the top
    if event.summary:
        desc_parts.append(event.summary)
        desc_parts.append("")
    
    if event.event_type == "tournament":
        desc_parts.append("🏆 TURNIER")
    else:
        desc_parts.append("⚽ TESTSPIEL / GEGNER GESUCHT")
    
    if event.skill_level:
        desc_parts.append(f"Stärke: {event.skill_level}/10")
    if event.age_group:
        desc_parts.append(f"Altersklasse: {event.age_group}")
    if event.entry_fee:
        desc_parts.append(f"Startgebühr: {event.entry_fee}€")
    if event.contact_name:
        desc_parts.append(f"Kontakt: {event.contact_name}")
    if event.contact_phone:
        desc_parts.append(f"📞 {event.contact_phone}")
    if event.status == "full":
        desc_parts.append("❌ AUSGEBUCHT")
    
    description = "\n".join(desc_parts)
    
    # Date/Time
    date_str = event.date.isoformat()
    
    if event.time_start:
        start = {'dateTime': f"{date_str}T{event.time_start}:00", 'timeZone': 'Europe/Berlin'}
        if event.time_end:
            end = {'dateTime': f"{date_str}T{event.time_end}:00", 'timeZone': 'Europe/Berlin'}
        else:
            end_hour = int(event.time_start.split(':')[0]) + 2
            end = {'dateTime': f"{date_str}T{end_hour:02d}:00:00", 'timeZone': 'Europe/Berlin'}
    else:
        start = {'date': date_str}
        end = {'date': date_str}
    
    cal_event = {
        'summary': title,
        'description': description,
        'start': start,
        'end': end,
    }
    
    if event.location:
        cal_event['location'] = event.location
    
    return cal_event


def add_event_to_calendar(service, calendar_id: str, cal_event: dict) -> str | None:
    """Add event to Google Calendar."""
    from googleapiclient.errors import HttpError
    
    try:
        created = service.events().insert(calendarId=calendar_id, body=cal_event).execute()
        return created.get('id')
    except HttpError as e:
        print(f"  ⚠️  Error creating event: {e}")
        return None


def cleanup_past_events(service, calendar_id: str, days_back: int = 60, dry_run: bool = False) -> int:
    """Delete past events from calendar using batch requests."""
    from googleapiclient.errors import HttpError
    
    today = date.today()
    start_date = today - timedelta(days=days_back)
    
    try:
        time_min = datetime.combine(start_date, datetime.min.time()).isoformat() + 'Z'
        time_max = datetime.combine(today - timedelta(days=1), datetime.max.time()).isoformat() + 'Z'
        
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=500,
            singleEvents=True
        ).execute()
        
        past_events = result.get('items', [])
    except HttpError:
        return 0
    
    if not past_events:
        return 0
    
    if dry_run:
        for event in past_events:
            event_date = event.get('start', {}).get('date') or event.get('start', {}).get('dateTime', '')[:10]
            print(f"  🗑️  Would delete: {event_date} - {event.get('summary', 'Untitled')}")
        return len(past_events)
    
    # Batch delete
    deleted = 0
    def callback(request_id, response, exception):
        nonlocal deleted
        if exception is None or (hasattr(exception, 'resp') and exception.resp.status == 410):
            deleted += 1
    
    batch = service.new_batch_http_request(callback=callback)
    for event in past_events:
        batch.add(service.events().delete(calendarId=calendar_id, eventId=event['id']))
    batch.execute()
    
    return deleted


def get_week_start(d: date) -> date:
    """Get the Monday of the week that contains this date."""
    return d - timedelta(days=d.weekday())


def group_events_by_week(events) -> dict:
    """Group events by week (Monday-Sunday)."""
    weeks = {}
    
    for event in events:
        if not event.date:
            continue
        
        week_start = get_week_start(event.date)
        week_key = week_start.isoformat()
        
        if week_key not in weeks:
            weeks[week_key] = []
        weeks[week_key].append(event)
    
    # Sort by date
    return dict(sorted(weeks.items()))


def format_event_message(event) -> str:
    """Format a single event as a WhatsApp message with consistent width."""
    weekday = WEEKDAYS_DE[event.date.weekday()]
    
    # Target width for consistent bubble size (using invisible braille pattern blank)
    # Must be wider than longest possible content line (location can be long)
    TARGET_WIDTH = 55
    FILLER_CHAR = "\u2800"  # Braille pattern blank - invisible but takes space
    
    lines = []
    
    # Header line with organizer name (no emoji)
    if event.organizer:
        lines.append(f"*{event.organizer}*")
    else:
        lines.append("*Termin*")
    lines.append("─────────────────")
    
    # Date with calendar emoji
    lines.append(f"* 📅 {event.date.strftime('%d.%m.%Y')}, {weekday}")
    
    # Time on separate line
    if event.time_start:
        time_str = event.time_start
        if event.time_end:
            time_str += f"-{event.time_end}"
        lines.append(f"* 🕐 {time_str}")
    
    # Location
    if event.location:
        lines.append(f"* 📍 {event.location}")
    
    # Contact
    if event.contact_phone:
        lines.append(f"* 📞 {event.contact_phone}")
    
    # Entry fee if available
    if hasattr(event, 'entry_fee') and event.entry_fee:
        lines.append(f"* 💰 {event.entry_fee}€")
    
    # Status
    if event.status == "full":
        lines.append("* ❌ AUSGEBUCHT")
    
    # Add invisible padding line to ensure consistent bubble width
    padding_line = FILLER_CHAR * TARGET_WIDTH
    lines.append(padding_line)
    
    return "\n".join(lines)


def format_week_header(week_start: date) -> str:
    """Format a week header message."""
    week_num = week_start.isocalendar()[1]
    week_end = week_start + timedelta(days=6)
    
    # Target width for consistent bubble size
    TARGET_WIDTH = 55
    FILLER_CHAR = "\u2800"
    
    header = f"📅 *KW {week_num}: {week_start.strftime('%d.%m.')} - {week_end.strftime('%d.%m.%Y')}*"
    padding = FILLER_CHAR * TARGET_WIDTH
    
    return f"{header}\n{padding}"


def format_events_for_whatsapp(events) -> list[str]:
    """Format events as separate messages for WhatsApp, grouped by week."""
    if not events:
        return []
    
    messages = []
    
    # Sort events by date
    sorted_events = sorted([e for e in events if e.date], key=lambda e: (e.date, e.time_start or ""))
    
    # Group by week
    weeks = group_events_by_week(sorted_events)
    
    for week_key in sorted(weeks.keys()):
        week_events = weeks[week_key]
        week_start = date.fromisoformat(week_key)
        
        # Add week header
        messages.append(format_week_header(week_start))
        
        # Add events for this week
        for event in sorted(week_events, key=lambda e: (e.date, e.time_start or "")):
            msg = format_event_message(event)
            if msg:
                messages.append(msg)
    
    return messages


def send_to_whatsapp(client, group_name: str, events, dry_run: bool = False) -> int:
    """Send event images to WhatsApp group."""
    from src.whatsapp import find_group_by_name
    from src.event_card import render_event_card, render_week_header
    import time
    import os
    
    group = find_group_by_name(client, group_name)
    if not group:
        print(f"  ❌ Group not found: {group_name}")
        return 0
    
    # Sort events and group by week
    sorted_events = sorted([e for e in events if e.date], key=lambda e: (e.date, e.time_start or ""))
    weeks = group_events_by_week(sorted_events)
    
    if dry_run:
        print(f"\n📱 Would send {len(sorted_events)} event images to '{group_name}'")
        print(f"   Grouped into {len(weeks)} weeks")
        return len(sorted_events)
    
    sent = 0
    temp_files = []
    
    try:
        for week_key in sorted(weeks.keys()):
            week_events = weeks[week_key]
            week_start = date.fromisoformat(week_key)
            
            # Send week header image
            print(f"  📅 Sending KW {week_start.isocalendar()[1]} header...")
            header_img = render_week_header(week_start)
            temp_files.append(header_img)
            
            if client.send_image(group.jid, header_img):
                sent += 1
            time.sleep(0.5)
            
            # Send each event as image
            for event in sorted(week_events, key=lambda e: (e.date, e.time_start or "")):
                print(f"  🖼 Sending: {event.organizer or 'Event'}...")
                event_img = render_event_card(event)
                temp_files.append(event_img)
                
                if client.send_image(group.jid, event_img):
                    sent += 1
                time.sleep(0.5)
        
        print(f"  📤 Sent {sent} images to {group_name}")
        return sent
    
    finally:
        # Cleanup temp files
        for f in temp_files:
            try:
                os.unlink(f)
            except:
                pass


def main():
    parser = argparse.ArgumentParser(description="WhatsApp to Google Calendar Sync (AI-powered)")
    parser.add_argument('--dry-run', action='store_true', help='Preview without adding to calendar')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS, help='Days to look back for messages')
    parser.add_argument('--group', type=str, default=DEFAULT_GROUP, help='WhatsApp group name')
    parser.add_argument('--calendar', type=str, default=CALENDAR_NAME, help='Google Calendar name')
    parser.add_argument('--cleanup', action='store_true', help='Delete past events from calendar')
    parser.add_argument('--post', action='store_true', help='Post events summary to WhatsApp Termine group')
    parser.add_argument('--notify-group', type=str, default=NOTIFY_GROUP, help='WhatsApp group for posting')
    args = parser.parse_args()
    
    print("=" * 60)
    print("📱 WhatsApp to Google Calendar Sync (AI-powered)")
    print("=" * 60)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made\n")
    
    # Import modules
    try:
        from src.whatsapp import WacliClient, check_wacli, find_group_by_name, get_sender_phones
        from src.ai_extractor import analyze_messages_with_ai
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1
    
    # Check wacli
    if not check_wacli():
        print("❌ wacli not installed")
        return 1
    
    # Initialize WhatsApp client
    print("📱 Connecting to WhatsApp...")
    client = WacliClient()
    
    if not client.is_authenticated():
        print("❌ Not authenticated. Run 'wacli auth' first.")
        return 1
    print("  ✅ Connected")
    
    # Refresh groups
    print("  🔄 Refreshing groups...")
    subprocess.run(["wacli", "groups", "refresh"], capture_output=True)
    
    # Find group
    group = find_group_by_name(client, args.group)
    
    if group:
        # Backfill message history to ensure we have recent messages
        print("  📥 Backfilling message history...")
        subprocess.run(
            ["wacli", "history", "backfill", "--chat", group.jid],
            capture_output=True,
            timeout=60
        )
    if not group:
        print(f"❌ Group not found: {args.group}")
        return 1
    print(f"  ✅ Found: {group.name}")
    
    # Fetch messages
    print(f"\n📨 Fetching messages (last {args.days} days)...")
    messages = client.get_messages(group.jid, limit=500)
    
    # Filter by date
    cutoff = datetime.now() - timedelta(days=args.days)
    filtered = []
    for msg in messages:
        try:
            ts = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            if ts >= cutoff and msg.text:  # Only filter by time, let AI handle relevance
                filtered.append(msg)
        except:
            pass
    
    print(f"  📥 {len(filtered)} messages in date range")
    
    if not filtered:
        print("\n  ℹ️  No messages to analyze")
        return 0
    
    # Get actual sender phone numbers
    msg_ids = [m.id for m in filtered if m.id]
    sender_phones = get_sender_phones(msg_ids)
    print(f"  📞 Retrieved {len(sender_phones)} sender phone numbers")
    
    # Format messages for AI
    print("\n🤖 Analyzing messages with AI (Gemini)...")
    messages_text = format_messages_for_ai(filtered, sender_phones)
    
    # Call AI to extract events
    events = analyze_messages_with_ai(messages_text)
    
    print(f"\n  🎯 AI found {len(events)} events")
    
    if not events:
        print("  ℹ️  No events found in messages")
        return 0
    
    # Filter future events
    today = date.today()
    future_events = [e for e in events if e.date and e.date >= today]
    past_count = len(events) - len(future_events)
    
    if past_count > 0:
        print(f"  ⏭️  Skipping {past_count} past events")
    
    if not future_events:
        print("  ℹ️  No future events to sync")
        return 0
    
    # Show found events
    print("\n📋 Events found:")
    for evt in future_events:
        emoji = "🏆" if evt.event_type == "tournament" else "⚽"
        status = " (VOLL)" if evt.status == "full" else ""
        print(f"  {emoji} {evt.date} - {evt.organizer or 'Unknown'}{status}")
        if evt.location:
            print(f"      📍 {evt.location}")
        if evt.contact_phone:
            print(f"      📞 {evt.contact_phone}")
    
    # Connect to Google Calendar
    print(f"\n📅 Connecting to Google Calendar...")
    try:
        service = get_calendar_service()
        calendar_id = get_or_create_calendar(service, args.calendar)
        
        if not calendar_id:
            print("  ❌ Failed to get calendar")
            return 1
        print(f"  ✅ Using calendar: {args.calendar}")
    except Exception as e:
        print(f"  ❌ Calendar error: {e}")
        return 1
    
    # Cleanup past events if requested
    if args.cleanup:
        print("\n🧹 Cleaning up past events...")
        deleted = cleanup_past_events(service, calendar_id, days_back=60, dry_run=args.dry_run)
        print(f"  🗑️  {'Would delete' if args.dry_run else 'Deleted'}: {deleted} past events")
    
    # Get existing events for duplicate check
    min_date = min(e.date for e in future_events)
    max_date = max(e.date for e in future_events) + timedelta(days=1)
    existing = get_existing_events(service, calendar_id, min_date, max_date)
    print(f"\n  🔍 Checking duplicates ({len(existing)} existing events)...")
    
    # Add events
    added = 0
    skipped = 0
    
    for evt in future_events:
        if is_duplicate(evt, existing):
            print(f"  ⏭️  Skipped (duplicate): {evt.date} - {evt.organizer or 'Event'}")
            skipped += 1
            continue
        
        # Create calendar event with AI summary
        cal_event = create_calendar_event(evt)
        
        if args.dry_run:
            print(f"  📝 Would add: {evt.date} - {evt.organizer or 'Event'}")
            added += 1
        else:
            event_id = add_event_to_calendar(service, calendar_id, cal_event)
            if event_id:
                print(f"  ✅ Added: {evt.date} - {evt.organizer or 'Event'}")
                added += 1
                # Add to existing for duplicate check within batch
                existing.append({
                    'start': {'date': evt.date.isoformat()},
                    'summary': cal_event['summary'],
                    'description': cal_event['description'],
                    'location': cal_event.get('location', '')
                })
    
    print(f"\n{'=' * 60}")
    print(f"✅ Calendar sync done! Added: {added}, Skipped: {skipped}")
    print("=" * 60)
    
    # Post to WhatsApp (always enabled) - send as images
    if future_events:
        print(f"\n📱 Posting event images to WhatsApp '{args.notify_group}'...")
        send_to_whatsapp(client, args.notify_group, future_events, dry_run=args.dry_run)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
