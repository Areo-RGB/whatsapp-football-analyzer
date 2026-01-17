"""
Google Calendar integration for football events.

Adds events to a Google Calendar named 'Spiele'.
Uses OAuth2 for authentication with a desktop app flow.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .extractor import Event

# OAuth2 scopes for Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Project paths
PROJECT_DIR = Path(__file__).parent.parent
CLIENT_SECRET_FILE = PROJECT_DIR / "client_secret_2_612621529981-s41ikk5s47gemc5bjts9t92ijjdeu16i.apps.googleusercontent.com.json"
TOKEN_FILE = PROJECT_DIR / "data" / "calendar_token.json"

# Calendar settings
CALENDAR_NAME = "Spiele"


def get_credentials() -> Credentials:
    """
    Get valid Google Calendar API credentials.
    
    On first run, opens a browser for OAuth consent.
    Subsequent runs use the saved token.
    
    Returns:
        Valid Credentials object
    """
    creds = None
    
    # Load existing token if available
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    
    # Refresh or get new credentials if needed
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            if not CLIENT_SECRET_FILE.exists():
                raise FileNotFoundError(
                    f"Client secret file not found: {CLIENT_SECRET_FILE}\n"
                    "Please download OAuth credentials from Google Cloud Console."
                )
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # Save credentials for next run
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    
    return creds


def get_calendar_service():
    """Get Google Calendar API service."""
    creds = get_credentials()
    return build('calendar', 'v3', credentials=creds)


def find_or_create_calendar(service, calendar_name: str = CALENDAR_NAME) -> str:
    """
    Find or create a calendar by name.
    
    Args:
        service: Google Calendar API service
        calendar_name: Name of the calendar
        
    Returns:
        Calendar ID
    """
    # List existing calendars
    calendars = service.calendarList().list().execute()
    
    for cal in calendars.get('items', []):
        if cal.get('summary') == calendar_name:
            print(f"  📅 Found calendar: {calendar_name}")
            return cal['id']
    
    # Create new calendar
    print(f"  📅 Creating calendar: {calendar_name}")
    new_calendar = {
        'summary': calendar_name,
        'description': 'Fußball-Termine (automatisch generiert)',
        'timeZone': 'Europe/Berlin'
    }
    created = service.calendars().insert(body=new_calendar).execute()
    return created['id']


def event_to_calendar_event(event: Event) -> dict:
    """
    Convert Event to Google Calendar event format.
    
    Args:
        event: Football event
        
    Returns:
        Google Calendar event dict
    """
    # Build title
    event_type_de = "🏆 Turnier" if event.event_type == "tournament" else "⚽ Testspiel"
    title = f"{event_type_de}"
    if event.organizer:
        title += f" - {event.organizer}"
    if event.age_group:
        title += f" ({event.age_group})"
    
    # Build description
    description_parts = []
    
    if event.skill_level:
        description_parts.append(f"Spielstärke: {event.skill_level}/10")
    
    if event.location:
        description_parts.append(f"📍 {event.location}")
    
    if event.maps_url:
        description_parts.append(f"🗺️ {event.maps_url}")
    
    if event.contact_name or event.contact_phone:
        contact = "📞 Kontakt: "
        if event.contact_name:
            contact += event.contact_name
        if event.contact_phone:
            contact += f" ({event.contact_phone})"
        description_parts.append(contact)
    
    if event.entry_fee:
        description_parts.append(f"💰 Startgeld: {event.entry_fee:.0f}€")
    
    if event.status == "full":
        description_parts.append("⚠️ AUSGEBUCHT")
    
    if event.raw_text:
        description_parts.append("\n---\nOriginal:\n" + event.raw_text[:500])
    
    description = "\n".join(description_parts)
    
    # Build date/time
    if not event.date:
        return None  # Can't create event without date
    
    # Default times if not specified
    start_time = event.time_start or "10:00"
    end_time = event.time_end
    
    # Calculate end time if not specified (assume 3 hours for tournaments, 2 for matches)
    if not end_time:
        start_h, start_m = map(int, start_time.split(':'))
        duration = 3 if event.event_type == "tournament" else 2
        end_h = start_h + duration
        if end_h >= 24:
            end_h = 23
        end_time = f"{end_h:02d}:{start_m:02d}"
    
    # Build datetime strings
    start_dt = f"{event.date.isoformat()}T{start_time}:00"
    end_dt = f"{event.date.isoformat()}T{end_time}:00"
    
    calendar_event = {
        'summary': title,
        'description': description,
        'location': event.location or '',
        'start': {
            'dateTime': start_dt,
            'timeZone': 'Europe/Berlin',
        },
        'end': {
            'dateTime': end_dt,
            'timeZone': 'Europe/Berlin',
        },
        # Use event ID as private extended property to avoid duplicates
        'extendedProperties': {
            'private': {
                'eventId': event.id
            }
        }
    }
    
    # Add colorId based on event type and status
    if event.status == "full":
        calendar_event['colorId'] = '8'  # Gray
    elif event.event_type == "tournament":
        calendar_event['colorId'] = '9'  # Blue
    else:
        calendar_event['colorId'] = '10'  # Green
    
    return calendar_event


def check_event_exists(service, calendar_id: str, event_id: str) -> Optional[str]:
    """
    Check if an event already exists in the calendar.
    
    Args:
        service: Google Calendar API service
        calendar_id: Calendar ID
        event_id: Our internal event ID
        
    Returns:
        Google Calendar event ID if exists, None otherwise
    """
    try:
        # Search for events with our event ID in extended properties
        events = service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"eventId={event_id}",
            maxResults=1
        ).execute()
        
        items = events.get('items', [])
        if items:
            return items[0]['id']
    except HttpError:
        pass
    
    return None


def sync_event_to_calendar(
    service,
    calendar_id: str,
    event: Event,
    update_existing: bool = True
) -> tuple[bool, str]:
    """
    Sync a single event to Google Calendar.
    
    Args:
        service: Google Calendar API service
        calendar_id: Calendar ID
        event: Football event to sync
        update_existing: Whether to update existing events
        
    Returns:
        Tuple of (success, status_message)
    """
    if not event.date:
        return False, "Kein Datum"
    
    calendar_event = event_to_calendar_event(event)
    if not calendar_event:
        return False, "Konvertierung fehlgeschlagen"
    
    try:
        # Check if event already exists
        existing_id = check_event_exists(service, calendar_id, event.id)
        
        if existing_id:
            if update_existing:
                service.events().update(
                    calendarId=calendar_id,
                    eventId=existing_id,
                    body=calendar_event
                ).execute()
                return True, "Aktualisiert"
            else:
                return True, "Bereits vorhanden"
        else:
            service.events().insert(
                calendarId=calendar_id,
                body=calendar_event
            ).execute()
            return True, "Hinzugefügt"
            
    except HttpError as e:
        return False, f"API-Fehler: {e.reason}"
    except Exception as e:
        return False, f"Fehler: {str(e)}"


def sync_events_to_calendar(
    events: list[Event],
    calendar_name: str = CALENDAR_NAME,
    update_existing: bool = True
) -> dict:
    """
    Sync multiple events to Google Calendar.
    
    Args:
        events: List of events to sync
        calendar_name: Name of the calendar
        update_existing: Whether to update existing events
        
    Returns:
        Summary dict with counts
    """
    print(f"\n📅 Syncing {len(events)} events to Google Calendar...")
    
    try:
        service = get_calendar_service()
        calendar_id = find_or_create_calendar(service, calendar_name)
    except Exception as e:
        print(f"  ❌ Calendar auth failed: {e}")
        return {'success': False, 'error': str(e)}
    
    results = {
        'success': True,
        'added': 0,
        'updated': 0,
        'skipped': 0,
        'failed': 0,
        'details': []
    }
    
    for event in events:
        success, status = sync_event_to_calendar(
            service, calendar_id, event, update_existing
        )
        
        event_desc = f"{event.date}: {event.organizer or event.event_type}"
        results['details'].append((event_desc, status))
        
        if status == "Hinzugefügt":
            results['added'] += 1
            print(f"  ✅ {event_desc}")
        elif status == "Aktualisiert":
            results['updated'] += 1
            print(f"  🔄 {event_desc}")
        elif status == "Bereits vorhanden":
            results['skipped'] += 1
        elif status == "Kein Datum":
            results['skipped'] += 1
        else:
            results['failed'] += 1
            print(f"  ❌ {event_desc}: {status}")
    
    print(f"\n  📊 Ergebnis: {results['added']} neu, {results['updated']} aktualisiert, "
          f"{results['skipped']} übersprungen, {results['failed']} fehlgeschlagen")
    
    return results


def delete_past_events(calendar_name: str = CALENDAR_NAME, days_ago: int = 7) -> int:
    """
    Delete events older than specified days.
    
    Args:
        calendar_name: Name of the calendar
        days_ago: Delete events older than this many days
        
    Returns:
        Number of deleted events
    """
    service = get_calendar_service()
    calendar_id = find_or_create_calendar(service, calendar_name)
    
    cutoff = datetime.now() - timedelta(days=days_ago)
    cutoff_str = cutoff.isoformat() + 'Z'
    
    deleted = 0
    page_token = None
    
    while True:
        events = service.events().list(
            calendarId=calendar_id,
            timeMax=cutoff_str,
            pageToken=page_token,
            maxResults=50
        ).execute()
        
        for event in events.get('items', []):
            try:
                service.events().delete(
                    calendarId=calendar_id,
                    eventId=event['id']
                ).execute()
                deleted += 1
            except HttpError:
                pass
        
        page_token = events.get('nextPageToken')
        if not page_token:
            break
    
    return deleted


if __name__ == "__main__":
    # Test authentication
    print("Testing Google Calendar authentication...")
    try:
        service = get_calendar_service()
        calendar_id = find_or_create_calendar(service)
        print(f"✅ Connected to calendar: {CALENDAR_NAME} ({calendar_id})")
        
        # List upcoming events
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        events = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        print("\nUpcoming events:")
        for event in events.get('items', []):
            start = event['start'].get('dateTime', event['start'].get('date'))
            print(f"  - {start}: {event['summary']}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
