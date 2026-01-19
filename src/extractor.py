"""
Event extractor for German football/soccer announcements.
Extracts tournaments, friendly matches, and event details from messages.
"""

import re
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Optional
from pathlib import Path

from .parser import Message


@dataclass
class Event:
    """Represents a football event (tournament or friendly match)."""
    id: str
    event_type: str  # "tournament" or "friendly_match"
    date: date | None
    time_start: str | None
    time_end: str | None
    location: str | None
    maps_url: str | None = None  # Google Maps link
    skill_level: int | None = None  # 1-10 scale
    age_group: str | None = None  # e.g., "D-Jugend", "JG15"
    organizer: str | None = None
    contact_phone: str | None = None
    contact_name: str | None = None
    status: str = "open"  # "open" or "full"
    catering: bool = False
    entry_fee: float | None = None
    raw_text: str = ""
    summary: str = ""  # AI-generated summary
    source_timestamp: datetime | None = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        if d['date']:
            d['date'] = d['date'].isoformat()
        if d['source_timestamp']:
            d['source_timestamp'] = d['source_timestamp'].isoformat()
        return d
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Event':
        """Create from dictionary."""
        if data.get('date'):
            data['date'] = date.fromisoformat(data['date'])
        if data.get('source_timestamp'):
            data['source_timestamp'] = datetime.fromisoformat(data['source_timestamp'])
        return cls(**data)


# German keywords for event detection
TOURNAMENT_KEYWORDS = [
    r'turnier', r'einlad', r'teams?\s*gesucht', r'mannschaften?\s*gesucht',
    r'heimturnier', r'hallenturnier', r'fußballturnier'
]

MATCH_KEYWORDS = [
    r'testspiel', r'leistungsvergleich', r'freundschaftsspiel',
    r'suchen.*gegner', r'gegner\s*gesucht', r'sparring'
]

# Status keywords
FULL_KEYWORDS = [r'voll', r'ausgebucht', r'belegt', r'keine\s*plätze']

# Date patterns (German formats)
DATE_PATTERNS = [
    # DD.MM.YYYY or DD.MM.YY
    r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})',
    # DD/MM/YYYY
    r'(\d{1,2})/(\d{1,2})/(\d{2,4})',
    # "25. Januar" or "25.01."
    r'(\d{1,2})\.\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)',
    r'(\d{1,2})\.(\d{1,2})\.',
]

# Time patterns - more specific to avoid matching dates
TIME_PATTERN = re.compile(
    r'(?:ab\s+|beginn[:\s]*|start[:\s]*|von\s+)?(\d{1,2})[:\.](\d{2})\s*uhr'
    r'(?:\s*[-–bis]+\s*(\d{1,2})[:\.](\d{2})\s*(?:uhr)?)?',
    re.IGNORECASE
)

# Alternative time pattern for ranges like "11-14 uhr"
TIME_RANGE_PATTERN = re.compile(
    r'(?:von\s+)?(\d{1,2})(?:[:\.](\d{2}))?\s*[-–bis]+\s*(\d{1,2})(?:[:\.](\d{2}))?\s*uhr',
    re.IGNORECASE
)

# Skill level patterns
LEVEL_PATTERNS = [
    r'(?:stärke|niveau|spielstärke)[:\s]*(\d{1,2})',
    r'(?:stärke|niveau)[:\s]*(\d{1,2})\s*[-–]\s*(\d{1,2})',
    r'(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(?:skala|scala)',
]

# Age group patterns
AGE_PATTERNS = [
    r'([ABCDEFG])\s*-?\s*jugend',
    r'jg\s*(\d{2,4})',
    r'jahrgang\s*(\d{2,4})',
    r'u\s*(\d{1,2})',
]

