"""Generate event card images from HTML templates."""

import os
import tempfile
from pathlib import Path
from datetime import date

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# HTML template for event card (double braces {{ }} escape for .format())
CARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: transparent;
            padding: 0;
        }}
        .card {{
            width: 400px;
            background: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }}
        .header {{
            background: linear-gradient(135deg, #1e3a5f 0%, #0d253f 100%);
            padding: 16px 20px;
        }}
        .organizer {{
            color: #fff;
            font-size: 22px;
            font-weight: 700;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}
        .event-type {{
            display: inline-block;
            background: rgba(255,255,255,0.2);
            color: #ffffff;
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 4px;
            margin-top: 6px;
            text-transform: uppercase;
        }}
        .event-type.friendly {{
            background: rgba(255,255,255,0.15);
            color: #ffffff;
        }}
        .content {{
            padding: 16px 20px;
        }}
        .row {{
            display: flex;
            align-items: flex-start;
            margin-bottom: 12px;
            color: #1a1a1a;
        }}
        .row:last-child {{
            margin-bottom: 0;
        }}
        .icon {{
            width: 28px;
            font-size: 18px;
            flex-shrink: 0;
        }}
        .text {{
            font-size: 15px;
            line-height: 1.4;
        }}
        .date-text {{
            font-weight: 600;
        }}
        .weekday {{
            color: #666666;
            font-weight: 400;
        }}
        .status-full {{
            background: #dc3545;
            color: white;
            font-size: 12px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 4px;
            display: inline-block;
            margin-top: 4px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <div class="organizer">{organizer}</div>
            <div class="event-type {event_type_class}">{event_type_label}</div>
        </div>
        <div class="content">
            <div class="row">
                <span class="icon">📅</span>
                <span class="text">
                    <span class="date-text">{date_str}</span>
                    <span class="weekday">• {weekday}</span>
                </span>
            </div>
            {time_row}
            {location_row}
            {phone_row}
            {fee_row}
            {status_row}
        </div>
    </div>
</body>
</html>
"""

ROW_TEMPLATE = '<div class="row"><span class="icon">{icon}</span><span class="text">{text}</span></div>'

STATUS_ROW_TEMPLATE = '<div class="row"><span class="icon">❌</span><span class="status-full">AUSGEBUCHT</span></div>'


def generate_event_html(event) -> str:
    """Generate HTML for an event card."""
    weekday = WEEKDAYS_DE[event.date.weekday()]
    
    # Event type
    if event.event_type == "tournament":
        event_type_label = "🏆 Turnier"
        event_type_class = "tournament"
    else:
        event_type_label = "⚽ Freundschaftsspiel"
        event_type_class = "friendly"
    
    # Build optional rows
    time_row = ""
    if event.time_start:
        time_str = event.time_start
        if event.time_end:
            time_str += f" - {event.time_end}"
        time_row = ROW_TEMPLATE.format(icon="🕐", text=time_str)
    
    location_row = ""
    if event.location:
        location_row = ROW_TEMPLATE.format(icon="📍", text=event.location)
    
    phone_row = ""
    if event.contact_phone:
        phone_row = ROW_TEMPLATE.format(icon="📞", text=event.contact_phone)
    
    fee_row = ""
    if hasattr(event, 'entry_fee') and event.entry_fee:
        fee_row = ROW_TEMPLATE.format(icon="💰", text=f"{event.entry_fee}€")
    
    status_row = ""
    if event.status == "full":
        status_row = STATUS_ROW_TEMPLATE
    
    return CARD_TEMPLATE.format(
        organizer=event.organizer or "Termin",
        event_type_label=event_type_label,
        event_type_class=event_type_class,
        date_str=event.date.strftime("%d.%m.%Y"),
        weekday=weekday,
        time_row=time_row,
        location_row=location_row,
        phone_row=phone_row,
        fee_row=fee_row,
        status_row=status_row,
    )


def render_event_card(event, output_path: str = None) -> str:
    """Render an event card to PNG image.
    
    Args:
        event: Event object with date, organizer, etc.
        output_path: Optional path for output image. If None, creates temp file.
        
    Returns:
        Path to the generated PNG image.
    """
    from playwright.sync_api import sync_playwright
    
    html = generate_event_html(event)
    
    # Create temp HTML file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        html_path = f.name
    
    try:
        # Render to image
        if output_path is None:
            output_path = tempfile.mktemp(suffix='.png')
        
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 450, 'height': 600})
            page.goto(f'file://{html_path}')
            
            # Screenshot just the card element
            card = page.locator('.card')
            card.screenshot(path=output_path)
            
            browser.close()
        
        return output_path
    finally:
        # Cleanup temp HTML
        os.unlink(html_path)


def render_week_header(week_start: date, output_path: str = None) -> str:
    """Render a week header card to PNG image."""
    from playwright.sync_api import sync_playwright
    
    week_num = week_start.isocalendar()[1]
    week_end = week_start + __import__('datetime').timedelta(days=6)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: transparent; }}
            .card {{
                width: 400px;
                background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
                border-radius: 12px;
                padding: 16px 20px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            }}
            .week {{
                color: #fff;
                font-size: 20px;
                font-weight: 700;
                text-align: center;
            }}
            .dates {{
                color: rgba(255,255,255,0.7);
                font-size: 15px;
                margin-top: 4px;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="week">📅 Kalenderwoche {week_num}</div>
            <div class="dates">{week_start.strftime('%d.%m.')} - {week_end.strftime('%d.%m.%Y')}</div>
        </div>
    </body>
    </html>
    """
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        html_path = f.name
    
    try:
        if output_path is None:
            output_path = tempfile.mktemp(suffix='.png')
        
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 450, 'height': 200})
            page.goto(f'file://{html_path}')
            
            card = page.locator('.card')
            card.screenshot(path=output_path)
            
            browser.close()
        
        return output_path
    finally:
        os.unlink(html_path)
