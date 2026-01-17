"""
AI-powered event extraction using Google Gemini CLI.
Uses the local Gemini CLI with user's subscription for unlimited access.
Supports both text and image analysis.
"""

import json
import subprocess
import tempfile
import base64
from datetime import date, datetime
from pathlib import Path

from .extractor import Event


EXTRACTION_PROMPT = """Du bist ein Experte für die Analyse von Fußball-Event-Ankündigungen aus WhatsApp-Nachrichten.
Extrahiere strukturierte Event-Informationen aus dem folgenden Text und/oder Bildern.

Der Text kann aus OCR (verrauscht) oder WhatsApp-Nachrichten stammen.
Extrahiere NUR Events, die Turniere oder Testspiele/Freundschaftsspiele sind.

Antworte IMMER im folgenden JSON-Format (NUR JSON, kein anderer Text):
{
  "events": [
    {
      "event_type": "tournament" oder "friendly_match",
      "date": "YYYY-MM-DD" oder null,
      "time_start": "HH:MM" oder null,
      "time_end": "HH:MM" oder null,
      "location": "Ort/Adresse" oder null,
      "maps_url": "Google Maps URL" oder null,
      "skill_level": Zahl 1-10 oder null,
      "age_group": "z.B. D-Jugend, U12, JG2014" oder null,
      "organizer": "Vereinsname" oder null,
      "contact_phone": "Telefonnummer im Format +49..." oder null,
      "contact_name": "Name der Kontaktperson" oder null,
      "entry_fee": Zahl oder null,
      "status": "open" oder "full",
      "summary": "Kurze Zusammenfassung auf Deutsch"
    }
  ]
}

GOOGLE MAPS LINKS:
- Wenn eine Adresse vorhanden ist, erstelle einen Google Maps Link im Format:
  https://www.google.com/maps/search/?api=1&query=[URL-encoded Adresse]
- Beispiel: "Felixstrasse 26, 12099 Berlin" wird zu:
  https://www.google.com/maps/search/?api=1&query=Felixstrasse+26%2C+12099+Berlin
- Ersetze Leerzeichen durch + und Sonderzeichen durch URL-Encoding (%2C für Komma etc.)

Wenn keine Events gefunden werden, antworte mit: {"events": []}

WICHTIG:
- Das aktuelle Jahr ist 2026
- Daten wie "25.01." bedeuten 25.01.2026
- Daten wie "08.03" oder "15.03" bedeuten 08.03.2026 bzw 15.03.2026
- "Stärke 5" oder "Niveau 5" bedeutet skill_level: 5
- "mittelstark 7/10" bedeutet skill_level: 7
- "voll" oder "ausgebucht" bedeutet status: "full"
- "Testspiel" oder "Spielpartner gesucht" = friendly_match
- "Turnier" oder "einladen" = tournament
- TELEFONNUMMER (contact_phone): 
  * WICHTIG: Nachrichten beginnen oft mit "[Von: +49...]" - diese Nummer ist die contact_phone des Absenders!
  * Beispiel: "[Von: +4917632223598]\nHallo zusammen..." → contact_phone: "+4917632223598"
  * Alternativ suche im Text nach: "Telefon:", "Tel:", "Mobil:", "Handy:"
  * IGNORIERE JIDs wie "4915783881850-1547842719@g.us" - das sind KEINE Telefonnummern!
- KONTAKTNAME (contact_name): Der Name der Kontaktperson findet sich oft:
  * Nach Grußformeln: "Grüße", "VG", "LG", "Beste Grüße", "Sportliche Grüße"
  * Als letzter Name vor einem Vereinsnamen (z.B. "Tomislav, S.D Croatia" → contact_name: "Tomislav")
  * Neben einer Telefonnummer (z.B. "Telefon Antje 0162..." → contact_name: "Antje")
  * In der Signatur am Ende der Nachricht
- Bei Bildern: Extrahiere alle sichtbaren Event-Informationen aus Flyern/Postern
"""