# Location indicators
LOCATION_PATTERNS = [
    r'📍\s*([^\n]+)',  # Emoji marker
    r'(?:spielort|ort)[:\s]+(?:ist\s+)?(?:die\s+)?([^.\n]{10,60})',
    r'(?:turnhalle|sporthalle|halle)\s+(?:der\s+)?([^.\n]{5,50})',
    r'(\w+(?:straße|str\.?|weg|platz|allee)\s*\d+[^,\n]{0,30})',
    r'(\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+)',  # German postal code + city
]

# Phone number pattern
PHONE_PATTERN = re.compile(r'\+?\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{4,8}')


def extract_date(text: str, reference_year: int = 2026) -> date | None:
    """Extract date from German text."""
    text_lower = text.lower()
    
    # Month name mapping
    months = {
        'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
        'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
        'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12
    }
    
    # Try DD.MM.YYYY format
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            pass
    
    # Try "DD. Monat" format
    for month_name, month_num in months.items():
        match = re.search(rf'(\d{{1,2}})\.\s*{month_name}', text_lower)
        if match:
            day = int(match.group(1))
            try:
                return date(reference_year, month_num, day)
            except ValueError:
                pass
    
    # Try DD.MM. format (no year)
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.(?!\d)', text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        try:
            return date(reference_year, month, day)
        except ValueError:
            pass
    
    return None


def extract_time(text: str) -> tuple[str | None, str | None]:
    """Extract start and end time from text."""
    # Try range pattern first (e.g., "11-14 uhr")
    match = TIME_RANGE_PATTERN.search(text)
    if match:
        start_h = match.group(1)
        start_m = match.group(2) or "00"
        end_h = match.group(3)
        end_m = match.group(4) or "00"
        
        # Validate hours
        if int(start_h) <= 23 and int(end_h) <= 23:
            start = f"{int(start_h):02d}:{start_m}"
            end = f"{int(end_h):02d}:{end_m}"
            return start, end
    
    # Try specific time pattern (e.g., "09:00 Uhr")
    match = TIME_PATTERN.search(text)
    if match:
        start_h, start_m = match.group(1), match.group(2)
        
        # Validate hour
        if int(start_h) > 23:
            return None, None
            
        start = f"{int(start_h):02d}:{start_m}"
        
        end = None
        if match.group(3) and match.group(4):
            end_h, end_m = match.group(3), match.group(4)
            if int(end_h) <= 23:
                end = f"{int(end_h):02d}:{end_m}"
        
        return start, end
    return None, None


def extract_skill_level(text: str) -> int | None:
    """Extract skill level (1-10 scale) from text."""
    text_lower = text.lower()
    
    for pattern in LEVEL_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            level = int(match.group(1))
            if 1 <= level <= 10:
                return level
    return None


def extract_age_group(text: str) -> str | None:
    """Extract age group from text."""
    text_lower = text.lower()
    
    # D-Jugend, C-Jugend, etc.
    match = re.search(r'([abcdefg])\s*-?\s*jugend', text_lower)
    if match:
        return f"{match.group(1).upper()}-Jugend"
    
    # JG 15, Jahrgang 2015, etc.
    match = re.search(r'(?:jg|jahrgang)\s*[:\s]*(\d{2,4})', text_lower)
    if match:
        year = match.group(1)
        if len(year) == 2:
            year = f"20{year}"
        return f"JG{year}"
    
    # U13, U15, etc.
    match = re.search(r'u\s*(\d{1,2})', text_lower)
    if match:
        return f"U{match.group(1)}"
    
    return None


def extract_location(text: str) -> str | None:
    """Extract location from text."""
    for pattern in LOCATION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            # Clean up
            location = re.sub(r'\s+', ' ', location)
            # Remove trailing punctuation
            location = location.rstrip('.,;:')
            # Skip if too short or just whitespace
            if len(location) >= 5:
                return location[:80]  # Limit length
    return None


