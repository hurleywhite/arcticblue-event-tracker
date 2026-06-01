"""One-off (re-runnable) merge of the ArcticScout export into the canonical
data/events.json.

Why this exists
---------------
ArcticScout_Events_Tracker.xlsx is a 184-row research export with far richer
per-event metadata than the original 82-event catalog (About, Focus Areas,
Typical Attendees, Speaking Route, Contact Info, Deadline, Attendee Count,
Pay-to-Play, Seed, Urgent, venue, granular region, POC email, Notes, status,
speaker). This script folds those rows ADDITIVELY into data/events.json:

  * Events whose lower(name) already exists are ENRICHED — we only fill in
    fields the existing row is missing; we never clobber a non-empty value.
  * New events are appended with fresh sequential `num`s.

The merge is idempotent: running it twice produces the same file (matching by
lower(name), enrichment only fills blanks).

Run:  python3 scripts/merge_arcticscout.py
"""
from __future__ import annotations
import json
import re
import math
from pathlib import Path
from datetime import date

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
EVENTS_JSON = HERE / 'data' / 'events.json'
XLSX = HERE / 'data' / 'ArcticScout_Events_Tracker.xlsx'

MONTHS = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
          'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}
MONTH_NAME = {v: k.capitalize() for k, v in MONTHS.items()}

# Rich fields ArcticScout carries that the original catalog did not.
RICH_FIELDS = [
    'about', 'focus_areas', 'typical_attendees', 'speaking_route',
    'contact_info', 'poc_email', 'deadline', 'attendee_count',
    'pay_to_play', 'seed', 'urgent', 'venue', 'city', 'country',
    'region', 'notes', 'speaker', 'workflow_status', 'end_date', 'start_date',
    'external_id', 'source',
]


def clean(v):
    """NaN / blank / placeholder → None; else stripped string."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    if not s or s.lower() in ('nan', 'none', 'n/a', 'na', 'null'):
        return None
    return s


def yesno(v):
    s = clean(v)
    if s is None:
        return None
    return s.strip().lower() in ('yes', 'true', '1', 'y')


def parse_md(s):
    """'April 14, 2026' → date(2026,4,14). Returns None on TBD/unparseable."""
    s = clean(s)
    if not s:
        return None
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$', s)
    if not m:
        return None
    mn = m.group(1).lower()
    if mn not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[mn], int(m.group(2)))


def make_date_str(start: date | None, end: date | None) -> str:
    if not start:
        return 'Date TBD'
    if not end or end == start:
        return f'{MONTH_NAME[start.month]} {start.day}, {start.year}'
    if start.year == end.year and start.month == end.month:
        return f'{MONTH_NAME[start.month]} {start.day}–{end.day}, {start.year}'
    if start.year == end.year:
        return f'{MONTH_NAME[start.month]} {start.day} – {MONTH_NAME[end.month]} {end.day}, {start.year}'
    return (f'{MONTH_NAME[start.month]} {start.day}, {start.year} – '
            f'{MONTH_NAME[end.month]} {end.day}, {end.year}')


def norm_url(v):
    s = clean(v)
    if not s:
        return None
    if s.lower() in ('unknown', 'tbd', 'pending', 'various'):
        return None
    if not re.match(r'^https?://', s, re.I):
        s = 'https://' + s
    return s


COUNTRY_FIX = {'CA': 'Canada', 'United States': 'USA', 'United Kingdom': 'UK',
               'United Arab Emirates': 'UAE'}


def build_location(city, country, venue):
    city = clean(city)
    country = clean(country)
    if country in COUNTRY_FIX:
        country = COUNTRY_FIX[country]
    bits = []
    if city and city.lower() not in ('tbd', 'various', 'remote', 'podcast'):
        bits.append(city)
    if country:
        bits.append(country)
    if bits:
        return ', '.join(bits)
    return clean(venue) or (city or '') or ''


def main():
    data = json.loads(EVENTS_JSON.read_text())
    events = data.get('events') or []

    by_name = {}
    max_num = 0
    for ev in events:
        nm = (ev.get('name') or '').strip().lower()
        if nm:
            by_name[nm] = ev
        if isinstance(ev.get('num'), int):
            max_num = max(max_num, ev['num'])

    df = pd.read_excel(XLSX, sheet_name='All Events')

    enriched = 0
    appended = 0
    for _, row in df.iterrows():
        name = clean(row.get('Event Name'))
        if not name:
            continue
        start = parse_md(row.get('Start Date'))
        end = parse_md(row.get('End Date'))
        if start and not end:
            end = start

        rich = {
            'about':             clean(row.get('About')),
            'focus_areas':       clean(row.get('Focus Areas')),
            'typical_attendees': clean(row.get('Typical Attendees')),
            'speaking_route':    clean(row.get('Speaking Route')),
            'contact_info':      clean(row.get('Contact Info')),
            'poc_email':         clean(row.get('POC Email')),
            'deadline':          clean(row.get('Deadline')),
            'attendee_count':    clean(row.get('Attendee Count')),
            'pay_to_play':       clean(row.get('Pay-to-Play')),
            'seed':              yesno(row.get('Seed?')),
            'urgent':            yesno(row.get('Urgent?')),
            'venue':             clean(row.get('Location (venue)')),
            'city':              clean(row.get('City')),
            'country':           clean(row.get('Country')),
            'region':            clean(row.get('Region')),
            'notes':             clean(row.get('Notes')),
            'speaker':           clean(row.get('Speaker(s) (derived from notes)')),
            'workflow_status':   clean(row.get('Status (derived from notes)')),
            'external_id':       clean(row.get('ID')),
            'source':            'arcticscout',
            'start_date':        start.isoformat() if start else None,
            'end_date':          end.isoformat() if end else None,
        }
        core = {
            'name':     name,
            'date_str': make_date_str(start, end),
            'location': build_location(row.get('City'), row.get('Country'), row.get('Location (venue)')),
            'type':     clean(row.get('Industry / Event Type')) or '',
            'priority': clean(row.get('Priority')) or '',
            'why':      clean(row.get('Why It Fits ArcticBlue')) or '',
            'url':      norm_url(row.get('Website URL')),
        }

        key = name.lower()
        existing = by_name.get(key)
        if existing is not None:
            # ENRICH: fill only blanks; never clobber a non-empty value.
            for k, v in {**core, **rich}.items():
                if v in (None, ''):
                    continue
                cur = existing.get(k)
                if cur in (None, ''):
                    existing[k] = v
            enriched += 1
        else:
            max_num += 1
            new_ev = {'num': max_num}
            new_ev.update({k: v for k, v in core.items() if v not in (None, '')})
            for k, v in rich.items():
                if v not in (None, ''):
                    new_ev[k] = v
            events.append(new_ev)
            by_name[key] = new_ev
            appended += 1

    data['events'] = events
    data['counts'] = {**data.get('counts', {}), 'total': len(events)}
    EVENTS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'enriched {enriched} existing, appended {appended} new → {len(events)} total events')


if __name__ == '__main__':
    main()
