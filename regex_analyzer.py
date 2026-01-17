#!/usr/bin/env python3
"""
WhatsApp Football Event Analyzer - Pure Regex/Python Version (No AI)

Analyzes WhatsApp chat exports to extract football events (tournaments,
friendly matches, training sessions) using pattern matching only.

Usage:
    python regex_analyzer.py                           # Analyze default chat file
    python regex_analyzer.py --file "chat.txt"         # Analyze specific file
    python regex_analyzer.py --output events.json      # Save to JSON
    python regex_analyzer.py --format table            # Output as table
    python regex_analyzer.py --upcoming                # Only future events
"""

import re
import json
import argparse
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from collections import defaultdict


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ExtractedEvent:
    """Represents an extracted football event."""
    id: str = ""
    event_type: str = "unknown"  # tournament, friendly_match, training, other
    date: Optional[date] = None
    date_str: str = ""  # Original date string
    time_start: str = ""
    time_end: str = ""
    location: str = ""
    address: str = ""
    organizer: str = ""
    contact_phone: str = ""
    skill_level: str = ""  # spielschwach, mittelstark, spielstark
    age_group: str = ""  # U8, U9, F-Jugend, etc.
    play_format: str = ""  # 6+1, 5+1, 4+1, Funino
    play_duration: str = ""  # 3x20 min, 12 min, etc.
    teams_count: str = ""
    entry_fee: str = ""
    has_trophies: bool = False
    status: str = "open"  # open, full, cancelled
    raw_message: str = ""
    sender: str = ""
    message_date: Optional[datetime] = None
    confidence: float = 0.0  # 0-1 confidence score

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d['date'] = self.date.isoformat() if self.date else None
        d['message_date'] = self.message_date.isoformat() if self.message_date else None
        return d


@dataclass
class WhatsAppMessage:
    """Represents a parsed WhatsApp message."""
    timestamp: datetime
    sender: str
    content: str
    has_media: bool = False


# ============================================================================
# REGEX PATTERNS (German football announcements)
# ============================================================================

