"""
Summary generator for events.
Creates German-language summaries formatted for WhatsApp.
"""

from datetime import date
from typing import Literal

from .extractor import Event
from .filter import filter_events, FilterCriteria, sort_events


# German day names
DAYS_DE = {
    0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
    4: "Freitag", 5: "Samstag", 6: "Sonntag"
}

# German month names
MONTHS_DE = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April",
    5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
    9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
}


def format_date_german(d: date | None) -> str:
    """Format date in German style."""
    if not d:
        return "Datum unbekannt"
    
    day_name = DAYS_DE[d.weekday()]
    return f"{day_name}, {d.day}. {MONTHS_DE[d.month]} {d.year}"


def format_time_range(start: str | None, end: str | None) -> str:
    """Format time range."""
    if not start:
        return "Zeit unbekannt"
    if end:
        return f"{start} - {end} Uhr"
    return f"ab {start} Uhr"


def format_event_short(event: Event) -> str:
    """Format event as a short one-liner."""
    emoji = "🏆" if event.event_type == "tournament" else "⚽"
    
    date_str = ""
    if event.date:
        date_str = f"{event.date.day}.{event.date.month}."
    
    parts = [emoji, date_str, event.organizer or "Unbekannt"]
    # Removed level_str per user request
    if event.status == "full":
        parts.append("❌ VOLL")
    
    return " ".join(filter(None, parts))


def format_event_full(event: Event) -> str:
    """Format event with full details."""
    lines = []
    
    # Header with emoji
    if event.event_type == "tournament":
        lines.append("🏆 *TURNIER*")
    else:
        lines.append("⚽ *TESTSPIEL*")
    
    # Status warning
    if event.status == "full":
        lines.append("❌ *AUSGEBUCHT*")
    
    # Date and time
    lines.append(f"📅 {format_date_german(event.date)}")
    lines.append(f"🕐 {format_time_range(event.time_start, event.time_end)}")
    
    # Location
    if event.location:
        lines.append(f"📍 {event.location}")
    
    # Details
    details = []
    details = []
    # Removed skill_level and age_group per user request
    if details:
        lines.append(f"ℹ️ {' | '.join(details)}")
    
    # Organizer
    if event.organizer:
        lines.append(f"🏟️ {event.organizer}")
    
    # Contact
    if event.contact_name or event.contact_phone:
        contact = event.contact_name or ""
        if event.contact_phone:
            contact = f"{contact} ({event.contact_phone})".strip()
        lines.append(f"📞 {contact}")
    
    # Extras
    extras = []
    # Removed catering per user request
    if event.entry_fee:
        extras.append(f"💰 {event.entry_fee}€")
    if extras:
        lines.append(" | ".join(extras))
    
    return "\n".join(lines)


def format_event_compact(event: Event) -> str:
    """Format event in compact multi-line format."""
    lines = []
    
    # Type emoji (only for tournaments) and date
    # emoji = "🏆 " if event.event_type == "tournament" else ""
    date_str = format_date_german(event.date) if event.date else "Datum TBD"
    lines.append(f"*{date_str}*")
    
    # Organizer and location
    org_loc = []
    if event.organizer:
        org_loc.append(f"*{event.organizer}*")
    if event.location:
        org_loc.append(event.location)
    if org_loc:
        lines.append("- " + " - ".join(org_loc))
    

    
    # Level and age
    info = []
    # Removed skill_level and age_group per user request
    if event.time_start:
        info.append(format_time_range(event.time_start, event.time_end))
    if info:
        lines.append("- " + " | ".join(info))
    
    # Contact details
    if event.contact_name or event.contact_phone:
        contact_parts = []
        if event.contact_name:
            contact_parts.append(event.contact_name)
        if event.contact_phone:
            contact_parts.append(f"``` {event.contact_phone} ```")
    # Contact details
    if event.contact_name or event.contact_phone:
        contact_parts = []
        if event.contact_name:
            contact_parts.append(event.contact_name)
        if event.contact_phone:
            contact_parts.append(f"``` {event.contact_phone} ```")
        lines.append("- " + " | ".join(contact_parts))
    
    # Status
    if event.status == "full":
        lines.append("- AUSGEBUCHT")
    
    return "\n".join(lines)


