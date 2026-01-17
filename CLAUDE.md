# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WhatsApp Football Event Analyzer - extracts football/soccer events (tournaments and friendly matches) from WhatsApp group messages, analyzes them with AI, and syncs to Google Calendar.

Target use case: German youth football coaches sharing event announcements in WhatsApp groups. Messages are in German with dates, times, locations, skill levels, and age groups.

## Commands

```bash
# Quick run (typical workflow)
python run.py              # Sync + AI analyze + send to "Termine" group + calendar sync
python run.py --dry-run    # Preview without sending/syncing
python run.py --full       # Force full resync (clears events)
python run.py --list       # Just list current events
python run.py --no-calendar # Skip Google Calendar sync

# CLI commands (via module)
python -m src.main sync --group "Jahrgang 2014er Trainer"  # Sync from WhatsApp group
python -m src.main list --format compact                    # List events
python -m src.main notify --filter week --dry-run           # Preview weekly summary
python -m src.main status                                   # Check system status
python -m src.main ocr <image>                              # Test OCR on an image
python -m src.main ai-analyze                               # Run AI analysis on saved content
```

## Architecture

### Data Flow
1. **WhatsApp sync** (`whatsapp.py`) - Uses `wacli` CLI tool to fetch messages from configured group
2. **Media download** - Downloads images (event flyers) from messages
3. **OCR** (`ocr.py`) - Extracts text from images using PaddleOCR or Tesseract
4. **AI extraction** (`ai_extractor.py`) - Uses Gemini CLI (`npx @google/gemini-cli`) to parse German event announcements into structured data
5. **Event storage** (`extractor.py`) - `Event` dataclass and JSON database in `data/events.json`
6. **Notification** - Sends formatted summary back to "Termine" WhatsApp group
7. **Calendar sync** (`calendar_sync.py`) - Syncs events to Google Calendar "Spiele"

### Key Components
- `Event` dataclass (`extractor.py:17-54`) - Core data model with fields for date, time, location, skill_level, age_group, organizer, etc.
- `EventDatabase` (`extractor.py:429-473`) - JSON-based persistence with deduplication by event ID
- `WacliClient` (`whatsapp.py:92-333`) - Python wrapper for wacli CLI commands
- Regex extraction (`extractor.py`) - Pattern-based fallback extraction for German date/time/location formats

### External Dependencies
- **wacli** - WhatsApp CLI tool (https://github.com/steipete/wacli) - must be authenticated via `wacli auth`
- **Gemini CLI** - Google AI via `npx @google/gemini-cli` with `--yolo` flag and user's subscription
- **Google Calendar API** - OAuth2 credentials required in `client_secret_*.json`

## Configuration

`config.yaml` contains:
- WhatsApp group JIDs for source and notification targets
- Filter defaults (days_back, skill levels, event types)
- OCR language settings
- Storage paths

## Data Storage

All data goes in `data/` (gitignored):
- `events.json` - Event database
- `last_sync.txt` - Timestamp of last WhatsApp sync
- `media/` - Downloaded images
- `calendar_token.json` - Google OAuth token