class GermanFootballPatterns:
    """Collection of regex patterns for German football event extraction."""

    # Message line pattern: DD/MM/YYYY, HH:MM - Sender: Message
    MESSAGE_LINE = re.compile(
        r'^(\d{2}/\d{2}/\d{4}),\s*(\d{2}:\d{2})\s*-\s*(.+?):\s*(.*)$',
        re.MULTILINE
    )

    # Alternative: DD.MM.YYYY, HH:MM - Sender: Message
    MESSAGE_LINE_ALT = re.compile(
        r'^(\d{2}\.\d{2}\.\d{4}),\s*(\d{2}:\d{2})\s*-\s*(.+?):\s*(.*)$',
        re.MULTILINE
    )

    # Date patterns (German formats)
    DATES = [
        # 29.10.2022, 29.10.22
        re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})'),
        # 29/10/2022
        re.compile(r'(\d{1,2})/(\d{1,2})/(\d{2,4})'),
        # "am 29.10" or "den 29.10"
        re.compile(r'(?:am|den|vom|zum|bis)\s+(\d{1,2})\.(\d{1,2})\.?(?:(\d{2,4}))?', re.IGNORECASE),
        # "29. Oktober 2022" or "29. Okt"
        re.compile(r'(\d{1,2})\.\s*(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|Jan|Feb|Mär|Apr|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\.?\s*(\d{2,4})?', re.IGNORECASE),
        # Relative: "diesen Samstag", "nächsten Sonntag"
        re.compile(r'(diesen?|nächsten?|kommenden?)\s+(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)', re.IGNORECASE),
    ]

    # Month name mapping
    MONTHS = {
        'januar': 1, 'jan': 1, 'februar': 2, 'feb': 2, 'märz': 3, 'mär': 3,
        'april': 4, 'apr': 4, 'mai': 5, 'juni': 6, 'jun': 6, 'juli': 7, 'jul': 7,
        'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'oktober': 10, 'okt': 10,
        'november': 11, 'nov': 11, 'dezember': 12, 'dez': 12
    }

    # Weekday mapping
    WEEKDAYS = {
        'montag': 0, 'dienstag': 1, 'mittwoch': 2, 'donnerstag': 3,
        'freitag': 4, 'samstag': 5, 'sonntag': 6
    }

    # Time patterns
    TIMES = [
        # 10:00 - 15:00 or 10.00 - 15.00 (ensure valid hours 0-23)
        re.compile(r'\b(0?[0-9]|1[0-9]|2[0-3])[:\.]([0-5]\d)\s*[-–bis]+\s*(0?[0-9]|1[0-9]|2[0-3])[:\.]([0-5]\d)', re.IGNORECASE),
        # Turnierbeginn: 10:00 or Beginn: 10:00
        re.compile(r'(?:Turnier)?[Bb]eginn[:\s]*(\d{1,2})[:\.]?(\d{2})?\s*(?:Uhr)?', re.IGNORECASE),
        # Ende: 13:30
        re.compile(r'Ende[:\s]*(\d{1,2})[:\.]?(\d{2})?\s*(?:Uhr)?', re.IGNORECASE),
        # 🕘 or 🕙 emoji followed by time
        re.compile(r'[🕐🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚🕛]\s*(?:\w+[:\s]+)?(\d{1,2})[:\.]?(\d{2})?\s*(?:Uhr)?', re.IGNORECASE),
        # ab 10:00 or ab 10 Uhr
        re.compile(r'\bab\s+(\d{1,2})[:\.]?(\d{2})?\s*(?:Uhr)?', re.IGNORECASE),
        # 10:00 Uhr or 10 Uhr (standalone)
        re.compile(r'\b(\d{1,2})[:\.](\d{2})\s*Uhr\b', re.IGNORECASE),
        re.compile(r'\b(\d{1,2})\s*Uhr\b', re.IGNORECASE),
    ]

    # Location/Address patterns
    LOCATIONS = [
        # Turnhalle/Sporthalle der ... Schule/Grundschule (check FIRST to get full name before street)
        re.compile(r'((?:Turn|Sport)halle\s+(?:der\s+)?[A-ZÄÖÜa-zäöüß\-\s]+?(?:[Ss]chule|[Gg]rundschule))', re.IGNORECASE),
        # 📍 emoji followed by location
        re.compile(r'📍\s*([A-ZÄÖÜa-zäöüß\s\-]+(?:halle|schule|platz|stadion|feld)[A-ZÄÖÜa-zäöüß\s\-]*)', re.IGNORECASE),
        # Spielort ist die Sporthalle XYZ in CITY
        re.compile(r'Spielort\s+ist\s+(?:die\s+)?([A-ZÄÖÜa-zäöüß\s\-]+?(?:halle|platz|feld)[A-ZÄÖÜa-zäöüß\s\-]*?)(?:\s+in\s+([A-ZÄÖÜa-zäöüß\s\-]+?))?(?:\.|,|$)', re.IGNORECASE),
        # Street address with better pattern: "Felixstrasse 26" or "Felixstr. 26" etc
        re.compile(r'(\b[A-ZÄÖÜa-zäöüß\s\.\-]+(?:str\.?|straße|weg|damm|allee|platz|zeile|ring|chaussee|ufer)\s+\d+(?:[\s\-]*\d+)?[a-z]?)', re.IGNORECASE),
        # Full street address with PLZ: Felixstrasse 26, 12099 Berlin or HALKERZEILE 151 + 12305 BERLIN
        re.compile(r'([A-ZÄÖÜa-zäöüß\-]+(?:straße|strasse|str\.|weg|damm|platz|allee|ring|chaussee|ufer|zeile)[.\s]+\d+[a-z]?)[,\s\+]+(\d{5})[,\s]*(Berlin|Brandenburg[^.]*|Potsdam)?', re.IGNORECASE),
        # Spielort: LOCATION (simple)
        re.compile(r'Spielort[:\s]+([A-ZÄÖÜa-zäöüß\-]+)', re.IGNORECASE),
        # "bei uns in/im LOCATION"
        re.compile(r'bei\s+uns\s+(?:in|im|auf)\s*([A-ZÄÖÜa-zäöüß\-]+)', re.IGNORECASE),
    ]

    # Play format patterns (players + goalkeeper)
    PLAY_FORMATS = [
        re.compile(r'(\d)\s*\+\s*(\d)', re.IGNORECASE),  # 6+1, 5+1, 4+1
        re.compile(r'(?:Spielmodus|Format)[:\s]*(\d)\s*(?:gegen|vs?\.?|:)\s*(\d)', re.IGNORECASE),  # explicit: 4 v 4
        re.compile(r'\b(\d)\s*(?:gegen|vs\.?)\s*(\d)\b', re.IGNORECASE),  # 4 v 4 (word boundary)
        re.compile(r'Funin[oñ]o?', re.IGNORECASE),  # Funino/Funiño
        re.compile(r'Spielmodus[:\s]*(\d+\s*\+\s*\d+)', re.IGNORECASE),  # Spielmodus: 4+1
    ]

    # Duration patterns
    DURATIONS = [
        re.compile(r'(\d+)\s*[xX×]\s*(\d+)\s*[Mm]in', re.IGNORECASE),  # 3x20 min
        re.compile(r'(\d+)\s*[Mm]in\.?(?:uten)?', re.IGNORECASE),  # 12 min
        re.compile(r'Spielzeit[:\s]*(\d+)\s*[Mm]in', re.IGNORECASE),  # Spielzeit: 12 min
        re.compile(r'(\d+)\s*[-–]\s*(\d+)\s*[Mm]in', re.IGNORECASE),  # 10-12 min
    ]

    # Skill level patterns
    SKILL_LEVELS = {
        'spielschwach': re.compile(r'spielschwach|spiel\s*schwach|schwach(?:e[rn]?)?', re.IGNORECASE),
        'mittelstark': re.compile(r'mittelstark|mittel\s*stark|mittel(?:starke?[rn]?)?', re.IGNORECASE),
        'spielstark': re.compile(r'spielstark|spiel\s*stark|stark(?:e[rn]?)?|leistungsstark', re.IGNORECASE),
    }

    # Age group patterns
    AGE_GROUPS = [
        re.compile(r'U\s*(\d{1,2})', re.IGNORECASE),  # U9, U10
        re.compile(r'([EFGD])\s*[-]?\s*Jugend', re.IGNORECASE),  # F-Jugend, E-Jugend
        re.compile(r'(?:Jahrgang|JG\.?|Jg\.?)\s*(\d{4})', re.IGNORECASE),  # Jahrgang 2014
        re.compile(r'2014(?:er)?|2015(?:er)?|2013(?:er)?', re.IGNORECASE),  # 2014er
    ]

    # Event type indicators
    EVENT_TYPES = {
        'tournament': re.compile(
            r'Turnier|Cup|Pokal|Hallenturnier|Feldturnier|Leistungsvergleich|'
            r'Weihnachtsturnier|Herbstturnier|Frühlingsturnier|Sommerturnier',
            re.IGNORECASE
        ),
        'friendly_match': re.compile(
            r'Testspiel|Freundschaftsspiel|Trainingsspiel|Spielpartner|'
            r'Testspielgegner|Spielgegner|Gegner\s+(?:gesucht|sucht)',
            re.IGNORECASE
        ),
        'training': re.compile(
            r'Training|Trainingszeit|gemeinsames?\s+Training|mittrainieren',
            re.IGNORECASE
        ),
    }

    # Team/Club patterns - matches full club name including suffix
    # More greedy pattern to capture full club names like "Croatia Berlin" or "Borussia Brandenburg"
    CLUBS = re.compile(
        r'(?:1\.\s*)?'
        r'(?:FC|SC|SV|BFC|TSV|FSV|VfB|SpVgg|SG|SK|BSC|NFC|TuS|LBC|'
        r'Hertha|Union|Dynamo|Tennis\s*Borussia|Berliner\s*AK|BAK|S\.?D\.?|'
        r'Rot[\s\-]?Weiß|Blau[\s\-]?Gelb|Askania|BSV|Borussia)'
        r'(?:\s*\d{4})?\s*'  # Optional year like BSV1892 or Borussia 1920
        r'([A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß\s\-\.]*?)'  # Club name - at least one letter start
        r'(?:\s*(?:D\d+|U\d+|F\d+|\d{4}er?|e\.V\.)|,|$|\.|⚽️?)',
        re.IGNORECASE
    )

    # Alternative: Full club name pattern for signatures/specific mentions
    CLUB_FULL = re.compile(
        r'(?:vom?|von|der|des|bei)?\s*'
        r'(?:1\.\s*)?'
        r'((?:FC|SC|SV|BFC|TSV|FSV|VfB|SpVgg|SG|SK|BSC|NFC|TuS|LBC|'
        r'Hertha|Union|Dynamo|Tennis\s*Borussia|Berliner\s*AK|BAK|S\.?\s*D\.?|'
        r'Rot[\s\-]?Weiß|Blau[\s\-]?Gelb|Askania|BSV|Borussia)'
        r'(?:\d{4})?\s*'  # Optional year (no space before - BSV1892)
        r'[A-ZÄÖÜa-zäöüß]?[A-ZÄÖÜa-zäöüß\s\-\.]*?)'  # Optional rest of the name
        r'(?:\s*(?:D\d+|U\d+|F\d+|\d{4}er?|e\.V\.)|,|\s*⚽️|\s*lädt|\s*sucht|\s+D\d|$)',
        re.IGNORECASE
    )

    # Signature pattern - for finding organizer at end of message
    SIGNATURE = re.compile(
        r'(?:Grüße?|Gruß|VG|LG|MfG|Sportliche Grüße)\s*,?\s*\n?\s*'
        r'([A-ZÄÖÜa-zäöüß]+(?:\s+[A-ZÄÖÜa-zäöüß]+)?)'  # Name
        r'(?:[,\s]+)?'
        r'((?:1\.\s*)?(?:FC|SC|SV|BFC|TSV|FSV|VfB|SpVgg|SG|SK|BSC|NFC|TuS|S\.?\s*D\.?|BSV|Askania|'
        r'Rot[\s\-]?Weiß|Blau[\s\-]?Gelb|Borussia)\s*'
        r'(?:\d{4}\s*)?[A-ZÄÖÜa-zäöüß\s\-\.]+)?',
        re.IGNORECASE | re.MULTILINE
    )

    # Entry fee patterns - must have € or Euro nearby, and NOT be followed by "uhr"
    ENTRY_FEE = [
        re.compile(r'(?:Startgebühr|Teilnahmegebühr|Startgeld|Gebühr)[:\s]*(\d+)\s*[€Euro]', re.IGNORECASE),
        re.compile(r'(\d+)\s*[€E]\s*(?:uro)?(?:\s*\(|\s*Startgebühr|\s*Teilnahme|\s*Startgeld|\s*pro\s+Team)?', re.IGNORECASE),  # 30 € or 30€
        re.compile(r'(?:Startgebühr|Startgeld)[:\s]*(\d+)(?!\s*(?:uhr|Uhr))\b', re.IGNORECASE),  # Startgeld: 30 (not followed by uhr)
        re.compile(r'Startgebühr[:\s]*❌|keine\s*(?:Start)?gebühr|kostenfrei|kostenlos', re.IGNORECASE),  # No fee
    ]

    # Trophy/Prize patterns
    TROPHIES = re.compile(r'Pokal[e]?|🏆|Pokale?\s*:\s*[Jj]a', re.IGNORECASE)

    # Status patterns
    STATUS_FULL = re.compile(
        r'ausgebucht|voll|belegt|gefunden|nicht\s+mehr|abgesagt|'
        r'Gegner\s+gefunden|Teams?\s+gefunden|Platz\s+vergeben',
        re.IGNORECASE
    )

    # Phone number patterns
    PHONE = re.compile(r'\+?\d{2,4}\s*\d{3,4}\s*\d{4,8}')

    # Teams count
    TEAMS_COUNT = [
        re.compile(r'(\d+)\s*Teams?', re.IGNORECASE),
        re.compile(r'Teams?[:\s]*(\d+)', re.IGNORECASE),
        re.compile(r'(\d+)\s*Mannschaften?', re.IGNORECASE),
    ]

    # Search indicators (someone looking for something)
    SEARCH_INDICATOR = re.compile(
        r'such(?:t|en|e)|gesucht|brauchen?\s+(?:noch)?|fehlt\s+(?:noch)?|'
        r'wer\s+hat|hätte[n]?\s+Interesse',
        re.IGNORECASE
    )


