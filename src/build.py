#!/usr/bin/env python3
"""Build an ArcticBlue Event Tracker â€” a self-contained, beautiful, deploy-direct
HTML page using ArcticBlue's real brand (black, periwinkle, Hanken Grotesk).

Pulls the 82 events from the Q2/Q3 2026 doc, splits them into TODAY / UPCOMING /
ARCHIVED relative to today (2026-05-21), and renders a single file ready to
upload to Vercel."""
import sys
sys.path.insert(0, '/Users/hurleywhite/Library/Python/3.11/lib/python/site-packages')
# `from docx import Document` is now lazy inside _parse_events_docx() â€” the
# canonical source is data/events.json. The .docx parser is only the legacy
# bootstrap fallback. Keeping the import at top-level used to break the whole
# build when lxml was in a broken state on the host.
import re
from datetime import date, datetime
from html import escape as e
from pathlib import Path

import json
HERE = Path(__file__).resolve().parent.parent
DOC_PATH      = HERE / 'data' / 'ArcticBlue AI 2026 Event Tracker.docx'
EVENTS_SOURCE = HERE / 'data' / 'events.json'   # canonical source â€” fed by Dust agent ingest
URLS_FROM_DOC = HERE / 'data' / 'event-urls-from-doc.json'
URLS_MANUAL   = HERE / 'data' / 'event-urls-manual.json'
OUT_SHIP      = HERE / 'public' / 'index.html'

# Date the build "thinks" today is.
# - Default to the real `date.today()` so a daily cron always reflects the
#   current calendar day.
# - Override with the BUILD_DATE env var (YYYY-MM-DD) when you need a
#   reproducible local build for snapshot/debug purposes.
import os
_build_date_env = os.environ.get('BUILD_DATE', '').strip()
if _build_date_env:
    TODAY = date.fromisoformat(_build_date_env)
else:
    # The team is in New York, and CI runs in UTC â€” between midnight and 4-5am
    # UTC that is still YESTERDAY in New York, so a plain date.today() rolled
    # the tracker over hours early (Hurley 2026-07-30). Everything downstream
    # (today / upcoming / archived, the header stamp) keys off this.
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        TODAY = _dt.now(ZoneInfo('America/New_York')).date()
    except Exception:
        TODAY = date.today()

# â”€â”€ Supabase (For Angela ops tab) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Project: AB Event Tracker [Hurley's Org] (ref efkvhlmfdwlobvdmvqiq)
# The publishable key is safe to embed in the HTML â€” RLS protects the data.
# Writes to event_state and manual_events require auth.email() in allowed_editors.
SUPABASE_URL              = 'https://efkvhlmfdwlobvdmvqiq.supabase.co'
SUPABASE_PUBLISHABLE_KEY  = 'sb_publishable_Lu7bLEA1jdsJXFDrKqC1OA_LYAjWYEj'

# Persona single-source-of-truth (config/personas.json) baked into the page so
# the Day-Of tab + brief drawer render without a runtime fetch. api/briefing.py
# reads the same file. PERSONAS_JS is a JSON object literal for the JS.
PERSONAS_JS = json.dumps(json.loads((HERE / 'config' / 'personas.json').read_text()), ensure_ascii=False)

# NEVER hallucinate URLs â€” only use what's in the doc OR what's manually
# vouched for in event-urls-manual.json. See AGENT-CONTEXT.md, Rule 2.
EVENT_URLS = {}
try:
    with open(URLS_FROM_DOC) as f:
        EVENT_URLS.update(json.load(f))
except Exception:
    pass
try:
    with open(URLS_MANUAL) as f:
        manual = json.load(f)
        # Manual entries override doc-extracted ones; skip documentation keys
        EVENT_URLS.update({k: v for k, v in manual.items() if not k.startswith('_')})
except Exception:
    pass


def parse_events():
    """Load events.

    Source priority:
      1. data/events.json  â€” the canonical, ingest-fed state (preferred)
      2. data/ArcticBlue AI 2026 Event Tracker.docx â€” legacy bootstrap fallback
    """
    if EVENTS_SOURCE.exists():
        return _load_events_json()
    return _parse_events_docx()


def _load_events_json():
    """Read canonical events from data/events.json. Side-effect: merge any
    `url` fields into the global EVENT_URLS map so render still respects
    the no-hallucination rule (null url â†’ unlinked card)."""
    data = json.loads(EVENTS_SOURCE.read_text())
    raw = data.get('events') or []
    # Optional rich metadata (present on ArcticScout-sourced rows). We carry
    # every key through so the expanded pop-up card can render them.
    RICH_KEYS = (
        'about', 'focus_areas', 'typical_attendees', 'speaking_route',
        'contact_info', 'poc_email', 'deadline', 'attendee_count',
        'pay_to_play', 'pricing', 'audience_type', 'past_speakers',
        'meeting_formats', 'attend_verdict', 'postmortem', 'seed', 'urgent',
        'venue', 'city', 'country',
        'region', 'notes', 'speaker', 'workflow_status', 'source',
        'external_id', 'start_date', 'end_date',
    )
    # Some source locations carry a trailing "(Halo)" / "(Seed, Halo)" tag
    # baked into the text â€” redundant noise (Halo is the type, Seed is a flag).
    # Strip it everywhere so it never shows on cards/modal.
    _LOC_TAG_RE = re.compile(r'\s*\((?:seed|halo)(?:\s*,\s*(?:seed|halo))*\)\s*$', re.I)
    events = []
    for r in raw:
        ev = {
            'num':           r.get('num'),
            'name':          r.get('name', ''),
            'date_str':      r.get('date_str', ''),
            'location':      _LOC_TAG_RE.sub('', r.get('location', '') or '').strip(),
            # Same noise leaks into a few `type` values ("Halo (Seed)" -> "Halo").
            'type':          _LOC_TAG_RE.sub('', r.get('type', '') or '').strip(),
            'priority':      r.get('priority', ''),
            'priority_full': r.get('priority_full', r.get('priority', '')),
            'why':           r.get('why', ''),
        }
        for k in RICH_KEYS:
            if r.get(k) not in (None, ''):
                ev[k] = r.get(k)
        events.append(ev)
        # Merge URL from events.json into the lookup map (only if non-null)
        if r.get('url') and r.get('num') is not None:
            EVENT_URLS[str(r['num'])] = r['url']
    return events


def _parse_events_docx():
    from docx import Document  # lazy: only loaded on legacy fallback path
    doc = Document(DOC_PATH)
    events = []
    current = {}
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        m = re.match(r'^(\d+)\.\s+(.+?)\s+â€”\s+(.+?)\s+\|\s+(.+)$', txt)
        if m:
            if current:
                events.append(current)
            current = {'num': int(m.group(1)), 'name': m.group(2),
                       'date_str': m.group(3), 'location': m.group(4),
                       'type': '', 'priority': '', 'why': ''}
        elif current:
            if txt.startswith('Type:'):
                current['type'] = txt.replace('Type:', '').strip()
            elif txt.startswith('Priority:'):
                p_full = txt.replace('Priority:', '').strip()
                # Pull leading word for the badge (High / Medium / Low)
                first = re.match(r'^(\w+)', p_full)
                current['priority'] = first.group(1) if first else p_full
                current['priority_full'] = p_full
            elif txt.startswith('Why it fits') and not current['why']:
                current['why'] = re.sub(r'^Why it fits[^:]*:', '', txt).strip()
    if current:
        events.append(current)
    return events


def parse_date(date_str):
    """Return (start_date, end_date, original_string). Handles 'June 1â€“4, 2026',
    'May 19, 2026', 'June 3â€“6, 2026 (TBC)', etc."""
    s = date_str.strip()
    # Strip parentheticals
    s_clean = re.sub(r'\([^)]+\)', '', s).strip()
    # Try patterns
    months = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
              'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}
    # "Month D[â€“|-D] YYYY"
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2})\s*[â€“-]\s*(\d{1,2}),\s+(\d{4})$', s_clean)
    if m:
        mn, d1, d2, y = m.group(1).lower(), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if mn in months:
            return date(y, months[mn], d1), date(y, months[mn], d2)
    # "Month D, YYYY"
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$', s_clean)
    if m:
        mn, d1, y = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        if mn in months:
            return date(y, months[mn], d1), date(y, months[mn], d1)
    # "Month D â€“ Month D, YYYY" (cross-month)
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2})\s*[â€“-]\s*([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$', s_clean)
    if m:
        m1, d1, m2, d2, y = m.group(1).lower(), int(m.group(2)), m.group(3).lower(), int(m.group(4)), int(m.group(5))
        if m1 in months and m2 in months:
            return date(y, months[m1], d1), date(y, months[m2], d2)
    # "Month D - Month D, YYYY" no spaces
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2})-(\d{1,2}),\s+(\d{4})$', s_clean)
    if m:
        mn, d1, d2, y = m.group(1).lower(), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if mn in months:
            return date(y, months[mn], d1), date(y, months[mn], d2)
    # Numeric (Angela's spreadsheet style) â€” "6/3/2026", "6/3-5/2026",
    # "6/3-6/5/2026", "3/6/26". Mirrors the client deriveDatesFromText so the
    # iCal feed + classification don't silently skip these.
    def _yr(v):
        v = int(v)
        return v + 2000 if v < 100 else v
    m = re.match(r'^(\d{1,2})/(\d{1,2})\s*[â€“-]\s*(\d{1,2})/(\d{1,2})/(\d{2,4})$', s_clean)  # M/D-M/D/Y
    if m:
        try:
            return date(_yr(m.group(5)), int(m.group(1)), int(m.group(2))), \
                   date(_yr(m.group(5)), int(m.group(3)), int(m.group(4)))
        except ValueError:
            pass
    m = re.match(r'^(\d{1,2})/(\d{1,2})\s*[â€“-]\s*(\d{1,2})/(\d{2,4})$', s_clean)  # M/D-D/Y (same month)
    if m:
        try:
            mo, y = int(m.group(1)), _yr(m.group(4))
            return date(y, mo, int(m.group(2))), date(y, mo, int(m.group(3)))
        except ValueError:
            pass
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', s_clean)  # single M/D/Y
    if m:
        try:
            d = date(_yr(m.group(3)), int(m.group(1)), int(m.group(2)))
            return d, d
        except ValueError:
            pass
    return None, None


def classify(events):
    today_events, upcoming, archived = [], [], []
    for ev in events:
        # Prefer explicit ISO start/end (ArcticScout rows carry them) so
        # bucketing never depends on re-parsing a display date string.
        start = end = None
        iso_s, iso_e = ev.get('start_date'), ev.get('end_date')
        if iso_s:
            try:
                start = date.fromisoformat(iso_s)
                end = date.fromisoformat(iso_e) if iso_e else start
            except (ValueError, TypeError):
                start = end = None
        if not start:
            start, end = parse_date(ev['date_str'])
        if not start:
            ev['_parse_failed'] = True
            upcoming.append(ev)  # fail safe
            continue
        if end is None:
            end = start
        ev['_start'] = start
        ev['_end'] = end
        # An event whose end date is today or earlier is over â€” archive it
        # (single-day events happening today included). Only genuinely-ongoing
        # multi-day events (still running past today) stay in "today".
        if end <= TODAY:
            archived.append(ev)
        elif start <= TODAY:
            today_events.append(ev)
        else:
            upcoming.append(ev)
    upcoming.sort(key=lambda x: x.get('_start') or date(2099,1,1))
    archived.sort(key=lambda x: x.get('_end') or date(1900,1,1), reverse=True)
    return today_events, upcoming, archived


def fmt_date(ev):
    """Mono-friendly short date string for display."""
    return ev['date_str']


def priority_class(p):
    p = (p or '').lower()
    if 'high' in p: return 'p-high'
    if 'medium' in p: return 'p-medium'
    if 'low' in p: return 'p-low'
    return 'p-medium'


def region_from_location(loc):
    loc = loc.lower()
    if any(c in loc for c in ['usa', 'canada', 'brazil']): return 'Americas'
    if any(c in loc for c in ['uk', 'germany', 'france', 'spain', 'netherlands', 'belgium', 'portugal', 'switzerland', 'italy']): return 'Europe'
    if any(c in loc for c in ['singapore', 'hong kong', 'china', 'australia', 'japan', 'korea']): return 'Asia-Pacific'
    if any(c in loc for c in ['saudi arabia', 'dubai', 'uae', 'qatar', 'doha']): return 'MENA'
    return 'Global'


def render_event_card(ev, archived=False):
    priority_label = ev.get('priority', 'Medium')
    pc = priority_class(priority_label)
    region = region_from_location(ev.get('location', ''))
    typ = ev.get('type', 'Enterprise')
    why = ev.get('why', '')
    if why and len(why) > 220:
        why = why[:220].rsplit(' ', 1)[0] + 'â€¦'
    extra_class = ' archived' if archived else ''
    num = ev.get('num', '')
    # Verified URL from the source doc (no invented URLs). The title always
    # opens the event detail card; the modal carries the website link inside it.
    url = EVENT_URLS.get(str(num))
    nm = e(ev['name'])
    if url: extra_class += ' has-link'
    name_html = (f'<a class="event-name-link event-detail-link" href="#event-detail-catalog-{e(str(num))}" '
                 f'data-event-detail data-event-detail-kind="catalog" data-event-detail-key="{e(str(num))}" '
                 f'aria-label="Open details for {nm}">{nm}</a>')
    # Attending signals (Verma): who's in the room, what a ticket costs, and
    # whether the event has built-in meeting mechanisms. Only rendered when
    # the catalog actually knows them.
    aud = str(ev.get('audience_type') or '').strip()
    sig = []
    if aud and aud.lower() != 'mixed':
        low = aud.lower()
        aud_cls = ('aud-buyer' if 'buyer' in low
                   else 'aud-vendor' if ('vendor' in low or 'seller' in low)
                   else 'aud-mixed')
        sig.append(f'<span class="badge {aud_cls}">{e(aud)}</span>')
    if ev.get('pricing'):
        sig.append(f'<span class="attend-sig" title="Price to attend">'
                   f'{e(str(ev["pricing"]))}</span>')
    signals_html = (f'<p class="attend-signals">{"".join(sig)}</p>' if sig else '')
    return f'''
    <article class="event is-clickable{extra_class}"
             data-num="{e(str(num))}"
             data-priority="{e(priority_label)}"
             data-region="{e(region)}"
             data-type="{e(typ)}"
             role="button" tabindex="0" aria-haspopup="dialog"
             aria-label="Open details for {e(ev['name'])}">
      <header class="event-head">
        <p class="event-date">{e(fmt_date(ev))}</p>
        <span class="badge {pc}">{e(priority_label)}</span>
      </header>
      <h3 class="event-name">{name_html}</h3>
      <p class="event-loc">{e(ev['location'])}</p>
      {signals_html}
      {f'<p class="event-why">{e(why)}</p>' if why else ''}
      <footer class="event-foot">
        <span class="event-type">{e(typ)}</span>
        <span class="event-more">Details â†’</span>
      </footer>
    </article>'''


def render_upcoming_grouped(upcoming):
    """Render the upcoming list with a full-width month divider before each
    new month, so the grid reads month-by-month instead of one long block.

    `upcoming` is already sorted ascending by `_start` (events that failed to
    parse a date have no `_start` and sort to the end â†’ grouped under
    'Date TBD'). Headers carry a data-month key + per-month count so the
    client filter JS can hide a header when none of its cards are visible.
    """
    out = []
    cur_key = None
    # Pre-count events per group so each header can show its size.
    counts = {}
    for ev in upcoming:
        start = ev.get('_start')
        k = (start.year, start.month) if start else ('tbd',)
        counts[k] = counts.get(k, 0) + 1
    for ev in upcoming:
        start = ev.get('_start')
        if start:
            key = (start.year, start.month)
            label = start.strftime('%B %Y')
            data_key = f'{start.year:04d}-{start.month:02d}'
        else:
            key = ('tbd',)
            label = 'Date TBD'
            data_key = 'tbd'
        if key != cur_key:
            cur_key = key
            n = counts[key]
            noun = 'event' if n == 1 else 'events'
            out.append(
                f'<div class="month-header" data-month="{data_key}" role="separator" '
                f'aria-label="{label}, {n} {noun}">{e(label)}'
                f'<span class="month-count">{n} {noun}</span></div>'
            )
        out.append(render_event_card(ev))
    return '\n'.join(out)


def build():
    events = parse_events()
    today_evs, upcoming, archived = classify(events)
    upcoming_count = len(upcoming)
    archived_count = len(archived)

    # Find the next single event
    next_up = upcoming[0] if upcoming else None

    # Render groups
    today_html = '\n'.join(render_event_card(ev) for ev in today_evs) if today_evs else ''
    upcoming_html = render_upcoming_grouped(upcoming)
    archived_html = '\n'.join(render_event_card(ev, archived=True) for ev in archived)

    # â”€â”€ Catalog data blob for the expanded pop-up (modal) cards â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Every rendered card carries data-num; the modal looks the full record
    # up here by num. Includes the ArcticScout rich fields when present.
    MODAL_FIELDS = (
        'about', 'focus_areas', 'typical_attendees', 'speaking_route',
        'contact_info', 'poc_email', 'deadline', 'attendee_count',
        'pay_to_play', 'pricing', 'audience_type', 'past_speakers',
        'meeting_formats', 'attend_verdict', 'postmortem', 'seed', 'urgent',
        'venue', 'city', 'country',
        'notes', 'speaker', 'workflow_status', 'source', 'priority_full',
    )

    def modal_event(ev, bucket):
        rec = {
            'num':      ev.get('num'),
            'name':     ev.get('name', ''),
            'date_str': ev.get('date_str', ''),
            'location': ev.get('location', ''),
            'region':   ev.get('region') or region_from_location(ev.get('location', '')),
            'type':     ev.get('type', ''),
            'priority': ev.get('priority', ''),
            'why':      ev.get('why', ''),
            'url':      EVENT_URLS.get(str(ev.get('num', ''))),
            'status':   bucket,
        }
        for k in MODAL_FIELDS:
            if ev.get(k) not in (None, ''):
                rec[k] = ev.get(k)
        return rec

    catalog_records = (
        [modal_event(ev, 'today')    for ev in today_evs] +
        [modal_event(ev, 'upcoming') for ev in upcoming]  +
        [modal_event(ev, 'archived') for ev in archived]
    )
    catalog_by_num = {str(r['num']): r for r in catalog_records if r.get('num') is not None}
    # Escape '<' so a field value can never break out of the <script> tag.
    catalog_json = json.dumps(catalog_by_num, ensure_ascii=False).replace('<', '\\u003c')

    today_iso = TODAY.isoformat()
    last_updated = TODAY.strftime('%B %d, %Y')

    head = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ArcticBlue Â· Event Tracker</title>
  <meta name="description" content="ArcticBlue's live tracker of in-person AI events, Mayâ€“December 2026. Today, upcoming, and archived. 82 enterprise + halo events.">

  <link rel="canonical" href="https://arcticblue.ai/labs/event-tracker/">

  <meta property="og:title" content="ArcticBlue Â· Event Tracker">
  <meta property="og:description" content="82 in-person AI events tracked live. Today, upcoming, and archived â€” sorted by priority and region.">
  <meta property="og:image" content="https://arcticblue.ai/og-default.png">
  <meta property="og:url" content="https://arcticblue.ai/labs/event-tracker/">
  <meta property="og:type" content="website">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="ArcticBlue Â· Event Tracker">
  <meta name="twitter:description" content="82 in-person AI events tracked live.">

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=Nunito+Sans:wght@600;700;800;900&family=Fragment+Mono&display=swap" rel="stylesheet">

  <!-- Supabase JS client â€” used only by the "For Angela" ops tab -->
  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js" defer></script>

  <style>
    :root {{
      /* Internal-tool palette â€” white-primary, monochromatic, sharp */
      --ab-bg: #ffffff;
      --ab-bg-2: #fafafa;
      --ab-bg-3: #f4f4f5;
      --ab-rule: #e7e7e8;
      --ab-rule-strong: #d4d4d6;
      --ab-fg: #0a0a0a;
      --ab-fg-2: #404040;
      --ab-fg-3: #737373;
      --ab-mute: #a3a3a3;
      /* Brand accents â€” used sparingly */
      --ab-blue: #2773c2;        /* primary accent (from the logo's middle blue) */
      --ab-blue-light: #4ea3d4;  /* lighter accent */
      --ab-amber: #ca8a04;        /* medium-priority */
      --ab-green: #15803d;        /* available / success */
      --ab-red: #b91c1c;          /* archived / fail */
      --ab-sans: "Hanken Grotesk", "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
      --ab-mono: "Fragment Mono", "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
      /* What Angela actually writes her outreach in. Used only by the email
         composer + template editor so the preview matches the sent mail. */
      --ab-email: "Trebuchet MS", "Lucida Grande", "Lucida Sans Unicode", "Lucida Sans", Tahoma, sans-serif;
      --ab-max: 1240px;
    }}

    * {{ box-sizing: border-box; }}
    html, body {{ background: var(--ab-bg); }}
    body {{
      margin: 0;
      font-family: var(--ab-sans);
      color: var(--ab-fg);
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      letter-spacing: -0.005em;
      min-height: 100vh;
    }}

    /* Reset margins on definition lists so KPI labels sit cleanly under numbers */
    dl, dt, dd {{ margin: 0; }}

    .wrap {{ max-width: var(--ab-max); margin: 0 auto; padding: 0 24px; position: relative; }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ nav strip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .nav {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 18px 24px;
      border-bottom: 1px solid var(--ab-rule);
      background: rgba(255, 255, 255, 0.85);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      position: sticky; top: 0; z-index: 10;
    }}
    .nav-inner {{ max-width: var(--ab-max); margin: 0 auto; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; width: 100%; gap: 16px; }}
    .brand {{
      display: flex; align-items: center; gap: 12px; justify-self: start;
      color: var(--ab-fg); text-decoration: none;
    }}
    .brand img {{
      height: 32px; width: auto; display: block;
    }}
    .brand-text {{
      font-family: var(--ab-sans); font-weight: 800;
      letter-spacing: -0.02em; font-size: 1.05rem; color: var(--ab-fg);
    }}
    .nav-meta {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      text-transform: uppercase; justify-self: end; text-align: right;
    }}
    /* "Viewing as <name> change" now lives in the nav next to the date. */
    .nav-meta .who {{
      text-transform: none; letter-spacing: normal;
      font-weight: 700; color: var(--ab-fg-2); white-space: nowrap;
    }}
    .nav-meta .who button.inline {{
      border: 0; background: none; padding: 0 0 0 6px; cursor: pointer;
      font-family: var(--ab-mono); font-size: inherit; font-weight: 700;
      text-transform: none; letter-spacing: normal;
      color: var(--ab-blue, #1d4ed8); text-decoration: underline;
    }}
    /* "Who am I" â€” your bubble; click it to drop down everyone else's bubbles
       to switch, or "Otherâ€¦" to type a name not on the roster. */
    .who-switcher {{ position: relative; display: inline-block; vertical-align: middle; }}
    .who-init {{
      display: inline-flex; align-items: center; justify-content: center;
      min-width: 20px; height: 20px; padding: 0 5px; border-radius: 999px;
      background: var(--ab-blue); color: #fff; border: 0; cursor: pointer;
      font-family: var(--ab-sans); font-size: 0.6rem; font-weight: 700;
      letter-spacing: 0; text-transform: none; line-height: 1;
      transition: opacity 120ms ease;
    }}
    .who-init:hover {{ opacity: 0.82; }}
    .who-current {{ box-shadow: 0 0 0 2px var(--ab-rule-strong); }}
    .who-dropdown {{
      position: absolute; top: 100%; right: 0; margin-top: 6px; z-index: 40;
      display: flex; flex-direction: column; gap: 3px; padding: 7px; width: 178px;
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 10px; box-shadow: 0 6px 20px rgba(0,0,0,0.14);
    }}
    .who-dropdown[hidden] {{ display: none; }}   /* [hidden] alone loses to .who-dropdown's display:flex */
    .who-menu-item {{
      display: flex; align-items: center; gap: 9px; width: 100%;
      padding: 7px 9px; border: 0; background: none; border-radius: 7px;
      cursor: pointer; text-align: left; font-family: var(--ab-sans);
      font-size: 0.82rem; font-weight: 650; color: var(--ab-fg);
    }}
    .who-menu-item:hover {{ background: var(--ab-bg-3); }}
    .who-menu-item svg {{ width: 15px; height: 15px; flex: 0 0 auto; color: var(--ab-fg-3); }}
    .who-switch-label {{
      font-family: var(--ab-mono); font-size: 0.56rem; letter-spacing: 0.07em;
      text-transform: uppercase; color: var(--ab-fg-3);
      padding: 6px 9px 3px; margin-top: 2px; border-top: 1px solid var(--ab-rule);
    }}
    .who-switch-row {{ display: flex; flex-wrap: wrap; gap: 6px; padding: 0 5px 2px; }}
    .who-dropdown .who-init {{ min-width: 24px; height: 24px; font-size: 0.62rem; }}
    .who-other {{
      width: 100%; margin-top: 3px; padding: 7px 9px 3px; border: 0; background: none;
      border-top: 1px solid var(--ab-rule); cursor: pointer; text-align: left;
      font-family: var(--ab-mono); font-size: 0.62rem; color: var(--ab-fg-3);
      text-decoration: underline; text-transform: none; letter-spacing: normal;
    }}
    /* App title â€” centered in the nav bar, same line as the logo + last-updated. */
    .app-title {{
      /* Matches the ArcticBlue logo â€” basic Helvetica-Bold (Thor's note). Uses
         the system Helvetica on Mac/most platforms, Arial as the close fallback.
         Not the rounded Nunito, which read as too casual. */
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-weight: 700; font-size: 1.5rem; letter-spacing: -0.01em;
      line-height: 1.1; color: #1fa0dc; margin: 0; white-space: nowrap;
      text-align: center;
    }}
    @media (max-width: 760px) {{
      .app-title {{ font-size: 1.05rem; }}
      .nav-meta {{ font-size: 0.6rem; }}
      .brand-text {{ display: none; }}
    }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ hero â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .hero {{ padding: 72px 0 48px; border-bottom: 1px solid var(--ab-rule); }}
    .eyebrow {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.14em;
      text-transform: uppercase; margin: 0 0 24px;
    }}
    h1 {{
      font-family: var(--ab-sans); font-weight: 800;
      font-size: clamp(2.4rem, 5.5vw, 4.5rem);
      line-height: 1.02; letter-spacing: -0.025em;
      margin: 0 0 24px; color: var(--ab-fg);
      max-width: 18ch;
    }}
    h1 em {{ font-style: normal; color: var(--ab-blue); }}
    .lede {{
      font-size: 1.15rem; color: var(--ab-fg-2);
      max-width: 60ch; margin: 0; line-height: 1.55;
    }}

    /* KPI strip â€” uniform columns, labels sit directly under numbers */
    .kpi-row {{
      display: grid; grid-template-columns: repeat(4, 1fr); gap: 0;
      border-top: 1px solid var(--ab-rule);
      border-bottom: 1px solid var(--ab-rule);
      margin: 48px 0 0;
    }}
    .kpi {{
      padding: 24px;
      border-right: 1px solid var(--ab-rule);
      display: flex; flex-direction: column; align-items: flex-start;
    }}
    .kpi:last-child {{ border-right: 0; }}
    .kpi-num {{
      font-family: var(--ab-mono); font-size: 2.4rem;
      color: var(--ab-fg); font-weight: 400;
      letter-spacing: -0.02em; line-height: 1; margin: 0 0 8px;
    }}
    .kpi-num .plus {{ color: var(--ab-blue); }}
    .kpi-label {{
      font-family: var(--ab-mono); font-size: 0.7rem;
      color: var(--ab-fg-3); letter-spacing: 0.1em;
      text-transform: uppercase; margin: 0;
    }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ today/up-next callout â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .today-block {{ padding: 48px 0 0; }}
    .today-card {{
      border: 1px solid var(--ab-rule);
      background: var(--ab-bg-2);
      padding: 28px 32px;
      border-radius: 4px;
      position: relative;
      overflow: hidden;
    }}
    .today-card::before {{
      content: "";
      position: absolute; top: 0; left: 0; bottom: 0; width: 3px;
      background: var(--ab-blue);
    }}
    .today-card-head {{
      display: flex; justify-content: space-between; align-items: baseline;
      margin: 0 0 12px; gap: 12px; flex-wrap: wrap;
    }}
    .today-label {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-blue); letter-spacing: 0.14em; text-transform: uppercase;
      font-weight: 600;
    }}
    .today-date {{
      font-family: var(--ab-mono); font-size: 0.74rem; color: var(--ab-fg-3);
    }}
    .today-name {{
      font-family: var(--ab-sans); font-weight: 800;
      font-size: 1.6rem; line-height: 1.15; margin: 0 0 8px;
      color: var(--ab-fg); letter-spacing: -0.015em;
    }}
    .today-meta {{ color: var(--ab-fg-2); font-size: 0.95rem; margin: 0 0 4px; }}
    .today-why {{ color: var(--ab-fg-3); font-size: 0.92rem; margin: 12px 0 0; max-width: 70ch; }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ filters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    section.events {{ padding: 56px 0 32px; }}
    .section-head {{
      display: flex; justify-content: space-between; align-items: baseline;
      gap: 16px; flex-wrap: wrap; margin: 0 0 24px;
      padding-bottom: 16px; border-bottom: 1px solid var(--ab-rule);
    }}
    .section-title {{
      font-family: var(--ab-sans); font-weight: 800;
      font-size: 1.6rem; letter-spacing: -0.015em; margin: 0; color: var(--ab-fg);
    }}
    .section-count {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em; text-transform: uppercase;
    }}
    .filter-bar {{
      display: flex; gap: 12px; flex-wrap: wrap; align-items: end;
      margin: 0 0 16px;
    }}
    .filter-group {{ display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 160px; }}
    .filter-group label {{
      font-family: var(--ab-mono); font-size: 0.68rem;
      color: var(--ab-fg-3); letter-spacing: 0.1em; text-transform: uppercase;
    }}
    .filter-group select, .filter-group input {{
      background: #fff;
      color: var(--ab-fg); border: 1px solid var(--ab-rule);
      padding: 12px 14px; font-family: var(--ab-sans); font-size: 0.95rem;
      border-radius: 2px; transition: border-color 0.15s;
      min-height: 44px;
    }}
    .filter-group select:focus, .filter-group input:focus {{
      outline: none; border-color: var(--ab-fg);
    }}
    #event-counter {{
      font-family: var(--ab-mono); font-size: 0.82rem;
      color: var(--ab-fg-3); margin: 0 0 24px;
    }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ event cards â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .event-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
    }}
    /* Month dividers inside the upcoming grid â€” span the full row so the
       list reads as month-by-month sections instead of one long block. */
    .month-header {{
      grid-column: 1 / -1;
      display: flex; align-items: center; gap: 14px;
      margin: 26px 0 4px;
      font-family: var(--ab-mono);
      font-size: 0.74rem; font-weight: 600; letter-spacing: 0.14em;
      text-transform: uppercase; color: var(--ab-fg-2);
    }}
    .month-header::after {{
      content: ""; flex: 1; height: 1px; background: var(--ab-rule);
    }}
    .month-header:first-child {{ margin-top: 0; }}
    .month-header .month-count {{
      font-weight: 400; color: var(--ab-fg-3); letter-spacing: 0.08em;
    }}
    .event {{
      background: #fff;
      border: 1px solid var(--ab-rule);
      padding: 22px;
      border-radius: 4px;
      transition: border-color 0.15s, transform 0.15s;
      display: flex; flex-direction: column; gap: 8px;
    }}
    .event:hover {{ border-color: var(--ab-fg-2); transform: translateY(-1px); }}
    .event-head {{
      display: flex; justify-content: space-between; align-items: center;
      gap: 12px; margin: 0;
    }}
    .event-date {{
      font-family: var(--ab-mono); font-size: 0.78rem;
      color: var(--ab-fg-3); letter-spacing: 0.02em; margin: 0;
    }}
    .badge {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.12em; text-transform: uppercase;
      padding: 3px 9px; border-radius: 2px; font-weight: 600;
    }}
    .badge.p-high {{ background: #166534; color: #fff; }}
    .badge.p-medium {{ background: var(--ab-bg-3); color: var(--ab-fg-2); border: 1px solid var(--ab-rule); }}
    .badge.p-low {{ background: transparent; color: var(--ab-fg-3); border: 1px solid var(--ab-rule); }}
    /* Buyer/seller read: green = buyers (what we want), amber = mixed, red = vendor fest. */
    .badge.aud-buyer {{ background: #166534; color: #fff; }}
    .badge.aud-mixed {{ background: #fef3c7; color: #92400e; border: 1px solid #f0c66b; }}
    .badge.aud-vendor {{ background: #fee2e2; color: #991b1b; border: 1px solid #f3b1b1; }}
    /* Attending signals row on cards: ticket price + meeting mechanisms. */
    .attend-signals {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 0 0 8px; }}
    .attend-sig {{
      font-family: var(--ab-mono); font-size: 0.66rem; letter-spacing: 0.06em;
      padding: 3px 9px; border-radius: 2px; font-weight: 600;
      background: var(--ab-bg-3); color: var(--ab-fg-2); border: 1px solid var(--ab-rule);
    }}
    /* Worth-attending verdict chip (Thor's post-mortems). */
    .badge.attend-yes {{ background: #1d4ed8; color: #fff; }}
    .badge.attend-no  {{ background: transparent; color: #991b1b; border: 1px solid #f3b1b1; }}
    /* CFP deadline on the card face; red when urgent or within ~30 days. */
    .deadline-line {{ font-weight: 600; }}
    .deadline-line.deadline-soon {{ color: #b91c1c !important; font-weight: 700; }}
    /* THE status line â€” one quiet derived line per card ("Closed to speak Â·
       Open to attend", "Booked â€” Thor speaking"). Plain text + a small colored
       dot; no boxes, no color assault. */
    .ops-status-line {{
      display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px;
      margin: 0 0 10px; font-size: 0.86rem; font-weight: 700; color: var(--ab-fg);
    }}
    .st-bit {{ display: inline-flex; align-items: center; white-space: nowrap; }}
    .st-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 6px; flex-shrink: 0; }}
    .st-ok   {{ background: #047857; }}
    .st-wait {{ background: #0ea5e9; }}
    .st-no   {{ background: #991b1b; }}   /* deeper red, in step with the rejected mic */
    /* Interest is a MAYBE â€” hollow ring, not a filled dot, so it reads lighter
       than Booked/Attending sitting beside it (matches the hollow star mark). */
    .st-int  {{ background: transparent; box-shadow: inset 0 0 0 2px #7c3aed; }}
    .st-sep  {{ color: var(--ab-fg-3); font-weight: 400; }}
    .st-sub-date {{ color: var(--ab-fg-3); font-weight: 500; }}
    /* Whisper-quiet data-freshness cue from updated_at. Deliberately faint â€”
       it's a background reassurance / nudge, not a headline. */
    .ops-fresh-line {{ margin: -4px 0 10px; }}
    .ops-fresh {{
      font-size: 0.72rem; font-weight: 500; letter-spacing: 0.01em;
      display: inline-flex; align-items: center; gap: 5px; color: var(--ab-fg-3);
    }}
    .ops-fresh::before {{
      content: ''; width: 6px; height: 6px; border-radius: 50%;
      background: currentColor; opacity: 0.65; flex-shrink: 0;
    }}
    .ops-fresh.is-fresh {{ color: #6b8f7a; }}   /* muted sage â€” quietly reassuring */
    .ops-fresh.is-stale {{ color: #b08968; }}   /* muted clay â€” a gentle "check me" */
    /* One-click "Apply to speak" button on ops cards â€” the booking shortcut. */
    /* Deadline/closed-to-speak label + Apply button sit side by side in one
       compact row, pinned to the bottom of the card (not each its own
       full-width block). */
    /* Card footer = a fixed STACK, one item per row, always in the same order:
       CFP deadline -> âœ‰ Contact -> Apply to speak. It used to be a wrapping row,
       so a card with a deadline put "CFP deadline: Rolling" and the Contact chip
       side by side while every other card had Contact on its own line â€” the chip
       landed in a different place card to card (Angela). Pinned to the bottom
       (margin-top:auto) so the footers line up across a row of cards. */
    .ops-card-foot {{
      display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
      margin-top: auto;
    }}
    .ops-card-foot > * {{ max-width: 100%; }}
    .ops-card-foot .ops-meta {{ margin: 0; }}
    /* Apply spans the FULL card width on its own row (Hurley â€” only Angela sees
       the button), below any deadline/contact note. */
    .ops-card-foot .ops-apply-btn {{ width: 100%; margin-left: 0; }}
    .ops-apply-btn {{
      display: flex; align-items: center; justify-content: center;
      box-sizing: border-box; text-align: center;
      font-family: var(--ab-mono); font-size: 0.7rem;
      letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700;
      padding: 7px 16px; border-radius: 999px;
      background: var(--ab-blue, #1d4ed8); color: #fff !important; text-decoration: underline; text-underline-offset: 2px;
    }}
    .ops-apply-btn:hover {{ opacity: 0.85; }}
    .event-name {{
      font-family: var(--ab-sans); font-size: 1.1rem; font-weight: 700;
      line-height: 1.25; margin: 0; color: var(--ab-fg); letter-spacing: -0.01em;
      overflow-wrap: anywhere;
    }}
    /* Event titles open the detail card â€” underlined + very bold. */
    .event-name-link {{
      color: inherit; font-weight: 800;
      text-decoration: underline; text-decoration-thickness: 2px;
      text-underline-offset: 3px; text-decoration-color: var(--ab-rule-strong);
      transition: color 0.15s, text-decoration-color 0.15s;
    }}
    .event-name-link:hover, .event-name-link:focus-visible {{
      color: var(--ab-blue); text-decoration-color: var(--ab-blue);
    }}
    .event-loc {{ font-size: 0.85rem; color: var(--ab-fg-3); margin: 0; }}
    .event-region {{ color: var(--ab-fg-2); font-weight: 500; }}
    .event-why {{ font-size: 0.85rem; color: var(--ab-fg-2); line-height: 1.5; margin: 4px 0 0; }}
    /* Note preview on the card face â€” clamped to 2 lines so a long pasted note
       (e.g. an application auto-reply) doesn't flood the grid. Full note in Details. */
    .event-note-preview {{
      font-size: 0.85rem; color: var(--ab-fg-2); line-height: 1.5; margin: 0 0 8px;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }}
    .event-foot {{
      margin-top: auto; padding-top: 10px; border-top: 1px solid var(--ab-rule);
      display: flex; justify-content: space-between; align-items: baseline; gap: 10px;
    }}
    .event-type {{
      font-family: var(--ab-mono); font-size: 0.68rem;
      color: var(--ab-fg-3); letter-spacing: 0.1em; text-transform: uppercase;
    }}
    .event-more {{
      font-family: var(--ab-mono); font-size: 0.66rem; letter-spacing: 0.08em;
      color: var(--ab-mute); text-transform: uppercase;
      opacity: 0; transition: opacity 0.15s, color 0.15s;
    }}
    .event.archived {{ opacity: 0.6; }}
    .event.archived:hover {{ opacity: 1; }}

    /* Clickable cards open the expanded pop-up (modal) */
    .event.is-clickable {{ cursor: pointer; }}
    .event.is-clickable:hover {{ border-color: var(--ab-blue); }}
    .event.is-clickable:focus-visible {{ outline: 2px solid var(--ab-blue); outline-offset: 2px; }}
    .event.is-clickable:hover .event-more {{ opacity: 1; color: var(--ab-blue); }}
    .event-link-arrow {{
      display: inline-block; font-family: var(--ab-mono);
      font-size: 0.85rem; color: var(--ab-fg-3);
      transition: color 0.15s, transform 0.15s;
      margin-left: 4px;
      vertical-align: 1px;
    }}
    .event.is-clickable:hover .event-link-arrow {{
      color: var(--ab-blue);
      transform: translate(2px, -2px);
    }}
    .event-no-link {{
      display: inline-block; color: var(--ab-rule-strong);
      font-family: var(--ab-mono); font-size: 0.85rem;
      margin-left: 4px; vertical-align: 1px;
      cursor: help;
    }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ expanded pop-up (modal) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .modal-overlay {{
      /* Above Leaflet's panes/controls (z-index up to ~1000), else the event
         pop-up opens BEHIND the map view. */
      position: fixed; inset: 0; z-index: 1200;
      background: rgba(10, 10, 10, 0.55);
      backdrop-filter: blur(3px);
      display: flex; align-items: flex-start; justify-content: center;
      padding: 5vh 20px; overflow-y: auto;
      animation: modalFade 0.14s ease-out;
    }}
    .modal-overlay[hidden] {{ display: none; }}
    @keyframes modalFade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
    .modal-card {{
      position: relative; background: #fff;
      width: 100%; max-width: 640px;
      border: 1px solid var(--ab-rule-strong); border-radius: 8px;
      box-shadow: 0 24px 60px rgba(10, 10, 10, 0.28);
      animation: modalRise 0.16s ease-out;
    }}
    @keyframes modalRise {{ from {{ transform: translateY(8px); opacity: 0.6; }} to {{ transform: translateY(0); opacity: 1; }} }}
    .modal-scroll {{ padding: 62px 32px 26px; max-height: 86vh; overflow-y: auto; }}
    /* Fixed top toolbar â€” Edit event + close sit in the SAME spot for every
       event. Full-width opaque band so form fields scroll cleanly UNDERNEATH it
       (no content bleeding through behind the buttons). */
    .modal-topbar {{
      position: absolute; top: 0; left: 0; right: 0; z-index: 3;
      display: flex; align-items: center; justify-content: flex-end; gap: 8px;
      padding: 12px 14px; background: #fff;
      border-bottom: 1px solid var(--ab-rule);
      border-radius: 8px 8px 0 0;
    }}
    /* Top-LEFT slot â€” holds the trash-can Delete while the editor is open. The
       topbar is justify-content: flex-end, so this pushes itself to the left. */
    #modal-head-left {{ margin-right: auto; display: flex; align-items: center; }}
    /* Trash-can Delete. Only appears in edit mode, and reads as destructive
       (red text, red-tinted hover) so it can't be mistaken for a save action. */
    .qa-del {{
      display: inline-flex; align-items: center; gap: 6px;
      font-family: var(--ab-sans); font-size: 0.78rem; font-weight: 700;
      letter-spacing: 0.04em; text-transform: uppercase;
      padding: 7px 12px; border-radius: 999px; cursor: pointer;
      border: 1px solid var(--ab-rule-strong); background: #fff; color: var(--ab-red, #b91c1c);
      transition: background 0.15s, border-color 0.15s, color 0.15s;
    }}
    /* An explicit `display` beats the [hidden] attribute's UA style, so the
       hidden state has to be spelled out or DELETE shows outside edit mode. */
    .qa-del[hidden] {{ display: none; }}
    .qa-del svg {{ width: 15px; height: 15px; }}
    .qa-del:hover, .qa-del:focus-visible {{ background: var(--ab-red, #b91c1c); border-color: var(--ab-red, #b91c1c); color: #fff; }}
    .qa-del:disabled {{ opacity: 0.5; cursor: wait; }}
    .modal-close {{
      flex-shrink: 0;
      width: 34px; height: 34px; border: none; background: var(--ab-bg-3);
      border-radius: 50%; cursor: pointer; font-size: 1.4rem; line-height: 1;
      color: var(--ab-fg-2); transition: background 0.15s, color 0.15s;
    }}
    .modal-close:hover {{ background: var(--ab-fg); color: #fff; }}
    .modal-head {{ border-bottom: 1px solid var(--ab-rule); padding-bottom: 16px; margin-bottom: 18px; }}
    .modal-badges {{ padding-right: 150px; }}  /* clear the top-right Edit + close toolbar */
    .modal-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
    .modal-badges .badge {{ position: static; }}
    /* Most events now render NO top label at all â€” don't leave its margin behind. */
    .modal-badges:empty {{ margin-bottom: 0; }}
    /* Date now sits LAST, under the city â€” so it carries no bottom margin. */
    .modal-date {{
      font-family: var(--ab-mono); font-size: 0.82rem; color: var(--ab-fg-3);
      margin: 0; letter-spacing: 0.02em;
    }}
    .modal-title {{
      font-family: var(--ab-sans); font-size: 1.55rem; font-weight: 800;
      line-height: 1.2; letter-spacing: -0.02em; margin: 0 0 6px; color: var(--ab-fg);
    }}
    /* Modal heading doubles as the website link â€” underlined, inherits 800 weight. */
    .modal-title-link {{
      color: inherit; text-decoration: underline; text-decoration-thickness: 2px;
      text-underline-offset: 3px; text-decoration-color: var(--ab-rule-strong);
      transition: color 0.15s, text-decoration-color 0.15s;
    }}
    .modal-title-link:hover, .modal-title-link:focus-visible {{
      color: var(--ab-blue); text-decoration-color: var(--ab-blue);
    }}
    /* City sits between the title and the date â€” a hair of space either side so
       the two read as one block of qualifiers under the name. */
    .modal-loc {{ font-size: 0.92rem; color: var(--ab-fg-2); margin: 0 0 3px; }}
    .modal-loc .event-region {{ color: var(--ab-fg); font-weight: 600; }}
    .modal-body {{ display: flex; flex-direction: column; gap: 16px; }}
    .modal-field {{ display: flex; flex-direction: column; gap: 4px; }}
    /* Field labels in Details (NOTES, ATTENDEES, ARCTICBLUE SPEAKER, â€¦) â€” bold
       and a step darker so each section is findable when scanning (Angela). */
    .modal-field .k {{
      font-family: var(--ab-mono); font-size: 0.64rem; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--ab-fg-2); font-weight: 700;
    }}
    .modal-field .v {{ font-size: 0.92rem; color: var(--ab-fg); line-height: 1.55; white-space: pre-wrap; }}
    /* Runners-up from the contact lookup â€” who else is worth a try. */
    .poc-alts {{ display: flex; flex-direction: column; gap: 6px; }}
    .poc-alt {{
      display: flex; align-items: center; gap: 10px;
      padding: 7px 10px; border: 1px solid var(--ab-rule); border-radius: 8px;
      background: var(--ab-bg-2);
    }}
    .poc-alt-main {{ display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1; }}
    .poc-alt-name {{ font-family: var(--ab-sans); font-size: 0.86rem; font-weight: 650; color: var(--ab-fg); }}
    .poc-alt-title {{ font-size: 0.76rem; color: var(--ab-fg-3); }}
    .poc-alt-mail {{ font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-fg-3); word-break: break-all; }}
    .poc-alt-use {{ flex: 0 0 auto; }}
    .poc-more {{ margin-top: 8px; align-self: flex-start; }}
    .modal-field .v a {{ color: var(--ab-blue); }}
    .modal-fresh {{ font-style: italic; color: var(--ab-fg-3); font-size: 0.82rem; margin: 14px 0 0; }}
    .modal-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px 22px; }}
    .modal-actions {{
      margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--ab-rule);
      display: flex; flex-wrap: wrap; gap: 10px;
    }}
    .modal-visit {{
      display: inline-flex; align-items: center; gap: 7px;
      background: var(--ab-blue); color: #fff; text-decoration: none;
      font-family: var(--ab-sans); font-weight: 600; font-size: 0.9rem;
      padding: 10px 16px; border-radius: 5px; transition: background 0.15s;
    }}
    .modal-visit:hover {{ background: #1f5fa3; }}
    .modal-nolink {{
      font-family: var(--ab-mono); font-size: 0.74rem; color: var(--ab-fg-3);
      align-self: center;
    }}
    /* Editable modal â€” one-tap quick-action bar at the top of the body. */
    .modal-quickbar {{
      display: flex; flex-direction: column; align-items: stretch;
      gap: 12px; margin: 0 0 20px; padding-bottom: 16px;
      border-bottom: 1px solid var(--ab-rule);
    }}
    .qa-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .modal-quickbar .qa {{
      display: inline-flex; align-items: center; min-height: 34px;
      font-family: var(--ab-sans); font-size: 0.82rem; font-weight: 600;
      padding: 0 12px; border-radius: 999px; cursor: pointer; white-space: nowrap;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); transition: all 0.12s;
    }}
    /* Status pills sit on one line; scroll horizontally rather than wrap if a
       narrow modal can't fit them all. */
    /* Status pills fit one line when they can; Angela's extra "Should Attend"
       simply wraps to the next line rather than being cut off / scrolling. */
    .qa-row--status {{ flex-wrap: wrap; gap: 6px; }}
    .modal-quickbar .qa:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .modal-quickbar .qa-static, .modal-quickbar .qa-static:hover {{
      cursor: default; border-color: var(--ab-rule-strong);
    }}
    .modal-quickbar .qa-static.on, .modal-quickbar .qa-static.on:hover {{ cursor: default; }}
    .modal-quickbar .qa.on {{
      background: #166534; color: #fff; border-color: #166534;
    }}
    /* Rejected-to-speak is a negative outcome â€” reads red when set. */
    .modal-quickbar .qa-neg.on {{ background: #b91c1c; border-color: #b91c1c; }}
    /* Primary edit affordance â€” top-right of the modal header, same spot always. */
    /* Edit â€” the primary action, solid ArcticBlue. */
    .qa-edit {{
      display: inline-flex; align-items: center; gap: 7px; min-height: 36px;
      font-family: var(--ab-sans); font-size: 0.85rem; font-weight: 600;
      padding: 0 16px; border-radius: 9px; cursor: pointer; white-space: nowrap;
      border: 1px solid #1fa0dc; background: #1fa0dc; color: #fff;
      box-shadow: 0 1px 2px rgba(31,160,220,0.28);
      transition: background 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease, transform 0.06s ease;
    }}
    .qa-edit:hover {{ background: #1488bf; border-color: #1488bf; }}
    .qa-edit:active {{ transform: translateY(1px); }}
    .qa-edit.on {{ background: #0f7298; border-color: #0f7298; box-shadow: none; }}
    .qa-edit-ic {{ font-size: 0.95em; line-height: 1; }}
    /* Enrich â€” soft purple "research" accent (AI = purple across the app);
       a clear secondary to the solid-blue Edit primary. */
    .qa-enrich {{ background: #f7f3ff; color: #7c3aed; border-color: #ddd6fe; box-shadow: none; }}
    .qa-enrich:hover {{ background: #7c3aed; color: #fff; border-color: #7c3aed; }}
    .qa-enrich[aria-busy] {{ opacity: 0.65; cursor: default; }}
    .modal-enrich-note {{
      font-family: var(--ab-sans); font-size: 0.85rem; padding: 8px 12px;
      border-radius: 8px; margin: 0 0 14px; background: var(--ab-bg-3); color: var(--ab-fg-2);
    }}
    .modal-enrich-note.ok {{ background: rgba(31,160,90,0.12); color: #1a8c54; font-weight: 600; }}
    .modal-quickbar .qa[data-qa="saved"].on {{ background: var(--ab-blue); border-color: var(--ab-blue); }}
    .modal-quickbar .qa[data-qa="archive"].on {{ background: var(--ab-fg-3); border-color: var(--ab-fg-3); }}
    .modal-quickbar .qa[data-qa="go"].on {{ background: #1a8c54; border-color: #1a8c54; }}
    .peek-clash {{
      font-size: 0.82rem; font-weight: 500; color: #9a3412;
      background: none; border: 0; border-left: 2px solid #f59e0b; border-radius: 0;
      padding: 1px 0 1px 9px; margin-bottom: 11px;
    }}
    /* â”€â”€ Follow-up log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
       A timeline, not a spreadsheet row: state up top, entries down a rule,
       each one saying whether it was the first contact or a chase. */
    .fu-state {{
      display: inline-flex; align-items: center; gap: 7px;
      font-family: var(--ab-sans); font-size: 0.84rem; font-weight: 600;
      padding: 6px 12px; border-radius: 8px; margin-bottom: 12px;
      background: var(--ab-bg-2); color: var(--ab-fg-2);
    }}
    .fu-state::before {{
      content: ''; width: 7px; height: 7px; border-radius: 50%;
      background: var(--ab-fg-3); flex: 0 0 auto;
    }}
    .fu-state.fu-due {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }}
    .fu-state.fu-due::before {{
      content: '\u23f3';                       /* hourglass with flowing sand */
      width: auto; height: auto; border-radius: 0; background: none;
      font-size: 0.95rem; line-height: 1;
    }}
    .fu-state.fu-ok {{ background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }}
    .fu-state.fu-ok::before {{ background: #22c55e; }}
    .fu-state.fu-hold::before {{ background: #94a3b8; }}
    .fu-state.fu-closed {{ color: var(--ab-fg-3); }}
    .fu-state.fu-closed::before {{ background: var(--ab-rule-strong); }}
    /* Rejected â€” same red as the card's status dot, so "they passed" reads the
       same wherever it appears. */
    .modal-note {{ color: var(--ab-fg-3); font-size: 0.94em; }}
    /* Interested + Archive in the modal header â€” the same star and struck
       eye the card face uses, so both surfaces read the same. */
    /* Beside the event name, revealed on hover â€” the card face's behaviour. */
    /* ALWAYS VISIBLE. These were opacity:0 until you hovered the event NAME,
       copied from the card face where hiding controls until hover keeps a dense
       grid calm. A pop-up you deliberately opened is the opposite situation:
       Hurley reported "when I click hide within the event card details, it
       doesn't work", and the screenshot showed why â€” the header offered Enrich,
       Edit and âœ• and nothing else, because the star and the eye were invisible
       until the pointer happened to cross the title (Hurley 2026-08-05). */
    .mt-acts {{
      display: inline-flex; align-items: center; gap: 2px; margin-left: 8px;
      vertical-align: middle; opacity: 1;
    }}
    .mt-ico {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 26px; height: 26px; padding: 0; border: 0; border-radius: 7px;
      background: none; color: var(--ab-fg-3); cursor: pointer;
    }}
    .mt-ico svg {{ width: 15px; height: 15px; display: block; }}
    .mt-ico:hover {{ color: var(--ab-blue); background: var(--ab-bg-2); }}
    .mt-ico.is-on {{ color: var(--ab-blue); }}
    /* Archive (the struck-through eye) reads as a removal, so it carries the
       same red as every other "this is off / closed" mark (Hurley 2026-07-30).
       Listed after .is-on so an archived event stays red rather than going blue. */
    .mt-ico[data-qa="archive"],
    .mt-ico[data-qa="archive"].is-on {{ color: #b91c1c; }}
    .mt-ico[data-qa="archive"]:hover {{ color: #991b1b; background: rgba(185, 28, 28, 0.10); }}
    .mh-ico {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 30px; height: 30px; margin-right: 4px; padding: 0;
      border: 1px solid var(--ab-rule-strong); border-radius: 8px;
      background: var(--ab-bg); color: var(--ab-fg-3); cursor: pointer;
    }}
    .mh-ico svg {{ width: 16px; height: 16px; display: block; }}
    .mh-ico:hover {{ border-color: var(--ab-blue); color: var(--ab-blue); }}
    .mh-ico.is-on {{ border-color: var(--ab-blue); color: var(--ab-blue); background: rgba(39,115,194,0.08); }}
    .me-apply {{ margin: 4px 0 18px; }}
    /* "Also from this organiser" â€” the umbrella's members, or the family a
       member belongs to. Rows, not buttons: it's navigation, not an action. */
    .sib-list {{ display: flex; flex-direction: column; }}
    .sib-row {{
      display: flex; align-items: baseline; gap: 10px; width: 100%;
      text-align: left; background: none; border: 0; cursor: pointer;
      padding: 7px 0; border-bottom: 1px solid var(--ab-rule);
      font-family: var(--ab-sans); color: var(--ab-fg);
    }}
    .sib-row:last-of-type {{ border-bottom: 0; }}
    .sib-row:hover .sib-name {{ color: var(--ab-blue); text-decoration: underline; }}
    .sib-name {{ font-size: 0.9rem; font-weight: 600; }}
    .sib-when {{
      margin-left: auto; white-space: nowrap;
      font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-fg-3);
    }}
    /* Who the contact is, under their name. Quiet â€” it's context, not a label. */
    .poc-note {{
      display: block; margin-top: 3px; font-size: 0.82rem; line-height: 1.45;
      color: var(--ab-fg-2); font-style: italic;
    }}
    .sib-line {{ display: flex; align-items: center; gap: 4px; border-bottom: 1px solid var(--ab-rule); }}
    .sib-line:last-of-type {{ border-bottom: 0; }}
    .sib-line .sib-row {{ border-bottom: 0; flex: 1 1 auto; min-width: 0; }}
    .sib-list {{ max-height: 340px; overflow-y: auto; }}
    /* Unlink: hover-revealed, same restraint as the archive X on a card. */
    .sib-unlink {{
      flex: none; width: 22px; height: 22px; padding: 0; border: 0; border-radius: 6px;
      background: none; color: var(--ab-fg-3); cursor: pointer; font-size: 1rem; line-height: 1;
      opacity: 0; transition: opacity 130ms;
    }}
    .sib-line:hover .sib-unlink, .sib-unlink:focus-visible {{ opacity: 1; }}
    .sib-unlink:hover {{ background: #fee2e2; color: #991b1b; }}
    @media (hover: none) {{ .sib-unlink {{ opacity: 1; }} }}
    .sib-more {{ margin: 7px 0 0; font-size: 0.8rem; color: var(--ab-fg-3); }}
    /* Angela's organiser-linking controls under the sibling list. */
    .sib-add {{ display: flex; flex-direction: column; gap: 6px; margin-top: 10px; align-items: flex-start; }}
    .sib-addwrap {{ position: relative; display: inline-block; }}
    .sib-addwrap[hidden] {{ display: none; }}
    .sib-caret {{ margin-left: 5px; font-size: 0.7em; opacity: 0.7; }}
    .sib-menu {{
      position: absolute; top: calc(100% + 5px); left: 0; z-index: 30;
      min-width: 262px; max-width: min(300px, calc(100vw - 24px)); padding: 5px;
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 10px; box-shadow: 0 10px 26px rgba(15, 23, 42, 0.14);
      display: flex; flex-direction: column; gap: 2px;
    }}
    .sib-menu[hidden] {{ display: none; }}
    .sib-menu-item {{
      width: 100%; padding: 8px 10px; border: 0; border-radius: 7px;
      background: transparent; cursor: pointer; text-align: left;
      font-family: var(--ab-sans); font-size: 0.82rem; color: var(--ab-fg-2);
    }}
    .sib-menu-item strong {{ color: var(--ab-fg); }}
    .sib-menu-item:hover {{ background: var(--ab-bg-3); }}
    .sib-results {{ display: flex; flex-direction: column; max-height: 220px; overflow-y: auto; margin: 6px 0 2px; }}
    .sib-hit {{
      display: flex; align-items: baseline; gap: 8px; width: 100%; text-align: left;
      background: none; border: 0; border-bottom: 1px solid var(--ab-rule);
      padding: 7px 2px; cursor: pointer; font-family: var(--ab-sans); color: var(--ab-fg);
    }}
    .sib-hit:hover {{ background: var(--ab-bg-2); }}
    .sib-hit-name {{ font-size: 0.88rem; font-weight: 600; }}
    .sib-hit-meta {{ margin-left: auto; white-space: nowrap; font-family: var(--ab-mono); font-size: 0.7rem; color: var(--ab-fg-3); }}
    .sib-hit-none {{ font-size: 0.85rem; color: var(--ab-fg-3); padding: 8px 2px; }}
    .fu-state.fu-rejected {{ color: #b91c1c; }}
    .fu-state.fu-rejected::before {{ background: #b91c1c; }}
    .fu-state.fu-none {{ font-weight: 500; color: var(--ab-fg-3); }}
    .fu-log {{ list-style: none; margin: 0 0 12px; padding: 0; }}
    .fu-log li {{
      position: relative; display: flex; flex-wrap: wrap; align-items: baseline;
      gap: 3px 9px; padding: 9px 0 9px 15px; border-left: 2px solid var(--ab-rule);
    }}
    /* One dot per entry; the newest picked out so "where are we" reads at a glance. */
    .fu-log li::before {{
      content: ''; position: absolute; left: -5px; top: 14px;
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--ab-bg); border: 2px solid var(--ab-rule-strong);
    }}
    /* The newest entry is filled; its colour IS the status, so a single row
       carries the same green/red signal the badge used to (Hurley 2026-07-30). */
    .fu-log li:last-child::before {{ border-color: var(--ab-blue); background: var(--ab-blue); }}
    .fu-log--ok  li:last-child::before {{ border-color: #15803d; background: #15803d; }}
    .fu-log--due li:last-child::before {{ border-color: #b91c1c; background: #b91c1c; }}
    .fu-log--hold li:last-child::before,
    .fu-log--closed li:last-child::before {{ border-color: #94a3b8; background: #94a3b8; }}
    .fu-inherited .fu-note {{ font-style: italic; color: var(--ab-fg-3); }}
    .fu-when {{ font-family: var(--ab-mono); font-size: 0.76rem; color: var(--ab-fg); font-weight: 700; }}
    .fu-kind {{
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 700;
      letter-spacing: 0.07em; text-transform: uppercase; color: var(--ab-fg-3);
    }}
    .fu-by {{ font-size: 0.76rem; color: var(--ab-fg-3); }}
    .fu-note {{ flex: 1 1 100%; font-size: 0.87rem; color: var(--ab-fg-2); line-height: 1.45; }}
    .fu-edited {{
      flex: 1 1 100%; font-family: var(--ab-mono); font-size: 0.62rem;
      color: var(--ab-fg-3); font-style: italic;
    }}
    /* Edit / delete stay out of the way until you're on the row. */
    .fu-acts {{ margin-left: auto; display: flex; gap: 9px; opacity: 0; transition: opacity 120ms; }}
    .fu-log li:hover .fu-acts, .fu-log li:focus-within .fu-acts {{ opacity: 1; }}
    @media (hover: none) {{ .fu-acts {{ opacity: 1; }} }}
    .fu-act {{
      display: inline-flex; align-items: center; justify-content: center;
      color: var(--ab-fg-3); background: none; border: 0;
      padding: 2px; border-radius: 5px; cursor: pointer; line-height: 0;
    }}
    .fu-act svg {{ width: 14px; height: 14px; display: block; }}
    .fu-act:hover {{ color: var(--ab-blue); background: var(--ab-bg-2); }}
    .fu-act-del:hover {{ color: var(--ab-red); background: var(--ab-bg-2); }}
    /* â”€â”€ Shared inline form â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
       ONE look for every "add something" in the tool. Nothing is typed into
       a browser prompt() any more: those float at the top of the window,
       detached from what they're about, and look nothing like the app
       (Hurley 2026-07-30). The pattern is always: a quiet add button, which
       swaps in place for a field + Save/Cancel. */
    .ab-addbtn {{
      display: inline-flex; align-items: center; gap: 6px;
      /* The modal section is a flex column, which blockifies inline-flex and
         stretches the button edge-to-edge â€” pin it to its own content. */
      align-self: flex-start; width: fit-content;
      font-family: var(--ab-sans); font-size: 0.82rem; font-weight: 600;
      color: var(--ab-fg-2); background: var(--ab-bg-2);
      border: 1px solid var(--ab-rule-strong); border-radius: 9px;
      padding: 7px 14px; cursor: pointer;
      transition: border-color 120ms, color 120ms, background 120ms;
    }}
    .ab-addbtn:hover {{ border-color: var(--ab-blue); color: var(--ab-blue); background: var(--ab-bg); }}
    .ab-addbtn[hidden] {{ display: none; }}
    .ab-addbtn .ab-addbtn-ic {{ font-size: 1rem; line-height: 1; font-weight: 400; }}
    .ab-form {{ margin: 2px 0 12px; }}
    .ab-input {{
      display: block; width: 100%; box-sizing: border-box;
      padding: 9px 12px; font: inherit; font-size: 0.87rem; line-height: 1.45;
      border: 1px solid var(--ab-rule-strong); border-radius: 9px;
      background: var(--ab-bg); color: var(--ab-fg); resize: vertical;
    }}
    .ab-input::placeholder {{ color: var(--ab-fg-3); }}
    .ab-input:focus {{
      border-color: var(--ab-blue); outline: none;
      box-shadow: 0 0 0 3px rgba(39,115,194,0.12);
    }}
    .ab-input + .ab-input {{ margin-top: 7px; }}
    /* The row is a wrapping flex line, so an editor dropped into it becomes a
       flex ITEM and gets squeezed into whatever space is left â€” a two-inch
       textarea beside the date (Hurley 2026-07-30). Force it onto its own
       full-width line so you edit at the width you read at. */
    .fu-log li .ab-form {{ flex: 1 1 100%; width: 100%; margin: 8px 0 2px; }}
    .fu-log li .ab-form textarea {{ min-height: 62px; }}
    .fu-when-row {{ display: flex; align-items: center; gap: 9px; margin-bottom: 7px; }}
    .fu-when-lab {{
      font-family: var(--ab-mono); font-size: 0.62rem; font-weight: 700;
      letter-spacing: 0.07em; text-transform: uppercase; color: var(--ab-fg-3);
    }}
    .ab-input-date {{ width: auto; padding: 6px 10px; font-size: 0.82rem; }}
    .ab-form-actions {{ display: flex; align-items: center; gap: 8px; margin-top: 8px; }}
    .ab-btn-primary, .ab-btn-ghost {{
      font-family: var(--ab-sans); font-size: 0.82rem; font-weight: 600;
      border-radius: 9px; padding: 7px 14px; cursor: pointer; white-space: nowrap;
    }}
    .ab-btn-primary {{ border: 1px solid var(--ab-blue); background: var(--ab-blue); color: #fff; }}
    .ab-btn-primary:hover {{ filter: brightness(1.08); }}
    .ab-btn-primary[disabled] {{ opacity: 0.45; cursor: default; filter: none; }}
    .ab-btn-ghost {{ border: 1px solid transparent; background: none; color: var(--ab-fg-3); }}
    .ab-btn-ghost:hover {{ color: var(--ab-fg); }}
    .ab-btn-outline {{
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-2);
    }}
    .ab-btn-outline:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); background: var(--ab-bg-2); }}
    .ab-form-hint {{
      margin-left: auto; font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3);
    }}
    .ab-btn-danger {{ border-color: var(--ab-red); background: var(--ab-red); color: #fff; }}
    /* Event picker inside the conflict form â€” the same list-of-hits idea the
       rest of the tool uses, instead of "type a number 1-9" in a prompt. */
    .cf-hits {{
      margin-top: 7px; border: 1px solid var(--ab-rule); border-radius: 9px;
      overflow: hidden; background: var(--ab-bg);
    }}
    .cf-hits:empty {{ display: none; }}
    .cf-hit {{
      display: block; width: 100%; box-sizing: border-box; text-align: left;
      font-family: var(--ab-sans); font-size: 0.84rem; color: var(--ab-fg);
      padding: 8px 12px; background: none; border: 0;
      border-bottom: 1px solid var(--ab-rule); cursor: pointer;
    }}
    .cf-hit:last-child {{ border-bottom: 0; }}
    .cf-hit:hover, .cf-hit:focus {{ background: var(--ab-bg-2); outline: none; }}
    .cf-hit-when {{ margin-left: 7px; font-family: var(--ab-mono); font-size: 0.7rem; color: var(--ab-fg-3); }}
    .cf-hit-none {{ padding: 8px 12px; font-size: 0.84rem; color: var(--ab-fg-3); }}
    /* Matches .fu-act â€” one look for "quiet action on a row". */
    .cf-edit {{
      font-family: var(--ab-sans); font-size: 0.72rem; color: var(--ab-fg-3);
      background: none; border: 0; padding: 0; cursor: pointer; text-decoration: underline;
    }}
    .cf-edit:hover {{ color: var(--ab-blue); }}
    /* Card-face conflict warning. NOT a pill and NOT bordered â€” a rounded
       chip read as a button people expected to click (Hurley 2026-07-30). It's
       a warning LINE: amber rule down the left, no background, no border. */
    .ops-clash {{
      display: flex; align-items: flex-start; gap: 6px;
      font-family: var(--ab-sans); font-size: 0.76rem; font-weight: 500;
      color: #9a3412; background: none; border: 0;
      border-left: 2px solid #f59e0b; border-radius: 0;
      padding: 1px 0 1px 8px; margin-top: 7px; cursor: default;
    }}
    /* â”€â”€ Hover peek: conversation + notes without opening the card â”€â”€â”€â”€â”€â”€ */
    .card-peek {{
      position: fixed; z-index: 900; width: 340px; max-width: 92vw;
      display: none; pointer-events: none;   /* read-only: nothing to cross */
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 11px; padding: 12px 13px;
      box-shadow: 0 14px 38px rgba(0,0,0,0.17);
    }}
    .card-peek.on {{ display: block; }}
    .peek-sec + .peek-sec {{ margin-top: 11px; padding-top: 10px; border-top: 1px solid var(--ab-rule); }}
    .peek-h {{
      display: block; font-family: var(--ab-mono); font-size: 0.58rem; font-weight: 700;
      letter-spacing: 0.09em; text-transform: uppercase; color: var(--ab-fg-3); margin-bottom: 6px;
    }}
    .peek-msg + .peek-msg {{ margin-top: 7px; }}
    .peek-who {{ font-size: 0.82rem; font-weight: 650; color: var(--ab-fg); }}
    .peek-when {{ font-family: var(--ab-mono); font-size: 0.62rem; color: var(--ab-fg-3); margin-left: 6px; }}
    .peek-body {{
      font-size: 0.86rem; color: var(--ab-fg-2); line-height: 1.42; margin-top: 1px;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }}
    .peek-more {{ font-size: 0.74rem; color: var(--ab-fg-3); margin-top: 5px; }}
    /* Notes cap at FOUR lines â€” some are very long, and the rest is one click
       away in the card itself (Hurley 2026-07-30). */
    .peek-notes {{
      font-size: 0.86rem; color: var(--ab-fg); line-height: 1.45; white-space: pre-wrap;
      display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
    }}
    .peek-cta {{
      margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--ab-rule);
      font-family: var(--ab-mono); font-size: 0.6rem; letter-spacing: 0.05em;
      text-transform: uppercase; color: var(--ab-fg-3);
    }}
    /* Touch has no hover â€” never show it there. */
    @media (hover: none) {{ .card-peek {{ display: none !important; }} }}

    /* Should-Attend name picker â€” hover (or focus) the button to choose who
       it's for. Sits above the quickbar so it can't be clipped by the row. */
    .qa-sa-wrap {{ position: relative; display: inline-flex; }}
    /* Same type as the route pills beside it. It sat a size larger and read
       as a heading for the row rather than one more button (Hurley). */
    .modal-quickbar .qa-sa-btn {{
      min-height: 0; font-size: 0.73rem; font-weight: 600; padding: 5px 9px;
    }}
    .qa-sa-menu {{
      position: absolute; top: 100%; left: 0; z-index: 40;
      display: none; flex-direction: column; gap: 2px; min-width: 178px;
      margin-top: 8px;
      padding: 7px; background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 9px; box-shadow: 0 10px 26px rgba(0,0,0,0.16);
    }}
    /* Bridge the 8px gap between button and menu. Without it, moving the mouse
       down to pick a name left .qa-sa-wrap, :hover dropped, and the menu closed
       before the click landed (Hurley 2026-07-30). The bridge is part of the
       menu, so the pointer never leaves the hover target. */
    .qa-sa-menu::before {{
      content: ''; position: absolute; left: 0; right: 0; top: -10px; height: 10px;
    }}
    .qa-sa-wrap:hover .qa-sa-menu,
    .qa-sa-wrap:focus-within .qa-sa-menu,
    .qa-sa-wrap.is-open .qa-sa-menu {{ display: flex; }}
    /* Clicking the button PINS the menu open, so it doesn't depend on keeping
       the pointer inside a small target at all. */
    .qa-sa-wrap.is-open > .qa {{ border-color: var(--ab-blue); }}
    .sa-pick-team {{ margin-top: 3px; padding-top: 7px; border-top: 1px solid var(--ab-rule); }}
    .sa-menu-h {{
      font-family: var(--ab-mono); font-size: 0.58rem; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--ab-fg-3); padding: 1px 5px 4px;
    }}
    .sa-pick {{
      text-align: left; font-family: var(--ab-sans); font-size: 0.86rem;
      padding: 6px 9px; border-radius: 6px; cursor: pointer;
      border: 1px solid transparent; background: none; color: var(--ab-fg);
    }}
    .sa-pick:hover {{ background: var(--ab-bg-3); }}
    .sa-pick.on {{ color: var(--ab-blue); font-weight: 650; }}
    .qa-row-label {{
      display: inline-flex; align-items: center; font-family: var(--ab-mono);
      font-size: 0.68rem; letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--ab-fg-3); margin-right: 2px;
    }}
    .modal-quickbar .qa[data-qa="interested"].on {{ background: var(--ab-blue); border-color: var(--ab-blue); }}
    .qa-int-summary {{ font-family: var(--ab-sans); font-size: 0.85rem; color: var(--ab-fg-2); margin-left: 4px; }}
    .qa-int-summary.qa-int-empty {{ color: var(--ab-fg-3); font-style: italic; }}
    .modal-edit-btn {{
      display: inline-flex; align-items: center; gap: 7px;
      font-family: var(--ab-sans); font-weight: 600; font-size: 0.9rem;
      padding: 10px 16px; border-radius: 5px; cursor: pointer;
      background: var(--ab-bg-3); color: var(--ab-fg); border: 1px solid var(--ab-rule-strong);
    }}
    .modal-edit-btn:hover {{ background: var(--ab-bg-2); border-color: var(--ab-fg-3); }}
    /* Inline editor inside the pop-up â€” change fields right here. */
    .modal-edit {{
      margin: 0 0 20px; padding: 14px 16px; border-radius: 10px;
      background: var(--ab-bg-2); border: 1px solid var(--ab-rule);
    }}
    .me-edithead {{
      font-family: var(--ab-mono); font-size: 0.68rem;
      letter-spacing: 0.08em; text-transform: uppercase; color: var(--ab-fg-3);
      margin-bottom: 12px;
    }}
    .me-grid {{ display: grid; gap: 11px; }}
    .me-row {{ display: grid; grid-template-columns: 130px 1fr; gap: 10px; align-items: center; }}
    .me-key {{
      font-family: var(--ab-mono); font-size: 0.68rem; letter-spacing: 0.06em;
      text-transform: uppercase; color: var(--ab-fg-3); padding-top: 2px; align-self: start;
    }}
    .me-row input, .me-row select, .me-row textarea {{
      width: 100%; font-family: var(--ab-sans); font-size: 0.9rem;
      padding: 8px 10px; border: 1px solid var(--ab-rule-strong); border-radius: 6px;
      background: var(--ab-bg); color: var(--ab-fg); box-sizing: border-box;
    }}
    .me-row textarea {{ resize: vertical; line-height: 1.45; }}
    .me-row input:focus, .me-row select:focus, .me-row textarea:focus {{
      outline: none; border-color: var(--ab-fg); box-shadow: 0 0 0 2px var(--ab-bg-3);
    }}
    .me-stages {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .me-stage {{
      font-family: var(--ab-sans); font-size: 0.78rem; font-weight: 600;
      padding: 5px 11px; border-radius: 999px; cursor: pointer;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-2);
    }}
    .me-stage:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .me-stage.on {{ background: #166534; color: #fff; border-color: #166534; }}
    /* Edit form controls â€” full-width, sit right under their .modal-field label
       so the form reads like the read-only view. */
    .modal-editform .modal-field {{ margin-bottom: 14px; }}
    .me-input {{
      width: 100%; box-sizing: border-box; font-family: var(--ab-sans); font-size: 0.92rem;
      padding: 8px 11px; border: 1px solid var(--ab-rule-strong); border-radius: 7px;
      background: var(--ab-bg); color: var(--ab-fg); line-height: 1.5;
    }}
    textarea.me-input {{ resize: vertical; }}
    .me-input:focus {{ outline: none; border-color: var(--ab-fg); box-shadow: 0 0 0 2px var(--ab-bg-3); }}
    /* Zone dividers, used by BOTH the Details read view and the edit form, so
       the two read as the same document (Angela). A heavier 2px rule â€” the old
       hairline didn't separate the groups strongly enough to scan by. */
    .me-sec {{ margin-top: 24px; padding-top: 16px; border-top: 2px solid var(--ab-rule-strong); }}
    .me-sec:first-of-type {{ margin-top: 0; padding-top: 0; border-top: 0; }}
    /* Read-view zones stack their fields the way .modal-body does. */
    .modal-view .me-sec {{ display: flex; flex-direction: column; gap: 16px; }}
    .modal-view .me-sec-h {{ margin-bottom: 0; }}
    /* The zone heading must outrank the field labels inside it â€” it was lighter
       and thinner than them, which read as backwards. Full-strength ink, heavier
       and a touch larger than a .modal-field .k. */
    .me-sec-h {{
      margin: 0 0 12px; font-family: var(--ab-sans); font-size: 0.8rem; font-weight: 700;
      letter-spacing: 0.06em; text-transform: uppercase; color: var(--ab-fg);
    }}
    /* The folded "Rarely used" zone â€” click the heading to reveal. */
    .me-sec-fold > .me-sec-h {{ cursor: pointer; list-style: none; display: flex; align-items: center; gap: 6px; }}
    .me-sec-fold > .me-sec-h::-webkit-details-marker {{ display: none; }}
    .me-sec-fold > .me-sec-h::before {{ content: '\\25b8'; font-size: 0.8rem; transition: transform 0.12s ease; }}
    .me-sec-fold[open] > .me-sec-h::before {{ transform: rotate(90deg); }}
    .me-sec-fold > .me-sec-h:hover {{ color: var(--ab-fg); }}
    /* Delete control for manual events, in the modal's Edit form. */
    .me-danger {{
      margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--ab-rule);
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }}
    .me-delete {{
      font-family: var(--ab-sans); font-weight: 600; font-size: 0.85rem;
      padding: 8px 14px; border-radius: 7px; cursor: pointer;
      background: var(--ab-bg); color: var(--ab-red); border: 1px solid var(--ab-red);
    }}
    .me-delete:hover {{ background: var(--ab-red); color: #fff; }}
    .me-delete:disabled {{ opacity: 0.5; cursor: wait; }}
    .me-danger-note {{ font-size: 0.78rem; color: var(--ab-fg-3); }}
    /* "Interested" picker â€” roster name chips you toggle on. */
    .me-ints {{ display: flex; flex-wrap: wrap; gap: 7px; }}
    .me-int {{
      display: inline-flex; align-items: center; cursor: pointer; user-select: none;
      font-family: var(--ab-sans); font-size: 0.82rem; font-weight: 600;
      padding: 5px 12px; border-radius: 999px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-2);
    }}
    .me-int input {{ position: absolute; opacity: 0; width: 0; height: 0; }}
    .me-int:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .me-int.on {{ background: var(--ab-blue); color: #fff; border-color: var(--ab-blue); }}
    /* "Private event" toggle in the edit form. */
    .me-toggle {{ display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-family: var(--ab-sans); font-size: 0.85rem; color: var(--ab-fg-2); }}
    .me-toggle input {{ width: 15px; height: 15px; accent-color: var(--ab-blue); flex: 0 0 auto; }}
    .badge-private {{ background: #ede9fe; color: #5b21b6; border: 1px solid #ddd6fe; }}
    /* Read-only "interested" chips in the detail view. */
    .int-chip {{
      display: inline-block; margin: 0 6px 4px 0; padding: 3px 10px; border-radius: 999px;
      font-family: var(--ab-sans); font-size: 0.8rem; font-weight: 600;
      background: rgba(39,115,194,0.12); color: var(--ab-blue); border: 1px solid rgba(39,115,194,0.3);
    }}
    .ops-interested {{ color: var(--ab-blue) !important; font-weight: 600; }}
    @media (max-width: 560px) {{
      .me-row {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
    @media (max-width: 560px) {{
      .modal-scroll {{ padding: 58px 20px 22px; }}
      .modal-title {{ font-size: 1.3rem; }}
      .modal-grid {{ grid-template-columns: 1fr; }}
    }}

    /* (The .archive-block / .archive-grid rules styled the retired public
       catalog's past-events disclosure. Removed with the markup â€” they were
       also the last "Show / hide" and "Hide" strings attached to the word
       archive, which now means one thing: an event you archived.) */

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ footer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    footer.foot {{
      margin: 96px 0 0; padding: 32px 0 64px;
      border-top: 1px solid var(--ab-rule);
      display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap;
    }}
    .foot-text {{ color: var(--ab-fg-3); font-size: 0.85rem; margin: 0; }}
    .foot-mono {{ font-family: var(--ab-mono); font-size: 0.78rem; color: var(--ab-fg-3); letter-spacing: 0.04em; }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ tab strip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .tabs {{
      border-bottom: 1px solid var(--ab-rule);
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      position: sticky; top: 65px; z-index: 9;
    }}
    .tabs-inner {{
      max-width: var(--ab-max); margin: 0 auto;
      display: flex; gap: 0; padding: 0 24px;
    }}
    .tab {{
      background: none; border: 0; cursor: pointer;
      font-family: var(--ab-sans);
      font-weight: 600; font-size: 0.95rem;
      color: var(--ab-fg-3);
      padding: 16px 0; margin-right: 28px;
      letter-spacing: -0.01em;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      transition: color 120ms ease, border-color 120ms ease;
    }}
    .tab:hover {{ color: var(--ab-fg-2); }}
    .tab.active {{
      color: var(--ab-fg);
      border-bottom-color: var(--ab-fg);
    }}
    .tab-badge {{
      display: inline-block;
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--ab-fg-3); background: var(--ab-bg-3);
      padding: 2px 6px; border-radius: 999px;
      margin-left: 8px; vertical-align: 1px;
    }}
    .panel[hidden] {{ display: none; }}
    .angela-placeholder {{
      max-width: 640px; margin: 96px auto;
      text-align: center; padding: 64px 32px;
      border: 1px dashed var(--ab-rule-strong); border-radius: 12px;
    }}
    .angela-placeholder h2 {{
      font-family: var(--ab-sans); font-weight: 700;
      font-size: 1.6rem; letter-spacing: -0.02em;
      margin: 0 0 12px;
    }}
    .angela-placeholder p {{
      color: var(--ab-fg-2); line-height: 1.55;
      margin: 0 0 8px;
    }}
    .angela-placeholder .mono {{
      font-family: var(--ab-mono); font-size: 0.78rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      text-transform: uppercase; margin-top: 24px;
    }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ For Angela â€” auth + ops UI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .angela-card {{
      max-width: 480px; margin: 96px auto;
      padding: 40px 36px; text-align: left;
      border: 1px solid var(--ab-rule-strong); border-radius: 12px;
      background: var(--ab-bg);
    }}
    .angela-card h2 {{
      font-family: var(--ab-sans); font-weight: 700;
      font-size: 1.35rem; letter-spacing: -0.02em;
      margin: 0 0 8px;
    }}
    .angela-card .lede {{
      color: var(--ab-fg-2); font-size: 0.98rem; line-height: 1.55;
      margin: 0 0 24px;
    }}
    .angela-card form {{ display: flex; flex-direction: column; gap: 12px; }}
    .angela-card label {{
      font-family: var(--ab-mono); font-size: 0.72rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .angela-card input[type="email"] {{
      font-family: var(--ab-sans); font-size: 1rem;
      padding: 12px 14px; border: 1px solid var(--ab-rule-strong);
      border-radius: 8px; background: var(--ab-bg);
      color: var(--ab-fg); outline: none;
    }}
    .angela-card input[type="email"]:focus {{
      border-color: var(--ab-blue); box-shadow: 0 0 0 3px rgba(39,115,194,0.15);
    }}
    .angela-card button.primary {{
      font-family: var(--ab-sans); font-weight: 600; font-size: 0.95rem;
      padding: 12px 18px; border-radius: 8px; border: 0;
      background: var(--ab-fg); color: var(--ab-bg);
      cursor: pointer; transition: background 120ms ease;
    }}
    .angela-card button.primary:hover {{ background: #262626; }}
    .angela-card button.primary:disabled {{
      background: var(--ab-mute); cursor: not-allowed;
    }}
    .angela-card .mono-foot {{
      font-family: var(--ab-mono); font-size: 0.72rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      text-transform: uppercase; margin-top: 24px;
    }}

    .angela-header {{
      display: flex; justify-content: space-between; align-items: center;
      gap: 16px; padding: 16px 0;
      border-bottom: 1px solid var(--ab-rule);
      margin-bottom: 32px;
    }}
    .angela-header .who {{
      font-family: var(--ab-mono); font-size: 0.78rem;
      color: var(--ab-fg-2); letter-spacing: 0.04em;
    }}
    .angela-header .who strong {{ color: var(--ab-fg); font-weight: 600; }}
    .angela-header .collab-note {{
      font-family: var(--ab-sans); font-size: 0.8rem; color: var(--ab-fg-3);
    }}
    .angela-header button {{
      font-family: var(--ab-mono); font-size: 0.72rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      padding: 8px 14px; border-radius: 6px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); cursor: pointer;
    }}
    .angela-header button:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .angela-header button.inline {{
      border: 0; background: none; padding: 0 0 0 8px; text-transform: none;
      font-size: 0.72rem; color: var(--ab-blue, #1d4ed8); text-decoration: underline;
    }}

    .alert {{
      max-width: 560px; margin: 32px auto;
      padding: 16px 20px; border-radius: 8px;
      font-size: 0.95rem; line-height: 1.5;
      background: var(--ab-bg-3); color: var(--ab-fg-2);
    }}
    .alert.warn {{ background: #fff4e5; color: #7c2d12; }}
    .alert.error {{ background: #fee2e2; color: #991b1b; }}
    /* The save/error toast must follow the user, not sit at the top of the
       panel where it's off-screen when you act on a card further down. */
    #ops-status {{
      position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
      z-index: 1300; margin: 0; max-width: min(560px, calc(100vw - 32px));
      box-shadow: 0 8px 28px rgba(0,0,0,0.20);
    }}
    .alert button.inline {{
      font: inherit; color: inherit;
      background: transparent; border: 0; padding: 0;
      text-decoration: underline; cursor: pointer; margin-left: 6px;
    }}

    /* Ops grid â€” one full-width card per line (was a multi-column tile grid) so
       every card is the same width and its internal labels land in the exact
       same spot, card after card, instead of shifting with each column's size. */
    .ops-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; align-items: start; }}
    .ops-empty {{ grid-column: 1 / -1; text-align: center; padding: 56px 24px; color: var(--ab-fg-2); }}
    .ops-empty-title {{ font-size: 1.05rem; font-weight: 600; color: var(--ab-fg); margin: 0 0 6px; }}
    .ops-empty-sub {{ font-size: 0.9rem; margin: 0 0 16px; }}
    .ops-empty-btn {{
      font-family: var(--ab-sans); font-size: 0.85rem; font-weight: 600;
      padding: 9px 18px; border-radius: 8px; border: 1px solid var(--ab-rule);
      background: var(--ab-bg); color: var(--ab-fg); cursor: pointer;
    }}
    .ops-empty-btn:hover {{ background: var(--ab-bg-3); }}

    /* Month dividers inside the For-Angela ops grid. Mirrors the public
       .month-header but is clickable to collapse/expand that month's cards. */
    .ops-month-header {{
      grid-column: 1 / -1;
      display: flex; align-items: center; gap: 12px;
      margin: 26px 0 4px;
      font-family: var(--ab-mono);
      font-size: 0.74rem; font-weight: 600; letter-spacing: 0.14em;
      text-transform: uppercase; color: var(--ab-fg-2);
      background: transparent; border: 0; width: 100%; text-align: left;
      cursor: pointer; padding: 4px 0;
      transition: color 0.15s;
    }}
    .ops-month-header:hover {{ color: var(--ab-fg); }}
    .ops-month-header:first-child {{ margin-top: 0; }}
    .ops-month-header .mh-caret {{
      display: inline-block; font-size: 0.6rem; line-height: 1;
      transition: transform 0.15s; color: var(--ab-fg-3);
    }}
    .ops-month-header.collapsed .mh-caret {{ transform: rotate(-90deg); }}
    .ops-month-header .mh-count {{
      font-weight: 400; color: var(--ab-fg-3); letter-spacing: 0.08em;
    }}
    .ops-month-header .mh-line {{
      flex: 1; height: 1px; background: var(--ab-rule);
    }}

    /* "Months" hide/show dropdown in the ops filter bar */
    .ops-months {{ position: relative; display: inline-block; }}
    .ops-months-btn {{
      font-family: "Nunito Sans", var(--ab-sans); font-size: 0.86rem; font-weight: 800; letter-spacing: 0.04em;
      text-transform: uppercase; color: var(--ab-fg-2);
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; padding: 10px 13px; cursor: pointer;
      display: inline-flex; align-items: center; gap: 5px;
      transition: background 0.15s, border-color 0.15s, color 0.15s;
    }}
    .ops-months-btn:hover {{ border-color: var(--ab-rule-strong); color: var(--ab-fg); }}
    .ops-months-btn .mb-caret {{ font-size: 0.55rem; color: var(--ab-fg-3); }}
    .ops-months-menu {{
      position: absolute; top: calc(100% + 6px); right: 0; z-index: 40;
      min-width: 220px; max-height: 360px; overflow-y: auto;
      background: var(--ab-bg); border: 1px solid var(--ab-rule);
      border-radius: 8px; padding: 8px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.10);
      display: none;
    }}
    .ops-months-menu.open {{ display: block; }}
    .ops-months-actions {{
      display: flex; gap: 6px; padding: 2px 4px 8px;
      border-bottom: 1px solid var(--ab-rule); margin-bottom: 6px;
    }}
    .ops-months-actions button {{
      flex: 1; font-family: var(--ab-mono); font-size: 0.6rem;
      letter-spacing: 0.05em; text-transform: uppercase;
      color: var(--ab-fg-2); background: var(--ab-bg-3);
      border: 1px solid var(--ab-rule); border-radius: 5px;
      padding: 4px 6px; cursor: pointer; transition: background 0.15s, color 0.15s;
    }}
    .ops-months-actions button:hover {{ background: var(--ab-blue); color: #fff; border-color: var(--ab-blue); }}
    .ops-months-list label {{
      display: flex; align-items: center; gap: 8px;
      padding: 5px 6px; border-radius: 5px; cursor: pointer;
      font-size: 0.8rem; color: var(--ab-fg);
    }}
    .ops-months-list label:hover {{ background: var(--ab-bg-3); }}
    .ops-months-list input {{ accent-color: var(--ab-blue); cursor: pointer; }}
    .ops-months-list .mc-count {{
      margin-left: auto; font-family: var(--ab-mono);
      font-size: 0.66rem; color: var(--ab-fg-3);
    }}
    .ops-card {{
      position: relative;
      padding: 22px;
      border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg); cursor: pointer;
      transition: border-color 120ms ease, box-shadow 120ms ease;
      display: flex; flex-direction: column; height: 100%;
    }}
    /* Whole card is clickable â†’ opens the detail pop-up. Hover lift + focus ring
       signal it; the star / chips / links inside keep their own actions. */
    .ops-card:hover {{ border-color: var(--ab-rule-strong); box-shadow: 0 2px 10px rgba(0,0,0,0.07); }}
    .ops-card:focus-visible {{ outline: 2px solid var(--ab-blue); outline-offset: 2px; }}
    /* Recently added (yellow) â€” lowest-priority outline, so a blue interested /
       should-attend outline below overrides it when both apply. */
    .ops-card.is-recent {{ border-color: #eab308; }}
    .ops-card.is-saved {{ border-color: var(--ab-blue); }}
    /* (.ops-card.is-mine / .modal-card.is-mine retired 2026-08-05 with the
       merged view â€” the per-person "I starred it" outline was the last thing
       making two people's grids differ. The corner star mark names who's
       interested instead. .chat-react.is-mine is unrelated and still live.) */
    .ops-card.is-sa    {{ border-color: var(--ab-blue); }}   /* Angela flagged Should Attend (her exception) */
    /* Hover-only card controls (star + archive/hide): hidden until you hover/focus the card. */
    .ops-hover {{ opacity: 0; pointer-events: none; transition: opacity 120ms ease; }}
    .ops-card:hover .ops-hover, .ops-card:focus-within .ops-hover {{ opacity: 1; pointer-events: auto; }}
    .ops-archive-x {{
      display: inline-flex; align-items: center; justify-content: center;
      cursor: pointer; background: transparent; border: 0; color: var(--ab-red);
      padding: 3px; border-radius: 5px; line-height: 1;
    }}
    .ops-archive-x svg {{ width: 18px; height: 18px; }}
    .ops-archive-x:hover {{ color: var(--ab-red); background: var(--ab-bg-3); }}
    /* Tiny per-card chat indicator ("ðŸ’¬ N"), always visible when there are messages. */
    .chat-count {{ font-family: var(--ab-mono); font-size: 0.58rem; color: var(--ab-fg-3); letter-spacing: 0.02em; align-self: center; white-space: nowrap; }}
    /* Modal "Discussion" thread. */
    /* Sits right after the quickbar, which already supplies the divider line
       (border-bottom) â€” no second border here, or you get a doubled-up gap. */
    .event-chat {{ margin-top: 4px; margin-bottom: 20px; }}
    /* Bold, and a step darker so the weight actually reads at 0.7rem (Hurley). */
    .chat-h {{ font-family: var(--ab-mono); font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ab-fg-2); margin: 0 0 10px; }}
    .chat-list {{ display: flex; flex-direction: column; gap: 8px; max-height: 260px; overflow-y: auto; margin: 0 0 12px; padding-top: 16px; }}
    .chat-empty {{ font-size: 0.85rem; color: var(--ab-fg-3); font-style: italic; margin: 0; }}
    .chat-msg {{ position: relative; background: var(--ab-bg-2); border: 1px solid var(--ab-rule); border-radius: 8px; padding: 8px 10px; }}
    .chat-meta {{ display: flex; gap: 8px; align-items: baseline; margin-bottom: 3px; }}
    .chat-who {{ font-weight: 700; font-size: 0.8rem; color: var(--ab-fg); }}
    .chat-when {{ font-family: var(--ab-mono); font-size: 0.6rem; color: var(--ab-fg-3); }}
    /* Slack-style hover toolbar: add-to-notes Â· ðŸ‘ Â· ðŸ‘Ž Â· delete (own only).
       Floats top-right of the message, revealed on hover / keyboard focus. */
    .chat-actions {{
      position: absolute; top: -14px; right: 8px; display: flex; align-items: center; gap: 1px;
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong); border-radius: 10px;
      padding: 3px 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.10);
      opacity: 0; pointer-events: none; transition: opacity 110ms ease;
    }}
    .chat-msg:hover .chat-actions, .chat-msg:focus-within .chat-actions {{ opacity: 1; pointer-events: auto; }}
    .chat-act {{
      display: inline-flex; align-items: center; justify-content: center;
      min-width: 30px; height: 30px; padding: 0 4px;
      border: 0; background: none; cursor: pointer; font-size: 1.05rem; line-height: 1;
      border-radius: 7px; color: var(--ab-fg-2); overflow: visible;
    }}
    .chat-act:hover {{ background: var(--ab-bg-3); }}
    /* Reaction emojis are the primary affordance â€” render them bigger. */
    .chat-react-btn {{ font-size: 1.28rem; }}
    .chat-react-btn:hover {{ transform: scale(1.12); }}
    /* Divider between reactions and the actions. */
    .chat-act-sep {{ width: 1px; align-self: stretch; margin: 3px 3px; background: var(--ab-rule); }}
    .chat-more {{ font-size: 1.2rem; letter-spacing: 1px; }}
    /* Forward-to-teammate + â‹¯ "More" (delete) popovers â€” fixed-positioned (a
       portal) so they're never clipped by the chat scroll area or covered by the
       message below. Coordinates are set inline from the button's position. */
    .chat-fwd-menu, .chat-more-menu {{
      position: fixed; z-index: 2000; min-width: 150px;   /* above .modal-overlay (1200) */
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong); border-radius: 10px;
      box-shadow: 0 6px 20px rgba(0,0,0,0.18); padding: 5px; display: flex; flex-direction: column;
    }}
    .chat-fwd-head {{ font-family: var(--ab-mono); font-size: 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ab-fg-3); padding: 4px 8px 5px; }}
    .chat-fwd-item, .chat-more-item {{ text-align: left; border: 0; background: none; cursor: pointer; font: inherit; font-size: 0.86rem; color: var(--ab-fg); padding: 7px 9px; border-radius: 6px; }}
    .chat-fwd-item:hover {{ background: var(--ab-bg-3); color: var(--ab-blue); }}
    .chat-more-del {{ color: var(--ab-red); font-weight: 600; }}
    .chat-more-del:hover {{ background: rgba(185,28,28,0.1); }}
    .chat-more-tag {{ font-size: 0.66rem; color: var(--ab-fg-3); font-weight: 400; }}
    .chat-body {{ margin: 0; font-size: 0.9rem; color: var(--ab-fg-2); line-height: 1.45; white-space: pre-wrap; word-break: break-word; }}
    .chat-mention {{ color: var(--ab-blue); font-weight: 600; }}   /* @teammate â€” pings them via "In the last week" */
    /* ðŸ‘/ðŸ‘Ž tallies under a message. */
    .chat-reacts {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
    .chat-react {{
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 0.9rem; color: var(--ab-fg-2);
      background: var(--ab-bg-3); border: 1px solid var(--ab-rule); border-radius: 999px; padding: 2px 9px;
    }}
    /* Who reacted, shown next to the emoji. */
    .chat-react-who {{ font-family: var(--ab-mono); font-size: 0.66rem; font-weight: 600; }}
    .chat-react.is-mine {{ border-color: var(--ab-blue); color: var(--ab-blue); background: rgba(31,160,220,0.10); }}
    .chat-form {{ display: flex; gap: 8px; }}
    .chat-input {{ flex: 1; padding: 9px 12px; border: 1px solid var(--ab-rule-strong); border-radius: 8px; font: inherit; font-size: 0.9rem; }}
    .chat-send {{ padding: 9px 16px; border-radius: 8px; border: 1px solid var(--ab-blue); background: var(--ab-blue); color: #fff; font-weight: 600; cursor: pointer; white-space: nowrap; }}
    .chat-send:hover {{ opacity: 0.9; }}
    /* One row: title, then date Â· place right next to it, then any chips/
       labels (star, urgent, archive, decision, chat count) pushed flush to
       the empty space at the end â€” same row on every card, so everything
       lands in the same spot instead of shifting card to card. */
    .ops-card-head {{
      display: flex; align-items: flex-start; flex-wrap: nowrap;
      column-gap: 10px; margin-bottom: 2px;
    }}
    .ops-card-head .event-name {{ flex: 1 1 auto; min-width: 60px; margin: 0; }}   /* grows so the star/hide/chat cluster pins to the top-right */
    .ops-card-head .ops-chips {{ flex: 0 0 auto; margin-left: auto; align-self: flex-start; }}   /* top-right cluster */
    /* Status mark: always on, never hover-revealed â€” it IS the card's state. */
    .ops-stage-ico {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 20px; height: 20px; margin-right: 2px; vertical-align: middle;
      opacity: 1 !important; pointer-events: none;
    }}
    .ops-stage-ico svg {{ width: 17px; height: 17px; display: block; }}
    .ops-stage-ico {{ gap: 3px; width: auto; min-width: 20px; }}
    /* The interest star carries the initials INSIDE it, so it needs a few more
       pixels than the mic/ticket to stay legible â€” sized for the two-letter
       case (JW / JL / JC); the single-letter ones just sit roomier. */
    /* The three marks are sized so their LETTERS land within a pixel of each
       other on screen (~8px), not so their boxes match â€” a star, a wide ticket
       and a badged mic can't share a box and shouldn't try. The mic is tallest
       because its badge hangs off the corner. */
    .ops-stage-ico.is-star svg {{ width: 24px; height: 24px; }}
    .ops-stage-ico.is-star {{ width: auto; min-width: 24px; height: 24px; }}
    /* The attending ticket carries initials too. It is drawn from a cropped
       viewBox (the art fills only the middle third of a 24-box), so it needs an
       explicit wide-and-short size rather than the shared square one. */
    .ops-stage-ico.is-ticket svg {{ width: 32px; height: 22px; }}
    .ops-stage-ico.is-ticket {{ width: auto; min-width: 32px; height: 28px; }}
    /* A badged mic draws in a 30-unit box instead of 24, so it needs more
       pixels just to hold the mic at its old size â€” and Hurley asked for it a
       bit bigger than that. 26px puts the mic art ~22% up on the plain one and
       gives the two-letter badge real height. */
    .ops-stage-ico.is-mic svg {{ width: 28px; height: 28px; }}
    .ops-stage-ico.is-mic {{ width: auto; min-width: 28px; height: 28px; }}
    /* Lineup rows carry the same marks as the card, on their own line under the
       date so they don't crowd the event name. */
    .qrow-marks {{ display: flex; align-items: center; flex-wrap: wrap; gap: 2px; margin-top: 4px; }}
    /* The pipeline as a ROUTE, not a row of switches. Colours match the corner
       mark exactly: amber = in flight, green = landed, red = closed. */
    .qa-flow {{ display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }}
    .qa-arrow {{ color: var(--ab-fg-3); font-size: 0.8rem; line-height: 1; }}
    .qa-branch {{
      display: inline-flex; align-items: center; gap: 4px;
      padding: 3px 5px; border-radius: 10px;
      background: var(--ab-bg-2); border: 1px dashed var(--ab-rule-strong);
    }}
    .qa-step {{
      display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;
      font-family: var(--ab-sans); font-size: 0.73rem; font-weight: 600;
      padding: 5px 9px; border-radius: 999px; cursor: pointer;
      border: 1px solid var(--ab-rule-strong);
      background: var(--ab-bg); color: var(--ab-fg-2);
      transition: border-color 90ms ease;
    }}
    .qa-step:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .qa-n {{
      margin-left: 3px; font-family: var(--ab-mono); font-size: 0.72em;
      font-weight: 700; opacity: 0.85;
    }}
    /* in flight â€” actually yellow. Darkening the yellow until WHITE text was
       legible is what produced the brownish orange; yellow is a light hue and
       won't carry white. So the fill stays a true yellow and the text goes
       dark instead (#713f12 on #facc15 is 8.6:1). */
    .qa-step.qa-flight.is-on {{ background: #facc15; border-color: #eab308; color: #713f12; }}
    /* landed */
    .qa-step.qa-good.is-on {{ background: #15803d; border-color: #15803d; color: #fff; }}
    /* closed */
    .qa-step.qa-bad.is-on {{ background: #991b1b; border-color: #991b1b; color: #fff; }}
    /* "Followed up" plus its correction control. The "âˆ’" stays out of the way
       until you go near the pill, so the normal path (click to log a chase) is
       the only thing on screen. */
    /* position:relative so the "âˆ’" can be taken OUT of the flow. Keeping it in
       the flow reserved 22px + a gap even while invisible, which showed up as a
       wider space before the second arrow than before the first â€” the route
       looked broken (Hurley 2026-07-31). Absolute costs no layout, so every
       step is evenly spaced whether or not the control exists. */
    /* The follow-up count control: + above, - below, in a stack UNDER the pill.
       Revealed on hover.

       The reason it does not vanish on the way to it: the stack is a DOM CHILD
       of .qa-fu, so hovering it still satisfies .qa-fu:hover even though it is
       positioned outside the parent's box â€” and its padding-top forms an
       invisible bridge across the gap, so there is no dead strip where the
       pointer is over neither. That gap is what made the earlier hover controls
       disappear as you reached for them (Hurley 2026-07-31). */
    .qa-fu {{ display: inline-flex; align-items: center; position: relative; }}
    .qa-fu-ctl {{
      position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
      padding-top: 7px;                 /* the bridge â€” do not turn into margin */
      display: flex; flex-direction: column; gap: 3px;
      opacity: 0; pointer-events: none; transition: opacity 120ms;
      z-index: 6;
    }}
    .qa-fu:hover .qa-fu-ctl,
    .qa-fu:focus-within .qa-fu-ctl {{ opacity: 1; pointer-events: auto; }}
    .qa-fu-btn {{
      box-sizing: border-box; width: 26px; height: 22px; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
      border: 1px solid var(--ab-rule-strong); border-radius: 6px;
      background: var(--ab-bg); color: var(--ab-fg-2); cursor: pointer;
      font-size: 0.95rem; line-height: 1; font-family: var(--ab-sans);
      box-shadow: 0 1px 3px rgba(0,0,0,0.10);
    }}
    .qa-fu-btn.is-add:hover    {{ background: #dcfce7; border-color: #15803d; color: #15803d; }}
    .qa-fu-btn.is-sub:hover:not(:disabled) {{ background: #fee2e2; border-color: #991b1b; color: #991b1b; }}
    .qa-fu-btn:disabled {{ opacity: 0.4; cursor: not-allowed; }}
    .qa-fu-btn:focus-visible {{ outline: 2px solid var(--ab-blue); outline-offset: 1px; }}
    /* Touch has no hover â€” keep it visible there. */
    @media (hover: none) {{ .qa-fu-ctl {{ opacity: 1; pointer-events: auto; }} }}
    /* (Draft-outreach styles removed 2026-08-05 with the feature.) */
    .qa-step.qa-static {{ cursor: default; }}
    .qa-step.qa-static:hover {{ border-color: var(--ab-rule-strong); color: var(--ab-fg-2); }}
    .qa-step.qa-good.qa-static.is-on:hover {{ color: #fff; border-color: #15803d; }}
    /* Team roll-ups: one block per person, their events beneath. */
    .tp-section {{ margin-top: 18px; }}
    .tp-person {{ padding: 8px 0; border-bottom: 1px solid var(--ab-rule); }}
    .tp-person:last-child {{ border-bottom: 0; }}
    .tp-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
    .tp-name {{ font-family: var(--ab-sans); font-size: 0.9rem; font-weight: 700; color: var(--ab-fg); }}
    .tp-count {{
      margin-left: auto; font-family: var(--ab-mono); font-size: 0.7rem;
      color: var(--ab-fg-3);
    }}
    .tp-list {{ display: flex; flex-direction: column; padding-left: 30px; }}
    .tp-row {{
      display: flex; align-items: baseline; gap: 9px; width: 100%; text-align: left;
      background: none; border: 0; padding: 4px 0; cursor: pointer;
      font-family: var(--ab-sans); color: var(--ab-fg);
    }}
    .tp-row:hover .tp-ev {{ color: var(--ab-blue); text-decoration: underline; }}
    .tp-ev {{ font-size: 0.86rem; }}
    .tp-stage {{
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 700;
      letter-spacing: 0.06em; text-transform: uppercase; color: var(--ab-fg-3);
      padding: 1px 6px; border-radius: 999px; background: var(--ab-bg-2);
    }}
    /* Same three colours as the mic, so a row reads the same way a card does. */
    .tp-stage--booked   {{ background: #dcfce7; color: #15803d; }}
    .tp-stage--flight   {{ background: #fef9c3; color: #a16207; }}
    .tp-stage--rejected {{ background: #fee2e2; color: #991b1b; }}
    /* "3 booked Â· 12 in flight" beside the name â€” the answer to "who has
       actually landed something" without reading every row. */
    .tp-tally {{
      margin-left: 8px; font-family: var(--ab-mono); font-size: 0.66rem;
      font-weight: 600; color: var(--ab-fg-3); letter-spacing: 0.02em;
    }}
    .tp-tally b {{ color: #15803d; font-weight: 700; }}
    .tp-when {{
      margin-left: auto; white-space: nowrap;
      font-family: var(--ab-mono); font-size: 0.68rem; color: var(--ab-fg-3);
    }}
    .ops-stage-who {{
      font-family: var(--ab-mono); font-size: 0.62rem; font-weight: 700;
      letter-spacing: 0.04em; color: var(--ab-fg-3); white-space: nowrap;
    }}
    .ops-card .event-date {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      text-transform: uppercase; margin: 0;
    }}
    .ops-card .event-name {{
      font-family: var(--ab-sans); font-weight: 700;
      font-size: 1.05rem; line-height: 1.3; letter-spacing: -0.01em;
      margin: 0; color: var(--ab-fg); overflow-wrap: anywhere;
      /* Reserve two lines for the title so a one-line name doesn't shove
         everything below it up â€” it lines up across cards either way. */
      min-height: 2.6em;
    }}
    .ops-card .event-meta {{
      font-size: 0.85rem; color: var(--ab-fg-2); margin: 0 0 12px; line-height: 1.4;
    }}
    .ops-card .event-meta .em-date {{
      font-family: var(--ab-mono); font-size: 0.72rem; letter-spacing: 0.05em;
      text-transform: uppercase; color: var(--ab-fg-3);
    }}
    .ops-card .event-loc {{
      font-size: 0.85rem; color: var(--ab-fg-2); margin: 0 0 12px;
    }}
    .ops-card .ops-link {{
      color: var(--ab-blue); text-decoration: none;
      font-weight: 600; padding: 0 4px;
      transition: color 120ms ease;
    }}
    .ops-card .ops-link:hover {{ color: var(--ab-blue-light); }}
    /* The whole queue row opens the event now that the Details pill is gone. */
    .queue-row-open {{ cursor: pointer; }}
    .queue-row-open:hover {{ background: var(--ab-bg-3); }}
    .ops-details-btn {{
      font-family: var(--ab-mono); font-size: 0.62rem; letter-spacing: 0.07em;
      text-transform: uppercase; color: var(--ab-fg-3);
      background: var(--ab-bg-3); border: 1px solid var(--ab-rule);
      border-radius: 999px; padding: 2px 10px; margin-left: 6px; cursor: pointer;
      text-decoration: underline; text-underline-offset: 2px;
      vertical-align: 2px; transition: background 0.15s, color 0.15s, border-color 0.15s;
    }}
    .ops-details-btn:hover {{ background: var(--ab-blue); color: #fff; border-color: var(--ab-blue); }}
    /* Per-role roster on the card face â€” a small colored initial-avatar next to
       the name (Google Calendar / Docs style) instead of a boxed label. */
    .ops-roster {{ display: flex; flex-direction: column; gap: 6px; margin: 8px 0 8px; }}
    .ops-roster-row {{ display: flex; align-items: center; gap: 7px; font-size: 0.86rem; line-height: 1.3; }}
    .ops-roster-label {{
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 700;
      letter-spacing: 0.05em; text-transform: uppercase; white-space: nowrap;
      flex-shrink: 0; color: var(--ab-fg-3);
    }}
    .ops-avatars {{ display: inline-flex; align-items: center; flex-shrink: 0; }}
    .ops-avatar {{
      width: 20px; height: 20px; border-radius: 50%;
      display: inline-flex; align-items: center; justify-content: center;
      font-family: var(--ab-sans); font-size: 0.62rem; font-weight: 700;
      box-sizing: border-box; border: 2px solid var(--ab-bg); flex-shrink: 0;
    }}
    .ops-avatar + .ops-avatar {{ margin-left: -6px; }}   /* overlapping stack */
    .ops-avatar.ops-avatar-more {{
      background: var(--ab-bg-3); color: var(--ab-fg-3);
      font-family: var(--ab-mono); font-size: 0.56rem;
    }}
    .ops-roster-who {{ color: var(--ab-fg); font-weight: 650; }}
    .ops-roster-who.muted {{ color: var(--ab-fg-3); font-weight: 400; font-style: italic; }}
    .ops-tags--meta {{ margin-top: 4px; }}
    .ops-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }}
    .ops-tag {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.06em; padding: 3px 8px;
      border-radius: 3px; background: var(--ab-bg-3);
      color: var(--ab-fg-2); line-height: 1.4;
      display: inline-flex; align-items: center; gap: 4px;
    }}
    .ops-tag.status   {{ background: #ecfdf5; color: #065f46; }}
    .ops-tag.speaker  {{ background: #eff6ff; color: #1e40af; }}
    /* Pipeline-stage pills (primary) get bg/fg inline from stageStyle();
       the legacy single-status pill is demoted to a small muted detail. */
    .ops-tag.stage  {{ font-weight: 600; letter-spacing: 0.04em; }}
    .ops-tag.legacy {{ font-size: 0.58rem; opacity: 0.72; }}
    .ops-tag .dot {{ width: 6px; height: 6px; border-radius: 50%; display: inline-block; }}
    .saved-star {{
      font: inherit; background: transparent; border: 0;
      padding: 4px 6px; cursor: pointer; line-height: 1;
      color: var(--ab-mute); font-size: 1.25rem;
      transition: color 120ms ease, transform 120ms ease;
    }}
    .saved-star:hover {{ color: var(--ab-fg-3); }}
    .saved-star.is-on {{ color: var(--ab-blue); }}
    .saved-star.is-on:hover {{ color: var(--ab-blue-light); }}
    .saved-star[aria-busy="true"] {{ opacity: 0.4; cursor: wait; }}

    /* Chip toggles on the ops card head (urgent, hidden) */
    .ops-chips {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
    /* Human should-attend = prominent; AI auto-pick = faint (so 256 don't drown the hand-picked few). */
    .sa-badge {{
      font-family: var(--ab-mono); font-size: 0.62rem; font-weight: 700;
      letter-spacing: 0.03em; text-transform: uppercase; white-space: nowrap;
      padding: 3px 8px; border-radius: 3px; background: #1d4ed8; color: #fff;
    }}
    .sa-badge--ai {{
      background: transparent; color: var(--ab-fg-3);
      border: 1px solid var(--ab-rule-strong); font-weight: 600;
    }}
    .contact-badge {{
      font-family: var(--ab-mono); font-size: 0.62rem; font-weight: 700;
      letter-spacing: 0.03em; text-transform: uppercase; white-space: nowrap;
      padding: 3px 8px; border-radius: 3px; background: #dcfce7; color: #15803d; border: 1px solid #86efac;
    }}
    /* Archived = a static (rectangular) status label; archiving is done in the pop-up. */
    .ops-archived-tag {{
      font-family: var(--ab-mono); font-size: 0.62rem; font-weight: 700;
      letter-spacing: 0.06em; text-transform: uppercase; white-space: nowrap;
      padding: 3px 8px; border-radius: 3px;
      border: 1px solid var(--ab-rule); background: var(--ab-bg-2); color: var(--ab-fg-3);
    }}
    /* Region row sits tight under the pipeline row. */
    #region-filters {{ margin-top: -4px; }}
    .ops-chip {{
      font: inherit; cursor: pointer;
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      padding: 3px 8px; border-radius: 999px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-3); line-height: 1.4;
      text-decoration: underline; text-underline-offset: 2px;
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
    }}
    .ops-chip:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .ops-chip.is-on {{ background: var(--ab-fg); color: var(--ab-bg); border-color: var(--ab-fg); }}
    .ops-chip.is-on.urgent {{ background: var(--ab-red); border-color: var(--ab-red); }}
    .ops-chip[aria-busy="true"] {{ opacity: 0.4; cursor: wait; }}
    .ops-chip.badge-manual {{
      cursor: default; pointer-events: none; text-decoration: none; border-radius: 3px;
      background: var(--ab-blue); color: var(--ab-bg); border-color: var(--ab-blue);
    }}

    .ops-card.is-archived {{ opacity: 0.55; background: var(--ab-bg-2); }}
    /* Past events: dimmed when revealed via "Show past" (default: filtered out). */
    .ops-card.is-past {{ opacity: 0.6; }}
    .ops-card.is-past:hover {{ opacity: 1; }}
    .ops-card.is-urgent {{ border-color: var(--ab-red); }}
    .ops-card.is-saved.is-urgent {{ border-color: var(--ab-red); box-shadow: inset 4px 0 0 var(--ab-blue); }}
    /* Urgent is Angela-only â€” for everyone else, hide its pill and drop the red cues. */
    body.hide-urgent .ops-chip.urgent {{ display: none; }}
    body.hide-urgent .ops-card.is-urgent {{ border-color: var(--ab-rule); }}
    body.hide-urgent .ops-card.is-saved.is-urgent {{ border-color: var(--ab-rule); box-shadow: inset 4px 0 0 var(--ab-blue); }}

    /* Inline edit disclosure */
    .ops-edit {{ margin-top: 12px; border-top: 1px solid var(--ab-rule); padding-top: 12px; }}
    .ops-edit > summary {{
      cursor: pointer; list-style: none;
      font-family: var(--ab-mono); font-size: 0.72rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 4px 0;
      user-select: none;
    }}
    .ops-edit > summary::-webkit-details-marker {{ display: none; }}
    .ops-edit > summary::before {{ content: "â–¸ "; display: inline-block; transition: transform 120ms ease; }}
    .ops-edit[open] > summary::before {{ content: "â–¾ "; }}
    .ops-edit > summary:hover {{ color: var(--ab-fg); }}

    .ops-form {{ display: grid; gap: 10px; margin-top: 12px; }}
    .ops-form .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    /* .ops-fieldset is a NON-label field wrapper â€” used where the field holds
       several checkboxes (each already in its own <label>), since nesting a
       <label> inside a <label> is invalid HTML and breaks clicking on Safari. */
    .ops-form label, .ops-form .ops-fieldset {{ display: flex; flex-direction: column; gap: 4px; }}
    .ops-form label > .key, .ops-form .ops-fieldset > .key {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .ops-form input[type="text"],
    .ops-form select,
    .ops-form textarea {{
      font-family: var(--ab-sans); font-size: 0.9rem;
      padding: 8px 10px; border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; background: var(--ab-bg);
      color: var(--ab-fg); outline: none; min-width: 0;
    }}
    .ops-form input[type="text"]:focus,
    .ops-form select:focus,
    .ops-form textarea:focus {{
      border-color: var(--ab-blue); box-shadow: 0 0 0 3px rgba(39,115,194,0.12);
    }}
    .ops-form textarea {{ min-height: 70px; resize: vertical; font-family: var(--ab-sans); }}
    .ops-form .field-saved {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-green); letter-spacing: 0.08em;
      text-transform: uppercase; padding-left: 6px;
      opacity: 0; transition: opacity 200ms ease;
    }}
    .ops-form .field-saved.show {{ opacity: 1; }}
    .ops-form .field-error {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-red); letter-spacing: 0.08em;
      text-transform: uppercase; padding-left: 6px;
    }}
    .ops-meta {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      margin-top: 8px;
    }}

    /* Segmented status filter: All / Pending / Booked / Attending. Sits at the
       left of the filter bar; the rest of the filters hide behind the icon. */
    .ops-seg {{
      display: inline-flex; align-items: stretch; gap: 2px;
      padding: 3px; border-radius: 10px; background: var(--ab-bg-3);
      border: 1px solid var(--ab-rule); flex: 0 0 auto;
    }}
    .ops-seg[hidden] {{ display: none; }}
    .seg-chip {{
      display: inline-flex; align-items: center; gap: 6px;
      font-family: var(--ab-sans); font-size: 0.84rem; font-weight: 600;
      color: var(--ab-fg-2); background: transparent; border: 0; cursor: pointer;
      padding: 7px 13px; border-radius: 7px; white-space: nowrap; transition: all 0.12s;
    }}
    .seg-chip:hover {{ color: var(--ab-fg); background: var(--ab-bg); }}
    .seg-chip.is-on {{ background: var(--ab-fg); color: var(--ab-bg); box-shadow: 0 1px 3px rgba(0,0,0,0.12); }}
    .seg-num {{
      font-family: var(--ab-mono); font-size: 0.72rem; font-weight: 600;
      color: var(--ab-fg-3); background: var(--ab-bg); border-radius: 999px; padding: 0 6px; min-width: 18px; text-align: center;
    }}
    .seg-chip.is-on .seg-num {{ color: var(--ab-fg); background: var(--ab-bg); }}
    @media (max-width: 560px) {{ .ops-seg {{ width: 100%; }} .seg-chip {{ flex: 1; justify-content: center; }} }}

    /* Status filter chip row */
    .status-filters {{
      display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
      padding: 10px 12px; margin-bottom: 16px;
      border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg);
    }}
    .status-filters > .label {{
      font-family: var(--ab-mono); font-size: 0.7rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase; margin-right: 4px;
    }}
    .status-group-label {{
      font-family: var(--ab-mono); font-size: 0.62rem;
      letter-spacing: 0.1em; text-transform: uppercase;
      padding: 2px 6px 2px 0;
      display: inline-flex; align-items: center;
    }}
    .status-group-label::before {{
      content: ''; width: 6px; height: 6px;
      border-radius: 50%; background: currentColor;
      margin-right: 5px;
    }}
    .status-group-sep {{
      display: inline-block; width: 1px; height: 18px;
      background: var(--ab-rule); margin: 0 4px;
    }}
    .status-chip {{
      font-family: var(--ab-sans); font-size: 0.74rem; font-weight: 500;
      padding: 4px 10px; border-radius: 999px;
      border: 1px solid transparent;
      cursor: pointer; opacity: 0.45;
      transition: opacity 120ms ease, box-shadow 120ms ease, transform 120ms ease;
      white-space: nowrap;
    }}
    .status-chip:hover {{ opacity: 0.8; }}
    .status-chip.is-on {{ opacity: 1; box-shadow: 0 0 0 2px var(--ab-fg); transform: translateY(-1px); }}
    .status-filters .clear-btn {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.06em; padding: 5px 10px;
      border: 1px solid var(--ab-rule-strong); border-radius: 6px;
      background: var(--ab-bg); color: var(--ab-fg-3);
      cursor: pointer; margin-left: auto;
    }}
    .status-filters .clear-btn:hover {{ color: var(--ab-fg); }}

    /* Pipeline-stage filter row â€” the new primary status control. The
       full legacy status vocabulary lives below it in a collapsed
       <details>, so the at-a-glance filter is just the 5 stages. */
    .stage-filters {{
      display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
      padding: 10px 12px; margin-bottom: 12px;
      border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg);
    }}
    .stage-filters > .label {{
      font-family: var(--ab-mono); font-size: 0.7rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase; margin-right: 4px;
    }}
    .stage-chip {{
      font-family: var(--ab-sans); font-size: 0.78rem; font-weight: 600;
      padding: 5px 12px; border-radius: 999px;
      border: 1px solid transparent;
      cursor: pointer; opacity: 0.5;
      transition: opacity 120ms ease, box-shadow 120ms ease, transform 120ms ease;
      white-space: nowrap;
    }}
    .stage-chip:hover {{ opacity: 0.85; }}
    .stage-chip.is-on {{ opacity: 1; box-shadow: 0 0 0 2px var(--ab-fg); transform: translateY(-1px); }}
    .stage-filters .clear-btn {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.06em; padding: 5px 10px;
      border: 1px solid var(--ab-rule-strong); border-radius: 6px;
      background: var(--ab-bg); color: var(--ab-fg-3);
      cursor: pointer; margin-left: auto;
    }}
    .stage-filters .clear-btn:hover {{ color: var(--ab-fg); }}
    .legacy-status-wrap {{ margin-bottom: 16px; }}
    .legacy-status-wrap > summary {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--ab-fg-3); cursor: pointer; padding: 4px 2px;
    }}
    .legacy-status-wrap[open] > summary {{ margin-bottom: 8px; }}
    .legacy-status-wrap .status-filters {{ margin-bottom: 0; }}

    /* Stage multi-select checkboxes inside the ops/manual edit forms */
    .stage-picker {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .ops-form .stage-picker label {{
      flex-direction: row; align-items: center; gap: 5px;
      font-family: var(--ab-sans); font-size: 0.76rem; font-weight: 500;
      padding: 4px 9px; border-radius: 999px;
      border: 1px solid var(--ab-rule-strong);
      background: var(--ab-bg); color: var(--ab-fg-2);
      cursor: pointer; user-select: none;
    }}
    .ops-form .stage-picker label.is-on {{ box-shadow: 0 0 0 2px var(--ab-fg) inset; }}
    .ops-form .stage-picker label input {{ margin: 0; width: auto; }}

    /* Extra filters (used by the Dust event-search panel: Types / Quarters / â€¦) */
    .extra-filters {{
      display: flex; flex-direction: column; gap: 8px;
      padding: 10px 12px; margin-bottom: 16px;
      border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg);
    }}
    .extra-filter-group {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .extra-filter-label {{
      font-family: var(--ab-mono); font-size: 0.66rem; font-weight: 700;
      letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--ab-fg-2); min-width: 84px;
    }}
    /* Compact filter dropdown â€” same look as the Months menu. */
    .filter-dd {{ position: relative; display: inline-block; }}
    .filter-dd-btn {{
      font-family: "Nunito Sans", var(--ab-sans); font-size: 0.86rem; font-weight: 800;
      letter-spacing: 0.04em; text-transform: uppercase; color: var(--ab-fg-2);
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; padding: 10px 13px; cursor: pointer;
      display: inline-flex; align-items: center; gap: 5px;
      transition: background 0.15s, border-color 0.15s, color 0.15s;
    }}
    .filter-dd-btn:hover {{ border-color: var(--ab-rule-strong); color: var(--ab-fg); }}
    .filter-dd-btn.has-active {{ background: var(--ab-fg); color: var(--ab-bg); border-color: var(--ab-fg); }}
    .filter-dd-btn .dd-caret {{ font-size: 0.55rem; color: var(--ab-fg-3); }}
    .filter-dd-menu {{
      /* Above Leaflet's map panes/controls (z-index up to ~1000) so the filter
         menus aren't cut off over the Map view; still below modals (1200+). */
      position: absolute; top: calc(100% + 6px); left: 0; z-index: 1100;
      min-width: 200px; max-width: 330px; max-height: 360px; overflow-y: auto;
      background: var(--ab-bg); border: 1px solid var(--ab-rule);
      border-radius: 8px; padding: 10px; gap: 6px; flex-wrap: wrap;
      box-shadow: 0 8px 24px rgba(0,0,0,0.10); display: none;
    }}
    .filter-dd-menu.open {{ display: flex; }}
    .filter-dd-menu .extra-clear {{ flex-basis: 100%; margin-top: 2px; }}
    /* Months filter: one month per line, past months collapsed at the bottom. */
    #filter-months .month-chip {{ flex-basis: 100%; text-align: left; }}
    #filter-months .filter-dd-menu .is-pastmonth {{ display: none; }}
    #filter-months .filter-dd-menu.show-past .is-pastmonth {{ display: block; }}
    .month-past-toggle {{
      flex-basis: 100%; margin-top: 4px; display: flex; align-items: center;
      justify-content: space-between; gap: 8px; background: none; cursor: pointer;
      border: 0; border-top: 1px solid var(--ab-rule); padding: 8px 2px 2px;
      font-family: var(--ab-mono); font-size: 0.6rem; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--ab-fg-3);
    }}
    .month-past-toggle:hover {{ color: var(--ab-fg); }}
    .month-past-toggle .mpt-caret {{ transition: transform 120ms ease; }}
    #filter-months .filter-dd-menu.show-past .month-past-toggle .mpt-caret {{ transform: rotate(180deg); }}
    /* Speaking (blue) vs Attending (green) active chips keep the two distinct. */
    .extra-chip.speak-chip.is-on {{ background: #1271a8; color: #fff; border-color: #1271a8; box-shadow: 0 0 0 2px #1271a8; }}
    .extra-chip.att-chip.is-on   {{ background: #047857; color: #fff; border-color: #047857; box-shadow: 0 0 0 2px #047857; }}
    .extra-empty {{
      font-family: var(--ab-mono); font-size: 0.7rem;
      color: var(--ab-fg-3); font-style: italic;
    }}
    .extra-chip {{
      font-family: var(--ab-sans); font-size: 0.74rem; font-weight: 500;
      padding: 4px 10px; border-radius: 999px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); cursor: pointer; opacity: 0.55;
      transition: opacity 120ms ease, box-shadow 120ms ease, transform 120ms ease;
      white-space: nowrap;
    }}
    .extra-chip:hover {{ opacity: 0.9; color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .extra-chip.is-on {{ opacity: 1; box-shadow: 0 0 0 2px var(--ab-fg); transform: translateY(-1px); }}
    .extra-chip.pri-high.is-on   {{ background: #166534; color: #fff; border-color: #166534; box-shadow: 0 0 0 2px #166534; }}
    .extra-chip.pri-medium.is-on {{ background: #fef3c7; color: #92400e; border-color: #92400e; box-shadow: 0 0 0 2px #92400e; }}
    .extra-chip.pri-low.is-on    {{ background: var(--ab-bg-3); color: var(--ab-fg-3); border-color: var(--ab-fg-3); box-shadow: 0 0 0 2px var(--ab-fg-3); }}
    /* Pipeline / Region / Should-attend chips keep their palette when selected. */
    .extra-chip.stage-chip-dd.is-on  {{ background: var(--sc-bg); color: var(--sc-fg); border-color: var(--sc-bg); box-shadow: 0 0 0 2px var(--sc-fg); }}
    .extra-chip.region-chip-dd.is-on {{ background: var(--rc-col); color: #fff; border-color: var(--rc-col); box-shadow: 0 0 0 2px var(--rc-col); }}
    .extra-chip.should-team.is-on    {{ background: #7c3aed; color: #fff; border-color: #7c3aed; box-shadow: 0 0 0 2px #7c3aed; }}
    .extra-chip.should-ai.is-on      {{ background: #64748b; color: #fff; border-color: #64748b; box-shadow: 0 0 0 2px #64748b; }}
    .extra-clear {{
      font-family: var(--ab-mono); font-size: 0.62rem;
      letter-spacing: 0.06em; padding: 4px 8px;
      border: 1px solid var(--ab-rule-strong); border-radius: 6px;
      background: var(--ab-bg); color: var(--ab-fg-3);
      cursor: pointer; margin-left: auto;
    }}
    .extra-clear:hover {{ color: var(--ab-fg); }}

    /* Filter bar */
    /* Always-visible top filter line: Pipeline Â· Region Â· Fits Â· Months Â·
       Should attend â€” compact multi-select dropdowns (replaced the tall
       colored Pipeline/Region chip rows). */
    .ops-topfilters {{
      display: flex; flex-wrap: wrap; align-items: center;
      gap: 8px; margin: 0 0 16px;
    }}
    .ops-topfilters .filter-dd-btn {{ width: auto; }}
    /* Search fills the space between the last filter and Ask Anything, so the
       filter row's right edge lines up with the stat cards + tabs rows. */
    .ops-topfilters #ops-search {{
      flex: 1 1 240px; min-width: 220px;
      font-family: "Nunito Sans", var(--ab-sans); font-size: 0.9rem; font-weight: 600;
      padding: 9px 13px; border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; background: var(--ab-bg); color: var(--ab-fg); outline: none;
    }}
    .ops-topfilters #ops-search::placeholder {{ color: var(--ab-fg-3); font-style: italic; font-weight: 500; }}
    .ops-topfilters #ops-search:focus {{ border-color: var(--ab-blue); box-shadow: 0 0 0 3px rgba(39,115,194,0.12); }}
    @media (max-width: 640px) {{ .ops-topfilters #ops-search {{ flex-basis: 100%; }} }}
    /* Ask Anything sits next to search â€” matched to the filter/search height. */
    .ops-topfilters .ab-btn--ask {{ flex: 0 0 auto; padding: 11px 16px; font-size: 0.86rem; font-weight: 700; }}
    /* Filter icon â€” reveals the drawer holding every non-status filter. */
    .tf-toggle {{
      flex: 0 0 auto; position: relative; display: inline-flex; align-items: center; justify-content: center;
      width: 40px; height: 40px; border-radius: 8px; cursor: pointer;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-2); transition: all 0.12s;
    }}
    .tf-toggle:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .tf-toggle[aria-expanded="true"] {{ background: var(--ab-fg); color: var(--ab-bg); border-color: var(--ab-fg); }}
    .tf-toggle svg {{ width: 18px; height: 18px; }}
    .tf-toggle.has-active {{ border-color: var(--ab-blue); color: var(--ab-blue); }}
    /* A small dot, top-right, when any secondary (drawer) filter is active. */
    .tf-dot {{
      position: absolute; top: -3px; right: -3px; width: 9px; height: 9px;
      background: var(--ab-blue); border: 2px solid var(--ab-bg); border-radius: 50%;
    }}
    .tf-dot[hidden] {{ display: none; }}
    /* The drawer: a full-width panel of dropdown filters below the bar. */
    .tf-drawer {{
      display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
      margin: -8px 0 16px; padding: 12px; border: 1px solid var(--ab-rule);
      border-radius: 10px; background: var(--ab-bg-2, var(--ab-bg));
    }}
    .tf-drawer[hidden] {{ display: none; }}
    .tf-drawer .filter-dd-btn {{ width: auto; }}
    /* "N filters active â€” Clear all", right under the top filter bar â€” an
       active filter (esp. Region/Months, easy to forget you set) shouldn't be
       invisible; everyone sees this, not just Angela. */
    .ops-active-filters {{
      margin: -8px 0 16px; font-family: "Nunito Sans", var(--ab-sans);
      font-size: 0.82rem; font-weight: 700; color: var(--ab-blue);
    }}
    .ops-active-filters button {{
      font: inherit; font-weight: 800; color: inherit; text-decoration: underline;
      background: none; border: none; padding: 0; cursor: pointer;
    }}
    .ops-active-filters button:hover {{ color: var(--ab-fg); }}
    .ops-filters {{
      display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px; align-items: stretch;
      padding: 12px; margin-bottom: 16px;
      border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg);
    }}
    /* Collapsible: by default the dropdowns hide behind the Filters toggle so
       the filter bar isn't the dominant element â€” search + toggle stay visible. */
    .ops-filter-toggle {{
      grid-column: 1 / -1; justify-self: start;
      font-family: "Nunito Sans", var(--ab-sans); font-size: 0.8rem; font-weight: 800;
      text-transform: uppercase; letter-spacing: 0.04em; color: var(--ab-fg-2);
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; padding: 8px 13px; cursor: pointer;
      display: inline-flex; align-items: center; gap: 7px;
    }}
    .ops-filter-toggle:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .ops-filter-toggle .ft-active {{ color: var(--ab-blue); }}
    .ops-filter-toggle .ft-caret {{ font-size: 0.6rem; color: var(--ab-fg-3); }}
    .ops-filters.collapsed > :not(#ops-search):not(.ops-filter-toggle) {{ display: none; }}
    /* Each filter fills its column so the bar reads as a tidy 5-up grid */
    .ops-filters > .filter-dd, .ops-filters > .ops-months {{ display: block; }}
    .ops-filters .filter-dd-btn, .ops-filters .ops-months-btn {{
      width: 100%; height: 100%; justify-content: space-between;
    }}
    .ops-filters input[type="search"] {{
      grid-column: 1 / -1;   /* own full-width row; the other filters sit 5-up below */
      font-family: "Nunito Sans", var(--ab-sans); font-size: 0.98rem; font-weight: 700;
      padding: 10px 13px; border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; background: var(--ab-bg);
      color: var(--ab-fg); outline: none;
    }}
    .ops-filters input[type="search"]:focus {{
      border-color: var(--ab-blue); box-shadow: 0 0 0 3px rgba(39,115,194,0.12);
    }}
    .ops-filters select {{
      width: 100%;
      appearance: none; -webkit-appearance: none; -moz-appearance: none;
      font-family: "Nunito Sans", var(--ab-sans); font-size: 0.86rem; font-weight: 800;
      text-transform: uppercase; letter-spacing: 0.04em;
      padding: 10px 32px 10px 13px; border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; cursor: pointer; color: var(--ab-fg); outline: none;
      background: var(--ab-bg) url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20width='10'%20height='6'%20viewBox='0%200%2010%206'%3E%3Cpath%20d='M0%200h10L5%206z'%20fill='%23737373'/%3E%3C/svg%3E") no-repeat right 13px center;
    }}
    .ops-filter-chip {{
      display: flex; width: 100%; align-items: center; gap: 6px;
      font-family: "Nunito Sans", var(--ab-sans); font-size: 0.86rem; font-weight: 800;
      letter-spacing: 0.04em; text-transform: uppercase;
      padding: 10px 13px; border-radius: 6px; white-space: nowrap;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); cursor: pointer; user-select: none;
    }}
    .ops-filter-chip:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .ops-filter-chip input {{ accent-color: var(--ab-blue); }}
    .ops-filter-chip.has-active {{ background: var(--ab-bg-3); border-color: var(--ab-fg); color: var(--ab-fg); }}
    .ops-shown {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      text-align: right; white-space: nowrap;
    }}

    /* View toggle (Grid / Calendar) */
    /* Primary nav â€” underlined TEXT tabs (not pills). The row's hairline doubles
       as the tab track; the active tab's 2px border sits on it. */
    .view-toggle {{
      display: inline-flex; flex-wrap: wrap; gap: 2px 22px; align-items: flex-end;
    }}
    .view-toggle button {{
      font-family: var(--ab-sans); font-weight: 400; font-size: 1.2rem;
      letter-spacing: -0.01em; padding: 6px 1px; border: 0;
      border-bottom: 2px solid transparent; margin-bottom: -1px;
      background: transparent; color: var(--ab-fg-2);
      cursor: pointer; transition: color 120ms ease, border-color 120ms ease;
    }}
    .view-toggle button:hover {{ color: var(--ab-fg); }}
    .view-toggle button.active {{ font-weight: 500; color: var(--ab-fg); border-bottom-color: var(--ab-fg); }}
    /* Small count pill inside a view-toggle tab (My lineup / Queue / Planner). */
    .vt-count {{
      display: inline-block; min-width: 18px; margin-left: 6px; padding: 0 6px;
      font-family: var(--ab-mono); font-size: 0.68rem; line-height: 18px;
      text-align: center; border-radius: 9px; vertical-align: middle;
      background: var(--ab-fg-3); color: #fff;
    }}
    .view-toggle button.active .vt-count {{ background: #1fa0dc; }}
    .vt-count.alert {{ background: #d64545; }}
    /* Secondary view switcher under the merged "Events" tab. List / Calendar
       / Map are three shapes of the same event set, so they read as a
       sub-level, not primary tabs. Shown only on an Events sub-view. */
    /* View switcher â€” icon-only segmented group (List / Calendar / Map). */
    .events-subnav {{
      display: inline-flex; gap: 2px; padding: 3px; flex: 0 0 auto;
      background: var(--ab-bg-3); border: 1px solid var(--ab-rule); border-radius: 10px;
    }}
    .events-subnav[hidden] {{ display: none; }}
    .subnav-btn {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 34px; height: 34px; border-radius: 7px; border: 0; background: transparent;
      color: var(--ab-fg-2); cursor: pointer; transition: all 120ms ease;
    }}
    .subnav-btn svg {{ width: 17px; height: 17px; }}
    .subnav-btn:hover {{ color: var(--ab-fg); background: var(--ab-bg); }}
    .subnav-btn.active {{ background: var(--ab-bg); color: var(--ab-fg); box-shadow: 0 1px 2px rgba(0,0,0,0.08); }}

    /* Go decision badge (cards + modal + queue rows). */
    .decision-badge {{
      display: inline-flex; align-items: center; gap: 3px;
      font-family: var(--ab-mono); font-size: 0.62rem; font-weight: 600;
      letter-spacing: 0.06em; text-transform: uppercase;
      padding: 2px 7px; border-radius: 3px; white-space: nowrap;
    }}
    .decision-badge.go    {{ background: rgba(31,160,90,0.14); color: #1a8c54; }}
    .recent-badge {{
      display: inline-flex; align-items: center;
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 600;
      letter-spacing: 0.05em; text-transform: uppercase;
      padding: 2px 7px; border-radius: 3px; white-space: nowrap;
      background: #fef3c7; color: #92600a; border: 1px solid #fde68a;
    }}

    /* â”€â”€ Queue view (Angela's application queue) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .ops-myevents, .ops-planahead, .ops-myprofile, .ops-queue, .ops-planner, .ops-dayof {{ display: none; }}
    .ops-myevents.show, .ops-planahead.show, .ops-myprofile.show, .ops-queue.show, .ops-planner.show, .ops-dayof.show {{ display: block; }}
    /* â”€â”€ Day-Of tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .vt-count--dayof {{ background: #f59e0b; color: #fff; }}
    .dayof-intro {{ font-size: 0.9rem; color: var(--ab-fg-2); margin: 0 0 18px; line-height: 1.5; max-width: 760px; }}
    .dayof-section {{ margin: 0 0 26px; }}
    .dayof-sec-head {{ display: flex; align-items: center; gap: 8px; margin: 0 0 12px; }}
    .dayof-sec-title {{ font-family: var(--ab-mono); font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ab-fg); font-weight: 700; }}
    .dayof-sec-count {{ font-family: var(--ab-mono); font-size: 0.66rem; background: var(--ab-bg-3); border-radius: 10px; padding: 1px 8px; color: var(--ab-fg-3); }}
    .dayof-card {{ display: flex; gap: 14px; align-items: center; justify-content: space-between; flex-wrap: wrap;
      border: 1px solid var(--ab-rule); border-radius: 8px; padding: 14px 16px; margin: 0 0 10px; background: var(--ab-bg); }}
    .dayof-card.is-today {{ border-color: #f59e0b; box-shadow: 0 0 0 1px #f59e0b33; background: linear-gradient(0deg, #fffaf0, #fff); }}
    .dayof-card-main {{ min-width: 0; flex: 1 1 280px; }}
    .dayof-name {{ font-family: var(--ab-sans); font-weight: 650; font-size: 1rem; color: var(--ab-fg); background: none; border: 0; padding: 0; cursor: pointer; text-align: left; }}
    .dayof-name:hover {{ color: #1fa0dc; text-decoration: underline; }}
    .dayof-meta {{ font-size: 0.8rem; color: var(--ab-fg-3); margin: 3px 0 8px; }}
    .dayof-who-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .dayof-who {{ font-size: 0.82rem; color: var(--ab-fg-2); display: inline-flex; align-items: center; gap: 5px; }}
    .dayof-actions {{ display: flex; align-items: center; gap: 10px; }}
    .dayof-ready {{ font-family: var(--ab-mono); font-size: 0.64rem; color: #15803d; }}
    .dayof-empty {{ border: 1px dashed var(--ab-rule); border-radius: 8px; padding: 22px; text-align: center; color: var(--ab-fg-3); font-size: 0.88rem; line-height: 1.6; }}
    /* Load-failure / degraded / filtered-empty states â€” a blank grid is never OK. */
    .ops-load-error {{
      grid-column: 1 / -1; border: 1px dashed #f3b1b1; border-radius: 8px;
      background: #fef7f7; color: #7f1d1d; padding: 24px; text-align: center;
      font-size: 0.9rem; line-height: 1.7;
    }}
    .ops-sb-warning {{
      border: 1px solid #fde68a; background: #fffbeb; color: #92400e;
      border-radius: 8px; padding: 10px 14px; font-size: 0.85rem;
      line-height: 1.5; margin: 0 0 14px;
    }}
    .ops-empty-note {{
      grid-column: 1 / -1; border: 1px dashed var(--ab-rule); border-radius: 8px;
      padding: 28px; text-align: center; color: var(--ab-fg-2);
      font-size: 0.92rem; line-height: 1.9;
    }}
    .mode-badge {{ font-family: var(--ab-mono); font-size: 0.6rem; letter-spacing: 0.06em; text-transform: uppercase; font-weight: 700; padding: 1px 7px; border-radius: 3px; }}
    .mode-room {{ background: #dbeafe; color: #1e40af; }}
    .mode-stage {{ background: #f3e8ff; color: #7e22ce; }}
    /* â”€â”€ Brief drawer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .briefing-overlay {{ position: fixed; inset: 0; z-index: 70; background: rgba(10,10,10,0.42); display: none; justify-content: flex-end; }}
    .briefing-overlay.show {{ display: flex; }}
    .briefing-card {{ background: #fff; width: 100%; max-width: 560px; height: 100%; display: flex; flex-direction: column;
      box-shadow: -18px 0 50px rgba(0,0,0,0.22); animation: bfSlide 0.18s ease-out; }}
    @keyframes bfSlide {{ from {{ transform: translateX(30px); opacity: 0.6; }} to {{ transform: none; opacity: 1; }} }}
    .briefing-top {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 16px;
      border-bottom: 1px solid var(--ab-rule); position: sticky; top: 0; background: #fff; }}
    .briefing-top-title {{ font-family: var(--ab-mono); font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ab-fg-3); }}
    .briefing-top-actions {{ display: flex; gap: 6px; }}
    .bf-btn {{ font-family: var(--ab-mono); font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 5px 9px;
      border: 1px solid var(--ab-rule); border-radius: 4px; background: var(--ab-bg-3); color: var(--ab-fg-2); cursor: pointer; }}
    .bf-btn:hover {{ border-color: #1fa0dc; color: #1271a8; }}
    .bf-close {{ font-size: 1rem; padding: 3px 9px; }}
    .briefing-body {{ padding: 18px 20px 60px; overflow-y: auto; flex: 1; }}
    .bf-head h2 {{ font-size: 1.35rem; margin: 0 0 4px; display: inline; }}
    .bf-head .mode-badge {{ margin-left: 8px; vertical-align: 3px; }}
    .bf-sub {{ font-size: 0.85rem; color: var(--ab-fg-2); margin: 6px 0 2px; }}
    .bf-stamp {{ font-family: var(--ab-mono); font-size: 0.62rem; color: var(--ab-fg-3); margin: 0 0 6px; }}
    .bf-sec {{ border-top: 1px solid var(--ab-rule); padding: 14px 0 4px; }}
    .bf-sec h3 {{ font-family: var(--ab-mono); font-size: 0.7rem; letter-spacing: 0.07em; text-transform: uppercase; color: var(--ab-fg); margin: 0 0 8px; }}
    .bf-conf {{ font-size: 0.58rem; background: var(--ab-bg-3); color: var(--ab-fg-3); border-radius: 8px; padding: 1px 7px; margin-left: 6px; }}
    .bf-sec p {{ font-size: 0.9rem; line-height: 1.55; margin: 0 0 8px; color: var(--ab-fg); }}
    .bf-muted {{ color: var(--ab-fg-3) !important; font-size: 0.82rem !important; }}
    .bf-label {{ font-family: var(--ab-mono); font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ab-fg-3); margin: 10px 0 4px !important; }}
    .bf-win {{ font-weight: 650; color: #b45309 !important; }}
    .bf-move {{ color: #15803d !important; }}
    .bf-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .bf-chip {{ font-size: 0.76rem; background: var(--ab-bg-3); border-radius: 4px; padding: 2px 8px; color: var(--ab-fg-2); }}
    .bf-list, .bf-news {{ margin: 4px 0 10px; padding-left: 18px; }}
    .bf-list li, .bf-news li {{ font-size: 0.88rem; line-height: 1.5; margin: 0 0 6px; color: var(--ab-fg); }}
    .bf-news a {{ color: var(--ab-blue); }}
    .bf-date {{ font-family: var(--ab-mono); font-size: 0.66rem; color: var(--ab-fg-3); }}
    .bf-speaker {{ margin: 0 0 12px; }}
    .bf-hook {{ font-style: italic; color: #1271a8 !important; font-size: 0.84rem !important; }}
    .bf-unconf li {{ color: #92600a; }}
    .bf-loading {{ display: flex; align-items: center; gap: 10px; color: var(--ab-fg-2); font-size: 0.9rem; padding: 30px 0; }}
    .bf-spin {{ width: 16px; height: 16px; border: 2px solid var(--ab-rule); border-top-color: #1fa0dc; border-radius: 50%; animation: bfspin 0.7s linear infinite; }}
    @keyframes bfspin {{ to {{ transform: rotate(360deg); }} }}
    .bf-error {{ color: #b91c1c; font-size: 0.88rem; padding: 24px 0; line-height: 1.5; }}
    /* Deep outreach targets */
    .tg-bar {{ display: flex; align-items: center; gap: 8px; margin: 0 0 12px; }}
    .tg-count {{ margin-left: auto; font-family: var(--ab-mono); font-size: 0.66rem; color: var(--ab-fg-3); }}
    .tg-note {{ font-size: 0.82rem; color: var(--ab-fg-2); background: var(--ab-bg-3); border-radius: 6px; padding: 8px 10px; margin: 0 0 14px; line-height: 1.45; }}
    .tg-card {{ border: 1px solid var(--ab-rule); border-radius: 10px; padding: 12px 14px; margin: 0 0 12px; }}
    .tg-head {{ display: flex; align-items: center; gap: 8px; }}
    .tg-head strong {{ font-size: 0.98rem; color: var(--ab-fg); }}
    .tg-conf {{ font-family: var(--ab-mono); font-size: 0.58rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 6px; border-radius: 4px; }}
    .tg-conf.ok {{ background: #dcfce7; color: #166534; }}
    .tg-conf.est {{ background: var(--ab-bg-3); color: var(--ab-fg-3); }}
    .tg-role {{ font-size: 0.86rem; font-weight: 600; color: var(--ab-fg); margin: 2px 0 0; }}
    .tg-fit {{ font-size: 0.82rem; color: var(--ab-fg-2); margin: 4px 0 0; line-height: 1.45; }}
    .tg-line {{ font-size: 0.82rem; color: var(--ab-fg-2); margin: 6px 0 0; line-height: 1.45; }}
    .tg-line a {{ color: var(--ab-blue); }}
    .tg-muted {{ color: var(--ab-fg-3); }}
    .tg-unver {{ font-size: 0.74rem; color: #92600a; background: #fef3c7; border-radius: 4px; padding: 1px 6px; }}
    .tg-verify {{ font-size: 0.78rem; color: #92600a; margin: 0 0 12px; }}
    .tg-warm {{ font-size: 0.78rem; color: #166534; background: #dcfce7; border-radius: 5px; padding: 4px 8px; margin: 8px 0 0; display: inline-block; }}
    .tg-draft {{ margin: 10px 0 0; }}
    .tg-draft-h {{ display: flex; align-items: center; justify-content: space-between; }}
    .tg-copy {{ font-family: var(--ab-mono); font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 3px 8px; border: 1px solid var(--ab-rule); border-radius: 5px; background: var(--ab-bg); color: var(--ab-fg-2); cursor: pointer; }}
    .tg-copy:hover {{ border-color: #1fa0dc; color: #1271a8; }}
    .tg-pre {{ white-space: pre-wrap; font-family: var(--ab-sans); font-size: 0.84rem; line-height: 1.5; color: var(--ab-fg); background: var(--ab-bg-3); border-radius: 6px; padding: 10px 12px; margin: 4px 0 0; }}
    .tg-foot {{ font-family: var(--ab-mono); font-size: 0.62rem; color: var(--ab-fg-3); margin: 14px 0 0; }}
    @media (max-width: 560px) {{ .briefing-card {{ max-width: 100%; }} }}
    .queue-intro, .planner-intro {{
      font-size: 0.9rem; color: var(--ab-fg-2); margin: 0 0 18px; max-width: 70ch; line-height: 1.5;
    }}
    /* My Events intro stays on one line (no 70ch cap) at desktop widths. */
    .myev-intro {{ max-width: none; }}
    /* "Your skips are narrowing this" + its undo, inside the Plan Ahead intro. */
    .veto-note {{ color: var(--ab-fg-3); }}
    .veto-reset {{
      font: inherit; color: var(--ab-blue); background: none; border: 0;
      padding: 0; cursor: pointer; text-decoration: underline;
    }}
    .veto-reset:hover, .veto-reset:focus-visible {{ color: var(--ab-fg); }}
    .queue-section {{ margin: 0 0 26px; }}
    .queue-sec-head {{
      display: flex; align-items: baseline; gap: 10px; margin: 0 0 10px;
      padding-bottom: 6px; border-bottom: 1px solid var(--ab-rule);
    }}
    .queue-sec-title {{ font-family: var(--ab-sans); font-weight: 700; font-size: 1.02rem; color: var(--ab-fg); }}
    .queue-sec-count {{ font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-fg-3); }}
    /* Collapsible section (My Events "Past events" dropdown) â€” starts collapsed. */
    .queue-section.collapsible .queue-sec-head {{ cursor: pointer; user-select: none; }}
    .qsec-caret {{ font-size: 0.7rem; color: var(--ab-fg-3); transition: transform 0.15s; }}
    .queue-section.collapsible.collapsed .qsec-caret {{ transform: rotate(-90deg); display: inline-block; }}
    .queue-section.collapsible.collapsed .queue-row {{ display: none; }}
    .queue-row {{
      display: grid; grid-template-columns: 1fr auto; gap: 6px 14px;
      align-items: start; padding: 12px 14px; margin: 0 0 8px;
      border: 1px solid var(--ab-rule); border-radius: 10px; background: var(--ab-bg);
      transition: border-color 120ms ease, box-shadow 120ms ease;
    }}
    .queue-row:hover {{ border-color: #bfe3f5; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
    /* Whole-row click-to-open (My Lineup) â€” reads as one big button. */
    .queue-row-open {{ cursor: pointer; }}
    .queue-row-open:hover {{ border-color: #1fa0dc; }}
    .queue-row-open:focus-visible {{ outline: 2px solid var(--ab-blue); outline-offset: 2px; }}
    .queue-row-open:hover .queue-name {{ color: #1fa0dc; }}
    .queue-main {{ min-width: 0; }}
    .queue-name {{
      font-family: var(--ab-sans); font-weight: 650; font-size: 0.98rem; color: var(--ab-fg);
      background: none; border: 0; padding: 0; text-align: left; display: inline-block; cursor: pointer;
    }}
    .queue-name:hover {{ color: #1fa0dc; text-decoration: underline; }}
    .queue-meta {{ font-size: 0.8rem; color: var(--ab-fg-3); margin: 3px 0 0; }}
    /* "Reach out" asks â€” a warm to-do tint so they read as an action assigned
       to you, sitting at the top of My Lineup. */
    .outreach-row {{ border-color: #f5d9a8; background: #fffaf0; }}
    .outreach-row:hover {{ border-color: #e0a038; }}
    .outreach-ask {{ font-size: 0.82rem; font-weight: 600; color: #92500a; margin: 6px 0 0; }}
    .outreach-ask .outreach-ico {{ font-style: normal; }}
    .outreach-note {{ font-size: 0.82rem; color: var(--ab-fg-2); margin: 4px 0 0; font-style: italic; }}
    .queue-chips {{ display: flex; flex-wrap: wrap; gap: 5px 10px; margin: 7px 0 0; align-items: center; }}
    /* Groups a person chip with their role pill so name+role read as one unit. */
    .q-role-chip {{ display: inline-flex; align-items: center; gap: 4px; }}
    .q-int-chip {{
      font-family: var(--ab-mono); font-size: 0.66rem; font-weight: 600;
      padding: 2px 7px; border-radius: 999px;
      background: rgba(31,160,220,0.12); color: #1271a8;
    }}
    .q-stage-pill {{
      font-family: var(--ab-mono); font-size: 0.64rem; padding: 2px 7px;
      border-radius: 999px; border: 1px solid var(--ab-rule); color: var(--ab-fg-2);
    }}
    /* x N chase count riding inside the "Followed up" pill. */
    .q-n {{ margin-left: 4px; font-weight: 700; opacity: 0.75; }}
    /* Month divider inside the "To apply" list â€” the queue is chronological,
       so these are the only thing telling you where one month ends. */
    .q-month {{
      font-family: var(--ab-mono); font-size: 0.6rem; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--ab-fg-3);
      padding: 12px 2px 4px; border-bottom: 1px solid var(--ab-rule); margin-bottom: 4px;
    }}
    .queue-section .q-month:first-child {{ padding-top: 2px; }}
    /* Per-person discs on the card corner mark. */
    .ops-who-dot {{
      display: inline-flex; align-items: center; justify-content: center;
      min-width: 15px; height: 15px; padding: 0 3px; margin-left: 2px;
      border-radius: 999px; color: #fff;
      font-family: var(--ab-sans); font-size: 0.52rem; font-weight: 700; line-height: 1;
    }}
    .ops-who-more {{ margin-left: 3px; font-family: var(--ab-mono); font-size: 0.56rem; color: var(--ab-fg-3); }}
    .q-deadline {{ font-family: var(--ab-mono); font-size: 0.7rem; color: var(--ab-fg-3); }}
    .q-deadline.soon {{ color: #d64545; font-weight: 600; }}
    .queue-actions {{ display: flex; flex-direction: column; gap: 6px; align-items: stretch; }}
    .q-btn {{
      font-family: var(--ab-sans); font-size: 0.78rem; font-weight: 550;
      padding: 5px 11px; border-radius: 7px; border: 1px solid var(--ab-rule);
      background: var(--ab-bg); color: var(--ab-fg-2); cursor: pointer; white-space: nowrap;
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
    }}
    .q-btn:hover {{ border-color: #1fa0dc; color: #1271a8; }}
    .q-btn.primary {{ background: #1fa0dc; border-color: #1fa0dc; color: #fff; }}
    .q-btn.primary:hover {{ background: #1488bf; }}
    .q-btn.danger:hover {{ border-color: #d64545; color: #d64545; }}
    /* "In the last week" rows + suggestion "why" line (My Events). */
    .wn-check {{ padding: 4px 10px; font-size: 0.85rem; }}
    /* Comment threads surface as prominent cards (they likely need a reply). */
    .wn-comment {{
      display: flex; align-items: flex-start; gap: 12px; cursor: pointer;
      background: rgba(31,160,220,0.09); border: 1px solid rgba(31,160,220,0.35);
      border-radius: 10px; padding: 12px 14px; margin: 0 0 10px;
      transition: background 120ms ease, border-color 120ms ease;
    }}
    .wn-comment:hover {{ background: rgba(31,160,220,0.14); border-color: rgba(31,160,220,0.6); }}
    .wn-comment.is-mention {{ background: rgba(234,179,8,0.12); border-color: rgba(234,179,8,0.5); }}
    .wn-avatar {{
      flex: 0 0 auto; width: 34px; height: 34px; border-radius: 999px;
      display: inline-flex; align-items: center; justify-content: center;
      background: #1271a8; color: #fff; font-family: var(--ab-sans); font-weight: 700; font-size: 0.8rem;
    }}
    .wn-avatar--sm {{ width: 26px; height: 26px; font-size: 0.7rem; background: var(--ab-fg-3); }}
    /* Who's on it â€” initials on the right of a Team's Upcoming Events row.
       Overlapped slightly so four of them still read as one cluster. */
    .qrow-who-wrap {{ align-self: center; }}
    /* Right-hand column of a Lineup row: who it's for, and the brief under
       them. Small and quiet â€” the event name is the headline, not this. */
    .qrow-side {{ align-self: center; align-items: flex-end; gap: 5px; }}
    .qrow-brief {{
      font-family: var(--ab-mono); font-size: 0.64rem; letter-spacing: 0.03em;
      padding: 3px 8px; border-radius: 999px; cursor: pointer; white-space: nowrap;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-3);
      transition: border-color 120ms, color 120ms;
    }}
    .qrow-brief:hover {{ border-color: #1fa0dc; color: #1271a8; }}
    .qrow-brief.is-ready {{ border-color: #15803d; color: #15803d; }}
    .qrow-who {{ display: inline-flex; align-items: center; }}
    /* Brand blue, not the --sm grey. Grey is for secondary chrome like the
       activity feed; here the person IS the information on the row, and at
       26px on white the grey read as a disabled dot. */
    .qrow-who .wn-avatar--sm {{
      margin-left: -6px; border: 2px solid var(--ab-bg); background: #1271a8;
    }}
    .qrow-who .wn-avatar--sm:first-child {{ margin-left: 0; }}
    .qrow-who-more {{
      margin-left: 4px; font-family: var(--ab-mono); font-size: 0.68rem; color: var(--ab-fg-3);
    }}
    /* Little chat-bubble badge on a comment card's avatar â€” signals "chat". */
    .wn-avatar-wrap {{ position: relative; flex: 0 0 auto; display: inline-flex; }}
    .wn-chat-badge {{ position: absolute; right: -3px; bottom: -3px; width: 16px; height: 16px; border-radius: 50%; background: #1271a8; color: #fff; display: inline-flex; align-items: center; justify-content: center; border: 2px solid var(--ab-bg); }}
    .wn-chat-badge svg {{ width: 9px; height: 9px; }}
    .wn-comment-main {{ min-width: 0; flex: 1 1 auto; }}
    .wn-comment-head {{ font-size: 0.9rem; color: var(--ab-fg-2); }}
    .wn-comment-head strong {{ color: var(--ab-fg); font-weight: 650; }}
    .wn-time {{ font-family: var(--ab-mono); font-size: 0.66rem; color: var(--ab-fg-3); margin-left: 8px; }}
    .wn-comment-quote {{ margin-top: 4px; font-size: 0.95rem; color: var(--ab-fg); font-weight: 500; line-height: 1.4; }}
    .wn-comment .wn-check {{ flex: 0 0 auto; align-self: center; border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); border-radius: 8px; cursor: pointer; color: var(--ab-fg-3); }}
    .wn-comment .wn-check:hover {{ color: #15803d; border-color: #86efac; }}
    /* Routine pipeline moves, grouped per person â€” collapsed by default. */
    .wn-group {{ border: 1px solid var(--ab-rule); border-radius: 10px; margin: 0 0 8px; overflow: hidden; }}
    .wn-group-head {{
      display: flex; align-items: center; gap: 10px; padding: 10px 14px; cursor: pointer; user-select: none;
      background: var(--ab-bg-2);
    }}
    .wn-group-head:hover {{ background: var(--ab-bg-3); }}
    .wn-group-name {{ font-weight: 650; font-size: 0.9rem; color: var(--ab-fg); }}
    .wn-group-count {{ font-size: 0.85rem; color: var(--ab-fg-3); }}
    /* "Mark all as read" â€” Slack's own wording and register: a quiet text
       action, not a button competing with the content. Sits to the right, goes
       blue on hover so it reads as clickable. */
    .wn-readall {{
      font-family: var(--ab-sans); font-size: 0.78rem; font-weight: 600;
      color: var(--ab-fg-3); background: none; border: 0; padding: 2px 4px;
      cursor: pointer; border-radius: 5px; white-space: nowrap;
      transition: color 120ms ease, background 120ms ease;
    }}
    .wn-readall:hover, .wn-readall:focus-visible {{ color: var(--ab-blue); background: rgba(39,115,194,0.08); }}
    /* The section-level one closes out the whole feed â€” right-aligned in the head. */
    .wn-readall--all {{ margin-left: auto; }}
    /* Per-person: push it right, keeping the caret last. */
    .wn-group-head .wn-readall {{ margin-left: auto; }}
    .wn-group-head .qsec-caret {{ margin-left: 0; }}
    /* Reveal the per-group action on hover / keyboard focus so a collapsed feed
       stays calm, but keep it permanently visible on touch (no hover there). */
    .wn-group-head .wn-readall {{ opacity: 0; }}
    .wn-group:hover .wn-readall, .wn-group-head:focus-within .wn-readall,
    .wn-group-head .wn-readall:focus-visible {{ opacity: 1; }}
    @media (hover: none) {{ .wn-group-head .wn-readall {{ opacity: 1; }} }}
    .wn-group.collapsed .qsec-caret {{ transform: rotate(-90deg); display: inline-block; }}
    .wn-group.collapsed .wn-group-body {{ display: none; }}
    .wn-group-body {{ padding: 4px 10px 6px; }}
    .sug-why {{ margin: 2px 0 0; font-family: var(--ab-mono); font-size: 0.64rem; color: var(--ab-fg-3); letter-spacing: 0.03em; }}
    /* "Mark applied" + the Ã— dismiss sit side by side, not stacked. */
    .q-btn-row {{ display: flex; gap: 6px; align-items: stretch; }}
    .q-btn-row .q-btn.primary {{ flex: 1; }}
    /* Plan Ahead embedded at the bottom of My Lineup â€” a clear divider above it. */
    .ops-planahead-embed {{ margin-top: 20px; padding-top: 8px; border-top: 1px solid var(--ab-rule); }}
    /* Off for someone (see _PLAN_AHEAD_OFF): the divider is on this element, so
       an emptied section would still draw a stray rule under Past events. */
    .ops-planahead-embed:empty {{ display: none; }}
    /* Plan Ahead decision buttons: "I'm interested" + "Not for me" side by side. */
    .queue-actions.sug-actions {{ flex-direction: row; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .q-btn.sug-skip {{ color: var(--ab-fg-3); }}
    .q-btn.sug-skip:hover {{ border-color: #d64545; color: #d64545; }}
    /* "Batch your trips" â€” a cluster of nearby-in-time events under an anchor. */
    .trip-cluster {{ position: relative; border-left: 3px solid #1fa0dc; padding-left: 12px; margin: 0 0 20px; }}
    /* âœ• to hide a whole trip cluster / radar group from Plan Ahead (hover-reveal). */
    .plan-hide-x {{
      position: absolute; top: 2px; right: 0;
      border: 0; background: none; cursor: pointer; color: var(--ab-fg-3);
      font-size: 1.1rem; line-height: 1; padding: 2px 7px; border-radius: 5px;
      opacity: 0; transition: opacity 120ms ease, color 120ms ease, background 120ms ease;
      /* Invisible must also mean UNCLICKABLE. At opacity:0 this still swallowed
         clicks, so aiming at the event name in the top-right of a cluster hit the
         hidden âœ• instead and made the whole block disappear rather than opening
         the event (Angela: "it won't let me click on any of the events"). */
      pointer-events: none;
    }}
    .trip-cluster:hover .plan-hide-x, .plan-hide-x:focus-visible {{ opacity: 1; pointer-events: auto; }}
    .plan-hide-x:hover {{ color: var(--ab-red); background: var(--ab-bg-3); }}
    .trip-anchor {{ font-size: 0.9rem; color: var(--ab-fg-2); margin: 0 0 8px; }}
    .trip-anchor strong {{ color: var(--ab-fg); }}
    .trip-anchor-name {{ font: inherit; font-weight: 700; color: var(--ab-fg); background: none; border: 0; padding: 0; cursor: pointer; }}
    .trip-anchor-name:hover {{ color: #1271a8; text-decoration: underline; }}
    .trip-anchor-role {{ font-size: 0.8rem; font-weight: 600; color: var(--ab-fg-3); }}
    .trip-anchor-meta {{ display: block; font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-fg-3); margin-top: 2px; }}
    .trip-prox {{ font-family: var(--ab-mono); font-size: 0.66rem; color: #1271a8; margin: 3px 0 0; }}
    /* Solo trip (nothing tracked to batch) â€” a quiet note while we auto-scan. */
    .trip-nonear-note {{ font-size: 0.8rem; color: var(--ab-fg-3); font-style: italic; }}
    /* Proactive "found for you near <city>" inline results (auto area search). */
    .trip-auto {{ margin: 4px 0 2px; }}
    .trip-auto-head {{ font-size: 0.74rem; font-family: var(--ab-mono); letter-spacing: 0.04em; text-transform: uppercase; color: var(--ab-fg-3); margin: 2px 0 4px; }}
    .trip-auto-row {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 7px 10px; border: 1px solid var(--ab-rule); border-radius: 8px; margin-top: 6px; background: var(--ab-bg); }}
    .trip-auto-info {{ min-width: 0; }}
    .trip-auto-name {{ display: block; font-weight: 650; font-size: 0.9rem; color: var(--ab-fg); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .trip-auto-name a {{ color: var(--ab-blue); text-decoration: none; }}
    .trip-auto-meta {{ display: block; font-size: 0.78rem; color: var(--ab-fg-2); }}
    .trip-auto-add {{ flex: none; font-size: 0.78rem; padding: 5px 12px; }}
    .trip-auto-dup {{ flex: none; font-size: 0.72rem; color: var(--ab-fg-3); font-style: italic; }}
    /* Angela's Batch-your-trips is grouped by person: a name header, then that
       person's trips by date. */
    .trip-person {{ margin: 0 0 22px; }}
    .trip-person-name {{
      display: flex; align-items: baseline; gap: 8px;
      font-family: var(--ab-sans); font-size: 1rem; font-weight: 700;
      color: var(--ab-fg); margin: 0 0 10px;
      padding-bottom: 6px; border-bottom: 1px solid var(--ab-rule);
    }}
    .trip-person-count {{ font-size: 0.72rem; font-weight: 500; color: var(--ab-fg-3); }}
    .trip-person .trip-cluster {{ margin-bottom: 14px; }}
    .trip-person .trip-cluster:last-child {{ margin-bottom: 0; }}
    /* â”€â”€ My Profile view (bio, topics, past talks, files, notes) â”€â”€â”€â”€â”€ */
    .profile-wrap {{ max-width: 760px; }}
    .profile-card {{
      border: 1px solid var(--ab-rule); border-radius: 12px;
      background: var(--ab-bg); padding: 20px 22px; margin: 0 0 24px;
    }}
    .profile-card-head {{ display: flex; align-items: center; gap: 13px; padding: 0 0 18px; border-bottom: 1px solid var(--ab-rule); }}
    .profile-avatar {{
      width: 34px; height: 34px; border-radius: 50%; flex: 0 0 auto;
      display: grid; place-items: center; font-family: var(--ab-mono);
      font-weight: 700; font-size: 0.92rem; color: #fff; background: var(--ab-blue);
    }}
    .profile-avatar-lg {{ width: 46px; height: 46px; font-size: 1.2rem; }}
    .profile-id {{ display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
    .profile-who {{ font-family: var(--ab-sans); font-weight: 700; font-size: 1.15rem; color: var(--ab-fg); }}
    .profile-role {{ font-size: 0.82rem; color: var(--ab-fg-3); }}
    /* Section headers inside the profile (Speaking materials / About you). */
    .profile-section-head {{
      margin: 24px 0 2px; font-family: var(--ab-sans); font-weight: 800;
      font-size: 1.02rem; color: var(--ab-fg);
      display: flex; align-items: baseline; gap: 9px;
    }}
    .profile-section-sub {{ font-size: 0.83rem; color: var(--ab-fg-3); margin: 0 0 6px; }}
    .profile-section-opt {{ font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ab-mute); }}
    /* One speaking-material slot (Headshot / Slides / Bio & one-pagers / â€¦). */
    .profile-material {{
      border: 1px solid var(--ab-rule); border-radius: 9px; background: var(--ab-bg-2);
      padding: 12px 14px; margin: 10px 0 0;
    }}
    .profile-material-head {{ display: flex; align-items: baseline; gap: 9px; flex-wrap: wrap; margin: 0 0 8px; }}
    .profile-material-label {{ font-family: var(--ab-sans); font-weight: 700; font-size: 0.9rem; color: var(--ab-fg); }}
    .profile-material .profile-file {{ background: var(--ab-bg); }}
    .profile-field {{ margin: 17px 0 0; }}
    .profile-field label {{
      display: block; font-family: var(--ab-mono); font-size: 0.68rem; font-weight: 600;
      letter-spacing: 0.06em; text-transform: uppercase; color: var(--ab-fg-3); margin: 0 0 5px;
    }}
    .profile-field label .hint {{ text-transform: none; letter-spacing: 0; color: var(--ab-mute); font-weight: 500; }}
    .profile-field textarea {{
      width: 100%; box-sizing: border-box; resize: vertical; min-height: 62px;
      font-family: var(--ab-sans); font-size: 0.9rem; line-height: 1.5; color: var(--ab-fg);
      padding: 9px 12px; border: 1px solid var(--ab-rule-strong); border-radius: 8px;
      background: var(--ab-bg-2);
    }}
    .profile-field textarea:focus {{ outline: none; border-color: var(--ab-blue); background: var(--ab-bg); box-shadow: 0 0 0 3px rgba(39,115,194,0.1); }}
    /* About-you: saved bio (hover-pencil) + list editors (add/edit/delete). */
    .pf-field {{ margin: 18px 0 0; }}
    .pf-fieldhead {{ font-family: var(--ab-mono); font-size: 0.68rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ab-fg-3); margin: 0 0 6px; }}
    .pf-fieldhead .hint {{ text-transform: none; letter-spacing: 0; color: var(--ab-mute); font-weight: 500; }}
    .pf-input {{ width: 100%; box-sizing: border-box; font-family: var(--ab-sans); font-size: 0.9rem; line-height: 1.5; color: var(--ab-fg); padding: 8px 11px; border: 1px solid var(--ab-rule-strong); border-radius: 8px; background: var(--ab-bg); }}
    .pf-input:focus {{ outline: none; border-color: var(--ab-blue); box-shadow: 0 0 0 3px rgba(39,115,194,0.1); }}
    textarea.pf-input {{ resize: vertical; min-height: 70px; }}
    /* Auto-growing fields: start at one line, wrap onto the next as they fill.
       These were single-line <input>s, so a long note scrolled sideways as one
       string with the start of it out of sight (Hurley 2026-07-31). */
    textarea.pf-input.pf-grow {{
      min-height: 0; resize: none; overflow: hidden; white-space: pre-wrap; word-break: break-word;
    }}
    .pf-edit-actions {{ display: flex; gap: 8px; margin-top: 8px; }}
    .pf-saved {{ position: relative; border: 1px solid var(--ab-rule); border-radius: 8px; padding: 12px 42px 12px 14px; background: var(--ab-bg); }}
    .pf-saved-text {{ font-size: 0.9rem; color: var(--ab-fg-2); line-height: 1.5; white-space: pre-wrap; word-break: break-word; }}
    .pf-edit {{ position: absolute; top: 8px; right: 8px; width: 28px; height: 28px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--ab-rule); border-radius: 6px; background: var(--ab-bg); color: var(--ab-fg-3); cursor: pointer; opacity: 0; transition: opacity 120ms ease, color 120ms ease, border-color 120ms ease; }}
    .pf-saved:hover .pf-edit, .pf-edit:focus-visible {{ opacity: 1; }}
    .pf-edit:hover {{ color: var(--ab-blue); border-color: var(--ab-blue); }}
    .pf-edit svg {{ width: 14px; height: 14px; }}
    .pf-add-btn {{ font-size: 0.86rem; color: var(--ab-blue); background: none; border: 1px dashed var(--ab-rule-strong); border-radius: 8px; padding: 9px 12px; width: 100%; text-align: left; cursor: pointer; }}
    .pf-add-btn:hover {{ border-color: var(--ab-blue); background: var(--ab-bg-3); }}
    .pf-item {{ display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--ab-rule); border-radius: 8px; background: var(--ab-bg); margin-top: 6px; }}
    .pf-item-text {{ flex: 1; min-width: 0; font-size: 0.9rem; color: var(--ab-fg-2); line-height: 1.4; white-space: pre-wrap; word-break: break-word; }}
    .pf-item-btn {{ flex: 0 0 auto; width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--ab-rule); border-radius: 6px; background: var(--ab-bg); color: var(--ab-fg-3); cursor: pointer; opacity: 0; transition: opacity 120ms ease, color 120ms ease, border-color 120ms ease; }}
    .pf-item:hover .pf-item-btn, .pf-item-btn:focus-visible {{ opacity: 1; }}
    .pf-item-btn:hover {{ color: var(--ab-blue); border-color: var(--ab-blue); }}
    .pf-item-btn.pf-del:hover {{ color: var(--ab-red); border-color: var(--ab-red); }}
    .pf-item-btn svg {{ width: 13px; height: 13px; }}
    .pf-item--edit .pf-input {{ flex: 1; }}
    .pf-additem {{ display: flex; gap: 8px; margin-top: 7px; }}
    .pf-additem .pf-input {{ flex: 1; }}
    .pf-additem .pf-add {{ flex: 0 0 auto; }}
    .profile-actions {{ display: flex; align-items: center; gap: 13px; margin: 19px 0 0; }}
    .profile-saved-note {{ font-size: 0.78rem; color: var(--ab-green); font-weight: 600; }}
    .profile-files {{ margin: 8px 0 0; display: flex; flex-direction: column; gap: 7px; }}
    .profile-file {{
      display: flex; align-items: center; gap: 10px; padding: 8px 12px;
      border: 1px solid var(--ab-rule); border-radius: 8px; background: var(--ab-bg-2);
    }}
    .profile-file-name {{ font-size: 0.86rem; color: var(--ab-fg); font-weight: 600; word-break: break-all; flex: 1; text-decoration: none; }}
    .profile-file-name:hover {{ color: var(--ab-blue); text-decoration: underline; }}
    /* The file name is now a PREVIEW button (opens a viewer, never downloads). */
    .profile-file-name.profile-file-open {{ background: none; border: 0; padding: 0; font-family: inherit; text-align: left; cursor: pointer; }}
    .profile-file--link .profile-file-name {{ color: var(--ab-blue); }}
    .profile-file-size {{ font-family: var(--ab-mono); font-size: 0.7rem; color: var(--ab-fg-3); white-space: nowrap; }}
    .profile-file-empty {{ font-size: 0.84rem; color: var(--ab-fg-3); font-style: italic; }}
    /* Download icon â€” the ONLY thing that downloads a file now. */
    .profile-file-dl {{
      display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
      width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
      color: var(--ab-fg-3); background: var(--ab-bg); border: 1px solid var(--ab-rule);
      transition: color 120ms ease, border-color 120ms ease;
    }}
    .profile-file-dl svg {{ width: 15px; height: 15px; }}
    .profile-file-dl:hover {{ color: var(--ab-blue); border-color: var(--ab-blue); }}
    /* Rename-a-link (pencil) â€” same icon-button shape as download. */
    .profile-file-ren {{
      display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
      width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
      color: var(--ab-fg-3); background: var(--ab-bg); border: 1px solid var(--ab-rule);
      transition: color 120ms ease, border-color 120ms ease;
    }}
    .profile-file-ren svg {{ width: 14px; height: 14px; }}
    .profile-file-ren:hover {{ color: var(--ab-blue); border-color: var(--ab-blue); }}
    /* Delete-a-file button â€” clearly a delete: trash icon + label, reddens on hover. */
    .profile-file-del {{
      display: inline-flex; align-items: center; gap: 5px; flex: 0 0 auto; white-space: nowrap;
      font-family: var(--ab-sans); font-size: 0.76rem; font-weight: 600;
      padding: 5px 9px; border-radius: 6px; cursor: pointer;
      color: var(--ab-fg-3); background: var(--ab-bg); border: 1px solid var(--ab-rule);
      transition: color 120ms ease, border-color 120ms ease, background 120ms ease;
    }}
    .profile-file-del svg {{ width: 14px; height: 14px; }}
    .profile-file-del:hover {{ color: #b91c1c; border-color: #e5a5a5; background: #fdf3f3; }}
    .profile-upload-row {{ display: flex; align-items: center; gap: 10px; margin: 11px 0 0; flex-wrap: wrap; }}
    .profile-upload-row input[type=file] {{ font-size: 0.82rem; color: var(--ab-fg-2); max-width: 100%; }}
    /* Push "Upload" to the right edge so it sits right above/aligned with "Add link". */
    .profile-upload-row .q-btn {{ margin-left: auto; }}
    /* Paste a Google Drive / Doc link instead of (or as well as) uploading. */
    .profile-link-row {{ display: flex; align-items: center; gap: 10px; margin: 7px 0 0; flex-wrap: wrap; }}
    .profile-link-row input {{ flex: 1; min-width: 160px; font-size: 0.84rem; padding: 7px 10px; border: 1px solid var(--ab-rule-strong); border-radius: 6px; font-family: inherit; }}
    .profile-link-row input.pf-link-title {{ flex: 0 1 150px; min-width: 110px; }}
    .profile-teammate {{
      border: 1px solid var(--ab-rule); border-radius: 10px; background: var(--ab-bg);
      padding: 14px 16px; margin: 0 0 10px;
    }}
    .profile-tm-head {{ display: flex; align-items: center; gap: 9px; margin: 0 0 6px; }}
    .profile-tm-name {{ font-weight: 700; font-size: 0.96rem; color: var(--ab-fg); text-decoration: none; }}
    a.profile-tm-name:hover {{ color: var(--ab-blue); text-decoration: underline; }}
    /* Full LinkedIn URL, right under the name â€” copy/paste-ready for Angela. */
    .profile-tm-linkedin {{ display: block; font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-blue); word-break: break-all; margin: -2px 0 8px; text-decoration: none; }}
    .profile-tm-linkedin:hover {{ text-decoration: underline; }}
    .profile-tm-role {{ font-size: 0.76rem; color: var(--ab-fg-3); margin-left: auto; text-align: right; }}
    .profile-tm-field {{ margin: 8px 0 0; }}
    .profile-tm-field .k {{ font-family: var(--ab-mono); font-size: 0.63rem; letter-spacing: 0.05em; text-transform: uppercase; color: var(--ab-fg-3); }}
    .profile-tm-field .v {{ font-size: 0.86rem; color: var(--ab-fg-2); line-height: 1.5; white-space: pre-wrap; margin: 2px 0 0; }}
    .profile-tm-files {{ margin: 3px 0 0; display: flex; flex-direction: column; gap: 8px; }}
    .tm-mat-group {{ display: flex; flex-direction: column; gap: 5px; }}
    .tm-mat-label {{ font-family: var(--ab-mono); font-size: 0.58rem; letter-spacing: 0.05em; text-transform: uppercase; color: var(--ab-mute); }}
    .profile-tm-empty {{ font-size: 0.82rem; color: var(--ab-mute); font-style: italic; }}
    .profile-setup-note {{
      border: 1px solid #f0d9a8; background: #fdf6e8; border-radius: 8px;
      padding: 11px 14px; font-size: 0.83rem; color: #8a6d1f; margin: 0 0 18px; line-height: 1.5;
    }}
    .q-btn-x {{
      flex: 0 0 auto; padding: 5px 10px; font-size: 1rem; line-height: 1;
      font-weight: 700; color: var(--ab-fg-3);
    }}
    .queue-empty, .planner-empty {{
      padding: 20px; border: 1px dashed var(--ab-rule); border-radius: 10px;
      color: var(--ab-fg-3); font-size: 0.9rem; text-align: center;
    }}

    /* â”€â”€ Planner view (conflicts + coverage gaps) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    .planner-section {{ margin: 0 0 30px; }}
    .conn-help {{ font-size: 0.82rem; color: var(--ab-fg-2); margin: 4px 0 8px; line-height: 1.45; }}
    .conn-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .conn-row select, .conn-row input[type=file] {{ padding: 6px 8px; border: 1px solid var(--ab-rule); border-radius: 6px; font-size: 0.85rem; background: var(--ab-bg); }}
    .conn-status {{ font-size: 0.8rem; color: var(--ab-fg-2); }}
    .conn-counts {{ font-size: 0.8rem; color: var(--ab-fg-3); margin-top: 8px; }}
    .planner-sec-head {{
      display: flex; align-items: baseline; gap: 10px; margin: 0 0 12px;
      padding-bottom: 6px; border-bottom: 1px solid var(--ab-rule);
    }}
    .planner-sec-title {{ font-family: var(--ab-sans); font-weight: 700; font-size: 1.05rem; color: var(--ab-fg); }}
    .planner-sec-sub {{ font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-fg-3); }}
    .conflict-row {{
      display: flex; align-items: flex-start; gap: 10px; padding: 12px 14px; margin: 0 0 8px;
      border: 1px solid rgba(214,69,69,0.35); border-radius: 10px; background: rgba(214,69,69,0.05);
    }}
    .conflict-icon {{ font-size: 1.1rem; line-height: 1.3; }}
    .conflict-body {{ min-width: 0; font-size: 0.88rem; color: var(--ab-fg); }}
    .conflict-who {{ font-weight: 700; }}
    .conflict-vs {{ display: block; margin-top: 4px; color: var(--ab-fg-2); font-size: 0.84rem; }}
    .conflict-evt {{
      background: none; border: 0; padding: 0; cursor: pointer; color: #1271a8;
      font: inherit; font-weight: 600; text-align: left; text-decoration: underline;
    }}
    .conflict-evt:hover {{ color: #0e5a86; }}
    .gap-owner {{ margin: 0 0 18px; border: 1px solid var(--ab-rule); border-radius: 12px; overflow: hidden; }}
    .gap-owner-head {{
      display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px;
      padding: 11px 14px; background: var(--ab-bg-3);
    }}
    .gap-owner-name {{ font-family: var(--ab-sans); font-weight: 700; font-size: 0.98rem; color: var(--ab-fg); }}
    .gap-owner-terr {{ font-size: 0.82rem; color: var(--ab-fg-2); }}
    .gap-owner-stat {{ font-family: var(--ab-mono); font-size: 0.7rem; color: var(--ab-fg-3); margin-left: auto; }}
    .gap-owner-stat b {{ color: #d64545; }}
    .gap-list {{ padding: 6px 14px 12px; }}
    .gap-row {{
      display: grid; grid-template-columns: 1fr auto; gap: 4px 12px;
      align-items: center; padding: 9px 0; border-bottom: 1px solid var(--ab-rule);
    }}
    .gap-row:last-child {{ border-bottom: 0; }}
    .gap-actions {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }}
    .gap-name {{
      background: none; border: 0; padding: 0; cursor: pointer; text-align: left;
      font-family: var(--ab-sans); font-weight: 600; font-size: 0.9rem; color: var(--ab-fg);
    }}
    .gap-name:hover {{ color: #1fa0dc; text-decoration: underline; }}
    .gap-meta {{ font-size: 0.78rem; color: var(--ab-fg-3); margin-top: 2px; }}
    .gap-none {{ padding: 10px 14px; font-size: 0.85rem; color: var(--ab-fg-3); }}
    .gap-more {{ padding: 8px 14px 0; font-size: 0.78rem; color: var(--ab-fg-3); }}

    /* Calendar view */
    .ops-calendar {{ display: none; }}
    .ops-calendar.show {{ display: block; }}
    /* Map view â€” Leaflet canvas, lazy-loaded on first open. */
    .ops-map {{ display: none; }}
    .ops-map.show {{ display: block; }}
    #ops-map-canvas {{
      height: 640px; border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg-2);
    }}
    /* Click a pin â†’ events slide into this right-hand panel (Angela-style). */
    .map-wrap {{ position: relative; }}
    .map-sidebar {{
      position: absolute; top: 0; right: 0; height: 100%; width: 380px; max-width: 84%;
      background: var(--ab-bg); border-left: 1px solid var(--ab-rule);
      border-radius: 0 10px 10px 0; box-shadow: -10px 0 28px rgba(0,0,0,0.14);
      display: flex; flex-direction: column; overflow: hidden; z-index: 500;
      animation: msb-in 160ms ease-out;
    }}
    .map-sidebar[hidden] {{ display: none; }}
    @keyframes msb-in {{ from {{ transform: translateX(16px); opacity: 0; }} to {{ transform: none; opacity: 1; }} }}
    .map-sidebar-head {{
      display: flex; align-items: center; gap: 9px;
      padding: 16px 16px 14px 20px; border-bottom: 1px solid var(--ab-rule);
    }}
    .msb-title {{ font-family: var(--ab-sans); font-weight: 700; font-size: 1.05rem; color: var(--ab-fg); }}
    .msb-count {{
      font-family: var(--ab-mono); font-size: 0.72rem; font-weight: 700;
      background: var(--ab-blue); color: #fff; border-radius: 999px;
      min-width: 22px; height: 22px; padding: 0 7px;
      display: inline-flex; align-items: center; justify-content: center;
    }}
    .msb-close {{
      margin-left: auto; border: 0; background: transparent; cursor: pointer;
      font-size: 1.4rem; line-height: 1; color: var(--ab-fg-3); padding: 2px 6px; border-radius: 6px;
    }}
    .msb-close:hover {{ color: var(--ab-fg); background: var(--ab-bg-3); }}
    .map-sidebar-list {{ overflow-y: auto; flex: 1; }}
    .map-sb-ev {{
      display: flex; align-items: flex-start; gap: 12px; justify-content: space-between;
      width: 100%; text-align: left; border: 0; background: transparent; cursor: pointer;
      padding: 13px 18px; border-bottom: 1px solid var(--ab-rule);
      font-family: var(--ab-sans);
    }}
    .map-sb-ev:hover {{ background: var(--ab-bg-3); }}
    .map-sb-ev.past {{ opacity: 0.5; }}      /* past event â€” grayed, sorted below upcoming */
    .map-sb-ev.past:hover {{ opacity: 0.75; }}
    .map-sb-ev .nm {{ font-size: 0.92rem; line-height: 1.35; color: var(--ab-fg); font-weight: 500; }}
    .map-sb-ev .meta {{ display: flex; flex-direction: column; align-items: flex-end; gap: 5px; flex-shrink: 0; }}
    .map-sb-ev .dt {{ font-family: var(--ab-mono); font-size: 0.74rem; color: var(--ab-fg-3); white-space: nowrap; }}
    .msb-badge {{
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 700;
      padding: 2px 7px; border-radius: 3px; white-space: nowrap; letter-spacing: 0.02em;
    }}
    .map-popup .map-ev {{ margin: 0 0 6px; font-size: 0.85rem; line-height: 1.35; }}
    .map-popup .map-ev a {{ color: var(--ab-blue, #1d4ed8); cursor: pointer; text-decoration: underline; }}
    .map-popup .map-ev .d {{ color: #666; font-family: var(--ab-mono); font-size: 0.72rem; }}
    .map-popup .map-city {{
      margin: 0 0 8px; font-family: var(--ab-mono); font-size: 0.68rem;
      letter-spacing: 0.1em; text-transform: uppercase; color: #666;
    }}
    /* Cluster-style pins: one consistent brand blue everywhere (region data
       is too patchy to color-code by); a soft halo gives them depth. */
    .map-pin {{
      display: flex; align-items: center; justify-content: center;
      width: 100%; height: 100%; border-radius: 50%;
      background: #2773c2;
      color: #fff; font-family: var(--ab-mono); font-weight: 700;
      font-size: 0.78rem; letter-spacing: -0.02em;
      border: 2.5px solid #fff;
      box-shadow: 0 0 0 4px rgba(39, 115, 194, 0.25), 0 2px 6px rgba(0,0,0,0.3);
      box-sizing: border-box;
      transition: transform 0.1s ease;
    }}
    .map-pin:hover {{ transform: scale(1.12); }}
    .map-pin.single {{ font-size: 0; }}  /* lone event: clean dot, no number */
    /* Past-only location: grayed so upcoming-event pins clearly stand out. */
    .map-pin.past {{
      background: #9ca3af;
      box-shadow: 0 0 0 4px rgba(156, 163, 175, 0.22), 0 2px 6px rgba(0,0,0,0.25);
    }}
    .calendar-month {{ margin-bottom: 32px; }}
    /* Calendar month nav: â€¹ prev on the left, month/year dropdown centered,
       next â€º on the right. The grid columns keep the dropdown truly centered. */
    .cal-nav {{
      display: grid; grid-template-columns: 40px 1fr 40px;
      align-items: center; gap: 12px; margin-bottom: 18px;
    }}
    .cal-navbtn {{
      width: 40px; height: 40px; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
      border: 1px solid var(--ab-rule-strong); border-radius: 10px;
      background: var(--ab-bg); color: var(--ab-fg-2);
      font-size: 1.4rem; line-height: 1; cursor: pointer;
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
    }}
    .cal-navbtn:hover {{ background: var(--ab-bg-3); color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    #cal-next.cal-navbtn {{ justify-self: end; }}
    .cal-month-select {{
      justify-self: center; text-align: center; text-align-last: center;
      font-family: "Nunito Sans", var(--ab-sans); font-weight: 800; font-size: 1.15rem;
      color: var(--ab-fg); background: var(--ab-bg);
      border: 1px solid var(--ab-rule); border-radius: 10px;
      padding: 9px 18px; cursor: pointer;
      transition: border-color 120ms ease, box-shadow 120ms ease;
    }}
    .cal-month-select:hover {{ border-color: var(--ab-fg-3); }}
    .cal-month-select:focus {{ outline: none; border-color: var(--ab-blue); box-shadow: 0 0 0 3px rgba(39,115,194,0.12); }}
    /* `minmax(0, 1fr)` is the standard fix to keep grid cells from
       overflowing their tracks when chip text would otherwise force a
       column wider than 1fr. Pair with `min-width: 0; overflow: hidden`
       on each cell so the cell respects its track width and the chips
       inside ellipsis-clip correctly. */
    .ops-calendar {{ overflow-x: auto; }}
    .calendar-grid {{
      border: 1px solid var(--ab-rule); border-radius: 8px; overflow: hidden;
      min-width: 700px;  /* horizontal-scroll kicks in below this on mobile */
      width: 100%; background: var(--ab-bg);
    }}
    .cal-weekhead {{
      display: grid; grid-template-columns: repeat(7, minmax(0, 1fr));
      background: var(--ab-bg-2);
    }}
    .calendar-day-head {{
      padding: 8px; font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase; text-align: center; min-width: 0; overflow: hidden;
    }}
    /* Each week is its own 7-column grid. Day backgrounds span every row, so the
       date numbers (row 1) and event lanes (rows 2+) layer on top. A multi-day
       event is ONE element spanning its day columns â€” genuinely contiguous,
       with room for the full name. */
    .cal-week {{
      display: grid; grid-template-columns: repeat(7, minmax(0, 1fr));
      grid-auto-rows: min-content; min-height: 106px;
    }}
    .cal-day-bg {{
      border-top: 1px solid var(--ab-rule); border-right: 1px solid var(--ab-rule);
      background: var(--ab-bg);
    }}
    .cal-day-bg.is-outside {{ background: var(--ab-bg-3); }}
    .cal-day-bg.is-today {{ background: rgba(39,115,194,0.06); }}
    .cal-daynum {{
      font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-fg-3);
      padding: 5px 0 3px 8px; position: relative; z-index: 1; pointer-events: none;
    }}
    .cal-daynum.is-outside {{ color: var(--ab-mute); }}
    .cal-evt {{
      position: relative; z-index: 2; margin: 1px 4px 2px; min-height: 21px;
      display: flex; align-items: center; gap: 5px; padding: 2px 8px;
      border-radius: 5px; background: var(--ab-bg);
      border: 1px solid var(--ab-rule);
      border-left: 3px solid var(--ab-rule-strong);
      font-family: var(--ab-sans); font-size: 0.74rem; line-height: 1.2;
      cursor: pointer; overflow: hidden; white-space: nowrap;
      transition: filter 120ms ease;
    }}
    .cal-evt:hover {{ filter: brightness(0.96); }}
    .cal-evt:focus-visible {{ outline: 2px solid var(--ab-blue); outline-offset: 1px; }}
    .cal-evt.is-saved {{ background: rgba(39,115,194,0.12); border-left-color: var(--ab-blue); }}
    .cal-evt.is-urgent {{ background: rgba(185,28,28,0.10); border-left-color: var(--ab-red); }}
    body.hide-urgent .cal-evt.is-urgent {{ background: transparent; border-left-color: var(--ab-rule); }}

    /* Calendar legend â€” shows status-group color meanings under the grid */
    .cal-legend {{
      display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
      margin-top: 12px; padding: 10px 12px;
      border: 1px solid var(--ab-rule); border-radius: 8px;
      background: var(--ab-bg);
    }}
    .cal-legend-label {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase; margin-right: 4px;
    }}
    .cal-legend-item {{
      display: inline-flex; align-items: center; gap: 6px;
      font-family: var(--ab-mono); font-size: 0.72rem;
      color: var(--ab-fg-2);
    }}
    .cal-legend-dot {{
      width: 8px; height: 8px; border-radius: 50%;
    }}
    /* Stage swatches in the legend render as the SAME pill shown on events,
       so the legend reads exactly like what's on the calendar. */
    .cal-legend-pill {{
      font-family: var(--ab-mono); font-size: 0.62rem; font-weight: 600;
      padding: 2px 7px; border-radius: 3px; letter-spacing: 0.02em;
    }}
    .cal-legend-sep {{
      width: 1px; height: 16px; background: var(--ab-rule); margin: 0 2px;
    }}
    .cal-evt-name {{ flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ab-fg); font-weight: 500; }}
    .cal-chip-initial {{
      display: inline-block; background: var(--ab-fg); color: var(--ab-bg);
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 600;
      border-radius: 50%; width: 16px; height: 16px;
      line-height: 16px; text-align: center; flex-shrink: 0;
    }}
    .cal-evt-status {{
      font-family: var(--ab-mono); font-size: 0.58rem; font-weight: 600;
      padding: 1px 5px; border-radius: 3px; flex-shrink: 0;
      letter-spacing: 0.02em;
    }}
    .cal-region-dot {{
      width: 6px; height: 6px; border-radius: 50%;
      display: inline-block; flex-shrink: 0;
    }}

    .ops-card.is-highlight {{
      animation: ops-highlight 1600ms ease-out;
    }}
    @keyframes ops-highlight {{
      0%   {{ box-shadow: 0 0 0 0 rgba(39,115,194,0); }}
      20%  {{ box-shadow: 0 0 0 6px rgba(39,115,194,0.3); border-color: var(--ab-blue); }}
      100% {{ box-shadow: 0 0 0 0 rgba(39,115,194,0); }}
    }}

    /* Toolbar with + Add event â€” pastel-icon style adopted from joes-fac.
       Each ab-btn picks one pastel color family. */
    .ops-toolbar {{
      display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
      margin-bottom: 18px;
    }}
    .ab-btn {{
      display: inline-flex; align-items: center; gap: 8px;
      padding: 8px 12px;
      font-family: var(--ab-sans); font-weight: 500;
      font-size: 0.875rem; line-height: 1;
      border: 0; border-radius: 8px;
      cursor: pointer;
      transition: background-color 150ms ease, color 150ms ease;
      white-space: nowrap;
    }}
    .ab-btn[disabled] {{ opacity: 0.5; cursor: not-allowed; }}
    .ab-btn .ab-btn__icon {{ width: 16px; height: 16px; flex-shrink: 0; }}
    /* Color variants â€” pastel bg + saturated text + slightly-darker hover bg */
    .ab-btn--emerald  {{ background: #ecfdf5; color: #047857; }}
    .ab-btn--emerald:hover  {{ background: #d1fae5; }}
    .ab-btn--blue     {{ background: #eff6ff; color: #1d4ed8; }}
    .ab-btn--blue:hover     {{ background: #dbeafe; }}
    .ab-btn--purple   {{ background: #faf5ff; color: #7e22ce; }}
    .ab-btn--purple:hover   {{ background: #f3e8ff; }}
    .ab-btn--amber    {{ background: #fffbeb; color: #b45309; }}
    .ab-btn--amber:hover    {{ background: #fef3c7; }}
    .ab-btn--indigo   {{ background: #eef2ff; color: #4338ca; }}
    .ab-btn--indigo:hover   {{ background: #e0e7ff; }}
    .ab-btn--rose     {{ background: #fff1f2; color: #be123c; }}
    .ab-btn--rose:hover     {{ background: #ffe4e6; }}
    /* Hierarchy: ONE solid primary (Add event); everything else is a quiet
       ghost that keeps its color identity in the text/icon only. */
    .ab-btn.ab-btn--primary {{ background: #047857; color: #fff; font-weight: 600; }}
    .ab-btn.ab-btn--primary:hover {{ background: #065f46; }}
    .ab-btn.ab-btn--ghost {{ background: var(--ab-bg); border: 1px solid var(--ab-rule-strong); }}
    .ab-btn.ab-btn--ghost:hover {{ background: var(--ab-bg-3); }}
    /* Ask AI â€” a gentle gradient accent so it reads as the smart assistant. */
    .ab-btn.ab-btn--ask {{
      background: linear-gradient(90deg, #eef2ff, #faf5ff); color: #6d28d9;
      border: 1px solid #ddd6fe; font-weight: 600;
    }}
    .ab-btn.ab-btn--ask:hover {{ background: linear-gradient(90deg, #e0e7ff, #f3e8ff); }}
    /* "+ Add" dropdown â€” the three add paths (manual / find new / paste email)
       folded behind one primary button. */
    .ops-add-wrap {{ position: relative; display: inline-block; }}
    .ab-btn__caret {{ width: 14px; height: 14px; flex-shrink: 0; margin-left: -2px; opacity: 0.85; }}
    #add-menu-btn[aria-expanded="true"] .ab-btn__caret {{ transform: rotate(180deg); }}
    .ops-add-menu {{
      position: absolute; top: calc(100% + 6px); right: 0; left: auto; z-index: 40;
      min-width: 248px; max-width: min(320px, calc(100vw - 24px)); padding: 6px;
      background: var(--ab-bg); border: 1px solid var(--ab-rule-strong);
      border-radius: 12px; box-shadow: 0 12px 32px rgba(15, 23, 42, 0.14);
      display: flex; flex-direction: column; gap: 2px;
    }}
    .ops-add-menu[hidden] {{ display: none; }}
    .ops-add-item {{
      display: flex; align-items: flex-start; gap: 10px; width: 100%;
      padding: 9px 10px; border: 0; border-radius: 8px; background: transparent;
      cursor: pointer; text-align: left; font-family: var(--ab-sans);
      transition: background-color 120ms ease;
    }}
    .ops-add-item:hover, .ops-add-item:focus-visible {{ background: var(--ab-bg-3); outline: none; }}
    .ops-add-item__icon {{ width: 18px; height: 18px; flex-shrink: 0; margin-top: 1px; color: #047857; }}
    .ops-add-item__txt {{ display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
    .ops-add-item__t {{ font-size: 0.875rem; font-weight: 600; color: var(--ab-fg); line-height: 1.2; }}
    .ops-add-item__d {{ font-size: 0.75rem; color: var(--ab-fg-3); line-height: 1.2; }}
    /* Pressed state while a feature's panel is open â€” click again to close. */
    .ab-btn.is-open {{ box-shadow: 0 0 0 2px currentColor; }}
    .ab-btn.ab-btn--primary.is-open {{ box-shadow: 0 0 0 2px #047857, 0 0 0 4px #d1fae5; }}
    /* Toolbar clusters: what ADDS events vs what SYNCS them out. */
    .ops-toolbar-group {{
      display: inline-flex; align-items: center; gap: 8px;
      padding: 6px 10px 6px 12px;
      border: 1px solid var(--ab-rule); border-radius: 12px;
      background: var(--ab-bg-2);
    }}
    .ops-toolbar-label {{
      font-family: var(--ab-mono); font-size: 0.62rem;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: var(--ab-fg-3); margin-right: 2px; user-select: none;
    }}

    /* Row 1 â€” primary nav: underlined text tabs on the left; the tracked/manual
       caption, Sync (Angela) and Add on the right. The bottom hairline is the
       tab track the active tab's border sits on. */
    .ops-controls-row {{
      display: flex; flex-wrap: wrap; align-items: flex-end;
      justify-content: space-between; gap: 10px 16px;
      border-bottom: 1px solid var(--ab-rule); margin-bottom: 16px;
    }}
    .ops-controls-right {{
      display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
      padding-bottom: 6px;   /* lift off the hairline, in line with the tab text */
    }}
    .ops-navcount {{
      font-family: var(--ab-mono); font-size: 0.72rem;
      color: var(--ab-fg-3); letter-spacing: 0.04em; white-space: nowrap;
    }}
    /* Results header â€” the tracked/manual count sits above the grid. */
    .ops-results-header {{
      display: flex; align-items: center; justify-content: flex-end;
      gap: 10px; margin: 0 0 16px;
    }}
    .ops-results-header .ops-count {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
    }}
    /* "Review duplicates" toggle â€” clickable, so it follows the underlined-pill
       convention. Sits at the left of the results header (count stays right). */
    .ops-dupe-review {{
      margin-right: auto; cursor: pointer;
      font-family: var(--ab-mono); font-size: 0.62rem; letter-spacing: 0.05em;
      text-transform: uppercase; padding: 4px 13px; border-radius: 999px;
      text-decoration: underline; text-underline-offset: 2px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-2);
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
    }}
    .ops-dupe-review:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    body.review-dupes .ops-dupe-review {{ background: var(--ab-red); color: #fff; border-color: var(--ab-red); }}
    /* Revealed duplicate cards get a clear (rectangular) DUPLICATE tag + dashed ring. */
    body.review-dupes .ops-card.is-dupe {{ outline: 2px dashed var(--ab-red); outline-offset: -2px; }}
    body.review-dupes .ops-card.is-dupe::before {{
      content: 'DUPLICATE'; position: absolute; top: 0; right: 0; z-index: 3;
      font-family: var(--ab-mono); font-size: 0.56rem; font-weight: 700; letter-spacing: 0.08em;
      padding: 3px 8px; border-radius: 0 9px 0 6px; background: var(--ab-red); color: #fff;
    }}
    /* Loose pass-3 match: flagged for a human to judge, never auto-hidden. */
    body.review-dupes .ops-card[data-dup-maybe="1"] {{ outline: 2px dashed #b45309; outline-offset: -2px; }}
    body.review-dupes .ops-card[data-dup-maybe="1"]::before {{
      content: 'POSSIBLE'; position: absolute; top: 0; right: 0; z-index: 3;
      font-family: var(--ab-mono); font-size: 0.56rem; font-weight: 700; letter-spacing: 0.08em;
      padding: 3px 8px; border-radius: 0 9px 0 6px; background: #b45309; color: #fff;
    }}
    /* Overdue review nudge (3 days) */
    .ops-dupe-review.due {{ border-color: var(--ab-red); color: var(--ab-red); font-weight: 700; }}
    /* The event a duplicate was matched AGAINST â€” shown alongside it in review
       mode so the pair can be compared, and tagged so it's obvious which one the
       tracker is keeping. */
    body.review-dupes .ops-card[data-dup-keeper="1"] {{ outline: 2px solid var(--ab-fg-3); outline-offset: -2px; }}
    body.review-dupes .ops-card[data-dup-keeper="1"]::before {{
      content: 'KEEPING'; position: absolute; top: 0; right: 0; z-index: 3;
      font-family: var(--ab-mono); font-size: 0.56rem; font-weight: 700; letter-spacing: 0.08em;
      padding: 3px 8px; border-radius: 0 9px 0 6px; background: var(--ab-fg-3); color: #fff;
    }}

    /* Flexible date text field + click-to-open calendar popup (single or range). */
    .date-pick {{ position: relative; }}
    .date-pick .date-flex-input {{ width: 100%; }}
    .date-cal {{
      position: absolute; z-index: 60; top: calc(100% + 4px); left: 0;
      width: 268px; padding: 10px; background: var(--ab-bg);
      border: 1px solid var(--ab-rule); border-radius: 10px;
      box-shadow: 0 10px 28px rgba(0,0,0,0.14);
    }}
    .dc-head {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }}
    .dc-title {{ font-family: "Nunito Sans", var(--ab-sans); font-weight: 800; font-size: 0.9rem; color: var(--ab-fg); }}
    .dc-nav {{ width: 28px; height: 28px; border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); border-radius: 6px; cursor: pointer; font-size: 1.05rem; line-height: 1; color: var(--ab-fg-2); }}
    .dc-nav:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .dc-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }}
    .dc-dow {{ text-align: center; font-family: var(--ab-mono); font-size: 0.58rem; color: var(--ab-fg-3); padding: 2px 0; }}
    .dc-day {{ border: 0; background: none; cursor: pointer; padding: 6px 0; border-radius: 6px; font-size: 0.8rem; color: var(--ab-fg); }}
    .dc-day:hover {{ background: var(--ab-bg-3); }}
    .dc-empty {{ visibility: hidden; }}
    .dc-inrange {{ background: rgba(39,115,194,0.14); border-radius: 0; }}
    .dc-start, .dc-end, .dc-single {{ background: var(--ab-blue); color: #fff; }}
    .dc-start {{ border-radius: 6px 0 0 6px; }}
    .dc-end {{ border-radius: 0 6px 6px 0; }}
    .dc-single {{ border-radius: 6px; }}
    .dc-foot {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; }}
    .dc-hint {{ font-size: 0.6rem; font-style: italic; color: var(--ab-fg-3); }}
    .dc-clear, .dc-done {{ border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); border-radius: 6px; padding: 4px 10px; font-size: 0.7rem; cursor: pointer; color: var(--ab-fg-2); }}
    .dc-done {{ background: var(--ab-fg); color: var(--ab-bg); border-color: var(--ab-fg); }}
    .add-event-card {{
      /* When a panel scrolls into view, clear the sticky header + tab bar. */
      scroll-margin-top: 130px;
      grid-column: 1 / -1;
      position: relative;
      padding: 24px;
      border: 1px dashed var(--ab-blue); border-radius: 10px;
      background: var(--ab-bg);
      margin-bottom: 16px;
    }}
    /* Standard top-right dismiss on every toolbar panel (add / find / paste /
       ask / spreadsheet / calendar-sync). Also closable with Esc. */
    .ops-panel-x {{
      position: absolute; top: 12px; right: 12px;
      width: 30px; height: 30px; line-height: 1; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
      font-size: 1.3rem; border-radius: 8px; cursor: pointer;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-3);
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
    }}
    .ops-panel-x:hover {{ background: var(--ab-bg-3); color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .add-event-card h3 {{ padding-right: 40px; }}   /* clear the Ã— */
    .add-event-card h3 {{
      font-family: var(--ab-sans); font-weight: 700; font-size: 1.05rem;
      letter-spacing: -0.01em; margin: 0 0 12px;
    }}
    .add-event-card .add-actions {{
      display: flex; gap: 8px; margin-top: 12px;
    }}
    .add-event-card button.primary {{
      font-family: var(--ab-sans); font-weight: 600; font-size: 0.9rem;
      padding: 9px 16px; border-radius: 8px; border: 0;
      background: var(--ab-fg); color: var(--ab-bg); cursor: pointer;
    }}
    .add-event-card button.primary:hover {{ background: #262626; }}
    .add-event-card button.primary:disabled {{ background: var(--ab-mute); cursor: not-allowed; }}
    .add-event-card button.secondary {{
      font-family: var(--ab-sans); font-weight: 500; font-size: 0.9rem;
      padding: 9px 16px; border-radius: 8px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); cursor: pointer;
    }}
    .add-event-card button.secondary:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}

    /* â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ responsive â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    @media (max-width: 800px) {{
      .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
      .kpi:nth-child(2n) {{ border-right: 0; }}
      .kpi:nth-child(-n+2) {{ border-bottom: 1px solid var(--ab-rule); }}
      .kpi {{ padding: 20px 20px 20px 0; }}
      .filter-bar {{ flex-direction: column; align-items: stretch; }}
      .filter-group {{ min-width: 0; }}
      .ops-grid {{ grid-template-columns: 1fr; }}
    }}
    /* Touch screens: give the small card controls a tappable target. */
    @media (pointer: coarse) {{
      .ops-details-btn, .ops-chip {{ min-height: 40px; padding-top: 8px; padding-bottom: 8px; }}
      .bf-close, .saved-star {{ min-width: 40px; min-height: 40px; }}
    }}
    @media (max-width: 500px) {{
      .nav {{ padding: 16px 0; }}
      .hero {{ padding: 48px 0 40px; }}
      .today-card {{ padding: 20px 22px; }}
      .today-name {{ font-size: 1.4rem; }}
      .event {{ padding: 20px; }}
      h1 {{ font-size: 2.2rem; }}
    }}
  </style>
</head>
<body class="hide-urgent">

  <nav class="nav">
    <div class="nav-inner">
      <a class="brand" href="https://arcticblue.ai/" aria-label="ArcticBlue home">
        <!-- Root-absolute: this page is also served at /angela, where a
             relative "arcticblue-logo.png" would resolve to /angela/â€¦ and 404. -->
        <img src="/arcticblue-logo.png" alt="ArcticBlue" width="32" height="29">
      </a>
      <h1 class="app-title">ArcticBlue Event Tracker</h1>
      <div class="nav-meta"><span id="ab-today">{last_updated.upper()}</span> <span class="who">Â· <span class="who-switcher" id="who-switcher"></span></span></div>
    </div>
  </nav>

  <main class="wrap">
'''

    # Today / Up-next callout
    if today_evs:
        first_today = today_evs[0]
        today_section = f'''
    <section class="today-block">
      <div class="today-card">
        <div class="today-card-head">
          <p class="today-label">Happening today</p>
          <p class="today-date">{e(fmt_date(first_today))}</p>
        </div>
        <h2 class="today-name">{e(first_today["name"])}</h2>
        <p class="today-meta">{e(first_today.get("location",""))} Â· {e(first_today.get("type",""))}</p>
        {f'<p class="today-why">{e(first_today.get("why",""))}</p>' if first_today.get('why') else ''}
      </div>
    </section>'''
    elif next_up:
        days_to_next = (next_up['_start'] - TODAY).days
        today_section = f'''
    <section class="today-block">
      <div class="today-card">
        <div class="today-card-head">
          <p class="today-label">No events today Â· Next up in {days_to_next} day{"s" if days_to_next != 1 else ""}</p>
          <p class="today-date">{e(fmt_date(next_up))}</p>
        </div>
        <h2 class="today-name">{e(next_up["name"])}</h2>
        <p class="today-meta">{e(next_up.get("location",""))} Â· {e(next_up.get("type",""))} Â· Priority: {e(next_up.get("priority","Medium"))}</p>
        {f'<p class="today-why">{e(next_up.get("why",""))}</p>' if next_up.get('why') else ''}
      </div>
    </section>'''
    else:
        today_section = ''

    # Build filter options dynamically
    regions = sorted({region_from_location(ev.get('location','')) for ev in upcoming})
    types = sorted({ev.get('type','') for ev in upcoming if ev.get('type')})
    region_opts = '\n'.join(f'<option value="{e(r)}">{e(r)}</option>' for r in regions)
    type_opts = '\n'.join(f'<option value="{e(t)}">{e(t)}</option>' for t in types)

    upcoming_section = f'''
    <section class="events">
      <div class="section-head">
        <h2 class="section-title">Upcoming</h2>
        <p class="section-count">{upcoming_count} events Â· sorted by date</p>
      </div>
      <div class="filter-bar">
        <div class="filter-group">
          <label for="f-search">Search</label>
          <input type="search" id="f-search" placeholder="Name, city, country">
        </div>
        <div class="filter-group">
          <label for="f-priority">Priority</label>
          <select id="f-priority" aria-label="Filter by priority">
            <option value="">All priorities</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Low">Low</option>
          </select>
        </div>
        <div class="filter-group">
          <label for="f-region">Region</label>
          <select id="f-region" aria-label="Filter by region">
            <option value="">All regions</option>
            {region_opts}
          </select>
        </div>
        <div class="filter-group">
          <label for="f-type">Type</label>
          <select id="f-type" aria-label="Filter by event type">
            <option value="">All types</option>
            {type_opts}
          </select>
        </div>
      </div>
      <p id="event-counter">Showing {upcoming_count} of {upcoming_count} upcoming events</p>
      <div class="event-grid" id="upcoming-grid">
{upcoming_html}
      </div>
    </section>'''

    # (The old public "Archive Â· N past events" <details> block was built here
    # and never rendered â€” the public catalog view was retired. Removed rather
    # than left to rot: it was also the last place calling PAST events an
    # "archive", which now means one thing only â€” an event you archived.)

    foot = f'''
    <div class="panel" id="panel-angela" role="tabpanel" data-tab="angela" aria-labelledby="tab-angela">

      <!-- Preloaded ArcticBlue speakers â€” referenced by every speaker input
           (manual form + ops-card inline editor) via list="ab-speakers".
           A datalist suggests these names but still allows a free-typed value,
           so existing speakers from imports are never lost. -->
      <datalist id="ab-speakers">
        <option value="Thor"></option>
        <option value="Joe"></option>
        <option value="Jerome"></option>
        <option value="Scott"></option>
        <option value="Verma"></option>
        <option value="Carlos"></option>
        <option value="Jim"></option>
      </datalist>

      <!-- State 1 Â· loading session -->
      <div id="angela-loading" class="alert">Loading your sessionâ€¦</div>

      <!-- State 2 Â· not signed in -->
      <div id="angela-signin" class="angela-card" hidden>
        <h2>Sign in to edit</h2>
        <p class="lede">Editing is restricted to ArcticBlue team members. Enter your work email and we'll send a one-time sign-in link.</p>
        <form id="signin-form" novalidate>
          <label for="signin-email">Work email</label>
          <input type="email" id="signin-email" placeholder="you@arcticblue.ai" required autocomplete="email">
          <button type="submit" class="primary" id="signin-submit">Send magic link</button>
        </form>
        <p class="mono-foot">Read access stays open to everyone Â· Only allow-listed emails can edit</p>
      </div>

      <!-- State 3 Â· magic-link sent -->
      <div id="angela-signin-sent" class="alert" hidden>
        Check your inbox â€” we sent a sign-in link to <strong id="signin-sent-to"></strong>. Click it on this device to come back here signed in.
      </div>

      <!-- State 4 Â· signed in but not on allow-list -->
      <div id="angela-unauth" class="alert warn" hidden>
        You're signed in as <strong id="unauth-email"></strong>, but this email isn't on the editor list. Read access is fine; ask Hurley to add you to <code>allowed_editors</code> if you need to edit.
        <button class="inline" id="signout-unauth">Sign out</button>
      </div>

      <!-- The collaborative tracker â€” open to everyone, no login. -->
      <div id="angela-ops" hidden>
        <div id="ops-status" class="alert" hidden></div>
        <div class="ops-controls-row">
        <div class="view-toggle" role="tablist" aria-label="View">
          <button type="button" role="tab" data-view="action" class="active" aria-selected="true">Action Center</button>
          <button type="button" role="tab" data-view="myevents" aria-selected="false">Lineup<span class="vt-count" id="vt-myevents-count" hidden></span></button>
          <button type="button" role="tab" id="tab-events" data-events-tab aria-selected="false">Events</button>
          <button type="button" role="tab" data-view="queue"    aria-selected="false">Queue<span class="vt-count" id="vt-queue-count" hidden></span></button>
          <button type="button" role="tab" data-view="planner"  aria-selected="false">Planner<span class="vt-count" id="vt-planner-count" hidden></span></button>
        </div>
        <div class="ops-controls-right">
            <span class="ops-navcount" id="ops-count"></span>
            <div class="ops-toolbar-group" role="group" aria-label="Sync and export" id="ops-sync-group">
              <span class="ops-toolbar-label">Sync</span>
              <button class="ab-btn ab-btn--ghost ab-btn--rose" id="ical-subscribe-btn" title="One auto-updating feed for Google Calendar, Apple Calendar or Outlook â€” plus a one-time .ics download">
                <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2v4"/><path d="M16 2v4"/><path d="M21 13V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8"/><path d="M3 10h18"/><path d="M16 19h6"/><path d="M19 16v6"/></svg>
                Calendar sync
              </button>
              <button class="ab-btn ab-btn--ghost ab-btn--amber" id="csv-btn" title="Download the tracker as a spreadsheet, or upload an edited one">
                <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 8a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2Z"/><path d="M3 10h18"/><path d="M10 6v12"/></svg>
                Spreadsheet
              </button>
            </div>
            <div class="ops-add-wrap">
              <button class="ab-btn ab-btn--primary" id="add-menu-btn" aria-haspopup="menu" aria-expanded="false" title="Add an event">
                <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
                Add
                <svg class="ab-btn__caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
              </button>
              <div class="ops-add-menu" id="add-menu" role="menu" aria-label="Add an event" hidden>
                <button class="ops-add-item" id="add-event-btn" role="menuitem" type="button">
                  <svg class="ops-add-item__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
                  <span class="ops-add-item__txt"><span class="ops-add-item__t">Add manually</span><span class="ops-add-item__d">Type in an event yourself</span></span>
                </button>
                <button class="ops-add-item" id="search-dust-btn" role="menuitem" type="button">
                  <svg class="ops-add-item__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .962 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.962 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/></svg>
                  <span class="ops-add-item__txt"><span class="ops-add-item__t">Find new events</span><span class="ops-add-item__d">Let AI suggest events to add</span></span>
                </button>
                <button class="ops-add-item" id="paste-email-btn" role="menuitem" type="button" hidden>
                  <svg class="ops-add-item__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg>
                  <span class="ops-add-item__txt"><span class="ops-add-item__t">Paste email</span><span class="ops-add-item__d">Pre-fill from an event email</span></span>
                </button>
              </div>
            </div>
        </div>
        </div>
        <div class="ops-topfilters" id="ops-topfilters">
          <div class="events-subnav" id="events-subnav" role="tablist" aria-label="Events view" hidden>
            <button type="button" role="tab" class="subnav-btn" data-view="grid" aria-selected="false" aria-label="List view" title="List view"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/></svg></button>
            <button type="button" role="tab" class="subnav-btn" data-view="calendar" aria-selected="false" aria-label="Calendar view" title="Calendar view"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/></svg></button>
            <button type="button" role="tab" class="subnav-btn" data-view="map" aria-selected="false" aria-label="Map view" title="Map view"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/></svg></button>
          </div>
          <div class="ops-stats ops-seg" id="ops-stats" hidden></div>
          <button type="button" class="tf-toggle" id="ops-filter-toggle" aria-haspopup="true" aria-expanded="false" aria-controls="tf-drawer" title="More filters â€” region, months, pipeline and more" aria-label="More filters">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/></svg>
            <span class="tf-dot" id="tf-active-count" hidden></span>
          </button>
          <input type="search" id="ops-search" placeholder="Search events" aria-label="Search events">
        </div>
        <div class="tf-drawer" id="tf-drawer" hidden>
          <div class="filter-dd" id="filter-pipeline" title="Pipeline stage â€” where each event stands (pick several to combine)">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Pipeline</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- stage chips injected by buildStageFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-region" title="Region (pick several to combine)">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Region</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- region chips injected by buildRegionFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-fits" title="Pick a person: shows the events that are actually theirs â€” flagged interested, submitted, booked or attending. Events they were rejected for are left out.">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Person</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"></div>
          </div>
          <div class="filter-dd" id="filter-months" title="Show only events in the months you pick (pick several to combine)">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Months</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- month chips injected by buildMonthsFilter() --></div>
          </div>
          <div class="filter-dd" id="filter-should" title="Should Attend â€” team hand-picks + AI recommendations">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Should attend</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- Team pick / AI pick chips injected by buildExtraFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-price" title="Ticket price as a buyer signal: a pricier pass usually means real buyers, not a hall of vendors">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Ticket price</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- chips injected by buildExtraFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-priority">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Priority</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- chips injected by buildExtraFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-speaker">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Speaking</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><span class="extra-empty" id="filter-speaker-empty">No speakers assigned yet</span></div>
          </div>
          <label class="ops-filter-chip" title="Show only events at the Submitted stage â€” a speaker application is in"><input type="checkbox" id="ops-f-submitted">Submitted</label>
          <label class="ops-filter-chip" title="Show only events added in the last 7 days (incl. AI-discovered) â€” the new batch to triage"><input type="checkbox" id="ops-f-recent">Recently added</label>
        </div>
        <p class="ops-active-filters" id="ops-active-filters" hidden></p>
        <div class="ops-results-header" id="ops-results-header">
          <button type="button" class="ops-dupe-review" id="ops-dupe-review" title="Show the auto-detected duplicate events so you can delete them (open one, then Details â†’ Edit â†’ Delete this event)" hidden></button>
          <span class="ops-shown" id="ops-shown"></span>
        </div>
        <div class="ops-grid" id="ops-grid"></div>
        <div class="ops-calendar" id="ops-calendar"></div>
        <div class="ops-map" id="ops-map">
          <p class="ops-meta" id="ops-map-note" style="margin:0 0 8px;"></p>
          <div class="map-wrap">
            <div id="ops-map-canvas"></div>
            <aside class="map-sidebar" id="map-sidebar" hidden aria-label="Events at this location">
              <div class="map-sidebar-head">
                <span class="msb-title" id="msb-title"></span>
                <span class="msb-count" id="msb-count"></span>
                <button type="button" class="msb-close" id="msb-close" aria-label="Close panel">&times;</button>
              </div>
              <div class="map-sidebar-list" id="msb-list"></div>
            </aside>
          </div>
        </div>
        <div class="ops-myevents" id="ops-myevents"></div>
        <div class="ops-myprofile" id="ops-myprofile"></div>
        <section id="ops-action" hidden aria-label="Action Center"></section>
        <div class="ops-queue" id="ops-queue"></div>
        <div class="ops-planner" id="ops-planner"></div>
        <div class="ops-dayof" id="ops-dayof"></div>
      </div>

    </div><!-- /panel-angela -->
  </main>

  <!-- â”€â”€ Expanded pop-up (modal) for a single event â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ -->
  <div id="event-modal" class="modal-overlay" hidden>
    <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-topbar">
        <div id="modal-head-left"></div>
        <div id="modal-head-side"></div>
        <button type="button" class="modal-close" id="modal-close" aria-label="Close">Ã—</button>
      </div>
      <div class="modal-scroll">
        <!-- Name, then city, then date (Hurley 2026-07-29). The event is what
             you came for; where and when are the qualifiers under it. -->
        <div class="modal-head">
          <div class="modal-badges" id="modal-badges"></div>
          <h2 class="modal-title" id="modal-title"></h2>
          <p class="modal-loc" id="modal-loc"></p>
          <p class="modal-date" id="modal-date"></p>
        </div>
        <div class="modal-body" id="modal-body"></div>
        <div class="modal-actions" id="modal-actions"></div>
      </div>
    </div>
  </div>
  <script type="application/json" id="catalog-data">{catalog_json}</script>

<script>
// â”€â”€ Sole view: the Event Tracker is the only panel (Public view retired). â”€â”€
(function () {{
  // Defensive: ensure the tracker panel is visible even if an old build left a
  // stale "activeTab" in localStorage that once hid it.
  var panel = document.getElementById('panel-angela');
  if (panel) panel.removeAttribute('hidden');
  try {{ localStorage.removeItem('ab.tracker.activeTab'); }} catch (e) {{}}
}})();

(function () {{
  var grid = document.getElementById('upcoming-grid');
  var counter = document.getElementById('event-counter');
  var search = document.getElementById('f-search');
  var priority = document.getElementById('f-priority');
  var region = document.getElementById('f-region');
  var type = document.getElementById('f-type');
  if (!grid) return;
  var cards = Array.prototype.slice.call(grid.querySelectorAll('.event'));
  var TOTAL = cards.length;

  function apply () {{
    var q = (search.value || '').toLowerCase().trim();
    var pri = priority.value || '';
    var rgn = region.value || '';
    var ty = type.value || '';
    var shown = 0;
    cards.forEach(function (c) {{
      var ok = true;
      if (pri && (c.dataset.priority || '').indexOf(pri) !== 0) ok = false;
      if (rgn && c.dataset.region !== rgn) ok = false;
      if (ty && c.dataset.type !== ty) ok = false;
      if (q && c.textContent.toLowerCase().indexOf(q) === -1) ok = false;
      c.style.display = ok ? '' : 'none';
      if (ok) shown++;
    }});
    // Hide any month divider whose cards are all filtered out, so we never
    // show an empty "June 2026" header floating above nothing.
    Array.prototype.slice.call(grid.querySelectorAll('.month-header')).forEach(function (h) {{
      var vis = 0;
      var n = h.nextElementSibling;
      while (n && !n.classList.contains('month-header')) {{
        if (n.classList.contains('event') && n.style.display !== 'none') vis++;
        n = n.nextElementSibling;
      }}
      h.style.display = vis ? '' : 'none';
    }});
    counter.textContent = 'Showing ' + shown + ' of ' + TOTAL + ' upcoming events';
  }}
  [search, priority, region, type].forEach(function (el) {{
    if (el) el.addEventListener(el.tagName === 'INPUT' ? 'input' : 'change', apply);
  }});
  apply();
}})();

// â”€â”€ Expanded pop-up (modal) for an event â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Clicking any catalog card (public page) or a "Details" affordance in the
// For-Angela tab opens this. The event website link lives INSIDE the modal
// now â€” the card itself is no longer a whole-card link.
(function () {{
  var CATALOG = {{}};
  try {{
    var blob = document.getElementById('catalog-data');
    if (blob) CATALOG = JSON.parse(blob.textContent || '{{}}');
  }} catch (e) {{ CATALOG = {{}}; }}
  window.AB_CATALOG = CATALOG;

  var overlay  = document.getElementById('event-modal');
  var closeBtn = document.getElementById('modal-close');
  if (!overlay) return;
  var $badges  = document.getElementById('modal-badges');
  var $date    = document.getElementById('modal-date');
  var $title   = document.getElementById('modal-title');
  var $loc     = document.getElementById('modal-loc');
  var $body    = document.getElementById('modal-body');
  var $actions = document.getElementById('modal-actions');
  var lastFocus = null;
  // The ArcticBlue speaker roster â€” drives the "Interested" picker.
  var AB_ROSTER = ['Thor', 'Verma', 'Jerome', 'Joe', 'Scott', 'Carlos', 'Jim'];
  // Persona single-source-of-truth (config/personas.json), baked in. Global so
  // both the modal (attendees picker) and the ops views (Day-Of) read it.
  window.AB_PERSONAS = {PERSONAS_JS}.personas;

  function esc(s) {{
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }}
  // â”€â”€ One clock for the whole app: New York â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  // "Today" was three different things â€” the build machine's UTC date baked
  // into the header, and each viewer's own timezone client-side. The team is in
  // New York, so that is the clock (Hurley 2026-07-30).
  function abTodayIso() {{
    try {{
      // en-CA formats as YYYY-MM-DD, which is exactly the key we compare on.
      return new Intl.DateTimeFormat('en-CA', {{ timeZone: 'America/New_York' }}).format(new Date());
    }} catch (e) {{
      var d = new Date();
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }}
  }}
  window.abTodayIso = abTodayIso;
  // "JULY 30, 2026" in New York, for the header stamp.
  function abTodayLabel() {{
    try {{
      return new Intl.DateTimeFormat('en-US', {{ timeZone: 'America/New_York',
        month: 'long', day: 'numeric', year: 'numeric' }}).format(new Date()).toUpperCase();
    }} catch (e) {{ return ''; }}
  }}
  // Paint it now, then keep it honest: a tab left open overnight rolls over on
  // its own, and a re-render is fired so today/upcoming/past reclassify too.
  function abPaintToday() {{
    var el = document.getElementById('ab-today');
    var lbl = abTodayLabel();
    if (el && lbl) el.textContent = lbl;
  }}
  (function abClock() {{
    abPaintToday();
    var last = abTodayIso();
    setInterval(function () {{
      var now = abTodayIso();
      if (now !== last) {{
        last = now;
        abPaintToday();
        if (window.opsRefresh) {{ try {{ window.opsRefresh(); }} catch (e) {{}} }}
      }}
    }}, 60000);
  }})();

  function priClass(p) {{
    p = (p || '').toLowerCase();
    if (p.indexOf('high') === 0) return 'p-high';
    if (p.indexOf('low')  === 0) return 'p-low';
    return 'p-medium';
  }}
  // Buyer/seller read -> badge color. Buyer-rich (what ArcticBlue wants) is the
  // "good" green-ish high tone; vendor-heavy is the cautionary low tone.
  function audienceClass(a) {{
    a = (a || '').toLowerCase();
    if (a.indexOf('buyer') !== -1) return 'aud-buyer';
    if (a.indexOf('vendor') !== -1 || a.indexOf('seller') !== -1) return 'aud-vendor';
    return 'aud-mixed';
  }}
  // Effective card priority (High / Medium / Low). "Like the data before" â€” it
  // starts from the stored priority (event_state override, else catalog/manual
  // base) â€” then folds in two live signals so the badge reflects what we
  // actually care about right now:
  //   * anyone marked INTERESTED right now is, by definition, a priority -> High
  //   * a BUYER-RICH audience (the room ArcticBlue most wants) lifts it one tier
  // Returns '' when there's no priority signal at all (so the badge is hidden).
  function cardPriority(o, st) {{
    o = o || {{}}; st = st || {{}};
    var intr = (st.interested && st.interested.length) ? st.interested
             : (o.interested && o.interested.length) ? o.interested : [];
    if (intr.length) return 'High';
    var base = String(st.priority_override || st.priority || o.priority_override || o.priority || '').trim().toLowerCase();
    var rank = base.indexOf('high') === 0 ? 3 : base.indexOf('med') === 0 ? 2 : base.indexOf('low') === 0 ? 1 : 0;
    var aud = String(st.audience_type || o.audience_type || '').toLowerCase();
    if (aud.indexOf('buyer') !== -1) rank += 1;
    return rank >= 3 ? 'High' : rank === 2 ? 'Medium' : rank >= 1 ? 'Low' : '';
  }}
  // Numeric ticket price from a free-text pricing string ('$2,495 delegate
  // pass' -> 2495, 'Free' -> 0, unknown -> null). Used by the price filter;
  // when several numbers appear (buyer vs vendor tiers) the HIGHEST wins,
  // since the top tier is the high-clientele signal Verma filters on.
  function priceNumOf(p) {{
    if (p == null) return null;
    var s = String(p).toLowerCase();
    if (!s.trim()) return null;
    // Only count a number that's actually a PRICE â€” tied to a currency symbol or
    // code. Otherwise attendee counts ("32,000"), years ("2026"), etc. get read
    // as prices, so "Price known" showed events with no real price.
    var clean = s.replace(/,/g, ''), nums = [], x;
    var re = /(?:[$Â£â‚¬]\\s?(\\d{{2,6}}(?:\\.\\d+)?))|(?:(\\d{{2,6}}(?:\\.\\d+)?)\\s?(?:usd|eur|gbp|dollars?|euros?|pounds?))/g;
    while ((x = re.exec(clean)) !== null) {{ var n = x[1] || x[2]; if (n) nums.push(parseFloat(n)); }}
    if (nums.length) return Math.max.apply(null, nums);
    if (/\\bfree\\b|\\bcomplimentary\\b|\\bno cost\\b/.test(s)) return 0;
    return null;
  }}
  // First http(s) URL inside a speaking_route blob ('Apply to speak:
  // https://x.io/cfp') -> the URL, else null. Powers the Apply button.
  function speakingRouteUrl(t) {{
    if (!t) return null;
    var m = String(t).match(/https?:\\/\\/[^\\s)\\]'"<>]+/);
    return m ? m[0] : null;
  }}
  function attendClass(v) {{
    v = (v || '').toLowerCase();
    if (v.indexOf('worth') === 0 || v.indexOf('yes') === 0) return 'attend-yes';
    if (v.indexOf('not') === 0 || v.indexOf('no') === 0) return 'attend-no';
    return 'p-medium';
  }}
  // Turn URLs + bare emails inside ALREADY-ESCAPED text into clickable links.
  // One combined pass so an email inside a URL can't double-wrap. Lets a pasted
  // link in a detail field (Speaking route, Contact info, â€¦) be clickable, not
  // just plain text (Angela's ask). Trailing sentence punctuation stays outside
  // the link.
  function _linkifyEsc(escaped) {{
    return String(escaped).replace(/(https?:\\/\\/[^\\s<]+)|([A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{{2,}})/g, function (m, url, email) {{
      if (url) {{
        var tail = '', t = url.match(/[).,;:!?]+$/);
        if (t) {{ tail = t[0]; url = url.slice(0, -tail.length); }}
        return '<a href="' + url + '" target="_blank" rel="noopener">' + url + '</a>' + tail;
      }}
      return '<a href="mailto:' + email + '">' + email + '</a>';
    }});
  }}
  // "Unknown" / "TBD" / "not verified" are non-answers. Printing them makes the
  // card look filled in when it isn't (Hurley 2026-07-29) â€” an absent row reads
  // better than a row that says nothing.
  var _MODAL_JUNK = /^(unknown|tbd|tba|n\/?a|none|null|not\s+(verified|specified|published|available|listed|confirmed|known)|no\s+information|to\s+be\s+(confirmed|announced))\.?$/i;
  // Enrichment writes its own ignorance into the field: "Not verifiable from
  // provided results", "Unknown (delegate pricing not published)", "CFP deadline
  // not specified". 77 such lines were on screen â€” half of every price shown.
  // A line that only says we don't know isn't worth the row (Hurley 2026-07-30).
  var _JUNK_WHOLE = /^(?:[a-z ]{{0,24}}\\b)?(?:not\s+(?:verifiable|published|specified|disclosed|listed|available|confirmed|stated|provided)|unknown|undisclosed|unclear|unspecified|no\s+(?:information|pricing|details?)\\b)[^.]*\.?$/i;
  function _modalJunk(v) {{
    var t = String(v == null ? '' : v).trim().replace(/^[\s\u2014-]+|[\s.;,]+$/g, '');
    if (!t) return true;
    return _MODAL_JUNK.test(t) || _JUNK_WHOLE.test(t);
  }}
  // Same idea one level down: "Paid; ticket tiers not verifiable from the
  // provided results" DOES say something ("Paid") â€” drop only the dead clause
  // rather than the whole line.
  function _dropJunkClauses(v) {{
    var t = String(v == null ? '' : v).trim();
    if (t.indexOf(';') === -1) return t;
    var keep = t.split(/\s*;\s*/).filter(function (c) {{
      c = c.trim(); return c && !_modalJunk(c);
    }});
    return keep.length ? keep.join('; ') : '';
  }}
  // The audience rating also hides INSIDE other fields: a few events have it
  // typed into their PRICE ("Buyer-rich tier: $2,500; Vendor tier: $5,000") or
  // their blurb. Gating the Audience row alone still left Thor reading
  // "Buyer-rich" (Hurley 2026-07-30), so the phrase is scrubbed from every
  // value we render for someone who isn't allowed the rating.
  function _deAudience(v) {{
    if (seesAudience()) return v;
    return String(v == null ? '' : v)
      .replace(/buyer[-\s]?rich/gi, function (m) {{ return m.charAt(0) === 'B' ? 'Buyer' : 'buyer'; }})
      .replace(/vendor[-\s]?heavy/gi, function (m) {{ return m.charAt(0) === 'V' ? 'Vendor' : 'vendor'; }});
  }}
  function field(label, val, html) {{
    if (val == null || String(val).trim() === '') return '';
    if (!html && _modalJunk(val)) return '';
    if (!html) {{
      val = _dropJunkClauses(val);
      if (!val) return '';
      val = _deAudience(val);
    }}
    return '<div class="modal-field"><span class="k">' + esc(label) + '</span>' +
           '<span class="v">' + (html ? val : _linkifyEsc(esc(val))) + '</span></div>';
  }}
  // Value with NO key label â€” for a field whose section heading already names it.
  // Notes was printing "Notes" twice (the zone heading, then the field key).
  function fieldBare(val) {{
    if (val == null || String(val).trim() === '') return '';
    if (_modalJunk(val)) return '';
    val = _dropJunkClauses(val);
    if (!val) return '';
    val = _deAudience(val);
    return '<div class="modal-field"><span class="v">' + _linkifyEsc(esc(val)) + '</span></div>';
  }}

  // Buyer-rich / audience mix is a targeting judgement, not a fact about the
  // event â€” Angela's triage tool. Nobody else sees it, in the read view OR the
  // editor (Hurley 2026-07-29).
  // Verma used to be carved out here too, which made his card different from
  // everyone else's on the same event. Profiles are merged and everyone gets
  // Thor's view, and Thor never saw this â€” so the carve-out goes (2026-08-05).
  // Angela stays: it's her triage job, not a persona.
  function seesAudience() {{
    return !!(window.isAngelaUser && window.isAngelaUser());
  }}

  // â”€â”€ Who attends: one list, not two overlapping ones â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  // "Typical attendees" and "Past / announced speakers" described the same room
  // from two angles and repeated each other â€” the same CIOs and CDOs listed
  // twice, padded out with entries that carry no information at all ("Technology
  // Leader, Global Enterprise") â€” so they're merged for display (Hurley
  // 2026-07-29). Both columns stay separate in the editor; this is presentation.
  //
  // Words that describe no one in particular. An entry made only of these is
  // filler and gets dropped; they're also ignored when judging repeats, so
  // "CIO, Major Enterprise" is recognised as a repeat of "CIOs".
  var _ATT_FILLER = {{
    major: 1, global: 1, worldwide: 1, international: 1, national: 1, regional: 1,
    enterprise: 1, company: 1, corporate: 1, corporation: 1, organisation: 1,
    organization: 1, business: 1, firm: 1, technology: 1, tech: 1, leader: 1,
    leadership: 1, senior: 1, executive: 1, various: 1, multiple: 1, large: 1,
    mid: 1, small: 1, level: 1, industry: 1, sector: 1, and: 1, the: 1, of: 1,
    from: 1, for: 1, with: 1, include: 1, including: 1, past: 1, announced: 1,
    attendee: 1, speaker: 1, delegate: 1, participant: 1, other: 1, plus: 1,
    // Function words, or "mid-to-large enterprises" survives on the word "to".
    to: 1, in: 1, at: 1, on: 1, or: 1, by: 1, a: 1, an: 1, as: 1, is: 1,
    are: 1, all: 1, only: 1, some: 1, most: 1, both: 1, per: 1, via: 1
  }};
  // Distinctive words only, singularised so "CIOs" and "CIO" are the same word.
  function _attSig(s) {{
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(' ')
      .map(function (w) {{ return (w.length > 3 && w.charAt(w.length - 1) === 's') ? w.slice(0, -1) : w; }})
      .filter(function (w) {{ return w && !_ATT_FILLER[w]; }});
  }}
  function mergeAttendees(typical, past) {{
    var raw = [typical, past].filter(function (x) {{ return x && String(x).trim(); }}).join('; ');
    if (!raw.trim()) return '';
    // The separators these fields actually use â€” semicolons, bullets, newlines
    // and sentence breaks. NOT commas: "CIO, Major Enterprise" is one entry.
    var parts = raw.split(/\\s*(?:;|\\u00b7|\\u2022|\\n|\\.\\s)\\s*/);
    var out = [], kept = [];
    for (var i = 0; i < parts.length && out.length < 6; i++) {{
      var s = parts[i].replace(/^[\\s,.;:Â·â€¢\\-]+/, '').replace(/[\\s,.;:Â·â€¢\\-]+$/, '');
      if (!s) continue;
      var sig = _attSig(s);
      if (!sig.length) continue;               // says nothing once filler is gone
      // Skip when everything distinctive about it is already on the list.
      var covered = kept.some(function (have) {{
        return sig.every(function (w) {{ return have.indexOf(w) !== -1; }});
      }});
      if (covered) continue;
      // Skip a restatement: it leads with a role we already listed and adds
      // barely anything. "CIO, Enterprise Agentic AI Deployment" after
      // "CDOs, CAIOs, CTOs, CIOsâ€¦" is the same person described again.
      var haveWords = {{}};
      kept.forEach(function (have) {{ have.forEach(function (w) {{ haveWords[w] = 1; }}); }});
      var fresh = sig.filter(function (w) {{ return !haveWords[w]; }});
      if (haveWords[sig[0]] && fresh.length < 3) continue;
      kept.push(sig);
      out.push(s);
    }}
    return out.join('; ');
  }}
  // One short clause â€” used to fold "Meetings & networking" into the overview
  // rather than giving a format note a section heading of its own.
  function briefClause(v) {{
    var s = String(v == null ? '' : v).trim().replace(/\s+/g, ' ');
    if (!s || _modalJunk(s)) return '';
    // These arrive as semicolon lists mixing real formats with non-answers
    // ("attendee app not verified; invite-only stream; innovation clinics").
    // Take clauses that actually state something, never a pipe-joined blob.
    var parts = s.split(/\s*[;|]\s*|\.\s+/);
    var picks = [];
    for (var i = 0; i < parts.length && picks.length < 4; i++) {{
      var t = parts[i].replace(/[.;,\s]+$/, '').trim();
      if (!t || _modalJunk(t)) continue;
      if (/\\bnot\s+(verified|specified|published|available|listed|confirmed|known)\\b/i.test(t)) continue;
      // "no guaranteed 1:1 meetings" is the absence of a feature â€” listing it
      // after "Includes" says the opposite of what it means.
      if (/^(?:no|none|without)\\b/i.test(t)) continue;
      t = t.replace(/\[\d+\]/g, '').trim();      // scrape citation markers
      if (!t) continue;
      picks.push(t);
    }}
    if (!picks.length) return '';
    // A meeting app is not a "format", and neither is being invite-only â€” the
    // sentence has to match what the clause actually IS (Hurley 2026-07-30).
    // Three kinds, three lead-ins; the one that fits wins, most useful first.
    // Plurals matter: \\bworkshop\\b never matches "workshops", so the old list
    // silently dropped every plural clause â€” "keynotes; roundtables; expo floor"
    // came out as just the expo floor.
    var _isFormat = /\\b(panels?|keynotes?|workshops?|roundtables?|firesides?|breakouts?|masterclass(?:es)?|sessions?|tracks?|talks?|discussions?|debates?|demos?|exhibitions?|expos?|hackathons?|pitch(?:es)?|clinics?|labs?|tours?|dinners?|receptions?|networking|presentations?|briefings?|forums?)\\b/i;
    // Only a bare adjectival access term can follow "Attendance is". Anything
    // longer ("invite-only stream") is a thing, not a condition, and reads as
    // broken English there â€” it goes through "Includes" instead.
    var _isAccess = /^(?:invite[- ]only|members?[- ]only|closed[- ]door|curated invite(?:[- ]only)?|invitation[- ]only|by application|application[- ]only|vetted|screened)$/i;
    var fmts = [], acc = [], rest = [];
    picks.forEach(function (t) {{
      if (_isFormat.test(t)) fmts.push(t);
      else if (_isAccess.test(t)) acc.push(t);
      else rest.push(t);
    }});
    var lead = 'The format includes ', chosen = fmts, article = true;
    if (!fmts.length && acc.length) {{ lead = 'Attendance is '; chosen = [acc[0]]; article = false; }}
    else if (!fmts.length)          {{ lead = 'Includes ';      chosen = rest;     article = true;  }}
    chosen = chosen.slice(0, 3);
    if (!chosen.length) return '';
    // Lead with the plainest one â€” insider shorthand ("Day 0") reads badly first.
    chosen.sort(function (a, b) {{
      var jarg = function (x) {{ return /\\bday\s*0\\b/i.test(x) ? 1 : 0; }};
      return jarg(a) - jarg(b);
    }});
    // Commas only â€” the last one becomes "and" below.
    var pick = chosen.join(', ');
    // Brief is the point â€” this rides at the END of the overview, so it has to
    // land in one readable breath rather than run on for three lines.
    if (pick.length > 110) pick = pick.slice(0, 107).replace(/[\s,]\S*$/, '') + 'â€¦';
    // Already a sentence? Leave it alone.
    if (/\\b(is|are|was|were|include|includes|offer|offers|feature|features|run|runs|host|hosts|provide|provides|guarantee|guarantees|use|uses|has|have|allow|allows|unlock|unlocks|cover|covers|grant|grants|combine|combines|admit|admits|give|gives|bring|brings|enable|enables|let|lets|mean|means|apply|applies|work|works|take|takes|require|requires|consist|consists|comprise|comprises|span|spans|award|awards|pair|pairs|connect|connects)\\b/i.test(pick)) {{
      return pick;
    }}
    // Clauses often carry their own "and" ("general and breakout sessions");
    // adding another produced "a and b and c". Commas only in that case.
    var _lst = / and /i.test(pick) ? pick : pick.replace(/,\s*([^,]+)$/, ' and $1');
    // Don't lowercase a brand â€” "Reuters Events app" must not become "reuters".
    // A second capitalised word is the tell that we're in a proper name.
    // A proper name is a capitalised word followed by ANOTHER capitalised word
    // ("Reuters Events", "One-to-One Meetings") â€” those keep their capitals.
    // Everything else is an ordinary noun phrase and gets lowercased. Applied
    // per clause, so "â€¦, Full access to keynotes" is fixed mid-sentence too,
    // not just the opening word.
    _lst = _lst.split(/(,\s*)/).map(function (seg) {{
      if (/^,/.test(seg) || !seg.trim()) return seg;
      return /^[A-Z][A-Za-z-]*\s+[A-Z]/.test(seg) ? seg
                                                 : seg.charAt(0).toLowerCase() + seg.slice(1);
    }}).join('');
    if (article) {{
      // "includes attendee app for pre-booking" wants an article. The head noun
      // sits before the first preposition, so test THAT for a plural.
      var _cut = _lst.search(/\s(?:for|with|via|in|on|at|to|during|across|from)\s|,/i);   // NOT 'and' â€” it's a conjunction, so the head noun continues past it
      var _head = (_cut > 0 ? _lst.slice(0, _cut) : _lst).trim().split(/\s+/).pop()
                    .replace(/[^A-Za-z-]+$/, '');
      // A gerund is a mass noun â€” "a matchmaking" / "a networking" are wrong.
      if (_head && !/s$/i.test(_head) && !/ing$/i.test(_head) &&
          !/^(?:a|an|the|some|several|multiple|\d)\\b/i.test(_lst)) {{
        _lst = (/^[aeiou]/i.test(_lst) ? 'an ' : 'a ') + _lst;
      }}
    }}
    return lead + _lst;
  }}

  // â”€â”€ Editable modal: one-tap quick actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  // Should-Attend has TWO sources that must NOT blur together (Angela: the 256
  // AI auto-tags were muting the handful Thor/Verma/Jerome flag by hand):
  //   human  -> attend_verdict = 'Worth attending'          (a teammate flagged it)
  //   ai     -> attend_verdict = 'Worth attending (AI)'     (the recommend pass)
  // Returns 'human' | 'ai' | null.
  // Global â€” shared between this modal scope and the separate ops closure
  // (buildOpsCard / applyFilters), which can't see a plain local declaration here.
  window.shouldAttendKind = function (v) {{
    var s = String(v == null ? '' : v).toLowerCase();
    if (s.indexOf('worth') !== 0 && s.indexOf('yes') !== 0) return null;
    return s.indexOf('(ai)') !== -1 ? 'ai' : 'human';
  }};
  function shouldAttendKind(v) {{ return window.shouldAttendKind(v); }}

  // Renders only when the modal was opened from an editable ops/manual card
  // (rec._table + rec._key present). Each button writes a single field via
  // window.opsWrite (bridged from the ops closure). Save/Hide are catalog-
  // only (manual_events has no saved/hidden column).
  // Who Angela flags Should-Attend for, in order of how often they go.
  var SA_PEOPLE = ['Thor', 'Verma', 'Jerome', 'Joe'];
  function quickBarHtml(rec) {{
    if (!rec || !rec._table || rec._key == null) return '';
    var stages = rec.stage_tags || [];
    function has(s) {{ return stages.indexOf(s) !== -1; }}
    var isCat = rec._table === 'event_state';
    var _saKind = shouldAttendKind(rec.attend_verdict);   // 'human' | 'ai' | null
    // Card actions (Save / Hide) sit on their own row; the pipeline + verdict
    // toggles are grouped under a "Status:" label so the modal reads as labeled
    // groups, not a wall of buttons (Thor's feedback).
    // These aren't six independent switches â€” they're a ROUTE:
    //   Submitted -> Followed up -> Booked / Rejected / Attending
    // laid out that way so the shape of the row tells you where the event has
    // got to, and the branch shows the three ways it can end (Hurley
    // 2026-07-30). Colours match the corner mark exactly: amber in flight,
    // green landed, red closed.
    var _fuN = (window.abFollowUps ? window.abFollowUps(rec) : []).length;
    // A logged follow-up IS a follow-up, even without the stage tag â€” Angela
    // could log three chases and still see the step unlit. But an END STATE
    // dims it regardless of the log: without this the log re-lights the step
    // the instant the tag is cleared, and clicking Booked looks like it did
    // nothing at all.
    var _endState = has('Booked') || has('Rejected') || has('Attending');
    var _fuOn = !_endState && (has('Followed up') || !!_fuN);
    function _step(qa, label, on, cls, extra) {{
      return '<button type="button" class="qa-step' + (on ? ' is-on' : '') + (cls ? ' ' + cls : '') +
             '" data-qa="' + qa + '"' + (extra || '') + '>' + label + '</button>';
    }}
    // Once an end state is set, the in-flight steps are spent: they read dark
    // and stop taking clicks. Leaving them live meant clicking "Followed up" on
    // a booked event wrote a chase to the log that the step then refused to
    // light \u2014 a dead button by another route.
    function _spentStep(label, tip) {{
      return '<span class="qa-step qa-flight qa-static" title="' + esc(tip) + '">' + label + '</span>';
    }}
    var bStage = [];
    bStage.push('<div class="qa-flow">');
    bStage.push(_endState
      ? _spentStep('Submitted', 'Retired \u2014 this event has reached an outcome')
      : _step('submitted', 'Submitted', has('Submitted'), 'qa-flight'));
    bStage.push('<span class="qa-arrow" aria-hidden="true">\u2192</span>');
    bStage.push(_endState
      ? _spentStep('Initial outreach', 'Retired \u2014 this event has reached an outcome')
      : _step('outreach', 'Initial outreach', has('Initial outreach'), 'qa-flight',
              ' title="' + esc('First approach to the organiser \u2014 before any chasing') + '"'));
    bStage.push('<span class="qa-arrow" aria-hidden="true">\u2192</span>');
    // Clicking this LOGS a chase dated today rather than flipping a bare tag:
    // the \u00d7N count comes from the log, so a tag-only toggle left the step stuck
    // lit and the button looked dead (Hurley 2026-07-30). Clicking again undoes
    // the last such quick entry; chases you typed a note against are real
    // history and are removed from their own row below, not from here.
    var _fuLabel = 'Followed up' + (_fuN ? '<span class="qa-n">\u00d7' + _fuN + '</span>' : '');
    // Clicking only ever ADDS now. Undo used to be a second click on the same
    // pill, which meant you couldn't add two chases in a row and couldn't tell
    // which way the next click would go (Hurley 2026-07-30). Correcting a
    // mis-click is its own "âˆ’", revealed on hover.
    var _fuTip = 'Click to log a chase dated today';
    // The "âˆ’" can only take back a quick click. An entry someone typed a note
    // against is real history and comes off via its own row below, so if every
    // logged chase has a note there is nothing safe for it to remove.
    var _fuUndoable = (window.abFollowUps ? window.abFollowUps(rec) : [])
      .filter(function (f) {{ return !String((f || {{}}).note || '').trim(); }}).length;
    if (_endState) {{
      bStage.push(_spentStep(_fuLabel, 'Retired \u2014 this event has reached an outcome. ' +
        (_fuN ? _fuN + ' chase' + (_fuN === 1 ? '' : 's') + ' still logged below.'
              : 'No chases were logged.')));
    }} else {{
      // The +/- stack is a CHILD of .qa-fu, not a sibling of it. That is what
      // keeps it open while the pointer travels onto it: :hover on an ancestor
      // holds for any descendant, even one positioned outside the ancestor's
      // box. Buttons can't nest, so they sit beside the pill inside the wrapper.
      bStage.push('<span class="qa-fu">' +
        _step('followed-up', _fuLabel, _fuOn, 'qa-flight', ' title="' + esc(_fuTip) + '"') +
        '<span class="qa-fu-ctl">' +
          '<button type="button" class="qa-fu-btn is-add" data-qa="followed-up"' +
            ' aria-label="Log one more follow-up"' +
            ' title="Log another chase, dated today">+</button>' +
          '<button type="button" class="qa-fu-btn is-sub" data-qa="followed-up-minus"' +
            (_fuUndoable ? '' : ' disabled') +
            ' aria-label="Remove one follow-up" title="' +
            esc(_fuUndoable
                  ? 'Take back the last quick chase'
                  : (_fuN ? 'Every chase logged here has a note \u2014 remove it from its own row below'
                          : 'Nothing logged yet')) +
            '">\u2212</button>' +
        '</span>' +
        '</span>');
    }}
    bStage.push('<span class="qa-arrow" aria-hidden="true">\u2192</span>');
    bStage.push('<span class="qa-branch">');
    bStage.push(_step('booked', 'Booked', has('Booked'), 'qa-good'));
    bStage.push(_step('rejected', 'Rejected', has('Rejected'), 'qa-bad',
      ' title="The organiser passed \u2014 flag it so the team can still opt to attend."'));
    // "Attending" is PER-PERSON: it reflects whether the signed-in person is in
    // the attendees list (Thor sees it off when only Jerome attends). Clicking it
    // adds/removes YOU. Angela assigns anyone via the edit-form Attending bubbles.
    var _meKey = ((window.opsCurrentUser ? window.opsCurrentUser() : '') || '').trim().split(/\\s+/)[0].toLowerCase();
    var _iAmAttending = !!(_meKey && (rec.attendees || []).some(function (a) {{ return String(a).toLowerCase() === _meKey; }}));
    if (window.isAngelaUser && window.isAngelaUser()) {{
      // Angela doesn't go to these herself, so the per-person test read false
      // for her on every event and the pill never ticked â€” even where the team
      // IS attending (Hurley 2026-07-30). She gets the EVENT's state. It's a
      // marker, not a toggle: clicking would have added HER to the attendees.
      // She assigns people in the edit form's Attending bubbles.
      var _attWho = (rec.attendees || []).map(function (a) {{
        a = String(a || '').trim();
        return a ? a.charAt(0).toUpperCase() + a.slice(1) : '';
      }}).filter(Boolean);
      var _attOn = has('Attending') || _attWho.length > 0;
      bStage.push('<span class="qa-step qa-good qa-static' + (_attOn ? ' is-on' : '') + '" title="' +
        (_attWho.length ? 'Attending: ' + esc(_attWho.join(', ')) + ' \u2014 set who in Edit'
                        : 'Nobody marked as attending yet \u2014 set who in Edit') + '">' +
        'Attending</span>');
    }} else {{
      bStage.push(_step('attending', 'Attending', _iAmAttending, 'qa-good',
        ' title="Attending is per-person \u2014 this marks whether YOU are going"'));
    }}
    bStage.push('</span>');   // /qa-branch
    bStage.push('</div>');    // /qa-flow
    // "Draft outreach" REMOVED for everyone (Hurley 2026-08-05, confirming the
    // earlier "take out the email drafter"). It offered a pre-filled organiser
    // email whenever an event was Submitted with no outreach logged yet. The
    // button, its panel, its click handler and Angela's template editor are all
    // gone, along with the whole compose engine (see the tombstone further down).
    // Should Attend is Angela's triage tool â€” only she sees/sets it here. For
    // everyone else, marking Interested funnels into her Should-Attend list.
    if (window.isAngelaUser && window.isAngelaUser()) {{
      // Angela can flag Should-Attend FOR a named person (Hurley 2026-07-30).
      // Operationally that IS the person saying "apply for me": it belongs in
      // her Queue and should drop off that person's Planner. Both already
      // happen for anyone on `interested` â€” queueItems() keys on it and
      // _suggestionsFor() skips events you're already flagged on â€” so this
      // writes the same list rather than inventing a parallel field.
      // Order is how often they actually go on stage.
      // Any pipeline stage at all means that triage question is answered.
      var _inPipeline = (rec.stage_tags || []).length > 0;
      var _saOn = (rec.interested || []).filter(Boolean);
      var _saHas = function (n) {{ return _saOn.some(function (x) {{ return String(x).toLowerCase() === n.toLowerCase(); }}); }};
      var _saPicked = SA_PEOPLE.filter(_saHas);
      var _saLabel = _saPicked.length
        ? 'Should Attend \u2014 ' + esc(_saPicked.join(', '))
        : 'Should Attend';
      var _saMenu = SA_PEOPLE.map(function (n) {{
        return '<button type="button" class="sa-pick' + (_saHas(n) ? ' on' : '') +
               '" data-sa-for="' + esc(n) + '">' + (_saHas(n) ? 'âœ“ ' : '') + esc(n) + '</button>';
      }}).join('');
      if (!_inPipeline) bStage.push('<span class="qa-sa-wrap">' +
        '<button type="button" class="qa qa-sa-btn' + ((_saKind === 'human' || _saPicked.length) ? ' on' : '') + '" data-qa="should-attend" title="' +
        (_saKind === 'ai' ? 'AI-suggested â€” click to confirm as a team Should-Attend' : 'Flag Should Attend â€” tentative but high on the radar') + '">' +
        _saLabel + '</button>' +
        '<span class="qa-sa-menu" role="group" aria-label="Flag Should Attend for">' +
          '<span class="sa-menu-h">Should attend &mdash; for</span>' + _saMenu +
          // The old blanket flag, kept for "worth attending, nobody named yet".
          '<button type="button" class="sa-pick sa-pick-team' + (_saKind === 'human' ? ' on' : '') +
            '" data-sa-team="1">' + (_saKind === 'human' ? '\u2713 ' : '') + 'Team &mdash; no one specific</button>' +
        '</span></span>');
    }}
    // "Interested" â€” the current teammate adds themselves to the list of people
    // who want Angela to apply for them. This feeds Angela's Queue.
    var me = (window.opsCurrentUser ? window.opsCurrentUser() : '') || '';
    var iAmIn = !!(me && (rec.interested || []).some(function (n) {{ return String(n).toLowerCase() === me.toLowerCase(); }}));
    // Show the ACTUAL flagged list here (raw), matching the toggle button â€” using
    // the booked/attending-filtered visibleInterested() made the summary read
    // "No one flagged yet" right after someone (e.g. the speaker) clicked
    // Interested. The dedup still applies to the Planner/Queue + card-face label.
    //
    // The "No one flagged yet" placeholder is ANGELA-ONLY (Hurley 2026-07-29):
    // she runs the apply queue, so an empty interested list is information she
    // acts on. For everyone else it was just a line of nothing â€” no flags is the
    // normal state of most events, so the row now shows only the button.
    // Thor first, short names â€” same order and vocabulary as the card's star
    // mark and the Lineup status line, so the three never disagree.
    var _intOrd = (window.abPlanOrder ? window.abPlanOrder(rec.interested || []) : (rec.interested || []))
      .map(function (n) {{ var w = String(n || '').trim().split(/\\s+/)[0];
                          return w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : ''; }})
      .filter(Boolean);
    var summary = formatInterested(_intOrd);
    var _qbAngela = !!(window.isAngelaUser && window.isAngelaUser());
    // Header icons need these two facts; the buttons themselves live up there now.
    window.__mqIn = iAmIn;
    // `summary` was BUILT and then dropped on the floor: the only branch that
    // used it fired when it was EMPTY, so "Verma & Joe are interested" never
    // reached the screen for anyone, Angela included (Hurley 2026-08-05). Thor
    // asked for the names, and this is the one place in Details they belong.
    // Angela additionally keeps the "nobody flagged this" prompt â€” an empty list
    // is a gap she works; for everyone else no flags is just the normal state.
    var intSummary = summary
      ? '<span class="qa-int-summary">' + summary + '</span>'
      : (_qbAngela ? '<span class="qa-int-summary qa-int-empty">No one flagged yet</span>' : '');
    // Archiving happens ONLY in this pop-up (the card face just shows an
    // "Archived" label), so the control is here for BOTH catalog and manual
    // events. Manual events also keep their separate "Delete this event" button
    // in the edit form.
    var _qbMan = rec._table === 'manual_events';
    var _qbArchivedMe = (window.opsIsArchivedForMe ? window.opsIsArchivedForMe(_qbMan, rec._key, rec.hidden === true) : !!rec.hidden);
    window.__mqArch = _qbArchivedMe;
    // The "Status:" / "Interested:" / "Hide:" row labels are gone (Hurley
    // 2026-07-29) â€” the buttons say what they do, and the labels were reading as
    // a wall of headings. The rows stay on SEPARATE lines, with "I'm interested"
    // and Archive sharing the second one.
    // "I'm interested" and Archive moved OUT of this row and into the modal's
    // top-right, as the same star and eye icons the card face uses â€” one place
    // to look for them, one visual language (Hurley 2026-07-30). Only the
    // who-flagged-it summary stays on the line.
    return '<div class="modal-quickbar">' +
           '<div class="qa-row qa-row--status" style="align-items:center;">' + bStage.join('') + '</div>' +
           (intSummary ? '<div class="qa-row qa-row--me" style="margin-top:6px;align-items:center;">' + intSummary + '</div>' : '') +
           '</div>';
  }}
  // Natural-language list of who's interested: "Joe is interested" /
  // "Verma & Joe are interested" / "Verma, Joe & Thor are interested".
  function formatInterested(names) {{
    names = (names || []).filter(Boolean);
    if (!names.length) return '';
    if (names.length === 1) return esc(names[0]) + ' is interested';
    var last = names[names.length - 1];
    var head = names.slice(0, -1).map(esc).join(', ');
    return head + ' &amp; ' + esc(last) + ' are interested';
  }}
  // Bound once: a pinned Should-Attend picker closes when you click away.
  if (!window._saOutsideWired) {{
    window._saOutsideWired = 1;
    document.addEventListener('click', function (e) {{
      var inside = e.target.closest ? e.target.closest('.qa-sa-wrap') : null;
      document.querySelectorAll('.qa-sa-wrap.is-open').forEach(function (w) {{
        if (w !== inside) w.classList.remove('is-open');
      }});
    }});
  }}
  function wireQuickBar(rec) {{
    var bar = $body.querySelector('.modal-quickbar');
    if (!bar) return;
    // Named + shared: the Interested / Archive icons now live in the modal
    // HEADER, outside this bar, and must run the identical logic.
    // Booked / Rejected / Attending all end the application, so each clears the
    // in-flight stages (Hurley 2026-07-30). The follow-up LOG is left alone â€”
    // those chases happened, and the log below the route is the history; only
    // the route step goes dark.
    // Repaint the minimum after a quickbar click, so the row stays responsive
    // and â€” for the follow-up pill â€” the button you just clicked survives to be
    // clicked again (Hurley 2026-07-30).
    var _qaFullTimer = null;
    function _qaLightRefresh(rec, qa) {{
      if (qa === 'followed-up' || qa === 'followed-up-minus') {{
        // Nothing STRUCTURAL changes when a chase is logged â€” only the count and
        // whether there's a quick entry left to undo. Patch those two in place:
        // replacing the node would drop the :hover that is revealing the "âˆ’",
        // so a second click would need the mouse jiggled first.
        var _n = (window.abFollowUps ? window.abFollowUps(rec) : []).length;
        var _pill = $body.querySelector('[data-qa="followed-up"]');
        if (_pill) {{
          var _cnt = _pill.querySelector('.qa-n');
          if (_n && !_cnt) {{
            _pill.insertAdjacentHTML('beforeend', '<span class="qa-n">\\u00d7' + _n + '</span>');
          }} else if (_n && _cnt) {{
            _cnt.textContent = '\\u00d7' + _n;
          }} else if (!_n && _cnt) {{
            _cnt.remove();
          }}
          _pill.classList.toggle('is-on', !!_n);
        }}
        var _minus = $body.querySelector('[data-qa="followed-up-minus"]');
        if (_minus) {{
          var _undoable = (window.abFollowUps ? window.abFollowUps(rec) : [])
            .filter(function (f) {{ return !String((f || {{}}).note || '').trim(); }}).length;
          _minus.disabled = !_undoable;
        }}
        return;
      }}
      // A stage toggle DOES change the row's shape â€” an outcome retires and
      // locks the in-flight steps â€” so rebuild just the bar, not the modal.
      _repaintStageSurfaces(rec);
    }}
    // â”€â”€ The pop-up shows the SAME stages twice â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    // Once in the quick bar at the top, once as the buttons in the edit area.
    // Both write rec.stage_tags, so whichever one you click, BOTH have to be
    // redrawn â€” and redrawn from the data, never by flipping a class.
    //
    // This was Angela's "I have to keep clicking Submitted" (2026-08-13). The
    // quick bar repainted itself and left the edit-area button showing the old
    // state. Clicking that stale button then did the OPPOSITE of what it looked
    // like it would: the record already had Submitted, so the click removed it
    // while `classList.toggle` lit the button up. It looked like the click had
    // finally worked, and it had actually undone the save â€” which is also why
    // the speaker stuck but Submitted came back empty. Every other click
    // appeared to work, because two wrongs put the parity back.
    //
    // Redrawing from rec is not optional tidiness: abStageImply lights stages
    // the click never touched (Followed up implies Submitted), so a single
    // button's class can never describe the outcome on its own.
    function _syncEditFormStages(rec) {{
      var tags = rec.stage_tags || [];
      Array.prototype.forEach.call($body.querySelectorAll('.modal-editform .me-stage'), function (b) {{
        b.classList.toggle('on', tags.indexOf(b.dataset.stage) !== -1);
      }});
      var _sf = $body.querySelector('.me-submitted-field');
      if (_sf) _sf.style.display = (tags.indexOf('Submitted') !== -1) ? '' : 'none';
    }}
    function _repaintStageSurfaces(rec) {{
      var _bar = $body.querySelector('.modal-quickbar');
      if (_bar) {{
        var _tmp = document.createElement('div');
        _tmp.innerHTML = quickBarHtml(rec);
        var _fresh = _tmp.firstElementChild;
        if (_fresh) {{
          _bar.parentNode.replaceChild(_fresh, _bar);
          wireQuickBar(rec);
        }}
      }}
      _syncEditFormStages(rec);
    }}
    // The ONE rule for turning a stage on or off, so the two surfaces cannot
    // disagree about what a click MEANS. The edit-area buttons used to skip the
    // end-state rules entirely: clicking Booked there left Rejected standing and
    // never retired the in-flight steps, while the same click in the quick bar
    // did both. Returns the new tags and whether this turned the stage ON.
    function _applyStageToggle(rec, stage) {{
      var tags = (rec.stage_tags || []).slice();
      var idx = tags.indexOf(stage);
      if (idx === -1) tags.push(stage); else tags.splice(idx, 1);
      // Reaching an END STATE retires the in-flight ones: Booked and Rejected
      // each clear Followed up / Initial outreach, and they are the same
      // question answered two ways, so turning one on turns the other off.
      if ((stage === 'Booked' || stage === 'Rejected') && idx === -1) {{
        var _other = tags.indexOf(stage === 'Booked' ? 'Rejected' : 'Booked');
        if (_other !== -1) tags.splice(_other, 1);
        tags = _abRetireInFlight(tags);
      }}
      tags = window.abStageImply(tags);
      rec.stage_tags = tags;
      return {{ tags: tags, turnedOn: idx === -1 }};
    }}
    // The edit form lives in the OUTER modal closure and cannot see either
    // helper â€” which is precisely why it grew its own copy of the toggle rule
    // and drifted out of step. Bridge them rather than duplicating again
    // (same pattern as window.abStageImply / window.closeEventModal).
    window.abApplyStageToggle = _applyStageToggle;
    window.abRepaintStages    = _repaintStageSurfaces;
    // An outcome retires the steps still IN FLIGHT, but no longer erases the
    // fact that we applied â€” "submitted, then rejected" is the useful record,
    // and clearing Submitted also fought the implication above (Hurley).
    function _abRetireInFlight(tags) {{
      return tags.filter(function (s) {{ return s !== 'Initial outreach' && s !== 'Followed up'; }});
    }}
    window.__qaClick = function (e) {{
      // Angela picked a NAME under Should Attend -> toggle them on `interested`,
      // which is what puts it in her Queue and takes it off their Planner.
      var pick = e.target.closest ? e.target.closest('[data-sa-for]') : null;
      if (pick && window.opsWrite) {{
        e.stopPropagation();
        var who = pick.getAttribute('data-sa-for') || '';
        var list = (rec.interested || []).slice();
        var at = -1;
        for (var q = 0; q < list.length; q++) {{
          if (String(list[q]).toLowerCase() === who.toLowerCase()) {{ at = q; break; }}
        }}
        var p2 = {{}};
        if (at === -1) {{
          list.push(who);
          // Flagging someone revives it in the queue and counts as a confirmed,
          // human Should-Attend â€” same as when the person flags themselves.
          if (shouldAttendKind(rec.attend_verdict) !== 'human') {{
            rec.attend_verdict = 'Worth attending'; p2.attend_verdict = 'Worth attending';
          }}
          rec.queue_dismissed = false; p2.queue_dismissed = false;
        }} else {{ list.splice(at, 1); }}
        if (window.abPlanOrder) list = window.abPlanOrder(list);
        rec.interested = list; p2.interested = list;
        window.opsWrite(rec._table, rec._key, p2);
        var wasOpen = !!(pick.closest('.qa-sa-wrap') || {{}}).classList;
        var sc0 = overlay.querySelector('.modal-scroll');
        var top0 = sc0 ? sc0.scrollTop : 0;
        openEventModal(rec);
        if (sc0) sc0.scrollTop = top0;
        // Re-pin it: flagging two people in a row shouldn't mean re-opening
        // the menu between each one.
        if (wasOpen) {{
          var w2 = $body.querySelector('.qa-sa-wrap');
          if (w2) w2.classList.add('is-open');
        }}
        if (window.opsRefresh) window.opsRefresh();
        // Someone is now expected to apply for this â€” start looking for who
        // to write to, in the background.
        if (at === -1 && window.abFindContact) window.abFindContact(rec);
        return;
      }}
      var btn = e.target.closest ? e.target.closest('[data-qa]') : null;
      // The Should-Attend button's job is to OPEN the picker. It used to write
      // attend_verdict and re-render, which tore the menu down mid-click.
      if (btn && btn.getAttribute('data-qa') === 'should-attend') {{
        e.stopPropagation();
        var wrap = btn.closest('.qa-sa-wrap');
        if (wrap) wrap.classList.toggle('is-open');
        return;
      }}
      // "Team â€” no one specific" keeps the old blanket flag available.
      var teamBtn = e.target.closest ? e.target.closest('[data-sa-team]') : null;
      if (teamBtn && window.opsWrite) {{
        e.stopPropagation();
        var _k2 = shouldAttendKind(rec.attend_verdict);
        rec.attend_verdict = (_k2 === 'human') ? '' : 'Worth attending';
        window.opsWrite(rec._table, rec._key, {{ attend_verdict: rec.attend_verdict || null }});
        var scT = overlay.querySelector('.modal-scroll');
        var topT = scT ? scT.scrollTop : 0;
        openEventModal(rec);
        if (scT) scT.scrollTop = topT;
        if (window.opsRefresh) window.opsRefresh();
        return;
      }}
      if (!btn || !window.opsWrite) return;
      var qa = btn.dataset.qa;
      var patch = {{}};
      // Set when an action deliberately CLOSED the pop-up, so the deferred
      // re-render below doesn't re-open what we just dismissed.
      var _qaClosed = false;
      if (qa === 'saved') {{ rec.saved = !rec.saved; patch.saved = rec.saved; }}
      else if (qa === 'archive') {{
        // Archive is PERSONAL (localStorage per signed-in name) â€” hides this from
        // MY view only. No DB write unless we're clearing a legacy team-wide hide.
        var _makeArch = (rec.hidden !== true);
        rec.hidden = _makeArch;
        patch.hidden = _makeArch;   // one shared flag â€” archiving hides it for everyone
        // ARCHIVING CLOSES THE POP-UP. It worked before this and still read as
        // broken: you clicked hide and were left looking at the very event you
        // had just hidden, with the card behind the overlay. Closing shows you
        // the thing disappear, which is the whole point of the action.
        // Un-archiving does NOT close â€” you're bringing something back to look
        // at it (Hurley 2026-08-05).
        if (_makeArch) {{
          if (_qaFullTimer) {{ clearTimeout(_qaFullTimer); _qaFullTimer = null; }}
          if (window.closeEventModal) window.closeEventModal();
          _qaClosed = true;
        }}
      }}
      else if (qa === 'interested') {{
        var me = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || '';
        if (!me) return;  // no name entered â€” nothing to toggle
        var ilist = (rec.interested || []).slice();
        var hit = -1;
        for (var z = 0; z < ilist.length; z++) {{ if (String(ilist[z]).toLowerCase() === me.toLowerCase()) {{ hit = z; break; }} }}
        if (hit === -1) {{
          ilist.push(me);
          // Interest funnels into Angela's Should-Attend list (a confirmed,
          // human Worth-attending) so flagged events surface in her filter.
          if (shouldAttendKind(rec.attend_verdict) !== 'human') {{
            rec.attend_verdict = 'Worth attending';
            patch.attend_verdict = 'Worth attending';
          }}
          // A fresh flag revives it in Angela's queue if it was dismissed.
          rec.queue_dismissed = false;
          patch.queue_dismissed = false;
        }} else {{ ilist.splice(hit, 1); }}
        rec.interested = ilist;
        patch.interested = ilist;
        // Flagging in (not out) is the signal that this one matters.
        if (hit === -1 && window.abFindContact) window.abFindContact(rec);
      }}
      else if (qa === 'attending') {{
        // Per-person: toggle the signed-in person in the attendees list, then
        // keep the event-level Attending stage in sync (on iff anyone attends).
        var meA = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || '';
        if (!meA) return;
        var meAk = meA.trim().split(/\\s+/)[0].toLowerCase();
        var att = (rec.attendees || []).slice();
        var aHit = -1;
        for (var w = 0; w < att.length; w++) {{ if (String(att[w]).toLowerCase() === meAk) {{ aHit = w; break; }} }}
        if (aHit === -1) att.push(meAk); else att.splice(aHit, 1);
        rec.attendees = att;
        patch.attendees = att;
        var atags = (rec.stage_tags || []).slice();
        var hadAtt = atags.indexOf('Attending') !== -1;
        // Attending is an end state too, so it retires the in-flight stages the
        // same way Booked and Rejected do.
        if (att.length && !hadAtt) {{ atags.push('Attending'); atags = _abRetireInFlight(atags); }}
        else if (!att.length && hadAtt) atags.splice(atags.indexOf('Attending'), 1);
        var aOrder = window.opsStageOrder || [];
        if (aOrder.length) atags = aOrder.filter(function (s) {{ return atags.indexOf(s) !== -1; }});
        rec.stage_tags = atags;
        patch.status_tags = atags;
      }}
      else if (qa === 'followed-up' || qa === 'followed-up-minus') {{
        // The Ã—N on this step counts LOGGED chases, so a tag-only toggle could
        // never turn it off â€” click, nothing moves, click again, still nothing
        // (Hurley 2026-07-30). Clicking writes the log itself.
        var _fuList = rec.follow_ups;
        if (typeof _fuList === 'string') {{ try {{ _fuList = JSON.parse(_fuList); }} catch (e) {{ _fuList = []; }} }}
        _fuList = Array.isArray(_fuList) ? _fuList.slice() : [];
        var _fuTags = (rec.stage_tags || []).slice();
        var _meFu = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || '';
        var _fuToday = window.abTodayIso ? window.abTodayIso() : '';
        // The pill only ever ADDS; the "âˆ’" beside it only ever removes. One
        // click, one predictable direction (Hurley 2026-07-30) â€” the old
        // single-pill toggle meant you couldn't log two chases in a row.
        if (qa === 'followed-up-minus') {{
          // Take back the most recent QUICK entry â€” one logged from the pill,
          // so it carries no note. A chase someone typed a note against is real
          // history and comes off via the trash can on its own row instead.
          var _cut = -1, _cutOn = '';
          for (var _f1 = 0; _f1 < _fuList.length; _f1++) {{
            var _e1 = _fuList[_f1] || {{}};
            if (String(_e1.note || '').trim()) continue;
            var _on1 = String(_e1.on || '');
            if (_cut === -1 || _on1 >= _cutOn) {{ _cut = _f1; _cutOn = _on1; }}
          }}
          if (_cut === -1) return;              // nothing safe to remove
          _fuList.splice(_cut, 1);
        }} else {{
          _fuList.push({{ on: _fuToday, by: _meFu, note: '' }});
        }}
        // Keep the tag honest: it means "there are chases on record".
        var _fuHad = _fuTags.indexOf('Followed up');
        if (_fuList.length && _fuHad === -1) _fuTags.push('Followed up');
        else if (!_fuList.length && _fuHad !== -1) _fuTags.splice(_fuHad, 1);
        rec.follow_ups = _fuList;
        patch.follow_ups = _fuList;
        _fuTags = window.abStageImply(_fuTags);
        rec.stage_tags = _fuTags;
        patch.status_tags = _fuTags;
      }}
      else if (qa === 'submitted' || qa === 'outreach' || qa === 'booked' || qa === 'rejected') {{
        var stage = qa === 'submitted' ? 'Submitted'
                  : (qa === 'outreach' ? 'Initial outreach'
                  : (qa === 'booked' ? 'Booked' : 'Rejected'));
        var _st = _applyStageToggle(rec, stage);
        patch.status_tags = _st.tags;
        // Submitted means the outreach email is next â€” have the contact ready.
        if (stage === 'Submitted' && _st.turnedOn && window.abFindContact) window.abFindContact(rec);
      }}
      else if (qa === 'should-attend') {{
        // human -> clear; AI-suggested OR none -> set a CONFIRMED human
        // Should-Attend (this is how Angela promotes an AI pick to the real list).
        var _k = shouldAttendKind(rec.attend_verdict);
        rec.attend_verdict = (_k === 'human') ? '' : 'Worth attending';
        patch.attend_verdict = rec.attend_verdict || null;
      }}
      else {{ return; }}
      // A personal archive toggle writes no DB patch â€” skip the empty upsert.
      if (Object.keys(patch).length) window.opsWrite(rec._table, rec._key, patch);
      // Every click used to rebuild the WHOLE modal â€” 50ms of synchronous work
      // plus a chat re-render â€” which is why the pipeline felt sluggish and why
      // clicking the follow-up pill twice in a row often lost the second one: a
      // real mouse click needs mousedown and mouseup on the SAME element, and
      // the rebuild replaced that element underneath the cursor
      // (Hurley 2026-07-30).
      //
      // So the click now repaints only what it changed, and the full rebuild is
      // deferred until the clicking stops.
      _qaLightRefresh(rec, qa);
      // Stage toggles: the bar IS the whole change, and _qaLightRefresh has
      // already repainted it synchronously from rec. Rebuilding the modal
      // 500ms later only made the click feel late (Hurley 2026-07-31).
      // Follow-ups and interest DO touch other sections, so they still settle.
      if (qa === 'submitted' || qa === 'outreach' || qa === 'booked' || qa === 'rejected') {{
        if (window.opsRefresh) window.opsRefresh();
        return;
      }}
      if (_qaFullTimer) clearTimeout(_qaFullTimer);
      // Archiving closes the pop-up. Without this guard the close landed and
      // then this timer re-opened the very event 500ms later, which looked
      // exactly like the click had done nothing (Hurley 2026-08-05).
      if (_qaClosed) {{ if (window.opsRefresh) window.opsRefresh(); return; }}
      _qaFullTimer = setTimeout(function () {{
        _qaFullTimer = null;
        var _sc0 = overlay.querySelector('.modal-scroll');
        var _top = _sc0 ? _sc0.scrollTop : 0;
        openEventModal(rec);
        // openEventModal rewrites $body, so the old node is stale â€” re-query.
        var _sc1 = overlay.querySelector('.modal-scroll');
        if (_sc1) _sc1.scrollTop = _top;
      }}, 500);
      // Archive lives in localStorage (no realtime echo), so re-render the grid
      // ourselves to move the card into / out of the per-person Hidden section.
      if (qa === 'archive' && window.opsRefresh) window.opsRefresh();
    }};
    bar.addEventListener('click', window.__qaClick);
  }}

  // Edit form â€” mirrors the READ-ONLY field layout (same .modal-field rows /
  // labels / spacing) so edit mode looks just like view mode, only editable.
  // Each control saves to the right table (event_state by num / manual_events
  // by id) via window.opsWrite. Catalog edits write override columns.
  function editFormHtml(rec) {{
    if (!rec || !rec._table || rec._key == null) return '';
    var isCat = rec._table === 'event_state';
    function opt(v, cur) {{
      return '<option value="' + esc(v) + '"' + (String(cur || '') === v ? ' selected' : '') + '>' + (v || 'â€”') + '</option>';
    }}
    function ef(label, control) {{
      // A single labelable control â†’ wrap in <label> so the field name is
      // programmatically associated (and clicking it focuses the control).
      // Groups (stage chips, interested/attending checkboxes) carry their own
      // per-item <label>s, so wrap them as a named role="group" instead â€” never
      // a <label> (that would nest labels and hijack clicks).
      var nControls = (control.match(/<(input|select|textarea)/g) || []).length;
      var isGroup = nControls !== 1 || control.indexOf('me-ints') !== -1 || control.indexOf('me-stages') !== -1;
      if (isGroup) {{
        return '<div class="modal-field" role="group" aria-label="' + esc(label) + '"><span class="k">' + esc(label) + '</span>' + control + '</div>';
      }}
      return '<label class="modal-field"><span class="k">' + esc(label) + '</span>' + control + '</label>';
    }}
    function inp(f, val, ph) {{
      return '<input class="me-input" type="text" data-edit="' + f + '" value="' + esc(val || '') + '"' + (ph ? ' placeholder="' + esc(ph) + '"' : '') + '>';
    }}
    function ta(f, val, rows) {{
      return '<textarea class="me-input" data-edit="' + f + '" rows="' + (rows || 3) + '">' + esc(val || '') + '</textarea>';
    }}
    // Legacy "Status label" dropdown (Sponsorship Only, etc.), built from the
    // shared status palette bridged as window.opsStatusOptions. data-edit="status"
    // so it saves via opsWrite (event_state for catalog, manual_events for manual).
    // statusDD removed with the Status marker field (Hurley 2026-07-31). The
    // `status` column is still stored and still read â€” the legacy marker just
    // isn't hand-set from the edit form any more.
    var stages = rec.stage_tags || [];
    var order = window.opsStageOrder || ['Submitted', 'Initial outreach', 'Followed up', 'Meeting held', 'Booked', 'Attending'];
    // Pipeline chips = the SPEAKING track only. "Attending" is managed per-person
    // via the Attending bubbles below (which sync the Attending stage), not as a
    // manual pipeline toggle.
    var chips = order.filter(function (s) {{ return s !== 'Attending'; }}).map(function (s) {{
      return '<button type="button" class="me-stage' + (stages.indexOf(s) !== -1 ? ' on' : '') + '" data-stage="' + esc(s) + '">' + esc(s) + '</button>';
    }}).join('');
    var interested = rec.interested || [];
    var intChips = AB_ROSTER.map(function (n) {{
      return '<label class="me-int' + (interested.indexOf(n) !== -1 ? ' on' : '') + '"><input type="checkbox" data-interested="' + esc(n) + '"' + (interested.indexOf(n) !== -1 ? ' checked' : '') + '>' + esc(n) + '</label>';
    }}).join('');
    // ArcticBlue speaker â€” bubbles (multi-select) from the roster, like Attending.
    var _spTok = String(rec.speaker || '').toLowerCase().split(/[,;/&]| and | plus /).map(function (s) {{ return s.trim(); }}).filter(Boolean);
    var spChips = AB_ROSTER.map(function (n) {{
      var on = _spTok.indexOf(n.toLowerCase()) !== -1;
      return '<label class="me-int' + (on ? ' on' : '') + '"><input type="checkbox" data-speaker="' + esc(n) + '"' + (on ? ' checked' : '') + '>' + esc(n) + '</label>';
    }}).join('');
    // Attending â€” bubbles from the roster (first names, no last names). The stored
    // key is the lowercased first name (= persona key for the Day-Of brief).
    var attendees = rec.attendees || [];
    var attChips = AB_ROSTER.map(function (n) {{
      var on = attendees.indexOf(n.toLowerCase()) !== -1;
      return '<label class="me-int' + (on ? ' on' : '') + '"><input type="checkbox" data-attending="' + esc(n.toLowerCase()) + '"' + (on ? ' checked' : '') + '>' + esc(n) + '</label>';
    }}).join('');
    var pris = ['', 'High', 'Medium', 'Low'];
    var p2p = ['', 'Yes', 'No', 'Both'];
    var curPri = isCat ? (rec.priority_override || rec.priority || '') : (rec.priority || '');
    var priv = rec.is_private === true;
    var h = '';
    // ---- Sectioned edit form (Angela) --------------------------------------
    // This had grown to ~33 fields in one flat column, so editing meant
    // scrolling up and down hunting for the zone you wanted. Fields are now
    // grouped into labelled sections separated by a rule, in the order she
    // actually works: what it is -> notes -> the speaking pipeline -> who's
    // going -> who to contact -> reference facts -> the stuff nobody fills in.
    // sec() drops any section whose body came back empty, so a private event
    // (which hides most fields) never shows a stray header.
    function sec(title, body, fold) {{
      if (!body) return '';
      if (fold) {{
        return '<details class="me-sec me-sec-fold"><summary class="me-sec-h">' + esc(title) + '</summary>' + body + '</details>';
      }}
      return '<section class="me-sec"><h4 class="me-sec-h">' + esc(title) + '</h4>' + body + '</section>';
    }}

    // Basics â€” what the card shows at a glance. Name / Date / Location are
    // editable on EVERY card: manual events store them directly, catalog events
    // as event_state overrides (needs scripts/2026-07-14_event_state_identity.sql
    // â€” until it runs, saving these three on a catalog event fails, while manual
    // events + every other catalog field keep working).
    h += sec('Basics',
      ef('Event name', inp('name', rec.name)) +
      ef('Date', inp('date_str', rec.date_str, 'e.g. Sept 14\\u201316, 2026')) +
      ef('Location', inp('location', rec.location)) +
      ef((isCat ? 'Website / link' : 'Website'), inp('url', rec.url, 'https://')) +
      ef('Private event', '<label class="me-toggle"><input type="checkbox" data-private' + (priv ? ' checked' : '') + '> Private / invite-only &mdash; hide the public-event fields, keep just POC, link, notes &amp; chat</label>'));

    // Notes â€” the most-used free-text field (159 of 627 events have one), so it
    // gets its own zone up top. The section header IS the label, hence the
    // aria-label instead of a duplicate visible one.
    h += sec('Notes',
      '<div class="modal-field"><textarea class="me-input" data-edit="notes" rows="4" aria-label="Notes">' + esc(rec.notes || '') + '</textarea></div>');

    // Contacts â€” everything you'd search a person by. Kept for private events
    // too: the POC is the whole point of a private event.
    // Angela only, matching the read view. Contacts were merged into Speaking &
    // submission, which is hers alone, so the read view already hides them from
    // everyone else â€” but the EDIT form still offered them, which meant Thor
    // could change a POC he cannot see (Hurley 2026-07-30). Outreach is hers.
    if (window.isAngelaUser && window.isAngelaUser()) {{
      var sContact = ef('Contact info', inp('contact_info', rec.contact_info));
      if (!isCat) {{
        sContact += ef('POC name', inp('poc_name', rec.poc_name));
        sContact += ef('POC email', inp('poc_email', rec.poc_email));
      }}
      // A few words on who they are â€” this is what tells Angela what to send.
      sContact += ef('Who they are', inp('poc_note', rec.poc_note,
                     'e.g. Programme director \u2014 owns the speaker agenda'));
      h += sec('Contacts', sContact);
    }}


    // Speaking & submission â€” the pipeline zone.
    var sSpeak = ef('Pipeline stage', '<div class="me-stages">' + chips + '</div>');
    // "Submitted on" â€” Angela records the date the application went out. Only
    // shown in her view, and only while the Submitted stage is on (the stage
    // toggle reveals/hides it). The generic data-edit wiring persists it.
    if (window.isAngelaUser && window.isAngelaUser()) {{
      var _subVal = (String(rec.submitted_at || '').match(/^\\d{{4}}-\\d{{2}}-\\d{{2}}/) || [''])[0];
      var _subOn = stages.indexOf('Submitted') !== -1;
      sSpeak += '<label class="modal-field me-submitted-field"' + (_subOn ? '' : ' style="display:none"') + '>' +
                '<span class="k">Submitted on</span>' +
                '<input class="me-input" type="date" data-edit="submitted_at" value="' + esc(_subVal) + '"></label>';
    }}
    sSpeak += ef('ArcticBlue speaker', '<div class="me-ints">' + spChips + '</div>');
    if (!priv) {{
      sSpeak += ef('Speaker topic \\u2014 drives the day-of news pull', inp('speaker_topic', rec.speaker_topic, 'e.g. AI workforce enablement'));
      sSpeak += ef('Apply to speak link \\u2014 powers the card button', inp('apply_url', rec.apply_url, 'https:// CFP or application page'));
      sSpeak += ef('Speaking Notes', ta('speaking_route', rec.speaking_route, 2));
      sSpeak += ef('Deadline', inp('deadline', rec.deadline, 'e.g. July 10, 2026'));
      // How we'd get in, in one place: is it pay-to-play, and the legacy status
      // marker (Sponsorship Only, Curated invite, ...). ONE dropdown for both
      // catalog and manual â€” Angela hit two edit sections that disagreed.
      sSpeak += ef('Pay-to-play', '<select class="me-input" data-edit="pay_to_play">' + p2p.map(function (v) {{ return opt(v, rec.pay_to_play); }}).join('') + '</select>');
    }}
    // Same in the editor â€” these are her fields to keep straight.
    if (window.isAngelaUser && window.isAngelaUser()) h += sec('Speaking & submission', sSpeak);

    // Attending & team â€” who from ArcticBlue is going / interested / assigned.
    var sTeam = ef('Attending \\u2014 surfaces a Day-Of brief', '<div class="me-ints">' + attChips + '</div>') +
                ef('Interested (joins Angela\\'s apply queue)', '<div class="me-ints">' + intChips + '</div>') +
                ef('Priority', '<select class="me-input" data-edit="' + (isCat ? 'priority_override' : 'priority') + '">' + pris.map(function (v) {{ return opt(v, curPri); }}).join('') + '</select>');
    // "Ask a teammate to reach out" â€” Angela assigns whoever has the personal
    // connection to the event; it surfaces at the top of that person's My
    // Lineup. Angela-only (it's her coordination tool).
    if (window.isAngelaUser && window.isAngelaUser()) {{
      var _outr = (rec.outreach_assignees || []).map(function (x) {{ return String(x).toLowerCase(); }});
      var outrChips = AB_ROSTER.map(function (n) {{
        var on = _outr.indexOf(n.toLowerCase()) !== -1;
        return '<label class="me-int' + (on ? ' on' : '') + '"><input type="checkbox" data-outreach="' + esc(n.toLowerCase()) + '"' + (on ? ' checked' : '') + '>' + esc(n) + '</label>';
      }}).join('');
      sTeam += ef('Ask a teammate to reach out \\u2014 they may have a connection', '<div class="me-ints">' + outrChips + '</div>');
      // A conflict the DATES can't reveal â€” a board meeting, a holiday, a
      // trip that makes this unreachable. Overlapping events are detected
      // automatically; this is for everything else (Hurley 2026-07-30).
      sTeam += ef('Scheduling conflict (optional)', inp('conflict_note', rec.conflict_note, 'e.g. Thor is at the board offsite that week'));
    }}
    // Attending & team is coordination: who's assigned, who to chase, the
    // triage priority. Everyone else sets their OWN attending / interested from
    // the buttons at the top of the card, so for them this whole section is
    // someone else's controls (Hurley 2026-07-30).
    if (window.isAngelaUser && window.isAngelaUser()) h += sec('Attending & team', sTeam);

    // Event details â€” the reference facts, mostly filled by the nightly enrich.
    var sDet = '';
    if (!priv) {{
      if (!isCat) sDet += ef('Region', '<select class="me-input" data-edit="region">' + ['', 'US & Canada', 'Latin America', 'Europe', 'Africa', 'MENA', 'Asia-Pacific', 'Global'].map(function (v) {{ return opt(v, rec.region); }}).join('') + '</select>');
      sDet += ef('Overview', ta('about', rec.about));
      sDet += ef('Topics', ta('focus_areas', rec.focus_areas, 2));
      sDet += ef('Typical attendees', ta('typical_attendees', rec.typical_attendees, 2));
      sDet += ef('Type', inp('type', rec.type, 'e.g. Enterprise'));
      if (seesAudience()) sDet += ef('Audience (buyers vs sellers)', '<select class="me-input" data-edit="audience_type">' + ['', 'Buyer-rich', 'Mixed', 'Vendor-heavy'].map(function (v) {{ return opt(v, rec.audience_type); }}).join('') + '</select>');
      sDet += ef('Meetings & networking (1:1s)', inp('meeting_formats', rec.meeting_formats, 'e.g. Hosted 1:1 meetings; roundtables'));
      sDet += ef('Price to attend', inp('pricing', rec.pricing, 'e.g. $1,995 delegate pass; free for buyers'));
      sDet += ef('Attendee count', inp('attendee_count', rec.attendee_count, 'e.g. 1,500+'));
      sDet += ef('Venue', inp('venue', rec.venue));
      sDet += ef('Past / announced speakers', ta('past_speakers', rec.past_speakers, 2));
    }}
    h += sec('Event details', sDet);

    // Rarely used â€” real fields that are essentially never filled in (Track is
    // set on 0 of 627 events; Paid / Speaking fee / Post-mortem / Additional
    // contacts / POC LinkedIn are all 0 too). Folded away rather than deleted,
    // so nothing is lost and the form above stays scannable.
    var sRare = '';
    if (!priv) {{
      if (!isCat) {{
        sRare += ef('Submission status', inp('submission_status', rec.submission_status));
        sRare += ef('Additional contacts', ta('additional_contacts', rec.additional_contacts, 2));
        sRare += ef('Speaking fee', inp('speaking_fee', rec.speaking_fee));
        var paidCur = rec.paid === true ? 'true' : (rec.paid === false ? 'false' : '');
        sRare += ef('Paid', '<select class="me-input" data-edit="paid">' + [['', '\\u2014'], ['true', 'Yes'], ['false', 'No']].map(function (o) {{ return '<option value="' + o[0] + '"' + (paidCur === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }}).join('') + '</select>');
      }}
      sRare += ef('Post-mortem (ROI: contacts \\u00b7 meetings \\u00b7 sales vs cost)', ta('postmortem', rec.postmortem, 2));
    }}
    if (!isCat) sRare += ef('POC LinkedIn', inp('poc_linkedin', rec.poc_linkedin));
    h += sec('Rarely used', sRare, true);
    h += '<div class="me-danger"><button type="button" class="me-delete">Delete this event</button>' +
         '<span class="me-danger-note">' + (isCat
           ? 'Removes this event from the tracker (stays gone after the daily sync).'
           : 'Removes this manually-added event. Cannot be undone.') + '</span></div>';
    return h;
  }}
  function wireEditForm(rec) {{
    var box = $body.querySelector('.modal-editform');
    if (!box || !window.opsWrite) return;
    box.querySelectorAll('.me-stage').forEach(function (btn) {{
      btn.addEventListener('click', function () {{
        var s = btn.dataset.stage;
        // Same rule as the quick bar, and repaint BOTH surfaces from the record
        // â€” never `classList.toggle` this button on its own. See
        // _repaintStageSurfaces for what that cost Angela.
        var _st = window.abApplyStageToggle(rec, s);
        window.opsWrite(rec._table, rec._key, {{ status_tags: _st.tags }});
        window.abRepaintStages(rec);
        // Submitted means the outreach email is next â€” have the contact ready.
        // The quick bar has always done this; the same click here used not to,
        // so which button you pressed decided whether we looked (Hurley
        // 2026-08-13). abFindContact only spends a lookup when there is NO
        // contact on file, at most once a week per event.
        if (s === 'Submitted' && _st.turnedOn && window.abFindContact) window.abFindContact(rec);
      }});
    }});
    box.querySelectorAll('[data-interested]').forEach(function (cb) {{
      cb.addEventListener('change', function () {{
        var list = (rec.interested || []).slice();
        var n = cb.dataset.interested;
        var i = list.indexOf(n);
        if (cb.checked && i === -1) list.push(n);
        else if (!cb.checked && i !== -1) list.splice(i, 1);
        // de-dupe but keep everyone â€” don't drop non-roster collaborators
        // added via the quick-bar "+ I'm interested".
        list = list.filter(function (x, idx) {{ return list.indexOf(x) === idx; }});
        rec.interested = list;
        var lbl = cb.closest('.me-int'); if (lbl) lbl.classList.toggle('on', cb.checked);
        window.opsWrite(rec._table, rec._key, {{ interested: list }});
      }});
    }});
    // ArcticBlue speaker â€” multi-select bubbles. Collect the checked names (in
    // roster/DOM order) into the comma-joined speaker string.
    box.querySelectorAll('[data-speaker]').forEach(function (cb) {{
      cb.addEventListener('change', function () {{
        var names = [];
        box.querySelectorAll('[data-speaker]').forEach(function (b) {{ if (b.checked) names.push(b.dataset.speaker); }});
        var val = names.join(', ');
        rec.speaker = val;
        var lbl = cb.closest('.me-int'); if (lbl) lbl.classList.toggle('on', cb.checked);
        window.opsWrite(rec._table, rec._key, {{ speaker: val || null }});
      }});
    }});
    box.querySelectorAll('[data-attending]').forEach(function (cb) {{
      cb.addEventListener('change', function () {{
        var list = (rec.attendees || []).slice();
        var k = cb.dataset.attending;
        var i = list.indexOf(k);
        if (cb.checked && i === -1) list.push(k);
        else if (!cb.checked && i !== -1) list.splice(i, 1);
        var order = AB_ROSTER.map(function (n) {{ return n.toLowerCase(); }});
        // Keep roster order, then any non-roster keys already present.
        list = order.filter(function (x) {{ return list.indexOf(x) !== -1; }})
                    .concat(list.filter(function (x) {{ return order.indexOf(x) === -1; }}));
        rec.attendees = list;
        var lbl = cb.closest('.me-int'); if (lbl) lbl.classList.toggle('on', cb.checked);
        // Keep the Attending pipeline stage in sync with the attendees roster, so
        // tagging someone as attending also lights the Attending filter + Day-Of
        // brief (and clearing everyone removes it). Speaking stages are untouched.
        var tags = (rec.stage_tags || []).slice();
        var hasAtt = tags.indexOf('Attending') !== -1;
        if (list.length && !hasAtt) tags.push('Attending');
        else if (!list.length && hasAtt) tags.splice(tags.indexOf('Attending'), 1);
        var sOrder = window.opsStageOrder || [];
        if (sOrder.length) tags = sOrder.filter(function (s) {{ return tags.indexOf(s) !== -1; }});
        rec.stage_tags = tags;
        window.opsWrite(rec._table, rec._key, {{ attendees: list, status_tags: tags }});
        // This ticks the Attending stage on or off behind the scenes, so both
        // stage surfaces have to catch up or the next stage click reads a stale
        // button and undoes it.
        window.abRepaintStages(rec);
      }});
    }});
    // "Ask a teammate to reach out" bubbles â€” collect the checked first names
    // (roster/DOM order) into outreach_assignees. No stage side-effects.
    box.querySelectorAll('[data-outreach]').forEach(function (cb) {{
      cb.addEventListener('change', function () {{
        var list = [];
        box.querySelectorAll('[data-outreach]').forEach(function (b) {{ if (b.checked) list.push(b.dataset.outreach); }});
        rec.outreach_assignees = list;
        var lbl = cb.closest('.me-int'); if (lbl) lbl.classList.toggle('on', cb.checked);
        window.opsWrite(rec._table, rec._key, {{ outreach_assignees: list }});
      }});
    }});
    box.querySelectorAll('[data-edit]').forEach(function (el) {{
      el.addEventListener('change', function () {{
        var field = el.dataset.edit;
        var val = (el.value == null ? '' : String(el.value)).trim();
        if (field === 'name' && !val) {{ el.value = rec.name || ''; return; }}
        var out = val === '' ? null : val;
        // Clearing a descriptive field on a CATALOG event: a plain null override
        // just falls back to the (often junky) catalog value, so the cleared text
        // "pops back up" â€” e.g. deleting a stray website from Contact info didn't
        // stick. Write a '__cleared__' sentinel instead; the render merge treats it
        // as an explicit blank that WINS over the catalog value. (Manual events own
        // their columns outright, so null already clears them there.)
        var _CLEARABLE_CAT = {{ contact_info:1, why:1, about:1, focus_areas:1, typical_attendees:1, speaking_route:1, venue:1, pricing:1, past_speakers:1, meeting_formats:1, attendee_count:1, deadline:1 }};
        if (out === null && rec._table === 'event_state' && _CLEARABLE_CAT[field]) out = '__cleared__';
        if ((field === 'url' || field === 'apply_url') && out && !/^https?:\\/\\//i.test(out)) out = 'https://' + out;
        // "Paid" is a boolean column on manual_events â€” coerce the select value.
        if (field === 'paid') out = (val === 'true') ? true : (val === 'false' ? false : null);
        var patch = {{}}; patch[field] = out;
        // The sentinel goes to the DB, but the in-memory record shows a real blank.
        var _recVal = (out === '__cleared__') ? '' : out;
        if (field === 'priority_override') rec.priority = _recVal;
        else rec[field] = _recVal;
        // Editing the Date must ALSO update the structured start_date / end_date
        // â€” the card, calendar and iCal read those (they win over the free-text
        // date_str). Applies to BOTH manual events and catalog events (whose
        // event_state now carries date_str/start_date/end_date overrides).
        if (field === 'date_str') {{
          var _dd = {{}};
          try {{ _dd = (window.opsDeriveDates && out) ? (window.opsDeriveDates(out) || {{}}) : {{}}; }} catch (e) {{ _dd = {{}}; }}
          patch.start_date = _dd.start_date || null;
          patch.end_date   = _dd.end_date || _dd.start_date || null;
          rec.start_date = patch.start_date;
          rec.end_date   = patch.end_date;
        }}
        window.opsWrite(rec._table, rec._key, patch);
      }});
    }});
    // Private-event toggle â€” persist, then re-render the modal so both the
    // read view and the edit form reflect the simplified (or full) layout.
    var privCb = box.querySelector('[data-private]');
    if (privCb) privCb.addEventListener('change', function () {{
      rec.is_private = privCb.checked;
      window.opsWrite(rec._table, rec._key, {{ is_private: privCb.checked }});
      if (window.openEventModal) window.openEventModal(rec);
    }});
    // Delete (manual events only) â€” lives at the bottom of the Edit form.
    var delBtn = box.querySelector('.me-delete');
    if (delBtn) delBtn.addEventListener('click', function () {{
      if (!window.confirm('Delete "' + (rec.name || 'this manual event') + '"? This cannot be undone.')) return;
      delBtn.disabled = true; delBtn.textContent = 'Deletingâ€¦';
      if (window.opsDelete) {{
        window.opsDelete(rec._table, rec._key).then(function (resp) {{
          if (resp && resp.error) {{ delBtn.disabled = false; delBtn.textContent = 'Delete this event'; return; }}
          if (window.closeEventModal) window.closeEventModal();
        }});
      }}
    }});
  }}

  // "Enrich" â€” POST the event to /api/enrich_one, which researches the gaps via
  // Perplexity + Exa and writes the fill-only-missing patch server-side. We then
  // merge the patch into rec and re-render so the new facts show immediately.
  function wireEnrichButton(rec) {{
    var btn = document.getElementById('modal-enrich-btn');
    if (!btn) return;
    btn.addEventListener('click', function () {{
      if (btn.getAttribute('aria-busy')) return;
      btn.setAttribute('aria-busy', '1');
      var prev = btn.innerHTML;
      btn.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">â³</span> Enrichingâ€¦';
      fetch('/api/enrich_one', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ event: rec, table: rec._table, key: rec._key }})
      }}).then(function (r) {{ return r.json(); }}).then(function (data) {{
        btn.removeAttribute('aria-busy'); btn.innerHTML = prev;
        if (!data || data.skipped) {{ window.alert("Enrichment isn't set up yet â€” no research API keys are configured on the server."); return; }}
        if (data.error) {{ window.alert('Enrichment failed: ' + (data.detail || data.error)); return; }}
        var filled = data.filled || [];
        var patch = data.patch || {{}};
        for (var k in patch) {{ if (Object.prototype.hasOwnProperty.call(patch, k)) rec[k] = patch[k]; }}
        openEventModal(rec);
        if (window.opsRefresh) window.opsRefresh();
        var note = filled.length
          ? '<div class="modal-enrich-note ok">&#10022; Enriched â€” filled: ' + esc(filled.join(', ')) + '</div>'
          : '<div class="modal-enrich-note">No new details found â€” everything we could fill is already here.</div>';
        if ($body) $body.insertAdjacentHTML('afterbegin', note);
      }}).catch(function (e) {{
        btn.removeAttribute('aria-busy'); btn.innerHTML = prev;
        window.alert('Enrichment error: ' + e);
      }});
    }});
  }}

  function _fuWhen(iso) {{
    try {{
      return new Date(String(iso).slice(0, 10) + 'T00:00:00')
        .toLocaleDateString('en-US', {{ month: 'short', day: 'numeric', year: 'numeric' }});
    }} catch (e) {{ return String(iso || ''); }}
  }}

  // Trash can for the top-left Delete (same glyph as the profile file-delete).
  var MD_TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  var MD_PENCIL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';

  // The record the pop-up is CURRENTLY showing. #modal-body is one permanent
  // node that every event re-renders into, so anything delegated on it must
  // read the event from here rather than from a closure â€” see wirePocActions.
  var _pocRec = null;
  // Same trap, smaller blast radius: the "Add event" menu closes on any
  // document click, and that listener was re-added on every render.
  var _sibCloser = null;

  function openEventModal(rec) {{
    if (!rec) return;
    // Blue border when it's yours, exactly as the card face reads â€” this
    // replaces the "<Name> is interested" sentence that used to sit in the
    // quickbar saying the same thing in words (Hurley 2026-07-31).
    var _mCard = document.querySelector('.modal-card');
    // (no per-person 'is-mine' border â€” the merged view shows the same pop-up
    // to everyone; who's interested is named in the quickbar instead.)
    // Top labels: NONE (Hurley 2026-07-30). Priority, event type, the pipeline
    // stages, Pay-to-play, Seed and Private all repeated something the reader
    // already has â€” the stages are the workflow route right below, and the rest
    // are on the card face they just clicked through. "Sponsorship Only" was
    // held back as the last exception; it's gone too now. The status marker is
    // still stored and still editable in Edit, and the door-closed reason
    // ("paid slots only") already carries it where it matters.
    $badges.innerHTML = '';

    $date.textContent  = rec.date_str || '';
    // A private / invite-only event has no public page â€” a scraped URL is almost
    // always the wrong page (Angela). Never link a private event's title; show
    // plain text so it can't "bring a fake link".
    if (rec.url && rec.is_private !== true) {{
      $title.innerHTML = '<a class="modal-title-link" href="' + esc(rec.url) + '" target="_blank" rel="noopener">' + esc(rec.name || 'Event') + '<span class="event-link-arrow" aria-hidden="true">â†—</span></a>';
    }} else {{
      $title.textContent = rec.name || 'Event';
    }}
    // Star + archive sit beside the NAME and appear on hover, exactly as they
    // do on the card face â€” same icons, same behaviour, so the modal isn't a
    // second language to learn (Hurley 2026-07-30).
    (function () {{
      var _tIn = !!(rec.interested || []).some(function (n) {{
        var me = ((window.opsCurrentUser ? window.opsCurrentUser() : '') || '').trim().split(/\s+/)[0].toLowerCase();
        return me && String(n).toLowerCase().split(/\s+/)[0] === me;
      }});
      var _tMan  = rec._table === 'manual_events';
      var _tArch = (window.opsIsArchivedForMe ? window.opsIsArchivedForMe(_tMan, rec._key, rec.hidden === true) : !!rec.hidden);
      var starD = 'M12 2.6l2.72 5.51 6.08.88-4.4 4.29 1.04 6.06L12 16.48 6.56 19.34l1.04-6.06-4.4-4.29 6.08-.88z';
      var wrap = document.createElement('span');
      wrap.className = 'mt-acts';
      wrap.innerHTML =
        '<button type="button" class="mt-ico' + (_tIn ? ' is-on' : '') + '" data-qa="interested" ' +
          'title="' + (_tIn ? "You're interested \u2014 click to clear" : "I'm interested") + '" aria-label="I am interested">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true" fill="' + (_tIn ? 'currentColor' : 'none') +
          '" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="' + starD + '"/></svg></button>' +
        // TELL THE TRUTH ABOUT WHAT THE CLICK DOES. A handful of events carry
        // the LEGACY team-wide `hidden` flag; on those this button un-hides for
        // EVERYONE and writes to the database, while the label read "Archived
        // for you \u2014 click to bring it back". A destructive, team-wide action
        // wearing a personal label is exactly what gets clicked by accident \u2014
        // it caught me while testing (Hurley 2026-08-05).
        '<button type="button" class="mt-ico' + (_tArch ? ' is-on' : '') + '" data-qa="archive" ' +
          'title="' + (rec.hidden === true
              ? 'Archived for the team \u2014 click to bring it back for everyone'
              : (_tArch ? 'Archived for the team \u2014 click to bring it back' : 'Archive \u2014 hides this event for the whole team')) +
          '" aria-label="' + (rec.hidden === true ? 'Un-archive for the whole team' : 'Archive for the whole team') + '">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>' +
          '<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/>' +
          '<path d="M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>' +
          '<path d="m2 2 20 20"/></svg></button>';
      $title.appendChild(wrap);
      wrap.querySelectorAll('[data-qa]').forEach(function (b5) {{
      // Bound through a wrapper, NOT as `window.__qaClick` directly. That
      // property is REASSIGNED (with this event's `rec` closed over) further
      // down in openEventModal, and addEventListener captures the function
      // OBJECT at bind time â€” so binding it here caught whatever was left from
      // the PREVIOUS pop-up, and on the first pop-up of a session it caught
      // `undefined` and attached no handler at all. That is why "hide" in the
      // event details did nothing (Hurley 2026-08-05); worse, on later opens it
      // would have acted on the previously-viewed event. The indirection defers
      // the lookup to click time, so it is always this event's handler.
        b5.addEventListener('click', function (ev5) {{ if (window.__qaClick) window.__qaClick(ev5); }});
      }});
    }})();
    // Just the city/venue â€” the region (MENA / Europe / â€¦) is redundant next
    // to it and adds nothing a reader needs.
    $loc.innerHTML = esc(rec.location || '');

    var html = '';
    html += quickBarHtml(rec);
    // Team Discussion thread â€” right after the quickbar (Status/Interested/
    // Hide: Archive), ahead of the read-only detail fields.
    html += '<div class="event-chat" id="event-chat-panel"></div>';

    // Read-only view â€” grouped into the SAME labelled zones as the edit form
    // (Angela: "break it up and group them more logically, i.e. attendees
    // together"). sec() drops a zone whose body came back empty, so a sparse or
    // private event never shows a bare header. Same .me-sec markup as the editor
    // so both views get the identical divider treatment.
    // "Why it fits ArcticBlue" removed from the read view (Hurley 2026-07-09) â€”
    // still used by search/suggestions scoring.
    // A zone holding exactly ONE field doesn't need the field's label â€” the
    // heading is already naming that value, so printing both reads as two
    // headings stacked on one line of content ("Who attends" / "Typical
    // attendees", "About the event" / "About"). The heading wins: it carries
    // the divider styling (Hurley 2026-07-29). Two or more fields keep their
    // labels, since then the heading can't tell them apart.
    function sec(title, body) {{
      if (!body) return '';
      if ((body.match(/class="modal-field"/g) || []).length === 1) {{
        var _m = body.match(/<span class="k">([\\s\\S]*?)<\\/span>/);
        var _lab = _m ? _m[1].replace(/<[^>]*>/g, '').trim().toLowerCase() : '';
        var _ttl = String(title || '').trim().toLowerCase();
        // The rule is one field WHOSE LABEL IS THE SECTION NAME â€” not any lone
        // field. Collapsing unconditionally stranded values under headings that
        // don't name them: "Speaking & submission / No" for pay-to-play
        // (Hurley 2026-07-30).
        if (_lab && (_lab === _ttl || _lab === _ttl.replace(/s$/, ''))) {{
          body = body.replace(/<span class="k">[\\s\\S]*?<\\/span>/, '');
        }}
      }}
      return '<section class="me-sec"><h4 class="me-sec-h">' + esc(title) + '</h4>' + body + '</section>';
    }}
    // Point of contact â€” the one detail that matters for a private event.
    // A contact is a PERSON: a name or an email. `contact_info` is very often
    // just the event's own domain ("ai4.io") or a registration URL, and the
    // section rendered that as "Contact info: ai4.io" â€” a Contacts heading over
    // something nobody can contact (Hurley 2026-07-30). opsContactText() is the
    // same test the card's âœ‰ badge uses: it strips URLs and bare domains and
    // returns what human-readable text is left, if any.
    var _ct  = window.opsContactText   || function (v) {{ return String(v == null ? '' : v).trim(); }};
    var _ctp = window.opsContactPerson || _ct;
    var contactBits = [];
    if (_ct(rec.poc_name))  contactBits.push(esc(rec.poc_name));
    if (rec.poc_email && String(rec.poc_email).indexOf('@') !== -1) {{
      contactBits.push('<a href="mailto:' + esc(rec.poc_email) + '">' + esc(rec.poc_email) + '</a>');
    }}
    if (rec.poc_linkedin) contactBits.push('<a href="' + esc(rec.poc_linkedin) + '" target="_blank" rel="noopener">LinkedIn â†—</a>');
    // Who they are, in a few words, under the name. A name and an address don't
    // tell you what to write â€” "programme director, owns the agenda" and
    // "sponsorship lead" get very different emails. Deliberately words, not a
    // confidence score: a number just raises "is 0.7 enough to email?", which
    // nobody can answer (Hurley 2026-07-31).
    var _pocNote = _ct(rec.poc_note) ? '<span class="poc-note">' + esc(rec.poc_note) + '</span>' : '';
    var pocHtml = (contactBits.length
                    ? field('Point of contact', contactBits.join(' Â· ') + _pocNote, true) : '') +
                  (_ctp(rec.contact_info) ? field('Contact info', rec.contact_info) : '');

    var _fuMine = !!(window.isAngelaUser && window.isAngelaUser());
    var _fuList = window.abFollowUps ? window.abFollowUps(rec) : [];
    // The chase LOG is Angela's worklist â€” dates, who, edit and delete controls.
    // For everyone else that machinery is noise, but what came back in those
    // chases is exactly what they want to know. So the notes travel and the log
    // doesn't: whatever Angela writes against a follow-up lands in everyone
    // else's Notes automatically (Hurley 2026-07-30).
    function _notesForReader() {{
      var base = String(rec.notes || '').trim();
      if (_fuMine || !_fuList.length) return base;
      // Compare on letters and digits only, so "Followed up with Terrapinn."
      // and "followed up with terrapinn" count as the same sentence and a note
      // already written into Notes is never repeated underneath it.
      function _norm(s) {{ return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }}
      // Angela writes the same thing twice in her own words â€” Notes say "I
      // followed up with her personally on 7/29" and the chase says "Followed
      // up w/ Jessica personally on 7/29." A substring test misses that, so
      // also treat a note as a repeat when nearly all of its words are already
      // on the page. Short fragments are exempt: too few words to judge.
      function _mostlySaid(text, hayTokens) {{
        // Whole tokens, not substrings â€” matching "he" inside "the" made
        // unrelated notes look like repeats. Two-letter words count: dropping
        // them left "Followed up w/ Jessica personally on 7/29" with only three
        // words to judge, under the minimum, so it slipped through as new.
        var w = _norm(text).split(' ').filter(function (x) {{ return x.length > 1; }});
        if (w.length < 4) return false;
        var hit = w.filter(function (x) {{ return hayTokens[x] === 1; }}).length;
        return hit / w.length >= 0.8;
      }}
      function _tokens(str) {{
        var m = {{}};
        _norm(str).split(' ').forEach(function (x) {{ if (x) m[x] = 1; }});
        return m;
      }}
      var seen = _norm(base), add = [];
      // Oldest first, so the merged block reads in the order it happened.
      _fuList.slice().reverse().forEach(function (f) {{
        var t = String((f || {{}}).note || '').trim();
        var n = _norm(t);
        if (!t || !n) return;
        if (seen.indexOf(n) !== -1) return;              // already said in Notes
        if (_mostlySaid(t, _tokens(seen))) return;       // ...or said in other words
        add.push((f.on ? _fuWhen(f.on) + ' â€” ' : '') + t);
        seen += ' ' + n;                                  // and don't repeat itself
      }});
      if (!add.length) return base;
      return base ? base + '\\n' + add.join('\\n') : add.join('\\n');
    }}
    var v = '';
    // Notes lead the read view â€” right below "Chat with the team" (Angela). The
    // zone heading already says "Notes", so the value goes in bare.
    v += sec('Notes', fieldBare(_notesForReader()));
    // Follow-up log â€” Angela's spreadsheet column, as a clean dated list, and
    // HERS ALONE (Hurley 2026-07-30). It used to show read-only to everyone
    // once there was a row, but the dates, the "reached out / followed up"
    // labels and the cadence badge are all worklist mechanics. What the rest of
    // the team actually needs from it â€” what came back â€” is merged into their
    // Notes above instead.
    if (_fuMine) {{
      var _fuSt = window.abFollowUpState
        ? window.abFollowUpState(rec, rec.stage_tags || [], '') : null;
      var _fuBody = '';
      // 'none' means no chase logged â€” that reads as noise on screen, so it
      // stays blank here. The fact still travels: the assistant is told
      // explicitly that nobody has chased it, so Thor gets it if he asks.
      //
      // And a badge that only repeats the single row beneath it is the same
      // noise: one bare entry "Jul 27 Â· Reached out" under "Followed up Jul 27"
      // says one thing twice (Hurley 2026-07-30). It comes back as soon as
      // there's something the rows DON'T say â€” a second entry, a note to
      // summarise, or a state other than "chased recently" (overdue, waiting,
      // door closed), which is the whole point of having it.
      // Restricting this to the 'ok' state was my own caveat and it was wrong:
      // on an event a fortnight out the same single bare entry comes back as
      // 'due' and the badge reappeared, which is what Hurley kept seeing. Any
      // cadence state â€” chased recently OR overdue â€” is derived from the row
      // itself, so with one bare entry it is pure repetition either way.
      // 'closed' and 'hold' stay: they describe the ORGANISER, which no row
      // says (Hurley 2026-07-30).
      // Count-based, plainly: ONE entry needs no badge â€” the row already says
      // the date, and if there's a note the row shows that too. From TWO the
      // badge earns its place, because "where are we across all of these" is
      // no longer readable at a glance. (This drops the earlier
      // one-entry-with-a-note exception â€” Hurley restated the rule on count
      // alone, 2026-07-30.) Closed and waiting-on-them always show: they
      // describe the ORGANISER, which no row states.
      var _fuEcho = {{ ok: 1, due: 1 }};
      // One ROW on screen -> no badge. That's one entry of our own, or one
      // inherited from a sibling event, which now renders as a row too.
      var _fuOnlyEcho = (_fuSt && _fuEcho[_fuSt.state] &&
                         (_fuList.length === 1 || (_fuList.length === 0 && _fuSt.via)));
      if (_fuSt && _fuSt.state !== 'none' && !_fuOnlyEcho) {{
        var _fuLab = _fuSt.label, _fuCls = _fuSt.state;
        // "Follow up now â€” 6 days since Jul 24" is Angela's worklist talking.
        // On a speaker's screen it reads as a job for HIM, so the chase-cadence
        // states become a plain statement of fact. Where we stand with the
        // ORGANISER (waiting on them, door closed) is his business and stays.
        if (!_fuMine && (_fuCls === 'due' || _fuCls === 'ok')) {{
          _fuLab = 'Last chased ' + _fuWhen(_fuSt.since || (_fuList[0] && _fuList[0].on));
          _fuCls = 'ok';
        }}
        _fuBody += '<div class="fu-state fu-' + _fuCls +
                   (_fuSt.rejected ? ' fu-rejected' : '') + '">' + esc(_fuLab) + '</div>';
      }}
      // A chase logged on a sibling event counts for this one, but it used to
      // show as a bare green label with nothing under it. Give it the same
      // dated row as any other, saying where it came from (Hurley 2026-07-30).
      if (!_fuList.length && _fuSt && _fuSt.via) {{
        _fuBody += '<ol class="fu-log fu-log--' + _fuSt.state + '"><li class="fu-inherited">' +
          '<span class="fu-when">' + esc(_fuWhen(_fuSt.via.on)) + '</span>' +
          '<span class="fu-kind">Followed up</span>' +
          '<span class="fu-note">via ' + esc(_fuSt.via.name || 'another event by this organiser') + '</span>' +
          '</li></ol>';
      }}
      if (_fuList.length) {{
        // Oldest entry is the FIRST contact; everything after it is a chase.
        // Naming them that way is the whole point â€” Angela wants to see when
        // she reached out and when she followed up (Hurley 2026-07-30).
        var _fuOldest = _fuList.length - 1;
        // Read top-to-bottom as it happened: first contact at the top, latest
        // chase at the bottom (Hurley 2026-07-30).
        var _fuRows = _fuList.map(function (f, i) {{ return {{ f: f, i: i }}; }}).reverse();
        _fuBody += '<ol class="fu-log fu-log--' + ((_fuSt && _fuSt.state) || 'none') + '">' +
          _fuRows.map(function (row) {{
          var f = row.f, i = row.i;
          var kind = (i === _fuOldest) ? 'Reached out' : 'Followed up';
          return '<li data-fu-i="' + i + '">' +
                 '<span class="fu-when">' + esc(_fuWhen(f.on)) + '</span>' +
                 '<span class="fu-kind">' + kind + '</span>' +
                 (f.by ? '<span class="fu-by">' + esc(f.by) + '</span>' : '') +
                 (_fuMine ? '<span class="fu-acts">' +
                   '<button type="button" class="fu-act" data-fu-edit="' + i + '" title="Edit this entry" aria-label="Edit this entry">' + MD_PENCIL + '</button>' +
                   '<button type="button" class="fu-act fu-act-del" data-fu-del="' + i + '" title="Delete this entry" aria-label="Delete this entry">' + MD_TRASH + '</button>' +
                 '</span>' : '') +
                 (f.note ? '<span class="fu-note">' + esc(f.note) + '</span>' : '') +
                 (f.edited ? '<span class="fu-edited">edited ' + esc(_fuWhen(f.edited)) + '</span>' : '') +
                 '</li>';
        }}).join('') + '</ol>';
      }}
      // No empty-state copy: an empty log is self-evident, and explaining the
      // columns of a list that isn't there is noise (Hurley 2026-07-30).
      // Today's date rides on the button, so the automatic stamp is visible
      // BEFORE you commit to it rather than being a surprise afterwards.
      var _fuToday = window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10);
      if (_fuMine) _fuBody += '<button type="button" class="ab-addbtn" id="fu-add-btn">' +
                 '<span class="ab-addbtn-ic" aria-hidden="true">+</span> Log a follow-up</button>' +
                 '<div class="ab-form" id="fu-add-form" hidden>' +
                   // Chases get written up after the fact, so the date has to be
                   // editable â€” you followed up on the 24th and log it on the
                   // 30th (Hurley 2026-07-30). Defaults to today; capped at
                   // today, because a follow-up you haven't made isn't one.
                   '<div class="fu-when-row">' +
                     '<label class="fu-when-lab" for="fu-add-on">When</label>' +
                     '<input type="date" class="ab-input ab-input-date" id="fu-add-on" ' +
                       'value="' + esc(_fuToday) + '" max="' + esc(_fuToday) + '">' +
                   '</div>' +
                   '<textarea class="ab-input" id="fu-add-note" rows="2" ' +
                     'placeholder="What you sent, or what came back (optional)"></textarea>' +
                   '<div class="ab-form-actions">' +
                     '<button type="button" class="ab-btn-primary" id="fu-add-save">Log for ' +
                       esc(_fuWhen(_fuToday)) + '</button>' +
                     '<button type="button" class="ab-btn-ghost" id="fu-add-cancel">Cancel</button>' +
                   '</div>' +
                 '</div>';
      v += sec('Follow-ups', _fuBody);
    }}
    // "ArcticBlue speaker: Thor" read as settled fact on events where all we'd
    // done was put him forward (Hurley 2026-07-30). The line now says where we
    // actually stand: plain when he's booked, parenthesised while it's only a
    // submission, and "Attending" when he's going but not speaking.
    function speakerLine() {{
      var who = String(rec.speaker || '').trim();
      if (!who) return field('ArcticBlue speaker', rec.speaker);
      var _sst = rec.stage_tags || [];
      function _sHas(x) {{ return _sst.indexOf(x) !== -1; }}
      if (_sHas('Booked')) return field('ArcticBlue speaker', who);
      if (_sHas('Rejected')) return field('ArcticBlue speaker', who + ' (rejected)');
      // Followed up presupposes a submission, so both read the same.
      if (_sHas('Submitted') || _sHas('Followed up')) return field('ArcticBlue speaker', who + ' (submitted)');
      if (_sHas('Attending')) return field('Attending', who);
      return field('ArcticBlue speaker', who);
    }}
    if (rec.is_private) {{
      // Private / invite-only: just the speaker + POC (link is the title, chat above).
      v += sec('Speaking', speakerLine());
      v += sec('Contacts', pocHtml);
    }} else {{
      // â€” Speaking & submission: how we'd get on stage, and where we stand.
      //   The legacy status marker (e.g. "Sponsorship Only") is kept OFF the card
      //   face by design but belongs here so a saved marker is visible.
      var _spkStatus = speakerLine() +
        field('Status marker', (function () {{
          var ws = rec.workflow_status;
          if (!ws || ws === '__deleted__') return '';
          // Rejected is terminal â€” a leftover legacy "Pending" marker would
          // contradict it, so it's suppressed (Hurley 2026-07-29).
          if (/^\\s*pending\\s*$/i.test(ws) && (rec.stage_tags || []).indexOf('Rejected') !== -1) return '';
          return ws;
        }})()) +
        // A 94-character raw URL is not a "route" anyone reads â€” it's a wall of
        // slug. Show what it IS and make the words the link (Hurley 2026-07-30).
        field('Speaking Notes', (function () {{
          var r = String(rec.speaking_route || '').trim();
          if (!r || _modalJunk(r)) return '';
          var m = r.match(/https?:\/\/\S+/);
          if (!m) return '';
          var lead = r.slice(0, m.index).replace(/[\s:\u2014-]+$/, '').trim();
          var rest = r.slice(m.index + m[0].length).replace(/^[\s:;,\u2014-]+/, '').trim();
          var label = lead || 'Apply to speak';
          return '<a href="' + esc(m[0]) + '" target="_blank" rel="noopener">' +
                 esc(label) + ' \u2197</a>' +
                 (rest ? ' <span class="modal-note">' + esc(rest) + '</span>' : '');
        }})(), true) +
        field('Deadline', (window.opsDeadlineUsable && window.opsDeadlineUsable(rec.deadline, rec)) ? rec.deadline : '') +
        field('Submission status', rec.submission_status);
      // Pay-to-play and the fee are footnotes to a status, not a status. On
      // their own they aren't worth a heading â€” and the stage buttons at the
      // top of the card already say where we stand (Hurley 2026-07-30).
      if (_spkStatus) {{
        _spkStatus += field('Pay-to-play', rec.pay_to_play) +
                      field('Speaking fee', rec.speaking_fee);
      }}
      // The runners-up from the same Apollo lookup. Stored as JSON so they can
    // be listed and promoted; older hand-typed values are plain text and still
    // render as-is (Hurley 2026-07-31).
    function _altContactsHtml(rec) {{
      var raw = String(rec.additional_contacts || '').trim();
      if (!raw) return '';
      var list = null;
      if (raw.charAt(0) === '[') {{ try {{ list = JSON.parse(raw); }} catch (e) {{ list = null; }} }}
      if (!Array.isArray(list) || !list.length) {{
        return '<div class="modal-field"><div class="k">Additional contacts</div>' +
               '<div class="v">' + esc(raw) + '</div></div>';
      }}
      var rows = list.map(function (c, i) {{
        var who = String(c.name || '').trim();
        var ttl = String(c.title || '').trim();
        var em  = String(c.email || '').trim();
        return '<div class="poc-alt">' +
          '<div class="poc-alt-main"><span class="poc-alt-name">' + esc(who) + '</span>' +
            (ttl ? '<span class="poc-alt-title">' + esc(ttl) + '</span>' : '') +
            (em ? '<span class="poc-alt-mail">' + esc(em) + '</span>' : '') + '</div>' +
          '<button type="button" class="q-btn poc-alt-use" data-poc-use="' + i + '" ' +
            'title="Make this the point of contact for the outreach draft">Use</button>' +
        '</div>';
      }}).join('');
      return '<div class="modal-field"><div class="k">Others we found</div>' +
             '<div class="poc-alts">' + rows + '</div></div>';
    }}
    // Speaking & submission is Angela's working record of the application â€”
      // the marker, the route, the deadline, pay-to-play. Where a speaker
      // stands is already the bold status line on the card face and the pills
      // at the top of this modal, and the apply link is its own button, so for
      // everyone else this section only restated it (Hurley 2026-07-30).
      // Contacts fold in here rather than standing alone: who to approach is
      // part of HOW we get on stage, and on most events it was one line under
      // its own heading (Hurley 2026-07-30).
      var _contactsHtml = pocHtml + _altContactsHtml(rec) +
        '<button type="button" class="q-btn poc-more" data-poc-more="1">' +
          (String(rec.poc_name || '').trim() ? '&#128269; Find more people' : '&#128269; Find someone to contact') +
        '</button>';
      var _spkSec = (window.isAngelaUser && window.isAngelaUser())
        ? sec('Speaking & submission', _spkStatus + _contactsHtml) : '';
      // â€” Who's in the room: every audience fact in one place.
      // One merged list â€” the heading already says who it's about, so the value
      // goes in bare rather than under a second "Typical attendees" label.
      var _whoSec = sec('Who attends',
        fieldBare(mergeAttendees(rec.typical_attendees, rec.past_speakers)) +
        (function () {{
          // "Audience: Buyer-rich" is a targeting judgement, not a fact about
          // the event â€” it's Verma's signal (regulated-industry board rooms) and
          // Angela's for triage. Everyone else was reading a label that didn't
          // change what they'd do (Hurley 2026-07-29).
          var g = field('Attendee count', rec.attendee_count) +
                  (seesAudience() ? field('Audience', rec.audience_type) : '');
          return g ? '<div class="modal-grid">' + g + '</div>' : '';
        }})());
      // â€” Overview of the event itself. The meeting/networking format rides
      //   along here as one clause instead of claiming its own labelled row.
      // Same organiser, other events. On an umbrella this is the list it
      // covers; on a member it's the family it belongs to (Hurley 2026-07-30).
      // Angela-only: pull an event we already track into this organiser's family,
      // or add one we don't have yet. The domain rule catches most families on
      // its own; this is for the ones it can't see â€” an organiser running several
      // brands, or an event whose page sits on a venue domain (Hurley 2026-07-31).
      function _sibAdd() {{
        if (!(window.isAngelaUser && window.isAngelaUser())) return '';
        return '<div class="sib-add">' +
          '<div class="sib-addwrap">' +
            '<button type="button" class="ab-addbtn" id="sib-add-btn" aria-haspopup="menu" aria-expanded="false">' +
              '<span class="ab-addbtn-ic" aria-hidden="true">+</span> Add event' +
              '<span class="sib-caret" aria-hidden="true">&#9662;</span></button>' +
            '<div class="sib-menu" id="sib-menu" role="menu" hidden>' +
              '<button type="button" class="sib-menu-item" id="sib-link-btn" role="menuitem">' +
                'Add an event we <strong>already</strong> track</button>' +
              '<button type="button" class="sib-menu-item" id="sib-new-btn" role="menuitem">' +
                'Add an event <strong>not</strong> in the tracker</button>' +
            '</div>' +
          '</div>' +
          // search-and-link
          '<div class="ab-form" id="sib-link-form" hidden>' +
            '<input type="text" class="ab-input" id="sib-search" autocomplete="off" ' +
              'placeholder="Search events by name\u2026">' +
            '<div class="sib-results" id="sib-results"></div>' +
            '<div class="ab-form-actions">' +
              '<button type="button" class="ab-btn-ghost" id="sib-link-cancel">Cancel</button>' +
            '</div>' +
          '</div>' +
          // create a brand-new event, pre-linked to this organiser
          '<div class="ab-form" id="sib-new-form" hidden>' +
            '<input type="text" class="ab-input" id="sib-new-name" placeholder="Event name (required)">' +
            '<input type="text" class="ab-input" id="sib-new-when" placeholder="Dates \u2014 e.g. March 3\u20135, 2027">' +
            '<input type="text" class="ab-input" id="sib-new-where" placeholder="Location">' +
            '<input type="url"  class="ab-input" id="sib-new-url" placeholder="Link (optional)">' +
            '<div class="ab-form-actions">' +
              '<button type="button" class="ab-btn-primary" id="sib-new-save">Add to this organiser</button>' +
              '<button type="button" class="ab-btn-ghost" id="sib-new-cancel">Cancel</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      }}
      var _sibSec = (function () {{
        var sibs = window.abSiblingEvents ? window.abSiblingEvents(rec) : [];
        // Angela sees the section even with no siblings â€” otherwise there is
        // nowhere to start a group from (Hurley 2026-07-31).
        var _sibMine = !!(window.isAngelaUser && window.isAngelaUser());
        if (!sibs.length && !_sibMine) return '';
        if (!sibs.length) return sec('Also from this organiser',
          '<p class="sib-more">Nothing else from this organiser yet.</p>' + _sibAdd());
        var live = sibs.filter(function (x) {{ return !x.past; }});
        var use = live.length ? live : sibs;
        // No cap: the point of this section is that the organiser's events are
        // all in ONE place, so quietly hiding the 13th defeats it. Long lists
        // scroll instead (Hurley 2026-07-31).
        var _sibMine2 = !!(window.isAngelaUser && window.isAngelaUser());
        var rowsH = use.map(function (x) {{
          return '<div class="sib-line">' +
                 '<button type="button" class="sib-row" data-sib-kind="' + esc(x.kind) +
                 '" data-sib-key="' + esc(String(x.key)) + '">' +
                 '<span class="sib-name">' + esc(x.name) + '</span>' +
                 (x.date ? '<span class="sib-when">' + esc(x.date) + '</span>' : '') +
                 '</button>' +
                 // Only hand-linked rows can be unlinked â€” a shared domain is a
                 // fact about the events, not a choice Angela made.
                 ((_sibMine2 && x.manual)
                   ? '<button type="button" class="sib-unlink" data-unlink-kind="' + esc(x.kind) +
                     '" data-unlink-key="' + esc(String(x.key)) +
                     '" title="Remove from this organiser" aria-label="Remove from this organiser">&times;</button>'
                   : '') +
                 '</div>';
        }}).join('');
        var more = '';
        return sec('Also from this organiser', '<div class="sib-list">' + rowsH + more + '</div>' + _sibAdd());
      }})();
      var _ovSec = sec('Overview',
        (function () {{
          var about = String(rec.about || '').trim();
          var fmt = briefClause(rec.meeting_formats);
          // Don't say it twice â€” enrichment sometimes works the format into the
          // overview prose as well, and repeating it is the padding we're
          // trying to get rid of.
          if (fmt && about) {{
            var aLow = about.toLowerCase();
            var fw = fmt.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/)
              .filter(function (w) {{ return w.length > 4; }});
            if (fw.length && fw.every(function (w) {{ return aLow.indexOf(w) !== -1; }})) fmt = '';
          }}
          if (fmt) about = about ? (about.replace(/[.\\s]+$/, '') + '. ' + fmt + '.') : (fmt + '.');
          return fieldBare(about);
        }})() +
        field('Topics', rec.focus_areas) +
        (function () {{
          var g = field('Price to attend', rec.pricing) + field('Venue', rec.venue);
          return g ? '<div class="modal-grid">' + g + '</div>' : '';
        }})());
      // Order (Hurley 2026-07-30): what we've said and where we stand first,
      // then what the event IS, who's in the room, the submission detail and
      // the contacts. The organiser's other events go LAST â€” it's a way OUT of
      // this card, so it belongs at the bottom, not mid-read.
      v += _spkSec + _ovSec + _whoSec;
      // This zone only ever holds the one field, so under the one-field rule the
      // heading IS the label â€” which means it has to be the informative one.
      v += sec('Post-mortem (ROI)', field('Post-mortem (ROI)', rec.postmortem));
      // Applying is the action this card exists for, so it sits at the end of
      // the read â€” but ABOVE the way out to the organiser's other events.
      var _apUrl = rec.apply_url || speakingRouteUrl(rec.speaking_route);
      if (_apUrl && window.isAngelaUser && window.isAngelaUser()) {{
        v += '<div class="me-apply"><a class="modal-visit modal-apply" href="' + esc(_apUrl) +
             '" target="_blank" rel="noopener">Apply to speak \u2197</a></div>';
      }}
      v += _sibSec;
    }}

    // "Updated Nd ago" now lives here (italic, at the bottom of the detail),
    // not on the card face (Hurley 2026-07-13).
    var _mFresh = (window.opsFreshText ? window.opsFreshText(rec.updated_at) : '');
    if (_mFresh) v += '<p class="modal-fresh">' + esc(_mFresh) + '</p>';
    html += '<div class="modal-view">' + (v || '<p class="modal-nolink">No extra detail on file for this event yet.</p>') + '</div>';
    var editForm = editFormHtml(rec);
    if (editForm) html += '<div class="modal-editform" hidden>' + editForm + '</div>';

    $body.innerHTML = html;
    wireQuickBar(rec);
    // Clicking a sibling opens THAT event's card.
    $body.querySelectorAll('[data-sib-kind]').forEach(function (b3) {{
      b3.addEventListener('click', function () {{
        if (window.abOpenRef) window.abOpenRef(b3.getAttribute('data-sib-kind'), b3.getAttribute('data-sib-key'));
      }});
    }});
    wireEditForm(rec);
    wireSiblingAdd(rec);
    wirePocActions(rec);
    if (window.opsRenderChat) window.opsRenderChat(rec);

    // â”€â”€ Organiser grouping (Angela) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    // Two ways in: link an event we already track, or add one we don't have.
    // Both write the same org_group key on BOTH sides, so the link is explicit
    // on each event and survives either being edited (Hurley 2026-07-31).
    // ONE listener for the life of the page, reading the event from _pocRec.
    // It used to re-bind whenever the key changed â€” but #modal-body is never
    // replaced, so every event you opened left its own listener behind, each
    // holding its own record. Clicking "Find someone to contact" then ran all
    // of them (stopPropagation doesn't stop siblings on the same node): the
    // oldest one looked up ITS event and re-opened ITS pop-up, so you landed
    // back on the event you'd viewed before and burned an Apollo credit on it.
    // Keying by _key alone was wrong twice over â€” catalog and manual numbering
    // overlap, so a collision skipped the wiring and left the button dead
    // (Hurley 2026-08-07).
    function wirePocActions(rec) {{
      _pocRec = rec;
      var host = $body;
      if (!host || host.dataset.pocWired === '1') return;
      host.dataset.pocWired = '1';
      host.addEventListener('click', function (e) {{
        var rec = _pocRec;                       // whatever is on screen NOW
        if (!rec) return;
        var use = e.target.closest ? e.target.closest('[data-poc-use]') : null;
        if (use) {{
          e.stopPropagation();
          var list = [];
          try {{ list = JSON.parse(rec.additional_contacts || '[]'); }} catch (x) {{ return; }}
          var pick = list[parseInt(use.getAttribute('data-poc-use'), 10)];
          if (!pick) return;
          // Promote them, and demote whoever was primary into the list so the
          // swap is reversible â€” nothing is thrown away.
          var demoted = {{ name: rec.poc_name || '', title: String(rec.poc_note || '').replace(/ \(found via Apollo\)$/, ''),
                          email: rec.poc_email || '', linkedin: rec.poc_linkedin || '' }};
          var rest = list.filter(function (c) {{ return c !== pick; }});
          if (demoted.name || demoted.email) rest.unshift(demoted);
          rec.poc_name = pick.name || '';
          rec.poc_email = pick.email || '';
          rec.poc_linkedin = pick.linkedin || '';
          rec.poc_note = pick.title ? pick.title + ' (found via Apollo)' : '';
          rec.additional_contacts = JSON.stringify(rest);
          if (window.opsWrite) window.opsWrite(rec._table, rec._key, {{
            poc_name: rec.poc_name, poc_email: rec.poc_email,
            poc_linkedin: rec.poc_linkedin, poc_note: rec.poc_note,
            additional_contacts: rec.additional_contacts
          }});
          openEventModal(rec);
          return;
        }}
        var more = e.target.closest ? e.target.closest('[data-poc-more]') : null;
        if (more) {{
          e.stopPropagation();
          if (more.getAttribute('aria-busy')) return;
          more.setAttribute('aria-busy', '1');
          more.textContent = 'Looking\u2026';
          // Only re-draw if this is still the event on screen. The lookup takes
          // seconds; if they've moved on, the contact is already saved and
          // opsRefresh has run â€” dragging them back would be the same rudeness.
          window.abFindContact(rec, function () {{
            if (_pocRec === rec) openEventModal(rec);
          }}, {{ force: true, want: 4 }});
          // No callback fires when nothing new turns up, so say so either way.
          setTimeout(function () {{
            if (!more.isConnected) return;
            more.removeAttribute('aria-busy');
            more.textContent = 'No one new found \u2014 try again';
          }}, 9000);
        }}
      }});
    }}
    function wireSiblingAdd(rec) {{
      var linkBtn = $body.querySelector('#sib-link-btn');
      var newBtn  = $body.querySelector('#sib-new-btn');
      if (!linkBtn && !newBtn) return;
      var linkForm = $body.querySelector('#sib-link-form');
      var newForm  = $body.querySelector('#sib-new-form');
      var addWrap  = $body.querySelector('.sib-addwrap');
      var addBtn   = $body.querySelector('#sib-add-btn');
      var addMenu  = $body.querySelector('#sib-menu');
      function closeMenu() {{
        if (addMenu) addMenu.hidden = true;
        if (addBtn) addBtn.setAttribute('aria-expanded', 'false');
      }}
      if (addBtn) addBtn.addEventListener('click', function (e) {{
        e.stopPropagation();
        var open = addMenu.hidden;
        addMenu.hidden = !open;
        addBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      }});
      if (_sibCloser) document.removeEventListener('click', _sibCloser);
      _sibCloser = closeMenu;
      document.addEventListener('click', closeMenu);
      function show(form) {{
        closeMenu();
        [linkForm, newForm].forEach(function (f) {{ if (f) f.hidden = (f !== form); }});
        if (addWrap) addWrap.hidden = !!form;
      }}
      function reset() {{ show(null); }}
      if (linkBtn) linkBtn.addEventListener('click', function () {{
        show(linkForm);
        var q = $body.querySelector('#sib-search');
        if (q) {{ q.value = ''; renderHits(''); q.focus(); }}
      }});
      if (newBtn) newBtn.addEventListener('click', function () {{ show(newForm); 
        var n = $body.querySelector('#sib-new-name'); if (n) n.focus(); }});
      var lc = $body.querySelector('#sib-link-cancel'); if (lc) lc.addEventListener('click', reset);
      var nc = $body.querySelector('#sib-new-cancel');  if (nc) nc.addEventListener('click', reset);

      // The group key this event anchors. Written to both sides on link.
      function groupKey() {{ return window.abOrgKey ? window.abOrgKey(rec) : ''; }}

      function afterChange() {{
        var sc = overlay.querySelector('.modal-scroll');
        var top = sc ? sc.scrollTop : 0;
        openEventModal(rec);
        var sc2 = overlay.querySelector('.modal-scroll');
        if (sc2) sc2.scrollTop = top;
        if (window.opsRefresh) window.opsRefresh();
      }}

      // â”€â”€ search over what we already track
      var results = $body.querySelector('#sib-results');
      function renderHits(term) {{
        if (!results) return;
        term = String(term || '').trim().toLowerCase();
        if (term.length < 2) {{
          results.innerHTML = '<p class="sib-hit-none">Type at least two letters.</p>';
          return;
        }}
        var already = {{}};
        (window.abSiblingEvents ? window.abSiblingEvents(rec) : []).forEach(function (x) {{
          already[x.kind + ':' + x.key] = 1;
        }});
        already[(rec._table === 'manual_events' ? 'manual' : 'catalog') + ':' + rec._key] = 1;  // not myself
        var hits = window.abSearchEvents ? window.abSearchEvents(term, already, 25) : [];
        if (!hits.length) {{ results.innerHTML = '<p class="sib-hit-none">No match.</p>'; return; }}
        results.innerHTML = hits.map(function (it) {{
          return '<button type="button" class="sib-hit" data-hit-kind="' + esc(it.kind) +
                 '" data-hit-key="' + esc(String(it.key)) + '">' +
                 '<span class="sib-hit-name">' + esc(it.name) + '</span>' +
                 '<span class="sib-hit-meta">' + esc(it.date) + '</span></button>';
        }}).join('');
        Array.prototype.forEach.call(results.querySelectorAll('.sib-hit'), function (b) {{
          b.addEventListener('click', function () {{ linkExisting(b.dataset.hitKind, b.dataset.hitKey); }});
        }});
      }}
      var sq = $body.querySelector('#sib-search');
      if (sq) sq.addEventListener('input', function () {{ renderHits(sq.value); }});

      // Unlink â€” clear the group on the row that was linked by hand. The
      // anchor keeps its own group so the rest of the family is untouched.
      Array.prototype.forEach.call($body.querySelectorAll('.sib-unlink'), function (b) {{
        b.addEventListener('click', function (e) {{
          e.stopPropagation();                      // don't open the event
          if (!window.opsWrite) return;
          var kind = b.dataset.unlinkKind, key = b.dataset.unlinkKey;
          var tbl = (kind === 'manual') ? 'manual_events' : 'event_state';
          window.opsWrite(tbl, (kind === 'manual') ? key : parseInt(key, 10), {{ org_group: null }});
          afterChange();
        }});
      }});

      function linkExisting(kind, key) {{
        var g = groupKey();
        if (!g || !window.opsWrite) return;
        var tbl = (kind === 'manual') ? 'manual_events' : 'event_state';
        window.opsWrite(tbl, (kind === 'manual') ? key : parseInt(key, 10), {{ org_group: g }});
        // Stamp this event too, so the group is explicit on both sides even when
        // it was only ever implied by the domain.
        if (String(rec.org_group || '') !== g) {{
          rec.org_group = g;
          window.opsWrite(rec._table, rec._key, {{ org_group: g }});
        }}
        reset(); afterChange();
      }}

      // â”€â”€ add an event we don't track yet, pre-linked
      var save = $body.querySelector('#sib-new-save');
      if (save) save.addEventListener('click', function () {{
        var name = ($body.querySelector('#sib-new-name') || {{}}).value || '';
        name = String(name).trim();
        if (!name) {{ var n0 = $body.querySelector('#sib-new-name'); if (n0) n0.focus(); return; }}
        var g = groupKey();
        var row = {{
          name: name,
          date_str: String((($body.querySelector('#sib-new-when') || {{}}).value || '')).trim() || null,
          location: String((($body.querySelector('#sib-new-where') || {{}}).value || '')).trim() || null,
          url: String((($body.querySelector('#sib-new-url') || {{}}).value || '')).trim() || null,
          org_group: g || null,
          created_by: (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || 'tracker',
          external_id: 'manual'
        }};
        save.disabled = true; save.textContent = 'Adding\u2026';
        if (window.opsCreateManual) {{
          window.opsCreateManual(row).then(function () {{
            if (String(rec.org_group || '') !== g && g) {{
              rec.org_group = g;
              window.opsWrite(rec._table, rec._key, {{ org_group: g }});
            }}
            reset(); afterChange();
          }}, function () {{ save.disabled = false; save.textContent = 'Add to this organiser'; }});
        }}
      }});
    }}

    // Edit / delete a single entry. Editing keeps the ORIGINAL date â€” that's
    // when the contact actually happened â€” and stamps an `edited` date beside
    // it, so the history stays honest rather than silently rewriting itself
    // (Hurley 2026-07-30).
    function _fuSave(list) {{
      rec.follow_ups = list;
      if (window.opsWrite) window.opsWrite(rec._table, rec._key, {{ follow_ups: list }});
      var sc = overlay.querySelector('.modal-scroll');
      var top = sc ? sc.scrollTop : 0;
      openEventModal(rec);
      if (sc) sc.scrollTop = top;
      if (window.opsRefresh) window.opsRefresh();
    }}
    // Both edit and delete happen INSIDE the row. Nothing floats to the top of
    // the window, and the entry you're acting on stays visible while you act.
    function _fuRowForm(li, html) {{
      if (li.querySelector('.ab-form')) return null;          // already open
      li.querySelectorAll('.fu-acts, .fu-note').forEach(function (n) {{ n.hidden = true; }});
      var wrap = document.createElement('div');
      wrap.className = 'ab-form fu-rowform';
      wrap.innerHTML = html;
      li.appendChild(wrap);
      return wrap;
    }}
    function _fuRowClose(li) {{
      var w = li.querySelector('.ab-form'); if (w) w.remove();
      li.querySelectorAll('.fu-acts, .fu-note').forEach(function (n) {{ n.hidden = false; }});
    }}
    $body.querySelectorAll('[data-fu-edit]').forEach(function (b2) {{
      b2.addEventListener('click', function () {{
        var i = parseInt(b2.getAttribute('data-fu-edit'), 10);
        var cur = (window.abFollowUps ? window.abFollowUps(rec) : [])[i];
        var li = b2.parentNode && b2.parentNode.parentNode;
        if (!cur || !li) return;
        var _today = window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10);
        var w = _fuRowForm(li,
          '<div class="fu-when-row">' +
            '<label class="fu-when-lab">When</label>' +
            '<input type="date" class="ab-input ab-input-date" data-on ' +
              'value="' + esc(String(cur.on || '').slice(0, 10)) + '" max="' + esc(_today) + '">' +
          '</div>' +
          '<textarea class="ab-input" rows="2" placeholder="What you sent, or what came back"></textarea>' +
          '<div class="ab-form-actions">' +
            '<button type="button" class="ab-btn-primary" data-go>Save</button>' +
            '<button type="button" class="ab-btn-ghost" data-cancel>Cancel</button>' +
          '</div>');
        if (!w) return;
        var ta = w.querySelector('textarea');
        ta.value = cur.note || '';
        ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
        function commit() {{
          var list = (window.abFollowUps ? window.abFollowUps(rec) : []).slice();
          if (!list[i]) return;
          var today = window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10);
          // The date is WHEN IT HAPPENED â€” it stays put unless she corrects it,
          // and the edit is stamped separately so the history can't quietly
          // rewrite itself.
          var onEl = w.querySelector('[data-on]');
          var onVal = (onEl && /^\d{{4}}-\d{{2}}-\d{{2}}$/.test(onEl.value)) ? onEl.value : list[i].on;
          if (onVal > today) onVal = today;
          list[i] = {{ on: onVal, by: list[i].by, note: ta.value.trim(), edited: today }};
          _fuSave(list);
        }}
        w.querySelector('[data-go]').addEventListener('click', commit);
        w.querySelector('[data-cancel]').addEventListener('click', function () {{ _fuRowClose(li); }});
        ta.addEventListener('keydown', function (e) {{
          if (e.key === 'Escape') {{ e.preventDefault(); _fuRowClose(li); }}
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {{ e.preventDefault(); commit(); }}
        }});
      }});
    }});
    $body.querySelectorAll('[data-fu-del]').forEach(function (b2) {{
      b2.addEventListener('click', function () {{
        var i = parseInt(b2.getAttribute('data-fu-del'), 10);
        var cur = (window.abFollowUps ? window.abFollowUps(rec) : [])[i];
        var li = b2.parentNode && b2.parentNode.parentNode;
        if (!cur || !li) return;
        var w = _fuRowForm(li,
          '<div class="ab-form-actions" style="margin-top:0;">' +
            '<span class="fu-note" style="flex:0 1 auto;">Delete the entry from ' +
              esc(_fuWhen(cur.on)) + '?</span>' +
            '<button type="button" class="ab-btn-primary ab-btn-danger" data-go>Delete</button>' +
            '<button type="button" class="ab-btn-outline" data-cancel>Keep</button>' +
          '</div>');
        if (!w) return;
        w.querySelector('[data-go]').addEventListener('click', function () {{
          var list = (window.abFollowUps ? window.abFollowUps(rec) : []).slice();
          if (!list[i]) return;
          list.splice(i, 1);
          _fuSave(list);
        }});
        w.querySelector('[data-cancel]').addEventListener('click', function () {{ _fuRowClose(li); }});
      }});
    }});

    // "+ Log a follow-up" â€” records today's date against the signed-in name,
    // with an optional line on what came back. Appends; never replaces.
    var _fuBtn = document.getElementById('fu-add-btn');
    var _fuForm = document.getElementById('fu-add-form');
    if (_fuBtn && _fuForm) {{
      var _fuTa = document.getElementById('fu-add-note');
      var _fuOn = document.getElementById('fu-add-on');
      function _fuAddClose() {{
        _fuForm.hidden = true; _fuBtn.hidden = false;
        if (_fuTa) _fuTa.value = '';
        if (_fuOn) _fuOn.value = _fuToday;
        var g0 = document.getElementById('fu-add-save');
        if (g0) g0.textContent = 'Log for ' + _fuWhen(_fuToday);
      }}
      // The button always names the date it will actually write.
      if (_fuOn) _fuOn.addEventListener('change', function () {{
        var g1 = document.getElementById('fu-add-save');
        var v = _fuOn.value || _fuToday;
        if (v > _fuToday) {{ v = _fuToday; _fuOn.value = v; }}
        if (g1) g1.textContent = 'Log for ' + _fuWhen(v);
      }});
      _fuBtn.addEventListener('click', function () {{
        _fuForm.hidden = false; _fuBtn.hidden = true;
        if (_fuTa) _fuTa.focus();
      }});
      var _fuCancel = document.getElementById('fu-add-cancel');
      if (_fuCancel) _fuCancel.addEventListener('click', _fuAddClose);
      function _fuAddSave() {{
        // The date is never typed â€” it's today's, in New York, taken at the
        // moment of logging and written straight through to Supabase.
        var today = window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10);
        // Whatever day it happened on â€” never later than today.
        var on = (_fuOn && /^\d{{4}}-\d{{2}}-\d{{2}}$/.test(_fuOn.value)) ? _fuOn.value : today;
        if (on > today) on = today;
        var list = (window.abFollowUps ? window.abFollowUps(rec) : []).slice();
        list.unshift({{ on: on, by: (window.opsCurrentUser ? window.opsCurrentUser() : '') || 'Angela',
                       note: _fuTa ? _fuTa.value.trim() : '' }});
        _fuSave(list);            // the list re-sorts by date, so it lands in order
      }}
      var _fuGo = document.getElementById('fu-add-save');
      if (_fuGo) _fuGo.addEventListener('click', _fuAddSave);
      if (_fuTa) _fuTa.addEventListener('keydown', function (e) {{
        if (e.key === 'Escape') {{ e.preventDefault(); _fuAddClose(); }}
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {{ e.preventDefault(); _fuAddSave(); }}
      }});
    }}

    // "Edit event" toggle â€” header top-right, same spot for every event. It
    // swaps the read-only view for the (identically-laid-out) edit form.
    // Trash-can DELETE â€” top LEFT of the toolbar, and only while the editor is
    // open (Hurley 2026-07-29). It drives the SAME delete path as the "Delete
    // this event" button at the foot of the form (confirm dialog, catalog
    // soft-delete vs manual hard-delete, backlog record), so there is one
    // implementation reachable two ways.
    var $left = document.getElementById('modal-head-left');
    if ($left) {{
      $left.innerHTML = editForm
        ? '<button type="button" class="qa-del" id="modal-delete-btn" hidden title="Delete this event">' + MD_TRASH + '<span>Delete</span></button>'
        : '';
      var dbtn = document.getElementById('modal-delete-btn');
      if (dbtn) dbtn.addEventListener('click', function () {{
        var formDel = $body.querySelector('.modal-editform .me-delete');
        if (formDel) formDel.click();
      }});
    }}

    var $side = document.getElementById('modal-head-side');
    if ($side) {{
      // "Enrich" â€” research missing details on demand (editable records only).
      var enrichBtn = (rec._table && rec._key != null)
        ? '<button type="button" class="qa-edit qa-enrich" id="modal-enrich-btn" title="Search the web to fill in missing details for this event"><span class="qa-edit-ic" aria-hidden="true">âœ¦</span> Enrich</button>'
        : '';
      // Interested + Archive as ICONS, same star and struck-eye the card face
      // uses, so the two surfaces speak the same language (Hurley 2026-07-30).
      var _hIn   = !!window.__mqIn, _hArch = !!window.__mqArch;
      var _starD = 'M12 2.6l2.72 5.51 6.08.88-4.4 4.29 1.04 6.06L12 16.48 6.56 19.34l1.04-6.06-4.4-4.29 6.08-.88z';
      var meIco =
        '<button type="button" class="mh-ico' + (_hIn ? ' is-on' : '') + '" data-qa="interested" ' +
        'title="' + (_hIn ? "You're interested â€” click to clear" : "I'm interested") + '" ' +
        'aria-pressed="' + (_hIn ? 'true' : 'false') + '" aria-label="I am interested">' +
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="' + (_hIn ? 'currentColor' : 'none') +
        '" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="' + _starD + '"/></svg>' +
        '</button>';
      // âš  DEAD CODE â€” meIco/archIco are BUILT HERE AND NEVER INSERTED. $side's
      // innerHTML below is only enrichBtn + the Edit button, so these two never
      // reach the page; the icons you actually see are the .mt-ico pair in the
      // modal TITLE (search 'mt-acts'). Verified in the browser: 0 .mh-ico
      // nodes, 2 .mt-ico. Left in place rather than deleted because the header
      // may want them back, but DO NOT edit these expecting a visible change â€”
      // I did, twice (Hurley 2026-08-05).
      var _teamHidden = (rec.hidden === true);
      var archIco =
        '<button type="button" class="mh-ico' + (_hArch ? ' is-on' : '') + '" data-qa="archive" ' +
        'title="' + (_teamHidden
            ? 'Archived for the team â€” click to bring it back for everyone'
            : (_hArch ? 'Archived for the team â€” click to bring it back' : 'Archive â€” hides this event for the whole team')) + '" ' +
        'aria-pressed="' + (_hArch ? 'true' : 'false') + '" aria-label="Archive for me">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>' +
        '<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/>' +
        '<path d="M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>' +
        '<path d="m2 2 20 20"/></svg></button>';
      $side.innerHTML = enrichBtn + (editForm
        ? '<button type="button" class="qa-edit" id="modal-edit-toggle" aria-expanded="false"><span class="qa-edit-ic" aria-hidden="true">âœŽ</span> Edit</button>'
        : '');
      // They drive the SAME handler the quickbar buttons did.
      $side.querySelectorAll('[data-qa]').forEach(function (b4) {{
        // Same deferred lookup as the title icons â€” see the note there.
        b4.addEventListener('click', function (ev4) {{ if (window.__qaClick) window.__qaClick(ev4); }});
      }});
      wireEnrichButton(rec);
      var et = document.getElementById('modal-edit-toggle');
      if (et) et.addEventListener('click', function () {{
        var view = $body.querySelector('.modal-view');
        var form = $body.querySelector('.modal-editform');
        if (!form) return;
        var del = document.getElementById('modal-delete-btn');
        if (form.hasAttribute('hidden')) {{
          form.removeAttribute('hidden'); if (view) view.setAttribute('hidden', '');
          et.classList.add('on'); et.setAttribute('aria-expanded', 'true');
          et.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">âœ“</span> Done';
          if (del) del.removeAttribute('hidden');
        }} else {{
          form.setAttribute('hidden', ''); if (view) view.removeAttribute('hidden');
          et.classList.remove('on'); et.setAttribute('aria-expanded', 'false');
          et.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">âœŽ</span> Edit';
          if (del) del.setAttribute('hidden', '');
        }}
      }});
    }}

    // Editing now lives in the top-right "Edit event" toggle; the footer just
    // links out to the event website.
    // No "Visit event website" button: the event NAME in the header is already
    // that link, so this was the same click twice (Hurley 2026-07-30).
    var actHtml = '';
    if (!rec.url) {{
      actHtml += '<span class="modal-nolink">No verified website URL on file.</span>';
    }}
    // "Apply to speak" moved into the read view, above "Also from this
    // organiser" (Hurley 2026-07-30) â€” the footer is now only the no-URL note.
    $actions.innerHTML = actHtml;

    lastFocus = document.activeElement;
    overlay.removeAttribute('hidden');
    document.body.style.overflow = 'hidden';
    overlay.querySelector('.modal-scroll').scrollTop = 0;
    closeBtn.focus();
  }}
  function closeModal() {{
    overlay.setAttribute('hidden', '');
    document.body.style.overflow = '';
    // Chat forward / â‹¯ menus are portaled onto <body>, so they don't die with
    // the modal on their own â€” an Esc-close leaves no click to fire their
    // click-away. Sweep them up here so none linger over the page.
    document.querySelectorAll('.chat-fwd-menu, .chat-more-menu').forEach(function (x) {{ x.remove(); }});
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }}
  window.openEventModal = openEventModal;
  // Bridged for the same reason openEventModal is: the quick-action handler
  // (window.__qaClick) is defined in a DIFFERENT closure and cannot see
  // closeModal directly â€” calling it by name there throws a ReferenceError that
  // silently kills the rest of the handler (Hurley 2026-08-05).
  window.closeEventModal = closeModal;
  // Focus trap shared by both overlays (modal here, briefing drawer in the ops
  // closure) â€” keeps Tab inside the dialog instead of walking the page behind.
  window.trapTab = function (container, e) {{
    if (!container || e.key !== 'Tab') return;
    var f = Array.prototype.slice.call(container.querySelectorAll(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(function (el) {{ return el.offsetParent !== null; }});
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) {{ e.preventDefault(); last.focus(); }}
    else if (!e.shiftKey && document.activeElement === last) {{ e.preventDefault(); first.focus(); }}
  }};
  // Shared helpers â€” the ops tab lives in a SEPARATE closure, so these must
  // ride on window or buildManualCard's calls throw ReferenceError.
  window.audienceClass = audienceClass;
  window.cardPriority = cardPriority;
  window.priceNumOf = priceNumOf;
  window.speakingRouteUrl = speakingRouteUrl;
  window.attendClass = attendClass;
  window.closeEventModal = closeModal;
  window.openEventByNum = function (num) {{ openEventModal(CATALOG[String(num)]); }};
  // "Interested" = people who want Angela to apply for them. Drop anyone who's
  // ALREADY booked (the assigned speaker) or attending (in attendees) for this
  // event â€” no need to apply for someone already going. Keeps everyone else.
  //
  // The speaker only counts as covered once the event is actually BOOKED. A name
  // in `speaker` with nothing booked is the person we INTEND to put forward â€” the
  // application still has to go out, so they belong in Angela's queue. This is
  // the same rule resolveAttendeeKeys uses for the Day-Of brief ("submitted is
  // not attending"). Without it, every event carrying a suggested speaker fell
  // out of the queue and the tab count was far lower than the real workload â€”
  // e.g. Jerome's five upcoming Reuters/CV Summit events vanished.
  window.visibleInterested = function (interested, speaker, attendees, stages) {{
    if (!interested || !interested.length) return [];
    var covered = {{}};
    (attendees || []).forEach(function (a) {{ var k = String(a).toLowerCase().trim(); if (k) covered[k] = 1; }});
    var _booked = !stages || (stages.indexOf && stages.indexOf('Booked') !== -1);
    if (_booked) {{
      String(speaker || '').toLowerCase().replace(/\\s+and\\s+/g, ',').split(/[,;\\/&]/).forEach(function (s) {{
        s = s.trim(); if (s) {{ covered[s] = 1; covered[s.split(/\\s+/)[0]] = 1; }}
      }});
    }}
    return interested.filter(function (n) {{
      var low = String(n).toLowerCase().trim();
      return !(covered[low] || covered[low.split(/\\s+/)[0]]);
    }});
  }};

  closeBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', function (ev) {{ if (ev.target === overlay) closeModal(); }});
  document.addEventListener('keydown', function (ev) {{
    if (overlay.hasAttribute('hidden')) return;
    if (ev.key === 'Escape') closeModal();
    else if (window.trapTab) window.trapTab(overlay.querySelector('.modal-card'), ev);
  }});

  // Every event title is a detail-card link. Keep the website URL inside the
  // detail card so the title has one predictable action everywhere.
  document.addEventListener('click', function (ev) {{
    var link = ev.target.closest ? ev.target.closest('[data-event-detail]') : null;
    if (!link) return;
    ev.preventDefault();
    var kind = link.getAttribute('data-event-detail-kind');
    var key = link.getAttribute('data-event-detail-key');
    if (kind === 'catalog') {{
      var rec = CATALOG[String(key)];
      if (rec) openEventModal(rec);
    }} else if (window.abOpenRef) {{
      window.abOpenRef(kind, key);
    }}
  }});

  // Public catalog cards: delegate clicks + keyboard activation.
  document.addEventListener('click', function (ev) {{
    var card = ev.target.closest ? ev.target.closest('.event.is-clickable') : null;
    if (!card) return;
    if (ev.target.closest('a')) return; // let real links inside cards work
    var rec = CATALOG[card.getAttribute('data-num')];
    if (rec) {{ ev.preventDefault(); openEventModal(rec); }}
  }});

  // For-Angela ops/manual cards: the "Details â†’" button carries a stashed
  // record (card._modalRec) so we can show the same rich pop-up.
  document.addEventListener('click', function (ev) {{
    if (!ev.target.closest) return;
    var card = ev.target.closest('.ops-card');
    if (!card || !card._modalRec) return;
    // The card's own controls keep their own click (star, Urgent/Archive, the
    // name/website link, Apply-to-speak, expandable contacts). A click anywhere
    // ELSE on the card opens the detail pop-up â€” the whole square is the button.
    if (ev.target.closest('a, button, input, select, textarea, label, details, summary')) return;
    ev.preventDefault();
    openEventModal(card._modalRec);
  }});
  document.addEventListener('keydown', function (ev) {{
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    var t = ev.target;
    // Keyboard-open the pop-up when a whole card (role=button) is focused.
    if (t && t.classList && t.classList.contains('ops-card') && t._modalRec) {{
      ev.preventDefault(); openEventModal(t._modalRec); return;
    }}
    if (!t || !t.classList || !t.classList.contains('is-clickable')) return;
    var rec = CATALOG[t.getAttribute('data-num')];
    if (rec) {{ ev.preventDefault(); openEventModal(rec); }}
  }});
}})();

// â”€â”€ Supabase wiring for "For Angela" tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Auth: magic-link via Supabase Auth. Allow-list lives in the
// allowed_editors table; RLS gates writes server-side.
(function () {{
  var SUPABASE_URL = '{SUPABASE_URL}';
  var SUPABASE_KEY = '{SUPABASE_PUBLISHABLE_KEY}';

  // Wait for the deferred Supabase UMD script to attach window.supabase.
  // Hardened: a blocked/failed CDN must become visible instead of leaving the
  // tracker on a blank loading state. We try a pinned fallback after ~3s and
  // show the concrete dependency failure after ~8s.
  function ready(cb) {{
    var polls = 0, injectedFallback = false, warned = false;
    (function poll() {{
      if (window.supabase && window.supabase.createClient) return cb();
      polls++;
      if (polls >= 60 && !injectedFallback) {{
        injectedFallback = true;
        var s = document.createElement('script');
        s.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/dist/umd/supabase.js';
        document.head.appendChild(s);
      }}
      if (polls >= 160 && !warned) {{
        warned = true;
        var el = document.getElementById('angela-loading');
        if (el) {{
          el.innerHTML = '<p class="alert">A required library couldn&rsquo;t load &mdash; check your network or ad&#8209;blocker. Still retrying&hellip; ' +
            '<button type="button" onclick="location.reload()" style="cursor:pointer;">Reload page</button></p>';
          el.style.display = '';
        }}
      }}
      setTimeout(poll, 50);
    }})();
  }}

  ready(function () {{
    var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY, {{
      auth: {{ persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }}
    }});
    window._ab = sb; // exposed for in-browser debugging

    var $loading  = document.getElementById('angela-loading');
    var $signin   = document.getElementById('angela-signin');
    var $sent     = document.getElementById('angela-signin-sent');
    var $unauth   = document.getElementById('angela-unauth');
    var $ops      = document.getElementById('angela-ops');
    var $signinForm   = document.getElementById('signin-form');
    var $signinEmail  = document.getElementById('signin-email');
    var $signinSubmit = document.getElementById('signin-submit');
    var $sentTo       = document.getElementById('signin-sent-to');
    var $unauthEmail  = document.getElementById('unauth-email');
    var $signoutUnauth = document.getElementById('signout-unauth');
    var $signoutOps    = document.getElementById('signout-ops');
    var $opsGrid   = document.getElementById('ops-grid');
    var $opsStatus = document.getElementById('ops-status');
    // Month keys ('YYYY-MM' or 'tbd') the user has collapsed in the ops grid.
    // A truthy value means that month's cards are hidden via the dropdown / header.
    // Both special groups start collapsed: 'archived' = you archived it,
    // 'past' = the date has gone by. Two different things, two different words.
    var opsCollapsedMonths = {{ archived: true, past: true }};
    // Active stat-tile filter ('' | 'saved' | 'urgent' | 'pipeline' | 'booked'
    // | 'attending' | 'buyer' | 'interested' | 'contacts' | 'myinterests') â€” click a top stat to
    // show only those events. Starts empty (All) for everyone; nothing
    // auto-selects a chip any more, so two people opening the tracker see the
    // same grid (the "My fits" auto-default was retired 2026-08-05).
    var opsStatFilter = '';
    // When true, the auto-detected duplicate cards are REVEALED (marked
    // "DUPLICATE") instead of hidden, so they can be opened + deleted in-app.
    var _reviewDupes = false;

    // Last-fetched data, cached by renderOps() so the Queue + Planner views can
    // render from the SAME set the grid just built (no extra fetch).
    var _lastEvs = [], _lastStateMap = {{}}, _lastStateRows = [], _lastManual = [];
    // Recent profile-material uploads (support only) â†’ "In the last week" alerts.
    var _recentUploads = null, _recentUploadsLoading = false;
    // Roster used by the Planner's coverage-gap "Flag for X" action. (The modal
    // closure has its own AB_ROSTER; this closure needs its own copy.)
    var OPS_ROSTER = ['Thor', 'Joe', 'Jerome', 'Scott', 'Verma', 'Carlos', 'Jim'];
    // People who don't want Plan Ahead's month-by-month suggestion list
    // under Event Radar â€” the curated blocks above it are enough.
    var _PLAN_SUGGESTIONS_OFF = {{ thor: 1 }};
    // People who don't want the Plan Ahead section AT ALL (Hurley 2026-07-30).
    // Nothing is deleted: renderPlanAhead and everything it builds stay exactly
    // as they are for everyone else, and this person's own stored state â€” their
    // skips, their hidden trip clusters â€” is left untouched, so removing a name
    // here brings the section back exactly as they left it.
    var _PLAN_AHEAD_OFF = {{ thor: 1 }};

    // â”€â”€ English-language gate for Thor / Verma / Joe â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    // They work the room and take the stage in English, so an event RUN in
    // Spanish / Portuguese / French / German / Italian ("Foro Digital
    // Iberoamericano") is not a fit for them however well the topic or city
    // scores (Hurley 2026-07-29). Jerome (Europe) and Carlos (Latin America)
    // are unaffected â€” their territories are exactly where those events are.
    //
    // Detected from the TITLE, which is the reliable proxy for the working
    // language. Deliberately NOT from the country: "Big Data & AI World Madrid"
    // is an English-language event in Spain and still counts for all three.
    var _ENGLISH_ONLY_PEOPLE = {{ thor: 1, verma: 1, joe: 1 }};
    // One of these is enough on its own â€” no English event title carries them.
    // Deliberately absent: words that are also English brand or venue names.
    // "Datos Insights" (the research firm) runs English events in London, "Messe
    // Frankfurt" and "Fiera Milano" are venues, and an "AI Salon" is an English
    // event format â€” so datos / dados / messe / fiera / salon sit in the weak
    // list below and need corroboration. A false positive here silently hides a
    // good event from someone's fits, which is worse than letting one through.
    var _FL_STRONG = [
      'foro', 'foros', 'congreso', 'congresso', 'cumbre', 'jornada', 'jornadas',
      'encuentro', 'encuentros', 'feria', 'semana', 'iberoamericano',
      'iberoamericana', 'latinoamericano', 'latinoamericana', 'inteligencia',
      'tecnologia', 'tecnologias', 'innovacion', 'inovacao', 'empresas',
      'empresarial', 'negocios', 'seguridad', 'educacion',
      'educacao', 'gestion', 'gestao', 'transformacion', 'transformacao',
      'kongress', 'tagung', 'wirtschaft', 'kunstliche', 'digitalisierung',
      'convegno', 'giornata', 'settimana', 'intelligenza', 'imprese',
      'numerique', 'journee', 'journees', 'rencontres', 'assises', 'entreprise',
      'entreprises', 'donnees'
    ];
    // Weak signals â€” a place name, brand or venue can supply one on its own, so
    // TWO are required. 'las' is deliberately absent: "Las Vegas" is a target city.
    var _FL_FUNC = [
      'de', 'del', 'la', 'el', 'los', 'y', 'para', 'con', 'da', 'do', 'dos',
      'das', 'em', 'sobre', 'du', 'des', 'pour', 'les', 'sur', 'avec', 'und',
      'fur', 'der', 'die', 'per', 'della', 'delle', 'sul', 'nel',
      'datos', 'dados', 'salon', 'messe', 'fiera'
    ];
    function _isForeignLangEvent(o) {{
      var name = String((o && o.name) || '');
      if (!name) return false;
      // Strip the event's OWN location words first: "Rio de Janeiro", "Ciudad de
      // Mexico" and "Sao Paulo" in a title are a place, not the language it runs
      // in, and they'd otherwise supply the function words on their own.
      var locTok = {{}};
      abFold([o.location, o.city, o.country, o.region].filter(Boolean).join(' '))
        .replace(/[^a-z0-9]+/g, ' ').split(' ')
        .forEach(function (w) {{ if (w) locTok[w] = 1; }});
      var strong = 0, func = 0;
      abFold(name).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').forEach(function (w) {{
        if (!w || locTok[w]) return;
        if (_FL_STRONG.indexOf(w) !== -1) strong++;
        else if (_FL_FUNC.indexOf(w) !== -1) func++;
      }});
      return strong >= 1 || func >= 2;
    }}
    // True when this event must stay off `who`'s fits / radar / trip lists.
    function _langBlocked(who, o) {{
      var k = abFold(String(who || '')).split(/\\s+/)[0];
      return !!_ENGLISH_ONLY_PEOPLE[k] && _isForeignLangEvent(o);
    }}

    function showOnly(el) {{
      [$loading, $signin, $sent, $unauth, $ops].forEach(function (n) {{
        if (n) n.setAttribute('hidden', '');
      }});
      if (el) el.removeAttribute('hidden');
    }}

    function status(msg, kind) {{
      if (window._opsStatusT) {{ clearTimeout(window._opsStatusT); window._opsStatusT = null; }}
      if (!msg) {{ $opsStatus.setAttribute('hidden', ''); return; }}
      $opsStatus.removeAttribute('hidden');
      $opsStatus.textContent = msg;
      $opsStatus.className = 'alert' + (kind ? ' ' + kind : '');
      // Auto-dismiss confirmations; keep errors up until the next action.
      if (kind !== 'error') {{
        window._opsStatusT = setTimeout(function () {{ $opsStatus.setAttribute('hidden', ''); }}, 4000);
      }}
    }}

    function escapeHtml(s) {{
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }}

    // â”€â”€ Status taxonomy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    // Light-theme palette derived from Angela's existing Airtable-style
    // tags + her Replit app's wider vocabulary. Grouped by lifecycle
    // stage so the filter row reads top-to-bottom Confirmed â†’ Closed.
    // Colors are picked to read on white background (in contrast to
    // Angela's dark-theme overlays in the Replit version).
    //
    // Each option carries `dot` (a small indicator color, matches the
    // group) which the calendar chip uses to convey status at a glance
    // without having to render the full status name.
    var STATUS_GROUPS = [
      {{ key: 'Confirmed', label: 'Confirmed / scheduled', dot: '#047857' }},
      {{ key: 'Active',    label: 'Active / in progress',  dot: '#0ea5e9' }},
      {{ key: 'Waiting',   label: 'Waiting on',            dot: '#a16207' }},
      {{ key: 'Action',    label: 'Needs action',          dot: '#ca8a04' }},
      {{ key: 'Closed',    label: 'Closed',                dot: '#dc2626' }},
      {{ key: 'Other',     label: 'Other',                 dot: '#737373' }}
    ];

    var STATUS_OPTIONS = [
      // â”€â”€ Confirmed / scheduled â”€â”€
      {{ group: 'Confirmed', value: 'Booked',                                  dup: true, bg: '#047857', fg: '#ffffff' }},
      {{ group: 'Confirmed', value: 'Self Submitted',                          dup: true, bg: '#15803d', fg: '#ffffff' }},
      {{ group: 'Confirmed', value: 'Attending',                               dup: true, bg: '#a78bfa', fg: '#3730a3' }},
      {{ group: 'Confirmed', value: 'Attending (Not Speaking)',                dup: true, bg: '#c4b5fd', fg: '#4c1d95' }},
      {{ group: 'Confirmed', value: 'Attending?',                              dup: true, bg: '#ddd6fe', fg: '#5b21b6' }},
      // â”€â”€ Active / in progress â”€â”€
      {{ group: 'Active',    value: 'Submitted',                               dup: true, bg: '#bbf7d0', fg: '#14532d' }},
      {{ group: 'Active',    value: 'Booking in Progress',                     dup: true, bg: '#86efac', fg: '#14532d' }},
      {{ group: 'Active',    value: 'In contact with',                         bg: '#d1fae5', fg: '#065f46' }},
      {{ group: 'Active',    value: 'In Progress',                             bg: '#fcd34d', fg: '#78350f' }},
      {{ group: 'Active',    value: 'Received Intro Meeting',                  dup: true, bg: '#a7f3d0', fg: '#064e3b' }},
      {{ group: 'Active',    value: 'Personal Contact/Inquiry',                bg: '#e9d5ff', fg: '#6b21a8' }},
      {{ group: 'Active',    value: 'Application Process Inquiry',             bg: '#dbeafe', fg: '#1e40af' }},
      {{ group: 'Active',    value: 'Pending',                                 bg: '#fef3c7', fg: '#854d0e' }},
      {{ group: 'Active',    value: 'Thor Contacting',                         bg: '#cffafe', fg: 'ßß:çfòµë(š+myÖçF‚Æææ–ærv–æF÷p¢–b‡6¶—5µ÷7Vu6¶—–B†—Bæ¶–æBÂ—Bæ¶W’•Ò’&WGW&ã²òò–÷RFV6–FVB&æ÷Bf÷"ÖR ¢–b…÷fWFöVD—FVÒ†—B’’&WGW&ã²òòÆöö·2Æ–¶Rv†B–÷R¶VW6––æræòFð¢–b‚†—Bæ–çFW&W7FVBÇÂµÒ’ç6öÖR†gVæ7F–öâ†â’·²&WGW&â7G&–ær†â’çFôÆ÷vW$66R‚’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒÖTf—'7C²×Ò’’&WGW&ã°¢f"òÒ—Bç7F'Dö&¢ÇÂ··×Ó°¢f"–ävVòÒ…bbvVòæÆVæwF‚’òvVô†—B†—B’¢fÇ6S°¢òòFVfVÇBF&vWF–ær'VÆS¢7F’v—F†–âF†RÆ—7FVBvVöw&†–W2â†&@¢òòvFR(	BF†R7V2w2&W†6WF–öæÂ"÷WBÖöbÖvVòWfVçG2&R&&RäBÖVç@¢òòFò&RfÆvvVBÂæBF†RFF†2æò&VÆ–&ÆRfÆw6†—Ö&¶W"‡&–÷&—G¢òò—2&†–v‚"öâãCbRöbWfVçG2ÂFöòæö—7’FòÖVâW†6WF–öæÂ’Â6òF†÷6P¢òò&RÆVgBFò6FÆör6V&6‚&F†W"F†âFFVB–çFòF†R7VvvW7F–öç2à¢–b…bbvVòæÆVæwF‚bb–ävVò’&WGW&ã°¢f"2ÒÂv‡’ÒµÓ°¢–b†–ävVò’·²2³Ò3²v‡’çW6‚†—Bç&Vv–öâ“²×Ð¢f"†—G2Ò°¢f÷"‡f"’Ò²’Â·w2æÆVæwF‚bb†—G2ÂC²’²²’·°¢–b†—BçFW‡Bæ–æFW„öb†·w5¶•Ò’ÓÒÓ’·²†—G2²³²–b‡v‡’æÆVæwF‚ÂB’v‡’çW6‚†·w5¶•Ò“²×Ð¢×Ð¢2³Ò†—G3°¢–b‚ö'W–W"ö’çFW7B†òæVF–Væ6U÷G—RÇÂrr’’·²2³Ò#²v‡’çW6‚‚v'W–W"×&–6‚r“²×Ð¢–b‚ö†–v‚ö’çFW7B†òç&–÷&—G•ö÷fW'&–FRÇÂòç&–÷&—G’ÇÂrr’’2³Ò°¢òò†÷r×V6‚F†—2Æöö·2Æ–¶Rv†BF†RW'6öâ7GVÆÇ’6†÷w2Wf÷"à¢f"E66÷&RÒ÷F7FU66÷&R‡F7FRÂ—B“°¢òò¦–Òw2&VÖ—B—2D2²v÷fW&æÖVçBâ¶VWöæÇ’WfVçG2F†B&R–âD2Â÷ ¢òò6ÆV&Ç’v÷b†æÖVBÂ÷"ÖF6†–ær"²öb†—2v÷bF†VÖW2“²&–2D2Wà¢–b†ÖTf—'7BÓÓÒv¦–Òr’·°¢f"¦Æö2Ò$föÆB…¶—BæÆö6F–öâÂ—Bæ6—G’Â—Bç&Vv–öåÒæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rr’“°¢f"–äD2Ò¦Æö2æ–æFW„öb‚wv6†–æwFöâr’ÓÒÓ°¢–b‚–äD2bbö—4v÷dFVb†—B’bb†—G2Â"’&WGW&ã°¢–b†–äD2’·²2³Ò3²v‡’çW6‚‚tD2r“²×Ð¢×Ð¢òòw7FvRrW'6öæ—2F†W&RFò5T²Â6òF÷–2ÖÆW72–6²(	B–âÖvVòæ@¢òò'W–W"×&–6‚'WBÖF6†–æræöæRöbF†V—"F†VÖW2(	B—6âwBf—B‡F†—2v0¢òò¦öRÂâ…"7V¶W"ÂvWGF–ærÆöæFöâf–ææ6–Â×6W'f–6W2WfVçG2’â'WB–`¢òò—B7G&öævÇ’ÖF6†W2F†V—"G&6²&V6÷&BÂ¶VW—Bà¢–b…bbÖöFRÓÓÒw7FvRrbb†—G2ÓÓÒbbE66÷&RÂB’&WGW&ã°¢òò–æ6ÇVFRöâW'6öæf—Bõ"7G&öær&W6VÖ&Ææ6RFòF†V—"†—7F÷'’à¢–b‡2ãÒ…òR¢B’ÇÂE66÷&RãÒb’66÷&VBçW6‚‡·²—C¢—BÂ3¢2ÂE66÷&S¢E66÷&RÂv‡“¢v‡’×Ò“°¢×Ò“°¢òò&æ²'’G&6²×&V6÷&B&W6VÖ&Ææ6Rd•%5B†Ö÷7B–×÷'FçB’ÂF†VâW'6öæ¢òòf—BÂF†Vâ6ööæW7B(	B6ò'7VvvW7FVBf÷"–÷R"ÆVG2v—F‚WfVçG2Æ–¶RF†P¢òòöæW2F†—2W'6öâ¶VW2GFVæF–ærò7V¶–ærBà¢66÷&VBç6÷'B†gVæ7F–öâ†Â"’·²&WGW&â†"çE66÷&RÒçE66÷&R’ÇÂ†"ç2Òç2’ÇÂ†æ—Bç6÷'BÒ"æ—Bç6÷'B“²×Ò“°¢&WGW&â66÷&VC²òò6ÆÆW'26Æ–6RFòF†V—"÷vâFWF‚„×’WfVçG2v–FvWBg2âF†RgVÆÂÆâ†VBvR¢×Ð¢f"÷väÆ7BÒµÓ²òòv†Bw2öâ67&VVâ†6VBB‚¢f"÷väÆÂÒµÓ²òòWfW'—F†–ærVÆ–v–&ÆR(	Bv†B$Ö&²ÆÂ2&VB"6ÆV'0¢òòF—7Æ’æÖRg&öÒÆ÷vW&66VBf—'7BÖæÖR¶W’‚'F†÷""Óâ%F†÷""’â¶WB–à¢òòF†R÷26Æ÷7W&R„%õ$õ5DU"Æ—fW2–âF†RÖöFÂ6Æ÷7W&R’Â6ò§W7B6—FÆ—¦Rà¢gVæ7F–öâö÷WG&V6„æÖR†²’·°¢²Ò7G&–ær†²ÇÂrr’çFôÆ÷vW$66R‚“°¢&WGW&â²ò²æ6†$Bƒ’çFõWW$66R‚’²²ç6Æ–6Rƒ’¢³°¢×Ð¢òòWfVçG2v†W&RF†R6–væVBÖ–âW'6öâv26¶VBFò&V6‚÷WB‡F†W’Ö’†fR¢òò6öææV7F–öâ’â7W÷'B„ævVÆô‡W&ÆW’’6VRWfW'’÷WG7FæF–ær6²ÂFVÒ×v–FRà¢gVæ7F–öâö÷WG&V6„—FV×2‚’·°¢f"ÖRÒvWD6öÆÆ$æÖR‚’ÇÂrs°¢–b‚ÖR’&WGW&âµÓ°¢f"ÖTf—'7BÒ$föÆB†ÖR’ç7Æ—B‚õÅÇ2²ò•³Ó°¢f"7W÷'BÒöÖW&vVEFVÕf–Wr‚“°¢f"÷WBÒµÓ°¢÷4ÆÄ—FV×2‚’æf÷$V6‚†gVæ7F–öâ†—B’·°¢–b†—Bç7BÇÂ—Bæ†–FFVâ’&WGW&ã°¢f"6rÒ†—Bæ÷WG&V6…ö76–væVW2ÇÂµÒ’æÖ†gVæ7F–öâ†â’·²&WGW&â$föÆB†â’ç7Æ—B‚õÅÇ2²ò•³Ó²×Ò’æf–ÇFW"„&ööÆVâ“°¢–b‚6ræÆVæwF‚’&WGW&ã°¢–b‚7W÷'Bbb6ræ–æFW„öb†ÖTf—'7B’ÓÓÒÓ’&WGW&ã°¢÷WBçW6‚‡·²¶–æC¢—Bæ¶–æBÂ¶W“¢—Bæ¶W’ÂæÖS¢—BææÖRÂFFU÷7G#¢—BæFFU÷7G"ÂÆö6F–öã¢—BæÆö6F–öâÂæ÷FS¢—Bæ÷WG&V6…öæ÷FRÇÂrrÂ76–væVW3¢6rÂ6÷'C¢—Bç6÷'B×Ò“°¢×Ò“°¢÷WBç6÷'B†gVæ7F–öâ†Â"’·²&WGW&âç6÷'BÒ"ç6÷'C²×Ò“°¢&WGW&â÷WC°¢×Ð¢gVæ7F–öâ&VæFW$×”WfVçG2‚’·°¢f"†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö×–WfVçG2r“°¢–b‚†÷7B’&WGW&ã°¢f""Ò×”WfVçG4'V6¶WG2‚“°¢–b‚"ææÖVB’·°¢†÷7Bæ–ææW$…DÔÂÒsÇ6Æ73Ò'VWVRÖ–çG&ò×–WbÖ–çG&ò#ãÇ7G&öæsä×’Æ–æWWãÂ÷7G&öæsâ6WB–÷W"æÖR‡F÷×&–v‡BfF"g&'#²6öÖVöæRVÇ6R’Fò6VRF†RWfVçG2–÷Rb33“·&R&öö¶VBFò7V²B÷"GFVæF–ærãÂ÷âs°¢&WGW&ã°¢×Ð¢gVæ7F–öâ&÷t‡FÖÂ†—BÂ6†÷uv†ò’·°¢f"Æö2Ò¶—BæÆö6F–öåÒæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rfÖ–FF÷C²r“°¢òòF†R4ÔRÖ&·2F†Rw&–B6&B6†÷w2(	BöæR7–Ö&öÂÆæwVvRWfW'—v†W&Rà¢f"7FGW4‡FÖÂÒ—Bç7FGW4‡FÖÂòsÆF—b6Æ73Ò'&÷rÖÖ&·2#âr²—Bç7FGW4‡FÖÂ²sÂöF—câr¢rs°¢òòF†RF’Ôöb'&–VbÆ—fW2†W&R†æò6W&FRF"’(	BöâW6öÖ–ær&÷w2â¢òò&—fFRò–çf—FRÖöæÇ’WfVçB†æòöæÆ–æRfö÷G&–çB’6âwB&R'&–VfVBÀ¢òò6òæò'&–Vb'WGFöâ‡6VR'&–Vf&ÆV’â'&–Vg2&RævVÆw2FööÂ(	BöæÇ¢òò†W"f–Wr6†÷w2F†R'WGFöâ†WfW'–öæRVÇ6Rw2Æ–æWW&÷w2†fRæò'&–Vb’à¢f"'&–VbÒ†—Bå÷7BÇÂ—Bæ'&–Vf&ÆRÇÂ‡v–æF÷ræ—4ævVÆW6W"bbv–æF÷ræ—4ævVÆW6W"‚’’’òrr ¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&÷rÖ'&–Vbr²†—Bæ'&–Ve&VG’òr—2×&VG’r¢rr’²r"FFÖ'&–VbÖ¶–æCÒ"r²—Bæ¶–æB²r"FFÖ'&–VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r"F—FÆSÒ"r°¢†—Bæ'&–Ve&VG’òt'&–Vb&VG’r¢t'V–ÆBF†RF’Ööb'&–Vbr’²r#âr°¢†—Bæ'&–Ve&VG’òrb33²'&–Vbr¢t'&–Vbg&'#²r’²sÂö'WGFöãâs°¢òòF†Rv†öÆR&÷r÷Vç2F†RWfVçBFWF–Ç2öâ6Æ–6²†Æ–¶RF†Rw&–B6&G2’(	@¢òòæò6W&FR$FWF–Ç2"'WGFöââF†R'&–Vb'WGFöâ7F÷2&÷vF–öâ6ò—@¢òò7F–ÆÂf—&W2—G2÷vâ7F–öâà¢òòF†R6W&FR'v†÷6RWfVçB—2—B"fF"7G&——2tôäRƒ##bÓ‚ÓR’à¢òòF†R7FGW2Ö&·2æ÷r6''’F†R–æ—F–Ç2F†V×6VÇfW2(	BÖ–2f÷"F†P¢òò7V¶W"ÂF–6¶WBf÷"GFVæFVW2Â6öÆ÷W&VB7F"W"–çFW&W7FVBW'6öâ(	@¢òò6òGWÆ–6FR&÷röbF—6726–BF†R6ÖRæÖW2Gv–6Râ6†÷uv†ö—0¢òò¶WB–âF†R6–væGW&R&V6W6RF†R6ÆÆW'27F–ÆÂ72—Bà¢fö–B6†÷uv†ó°¢f"v†ô‡FÖÂÒrs°¢&WGW&âsÆF—b6Æ73Ò'VWVR×&÷rVWVR×&÷rÖ÷Vâ"&öÆSÒ&'WGFöâ"F&–æFWƒÒ#"FF×&VbÖ¶–æCÒ"r²—Bæ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r#ãÆF—b6Æ73Ò'VWVRÖÖ–â#âr°¢sÇ7â6Æ73Ò'VWVRÖæÖR#âr²W66T‡FÖÂ†—BææÖR’²sÂ÷7ãâr°¢sÇ6Æ73Ò'VWVRÖÖWF#âr²W66T‡FÖÂ†—BæFFU÷7G"ÇÂtFFRD$Br’²†Æö2òrfÖ–FF÷C²r²Æö2¢rr’²sÂ÷âr°¢7FGW4‡FÖÂ°¢sÂöF—câr°¢‚‡v†ô‡FÖÂÇÂ'&–Vb¢òsÆF—b6Æ73Ò'VWVRÖ7F–öç2&÷r×6–FR#âr²v†ô‡FÖÂ²'&–Vb²sÂöF—câp¢¢rr’°¢sÂöF—câs°¢×Ð¢gVæ7F–öâ6V7F–öâ‡F—FÆRÂÆ—7BÂV×G”×6rÂ6öÆÆ6–&ÆRÂ6öÆÆ6VBÂ6†÷uv†ò’·°¢f"6&WBÒ6öÆÆ6–&ÆRòsÇ7â6Æ73Ò'6V2Ö6&WB"&–Ö†–FFVãÒ'G'VR#âb3“cc#³Â÷7ãâr¢rs°¢f"†VBÒsÆF—b6Æ73Ò'VWVR×6V2Ö†VB"r²†6öÆÆ6–&ÆRòr&öÆSÒ&'WGFöâ"F&–æFWƒÒ#"r¢rr’²sâr²6&WB°¢sÇ7â6Æ73Ò'VWVR×6V2×F—FÆR#âr²F—FÆR²sÂ÷7ããÇ7â6Æ73Ò'VWVR×6V2Ö6÷VçB#âr²Æ—7BæÆVæwF‚²sÂ÷7ããÂöF—câs°¢f"&öG’ÒÆ—7BæÆVæwF‚òÆ—7BæÖ†gVæ7F–öâ†—B’·²&WGW&â&÷t‡FÖÂ†—BÂ6†÷uv†ò“²×Ò’æ¦ö–â‚rr¢¢sÆF—b6Æ73Ò'VWVRÖV×G’#âr²V×G”×6r²sÂöF—câs°¢&WGW&âsÆF—b6Æ73Ò'VWVR×6V7F–öâr²†6öÆÆ6–&ÆRòr6öÆÆ6–&ÆRr¢rr’²†6öÆÆ6VBòr6öÆÆ6VBr¢rr’²r#âr²†VB²&öG’²sÂöF—câs°¢×Ð¢f"–çG&òÒ"ç7W÷'@¢òsÇ6Æ73Ò'VWVRÖ–çG&ò×–WbÖ–çG&ò#ãÇ7G&öæsåFVÒWfVçG3£Â÷7G&öæsâWfW'–öæRF†RFVÒ—2&öö¶VBFò7V²B÷"GFVæF–ærfÖF6ƒ²W6öÖ–ærf—'7BÂ7B&VÆ÷rãÂ÷âp¢¢sÇ6Æ73Ò'VWVRÖ–çG&ò×–WbÖ–çG&ò#ãÇ7G&öæsâr²W66T‡FÖÂ†"æÖR’²rb33“·2WfVçG3£Â÷7G&öæsâWfVçG2–÷Rb33“·&R&öö¶VBFò7V²B÷"GFVæF–ærfÖF6ƒ²W6öÖ–ærf—'7BÂ7B&VÆ÷rãÂ÷âs°¢òòöæR6†&VBÆ—7BÂ6ò$×’"v÷VÆB&RÆ–R(	BF†W6R&RF†RFVÒw2ÂæBF†P¢òò–æ—F–Ç2öâV6‚&÷r6’v†÷6R†ÖW&vVBf–WrÂ##bÓ‚ÓR’à¢f"WF—FÆRÒöÖW&vVEFVÕf–Wr‚’òuW6öÖ–ærWfVçG2r¢t×’W6öÖ–ærWfVçG2s°¢òò7BWfVçG26öÆÆ6R–çFòG&÷F÷vâÂ†–FFVâ'’FVfVÇB†Æ–¶RF†Rw&–Bw0¢òòÖöçF‚w&÷W2’âö×”WfVçG57D÷Vâ&VÖVÖ&W'2–bF†R&VFW"W‡æFVBF†VÒà¢òò$–âF†RÆ7BvVV²"(	BFVÖÖFW2rWFFW2²æWr6öÖÖVçG2â&÷r6öÖW2F÷và¢òòv†Vâ—Bw24„T4´TBôdbæBöæÇ’F†Vã²6Æ–6¶–ærF‡&÷Vv‚FòF†RWfVçBÆVfW0¢òò—B–âÆ6Râ$Ö&²ÆÂ2&VB"6ÆV'2F†RfVVBÂ÷"öæRW'6öâw2&÷WF–æP¢òòWFFW2Â–â6–ævÆRvòà¢òò7W÷'C¢ÆöB&V6VçB&öf–ÆRWÆöG2öæ6RÂF†Vâ&R×&VæFW"FòföÆBF†VÒ–âà¢–b†"ç7W÷'Bbb÷&V6VçEWÆöG2ÓÓÒçVÆÂbb÷&V6VçEWÆöG4ÆöF–ær’·°¢÷&V6VçEWÆöG4ÆöF–ærÒG'VS°¢öÆöE&V6VçEWÆöG2†gVæ7F–öâ‚’·²÷&V6VçEWÆöG4ÆöF–ærÒfÇ6S²–b†7W'&VçEf–WrÓÓÒv×–WfVçG2r’&VæFW$×”WfVçG2‚“²×Ò“°¢×Ð¢òò%&V6‚÷WB"(	BWfVçG2ævVÆ6¶VBF†—2W'6öâFòÖ¶R6öçF7Bf÷"â6—G0¢òòBF†RfW'’Dõöb×’Æ–æWW†—Bw2FòÖFò76–væVBFòF†VÒ’â7W÷'B6VP¢òòWfW'’÷WG7FæF–ær6²7&÷72F†RFVÒà¢f"ö÷WG&V6‚Òö÷WG&V6„—FV×2‚“°¢f"÷WD‡FÖÂÒrs°¢–b…ö÷WG&V6‚æÆVæwF‚’·°¢f"÷WE&÷w2Òö÷WG&V6‚æÖ†gVæ7F–öâ†ò’·°¢f"Æö2Ò¶òæÆö6F–öåÒæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rfÖ–FF÷C²r“°¢f"6²Ò"ç7W÷'@¢òu–÷R6¶VBr²òæ76–væVW2æÖ†gVæ7F–öâ†’·²&WGW&âsÇ7G&öæsâr²W66T‡FÖÂ…ö÷WG&V6„æÖR†’’²sÂ÷7G&öæsâs²×Ò’æ¦ö–â‚rf×²r’²rFò&V6‚÷WBp¢¢sÇ7G&öæsäævVÆÂ÷7G&öæsâ6¶VB–÷RFò&V6‚÷WBfÖF6ƒ²–÷RÖ’†fR6öææV7F–öâs°¢f"æ÷FT‡FÖÂÒòææ÷FRòsÇ6Æ73Ò&÷WG&V6‚Öæ÷FR#âfÆGVó²r²W66T‡FÖÂ†òææ÷FR’²rg&GVó³Â÷âr¢rs°¢&WGW&âsÆF—b6Æ73Ò'VWVR×&÷rVWVR×&÷rÖ÷Vâ÷WG&V6‚×&÷r"&öÆSÒ&'WGFöâ"F&–æFWƒÒ#"FF×&VbÖ¶–æCÒ"r²òæ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†òæ¶W’’’²r#ãÆF—b6Æ73Ò'VWVRÖÖ–â#âr°¢sÇ7â6Æ73Ò'VWVRÖæÖR#âr²W66T‡FÖÂ†òææÖR’²sÂ÷7ãâr°¢sÇ6Æ73Ò'VWVRÖÖWF#âr²W66T‡FÖÂ†òæFFU÷7G"ÇÂtFFRD$Br’²†Æö2òrfÖ–FF÷C²r²Æö2¢rr’²sÂ÷âr°¢sÇ6Æ73Ò&÷WG&V6‚Ö6²#ãÇ7â6Æ73Ò&÷WG&V6‚Ö–6ò"&–Ö†–FFVãÒ'G'VR#âb3#“3“³Â÷7ãâr²6²²sÂ÷âr²æ÷FT‡FÖÂ°¢sÂöF—cãÂöF—câs°¢×Ò’æ¦ö–â‚rr“°¢÷WD‡FÖÂÒsÆF—b6Æ73Ò'VWVR×6V7F–öâ÷WG&V6‚×6V7F–öâ#ãÆF—b6Æ73Ò'VWVR×6V2Ö†VB#âr°¢sÇ7â6Æ73Ò'VWVR×6V2×F—FÆR#âr²†"ç7W÷'Bòt÷WG&V6‚6·2r¢u&V6‚÷WBr’²sÂ÷7ãâr°¢sÇ7â6Æ73Ò'VWVR×6V2Ö6÷VçB#âr²ö÷WG&V6‚æÆVæwF‚²sÂ÷7ããÂöF—câr²÷WE&÷w2²sÂöF—câs°¢×Ð¢÷väÆ7BÒ÷v†G4æWt—FV×2‚“°¢÷väÆÂÒ÷v†G4æWt—FV×2‡G'VR“°¢f"vä‡FÖÂÒrs°¢–b…÷väÆ7BæÆVæwF‚’·°¢òò6öÖÖVçBF‡&VG27W&f6RBeTÄÂf—6–&–Æ—G’‡F†W’Æ–¶VÇ’æVVB&WÇ’“°¢òò&÷WF–æR—VÆ–æRÖ÷fW2vWBw&÷WVBW"W'6öâ–çFò6öÆÆ6V@¢òò#ÄæÖSâ+râ&÷WF–æRWFFW2"&÷r‡FFòW‡æB’6òF†W’FöâwBG&÷và¢òòF†R6öçfW'6F–öç2F†BæVVB–÷Rà¢f"ö6öÖÖVçG2ÒµÒÂ÷WFFW2ÒµÓ°¢÷väÆ7Bæf÷$V6‚†gVæ7F–öâ‡rÂ’’·²‡rçG—RÓÓÒv6öÖÖVçBròö6öÖÖVçG2¢÷WFFW2’çW6‚‡·²s¢rÂ“¢’×Ò“²×Ò“°¢f"ö6&G4‡FÖÂÒö6öÖÖVçG2æÖ†gVæ7F–öâ†ò’·°¢f"rÒòçs°¢f"V÷FRÒrç&Wf–WròrfÆGVó²r²W66T‡FÖÂ‡rç&Wf–Wr’²rg&GVó²r¢W66T‡FÖÂ‡ræÆ&VÂ“°¢f"†VBÒræÖVçF–öà¢òsÇ7G&öæsâr²W66T‡FÖÂ‡ræWF†÷"ÇÂu6öÖVöæRr’²sÂ÷7G&öæsâÖVçF–öæVB–÷RöâÇ7G&öæsâr²W66T‡FÖÂ‡ræWfVçDæÖRÇÂvâWfVçBr’²sÂ÷7G&öæsâp¢¢sÇ7G&öæsâr²W66T‡FÖÂ‡ræWF†÷"ÇÂu6öÖVöæRr’²sÂ÷7G&öæsâ6öÖÖVçFVBöâÇ7G&öæsâr²W66T‡FÖÂ‡ræWfVçDæÖRÇÂvâWfVçBr’²sÂ÷7G&öæsâs°¢&WGW&âsÆF—b6Æ73Ò'vâÖ6öÖÖVçBr²‡ræÖVçF–öâòr—2ÖÖVçF–öâr¢rr’²r"&öÆSÒ&'WGFöâ"F&–æFWƒÒ#"FF×vâÖ÷VãÒ"r²òæ’²r#âr°¢sÇ7â6Æ73Ò'vâÖfF"×w&#ãÇ7â6Æ73Ò'vâÖfF""7G–ÆSÒ&&6¶w&÷VæC¢r²v–æF÷ræ%W'6öä6öÆ÷"‡ræWF†÷"’²r#âr²W66T‡FÖÂ…÷vä–æ—F–Ç2‡ræWF†÷"’’²sÂ÷7ãâr°¢sÇ7â6Æ73Ò'vâÖ6†BÖ&FvR"F—FÆSÒ$6†B6öÖÖVçB"&–ÖÆ&VÃÒ&6†B6öÖÖVçB#ãÇ7frf–Wt&÷ƒÒ##B#B"f–ÆÃÒ&7W'&VçD6öÆ÷""&–Ö†–FFVãÒ'G'VR#ãÇF‚CÒ$Ó#$ƒF""Ó"'c†ÃBÓFƒF"""Ó%cF""Ó"Ó'¢"óãÂ÷7fsãÂ÷7ããÂ÷7ãâr°¢sÆF—b6Æ73Ò'vâÖ6öÖÖVçBÖÖ–â#âr°¢sÆF—b6Æ73Ò'vâÖ6öÖÖVçBÖ†VB#âr²†VB²sÇ7â6Æ73Ò'vâ×F–ÖR#âr²W66T‡FÖÂ…÷&VÅF–ÖR‡rçG2’’²sÂ÷7ããÂöF—câr°¢sÆF—b6Æ73Ò'vâÖ6öÖÖVçB×V÷FR#âr²V÷FR²sÂöF—câr°¢sÂöF—câr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'vâÖ6†V6²"FF×vâÖ6†V6³Ò"r²òæ’²r"F—FÆSÒ$Ö&²26VVâ#âb33³Âö'WGFöãâr°¢sÂöF—câs°¢×Ò’æ¦ö–â‚rr“°¢òòw&÷W&÷WF–æRWFFW2'’W'6öâà¢f"ö'•v†òÒ··×ÒÂ÷v†ô÷&FW"ÒµÓ°¢÷WFFW2æf÷$V6‚†gVæ7F–öâ†ò’·°¢f"v†òÒòçrçv†òÇÂu6öÖVöæRs°¢–b‚ö'•v†õ·v†õÒ’·²ö'•v†õ·v†õÒÒµÓ²÷v†ô÷&FW"çW6‚‡v†ò“²×Ð¢ö'•v†õ·v†õÒçW6‚†ò“°¢×Ò“°¢f"öw&÷W4‡FÖÂÒ÷v†ô÷&FW"æÖ†gVæ7F–öâ‡v†ò’·°¢f"Æ—7BÒö'•v†õ·v†õÓ°¢f"&÷w2ÒÆ—7BæÖ†gVæ7F–öâ†ò’·°¢&WGW&âsÆF—b6Æ73Ò'VWVR×&÷rvâ×&÷r#ãÆF—b6Æ73Ò'VWVRÖÖ–â#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'VWVRÖæÖRvâÖ÷Vâ"FF×vâÖ÷VãÒ"r²òæ’²r#âr²W66T‡FÖÂ†òçræFWF–ÂÇÂòçræÆ&VÂ’²sÂö'WGFöãâr°¢sÂöF—cãÆF—b6Æ73Ò'VWVRÖ7F–öç2#ãÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'FâvâÖ6†V6²"FF×vâÖ6†V6³Ò"r²òæ’²r"F—FÆSÒ$Ö&²26VVâ#âb33³Âö'WGFöããÂöF—cãÂöF—câs°¢×Ò’æ¦ö–â‚rr“°¢òò&F6‚6†V6²Ööfbf÷"F†—2W'6öâw2&÷WF–æRWFFW2(	B6ÆV&–ær'Vâö`¢òò—VÆ–æRÖ÷fW2öæR)É2BF–ÖRv2F†RFVF–÷W2'B„‡W&ÆW’’â¶W–VB'¢òòF†RU%4ôâÂæ÷BF†Rf—6–&ÆR&÷r–æFW†W2Â6ò—BÇ6ò6ÆV'2F†V— ¢òòWFFW26—GF–ær&V†–æBF†R‚Ö—FVÒF—7Æ’6à¢&WGW&âsÆF—b6Æ73Ò'vâÖw&÷W6öÆÆ6VB#âr°¢sÆF—b6Æ73Ò'vâÖw&÷WÖ†VB"&öÆSÒ&'WGFöâ"F&–æFWƒÒ##âr°¢sÇ7â6Æ73Ò'vâÖfF"vâÖfF"Ò×6Ò"7G–ÆSÒ&&6¶w&÷VæC¢r²v–æF÷ræ%W'6öä6öÆ÷"‡v†ò’²r#âr²W66T‡FÖÂ…÷vä–æ—F–Ç2‡v†ò’’²sÂ÷7ãâr°¢sÇ7â6Æ73Ò'vâÖw&÷WÖæÖR#âr²W66T‡FÖÂ‡v†ò’²sÂ÷7ãâr°¢sÇ7â6Æ73Ò'vâÖw&÷WÖ6÷VçB#âr²Æ—7BæÆVæwF‚²rr°¢†Æ—7BæWfW'’†gVæ7F–öâ†ò’·²&WGW&âòçræ6³²×Ò¢ò‚wVW7F–öâr²†Æ—7BæÆVæwF‚ÓÓÒòrr¢w2r’²rFò’r¢¢‚w&÷WF–æRWFFRr²†Æ—7BæÆVæwF‚ÓÓÒòrr¢w2r’’’²sÂ÷7ãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'vâ×&VFÆÂ"FF×vâ×&VFw&÷WÒ"r²W66T‡FÖÂ‡v†ò’²r#äÖ&²ÆÂ2&VCÂö'WGFöãâr°¢sÇ7â6Æ73Ò'6V2Ö6&WB"&–Ö†–FFVãÒ'G'VR#âb3“cc#³Â÷7ãâr°¢sÂöF—câr°¢sÆF—b6Æ73Ò'vâÖw&÷WÖ&öG’#âr²&÷w2²sÂöF—câr°¢sÂöF—câs°¢×Ò’æ¦ö–â‚rr“°¢vä‡FÖÂÒsÆF—b6Æ73Ò'VWVR×6V7F–öâvâ×6V7F–öâ#ãÆF—b6Æ73Ò'VWVR×6V2Ö†VB#âr°¢sÇ7â6Æ73Ò'VWVR×6V2×F—FÆR#ä–âF†RÆ7BvVV³Â÷7ãâr°¢òò6’6òv†VâF†W&Rw2Ö÷&R&V†–æBF†R‚Ö—FVÒ6Â÷F†W'v—6P¢òò$Ö&²ÆÂ2&VB"V'2Fò6ÆV"‚æB6–ÆVçFÇ’6ÆV'2Bà¢sÇ7â6Æ73Ò'VWVR×6V2Ö6÷VçB#âr²÷väÆ7BæÆVæwF‚°¢…÷väÆÂæÆVæwF‚â÷väÆ7BæÆVæwF‚òröbr²÷väÆÂæÆVæwF‚¢rr’²sÂ÷7ãâr°¢òò6V7F–öâÖÆWfVÂ6ÆV"ÖWfW'—F†–ærÂ6ÖRv÷&F–ær2F†RW"×W'6öâöæRà¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'vâ×&VFÆÂvâ×&VFÆÂÒÖÆÂ"FF×vâ×&VFÆÃäÖ&²ÆÂ2&VCÂö'WGFöãâr°¢sÂöF—câr°¢ö6&G4‡FÖÂ²öw&÷W4‡FÖÂ²sÂöF—câs°¢×Ð¢òòFVÒ–çFW&W7G2òGFVæFæ6Rò—VÆ–æRÆ—fVB†W&RVçF–Â##bÓrÓ3à¢òòF‡&VR'’×W'6öâ&öÆÂ×W2ç7vW&–ær'v†ò—2–çFW&W7FVBÂv†ò—2vö–ærÀ¢òòv†B—2–âfÆ–v‡B"(	B'WBF†RÆ–æWW—2ÖVçBFò&R”õU"WfVçG2Âæ@¢òòf÷"ævVÆ—B†B&V6öÖRvÆÂöbæÖW2&÷fR†W"7GVÂv÷&²à¢òòF†RVWVRæ÷rç7vW'2F†R6ÖRVW7F–öâ–âF†R6†R6†R&VG2—B–à¢òò†'’WfVçBÂ–âFFR÷&FW"Âv—F‚F†R–çFW&W7FVBæÖW2öâF†R&÷r’Â6ð¢òòF†W6R&RvöæR&F†W"F†âÖ÷fVB„‡W&ÆW“¢'6†÷VÆB&R–âF†RVWVR–`¢òòç—F†–ærÂ'WBæ÷BÆ–¶RF†—27G–ÆR"’à¢òòÆâ†VBæ÷rÆ—fW2BF†R$õEDôÒöb×’Æ–æWW†&VÆ÷r7BWfVçG2’À¢òò&WÆ6–ærF†RöÆB%7VvvW7FVBf÷"–÷R"(	B—Bw2&WGFW"fW'6–öâöbF†P¢òò6ÖR–FV‡G&—2²–çFW&W7B&V72²ÖöçF†Ç’–6·2’â&VæFW%Æä†VB‚¢òòf–ÆÇ2F†RVÖ&VB&VÆ÷s²—G2÷vâ–çG&ò—2F†RF—f–FW"&WGvVVâF†RGvòà¢òòVæFW"F†RÖW&vVBf–WrWfW'’FVÒWfVçBÆæG2–âW6öÖ–ævÂ6òFVÖ—0¢òòÇv—2V×G’(	B—Bv27F–ÆÂ&VæFW&–ær2W&ÖæVçB$æö&öG’VÇ6R—0¢òòF÷vâf÷"ç—F†–ærW6öÖ–ær"Âv†–6‚—2&÷F‚VçG'VRæBVæ†VÇgVÂâöæP¢òò6V7F–öâæ÷rÂv—F‚–æ—F–Ç2öâF†R&÷w2‡6†÷uv†ò’6ò–÷R6â7F–ÆÂFVÆÀ¢òòv†÷6RWfVçBV6‚öæR—2„‡W&ÆW’##bÓ‚ÓR’à¢f"öÖW&vVBÒöÖW&vVEFVÕf–Wr‚“°¢†÷7Bæ–ææW$…DÔÂÒ–çG&ò²÷WD‡FÖÂ²vä‡FÖÂ°¢‚†"ç7W÷'Bbb"çW6öÖ–æræÆVæwF‚’òrr¢6V7F–öâ‡WF—FÆRÂ"çW6öÖ–ærÂtæ÷F†–ærW6öÖ–ær–WBârÂfÇ6RÂfÇ6RÂöÖW&vVB’’°¢…öÖW&vVBòrr¢6V7F–öâ‚%FVÒb33“·2W6öÖ–ærWfVçG2"Â"çFVÒÀ¢tæö&öG’VÇ6R—2F÷vâf÷"ç—F†–ærW6öÖ–ærârÂfÇ6RÂfÇ6RÂG'VR’’°¢†"ç7BæÆVæwF‚ò6V7F–öâ‚u7BWfVçG2rÂ"ç7BÂrrÂG'VRÂö×”WfVçG57D÷VâÂöÖW&vVB’¢rr’°¢sÆF—b–CÒ&÷2×Ææ†VB"6Æ73Ò&÷2×Ææ†VBÖVÖ&VB#ãÂöF—câs°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×&VbÖ¶–æEÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²÷4÷Vå&Vb†VÂævWDGG&–'WFR‚vFF×&VbÖ¶–æBr’ÂVÂævWDGG&–'WFR‚vFF×&VbÖ¶W’r’“²×Ò“°¢×Ò“°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×vâÖ÷VåÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢f"ö÷VâÒgVæ7F–öâ‚’·°¢f"rÒ÷väÆ7E·'6T–çB†VÂævWDGG&–'WFR‚vFF×vâÖ÷Vâr’Â•Ó°¢–b‚r’&WGW&ã°¢òòäõDS¢÷Væ–ærFöW2äõBÖ&²—B&VB(	BöæÇ’F†R)É2FöW2„‡W&ÆW’’â–÷P¢òò6â6Æ–6²F‡&÷Vv‚FòF†RWfVçBÂ6öÖR&6²ÂæBF†R&÷r—27F–ÆÂ†W&Rà¢òò&öf–ÆR×WÆöBWFFR÷Vç2×’&öf–ÆR†—B—6âwBF–VBFòâWfVçB’à¢–b‡rç&öf–ÆR’·²6WEf–Wr‚v×—&öf–ÆRr“²&WGW&ã²×Ð¢÷4÷Vå&Vb‡ræ¶–æBÂ7G&–ær‡ræ¶W’’“°¢×Ó°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂö÷Vâ“°¢òò6öÖÖVçB6&G2&R&öÆSÒ&'WGFöâ"(	B÷VâöâVçFW"ò76RFöòà¢–b†VÂæ6Æ74Æ—7Bæ6öçF–ç2‚wvâÖ6öÖÖVçBr’’VÂæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·²–b†Ræ¶W’ÓÓÒtVçFW"rÇÂRæ¶W’ÓÓÒrr’·²Rç&WfVçDFVfVÇB‚“²ö÷Vâ‚“²×Ò×Ò“°¢×Ò“°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×vâÖ6†V6µÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“²òòFöâwBÇ6òG&–vvW"F†R6&B÷&÷rw2÷Và¢f"rÒ÷väÆ7E·'6T–çB†VÂævWDGG&–'WFR‚vFF×vâÖ6†V6²r’Â•Ó°¢–b‚r’&WGW&ã°¢÷väF—6Ö—72‡r“°¢&VæFW$×”WfVçG2‚“°¢×Ò“°¢×Ò“°¢òò$Ö&²ÆÂ2&VB"(	BF†Rv†öÆRfVVBà¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×vâ×&VFÆÅÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢÷väF—6Ö—74Öç’…÷väÆÂ“²òòWfW'—F†–ærÂæ÷B§W7BF†Rf—6–&ÆR€¢&VæFW$×”WfVçG2‚“°¢×Ò“°¢×Ò“°¢òò$Ö&²ÆÂ2&VB"(	BöæRW'6öâw2&÷WF–æRWFFW2â7F÷&÷vF–öâ¶VW0¢òòF†R6Æ–6²öfbF†Rw&÷W†VFW"Âv†–6‚v÷VÆB÷F†W'v—6R6öÆÆ6RöW‡æBà¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×vâ×&VFw&÷WÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢f"v†òÒVÂævWDGG&–'WFR‚vFF×vâ×&VFw&÷Wr’ÇÂrs°¢÷väF—6Ö—74Öç’…÷väÆÂæf–ÇFW"†gVæ7F–öâ‡r’·°¢&WGW&ârçG—RÓÒv6öÖÖVçBrbb7G&–ær‡rçv†òÇÂu6öÖVöæRr’ÓÓÒv†ó°¢×Ò’“°¢&VæFW$×”WfVçG2‚“°¢×Ò“°¢×Ò“°¢òòW"×W'6öâ'&÷WF–æRWFFW2"w&÷W27F'B6öÆÆ6VC²FF†R†VFW"Fð¢òòW‡æB†W†VÖW&Â(	BæòæVVBFòW'6—7BöæR×vVV²fVVBw2÷Vâ7FFR’à¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚rçvâÖw&÷WÖ†VBr’æf÷$V6‚†gVæ7F–öâ††VB’·°¢f"÷FrÒgVæ7F–öâ‚’·²†VBæ6Æ÷6W7B‚rçvâÖw&÷Wr’æ6Æ74Æ—7BçFövvÆR‚v6öÆÆ6VBr“²×Ó°¢†VBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂ÷Fr“°¢†VBæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·°¢òòöæÇ’F†R†VFW"—G6VÆbFövvÆW2(	BVçFW"õ76RöâF†RæW7FV@¢òò$Ö&²ÆÂ2&VB"'WGFöâ×W7Bæ÷BÇ6ò6öÆÆ6RF†Rw&÷Wà¢–b†RçF&vWBÓÒ†VB’&WGW&ã°¢–b†Ræ¶W’ÓÓÒtVçFW"rÇÂRæ¶W’ÓÓÒrr’·²Rç&WfVçDFVfVÇB‚“²÷Fr‚“²×Ð¢×Ò“°¢×Ò“°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FFÖ'&–VbÖ¶–æEÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·²Rç7F÷&÷vF–öâ‚“²÷Vä'&–VdG&vW"†VÂævWDGG&–'WFR‚vFFÖ'&–VbÖ¶–æBr’ÂVÂævWDGG&–'WFR‚vFFÖ'&–VbÖ¶W’r’“²×Ò“°¢×Ò“°¢òòv†öÆR×&÷r¶W–&ö&B÷Vâ‡&÷w2&R&öÆSÒ&'WGFöâ"æ÷r’à¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚rçVWVR×&÷rÖ÷Vâr’æf÷$V6‚†gVæ7F–öâ‡&÷r’·°¢&÷ræFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·°¢–b†Ræ¶W’ÓÓÒtVçFW"rÇÂRæ¶W’ÓÓÒrr’·²Rç&WfVçDFVfVÇB‚“²÷4÷Vå&Vb‡&÷rævWDGG&–'WFR‚vFF×&VbÖ¶–æBr’Â&÷rævWDGG&–'WFR‚vFF×&VbÖ¶W’r’“²×Ð¢×Ò“°¢×Ò“°¢òò7BÖWfVçG26V7F–öâ—26öÆÆ6–&ÆRFöò(	B'WBF†R7Vr×6V7F–öâæ÷r6†&W0¢òòF†B6Æ72Â6òF&vWBF†R7BöæR7V6–f–6ÆÇ’ƒ¦æ÷B‚ç7Vr×6V7F–öâ’’à¢f"÷7D†VBÒ†÷7BçVW'•6VÆV7F÷"‚rçVWVR×6V7F–öâæ6öÆÆ6–&ÆS¦æ÷B‚ç7Vr×6V7F–öâ’çVWVR×6V2Ö†VBr“°¢–b…÷7D†VB’·°¢f"÷FövvÆU7BÒgVæ7F–öâ‚’·°¢f"6V2Ò÷7D†VBæ6Æ÷6W7B‚rçVWVR×6V7F–öâr“°¢ö×”WfVçG57D÷VâÒ6V2æ6Æ74Æ—7BçFövvÆR‚v6öÆÆ6VBr“°¢×Ó°¢÷7D†VBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂ÷FövvÆU7B“°¢÷7D†VBæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·²–b†Ræ¶W’ÓÓÒtVçFW"rÇÂRæ¶W’ÓÓÒrr’·²Rç&WfVçDFVfVÇB‚“²÷FövvÆU7B‚“²×Ò×Ò“°¢×Ð¢òòÆâ†VB—2VÖ&VFFVBBF†R&÷GFöÒ†&VÆ÷r7BWfVçG2’â&VæFW"—B–çFð¢òòF†R6÷2×Ææ†VBVÖ&VB(	B—Bv—&W2—G2÷vâG&—2ò&F"ò7VvvW7F–öà¢òò&÷w2„’vÒ–çFW&W7FVBòæ÷Bf÷"ÖR’ÂæB—G2–çG&ò—2F†R6V7F–öâF—f–FW"à¢&VæFW%Æä†VB‚“°¢WFFUf–Wt&FvW2‚“°¢×Ð ¢òòÖöçF‚Æ&VÂ²6‡&öæöÆöv–6Â6÷'B¶W’g&öÒâ÷4—FVÒw2•••”ÔÔDB6÷'Fà¢gVæ7F–öâ÷7VtÖöçF‚‡6÷'B’·°¢–b‚6÷'BÇÂ6÷'BãÒ“““““““’’&WGW&â·²¶W“¢wF&BrÂÆ&VÃ¢tFFRD$BrÂ6÷'C¢“““““““’×Ó°¢f"’ÒÖF‚æfÆö÷"‡6÷'Bò’ÂÖòÒÖF‚æfÆö÷"‚‡6÷'BR’ò“°¢–b†ÖòÂÇÂÖòâ"’&WGW&â·²¶W“¢wF&BrÂÆ&VÃ¢tFFRD$BrÂ6÷'C¢“““““““’×Ó°¢&WGW&â·²¶W“¢’²rÒr²ÖòÂÆ&VÃ¢õ5ôÔôåD…ôäÔU5¶ÖòÒÒ²rr²’Â6÷'C¢’¢²Öò×Ó°¢×Ð¢òò)H)HG&—6ÇW7FW&–ær(	Bv†Vâ–÷Rw&RÇ&VG’vö–ærFò6—G’Âv†BTÅ4R—2öà¢òòæV&'’v—F†–âfWrF—2Â6òöæRG&—6â6÷fW"GvòWfVçG2âæ6†÷&VBöà¢òòF†RWfVçG2–÷Rw&RGFVæF–ærò&öö¶VBBò–çFW&W7FVB–ã²6æF–FFR×W7@¢òò&R6Æ÷6R–â$õD‚Æ6R‡6ÖR÷"æV–v†&÷W&–ær6—G’Âf–F†RÖw26—G¢òò6ö÷&G2’æBF–ÖR‡v—F†–âã2F—2öb–÷W"æ6†÷"w2FFW2’à¢gVæ7F–öâö†fW'6–æT¶Ò†Â"’·°¢f""Òc3sÂFõ"ÒÖF‚å’òƒ°¢f"DÆBÒ†%³ÒÒ³Ò’¢Fõ"ÂDÆöâÒ†%³ÒÒ³Ò’¢Fõ#°¢f"‚ÒÖF‚ç6–â†DÆBò"’¢ÖF‚ç6–â†DÆBò"’°¢ÖF‚æ6÷2†³Ò¢Fõ"’¢ÖF‚æ6÷2†%³Ò¢Fõ"’¢ÖF‚ç6–â†DÆöâò"’¢ÖF‚ç6–â†DÆöâò"“°¢&WGW&â"¢"¢ÖF‚æ6–â„ÖF‚æÖ–âƒÂÖF‚ç7'B†‚’’“°¢×Ð¢gVæ7F–öâ÷6÷'EFôFFR‡2’·°¢–b‚2ÇÂ2ãÒ“““““““’’&WGW&âçVÆÃ°¢&WGW&âæWrFFR„ÖF‚æfÆö÷"‡2ò’ÂÖF‚æfÆö÷"‚‡2R’ò’ÒÂ‡2R’ÇÂ“°¢×Ð¢gVæ7F–öâöVæE6÷'Döb†—B’·°¢f"RÒ—BæVæEöFFS°¢–b†RbbõåÅÆG·³G×ÒÕÅÆG·³'×ÒÕÅÆG·³'×ÒòçFW7B†R’’·²&WGW&â‚¶Rç6Æ–6RƒÂB’’¢²‚¶Rç6Æ–6RƒRÂr’’¢²‚¶Rç6Æ–6Rƒ‚Â’“²×Ð¢&WGW&â—Bç6÷'C°¢×Ð¢òò'6ÖR†÷7BÂ6ÖR6—G’"f–ævW'&–çBâ6F6†W2æV"Ö–FVçF–6ÂWfVçG2F†@¢òòæÖRÖFVGWÖ—76W2&V6W6RF†V—"F—FÆW2F–ffW"(	BRærâ6÷&–æ—VÒw0¢òò$4DòFVfVç6Rb6V7W&—G’"Â$4Dòv÷fW&æÖVçB"æB$4Dòv6†–æwFöâBä2â##b ¢òò†ÆÂ4DòÂÆÂv6†–æwFöâD2ÂÆÂ6W#"Ó#2’6öÆÆ6RFòöæR6ÇW7FW"&÷rà¢òò¶W’Òf—'7BF—7F–æ7F—fRF—FÆRv÷&B‡F†R†÷7Bö'&æBÂRærâ&6Fò"’²F†P¢òò&W6öÇfVBÖ6ö÷&F–æFW2‡&÷VæFVBFòæ6—G’66ÆR’â6ö÷&G26öÖRg&öÒvVôö`¢òò(	BäõBF†R&rÆö6F–öâ7G&–ærÂv†÷6Rf—'7BFö¶Vâ—2ögFVâF†RfVçVP¢òò‚$ÆRÜ:—&–F–Vâv6†–æwFöî(
b"’Âv†–6‚v÷VÆBv—fRF†R6ÖRWfVçBF‡&VR¶W—2à¢òò6—G’ÖæÖRv÷&G2–âF†RF—FÆR&R6¶—VBv†Vâ–6¶–ærF†R'&æB‡6ð¢òò$&÷7FöâFFf÷'VÒ"g2$&÷7Föâ’7VÖÖ—B"FöâwB6öÆÆ6Röâ&&÷7Föâ"“°¢òòv†VâF—FÆR†2æòF—7F–æ7F—fRv÷&BÆVgBÂfÆÂ&6²FòF†RgVÆÂföÆFV@¢òòæÖR6òVç&VÆFVBWfVçG2&RæWfW"÷fW"ÖÖW&vVBà¢f"ô%$äEõ5DõÒ·²F†S£ÂæC£Âf÷#£Â“£ÂæçVÃ£Â7VÖÖ—C£Â6öæfW&Væ6S£À¢6öæc£Âf÷'VÓ£ÂW‡ó£Â6öæw&W73£ÂWfVçC£ÂWfVçG3£Âv÷&ÆC£ÂvÆö&Ã£À¢æF–öæÃ£Â–çFW&æF–öæÃ£Â–çFÃ£ÂF“£ÂF—3£ÂvVV³£Âæ÷'Fƒ£Â6÷WFƒ£À¢ÖW&–6£ÂÖW&–63£ÂWW&÷Vã£ÂWW&÷S£Â6–£ÂW6£ÂV³£ÂVÖV£À¢3£ÂÆFÓ£×Ó°¢gVæ7F–öâö'&æD¶W’†—BÂr’·°¢f"6—G•Fö·2Ò··×Ó°¢$föÆB…7G&–ær†—BæÆö6F–öâÇÂrr’²rr²7G&–ær†—Bæ6—G’ÇÂrr’¢ç&WÆ6R‚õµæ×£Ó’ÒörÂrr’ç7Æ—B‚õÅÇ2²ò’æf÷$V6‚†gVæ7F–öâ‡r’·²–b‡r’6—G•Fö·5·uÒÒ²×Ò“°¢f"v÷&G2Ò$föÆB†—BææÖRÇÂrr’ç&WÆ6R‚õµæ×£Ó’ÒörÂrr’ç7Æ—B‚õÅÇ2²ò’æf–ÇFW"„&ööÆVâ“°¢f"'&æBÒrs°¢f÷"‡f"’Ò²’Âv÷&G2æÆVæwFƒ²’²²’·°¢f"rÒv÷&G5¶•Ó°¢–b‡ræÆVæwF‚ãÒ2bbô%$äEõ5Dõ·uÒbbõåÅÆB²BòçFW7B‡r’bb6—G•Fö·5·uÒ’·²'&æBÒs²'&V³²×Ð¢×Ð¢–b‚'&æB’&WGW&âvæÖS¢r²$föÆB†—BææÖRÇÂrr“²òòæ÷F†–ærF—7F–æ7F—fRÓâFVGWRW†7BæÖW2öæÇ¢f"vVô¶W’Òrò„ÖF‚ç&÷VæB†u³Ò¢"’ò"’²rÂr²„ÖF‚ç&÷VæB†u³Ò¢"’ò"’¢sòs°¢&WGW&â'&æB²wÂr²vVô¶W“°¢×Ð¢òò)H)Hv÷fW&æÖVçBòW&÷76RbFVfVç6R—2¦–Òw2ÆæRöæÇ’)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòV&Æ–2×6V7F÷"ÂfVFW&ÂÂFVfVç6RæBdBWfVçG2&R¦–Òw2f—C²F†W’×W7@¢òòæ÷BÆV²–çFòç–öæRVÇ6Rw27VvvW7F–öç2ÂG&—&F6†W2÷"–çFW&W7B&V72à¢òòÖF6‚F†RWfVçBw2äÔR²7G'V7GW&VBG—RöæÇ’(	BäõB—G2&ÇW&"÷"GFVæFVP¢òòÆ—7C¢'&öBVçFW'&—6RWfVçG2…v÷&ÆB7VÖÖ—B’ÂÆöæFöâFV6‚vVV²(
b’ÖVçF–öà¢òò&v÷fW&æÖVçB"ÖöærÖç’GFVæFVRG—W2ÂæBÖF6†–ærF†÷6Rg&VR×FW‡Bf–VÆG0¢òòw&öævÇ’VÆÆVBã3ÆVv—BWfVçG2÷WBöbF†÷"w2f—BâG'VÇ’v÷bôdBWfVçB—0¢òòæÖVB2öæR‚$4Dòv÷fW&æÖVçB"Â$v÷eFV6‚7VÖÖ—B"Â$4DòFVfVç6R"’âæ÷FS ¢òò&v÷fW&ææ6R"—2FVÆ–&W&FVÇ’äõBÖF6†VB(	BF†Bw2âVçFW'&—6RF†VÖRà¢f"tõdDTbÒõÅÆ"†v÷fW&æÖVçGÆv÷fW&æÖVçFÇÆfVFW&ÇÆv÷gFV6‡ÆFVfVç6WÆFVfVæ6WÆÖ–Æ—F'—ÆW&÷76WÇv&f&WÆ†öÖVÆæGÆæF÷Æ&×—Ææg’•ÅÆ'ÅÅÆ'V&Æ–26V7F÷%ÅÆ'ÅÅÆ&æF–öæÂ6V7W&—G•ÅÆ'ÅÅÆ&&ÖVBf÷&6W5ÅÆ"ö“°¢gVæ7F–öâö—4v÷dFVb†—B’·°¢f"òÒ—Bç7F'Dö&¢ÇÂ··×Ó°¢&WGW&âtõdDTbçFW7B…¶—BææÖRÂòçG—RÂòæ–æGW7G'’Âòæ–7ö–æGW7G&–W5Òæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rr’“°¢×Ð¢òòv†òÖ’6VRv÷bôdBWfVçG3¢¦–Ò†—Bw2†—2f—B’æB7W÷'B„ævVÆô‡W&ÆW’À¢òòv†òÆâf÷"F†Rv†öÆRFVÒÂ¦–Ò–æ6ÇVFVB’âWfW'–öæRVÇ6R—2f–ÇFW&VBà¢gVæ7F–öâöv÷dö²†f—'7B’·²&WGW&âf—'7BÓÓÒv¦–ÒrÇÂ—57W÷'EW'6öâ†f—'7B“²×Ð ¢òò)H)H6öçFVçB6–Ö–Æ&—G’(	B&&V6W6R–÷Rw&R–çFW&W7FVB–â‚")H)H)H)H)H)H)H)H)H)H)H ¢òòÖF6‚öâv†BâWfVçB—2$õUB†–æGW7G'’²F÷–73¢fö7W5ö&V2ò&÷WBð¢òòG—R’æBt„ò—Bw2f÷"‡F&vWB&öÆW3¢G—–6ÅöGFVæFVW2’âV&—V—F÷W2v÷&G0¢òò‚&’"Â&VçFW'&—6R"Â&ÆVFW'2"(
b’&RG&÷VB6òÖF6†W2GW&âöâF†P¢òòF—7F–æ7F—fR6–væÂ†6Æ÷VBö†VÇF†6&Rö–ç7W&æ6Rö–FVçF—G“²&6†—FV7G2ð¢òòFWfVÆ÷W'2ö7GV&–W2’Âæ÷Böâv÷&G2WfW'’WfVçB6†&W2à¢f"õ4”Õõ5DõÒ·²F†S£ÂæC£Âf÷#£Âv—Fƒ£Âg&öÓ£ÂÆÃ£ÂæWs£Â–÷W#£Â÷W#£À¢F†V—#£ÂF†—3£ÂF†C£Â–çFó£Â7&÷73£Â÷fW#£Â÷F†W#£ÂÖ÷&S£ÂÖ÷7C£ÂÇ6ó£À¢ÇW3£Âv†ó£Â†÷s£Âv‡“£Âv†C£Âv†Vã£Âv†W&S£ÂWfVçC£ÂWfVçG3£Â7VÖÖ—C£À¢7VÖÖ—G3£Â6öæfW&Væ6S£Â6öæfW&Væ6W3£Âf÷'VÓ£Âf÷'V×3£ÂW‡ó£Â6öæw&W73£À¢æçVÃ£ÂvÆö&Ã£Âv÷&ÆC£ÂæF–öæÃ£Â–çFW&æF–öæÃ£Â6W&–W3£ÂVF—F–öã£ÂF“£À¢F—3£ÂvVV³£ÂÆVFW'3£ÂÆVFW#£ÂÆVFW'6†—£ÂW†V7WF—fS£ÂW†V7WF—fW3£À¢&öfW76–öæÃ£Â&öfW76–öæÇ3£ÂF—&V7F÷#£ÂF—&V7F÷'3£ÂÖævW#£ÂÖævW'3£À¢ÖævVÖVçC£Âöff–6W#£Âöff–6W'3£Â†VC£Â†VG3£Â6Væ–÷#£Â§Væ–÷#£ÂFV6—6–öã£À¢Ö¶W#£ÂÖ¶W'3£ÂÖ¶–æs£ÂFV×3£ÂFVÓ£ÂV÷ÆS£ÂGFVæFVW3£ÂFVÆVvFW3£À¢&7F—F–öæW#£Â&7F—F–öæW'3£Â7V6–Æ—7C£Â7V6–Æ—7G3£ÂW‡W'C£ÂW‡W'G3£À¢7F¶V†öÆFW#£Â7F¶V†öÆFW'3£Â&W&W6VçFF—fS£Â&W&W6VçFF—fW3£ÂW'6öææVÃ£À¢7Ffc£ÂÖVÖ&W'3£Â6öÖ×Væ—G“£ÂæWGv÷&³£Â'W6–æW73£Â'W6–æW76W3£Â6ö×ç“£À¢6ö×æ–W3£Â÷&væ—¦F–öã£Â÷&væ—¦F–öç3£Â÷&væ—6F–öã£Â–æGW7G'“£Â–æGW7G&–W3£À¢6V7F÷#£Â6V7F÷'3£ÂÖ&¶WC£ÂÖ&¶WG3£ÂVçFW'&—6S£ÂVçFW'&—6W3£ÂFV6†æöÆöw“£À¢FV6†æöÆöv–W3£ÂFV6ƒ£ÂF–v—FÃ£Â–ææ÷fF–öã£Â7G&FVw“£Â7G&FVv–3£Â6öÇWF–öç3£À¢6öÇWF–öã£Â–æ6ÇVF–æs£Âf&–÷W3£Â&ævS£ÂÆ&vS£ÂÆ&vW7C£ÂÆVF–æs£ÂF÷£Â¶W“£À¢Ö¦÷#£Â6WfW&Ã£ÂÖç“£ÂGFVæC£ÂGFVæF–æs£Â¦ö–ã£ÂfVGW&W3£ÂfVGW&–æs£À¢fö7W3£Âfö7W6VC£Â&V£Â&V3£Â“£Â'F–f–6–Ã£Â–çFVÆÆ–vVæ6S£ÂFF£À¢G&ç6f÷&ÖF–öã£ÂgWGW&S£ÂæW‡C£ÂvVã£ÂvVæW&F–öã£×Ó°¢gVæ7F–öâ÷6–ÕFö¶Vç2‡2’·°¢f"÷WBÒ··×Ó°¢$föÆB…7G&–ær‡2ÇÂrr’’ç&WÆ6R‚õµæ×£Ó’ÒörÂrr’ç7Æ—B‚õÅÇ2²ò’æf÷$V6‚†gVæ7F–öâ‡r’·°¢–b‡ræÆVæwF‚ãÒBbbõ4”Õõ5Dõ·uÒ’÷WE·uÒÒ°¢×Ò“°¢&WGW&â÷WC°¢×Ð¢gVæ7F–öâö6öçFVçE&öf–ÆR†—B’·°¢f"òÒ—Bç7F'Dö&¢ÇÂ··×Ó°¢òòv†B—Bw2&÷WB†æÖR²fö7W2÷F÷–72²G—Rö–æGW7G'’’æBt„ò—Bw2f÷ ¢òò†VF–Væ6R&öÆW2²v†òw27ö¶VâöGFVæFVBF†W&R’âæÖR—2–æ6ÇVFVB6ò¢òò6W&–W2ö'&æBW'6öâ¶VW26†÷v–ærWf÷"„4DòÂÖöæW“#ó#Âv'FæW"(
b¢òò66÷&W22fÖ–Æ–#²7B7V¶W'26–væÂF†R&ööÒw26Æ–'&Rà¢&WGW&â·°¢F÷–73¢÷6–ÕFö¶Vç2…¶—BææÖRÂòæfö7W5ö&V2Âòæ&÷WBÂòçG—RÂòæ–æGW7G'•Òæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rr’’À¢&öÆW3¢÷6–ÕFö¶Vç2…¶òçG—–6ÅöGFVæFVW2Âòç7E÷7V¶W'5Òæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rr’¢×Ó°¢×Ð¢gVæ7F–öâö÷fW&Æâ†Â"’·²f"âÒ²f÷"‡f"²–â’·²–b†%¶µÒ’â²³²×Ò&WGW&âã²×Ð¢òò66÷&RÒ†÷r×V6‚GvòWfVçG26†&Röâ–æGW7G'’÷F÷–72‡vV–v‡FVB"’²&öÆW0¢òò‡vV–v‡FVB’â&WGW&ç2F†R6ö×öæVçG26ò6ÆÆW'26âvFRöâ&VÀ¢òò–æGW7G'’ÖF6‚Âæ÷B§W7B6÷WÆRöb7G&’&öÆRv÷&G2à¢gVæ7F–öâ÷6–Õ66÷&R‡Â"’·°¢f"BÒö÷fW&Æâ‡çF÷–72Â"çF÷–72“°¢f""Òö÷fW&Æâ‡ç&öÆW2Â"ç&öÆW2“°¢&WGW&â·²C¢BÂ#¢"Â66÷&S¢B¢"²"×Ó°¢×Ð¢òò)H)HF7FR&öf–ÆR(	Bv†BW'6öâ7GVÆÇ’FöW2)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòF†R7G&öævW7BW'6öæÆ—¦F–öâ6–væÂ—2W'6öâw2÷vâG&6²&V6÷&C ¢òòWfVçG2F†W’wfREDTäDTB÷"5ô´TâB‡vV–v‡B"Â7B–æ6ÇVFVB(	BF†B•0¢òòF†V—"†—7F÷'’’æBWfVçG2F†W’wfRfÆvvVB”åDU$U5DTB–â‡vV–v‡B’âvP¢òò67V×VÆFRF†R–æGW7G'’÷F÷–2²&öÆRFö¶Vç27&÷72ÆÂöbF†VÒÂ6ò¢òò6æF–FFRF†BÆöö·2Æ–¶Rv†BF†W’¶VW6†÷v–ærWf÷"66÷&W2†–v‚à¢òò66†VBÂFö¶Væ—¦VB×’Õ&öf–ÆRFW‡BW"W'6öâ‡·²f—'7C¢··F÷–72Â&öÆW7×Ò×Ò’à¢òò÷VÆFVB'’öÆöE&öf–ÆUF7FR‚’g&öÒFVÕ÷&öf–ÆW3²föÆFVB–çFòF7FR6ð¢òò7VvvW7F–öç2vWBÔõ$RF–Æ÷&VBF†RÖ÷&R6öÖVöæRw&—FW2–âF†V—"&öf–ÆRà¢f"÷&öf–ÆUF7FT66†RÒçVÆÃ°¢gVæ7F–öâ÷F7FU&öf–ÆR‡v†ò’·°¢f"F÷–72Ò··×ÒÂ&öÆW2Ò··×ÒÂâÒ°¢–b‚v†ò’&WGW&â·²F÷–73¢F÷–72Â&öÆW3¢&öÆW2Â†3¢fÇ6R×Ó°¢÷4ÆÄ—FV×2‚’æf÷$V6‚†gVæ7F–öâ†—B’·°¢f"rÒ°¢–b‚†—BæGFVæFVW2ÇÂµÒ’ç6öÖR†gVæ7F–öâ†’·²&WGW&â$föÆB†’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒv†ó²×Ò’’rÒ#°¢VÇ6R–b†—Bç7FvW2æ–æFW„öb‚t&öö¶VBr’ÓÒÓbb$föÆB†—Bç7V¶W"ÇÂrr’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒv†ò’rÒ#°¢VÇ6R–b‚†—Bæ–çFW&W7FVBÇÂµÒ’ç6öÖR†gVæ7F–öâ‡‚’·²&WGW&â$föÆB‡‚’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒv†ó²×Ò’’rÒ°¢–b‚r’&WGW&ã°¢â²³°¢f"Òö6öçFVçE&öf–ÆR†—B“°¢f÷"‡f"B–âçF÷–72’·²F÷–75·EÒÒ‡F÷–75·EÒÇÂ’²s²×Ð¢f÷"‡f""–âç&öÆW2’·²&öÆW5·%ÒÒ‡&öÆW5·%ÒÇÂ’²s²×Ð¢×Ò“°¢òòF†V—"÷vâv÷&G2†&–òò7V¶–ærF÷–72ò7BFÆ·2òF&vWF–æræ÷FW2¢òò&RF†RÖ÷7BW‡Æ–6—B&VfW&Væ6R6–væÂ(	BvV–v‡B†–v†W7Bà¢f"BÒ÷&öf–ÆUF7FT66†Rbb÷&öf–ÆUF7FT66†U·v†õÓ°¢–b‡B’·°¢f÷"‡f"C"–âBçF÷–72’·²F÷–75·C%ÒÒ‡F÷–75·C%ÒÇÂ’²3²×Ð¢f÷"‡f""–âBç&öÆW2’·²&öÆW5·%ÒÒ‡&öÆW5·%ÒÇÂ’²3²×Ð¢–b„ö&¦V7Bæ¶W—2‡BçF÷–72’æÆVæwF‚ÇÂö&¦V7Bæ¶W—2‡Bç&öÆW2’æÆVæwF‚’â²³°¢×Ð¢&WGW&â·²F÷–73¢F÷–72Â&öÆW3¢&öÆW2Â†3¢ââ×Ó°¢×Ð¢òò†÷r×V6‚6æF–FFR&W6VÖ&ÆW2F†RW'6öâw2F7FR†67V×VÆFVBvV–v‡G2’à¢gVæ7F–öâ÷F7FU66÷&R‡F7FRÂ—B’·°¢–b‚F7FRÇÂF7FRæ†2’&WGW&â°¢f"Òö6öçFVçE&öf–ÆR†—B’Â2ÒÂC°¢f÷"‡B–âçF÷–72’·²–b‡F7FRçF÷–75·EÒ’2³ÒF7FRçF÷–75·EÒ¢#²×Ð¢f÷"‡B–âç&öÆW2’·²–b‡F7FRç&öÆW5·EÒ’2³ÒF7FRç&öÆW5·EÓ²×Ð¢&WGW&â3°¢×Ð¢òòVÆÂV6‚FVÖÖFRw2×’Õ&öf–ÆRFW‡B†&–òò7V¶–ærF÷–72ò7BFÆ·2ð¢òòF&vWF–æræ÷FW2’æBFö¶Væ—¦R—B–çFòF†RF7FR66†RÂ6òF†RÖ÷&R6öÖVöæP¢òòf–ÆÇ2–âF†V—"&öf–ÆRÂF†RÖ÷&RF–Æ÷&VBF†V—"7VvvW7F–öç2&V6öÖRâ'Vç0¢òò&W7BÖVff÷'B†æòFVÕ÷&öf–ÆW2F&ÆR–WBÓâ7F—2V×G’“²&R×&VæFW"gFW"à¢gVæ7F–öâöÆöE&öf–ÆUF7FR†6"’·°¢–b‡G—Vöb6"ÓÓÒwVæFVf–æVBrÇÂ6"ÇÂ6"æg&öÒ’·²–b†6"’6"‚“²&WGW&ã²×Ð¢6"æg&öÒ‚wFVÕ÷&öf–ÆW2r’ç6VÆV7B‚r¢r’çF†Vâ†gVæ7F–öâ‡"’·°¢f"66†RÒ··×Ó°¢òò&r&÷w2Â¶W–VB'’f—'7BæÖR(	BF†R÷WG&V6‚6ö×÷6W"&VG2V6€¢òò7V¶W"w2F÷–72æBævVÆw26fVBVÖ–ÂFV×ÆFW2g&öÒ†W&R&F†W ¢òòF†âfWF6†–ærF†R6ÖRF&ÆR6V6öæBF–ÖRà¢v–æF÷råö%&öf–ÆU&÷w2Ò··×Ó°¢‚‡"bb"æFF’ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ‡&÷r’·°¢f"v†òÒ$föÆB…7G&–ær‡&÷rçW'6öâÇÂ&÷ræF—7Æ•öæÖRÇÂrr’’ç7Æ—B‚õÅÇ2²ò•³Ó°¢–b‚v†ò’&WGW&ã°¢v–æF÷råö%&öf–ÆU&÷w5·v†õÒÒ&÷s°¢f"&Æö"Ò·&÷ræ&–òÂ&÷rçF÷–72Â&÷rç7E÷FÆ·2Â&÷rææ÷FW5Òæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rr“°¢–b‚&Æö"çG&–Ò‚’’&WGW&ã°¢66†U·v†õÒÒ·²F÷–73¢÷6–ÕFö¶Vç2†&Æö"’Â&öÆW3¢÷6–ÕFö¶Vç2…·&÷rçF÷–72Â&÷rç7E÷FÆ·5Òæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rr’’×Ó°¢×Ò“°¢÷&öf–ÆUF7FT66†RÒ66†S°¢–b†6"’6"‚“°¢×ÒÂgVæ7F–öâ‚’·²÷&öf–ÆUF7FT66†RÒ÷&öf–ÆUF7FT66†RÇÂ··×Ó²–b†6"’6"‚“²×Ò“°¢×Ð¢òò&V6VçB&öf–ÆRÖÖFW&–ÂWÆöG2†Æ7BrF—2’Âf÷"ævVÆw2$–âF†RÆ7@¢òòvVV²"(	B6ò6†R6VW2v†Vâ6öÖVöæRFG2&–òòFV6²ò†VG6†÷BòÆ–æ²à¢òò7W÷'BÖöæÇ’²ÆöFVBöæ6RW"6W76–öâ‡7F÷&vR†2æò&V7W'6—fRÆ—7BÂ6ð¢òòF†—2—2W'6öç2‚ÖFW&–Â×6Æ÷G3²¶WBöfbF†R†÷B&VæFW"F‚’à¢gVæ7F–öâöÆöE&V6VçEWÆöG2†6"’·°¢–b‡G—Vöb6"ÓÓÒwVæFVf–æVBrÇÂ6"ÇÂ6"ç7F÷&vRÇÂ—57W÷'EW'6öâ†vWD6öÆÆ$æÖR‚’ÇÂrr’’·²÷&V6VçEWÆöG2ÒµÓ²–b†6"’6"‚“²&WGW&ã²×Ð¢f"7WFöfbÒæWrFFR„FFRææ÷r‚’Òr¢ƒcC’çFô•4õ7G&–ær‚“°¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æÆ—7B‚rrÂ·²Æ–Ö—C¢#×Ò’çF†Vâ†gVæ7F–öâ‡"’·°¢f"W'6öç2Ò‚‚‡"bb"æFF’ÇÂµÒ’æÖ†gVæ7F–öâ†b’·²&WGW&âbææÖS²×Ò¢æf–ÇFW"†gVæ7F–öâ†â’·²&WGW&ââbbâÓÒræV×G”föÆFW%Æ6V†öÆFW"s²×Ò’“°¢f"÷WBÒµÒÂVæF–ærÒW'6öç2æÆVæwF‚¢$ôd”ÄUôÔDU$”Å2æÆVæwFƒ°¢–b‚VæF–ær’·²÷&V6VçEWÆöG2ÒµÓ²–b†6"’6"‚“²&WGW&ã²×Ð¢gVæ7F–öâöFöæR‚’·²–b‚Ò×VæF–ærÓÓÒ’·²÷&V6VçEWÆöG2Ò÷WC²–b†6"’6"‚“²×Ò×Ð¢W'6öç2æf÷$V6‚†gVæ7F–öâ‡²’·°¢$ôd”ÄUôÔDU$”Å2æf÷$V6‚†gVæ7F–öâ†Ò’·°¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æÆ—7B‡²²ròr²Òæ²Â·²Æ–Ö—C¢S×Ò’çF†Vâ†gVæ7F–öâ‡'"’·°¢‚‚‡'"bb'"æFF’ÇÂµÒ’’æf÷$V6‚†gVæ7F–öâ†b’·°¢–b‚bææÖRÇÂbææÖRÓÓÒræV×G”föÆFW%Æ6V†öÆFW"r’&WGW&ã°¢f"BÒbæ7&VFVEöBÇÂ†bæÖWFFFbbbæÖWFFFæÆ7DÖöF–f–VB’ÇÂrs°¢–b†BbbBãÒ7WFöfb’÷WBçW6‚‡·²v†ó¢²Â6C¢Òæ²Â6DÆ&VÃ¢ÒæÆ&VÂÂæÖS¢bææÖRÂC¢B×Ò“°¢×Ò“°¢öFöæR‚“°¢×ÒÂöFöæR“°¢×Ò“°¢×Ò“°¢×ÒÂgVæ7F–öâ‚’·²÷&V6VçEWÆöG2ÒµÓ²–b†6"’6"‚“²×Ò“°¢×Ð¢òò)H)H†öÖR&6W2(	BG&—&F6†–ær—26Ö'FW"&÷WBF–ÖR²F—7Fæ6R)H)H)H)H)H)H ¢òòV6‚FVÖÖFRw2†öÖR6—G’âF†Rf'F†W"âæ6†÷"WfVçB—2g&öÒ†öÖRÂF†P¢òòv–FW"F†R&F6‚æWC¢Æö6ÂWfVçB&F6†W2F–v‡B†F’÷"GvòÂ6ÖP¢òòÖWG&ò“²ÆöærÖ†VÂG&—&F6†W2F†Rv†öÆR&Vv–öâf÷"ã"vVV·2†Ç&VG¢òòfÆWrFò—7Fæ'VÂ(	B&öÖRF†RæW‡BvVV²—2v÷'F‚F†RFWF÷W"’â7W÷'B¶W—0¢òòÖFòå”2'WBvòVçW6VB‡F†V—"6ÇW7FW'2&RW"Ö÷væW"’à¢f"„ôÔUô$4RÒ·°¢F†÷#¢³CãsÂÓsBãÒÂòòæWr–÷&°¢¦öS¢³CãsÂÓsBãÒÂòòæWr–÷&°¢fW&Ö¢³Cãs"ÂÓsBãUÒÂòò¦W'6W’6—G¢ævVÆ¢³CãsÂÓsBãÒÂòòæWr–÷&°¢‡W&ÆW“¢³CãsÂÓsBãÒÂòòæWr–÷&°¢¦W&öÖS¢³SãSÂÓã5ÒÂòòÆöæFöà¢6&Æ÷3¢³‚ãC’ÂÓc’ã“5ÒÂòò6çFòFöÖ–ævð¢¦–Ó¢³3‚ã“ÂÓsrãEÒòòv6†–æwFöâD0¢×Ó°¢gVæ7F–öâö†öÖTöb‡v†ò’·²&WGW&â„ôÔUô$4U·v†õÒÇÂçVÆÃ²×Ð¢òò†÷rv–FRFò67BF†R&F6‚æWBÂ'’†÷rf"F†Ræ6†÷"—2g&öÒ†öÖR†¶Ò’à¢gVæ7F–öâ÷G&—v–æF÷r††öÖTF—7B’·°¢–b††öÖTF—7BâC’&WGW&â·²Ö„¶Ó¢cÂÖ„v¢"×Ó²òò–çFW&6öçF–æVçFÂ(	B&F6‚F†R&Vv–öà¢–b††öÖTF—7Bâ#’&WGW&â·²Ö„¶Ó¢cSÂÖ„v¢b×Ó²òò7&÷72Ö6÷VçG'’òf"FöÖW7F–0¢&WGW&â·²Ö„¶Ó¢3#ÂÖ„v¢2×Ó²òòæV"†öÖR(	BF–v‡@¢×Ð¢f"4ÔUô4•E•ô´ÒÒC²òòv—F†–âöæRÖWG&ó¢6ÖRÖF’—2Fö&ÆS²7&÷726—F–W2—B—6âw@¢òòv†÷6RÆ–æWWG&—fW2Æâ†VBâæÖVBFVÖÖFR6VW2F†V—"÷vã²7W÷'@¢òò„ævVÆô‡W&ÆW’’Æâf÷"WfW'–öæRÂ6òF†W’vWBF†Rv†öÆRFVÒw2(	BWfW'¢òòW'6öæf—'7BæÖRâ&WGW&ç2µÒv†VâF†W&Rw2æò6–væVBÖ–âæÖRà¢òòv†òF†RFVÒ7GVÆÇ’WG2öâ7FvRÂÖ÷7BögFVâf—'7B(	BF†÷"ÆVG0¢òò„‡W&ÆW’##bÓrÓ3’â7W÷'B6VW2WfW'’W'6öæÂ'WB–âD„•2÷&FW"&F†W ¢òòF†âv†FWfW"÷&FW"W'6öæ2æ§6öâ†Vç2Fò&Rw&—GFVâ–âà¢f"Äåôõ$DU"Ò²wF†÷"rÂwfW&ÖrÂv¦W&öÖRrÂv¦öRrÂv6&Æ÷2rÂv¦–ÒrÂw66÷GBuÓ°¢gVæ7F–öâÆå6÷'B†æÖW2’·°¢&WGW&âæÖW2ç6Æ–6R‚’ç6÷'B†gVæ7F–öâ†Â"’·°¢f"–ÒÄåôõ$DU"æ–æFW„öb…7G&–ær†’çFôÆ÷vW$66R‚’“°¢f"–"ÒÄåôõ$DU"æ–æFW„öb…7G&–ær†"’çFôÆ÷vW$66R‚’“°¢–b†–ÓÓÒÓ’–Ò““²–b†–"ÓÓÒÓ’–"Ò““°¢&WGW&â–Ò–"ÇÂ7G&–ær†’æÆö6ÆT6ö×&R…7G&–ær†"’“°¢×Ò“°¢×Ð¢v–æF÷ræ%Æä÷&FW"ÒÆå6÷'C°¢gVæ7F–öâ÷Æä÷væW'2‚’·°¢f"ÖRÒvWD6öÆÆ$æÖR‚’ÇÂrs°¢f"f—'7BÒ$föÆB†ÖR’ç7Æ—B‚õÅÇ2²ò•³Ó°¢–b‚f—'7B’&WGW&âµÓ°¢–b…öÖW&vVEFVÕf–Wr‚’’&WGW&âÆå6÷'B„ö&¦V7Bæ¶W—2‡v–æF÷rä%õU%4ôä2ÇÂ··×Ò’“°¢&WGW&â¶f—'7EÓ°¢×Ð¢òòF†R6öÖÖ—GFVB×G&fVÂ&öÆRv—fVâW'6öâ†2f÷"âWfVçB†G&—fW2G&— ¢òò&F6†–ær’â–çFW&W7FVB—2äõB†W&R(	BF†Bw2Ö–&RÂ†æFÆVB'’6öçFVç@¢òò&V72Âæ÷B'–÷Rw&RÇ&VG’vö–ær"à¢gVæ7F–öâ÷G&fVÅ&öÆR†—BÂv†ò’·°¢–b‚†—BæGFVæFVW2ÇÂµÒ’ç6öÖR†gVæ7F–öâ†’·²&WGW&â$föÆB†’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒv†ó²×Ò’’&WGW&âvGFVæF–ærs°¢–b†—Bç7FvW2æ–æFW„öb‚t&öö¶VBr’ÓÒÓbb$föÆB†—Bç7V¶W"ÇÂrr’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒv†ò’&WGW&âw7V¶–ærBs°¢&WGW&âçVÆÃ°¢×Ð¢gVæ7F–öâöç•&öÆR†—BÂv†ò’·°¢&WGW&â÷G&fVÅ&öÆR†—BÂv†ò’ÇÀ¢‚†—Bæ–çFW&W7FVBÇÂµÒ’ç6öÖR†gVæ7F–öâ†â’·²&WGW&â$föÆB†â’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒv†ó²×Ò’òv–çFW&W7FVB–âr¢çVÆÂ“°¢×Ð¢gVæ7F–öâ÷G&—6ÇW7FW'2‚’·°¢f"÷væW'2Ò÷Æä÷væW'2‚“°¢–b‚÷væW'2æÆVæwF‚’&WGW&âµÓ°¢f"7W÷'BÒöÖW&vVEFVÕf–Wr‚“°¢f"$GBÒö6ö×Æ–çÇ&VwVÆGÇ&VwFV6‡ÆvG'ÅÅÆ&VF—Bö“°¢f"6¶—2Ò÷7Vu6¶—2‚“°¢f"D•ôÕ2ÒƒcC°¢f"ÆÂÒ÷4ÆÄ—FV×2‚“°¢òòæ6†÷'2Ò6öÖÖ—GFVBG&fVÂ†GFVæF–ærò&öö¶VB’f÷"ç’÷væW"âöæRæ6†÷ ¢òòW"†WfVçBÂ÷væW"“²7W÷'BW6W"6VW2WfW'’FVÖÖFRw2G&—2Æ&VÆÆV@¢òòv—F‚v†òw2vö–ærà¢f"æ6†÷'2ÒµÓ°¢ÆÂæf÷$V6‚†gVæ7F–öâ†—B’·°¢–b†—Bç7BÇÂ—Bæ†–FFVâ’&WGW&ã°¢–b‚—Bç6÷'BÇÂ—Bç6÷'BãÒ“““““““’’&WGW&ã°¢òòvVòÖ’&RçVÆÂ†âVæÖ&ÆRÆö6F–öâÆ–¶R$—7Fæ'VÂ"&Vf÷&R—Bv0¢òò–âF†R6ö÷&BF&ÆR’(	BvR7F–ÆÂÄ•5BF†RG&—ÂvR§W7B6âwB&F6€¢òòæV&'’WfVçG2öçFò—Bà¢f"rÒvVôöb†—B“°¢÷væW'2æf÷$V6‚†gVæ7F–öâ‡v†ò’·°¢f""Ò÷G&fVÅ&öÆR†—BÂv†ò“²–b‚"’&WGW&ã°¢æ6†÷'2çW6‚‡·²—C¢—BÂv†ó¢v†òÂ&öÆS¢"ÂvVó¢rÂ7F'DC¢÷6÷'EFôFFR†—Bç6÷'B’ÂVæDC¢÷6÷'EFôFFR…öVæE6÷'Döb†—B’’×Ò“°¢×Ò“°¢×Ò“°¢–b‚æ6†÷'2æÆVæwF‚’&WGW&âµÓ°¢æ6†÷'2ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&âæ—Bç6÷'BÒ"æ—Bç6÷'C²×Ò“°¢f"6ÇW7FW'2ÒµÒÂW6VD¶W—2Ò··×Ó°¢æ6†÷'2æf÷$V6‚†gVæ7F–öâ†æ6†÷"’·°¢–b‚æ6†÷"ç7F'DBÇÂæ6†÷"æVæDB’&WGW&ã°¢f"æV"ÒµÓ°¢òòöæÇ’Æöö²f÷"æV&'’WfVçG2Fò&F6‚v†VâvR¶æ÷rt„U$RF†RG&——2à¢òòG&—v—F‚æò&W6öÇf&ÆR6ö÷&G27F–ÆÂ6†÷w2(	B§W7Bv—F‚æ÷F†–æp¢òò&F6†VBöçFò—B‡6òWfW'’6öÖÖ—GFVBG&——2Æ—7FVB’à¢–b†æ6†÷"ævVò’·°¢f"÷væW$v÷bÒöv÷dö²†æ6†÷"çv†ò“²òòv÷bôdBæV&'’öæÇ’f÷"¦–Òw2†÷"7W÷'Bw2’G&—0¢òòv–FVâF†R&F6‚v–æF÷rv—F‚†÷rf"F†—2G&—Ç&VG’—2g&öÒ†öÖRà¢f"†öÖRÒö†öÖTöb†æ6†÷"çv†ò“°¢f"v–âÒ÷G&—v–æF÷r††öÖRòö†fW'6–æT¶Ò††öÖRÂæ6†÷"ævVò’¢“°¢f"6VVäæÖRÒ··×Ó°¢ÆÂæf÷$V6‚†gVæ7F–öâ†—B’·°¢–b†—BÓÓÒæ6†÷"æ—B’&WGW&ã°¢–b†—Bç7BÇÂ—Bæ†–FFVâÇÂ—BçVWVUöF—6Ö—76VB’&WGW&ã°¢–b†—Bç7FvW2æÆVæwF‚’&WGW&ã²òòÇ&VG’–âF†R—VÆ–æP¢–b„$GBçFW7B†—BææÖR’’&WGW&ã°¢–b…öç•&öÆR†—BÂæ6†÷"çv†ò’’&WGW&ã²òòÇ&VG’öâF†—2W'6öâw2Æ—7@¢–b‚÷væW$v÷bbbö—4v÷dFVb†—B’’&WGW&ã²òòv÷bôdB—2¦–Òw2ÆæP¢–b…öÆæt&Æö6¶VB†æ6†÷"çv†òÂ—B’’&WGW&ã²òòæöâÔVævÆ—6‚(	BFöâwB&F6‚—BöçFòF†V—"G&— ¢–b‡6¶—5µ÷7Vu6¶—–B†—Bæ¶–æBÂ—Bæ¶W’•Ò’&WGW&ã°¢–b…÷fWFöVD—FVÒ†—B’’&WGW&ã²òòÆV&æVB&æ÷Bf÷"ÖR"GFW&à¢–b‡W6VD¶W—5¶æ6†÷"çv†ò²wÂr²—Bæ¶–æB²s¢r²—Bæ¶W•Ò’&WGW&ã²òòFöâwB&WVBv—F†–âF†—2W'6öâw2G&—0¢f"æÒÒ$föÆB†—BææÖR“²–b‡6VVäæÖU¶æÕÒ’&WGW&ã²òò6öÆÆ6RGWÆ–6FRWfVçG0¢f"rÒvVôöb†—B“²–b‚r’&WGW&ã°¢f"¶ÒÒö†fW'6–æT¶Ò†æ6†÷"ævVòÂr“°¢–b†¶Òâv–âæÖ„¶Ò’&WGW&ã°¢f"72Ò÷6÷'EFôFFR†—Bç6÷'B’Â6RÒ÷6÷'EFôFFR…öVæE6÷'Döb†—B’“°¢–b‚72ÇÂ6R’&WGW&ã°¢f"vÒÖF‚æÖ‚ƒÂÖF‚æ6V–Â‚†72Òæ6†÷"æVæDB’òD•ôÕ2’ÂÖF‚æ6V–Â‚†æ6†÷"ç7F'DBÒ6R’òD•ôÕ2’“°¢–b†vâv–âæÖ„v’&WGW&ã°¢òò6âwB&R–âGvòF–ffW&VçB6—F–W2öâF†R6ÖRF’(	BöæÇ’6ÖRÖÖWG&ð¢òòWfVçG2Ö’÷fW&Æ–âF–ÖRâ7&÷726—F–W2Â&WV—&RF’&WGvVVâà¢–b†¶ÒãÒ4ÔUô4•E•ô´ÒbbvÓÓÒ’&WGW&ã°¢6VVäæÖU¶æÕÒÒ°¢æV"çW6‚‡·²—C¢—BÂv¢vÂ¶Ó¢¶ÒÂvVó¢r×Ò“°¢×Ò“°¢–b†æV"æÆVæwF‚’·°¢òò&æ²v†BFò7GVÆÇ’7W&f6S¢G&—&F6†W2„äDeTÂÂæ÷B¢òò6öçF–æVçBâfÆöBWfVçG2F†BÖF6‚F†Ræ6†÷"w2F÷–2‡F÷–0¢òò÷fW&ÆãÒ"’ÂF†VâF†R6Æ÷6W7BÂF†VâF†R6ööæW7Bà¢f"&öbÒö6öçFVçE&öf–ÆR†æ6†÷"æ—B“°¢æV"æf÷$V6‚†gVæ7F–öâ†â’·²âç&VÂÒ÷6–Õ66÷&R†&öbÂö6öçFVçE&öf–ÆR†âæ—B’’çC²×Ò“°¢æV"ç6÷'B†gVæ7F–öâ†Â"’·°¢f"&Òç&VÂãÒ"ò¢Â&"Ò"ç&VÂãÒ"ò¢°¢&WGW&â&Ò&"ÇÂæ¶ÒÒ"æ¶ÒÇÂævÒ"æv°¢×Ò“°¢òò6öÆÆ6R6ÖRÖ†÷7B÷6ÖRÖ6—G’æV"ÖGWW2„4DòFVfVç6Rb6V7W&—G’ð¢òò4Dòv÷fW&æÖVçBò4Dòv6†–æwFöâBä2âÓâöæR&÷r’à¢f"6VVä'&æBÒ··×Ó°¢6VVä'&æEµö'&æD¶W’†æ6†÷"æ—BÂæ6†÷"ævVò•ÒÒ°¢æV"ÒæV"æf–ÇFW"†gVæ7F–öâ†â’·°¢f"&²Òö'&æD¶W’†âæ—BÂâævVò“°¢–b‡6VVä'&æE¶&µÒ’&WGW&âfÇ6S°¢6VVä'&æE¶&µÒÒ²&WGW&âG'VS°¢×Ò“°¢æV"ÒæV"ç6Æ–6RƒÂR“²òò6(	BöæRG&—6÷fW'2fWrÂæ÷BGvVçG¢æV"ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&âæ—Bç6÷'BÒ"æ—Bç6÷'C²×Ò“²òò6†÷rF†R¶WBfWr6‡&öæöÆöv–6ÆÇ¢æV"æf÷$V6‚†gVæ7F–öâ†â’·²W6VD¶W—5¶æ6†÷"çv†ò²wÂr²âæ—Bæ¶–æB²s¢r²âæ—Bæ¶W•ÒÒ²×Ò“°¢×Ð¢×Ð¢òòW6‚UdU%’6öÖÖ—GFVBG&—(	BWfVâ6öÆòöæRv—F‚æ÷F†–æræV&'’(	B6ð¢òò$&F6‚–÷W"G&—2"Æ—7G2ÆÂöbW'6öâw2GFVæF–ær÷7V¶–ærWfVçG2à¢6ÇW7FW'2çW6‚‡·²æ6†÷#¢æ6†÷"æ—BÂv†ó¢æ6†÷"çv†òÂ7W÷'C¢7W÷'BÂ&öÆS¢æ6†÷"ç&öÆRÂæV#¢æV"×Ò“°¢×Ò“°¢&WGW&â6ÇW7FW'3°¢×Ð¢òò$&V6W6R–÷Rw&R–çFW&W7FVB–â‚"(	B6öçFVçB&V6öÖÖVæFF–öç2âf÷"V6‚WfVç@¢òòâ÷væW"—2”åDU$U5DTB–â†Ö–&RÂæ÷B6öÖÖ—GFVBG&fVÂ’Â7W&f6RW6öÖ–æp¢òòWfVçG2F†BÖF6‚öâ–æGW7G'’÷F÷–72²F&vWB&öÆW2Âv†W&WfW"F†W’&Rà¢òòF†—2—2F†R6öçFVçB6÷VçFW''BFòG&—&F6†–ær‡v†–6‚—2vVöw&†–2’à¢gVæ7F–öâö6öçFVçE&V72‚’·°¢f"÷væW'2Ò÷Æä÷væW'2‚“°¢–b‚÷væW'2æÆVæwF‚’&WGW&âµÓ°¢f"$GBÒö6ö×Æ–çÇ&VwVÆGÇ&VwFV6‡ÆvG'ÅÅÆ&VF—Bö“°¢f"6¶—2Ò÷7Vu6¶—2‚“°¢f"ÆÂÒ÷4ÆÄ—FV×2‚“°¢òò–çFW&W7Bæ6†÷'3¢öæRW"†WfVçBÂ÷væW"’â6öÆÆ6RFò6–ævÆR&÷rW ¢òòWfVçBÂÆ—7F–ærWfW'–öæR–çFW&W7FVBÂ6ò7W÷'BFöW6âwB6VR—B&WVFVBà¢f"æ6†÷$ÖÒ··×ÒÂæ6†÷$÷&FW"ÒµÓ°¢ÆÂæf÷$V6‚†gVæ7F–öâ†—B’·°¢–b†—Bç7BÇÂ—Bæ†–FFVâ’&WGW&ã°¢–b‚—Bç6÷'BÇÂ—Bç6÷'BãÒ“““““““’’&WGW&ã°¢f"v†òÒ÷væW'2æf–ÇFW"†gVæ7F–öâ‡r’·°¢&WGW&â†—Bæ–çFW&W7FVBÇÂµÒ’ç6öÖR†gVæ7F–öâ†â’·²&WGW&â$föÆB†â’ç7Æ—B‚õÅÇ2²ò•³ÒÓÓÒs²×Ò“°¢×Ò“°¢–b‚v†òæÆVæwF‚’&WGW&ã°¢f"–BÒ—Bæ¶–æB²s¢r²—Bæ¶W“°¢–b‚æ6†÷$Ö¶–EÒ’·²æ6†÷$Ö¶–EÒÒ·²—C¢—BÂv†ó¢v†òç6Æ–6R‚’×Ó²æ6†÷$÷&FW"çW6‚†–B“²×Ð¢×Ò“°¢–b‚æ6†÷$÷&FW"æÆVæwF‚’&WGW&âµÓ°¢æ6†÷$÷&FW"ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&âæ6†÷$Ö¶Òæ—Bç6÷'BÒæ6†÷$Ö¶%Òæ—Bç6÷'C²×Ò“°¢f"&V72ÒµÒÂÔ…ôä4„õ%2ÒbÂU"Ò3°¢æ6†÷$÷&FW"ç6Æ–6RƒÂÔ…ôä4„õ%2’æf÷$V6‚†gVæ7F–öâ†–B’·°¢f"Òæ6†÷$Ö¶–EÒÂæ6†÷"Òæ—C°¢f"Òö6öçFVçE&öf–ÆR†æ6†÷"“°¢òòæ÷F†–ærFòÖF6‚öâ†7'6RÖçVÂWfVçBv—F‚æòfö7W2÷&öÆW2’Óâ6¶—à¢–b‚ö&¦V7Bæ¶W—2†çF÷–72’æÆVæwF‚’&WGW&ã°¢f"÷væW$v÷bÒçv†òç6öÖR…öv÷dö²“°¢f"6æBÒµÒÂ6VVä'&æBÒ··×ÒÂ6VVäæÖRÒ··×Ó°¢6VVä'&æEµö'&æD¶W’†æ6†÷"ÂvVôöb†æ6†÷"’•ÒÒ°¢ÆÂæf÷$V6‚†gVæ7F–öâ†—B’·°¢–b†—BÓÓÒæ6†÷"’&WGW&ã°¢–b†—Bç7BÇÂ—Bæ†–FFVâÇÂ—BçVWVUöF—6Ö—76VB’&WGW&ã°¢–b†—Bç7FvW2æÆVæwF‚’&WGW&ã²òòÇ&VG’–âF†R—VÆ–æP¢–b„$GBçFW7B†—BææÖR’’&WGW&ã°¢–b‚÷væW$v÷bbbö—4v÷dFVb†—B’’&WGW&ã²òòv÷bôdB—2¦–Òw2ÆæP¢òòæöâÔVævÆ—6‚WfVçC¢G&÷—BöæÇ’v†VâUdU%’÷væW"F†—2&V2—2f÷"—0¢òòVævÆ—6‚ÖöæÇ’(	B–b¦W&öÖR÷"6&Æ÷2—2Ç6ò–çFW&W7FVBÂ—B7F–ÆÂf—G2à¢–b„çv†òæWfW'’†gVæ7F–öâ‡r’·²&WGW&âöÆæt&Æö6¶VB‡rÂ—B“²×Ò’’&WGW&ã°¢–b‡6¶—5µ÷7Vu6¶—–B†—Bæ¶–æBÂ—Bæ¶W’•Ò’&WGW&ã°¢–b…÷fWFöVD—FVÒ†—B’’&WGW&ã²òòÆV&æVB&æ÷Bf÷"ÖR"GFW&à¢òò6¶—ç—F†–ærâ–çFW&W7FVB÷væW"—2Ç&VG’F–VBFòà¢–b„çv†òç6öÖR†gVæ7F–öâ‡r’·²&WGW&âöç•&öÆR†—BÂr“²×Ò’’&WGW&ã°¢f"æÒÒ$föÆB†—BææÖR“²–b‡6VVäæÖU¶æÕÒ’&WGW&ã°¢f"62Ò÷6–Õ66÷&R†Âö6öçFVçE&öf–ÆR†—B’“°¢–b‡62çBÂ"ÇÂ62ç"Â’&WGW&ã²òòæVVG2&VÂ–æGW7G'’äBVF–Væ6R÷fW&Æ ¢6VVäæÖU¶æÕÒÒ°¢6æBçW6‚‡·²—C¢—BÂ63¢62×Ò“°¢×Ò“°¢–b‚6æBæÆVæwF‚’&WGW&ã°¢6æBç6÷'B†gVæ7F–öâ†Â"’·²&WGW&â"ç62ç66÷&RÒç62ç66÷&RÇÂæ—Bç6÷'BÒ"æ—Bç6÷'C²×Ò“°¢òò'&æB¶6—G’FVGWR6òæV"Ö–FVçF–6Â†÷7G2FöâwBf–ÆÂF†RÆ—7Bà¢f"–6¶VBÒµÓ°¢f÷"‡f"’Ò²’Â6æBæÆVæwF‚bb–6¶VBæÆVæwF‚ÂU#²’²²’·°¢f"&²Òö'&æD¶W’†6æE¶•Òæ—BÂvVôöb†6æE¶•Òæ—B’“°¢–b‡6VVä'&æE¶&µÒ’6öçF–çVS°¢6VVä'&æE¶&µÒÒ²–6¶VBçW6‚†6æE¶•Ò“°¢×Ð¢–b‡–6¶VBæÆVæwF‚’&V72çW6‚‡·²æ6†÷#¢æ6†÷"Âv†ó¢çv†òÂ&V73¢–6¶VB×Ò“°¢×Ò“°¢&WGW&â&V73°¢×Ð¢òò)H)HÆâ†VC¢F†RWfW'–öæRÖf6–ær&FV6–FRv†BFòvòFò"7W&f6R(	@¢òò.(	3BÖöçF‚7VvvW7F–öç2–÷R6ÆV"v—F‚öæR6ÆÂV6ƒ¢$’vÒ–çFW&W7FVB ¢òò†vöW2öâævVÆw2&F"Fò&Vv—7FW"–÷R’÷"$æ÷Bf÷"ÖR"†öfb–÷W"Æ—7@¢òòf÷"vööB’âæò6÷fW&vRÖvö6öæfÆ–7BÆöv–2(	BF†B7F—2–âævVÆw0¢òòÆææW"âFV6–FRF÷vâFò¦W&òÂF†Vâ'–÷Rw&RÆÂ6Vv‡BW"à¢gVæ7F–öâ&VæFW%Æä†VB‚’·°¢f"†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×Ææ†VBr“°¢–b‚†÷7B’&WGW&ã°¢f"ÖTf—'7BÒ†vWD6öÆÆ$æÖR‚’ÇÂrr’çG&–Ò‚’çFôÆ÷vW$66R‚’ç7Æ—B‚õÅÇ2²ò•³Ó°¢òòöfbf÷"F†—2W'6öâ(	BÆVfRF†R6V7F–öâV×G’ƒ¦V×G’†–FW2—BæB—G0¢òòF—f–FW"’æB'V–ÆBæöæRöb—BâWfW'–öæRVÇ6R—2VæffV7FVBà¢òòWfW'–öæRæ÷r6†&W2D„õ"u2f–Wr„‡W&ÆW’##bÓ‚ÓR’ÂæBF†÷"†BÆà¢òò†VB7v—F6†VBöfb(	B6ò—Bw2öfbf÷"F†Rv†öÆRFVÒâævVÆ—2F†R6öÆP¢òòW†6WF–öã¢6†RÆç2æB&öö·2dõ"WfW'–öæRÂ6ò6†R¶VW2—BâF†—0¢òò&WÆ6W2F†RöÆBW"×W'6öâõÄåô„TEôôdbÖÂv†–6‚v2—G6VÆb¢òò6W&FR×&öf–ÆR&V†f–÷W"à¢–b‚‡v–æF÷ræ—4ævVÆW6W"bbv–æF÷ræ—4ævVÆW6W"‚’’’·²†÷7Bæ–ææW$…DÔÂÒrs²&WGW&ã²×Ð¢f"W'6öæÆ—¦VBÒ‚‡v–æF÷rä%õU%4ôä2ÇÂ··×Ò•¶ÖTf—'7EÒ“°¢f"ÖTæÖRÒvWD6öÆÆ$æÖR‚’ÇÂrs°¢f"7W÷'BÒ—57W÷'EW'6öâ†ÖTæÖR“°¢f"–çG&òÒsÇ6Æ73Ò'VWVRÖ–çG&ò×–WbÖ–çG&ò#ãÇ7G&öæsåÆâ†VC£Â÷7G&öæsâr°¢‡7W÷'BòtWfVçG2&÷VæBv†W&RF†RFVÒb33“·2Ç&VG’†VFVBÂÇW2÷F†W'2v÷'F‚Æöö²âp¢¢‡W'6öæÆ—¦VBòtWfVçG2&÷VæBF†RG&—2–÷Rb33“·&RÇ&VG’F¶–ærÂÇW2Ö÷&RÆ–¶RF†RöæW2–÷RfÆrâr¢tWfVçG2v÷'F‚Æöö²âr’’°¢tfÆrF†RöæW2FòvòFò„ævVÆ&Vv—7FW'2–÷R’æB6¶—F†R&W7Bâr°¢òò6¶—–ærFV6†W2F†—2vRv†B–÷RFöâwBvçB†÷&væ—¦W"ÂF÷–2À¢òòÆW76W"Ö¶æ÷vâ6—G’’â6’6òÆ–æÇ’ÂæBÇv—2öffW"F†RVæFò(	B¢òòÆV&æVBGFW&â–÷R6âwB6ÆV"v÷VÆBV–WFÇ’6‡&–æ²–÷W"÷vâf—G2à¢†gVæ7F–öâ‚’·°¢f"bÒ÷fWFõ&öf–ÆR‚“°¢–b‚‡bæâÇÂ’Â"’&WGW&ârs°¢&WGW&ârÇ7â6Æ73Ò'fWFòÖæ÷FR#å–÷W"6¶—2&Ræ'&÷v–ærv†B6†÷w2†W&RæB–âÆVÓä×’f—G3ÂöVÓââr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'fWFò×&W6WB"FF×fWFò×&W6WCå&W6WBv†B’b33“·fRFVv‡B—CÂö'WGFöããÂ÷7ãâs°¢×Ò’‚’²sÂ÷âs°¢òòW'6öâÆ&VÂ†VÇW'2(	BG&—2²–çFW&W7B&V72vòFVÒ×v–FRf÷"7W÷'Bà¢òòÆ&VÂ'’F†R–FVçF–f–W"F†RFVÒ7GVÆÇ’W6W2‡F†RW'6öæ¶W“¢F†÷"À¢òò¦W&öÖRÂfW&ÖÂ6&Æ÷2Â¦öRÂ¦–Ò’Âv†–6‚—2†÷rGFVæFVW2&R7F÷&VBà¢gVæ7F–öâ÷v†ôÆ&VÂ‡r’·²&WGW&âW66T‡FÖÂ‡ròræ6†$Bƒ’çFõWW$66R‚’²rç6Æ–6Rƒ’¢rr“²×Ð¢gVæ7F–öâ÷v†ôÆ—7B†'"’·²&WGW&â†'"ÇÂµÒ’æÖ…÷v†ôÆ&VÂ’æ¦ö–â‚rf×²r“²×Ð¢òòöæR&WW6&ÆR7VvvW7F–öâ&÷r†æÖR+rFFR+rÆö2²–çFW&W7FVB÷6¶—’à¢òð¢òòf÷%v†öÒF†RFVÖÖFRF†—2&÷r—2&V–ær7VvvW7FVBdõ"âævVÆæ@¢òò‡W&ÆW’'VâF†RG&6¶W"'WBæWfW"GFVæBÂ6ò$’vÒ–çFW&W7FVB"ò$æ÷Bf÷ ¢òòÖR"v2ÖVæ–ævÆW72–âF†V—"f–Wr(	BF†R&÷r&VÆöæw2FòF†÷"ÂfW&ÖÂWF2à¢òòf÷"F†VÒF†R'WGFöç2æÖRF†BW'6öâ‚%F†÷"w2–çFW&W7FVB"ò$æ÷Bf÷ ¢òò†–Ò"“²f÷"WfW'–öæRVÇ6RF†R&÷r—2F†V—"÷vâæBF†Rv÷&F–ær7F—0¢òòf—'7B×W'6öââ6VRµ·6ÆW2×7W÷'BÖæöâÖGFVæFVW5ÕÒà¢gVæ7F–öâ7Vu&÷r†—BÂW‡G&‡FÖÂÂf÷%v†ò’·°¢f"Æö2Ò—BæÆö6F–öâÇÂrs°¢f"v†òÒ‡7W÷'Bbbf÷%v†ò’ò7G&–ær†f÷%v†ò’¢rs°¢f"v†ô6Òv†òòv†òæ6†$Bƒ’çFõWW$66R‚’²v†òç6Æ–6Rƒ’¢rs°¢òòæÖR&F†W"F†â&öæ÷Vâ‚$æ÷Bf÷"F†÷""Âæ÷B$æ÷Bf÷"†–Ò"’(	B—@¢òò&VG2F†R6ÖRæBFöW6âwBwVW72ç–öæRw2&öæ÷Vç2à¢f"–W2Òv†òò†W66T‡FÖÂ‡v†ô6’²rb33“·2–çFW&W7FVBr’¢t’b33“¶Ò–çFW&W7FVBs°¢f"æòÒv†òò‚tæ÷Bf÷"r²W66T‡FÖÂ‡v†ô6’’¢tæ÷Bf÷"ÖRs°¢f"æõF—FÆRÒv†òò‚uF¶RF†—2öfbr²W66T‡FÖÂ‡v†ô6’²rb33“·2Æ—7B†æB÷WBöb–÷W"Æâ†VB’r¢¢uF¶RF†—2öfb–÷W"Æ—7Bs°¢&WGW&âsÆF—b6Æ73Ò'VWVR×&÷r7Vr×&÷r#ãÆF—b6Æ73Ò'VWVRÖÖ–â#âr°¢sÆ'WGFöâ6Æ73Ò'VWVRÖæÖR"FF×&VbÖ¶–æCÒ"r²—Bæ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r#âr²W66T‡FÖÂ†—BææÖR’²sÂö'WGFöãâr°¢sÇ6Æ73Ò'VWVRÖÖWF#âr²W66T‡FÖÂ†—BæFFU÷7G"ÇÂtFFRD$Br’²†Æö2òrÅÇS#rr²W66T‡FÖÂ†Æö2’¢rr’²sÂ÷âr°¢†W‡G&‡FÖÂÇÂrr’°¢sÂöF—cãÆF—b6Æ73Ò'VWVRÖ7F–öç27VrÖ7F–öç2#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ&–Ö'’"FF×ÖfÆsÒ#"FFÖ³Ò"r²—Bæ¶–æB²r"FFÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r"r°¢‡v†òòrFF×Öf÷#Ò"r²W66T‡FÖÂ‡v†ò’²r"r¢rr’²sâr²–W2²sÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ7Vr×6¶—"FF××6¶—Ò#"FFÖ³Ò"r²—Bæ¶–æB²r"FFÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r"r°¢‡v†òòrFF×Öf÷#Ò"r²W66T‡FÖÂ‡v†ò’²r"r¢rr’²rF—FÆSÒ"r²æõF—FÆR²r#âr²æò²sÂö'WGFöãâr°¢sÂöF—cãÂöF—câs°¢×Ð¢òò6ÖÆÂ&†–FRF†—2v†öÆR&Æö6²g&öÒÆâ†VB")ÉRf÷"G&—6ÇW7FW"ò&F ¢òòw&÷WÂ¶W–VB'’—G2æ6†÷"WfVçBà¢gVæ7F–öâ÷Æä†–FU‚†Wb’·°¢&WGW&âsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'ÆâÖ†–FR×‚"FF×ÆâÖ†–FRÖ¶–æCÒ"r²Wbæ¶–æB°¢r"FF×ÆâÖ†–FRÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†Wbæ¶W’’’²r"F—FÆSÒ$†–FRF†—2g&öÒÆâ†VB"&–ÖÆ&VÃÒ$†–FRg&öÒÆâ†VB#âgF–ÖW3³Âö'WGFöãâs°¢×Ð¢gVæ7F–öâæ6†÷$†VB†ÆVBÂWbÂW‡G&6Ç2’·°¢f"Æö2ÒWbæÆö6F–öâÇÂWbæ6—G’ÇÂrs°¢&WGW&âsÆF—b6Æ73Ò'VWVR×6V7F–öâG&—Ö6ÇW7FW"r²†W‡G&6Ç2òrr²W‡G&6Ç2¢rr’²r#âr²÷Æä†–FU‚†Wb’²sÇ6Æ73Ò'G&—Öæ6†÷"#âr²ÆVB°¢rÆ'WGFöâ6Æ73Ò'G&—Öæ6†÷"ÖæÖR"FF×&VbÖ¶–æCÒ"r²Wbæ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†Wbæ¶W’’’²r#âr²W66T‡FÖÂ†WbææÖR’²sÂö'WGFöãâr°¢sÇ7â6Æ73Ò'G&—Öæ6†÷"ÖÖWF#âr²W66T‡FÖÂ†WbæFFU÷7G"ÇÂrr’²†Æö2òrÅÇS#rr²W66T‡FÖÂ†Æö2’¢rr’²sÂ÷7ããÂ÷âs°¢×Ð¢f"6†÷vä¶W—2Ò··×Ó²òò7W&f6VB–âG&—2ò–çFW&W7B&V72Óâ¶VW÷WBöbF†RÖöçF†Ç’Æ—7@¢òò)H)H&F6‚–÷W"G&—2†vVöw&†–2’)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢f"6ÇW7FW'2Ò÷G&—6ÇW7FW'2‚’æf–ÇFW"†gVæ7F–öâ†6Â’·²&WGW&â÷Æä†–FFVâ†6Âææ6†÷"æ¶–æBÂ6Âææ6†÷"æ¶W’“²×Ò“°¢f"G&—‡FÖÂÒrs°¢òòÖâWfVçBw2•••”ÔÔDB6÷'B¶W’Fò%2•••’"7G&–ærÂFò6VVBF†P¢òò&V6V&6‚w2V'FW"v†VâF†W&Rw2æ÷F†–ærFò&F6‚öçFòG&—à¢gVæ7F–öâ÷V'FW$öe6÷'B‡6÷'B’·°¢f"2Ò7G&–ær‡6÷'BÇÂrr“°¢–b‡2æÆVæwF‚Âb’&WGW&ârs°¢f"’Ò2ç6Æ–6RƒÂB’ÂÖòÒ'6T–çB‡2ç6Æ–6RƒBÂb’Â“°¢–b‚õå³Ó•×·³G×ÒBòçFW7B‡’’ÇÂÖò’&WGW&ârs°¢&WGW&âur²„ÖF‚æfÆö÷"‚†ÖòÒ’ò2’²’²rr²“°¢×Ð¢òò•••”ÔÔDB6÷'B¶W’Óâ•4ò%•••’ÔÔÒÔDB"ÂFò6VVBF†R&V6V&6‚w2W†7@¢òòFFRv–æF÷r‡6ò—B‡VçG2&÷VæBF†RE$•u2DDU2Âæ÷BF†Rv†öÆRV'FW"’à¢gVæ7F–öâö—6ôg&öÕ6÷'B‡6÷'B’·°¢f"2Ò7G&–ær‡6÷'BÇÂrr“°¢–b‡2æÆVæwF‚Â‚’&WGW&ârs°¢&WGW&â2ç6Æ–6RƒÂB’²rÒr²2ç6Æ–6RƒBÂb’²rÒr²2ç6Æ–6RƒbÂ‚“°¢×Ð¢–b†6ÇW7FW'2æÆVæwF‚’·°¢G&—‡FÖÂ³ÒsÆF—b6Æ73Ò'VWVR×6V2Ö†VB#ãÇ7â6Æ73Ò'VWVR×6V2×F—FÆR#âb3#“Ss²&F6‚–÷W"G&—3Â÷7ããÇ7â6Æ73Ò'VWVR×6V2Ö6÷VçB#âr²6ÇW7FW'2æÆVæwF‚²sÂ÷7ããÂöF—câr°¢sÇ6Æ73Ò'VWVRÖÖWF"7G–ÆSÒ&Ö&v–ã¢ÓG‚Gƒ²#âr°¢‡7W÷'Bòuv†W&RF†RFVÒb33“·2Ç&VG’†VFVBfÖF6ƒ²æBv†BVÇ6R—2öâv—F†–âfWrF—2Â6ÖR÷"æV&'’6—G’âp¢¢u–÷Rb33“·&RÇ&VG’vö–ærFòF†W6RfÖF6ƒ²†W&Rb33“·2v†BVÇ6R—2öâv—F†–âfWrF—2Â–âF†R6ÖR÷"æV&'’6—G’âr’²sÂ÷âs°¢òò&VæFW"öæRæ6†÷"²—G2æV&'’WfVçG2âF†Ræ6†÷"&VG0¢òò$tDâ†GFVæF–ær’"ò%vV"7VÖÖ—BÆ—6&öâ‡7V¶–ær’"(	BWfVçBæÖRf—'7BÀ¢òò&öÆR–â&VçF†W6W2‡v÷&·2F†R6ÖRVæFW"W'6öâ†VFW"f÷"7W÷'B’à¢gVæ7F–öâ&VæFW$6ÇW7FW"†6Â’·°¢f"WbÒ6Âææ6†÷"ÂÆö2ÒWbæÆö6F–öâÇÂWbæ6—G’ÇÂrs°¢f""Ò†6Âç&öÆRÓÓÒw7V¶–ærBr’òw7V¶–ærr¢6Âç&öÆS°¢G&—‡FÖÂ³ÒsÆF—b6Æ73Ò'VWVR×6V7F–öâG&—Ö6ÇW7FW"#âr²÷Æä†–FU‚†Wb’²sÇ6Æ73Ò'G&—Öæ6†÷"#âr°¢sÆ'WGFöâ6Æ73Ò'G&—Öæ6†÷"ÖæÖR"FF×&VbÖ¶–æCÒ"r²Wbæ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†Wbæ¶W’’’²r#âr²W66T‡FÖÂ†WbææÖR’²sÂö'WGFöãâr°¢rÇ7â6Æ73Ò'G&—Öæ6†÷"×&öÆR#â‚r²W66T‡FÖÂ‡"’²r“Â÷7ãâr°¢sÇ7â6Æ73Ò'G&—Öæ6†÷"ÖÖWF#âr²W66T‡FÖÂ†WbæFFU÷7G"ÇÂrr’²†Æö2òrÅÇS#rr²W66T‡FÖÂ†Æö2’¢rr’²sÂ÷7ããÂ÷âs°¢6ÂææV"æf÷$V6‚†gVæ7F–öâ†â’·°¢6†÷vä¶W—5¶âæ—Bæ¶–æB²s¢r²âæ—Bæ¶W•ÒÒ°¢f"&÷‚Ò†âævÓÓÒòv÷fW&Æ2r¢‚wâr²âæv²rF’r²†âævÓÓÒòrr¢w2r’²r'Br’’°¢rÅÇS#rr²†âæ¶ÒÂ#Ròw6ÖR6—G’r¢‚wâr²ÖF‚ç&÷VæB†âæ¶Ò’²r¶Òv’r’“°¢G&—‡FÖÂ³Ò7Vu&÷r†âæ—BÂsÇ6Æ73Ò'G&—×&÷‚#âr²&÷‚²sÂ÷ârÂ6Âçv†ò“°¢×Ò“°¢òòæ÷F†–ærVÇ6RG&6¶VBæV"F†—2G&—â&F†W"F†âFVBVæBÂvP¢òò$ô5D•dTÅ’‡VçBf÷"æV&'’WfVçG2Ž(šCR’f–öæR×F–ÖRÂ66†VB¢òò&V6V&6‚(	Bæò6Æ–6²æVVFVBâF†RçG&—ÖWFòÆ6V†öÆFW"—2f–ÆÆV@¢òò'’÷'VäWFôæV"gFW"&VæFW"‡6VRF†Rv—&–ær&VÆ÷r’à¢–b‚6ÂææV"æÆVæwF‚’·°¢f"ö6—G’ÒW66T‡FÖÂ…7G&–ær†Æö2’ç7Æ—B‚rÂr•³ÒçG&–Ò‚’“°¢–b†Wbæ—5÷&—fFR’·°¢òò&—fFRò–çf—FRÖöæÇ’æ6†÷"„t%2ÂtDâ“¢æòV&Æ–2vV"fö÷G&–çBÀ¢òò6òâ’&V6V&6‚—2FVBVæB(	BæWfW"'Vâ—Bà¢–b†Æö2’G&—‡FÖÂ³ÒsÇ6Æ73Ò'G&—ÖæöæV"Öæ÷FR#äæ÷F†–ærVÇ6RG&6¶VBæV"r²ö6—G’²r&÷VæBF†VâãÂ÷âs°¢×ÒVÇ6R–b†Æö2’·°¢f"÷7F'BÒWbç7F'EöFFRÇÂö—6ôg&öÕ6÷'B†Wbç6÷'B“°¢f"÷VæBÒWbæVæEöFFRÇÂWbç7F'EöFFRÇÂö—6ôg&öÕ6÷'B…öVæE6÷'Döb†Wb’“°¢G&—‡FÖÂ³ÒsÆF—b6Æ73Ò'G&—ÖWFò"r°¢rFFÖWFòÖ¶–æCÒ"r²W66T‡FÖÂ…7G&–ær†Wbæ¶–æB’’²r"r°¢rFFÖWFòÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†Wbæ¶W’’’²r"r°¢rFFÖWFòÖæV#Ò"r²W66T‡FÖÂ†Æö2’²r"r°¢rFFÖWFò×V'FW#Ò"r²W66T‡FÖÂ…÷V'FW$öe6÷'B†Wbç6÷'B’’²r"r°¢rFFÖWFò×7F'CÒ"r²W66T‡FÖÂ…÷7F'B’²r"r°¢rFFÖWFòÖVæCÒ"r²W66T‡FÖÂ…÷VæB’²r"r°¢rFFÖWFòÖW†6ÇVFSÒ"r²W66T‡FÖÂ†WbææÖRÇÂrr’²r#âr°¢sÇ6Æ73Ò'G&—ÖæöæV"Öæ÷FR#åÅÇS##cÂ÷ãÂöF—câs°¢×ÒVÇ6R·°¢G&—‡FÖÂ³ÒsÇ6Æ73Ò'G&—ÖæöæV"Öæ÷FR#äFB6—G’FòF†—2WfVçB„VF—BÅÇS#“"Æö6F–öâ’Fòf–æBæV&'’WfVçG2Fò&F6‚ãÂ÷âs°¢×Ð¢×Ð¢G&—‡FÖÂ³ÒsÂöF—câs°¢×Ð¢–b‡7W÷'B’·°¢òòævVÆÆç2f÷"WfW'–öæS¢w&÷WF†RG&—2%’U%4ôâÂF†Vâ'’FFP¢òòv—F†–âV6‚W'6öâÂ6ò—B&VG2&†W&Rw2v†W&RF†÷"—2vö–ærÂF†Và¢òòfW&ÖÂ(
b"âW'6öç2÷&FW&VB'’F†V—"6ööæW7BG&—à¢f"'•v†òÒ··×ÒÂv†ô÷&FW"ÒµÓ°¢6ÇW7FW'2æf÷$V6‚†gVæ7F–öâ†6Â’·°¢–b‚'•v†õ¶6Âçv†õÒ’·²'•v†õ¶6Âçv†õÒÒµÓ²v†ô÷&FW"çW6‚†6Âçv†ò“²×Ð¢'•v†õ¶6Âçv†õÒçW6‚†6Â“°¢×Ò“°¢v†ô÷&FW"ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&â†'•v†õ¶Õ³Òææ6†÷"ç6÷'BÇÂ’Ò†'•v†õ¶%Õ³Òææ6†÷"ç6÷'BÇÂ“²×Ò“°¢v†ô÷&FW"æf÷$V6‚†gVæ7F–öâ‡v†ò’·°¢f"Æ—7BÒ'•v†õ·v†õÒç6Æ–6R‚’ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&â†ææ6†÷"ç6÷'BÇÂ’Ò†"ææ6†÷"ç6÷'BÇÂ“²×Ò“°¢G&—‡FÖÂ³ÒsÆF—b6Æ73Ò'G&—×W'6öâ#ãÆƒB6Æ73Ò'G&—×W'6öâÖæÖR#âr²÷v†ôÆ&VÂ‡v†ò’°¢sÇ7â6Æ73Ò'G&—×W'6öâÖ6÷VçB#âr²Æ—7BæÆVæwF‚²rG&—r²†Æ—7BæÆVæwF‚ÓÓÒòrr¢w2r’²sÂ÷7ããÂöƒCâs°¢Æ—7Bæf÷$V6‚†gVæ7F–öâ†6Â’·²&VæFW$6ÇW7FW"†6Â“²×Ò“°¢G&—‡FÖÂ³ÒsÂöF—câs°¢×Ò“°¢×ÒVÇ6R·°¢6ÇW7FW'2æf÷$V6‚†gVæ7F–öâ†6Â’·²&VæFW$6ÇW7FW"†6Â“²×Ò“°¢×Ð¢×Ð¢òò)H)H&V6W6R–÷Rw&R–çFW&W7FVB–â‚†6öçFVçB6–Ö–Æ&—G’’)H)H)H)H)H)H)H)H)H)H)H ¢f"&V72Òö6öçFVçE&V72‚’æf–ÇFW"†gVæ7F–öâ‡&2’·²&WGW&â÷Æä†–FFVâ‡&2ææ6†÷"æ¶–æBÂ&2ææ6†÷"æ¶W’“²×Ò“°¢f"&V4‡FÖÂÒrs°¢–b‡&V72æÆVæwF‚’·°¢&V4‡FÖÂ³ÒsÆF—b6Æ73Ò'VWVR×6V2Ö†VB#ãÇ7â6Æ73Ò'VWVR×6V2×F—FÆR#âb3#ƒ##S²WfVçB&F#Â÷7ããÇ7â6Æ73Ò'VWVR×6V2Ö6÷VçB#âr²&V72æÆVæwF‚²sÂ÷7ããÂöF—câr°¢sÇ6Æ73Ò'VWVRÖÖWF"7G–ÆSÒ&Ö&v–ã¢ÓG‚Gƒ²#âr°¢‡7W÷'BòtÖ÷&RÆ–¶Rv†BFVÖÖFW2fÆvvVBfÖF6ƒ²6ÖR–æGW7G'’ÂVF–Væ6RæBF÷–72âp¢¢tÖ÷&RÆ–¶RF†RWfVçG2–÷RfÆvvVBfÖF6ƒ²6ÖR–æGW7G'’ÂVF–Væ6RæBF÷–72âr’²sÂ÷âs°¢&V72æf÷$V6‚†gVæ7F–öâ‡&2’·°¢f"ÆVBÒ7W÷'@¢ò…÷v†ôÆ—7B‡&2çv†ò’²rr²‡&2çv†òæÆVæwF‚âòv&Rr¢v—2r’²r–çFW&W7FVB–âr¢¢t&V6W6R–÷Rb33“·&R–çFW&W7FVB–âs°¢&V4‡FÖÂ³Òæ6†÷$†VB†ÆVBÂ&2ææ6†÷"Âw&V2Ö6ÇW7FW"r“°¢&2ç&V72æf÷$V6‚†gVæ7F–öâ‡’·°¢6†÷vä¶W—5·æ—Bæ¶–æB²s¢r²æ—Bæ¶W•ÒÒ°¢òòæÖRF†RW'6öâv†VâF†R&V6öÖÖVæFF–öâG&6W2FòW†7FÇ’öæRö`¢òòF†VÓ²v—F‚6WfW&Â–çFW&W7FVB—B7F—2vVæW&–2à¢&V4‡FÖÂ³Ò7Vu&÷r‡æ—BÂrrÂ‡&2çv†òbb&2çv†òæÆVæwF‚ÓÓÒ’ò&2çv†õ³Ò¢rr“°¢×Ò“°¢&V4‡FÖÂ³ÒsÂöF—câs°¢×Ò“°¢×Ð ¢òò.(	3BÖöçF‚7VvvW7F–öç2†W†6ÇVF–ærç—F†–ærÇ&VG’7W&f6VB&÷fR’à¢f"7VrÒ÷7VvvW7F–öç4f÷"‚’æf–ÇFW"†gVæ7F–öâ‡‚’·²&WGW&â6†÷vä¶W—5·‚æ—Bæ¶–æB²s¢r²‚æ—Bæ¶W•Ó²×Ò“°¢–b‚7VræÆVæwF‚bbG&—‡FÖÂbb&V4‡FÖÂ’·°¢òòV×G’&V6W6R–÷R6ÆV&VB—Bg2â&V6W6Ræ÷F†–ærf—B–WB(	B6’v†–6‚à¢f"ç•6¶—VBÒö&¦V7Bæ¶W—2…÷7Vu6¶—2‚’’æÆVæwF‚â°¢†÷7Bæ–ææW$…DÔÂÒ–çG&ò²sÆF—b6Æ73Ò'VWVRÖV×G’#âr°¢†ç•6¶—V@¢òrb33²–÷Rb33“·&RÆÂ6Vv‡BWfÖF6ƒ²–÷Rb33“·fRFV6–FVBöâWfW'—F†–ær–âF†R"fæF6ƒ³BÖöçF‚v–æF÷râæWrWfVçG2v–ÆÂ6†÷rW†W&R2F†W’6öÖR–ââp¢¢tæ÷F†–ær–âF†R"fæF6ƒ³BÖöçF‚v–æF÷rf—G2–WBfÖF6ƒ²6†V6²&6²2æWrWfVçG26öÖR–ââr’°¢sÂöF—câs°¢&WGW&ã°¢×Ð¢òòw&÷W'’ÔôåD‚Âæ÷B&Vv–öâ(	B6‡&öæöÆöv–6Â&VG2&WGFW"f÷"'v†Bw0¢òò6öÖ–ærWFòFV6–FRöâ"ÂæBF†R&Vv–öâÆ&VÂv2&VGVæFçBv—F‚F†P¢òò6—G’öâWfW'’&÷rç—v’à¢f"w&÷W2Ò··×ÒÂ÷&FW"ÒµÓ°¢7Vræf÷$V6‚†gVæ7F–öâ‡‚’·°¢f"ÒÒ÷7VtÖöçF‚‡‚æ—Bç6÷'B“°¢–b‚w&÷W5¶Òæ¶W•Ò’·²w&÷W5¶Òæ¶W•ÒÒ·²Æ&VÃ¢ÒæÆ&VÂÂ6÷'C¢Òç6÷'BÂ—FV×3¢µÒ×Ó²÷&FW"çW6‚†Òæ¶W’“²×Ð¢w&÷W5¶Òæ¶W•Òæ—FV×2çW6‚‡‚“°¢×Ò“°¢÷&FW"ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&âw&÷W5¶Òç6÷'BÒw&÷W5¶%Òç6÷'C²×Ò“°¢f"‡FÖÂÒ–çG&ò²G&—‡FÖÂ²&V4‡FÖÃ°¢òòF†RÖöçF‚Ö'’ÖÖöçF‚7VvvW7F–öâÆ—7BF†BföÆÆ÷w2WfVçB&F"—2öfbf÷ ¢òòF†÷"„‡W&ÆW’##bÓrÓ#’’â†RvWG2F†RGvò7W&FVB&Æö6·2(	BG&—2†Rw0¢òòÇ&VG’F¶–ærÂæBWfVçG2Æ–¶RF†RöæW2F†RFVÒfÆvvVB(	BæBæ÷BF†P¢òòÆöærF–ÂVæFW&æVF‚F†VÒÂv†–6‚—2'&÷w6–ærÂæ÷BFV6—6–öâVWVRà¢–b‚õÄåõ5TttU5D”ôå5ôôde²†vWD6öÆÆ$æÖR‚’ÇÂrr’çG&–Ò‚’çFôÆ÷vW$66R‚’ç7Æ—B‚õÅÇ2²ò•³ÕÒ’·°¢÷&FW"æf÷$V6‚†gVæ7F–öâ†Ö¶W’’·°¢f"rÒw&÷W5¶Ö¶W•Ó°¢f"Æ—7BÒræ—FV×2ç6Æ–6R‚’ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&âæ—Bç6÷'BÒ"æ—Bç6÷'C²×Ò“°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'VWVR×6V7F–öâ#ãÆF—b6Æ73Ò'VWVR×6V2Ö†VB#ãÇ7â6Æ73Ò'VWVR×6V2×F—FÆR#âr²W66T‡FÖÂ†ræÆ&VÂ’²sÂ÷7ããÇ7â6Æ73Ò'VWVR×6V2Ö6÷VçB#âr²Æ—7BæÆVæwF‚²sÂ÷7ããÂöF—câs°¢Æ—7Bæf÷$V6‚†gVæ7F–öâ‡‚’·²‡FÖÂ³Ò7Vu&÷r‡‚æ—BÂrr“²×Ò“°¢‡FÖÂ³ÒsÂöF—câs°¢×Ò“°¢×Ð¢†÷7Bæ–ææW$…DÔÂÒ‡FÖÃ°¢òòôäRFVÆVvFVBÆ—7FVæW"öâF†R†÷7B–ç7FVBöbÆ—7FVæW"W"'WGFöâà¢òòÆâ†VB&Ww&—FW2'G2öb—G6VÆbgFW"&VæFW"‡F†R’&V×6V&6€¢òòf–ÆÇ2V6‚çG&—ÖWFòÆ6V†öÆFW"’ÂæBç’W"ÖVÆVÖVçBÆ—7FVæW"öà¢òò&WÆ6VBÖ&·WF–W2v—F‚—B(	BÆVf–ær&÷w2F†BÆöö²6Æ–6¶&ÆRæBFð¢òòæ÷F†–ærâFVÆVvF–öâ7W'f—fW2WfW'’&R×&VæFW"ÂæB6Æ÷6W7B‚’ÖVç2¢òò6Æ–6²ç—v†W&RöâF†R&÷rw2'WGFöâ7F–ÆÂ&W6öÇfW2à¢–b‚†÷7BæFF6WBç&Vev—&VB’·°¢†÷7BæFF6WBç&Vev—&VBÒss°¢†÷7BæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢f"VÂÒRçF&vWBbbRçF&vWBæ6Æ÷6W7BòRçF&vWBæ6Æ÷6W7B‚u¶FF×&VbÖ¶–æEÒr’¢çVÆÃ°¢–b‚VÂÇÂ†÷7Bæ6öçF–ç2†VÂ’’&WGW&ã°¢÷4÷Vå&Vb†VÂævWDGG&–'WFR‚vFF×&VbÖ¶–æBr’ÂVÂævWDGG&–'WFR‚vFF×&VbÖ¶W’r’“°¢×Ò“°¢×Ð¢òò6öÆòG&—2v—F‚æ÷F†–ærG&6¶VBæV&'“¢&ö7F—fVÇ’f–ÆÂV6‚v—F‚WFð¢òòR’Öf÷VæBWfVçG2†öæRÖWFW&VB6V&6‚W"G&—Â66†VBF—2(	BæWfW ¢òò&RÖf—&VBöâÆ–â&R×&VæFW"’âæò6Æ–6²æVVFVBâ6äUr6V&6†W2W ¢òò&VæFW"†66†VBöæW2&Rg&VR’6ò&–rFVÒ6âwB'W'7BF†R’'VFvWBà¢öWFô'VFvWBÒS°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚rçG&—ÖWFòr’æf÷$V6‚†gVæ7F–öâ†2’·°¢÷'VäWFôæV"‡·°¢æ6†÷$¶–æC¢2ævWDGG&–'WFR‚vFFÖWFòÖ¶–æBr’À¢æ6†÷$¶W“¢2ævWDGG&–'WFR‚vFFÖWFòÖ¶W’r’À¢Æö3¢2ævWDGG&–'WFR‚vFFÖWFòÖæV"r’À¢V'FW#¢2ævWDGG&–'WFR‚vFFÖWFò×V'FW"r’À¢FFTg&öÓ¢2ævWDGG&–'WFR‚vFFÖWFò×7F'Br’À¢FFUFó¢2ævWDGG&–'WFR‚vFFÖWFòÖVæBr’À¢W†6ÇVFS¢2ævWDGG&–'WFR‚vFFÖWFòÖW†6ÇVFRr¢×Ò“°¢×Ò“°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×ÖfÆuÒr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"¶–æBÒ'FâævWDGG&–'WFR‚vFFÖ²r’Â¶W’Ò'FâævWDGG&–'WFR‚vFFÖ¶W’r“°¢f"—BÒ÷4ÆÄ—FV×2‚’æf–ÇFW"†gVæ7F–öâ‡‚’·²&WGW&â‚æ¶–æBÓÓÒ¶–æBbb7G&–ær‡‚æ¶W’’ÓÓÒ¶W“²×Ò•³Ó°¢–b‚—B’&WGW&ã°¢'Fâç6WDGG&–'WFR‚v&–Ö'W7’rÂwG'VRr“°¢òòævVÆô‡W&ÆW’fÆrôâ$T„ÄbôbF†RFVÖÖFRF†R&÷rv27VvvW7FV@¢òòf÷"(	BFövvÆT×”–çFW&W7Bv÷VÆB†fR&Vv—7FW&VBD„TÒÂæBF†W’Föâw@¢òòGFVæBâFBF†BW'6öâFòF†R6†&VB–çFW&W7FVBÆ—7B–ç7FV@¢òò‡6ÖRw&—FRF†RÆææW"w2"²fÆrf÷"‚"FöW2’à¢f"f÷%v†òÒ'FâævWDGG&–'WFR‚vFF×Öf÷"r“°¢–b†f÷%v†ò’·°¢f"F&vWBÒõ5õ$õ5DU"æf–ÇFW"†gVæ7F–öâ†â’·²&WGW&ââçFôÆ÷vW$66R‚’ÓÓÒ7G&–ær†f÷%v†ò’çFôÆ÷vW$66R‚“²×Ò•³Ó°¢–b‡F&vWB’·°¢f"Æ—7BÒ†—Bæ–çFW&W7FVBÇÂµÒ’ç6Æ–6R‚“°¢–b†Æ—7Bæ–æFW„öb‡F&vWB’ÓÓÒÓ’Æ—7BçW6‚‡F&vWB“°¢Æ—7BÒõ5õ$õ5DU"æf–ÇFW"†gVæ7F–öâ‡‚’·²&WGW&âÆ—7Bæ–æFW„öb‡‚’ÓÒÓ²×Ò“°¢÷5V–6µw&—FR†¶–æBÂ¶W’Â·²–çFW&W7FVC¢Æ—7B×Ò“°¢&WGW&ã°¢×Ð¢×Ð¢FövvÆT×”–çFW&W7B†¶–æBÂ—Bæ¶W’Â—Bæ–çFW&W7FVBÂ—Bç7F'Dö&¢bb—Bç7F'Dö&¢æGFVæE÷fW&F–7B“°¢×Ò“°¢×Ò“°¢òòVæFòF†RÆV&æ–ær†æ÷BF†R–æF—f–GVÂ6¶—2(	BF†÷6R7F’FV6–FVB’à¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×fWFò×&W6WEÒr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢G'’·²Æö6Å7F÷&vRç&VÖ÷fT—FVÒ…÷fWFô¶W’‚’“²×Ò6F6‚†R’··×Ð¢&VæFW%Æä†VB‚“°¢–b‡v–æF÷ræ÷5&Vg&W6‚’v–æF÷ræ÷5&Vg&W6‚‚“²òò×’f—G2&V6ö×WFW0¢×Ò“°¢×Ò“°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF××6¶—Òr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢÷7Vu6¶—†'FâævWDGG&–'WFR‚vFFÖ²r’Â'FâævWDGG&–'WFR‚vFFÖ¶W’r’“°¢f"&÷rÒ'Fâæ6Æ÷6W7B‚rçVWVR×&÷rr“°¢–b‡&÷r’&÷rç7G–ÆRæF—7Æ’ÒvæöæRs²òò–ç7FçBfVVF&6°¢&VæFW%Æä†VB‚“²òò&R×&VæFW#¢6÷VçG2²V×G’7FFRWFFP¢×Ò“°¢×Ò“°¢òò)ÉRöâG&—6ÇW7FW"ò&F"w&÷W(i"†–FRF†Bv†öÆR&Æö6²g&öÒÆâ†VBà¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×ÆâÖ†–FRÖ¶–æEÒr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢÷Æä†–FR†'FâævWDGG&–'WFR‚vFF×ÆâÖ†–FRÖ¶–æBr’Â'FâævWDGG&–'WFR‚vFF×ÆâÖ†–FRÖ¶W’r’“°¢&VæFW%Æä†VB‚“°¢×Ò“°¢×Ò“°¢×Ð ¢òò)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y ¢òò×’&öf–ÆR(	BW"×W'6öâ&–òÂ7V¶–ærF÷–72Â7BFÆ·2Âf–ÆW2À¢òòæBF&vWF–æræ÷FW2âVF—F&ÆRf÷"v†öWfW"w26–væVB–ã²F†R&W7Bö`¢òòF†RFVÒw2FW‡B6†÷w2&VBÖöæÇ’&VÆ÷rÂ6òvR6â6VRv†W&RV6€¢òòW'6öâ†27ö¶VâæBv†BF†W’vçBFòF&vWB†F&vWF–ær–B(	@¢òòæòW"ÖWfVçB&V6öæ–ærÆ—fW2†W&R’âFW‡BÆ—fW2–âFVÕ÷&öf–ÆW3°¢òòf–ÆW2Æ—fR–âF†R&—fFRw&öf–ÆW2r7F÷&vR'V6¶WBâ&÷F‚FVw&FP¢òòFòöæR×F–ÖR''Vâ6WGW"æ÷FR–bF†W’&VâwBF†W&R–WBà¢òò)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y ¢f"$ôd”ÄUôd”TÄE2Ò°¢·²³¢væ÷FW2rÂÆ&VÃ¢uF&vWF–æræ÷FW2rÂ†–çC¢vWfVçG2–÷RvçBrÂƒ¢uG—W2öbWfVçG2–÷RvçBFò&RBÂ7V6–f–2WfVçBæÖW2Â&Vv–öç2(	Bç—F†–æröâ–÷W"Ö–æBâr×ÒÀ¢·²³¢v&–òrÂÆ&VÃ¢u6†÷'B&–òrÂ†–çC¢v6÷WÆRöb6VçFVæ6W2rÂƒ¢uGvò÷"F‡&VR6VçFVæ6W2â÷&væ—¦W"6÷VÆBG&÷7G&–v‡B–çFòâvVæFâr×ÒÀ¢·²³¢wF÷–72rÂÆ&VÃ¢uFÆ·2bF÷–72rÂ†–çC¢wv†B–÷R7V²öârÂƒ¢uFÆ²F—FÆW2ÂF†VÖW2Â6–væGW&RævÆW2(	BöæRW"Æ–æRâr×Ð¢Ó°¢òò7V¶–ærÖFW&–Ç2Â÷&væ—¦VB'’v†Bâ÷&væ—¦W"7GVÆÇ’6·2f÷"(	@¢òòV6‚—2—G2÷vâWÆöB6Æ÷B†f–ÆW2Æ—fRVæFW"ÇW'6öãâóÇ6Æ÷Câò–âF†P¢òò&öf–ÆW2'V6¶WB’âF†—2—2F†Rö–çBöbF†R&öf–ÆS¢&VG’×Fò×6VæB¶—Bà¢òòF‡&VR6Æ÷G2Âæ÷Bf—fR„‡W&ÆW’##bÓrÓ3’â&–÷2æB7V¶–ærF÷–72vW&P¢òòF†R6ÖR6²vV&–ærGvò†G2ÂæB6Æ–FW2bFV6·2—2§W7Bæ÷F†W"f–ÆR(	@¢òò÷F†W"ÖFW&–Ç26÷fW'2—Bà¢òð¢òòÇ6öÆ—7G2föÆFW'26Æ÷BÅ4ò&VG2âF†RæÖW2&R7F÷&vRF‡2Â6ð¢òò&VæÖ–ær6Æ÷Bv÷VÆB÷'†âv†B—2Ç&VG’WÆöFVC¢fW&Öw2öæR×6†VW@¢òò6—G2VæFW"7V¶–æu÷F÷–72òæBF†÷"w2FV6²föÆFW"Ö’f–ÆÂÆFW"âæWp¢òòWÆöG2vòFò¶²F†RöÆBföÆFW'27F’&VF&ÆRà¢f"$ôd”ÄUôÔDU$”Å2Ò°¢·²³¢v&–÷2rÂÆ&VÃ¢t&–÷2b7V¶–ærF÷–72rÀ¢†–çC¢vf÷&ÖÂ&–òFö2Â7V¶–ærF÷–72Â÷"÷fW'f–Wröâ–÷W'6VÆbrÀ¢Ç6ó¢²w7V¶–æu÷F÷–72uÒ×ÒÀ¢·²³¢vVÖ–Å÷FV×ÆFRrÂÆ&VÃ¢tVÖ–ÂFV×ÆFRrÀ¢†–çC¢wv†B–÷^(	–BÆ–¶RævVÆFò6VæBFòF†RWfVçB÷&væ—¦W"–bæVVFVBrÀ¢7W÷'D†–çC¢uv†BFò6VæBFòF†RWfVçB÷&væ—¦W'2r×ÒÀ¢·²³¢v÷F†W"rÂÆ&VÃ¢t÷F†W"ÖFW&–Ç2rÀ¢†–çC¢w&W72ÂFW7F–Ööæ–Ç2Âf–FVòÆ–æ·2Â÷"ç—F†–ærVÇ6RrÀ¢Ç6ó¢²vFV6·2uÒ×Ð¢Ó°¢òòævVÆFöW2æ÷B7V²Â6òF†R6Æ÷BÖVç26öÖWF†–ærF–ffW&VçBöâ†W"6&Bà¢gVæ7F–öâöÖD†–çB†ÒÂ—57W÷'B’·°¢&WGW&â†—57W÷'BbbÒç7W÷'D†–çB’òÒç7W÷'D†–çB¢Òæ†–çC°¢×Ð¢gVæ7F–öâ÷&öf–ÆT¶W’†æÖR’·²&WGW&â†æÖRÇÂrr’çG&–Ò‚’çFôÆ÷vW$66R‚’ç7Æ—B‚õÅÇ2²ò•³Ó²×Ð¢gVæ7F–öâ÷&öf–ÆTF—7Æ’‡&÷rÂ¶W’’·°¢–b‡&÷rbb&÷ræF—7Æ•öæÖR’&WGW&â&÷ræF—7Æ•öæÖS°¢f"Ò‡v–æF÷rä%õU%4ôä2ÇÂ··×Ò•¶¶W•Ó°¢–b…bbææÖR’&WGW&âææÖS°¢&WGW&â¶W’ò¶W’æ6†$Bƒ’çFõWW$66R‚’²¶W’ç6Æ–6Rƒ’¢rs°¢×Ð¢gVæ7F–öâ÷&öf–ÆU&öÆR†¶W’’·²f"Ò‡v–æF÷rä%õU%4ôä2ÇÂ··×Ò•¶¶W•Ó²&WGW&â…bbç&öÆR’ÇÂrs²×Ð¢gVæ7F–öâöf×D'—FW2†â’·°¢âÒçVÖ&W"†â’ÇÂ°¢–b†âÂ#B’&WGW&ââ²r"s°¢–b†âÂ#B¢#B’&WGW&â†âò#B’çFôf—†VBƒ’²r´"s°¢&WGW&â†âòƒ#B¢#B’’çFôf—†VBƒ’²rÔ"s°¢×Ð¢òò)H)H&öf–ÆRÖFW&–Ç3¢&Wf–Wr†æ÷BF÷væÆöB’²F÷væÆöB–6öâ²Æ–æ·2)H)H ¢f"$ôd”ÄUôDÅô”4ôâÒsÇ7frf–Wt&÷ƒÒ##B#B"f–ÆÃÒ&æöæR"7G&ö¶SÒ&7W'&VçD6öÆ÷""7G&ö¶R×v–GFƒÒ#""7G&ö¶RÖÆ–æV6Ò'&÷VæB"7G&ö¶RÖÆ–æV¦ö–ãÒ'&÷VæB"&–Ö†–FFVãÒ'G'VR#ãÇF‚CÒ$Ó#WcF""Ó"$ƒV""Ó"Ó'bÓB"óãÇöÇ–Æ–æRö–çG3Ò#r"Rr"óãÆÆ–æRƒÒ#""ƒ#Ò#""“Ò#R"“#Ò#2"óãÂ÷7fsâs°¢òòÆ–æ·2„vöövÆRG&—fRôFö2WF2â’&R7F÷&VB2F–ç’"çvV&Æ–æ²"Ö&¶W"f–ÆW0¢òòv†÷6RäÔR—2&6ScGW&Âöb··C§F—FÆRÂS§W&Ç×Ò‡6òÆ—7F–æræVVG2æòW‡G&¢òòfWF6‚’âÆVv7’Ö&¶W'2†öÆB§W7BF†R&rU$Âà¢gVæ7F–öâö#cGW&ÄVæ2‡2’·²G'’·²&WGW&â'Fö‡VæW66R†Væ6öFUU$”6ö×öæVçB‡2’’’ç&WÆ6R‚õÅÂ²örÂrÒr’ç&WÆ6R‚õÅÂòörÂuòr’ç&WÆ6R‚óÒ²BòÂrr“²×Ò6F6‚†R’·²&WGW&ârs²×Ò×Ð¢gVæ7F–öâö#cGW&ÄFV2‡2’·²G'’·²2Ò7G&–ær‡2’ç&WÆ6R‚òÒörÂr²r’ç&WÆ6R‚õòörÂròr“²v†–ÆR‡2æÆVæwF‚RB’2³ÒsÒs²&WGW&âFV6öFUU$”6ö×öæVçB†W66R†Fö"‡2’’“²×Ò6F6‚†R’·²&WGW&ârs²×Ò×Ð¢gVæ7F–öâö—5vV&Æ–æ²†æÖR’·²&WGW&âõÅÂçvV&Æ–æ²Bö’çFW7B†æÖRÇÂrr“²×Ð¢gVæ7F–öâ÷vV&Æ–æ´–æfò†æÖR’·°¢f"FV2Òö#cGW&ÄFV2…7G&–ær†æÖR’ç&WÆ6R‚õÅÂçvV&Æ–æ²Bö’Ârr’“°¢G'’·²f"òÒ¥4ôâç'6R†FV2“²–b†òbbòçR’&WGW&â·²W&Ã¢7G&–ær†òçR’ÂF—FÆS¢7G&–ær†òçBÇÂrr’×Ó²×Ò6F6‚†R’··×Ð¢&WGW&â·²W&Ã¢FV2ÂF—FÆS¢rr×Ó²òòÆVv7“¢F†RæÖRv2F†R&rU$À¢×Ð¢gVæ7F–öâö—4öff–6TFö2†æÖR’·²&WGW&âõÅÂâ†Fö7ƒ÷ÇGƒ÷Ç†Ç7ƒò’Bö’çFW7B†æÖRÇÂrr“²×Ð¢òò$Ud”Ur7F÷&VBf–ÆR–âF†R&–v‡Bf–WvW"(	BæWfW"f÷&6VBF÷væÆöBâöff–6P¢òòFö72&VæFW"f–Ö–7&÷6ögBw2öæÆ–æRf–WvW#²Dg2ò–ÖvW2òFW‡B÷Và¢òòF—&V7FÇ’‡F†R'&÷w6W"&Wf–Ww2F†÷6R’âF†—2—2F†Rf—‚f÷"&6Æ–6¶–ær—@¢òò§W7BF÷væÆöG2F†RæFö7‚"à¢gVæ7F–öâ÷&öf–ÆU&Wf–Wr†gVÆÅF‚ÂæÖR’·°¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æ7&VFU6–væVEW&Â†gVÆÅF‚Âc’çF†Vâ†gVæ7F–öâ‡"’·°¢f"W&ÂÒ"bb"æFFbb"æFFç6–væVEW&Ã°¢–b‚W&Â’·²7FGW2‚t6÷VÆBæ÷B÷VâF†Bf–ÆRârÂvW'&÷"r“²&WGW&ã²×Ð¢f"FW7BÒö—4öff–6TFö2†æÖR¢ò‚v‡GG3¢ò÷f–Wræöff–6V2æÆ—fRæ6öÒö÷÷f–Wræ7ƒ÷7&3Òr²Væ6öFUU$”6ö×öæVçB‡W&Â’¢¢W&Ã°¢v–æF÷ræ÷Vâ†FW7BÂuö&Ææ²rÂvæö÷VæW"r“°¢×Ò“°¢×Ð¢òòDõtäÄôBöâFVÖæB„6öçFVçBÔF—7÷6—F–öã¢GF6†ÖVçB’(	B&V†–æB—G2÷vâ–6öâà¢gVæ7F–öâ÷&öf–ÆTF÷væÆöB†gVÆÅF‚ÂæÖR’·°¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æ7&VFU6–væVEW&Â†gVÆÅF‚Â#Â·²F÷væÆöC¢æÖRÇÂG'VR×Ò’çF†Vâ†gVæ7F–öâ‡"’·°¢f"W&ÂÒ"bb"æFFbb"æFFç6–væVEW&Ã°¢–b‡W&Â’v–æF÷ræ÷Vâ‡W&ÂÂuö&Ææ²rÂvæö÷VæW"r“²VÇ6R7FGW2‚t6÷VÆBæ÷BF÷væÆöBF†Bf–ÆRârÂvW'&÷"r“°¢×Ò“°¢×Ð¢òòöæR&÷rf÷"f–ÆRõ"Æ–æ³¢æÖRÒ&Wf–WrÂF÷væÆöB–6öâÂæBà¢òò÷F–öæÂFVÆWFR†÷vâ&öf–ÆRöæÇ’’âÆ–æ·2÷VâF—&V7FÇ’‡F†B•2&Wf–Wr’à¢gVæ7F–öâöÖDf–ÆU&÷t‡FÖÂ†gVÆÅF‚ÂæÖRÂ6—¦RÂ6äFVÆWFR’·°¢f"FVÂÒ6äFVÆWFP¢òsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&öf–ÆRÖf–ÆRÖFVÂ"FFÖFVÇFƒÒ"r²W66T‡FÖÂ†gVÆÅF‚’²r"FFÖFVÆæÖSÒ"r²W66T‡FÖÂ†æÖR’²r"&–ÖÆ&VÃÒ$FVÆWFRr²W66T‡FÖÂ†æÖR’²r"F—FÆSÒ$FVÆWFR#ãÇ7frf–Wt&÷ƒÒ##B#B"f–ÆÃÒ&æöæR"7G&ö¶SÒ&7W'&VçD6öÆ÷""7G&ö¶R×v–GFƒÒ#""7G&ö¶RÖÆ–æV6Ò'&÷VæB"7G&ö¶RÖÆ–æV¦ö–ãÒ'&÷VæB"&–Ö†–FFVãÒ'G'VR#ãÇF‚CÒ$Ó2fƒ‚"óãÇF‚CÒ$Ó’gcF""Ó"$ƒv""Ó"Ó%cb"óãÇF‚CÒ$Ó‚ecF"""Ó&ƒF"""'c""óãÂ÷7fsãÂö'WGFöãâp¢¢rs°¢–b…ö—5vV&Æ–æ²†æÖR’’·°¢f"–æfòÒ÷vV&Æ–æ´–æfò†æÖR“°¢f"W&ÂÒ–æfòçW&Ã°¢f"Æ&ÂÒ–æfòçF—FÆRÇÂ†gVæ7F–öâ‚’·°¢–b‚öFö75ÅÂævöövÆWÆG&—fUÅÂævöövÆRö’çFW7B‡W&Â’’&WGW&âtvöövÆRFö2s°¢G'’·²&WGW&âæWrU$Â‡W&Â’æ†÷7Bç&WÆ6R‚õçwwuÅÂâòÂrr“²×Ò6F6‚†R’·²&WGW&âtÆ–æ²s²×Ð¢×Ò’‚“°¢òò&VæÖRF†RÆ–æ²w2F—FÆRgFW"F†Rf7B†÷vâ&öf–ÆRöæÇ’’à¢f"&VâÒ6äFVÆWFP¢òsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&öf–ÆRÖf–ÆR×&Vâ"FF×&VçFƒÒ"r²W66T‡FÖÂ†gVÆÅF‚’²r"FF×&VçW&ÃÒ"r²W66T‡FÖÂ‡W&Â’²r"FF×&VçF—FÆSÒ"r²W66T‡FÖÂ†–æfòçF—FÆR’²r"&–ÖÆ&VÃÒ%&VæÖRÆ–æ²"F—FÆSÒ%&VæÖR#ãÇ7frf–Wt&÷ƒÒ##B#B"f–ÆÃÒ&æöæR"7G&ö¶SÒ&7W'&VçD6öÆ÷""7G&ö¶R×v–GFƒÒ#""7G&ö¶RÖÆ–æV6Ò'&÷VæB"7G&ö¶RÖÆ–æV¦ö–ãÒ'&÷VæB"&–Ö†–FFVãÒ'G'VR#ãÇF‚CÒ$Ó"#ƒ’"óãÇF‚CÒ$ÓbãR2ãV"ã""ã"24Ãr–ÂÓBÓE¢"óãÂ÷7fsãÂö'WGFöãâp¢¢rs°¢&WGW&âsÆF—b6Æ73Ò'&öf–ÆRÖf–ÆR&öf–ÆRÖf–ÆRÒÖÆ–æ²#âr°¢sÆ6Æ73Ò'&öf–ÆRÖf–ÆRÖæÖR"‡&VcÒ"r²W66T‡FÖÂ‡W&Â’²r"F&vWCÒ%ö&Ææ²"&VÃÒ&æö÷VæW""F—FÆSÒ"r²W66T‡FÖÂ‡W&Â’²r#åÅÇVCƒ6EÅÇVFCrr²W66T‡FÖÂ†Æ&Â’²rÅÇS#“sÂöâr²&Vâ²FVÂ²sÂöF—câs°¢×Ð¢&WGW&âsÆF—b6Æ73Ò'&öf–ÆRÖf–ÆR#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&öf–ÆRÖf–ÆRÖæÖR&öf–ÆRÖf–ÆRÖ÷Vâ"FFÖ÷VçFƒÒ"r²W66T‡FÖÂ†gVÆÅF‚’²r"FFÖ÷VææÖSÒ"r²W66T‡FÖÂ†æÖR’²r"F—FÆSÒ%&Wf–Wrr²W66T‡FÖÂ†æÖR’²r#âr²W66T‡FÖÂ†æÖR’²sÂö'WGFöãâr°¢‡6—¦RòsÇ7â6Æ73Ò'&öf–ÆRÖf–ÆR×6—¦R#âr²W66T‡FÖÂ‡6—¦R’²sÂ÷7ãâr¢rr’°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&öf–ÆRÖf–ÆRÖFÂ"FFÖFÇFƒÒ"r²W66T‡FÖÂ†gVÆÅF‚’²r"FFÖFÆæÖSÒ"r²W66T‡FÖÂ†æÖR’²r"&–ÖÆ&VÃÒ$F÷væÆöBr²W66T‡FÖÂ†æÖR’²r"F—FÆSÒ$F÷væÆöB#âr²$ôd”ÄUôDÅô”4ôâ²sÂö'WGFöãâr°¢FVÂ²sÂöF—câs°¢×Ð¢òòFVÆVvFVB&Wf–WròF÷væÆöBò&VæÖRòFVÆWFRf÷"f–ÆR6öçF–æW"†FFVBöæ6R’à¢gVæ7F–öâ÷v—&U&öf–ÆTf–ÆT6öçF–æW"‚F2ÂöäFVÆWFRÂöå&VæÖR’·°¢–b‚F2ÇÂF2æFF6WBæf5v—&VB’&WGW&ã°¢F2æFF6WBæf5v—&VBÒss°¢F2æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢f"BÒRçF&vWC²–b‚BÇÂBæ6Æ÷6W7B’&WGW&ã°¢f"÷ÒBæ6Æ÷6W7B‚u¶FFÖ÷VçF…Òr“²–b†÷’·²Rç&WfVçDFVfVÇB‚“²÷&öf–ÆU&Wf–Wr†÷ævWDGG&–'WFR‚vFFÖ÷VçF‚r’Â÷ævWDGG&–'WFR‚vFFÖ÷VææÖRr’“²&WGW&ã²×Ð¢f"FÂÒBæ6Æ÷6W7B‚u¶FFÖFÇF…Òr“²–b†FÂ’·²Rç&WfVçDFVfVÇB‚“²÷&öf–ÆTF÷væÆöB†FÂævWDGG&–'WFR‚vFFÖFÇF‚r’ÂFÂævWDGG&–'WFR‚vFFÖFÆæÖRr’“²&WGW&ã²×Ð¢f"&RÒBæ6Æ÷6W7B‚u¶FF×&VçF…Òr“²–b‡&Rbböå&VæÖR’·²Rç&WfVçDFVfVÇB‚“²öå&VæÖR‡&RævWDGG&–'WFR‚vFF×&VçF‚r’Â&RævWDGG&–'WFR‚vFF×&VçW&Âr’Â&RævWDGG&–'WFR‚vFF×&VçF—FÆRr’“²&WGW&ã²×Ð¢f"FRÒBæ6Æ÷6W7B‚u¶FFÖFVÇF…Òr“²–b†FRbböäFVÆWFR’·²Rç&WfVçDFVfVÇB‚“²öäFVÆWFR†FRævWDGG&–'WFR‚vFFÖFVÇF‚r’ÂFRævWDGG&–'WFR‚vFFÖFVÆæÖRr’“²&WGW&ã²×Ð¢×Ò“°¢×Ð¢gVæ7F–öâ&VæFW$×•&öf–ÆR‚’·°¢f"†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö×—&öf–ÆRr“°¢–b‚†÷7B’&WGW&ã°¢f"ÖTæÖRÒvWD6öÆÆ$æÖR‚“°¢–b‚ÖTæÖR’·°¢†÷7Bæ–ææW$…DÔÂÒsÆF—b6Æ73Ò'&öf–ÆR×w&#ãÇ6Æ73Ò'VWVRÖ–çG&ò×–WbÖ–çG&ò#ãÇ7G&öæså&öf–ÆRãÂ÷7G&öæsâ6WB–÷W"æÖR‡F÷×&–v‡BfF"g&'#²6öÖVöæRVÇ6R’Fò'V–ÆB–÷W"&öf–ÆR÷"6VRF†RFVÒb33“·2ãÂ÷ãÂöF—câs°¢&WGW&ã°¢×Ð¢f"ÖT¶W’Ò÷&öf–ÆT¶W’†ÖTæÖR“°¢†÷7Bæ–ææW$…DÔÂÒsÆF—b6Æ73Ò'&öf–ÆR×w&#ãÇ6Æ73Ò'VWVRÖ–çG&ò×–WbÖ–çG&ò#äÆöF–ær&öf–ÆW2f†VÆÆ—³Â÷ãÂöF—câs°¢òòWfW'–öæRw2FW‡B‡FVÕ÷&öf–ÆW2’²WfW'–öæRv†ò†2f–ÆW2‡7F÷&vP¢òòföÆFW'2’Â–â&ÆÆVÂÂ6òF†RF—&V7F÷'’—26ö×ÆWFRâ&÷F‚6öçfW'B¢òò&V¦V7F–öâFò6fRV×G’fÇVR6òöæRf–Æ–ærFöW6âwB&Ææ²F†Rf–Wrà¢&öÖ—6RæÆÂ…°¢6"æg&öÒ‚wFVÕ÷&öf–ÆW2r’ç6VÆV7B‚r¢r’çF†Vâ†gVæ7F–öâ‡"’·²&WGW&â#²×ÒÂgVæ7F–öâ‚’·²&WGW&â·²W'&÷#¢G'VRÂFF¢µÒ×Ó²×Ò’À¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æÆ—7B‚rrÂ·²Æ–Ö—C¢#×Ò’çF†Vâ†gVæ7F–öâ‡"’·²&WGW&â#²×ÒÂgVæ7F–öâ‚’·²&WGW&â·²FF¢µÒ×Ó²×Ò¢Ò’çF†Vâ†gVæ7F–öâ‡&W2’·°¢f"&÷w5&W7Ò&W5³ÒÂföÆE&W7Ò&W5³Ó°¢f"F$Ö—76–ærÒ‡&÷w5&W7bb&÷w5&W7æW'&÷"“°¢f"&÷w2Ò‡&÷w5&W7bb&÷w5&W7æFF’ÇÂµÓ°¢f"'”¶W’Ò··×Ó°¢&÷w2æf÷$V6‚†gVæ7F–öâ‡"’·²'”¶W•·"çW'6öåÒÒ#²×Ò“°¢f"föÆFW'2Ò‚†föÆE&W7bbföÆE&W7æFF’ÇÂµÒ’æÖ†gVæ7F–öâ†b’·²&WGW&âbææÖS²×Ò¢æf–ÇFW"†gVæ7F–öâ†â’·²&WGW&ââbbâÓÒræV×G”föÆFW%Æ6V†öÆFW"s²×Ò“°¢÷–çD×•&öf–ÆR††÷7BÂÖT¶W’ÂÖTæÖRÂ'”¶W’Â&÷w2ÂföÆFW'2ÂF$Ö—76–ær“°¢×Ò“°¢×Ð¢òòöæR&VBÖöæÇ’W'6öâ6&Bf÷"F†RF—&V7F÷'“¢æÖR²&öÆRÂF†V—"w&—GFVà¢òòf–VÆG2ÂæBÖFW&–Ç26Æ÷Bf–ÆÆVB–â7–æ2'’öÆöEFVÖÖFTf–ÆW2à¢òòV6‚FVÖÖFRw2Æ–æ¶VD–â(	BF†RæÖRÆ–æ·2Fò—BÂæBF†RgVÆÂU$Â6†÷w0¢òò&–v‡B&VÆ÷r‡6òævVÆ6â6÷’÷7FR—B–çFòâ÷&væ—¦W"VÖ–Â’à¢òò)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y ¢òò÷WG&V6‚6ö×÷6W"(	BF†RVÖ–ÂÂBF†RÖöÖVçBævVÆæVVG2—@¢òð¢òò6†Rw&—FW2FòF†R÷&væ—6W"–ÖÖVF–FVÇ’gFW"Ö&¶–ærâWfVç@¢òò7V&Ö—GFVBÂæB†W"7FFVBg&–7F–öâ—2&RÖ6†V6¶–ærF†RWfVçBæÖRæ@¢òòF†RFFW2WfW'’F–ÖR&Vf÷&R7F–ærFV×ÆFRâ6òF†—2Æ—fW2ôâF†P¢òòWfVçBÂV'2F†RÖöÖVçB7V&Ö—GFVB—26WBÂæB6öÖW2&RÖf–ÆÆVBg&öÐ¢òòF†R&÷r6†R—2Ç&VG’Æöö¶–ærBâæ÷F†–ærFòÆöö²WÂæ÷F†–ærFð¢òò&R×G—RÂæB$Ö&²6VçB"Gfæ6W2F†RWfVçBFò–æ—F–Â÷WG&V6‚(	BF†P¢òò7FWF†BW6VBFòvWB&V6÷&FVB2föÆÆ÷r×Wà¢òð¢òòGvòf&–çG2&V6W6RF†R—F6‚F–ffW'2'’vVöw&‡“¢÷WG6–FRF†RU2F†P¢òòÖ–FFÆRV7B&öw&ÖÖR—2F†RÆVBÂ–ç6–FRF†RU2—B6—G2&VÆ÷rF†P¢òò6–væGW&R26öçFW‡B&F†W"F†âF†R†VFÆ–æRà¢òð¢òòÆ6V†öÆFW'2&R·7V&R'&6¶WG5ÒÂæ÷B'&6W2(	BF†—2f–ÆR—2—F†öà¢òòæf÷&ÖB‚’FV×ÆFRæBWfW'’'&6R–â—B†2Fò&RF÷V&ÆVBà¢òò)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y)Y ¢òò)H)H÷WG&V6‚VÖ–ÂG&gFW#¢$TÔõdTB##bÓ‚ÓR)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòF†R$G&gB÷WG&V6‚"'WGFöâÂ—G2æVÂÂævVÆw2FV×ÆFRVF—F÷"æBF†P¢òòv†öÆR6ö×÷6RVæv–æR„%ôÔ”ÅõÄ4T„ôÄDU%2ò%ôÔ”ÅôDTdTÅE2ÂöÖ–Ä—5U2À¢òòöÖ–ÅFV×ÆFW2ÂöÖ–ÄGf–6RÂöÖ–Äf–ÆÂÂöÖ–Ä7G‚ÂöÖ–Å–6µ6W76–öâÀ¢òòv–æF÷ræ$Ö–ÄG&gBÂv–æF÷ræ%&VæFW$Ö–ÅæVÂ’&RvöæR(	B‡W&ÆW’6¶VBf÷ ¢òòF†RG&gFW"÷WBf÷"WfW'–öæRâæ÷F†–ær6ö×÷6W2VÖ–Â–âF†RG&6¶W"æ÷s°¢òòævVÆw&—FW2†W'2–â†W"Ö–Â6Æ–VçBà¢òòF†RFVÕ÷&öf–ÆW2æVÖ–Å÷FV×ÆFU÷W2òövÆö&Â4ôÅTÔå2&RÆVgBÆöæS ¢òòG&÷–ær6öÇVÖç2æVVG2Ö–w&F–öâæBF†W’†öÆBFW‡B6†RÖ’vçB&6²à¢f"$ôd”ÄUôÄ”ä´TD”âÒ·°¢F†÷#¢v‡GG3¢ò÷wwræÆ–æ¶VF–âæ6öÒö–â÷F†÷&W&ç7G76öâòrÀ¢fW&Ö¢v‡GG3¢ò÷wwræÆ–æ¶VF–âæ6öÒö–âöçW&w7fW&ÖòrÀ¢6&Æ÷3¢v‡GG3¢ò÷wwræÆ–æ¶VF–âæ6öÒö–âö6&Æ÷2ÖÂÖ6†6öâÖÆÖV–FóöÆö6ÆSÖVârÀ¢¦W&öÖS¢v‡GG3¢ò÷wwræÆ–æ¶VF–âæ6öÒö–âö¦W&öÖWv÷WFW'2òrÀ¢¦öS¢v‡GG3¢ò÷wwræÆ–æ¶VF–âæ6öÒö–âö¦öVÆÆÆW’òrÀ¢66÷GC¢v‡GG3¢ò÷wwræÆ–æ¶VF–âæ6öÒö–â÷6ÇöÆÆ6²òrÀ¢¦–Ó¢v‡GG3¢ò÷wwræÆ–æ¶VF–âæ6öÒö–âö¦–Ö6‡Væw&öf–ÆRòp¢×Ó°¢gVæ7F–öâöF—&V7F÷'”6&D‡FÖÂ†¶W’Â&÷rÂf–ÆW4–BÂ6äVF—B’·°¢f"BÒ÷&öf–ÆTF—7Æ’‡&÷rÂ¶W’“°¢f"&öÆRÒ÷&öf–ÆU&öÆR†¶W’“°¢f"Æ’Ò$ôd”ÄUôÄ”ä´TD”åµ7G&–ær†¶W’’çFôÆ÷vW$66R‚•ÒÇÂrs°¢f"æÖTVÂÒÆ¢òsÆ6Æ73Ò'&öf–ÆR×FÒÖæÖR"‡&VcÒ"r²W66T‡FÖÂ†Æ’’²r"F&vWCÒ%ö&Ææ²"&VÃÒ&æö÷VæW""F—FÆSÒ$÷Vâr²W66T‡FÖÂ†B’²röâÆ–æ¶VD–â#âr²W66T‡FÖÂ†B’²sÂöâp¢¢sÇ7â6Æ73Ò'&öf–ÆR×FÒÖæÖR#âr²W66T‡FÖÂ†B’²sÂ÷7ãâs°¢f"‚ÒsÆF—b6Æ73Ò'&öf–ÆR×FVÖÖFR#ãÆF—b6Æ73Ò'&öf–ÆR×FÒÖ†VB#âr°¢sÇ7â6Æ73Ò'&öf–ÆRÖfF"#âr²W66T‡FÖÂ‚†BÇÂsòr’æ6†$Bƒ’çFõWW$66R‚’’²sÂ÷7ãâr°¢æÖTVÂ°¢‡&öÆRòsÇ7â6Æ73Ò'&öf–ÆR×FÒ×&öÆR#âr²W66T‡FÖÂ‡&öÆR’²sÂ÷7ãâr¢rr’²sÂöF—câr°¢†Æ’òsÆ6Æ73Ò'&öf–ÆR×FÒÖÆ–æ¶VF–â"‡&VcÒ"r²W66T‡FÖÂ†Æ’’²r"F&vWCÒ%ö&Ææ²"&VÃÒ&æö÷VæW"#âr²W66T‡FÖÂ†Æ’’²sÂöâr¢rr“°¢–b‡&÷r’·°¢$ôd”ÄUôd”TÄE2æf÷$V6‚†gVæ7F–öâ†b’·°¢–b‚&÷u¶bæµÒ’&WGW&ã°¢‚³ÒsÆF—b6Æ73Ò'&öf–ÆR×FÒÖf–VÆB#ãÆF—b6Æ73Ò&²#âr²W66T‡FÖÂ†bæÆ&VÂ’²sÂöF—cãÆF—b6Æ73Ò'b#âr²W66T‡FÖÂ‡&÷u¶bæµÒ’²sÂöF—cãÂöF—câs°¢×Ò“°¢×Ð¢òòævVÆ†6äVF—B’vWG2F†R4ÔRVF—F&ÆRW"×6Æ÷BT’6†R†2öâ†W"÷vâ(	@¢òòWÆöBòFBÖÆ–æ²òFVÆWFRf÷"F†—2FVÖÖFRâWfW'–öæRVÇ6R—2&VBÖöæÇ’à¢–b†6äVF—B’·°¢‚³ÒsÆF—b6Æ73Ò'&öf–ÆR×FÒÖf–VÆB#ãÆF—b6Æ73Ò&²#äÖFW&–Ç3ÂöF—câr°¢$ôd”ÄUôÔDU$”Å2æÖ†gVæ7F–öâ†Ò’·²&WGW&âöÖFW&–Å6Æ÷D‡FÖÂ†¶W’ÂÒÂ—57W÷'EW'6öâ†¶W’’“²×Ò’æ¦ö–â‚rr’²sÂöF—câs°¢×ÒVÇ6R·°¢‚³ÒsÆF—b6Æ73Ò'&öf–ÆR×FÒÖf–VÆB#ãÆF—b6Æ73Ò&²#äÖFW&–Ç3ÂöF—cãÆF—b6Æ73Ò'&öf–ÆR×FÒÖf–ÆW2"–CÒ"r²f–ÆW4–B²r#ãÇ6Æ73Ò'&öf–ÆRÖf–ÆRÖV×G’#äÆöF–ærf†VÆÆ—³Â÷ãÂöF—cãÂöF—câs°¢×Ð¢&WGW&â‚²sÂöF—câs°¢×Ð¢òò&VBÖöæÇ’ÖFW&–Ç2f÷"FVÖÖFR(	Bw&÷WVB'’6Æ÷BÂF÷væÆöBöæÇ’à¢òòÆ—7G2V6‚ÖFW&–Â6FVv÷'’ƒÇW'6öãâóÆ6Câþ(
b’æBVæG2F†R6Æ÷G0¢òòF†B†fRf–ÆW3²6Æ–6·2&R†æFÆVB'’FVÆVvF–öâ6ò7–æ2VæG2v÷&²à¢gVæ7F–öâöÆöEFVÖÖFTf–ÆW2‡W'6öä¶W’Â6öçF–æW$–B’·°¢f"F2ÒFö7VÖVçBævWDVÆVÖVçD'”–B†6öçF–æW$–B“°¢–b‚F2’&WGW&ã°¢F2æ–ææW$…DÔÂÒrs°¢÷v—&U&öf–ÆTf–ÆT6öçF–æW"‚F2ÂçVÆÂ“²òò&Wf–Wr²F÷væÆöBÂæòFVÆWFR‡&VBÖöæÇ’¢f"VæF–ærÒ$ôd”ÄUôÔDU$”Å2æÆVæwF‚Âç•6†÷vâÒfÇ6S°¢$ôd”ÄUôÔDU$”Å2æf÷$V6‚†gVæ7F–öâ†Ò’·°¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æÆ—7B‡W'6öä¶W’²ròr²Òæ²Â·²Æ–Ö—C¢S×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢f"—FV×2Ò‚‡&W7bb&W7æFF’ÇÂµÒ’æf–ÇFW"†gVæ7F–öâ†b’·²&WGW&âbææÖRbbbææÖRÓÒræV×G”föÆFW%Æ6V†öÆFW"s²×Ò“°¢–b†—FV×2æÆVæwF‚’·°¢ç•6†÷vâÒG'VS°¢f"‚ÒsÆF—b6Æ73Ò'FÒÖÖBÖw&÷W#ãÆF—b6Æ73Ò'FÒÖÖBÖÆ&VÂ#âr²W66T‡FÖÂ†ÒæÆ&VÂ’²sÂöF—câr°¢—FV×2æÖ†gVæ7F–öâ†b’·°¢f"6—¦RÒ†bæÖWFFFbbbæÖWFFFç6—¦R’òöf×D'—FW2†bæÖWFFFç6—¦R’¢rs°¢&WGW&âöÖDf–ÆU&÷t‡FÖÂ‡W'6öä¶W’²ròr²Òæ²²ròr²bææÖRÂbææÖRÂ6—¦RÂfÇ6R“°¢×Ò’æ¦ö–â‚rr’²sÂöF—câs°¢F2æ–ç6W'DF¦6VçD…DÔÂ‚v&Vf÷&VVæBrÂ‚“°¢×Ð¢–b‚Ò×VæF–ærÓÓÒbbç•6†÷vâ’F2æ–ææW$…DÔÂÒsÇ6Æ73Ò'&öf–ÆRÖf–ÆRÖV×G’#âfÖF6ƒ³Â÷âs°¢×Ò“°¢×Ò“°¢×Ð¢gVæ7F–öâ÷–çD×•&öf–ÆR††÷7BÂÖT¶W’ÂÖTæÖRÂ'”¶W’ÂÆÅ&÷w2ÂföÆFW'2ÂF$Ö—76–ær’·°¢f"7W÷'BÒ—57W÷'EW'6öâ†ÖTæÖR“°¢f"×•&÷rÒ'”¶W•¶ÖT¶W•ÒÇÂçVÆÃ°¢òòWfW'–öæRv†ò†2FFVBç—F†–æs¢&öf–ÆR&÷rv—F‚FW‡BÂ÷"f–ÆW2à¢f"¶W•6WBÒ··×Ó°¢†ÆÅ&÷w2ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ‡"’·°¢–b‡"çW'6öâbb‡"æ&–òÇÂ"çF÷–72ÇÂ"ç7E÷FÆ·2ÇÂ"ææ÷FW2’’¶W•6WE·"çW'6öåÒÒ°¢×Ò“°¢†föÆFW'2ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†²’·²¶W•6WE¶µÒÒ²×Ò“°¢f"F—$¶W—2Òö&¦V7Bæ¶W—2†¶W•6WB’æf–ÇFW"†gVæ7F–öâ†²’·²&WGW&â7W÷'BÇÂ²ÓÒÖT¶W“²×Ò“°¢F—$¶W—2ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&â÷&öf–ÆTF—7Æ’†'”¶W•¶ÒÂ’æÆö6ÆT6ö×&R…÷&öf–ÆTF—7Æ’†'”¶W•¶%ÒÂ"’“²×Ò“° ¢f"‡FÖÂÒsÆF—b6Æ73Ò'&öf–ÆR×w&#âs°¢–b†F$Ö—76–ær’·°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'&öf–ÆR×6WGWÖæ÷FR#ãÇ7G&öæsäöæR×F–ÖR6WGWæVVFVBãÂ÷7G&öæsâF†R&öf–ÆR7F÷&R—6âb33“·B–âF†RFF&6R–WBÂ6òæ÷F†–ær†W&Rv–ÆÂ6fR÷"6†÷râ'VâF†RÆ6öFSçFVÕ÷&öf–ÆW3Âö6öFSâ6WGWöæ6RÂF†Vâ&VÆöBãÂöF—câs°¢×Ð¢òò„ævVÆw2÷WG&V6‚×FV×ÆFRVF—F÷"&VÖ÷fVB##bÓ‚ÓRv—F‚F†P¢òò$G&gB÷WG&V6‚"'WGFöâ—BfVB(	Bv—F‚æ÷F†–ær6ö×÷6–ærâVÖ–ÂÂF†P¢òòFV×ÆFW2VF—FVBæ÷F†–ærâ†W"VÖ–ÂFV×ÆFRd”ÄR6Æ÷B&VÆ÷r7F—2â¢òò7W÷'BFöâwB7V²Â'WBF†W’7F–ÆÂ¶VWÖFW&–Ç2(	BævVÆw2Ö7FW ¢òòVÖ–ÂFV×ÆFR—2f–ÆRÂæB—B&VÆöæw2Fò†W"&F†W"F†âFòç’öæP¢òò7V¶W"„‡W&ÆW’##bÓrÓ3’â6ÖRF‡&VR6Æ÷G2Â÷vâv÷&F–ærà¢–b‡7W÷'B’·°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'&öf–ÆRÖ6&B#âr°¢sÆF—b6Æ73Ò'&öf–ÆR×6V7F–öâÖ†VB#å–÷W"ÖFW&–Ç3ÂöF—câr°¢sÇ6Æ73Ò'&öf–ÆR×6V7F–öâ×7V"#å–÷W'2Âæ÷B7V¶W%ÇS#—2ÇS#Bv†B–÷R6VæBöâF†V—"&V†ÆbãÂ÷âs°¢$ôd”ÄUôÔDU$”Å2æf÷$V6‚†gVæ7F–öâ†Ò’·²‡FÖÂ³ÒöÖFW&–Å6Æ÷D‡FÖÂ†ÖT¶W’ÂÒÂG'VR“²×Ò“°¢‡FÖÂ³ÒsÂöF—câs°¢×Ð¢òò7W÷'B„ævVÆô‡W&ÆW’’6ö÷&F–æFR(	BF†W’FöâwB7V²Â6òF†W’vWBF†P¢òòFVÒF—&V7F÷'’7G&–v‡Bv’Âæ÷BF†V—"÷vâ7V¶W"6&Bà¢–b‚7W÷'B’·°¢f"F—7Ò÷&öf–ÆTF—7Æ’†×•&÷rÂÖT¶W’’ÇÂÖTæÖS°¢f"–æ—F–ÂÒW66T‡FÖÂ‚†F—7ÇÂsòr’æ6†$Bƒ’çFõWW$66R‚’“°¢f"&öÆRÒ÷&öf–ÆU&öÆR†ÖT¶W’“°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'&öf–ÆRÖ6&B#âr°¢sÆF—b6Æ73Ò'&öf–ÆRÖ6&BÖ†VB#âr°¢sÇ7â6Æ73Ò'&öf–ÆRÖfF"&öf–ÆRÖfF"ÖÆr#âr²–æ—F–Â²sÂ÷7ãâr°¢sÇ7â6Æ73Ò'&öf–ÆRÖ–B#ãÇ7â6Æ73Ò'&öf–ÆR×v†ò#âr²W66T‡FÖÂ†F—7’²sÂ÷7ãâr°¢‡&öÆRòsÇ7â6Æ73Ò'&öf–ÆR×&öÆR#âr²W66T‡FÖÂ‡&öÆR’²sÂ÷7ãâr¢rr’²sÂ÷7ãâr°¢sÂöF—câs°¢òò)H)H7V¶–ærÖFW&–Ç2(	BF†Rö–çBöbF†R&öf–ÆS¢&VG’×Fò×6Væ@¢òò¶—BÂ÷&væ—¦VB'’v†B÷&væ—¦W'26²f÷"âV6‚6Æ÷B—2—G2÷và¢òòWÆöB²Æ—7Bà¢‡FÖÂ³ÒsÆF—b6Æ73Ò'&öf–ÆR×6V7F–öâÖ†VB#å7V¶–ærÖFW&–Ç3ÂöF—câr°¢sÇ6Æ73Ò'&öf–ÆR×6V7F–öâ×7V"#ä†VÇævVÆ÷&væ—¦R–÷W"7V¶–ærÖFW&–Ç2ãÂ÷âs°¢$ôd”ÄUôÔDU$”Å2æf÷$V6‚†gVæ7F–öâ†Ò’·²‡FÖÂ³ÒöÖFW&–Å6Æ÷D‡FÖÂ†ÖT¶W’ÂÒ“²×Ò“°¢òò)H)Hw&—GFVâ&öf–ÆR(	B&–ò‡6fVBf–VÆB²†÷fW"ÖVF—B’æBæ÷FW2÷F÷–70¢òò†FBöVF—BöFVÆWFRÆ—7G2’âV6‚6fW2–ÖÖVF–FVÇ“²f–ÆÆVB'’÷e&VæFW$&÷WBà¢÷ev†òÒ·²¶W“¢ÖT¶W’ÂæÖS¢ÖTæÖR×Ó°¢÷d×’Ò·²&–ó¢†×•&÷rbb×•&÷ræ&–ò’ÇÂrrÂæ÷FW3¢†×•&÷rbb×•&÷rææ÷FW2’ÇÂrrÂF÷–73¢†×•&÷rbb×•&÷rçF÷–72’ÇÂrr×Ó°¢÷dVF—BÒ·²f–VÆC¢çVÆÂÂ–æFWƒ¢Ó×Ó°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'&öf–ÆR×6V7F–öâÖ†VB#ä&÷WB–÷RÇ7â6Æ73Ò'&öf–ÆR×6V7F–öâÖ÷B#æ÷F–öæÂÅÇS#r6fW22–÷RvóÂ÷7ããÂöF—câs°¢‡FÖÂ³ÒsÆF—b–CÒ'bÖ&÷WB#ãÂöF—câs°¢‡FÖÂ³ÒsÂöF—câs²òòVæBç&öf–ÆRÖ6&@¢×Ð¢òòF†RW"×W'6öâF—&V7F÷'’(	BWfW'–öæRw2&öf–ÆR²ÖFW&–Ç2Â'’W'6öâà¢f"F—%F—FÆRÒ7W÷'BòuFVÒ&öf–ÆW2r¢uF†R&W7BöbF†RFVÒs°¢f"F—$–çG&òÒ7W÷'@¢òtWfW'–öæRb33“·2&–òÂF÷–72ÂF&vWF–æræ÷FW2ÂæBÖFW&–Ç2fÖF6ƒ²'’W'6öââWFFW22V6‚W'6öâVF—G2F†V—"&öf–ÆRâp¢¢t–b–çFW&W7FVBFòÆV&âÖ÷&R&÷WBF†RFVÒÂF†RföÆÆ÷v–ær—2v†BF†W’b33“·&R7V¶–æröâæBF†V—"&6¶w&÷VæG2âs°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'VWVR×6V2Ö†VB"r²‡7W÷'Bòrr¢r7G–ÆSÒ&Ö&v–â×F÷£‡ƒ²"r’²sãÇ7â6Æ73Ò'VWVR×6V2×F—FÆR#âr²F—%F—FÆR²sÂ÷7ããÇ7â6Æ73Ò'VWVR×6V2Ö6÷VçB#âr²F—$¶W—2æÆVæwF‚²sÂ÷7ããÂöF—câr°¢sÇ6Æ73Ò'VWVRÖÖWF"7G–ÆSÒ&Ö&v–ã¢ÓG‚Gƒ²#âr²F—$–çG&ò²sÂ÷âs°¢–b‚F—$¶W—2æÆVæwF‚’·°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'VWVRÖV×G’#äæòöæRb33“·2FFVB&öf–ÆR–WBfÖF6ƒ²v†Vâ6öÖVöæRf–ÆÇ2–âF†V—"&–òÂF÷–72Â÷"WÆöG2f–ÆRÂ—B6†÷w2W†W&R'’W'6öâãÂöF—câs°¢×ÒVÇ6R·°¢F—$¶W—2æf÷$V6‚†gVæ7F–öâ†²Â’’·²‡FÖÂ³ÒöF—&V7F÷'”6&D‡FÖÂ†²Â'”¶W•¶µÒÇÂçVÆÂÂwFÖf–ÆW2Òr²’Â7W÷'B“²×Ò“°¢×Ð¢‡FÖÂ³ÒsÂöF—câs²òòVæBç&öf–ÆR×w& ¢†÷7Bæ–ææW$…DÔÂÒ‡FÖÃ°¢òòWÆöBòFBÖÆ–æ²'WGFöç26''’#Æ¶W“çÃÆ6Câ"(	BöæRv—&–ær6÷fW'2F†R÷và¢òò6&BäB†f÷"ævVÆ’WfW'’VF—F&ÆRFVÖÖFR6Æ÷B–âF†RF—&V7F÷'’à¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FFÖÖB×WÆöEÒr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²f"Ò'FâævWDGG&–'WFR‚vFFÖÖB×WÆöBr’ç7Æ—B‚wÂr“²÷WÆöE&öf–ÆTf–ÆR‡³ÒÂ³Ò“²×Ò“°¢×Ò“°¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FFÖÖBÖÆ–æµÒr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²f"Ò'FâævWDGG&–'WFR‚vFFÖÖBÖÆ–æ²r’ç7Æ—B‚wÂr“²öFE&öf–ÆTÆ–æ²‡³ÒÂ³Ò“²×Ò“°¢×Ò“°¢–b‚7W÷'B’·°¢f"F&÷WBÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖ&÷WBr“°¢–b‚F&÷WB’·²÷ev—&T&÷WB‚F&÷WB“²÷e&VæFW$&÷WB‚“²×Ð¢×Ð¢òò&÷F‚F‡2&VæFW"ÖT¶W’w26Æ÷G2æ÷r(	B7W÷'Bf–%–÷W"ÖFW&–Ç2"À¢òòWfW'–öæRVÇ6R–ç6–FRF†V—"7V¶W"6&Bà¢$ôd”ÄUôÔDU$”Å2æf÷$V6‚†gVæ7F–öâ†Ò’·²öÆöE&öf–ÆTf–ÆW2†ÖT¶W’ÂÒæ²ÂF$Ö—76–ær“²×Ò“°¢òò‡bÖÖ–Â×6fR†æFÆW"&VÖ÷fVBv—F‚F†RFV×ÆFRVF—F÷"&÷fRâ¢òòF—&V7F÷'’ÖFW&–Ç3¢ævVÆ‡7W÷'B’vWG2VF—F&ÆR6Æ÷G2†ÆöBV6‚“°¢òòWfW'–öæRVÇ6RvWG2F†R&VBÖöæÇ’w&÷WVBÆ—7Bà¢F—$¶W—2æf÷$V6‚†gVæ7F–öâ†²Â’’·°¢–b‡7W÷'B’·²$ôd”ÄUôÔDU$”Å2æf÷$V6‚†gVæ7F–öâ†Ò’·²öÆöE&öf–ÆTf–ÆW2†²ÂÒæ²ÂF$Ö—76–ær“²×Ò“²×Ð¢VÇ6R·²öÆöEFVÖÖFTf–ÆW2†²ÂwFÖf–ÆW2Òr²’“²×Ð¢×Ò“°¢×Ð¢gVæ7F–öâ÷6fT×•&öf–ÆR†ÖT¶W’ÂÖTæÖR’·°¢f"&÷rÒ·²W'6öã¢ÖT¶W’ÂF—7Æ•öæÖS¢ÖTæÖRÂWFFVEö'“¢ÖTæÖRÂWFFVEöC¢æWrFFR‚’çFô•4õ7G&–ær‚’×Ó°¢$ôd”ÄUôd”TÄE2æf÷$V6‚†gVæ7F–öâ†b’·²f"VÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÒr²bæ²“²&÷u¶bæµÒÒVÂòVÂçfÇVR¢rs²×Ò“°¢f"G6fRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wb×6fRr“°¢–b‚G6fR’G6fRç6WDGG&–'WFR‚v&–Ö'W7’rÂwG'VRr“°¢6"æg&öÒ‚wFVÕ÷&öf–ÆW2r’çW6W'B‡&÷rÂ·²öä6öæfÆ–7C¢wW'6öâr×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‚G6fR’G6fRç&VÖ÷fTGG&–'WFR‚v&–Ö'W7’r“°¢–b‡&W7bb&W7æW'&÷"’·°¢7FGW2‚t6÷VÆBæ÷B6fR–÷W"&öf–ÆS¢r²&W7æW'&÷"æÖW76vR²‚÷FVÕ÷&öf–ÆW7Æ6öÇVÖçÇ&VÆF–öçÆFöW2æ÷BW†—7Bö’çFW7B‡&W7æW'&÷"æÖW76vR’òrÅÇS#BF†RöæR×F–ÖRFVÕ÷&öf–ÆW26WGWÖ’7F–ÆÂ&RVæF–ærâr¢rr’ÂvW'&÷"r“°¢&WGW&ã°¢×Ð¢f"Fö²ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wb×6fVBr“°¢–b‚Fö²’·²Fö²æ†–FFVâÒfÇ6S²6WEF–ÖV÷WB†gVæ7F–öâ‚’·²–b‚Fö²’Fö²æ†–FFVâÒG'VS²×ÒÂ#S“²×Ð¢fÆ6„ö²‚u&öf–ÆR6fVBr“°¢òò&Vg&W6‚F†RF7FR66†R6òF†RæWr&öf–ÆRFW‡BW'6öæÆ—¦W0¢òò7VvvW7F–öç2&–v‡Bv’†æ÷B§W7BöâæW‡BÆöB’à¢öÆöE&öf–ÆUF7FR‚“°¢×Ò“°¢×Ð¢òò)H)H&÷WB×–÷R†÷vâ&öf–ÆR“¢6fVB&–òv—F‚†÷fW"×Væ6–ÂFòVF—BÂæ@¢òòF&vWF–æræ÷FW2òFÆ·2bF÷–722FBöVF—BöFVÆWFRÄ•5E2âÆ—7G2&R7F÷&V@¢òòæWvÆ–æRÖ¦ö–æVB–âF†R6ÖRFVÕ÷&öf–ÆW2FW‡B6öÇVÖç2†æò66†VÖ6†ævR’à¢òòWfW'’7F–öâ6fW2–ÖÖVF–FVÇ’†gVÆÂ×&÷rW6W'BÂ6òæ÷F†–ærVÇ6R—2Æ÷7B’à¢f"eõTä4”ÂÒsÇ7frf–Wt&÷ƒÒ##B#B"f–ÆÃÒ&æöæR"7G&ö¶SÒ&7W'&VçD6öÆ÷""7G&ö¶R×v–GFƒÒ#""7G&ö¶RÖÆ–æV6Ò'&÷VæB"7G&ö¶RÖÆ–æV¦ö–ãÒ'&÷VæB"&–Ö†–FFVãÒ'G'VR#ãÇF‚CÒ$Ó"#ƒ’"óãÇF‚CÒ$ÓbãR2ãV"ã""ã"24Ãr–ÂÓBÓE¢"óãÂ÷7fsâs°¢f"eõE$4‚ÒsÇ7frf–Wt&÷ƒÒ##B#B"f–ÆÃÒ&æöæR"7G&ö¶SÒ&7W'&VçD6öÆ÷""7G&ö¶R×v–GFƒÒ#""7G&ö¶RÖÆ–æV6Ò'&÷VæB"7G&ö¶RÖÆ–æV¦ö–ãÒ'&÷VæB"&–Ö†–FFVãÒ'G'VR#ãÇF‚CÒ$Ó2fƒ‚"óãÇF‚CÒ$Ó’gcF""Ó"$ƒv""Ó"Ó%cb"óãÇF‚CÒ$Ó‚ecF"""Ó&ƒF"""'c""óãÂ÷7fsâs°¢f"÷d×’Ò·²&–ó¢rrÂæ÷FW3¢rrÂF÷–73¢rr×Ó°¢f"÷dVF—BÒ·²f–VÆC¢çVÆÂÂ–æFWƒ¢Ó×Ó°¢f"÷ev†òÒ·²¶W“¢rrÂæÖS¢rr×Ó°¢gVæ7F–öâ÷dÆ–æW2†¶W’’·²&WGW&â7G&–ær…÷d×•¶¶W•ÒÇÂrr’ç7Æ—B‚õÅÇ#õÅÆâò’æÖ†gVæ7F–öâ‡2’·²&WGW&â2çG&–Ò‚“²×Ò’æf–ÇFW"„&ööÆVâ“²×Ð¢gVæ7F–öâ÷eW'6—7B‚’·°¢f"F6‚Ò·²W'6öã¢÷ev†òæ¶W’ÂF—7Æ•öæÖS¢÷ev†òææÖRÂWFFVEö'“¢÷ev†òææÖRÂWFFVEöC¢æWrFFR‚’çFô•4õ7G&–ær‚’À¢&–ó¢÷d×’æ&–òÇÂrrÂæ÷FW3¢÷d×’ææ÷FW2ÇÂrrÂF÷–73¢÷d×’çF÷–72ÇÂrr×Ó°¢6"æg&öÒ‚wFVÕ÷&öf–ÆW2r’çW6W'B‡F6‚Â·²öä6öæfÆ–7C¢wW'6öâr×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7bb&W7æW'&÷"’·²7FGW2‚t6÷VÆBæ÷B6fS¢r²&W7æW'&÷"æÖW76vR²‚÷FVÕ÷&öf–ÆW7Æ6öÇVÖçÇ&VÆF–öçÆFöW2æ÷BW†—7Bö’çFW7B‡&W7æW'&÷"æÖW76vR’òrÅÇS#BF†RöæR×F–ÖRFVÕ÷&öf–ÆW26WGWÖ’7F–ÆÂ&RVæF–ærâr¢rr’ÂvW'&÷"r“²&WGW&ã²×Ð¢fÆ6„ö²‚u6fVBr“²öÆöE&öf–ÆUF7FR‚“°¢×Ò“°¢×Ð¢gVæ7F–öâ÷d&–ô‡FÖÂ‚’·°¢f"†VBÒsÆF—b6Æ73Ò'bÖf–VÆF†VB#å6†÷'B&–òÇ7â6Æ73Ò&†–çB#åÅÇS#r6÷WÆRöb6VçFVæ6W3Â÷7ããÂöF—câs°¢f"bÒ÷d×’æ&–òÇÂrs°¢–b…÷dVF—Bæf–VÆBÓÓÒv&–òr’·°¢&WGW&âsÆF—b6Æ73Ò'bÖf–VÆB#âr²†VB°¢sÇFW‡F&V6Æ73Ò'bÖ–çWBbÖw&÷r"–CÒ'bÖ&–òÖ–çWB"&÷w3Ò#""FF×bÖfö7W2Æ6V†öÆFW#Ò%Gvò÷"F‡&VR6VçFVæ6W2â÷&væ—¦W"6÷VÆBG&÷7G&–v‡B–çFòâvVæFâ#âr²W66T‡FÖÂ‡b’²sÂ÷FW‡F&Vâr°¢sÆF—b6Æ73Ò'bÖVF—BÖ7F–öç2#ãÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ&–Ö'’"FF×cÒ&&–ò×6fR#å6fSÂö'WGFöããÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ"FF×cÒ&&–òÖ6æ6VÂ#ä6æ6VÃÂö'WGFöããÂöF—cãÂöF—câs°¢×Ð¢–b‚b’&WGW&âsÆF—b6Æ73Ò'bÖf–VÆB#âr²†VB²sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'bÖFBÖ'Fâ"FF×cÒ&&–òÖVF—B#â²FB6†÷'B&–óÂö'WGFöããÂöF—câs°¢&WGW&âsÆF—b6Æ73Ò'bÖf–VÆB#âr²†VB²sÆF—b6Æ73Ò'b×6fVB#ãÆF—b6Æ73Ò'b×6fVB×FW‡B#âr²W66T‡FÖÂ‡b’²sÂöF—câr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'bÖVF—B"FF×cÒ&&–òÖVF—B"F—FÆSÒ$VF—B&–ò"&–ÖÆ&VÃÒ$VF—B&–ò#âr²eõTä4”Â²sÂö'WGFöããÂöF—cãÂöF—câs°¢×Ð¢gVæ7F–öâ÷dÆ—7D‡FÖÂ†¶W’ÂÆ&VÂÂ†–çBÂFE‚’·°¢f"Æ–æW2Ò÷dÆ–æW2†¶W’“°¢f"†VBÒsÆF—b6Æ73Ò'bÖf–VÆF†VB#âr²W66T‡FÖÂ†Æ&VÂ’²rÇ7â6Æ73Ò&†–çB#åÅÇS#rr²W66T‡FÖÂ††–çB’²sÂ÷7ããÂöF—câs°¢f"&÷w2ÒÆ–æW2æÖ†gVæ7F–öâ†Æ–æRÂ’’·°¢–b…÷dVF—Bæf–VÆBÓÓÒ¶W’bb÷dVF—Bæ–æFW‚ÓÓÒ’’·°¢&WGW&âsÆF—b6Æ73Ò'bÖ—FVÒbÖ—FVÒÒÖVF—B#ãÆ–çWB6Æ73Ò'bÖ–çWB"FF×bÖfö7W2FFÖ¶W“Ò"r²¶W’²r"FFÖ“Ò"r²’²r"fÇVSÒ"r²W66T‡FÖÂ†Æ–æR’²r#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ&–Ö'’"FF×cÒ&Æ—7B×6fR"FFÖ¶W“Ò"r²¶W’²r"FFÖ“Ò"r²’²r#å6fSÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ"FF×cÒ&Æ—7BÖ6æ6VÂ#ä6æ6VÃÂö'WGFöããÂöF—câs°¢×Ð¢&WGW&âsÆF—b6Æ73Ò'bÖ—FVÒ#ãÇ7â6Æ73Ò'bÖ—FVÒ×FW‡B#âr²W66T‡FÖÂ†Æ–æR’²sÂ÷7ãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'bÖ—FVÒÖ'Fâ"FF×cÒ&Æ—7BÖVF—B"FFÖ¶W“Ò"r²¶W’²r"FFÖ“Ò"r²’²r"F—FÆSÒ$VF—B"&–ÖÆ&VÃÒ$VF—B#âr²eõTä4”Â²sÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'bÖ—FVÒÖ'FâbÖFVÂ"FF×cÒ&Æ—7BÖFVÂ"FFÖ¶W“Ò"r²¶W’²r"FFÖ“Ò"r²’²r"F—FÆSÒ$FVÆWFR"&–ÖÆ&VÃÒ$FVÆWFR#âr²eõE$4‚²sÂö'WGFöããÂöF—câs°¢×Ò’æ¦ö–â‚rr“°¢f"FBÒsÆF—b6Æ73Ò'bÖFF—FVÒ#ãÇFW‡F&V6Æ73Ò'bÖ–çWBbÖw&÷r"&÷w3Ò#"–CÒ'bÖFBÒr²¶W’²r"FFÖFF¶W“Ò"r²¶W’²r"Æ6V†öÆFW#Ò"r²W66T‡FÖÂ†FE‚’²r#ãÂ÷FW‡F&Vâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'FâbÖFB"FF×cÒ&Æ—7BÖFB"FFÖ¶W“Ò"r²¶W’²r#äFCÂö'WGFöããÂöF—câs°¢&WGW&âsÆF—b6Æ73Ò'bÖf–VÆB#âr²†VB²&÷w2²FB²sÂöF—câs°¢×Ð¢gVæ7F–öâ÷dw&÷r†VÂ’·°¢–b‚VÂ’&WGW&ã°¢òòæWfW"6—¦Rv–ç7B&÷‚F†B†2æòÆ–÷WB–WB(	B†–FFVâÂ÷"¢òò6öÆÆ6VB6öçF–æW"âBç¦W&òv–GF‚F†RFW‡Bw&2–çFò‡VæG&V@¢òòÆ–æW2æBvRv÷VÆB&¶R3‚†V–v‡B–çFòF†R7G–ÆRGG&–'WFRà¢–b‚VÂæöfg6WE&VçBbbVÂæöfg6WD†V–v‡BÓÓÒ’&WGW&ã°¢–b†VÂæ6Æ–VçEv–GF‚ÂC’&WGW&ã°¢VÂç7G–ÆRæ†V–v‡BÒvWFòs°¢òò³"f÷"F†R&÷&FW"Â÷"F†RÆ7BÆ–æR6Æ—2æB—B67&öÆÇ2'’—†VÂà¢VÂç7G–ÆRæ†V–v‡BÒ†VÂç67&öÆÄ†V–v‡B²"’²w‚s°¢×Ð¢gVæ7F–öâ÷dw&÷tÆÂ††÷7B’·°¢††÷7BÇÂFö7VÖVçB’çVW'•6VÆV7F÷$ÆÂ‚rçbÖw&÷rr’æf÷$V6‚…÷dw&÷r“°¢×Ð¢gVæ7F–öâ÷e&VæFW$&÷WB‚’·°¢f"†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖ&÷WBr“²–b‚†÷7B’&WGW&ã°¢†÷7Bæ–ææW$…DÔÂÒ÷d&–ô‡FÖÂ‚’°¢÷dÆ—7D‡FÖÂ‚væ÷FW2rÂuF&vWF–æræ÷FW2rÂvWfVçG2–÷RvçBrÂtFBæ÷FRÅÇS#BâWfVçBÂ&Vv–öâÂ÷"G—R–÷RvçBr’°¢÷dÆ—7D‡FÖÂ‚wF÷–72rÂuFÆ·2bF÷–72rÂwv†B–÷R7V²öârÂtFBFÆ²F—FÆRÂF†VÖRÂ÷"6–væGW&RævÆRr“°¢÷dw&÷tÆÂ††÷7B“°¢f"bÒ†÷7BçVW'•6VÆV7F÷"‚u¶FF×bÖfö7W5Òr“°¢–b†b’·²bæfö7W2‚“²G'’·²bç6VÆV7F–öå7F'BÒbç6VÆV7F–öäVæBÒbçfÇVRæÆVæwFƒ²×Ò6F6‚†R’··×Ò×Ð¢×Ð¢gVæ7F–öâ÷d6öÖÖ—DVF—B†¶W’Â’ÂfÂ’·°¢f"Æ–æW2Ò÷dÆ–æW2†¶W’“²fÂÒ‡fÂÇÂrr’çG&–Ò‚“°¢–b‡fÂ’Æ–æW5¶•ÒÒfÃ²VÇ6RÆ–æW2ç7Æ–6R†’Â“°¢÷d×•¶¶W•ÒÒÆ–æW2æ¦ö–â‚uÅÆâr“²÷dVF—BÒ·²f–VÆC¢çVÆÂÂ–æFWƒ¢Ó×Ó²÷eW'6—7B‚“²÷e&VæFW$&÷WB‚“°¢×Ð¢gVæ7F–öâ÷d6öÖÖ—DFB†¶W’ÂfÂ’·°¢fÂÒ‡fÂÇÂrr’çG&–Ò‚“²–b‚fÂ’&WGW&ã°¢f"Æ–æW2Ò÷dÆ–æW2†¶W’“²Æ–æW2çW6‚‡fÂ“²÷d×•¶¶W•ÒÒÆ–æW2æ¦ö–â‚uÅÆâr“²÷eW'6—7B‚“²÷e&VæFW$&÷WB‚“°¢f"’ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖFBÒr²¶W’“²–b†’’’æfö7W2‚“²òò&VG’FòFBæ÷F†W ¢×Ð¢gVæ7F–öâ÷ev—&T&÷WB††÷7B’·°¢–b‚†÷7BÇÂ†÷7BæFF6WBçev—&VB’&WGW&ã²†÷7BæFF6WBçev—&VBÒss°¢†÷7BæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢f""ÒRçF&vWBæ6Æ÷6W7BòRçF&vWBæ6Æ÷6W7B‚u¶FF×eÒr’¢çVÆÃ²–b‚"’&WGW&ã°¢f"7BÒ"ævWDGG&–'WFR‚vFF×br’Â¶W’Ò"ævWDGG&–'WFR‚vFFÖ¶W’r’Â’Ò'6T–çB†"ævWDGG&–'WFR‚vFFÖ’r’Â“°¢–b†7BÓÓÒv&–òÖVF—Br’·²÷dVF—BÒ·²f–VÆC¢v&–òrÂ–æFWƒ¢Ó×Ó²÷e&VæFW$&÷WB‚“²×Ð¢VÇ6R–b†7BÓÓÒv&–òÖ6æ6VÂrÇÂ7BÓÓÒvÆ—7BÖ6æ6VÂr’·²÷dVF—BÒ·²f–VÆC¢çVÆÂÂ–æFWƒ¢Ó×Ó²÷e&VæFW$&÷WB‚“²×Ð¢VÇ6R–b†7BÓÓÒv&–ò×6fRr’·²f"VÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖ&–òÖ–çWBr“²÷d×’æ&–òÒVÂòVÂçfÇVRçG&–Ò‚’¢rs²÷dVF—BÒ·²f–VÆC¢çVÆÂÂ–æFWƒ¢Ó×Ó²÷eW'6—7B‚“²÷e&VæFW$&÷WB‚“²×Ð¢VÇ6R–b†7BÓÓÒvÆ—7BÖVF—Br’·²÷dVF—BÒ·²f–VÆC¢¶W’Â–æFWƒ¢’×Ó²÷e&VæFW$&÷WB‚“²×Ð¢VÇ6R–b†7BÓÓÒvÆ—7B×6fRr’·²f"–çÒ†÷7BçVW'•6VÆV7F÷"‚rçbÖ—FVÒÒÖVF—BçbÖ–çWE¶FFÖ¶W“Ò"r²¶W’²r%Õ¶FFÖ“Ò"r²’²r%Òr“²÷d6öÖÖ—DVF—B†¶W’Â’Â–çò–ççfÇVR¢rr“²×Ð¢VÇ6R–b†7BÓÓÒvÆ—7BÖFVÂr’·²f"Ç2Ò÷dÆ–æW2†¶W’“²Ç2ç7Æ–6R†’Â“²÷d×•¶¶W•ÒÒÇ2æ¦ö–â‚uÅÆâr“²÷eW'6—7B‚“²÷e&VæFW$&÷WB‚“²×Ð¢VÇ6R–b†7BÓÓÒvÆ—7BÖFBr’·²f"’ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖFBÒr²¶W’“²÷d6öÖÖ—DFB†¶W’Â’ò’çfÇVR¢rr“²×Ð¢×Ò“°¢†÷7BæFDWfVçDÆ—7FVæW"‚v–çWBrÂgVæ7F–öâ†R’·°¢–b†RçF&vWBbbRçF&vWBæ6Æ74Æ—7BbbRçF&vWBæ6Æ74Æ—7Bæ6öçF–ç2‚wbÖw&÷rr’’÷dw&÷r†RçF&vWB“°¢×Ò“°¢†÷7BæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·°¢òòVçFW"7F–ÆÂ6öÖÖ—G2(	BF†W6R&VB2öæRÖÆ–æRf–VÆG2WfVâF†÷Vv‚F†W¢òò&RFW‡F&V2æ÷râ6†–gB´VçFW"—2F†RFVÆ–&W&FRÆ–æR'&V²à¢–b†Ræ¶W’ÓÒtVçFW"rÇÂRç6†–gD¶W’’&WGW&ã°¢f"BÒRçF&vWC²–b‚BÇÂBæ†4GG&–'WFR’&WGW&ã°¢–b‡Bæ†4GG&–'WFR‚vFFÖFF¶W’r’’·²Rç&WfVçDFVfVÇB‚“²÷d6öÖÖ—DFB‡BævWDGG&–'WFR‚vFFÖFF¶W’r’ÂBçfÇVR“²&WGW&ã²×Ð¢–b‡Bæ6Æ74Æ—7BbbBæ6Æ74Æ—7Bæ6öçF–ç2‚wbÖ–çWBr’bbBæ†4GG&–'WFR‚vFFÖ’r’’·²Rç&WfVçDFVfVÇB‚“²÷d6öÖÖ—DVF—B‡BævWDGG&–'WFR‚vFFÖ¶W’r’Â'6T–çB‡BævWDGG&–'WFR‚vFFÖ’r’Â’ÂBçfÇVR“²&WGW&ã²×Ð¢×Ò“°¢×Ð¢òòöæRVF—F&ÆRÖFW&–Â6Æ÷Bf÷"W'6öâ‡F†V—"÷vâ6&BÂ÷"ç’W'6öâ–à¢òòævVÆw2FVÒF—&V7F÷'’’âVÆVÖVçB–G2&R¶W–VB'’ÇW'6öãâÓÇ6Æ÷Câ6ð¢òò6WfW&ÂV÷ÆRw26Æ÷G26â6öW†—7Bâ–æ6ÇVFW2â÷F–öæÂÆ–æ²D•DÄRà¢gVæ7F–öâöÖFW&–Å6Æ÷D‡FÖÂ†¶W’ÂÒÂ—57W÷'B’·°¢f"6–BÒ¶W’²rÒr²Òæ³°¢&WGW&âsÆF—b6Æ73Ò'&öf–ÆRÖÖFW&–Â#ãÆF—b6Æ73Ò'&öf–ÆRÖÖFW&–ÂÖ†VB#âr°¢sÇ7â6Æ73Ò'&öf–ÆRÖÖFW&–ÂÖÆ&VÂ#âr²W66T‡FÖÂ†ÒæÆ&VÂ’²sÂ÷7ãâr°¢sÇ7â6Æ73Ò&†–çB#âr²W66T‡FÖÂ…öÖD†–çB†ÒÂ—57W÷'B’’²sÂ÷7ããÂöF—câr°¢sÆF—b6Æ73Ò'&öf–ÆRÖf–ÆW2"–CÒ'bÖf–ÆW2Òr²6–B²r#ãÇ6Æ73Ò'&öf–ÆRÖf–ÆRÖV×G’#äÆöF–ærf†VÆÆ—³Â÷ãÂöF—câr°¢sÆF—b6Æ73Ò'&öf–ÆR×WÆöB×&÷r#ãÆ–çWBG—SÒ&f–ÆR"–CÒ'bÖf–ÆRÖ–çWBÒr²6–B²r"&–ÖÆ&VÃÒ$6†ö÷6Rf–ÆRf÷"r²W66T‡FÖÂ†ÒæÆ&VÂ’²r#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ"FFÖÖB×WÆöCÒ"r²W66T‡FÖÂ†¶W’²wÂr²Òæ²’²r#åWÆöCÂö'WGFöããÂöF—câr°¢sÆF—b6Æ73Ò'&öf–ÆRÖÆ–æ²×&÷r#ãÆ–çWBG—SÒ'FW‡B"–CÒ'bÖÆ–æ²×F—FÆRÒr²6–B²r"6Æ73Ò'bÖÆ–æ²×F—FÆR"Æ6V†öÆFW#Ò$Fö2F—FÆR†÷F–öæÂ’"&–ÖÆ&VÃÒ%F—FÆRf÷"F†Rr²W66T‡FÖÂ†ÒæÆ&VÂ’²rÆ–æ²#âr°¢sÆ–çWBG—SÒ'W&Â"–CÒ'bÖÆ–æ²Ö–çWBÒr²6–B²r"Æ6V†öÆFW#Ò'7FRvöövÆRG&—fRòFö2Æ–æ²"&–ÖÆ&VÃÒ%7FRÆ–æ²f÷"r²W66T‡FÖÂ†ÒæÆ&VÂ’²r#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ"FFÖÖBÖÆ–æ³Ò"r²W66T‡FÖÂ†¶W’²wÂr²Òæ²’²r#äFBÆ–æ³Âö'WGFöããÂöF—câr°¢sÂöF—câs°¢×Ð¢òòf–ÆW2f÷"öæRÖFW&–Â6Æ÷BƒÆÖT¶W“âóÆ6Câþ(
b’(	BF÷væÆöB²FVÆWFRà¢gVæ7F–öâöÆöE&öf–ÆTf–ÆW2†ÖT¶W’Â6BÂ6WGWVæF–ær’·°¢f"Ff–ÆW2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖf–ÆW2Òr²ÖT¶W’²rÒr²6B“°¢–b‚Ff–ÆW2’&WGW&ã°¢f"&Vf—‚ÒÖT¶W’²ròr²6C°¢òòföÆFW'2F†—26Æ÷B'6÷&&VBv†VâF†RÆ—7Bv27WBg&öÒf—fRFòF‡&VRà¢f"÷6Æ÷BÒ$ôd”ÄUôÔDU$”Å2æf–ÇFW"†gVæ7F–öâ†Ò’·²&WGW&âÒæ²ÓÓÒ6C²×Ò•³ÒÇÂ··×Ó°¢f"öÇ6òÒ…÷6Æ÷BæÇ6òÇÂµÒ’æÖ†gVæ7F–öâ†2’·²&WGW&âÖT¶W’²ròr²3²×Ò“°¢òòÖ—76–ær'V6¶WB&WGW&ç2âV×G’Æ—7B†æ÷BâW'&÷"’Â6òÆVâöâF†P¢òò6ÖR6WGW6–væÂ2F†RFW‡B7F÷&Rf÷"F†RV×G’×7FFRv÷&F–ærà¢òòâV×G’6Æ÷B6—2æ÷F†–ærBÆÂæ÷r(	BF†RWÆöB&÷rVæFW&æVF‚—0¢òòÇ&VG’F†R–çf—FF–öâÂæB$æ÷F†–ær†W&R–WB"F‡&VRF–ÖW2÷fW"v0¢òò§W7Bæö—6R„‡W&ÆW’##bÓrÓ3’â7F÷&vRÖæ÷B×6WB×W7F–ÆÂ7V·2Wà¢f"ö÷G2Ò·²Æ–Ö—C¢Â6÷'D'“¢·²6öÇVÖã¢v7&VFVEöBrÂ÷&FW#¢vFW62r×Ò×Ó°¢f"öÆ—7G2Ò·&Vf—…Òæ6öæ6B…öÇ6ò’æÖ†gVæ7F–öâ‡g‚’·°¢&WGW&â6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æÆ—7B‡g‚Âö÷G2’çF†Vâ†gVæ7F–öâ‡"’·°¢&WGW&â·²gƒ¢g‚Â&W7¢"×Ó°¢×ÒÂgVæ7F–öâ‚’·²&WGW&â·²gƒ¢g‚Â&W7¢çVÆÂ×Ó²×Ò“°¢×Ò“°¢&öÖ—6RæÆÂ…öÆ—7G2’çF†Vâ†gVæ7F–öâ†ÆÂ’·°¢f"†VBÒÆÅ³ÒbbÆÅ³Òç&W7°¢–b††VBbb†VBæW'&÷"’·°¢Ff–ÆW2æ–ææW$…DÔÂÒsÇ6Æ73Ò'&öf–ÆRÖf–ÆRÖV×G’#äf–ÆR7F÷&vR—6âb33“·B6WBW–WBfÖF6ƒ²F†RöæR×F–ÖRÆ6öFSç&öf–ÆW3Âö6öFSâ'V6¶WB6WGW—27F–ÆÂVæF–ærãÂ÷âs°¢&WGW&ã°¢×Ð¢f"—FV×2ÒµÓ°¢ÆÂæf÷$V6‚†gVæ7F–öâ†ò’·°¢‚†òç&W7bbòç&W7æFF’ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†b’·°¢–b†bææÖRbbbææÖRÓÒræV×G”föÆFW%Æ6V†öÆFW"r’—FV×2çW6‚‡·²gƒ¢òçg‚Âc¢b×Ò“°¢×Ò“°¢×Ò“°¢–b‚—FV×2æÆVæwF‚’·°¢Ff–ÆW2æ–ææW$…DÔÂÒ6WGWVæF–æp¢òsÇ6Æ73Ò'&öf–ÆRÖf–ÆRÖV×G’#å7F÷&vRæ÷B6WBW–WBãÂ÷âr¢rs°¢&WGW&ã°¢×Ð¢Ff–ÆW2æ–ææW$…DÔÂÒ—FV×2æÖ†gVæ7F–öâ†—B’·°¢f"bÒ—Bæc°¢f"6—¦RÒ†bæÖWFFFbbbæÖWFFFç6—¦R’òöf×D'—FW2†bæÖWFFFç6—¦R’¢rs°¢&WGW&âöÖDf–ÆU&÷t‡FÖÂ†—Bçg‚²ròr²bææÖRÂbææÖRÂ6—¦RÂG'VR“°¢×Ò’æ¦ö–â‚rr“°¢÷v—&U&öf–ÆTf–ÆT6öçF–æW"‚Ff–ÆW2ÂgVæ7F–öâ†gVÆÅF‚ÂæÖR’·°¢–b‚v–æF÷ræ6öæf—&Ò‚tFVÆWFR"r²æÖR²r#òF†—26ææ÷B&RVæFöæRâr’’&WGW&ã°¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’ç&VÖ÷fR…¶gVÆÅF…Ò’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‡"bb"æW'&÷"’·²7FGW2‚tFVÆWFRf–ÆVC¢r²"æW'&÷"æÖW76vRÂvW'&÷"r“²&WGW&ã²×Ð¢fÆ6„ö²‚tFVÆWFVBr“²öÆöE&öf–ÆTf–ÆW2†ÖT¶W’Â6BÂfÇ6R“°¢×Ò“°¢×ÒÂgVæ7F–öâ†gVÆÅF‚ÂW&ÂÂ7W%F—FÆR’·°¢òò&VæÖRÆ–æ¶VBFö2w2F—FÆS¢&RÖVæ6öFR··BÇW×ÒæBÔõdRF†RÖ&¶W"f–ÆP¢òòFòF†RæWræÖR†—G2æÖR—2F†R6÷W&6RöbG'WFƒ²6öçFVçB—2VçW6VB’à¢f"&rÒv–æF÷rç&ö×B‚u&VæÖRF†—2Æ–æ³¢rÂ7W%F—FÆRÇÂrr“°¢–b‡&rÓÓÒçVÆÂ’&WGW&ã²òò6æ6VÆÆV@¢f"çBÒ&rçG&–Ò‚’ç6Æ–6RƒÂ#“°¢f"–ÆöBÒçBò¥4ôâç7G&–æv–g’‡·²C¢çBÂS¢W&Â×Ò’¢W&Ã°¢f"Væ2Òö#cGW&ÄVæ2‡–ÆöB“°¢–b‚Væ2ÇÂVæ2æÆVæwF‚âs’·²7FGW2‚t6÷VÆBæ÷B&VæÖR‡FöòÆöær’ârÂvW'&÷"r“²&WGW&ã²×Ð¢f"æWuF‚ÒgVÆÅF‚ç&WÆ6R‚õÅÂõµåÅÂõÒ¢BòÂròr²Væ2²rçvV&Æ–æ²r“°¢–b†æWuF‚ÓÓÒgVÆÅF‚’&WGW&ã²òòæò6†ævP¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’æÖ÷fR†gVÆÅF‚ÂæWuF‚’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‡"bb"æW'&÷"’·²7FGW2‚u&VæÖRf–ÆVC¢r²"æW'&÷"æÖW76vRÂvW'&÷"r“²&WGW&ã²×Ð¢fÆ6„ö²‚u&VæÖVBr“²öÆöE&öf–ÆTf–ÆW2†ÖT¶W’Â6BÂfÇ6R“°¢×Ò“°¢×Ò“°¢×Ò“°¢×Ð¢òò6fRvöövÆRG&—fRòFö2†÷"ç’’Æ–æ²–çFòÖFW&–Â6Æ÷BÂ7F÷&VB2¢òò"çvV&Æ–æ²"Ö&¶W"f–ÆS¢&6ScGW&Âöb··C§F—FÆRÂS§W&Ç×Ò†÷"§W7BF†RU$À¢òòv†VâæòF—FÆR—2v—fVâ’âF—FÆR6†÷w22F†RÆ–æ²w2Æ&VÂà¢gVæ7F–öâöFE&öf–ÆTÆ–æ²†ÖT¶W’Â6B’·°¢f"6–BÒÖT¶W’²rÒr²6C°¢f"F–âÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖÆ–æ²Ö–çWBÒr²6–B“°¢f"GF—FÆRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖÆ–æ²×F—FÆRÒr²6–B“°¢f"W&ÂÒ‚‚F–âbbF–âçfÇVR’ÇÂrr’çG&–Ò‚“°¢f"F—FÆRÒ‚‚GF—FÆRbbGF—FÆRçfÇVR’ÇÂrr’çG&–Ò‚’ç6Æ–6RƒÂ#“°¢–b‚õæ‡GG3ó¥ÅÂõÅÂòö’çFW7B‡W&Â’’·²7FGW2‚u7FRgVÆÂÆ–æ²7F'F–ærv—F‚‡GG¢òò÷"‡GG3¢òòrÂwv&âr“²&WGW&ã²×Ð¢–b‡W&ÂæÆVæwF‚âc’·²7FGW2‚uF†BÆ–æ²—2FöòÆöærFò6fRârÂvW'&÷"r“²&WGW&ã²×Ð¢f"–ÆöBÒF—FÆRò¥4ôâç7G&–æv–g’‡·²C¢F—FÆRÂS¢W&Â×Ò’¢W&Ã°¢f"Væ2Òö#cGW&ÄVæ2‡–ÆöB“°¢–b‚Væ2ÇÂVæ2æÆVæwF‚âs’·²7FGW2‚t6÷VÆBæ÷B6fRF†BÆ–æ²‡FöòÆöær’ârÂvW'&÷"r“²&WGW&ã²×Ð¢f"F'FâÒFö7VÖVçBçVW'•6VÆV7F÷"‚u¶FFÖÖBÖÆ–æ³Ò"r²ÖT¶W’²wÂr²6B²r%Òr“°¢–b‚F'Fâ’·²F'Fâç6WDGG&–'WFR‚v&–Ö'W7’rÂwG'VRr“²F'FâçFW‡D6öçFVçBÒtFF–æuÅÇS##bs²×Ð¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’çWÆöB†ÖT¶W’²ròr²6B²ròr²Væ2²rçvV&Æ–æ²rÀ¢æWr&Æö"…·–ÆöEÒÂ·²G—S¢wFW‡B÷Æ–âr×Ò’Â·²W6W'C¢G'VRÂ6öçFVçEG—S¢wFW‡B÷Æ–âr×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‚F'Fâ’·²F'Fâç&VÖ÷fTGG&–'WFR‚v&–Ö'W7’r“²F'FâçFW‡D6öçFVçBÒtFBÆ–æ²s²×Ð¢–b‡&W7bb&W7æW'&÷"’·°¢7FGW2‚t6÷VÆBæ÷BFBF†RÆ–æ³¢r²&W7æW'&÷"æÖW76vR²‚ö'V6¶WGÆæ÷Bf÷VæBö’çFW7B‡&W7æW'&÷"æÖW76vR’òrÅÇS#BF†R&öf–ÆW27F÷&vR'V6¶WBÖ’æ÷B&R6WBW–WBâr¢rr’ÂvW'&÷"r“°¢&WGW&ã°¢×Ð¢–b‚F–â’F–âçfÇVRÒrs²–b‚GF—FÆR’GF—FÆRçfÇVRÒrs°¢fÆ6„ö²‚tÆ–æ²FFVBr“²öÆöE&öf–ÆTf–ÆW2†ÖT¶W’Â6BÂfÇ6R“°¢×Ò“°¢×Ð¢gVæ7F–öâ÷WÆöE&öf–ÆTf–ÆR†ÖT¶W’Â6B’·°¢f"F–âÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wbÖf–ÆRÖ–çWBÒr²ÖT¶W’²rÒr²6B“°¢–b‚F–âÇÂF–âæf–ÆW2ÇÂF–âæf–ÆW2æÆVæwF‚’·²7FGW2‚u–6²f–ÆRf—'7BârÂwv&âr“²&WGW&ã²×Ð¢f"f–ÆRÒF–âæf–ÆW5³Ó°¢–b†f–ÆRç6—¦Râ#R¢#B¢#B’·²7FGW2‚uF†Bf–ÆR—2÷fW"#RÔ"ÅÇS#BÆV6RWÆöB6öÖWF†–ær6ÖÆÆW"ârÂvW'&÷"r“²&WGW&ã²×Ð¢f"GWÒFö7VÖVçBçVW'•6VÆV7F÷"‚u¶FFÖÖB×WÆöCÒ"r²ÖT¶W’²wÂr²6B²r%Òr“°¢–b‚GW’·²GWç6WDGG&–'WFR‚v&–Ö'W7’rÂwG'VRr“²GWçFW‡D6öçFVçBÒuWÆöF–æuÅÇS##bs²×Ð¢6"ç7F÷&vRæg&öÒ‚w&öf–ÆW2r’çWÆöB†ÖT¶W’²ròr²6B²ròr²f–ÆRææÖRÂf–ÆRÂ·²W6W'C¢G'VR×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‚GW’·²GWç&VÖ÷fTGG&–'WFR‚v&–Ö'W7’r“²GWçFW‡D6öçFVçBÒuWÆöBs²×Ð¢–b‡&W7bb&W7æW'&÷"’·°¢7FGW2‚uWÆöBf–ÆVC¢r²&W7æW'&÷"æÖW76vR²‚ö'V6¶WGÆæ÷Bf÷VæBö’çFW7B‡&W7æW'&÷"æÖW76vR’òrÅÇS#BF†R&öf–ÆW27F÷&vR'V6¶WBÖ’æ÷B&R6WBW–WBâr¢rr’ÂvW'&÷"r“°¢&WGW&ã°¢×Ð¢–b‚F–â’F–âçfÇVRÒrs°¢fÆ6„ö²‚tf–ÆRWÆöFVBr“°¢öÆöE&öf–ÆTf–ÆW2†ÖT¶W’Â6BÂfÇ6R“°¢×Ò“°¢×Ð ¢òò)H)HÆææW#¢66†VGVÆ–ær6öæfÆ–7G2²6÷fW&vRv2'’FW'&—F÷'’)H)H ¢òò)H)HW"×FVÖÖFRF&vWB&öf–ÆW2)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò6–ævÆR6÷W&6RöbG'WF‚f÷"'v†–6‚WfVçG2&Rf÷"v†öÒ"(	BG&—fW2F†P¢òòÆææW"w26÷fW&vRv2äBF†Rw&–B$f—G2"f–ÇFW"†æB—2Ö—'&÷&VB–à¢òò&÷6Rf÷"F†R6²Ô’76—7FçB’ââWfVçBf—G2&öf–ÆR–b—G26æöæ–6À¢òò&Vv–öâ—2–â&Vv–öç6Âõ"ç’¶W—v÷&B†—G2F†RWfVçBw2föÆFVBFW‡B&Æö ¢òò†ÖF6†VB2v†öÆRv÷&G2’â¶VW¶W—v÷&G2Æ÷vW&66R²Væ7GVF–öâÖg&VRà¢òò)H)HFVÖÖFRF&vWF–ær&öf–ÆW2)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò$U5Dõ$TB##bÓ‚ÓRÂ†÷W'2gFW"&V–ær&VÖ÷fVBâF¶–ærF†VÒ÷WBÖFRF†P¢òòW'6öâf–ÇFW"ç7vW"öæÇ’'v†B†2ÆæÖSâÇ&VG’F÷V6†VCò"ÂæB‡W&ÆW’w0¢òòö–çB—2F†BF†Rf–ÇFW"Ç6ò†2Fòd”äBF†–æw3¢&—B6†÷VÆB&R&6VBöà¢òòF†R×’Öf—B2vVÆÂ6òF†BvR6âf–æBÖ÷&RWfVçG2Âæ'&÷v–ærF÷vâF†P¢òò‡VvRÆ—7Bf÷"öæW2F†B&R&VÆWfçBFòF†B7V6–f–2W'6öâ"â&V6ÆÀ¢òòÆöæR6âwBFòF†B(	BâWfVçBæö&öG’†2Æöö¶VBB–WB†2æòVævvVÖVç@¢òòFòÖF6‚öâÂæBF†÷6R&RW†7FÇ’F†RöæW2v÷'F‚7W&f6–ærà¢òð¢òò6òF†RW'6öâf–ÇFW"—2æ÷rf—Bõ"VævvVÖVçB‡6VR÷W'6öå&VÆWfçB“ ¢òòF†R&öf–ÆR&÷÷6W2ÂF†RVævvVÖVçB&V6÷&B6öæf—&×2ÂæB&V¦V7F–öà¢òò&VÖ÷fW2â%õDU%$•Dõ$”U2F–BäõB6öÖR&6²(	BF†RÆææW"'Vç2öâF†RfÆ@¢òò%VçF÷V6†VBWfVçG2"Æ—7Bæ÷rÂv†–6‚FöW6âwBæVVBFW'&—F÷'’7Æ—Bà¢f"%õ$ôd”ÄU2Ò°¢·²¶W“¢t¦W&öÖRrÂÆ&VÃ¢tWW&÷R†VçFW'&—6R’rÂ&Vv–öç3¢²tWW&÷RuÒÂÆö6¶VC¢G'VRÀ¢·s¢²vÆöæFöârÂvGV&Æ–ârÂv×7FW&FÒrÂv''W76VÇ2rÂw§W&–6‚rÂvvVæWfrÂvÇW†VÖ&÷W&rrÂv&W&Æ–ârÂv×Væ–6‚rÂvg&æ¶gW'BrÂwf–VæærÂw7Fö6¶†öÆÒrÂv6÷Væ†vVârÂv÷6ÆòrÂv†VÇ6–æ¶’rÂvÖG&–BrÂv&&6VÆöærÂvÖ–ÆârÂvÆ—6&öârÂvWW&÷RrÂvVÖVrÂvWW&÷VârÂvf–ææ6–Â6W'f–6W2rÂv–ç7W&æ6RrÂvf–çFV6‚rÂv†VÇF†6&RrÂwFVÆ6òrÂw&WF–ÂrÂvV6öÖÖW&6RrÂvÖVF–rÂvvG"uÒ×ÒÀ¢·²¶W“¢t¦öRrÂÆ&VÃ¢t…"bV÷ÆR…U2’rÂ&Vv–öç3¢µÒÀ¢·s¢²v‡"rÂv‡VÖâ&W6÷W&6W2rÂv6‡&òrÂv6ÆòrÂv6†–VbV÷ÆRrÂwV÷ÆRöff–6W"rÂwgöb‡"rÂwFÆVçBrÂwv÷&¶f÷&6RrÂvgWGW&Röbv÷&²rÂwW6¶–ÆÆ–ærrÂw&W6¶–ÆÆ–ærrÂvÆV&æ–ærrÂvÂfBrÂwV÷ÆRæÇ—F–72rÂv6†ævRÖævVÖVçBrÂv‡VÖâVæ&ÆVÖVçBrÂv‡VÖâ6—FÂrÂv÷&væ—¦F–öæÂFWfVÆ÷ÖVçBrÂvV×Æ÷–VRW‡W&–Væ6RuÒ×ÒÀ¢·²¶W“¢uF†÷"rÂÆ&VÃ¢t†VÇF†6&R†W†V2’rÂ&Vv–öç3¢µÒÀ¢òòwF–VçB6&RrÂwFVÆV†VÇF‚ræBw&÷f–FW"rVÆÆVB–â6&RÖFVÆ—fW'¢òòWfVçG2F—&V7FÇ’(	BF†RW†7BF†–ærF†R'VÆRW†6ÇVFW2â'W–W"×6–FP¢òòFW&×2¶WB„‡W&ÆW’##bÓrÓ3’à¢·s¢²v†VÇF†6&RrÂv†VÇF‡FV6‚rÂv†VÇF‚FV6‚rÂvF–v—FÂ†VÇF‚rÂvÖVGFV6‚rÂvÖVBFV6‚rÂvÆ–fR66–Væ6W2rÂw†&ÖrÂw†&Ö6WWF–6ÂrÂv&–÷FV6‚rÂv†VÇF‚7—7FVÒrÂv†VÇF†6&R’rÂw–W"rÂv†VÇF‚ÆârÂv†÷7—FÂW†V7WF—fRrÂv6†–VbÖVF–6Âöff–6W"uÒ×ÒÀ¢·²¶W“¢ufW&ÖrÂÆ&VÃ¢t–ç7W&æ6Rb&VwVÆFVB†&ö&BÖÆWfVÂ’rÂ&Vv–öç3¢µÒÀ¢·s¢²v–ç7W&æ6RrÂv–ç7W'FV6‚rÂvÆ–fR–ç7W&æ6RrÂw&V–ç7W&æ6RrÂvf–ææ6RrÂvf–ææ6–Â6W'f–6W2rÂv&æ²rÂv&æ¶–ærrÂv6—FÂÖ&¶WG2rÂw–ÖVçG2rÂvf–çFV6‚rÂv&ö&BrÂv6†–VbFFrÂw&VwVÆFVBrÂv6ö×Æ–æ6RuÒ×ÒÀ¢òò6&Æ÷2'Vç2ÆDÒ(	BæòU26—F–W2„‡W&ÆW’##bÓrÓ#’’âuU2b6æFrW6V@¢òòFò6—B–â†—2&Vv–öç2ÂæB&V6W6R†Rw2&Vv–öâÔÄô4´TBF†B6–ævÆRFö¶Và¢òòv2Fö–ærÆÖ÷7BÆÂF†Rv÷&³¢3“2öb†—2C#rf—G2vW&RU2WfVçG0¢òò„Æ2fVv2ÂW7F–âÂæ6‡f–ÆÆ^(
b’Â7v×–ærF†R3BF†B&R7GVÆÇ’†—2à¢òòäõDS¢Æö6¶VF&WGW&ç2öâF†R&Vv–öâFW7BÂ6òF†R·rÆ—7B&VÆ÷ræWfW ¢òò'Vç2f÷"†–Ò(	B—Bw2¶WBöæÇ’2Fö7VÖVçFF–öâöb†—2FW'&—F÷'’à¢·²¶W“¢t6&Æ÷2rÂÆ&VÃ¢tÆF–âÖW&–6†Ö–BÖÖ&¶WB’rÂ&Vv–öç3¢²tÆF–âÖW&–6uÒÂÆö6¶VC¢G'VRÀ¢·s¢²vÖW†–6ò6—G’rÂvÖöçFW'&W’rÂw6çFòFöÖ–ævòrÂw6â§VârÂw6òVÆòrÂv&öv÷FrÂv'VVæ÷2—&W2rÂvÆ–ÖrÂw6çF–vòrÂwV—FòrÂvf–ææ6–Â6W'f–6W2rÂv–ç7W&æ6RrÂvf–çFV6‚rÂv†VÇF†6&RrÂw62rÂw&WF–ÂrÂwFVÆ6òrÂvÖVF–uÒ×ÒÀ¢òò¦–Ò—2DTd”äTB'’Æ6RæB6V7F÷"Â'WB6'&–W2æò&Vv–öâÆö6²†à¢òòV×G’&Vv–öç6ÖVç2F†R&Vv–öâFW7B6âæWfW"72f÷"†–Ò’âv—F†÷W@¢òòÖ–ä·r†RÖF6†VBöâç’6–ævÆRv÷&B&VÆ÷r(	B6VRF†Ræ÷FR–à¢òò&öf–ÆTf—G2â7G&öæt·vFW&×2&RVæÖ&–wV÷W2Væ÷Vv‚Fò7FæBÆöæS°¢òòWfW'—F†–ærVÇ6RæVVG2Gvòâwv6†–æwFöâr—2FVÆ–&W&FVÇ’äõB7G&öæs ¢òòöâ—G2÷vâ—Bw22Æ–¶VÇ’Fò&Rv6†–æwFöâ5DDR2D2à¢·²¶W“¢t¦–ÒrÂÆ&VÃ¢tv÷fW&æÖVçB„D2’rÂ&Vv–öç3¢µÒÂÖ–ä·s¢"À¢7G&öæt·s¢²wv6†–æwFöâF2rÂwV&Æ–26V7F÷"rÂvv÷gFV6‚rÂvfVG&×rÂvw6rÂvFöBrÂvæ—7BrÂvæF–öæÂ6V7W&—G’rÂvFVfVç6RuÒÀ¢·s¢²vv÷fW&æÖVçBrÂwV&Æ–26V7F÷"rÂvfVFW&ÂrÂvFVfVç6RrÂvæF–öæÂ6V7W&—G’rÂvv÷gFV6‚rÂv6—f–2rÂv×Væ–6—ÂrÂw7FFRæBÆö6ÂrÂwv6†–æwFöârÂwv6†–æwFöâF2rÂv6—FöÂrÂv6öæw&W72rÂwv†—FR†÷W6RrÂvvVæ7’rÂvw6rÂvFöBrÂvæ—7BrÂvfVG&×rÂwV&Æ–2öÆ–7’uÒ×ÒÀ¢òò‡W&ÆW’'Vç2F†RG&6¶W"æBFöW6âwB7V²(	B†—2&f—G2"&RF†RöæW2†Rv@¢òò7GVÆÇ’vÆ²–çFó¢e$TR’WfVçG2v—F†–â&V6‚öbF†Ræ÷'F†V7BâVæÆ–¶P¢òòF†R÷F†W'2F†—2—2âäBÂæ÷B¶W—v÷&Bõ#¢—B×W7B&Râ’WfVçBÂä@¢òò–âF†Ræ÷'F†V7BÂäBg&VRâ†Væ6RÆÄ·r†WfW'’w&÷W×W7B†—B’²g&VTöæÇ’à¢·²¶W“¢t‡W&ÆW’rÂÆ&VÃ¢tg&VR’WfVçG2„æ÷'F†V7B’rÂ&Vv–öç3¢µÒÂ·s¢µÒÂ7W÷'C¢G'VRÀ¢g&VTöæÇ“¢G'VRÀ¢ÆÄ·s¢°¢²v’rÂv’rÂv'F–f–6–Â–çFVÆÆ–vVæ6RrÂvÖ6†–æRÆV&æ–ærrÂvFVWÆV&æ–ærrÂvvVæ’rÂvvVâ’rÂvvVæW&F—fR’rÂvÆÆÒrÂvÆÆ×2rÂvvVçF–2rÂvFF66–Væ6RrÂvÖÆ÷2rÂvæÇuÒÀ¢²væWr–÷&²rÂvæWr–÷&²6—G’rÂvç–2rÂvÖæ†GFârÂv'&öö¶Ç–ârÂwVVVç2rÂv'&öç‚rÂvÆöær—6ÆæBrÂv&÷7FöârÂv6Ö'&–FvRrÂw6öÖW'f–ÆÆRrÂw†–ÆFVÇ†–rÂw†–ÆÇ’rÂw—GG6'W&v‚rÂvæWv&²rÂv¦W'6W’6—G’rÂw&–æ6WFöârÂv†ö&ö¶VârÂw7FÖf÷&BrÂv†'Ff÷&BrÂvæWr†fVârÂvw&VVçv–6‚rÂw&÷f–FVæ6RrÂw÷'FÆæBÖ–æRrÂv'W&Æ–æwFöârÂvÆ&ç’rÂv'VffÆòrÂw&ö6†W7FW"rÂw7—&7W6RrÂvæWrVævÆæBrÂvæ÷'F†V7BrÂwG&’7FFRrÂwG&’×7FFRrÂv6öææV7F–7WBrÂvÖ766‡W6WGG2rÂvæWr¦W'6W’rÂw&†öFR—6ÆæBrÂvæWr†×6†—&RrÂwfW&ÖöçBrÂvÖ–æRrÂwVæç7–Çfæ–rÂvæWr–÷&²7FFRuÐ¢Ò×Ð¢Ó°¢f"%õ$ôd”ÄUô%•ô´U’Ò··×Ó°¢%õ$ôd”ÄU2æf÷$V6‚†gVæ7F–öâ‡’·²%õ$ôd”ÄUô%•ô´U•·æ¶W•ÒÒ²×Ò“°¢òò&öf–ÆR¶W—2&R6—FÆ—¦VB‚%F†÷""“²F†R6–væVBÖ–âf—'7BæÖR—2föÆFV@¢òòÆ÷vW&66R‚'F†÷""’â66RÖ–ç6Vç6—F—fRÆöö·Wf÷"F†R$×’f—G2"6†—à¢f"%õ$ôd”ÄUô%•ôÄ4´U’Ò··×Ó°¢%õ$ôd”ÄU2æf÷$V6‚†gVæ7F–öâ‡’·²%õ$ôd”ÄUô%•ôÄ4´U•µ7G&–ær‡æ¶W’’çFôÆ÷vW$66R‚•ÒÒ²×Ò“°¢òòG'VR–bâWfVçB†6æöæ–6Â&Vv–öâ²föÆFVBFW‡B&Æö"’f—G2&öf–ÆRà¢gVæ7F–öâö6&E&–6TçVÒ†6&B’·°¢f"bÒ6&Bbb6&BæFF6WBò6&BæFF6WBç&–6R¢rs°¢–b‡bÓÓÒrrÇÂbÓÒçVÆÂ’&WGW&âçVÆÃ°¢f"âÒ'6TfÆöB‡b“°¢&WGW&â—4æâ†â’òçVÆÂ¢ã°¢×Ð¢òò&–6TçVÓ¢F†RWfVçBw2'6VBF–6¶WB&–6RƒÒg&VRÂçVÆÂÒVæ¶æ÷vâ’âöæÇ¢òò6öç7VÇFVB'’g&VTöæÇ’&öf–ÆS²WfW'’÷F†W"&öf–ÆR–væ÷&W2—Bà¢òò—4f÷&V–vã¢F†RWfVçBw2F—FÆR—2–âæöâÔVævÆ—6‚ÆæwVvRâF†÷"ÂfW&Öæ@¢òò¦öR&W6VçBæB6VÆÂ–âVævÆ—6‚Â6ò7æ—6‚õ÷'GVwVW6Rôg&Væ6‚ôvW&Öâð¢òò—FÆ–âÖÆæwVvRWfVçB—2æWfW"F†V—"f—B„‡W&ÆW’##bÓrÓ#’’(	B—B7F—0¢òòf–Æ&ÆRFò¦W&öÖRæB6&Æ÷2Âv†÷6RFW'&—F÷&–W2—B&VÆöæw2Fòà¢òò6Æ–æ–6Âò6&RÖFVÆ—fW'’WfVçG2&RäõBF†÷"w2ÂWfVâF†÷Vv‚†VÇF†6&R—0¢òò†—2–æGW7G'’âF†R'VÆRF†RFVÒ7GVÆÇ’föÆÆ÷w2—2†VÇF†6&R%U”U%2–W2À¢òò6Æ–æ–6Â×&7F–6R6öæfW&Væ6W2æò(	BF†W’FVÆWFR”ÖVBÂt”åB†VÇF‚ä…2À¢òò$Ô¢gWGW&R†VÇF‚æB¶–ærw2gVæBv†–ÆR¶VW–ær„ÅD‚Â„”Õ52æBF†P¢òòÖ–ÆÆVææ—VÒÆÆ–æ6R†VÇF†6&R76VÖ&Æ–W2„‡W&ÆW’##bÓrÓ3ÂæBæ÷p¢òò7FFVB–âW'6öæ2æ§6öâF†÷"æWfVçE÷'VÆW2’à¢òð¢òò6ÖRGvò×FW7B6†R2F†R…"vFS¢F†RäÔRô„õ5B6F6†W2F†Rö'f–÷W0¢òòöæW2ÂF†R$Äô"6F6†W2WfVçG2v†÷6RVF–Væ6R—26Æ–æ–6–ç2WfVâv†VâF†P¢òòF—FÆR6—2’âFVÆ–&W&FVÇ’FöW2äõBf—&Röâ'F–VçB"ÆöæR(	B'F–Vç@¢òò÷WF6öÖW2"—27FæF&BÆæwVvRB'W–W"WfVçBFöòà¢f"ô4Ä”åôäÔRÒõÅÆ&–ÖVEÅÆB¥ÅÆ'ÅÅÆ&&Ö¥ÅÆ'Æ¶–ærs÷2gVæGÆv–çB†VÇF‡ÅÅÆ&æ‡5ÅÆ'Æ6Æ–æ–6Â‡G&–Ç3÷Ç&W6V&6‡Ç&7F–6WÆW†6VÆÆVæ6R—ÅÅÆ&6ÖUÅÆ'Æw&æB&÷VæG7ÆçW'6–æwÇ‡—6–6–ç3÷Æ6Æ–æ–6–ç3÷Æöæ6öÆöwÇ&F–öÆöwÆ6&F–öÆöwÇ7W&v–6ÇÇ7W&vW'—ÅÅÆ&ÖVF–6Â†76ö6–F–öçÇ6ö6–WG—Æ6öæw&W72•ÅÆ"ö“°¢f"ô4Ä”åô„õ5BÒõÅÆ"†’ÖÖVEÂæ–÷Æ–ÖVEÂæ6ö×Æ&Ö¥Âæ6ö×Æ¶–æw6gVæEÂæ÷&uÂçV·Æv–çEÂæ†VÇF‡Ææ‡5ÂçV·ÆÖW&–6æ†VÇF†ÆuÂæ÷&wÆæ7Âæ÷&r•ÅÆ"ö“°¢f"ô4Ä”åô$Äô"ÒõÅÆ"‡&7F—6–æwÇ&7F–6–ær’†6Æ–æ–6–ç3÷Ç‡—6–6–ç3ò•ÅÆ'Æf÷"†6Æ–æ–6–ç3÷Ç‡—6–6–ç3÷ÆçW'6W2•ÅÆ'Æ6Æ–æ–6Â‡G&–Ç3÷Ç&W6V&6‡Çv÷&¶fÆ÷w3÷Ç&7F–6R•ÅÆ'Æ&VG6–FWÇö–çBöb6&WÆ6&RFVÆ—fW'’ó°¢gVæ7F–öâö—46Æ–æ–6ÄWfVçB†æÖRÂW&ÂÂ&Æö"’·°¢&WGW&âô4Ä”åôäÔRçFW7B…7G&–ær†æÖRÇÂrr’’ÇÀ¢ô4Ä”åô„õ5BçFW7B…7G&–ær‡W&ÂÇÂrr’’ÇÀ¢ô4Ä”åô$Äô"çFW7B…7G&–ær†&Æö"ÇÂrr’“°¢×Ð¢v–æF÷ræ$—46Æ–æ–6ÄWfVçBÒö—46Æ–æ–6ÄWfVçC°¢f"ô…%ô$Äô"ÒõÅÆ&6‡&õÅÆ'Ç6‡&×Æ6†–Vb†‡VÖâ&W6÷W&6W7ÇV÷ÆR—ÇV÷ÆRöff–6W'ÅÅÆ&‡"‡7VÖÖ—GÆ6öæfW&Væ6WÆf÷'V×Æ76VÖ&Ç—ÆW†6†ævWÆ6öæw&W77ÆÆVFW'2•ÅÆ"ó°¢òòF—FÆRv÷&G2F†BÖ¶R…"ôÂdBF†R5T$¤T5BöbF†RWfVçBÂæ÷BF÷–2–â—Bà¢f"ô…%ôäÔRÒõÅÆ"†‡'Æ6‡&÷Ç6‡&×Ç6‡&Æ‡&6—Æ6Æ÷Æ7W•ÅÆ'Æ‡VÖâ&W6÷W&6W3÷Æ6†–Vb†‡VÖâ&W6÷W&6W7ÇV÷ÆWÆÆV&æ–ær’öff–6W'ÇV÷ÆR†öff–6W'ÆæÇ—F–72—ÇFÆVçB†ÖævVÖVçGÆ7V—6—F–öçÇ7G&FVw—Æf÷'VÒ—Çv÷&¶f÷&6R‡7VÖÖ—GÆf÷'V×Æ6öæfW&Væ6WÆ–ç7F—GWFR—ÆÆV&æ–ær†gWGW&W7ÇFV6†æöÆöv–W2—ÅÅÆ&ÂfEÅÆ'ÆV×Æ÷–VRW‡W&–Væ6WÇF÷FÂ&Wv&G7Æ6ö×Vç6F–öâ†æGÂb’&VæVf—G2ö“°¢òò÷&væ—6W'2v†÷6Rv†öÆR'W6–æW72—2…"òÂdBòV÷ÆRWfVçG2à¢f"ô…%ô„õ5BÒõÅÆ"‡6‡&ÕÂæ÷&wÆVæUÂæ÷&wÇ6‡&Âæ÷&wÆ‡&6•Âæ÷&wÆ7W‡%Âæ÷&wÆ—fVçF—eÂæ6ö×Æ¦÷6†&W'6–åÂæ6ö×ÇVæÆV6…Âæ—ÇFEÂæ÷&wÆ6÷'÷&FVÆV&æ–ævæWGv÷&µÂæ6ö×Æ‡&W†6†ævVæWGv÷&µÂæ6ö×Æ‡'FV6†æöÆöw–6öæfW&Væ6UÂæ6öÒ•ÅÆ"ö“°¢gVæ7F–öâö—4‡$WfVçB†æÖRÂW&Â’·°¢&WGW&âô…%ôäÔRçFW7B…7G&–ær†æÖRÇÂrr’’ÇÂô…%ô„õ5BçFW7B…7G&–ær‡W&ÂÇÂrr’“°¢×Ð¢v–æF÷ræ$—4‡$WfVçBÒö—4‡$WfVçC°¢gVæ7F–öâ&öf–ÆTf—G2‡Â&Æö"Â&Vv–öâÂ&–6TçVÒÂ—4f÷&V–vâÂWdæÖRÂWeW&Â’·°¢–b‚’&WGW&âfÇ6S°¢–b†—4f÷&V–vâbbôTätÄ•4…ôôäÅ•õTõÄUµ7G&–ær‡æ¶W’ÇÂrr’çFôÆ÷vW$66R‚•Ò’&WGW&âfÇ6S°¢òò„W7G&Æ–W6VBFò&R6'fVB÷WB2fW&Öw2W†6ÇW6—fRFW'&—F÷'’â—Bv0¢òòF¶Vâöfb†—2&öf–ÆRÂ6òF†—2vFRvVçBv—F‚—B(	B¶WBöâ—G2÷vâ—@¢òòv÷VÆB†fRÆVgBWfW'’RWfVçBf—GF–æräô$ôE’âW7G&Æ–âWfVçG2æ÷p¢òòÖF6‚öâF†V—"÷vâÖW&—G2ÂÆ–¶Rç—v†W&RVÇ6S¢âR–ç7W&æ6RWfVç@¢òò7F–ÆÂ&V6†W2fW&Öf–v–ç7W&æ6RrÂâR†VÇF†6&RöæR&V6†W2F†÷"â¢òò…"ò4…$òòV÷ÆRWfVçG2&R¤ôRu2VF–Væ6RöæÇ’(	B¶VWF†VÒöfbWfW'–öæP¢òòVÇ6Rw2f—B†4…$ò7VÖÖ—Bv†÷6RGFVæFVW27â–æGW7G&–W2v2ÖF6†–æp¢òòF†÷"öâ7G&’&†VÇF†6&R"’âÖF6†VBöâF†R7G&öær…"WfVçB6–væÇ2à¢òòGvòv—2âWfVçB—2â…"WfVçBÂæB—BæVVG2&÷F‚âF†R&Æö"FW7@¢òò6F6†W2F†RöæW2v†÷6R$ÅU$"v—fW2F†VÒv’„7VÇGW&T6öâÂg&öÒF’öæRÀ¢òòV÷ÆRÆVFW'27VÖÖ—B(	Bæ÷F†–ær–âF†RF—FÆR6—2…"’âF†RæÖRö†÷7@¢òòFW7B6F6†W2F†RöæW2v†÷6R&ÇW&"FÆ·2&÷WB’v†–ÆRF†RWfVçB—G6VÆ`¢òò—27V&VÇ’…"÷"ÂdC¢$TäR…"6öææV7B"Â$4ÄòW†6†ævR"Â&•fVçF—`¢òòÆV&æ–ærgWGW&W2"Â%4…$æçVÂ6öæfW&Væ6R"âs"öbF†÷6RvW&R&V6†–æp¢òòF†÷"„‡W&ÆW’##bÓrÓ3’âFVÆ–&W&FVÇ’öâF†RäÔRæBF†R÷&væ—6W"w0¢òòFöÖ–âÂæWfW"F†R&ÇW&"(	Bâ’7VÖÖ—BF†BÖW&VÇ’ÖVçF–öç2v÷&¶f÷&6P¢òò—27F–ÆÂ†—2à¢–b‡æ¶W’ÓÒt¦öRrbb…ô…%ô$Äô"çFW7B…7G&–ær†&Æö"ÇÂrr’’ÇÀ¢ö—4‡$WfVçB†WdæÖRÂWeW&Â’’’&WGW&âfÇ6S°¢òò†VÇF†6&R%U”U%2–W2Â6Æ–æ–6Â×&7F–6R6öæfW&Væ6W2æòâF†÷"w2¶W—v÷&@¢òòÆ—7B6'&–W2F†R†VÇF†6&RFW&×2F†Bf–æBF†R&–v‡BWfVçG3²F†—2¶VW0¢òòF†R6Æ–æ–6–âöæW2÷WBöbF†R6ÖRæWBà¢–b…ö—46Æ–æ–6ÄWfVçB†WdæÖRÂWeW&ÂÂ&Æö"’’&WGW&âfÇ6S°¢òòäB×&öf–ÆR„‡W&ÆW’“¢WfW'’¶W—v÷&Bw&÷W×W7B†—BÂæBg&VTöæÇ¢òò&öf–ÆRFF—F–öæÆÇ’&WV—&W2&–6RvR´äõr—2¦W&ò(	BâVæ¶æ÷vâ&–6P¢òò—2æ÷B&g&VR"Â6ò—B7F—2÷WB&F†W"F†â&WFVæF–ærà¢–b‡æÆÄ·rbbæÆÄ·ræÆVæwF‚’·°¢–b‡æg&VTöæÇ’bb&–6TçVÒÓÒ’&WGW&âfÇ6S°¢f"†"Òrr²7G&–ær†&Æö"ÇÂrr’ç&WÆ6R‚õµæ×£Ó•ÒörÂrr’ç&WÆ6R‚ò²örÂrr’çG&–Ò‚’²rs°¢f÷"‡f"v’Ò²v’ÂæÆÄ·ræÆVæwFƒ²v’²²’·°¢f"w'ÒæÆÄ·u¶v•ÒÂ†—BÒfÇ6S°¢f÷"‡f"v¢Ò²v¢Âw'æÆVæwFƒ²v¢²²’·°¢–b††"æ–æFW„öb‚rr²w'¶v¥Ò²rr’ÓÒÓ’·²†—BÒG'VS²'&V³²×Ð¢×Ð¢–b‚†—B’&WGW&âfÇ6S°¢×Ð¢&WGW&âG'VS°¢×Ð¢f"&Vv–öäö²Ò‡&Vv–öâbbç&Vv–öç2æ–æFW„öb‡&Vv–öâ’ÓÒÓ“°¢òò&Vv–öâÖÆö6¶VBV÷ÆR„¦W&öÖRÒWW&÷RÂ6&Æ÷2ÒÆF–âÖW&–6’f—BôäÅ¢òòF†V—"÷vâ&Vv–öâ(	BÆö÷6R¶W—v÷&B†6—G’æÖVB–â&ÇW&"Â÷"wvV ¢òò7VÖÖ—Br’×W7Bæ÷BVÆÂâ÷WBÖöb×&Vv–öâWfVçBFòF†VÒà¢–b‡æÆö6¶VB’&WGW&â&Vv–öäö³°¢–b‡&Vv–öäö²’&WGW&âG'VS°¢f""Òrr²7G&–ær†&Æö"ÇÂrr’ç&WÆ6R‚õµæ×£Ó’ÒörÂrr’ç&WÆ6R‚ò²örÂrr’çG&–Ò‚’²rs°¢òò7G&öæt·v(	BFW&×2F†BÖVâF†RWfVçB•2F†—2W'6öâw2öâF†V—"÷vâà¢òòÖ–ä·v(	B†÷rÖç’÷&F–æ'’¶W—v÷&G2—BF¶W2÷F†W'v—6R†FVfVÇB’à¢òò&÷F‚W†—7Bf÷"¦–Òâ†—2&VÖ—B—2D2²v÷fW&æÖVçB'WB†—2&Vv–öç6—0¢òòV×G’Â6ò†RæWfW"76VBF†R&Vv–öâFW7BæBfVÆÂ7G&–v‡BF‡&÷Vv‚Fð¢òòÆ–â¶W—v÷&Bõ"(	BæB6–ævÆR&v÷fW&æÖVçB"–âF†R&ÇW&"öbâ¢òò7VÖÖ—Bv2Væ÷Vv‚âC’öb†—2cRÖF6†W2vW&RöæR7G&’v÷&BÂVÆÆ–ær–à¢òò&—–F‚ÂW7G&Æ–Â6öÆöÖ&–æBVW'Fò&–6ò„‡W&ÆW’##bÓ‚ÓR’à¢òòF†—2—2F†R4ÔR&"†—2Æâ†VB7VvvW7F–öç2Ç&VG’Æ–V@¢òò‚&–âD2Â÷"6ÆV&Ç’v÷bÂ÷""²F†VÖW2"’(	BF†Rw&–Bf–ÇFW"§W7BæWfW ¢òòv÷B—BÂv†–6‚æö&öG’æ÷F–6VBv†–ÆR†R†Bæòf–ÇFW"6†—BÆÂà¢–b‡ç7G&öæt·r’·°¢f÷"‡f"2Ò²2Âç7G&öæt·ræÆVæwFƒ²2²²’·°¢–b†"æ–æFW„öb‚rr²ç7G&öæt·u·5Ò²rr’ÓÒÓ’&WGW&âG'VS°¢×Ð¢×Ð¢f"öæVVBÒæÖ–ä·rÇÂÂö†—G2Ò°¢f÷"‡f"’Ò²’Âæ·ræÆVæwFƒ²’²²’·°¢–b†"æ–æFW„öb‚rr²æ·u¶•Ò²rr’ÓÒÓbb²µö†—G2ãÒöæVVB’&WGW&âG'VS°¢×Ð¢&WGW&âfÇ6S°¢×Ð ¢gVæ7F–öâ÷4FFU&ævR†ò’·°¢f"2Ò†òç7F'EöFFRbbõåÅÆG·³G×ÒÕÅÆG·³'×ÒÕÅÆG·³'×ÒòçFW7B†òç7F'EöFFR’’òòç7F'EöFFRç6Æ–6RƒÂ’¢çVÆÃ°¢f"RÒ†òæVæEöFFRbbõåÅÆG·³G×ÒÕÅÆG·³'×ÒÕÅÆG·³'×ÒòçFW7B†òæVæEöFFR’’òòæVæEöFFRç6Æ–6RƒÂ’¢çVÆÃ°¢–b‚2bbòæFFU÷7G"’·²G'’·²f"BÒFW&—fTFFW4g&öÕFW‡B†òæFFU÷7G"“²2ÒBç7F'EöFFS²RÒBæVæEöFFS²×Ò6F6‚‡‚’··×Ò×Ð¢–b‚2’&WGW&âçVÆÃ°¢–b‚R’RÒ3°¢f"6ÒÒæWrFFR‡2²uC££r’ævWEF–ÖR‚“°¢f"VÒÒæWrFFR†R²uC#3£S“£S’r’ævWEF–ÖR‚“°¢–b†—4æâ‡6Ò’’&WGW&âçVÆÃ°¢–b†—4æâ†VÒ’ÇÂVÒÂ6Ò’VÒÒ6Ó°¢&WGW&â·6ÒÂVÕÓ°¢×Ð ¢gVæ7F–öâ7V¶W%Fö¶Vç2‡7’·°¢–b‚7’&WGW&âµÓ°¢&WGW&â$föÆB‡7’ç7Æ—B‚õ²Ã²òe×ÂæBÅÅÆ'ÇW5ÅÆ"ò’æÖ†gVæ7F–öâ‡2’·²&WGW&â2çG&–Ò‚“²×Ò’æf–ÇFW"„&ööÆVâ“°¢×Ð ¢gVæ7F–öâf–æD6öæfÆ–7G2‚’·°¢f"'•v†òÒ··×Ó°¢÷4ÆÄ—FV×2‚’æf÷$V6‚†gVæ7F–öâ†—B’·°¢–b†—Bç7BÇÂ—Bç7V¶W"ÇÂ—Bæ†–FFVâ’&WGW&ã°¢òòöæÇ’&VÂ6Æ6‚–bF†RW'6öâ—26öÖÖ—GFVB„&öö¶VB÷"GFVæF–ær¢òòFò&÷F‚WfVçG2(	Bæ÷BÖW&VÇ’6öç6–FW&–ærF†VÒà¢–b†—Bç7FvW2æ–æFW„öb‚t&öö¶VBr’ÓÓÒÓbb—Bç7FvW2æ–æFW„öb‚tGFVæF–ærr’ÓÓÒÓ’&WGW&ã°¢f"&ævRÒ÷4FFU&ævR†—Bç7F'Dö&¢“°¢–b‚&ævR’&WGW&ã°¢7V¶W%Fö¶Vç2†—Bç7V¶W"’æf÷$V6‚†gVæ7F–öâ‡Fö²’·°¢–b‡Fö²’†'•v†õ·FöµÒÒ'•v†õ·FöµÒÇÂµÒ’çW6‚‡·²—C¢—BÂ&ævS¢&ævR×Ò“°¢×Ò“°¢×Ò“°¢f"6öæfÆ–7G2ÒµÓ°¢ö&¦V7Bæ¶W—2†'•v†ò’æf÷$V6‚†gVæ7F–öâ‡Fö²’·°¢f"Æ—7BÒ'•v†õ·FöµÓ°¢–b†Æ—7BæÆVæwF‚Â"’&WGW&ã°¢f÷"‡f"’Ò²’ÂÆ—7BæÆVæwFƒ²’²²’·°¢f÷"‡f"¢Ò’²²¢ÂÆ—7BæÆVæwFƒ²¢²²’·°¢f"ÒÆ—7E¶•ÒÂ"ÒÆ—7E¶¥Ó°¢–b†ç&ævU³ÒÃÒ"ç&ævU³Òbb"ç&ævU³ÒÃÒç&ævU³Ò’·°¢òò6ÖR6—G’Ò6ÖRG&—Âæ÷BF÷V&ÆRÖ&öö¶–ær(	BöæÇ’fÆp¢òò÷fW&Æ–ærWfVçG2–âD”ddU$TåB6—F–W22&VÂ6öæfÆ–7G2à¢–b†æ—Bæ6—G’bb"æ—Bæ6—G’bbæ—Bæ6—G’ÓÓÒ"æ—Bæ6—G’’6öçF–çVS°¢6öæfÆ–7G2çW6‚‡·²v†ó¢Fö²Â¢æ—BÂ#¢"æ—B×Ò“°¢×Ð¢×Ð¢×Ð¢×Ò“°¢&WGW&â6öæfÆ–7G3°¢×Ð ¢òò)H)Hv&ÒÖ–çG&ò6öææV7F–öç2„Æ–æ¶VD–â55bWÆöB’)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢gVæ7F–öâö77dÆ–æR†Æ–æR’·°¢f"÷WBÒµÒÂ7W"ÒrrÂÒfÇ6S°¢f÷"‡f"’Ò²’ÂÆ–æRæÆVæwFƒ²’²²’·°¢f"2ÒÆ–æU¶•Ó°¢–b‡’·²–b†2ÓÓÒr"r’·²–b†Æ–æU¶’²ÒÓÓÒr"r’·²7W"³Òr"s²’²³²×ÒVÇ6RÒfÇ6S²×ÒVÇ6R7W"³Ò3²×Ð¢VÇ6R·²–b†2ÓÓÒr"r’ÒG'VS²VÇ6R–b†2ÓÓÒrÂr’·²÷WBçW6‚†7W"“²7W"Òrs²×ÒVÇ6R7W"³Ò3²×Ð¢×Ð¢÷WBçW6‚†7W"“²&WGW&â÷WC°¢×Ð¢gVæ7F–öâ'6T6öææV7F–öç477b‡FW‡BÂ÷væW"’·°¢f"Æ–æW2ÒFW‡Bç7Æ—B‚õÅÇ%ÅÆçÅÅÆçÅÅÇ"ò“°¢f"†’ÒÓ°¢f÷"‡f"’Ò²’ÂÆ–æW2æÆVæwFƒ²’²²’·²–b‚õâ#ôf—'7BæÖR#õÅÇ2¢Âö’çFW7B†Æ–æW5¶•Ò’’·²†’Ò“²'&V³²×Ò×Ð¢–b††’ÓÓÒÓ’&WGW&âµÓ°¢f"‚Òö77dÆ–æR†Æ–æW5¶†•Ò’æÖ†gVæ7F–öâ‡‚’·²&WGW&â‚çG&–Ò‚’çFôÆ÷vW$66R‚“²×Ò“°¢f"6’Ò·²f—'7C¢‚æ–æFW„öb‚vf—'7BæÖRr’ÂÆ7C¢‚æ–æFW„öb‚vÆ7BæÖRr’À¢6ö×ç“¢‚æ–æFW„öb‚v6ö×ç’r’Â÷6—F–öã¢‚æ–æFW„öb‚w÷6—F–öâr’ÂW&Ã¢‚æ–æFW„öb‚wW&Âr’×Ó°¢–b†6’æf—'7BÓÓÒÓÇÂ6’æÆ7BÓÓÒÓ’&WGW&âµÓ°¢f"&÷w2ÒµÓ°¢f÷"‡f"¢Ò†’²²¢ÂÆ–æW2æÆVæwFƒ²¢²²’·°¢–b‚Æ–æW5¶¥ÒçG&–Ò‚’’6öçF–çVS°¢f"bÒö77dÆ–æR†Æ–æW5¶¥Ò“°¢f"gVÆÂÒ‚†e¶6’æf—'7EÒÇÂrr’çG&–Ò‚’²rr²†e¶6’æÆ7EÒÇÂrr’çG&–Ò‚’’çG&–Ò‚“°¢–b‚gVÆÂ’6öçF–çVS°¢&÷w2çW6‚‡·²÷væW#¢÷væW"ÂgVÆÅöæÖS¢gVÆÂçFôÆ÷vW$66R‚’ÂF—7Æ•öæÖS¢gVÆÂÀ¢6ö×ç“¢6’æ6ö×ç’ãÒò†e¶6’æ6ö×ç•ÒÇÂrr’çG&–Ò‚’¢çVÆÂÀ¢÷6—F–öã¢6’ç÷6—F–öâãÒò†e¶6’ç÷6—F–öåÒÇÂrr’çG&–Ò‚’¢çVÆÂÀ¢&öf–ÆU÷W&Ã¢6’çW&ÂãÒò†e¶6’çW&ÅÒÇÂrr’çG&–Ò‚’¢çVÆÂ×Ò“°¢×Ð¢&WGW&â&÷w3°¢×Ð¢òòF†R6öææV7F–öç2F&ÆRæVVG2öæR×F–ÖRÖ–w&F–öââ÷7Fu$U5B&W÷'G2¢òòÖ—76–ærF&ÆR6WfW&Âv—2‚&FöW2æ÷BW†—7B"Â'66†VÖ66†R"Âu%5C#R’À¢òò6òÖF6‚F†VÒÆÂæB6†÷rôäR6ÆV"6WGWÖW76vR–ç7FVBöb&rW'&÷"à¢f"ô4ôäåõ4UEUôÕ4rÒuv&Ò–çG&÷2æVVBöæR×F–ÖR6WGW(	B'Vâ67&—G2ó##bÓbÓ#ö6öææV7F–öç2ç7Â–âF†R7W&6R5ÂVF—F÷"ÂF†Vâ&R×WÆöBâs°¢gVæ7F–öâö—4Ö—76–æuF&ÆR†W'"’·°¢f"ÒÒ‚†W'"bb†W'"æÖW76vRÇÂrr’’²rr²†W'"bb†W'"æ6öFRÇÂrr’’’çFôÆ÷vW$66R‚“°¢&WGW&âöFöW2æ÷BW†—7GÇ&VÆF–öçÇ66†VÖ66†WÆf–æBF†RF&ÆWÇw'7C#RòçFW7B†Ò“°¢×Ð¢gVæ7F–öâ&Vg&W6„6öæä6÷VçG2‚’·°¢f"VÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6öæâÖ6÷VçG2r“²–b‚VÂ’&WGW&ã°¢6"æg&öÒ‚v6öææV7F–öç2r’ç6VÆV7B‚v÷væW"r’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‡"æW'&÷"’·²VÂçFW‡D6öçFVçBÒö—4Ö—76–æuF&ÆR‡"æW'&÷"’òô4ôäåõ4UEUôÕ4r¢rs²&WGW&ã²×Ð¢f"6÷VçG2Ò··×Ó²‡"æFFÇÂµÒ’æf÷$V6‚†gVæ7F–öâ‡‚’·²6÷VçG5·‚æ÷væW%ÒÒ†6÷VçG5·‚æ÷væW%ÒÇÂ’²²×Ò“°¢f"'G2Òö&¦V7Bæ¶W—2†6÷VçG2’ç6÷'B‚’æÖ†gVæ7F–öâ†ò’·²&WGW&âò²s¢r²6÷VçG5¶õÓ²×Ò“°¢VÂçFW‡D6öçFVçBÒ'G2æÆVæwF‚ò‚u7F÷&VB(	Br²'G2æ¦ö–â‚r+rr’’¢tæò6öææV7F–öç2WÆöFVB–WBâs°¢×Ò“°¢×Ð¢gVæ7F–öâv—&T6öææV7F–öç5æVÂ‚’·°¢f"'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6öæâ×WÆöBr“²–b‚'Fâ’&WGW&ã°¢&Vg&W6„6öæä6÷VçG2‚“°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"÷væW"Ò†Fö7VÖVçBævWDVÆVÖVçD'”–B‚v6öæâÖ÷væW"r’ÇÂ··×Ò’çfÇVS°¢f"f–ÆTVÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6öæâÖf–ÆRr“°¢f"7FGW2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6öæâ×7FGW2r“°¢f"f–ÆRÒf–ÆTVÂbbf–ÆTVÂæf–ÆW2bbf–ÆTVÂæf–ÆW5³Ó°¢–b‚f–ÆR’·²7FGW2çFW‡D6öçFVçBÒt6†ö÷6R55bf—'7Bâs²&WGW&ã²×Ð¢7FGW2çFW‡D6öçFVçBÒu&VF–æ~(
bs°¢f"&VFW"ÒæWrf–ÆU&VFW"‚“°¢&VFW"æöæÆöBÒgVæ7F–öâ‚’·°¢f"&÷w2Ò'6T6öææV7F–öç477b‡&VFW"ç&W7VÇBÂ÷væW"“°¢–b‚&÷w2æÆVæwF‚’·²7FGW2çFW‡D6öçFVçBÒtæò6öææV7F–öç2f÷VæB†W‡V7FVBÆ–æ¶VD–â6öææV7F–öç2æ77b’âs²&WGW&ã²×Ð¢7FGW2çFW‡D6öçFVçBÒuWÆöF–ærr²&÷w2æÆVæwF‚²~(
bs°¢òò&WÆ6RF†—2FVÖÖFRw26WBÂF†Vâ–ç6W'B–â6‡Væ·2à¢6"æg&öÒ‚v6öææV7F–öç2r’æFVÆWFR‚’æW‚v÷væW"rÂ÷væW"’çF†Vâ†gVæ7F–öâ†B’·°¢–b†BæW'&÷"bbö—4Ö—76–æuF&ÆR†BæW'&÷"’’·²7FGW2çFW‡D6öçFVçBÒô4ôäåõ4UEUôÕ4s²&WGW&ã²×Ð¢f"4…Tä²ÒSÂ–G‚Ò°¢†gVæ7F–öâæW‡B‚’·°¢–b†–G‚ãÒ&÷w2æÆVæwF‚’·²7FGW2çFW‡D6öçFVçBÒu6fVBr²&÷w2æÆVæwF‚²r6öææV7F–öç2f÷"r²÷væW"²râs²&Vg&W6„6öæä6÷VçG2‚“²&WGW&ã²×Ð¢6"æg&öÒ‚v6öææV7F–öç2r’æ–ç6W'B‡&÷w2ç6Æ–6R†–G‚Â–G‚²4…Tä²’’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‡"æW'&÷"’·²7FGW2çFW‡D6öçFVçBÒö—4Ö—76–æuF&ÆR‡"æW'&÷"’òô4ôäåõ4UEUôÕ4r¢‚tW'&÷#¢r²"æW'&÷"æÖW76vR“²&WGW&ã²×Ð¢–G‚³Ò4…Tä³²æW‡B‚“°¢×Ò“°¢×Ò’‚“°¢×Ò“°¢×Ó°¢&VFW"ç&VD5FW‡B†f–ÆR“°¢×Ò“°¢×Ð ¢gVæ7F–öâ&VæFW%ÆææW"‚’·°¢f"†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×ÆææW"r“°¢–b‚†÷7B’&WGW&ã°¢f"—FV×2Ò÷4ÆÄ—FV×2‚“°¢f"‡FÖÂÒsÇ6Æ73Ò'ÆææW"Ö–çG&ò#ãÇ7G&öæsåÆææW#£Â÷7G&öæsâ6†V6·2F†R6ÆVæF#¢66†VGVÆ–ær6öæfÆ–7G2†öæR7V¶W"F÷V&ÆRÖ&öö¶VB“Â÷âs° ¢f"6öæfÆ–7G2Òf–æD6öæfÆ–7G2‚“°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'ÆææW"×6V7F–öâ#ãÆF—b6Æ73Ò'ÆææW"×6V2Ö†VB#ãÇ7â6Æ73Ò'ÆææW"×6V2×F—FÆR#âb3“ƒƒƒ²66†VGVÆ–ær6öæfÆ–7G3Â÷7ããÇ7â6Æ73Ò'ÆææW"×6V2×7V"#âr²6öæfÆ–7G2æÆVæwF‚²rf÷VæCÂ÷7ããÂöF—câs°¢–b‚6öæfÆ–7G2æÆVæwF‚’·°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'ÆææW"ÖV×G’#äæò6öæfÆ–7G2fÖF6ƒ²WfW'’76–væVB7V¶W"—2–âöæRÆ6RBF–ÖRãÂöF—câs°¢×ÒVÇ6R·°¢6öæfÆ–7G2æf÷$V6‚†gVæ7F–öâ†2’·°¢f"v†òÒ2çv†òæ6†$Bƒ’çFõWW$66R‚’²2çv†òç6Æ–6Rƒ“°¢‡FÖÂ³ÒsÆF—b6Æ73Ò&6öæfÆ–7B×&÷r#ãÇ7â6Æ73Ò&6öæfÆ–7BÖ–6öâ#âb3“ƒƒƒ³Â÷7ããÆF—b6Æ73Ò&6öæfÆ–7BÖ&öG’#âr°¢sÇ7â6Æ73Ò&6öæfÆ–7B×v†ò#âr²W66T‡FÖÂ‡v†ò’²sÂ÷7ãâ—2&öö¶VBf÷"Gvò÷fW&Æ–ærWfVçG3¢r°¢sÇ7â6Æ73Ò&6öæfÆ–7B×g2#âr°¢sÆ'WGFöâ6Æ73Ò&6öæfÆ–7BÖWgB"FF×&VbÖ¶–æCÒ"r²2ææ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†2ææ¶W’’’²r#âr²W66T‡FÖÂ†2æææÖR’²sÂö'WGFöãâ‚r²W66T‡FÖÂ†2ææFFU÷7G"ÇÂsòr’²r’r°¢rfæ'7·g2fæ'7²r°¢sÆ'WGFöâ6Æ73Ò&6öæfÆ–7BÖWgB"FF×&VbÖ¶–æCÒ"r²2æ"æ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†2æ"æ¶W’’’²r#âr²W66T‡FÖÂ†2æ"ææÖR’²sÂö'WGFöãâ‚r²W66T‡FÖÂ†2æ"æFFU÷7G"ÇÂsòr’²r’r°¢sÂ÷7ããÂöF—cãÂöF—câs°¢×Ò“°¢×Ð¢òò6öæfÆ–7G2ævVÆG—VB(	BF†RöæW2FFW26âwB&WfVÂ†&ö&Böfg6—FRÀ¢òòÆVfR’âÆ—7FVBÆöæw6–FRF†RFWFV7FVBöæW26òF†R6V7F–öâ—2F†Rv†öÆP¢òò–7GW&RÂæ÷B§W7Bv†BF†R6ÆVæF"6÷VÆBv÷&²÷WBà¢f"ÖçVÄ6bÒ—FV×2æf–ÇFW"†gVæ7F–öâ†—B’·°¢&WGW&â—Bç7Bbb—Bæ†–FFVâbb7G&–ær‚†—Bç7F'Dö&¢ÇÂ—B’æ6öæfÆ–7Eöæ÷FRÇÂrr’çG&–Ò‚“°¢×Ò“°¢ÖçVÄ6bæf÷$V6‚†gVæ7F–öâ†—B’·°¢‡FÖÂ³ÒsÆF—b6Æ73Ò&6öæfÆ–7B×&÷r#ãÇ7â6Æ73Ò&6öæfÆ–7BÖ–6öâ#âb3“ƒƒƒ³Â÷7ããÆF—b6Æ73Ò&6öæfÆ–7BÖ&öG’#âr°¢sÆ'WGFöâ6Æ73Ò&6öæfÆ–7BÖWgB"FF×&VbÖ¶–æCÒ"r²—Bæ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r#âr°¢W66T‡FÖÂ†—BææÖR’²sÂö'WGFöãâfÖF6ƒ²r°¢W66T‡FÖÂ…7G&–ær‚†—Bç7F'Dö&¢ÇÂ—B’æ6öæfÆ–7Eöæ÷FR’çG&–Ò‚’’°¢rÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6bÖVF—B"FFÖ6bÖ¶–æCÒ"r²—Bæ¶–æB²r"FFÖ6bÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r#æVF—CÂö'WGFöãâr°¢sÂöF—cãÂöF—câs°¢×Ò“°¢‡FÖÂ³ÒsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&"ÖFF'Fâ"–CÒ'ÆææW"Ö6bÖFB#âr°¢sÇ7â6Æ73Ò&"ÖFF'FâÖ–2"&–Ö†–FFVãÒ'G'VR#â³Â÷7ãâFB66†VGVÆ–ær6öæfÆ–7CÂö'WGFöãâr°¢sÆF—b6Æ73Ò&"Öf÷&Ò"–CÒ'ÆææW"Ö6bÖf÷&Ò"†–FFVãâr°¢sÆ–çWBG—SÒ'FW‡B"6Æ73Ò&"Ö–çWB"–CÒ'ÆææW"Ö6b×"WFö6ö×ÆWFSÒ&öfb"r°¢wÆ6V†öÆFW#Ò%v†–6‚WfVçCò7F'BG—–ær—G2æÖUÇS##b#âr°¢sÆF—b6Æ73Ò&6bÖ†—G2"–CÒ'ÆææW"Ö6bÖ†—G2#ãÂöF—câr°¢sÇFW‡F&V6Æ73Ò&"Ö–çWB"–CÒ'ÆææW"Ö6bÖæ÷FR"&÷w3Ò#""r°¢wÆ6V†öÆFW#Ò%v†EÇS#—2F†R6Æ6ƒòRærâF†÷"—2BF†R&ö&Böfg6—FRF†BvVV²#ãÂ÷FW‡F&Vâr°¢sÆF—b6Æ73Ò&"Öf÷&ÒÖ7F–öç2#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&"Ö'Fâ×&–Ö'’"–CÒ'ÆææW"Ö6b×6fR"F—6&ÆVCå6fR6öæfÆ–7CÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&"Ö'FâÖv†÷7B"–CÒ'ÆææW"Ö6bÖ6æ6VÂ#ä6æ6VÃÂö'WGFöãâr°¢sÇ7â6Æ73Ò&"Öf÷&ÒÖ†–çB"–CÒ'ÆææW"Ö6b×–6¶VB#ãÂ÷7ãâr°¢sÂöF—câr°¢sÂöF—câs°¢‡FÖÂ³ÒsÂöF—câs° ¢òòTåDõT4„TBUdTåE2(	Bv2$6÷fW&vRv2'’FW'&—F÷'’"Âv†–6‚7Æ—BF†—0¢òòÆ—7B'’v†÷6RF&vWF–ær$ôd”ÄRâWfVçBÖF6†VBâF†÷6R&öf–ÆW2&P¢òòvöæR„‡W&ÆW’##bÓ‚ÓR’ÂæBv—F‚F†VÒF†R–FVöbFW'&—F÷'’âF†P¢òòv÷&²—G6VÆb—2Væ6†ævVBæB—2v†BævVÆ7GVÆÇ’W6W2F†—2f÷# ¢òòW6öÖ–ærWfVçG2v—F‚æò7V¶W"F†Bæö&öG’†2FVÇBv—F‚–WBà¢òò÷4†æFÆVB‚’—2F†R6–ævÆR&Ç&VG’FVÇBv—F‚"FW7B(	BfÆvv–ærÀ¢òòFvv–ærÂæ÷F–ær÷"&6†—f–ærâWfVçBG&÷2—Böfb†W&RÂ6òF†RÆ—7@¢òò6‡&–æ·226†Rv÷&·2—Bà¢òð¢òò&WGFW"F†âv†B—B&WÆ6VB–âöæRv“¢F†RfÆr'WGFöâW6VBFòöffW ¢òòöæÇ’F†RFW'&—F÷'’w2÷væW"Â6òâWfVçB–â%fW&Öw2"FW'&—F÷'’6÷VÆB&P¢òòöæRÖ6Æ–6²fÆvvVBf÷"fW&ÖæBæö&öG’VÇ6RâV6‚&÷ræ÷r6'&–W2F†P¢òòv†öÆR&÷7FW"–â–6¶W"Â6ò6†R6âfÆr—Bf÷"v†öWfW"—B7GVÆÇ¢òò7V—G2(	Bv†–6‚—2F†R§VFvVÖVçBF†R&öf–ÆW2vW&RwVW76–ærBà¢f"4Ò#S°¢f"v2Ò—FV×2æf–ÇFW"†gVæ7F–öâ†—B’·°¢&WGW&â—Bç7Bbb—Bæ†–FFVâbb†—Bç7V¶W"bb—Bç7V¶W"çG&–Ò‚’’bb÷4†æFÆVB†—B“°¢×Ò’ç6÷'B†gVæ7F–öâ†Â"’·²&WGW&âç6÷'BÒ"ç6÷'C²×Ò“°¢f"÷W6öÖ–ærÒ—FV×2æf–ÇFW"†gVæ7F–öâ†—B’·²&WGW&â—Bç7Bbb—Bæ†–FFVã²×Ò“°¢f"ö6÷fW&VBÒ÷W6öÖ–æræf–ÇFW"†gVæ7F–öâ†—B’·²&WGW&â—Bç7V¶W"bb—Bç7V¶W"çG&–Ò‚“²×Ò“°¢‡FÖÂ³ÒsÆF—b6Æ73Ò'ÆææW"×6V7F–öâ#ãÆF—b6Æ73Ò'ÆææW"×6V2Ö†VB#âr°¢sÇ7â6Æ73Ò'ÆææW"×6V2×F—FÆR#âb3#ƒ#3²VçF÷V6†VBWfVçG3Â÷7ãâr°¢sÇ7â6Æ73Ò'ÆææW"×6V2×7V"#çW6öÖ–ærÂæò7V¶W"76–væVBÂæ÷F†–ærFöæR–WCÂ÷7ããÂöF—câs°¢‡FÖÂ³ÒsÆF—b6Æ73Ò&vÖ÷væW"#ãÆF—b6Æ73Ò&vÖ÷væW"Ö†VB#âr°¢sÇ7â6Æ73Ò&vÖ÷væW"ÖæÖR#åv†öÆR6FÆöwVSÂ÷7ãâr°¢sÇ7â6Æ73Ò&vÖ÷væW"×7FB#âr²÷W6öÖ–æræÆVæwF‚²rW6öÖ–ærfÖ–FF÷C²r²ö6÷fW&VBæÆVæwF‚°¢r6÷fW&VBfÖ–FF÷C²Æ#âr²v2æÆVæwF‚²rVçF÷V6†VCÂö#ãÂ÷7ãâr°¢sÂöF—câs°¢–b‚v2æÆVæwF‚’·°¢‡FÖÂ³ÒsÇ6Æ73Ò&vÖæöæR#âb33²æ÷F†–ærÆVgBFòG&–vRfÖF6ƒ²WfW'’W6öÖ–ærWfVçB—276–væVBÂfÆvvVB÷"Ç&VG’FVÇBv—F‚ãÂ÷âs°¢×ÒVÇ6R·°¢‡FÖÂ³ÒsÆF—b6Æ73Ò&vÖÆ—7B#âs°¢v2ç6Æ–6RƒÂ4’æf÷$V6‚†gVæ7F–öâ†—B’·°¢f"Æö2Ò¶—BæÆö6F–öåÒæf–ÇFW"„&ööÆVâ’æ¦ö–â‚rfÖ–FF÷C²r“°¢f"6VÄ–BÒvvv†òÒr²—Bæ¶–æB²rÒr²7G&–ær†—Bæ¶W’’ç&WÆ6R‚õµæ×¤Õ£Ó•ÒörÂrr“°¢‡FÖÂ³ÒsÆF—b6Æ73Ò&v×&÷r#ãÆF—câr°¢sÆ'WGFöâ6Æ73Ò&vÖæÖR"FF×&VbÖ¶–æCÒ"r²—Bæ¶–æB²r"FF×&VbÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r#âr²W66T‡FÖÂ†—BææÖR’²sÂö'WGFöãâr°¢sÇ6Æ73Ò&vÖÖWF#âr²W66T‡FÖÂ†—BæFFU÷7G"ÇÂtFFRD$Br’²†Æö2òrfÖ–FF÷C²r²Æö2¢rr’²sÂ÷âr°¢sÂöF—câr°¢sÆF—b6Æ73Ò&vÖ7F–öç2#âr°¢sÇ6VÆV7B6Æ73Ò&v×v†ò"–CÒ"r²6VÄ–B²r"&–ÖÆ&VÃÒ$fÆrr²W66T‡FÖÂ†—BææÖR’²rf÷"#âr°¢õ5õ$õ5DU"æÖ†gVæ7F–öâ†â’·²&WGW&âsÆ÷F–öâfÇVSÒ"r²W66T‡FÖÂ†â’²r#âr²W66T‡FÖÂ†â’²sÂö÷F–öãâs²×Ò’æ¦ö–â‚rr’°¢sÂ÷6VÆV7Câr°¢sÆ'WGFöâ6Æ73Ò'Ö'Fâ&–Ö'’"FFÖfÆr×6VÃÒ"r²6VÄ–B²r"FFÖ³Ò"r²—Bæ¶–æB²r"FFÖ¶W“Ò"r²W66T‡FÖÂ…7G&–ær†—Bæ¶W’’’²r#â²fÆsÂö'WGFöãâr°¢sÂöF—câr°¢sÂöF—câs°¢×Ò“°¢–b†v2æÆVæwF‚â4’‡FÖÂ³ÒsÇ6Æ73Ò&vÖÖ÷&R#å6†÷v–ærf—'7Br²4²röbr²v2æÆVæwF‚²rfÖF6ƒ²76–vâ÷"fÆr6öÖRFò6ÆV"F†RÆ—7BãÂ÷âs°¢‡FÖÂ³ÒsÂöF—câs°¢×Ð¢‡FÖÂ³ÒsÂöF—câs°¢‡FÖÂ³ÒsÂöF—câs°¢òòv&ÒÖ–çG&ò6öææV7F–öç2WÆöFW"(	B÷vW'2'v&Òf–(
b"öâFVWF&vWG2à¢‡FÖÂ³ÒsÆF—b6Æ73Ò'ÆææW"×6V7F–öâ6öæâ×æVÂ#ãÆF—b6Æ73Ò'ÆææW"×6V2Ö†VB#âr°¢sÇ7â6Æ73Ò'ÆææW"×6V2×F—FÆR#âb3#ƒ#s“²v&Ò–çG&÷2fÖF6ƒ²FVÒÆ–æ¶VD–â6öææV7F–öç3Â÷7ãâr°¢sÇ7â6Æ73Ò'ÆææW"×6V2×7V"#æfÆw2fÆGVó·v&Òf–f†VÆÆ—²g&GVó²öâFVWF&vWG2fÖ–FF÷C²7F—2–â÷W"D"ÂæWfW"6VçBFò“Â÷7ããÂöF—câr°¢sÇ6Æ73Ò&6öæâÖ†VÇ#äV6‚FVÖÖFS¢Æ–æ¶VD–âg&'#²6WGF–æw2g&'#²vWB6÷’öb–÷W"FFg&'#²6öææV7F–öç2g&'#²WÆöBF†R55b†W&RãÂ÷âr°¢sÆF—b6Æ73Ò&6öæâ×&÷r#ãÇ6VÆV7B–CÒ&6öæâÖ÷væW""&–ÖÆ&VÃÒ%v†÷6R6öææV7F–öç2#âr°¢õ5õ$õ5DU"æÖ†gVæ7F–öâ†â’·²&WGW&âsÆ÷F–öâfÇVSÒ"r²W66T‡FÖÂ†â’²r#âr²W66T‡FÖÂ†â’²sÂö÷F–öãâs²×Ò’æ¦ö–â‚rr’°¢sÂ÷6VÆV7CãÆ–çWBG—SÒ&f–ÆR"–CÒ&6öæâÖf–ÆR"66WCÒ"æ77b"&–ÖÆ&VÃÒ$6öææV7F–öç255b#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ&–Ö'’"–CÒ&6öæâ×WÆöB#åWÆöCÂö'WGFöãâr°¢sÇ7â–CÒ&6öæâ×7FGW2"6Æ73Ò&6öæâ×7FGW2#ãÂ÷7ããÂöF—câr°¢sÆF—b–CÒ&6öæâÖ6÷VçG2"6Æ73Ò&6öæâÖ6÷VçG2#ãÂöF—cãÂöF—câs°¢†÷7Bæ–ææW$…DÔÂÒ‡FÖÃ°¢v—&T6öææV7F–öç5æVÂ‚“° ¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FF×&VbÖ¶–æEÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²÷4÷Vå&Vb†VÂævWDGG&–'WFR‚vFF×&VbÖ¶–æBr’ÂVÂævWDGG&–'WFR‚vFF×&VbÖ¶W’r’“²×Ò“°¢×Ò“° ¢òòFBòVF—B66†VGVÆ–ær6öæfÆ–7Bg&öÒF†RÆææW"Âv†–6‚—2v†W&P¢òòævVÆ—2Æöö¶–ærv†Vâ6†Ræ÷F–6W2öæR„‡W&ÆW’##bÓrÓ3’à¢òòVF—F–ærâW†—7F–ær6öæfÆ–7B†Vç2–âF†R&÷r—B&VÆöæw2Fò(	BF†P¢òòæ÷FR&V6öÖW2f–VÆBv†W&RF†RFW‡Bv2ÂæBæ÷F†–ærfÆöG2FòF†RF÷ ¢òòöbF†Rv–æF÷r„‡W&ÆW’##bÓrÓ3’à¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FFÖ6bÖ¶–æEÒr’æf÷$V6‚†gVæ7F–öâ†VÂ’·°¢VÂæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢f"—BÒ÷4ÆÄ—FV×2‚’æf–ÇFW"†gVæ7F–öâ‡‚’·°¢&WGW&â‚æ¶–æBÓÓÒVÂævWDGG&–'WFR‚vFFÖ6bÖ¶–æBr’b`¢7G&–ær‡‚æ¶W’’ÓÓÒVÂævWDGG&–'WFR‚vFFÖ6bÖ¶W’r“°¢×Ò•³Ó°¢f"&÷rÒVÂç&VçDæöFS²òòæ6öæfÆ–7BÖ&öG¢–b‚—BÇÂ&÷rÇÂ&÷rçVW'•6VÆV7F÷"‚ræ"Öf÷&Òr’’&WGW&ã°¢f"7W"Ò7G&–ær‚†—Bç7F'Dö&¢ÇÂ—B’æ6öæfÆ–7Eöæ÷FRÇÂrr“°¢f"¶VWÒ&÷ræ–ææW$…DÔÃ°¢f"rÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢ræ6Æ74æÖRÒv"Öf÷&Òs°¢ræ–ææW$…DÔÂÒsÇFW‡F&V6Æ73Ò&"Ö–çWB"&÷w3Ò#"#ãÂ÷FW‡F&Vâr°¢sÆF—b6Æ73Ò&"Öf÷&ÒÖ7F–öç2#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&"Ö'Fâ×&–Ö'’"FFÖvóå6fSÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&"Ö'FâÖv†÷7B"FFÖ6æ6VÃä6æ6VÃÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6bÖVF—B"FFÖ6ÆV"7G–ÆSÒ&Ö&v–âÖÆVgC¦WFó²#å&VÖ÷fSÂö'WGFöãâr°¢sÂöF—câs°¢&÷ræ–ææW$…DÔÂÒsÇ7G&öæsâr²W66T‡FÖÂ†—BææÖR’²sÂ÷7G&öæsâs°¢&÷ræVæD6†–ÆB‡r“°¢f"FÒrçVW'•6VÆV7F÷"‚wFW‡F&Vr“°¢FçfÇVRÒ7W#²Fæfö7W2‚“²Fç6WE6VÆV7F–öå&ævR†7W"æÆVæwF‚Â7W"æÆVæwF‚“°¢gVæ7F–öâFöæR‡fÂ’·²÷5V–6µw&—FR†—Bæ¶–æBÂ—Bæ¶W’Â·²6öæfÆ–7Eöæ÷FS¢fÂ×Ò“²×Ð¢rçVW'•6VÆV7F÷"‚u¶FFÖvõÒr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢FöæR‡FçfÇVRçG&–Ò‚’ÇÂçVÆÂ“°¢×Ò“°¢rçVW'•6VÆV7F÷"‚u¶FFÖ6ÆV%Òr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²FöæR†çVÆÂ“²×Ò“°¢rçVW'•6VÆV7F÷"‚u¶FFÖ6æ6VÅÒr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢&÷ræ–ææW$…DÔÂÒ¶VW°¢&VæFW%ÆææW"‚“²òò&Wv—&RF†R&W7F÷&VB&÷p¢×Ò“°¢FæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†Wb’·°¢–b†Wbæ¶W’ÓÓÒtVçFW"rbb†WbæÖWF¶W’ÇÂWbæ7G&Ä¶W’’’·²Wbç&WfVçDFVfVÇB‚“²FöæR‡FçfÇVRçG&–Ò‚’ÇÂçVÆÂ“²×Ð¢×Ò“°¢×Ò“°¢×Ò“°¢òò"²FB66†VGVÆ–ær6öæfÆ–7B"(	B–6²F†RWfVçBg&öÒf–ÇFW&VBÆ—7@¢òò&F†W"F†âG—–ær'BöbæÖR–çFò&ö×BæBF†VâçVÖ&W"Fð¢òò6†ö÷6R&WGvVVâF†RÖF6†W2à¢f"6dFBÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6bÖFBr“°¢f"6df÷&ÒÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6bÖf÷&Òr“°¢–b†6dFBbb6df÷&Ò’·°¢f"6eÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6b×r“°¢f"6d†—G2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6bÖ†—G2r“°¢f"6dæ÷FRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6bÖæ÷FRr“°¢f"6e6fRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6b×6fRr“°¢f"6e–6¶VBÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6b×–6¶VBr“°¢f"÷–6²ÒçVÆÃ°¢gVæ7F–öâ6d6Æ÷6R‚’·°¢6df÷&Òæ†–FFVâÒG'VS²6dFBæ†–FFVâÒfÇ6S°¢÷–6²ÒçVÆÃ²6eçfÇVRÒrs²6dæ÷FRçfÇVRÒrs°¢6d†—G2æ–ææW$…DÔÂÒrs²6e–6¶VBçFW‡D6öçFVçBÒrs²6e6fRæF—6&ÆVBÒG'VS°¢×Ð¢gVæ7F–öâ6e7–æ2‚’·²6e6fRæF—6&ÆVBÒ…÷–6²bb6dæ÷FRçfÇVRçG&–Ò‚’“²×Ð¢6dFBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢6df÷&Òæ†–FFVâÒfÇ6S²6dFBæ†–FFVâÒG'VS²6eæfö7W2‚“°¢×Ò“°¢Fö7VÖVçBævWDVÆVÖVçD'”–B‚wÆææW"Ö6bÖ6æ6VÂr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂ6d6Æ÷6R“°¢6eæFDWfVçDÆ—7FVæW"‚v–çWBrÂgVæ7F–öâ‚’·°¢÷–6²ÒçVÆÃ²6e–6¶VBçFW‡D6öçFVçBÒrs²6e7–æ2‚“°¢f"Ò6eçfÇVRçG&–Ò‚’çFôÆ÷vW$66R‚“°¢–b‡æÆVæwF‚Â"’·²6d†—G2æ–ææW$…DÔÂÒrs²&WGW&ã²×Ð¢f"†—G2Ò÷4ÆÄ—FV×2‚’æf–ÇFW"†gVæ7F–öâ†—B’·°¢&WGW&â—Bç7Bbb—Bæ†–FFVâbb7G&–ær†—BææÖRÇÂrr’çFôÆ÷vW$66R‚’æ–æFW„öb‡’ÓÒÓ°¢×Ò’ç6Æ–6RƒÂr“°¢–b‚†—G2æÆVæwF‚’·°¢6d†—G2æ–ææW$…DÔÂÒsÆF—b6Æ73Ò&6bÖ†—BÖæöæR#äæòW6öÖ–ærWfVçBÖF6†W2F†BãÂöF—câs°¢&WGW&ã°¢×Ð¢6d†—G2æ–ææW$…DÔÂÒ†—G2æÖ†gVæ7F–öâ†—BÂ’’·°¢&WGW&âsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6bÖ†—B"FFÖ“Ò"r²’²r#âr°¢W66T‡FÖÂ†—BææÖR’°¢sÇ7â6Æ73Ò&6bÖ†—B×v†Vâ#âr²W66T‡FÖÂ…7G&–ær†—BæFFU÷7G"ÇÂrr’’²sÂ÷7ãâr°¢sÂö'WGFöãâs°¢×Ò’æ¦ö–â‚rr“°¢6d†—G2çVW'•6VÆV7F÷$ÆÂ‚ræ6bÖ†—Br’æf÷$V6‚†gVæ7F–öâ†"Â’’·°¢"æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢÷–6²Ò†—G5¶•Ó°¢6eçfÇVRÒ÷–6²ææÖS°¢6d†—G2æ–ææW$…DÔÂÒrs°¢6e–6¶VBçFW‡D6öçFVçBÒvöâr²÷–6²ææÖS°¢6dæ÷FRæfö7W2‚“°¢6e7–æ2‚“°¢×Ò“°¢×Ò“°¢×Ò“°¢6dæ÷FRæFDWfVçDÆ—7FVæW"‚v–çWBrÂ6e7–æ2“°¢6e6fRæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢–b‚÷–6²ÇÂ6dæ÷FRçfÇVRçG&–Ò‚’’&WGW&ã°¢÷5V–6µw&—FR…÷–6²æ¶–æBÂ÷–6²æ¶W’Â·²6öæfÆ–7Eöæ÷FS¢6dæ÷FRçfÇVRçG&–Ò‚’×Ò“°¢×Ò“°¢6dæ÷FRæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·°¢–b†Ræ¶W’ÓÓÒtW66Rr’·²Rç&WfVçDFVfVÇB‚“²6d6Æ÷6R‚“²×Ð¢–b†Ræ¶W’ÓÓÒtVçFW"rbb†RæÖWF¶W’ÇÂRæ7G&Ä¶W’’’·²Rç&WfVçDFVfVÇB‚“²6e6fRæ6Æ–6²‚“²×Ð¢×Ò“°¢6eæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·°¢–b†Ræ¶W’ÓÓÒtW66Rr’·²Rç&WfVçDFVfVÇB‚“²6d6Æ÷6R‚“²×Ð¢×Ò“°¢×Ð¢òòGvò6†W3¢f—†VBFFÖfÆr‡W6VBVÇ6Wv†W&R’Â÷"FFÖfÆr×6VÂæÖ–æp¢òòF†R&÷rw2÷vâW'6öâ–6¶W"‡F†RVçF÷V6†VBÆ—7BÂv†–6‚ÆWG2ævVÆ–6°¢òòç–öæR&F†W"F†âFW'&—F÷'’w2÷væW"’à¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚u¶FFÖfÆuÒÂ¶FFÖfÆr×6VÅÒr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢f"v†òÒ'FâævWDGG&–'WFR‚vFFÖfÆrr“°¢–b‚v†ò’·°¢f"6VÂÒFö7VÖVçBævWDVÆVÖVçD'”–B†'FâævWDGG&–'WFR‚vFFÖfÆr×6VÂr’ÇÂrr“°¢v†òÒ6VÂò6VÂçfÇVR¢rs°¢×Ð¢–b‚v†ò’&WGW&ã°¢f"¶–æBÒ'FâævWDGG&–'WFR‚vFFÖ²r’Â¶W’Ò'FâævWDGG&–'WFR‚vFFÖ¶W’r“°¢f"—BÒ—FV×2æf–ÇFW"†gVæ7F–öâ‡‚’·²&WGW&â‚æ¶–æBÓÓÒ¶–æBbb7G&–ær‡‚æ¶W’’ÓÓÒ¶W“²×Ò•³Ó°¢–b‚—B’&WGW&ã°¢f"Æ—7BÒ—Bæ–çFW&W7FVBç6Æ–6R‚“°¢–b†Æ—7Bæ–æFW„öb‡v†ò’ÓÓÒÓ’Æ—7BçW6‚‡v†ò“°¢Æ—7BÒõ5õ$õ5DU"æf–ÇFW"†gVæ7F–öâ‡‚’·²&WGW&âÆ—7Bæ–æFW„öb‡‚’ÓÒÓ²×Ò“°¢÷5V–6µw&—FR†¶–æBÂ¶W’Â·²–çFW&W7FVC¢Æ—7B×Ò“°¢×Ò“°¢×Ò“°¢WFFUf–Wt&FvW2‚“°¢×Ð ¢òò6÷VçB&FvW2öâF†RVWVRòÆææW"F'2†÷Vâ×FòÖÇ’6÷VçB²6öæfÆ–7G2’à¢gVæ7F–öâWFFUf–Wt&FvW2‚’·°¢f"Ö2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wgBÖ×–WfVçG2Ö6÷VçBr“°¢–b†Ö2’·°¢f"Ö"Ò×”WfVçG4'V6¶WG2‚“°¢f"ÖâÒÖ"çW6öÖ–æræÆVæwFƒ²òò&FvRÒW6öÖ–ær6÷VçB‡F†R7F–öæ&ÆRöæR¢–b†Ö"ææÖVBbbÖâ’·²Ö2çFW‡D6öçFVçBÒÖã²Ö2ç&VÖ÷fTGG&–'WFR‚v†–FFVâr“²×ÒVÇ6R·²Ö2ç6WDGG&–'WFR‚v†–FFVârÂrr“²×Ð¢×Ð¢f"2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wgB×VWVRÖ6÷VçBr“°¢f"2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wgB×ÆææW"Ö6÷VçBr“°¢–b‡2’·°¢òò6ÖR6÷W&6R2F†R&VæFW&VBVWVR(	BF†R&FvR—26÷VçBöbF†R&÷w0¢òò6†RvÆÂ7GVÆÇ’6VRv†Vâ6†R÷Vç2F†RF"Âæ÷F†–ærVÇ6Rà¢f"âÒVWVT—FV×2‚’æÆVæwFƒ°¢–b†â’·²2çFW‡D6öçFVçBÒã²2ç&VÖ÷fTGG&–'WFR‚v†–FFVâr“²×ÒVÇ6R·²2ç6WDGG&–'WFR‚v†–FFVârÂrr“²×Ð¢×Ð¢–b‡2’·°¢f"2Òf–æD6öæfÆ–7G2‚’æÆVæwFƒ°¢–b†2’·²2çFW‡D6öçFVçBÒ3²2æ6Æ74Æ—7BæFB‚vÆW'Br“²2ç&VÖ÷fTGG&–'WFR‚v†–FFVâr“²×Ð¢VÇ6R·²2ç6WDGG&–'WFR‚v†–FFVârÂrr“²2æ6Æ74Æ—7Bç&VÖ÷fR‚vÆW'Br“²×Ð¢×Ð¢×Ð ¢òò)H)H&W6–Æ–VçBFFÆöF–ær)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòfWF6‚‚’FöW2äõB&V¦V7Böâ…EEW'&÷'2ÂæBÖ–BÖFWÆ÷’VFvR6â6W'fR¢òòæöâÔ¥4ôâW'&÷"vR(	B6ò6†V6²"æö²äB&WG'’Gv–6Rv—F‚&6¶öfb&Vf÷&P¢òòf–Æ–ærâv—F†÷WBF†—2ÂöæRG&ç6–VçB&Æ—7G&æFVBF†Röà¢òò$ÆöF–ærWfVçG>(
b"f÷&WfW"…F†÷"w23ÖÖ–çWFR&æòWfVçG2"÷WFvR’à¢gVæ7F–öâfWF6„WfVçG4§6öâ†GFV×B’·°¢GFV×BÒGFV×BÇÂ°¢&WGW&âfWF6‚‚röWfVçG2æ§6öâr’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‚"æö²’F‡&÷ræWrW'&÷"‚vWfVçG2æ§6öâ…EEr²"ç7FGW2“°¢&WGW&â"æ§6öâ‚“°¢×Ò’æ6F6‚†gVæ7F–öâ†W'"’·°¢–b†GFV×BãÒ2’F‡&÷rW'#°¢&WGW&âæWr&öÖ—6R†gVæ7F–öâ‡&W2’·²6WEF–ÖV÷WB‡&W2ÂGFV×B¢S“²×Ò¢çF†Vâ†gVæ7F–öâ‚’·²&WGW&âfWF6„WfVçG4§6öâ†GFV×B²“²×Ò“°¢×Ò“°¢×Ð¢òòæWfW"ÆVfRF†Rw&–B&Ææ³¢–çBf—6–&ÆRW'&÷"²¶VW&WG'––ærv—F€¢òòW66ÆF–ær&6¶öfbƒW2(i"c26’VçF–ÂÆöB7V66VVG2à¢f"ö÷5&WG'•F–ÖW"ÒçVÆÂÂö÷5&WG'”FVÆ’ÒS°¢gVæ7F–öâ6†÷t÷4ÆöDW'&÷"†VÖ–ÂÂW'"’·°¢f"×6rÒ†W'"bbW'"æÖW76vR’ò7G&–ær†W'"æÖW76vR’¢væWGv÷&²W'&÷"s°¢òò&R×&VæFW"f–ÇW&Rv—F‚6&G2Ç&VG’öâ67&VVâ¶VW2F†RöÆB6&G2(	@¢òò7FÆRFF&VG2v—VBw&–Bà¢–b‚F÷4w&–BçVW'•6VÆV7F÷"‚ræ÷2Ö6&Br’’·°¢7FGW2‚u&Vg&W6‚f–ÆVB‚r²×6r²r’(	B6†÷v–ærF†RÆ7BÆöFVBFFârÂvW'&÷"r“°¢&WGW&ã°¢×Ð¢f"FVÆ’Òö÷5&WG'”FVÆ“°¢ö÷5&WG'”FVÆ’ÒÖF‚æÖ–â†FVÆ’¢"Âc“°¢F÷4w&–Bæ–ææW$…DÔÂÐ¢sÆF—b6Æ73Ò&÷2ÖÆöBÖW'&÷"#âr°¢sÇãÇ7G&öæsä6÷VÆFâg'7Vó·BÆöBF†RWfVçG2ãÂ÷7G&öæsâW7VÆÇ’'&–VbæWGv÷&²÷"FWÆ÷’†–67W‚r²W66T‡FÖÂ†×6r’²r’ãÂ÷âr°¢sÇå&WG'––ærWFöÖF–6ÆÇ’–âr²ÖF‚ç&÷VæB†FVÆ’ò’²w2f†VÆÆ—²r°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ&–Ö'’"–CÒ&÷2×&WG'’Öæ÷r#å&WG'’æ÷sÂö'WGFöããÂ÷âr°¢sÂöF—câs°¢f"'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×&WG'’Öæ÷rr“°¢–b†'Fâ’'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²6ÆV%F–ÖV÷WB…ö÷5&WG'•F–ÖW"“²&VæFW$÷2†VÖ–Â“²×Ò“°¢6ÆV%F–ÖV÷WB…ö÷5&WG'•F–ÖW"“°¢ö÷5&WG'•F–ÖW"Ò6WEF–ÖV÷WB†gVæ7F–öâ‚’·²&VæFW$÷2†VÖ–Â“²×ÒÂFVÆ’“°¢×Ð¢òòÆ—fRG&6¶–ær…7W&6R’f–ÆVB'WBF†R6FÆörÆöFVC¢v&âÆ÷VFÇ’(	@¢òò6&G26–ÆVçFÇ’Æ÷6–ærF†V—"7FvW2öGFVæFVW2&VG22FFÆ÷72à¢gVæ7F–öâ6†÷u6$FVw&FVB†W'$ö&¢ÂVÖ–Â’·°¢f"†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×6"×v&æ–ærr“°¢–b‚W'$ö&¢’·²–b††÷7B’†÷7Bç&VÖ÷fR‚“²&WGW&ã²×Ð¢–b‚†÷7B’·°¢†÷7BÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢†÷7Bæ–BÒv÷2×6"×v&æ–ærs°¢†÷7Bæ6Æ74æÖRÒv÷2×6"×v&æ–ærs°¢F÷4w&–Bç&VçDæöFRæ–ç6W'D&Vf÷&R††÷7BÂF÷4w&–B“°¢×Ð¢†÷7Bæ–ææW$…DÔÂÒrb3“ƒƒƒ²Æ—fRG&6¶–ærFF6÷VÆFâg'7Vó·BÆöB‚r²W66T‡FÖÂ†W'$ö&¢æÖW76vRÇÂ7G&–ær†W'$ö&¢’’²r’âr°¢t6&G26†÷r6FÆör–æfòöæÇ’(	B7FvW2ÂGFVæFVW2æBVF—G2&VV"v†Vâ—B&V6öææV7G2âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'Ö'Fâ"–CÒ&÷2×6"×&WG'’#å&WG'’æ÷sÂö'WGFöãâs°¢f""ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×6"×&WG'’r“°¢–b†"’"æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²&VæFW$÷2†VÖ–Â“²×Ò“°¢6ÆV%F–ÖV÷WB…ö÷5&WG'•F–ÖW"“°¢ö÷5&WG'•F–ÖW"Ò6WEF–ÖV÷WB†gVæ7F–öâ‚’·²&VæFW$÷2†VÖ–Â“²×ÒÂ3“°¢×Ð¢òò6fWG’æWC¢å’Væ†æFÆVB7–æ2f–ÇW&Rv†–ÆRF†Rw&–B—27F–ÆÂV×G¢òò–çG2F†R&WG'’6&B–ç7FVBöb7G&æF–ær$ÆöF–ærWfVçG>(
b"f÷&WfW"à¢v–æF÷ræFDWfVçDÆ—7FVæW"‚wVæ†æFÆVG&V¦V7F–öârÂgVæ7F–öâ†R’·°¢–b‚F÷4w&–BbbF÷4w&–BçVW'•6VÆV7F÷"‚ræ÷2Ö6&Br’bbF÷4w&–BçVW'•6VÆV7F÷"‚ræ÷2ÖÆöBÖW'&÷"r’’·°¢6†÷t÷4ÆöDW'&÷"†vWD6öÆÆ$æÖR‚’ÇÂuFVÒrÂ†RbbRç&V6öâ’ÇÂ··×Ò“°¢×Ð¢×Ò“° ¢òòG&6¶–ær×&–6†æW7266÷&R(	Bv†VâGvò6&G2&RF†R6ÖRWfVçBÂ¶VWF†RöæP¢òò6''––ærF†RÖ÷7B—VÆ–æRöGFVæFVRFF‡6ò&&R67&VBGWRÆ÷6W2Fð¢òòF†RG&6¶VB&V6÷&B’â6FÆörv–ç2F–W2†—Bw2F†R7W&FVB6÷W&6R’à¢gVæ7F–öâ÷G&6µ66÷&R†2’·°¢f""Ò2åöÖöFÅ&V2ÇÂ··×Ó°¢f"2Ò‡"ç7FvU÷Fw2ÇÂµÒ’æÆVæwF‚¢3°¢–b‡"ç7V¶W"’2³Ò#°¢–b‡"æGFVæFVW2bb"æGFVæFVW2æÆVæwF‚’2³Ò#°¢–b‡"æ–çFW&W7FVBbb"æ–çFW&W7FVBæÆVæwF‚’2³Ò#°¢–b‡"æGFVæE÷fW&F–7B’2³Ò°¢–b‡"ç6fVB’2³Ò#°¢–b‡"æFV6—6–öâ’2³Ò#°¢–b‡"ææ÷FW2’2³Ò°¢–b†2æFF6WBæWfVçDçVÒ’2³ÒãS²òò&VfW"6FÆöröâF–P¢&WGW&â3°¢×Ð¢òòFRÖGWÆ–6FRF†Rw&–C¢F†R67&W"6öÖWF–ÖW2ÆæG2&æB6&Bf÷"âWfVç@¢òòÇ&VG’G&6¶VB„ævVÆ¶VW2f–æF–ær&F÷V&ÆW2"’âw&÷W'’F†RgW§§¢òòæÖR¶6—G’·–V"¶W’Â¶VWF†R&–6†W7B6&BÂÖ&²F†R&W7BGW†–FFVâ6òF†W¢òòG&÷÷WBöbF†Rw&–BÂ6÷VçBÂ6ÆVæF"×f–Wr²f–ÇFW'2âæöâÖFW7G'V7F—fP¢òò†æ÷F†–ærFVÆWFVC²&R×&VæFW"&RÖWfÇVFW2g&öÒg&W6‚FF’à¢òò)H)HföÆÆ÷r×WÆör)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòævVÆw27&VG6†VWB6öÇVÖâ‚#bó#BÂró#"’2&VÂFFâV6‚VçG'’—0¢òò·¶öâÂ'’Âæ÷FW×ÒâWfW'—F†–ær&÷WBt„TâFò6†6Rv–â—2FW&—fVBÂæWfW ¢òò7F÷&VBÂ6ò—B6âwBvò7FÆRv†Vâæ÷FR6†ævW2„‡W&ÆW’##bÓrÓ3’à¢f"dôÄÄõuõUôD•2ÒC°¢òòf÷'Fæ–v‡Bw26–ÆVæ6R—2f–æRF‡&VRÖöçF‡2÷WBæBW6VÆW72F‡&VRvVV·0¢òò÷WB(	BF†R6FVæ6RF–v‡FVç22F†RWfVçB&ö6†W2„‡W&ÆW’##bÓrÓ3’à¢f"dôÄÄõuõUôäT%ôD•2ÒrÂdôÄÄõuõUô”ÔÔ”äTåEôD•2Ò3°¢gVæ7F–öâögU7F'D—6ò†ò’·°¢f"bÒ†òbb†òç7F'EöFFRÇÂòç7F'Dö&¢bbòç7F'Dö&¢ç7F'EöFFR’’ÇÂrs°¢bÒ7G&–ær‡b’ç6Æ–6RƒÂ“°¢&WGW&âõåÆG·³G×ÒÕÆG·³'×ÒÕÆG·³'×ÒBòçFW7B‡b’òb¢çVÆÃ°¢×Ð¢gVæ7F–öâögTF—5FôWfVçB†òÂFöF’’·°¢f"—6òÒögU7F'D—6ò†ò“°¢&WGW&â—6òòögTF—56–æ6R‡FöF’Â—6ò’¢çVÆÃ²òòæVvF—fRöæ6R—Bw27@¢×Ð¢òò†÷rÆöærvRÆWB6–ÆVæ6R'Vâ&Vf÷&R—B6÷VçG22GVRà¢gVæ7F–öâföÆÆ÷uWWfW'’†òÂFöF’’·°¢f"BÒögTF—5FôWfVçB†òÂFöF’“°¢–b†BÓÒçVÆÂÇÂBÂ’&WGW&âdôÄÄõuõUôD•3°¢–b†BÃÒ’&WGW&âdôÄÄõuõUô”ÔÔ”äTåEôD•3°¢–b†BÃÒ3R’&WGW&âdôÄÄõuõUôäT%ôD•3°¢&WGW&âdôÄÄõuõUôD•3°¢×Ð¢gVæ7F–öâföÆÆ÷uW2†ò’·°¢f"bÒ†òbbòæföÆÆ÷u÷W2’ÇÂµÓ°¢–b‡G—VöbbÓÓÒw7G&–ærr’·²G'’·²bÒ¥4ôâç'6R‡b“²×Ò6F6‚†R’·²bÒµÓ²×Ò×Ð¢–b‚'&’æ—4'&’‡b’’&WGW&âµÓ°¢&WGW&âbæf–ÇFW"„&ööÆVâ’ç6Æ–6R‚’ç6÷'B†gVæ7F–öâ†"Â#"’·°¢&WGW&â7G&–ær†"æöâÇÂrr’Â7G&–ær†#"æöâÇÂrr’ò¢Ó²òòæWvW7Bf—'7@¢×Ò“°¢×Ð¢gVæ7F–öâÆ7DföÆÆ÷uW†ò’·°¢f"bÒföÆÆ÷uW2†ò“°¢&WGW&âbæÆVæwF‚òe³Ò¢çVÆÃ°¢×Ð¢òòFö÷"F†B—26‡WBæVVG2æò6†6–ærâ&÷F‚6–væÇ2Ç&VG’W†—7B(	B¢òò&V¦V7FVB7FvRÂ÷"v÷&¶fÆ÷u÷7FGW2F†RF†öæö×’f–ÆW2VæFW"$6Æ÷6VB ¢òò‡F†Bw2v†W&R%7öç6÷'6†—öæÇ’"Æ—fW2’(	B6òæòæWr6öÇVÖâà¢òò$Fö÷"6Æ÷6VB"ÖVçBæ÷F†–ærFòç–öæR&VF–ær—B„‡W&ÆW’##bÓrÓ3’Â6ð¢òòF†R&V6öâG&fVÇ2v—F‚F†Rf7C¢F†R&FvR6—2t…’vRw&Ræ÷B6†6–ærà¢gVæ7F–öâFö÷$6Æ÷6VEv‡’†òÂ7FvW2’·°¢–b‚‡7FvW2ÇÂµÒ’æ–æFW„öb‚u&V¦V7FVBr’ÓÒÓ’&WGW&âwF†W’6–Bæòs°¢f"w2Ò7G&–ær‚†òbbòçv÷&¶fÆ÷u÷7FGW2’ÇÂrr’çG&–Ò‚“°¢–b‚w2ÇÂw2ÓÓÒuõöFVÆWFVEõòr’&WGW&ârs°¢f"6‡WBÒ…5DEU5ôu$õUô%•ô´U•·w5ÒÓÓÒt6Æ÷6VBr’ÇÀ¢÷7öç6÷'6†—öæÇ—ÆFV6Æ–çÆæ÷B66WF–æwÆæò÷Væ–æwÇ76VBöâW2ö’çFW7B‡w2“°¢–b‚6‡WB’&WGW&ârs°¢–b‚÷7öç6÷'6†—öæÇ’ö’çFW7B‡w2’’&WGW&âw–B6Æ÷G2öæÇ’s°¢–b‚öFV6Æ–çÇ76VBöâW2ö’çFW7B‡w2’’&WGW&âwF†W’6–Bæòs°¢–b‚öæ÷B66WF–æwÆæò÷Væ–ærö’çFW7B‡w2’’&WGW&âvæ÷BF¶–ær7V¶W'2s°¢&WGW&âw2çFôÆ÷vW$66R‚“°¢×Ð¢gVæ7F–öâFö÷$6Æ÷6VB†òÂ7FvW2’·²&WGW&âFö÷$6Æ÷6VEv‡’†òÂ7FvW2“²×Ð¢f"ôeUôÔôåD…2Ò·²¦çV'“£ÂfV''V'“£"ÂÖ&6ƒ£2Â&–Ã£BÂÖ“£RÂ§VæS£bÂ§VÇ“£rÀ¢VwW7C£‚Â6WFVÖ&W#£’Âö7Fö&W#£Âæ÷fVÖ&W#£ÂFV6VÖ&W#£"À¢¦ã£ÂfV#£"ÂÖ#£2Â#£BÂ§Vã£bÂ§VÃ£rÂVs£‚Â6W£’Â6WC£’Âö7C£Âæ÷c£ÂFV3£"×Ó°¢òò'VæÆW726†R6—26öÖWF†–ær"(	B&VB†W"÷vâv÷&G2&Vf÷&Rævv–ær†W"à¢òò&WGW&ç2·²†öÆC§G'VRÂVçF–ÂÂv‡’×Òv†VâF†Ræ÷FW26’Fòv—Bà¢òò&&RÖöçF‚æÖR—2ÆÖ÷7BÇv—2F†RUdTåBu2õtâDDR&W7FFVB–âF†P¢òòæ÷FW2‚"…6W’Ó’"Â%÷7GöæVBg&öÒ&–Â2FòVr3"ÂU$Â6ÇVp¢òò"âââö76VÖ&Ç’ÖVwW7BÓ##bò"Â%vfR66WFæ6W3¢VrR"’(	B÷"F†RÆ–à¢òòVævÆ—6‚v÷&B&Ö’"‚%F†÷"Ö’æ÷BGFVæB"’âG&VF–ærç’öbF†÷6R0¢òò'v—BVçF–ÂF†Vâ"6–ÆVæ6W2F†RföÆÆ÷r×WçVFvRöâWfVçG2F†BæVV@¢òò6†6–ærÖ÷7BÂv†–6‚—2W†7FÇ’v†B—BF–B„‡W&ÆW’##bÓrÓ3’âÖöçF€¢òòæ÷röæÇ’ÖVç2t•Bv†Vâ‡&6R–âg&öçBöb—B6—26òà¢f"ôeUõt•EôÄTBÒrƒó§VçF–ÇÇF–ÆÇÆ&6²ƒó§FòW2“ö–çÆ6öÖU·6åÓò&6²–çÂp¢²w&V6‚ƒó¦–ær“ò÷WB–çÆ&R–âF÷V6‚–çÆ†V"ƒó¦–ær“òƒó¦&6²“ö–çÂp¢²vFV6—6–öç3ò–çÆFV6–F–ær–çÇ&Wf–Wrƒó¦–ær“ò–çÆææ÷Væ6Rƒó¦GÆÖVçB“÷3ò–çÂp¢²v÷Vç3òƒó¦v–â“ö–çÆæ÷B&Vf÷&WÇ&Wf—6—B–çÆ6—&6ÆR&6²–çÂp¢²vföÆÆ÷rƒó¦–ær“òW–çÆ6†V6²&6²–çÇG'’v–â–çÇ&W7V&Ö—B–çÇ&VÇ’–â’s°¢f"ôeUôÔôåD…ôÅBÒr†¦çV'—ÆfV''V'—ÆÖ&6‡Æ&–ÇÆÖ—Æ§VæWÆ§VÇ—ÆVwW7GÇ6WFVÖ&W'Æö7Fö&W'Âr°¢væ÷fVÖ&W'ÆFV6VÖ&W'Æ¦çÆfV'ÆÖ'Æ'Æ§VçÆ§VÇÆVwÇ6WGÇ6WÆö7GÆæ÷gÆFV2’s°¢gVæ7F–öâföÆÆ÷uW†öÆB‡FW‡B’·°¢f"BÒ7G&–ær‡FW‡BÇÂrr’çFôÆ÷vW$66R‚“°¢–b‚BçG&–Ò‚’’&WGW&âçVÆÃ°¢òòâW‡Æ–6—B'F†W’vÆÂ6öÖR&6²òvRw&Rv—F–ær"7FFRà¢òòU$ÔäTåBFVBVæC¢F†W’wfRFöÆBW2æ÷BFò6†6Râf÷&Ò7V&Ö—76–öà¢òòç7vW&VBöæÇ’–b–÷Rw&R–6¶VB—2æWfW"v÷'F‚çVFvRÂ6òF–ÖRæWfW ¢òò&VÆV6W2F†—2öæRà¢f"æWfW"Òò†öæÇ•Ç2²‡&V6…Ç2¶÷WGÆ6öçF7GÆ&UÇ2¶–åÇ2·F÷V6‚•Ç2¶–gÆ–eÇ2²‡–÷Rã÷&UÇ2²“ò‡6VÆV7FVGÆ6†÷6VçÇ7V66W76gVÂ—ÆFõÇ2¶æ÷EÇ2¶6öçF7GÆæõÇ2¶æVVEÇ2·FõÇ2¶föÆÆ÷r’òçFW7B‡B“°¢òò4ôeBv—C¢F†R&ÆÂ—2v—F‚F†VÒf÷"æ÷rÂ'WBæ÷Bf÷&WfW"(	BgFW"¢òòÖöçF‚—Bw2f—"FòçVFvRv–âà¢f"v—F–ærÒò‡v–ÆÇÇF†W’ãöÆÇÇvRãöÆÇÆ—7Æ&R•Ç2²†&UÇ2¶–åÇ2·F÷V6‡Ç&V6…Ç2¶÷WGÆ6öÖUÇ2¶&6·ÆÆWEÇ2·W5Ç2¶¶æ÷wÆföÆÆ÷uÇ2·WÆ6öææV7GÆ6öææV7F–æwÆ–çG&öGV7Æ¶VWÇ2²‡–÷WÇW2•Ç2²†–åÇ2·F†UÇ2¶Æö÷Ç÷7FVB’’òçFW7B‡B¢ÇÂò†¶VWÇ2²‡–÷WÇW2•Ç2¶–åÇ2·F†UÇ2¶Æö÷ÆöåÇ2¶†öÆGÇv—F–æuÇ2¶öçÆv—F–æwÆ†fUÇ2¶WfW'—F†–æuÇ2²‡F†W—ÇvR•Ç2¶æVVGÆvö–æuÇ2·F‡&÷Vv…Ç2¶Æ–6F–öç2’òçFW7B‡B“°¢òòæÖVBgWGW&RÖöçF‚Â'WBôäÅ’&V†–æB‡&6RF†BÖVç2v—F–ær(	@¢òò&&6²FòW2–â6WFVÖ&W""Â&FV6—6–öç2–âö7Fö&W""Â&æ÷B&Vf÷&RÖ&6‚"à¢f"VçF–ÂÒçVÆÃ°¢f"FöF’Ò‡v–æF÷ræ%FöF”—6òòv–æF÷ræ%FöF”—6ò‚’¢æWrFFR‚’çFô•4õ7G&–ær‚’ç6Æ–6RƒÂ’“°¢òòÆ–æ·26''’ÖöçF‚æÖW2–âF†V—"6ÇVw3²F†W’&RæWfW"&öÖ—6Rà¢f"GrÒBç&WÆ6R‚ö‡GG3ó¥ÂõÂõÅ2²örÂrr¢ç&WÆ6R‚õÅ2µÂâƒó¦6ö×Æ÷&wÆæWGÆ–÷Æ—Æ6ò•Å2¢örÂrr¢ç&WÆ6R‚õµÇ5ÇSÒ²örÂrr“°¢f"&RÒæWr&VtW‡…ôeUõt•EôÄTB²rr²ôeUôÔôåD…ôÅB²rƒò¶×¥Ò’rÂvrr“°¢f"—"Ò'6T–çB‡FöF’ç6Æ–6RƒÂB’Â’ÂÖòÒ'6T–çB‡FöF’ç6Æ–6RƒRÂr’Â“°¢f"†—C°¢v†–ÆR‚††—BÒ&RæW†V2‡Gr’’ÓÒçVÆÂ’·°¢f"âÒôeUôÔôåD…5¶†—E³ÕÓ²–b‚â’6öçF–çVS°¢f"’ÒâãÒÖòò—"¢—"²²òòæW‡Bö67W'&Væ6P¢f"—6òÒ’²rÒr²7G&–ær†â’çE7F'Bƒ"Âsr’²rÓs°¢–b†—6òâFöF’bb‚VçF–ÂÇÂ—6òÂVçF–Â’’VçF–ÂÒ—6ó°¢×Ð¢–b†æWfW"’&WGW&â·²†öÆC¢G'VRÂVçF–Ã¢çVÆÂÂW&ÖæVçC¢G'VRÂv‡“¢wF†W’6öçF7BW2r×Ó°¢–b‡VçF–Â’&WGW&â·²†öÆC¢G'VRÂVçF–Ã¢VçF–ÂÂv‡“¢wF†V—"F–Ö–ærr×Ó°¢–b‡v—F–ær’&WGW&â·²†öÆC¢G'VRÂVçF–Ã¢çVÆÂÂv‡“¢wv—F–æröâF†VÒr×Ó°¢&WGW&âçVÆÃ°¢×Ð¢òòWfVçG2'Vâ'’F†R4ÔR÷WFf—B6†&RföÆÆ÷r×Wâ6†6–ær6–&öæ6P¢òò6†÷VÆFâwBÆVfRf÷W"÷F†W"vV"7VÖÖ—BWfVçG2ævv–ær„‡W&ÆW’##bÓrÓ3’à¢f"ögT'”÷&rÒçVÆÃ°¢gVæ7F–öâögT÷&t¶W’†ò’·°¢f"BÒ÷W&Ä÷&r‚†òbb†òçW&ÂÇÂ†òç7F'Dö&¢bbòç7F'Dö&¢çW&Â’’’ÇÂrr“°¢&WGW&âBòvC¢r²B¢rs°¢×Ð¢gVæ7F–öâö'V–ÆDföÆÆ÷uW÷&t–æFW‚‚’·°¢f"–G‚Ò··×Ó°¢÷4ÆÄ—FV×2‚’æf÷$V6‚†gVæ7F–öâ†—B’·°¢f"²ÒögT÷&t¶W’†—Bç7F'Dö&¢ÇÂ—B“²–b‚²’&WGW&ã°¢f"bÒÆ7DföÆÆ÷uW†—Bç7F'Dö&¢ÇÂ—B“²–b‚bÇÂbæöâ’&WGW&ã°¢–b‚–G…¶µÒÇÂ7G&–ær†bæöâ’â7G&–ær†–G…¶µÒæöâ’’–G…¶µÒÒ·²öã¢bæöâÂæÖS¢—BææÖR×Ó°¢×Ò“°¢ögT'”÷&rÒ–Gƒ°¢&WGW&â–Gƒ°¢×Ð¢òòD„R7FFRÖ6†–æRâöæRöc ¢òò6Æ÷6VBÒFö÷"6‡WBÂæWfW"6†6P¢òò†öÆBÒ†W"æ÷FW26’v—B‡VçF–ÂFFRÂ÷"öâF†VÒ¢òòæöæRÒæ÷F†–ærÆövvVB–W@¢òòö²Ò6†6VB&V6VçFÇ¢òòGVRÒB²F—26–æ6RF†RÆ7B6†6P¢gVæ7F–öâföÆÆ÷uW7FFR†òÂ7FvW2ÂW‡G&æ÷FW2’·°¢f"6‡WEv‡’ÒFö÷$6Æ÷6VEv‡’†òÂ7FvW2“°¢òò&V¦V7F–öâ—2F–ffW&VçBF†–ærg&öÒFö÷"F†Bv2æWfW"÷Vâ(	@¢òò'F†W’6–Bæò"V&ç2F†R&VBF÷C²7öç6÷'6†—ÖöæÇ’÷"æ÷B×F¶–ærÐ¢òò7V¶W'2—27G'V7GW&ÂÂæB7F—2w&W’„‡W&ÆW’##bÓrÓ3’à¢–b‡6‡WEv‡’’&WGW&â·²7FFS¢v6Æ÷6VBrÂ&V¦V7FVC¢‡6‡WEv‡’ÓÓÒwF†W’6–Bæòr’À¢Æ&VÃ¢t6Æ÷6VBÇS#Br²6‡WEv‡’×Ó°¢f"æ÷FW2Ò²†òbbòææ÷FW2’ÇÂrrÂW‡G&æ÷FW2ÇÂrrÒæ¦ö–â‚rr“°¢f"†öÆBÒföÆÆ÷uW†öÆB†æ÷FW2“°¢f"FöF’Ò‡v–æF÷ræ%FöF”—6òòv–æF÷ræ%FöF”—6ò‚’¢æWrFFR‚’çFô•4õ7G&–ær‚’ç6Æ–6RƒÂ’“°¢f"Æ7BÒÆ7DföÆÆ÷uW†ò“°¢òò†÷vWfW"f—&ÒF†Rv—BÂâWfVçBGvòvVV·2÷WB÷fW'&–FW2—C¢–bvRw&P¢òò7F–ÆÂæ÷BöâF†R&öw&ÖÖR'’F†VâÂv—F–ærV–WFÇ’—2æ÷BÆâà¢f"FôWfVçBÒögTF—5FôWfVçB†òÂFöF’“°¢–b††öÆBbbFôWfVçBÒçVÆÂbbFôWfVçBãÒbbFôWfVçBÃÒB’†öÆBÒçVÆÃ°¢òòF†V—"F–Ö–ær&VG2÷W"6Æö6²à¢–b††öÆBbb†öÆBçVçF–Âbb†öÆBçVçF–ÂâFöF’’·°¢&WGW&â·²7FFS¢v†öÆBrÂVçF–Ã¢†öÆBçVçF–ÂÂÆ&VÃ¢uv—F–ærVçF–Âr²ögTæ–6R††öÆBçVçF–Â’×Ó°¢×Ð¢òòW&ÖæVçB†öÆB—2æWfW"&VÆV6VB'’F†R76vRöbF–ÖRà¢–b††öÆBbb†öÆBçW&ÖæVçB’·°¢&WGW&â·²7FFS¢v†öÆBrÂW&ÖæVçC¢G'VRÂÆ&VÃ¢tæò6†6RæVVFVBÇS#BF†W’6öÖR&6²FòW2r×Ó°¢×Ð¢òò6ögBv—BW‡—&W2gFW"ÖöçF‚(	BF†Vâ—Bw2f—"FòçVFvRv–âà¢–b††öÆBbb†öÆBçVçF–Âbb‚Æ7BÇÂögTF—56–æ6R†Æ7BæöâÂFöF’’Â3’’·°¢&WGW&â·²7FFS¢v†öÆBrÂÆ&VÃ¢uv—F–æröâF†VÒr×Ó°¢×Ð¢f"Æ7DöâÒÆ7BbbÆ7Bæöã°¢òòç–öæRVÇ6R6†6–ærF†R6ÖR÷&væ—6W"6÷VçG2à¢f"÷&rÒögT÷&t¶W’†ò’Â÷f–ÒçVÆÃ°¢–b†÷&r’·°¢f"6†&VBÒ…ögT'”÷&rÇÂö'V–ÆDföÆÆ÷uW÷&t–æFW‚‚’•¶÷&uÓ°¢–b‡6†&VBbb6†&VBæöâbb‚Æ7DöâÇÂ7G&–ær‡6†&VBæöâ’â7G&–ær†Æ7Döâ’’’·°¢Æ7DöâÒ6†&VBæöã°¢òò&VÖVÖ&W"t„õ4R6†6RF†—2v2(	B6&Bv—F‚æòÆöröb—G2÷vâ6à¢òòF†Vâ6†÷rF†R&÷r&F†W"F†â&&RÆ&VÂ„‡W&ÆW’##bÓrÓ3’à¢÷f–Ò·²öã¢6†&VBæöâÂæÖS¢6†&VBææÖR×Ó°¢×Ð¢×Ð¢–b‚Æ7Döâ’&WGW&â·²7FFS¢væöæRrÂÆ&VÃ¢tæ÷B6öçF7FVB–WBr×Ó°¢f"F—2ÒögTF—56–æ6R†Æ7DöâÂFöF’“°¢–b†F—2ãÒföÆÆ÷uWWfW'’†òÂFöF’’’·°¢&WGW&â·²7FFS¢vGVRrÂF—3¢F—2Â6–æ6S¢Æ7DöâÂf–¢÷f–À¢Æ&VÃ¢tföÆÆ÷rWæ÷rÇS#Br²F—2²rF—26–æ6Rr²ögTæ–6R†Æ7Döâ’×Ó°¢×Ð¢&WGW&â·²7FFS¢vö²rÂF—3¢F—2Â6–æ6S¢Æ7DöâÂf–¢÷f–À¢Æ&VÃ¢tföÆÆ÷vVBWr²ögTæ–6R†Æ7Döâ’×Ó°¢×Ð¢gVæ7F–öâögTF—56–æ6R†—6òÂFöF’’·°¢G'’·°¢f""ÒæWrFFR…7G&–ær†—6ò’ç6Æ–6RƒÂ’²uC££r“°¢f"#"ÒæWrFFR…7G&–ær‡FöF’’ç6Æ–6RƒÂ’²uC££r“°¢&WGW&âÖF‚æfÆö÷"‚†#"Ò"’òƒcC“°¢×Ò6F6‚†R’·²&WGW&â²×Ð¢×Ð¢gVæ7F–öâögTæ–6R†—6ò’·°¢G'’·°¢&WGW&âæWrFFR…7G&–ær†—6ò’ç6Æ–6RƒÂ’²uC££r¢çFôÆö6ÆTFFU7G&–ær‚vVâÕU2rÂ·²ÖöçFƒ¢w6†÷'BrÂF“¢vçVÖW&–2r×Ò“°¢×Ò6F6‚†R’·²&WGW&â7G&–ær†—6òÇÂrr“²×Ð¢×Ð¢v–æF÷ræ$föÆÆ÷uW7FFRÒföÆÆ÷uW7FFS°¢v–æF÷ræ$föÆÆ÷uW2ÒföÆÆ÷uW3° ¢òò)H)H66†VGVÆ–ær6öæfÆ–7G2)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò5DEU2##bÓrÓ3¢F†RÔåTÂ6öæfÆ–7Eöæ÷FRF‚&VÆ÷r—2Æ—fRæ@¢òò&VæFW'2âF†RWFöÖF–26ÖR×W'6öâö÷fW&Æ–ærÖFFRFWFV7F–öâ—0¢òòw&—GFVâ'WB—2äõBÖF6†–ær–WB(	B6Æ6†W4f÷"‚’&WGW&ç2µÒv–ç7@¢òò&VÂFFWfVâF†÷Vv‚7FæFÆöæR72÷fW"F†R6ÖR&÷w2f–æG2“¢òò—'2Â6òF†R—FVÒ6†R—B&VG2—27F–ÆÂw&öær6öÖWv†W&RâFòæ÷@¢òòG&VBF†R'6Væ6Röb6†—2væò6öæfÆ–7G2rà¢òòÖ÷7BöbF†W6R&RÇ&VG’–×Æ–VB'’FFvR†öÆC¢F†R6ÖRW'6öâ—0¢òòF÷vâf÷"GvòWfVçG2v†÷6RFFW2÷fW&Æâ“’7V6‚—'2W†—7B&–v‡Bæ÷p¢òò…F†÷"—2öâF‡&VR6W&FRF†–æw2öâ2æ÷b’Â6òF†—2—2FWFV7FVB&F†W ¢òòF†âG—VB„‡W&ÆW’##bÓrÓ3’âævVÆ6â7F–ÆÂ&V6÷&B6öæfÆ–7BF†P¢òòFF6âwB6VR(	B&ö&BÖVWF–ærÂ†öÆ–F’(	B–â6öæfÆ–7Eöæ÷FVà¢òð¢òò'V–ÇBôä4RW"&VæFW"–çFòW'6öâÓâ¶WfVçEÒ–æFWƒ²Fö–ær—B—'v—6P¢òòW"6&Bv÷VÆB&Rãsã"à¢f"ö6Æ6„–G‚ÒçVÆÃ°¢òòöæÇ’V÷ÆRv†ò&R7GVÆÇ’4ôÔÔ•EDTB(	Bvö–ærÂ÷"&öö¶VBFò7V²à¢òò÷fW&Æ–ærÄ”4D”ôå2&Ræ÷&ÖÂæBW‡V7FVC¢–÷RÇ’FòÖç¢òòF†–æw2æBÖ÷7BFöâwBÆæBÂ6ò6÷VçF–ær7V&Ö—GFVB7V¶W"26öÖÖ—GFV@¢òòÖFRWfW'’7V&Ö—GFVBWfVçB6Æ6‚v—F‚WfW'’÷F†W"öæR„‡W&ÆW¢òò##bÓrÓ3’â6ÖR'VÆR2÷G&fVÅ&öÆR‚“¢âGFVæFVRÂ÷"F†R7V¶W"öâ¢òò&öö¶VBWfVçBâ7V&Ö—GFVBòföÆÆ÷vVBWòÖVWF–ær†VÆB&RäõB6öÖÖ—FÖVçG2à¢gVæ7F–öâö6Æ6…V÷ÆR†—B’·°¢f"÷WBÒ··×Ó°¢†—BæGFVæFVW2ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†’·°¢f"bÒ$föÆB†’ç7Æ—B‚õÇ2²ò•³Ó²–b†b’÷WE¶eÒÒ°¢×Ò“°¢f"7FvW2Ò—Bç7FvW2ÇÂ†—Bç7F'Dö&¢bb—Bç7F'Dö&¢ç7FvU÷Fw2’ÇÂµÓ°¢–b‡7FvW2æ–æFW„öbbb7FvW2æ–æFW„öb‚t&öö¶VBr’ÓÒÓ’·°¢7G&–ær†—Bç7V¶W"ÇÂrr’ç7Æ—B‚õ²Ã²òe×ÂæBò’æf÷$V6‚†gVæ7F–öâ‡B’·°¢f"bÒ$föÆB‡B’ç7Æ—B‚õÇ2²ò•³Ó²–b†b’÷WE¶eÒÒ°¢×Ò“°¢×Ð¢&WGW&âö&¦V7Bæ¶W—2†÷WB“°¢×Ð¢gVæ7F–öâö6Æ6…&ævR†—B’·°¢òòW6RF†R4ÔR&W6öÇfW"F†R&W7BöbF†Rw&–BW6W2â&VF–ær7F'EöFFRöf`¢òòF†R&V6÷&BF—&V7FÇ’v÷&¶VBf÷"ÖçVÂ&÷w2'WB6–ÆVçFÇ’&WGW&æVBçVÆÀ¢òòf÷"6FÆöröæW2(	BF†V—"FFW2Æ—fRöâF†R6FÆörVçG'’Âæ÷BF†R÷0¢òò&V6÷&B(	B6òæ÷F†–ærWfW"ÖF6†VB„‡W&ÆW’##bÓrÓ3’à¢f"3ÒçVÆÃ°¢G'’·²3ÒWfVçE7F'D—6ò†—B’ÇÂWfVçE7F'D—6ò†—Bç7F'Dö&¢ÇÂ··×Ò“²×Ò6F6‚†R’··×Ð¢–b‚3ÇÂõåÆG·³G×ÒÕÆG·³'×ÒÕÆG·³'×ÒòçFW7B…7G&–ær‡3’’’&WGW&âçVÆÃ°¢3Ò7G&–ær‡3’ç6Æ–6RƒÂ“°¢f"òÒ—Bç7F'Dö&¢ÇÂ—C°¢f"SÒòæVæEöFFRÇÂ—BæVæEöFFS°¢SÒ†SbbõåÆG·³G×ÒÕÆG·³'×ÒÕÆG·³'×ÒòçFW7B…7G&–ær†S’’’ò7G&–ær†S’ç6Æ–6RƒÂ’¢3°¢&WGW&â·3ÂSÂ3ò3¢SÓ°¢×Ð¢gVæ7F–öâö'V–ÆD6Æ6„–æFW‚‚’·°¢f"–G‚Ò··×Ó°¢÷4ÆÄ—FV×2‚’æf÷$V6‚†gVæ7F–öâ†—B’·°¢–b†—Bç7BÇÂ—Bæ†–FFVâ’&WGW&ã°¢òò—FV×26''’çVÖW&–26÷'F¶W’Âæ÷B7F'EöFFR(	BF†R6ÖRF†–æp¢òò÷G&—6ÇW7FW'2‚’&VG2âvö–ærf–F†R&V6÷&Bw27F'EöFFRv÷&¶VBf÷ ¢òòF†R6&B'WBÆVgBF†—2–æFW‚V×G’Â6òæ÷F†–ærWfW"ÖF6†VBà¢f"6BÒçVÆÂÂVBÒçVÆÃ°¢G'’·²6BÒ÷6÷'EFôFFR†—Bç6÷'B“²VBÒ÷6÷'EFôFFR…öVæE6÷'Döb†—B’“²×Ò6F6‚†R’··×Ð¢–b‚6BÇÂ—4æâ‡6B’’&WGW&ã°¢–b‚VBÇÂ—4æâ†VB’’VBÒ6C°¢f"—6òÒgVæ7F–öâ†B’·°¢&WGW&âBævWDgVÆÅ–V"‚’²rÒr²7G&–ær†BævWDÖöçF‚‚’²’çE7F'Bƒ"Âsr’°¢rÒr²7G&–ær†BævWDFFR‚’’çE7F'Bƒ"Âsr“°¢×Ó°¢f"3Ò—6ò‡6B’ÂSÒ—6ò†VB“°¢–b†SÂ3’SÒ3°¢ö6Æ6…V÷ÆR†—B’æf÷$V6‚†gVæ7F–öâ‡v†ò’·°¢†–G…·v†õÒÒ–G…·v†õÒÇÂµÒ’çW6‚‡·²¶W“¢—Bæ¶–æB²s¢r²—Bæ¶W’ÂæÖS¢—BææÖRÂ3¢3ÂS¢S×Ò“°¢×Ò“°¢×Ò“°¢ö6Æ6„–G‚Ò–Gƒ°¢&WGW&â–Gƒ°¢×Ð¢òò··²v†òÂæÖRÂ2×ÕÒ(	BWfW'–öæRF÷V&ÆRÖ&öö¶VBv–ç7BD„•2WfVçBà¢gVæ7F–öâ6Æ6†W4f÷"†—B’·°¢f""Òö6Æ6…&ævR†—B“²–b‚"’&WGW&âµÓ°¢f"–G‚Òö6Æ6„–G‚ÇÂö'V–ÆD6Æ6„–æFW‚‚“°¢f"ÖRÒ—Bæ¶–æB²s¢r²—Bæ¶W’Â÷WBÒµÓ°¢f"×”æÖRÒ$föÆB†—BææÖRÇÂrr“°¢ö6Æ6…V÷ÆR†—B’æf÷$V6‚†gVæ7F–öâ‡v†ò’·°¢†–G…·v†õÒÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†ò’·°¢òòW†6ÇVFR6VÆb'’¶W’äB'’æÖS¢F†R7–çF†WF–2—FVÒ6&B'V–ÆG0¢òòFöW6âwBÇv—2&W&öGV6RF†R–æFW‚w2¶–æC¦¶W’Âv†–6‚—2†÷r$“B ¢òòVæFVBWÆ—7FVB2—G2÷vâ6öæfÆ–7B„‡W&ÆW’##bÓrÓ3’à¢–b†òæ¶W’ÓÓÒÖR’&WGW&ã°¢–b†×”æÖRbb$föÆB†òææÖRÇÂrr’ÓÓÒ×”æÖR’&WGW&ã°¢–b‡%³ÒÃÒòæRbbòç2ÃÒ%³Ò’÷WBçW6‚‡·²v†ó¢v†òÂæÖS¢òææÖRÂ3¢òç2×Ò“°¢×Ò“°¢×Ò“°¢&WGW&â÷WC°¢×Ð¢òòUdU%’6Æ6‚Âf÷"WfW'–öæR†ÖW&vVBf–WrÂ##bÓ‚ÓR’âF†—2W6VBFò6†÷r¢òò7V¶W"öæÇ’F†V—"÷vâF–'’6öÆÆ—6–öç2Âv†–6‚FVfVG2F†Rö–çC¢F†P¢òò6Æ6‚v&æ–ærW†—7G26òvRFöâwB6VæBGvòV÷ÆRFòF†R6ÖRvVV²Âæ@¢òò–÷R6ææ÷B6VRF†B–âÆ—7Bf–ÇFW&VBFò–÷W'6VÆbâF†R6Æ6‚Æ&VÂæÖW0¢òòv†òÂ6òFVÒ×v–FRÆ—7B7F–ÆÂ&VG2VæÖ&–wV÷W6Ç’à¢gVæ7F–öâf—6–&ÆT6Æ6†W2†—B’·°¢f"ÆÂÒ6Æ6†W4f÷"†—B“°¢–b‚ÆÂæÆVæwF‚’&WGW&âµÓ°¢–b…öÖW&vVEFVÕf–Wr‚’’&WGW&âÆÃ°¢f"ÖRÒ$föÆB†vWD6öÆÆ$æÖR‚’ÇÂrr’ç7Æ—B‚õÇ2²ò•³Ó°¢&WGW&âÖRòÆÂæf–ÇFW"†gVæ7F–öâ†2’·²&WGW&â2çv†òÓÓÒÖS²×Ò’¢µÓ°¢×Ð¢gVæ7F–öâ6Æ6„Æ&VÂ†Æ—7B’·°¢–b‚Æ—7BæÆVæwF‚’&WGW&ârs°¢f"v†òÒµÓ°¢Æ—7Bæf÷$V6‚†gVæ7F–öâ†2’·²–b‡v†òæ–æFW„öb†2çv†ò’ÓÓÒÓ’v†òçW6‚†2çv†ò“²×Ò“°¢f"6ÒgVæ7F–öâ†â’·²&WGW&ââæ6†$Bƒ’çFõWW$66R‚’²âç6Æ–6Rƒ“²×Ó°¢f"æÖW2Ò‡v–æF÷ræ%Æä÷&FW"òv–æF÷ræ%Æä÷&FW"‡v†ò’¢v†ò’æÖ†6“°¢&WGW&âæÖW2æ¦ö–â‚rbr’²rÇ6òöâr²W66T‡FÖÂ†Æ—7E³ÒææÖR’°¢†Æ—7BæÆVæwF‚âòr²r²†Æ—7BæÆVæwF‚Ò’²rÖ÷&Rr¢rr“°¢×Ð ¢òò)H)H†÷fW"VV³¢F†R6öçfW'6F–öâ²æ÷FW2Âv—F†÷WB÷Væ–ærF†R6&B)H)H ¢òòöæR6†&VB÷÷fW"Âæ÷BöæRW"6&B‡F†W&R&Rãs’â—B—0¢òòö–çFW"ÖWfVçG3¦æöæRöâW'÷6R(	B–÷RöæÇ’WfW"$TB—BÂ6òF†W&R—2æð¢òòvFò7&÷72æBæòv’FòÆ÷6R—BÖ–BÖÖ÷fRÂv†–6‚—2v†BÖFRF†P¢òò6†÷VÆBÔGFVæBÖVçRg&v–ÆRâ6Æ–6²F†R6&Bf÷"F†RgVÆÂF†–ærà¢f"÷VV´VÂÒçVÆÂÂ÷VVµF–ÖW"ÒçVÆÂÂ÷VV´f÷"ÒçVÆÃ°¢gVæ7F–öâ÷VV´æöFR‚’·°¢–b…÷VV´VÂ’&WGW&â÷VV´VÃ°¢÷VV´VÂÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢÷VV´VÂæ6Æ74æÖRÒv6&B×VV²s°¢÷VV´VÂç6WDGG&–'WFR‚v&–Ö†–FFVârÂwG'VRr“°¢Fö7VÖVçBæ&öG’æVæD6†–ÆB…÷VV´VÂ“°¢&WGW&â÷VV´VÃ°¢×Ð¢gVæ7F–öâ÷VV´†–FR‚’·°¢–b…÷VVµF–ÖW"’·²6ÆV%F–ÖV÷WB…÷VVµF–ÖW"“²÷VVµF–ÖW"ÒçVÆÃ²×Ð¢÷VV´f÷"ÒçVÆÃ°¢–b…÷VV´VÂ’÷VV´VÂæ6Æ74Æ—7Bç&VÖ÷fR‚vöâr“°¢×Ð¢òòföÆBFW‡Bf÷"6ö×&—6öã¢66RÂVæ7GVF–öâæB76–ærFöâwB6÷VçBà¢gVæ7F–öâ÷VV´föÆB‡B’·°¢&WGW&â7G&–ær‡BÓÒçVÆÂòrr¢B’çFôÆ÷vW$66R‚’ç&WÆ6R‚õµæ×£Ó•Ò²örÂrr’çG&–Ò‚“°¢×Ð¢òò6öÖWF†–ær†2Fò†fR„TäTB†W&RâVV²öââWfVçBæö&öG’†0¢òòF÷V6†VB—2æö—6RÂ†÷vWfW"Öç’æ÷FW26—Böâ—B„‡W&ÆW’##bÓrÓ3’à¢f"õTTµô5D•dRÒ²u7V&Ö—GFVBrÂtföÆÆ÷vVBWrÂtÖVWF–ær†VÆBrÂt&öö¶VBrÂtGFVæF–æruÓ°¢gVæ7F–öâ÷VV´†47F—f—G’†6&B’·°¢f""Ò6&BåöÖöFÅ&V2ÇÂ··×Ó°¢f"Fw2Ò†6&BæFF6WBç7FGW5Fw2ÇÂrr’ç7Æ—B‚wÂr’æf–ÇFW"„&ööÆVâ“°¢f÷"‡f"’Ò²’ÂõTTµô5D•dRæÆVæwFƒ²’²²’·°¢–b‡Fw2æ–æFW„öb…õTTµô5D•dU¶•Ò’ÓÒÓ’&WGW&âG'VS°¢×Ð¢–b‚†6&BæFF6WBæGFVæFVTæÖW2ÇÂrr’ç&WÆ6R‚õÇÂörÂrr’çG&–Ò‚’’&WGW&âG'VS°¢–b‚‡"æ÷WG&V6…ö76–væVW2ÇÂµÒ’æÆVæwF‚’&WGW&âG'VS²òòævVÆ6¶VB6öÖVöæRFò&V6‚÷W@¢&WGW&âfÇ6S°¢×Ð¢gVæ7F–öâ÷VV´‡FÖÂ†6&B’·°¢òòvFR¢†2ç—F†–ær7GVÆÇ’†VæVBöâF†—2WfVçCð¢–b‚÷VV´†47F—f—G’†6&B’’&WGW&ârs°¢f"&V2Ò6&BåöÖöFÅ&V2ÇÂ··×Ó°¢f"æ÷FW2Ò7G&–ær‡&V2ææ÷FW2ÇÂrr’çG&–Ò‚“°¢f"6´VÂÒ6&BçVW'•6VÆV7F÷"‚ræ6†BÖ6÷VçE¶FFÖ6†F¶W•Òr“°¢f"6²Ò6´VÂò6´VÂævWDGG&–'WFR‚vFFÖ6†F¶W’r’¢çVÆÃ°¢f"ÖWFÒ†6²bbö6†DÖWF¶6µÒ’ÇÂçVÆÃ°¢òò6ÖRW†6ÇW6–öâ2F†RF‡&VBæBF†R&FvR(	Bâ’VW7F–öâ—2æ÷B¢òòÖW76vRÂ6ò—B×W7Bæ÷B7W&f6R–âF†R†÷fW"&Wf–WrV—F†W"à¢f"×6w2Ò†ÖWFbbÖWFæ×6w2òÖWFæ×6w2æf–ÇFW"†gVæ7F–öâ†ÖÒ’·²&WGW&âv–æF÷ræ$—46µ&÷r†ÖÒæ&öG’“²×Ò’¢µÒ“°¢×6w2ç6÷'B†gVæ7F–öâ†"Â#"’·²&WGW&â†"æBÇÂrr’Â†#"æBÇÂrr’ò¢Ó²×Ò“°¢×6w2Ò×6w2ç6Æ–6RƒÂ2“° ¢òòvFR#¢æB—2F†W&Rç—F†–ærFò4’(	Bæ÷FR÷"ÖW76vSð¢–b‚æ÷FW2bb×6w2æÆVæwF‚’&WGW&ârs° ¢òòFöâwB&–çBF†R6ÖR6VçFVæ6RGv–6Râv†Vâæ÷FRæBÖW76vR6’F†P¢òò6ÖRF†–ærÂ¶VWF†R4ôådU%4D”ôâ(	B—B6'&–W2v†ò6–B—BæBv†VâÀ¢òòv†–6‚F†R&&Ræ÷FRFöW6âwB„‡W&ÆW’##bÓrÓ3’à¢f"dæ÷FRÒ÷VV´föÆB†æ÷FW2“°¢f"æ÷FT6÷fW&VBÒfÇ6S°¢–b†dæ÷FR’·°¢×6w2æf÷$V6‚†gVæ7F–öâ†Ò’·°¢f"fÒÒ÷VV´föÆB†Òæ&öG’“°¢òòF—&V7F–öæÂöâW'÷6S¢F†Ræ÷FR—2&VGVæFçBöæÇ’v†VâÔU54tP¢òòÇ&VG’6öçF–ç2—Bâ–bF†RäõDR—2F†RgVÆÆW"öæRÂ¶VWF†Ræ÷FP¢òòæBG&÷F†RÖW76vR–ç7FVB†&VÆ÷r’(	B÷F†W'v—6RvRvBF‡&÷rv¢òòF†RFWF–ÂæB¶VWF†R6†÷'FW"Æ–æRà¢–b†fÒbbfÒæ–æFW„öb†dæ÷FR’ÓÒÓ’æ÷FT6÷fW&VBÒG'VS°¢×Ò“°¢×Ð¢òòæBG&÷ÖW76vRF†Ræ÷FRÇ&VG’7FFW2fW&&F–Ò‡F†R÷F†W"v’&÷VæB’à¢–b†dæ÷FRbbæ÷FT6÷fW&VB’·°¢×6w2Ò×6w2æf–ÇFW"†gVæ7F–öâ†Ò’·°¢f"fÒÒ÷VV´föÆB†Òæ&öG’“°¢&WGW&â†fÒbbdæ÷FRæ–æFW„öb†fÒ’ÓÒÓ“°¢×Ò“°¢×Ð¢–b‚æ÷FW2bb×6w2æÆVæwF‚’&WGW&ârs° ¢f"‚Òrs°¢–b†×6w2æÆVæwF‚’·°¢‚³ÒsÆF—b6Æ73Ò'VV²×6V2#ãÇ7â6Æ73Ò'VV²Ö‚#ä6öçfW'6F–öãÂ÷7ãâs°¢×6w2æf÷$V6‚†gVæ7F–öâ†Ò’·°¢‚³ÒsÆF—b6Æ73Ò'VV²Ö×6r#ãÇ7â6Æ73Ò'VV²×v†ò#âr²W66T‡FÖÂ…7G&–ær†ÒæWF†÷"ÇÂu6öÖVöæRr’ç7Æ—B‚õÇ2²ò•³Ò’°¢sÂ÷7ããÇ7â6Æ73Ò'VV²×v†Vâ#âr²W66T‡FÖÂ…÷&VÅF–ÖR†ÒæB’’²sÂ÷7ãâr°¢sÆF—b6Æ73Ò'VV²Ö&öG’#âr²W66T‡FÖÂ†Òæ&öG’ÇÂrr’²sÂöF—cãÂöF—câs°¢×Ò“°¢–b†ÖWFbbÖWFæ6÷VçBâ×6w2æÆVæwF‚’·°¢‚³ÒsÆF—b6Æ73Ò'VV²ÖÖ÷&R#â²r²†ÖWFæ6÷VçBÒ×6w2æÆVæwF‚’²rÖ÷&SÂöF—câs°¢×Ð¢‚³ÒsÂöF—câs°¢×Ð¢–b†æ÷FW2bbæ÷FT6÷fW&VB’·°¢‚³ÒsÆF—b6Æ73Ò'VV²×6V2#ãÇ7â6Æ73Ò'VV²Ö‚#äæ÷FW3Â÷7ãâr°¢sÆF—b6Æ73Ò'VV²Öæ÷FW2#âr²W66T‡FÖÂ†æ÷FW2’²sÂöF—cãÂöF—câs°¢×Ð¢–b‚‚’&WGW&ârs°¢‚³ÒsÆF—b6Æ73Ò'VV²Ö7F#ä6Æ–6²F†R6&BFò÷Vâ—CÂöF—câs°¢f"÷²Ò6&BæFF6WBæ6Æ6‚ÇÂrs°¢–b…÷²’‚ÒsÆF—b6Æ73Ò'VV²Ö6Æ6‚#âb3“ƒƒƒ²r²÷²²sÂöF—câr²ƒ°¢f"÷6âÒ7G&–ær‡&V2æ6öæfÆ–7Eöæ÷FRÇÂrr’çG&–Ò‚“°¢–b…÷6â’‚ÒsÆF—b6Æ73Ò'VV²Ö6Æ6‚#âb3“ƒƒƒ²r²W66T‡FÖÂ…÷6â’²sÂöF—câr²ƒ°¢&WGW&âƒ°¢×Ð¢gVæ7F–öâ÷VVµ6†÷r†6&B’·°¢f"‡FÖÂÒ÷VV´‡FÖÂ†6&B“°¢–b‚‡FÖÂ’&WGW&ã°¢f"VÂÒ÷VV´æöFR‚“°¢VÂæ–ææW$…DÔÂÒ‡FÖÃ°¢VÂæ6Æ74Æ—7BæFB‚vöâr“°¢òòÆ6R—B&W6–FRF†R6&BÂfÆ—–ærFòF†RÆVgBò&÷fRv†Vâ—Bv÷VÆ@¢òò÷F†W'v—6R'VâöfbF†Rf–Ww÷'Bà¢f""Ò6&BævWD&÷VæF–æt6Æ–VçE&V7B‚“°¢f"rÒVÂæöfg6WEv–GF‚Â‚ÒVÂæöfg6WD†V–v‡C°¢f"ÆVgBÒ"ç&–v‡B²#°¢–b†ÆVgB²râv–æF÷ræ–ææW%v–GF‚Ò‚’ÆVgBÒÖF‚æÖ‚ƒ‚Â"æÆVgBÒrÒ"“°¢f"F÷Ò"çF÷°¢–b‡F÷²‚âv–æF÷ræ–ææW$†V–v‡BÒ‚’F÷ÒÖF‚æÖ‚ƒ‚Âv–æF÷ræ–ææW$†V–v‡BÒ‚Ò‚“°¢VÂç7G–ÆRæÆVgBÒÖF‚ç&÷VæB†ÆVgB’²w‚s°¢VÂç7G–ÆRçF÷ÒÖF‚ç&÷VæB‡F÷’²w‚s°¢×Ð¢gVæ7F–öâv—&T6&EVV²‚’·°¢–b‚F÷4w&–BÇÂF÷4w&–BæFF6WBçVVµv—&VB’&WGW&ã°¢F÷4w&–BæFF6WBçVVµv—&VBÒss°¢F÷4w&–BæFDWfVçDÆ—7FVæW"‚vÖ÷W6V÷fW"rÂgVæ7F–öâ†R’·°¢òòF†RVV²—2G&–vRFööÃ¢—BW†—7G26òævVÆ6â7vVWF†Rw&–Bæ@¢òò6VRv†–6‚WfVçG26''’6öçfW'6F–öâ÷"æ÷FRv—F†÷WB÷Væ–ærV6€¢òòöæRâf÷"7V¶W"Â†÷fW&–ærF†V—"÷vâ6&G2§W7B÷2F†V—"÷và¢òòæ÷FW2&6²BF†VÒ„‡W&ÆW’##bÓrÓ3’â6†V6¶VB„U$RÂæ÷BBv—&–æp¢òòF–ÖRÂ6ò7v—F6†–ær66÷VçBF¶W2VffV7Bv—F†÷WB&VÆöBà¢–b‚—57W÷'EW'6öâ†vWD6öÆÆ$æÖR‚’ÇÂrr’’&WGW&ã°¢f"6&BÒRçF&vWBæ6Æ÷6W7BòRçF&vWBæ6Æ÷6W7B‚ræ÷2Ö6&Br’¢çVÆÃ°¢–b‚6&BÇÂ6&BÓÓÒ÷VV´f÷"’&WGW&ã°¢÷VV´†–FR‚“°¢÷VV´f÷"Ò6&C°¢òò6†÷'BFVÆ’6ò7vVW–ærF†Rö–çFW"7&÷72F†Rw&–BFöW6âwB7G&ö&Rà¢÷VVµF–ÖW"Ò6WEF–ÖV÷WB†gVæ7F–öâ‚’·²–b…÷VV´f÷"ÓÓÒ6&B’÷VVµ6†÷r†6&B“²×ÒÂ3#“°¢×Ò“°¢F÷4w&–BæFDWfVçDÆ—7FVæW"‚vÖ÷W6V÷WBrÂgVæ7F–öâ†R’·°¢f"FòÒRç&VÆFVEF&vWC°¢–b‡FòbbFòæ6Æ÷6W7BbbFòæ6Æ÷6W7B‚ræ÷2Ö6&Br’ÓÓÒ÷VV´f÷"’&WGW&ã°¢÷VV´†–FR‚“°¢×Ò“°¢v–æF÷ræFDWfVçDÆ—7FVæW"‚w67&öÆÂrÂ÷VV´†–FRÂG'VR“°¢F÷4w&–BæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂ÷VV´†–FR“°¢×Ð ¢gVæ7F–öâFVGWT÷46&G2‚’·°¢–b‚F÷4w&–B’&WGW&â°¢òò&Wf–Wv–ærò&WfVÆ–ær÷76–&ÆRGWÆ–6FW2—2ævVÆw2¦ö"(	Bf÷"WfW'–öæP¢òòVÇ6RGWÆ–6FW27F’6öÆÆ6VBÂæòÖGFW"v†B†6÷fW'27v—F6†–ærv¢òòg&öÒævVÆw2æÖRÖ–B×6W76–öâv—F‚F†R&WfVÂ7F–ÆÂöâ’à¢–b‚‡v–æF÷ræ—4ævVÆW6W"bbv–æF÷ræ—4ævVÆW6W"‚’’’·°¢÷&Wf–WtGWW2ÒfÇ6S°¢Fö7VÖVçBæ&öG’æ6Æ74Æ—7Bç&VÖ÷fR‚w&Wf–WrÖGWW2r“°¢×Ð¢f"w&÷W2Ò··×Ó°¢'&’ç&÷F÷G—Ræf÷$V6‚æ6ÆÂ‚F÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&Br’ÂgVæ7F–öâ†2’·°¢2æFF6WBæGW†–FFVâÒrs°¢2æFF6WBæGW¶VWW"Òrs°¢2æFF6WBæGWÖ–&RÒrs°¢2æFF6WBæGWw&÷WÒrs°¢2æ6Æ74Æ—7Bç&VÖ÷fR‚v—2ÖGWRr“°¢f"²ÒGW¶W”öb†2åöÖöFÅ&V2ÇÂ··×Ò“°¢–b†²’†w&÷W5¶µÒÒw&÷W5¶µÒÇÂµÒ’çW6‚†2“°¢×Ò“°¢f"†–FFVâÒ°¢ö&¦V7Bæ¶W—2†w&÷W2’æf÷$V6‚†gVæ7F–öâ†²’·°¢f"rÒw&÷W5¶µÓ°¢–b†ræÆVæwF‚Â"’&WGW&ã°¢rç6÷'B†gVæ7F–öâ†Â"’·²&WGW&â÷G&6µ66÷&R†"’Ò÷G&6µ66÷&R†“²×Ò“°¢òòÖ&²F†RGWÆ–6FR6&G2†¶VWF†R&–6†W7B’â†–FFVâ'’FVfVÇC²F†P¢òò%&Wf–WrGWÆ–6FW2"FövvÆR&WfVÇ2F†VÒ†Ö&¶VB’6òF†W’6â&RFVÆWFVBà¢òòFrF†R´TUU"FöòÂæB7F×F†Rw&÷W–BöâWfW'’6&B–â—BÂ6ð¢òò%&Wf–WrGWÆ–6FW2"6â6†÷rV6‚GWRæW‡BFòF†RWfVçB—BGWÆ–6FW0¢òò„ævVÆæVVG2Fò6ö×&RF†R—"&Vf÷&RFVÆWF–æröæR’à¢u³ÒæFF6WBæGW¶VWW"Òss²u³ÒæFF6WBæGWw&÷WÒ³°¢f÷"‡f"’Ò²’ÂræÆVæwFƒ²’²²’·²u¶•ÒæFF6WBæGW†–FFVâÒss²u¶•ÒæFF6WBæGWw&÷WÒ³²u¶•Òæ6Æ74Æ—7BæFB‚v—2ÖGWRr“²–b‚÷&Wf–WtGWW2’u¶•Òç7G–ÆRæF—7Æ’ÒvæöæRs²†–FFVâ²³²×Ð¢×Ò“°¢òò)H)H72"(	BF—FÆRd$”D”ôå2F†RW†7B¶W’Ö—76W2)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò6ÖR7F'BDDR²6ÖR4•E’Âv†W&RöæRWfVçBw2F—7F–æ7F—fRv÷&G2&R¢òò7V'6WBöbF†R÷F†W"w2†Rærâ$’–âf–ææ6R7VÖÖ—B6†–6vò"g2%$\+utõ$°¢òò’–âf–ææ6R7VÖÖ—B6†–6vò"Â÷"$v'FæW"(
b"ò$”D2(
b"÷&væ—6W ¢òò&Vf—‚’âwV&FVB6òvVçV–æVÇ’F–ffW&VçB6ÖRÖF’ö6—G’WfVçG0¢òò„4Dòg24”ò7VÖÖ—B’7F’6W&FS¢æVVG26†&VBÂ7V6–f–2F÷–2à¢f"EUôtTäU$”2Ò·²7VÖÖ—C£Â6öæfW&Væ6S£Â6öæc£Âf÷'VÓ£ÂW‡ó£ÂW‡÷6—F–öã£Â6öæw&W73£Â7–×÷6—VÓ£ÂfW7F—fÃ£ÂWfVçC£ÂÖVWF–æs£ÂvVV³£ÂF“£ÂF—3£ÂF†S£Âã£Âöc£Âf÷#£ÂFó£ÂæC£Â–ã£Âöã£ÂC£Â'“£Âv—Fƒ£ÂæçVÃ£ÂVF—F–öã£Â6W&–W3£ÂæF–öæÃ£À¢òò&Vv–öâv÷&G2(	B6ò.(
bT²"ò.(
bWW&÷R"ò.(
bTÔT"&VGV6RFòF†R6ÖR6÷&Rà¢V³£ÂWW&÷S£ÂWW&÷Vã£ÂVÖV£ÂVÖV–£Â3£ÂÖW&–63£ÂÖW&–6£ÂÖVæ£ÂÆFÓ£Â–çFW&æF–öæÃ£ÂvÆö&Ã£Âv÷&ÆGv–FS£×Ó°¢gVæ7F–öâ÷F÷–56–r†ò’·°¢f"6—G•Fö·2Ò··×Ó²GW6—G”öb†ò’ç7Æ—B‚rr’æf÷$V6‚†gVæ7F–öâ‡B’·²–b‡B’6—G•Fö·5·EÒÒ²×Ò“°¢f"6WBÒ··×ÒÂâÒ°¢GWæÖT6÷&R†òææÖRÇÂrr’ç7Æ—B‚rr’æf÷$V6‚†gVæ7F–öâ‡B’·°¢–b‡BbbEUôtTäU$”5·EÒbb6—G•Fö·5·EÒbb6WE·EÒ’·²6WE·EÒÒ²â²³²×Ð¢×Ò“°¢&WGW&â·²6WC¢6WBÂ6—¦S¢â×Ó°¢×Ð¢gVæ7F–öâ÷F÷–5&VÆFVB†Â"’·°¢–b†ç6—¦RÂ"ÇÂ"ç6—¦RÂ"’&WGW&âfÇ6S²òòæVVB7V6–f–26†&VBF÷–0¢f"6ÒÒç6—¦RÃÒ"ç6—¦Rò¢"ÂÆrÒç6—¦RÃÒ"ç6—¦Rò"¢°¢f÷"‡f"B–â6Òç6WB’·²–b‚Ærç6WE·EÒ’&WGW&âfÇ6S²×Ð¢&WGW&âG'VS²òò6ÖÆÆW"F÷–2gVÆÇ’–ç6–FRÆ&vW ¢×Ð¢òò)H)HF†RWfVçBÆ–æ²FV6–FW2v†òw27GVÆÇ’'Vææ–ærâWfVçB)H)H)H)H)H)H)H)H)H)H ¢òò76W2"æB2—"WfVçG2öâD•DÄR4„RÂv†–6‚—2W†7FÇ’v†W&R¢òòwVW72vöW2w&öærâF†RÆ–æ²6WGFÆW2—C¢Gvò6–Ö–Æ"ÖÆöö¶–ærWfVçG2öà¢òòF–ffW&VçB6ö×æ–W2rFöÖ–ç2&RF–ffW&VçBWfVçG2„‡W&ÆW’##bÓrÓ#’’à¢òòÖ—76–ærÆ–æ²öâV—F†W"6–FRFVÆÇ2W2æ÷F†–ærÂ6òF†RF—FÆR'VÆW2F†Và¢òò7FæBöâF†V—"÷vâÂVæ6†ævVBà¢gVæ7F–öâöGWFöÒ†ò’·²&WGW&â÷W&Ä÷&r‚†òbbòçW&Â’ÇÂrr“²×Ð¢gVæ7F–öâöFö×46öæfÆ–7B†Â"’·²&WGW&âbb"bbÓÒ#²×Ð¢gVæ7F–öâöFö×4w&VR†Â"’·²&WGW&âbb"bbÓÓÒ#²×Ð¢f"F4w&÷W2Ò··×Ó°¢'&’ç&÷F÷G—Ræf÷$V6‚æ6ÆÂ‚F÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&Br’ÂgVæ7F–öâ†2’·°¢–b†2æFF6WBæGW†–FFVâÓÓÒsr’&WGW&ã²òòÇ&VG’†–FFVâ'’72¢f"6÷'F²Ò2æFF6WBç6÷'BÇÂrs°¢–b‚6÷'F²ÇÂ6÷'F²ÓÓÒs“““““““’r’&WGW&ã²òòVæFFVBÓâ6âwBFFRÖÖF6€¢f"6—G’ÒGW6—G”öb†2åöÖöFÅ&V2ÇÂ··×Ò“°¢–b‚6—G’’&WGW&ã°¢f"¶W’Ò6÷'F²²wÂr²6—G“°¢†F4w&÷W5¶¶W•ÒÒF4w&÷W5¶¶W•ÒÇÂµÒ’çW6‚†2“°¢×Ò“°¢ö&¦V7Bæ¶W—2†F4w&÷W2’æf÷$V6‚†gVæ7F–öâ†¶W’’·°¢f"rÒF4w&÷W5¶¶W•Ó°¢–b†ræÆVæwF‚Â"’&WGW&ã°¢rç6÷'B†gVæ7F–öâ†Â"’·²&WGW&â÷G&6µ66÷&R†"’Ò÷G&6µ66÷&R†“²×Ò“°¢f"¶VWW"Òu³ÒÂ6–t²Ò÷F÷–56–r†¶VWW"åöÖöFÅ&V2ÇÂ··×Ò’ÂÖW&vVBÒ°¢f"FöÔ²ÒöGWFöÒ†¶VWW"åöÖöFÅ&V2ÇÂ··×Ò“°¢f÷"‡f"’Ò²’ÂræÆVæwFƒ²’²²’·°¢–b†u¶•ÒæFF6WBæGW†–FFVâÓÓÒsr’6öçF–çVS°¢òòF–ffW&VçB÷WFf—BÓâF–ffW&VçBWfVçBÂ†÷vWfW"Æ–¶RF†RF—FÆW2&VBà¢–b…öFö×46öæfÆ–7B†FöÔ²ÂöGWFöÒ†u¶•ÒåöÖöFÅ&V2ÇÂ··×Ò’’’6öçF–çVS°¢–b…÷F÷–5&VÆFVB‡6–t²Â÷F÷–56–r†u¶•ÒåöÖöFÅ&V2ÇÂ··×Ò’’’·°¢u¶•ÒæFF6WBæGW†–FFVâÒss²u¶•ÒæFF6WBæGWw&÷WÒ¶W“²u¶•Òæ6Æ74Æ—7BæFB‚v—2ÖGWRr“²–b‚÷&Wf–WtGWW2’u¶•Òç7G–ÆRæF—7Æ’ÒvæöæRs²†–FFVâ²³²ÖW&vVB²³°¢¶VWW"æFF6WBæGW¶VWW"Òss²¶VWW"æFF6WBæGWw&÷WÒ¶W“°¢×Ð¢×Ð¢òò„GWÆ–6FW2Ö&¶VB&÷fS²†–FFVâVæÆW72%&Wf–WrGWÆ–6FW2"—2öââ¢×Ò“° ¢òò)H)H722(	BÄôõ4R'÷76–&ÆRGWÆ–6FR"72‡&Wf–WröæÇ’’)H)H)H)H)H)H)H)H ¢òò76W2æB"¶W’öâæÖRÖ6÷&R¶6—G’·–V"ò6ÖRÖFFR¶6—G’·F÷–2Â6ò¢òòG&–Æ–ærVÆ–f–W"FVfVG2F†VÓ¢%6–&÷2"æB%6–&÷2##bÖ–Ö’"‡6ÖP¢òòFFW2Â6ÖR6—G’’æWfW"ÖF6†VBâF†—2726F6†W2F†B6†R(	BöæP¢òòF—FÆRw2F—7F–æ7F—fRv÷&G2&V–ær5T%4UBöbF†R÷F†W"w2ÂöâF†R6ÖP¢òòFFR÷"–âF†R6ÖR6—G’à¢òð¢òò7'V6–ÆÇ’—BöæÇ’dÄu2â—BæWfW"6WG2GW†–FFVâæBæWfW"†–FW26&BÀ¢òò&V6W6RBF†—2Æö÷6VæW72—BÇ6ò—'2vVçV–æVÇ’F–ffW&VçBWfVçG0¢òò‚$”D24”ò7VÖÖ—BT²"g2$”D2’bFF7VÖÖ—BT²"’âWFòÖ†–F–ærF†÷6P¢òòv÷VÆBÆ÷6R&VÂWfVçG3²‡VÖâFV6–FW2–âF†R&Wf–Wrf–Wr–ç7FVBà¢f"ôEUõ5DõÒ·²F†S£Â£Âã£ÂæC£Âöc£Âf÷#£ÂFó£Â–ã£Âöã£ÂC£Â'“£Âv—Fƒ£À¢7VÖÖ—C£Â7VÖÖ—G3£Â6öæfW&Væ6S£Â6öæfW&Væ6W3£ÂW‡ó£Âf÷'VÓ£ÂWfVçC£ÂWfVçG3£À¢æçVÃ£ÂVF—F–öã£Âv÷&ÆC£ÂvÆö&Ã£Â–çFW&æF–öæÃ£×Ó°¢gVæ7F–öâöGWFö·2†æÖR’·°¢f"BÒ$föÆB…7G&–ær†æÖRÇÂrr’’ç&WÆ6R‚õÅÆ##ÆEÆEÅÆ"örÂrr’ç&WÆ6R‚õµæ×£Ó•Ò²örÂrr“°¢f"÷WBÒ··×ÒÂâÒ°¢Bç7Æ—B‚rr’æf÷$V6‚†gVæ7F–öâ‡r’·²–b‡ræÆVæwF‚âbbôEUõ5Dõ·uÒbb÷WE·uÒ’·²÷WE·uÒÒ²â²³²×Ò×Ò“°¢&WGW&â·²6WC¢÷WBÂã¢â×Ó°¢×Ð¢f"öÖ–&RÒ°¢f"öÆ—fRÒ'&’ç&÷F÷G—Ræf–ÇFW"æ6ÆÂ‚F÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&Br’ÂgVæ7F–öâ†2’·°¢&WGW&â2æFF6WBæGW†–FFVâÓÒss²òòÇ&VG’†æFÆVB'’72ó ¢×Ò“°¢f÷"‡f"’Ò²’ÂöÆ—fRæÆVæwFƒ²’²²’·°¢f÷"‡f"¢Ò’²²¢ÂöÆ—fRæÆVæwFƒ²¢²²’·°¢f"ÒöÆ—fU·•ÒÂ"ÒöÆ—fU·¥Ó°¢f"&ÒåöÖöFÅ&V2ÇÂ··×ÒÂ&"Ò"åöÖöFÅ&V2ÇÂ··×Ó°¢f"FÒöGWFö·2‡&ææÖR’ÂF"ÒöGWFö·2‡&"ææÖR“°¢–b‚FæâÇÂF"æâ’6öçF–çVS°¢f"FöÔÒöGWFöÒ‡&’ÂFöÔ"ÒöGWFöÒ‡&"“°¢òòF–ffW&VçB6ö×æ–W2r6—FW2Óâæ÷B—"âF†—2—2v†B7F÷2F†P¢òòÆö÷6R72g&öÒævv–ær&÷WBWfVçG2F†BÖW&VÇ’6÷VæBÆ–¶Rà¢–b…öFö×46öæfÆ–7B†FöÔÂFöÔ"’’6öçF–çVS°¢f"6†&VBÒÂ¶³°¢f÷"†¶²–âFç6WB’·²–b‡F"ç6WE¶¶µÒ’6†&VB²³²×Ð¢f"6ÖTFFRÒæFF6WBç6÷'BbbæFF6WBç6÷'BÓÒs“““““““’rbbæFF6WBç6÷'BÓÓÒ"æFF6WBç6÷'C°¢f"6ÒGW6—G”öb‡&’Â6"ÒGW6—G”öb‡&"“°¢f"6ÖT6—G’Ò6bb6ÓÓÒ6#°¢f"7V'6WBÒ‡6†&VBÓÓÒÖF‚æÖ–â‡FæâÂF"æâ’“°¢òòæ÷&ÖÆÇ’gVÆÂ7V'6WB—2&WV—&VBâ'WBv†Vâ&÷F‚WfVçG26—BöâF†P¢òò4ÔR6ö×ç’w2FöÖ–âöâF†R6ÖRFFRÂöæRF—7F–æ7F—fR6†&VBv÷&@¢òò—2Væ÷Vv‚Fò&Rv÷'F‚Æöö²(	BF†Bw2F†R$‡VÖå‚×7FW&FÒ"g0¢òò$‡VÖå‚WW&÷R"6†RÂv†–6‚æò7V'6WB'VÆR6â6VRâfÆrÖöæÇ’Â0¢òòWfW#¢6–&Æ–æw26–ævÆR†÷7B'Vç26–FR'’6–FR„4Dòv÷fW&æÖVçBg0¢òò4DòFVfVç6R’ÆæB†W&RFöòÂæB‡VÖâFV6–FW2à¢–b‚7V'6WBbb…öFö×4w&VR†FöÔÂFöÔ"’bb6ÖTFFRbb6†&VBãÒ’’6öçF–çVS°¢–b‚6ÖTFFRbb6ÖT6—G’’6öçF–çVS°¢f"Ö²ÒvÖ–&S¢r²´æFF6WBç6÷'BÂ6Âö&¦V7Bæ¶W—2‡Fç6WB’ç6÷'B‚’æ¦ö–â‚rÒr•Òæ¦ö–â‚wÂr“°¢´Â%Òæf÷$V6‚†gVæ7F–öâ†VÂ’·°¢–b†VÂæFF6WBæGWÖ–&RÓÒsr’·²VÂæFF6WBæGWÖ–&RÒss²öÖ–&R²³²×Ð¢–b‚VÂæFF6WBæGWw&÷W’VÂæFF6WBæGWw&÷WÒÖ³°¢×Ò“°¢×Ð¢×Ð ¢òòG&—fRF†R%&Wf–WrGWÆ–6FW2"FövvÆR–âF†R&W7VÇG2†VFW"à¢f"÷&Wd'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2ÖGWR×&Wf–Wrr“°¢–b…÷&Wd'Fâ’·°¢–b‚÷&Wd'FâæFF6WBçv—&VB’·°¢÷&Wd'FâæFF6WBçv—&VBÒss°¢÷&Wd'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢÷&Wf–WtGWW2Ò÷&Wf–WtGWW3°¢Fö7VÖVçBæ&öG’æ6Æ74Æ—7BçFövvÆR‚w&Wf–WrÖGWW2rÂ÷&Wf–WtGWW2“°¢FVGWT÷46&G2‚“²&Vw&÷W÷4'”ÖöçF‚‚“²Ç”f–ÇFW'2‚“°¢–b…÷&Wf–WtGWW2’v–æF÷rç67&öÆÅFò‡·²F÷¢Â&V†f–÷#¢w6Öö÷F‚r×Ò“°¢×Ò“°¢×Ð¢òòævVÆÖöæÇ“¢öæÇ’6†R6â&Wf–WröFVÆWFRGWÆ–6FW2Â6òöæÇ’6†R6VW0¢òòF†RFövvÆRâWfW'–öæRVÇ6R§W7BvWG2F†R6ÆVâÂFVGWVBw&–Bà¢f"÷&WeF÷FÂÒ†–FFVâ²öÖ–&S°¢÷&Wd'Fâæ†–FFVâÒ…÷&WeF÷FÂÓÓÒ’ÇÂ‡v–æF÷ræ—4ævVÆW6W"bbv–æF÷ræ—4ævVÆW6W"‚’“°¢÷&Wd'FâçFW‡D6öçFVçBÒ÷&Wf–WtGWW0¢òuÅÇS#sRFöæRÅÇS#r†–FRGWÆ–6FW2v–âp¢¢‚u&Wf–Wrr²÷&WeF÷FÂ²r÷76–&ÆRGWÆ–6FRr²…÷&WeF÷FÂÓÓÒòrr¢w2r’“°¢òòçVFvRWfW'’2F—26òF†R–ÆRFöW6âwBV–WFÇ’w&÷s¢–b—Bw2&VVâF†@¢òòÆöær6–æ6RGWÆ–6FW2vW&RÆ7B&Wf–WvVBÂF†R'WGFöâvöW2&VBà¢f"öGW6VVä¶W’Òv"æGW6VVââr²†vWD6öÆÆ$æÖR‚’ÇÂrr’çFôÆ÷vW$66R‚“°¢f"öÆ7E6VVâÒ°¢G'’·²öÆ7E6VVâÒ'6T–çB†Æö6Å7F÷&vRævWD—FVÒ…öGW6VVä¶W’’ÇÂsrÂ’ÇÂ²×Ò6F6‚†R’··×Ð¢f"÷7FÆRÒ„FFRææ÷r‚’ÒöÆ7E6VVâ’â2¢ƒcC°¢÷&Wd'Fâæ6Æ74Æ—7BçFövvÆR‚vGVRrÂ÷7FÆRbb÷&Wf–WtGWW2bb÷&WeF÷FÂâ“°¢–b…÷&Wf–WtGWW2’·²G'’·²Æö6Å7F÷&vRç6WD—FVÒ…öGW6VVä¶W’Â7G&–ær„FFRææ÷r‚’’“²×Ò6F6‚†R’··×Ò×Ð¢×Ð¢&WGW&â†–FFVã°¢×Ð ¢gVæ7F–öâ&VæFW$÷2†VÖ–Â’·°¢òò¶VWF†R&VFW"w2Æ6R7&÷72&R×&VæFW"âÖçVÂ6fRäBF†P¢òò&VÇF–ÖR÷7Fw&W5ö6†ævW2V6†ò&÷F‚6ÆÂ&VæFW$÷2‚“²v—F†÷WBF†—2F†P¢òòw&–B—2v—VBæBF†RvR6æ2&6²FòF†RF÷Â6ò–÷R&Æ÷6R"F†P¢òòWfVçB–÷RvW&R§W7BVF—F–ærâ6GW&RF†R67&öÆÂ÷6—F–öâ²v†–6‚6&Bw0¢òòVF—F÷"—2÷VâÂF†Vâ&W7F÷&R&÷F‚öæ6RF†Rg&W6‚w&–B—2'V–ÇBà¢f"÷&We67&öÆÅ’Òv–æF÷rç67&öÆÅ’ÇÂv–æF÷rçvU”öfg6WBÇÂ°¢òò6''’ç’÷VâFööÆ&"æVÂ„FBf÷&Òòf–æBWfVçG2ò6ÆVæF"7–æ2ð¢òò7&VG6†VWB’7&÷72F†R&V'V–ÆB(	B&RÖ–ç6W'F–ærF†R4ÔRæöFR¶VW2—G0¢òòÆ—7FVæW'2æBç’†Æb×G—VB–çWBâv—F†÷WBF†—2ÂF†R–æ—F–ÂFF¢òòÆöB†÷"FVÖÖFRw2VF—B’6–ÆVçFÇ’v—VBâ÷VâæVÂà¢f"÷æVÂÒF÷4w&–BçVW'•6VÆV7F÷"‚s§66÷RâæFBÖWfVçBÖ6&Br“°¢f"ö÷Vä¶W’ÒçVÆÃ°¢f"ö÷VäVBÒF÷4w&–BçVW'•6VÆV7F÷"‚ræ÷2Ö6&BâFWF–Ç2æ÷2ÖVF—E¶÷VåÒr“°¢–b…ö÷VäVB’·°¢f"öö2Òö÷VäVBæ6Æ÷6W7B‚ræ÷2Ö6&Br“°¢–b…öö2’ö÷Vä¶W’Òöö2æFF6WBæÖçVÄ–@¢ò‚vÒr²öö2æFF6WBæÖçVÄ–B¢¢…öö2æFF6WBæWfVçDçVÒò‚vRr²öö2æFF6WBæWfVçDçVÒ’¢çVÆÂ“°¢×Ð¢òòöæÇ’–çBF†R$ÆöF–æ~(
b"Æ6V†öÆFW"öâF†Rf—'7B&VæFW"âöâ¢òò&R×&VæFW"ÂÆVfRF†R7W'&VçB6&G2–âÆ6R†æòfÆ6‚’VçF–Âg&W6€¢òòFF'&—fW2æBvR7vF†VÒ÷WB&VÆ÷rà¢–b‚F÷4w&–BçVW'•6VÆV7F÷"‚ræ÷2Ö6&Br’’·°¢F÷4w&–Bæ–ææW$…DÔÂÒsÇ7G–ÆSÒ&w&–BÖ6öÇVÖã£òÓ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ2“¶föçB×6—¦S£ã—&VÓ²#äÆöF–ærWfVçG>(
cÂ÷âs°¢×Ð¢&WGW&â&öÖ—6RæÆÂ…°¢fWF6„WfVçG4§6öâ‚’À¢6"æg&öÒ‚vWfVçE÷7FFRr’ç6VÆV7B‚r¢r’À¢6"æg&öÒ‚vÖçVÅöWfVçG2r’ç6VÆV7B‚r¢r’æ÷&FW"‚v7&VFVEöBrÂ·²66VæF–æs¢fÇ6R×Ò¢Ò’çF†Vâ†gVæ7F–öâ‡&W7VÇG2’·°¢f"FFÒ&W7VÇG5³Ó°¢f"7FFU&÷w2Ò‡&W7VÇG5³Òbb&W7VÇG5³ÒæFF’ÇÂµÓ°¢f"ÖçVÅ&÷w2Ò‡&W7VÇG5³%Òbb&W7VÇG5³%ÒæFF’ÇÂµÓ°¢òò†VÇF‡’6FÆörÆöC¢6æ6VÂç’VæF–ærf–ÇW&R×&WG'’²&W6WB&6¶öfbà¢6ÆV%F–ÖV÷WB…ö÷5&WG'•F–ÖW"“°¢ö÷5&WG'”FVÆ’ÒS°¢òò7W&6RW'&÷&–ærv†–ÆRWfVçG2æ§6öâ7V66VVG2Ò6&G26–ÆVçFÇ’Æ÷6–æp¢òòÆÂF†V—"G&6¶–ærâ&ææW"²WFò×&WG'’–ç7FVBöb6–ÆVæ6Rà¢6†÷u6$FVw&FVB‚‡&W7VÇG5³Òbb&W7VÇG5³ÒæW'&÷"’ÇÂ‡&W7VÇG5³%Òbb&W7VÇG5³%ÒæW'&÷"’ÂVÖ–Â“°¢òò6ögBÖFVÆWFVB6FÆörWfVçG26''’uõöFVÆWFVEõòr6VçF–æVÂöâF†V— ¢òòWfVçE÷7FFR&÷râG&÷F†VÒUdU%•t„U$R(	Bw&–BÂ7FG2Â6ÆVæF"ÂVWVRÀ¢òòÆææW"(	B'’W†6ÇVF–ær&÷F‚F†R6FÆörWfVçBäB—G27FFR&÷rÂ6ò¢òòFVÆWFRG'VÇ’&VÖ÷fW2—Bg&öÒF†R—VÆ–æR†æ÷B§W7B†–FW2F†R6&B’à¢f"öFVÆWFVDçV×2Ò··×Ó°¢7FFU&÷w2æf÷$V6‚†gVæ7F–öâ‡"’·²–b‡"ç7FGW2ÓÓÒuõöFVÆWFVEõòr’öFVÆWFVDçV×5·"æWfVçEöçVÕÒÒG'VS²×Ò“°¢7FFU&÷w2Ò7FFU&÷w2æf–ÇFW"†gVæ7F–öâ‡"’·²&WGW&â"ç7FGW2ÓÒuõöFVÆWFVEõòs²×Ò“°¢f"7FFTÖÒ··×Ó°¢7FFU&÷w2æf÷$V6‚†gVæ7F–öâ‡"’·²7FFTÖ·"æWfVçEöçVÕÒÒ#²×Ò“° ¢òò–æ6ÇVFR&6†—fVB‡7B’6FÆörWfVçG2FöòÂ6òF†W’7F’&V6†&ÆR–à¢òòF†R6öÆÆ6–&ÆR$&6†—fR+r7BWfVçG2"w&÷Wâ7FG2ò6ÆVæF"ð¢òòVWVRòÆææW"¶VWW6–ærWg6†æöâÖ&6†—fVB’6ò7BWfVçG2Föâw@¢òò–æfÆFR6÷VçG2÷"7W&f6R2fÇ6R66†VGVÆ–ær6öæfÆ–7G2à¢f"ÆÄWg2Ò†FFæWfVçG2ÇÂµÒ’æf–ÇFW"†gVæ7F–öâ†R’·²&WGW&âöFVÆWFVDçV×5¶RæçVÕÓ²×Ò“°¢f"Wg2ÒÆÄWg2æf–ÇFW"†gVæ7F–öâ†R’·²&WGW&âRç7FGW2ÓÒv&6†—fVBs²×Ò“°¢òò6FÆörWfVçG2&Ræ÷rgVÆÇ’VF—F&ÆS¢WfVçE÷7FFR6â÷fW'&–FRF†P¢òò–FVçF—G’f–VÆG2†æÖRòFFU÷7G"ò7F'EöFFRòVæEöFFRòÆö6F–öâ’à¢òòÇ’F†R÷fW'&–FR–âÆ6R$Tdõ$Rç—F†–ær&VæFW'2Â6òF†RVF—FVBfÇVP¢òòv–ç2÷fW"F†R6FÆörfÇVRWfW'—v†W&RF÷vç7G&VÒ(	Bw&–B6&BÂFWF–Ç2À¢òò6ÆVæF"ÂÖÂ6V&6‚²7VvvW7F–öç2ÆÂ&VBF†W6RÖW&vVBWfVçG2â¢òòæòÖ÷VçF–ÂF†R##bÓrÓEöWfVçE÷7FFUö–FVçF—G’Ö–w&F–öâFG2F†P¢òò6öÇVÖç2‡F†Rf–VÆG2§W7B6öÖR&6²VæFVf–æVB’à¢ÆÄWg2æf÷$V6‚†gVæ7F–öâ†R’·°¢f"7BÒ7FFTÖ¶RæçVÕÓ²–b‚7B’&WGW&ã°¢–b‡7BææÖRÒçVÆÂbb7G&–ær‡7BææÖR’çG&–Ò‚’ÓÒrr’RææÖRÒ7BææÖS°¢òò6ÆV"F†R'6VB6—G’ö6÷VçG'’6ò6†÷'DÆö6F–öâ‚’6†÷w2F†RVF—FV@¢òòÆö6F–öâFW‡B†—B&VfW'26—G’¶6÷VçG'’÷fW"F†R&rÆö6F–öâ’à¢–b‡7BæÆö6F–öâÒçVÆÂbb7G&–ær‡7BæÆö6F–öâ’çG&–Ò‚’ÓÒrr’·²RæÆö6F–öâÒ7BæÆö6F–öã²Ræ6—G’Òrs²Ræ6÷VçG'’Òrs²×Ð¢–b‡7BæFFU÷7G"ÒçVÆÂbb7G&–ær‡7BæFFU÷7G"’çG&–Ò‚’ÓÒrr’RæFFU÷7G"Ò7BæFFU÷7G#°¢–b‡7Bç7F'EöFFR’Rç7F'EöFFRÒ7Bç7F'EöFFS°¢–b‡7BæVæEöFFR’RæVæEöFFRÒ7BæVæEöFFS°¢×Ò“°¢òòG&–Æ–ær×–V"7G&—f÷"F—7Æ’(	BF†R–V"—2&VGVæFçBv—F‚F†RFFRà¢ÆÄWg2æf÷$V6‚†gVæ7F–öâ†R’·²–b†RbbRææÖR’RææÖRÒ7G&—G&–Æ–æu–V"†RææÖR“²×Ò“°¢ÖçVÅ&÷w2æf÷$V6‚†gVæ7F–öâ†Ò’·²–b†ÒbbÒææÖR’ÒææÖRÒ7G&—G&–Æ–æu–V"†ÒææÖR“²×Ò“°¢F÷4w&–Bæ–ææW$…DÔÂÒrs°¢ÆÄWg2æf÷$V6‚†gVæ7F–öâ†Wb’·°¢f"6&BÒ'V–ÆD÷46&B†WbÂ7FFTÖ¶WbæçVÕÒÇÂ··×ÒÂVÖ–Â“°¢F÷4w&–BæVæD6†–ÆB†6&B“°¢v—&T÷46&B†6&BÂVÖ–Â“°¢×Ò“°¢ÖçVÅ&÷w2æf÷$V6‚†gVæ7F–öâ†ÖWb’·°¢f"6&BÒ'V–ÆDÖçVÄ6&B†ÖWbÂVÖ–Â“°¢F÷4w&–BæVæD6†–ÆB†6&B“°¢v—&TÖçVÄ6&B†6&BÂVÖ–Â“°¢×Ò“°¢WFFT÷46÷VçB‚“°¢&V'V–ÆE7V¶W$f–ÇFW"‡7FFU&÷w2ÂÖçVÅ&÷w2“°¢FVGWT÷46&G2‚“²òò6öÆÆ6R67&VBGWÆ–6FR6&G2&Vf÷&RÆ–÷W@¢&Vw&÷W÷4'”ÖöçF‚‚“°¢òò&VæFW%7FG2eDU"F†RFVGWR73¢F†R$×’–çFW&W7G2"6÷VçB—2FW&—fV@¢òòg&öÒF†R&VæFW&VB6&G2‡6ò—B6â6†&R÷W'6öå&VÆWfçBv—F‚F†P¢òòf–ÇFW"æBæWfW"G&–gBg&öÒ—B’ÂæB&Vf÷&RFVGWT÷46&G2'Vç2F†÷6P¢òò6&G27F–ÆÂ–æ6ÇVFRGWÆ–6FW2F†Rw&–B—2&÷WBFò†–FRâ6÷VçF–æp¢òòV&Ç’—2W†7FÇ’v†BÖ¶W26†—6’c"æB—G2Æ—7B6†÷rcà¢&VæFW%7FG2†Wg2Â7FFU&÷w2ÂÖçVÅ&÷w2“°¢Ç”f–ÇFW'2‚“°¢ÆöD6†D6÷VçG2‚“²òòf–ÆÂF†RÆ—GFÆR/	ù*Ââ"6†B&FvW2öâF†R6&G0¢òò&V'V–ÆBF†RFVGW–æFW‚g&öÒF†—2g&W6‚fWF6‚(	B&VÇF–ÖP¢òòWfVçG2g&öÒ÷F†W"F'2ò6W76–öç2ÆæB†W&RÂ6òvRvçBWfW'¢òò&R×&VæFW"Fò&Vg&W6‚ö¶æ÷väæÖW2Föòà¢ö¶æ÷väæÖU6÷W&6RÒ··×Ó²ö¶æ÷vä¶W—2Ò··×Ó°¢†FFæWfVçG2ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†R’·²f"âÒ†RææÖRÇÂrr’çFôÆ÷vW$66R‚’çG&–Ò‚“²–b†â’ö¶æ÷väæÖU6÷W&6U¶åÒÒv6FÆörs²f"²ÒGW¶W”öb†R“²–b†²bbö¶æ÷vä¶W—5¶µÒ’ö¶æ÷vä¶W—5¶µÒÒv6FÆörs²×Ò“°¢ÖçVÅ&÷w2æf÷$V6‚†gVæ7F–öâ†Ò’·²f"âÒ†ÒææÖRÇÂrr’çFôÆ÷vW$66R‚’çG&–Ò‚“²–b†â’ö¶æ÷väæÖU6÷W&6U¶åÒÒvÖçVÃ¢r²Òæ–C²f"²ÒGW¶W”öb†Ò“²–b†²’ö¶æ÷vä¶W—5¶µÒÒvÖçVÃ¢r²Òæ–C²×Ò“°¢ö¶æ÷väæÖW2Òö&¦V7Bæ¶W—2…ö¶æ÷väæÖU6÷W&6R“°¢òòÖ—'&÷"–çFòF†R6ÆVæF"f–Wr‡W6W2F†R6ÖRFF6WB¢&VæFW$6ÆVæF"†Wg2Â7FFTÖÂÖçVÅ&÷w2“°¢òò66†Rf÷"F†RVWVR²ÆææW"f–Ww3²&Vg&W6‚v†–6†WfW"—27F—fRÇW0¢òòF†RF"Ö6÷VçB&FvW2‡6òfÆvv–ærò6öæfÆ–7G2WFFRÆ—fR’à¢öÆ7DWg2ÒWg3²öÆ7E7FFTÖÒ7FFTÖ²öÆ7E7FFU&÷w2Ò7FFU&÷w3²öÆ7DÖçVÂÒÖçVÅ&÷w3°¢f"&öö¶–ætGWÆ–6FW2ÒæWr6WB‚“°¢F÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&E¶FFÖGWÖ†–FFVãÒ#%Òr’æf÷$V6‚†gVæ7F–öâ†6&B’·°¢&öö¶–ætGWÆ–6FW2æFB†6&BæFF6WBæÖçVÄ–BòvÒr¶6&BæFF6WBæÖçVÄ–B¢vRr¶6&BæFF6WBæWfVçDçVÒ“°¢×Ò“°¢–b‡v–æF÷rä7F–öä6VçFW"’v–æF÷rä7F–öä6VçFW"çWFFR€¢ÆÄWg2æÖ†gVæ7F–öâ†Wb’·°¢f"ÖW&vVBÒö&¦V7Bæ76–vâ‡··×ÒÂWb’Â÷fW&Æ’Ò7FFTÖ¶WbæçVÕÒÇÂ··×Ó°¢ö&¦V7Bæ¶W—2†÷fW&Æ’’æf÷$V6‚†gVæ7F–öâ†²’·²–b†÷fW&Æ•¶µÒÒçVÆÂbb÷fW&Æ•¶µÒÓÒrr’ÖW&vVE¶µÒÒ÷fW&Æ•¶µÒÓÓÒuõö6ÆV&VEõòròrr¢÷fW&Æ•¶µÓ²×Ò“°¢&WGW&âö&¦V7Bæ76–vâ†ÖW&vVBÂ·µ÷F&ÆS¢vWfVçE÷7FFRrÂö¶W“¦WbæçVÒÂö–C¢vRr¶WbæçV××Ò“°¢×Ò¢æ6öæ6B†ÖçVÅ&÷w2æÖ†gVæ7F–öâ†Ò’·²&WGW&âö&¦V7Bæ76–vâ‡··×ÒÂÒÂ·µ÷F&ÆS¢vÖçVÅöWfVçG2rÂö¶W“¦Òæ–BÂö–C¢vÒr¶Òæ–G×Ò“²×Ò’’æf–ÇFW"†gVæ7F–öâ‡"’·²&WGW&â&öö¶–ætGWÆ–6FW2æ†2‡"åö–B“²×Ò¢“° ¢÷4–çfÆ–FFT—FV×2‚“²òòæWrFF(	BF†RÖVÖò×W7Bæ÷B7W'f—fR—@¢òòF–fbF†—2ÆöBv–ç7BF†RÆ7BöæR$Tdõ$Rç—F†–ær&VæFW'2Â6ð¢òò$–âF†RÆ7BvVV²"6â6’v†B7GVÆÇ’6†ævVBà¢G'’·²÷vå66ä6†ævW2‡7FFU&÷w2ÂÖçVÅ&÷w2“²×Ò6F6‚†R’··×Ð¢–b†7W'&VçEf–WrÓÓÒv×–WfVçG2r’&VæFW$×”WfVçG2‚“°¢VÇ6R–b†7W'&VçEf–WrÓÓÒwVWVRr’&VæFW%VWVR‚“°¢VÇ6R–b†7W'&VçEf–WrÓÓÒwÆææW"r’&VæFW%ÆææW"‚“°¢WFFUf–Wt&FvW2‚“°¢òòföÆBWfW'–öæRw2×’Õ&öf–ÆRFW‡B–çFòF†RF7FR66†Röæ6R†&–òð¢òòF÷–72ò7BFÆ·2òæ÷FW2Ö¶R7VvvW7F–öç2Ö÷&RF–Æ÷&VB’ÂF†Và¢òò&Vg&W6‚F†R7VvvW7F–öâ7W&f6W26òF†W’&VfÆV7B—Bà¢–b…÷&öf–ÆUF7FT66†RÓÓÒçVÆÂ’·°¢öÆöE&öf–ÆUF7FR†gVæ7F–öâ‚’·°¢–b†7W'&VçEf–WrÓÓÒv×–WfVçG2r’&VæFW$×”WfVçG2‚“°¢×Ò“°¢×Ð¢òòæBF†RÖÂv†Vâ—Bw2F†R7F—fRf–Wr‡&VÇF–ÖRV6†òò6fW2’à¢–b†7W'&VçEf–WrÓÓÒvÖrbbö÷4ÖÆ–W"’&VæFW$÷4Ö‚“°¢òòWBF†R&VFW"&6²v†W&RF†W’vW&R†6GW&VBBF†RF÷“¢&RÖ÷Và¢òòF†RVF—F÷"F†W’†B÷VâæB&W7F÷&RF†R67&öÆÂ÷6—F–öâ6ò6fP¢òò÷"&VÇF–ÖRV6†òæòÆöævW"6æ2F†VÒFòF†RF÷öbF†RÆ—7Bà¢–b…ö÷Vä¶W’’·°¢f"÷6VÂÒö÷Vä¶W’æ6†$Bƒ’ÓÓÒvÒp¢òræ÷2Ö6&E¶FFÖÖçVÂÖ–CÒ"r²ö÷Vä¶W’ç6Æ–6Rƒ’²r%Òp¢¢ræ÷2Ö6&E¶FFÖWfVçBÖçVÓÒ"r²ö÷Vä¶W’ç6Æ–6Rƒ’²r%Òs°¢f"öv–âÒF÷4w&–BçVW'•6VÆV7F÷"…÷6VÂ“°¢–b…öv–â’·°¢f"öVC"Òöv–âçVW'•6VÆV7F÷"‚vFWF–Ç2æ÷2ÖVF—Br“°¢–b…öVC"’öVC"æ÷VâÒG'VS°¢×Ð¢×Ð¢òò&R×6VBF†R÷VâFööÆ&"æVÂ†FWF6†VB'’F†R&V'V–ÆB&÷fR’à¢–b…÷æVÂ’F÷4w&–Bæ–ç6W'D&Vf÷&R…÷æVÂÂF÷4w&–Bæf—'7D6†–ÆB“°¢v–æF÷rç67&öÆÅFòƒÂ÷&We67&öÆÅ’“°¢×Ò’æ6F6‚†gVæ7F–öâ†W'"’·°¢òòfWF6‚f–ÆVBgFW"&WG&–W2Âõ"F†R&VæFW"—G6VÆbF‡&WrÖ–BÖ'V–ÆB(	@¢òòV—F†W"v’ÂæWfW"ÆVfR6–ÆVçB&Ææ²w&–C¢6†÷r²WFò×&WG'’à¢6†÷t÷4ÆöDW'&÷"†VÖ–ÂÂW'"“°¢×Ò“°¢×Ð ¢òò)H)HVÖ–Â(i"WfVçBÖf–VÆG2W‡G&7F÷")H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢gVæ7F–öâW‡G&7Dg&öÔVÖ–Â‡FW‡B’·°¢f"÷WBÒ··×Ó°¢FW‡BÒFW‡BÇÂrs°¢òòU$Â(	Bf—'7BÆW6–&ÆR‡GG3ó¢òòÆ–æ²Â6¶—6öÖÖöâ&ö–ÆW'ÆFP¢f"W&Å&RÒö‡GG3ó¥ÂõÂõµåÇ3Ãâ"uÅÕÂ•Ò²ös°¢f"W&Ç2ÒFW‡BæÖF6‚‡W&Å&R’ÇÂµÓ°¢f"6¶—BÒ÷Vç7V'67&–&WÇ&—f7—ÇFW&×2Ööb×6W'f–6WÆvöövÆWW6W&6öçFVçGÇG&6µÂçÆ6Æ–6µÂçÆæ÷F–f–6F–öç3õÂâö“°¢f"vööBÒçVÆÃ°¢f÷"‡f"’Ò²’ÂW&Ç2æÆVæwFƒ²’²²’·°¢–b‚6¶—BçFW7B‡W&Ç5¶•Ò’’·²vööBÒW&Ç5¶•Ó²'&V³²×Ð¢×Ð¢–b†vööB’÷WBçW&ÂÒvööBç&WÆ6R‚õ²âÃ³£âuÂ•Ò²BòÂrr“°¢òòFFR(	B×VÇF—ÆRf÷&ÖG2Â&VfW"&ævW0¢f"ÖöçF‡2Òt¦çV'—ÄfV''V'—ÄÖ&6‡Ä&–ÇÄÖ—Ä§VæWÄ§VÇ—ÄVwW7GÅ6WFVÖ&W'Äö7Fö&W'Äæ÷fVÖ&W'ÄFV6VÖ&W"s°¢f"ÖöçF‡56†÷'BÒt¦çÄfV'ÄÖ'Ä'ÄÖ—Ä§VçÄ§VÇÄVwÅ6WÄö7GÄæ÷gÄFV2s°¢f"FFU&W2Ò°¢æWr&VtW‡‚rƒó¢r²ÖöçF‡2²r•ÅÅÅÇ2µÅÅÅÆG·³Ã'×ÕÅÅÅÇ2¥¾(	>(	BÕÕÅÅÅÇ2¢ƒó¢ƒó¢r²ÖöçF‡2²r•ÅÅÅÇ2²“õÅÅÅÆG·³Ã'×ÒÅÅÅÅÇ2µÅÅÅÆG·³G×ÒrÂv’r’À¢æWr&VtW‡‚rƒó¢r²ÖöçF‡2²r•ÅÅÅÇ2µÅÅÅÆG·³Ã'×ÒÅÅÅÅÇ2µÅÅÅÆG·³G×ÒrÂv’r’À¢æWr&VtW‡‚rƒó¢r²ÖöçF‡56†÷'B²r•ÅÅÅÇ2µÅÅÅÆG·³Ã'×ÕÅÅÅÇ2¥¾(	>(	BÕÕÅÅÅÇ2¥ÅÅÅÆG·³Ã'×ÒÅÅÅÅÇ2µÅÅÅÆG·³G×ÒrÂv’r’À¢æWr&VtW‡‚rƒó¢r²ÖöçF‡56†÷'B²r•ÅÅÅÇ2µÅÅÅÆG·³Ã'×ÒÅÅÅÅÇ2µÅÅÅÆG·³G×ÒrÂv’r¢Ó°¢f÷"‡f"¢Ò²¢ÂFFU&W2æÆVæwFƒ²¢²²’·°¢f"FÒÒFW‡BæÖF6‚†FFU&W5¶¥Ò“°¢–b†FÒ’·²÷WBæFFU÷7G"ÒFÕ³Ó²'&V³²×Ð¢×Ð¢òòæÖR(	B7V&¦V7BÆ–æRf—'7C²VÇ6Rf—'7B&V6öæ&ÆRÆ–æRà¢òò7G&—&S¢ôgvC¢&Vf—†W2&WVFVFÇ’Fò†æFÆR6†–ç2Æ–¶R$gvC¢&S¢(
b ¢f"7V&¢ÒFW‡BæÖF6‚‚õåÇ2¥7V&¦V7C¥Ç2¢‚â²’Bö–Ò“°¢–b‡7V&¢’·°¢f"æÒÒ7V&¥³ÒçG&–Ò‚“°¢v†–ÆR‚õâƒó¥&S§ÄgvCó§Äes¢•Ç2¢ö’çFW7B†æÒ’’·°¢æÒÒæÒç&WÆ6R‚õâƒó¥&S§ÄgvCó§Äes¢•Ç2¢ö’Ârr“°¢×Ð¢÷WBææÖRÒæÓ°¢×ÒVÇ6R·°¢f"Æ–æW2ÒFW‡Bç7Æ—B‚õÅÇ#õÅÆâò’æÖ†gVæ7F–öâ‡2’·²&WGW&â2çG&–Ò‚“²×Ò’æf–ÇFW"„&ööÆVâ“°¢f÷"‡f"²Ò²²ÂÆ–æW2æÆVæwFƒ²²²²’·°¢f"ÂÒÆ–æW5¶µÓ°¢–b†ÂæÆVæwF‚âRbbÂæÆVæwF‚Â#bbõæ‡GG3ó¢ö’çFW7B†Â’bbõåµÇrâÕÒ´µÇrâÕÒ²òçFW7B†Â’’·°¢÷WBææÖRÒÃ²'&V³°¢×Ð¢×Ð¢×Ð¢òòÆö6F–öâ(	B×VÇF’×F–W"fÆÆ&6³ ¢òòâ$Æö6F–öã¢"ò%v†W&S¢"ò%fVçVS¢"¶W—v÷&BÆ–æR‡7G&öævW7B¢òò"â$6—G’Â6÷VçG'’"æ6†÷&VBBVæBöb7FæFÆöæRÆ–æP¢òò2â&–âÄ6—G“â"&÷6R†fö–B&B"v†–6‚fÇ6VÇ’ÖF6†W2'7V²B‚"¢f"Æ²ÒFW‡BæÖF6‚‚õåÇ2¢ƒó¤Æö6F–öçÅv†W&WÅfVçVWÄ6—G’•Ç2£¥Ç2¢‚â²’Bö–Ò“°¢–b†Æ²’·°¢÷WBæÆö6F–öâÒÆµ³ÒçG&–Ò‚“°¢×ÒVÇ6R·°¢f"7FæFÆöæRÒFW‡BæÖF6‚‚ò…´Õ¥Õ¶×¤Õ¥Ò²ƒó¥²ÇEÒµ´Õ¥Õ¶×¤Õ¥Ò²“òÅ²ÇEÒµ´Õ¥Õ¶×¤Õ¥Ò²•²ÇEÒ¢BöÒ“°¢–b‡7FæFÆöæR’·°¢÷WBæÆö6F–öâÒ7FæFÆöæU³ÒçG&–Ò‚“°¢×ÒVÇ6R·°¢f"Æ2ÒFW‡BæÖF6‚‚õÅÆ&–åÇ2²…´Õ¥Õ¶×¤Õ¥Ò²ƒó¥Ç2µ´Õ¥Õ¶×¤Õ¥Ò²“òƒó¢ÅÇ2µ´Õ¥Õ¶×¤Õ¥Ò²“ò’ò“°¢–b†Æ2’÷WBæÆö6F–öâÒÆ5³ÒçG&–Ò‚“°¢×Ð¢×Ð¢òò&Vv–öâwVW72g&öÒÆö6F–öà¢–b†÷WBæÆö6F–öâ’·°¢f"ÆòÒ÷WBæÆö6F–öâçFôÆ÷vW$66R‚“°¢f"örÒ6æöæ–6Å&Vv–öâ‡·²Æö6F–öã¢÷WBæÆö6F–öâ×Ò“°¢–b…örbbörÓÒtvÆö&Âr’÷WBç&Vv–öâÒös°¢×Ð¢&WGW&â÷WC°¢×Ð ¢òòÇ’W‡G&7FVBf–VÆG2FòF†Rf÷&Ò†öæÇ’f–ÆÇ2V×G’–çWG2'’FVfVÇB¢òò6Æ–6²×FòÖ÷Vâ6ÆVæF"÷Wf÷"F†RFBÖWfVçBFFRf–VÆBâ7W÷'G2¢òò6–ævÆRF’õ"&ævS¢6Æ–6²öæRF’‡6–ævÆR’Â6Æ–6²6V6öæBÆFW"F¢òò‡&ævR“²F†—&B6Æ–6²7F'G2÷fW"âw&—FW2F†Rf÷&ÖGFVBFFR–çFòF†P¢òòFW‡B–çWBäB7F6†W2W†7B•4ò7F'BöVæBöâ—G2FF6WB‡F†R7V&Ö—@¢òò†æFÆW"G'W7G2F†÷6R’âF†Rf–VÆB—27F–ÆÂg&VR×FW‡B²fÆW†–&Ç’'6VBà¢gVæ7F–öâv—&TFFU–6¶W"‡w&’·°¢–b‚w&ÇÂw&æFF6WBçv—&VB’&WGW&ã°¢w&æFF6WBçv—&VBÒss°¢f"–çWBÒw&çVW'•6VÆV7F÷"‚ræFFRÖfÆW‚Ö–çWBr“°¢f"÷Òw&çVW'•6VÆV7F÷"‚ræFFRÖ6Âr“°¢–b‚–çWBÇÂ÷’&WGW&ã°¢f"ÔôâÒ²t¦çV'’rÂtfV''V'’rÂtÖ&6‚rÂt&–ÂrÂtÖ’rÂt§VæRrÂt§VÇ’rÂtVwW7BrÂu6WFVÖ&W"rÂtö7Fö&W"rÂtæ÷fVÖ&W"rÂtFV6VÖ&W"uÓ°¢f"DõrÒ²u7RrÂtÖòrÂuGRrÂuvRrÂuF‚rÂtg"rÂu6uÓ°¢f"6VÂÒ·²7F'C¢çVÆÂÂVæC¢çVÆÂ×Ó°¢f"f–Wu’Âf–WtÓ°¢gVæ7F–öâB†â’·²&WGW&â7G&–ær†â’çE7F'Bƒ"Âsr“²×Ð¢gVæ7F–öâ—6ôöb‡’ÂÓÂB’·²&WGW&â’²rÒr²B†Ó²’²rÒr²B†B“²×Ð¢gVæ7F–öâ'G4öb†—6ò’·²f"ÒÒõâ…ÅÆG·³G×Ò’Ò…ÅÆG·³'×Ò’Ò…ÅÆG·³'×Ò’òæW†V2†—6òÇÂrr“²&WGW&âÒò·²“¢¶Õ³ÒÂÖó¢¶Õ³%ÒÒÂC¢¶Õ³5Ò×Ò¢çVÆÃ²×Ð¢gVæ7F–öâf×B‡4—6òÂT—6ò’·°¢f"2Ò'G4öb‡4—6ò“²–b‚2’&WGW&ârs°¢f"RÒ'G4öb†T—6ò’Â4ÒÒÔôå·2æÖõÓ°¢–b‚RÇÂ†Rç’ÓÓÒ2ç’bbRæÖòÓÓÒ2æÖòbbRæBÓÓÒ2æB’’&WGW&â4Ò²rr²2æB²rÂr²2ç“°¢f"TÒÒÔôå¶RæÖõÓ°¢–b†Rç’ÓÓÒ2ç’bbRæÖòÓÓÒ2æÖò’&WGW&â4Ò²rr²2æB²uÅÇS#2r²RæB²rÂr²2ç“°¢–b†Rç’ÓÓÒ2ç’’&WGW&â4Ò²rr²2æB²rÅÇS#2r²TÒ²rr²RæB²rÂr²2ç“°¢&WGW&â4Ò²rr²2æB²rÂr²2ç’²rÅÇS#2r²TÒ²rr²RæB²rÂr²Rç“°¢×Ð¢gVæ7F–öâw&—FT–çWB‚’·°¢–b‚6VÂç7F'B’&WGW&ã°¢f"—5&ævRÒ6VÂæVæBbb6VÂæVæBÓÒ6VÂç7F'C°¢–çWBçfÇVRÒf×B‡6VÂç7F'BÂ—5&ævRò6VÂæVæB¢çVÆÂ“°¢–çWBç6WDGG&–'WFR‚vFF×7F'BÖ—6òrÂ6VÂç7F'B“°¢–çWBç6WDGG&–'WFR‚vFFÖVæBÖ—6òrÂ—5&ævRò6VÂæVæB¢6VÂç7F'B“°¢×Ð¢gVæ7F–öâ&VæFW"‚’·°¢f"7F'DF÷rÒæWrFFR‡f–Wu’Âf–WtÒÂ’ævWDF’‚“°¢f"F—4–âÒæWrFFR‡f–Wu’Âf–WtÒ²Â’ævWDFFR‚“°¢f"‡FÖÂÒsÆF—b6Æ73Ò&F2Ö†VB#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&F2Öæb"FFÖæcÒ"Ó"&–ÖÆ&VÃÒ%&Wf–÷W2ÖöçF‚#åÅÇS#3“Âö'WGFöãâr°¢sÇ7â6Æ73Ò&F2×F—FÆR#âr²Ôôå·f–WtÕÒ²rr²f–Wu’²sÂ÷7ãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&F2Öæb"FFÖæcÒ#"&–ÖÆ&VÃÒ$æW‡BÖöçF‚#åÅÇS#6Âö'WGFöãâr°¢sÂöF—cãÆF—b6Æ73Ò&F2Öw&–B#âs°¢Dõræf÷$V6‚†gVæ7F–öâ†B’·²‡FÖÂ³ÒsÇ7â6Æ73Ò&F2ÖF÷r#âr²B²sÂ÷7ãâs²×Ò“°¢f"“°¢f÷"†’Ò²’Â7F'DF÷s²’²²’‡FÖÂ³ÒsÇ7â6Æ73Ò&F2ÖF’F2ÖV×G’#ãÂ÷7ãâs°¢f"—5"Ò6VÂç7F'Bbb6VÂæVæBbb6VÂç7F'BÓÒ6VÂæVæC°¢f÷"‡f"F’Ò²F’ÃÒF—4–ã²F’²²’·°¢f"—6òÒ—6ôöb‡f–Wu’Âf–WtÒÂF’’Â6Ç2ÒvF2ÖF’s°¢–b†—5"’·°¢–b†—6òÓÓÒ6VÂç7F'B’6Ç2³ÒrF2×7F'Bs°¢VÇ6R–b†—6òÓÓÒ6VÂæVæB’6Ç2³ÒrF2ÖVæBs°¢VÇ6R–b†—6òâ6VÂç7F'Bbb—6òÂ6VÂæVæB’6Ç2³ÒrF2Ö–ç&ævRs°¢×ÒVÇ6R–b‡6VÂç7F'Bbb—6òÓÓÒ6VÂç7F'B’6Ç2³ÒrF2×6–ævÆRs°¢‡FÖÂ³ÒsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò"r²6Ç2²r"FFÖ—6óÒ"r²—6ò²r#âr²F’²sÂö'WGFöãâs°¢×Ð¢‡FÖÂ³ÒsÂöF—cãÆF—b6Æ73Ò&F2Öfö÷B#ãÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&F2Ö6ÆV"#ä6ÆV#Âö'WGFöãâr°¢sÇ7â6Æ73Ò&F2Ö†–çB#äöæRF’Â÷"6Æ–6²&æBf÷"&ævSÂ÷7ãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&F2ÖFöæR#äFöæSÂö'WGFöããÂöF—câs°¢÷æ–ææW$…DÔÂÒ‡FÖÃ°¢×Ð¢gVæ7F–öâ÷Vä6Â‚’·°¢6VÂÒ·²7F'C¢çVÆÂÂVæC¢çVÆÂ×Ó°¢f"G2Ò–çWBævWDGG&–'WFR‚vFF×7F'BÖ—6òr’ÂFRÒ–çWBævWDGG&–'WFR‚vFFÖVæBÖ—6òr“°¢–b†G2’·²6VÂç7F'BÒG3²6VÂæVæBÒFRÇÂG3²×Ð¢VÇ6R·°¢f"BÒ†–çWBçfÇVRÇÂrr’çG&–Ò‚“°¢–b‡B’·²G'’·²f"BÒFW&—fTFFW4g&öÕFW‡B‡B“²–b†BbbBç7F'EöFFR’·²6VÂç7F'BÒBç7F'EöFFS²6VÂæVæBÒBæVæEöFFRÇÂBç7F'EöFFS²×Ò×Ò6F6‚†R’··×Ò×Ð¢×Ð¢f"&6RÒ6VÂç7F'Bò'G4öb‡6VÂç7F'B’¢çVÆÂÂæ÷rÒæWrFFR‚“°¢f–Wu’Ò&6Rò&6Rç’¢æ÷rævWDgVÆÅ–V"‚“°¢f–WtÒÒ&6Rò&6RæÖò¢æ÷rævWDÖöçF‚‚“°¢&VæFW"‚“°¢÷æ†–FFVâÒfÇ6S°¢×Ð¢gVæ7F–öâ6Æ÷6T6Â‚’·²÷æ†–FFVâÒG'VS²×Ð¢–çWBæFDWfVçDÆ—7FVæW"‚vfö7W2rÂ÷Vä6Â“°¢–çWBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂ÷Vä6Â“°¢–çWBæFDWfVçDÆ—7FVæW"‚v–çWBrÂgVæ7F–öâ‚’·²–çWBç&VÖ÷fTGG&–'WFR‚vFF×7F'BÖ—6òr“²–çWBç&VÖ÷fTGG&–'WFR‚vFFÖVæBÖ—6òr“²×Ò“°¢÷æFDWfVçDÆ—7FVæW"‚vÖ÷W6VF÷vârÂgVæ7F–öâ†R’·²Rç&WfVçDFVfVÇB‚“²×Ò“²òòFöâwB7FVÂfö7W2ò&ÇW"Ö6Æ÷6RF†Rf–VÆ@¢÷æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢òò¶VWF†R6Æ–6²–ç6–FRF†R÷W¢&VæFW"‚’&VÆ÷r&WÆ6W2F†R÷Ww0¢òò–ææW$…DÔÂÂv†–6‚FWF6†W2F†RVÆVÖVçB–÷R6Æ–6¶VB‡F†R(’ò(¢'&÷rÂ¢òòF’6VÆÂ’âv—F†÷WBF†—2ÂF†R6Æ–6²'V&&ÆW2FòF†RFö7VÖVç@¢òò&÷WG6–FRÖ6Æ–6²6Æ÷6W2"†æFÆW"Âv†–6‚F†Vâ6VW2æ÷rÖFWF6†VBF&vW@¢òòF†Bw2æòÆöævW"–ç6–FRæFFR×–6²æB6Æ÷6W2F†R6ÆVæF"(	B6òF†P¢òòÖöçF‚'&÷w2†æBÖ–B×&ævRF’–6·2’V&VBFò&6Æ÷6RF†R–6¶W""à¢Rç7F÷&÷vF–öâ‚“°¢f"æbÒRçF&vWBæ6Æ÷6W7B‚u¶FFÖæeÒr“°¢–b†æb’·²f–WtÒ³Ò'6T–çB†æbævWDGG&–'WFR‚vFFÖæbr’Â“²–b‡f–WtÒÂ’·²f–WtÒÒ²f–Wu’ÒÓ²×ÒVÇ6R–b‡f–WtÒâ’·²f–WtÒÒ²f–Wu’²³²×Ò&VæFW"‚“²&WGW&ã²×Ð¢–b†RçF&vWBæ6Æ÷6W7B‚ræF2Ö6ÆV"r’’·²6VÂÒ·²7F'C¢çVÆÂÂVæC¢çVÆÂ×Ó²–çWBçfÇVRÒrs²–çWBç&VÖ÷fTGG&–'WFR‚vFF×7F'BÖ—6òr“²–çWBç&VÖ÷fTGG&–'WFR‚vFFÖVæBÖ—6òr“²&VæFW"‚“²&WGW&ã²×Ð¢–b†RçF&vWBæ6Æ÷6W7B‚ræF2ÖFöæRr’’·²6Æ÷6T6Â‚“²&WGW&ã²×Ð¢f"6VÆÂÒRçF&vWBæ6Æ÷6W7B‚u¶FFÖ—6õÒr“°¢–b†6VÆÂ’·°¢f"—6òÒ6VÆÂævWDGG&–'WFR‚vFFÖ—6òr“°¢–b‚6VÂç7F'BÇÂ‡6VÂæVæBbb6VÂç7F'BÓÒ6VÂæVæB’ÇÂ—6òÂ6VÂç7F'B’6VÂÒ·²7F'C¢—6òÂVæC¢—6ò×Ó°¢VÇ6R6VÂæVæBÒ—6ó°¢w&—FT–çWB‚“°¢&VæFW"‚“°¢×Ð¢×Ò“°¢Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·²–b‚w&æ6öçF–ç2†RçF&vWB’’6Æ÷6T6Â‚“²×Ò“°¢×Ð ¢gVæ7F–öâÇ”W‡G&7EFôf÷&Ò†f÷&ÒÂW‡G&7FVBÂ÷G2’·°¢÷G2Ò÷G2ÇÂ··×Ó°¢òòÖWfW'’f–VÆBF†R67&W"6â&WGW&â(	Bæ÷B§W7BF†R&6–2Râ6VÆV7G0¢òò‡&Vv–öâ÷G—R÷&–÷&—G’öVF–Væ6U÷G—R÷•÷Fõ÷Æ’’f–ÆÂöæÇ’–bF†RfÇVP¢òòÖF6†W2â÷F–öã²FW‡Bf–VÆG2Çv—2f–ÆÂâ&W7BÖVff÷'BÂæWfW"6Æö&&W'0¢òòfÇVRF†RW6W"Ç&VG’G—VB†÷fW'w&—FS¦fÇ6R’à¢f"¶W—2Ò²væÖRrÂvFFU÷7G"rÂvÆö6F–öârÂw&Vv–öârÂwW&ÂrÂwG—RrÀ¢w&–÷&—G’rÂwv‡’rÂv&÷WBrÂvfö7W5ö&V2rÂwG—–6ÅöGFVæFVW2rÀ¢w7V¶–æu÷&÷WFRrÂv6öçF7Eö–æfòrÂvVF–Væ6U÷G—RrÂw•÷Fõ÷Æ’rÀ¢w&–6–ærrÂvGFVæFVUö6÷VçBrÂw7E÷7V¶W'2rÂwfVçVRrÂvFVFÆ–æRrÀ¢w7V¶W"rÂvÖVWF–æuöf÷&ÖG2uÓ°¢f"f–ÆÆVBÒÂ6¶—VBÒ°¢¶W—2æf÷$V6‚†gVæ7F–öâ†²’·°¢f"VÂÒf÷&ÒçVW'•6VÆV7F÷"‚u¶æÖSÒ"r²²²r%Òr“°¢–b‚VÂ’&WGW&ã°¢–b‚W‡G&7FVE¶µÒ’&WGW&ã°¢–b†VÂçfÇVRbb÷G2æ÷fW'w&—FR’·²6¶—VB²³²&WGW&ã²×Ð¢VÂçfÇVRÒW‡G&7FVE¶µÓ°¢f–ÆÆVB²³°¢òòF†RFFRf–VÆBw26ÆVæF"÷W&VG2F†R–çWBw2•4ò7F6ƒ²67&V@¢òòg&VR×FW‡BFFR6†÷VÆBfÆÂ&6²FòfÆW†–&ÆR'6–ærÂ6ò6ÆV"F†R7F6‚à¢–b†²ÓÓÒvFFU÷7G"r’·²VÂç&VÖ÷fTGG&–'WFR‚vFF×7F'BÖ—6òr“²VÂç&VÖ÷fTGG&–'WFR‚vFFÖVæBÖ—6òr“²×Ð¢×Ò“°¢&WGW&â·²f–ÆÆVC¢f–ÆÆVBÂ6¶—VC¢6¶—VBÂF÷FÃ¢¶W—2æf–ÇFW"†gVæ7F–öâ†²’·²&WGW&âW‡G&7FVE¶µÓ²×Ò’æÆVæwF‚×Ó°¢×Ð ¢gVæ7F–öâ'V–ÆDFDWfVçDf÷&Ò‚’·°¢f"f÷&ÒÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vf÷&Òr“°¢f÷&Òæ–BÒvFBÖWfVçBÖ6&Bs°¢f÷&Òæ6Æ74æÖRÒvFBÖWfVçBÖ6&B÷2Öf÷&Òs°¢f÷&Òæ–ææW$…DÔÂÐ¢sÆƒ3äæWrÖçVÂWfVçCÂöƒ3âr°¢sÆFWF–Ç26Æ73Ò&÷2ÖVF—B"–CÒ'7FRÖVÖ–Â×6V7F–öâ#âr°¢sÇ7VÖÖ'“ä÷"7FRg&öÒVÖ–ÂòvV"6÷ž(
cÂ÷7VÖÖ'“âr°¢sÆF—b6Æ73Ò&÷2Öf÷&Ò"7G–ÆSÒ&Ö&v–â×F÷£‡ƒ²#âr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#å7FR†W&SÂ÷7ãâr°¢sÇFW‡F&V–CÒ'7FRÖVÖ–Â×FW‡B"Æ6V†öÆFW#Ò%7FRF†RgVÆÂVÖ–ÂòvV"Æ—7F–ærDU…B(	B÷"§W7BF†RWfVçBÄ”ä²‡vUÅÇS#–ÆÂ67&RF†RvR’âWFòÖf–ÆÇ2æÖRÂFFRÂÆö6F–öâÂ&Vv–öâÂU$Ââ"7G–ÆSÒ&Ö–âÖ†V–v‡C£#ƒ²#ãÂ÷FW‡F&Vâr°¢sÂöÆ&VÃâr°¢sÆF—b6Æ73Ò&FBÖ7F–öç2#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’"–CÒ'7FRÖW‡G&7BÖ'Fâ#äW‡G&7Bf–VÆG3Âö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'6V6öæF'’"–CÒ'7FRÖ6ÆV"Ö'Fâ#ä6ÆV#Âö'WGFöãâr°¢sÂöF—câr°¢sÇ6Æ73Ò&÷2ÖÖWF"–CÒ'7FRÖW‡G&7BÖÖWF#ãÂ÷âr°¢sÂöF—câr°¢sÂöFWF–Ç3âr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#åU$Â(	B7FR†W&RFòWFòÖf–ÆÂ(i3Â÷7ãâr°¢sÆF—b7G–ÆSÒ&F—7Æ“¦fÆWƒ¶v£gƒ¶Æ–vâÖ—FV×3§7G&WF6ƒ²#âr°¢sÆ–çWBG—SÒ'FW‡B"æÖSÒ'W&Â"Æ6V†öÆFW#Ò&‡GG3¢òöWfVçB×6—FRæ6öÒ"7G–ÆSÒ&fÆWƒ£²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’"–CÒ&f–ÆÂÖg&öÒ×W&ÂÖ'Fâ"7G–ÆSÒ'v†—FR×76S¦æ÷w&·FF–æs£Gƒ¶föçB×6—¦S£ãƒW&VÓ²#äf–ÆÂg&öÒU$ÃÂö'WGFöãâr°¢sÂöF—câr°¢sÇ6Æ73Ò&÷2ÖÖWF"–CÒ&f–ÆÂÖg&öÒ×W&ÂÖÖWF"7G–ÆSÒ&Ö&v–ã£g‚²#ãÂ÷âr°¢sÂöÆ&VÃâr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#äæÖR£Â÷7ãâr°¢sÆ–çWBG—SÒ'FW‡B"æÖSÒ&æÖR"&WV—&VBÆ6V†öÆFW#Ò&Rærâ’7VÖÖ—B6âg&æ6—66ò#âr°¢sÂöÆ&VÃâr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#äFFSÂ÷7ãâr°¢sÆF—b6Æ73Ò&FFR×–6²#âr°¢sÆ–çWBG—SÒ'FW‡B"æÖSÒ&FFU÷7G""6Æ73Ò&FFRÖfÆW‚Ö–çWB"WFö6ö×ÆWFSÒ&öfb"Æ6V†öÆFW#Ò%G—Rç’FFR†Rærâ6WB.(	3BÂ##b+r’ó"+ræW‡B6–ævÆRF’’Â÷"6Æ–6²Fò–6²#âr°¢sÆF—b6Æ73Ò&FFRÖ6Â"†–FFVããÂöF—câr°¢sÂöF—câr°¢sÂöÆ&VÃâr°¢sÆF—b6Æ73Ò'&÷r#âr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#äÆö6F–öãÂ÷7ãâr°¢sÆ–çWBG—SÒ'FW‡B"æÖSÒ&Æö6F–öâ"Æ6V†öÆFW#Ò$6—G’Â6÷VçG'’#âr°¢sÂöÆ&VÃâr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#å&Vv–öãÂ÷7ãâr°¢sÇ6VÆV7BæÖSÒ'&Vv–öâ#âr°¢÷F–öå&÷w2…²rrÂuU2b6æFrÂtÆF–âÖW&–6rÂtWW&÷RrÂtg&–6rÂtÔTärÂt6–Õ6–f–2rÂtvÆö&ÂuÒÂrr’°¢sÂ÷6VÆV7Câr°¢sÂöÆ&VÃâr°¢sÂöF—câr°¢sÆF—b6Æ73Ò'&÷r#âr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#åG—SÂ÷7ãâr°¢sÆ–çWBG—SÒ'FW‡B"æÖSÒ'G—R"Æ6V†öÆFW#Ò$VçFW'&—6RÂ†ÆòÂ&W6V&6‚Â(
b#âr°¢sÂöÆ&VÃâr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#å&–÷&—G“Â÷7ãâr°¢sÇ6VÆV7BæÖSÒ'&–÷&—G’#âr°¢÷F–öå&÷w2…²rrÂt†–v‚rÂtÖVF—VÒrÂtÆ÷ruÒÂtÖVF—VÒr’°¢sÂ÷6VÆV7Câr°¢sÂöÆ&VÃâr°¢sÂöF—câr°¢sÆÆ&VÃãÇ7â6Æ73Ò&¶W’#ä&7F–4&ÇVR7V¶W#Â÷7ãâr°¢sÆ–çWBG—SÒ'FW‡B"æÖSÒ'7V¶W""Æ—7CÒ&"×7V¶W'2"Æ6V†öÆFW#Ò%F†÷"Â¦öRÂ¦W&öÖRÂ66÷GBÂfW&ÖÂ6&Æ÷2Â¦–Þ(
b#âr°¢sÂöÆ&VÃâr°¢sÆF—b6Æ73Ò&÷2Öf–VÆG6WB#ãÇ7â6Æ73Ò&¶W’#å—VÆ–æR7FvW3Â÷7ãâr°¢7FvT6†V6¶&÷†W2…µÒÂw7FGW5÷Fw2r’°¢sÂöF—câr°¢sÆFWF–Ç26Æ73Ò&÷2ÖVF—B#ãÇ7VÖÖ'“äÖ÷&RFWF–Ç2„&÷WBÂfö7W2ÂFVFÆ–æRÂ(
b“Â÷7VÖÖ'“âr°¢sÆF—b6Æ73Ò&÷2Öf÷&Ò"7G–ÆSÒ&Ö&v–â×F÷£‡ƒ²#âr²&–6„FWF–Äf–VÆG2‡··×Ò’²sÂöF—câr°¢sÂöFWF–Ç3âr°¢sÆF—b6Æ73Ò&FBÖ7F–öç2#âr°¢sÆ'WGFöâG—SÒ'7V&Ö—B"6Æ73Ò'&–Ö'’#äFBWfVçCÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'6V6öæF'’"FFÖ6æ6VÃä6æ6VÃÂö'WGFöãâr°¢sÂöF—câs°¢&WGW&âf÷&Ó°¢×Ð ¢òòFVGW–æFW‚öbWfW'’WfVçBæÖRvR¶æ÷r&÷WB(	B&Vg&W6†VBgFW ¢òòWfW'’–ç6W'B÷WFFRöFVÆWFR6ò—B7F—267W&FRâF†R6FÆöp¢òò†WfVçG2æ§6öâ’—2ÆöFVBöæ6S²ÖçVÅöWfVçG2—2&VÆöFVBV6‚F–ÖRà¢f"ö¶æ÷väæÖW2ÒçVÆÃ²òò6WBöbÆ÷vW&66VBæÖW0¢f"ö¶æ÷väæÖU6÷W&6RÒ··×Ó²òòÖ¢æÖUöÆ÷vW"(i"v6FÆörrÂvÖçVÂp¢f"ö¶æ÷vä¶W—2Ò··×Ó²òòÖ¢gW§§’æÖR¶6—G’·–V"¶W’(i"6÷W&6P¢f"ö¶æ÷vå&V2Ò··×Ó²òòÖ¢æÖUöÆ÷vW"ògW§§’¶W’(i"·¶æÖRÆÆö6F–öâÆFFU÷7G'×Òf÷"6ÆV&W"GWÖW76vW0¢òògW§§’GWÆ–6FR¶W“¢&VGV6RF†RæÖRFò—G26÷&R†G&÷&VçF†WF–6Ç2Æ–¶P¢òò"„•BVF—F–öâ’"ÂF†R–V"ÂæBVæ7GVF–öâ’ÂF†Vâ–âFò6—G’²–V"â6ð¢òò$’7VÖÖ—B'&6–Â(	26òVÆò##b"æB$’7VÖÖ—B'&6–Â(	B6òVÆð¢òò„•BVF—F–öâ’"6öÆÆ6RFòF†R4ÔR¶W’æB&R6Vv‡B2öæRWfVçBà¢gVæ7F–öâGWæÖT6÷&R†æÖR’·°¢&WGW&â$föÆB†æÖR¢òò6öÖÖöâ&'&Wf–F–öç2Â6ò$…"FV6‚"ÓÒ$…"FV6†æöÆöw’"æ@¢òò$’(
b"ÓÒ$'F–f–6–Â–çFVÆÆ–vVæ6R(
b"à¢ç&WÆ6R‚õÅÆ&'F–f–6–Â–çFVÆÆ–vVæ6UÅÆ"örÂv’r¢ç&WÆ6R‚õÅÆ'FV6†æöÆöw•ÅÆ"örÂwFV6‚r¢ç&WÆ6R‚õÅÆ&‡VÖâ&W6÷W&6W5ÅÆ"örÂv‡"r¢ç&WÆ6R‚õÅÂ‚â£õÅÂ’örÂrr’òò&VçF†WF–6Ç0¢ç&WÆ6R‚õÅÆ##ÅÆEÅÆEÅÆ"örÂrr’òò–V'2†6—G’·–V"¶W–VB6W&FVÇ’¢ç&WÆ6R‚ò…ÅÆB’…¶×¥Ò’örÂrCC"r’ç&WÆ6R‚ò…¶×¥Ò’…ÅÆB’örÂrCC"r’òòÖöæW“#ÓâÖöæW’# ¢ç&WÆ6R‚õµæ×£Ó’ÒörÂrr¢òò7G&—vVæW&–2&Vv–öâöVF—F–öâv÷&G26ò%‚U4"ÓÒ%‚æ÷'F‚ÖW&–6"ÓÐ¢òò%‚"‡F†R4•E’–âGW¶W”öb7F–ÆÂF—6Ö&–wVFW2&VÂF–ffW&VçBVF—F–öç2’à¢ç&WÆ6R‚õÅÆ"‡W6ÇW7ÇR2ÇVæ—FVB7FFW7ÆæÆæ÷'F‚ÖW&–6ÆVÖVÆ7ÆVF—F–öçÇ6W&–W2•ÅÆ"örÂrr¢ç&WÆ6R‚õÅÇ2²örÂrr’çG&–Ò‚“°¢×Ð¢f"ôEUô4õTåE$”U2Ò·²W6£ÂW3£ÂwR2s£ÂwVæ—FVB7FFW2s£ÂÖW&–6£ÂV³£ÂwR²s£ÂwVæ—FVB¶–ævFöÒs£ÂVævÆæC£Â66÷FÆæC£ÂvÆW3£Â6æF£ÂvW&Öç“£Âg&æ6S£Â7–ã£Â—FÇ“£ÂæWF†W&ÆæG3£Â†öÆÆæC£Â&VÆv—VÓ£Â7v—G¦W&ÆæC£ÂW7G&–£Â7vVFVã£ÂFVæÖ&³£Âæ÷'v“£Âf–æÆæC£Â—&VÆæC£Â÷'GVvÃ£ÂöÆæC£Â7¦V6†–£Â‡Væv'“£Â&öÖæ–£Âw&VV6S£ÂW7G&Æ–£ÂvæWr¦VÆæBs£Â¦ã£Â6†–æ£Â–æF–£Â¶÷&V£Âw6÷WF‚¶÷&Vs£ÂF†–ÆæC£ÂÖÆ—6–£Â–æFöæW6–£Âf–WFæÓ£Â†–Æ—–æW3£ÂF—vã£Â'&¦–Ã£ÂÖW†–6ó£Â&vVçF–æ£Â6†–ÆS£Â6öÆöÖ&–£ÂW'S£ÂGW&¶W“£ÂGW&¶—–S£Â—7&VÃ£ÂVw—C£ÂÖ÷&ö66ó£Âæ–vW&–£Â¶Vç–£ÂVS£ÂwVæ—FVB&"VÖ—&FW2s£Âw6VF’&&–s£ÂF#£Â&‡&–ã£Â·Wv—C£ÂöÖã£×Ó°¢gVæ7F–öâGW6—G”öb†ò’·°¢òÒòÇÂ··×Ó°¢f"2Ò7G&–ær†òæ6—G’ÇÂrr’çG&–Ò‚“°¢–b‚2’·°¢f"'G2Ò7G&–ær†òæÆö6F–öâÇÂrr’ç7Æ—B‚rÂr’æÖ†gVæ7F–öâ‡2’·²&WGW&â2çG&–Ò‚“²×Ò’æf–ÇFW"„&ööÆVâ“°¢òò&VBF†R4•E’'’vÆ¶–ærg&öÒF†RTäBöbF†RÆö6F–öâÂ6¶—–ærF†P¢òò6÷VçG'’æBç’7FFR÷&÷f–æ6R6öFR(	B6ò$6öçfVæRÂSR&—6†÷6vFRÀ¢òòÆöæFöâÂT²"æB#Sƒ2&²fVçVRÂæWr–÷&²Âå’ÂU4"&÷F‚&W6öÇfRFð¢òòF†R&VÂ6—G’„ÆöæFöâòæWr–÷&²’Âv†FWfW"F†RfVçVR—26ÆÆVBà¢f÷"‡f"’Ò'G2æÆVæwF‚Ò²’ãÒ²’ÒÒ’·°¢f"Ò'G5¶•Ó°¢–b…ôEUô4õTåE$”U5¶$föÆB‡•Ò’6öçF–çVS²òò6÷VçG'¢–b‚õå¶×¥×·³'×ÒBö’çFW7B‡’’6öçF–çVS²òò7FFRò&÷f–æ6R6öFR„å’Â4Âôâ¢–b‚õåÅÆBòçFW7B‡’’6öçF–çVS²òò7G&VWBçVÖ&W ¢2Ò²'&V³°¢×Ð¢–b‚2bb'G2æÆVæwF‚’2Ò'G5³Ó°¢×Ð¢òòæ÷&ÖÆ—6R$æWr–÷&²6—G’"Óâ&æWr–÷&²"Â$w&VFW"ÆöæFöâ"Óâ&ÆöæFöâ"à¢&WGW&â$föÆB†2’ç&WÆ6R‚õÅÆ"†6—G—Æw&VFW"•ÅÆ"örÂrr’ç&WÆ6R‚õÅÇ2²örÂrr’çG&–Ò‚“°¢×Ð¢gVæ7F–öâGW–V$öb†ò’·²f"ÒÒ‚†òç7F'EöFFRÇÂrr’²rr²†òæFFU÷7G"ÇÂrr’’æÖF6‚‚ó#ÅÆEÅÆBò“²&WGW&âÒòÕ³Ò¢rs²×Ð¢gVæ7F–öâGW¶W”öb†ò’·²f"6÷&RÒGWæÖT6÷&R†òææÖRÇÂrr“²&WGW&â6÷&Rò†6÷&R²wÂr²GW6—G”öb†ò’²wÂr²GW–V$öb†ò’’¢rs²×Ð¢òò)H)H7G&—ÖæB×&WG'’&÷VæBæ÷B×–WBÖÖ–w&FVB6öÇVÖç2)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò&–6–æròVF–Væ6U÷G—RvW&RFFVB##bÓbâ–bF†—2D"†6âwB'VâF†P¢òòÖ–w&F–öâ–WBÂ÷7Fu$U5B&V¦V7G2F†Rv†öÆRw&—FRâvRFWFV7BF†BÂG&÷ ¢òòF†RöffVæF–ær6öÇVÖâÂæB&WG'’6òF†R6fR7F–ÆÂÆæG2‡F†R'W–W"÷&–6P¢òòf–VÆG2§W7B7F’&Ææ²VçF–ÂF†RÖ–w&F–öâ'Vç2’à¢òò–çFW&æÂöVF—B6öÇVÖç3¢7G&—4”ÄTåDÅ’öâÖ—76–ærÖ6öÇVÖâW'&÷"‡F†W¢òò&VâwBW6W"ÖVçFW&VBFFÂ6òFöâwBv&âF†BF†W’'vW&VâwB6fVB"’à¢òð¢òòTÕE’4”ä4R##bÓ’ÓâF†—2†VÆB²wWFFVEö'’rÂwWFFVEöBuÒÂv†–6‚—0¢òòv‡’ÖçVÅöWfVçG2Æ÷7B—G2VF—BG&–Âf÷"6—‚vVV·2v—F†÷WBöæRf—6–&ÆP¢òò7–×FöÓ¢F†R6öÇVÖâv2Ö—76–ærÂF†Rw&—FRv27G&—VBÂæBF†R6–ÆVæ6P¢òòv2FVÆ–&W&FRâ&÷F‚6öÇVÖç2W†—7Böâ&÷F‚F&ÆW2æ÷rÂ6ò7G&—†W&P¢òòv÷VÆBÖVâ6öÖWF†–ær—2vVçV–æVÇ’w&öærÒÒÆWB—Bv&âà¢òòöæÇ’FB6öÇVÖâ&6²–b—B—2G'VÇ’÷F–öæÂäB—G2'6Væ6R—0¢òò6öÖWF†–æræö&öG’v÷VÆBWfW"æVVBFò6VRà¢f"4”ÄTåEõ5E$•ô4ôÅ2ÒµÓ°¢gVæ7F–öâÖ—76–æt6öÄg&öÔW'"†W'"’·°¢òòF†R6öÇVÖâæÖR÷7Fw&W2õ÷7Fu$U5B&W÷'G22Ö—76–ærÂf÷"V—F†W# ¢òòu%5C#B$6÷VÆBæ÷Bf–æBF†RwWFFVEö'’r6öÇVÖâöbvÖçVÅöWfVçG2r–âF†R66†VÖ66†R ¢òòC#s2&6öÇVÖâÖçVÅöWfVçG2çWFFVEö'’FöW2æ÷BW†—7B ¢òò&WGW&æ–ær—BÆWG26%w&—FU&WG'’7G&—F†BöæR6öÇVÖâæB&WG'’Â6ò6fP¢òòæWfW"F–W2§W7B&V6W6RF†RD"Æ6·2â÷F–öæÂòæ÷B×–WBÖÖ–w&FV@¢òò6öÇVÖâ†ç’6öÇVÖâÂæ÷B§W7B†&BÖ6öFVBÆ—7B’à¢–b‚W'"’&WGW&âçVÆÃ°¢f"×6rÒ†W'"æÖW76vRÇÂrr’²rr²†W'"æFWF–Ç2ÇÂrr“°¢f"6öFRÒ7G&–ær†W'"æ6öFRÇÂrr“°¢–b†6öFRÓÒuu%5C#Brbb6öFRÓÒsC#s2rbb×6rçFôÆ÷vW$66R‚’æ–æFW„öb‚v6öÇVÖâr’ÓÓÒÓ’&WGW&âçVÆÃ°¢f"ÒÒ×6ræÖF6‚‚öf–æBF†R²r%Ò…´Õ¦×£Ó•õÒ²•²r%Ò6öÇVÖâö’¢ÇÂ×6ræÖF6‚‚ö6öÇVÖâ²r%Óòƒó¥´Õ¦×£Ó•õÒµÅÂâ“ò…´Õ¦×£Ó•õÒ²•²r%Óòƒó¦öbÆFöW2æ÷BW†—7B’ö’¢ÇÂ×6ræÖF6‚‚õ²r%Ò…´Õ¦×£Ó•õÒ²•²r%Ò6öÇVÖâö’“°¢&WGW&âÒòÕ³Ò¢çVÆÃ°¢×Ð¢òò'Väfâ‡–ÆöB’Óâ7W&6RF†Væ&ÆR&W6öÇf–ærFò·¶FFÂW'&÷'×Òà¢òòöâÖ—76–ærÖ6öÇVÖâW'&÷"—B7G&—2F†B6öÇVÖâæB&WG&–W2âF†Rf–æÀ¢òò&W76'&–W27G&—VDÖ–w&F–öä6öÇ2‡W6W"ÖFF6öÇVÖç2öæÇ’’6ò6ÆÆW'26à¢òòv&âF†BF†÷6RfÇVW2vW&RäõB6fVB„D"Ö–w&F–öâ7F–ÆÂVæF–ær’à¢gVæ7F–öâ6%w&—FU&WG'’‡–ÆöBÂ'VäfâÂ÷7G&—VB’·°¢÷7G&—VBÒ÷7G&—VBÇÂµÓ°¢&WGW&â'Väfâ‡–ÆöB’çF†Vâ†gVæ7F–öâ‡&W7’·°¢f"6öÂÒÖ—76–æt6öÄg&öÔW'"‡&W7æW'&÷"“°¢–b†6öÂbbö&¦V7Bç&÷F÷G—Ræ†4÷vå&÷W'G’æ6ÆÂ‡–ÆöBÂ6öÂ’’·°¢f""Ò··×Ó°¢f÷"‡f"²–â–ÆöB’·²–b†²ÓÒ6öÂbbö&¦V7Bç&÷F÷G—Ræ†4÷vå&÷W'G’æ6ÆÂ‡–ÆöBÂ²’’%¶µÒÒ–ÆöE¶µÓ²×Ð¢f"æW‡BÒ…4”ÄTåEõ5E$•ô4ôÅ2æ–æFW„öb†6öÂ’ÓÒÓ’ò÷7G&—VB¢÷7G&—VBæ6öæ6B…¶6öÅÒ“°¢&WGW&â6%w&—FU&WG'’‡"Â'VäfâÂæW‡B“°¢×Ð¢–b…÷7G&—VBæÆVæwF‚’&W7ç7G&—VDÖ–w&F–öä6öÇ2Ò÷7G&—VC°¢&WGW&â&W7°¢×Ò“°¢×Ð ¢gVæ7F–öâÆöD¶æ÷väæÖW2‚’·°¢f"ÒfWF6‚‚röWfVçG2æ§6öâr’çF†Vâ†gVæ7F–öâ‡"’·²&WGW&â"æ§6öâ‚“²×Ò’çF†Vâ†gVæ7F–öâ†B’·°¢&WGW&â‚†BbbBæWfVçG2’ÇÂµÒ“°¢×Ò’æ6F6‚†gVæ7F–öâ‚’·²&WGW&âµÓ²×Ò“°¢f""Ò6"æg&öÒ‚vÖçVÅöWfVçG2r’ç6VÆV7B‚v–BÆæÖRÆ6—G’ÆÆö6F–öâÇ7F'EöFFRÆFFU÷7G"r’çF†Vâ†gVæ7F–öâ‡"’·°¢&WGW&â‚‡"bb"æFF’ÇÂµÒ“°¢×Ò“°¢&WGW&â&öÖ—6RæÆÂ…·Â%Ò’çF†Vâ†gVæ7F–öâ†’·°¢ö¶æ÷väæÖU6÷W&6RÒ··×Ó²ö¶æ÷vä¶W—2Ò··×Ó²ö¶æ÷vå&V2Ò··×Ó°¢gVæ7F–öâ&VÖVÖ&W"†RÂ7&2’·°¢f"&V2Ò·²æÖS¢RææÖRÇÂrrÂÆö6F–öã¢RæÆö6F–öâÇÂRæ6—G’ÇÂrrÂFFU÷7G#¢RæFFU÷7G"ÇÂrr×Ó°¢f"âÒ†RææÖRÇÂrr’çFôÆ÷vW$66R‚’çG&–Ò‚“°¢–b†â’·²ö¶æ÷väæÖU6÷W&6U¶åÒÒ7&3²ö¶æ÷vå&V5¶åÒÒ&V3²×Ð¢f"²ÒGW¶W”öb†R“°¢–b†²’·²–b‚ö¶æ÷vä¶W—5¶µÒÇÂ7&2æ–æFW„öb‚vÖçVÂr’ÓÓÒ’ö¶æ÷vä¶W—5¶µÒÒ7&3²–b‚ö¶æ÷vå&V5¶µÒ’ö¶æ÷vå&V5¶µÒÒ&V3²×Ð¢×Ð¢³Òæf÷$V6‚†gVæ7F–öâ†R’·²&VÖVÖ&W"†RÂv6FÆörr“²×Ò“°¢³Òæf÷$V6‚†gVæ7F–öâ†R’·²&VÖVÖ&W"†RÂvÖçVÃ¢r²Ræ–B“²×Ò“°¢ö¶æ÷väæÖW2Òö&¦V7Bæ¶W—2…ö¶æ÷väæÖU6÷W&6R“°¢&WGW&âö¶æ÷väæÖW3°¢×Ò“°¢×Ð¢òò&WGW&ç2çVÆÂ–bæÖR—2f–æRÂ÷"âö&¦V7BFW67&–&–ærF†R6öæfÆ–7@¢òò†–æ6ÂâF†RÖF6†VBWfVçBw2FWF–Ç2f÷"6ÆV"ÖW76vR’à¢òò6VÆd–B÷F–öæÂ(	Bv†VâVF—F–ærÂ–væ÷&W2ÖF6‚v–ç7BF†R&÷r&V–ærVF—FVBà¢gVæ7F–öâf–æDGWÆ–6FR†æÖRÂ6VÆd–BÂò’·°¢f"âÒ†æÖRÇÂrr’çFôÆ÷vW$66R‚’çG&–Ò‚“°¢–b‚ö¶æ÷väæÖU6÷W&6R’&WGW&âçVÆÃ°¢f"7&2Òâòö¶æ÷väæÖU6÷W&6U¶åÒ¢çVÆÃ²òò’W†7BæÖRÖF6€¢f"&V2Ò7&2òö¶æ÷vå&V5¶åÒ¢çVÆÃ°¢–b‚7&2bbò’·²òò"’gW§§’æÖR¶6—G’·–V ¢f"²ÒGW¶W”öb†ò“°¢–b†²’·²7&2Òö¶æ÷vä¶W—5¶µÒÇÂçVÆÃ²&V2Ò7&2òö¶æ÷vå&V5¶µÒ¢çVÆÃ²×Ð¢×Ð¢–b‚7&2’&WGW&âçVÆÃ°¢–b‡6VÆd–Bbb7&2ÓÓÒvÖçVÃ¢r²6VÆd–B’&WGW&âçVÆÃ°¢&WGW&â·²æÖUöÆ÷vW#¢âÂ6÷W&6S¢7&2Â&V3¢&V2ÇÂçVÆÂ×Ó°¢×Ð¢òò%DTD’…f–VææÂW7G&–+rö7Fö&W"#Ž(	33Â##b’"f÷"GWÖW76vW2à¢gVæ7F–öâGWÆ&VÂ†GW’·°¢f""ÒGWbbGWç&V3²–b‚"’&WGW&ârs°¢f"&—G2Ò·"æÆö6F–öâÂ"æFFU÷7G%Òæf–ÇFW"„&ööÆVâ’æ¦ö–â‚r+rr“°¢&WGW&â‡"ææÖRÇÂrr’²†&—G2òr‚r²&—G2²r’r¢rr“°¢×Ð¢gVæ7F–öâ—4GWÆ–6FTæÖR†æÖRÂ6VÆd–BÂò’·²&WGW&âf–æDGWÆ–6FR†æÖRÂ6VÆd–BÂò“²×Ð ¢gVæ7F–öâGF6„FDWfVçD†æFÆW'2†f÷&ÒÂVÖ–Â’·°¢òòv&ÒF†RGWÆ–6FRÖæÖR66†R6òF†R7V&Ö—B†æFÆW"6â7–æ6‡&öæ÷W6Ç¢òò6†V6²v—F†÷WBâW‡G&&÷VæB×G&—à¢ÆöD¶æ÷väæÖW2‚“°¢òòf–ÆÂg&öÒU$Â(	B67&Rf–W†æ’²W‡G&7Bf–GW7BÂ–âö’÷fW@¢f"f–ÆÄ'FâÒf÷&ÒçVW'•6VÆV7F÷"‚r6f–ÆÂÖg&öÒ×W&ÂÖ'Fâr“°¢f"f–ÆÄÖWFÒf÷&ÒçVW'•6VÆV7F÷"‚r6f–ÆÂÖg&öÒ×W&ÂÖÖWFr“°¢–b†f–ÆÄ'Fâ’·°¢f–ÆÄ'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"W&Ä–çÒf÷&ÒçVW'•6VÆV7F÷"‚v–çWE¶æÖSÒ'W&Â%Òr“°¢f"W&ÂÒ‡W&Ä–ççfÇVRÇÂrr’çG&–Ò‚“°¢–b‚õæ‡GG3ó¥ÅÂõÅÂòö’çFW7B‡W&Â’’·°¢f–ÆÄÖWFçFW‡D6öçFVçBÒu7FRâ‡GG¢òò÷"‡GG3¢òòU$Âf—'7Bâs°¢&WGW&ã°¢×Ð¢f–ÆÄ'FâæF—6&ÆVBÒG'VS²f–ÆÄ'FâçFW‡D6öçFVçBÒu67&–æ~(
bs°¢f–ÆÄÖWFçFW‡D6öçFVçBÒtfWF6†–ærF†RvRf–W†ÂF†Vâ7G'V7GW&–ær—Bv—F‚’†wBÓRãB’âW7VÆÇ’ÅÇS#3C6V6öæG2âs°¢6"æWF‚ævWE6W76–öâ‚’çF†Vâ†gVæ7F–öâ‡"’·°¢f"Fö¶VâÒ"bb"æFFbb"æFFç6W76–öâbb"æFFç6W76–öâæ66W75÷Fö¶Vã°¢f"÷f‚Ò·²t6öçFVçBÕG—Rs¢vÆ–6F–öâö§6öâr×Ó°¢–b‡Fö¶Vâ’÷f…²tWF†÷&—¦F–öâuÒÒt&V&W"r²Fö¶Vã°¢f"CÒFFRææ÷r‚“°¢fWF6‚‚rö’÷fWBrÂ·°¢ÖWF†öC¢uõ5BrÀ¢†VFW'3¢÷f‚À¢&öG“¢¥4ôâç7G&–æv–g’‡·²W&Ã¢W&Â×Ò¢×Ò’çF†Vâ†gVæ7F–öâ‡&W2’·°¢&WGW&â&W2æ§6öâ‚’çF†Vâ†gVæ7F–öâ†¢’·²&WGW&â·&W2ç7FGW2Â¥Ó²×Ò“°¢×Ò’çF†Vâ†gVæ7F–öâ‡—"’·°¢f–ÆÄ'FâæF—6&ÆVBÒfÇ6S²f–ÆÄ'FâçFW‡D6öçFVçBÒtf–ÆÂg&öÒU$Âs°¢f"7BÒ—%³ÒÂFFÒ—%³Ó°¢–b‡7BÓÒ#’·°¢f–ÆÄÖWFçFW‡D6öçFVçBÒt6÷VÆFåÅÇS#—B67&R‚r²7B²r“¢r²†FFbbFFæW'&÷"ÇÂwVæ¶æ÷vâr“°¢&WGW&ã°¢×Ð¢f"bÒFFæf–VÆG2ÇÂ··×Ó°¢òòöæÇ’f–ÆÂV×G’–çWG2'’FVfVÇB(	BæWfW"6Æö&&W"v†BW6W"G—V@¢f"&W÷'BÒÇ”W‡G&7EFôf÷&Ò†f÷&ÒÂbÂ·²÷fW'w&—FS¢fÇ6R×Ò“°¢f"GW"ÒÖF‚ç&÷VæB‚„FFRææ÷r‚’ÒC’ò“°¢f"æ÷FRÒtf–ÆÆVBr²&W÷'Bæf–ÆÆVB²röbr²&W÷'BçF÷FÂ²rf–VÆG2–âr²GW"²w2r°¢‡&W÷'Bç6¶—VBòr‚r²&W÷'Bç6¶—VB²r6¶—VB(	BÇ&VG’†BfÇVW2’âr¢râr’°¢rÅÇS#fÅÇVfSbF÷V&ÆRÖ6†V6²F†RFFRbÆö6F–öâ(	B67&W'2ögFVâ&VBF†VÒw&öæs²–÷R6âf—‚F†RFFRç’F–ÖR–âFWF–Ç2ÅÇS#“"VF—Bâs°¢–b†FFæFVw&FVB’·°¢æ÷FR³Òr„’7G'V7GW&–ærv2Væf–Æ&ÆR(	BW6VBF†R67&VBvRv—F‚&6–2W‡G&7F–öâÂ6òÆV6RF÷V&ÆRÖ6†V6²F†Rf–VÆG2â’s°¢×Ð¢f–ÆÄÖWFçFW‡D6öçFVçBÒæ÷FS°¢×Ò’æ6F6‚†gVæ7F–öâ†W'"’·°¢f–ÆÄ'FâæF—6&ÆVBÒfÇ6S²f–ÆÄ'FâçFW‡D6öçFVçBÒtf–ÆÂg&öÒU$Âs°¢f–ÆÄÖWFçFW‡D6öçFVçBÒtæWGv÷&²W'&÷#¢r²W'"æÖW76vS°¢×Ò“°¢×Ò“°¢×Ò“°¢×Ð ¢òòW‡G&7Bg&öÒ7FVBVÖ–À¢f"W‡G&7D'FâÒf÷&ÒçVW'•6VÆV7F÷"‚r77FRÖW‡G&7BÖ'Fâr“°¢f"6ÆV$'FâÒf÷&ÒçVW'•6VÆV7F÷"‚r77FRÖ6ÆV"Ö'Fâr“°¢f"7FT&VÒf÷&ÒçVW'•6VÆV7F÷"‚r77FRÖVÖ–Â×FW‡Br“°¢f"ÖWFÒf÷&ÒçVW'•6VÆV7F÷"‚r77FRÖW‡G&7BÖÖWFr“°¢W‡G&7D'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"FW‡BÒ7FT&VçfÇVRÇÂrs°¢f"G&–ÖÖVBÒFW‡BçG&–Ò‚“°¢–b‡G&–ÖÖVBæÆVæwF‚Â’·²ÖWFçFW‡D6öçFVçBÒtæ÷F†–ærFòW‡G&7Bg&öÒ–WBâs²&WGW&ã²×Ð¢òò7FVB§W7BÆ–æ³òÆö6ÂFW‡B×'6–ær6âwB&VBvR(	B&÷WFR—BFð¢òòF†R&VÂ67&W"„f–ÆÂg&öÒU$Â(i"ö’÷fWB’6òæÖRöFFRöÆö6F–öâf–ÆÂà¢–b‚õæ‡GG3ó¥ÅÂõÅÂõÅÅ2²Bö’çFW7B‡G&–ÖÖVB’’·°¢f"W&Ä–ç"Òf÷&ÒçVW'•6VÆV7F÷"‚v–çWE¶æÖSÒ'W&Â%Òr“°¢–b‡W&Ä–ç"’W&Ä–ç"çfÇVRÒG&–ÖÖVC°¢–b†f–ÆÄ'Fâ’·°¢ÖWFçFW‡D6öçFVçBÒuF†EÅÇS#—2Æ–æ²(	B67&–ærF†RvR‡6VRF†RU$Â&÷r&÷fRž(
bs°¢f–ÆÄ'Fâæ6Æ–6²‚“°¢&WGW&ã°¢×Ð¢×Ð¢f"W‡G&7FVBÒW‡G&7Dg&öÔVÖ–Â‡FW‡B“°¢f"&W÷'BÒÇ”W‡G&7EFôf÷&Ò†f÷&ÒÂW‡G&7FVBÂ·²÷fW'w&—FS¢fÇ6R×Ò“°¢–b‡&W÷'BçF÷FÂÓÓÒ’·°¢ÖWFçFW‡D6öçFVçBÒt6÷VÆFåÅÇS#—Bf–æBæÖRòFFRòÆö6F–öâòU$Â–âF†BFW‡Bâf–ÆÂF†Rf÷&ÒÖçVÆÇ’âs°¢&WGW&ã°¢×Ð¢ÖWFçFW‡D6öçFVçBÒtW‡G&7FVBr²&W÷'Bæf–ÆÆVB²röbr²&W÷'BçF÷FÂ²rf–VÆG2r²‡&W÷'Bç6¶—VBòr‚r²&W÷'Bç6¶—VB²r6¶—VB&V6W6Rf–VÆG2vW&RÇ&VG’f–ÆÆVB’âr¢râr“°¢×Ò“°¢6ÆV$'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²7FT&VçfÇVRÒrs²ÖWFçFW‡D6öçFVçBÒrs²×Ò“° ¢òò6æ6VÀ¢f÷&ÒçVW'•6VÆV7F÷"‚u¶FFÖ6æ6VÅÒr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²f÷&Òç&VÖ÷fR‚“²×Ò“° ¢òòFFRf–VÆC¢fÆW†–&ÆRFW‡B²6Æ–6²×FòÖ÷Vâ6ÆVæF"‡6–ævÆRF’÷"&ævR’à¢v—&TFFU–6¶W"†f÷&ÒçVW'•6VÆV7F÷"‚ræFFR×–6²r’“° ¢òò7V&Ö—B(i"ÖçVÅöWfVçG2–ç6W'@¢f÷&ÒæFDWfVçDÆ—7FVæW"‚w7V&Ö—BrÂgVæ7F–öâ†Wb’·°¢Wbç&WfVçDFVfVÇB‚“°¢f"fBÒæWrf÷&ÔFF†f÷&Ò“°¢f"&÷rÒ·°¢æÖS¢†fBævWB‚væÖRr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’À¢FFU÷7G#¢†fBævWB‚vFFU÷7G"r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’À¢Æö6F–öã¢†fBævWB‚vÆö6F–öâr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢&Vv–öã¢†fBævWB‚w&Vv–öâr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢G—S¢†fBævWB‚wG—Rr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢&–÷&—G“¢†fBævWB‚w&–÷&—G’r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢v‡“¢†fBævWB‚wv‡’r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢W&Ã¢æ÷&ÕW&Â†fBævWB‚wW&Âr’’À¢7V¶W#¢†fBævWB‚w7V¶W"r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢7FGW5÷Fw3¢æ÷&ÖÆ—¦U7FvUFw2†fBævWDÆÂ‚w7FGW5÷Fw2r’’À¢&÷WC¢†fBævWB‚v&÷WBr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢fö7W5ö&V3¢†fBævWB‚vfö7W5ö&V2r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢G—–6ÅöGFVæFVW3¢†fBævWB‚wG—–6ÅöGFVæFVW2r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢7V¶–æu÷&÷WFS¢†fBævWB‚w7V¶–æu÷&÷WFRr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢6öçF7Eö–æfó¢†fBævWB‚v6öçF7Eö–æfòr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢FVFÆ–æS¢†fBævWB‚vFVFÆ–æRr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢GFVæFVUö6÷VçC¢†fBævWB‚vGFVæFVUö6÷VçBr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢VF–Væ6U÷G—S¢†fBævWB‚vVF–Væ6U÷G—Rr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢&–6–æs¢†fBævWB‚w&–6–ærr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢7E÷7V¶W'3¢†fBævWB‚w7E÷7V¶W'2r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢ÖVWF–æuöf÷&ÖG3¢†fBævWB‚vÖVWF–æuöf÷&ÖG2r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢GFVæE÷fW&F–7C¢†fBævWB‚vGFVæE÷fW&F–7Br’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢÷7FÖ÷'FVÓ¢†fBævWB‚w÷7FÖ÷'FVÒr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢•÷Fõ÷Æ“¢†fBævWB‚w•÷Fõ÷Æ’r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢fVçVS¢†fBævWB‚wfVçVRr’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢6—G“¢†fBævWB‚v6—G’r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢6÷VçG'“¢†fBævWB‚v6÷VçG'’r’ÇÂrr’çFõ7G&–ær‚’çG&–Ò‚’ÇÂçVÆÂÀ¢6VVC¢G&”&ööÂ†fBævWB‚w6VVBr’’À¢W&vVçC¢G&”&ööÂ†fBævWB‚wW&vVçBr’’À¢7&VFVEö'“¢VÖ–À¢×Ó°¢–b‚&÷rææÖR’·²ÆW'B‚tæÖR—2&WV—&VB†—B6†÷w2öâF†R6ÆVæF"’r“²&WGW&ã²×Ð¢òòFFR—2fÆW†–&ÆRg&VR×FW‡Bf–VÆB‡'6VB7WW"ÖÆö÷6VÇ’'¢òòFW&—fTFFW4g&öÕFW‡B’F†BF†R6ÆVæF"÷W6âÇ6òf–ÆÂâv†VâF†P¢òò6ÆVæF"—2W6VB—B7F6†W2W†7B•4ò7F'BöVæBöâF†R–çWBw0¢òòFF6WB(	BG'W7BF†÷6S²÷F†W'v—6R'6Rv†FWfW"v2G—VBà¢f"öG4VÂÒf÷&ÒçVW'•6VÆV7F÷"‚u¶æÖSÒ&FFU÷7G"%Òr“°¢f"ö6Å2ÒöG4VÂbböG4VÂævWDGG&–'WFR‚vFF×7F'BÖ—6òr“°¢f"ö6ÄRÒöG4VÂbböG4VÂævWDGG&–'WFR‚vFFÖVæBÖ—6òr“°¢–b‚&÷ræFFU÷7G"’&÷ræFFU÷7G"ÒtFFRD$Bs°¢–b…ö6Å2’·°¢&÷rç7F'EöFFRÒö6Å3°¢&÷ræVæEöFFRÒö6ÄRÇÂö6Å3°¢×ÒVÇ6R·°¢f"FW&—fVBÒFW&—fTFFW4g&öÕFW‡B‡&÷ræFFU÷7G"“°¢–b†FW&—fVBç7F'EöFFR’&÷rç7F'EöFFRÒFW&—fVBç7F'EöFFS°¢–b†FW&—fVBæVæEöFFR’&÷ræVæEöFFRÒFW&—fVBæVæEöFFS°¢×Ð¢òòF†RW6W"G—VB&VÂFFRF†R'6W"6÷VÆFâwB&VB†Rærâ%2##b"À¢òò&æW‡B7&–ær"’(i"7F'EöFFR7F—2çVÆÂæBF†RWfVçB6–ÆVçFÇ’æWfW ¢òò6†÷w2öâF†R6ÆVæF"ò”6ÂâfÆr—B6òvR6âv&âöâ6fRà¢f"Vç'6VDFFRÒ‡&÷ræFFU÷7G"ÓÒtFFRD$Br’bb&÷rç7F'EöFFS°¢òò–V"—2&VGVæFçBv—F‚F†RFFR(	B7G&—G&–Æ–ær–V"öâ6fRà¢&÷rææÖRÒ7G&—G&–Æ–æu–V"‡&÷rææÖR“°¢òòWFòÖfÆrv†öWfW"FG2F†RWfVçB2–çFW&W7FVBÂ6ò—BÆæG2–à¢òòævVÆw2VWVR‚&Ç’f÷"ÖR"’–ÖÖVF–FVÇ’(	BU„4UB6ÆW2×7W÷'@¢òò7Ffb„‡W&ÆW’ôævVÆ’Âv†ò'VâF†RG&6¶W"'WBFöâwBGFVæBà¢f"öFFW"ÒvWD6öÆÆ$æÖR‚’ÇÂ†VÖ–Âòf—'7DæÖTg&öÔVÖ–Â†VÖ–Â’¢rr’ÇÂuFVÒs°¢&÷ræ–çFW&W7FVBÒ—57W÷'EW'6öâ…öFFW"’òµÒ¢µöFFW%Ó°¢òò„$BGWÆ–6FRÖæÖRwV&B(	B66RÖ–ç6Vç6—F—fR7&÷726FÆör²ÖçVÅöWfVçG2à¢òòæò6öæf—&Ò‚’W66R†F6ƒ¢GWÆ–6FW2ÆæB–âF†R6ÆVæF"2Gvð¢òò6W&FRVçG&–W2v—F‚GvòT”G2Âv†–6‚&öGV6W2F÷V&ÆR×&VæFW&V@¢òòWfVçG2–â7V'67&–&VB6ÆVæF'2âF†RVæ—VR–æFW‚öâF†RD ¢òò‡67&—G2ó##bÓRÓ#eöFVGWöÖçVÅöWfVçG2ç7Â’—2F†Rf–æÂFVfVç6Rà¢òòW†7BÖæÖRÖF6‚â6†÷rt„”4‚WfVçB†Æö6F–öâ²FFR’6òF†RW6W"6à¢òòFVÆÂ–b—Bw2G'VÇ’F†R6ÖRÂæBÆWBF†VÒ÷fW'&–FR–b—Bw2vVçV–æVÇ¢òòF–ffW&VçB†Rærâ6ÖRæÖRÂF–ffW&VçB6—G’÷–V"’(	BF†RD"Væ—VR–æFW€¢òò—2F†Rf–æÂ&6·7F÷à¢f"GWÒf–æDGWÆ–6FR‡&÷rææÖR“°¢–b†GW’·°¢f"v†W&RÒGWç6÷W&6RÓÓÒv6FÆörròwF†R&7F–4&ÇVR6FÆörr¢w–÷W"ÖçVÂWfVçG2s°¢f"Æ&ÂÒGWÆ&VÂ†GW’ÇÂ‚r"r²&÷rææÖR²r"r“°¢–b‚6öæf—&Ò†Æ&Â²r—2Ç&VG’–âr²v†W&R²râ–bF†EÅÇS#—2F†R6ÖRWfVçBÂ÷Vâ—B–ç7FVBöbFF–ærGWÆ–6FRâFB—Bç—v“òr’’·°¢&WGW&ã°¢×Ð¢×Ð¢òògW§§’wV&B(	B6ÖR6÷&RæÖR²6—G’²–V"2âW†—7F–ærWfVçB†Rærà¢òò.(
b##b"g2.(
b„•BVF—F–öâ’"’âÆ–¶VÇ’F†R6ÖRWfVçC²ÆWBF†RW6W ¢òò÷fW'&–FR–â66R—Bw2vVçV–æVÇ’F–ffW&VçBVF—F–öâà¢f"gW§§”GWÒGWòçVÆÂ¢f–æDGWÆ–6FR†çVÆÂÂçVÆÂÂ&÷r“°¢–b†gW§§”GW’·°¢f"fÆ&ÂÒGWÆ&VÂ†gW§§”GW’ÇÂvâWfVçBs°¢–b‚6öæf—&Ò‚uF†—2Æöö·2Æ–¶RGWÆ–6FRöbr²fÆ&Â²rÇ&VG’–âr²†gW§§”GWç6÷W&6RÓÓÒv6FÆörròwF†R6FÆörr¢w–÷W"ÖçVÂWfVçG2r’²r(	B6ÖRæÖRÂ6—G’æB–V"âFB—Bç—v“òr’’·°¢&WGW&ã°¢×Ð¢×Ð¢f"7V&Ö—D'FâÒf÷&ÒçVW'•6VÆV7F÷"‚v'WGFöâç&–Ö'•·G—SÒ'7V&Ö—B%Òr“°¢7V&Ö—D'FâæF—6&ÆVBÒG'VS²7V&Ö—D'FâçFW‡D6öçFVçBÒu6f–æ~(
bs°¢6%w&—FU&WG'’‡&÷rÂgVæ7F–öâ‡’·²&WGW&â6"æg&öÒ‚vÖçVÅöWfVçG2r’æ–ç6W'B‡’ç6VÆV7B‚“²×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢7V&Ö—D'FâæF—6&ÆVBÒfÇ6S²7V&Ö—D'FâçFW‡D6öçFVçBÒtFBWfVçBs°¢–b‡&W7æW'&÷"’·°¢òò#3SRÒVæ—VU÷f–öÆF–öââ†—Bv†VâF†RD"Væ—VR–æFW‚6F6†W0¢òò&6RvRÖ—76VB‡Gvò6öæ7W'&VçB–ç6W'G2öbF†R6ÖRæÖR’à¢–b‡&W7æW'&÷"æ6öFRÓÓÒs#3SRrÇÂöGWÆ–6FR¶W’fÇVWÇVæ—VRö’çFW7B‡&W7æW'&÷"æÖW76vRÇÂrr’’·°¢7FGW2‚r"r²&÷rææÖR²r"Ç&VG’W†—7G2â&Vg&W6†–ærF†RGWÆ–6FR66†^(
brÂwv&âr“°¢ÆöD¶æ÷väæÖW2‚“°¢&WGW&ã°¢×Ð¢7FGW2‚tFBf–ÆVC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“°¢&WGW&ã°¢×Ð¢f"æWu&÷rÒ‡&W7æFFbb&W7æFF³Ò’ÇÂ&÷s°¢f÷&Òç&VÖ÷fR‚“°¢f"6&BÒ'V–ÆDÖçVÄ6&B†æWu&÷rÂVÖ–Â“°¢F÷4w&–Bæ–ç6W'D&Vf÷&R†6&BÂF÷4w&–Bæf—'7D6†–ÆB“°¢v—&TÖçVÄ6&B†6&BÂVÖ–Â“°¢WFFT÷46÷VçB‚“°¢&Vw&÷W÷4'”ÖöçF‚‚“²òò6Æ÷BF†RæWr6&B–çFò—G2ÖöçF‚6V7F–öà¢Ç”f–ÇFW'2‚“°¢ÆöD¶æ÷väæÖW2‚“²òò¶VWF†RGW–æFW‚g&W6€¢–b‡Vç'6VDFFR’·°¢7FGW2‚tFFVB"r²æWu&÷rææÖR²r"(	B'WB’6÷VÆFî(	—B&VBFFRg&öÒ"r²&÷ræFFU÷7G"²r"Â6ò—Bvöî(	—B6†÷röâF†R6ÆVæF"VçF–Â–÷RVF—B—BFòFFRÆ–¶R%6WFVÖ&W""Â##b"ârÂwv&âr“°¢×ÒVÇ6R·°¢fÆ6„ö²‚tWfVçBFFVBr“°¢×Ð¢×Ò“°¢×Ò“°¢×Ð ¢òò)H)H”6ÂW‡÷'B)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢gVæ7F–öâ–6ÄW66R‡2’·°¢&WGW&â7G&–ær‡2ÓÒçVÆÂòrr¢2¢ç&WÆ6R‚õÅÅÅÂörÂuÅÅÅÅÅÅÅÂr¢ç&WÆ6R‚ó²örÂuÅÅÅÃ²r¢ç&WÆ6R‚òÂörÂuÅÅÅÂÂr¢ç&WÆ6R‚õÅÆâörÂuÅÅÅÆâr“°¢×Ð ¢gVæ7F–öâ–74FFR†—6ò’·°¢–b‚—6ò’&WGW&ârs°¢&WGW&â—6òç&WÆ6R‚òÒörÂrr“°¢×Ð ¢òòFBöæRF’Fò•••’ÔÔÒÔDB„”52EDTäB—2W†6ÇW6—fRf÷"ÆÂÖF’WfVçG2¢gVæ7F–öâ–74FFUÇW3†—6ò’·°¢–b‚—6ò’&WGW&ârs°¢f"BÒæWrFFR†—6ò²uC££¢r“°¢Bç6WEUD4FFR†BævWEUD4FFR‚’²“°¢&WGW&âBçFô•4õ7G&–ær‚’ç6Æ–6RƒÃ’ç&WÆ6R‚òÒörÂrr“°¢×Ð ¢gVæ7F–öâ'V–ÆD–74f÷%6fVB†WfVçG2Â7FFTÖÂÖçVÄWfVçG2’·°¢f"æ÷rÒæWrFFR‚“°¢f"GG7F×Òæ÷rçFô•4õ7G&–ær‚’ç&WÆ6R‚õ²Ó¥ÒörÂrr’ç6Æ–6RƒÂR’²u¢s°¢f"Æ–æW2Ò°¢t$Tt”ã¥d4ÄTäD"rÀ¢udU%4”ôã£"ãrÀ¢u$ôD”C¢Òòô&7F–4&ÇVRòôWfVçBG&6¶W"òôTârÀ¢t4Å44ÄS¤u$Ttõ$”ârÀ¢tÔUD„ôC¥T$Ä•4‚rÀ¢u‚Õu"Ô4ÄäÔS¤&7F–4&ÇVR+r6fVBWfVçG2p¢Ó°¢gVæ7F–öâW6„WfVçB†WbÂ7BÂV–B’·°¢f"7F'D—6òÒWbç7F'EöFFRÇÂ‡7Bbb7Bç7F'EöFFR’ÇÂçVÆÃ°¢f"VæD—6òÒWbæVæEöFFRÇÂ7F'D—6ó°¢f"FW62ÒµÓ°¢–b†Wbçv‡’’FW62çW6‚†Wbçv‡’“°¢–b‡7Bbb7Bææ÷FW2’FW62çW6‚‚tæ÷FW3¢r²7Bææ÷FW2“°¢–b‡7Bbb7Bç7V¶W"’FW62çW6‚‚u7V¶W#¢r²7Bç7V¶W"“°¢–b‡7Bbb7Bç7FGW2’FW62çW6‚‚u7FGW3¢r²7Bç7FGW2“°¢–b†Wbç&–÷&—G’ÇÂ‡7Bbb7Bç&–÷&—G•ö÷fW'&–FR’’FW62çW6‚‚u&–÷&—G“¢r²‡7Bbb7Bç&–÷&—G•ö÷fW'&–FRÇÂWbç&–÷&—G’ÇÂrr’“°¢f"FW67&—F–öâÒFW62æ¦ö–â‚uÅÆâr“°¢Æ–æW2çW6‚‚t$Tt”ã¥dUdTåBr“°¢Æ–æW2çW6‚‚uT”C¢r²V–B“°¢Æ–æW2çW6‚‚tEE5DÕ¢r²GG7F×“°¢–b‡7F'D—6ò’Æ–æW2çW6‚‚tEE5D%CµdÅTSÔDDS¢r²–74FFR‡7F'D—6ò’“°¢–b†VæD—6ò’Æ–æW2çW6‚‚tEDTäCµdÅTSÔDDS¢r²–74FFUÇW3†VæD—6ò’“°¢Æ–æW2çW6‚‚u5TÔÔ%“¢r²–6ÄW66R†WbææÖRÇÂrr’“°¢–b†WbæÆö6F–öâ’Æ–æW2çW6‚‚tÄô4D”ôã¢r²–6ÄW66R†WbæÆö6F–öâ’“°¢–b†FW67&—F–öâ’Æ–æW2çW6‚‚tDU45$•D”ôã¢r²–6ÄW66R†FW67&—F–öâ’“°¢–b†WbçW&Â’Æ–æW2çW6‚‚uU$Ã¢r²WbçW&Â“°¢–b‡7Bbb7BçW&vVçB’Æ–æW2çW6‚‚t4DTtõ$”U3¥U$tTåBr“°¢Æ–æW2çW6‚‚tTäC¥dUdTåBr“°¢×Ð¢òòFVGW¢6FÆör&÷r²ÖçVÂ&÷rf÷"F†R4ÔRWfVçB†öæR†öÆF–æp¢òò7V¶–ær–æfòÂöæRGFVæF–ær’×W7Bæ÷BF÷V&ÆR–âF†RW‡÷'FVB6ÆVæF"à¢òò¶W’Òæ÷&ÖÆ—¦VBæÖR²7F'BFFR†FFR–æ6ÇVFVB6òF–ffW&VçBÖ6—G¢òòVF—F–öç2öb6W&–W2FöâwBfÇ6RÖÖF6‚’à¢f"÷6VVä–72Ò··×Ó°¢gVæ7F–öâö–74¶W’†æÖRÂ7F'D—6ò’·°¢f"2Ò7G&–ær†æÖRÇÂrr’çFôÆ÷vW$66R‚’ç&WÆ6R‚õµæ×£Ó’ÒörÂrr¢ç&WÆ6R‚õÅÆ"ƒ#ÅÆEÅÆGÇW6Ææ÷'F‚ÖW&–6ÆWW&÷WÆVF—F–öçÇF†WÆæçVÂ•ÅÆ"örÂrr¢ç&WÆ6R‚õÅÇ2²örÂrr’çG&–Ò‚“°¢&WGW&â2²wÂr²7G&–ær‡7F'D—6òÇÂrr“°¢×Ð¢†WfVçG2ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†Wb’·°¢f"7BÒ7FFTÖ¶WbæçVÕÓ°¢–b‚7BÇÂ7Bç6fVB’&WGW&ã°¢f"²Òö–74¶W’†WbææÖRÂWbç7F'EöFFR“°¢–b…÷6VVä–75¶µÒ’&WGW&ã°¢÷6VVä–75¶µÒÒ°¢W6„WfVçB†WbÂ7BÂvWfVçBÒr²WbæçVÒ²t&7F–6&ÇVRÖWfVçB×G&6¶W"r“°¢×Ò“°¢òòÖçVÂWfVçG3¢–æ6ÇVFRÆÂöbF†VÒ‡6–æ6RFF–ærÖçVÆÇ’—26fVBÖ–çFVçB7F–öâ¢†ÖçVÄWfVçG2ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†ÖWb’·°¢–b‚ÖWbç7F'EöFFR’&WGW&ã°¢f"²Òö–74¶W’†ÖWbææÖRÂÖWbç7F'EöFFR“°¢–b…÷6VVä–75¶µÒ’&WGW&ã°¢÷6VVä–75¶µÒÒ°¢W6„WfVçB‡·°¢æÖS¢ÖWbææÖRÂÆö6F–öã¢ÖWbæÆö6F–öâÂv‡“¢ÖWbçv‡’ÂW&Ã¢ÖWbçW&ÂÀ¢7F'EöFFS¢ÖWbç7F'EöFFRÂVæEöFFS¢ÖWbæVæEöFFRÇÂÖWbç7F'EöFFRÀ¢&–÷&—G“¢ÖWbç&–÷&—G¢×ÒÂçVÆÂÂvÖçVÂÒr²ÖWbæ–B²t&7F–6&ÇVRÖWfVçB×G&6¶W"r“°¢×Ò“°¢Æ–æW2çW6‚‚tTäC¥d4ÄTäD"r“°¢&WGW&âÆ–æW2æ¦ö–â‚uÅÇ%ÅÆâr’²uÅÇ%ÅÆâs°¢×Ð ¢gVæ7F–öâW‡÷'E6fVD4–72‚’·°¢&öÖ—6RæÆÂ…°¢fWF6‚‚röWfVçG2æ§6öâr’çF†Vâ†gVæ7F–öâ‡"’·²&WGW&â"æ§6öâ‚“²×Ò’À¢6"æg&öÒ‚vWfVçE÷7FFRr’ç6VÆV7B‚r¢r’À¢6"æg&öÒ‚vÖçVÅöWfVçG2r’ç6VÆV7B‚r¢r¢Ò’çF†Vâ†gVæ7F–öâ‡&W7VÇG2’·°¢f"FFÒ&W7VÇG5³Ó°¢f"7FFU&÷w2Ò‡&W7VÇG5³Òbb&W7VÇG5³ÒæFF’ÇÂµÓ°¢f"ÖçVÅ&÷w2Ò‡&W7VÇG5³%Òbb&W7VÇG5³%ÒæFF’ÇÂµÓ°¢f"7FFTÖÒ··×Ó°¢7FFU&÷w2æf÷$V6‚†gVæ7F–öâ‡"’·²7FFTÖ·"æWfVçEöçVÕÒÒ#²×Ò“°¢f"Wg2Ò†FFæWfVçG2ÇÂµÒ’æf–ÇFW"†gVæ7F–öâ†R’·²&WGW&âRç7FGW2ÓÒv&6†—fVBs²×Ò“°¢f"–72Ò'V–ÆD–74f÷%6fVB†Wg2Â7FFTÖÂÖçVÅ&÷w2“°¢f"6fVD6÷VçBÒ7FFU&÷w2æf–ÇFW"†gVæ7F–öâ‡"’·²&WGW&â"ç6fVC²×Ò’æÆVæwFƒ°¢–b‡6fVD6÷VçBÓÓÒbbÖçVÅ&÷w2æÆVæwF‚ÓÓÒ’·°¢7FGW2‚tæ÷F†–ærFòW‡÷'B–WB(	B6fRBÆV7BöæRWfVçBf—'7BârÂwv&âr“°¢&WGW&ã°¢×Ð¢f"&Æö"ÒæWr&Æö"…¶–75ÒÂ·²G—S¢wFW‡Bö6ÆVæF#¶6†'6WC×WFbÓƒ²r×Ò“°¢f"W&ÂÒU$Âæ7&VFTö&¦V7EU$Â†&Æö"“°¢f"ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vr“°¢æ‡&VbÒW&Ã²æF÷væÆöBÒv&7F–6&ÇVR×6fVBÒr²æWrFFR‚’çFô•4õ7G&–ær‚’ç6Æ–6RƒÃ’²ræ–72s°¢Fö7VÖVçBæ&öG’æVæD6†–ÆB†“²æ6Æ–6²‚“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²U$Âç&Wfö¶Tö&¦V7EU$Â‡W&Â“²ç&VÖ÷fR‚“²×ÒÂ“°¢fÆ6„ö²‚v”6ÂF÷væÆöFVB(	Br²6fVD6÷VçB²r6fVB²r²ÖçVÅ&÷w2æÆVæwF‚²rÖçVÂr“°¢×Ò“°¢×Ð ¢òò)H)Hf–WrFövvÆR„w&–Bò6ÆVæF"’)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢f"d”Uuô´U’Òv"æævVÆçf–Wrs°¢f"7W'&VçEf–WrÒvw&–Bs°¢òòF†R$WfVçG2"F"&VÖVÖ&W'2v†–6‚öbÆ—7Bò6ÆVæF"òÖ–÷RÆ7BW6VBÀ¢òò6ò&WGW&æ–ærFò—BÆæG2–÷R&6²v†W&R–÷RvW&Rà¢f"öÆ7DWfVçG57V"Òvw&–Bs° ¢f"d”UuôäÔU2Ò²v7F–öârÂv×–WfVçG2rÂv×—&öf–ÆRrÂvw&–BrÂv6ÆVæF"rÂvÖrÂwVWVRrÂwÆææW"rÂvF–öbuÓ²òòwÆæ†VBrÖW&vVB–çFòv×–WfVçG2p¢gVæ7F–öâ6WEf–Wr†æÖR’·°¢–b…d”UuôäÔU2æ–æFW„öb†æÖR’ÓÓÒÓ’æÖRÒvw&–Bs°¢òòF†RF’Ôöb'&–Vbæ÷rÆ—fW2–ç6–FR×’WfVçG2(	Bæò7FæFÆöæRF"à¢–b†æÖRÓÓÒvF–öbr’æÖRÒv×–WfVçG2s°¢òòÆææW"ÂVWVRæBF†R&öf–ÆRvR&RævVÆÖöæÇ’(	B&VF—&V7Bç–öæP¢òòVÇ6Rv†òÆæG2öâF†VÒâF†RwV&BÖGFW'2f÷"v×—&öf–ÆRr&W–öæBF†P¢òò†–FFVâÖVçRVçG'“¢â7F—f—G’&÷r&÷WB&öf–ÆRWÆöB6ÆÇ0¢òò6WEf–Wr‚v×—&öf–ÆRr’F—&V7FÇ’ÂæBv—F†÷WBF†—2—Bv÷VÆBG&÷¢òòFVÖÖFRöâ&Ææ²f–Wr„‡W&ÆW’##bÓ‚ÓR’à¢–b‚†æÖRÓÓÒwÆææW"rÇÂæÖRÓÓÒwVWVRr’b`¢v–æF÷ræ—4ævVÆW6W"bbv–æF÷ræ—4ævVÆW6W"‚’’æÖRÒvWD6öÆÆ$æÖR‚’òv×–WfVçG2r¢vw&–Bs°¢7W'&VçEf–WrÒæÖS°¢f"7F–öä†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö7F–öâr“°¢–b†7F–öä†÷7B’7F–öä†÷7Bæ†–FFVâÒæÖRÓÒv7F–öâs°¢–b†æÖRÓÓÒv7F–öârbbv–æF÷rä7F–öä6VçFW"’v–æF÷rä7F–öä6VçFW"ç6†÷r‚“°¢f"—4WfVçG5f–WrÒ†æÖRÓÓÒvw&–BrÇÂæÖRÓÓÒv6ÆVæF"rÇÂæÖRÓÓÒvÖr“°¢–b†—4WfVçG5f–Wr’öÆ7DWfVçG57V"ÒæÖS°¢Fö7VÖVçBçVW'•6VÆV7F÷$ÆÂ‚rçf–Wr×FövvÆR'WGFöå¶FF×f–WuÒr’æf÷$V6‚†gVæ7F–öâ†"’·°¢f"öâÒ"æFF6WBçf–WrÓÓÒæÖS°¢"æ6Æ74Æ—7BçFövvÆR‚v7F—fRrÂöâ“°¢"ç6WDGG&–'WFR‚v&–×6VÆV7FVBrÂöâòwG'VRr¢vfÇ6Rr“°¢×Ò“°¢òòF†RÖW&vVB$WfVçG2"F"†2æòFF×f–Wröb—G2÷vâ(	B—Bw27F—fRf÷ ¢òòå’öb—G2Æ—7Bò6ÆVæF"òÖ7V"×f–Ww2Âv†–6‚Æ—fR–â6V6öæF'¢òò7v—F6†W"6†÷vâöæÇ’v†–ÆR–÷Rw&RöâöæRöbF†VÒà¢f"FWfVçG5F"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wF"ÖWfVçG2r“°¢–b‚FWfVçG5F"’·°¢FWfVçG5F"æ6Æ74Æ—7BçFövvÆR‚v7F—fRrÂ—4WfVçG5f–Wr“°¢FWfVçG5F"ç6WDGG&–'WFR‚v&–×6VÆV7FVBrÂ—4WfVçG5f–WròwG'VRr¢vfÇ6Rr“°¢×Ð¢f"G7V&æbÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vWfVçG2×7V&æbr“°¢–b‚G7V&æb’·°¢G7V&æbæ†–FFVâÒ—4WfVçG5f–Ws°¢'&’ç&÷F÷G—Ræf÷$V6‚æ6ÆÂ‚G7V&æbçVW'•6VÆV7F÷$ÆÂ‚u¶FF×f–WuÒr’ÂgVæ7F–öâ†"’·°¢f"öâÒ"æFF6WBçf–WrÓÓÒæÖS°¢"æ6Æ74Æ—7BçFövvÆR‚v7F—fRrÂöâ“°¢"ç6WDGG&–'WFR‚v&–×6VÆV7FVBrÂöâòwG'VRr¢vfÇ6Rr“°¢×Ò“°¢×Ð¢òò6V&6‚²f–ÇFW'2&RF†RWfVçG27W&f6Rw2÷vâFööÇ2(	B†–FRF†Rv†öÆP¢òò&÷röâF†RW'6öæÂF'2„×’Æ–æWWòÆâ†VBò×’&öf–ÆR’Âv†W&P¢òòF†W&Rw2æ÷F†–ærFòf–ÇFW"â…F†R6öçG&öÇ27F’–âF†RDôÒÂ6ò&WGW&æ–æp¢òòFòWfVçG2&W7F÷&W2F†VÒv—F‚F†V—"7FFR–çF7Bâ¢f"GF÷bÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×F÷f–ÇFW'2r“°¢–b‚GF÷b’GF÷bç7G–ÆRæF—7Æ’Ò—4WfVçG5f–Wròrr¢væöæRs°¢f"Ff"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö7F—fRÖf–ÇFW'2r“°¢–b‚Ff"’Ff"ç7G–ÆRæF—7Æ’Ò—4WfVçG5f–Wròrr¢væöæRs°¢òòF†Rf–ÇFW"G&vW"—2WfVçG2ÖöæÇ’Föó²Çv—2ÆVfR—B6Æ÷6VBöâ7v—F6‚à¢f"FffBÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wFbÖG&vW"r“°¢–b‚FffB’·²FffBæ†–FFVâÒG'VS²×Ð¢f"FfgBÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Öf–ÇFW"×FövvÆRr“°¢–b‚FfgB’·²FfgBç6WDGG&–'WFR‚v&–ÖW‡æFVBrÂvfÇ6Rr“²FfgBç7G–ÆRæF—7Æ’Ò—4WfVçG5f–Wròrr¢væöæRs²×Ð¢f"rÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Öw&–Br“°¢f"2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö6ÆVæF"r“°¢f"ÒÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2ÖÖr“°¢f"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×VWVRr“°¢f"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×ÆææW"r“°¢f"BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2ÖF–öbr“°¢f"ÖRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö×–WfVçG2r“°¢f""ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö×—&öf–ÆRr“°¢–b†r’rç7G–ÆRæF—7Æ’Ò†æÖRÓÓÒvw&–Br’òrr¢væöæRs°¢f"&‚ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2×&W7VÇG2Ö†VFW"r“°¢–b‡&‚’&‚ç7G–ÆRæF—7Æ’Ò†æÖRÓÓÒvw&–Br’òrr¢væöæRs°¢–b†ÖR’ÖRæ6Æ74Æ—7BçFövvÆR‚w6†÷rrÂæÖRÓÓÒv×–WfVçG2r“°¢–b‡"’"æ6Æ74Æ—7BçFövvÆR‚w6†÷rrÂæÖRÓÓÒv×—&öf–ÆRr“°¢–b†2’2æ6Æ74Æ—7BçFövvÆR‚w6†÷rrÂæÖRÓÓÒv6ÆVæF"r“°¢–b†Ò’Òæ6Æ74Æ—7BçFövvÆR‚w6†÷rrÂæÖRÓÓÒvÖr“°¢–b‡’æ6Æ74Æ—7BçFövvÆR‚w6†÷rrÂæÖRÓÓÒwVWVRr“°¢–b‡’æ6Æ74Æ—7BçFövvÆR‚w6†÷rrÂæÖRÓÓÒwÆææW"r“°¢–b†B’Bæ6Æ74Æ—7BçFövvÆR‚w6†÷rrÂæÖRÓÓÒvF–öbr“°¢–b†æÖRÓÓÒv×–WfVçG2r’&VæFW$×”WfVçG2‚“°¢–b†æÖRÓÓÒv×—&öf–ÆRr’&VæFW$×•&öf–ÆR‚“°¢–b†æÖRÓÓÒv6ÆVæF"r’&V6Æ46ÆVæF"‚“²òò&RÖÇ’F†RÆ—fRf–ÇFW'0¢–b†æÖRÓÓÒvÖr’÷Vä÷4Ö‚“°¢–b†æÖRÓÓÒwVWVRr’&VæFW%VWVR‚“°¢–b†æÖRÓÓÒwÆææW"r’&VæFW%ÆææW"‚“°¢–b†æÖRÓÓÒvF–öbr’&VæFW$F”öb‚“°¢G'’·²Æö6Å7F÷&vRç6WD—FVÒ…d”Uuô´U’ÂæÖR“²×Ò6F6‚†R’··×Ð¢×Ð ¢v–æF÷ræ$&öö¶–æuf–WrÒ6WEf–Ws°¢gVæ7F–öâv—&Uf–WuFövvÆR‚’·°¢Fö7VÖVçBçVW'•6VÆV7F÷$ÆÂ‚rçf–Wr×FövvÆR'WGFöå¶FF×f–WuÒr’æf÷$V6‚†gVæ7F–öâ†"’·°¢òò6ÆöæR×&WÆ6RFòfö–BGWÆ–6FRÆ—7FVæW'2öâ&R×&÷WFP¢f"g&W6‚Ò"æ6ÆöæTæöFR‡G'VR“°¢"ç&VçDæöFRç&WÆ6T6†–ÆB†g&W6‚Â"“°¢g&W6‚æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²6WEf–Wr†g&W6‚æFF6WBçf–Wr“²×Ò“°¢×Ò“°¢òòF†RÖW&vVB$WfVçG2"F"†æòFF×f–Wr’÷Vç2–÷W"Æ7B×W6VB7V"×f–Ws°¢òò—G2Æ—7Bò6ÆVæF"òÖ7v—F6†W"Æ—fW2÷WG6–FRçf–Wr×FövvÆRà¢f"FWfVçG5F"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wF"ÖWfVçG2r“°¢–b‚FWfVçG5F"bbFWfVçG5F"æFF6WBçv—&VB’·°¢FWfVçG5F"æFF6WBçv—&VBÒss°¢FWfVçG5F"æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²6WEf–Wr…öÆ7DWfVçG57V"ÇÂvw&–Br“²×Ò“°¢×Ð¢Fö7VÖVçBçVW'•6VÆV7F÷$ÆÂ‚ræWfVçG2×7V&æb'WGFöå¶FF×f–WuÒr’æf÷$V6‚†gVæ7F–öâ†"’·°¢–b†"æFF6WBçv—&VB’&WGW&ã°¢"æFF6WBçv—&VBÒss°¢"æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²6WEf–Wr†"æFF6WBçf–Wr“²×Ò“°¢×Ò“°¢òòF†Rv÷&¶–ær†öÖWvRÇv—2÷Vç27F–öâ6VçFW#²W‡Æ–6—Bf–WrÆ–æ·0¢òò6â7F–ÆÂ÷VâF†R÷&–v–æÂ6ÆVæF"÷"÷F†W"G&6¶W"f–Ww2à¢f"&WVW7FVBÒæWrU$Å6V&6…&×2‡v–æF÷ræÆö6F–öâç6V&6‚’ævWB‚wf–Wrr“°¢6WEf–Wr…d”UuôäÔU2æ–æFW„öb‡&WVW7FVB’ÓÒÓò&WVW7FVB¢v7F–öâr“°¢×Ð ¢òò)H)HÖf–Wr)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò6—G’ÖÆWfVÂ–ç2„ÆVfÆWB²÷Vå7G&VWDÖÂÆ§’ÖÆöFVB’â6ö÷&F–æFW26öÖP¢òòg&öÒ7FF–2Æöö·W¶W–VB'’7V'7G&–æw2öb6—G’÷fVçVRöÆö6F–öâFW‡B(	@¢òòfVçVRæÖW2‚$¦f—G26VçFW""’&W6öÇfRFòF†V—"6—G’âWfVçG2v†÷6P¢òòÆö6F–öâÖF6†W2æ÷F†–ær…&VÖ÷FRÂD$BÂöF67B’&R6÷VçFVB–âæ÷FP¢òò&÷fRF†RÖ&F†W"F†âG&÷VB6–ÆVçFÇ’à¢f"4•E•ô4ôõ$E2Ò°¢òò·7V'7G&–ær¶W’ÂÆBÂÆæuÒ(	B6†V6¶VB–â÷&FW"Âf—'7B†—Bv–ç2Â6òW@¢òòÆöævW"öÖ÷&R×7V6–f–2¶W—2&Vf÷&R6†÷'BvVæW&–2öæW2à¢²vW†6VÂÆöæFöârÂSãS‚Âã#•ÒÂ²vöÇ–×–ÆöæFöârÂSãC“bÂÓã#ÒÀ¢²v–çFW&6öçF–æVçFÂÆöæFöârÂSãS"Âã5ÒÂ²sƒ‚vööB7G&VWBrÂSãSbÂÓã“EÒÀ¢²væWr–÷&²rÂCãs#‚ÂÓsBãeÒÂ²vç–2rÂCãs#‚ÂÓsBãeÒÀ¢²v¦f—G2rÂCãsSs‚ÂÓsBã#ÒÂ²w–W"6—‡G’rÂCãsCcbÂÓsBãƒeÒÀ¢²sSƒ2&²rÂCãscSÂÓs2ã“cƒ5ÒÂ²vÖ'&–÷GBÖ'V—2rÂCãsSƒ’ÂÓs2ã“ƒSÒÀ¢²vÆ2fVv2rÂ3bãc“’ÂÓRã3“…ÒÂ²wfVæWF–ârÂ3bã#"ÂÓRãc“uÒÀ¢²vÖæFÆ’&’rÂ3bã“#ÂÓRãscÒÀ¢²w6âg&æ6—66òrÂ3rãssC’ÂÓ#"ãC“EÒÂ²vÖ÷66öæRrÂ3rãsƒC"ÂÓ#"ãCeÒÀ¢²w6æG’7&–æw2rÂ32ã“3BÂÓƒBã3s35ÒÂ²vFÆçFrÂ32ãsC’ÂÓƒBã3ƒ…ÒÀ¢²vÖ&–æ&’6æG2rÂã#ƒ3BÂ2ãƒcuÒÂ²w6–æv÷&RrÂã3S#Â2ãƒ“…ÒÀ¢²w6â¦÷6RrÂ3rã33ƒ"ÂÓ#ãƒƒc5ÒÂ²w6çF6Æ&rÂ3rã3SCÂÓ#ã“SS%ÒÀ¢²vÖ66÷&Ö–6²rÂCãƒS"ÂÓƒrãc“5ÒÂ²v6†–6vòrÂCãƒsƒÂÓƒrãc#“…ÒÀ¢²w&—2rÂC‚ãƒScbÂ"ã3S#%ÒÂ²wFWG2rÂS"ãC33‚ÂBãƒcuÒÀ¢²v×7FW&FÒrÂS"ã3csbÂBã“CÒÂ²v‡–æW2rÂC"ã3CsÂÓsãƒS•ÒÀ¢²v6Ö'&–FvRrÂC"ã3s3bÂÓsã“uÒÂ²v&÷7FöârÂC"ã3cÂÓsãSƒ•ÒÀ¢²vGV&’W††–&—F–öârÂ#Rã#C‚ÂSRã#s…ÒÂ²vw&æB‡–GBGV&’rÂ#Rã##ƒRÂSRã3#s5ÒÀ¢²vGV&’rÂ#Rã#C‚ÂSRã#s…ÒÀ¢²vÖ–Ö’&V6‚rÂ#Rãs“rÂÓƒã5ÒÂ²v&–ÇFÖ÷&RrÂ#RãsC’ÂÓƒã#sƒEÒÀ¢²vÖ–Ö’rÂ#RãscrÂÓƒã“…ÒÀ¢²v&&6VÆöærÂCã3ƒSÂ"ãs3EÒÂ²wv6†–æwFöârÂ3‚ã“s"ÂÓsrã3c•ÒÀ¢²væF–öæÂ†&&÷"rÂ3‚ãsƒ#bÂÓsrãcEÒÂ²væ6‡f–ÆÆRrÂ3bãc#rÂÓƒbãsƒeÒÀ¢²w6âF–VvòrÂ3"ãsSrÂÓrãcÒÀ¢²v¶’&–ÆW’rÂ3"ãssSrÂÓ“bãƒ5ÒÂ²vg&—66òrÂ32ãSrÂÓ“bãƒ#3eÒÀ¢²vFÆÆ2rÂ3"ãsscrÂÓ“bãs“uÒÀ¢²vÆ÷2ævVÆW2rÂ3BãS#"ÂÓ‚ã#C3uÒÂ²vW7F–ârÂ3ã#cs"ÂÓ“rãsC3ÒÀ¢²vFö†rÂ#Rã#ƒSBÂSãS3ÒÀ¢²vÖW76R&W&Æ–ârÂS"ãSRÂ2ã#c“uÒÂ²vÖ&—F–ÒrÂS"ãS‚Â2ã3ƒeÒÀ¢²v&W&Æ–ârÂS"ãS"Â2ãCUÒÀ¢²v6RF÷vârÂÓ32ã“#C’Â‚ãC#CÒÂ²w§W&–6‚rÂCrã3sc’Â‚ãSCuÒÀ¢²v7VârÂ3’ã“ÂÓbãƒsUÒÂ²vF—6æW’rÂ#‚ã3cS‚ÂÓƒãSC“EÒÀ¢²v÷&ÆæFòrÂ#‚ãS3ƒ2ÂÓƒã3s“%ÒÂ²v×Væ–6‚rÂC‚ã3SÂãSƒ%ÒÀ¢²v†ö&ö¶VârÂCãsCBÂÓsBã3#EÒÂ²w&—–F‚rÂ#Bãs3bÂCbãcsS5ÒÀ¢²vf÷'BÆVFW&FÆRrÂ#bã##BÂÓƒã3s5ÒÂ²v'RF†&’rÂ#BãCS3’ÂSBã3ss5ÒÀ¢²wfæ6÷WfW"rÂC’ã#ƒ#rÂÓ#2ã#uÒÂ²w&öÖRrÂCã“#‚Â"ãC“cEÒÀ¢²v&‡&–ârÂ#bãccrÂSãSSsuÒÀ¢²w–öævR7G&VWBrÂC2ãccbÂÓs’ã3sƒuÒÂ²vvV÷&vR6×W2rÂC2ãccbÂÓs’ã3sƒuÒÀ¢²wF÷&öçFòrÂC2ãcS3"ÂÓs’ã3ƒ3%ÒÀ¢²wÆW‡òrÂCbã#3ƒÂbãS5ÒÂ²vvVæWfrÂCbã#CBÂbãC3%ÒÀ¢²væ†V–ÒrÂ32ãƒ3cbÂÓrã“C5ÒÂ²w6òVÆòrÂÓ#2ãSSRÂÓCbãc335ÒÀ¢²væ÷F'’†÷FVÂrÂ3’ã“S#bÂÓsRãcS%ÒÂ²w†–ÆFVÇ†–rÂ3’ã“S#bÂÓsRãcS%ÒÀ¢²v–fVÖrÂCãCcƒ2ÂÓ2ãcceÒÂ²vÖG&–BrÂCãCc‚ÂÓ2ãs3…ÒÀ¢²vÖVò&VærÂ3‚ãscƒBÂÓ’ã“3…ÒÂ²vÆ—6&öârÂ3‚ãs##2ÂÓ’ã3“5ÒÀ¢²v''W76VÇ2rÂSãƒS2ÂBã3SuÒÂ²w7Fö6¶†öÆÒrÂS’ã3#“2Â‚ãcƒeÒÀ¢²w6âÖFVòrÂ3rãSc2ÂÓ#"ã3#SUÒÂ²v&W&¶VÆW’rÂ3rãƒsRÂÓ#"ã#s5ÒÀ¢²vFVçfW"rÂ3’ãs3“"ÂÓBã““5ÒÂ²v†ÆbÖööâ&’rÂ3rãCc3bÂÓ#"ãC#ƒeÒÀ¢²vÖVæÆò&²rÂ3rãCS#’ÂÓ#"ãƒuÒÂ²w†öVæ—‚rÂ32ãCCƒBÂÓ"ãsEÒÀ¢²v&ÇF–Ö÷&RrÂ3’ã#“BÂÓsbãc#%ÒÂ²v×W66BrÂ#2ãSƒ‚ÂS‚ã3ƒ#•ÒÀ¢²vöÖârÂ#2ãSƒ‚ÂS‚ã3ƒ#•ÒÂ²v6ææW2rÂC2ãSS#‚ÂrãsEÒÀ¢²v÷†f÷&BrÂSãsS"ÂÓã#SsuÒÂ²v÷6ÆòrÂS’ã“3’ÂãsS#%ÒÀ¢²vÆVW6'W&rrÂ3’ãSrÂÓsrãSc3eÒÂ²vGV&Æ–ârÂS2ã3C“‚ÂÓbã#c5ÒÀ¢²v†öær¶öærrÂ#"ã3“2ÂBãc“EÒÂ²vFæö–çBrÂ32ãCcc’ÂÓrãc“…ÒÀ¢²vÆ÷VF÷VârÂ3’ã’ÂÓsrãcEÒÀ¢²wfVæW§VVÆrÂãCƒbÂÓcbã“3eÒÂ²v&6†VÆ÷"rÂ3’ãSƒbÂÓbãS3CuÒÀ¢²væWr÷&ÆVç2rÂ#’ã“SÂÓ“ãsUÒÂ²vw&Wf–æRrÂ3"ã“3C2ÂÓ“rãsƒÒÀ¢²w7–FæW’rÂÓ32ãƒcƒ‚ÂSã#“5ÒÂ²vÖVÆ&÷W&æRrÂÓ3rãƒ3bÂCBã“c3ÒÀ¢²vvöÆB6ö7BrÂÓ#‚ãcrÂS2ãEÒÂ²w–ö¶ö†ÖrÂ3RãCC3rÂ3’ãc3…ÒÀ¢²wFö·–òrÂ3Rãcsc"Â3’ãcS5ÒÂ²v×VÖ&’rÂ’ãsbÂs"ãƒssuÒÀ¢²v&VævÇW'RrÂ"ã“sbÂsrãS“CeÒÂ²v&ævÆ÷&RrÂ"ã“sbÂsrãS“CeÒÀ¢²væWrFVÆ†’rÂ#‚ãc3’Âsrã#•ÒÂ²w6V÷VÂrÂ3rãSccRÂ#bã“s…ÒÀ¢²w6†æv†’rÂ3ã#3BÂ#ãCs3uÒÂ²wFVÂf—brÂ3"ãƒS2Â3Bãsƒ…ÒÀ¢²v—7Fæ'VÂrÂCãƒ"Â#‚ã“sƒEÒÂ²v¦W'6W’6—G’rÂCãss‚ÂÓsBãC3ÒÀ¢²vFö†rÂ#Rã#ƒSBÂSãS3ÒÂ²w6çFòFöÖ–ævòrÂ‚ãCƒcÂÓc’ã“3%ÒÀ¢²vÆöæFöârÂSãSsBÂÓã#s…Ð¢Ó°¢òò7G&—66VçG26ò%<:6òVÆò"ò$&öv÷L:"ÖF6‚'6òVÆò"ò&&öv÷F"à¢gVæ7F–öâöFV66VçB‡2’·°¢G'’·²&WGW&â2ææ÷&ÖÆ—¦R‚tädBr’ç&WÆ6R‚õµÅÇS3ÕÅÇS3feÒörÂrr“²×Ò6F6‚†R’·²&WGW&â3²×Ð¢×Ð¢òò6†V6¶VB$Tdõ$R4•E•ô4ôõ$E26ò6†&VBæÖW2…6â¦÷<:’Â6çF6Æ&À¢òò6çF–vò’&W6öÇfRFòÆF–âÖW&–6(	Bæ÷BF†V—"U2æÖW6¶W2(	Bv†VâF†P¢òòÆö6F–öâ7GVÆÇ’æÖW2ÆDÒÆ6Rà¢f"ÄDÕô4ôõ$E2Ò°¢²v6÷7F&–6rÂ’ã“#ƒÂÓƒBã“uÒÂ²w6â6ÇfF÷"rÂ2ãc“#’ÂÓƒ’ã#ƒ%ÒÀ¢²vVÂ6ÇfF÷"rÂ2ãc“#’ÂÓƒ’ã#ƒ%ÒÂ²vwVFVÖÆrÂBãc3C’ÂÓ“ãSc•ÒÀ¢²vÖW†–6ò6—G’rÂ’ãC3#bÂÓ“’ã33%ÒÂ²v6—VFBFRÖW†–6òrÂ’ãC3#bÂÓ“’ã33%ÒÀ¢²vwVFÆ¦&rÂ#ãcS“rÂÓ2ã3C“eÒÂ²vÖöçFW'&W’rÂ#RãcƒcbÂÓã3cÒÀ¢²v6æ7VârÂ#ãc’ÂÓƒbãƒSUÒÂ²v&öv÷FrÂBãsÂÓsBãs#ÒÀ¢²v6'FvVærÂã3“ÂÓsRãCs“EÒÂ²wæÖ6—G’rÂ‚ã“ƒ#BÂÓs’ãS“•ÒÀ¢²vÖVFVÆÆ–ârÂbã#CC"ÂÓsRãSƒ%ÒÂ²vÆ–ÖrÂÓ"ãCcBÂÓsrãC#…ÒÀ¢²v'VVæ÷2—&W2rÂÓ3Bãc3rÂÓS‚ã3ƒeÒÂ²w6çF–vòrÂÓ32ãCCƒ’ÂÓsãcc“5ÒÀ¢²w&–òFR¦æV—&òrÂÓ#"ã“c‚ÂÓC2ãs#•ÒÂ²wV—FòrÂÓãƒrÂÓs‚ãCcs…ÒÀ¢²vÖöçFWf–FVòrÂÓ3Bã“ÂÓSbãcCUÒÂ²v6&62rÂãCƒbÂÓcbã“3eÐ¢Ó°¢òòÆ7B&W6÷'B(	Bæò¶æ÷vâ6—G’ÖF6†VBÂ6òÆæBF†R–â–âF†R&–v‡B4õTåE%¢òò†—G26—FÂòÆ&vW7B6—G’’–ç7FVBöbG&÷–ærF†RWfVçBöfbF†RÖà¢f"4õTåE%•ô4ôõ$E2Ò°¢²v6÷7F&–6rÂ’ã“#ƒÂÓƒBã“uÒÂ²wæÖrÂ‚ã“ƒ#BÂÓs’ãS“•ÒÀ¢²vwVFVÖÆrÂBãc3C’ÂÓ“ãSc•ÒÂ²v6öÆöÖ&–rÂBãsÂÓsBãs#ÒÀ¢²wW'RrÂÓ"ãCcBÂÓsrãC#…ÒÂ²vV7VF÷"rÂÓãƒrÂÓs‚ãCcs…ÒÀ¢²v6†–ÆRrÂÓ32ãCCƒ’ÂÓsãcc“5ÒÂ²v&vVçF–ærÂÓ3Bãc3rÂÓS‚ã3ƒeÒÀ¢²wW'VwV’rÂÓ3Bã“ÂÓSbãcCUÒÂ²v'&¦–ÂrÂÓ#2ãSSRÂÓCbãc335ÒÀ¢²wfVæW§VVÆrÂãCƒbÂÓcbã“3eÒÂ²vFöÖ–æ–6â&WV&Æ–2rÂ‚ãCƒcÂÓc’ã“3%ÒÀ¢²wVW'Fò&–6òrÂ‚ãCcSRÂÓcbãSuÒÂ²vÖW†–6òrÂ’ãC3#bÂÓ“’ã33%ÒÀ¢²v–æF–rÂ’ãsbÂs"ãƒssuÒÂ²v¦ârÂ3Rãcsc"Â3’ãcS5ÒÀ¢²vW7G&Æ–rÂÓ32ãƒcƒ‚ÂSã#“5ÒÂ²v6†–ærÂ3ã#3BÂ#ãCs3uÒÀ¢²w6÷WF‚¶÷&VrÂ3rãSccRÂ#bã“s…ÒÂ²w6VF’&&–rÂ#Bãs3bÂCbãcsS5ÒÀ¢²wVæ—FVB&"VÖ—&FW2rÂ#Rã#C‚ÂSRã#s…Ð¢Ó°¢gVæ7F–öâvVôöb‡&V2’·°¢f"&rÒ‡&V2æ6—G’ÇÂrr’²rr²‡&V2çfVçVRÇÂrr’²rr²‡&V2æÆö6F–öâÇÂrr“°¢–b‚&rçG&–Ò‚’’&WGW&âçVÆÃ°¢òòwV&B$æWrÖW†–6ò"…U27FFR’g&öÒF†RvÖW†–6òr6÷VçG'’fÆÆ&6²à¢f"†’ÒöFV66VçB‡&rçFôÆ÷vW$66R‚’’ç&WÆ6R‚öæWrÖW†–6òörÂvæWvÖW‚r“°¢f"“°¢f÷"†’Ò²’ÂÄDÕô4ôõ$E2æÆVæwFƒ²’²²’·°¢–b††’æ–æFW„öb„ÄDÕô4ôõ$E5¶•Õ³Ò’ÓÒÓ’&WGW&â´ÄDÕô4ôõ$E5¶•Õ³ÒÂÄDÕô4ôõ$E5¶•Õ³%ÕÓ°¢×Ð¢f÷"†’Ò²’Â4•E•ô4ôõ$E2æÆVæwFƒ²’²²’·°¢–b††’æ–æFW„öb„4•E•ô4ôõ$E5¶•Õ³Ò’ÓÒÓ’&WGW&â´4•E•ô4ôõ$E5¶•Õ³ÒÂ4•E•ô4ôõ$E5¶•Õ³%ÕÓ°¢×Ð¢f÷"†’Ò²’Â4õTåE%•ô4ôõ$E2æÆVæwFƒ²’²²’·°¢–b††’æ–æFW„öb„4õTåE%•ô4ôõ$E5¶•Õ³Ò’ÓÒÓ’&WGW&â´4õTåE%•ô4ôõ$E5¶•Õ³ÒÂ4õTåE%•ô4ôõ$E5¶•Õ³%ÕÓ°¢×Ð¢&WGW&âçVÆÃ°¢×Ð ¢f"öÆVfÆWDÆöF–ærÒçVÆÃ°¢gVæ7F–öâÆöDÆVfÆWB‚’·°¢–b‡v–æF÷räÂ’&WGW&â&öÖ—6Rç&W6öÇfR‚“°¢–b…öÆVfÆWDÆöF–ær’&WGW&âöÆVfÆWDÆöF–æs°¢öÆVfÆWDÆöF–ærÒæWr&öÖ—6R†gVæ7F–öâ‡&W6öÇfRÂ&V¦V7B’·°¢f"772ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vÆ–æ²r“°¢772ç&VÂÒw7G–ÆW6†VWBs°¢772æ‡&VbÒv‡GG3¢ò÷Vç¶ræ6öÒöÆVfÆWDã’ãBöF—7BöÆVfÆWBæ772s°¢Fö7VÖVçBæ†VBæVæD6†–ÆB†772“°¢f"2ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚w67&—Br“°¢2ç7&2Òv‡GG3¢ò÷Vç¶ræ6öÒöÆVfÆWDã’ãBöF—7BöÆVfÆWBæ§2s°¢2æöæÆöBÒ&W6öÇfS°¢2æöæW'&÷"ÒgVæ7F–öâ‚’·²öÆVfÆWDÆöF–ærÒçVÆÃ²&V¦V7B†æWrW'&÷"‚vÆVfÆWBÆöBf–ÆVBr’“²×Ó°¢Fö7VÖVçBæ†VBæVæD6†–ÆB‡2“°¢×Ò“°¢&WGW&âöÆVfÆWDÆöF–æs°¢×Ð ¢f"ö÷4ÖÒçVÆÂÂö÷4ÖÆ–W"ÒçVÆÃ°¢òò)H)HöæRv÷&ÆBÂW†7FÇ’öæ6R)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòF†RÖW6VBFò&WVC¢¦ööÖVB÷WBÂ–÷Rv÷Bf—fR6–FRÖ'’×6–FR6÷–W2ö`¢òòV'F‚v—F‚F†R–ç266GFW&VB7&÷72ÆÂöbF†VÒ„‡W&ÆW’##bÓrÓ#’’à¢òòF‡&VRF†–æw2FövWF†W"f—‚—C ¢òòæõw&(	BF†RF–ÆRÆ–W"7F÷2–çF–ær6÷–W2V—F†W"6–FRà¢òòÖ„&÷VæG2(	B–÷R6âwBG&röfb–çFòF†Rfö–Bv†W&R6÷–W2Æ—fVBà¢òòfÆö÷"¦ööÒ(	B6ö×WFVB&VÆ÷rÂ6ò–÷R6âæWfW"¦ööÒ÷WB7BF†P¢òòö–çBv†W&RöæRv÷&ÆB7F÷2f–ÆÆ–ærF†Rf–Ww÷'Bà¢òòv÷&ÆD6÷”§V×—2ôdc¢—BW†—7G2FòÖ÷fRÖ&¶W'2FòF†RæV&W7Bv÷&Æ@¢òò4õ’Âv†–6‚—2ÖVæ–ævÆW72öæ6RF†W&Rw2öæÇ’öæRà¢f"Ôõtõ$ÄBÒçVÆÃ²òò6WBöæ6RÂ—2ÆöFV@¢òò6ÖÆÆW7B¦ööÒBv†–6‚6–ævÆRv÷&ÆB7F–ÆÂ6÷fW'2F†RgVÆÂv–GF‚â&VÆ÷p¢òòF†—2ÆVfÆWB†2æ÷F†–ærFò6†÷rV—F†W"6–FR(	Bv†–6‚—2v†B&öGV6VBF†P¢òò&WVG2â&V6ö×WFVBöâ&W6—¦RÂ6–æ6R—BFWVæG2öâF†R6öçF–æW"v–GF‚à¢gVæ7F–öâöÇ”ÖÖ–å¦ööÒ‚’·°¢–b‚ö÷4Ö’&WGW&ã°¢f"rÒö÷4ÖævWE6—¦R‚’çƒ°¢–b‚r’&WGW&ã°¢f"Ö–å¢ÒÖF‚æ6V–Â„ÖF‚æÆör‡rò#Sb’òÖF‚äÄã"¢’ò°¢–b‚—4f–æ—FR†Ö–å¢’’&WGW&ã°¢ö÷4Öç6WDÖ–å¦ööÒ†Ö–å¢“°¢–b…ö÷4ÖævWE¦ööÒ‚’ÂÖ–å¢’ö÷4Öç6WE¦ööÒ†Ö–å¢“°¢×Ð¢gVæ7F–öâ÷Vä÷4Ö‚’·°¢ÆöDÆVfÆWB‚’çF†Vâ†gVæ7F–öâ‚’·°¢–b‚ö÷4Ö’·°¢òò+ƒR—2F†RÖW&6F÷"Æ–Ö—B(	B7B—BF†R&ö¦V7F–öâ'Vç2Fò–æf–æ—G’à¢Ôõtõ$ÄBÒÂæÆDÆæt&÷VæG2…µ²ÓƒRÂÓƒÒÂ³ƒRÂƒÕÒ“°¢ö÷4ÖÒÂæÖ‚v÷2ÖÖÖ6çf2rÂ·°¢v÷&ÆD6÷”§V×¢fÇ6RÀ¢Ö„&÷VæG3¢Ôõtõ$ÄBÀ¢Ö„&÷VæG5f—66÷6—G“¢ãÂòò†&BVFvRÂæò'V&&W"Ö&æF–ær7B—@¢¦ööÕ6æ¢ã#Ròò6òF†RfÆö÷"¦ööÒ6â&RW†7BÂæ÷B&÷VæFVBW ¢×Ò’ç6WEf–Wr…³3ÂÓ#ÒÂ"“°¢ÂçF–ÆTÆ–W"‚v‡GG3¢ò÷··7×ÒçF–ÆRæ÷Vç7G&VWFÖæ÷&r÷··§×Ò÷··‡×Ò÷··—×ÒçærrÂ·°¢GG&–'WF–öã¢rf6÷“²÷Vå7G&VWDÖ6öçG&–'WF÷'2rÂÖ…¦ööÓ¢‚À¢æõw&¢G'VRÂ&÷VæG3¢Ôõtõ$Ä@¢×Ò’æFEFò…ö÷4Ö“°¢ö÷4ÖÆ–W"ÒÂæÆ–W$w&÷W‚’æFEFò…ö÷4Ö“°¢ö÷4Öæöâ‚w&W6—¦RrÂöÇ”ÖÖ–å¦ööÒ“°¢òò6–FV&"6Æ÷6R'WGFöâ²6Æ–6¶–ærV×G’ÖF—6Ö—76W2F†RæVÂà¢f"6$6Æ÷6RÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v×6"Ö6Æ÷6Rr“°¢–b‡6$6Æ÷6R’6$6Æ÷6RæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂ6Æ÷6TÖ6–FV&"“°¢ö÷4Öæöâ‚v6Æ–6²rÂ6Æ÷6TÖ6–FV&"“°¢×Ð¢&VæFW$÷4Ö‚“°¢òòF†R6öçF–æW"v2F—7Æ“¦æöæRB–æ—B(	Bf÷&6R6—¦R&V6Æ2ÂF†Và¢òò6WBF†R¦ööÒfÆö÷"g&öÒF†R&VÂv–GF‚à¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²ö÷4Öæ–çfÆ–FFU6—¦R‚“²öÇ”ÖÖ–å¦ööÒ‚“²×ÒÂS“°¢×Ò’æ6F6‚†gVæ7F–öâ‚’·°¢f"æ÷FRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2ÖÖÖæ÷FRr“°¢–b†æ÷FR’æ÷FRçFW‡D6öçFVçBÒtÖ6÷VÆBæ÷BÆöB†öffÆ–æR÷"&Æö6¶VB4Dâ’âW6Rw&–B÷"6ÆVæF"–ç7FVBâs°¢×Ò“°¢×Ð ¢gVæ7F–öâ&VæFW$÷4Ö‚’·°¢–b‚ö÷4ÖÆ–W"’&WGW&ã°¢ö÷4ÖÆ–W"æ6ÆV$Æ–W'2‚“°¢6Æ÷6TÖ6–FV&"‚“²òòf–ÇFW'26†ævVB(i"&W6WBF†RæVÀ¢òòW6RF†R6&G22F†RFF6÷W&6R6òF†RÖ†öæ÷'2F†R4ÔRf–ÇFW'0¢òò2F†Rw&–B‡&–6RÂ'W–W"×&–6‚ÂÖöçF‡2Â6V&6‚Ââââ’à¢f"'”6ö÷&BÒ··×Ó°¢f"VçÆ6VBÒÂÆ6VBÒÂ7EÆ6VBÒÂW6öÖ–æuÆ6VBÒ°¢F÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&Br’æf÷$V6‚†gVæ7F–öâ†6&B’·°¢òòW6RF†Rf–ÇFW"×72fÆrÂäõBF—7Æ’(	B7BWfVçG2Æ—fR–âF†P¢òò6öÆÆ6VB&6†—fRw&÷W†F—7Æ“¦æöæR’'WB6†÷VÆB7F–ÆÂÖÂw&–VBà¢–b†6&BæFF6WBç76VBÓÒsr’&WGW&ã²òòf–ÆVBâ7F—fRf–ÇFW ¢–b†6&Bæ6Æ74Æ—7Bæ6öçF–ç2‚v—2Ö&6†—fVBr’’&WGW&ã²òòW6W"Ö†–FFVâ(	B¶VWöfbF†RÖ ¢f"&V2Ò6&BåöÖöFÅ&V2ÇÂ··×Ó°¢f"ÆÂÒvVôöb‡&V2“°¢–b‚ÆÂ’·²VçÆ6VB²³²&WGW&ã²×Ð¢Æ6VB²³°¢f"6&E7BÒ6&BæFF6WBç7BÓÓÒss°¢–b†6&E7B’7EÆ6VB²³²VÇ6RW6öÖ–æuÆ6VB²³°¢f"¶W’ÒÆÅ³ÒçFôf—†VBƒ2’²rÂr²ÆÅ³ÒçFôf—†VBƒ2“°¢f"rÒ†'”6ö÷&E¶¶W•ÒÒ'”6ö÷&E¶¶W•ÒÇÂ·²ÆÃ¢ÆÂÂWg3¢µÒÂ†5W6öÖ–æs¢fÇ6R×Ò“°¢ræWg2çW6‚‡&V2“°¢–b‚6&E7B’ræ†5W6öÖ–ærÒG'VS°¢×Ò“°¢ö&¦V7Bæ¶W—2†'”6ö÷&B’æf÷$V6‚†gVæ7F–öâ†¶W’’·°¢f"rÒ'”6ö÷&E¶¶W•Ó°¢f"âÒræWg2æÆVæwFƒ°¢òò6ÇW7FW"×7G–ÆR&FvS¢öæR6öç6—7FVçB'&æB6öÆ÷"WfW'—v†W&R(	BF†P¢òò&Vv–öâFF—2FöòF6‡’Fò6öÆ÷"Ö6öFR'’‡6ÖRÖWG&ò&Vv0¢òòvWGF–ær&ÇVRäBw&’–ç2’â6—¦RÆöæR6'&–W2F†R6÷VçB6–væÂà¢f"6—¦RÒâÓÓÒòB¢ÖF‚æÖ–âƒ#b²â¢ã"ÂCB“°¢f"–6öâÒÂæF—d–6öâ‡·°¢6Æ74æÖS¢rrÂòò7W&W72ÆVfÆWBw2FVfVÇBv†—FR7V&P¢‡FÖÃ¢sÆF—b6Æ73Ò&Ö×–âr²†âÓÓÒòr6–ævÆRr¢rr’²†ræ†5W6öÖ–æròrr¢r7Br’²r#âr°¢†âÓÓÒòrr¢â’²sÂöF—cârÀ¢–6öå6—¦S¢·6—¦RÂ6—¦UÒÀ¢–6öäæ6†÷#¢·6—¦Rò"Â6—¦Rò%ÒÀ¢÷Wæ6†÷#¢³Â×6—¦Rò%Ð¢×Ò“°¢f"Ö&¶W"ÒÂæÖ&¶W"†ræÆÂÂ·²–6öã¢–6öâ×Ò’æFEFò…ö÷4ÖÆ–W"“° ¢òò6Æ–6²–â(i"6Æ–FRF†—2Æ6Rw2WfVçG2–çFòF†R&–v‡B6–FV&"à¢Ö&¶W"æöâ‚v6Æ–6²rÂgVæ7F–öâ‚’·²÷VäÖ6–FV&"†r“²×Ò“°¢×Ò“°¢òò&V6VçFW"Fòf—Bv†FWfW"—2Æ÷GFVBÂ6òf–ÇFW"6âwBÆVfRÖF6†–æp¢òò–ç2öfb×67&VVâ‚'F†RÖ—6âwB6†÷v–ærWfW'—F†–ær"’â6F†R¦ööÒ6ò¢òò6–ævÆRWfVçBFöW6âwB6ÆÒFò7G&VWBÆWfVÃ²6¶—–bæ÷F†–ærw2Æ6VBà¢f"÷G2Òö&¦V7Bæ¶W—2†'”6ö÷&B’æÖ†gVæ7F–öâ†²’·²&WGW&â'”6ö÷&E¶µÒæÆÃ²×Ò“°¢–b…÷G2æÆVæwF‚’·°¢G'’·²ö÷4Öæf—D&÷VæG2„ÂæÆDÆæt&÷VæG2…÷G2’Â·²FF–æs¢³CÂCÒÂÖ…¦ööÓ¢×Ò“²×Ò6F6‚†R’··×Ð¢×Ð¢f"æ÷FRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2ÖÖÖæ÷FRr“°¢–b†æ÷FR’·°¢æ÷FRçFW‡D6öçFVçBÒÆ6VB²rWfVçG2öâF†RÖr°¢‡7EÆ6VBòr‚r²W6öÖ–æuÆ6VB²rW6öÖ–ær+rr²7EÆ6VB²r7BÂw&–VB’r¢rr’°¢‡VçÆ6VBòr+rr²VçÆ6VB²rv—F†÷WBÖ&ÆRÆö6F–öâ…&VÖ÷FRòD$BòöF67B’r¢rr’°¢r(	B6Æ–6²–âFòÆ—7B—G2WfVçG2âs°¢×Ð¢×Ð ¢òò6†÷'BFFRf÷"F†R6–FV&"&÷w2‚$Ö"R"’Âg&öÒ7F'EöFFRv†VâvR†fR—Bà¢gVæ7F–öâö×6%6†÷'DFFR‡"’·°¢–b‡"ç7F'EöFFR’·°¢f"BÒæWrFFR‡"ç7F'EöFFR²uC££r“°¢–b‚—4æâ†B’’&WGW&âBçFôÆö6ÆTFFU7G&–ær‚vVâÕU2rÂ·²ÖöçFƒ¢w6†÷'BrÂF“¢vçVÖW&–2r×Ò“°¢×Ð¢&WGW&â"æFFU÷7G"ÇÂrs°¢×Ð¢òò÷VÆFR²&WfVÂF†R&–v‡BÖ†æB6–FV&"v—F‚F†RWfVçG2BöæR–âà¢gVæ7F–öâ÷VäÖ6–FV&"†r’·°¢f"6"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vÖ×6–FV&"r“°¢–b‚6"’&WGW&ã°¢f"÷7BÒgVæ7F–öâ‡"’·²&WGW&â‡G—Vöb—57DWfVçBÓÓÒvgVæ7F–öâr’bb—57DWfVçB‡"“²×Ó°¢f"Wg2ÒræWg2ç6Æ–6R‚’ç6÷'B†gVæ7F–öâ†Â"’·°¢f"Ò÷7B†’ò¢Â'Ò÷7B†"’ò¢°¢–b†ÓÒ'’&WGW&âÒ'²òòW6öÖ–ærf—'7BÂ7B6–æ·2FòF†R&÷GFöÐ¢&WGW&â7G&–ær†ç7F'EöFFRÇÂæFFU÷7G"ÇÂrr’æÆö6ÆT6ö×&R…7G&–ær†"ç7F'EöFFRÇÂ"æFFU÷7G"ÇÂrr’“°¢×Ò“°¢f"6—G’Ò†Wg5³Òæ6—G’ÇÂ†Wg5³ÒæÆö6F–öâÇÂrr’ç7Æ—B‚rÂr•³ÒÇÂrr’çG&–Ò‚’ÇÂtÆö6F–öâs°¢Fö7VÖVçBævWDVÆVÖVçD'”–B‚v×6"×F—FÆRr’çFW‡D6öçFVçBÒ6—G“°¢Fö7VÖVçBævWDVÆVÖVçD'”–B‚v×6"Ö6÷VçBr’çFW‡D6öçFVçBÒWg2æÆVæwFƒ°¢f"Æ—7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v×6"ÖÆ—7Br“°¢Æ—7Bæ–ææW$…DÔÂÒrs°¢Wg2æf÷$V6‚†gVæ7F–öâ‡"’·°¢f"&÷rÒFö7VÖVçBæ7&VFTVÆVÖVçB‚v'WGFöâr“°¢&÷rçG—RÒv'WGFöâs°¢&÷ræ6Æ74æÖRÒvÖ×6"ÖWbr²…÷7B‡"’òr7Br¢rr“°¢f"F÷7FvRÒ‡"ç7FvU÷Fw2bb"ç7FvU÷Fw2æÆVæwF‚bbG—VöbÖ÷7DGfæ6VE7FvRÓÓÒvgVæ7F–öâr¢òÖ÷7DGfæ6VE7FvR‡"ç7FvU÷Fw2’¢çVÆÃ°¢f"&FvRÒrs°¢–b‡F÷7FvRbb5DtUô%•ô´U•·F÷7FvUÒ’·°¢f"2Ò5DtUô%•ô´U•·F÷7FvUÓ°¢&FvRÒsÇ7â6Æ73Ò&×6"Ö&FvR"7G–ÆSÒ&&6¶w&÷VæC¢r²2æ&r²s¶6öÆ÷#¢r²2æfr²s²#âr²W66T‡FÖÂ‡F÷7FvR’²sÂ÷7ãâs°¢×Ð¢f"GBÒö×6%6†÷'DFFR‡"“°¢&÷ræ–ææW$…DÔÂÒsÇ7â6Æ73Ò&æÒ#âr²W66T‡FÖÂ‡"ææÖRÇÂtWfVçBr’²sÂ÷7ãâr°¢sÇ7â6Æ73Ò&ÖWF#âr²†GBòsÇ7â6Æ73Ò&GB#âr²W66T‡FÖÂ†GB’²sÂ÷7ãâr¢rr’²&FvR²sÂ÷7ãâs°¢&÷ræFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢–b‡G—Vöbv–æF÷ræ÷VäWfVçDÖöFÂÓÓÒvgVæ7F–öâr’v–æF÷ræ÷VäWfVçDÖöFÂ‡"“°¢×Ò“°¢Æ—7BæVæD6†–ÆB‡&÷r“°¢×Ò“°¢Æ—7Bç67&öÆÅF÷Ò°¢6"ç&VÖ÷fTGG&–'WFR‚v†–FFVâr“°¢×Ð¢gVæ7F–öâ6Æ÷6TÖ6–FV&"‚’·°¢f"6"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vÖ×6–FV&"r“°¢–b‡6"’6"ç6WDGG&–'WFR‚v†–FFVârÂrr“°¢×Ð ¢òò)H)H6ÆVæF"&VæFW&–ær)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢f"$Tt”ôåô4ôÄõ%2Ò·°¢uU2b6æFs¢r3#ss63"rÀ¢tÆF–âÖW&–6s¢r3VVS’rÀ¢tWW&÷Rs¢r3v36VBrÀ¢tg&–6s¢r6F##ssrrÀ¢tÔTäs¢r66†BrÀ¢t6–Õ6–f–2s¢r3S“cc’rÀ¢tvÆö&Âs¢r3CsSSc’p¢×Ó° ¢gVæ7F–öâ&Vv–öä6öÆ÷"‡"’·²&WGW&â$Tt”ôåô4ôÄõ%5·%ÒÇÂr3s3s3s2s²×Ð¢òòÆ–v‡BG&ç6ÇV6VçBF–çBöb†W‚6öÆ÷"(	BW6VB6ò6ÆVæF"6†—2v—F†÷WB¢òò—VÆ–æR7FvR7F–ÆÂvWB‡&Vv–öâÖ6öÆ÷&VB’f–ÆÂ–ç7FVBöb&Ææ²v†—FRà¢gVæ7F–öâ†W…Fõ&v&††W‚Â’·°¢†W‚Ò7G&–ær††W‚ÇÂrr’ç&WÆ6R‚r2rÂrr“°¢–b††W‚æÆVæwF‚ÓÓÒ2’†W‚Ò†W‚æ6†$Bƒ’²†W‚æ6†$Bƒ’²†W‚æ6†$Bƒ’²†W‚æ6†$Bƒ’²†W‚æ6†$Bƒ"’²†W‚æ6†$Bƒ"“°¢f"âÒ'6T–çB††W‚Âb“°¢–b†—4æâ†â’’&WGW&âw&v&ƒRÃRÃRÂr²²r’s°¢&WGW&âw&v&‚r²‚†âãâb’b#SR’²rÂr²‚†âãâ‚’b#SR’²rÂr²†âb#SR’²rÂr²²r’s°¢×Ð ¢gVæ7F–öâ–æ—F–Ç2†æÖR’·°¢–b‚æÖR’&WGW&ârs°¢f"'G2Ò7G&–ær†æÖR’çG&–Ò‚’ç7Æ—B‚õÅÇ2²ò’æf–ÇFW"„&ööÆVâ“°¢&WGW&â'G2æÖ†gVæ7F–öâ‡r’·²&WGW&âu³Ó²×Ò’æ¦ö–â‚rr’ç6Æ–6RƒÂ"’çFõWW$66R‚“°¢×Ð ¢gVæ7F–öâ—6ôg&öÕ”ÔB‡’ÂÒÂB’·°¢&WGW&â’²rÒr²7G&–ær†Ò³’çE7F'Bƒ"Âsr’²rÒr²7G&–ær†B’çE7F'Bƒ"Âsr“°¢×Ð ¢gVæ7F–öâ'V–ÆD6ÆVæF$ÖöçF‚‡–V"ÂÖöçF‚ÂWfVçG2Â7FFTÖÂöä6†—6Æ–6²’·°¢f"ÖöçF„F—bÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢ÖöçF„F—bæ6Æ74æÖRÒv6ÆVæF"ÖÖöçF‚s° ¢òòF†RÖöçF‚÷–V"æ÷rÆ—fW2–âF†R6VçFW&VBæbG&÷F÷vâ&÷fRF†Rw&–BÀ¢òò6òæò7FF–2F—FÆR†W&Rà¢f"w&–BÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢w&–Bæ6Æ74æÖRÒv6ÆVæF"Öw&–Bs° ¢òòvVV¶F’†VFW"&÷rà¢f"†G"ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢†G"æ6Æ74æÖRÒv6Â×vVV¶†VBs°¢²u7VârÂtÖöârÂuGVRrÂuvVBrÂuF‡RrÂtg&’rÂu6BuÒæf÷$V6‚†gVæ7F–öâ†B’·°¢f"F‚ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢F‚æ6Æ74æÖRÒv6ÆVæF"ÖF’Ö†VBs°¢F‚çFW‡D6öçFVçBÒC°¢†G"æVæD6†–ÆB†F‚“°¢×Ò“°¢w&–BæVæD6†–ÆB††G"“° ¢f"f—'7DF’ÒæWrFFR‡–V"ÂÖöçF‚Â’ævWDF’‚“°¢f"F—4–äÖöçF‚ÒæWrFFR‡–V"ÂÖöçF‚²Â’ævWDFFR‚“°¢f"&WdÖöçF„F—2ÒæWrFFR‡–V"ÂÖöçF‚Â’ævWDFFR‚“°¢f"FöF’ÒæWrFFR‚“²FöF’ç6WD†÷W'2ƒÂÂÂ“°¢f"FöF”—6òÒ—6ôg&öÕ”ÔB‡FöF’ævWDgVÆÅ–V"‚’ÂFöF’ævWDÖöçF‚‚’ÂFöF’ævWDFFR‚’“°¢f"D’ÒƒcC° ¢òò'V–ÆBWfW'’6VÆÂöbF†RÖöçF‚w&–C¢&Wf–÷W2ÖÖöçF‚F–ÂÂF†—2ÖöçF‚À¢òòæW‡BÖÖöçF‚†VB(	BFFVBFòv†öÆRvVV·2à¢f"6VÆÇ2ÒµÓ°¢f÷"‡f"’Ò²’Âf—'7DF“²’²²’·°¢f"FâÒ&WdÖöçF„F—2Òf—'7DF’²’²°¢f"ÒÒæWrFFR‡–V"ÂÖöçF‚ÒÂFâ“°¢6VÆÇ2çW6‚‡·²—6ó¢—6ôg&öÕ”ÔB‡ÒævWDgVÆÅ–V"‚’ÂÒævWDÖöçF‚‚’ÂÒævWDFFR‚’’ÂF“¢FâÂ÷WG6–FS¢G'VR×Ò“°¢×Ð¢f÷"‡f"F’Ò²F’ÃÒF—4–äÖöçFƒ²F’²²’·°¢6VÆÇ2çW6‚‡·²—6ó¢—6ôg&öÕ”ÔB‡–V"ÂÖöçF‚ÂF’’ÂF“¢F’Â÷WG6–FS¢fÇ6R×Ò“°¢×Ð¢f"G&–ÂÒ„ÖF‚æ6V–Â†6VÆÇ2æÆVæwF‚òr’¢r’Ò6VÆÇ2æÆVæwFƒ°¢f÷"‡f"BÒ²BÃÒG&–Ã²B²²’·°¢f"æÒÒæWrFFR‡–V"ÂÖöçF‚²ÂB“°¢6VÆÇ2çW6‚‡·²—6ó¢—6ôg&öÕ”ÔB†æÒævWDgVÆÅ–V"‚’ÂæÒævWDÖöçF‚‚’ÂæÒævWDFFR‚’’ÂF“¢BÂ÷WG6–FS¢G'VR×Ò“°¢×Ð¢6VÆÇ2æf÷$V6‚†gVæ7F–öâ†2’·²2æ×2ÒæWrFFR†2æ—6ò²uC££¢r’ævWEF–ÖR‚“²×Ò“°¢f"6Å7F'D×2Ò6VÆÇ5³Òæ×2Â6ÄVæD×2Ò6VÆÇ5¶6VÆÇ2æÆVæwF‚ÒÒæ×3° ¢òò&W6öÇfR÷27FFRf÷"âWfVçB†6FÆör(i"WfVçE÷7FFS²ÖçVÂ(i"&¶VBöâ’à¢gVæ7F–öâ7Döb†Wb’·°¢&WGW&âWbåöÖçVÀ¢ò·²7FGW5÷Fw3¢WbåöÖçVÅ7FGW5Fw2Â7V¶W#¢WbåöÖçVÅ7V¶W"Â†–FFVã¢WbåöÖçVÄ†–FFVâ×Ð¢¢‡7FFTÖ¶WbæçVÕÒÇÂ··×Ò“°¢×Ð ¢òòV6‚f—6–&ÆRWfVçB&V6öÖW27â6Æ×VBFòF†Rw&–Bw2FFR&ævRà¢f"7ç2ÒµÓ°¢WfVçG2æf÷$V6‚†gVæ7F–öâ†Wb’·°¢–b‚Wbç7F'EöFFR’&WGW&ã°¢f"7BÒ7Döb†Wb“°¢–b‡7Bæ†–FFVâ’&WGW&ã°¢f"4×2ÒæWrFFR†Wbç7F'EöFFR²uC££¢r’ævWEF–ÖR‚“°¢f"T×2ÒæWrFFR‚†WbæVæEöFFRÇÂWbç7F'EöFFR’²uC££¢r’ævWEF–ÖR‚“°¢–b†—4æâ‡4×2’’&WGW&ã°¢–b†—4æâ†T×2’ÇÂT×2Â4×2’T×2Ò4×3°¢–b†T×2Â6Å7F'D×2ÇÂ4×2â6ÄVæD×2’&WGW&ã°¢7ç2çW6‚‡·²Wc¢WbÂ7C¢7BÂ4×3¢ÖF‚æÖ‚‡4×2Â6Å7F'D×2’ÂT×3¢ÖF‚æÖ–â†T×2Â6ÄVæD×2’×Ò“°¢×Ò“° ¢f"vVV·2ÒÖF‚æ6V–Â†6VÆÇ2æÆVæwF‚òr“°¢f÷"‡f"rÒ²rÂvVV·3²r²²’·°¢f"vVV´6VÆÇ2Ò6VÆÇ2ç6Æ–6R‡r¢rÂr¢r²r“°¢f"vVVµ7F'D×2ÒvVV´6VÆÇ5³Òæ×2ÂvVV´VæD×2ÒvVV´6VÆÇ5³eÒæ×3°¢f"vVV´F—bÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢vVV´F—bæ6Æ74æÖRÒv6Â×vVV²s° ¢òò&6¶w&÷VæBF’6VÆÇ2²FFRçVÖ&W'2†V6‚ö67W–W2öæR6öÇVÖã²F†P¢òò&6¶w&÷VæB7ç2WfW'’&÷r6òWfVçBÆæW26—BöâF÷öb—B’à¢vVV´6VÆÇ2æf÷$V6‚†gVæ7F–öâ†2Â6’’·°¢f"&rÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢&ræ6Æ74æÖRÒv6ÂÖF’Ö&rr²†2æ÷WG6–FRòr—2Ö÷WG6–FRr¢rr’²†2æ—6òÓÓÒFöF”—6òòr—2×FöF’r¢rr“°¢&rç7G–ÆRæw&–D6öÇVÖâÒ†6’²“°¢&rç7G–ÆRæw&–E&÷rÒsòÓs°¢vVV´F—bæVæD6†–ÆB†&r“°¢f"çVÒÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢çVÒæ6Æ74æÖRÒv6ÂÖF–çVÒr²†2æ÷WG6–FRòr—2Ö÷WG6–FRr¢rr“°¢çVÒç7G–ÆRæw&–D6öÇVÖâÒ†6’²“°¢çVÒç7G–ÆRæw&–E&÷rÒss°¢çVÒçFW‡D6öçFVçBÒ2æF“°¢vVV´F—bæVæD6†–ÆB†çVÒ“°¢×Ò“° ¢òòWfVçB6VvÖVçG2F†B–çFW'6V7BF†—2vVV²(i"öæR6öçF–wV÷W2&"V6‚à¢f"vVVµ7ç2Ò7ç2æf–ÇFW"†gVæ7F–öâ‡7’·°¢&WGW&â7æT×2ãÒvVVµ7F'D×2bb7ç4×2ÃÒvVV´VæD×3°¢×Ò’æÖ†gVæ7F–öâ‡7’·°¢f"6Vu7F'BÒÖF‚æÖ‚‡7ç4×2ÂvVVµ7F'D×2“°¢f"6VtVæBÒÖF‚æÖ–â‡7æT×2ÂvVV´VæD×2“°¢f"7F'D6öÂÒÖF‚ç&÷VæB‚‡6Vu7F'BÒvVVµ7F'D×2’òD’“°¢f"VæD6öÂÒÖF‚ç&÷VæB‚‡6VtVæBÒvVVµ7F'D×2’òD’“°¢&WGW&â·²7¢7Â7F'D6öÃ¢7F'D6öÂÂ7ã¢†VæD6öÂÒ7F'D6öÂ²’×Ó°¢×Ò’ç6÷'B†gVæ7F–öâ†Â"’·°¢&WGW&âç7F'D6öÂÒ"ç7F'D6öÂÇÂ"ç7âÒç7ã°¢×Ò“° ¢òòw&VVG’ÆæR6¶–ær6ò÷fW&Æ–ærWfVçG27F6²fW'F–6ÆÇ’à¢f"ÆæW2ÒµÓ°¢vVVµ7ç2æf÷$V6‚†gVæ7F–öâ‡w2’·°¢f"VæD6öÂÒw2ç7F'D6öÂ²w2ç7âÒ°¢f"ÆæRÒ°¢v†–ÆR‚†ÆæW5¶ÆæUÒÇÂµÒ’ç6öÖR†gVæ7F–öâ‡"’·²&WGW&â†VæD6öÂÂ%³ÒÇÂw2ç7F'D6öÂâ%³Ò“²×Ò’’ÆæR²³°¢†ÆæW5¶ÆæUÒÒÆæW5¶ÆæUÒÇÂµÒ’çW6‚…·w2ç7F'D6öÂÂVæD6öÅÒ“°¢w2æÆæRÒÆæS°¢×Ò“° ¢òò6²F†RFFRÖçVÖ&W"&÷r²V6‚WfVçBÆæR2F–v‡BWFò&÷w2ÂF†Vâ¢òòfÆW†–&ÆRf–ÆÆW"&÷rF†B6ö·2WF†R&W7BöbF†R6VÆÂ†V–v‡Bâv—F†÷W@¢òòF†—2F†RF’Ö6VÆÂÖ–âÖ†V–v‡B–æfÆFW2&÷r‡F†RFFRçVÖ&W"’æBF†P¢òòWfVçG2fÆöBf"&VÆ÷r—C²F†—2¶VW2F†VÒ&–v‡BVæFW"F†RFFRà¢vVV´F—bç7G–ÆRæw&–EFV×ÆFU&÷w2Òw&WVB‚r²†ÆæW2æÆVæwF‚²’²rÂWFò’g"s° ¢vVVµ7ç2æf÷$V6‚†gVæ7F–öâ‡w2’·°¢f"WbÒw2ç7æWbÂ7BÒw2ç7ç7C°¢f"&"ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢&"æ6Æ74æÖRÒv6ÂÖWgBs°¢–b‡7Bç6fVB’&"æ6Æ74Æ—7BæFB‚v—2×6fVBr“°¢–b‡7BçW&vVçBÇÂ—4FVFÆ–æUW&vVçB†WbæFVFÆ–æR’’&"æ6Æ74Æ—7BæFB‚v—2×W&vVçBr“°¢&"æFF6WBæWfVçDçVÒÒWbæçVÓ°¢òò¶W–&ö&B×&V6†&ÆS¢6ÆVæF"6†——2F†RöæÇ’æöâÖ'WGFöâ6öçG&öÂÀ¢òò6òv—fR—B'WGFöâ6VÖçF–72²VçFW"õ76R7F—fF–öâà¢&"ç6WDGG&–'WFR‚w&öÆRrÂv'WGFöâr“°¢&"çF$–æFW‚Ò°¢&"ç6WDGG&–'WFR‚v&–ÖÆ&VÂrÂt÷Vâr²†WbææÖRÇÂvWfVçBr’“°¢&"ç7G–ÆRæw&–D6öÇVÖâÒ‡w2ç7F'D6öÂ²’²rò7âr²w2ç7ã°¢&"ç7G–ÆRæw&–E&÷rÒ‡w2æÆæR²"“°¢f"6Å7FvW2Ò7FvUFw4öb‡7B“°¢òò6ÆVæF"6†÷w2ôäÅ’F†RF‡&VR&–÷&—G’&Æö6·2(	B7V&Ö—GFVB†&ÇVR’À¢òò&öö¶VB†w&VVâ’ÂGFVæF–ær‡FVÂ’(	BWfW'—F†–ærVÇ6R7F—2w&W’âF†—0¢òò¶–ÆÇ2F†RöÆB&Vv–öâÖ6öÆ÷"g27FvRÖ6öÆ÷"6öÆÆ—6–öâ„WW&÷R×W'ÆP¢òò&VB2tÖVWF–ær†VÆBr×W'ÆR’æBÖF6†W2ævVÆw2&6öÆ÷"F†P¢òò7FGW26†ævW2Â¶VWF†R&W7Bw&W’"6²à¢f"6Ä&Æö6²Ò6Å7FvW2æ–æFW„öb‚t&öö¶VBr’ÓÒÓòt&öö¶VBp¢¢6Å7FvW2æ–æFW„öb‚tGFVæF–ærr’ÓÒÓòtGFVæF–ærp¢¢6Å7FvW2æ–æFW„öb‚u7V&Ö—GFVBr’ÓÒÓòu7V&Ö—GFVBr¢çVÆÃ°¢–b†6Ä&Æö6²bb5DtUô%•ô´U•¶6Ä&Æö6µÒ’·°¢&"ç7G–ÆRæ&6¶w&÷VæBÒ5DtUô%•ô´U•¶6Ä&Æö6µÒæ&s°¢&"ç7G–ÆRæ&÷&FW$ÆVgD6öÆ÷"Ò5DtUô%•ô´U•¶6Ä&Æö6µÒæF÷C°¢×ÒVÇ6R·°¢&"ç7G–ÆRæ&6¶w&÷VæBÒr6c6cFcbs°¢&"ç7G–ÆRæ&÷&FW$ÆVgD6öÆ÷"Òr6CCVF"s°¢×Ð¢f"7"Ò7Bç7V¶W"ÇÂrs°¢f"–æ’Ò7"ò–æ—F–Ç2‡7"’¢rs°¢f"7FGW4–æÆ–æRÒrs°¢–b†6Ä&Æö6²bb5DtUô%•ô´U•¶6Ä&Æö6µÒ’·°¢f"2Ò5DtUô%•ô´U•¶6Ä&Æö6µÓ°¢7FGW4–æÆ–æRÒsÇ7â6Æ73Ò&6ÂÖWgB×7FGW2"7G–ÆSÒ&&6¶w&÷VæC¢r²2æ&r²s¶6öÆ÷#¢r²2æfr²s²#âr²W66T‡FÖÂ†6Ä&Æö6²’²sÂ÷7ãâs°¢×Ð¢&"æ–ææW$…DÔÂÐ¢sÇ7â6Æ73Ò&6ÂÖWgBÖæÖR#âr²W66T‡FÖÂ†WbææÖR’²sÂ÷7ãâr°¢†–æ’òsÇ7â6Æ73Ò&6ÂÖ6†—Ö–æ—F–Â"F—FÆSÒ"r²W66T‡FÖÂ‡7"’²r#âr²W66T‡FÖÂ†–æ’’²sÂ÷7ãâr¢rr’°¢7FGW4–æÆ–æS°¢&"çF—FÆRÒWbææÖR°¢‡7"òr+r7V¶W#¢r²7"¢rr’°¢†WbæÆö6F–öâòr+rr²WbæÆö6F–öâ¢rr’°¢†6Å7FvW2æÆVæwF‚òr+rr²6Å7FvW2æ¦ö–â‚rÂr’¢rr’°¢†WbæVæEöFFRbbWbæVæEöFFRÓÒWbç7F'EöFFRòr+rr²Wbç7F'EöFFR²rFòr²WbæVæEöFFR¢rr“°¢&"æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²öä6†—6Æ–6²†WbæçVÒ“²×Ò“°¢&"æFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·°¢–b†Ræ¶W’ÓÓÒtVçFW"rÇÂRæ¶W’ÓÓÒrr’·²Rç&WfVçDFVfVÇB‚“²öä6†—6Æ–6²†WbæçVÒ“²×Ð¢×Ò“°¢vVV´F—bæVæD6†–ÆB†&"“°¢×Ò“° ¢w&–BæVæD6†–ÆB‡vVV´F—b“°¢×Ð ¢ÖöçF„F—bæVæD6†–ÆB†w&–B“°¢&WGW&âÖöçF„F—c°¢×Ð ¢òò66†VBgVÆÂ6ÆVæF"–çWG26òvR6â&R×&VæFW"v—F‚F†RÆ—fRf–ÇFW'0¢òòÆ–VB(	BF†R6ÆVæF"†öæ÷'2F†R4ÔRf–ÇFW'22F†Rw&–Bà¢f"ö6ÄWfVçG2ÒçVÆÂÂö6Å7FFTÖÒçVÆÂÂö6ÄÖçVÂÒçVÆÃ°¢gVæ7F–öâ&V6Æ46ÆVæF"‚’·²–b…ö6ÄWfVçG2’&VæFW$6ÆVæF"…ö6ÄWfVçG2Âö6Å7FFTÖÂö6ÄÖçVÂ“²×Ð¢òòv†–6‚WfVçG276VBF†R7F—fRw&–Bf–ÇFW'3ò¶W–VBFòF†R6ÆVæF"w0¢òòWbæçVÒ†6FÆörÒWfVçEöçVÒÂÖçVÂÒvÒr¶–B’â7F—fSÖfÇ6Rv†Vâæ÷F†–æp¢òò—2f–ÇFW&VB÷WBÂ6òâVæf–ÇFW&VB6ÆVæF"6†÷w2WfW'’WfVçBà¢gVæ7F–öâ÷46Å76VB‚’·°¢f"ÖÒ··×ÒÂF÷FÂÒÂ76VBÒ°¢f"6&G2ÒF÷4w&–BòF÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&Br’¢µÓ°¢'&’ç&÷F÷G—Ræf÷$V6‚æ6ÆÂ†6&G2ÂgVæ7F–öâ†2’·°¢F÷FÂ²³°¢f"¶W’Ò2æFF6WBæÖçVÄ–Bò‚vÒr²2æFF6WBæÖçVÄ–B’¢2æFF6WBæWfVçDçVÓ°¢–b†2æFF6WBç76VBÓÓÒsr’·²Öµ7G&–ær†¶W’•ÒÒ²76VB²³²×Ð¢×Ò“°¢&WGW&â·²Ö¢ÖÂ7F—fS¢F÷FÂâbb76VBÂF÷FÂ×Ó°¢×Ð¢gVæ7F–öâ&VæFW$6ÆVæF"†WfVçG2Â7FFTÖÂÖçVÄWfVçG2’·°¢f"6ÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v÷2Ö6ÆVæF"r“°¢–b‚6Â’&WGW&ã°¢6Âæ–ææW$…DÔÂÒrs°¢ö6ÄWfVçG2ÒWfVçG3²ö6Å7FFTÖÒ7FFTÖ²ö6ÄÖçVÂÒÖçVÄWfVçG3° ¢òò6öÖ&–æR&VwVÆ"²ÖçVÂWfVçG2âÖçVÂWfVçG2W6R&–w6W&–Â–BæÖW76P¢òòF—7F–æ7Bg&öÒWfVçEöçVÒÂ6òvRFrF†VÒ6òF†R6Æ–6²†æFÆW"6âf–æ@¢òòF†VÒ–âF†R÷2Öw&–B'’FFÖÖçVÂÖ–B–ç7FVBà¢f"6öÖ&–æVBÒWfVçG2ç6Æ–6R‚“°¢†ÖçVÄWfVçG2ÇÂµÒ’æf÷$V6‚†gVæ7F–öâ†Ò’·°¢–b‚Òç7F'EöFFR’·°¢f"FW&—fVBÒFW&—fTFFW4g&öÕFW‡B†ÒæFFU÷7G"“°¢–b†FW&—fVBç7F'EöFFR’ÒÒö&¦V7Bæ76–vâ‡··×ÒÂÒÂ·²7F'EöFFS¢FW&—fVBç7F'EöFFRÂVæEöFFS¢ÒæVæEöFFRÇÂFW&—fVBæVæEöFFR×Ò“°¢×Ð¢6öÖ&–æVBçW6‚‡·°¢çVÓ¢vÒr²Òæ–BÀ¢öÖçVÃ¢G'VRÀ¢öÖçVÄ–C¢Òæ–BÀ¢æÖS¢ÒææÖRÀ¢7F'EöFFS¢Òç7F'EöFFRÀ¢VæEöFFS¢ÒæVæEöFFRÇÂÒç7F'EöFFRÀ¢Æö6F–öã¢ÒæÆö6F–öâÇÂrrÀ¢&Vv–öã¢Òç&Vv–öâÇÂrrÀ¢FFU÷7G#¢ÒæFFU÷7G"ÇÂrrÀ¢FVFÆ–æS¢ÒæFVFÆ–æRÇÂrrÀ¢òò†ö—7BævVÆw2÷2f–VÆG2öçFòF†R6ÆVæF"VçG'’6òF†R6†— ¢òò6â6öÆ÷"×F–çB'’—VÆ–æR7FvR²6†÷r7V¶W"–æ—F–Ç2à¢öÖçVÅ7FGW3¢Òç7FGW2ÇÂrrÀ¢öÖçVÅ7FGW5Fw3¢Òç7FGW5÷Fw2ÇÂµÒÀ¢öÖçVÅ7V¶W#¢Òç7V¶W"ÇÂrrÀ¢öÖçVÄ†–FFVã¢Òæ†–FFVà¢×Ò“°¢×Ò“° ¢òòG&÷GWÆ–6FRWfVçG2F†Rw&–B6öÆÆ6VBÂ6òF†R6ÆVæF"†æB—G0¢òòW‡÷'B’æWfW"F÷V&ÆRÖ&öö·2âWfVçBâ6ÖR726öÆÆV7G2F†RWfVçG2F†P¢òò6–væVBÖ–âW'6öâ$4„•dTC¢&6†—f–ær—2&†–FRF†—2g&öÒÕ’f–Wr"Â6òà¢òò&6†—fVBWfVçB×W7Bæ÷B6ÇWGFW"F†R6ÆVæF"V—F†W"„ævVÆv26†V6¶–æp¢òòv†B6Æ6†VBv—F‚F†÷"w2×Væ–6‚G&—æB†—BW†7FÇ’F†—2’âF†RÖ ¢òòÇ&VG’6¶—2—2Ö&6†—fVB6&G2(	BF†R6ÆVæF"v2F†RöæRf–WrF†@¢òòF–FâwBâ&VBF†R6Æ72öfbF†R6&B6òW"×W'6öâ&6†—f–ærÂ6FÆöræ@¢òòÖçVÂWfVçG2&RÆÂ†æFÆVB'’öæR'VÆRà¢f"öGW6WBÒ··×ÒÂö&6…6WBÒ··×Ó°¢'&’ç&÷F÷G—Ræf÷$V6‚æ6ÆÂ‚F÷4w&–BòF÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&Br’¢µÒÂgVæ7F–öâ†2’·°¢f"ö²Ò7G&–ær†2æFF6WBæÖçVÄ–Bò‚vÒr²2æFF6WBæÖçVÄ–B’¢2æFF6WBæWfVçDçVÒ“°¢–b†2æFF6WBæGW†–FFVâÓÓÒsr’öGW6WEµöµÒÒ°¢–b†2æ6Æ74Æ—7Bæ6öçF–ç2‚v—2Ö&6†—fVBr’’ö&6…6WEµöµÒÒ°¢×Ò“°¢6öÖ&–æVBÒ6öÖ&–æVBæf–ÇFW"†gVæ7F–öâ†Wb’·²&WGW&âöGW6WEµ7G&–ær†WbæçVÒ•Òbbö&6…6WEµ7G&–ær†WbæçVÒ•Ó²×Ò“°¢òò†öæ÷"F†R7F—fRw&–Bf–ÇFW'2‡7FvR6†—2Â6V&6‚Â&–6RÂ&Vv–öâÂ(
b“ ¢òòv†Vâ6öÖWF†–ær—2f–ÇFW&VBÂG&÷6ÆVæF"WfVçG2v†÷6R6&BF–FâwB72à¢f"÷bÒ÷46Å76VB‚“°¢–b…÷bæ7F—fR’6öÖ&–æVBÒ6öÖ&–æVBæf–ÇFW"†gVæ7F–öâ†Wb’·²&WGW&â÷bæÖµ7G&–ær†WbæçVÒ•Ó²×Ò“° ¢òòFWFW&Ö–æRÖöçF‚&ævP¢f"V&Æ–W7BÒçVÆÂÂÆFW7BÒçVÆÃ°¢6öÖ&–æVBæf÷$V6‚†gVæ7F–öâ†Wb’·°¢–b‚Wbç7F'EöFFR’&WGW&ã°¢òò'6R2Äô4ÂÖ–Fæ–v‡B†æ÷BUD2’6òvWDÖöçF‚‚’ÖF6†W2F†R•4ð¢òò7G&–ærw2ÖöçF‚(	B&&RæWrFFR‚s##bÓbÓr’—2UD2æB&öÆÇ2&6°¢òòF’–âF†RÖW&–62Â&WVæF–ær7W&–÷W2V×G’ÖöçF‚†W&Rà¢f"BÒæWrFFR†Wbç7F'EöFFR²uC££r“°¢–b†—4æâ†B’’&WGW&ã°¢–b‚V&Æ–W7BÇÂBÂV&Æ–W7B’V&Æ–W7BÒC°¢–b‚ÆFW7BÇÂBâÆFW7B’ÆFW7BÒC°¢×Ò“°¢–b‚V&Æ–W7B’·°¢6Âæ–ææW$…DÔÂÒsÇ6Æ73Ò&ÆW'B#äæòWfVçG2v—F‚FFW2FòF—7Æ’öâF†R6ÆVæF"–WBãÂ÷âs°¢&WGW&ã°¢×Ð¢òòÇv—2–æ6ÇVFR7W'&VçBÖöçF‚WfVâ–bæòWfVçG0¢f"æ÷rÒæWrFFR‚“²æ÷rç6WDFFRƒ“°¢–b†æ÷rÂV&Æ–W7B’V&Æ–W7BÒæ÷s°¢òò6BFV2##rFò&WfVçB'Væv’–â66Röb&BFF¢f"6FFRÒæWrFFRƒ##rÂÂ“°¢–b†ÆFW7Bâ6FFR’ÆFW7BÒ6FFS° ¢òòVçVÖW&FRWfW'’ÖöçF‚–âF†R&ævR6òF†RG&÷F÷vâ6†÷w2F†RgVÆÂÖVçRà¢f"ÖöçF‡2ÒµÓ°¢f"’ÒV&Æ–W7BævWDgVÆÅ–V"‚’ÂÒÒV&Æ–W7BævWDÖöçF‚‚“°¢f"VæE’ÒÆFW7BævWDgVÆÅ–V"‚’ÂVæDÒÒÆFW7BævWDÖöçF‚‚“°¢f"wV&BÒ°¢v†–ÆR‚‡’ÂVæE’ÇÂ‡’ÓÓÒVæE’bbÒÃÒVæDÒ’’bbwV&B²²ÂC‚’·°¢ÖöçF‡2çW6‚‡·²“¢’ÂÓ¢ÒÂ¶W“¢’²rÒr²7G&–ær†Ò²’çE7F'Bƒ"Âsr’×Ò“°¢Ò²³°¢–b†Òâ’·²ÒÒ²’²³²×Ð¢×Ð¢–b†ÖöçF‡2æÆVæwF‚ÓÓÒ’·°¢6Âæ–ææW$…DÔÂÒsÇ6Æ73Ò&ÆW'B#äæòWfVçG2v—F‚FFW2FòF—7Æ’öâF†R6ÆVæF"–WBãÂ÷âs°¢&WGW&ã°¢×Ð ¢òòÇv—2÷VâöâF†R5U%$TåBÖöçF‚†–b—B†2WfVçG2’ÂVÇ6RF†Rf—'7@¢òòÖöçF‚v—F‚WfVçG2(	BFöâwB&V÷Vâv†W&WfW"–÷RÆ7B'&÷w6VBFòà¢f"FöF”¶W’ÒæWrFFR‚’ævWDgVÆÅ–V"‚’²rÒr²7G&–ær†æWrFFR‚’ævWDÖöçF‚‚’²’çE7F'Bƒ"Âsr“°¢f"FVfVÇD¶W’ÒÖöçF‡2ç6öÖR†gVæ7F–öâ‡‚’·²&WGW&â‚æ¶W’ÓÓÒFöF”¶W“²×Ò’òFöF”¶W’¢ÖöçF‡5³Òæ¶W“° ¢òò6ÆVâÖöçF‚æc¢(’&WböâF†Rf"ÆVgBÂF†RÖöçF‚÷–V"G&÷F÷và¢òò6VçFW&VBÂæW‡B(¢öâF†Rf"&–v‡B†æòWfVçB6÷VçB’à¢f"†VFW%w&ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢†VFW%w&æ6Æ74æÖRÒv6ÂÖæbs°¢†VFW%w&æ–ææW$…DÔÂÐ¢sÆ'WGFöâG—SÒ&'WGFöâ"–CÒ&6Â×&Wb"6Æ73Ò&6ÂÖæf'Fâ"&–ÖÆ&VÃÒ%&Wf–÷W2ÖöçF‚#åÅÇS#3“Âö'WGFöãâr°¢sÇ6VÆV7B–CÒ&6ÂÖÖöçF‚×6VÆV7B"6Æ73Ò&6ÂÖÖöçF‚×6VÆV7B"&–ÖÆ&VÃÒ$§V×FòÖöçF‚#âr°¢ÖöçF‡2æÖ†gVæ7F–öâ†Ò’·°¢f"Æ&VÂÒæWrFFR†Òç’ÂÒæÒÂ’çFôÆö6ÆU7G&–ær‚vVâÕU2rÂ·²ÖöçFƒ¢vÆöærrÂ–V#¢vçVÖW&–2r×Ò“°¢&WGW&âsÆ÷F–öâfÇVSÒ"r²Òæ¶W’²r"r²†Òæ¶W’ÓÓÒFVfVÇD¶W’òr6VÆV7FVBr¢rr’²sâr²W66T‡FÖÂ†Æ&VÂ’²sÂö÷F–öãâs°¢×Ò’æ¦ö–â‚rr’°¢sÂ÷6VÆV7Câr°¢sÆ'WGFöâG—SÒ&'WGFöâ"–CÒ&6ÂÖæW‡B"6Æ73Ò&6ÂÖæf'Fâ"&–ÖÆ&VÃÒ$æW‡BÖöçF‚#åÅÇS#6Âö'WGFöãâs°¢6ÂæVæD6†–ÆB††VFW%w&“° ¢f"ÖöçF„†÷7BÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢ÖöçF„†÷7Bæ–BÒv6ÂÖÖöçF‚Ö†÷7Bs°¢6ÂæVæD6†–ÆB†ÖöçF„†÷7B“° ¢òòÆVvVæC¢§W7BF†RF‡&VR&–÷&—G’6öÆ÷"Ö&Æö6·2²w&W’f÷"WfW'—F†–ærVÇ6Rà¢òò…&Vv–öâ6öÆ÷'2vW&R&VÖ÷fVB(	BF†W’6öÆÆ–FVBv—F‚F†R7FvR6öÆ÷'2â¢f"ÆVvVæBÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢ÆVvVæBæ6Æ74æÖRÒv6ÂÖÆVvVæBs°¢ÆVvVæBæ–ææW$…DÔÂÐ¢sÇ7â6Æ73Ò&6ÂÖÆVvVæBÖÆ&VÂ#ä6ÆVæF"¶W“£Â÷7ãâr°¢²u7V&Ö—GFVBrÂt&öö¶VBrÂtGFVæF–æruÒæÖ†gVæ7F–öâ†²’·°¢&WGW&âsÇ7â6Æ73Ò&6ÂÖÆVvVæB×–ÆÂ"7G–ÆSÒ"r²7FvU7G–ÆR†²’²r#âr²W66T‡FÖÂ†²’²sÂ÷7ãâs°¢×Ò’æ¦ö–â‚rr’°¢sÇ7â6Æ73Ò&6ÂÖÆVvVæB×–ÆÂ"7G–ÆSÒ&&6¶w&÷VæC¢6c6cFcc¶6öÆ÷#¢3f#s#ƒ²#ä÷F†W"òæò7FGW3Â÷7ãâs°¢6ÂæVæD6†–ÆB†ÆVvVæB“° ¢gVæ7F–öâöä6†—6Æ–6²†çVÒ’·°¢f"6VÆV7F÷"Ò7G&–ær†çVÒ’æ6†$Bƒ’ÓÓÒvÒp¢òræ÷2Ö6&E¶FFÖÖçVÂÖ–CÒ"r²7G&–ær†çVÒ’ç6Æ–6Rƒ’²r%Òp¢¢ræ÷2Ö6&E¶FFÖWfVçBÖçVÓÒ"r²çVÒ²r%Òs°¢f"6&BÒF÷4w&–BçVW'•6VÆV7F÷"‡6VÆV7F÷"“°¢òò&–Ö'’&V†f–÷W#¢÷VâF†R&–6‚FWF–Â÷×W7G&–v‡Bg&öÒF†P¢òò6ÆVæF"6ò6Æ–6²vöW2FòF†RWfVçBÂæ÷B§W7B67&öÆÂ×FòÖ6&Bà¢–b†6&Bbb6&BåöÖöFÅ&V2bbG—Vöbv–æF÷ræ÷VäWfVçDÖöFÂÓÓÒvgVæ7F–öâr’·°¢v–æF÷ræ÷VäWfVçDÖöFÂ†6&BåöÖöFÅ&V2“°¢&WGW&ã°¢×Ð¢òòfÆÆ&6²†6&Bæ÷B'V–ÇB–WBòæò7F6†VB&V6÷&B“¢§V×²fÆ6‚à¢6WEf–Wr‚vw&–Br“°¢–b†6&B’·°¢6&Bç67&öÆÄ–çFõf–Wr‡·²&V†f–÷#¢w6Öö÷F‚rÂ&Æö6³¢v6VçFW"r×Ò“°¢6&Bæ6Æ74Æ—7Bç&VÖ÷fR‚v—2Ö†–v†Æ–v‡Br“°¢fö–B6&Bæöfg6WEv–GFƒ°¢6&Bæ6Æ74Æ—7BæFB‚v—2Ö†–v†Æ–v‡Br“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²6&Bæ6Æ74Æ—7Bç&VÖ÷fR‚v—2Ö†–v†Æ–v‡Br“²×ÒÂs“°¢×Ð¢×Ð ¢gVæ7F–öâ&VæFW$ÖöçF„'”¶W’†¶W’’·°¢f"ÖF6‚ÒÖöçF‡2æf–ÇFW"†gVæ7F–öâ‡‚’·²&WGW&â‚æ¶W’ÓÓÒ¶W“²×Ò•³Ó°¢–b‚ÖF6‚’ÖF6‚ÒÖöçF‡5³Ó°¢ÖöçF„†÷7Bæ–ææW$…DÔÂÒrs°¢ÖöçF„†÷7BæVæD6†–ÆB†'V–ÆD6ÆVæF$ÖöçF‚†ÖF6‚ç’ÂÖF6‚æÒÂ6öÖ&–æVBÂ7FFTÖÂöä6†—6Æ–6²’“°¢f"6VÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6ÂÖÖöçF‚×6VÆV7Br“°¢–b‡6VÂ’6VÂçfÇVRÒÖF6‚æ¶W“°¢×Ð ¢f"6VÂÒ†VFW%w&çVW'•6VÆV7F÷"‚r66ÂÖÖöçF‚×6VÆV7Br“°¢6VÂæFDWfVçDÆ—7FVæW"‚v6†ævRrÂgVæ7F–öâ‚’·²&VæFW$ÖöçF„'”¶W’‡6VÂçfÇVR“²×Ò“° ¢gVæ7F–öâ7FW†FVÇF’·°¢f"–G‚ÒÖöçF‡2æf–æD–æFW‚†gVæ7F–öâ‡‚’·²&WGW&â‚æ¶W’ÓÓÒ6VÂçfÇVS²×Ò“°¢f"æW‡BÒÖF‚æÖ‚ƒÂÖF‚æÖ–â†ÖöçF‡2æÆVæwF‚ÒÂ–G‚²FVÇF’“°¢&VæFW$ÖöçF„'”¶W’†ÖöçF‡5¶æW‡EÒæ¶W’“°¢×Ð¢†VFW%w&çVW'•6VÆV7F÷"‚r66Â×&Wbr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²7FW‚Ó“²×Ò“°¢†VFW%w&çVW'•6VÆV7F÷"‚r66ÂÖæW‡Br’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²7FWƒ“²×Ò“° ¢&VæFW$ÖöçF„'”¶W’†FVfVÇD¶W’“°¢×Ð ¢òò'6W2g&VRÖf÷&ÒWfVçBFFU÷7G"–çFò•4ò7F'EöFFR²VæEöFFRà¢òò†æFÆW2F‡&VR6öÖÖöâ6†W3 ¢òò$ÖöçF‚BÂ•••’"(i"7F'BÓÒVæB‡6–ævÆRÆÂÖF’¢òò$ÖöçF‚C(	4C"Â•••’"(i"6ÖRÖÖöçF‚&ævP¢òò$ÖöçFƒC(	2ÖöçFƒ"C"Â•••’"(i"7&÷72ÖÖöçF‚&ævP¢òò&WGW&ç2·²7F'EöFFRÂVæEöFFR×Ó²V—F†W"Ö’&RçVÆÂ–bF†R'6Rf–Ç2à¢gVæ7F–öâFW&—fTFFW4g&öÕFW‡B‡FW‡B’·°¢f"÷WBÒ·²7F'EöFFS¢çVÆÂÂVæEöFFS¢çVÆÂ×Ó°¢–b‚FW‡B’&WGW&â÷WC°¢f"ÖöçF‡2Ò·¶¦çV'“£ÆfV''V'“£"ÆÖ&6ƒ£2Æ&–Ã£BÆÖ“£RÆ§VæS£bÀ¢§VÇ“£rÆVwW7C£‚Ç6WFVÖ&W#£’Æö7Fö&W#£Ææ÷fVÖ&W#£ÆFV6VÖ&W#£"À¢¦ã£ÆfV#£"ÆÖ#£2Æ#£BÆ§Vã£bÆ§VÃ£rÆVs£‚Ç6W£’Æö7C£Ææ÷c£ÆFV3£'×Ó°¢gVæ7F–öâB†â’·²&WGW&â7G&–ær†â’çE7F'Bƒ"Âsr“²×Ð¢gVæ7F–öâ—6ò‡’ÂÒÂB’·²&WGW&â’²rÒr²B†Ò’²rÒr²B†B“²×Ð¢f"2Ò7G&–ær‡FW‡B“° ¢òòâ7&÷72ÖÖöçF‚&ævR(	B$ÖöçF‚B(	2ÖöçF‚BÂ•••’ ¢f"ÓÒ2æÖF6‚‚ò…´Õ¦×¥Ò²•ÅÇ2²…ÅÆG·³Ã'×Ò•ÅÇ2¥¾(	>(	BÕÕÅÇ2¢…´Õ¦×¥Ò²•ÅÇ2²…ÅÆG·³Ã'×Ò’ÃõÅÇ2²…ÅÆG·³G×Ò’ò“°¢–b†Ó’·°¢f"ÖÒÖöçF‡5¶Ó³ÒçFôÆ÷vW$66R‚•ÒÂÖ"ÒÖöçF‡5¶Ó³5ÒçFôÆ÷vW$66R‚•Ó°¢–b†ÖbbÖ"’·°¢f"“Ò'6T–çB†Ó³UÒÂ“°¢÷WBç7F'EöFFRÒ—6ò‡“ÂÖÂ'6T–çB†Ó³%ÒÂ’“°¢÷WBæVæEöFFRÒ—6ò‡“ÂÖ"Â'6T–çB†Ó³EÒÂ’“°¢&WGW&â÷WC°¢×Ð¢×Ð¢òò"â6ÖRÖÖöçF‚&ævR(	B$ÖöçF‚C(	4C"Â•••’ ¢f"Ó"Ò2æÖF6‚‚ò…´Õ¦×¥Ò²•ÅÇ2²…ÅÆG·³Ã'×Ò•ÅÇ2¥¾(	>(	BÕÕÅÇ2¢…ÅÆG·³Ã'×Ò’ÃõÅÇ2²…ÅÆG·³G×Ò’ò“°¢–b†Ó"’·°¢f"Öã"ÒÖöçF‡5¶Ó%³ÒçFôÆ÷vW$66R‚•Ó°¢–b†Öã"’·°¢f"“"Ò'6T–çB†Ó%³EÒÂ“°¢÷WBç7F'EöFFRÒ—6ò‡“"ÂÖã"Â'6T–çB†Ó%³%ÒÂ’“°¢÷WBæVæEöFFRÒ—6ò‡“"ÂÖã"Â'6T–çB†Ó%³5ÒÂ’“°¢&WGW&â÷WC°¢×Ð¢×Ð¢òò2â6–ævÆRFFR(	B$ÖöçF‚BÂ•••’ ¢f"Ó2Ò2æÖF6‚‚ò…´Õ¦×¥Ò²•ÅÇ2²…ÅÆG·³Ã'×Ò’ÃõÅÇ2²…ÅÆG·³G×Ò’ò“°¢–b†Ó2’·°¢f"Öã2ÒÖöçF‡5¶Ó5³ÒçFôÆ÷vW$66R‚•Ó°¢–b†Öã2’·°¢f"C2Ò—6ò‡'6T–çB†Ó5³5ÒÂ’ÂÖã2Â'6T–çB†Ó5³%ÒÂ’“°¢÷WBç7F'EöFFRÒC3°¢÷WBæVæEöFFRÒC3°¢&WGW&â÷WC°¢×Ð¢×Ð¢òò6"âD’Ôd•%5B7&÷72ÖÖöçF‚&ævR(	B$BÖöçF‚(	2BÖöçF‚•••’ ¢f"FcÒ2æÖF6‚‚ò…ÅÆG·³Ã'×Ò•ÅÇ2²…´Õ¦×¥Ò²•ÅÇ2¥¾(	>(	BÕÕÅÇ2¢…ÅÆG·³Ã'×Ò•ÅÇ2²…´Õ¦×¥Ò²’ÃõÅÇ2²…ÅÆG·³G×Ò’ò“°¢–b†Fc’·°¢f"FfÒÖöçF‡5¶Fc³%ÒçFôÆ÷vW$66R‚•ÒÂFf"ÒÖöçF‡5¶Fc³EÒçFôÆ÷vW$66R‚•Ó°¢–b†FfbbFf"’·°¢f"Fg’Ò'6T–çB†Fc³UÒÂ“°¢÷WBç7F'EöFFRÒ—6ò†Fg’ÂFfÂ'6T–çB†Fc³ÒÂ’“°¢÷WBæVæEöFFRÒ—6ò†Fg’ÂFf"Â'6T–çB†Fc³5ÒÂ’“°¢&WGW&â÷WC°¢×Ð¢×Ð¢òò62âD’Ôd•%5B6ÖRÖÖöçF‚&ævR(	B$N(	4BÖöçF‚•••’"†Rærâ#BÓbÖ’##r"¢f"Fc"Ò2æÖF6‚‚ò…ÅÆG·³Ã'×Ò•ÅÇ2¥¾(	>(	BÕÕÅÇ2¢…ÅÆG·³Ã'×Ò•ÅÇ2²…´Õ¦×¥Ò²’ÃõÅÇ2²…ÅÆG·³G×Ò’ò“°¢–b†Fc"’·°¢f"FfÒÒÖöçF‡5¶Fc%³5ÒçFôÆ÷vW$66R‚•Ó°¢–b†FfÒ’·°¢f"Fg“"Ò'6T–çB†Fc%³EÒÂ“°¢÷WBç7F'EöFFRÒ—6ò†Fg“"ÂFfÒÂ'6T–çB†Fc%³ÒÂ’“°¢÷WBæVæEöFFRÒ—6ò†Fg“"ÂFfÒÂ'6T–çB†Fc%³%ÒÂ’“°¢&WGW&â÷WC°¢×Ð¢×Ð¢òò6BâD’Ôd•%5B6–ævÆR(	B$BÖöçF‚•••’"†Rærâ#BÖ’##r"¢f"Fc2Ò2æÖF6‚‚ò…ÅÆG·³Ã'×Ò•ÅÇ2²…´Õ¦×¥Ò²’ÃõÅÇ2²…ÅÆG·³G×Ò’ò“°¢–b†Fc2’·°¢f"FfÓ2ÒÖöçF‡5¶Fc5³%ÒçFôÆ÷vW$66R‚•Ó°¢–b†FfÓ2’·°¢f"FfBÒ—6ò‡'6T–çB†Fc5³5ÒÂ’ÂFfÓ2Â'6T–çB†Fc5³ÒÂ’“°¢÷WBç7F'EöFFRÒFfC²÷WBæVæEöFFRÒFfC°¢&WGW&â÷WC°¢×Ð¢×Ð¢òò6Râ•4ò(	B%•••’ÔÔÒÔDB"†÷F–öæÆÇ’&ævR¢f"Ff’Ò2æÖF6‚‚ò…ÅÆG·³G×Ò’Ò…ÅÆG·³Ã'×Ò’Ò…ÅÆG·³Ã'×Ò’ƒó¥ÅÇ2¥¾(	>(	BÕÕÅÇ2¢…ÅÆG·³G×Ò’Ò…ÅÆG·³Ã'×Ò’Ò…ÅÆG·³Ã'×Ò’“òò“°¢–b†Ff’’·°¢÷WBç7F'EöFFRÒ—6ò‡'6T–çB†Ff•³ÒÂ’Â'6T–çB†Ff•³%ÒÂ’Â'6T–çB†Ff•³5ÒÂ’“°¢÷WBæVæEöFFRÒFf•³EÒò—6ò‡'6T–çB†Ff•³EÒÂ’Â'6T–çB†Ff•³UÒÂ’Â'6T–çB†Ff•³eÒÂ’’¢÷WBç7F'EöFFS°¢&WGW&â÷WC°¢×Ð¢òò6bâÖöçF‚²–V"öæÇ’(	B$ÖöçF‚•••’"†Rærâ$Ö’##r"’Óâ7BöbÖöçF€¢f"Ff×’Ò2æÖF6‚‚ò…´Õ¦×¥Ò²•ÅÇ2²…ÅÆG·³G×Ò’ò“°¢–b†Ff×’’·°¢f"F×’ÒÖöçF‡5¶Ff×•³ÒçFôÆ÷vW$66R‚•Ó°¢–b†F×’’·°¢f"F×–BÒ—6ò‡'6T–çB†Ff×•³%ÒÂ’ÂF×’Â“°¢÷WBç7F'EöFFRÒF×–C²÷WBæVæEöFFRÒF×–C°¢&WGW&â÷WC°¢×Ð¢×Ð ¢òòBÓbâçVÖW&–26†÷'F†æB(	BævVÆw27&VG6†VWB†&—C¢#Bó#‚"À¢òò#Bó#‚ÓBó3"Â#ó’Òó"ó#b"Â#Bó#‚Ó3"âÖ—76–ær–V"—0¢òòf÷'v&BÖÆöö¶–æs¢77VÖRF†R7W'&VçB–V"Â&öÆÂFòæW‡B–V"v†VâF†P¢òòFFR76VBÖ÷&RF†âãbvVV·2vòà¢gVæ7F–öâ—"‡B’·°¢–b‚B’&WGW&âçVÆÃ°¢f"’Ò'6T–çB‡BÂ“°¢&WGW&â’Âò’²#¢“°¢×Ð¢gVæ7F–öâ–æfW%–V"†ÖòÂB’·°¢f"æ÷rÒæWrFFR‚“°¢f"’Òæ÷rævWDgVÆÅ–V"‚“°¢–b†æ÷rÒæWrFFR‡’ÂÖòÒÂB’âCR¢ƒcC’’³Ò°¢&WGW&â“°¢×Ð¢gVæ7F–öâö´ÔB†ÖòÂB’·²&WGW&âÖòãÒbbÖòÃÒ"bbBãÒbbBÃÒ3²×Ð¢òòBâ$ÒôBÒÒôB"v—F‚÷F–öæÂ–V'2öâV—F†W"6–FP¢f"ãÒ2æÖF6‚‚ò…ÅÆG·³Ã'×Ò•ÅÂò…ÅÆG·³Ã'×Ò’ƒó¥ÅÂò…ÅÆG·³"ÃG×Ò’“õÅÇ2¥¾(	>(	BÕÕÅÇ2¢…ÅÆG·³Ã'×Ò•ÅÂò…ÅÆG·³Ã'×Ò’ƒó¥ÅÂò…ÅÆG·³"ÃG×Ò’“òò“°¢–b†ã’·°¢f"Ò'6T–çB†ã³ÒÂ’Â"Ò'6T–çB†ã³%ÒÂ“°¢f"#Ò'6T–çB†ã³EÒÂ’Â#"Ò'6T–çB†ã³UÒÂ“°¢–b†ö´ÔB†Â"’bbö´ÔB†#Â#"’’·°¢f"–Ò—"†ã³5Ò’ÇÂ—"†ã³eÒ’ÇÂ–æfW%–V"†Â"“°¢f"–"Ò—"†ã³eÒ’ÇÂ–°¢–b‡–"ÓÓÒ–bb†#Â’’–"Ò–²²òò"ó3Òó"w&2–V ¢÷WBç7F'EöFFRÒ—6ò‡–ÂÂ"“°¢÷WBæVæEöFFRÒ—6ò‡–"Â#Â#"“°¢&WGW&â÷WC°¢×Ð¢×Ð¢òòRâ$ÒôBÒB"‡6ÖRÖöçF‚’v—F‚÷F–öæÂ–V"(	B–æ6ÂâG&–Æ–æp¢òò6öÖÖ×–V"Æ–¶R#’óÓ"Â##b"†ã%³UÒ“²&VfW"—B÷fW"–æfW&Væ6Rà¢f"ã"Ò2æÖF6‚‚ò…ÅÆG·³Ã'×Ò•ÅÂò…ÅÆG·³Ã'×Ò’ƒó¥ÅÂò…ÅÆG·³"ÃG×Ò’“õÅÇ2¥¾(	>(	BÕÕÅÇ2¢…ÅÆG·³Ã'×Ò’ƒòÅÆB¥ÅÂò’ƒó¢ÃõÅÇ2¢…ÅÆG·³"ÃG×Ò’“òò“°¢–b†ã"’·°¢f"3Ò'6T–çB†ã%³ÒÂ’Â3"Ò'6T–çB†ã%³%ÒÂ’Â32Ò'6T–çB†ã%³EÒÂ“°¢–b†ö´ÔB†3Â3"’bb32ãÒbb32ÃÒ3’·°¢f"–2Ò—"†ã%³5Ò’ÇÂ—"†ã%³UÒ’ÇÂ–æfW%–V"†3Â3"“°¢÷WBç7F'EöFFRÒ—6ò‡–2Â3Â3"“°¢÷WBæVæEöFFRÒ—6ò‡–2Â3Â32“°¢&WGW&â÷WC°¢×Ð¢×Ð¢òòbâ6–ævÆR$ÒôB"v—F‚÷F–öæÂ–V ¢f"ã2Ò2æÖF6‚‚ò…ÅÆG·³Ã'×Ò•ÅÂò…ÅÆG·³Ã'×Ò’ƒó¥ÅÂò…ÅÆG·³"ÃG×Ò’“òò“°¢–b†ã2’·°¢f"SÒ'6T–çB†ã5³ÒÂ’ÂS"Ò'6T–çB†ã5³%ÒÂ“°¢–b†ö´ÔB†SÂS"’’·°¢f"–RÒ—"†ã5³5Ò’ÇÂ–æfW%–V"†SÂS"“°¢f"FRÒ—6ò‡–RÂSÂS"“°¢÷WBç7F'EöFFRÒFS°¢÷WBæVæEöFFRÒFS°¢&WGW&â÷WC°¢×Ð¢×Ð¢&WGW&â÷WC°¢×Ð ¢òò&6²Ö6ö×B6†–Ò(	BöÆFW"6ÆÆW'2vçB§W7BF†R7F'BFFRà¢gVæ7F–öâFW&—fU7F'DFFTg&öÕFW‡B‡FW‡B’·°¢&WGW&âFW&—fTFFW4g&öÕFW‡B‡FW‡B’ç7F'EöFFS°¢×Ð ¢òò)H)H&VÇF–ÖR7V'67&—F–öâ)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòF†RV6†òG&–vvW'2eTÄÂw&–B&V'V–ÆBâ–bF†RW6W"—2Ö–BÖVF—B‡G—–æp¢òò–çFòâ÷VâVF—F÷"’Â&V'V–ÆF–ærv÷VÆBF‡&÷rv’F†V—"Vç6fVB–çWB(	@¢òò6òv†–ÆRâVF—F÷"—2fö7W6VBvR§W7BÖ&²F†R&Vg&W6‚2VæF–æræ@¢òòfÇW6‚—BF†RÖöÖVçBF†RVF—F÷"6Æ÷6W2òÆ÷6W2fö7W2à¢f"ö÷4V6†õVæF–ærÒfÇ6S°¢gVæ7F–öâw&–D†47F—fTVF—F÷"‚’·°¢–b‚F÷4w&–B’&WGW&âfÇ6S°¢f"VBÒF÷4w&–BçVW'•6VÆV7F÷"‚vFWF–Ç2æ÷2ÖVF—E¶÷VåÒr“°¢&WGW&â†VBbbFö7VÖVçBæ7F—fTVÆVÖVçBbbVBæ6öçF–ç2†Fö7VÖVçBæ7F—fTVÆVÖVçB’“°¢×Ð¢gVæ7F–öâ÷4V6†õ&VæFW"†VÖ–Â’·°¢–b†w&–D†47F—fTVF—F÷"‚’’·²ö÷4V6†õVæF–ærÒG'VS²&WGW&ã²×Ð¢ö÷4V6†õVæF–ærÒfÇ6S°¢&VæFW$÷2†VÖ–Â“°¢×Ð¢gVæ7F–öâv—&TV6†ôfÇW6‚†VÖ–Â’·°¢–b‚F÷4w&–BæFF6WBæV6†õv—&VB’&WGW&ã°¢F÷4w&–BæFF6WBæV6†õv—&VBÒss°¢gVæ7F–öâÖ–&TfÇW6‚‚’·°¢–b‚ö÷4V6†õVæF–ær’&WGW&ã°¢òòv—BF–6²6òfö7W2†26WGFÆVB‡FövvÆRöfö7W6÷WBf—&R&RÖÖ÷fR’à¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·°¢–b…ö÷4V6†õVæF–ærbbw&–D†47F—fTVF—F÷"‚’’·°¢ö÷4V6†õVæF–ærÒfÇ6S°¢&VæFW$÷2†VÖ–Â“°¢×Ð¢×ÒÂS“°¢×Ð¢F÷4w&–BæFDWfVçDÆ—7FVæW"‚wFövvÆRrÂÖ–&TfÇW6‚ÂG'VR“°¢F÷4w&–BæFDWfVçDÆ—7FVæW"‚vfö7W6÷WBrÂÖ–&TfÇW6‚“°¢×Ð ¢f"&VÇF–ÖT6†ææVÂÒçVÆÃ°¢gVæ7F–öâ6WGW&VÇF–ÖR†VÖ–Â’·°¢v—&TV6†ôfÇW6‚†VÖ–Â“°¢–b‡&VÇF–ÖT6†ææVÂ’·°¢G'’·²&VÇF–ÖT6†ææVÂçVç7V'67&–&R‚“²×Ò6F6‚†R’··×Ð¢&VÇF–ÖT6†ææVÂÒçVÆÃ°¢×Ð¢G'’·°¢&VÇF–ÖT6†ææVÂÒ6"æ6†ææVÂ‚v÷2×&VÇF–ÖRÒr²ÖF‚ç&æFöÒ‚’çFõ7G&–ærƒ3b’ç6Æ–6Rƒ"Ã‚’¢æöâ‚w÷7Fw&W5ö6†ævW2rÂ·²WfVçC¢r¢rÂ66†VÖ¢wV&Æ–2rÂF&ÆS¢vWfVçE÷7FFRr×ÒÂgVæ7F–öâ‚’·°¢÷4V6†õ&VæFW"†VÖ–Â“°¢×Ò¢æöâ‚w÷7Fw&W5ö6†ævW2rÂ·²WfVçC¢r¢rÂ66†VÖ¢wV&Æ–2rÂF&ÆS¢vÖçVÅöWfVçG2r×ÒÂgVæ7F–öâ‚’·°¢÷4V6†õ&VæFW"†VÖ–Â“°¢×Ò¢æöâ‚w÷7Fw&W5ö6†ævW2rÂ·²WfVçC¢r¢rÂ66†VÖ¢wV&Æ–2rÂF&ÆS¢vWfVçEö6†Br×ÒÂgVæ7F–öâ‚’·°¢–b‡G—VöbÆöD6†D6÷VçG2ÓÓÒvgVæ7F–öâr’ÆöD6†D6÷VçG2‚“°¢–b‡G—Vöb÷&VÆöD÷Vä6†BÓÓÒvgVæ7F–öâr’÷&VÆöD÷Vä6†B‚“°¢×Ò¢ç7V'67&–&R‚“°¢×Ò6F6‚†R’·°¢òò&VÇF–ÖR—2æ–6R×FòÖ†fS²–b—Bf–Ç2ÂöÆÆ–æröâW6W"7F–öâ7F–ÆÂv÷&·0¢6öç6öÆRçv&â‚u&VÇF–ÖR6WGWf–ÆVC¢rÂR“°¢×Ð¢×Ð ¢òò)H)H55b–×÷'BöW‡÷'B)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢f"55eô4ôÅTÔå2Ò²vWfVçEöçVÒrÂw7FGW5÷Fw2rÂw7FGW2rÂw7V¶W"rÂw&–÷&—G•ö÷fW'&–FRrÂwG&6²rÂw6fVBrÂv†–FFVârÂwW&vVçBrÂvæ÷FW2rÂvGFVæE÷fW&F–7BrÂw÷7FÖ÷'FVÒuÓ°¢òò÷F–öæÂöâ–×÷'C¢öÆFW"55g2&VFFRF†W6Râv†VâF†R6öÇVÖâ—2'6Vç@¢òòvRÆVfRF†RW†—7F–ærD"fÇVRVçF÷V6†VB–ç7FVBöbv—–ær—Bà¢f"55eôõD”ôäÂÒ²w7FGW5÷Fw2rÂvGFVæE÷fW&F–7BrÂw÷7FÖ÷'FVÒuÓ° ¢gVæ7F–öâFô77d6VÆÂ‡b’·°¢–b‡bÓÓÒçVÆÂÇÂbÓÓÒVæFVf–æVB’&WGW&ârs°¢bÒ7G&–ær‡b“°¢–b‡bæ–æFW„öb‚rÂr’ãÒÇÂbæ–æFW„öb‚r"r’ãÒÇÂbæ–æFW„öb‚uÅÆâr’ãÒ’·°¢&WGW&âr"r²bç&WÆ6R‚ò"örÂr""r’²r"s°¢×Ð¢&WGW&âc°¢×Ð ¢gVæ7F–öâ&÷w5Fô77b††VFW'2Â&÷w2’·°¢f"Æ–æW2Ò¶†VFW'2æÖ‡Fô77d6VÆÂ’æ¦ö–â‚rÂr•Ó°¢&÷w2æf÷$V6‚†gVæ7F–öâ‡&÷r’·°¢Æ–æW2çW6‚††VFW'2æÖ†gVæ7F–öâ†‚’·²&WGW&âFô77d6VÆÂ‡&÷u¶…Ò“²×Ò’æ¦ö–â‚rÂr’“°¢×Ò“°¢&WGW&âÆ–æW2æ¦ö–â‚uÅÆâr’²uÅÆâs°¢×Ð ¢gVæ7F–öâ'6T77dÆ–æR†Æ–æR’·°¢f"6VÆÇ2ÒµÓ²f"’ÒÂ7W'&VçBÒrrÂ–åV÷FRÒfÇ6S°¢v†–ÆR†’ÂÆ–æRæÆVæwF‚’·°¢f"6‚ÒÆ–æU¶•Ó°¢–b†–åV÷FR’·°¢–b†6‚ÓÓÒr"r’·°¢–b†Æ–æU¶’³ÒÓÓÒr"r’·²7W'&VçB³Òr"s²’³Ò#²6öçF–çVS²×Ð¢–åV÷FRÒfÇ6S²’²³²6öçF–çVS°¢×Ð¢7W'&VçB³Ò6ƒ²’²³°¢×ÒVÇ6R·°¢–b†6‚ÓÓÒr"r’·²–åV÷FRÒG'VS²’²³²6öçF–çVS²×Ð¢–b†6‚ÓÓÒrÂr’·²6VÆÇ2çW6‚†7W'&VçB“²7W'&VçBÒrs²’²³²6öçF–çVS²×Ð¢7W'&VçB³Ò6ƒ²’²³°¢×Ð¢×Ð¢6VÆÇ2çW6‚†7W'&VçB“°¢&WGW&â6VÆÇ3°¢×Ð ¢gVæ7F–öâ'6T77b‡FW‡B’·°¢òò7G&—$ôÒÂæ÷&ÖÆ—¦RæWvÆ–æW0¢FW‡BÒFW‡Bç&WÆ6R‚õåÅÇTdTdbòÂrr’ç&WÆ6R‚õÅÇ%ÅÆãòörÂuÅÆâr“°¢òò†æFÆR×VÇF’ÖÆ–æRV÷FVB6VÆÇ2'’vÆ¶–ærF†R7G&–æp¢f"&÷w2ÒµÓ²f"’Ò²f"7W"Òrs²f"&÷t6VÆÇ2ÒµÓ²f"–åÒfÇ6S°¢v†–ÆR†’ÂFW‡BæÆVæwF‚’·°¢f"6‚ÒFW‡E¶•Ó°¢–b†–å’·°¢–b†6‚ÓÓÒr"r’·°¢–b‡FW‡E¶’³ÒÓÓÒr"r’·²7W"³Òr"s²’³Ò#²6öçF–çVS²×Ð¢–åÒfÇ6S²’²³²6öçF–çVS°¢×Ð¢7W"³Ò6ƒ²’²³°¢×ÒVÇ6R·°¢–b†6‚ÓÓÒr"r’·²–åÒG'VS²’²³²6öçF–çVS²×Ð¢–b†6‚ÓÓÒrÂr’·²&÷t6VÆÇ2çW6‚†7W"“²7W"Òrs²’²³²6öçF–çVS²×Ð¢–b†6‚ÓÓÒuÅÆâr’·²&÷t6VÆÇ2çW6‚†7W"“²&÷w2çW6‚‡&÷t6VÆÇ2“²&÷t6VÆÇ2ÒµÓ²7W"Òrs²’²³²6öçF–çVS²×Ð¢7W"³Ò6ƒ²’²³°¢×Ð¢×Ð¢–b†7W"ÓÒrrÇÂ&÷t6VÆÇ2æÆVæwF‚â’·²&÷t6VÆÇ2çW6‚†7W"“²&÷w2çW6‚‡&÷t6VÆÇ2“²×Ð¢–b‡&÷w2æÆVæwF‚ÓÓÒ’&WGW&â·²†VFW'3¢µÒÂ&÷w3¢µÒ×Ó°¢f"†VFW'2Ò&÷w5³ÒæÖ†gVæ7F–öâ†‚’·²&WGW&â‚çG&–Ò‚“²×Ò“°¢f"FFÒ&÷w2ç6Æ–6Rƒ’æf–ÇFW"†gVæ7F–öâ‡"’·²&WGW&â"ç6öÖR†gVæ7F–öâ†2’·²&WGW&â2bb2çG&–Ò‚’æÆVæwF‚â²×Ò“²×Ò¢æÖ†gVæ7F–öâ†6VÆÇ2’·°¢f"ö&¢Ò··×Ó°¢†VFW'2æf÷$V6‚†gVæ7F–öâ†‚Â–G‚’·²ö&¥¶…ÒÒ6VÆÇ5¶–G…ÒÓÒVæFVf–æVBò6VÆÇ5¶–G…Ò¢rs²×Ò“°¢&WGW&âö&£°¢×Ò“°¢&WGW&â·²†VFW'3¢†VFW'2Â&÷w3¢FF×Ó°¢×Ð ¢gVæ7F–öâ6öW&6T77efÇVR†6öÂÂ&r’·°¢f"bÒ‡&rÓÒçVÆÂ’òrr¢7G&–ær‡&r’çG&–Ò‚“°¢–b†6öÂÓÓÒvWfVçEöçVÒr’·°¢–b‚b’&WGW&âçVÆÃ°¢f"âÒ'6T–çB‡bÂ“°¢&WGW&âçVÖ&W"æ—4f–æ—FR†â’òâ¢çVÆÃ°¢×Ð¢–b†6öÂÓÓÒw6fVBrÇÂ6öÂÓÓÒv†–FFVârÇÂ6öÂÓÓÒwW&vVçBr’·°¢–b‚õâ‡G'VWÃÇ–W7Ç—Æöâ’Bö’çFW7B‡b’’&WGW&âG'VS°¢–b‚õâ†fÇ6WÃÆæ÷ÆçÆöfgÂ’Bö’çFW7B‡b’’&WGW&âfÇ6S°¢&WGW&âfÇ6S°¢×Ð¢òò—VÆ–æR7FvW2(	B—R×6W&FVBÆ—7B(i"æ÷&ÖÆ—¦VBFW‡EµÒ'&’à¢–b†6öÂÓÓÒw7FGW5÷Fw2r’·°¢&WGW&âæ÷&ÖÆ—¦U7FvUFw2‡bç7Æ—B‚wÂr’“°¢×Ð¢òòFW‡B6öÇVÖç3¢V×G’&V6öÖW2çVÆÂ6òvRFöâwB&Æ÷rv’åTÄÇ2Fòrp¢&WGW&âbÓÓÒrròçVÆÂ¢c°¢×Ð ¢gVæ7F–öâF÷væÆöD77b†f–ÆVæÖRÂ77eFW‡B’·°¢f"&Æö"ÒæWr&Æö"…¶77eFW‡EÒÂ·²G—S¢wFW‡Bö77c¶6†'6WC×WFbÓƒ²r×Ò“°¢f"W&ÂÒU$Âæ7&VFTö&¦V7EU$Â†&Æö"“°¢f"ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vr“°¢æ‡&VbÒW&Ã²æF÷væÆöBÒf–ÆVæÖS°¢Fö7VÖVçBæ&öG’æVæD6†–ÆB†“²æ6Æ–6²‚“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²U$Âç&Wfö¶Tö&¦V7EU$Â‡W&Â“²ç&VÖ÷fR‚“²×ÒÂ“°¢×Ð ¢gVæ7F–öâF–fe&÷w2†7W'&VçE&÷w2Â–æ6öÖ–æu&÷w2’·°¢f"'”çVÒÒ··×Ó°¢7W'&VçE&÷w2æf÷$V6‚†gVæ7F–öâ‡"’·²'”çVÕ·"æWfVçEöçVÕÒÒ#²×Ò“°¢f"FFVBÒµÒÂWFFVBÒµÒÂVæ6†ævVBÒµÓ°¢–æ6öÖ–æu&÷w2æf÷$V6‚†gVæ7F–öâ‡&÷r’·°¢–b‡&÷ræWfVçEöçVÒÓÒçVÆÂ’&WGW&ã²òò6¶—–çfÆ–@¢f"W†—7F–ærÒ'”çVÕ·&÷ræWfVçEöçVÕÓ°¢–b‚W†—7F–ær’·²FFVBçW6‚‡&÷r“²&WGW&ã²×Ð¢f"6†ævVBÒ55eô4ôÅTÔå2ç6öÖR†gVæ7F–öâ†2’·°¢–b†2ÓÓÒvWfVçEöçVÒr’&WGW&âfÇ6S°¢f"ÒW†—7F–æu¶5Ó²f""Ò&÷u¶5Ó°¢–b†"ÓÓÒVæFVf–æVB’&WGW&âfÇ6S²òò6öÇVÖâæ÷B7WÆ–VB'’F†—2–×÷'@¢–b†ÓÓÒçVÆÂbb"ÓÓÒçVÆÂ’&WGW&âfÇ6S°¢–b†ÓÓÒfÇ6Rbb†"ÓÓÒçVÆÂÇÂ"ÓÓÒfÇ6R’’&WGW&âfÇ6S°¢–b†"ÓÓÒfÇ6Rbb†ÓÓÒçVÆÂÇÂÓÓÒfÇ6R’’&WGW&âfÇ6S°¢&WGW&â7G&–ær†ÓÒçVÆÂòrr¢’ÓÒ7G&–ær†"ÓÒçVÆÂòrr¢"“°¢×Ò“°¢†6†ævVBòWFFVB¢Væ6†ævVB’çW6‚‡&÷r“°¢×Ò“°¢&WGW&â·²FFVC¢FFVBÂWFFVC¢WFFVBÂVæ6†ævVC¢Væ6†ævVB×Ó°¢×Ð ¢òò)H)HFööÆ&"æVÇ3¢Væ—fW'6Â)ÉR²W62F—6Ö—72)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòWfW'’FööÆ&"æVÂ„FBÖçVÆÇ’òf–æBæWrò7FRVÖ–Âò6²’ð¢òò7&VG6†VWBò6ÆVæF"7–æ2’—2æFBÖWfVçBÖ6&F–æ¦V7FVBBF†RF÷ö`¢òòF†Rw&–Bâv—fRV6‚7FæF&BF÷×&–v‡B)ÉRÂæBÆWBW626Æ÷6Rv†–6†WfW"—0¢òò÷Vâ(	BF†RfÖ–Æ–"v’Fò&6²÷WBöbæVÂâ…F†RWfVçBÖöFÂÂv†Và¢òò÷VâÂ¶VW2W62&–÷&—G’6–æ6R—B6—G2öâF÷â¢gVæ7F–öâöÖ÷VçEæVÄ6Æ÷6R‡æVÂ’·°¢–b‚æVÂÇÂæVÂçVW'•6VÆV7F÷"‚ræ÷2×æVÂ×‚r’’&WGW&ã°¢f"‚ÒFö7VÖVçBæ7&VFTVÆVÖVçB‚v'WGFöâr“°¢‚çG—RÒv'WGFöâs²‚æ6Æ74æÖRÒv÷2×æVÂ×‚s°¢‚ç6WDGG&–'WFR‚v&–ÖÆ&VÂrÂt6Æ÷6Rr“²‚çF—FÆRÒt6Æ÷6R„W62’s°¢‚æ–ææW$…DÔÂÒrgF–ÖW3²s°¢‚æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²æVÂç&VÖ÷fR‚“²×Ò“°¢æVÂæVæD6†–ÆB‡‚“°¢×Ð¢–b‚v–æF÷råö÷5æVÄW65v—&VB’·°¢v–æF÷råö÷5æVÄW65v—&VBÒG'VS°¢Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·°¢–b†Ræ¶W’ÓÒtW66Rr’&WGW&ã°¢f"÷bÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vWfVçBÖÖöFÂr“°¢–b†÷bbb÷bæ†4GG&–'WFR‚v†–FFVâr’’&WGW&ã²òòÖöFÂ÷vç2W62v†–ÆR÷Và¢f"æVÂÒF÷4w&–BbbF÷4w&–BçVW'•6VÆV7F÷"‚s§66÷RâæFBÖWfVçBÖ6&Br“°¢–b‡æVÂ’æVÂç&VÖ÷fR‚“°¢×Ò“°¢×Ð ¢gVæ7F–öâ÷Vä77eæVÂ†VÖ–Â’·°¢òòFövvÆR6Æ÷6R–b÷Và¢f"W†—7F–ærÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v77b×æVÂr“°¢–b†W†—7F–ær’·²W†—7F–ærç&VÖ÷fR‚“²&WGW&ã²×Ð ¢f"æVÂÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢æVÂæ–BÒv77b×æVÂs°¢æVÂæ6Æ74æÖRÒvFBÖWfVçBÖ6&Bs°¢æVÂæ–ææW$…DÔÂÐ¢sÆƒ3ä55b–×÷'BòW‡÷'CÂöƒ3âr°¢sÇ7G–ÆSÒ&Ö&v–ã£'ƒ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ"“¶föçB×6—¦S£ã—&VÓ²#âr°¢tW‡÷'B7W'&VçB÷27FFR255bÂVF—B–âç’7&VG6†VWBFööÂÂF†Vâ&R×WÆöBâr°¢t6öÇVÖç3¢Æ6öFSâr²55eô4ôÅTÔå2æ¦ö–â‚rÂr’²sÂö6öFSââ&ööÆVç3¢Æ6öFSçG'VSÂö6öFSâòÆ6öFSæfÇ6SÂö6öFSââr°¢sÆ6öFSç7FGW5÷Fw3Âö6öFSâ—2—RÖ¦ö–æVBÆ—7Böb—VÆ–æR7FvW2ÂRærâÆ6öFSå7V&Ö—GFVGÄÖVWF–ær†VÆGÄ&öö¶VCÂö6öFSâ†÷F–öæÂ(	BöÖ—BF†R6öÇVÖâFòÆVfR7FvW2VçF÷V6†VB’âr°¢sÂ÷âr°¢sÆF—b6Æ73Ò&FBÖ7F–öç2"7G–ÆSÒ&Ö&v–âÖ&÷GFöÓ£‡ƒ²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’"–CÒ&77bÖW‡÷'BÖ'Fâ#äF÷væÆöB7W'&VçB55cÂö'WGFöãâr°¢sÆÆ&VÂ6Æ73Ò'&–Ö'’"7G–ÆSÒ&7W'6÷#§ö–çFW#¶F—7Æ“¦–æÆ–æRÖfÆWƒ¶Æ–vâÖ—FV×3¦6VçFW#·FF–æs£—‚gƒ¶&6¶w&÷VæC§f"‚ÒÖ"Öfr“¶6öÆ÷#§f"‚ÒÖ"Ö&r“¶&÷&FW"×&F—W3£‡ƒ¶föçB×vV–v‡C£c¶föçB×6—¦S£ã—&VÓ²#âr°¢uWÆöB55n(
br°¢sÆ–çWBG—SÒ&f–ÆR"–CÒ&77bÖf–ÆR"66WCÒ"æ77bÇFW‡Bö77b"7G–ÆSÒ&F—7Æ“¦æöæS²#âr°¢sÂöÆ&VÃâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'6V6öæF'’"–CÒ&77bÖ6æ6VÂÖ'Fâ#ä6Æ÷6SÂö'WGFöãâr°¢sÂöF—câr°¢sÆF—b–CÒ&77b×&Wf–Wr"7G–ÆSÒ&Ö&v–â×F÷£‡ƒ²#ãÂöF—câs° ¢F÷4w&–Bæ–ç6W'D&Vf÷&R‡æVÂÂF÷4w&–Bæf—'7D6†–ÆB“°¢öÖ÷VçEæVÄ6Æ÷6R‡æVÂ“°¢æVÂçVW'•6VÆV7F÷"‚r677bÖ6æ6VÂÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²æVÂç&VÖ÷fR‚“²×Ò“° ¢òòW‡÷'B7W'&VçB7FFP¢æVÂçVW'•6VÆV7F÷"‚r677bÖW‡÷'BÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢6"æg&öÒ‚vWfVçE÷7FFRr’ç6VÆV7B‚r¢r’æ÷&FW"‚vWfVçEöçVÒr’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"’·²7FGW2‚tW‡÷'Bf–ÆVC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“²&WGW&ã²×Ð¢f"&÷w2Ò&W7æFFÇÂµÓ°¢òò–bV×G’Âv—fR†VFW"ÖöæÇ’FV×ÆFP¢–b‡&÷w2æÆVæwF‚ÓÓÒ’&÷w2ÒµÓ°¢òòfÆGFVâF†R7FGW5÷Fw2FW‡EµÒ–çFò—RÖ¦ö–æVB7G&–ær6ò—@¢òò&÷VæB×G&—26ÆVæÇ’F‡&÷Vv‚7&VG6†VWB†æò6öÖÖ6öÆÆ—6–öç2’à¢&÷w2Ò&÷w2æÖ†gVæ7F–öâ‡"’·°¢f"2Òö&¦V7Bæ76–vâ‡··×ÒÂ"“°¢2ç7FGW5÷Fw2Ò'&’æ—4'&’†2ç7FGW5÷Fw2’ò2ç7FGW5÷Fw2æ¦ö–â‚wÂr’¢†2ç7FGW5÷Fw2ÇÂrr“°¢&WGW&â3°¢×Ò“°¢f"77bÒ&÷w5Fô77b„55eô4ôÅTÔå2Â&÷w2“°¢f"7F×ÒæWrFFR‚’çFô•4õ7G&–ær‚’ç6Æ–6RƒÃ“°¢F÷væÆöD77b‚vWfVçE÷7FFUòr²7F×²ræ77brÂ77b“°¢fÆ6„ö²‚t55bF÷væÆöFVBr“°¢×Ò“°¢×Ò“° ¢òòWÆöB²&Wf–Wp¢æVÂçVW'•6VÆV7F÷"‚r677bÖf–ÆRr’æFDWfVçDÆ—7FVæW"‚v6†ævRrÂgVæ7F–öâ†Wb’·°¢f"f–ÆRÒWbçF&vWBæf–ÆW2bbWbçF&vWBæf–ÆW5³Ó°¢–b‚f–ÆR’&WGW&ã°¢f"&VFW"ÒæWrf–ÆU&VFW"‚“°¢&VFW"æöæÆöBÒgVæ7F–öâ‚’·°¢f"FW‡BÒ7G&–ær‡&VFW"ç&W7VÇBÇÂrr“°¢f"'6VBÒ'6T77b‡FW‡B“°¢òòfÆ–FFR†VFW'2†÷F–öæÂ6öÇVÖç2W†6ÇVFVBg&öÒF†R&WV—&VB6WB¢f"Ö—76–ærÒ55eô4ôÅTÔå2æf–ÇFW"†gVæ7F–öâ†2’·²&WGW&â55eôõD”ôäÂæ–æFW„öb†2’ÓÓÒÓbb'6VBæ†VFW'2æ–æFW„öb†2’ÓÓÒÓ²×Ò“°¢f"G&WbÒæVÂçVW'•6VÆV7F÷"‚r677b×&Wf–Wrr“°¢–b‡'6VBç&÷w2æÆVæwF‚ÓÓÒ’·°¢G&Wbæ–ææW$…DÔÂÒsÇ6Æ73Ò&ÆW'BW'&÷"#ä55bÆöö·2V×G’ãÂ÷âs°¢&WGW&ã°¢×Ð¢–b†Ö—76–æræÆVæwF‚â’·°¢G&Wbæ–ææW$…DÔÂÒsÇ6Æ73Ò&ÆW'BW'&÷"#äÖ—76–ær&WV—&VB6öÇVÖç3¢r²Ö—76–æræÖ†W66T‡FÖÂ’æ¦ö–â‚rÂr’²râW6RF†RF÷væÆöB'WGFöâFòw&"fÆ–BFV×ÆFRãÂ÷âs°¢&WGW&ã°¢×Ð¢òò6öW&6RG—W0¢f"6öW&6VBÒ'6VBç&÷w2æÖ†gVæ7F–öâ‡&÷r’·°¢f"÷WBÒ··×Ó°¢55eô4ôÅTÔå2æf÷$V6‚†gVæ7F–öâ†2’·°¢òò÷F–öæÂ6öÇVÖç2'6VçBg&öÒF†—255b7F’VæFVf–æVB(i"VçF÷V6†V@¢–b„55eôõD”ôäÂæ–æFW„öb†2’ÓÒÓbb'6VBæ†VFW'2æ–æFW„öb†2’ÓÓÒÓ’&WGW&ã°¢÷WE¶5ÒÒ6öW&6T77efÇVR†2Â&÷u¶5Ò“°¢×Ò“°¢&WGW&â÷WC°¢×Ò’æf–ÇFW"†gVæ7F–öâ‡"’·²&WGW&â"æWfVçEöçVÒÓÒçVÆÃ²×Ò“° ¢òòF–fbv–ç7B7W'&VçB7FFP¢6"æg&öÒ‚vWfVçE÷7FFRr’ç6VÆV7B‚r¢r’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"’·²G&Wbæ–ææW$…DÔÂÒsÇ6Æ73Ò&ÆW'BW'&÷"#ä6÷VÆFåÅÇS#—BfWF6‚7W'&VçB7FFS¢r²W66T‡FÖÂ‡&W7æW'&÷"æÖW76vR’²sÂ÷âs²&WGW&ã²×Ð¢f"7W'&VçBÒ&W7æFFÇÂµÓ°¢f"F–fbÒF–fe&÷w2†7W'&VçBÂ6öW&6VB“°¢f"G&Wc"ÒæVÂçVW'•6VÆV7F÷"‚r677b×&Wf–Wrr“°¢G&Wc"æ–ææW$…DÔÂÐ¢sÆF—b6Æ73Ò&ÆW'B#âr°¢sÇ7G&öæså&Wf–Ws£Â÷7G&öæsâr°¢sÇ7â7G–ÆSÒ&6öÆ÷#§f"‚ÒÖ"Öw&VVâ“²#âr²F–fbæFFVBæÆVæwF‚²ræWsÂ÷7ãâ+rr°¢sÇ7â7G–ÆSÒ&6öÆ÷#§f"‚ÒÖ"Ö&ÇVR“²#âr²F–fbçWFFVBæÆVæwF‚²rWFFVCÂ÷7ãâ+rr°¢sÇ7â7G–ÆSÒ&6öÆ÷#§f"‚ÒÖ"ÖfrÓ2“²#âr²F–fbçVæ6†ævVBæÆVæwF‚²rVæ6†ævVCÂ÷7ãâr°¢sÂöF—câr°¢sÆF—b6Æ73Ò&FBÖ7F–öç2"7G–ÆSÒ&Ö&v–â×F÷£‡ƒ²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’"–CÒ&77bÖÇ’Ö'Fâ#äÇ’r²†F–fbæFFVBæÆVæwF‚²F–fbçWFFVBæÆVæwF‚’²r6†ævRr²‚†F–fbæFFVBæÆVæwF‚²F–fbçWFFVBæÆVæwF‚’ÓÓÒòrr¢w2r’²sÂö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'6V6öæF'’"–CÒ&77bÖF—66&BÖ'Fâ#äF—66&CÂö'WGFöãâr°¢sÂöF—câs°¢G&Wc"çVW'•6VÆV7F÷"‚r677bÖF—66&BÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²G&Wc"æ–ææW$…DÔÂÒrs²WbçF&vWBçfÇVRÒrs²×Ò“°¢G&Wc"çVW'•6VÆV7F÷"‚r677bÖÇ’Ö'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"'FâÒG&Wc"çVW'•6VÆV7F÷"‚r677bÖÇ’Ö'Fâr“°¢'FâæF—6&ÆVBÒG'VS²'FâçFW‡D6öçFVçBÒtÇ––æ~(
bs°¢òòFrWFFVEö'’öâÆÂ6†ævW0¢f"FõW6W'BÒF–fbæFFVBæ6öæ6B†F–fbçWFFVB’æÖ†gVæ7F–öâ‡"’·°¢f"&÷rÒ··×Ó°¢55eô4ôÅTÔå2æf÷$V6‚†gVæ7F–öâ†2’·°¢–b‡%¶5ÒÓÓÒVæFVf–æVB’&WGW&ã²òò÷F–öæÂ6öÇVÖâ'6VçB(	B&W6W'fRD"fÇVP¢&÷u¶5ÒÒ%¶5Ó°¢×Ò“°¢&÷rçWFFVEö'’ÒVÖ–Ã°¢&WGW&â&÷s°¢×Ò“°¢–b‡FõW6W'BæÆVæwF‚ÓÓÒ’·²'FâæF—6&ÆVBÒfÇ6S²'FâçFW‡D6öçFVçBÒtæ÷F†–ærFòÇ’s²&WGW&ã²×Ð¢òòäõDS¢'VÆ²W6W'B6âwB7G&—ÖæB×&WG'’W"&÷s²&RÖÖ–w&F–öà¢òò55g26–×Ç’6†÷VÆFâwB–æ6ÇVFRGFVæE÷fW&F–7B÷÷7FÖ÷'FVÒ6öÇVÖç2à¢6"æg&öÒ‚vWfVçE÷7FFRr’çW6W'B‡FõW6W'BÂ·²öä6öæfÆ–7C¢vWfVçEöçVÒr×Ò’çF†Vâ†gVæ7F–öâ‡&W7"’·°¢–b‡&W7"æW'&÷"’·²'FâæF—6&ÆVBÒfÇ6S²'FâçFW‡D6öçFVçBÒu&WG'’s²7FGW2‚tÇ’f–ÆVC¢r²&W7"æW'&÷"æÖW76vRÂvW'&÷"r“²&WGW&ã²×Ð¢G&Wc"æ–ææW$…DÔÂÒsÇ6Æ73Ò&ÆW'B#ãÇ7G&öæsäÆ–VC£Â÷7G&öæsâr²F–fbæFFVBæÆVæwF‚²ræWr²r²F–fbçWFFVBæÆVæwF‚²rWFFVBâ&Vg&W6†–ærw&–N(
cÂ÷âs°¢fÆ6„ö²‚t55bÆ–VBr“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²æVÂç&VÖ÷fR‚“²&VæFW$÷2†VÖ–Â“²×ÒÂc“°¢×Ò“°¢×Ò“°¢×Ò“°¢×Ó°¢&VFW"ç&VD5FW‡B†f–ÆR“°¢×Ò“°¢×Ð ¢òò)H)H6V&6‚WfVçG2f–GW7B)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò6·2F†R&7F–4&ÇVTWfVçE7V¶–ærvVçBf÷"âW6öÖ–ærWfVçG0¢òòÖF6†–ær7&—FW&–†6÷VçB²G—W2²V'FW'2²&Vv–öç2’Â&VæFW'0¢òòF†VÒ2&W7VÇBÆ—7BÂæBÆWG2F†RW6W"FB–æF—f–GVÂ&÷w0¢òò†÷"ÆÂBöæ6R’–çFòÖçVÅöWfVçG2â&WÆ6W2F†RöÆFW ¢òò6–ævÆRÖ6æF–FFRfWBv÷&¶fÆ÷rà ¢gVæ7F–öâö7W'&VçEV'FW$÷F–öç2‚’·°¢òò'V–ÆB‚V'FW'27F'F–ærg&öÒF†R7W'&VçBöæRà¢f"æ÷rÒæWrFFR‚“°¢f"7F'BÒÖF‚æfÆö÷"†æ÷rævWDÖöçF‚‚’ò2“²òòâã0¢f"–V"Òæ÷rævWDgVÆÅ–V"‚“°¢f"÷WBÒµÓ°¢f÷"‡f"’Ò²’Âƒ²’²²’·°¢f"’Ò‡7F'B²’’RC°¢f"–’Ò–V"²ÖF‚æfÆö÷"‚‡7F'B²’’òB“°¢÷WBçW6‚‚ur²‡’²’²rr²–’“°¢×Ð¢&WGW&â÷WC°¢×Ð ¢f"4T$4…õE•UôõD”ôå2Ò²tVçFW'&—6RrÂt†ÆòrÂu&W6V&6‚rÂt–æGW7G'’rÂu7öç6÷"rÂt6öæfW&Væ6RrÂu7VÖÖ—BrÂuv÷&·6†÷uÓ°¢f"4T$4…õ$Tt”ôåôõD”ôå2Ò²uU2b6æFrÂtÆF–âÖW&–6rÂtWW&÷RrÂtg&–6rÂtÔTärÂt6–Õ6–f–2rÂtvÆö&ÂuÓ° ¢gVæ7F–öâö×VÇF–6†—††÷7BÂ÷F–öç2ÂFVfVÇG2’·°¢òò'V–ÆB6†—w&÷W–ç6–FR†÷7Fâ&WGW&ç2vWGFW"f÷"6VÆV7FVBfÇVW2à¢÷F–öç2æf÷$V6‚†gVæ7F–öâ†÷B’·°¢f"'FâÒFö7VÖVçBæ7&VFTVÆVÖVçB‚v'WGFöâr“°¢'FâçG—RÒv'WGFöâs°¢'Fâæ6Æ74æÖRÒvW‡G&Ö6†—s°¢'FâæFF6WBçfÇVRÒ÷C°¢'FâçFW‡D6öçFVçBÒ÷C°¢–b†FVfVÇG2bbFVfVÇG2æ–æFW„öb†÷B’ÓÒÓ’'Fâæ6Æ74Æ—7BæFB‚v—2Ööâr“°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²'Fâæ6Æ74Æ—7BçFövvÆR‚v—2Ööâr“²×Ò“°¢†÷7BæVæD6†–ÆB†'Fâ“°¢×Ò“°¢&WGW&âgVæ7F–öâ‚’·°¢&WGW&â'&’ç&÷F÷G—RæÖæ6ÆÂ€¢†÷7BçVW'•6VÆV7F÷$ÆÂ‚ræW‡G&Ö6†—æ—2Ööâr’À¢gVæ7F–öâ†"’·²&WGW&â"æFF6WBçfÇVS²×Ð¢“°¢×Ó°¢×Ð ¢gVæ7F–öâ÷Vå6V&6…æVÂ†VÖ–ÂÂ6VVB’·°¢6VVBÒ6VVBÇÂ··×Ó°¢f"W†—7F–ærÒFö7VÖVçBævWDVÆVÖVçD'”–B‚w6V&6‚×æVÂr“°¢–b†W†—7F–ær’·°¢òòÆ–â&RÖ6Æ–6²ÒFövvÆR6Æ÷6VBâ4TTDTB÷Vâ†Rærâg&öÒÆâÔ†V@¢òò$f–æBWfVçG2æV"Æ6—G“â"'WGFöâ’Çv—2&V÷Vç2v—F‚F†RæWr6VVBà¢W†—7F–ærç&VÖ÷fR‚“°¢–b‚6VVBæÆö6F–öâbb6VVBçV'FW"bb6VVBæFFTg&öÒ’&WGW&ã°¢×Ð ¢f"÷G2Òö7W'&VçEV'FW$÷F–öç2‚“°¢òò6VVFVBv—F‚G&—w2V'FW"†–b—Bw2v—F†–â÷W"‚×V'FW"v–æF÷r’(i ¢òòæ'&÷rFò§W7BF†BV'FW#²÷F†W'v—6RFVfVÇBFòF†RæW‡BGvòà¢f"FVfVÇG2Ò‡6VVBçV'FW"bb÷G2æ–æFW„öb‡6VVBçV'FW"’ÓÒÓ¢ò·6VVBçV'FW%Ò¢÷G2ç6Æ–6RƒÂ"“° ¢f"æVÂÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢æVÂæ–BÒw6V&6‚×æVÂs°¢æVÂæ6Æ74æÖRÒvFBÖWfVçBÖ6&Bs°¢æVÂæ–ææW$…DÔÂÐ¢sÆƒ3äf–æBWfVçG2„’6V&6‚“Âöƒ3âr°¢sÇ7G–ÆSÒ&Ö&v–ã£'ƒ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ"“¶föçB×6—¦S£ã—&VÓ²#âr°¢‡6VVBæÆö6F–öà¢òu6V&6†–ærf÷"WfVçG2–â÷"æV"Ç7G&öæsâr²W66T‡FÖÂ‡6VVBæÆö6F–öâ’²sÂ÷7G&öæsâr°¢‚‡6VVBæFFTg&öÒbb6VVBæFFUFò’òr&÷VæBÇ7G&öæsâr²W66T‡FÖÂ‡6VVBæFFTg&öÒ’²rÅÇS#2r²W66T‡FÖÂ‡6VVBæFFUFò’²sÂ÷7G&öæsâr¢rr’°¢‡6VVBæW†6ÇVFRòr‡Fò7F6²öçFòr²W66T‡FÖÂ‡6VVBæW†6ÇVFR’²rÂv†–6‚—2W†6ÇVFVB’r¢rr’°¢rÅÇS#B6ò–÷R6â6÷fW"Ö÷&R–âöæRG&—âF§W7BF†Rf–VÆG2&VÆ÷ræB'Vâ—Bâp¢¢t’vV"6V&6‚f–æG2W6öÖ–ær–â×W'6öâWfVçG2ÖF6†–ær–÷W"7&—FW&–(	B'W–W"×&–6‚VF–Væ6W2&VfW'&VBâ—Bf—'7BÆöö·2f÷"æW‡B×–V"VF—F–öç2öbWfVçG2F†RFVÒ†2GFVæFVBÂF†Vâf–ÆÇ2–âv—F‚–÷W"7&—FW&–âFFVBWfVçG2&RfWGFVBæBWFòÖVç&–6†VBâr’°¢sÂ÷âr°¢sÆF—b7G–ÆSÒ&F—7Æ“¦fÆWƒ¶v£gƒ¶Æ–vâÖ—FV×3¦6VçFW#¶fÆW‚×w&§w&¶Ö&v–âÖ&÷GFöÓ£ƒ²#âr°¢sÆÆ&VÂ7G–ÆSÒ&F—7Æ“¦–æÆ–æRÖfÆWƒ¶Æ–vâÖ—FV×3¦6VçFW#¶v£‡ƒ¶föçBÖfÖ–Ç“§f"‚ÒÖ"ÖÖöæò“¶föçB×6—¦S£ãw&VÓ¶ÆWGFW"×76–æs£ãfVÓ·FW‡B×G&ç6f÷&Ó§WW&66S¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ2“²#âr°¢t†÷rÖç“¢r°¢sÆ–çWBG—SÒ&çVÖ&W""–CÒ'6V&6‚Ö6÷VçB"Ö–ãÒ#"ÖƒÒ##R"fÇVSÒ#"7G–ÆSÒ'v–GFƒ£cƒ·FF–æs£g‚‡ƒ¶&÷&FW#£‚6öÆ–Bf"‚ÒÖ"×'VÆR×7G&öær“¶&÷&FW"×&F—W3£gƒ¶föçBÖfÖ–Ç“§f"‚ÒÖ"×6ç2“¶föçB×6—¦S£ã—&VÓ²#âr°¢sÂöÆ&VÃâr°¢sÆÆ&VÂ7G–ÆSÒ&F—7Æ“¦–æÆ–æRÖfÆWƒ¶Æ–vâÖ—FV×3¦6VçFW#¶v£‡ƒ¶fÆWƒ£¶Ö–â×v–GFƒ£#ƒ¶föçBÖfÖ–Ç“§f"‚ÒÖ"ÖÖöæò“¶föçB×6—¦S£ãw&VÓ¶ÆWGFW"×76–æs£ãfVÓ·FW‡B×G&ç6f÷&Ó§WW&66S¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ2“²#âr°¢tæV#¢r°¢sÆ–çWBG—SÒ'FW‡B"–CÒ'6V&6‚ÖæV""Æ6V†öÆFW#Ò$6—G’÷"6÷VçG'’ÅÇS#B÷F–öæÂ"7G–ÆSÒ&fÆWƒ£¶Ö–â×v–GFƒ£#ƒ·FF–æs£g‚‡ƒ¶&÷&FW#£‚6öÆ–Bf"‚ÒÖ"×'VÆR×7G&öær“¶&÷&FW"×&F—W3£gƒ¶föçBÖfÖ–Ç“§f"‚ÒÖ"×6ç2“¶föçB×6—¦S£ã—&VÓ·FW‡B×G&ç6f÷&Ó¦æöæS¶ÆWGFW"×76–æs¦æ÷&ÖÃ²#âr°¢sÂöÆ&VÃâr°¢sÂöF—câr°¢sÆF—b6Æ73Ò&W‡G&Öf–ÇFW'2"7G–ÆSÒ&Ö&v–âÖ&÷GFöÓ£ƒ²#âr°¢sÆF—b6Æ73Ò&W‡G&Öf–ÇFW"Öw&÷W"–CÒ'6V&6‚×V'FW'2#âr°¢sÇ7â6Æ73Ò&W‡G&Öf–ÇFW"ÖÆ&VÂ#åV'FW'3Â÷7ãâr°¢sÂöF—câr°¢sÆF—b6Æ73Ò&W‡G&Öf–ÇFW"Öw&÷W"–CÒ'6V&6‚×&Vv–öç2#âr°¢sÇ7â6Æ73Ò&W‡G&Öf–ÇFW"ÖÆ&VÂ#å&Vv–öç3Â÷7ãâr°¢sÂöF—câr°¢sÂöF—câr°¢sÆF—b6Æ73Ò&FBÖ7F–öç2"7G–ÆSÒ&Ö&v–â×F÷£ƒ²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’"–CÒ'6V&6‚×'VâÖ'Fâ#äf–æBWfVçG3Âö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'6V6öæF'’"–CÒ'6V&6‚Ö6æ6VÂÖ'Fâ#ä6Æ÷6SÂö'WGFöãâr°¢sÂöF—câr°¢sÇ6Æ73Ò&÷2ÖÖWF"–CÒ'6V&6‚ÖÖWF"7G–ÆSÒ&Ö&v–â×F÷£ƒ²#ä’6V&6‚W7VÆÇ’F¶W2ÅÇS#3#6V6öæG2ãÂ÷âr°¢sÆF—b–CÒ'6V&6‚×&W7VÇG2"7G–ÆSÒ&Ö&v–â×F÷£'ƒ²#ãÂöF—câs° ¢F÷4w&–Bæ–ç6W'D&Vf÷&R‡æVÂÂF÷4w&–Bæf—'7D6†–ÆB“°¢öÖ÷VçEæVÄ6Æ÷6R‡æVÂ“°¢–b‡6VVBæÆö6F–öâ’æVÂçVW'•6VÆV7F÷"‚r76V&6‚ÖæV"r’çfÇVRÒ6VVBæÆö6F–öã° ¢f"vWEV'FW'2Òö×VÇF–6†—‡æVÂçVW'•6VÆV7F÷"‚r76V&6‚×V'FW'2r’Â÷G2ÂFVfVÇG2“°¢f"vWE&Vv–öç2Òö×VÇF–6†—‡æVÂçVW'•6VÆV7F÷"‚r76V&6‚×&Vv–öç2r’Â4T$4…õ$Tt”ôåôõD”ôå2ÂµÒ“° ¢æVÂçVW'•6VÆV7F÷"‚r76V&6‚Ö6æ6VÂÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²æVÂç&VÖ÷fR‚“²×Ò“° ¢æVÂçVW'•6VÆV7F÷"‚r76V&6‚×'VâÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"6÷VçBÒ'6T–çB‡æVÂçVW'•6VÆV7F÷"‚r76V&6‚Ö6÷VçBr’çfÇVRÂ“°¢–b‚çVÖ&W"æ—4f–æ—FR†6÷VçB’ÇÂ6÷VçBÂ’6÷VçBÒ°¢–b†6÷VçBâ#R’6÷VçBÒ#S°¢òòG—W2&RæòÆöævW"ÖçVÂ–6²(	B6VæBF†RgVÆÂfö6'VÆ'’F†P¢òò&ö×BÇ&VG’¶æ÷w2&÷WB„VçFW'&—6RÂ†ÆòÂ&W6V&6‚Â(
b’6òF†R¢òòf–æG2F†Rv†öÆR&ævRWFöÖF–6ÆÇ’à¢òò&¶R–â'&WGW&âæW‡B–V"#¢6öÆÆV7BF†RWfVçG2F†RFVÒEDTäDTB÷ ¢òò5ô´RB–âF†R7BÂ6òF†RvVçB‡VçG2f÷"F†V—"æW‡B×–V"VF—F–öç0¢òòf—'7BæBöæÇ’F†VâfÆÇ2&6²FòF†R7&—FW&–&VÆ÷rà¢f"÷&V7W'&–ærÒµÓ°¢G'’·°¢'&’ç&÷F÷G—Ræf÷$V6‚æ6ÆÂ‚F÷4w&–BçVW'•6VÆV7F÷$ÆÂ‚ræ÷2Ö6&E¶FF×7CÒ#%Òr’ÂgVæ7F–öâ†2’·°¢f"GG2Ò†2æFF6WBæGFVæFVTæÖW2ÇÂrr’ç7Æ—B‚wÂr’æf–ÇFW"„&ööÆVâ“°¢f"7FrÒ†2æFF6WBç7FGW5Fw2ÇÂrr’ç7Æ—B‚wÂr“°¢f"&öö¶VE7²Ò7Fræ–æFW„öb‚t&öö¶VBr’ÓÒÓbb†2æFF6WBç7V¶W"ÇÂrr“°¢f"æÒÒ2åöÖöFÅ&V2bb2åöÖöFÅ&V2ææÖS°¢–b†æÒbb†GG2æÆVæwF‚ÇÂ&öö¶VE7²’bb÷&V7W'&–æræ–æFW„öb†æÒ’ÓÓÒÓ’÷&V7W'&–ærçW6‚†æÒ“°¢×Ò“°¢×Ò6F6‚†R’··×Ð¢f"öæV"Ò‡æVÂçVW'•6VÆV7F÷"‚r76V&6‚ÖæV"r’çfÇVRÇÂrr’çG&–Ò‚“°¢òò6VVFVBg&öÒG&—¢6V&6‚—G2U„5BFFRv–æF÷r†÷fW'&–FW2V'FW"’æ@¢òòW†6ÇVFRF†RG&—WfVçB—G6VÆbà¢f"7&—FW&–Ò·²6÷VçC¢6÷VçBÂG—W3¢4T$4…õE•UôõD”ôå2ç6Æ–6R‚’ÂV'FW'3¢vWEV'FW'2‚’Â&Vv–öç3¢vWE&Vv–öç2‚’Â&V7W'&–æs¢÷&V7W'&–ærç6Æ–6RƒÂ3’ÂÆö6F–öã¢öæV"À¢FFUög&öÓ¢6VVBæFFTg&öÒÇÂrrÂFFU÷Fó¢6VVBæFFUFòÇÂrrÂW†6ÇVFS¢6VVBæW†6ÇVFRÇÂrr×Ó°¢f"'Vä'FâÒæVÂçVW'•6VÆV7F÷"‚r76V&6‚×'VâÖ'Fâr“°¢f"ÖWFÒæVÂçVW'•6VÆV7F÷"‚r76V&6‚ÖÖWFr“°¢'Vä'FâæF—6&ÆVBÒG'VS²'Vä'FâçFW‡D6öçFVçBÒu6V&6†–æuÅÇS##bs°¢ÖWFçFW‡D6öçFVçBÒt6¶–ær&7F–4&ÇVTWfVçE7V¶–ærf÷"r²6÷VçB²rWfVçG2âF†—26âF¶RÅÇS#3c6V6öæG2âs° ¢6"æWF‚ævWE6W76–öâ‚’çF†Vâ†gVæ7F–öâ‡"’·°¢f"Fö¶VâÒ"bb"æFFbb"æFFç6W76–öâbb"æFFç6W76–öâæ66W75÷Fö¶Vã°¢f"÷6‚Ò·²t6öçFVçBÕG—Rs¢vÆ–6F–öâö§6öâr×Ó°¢–b‡Fö¶Vâ’÷6…²tWF†÷&—¦F–öâuÒÒt&V&W"r²Fö¶Vã°¢f"CÒFFRææ÷r‚“°¢fWF6‚‚rö’÷6V&6‚rÂ·°¢ÖWF†öC¢uõ5BrÀ¢†VFW'3¢÷6‚À¢&öG“¢¥4ôâç7G&–æv–g’†7&—FW&–¢×Ò’çF†Vâ†gVæ7F–öâ‡&W2’·°¢&WGW&â&W2æ§6öâ‚’çF†Vâ†gVæ7F–öâ†¢’·²&WGW&â·&W2ç7FGW2Â¥Ó²×Ò“°¢×Ò’çF†Vâ†gVæ7F–öâ‡—"’·°¢f"7BÒ—%³ÒÂFFÒ—%³Ó°¢f"GW"ÒÖF‚ç&÷VæB‚„FFRææ÷r‚’ÒC’ò“°¢'Vä'FâæF—6&ÆVBÒfÇ6S²'Vä'FâçFW‡D6öçFVçBÒtf–æBÖ÷&Rs°¢–b‡7BÓÒ#’·°¢ÖWFçFW‡D6öçFVçBÒtf–æBf–ÆVB‚r²7B²r“¢r²†FFbbFFæW'&÷"ÇÂwVæ¶æ÷vâW'&÷"r“°¢&WGW&ã°¢×Ð¢f"öf–ÇG2ÒµÓ°¢–b†FFæGWW5öf–ÇFW&VB’öf–ÇG2çW6‚†FFæGWW5öf–ÇFW&VB²rÇ&VG’×G&6¶VBr“°¢–b†FFæöfe÷F&vWEöf–ÇFW&VB’öf–ÇG2çW6‚†FFæöfe÷F&vWEöf–ÇFW&VB²röfb×F&vWBr“°¢ÖWFçFW‡D6öçFVçBÒtf÷VæBr²†FFæWfVçG2ÇÂµÒ’æÆVæwF‚²ræWrWfVçG2–âr²GW"²w2r°¢…öf–ÇG2æÆVæwF‚òr‚r²öf–ÇG2æ¦ö–â‚r²r’²rf–ÇFW&VB÷WB’r¢rr’²râs°¢òò6VVFVB6öÆò×G&—6V&6‚F†Bf÷VæBæ÷F†–ærFòFB(i"&VÖVÖ&W"F†—0¢òòæ6†÷"—2FVBVæBÂ6òÆâ†VB7F÷2öffW&–ærF†R'WGFöâà¢–b‡6VVBææ6†÷$¶W’bb†FFæWfVçG2ÇÂµÒ’æÆVæwF‚ÓÓÒ’÷Æä&VV×G”Ö&²‡6VVBææ6†÷$¶–æBÂ6VVBææ6†÷$¶W’“°¢&VæFW%6V&6…&W7VÇG2‡æVÂÂFFÂVÖ–Â“°¢×Ò’æ6F6‚†gVæ7F–öâ†W'"’·°¢'Vä'FâæF—6&ÆVBÒfÇ6S²'Vä'FâçFW‡D6öçFVçBÒtf–æBÖ÷&Rs°¢ÖWFçFW‡D6öçFVçBÒtæWGv÷&²W'&÷#¢r²W'"æÖW76vS°¢×Ò“°¢×Ò“°¢×Ò“°¢×Ð ¢òò–ç6W'BöæR’Öf÷VæBWfVçB–çFòÖçVÅöWfVçG2â6†&VB'’F†R6V&6‚æVÂw0¢òò$FBFòWfVçG2"æBÆâ†VBw2–æÆ–æR&ö7F—fR&W7VÇG2à¢gVæ7F–öâö–ç6W'Df÷VæDWfVçB†WbÂVÖ–Â’·°¢–b‚WbÇÂWbææÖR’&WGW&â&öÖ—6Rç&W6öÇfR‡·²ö³¢fÇ6RÂ&V6öã¢vÖ—76–æræÖRr×Ò“°¢–b†—4GWÆ–6FTæÖR†WbææÖRÂçVÆÂÂWb’’&WGW&â&öÖ—6Rç&W6öÇfR‡·²ö³¢fÇ6RÂ&V6öã¢vGWÆ–6FRr×Ò“°¢f"FFW2ÒWbæFFU÷7G"òFW&—fTFFW4g&öÕFW‡B†WbæFFU÷7G"’¢··×Ó°¢f"&÷rÒ·°¢æÖS¢WbææÖRçG&–Ò‚’À¢FFU÷7G#¢WbæFFU÷7G"ÇÂtFFRD$BrÀ¢7F'EöFFS¢FFW2ç7F'EöFFRÇÂçVÆÂÀ¢VæEöFFS¢FFW2æVæEöFFRÇÂçVÆÂÀ¢Æö6F–öã¢WbæÆö6F–öâÇÂçVÆÂÀ¢&Vv–öã¢Wbç&Vv–öâÇÂçVÆÂÀ¢G—S¢WbçG—RÇÂçVÆÂÀ¢&–÷&—G“¢Wbç&–÷&—G’ÇÂçVÆÂÀ¢v‡“¢Wbçv‡’ÇÂçVÆÂÀ¢W&Ã¢WbçW&ÂÇÂçVÆÂÀ¢òòGFVæF–ær6–væÇ2Âv†VâF†R6V&6‚&W7VÇG26''’F†VÒâF†RvVç@¢òò6—2&VF–Væ6R#²F†R6öÇVÖâ—2VF–Væ6U÷G—Rà¢&–6–æs¢Wbç&–6–ærÇÂçVÆÂÀ¢VF–Væ6U÷G—S¢WbæVF–Væ6U÷G—RÇÂWbæVF–Væ6RÇÂçVÆÂÀ¢7E÷7V¶W'3¢Wbç7E÷7V¶W'2ÇÂWbç7V¶W'2ÇÂçVÆÂÀ¢ÖVWF–æuöf÷&ÖG3¢WbæÖVWF–æuöf÷&ÖG2ÇÂWbæwV&çFVVEöÖVWF–æw2ÇÂçVÆÂÀ¢7&VFVEö'“¢VÖ–À¢×Ó°¢&WGW&â6%w&—FU&WG'’‡&÷rÂgVæ7F–öâ‡’·²&WGW&â6"æg&öÒ‚vÖçVÅöWfVçG2r’æ–ç6W'B‡’ç6VÆV7B‚“²×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"’·°¢–b‡&W7æW'&÷"æ6öFRÓÓÒs#3SRr’&WGW&â·²ö³¢fÇ6RÂ&V6öã¢vGWÆ–6FRr×Ó°¢&WGW&â·²ö³¢fÇ6RÂ&V6öã¢&W7æW'&÷"æÖW76vR×Ó°¢×Ð¢&WGW&â·²ö³¢G'VRÂ&÷s¢&W7æFFbb&W7æFF³Ò×Ó°¢×Ò“°¢×Ð ¢gVæ7F–öâ&VæFW%6V&6…&W7VÇG2‡æVÂÂFFÂVÖ–Â’·°¢f"WfVçG2Ò†FFæWfVçG2ÇÂµÒ“°¢f"G"ÒæVÂçVW'•6VÆV7F÷"‚r76V&6‚×&W7VÇG2r“°¢–b†WfVçG2æÆVæwF‚ÓÓÒ’·°¢G"æ–ææW$…DÔÂÒsÇ6Æ73Ò&ÆW'B#äæò&VÆWfçBWfVçG3Â÷âs°¢&WGW&ã°¢×Ð ¢gVæ7F–öâ&V5–ÆÄ‡FÖÂ‡&V2’·°¢f""Ò‡&V2ÇÂrr’çFôÆ÷vW$66R‚“°¢–b‡"ÓÓÒw–W2r’&WGW&âsÇ7â6Æ73Ò&÷2×Fr"7G–ÆSÒ&&6¶w&÷VæC¢6F6f6Ss¶6öÆ÷#¢3ccS3C²#å&V6öÖÖVæCÂ÷7ãâs°¢–b‡"ÓÓÒvÖ–&Rr’&WGW&âsÇ7â6Æ73Ò&÷2×Fr"7G–ÆSÒ&&6¶w&÷VæC¢6fVc63s¶6öÆ÷#¢3“#CS²#äÖ–&SÂ÷7ãâs°¢–b‡"ÓÓÒvæòr’&WGW&âsÇ7â6Æ73Ò&÷2×Fr"7G–ÆSÒ&&6¶w&÷VæC¢6fVS&S#¶6öÆ÷#¢3““##²#å6¶—Â÷7ãâs°¢&WGW&ârs°¢×Ð ¢f"6&G2ÒWfVçG2æÖ†gVæ7F–öâ†WbÂ–G‚’·°¢f"W&ÂÒWbçW&ÂòrÆ‡&VcÒ"r²W66T‡FÖÂ†WbçW&Â’²r"F&vWCÒ%ö&Ææ²"&VÃÒ&æö÷VæW""7G–ÆSÒ&6öÆ÷#§f"‚ÒÖ"Ö&ÇVR“·FW‡BÖFV6÷&F–öã¦æöæS¶föçB×vV–v‡C£c²#î(isÂöâr¢rs°¢f"GWÒ—4GWÆ–6FTæÖR†WbææÖRÂçVÆÂÂWb’òsÇ7â6Æ73Ò&÷2×Fr"7G–ÆSÒ&&6¶w&÷VæC¢6fVc&c#¶6öÆ÷#¢3vcCC¶&÷&FW#£‚6öÆ–B6fV66²#äÇ&VG’–âG&6¶W#Â÷7ãâr¢rs°¢&WGW&â€¢sÆF—b6Æ73Ò'6V&6‚×&W7VÇB"FFÖ–GƒÒ"r²–G‚²r"7G–ÆSÒ&&÷&FW#£‚6öÆ–Bf"‚ÒÖ"×'VÆR“¶&÷&FW"×&F—W3£‡ƒ·FF–æs£Gƒ¶Ö&v–âÖ&÷GFöÓ£ƒ¶&6¶w&÷VæC§f"‚ÒÖ"Ö&r“²#âr°¢sÆF—b7G–ÆSÒ&F—7Æ“¦fÆWƒ¶§W7F–g’Ö6öçFVçC§76RÖ&WGvVVã¶Æ–vâÖ—FV×3¦fÆW‚×7F'C¶v£ƒ¶Ö&v–âÖ&÷GFöÓ£gƒ¶fÆW‚×w&§w&²#âr°¢sÆF—b7G–ÆSÒ&fÆWƒ£¶Ö–â×v–GFƒ£²#âr°¢sÆƒB7G–ÆSÒ&Ö&v–ã£¶föçB×6—¦S£ã'&VÓ¶föçB×vV–v‡C£s¶ÆWGFW"×76–æs¢ÓãVÓ¶6öÆ÷#§f"‚ÒÖ"Öfr“²#âr²W66T‡FÖÂ†WbææÖRÇÂr‡VææÖVB’r’²W&Â²sÂöƒCâr°¢sÇ7G–ÆSÒ&Ö&v–ã£G‚¶föçB×6—¦S£ãƒW&VÓ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ"“²#âr°¢W66T‡FÖÂ†WbæFFU÷7G"ÇÂrr’²r+rr²W66T‡FÖÂ†Wbç&Vv–öâÇÂrr’²†WbæÆö6F–öâòr+rr²W66T‡FÖÂ†WbæÆö6F–öâ’¢rr’°¢†WbçG—RbbWbçG—RçFôÆ÷vW$66R‚’ÓÒv†Æòròr+rr²W66T‡FÖÂ†WbçG—R’¢rr’°¢†Wbç&–÷&—G’òr+rr²W66T‡FÖÂ†Wbç&–÷&—G’’¢rr’°¢sÂ÷âr°¢sÂöF—câr°¢sÆF—b7G–ÆSÒ&F—7Æ“¦fÆWƒ¶v£gƒ¶Æ–vâÖ—FV×3¦6VçFW#¶fÆW‚×w&§w&²#âr°¢&V5–ÆÄ‡FÖÂ†Wbç&V6öÖÖVæB’²rr²GW°¢sÂöF—câr°¢sÂöF—câr°¢†Wbçv‡’ÇÂWbç&V6öæ–ærð¢sÇ7G–ÆSÒ&föçB×6—¦S£ãƒW&VÓ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ"“¶Ö&v–ã£G‚‡ƒ²#âr°¢†Wbçv‡’òW66T‡FÖÂ†Wbçv‡’’¢rr’°¢†Wbçv‡’bbWbç&V6öæ–æròr(	Br¢rr’°¢†Wbç&V6öæ–æròsÆVÓâr²W66T‡FÖÂ†Wbç&V6öæ–ær’²sÂöVÓâr¢rr’°¢sÂ÷âr¢rr’°¢sÆF—b6Æ73Ò&FBÖ7F–öç2"7G–ÆSÒ&Ö&v–â×F÷£gƒ²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’6V&6‚ÖFB"FFÖ–GƒÒ"r²–G‚²r"r²†GWòvF—6&ÆVBr¢rr’²säFBFòWfVçG3Âö'WGFöãâr°¢sÂöF—câr°¢sÂöF—câp¢“°¢×Ò’æ¦ö–â‚rr“° ¢G"æ–ææW$…DÔÂÐ¢sÆF—b7G–ÆSÒ&F—7Æ“¦fÆWƒ¶v£‡ƒ¶Æ–vâÖ—FV×3¦6VçFW#¶Ö&v–âÖ&÷GFöÓ£ƒ¶fÆW‚×w&§w&²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’"–CÒ'6V&6‚ÖFBÖÆÂ#äFBÆÂFòWfVçG3Âö'WGFöãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'6V6öæF'’"–CÒ'6V&6‚×&rÖ'Fâ#å6†÷r&r&WÇ“Âö'WGFöãâr°¢sÂöF—câr°¢sÇ&R–CÒ'6V&6‚×&r"7G–ÆSÒ&F—7Æ“¦æöæS¶Ö&v–ã£ƒ·FF–æs£'ƒ¶&6¶w&÷VæC§f"‚ÒÖ"Ö&rÓ2“¶&÷&FW"×&F—W3£gƒ¶föçB×6—¦S£ãs‡&VÓ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ"“¶Ö‚Ö†V–v‡C£#ƒƒ¶÷fW&fÆ÷s¦WFó·v†—FR×76S§&R×w&²#ãÂ÷&Sâr°¢6&G3° ¢òòW'6—7BFFf÷"FVÆVvFVB†æFÆW'0¢f"öWfVçG4'”–G‚ÒWfVçG3° ¢G"çVW'•6VÆV7F÷"‚r76V&6‚×&rÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"&RÒG"çVW'•6VÆV7F÷"‚r76V&6‚×&rr“°¢–b‡&Rç7G–ÆRæF—7Æ’ÓÓÒvæöæRr’·°¢&RçFW‡D6öçFVçBÒFFç&rÇÂr†æò&r&WÇ’’s°¢&Rç7G–ÆRæF—7Æ’Òv&Æö6²s°¢×ÒVÇ6R·°¢&Rç7G–ÆRæF—7Æ’ÒvæöæRs°¢×Ð¢×Ò“° ¢gVæ7F–öâ–ç6W'DöæR†Wb’·²&WGW&âö–ç6W'Df÷VæDWfVçB†WbÂVÖ–Â“²×Ð ¢G"çVW'•6VÆV7F÷$ÆÂ‚rç6V&6‚ÖFBr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"–G‚Ò'6T–çB†'FâæFF6WBæ–G‚Â“°¢f"WbÒöWfVçG4'”–G…¶–G…Ó°¢'FâæF—6&ÆVBÒG'VS²'FâçFW‡D6öçFVçBÒtFF–æuÅÇS##bs°¢–ç6W'DöæR†Wb’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‡"æö²’·°¢'FâçFW‡D6öçFVçBÒtFFVB)É2s°¢'Fâæ6Æ74Æ—7Bç&VÖ÷fR‚w&–Ö'’r“²'Fâæ6Æ74Æ—7BæFB‚w6V6öæF'’r“°¢ÆöD¶æ÷väæÖW2‚“°¢&VæFW$÷2†VÖ–Â“°¢fÆ6„ö²‚tFFVB"r²†WbææÖRÇÂrr’²r"r“°¢×ÒVÇ6R·°¢'FâæF—6&ÆVBÒfÇ6S°¢'FâçFW‡D6öçFVçBÒtFBFòWfVçG2s°¢7FGW2‚tFBf–ÆVC¢r²"ç&V6öâÂvW'&÷"r“°¢×Ð¢×Ò“°¢×Ò“°¢×Ò“° ¢G"çVW'•6VÆV7F÷"‚r76V&6‚ÖFBÖÆÂr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"FDÆÂÒG"çVW'•6VÆV7F÷"‚r76V&6‚ÖFBÖÆÂr“°¢FDÆÂæF—6&ÆVBÒG'VS²FDÆÂçFW‡D6öçFVçBÒtFF–æuÅÇS##bs°¢f"FFVBÒÂ6¶—VBÒÂW'&÷'2Ò°¢òò–ç6W'B6W&–ÆÇ’6òFVGW66†R7F—2–â7–æ2&WGvVVâ&÷w0¢f"6†–âÒ&öÖ—6Rç&W6öÇfR‚“°¢WfVçG2æf÷$V6‚†gVæ7F–öâ†Wb’·°¢6†–âÒ6†–âçF†Vâ†gVæ7F–öâ‚’·²&WGW&â–ç6W'DöæR†Wb“²×Ò’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‡"æö²’·²FFVB²³²ÆöD¶æ÷väæÖW2‚“²×Ð¢VÇ6R–b‡"ç&V6öâÓÓÒvGWÆ–6FRr’·²6¶—VB²³²×Ð¢VÇ6R·²W'&÷'2²³²×Ð¢×Ò“°¢×Ò“°¢6†–âçF†Vâ†gVæ7F–öâ‚’·°¢FDÆÂæF—6&ÆVBÒfÇ6S°¢FDÆÂçFW‡D6öçFVçBÒtFBÆÂFòWfVçG2s°¢f"×6rÒtFFVBr²FFVB²r+r6¶—VBr²6¶—VB²rGWÆ–6FRr²‡6¶—VBÓÓÒòrr¢w2r“°¢–b†W'&÷'2’×6r³Òr+rr²W'&÷'2²rW'&÷"r²†W'&÷'2ÓÓÒòrr¢w2r“°¢fÆ6„ö²†×6r“°¢&VæFW$÷2†VÖ–Â“°¢×Ò“°¢×Ò“°¢×Ð    ¢òò)H)H²FBWfVçBò7FRVÖ–Â÷&6†W7G&F–öâ)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òò÷Vç2â–æÆ–æRæVÂF†B7W&f6W2F†RV&Æ–2fVVBU$Â²Ö6Æ–6°¢òò6÷’'WGFöâ²7FRÖ–ç7G'V7F–öç2f÷"F†RF‡&VR6öÖÖöâ6ÆVæF"2à¢gVæ7F–öâ÷Vå7V'67&–&UæVÂ‚’·°¢f"W†—7F–ærÒFö7VÖVçBævWDVÆVÖVçD'”–B‚w7V'67&–&R×æVÂr“°¢–b†W†—7F–ær’·²W†—7F–ærç&VÖ÷fR‚“²&WGW&ã²×Ð¢f"fVVEW&ÂÒv–æF÷ræÆö6F–öâæ÷&–v–â²rö6ÆVæF"æ–72s°¢f"æVÂÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“°¢æVÂæ–BÒw7V'67&–&R×æVÂs°¢æVÂæ6Æ74æÖRÒvFBÖWfVçBÖ6&Bs°¢æVÂæ–ææW$…DÔÂÐ¢sÆƒ3ä6ÆVæF"7–æ3Âöƒ3âr°¢sÇ7G–ÆSÒ&Ö&v–ã£Gƒ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ"“¶föçB×6—¦S£ã—&VÓ²#âr°¢töæRÆ—fRfVVBöbWfW'’6fVB)ˆRæBÖçVÂWfVçBâ7V'67&–&Röæ6R(	Br°¢w–÷W"6ÆVæF"WFFW2—G6VÆbg&öÒF†Vâöââr°¢sÂ÷âr°¢òò„U$ó¢öæRÖ6Æ–6²vöövÆR6ÆVæF"7V'67&–&R(	BF†RFVÕÂw26†&V@¢òò6ÆVæF"Æ—fW2–âvöövÆRÂ6òF†—2—2F†R“RRF‚à¢sÆ‡&VcÒ&‡GG3¢òö6ÆVæF"ævöövÆRæ6öÒö6ÆVæF"÷&VæFW#ö6–CÒr°¢Væ6öFUU$”6ö×öæVçB‚wvV&6Ã¢òòr²v–æF÷ræÆö6F–öâæ†÷7B²rö6ÆVæF"æ–72r’°¢r"F&vWCÒ%ö&Ææ²"&VÃÒ&æö÷VæW""6Æ73Ò'&–Ö'’"–CÒ'7V'67&–&RÖv6ÂÖ'Fâ"r°¢w7G–ÆSÒ&F—7Æ“¦&Æö6³·FW‡BÖÆ–vã¦6VçFW#¶Ö&v–âÖ&÷GFöÓ£Gƒ¶föçBÖfÖ–Ç“§f"‚ÒÖ"×6ç2“¶föçB×vV–v‡C£c¶föçB×6—¦S£&VÓ·FF–æs£7‚‡ƒ¶&÷&FW"×&F—W3£‡ƒ¶&6¶w&÷VæC¢3s6Sƒ¶6öÆ÷#¢6ffc·FW‡BÖFV6÷&F–öã¦æöæS²#âr°¢tFBFòvöövÆR6ÆVæF"(	BöæR6Æ–6³Âöâr°¢sÆF—b7G–ÆSÒ&F—7Æ“¦fÆWƒ¶v£‡ƒ¶Æ–vâÖ—FV×3¦6VçFW#¶Ö&v–âÖ&÷GFöÓ£'ƒ²#âr°¢sÆ–çWBG—SÒ'FW‡B"–CÒ'7V'67&–&R×W&Â"&VFöæÇ’fÇVSÒ"r²W66T‡FÖÂ†fVVEW&Â’²r"r°¢w7G–ÆSÒ&fÆWƒ£¶föçBÖfÖ–Ç“§f"‚ÒÖ"ÖÖöæò“¶föçB×6—¦S£ãƒW&VÓ·FF–æs£‚'ƒ¶&÷&FW#£‚6öÆ–Bf"‚ÒÖ"×'VÆR×7G&öær“¶&÷&FW"×&F—W3£gƒ¶&6¶w&÷VæC§f"‚ÒÖ"Ö&rÓ"“¶6öÆ÷#§f"‚ÒÖ"Öfr“²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'&–Ö'’"–CÒ'7V'67&–&RÖ6÷’Ö'Fâ"7G–ÆSÒ'v†—FR×76S¦æ÷w&¶föçBÖfÖ–Ç“§f"‚ÒÖ"×6ç2“¶föçB×vV–v‡C£c¶föçB×6—¦S£ã—&VÓ·FF–æs£‚gƒ¶&÷&FW"×&F—W3£gƒ¶&÷&FW#£¶&6¶w&÷VæC§f"‚ÒÖ"Öfr“¶6öÆ÷#§f"‚ÒÖ"Ö&r“¶7W'6÷#§ö–çFW#²#ä6÷’Æ–æ³Âö'WGFöãâr°¢sÂöF—câr°¢sÆFWF–Ç27G–ÆSÒ&&÷&FW"×F÷£‚6öÆ–Bf"‚ÒÖ"×'VÆR“·FF–ær×F÷£'ƒ²#âr°¢sÇ7VÖÖ'’7G–ÆSÒ&7W'6÷#§ö–çFW#¶föçBÖfÖ–Ç“§f"‚ÒÖ"ÖÖöæò“¶föçB×6—¦S£ãs'&VÓ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ2“¶ÆWGFW"×76–æs£ã†VÓ·FW‡B×G&ç6f÷&Ó§WW&66S²#ä÷F†W"6ÆVæF"2„ÆR+r÷WFÆöö²“Â÷7VÖÖ'“âr°¢sÆF—b7G–ÆSÒ&F—7Æ“¦w&–C¶v£ƒ¶Ö&v–â×F÷£ƒ¶föçB×6—¦S£ã—&VÓ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ"“¶Æ–æRÖ†V–v‡C£ãSS²#âr°¢sÆF—cãÇ7G&öæsäÆR6ÆVæF"„Ö2“£Â÷7G&öæsâf–ÆR(i"æWr6ÆVæF"7V'67&—F–öâ(i"7FRF†RÆ–æ²&÷fR(i"7V'67&–&R(i"6†ö÷6RWFò×&Vg&W6‚ãÂöF—câr°¢sÆF—cãÇ7G&öæsäÆR6ÆVæF"†•†öæRö•B“£Â÷7G&öæsâ6WGF–æw2(i"6ÆVæF"(i"66÷VçG2(i"FB66÷VçB(i"÷F†W"(i"FB7V'67&–&VB6ÆVæF"(i"7FRãÂöF—câr°¢sÆF—cãÇ7G&öæsä÷WFÆöö²‡vV"“£Â÷7G&öæsâ6ÆVæF"(i"FB6ÆVæF"(i"7V'67&–&Rg&öÒvV"(i"7FRãÂöF—câr°¢sÂöF—câr°¢sÂöFWF–Ç3âr°¢sÆF—b6Æ73Ò&FBÖ7F–öç2"7G–ÆSÒ&Ö&v–â×F÷£Gƒ¶Æ–vâÖ—FV×3¦6VçFW#²#âr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'6V6öæF'’"–CÒ'7V'67&–&RÖ6Æ÷6RÖ'Fâ#ä6Æ÷6SÂö'WGFöãâr°¢sÆ–CÒ'7V'67&–&RÖF÷væÆöBÖ'Fâ"7G–ÆSÒ&7W'6÷#§ö–çFW#¶föçB×6—¦S£ãƒW&VÓ¶6öÆ÷#§f"‚ÒÖ"ÖfrÓ2“·FW‡BÖFV6÷&F–öã§VæFW&Æ–æS¶Ö&v–âÖÆVgC¦WFó²"F—FÆSÒ$öæR×F–ÖR6æ6†÷Bf–ÆR(	BFöW2äõB7F’–â7–æ3²&VfW"F†RÆ—fRfVVB&÷fR#äF÷væÆöBöæR×F–ÖRæ–72f–ÆR–ç7FVCÂöâr°¢sÂöF—câr°¢sÇ6Æ73Ò&÷2ÖÖWF"7G–ÆSÒ&Ö&v–â×F÷£ƒ²#åF—¢F†RfVVB—2V×G’VçF–ÂBÆV7BöæRWfVçB—27F'&VB)ˆR6fVBÂ÷"–÷RFBÖçVÂWfVçBãÂ÷âs° ¢F÷4w&–Bæ–ç6W'D&Vf÷&R‡æVÂÂF÷4w&–Bæf—'7D6†–ÆB“°¢öÖ÷VçEæVÄ6Æ÷6R‡æVÂ“° ¢æVÂçVW'•6VÆV7F÷"‚r77V'67&–&RÖ6Æ÷6RÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²æVÂç&VÖ÷fR‚“²×Ò“°¢æVÂçVW'•6VÆV7F÷"‚r77V'67&–&RÖF÷væÆöBÖ'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²W‡÷'E6fVD4–72‚“²×Ò“° ¢f"6÷”'FâÒæVÂçVW'•6VÆV7F÷"‚r77V'67&–&RÖ6÷’Ö'Fâr“°¢6÷”'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢f"–çWBÒæVÂçVW'•6VÆV7F÷"‚r77V'67&–&R×W&Âr“°¢gVæ7F–öâFöæR‚’·°¢f"÷&–v–æÂÒ6÷”'FâçFW‡D6öçFVçC°¢6÷”'FâçFW‡D6öçFVçBÒ~)É26÷–VBs°¢6÷”'FâæF—6&ÆVBÒG'VS°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²6÷”'FâçFW‡D6öçFVçBÒ÷&–v–æÃ²6÷”'FâæF—6&ÆVBÒfÇ6S²×ÒÂc“°¢×Ð¢òò&VfW"F†R7–æ26Æ—&ö&B’„…EE2&WV—&VB“²fÆÂ&6²Fò6VÆV7BÖæBÖW†V46öÖÖæ@¢–b†æf–vF÷"æ6Æ—&ö&Bbbv–æF÷ræ—56V7W&T6öçFW‡B’·°¢æf–vF÷"æ6Æ—&ö&Bçw&—FUFW‡B†fVVEW&Â’çF†Vâ†FöæRÂgVæ7F–öâ‚’·°¢–çWBç6VÆV7B‚“²–çWBç6WE6VÆV7F–öå&ævRƒÂ“““’“°¢G'’·²Fö7VÖVçBæW†V46öÖÖæB‚v6÷’r“²FöæR‚“²×Ò6F6‚†R’·²ÆW'B‚t6÷VÆFåÅÇS#—B6÷’â6VÆV7BF†RU$ÂÖçVÆÇ’æB6ÖB´2âr“²×Ð¢×Ò“°¢×ÒVÇ6R·°¢–çWBç6VÆV7B‚“²–çWBç6WE6VÆV7F–öå&ævRƒÂ“““’“°¢G'’·²Fö7VÖVçBæW†V46öÖÖæB‚v6÷’r“²FöæR‚“²×Ò6F6‚†R’·²ÆW'B‚t6÷VÆFåÅÇS#—B6÷’â6VÆV7BF†RU$ÂÖçVÆÇ’æB6ÖB´2âr“²×Ð¢×Ð¢×Ò“°¢×Ð ¢gVæ7F–öâv—&TFDWfVçB†VÖ–Â’·°¢f"FFD'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vFBÖWfVçBÖ'Fâr“°¢f"G7FT'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚w7FRÖVÖ–ÂÖ'Fâr“°¢f"G6V&6„'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚w6V&6‚ÖGW7BÖ'Fâr“°¢f"F77d'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v77bÖ'Fâr“°¢f"F–6Ä'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v–6ÂÖ'Fâr“°¢f"G7V$'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v–6Â×7V'67&–&RÖ'Fâr“°¢–b‚FFD'Fâ’&WGW&ã°¢òò6ÆöæR×&WÆ6RFò6ÆV"Æ—7FVæW'2g&öÒç’&–÷"&÷WFR‚’6ÆÀ¢f"g&W6„FBÒFFD'Fâæ6ÆöæTæöFR‡G'VR“²FFD'Fâç&VçDæöFRç&WÆ6T6†–ÆB†g&W6„FBÂFFD'Fâ“²FFD'FâÒg&W6„FC°¢–b‚G7FT'Fâ’·²f"gÒG7FT'Fâæ6ÆöæTæöFR‡G'VR“²G7FT'Fâç&VçDæöFRç&WÆ6T6†–ÆB†gÂG7FT'Fâ“²G7FT'FâÒg²×Ð¢–b‚G6V&6„'Fâ’·²f"g3"ÒG6V&6„'Fâæ6ÆöæTæöFR‡G'VR“²G6V&6„'Fâç&VçDæöFRç&WÆ6T6†–ÆB†g3"ÂG6V&6„'Fâ“²G6V&6„'FâÒg3#²×Ð¢–b‚F77d'Fâ’·²f"f2ÒF77d'Fâæ6ÆöæTæöFR‡G'VR“²F77d'Fâç&VçDæöFRç&WÆ6T6†–ÆB†f2ÂF77d'Fâ“²F77d'FâÒf3²×Ð¢–b‚F–6Ä'Fâ’·²f"f’ÒF–6Ä'Fâæ6ÆöæTæöFR‡G'VR“²F–6Ä'Fâç&VçDæöFRç&WÆ6T6†–ÆB†f’ÂF–6Ä'Fâ“²F–6Ä'FâÒf“²×Ð¢–b‚G7V$'Fâ’·²f"g2ÒG7V$'Fâæ6ÆöæTæöFR‡G'VR“²G7V$'Fâç&VçDæöFRç&WÆ6T6†–ÆB†g2ÂG7V$'Fâ“²G7V$'FâÒg3²×Ð ¢òò"²FB"G&÷F÷vã¢FövvÆRF†RÖVçR†öÆF–ærF†RF‡&VRFBF‡2âF†RÖVçP¢òò'WGFöâ²6öçF–æW"&RäõB6ÆöæVB&÷fRÂ6òv—&Röæ6R†wV&BfÆr’(	BF†P¢òò—FVÒ'WGFöç2–ç6–FR¶VWF†V—"÷vâ†æFÆW'2†GF6†VB&VÆ÷r’â6Æ–6¶–æp¢òòç’—FVÒ'Vç2—G27F–öâäB6Æ÷6W2F†RÖVçR†FVÆVvFVBöâF†R6öçF–æW"’à¢f"FFDÖVçT'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vFBÖÖVçRÖ'Fâr“°¢f"FFDÖVçRÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vFBÖÖVçRr“°¢–b‚FFDÖVçT'FâbbFFDÖVçRbbFFDÖVçT'FâåöÖVçUv—&VB’·°¢FFDÖVçT'FâåöÖVçUv—&VBÒG'VS°¢gVæ7F–öâö6Æ÷6TFDÖVçR‚’·²FFDÖVçRæ†–FFVâÒG'VS²FFDÖVçT'Fâç6WDGG&–'WFR‚v&–ÖW‡æFVBrÂvfÇ6Rr“²×Ð¢FFDÖVçT'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢f"v–ÆÄ÷VâÒFFDÖVçRæ†–FFVã°¢FFDÖVçRæ†–FFVâÒv–ÆÄ÷Vã°¢FFDÖVçT'Fâç6WDGG&–'WFR‚v&–ÖW‡æFVBrÂv–ÆÄ÷VâòwG'VRr¢vfÇ6Rr“°¢×Ò“°¢FFDÖVçRæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²ö6Æ÷6TFDÖVçR‚“²×Ò“²òòç’—FVÒ6Æ÷6W2—@¢Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢–b‚FFDÖVçRæ†–FFVâbbFFDÖVçRæ6öçF–ç2†RçF&vWB’bbFFDÖVçT'Fâæ6öçF–ç2†RçF&vWB’’ö6Æ÷6TFDÖVçR‚“°¢×Ò“°¢Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚v¶W–F÷vârÂgVæ7F–öâ†R’·²–b†Ræ¶W’ÓÓÒtW66Rr’ö6Æ÷6TFDÖVçR‚“²×Ò“°¢×Ð ¢gVæ7F–öâ÷VäFDf÷&Ò†÷G2’·°¢÷G2Ò÷G2ÇÂ··×Ó°¢f"W†—7F–ærÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vFBÖWfVçBÖ6&Br“°¢–b†W†—7F–ær’·°¢–b†÷G2æW‡æE7FR’·°¢f"6V7F–öâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚w7FRÖVÖ–Â×6V7F–öâr“°¢–b‡6V7F–öâ’6V7F–öâç6WDGG&–'WFR‚v÷VârÂrr“°¢f"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚w7FRÖVÖ–Â×FW‡Br“°¢–b‡’æfö7W2‚“°¢×Ð¢&WGW&âW†—7F–æs°¢×Ð¢f"f÷&ÒÒ'V–ÆDFDWfVçDf÷&Ò‚“°¢F÷4w&–Bæ–ç6W'D&Vf÷&R†f÷&ÒÂF÷4w&–Bæf—'7D6†–ÆB“°¢öÖ÷VçEæVÄ6Æ÷6R†f÷&Ò“°¢GF6„FDWfVçD†æFÆW'2†f÷&ÒÂVÖ–Â“°¢–b†÷G2æW‡æE7FR’·°¢f÷&ÒçVW'•6VÆV7F÷"‚r77FRÖVÖ–Â×6V7F–öâr’ç6WDGG&–'WFR‚v÷VârÂrr“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²f÷&ÒçVW'•6VÆV7F÷"‚r77FRÖVÖ–Â×FW‡Br’æfö7W2‚“²×ÒÂ“°¢×ÒVÇ6R·°¢f÷&ÒçVW'•6VÆV7F÷"‚v–çWE¶æÖSÒ&æÖR%Òr’æfö7W2‚“°¢×Ð¢&WGW&âf÷&Ó°¢×Ð ¢òòF†RæVÇ2ÆÂ–æ¦V7B–çFò6÷2Öw&–Bv†–6‚—2†–FFVâ–â6ÆVæF ¢òòf–WrâWFò×7v—F6‚Fòw&–B6òWfW'’FööÆ&"'WGFöâ—2gVæ7F–öæÀ¢òòg&öÒV—F†W"f–Wrà¢gVæ7F–öâVç7W&Tw&–Ef–Wr‚’·°¢–b‡G—Vöb7W'&VçEf–WrÓÒwVæFVf–æVBrbb7W'&VçEf–WrÓÒvw&–Br’6WEf–Wr‚vw&–Br“°¢×Ð ¢òò)H)HæVÂF—66—Æ–æR)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòWfW'’FööÆ&"fVGW&R—27G&–7BFövvÆS¢6Æ–6²÷Vç2—BÂ6Æ–6°¢òòv–â6Æ÷6W2—BâöæÇ’ôäRæVÂBF–ÖR†÷Væ–æröæR6Æ÷6W2F†P¢òò&W7B’ÂF†R÷VæVBæVÂ67&öÆÇ2–çFòf–Wr†—B–æ¦V7G2BF†RF÷ö`¢òòF†Rw&–B(	B–çf—6–&ÆR–b–÷RvB67&öÆÆVBF÷vâ’ÂæBF†R'WGFöâ6†÷w2¢òò&W76VB7FFRv†–ÆR—G2æVÂ—2÷Vâà¢f"äTÅ2Ò°¢²vFBÖWfVçBÖ6&BrÂFFD'FåÒÀ¢²w6V&6‚×æVÂrÂG6V&6„'FåÒÀ¢²v77b×æVÂrÂF77d'FåÒÀ¢²w7V'67&–&R×æVÂrÂG7V$'FåÐ¢Ó°¢gVæ7F–öâ6Æ÷6T÷F†W%æVÇ2†¶VW–B’·°¢äTÅ2æf÷$V6‚†gVæ7F–öâ‡’·°¢–b‡³ÒÓÓÒ¶VW–B’&WGW&ã°¢f"VÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‡³Ò“°¢–b†VÂ’VÂç&VÖ÷fR‚“°¢×Ò“°¢×Ð¢gVæ7F–öâ&WfVÅæVÂ†–B’·°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·°¢f"VÂÒFö7VÖVçBævWDVÆVÖVçD'”–B†–B“°¢–b†VÂbbVÂç67&öÆÄ–çFõf–Wr’VÂç67&öÆÄ–çFõf–Wr‡·²&V†f–÷#¢w6Öö÷F‚rÂ&Æö6³¢w7F'Br×Ò“°¢×ÒÂc“°¢×Ð¢gVæ7F–öâ7–æ5FööÆ&%7FFR‚’·°¢äTÅ2æf÷$V6‚†gVæ7F–öâ‡’·°¢–b‡³Ò’³Òæ6Æ74Æ—7BçFövvÆR‚v—2Ö÷VârÂFö7VÖVçBævWDVÆVÖVçD'”–B‡³Ò’“°¢×Ò“°¢òò7FRVÖ–ÂÆ—fW2–ç6–FRF†RFBÖWfVçB6&B(	BÆ–v‡B—BWFöòà¢–b‚G7FT'Fâ’·°¢f"6V2ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚w7FRÖVÖ–Â×6V7F–öâr“°¢G7FT'Fâæ6Æ74Æ—7BçFövvÆR‚v—2Ö÷VârÂ‡6V2bb6V2æ†4GG&–'WFR‚v÷Vâr’’“°¢×Ð¢×Ð¢òòæVÇ2Ç6ò6Æ÷6Rf–F†V—"÷vâ6Æ÷6R'WGFöç2ògFW"6fR(	BvF6€¢òòF†Rw&–B6ò'WGFöâ7FFW27F’G'WF†gVÂæòÖGFW"†÷ræVÂÆVgBà¢G'’·°¢æWr×WFF–öäö'6W'fW"‡7–æ5FööÆ&%7FFR¢æö'6W'fR‚F÷4w&–BÂ·²6†–ÆDÆ—7C¢G'VRÂ7V'G&VS¢fÇ6R×Ò“°¢×Ò6F6‚†R’··×Ð ¢FFD'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢Vç7W&Tw&–Ef–Wr‚“°¢f"W†—7F–ærÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vFBÖWfVçBÖ6&Br“°¢–b†W†—7F–ær’·²W†—7F–ærç&VÖ÷fR‚“²7–æ5FööÆ&%7FFR‚“²&WGW&ã²×Ð¢6Æ÷6T÷F†W%æVÇ2‚vFBÖWfVçBÖ6&Br“°¢÷VäFDf÷&Ò‡··×Ò“°¢&WfVÅæVÂ‚vFBÖWfVçBÖ6&Br“°¢7–æ5FööÆ&%7FFR‚“°¢×Ò“°¢–b‚G7FT'Fâ’·°¢G7FT'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢Vç7W&Tw&–Ef–Wr‚“°¢f"W†—7F–ærÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vFBÖWfVçBÖ6&Br“°¢–b†W†—7F–ær’·²W†—7F–ærç&VÖ÷fR‚“²7–æ5FööÆ&%7FFR‚“²&WGW&ã²×Ð¢6Æ÷6T÷F†W%æVÇ2‚vFBÖWfVçBÖ6&Br“°¢÷VäFDf÷&Ò‡·²W‡æE7FS¢G'VR×Ò“°¢&WfVÅæVÂ‚vFBÖWfVçBÖ6&Br“°¢7–æ5FööÆ&%7FFR‚“°¢×Ò“°¢×Ð¢–b‚G6V&6„'Fâ’·°¢G6V&6„'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢Vç7W&Tw&–Ef–Wr‚“°¢6Æ÷6T÷F†W%æVÇ2‚w6V&6‚×æVÂr“°¢÷Vå6V&6…æVÂ†VÖ–Â“²òò6VÆb×FövvÆW2v†VâÇ&VG’÷Và¢&WfVÅæVÂ‚w6V&6‚×æVÂr“°¢7–æ5FööÆ&%7FFR‚“°¢×Ò“°¢×Ð¢–b‚F77d'Fâ’·°¢F77d'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢Vç7W&Tw&–Ef–Wr‚“°¢6Æ÷6T÷F†W%æVÇ2‚v77b×æVÂr“°¢÷Vä77eæVÂ†VÖ–Â“°¢&WfVÅæVÂ‚v77b×æVÂr“°¢7–æ5FööÆ&%7FFR‚“°¢×Ò“°¢×Ð¢–b‚F–6Ä'Fâ’·°¢F–6Ä'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·²W‡÷'E6fVD4–72‚“²×Ò“°¢×Ð¢–b‚G7V$'Fâ’·°¢G7V$'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ‚’·°¢Vç7W&Tw&–Ef–Wr‚“°¢6Æ÷6T÷F†W%æVÇ2‚w7V'67&–&R×æVÂr“°¢÷Vå7V'67&–&UæVÂ‚“°¢&WfVÅæVÂ‚w7V'67&–&R×æVÂr“°¢7–æ5FööÆ&%7FFR‚“°¢×Ò“°¢×Ð¢×Ð ¢òò)H)H6öÆÆ&÷&F÷"–FVçF—G’†æòÆöv–â’)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòF†Rv†öÆRFVÒ6†&W2F†—2G&6¶W"v—F†÷WB6–væ–ær–ââvR6GW&R¢òòF—7Æ’æÖRöæ6R†Æö6Å7F÷&vR’W&VÇ’6òVF—G2&RGG&–'WFV@¢òò‚$Æ7BVF—B+rF†÷""’â—Bw2æ÷B6V7W&—G’(	B§W7B6÷W'FW7’à¢gVæ7F–öâvWD6öÆÆ$æÖR‚’·°¢f"âÒrs°¢G'’·²âÒ†Æö6Å7F÷&vRævWD—FVÒ‚v"æ6öÆÆ"ææÖRr’ÇÂrr’çG&–Ò‚“²×Ò6F6‚†R’··×Ð¢&WGW&âã°¢×Ð¢gVæ7F–öâ6WD6öÆÆ$æÖR†â’·°¢âÒ†âÇÂrr’çG&–Ò‚“°¢f"&WbÒvWD6öÆÆ$æÖR‚“°¢G'’·²Æö6Å7F÷&vRç6WD—FVÒ‚v"æ6öÆÆ"ææÖRrÂâ“²×Ò6F6‚†R’··×Ð¢Ç”f–ÇFW%f—6–&–Æ—G’‚“²òòævVÆÖöæÇ’$f–ÇFW'2"æVÂ²W&vVçBföÆÆ÷rF†RæÖP¢òòVæFW"F†RÖW&vVBf–WrF†Ru$”BæòÆöævW"FWVæG2öâv†ò–÷R&RÂ6òF†P¢òò&R×&VæFW"†W&R—2Ö÷7FÇ’&÷WBF†RF†–æw2F†B7F–ÆÂFó¢F†R7F ¢òò'WGFöâw2÷vâf–ÆÆVB7FFRÂ–÷W"W"×W'6öâ&6†—fRÂæBævVÆw2W‡G&2à¢òò„—BW6VBFòG&—fRF†R$×’WfVçB–çFW&W7G2"7FBÂF†R×––çFW&W7FVBf–ÇFW ¢òòæBF†R&ÇVR–çFW&W7FVB÷WFÆ–æR(	BÆÂ&WF—&VB##bÓ‚ÓRâ¢–b†âçFôÆ÷vW$66R‚’ÓÒ‡&WbÇÂrr’çFôÆ÷vW$66R‚’bbF÷4w&–BbbF÷4w&–BçVW'•6VÆV7F÷"‚ræ÷2Ö6&Br’’·°¢–b†â’6WEf–Wr‚v×–WfVçG2r“²òòF†÷"w26³¢6WGF–ær–÷W"æÖR÷Vç2×’WfVçG0¢&VæFW$÷2†âÇÂuFVÒr“°¢×Ð¢×Ð¢òòWfW'–öæRÆæG22D„õ"VæÆW72F†W’6’÷F†W'v—6R„‡W&ÆW’##bÓ‚ÓR’à¢òòF†RG&6¶W"W6VBFò÷Vâv—F‚'&÷w6W"&ö×B6¶–ærv†ò–÷R&R(	B¢òòvÆÂ–âg&öçBöbFööÂF†B÷F†W'v—6RæVVG2æòÆöv–âÂæBv—F‚öæRÖW&vV@¢òòf–WrF†Rç7vW"&&VÇ’6†ævW2v†B–÷R6VRâ–FVçF—G’æ÷röæÇ’FV6–FW0¢òòGG&–'WF–öâæB–÷W"÷vâ&6†—fRÂ6ò6Vç6–&ÆRFVfVÇB&VG2à¢òò–çFW'&övF–öââ6†ævR—Bç’F–ÖRf–F†RfF"(i"%6öÖVöæRVÇ6^(
b"à¢f"%ôDTdTÅEôäÔRÒuF†÷"s°¢gVæ7F–öâVç7W&T6öÆÆ$æÖR‚’·°¢f"âÒvWD6öÆÆ$æÖR‚“°¢òòöævVÆ•2ævVÆw2vR(	B6WGFÆR—BF†W&R&F†W"F†âFVfVÇF–ær†W ¢òòFòF†÷"æB6–væ–ær†W"VF—G22†–Òà¢–b…ö—4ævVÆ&÷WFR‚’bb7G&–ær†âÇÂrr’çG&–Ò‚’çFôÆ÷vW$66R‚’æ–æFW„öb‚vævVÆr’ÓÒ’·°¢6WD6öÆÆ$æÖR‚tævVÆr“²&WGW&âtævVÆs°¢×Ð¢–b‚â’·²6WD6öÆÆ$æÖR„%ôDTdTÅEôäÔR“²&WGW&â%ôDTdTÅEôäÔS²×Ð¢&WGW&âã°¢×Ð ¢òò)H)H'&–FvRf÷"F†RFWF–ÂÖöFÂ‡v†–6‚Æ—fW2–â6W&FR6Æ÷7W&R’)H)H ¢òòF†RÖöFÂw2V–6²Ö7F–öâ'WGFöç2²$VF—BWfVçB"6ÆÂF†W6Râ÷5w&—FP¢òò&÷WFW2F6‚FòF†R&–v‡BF&ÆS²÷4÷VäVF—F÷"W‡æG2F†R6÷W&6P¢òò6&Bw2gVÆÂVF—Bf÷&Òà¢f"õ5DtUôõ$DU"Ò²u7V&Ö—GFVBrÂt–æ—F–Â÷WG&V6‚rÂtföÆÆ÷vVBWrÂtÖVWF–ær†VÆBrÂt&öö¶VBrÂu&V¦V7FVBrÂtGFVæF–æruÓ°¢v–æF÷ræ÷57FvT÷&FW"Òõ5DtUôõ$DU#°¢òò'&–FvR6òF†RÖöFÂw2VF—Bf÷&Ò‡6W&FR6Æ÷7W&R’6â&RÖFW&—fRF†P¢òò7G'V7GW&VB7F'BöVæBFFW2v†VâÖçVÂWfVçBw2FFRDU…B—2VF—FVBà¢v–æF÷ræ÷4FW&—fTFFW2ÒFW&—fTFFW4g&öÕFW‡C°¢v–æF÷ræ÷5w&—FRÒgVæ7F–öâ‡F&ÆRÂ¶W’ÂF6‚’·°¢÷4–çfÆ–FFT—FV×2‚“°¢f"v†òÒvWD6öÆÆ$æÖR‚’ÇÂuFVÒs°¢f"'Vã°¢–b‡F&ÆRÓÓÒvÖçVÅöWfVçG2r’·°¢òò7F×F†RVF—BG&–Â†W&RFöò„‡W&ÆW’##bÓrÓ3’âÖçVÅöWfVçG0¢òò&V6÷&FVBöæÇ’7&VFVEöBò7&VFVEö'’Â6òöæ6R&÷rW†—7FVBF†W&P¢òòv2æò&V6÷&B—B†BWfW"6†ævVB(	BæB$–âF†RÆ7BvVV²"†@¢òòæ÷F†–ærFòFFRÖçVÂÖWfVçBVF—Bg&öÒÂv†–6‚—2v‡’F†÷6RVF—G0¢òòæWfW"7W&f6VBâF†RÖ–w&F–öâÆæFVB##bÓ’ÓÂ6òF†W6Ræ÷p¢òòW'6—7C²Ö—76–ærÖ6öÇVÖâW'&÷"†W&R—2&VÂfVÇBæBv&ç2à¢F6‚çWFFVEö'’Òv†ó°¢F6‚çWFFVEöBÒæWrFFR‚’çFô•4õ7G&–ær‚“°¢'VâÒ6%w&—FU&WG'’‡F6‚ÂgVæ7F–öâ‡’·²&WGW&â6"æg&öÒ‚vÖçVÅöWfVçG2r’çWFFR‡’æW‚v–BrÂ¶W’“²×Ò“°¢×ÒVÇ6R·°¢F6‚çWFFVEö'’Òv†ó°¢f"ÒF–7Eö76–vâ‡·²WfVçEöçVÓ¢¶W’×ÒÂF6‚“°¢'VâÒ6%w&—FU&WG'’‡ÂgVæ7F–öâ‡’·²&WGW&â6"æg&öÒ‚vWfVçE÷7FFRr’çW6W'B‡Â·²öä6öæfÆ–7C¢vWfVçEöçVÒr×Ò“²×Ò“°¢×Ð¢&WGW&â'VâçF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7bb&W7æW'&÷"’·²7FGW2‚u6fRf–ÆVC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“²×Ð¢VÇ6R–b‡&W7bb&W7ç7G&—VDÖ–w&F–öä6öÇ2bb&W7ç7G&—VDÖ–w&F–öä6öÇ2æÆVæwF‚’·°¢òòF†Rw&—FRÄäDTBÂ'WBöæR÷"Ö÷&RW6W"ÖVçFW&VB6öÇVÖç2FöâwBW†—7B–à¢òòF†RFF&6R–WB†VæF–ærÖ–w&F–öâ’Â6òF†÷6RfÇVW2vW&RG&÷VBà¢òò6’6ò–ç7FVBöbfÆ6†–ærÖ—6ÆVF–ær%6fVB"‡F†—2v2F†R6–ÆVç@¢òò$Ç’Fò7V²Æ–æ²FöW6âwB7F÷&R"'Vr’à¢7FGW2‚u6fVBF†R&W7B(	B'WB"r²&W7ç7G&—VDÖ–w&F–öä6öÇ2æ¦ö–â‚r"Â"r’°¢r"6÷VÆBæ÷B&R7F÷&VC¢F†B6öÇVÖâ—2Ö—76–ærg&öÒF†RFF&6Râ—BæVVG2öæR×F–ÖR7W&6RÖ–w&F–öâ&Vf÷&R—Bv–ÆÂ6fRârÂvW'&÷"r“°¢&VæFW$÷2‡v†ò“°¢×Ð¢VÇ6R·²fÆ6„ö²‚u6fVBr“²&VæFW$÷2‡v†ò“²×Ð¢&WGW&â&W7°¢×Ò“°¢×Ó°¢gVæ7F–öâF–7Eö76–vâ†Â"’·²f÷"‡f"²–â"’·²–b„ö&¦V7Bç&÷F÷G—Ræ†4÷vå&÷W'G’æ6ÆÂ†"Â²’’¶µÒÒ%¶µÓ²×Ò&WGW&â²×Ð¢òò7W'&VçB6öÆÆ&÷&F÷"w2F—7Æ’æÖRÂf÷"F†RÖöFÂw2$’vÒ–çFW&W7FVB ¢òòFövvÆRâ72Vç7W&S×G'VRFò&ö×Bf÷"æÖR–bæöæR—26WB–WBà¢v–æF÷ræ÷47W'&VçEW6W"ÒgVæ7F–öâ†Vç7W&R’·°¢–b†Vç7W&RbbvWD6öÆÆ$æÖR‚’’&WGW&âVç7W&T6öÆÆ$æÖR‚“°¢&WGW&âvWD6öÆÆ$æÖR‚’ÇÂrs°¢×Ó°¢òò&RÖfWF6‚²&R×&VæFW"WfW'—F†–ær‡W6VBgFW"6W'fW"×6–FRVç&–6†ÖVçBw&—FW2’à¢v–æF÷ræ÷5&Vg&W6‚ÒgVæ7F–öâ‚’·²&WGW&â&VæFW$÷2†vWD6öÆÆ$æÖR‚’ÇÂuFVÒr“²×Ó°¢òò)H)H$FöâwB'&–ærF†—2&6²"&6¶Æör)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòWfW'’FVÆWFR—2&V6÷&FVB–âFVÆWFVEöWfVçG26òF†Ræ–v‡FÇ’GW7B–ævW7B6à¢òò6¶—âWfVçB6öÖVöæR†2Ç&VG’F‡&÷vâ÷WB†’öWfVçG2ç’&VG2F†—0¢òòF&ÆRæB&W÷'G2—B2'&Wf–÷W6Ç’FVÆWFVB"’â†&BÖFVÆWFVBÖçVÂWfVç@¢òòW6VBFòÆVfRæòG&6RBÆÂÂ6òF†R67&W"v÷VÆB&RÖFB—BF—2ÆFW"à¢òð¢òò&W7BÖVff÷'B'’FW6–vã¢F&ÆRF†B†6âwB&VVâÖ–w&FVB–WBÂ÷"f–ÆV@¢òò–ç6W'BÂäUdU"&Æö6·2F†RFVÆWFRâv÷'7B66RF†R67&W"&R×7VvvW7G2—Bà¢gVæ7F–öâ&V6÷&DFVÆWFVB†–æfò’·°¢–b‚–æfòÇÂ–æfòææÖR’&WGW&ã°¢f"&÷rÒ·°¢æÖS¢7G&–ær†–æfòææÖR’ç6Æ–6RƒÂ3’À¢7F'EöFFS¢†–æfòç7F'EöFFRbbõåÅÆG·³G×ÒÕÅÆG·³'×ÒÕÅÆG·³'×ÒòçFW7B†–æfòç7F'EöFFR’’ò7G&–ær†–æfòç7F'EöFFR’ç6Æ–6RƒÂ’¢çVÆÂÀ¢Æö6F–öã¢–æfòæÆö6F–öâò7G&–ær†–æfòæÆö6F–öâ’ç6Æ–6RƒÂ3’¢çVÆÂÀ¢6÷W&6U÷F&ÆS¢–æfòçF&ÆRÇÂçVÆÂÀ¢6÷W&6Uö¶W“¢†–æfòæ¶W’ÓÒçVÆÂ’òçVÆÂ¢7G&–ær†–æfòæ¶W’’À¢FVÆWFVEö'“¢vWD6öÆÆ$æÖR‚’ÇÂçVÆÂÀ¢&V6öã¢–æfòç&V6öâÇÂvFVÆWFVB–âF†RG&6¶W"p¢×Ó°¢G'’·°¢6"æg&öÒ‚vFVÆWFVEöWfVçG2r’æ–ç6W'B‡&÷r’çF†Vâ†gVæ7F–öâ‡"’·°¢–b‡"bb"æW'&÷"’6öç6öÆRçv&â‚vFVÆWFVEöWfVçG2æ÷B&V6÷&FVC¢r²"æW'&÷"æÖW76vR“°¢×ÒÂgVæ7F–öâ†R’·²6öç6öÆRçv&â‚vFVÆWFVEöWfVçG2æ÷B&V6÷&FVC¢r²R“²×Ò“°¢×Ò6F6‚†R’·²6öç6öÆRçv&â‚vFVÆWFVEöWfVçG2æ÷B&V6÷&FVC¢r²R“²×Ð¢×Ð¢v–æF÷ræ÷5&V6÷&DFVÆWFVBÒ&V6÷&DFVÆWFVC°¢òòæÖRòFFRòÆö6F–öâf÷"F†R&÷r&V–ærFVÆWFVBÂVÆÆVBg&öÒv†Bw0¢òòÇ&VG’ÆöFVB†âWfVçE÷7FFR÷fW'&–FRv–ç2÷fW"F†R6FÆörfÇVRÂ6ÖP¢òò2WfW'—v†W&RVÇ6R’â&WGW&ç2æÖVÆW727GV"–bvR6âwBf–æB—B(	BF†Và¢òò&V6÷&DFVÆWFVBæòÖ÷2&F†W"F†âw&—F–ærW6VÆW72&÷rà¢gVæ7F–öâöFVÆWFVD–æfôf÷"‡F&ÆRÂ¶W’’·°¢f"òÒçVÆÂÂ7BÒ··×Ó°¢–b‡F&ÆRÓÓÒvÖçVÅöWfVçG2r’·°¢òÒ…öÆ7DÖçVÂÇÂµÒ’æf–ÇFW"†gVæ7F–öâ†Ò’·²&WGW&â7G&–ær†Òæ–B’ÓÓÒ7G&–ær†¶W’“²×Ò•³Ó°¢7BÒòÇÂ··×Ó°¢×ÒVÇ6R·°¢òÒ…öÆ7DWg2ÇÂµÒ’æf–ÇFW"†gVæ7F–öâ†R’·²&WGW&â7G&–ær†RæçVÒ’ÓÓÒ7G&–ær†¶W’“²×Ò•³Ó°¢7BÒ†òbb…öÆ7E7FFTÖÇÂ··×Ò•¶òæçVÕÒ’ÇÂ··×Ó°¢×Ð¢–b‚ò’&WGW&â·²F&ÆS¢F&ÆRÂ¶W“¢¶W’ÂæÖS¢rr×Ó°¢&WGW&â·°¢F&ÆS¢F&ÆRÂ¶W“¢¶W’À¢æÖS¢7BææÖRÇÂòææÖRÇÂrrÀ¢7F'EöFFS¢7Bç7F'EöFFRÇÂòç7F'EöFFRÇÂrrÀ¢Æö6F–öã¢7BæÆö6F–öâÇÂòæÆö6F–öâÇÂrp¢×Ó°¢×Ð ¢òòFVÆWFR'&–FvRf÷"F†RÖöFÂw2VF—Bf÷&ÒâÖçVÂWfVçG2&R†&BÖFVÆWFVC°¢òò6FÆörWfVçG2†g&öÒF†RF–Ç’–ævW7B’&RW'6—7FVçFÇ’7W&W76VBf–¢òòuõöFVÆWFVEõòr6VçF–æVÂöâF†V—"WfVçE÷7FFR&÷rÂ6òF†W’FöâwB&VV"à¢òòV—F†W"v’F†RWfVçBvöW2öâF†RFVÆWFVEöWfVçG2&6¶Æörf—'7BÂ6òF†P¢òò–ævW7BvöâwBöffW"—Bv–âà¢òò7&VFRÖçVÂWfVçBg&öÒç—v†W&R–âF†RâvöW2F‡&÷Vv‚6%w&—FU&WG'’À¢òò6ò6öÇVÖâF†RD"FöW6âwB†fR–WB†÷&uöw&÷W&Vf÷&R—G2Ö–w&F–öâ'Vç2¢òò—27G&—VBæBF†R–ç6W'B7F–ÆÂ7V66VVG2&F†W"F†âf–Æ–ær÷WG&–v‡Bà¢v–æF÷ræ÷47&VFTÖçVÂÒgVæ7F–öâ‡&÷r’·°¢f""Ò··×Ó°¢f÷"‡f"²–â&÷r’·°¢–b„ö&¦V7Bç&÷F÷G—Ræ†4÷vå&÷W'G’æ6ÆÂ‡&÷rÂ²’bb&÷u¶µÒÓÒçVÆÂbb&÷u¶µÒÓÒrr’%¶µÒÒ&÷u¶µÓ°¢×Ð¢–b‚7G&–ær‡"ææÖRÇÂrr’çG&–Ò‚’’&WGW&â&öÖ—6Rç&V¦V7B†æWrW'&÷"‚væÖR&WV—&VBr’“°¢&WGW&â6%w&—FU&WG'’‡"ÂgVæ7F–öâ‡’·²&WGW&â6"æg&öÒ‚vÖçVÅöWfVçG2r’æ–ç6W'B‡’ç6VÆV7B‚“²×Ò¢çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7bb&W7æW'&÷"’·°¢7FGW2‚t6÷VÆBæ÷BFBF†RWfVçC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“°¢F‡&÷ræWrW'&÷"‡&W7æW'&÷"æÖW76vR“°¢×Ð¢–b‡&W7bb&W7ç7G&—VDÖ–w&F–öä6öÇ2bb&W7ç7G&—VDÖ–w&F–öä6öÇ2æÆVæwF‚’·°¢7FGW2‚tFFVBÂ'WB"r²&W7ç7G&—VDÖ–w&F–öä6öÇ2æ¦ö–â‚rÂr’°¢r"æVVG2—G2Ö–w&F–öâ&Vf÷&RF†R÷&væ—6W"Æ–æ²7F–6·2ârÂvW'&÷"r“°¢×ÒVÇ6R·°¢fÆ6„ö²‚tWfVçBFFVBr“°¢×Ð¢–b‡G—VöbÆöD¶æ÷väæÖW2ÓÓÒvgVæ7F–öâr’ÆöD¶æ÷väæÖW2‚“°¢&VæFW$÷2†vWD6öÆÆ$æÖR‚’ÇÂuFVÒr“°¢&WGW&â&W7æFFbb&W7æFF³Ó°¢×Ò“°¢×Ó°¢v–æF÷ræ÷4FVÆWFRÒgVæ7F–öâ‡F&ÆRÂ¶W’’·°¢f"ö–æfòÒöFVÆWFVD–æfôf÷"‡F&ÆRÂ¶W’“°¢–b‡F&ÆRÓÓÒvÖçVÅöWfVçG2r’·°¢&WGW&â6"æg&öÒ‚vÖçVÅöWfVçG2r’æFVÆWFR‚’æW‚v–BrÂ¶W’’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7bb&W7æW'&÷"’·²7FGW2‚tFVÆWFRf–ÆVC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“²×Ð¢VÇ6R·°¢òò&V6÷&BöæÇ’öæ6RF†RFVÆWFR7GVÆÇ’ÆæFVBà¢&V6÷&DFVÆWFVB…ö–æfò“°¢fÆ6„ö²‚tÖçVÂWfVçBFVÆWFVBr“²–b‡G—VöbÆöD¶æ÷väæÖW2ÓÓÒvgVæ7F–öâr’ÆöD¶æ÷väæÖW2‚“²&VæFW$÷2†vWD6öÆÆ$æÖR‚’ÇÂuFVÒr“°¢×Ð¢&WGW&â&W7°¢×Ò“°¢×Ð¢òò6FÆörWfVçB(	B6ögBÖFVÆWFRf–÷5w&—FR‡&R×&VæFW'2²f–ÇFW'2—B÷WB’à¢&V6÷&DFVÆWFVB…ö–æfò“°¢&WGW&âv–æF÷ræ÷5w&—FR‚vWfVçE÷7FFRrÂ¶W’Â·²7FGW3¢uõöFVÆWFVEõòr×Ò“°¢×Ó° ¢òò)H)HW"ÖWfVçBFVÒ6†B‡F†R$F—67W76–öâ"F‡&VB’)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢òòF†RÖöFÂÆ—fW2–â6W&FR6Æ÷7W&Rv—F‚æòF—&V7B6&Â6ò—B†æG2W0¢òòF†R&V6÷&BæBvR÷vâfWF6‚ò&VæFW"ò6VæB†W&RâFVw&FW2V–WFÇ’Fò¢òò''VâF†RÖ–w&F–öâ"æ÷FR–bF†RWfVçEö6†BF&ÆR—6âwBF†W&R–WBà¢f"ö6†D6÷VçG2Ò··×Ó°¢f"ö6†DÖWFÒ··×Ó²òòW"WfVçC¢·¶6÷VçBÂÆFW7BÂ×6w3¥··¶WF†÷"ÂG×Õ××Ò(	BfVVG2$–âF†RÆ7BvVV² ¢òòVW7F–öç2FòF†R76—7FçB&RG&ç6–VçB(	BF†W’W†—7BFòFVÆÂævVÆv†@¢òò6öÖVöæRv2Æöö¶–ærBF†—2vVV²Âæ÷BFò&V6öÖRW&ÖæVçB†—7F÷'’âöæ6P¢òòF†W’vR7BF†R$–âF†RÆ7BvVV²"v–æF÷rF†W’†fR6W'fVBF†V— ¢òòW'÷6RÂ6òF†W’w&R6ÆV&VB&F†W"F†â–Æ–ærWf÷&WfW ¢òò„‡W&ÆW’##bÓrÓ3’â7W÷'B'Vç2F†R7vVW6ò—B†Vç2öæ6RÂæ÷Böæ6P¢òòW"FVÖÖFRà¢gVæ7F–öâ÷W&vTöÆD6·2‚’·°¢–b‚—57W÷'EW'6öâ†vWD6öÆÆ$æÖR‚’ÇÂrr’’&WGW&ã°¢f"7WBÒæWrFFR„FFRææ÷r‚’Òr¢ƒcC’çFô•4õ7G&–ær‚“°¢G'’·°¢6"æg&öÒ‚vWfVçEö6†Br’æFVÆWFR‚¢æÇB‚v7&VFVEöBrÂ7WB’æÆ–¶R‚v&öG’rÂrT6¶VB“¢Rr¢çF†Vâ†gVæ7F–öâ‚’··×ÒÂgVæ7F–öâ‚’··×Ò“°¢×Ò6F6‚†R’··×Ð¢×Ð¢gVæ7F–öâÆöD6†D6÷VçG2‚’·°¢÷W&vTöÆD6·2‚“°¢6"æg&öÒ‚vWfVçEö6†Br’ç6VÆV7B‚vWfVçEöçVÒÆÖçVÅö–BÆWF†÷"Æ7&VFVEöBÆ&öG’r’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"ÇÂ&W7æFF’&WGW&ã²òòF&ÆRæ÷BÖ–w&FVB–WBÓâæò6÷VçG2Âæòæö—6P¢f"6÷VçG2Ò··×ÒÂÖWFÒ··×Ó°¢&W7æFFæf÷$V6‚†gVæ7F–öâ‡"’·°¢f"²Ò‡"æÖçVÅö–BÒçVÆÂ’ò‚vÒr²"æÖçVÅö–B’¢‡"æWfVçEöçVÒÒçVÆÂò‚v2r²"æWfVçEöçVÒ’¢çVÆÂ“°¢–b‚²’&WGW&ã°¢òòD„R$DtRÕU5B4õTåBt„BD„RD…$TB4„õu2â$6¶VB’"&÷w2&P¢òò7F÷&VB–âWfVçEö6†B'WBæWfW"&VæFW&VB26öçfW'6F–öâÂ6òà¢òòWfVçBv†÷6RöæÇ’&÷rv2â’VW7F–öâv÷&R/	ù*Â"÷fW"âV×G¢òòF‡&VB(	B–÷R6Æ–6¶VB–âW‡V7F–ærÖW76vRæBf÷VæBæ÷F†–æp¢òò„‡W&ÆW’##bÓ‚ÓRÂ6öÆöÖ&–FV6‚vVV³¢öæR&÷rÂ.)Ù26¶VB“ ¢òòv†Bw2F†R7FGW2öâF†—3ò"’â6ÖR$—46µ&÷r‚’F†RF‡&VBf–ÇFW'0¢òòv—F‚Â6òF†RGvò6âwBF—6w&VRv–âà¢òòF†W’5D’–âÖWFæ×6w3¢$–âF†RÆ7BvVV²"7Æ—G26·2g&öÒ&VÀ¢òòÖW76vW2—G6VÆbæBæVVG2&÷F‚à¢f"ö—46²Òv–æF÷ræ$—46µ&÷r‡"æ&öG’“°¢–b‚ö—46²’6÷VçG5¶µÒÒ†6÷VçG5¶µÒÇÂ’²°¢f"ÒÒ†ÖWF¶µÒÒÖWF¶µÒÇÂ·²6÷VçC¢ÂÆFW7C¢rrÂ×6w3¢µÒ×Ò“°¢–b‚ö—46²’Òæ6÷VçB²³°¢–b‚‡"æ7&VFVEöBÇÂrr’âÒæÆFW7B’ÒæÆFW7BÒ"æ7&VFVEöBÇÂrs°¢Òæ×6w2çW6‚‡·²WF†÷#¢"æWF†÷"ÇÂrrÂC¢"æ7&VFVEöBÇÂrrÂ&öG“¢"æ&öG’ÇÂrr×Ò“°¢×Ò“°¢ö6†D6÷VçG2Ò6÷VçG3²ö6†DÖWFÒÖWF²÷–çD6†D6÷VçG2‚“°¢–b†7W'&VçEf–WrÓÓÒv×–WfVçG2r’&VæFW$×”WfVçG2‚“²òò&Vg&W6‚&æWr6öÖÖVçG2"&÷w0¢×Ò“°¢×Ð¢gVæ7F–öâ÷–çD6†D6÷VçG2‚’·°¢'&’ç&÷F÷G—Ræf÷$V6‚æ6ÆÂ†Fö7VÖVçBçVW'•6VÆV7F÷$ÆÂ‚ræ6†BÖ6÷VçE¶FFÖ6†F¶W•Òr’ÂgVæ7F–öâ†VÂ’·°¢f"âÒö6†D6÷VçG5¶VÂævWDGG&–'WFR‚vFFÖ6†F¶W’r•ÒÇÂ°¢VÂçFW‡D6öçFVçBÒâò‚uÅÇTCƒ4EÅÇTD42r²â’¢rs°¢VÂç7G–ÆRæF—7Æ’Òâòrr¢væöæRs°¢×Ò“°¢×Ð¢òòÖW76vRw2	ùÒÿ	ùâFÆÆ–W2‡7F÷&VB–âWfVçEö6†Bç&V7F–öç2§6öæ"(	@¢òò··W¥¶æÖW5ÒÂF÷vã¥¶æÖW5××Ó²'6VçBVçF–ÂF†RÖ–w&F–öâ'Vç2(i"æòÆ–æR’à¢òòV–6²×&V7F–öâÆWGFR‡F‡VÖ'2f—'7BÂF†Vâv–FW"&ævR’(	B6Æ6²×7G–ÆRà¢f"4„EôTÔô¤•2Ò²uÅÇVCƒ6EÅÇVF3FBrÂuÅÇVCƒ6EÅÇVF3FRrÂuÅÇS#scEÅÇVfSbrÂuÅÇVCƒ65ÅÇVFcƒ’rÂuÅÇS#sRrÂuÅÇVCƒ6EÅÇVF3CrÂuÅÇVCƒ6EÅÇVFSF2uÓ°¢òòæ÷&ÖÆ—¦R&V7F–öç2&Æö"Fò·¶VÖö¦“¢¶æÖW5××ÒÂföÆF–ærF†RÆVv7¢òòWöF÷vâ6†R–çFò	ùÒÿ	ùâ6òöÆB&V7F–öç27F–ÆÂ&VæFW"à¢gVæ7F–öâöæ÷&Õ&V7F–öç2‡'‚’·°¢–b‚'‚ÇÂG—Vöb'‚ÓÒvö&¦V7Br’&WGW&â··×Ó°¢f"÷WBÒ··×Ó°¢ö&¦V7Bæ¶W—2‡'‚’æf÷$V6‚†gVæ7F–öâ†²’·°¢f"VÒÒ²ÓÓÒwWròuÅÇVCƒ6EÅÇVF3FBr¢†²ÓÓÒvF÷vâròuÅÇVCƒ6EÅÇVF3FRr¢²“°¢–b‚'&’æ—4'&’‡'…¶µÒ’’&WGW&ã°¢÷WE¶VÕÒÒ†÷WE¶VÕÒÇÂµÒ’æ6öæ6B‡'…¶µÒ“°¢×Ò“°¢&WGW&â÷WC°¢×Ð¢òò6†÷rt„ò&V7FVBÂæ÷B§W7B6÷VçB(	Bf—'7BæÖW2–æÆ–æR†6VBÂ´â’à¢gVæ7F–öâ÷&V7Ev†ò†Æ—7B’·°¢f"bÒÆ—7BæÖ†gVæ7F–öâ†â’·²&WGW&â7G&–ær†â’ç7Æ—B‚õÅÇ2²ò•³Ó²×Ò“°¢–b†bæÆVæwF‚ÃÒ2’&WGW&âbæ¦ö–â‚rÂr“°¢&WGW&âbç6Æ–6RƒÂ"’æ¦ö–â‚rÂr’²r²r²†bæÆVæwF‚Ò"“°¢×Ð¢gVæ7F–öâö6†E&V7DÆ–æR‡'‚ÂÖR’·°¢'‚Òöæ÷&Õ&V7F–öç2‡'‚“°¢f"÷WBÒµÓ°¢ö&¦V7Bæ¶W—2‡'‚’æf÷$V6‚†gVæ7F–öâ†VÒ’·°¢f"Æ—7BÒ'…¶VÕÒÇÂµÓ²–b‚Æ—7BæÆVæwF‚’&WGW&ã°¢f"Ö–æRÒÖRbbÆ—7Bç6öÖR†gVæ7F–öâ†â’·²&WGW&â7G&–ær†â’çFôÆ÷vW$66R‚’ÓÓÒÖS²×Ò“°¢÷WBçW6‚‚sÇ7â6Æ73Ò&6†B×&V7Br²†Ö–æRòr—2ÖÖ–æRr¢rr’²r"F—FÆSÒ"r²W66T‡FÖÂ†Æ—7Bæ¦ö–â‚rÂr’’²r#âr°¢VÒ²rÇ7â6Æ73Ò&6†B×&V7B×v†ò#âr²W66T‡FÖÂ…÷&V7Ev†ò†Æ—7B’’²sÂ÷7ããÂ÷7ãâr“°¢×Ò“°¢&WGW&â÷WBæÆVæwF‚òsÆF—b6Æ73Ò&6†B×&V7G2#âr²÷WBæ¦ö–â‚rr’²sÂöF—câr¢rs°¢×Ð¢òòFövvÆR×’&V7F–öâv—F‚ç’VÖö¦’g&öÒF†RÆWGFRà¢gVæ7F–öâö6†E&V7B†ÒÂVÖö¦’’·°¢f"v†òÒ†vWD6öÆÆ$æÖR‚’ÇÂrr’çG&–Ò‚“²–b‚v†ò’·²Vç7W&T6öÆÆ$æÖR‚“²&WGW&ã²×Ð¢f"Æ2Òv†òçFôÆ÷vW$66R‚“°¢f"'‚Òöæ÷&Õ&V7F–öç2†Òç&V7F–öç2“°¢f"†BÒ‡'…¶VÖö¦•ÒÇÂµÒ’ç6öÖR†gVæ7F–öâ†â’·²&WGW&â7G&–ær†â’çFôÆ÷vW$66R‚’ÓÓÒÆ3²×Ò“°¢f"7W"Ò‡'…¶VÖö¦•ÒÇÂµÒ’æf–ÇFW"†gVæ7F–öâ†â’·²&WGW&â7G&–ær†â’çFôÆ÷vW$66R‚’ÓÒÆ3²×Ò“°¢–b‚†B’7W"çW6‚‡v†ò“°¢–b†7W"æÆVæwF‚’'…¶VÖö¦•ÒÒ7W#²VÇ6RFVÆWFR'…¶VÖö¦•Ó°¢Òç&V7F–öç2Ò'ƒ²òò÷F–Ö—7F–2(	B6òV–6²&R×FövvÆR6VW2F†RæWr7FFP¢6"æg&öÒ‚vWfVçEö6†Br’çWFFR‡·²&V7F–öç3¢'‚×Ò’æW‚v–BrÂÒæ–B’ç6VÆV7B‚v–BÂ&V7F–öç2r’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"’·°¢7FGW2‚ö6öÇVÖçÇ&V7F–öç2ö’çFW7B‡&W7æW'&÷"æÖW76vRÇÂrr¢òu&V7F–öç2æVVBF†RöæR×F–ÖRÖ–w&F–öâ‡67&—G2ó##bÓrÓö6†E÷&V7F–öç2ç7Â’–â7W&6Râp¢¢u&V7F–öâæ÷B6fVC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“°¢&WGW&ã°¢×Ð¢òò$Å2v—F‚æòUDDRöÆ–7’&WGW&ç27V66W72'WB&÷w2(	BFWFV7BF†Bæ@¢òòFVÆÂF†RW6W"W†7FÇ’v†BFò'Vâ‡F†RWFFVB6†E÷&V7F–öç2ç7ÂFG0¢òòF†RUDDRöÆ–7’’à¢–b‚&W7æFFÇÂ&W7æFFæÆVæwF‚’·°¢7FGW2‚u&V7F–öç26÷VÆFåÅÇS#—B6fRÅÇS#BWfVçEö6†BæVVG2âUDDRöÆ–7’â&R×'VâF†RWFFVB67&—G2ó##bÓrÓö6†E÷&V7F–öç2ç7Â–â7W&6RârÂvW'&÷"r“°¢&WGW&ã°¢×Ð¢÷&VÆöD÷Vä6†B‚“°¢×Ò“°¢×Ð¢òòf÷'v&BÖW76vRFòFVÖÖFS¢–6²æÖRÂæB—B÷7G2.(j¢æÖR(	BÆ×6sâ ¢òò–çFòF†—2WfVçBw26†BÂv†–6‚–æw2F†VÒf–F†R$–âF†RÆ7BvVV²"ÖVçF–öâà¢òò÷6—F–öâ6†B÷÷fW"†f÷'v&BòÖ÷&R’2f—†VB'÷'FÂ"æ6†÷&VBFð¢òò—G2G&–vvW"'WGFöââVæFVBFòÆ&öG“â(	BäõB–ç6–FRF†Ræ6†BÖÆ—7B(	B6ò—@¢òò—2æWfW"6Æ—VB'’F†RÆ—7Bw2÷fW&fÆ÷r67&öÆÂæ÷"6÷fW&VB'’F†RÖW76vP¢òò&VÆ÷r—B‡F†Bv2v‡’öæÇ’F†RÆ7BÖW76vRw2ÖVçRv2&V6†&ÆR’à¢gVæ7F–öâ÷÷6—F–öä6†DÖVçR†ÖVçRÂ'Fâ’·°¢òòöæÇ’WfW"öæR6†B÷÷fW"BF–ÖR(	B7vVWç’÷F†W"÷VâöæR†–æ6Âà¢òòF†R÷F†W"G—R’6òf÷'v&B²(ºò6âwB&÷F‚†ær÷Vâà¢Fö7VÖVçBçVW'•6VÆV7F÷$ÆÂ‚ræ6†BÖgvBÖÖVçRÂæ6†BÖÖ÷&RÖÖVçRr’æf÷$V6‚†gVæ7F–öâ‡‚’·²‚ç&VÖ÷fR‚“²×Ò“°¢Fö7VÖVçBæ&öG’æVæD6†–ÆB†ÖVçR“°¢f""Ò'FâævWD&÷VæF–æt6Æ–VçE&V7B‚“°¢ÖVçRç7G–ÆRç÷6—F–öâÒvf—†VBs°¢ÖVçRç7G–ÆRæÆVgBÒvWFòs°¢ÖVçRç7G–ÆRç&–v‡BÒÖF‚æÖ‚ƒ‚Âv–æF÷ræ–ææW%v–GF‚Ò"ç&–v‡B’²w‚s°¢f"Ö‚ÒÖVçRæöfg6WD†V–v‡BÇÂCC²òòæ÷rÖV7W&&ÆR†–âDôÒ¢f"F÷Ò"æ&÷GFöÒ²C°¢–b‡F÷²Ö‚âv–æF÷ræ–ææW$†V–v‡BÒ‚’F÷ÒÖF‚æÖ‚ƒ‚Â"çF÷ÒÖ‚ÒB“²òòfÆ—WæV"&÷GFöÐ¢ÖVçRç7G–ÆRçF÷ÒF÷²w‚s°¢òòf—†VBÖVçR6âwBföÆÆ÷rF†R'WGFöâÂ6ò6Æ÷6R—Böâ67&öÆÂ÷&W6—¦P¢òò–ç7FVBöbÆWGF–ær—BfÆöBFWF6†VBâ6VÆb×&VÖ÷f–ærÆ—7FVæW'2à¢f"öF—6Ö—72ÒgVæ7F–öâ‚’·²ÖVçRç&VÖ÷fR‚“²v–æF÷rç&VÖ÷fTWfVçDÆ—7FVæW"‚w67&öÆÂrÂöF—6Ö—72ÂG'VR“²v–æF÷rç&VÖ÷fTWfVçDÆ—7FVæW"‚w&W6—¦RrÂöF—6Ö—72“²×Ó°¢v–æF÷ræFDWfVçDÆ—7FVæW"‚w67&öÆÂrÂöF—6Ö—72ÂG'VR“°¢v–æF÷ræFDWfVçDÆ—7FVæW"‚w&W6—¦RrÂöF—6Ö—72“°¢×Ð¢gVæ7F–öâö6†Df÷'v&B†ÒÂ'Fâ’·°¢f"÷VâÒFö7VÖVçBçVW'•6VÆV7F÷"‚ræ6†BÖgvBÖÖVçRr“²–b†÷Vâ’÷Vâç&VÖ÷fR‚“°¢f"Òv–æF÷rä%õU%4ôä2ÇÂ··×Ó°¢f"6VVâÒ··×ÒÂÆ—7BÒµÓ°¢ö&¦V7Bæ¶W—2…’æf÷$V6‚†gVæ7F–öâ†²’·°¢f"âÒ…¶µÒbb¶µÒææÖR’ò7G&–ær…¶µÒææÖR’ç7Æ—B‚õÅÇ2²ò•³Ò¢³°¢f"Æ2ÒâçFôÆ÷vW$66R‚“²–b‡6VVå¶Æ5Ò’&WGW&ã²6VVå¶Æ5ÒÒ²Æ—7BçW6‚†â“°¢×Ò“°¢–b‚Æ—7BæÆVæwF‚’&WGW&ã°¢f"ÖVçRÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“²ÖVçRæ6Æ74æÖRÒv6†BÖgvBÖÖVçRs°¢ÖVçRæ–ææW$…DÔÂÒsÆF—b6Æ73Ò&6†BÖgvBÖ†VB#äf÷'v&BFóÂöF—câr°¢Æ—7BæÖ†gVæ7F–öâ†â’·²&WGW&âsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6†BÖgvBÖ—FVÒ"FFÖgvCÒ"r²W66T‡FÖÂ†â’²r#âr²W66T‡FÖÂ†â’²sÂö'WGFöãâs²×Ò’æ¦ö–â‚rr“°¢÷÷6—F–öä6†DÖVçR†ÖVçRÂ'Fâ“°¢gVæ7F–öâö6Æ÷6R‚’·²ÖVçRç&VÖ÷fR‚“²×Ð¢ÖVçRçVW'•6VÆV7F÷$ÆÂ‚u¶FFÖgvEÒr’æf÷$V6‚†gVæ7F–öâ†"’·°¢"æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢f"FòÒ"ævWDGG&–'WFR‚vFFÖgvBr“°¢f"v†òÒ‡v–æF÷ræ÷47W'&VçEW6W"òv–æF÷ræ÷47W'&VçEW6W"‡G'VR’¢vWD6öÆÆ$æÖR‚’’ÇÂrs²–b‚v†ò’&WGW&ã°¢f"æVÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vWfVçBÖ6†B×æVÂr“²–b‚æVÂÇÂæVÂæFF6WBæ6öÂ’&WGW&ã°¢f"&÷rÒ·²WF†÷#¢v†òÂ&öG“¢uÅÇS#r²Fò²rÅÇS#Br²7G&–ær†Òæ&öG’ÇÂrr’×Ó°¢&÷u·æVÂæFF6WBæ6öÅÒÒæVÂæFF6WBæ¶W—fÃ°¢ö6Æ÷6R‚“°¢6"æg&öÒ‚vWfVçEö6†Br’æ–ç6W'B‡&÷r’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"’·²7FGW2‚tf÷'v&Bf–ÆVC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“²&WGW&ã²×Ð¢fÆ6„ö²‚tf÷'v&FVBFòr²Fò“²÷&VÆöD÷Vä6†B‚“²ÆöD6†D6÷VçG2‚“°¢×Ò“°¢×Ò“°¢×Ò“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâö2†Wb’·²–b‚ÖVçRæ6öçF–ç2†WbçF&vWB’’·²ö6Æ÷6R‚“²Fö7VÖVçBç&VÖ÷fTWfVçDÆ—7FVæW"‚v6Æ–6²rÂö2“²×Ò×Ò“²×ÒÂ“°¢×Ð¢òò(ºò$Ö÷&R"÷fW&fÆ÷r(i"6ÖÆÂÖVçRv†÷6RÖ–â—FVÒ—2FVÆWFRÂ6òF†RFVÆWFP¢òò—26ÆV&Ç’f—6–&ÆR–ç7FVBöb†–FFVââ—4ÖöBÒFVÆWF–ær6öÖVöæRVÇ6Rw0¢òòÖW76vR‡7W÷'BÖöFW&F–öâ’à¢gVæ7F–öâö6†DÖ÷&R†ÒÂ'FâÂ—4ÖöB’·°¢f"÷VâÒFö7VÖVçBçVW'•6VÆV7F÷"‚ræ6†BÖÖ÷&RÖÖVçRr“°¢–b†÷Vâ’·²÷Vâç&VÖ÷fR‚“²&WGW&ã²×Ð¢f"ÖVçRÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“²ÖVçRæ6Æ74æÖRÒv6†BÖÖ÷&RÖÖVçRs°¢ÖVçRæ–ææW$…DÔÂÒsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6†BÖÖ÷&RÖ—FVÒ6†BÖÖ÷&RÖFVÂ"FFÖÖFVÃÒ##åÅÇS#sRFVÆWFRÖW76vRr°¢†—4ÖöBòrÇ7â6Æ73Ò&6†BÖÖ÷&R×Fr#â†ÖöFW&FR“Â÷7ãâr¢rr’²sÂö'WGFöãâs°¢÷÷6—F–öä6†DÖVçR†ÖVçRÂ'Fâ“°¢gVæ7F–öâö6Æ÷6R‚’·²ÖVçRç&VÖ÷fR‚“²×Ð¢ÖVçRçVW'•6VÆV7F÷"‚u¶FFÖÖFVÅÒr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢ö6Æ÷6R‚“°¢–b‚v–æF÷ræ6öæf—&Ò‚tFVÆWFRF†—2ÖW76vSòF†—26ææ÷B&RVæFöæRâr’’&WGW&ã°¢6"æg&öÒ‚vWfVçEö6†Br’æFVÆWFR‚’æW‚v–BrÂÒæ–B’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"’·²7FGW2‚tFVÆWFRf–ÆVC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“²&WGW&ã²×Ð¢fÆ6„ö²‚tÖW76vRFVÆWFVBr“²÷&VÆöD÷Vä6†B‚“²ÆöD6†D6÷VçG2‚“°¢×Ò“°¢×Ò“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·²Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâö2†Wb’·²–b‚ÖVçRæ6öçF–ç2†WbçF&vWB’’·²ö6Æ÷6R‚“²Fö7VÖVçBç&VÖ÷fTWfVçDÆ—7FVæW"‚v6Æ–6²rÂö2“²×Ò×Ò“²×ÒÂ“°¢×Ð¢òò$FBFòæ÷FW2"(	BVæBF†RÖW76vRFòF†RWfVçBw2æ÷FW2†g&W6‚×&VBF†P¢òò7W'&VçBfÇVR6òvRæWfW"6Æö&&W"6öæ7W'&VçBVF—B’Âf–÷5w&—FRà¢gVæ7F–öâö6†EFôæ÷FW2†Ò’·°¢f"æVÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vWfVçBÖ6†B×æVÂr“°¢–b‚æVÂÇÂæVÂæFF6WBæ6öÂ’&WGW&ã°¢f"6öÂÒæVÂæFF6WBæ6öÂÂ¶W’ÒæVÂæFF6WBæ¶W—fÃ°¢f"F&ÆRÒ6öÂÓÓÒvÖçVÅö–BròvÖçVÅöWfVçG2r¢vWfVçE÷7FFRs°¢f"–F6öÂÒ6öÂÓÓÒvÖçVÅö–Bròv–Br¢vWfVçEöçVÒs°¢f"Æ–æRÒ†ÒæWF†÷"ò7G&–ær†ÒæWF†÷"’²s¢r¢rr’²7G&–ær†Òæ&öG’ÇÂrr“°¢6"æg&öÒ‡F&ÆR’ç6VÆV7B‚væ÷FW2r’æW†–F6öÂÂ¶W’’æÖ–&U6–ævÆR‚’çF†Vâ†gVæ7F–öâ‡&W7’·°¢f"7W"Ò‡&W7bb&W7æFFbb&W7æFFææ÷FW2’ò7G&–ær‡&W7æFFææ÷FW2’¢rs°¢f"æW‡BÒ7W"ò†7W"ç&WÆ6R‚õÅÇ2²BòÂrr’²uÅÆâr²Æ–æR’¢Æ–æS°¢–b‡v–æF÷ræ÷5w&—FR’v–æF÷ræ÷5w&—FR‡F&ÆRÂ¶W’Â·²æ÷FW3¢æW‡B×Ò“²òòfÆ6†W2%6fVB"²&R×&VæFW'0¢×Ò“°¢×Ð¢òò†–v†Æ–v‡BÇFVÖÖFSâÖVçF–öç2–â6†B&öG’â'Vç2öâÅ$TE’ÖW66V@¢òòFW‡B†æÖW2&RÇ†çVÖW&–2Â6ò–æ¦V7F–ærÇ7ãâ—26fR’âÖVçF–öà¢òò&V6†W2F†RW'6öâf–÷v†G4æWt—FV×2Âv†–6‚fÆw2$ÇF†V—"æÖSâ"6öÖÖVçG0¢òò2%–÷RvW&RÖVçF–öæVB"–âF†V—"$–âF†RÆ7BvVV²"à¢gVæ7F–öâöÖVçF–öä‡FÖÂ†W66VB’·°¢f"Òv–æF÷rä%õU%4ôä2ÇÂ··×Ó°¢&WGW&â7G&–ær†W66VB’ç&WÆ6R‚ô…¶×¥Õ¶×£Ó•×·³Ã#×Ò’öv’ÂgVæ7F–öâ†gVÆÂÂæÖR’·°¢f"Æ2ÒæÖRçFôÆ÷vW$66R‚“°¢&WGW&â…¶Æ5ÒÇÂÆ2ÓÓÒvævVÆrÇÂÆ2ÓÓÒv‡W&ÆW’r’òsÇ7â6Æ73Ò&6†BÖÖVçF–öâ#är²æÖR²sÂ÷7ãâr¢gVÆÃ°¢×Ò“°¢×Ð¢gVæ7F–öâ÷–çD6†DÆ—7B†Æ—7BÂ×6w2’·°¢òòG&÷ç’÷'FÆVBf÷'v&Bþ(ºòÖVçR&Vf÷&RvR&W–çB(	B&VÇF–ÖRW6‚÷ ¢òòg&W6‚6VæBv÷VÆB÷F†W'v—6RÆVfRöæRfÆöF–ærÂFWF6†VBg&öÒ—G2†æ÷p¢òò&R×&VæFW&VB’ÖW76vRà¢Fö7VÖVçBçVW'•6VÆV7F÷$ÆÂ‚ræ6†BÖgvBÖÖVçRÂæ6†BÖÖ÷&RÖÖVçRr’æf÷$V6‚†gVæ7F–öâ‡‚’·²‚ç&VÖ÷fR‚“²×Ò“°¢Æ—7Bæ–ææW$…DÔÂÒrs°¢òò$6¶VB’"&÷w2&RæWfW"6öçfW'6F–öâÂ6òF†W’æWfW"&VæFW"–âF†P¢òòF‡&VBÇS#Bf÷"ç–öæRâF†W’&V6‚ævVÆ2'Væ6†VB&÷r–â$–âF†P¢òòÆ7BvVV²"–ç7FVB„‡W&ÆW’##bÓrÓ3’à¢×6w2Ò×6w2æf–ÇFW"†gVæ7F–öâ†Ò’·²&WGW&âv–æF÷ræ$—46µ&÷r†Òæ&öG’“²×Ò“°¢òòâV×G’F‡&VB6†÷w2æ÷F†–ærBÆÂ„‡W&ÆW’##bÓrÓ#’’(	BF†R6ö×÷6W ¢òò&VÆ÷r—B—2Ç&VG’F†R–çf—FF–öâFò7F'BöæRà¢–b‚×6w2æÆVæwF‚’&WGW&ã°¢f"ÖRÒ†vWD6öÆÆ$æÖR‚’ÇÂrr’çG&–Ò‚’çFôÆ÷vW$66R‚“°¢òò7W÷'B„ævVÆò‡W&ÆW’’6âÖöFW&FR(	BFVÆWFRå’ÖW76vRÂæ÷B§W7@¢òòF†V—"÷vã²WfW'–öæRVÇ6R6âFVÆWFRöæÇ’v†BF†W’w&÷FRà¢f"ö6äÖöFW&FRÒ—57W÷'EW'6öâ†vWD6öÆÆ$æÖR‚’ÇÂrr“°¢×6w2æf÷$V6‚†gVæ7F–öâ†Ò’·°¢f"v†VâÒrs°¢G'’·²v†VâÒæWrFFR†Òæ7&VFVEöB’çFôÆö6ÆU7G&–ær‚vVâÕU2rÂ·²ÖöçFƒ¢w6†÷'BrÂF“¢vçVÖW&–2rÂ†÷W#¢vçVÖW&–2rÂÖ–çWFS¢s"ÖF–v—Br×Ò“²×Ò6F6‚†R’··×Ð¢f"Ö–æRÒÖRbb7G&–ær†ÒæWF†÷"ÇÂrr’çG&–Ò‚’çFôÆ÷vW$66R‚’ÓÓÒÖS°¢f"6äFVÂÒÖ–æRÇÂö6äÖöFW&FS°¢f"F—bÒFö7VÖVçBæ7&VFTVÆVÖVçB‚vF—br“²F—bæ6Æ74æÖRÒv6†BÖ×6rs°¢F—bæFF6WBæ×6t–BÒÒæ–C°¢òò6Æ6²×7G–ÆR†÷fW"FööÆ&#¢VÖö¦’&V7F–öç2	ùÒ	ùâf—'7BÂF†VâÖ÷&R’+p¢òòFB×FòÖæ÷FW2+r(ºò÷fW&fÆ÷rF†B÷Vç2ÖVçRv—F‚$FVÆWFRÖW76vR ¢òò†÷vâÖW76vRÂ÷"ç’f÷"7W÷'B’âFòÆö÷FVÖÖFR–âÂÖVçF–öâF†VÐ¢òò–âF†RÖW76vR†Rærâ$fW&Ö"’(	B—B7W&f6W2–âF†V—"$–âF†RÆ7BvVV²"à¢f"&V7D'Fç2Ò4„EôTÔô¤•2æÖ†gVæ7F–öâ†VÒ’·°¢&WGW&âsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6†BÖ7B6†B×&V7BÖ'Fâ"FF×&V7CÒ"r²VÒ²r"F—FÆSÒ%&V7Br²VÒ²r"&–ÖÆ&VÃÒ%&V7B#âr²VÒ²sÂö'WGFöãâs°¢×Ò’æ¦ö–â‚rr“°¢f"7F–öç2ÒsÆF—b6Æ73Ò&6†BÖ7F–öç2#âr°¢&V7D'Fç2°¢sÇ7â6Æ73Ò&6†BÖ7B×6W"&–Ö†–FFVãÒ'G'VR#ãÂ÷7ãâr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6†BÖ7B"FFÖ7CÒ&æ÷FR"F—FÆSÒ$FBFòWfVçBæ÷FW2"&–ÖÆ&VÃÒ$FBFòæ÷FW2#åÅÇVCƒ6EÅÇVF6FCÂö'WGFöãâr°¢†6äFVÀ¢òsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò&6†BÖ7B6†BÖÖ÷&R"FFÖ7CÒ&Ö÷&R"FFÖ6æÖöCÒ"r²†Ö–æRòsr¢sr’²r"F—FÆSÒ$Ö÷&R7F–öç2"&–ÖÆ&VÃÒ$Ö÷&R#åÅÇS#&VcÂö'WGFöãâp¢¢rr’°¢sÂöF—câs°¢F—bæ–ææW$…DÔÂÒ7F–öç2°¢sÆF—b6Æ73Ò&6†BÖÖWF#ãÇ7â6Æ73Ò&6†B×v†ò#âr²W66T‡FÖÂ…7G&–ær†ÒæWF†÷"ÇÂrr’’°¢sÂ÷7ãâÇ7â6Æ73Ò&6†B×v†Vâ#âr²W66T‡FÖÂ‡v†Vâ’²sÂ÷7ããÂöF—câr°¢sÇ6Æ73Ò&6†BÖ&öG’#âr²öÖVçF–öä‡FÖÂ†W66T‡FÖÂ…7G&–ær†Òæ&öG’ÇÂrr’’’²sÂ÷âr°¢ö6†E&V7DÆ–æR†Òç&V7F–öç2ÂÖR“°¢F—bçVW'•6VÆV7F÷$ÆÂ‚ræ6†BÖ7Br’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢f"&V7BÒ'FâævWDGG&–'WFR‚vFF×&V7Br“°¢–b‡&V7B’&WGW&âö6†E&V7B†ÒÂ&V7B“°¢f"7BÒ'FâævWDGG&–'WFR‚vFFÖ7Br“°¢–b†7BÓÓÒvæ÷FRr’&WGW&âö6†EFôæ÷FW2†Ò“°¢–b†7BÓÓÒvÖ÷&Rr’&WGW&âö6†DÖ÷&R†ÒÂ'FâÂ'FâævWDGG&–'WFR‚vFFÖ6æÖöBr’ÓÓÒsr“°¢×Ò“°¢×Ò“°¢Æ—7BæVæD6†–ÆB†F—b“°¢×Ò“°¢Æ—7Bç67&öÆÅF÷ÒÆ—7Bç67&öÆÄ†V–v‡C°¢×Ð¢gVæ7F–öâ÷&VÆöD÷Vä6†B‚’·°¢f"æVÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vWfVçBÖ6†B×æVÂr“°¢–b‚æVÂÇÂæVÂæFF6WBæ6öÂ’&WGW&ã°¢f"Æ—7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6†BÖÆ—7Br“²–b‚Æ—7B’&WGW&ã°¢6"æg&öÒ‚vWfVçEö6†Br’ç6VÆV7B‚r¢r’æW‡æVÂæFF6WBæ6öÂÂæVÂæFF6WBæ¶W—fÂ¢æ÷&FW"‚v7&VFVEöBrÂ·²66VæF–æs¢G'VR×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‚&W7æW'&÷"’÷–çD6†DÆ—7B†Æ—7BÂ&W7æFFÇÂµÒ“°¢×Ò“°¢×Ð¢v–æF÷ræ÷5&VæFW$6†BÒgVæ7F–öâ‡&V2’·°¢f"æVÂÒFö7VÖVçBævWDVÆVÖVçD'”–B‚vWfVçBÖ6†B×æVÂr“°¢–b‚æVÂ’&WGW&ã°¢–b‚&V2ÇÂ&V2åö¶W’ÓÒçVÆÂ’·²æVÂæ–ææW$…DÔÂÒrs²&WGW&ã²×Ð¢f"6öÂÒ&V2å÷F&ÆRÓÓÒvÖçVÅöWfVçG2ròvÖçVÅö–Br¢vWfVçEöçVÒs°¢æVÂæFF6WBæ6öÂÒ6öÃ²æVÂæFF6WBæ¶W—fÂÒ7G&–ær‡&V2åö¶W’“°¢æVÂæFF6WBæ6†F¶W’Ò†6öÂÓÓÒvÖçVÅö–BròvÒr¢v2r’²&V2åö¶W“°¢æVÂæ–ææW$…DÔÂÐ¢sÆƒB6Æ73Ò&6†BÖ‚#ä6†Bv—F‚F†RFVÓÂöƒCâr°¢sÆF—b6Æ73Ò&6†BÖÆ—7B"–CÒ&6†BÖÆ—7B#ãÇ6Æ73Ò&6†BÖV×G’#äÆöF–æ~(
cÂ÷ãÂöF—câr°¢sÆf÷&Ò6Æ73Ò&6†BÖf÷&Ò"–CÒ&6†BÖf÷&Ò#âr°¢sÆ–çWB6Æ73Ò&6†BÖ–çWB"–CÒ&6†BÖ–çWB"Æ6V†öÆFW#Ò$ÖW76vRF†RFVÒ&÷WBF†—2WfVçN(
b"WFö6ö×ÆWFSÒ&öfb"Ö†ÆVæwFƒÒ##âr°¢sÆ'WGFöâG—SÒ'7V&Ö—B"6Æ73Ò&6†B×6VæB#å6VæCÂö'WGFöãâr°¢sÂöf÷&Óâr°¢rs°¢6"æg&öÒ‚vWfVçEö6†Br’ç6VÆV7B‚r¢r’æW†6öÂÂ&V2åö¶W’’æ÷&FW"‚v7&VFVEöBrÂ·²66VæF–æs¢G'VR×Ò’çF†Vâ†gVæ7F–öâ‡&W7’·°¢f"Æ—7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6†BÖÆ—7Br“²–b‚Æ—7B’&WGW&ã°¢òò–bF†RWfVçEö6†BF&ÆR†6âwB&VVâÖ–w&FVB–WBÂ6†÷rF†Ræ÷&ÖÀ¢òòV×G’7FFR–ç7FVBöb6WGWv&æ–ær†6VæBv–ÆÂ7W&f6RF†RW'&÷"’à¢–b‡&W7æW'&÷"’·²÷–çD6†DÆ—7B†Æ—7BÂµÒ“²&WGW&ã²×Ð¢÷–çD6†DÆ—7B†Æ—7BÂ&W7æFFÇÂµÒ“°¢òò&VF–ærF†RF‡&VBFöW2äõB6ÆV"—G2$–âF†RÆ7BvVV²"&÷rç’Ö÷&P¢òò„‡W&ÆW’##bÓrÓ#’’(	BF†B&÷r6öÖW2F÷vâöæÇ’v†Vâ—Bw26†V6¶VBöfbÀ¢òò6ò÷Væ–ærâWfVçBFòÆöö²B—B6âwBV–WFÇ’V×G’–÷W"fVVBà¢×Ò“°¢òò)H)HÖ–æ’W"ÖWfVçB76—7FçB)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢f"f÷&ÒÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6†BÖf÷&Òr“°¢–b†f÷&Ò’f÷&ÒæFDWfVçDÆ—7FVæW"‚w7V&Ö—BrÂgVæ7F–öâ†R’·°¢Rç&WfVçDFVfVÇB‚“°¢f"–çÒFö7VÖVçBævWDVÆVÖVçD'”–B‚v6†BÖ–çWBr“°¢f"&öG’Ò†–ççfÇVRÇÂrr’çG&–Ò‚“²–b‚&öG’’&WGW&ã°¢f"v†òÒ‡v–æF÷ræ÷47W'&VçEW6W"òv–æF÷ræ÷47W'&VçEW6W"‡G'VR’¢rr’ÇÂrs²–b‚v†ò’&WGW&ã°¢f"&÷rÒ·²WF†÷#¢v†òÂ&öG“¢&öG’×Ó²&÷u¶6öÅÒÒ&V2åö¶W“²–ççfÇVRÒrs°¢6"æg&öÒ‚vWfVçEö6†Br’æ–ç6W'B‡&÷r’çF†Vâ†gVæ7F–öâ‡&W7’·°¢–b‡&W7æW'&÷"’·²7FGW2‚tÖW76vRæ÷B6VçC¢r²&W7æW'&÷"æÖW76vRÂvW'&÷"r“²–ççfÇVRÒ&öG“²&WGW&ã²×Ð¢÷&VÆöD÷Vä6†B‚“²ÆöD6†D6÷VçG2‚“°¢×Ò“°¢×Ò“°¢×Ó°¢v–æF÷ræ÷4÷VäVF—F÷"ÒgVæ7F–öâ‡F&ÆRÂ¶W’’·°¢òòVF—F–æræ÷rÆ—fW2–âF†RFWF–Ç2÷×WÂæ÷Bâ–æÆ–æR6&BVF—F÷"à¢–b‡G—Vöb7W'&VçEf–WrÓÒwVæFVf–æVBrbb7W'&VçEf–WrÓÒvw&–Br’6WEf–Wr‚vw&–Br“°¢6WEF–ÖV÷WB†gVæ7F–öâ‚’·°¢f"6VÂÒF&ÆRÓÓÒvÖçVÅöWfVçG2p¢òræ÷2Ö6&E¶FFÖÖçVÂÖ–CÒ"r²¶W’²r%Òp¢¢ræ÷2Ö6&E¶FFÖWfVçBÖçVÓÒ"r²¶W’²r%Òs°¢f"6&BÒF÷4w&–BçVW'•6VÆV7F÷"‡6VÂ“°¢–b†6&B’6&Bç67&öÆÄ–çFõf–Wr‡·²&V†f–÷#¢w6Öö÷F‚rÂ&Æö6³¢v6VçFW"r×Ò“°¢–b†6&Bbb6&BåöÖöFÅ&V2bbv–æF÷ræ÷VäWfVçDÖöFÂ’v–æF÷ræ÷VäWfVçDÖöFÂ†6&BåöÖöFÅ&V2“°¢×ÒÂs“°¢×Ó° ¢òò&÷WFR‚’(	BæòWF‚âÇv—26†÷rF†R6öÆÆ&÷&F—fRG&6¶W"à¢gVæ7F–öâ&÷WFR‚’·°¢f"v†òÒvWD6öÆÆ$æÖR‚’ÇÂuFVÒs°¢6†÷töæÇ’‚F÷2“°¢v—&Uf–WuFövvÆR‚“°¢v—&Tf–ÇFW'2‚“°¢'V–ÆE7FvTf–ÇFW'2‚“°¢'V–ÆE&Vv–öäf–ÇFW'2‚“°¢'V–ÆE7FGW4f–ÇFW'2‚“°¢'V–ÆDW‡G&f–ÇFW'2‚“°¢v—&Tf–ÇFW$G&÷F÷vç2‚“°¢v—&Tf–ÇFW%FövvÆR‚“°¢Ç”f–ÇFW%f—6–&–Æ—G’‚“²òò†–FRF†R$f–ÇFW'2"æVÂVæÆW72ævVÆ—26–væVB–à¢&VæFW$÷2‡v†ò“°¢v—&TFDWfVçB‡v†ò“°¢6WGW&VÇF–ÖR‡v†ò“°¢òò6²f÷"æÖRöâf—'7BVF—BÖ–çFVçB–bvR7F–ÆÂFöâwB†fRöæRà¢–b‚vWD6öÆÆ$æÖR‚’’·°¢G'’·°¢F÷4w&–BæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâöæ6T6²‚’·°¢Vç7W&T6öÆÆ$æÖR‚“°¢F÷4w&–Bç&VÖ÷fTWfVçDÆ—7FVæW"‚v6Æ–6²rÂöæ6T6²“°¢×ÒÂ·²öæ6S¢G'VR×Ò“°¢×Ò6F6‚†R’··×Ð¢×Ð¢×Ð ¢òò%v†òÒ’"(	B–÷W"'V&&ÆR²G&÷F÷vâöbWfW'–öæRVÇ6Rw2'V&&ÆW2Fð¢òò7v—F6‚ÂÇ†&WF–6Â'’æÖRâ$÷F†W.(
b"÷Vç2F†Rg&VR×FW‡B&ö×Bf÷ ¢òòç–öæRæ÷BöâF†—2&÷7FW"‡Væ6†ævVB&V†f–÷"g&öÒF†RöÆB6†ævRW6W'2’à¢f"t„õõ$õ5DU"Ò°¢·²æÖS¢tævVÆrÂ–æ—C¢tr×ÒÀ¢·²æÖS¢t6&Æ÷2rÂ–æ—C¢t2r×ÒÀ¢·²æÖS¢t‡W&ÆW’rÂ–æ—C¢t‚r×ÒÀ¢·²æÖS¢t¦W&öÖRrÂ–æ—C¢t¥rr×ÒÀ¢·²æÖS¢t¦–ÒrÂ–æ—C¢t¤2r×ÒÀ¢·²æÖS¢t¦öRrÂ–æ—C¢t¤Âr×ÒÀ¢·²æÖS¢u66÷GBrÂ–æ—C¢u2r×ÒÀ¢·²æÖS¢uF†÷"rÂ–æ—C¢uBr×ÒÀ¢·²æÖS¢ufW&ÖrÂ–æ—C¢ubr×Ð¢Ó°¢òòD„R–æ—F–Ç2'VÆRf÷"F†Rv†öÆR¢öæRÆWGFW"v†VâF†Bf—'7B–æ—F–Â—0¢òòVæ—VRöâF†R&÷7FW"Âf—'7B²7W&æÖR–æ—F–ÂöæÇ’v†Vâ—B6öÆÆ–FW2à¢òò†æBÖ¶WB–ât„õõ$õ5DU"&÷fR&F†W"F†âFW&—fVBg&öÒW'6öæ2æ§6öâÀ¢òòv†–6‚†2æò7W&æÖRf÷"¦–Ò(	BF†W&R—2æ÷F†–ærFòFW&—fR$¤2"g&öÒà¢òòW‡÷6VB6òF†R6&Bw27FGW2Ö&·2W6RF†R4ÔRç7vW"2F†—2fF ¢òò‡6VRöÖ&´–æ—F–Ç2“²F†W’F—6w&VVBf÷"v†–ÆRæB—BÆöö¶VBÆ–¶R'Vrà¢òòF¶W2F†Rf—'7Bv÷&BÂ6ò$¦W&öÖRv÷WFW'2"æB&¦W&öÖR"&÷F‚ÆæBöâ¥rà¢gVæ7F–öâ÷v†ô–æ—Df÷"†æÖR’·°¢f"âÒ7G&–ær†æÖRÇÂrr’çG&–Ò‚’çFôÆ÷vW$66R‚’ç7Æ—B‚õÇ2²ò•³Ó°¢f"†—BÒt„õõ$õ5DU"æf–ÇFW"†gVæ7F–öâ‡’·²&WGW&âææÖRçFôÆ÷vW$66R‚’ÓÓÒã²×Ò•³Ó°¢&WGW&â†—Bò†—Bæ–æ—B¢†âòâæ6†$Bƒ’çFõWW$66R‚’¢sòr“°¢×Ð¢v–æF÷ræ$–æ—Df÷"Ò÷v†ô–æ—Df÷#°¢òòv†òÖ’÷VâF†R&öf–ÆRvS¢UdU%”ôäRâ—Bv2'&–VfÇ’ævVÆÖöæÇ’v†Và¢òò'F¶R÷WBF†R&öf–ÆW2"v2&VB26÷fW&–ærF†—2vRFöó²‡W&ÆW’WB—@¢òò&6²(	B$’FòvçBF†R&öf–ÆRFWF–Ç2†§W7BFòWÆöBÆÂöbF†B7GVfb–à¢òòöæRÆ6R’"â—B—2Æ6RFò¶VW–÷W"&–òÂF÷–72Â7BFÆ·2æ@¢òòÖFW&–Ç2Âæ÷B6W&FRd”UröbF†RG&6¶W"Â6ò—BæWfW"6öæfÆ–7FVBv—F€¢òòF†RÖW&vRâ¶WB2æÖVBgVæ7F–öâ6òF†RÖVçRVçG'’æBF†Rf–WrwV&@¢òò6âwBG&–gB'Bà¢gVæ7F–öâ÷&öf–ÆTÖVçTö²‚’·²&WGW&âG'VS²×Ð¢gVæ7F–öâö6Æ÷6Uv†ôG&÷F÷vâ‚’·°¢f"FBÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wv†òÖG&÷F÷vâr“°¢f"'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wv†òÖ7W'&VçBÖ'Fâr“°¢–b†FB’FBç6WDGG&–'WFR‚v†–FFVârÂrr“°¢–b†'Fâ’'Fâç6WDGG&–'WFR‚v&–ÖW‡æFVBrÂvfÇ6Rr“°¢×Ð¢gVæ7F–öâ÷&VæFW%v†õ7v—F6†W"‚’·°¢f"†÷7BÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wv†ò×7v—F6†W"r“°¢–b‚†÷7B’&WGW&ã°¢f"7W"ÒvWD6öÆÆ$æÖR‚“°¢†÷7Bæ–ææW$…DÔÂÐ¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'v†òÖ–æ—Bv†òÖ7W'&VçB"–CÒ'v†òÖ7W'&VçBÖ'Fâ"&–Ö†7÷WÒ'G'VR"&–ÖW‡æFVCÒ&fÇ6R"r°¢r7G–ÆSÒ&&6¶w&÷VæC¢r²v–æF÷ræ%W'6öä6öÆ÷"†7W"’²r"F—FÆSÒ"r°¢†7W"òW66T‡FÖÂ†7W"’²r(	B&öf–ÆRb7v—F6‚r¢u6WBv†ò–÷R&Rr’²r#âr²W66T‡FÖÂ…÷v†ô–æ—Df÷"†7W"’’²sÂö'WGFöãâr°¢sÆF—b6Æ73Ò'v†òÖG&÷F÷vâ"–CÒ'v†òÖG&÷F÷vâ"†–FFVãâr°¢òò$ôd”ÄU2$RätTÄu2äõr„‡W&ÆW’##bÓ‚ÓS¢&—B7F–ÆÂ6†÷w2W ¢òòF†BF†W&R&R6W&FRW'6öæ2÷&öf–ÆW2Âv†–6‚6†÷VÆFâwB&RF†P¢òò66R(	B—B6†÷VÆB&RÖW&vVB&W6–FW2ævVÆ"’âW"×W'6öâ&öf–ÆP¢òòvR—2F†RÆ7BF†–ær–âF†RF†B6—2F†RFVÒ—26WBö`¢òò6W&FR–FVçF—F–W2&F†W"F†âöæR6†&VBG&6¶W"âævVÆ¶VW2—@¢òò2%FVÒ&öf–ÆW2"&V6W6R6†Rw&—FW2F†R7V¶W"&–÷2æB&öö·0¢òòdõ"WfW'–öæR(	B6ÖRW†6WF–öâ2VWVRÂÆææW"æBÆâ†VBà¢òòF†R7v—F6†W"&VÆ÷r5D•2f÷"WfW'–öæS¢—B—6âwB&öf–ÆRÂ—Bw2†÷p¢òò–÷R6’v†ò–÷R&RÂæBv—F†÷WB—B7F"÷"â&6†—fR6âwB&P¢òòGG&–'WFVBFòç–&öG’à¢…÷&öf–ÆTÖVçTö²‚¢òsÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'v†òÖÖVçRÖ—FVÒ"–CÒ'v†òÖ×—&öf–ÆRÖ'Fâ#âr°¢sÇ7frf–Wt&÷ƒÒ##B#B"f–ÆÃÒ&æöæR"7G&ö¶SÒ&7W'&VçD6öÆ÷""7G&ö¶R×v–GFƒÒ#""7G&ö¶RÖÆ–æV6Ò'&÷VæB"7G&ö¶RÖÆ–æV¦ö–ãÒ'&÷VæB"&–Ö†–FFVãÒ'G'VR#ãÆ6—&6ÆR7ƒÒ#""7“Ò#‚"#Ò#B"óãÇF‚CÒ$ÓB#‚‚b"óãÂ÷7fsâr°¢†—57W÷'EW'6öâ†7W"’òuFVÒ&öf–ÆW2r¢t×’&öf–ÆRr’²sÂö'WGFöãâp¢¢rr’°¢òòF†R%7v—F6‚Fò"&÷7FW"öbF—672—2tôäR„‡W&ÆW’##bÓ‚ÓS¢$’§W7@¢òòFöâwBvçBF†R7v—F6‚Fò2‚6–æ6R—Bw2§W7BöæR"’â—BÖFR6Vç6P¢òòv†VâV6‚W'6öâ†BF†V—"÷vâf–WrFò§V×&WGvVVã²v—F‚öæRÖW&vV@¢òòf–Wr—BöæÇ’GfW'F—6VBW'6öæ2F†BæòÆöævW"W†—7Bâ%6öÖVöæP¢òòVÇ6^(
b"&VÆ÷r7F–ÆÂ6WG2v†ò–÷R&RÂv†–6‚—2ÆÂ–FVçF—G’—2f÷ ¢òòæ÷r(	BGG&–'WF–ær–÷W"7F'2Â–÷W"&6†—fRæB–÷W"ÖW76vW2à¢rr°¢sÆ'WGFöâG—SÒ&'WGFöâ"6Æ73Ò'v†òÖ÷F†W""–CÒ'v†òÖ÷F†W"Ö'Fâ#å6öÖVöæRVÇ6Rf†VÆÆ—³Âö'WGFöãâr°¢sÂöF—câs°¢f"7W$'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wv†òÖ7W'&VçBÖ'Fâr“°¢f"G&÷F÷vâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wv†òÖG&÷F÷vâr“°¢7W$'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢f"v–ÆÄ÷VâÒG&÷F÷vâæ†4GG&–'WFR‚v†–FFVâr“°¢ö6Æ÷6Uv†ôG&÷F÷vâ‚“°¢–b‡v–ÆÄ÷Vâ’·²G&÷F÷vâç&VÖ÷fTGG&–'WFR‚v†–FFVâr“²7W$'Fâç6WDGG&–'WFR‚v&–ÖW‡æFVBrÂwG'VRr“²×Ð¢×Ò“°¢f"ö×'FâÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wv†òÖ×—&öf–ÆRÖ'Fâr“°¢–b…ö×'Fâ’ö×'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢ö6Æ÷6Uv†ôG&÷F÷vâ‚“°¢Vç7W&T6öÆÆ$æÖR‚“²òòFVfVÇG2FòF†÷#²æWfW"&ö×G0¢6WEf–Wr‚v×—&öf–ÆRr“°¢÷&VæFW%v†õ7v—F6†W"‚“°¢×Ò“°¢G&÷F÷vâçVW'•6VÆV7F÷$ÆÂ‚rçv†òÖ–æ—E¶FF×6WFæÖUÒr’æf÷$V6‚†gVæ7F–öâ†'Fâ’·°¢'FâæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢6WD6öÆÆ$æÖR†'FâævWDGG&–'WFR‚vFF×6WFæÖRr’“°¢÷&VæFW%v†õ7v—F6†W"‚“°¢×Ò“°¢×Ò“°¢Fö7VÖVçBævWDVÆVÖVçD'”–B‚wv†òÖ÷F†W"Ö'Fâr’æFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢Rç7F÷&÷vF–öâ‚“°¢ö6Æ÷6Uv†ôG&÷F÷vâ‚“°¢f"âÒ‡v–æF÷rç&ö×B‚u–÷W"æÖS¢rÂ7W"’ÇÂrr’çG&–Ò‚“°¢–b†â’·²6WD6öÆÆ$æÖR†â“²÷&VæFW%v†õ7v—F6†W"‚“²×Ð¢×Ò“°¢×Ð¢Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚v6Æ–6²rÂgVæ7F–öâ†R’·°¢f"7v—F6†W"ÒFö7VÖVçBævWDVÆVÖVçD'”–B‚wv†ò×7v—F6†W"r“°¢–b‡7v—F6†W"bb7v—F6†W"æ6öçF–ç2†RçF&vWB’’ö6Æ÷6Uv†ôG&÷F÷vâ‚“°¢×Ò“°¢òò6WGFÆRF†R–FVçF—G’$Tdõ$RF†Rf—'7B&VæFW#¢Vç7W&T6öÆÆ$æÖR‚’öæÇ¢òòf—&W2öâF†Rf—'7Bw&—FRÂæBVçF–ÂF†VâF†RfF"ÂF†R7F—f—G’fVV@¢òòæBç—F†–ærVF—FVBv÷VÆB6''’v†FWfW"F†R'&÷w6W"Æ7B†VÆB(	B÷ ¢òòæ÷F†–ærBÆÂ„‡W&ÆW’##bÓ‚ÓR’à¢Vç7W&T6öÆÆ$æÖR‚“°¢÷&VæFW%v†õ7v—F6†W"‚“° ¢òò÷Vâ–ÖÖVF–FVÇ’(	Bæò6W76–öâv—BÂæòÖv–2Æ–æ²à¢&÷WFR‚“°¢×Ò“°§×Ò’‚“°£Â÷67&—Cà£Âö&öG“à£Âö‡FÖÃà¢rrp ¢2V&Æ–26FÆör6V7F–öç2‡FöF’÷W6öÖ–ærö&6†—fR’vW&R&WF—&VBv—F‚F†P¢2V&Æ–2f–Wr(	BF†RWfVçBG&6¶W"—2æ÷rF†R6öÆRÂgVÆÇ’6Æ–VçB×&VæFW&VBf–Wrà¢‡FÖÂÒ†VB²fö÷@¢‡FÖÂÒ‡FÖÂç&WÆ6R‚sÂ÷7G–ÆSârÂ„„U$Ròw7&2ö7F–öâÖ6VçFW"æ772r’ç&VE÷FW‡B‚’²uÆãÂ÷7G–ÆSârÂ¢&öö¶–æu÷67&—G2ÒsÇ67&—CåÆâr²„„U$Ròw7&2ö&öö¶–ærÖ6÷&Ræ§2r’ç&VE÷FW‡B‚’²uÆâr²„„U$Ròw7&2öÆ–6F–öâ×v÷&¶fÆ÷ræ§2r’ç&VE÷FW‡B‚’²uÆâr²„„U$Ròw7&2ö7F–öâÖ6VçFW"æ§2r’ç&VE÷FW‡B‚’²uÆãÂ÷67&—CåÆâp¢‡FÖÂÒ‡FÖÂç&WÆ6R‚sÇ67&—BG—SÒ&Æ–6F–öâö§6öâ"–CÒ&6FÆörÖFF#ârÂ&öö¶–æu÷67&—G2²sÇ67&—BG—SÒ&Æ–6F–öâö§6öâ"–CÒ&6FÆörÖFF#ârÂ¢õUEõ4„•ç&VçBæÖ¶F—"‡&VçG3ÕG'VRÂW†—7Eöö³ÕG'VR¢õUEõ4„•çw&—FU÷FW‡B†‡FÖÂÂVæ6öF–æsÒwWFbÓ‚r¢&–çB†buu$õDR´õUEõ4„•Ò‡¶ÆVâ†‡FÖÂ“¢ÇÒ'—FW2’r¢&–çB†btWfVçG3¢FöF“×¶ÆVâ‡FöF•öWg2—Ò+rW6öÖ–æs×·W6öÖ–æuö6÷VçGÒ+r&6†—fVC×¶&6†—fVEö6÷VçGÒr ¢2)H)H&ö&÷B×&VF&ÆR6ö×æ–öâf–ÆRf÷"F†RGW7BvVçB)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H)H ¢2F†RvVçBfWF6†W2F†—2U$ÂBF†R7F'BöbWfW'’'VâFòFVGWRà¢266†VÖ—2–çFVçF–öæÆÇ’fÆB²6ÖÆÂ6ò—Bw26†VFò&VBà¢w&—FUöWfVçG5ö§6öâ‡FöF•öWg2ÂW6öÖ–ærÂ&6†—fVB ¢2)H)HV&Æ–6Ç’7V'67&–&&ÆR”6ÂfVVBöb6fVB²ÖçVÂWfVçG2)H)H)H)H)H)H)H)H)H ¢2fWF6†W27W'&VçB7W&6R7FFRf–$U5B†æöâV&Æ—6†&ÆR¶W’’âf–ÇW&P¢2Fò&V6‚7W&6R—2æöâÖfFÂ(	BF†RW†—7F–ær6ÆVæF"æ–72—2ÆVg@¢2ÆöæR6òæWGv÷&²&Æ—6âwB'&V²F†R'V–ÆBà¢w&—FUö6ÆVæF%ö–72‡FöF•öWg2ÂW6öÖ–ær  ¦FVbw&—FUöWfVçG5ö§6öâ‡FöF•öWg2ÂW6öÖ–ærÂ&6†—fVB“ ¢""$VÖ—BV&Æ–2öWfVçG2æ§6öâ(	BF†R6æöæ–6ÂÂ&ö&÷B×&VF&ÆRWfVçBÆ—7Bà¢&VB'’F†R&7F–4&ÇVTWfVçE7V¶–ærGW7BvVçBf÷"FVGWÆ–6F–öâà¢66†VÖ—27F&ÆS²Fòæ÷B'&V²—Bv—F†÷WB'V×–ær66†VÖ÷fW'6–öæâ"" ¢õUEô¥4ôâÒ„U$RòwV&Æ–2ròvWfVçG2æ§6öâp ¢$”4…ô´U•2Ò€¢v&÷WBrÂvfö7W5ö&V2rÂwG—–6ÅöGFVæFVW2rÂw7V¶–æu÷&÷WFRrÀ¢v6öçF7Eö–æfòrÂwö5öVÖ–ÂrÂvFVFÆ–æRrÂvGFVæFVUö6÷VçBrÀ¢w•÷Fõ÷Æ’rÂw&–6–ærrÂvVF–Væ6U÷G—RrÂw7E÷7V¶W'2rÀ¢vÖVWF–æuöf÷&ÖG2rÂvGFVæE÷fW&F–7BrÂw÷7FÖ÷'FVÒrÂw6VVBrÂwW&vVçBrÀ¢wfVçVRrÂv6—G’rÂv6÷VçG'’rÀ¢væ÷FW2rÂw7V¶W"rÂwv÷&¶fÆ÷u÷7FGW2rÂw6÷W&6RrÂvW‡FW&æÅö–BrÀ¢ ¢FVb6W&–Æ—¦R†WbÂ'V6¶WB“ ¢÷WBÒ°¢vçVÒs¢WbævWB‚vçVÒr’À¢væÖRs¢WbævWB‚væÖRrÂrr’À¢vFFU÷7G"s¢WbævWB‚vFFU÷7G"rÂrr’À¢w7F'EöFFRs¢WbævWB‚u÷7F'Br’æ—6öf÷&ÖB‚’–bWbævWB‚u÷7F'Br’VÇ6RæöæRÀ¢vVæEöFFRs¢WbævWB‚uöVæBr’æ—6öf÷&ÖB‚’–bWbævWB‚uöVæBr’VÇ6RæöæRÀ¢vÆö6F–öâs¢WbævWB‚vÆö6F–öârÂrr’À¢2w&çVÆ"&Vv–öâ†Rærâ$&’&V"’v†VâF†R6÷W&6R6'&–W2öæS°¢2÷F†W'v—6RfÆÂ&6²FòF†R6ö'6RÖW&–62ôWW&÷Rþ(
bÖ–ærà¢w&Vv–öâs¢WbævWB‚w&Vv–öâr’÷"&Vv–öåög&öÕöÆö6F–öâ†WbævWB‚vÆö6F–öârÂrr’’À¢w&Vv–öåö6ö'6Rs¢&Vv–öåög&öÕöÆö6F–öâ†WbævWB‚vÆö6F–öârÂrr’’À¢wG—Rs¢WbævWB‚wG—RrÂrr’À¢w&–÷&—G’s¢WbævWB‚w&–÷&—G’rÂrr’À¢w&–÷&—G•ögVÆÂs¢WbævWB‚w&–÷&—G•ögVÆÂrÂWbævWB‚w&–÷&—G’rÂrr’’À¢wv‡’s¢WbævWB‚wv‡’rÂrr’À¢wW&Âs¢UdTåEõU$Å2ævWB‡7G"†WbævWB‚vçVÒrÂrr’’’À¢w7FGW2s¢'V6¶WBÀ¢Ð¢f÷"²–â$”4…ô´U•3 ¢–bWbævWB†²’æ÷B–â„æöæRÂrr“ ¢÷WE¶µÒÒWbævWB†²¢&WGW&â÷W@ ¢–ÆöBÒ°¢w66†VÖ÷fW'6–öâs¢À¢2W"ÔD’7F×†æ÷BW"×6V6öæB“¢6ÖRÖF’&V'V–ÆG27F’'—FRÖ–FVçF–6ÂÀ¢26òF†RF–Ç’WFòÖ'V–ÆB6öÖÖ—BæWfW"6öæfÆ–7G2v—F‚ÖçVÂVF—Bà¢vvVæW&FVEöBs¢DôD’æ—6öf÷&ÖB‚’²uC££¢rÀ¢v'V–ÆEöFFRs¢DôD’æ—6öf÷&ÖB‚’À¢w6÷W&6Rs¢v&7F–6&ÇVRÖWfVçB×G&6¶W"rÀ¢v6æöæ–6Å÷W&Âs¢v‡GG3¢òö&7F–6&ÇVRÖWfVçB×G&6¶W"ÖFWÆ÷’çfW&6VÂæöWfVçG2æ§6öârÀ¢v6÷VçG2s¢°¢wFöF’s¢ÆVâ‡FöF•öWg2’À¢wW6öÖ–ærs¢ÆVâ‡W6öÖ–ær’À¢v&6†—fVBs¢ÆVâ†&6†—fVB’À¢wF÷FÂs¢ÆVâ‡FöF•öWg2’²ÆVâ‡W6öÖ–ær’²ÆVâ†&6†—fVB’À¢ÒÀ¢vWfVçG2s¢€¢·6W&–Æ—¦R†WbÂwFöF’r’f÷"Wb–âFöF•öWg5Ò°¢·6W&–Æ—¦R†WbÂwW6öÖ–ærr’f÷"Wb–âW6öÖ–æuÒ°¢·6W&–Æ—¦R†WbÂv&6†—fVBr’f÷"Wb–â&6†—fVEÐ¢’À¢Ð ¢õUEô¥4ôâçw&—FU÷FW‡B†§6öâæGV×2‡–ÆöBÂ–æFVçCÓ"’²uÆârÂVæ6öF–æsÒwWFbÓ‚r¢&–çB†buu$õDR´õUEô¥4ôçÒ‡´õUEô¥4ôâç7FB‚’ç7E÷6—¦S¢ÇÒ'—FW2Â¶ÆVâ‡–ÆöE²&WfVçG2%Ò—ÒWfVçG2’r  ¦FVbw&—FUö6ÆVæF%ö–72‡FöF•öWg2ÂW6öÖ–ær“ ¢""$VÖ—BV&Æ–2ö6ÆVæF"æ–72(	BV&Æ–6Ç’7V'67&–&&ÆR”6ÂfVVBö`¢WfW'’WfVçBF†Bw2&VVâÖ&¶VB6fVF–âWfVçE÷7FFRÅU2WfW'¢&÷r–âÖçVÅöWfVçG2à ¢FW6–væVB6òævVÆ†÷"ç–öæR’6â7FRF†RFWÆ÷–VBfVVBU$Â–çFð¢ÆR6ÆVæF"òvöövÆR6ÆVæF"ò÷WFÆöö²(i"7V'67&–&RFòU$Âæ@¢†fR—B7F’–â7–æ2v—F†÷WBç’W"×W6W"WF‚÷"ôWF‚Fæ6RâF†P¢fVVB—2&VvVæW&FVB'’F†RF–Ç’WFòÖ'V–ÆBv—D‡V"7F–öâà ¢æWGv÷&²6ÆÂ—2&W7BÖVff÷'C¢–b7W&6R—2Vç&V6†&ÆRF†RW†—7F–æp¢V&Æ–2ö6ÆVæF"æ–72†–bç’’—2ÆVgBÆöæRæBF†R'V–ÆB6öçF–çVW2à¢"" ¢–×÷'BW&ÆÆ–"ç&WVW7BÂW&ÆÆ–"æW'&÷ ¢õUEô”52Ò„U$RòwV&Æ–2ròv6ÆVæF"æ–72p ¢†VFW'2Ò°¢v–¶W’s¢5U$4UõT$Ä•4„$ÄUô´U’À¢tWF†÷&—¦F–öâs¢t&V&W"r²5U$4UõT$Ä•4„$ÄUô´U’À¢t66WBs¢vÆ–6F–öâö§6öârÀ¢Ð ¢FVbfWF6‚‡F‚“ ¢W&ÂÒ5U$4UõU$Âç'7G&—‚ròr’²r÷&W7B÷còr²F€¢&WÒW&ÆÆ–"ç&WVW7Bå&WVW7B‡W&ÂÂ†VFW'3Ö†VFW'2¢G'“ ¢v—F‚W&ÆÆ–"ç&WVW7BçW&Æ÷Vâ‡&WÂF–ÖV÷WCÓ’2# ¢&WGW&â§6öâæÆöG2‡"ç&VB‚’æFV6öFR‚wWFbÓ‚r’¢W†6WB‡W&ÆÆ–"æW'&÷"åU$ÄW'&÷"ÂW&ÆÆ–"æW'&÷"ä…EEW'&÷"ÂF–ÖV÷WDW'&÷"Âõ4W'&÷"’2S ¢&–çB†br”6Ã¢6¶—–ær(	B7W&6RfWF6‚f–ÆVBf÷"·F‡Ó¢¶WÒr¢&WGW&âæöæP ¢7FFU÷&÷w2ÒfWF6‚‚vWfVçE÷7FFS÷6VÆV7CÒ¢r¢ÖçVÅ÷&÷w2ÒfWF6‚‚vÖçVÅöWfVçG3÷6VÆV7CÒ¢f÷&FW#Ö7&VFVEöBæFW62r¢–b7FFU÷&÷w2—2æöæRæBÖçVÅ÷&÷w2—2æöæS ¢&WGW&â2ÆVfRF†R&Wf–÷W2f–ÆR–âÆ6P ¢7FFU÷&÷w2Ò7FFU÷&÷w2÷"µÐ¢ÖçVÅ÷&÷w2ÒÖçVÅ÷&÷w2÷"µÐ ¢7FFUö'•öçVÒÒ·%²vWfVçEöçVÒuÓ¢"f÷""–â7FFU÷&÷w2–b"ævWB‚vWfVçEöçVÒr’—2æ÷BæöæWÐ ¢FVb–75öW66R‡2“ ¢–b2—2æöæS ¢&WGW&ârp¢&WGW&â‡7G"‡2¢ç&WÆ6R‚uÅÂrÂuÅÅÅÂr¢ç&WÆ6R‚s²rÂuÅÃ²r¢ç&WÆ6R‚rÂrÂuÅÂÂr¢ç&WÆ6R‚uÆârÂuÅÆâr’ ¢FVb–ÖB†B“ ¢–bæ÷BC ¢&WGW&âæöæP¢–b†6GG"†BÂv—6öf÷&ÖBr“ ¢BÒBæ—6öf÷&ÖB‚¢&WGW&âBç&WÆ6R‚rÒrÂrr•³£…Ò÷"æöæP ¢FVb–ÖE÷ÇW3†B“ ¢–bæ÷BC ¢&WGW&âæöæP¢–b—6–ç7Fæ6R†BÂ7G"“ ¢BÒFFRæg&öÖ—6öf÷&ÖB†B¢g&öÒFFWF–ÖR–×÷'BF–ÖVFVÇF¢&WGW&â†B²F–ÖVFVÇF†F—3Ó’’æ—6öf÷&ÖB‚’ç&WÆ6R‚rÒrÂrr ¢2W"ÔD’7F×†Ö–Fæ–v‡BUD2öbF†R'V–ÆBFFR’ÂäõBW"×6V6öæBvÆÂÖ6Æö6³ ¢2¶VW26ÆVæF"æ–72'—FRÖ–FVçF–6Â7&÷726ÖRÖF’&V'V–ÆG26òF†RF–Ç¢2WFòÖ'V–ÆB6öÖÖ—BFöW6âwB6öæfÆ–7Bv—F‚ÖçVÂVF—G2â7F–ÆÂ&Vg&W6†W2F–Ç¢22WfVçG2&öÆÂ–çFòF†R7Bâ…$d2SSCRöæÇ’æVVG2fÆ–BUD2EE5DÕâ¢æ÷uö—6òÒDôD’ç7G&gF–ÖR‚rU’VÒVEC¢r ¢Æ–æW2Ò°¢t$Tt”ã¥d4ÄTäD"rÀ¢udU%4”ôã£"ãrÀ¢u$ôD”C¢Òòô&7F–4&ÇVRòôWfVçBG&6¶W"òôTârÀ¢t4Å44ÄS¤u$Ttõ$”ârÀ¢tÔUD„ôC¥T$Ä•4‚rÀ¢u‚Õu"Ô4ÄäÔS¤&7F–4&ÇVR+r6fVBWfVçG2rÀ¢u‚Õu"Ô4ÄDU43¤ÆÂ6fVBWfVçG2ÇW2WfW'’ÖçVÂFF—F–öââWFFVBF–Ç’ârÀ¢Ð ¢FVbW6…öWfVçB‡V–BÂæÖRÂ7F'BÂVæBÂÆö6F–öâÂFW67&—F–öâÂW&ÂÂW&vVçB“ ¢Æ–æW2æVæB‚t$Tt”ã¥dUdTåBr¢Æ–æW2æVæB‚uT”C¢r²V–B¢Æ–æW2æVæB‚tEE5DÕ¢r²æ÷uö—6ò¢–b7F'C ¢Æ–æW2æVæB‚tEE5D%CµdÅTSÔDDS¢r²7F'B¢–bVæC ¢Æ–æW2æVæB‚tEDTäCµdÅTSÔDDS¢r²VæB¢Æ–æW2æVæB‚u5TÔÔ%“¢r²–75öW66R†æÖR’¢–bÆö6F–öã ¢Æ–æW2æVæB‚tÄô4D”ôã¢r²–75öW66R†Æö6F–öâ’¢–bFW67&—F–öã ¢Æ–æW2æVæB‚tDU45$•D”ôã¢r²–75öW66R†FW67&—F–öâ’¢–bW&Ã ¢Æ–æW2æVæB‚uU$Ã¢r²W&Â¢–bW&vVçC ¢Æ–æW2æVæB‚t4DTtõ$”U3¥U$tTåBr¢Æ–æW2æVæB‚tTäC¥dUdTåBr ¢26fVBWfVçG2g&öÒF†R&VwVÆ"6FÆöp¢6fVEö6÷VçBÒ ¢2FVGWwV&C¢F†R6ÖR&VÂ×v÷&ÆBWfVçB6âW†—7BGv–6R†6FÆör&÷p¢2†öÆF–ær7V¶–ær–æfò²ÖçVÂ&÷r†öÆF–ærGFVæF–ær–æfò’âVÖ—GF–æp¢2&÷F‚F÷V&ÆW2—B–âWfW'’7V'67&–&VB6ÆVæF"„ævVÆw2&W÷'B’Â6ò¶W¢2V6‚dUdTåB'’æ÷&ÖÆ—¦VBÖæÖR²7F'BFFRæBVÖ—BöæÇ’F†Rf—'7Bà¢2FFR×W7BÖF6‚Föò(	B$‡VÖå‚"…fVv2Â"’g2$‡VÖå‚×7FW&FÒ"…6W¢26†&RæÖRÖ6÷&R'WB&RF–ffW&VçBWfVçG2à¢÷6VVåö¶W—2Ò6WB‚¢FVböFVGWö¶W’†æÖRÂ7F'E÷–ÖB“ ¢–×÷'B&R2÷&P¢2Ò÷&Rç7V"‡"uµæ×£Ó’ÒrÂrrÂ7G"†æÖR÷"rr’æÆ÷vW"‚’¢2Ò÷&Rç7V"‡"uÆ"ƒ#ÆEÆGÇW6Ææ÷'F‚ÖW&–6ÆWW&÷WÆVF—F–öçÇF†WÆæçVÂ•Æ"rÂrrÂ2¢&WGW&ârræ¦ö–â‡2ç7Æ—B‚’’²wÂr²7G"‡7F'E÷–ÖB÷"rr ¢f÷"Wb–â‡FöF•öWg2²W6öÖ–ær“ ¢7BÒ7FFUö'•öçVÒævWB†WbævWB‚vçVÒr’¢–bæ÷B7B÷"æ÷B7BævWB‚w6fVBr“ ¢6öçF–çVP¢ö²ÒöFVGWö¶W’†WbævWB‚væÖRr’Â–ÖB†WbævWB‚u÷7F'Br’’¢–bö²–â÷6VVåö¶W—3 ¢6öçF–çVP¢÷6VVåö¶W—2æFB…ö²¢6fVEö6÷VçB³Ò¢7F'BÒWbævWB‚u÷7F'Br¢VæBÒWbævWB‚uöVæBr’÷"7F'@¢FW65÷'G2ÒµÐ¢–bWbævWB‚wv‡’r“¢FW65÷'G2æVæB†We²wv‡’uÒ¢–b7BævWB‚væ÷FW2r“¢FW65÷'G2æVæB‚tæ÷FW3¢r²7E²væ÷FW2uÒ¢–b7BævWB‚w7V¶W"r“¢FW65÷'G2æVæB‚u7V¶W#¢r²7E²w7V¶W"uÒ¢–b7BævWB‚w7FGW2r“¢FW65÷'G2æVæB‚u7FGW3¢r²7E²w7FGW2uÒ¢&–÷&—G’Ò7BævWB‚w&–÷&—G•ö÷fW'&–FRr’÷"WbævWB‚w&–÷&—G’r¢–b&–÷&—G“ ¢FW65÷'G2æVæB‚u&–÷&—G“¢r²&–÷&—G’¢W6…öWfVçB€¢V–BÒvWfVçB×·Ô&7F–6&ÇVRÖWfVçB×G&6¶W"ræf÷&ÖB†We²vçVÒuÒ’À¢æÖRÒWbævWB‚væÖRrÂrr’À¢7F'BÒ–ÖB‡7F'B’À¢VæBÒ–ÖE÷ÇW3†VæB’–bVæBVÇ6RæöæRÀ¢Æö6F–öâÒWbævWB‚vÆö6F–öâr’À¢FW67&—F–öâÒuÆâræ¦ö–â†FW65÷'G2’À¢W&ÂÒUdTåEõU$Å2ævWB‡7G"†WbævWB‚vçVÒrÂrr’’’À¢W&vVçBÒ&ööÂ‡7BævWB‚wW&vVçBr’’À¢ ¢2WfW'’ÖçVÂWfVçB„ævVÆFFVBF†W6RFVÆ–&W&FVÇ’ÂF†W’w&RÇv—2–â¢6¶—VEöÖçVÂÒ ¢f÷"Ò–âÖçVÅ÷&÷w3 ¢2„”DDTâäB4ôeBÔDTÄUDTBUdTåE2DòäõBtò”âD„RT$Ä”2dTTBà¢26ÆVæF"æ–72—27V'67&–&&ÆRU$Â(	BF†Rv†öÆRö–çBöb†–F–ærà¢2WfVçBFVÒ×v–FR—2F†B—B7F÷2V&–ærÂæBF†RfVVBv27F–ÆÀ¢2V&Æ—6†–ærÆÂöbF†VÒ„‡W&ÆW’##bÓ‚ÓS¢f÷VæB•fVçF—bÂvÆö&À¢2f–çFV6‚fW7BæBRå2â&æµFV6‚7VÖÖ—BÆÂÆ—fR–âF†Ræ–72v†–ÆP¢2fÆvvVB†–FFVâ–âF†RFF&6R’âF†Rw&–BÂ6ÆVæF"f–WræBÖ ¢2Ç&VG’†öæ÷W"F†—3²F†RfVVBv2F†RöæR7W&f6RF†BF–FâwBà¢2õöFVÆWFVEõö—2F†R6ögBÖFVÆWFR6VçF–æVÂ(	BæöæRFöF’Â'WBFVÆWFV@¢2WfVçB&V6†–ær7V'67&–&W'2v÷VÆB&Rv÷'6RF†â†–FFVâöæRà¢–bÒævWB‚v†–FFVâr’—2G'VS ¢6¶—VEöÖçVÂ³Ò¢6öçF–çVP¢–b7G"†ÒævWB‚væÖRr’÷"rr’ç7G&—‚’ÓÒuõöFVÆWFVEõòs ¢6¶—VEöÖçVÂ³Ò¢6öçF–çVP¢6BÒÒævWB‚w7F'EöFFRr¢VBÒÒævWB‚vVæEöFFRr’÷"6@¢2&6²Ö6ö×C¢öÆFW"&÷w2&RÖFFRF†R¥2×6–FRFFRFW&—fF–öâæ@¢2†fRåTÄÂ7F'BöVæBâ&WW6RF†RW†—7F–ær—F†öâ'6UöFFR‚’6ð¢2F†W’7F–ÆÂV"–âF†RfVVBv—F‚F†R&–v‡B×VÇF’ÖF’&ævRà¢–bæ÷B6BæBÒævWB‚vFFU÷7G"r“ ¢2ÂRÒ'6UöFFR†Õ²vFFU÷7G"uÒ¢–b3 ¢6BÒ0¢–bæ÷BVC ¢VBÒR÷"0¢–bæ÷B6C ¢6¶—VEöÖçVÂ³Ò¢6öçF–çVP¢ö²ÒöFVGWö¶W’†ÒævWB‚væÖRr’Â–ÖB‡6B’¢–bö²–â÷6VVåö¶W—3 ¢6¶—VEöÖçVÂ³Ò¢6öçF–çVP¢÷6VVåö¶W—2æFB…ö²¢FW65÷'G2ÒµÐ¢–bÒævWB‚wv‡’r“¢FW65÷'G2æVæB†Õ²wv‡’uÒ¢–bÒævWB‚w&–÷&—G’r“¢FW65÷'G2æVæB‚u&–÷&—G“¢r²Õ²w&–÷&—G’uÒ¢–bÒævWB‚v7&VFVEö'’r“¢FW65÷'G2æVæB‚tFFVB'“¢r²Õ²v7&VFVEö'’uÒ¢W6…öWfVçB€¢V–BÒvÖçVÂ×·Ô&7F–6&ÇVRÖWfVçB×G&6¶W"ræf÷&ÖB†ÒævWB‚v–Br’’À¢æÖRÒÒævWB‚væÖRrÂrr’À¢7F'BÒ–ÖB‡6B’À¢VæBÒ–ÖE÷ÇW3†VB’–bVBVÇ6RæöæRÀ¢Æö6F–öâÒÒævWB‚vÆö6F–öâr’À¢FW67&—F–öâÒuÆâræ¦ö–â†FW65÷'G2’À¢W&ÂÒÒævWB‚wW&Âr’À¢W&vVçBÒfÇ6RÀ¢ ¢Æ–æW2æVæB‚tTäC¥d4ÄTäD"r¢FW‡BÒuÇ%Æâræ¦ö–â†Æ–æW2’²uÇ%Æâp¢õUEô”52çw&—FU÷FW‡B‡FW‡BÂVæ6öF–æsÒwWFbÓ‚r¢×6rÒbuu$õDR´õUEô”57Ò‡´õUEô”52ç7FB‚’ç7E÷6—¦S¢ÇÒ'—FW2Â·6fVEö6÷VçGÒ6fVB²¶ÆVâ†ÖçVÅ÷&÷w2’Ò6¶—VEöÖçVÇÒÖçVÂp¢–b6¶—VEöÖçVÃ ¢×6r³ÒbrÂ·6¶—VEöÖçVÇÒÖçVÂ6¶—VB(	BVç'6V&ÆRFFU÷7G"p¢&–çB†×6r²r’r  ¦–bõöæÖUõòÓÒuõöÖ–åõòs ¢'V–ÆB‚