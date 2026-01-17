"""
Filter module for events.
Filter by date, skill level, age group, location, and event type.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from .extractor import Event


@dataclass
class FilterCriteria:
    """Criteria for filtering events."""
    # Date range
    date_from: date | None = None
    date_to: date | None = None
    
    # Skill level range (1-10)
    min_level: int | None = None
    max_level: int | None = None
    
    # Age groups to include (empty = all)
    age_groups: list[str] | None = None
    
    # Event types to include
    event_types: list[str] | None = None
    
    # Only show open events
    only_open: bool = True
    
    # Location filter (substring match)
    location_contains: str | None = None
    
    # Organizer filter (substring match)
    organizer_contains: str | None = None


def filter_by_date(event: Event, date_from: date | None, date_to: date | None) -> bool:
    """Filter event by date range."""
    if event.date is None:
        # Exclude events without dates when filtering by date range
        return date_from is None and date_to is None
    
    if date_from and event.date < date_from:
        return False
    if date_to and event.date > date_to:
        return False
    return True


def filter_by_level(event: Event, min_level: int | None, max_level: int | None) -> bool:
    """Filter event by skill level."""
    if event.skill_level is None:
        return True  # Include events without level
    
    if min_level and event.skill_level < min_level:
        return False
    if max_level and event.skill_level > max_level:
        return False
    return True


def filter_by_age_group(event: Event, age_groups: list[str] | None) -> bool:
    """Filter event by age group."""
    if not age_groups:
        return True  # No filter
    if event.age_group is None:
        return True  # Include events without age group
    
    # Normalize comparison
    event_age = event.age_group.lower().replace('-', '').replace(' ', '')
    for ag in age_groups:
        ag_normalized = ag.lower().replace('-', '').replace(' ', '')
        if ag_normalized in event_age or event_age in ag_normalized:
            return True
    return False


def filter_by_type(event: Event, event_types: list[str] | None) -> bool:
    """Filter event by type."""
    if not event_types:
        return True
    return event.event_type in event_types


def filter_by_status(event: Event, only_open: bool) -> bool:
    """Filter event by open/full status."""
    if not only_open:
        return True
    return event.status == "open"


def filter_by_location(event: Event, location_contains: str | None) -> bool:
    """Filter event by location (substring match)."""
    if not location_contains:
        return True
    if event.location is None:
        return False
    return location_contains.lower() in event.location.lower()


def filter_by_organizer(event: Event, organizer_contains: str | None) -> bool:
    """Filter event by organizer (substring match)."""
    if not organizer_contains:
        return True
    if event.organizer is None:
        return False
    return organizer_contains.lower() in event.organizer.lower()


def filter_events(events: list[Event], criteria: FilterCriteria) -> list[Event]:
    """
    Filter a list of events based on criteria.
    
    Args:
        events: List of events to filter
        criteria: Filter criteria
        
    Returns:
        Filtered list of events
    """
    result = []
    
    for event in events:
        # Apply all filters
        if not filter_by_date(event, criteria.date_from, criteria.date_to):
            continue
        if not filter_by_level(event, criteria.min_level, criteria.max_level):
            continue
        if not filter_by_age_group(event, criteria.age_groups):
            continue
        if not filter_by_type(event, criteria.event_types):
            continue
        if not filter_by_status(event, criteria.only_open):
            continue
        if not filter_by_location(event, criteria.location_contains):
            continue
        if not filter_by_organizer(event, criteria.organizer_contains):
            continue
        
        result.append(event)
    
    return result


def sort_events(events: list[Event], by: str = "date", reverse: bool = False) -> list[Event]:
    """
    Sort events by specified field.
    
    Args:
        events: List of events
        by: Field to sort by ("date", "level", "type")
        reverse: Sort in descending order
        
    Returns:
        Sorted list of events
    """
    if by == "date":
        # Put None dates at the end
        key = lambda e: (e.date is None, e.date or date.max)
    elif by == "level":
        key = lambda e: (e.skill_level is None, e.skill_level or 0)
    elif by == "type":
        key = lambda e: e.event_type
    else:
        key = lambda e: e.id
    
    return sorted(events, key=key, reverse=reverse)


# Preset filters
def upcoming_week(events: list[Event]) -> list[Event]:
    """Get events in the upcoming week."""
    today = date.today()
    next_week = today + timedelta(days=7)
    criteria = FilterCriteria(date_from=today, date_to=next_week)
    return filter_events(events, criteria)


def upcoming_month(events: list[Event]) -> list[Event]:
    """Get events in the upcoming month."""
    today = date.today()
    next_month = today + timedelta(days=30)
    criteria = FilterCriteria(date_from=today, date_to=next_month)
    return filter_events(events, criteria)


def tournaments_only(events: list[Event]) -> list[Event]:
    """Get only tournaments."""
    criteria = FilterCriteria(event_types=["tournament"])
    return filter_events(events, criteria)


def matches_only(events: list[Event]) -> list[Event]:
    """Get only friendly matches."""
    criteria = FilterCriteria(event_types=["friendly_match"])
    return filter_events(events, criteria)


def by_level_range(events: list[Event], min_level: int, max_level: int) -> list[Event]:
    """Filter by skill level range."""
    criteria = FilterCriteria(min_level=min_level, max_level=max_level)
    return filter_events(events, criteria)


if __name__ == "__main__":
    from datetime import date
    from .extractor import Event
    
    # Test with sample events
    events = [
        Event(
            id="1", event_type="tournament", date=date(2026, 1, 25),
            time_start="09:00", time_end="14:00", location="Berlin",
            skill_level=5, age_group="D-Jugend", organizer="FC Test",
            contact_phone="+49123", contact_name="Max", status="open"
        ),
        Event(
            id="2", event_type="friendly_match", date=date(2026, 1, 22),
            time_start="17:00", time_end=None, location="Wilmersdorf",
            skill_level=3, age_group="D-Jugend", organizer="BSV 1892",
            contact_phone="+49456", contact_name="Nico", status="open"
        ),
        Event(
            id="3", event_type="tournament", date=date(2026, 2, 1),
            time_start="09:00", time_end="13:30", location="Berlin",
            skill_level=2, age_group="D-Jugend", organizer="Croatia Berlin",
            contact_phone="+49789", contact_name="Tomislav", status="full"
        ),
    ]
    
    print("All events:", len(events))
    print("Open only:", len(filter_events(events, FilterCriteria(only_open=True))))
    print("Level 3-5:", len(by_level_range(events, 3, 5)))
    print("Tournaments:", len(tournaments_only(events)))
