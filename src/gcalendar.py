"""
Google Calendar integration for adding football events.
Uses OAuth2 for authentication with Google Calendar API.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .extractor import Event

# OAuth scopes for Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Paths
PROJECT_DIR = Path(__file__).parent.parent
CREDENTIALS_FILE = PROJECT_DIR / "client_secret_2_612621529981-s41ikk5s47gemc5bjts9t92ijjdeu16i.apps.googleusercontent.com.json"
TOKEN_FILE = PROJECT_DIR / "data" / "calendar_token.json"

# Calendar name to use
CALENDAR_NAME = "Spiele"


def get_calendar_service():
    """
    Get authenticated Google Calendar service.
    Will prompt for OAuth login on first run.
    
    Returns:
        Google Calendar API service object
    """
    creds = None
    
    # Load existing token
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    
    # Refresh or get new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"OAuth credentials not found: {CREDENTIALS_FILE}\n"
                    "Download from Google Cloud Console > APIs & Services > Credentials"
                )
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # Save token for future use
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    return build('calendar', 'v3', credentials=creds)


def find_calendar_id(service, calendar_name: str = CALENDAR_NAME) -> Optional[str]:
    """
    Find calendar ID by name.
    
    Args:
        service: Google Calendar API service
        calendar_name: Name of calendar to find
        
    Returns:
        Calendar ID or None if not found
    """
    try:
        calendars = service.calendarList().list().execute()
        for cal in calendars.get('items', []):
            if cal.get('summary', '').lower() == calendar_name.lower():
                return cal['id']
        return None
    except HttpError as e:
        print(f"Error listing calendars: {e}")
        return None


def create_calendar(service, calendar_name: str = CALENDAR_NAME) -> Optional[str]:
    """
    Create a new calendar.
    
    Args:
        service: Google Calendar API service
        calendar_name: Name for new calendar
        
    Returns:
        New calendar ID
    """
    try:
        calendar = {
            'summary': calendar_name,
            'timeZone': 'Europe/Berlin'
        }
        created = service.calendars().insert(body=calendar).execute()
        return created['id']
    except HttpError as e:
        print(f"Error creating calendar: {e}")
        return None


def get_or_create_calendar(service, calendar_name: str = CALENDAR_NAME) -> str:
    """Get calendar ID, creating if needed."""
    cal_id = find_calendar_id(service, calendar_name)
    if not cal_id:
        print(f"Creating calendar: {calendar_name}")
        cal_id = create_calendar(service, calendar_name)
    return cal_id


def event_to_calendar_event(event: Event) -> dict:
    """
    Convert our Event to Google Calendar event format.
    
    Args:
        event: Our Event object
        
    Returns:
        Google Calendar event dict
    """
    # Build title
    emoji = "🏆" if event.event_type == "tournament" else "⚽"
    title = f"{emoji} {event.organizer or 'Fußball Event'}"
    if event.age_group:
        title += f" ({event.age_group})"
    
    # Build description
    desc_parts = []
    if event.event_type == "tournament":
        desc_parts.append("🏆 TURNIER")
    else:
        desc_parts.append("⚽ TESTSPIEL")
    
    if event.skill_level:
        desc_parts.append(f"Stärke: {event.skill_level}/10")
    if event.age_group:
        desc_parts.append(f"Altersklasse: {event.age_group}")
    if event.entry_fee:
        desc_parts.append(f"Startgebühr: {event.entry_fee}€")
    if event.contact_name:
        desc_parts.append(f"Kontakt: {event.contact_name}")
    if event.contact_phone:
        desc_parts.append(f"Telefon: {event.contact_phone}")
    if event.status == "full":
        desc_parts.append("❌ AUSGEBUCHT")
    if event.maps_url:
        desc_parts.append(f"\n📍 {event.maps_url}")
    
    description = "\n".join(desc_parts)
    
    # Build time
    if event.date:
        date_str = event.date.isoformat()
        
        if event.time_start:
            # Timed event
            start_time = f"{date_str}T{event.time_start}:00"
            if event.time_end:
                end_time = f"{date_str}T{event.time_end}:00"
            else:
                # Default 2 hour duration
                start_dt = datetime.fromisoformat(start_time)
                end_dt = start_dt + timedelta(hours=2)
                end_time = end_dt.isoformat()
            
            start = {'dateTime': start_time, 'timeZone': 'Europe/Berlin'}
            end = {'dateTime': end_time, 'timeZone': 'Europe/Berlin'}
        else:
            # All-day event
            start = {'date': date_str}
            end = {'date': date_str}
    else:
        # No date - skip
        return None
    
    cal_event = {
        'summary': title,
        'description': description,
        'start': start,
        'end': end,
    }
    
    # Add location
    if event.location:
        cal_event['location'] = event.location
    
    return cal_event


def add_event_to_calendar(service, calendar_id: str, event: Event) -> Optional[str]:
    """
    Add an event to Google Calendar.
    
    Args:
        service: Google Calendar API service
        calendar_id: Calendar ID to add to
        event: Our Event object
        
    Returns:
        Created event ID or None
    """
    cal_event = event_to_calendar_event(event)
    if not cal_event:
        return None
    
    try:
        created = service.events().insert(
            calendarId=calendar_id,
            body=cal_event
        ).execute()
        return created.get('id')
    except HttpError as e:
        print(f"Error creating calendar event: {e}")
        return None


def sync_events_to_calendar(events: list[Event], calendar_name: str = CALENDAR_NAME) -> int:
    """
    Sync events to Google Calendar.
    
    Args:
        events: List of events to sync
        calendar_name: Calendar name to use
        
    Returns:
        Number of events added
    """
    service = get_calendar_service()
    calendar_id = get_or_create_calendar(service, calendar_name)
    
    if not calendar_id:
        print("Failed to get/create calendar")
        return 0
    
    added = 0
    for event in events:
        if not event.date:
            continue  # Skip events without dates
        
        event_id = add_event_to_calendar(service, calendar_id, event)
        if event_id:
            added += 1
            print(f"  ✓ Added: {event.date} - {event.organizer or 'Event'}")
    
    return added


def list_calendars():
    """List all available calendars."""
    service = get_calendar_service()
    calendars = service.calendarList().list().execute()
    
    print("Available calendars:")
    for cal in calendars.get('items', []):
        print(f"  - {cal.get('summary')} ({cal.get('id')[:30]}...)")


if __name__ == "__main__":
    print("Google Calendar Integration")
    print("-" * 40)
    
    try:
        service = get_calendar_service()
        print("✓ Authenticated successfully")
        
        list_calendars()
        
        cal_id = get_or_create_calendar(service, CALENDAR_NAME)
        print(f"\n'{CALENDAR_NAME}' calendar ID: {cal_id}")
        
    except Exception as e:
        print(f"Error: {e}")