def call_gemini_cli(prompt: str, image_paths: list[str] | None = None) -> str | None:
    """
    Call Gemini CLI with a prompt and optional images.
    Uses the user's Gemini subscription via npx.
    
    Args:
        prompt: The prompt to send to Gemini
        image_paths: Optional list of image file paths to include
        
    Returns:
        Response text or None on error
    """
    try:
        # Build the prompt with image references if provided
        full_prompt = prompt
        if image_paths:
            full_prompt += "\n\nBitte analysiere auch diese Bilder:\n"
            for img_path in image_paths:
                full_prompt += f"- Bild: {img_path}\n"
        
        # Use npx to run the Gemini CLI with --yolo flag and model
        # Note: Gemini CLI reads files from current directory
        result = subprocess.run(
            ["npx", "-y", "@google/gemini-cli", "--yolo", "-m", "gemini-2.5-flash-lite", "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for images
            cwd=Path(image_paths[0]).parent if image_paths else None
        )
        
        if result.returncode == 0:
            return result.stdout
        else:
            print(f"  Gemini CLI error: {result.stderr[:200]}")
            return None
            
    except subprocess.TimeoutExpired:
        print("  Gemini CLI timeout")
        return None
    except Exception as e:
        print(f"  Gemini CLI error: {e}")
        return None


def extract_events_with_ai(text: str, image_paths: list[str] | None = None, source_date: datetime | None = None) -> list[Event]:
    """
    Extract events from text and/or images using Gemini AI.
    
    Args:
        text: Raw text (from OCR or messages)
        image_paths: Optional list of image file paths
        source_date: Optional source timestamp
        
    Returns:
        List of extracted Event objects
    """
    if not text and not image_paths:
        return []
    
    if text and len(text.strip()) < 20 and not image_paths:
        return []
    
    try:
        # Truncate very long text
        if text and len(text) > 8000:
            text = text[:8000]
        
        prompt = f"{EXTRACTION_PROMPT}\n\nAnalysiere diesen Text:\n\n{text or '(Kein Text, nur Bilder)'}"
        
        response = call_gemini_cli(prompt, image_paths)
        if not response:
            return []
        
        content = response
        
        # Parse JSON response - find JSON in response (might have markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            parts = content.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("{") or part.startswith("["):
                    content = part
                    break
        
        # Try to find JSON object in response
        start_idx = content.find("{")
        if start_idx == -1:
            print("  No JSON found in response")
            return []
        
        # Find matching closing brace
        content = content[start_idx:]
        
        data = json.loads(content.strip())
        events = []
        
        for i, event_data in enumerate(data.get("events", [])):
            # Parse date
            event_date = None
            if event_data.get("date"):
                try:
                    event_date = date.fromisoformat(event_data["date"])
                except:
                    pass
            
            # Generate ID
            event_id = f"ai-{datetime.now().strftime('%Y%m%d%H%M%S')}-{i}"
            
            event = Event(
                id=event_id,
                event_type=event_data.get("event_type", "tournament"),
                date=event_date,
                time_start=event_data.get("time_start"),
                time_end=event_data.get("time_end"),
                location=event_data.get("location"),
                maps_url=event_data.get("maps_url"),
                skill_level=event_data.get("skill_level"),
                age_group=event_data.get("age_group"),
                organizer=event_data.get("organizer"),
                contact_phone=event_data.get("contact_phone"),
                contact_name=event_data.get("contact_name"),
                status=event_data.get("status", "open"),
                entry_fee=event_data.get("entry_fee"),
                raw_text=text[:500] if text else "",
                source_timestamp=source_date
            )
            events.append(event)
        
        return events
        
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"AI extraction error: {e}")
        return []


def analyze_messages_with_ai(messages_text: str, image_paths: list[str] | None = None) -> list[Event]:
    """
    Analyze multiple messages at once with AI.
    
    Args:
        messages_text: Combined text of multiple messages
        image_paths: Optional list of image file paths
        
    Returns:
        List of extracted events
    """
    # Split into chunks if too long (max ~6000 chars per request for CLI)
    max_chunk = 6000
    chunks = []
    
    if len(messages_text) > max_chunk:
        # Split by message separators or newlines
        parts = messages_text.split("\n\n")
        current_chunk = ""
        
        for part in parts:
            if len(current_chunk) + len(part) < max_chunk:
                current_chunk += part + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = part + "\n\n"
        
        if current_chunk:
            chunks.append(current_chunk)
    else:
        chunks = [messages_text]
    
    all_events = []
    
    # Process first chunk with images (if any)
    if chunks:
        print(f"  Processing chunk 1/{len(chunks)} with {len(image_paths or [])} images...")
        events = extract_events_with_ai(chunks[0], image_paths)
        all_events.extend(events)
        print(f"    Found {len(events)} events")
    
    # Process remaining chunks (text only)
    for i, chunk in enumerate(chunks[1:], 2):
        print(f"  Processing chunk {i}/{len(chunks)}...")
        events = extract_events_with_ai(chunk)
        all_events.extend(events)
        print(f"    Found {len(events)} events")
    
    return all_events


if __name__ == "__main__":
    # Test with sample text
    test_text = """
    ⚽️Guten Abend liebe Trainerkolleginnen und -kollegen,

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

    Sportliche Grüße 
    Tomislav, S.D Croatia Berlin
    """
    
    print("Testing Gemini CLI extraction...")
    events = extract_events_with_ai(test_text)
    
    for event in events:
        print(f"\nEvent: {event.event_type}")
        print(f"  Date: {event.date}")
        print(f"  Time: {event.time_start} - {event.time_end}")
        print(f"  Location: {event.location}")
        print(f"  Maps: {event.maps_url}")
        print(f"  Level: {event.skill_level}")
        print(f"  Organizer: {event.organizer}")
        print(f"  Fee: {event.entry_fee}€")