def generate_summary(
    events: list[Event],
    format_style: Literal["short", "compact", "full"] = "compact",
    title: str | None = None,
    include_header: bool = False
) -> str:
    """
    Generate a summary of events.
    
    Args:
        events: List of events to summarize
        format_style: How to format each event
        title: Optional title for the summary
        include_header: Whether to include header with count
        
    Returns:
        Formatted summary string
    """
    if not events:
        return "📭 Keine Events gefunden."
    
    lines = []
    
    # Header
    if include_header:
        if title:
            lines.append(f"*{title}*")
        
        # Count by type
        tournaments = sum(1 for e in events if e.event_type == "tournament")
        matches = sum(1 for e in events if e.event_type == "friendly_match")
        
        count_parts = []
        if tournaments:
            count_parts.append(f"🏆 {tournaments} Turnier{'e' if tournaments > 1 else ''}")
        if matches:
            count_parts.append(f"⚽ {matches} Testspiel{'e' if matches > 1 else ''}")
        
        if count_parts:
            lines.append(" | ".join(count_parts))
        
        lines.append("")  # Empty line
    
    # Sort by date
    sorted_events = sort_events(events, by="date")
    
    # Format each event
    for event in sorted_events:
        if format_style == "short":
            lines.append(format_event_short(event))
        elif format_style == "compact":
            lines.append(format_event_compact(event))
            lines.append("")  # Spacing between events
        else:  # full
            lines.append(format_event_full(event))
            lines.append("")
            lines.append("─" * 30)
            lines.append("")
    
    return "\n".join(lines).strip()


def generate_weekly_digest(events: list[Event]) -> str:
    """Generate a weekly digest of upcoming events."""
    from datetime import timedelta
    
    today = date.today()
    next_week = today + timedelta(days=7)
    
    # Filter for next 7 days, open only
    criteria = FilterCriteria(
        date_from=today,
        date_to=next_week,
        only_open=True
    )
    upcoming = filter_events(events, criteria)
    
    title = f"📅 Wochenübersicht ({today.day}.{today.month}. - {next_week.day}.{next_week.month}.)"
    
    return generate_summary(upcoming, format_style="compact", title=title)


def generate_daily_digest(events: list[Event], for_date: date | None = None) -> str:
    """Generate a daily digest for a specific date."""
    target_date = for_date or date.today()
    
    # Filter for specific date
    criteria = FilterCriteria(
        date_from=target_date,
        date_to=target_date
    )
    day_events = filter_events(events, criteria)
    
    title = f"📅 Events am {format_date_german(target_date)}"
    
    return generate_summary(day_events, format_style="full", title=title)


if __name__ == "__main__":
    from datetime import date
    from .extractor import Event
    
    # Test with sample events
    events = [
        Event(
            id="1", event_type="tournament", date=date(2026, 1, 25),
            time_start="09:00", time_end="14:00",
            location="Sporthalle am Neuendorfer Sand, Brandenburg",
            skill_level=5, age_group="JG2015",
            organizer="FC Borussia Brandenburg",
            contact_phone="+49 173 2843016", contact_name="Kay",
            status="open", catering=True
        ),
        Event(
            id="2", event_type="friendly_match", date=date(2026, 1, 22),
            time_start="17:00", time_end=None,
            location="Wilmersdorf",
            skill_level=3, age_group="D-Jugend",
            organizer="BSV 1892 D2",
            contact_phone="+49 176 32223598", contact_name="Nico",
            status="open"
        ),
        Event(
            id="3", event_type="tournament", date=date(2026, 2, 1),
            time_start="09:00", time_end="13:30",
            location="Turnhalle Paul-Simmel-Grundschule, Felixstr. 26, 12099 Berlin",
            skill_level=2, age_group="D-Jugend",
            organizer="S.D Croatia Berlin",
            contact_phone="+49 176 70720831", contact_name="Tomislav",
            status="full", entry_fee=30
        ),
    ]
    
    print("=== SHORT FORMAT ===")
    print(generate_summary(events, format_style="short"))
    print("\n=== COMPACT FORMAT ===")
    print(generate_summary(events, format_style="compact", title="Kommende Events"))
    print("\n=== FULL FORMAT ===")
    print(generate_summary(events[:1], format_style="full"))
