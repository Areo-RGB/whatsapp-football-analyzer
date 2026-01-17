"""
WhatsApp Football Event Analyzer - Main CLI
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from .parser import parse_export_file, parse_export_text, Message
from .ocr import extract_text_from_image, extract_text_from_images, check_tesseract, check_ocr, HAS_OCR
from .extractor import (
    extract_events_from_messages, extract_event_from_text,
    EventDatabase, Event
)
from .filter import filter_events, FilterCriteria, sort_events
from .summarizer import (
    generate_summary, generate_weekly_digest, generate_daily_digest,
    format_event_full
)
from .whatsapp import WacliClient, check_wacli, find_group_by_name, get_sender_phones
from .ai_extractor import extract_events_with_ai, analyze_messages_with_ai
from .calendar import sync_events_to_calendar, list_calendars, CALENDAR_NAME

console = Console()


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def get_db(config: dict) -> EventDatabase:
    """Get event database from config."""
    db_path = config.get('paths', {}).get('events_db', 'data/events.json')
    return EventDatabase(db_path)


@click.group()
@click.option('--config', '-c', default='config.yaml', help='Config file path')
@click.pass_context
def cli(ctx, config):
    """WhatsApp Football Event Analyzer
    
    Extract, filter, and summarize football events from WhatsApp messages.
    """
    ctx.ensure_object(dict)
    ctx.obj['config'] = load_config(config)
    ctx.obj['config_path'] = config


@cli.command()
@click.argument('file', type=click.Path(exists=True))
@click.option('--images', '-i', multiple=True, help='Image files to OCR')
@click.option('--days', '-d', type=int, help='Only import messages from last N days (default: 30)')
@click.pass_context
def import_chat(ctx, file, images, days):
    """Import events from a WhatsApp chat export file.
    
    FILE: Path to the exported chat .txt file
    """
    config = ctx.obj['config']
    db = get_db(config)
    
    # Get days filter from option or config
    days_back = days if days is not None else config.get('filters', {}).get('days_back', 30)
    
    console.print(f"[bold blue]Importing from:[/] {file}")
    
    # Parse text messages
    all_messages = parse_export_file(file)
    console.print(f"  Found [green]{len(all_messages)}[/] total messages")
    
    # Filter by date (last N days)
    if days_back > 0:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        messages = [m for m in all_messages if m.timestamp >= cutoff_date]
        console.print(f"  Messages in last {days_back} days: [green]{len(messages)}[/]")
    else:
        messages = all_messages
    
    # Extract events from text
    events = extract_events_from_messages(messages)
    console.print(f"  Detected [green]{len(events)}[/] events")
    
    # Process images with OCR
    if images:
        if not HAS_OCR:
            console.print("[yellow]Warning: OCR dependencies not installed (pytesseract, Pillow)[/]")
        elif not check_tesseract():
            console.print("[yellow]Warning: Tesseract not installed[/]")
        else:
            console.print(f"\n[bold blue]Processing {len(images)} images...[/]")
            for img_path in images:
                try:
                    text = extract_text_from_image(img_path)
                    event = extract_event_from_text(text)
                    if event:
                        events.append(event)
                        console.print(f"  [green]✓[/] {img_path}: Found event")
                    else:
                        console.print(f"  [yellow]-[/] {img_path}: No event detected")
                except Exception as e:
                    console.print(f"  [red]✗[/] {img_path}: {e}")
    
    # Save to database
    added = 0
    for event in events:
        if db.add(event):
            added += 1
    db.save()
    
    console.print(f"\n[bold green]Added {added} new events[/] (total: {len(db)})")


def get_last_sync(config: dict) -> datetime | None:
    """Get the timestamp of last sync."""
    sync_file = Path(config.get('paths', {}).get('last_sync', 'data/last_sync.txt'))
    if sync_file.exists():
        try:
            ts_str = sync_file.read_text().strip()
            return datetime.fromisoformat(ts_str)
        except:
            pass
    return None


def save_last_sync(config: dict, timestamp: datetime):
    """Save the timestamp of this sync."""
    sync_file = Path(config.get('paths', {}).get('last_sync', 'data/last_sync.txt'))
    sync_file.parent.mkdir(parents=True, exist_ok=True)
    sync_file.write_text(timestamp.isoformat())


@cli.command()
@click.option('--group', '-g', help='Group name to sync from')
@click.option('--limit', '-l', default=500, help='Message limit')
@click.option('--full', is_flag=True, help='Force full sync (ignore last sync time)')
@click.option('--ai', is_flag=True, default=True, help='Use AI analysis (default: True)')
@click.option('--regex', is_flag=True, help='Also use regex extraction (disabled by default)')
@click.pass_context
def sync(ctx, group, limit, full, ai, regex):
    """Sync events from WhatsApp using wacli.
    
    First run: syncs last N days (config: days_back).
    Subsequent runs: only syncs since last sync.
    Use --full to force a complete re-sync.
    Uses AI by default for better extraction. Use --regex to also use regex.
    """
    config = ctx.obj['config']
    db = get_db(config)
    
    if not check_wacli():
        console.print("[red]Error: wacli not installed[/]")
        console.print("Install from: https://github.com/steipete/wacli")
        return
    
    try:
        client = WacliClient()
        
        if not client.is_authenticated():
            console.print("[yellow]Not authenticated. Run 'wacli auth' first.[/]")
            return
        
        console.print("[bold blue]Syncing from WhatsApp...[/]")
        
        # Find the group
        target_group = None
        if group:
            target_group = find_group_by_name(client, group)
            if not target_group:
                console.print(f"[red]Group not found: {group}[/]")
                console.print("\nAvailable groups:")
                for g in client.list_groups()[:10]:
                    console.print(f"  - {g.name}")
                return
            console.print(f"  Found group: [green]{target_group.name}[/]")
        else:
            # Use configured group
            group_jid = config.get('whatsapp', {}).get('source_group')
            if group_jid:
                groups = client.list_groups()
                target_group = next((g for g in groups if g.jid == group_jid), None)
        
        if not target_group:
            console.print("[yellow]No group specified. Use --group or set in config.yaml[/]")
            return
        
        # Get messages
        console.print(f"  Fetching messages...")
        wacli_messages = client.get_messages(target_group.jid, limit=limit)
        console.print(f"  Retrieved [green]{len(wacli_messages)}[/] messages")
        
        # Determine cutoff date
        last_sync = get_last_sync(config)
        days_back = config.get('filters', {}).get('days_back', 30)
        
        if full or last_sync is None:
            # First run or forced: use days_back
            cutoff_date = datetime.now() - timedelta(days=days_back) if days_back > 0 else None
            console.print(f"  [yellow]First sync or --full: checking last {days_back} days[/]")
        else:
            # Subsequent run: only since last sync
            cutoff_date = last_sync
            console.print(f"  Checking since last sync: [cyan]{last_sync.strftime('%Y-%m-%d %H:%M')}[/]")
        
        sync_time = datetime.now()
        
        # Convert to our Message format, filtering by date
        messages = []
        for wm in wacli_messages:
            try:
                ts = datetime.fromisoformat(wm.timestamp.replace('Z', '+00:00'))
                # Make timezone-naive for comparison
                if ts.tzinfo:
                    ts = ts.replace(tzinfo=None)
            except:
                ts = datetime.now()
            
            # Filter by date
            if cutoff_date and ts < cutoff_date:
                continue
            
            messages.append(Message(
                timestamp=ts,
                sender=wm.sender,
                content=wm.text,
                has_media=wm.has_media,
                msg_id=wm.id
            ))
        
        console.print(f"  New messages: [green]{len(messages)}[/]")
        
        # Extract events using regex if enabled
        added = 0
        if regex:
            events = extract_events_from_messages(messages)
            console.print(f"  Regex detected [green]{len(events)}[/] events")
            
            for event in events:
                if db.add(event):
                    added += 1
            db.save()
        
        # Download images from messages with media
        image_paths = []
        media_dir = Path(config.get('paths', {}).get('media_dir', 'data/media'))
        media_dir.mkdir(parents=True, exist_ok=True)
        
        media_messages = [wm for wm in wacli_messages if wm.has_media and wm.media_type in ('image', 'image/jpeg', 'image/png')]
        if media_messages:
            console.print(f"  Downloading [cyan]{len(media_messages)}[/] images...")
            for wm in media_messages:
                try:
                    # Check if already downloaded
                    existing = list(media_dir.glob(f"*{wm.id}*"))
                    if existing:
                        image_paths.append(str(existing[0]))
                    else:
                        path = client.download_media(target_group.jid, wm.id, media_dir)
                        if path:
                            image_paths.append(path)
                            console.print(f"    ✓ Downloaded: {Path(path).name}")
                except Exception as e:
                    console.print(f"    [red]✗ Failed: {wm.id} - {e}[/]")
        
        console.print(f"  [green]{len(image_paths)}[/] images available")
        
        # Look up actual sender phone numbers from whatsmeow database (needed for both OCR and text)
        message_ids = [wm.id for wm in wacli_messages]
        sender_phones = get_sender_phones(message_ids)
        
        # Extract text from images using OCR (PaddleOCR)
        # Include sender phone for each image
        ocr_parts = []
        if image_paths and media_messages:
            console.print(f"\n[bold blue]Running OCR on {len(image_paths)} images...[/]")
            
            # Create mapping from image path to message ID
            path_to_msg = {}
            for wm in media_messages:
                existing = list(media_dir.glob(f"*{wm.id}*"))
                if existing:
                    path_to_msg[str(existing[0])] = wm.id
            
            for img_path in image_paths:
                try:
                    from .ocr import extract_text_from_image
                    ocr_text = extract_text_from_image(img_path)
                    if ocr_text and ocr_text.strip():
                        # Get sender phone for this image
                        msg_id = path_to_msg.get(img_path)
                        phone = sender_phones.get(msg_id) if msg_id else None
                        
                        if phone:
                            formatted_phone = f"+{phone}" if not phone.startswith('+') else phone
                            ocr_parts.append(f"[Von: {formatted_phone}]\n{ocr_text}")
                        else:
                            ocr_parts.append(ocr_text)
                except Exception as e:
                    console.print(f"    [red]OCR failed for {img_path}: {e}[/]")
            
            total_chars = sum(len(p) for p in ocr_parts)
            console.print(f"  Extracted [green]{total_chars}[/] chars from images")
        
        # Run AI analysis (default behavior) - TEXT ONLY, no images
        if ai and (messages or ocr_parts):
            console.print("\n[bold blue]Running AI analysis (text only)...[/]")
            
            # Combine message content + OCR text for AI analysis
            # Include sender phone where available using msg_id
            content_parts = []
            for msg in messages:
                if msg.content:
                    # Get phone number using msg_id directly
                    phone = sender_phones.get(msg.msg_id) if msg.msg_id else None
                    
                    # Format with phone if available
                    if phone:
                        # Format as +49 XXX format for AI
                        formatted_phone = f"+{phone}" if not phone.startswith('+') else phone
                        content_parts.append(f"[Von: {formatted_phone}]\n{msg.content}")
                    else:
                        content_parts.append(f"{msg.sender}: {msg.content}")
            
            combined_content = "\n\n".join(content_parts)
            
            # Add OCR text with sender phones already included
            if ocr_parts:
                combined_content += "\n\n--- OCR FROM IMAGES ---\n" + "\n\n".join(ocr_parts)
            
            console.print(f"  Analyzing {len(combined_content)} chars (text only, faster)...")
            ai_events = analyze_messages_with_ai(combined_content)  # No images, just text
            
            ai_added = 0
            for event in ai_events:
                if db.add(event):
                    ai_added += 1
                    console.print(f"  ✓ {event.event_type}: {event.date} - {event.organizer or 'Unknown'}")
            
            db.save()
            console.print(f"\n[bold green]AI added {ai_added} new events[/] (total: {len(db)})")
            added += ai_added
        
        # Save sync timestamp
        save_last_sync(config, sync_time)
        
        if not ai:
            console.print(f"\n[bold green]Added {added} events[/] (total: {len(db)})")
        console.print(f"[dim]Next sync will check from: {sync_time.strftime('%Y-%m-%d %H:%M')}[/]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")


@cli.command('list')
@click.option('--from', 'date_from', help='Start date (YYYY-MM-DD, "today", or "-30days")')
@click.option('--to', 'date_to', help='End date (YYYY-MM-DD or "+7days")')
@click.option('--level', '-l', help='Skill level range (e.g., "3-6")')
@click.option('--type', '-t', 'event_type', type=click.Choice(['tournament', 'friendly_match', 'all']), default='all')
@click.option('--age', '-a', help='Age group filter')
@click.option('--open-only/--include-full', default=True, help='Only show open events')
@click.option('--format', '-f', type=click.Choice(['table', 'compact', 'full', 'short']), default='compact')
@click.pass_context
def list_events(ctx, date_from, date_to, level, event_type, age, open_only, format):
    """List events with optional filters.
    
    Examples:
        list --from today --to +7days
        list --level 3-6 --type tournament
        list --age D-Jugend --open-only
    """
    config = ctx.obj['config']
    db = get_db(config)
    
    if len(db) == 0:
        console.print("[yellow]No events in database. Run 'import' or 'sync' first.[/]")
        return
    
    # Parse date filters
    today = date.today()
    
    # Apply default days_back from config if no --from specified
    days_back = config.get('filters', {}).get('days_back', 30)
    
    if date_from == 'today':
        from_date = today
    elif date_from and date_from.startswith('-'):
        # Handle "-30days" format
        days = int(date_from[1:].replace('days', '').replace('d', ''))
        from_date = today - timedelta(days=days)
    elif date_from:
        try:
            from_date = date.fromisoformat(date_from)
        except:
            from_date = None
    elif days_back > 0:
        # Default: only show events from last N days
        from_date = today - timedelta(days=days_back)
    else:
        from_date = None
    
    if date_to:
        if date_to.startswith('+'):
            days = int(date_to[1:].replace('days', '').replace('d', ''))
            to_date = today + timedelta(days=days)
        else:
            try:
                to_date = date.fromisoformat(date_to)
            except:
                to_date = None
    else:
        to_date = None
    
    # Parse level range
    min_level, max_level = None, None
    if level:
        parts = level.split('-')
        min_level = int(parts[0])
        max_level = int(parts[1]) if len(parts) > 1 else min_level
    
    # Build filter criteria
    criteria = FilterCriteria(
        date_from=from_date,
        date_to=to_date,
        min_level=min_level,
        max_level=max_level,
        event_types=[event_type] if event_type != 'all' else None,
        age_groups=[age] if age else None,
        only_open=open_only
    )
    
    # Filter and sort
    events = filter_events(db.all(), criteria)
    events = sort_events(events, by='date')
    
    if not events:
        console.print("[yellow]No events match the filters.[/]")
        return
    
    console.print(f"\n[bold]Found {len(events)} events[/]\n")
    
    # Output format
    if format == 'table':
        table = Table(show_header=True)
        table.add_column("Date", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Level", justify="center")
        table.add_column("Age", style="yellow")
        table.add_column("Organizer")
        table.add_column("Location")
        table.add_column("Status")
        
        for e in events:
            date_str = e.date.strftime("%d.%m.%Y") if e.date else "TBD"
            type_str = "🏆" if e.event_type == "tournament" else "⚽"
            level_str = str(e.skill_level) if e.skill_level else "-"
            status = "❌ VOLL" if e.status == "full" else "✓"
            
            table.add_row(
                date_str,
                type_str,
                level_str,
                e.age_group or "-",
                e.organizer or "-",
                (e.location[:30] + "..." if e.location and len(e.location) > 30 else e.location) or "-",
                status
            )
        
        console.print(table)
    else:
        summary = generate_summary(events, format_style=format)
        console.print(summary)


@cli.command()
@click.option('--to', '-t', help='Phone number, group JID, or group name to notify')
@click.option('--filter', '-f', 'filter_preset', 
              type=click.Choice(['week', 'month', 'today', 'all']), 
              default='week',
              help='Event filter preset')
@click.option('--level', '-l', help='Skill level range (e.g., "3-6")')
@click.option('--dry-run', is_flag=True, help='Preview message without sending')
@click.pass_context
def notify(ctx, to, filter_preset, level, dry_run):
    """Send event summary to a WhatsApp chat.
    
    Examples:
        notify --to +491234567890 --filter week
        notify --to 123456789@g.us --filter month --level 3-6
        notify --to "Termine" --filter week
        notify --filter week  (uses config default: "Termine")
    """
    config = ctx.obj['config']
    db = get_db(config)
    
    # Use config default if --to not specified
    if not to:
        to = config.get('whatsapp', {}).get('notify_group_name', '') or \
             config.get('whatsapp', {}).get('notify_to', '')
    
    if not to:
        console.print("[red]Error: No recipient specified. Use --to or set in config.yaml[/]")
        return
    
    if len(db) == 0:
        console.print("[yellow]No events to notify about.[/]")
        return
    
    # Apply filter preset
    today = date.today()
    criteria = FilterCriteria(only_open=True)
    
    if filter_preset == 'week':
        criteria.date_from = today
        criteria.date_to = today + timedelta(days=7)
        title = "📅 Events diese Woche"
    elif filter_preset == 'month':
        criteria.date_from = today
        criteria.date_to = today + timedelta(days=30)
        title = "📅 Events diesen Monat"
    elif filter_preset == 'today':
        criteria.date_from = today
        criteria.date_to = today
        title = "📅 Events heute"
    else:
        title = "📅 Alle Events"
    
    # Apply level filter
    if level:
        parts = level.split('-')
        criteria.min_level = int(parts[0])
        criteria.max_level = int(parts[1]) if len(parts) > 1 else criteria.min_level
    
    events = filter_events(db.all(), criteria)
    events = sort_events(events, by='date')
    
    if not events:
        console.print("[yellow]No events match the filters.[/]")
        return
    
    # Generate message
    message = generate_summary(events, format_style='compact', title=title)
    
    console.print("\n[bold]Message Preview:[/]")
    console.print(message)
    console.print()
    
    if dry_run:
        console.print("[yellow]Dry run - message not sent[/]")
        return
    
    if not check_wacli():
        console.print("[red]Error: wacli not installed[/]")
        return
    
    try:
        client = WacliClient()
        
        if not client.is_authenticated():
            console.print("[yellow]Not authenticated. Run 'wacli auth' first.[/]")
            return
        
        # Resolve group name to JID if needed
        target_jid = to
        if '@' not in to and not to.startswith('+') and not to[0].isdigit():
            # Looks like a group name, try to find it
            console.print(f"[bold blue]Looking for group: {to}...[/]")
            group = find_group_by_name(client, to)
            if group:
                target_jid = group.jid
                console.print(f"  Found: [green]{group.name}[/] ({group.jid})")
            else:
                console.print(f"[red]Group not found: {to}[/]")
                console.print("\nAvailable groups:")
                for g in client.list_groups()[:10]:
                    console.print(f"  - {g.name}")
                return
        
        console.print(f"[bold blue]Sending to {target_jid}...[/]")
        
        if '@g.us' in target_jid:
            success = client.send_to_group(target_jid, message)
        else:
            success = client.send_message(target_jid, message)
        
        if success:
            console.print("[bold green]Message sent successfully![/]")
        else:
            console.print("[red]Failed to send message[/]")
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")


@cli.command()
@click.argument('image', type=click.Path(exists=True))
@click.pass_context
def ocr(ctx, image):
    """Extract text from an image using OCR.
    
    IMAGE: Path to the image file
    """
    if not HAS_OCR:
        console.print("[red]Error: OCR dependencies not installed[/]")
        console.print("Install with: pip install pytesseract Pillow")
        return
    
    if not check_tesseract():
        console.print("[red]Error: Tesseract not installed[/]")
        console.print("Install with: sudo apt install tesseract-ocr tesseract-ocr-deu")
        return
    
    console.print(f"[bold blue]Extracting text from:[/] {image}")
    
    try:
        text = extract_text_from_image(image, language='deu')
        
        console.print("\n[bold]Extracted text:[/]")
        console.print(text)
        
        # Try to extract event
        event = extract_event_from_text(text)
        if event:
            console.print("\n[bold green]Detected event:[/]")
            console.print(format_event_full(event))
        else:
            console.print("\n[yellow]No event detected in text[/]")
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")


@cli.command()
@click.pass_context
def status(ctx):
    """Show current status and statistics."""
    config = ctx.obj['config']
    db = get_db(config)
    
    console.print("[bold]WhatsApp Football Event Analyzer[/]\n")
    
    # Check dependencies
    table = Table(title="System Status", show_header=True)
    table.add_column("Component")
    table.add_column("Status")
    
    table.add_row("wacli", "[green]✓ Installed[/]" if check_wacli() else "[red]✗ Not installed[/]")
    table.add_row("Tesseract OCR", "[green]✓ Installed[/]" if (HAS_OCR and check_tesseract()) else "[yellow]✗ Not installed[/]")
    table.add_row("Config", f"[green]{ctx.obj['config_path']}[/]" if config else "[yellow]Not found[/]")
    
    console.print(table)
    console.print()
    
    # Event statistics
    events = db.all()
    if events:
        console.print(f"[bold]Events in Database:[/] {len(events)}")
        
        tournaments = sum(1 for e in events if e.event_type == 'tournament')
        matches = sum(1 for e in events if e.event_type == 'friendly_match')
        open_events = sum(1 for e in events if e.status == 'open')
        
        console.print(f"  🏆 Tournaments: {tournaments}")
        console.print(f"  ⚽ Friendly matches: {matches}")
        console.print(f"  ✓ Open events: {open_events}")
        
        # Upcoming
        today = date.today()
        upcoming = [e for e in events if e.date and e.date >= today and e.status == 'open']
        if upcoming:
            console.print(f"\n[bold]Upcoming Events:[/] {len(upcoming)}")
            for e in sorted(upcoming, key=lambda x: x.date)[:5]:
                console.print(f"  - {e.date}: {e.organizer or 'Unknown'} ({e.event_type})")
    else:
        console.print("[yellow]No events in database. Run 'import' or 'sync' to add events.[/]")


@cli.command('ai-analyze')
@click.option('--file', '-f', 'input_file', type=click.Path(exists=True), 
              help='Text file to analyze (default: data/all_content_last_month.txt)')
@click.option('--images', '-i', is_flag=True, help='Also analyze images with OCR + AI')
@click.pass_context
def ai_analyze(ctx, input_file, images):
    """Analyze messages using AI for better event extraction.
    
    Uses Z.AI API to extract events from noisy text and OCR content.
    """
    config = ctx.obj['config']
    db = get_db(config)
    
    console.print("[bold blue]AI-Powered Event Analysis[/]\n")
    
    # Determine input file
    if not input_file:
        input_file = "data/all_content_last_month.txt"
        if not Path(input_file).exists():
            input_file = "data/messages_last_month.txt"
    
    if not Path(input_file).exists():
        console.print(f"[red]File not found: {input_file}[/]")
        console.print("Run 'sync' first to get messages.")
        return
    
    # Read content
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    console.print(f"[bold]Analyzing:[/] {input_file}")
    console.print(f"  Content size: {len(content)} chars")
    
    # Analyze with AI
    console.print("\n[bold blue]Sending to AI for analysis...[/]")
    
    try:
        events = analyze_messages_with_ai(content)
        console.print(f"  [green]AI extracted {len(events)} events[/]")
        
        # Add events to database
        added = 0
        for event in events:
            if db.add(event):
                added += 1
                console.print(f"  ✓ {event.event_type}: {event.date} - {event.organizer or 'Unknown'}")
        
        db.save()
        console.print(f"\n[bold green]Added {added} new events[/] (total: {len(db)})")
        
    except Exception as e:
        console.print(f"[red]AI analysis error: {e}[/]")
        return
    
    # Also analyze images if requested
    if images:
        console.print("\n[bold blue]Analyzing images with OCR + AI...[/]")
        media_dir = Path("data/media")
        
        if not media_dir.exists():
            console.print("[yellow]No media directory found[/]")
            return
        
        for img in media_dir.glob("*.jfif"):
            console.print(f"\n  Processing: {img.name}")
            try:
                # OCR
                from .ocr import extract_text_from_image
                ocr_text = extract_text_from_image(img, language="deu")
                console.print(f"    OCR: {len(ocr_text)} chars")
                
                # AI extraction
                events = extract_events_with_ai(ocr_text)
                for event in events:
                    event.id = f"ai-ocr-{img.stem}"
                    if db.add(event):
                        console.print(f"    ✓ Found: {event.event_type} - {event.date}")
                        
            except Exception as e:
                console.print(f"    [red]Error: {e}[/]")
        
        db.save()
        console.print(f"\n[bold green]Total events: {len(db)}[/]")


def main():
    """Main entry point."""
    cli(obj={})


if __name__ == '__main__':
    main()
