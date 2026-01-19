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

EXTRAHIERE NUR Nachrichten wo jemand:
1. Ein Turnier oder Testspiel VERANSTALTET und Teams sucht
2. Ein Team HAT das ein Turnier oder Testspiel SUCHT
3. Eine SERIE von Leistungsvergleichen/Spielterminen anbietet

WICHTIG - MEHRERE EVENTS:
- Eine Nachricht kann MEHRERE Termine enthalten!
- Beispiel: "📌 Mi., 21.01.2026" und "📌 Mi., 28.01.2026" = 2 separate Events
- Erstelle für JEDEN Termin ein eigenes Event im JSON Array

IGNORIERE diese Nachrichten:
- "Gefunden", "Danke für die Anfragen" - das sind nur Bestätigungen
- Nachrichten die jemanden bitten sich zu melden (z.B. "kann sich X bei mir melden")
- Nachrichten ohne konkretes Datum (nur "Samstag" ohne Datum reicht NICHT)

Antworte IMMER im folgenden JSON-Format (NUR JSON, kein anderer Text):
{
  "events": [
    {
      "event_type": "tournament" oder "friendly_match",
      "date": "YYYY-MM-DD" oder null,
      "time_start": "HH:MM" oder null,
      "time_end": "HH:MM" oder null,
      "location": "Vollständige Adresse für Google Calendar" oder null,
      "organizer": "Vereinsname" oder null,
      "contact_phone": "Telefonnummer im Format +49..." oder null,
      "contact_name": "Name der Kontaktperson" oder null,
      "entry_fee": Zahl oder null,
      "status": "open" oder "full",
      "summary": "Kurze Zusammenfassung auf Deutsch"
    }
  ]
}

LOCATION (Adresse):
- Formatiere die Adresse IMMER vollständig für Google Calendar Integration
- Format: "Straße Hausnummer, PLZ Stadt, Deutschland"
- Beispiel: "Ernst-Ludwig-Heim-Str. 14, 13125 Berlin, Deutschland"

KONTAKTNAME (contact_name) - SEHR WICHTIG:
- Steht IMMER am Ende der Nachricht nach Grußformeln
- Suche nach: "LG [Name]", "Grüße [Name]", "VG [Name]"
- Beispiele aus echten Nachrichten:
  * "LG Batuhan" → contact_name: "Batuhan"
  * "Viele Grüße Denis" → contact_name: "Denis"  
  * "Danke und Grüße André" → contact_name: "André"
  * "LG Selçuk" → contact_name: "Selçuk"
  * "Lg Sebastian" → contact_name: "Sebastian"

TELEFONNUMMER (contact_phone):
- Nachrichten beginnen mit "[Von: +49...]" - das ist die contact_phone!
- Beispiel: "[19.01.2026 09:35] [Von: +491793278560]" → contact_phone: "+491793278560"

ZEITEN (time_start, time_end):
- "10-15 uhr" oder "ca. 10-15 uhr" → time_start: "10:00", time_end: "15:00"
- "ab 09:00 Uhr" → time_start: "09:00"

DATUM:
- Das aktuelle Jahr ist 2026
- "25.01" oder "25.01." → 2026-01-25
- "14.02.25" ist ein Tippfehler, bedeutet 2026-02-14
- "01.02." → 2026-02-01

EVENT TYPES:
- "sucht Turnier" oder "sucht Hallenturnier" = tournament (Team sucht Turnier)
- "lädt ein" oder "veranstaltet Turnier" = tournament (Team veranstaltet)
- "sucht Testspiel" oder "sucht Spielmöglichkeit" = friendly_match
- "Leistungsvergleich" = friendly_match (auch als Serie mit mehreren Terminen!)

EMOJI-FORMATIERTE NACHRICHTEN:
- 📍 Ort: = location
- 🕔 oder 🕘 Uhrzeit: = time_start, time_end
- 📅 Termine: = Liste von Daten (erstelle separate Events!)
- 📌 Mi., 21.01.2026 = ein Termin → ein Event
- Der Kontaktname steht oft ganz am Ende: "Vereinsname / [Name]" → contact_name

BEISPIEL mit mehreren Terminen:
Nachricht enthält "📌 Mi., 21.01.2026" und "📌 Mi., 28.01.2026"
→ Erstelle 2 Events mit unterschiedlichen Daten aber gleicher Location/Zeit/Kontakt

Wenn keine gültigen Events gefunden werden, antworte mit: {"events": []}
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
        
        # Use npx to run the Gemini CLI with structured JSON output
        # --output-format json returns {"response": "...", "stats": {...}, "error": {...}}
        result = subprocess.run(
            [
                "npx", "-y", "@google/gemini-cli",
                "--yolo",
                "-m", "gemini-3-pro-preview",
                "--output-format", "json",
                "-p", full_prompt
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for images
            cwd=Path(image_paths[0]).parent if image_paths else None
        )
        
        if result.returncode == 0:
            # Parse the structured JSON response
            try:
                response_data = json.loads(result.stdout)
                
                # Check for errors in response
                if response_data.get("error"):
                    error = response_data["error"]
                    print(f"  Gemini API error: {error.get('type')}: {error.get('message')}")
                    return None
                
                # Return the response text
                return response_data.get("response", "")
                
            except json.JSONDecodeError:
                # Fallback to raw output if not valid JSON
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
                skill_level=event_data.get("skill_level"),
                age_group=event_data.get("age_group"),
                organizer=event_data.get("organizer"),
                contact_phone=event_data.get("contact_phone"),
                contact_name=event_data.get("contact_name"),
                status=event_data.get("status", "open"),
                entry_fee=event_data.get("entry_fee"),
                raw_text=text[:500] if text else "",
                summary=event_data.get("summary", ""),
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