# ============================================================================
# PARSER
# ============================================================================

class WhatsAppChatParser:
    """Parse WhatsApp chat export files."""

    def __init__(self):
        self.patterns = GermanFootballPatterns()

    def parse_file(self, filepath: str) -> list[WhatsAppMessage]:
        """Parse a WhatsApp chat export file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return self.parse_content(content)

    def parse_content(self, content: str) -> list[WhatsAppMessage]:
        """Parse WhatsApp chat content."""
        messages = []
        current_msg = None

        for line in content.split('\n'):
            # Try to match message line
            match = self.patterns.MESSAGE_LINE.match(line)
            if not match:
                match = self.patterns.MESSAGE_LINE_ALT.match(line)

            if match:
                # Save previous message
                if current_msg:
                    messages.append(current_msg)

                date_str, time_str, sender, text = match.groups()

                # Parse timestamp
                try:
                    if '/' in date_str:
                        ts = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                    else:
                        ts = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
                except ValueError:
                    ts = datetime.now()

                # Check for media
                has_media = '<Media omitted>' in text or '(file attached)' in text

                current_msg = WhatsAppMessage(
                    timestamp=ts,
                    sender=sender.strip(),
                    content=text.strip(),
                    has_media=has_media
                )
            elif current_msg:
                # Continuation of previous message
                current_msg.content += '\n' + line

        # Don't forget last message
        if current_msg:
            messages.append(current_msg)

        return messages


# ============================================================================
# EVENT EXTRACTOR
# ============================================================================

class FootballEventExtractor:
    """Extract football events from WhatsApp messages using regex patterns."""

    def __init__(self):
        self.patterns = GermanFootballPatterns()

    def extract_events(self, messages: list[WhatsAppMessage]) -> list[ExtractedEvent]:
        """Extract events from a list of messages."""
        events = []

        for msg in messages:
            # Skip system messages, deleted messages, very short messages
            if self._is_system_message(msg):
                continue

            # Check if message likely contains event info
            if not self._is_event_relevant(msg.content):
                continue

            event = self._extract_event(msg)
            if event and event.confidence > 0.3:
                events.append(event)

        return events

    def _is_system_message(self, msg: WhatsAppMessage) -> bool:
        """Check if message is a system message."""
        system_indicators = [
            'Messages and calls are end-to-end encrypted',
            'created group',
            'added you',
            'added +',
            'left',
            'removed',
            'changed the subject',
            'changed this group',
            'This message was deleted',
        ]
        return any(ind in msg.content for ind in system_indicators)

    def _is_event_relevant(self, text: str) -> bool:
        """Quick check if message might contain event information."""
        # Must have at least one indicator
        indicators = [
            # Event types
            r'turnier|cup|pokal|testspiel|freundschaftsspiel|training',
            # Actions
            r'such(?:t|en|e)|veranstalte|einlad|melden',
            # Date indicators
            r'\d{1,2}\.\d{1,2}\.|\d{1,2}/\d{1,2}/|am\s+\d|den\s+\d',
            # Play format
            r'\d\s*\+\s*\d|funino',
            # Time
            r'\d{1,2}:\d{2}|\d{1,2}\s*uhr',
        ]

        pattern = '|'.join(indicators)
        return bool(re.search(pattern, text, re.IGNORECASE))

    def _extract_event(self, msg: WhatsAppMessage) -> Optional[ExtractedEvent]:
        """Extract event details from a single message."""
        text = msg.content
        confidence = 0.0

        event = ExtractedEvent(
            raw_message=text,
            sender=msg.sender,
            message_date=msg.timestamp
        )

        # Extract event type
        event.event_type, type_conf = self._extract_event_type(text)
        confidence += type_conf * 0.2

        # Extract date
        event.date, event.date_str, date_conf = self._extract_date(text, msg.timestamp)
        confidence += date_conf * 0.25

        # Extract time
        event.time_start, event.time_end, time_conf = self._extract_time(text)
        confidence += time_conf * 0.1

        # Extract location
        event.location, event.address, loc_conf = self._extract_location(text)
        confidence += loc_conf * 0.1

        # Extract organizer
        event.organizer, org_conf = self._extract_organizer(text, msg.sender)
        confidence += org_conf * 0.1

        # Extract skill level
        event.skill_level, skill_conf = self._extract_skill_level(text)
        confidence += skill_conf * 0.05

        # Extract age group
        event.age_group, age_conf = self._extract_age_group(text)
        confidence += age_conf * 0.05

        # Extract play format
        event.play_format, format_conf = self._extract_play_format(text)
        confidence += format_conf * 0.05

        # Extract duration
        event.play_duration = self._extract_duration(text)

        # Extract teams count
        event.teams_count = self._extract_teams_count(text)

        # Extract entry fee
        event.entry_fee = self._extract_entry_fee(text)

        # Check for trophies
        event.has_trophies = bool(self.patterns.TROPHIES.search(text))

        # Extract contact phone
        event.contact_phone = self._extract_phone(text, msg.sender)

        # Check status
        event.status = self._extract_status(text)

        # Generate ID
        event.id = self._generate_id(event)

        event.confidence = min(confidence, 1.0)

        return event

    def _extract_event_type(self, text: str) -> tuple[str, float]:
        """Extract event type from text."""
        for event_type, pattern in self.patterns.EVENT_TYPES.items():
            if pattern.search(text):
                return event_type, 1.0
        return 'unknown', 0.0

    def _extract_date(self, text: str, msg_date: datetime) -> tuple[Optional[date], str, float]:
        """Extract date from text."""
        # Try explicit date patterns
        for pattern in self.patterns.DATES[:4]:  # Non-relative patterns
            match = pattern.search(text)
            if match:
                groups = match.groups()
                try:
                    if len(groups) >= 2:
                        day = int(groups[0])

                        # Check if month is text or number
                        if groups[1].isdigit():
                            month = int(groups[1])
                        else:
                            month = self.patterns.MONTHS.get(groups[1].lower(), 0)

                        if month == 0:
                            continue

                        # Year
                        if len(groups) >= 3 and groups[2]:
                            year = int(groups[2])
                            if year < 100:
                                year += 2000
                        else:
                            year = msg_date.year
                            # If month is before current month, assume next year
                            if month < msg_date.month:
                                year += 1

                        extracted_date = date(year, month, day)
                        return extracted_date, match.group(), 1.0
                except (ValueError, TypeError):
                    continue

        # Try relative dates (diesen Samstag, nächsten Sonntag)
        rel_pattern = self.patterns.DATES[4]
        match = rel_pattern.search(text)
        if match:
            modifier, weekday = match.groups()
            weekday_num = self.patterns.WEEKDAYS.get(weekday.lower())

            if weekday_num is not None:
                current_weekday = msg_date.weekday()
                days_ahead = weekday_num - current_weekday

                if 'nächst' in modifier.lower() or 'kommend' in modifier.lower():
                    if days_ahead <= 0:
                        days_ahead += 7
                else:  # "diesen"
                    if days_ahead < 0:
                        days_ahead += 7

                extracted_date = (msg_date + timedelta(days=days_ahead)).date()
                return extracted_date, match.group(), 0.7

        return None, "", 0.0

    def _extract_time(self, text: str) -> tuple[str, str, float]:
        """Extract time from text."""
        start_time = ""
        end_time = ""

        # Time range pattern (10:00 - 15:00) - but validate hours are reasonable
        match = self.patterns.TIMES[0].search(text)
        if match:
            h1, m1, h2, m2 = match.groups()
            h1_int = int(h1)
            h2_int = int(h2)
            # Validate: hours should be 0-23 and start should be before end (or same for overnight)
            if 0 <= h1_int <= 23 and 0 <= h2_int <= 23:
                return f"{h1}:{m1}", f"{h2}:{m2}", 1.0

        # Turnierbeginn/Beginn pattern
        match = self.patterns.TIMES[1].search(text)
        if match:
            hour = match.group(1)
            minute = match.group(2) if match.group(2) else "00"
            start_time = f"{hour}:{minute}"

        # Ende pattern
        match = self.patterns.TIMES[2].search(text)
        if match:
            hour = match.group(1)
            minute = match.group(2) if match.group(2) else "00"
            end_time = f"{hour}:{minute}"

        if start_time:
            return start_time, end_time, 0.9 if end_time else 0.8

        # Clock emoji patterns
        match = self.patterns.TIMES[3].search(text)
        if match:
            hour = match.group(1)
            minute = match.group(2) if match.group(2) else "00"
            return f"{hour}:{minute}", "", 0.7

        # "ab" pattern
        match = self.patterns.TIMES[4].search(text)
        if match:
            hour = match.group(1)
            minute = match.group(2) if match.group(2) else "00"
            return f"{hour}:{minute}", "", 0.7

        # Single time with Uhr
        for pattern in self.patterns.TIMES[5:]:
            match = pattern.search(text)
            if match:
                hour = match.group(1)
                minute = match.group(2) if len(match.groups()) > 1 and match.group(2) else "00"
                return f"{hour}:{minute}", "", 0.6

        return "", "", 0.0

    def _extract_location(self, text: str) -> tuple[str, str, float]:
        """Extract location from text."""
        location = ""
        address = ""
        confidence = 0.0

        # First: Turnhalle/Sporthalle der Schule (check FIRST for full hall name)
        pattern = self.patterns.LOCATIONS[0]
        match = pattern.search(text)
        if match:
            location = match.group(1).strip()
            location = re.sub(r'\s+', ' ', location)  # Normalize whitespace

            # Also look for full street address with PLZ
            street_match = self.patterns.LOCATIONS[4].search(text)
            if street_match and len(street_match.groups()) >= 1:
                street = street_match.group(1).strip()
                plz = street_match.group(2) if len(street_match.groups()) > 1 else ""
                city = street_match.group(3) if len(street_match.groups()) > 2 else ""

                address = street
                if plz:
                    address += f", {plz}"
                if city:
                    address += f" {city}"

            if len(location) > 8:
                return location, address, 0.9 if address else 0.85

        # Second: 📍 emoji
        pattern = self.patterns.LOCATIONS[1]
        match = pattern.search(text)
        if match:
            location = match.group(1).strip()
            location = re.sub(r'\s+', ' ', location)
            if len(location) > 5:
                return location, "", 0.85

        # Third: Spielort ist die Sporthalle XYZ in CITY
        pattern = self.patterns.LOCATIONS[2]
        match = pattern.search(text)
        if match:
            hall = match.group(1).strip() if match.group(1) else ""
            city = match.group(2).strip() if len(match.groups()) > 1 and match.group(2) else ""
            hall = re.sub(r'\s+', ' ', hall).strip()

            if city:
                location = f"{hall} ({city})"
            else:
                location = hall
            if len(location) > 5:
                return location, "", 0.85

        # Fourth: Improved street address pattern
        pattern = self.patterns.LOCATIONS[3]
        match = pattern.search(text)
        if match:
            address = match.group(1).strip()
            address = re.sub(r'\s+', ' ', address)
            if len(address) > 5:
                return address, address, 0.8

        # Fifth: Full street address with PLZ (most reliable for address)
        pattern = self.patterns.LOCATIONS[4]
        match = pattern.search(text)
        if match:
            street = match.group(1).strip()
            plz = match.group(2) if len(match.groups()) > 1 else ""
            city = match.group(3).strip() if len(match.groups()) > 2 and match.group(3) else ""

            address = street
            if plz:
                address += f", {plz}"
            if city:
                address += f" {city}"
            location = city if city else street
            return location, address, 0.95

        # Sixth: Spielort: LOCATION (simple)
        pattern = self.patterns.LOCATIONS[5]
        match = pattern.search(text)
        if match:
            location = match.group(1).strip()
            if len(location) > 3:
                return location, "", 0.7

        # Seventh: bei uns in LOCATION
        pattern = self.patterns.LOCATIONS[6]
        match = pattern.search(text)
        if match:
            location = match.group(1).strip()
            return location, "", 0.6

        return "", "", 0.0

    def _extract_organizer(self, text: str, sender: str) -> tuple[str, float]:
        """Extract organizer/club from text."""

        # OCR pattern: "LBC 25 | BERLIN" or "LBC 25 BERLIN"
        ocr_club_pattern = re.compile(
            r'(LBC\s*\d+(?:\s*\|?\s*BERLIN)?)',
            re.IGNORECASE)
        match = ocr_club_pattern.search(text)
        if match:
            club = match.group(1).strip().replace("|", "").replace("  ", " ")
            return club, 0.8

        # OCR pattern: "BFC Preussen" or "BFC Preüssen" (with umlaut from OCR)
        bfc_pattern = re.compile(
            r'(?:Der\s+)?(BFC\s+Preü?ssen)',
            re.IGNORECASE)
        match = bfc_pattern.search(text)
        if match:
            return "BFC Preussen", 0.9

        # First: Look for "SC/FC/SV Borussia XXXX YYYY" pattern directly
        # Handles: SC Borussia 1920 Friedrichsfelde
        combo_pattern = re.compile(
            r'((?:FC|SC|SV|BSV)\s+Borussia\s*(?:\d{4})?\s*[A-ZÄÖÜa-zäöüß]+)',
            re.IGNORECASE)
        match = combo_pattern.search(text)
        if match:
            club = match.group(1).strip()
            if len(club) > 8:
                return club, 0.95

        # Second: Look for "die X.D von CLUB" pattern (e.g., "die 2. D-Jugend von S.D Croatia Berlin")
        von_pattern = re.compile(
            r'(?:die\s+)?(?:\d\.?\s*)?(?:D|E|F)-?(?:Jugend)?\s+(?:von|des)\s+'
            r'((?:S\.?\s*D\.?|FC|SC|SV|BSV|SG|TuS|Borussia)\s*'
            r'(?:\d{4}\s*)?[A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß\s\-\.]+?)'
            r'(?:\s+lädt|\s+sucht|,|⚽️|$)', re.IGNORECASE)
        match = von_pattern.search(text)
        if match:
            club = match.group(1).strip()
            club = re.sub(r'[⚽️🏆✌️]+$', '', club).strip()
            if len(club) > 5:
                return club, 0.95

        # Third: Look for signature at end of message
        # Pattern: "Grüße\nName, Club Name"
        sig_match = self.patterns.SIGNATURE.search(text)
        if sig_match:
            name = sig_match.group(1).strip() if sig_match.group(1) else ""
            club = sig_match.group(2).strip() if sig_match.group(2) else ""

            # Clean up club name - remove trailing emojis and whitespace
            if club:
                club = re.sub(r'[⚽️🏆✌️]+', '', club).strip()
                club = re.sub(r'\s+', ' ', club)
                if len(club) > 5:
                    return club, 0.9

        # Fourth: Look for "wir vom/von CLUB D2 suchen" pattern
        wir_pattern = re.compile(
            r'wir\s+(?:vom|von|der|des)\s+'
            r'((?:FC|SC|SV|BSV|BSC|SG|TuS|Borussia)\s*(?:\d{4})?\s*[A-ZÄÖÜa-zäöüß]+)'
            r'(?:\s+D\d|\s+suchen|\s+laden|,|\.|$)', re.IGNORECASE)
        match = wir_pattern.search(text)
        if match:
            club = match.group(1).strip()
            if len(club) > 5:
                return club, 0.9

        # Fifth: Standard club name with prefix
        standard_pattern = re.compile(
            r'((?:FC|SC|SV|BSV|BSC|SG|TuS)\s+[A-ZÄÖÜa-zäöüß]+(?:\s+\d{4})?\s*[A-ZÄÖÜa-zäöüß]*)',
            re.IGNORECASE)
        match = standard_pattern.search(text)
        if match:
            club = match.group(1).strip()
            # Remove trailing junk
            club = re.sub(r'[⚽️🏆✌️,]+$', '', club).strip()
            if len(club) > 5:
                return club, 0.85

        # Sixth: Use CLUB_FULL pattern for full club names
        match = self.patterns.CLUB_FULL.search(text)
        if match:
            club = match.group(1).strip()
            club = re.sub(r'[⚽️🏆✌️]+', '', club).strip()
            club = re.sub(r'\s+', ' ', club)
            if len(club) > 5:
                return club, 0.85

        # Fifth: Look at last few lines for club name (common signature placement)
        lines = text.strip().split('\n')
        for line in reversed(lines[-5:]):
            line = line.strip()
            if not line:
                continue
            club_match = self.patterns.CLUB_FULL.search(line)
            if club_match:
                club = club_match.group(1).strip()
                club = re.sub(r'[⚽️🏆✌️]+', '', club).strip()
                if len(club) > 5:
                    return club, 0.8

        return "", 0.0

    def _extract_skill_level(self, text: str) -> tuple[str, float]:
        """Extract skill level from text."""
        found_levels = []

        for level, pattern in self.patterns.SKILL_LEVELS.items():
            if pattern.search(text):
                found_levels.append(level)

        if len(found_levels) == 1:
            return found_levels[0], 1.0
        elif len(found_levels) > 1:
            # Multiple levels found - likely a range
            return ' - '.join(found_levels), 0.8

        return "", 0.0

    def _extract_age_group(self, text: str) -> tuple[str, float]:
        """Extract age group from text."""
        for pattern in self.patterns.AGE_GROUPS:
            match = pattern.search(text)
            if match:
                return match.group(), 0.9
        return "", 0.0

    def _extract_play_format(self, text: str) -> tuple[str, float]:
        """Extract play format from text."""
        # Check for +1 format (most common and reliable)
        match = self.patterns.PLAY_FORMATS[0].search(text)
        if match:
            players, keeper = match.groups()
            # Validate: players should be 3-7 for youth football
            players_int = int(players)
            keeper_int = int(keeper)
            if 3 <= players_int <= 7 and keeper_int == 1:
                return f"{players}+{keeper}", 1.0

        # Check for Spielmodus: 4+1 format
        match = self.patterns.PLAY_FORMATS[4].search(text)
        if match:
            return match.group(1), 0.95

        # Check for explicit vs format with context (Spielmodus/Format: 4 vs 4)
        match = self.patterns.PLAY_FORMATS[1].search(text)
        if match:
            return f"{match.group(1)} vs {match.group(2)}", 0.9

        # Check for standalone vs format (less reliable)
        match = self.patterns.PLAY_FORMATS[2].search(text)
        if match:
            p1, p2 = int(match.group(1)), int(match.group(2))
            # Validate: both should be 3-7 for youth football
            if 3 <= p1 <= 7 and 3 <= p2 <= 7:
                return f"{match.group(1)} vs {match.group(2)}", 0.7

        # Check for Funino
        if self.patterns.PLAY_FORMATS[3].search(text):
            return "Funino", 1.0

        return "", 0.0

    def _extract_duration(self, text: str) -> str:
        """Extract play duration from text."""
        for pattern in self.patterns.DURATIONS:
            match = pattern.search(text)
            if match:
                return match.group()
        return ""

    def _extract_teams_count(self, text: str) -> str:
        """Extract teams count from text."""
        for pattern in self.patterns.TEAMS_COUNT:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return ""

    def _extract_entry_fee(self, text: str) -> str:
        """Extract entry fee from text."""
        # Try explicit patterns first (Startgeld: XX)
        for pattern in self.patterns.ENTRY_FEE[:3]:  # Patterns with context
            match = pattern.search(text)
            if match and match.groups():
                fee = match.group(1)
                # Validate: should be a reasonable fee amount (1-500)
                try:
                    fee_int = int(fee)
                    if 1 <= fee_int <= 500:
                        return f"{fee}€"
                except:
                    pass

        # Check for free events
        if self.patterns.ENTRY_FEE[3].search(text):
            return "kostenlos"

        return ""

    def _extract_phone(self, text: str, sender: str) -> str:
        """Extract contact phone number."""
        # If sender is a phone number, use that
        if re.match(r'^\+?\d', sender):
            return sender

        # Search in text
        match = self.patterns.PHONE.search(text)
        if match:
            return match.group()

        return ""

    def _extract_status(self, text: str) -> str:
        """Extract event status."""
        if self.patterns.STATUS_FULL.search(text):
            return "full"
        return "open"

    def _generate_id(self, event: ExtractedEvent) -> str:
        """Generate unique event ID."""
        parts = [
            event.event_type[:3] if event.event_type else "unk",
            event.date.isoformat() if event.date else "nodate",
            (event.organizer or "")[:10].replace(" ", ""),
            str(hash(event.raw_message[:50]))[-6:]
        ]
        return "-".join(parts)


# ============================================================================
# EVENT DEDUPLICATION
# ============================================================================

class EventDeduplicator:
    """Deduplicate events based on similarity."""

    def deduplicate(self, events: list[ExtractedEvent]) -> list[ExtractedEvent]:
        """Remove duplicate events, keeping the one with highest confidence."""
        seen = {}

        for event in events:
            key = self._get_similarity_key(event)

            if key in seen:
                # Keep event with higher confidence
                if event.confidence > seen[key].confidence:
                    seen[key] = event
            else:
                seen[key] = event

        return list(seen.values())

    def _get_similarity_key(self, event: ExtractedEvent) -> str:
        """Generate a key for similarity comparison."""
        return f"{event.date}|{event.organizer[:15] if event.organizer else ''}|{event.event_type}"


# ============================================================================
# OUTPUT FORMATTERS
# ============================================================================

class EventFormatter:
    """Format events for output."""

    def format_table(self, events: list[ExtractedEvent]) -> str:
        """Format events as ASCII table."""
        if not events:
            return "No events found."

        lines = []
        lines.append("=" * 100)
        lines.append(f"{'Date':<12} {'Type':<12} {'Organizer':<25} {'Level':<15} {'Format':<8} {'Status':<8}")
        lines.append("=" * 100)

        for e in sorted(events, key=lambda x: (x.date or date.max, x.confidence), reverse=False):
            date_str = e.date.strftime("%d.%m.%Y") if e.date else "TBD"
            type_icon = "🏆" if e.event_type == "tournament" else "⚽" if e.event_type == "friendly_match" else "🏃"
            org = (e.organizer[:23] + "..") if e.organizer and len(e.organizer) > 25 else (e.organizer or "-")
            level = e.skill_level[:13] if e.skill_level else "-"
            fmt = e.play_format or "-"
            status = "❌VOLL" if e.status == "full" else "✓"

            lines.append(f"{date_str:<12} {type_icon} {e.event_type:<9} {org:<25} {level:<15} {fmt:<8} {status:<8}")

        lines.append("=" * 100)
        lines.append(f"Total: {len(events)} events")

        return "\n".join(lines)

    def format_compact(self, events: list[ExtractedEvent]) -> str:
        """Format events in compact style."""
        if not events:
            return "No events found."

        lines = []

        # Group by date
        by_date = defaultdict(list)
        for e in events:
            key = e.date or date.max
            by_date[key].append(e)

        for event_date in sorted(by_date.keys()):
            if event_date == date.max:
                lines.append("\n📅 Datum unbekannt:")
            else:
                lines.append(f"\n📅 {event_date.strftime('%d.%m.%Y (%A)')}:")

            for e in by_date[event_date]:
                icon = "🏆" if e.event_type == "tournament" else "⚽"
                status = " [VOLL]" if e.status == "full" else ""
                org = e.organizer or "Unbekannt"
                level = f" ({e.skill_level})" if e.skill_level else ""
                time_str = f" {e.time_start}" if e.time_start else ""

                lines.append(f"  {icon} {org}{level}{time_str}{status}")

        lines.append(f"\n📊 Gesamt: {len(events)} Events gefunden")

        return "\n".join(lines)

    def format_full(self, events: list[ExtractedEvent]) -> str:
        """Format events with full details."""
        if not events:
            return "No events found."

        lines = []

        for i, e in enumerate(events, 1):
            lines.append(f"\n{'='*60}")
            lines.append(f"Event #{i}")
            lines.append(f"{'='*60}")

            icon = "🏆" if e.event_type == "tournament" else "⚽" if e.event_type == "friendly_match" else "🏃"
            lines.append(f"Type:       {icon} {e.event_type}")
            lines.append(f"Date:       {e.date.strftime('%d.%m.%Y') if e.date else 'TBD'}")
            lines.append(f"Time:       {e.time_start}{' - ' + e.time_end if e.time_end else ''}")
            lines.append(f"Organizer:  {e.organizer or '-'}")
            lines.append(f"Location:   {e.location or '-'}")
            lines.append(f"Address:    {e.address or '-'}")
            lines.append(f"Level:      {e.skill_level or '-'}")
            lines.append(f"Age Group:  {e.age_group or '-'}")
            lines.append(f"Format:     {e.play_format or '-'}")
            lines.append(f"Duration:   {e.play_duration or '-'}")
            lines.append(f"Teams:      {e.teams_count or '-'}")
            lines.append(f"Entry Fee:  {e.entry_fee or '-'}")
            lines.append(f"Trophies:   {'Yes 🏆' if e.has_trophies else 'No'}")
            lines.append(f"Status:     {'❌ FULL' if e.status == 'full' else '✓ Open'}")
            lines.append(f"Contact:    {e.contact_phone or '-'}")
            lines.append(f"Confidence: {e.confidence:.0%}")

            if e.raw_message:
                preview = e.raw_message[:200].replace('\n', ' ')
                lines.append(f"Message:    {preview}...")

        return "\n".join(lines)

    def format_json(self, events: list[ExtractedEvent]) -> str:
        """Format events as JSON."""
        return json.dumps([e.to_dict() for e in events], indent=2, ensure_ascii=False)


# ============================================================================
# STATISTICS
# ============================================================================

class EventStatistics:
    """Generate statistics from extracted events."""

    def generate(self, events: list[ExtractedEvent]) -> dict:
        """Generate statistics from events."""
        stats = {
            'total': len(events),
            'by_type': defaultdict(int),
            'by_status': defaultdict(int),
            'by_skill': defaultdict(int),
            'by_month': defaultdict(int),
            'organizers': defaultdict(int),
            'avg_confidence': 0.0,
        }

        confidences = []

        for e in events:
            stats['by_type'][e.event_type] += 1
            stats['by_status'][e.status] += 1

            if e.skill_level:
                stats['by_skill'][e.skill_level] += 1

            if e.date:
                month_key = e.date.strftime("%Y-%m")
                stats['by_month'][month_key] += 1

            if e.organizer:
                stats['organizers'][e.organizer] += 1

            confidences.append(e.confidence)

        if confidences:
            stats['avg_confidence'] = sum(confidences) / len(confidences)

        # Convert defaultdicts to regular dicts
        stats['by_type'] = dict(stats['by_type'])
        stats['by_status'] = dict(stats['by_status'])
        stats['by_skill'] = dict(stats['by_skill'])
        stats['by_month'] = dict(stats['by_month'])
        stats['organizers'] = dict(sorted(stats['organizers'].items(), key=lambda x: -x[1])[:10])

        return stats

    def format_stats(self, stats: dict) -> str:
        """Format statistics for display."""
        lines = [
            "\n" + "=" * 50,
            "📊 EXTRACTION STATISTICS",
            "=" * 50,
            f"\nTotal Events: {stats['total']}",
            f"Avg Confidence: {stats['avg_confidence']:.1%}",
            "\nBy Type:",
        ]

        for t, count in stats['by_type'].items():
            icon = "🏆" if t == "tournament" else "⚽" if t == "friendly_match" else "🏃"
            lines.append(f"  {icon} {t}: {count}")

        lines.append("\nBy Status:")
        for s, count in stats['by_status'].items():
            icon = "✓" if s == "open" else "❌"
            lines.append(f"  {icon} {s}: {count}")

        if stats['by_skill']:
            lines.append("\nBy Skill Level:")
            for level, count in stats['by_skill'].items():
                lines.append(f"  • {level}: {count}")

        if stats['organizers']:
            lines.append("\nTop Organizers:")
            for org, count in list(stats['organizers'].items())[:5]:
                lines.append(f"  • {org}: {count}")

        return "\n".join(lines)


# ============================================================================
# MAIN ANALYZER
# ============================================================================

class WhatsAppFootballAnalyzer:
    """Main analyzer class combining all components."""

    def __init__(self):
        self.parser = WhatsAppChatParser()
        self.extractor = FootballEventExtractor()
        self.deduplicator = EventDeduplicator()
        self.formatter = EventFormatter()
        self.stats = EventStatistics()

    def analyze_file(self, filepath: str, deduplicate: bool = True) -> list[ExtractedEvent]:
        """Analyze a WhatsApp chat export file."""
        print(f"📂 Loading: {filepath}")
        messages = self.parser.parse_file(filepath)
        print(f"📨 Parsed: {len(messages)} messages")

        print("🔍 Extracting events...")
        events = self.extractor.extract_events(messages)
        print(f"📋 Found: {len(events)} potential events")

        if deduplicate:
            events = self.deduplicator.deduplicate(events)
            print(f"🧹 After dedup: {len(events)} unique events")

        return events

    def filter_upcoming(self, events: list[ExtractedEvent], days_ahead: int = 365) -> list[ExtractedEvent]:
        """Filter to only upcoming events."""
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        return [e for e in events if e.date and today <= e.date <= cutoff]

    def filter_open(self, events: list[ExtractedEvent]) -> list[ExtractedEvent]:
        """Filter to only open events."""
        return [e for e in events if e.status == "open"]


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="WhatsApp Football Event Analyzer (Pure Python/Regex - No AI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python regex_analyzer.py
  python regex_analyzer.py --file "chat.txt" --format table
  python regex_analyzer.py --upcoming --open-only
  python regex_analyzer.py --output events.json --stats
        """
    )

    parser.add_argument(
        '--file', '-f',
        default='WhatsApp Chat with Jahrgang 2014er Trainer.txt',
        help='WhatsApp chat export file to analyze'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output JSON file path'
    )
    parser.add_argument(
        '--format',
        choices=['table', 'compact', 'full', 'json'],
        default='compact',
        help='Output format'
    )
    parser.add_argument(
        '--upcoming',
        action='store_true',
        help='Only show upcoming events'
    )
    parser.add_argument(
        '--open-only',
        action='store_true',
        help='Only show open events (exclude full/cancelled)'
    )
    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.3,
        help='Minimum confidence threshold (0-1)'
    )
    parser.add_argument(
        '--no-dedup',
        action='store_true',
        help='Disable deduplication'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show extraction statistics'
    )
    parser.add_argument(
        '--type',
        choices=['tournament', 'friendly_match', 'training', 'all'],
        default='all',
        help='Filter by event type'
    )

    args = parser.parse_args()

    # Check file exists
    if not Path(args.file).exists():
        print(f"❌ File not found: {args.file}")
        return 1

    # Run analyzer
    analyzer = WhatsAppFootballAnalyzer()

    try:
        events = analyzer.analyze_file(args.file, deduplicate=not args.no_dedup)
    except Exception as e:
        print(f"❌ Error analyzing file: {e}")
        return 1

    # Apply filters
    if args.min_confidence:
        events = [e for e in events if e.confidence >= args.min_confidence]

    if args.upcoming:
        events = analyzer.filter_upcoming(events)
        print(f"📅 Upcoming: {len(events)} events")

    if args.open_only:
        events = analyzer.filter_open(events)
        print(f"✓ Open: {len(events)} events")

    if args.type != 'all':
        events = [e for e in events if e.event_type == args.type]
        print(f"🎯 Type '{args.type}': {len(events)} events")

    # Output
    if args.format == 'table':
        print(analyzer.formatter.format_table(events))
    elif args.format == 'compact':
        print(analyzer.formatter.format_compact(events))
    elif args.format == 'full':
        print(analyzer.formatter.format_full(events))
    elif args.format == 'json':
        print(analyzer.formatter.format_json(events))

    # Statistics
    if args.stats:
        stats = analyzer.stats.generate(events)
        print(analyzer.stats.format_stats(stats))

    # Save to JSON
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump([e.to_dict() for e in events], f, indent=2, ensure_ascii=False)

        print(f"\n💾 Saved to: {args.output}")

    return 0


if __name__ == '__main__':
    exit(main())
