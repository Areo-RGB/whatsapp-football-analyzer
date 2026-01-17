"""
Message parser for WhatsApp chat exports.
Handles the format: [HH:MM, M/DD/YYYY] +phone: message
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator
from pathlib import Path


@dataclass
class Message:
    """Represents a single WhatsApp message."""
    timestamp: datetime
    sender: str
    content: str
    has_media: bool = False
    media_path: str | None = None

    def __repr__(self) -> str:
        return f"Message({self.timestamp}, {self.sender[:15]}..., {self.content[:30]}...)"


# Pattern for WhatsApp export format: [HH:MM, M/DD/YYYY] +phone: message
# Also handles: [HH:MM, DD/MM/YYYY] and [HH:MM, DD.MM.YYYY] formats
MESSAGE_PATTERN = re.compile(
    r'^\[(\d{1,2}:\d{2}),\s*(\d{1,2}[/\.]\d{1,2}[/\.]\d{4})\]\s*([^:]+):\s*(.*)$',
    re.MULTILINE
)

# Alternative format: DD/MM/YYYY, HH:MM - +phone: message (WhatsApp export without brackets)
MESSAGE_PATTERN_ALT = re.compile(
    r'^(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)$',
    re.MULTILINE
)

# Pattern for media attachments
MEDIA_PATTERN = re.compile(r'<?(Medien|Media|Bild|image|video|audio|document).*>?', re.IGNORECASE)


def parse_timestamp(time_str: str, date_str: str) -> datetime:
    """Parse timestamp from WhatsApp format."""
    # Normalize separators
    date_str = date_str.replace('.', '/')
    
    # Try different date formats
    formats = [
        f"%H:%M {date_str}",  # Will be combined
    ]
    
    combined = f"{time_str} {date_str}"
    
    # Try M/DD/YYYY (US format)
    try:
        return datetime.strptime(combined, "%H:%M %m/%d/%Y")
    except ValueError:
        pass
    
    # Try DD/MM/YYYY (EU format)
    try:
        return datetime.strptime(combined, "%H:%M %d/%m/%Y")
    except ValueError:
        pass
    
    # Try YYYY/MM/DD
    try:
        return datetime.strptime(combined, "%H:%M %Y/%m/%d")
    except ValueError:
        pass
    
    raise ValueError(f"Could not parse timestamp: {combined}")


def parse_export_file(file_path: str | Path) -> list[Message]:
    """
    Parse a WhatsApp chat export file.
    
    Args:
        file_path: Path to the exported chat .txt file
        
    Returns:
        List of Message objects
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Chat export not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return parse_export_text(content)


def parse_export_text(content: str) -> list[Message]:
    """
    Parse WhatsApp chat export text content.
    
    Args:
        content: Raw text content from WhatsApp export
        
    Returns:
        List of Message objects
    """
    messages: list[Message] = []
    current_message: Message | None = None
    
    lines = content.split('\n')
    
    for line in lines:
        # Try original format: [HH:MM, DD/MM/YYYY] +phone: message
        match = MESSAGE_PATTERN.match(line)
        if match:
            # Save previous message if exists
            if current_message:
                messages.append(current_message)
            
            time_str, date_str, sender, text = match.groups()
            
            try:
                timestamp = parse_timestamp(time_str, date_str)
            except ValueError:
                continue
            
            has_media = bool(MEDIA_PATTERN.search(text))
            
            current_message = Message(
                timestamp=timestamp,
                sender=sender.strip(),
                content=text.strip(),
                has_media=has_media
            )
            continue
        
        # Try alternative format: DD/MM/YYYY, HH:MM - +phone: message
        match_alt = MESSAGE_PATTERN_ALT.match(line)
        if match_alt:
            if current_message:
                messages.append(current_message)
            
            date_str, time_str, sender, text = match_alt.groups()
            
            try:
                timestamp = parse_timestamp(time_str, date_str)
            except ValueError:
                continue
            
            has_media = bool(MEDIA_PATTERN.search(text)) or '<Media omitted>' in text
            
            current_message = Message(
                timestamp=timestamp,
                sender=sender.strip(),
                content=text.strip(),
                has_media=has_media
            )
            continue
        
        # Multi-line message continuation
        if current_message:
            current_message.content += '\n' + line
    
    # Don't forget the last message
    if current_message:
        messages.append(current_message)
    
    return messages


def iter_messages(file_path: str | Path) -> Iterator[Message]:
    """
    Iterate over messages in a chat export file.
    Memory-efficient for large files.
    """
    for message in parse_export_file(file_path):
        yield message


if __name__ == "__main__":
    # Test with sample message
    sample = """[13:32, 1/16/2026] +49 173 2843016: Guten Tag zusammen ✌️ 
Wir suchen für den 25.01. zwei Mannschaften für einen lockeren Leistungsvergleich von 11-14 uhr, Niveau 5. Spielort ist die Sporthalle am Neuendorfer Sand in Brandenburg an der Havel.

Es wird ein kleines kostenfreies Catering-Angebot für die Mannschaften geben.

Bei Interesse gerne melden 😉

Beste Grüße Kay 
FC Borussia Brandenburg
[15:47, 1/16/2026] +49 177 2736869: Hello. 
Kann sich der Trainer von SFC FRIEDRICHSHAIN II bitte bei mir melden?!✌🏻⚽😌
Christian Askania Coepenick 🤍💙❤️"""
    
    messages = parse_export_text(sample)
    for msg in messages:
        print(f"[{msg.timestamp}] {msg.sender}: {msg.content[:50]}...")
