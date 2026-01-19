#!/usr/bin/env python3
"""
Clean all events from Google Calendar.

Usage:
    python3 clean_calendar.py                    # Delete all events (with confirmation)
    python3 clean_calendar.py --dry-run          # Preview only
    python3 clean_calendar.py --force            # Delete without confirmation
    python3 clean_calendar.py --calendar "Name"  # Specify calendar name
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# Project directory
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

# Configuration
CALENDAR_NAME = "Spiele"


def get_all_calendar_events(service, calendar_id: str) -> list[dict]:
    """Get ALL events from Google Calendar."""
    from googleapiclient.errors import HttpError
    
    all_events = []
    page_token = None
    
    try:
        while True:
            events_result = service.events().list(
                calendarId=calendar_id,
                maxResults=500,
                singleEvents=True,
                orderBy='startTime',
                pageToken=page_token
            ).execute()
            
            all_events.extend(events_result.get('items', []))
            page_token = events_result.get('nextPageToken')
            
            if not page_token:
                break
                
        return all_events
    except HttpError as e:
        print(f"  ⚠️  Error fetching events: {e}")
        return []


def delete_events_batch(service, calendar_id: str, events: list[dict]) -> int:
    """Delete multiple events using batch request (much faster)."""
    from googleapiclient.http import BatchHttpRequest
    
    deleted = 0
    errors = 0
    
    def callback(request_id, response, exception):
        nonlocal deleted, errors
        if exception is None:
            deleted += 1
        elif hasattr(exception, 'resp') and exception.resp.status == 410:
            # Already deleted
            deleted += 1
        else:
            errors += 1
    
    # Process in batches of 50 (Google's limit)
    batch_size = 50
    total = len(events)
    
    for i in range(0, total, batch_size):
        batch_events = events[i:i + batch_size]
        batch = service.new_batch_http_request(callback=callback)
        
        for event in batch_events:
            batch.add(service.events().delete(calendarId=calendar_id, eventId=event['id']))
        
        batch.execute()
        
        progress = min(i + batch_size, total)
        print(f"  🗑️  Deleted {progress}/{total} events...")
    
    if errors > 0:
        print(f"  ⚠️  {errors} events failed to delete")
    
    return deleted


def clean_all_events(calendar_name: str = CALENDAR_NAME, dry_run: bool = False) -> int:
    """
    Delete ALL events from Google Calendar.
    
    Args:
        calendar_name: Calendar name
        dry_run: If True, don't actually delete
        
    Returns:
        Number of events deleted
    """
    from src.gcalendar import get_calendar_service, find_calendar_id
    
    print(f"  🔌 Connecting to Google Calendar...")
    service = get_calendar_service()
    calendar_id = find_calendar_id(service, calendar_name)
    
    if not calendar_id:
        print(f"  ❌ Calendar '{calendar_name}' not found")
        return 0
    
    print(f"  ✅ Found calendar: {calendar_name}")
    print(f"  📥 Fetching all events...")
    
    all_events = get_all_calendar_events(service, calendar_id)
    
    if not all_events:
        print("  ℹ️  No events found in calendar")
        return 0
    
    print(f"  📊 Found {len(all_events)} events")
    
    if dry_run:
        # Show what would be deleted
        for i, event in enumerate(all_events, 1):
            event_date = event.get('start', {}).get('date') or event.get('start', {}).get('dateTime', '')[:10]
            event_title = event.get('summary', 'Untitled')
            print(f"  [{i}/{len(all_events)}] 🗑️  Would delete: {event_date} - {event_title}")
        return len(all_events)
    else:
        # Use fast batch deletion
        print(f"  ⚡ Using batch delete for speed...")
        return delete_events_batch(service, calendar_id, all_events)


def main():
    parser = argparse.ArgumentParser(description="Clean all events from Google Calendar")
    parser.add_argument('--dry-run', action='store_true', help='Preview without deleting')
    parser.add_argument('--force', '-f', action='store_true', help='Delete without confirmation')
    parser.add_argument('--calendar', type=str, default=CALENDAR_NAME, help='Google Calendar name')
    args = parser.parse_args()
    
    print("=" * 60)
    print("🧹 Google Calendar Cleaner")
    print("=" * 60)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made\n")
    
    try:
        deleted = clean_all_events(
            calendar_name=args.calendar,
            dry_run=args.dry_run
        )
        
        print(f"\n{'=' * 60}")
        if args.dry_run:
            print(f"📋 Would delete {deleted} events")
        else:
            print(f"✅ Deleted {deleted} events")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