def extract_contact(text: str) -> tuple[str | None, str | None]:
    """Extract contact phone and name."""
    phone = None
    name = None
    
    # Find phone number
    match = PHONE_PATTERN.search(text)
    if match:
        phone = match.group(0)
    
    # Try to find name (often after "Grüße" or before contact info)
    name_patterns = [
        r'(?:grüße?|gruß)\s+(\w+)',
        r'(\w+)\s+(?:askania|borussia|croatia|hertha|union)',
    ]
    
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1)
            break
    
    return phone, name


def extract_organizer(text: str) -> str | None:
    """Extract organizing club/team name."""
    # Common patterns for club names
    patterns = [
        r'(s\.?d\.?\s*croatia\s*berlin)',
        r'(bsv\s*\d+)',
        r'((?:fc|sc|sv|tus|vfb|bsc|1\.\s*fc|sg|tsv|sfc)\s+[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'(?:von|vom|wir)\s+(?:der\s+)?([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){0,2})\s+(?:lädt|suchen|laden)',
        r'grüße?\s*\n?\s*\w+,?\s*([A-ZÄÖÜ][A-Za-zäöüß\.\s]+(?:berlin|brandenburg))',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            org = match.group(1).strip()
            # Clean up
            org = re.sub(r'\s+', ' ', org)
            if 3 < len(org) < 50:
                return org
    return None


def is_event_full(text: str) -> bool:
    """Check if event is marked as full/complete."""
    text_lower = text.lower()
    for keyword in FULL_KEYWORDS:
        if re.search(keyword, text_lower):
            return True
    return False


def has_catering(text: str) -> bool:
    """Check if event mentions catering."""
    keywords = [r'catering', r'verpflegung', r'essen', r'getränke', r'leibliche\s*wohl']
    text_lower = text.lower()
    for keyword in keywords:
        if re.search(keyword, text_lower):
            return True
    return False


def extract_entry_fee(text: str) -> float | None:
    """Extract entry/start fee."""
    match = re.search(r'(\d+)\s*(?:€|euro|eur)', text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def detect_event_type(text: str) -> str | None:
    """Detect if text describes a tournament or friendly match."""
    text_lower = text.lower()
    
    # Check for tournament keywords
    for keyword in TOURNAMENT_KEYWORDS:
        if re.search(keyword, text_lower):
            return "tournament"
    
    # Check for match keywords
    for keyword in MATCH_KEYWORDS:
        if re.search(keyword, text_lower):
            return "friendly_match"
    
    return None


def extract_event(message: Message, event_id: str | None = None) -> Event | None:
    """
    Extract event information from a message.
    
    Args:
        message: Parsed WhatsApp message
        event_id: Optional ID for the event
        
    Returns:
        Event object if an event was detected, None otherwise
    """
    text = message.content
    
    # Detect event type
    event_type = detect_event_type(text)
    if not event_type:
        return None
    
    # Generate event ID if not provided
    if not event_id:
        event_id = f"{message.timestamp.strftime('%Y%m%d%H%M')}-{hash(text) % 10000:04d}"
    
    # Extract date (use message year as reference)
    event_date = extract_date(text, message.timestamp.year)
    
    # Extract time
    time_start, time_end = extract_time(text)
    
    # Extract other details
    contact_phone, contact_name = extract_contact(text)
    
    return Event(
        id=event_id,
        event_type=event_type,
        date=event_date,
        time_start=time_start,
        time_end=time_end,
        location=extract_location(text),
        skill_level=extract_skill_level(text),
        age_group=extract_age_group(text),
        organizer=extract_organizer(text),
        contact_phone=contact_phone or message.sender,
        contact_name=contact_name,
        status="full" if is_event_full(text) else "open",
        catering=has_catering(text),
        entry_fee=extract_entry_fee(text),
        raw_text=text,
        source_timestamp=message.timestamp
    )


def extract_event_from_text(text: str, timestamp: datetime | None = None) -> Event | None:
    """
    Extract event from raw text (e.g., from OCR).
    
    Args:
        text: Raw text content
        timestamp: Optional timestamp for the source
        
    Returns:
        Event object if detected, None otherwise
    """
    # Create a dummy message
    msg = Message(
        timestamp=timestamp or datetime.now(),
        sender="unknown",
        content=text
    )
    return extract_event(msg)


def extract_events_from_messages(messages: list[Message]) -> list[Event]:
    """Extract all events from a list of messages."""
    events = []
    for msg in messages:
        event = extract_event(msg)
        if event:
            events.append(event)
    return events


class EventDatabase:
    """Simple JSON-based event database."""
    
    def __init__(self, db_path: str | Path = "data/events.json"):
        self.db_path = Path(db_path)
        self.events: dict[str, Event] = {}
        self._load()
    
    def _load(self):
        """Load events from JSON file."""
        if self.db_path.exists():
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for event_data in data:
                    event = Event.from_dict(event_data)
                    self.events[event.id] = event
    
    def save(self):
        """Save events to JSON file."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.db_path, 'w', encoding='utf-8') as f:
            data = [e.to_dict() for e in self.events.values()]
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def add(self, event: Event) -> bool:
        """Add event if not already exists. Returns True if added."""
        if event.id not in self.events:
            self.events[event.id] = event
            return True
        return False
    
    def update(self, event: Event):
        """Update or add event."""
        self.events[event.id] = event
    
    def get(self, event_id: str) -> Event | None:
        """Get event by ID."""
        return self.events.get(event_id)
    
    def all(self) -> list[Event]:
        """Get all events."""
        return list(self.events.values())
    
    def __len__(self) -> int:
        return len(self.events)


if __name__ == "__main__":
    # Test extraction
    from .parser import parse_export_text
    
    sample = """[13:32, 1/16/2026] +49 173 2843016: Guten Tag zusammen ✌️ 
Wir suchen für den 25.01. zwei Mannschaften für einen lockeren Leistungsvergleich von 11-14 uhr, Niveau 5. Spielort ist die Sporthalle am Neuendorfer Sand in Brandenburg an der Havel. Dabei sind wir (JG15) und unsere Gäste vom PSV Röbel-Müritz (JG 13-15).

Es wird ein kleines kostenfreies Catering-Angebot für die Mannschaften geben.

Bei Interesse gerne melden 😉

Beste Grüße Kay 
FC Borussia Brandenburg
[20:31, 1/16/2026] +49 176 70720831: ⚽️Guten Abend liebe Trainerkolleginnen und -kollegen,

die 2. D-Jugend von S.D Croatia Berlin lädt euch herzlich zum
1. Heimturnier in diesem Jahr ein.

📅 Samstag, 01.02.2026
🕘 Einlass ab 08:00 Uhr
🕙 Turnierbeginn: 09:00 Uhr
⏳ Ende: 13:30 uhr

📍 Turnhalle der Paul-Simmel-Grundschule
      Felixstrasse 26, 12099 Berlin

Spielstärke: 2-3 ( 1-10 Skala )
Startgeld: 30 €

Bei Interesse bitte PN an mich

Sportliche Grüße 
Tomislav, S.D Croatia Berlin⚽️"""

    messages = parse_export_text(sample)
    events = extract_events_from_messages(messages)
    
    for event in events:
        print(f"\n{'='*50}")
        print(f"Type: {event.event_type}")
        print(f"Date: {event.date}")
        print(f"Time: {event.time_start} - {event.time_end}")
        print(f"Location: {event.location}")
        print(f"Level: {event.skill_level}")
        print(f"Age: {event.age_group}")
        print(f"Organizer: {event.organizer}")
        print(f"Contact: {event.contact_name} ({event.contact_phone})")
        print(f"Status: {event.status}")
        print(f"Catering: {event.catering}")
        print(f"Fee: {event.entry_fee}€" if event.entry_fee else "Fee: Free")
