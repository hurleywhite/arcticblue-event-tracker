#!/usr/bin/env python3
"""Build an ArcticBlue Event Tracker — a self-contained, beautiful, deploy-direct
HTML page using ArcticBlue's real brand (black, periwinkle, Hanken Grotesk).

Pulls the 82 events from the Q2/Q3 2026 doc, splits them into TODAY / UPCOMING /
ARCHIVED relative to today (2026-05-21), and renders a single file ready to
upload to Vercel."""
import sys
sys.path.insert(0, '/Users/hurleywhite/Library/Python/3.11/lib/python/site-packages')
# `from docx import Document` is now lazy inside _parse_events_docx() — the
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
EVENTS_SOURCE = HERE / 'data' / 'events.json'   # canonical source — fed by Dust agent ingest
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
    # The team is in New York, and CI runs in UTC — between midnight and 4-5am
    # UTC that is still YESTERDAY in New York, so a plain date.today() rolled
    # the tracker over hours early (Hurley 2026-07-30). Everything downstream
    # (today / upcoming / archived, the header stamp) keys off this.
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        TODAY = _dt.now(ZoneInfo('America/New_York')).date()
    except Exception:
        TODAY = date.today()

# ── Supabase (For Angela ops tab) ────────────────────────────────────────────
# Project: AB Event Tracker [Hurley's Org] (ref efkvhlmfdwlobvdmvqiq)
# The publishable key is safe to embed in the HTML — RLS protects the data.
# Writes to event_state and manual_events require auth.email() in allowed_editors.
SUPABASE_URL              = 'https://efkvhlmfdwlobvdmvqiq.supabase.co'
SUPABASE_PUBLISHABLE_KEY  = 'sb_publishable_Lu7bLEA1jdsJXFDrKqC1OA_LYAjWYEj'

# Persona single-source-of-truth (config/personas.json) baked into the page so
# the Day-Of tab + brief drawer render without a runtime fetch. api/briefing.py
# reads the same file. PERSONAS_JS is a JSON object literal for the JS.
PERSONAS_JS = json.dumps(json.loads((HERE / 'config' / 'personas.json').read_text()), ensure_ascii=False)

# NEVER hallucinate URLs — only use what's in the doc OR what's manually
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
      1. data/events.json  — the canonical, ingest-fed state (preferred)
      2. data/ArcticBlue AI 2026 Event Tracker.docx — legacy bootstrap fallback
    """
    if EVENTS_SOURCE.exists():
        return _load_events_json()
    return _parse_events_docx()


def _load_events_json():
    """Read canonical events from data/events.json. Side-effect: merge any
    `url` fields into the global EVENT_URLS map so render still respects
    the no-hallucination rule (null url → unlinked card)."""
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
    # baked into the text — redundant noise (Halo is the type, Seed is a flag).
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
        m = re.match(r'^(\d+)\.\s+(.+?)\s+—\s+(.+?)\s+\|\s+(.+)$', txt)
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
    """Return (start_date, end_date, original_string). Handles 'June 1–4, 2026',
    'May 19, 2026', 'June 3–6, 2026 (TBC)', etc."""
    s = date_str.strip()
    # Strip parentheticals
    s_clean = re.sub(r'\([^)]+\)', '', s).strip()
    # Try patterns
    months = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
              'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}
    # "Month D[–|-D] YYYY"
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2})\s*[–-]\s*(\d{1,2}),\s+(\d{4})$', s_clean)
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
    # "Month D – Month D, YYYY" (cross-month)
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2})\s*[–-]\s*([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$', s_clean)
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
    # Numeric (Angela's spreadsheet style) — "6/3/2026", "6/3-5/2026",
    # "6/3-6/5/2026", "3/6/26". Mirrors the client deriveDatesFromText so the
    # iCal feed + classification don't silently skip these.
    def _yr(v):
        v = int(v)
        return v + 2000 if v < 100 else v
    m = re.match(r'^(\d{1,2})/(\d{1,2})\s*[–-]\s*(\d{1,2})/(\d{1,2})/(\d{2,4})$', s_clean)  # M/D-M/D/Y
    if m:
        try:
            return date(_yr(m.group(5)), int(m.group(1)), int(m.group(2))), \
                   date(_yr(m.group(5)), int(m.group(3)), int(m.group(4)))
        except ValueError:
            pass
    m = re.match(r'^(\d{1,2})/(\d{1,2})\s*[–-]\s*(\d{1,2})/(\d{2,4})$', s_clean)  # M/D-D/Y (same month)
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
        # An event whose end date is today or earlier is over — archive it
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
        why = why[:220].rsplit(' ', 1)[0] + '…'
    extra_class = ' archived' if archived else ''
    num = ev.get('num', '')
    # Verified URL from the source doc (no invented URLs). The card itself is
    # NO LONGER a link — clicking it opens an expanded pop-up (modal) that
    # carries the website link *inside* it, alongside the rich detail fields.
    url = EVENT_URLS.get(str(num))
    nm = e(ev['name'])
    if url:
        extra_class += ' has-link'
        # The NAME itself is the website link (underlined + very bold). The
        # rest of the card still opens the pop-up; the card's delegated click
        # handler ignores clicks that land inside an <a>.
        name_html = (f'<a class="event-name-link" href="{e(url)}" target="_blank" '
                     f'rel="noopener" aria-label="Open website for {nm}">{nm} '
                     f'<span class="event-link-arrow" aria-hidden="true">↗</span></a>')
    else:
        name_html = (f'{nm} <span class="event-no-link" '
                     f'title="No verified URL on file for this event">·</span>')
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
        <span class="event-more">Details →</span>
      </footer>
    </article>'''


def render_upcoming_grouped(upcoming):
    """Render the upcoming list with a full-width month divider before each
    new month, so the grid reads month-by-month instead of one long block.

    `upcoming` is already sorted ascending by `_start` (events that failed to
    parse a date have no `_start` and sort to the end → grouped under
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

    # ── Catalog data blob for the expanded pop-up (modal) cards ──────────
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
  <title>ArcticBlue · Event Tracker</title>
  <meta name="description" content="ArcticBlue's live tracker of in-person AI events, May–December 2026. Today, upcoming, and archived. 82 enterprise + halo events.">

  <link rel="canonical" href="https://arcticblue.ai/labs/event-tracker/">

  <meta property="og:title" content="ArcticBlue · Event Tracker">
  <meta property="og:description" content="82 in-person AI events tracked live. Today, upcoming, and archived — sorted by priority and region.">
  <meta property="og:image" content="https://arcticblue.ai/og-default.png">
  <meta property="og:url" content="https://arcticblue.ai/labs/event-tracker/">
  <meta property="og:type" content="website">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="ArcticBlue · Event Tracker">
  <meta name="twitter:description" content="82 in-person AI events tracked live.">

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=Nunito+Sans:wght@600;700;800;900&family=Fragment+Mono&display=swap" rel="stylesheet">

  <!-- Supabase JS client — used only by the "For Angela" ops tab -->
  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js" defer></script>

  <style>
    :root {{
      /* Internal-tool palette — white-primary, monochromatic, sharp */
      --ab-bg: #ffffff;
      --ab-bg-2: #fafafa;
      --ab-bg-3: #f4f4f5;
      --ab-rule: #e7e7e8;
      --ab-rule-strong: #d4d4d6;
      --ab-fg: #0a0a0a;
      --ab-fg-2: #404040;
      --ab-fg-3: #737373;
      --ab-mute: #a3a3a3;
      /* Brand accents — used sparingly */
      --ab-blue: #2773c2;        /* primary accent (from the logo's middle blue) */
      --ab-blue-light: #4ea3d4;  /* lighter accent */
      --ab-amber: #ca8a04;        /* medium-priority */
      --ab-green: #15803d;        /* available / success */
      --ab-red: #b91c1c;          /* archived / fail */
      --ab-sans: "Hanken Grotesk", "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
      --ab-mono: "Fragment Mono", "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
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

    /* ───────────── nav strip ───────────── */
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
    /* "Who am I" — your bubble; click it to drop down everyone else's bubbles
       to switch, or "Other…" to type a name not on the roster. */
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
    /* App title — centered in the nav bar, same line as the logo + last-updated. */
    .app-title {{
      /* Matches the ArcticBlue logo — basic Helvetica-Bold (Thor's note). Uses
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

    /* ───────────── hero ───────────── */
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

    /* KPI strip — uniform columns, labels sit directly under numbers */
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

    /* ───────────── today/up-next callout ───────────── */
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

    /* ───────────── filters ───────────── */
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

    /* ───────────── event cards ───────────── */
    .event-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
    }}
    /* Month dividers inside the upcoming grid — span the full row so the
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
    /* THE status line — one quiet derived line per card ("Closed to speak ·
       Open to attend", "Booked — Thor speaking"). Plain text + a small colored
       dot; no boxes, no color assault. */
    .ops-status-line {{
      display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px;
      margin: 0 0 10px; font-size: 0.86rem; font-weight: 600; color: var(--ab-fg-2);
    }}
    .st-bit {{ display: inline-flex; align-items: center; white-space: nowrap; }}
    .st-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 6px; flex-shrink: 0; }}
    .st-ok   {{ background: #047857; }}
    .st-wait {{ background: #0ea5e9; }}
    .st-no   {{ background: #b91c1c; }}
    .st-sep  {{ color: var(--ab-fg-3); font-weight: 400; }}
    .st-sub-date {{ color: var(--ab-fg-3); font-weight: 500; }}
    /* Emoji between the status word and the "— Name": 🎤 = speaking
       (Booked / Submitted / Rejected), 🎟 = attending. No opacity — it just
       washes emoji out — and a hair under 1em so they sit with the text. */
    .st-mic {{
      display: inline-block; margin: 0 3px 0 5px; font-size: 0.92em; line-height: 1;
      font-family: "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif;
    }}
    /* Whisper-quiet data-freshness cue from updated_at. Deliberately faint —
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
    .ops-fresh.is-fresh {{ color: #6b8f7a; }}   /* muted sage — quietly reassuring */
    .ops-fresh.is-stale {{ color: #b08968; }}   /* muted clay — a gentle "check me" */
    /* One-click "Apply to speak" button on ops cards — the booking shortcut. */
    /* Deadline/closed-to-speak label + Apply button sit side by side in one
       compact row, pinned to the bottom of the card (not each its own
       full-width block). */
    /* Card footer = a fixed STACK, one item per row, always in the same order:
       CFP deadline -> ✉ Contact -> Apply to speak. It used to be a wrapping row,
       so a card with a deadline put "CFP deadline: Rolling" and the Contact chip
       side by side while every other card had Contact on its own line — the chip
       landed in a different place card to card (Angela). Pinned to the bottom
       (margin-top:auto) so the footers line up across a row of cards. */
    .ops-card-foot {{
      display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
      margin-top: auto;
    }}
    .ops-card-foot > * {{ max-width: 100%; }}
    .ops-card-foot .ops-meta {{ margin: 0; }}
    /* Apply spans the FULL card width on its own row (Hurley — only Angela sees
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
    /* The event name doubles as the website link — underlined + very bold. */
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
    /* Note preview on the card face — clamped to 2 lines so a long pasted note
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

    /* ───────────── expanded pop-up (modal) ───────────── */
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
    /* Fixed top toolbar — Edit event + close sit in the SAME spot for every
       event. Full-width opaque band so form fields scroll cleanly UNDERNEATH it
       (no content bleeding through behind the buttons). */
    .modal-topbar {{
      position: absolute; top: 0; left: 0; right: 0; z-index: 3;
      display: flex; align-items: center; justify-content: flex-end; gap: 8px;
      padding: 12px 14px; background: #fff;
      border-bottom: 1px solid var(--ab-rule);
      border-radius: 8px 8px 0 0;
    }}
    /* Top-LEFT slot — holds the trash-can Delete while the editor is open. The
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
    /* Most events now render NO top label at all — don't leave its margin behind. */
    .modal-badges:empty {{ margin-bottom: 0; }}
    /* Date now sits LAST, under the city — so it carries no bottom margin. */
    .modal-date {{
      font-family: var(--ab-mono); font-size: 0.82rem; color: var(--ab-fg-3);
      margin: 0; letter-spacing: 0.02em;
    }}
    .modal-title {{
      font-family: var(--ab-sans); font-size: 1.55rem; font-weight: 800;
      line-height: 1.2; letter-spacing: -0.02em; margin: 0 0 6px; color: var(--ab-fg);
    }}
    /* Modal heading doubles as the website link — underlined, inherits 800 weight. */
    .modal-title-link {{
      color: inherit; text-decoration: underline; text-decoration-thickness: 2px;
      text-underline-offset: 3px; text-decoration-color: var(--ab-rule-strong);
      transition: color 0.15s, text-decoration-color 0.15s;
    }}
    .modal-title-link:hover, .modal-title-link:focus-visible {{
      color: var(--ab-blue); text-decoration-color: var(--ab-blue);
    }}
    /* City sits between the title and the date — a hair of space either side so
       the two read as one block of qualifiers under the name. */
    .modal-loc {{ font-size: 0.92rem; color: var(--ab-fg-2); margin: 0 0 3px; }}
    .modal-loc .event-region {{ color: var(--ab-fg); font-weight: 600; }}
    .modal-body {{ display: flex; flex-direction: column; gap: 16px; }}
    .modal-field {{ display: flex; flex-direction: column; gap: 4px; }}
    /* Field labels in Details (NOTES, ATTENDEES, ARCTICBLUE SPEAKER, …) — bold
       and a step darker so each section is findable when scanning (Angela). */
    .modal-field .k {{
      font-family: var(--ab-mono); font-size: 0.64rem; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--ab-fg-2); font-weight: 700;
    }}
    .modal-field .v {{ font-size: 0.92rem; color: var(--ab-fg); line-height: 1.55; white-space: pre-wrap; }}
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
    /* Editable modal — one-tap quick-action bar at the top of the body. */
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
    .modal-quickbar .qa.on {{
      background: #166534; color: #fff; border-color: #166534;
    }}
    /* Rejected-to-speak is a negative outcome — reads red when set. */
    .modal-quickbar .qa-neg.on {{ background: #b91c1c; border-color: #b91c1c; }}
    /* Primary edit affordance — top-right of the modal header, same spot always. */
    /* Edit — the primary action, solid ArcticBlue. */
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
    /* Enrich — soft purple "research" accent (AI = purple across the app);
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
    /* ── Follow-up log ──────────────────────────────────────────────
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
    .fu-state.fu-due {{ background: #fff7ed; color: #9a3412; }}
    .fu-state.fu-due::before {{ background: #f59e0b; }}
    .fu-state.fu-ok {{ background: #f0fdf4; color: #15803d; }}
    .fu-state.fu-ok::before {{ background: #22c55e; }}
    .fu-state.fu-hold::before {{ background: #94a3b8; }}
    .fu-state.fu-closed {{ color: var(--ab-fg-3); }}
    .fu-state.fu-closed::before {{ background: var(--ab-rule-strong); }}
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
    .fu-log li:first-child::before {{ border-color: var(--ab-blue); }}
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
      font-family: var(--ab-sans); font-size: 0.72rem; color: var(--ab-fg-3);
      background: none; border: 0; padding: 0; cursor: pointer; text-decoration: underline;
    }}
    .fu-act:hover {{ color: var(--ab-blue); }}
    .fu-act-del:hover {{ color: var(--ab-red); }}
    /* ── Shared inline form ───────────────────────────────────────────
       ONE look for every "add something" in the tool. Nothing is typed into
       a browser prompt() any more: those float at the top of the window,
       detached from what they're about, and look nothing like the app
       (Hurley 2026-07-30). The pattern is always: a quiet add button, which
       swaps in place for a field + Save/Cancel. */
    .ab-addbtn {{
      display: inline-flex; align-items: center; gap: 6px;
      /* The modal section is a flex column, which blockifies inline-flex and
         stretches the button edge-to-edge — pin it to its own content. */
      align-self: flex-start; width: fit-content;
      font-family: var(--ab-sans); font-size: 0.82rem; font-weight: 600;
      color: var(--ab-fg-2); background: var(--ab-bg-2);
      border: 1px solid var(--ab-rule-strong); border-radius: 9px;
      padding: 7px 14px; cursor: pointer;
      transition: border-color 120ms, color 120ms, background 120ms;
    }}
    .ab-addbtn:hover {{ border-color: var(--ab-blue); color: var(--ab-blue); background: var(--ab-bg); }}
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
    .ab-form-hint {{
      margin-left: auto; font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3);
    }}
    .ab-btn-danger {{ border-color: var(--ab-red); background: var(--ab-red); color: #fff; }}
    /* Event picker inside the conflict form — the same list-of-hits idea the
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
    /* Matches .fu-act — one look for "quiet action on a row". */
    .cf-edit {{
      font-family: var(--ab-sans); font-size: 0.72rem; color: var(--ab-fg-3);
      background: none; border: 0; padding: 0; cursor: pointer; text-decoration: underline;
    }}
    .cf-edit:hover {{ color: var(--ab-blue); }}
    /* Card-face conflict warning. NOT a pill and NOT bordered — a rounded
       chip read as a button people expected to click (Hurley 2026-07-30). It's
       a warning LINE: amber rule down the left, no background, no border. */
    .ops-clash {{
      display: flex; align-items: flex-start; gap: 6px;
      font-family: var(--ab-sans); font-size: 0.76rem; font-weight: 500;
      color: #9a3412; background: none; border: 0;
      border-left: 2px solid #f59e0b; border-radius: 0;
      padding: 1px 0 1px 8px; margin-top: 7px; cursor: default;
    }}
    /* ── Hover peek: conversation + notes without opening the card ────── */
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
    /* Notes cap at FOUR lines — some are very long, and the rest is one click
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
    /* Touch has no hover — never show it there. */
    @media (hover: none) {{ .card-peek {{ display: none !important; }} }}

    /* Should-Attend name picker — hover (or focus) the button to choose who
       it's for. Sits above the quickbar so it can't be clipped by the row. */
    .qa-sa-wrap {{ position: relative; display: inline-flex; }}
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
    /* Inline editor inside the pop-up — change fields right here. */
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
    /* Edit form controls — full-width, sit right under their .modal-field label
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
       the two read as the same document (Angela). A heavier 2px rule — the old
       hairline didn't separate the groups strongly enough to scan by. */
    .me-sec {{ margin-top: 24px; padding-top: 16px; border-top: 2px solid var(--ab-rule-strong); }}
    .me-sec:first-of-type {{ margin-top: 0; padding-top: 0; border-top: 0; }}
    /* Read-view zones stack their fields the way .modal-body does. */
    .modal-view .me-sec {{ display: flex; flex-direction: column; gap: 16px; }}
    .modal-view .me-sec-h {{ margin-bottom: 0; }}
    /* The zone heading must outrank the field labels inside it — it was lighter
       and thinner than them, which read as backwards. Full-strength ink, heavier
       and a touch larger than a .modal-field .k. */
    .me-sec-h {{
      margin: 0 0 12px; font-family: var(--ab-sans); font-size: 0.8rem; font-weight: 700;
      letter-spacing: 0.06em; text-transform: uppercase; color: var(--ab-fg);
    }}
    /* The folded "Rarely used" zone — click the heading to reveal. */
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
    /* "Interested" picker — roster name chips you toggle on. */
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
       catalog's past-events disclosure. Removed with the markup — they were
       also the last "Show / hide" and "Hide" strings attached to the word
       archive, which now means one thing: an event you archived.) */

    /* ───────────── footer ───────────── */
    footer.foot {{
      margin: 96px 0 0; padding: 32px 0 64px;
      border-top: 1px solid var(--ab-rule);
      display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap;
    }}
    .foot-text {{ color: var(--ab-fg-3); font-size: 0.85rem; margin: 0; }}
    .foot-mono {{ font-family: var(--ab-mono); font-size: 0.78rem; color: var(--ab-fg-3); letter-spacing: 0.04em; }}

    /* ───────────── tab strip ───────────── */
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

    /* ───────────── For Angela — auth + ops UI ───────────── */
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

    /* Ops grid — one full-width card per line (was a multi-column tile grid) so
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
    /* Whole card is clickable → opens the detail pop-up. Hover lift + focus ring
       signal it; the star / chips / links inside keep their own actions. */
    .ops-card:hover {{ border-color: var(--ab-rule-strong); box-shadow: 0 2px 10px rgba(0,0,0,0.07); }}
    .ops-card:focus-visible {{ outline: 2px solid var(--ab-blue); outline-offset: 2px; }}
    /* Recently added (yellow) — lowest-priority outline, so a blue interested /
       should-attend outline below overrides it when both apply. */
    .ops-card.is-recent {{ border-color: #eab308; }}
    .ops-card.is-saved {{ border-color: var(--ab-blue); }}
    .ops-card.is-mine  {{ border-color: var(--ab-blue); }}   /* the signed-in person starred it */
    .ops-card.is-sa    {{ border-color: var(--ab-blue); }}   /* Angela flagged Should Attend (blue outline, like an interested card) */
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
    /* Tiny per-card chat indicator ("💬 N"), always visible when there are messages. */
    .chat-count {{ font-family: var(--ab-mono); font-size: 0.58rem; color: var(--ab-fg-3); letter-spacing: 0.02em; align-self: center; white-space: nowrap; }}
    /* Modal "Discussion" thread. */
    /* Sits right after the quickbar, which already supplies the divider line
       (border-bottom) — no second border here, or you get a doubled-up gap. */
    .event-chat {{ margin-top: 4px; margin-bottom: 20px; }}
    /* Bold, and a step darker so the weight actually reads at 0.7rem (Hurley). */
    .chat-h {{ font-family: var(--ab-mono); font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ab-fg-2); margin: 0 0 10px; }}
    .chat-list {{ display: flex; flex-direction: column; gap: 8px; max-height: 260px; overflow-y: auto; margin: 0 0 12px; padding-top: 16px; }}
    .chat-empty {{ font-size: 0.85rem; color: var(--ab-fg-3); font-style: italic; margin: 0; }}
    .chat-msg {{ position: relative; background: var(--ab-bg-2); border: 1px solid var(--ab-rule); border-radius: 8px; padding: 8px 10px; }}
    .chat-meta {{ display: flex; gap: 8px; align-items: baseline; margin-bottom: 3px; }}
    .chat-who {{ font-weight: 700; font-size: 0.8rem; color: var(--ab-fg); }}
    .chat-when {{ font-family: var(--ab-mono); font-size: 0.6rem; color: var(--ab-fg-3); }}
    /* Slack-style hover toolbar: add-to-notes · 👍 · 👎 · delete (own only).
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
    /* Reaction emojis are the primary affordance — render them bigger. */
    .chat-react-btn {{ font-size: 1.28rem; }}
    .chat-react-btn:hover {{ transform: scale(1.12); }}
    /* Divider between reactions and the actions. */
    .chat-act-sep {{ width: 1px; align-self: stretch; margin: 3px 3px; background: var(--ab-rule); }}
    .chat-more {{ font-size: 1.2rem; letter-spacing: 1px; }}
    /* Forward-to-teammate + ⋯ "More" (delete) popovers — fixed-positioned (a
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
    .chat-mention {{ color: var(--ab-blue); font-weight: 600; }}   /* @teammate — pings them via "In the last week" */
    /* 👍/👎 tallies under a message. */
    .chat-reacts {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
    .chat-react {{
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 0.9rem; color: var(--ab-fg-2);
      background: var(--ab-bg-3); border: 1px solid var(--ab-rule); border-radius: 999px; padding: 2px 9px;
    }}
    /* Who reacted, shown next to the emoji. */
    .chat-react-who {{ font-family: var(--ab-mono); font-size: 0.66rem; font-weight: 600; }}
    .chat-react.is-mine {{ border-color: var(--ab-blue); color: var(--ab-blue); background: rgba(31,160,220,0.10); }}
    /* Mini per-event assistant — deliberately smaller than the chat composer
       so it reads as a utility, not the main action. */
    .ask1-form {{ display: flex; gap: 8px; margin: 18px 0 0; align-items: stretch; }}
    .ask1-input {{
      flex: 1; padding: 9px 13px; font: inherit; font-size: 0.87rem;
      border: 1px solid var(--ab-rule-strong); border-radius: 9px;
      background: var(--ab-bg); color: var(--ab-fg);
    }}
    .ask1-input::placeholder {{ color: var(--ab-fg-3); }}
    .ask1-input:focus {{
      border-color: var(--ab-blue); outline: none;
      box-shadow: 0 0 0 3px rgba(39,115,194,0.12);
    }}
    .ask1-go {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 0 16px; border-radius: 9px; cursor: pointer;
      font-family: var(--ab-sans); font-size: 0.85rem; font-weight: 600;
      white-space: nowrap;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg-2); color: var(--ab-fg-2);
    }}
    .ask1-go:hover {{ border-color: var(--ab-blue); background: var(--ab-bg); color: var(--ab-blue); }}
    .ask1-ic {{ color: #7c3aed; font-size: 0.9rem; line-height: 1; }}
    .ask1-answer {{
      margin-top: 7px; padding: 9px 11px; font-size: 0.85rem; line-height: 1.45;
      color: var(--ab-fg); background: var(--ab-bg-2); border-radius: 8px;
      border-left: 2px solid var(--ab-blue); white-space: pre-wrap;
    }}
    .chat-form {{ display: flex; gap: 8px; }}
    .chat-input {{ flex: 1; padding: 9px 12px; border: 1px solid var(--ab-rule-strong); border-radius: 8px; font: inherit; font-size: 0.9rem; }}
    .chat-send {{ padding: 9px 16px; border-radius: 8px; border: 1px solid var(--ab-blue); background: var(--ab-blue); color: #fff; font-weight: 600; cursor: pointer; white-space: nowrap; }}
    .chat-send:hover {{ opacity: 0.9; }}
    /* One row: title, then date · place right next to it, then any chips/
       labels (star, urgent, archive, decision, chat count) pushed flush to
       the empty space at the end — same row on every card, so everything
       lands in the same spot instead of shifting card to card. */
    .ops-card-head {{
      display: flex; align-items: flex-start; flex-wrap: nowrap;
      column-gap: 10px; margin-bottom: 2px;
    }}
    .ops-card-head .event-name {{ flex: 1 1 auto; min-width: 60px; margin: 0; }}   /* grows so the star/hide/chat cluster pins to the top-right */
    .ops-card-head .ops-chips {{ flex: 0 0 auto; margin-left: auto; align-self: flex-start; }}   /* top-right cluster */
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
         everything below it up — it lines up across cards either way. */
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
    /* Small amber warning action in the queue — opens the conflict prompt. */
    .q-btn-conflict {{
      color: #9a3412; border-color: #fed7aa; background: #fff7ed;
      font-size: 0.9rem; line-height: 1; padding: 0 10px;
    }}
    .q-btn-conflict:hover {{ background: #fde9d3; border-color: #f59e0b; }}
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
    /* Per-role roster on the card face — a small colored initial-avatar next to
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
    /* Urgent is Angela-only — for everyone else, hide its pill and drop the red cues. */
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
    .ops-edit > summary::before {{ content: "▸ "; display: inline-block; transition: transform 120ms ease; }}
    .ops-edit[open] > summary::before {{ content: "▾ "; }}
    .ops-edit > summary:hover {{ color: var(--ab-fg); }}

    .ops-form {{ display: grid; gap: 10px; margin-top: 12px; }}
    .ops-form .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    /* .ops-fieldset is a NON-label field wrapper — used where the field holds
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

    /* Pipeline-stage filter row — the new primary status control. The
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

    /* Extra filters (used by the Dust event-search panel: Types / Quarters / …) */
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
    /* Compact filter dropdown — same look as the Months menu. */
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
    /* Always-visible top filter line: Pipeline · Region · Fits · Months ·
       Should attend — compact multi-select dropdowns (replaced the tall
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
    /* Ask Anything sits next to search — matched to the filter/search height. */
    .ops-topfilters .ab-btn--ask {{ flex: 0 0 auto; padding: 11px 16px; font-size: 0.86rem; font-weight: 700; }}
    /* Filter icon — reveals the drawer holding every non-status filter. */
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
    /* "N filters active — Clear all", right under the top filter bar — an
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
       the filter bar isn't the dominant element — search + toggle stay visible. */
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
    /* Primary nav — underlined TEXT tabs (not pills). The row's hairline doubles
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
    /* View switcher — icon-only segmented group (List / Calendar / Map). */
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

    /* ── Queue view (Angela's application queue) ─────────────────── */
    .ops-myevents, .ops-planahead, .ops-myprofile, .ops-queue, .ops-planner, .ops-dayof {{ display: none; }}
    .ops-myevents.show, .ops-planahead.show, .ops-myprofile.show, .ops-queue.show, .ops-planner.show, .ops-dayof.show {{ display: block; }}
    /* ── Day-Of tab ─────────────────────────────────────────────── */
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
    /* Load-failure / degraded / filtered-empty states — a blank grid is never OK. */
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
    /* ── Brief drawer ───────────────────────────────────────────── */
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
    /* Collapsible section (My Events "Past events" dropdown) — starts collapsed. */
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
    /* Whole-row click-to-open (My Lineup) — reads as one big button. */
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
    /* "Reach out" asks — a warm to-do tint so they read as an action assigned
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
    /* Little chat-bubble badge on a comment card's avatar — signals "chat". */
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
    /* Routine pipeline moves, grouped per person — collapsed by default. */
    .wn-group {{ border: 1px solid var(--ab-rule); border-radius: 10px; margin: 0 0 8px; overflow: hidden; }}
    .wn-group-head {{
      display: flex; align-items: center; gap: 10px; padding: 10px 14px; cursor: pointer; user-select: none;
      background: var(--ab-bg-2);
    }}
    .wn-group-head:hover {{ background: var(--ab-bg-3); }}
    .wn-group-name {{ font-weight: 650; font-size: 0.9rem; color: var(--ab-fg); }}
    .wn-group-count {{ font-size: 0.85rem; color: var(--ab-fg-3); }}
    /* "Mark all as read" — Slack's own wording and register: a quiet text
       action, not a button competing with the content. Sits to the right, goes
       blue on hover so it reads as clickable. */
    .wn-readall {{
      font-family: var(--ab-sans); font-size: 0.78rem; font-weight: 600;
      color: var(--ab-fg-3); background: none; border: 0; padding: 2px 4px;
      cursor: pointer; border-radius: 5px; white-space: nowrap;
      transition: color 120ms ease, background 120ms ease;
    }}
    .wn-readall:hover, .wn-readall:focus-visible {{ color: var(--ab-blue); background: rgba(39,115,194,0.08); }}
    /* The section-level one closes out the whole feed — right-aligned in the head. */
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
    /* "Mark applied" + the × dismiss sit side by side, not stacked. */
    .q-btn-row {{ display: flex; gap: 6px; align-items: stretch; }}
    .q-btn-row .q-btn.primary {{ flex: 1; }}
    /* Plan Ahead embedded at the bottom of My Lineup — a clear divider above it. */
    .ops-planahead-embed {{ margin-top: 20px; padding-top: 8px; border-top: 1px solid var(--ab-rule); }}
    /* Plan Ahead decision buttons: "I'm interested" + "Not for me" side by side. */
    .queue-actions.sug-actions {{ flex-direction: row; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .q-btn.sug-skip {{ color: var(--ab-fg-3); }}
    .q-btn.sug-skip:hover {{ border-color: #d64545; color: #d64545; }}
    /* "Batch your trips" — a cluster of nearby-in-time events under an anchor. */
    .trip-cluster {{ position: relative; border-left: 3px solid #1fa0dc; padding-left: 12px; margin: 0 0 20px; }}
    /* ✕ to hide a whole trip cluster / radar group from Plan Ahead (hover-reveal). */
    .plan-hide-x {{
      position: absolute; top: 2px; right: 0;
      border: 0; background: none; cursor: pointer; color: var(--ab-fg-3);
      font-size: 1.1rem; line-height: 1; padding: 2px 7px; border-radius: 5px;
      opacity: 0; transition: opacity 120ms ease, color 120ms ease, background 120ms ease;
      /* Invisible must also mean UNCLICKABLE. At opacity:0 this still swallowed
         clicks, so aiming at the event name in the top-right of a cluster hit the
         hidden ✕ instead and made the whole block disappear rather than opening
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
    /* Solo trip (nothing tracked to batch) — a quiet note while we auto-scan. */
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
    /* ── My Profile view (bio, topics, past talks, files, notes) ───── */
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
    /* One speaking-material slot (Headshot / Slides / Bio & one-pagers / …). */
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
    /* Download icon — the ONLY thing that downloads a file now. */
    .profile-file-dl {{
      display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
      width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
      color: var(--ab-fg-3); background: var(--ab-bg); border: 1px solid var(--ab-rule);
      transition: color 120ms ease, border-color 120ms ease;
    }}
    .profile-file-dl svg {{ width: 15px; height: 15px; }}
    .profile-file-dl:hover {{ color: var(--ab-blue); border-color: var(--ab-blue); }}
    /* Rename-a-link (pencil) — same icon-button shape as download. */
    .profile-file-ren {{
      display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
      width: 30px; height: 30px; border-radius: 6px; cursor: pointer;
      color: var(--ab-fg-3); background: var(--ab-bg); border: 1px solid var(--ab-rule);
      transition: color 120ms ease, border-color 120ms ease;
    }}
    .profile-file-ren svg {{ width: 14px; height: 14px; }}
    .profile-file-ren:hover {{ color: var(--ab-blue); border-color: var(--ab-blue); }}
    /* Delete-a-file button — clearly a delete: trash icon + label, reddens on hover. */
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
    /* Full LinkedIn URL, right under the name — copy/paste-ready for Angela. */
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

    /* ── Planner view (conflicts + coverage gaps) ─────────────────── */
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
    /* Map view — Leaflet canvas, lazy-loaded on first open. */
    .ops-map {{ display: none; }}
    .ops-map.show {{ display: block; }}
    #ops-map-canvas {{
      height: 640px; border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg-2);
    }}
    /* Click a pin → events slide into this right-hand panel (Angela-style). */
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
    .map-sb-ev.past {{ opacity: 0.5; }}      /* past event — grayed, sorted below upcoming */
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
    /* Calendar month nav: ‹ prev on the left, month/year dropdown centered,
       next › on the right. The grid columns keep the dropdown truly centered. */
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
       event is ONE element spanning its day columns — genuinely contiguous,
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

    /* Calendar legend — shows status-group color meanings under the grid */
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

    /* Toolbar with + Add event — pastel-icon style adopted from joes-fac.
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
    /* Color variants — pastel bg + saturated text + slightly-darker hover bg */
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
    /* Ask AI — a gentle gradient accent so it reads as the smart assistant. */
    .ab-btn.ab-btn--ask {{
      background: linear-gradient(90deg, #eef2ff, #faf5ff); color: #6d28d9;
      border: 1px solid #ddd6fe; font-weight: 600;
    }}
    .ab-btn.ab-btn--ask:hover {{ background: linear-gradient(90deg, #e0e7ff, #f3e8ff); }}
    /* "+ Add" dropdown — the three add paths (manual / find new / paste email)
       folded behind one primary button. */
    .ops-add-wrap {{ position: relative; display: inline-block; }}
    .ab-btn__caret {{ width: 14px; height: 14px; flex-shrink: 0; margin-left: -2px; opacity: 0.85; }}
    #add-menu-btn[aria-expanded="true"] .ab-btn__caret {{ transform: rotate(180deg); }}
    .ops-add-menu {{
      position: absolute; top: calc(100% + 6px); left: 0; z-index: 40;
      min-width: 248px; padding: 6px;
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
    /* Chat panel */
    .ask-log {{ display: flex; flex-direction: column; gap: 10px; max-height: 420px; overflow-y: auto; margin: 4px 0 12px; }}
    .ask-msg {{ padding: 10px 13px; border-radius: 10px; font-size: 0.92rem; line-height: 1.5; max-width: 85%; white-space: pre-wrap; }}
    .ask-msg.user {{ align-self: flex-end; background: var(--ab-fg); color: var(--ab-bg); }}
    .ask-msg.ai   {{ align-self: flex-start; background: var(--ab-bg-3); color: var(--ab-fg); border: 1px solid var(--ab-rule); }}
    .ask-msg.ai a {{ color: var(--ab-blue, #1d4ed8); }}
    /* Recommended event cards returned under an AI answer — clickable, ranked. */
    .ask-cards {{ align-self: stretch; max-width: 100%; display: flex; flex-direction: column; gap: 7px; margin: 2px 0 2px; }}
    .ask-card {{
      display: block; width: 100%; text-align: left; cursor: pointer;
      border: 1px solid var(--ab-rule-strong); border-radius: 9px;
      background: var(--ab-bg); color: var(--ab-fg);
      padding: 9px 11px; font-family: var(--ab-sans); position: relative;
    }}
    .ask-card:hover {{ background: var(--ab-bg-3); border-color: var(--ab-fg-3); }}
    .ask-card .rank {{
      position: absolute; top: 9px; right: 10px; font-family: var(--ab-mono);
      font-size: 0.64rem; color: var(--ab-fg-3); letter-spacing: 0.06em;
    }}
    .ask-card .ac-name {{ font-weight: 600; font-size: 0.9rem; line-height: 1.3; padding-right: 26px; }}
    .ask-card .ac-meta {{ font-size: 0.78rem; color: var(--ab-fg-2); margin-top: 3px; }}
    .ask-card .ac-tags {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }}
    .ask-card .ac-tag {{
      font-family: var(--ab-mono); font-size: 0.62rem; letter-spacing: 0.04em;
      padding: 2px 7px; border-radius: 3px; border: 1px solid var(--ab-rule);
      background: var(--ab-bg-2); color: var(--ab-fg-2);
    }}
    .ask-card .ac-tag.buyer {{ background: #ecfdf5; color: #047857; border-color: #a7f3d0; }}
    .ask-card .ac-tag.worth {{ background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }}
    .ask-card .ac-tag.pri-high   {{ background: #166534; color: #fff; border-color: #166534; }}
    .ask-card .ac-tag.pri-medium {{ background: #fef3c7; color: #92400e; border-color: #fde68a; }}
    .ask-card .ac-tag.pri-low    {{ background: var(--ab-bg-3); color: var(--ab-fg-3); border-color: var(--ab-rule); }}
    /* Reasoning under the ranked cards — small + muted so cards stay the headline. */
    .ask-note {{
      margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--ab-rule);
      font-size: 0.82rem; line-height: 1.5; color: var(--ab-fg-2);
    }}
    .ask-note a {{ color: var(--ab-blue, #1d4ed8); }}
    /* A conversational reply (specific event / how-to / chat) — the prose is the
       headline; any single event card sits below it. */
    .ask-prose {{ font-size: 0.92rem; line-height: 1.55; color: var(--ab-fg); }}
    .ask-prose a {{ color: var(--ab-blue, #1d4ed8); }}
    .ask-prose + .ask-cards {{ margin-top: 10px; }}
    .ask-forrow {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 10px; }}
    .ask-for-label {{ font-family: var(--ab-mono); font-size: 0.62rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ab-fg-3); margin-right: 2px; }}
    .ask-for-chip {{ font-size: 0.78rem; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-2); cursor: pointer; }}
    .ask-for-chip:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .ask-for-chip.is-on {{ background: #7c3aed; color: #fff; border-color: #7c3aed; }}
    .ask-examples {{ display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }}
    .ask-chip {{ font-size: 0.8rem; padding: 6px 11px; border-radius: 999px; border: 1px solid var(--ab-rule-strong); background: var(--ab-bg); color: var(--ab-fg-2); cursor: pointer; }}
    .ask-chip:hover {{ background: var(--ab-bg-3); color: var(--ab-fg); }}
    .ask-inputrow {{ display: flex; gap: 8px; }}
    .ask-inputrow input {{ flex: 1; padding: 11px 13px; border: 1px solid var(--ab-rule-strong); border-radius: 8px; font-family: var(--ab-sans); font-size: 0.95rem; background: var(--ab-bg); color: var(--ab-fg); }}
    /* Pressed state while a feature's panel is open — click again to close. */
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

    /* Row 1 — primary nav: underlined text tabs on the left; the tracked/manual
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
    /* Results header — the tracked/manual count sits above the grid. */
    .ops-results-header {{
      display: flex; align-items: center; justify-content: flex-end;
      gap: 10px; margin: 0 0 16px;
    }}
    .ops-results-header .ops-count {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
    }}
    /* "Review duplicates" toggle — clickable, so it follows the underlined-pill
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
    /* The event a duplicate was matched AGAINST — shown alongside it in review
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
    .add-event-card h3 {{ padding-right: 40px; }}   /* clear the × */
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

    /* ───────────── responsive ───────────── */
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
        <img src="arcticblue-logo.png" alt="ArcticBlue" width="32" height="29">
      </a>
      <h1 class="app-title">ArcticBlue Event Tracker</h1>
      <div class="nav-meta"><span id="ab-today">{last_updated.upper()}</span> <span class="who">· <span class="who-switcher" id="who-switcher"></span></span></div>
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
        <p class="today-meta">{e(first_today.get("location",""))} · {e(first_today.get("type",""))}</p>
        {f'<p class="today-why">{e(first_today.get("why",""))}</p>' if first_today.get('why') else ''}
      </div>
    </section>'''
    elif next_up:
        days_to_next = (next_up['_start'] - TODAY).days
        today_section = f'''
    <section class="today-block">
      <div class="today-card">
        <div class="today-card-head">
          <p class="today-label">No events today · Next up in {days_to_next} day{"s" if days_to_next != 1 else ""}</p>
          <p class="today-date">{e(fmt_date(next_up))}</p>
        </div>
        <h2 class="today-name">{e(next_up["name"])}</h2>
        <p class="today-meta">{e(next_up.get("location",""))} · {e(next_up.get("type",""))} · Priority: {e(next_up.get("priority","Medium"))}</p>
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
        <p class="section-count">{upcoming_count} events · sorted by date</p>
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

    # (The old public "Archive · N past events" <details> block was built here
    # and never rendered — the public catalog view was retired. Removed rather
    # than left to rot: it was also the last place calling PAST events an
    # "archive", which now means one thing only — an event you archived.)

    foot = f'''
    <div class="panel" id="panel-angela" role="tabpanel" data-tab="angela" aria-labelledby="tab-angela">

      <!-- Preloaded ArcticBlue speakers — referenced by every speaker input
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

      <!-- State 1 · loading session -->
      <div id="angela-loading" class="alert">Loading your session…</div>

      <!-- State 2 · not signed in -->
      <div id="angela-signin" class="angela-card" hidden>
        <h2>Sign in to edit</h2>
        <p class="lede">Editing is restricted to ArcticBlue team members. Enter your work email and we'll send a one-time sign-in link.</p>
        <form id="signin-form" novalidate>
          <label for="signin-email">Work email</label>
          <input type="email" id="signin-email" placeholder="you@arcticblue.ai" required autocomplete="email">
          <button type="submit" class="primary" id="signin-submit">Send magic link</button>
        </form>
        <p class="mono-foot">Read access stays open to everyone · Only allow-listed emails can edit</p>
      </div>

      <!-- State 3 · magic-link sent -->
      <div id="angela-signin-sent" class="alert" hidden>
        Check your inbox — we sent a sign-in link to <strong id="signin-sent-to"></strong>. Click it on this device to come back here signed in.
      </div>

      <!-- State 4 · signed in but not on allow-list -->
      <div id="angela-unauth" class="alert warn" hidden>
        You're signed in as <strong id="unauth-email"></strong>, but this email isn't on the editor list. Read access is fine; ask Hurley to add you to <code>allowed_editors</code> if you need to edit.
        <button class="inline" id="signout-unauth">Sign out</button>
      </div>

      <!-- The collaborative tracker — open to everyone, no login. -->
      <div id="angela-ops" hidden>
        <div id="ops-status" class="alert" hidden></div>
        <div class="ops-controls-row">
        <div class="view-toggle" role="tablist" aria-label="View">
          <button type="button" role="tab" data-view="myevents" class="active" aria-selected="true">My lineup<span class="vt-count" id="vt-myevents-count" hidden></span></button>
          <button type="button" role="tab" id="tab-events" data-events-tab aria-selected="false">Events</button>
          <button type="button" role="tab" data-view="queue"    aria-selected="false">Queue<span class="vt-count" id="vt-queue-count" hidden></span></button>
          <button type="button" role="tab" data-view="planner"  aria-selected="false">Planner<span class="vt-count" id="vt-planner-count" hidden></span></button>
        </div>
        <div class="ops-controls-right">
            <span class="ops-navcount" id="ops-count"></span>
            <div class="ops-toolbar-group" role="group" aria-label="Sync and export" id="ops-sync-group">
              <span class="ops-toolbar-label">Sync</span>
              <button class="ab-btn ab-btn--ghost ab-btn--rose" id="ical-subscribe-btn" title="One auto-updating feed for Google Calendar, Apple Calendar or Outlook — plus a one-time .ics download">
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
                <button class="ops-add-item" id="paste-email-btn" role="menuitem" type="button">
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
          <button type="button" class="tf-toggle" id="ops-filter-toggle" aria-haspopup="true" aria-expanded="false" aria-controls="tf-drawer" title="More filters — region, months, pipeline and more" aria-label="More filters">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/></svg>
            <span class="tf-dot" id="tf-active-count" hidden></span>
          </button>
          <input type="search" id="ops-search" placeholder="Search events" aria-label="Search events">
          <button class="ab-btn ab-btn--ask" id="ask-ai-btn" title="Ask the AI to analyse and rank the events currently in view — e.g. 'which of these should I attend in September?'">
            <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .962 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.962 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/></svg>
            Ask Anything
          </button>
        </div>
        <div class="tf-drawer" id="tf-drawer" hidden>
          <div class="filter-dd" id="filter-pipeline" title="Pipeline stage — where each event stands (pick several to combine)">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Pipeline</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- stage chips injected by buildStageFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-region" title="Region (pick several to combine)">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Region</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- region chips injected by buildRegionFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-fits" title="Show events matching a teammate's target profile (geography, audience, industry, themes)">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Fits</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"></div>
          </div>
          <div class="filter-dd" id="filter-months" title="Show only events in the months you pick (pick several to combine)">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Months</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- month chips injected by buildMonthsFilter() --></div>
          </div>
          <div class="filter-dd" id="filter-should" title="Should Attend — team hand-picks + AI recommendations">
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
          <label class="ops-filter-chip" title="Show only events at the Submitted stage — a speaker application is in"><input type="checkbox" id="ops-f-submitted">Submitted</label>
          <label class="ops-filter-chip" title="Show only events added in the last 7 days (incl. AI-discovered) — the new batch to triage"><input type="checkbox" id="ops-f-recent">Recently added</label>
        </div>
        <p class="ops-active-filters" id="ops-active-filters" hidden></p>
        <div class="ops-results-header" id="ops-results-header">
          <button type="button" class="ops-dupe-review" id="ops-dupe-review" title="Show the auto-detected duplicate events so you can delete them (open one, then Details → Edit → Delete this event)" hidden></button>
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
        <div class="ops-queue" id="ops-queue"></div>
        <div class="ops-planner" id="ops-planner"></div>
        <div class="ops-dayof" id="ops-dayof"></div>
      </div>

    </div><!-- /panel-angela -->
  </main>

  <!-- ── Expanded pop-up (modal) for a single event ─────────────────── -->
  <div id="event-modal" class="modal-overlay" hidden>
    <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-topbar">
        <div id="modal-head-left"></div>
        <div id="modal-head-side"></div>
        <button type="button" class="modal-close" id="modal-close" aria-label="Close">×</button>
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
// ── Sole view: the Event Tracker is the only panel (Public view retired). ──
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

// ── Expanded pop-up (modal) for an event ──────────────────────────────
// Clicking any catalog card (public page) or a "Details" affordance in the
// For-Angela tab opens this. The event website link lives INSIDE the modal
// now — the card itself is no longer a whole-card link.
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
  // The ArcticBlue speaker roster — drives the "Interested" picker.
  var AB_ROSTER = ['Thor', 'Verma', 'Jerome', 'Joe', 'Scott', 'Carlos', 'Jim'];
  // Persona single-source-of-truth (config/personas.json), baked in. Global so
  // both the modal (attendees picker) and the ops views (Day-Of) read it.
  window.AB_PERSONAS = {PERSONAS_JS}.personas;

  function esc(s) {{
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }}
  // ── One clock for the whole app: New York ────────────────────────────
  // "Today" was three different things — the build machine's UTC date baked
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
  // Effective card priority (High / Medium / Low). "Like the data before" — it
  // starts from the stored priority (event_state override, else catalog/manual
  // base) — then folds in two live signals so the badge reflects what we
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
    // Only count a number that's actually a PRICE — tied to a currency symbol or
    // code. Otherwise attendee counts ("32,000"), years ("2026"), etc. get read
    // as prices, so "Price known" showed events with no real price.
    var clean = s.replace(/,/g, ''), nums = [], x;
    var re = /(?:[$£€]\\s?(\\d{{2,6}}(?:\\.\\d+)?))|(?:(\\d{{2,6}}(?:\\.\\d+)?)\\s?(?:usd|eur|gbp|dollars?|euros?|pounds?))/g;
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
  // link in a detail field (Speaking route, Contact info, …) be clickable, not
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
  // card look filled in when it isn't (Hurley 2026-07-29) — an absent row reads
  // better than a row that says nothing.
  var _MODAL_JUNK = /^(unknown|tbd|tba|n\/?a|none|null|not\s+(verified|specified|published|available|listed|confirmed|known)|no\s+information|to\s+be\s+(confirmed|announced))\.?$/i;
  function _modalJunk(v) {{ return _MODAL_JUNK.test(String(v == null ? '' : v).trim()); }}
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
    if (!html) val = _deAudience(val);
    return '<div class="modal-field"><span class="k">' + esc(label) + '</span>' +
           '<span class="v">' + (html ? val : _linkifyEsc(esc(val))) + '</span></div>';
  }}
  // Value with NO key label — for a field whose section heading already names it.
  // Notes was printing "Notes" twice (the zone heading, then the field key).
  function fieldBare(val) {{
    if (val == null || String(val).trim() === '') return '';
    if (_modalJunk(val)) return '';
    val = _deAudience(val);
    return '<div class="modal-field"><span class="v">' + _linkifyEsc(esc(val)) + '</span></div>';
  }}

  // Buyer-rich / audience mix is a targeting judgement, not a fact about the
  // event: it's Verma's signal (regulated-industry board rooms) and Angela's
  // triage tool. Nobody else sees it — in the read view OR the editor, which is
  // where it was still leaking to Thor (Hurley 2026-07-29). The assistant is
  // held to the same rule server-side in api/ask.py.
  function seesAudience() {{
    var me = ((window.opsCurrentUser ? window.opsCurrentUser() : '') || '')
      .trim().toLowerCase().split(/\\s+/)[0];
    return me === 'verma' || !!(window.isAngelaUser && window.isAngelaUser());
  }}

  // ── Who attends: one list, not two overlapping ones ──────────────────
  // "Typical attendees" and "Past / announced speakers" described the same room
  // from two angles and repeated each other — the same CIOs and CDOs listed
  // twice, padded out with entries that carry no information at all ("Technology
  // Leader, Global Enterprise") — so they're merged for display (Hurley
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
    // The separators these fields actually use — semicolons, bullets, newlines
    // and sentence breaks. NOT commas: "CIO, Major Enterprise" is one entry.
    var parts = raw.split(/\\s*(?:;|\\u00b7|\\u2022|\\n|\\.\\s)\\s*/);
    var out = [], kept = [];
    for (var i = 0; i < parts.length && out.length < 6; i++) {{
      var s = parts[i].replace(/^[\\s,.;:·•\\-]+/, '').replace(/[\\s,.;:·•\\-]+$/, '');
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
      // "CDOs, CAIOs, CTOs, CIOs…" is the same person described again.
      var haveWords = {{}};
      kept.forEach(function (have) {{ have.forEach(function (w) {{ haveWords[w] = 1; }}); }});
      var fresh = sig.filter(function (w) {{ return !haveWords[w]; }});
      if (haveWords[sig[0]] && fresh.length < 3) continue;
      kept.push(sig);
      out.push(s);
    }}
    return out.join('; ');
  }}
  // One short clause — used to fold "Meetings & networking" into the overview
  // rather than giving a format note a section heading of its own.
  function briefClause(v) {{
    var s = String(v == null ? '' : v).trim().replace(/\\s+/g, ' ');
    if (!s || _modalJunk(s)) return '';
    // These arrive as semicolon lists mixing real formats with non-answers
    // ("attendee app not verified; invite-only stream; innovation clinics").
    // Take the first clause that actually states something, not blindly the
    // first one, and never a pipe-joined blob.
    var parts = s.split(/\\s*[;|]\\s*|\\.\\s+/);
    var pick = '';
    for (var i = 0; i < parts.length; i++) {{
      var t = parts[i].replace(/[.;,\\s]+$/, '').trim();
      if (!t || _modalJunk(t)) continue;
      if (/\\bnot\\s+(verified|specified|published|available|listed|confirmed|known)\\b/i.test(t)) continue;
      pick = t; break;
    }}
    if (!pick) return '';
    if (pick.length > 140) pick = pick.slice(0, 137).replace(/\\s\\S*$/, '') + '…';
    return pick;
  }}

  // ── Editable modal: one-tap quick actions ──────────────────────────
  // Should-Attend has TWO sources that must NOT blur together (Angela: the 256
  // AI auto-tags were muting the handful Thor/Verma/Jerome flag by hand):
  //   human  -> attend_verdict = 'Worth attending'          (a teammate flagged it)
  //   ai     -> attend_verdict = 'Worth attending (AI)'     (the recommend pass)
  // Returns 'human' | 'ai' | null.
  // Global — shared between this modal scope and the separate ops closure
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
    var bStage = [];
    bStage.push('<button type="button" class="qa' + (has('Submitted') ? ' on' : '') + '" data-qa="submitted">' + (has('Submitted') ? '✓ Submitted' : 'Submitted') + '</button>');
    bStage.push('<button type="button" class="qa' + (has('Followed up') ? ' on' : '') + '" data-qa="followed-up">' + (has('Followed up') ? '✓ Followed up' : 'Followed up') + '</button>');
    bStage.push('<button type="button" class="qa' + (has('Booked') ? ' on' : '') + '" data-qa="booked">' + (has('Booked') ? '✓ Booked' : 'Booked') + '</button>');
    bStage.push('<button type="button" class="qa qa-neg' + (has('Rejected') ? ' on' : '') + '" data-qa="rejected" title="Rejected to speak — the organizer passed. Angela can flag it so the team can opt to just attend.">' + (has('Rejected') ? '✓ Rejected' : 'Rejected') + '</button>');
    // "Attending" is PER-PERSON: it reflects whether the signed-in person is in
    // the attendees list (Thor sees it off when only Jerome attends). Clicking it
    // adds/removes YOU. Angela assigns anyone via the edit-form Attending bubbles.
    var _meKey = ((window.opsCurrentUser ? window.opsCurrentUser() : '') || '').trim().split(/\\s+/)[0].toLowerCase();
    var _iAmAttending = !!(_meKey && (rec.attendees || []).some(function (a) {{ return String(a).toLowerCase() === _meKey; }}));
    bStage.push('<button type="button" class="qa' + (_iAmAttending ? ' on' : '') + '" data-qa="attending" title="Attending is per-person — this marks whether YOU are going">' + (_iAmAttending ? '✓ Attending' : 'Attending') + '</button>');
    // Should Attend is Angela's triage tool — only she sees/sets it here. For
    // everyone else, marking Interested funnels into her Should-Attend list.
    if (window.isAngelaUser && window.isAngelaUser()) {{
      // Angela can flag Should-Attend FOR a named person (Hurley 2026-07-30).
      // Operationally that IS the person saying "apply for me": it belongs in
      // her Queue and should drop off that person's Planner. Both already
      // happen for anyone on `interested` — queueItems() keys on it and
      // _suggestionsFor() skips events you're already flagged on — so this
      // writes the same list rather than inventing a parallel field.
      // Order is how often they actually go on stage.
      var _saOn = (rec.interested || []).filter(Boolean);
      var _saHas = function (n) {{ return _saOn.some(function (x) {{ return String(x).toLowerCase() === n.toLowerCase(); }}); }};
      var _saPicked = SA_PEOPLE.filter(_saHas);
      var _saLabel = _saPicked.length
        ? '✓ Should Attend — ' + esc(_saPicked.join(', '))
        : (_saKind === 'human' ? '✓ Should Attend' : 'Should Attend');
      var _saMenu = SA_PEOPLE.map(function (n) {{
        return '<button type="button" class="sa-pick' + (_saHas(n) ? ' on' : '') +
               '" data-sa-for="' + esc(n) + '">' + (_saHas(n) ? '✓ ' : '') + esc(n) + '</button>';
      }}).join('');
      bStage.push('<span class="qa-sa-wrap">' +
        '<button type="button" class="qa' + ((_saKind === 'human' || _saPicked.length) ? ' on' : '') + '" data-qa="should-attend" title="' +
        (_saKind === 'ai' ? 'AI-suggested — click to confirm as a team Should-Attend' : 'Flag Should Attend — tentative but high on the radar') + '">' +
        _saLabel + '</button>' +
        '<span class="qa-sa-menu" role="group" aria-label="Flag Should Attend for">' +
          '<span class="sa-menu-h">Should attend &mdash; for</span>' + _saMenu +
          // The old blanket flag, kept for "worth attending, nobody named yet".
          '<button type="button" class="sa-pick sa-pick-team' + (_saKind === 'human' ? ' on' : '') +
            '" data-sa-team="1">' + (_saKind === 'human' ? '\u2713 ' : '') + 'Team &mdash; no one specific</button>' +
        '</span></span>');
    }}
    // "Interested" — the current teammate adds themselves to the list of people
    // who want Angela to apply for them. This feeds Angela's Queue.
    var me = (window.opsCurrentUser ? window.opsCurrentUser() : '') || '';
    var iAmIn = !!(me && (rec.interested || []).some(function (n) {{ return String(n).toLowerCase() === me.toLowerCase(); }}));
    // Show the ACTUAL flagged list here (raw), matching the toggle button — using
    // the booked/attending-filtered visibleInterested() made the summary read
    // "No one flagged yet" right after someone (e.g. the speaker) clicked
    // Interested. The dedup still applies to the Planner/Queue + card-face label.
    //
    // The "No one flagged yet" placeholder is ANGELA-ONLY (Hurley 2026-07-29):
    // she runs the apply queue, so an empty interested list is information she
    // acts on. For everyone else it was just a line of nothing — no flags is the
    // normal state of most events, so the row now shows only the button.
    var summary = formatInterested(rec.interested);
    var _qbAngela = !!(window.isAngelaUser && window.isAngelaUser());
    var intBtn =
      '<button type="button" class="qa' + (iAmIn ? ' on' : '') + '" data-qa="interested">' + (iAmIn ? '✓ Interested' : "I'm interested") + '</button>';
    var intSummary = summary
      ? '<span class="qa-int-summary">' + summary + '</span>'
      : (_qbAngela ? '<span class="qa-int-summary qa-int-empty">No one flagged yet</span>' : '');
    // Archiving happens ONLY in this pop-up (the card face just shows an
    // "Archived" label), so the control is here for BOTH catalog and manual
    // events. Manual events also keep their separate "Delete this event" button
    // in the edit form.
    var _qbMan = rec._table === 'manual_events';
    var _qbArchivedMe = (window.opsIsArchivedForMe ? window.opsIsArchivedForMe(_qbMan, rec._key, rec.hidden === true) : !!rec.hidden);
    var hideBtn =
        '<button type="button" class="qa' + (_qbArchivedMe ? ' on' : '') + '" data-qa="archive" title="Archived for you only — teammates still see it">' + (_qbArchivedMe ? 'Unarchive' : 'Archive') + '</button>';
    // The "Status:" / "Interested:" / "Hide:" row labels are gone (Hurley
    // 2026-07-29) — the buttons say what they do, and the labels were reading as
    // a wall of headings. The rows stay on SEPARATE lines, with "I'm interested"
    // and Archive sharing the second one.
    return '<div class="modal-quickbar">' +
           '<div class="qa-row qa-row--status" style="align-items:center;">' + bStage.join('') + '</div>' +
           '<div class="qa-row qa-row--me" style="margin-top:6px;align-items:center;">' + intBtn + hideBtn + intSummary + '</div>' +
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
    bar.addEventListener('click', function (e) {{
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
          // human Should-Attend — same as when the person flags themselves.
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
      // "Team — no one specific" keeps the old blanket flag available.
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
      if (qa === 'saved') {{ rec.saved = !rec.saved; patch.saved = rec.saved; }}
      else if (qa === 'archive') {{
        // Archive is PERSONAL (localStorage per signed-in name) — hides this from
        // MY view only. No DB write unless we're clearing a legacy team-wide hide.
        var _isMan = rec._table === 'manual_events';
        var _wasArchived = (window.opsIsArchivedForMe ? window.opsIsArchivedForMe(_isMan, rec._key, rec.hidden === true) : !!rec.hidden);
        var _makeArch = !_wasArchived;
        if (window.opsSetArchivedMine) window.opsSetArchivedMine(_isMan, rec._key, _makeArch);
        // Unarchiving a legacy team-wide hide also clears that shared flag (it
        // comes back for everyone) — there's no per-person record to remove.
        if (!_makeArch && rec.hidden === true) {{ rec.hidden = false; patch.hidden = false; }}
      }}
      else if (qa === 'interested') {{
        var me = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || '';
        if (!me) return;  // no name entered — nothing to toggle
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
        if (att.length && !hadAtt) atags.push('Attending');
        else if (!att.length && hadAtt) atags.splice(atags.indexOf('Attending'), 1);
        var aOrder = window.opsStageOrder || [];
        if (aOrder.length) atags = aOrder.filter(function (s) {{ return atags.indexOf(s) !== -1; }});
        rec.stage_tags = atags;
        patch.status_tags = atags;
      }}
      else if (qa === 'submitted' || qa === 'followed-up' || qa === 'booked' || qa === 'rejected') {{
        var stage = qa === 'submitted' ? 'Submitted' : (qa === 'followed-up' ? 'Followed up' : (qa === 'booked' ? 'Booked' : 'Rejected'));
        var tags = (rec.stage_tags || []).slice();
        var idx = tags.indexOf(stage);
        if (idx === -1) tags.push(stage); else tags.splice(idx, 1);
        var order = window.opsStageOrder || [];
        if (order.length) tags = order.filter(function (s) {{ return tags.indexOf(s) !== -1; }});
        rec.stage_tags = tags;
        patch.status_tags = tags;
      }}
      else if (qa === 'should-attend') {{
        // human -> clear; AI-suggested OR none -> set a CONFIRMED human
        // Should-Attend (this is how Angela promotes an AI pick to the real list).
        var _k = shouldAttendKind(rec.attend_verdict);
        rec.attend_verdict = (_k === 'human') ? '' : 'Worth attending';
        patch.attend_verdict = rec.attend_verdict || null;
      }}
      else {{ return; }}
      // Optimistic: re-render the modal with the updated rec, preserving the
      // scroll position so quick edits don't jump the reader.
      var scEl = overlay.querySelector('.modal-scroll');
      var sc = scEl ? scEl.scrollTop : 0;
      // A personal archive toggle writes no DB patch — skip the empty upsert.
      if (Object.keys(patch).length) window.opsWrite(rec._table, rec._key, patch);
      openEventModal(rec);
      if (scEl) scEl.scrollTop = sc;
      // Archive lives in localStorage (no realtime echo), so re-render the grid
      // ourselves to move the card into / out of the per-person Hidden section.
      if (qa === 'archive' && window.opsRefresh) window.opsRefresh();
    }});
  }}

  // Edit form — mirrors the READ-ONLY field layout (same .modal-field rows /
  // labels / spacing) so edit mode looks just like view mode, only editable.
  // Each control saves to the right table (event_state by num / manual_events
  // by id) via window.opsWrite. Catalog edits write override columns.
  function editFormHtml(rec) {{
    if (!rec || !rec._table || rec._key == null) return '';
    var isCat = rec._table === 'event_state';
    function opt(v, cur) {{
      return '<option value="' + esc(v) + '"' + (String(cur || '') === v ? ' selected' : '') + '>' + (v || '—') + '</option>';
    }}
    function ef(label, control) {{
      // A single labelable control → wrap in <label> so the field name is
      // programmatically associated (and clicking it focuses the control).
      // Groups (stage chips, interested/attending checkboxes) carry their own
      // per-item <label>s, so wrap them as a named role="group" instead — never
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
    function statusDD(cur) {{
      var c = (cur === '__deleted__') ? '' : (cur || '');
      var opts = (window.opsStatusOptions) ? window.opsStatusOptions(c) : ('<option value="">\\u2014 none \\u2014</option>');
      return '<select class="me-input" data-edit="status">' + opts + '</select>';
    }}
    var stages = rec.stage_tags || [];
    var order = window.opsStageOrder || ['Submitted', 'Followed up', 'Meeting held', 'Booked', 'Attending'];
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
    // ArcticBlue speaker — bubbles (multi-select) from the roster, like Attending.
    var _spTok = String(rec.speaker || '').toLowerCase().split(/[,;/&]| and | plus /).map(function (s) {{ return s.trim(); }}).filter(Boolean);
    var spChips = AB_ROSTER.map(function (n) {{
      var on = _spTok.indexOf(n.toLowerCase()) !== -1;
      return '<label class="me-int' + (on ? ' on' : '') + '"><input type="checkbox" data-speaker="' + esc(n) + '"' + (on ? ' checked' : '') + '>' + esc(n) + '</label>';
    }}).join('');
    // Attending — bubbles from the roster (first names, no last names). The stored
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

    // Basics — what the card shows at a glance. Name / Date / Location are
    // editable on EVERY card: manual events store them directly, catalog events
    // as event_state overrides (needs scripts/2026-07-14_event_state_identity.sql
    // — until it runs, saving these three on a catalog event fails, while manual
    // events + every other catalog field keep working).
    h += sec('Basics',
      ef('Event name', inp('name', rec.name)) +
      ef('Date', inp('date_str', rec.date_str, 'e.g. Sept 14\\u201316, 2026')) +
      ef('Location', inp('location', rec.location)) +
      ef((isCat ? 'Website / link' : 'Website'), inp('url', rec.url, 'https://')) +
      ef('Private event', '<label class="me-toggle"><input type="checkbox" data-private' + (priv ? ' checked' : '') + '> Private / invite-only &mdash; hide the public-event fields, keep just POC, link, notes &amp; chat</label>'));

    // Notes — the most-used free-text field (159 of 627 events have one), so it
    // gets its own zone up top. The section header IS the label, hence the
    // aria-label instead of a duplicate visible one.
    h += sec('Notes',
      '<div class="modal-field"><textarea class="me-input" data-edit="notes" rows="4" aria-label="Notes">' + esc(rec.notes || '') + '</textarea></div>');

    // Speaking & submission — the pipeline zone.
    var sSpeak = ef('Pipeline stage', '<div class="me-stages">' + chips + '</div>');
    // "Submitted on" — Angela records the date the application went out. Only
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
      sSpeak += ef('Speaking route', ta('speaking_route', rec.speaking_route, 2));
      sSpeak += ef('Deadline', inp('deadline', rec.deadline, 'e.g. July 10, 2026'));
      // How we'd get in, in one place: is it pay-to-play, and the legacy status
      // marker (Sponsorship Only, Curated invite, ...). ONE dropdown for both
      // catalog and manual — Angela hit two edit sections that disagreed.
      sSpeak += ef('Pay-to-play', '<select class="me-input" data-edit="pay_to_play">' + p2p.map(function (v) {{ return opt(v, rec.pay_to_play); }}).join('') + '</select>');
      sSpeak += ef('Status marker (e.g. Sponsorship Only)', statusDD(rec.workflow_status));
    }}
    h += sec('Speaking & submission', sSpeak);

    // Attending & team — who from ArcticBlue is going / interested / assigned.
    var sTeam = ef('Attending \\u2014 surfaces a Day-Of brief', '<div class="me-ints">' + attChips + '</div>') +
                ef('Interested (joins Angela\\'s apply queue)', '<div class="me-ints">' + intChips + '</div>') +
                ef('Priority', '<select class="me-input" data-edit="' + (isCat ? 'priority_override' : 'priority') + '">' + pris.map(function (v) {{ return opt(v, curPri); }}).join('') + '</select>');
    // "Ask a teammate to reach out" — Angela assigns whoever has the personal
    // connection to the event; it surfaces at the top of that person's My
    // Lineup. Angela-only (it's her coordination tool).
    if (window.isAngelaUser && window.isAngelaUser()) {{
      var _outr = (rec.outreach_assignees || []).map(function (x) {{ return String(x).toLowerCase(); }});
      var outrChips = AB_ROSTER.map(function (n) {{
        var on = _outr.indexOf(n.toLowerCase()) !== -1;
        return '<label class="me-int' + (on ? ' on' : '') + '"><input type="checkbox" data-outreach="' + esc(n.toLowerCase()) + '"' + (on ? ' checked' : '') + '>' + esc(n) + '</label>';
      }}).join('');
      sTeam += ef('Ask a teammate to reach out \\u2014 they may have a connection', '<div class="me-ints">' + outrChips + '</div>');
      sTeam += ef('Who to reach / why them (optional)', inp('outreach_note', 'conflict_note', rec.outreach_note, 'e.g. you know their Head of Events'));
      // A conflict the DATES can't reveal — a board meeting, a holiday, a
      // trip that makes this unreachable. Overlapping events are detected
      // automatically; this is for everything else (Hurley 2026-07-30).
      sTeam += ef('Scheduling conflict (optional)', inp('conflict_note', rec.conflict_note, 'e.g. Thor is at the board offsite that week'));
    }}
    h += sec('Attending & team', sTeam);

    // Contacts — everything you'd search a person by. Kept for private events
    // too: the POC is the whole point of a private event.
    var sContact = ef('Contact info', inp('contact_info', rec.contact_info));
    if (!isCat) {{
      sContact += ef('POC name', inp('poc_name', rec.poc_name));
      sContact += ef('POC email', inp('poc_email', rec.poc_email));
    }}
    h += sec('Contacts', sContact);

    // Event details — the reference facts, mostly filled by the nightly enrich.
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

    // Rarely used — real fields that are essentially never filled in (Track is
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
        var tags = (rec.stage_tags || []).slice();
        var i = tags.indexOf(s);
        if (i === -1) tags.push(s); else tags.splice(i, 1);
        var ord = window.opsStageOrder || [];
        if (ord.length) tags = ord.filter(function (x) {{ return tags.indexOf(x) !== -1; }});
        rec.stage_tags = tags;
        btn.classList.toggle('on');
        window.opsWrite(rec._table, rec._key, {{ status_tags: tags }});
        // The "Submitted on" date field rides with the Submitted stage.
        if (s === 'Submitted') {{
          var _sf = box.querySelector('.me-submitted-field');
          if (_sf) _sf.style.display = (tags.indexOf('Submitted') !== -1) ? '' : 'none';
        }}
      }});
    }});
    box.querySelectorAll('[data-interested]').forEach(function (cb) {{
      cb.addEventListener('change', function () {{
        var list = (rec.interested || []).slice();
        var n = cb.dataset.interested;
        var i = list.indexOf(n);
        if (cb.checked && i === -1) list.push(n);
        else if (!cb.checked && i !== -1) list.splice(i, 1);
        // de-dupe but keep everyone — don't drop non-roster collaborators
        // added via the quick-bar "+ I'm interested".
        list = list.filter(function (x, idx) {{ return list.indexOf(x) === idx; }});
        rec.interested = list;
        var lbl = cb.closest('.me-int'); if (lbl) lbl.classList.toggle('on', cb.checked);
        window.opsWrite(rec._table, rec._key, {{ interested: list }});
      }});
    }});
    // ArcticBlue speaker — multi-select bubbles. Collect the checked names (in
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
      }});
    }});
    // "Ask a teammate to reach out" bubbles — collect the checked first names
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
        // "pops back up" — e.g. deleting a stray website from Contact info didn't
        // stick. Write a '__cleared__' sentinel instead; the render merge treats it
        // as an explicit blank that WINS over the catalog value. (Manual events own
        // their columns outright, so null already clears them there.)
        var _CLEARABLE_CAT = {{ contact_info:1, why:1, about:1, focus_areas:1, typical_attendees:1, speaking_route:1, venue:1, pricing:1, past_speakers:1, meeting_formats:1, attendee_count:1, deadline:1 }};
        if (out === null && rec._table === 'event_state' && _CLEARABLE_CAT[field]) out = '__cleared__';
        if ((field === 'url' || field === 'apply_url') && out && !/^https?:\\/\\//i.test(out)) out = 'https://' + out;
        // "Paid" is a boolean column on manual_events — coerce the select value.
        if (field === 'paid') out = (val === 'true') ? true : (val === 'false' ? false : null);
        var patch = {{}}; patch[field] = out;
        // The sentinel goes to the DB, but the in-memory record shows a real blank.
        var _recVal = (out === '__cleared__') ? '' : out;
        if (field === 'priority_override') rec.priority = _recVal;
        else rec[field] = _recVal;
        // Editing the Date must ALSO update the structured start_date / end_date
        // — the card, calendar and iCal read those (they win over the free-text
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
    // Private-event toggle — persist, then re-render the modal so both the
    // read view and the edit form reflect the simplified (or full) layout.
    var privCb = box.querySelector('[data-private]');
    if (privCb) privCb.addEventListener('change', function () {{
      rec.is_private = privCb.checked;
      window.opsWrite(rec._table, rec._key, {{ is_private: privCb.checked }});
      if (window.openEventModal) window.openEventModal(rec);
    }});
    // Delete (manual events only) — lives at the bottom of the Edit form.
    var delBtn = box.querySelector('.me-delete');
    if (delBtn) delBtn.addEventListener('click', function () {{
      if (!window.confirm('Delete "' + (rec.name || 'this manual event') + '"? This cannot be undone.')) return;
      delBtn.disabled = true; delBtn.textContent = 'Deleting…';
      if (window.opsDelete) {{
        window.opsDelete(rec._table, rec._key).then(function (resp) {{
          if (resp && resp.error) {{ delBtn.disabled = false; delBtn.textContent = 'Delete this event'; return; }}
          if (window.closeEventModal) window.closeEventModal();
        }});
      }}
    }});
  }}

  // "Enrich" — POST the event to /api/enrich_one, which researches the gaps via
  // Perplexity + Exa and writes the fill-only-missing patch server-side. We then
  // merge the patch into rec and re-render so the new facts show immediately.
  function wireEnrichButton(rec) {{
    var btn = document.getElementById('modal-enrich-btn');
    if (!btn) return;
    btn.addEventListener('click', function () {{
      if (btn.getAttribute('aria-busy')) return;
      btn.setAttribute('aria-busy', '1');
      var prev = btn.innerHTML;
      btn.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">⏳</span> Enriching…';
      fetch('/api/enrich_one', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ event: rec, table: rec._table, key: rec._key }})
      }}).then(function (r) {{ return r.json(); }}).then(function (data) {{
        btn.removeAttribute('aria-busy'); btn.innerHTML = prev;
        if (!data || data.skipped) {{ window.alert("Enrichment isn't set up yet — no research API keys are configured on the server."); return; }}
        if (data.error) {{ window.alert('Enrichment failed: ' + (data.detail || data.error)); return; }}
        var filled = data.filled || [];
        var patch = data.patch || {{}};
        for (var k in patch) {{ if (Object.prototype.hasOwnProperty.call(patch, k)) rec[k] = patch[k]; }}
        openEventModal(rec);
        if (window.opsRefresh) window.opsRefresh();
        var note = filled.length
          ? '<div class="modal-enrich-note ok">&#10022; Enriched — filled: ' + esc(filled.join(', ')) + '</div>'
          : '<div class="modal-enrich-note">No new details found — everything we could fill is already here.</div>';
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

  function openEventModal(rec) {{
    if (!rec) return;
    // Top labels: cleared out (Hurley 2026-07-29). Priority, event type, the
    // pipeline stages, Pay-to-play, Seed and Private all repeated something the
    // reader already has — the stages are the Status buttons right below, and
    // priority / type / pay-to-play / private are on the card face they just
    // clicked through. The ONE exception is the legacy "Sponsorship Only"
    // marker: it's a real closed-stage outcome ("they'll take our money, not our
    // speaker") with no button of its own, so it still earns a label up top.
    var badges = [];
    if (/sponsorship\\s*only/i.test(String(rec.workflow_status || ''))) {{
      badges.push('<span class="badge p-low">' + esc(rec.workflow_status) + '</span>');
    }}
    $badges.innerHTML = badges.join('');

    $date.textContent  = rec.date_str || '';
    // A private / invite-only event has no public page — a scraped URL is almost
    // always the wrong page (Angela). Never link a private event's title; show
    // plain text so it can't "bring a fake link".
    if (rec.url && rec.is_private !== true) {{
      $title.innerHTML = '<a class="modal-title-link" href="' + esc(rec.url) + '" target="_blank" rel="noopener">' + esc(rec.name || 'Event') + '<span class="event-link-arrow" aria-hidden="true">↗</span></a>';
    }} else {{
      $title.textContent = rec.name || 'Event';
    }}
    // Just the city/venue — the region (MENA / Europe / …) is redundant next
    // to it and adds nothing a reader needs.
    $loc.innerHTML = esc(rec.location || '');

    var html = '';
    html += quickBarHtml(rec);
    // Team Discussion thread — right after the quickbar (Status/Interested/
    // Hide: Archive), ahead of the read-only detail fields.
    html += '<div class="event-chat" id="event-chat-panel"></div>';

    // Read-only view — grouped into the SAME labelled zones as the edit form
    // (Angela: "break it up and group them more logically, i.e. attendees
    // together"). sec() drops a zone whose body came back empty, so a sparse or
    // private event never shows a bare header. Same .me-sec markup as the editor
    // so both views get the identical divider treatment.
    // "Why it fits ArcticBlue" removed from the read view (Hurley 2026-07-09) —
    // still used by search/suggestions scoring.
    // A zone holding exactly ONE field doesn't need the field's label — the
    // heading is already naming that value, so printing both reads as two
    // headings stacked on one line of content ("Who attends" / "Typical
    // attendees", "About the event" / "About"). The heading wins: it carries
    // the divider styling (Hurley 2026-07-29). Two or more fields keep their
    // labels, since then the heading can't tell them apart.
    function sec(title, body) {{
      if (!body) return '';
      if ((body.match(/class="modal-field"/g) || []).length === 1) {{
        body = body.replace(/<span class="k">[\\s\\S]*?<\\/span>/, '');
      }}
      return '<section class="me-sec"><h4 class="me-sec-h">' + esc(title) + '</h4>' + body + '</section>';
    }}
    // Point of contact — the one detail that matters for a private event.
    // A contact is a PERSON: a name or an email. `contact_info` is very often
    // just the event's own domain ("ai4.io") or a registration URL, and the
    // section rendered that as "Contact info: ai4.io" — a Contacts heading over
    // something nobody can contact (Hurley 2026-07-30). opsContactText() is the
    // same test the card's ✉ badge uses: it strips URLs and bare domains and
    // returns what human-readable text is left, if any.
    var _ct  = window.opsContactText   || function (v) {{ return String(v == null ? '' : v).trim(); }};
    var _ctp = window.opsContactPerson || _ct;
    var contactBits = [];
    if (_ct(rec.poc_name))  contactBits.push(esc(rec.poc_name));
    if (rec.poc_email && String(rec.poc_email).indexOf('@') !== -1) {{
      contactBits.push('<a href="mailto:' + esc(rec.poc_email) + '">' + esc(rec.poc_email) + '</a>');
    }}
    if (rec.poc_linkedin) contactBits.push('<a href="' + esc(rec.poc_linkedin) + '" target="_blank" rel="noopener">LinkedIn ↗</a>');
    var pocHtml = (contactBits.length ? field('Point of contact', contactBits.join(' · '), true) : '') +
                  (_ctp(rec.contact_info) ? field('Contact info', rec.contact_info) : '');

    var v = '';
    // Notes lead the read view — right below "Chat with the team" (Angela). The
    // zone heading already says "Notes", so the value goes in bare.
    v += sec('Notes', fieldBare(rec.notes));
    // Follow-up log — Angela's spreadsheet column, as a clean dated list.
    // Angela always gets the section (she needs the log button even on an empty
    // one). Everyone else sees it only once there IS something to read: the
    // speakers want to know they've been chased for, not to be shown an empty
    // heading (Hurley 2026-07-30). Read-only for them — it's hers to run.
    var _fuMine = !!(window.isAngelaUser && window.isAngelaUser());
    var _fuList = window.abFollowUps ? window.abFollowUps(rec) : [];
    if (_fuMine || _fuList.length) {{
      var _fuSt = window.abFollowUpState
        ? window.abFollowUpState(rec, rec.stage_tags || [], '') : null;
      var _fuBody = '';
      // 'none' means no chase logged — that reads as noise on screen, so it
      // stays blank here. The fact still travels: the assistant is told
      // explicitly that nobody has chased it, so Thor gets it if he asks.
      if (_fuSt && _fuSt.state !== 'none') {{
        var _fuLab = _fuSt.label, _fuCls = _fuSt.state;
        // "Follow up now — 6 days since Jul 24" is Angela's worklist talking.
        // On a speaker's screen it reads as a job for HIM, so the chase-cadence
        // states become a plain statement of fact. Where we stand with the
        // ORGANISER (waiting on them, door closed) is his business and stays.
        if (!_fuMine && (_fuCls === 'due' || _fuCls === 'ok')) {{
          _fuLab = 'Last chased ' + _fuWhen(_fuSt.since || (_fuList[0] && _fuList[0].on));
          _fuCls = 'ok';
        }}
        _fuBody += '<div class="fu-state fu-' + _fuCls + '">' + esc(_fuLab) + '</div>';
      }}
      if (_fuList.length) {{
        // Oldest entry is the FIRST contact; everything after it is a chase.
        // Naming them that way is the whole point — Angela wants to see when
        // she reached out and when she followed up (Hurley 2026-07-30).
        var _fuOldest = _fuList.length - 1;
        _fuBody += '<ol class="fu-log">' + _fuList.map(function (f, i) {{
          var kind = (i === _fuOldest) ? 'Reached out' : 'Followed up';
          return '<li data-fu-i="' + i + '">' +
                 '<span class="fu-when">' + esc(_fuWhen(f.on)) + '</span>' +
                 '<span class="fu-kind">' + kind + '</span>' +
                 (f.by ? '<span class="fu-by">' + esc(f.by) + '</span>' : '') +
                 (_fuMine ? '<span class="fu-acts">' +
                   '<button type="button" class="fu-act" data-fu-edit="' + i + '" title="Edit this entry">edit</button>' +
                   '<button type="button" class="fu-act fu-act-del" data-fu-del="' + i + '" title="Delete this entry">delete</button>' +
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
                   // editable — you followed up on the 24th and log it on the
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
    if (rec.is_private) {{
      // Private / invite-only: just the speaker + POC (link is the title, chat above).
      v += sec('Speaking', field('ArcticBlue speaker', rec.speaker));
      v += sec('Contacts', pocHtml);
    }} else {{
      // — Speaking & submission: how we'd get on stage, and where we stand.
      //   The legacy status marker (e.g. "Sponsorship Only") is kept OFF the card
      //   face by design but belongs here so a saved marker is visible.
      v += sec('Speaking & submission',
        field('ArcticBlue speaker', rec.speaker) +
        field('Status marker', (function () {{
          var ws = rec.workflow_status;
          if (!ws || ws === '__deleted__') return '';
          // Rejected is terminal — a leftover legacy "Pending" marker would
          // contradict it, so it's suppressed (Hurley 2026-07-29).
          if (/^\\s*pending\\s*$/i.test(ws) && (rec.stage_tags || []).indexOf('Rejected') !== -1) return '';
          return ws;
        }})()) +
        field('Speaking route', rec.speaking_route) +
        field('Deadline', (window.opsDeadlineUsable && window.opsDeadlineUsable(rec.deadline, rec)) ? rec.deadline : '') +
        field('Pay-to-play', rec.pay_to_play) +
        field('Submission status', rec.submission_status) +
        field('Speaking fee', rec.speaking_fee));
      // — Who's in the room: every audience fact in one place.
      // One merged list — the heading already says who it's about, so the value
      // goes in bare rather than under a second "Typical attendees" label.
      v += sec('Who attends',
        fieldBare(mergeAttendees(rec.typical_attendees, rec.past_speakers)) +
        (function () {{
          // "Audience: Buyer-rich" is a targeting judgement, not a fact about
          // the event — it's Verma's signal (regulated-industry board rooms) and
          // Angela's for triage. Everyone else was reading a label that didn't
          // change what they'd do (Hurley 2026-07-29).
          var g = field('Attendee count', rec.attendee_count) +
                  (seesAudience() ? field('Audience', rec.audience_type) : '');
          return g ? '<div class="modal-grid">' + g + '</div>' : '';
        }})());
      // — Overview of the event itself. The meeting/networking format rides
      //   along here as one clause instead of claiming its own labelled row.
      v += sec('Overview',
        (function () {{
          var about = String(rec.about || '').trim();
          var fmt = briefClause(rec.meeting_formats);
          // Don't say it twice — enrichment sometimes works the format into the
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
      v += sec('Contacts', pocHtml + (_ctp(rec.additional_contacts) ? field('Additional contacts', rec.additional_contacts) : ''));
      // This zone only ever holds the one field, so under the one-field rule the
      // heading IS the label — which means it has to be the informative one.
      v += sec('Post-mortem (ROI)', field('Post-mortem (ROI)', rec.postmortem));
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
    wireEditForm(rec);
    if (window.opsRenderChat) window.opsRenderChat(rec);

    // Edit / delete a single entry. Editing keeps the ORIGINAL date — that's
    // when the contact actually happened — and stamps an `edited` date beside
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
          // The date is WHEN IT HAPPENED — it stays put unless she corrects it,
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
            '<button type="button" class="ab-btn-ghost" data-cancel>Keep</button>' +
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

    // "+ Log a follow-up" — records today's date against the signed-in name,
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
        // The date is never typed — it's today's, in New York, taken at the
        // moment of logging and written straight through to Supabase.
        var today = window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10);
        // Whatever day it happened on — never later than today.
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

    // "Edit event" toggle — header top-right, same spot for every event. It
    // swaps the read-only view for the (identically-laid-out) edit form.
    // Trash-can DELETE — top LEFT of the toolbar, and only while the editor is
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
      // "Enrich" — research missing details on demand (editable records only).
      var enrichBtn = (rec._table && rec._key != null)
        ? '<button type="button" class="qa-edit qa-enrich" id="modal-enrich-btn" title="Search the web to fill in missing details for this event"><span class="qa-edit-ic" aria-hidden="true">✦</span> Enrich</button>'
        : '';
      $side.innerHTML = enrichBtn + (editForm
        ? '<button type="button" class="qa-edit" id="modal-edit-toggle" aria-expanded="false"><span class="qa-edit-ic" aria-hidden="true">✎</span> Edit</button>'
        : '');
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
          et.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">✓</span> Done';
          if (del) del.removeAttribute('hidden');
        }} else {{
          form.setAttribute('hidden', ''); if (view) view.removeAttribute('hidden');
          et.classList.remove('on'); et.setAttribute('aria-expanded', 'false');
          et.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">✎</span> Edit';
          if (del) del.setAttribute('hidden', '');
        }}
      }});
    }}

    // Editing now lives in the top-right "Edit event" toggle; the footer just
    // links out to the event website.
    var actHtml = '';
    if (rec.url) {{
      actHtml += '<a class="modal-visit" href="' + esc(rec.url) + '" target="_blank" rel="noopener">Visit event website ↗</a>';
    }} else {{
      actHtml += '<span class="modal-nolink">No verified website URL on file.</span>';
    }}
    var _applyUrl = rec.apply_url || speakingRouteUrl(rec.speaking_route);
    if (_applyUrl && window.isAngelaUser && window.isAngelaUser()) {{
      actHtml += '<a class="modal-visit modal-apply" href="' + esc(_applyUrl) + '" target="_blank" rel="noopener">Apply to speak ↗</a>';
    }}
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
    // Chat forward / ⋯ menus are portaled onto <body>, so they don't die with
    // the modal on their own — an Esc-close leaves no click to fire their
    // click-away. Sweep them up here so none linger over the page.
    document.querySelectorAll('.chat-fwd-menu, .chat-more-menu').forEach(function (x) {{ x.remove(); }});
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }}
  window.openEventModal = openEventModal;
  // Focus trap shared by both overlays (modal here, briefing drawer in the ops
  // closure) — keeps Tab inside the dialog instead of walking the page behind.
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
  // Shared helpers — the ops tab lives in a SEPARATE closure, so these must
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
  // event — no need to apply for someone already going. Keeps everyone else.
  //
  // The speaker only counts as covered once the event is actually BOOKED. A name
  // in `speaker` with nothing booked is the person we INTEND to put forward — the
  // application still has to go out, so they belong in Angela's queue. This is
  // the same rule resolveAttendeeKeys uses for the Day-Of brief ("submitted is
  // not attending"). Without it, every event carrying a suggested speaker fell
  // out of the queue and the tab count was far lower than the real workload —
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

  // Public catalog cards: delegate clicks + keyboard activation.
  document.addEventListener('click', function (ev) {{
    var card = ev.target.closest ? ev.target.closest('.event.is-clickable') : null;
    if (!card) return;
    if (ev.target.closest('a')) return; // let real links inside cards work
    var rec = CATALOG[card.getAttribute('data-num')];
    if (rec) {{ ev.preventDefault(); openEventModal(rec); }}
  }});

  // For-Angela ops/manual cards: the "Details →" button carries a stashed
  // record (card._modalRec) so we can show the same rich pop-up.
  document.addEventListener('click', function (ev) {{
    if (!ev.target.closest) return;
    var card = ev.target.closest('.ops-card');
    if (!card || !card._modalRec) return;
    // The card's own controls keep their own click (star, Urgent/Archive, the
    // name/website link, Apply-to-speak, expandable contacts). A click anywhere
    // ELSE on the card opens the detail pop-up — the whole square is the button.
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

// ── Supabase wiring for "For Angela" tab ──────────────────────────────
// Auth: magic-link via Supabase Auth. Allow-list lives in the
// allowed_editors table; RLS gates writes server-side.
(function () {{
  var SUPABASE_URL = '{SUPABASE_URL}';
  var SUPABASE_KEY = '{SUPABASE_PUBLISHABLE_KEY}';

  // Wait for the deferred Supabase UMD script to attach window.supabase.
  // Hardened: the old version polled silently FOREVER, so a blocked/failed CDN
  // (ad-blocker, strict network) left the app on a blank loading state with no
  // clue. Now: ~5s → inject a fallback CDN; ~20s → tell the user (keep trying).
  function ready(cb) {{
    var polls = 0, injectedFallback = false, warned = false;
    (function poll() {{
      if (window.supabase && window.supabase.createClient) return cb();
      polls++;
      if (polls >= 100 && !injectedFallback) {{
        injectedFallback = true;
        var s = document.createElement('script');
        s.src = 'https://unpkg.com/@supabase/supabase-js@2/dist/umd/supabase.js';
        document.head.appendChild(s);
      }}
      if (polls >= 400 && !warned) {{
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
    // | 'buyer' | 'interested' | 'myfits') — click a top stat to show only those events.
    var opsStatFilter = '';
    var _userPickedStat = false;   // once the reader clicks any status chip, stop auto-defaulting to "My fits"
    // When true, the auto-detected duplicate cards are REVEALED (marked
    // "DUPLICATE") instead of hidden, so they can be opened + deleted in-app.
    var _reviewDupes = false;

    // Last-fetched data, cached by renderOps() so the Queue + Planner views can
    // render from the SAME set the grid just built (no extra fetch).
    var _lastEvs = [], _lastStateMap = {{}}, _lastStateRows = [], _lastManual = [];
    // Recent profile-material uploads (support only) → "In the last week" alerts.
    var _recentUploads = null, _recentUploadsLoading = false;
    // Roster used by the Planner's coverage-gap "Flag for X" action. (The modal
    // closure has its own AB_ROSTER; this closure needs its own copy.)
    var OPS_ROSTER = ['Thor', 'Joe', 'Jerome', 'Scott', 'Verma', 'Carlos', 'Jim'];
    // People who don't want Plan Ahead's month-by-month suggestion list
    // under Event Radar — the curated blocks above it are enough.
    var _PLAN_SUGGESTIONS_OFF = {{ thor: 1 }};

    // ── English-language gate for Thor / Verma / Joe ──────────────────────
    // They work the room and take the stage in English, so an event RUN in
    // Spanish / Portuguese / French / German / Italian ("Foro Digital
    // Iberoamericano") is not a fit for them however well the topic or city
    // scores (Hurley 2026-07-29). Jerome (Europe) and Carlos (Latin America)
    // are unaffected — their territories are exactly where those events are.
    //
    // Detected from the TITLE, which is the reliable proxy for the working
    // language. Deliberately NOT from the country: "Big Data & AI World Madrid"
    // is an English-language event in Spain and still counts for all three.
    var _ENGLISH_ONLY_PEOPLE = {{ thor: 1, verma: 1, joe: 1 }};
    // One of these is enough on its own — no English event title carries them.
    // Deliberately absent: words that are also English brand or venue names.
    // "Datos Insights" (the research firm) runs English events in London, "Messe
    // Frankfurt" and "Fiera Milano" are venues, and an "AI Salon" is an English
    // event format — so datos / dados / messe / fiera / salon sit in the weak
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
    // Weak signals — a place name, brand or venue can supply one on its own, so
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

    // ── Status taxonomy ────────────────────────────────────────────
    // Light-theme palette derived from Angela's existing Airtable-style
    // tags + her Replit app's wider vocabulary. Grouped by lifecycle
    // stage so the filter row reads top-to-bottom Confirmed → Closed.
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
      // ── Confirmed / scheduled ──
      {{ group: 'Confirmed', value: 'Booked',                                  dup: true, bg: '#047857', fg: '#ffffff' }},
      {{ group: 'Confirmed', value: 'Self Submitted',                          dup: true, bg: '#15803d', fg: '#ffffff' }},
      {{ group: 'Confirmed', value: 'Attending',                               dup: true, bg: '#a78bfa', fg: '#3730a3' }},
      {{ group: 'Confirmed', value: 'Attending (Not Speaking)',                dup: true, bg: '#c4b5fd', fg: '#4c1d95' }},
      {{ group: 'Confirmed', value: 'Attending?',                              dup: true, bg: '#ddd6fe', fg: '#5b21b6' }},
      // ── Active / in progress ──
      {{ group: 'Active',    value: 'Submitted',                               dup: true, bg: '#bbf7d0', fg: '#14532d' }},
      {{ group: 'Active',    value: 'Booking in Progress',                     dup: true, bg: '#86efac', fg: '#14532d' }},
      {{ group: 'Active',    value: 'In contact with',                         bg: '#d1fae5', fg: '#065f46' }},
      {{ group: 'Active',    value: 'In Progress',                             bg: '#fcd34d', fg: '#78350f' }},
      {{ group: 'Active',    value: 'Received Intro Meeting',                  dup: true, bg: '#a7f3d0', fg: '#064e3b' }},
      {{ group: 'Active',    value: 'Personal Contact/Inquiry',                bg: '#e9d5ff', fg: '#6b21a8' }},
      {{ group: 'Active',    value: 'Application Process Inquiry',             bg: '#dbeafe', fg: '#1e40af' }},
      {{ group: 'Active',    value: 'Pending',                                 bg: '#fef3c7', fg: '#854d0e' }},
      {{ group: 'Active',    value: 'Thor Contacting',                         bg: '#cffafe', fg: '#155e75' }},
      // ── Waiting on ──
      {{ group: 'Waiting',   value: 'Joined Waitlist',                         bg: '#c7d2fe', fg: '#3730a3' }},
      {{ group: 'Waiting',   value: 'Enrollment not open yet',                 bg: '#e5e7eb', fg: '#374151' }},
      {{ group: 'Waiting',   value: 'Registered for Speaker Updates',         bg: '#bfdbfe', fg: '#1e40af' }},
      {{ group: 'Waiting',   value: 'On Hold',                                 bg: '#fed7aa', fg: '#9a3412' }},
      {{ group: 'Waiting',   value: 'Postponed',                               bg: '#fb923c', fg: '#7c2d12' }},
      {{ group: 'Waiting',   value: 'Postponed?',                              bg: '#fdba74', fg: '#9a3412' }},
      // ── Needs action ──
      {{ group: 'Action',    value: 'Finish Submission',                       bg: '#fde047', fg: '#713f12' }},
      {{ group: 'Action',    value: 'Needed: Submit Session Topic',            bg: '#fef3c7', fg: '#92400e' }},
      {{ group: 'Action',    value: 'Late Inquiry',                            bg: '#fdba74', fg: '#7c2d12' }},
      {{ group: 'Action',    value: 'Get Invited',                             bg: '#fca5a5', fg: '#7f1d1d' }},
      {{ group: 'Action',    value: 'Thor Interested',                         bg: '#7dd3fc', fg: '#0c4a6e' }},
      {{ group: 'Action',    value: 'Verma Interested',                        bg: '#67e8f9', fg: '#155e75' }},
      // ── Closed ──
      {{ group: 'Closed',    value: 'No Openings',                             bg: '#111827', fg: '#ffffff' }},
      {{ group: 'Closed',    value: 'Not Accepted',                            dup: true, bg: '#dc2626', fg: '#ffffff' }},
      {{ group: 'Closed',    value: 'Not Accepted This Yr',                    dup: true, bg: '#ef4444', fg: '#ffffff' }},
      {{ group: 'Closed',    value: 'Skip',                                    bg: '#b91c1c', fg: '#ffffff' }},
      {{ group: 'Closed',    value: 'Passing',                                 bg: '#94a3b8', fg: '#1e293b' }},
      {{ group: 'Closed',    value: "We'll Pass",                              bg: '#cbd5e1', fg: '#475569' }},
      {{ group: 'Closed',    value: 'Not accepting External Company Speakers', bg: '#1f2937', fg: '#ffffff' }},
      {{ group: 'Closed',    value: 'Date Conflict',                           bg: '#475569', fg: '#ffffff' }},
      {{ group: 'Closed',    value: 'Sponsorship Only',                        bg: '#fda4af', fg: '#9f1239' }},
      {{ group: 'Closed',    value: '"Don\\u2019t call us, we call you"',      bg: '#fee2e2', fg: '#991b1b' }},
      // ── Other / placeholder ──
      {{ group: 'Other',     value: 'Not yet',                                 bg: '#e5e7eb', fg: '#374151' }},
      {{ group: 'Other',     value: "--- cc'd on Inquiry",                     bg: '#f3f4f6', fg: '#6b7280' }},
      {{ group: 'Other',     value: "--- cc'd on MTG",                         bg: '#f3f4f6', fg: '#6b7280' }}
    ];

    var STATUS_BY_VALUE = {{}};
    STATUS_OPTIONS.forEach(function (s) {{ STATUS_BY_VALUE[s.value] = s; }});
    var STATUS_GROUP_BY_KEY = {{}};
    STATUS_GROUPS.forEach(function (g) {{ STATUS_GROUP_BY_KEY[g.key] = g; }});

    function statusGroupDot(value) {{
      var s = STATUS_BY_VALUE[value];
      if (!s) return null;
      var g = STATUS_GROUP_BY_KEY[s.group];
      return g ? g.dot : null;
    }}

    function statusStyle(value) {{
      var s = STATUS_BY_VALUE[value];
      if (!s) return '';
      return 'background:' + s.bg + ';color:' + s.fg + ';';
    }}

    function statusOptionRows(current) {{
      var rows = '<option value=""' + (!current ? ' selected' : '') + '>\\u2014 none \\u2014</option>';
      STATUS_OPTIONS.forEach(function (s) {{
        // Options flagged `dup` restate a Pipeline stage that already has its own
        // button (Submitted / Booked / Attending / …). Angela was recording the
        // same fact in two places, so they're no longer OFFERED here — but they
        // stay in STATUS_OPTIONS so existing values keep their colour, dot and
        // filter chip, and an event already set to one still shows it (below).
        if (s.dup && s.value !== current) return;
        var sel = (s.value === current) ? ' selected' : '';
        rows += '<option value="' + escapeHtml(s.value) + '"' + sel + '>' + escapeHtml(s.value) + '</option>';
      }});
      // If the current value isn't in our palette, surface it as a one-off
      // option so we don't silently overwrite legacy data when re-saved.
      if (current && !STATUS_BY_VALUE[current]) {{
        rows += '<option value="' + escapeHtml(current) + '" selected>' + escapeHtml(current) + '  (legacy)</option>';
      }}
      return rows;
    }}
    // Bridge for the Details editor (separate closure) — the legacy "Status
    // label" (incl. "Sponsorship Only") is a dropdown built from these options.
    window.opsStatusOptions = statusOptionRows;

    // ── Pipeline stages (the simplified, multi-tag status model) ───────
    // An event can hold SEVERAL of these at once (e.g. Submitted + Meeting
    // held + Booked). Stored in event_state.status_tags / manual_events
    // .status_tags (Postgres text[]). The old single `status` column is
    // kept as an optional granular "legacy" detail and still drives the
    // read-side fallback below for rows not yet migrated.
    //
    // Order here IS the canonical pipeline order (Identified → … → Booked),
    // with Attending as the alternate positive outcome.
    var STAGE_TAGS = [
      {{ key: 'Submitted',    dot: '#0ea5e9', bg: '#bae6fd', fg: '#075985' }},
      {{ key: 'Followed up',  dot: '#d97706', bg: '#fde68a', fg: '#92400e' }},
      {{ key: 'Meeting held', dot: '#8b5cf6', bg: '#ddd6fe', fg: '#5b21b6' }},
      {{ key: 'Booked',       dot: '#047857', bg: '#bbf7d0', fg: '#14532d' }},
      {{ key: 'Rejected',     dot: '#dc2626', bg: '#fecaca', fg: '#991b1b' }},
      {{ key: 'Attending',    dot: '#0d9488', bg: '#ccfbf1', fg: '#115e59' }}
    ];
    var STAGE_BY_KEY = {{}};
    STAGE_TAGS.forEach(function (s, i) {{ s.order = i; STAGE_BY_KEY[s.key] = s; }});
    // "Most important" ranking for a single calendar tint when an event
    // carries several stages: a win (Booked) trumps everything, then
    // Attending, then progress backwards.
    var STAGE_DISPLAY_RANK = ['Booked', 'Attending', 'Rejected', 'Meeting held', 'Followed up', 'Submitted', 'Identified'];

    function stageStyle(key) {{
      var s = STAGE_BY_KEY[key];
      if (!s) return '';
      return 'background:' + s.bg + ';color:' + s.fg + ';';
    }}
    function stageDot(key) {{
      var s = STAGE_BY_KEY[key];
      return s ? s.dot : null;
    }}

    // Keep only recognized stages, dedupe, return in canonical order.
    function normalizeStageTags(arr) {{
      if (!arr) return [];
      if (!Array.isArray(arr)) {{
        // Accept a pipe- or comma-joined string (CSV / older rows)
        arr = String(arr).split(/[|,]/);
      }}
      var seen = {{}};
      arr.forEach(function (v) {{
        var k = (v == null ? '' : String(v)).trim();
        if (STAGE_BY_KEY[k]) seen[k] = true;
      }});
      return STAGE_TAGS.filter(function (s) {{ return seen[s.key]; }}).map(function (s) {{ return s.key; }});
    }}

    // Best-effort map from a single legacy `status` to one stage. Mirrors
    // the SQL backfill in scripts/2026-06-02_add_status_tags.sql so the UI
    // shows the same thing pre- and post-migration. First match wins.
    function legacyToStages(status) {{
      var s = (status == null ? '' : String(status)).trim();
      if (!s) return [];
      if (/attending|will attend|attend only/i.test(s)) return ['Attending'];
      if (/book|self submitted|speaking|confirmed/i.test(s)) return ['Booked'];
      if (/reject|turned down|not selected|not chosen|declined to speak/i.test(s)) return ['Rejected'];
      if (/not accept|declin|\\bskip\\b|passing|we.ll pass|no opening|date conflict|sponsorship only|don.?t call/i.test(s)) return [];
      if (/intro meeting|received intro|in contact|cc.?d on mtg|\\bmeeting\\b/i.test(s)) return ['Meeting held'];
      if (/follow.?up|followed up|chased|nudged/i.test(s)) return ['Followed up'];
      if (/submit|application|finish submission/i.test(s)) return ['Submitted'];
      return ['Identified'];
    }}

    // Resolve the stage list for an ops/manual row. The stored status_tags
    // array is AUTHORITATIVE — including when it's empty: an empty array
    // means "no stages" (the user cleared them, or the import mapped the
    // status to attend-intent instead). We only fall back to deriving from
    // the legacy status text when the column itself is absent (pre-migration
    // data). Falling back on empty-array made cleared checkboxes "revert":
    // un-check -> save [] -> re-render re-derived the stage from the legacy
    // status string ("Attending?" even re-derived as Booked).
    function stageTagsOf(st) {{
      if (!st) return [];
      if (st.status_tags == null) return legacyToStages(st.status);
      return normalizeStageTags(st.status_tags);
    }}

    // Pick the single most meaningful stage (for the calendar tint).
    function mostAdvancedStage(tags) {{
      tags = tags || [];
      for (var i = 0; i < STAGE_DISPLAY_RANK.length; i++) {{
        if (tags.indexOf(STAGE_DISPLAY_RANK[i]) !== -1) return STAGE_DISPLAY_RANK[i];
      }}
      return null;
    }}

    function renderStagePills(tags) {{
      return (tags || []).map(function (k) {{
        return '<span class="ops-tag stage" style="' + stageStyle(k) + '">' + escapeHtml(k) + '</span>';
      }}).join('');
    }}

    // 5 checkboxes for an edit form. `name` is the form field name (used by
    // the manual form's FormData.getAll); `current` is the array of checked
    // stages. For the ops inline editor we don't use a <form>, so the
    // wireOpsCard handler reads the checkboxes by [data-stage] instead.
    function stageCheckboxes(current, name) {{
      var checked = normalizeStageTags(current);
      return '<div class="stage-picker" data-stage-picker>' +
        STAGE_TAGS.map(function (s) {{
          var on = checked.indexOf(s.key) !== -1;
          return '<label class="' + (on ? 'is-on' : '') + '" style="' + stageStyle(s.key) + '">' +
            '<input type="checkbox" data-stage' + (name ? ' name="' + name + '"' : '') +
            ' value="' + escapeHtml(s.key) + '"' + (on ? ' checked' : '') + '>' +
            escapeHtml(s.key) +
          '</label>';
        }}).join('') +
      '</div>';
    }}

    // "hurley@arcticblue.ai" → "Hurley". Used in any user-facing label;
    // the full email is preserved as the `title` attribute so it's still
    // visible on hover for audit purposes.
    function firstNameFromEmail(email) {{
      if (!email) return '';
      var local = String(email).split('@')[0] || '';
      // Split on common separators (dot, underscore, dash); first segment wins
      var parts = local.replace(/[._-]+/g, ' ').split(/\\s+/).filter(Boolean);
      if (parts.length === 0) return email;
      var first = parts[0].replace(/[0-9]+$/, '');
      if (!first) return parts[0];
      return first.charAt(0).toUpperCase() + first.slice(1).toLowerCase();
    }}
    // ArcticBlue sales-support staff: they run the tracker but don't attend
    // events, so they should never be auto-flagged "interested" on upload.
    var AB_SUPPORT_NAMES = ['hurley', 'angela'];
    function isSupportPerson(name) {{
      var first = String(name || '').trim().toLowerCase().split(/[ @]/)[0];
      return AB_SUPPORT_NAMES.indexOf(first) !== -1;
    }}

    // Drop a trailing year (e.g. "Databricks Data + AI Summit 2026" → "…Summit")
    // — the year is redundant with the event's date. Keeps the name if stripping
    // would leave it empty (a year-only name).
    function stripTrailingYear(name) {{
      var s = String(name == null ? '' : name);
      var out = s.replace(/[\\s,;:\\u2013\\u2014-]+(?:19|20)\\d{{2}}\\s*$/, '').trim();
      return out || s.trim();
    }}

    // ── Past-event detection (client-side, uses the REAL current date) ──
    // An event is "past" once its END date is before today. Computed live so
    // a just-ended event hides immediately — not only after the next daily
    // build. Undated / TBD / ongoing events are NEVER past (no end date to
    // compare). Catalog + manual cards both use this so behavior is uniform.
    function eventEndIso(o) {{
      if (!o) return null;
      if (o.end_date)   return String(o.end_date).slice(0, 10);
      if (o.start_date) return String(o.start_date).slice(0, 10);
      if (o.date_str) {{
        try {{
          var d = deriveDatesFromText(o.date_str);
          if (d.end_date)   return d.end_date;
          if (d.start_date) return d.start_date;
        }} catch (e) {{}}
      }}
      return null;
    }}
    // Start (preferred) — for the "has it begun?" check below.
    function eventStartIso(o) {{
      if (!o) return null;
      if (o.start_date) return String(o.start_date).slice(0, 10);
      if (o.end_date)   return String(o.end_date).slice(0, 10);
      if (o.date_str) {{
        try {{
          var d = deriveDatesFromText(o.date_str);
          if (d.start_date) return d.start_date;
          if (d.end_date)   return d.end_date;
        }} catch (e) {{}}
      }}
      return null;
    }}
    function isPastEvent(o) {{
      // Angela's ask: once we're AT the event (its start date has arrived) or
      // past it, there's nothing left to submit to — so hide it into the
      // collapsed Archive. Keyed on the START date, so a multi-day event that
      // has already begun (today falls inside its run) is hidden too, not just
      // after it ends. Day-Of briefs + the iCal feed use their own date windows,
      // so today's attended events still surface there.
      var iso = eventStartIso(o);
      if (!iso || !/^\\d{{4}}-\\d{{2}}-\\d{{2}}/.test(iso)) return false;  // undated -> not past
      // New York's date, not the viewer's — otherwise the same event reads
      // "past" in London and "today" in San Francisco (Hurley 2026-07-30).
      return iso <= (window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10));
    }}

    // Normalize any event's messy/granular region (or country/city/location)
    // into one of the 7 canonical regions used by the filter + map + planner.
    // Country is the most reliable signal; region/city/location are fallbacks.
    // Idempotent — feeding a canonical value back in returns the same value.
    function canonicalRegion(o) {{
      o = o || {{}};
      var hay = abFold([o.country, o.region, o.city, o.location].join(' '));
      function has(re) {{ return re.test(hay); }}
      if (has(/\\b(uae|united arab emirates|saudi|riyadh|dubai|abu dhabi|doha|qatar|bahrain|kuwait|oman|israel|tel aviv|jordan|lebanon|egypt|cairo|morocco|mena|middle east)\\b/)) return 'MENA';
      if (has(/\\b(south africa|johannesburg|cape town|nigeria|lagos|kenya|nairobi|ghana|accra|ethiopia|rwanda|kigali|tanzania|uganda|senegal|africa)\\b/)) return 'Africa';
      // Central America + the (non-US) Caribbean belong here too. Without them
      // an event in Santo Domingo — where Carlos is BASED — fell through to the
      // rule below and came back "US & Canada", because these rows carry
      // region: "Americas" and that regex matches the word "americas". His own
      // home market was landing in someone else's territory (Hurley 2026-07-29).
      // Puerto Rico is deliberately NOT here: it's a US territory, and whether
      // it counts as LatAm for GTM is a call for the team, not for this regex.
      if (has(/\\b(brazil|brasil|sao paulo|rio de janeiro|mexico|cdmx|guadalajara|monterrey|argentina|buenos aires|chile|santiago|colombia|bogota|medellin|cartagena|peru|lima|venezuela|caracas|uruguay|montevideo|ecuador|quito|dominican republic|republica dominicana|santo domingo|panama|costa rica|guatemala|el salvador|san salvador|honduras|tegucigalpa|nicaragua|managua|paraguay|asuncion|bolivia|latin america|latam|south america|central america)\\b/)) return 'Latin America';
      if (has(/\\b(usa|united states|america|americas|canada|toronto|vancouver|montreal|ottawa|new york|nyc|san francisco|san diego|san jose|los angeles|bay area|boston|chicago|seattle|austin|dallas|houston|denver|phoenix|philadelphia|washington dc|new orleans|hoboken|menlo park|half moon bay|berkeley|leesburg|pier sixty|texas|miami|florida|atlanta|las vegas|nevada|california|midwest|northeast|southeast|southwest|west coast|east coast|mountain west|new jersey|other us)\\b/)) return 'US & Canada';
      if (has(/\\b(uk|united kingdom|england|london|france|paris|germany|berlin|munich|spain|madrid|barcelona|catalonia|italy|rome|milan|netherlands|amsterdam|ireland|dublin|switzerland|zurich|geneva|sweden|stockholm|denmark|copenhagen|norway|oslo|finland|portugal|lisbon|austria|vienna|belgium|brussels|poland|czech|prague|europe)\\b/)) return 'Europe';
      if (has(/\\b(singapore|hong kong|china|beijing|shanghai|japan|tokyo|korea|seoul|india|delhi|mumbai|bangalore|bengaluru|australia|sydney|melbourne|new zealand|indonesia|jakarta|thailand|bangkok|malaysia|vietnam|philippines|taiwan|apac|asia.pacific|asia)\\b/)) return 'Asia-Pacific';
      return 'Global';
    }}

    // City + country for the CARD FACE — the venue / full address stays in the
    // Details pop-up. Prefer the explicit city/country fields; when they're
    // missing, strip a leading venue or street address from the location string
    // (e.g. "Hong Kong Convention and Exhibition Centre, Hong Kong, China" ->
    // "Hong Kong, China") while leaving plain "City, State, Country" untouched.
    function shortLocation(o) {{
      o = o || {{}};
      var city = String(o.city || '').trim();
      var country = String(o.country || '').trim();
      if (city && country) return city + ', ' + country;
      var parts = String(o.location || '').split(',').map(function (s) {{ return s.trim(); }}).filter(Boolean);
      if (parts.length >= 3 && (/^\\d/.test(parts[0]) ||
          /\\b(cent(er|re)|hotel|arena|convention|exhibition|expo|hall|conference|resort|casino|stadium|university|college|institute|messe|palexpo|sands|pavilion|forum|plaza|complex|palace|marina|garden|tower|club|pier|westin|marriott|hilton|hyatt|sheraton|ritz|fairmont|intercontinental|radisson|sofitel|wynn|venetian|mandalay|caesars|bellagio|renaissance|waldorf|peninsula|shangri|kempinski|four seasons)\\b/i.test(parts[0]))) {{
        parts = parts.slice(1);
      }}
      return parts.join(', ') || city || country || '';
    }}

    function formatStamp(iso) {{
      if (!iso) return '';
      var d = new Date(iso);
      if (isNaN(d)) return iso;
      var dt = d.toLocaleString(undefined, {{
        month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit'
      }});
      return dt;
    }}

    // A whisper-quiet freshness cue from the row's existing updated_at (no
    // schema change): recently touched reads "Updated 3d ago"; long-untouched
    // reads "stale · 45d untouched". Nothing shows for events never edited (no
    // timestamp to stand behind). 30 days is the line between the two.
    function freshnessTag(iso) {{
      if (!iso) return '';
      var t = new Date(iso).getTime();
      if (isNaN(t)) return '';
      var days = Math.max(0, Math.floor((Date.now() - t) / 86400000));
      var stale = days > 30;
      var ago = days === 0 ? 'today' : (days === 1 ? '1d ago' : days + 'd ago');
      var text = stale ? ('stale \\u00b7 ' + days + 'd untouched') : ('Updated ' + ago);
      return '<span class="ops-fresh ' + (stale ? 'is-stale' : 'is-fresh') +
        '" title="Last updated ' + escapeHtml(formatStamp(iso)) + '">' + text + '</span>';
    }}
    // Plain-text "Updated Nd ago" for the Details pop-up (the card face no longer
    // shows it — Hurley moved it into the detail, in italics). Exposed for the
    // modal, which lives in a separate closure.
    function _freshText(iso) {{
      if (!iso) return '';
      var t = new Date(iso).getTime();
      if (isNaN(t)) return '';
      var days = Math.max(0, Math.floor((Date.now() - t) / 86400000));
      var ago = days === 0 ? 'today' : (days === 1 ? '1 day ago' : days + ' days ago');
      return 'Updated ' + ago;
    }}
    window.opsFreshText = _freshText;

    // True if a row was created within the last 7 days (covers hand-added AND
    // Dust-ingested manual events — both stamp created_at on insert).
    function isRecentlyAdded(ts) {{
      if (!ts) return false;
      var t = new Date(ts).getTime();
      if (isNaN(t)) return false;
      return (Date.now() - t) < 7 * 86400000;
    }}

    function optionRows(values, current) {{
      return values.map(function (v) {{
        var label = v || '— none —';
        var sel = (v === (current || '')) ? ' selected' : '';
        return '<option value="' + escapeHtml(v) + '"' + sel + '>' + escapeHtml(label) + '</option>';
      }}).join('');
    }}

    function flashOk(toast) {{
      status(toast || 'Saved', null);
      clearTimeout(window._flashT);
      window._flashT = setTimeout(function () {{ status(''); }}, 1400);
    }}

    // Single-field upsert into event_state. Partial — preserves other columns
    // on conflict (PostgREST translates upsert with PK conflict into
    // `INSERT ... ON CONFLICT (event_num) DO UPDATE SET ...` for the
    // explicit columns we send).
    function upsertEventState(num, patch, email) {{
      patch.event_num = num;
      patch.updated_by = email;
      // sbWriteRetry strips not-yet-migrated columns (attend_verdict,
      // postmortem) and retries, so saves never break pre-migration.
      return sbWriteRetry(patch, function (p) {{
        return sb.from('event_state').upsert(p, {{ onConflict: 'event_num' }});
      }}).then(function (resp) {{
        if (!resp.error && resp.strippedMigrationCols) {{
          status('Saved — but ' + resp.strippedMigrationCols.join(', ') +
                 ' could not be stored until the DB migration runs.', 'warn');
        }}
        return resp.error || null;
      }});
    }}

    function renderOpsTags(st) {{
      var tags = [];
      // Primary: the multi-tag pipeline stages.
      var stages = stageTagsOf(st);
      stages.forEach(function (k) {{
        tags.push('<span class="ops-tag stage" style="' + stageStyle(k) + '">' + escapeHtml(k) + '</span>');
      }});
      if (st.speaker) {{
        tags.push('<span class="ops-tag speaker">' + escapeHtml(st.speaker) + '</span>');
      }}
      if (st.priority_override) {{
        var cls = 'pri-' + st.priority_override.toLowerCase();
        tags.push('<span class="ops-tag ' + cls + '">' + escapeHtml(st.priority_override) + '</span>');
      }}
      // The legacy single status (imported Replit label, e.g. "Sponsorship
      // Only") is NO LONGER shown on the card face — 148 of them were cluttering
      // the cards. It's preserved in event_state and editable/clearable in
      // Details → "Status label", so nothing Angela typed is lost.
      if (tags.length === 0) return '';
      return '<div class="ops-tags">' + tags.join('') + '</div>';
    }}

    // Per-role roster for the card face — replaces the old pile of stage/speaker
    // pills with clear "Stage: who" lines so it's obvious WHO is doing what
    // (e.g. Submitted: Thor / Attending: Jerome). Blank rows are hidden.
    function _personName(k) {{
      var P = window.AB_PERSONAS || {{}};
      var key = String(k == null ? '' : k).toLowerCase();
      if (P[key] && P[key].name) return P[key].name;
      var s = String(k == null ? '' : k);
      return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
    }}
    // Small colored initial-avatar (Google Calendar / Docs style) instead of a
    // boxed "STAGE: name" label — the stage color now lives on the avatar, the
    // stage word is a plain muted caption, and "who" reads like a byline.
    function _avatarInitial(name) {{
      var s = String(name == null ? '' : name).trim();
      return s ? s.charAt(0).toUpperCase() : '?';
    }}
    function _avatarsHtml(names, style) {{
      if (!names || !names.length) return '';
      var sty = style || 'background:var(--ab-bg-3);color:var(--ab-fg-2);';
      var MAX = 4;
      var shown = names.slice(0, MAX);
      var extra = names.length - shown.length;
      var html = shown.map(function (n) {{
        return '<span class="ops-avatar" style="' + sty + '" title="' + escapeHtml(String(n)) + '">' +
          escapeHtml(_avatarInitial(n)) + '</span>';
      }}).join('');
      if (extra > 0) html += '<span class="ops-avatar ops-avatar-more" title="' + (extra) + ' more">+' + extra + '</span>';
      return '<span class="ops-avatars">' + html + '</span>';
    }}
    function _rosterRow(label, names, who, style, muted) {{
      return '<div class="ops-roster-row">' +
        '<span class="ops-roster-label">' + escapeHtml(label) + '</span>' +
        _avatarsHtml(names, style) +
        '<span class="ops-roster-who' + (muted ? ' muted' : '') + '">' + who + '</span>' +
      '</div>';
    }}
    // The card-face star means "I'm interested" — specific to whoever is signed
    // in (Jerome stars it -> Jerome shows as interested). These drive the star's
    // filled state + click, reusing the same interested list as the modal toggle.
    function meInInterested(list) {{
      var me = (getCollabName() || '').toLowerCase();
      if (!me) return false;
      return (list || []).some(function (n) {{ return String(n).toLowerCase() === me; }});
    }}
    function toggleMyInterest(kind, key, list, saVerdict) {{
      var me = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || '';
      if (!me) return;   // no name -> nothing to flag
      // Support (Angela) doesn't attend — for her the star is a team SHOULD-ATTEND
      // flag, not a personal "I'm interested". Toggle attend_verdict (human) and
      // never add her to the interested list.
      if (isAngelaUser()) {{
        var onSA = shouldAttendKind(saVerdict) === 'human';
        var pSA = {{ attend_verdict: onSA ? null : 'Worth attending' }};
        if (!onSA) pSA.queue_dismissed = false;
        if (window.opsWrite) window.opsWrite(kind === 'manual' ? 'manual_events' : 'event_state', key, pSA);
        return;
      }}
      var cur = (list || []).slice();
      var lc = me.toLowerCase(), hit = -1;
      for (var z = 0; z < cur.length; z++) {{ if (String(cur[z]).toLowerCase() === lc) {{ hit = z; break; }} }}
      var patch = {{}};
      if (hit === -1) {{
        cur.push(me);
        patch.attend_verdict = 'Worth attending';  // interest funnels into Angela's Should-Attend
        patch.queue_dismissed = false;   // a fresh flag revives it in Angela's queue if it was dismissed
      }}
      else {{ cur.splice(hit, 1); }}
      patch.interested = cur;
      if (window.opsWrite) window.opsWrite(kind === 'manual' ? 'manual_events' : 'event_state', key, patch);
    }}
    function starButtonHtml(list, saVerdict) {{
      // For Angela the star = "Should Attend" (team flag); for everyone else it's
      // "I'm interested". The filled state + tooltip follow whichever it is.
      var angela = isAngelaUser();
      var on = angela ? (shouldAttendKind(saVerdict) === 'human') : meInInterested(list);
      var lbl = angela ? 'Flag Should Attend' : 'I\\'m interested';
      var ttl = angela ? 'Star = Should Attend \\u2014 flags this event for the team'
                       : 'Star = I\\'m interested (adds you to the interested list + Angela\\'s queue)';
      return '<button class="saved-star ops-hover' + (on ? ' is-on' : '') + '" data-star type="button"' +
        ' aria-label="' + lbl + '" title="' + ttl + '">' +
        (on ? '\\u2605' : '\\u2606') + '</button>';
    }}

    function renderOpsRoster(st, extra) {{
      var stages = stageTagsOf(st);
      var rows = [];
      // Speaking track — the furthest active speaking stage, with the speaker.
      var SPEAK = ['Booked', 'Meeting held', 'Followed up', 'Submitted'];
      var spStage = null;
      for (var i = 0; i < SPEAK.length; i++) {{ if (stages.indexOf(SPEAK[i]) !== -1) {{ spStage = SPEAK[i]; break; }} }}
      var speaker = (st.speaker || '').trim();
      if (spStage) rows.push(_rosterRow(spStage, speaker ? [speaker] : null, speaker ? escapeHtml(speaker) : '&mdash;', stageStyle(spStage), !speaker));
      else if (speaker) rows.push(_rosterRow('Speaker', [speaker], escapeHtml(speaker), ''));
      // Attending — the people actually GOING (the attendees roster). THIS is the
      // line that was missing: tagging an attendee now shows up here.
      var att = (st.attendees || []).map(_personName).filter(Boolean);
      if (att.length) rows.push(_rosterRow('Attending', att, escapeHtml(att.join(', ')), stageStyle('Attending')));
      else if (stages.indexOf('Attending') !== -1) rows.push(_rosterRow('Attending', null, 'add who in Details &rarr; Edit', stageStyle('Attending'), true));
      // Interested names — feeds Angela's apply queue, so ONLY she sees the list.
      // For everyone else, their own interest shows as the blue card outline +
      // blue star (is-mine), not a "Name interested" label.
      var intr = (st.interested || []).filter(Boolean);
      if (intr.length && window.isAngelaUser && window.isAngelaUser()) rows.push(_rosterRow('\\u2605 Interested', intr, escapeHtml(intr.join(', ')), ''));
      var pills = [];
      // Audience badge (Buyer-rich etc.) shares this SAME row so the labels sit
      // side-by-side instead of stacking (the card is a flex column, so two
      // separate rows would each take a full line — wasted vertical space).
      if (extra) pills.push(extra);
      var html = '';
      if (rows.length) html += '<div class="ops-roster">' + rows.join('') + '</div>';
      if (pills.length) html += '<div class="ops-tags ops-tags--meta">' + pills.join('') + '</div>';
      return html;
    }}

    // Month-grouping metadata for an ops card. Prefers an ISO start_date,
    // falls back to parsing the free-form date_str, and lands undated rows in
    // a "Date TBD" bucket sorted to the very end. Returns key / label / sort
    // where key is 'YYYY-MM' (or 'tbd'), label is e.g. 'June 2026', and sort is
    // a DAY-PRECISE comparable integer (year*10000 + month*100 + day) so cards
    // order by their actual event date — within a month too — regardless of
    // when they were added. Undated rows sort last (99999999).
    var OPS_MONTH_NAMES = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];
    // ONE canonical card date everywhere: "Month D, YYYY" (single day) or
    // "Month D–D, YYYY" (range) — year dropped when it's the CURRENT year (the
    // month divider already shows it). Sources store date_str in every shape
    // ("April 12–14, 2027", "4-6 May 2027", "6/7/2027 - 6/8/2027"), so prefer the
    // structured ISO start/end, and parse the free text when ISO is missing.
    function cardDate(dateStr, startIso, endIso) {{
      function iso(v) {{ return (v && /^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(v)) ? v : null; }}
      var s = iso(startIso), e = iso(endIso);
      if (!s && dateStr) {{ try {{ var d = deriveDatesFromText(dateStr); s = iso(d.start_date); e = iso(d.end_date) || e; }} catch (x) {{}} }}
      if (!s) {{
        // Unparseable — fall back to the cleaned raw string (drop this year).
        var raw = (dateStr || '').trim(); if (!raw) return raw;
        var ym = raw.match(/\\b20\\d\\d\\b/);
        if (ym && ym[0] === String(new Date().getFullYear())) raw = raw.split(ym[0]).join('').replace(/[\\s,\\/]+$/, '').replace(/^[\\s,\\/]+/, '').trim();
        return raw;
      }}
      function p(x) {{ return {{ y: +x.slice(0, 4), m: +x.slice(5, 7), d: +x.slice(8, 10) }}; }}
      var a = p(s), b = e ? p(e) : null;
      if (b && (b.y < a.y || (b.y === a.y && (b.m < a.m || (b.m === a.m && b.d < a.d))))) b = null;   // ignore a bogus earlier end
      var M = OPS_MONTH_NAMES, thisY = new Date().getFullYear(), out, yr;
      if (!b || (b.y === a.y && b.m === a.m && b.d === a.d)) {{ out = M[a.m - 1] + ' ' + a.d; yr = a.y; }}                       // single day
      else if (b.y === a.y && b.m === a.m) {{ out = M[a.m - 1] + ' ' + a.d + '\\u2013' + b.d; yr = a.y; }}                       // April 12–14
      else if (b.y === a.y) {{ out = M[a.m - 1] + ' ' + a.d + ' \\u2013 ' + M[b.m - 1] + ' ' + b.d; yr = a.y; }}                  // May 30 – June 2
      else {{ return M[a.m - 1] + ' ' + a.d + ', ' + a.y + ' \\u2013 ' + M[b.m - 1] + ' ' + b.d + ', ' + b.y; }}                  // spans years — keep both
      return out + (yr === thisY ? '' : ', ' + yr);
    }}

    function opsMonthMeta(startIso, dateStr) {{
      // Prefer a well-formed ISO start_date; if it's missing OR malformed,
      // fall back to parsing the free-form date_str before giving up to TBD.
      var iso = (startIso && /^\\d{{4}}-\\d{{2}}/.test(startIso)) ? startIso : null;
      if (!iso && dateStr) {{
        try {{ iso = deriveDatesFromText(dateStr).start_date; }} catch (e) {{ iso = null; }}
      }}
      if (iso && /^\\d{{4}}-\\d{{2}}/.test(iso)) {{
        var y = parseInt(iso.slice(0, 4), 10);
        var mo = parseInt(iso.slice(5, 7), 10);
        var day = parseInt(iso.slice(8, 10), 10) || 1;  // missing day -> 1st
        if (day < 1 || day > 31) day = 1;
        if (y && mo >= 1 && mo <= 12) {{
          return {{
            key: iso.slice(0, 4) + '-' + iso.slice(5, 7),
            label: OPS_MONTH_NAMES[mo - 1] + ' ' + y,
            sort: y * 10000 + mo * 100 + day
          }};
        }}
      }}
      return {{ key: 'tbd', label: 'Date TBD', sort: 99999999 }};
    }}

    // CFP-deadline line for the card face. Red when the text says URGENT or
    // a parseable date is within ~30 days (or already passed — either way it
    // needs Angela's attention NOW, not buried in the pop-up).
    // True when an event's APPLY / CFP deadline is still open and closing soon —
    // a parseable deadline date within the next ~6 weeks, or text that says it's
    // urgent/closing. This is the ONLY thing that makes an event "Urgent": a
    // deadline to apply that's coming up — NOT the event date itself.
    // Rolling / open-ended / already-closed deadlines carry no urgency.
    function isDeadlineSoon(d) {{
      if (d == null || !String(d).trim()) return false;
      var txt = String(d).trim();
      if (/rolling|ongoing|membership|closed|has passed|may have passed/i.test(txt)) return false;
      if (/urgent|immediately|asap|closing soon|closes soon/i.test(txt)) return true;
      var iso = null;
      try {{ iso = deriveDatesFromText(txt).start_date; }} catch (e) {{}}
      if (!iso) return false;
      var days = (new Date(iso + 'T00:00:00') - new Date()) / 86400000;
      return days >= -1 && days <= 45;  // still open, closing within ~6 weeks
    }}
    // Urgent when the CFP/apply deadline is within the next two weeks (and not
    // already past). Tighter than isDeadlineSoon, which drives the softer
    // "deadline approaching" highlight at ~6 weeks.
    function isDeadlineUrgent(d) {{
      if (d == null || !String(d).trim()) return false;
      var txt = String(d).trim();
      if (/rolling|ongoing|membership|closed|has passed|may have passed/i.test(txt)) return false;
      if (/urgent|immediately|asap|closing soon|closes soon/i.test(txt)) return true;
      var iso = null;
      try {{ iso = deriveDatesFromText(txt).start_date; }} catch (e) {{}}
      if (!iso) return false;
      var days = (new Date(iso + 'T00:00:00') - new Date()) / 86400000;
      return days >= -1 && days <= 14;  // closing within two weeks
    }}
    // True when the apply/CFP deadline has clearly already passed — so we stop
    // showing it as an active "⏳ deadline". Open-ended deadlines (rolling /
    // ongoing / TBD) and unparseable text never count as past.
    function isDeadlinePast(d) {{
      if (d == null || !String(d).trim()) return false;
      var txt = String(d).trim();
      if (/closed|has passed|deadline passed|expired/i.test(txt)) return true;
      if (/rolling|ongoing|membership|continuous|tbd|tba|open|invite|varies|year.round/i.test(txt)) return false;
      var dt = null;
      // deriveDatesFromText handles ranges + "Month DD, YYYY"; fall back to the
      // native parser for day-first formats like "4 April 2026" it misses.
      try {{ var iso = deriveDatesFromText(txt).start_date; if (iso) dt = new Date(iso + 'T00:00:00'); }} catch (e) {{}}
      if (!dt || isNaN(dt)) {{ var d2 = new Date(txt); if (!isNaN(d2)) dt = d2; }}
      if (!dt || isNaN(dt)) return false;  // unparseable -> don't assume past
      return ((dt - new Date()) / 86400000) < 0;  // strictly before today
    }}
    // Non-informative placeholder values we should never print as a label
    // ("CFP deadline: not specified", "Fee: N/A", …). Blank counts as junk too.
    var _JUNK_VAL_RE = /^(n\\/?a|na|none|null|nil|unknown|unspecified|not\\s+(specified|announced|available|listed|provided|applicable|known|set)|tbd|tba|to\\s+be\\s+(determined|announced|confirmed)|-+|\\.+|\\u2014+|\\?+)$/i;
    function _isJunkVal(v) {{
      var s = String(v == null ? '' : v).trim();
      if (!s || _JUNK_VAL_RE.test(s)) return true;
      // A phrase like "CFP deadline not specified" (no real date) is also junk,
      // but keep anything that carries an actual date or a rolling window.
      var junkPhrase = /\\b(not\\s+(specified|announced|available|listed|provided|determined|set|known)|unspecified|unknown|no\\s+(deadline|cfp|date)|to\\s+be\\s+(determined|announced|confirmed)|tbd|tba)\\b/i.test(s);
      return junkPhrase && !/\\d/.test(s) && !/rolling|ongoing|year.?round|continuous|\\bopen\\b/i.test(s);
    }}
    // Enrichment sometimes leaves a DATED hedge on the deadline — e.g.
    // "speakers drop soon (not officially announced as of April 21, 2026)".
    // Once that "as of" stamp is more than a week old the note is no longer
    // relevant, so the read view should hide it (only recent info is shown).
    // A real FUTURE date that survives stripping the "as of" clause is kept —
    // only date-less hedges and stale stamps are treated as stale.
    function isStaleDeadline(d) {{
      var s = String(d == null ? '' : d).trim();
      if (!s) return false;
      if (_isJunkVal(s)) return true;
      // Strip any "(… as of <date>)" or bare "as of <date>" enrichment stamp.
      var bare = s.replace(/\\([^)]*\\bas of\\b[^)]*\\)/ig, ' ')
                   .replace(/\\bas of\\s+[a-z0-9.,\\/ -]{{4,22}}/ig, ' ')
                   .replace(/\\s+/g, ' ').trim();
      var hasRealDate = /\\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?\\s+\\d/i.test(bare)
                     || /\\d{{4}}-\\d{{1,2}}-\\d{{1,2}}/.test(bare)
                     || /\\b\\d{{1,2}}\\/\\d{{1,2}}\\b/.test(bare);
      if (hasRealDate) return false;   // a concrete date remains -> still useful
      // No real date left. Stale if the "as of" stamp is >1 week old…
      var m = s.match(/as of\\s+([a-z]{{3,9}}\\.?\\s+\\d{{1,2}},?\\s*\\d{{4}}|\\d{{4}}-\\d{{1,2}}-\\d{{1,2}}|\\d{{1,2}}\\/\\d{{1,2}}\\/\\d{{2,4}})/i);
      if (m) {{
        var dt = new Date(m[1]);
        if (!isNaN(dt) && (Date.now() - dt.getTime()) > 7 * 86400000) return true;
      }}
      // …or it's a bare, date-less "not … announced / … soon / expected" hedge.
      return /\\bnot\\s+\\S+\\s+(announced|confirmed|released|published)\\b|\\b(announced?|drop|dropping|release[ds]?)\\s+soon\\b|\\bexpected\\s+(soon|shortly|later)\\b|\\bto be (announced|confirmed|determined)\\b/i.test(s);
    }}
    window.isStaleDeadline = isStaleDeadline;
    // Format a stored submission date (YYYY-MM-DD) as "Jul 2" (drops the year
    // when it's the current year, like the card dates). Parsed by hand so an
    // ISO date never shifts a day across the local timezone.
    function _fmtSubmittedDate(v) {{
      var s = String(v || '').trim();
      var m = /^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})/.exec(s);
      if (!m) return s;
      var y = +m[1], mo = +m[2], da = +m[3];
      if (mo < 1 || mo > 12) return s;
      var lbl = OPS_MONTH_NAMES[mo - 1].slice(0, 3) + ' ' + da;
      return lbl + (y === new Date().getFullYear() ? '' : ', ' + y);
    }}
    // ONE derived status line per card — computed from the data, never
    // hand-edited. Speaking-first (this is primarily a speaking tracker).
    // Examples:
    //   Booked — Thor speaking
    //   Submitted to speak (CFP closed)
    //   Closed to speak
    //   Attending — Jerome
    // Shows NOTHING when we know nothing — no invented status, no filler.
    function cardStatusLine(ev, st) {{
      st = st || ev;
      var stages = stageTagsOf(st);
      var past = isPastEvent(ev);
      var speaker = (st.speaker || '').trim();
      var att = ((st.attendees || ev.attendees) || []).map(_personName).filter(Boolean);
      var d = (st.deadline === '__cleared__') ? '' : ((st.deadline != null && String(st.deadline).trim()) ? st.deadline : ev.deadline);
      var closed = !past && d && !_isJunkVal(d) && isDeadlinePast(d);
      // Each bit carries a priority: COMMITTED presence (Attending / Booked)
      // leads (p1), then the pending "Submitted to speak" (p2), then the
      // soft Open/Closed states (p3) — so a card that is both "submitted to
      // speak" and "attending" reads "Attending … · Submitted to speak …".
      var bits = [];   // {{ p: priority, h: html }}
      if (stages.indexOf('Booked') !== -1) {{
        bits.push({{ p: 1, h: '<span class="st-bit"><span class="st-dot st-ok"></span>Booked' + ST_MIC + (speaker ? ' \\u2014 ' + escapeHtml(speaker) + ' speaking' : '') + '</span>' }});
      }} else if (stages.indexOf('Rejected') !== -1) {{
        // Rejected to speak — a terminal "no" that wins over a pending Submitted.
        bits.push({{ p: 3, h: '<span class="st-bit"><span class="st-dot st-no"></span>Rejected' + ST_MIC + (speaker ? ' \\u2014 ' + escapeHtml(speaker) : '') + '</span>' }});
      }} else if (stages.indexOf('Submitted') !== -1 || stages.indexOf('Followed up') !== -1 || stages.indexOf('Meeting held') !== -1) {{
        // Angela records WHEN the application went out (event_state/manual
        // .submitted_at) — surface it on her status line only.
        var _subDate = (window.isAngelaUser && window.isAngelaUser() && st.submitted_at)
          ? '<span class="st-sub-date"> \\u00b7 submitted ' + escapeHtml(_fmtSubmittedDate(st.submitted_at)) + '</span>' : '';
        // Just "Submitted" — the mic already says it's the speaking track, so
        // "to speak" was redundant (Angela). ("Closed to speak" below KEEPS its
        // wording: it carries no mic.)
        bits.push({{ p: 2, h: '<span class="st-bit"><span class="st-dot st-wait"></span>Submitted' + ST_MIC + (speaker ? ' \\u2014 ' + escapeHtml(speaker) : '') + _subDate + (closed ? ' (CFP closed)' : '') + '</span>' }});
      }} else if (closed) {{
        bits.push({{ p: 3, h: '<span class="st-bit"><span class="st-dot st-no"></span>Closed to speak</span>' }});
      }}
      // NOTE: no "Open to speak" / "Open to attend" bits. This is primarily a
      // SPEAKING tracker: every fitting event is implicitly open to speak, and
      // "open to attend" added noise (Hurley — people rarely attend a paid event
      // they can't speak at, and attending is something you just book yourself).
      // The status line only shows a committed/pending/closed speak state + who's
      // actually attending.
      if (att.length) {{
        bits.push({{ p: 1, h: '<span class="st-bit"><span class="st-dot st-ok"></span>Attending' + ST_TICKET + ' \\u2014 ' + escapeHtml(att.join(', ')) + '</span>' }});
      // The Attending STAGE is set but no attendee is named yet — still show it,
      // so ticking "Attending" on the add form holds visibly (add who in Edit).
      }} else if (stages.indexOf('Attending') !== -1 && !past) {{
        bits.push({{ p: 1, h: '<span class="st-bit"><span class="st-dot st-ok"></span>Attending' + ST_TICKET + '</span>' }});
      }}
      if (!bits.length) return '';
      bits.sort(function (a, b) {{ return a.p - b.p; }});   // committed presence leads (stable within a tier)
      return '<p class="ops-status-line">' + bits.map(function (b) {{ return b.h; }}).join('<span class="st-sep">\\u00b7</span>') + '</p>';
    }}
    function deadlineLine(d, o) {{
      // Raw CFP deadline DATES are Angela's business (she runs applications) —
      // the derived open/closed STATUS shows for everyone via cardStatusLine.
      if (!(window.isAngelaUser && window.isAngelaUser())) return '';
      if (!deadlineUsable(d, o)) return '';   // shared vetting — see deadlineUsable
      var txt = String(d).trim();
      var cls = isDeadlineSoon(d) ? ' deadline-soon' : '';
      return '<p class="ops-meta deadline-line' + cls + '">CFP deadline: ' + escapeHtml(txt) + '</p>';
    }}

    // Is this CFP deadline worth showing AT ALL? Same rules the card applies,
    // pulled out so the Details pop-up can't disagree with the card — it used to
    // print the raw value, so eCommerce Day Uruguay (event Jul 30) showed a
    // "2026-06-30" deadline in Details that the card had already suppressed.
    // Rejected: blank, junk ("TBD"/"N/A"), a stale "…as of April 21" hedge, a
    // deadline that has already passed, and — per Angela — any deadline falling
    // ON or AFTER the event itself (you can't submit a talk once it's started).
    function deadlineUsable(d, o) {{
      if (d == null || !String(d).trim()) return false;
      var txt = String(d).trim();
      if (_isJunkVal(txt)) return false;
      if (isStaleDeadline(txt)) return false;
      if (isDeadlinePast(d)) return false;
      var evStart = eventStartIso(o);
      if (evStart) {{
        var dl = null;
        try {{ var diso = deriveDatesFromText(txt).start_date; if (diso) dl = new Date(diso + 'T00:00:00'); }} catch (e) {{}}
        if (!dl || isNaN(dl)) {{ var d2 = new Date(txt); if (!isNaN(d2)) dl = d2; }}
        var evd = new Date(evStart + 'T00:00:00');
        if (dl && !isNaN(dl) && !isNaN(evd) && dl >= evd) return false;
      }}
      return true;
    }}
    window.opsDeadlineUsable = deadlineUsable;

    // Two status glyphs so speaking vs attending reads at a glance (Angela):
    //   mic    = the SPEAKING track (Booked / Submitted / Rejected) — "Rejected 🎤 — Thor"
    //   ticket = ATTENDING (we're in the room, not on stage)
    // Real emoji, not hairline SVGs — the thin outline icons rendered as faint
    // smudges at 11px on the card (Angela). \\uD83C\\uDFA4 = 🎤,
    // \\uD83C\\uDF9F\\uFE0F = 🎟 (the VS16 forces emoji, not text, presentation).
    var ST_MIC    = '<span class="st-mic" role="img" title="Speaking" aria-label="speaking">\\uD83C\\uDFA4</span>';
    var ST_TICKET = '<span class="st-mic st-ticket" role="img" title="Attending" aria-label="attending">\\uD83C\\uDF9F\\uFE0F</span>';

    // "Contact found" = we have a real email to reach this event's organizer,
    // in the structured poc_email or embedded in the free-text contact_info.
    var _EMAIL_RE = /[^\\s@]+@[^\\s@]+\\.[^\\s@]{{2,}}/;
    // The ✉ badge means "there's a human we can reach here" — an email OR a NAMED
    // person. It used to require an email address, so an event where Angela had
    // written down a contact's name but no address showed nothing (Angela).
    //
    // A bare website is NOT a contact: contact_info is often just "ai4.io" or a
    // registration URL, so free text only counts once the URLs/domains are
    // stripped out and something human-readable is still left. Junk values
    // ("TBD", "Not verifiable…") never count.
    function _contactText(v) {{
      var s = String(v == null ? '' : v).trim();
      if (!s || _isJunkVal(s)) return '';
      if (_EMAIL_RE.test(s)) return s;                       // an address anywhere wins
      var stripped = s
        .replace(/https?:\\/\\/\\S+/gi, ' ')                    // full URLs
        .replace(/\\b[\\w-]+(\\.[\\w-]+)+(\\/\\S*)?/g, ' ')        // bare domains / paths
        .replace(/[^A-Za-z0-9]+/g, ' ')
        .trim();
      return stripped.length >= 3 ? stripped : '';
    }}
    // Stricter test for the FREE-TEXT contact fields (contact_info,
    // additional_contacts). _contactText() only strips URLs, so instructions
    // like "Contact via the website" survived it and rendered under a Contacts
    // heading — no name, no address, nobody to contact (Hurley 2026-07-30).
    // Here a value must carry an email, or a person-shaped name: two
    // consecutive capitalised words. poc_name keeps the looser test, since a
    // one-word name in a field literally called "name" is still a name.
    var _PERSON_RE = /[A-Z][a-z'\u2019-]+(?:\s+[A-Z][a-z'\u2019-]+)+/;   // NB: no \\b — this template is a non-raw Python string, so a lone backslash-b would be emitted as a BACKSPACE character and silently break the pattern. The [A-Z] anchor makes it unnecessary anyway.
    function _contactPerson(v) {{
      var t = _contactText(v);
      if (!t) return '';
      if (_EMAIL_RE.test(String(v))) return t;
      return _PERSON_RE.test(String(v)) ? t : '';
    }}
    // Shared with the Details modal so the Contacts section and the card's
    // envelope badge agree on what counts as a contact.
    window.opsContactText = function (v) {{ return _contactText(v); }};
    window.opsContactPerson = function (v) {{ return _contactPerson(v); }};
    function hasEmailContact() {{
      for (var i = 0; i < arguments.length; i++) {{
        var o = arguments[i]; if (!o) continue;
        if (_EMAIL_RE.test(String(o.poc_email || ''))) return true;
        // A named point of contact counts on its own — no address required.
        if (_contactText(o.poc_name)) return true;
        if (String(o.poc_linkedin || '').trim()) return true;
        if (_contactPerson(o.contact_info)) return true;
        if (_contactPerson(o.additional_contacts)) return true;
      }}
      return false;
    }}

    // "Hide" icon (eye with a slash) for the card's hover-only archive control —
    // matches the Lucide icon set already used elsewhere in this file.
    var OPS_HIDE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="17" height="17">' +
      '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>' +
      '<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/>' +
      '<path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>' +
      '<line x1="2" x2="22" y1="2" y2="22"/>' +
    '</svg>';

    function buildOpsCard(ev, st, email) {{
      var card = document.createElement('article');
      card.className = 'ops-card';
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      card.dataset.eventNum = ev.num;
      card.dataset.kind = 'regular';
      card.dataset.region = canonicalRegion(ev);
      card.dataset.hasSpeaker = (st.speaker && st.speaker.trim()) ? '1' : '';
      card.dataset.status = st.status || '';
      var opsStages = stageTagsOf(st);
      card.dataset.statusTags = opsStages.join('|');
      var opsMeta = opsMonthMeta(ev.start_date || (st && st.start_date), ev.date_str);
      card.dataset.month = opsMeta.key;
      card.dataset.monthLabel = opsMeta.label;
      card.dataset.sort = opsMeta.sort;
      // Priority falls back to the event's own priority; override wins if set
      card.dataset.priority = (st.priority_override || ev.priority || '');
      card.dataset.speaker  = (st.speaker || '');
      // Attending signals — an event_state override (edited on the card) wins
      // over the catalog value, so audience / 1:1 / price edits show on the face.
      var _aud   = (st.audience_type  && String(st.audience_type).trim())  ? st.audience_type  : ev.audience_type;
      var _meet  = (st.meeting_formats === '__cleared__') ? '' : ((st.meeting_formats && String(st.meeting_formats).trim()) ? st.meeting_formats : ev.meeting_formats);
      var _price = (st.pricing === '__cleared__') ? '' : ((st.pricing && String(st.pricing).trim()) ? st.pricing : ev.pricing);
      card.dataset.audience = (_aud || '');
      var _pn = priceNumOf(_price);
      card.dataset.price    = (_pn == null ? '' : String(_pn));
      card.dataset.meetings = (_meet ? '1' : '');
      card.dataset.attend   = (st.attend_verdict || '');
      card.dataset.interested = (st.interested && st.interested.length) ? '1' : '';
      card.dataset.interestedNames = (st.interested || []).map(function (n) {{ return String(n).toLowerCase(); }}).join('|');
      // Who's ATTENDING (the source of truth) — per-account, incl. past + future.
      card.dataset.attendeeNames = ((st.attendees || ev.attendees) || []).map(function (n) {{ return String(n).toLowerCase(); }}).join('|');
      card.dataset.briefReady = (st.briefing_json ? '1' : '');   // Day-Of brief pre-generated?
      card.dataset.fitText = abFold([ev.name, ev.about, ev.focus_areas, ev.typical_attendees, ev.location, ev.city, ev.country, ev.type, ev.past_speakers, _aud].join(' '));
      // Non-English event title -> off Thor's / Verma's / Joe's fit lists.
      card.dataset.foreignLang = _isForeignLangEvent(ev) ? '1' : '';
      // Signals the per-person "Not for me" veto scores against (see _vetoScore).
      card.dataset.vetoOrg  = _orgKeyOf(ev);
      card.dataset.vetoCity = _lesserCityOf(ev);
      var _opsPast = isPastEvent(ev);
      card.dataset.past = _opsPast ? '1' : '';
      if (_opsPast) card.classList.add('is-past');
      if (st.saved)  card.classList.add('is-saved');
      if (meInInterested(st.interested)) card.classList.add('is-mine');   // I starred it → blue outline
      // Angela's Should-Attend now shows as the SAME blue outline (like an
      // interested card), replacing the old "★ Should Attend" badge.
      if (window.isAngelaUser && window.isAngelaUser() && shouldAttendKind(st.attend_verdict) === 'human') card.classList.add('is-sa');
      var _catArchivedMe = _isArchivedForMe(false, ev.num, st.hidden === true);
      if (_catArchivedMe) card.classList.add('is-archived');
      // Urgent = manually flagged OR an apply/CFP deadline that's closing soon.
      // (The event merely being upcoming does NOT make it urgent.)
      var _soon = isDeadlineSoon(ev.deadline) && !_opsPast;
      if (_soon) card.dataset.deadlineSoon = '1';
      if (st.urgent || (isDeadlineUrgent(ev.deadline) && !_opsPast)) card.classList.add('is-urgent');
      card.dataset.decision = (st.decision || '');
      // "✓ Go" is Angela's promotion call — Angela-only on the card face.
      var decBadge = (st.decision === 'go' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="decision-badge go">✓ Go</span>' : '';
      // Card-face Should-Attend badge (Angela: needs to spot them while scanning).
      // HUMAN flags get a prominent star badge; the 256 AI auto-picks get only a
      // faint tag so they don't drown the ones the team hand-picked.
      // Only the team's HAND-PICKED should-attends get a card-face badge — the
      // 239 AI auto-picks stay off the face (findable via the "AI picks" filter)
      // so they don't clutter/mute the manual ones Angela scans for.
      // Should-Attend is now the blue card outline (is-sa), not a face badge.
      var saBadge = '';
      // A cleared ('__cleared__') contact override must not fall back to the
      // catalog email for the ✉ Contact badge / Contacts filter either.
      var _effContact = (st && st.contact_info != null && String(st.contact_info).trim() !== '')
        ? (st.contact_info === '__cleared__' ? '' : st.contact_info)
        : (ev.contact_info || '');
      card.dataset.contactFound = hasEmailContact({{
        poc_email:           (st && st.poc_email) || ev.poc_email,
        poc_name:            (st && st.poc_name) || ev.poc_name,
        poc_linkedin:        (st && st.poc_linkedin) || ev.poc_linkedin,
        additional_contacts: (st && st.additional_contacts) || ev.additional_contacts,
        contact_info:        _effContact
      }}) ? '1' : '';
      // Contact (POC) badge is Angela's outreach cue — only she sees it on the card.
      var contactBadge = (card.dataset.contactFound === '1' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="contact-badge" title="We have a contact for this event — a name, an email or both">✉ Contact</span>' : '';
      // A link added/edited in event_state (override) wins over the catalog URL,
      // so adding a link to a link-less catalog event lights up the card ↗.
      // Private events have no public page — a scraped URL is usually wrong, so
      // never link the card title for them (Angela).
      var _catPriv = (st.is_private === true) || (ev.is_private === true);
      var _cardUrl = _catPriv ? '' : ((st.url && String(st.url).trim()) ? String(st.url).trim() : (ev.url || ''));

      var metaLine = (st.updated_by && st.updated_at)
        ? '<p class="ops-meta" title="' + escapeHtml(st.updated_by) + '">Last edit · ' + escapeHtml(firstNameFromEmail(st.updated_by)) + ' · ' + escapeHtml(formatStamp(st.updated_at)) + '</p>'
        : '';

      // One-click apply (the booking shortcut) — Angela-only.
      var applyUrl = (st && st.apply_url) || speakingRouteUrl(ev.speaking_route);
      var applyBtn = (applyUrl && window.isAngelaUser && window.isAngelaUser())
        ? '<a class="ops-apply-btn" href="' + escapeHtml(applyUrl) + '" target="_blank" rel="noopener">Apply to speak ↗</a>'
        : '';

      var _cdate = escapeHtml(cardDate(ev.date_str, ev.start_date, ev.end_date));
      var _cloc  = escapeHtml(shortLocation(ev));
      // Angela's working row: raw CFP date + contact cue + Apply, side by side.
      var _cDeadlineHtml = deadlineLine(ev.deadline, ev);
      var _cFootHtml = (_cDeadlineHtml || applyBtn || contactBadge) ? ('<div class="ops-card-foot">' + _cDeadlineHtml + contactBadge + applyBtn + '</div>') : '';
      card.innerHTML =
        '<div class="ops-card-head">' +
          '<h3 class="event-name">' +
            (_cardUrl
              ? '<a class="event-name-link" href="' + escapeHtml(_cardUrl) + '" target="_blank" rel="noopener" aria-label="Open website for ' + escapeHtml(ev.name) + '">' + escapeHtml(ev.name) + '<span class="event-link-arrow" aria-hidden="true">↗</span></a>'
              : escapeHtml(ev.name)) +
          '</h3>' +
          // Top-right cluster (shown on every card): star · hide · chat.
          '<div class="ops-chips">' +
            starButtonHtml(st.interested, st.attend_verdict) +
            '<button class="ops-chip urgent' + (st.urgent ? ' is-on' : '') + '" data-field="urgent" data-on="' + (st.urgent ? '1' : '0') + '" type="button">Urgent</button>' +
            (_catArchivedMe
              ? '<span class="ops-archived-tag" title="Archived for you — open the event to bring it back">Archived</span>'
              : '<button class="ops-archive-x ops-hover" data-archive type="button" title="Archive — for you only; teammates still see it" aria-label="Archive event for me">' + OPS_HIDE_ICON + '</button>') +
            decBadge + saBadge +
            '<span class="chat-count" data-chatkey="c' + escapeHtml(String(ev.num)) + '" style="display:none;" title="Discussion messages"></span>' +
          '</div>' +
        '</div>' +
        '<p class="event-meta">' + (_cdate ? '<span class="em-date">' + _cdate + '</span>' : '') + ((_cdate && _cloc) ? ' \\u00b7 ' : '') + (_cloc || '') + '</p>' +
        cardStatusLine(ev, st) +
        _cFootHtml;
      // (metaLine intentionally unused now — "Last edit" detail lived inside the
      // old inline editor, which has moved to the Details pop-up.)
      void metaLine;
      // Stash a modal record on the node for the delegated "Details" handler.
      var rec = {{}};
      for (var k in ev) {{ if (Object.prototype.hasOwnProperty.call(ev, k)) rec[k] = ev[k]; }}
      if (st) {{
        if (st.speaker) rec.speaker = st.speaker;
        if (st.notes)   rec.notes = st.notes;
        if (st.status)  rec.workflow_status = st.status;
        if (st.priority_override) rec.priority = st.priority_override;
        if (st.attend_verdict) rec.attend_verdict = st.attend_verdict;
        if (st.postmortem) rec.postmortem = st.postmortem;
        // Descriptive-field overrides edited in the pop-up — they live in
        // event_state and win over the read-only catalog value when set.
        ['why', 'about', 'focus_areas', 'typical_attendees', 'speaking_route',
         'pay_to_play', 'venue', 'contact_info', 'deadline', 'type',
         'url', 'apply_url', 'pricing', 'audience_type', 'past_speakers',
         'meeting_formats', 'attendee_count'].forEach(function (f) {{
          // '__cleared__' is an explicit "blank this out" sentinel — it WINS over
          // the catalog value (rendered as empty), so a deleted field stays deleted
          // instead of the catalog value popping back up.
          if (st[f] === '__cleared__') rec[f] = '';
          else if (st[f] != null && String(st[f]).trim() !== '') rec[f] = st[f];
        }});
        if (st.interested && st.interested.length) rec.interested = st.interested;
        if (st.attendees && st.attendees.length) rec.attendees = st.attendees;
        if (st.outreach_assignees && st.outreach_assignees.length) rec.outreach_assignees = st.outreach_assignees;
        if (st.outreach_note) rec.outreach_note = st.outreach_note;
        if (st.conflict_note) rec.conflict_note = st.conflict_note;
        if (st.follow_ups) rec.follow_ups = st.follow_ups;
        if (st.speaker_topic) rec.speaker_topic = st.speaker_topic;
        if (st.decision) rec.decision = st.decision;
        if (st.is_private != null) rec.is_private = !!st.is_private;
        if (st.updated_at) rec.updated_at = st.updated_at;   // drives the modal "Updated …" line
        rec.stage_tags = opsStages;
      }}
      rec.saved  = !!(st && st.saved);
      rec.hidden = !!(st && st.hidden);
      // Editing context for the modal's quick-actions / Edit Event button.
      rec._table = 'event_state'; rec._key = ev.num;
      rec.region = canonicalRegion(ev);
      card._modalRec = rec;
      // Scheduling conflict: derived (same person, overlapping dates) plus any
      // note Angela typed. Stamped on the card so the face and the hover peek
      // agree without recomputing.
      (function () {{
        var _r = card._modalRec || {{}};
        var _it = {{ kind: card.dataset.kind || (_r._table === 'manual_events' ? 'manual' : 'catalog'),
                    key: _r._key, name: _r.name, speaker: _r.speaker,
                    attendees: _r.attendees, start_date: _r.start_date, end_date: _r.end_date,
                    date_str: _r.date_str, startObj: _r, past: false, hidden: false,
                    stages: (card.dataset.statusTags || '').split('|').filter(Boolean) }};
        var _cl = [];
        try {{ _cl = visibleClashes(_it); }} catch (e) {{}}
        var _lbl = _cl.length ? clashLabel(_cl) : '';
        card.dataset.clash = _lbl;
        var _note = String(_r.conflict_note || '').trim();
        if (_lbl || _note) {{
          var _host = card.querySelector('.ops-status-line') || card.querySelector('.ops-meta');
          var _chip = '<span class="ops-clash" title="Scheduling conflict">&#9888; ' +
            (_note ? escapeHtml(_note) : _lbl) + '</span>';
          if (_host) _host.insertAdjacentHTML('afterend', _chip);
          else card.insertAdjacentHTML('beforeend', _chip);
        }}
      }})();
      return card;
    }}

    // Parse a tri-state select value ('true' / 'false' / '') into a
    // boolean or null — used for the Seed? / Urgent? dropdowns.
    function triBool(s) {{ s = (s == null ? '' : String(s)); return s === 'true' ? true : (s === 'false' ? false : null); }}

    // A pasted "example.com" without a scheme renders as a BROKEN relative
    // link on cards — normalize to https:// on save.
    function normUrl(v) {{
      v = (v == null ? '' : String(v)).trim();
      if (!v) return null;
      if (!/^https?:\\/\\//i.test(v)) v = 'https://' + v.replace(/^\\/+/, '');
      // Reject obviously-broken input (whitespace inside, unparseable, or a host
      // with no dot/TLD) so we never store a dead link that renders as a real
      // one. Only runs on save — existing stored URLs are untouched.
      if (/\\s/.test(v)) return null;
      try {{
        var u = new URL(v);
        if (!u.hostname || u.hostname.indexOf('.') === -1) return null;
      }} catch (e) {{ return null; }}
      return v;
    }}

    // Shared markup for the ArcticScout rich detail fields, used by BOTH the
    // "Add event" form (pass {{}}) and the per-card "Edit" form (pass mev).
    // External_id is intentionally omitted — it's a system provenance id.
    function richDetailFields(o) {{
      o = o || {{}};
      function v(k) {{ return escapeHtml(o[k] || ''); }}
      function triSel(name, cur) {{
        var t = (cur === true), f = (cur === false), n = (cur === null || cur === undefined);
        return '<select name="' + name + '">' +
          '<option value=""'      + (n ? ' selected' : '') + '>—</option>' +
          '<option value="true"'  + (t ? ' selected' : '') + '>Yes</option>' +
          '<option value="false"' + (f ? ' selected' : '') + '>No</option>' +
        '</select>';
      }}
      return '' +
        '<label><span class="key">About</span><textarea name="about">' + v('about') + '</textarea></label>' +
        '<label><span class="key">Topics</span><textarea name="focus_areas">' + v('focus_areas') + '</textarea></label>' +
        '<label><span class="key">Typical attendees</span><input type="text" name="typical_attendees" value="' + v('typical_attendees') + '"></label>' +
        '<label><span class="key">Speaking route</span><textarea name="speaking_route">' + v('speaking_route') + '</textarea></label>' +
        '<label><span class="key">Contact info</span><textarea name="contact_info">' + v('contact_info') + '</textarea></label>' +
        '<div class="row">' +
          '<label><span class="key">Deadline</span><input type="text" name="deadline" value="' + v('deadline') + '"></label>' +
          '<label><span class="key">Attendee count</span><input type="text" name="attendee_count" value="' + v('attendee_count') + '"></label>' +
        '</div>' +
        '<div class="row">' +
          '<label><span class="key">Audience (buyers vs sellers)</span><select name="audience_type">' + optionRows(['', 'Buyer-rich', 'Mixed', 'Vendor-heavy'], o.audience_type || '') + '</select></label>' +
          '<label><span class="key">Price to attend</span><input type="text" name="pricing" value="' + v('pricing') + '"></label>' +
        '</div>' +
        '<label><span class="key">Past / announced speakers (Title, Company)</span><textarea name="past_speakers" placeholder="e.g. CIO, UnitedHealth; Chief Data Officer, Pfizer">' + v('past_speakers') + '</textarea></label>' +
        '<label><span class="key">Meetings &amp; networking (guaranteed 1:1s, roundtables, attendee app)</span><input type="text" name="meeting_formats" value="' + v('meeting_formats') + '" placeholder="e.g. Hosted 1:1 meetings; roundtables; Brella app"></label>' +
        '<label><span class="key">Post-mortem (ROI)</span><input type="text" name="postmortem" value="' + v('postmortem') + '" placeholder="Contacts / meetings / sales vs cost"></label>' +
        '<div class="row">' +
          '<label><span class="key">Pay-to-play</span><select name="pay_to_play">' + optionRows(['', 'Yes', 'No', 'Unknown'], o.pay_to_play || '') + '</select></label>' +
          '<label><span class="key">Venue</span><input type="text" name="venue" value="' + v('venue') + '"></label>' +
        '</div>' +
        '<div class="row">' +
          '<label><span class="key">City</span><input type="text" name="city" value="' + v('city') + '"></label>' +
          '<label><span class="key">Country</span><input type="text" name="country" value="' + v('country') + '"></label>' +
        '</div>' +
        '<div class="row">' +
          '<label><span class="key">Seed?</span>' + triSel('seed', o.seed) + '</label>' +
          '<label><span class="key">Urgent?</span>' + triSel('urgent', o.urgent) + '</label>' +
        '</div>';
    }}

    function buildManualCard(mev, email) {{
      var card = document.createElement('article');
      card.className = 'ops-card';
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      card.dataset.manualId = mev.id;
      card.dataset.kind = 'manual';
      card.dataset.region = canonicalRegion(mev);
      card.dataset.hasSpeaker = (mev.speaker && mev.speaker.trim()) ? '1' : '';
      card.dataset.status = mev.status || '';
      var manualStages = stageTagsOf(mev);
      card.dataset.statusTags = manualStages.join('|');
      card.dataset.priority = mev.priority || '';
      card.dataset.speaker  = (mev.speaker || '');
      card.dataset.audience = (mev.audience_type || '');
      var _mpn = priceNumOf(mev.pricing);
      card.dataset.price    = (_mpn == null ? '' : String(_mpn));
      card.dataset.meetings = (mev.meeting_formats ? '1' : '');
      card.dataset.attend   = (mev.attend_verdict || '');
      card.dataset.interested = (mev.interested && mev.interested.length) ? '1' : '';
      card.dataset.interestedNames = (mev.interested || []).map(function (n) {{ return String(n).toLowerCase(); }}).join('|');
      card.dataset.attendeeNames = (mev.attendees || []).map(function (n) {{ return String(n).toLowerCase(); }}).join('|');
      card.dataset.briefReady = (mev.briefing_json ? '1' : '');   // Day-Of brief pre-generated?
      card.dataset.fitText = abFold([mev.name, mev.about, mev.focus_areas, mev.typical_attendees, mev.location, mev.city, mev.country, mev.type, mev.past_speakers, mev.audience_type].join(' '));
      // Non-English event title -> off Thor's / Verma's / Joe's fit lists.
      card.dataset.foreignLang = _isForeignLangEvent(mev) ? '1' : '';
      // Signals the per-person "Not for me" veto scores against (see _vetoScore).
      card.dataset.vetoOrg  = _orgKeyOf(mev);
      // follow_ups / conflict_note live on the manual row itself.
      card.dataset.vetoCity = _lesserCityOf(mev);
      var _manPast = isPastEvent(mev);
      card.dataset.past = _manPast ? '1' : '';
      if (_manPast) card.classList.add('is-past');
      // Urgent = an apply/CFP deadline that's closing soon (not just upcoming).
      var _manSoon = isDeadlineSoon(mev.deadline) && !_manPast;
      if (_manSoon) card.dataset.deadlineSoon = '1';
      if (isDeadlineUrgent(mev.deadline) && !_manPast) card.classList.add('is-urgent');
      card.dataset.decision = (mev.decision || '');
      // "✓ Go" is Angela's promotion call — Angela-only on the card face.
      var mDecBadge = (mev.decision === 'go' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="decision-badge go">✓ Go</span>' : '';
      // Should-Attend is now the blue card outline (is-sa), not a face badge.
      var mSaBadge = '';
      card.dataset.contactFound = hasEmailContact(mev) ? '1' : '';
      // Contact (POC) badge is Angela's outreach cue — only she sees it on the card.
      var mContactBadge = (card.dataset.contactFound === '1' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="contact-badge" title="We have a contact for this event — a name, an email or both">✉ Contact</span>' : '';
      // "Recently added" means UNTRIAGED-and-new. Once someone has worked the
      // event — tagged it, written a note, flagged it for a teammate, archived
      // it — it isn't new to Angela any more, so it drops the yellow outline and
      // leaves the "Recently added" filter even inside the 7-day window. It was
      // still showing up as new after she'd already dealt with it.
      var mRecent = isRecentlyAdded(mev.created_at) && !opsHandled({{
        hidden: _isArchivedForMe(true, mev.id, mev.hidden === true),
        queue_dismissed: mev.queue_dismissed,
        stages: manualStages,
        workflow_status: mev.status,
        notes: mev.notes,
        interested: mev.interested,
        attendees: mev.attendees,
        outreach_assignees: mev.outreach_assignees,
        speaker: mev.speaker,
        decision: mev.decision
      }});
      card.dataset.recent = mRecent ? '1' : '';
      // Recently added now shows as a YELLOW card outline, no label — a triage cue
      // for support (Angela/Hurley), the same audience the old "Recently Added"
      // badge served. dataset.recent still drives the "Recently added" filter.
      if (mRecent && isSupportPerson(getCollabName() || '')) card.classList.add('is-recent');
      var mRecentBadge = '';
      var manualMeta = opsMonthMeta(mev.start_date, mev.date_str);
      card.dataset.month = manualMeta.key;
      card.dataset.monthLabel = manualMeta.label;
      card.dataset.sort = manualMeta.sort;
      var whoText  = mev.created_by ? ('Added by ' + escapeHtml(firstNameFromEmail(mev.created_by)) + ' · ' + escapeHtml(formatStamp(mev.created_at))) : '';
      var whoTitle = mev.created_by ? (' title="' + escapeHtml(mev.created_by) + '"') : '';
      var who      = whoText;

      // The card face stays minimal: name, date · place, ONE derived status
      // line, chat count. Everything else (POC / notes / fee / priority /
      // per-person rosters) lives in the Details pop-up.
      var tagsHtml = cardStatusLine(mev, mev);
      var mApplyUrl = mev.apply_url || speakingRouteUrl(mev.speaking_route);
      var mApplyBtn = (mApplyUrl && window.isAngelaUser && window.isAngelaUser())
        ? '<a class="ops-apply-btn" href="' + escapeHtml(mApplyUrl) + '" target="_blank" rel="noopener">Apply to speak ↗</a>'
        : '';
      // Angela's working row: raw CFP date + contact cue + Apply, side by side.
      var _mDeadlineHtml = deadlineLine(mev.deadline, mev);
      var _mFootHtml = (_mDeadlineHtml || mApplyBtn || mContactBadge) ? ('<div class="ops-card-foot">' + _mDeadlineHtml + mContactBadge + mApplyBtn + '</div>') : '';
      var _mdate = escapeHtml(cardDate(mev.date_str, mev.start_date, mev.end_date));
      var _mloc  = escapeHtml(shortLocation(mev));
      // Private events have no public page — a scraped URL is usually wrong, so
      // never link the card title for them (Angela).
      var _mCardUrl = (mev.is_private === true) ? '' : mev.url;
      card.innerHTML =
        '<div class="ops-card-head">' +
          '<h3 class="event-name">' +
            (_mCardUrl
              ? '<a class="event-name-link" href="' + escapeHtml(_mCardUrl) + '" target="_blank" rel="noopener" aria-label="Open website for ' + escapeHtml(mev.name || '') + '">' + escapeHtml(mev.name || '') + '<span class="event-link-arrow" aria-hidden="true">↗</span></a>'
              : escapeHtml(mev.name || '')) +
          '</h3>' +
          // Top-right cluster (shown on every card): star · hide · chat.
          '<div class="ops-chips">' +
            starButtonHtml(mev.interested, mev.attend_verdict) +
            '<button class="ops-chip urgent' + (mev.urgent ? ' is-on' : '') + '" data-field="urgent" data-on="' + (mev.urgent ? '1' : '0') + '" type="button">Urgent</button>' +
            (_isArchivedForMe(true, mev.id, mev.hidden === true)
              ? '<span class="ops-archived-tag" title="Archived for you — open the event to bring it back">Archived</span>'
              : '<button class="ops-archive-x ops-hover" data-archive type="button" title="Archive — for you only; teammates still see it" aria-label="Archive event for me">' + OPS_HIDE_ICON + '</button>') +
            mDecBadge + mSaBadge + mRecentBadge +
            '<span class="chat-count" data-chatkey="m' + escapeHtml(String(mev.id)) + '" style="display:none;" title="Discussion messages"></span>' +
          '</div>' +
        '</div>' +
        '<p class="event-meta">' + (_mdate ? '<span class="em-date">' + _mdate + '</span>' : '') + ((_mdate && _mloc) ? ' \\u00b7 ' : '') + (_mloc || '') + '</p>' +
        tagsHtml +
        _mFootHtml;
      // Stash a modal record on the node for the delegated "Details" handler.
      var mrec = {{}};
      for (var mk in mev) {{ if (Object.prototype.hasOwnProperty.call(mev, mk)) mrec[mk] = mev[mk]; }}
      mrec.workflow_status = mev.status || null;
      mrec.stage_tags = manualStages;
      // Editing context for the modal's quick-actions / Edit Event button.
      mrec._table = 'manual_events'; mrec._key = mev.id;
      mrec.region = canonicalRegion(mev);
      card._modalRec = mrec;
      // Scheduling conflict: derived (same person, overlapping dates) plus any
      // note Angela typed. Stamped on the card so the face and the hover peek
      // agree without recomputing.
      (function () {{
        var _r = card._modalRec || {{}};
        var _it = {{ kind: card.dataset.kind || (_r._table === 'manual_events' ? 'manual' : 'catalog'),
                    key: _r._key, name: _r.name, speaker: _r.speaker,
                    attendees: _r.attendees, start_date: _r.start_date, end_date: _r.end_date,
                    date_str: _r.date_str, startObj: _r, past: false, hidden: false,
                    stages: (card.dataset.statusTags || '').split('|').filter(Boolean) }};
        var _cl = [];
        try {{ _cl = visibleClashes(_it); }} catch (e) {{}}
        var _lbl = _cl.length ? clashLabel(_cl) : '';
        card.dataset.clash = _lbl;
        var _note = String(_r.conflict_note || '').trim();
        if (_lbl || _note) {{
          var _host = card.querySelector('.ops-status-line') || card.querySelector('.ops-meta');
          var _chip = '<span class="ops-clash" title="Scheduling conflict">&#9888; ' +
            (_note ? escapeHtml(_note) : _lbl) + '</span>';
          if (_host) _host.insertAdjacentHTML('afterend', _chip);
          else card.insertAdjacentHTML('beforeend', _chip);
        }}
      }})();

      if (_isArchivedForMe(true, mev.id, mev.hidden === true)) card.classList.add('is-archived');
      if (mev.saved)  card.classList.add('is-saved');
      if (meInInterested(mev.interested)) card.classList.add('is-mine');   // I starred it → blue outline
      // Angela's Should-Attend shows as the same blue outline (was the badge).
      if (window.isAngelaUser && window.isAngelaUser() && shouldAttendKind(mev.attend_verdict) === 'human') card.classList.add('is-sa');
      if (mev.urgent) card.classList.add('is-urgent');
      // Star = "I'm interested" (per-signed-in-person), not a shared bookmark.
      // For Angela it's a Should-Attend flag (see toggleMyInterest).
      var _manStar = card.querySelector('.saved-star');
      if (_manStar) _manStar.addEventListener('click', function () {{
        _manStar.setAttribute('aria-busy', 'true');
        toggleMyInterest('manual', mev.id, mev.interested, mev.attend_verdict);
      }});
      // Boolean toggles (urgent/hidden) — same UX as catalog cards, but
      // written to manual_events. Needs the columns from
      // scripts/2026-06-18_manual_events_toggles.sql; until that runs,
      // sbWriteRetry strips the unknown column and we warn instead of pretending.
      card.querySelectorAll('[data-field][data-on]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          var field = btn.dataset.field;
          var nextOn = btn.dataset.on !== '1';
          btn.setAttribute('aria-busy', 'true');
          var patch = {{}}; patch[field] = nextOn;
          sbWriteRetry(patch, function (p) {{ return sb.from('manual_events').update(p).eq('id', mev.id); }}).then(function (resp) {{
            btn.removeAttribute('aria-busy');
            if (resp.error) {{ status('Save failed: ' + resp.error.message, 'error'); return; }}
            if (resp.strippedMigrationCols && resp.strippedMigrationCols.indexOf(field) !== -1) {{
              status('Run scripts/2026-06-18_manual_events_toggles.sql in Supabase to enable ' + field + ' on manual events.', 'warn');
              return;
            }}
            btn.dataset.on = nextOn ? '1' : '0';
            btn.classList.toggle('is-on', nextOn);
            mev[field] = nextOn;
            if (field === 'saved') {{ btn.textContent = nextOn ? '★' : '☆'; card.classList.toggle('is-saved', nextOn); }}
            else if (field === 'urgent') {{ card.classList.toggle('is-urgent', nextOn); }}
            flashOk();
          }});
        }});
      }});
      // Archive (hover ×) — personal, localStorage only (hides from MY grid).
      var _manArch = card.querySelector('[data-archive]');
      if (_manArch) _manArch.addEventListener('click', function () {{
        _archSetMine(true, mev.id, true);
        card.classList.add('is-archived');
        _manArch.outerHTML = '<span class="ops-archived-tag" title="Archived for you — open the event to bring it back">Archived</span>';
        regroupOpsByMonth();
        applyFilters();
        flashOk();
      }});
      return card;
    }}

    function wireManualCard(card, email) {{
      var form = card.querySelector('form.manual-edit');
      if (!form) return;
      var id = parseInt(card.dataset.manualId, 10);

      form.addEventListener('submit', function (ev) {{
        ev.preventDefault();
        var fd = new FormData(form);
        var paidRaw = (fd.get('paid') || '').toString();
        var patch = {{
          name:                (fd.get('name') || '').toString().trim(),
          date_str:            (fd.get('date_str') || '').toString().trim(),
          location:            (fd.get('location') || '').toString().trim() || null,
          region:              (fd.get('region') || '').toString().trim() || null,
          type:                (fd.get('type') || '').toString().trim() || null,
          priority:            (fd.get('priority') || '').toString().trim() || null,
          status:              (fd.get('status') || '').toString().trim() || null,
          status_tags:         normalizeStageTags(fd.getAll('status_tags')),
          submission_status:   (fd.get('submission_status') || '').toString().trim() || null,
          speaker:             (fd.get('speaker') || '').toString().trim() || null,
          poc_name:            (fd.get('poc_name') || '').toString().trim() || null,
          poc_email:           (fd.get('poc_email') || '').toString().trim() || null,
          poc_linkedin:        (fd.get('poc_linkedin') || '').toString().trim() || null,
          additional_contacts: (fd.get('additional_contacts') || '').toString().trim() || null,
          why:                 (fd.get('why') || '').toString().trim() || null,
          notes:               (fd.get('notes') || '').toString().trim() || null,
          speaking_fee:        (fd.get('speaking_fee') || '').toString().trim() || null,
          paid:                paidRaw === 'true' ? true : (paidRaw === 'false' ? false : null),
          url:                 normUrl(fd.get('url')),
          about:               (fd.get('about') || '').toString().trim() || null,
          focus_areas:         (fd.get('focus_areas') || '').toString().trim() || null,
          typical_attendees:   (fd.get('typical_attendees') || '').toString().trim() || null,
          speaking_route:      (fd.get('speaking_route') || '').toString().trim() || null,
          contact_info:        (fd.get('contact_info') || '').toString().trim() || null,
          deadline:            (fd.get('deadline') || '').toString().trim() || null,
          attendee_count:      (fd.get('attendee_count') || '').toString().trim() || null,
          audience_type:       (fd.get('audience_type') || '').toString().trim() || null,
          pricing:             (fd.get('pricing') || '').toString().trim() || null,
          past_speakers:       (fd.get('past_speakers') || '').toString().trim() || null,
          meeting_formats:     (fd.get('meeting_formats') || '').toString().trim() || null,
          attend_verdict:      (fd.get('attend_verdict') || '').toString().trim() || null,
          postmortem:          (fd.get('postmortem') || '').toString().trim() || null,
          pay_to_play:         (fd.get('pay_to_play') || '').toString().trim() || null,
          venue:               (fd.get('venue') || '').toString().trim() || null,
          city:                (fd.get('city') || '').toString().trim() || null,
          country:             (fd.get('country') || '').toString().trim() || null,
          seed:                triBool(fd.get('seed')),
          urgent:              triBool(fd.get('urgent'))
        }};
        if (!patch.name) {{ alert('Name is required'); return; }}
        if (!patch.date_str) patch.date_str = 'Date TBD';
        // Re-derive start_date / end_date from date_str (best effort)
        var derived = deriveDatesFromText(patch.date_str);
        if (derived.start_date) patch.start_date = derived.start_date;
        if (derived.end_date)   patch.end_date   = derived.end_date;
        // Unreadable date → start_date null → event won't show on the calendar.
        var unparsedDate = (patch.date_str !== 'Date TBD') && !patch.start_date;
        // Rename-into-existing guard: a fresh name must not collide with
        // another manual event or anything in the catalog.
        var dup = findDuplicate(patch.name, id, patch);
        if (dup) {{
          var srcLabel = dup.source === 'catalog'
            ? 'the public ArcticBlue catalog (events.json)'
            : 'another manual event';
          alert('Renaming to "' + patch.name + '" would collide with ' + srcLabel + '. Pick a different name.');
          return;
        }}
        var btn = form.querySelector('button.primary[type="submit"]');
        btn.disabled = true; btn.textContent = 'Saving…';
        sbWriteRetry(patch, function (p) {{ return sb.from('manual_events').update(p).eq('id', id); }}).then(function (resp) {{
          btn.disabled = false; btn.textContent = 'Save changes';
          if (resp.error) {{
            if (resp.error.code === '23505' || /duplicate key value|unique/i.test(resp.error.message || '')) {{
              status('Another event with that name exists — pick a different one.', 'warn');
              loadKnownNames();
              return;
            }}
            status('Save failed: ' + resp.error.message, 'error');
            return;
          }}
          if (resp.strippedMigrationCols) {{
            status('Saved — but ' + resp.strippedMigrationCols.join(', ') +
                   ' could not be stored until the DB migration runs.', 'warn');
          }} else if (unparsedDate) {{
            status('Saved, but I couldn’t read a date from "' + patch.date_str + '" — it won’t show on the calendar until you enter a date like "September 12, 2026".', 'warn');
          }} else {{
            flashOk('Manual event saved');
          }}
          loadKnownNames();
          renderOps(email);
        }});
      }});

      var delBtn = form.querySelector('[data-delete]');
      delBtn.addEventListener('click', function () {{
        var name = (form.querySelector('input[name="name"]').value || '').trim();
        if (!confirm('Delete "' + (name || 'this manual event') + '"? This cannot be undone.')) return;
        delBtn.disabled = true; delBtn.textContent = 'Deleting…';
        var _dLoc = form.querySelector('input[name="location"]');
        var _dStart = form.querySelector('input[name="start_date"]');
        sb.from('manual_events').delete().eq('id', id).then(function (resp) {{
          delBtn.disabled = false; delBtn.textContent = 'Delete event';
          if (resp.error) {{ status('Delete failed: ' + resp.error.message, 'error'); return; }}
          // Same backlog the modal's delete writes to — keeps the nightly ingest
          // from re-adding this one whichever button was used.
          if (window.opsRecordDeleted) window.opsRecordDeleted({{
            table: 'manual_events', key: id, name: name,
            start_date: _dStart ? _dStart.value : '',
            location:   _dLoc ? _dLoc.value : ''
          }});
          card.remove();
          updateOpsCount();
          loadKnownNames();   // freed-up name is now valid for reuse
          flashOk('Manual event deleted');
        }});
      }});
    }}

    function wireOpsCard(card, email) {{
      var num = parseInt(card.dataset.eventNum, 10);

      // Pipeline-stage checkboxes — save the whole status_tags array on any
      // toggle. The ops editor isn't a <form>, so we gather by [data-stage].
      var stageBoxes = card.querySelectorAll('input[type="checkbox"][data-stage]');
      if (stageBoxes.length) {{
        stageBoxes.forEach(function (box) {{
          box.addEventListener('change', function () {{
            var tags = normalizeStageTags(
              Array.prototype.map.call(stageBoxes, function (b) {{ return b.checked ? b.value : null; }})
            );
            box.closest('label').classList.toggle('is-on', box.checked);
            upsertEventState(num, {{ status_tags: tags }}, email).then(function (err) {{
              if (err) {{ status('Save failed: ' + err.message, 'error'); return; }}
              card.dataset.statusTags = tags.join('|');
              // Refresh the visible pills + calendar tint on next render.
              var pillHost = card.querySelector('.ops-tags');
              if (pillHost) {{
                var stagePills = pillHost.querySelectorAll('.ops-tag.stage');
                stagePills.forEach(function (p) {{ p.remove(); }});
                if (tags.length) pillHost.insertAdjacentHTML('afterbegin', renderStagePills(tags));
                // Re-evaluate the legacy tag: it's hidden while it repeats a
                // stage pill, so toggling that stage must show/hide it too.
                var legacyVal = (card.dataset.status || '').trim();
                var legacyEl = pillHost.querySelector('.ops-tag.status.legacy');
                var isDup = legacyVal && tags.some(function (k) {{ return k.toLowerCase() === legacyVal.toLowerCase(); }});
                if (legacyEl && isDup) legacyEl.remove();
                if (!legacyEl && legacyVal && !isDup) {{
                  var ls = statusStyle(legacyVal);
                  pillHost.insertAdjacentHTML('beforeend',
                    '<span class="ops-tag status legacy"' + (ls ? ' style="' + ls + '"' : '') +
                    ' title="Legacy status detail">' + escapeHtml(legacyVal) + '</span>');
                }}
              }}
              applyFilters();
              flashOk();
            }});
          }});
        }});
      }}

      // Star = "I'm interested" (per-signed-in-person), not a shared bookmark.
      var _catStar = card.querySelector('.saved-star');
      if (_catStar) _catStar.addEventListener('click', function () {{
        _catStar.setAttribute('aria-busy', 'true');
        toggleMyInterest('catalog', num, (card._modalRec && card._modalRec.interested) || [], card.dataset.attend);
      }});
      // Boolean toggles (urgent + hidden chips)
      card.querySelectorAll('[data-field][data-on]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          var field = btn.dataset.field;
          var nextOn = btn.dataset.on !== '1';
          btn.setAttribute('aria-busy', 'true');
          var patch = {{}};
          patch[field] = nextOn;
          upsertEventState(num, patch, email).then(function (err) {{
            btn.removeAttribute('aria-busy');
            if (err) {{ status('Save failed: ' + err.message, 'error'); return; }}
            btn.dataset.on = nextOn ? '1' : '0';
            btn.classList.toggle('is-on', nextOn);
            if (field === 'saved') {{
              btn.textContent = nextOn ? '★' : '☆';
              card.classList.toggle('is-saved', nextOn);
            }} else if (field === 'urgent') {{
              card.classList.toggle('is-urgent', nextOn);
            }}
            flashOk();
          }});
        }});
      }});
      // Archive (the hover × on the card face) — hides the event from MY view
      // only (localStorage, per signed-in name). No DB write, no effect on
      // teammates. Un-archive is done from the Details pop-up.
      var _catArch = card.querySelector('[data-archive]');
      if (_catArch) _catArch.addEventListener('click', function () {{
        _archSetMine(false, num, true);
        card.classList.add('is-archived');
        _catArch.outerHTML = '<span class="ops-archived-tag" title="Archived for you — open the event to bring it back">Archived</span>';
        regroupOpsByMonth();
        applyFilters();
        flashOk();
      }});

      // Text inputs (status, speaker) — save on blur if changed
      card.querySelectorAll('input[type="text"][data-field]').forEach(function (inp) {{
        var initial = inp.value;
        inp.addEventListener('blur', function () {{
          if (inp.value === initial) return;
          initial = inp.value;
          var patch = {{}};
          patch[inp.dataset.field] = inp.value.trim() || null;
          upsertEventState(num, patch, email).then(function (err) {{
            if (err) {{ status('Save failed: ' + err.message, 'error'); return; }}
            flashOk();
          }});
        }});
      }});

      // Selects (status, priority_override, track) — save on change
      card.querySelectorAll('select[data-field]').forEach(function (sel) {{
        sel.addEventListener('change', function () {{
          var patch = {{}};
          patch[sel.dataset.field] = sel.value || null;
          upsertEventState(num, patch, email).then(function (err) {{
            if (err) {{ status('Save failed: ' + err.message, 'error'); return; }}
            // Mirror the new value onto the card's data-attributes so the
            // filter chip rows + status group color see the change without
            // waiting for the next renderOps.
            var f = sel.dataset.field;
            if (f === 'status') {{
              card.dataset.status = sel.value || '';
              // Refresh the visible legacy tag immediately (re-renders are
              // paused while the editor is open). Same rule as renderOpsTags:
              // show it unless it exactly repeats a stage pill.
              var host = card.querySelector('.ops-tags');
              if (!host) {{
                host = document.createElement('div');
                host.className = 'ops-tags';
                var det = card.querySelector('details.ops-edit');
                if (det) card.insertBefore(host, det);
              }}
              var oldLegacy = host.querySelector('.ops-tag.status.legacy');
              if (oldLegacy) oldLegacy.remove();
              var v = (sel.value || '').trim();
              if (v) {{
                var dupPill = Array.prototype.some.call(
                  host.querySelectorAll('.ops-tag.stage'),
                  function (p) {{ return p.textContent.trim().toLowerCase() === v.toLowerCase(); }});
                if (!dupPill) {{
                  var lstyle = statusStyle(v);
                  host.insertAdjacentHTML('beforeend',
                    '<span class="ops-tag status legacy"' + (lstyle ? ' style="' + lstyle + '"' : '') +
                    ' title="Legacy status detail">' + escapeHtml(v) + '</span>');
                }}
              }}
            }}
            if (f === 'priority_override') card.dataset.priority = sel.value || '';
            if (f === 'attend_verdict')    card.dataset.attend   = sel.value || '';
            applyFilters();
            flashOk();
          }});
        }});
      }});

      // Speaker (text input) — refresh data-speaker + data-hasSpeaker on save
      card.querySelectorAll('input[data-field="speaker"]').forEach(function (inp) {{
        inp.addEventListener('blur', function () {{
          // The generic text handler above already wrote to Supabase;
          // we just need to keep the card's data attributes consistent.
          card.dataset.speaker     = inp.value || '';
          card.dataset.hasSpeaker  = inp.value && inp.value.trim() ? '1' : '';
          applyFilters();
        }});
      }});

      // Textarea (notes) — save on blur if changed
      card.querySelectorAll('textarea[data-field]').forEach(function (ta) {{
        var initial = ta.value;
        ta.addEventListener('blur', function () {{
          if (ta.value === initial) return;
          initial = ta.value;
          var patch = {{}};
          patch[ta.dataset.field] = ta.value.trim() || null;
          upsertEventState(num, patch, email).then(function (err) {{
            if (err) {{ status('Save failed: ' + err.message, 'error'); return; }}
            flashOk();
          }});
        }});
      }});
    }}

    function updateOpsCount() {{
      // Count only active (non-past) events — archived events now live in the
      // grid too (collapsible Archive group), but shouldn't inflate "tracked".
      var regular = $opsGrid.querySelectorAll('.ops-card[data-kind="regular"]:not([data-past="1"])').length;
      var manual  = $opsGrid.querySelectorAll('.ops-card[data-kind="manual"]:not([data-past="1"])').length;
      var $count = document.getElementById('ops-count');
      if (!$count) return;
      $count.textContent = regular + ' tracked · ' + manual + ' manual';
    }}

    // ── Priority + Track + Speakers filter rows ────────────────────
    function _makeExtraChip(value, label, extraClass) {{
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'extra-chip' + (extraClass ? ' ' + extraClass : '');
      btn.dataset.value = value;
      btn.textContent = label;
      btn.setAttribute('aria-pressed', 'false');
      btn.title = 'Click to filter by ' + label;
      btn.addEventListener('click', function () {{
        btn.classList.toggle('is-on');
        applyFilters();
      }});
      return btn;
    }}

    function buildExtraFilters() {{
      // Priority (static)
      var pri = document.querySelector('#filter-priority .filter-dd-menu');
      if (pri && pri.dataset.built !== '1') {{
        ['High', 'Medium', 'Low'].forEach(function (v) {{
          pri.appendChild(_makeExtraChip(v, v, 'pri-' + v.toLowerCase()));
        }});
        var clr = document.createElement('button');
        clr.type = 'button'; clr.className = 'extra-clear'; clr.textContent = 'Clear';
        clr.addEventListener('click', function () {{
          pri.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
          applyFilters();
        }});
        pri.appendChild(clr);
        pri.dataset.built = '1';
      }}
      // Ticket price (multi-select bubbles — pick any bands)
      var prc = document.querySelector('#filter-price .filter-dd-menu');
      if (prc && prc.dataset.built !== '1') {{
        [['free', 'Free'], ['lt1000', 'Under $1,000'], ['1000-2500', '$1,000 – $2,500'],
         ['gte2500', '$2,500+ (buyer-rich)'], ['known', 'Price known']].forEach(function (p) {{
          prc.appendChild(_makeExtraChip(p[0], p[1], 'price-chip'));
        }});
        var clrP = document.createElement('button');
        clrP.type = 'button'; clrP.className = 'extra-clear'; clrP.textContent = 'Clear';
        clrP.addEventListener('click', function () {{
          prc.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
          applyFilters();
        }});
        prc.appendChild(clrP);
        prc.dataset.built = '1';
      }}
      // Fits: teammate ICP profiles (multi-select bubbles)
      var fit = document.querySelector('#filter-fits .filter-dd-menu');
      if (fit && fit.dataset.built !== '1') {{
        ['Jerome', 'Joe', 'Thor', 'Verma', 'Carlos'].forEach(function (n) {{
          fit.appendChild(_makeExtraChip(n, n, 'fits-chip'));
        }});
        var clrF = document.createElement('button');
        clrF.type = 'button'; clrF.className = 'extra-clear'; clrF.textContent = 'Clear';
        clrF.addEventListener('click', function () {{
          fit.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
          applyFilters();
        }});
        fit.appendChild(clrF);
        fit.dataset.built = '1';
      }}
      // Should attend: team hand-picks + AI recommendations (multi-select bubbles)
      var sha = document.querySelector('#filter-should .filter-dd-menu');
      if (sha && sha.dataset.built !== '1') {{
        sha.appendChild(_makeExtraChip('human', 'Team pick', 'should-team'));
        sha.appendChild(_makeExtraChip('ai', 'AI pick', 'should-ai'));
        var clrS = document.createElement('button');
        clrS.type = 'button'; clrS.className = 'extra-clear'; clrS.textContent = 'Clear';
        clrS.addEventListener('click', function () {{
          sha.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
          applyFilters();
        }});
        sha.appendChild(clrS);
        sha.dataset.built = '1';
      }}
    }}

    // Priority / Track / Speaking / Attending are dropdowns (button + popup of
    // chips) — same pattern as the Months menu. The chips inside keep their
    // existing is-on toggle + applyFilters, so the filter logic is unchanged.
    function updateFilterDropdownCounts() {{
      Array.prototype.forEach.call(document.querySelectorAll('.filter-dd'), function (dd) {{
        var n = dd.querySelectorAll('.filter-dd-menu .extra-chip.is-on').length;
        var cnt = dd.querySelector('.dd-count');
        var btn = dd.querySelector('.filter-dd-btn');
        if (cnt) cnt.textContent = n ? (' · ' + n) : '';
        if (btn) btn.classList.toggle('has-active', n > 0);
      }});
    }}

    function _closeFilterDropdowns() {{
      Array.prototype.forEach.call(document.querySelectorAll('.filter-dd-menu.open'), function (m) {{ m.classList.remove('open'); }});
      Array.prototype.forEach.call(document.querySelectorAll('.filter-dd-btn[aria-expanded="true"]'), function (b) {{ b.setAttribute('aria-expanded', 'false'); }});
    }}

    function wireFilterDropdowns() {{
      Array.prototype.forEach.call(document.querySelectorAll('.filter-dd'), function (dd) {{
        var btn = dd.querySelector('.filter-dd-btn');
        var menu = dd.querySelector('.filter-dd-menu');
        if (!btn || !menu || menu.dataset.wired) return;
        menu.dataset.wired = '1';
        btn.addEventListener('click', function (e) {{
          e.stopPropagation();
          var willOpen = !menu.classList.contains('open');
          _closeFilterDropdowns();
          if (willOpen) {{ menu.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); }}
        }});
        menu.addEventListener('click', function (e) {{ e.stopPropagation(); }});
      }});
      if (!document.body.dataset.ddOutside) {{
        document.body.dataset.ddOutside = '1';
        document.addEventListener('click', _closeFilterDropdowns);
        document.addEventListener('keydown', function (e) {{ if (e.key === 'Escape') _closeFilterDropdowns(); }});
      }}
      updateFilterDropdownCounts();
    }}

    // How many filters are currently engaged (so the collapsed toggle can say
    // "Filters · N active" — otherwise an active filter would be invisible).
    function countActiveOpsFilters() {{
      var n = 0;
      ['ops-f-submitted', 'ops-f-recent'].forEach(function (id) {{ var e = document.getElementById(id); if (e && e.checked) n++; }});
      ['filter-price', 'filter-priority', 'filter-speaker'].forEach(function (id) {{
        var box = document.getElementById(id);
        if (box && box.querySelector('.filter-dd-btn.has-active')) n++;
      }});
      return n;
    }}
    function updateFilterToggle() {{
      var $ft = document.getElementById('ops-filter-toggle');
      var $badge = document.getElementById('tf-active-count');
      if (!$ft) return;
      // Every non-status filter (region/months/pipeline/… + the checkboxes and
      // search) lives behind this one icon — show a dot when any is engaged so
      // an active filter is never invisible. Search is a visible input, so it
      // doesn't count toward the "hidden filters active" dot.
      var n = countActiveOpsFilters() + countActiveTopFilters();
      var $search = document.getElementById('ops-search');
      if ($search && ($search.value || '').trim()) n--;   // search is visible, not hidden
      $ft.classList.toggle('has-active', n > 0);
      if ($badge) $badge.hidden = !(n > 0);
    }}
    function wireFilterToggle() {{
      var $ft = document.getElementById('ops-filter-toggle');
      var $drawer = document.getElementById('tf-drawer');
      if (!$ft || !$drawer || $ft.dataset.wired) return;
      $ft.dataset.wired = '1';
      $ft.addEventListener('click', function (e) {{
        e.stopPropagation();
        var open = $drawer.hidden;
        $drawer.hidden = !open;
        $ft.setAttribute('aria-expanded', open ? 'true' : 'false');
      }});
      // Click outside the drawer (and not on the icon) closes it.
      document.addEventListener('click', function (e) {{
        if ($drawer.hidden) return;
        if ($drawer.contains(e.target) || $ft.contains(e.target)) return;
        $drawer.hidden = true; $ft.setAttribute('aria-expanded', 'false');
      }});
      updateFilterToggle();
    }}

    // How many of the everyone-visible TOP filter bar's dimensions (Pipeline /
    // Region / Fits / Months / Should-attend + search) are currently engaged —
    // separate from countActiveOpsFilters() above, which only covers Angela's
    // collapsed power-user panel. A live filter is easy to forget you set
    // (esp. Region/Months), so this stays visible to everyone, with one-click
    // "Clear all" (reuses clearOpsFilters(), which already resets both bars).
    function countActiveTopFilters() {{
      var n = 0;
      var $search = document.getElementById('ops-search');
      if ($search && ($search.value || '').trim()) n++;
      ['filter-pipeline', 'filter-region', 'filter-fits', 'filter-months', 'filter-should'].forEach(function (id) {{
        var box = document.getElementById(id);
        if (box && box.style.display !== 'none' && box.querySelector('.extra-chip.is-on')) n++;
      }});
      return n;
    }}
    function updateActiveTopFiltersBanner() {{
      var $el = document.getElementById('ops-active-filters');
      if (!$el) return;
      var n = countActiveTopFilters();
      if (!n) {{ $el.hidden = true; $el.innerHTML = ''; return; }}
      $el.hidden = false;
      $el.innerHTML = n + ' filter' + (n === 1 ? '' : 's') + ' active &mdash; <button type="button" id="ops-clear-top-filters">Clear all</button>';
      var $btn = document.getElementById('ops-clear-top-filters');
      if ($btn) $btn.addEventListener('click', clearOpsFilters);
    }}

    // The extra "Filters" panel (ticket price / priority / track / speaking +
    // Submitted / Recently added / Contact found) is Angela's power-user set —
    // only show the toggle when the signed-in name is Angela. Everyone else
    // keeps the top-line dropdowns + search, but never sees the hidden filters.
    // Re-run on sign-in (route) and whenever the collaborator name changes.
    // Global (the detail modal lives in a separate closure and needs this too).
    window.isAngelaUser = function () {{
      return (getCollabName() || '').toLowerCase().indexOf('angela') !== -1;
    }};
    function isAngelaUser() {{ return window.isAngelaUser(); }}
    function applyFilterVisibility() {{
      var show = isAngelaUser();
      // The "My Lineup" tab reads "Team Lineup" for support (Angela/Hurley),
      // since their view is the whole team's, not their own.
      var $myTab = document.querySelector('.view-toggle [data-view="myevents"]');
      if ($myTab) {{
        var _teamView = isSupportPerson(getCollabName() || '');
        var _badge = $myTab.querySelector('.vt-count');
        $myTab.textContent = _teamView ? 'Team lineup' : 'My lineup';
        if (_badge) $myTab.appendChild(_badge);   // re-attach the count badge
      }}
      // Sync/export (Calendar sync + Spreadsheet) is Angela-only.
      var $sync = document.getElementById('ops-sync-group');
      if ($sync) $sync.style.display = show ? '' : 'none';
      // Planner + Queue views are Angela-only — hide their tabs (setView blocks
      // them too). The top-line "Should attend" dropdown is Angela-only as well.
      var $plannerTab = document.querySelector('.view-toggle [data-view="planner"]');
      if ($plannerTab) $plannerTab.style.display = show ? '' : 'none';
      var $queueTab = document.querySelector('.view-toggle [data-view="queue"]');
      if ($queueTab) $queueTab.style.display = show ? '' : 'none';
      var $should = document.getElementById('filter-should');
      if ($should) $should.style.display = show ? '' : 'none';
      if (!show && typeof currentView !== 'undefined' && (currentView === 'planner' || currentView === 'queue')) {{
        setView(getCollabName() ? 'myevents' : 'grid');
      }}
      // Ticket price / priority / track / speaking + the three checkboxes are
      // Angela's power-user set — keep them OUT of everyone else's filter drawer,
      // which then holds only the filters that were there before for them:
      // Pipeline / Region / Fits / Months (+ Should-attend, gated above).
      ['filter-price', 'filter-priority', 'filter-speaker'].forEach(function (id) {{
        var el = document.getElementById(id);
        if (el) el.style.display = show ? '' : 'none';
      }});
      Array.prototype.forEach.call(document.querySelectorAll('#tf-drawer .ops-filter-chip'), function (l) {{
        l.style.display = show ? '' : 'none';
      }});
      var $ft = document.getElementById('ops-filter-toggle');
      if ($ft && !show) $ft.setAttribute('aria-expanded', 'false');
      updateFilterToggle();
    }}

    // Rebuild the Speakers row from the current data set. Called from
    // renderOps() so the chip list reflects who's actually assigned right
    // now (including changes that just synced in via realtime).
    function rebuildSpeakerFilter(stateRows, manualRows) {{
      var host = document.querySelector('#filter-speaker .filter-dd-menu');
      if (!host) return;
      // Wipe any prior chips/clear/empty markers but keep the label
      Array.prototype.slice.call(host.querySelectorAll('.extra-chip, .extra-clear, .extra-empty'))
        .forEach(function (n) {{ n.remove(); }});

      // Collect distinct speaker tokens from both sources. The speaker
      // field can be a single name ("Thor"), a comma-joined pair, or
      // free text. Split on common separators and dedupe case-insensitive.
      var seen = {{}};
      var speakers = [];
      function add(raw) {{
        if (!raw || typeof raw !== 'string') return;
        raw.split(/[,;/&]| and |\\bplus\\b/i).forEach(function (s) {{
          var t = s.trim();
          if (!t) return;
          var k = t.toLowerCase();
          if (seen[k]) return;
          seen[k] = true;
          speakers.push(t);
        }});
      }}
      // Always surface the full ArcticBlue speaker roster as filter chips —
      // even teammates not yet assigned to any event (Carlos, Jim, Scott…).
      ['Thor', 'Joe', 'Jerome', 'Scott', 'Verma', 'Carlos', 'Jim'].forEach(add);
      (stateRows  || []).forEach(function (r) {{ add(r.speaker); }});
      (manualRows || []).forEach(function (m) {{ add(m.speaker); }});

      if (speakers.length === 0) {{
        var empty = document.createElement('span');
        empty.className = 'extra-empty';
        empty.id = 'filter-speaker-empty';
        empty.textContent = 'No speakers assigned yet';
        host.appendChild(empty);
        return;
      }}

      // Sort alphabetically, then build chips
      speakers.sort(function (a, b) {{ return a.localeCompare(b); }});
      speakers.forEach(function (name) {{
        host.appendChild(_makeExtraChip(name, name, 'speak-chip'));
      }});
      var clr = document.createElement('button');
      clr.type = 'button'; clr.className = 'extra-clear'; clr.textContent = 'Clear';
      clr.addEventListener('click', function () {{
        host.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
        applyFilters();
      }});
      host.appendChild(clr);
    }}

    // The Attending row — same roster, but filters by who's marked ATTENDING
    // (the attendees field), distinct from who's SPEAKING (the speaker field).
    // The new primary filter row: one chip per pipeline stage. Selecting
    // chips keeps any card carrying ANY of the chosen stages (OR).
    // Plain-English meaning of each pipeline stage — the team kept tripping over
    // "Identified" (it means logged-but-not-applied, NOT submitted).
    var STAGE_HELP = {{
      'Identified':   'Logged as a candidate — we have NOT applied yet. (not submitted)',
      'Submitted':    'A speaking application has been sent.',
      'Followed up':  'We chased/nudged after submitting.',
      'Meeting held': 'An intro call / meeting with the organizer happened.',
      'Booked':       'Confirmed to speak.',
      'Attending':    'Going to the event (not speaking).'
    }};
    // Pipeline is now a multi-select .filter-dd (top line), same bubble UI as
    // Fits/Price. applyFilters ORs every selected stage chip. Each chip keeps
    // its stage palette via --sc-bg/--sc-fg (see .stage-chip-dd.is-on CSS).
    function buildStageFilters() {{
      var menu = document.querySelector('#filter-pipeline .filter-dd-menu');
      if (!menu || menu.dataset.built === '1') return;
      STAGE_TAGS.forEach(function (s) {{
        var chip = _makeExtraChip(s.key, s.key, 'stage-chip-dd');
        chip.title = (typeof STAGE_HELP !== 'undefined' && STAGE_HELP[s.key]) ? (s.key + ' — ' + STAGE_HELP[s.key]) : ('Filter by ' + s.key);
        chip.style.setProperty('--sc-bg', s.bg);
        chip.style.setProperty('--sc-fg', s.fg);
        menu.appendChild(chip);
      }});
      var clr = document.createElement('button');
      clr.type = 'button'; clr.className = 'extra-clear'; clr.textContent = 'Clear';
      clr.addEventListener('click', function () {{
        menu.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
        applyFilters();
      }});
      menu.appendChild(clr);
      menu.dataset.built = '1';
    }}

    // Region filter row — same colored-chip UI as the pipeline (Angela's ask:
    // "put the region filter right below the pipeline, shown like pipeline").
    // Single-select: click a region to show only it; re-click to clear.
    // Region is now a multi-select .filter-dd (top line). Each chip carries its
    // region colour via --rc-col (see .region-chip-dd.is-on CSS).
    function buildRegionFilters() {{
      var menu = document.querySelector('#filter-region .filter-dd-menu');
      if (!menu || menu.dataset.built === '1') return;
      Object.keys(REGION_COLORS).forEach(function (r) {{
        var chip = _makeExtraChip(r, r, 'region-chip-dd');
        chip.title = 'Filter by ' + r + ' (pick several to combine)';
        chip.style.setProperty('--rc-col', REGION_COLORS[r]);
        menu.appendChild(chip);
      }});
      var clr = document.createElement('button');
      clr.type = 'button'; clr.className = 'extra-clear'; clr.textContent = 'Clear';
      clr.addEventListener('click', function () {{
        menu.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
        applyFilters();
      }});
      menu.appendChild(clr);
      menu.dataset.built = '1';
    }}

    function buildStatusFilters() {{
      var host = document.getElementById('status-filters');
      if (!host || host.dataset.built === '1') return;
      // Walk STATUS_GROUPS in order so the filter row reads
      // Confirmed → Active → Waiting → Action → Closed → Other.
      var frag = document.createDocumentFragment();
      STATUS_GROUPS.forEach(function (g, idx) {{
        if (idx > 0) {{
          var sep = document.createElement('span');
          sep.className = 'status-group-sep';
          frag.appendChild(sep);
        }}
        var label = document.createElement('span');
        label.className = 'status-group-label';
        label.style.color = g.dot;
        label.textContent = g.label;
        frag.appendChild(label);
        STATUS_OPTIONS.filter(function (s) {{ return s.group === g.key; }}).forEach(function (s) {{
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'status-chip';
          btn.dataset.status = s.value;
          btn.setAttribute('aria-pressed', 'false');
          btn.style.background = s.bg;
          btn.style.color = s.fg;
          btn.style.borderColor = s.bg;
          btn.textContent = s.value;
          btn.title = g.label + ' · click to filter by ' + s.value;
          btn.addEventListener('click', function () {{
            btn.classList.toggle('is-on');
            applyFilters();
          }});
          frag.appendChild(btn);
        }});
      }});
      var clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.className = 'clear-btn';
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', function () {{
        host.querySelectorAll('.status-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
        applyFilters();
      }});
      frag.appendChild(clearBtn);
      host.appendChild(frag);
      host.dataset.built = '1';
    }}

    // ── Month grouping for the ops grid ────────────────────────────
    // Builds an .ops-month-header divider (clickable to collapse) for one
    // month. Caret rotates via the .collapsed class; count is filled by
    // applyFilters so it always reflects what the active filters matched.
    function buildOpsMonthHeader(key, label) {{
      var h = document.createElement('button');
      h.type = 'button';
      h.className = 'ops-month-header' + (opsCollapsedMonths[key] ? ' collapsed' : '');
      h.dataset.month = key;
      h.setAttribute('aria-expanded', opsCollapsedMonths[key] ? 'false' : 'true');
      h.innerHTML =
        '<span class="mh-caret" aria-hidden="true">▼</span>' +
        '<span class="mh-label">' + escapeHtml(label) + '</span>' +
        '<span class="mh-count" data-mh-count></span>' +
        '<span class="mh-line" aria-hidden="true"></span>';
      h.addEventListener('click', function () {{ toggleOpsMonth(key); }});
      return h;
    }}

    // Card placement tier: regular months (0) sort first, then the collapsible
    // "Archived" group (1) — events YOU archived — then "Past events" (2), whose
    // date has simply gone by, at the very bottom. Two separate lists, two words.
    function opsCardTier(card) {{
      if (card.classList.contains('is-archived')) return 1;
      if (card.dataset.past === '1') return 2;
      return 0;
    }}

    // Re-sort every .ops-card chronologically and (re)insert month dividers.
    // Cards keep their DOM nodes — we only move them — so wired handlers and
    // open <details> survive. Also (re)builds the Months dropdown list.
    function regroupOpsByMonth() {{
      if (!$opsGrid) return;
      Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-month-header'))
        .forEach(function (h) {{ if (h.parentNode) h.parentNode.removeChild(h); }});
      var cards = Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-card'));
      if (!cards.length) {{ buildMonthsFilter(); return; }}
      // Hidden events sink to their own group after everything (incl. Date TBD);
      // within each group, chronological by event date.
      cards.sort(function (a, b) {{
        var at = opsCardTier(a), bt = opsCardTier(b);
        if (at !== bt) return at - bt;
        var as = parseInt(a.dataset.sort || '99999999', 10);
        var bs = parseInt(b.dataset.sort || '99999999', 10);
        // Past events read best most-recent-first; everything else stays
        // chronological (soonest first).
        return at === 2 ? (bs - as) : (as - bs);
      }});
      var frag = document.createDocumentFragment();
      var curKey = null;
      var order = [];
      cards.forEach(function (card) {{
        var tier = opsCardTier(card);
        // Keys match the labels on purpose. They used to be inverted — tier 1
        // (what the reader sees as "Archived") was keyed 'hidden', and tier 2
        // (past events) was keyed 'archive' — so the constant called `archive`
        // was NOT the archive anyone means.
        var key = tier === 1 ? 'archived' : (tier === 2 ? 'past' : (card.dataset.month || 'tbd'));
        var label = tier === 1 ? 'Archived' : (tier === 2 ? 'Past events' : (card.dataset.monthLabel || 'Date TBD'));
        if (key !== curKey) {{
          curKey = key;
          order.push({{ key: key, label: label }});
          frag.appendChild(buildOpsMonthHeader(key, label));
        }}
        frag.appendChild(card);
      }});
      $opsGrid.appendChild(frag);
      _buildClashIndex();
      wireCardPeek();
      buildMonthsFilter();
    }}

    function toggleOpsMonth(key) {{
      opsCollapsedMonths[key] = !opsCollapsedMonths[key];
      applyFilters();
    }}

    function setAllMonths(collapsed) {{
      if (!$opsGrid) return;
      Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-month-header')).forEach(function (h) {{
        opsCollapsedMonths[h.dataset.month] = !!collapsed;
      }});
      applyFilters();
    }}

    // (Re)build the Months filter as a multi-select .filter-dd (top line) — one
    // bubble per distinct month present in the grid, chronological. No chips
    // selected = all months; select some = show only those. Prior selection is
    // preserved across re-renders. (Month-section collapse via header click is a
    // separate concern, still handled by opsCollapsedMonths / toggleOpsMonth.)
    function buildMonthsFilter() {{
      var menu = document.querySelector('#filter-months .filter-dd-menu');
      if (!menu || !$opsGrid) return;
      var prev = {{}};
      Array.prototype.forEach.call(menu.querySelectorAll('.extra-chip.is-on'), function (b) {{ prev[b.dataset.value] = 1; }});
      var seen = {{}}, months = [];
      Array.prototype.forEach.call($opsGrid.querySelectorAll('.ops-card'), function (card) {{
        var k = card.dataset.month;
        if (!k || k === 'tbd' || seen[k]) return;
        seen[k] = 1;
        months.push({{ key: k, label: card.dataset.monthLabel || k, sort: parseInt(card.dataset.sort || '99999999', 10) }});
      }});
      months.sort(function (a, b) {{ return a.sort - b.sort; }});
      menu.classList.remove('show-past');
      menu.innerHTML = '';
      if (!months.length) {{ menu.innerHTML = '<span class="extra-empty">No dated events yet</span>'; return; }}
      // Upcoming months lead (one per line); months before this calendar month
      // collapse into a "past months" list hidden at the bottom.
      var _now = new Date();
      var curKey = _now.getFullYear() + '-' + String(_now.getMonth() + 1).padStart(2, '0');
      var upcoming = months.filter(function (m) {{ return m.key >= curKey; }});
      var past = months.filter(function (m) {{ return m.key < curKey; }});
      function addChip(m, extraCls) {{
        var chip = _makeExtraChip(m.key, m.label, 'month-chip' + (extraCls ? ' ' + extraCls : ''));
        if (prev[m.key]) chip.classList.add('is-on');
        menu.appendChild(chip);
        return chip;
      }}
      upcoming.forEach(function (m) {{ addChip(m); }});
      if (past.length) {{
        var tog = document.createElement('button');
        tog.type = 'button'; tog.className = 'month-past-toggle';
        function togLabel() {{ return (menu.classList.contains('show-past') ? 'Hide' : 'Show') + ' ' + past.length + ' past month' + (past.length === 1 ? '' : 's'); }}
        tog.innerHTML = '<span class="mpt-label"></span><span class="mpt-caret" aria-hidden="true">\\u25be</span>';
        tog.querySelector('.mpt-label').textContent = togLabel();
        tog.addEventListener('click', function (e) {{
          e.stopPropagation();
          menu.classList.toggle('show-past');
          tog.querySelector('.mpt-label').textContent = togLabel();
        }});
        menu.appendChild(tog);
        var anyPastOn = false;
        past.forEach(function (m) {{ addChip(m, 'is-pastmonth'); if (prev[m.key]) anyPastOn = true; }});
        if (anyPastOn) {{ menu.classList.add('show-past'); tog.querySelector('.mpt-label').textContent = togLabel(); }}
      }}
      var clr = document.createElement('button');
      clr.type = 'button'; clr.className = 'extra-clear'; clr.textContent = 'Clear';
      clr.addEventListener('click', function () {{
        menu.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
        applyFilters();
      }});
      menu.appendChild(clr);
    }}

    // Keep aria-pressed in lock-step with the visual is-on/is-activestat state,
    // centrally — every chip/tile toggle routes through applyFilters(), so one
    // sync here covers them all instead of editing ~10 toggle sites.
    function syncAriaPressed() {{
      Array.prototype.forEach.call(document.querySelectorAll('.stage-chip, .status-chip, .extra-chip'), function (b) {{
        b.setAttribute('aria-pressed', b.classList.contains('is-on') ? 'true' : 'false');
      }});
      Array.prototype.forEach.call(document.querySelectorAll('.ops-stat[data-stat]'), function (b) {{
        b.setAttribute('aria-pressed', b.classList.contains('is-activestat') ? 'true' : 'false');
      }});
    }}

    function applyFilters() {{
      var $search  = document.getElementById('ops-search');
      var $saved   = document.getElementById('ops-f-saved');
      var $urgent  = document.getElementById('ops-f-urgent');
      var $submitted = document.getElementById('ops-f-submitted');
      var $meet    = document.getElementById('ops-f-meetings');
      var $past    = document.getElementById('ops-f-past');
      var $hidden  = document.getElementById('ops-f-hidden');
      var $recent  = document.getElementById('ops-f-recent');
      if (!$search || !$opsGrid) return;
      var q = ($search.value || '').toLowerCase().trim();
      // Region / Months / Should-attend are multi-select .filter-dd bubbles in
      // the top line — OR the chips within each dimension, AND across dimensions.
      var activeRegions = Array.prototype.map.call(document.querySelectorAll('#filter-region .extra-chip.is-on'), function (b) {{ return b.dataset.value; }});
      var activeMonths  = Array.prototype.map.call(document.querySelectorAll('#filter-months .extra-chip.is-on'), function (b) {{ return b.dataset.value; }});
      var activeShould  = Array.prototype.map.call(document.querySelectorAll('#filter-should .extra-chip.is-on'), function (b) {{ return b.dataset.value; }});
      // Per-account "Attending" filter (support = team-wide). Precomputed once.
      var _attMe = (getCollabName() || 'Team').toLowerCase().split(/\\s+/)[0];
      var _attSupport = isSupportPerson(getCollabName() || '');
      var _myFitPf = AB_PROFILE_BY_LCKEY[_attMe] || null;   // for the "My fits" chip (keys are capitalized)
      var fSaved   = !!($saved && $saved.checked);
      var fUrgent  = !!($urgent && $urgent.checked);
      var fSubmitted = !!($submitted && $submitted.checked);
      var fMeet    = !!($meet && $meet.checked);
      // Ticket price + Fits are now MULTI-select bubble dropdowns — OR the chips.
      var activePrices = Array.prototype.map.call(document.querySelectorAll('#filter-price .extra-chip.is-on'), function (b) {{ return b.dataset.value; }});
      var activeFits   = Array.prototype.map.call(document.querySelectorAll('#filter-fits .extra-chip.is-on'), function (b) {{ return b.dataset.value; }});
      var showPast   = !!($past && $past.checked);
      var showHidden = !!($hidden && $hidden.checked);
      var fRecent    = !!($recent && $recent.checked);
      // Toggle has-active classes for chip styling
      [['ops-f-saved',$saved],['ops-f-urgent',$urgent],['ops-f-submitted',$submitted],['ops-f-meetings',$meet],['ops-f-past',$past],['ops-f-hidden',$hidden],['ops-f-recent',$recent]].forEach(function (pair) {{
        var inp = pair[1]; if (!inp) return;
        var lbl = inp.closest('.ops-filter-chip');
        if (lbl) lbl.classList.toggle('has-active', inp.checked);
      }});
      // Pipeline-stage filter — keep a card if it carries ANY selected stage.
      var activeStages = Array.prototype.map.call(
        document.querySelectorAll('#filter-pipeline .extra-chip.is-on'),
        function (b) {{ return b.dataset.value; }}
      );
      // Legacy status chip filter — OR across selected statuses (multi-select)
      var activeStatuses = Array.prototype.map.call(
        document.querySelectorAll('.status-filters .status-chip.is-on'),
        function (b) {{ return b.dataset.status; }}
      );
      // Priority / Track / Speakers — OR across each dimension; AND across dimensions
      var activePriorities = Array.prototype.map.call(
        document.querySelectorAll('#filter-priority .extra-chip.is-on'),
        function (b) {{ return b.dataset.value; }}
      );
      var activeSpeakers = Array.prototype.map.call(
        document.querySelectorAll('#filter-speaker .extra-chip.is-on'),
        function (b) {{ return (b.dataset.value || '').toLowerCase(); }}
      );

      var shown = 0, dupSkipped = 0;
      // "Showing N of M" reports only the LIVE set the user cares about —
      // upcoming events that aren't hidden or archived/past (tier 0). shown
      // (below) still counts every passing card incl. collapsed past ones, for
      // the empty-state guard; activeShown/activeTotal drive the visible count.
      var activeShown = 0, activeTotal = 0;
      var monthMatched = {{}};
      // Query the card set once per pass (it's also the count denominator) —
      // re-querying inside + again for the count walked the DOM twice/keystroke.
      var opsCards = $opsGrid.querySelectorAll('.ops-card');
      opsCards.forEach(function (card) {{
        // Hidden duplicate of an already-shown event — never render or count it.
        if (card.dataset.dupHidden === '1' && !_reviewDupes) {{ card.style.display = 'none'; dupSkipped++; return; }}
        // "Review duplicates" is a COMPARISON view: show only the suspected
        // duplicates AND the events they duplicate, so each pair can be judged
        // side by side. Previously it un-hid the dupes into the full grid, which
        // meant hunting for the original before deciding what to delete.
        if (_reviewDupes && card.dataset.dupHidden !== '1' && card.dataset.dupKeeper !== '1'
            && card.dataset.dupMaybe !== '1') {{
          card.style.display = 'none'; return;
        }}
        var on = true;
        if (q) {{
          // Cache the lowercased search text on the node. textContent serializes
          // the whole card subtree — doing it per card per keystroke was the
          // biggest typing cost. Fresh nodes (re-render) recompute; in-place
          // toggles don't change searchable text, so the cache stays valid.
          var _blob = card._searchBlob;
          if (_blob == null) {{
            // The visible card text PLUS hidden record fields — so searching a
            // POC name ("ciara"), an organiser contact, a past speaker, or the
            // about/focus text finds the event even though the stripped card
            // face doesn't show them.
            var _r = card._modalRec || {{}};
            // NOTES are indexed too: Angela writes the organiser/contact person
            // she spoke to straight into Notes, and searching that name found
            // nothing because notes never reach the card face. Same for the
            // outreach note and the remaining contact fields.
            // Indexed: the card face (name, date, location, status, tags) plus the
            // fields you'd actually search BY — the contact block and our own
            // written record. The "Who attends" prose is deliberately NOT indexed:
            // typical_attendees and past_speakers are long lists of other people's
            // names and job titles, so searching for a contact matched dozens of
            // events that merely list someone with that name in their audience or
            // past-speaker blurb, burying the event you actually wanted (Angela).
            _blob = card._searchBlob = ((card.textContent || '') + ' ' +
              [_r.poc_name, _r.poc_email, _r.poc_linkedin, _r.contact_info,
               _r.additional_contacts, _r.notes, _r.outreach_note,
               _r.speaker, _r.speaker_topic,
               _r.about, _r.focus_areas].filter(Boolean).join(' ')).toLowerCase();
          }}
          if (_blob.indexOf(q) === -1) on = false;
        }}
        if (activeRegions.length && activeRegions.indexOf(card.dataset.region) === -1) on = false;
        if (activeMonths.length && activeMonths.indexOf(card.dataset.month) === -1) on = false;
        if (activeFits.length) {{
          var _intNames = (card.dataset.interestedNames || '').split('|').filter(Boolean);
          var _fitHit = activeFits.some(function (k) {{
            var pf = AB_PROFILE_BY_KEY[k]; if (!pf) return false;
            if (profileFits(pf, card.dataset.fitText, card.dataset.region, _cardPriceNum(card), card.dataset.foreignLang === '1')) return true;
            // If that person flagged "I'm interested", the event fits THEM —
            // keep it in their Fits filter even when the keywords don't match.
            var kf = abFold(pf.key);
            return _intNames.some(function (n) {{ return abFold(n).split(/\\s+/)[0] === kf; }});
          }});
          if (!_fitHit) on = false;
        }}
        if (fSaved && !card.classList.contains('is-saved'))  on = false;
        if (fUrgent && !card.classList.contains('is-urgent')) on = false;
        if (fSubmitted && (card.dataset.statusTags || '').split('|').indexOf('Submitted') === -1) on = false;
        if (fMeet && card.dataset.meetings !== '1') on = false;
        if (fRecent && card.dataset.recent !== '1') on = false;
        // Should attend — OR the selected kinds: Team pick = hand-flagged (human),
        // AI pick = the AI recommend pass. No chips selected = don't filter.
        if (activeShould.length) {{
          var _sak = shouldAttendKind(card.dataset.attend);
          if (activeShould.indexOf(_sak) === -1) on = false;
        }}
        if (activePrices.length) {{
          var pn = card.dataset.price === '' || card.dataset.price == null ? null : parseFloat(card.dataset.price);
          var _priceHit = activePrices.some(function (band) {{
            if (band === 'known')     return pn != null;
            if (band === 'free')      return pn === 0;
            if (band === 'lt1000')    return pn != null && pn > 0 && pn < 1000;
            if (band === '1000-2500') return pn != null && pn >= 1000 && pn < 2500;
            if (band === 'gte2500')   return pn != null && pn >= 2500;
            return false;
          }});
          if (!_priceHit) on = false;
        }}
        // Past events are no longer force-hidden — they collect in the
        // collapsible "Archive · past events" group at the bottom (opsCardTier).
        // Hidden events are NOT filtered out — they collect in a collapsible
        // "Hidden" section at the bottom (see the effective month key below).
        // Top stat-tile filter (one click on a stat shows only those events).
        if (opsStatFilter) {{
          var tagsS = (card.dataset.statusTags || '');
          if (opsStatFilter === 'myinterested' && (card.dataset.interestedNames || '').split('|').indexOf((getCollabName() || 'Team').toLowerCase()) === -1) on = false;
          if (opsStatFilter === 'urgent'  && !card.classList.contains('is-urgent')) on = false;
          if (opsStatFilter === 'pipeline') {{
            // "Pending" = my in-flight speaking application (Submitted / Followed
            // up / Meeting held, not yet Booked). Per-account (I'm the speaker);
            // team-wide for Angela/Hurley.
            var _ps = tagsS.split('|');
            // Rejected is terminal — never "pending" (matches _iPending's count).
            var _isPend = _ps.indexOf('Rejected') === -1 &&
              (_ps.indexOf('Submitted') !== -1 || _ps.indexOf('Followed up') !== -1 || _ps.indexOf('Meeting held') !== -1) && _ps.indexOf('Booked') === -1;
            var _mine = _attSupport;
            if (_isPend && !_mine) {{
              var _sp = (card.dataset.speaker || '').toLowerCase();
              var _tok = _sp ? _sp.split(/[,;/&]| and |\\bplus\\b/i).map(function (s) {{ return s.trim(); }}) : [];
              _mine = _tok.indexOf(_attMe) !== -1;
            }}
            if (!(_isPend && _mine)) on = false;
          }}
          if (opsStatFilter === 'booked'  && tagsS.split('|').indexOf('Booked') === -1) on = false;
          if (opsStatFilter === 'attending') {{
            var _anF = (card.dataset.attendeeNames || '');
            var _attHit = _attSupport ? (_anF.length > 0) : (_anF.split('|').indexOf(_attMe) !== -1);
            if (!_attHit) on = false;
          }}
          if (opsStatFilter === 'buyer'   && (card.dataset.audience || '').toLowerCase().indexOf('buyer') === -1) on = false;
          if (opsStatFilter === 'contacts' && card.dataset.contactFound !== '1') on = false;
          if (opsStatFilter === 'interested' && card.dataset.interested !== '1') on = false;
          if (opsStatFilter === 'myfits') {{
            // Fits my profile OR I flagged interested (interest = a fit). Mirrors
            // the count in renderStats and the Fits-dropdown rule.
            var _mfInt = (card.dataset.interestedNames || '').split('|').filter(Boolean).some(function (n) {{ return abFold(n).split(/\\s+/)[0] === _attMe; }});
            // A learned "Not for me" pattern narrows MY fits — but never drops an
            // event I've actively flagged interest in.
            if (!_mfInt && _vetoedCard(card)) on = false;
            else if (!(_mfInt || (_myFitPf && profileFits(_myFitPf, card.dataset.fitText, card.dataset.region, _cardPriceNum(card), card.dataset.foreignLang === '1')))) on = false;
          }}
        }}
        if (activeStages.length > 0) {{
          var cardStages = (card.dataset.statusTags || '').split('|').filter(Boolean);
          var stageHit = activeStages.some(function (a) {{ return cardStages.indexOf(a) !== -1; }});
          if (!stageHit) on = false;
        }}
        if (activeStatuses.length   > 0 && activeStatuses.indexOf(card.dataset.status   || '') === -1) on = false;
        if (activePriorities.length > 0 && activePriorities.indexOf(card.dataset.priority || '') === -1) on = false;
        // Speaking filter — the assigned speaker (booked, or pursuing a slot),
        // NOT an attending-only event.
        if (activeSpeakers.length > 0) {{
          var _sp = (card.dataset.speaker || '').toLowerCase();
          var _tok = _sp ? _sp.split(/[,;/&]| and |\\bplus\\b/i).map(function (s) {{ return s.trim(); }}).filter(Boolean) : [];
          var _stg = (card.dataset.statusTags || '').split('|');
          var _attendingOnly = _stg.indexOf('Attending') !== -1 && _stg.indexOf('Booked') === -1;
          var _speakHit = !_attendingOnly && activeSpeakers.some(function (a) {{ return _tok.indexOf(a) !== -1; }});
          if (!_speakHit) on = false;
        }}
        // Collapsing a month is a view convenience, not a filter: a card that
        // passes the filters still counts toward "shown" even when its month
        // is folded — we only hide it from view. Hidden cards live in the
        // "hidden" group regardless of their date.
        var _tier = opsCardTier(card);
        var mkey = _tier === 1 ? 'archived' : (_tier === 2 ? 'past' : (card.dataset.month || 'tbd'));
        if (_tier === 0) activeTotal++;   // live universe (not hidden / past)
        if (on) {{ monthMatched[mkey] = (monthMatched[mkey] || 0) + 1; shown++; if (_tier === 0) activeShown++; }}
        // Did the card pass the real filters? (independent of month/archive
        // collapse) — the Map view uses this so past events still appear.
        card.dataset.passed = on ? '1' : '0';
        // An active search overrides month collapsing — a match inside a
        // folded month must be visible or the event looks like it's missing.
        card.style.display = (on && (!opsCollapsedMonths[mkey] || q)) ? '' : 'none';
      }});
      // Month dividers: hide a header whose month matched nothing; otherwise
      // reflect the collapsed state + the matched count.
      Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-month-header')).forEach(function (h) {{
        var mkey = h.dataset.month || 'tbd';
        var n = monthMatched[mkey] || 0;
        h.style.display = n ? '' : 'none';
        var collapsed = !!opsCollapsedMonths[mkey] && !q;  // search overrides collapse
        h.classList.toggle('collapsed', collapsed);
        h.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        var cnt = h.querySelector('[data-mh-count]');
        // "collapsed", not "hidden" — a folded group sits right next to one
        // actually named "Archived", and two meanings of hidden in one line is
        // exactly the confusion we just took out.
        if (cnt) cnt.textContent = n + (n === 1 ? ' event' : ' events') + (collapsed ? ' · collapsed' : '');
      }});
      var $shown = document.getElementById('ops-shown');
      if ($shown) {{
        // No narrowing → just "N events"; a filter/search in play → "Showing N
        // of M events". Counts exclude hidden + archived/past (see activeTotal).
        $shown.textContent = (activeShown === activeTotal)
          ? activeTotal + ' event' + (activeTotal === 1 ? '' : 's')
          : 'Showing ' + activeShown + ' of ' + activeTotal + ' events';
      }}
      // Filtered-to-zero guard: an all-filtered grid LOOKS like "no events
      // loaded" (that was Thor's read of it). Say so explicitly + one-tap reset.
      var _emptyNote = document.getElementById('ops-empty-note');
      if (shown === 0 && opsCards.length > 0) {{
        if (!_emptyNote) {{
          _emptyNote = document.createElement('div');
          _emptyNote.id = 'ops-empty-note';
          _emptyNote.className = 'ops-empty-note';
          $opsGrid.appendChild(_emptyNote);
        }}
        _emptyNote.innerHTML = 'All ' + opsCards.length + ' events are hidden by the active filters &mdash; nothing is missing.<br>' +
          '<button type="button" class="q-btn primary" id="ops-empty-clear">Show all events (clear filters)</button>';
        var _ec = document.getElementById('ops-empty-clear');
        if (_ec) _ec.addEventListener('click', clearOpsFilters);
      }} else if (_emptyNote) {{
        _emptyNote.remove();
      }}
      // Empty state — a fully-filtered grid should explain itself, not blank out.
      var $empty = document.getElementById('ops-empty');
      if (shown === 0) {{
        if (!$empty) {{
          $empty = document.createElement('div');
          $empty.id = 'ops-empty'; $empty.className = 'ops-empty';
          $empty.innerHTML = '<p class="ops-empty-title">No events match your filters.</p>'
            + '<p class="ops-empty-sub">Try a different search term or loosen a filter.</p>'
            + '<button type="button" class="ops-empty-btn" id="ops-empty-clear">Clear search &amp; filters</button>';
          $opsGrid.appendChild($empty);
          var _b = document.getElementById('ops-empty-clear');
          if (_b) _b.addEventListener('click', clearOpsFilters);
        }}
        $empty.style.display = '';
      }} else if ($empty) {{
        $empty.style.display = 'none';
      }}
      syncAriaPressed();  // reflect on/off state to screen readers
      updateFilterDropdownCounts();  // keep dropdown buttons' active counts current
      updateFilterToggle();          // keep the collapsed "Filters · N active" count fresh
      updateActiveTopFiltersBanner(); // and the everyone-visible "N filters active — Clear all"
      // The map + calendar mirror the grid's filters — keep them in sync.
      if (currentView === 'map' && _opsMapLayer) renderOpsMap();
      if (currentView === 'calendar' && _calEvents) recalcCalendar();
    }}

    function debounce(fn, ms) {{
      var t;
      return function () {{
        var ctx = this, args = arguments;
        clearTimeout(t);
        t = setTimeout(function () {{ fn.apply(ctx, args); }}, ms);
      }};
    }}

    function wireFilters() {{
      // Debounce only the free-text search (fires on every keystroke); selects
      // and checkboxes change discretely, so apply those immediately.
      var debouncedApply = debounce(applyFilters, 130);
      ['ops-search','ops-f-saved','ops-f-urgent','ops-f-submitted','ops-f-meetings','ops-f-past','ops-f-hidden','ops-f-recent'].forEach(function (id) {{
        var el = document.getElementById(id); if (!el) return;
        if (el.dataset.wired) return;
        el.dataset.wired = '1';
        var ev = (el.tagName === 'INPUT' && el.type !== 'checkbox') ? 'input' : 'change';
        el.addEventListener(ev, ev === 'input' ? debouncedApply : applyFilters);
      }});
    }}

    function clearOpsFilters() {{
      // Reset every ops filter to its default, then re-run. Safe because
      // applyFilters reads all state fresh from these controls each call.
      ['ops-search'].forEach(function (id) {{
        var el = document.getElementById(id); if (el) el.value = '';
      }});
      ['ops-f-saved','ops-f-urgent','ops-f-submitted','ops-f-meetings','ops-f-past','ops-f-hidden','ops-f-recent'].forEach(function (id) {{
        var el = document.getElementById(id); if (el) el.checked = false;
      }});
      Array.prototype.forEach.call(
        document.querySelectorAll('#filter-pipeline .extra-chip.is-on, #filter-region .extra-chip.is-on, #filter-months .extra-chip.is-on, #filter-should .extra-chip.is-on, .status-filters .status-chip.is-on, #filter-price .extra-chip.is-on, #filter-fits .extra-chip.is-on, #filter-priority .extra-chip.is-on, #filter-speaker .extra-chip.is-on'),
        function (c) {{ c.classList.remove('is-on'); }}
      );
      opsStatFilter = ''; _userPickedStat = true;   // "clear all" = show All; don't re-default to My fits
      var $stats = document.getElementById('ops-stats');
      if ($stats) Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (x) {{ x.classList.toggle('is-on', x.dataset.stat === 'all'); }});
      applyFilters();
    }}

    function renderStats(evs, stateRows, manualRows) {{
      var $stats = document.getElementById('ops-stats');
      if (!$stats) return;
      // The "Upcoming" headline excludes events that already happened.
      var total = (evs || []).filter(function (e) {{ return !isPastEvent(e); }}).length +
                  (manualRows || []).filter(function (m) {{ return !isPastEvent(m); }}).length;
      var stByNum = {{}};
      (stateRows || []).forEach(function (r) {{ stByNum[r.event_num] = r; }});
      var evByNum = {{}};
      (evs || []).forEach(function (e) {{ evByNum[e.num] = e; }});
      var saved = 0, urgent = 0, inPipeline = 0, booked = 0, attending = 0;
      var buyerRich = 0, interestedCount = 0, myInterested = 0, contacts = 0;
      var me = (getCollabName() || 'Team').toLowerCase();
      var meFirst = me.split(/\\s+/)[0];   // attendees are stored as lowercase first names
      var _support = isSupportPerson(getCollabName() || '');   // Angela/Hurley -> team-wide
      // A persona lands on "My fits"; support (no profile) stays on All. Applied
      // on every (re)render until the reader clicks a status chip — robust to the
      // load-order of profiles vs. the first stats render.
      if (!_userPickedStat && !opsStatFilter && AB_PROFILE_BY_LCKEY[meFirst]) opsStatFilter = 'myfits';
      // Angela has no "My fits" chip (see renderStats) — make sure she can never
      // be left sitting on that filter with no visible control to clear it.
      if (opsStatFilter === 'myfits' && window.isAngelaUser && window.isAngelaUser()) opsStatFilter = '';
      function _isMine(list) {{ return (list || []).some(function (n) {{ return String(n).toLowerCase() === me; }}); }}
      // "Attending" is PER-ACCOUNT: events where the signed-in person is an
      // assigned attendee — the attendee list is the source of truth (not the
      // Attending stage), so it stays accurate even if the stage wasn't synced,
      // and it counts BOTH past and future events they're attending. Support
      // people (Angela/Hurley) coordinate for everyone, so they see team-wide.
      function _iAttend(list) {{ return _support ? (list || []).length > 0 : (list || []).some(function (n) {{ return String(n).toLowerCase() === meFirst; }}); }}
      // "Pending" = a speaking application still in flight for the signed-in
      // person: Submitted / Followed up / Meeting held but NOT yet Booked (the
      // goal). Tied to them as the assigned speaker; support = team-wide.
      function _iPending(stages, speaker) {{
        // Rejected is TERMINAL — the organizer already said no, so there is
        // nothing in flight (Hurley 2026-07-29). It used to keep counting as
        // Pending because only Booked closed the application out.
        if (stages.indexOf('Rejected') !== -1) return false;
        var pend = (stages.indexOf('Submitted') !== -1 || stages.indexOf('Followed up') !== -1 || stages.indexOf('Meeting held') !== -1) && stages.indexOf('Booked') === -1;
        if (!pend) return false;
        return _support || speakerTokens(speaker || '').indexOf(meFirst) !== -1;
      }}
      (stateRows || []).forEach(function (r) {{
        if (r.saved)  saved++;
        var stages = stageTagsOf(r);
        // The status chips count only UPCOMING events (a past Booked/Attending
        // shouldn't inflate the number when the grid hides past by default).
        var _ev = evByNum[r.event_num];
        var _up = _ev && !isPastEvent(_ev);
        if (_up && _iPending(stages, r.speaker)) inPipeline++;
        if (_up && stages.indexOf('Booked') !== -1) booked++;
        if (_up && _iAttend(r.attendees)) attending++;
        if (r.interested && r.interested.length) interestedCount++;
        if (_isMine(r.interested)) myInterested++;
      }});
      // Urgent = an apply/CFP deadline closing soon (or a manually-flagged
      // urgent event) — NOT merely an upcoming event. Counted per event.
      (evs || []).forEach(function (ev) {{
        if (((ev.audience_type || '').toLowerCase()).indexOf('buyer') !== -1) buyerRich++;
        var st = stByNum[ev.num] || {{}};
        if (!isPastEvent(ev) && (st.urgent || isDeadlineUrgent(ev.deadline))) urgent++;
        // Contacts = an organizer email / POC we can reach out to (same test the
        // card's ✉ badge + the Contacts chip filter use). Upcoming only.
        if (!isPastEvent(ev) && hasEmailContact(st, ev)) contacts++;
      }});
      // Manual events carry their own stage tags + deadlines — fold them in.
      (manualRows || []).forEach(function (m) {{
        var stages = stageTagsOf(m);
        var _mup = !isPastEvent(m);   // upcoming-only, like the catalog counts above
        if (_mup && _iPending(stages, m.speaker)) inPipeline++;
        if (_mup && stages.indexOf('Booked') !== -1) booked++;
        if (_mup && _iAttend(m.attendees)) attending++;
        if (((m.audience_type || '').toLowerCase()).indexOf('buyer') !== -1) buyerRich++;
        if (m.interested && m.interested.length) interestedCount++;
        if (_isMine(m.interested)) myInterested++;
        if (!isPastEvent(m) && isDeadlineUrgent(m.deadline)) urgent++;
        if (!isPastEvent(m) && hasEmailContact(m)) contacts++;
      }});
      // "My fits" = events matching the signed-in person's target profile, OR
      // ones they flagged "I'm interested" (interest counts as a fit). Support
      // has no profile, so for them it's just their interested events. Upcoming
      // only, like the other chips. Kept in lock-step with the applyFilters test.
      var _myPf = AB_PROFILE_BY_LCKEY[meFirst] || null, myFits = 0;
      function _fitBlob(o, st2) {{
        var aud = (st2 && st2.audience_type && String(st2.audience_type).trim()) ? st2.audience_type : o.audience_type;
        return abFold([o.name, o.about, o.focus_areas, o.typical_attendees, o.location, o.city, o.country, o.type, o.past_speakers, aud].join(' '));
      }}
      function _mineInterest(list) {{ return (list || []).some(function (n) {{ return abFold(n).split(/\\s+/)[0] === meFirst; }}); }}
      (evs || []).forEach(function (ev) {{
        if (isPastEvent(ev)) return;
        var st2 = stByNum[ev.num] || {{}};
        var _int = (st2.interested && st2.interested.length) ? st2.interested : (ev.interested || []);
        if (_mineInterest(_int)) myFits++;
        else if (!_vetoedItem(ev) && _myPf && profileFits(_myPf, _fitBlob(ev, st2), canonicalRegion(ev), priceNumOf((st2 && st2.pricing) || ev.pricing), _isForeignLangEvent(ev))) myFits++;
      }});
      (manualRows || []).forEach(function (m) {{
        if (isPastEvent(m)) return;
        if (_mineInterest(m.interested)) myFits++;
        else if (!_vetoedItem(m) && _myPf && profileFits(_myPf, _fitBlob(m, m), canonicalRegion(m), priceNumOf(m.pricing), _isForeignLangEvent(m))) myFits++;
      }});
      // A cut-and-dry segmented status filter (data-stat). 'All' clears the
      // status filter; the rest are one-click chips. Other filters (region,
      // months, pipeline stages, …) live behind the filter icon beside search.
      function tile(key, num, label) {{
        var sel = (key === 'all') ? !opsStatFilter : (opsStatFilter === key);
        return '<button type="button" class="seg-chip' + (sel ? ' is-on' : '') +
          '" data-stat="' + key + '" aria-pressed="' + (sel ? 'true' : 'false') + '">' + label +
          (key !== 'all' ? '<span class="seg-num">' + num + '</span>' : '') + '</button>';
      }}
      var _isAngelaView = !!(window.isAngelaUser && window.isAngelaUser());
      var _coreTiles =
        tile('all', total, 'All') +
        tile('pipeline', inPipeline, 'Pending') +
        tile('booked', booked, 'Booked') +
        tile('attending', attending, _support ? 'Team Attending' : 'Attending');
      // "My fits" is a personal targeting filter — it means nothing for Angela,
      // who books events FOR the team and never attends herself, so she doesn't
      // get the chip at all (it used to sit at the end of her row). Everyone
      // else is targeting their own fits, so it leads — left of "All" (Hurley).
      var _myfitsTile = _isAngelaView ? '' : tile('myfits', myFits, 'My fits');
      // "Contacts" = events where we have an organizer email / POC — Angela-only
      // (like the ✉ badge), sits after Attending.
      var _contactsTile = _isAngelaView ? tile('contacts', contacts, 'Contacts') : '';
      $stats.innerHTML = _isAngelaView
        ? (_coreTiles + _contactsTile)
        : (_myfitsTile + _coreTiles);
      $stats.removeAttribute('hidden');
      Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (t) {{
        t.addEventListener('click', function () {{
          var k = t.dataset.stat;
          _userPickedStat = true;   // reader chose — stop auto-defaulting to My fits
          opsStatFilter = (k === 'all' || opsStatFilter === k) ? '' : k;
          // Jump to the Grid so the filtered events are actually visible — unless
          // the reader is on the Calendar or Map, which mirror the same filters
          // in place (no need to yank them to the grid).
          var goGrid = (currentView !== 'calendar' && currentView !== 'map' && currentView !== 'grid');
          // Niche exception: on the Calendar, clicking Booked/Attending only
          // makes sense in place if some of those events are still UPCOMING (the
          // calendar can't show past ones). If every booked/attending event is
          // already past, jump to the Grid and open the Past-events group so they
          // show; if any are upcoming, stay on the calendar filtered to those.
          if (currentView === 'calendar' && opsStatFilter === k && (k === 'booked' || k === 'attending')) {{
            var _meFirst = (getCollabName() || 'Team').toLowerCase().split(/\\s+/)[0];
            var _sup = isSupportPerson(getCollabName() || '');
            var _cards = $opsGrid.querySelectorAll('.ops-card'), _hasUpcoming = false;
            for (var _i = 0; _i < _cards.length; _i++) {{
              var _c = _cards[_i];
              if (_c.dataset.dupHidden === '1' || _c.dataset.past === '1') continue;
              // Booked = the event's Booked stage; Attending = per-account attendee
              // (team-wide for support).
              var _an = (_c.dataset.attendeeNames || '');
              var _hit = (k === 'booked')
                ? (_c.dataset.statusTags || '').split('|').indexOf('Booked') !== -1
                : (_sup ? _an.length > 0 : _an.split('|').indexOf(_meFirst) !== -1);
              if (_hit) {{ _hasUpcoming = true; break; }}
            }}
            if (!_hasUpcoming) {{ goGrid = true; opsCollapsedMonths.past = false; }}
          }}
          if (goGrid) setView('grid');
          applyFilters();
          // Reflect the active chip without a full re-render ('All' = nothing set).
          Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (x) {{
            x.classList.toggle('is-on', x.dataset.stat === (opsStatFilter || 'all'));
          }});
        }});
      }});
    }}

    // ════════════════════════════════════════════════════════════════
    // Queue + Planner views — render from the cached last-fetched data.
    // ════════════════════════════════════════════════════════════════

    // Accent-fold + lowercase, so territory keyword matching catches "São".
    function abFold(s) {{
      try {{ return String(s == null ? '' : s).normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase(); }}
      catch (e) {{ return String(s == null ? '' : s).toLowerCase(); }}
    }}

    // Normalise a catalog or manual row into the one shape the new views share.
    // ── Per-person ARCHIVE (hide from MY view only) ──────────────────
    // Archiving is now personal: it lives in localStorage keyed by the signed-in
    // name (like the dismiss / skip / hide-suggestion state), so hiding an event
    // takes it off MY grid without touching anyone else's. A legacy team-wide
    // event_state.hidden === true is still honored as a shared hide until someone
    // unarchives it (which clears that global flag). No DB column, no migration.
    function _archStoreKey() {{ return 'ab.arch.' + (getCollabName() || '').toLowerCase(); }}
    // Memoized so a full render's thousands of _isArchivedForMe() calls don't each
    // hit localStorage. Invalidated on save + whenever the signed-in name changes.
    var _archCache = null, _archCacheKey = null;
    function _archList() {{
      var k = _archStoreKey();
      if (_archCache && _archCacheKey === k) return _archCache;
      try {{ _archCache = JSON.parse(localStorage.getItem(k) || '[]'); }} catch (e) {{ _archCache = []; }}
      _archCacheKey = k;
      return _archCache;
    }}
    function _archSave(list) {{
      _archCacheKey = _archStoreKey(); _archCache = list;
      try {{ localStorage.setItem(_archCacheKey, JSON.stringify(list)); }} catch (e) {{}}
    }}
    function _archId(isManual, key) {{ return (isManual ? 'm' : 'e') + key; }}
    function _isArchivedForMe(isManual, key, legacyHidden) {{
      if (legacyHidden === true) return true;   // legacy team-wide archive
      return _archList().indexOf(_archId(isManual, key)) !== -1;
    }}
    function _archSetMine(isManual, key, on) {{
      var list = _archList(), id = _archId(isManual, key), i = list.indexOf(id);
      if (on && i === -1) list.push(id);
      else if (!on && i !== -1) list.splice(i, 1);
      _archSave(list);
    }}
    // Bridge for the modal closure (quick-actions).
    window.opsIsArchivedForMe = _isArchivedForMe;
    window.opsSetArchivedMine = _archSetMine;

    function opsItem(kind, base, st) {{
      var stages = stageTagsOf(st || base);
      var interested = (st && st.interested) || base.interested || [];
      var outr = (st && st.outreach_assignees) || base.outreach_assignees || [];
      var meta = opsMonthMeta(base.start_date || (st && st.start_date), base.date_str);
      // Prefer the event_state override where one exists: a CATALOG event's notes
      // and contact live on `st`, so reading base.* alone missed them entirely.
      var _pick = function (f) {{ var v = (st && st[f]); if (v === '__cleared__') return ''; return (v != null && String(v).trim() !== '') ? v : (base[f] || ''); }};
      // Same rule as the grid's search blob: identity + place + our own record +
      // contacts. NOT typical_attendees / past_speakers — those are other people's
      // names and titles, and they drown a contact search in false matches.
      var blob = [base.name, _pick('about'), _pick('focus_areas'),
                  base.location, base.region, base.city, base.country, _pick('type'),
                  _pick('notes'),
                  _pick('poc_name'), _pick('poc_email'), _pick('contact_info'),
                  _pick('outreach_note')].join(' ');
      return {{
        kind: kind,
        key: (kind === 'manual') ? base.id : base.num,
        name: base.name || 'Event',
        date_str: base.date_str || '',
        region: canonicalRegion(base),
        location: base.location || '',
        city: abFold(base.city || ((base.location || '').split(',')[0]) || ''),
        speaker: (st && st.speaker) || base.speaker || '',
        interested: (interested && interested.slice) ? interested.slice() : [],
        stages: stages,
        decision: (st && st.decision) || base.decision || '',
        deadline: (st && st.deadline === '__cleared__') ? '' : ((st && st.deadline) || base.deadline || ''),
        queue_dismissed: !!((st && st.queue_dismissed) || base.queue_dismissed),
        past: isPastEvent(base),
        hidden: _isArchivedForMe(kind === 'manual', kind === 'manual' ? base.id : base.num, (st && st.hidden === true) || (base && base.hidden === true)),
        is_private: !!((st && st.is_private) || base.is_private),   // catalog: on state; manual: on the row
        sort: meta.sort,
        startObj: base,
        start_date: base.start_date || (st && st.start_date) || '',
        end_date: base.end_date || (st && st.end_date) || base.start_date || '',
        attendees: ((st && st.attendees) || base.attendees || []).slice ? ((st && st.attendees) || base.attendees || []).slice() : [],
        outreach_assignees: (outr && outr.slice) ? outr.slice() : [],
        outreach_note: (st && st.outreach_note) || base.outreach_note || '',
        speaker_topic: (st && st.speaker_topic) || base.speaker_topic || '',
        // Notes + legacy status marker, so the "has anyone already worked this
        // event?" test (opsHandled) can see them. '__cleared__' is an explicit
        // blank; '__deleted__' is the soft-delete sentinel — neither is content.
        notes: (function () {{ var v = (st && st.notes); if (v === '__cleared__') v = ''; return (v && String(v).trim()) ? v : (base.notes || ''); }})(),
        workflow_status: (function () {{ var v = (st && st.status) || base.status || ''; return v === '__deleted__' ? '' : v; }})(),
        briefing_json: (st && st.briefing_json) || base.briefing_json || null,
        briefing_generated_at: (st && st.briefing_generated_at) || base.briefing_generated_at || null,
        createdBy: abFold(base.created_by || ''),
        text: abFold(blob)
      }};
    }}

    // "Has this event already been dealt with?" — ONE definition, used by every
    // surface that is supposed to show only UNTRIAGED events (Recently added,
    // the Planner's coverage gaps, Plan Ahead suggestions). Angela's rule: once
    // she's looked into an event — tagged it, written a note, flagged it for
    // someone, assigned a speaker, made a go/no-go call, or archived it — it is
    // no longer "new" and must stop being offered back to her as something to
    // triage. Everything here is a deliberate action someone took on the event.
    function opsHandled(it) {{
      if (!it) return false;
      return !!(
        it.hidden ||                                        // archived (per person)
        it.queue_dismissed ||                               // "not relevant" in the queue
        (it.stages && it.stages.length) ||                  // any pipeline stage
        (it.workflow_status && String(it.workflow_status).trim()) ||
        (it.notes && String(it.notes).trim()) ||
        (it.interested && it.interested.length) ||          // flagged for someone
        (it.attendees && it.attendees.length) ||
        (it.outreach_assignees && it.outreach_assignees.length) ||
        (it.speaker && String(it.speaker).trim()) ||
        (it.decision && String(it.decision).trim())
      );
    }}
    window.opsHandled = opsHandled;

    // Attendee persona keys for an event = explicit `attendees` ∪ any persona
    // matched by the assigned speaker. Drives the Day-Of tab + brief.
    function resolveAttendeeKeys(it) {{
      var P = window.AB_PERSONAS || {{}};
      var keys = [];
      (it.attendees || []).forEach(function (k) {{
        k = String(k || '').toLowerCase();
        if (k && P[k] && keys.indexOf(k) === -1) keys.push(k);
      }});
      // Include the assigned speaker ONLY if they're BOOKED (confirmed to speak).
      // A submitted-but-not-booked speaker has only APPLIED to speak — they are
      // NOT attending yet, so they must not show in the Day-Of "who's there" list.
      if ((it.stages || []).indexOf('Booked') !== -1) {{
        var sp = abFold(it.speaker || '');
        Object.keys(P).forEach(function (k) {{
          var first = abFold((P[k].name || '').split(' ')[0]);
          var hit = new RegExp('\\\\b' + k + '\\\\b').test(sp) || (first && new RegExp('\\\\b' + first + '\\\\b').test(sp));
          if (hit && keys.indexOf(k) === -1) keys.push(k);
        }});
      }}
      return keys;
    }}

    function opsAllItems() {{
      var items = [];
      (_lastEvs || []).forEach(function (ev) {{ items.push(opsItem('catalog', ev, _lastStateMap[ev.num] || {{}})); }});
      (_lastManual || []).forEach(function (m) {{ items.push(opsItem('manual', m, m)); }});
      return items;
    }}

    // Open the rich modal for a queue/planner row by reusing the grid card's
    // stashed _modalRec (which carries full edit context), so editing works.
    function opsOpenRef(kind, key) {{
      var sel = (kind === 'manual')
        ? '.ops-card[data-manual-id="' + key + '"]'
        : '.ops-card[data-event-num="' + key + '"]';
      var card = $opsGrid.querySelector(sel);
      if (card && card._modalRec && window.openEventModal) window.openEventModal(card._modalRec);
    }}

    function qStagePills(stages) {{
      if (!stages || !stages.length) return '<span class="q-stage-pill">Not started</span>';
      return stages.map(function (s) {{ return '<span class="q-stage-pill" style="' + stageStyle(s) + '">' + escapeHtml(s) + '</span>'; }}).join('');
    }}

    function opsQuickWrite(kind, key, patch) {{
      if (!window.opsWrite) return;
      window.opsWrite(kind === 'manual' ? 'manual_events' : 'event_state', key, patch);
    }}

    // ════════════════════════════════════════════════════════════════
    // Day-Of view — events happening now that an ArcticBlue person attends.
    // ════════════════════════════════════════════════════════════════
    function dayofItems() {{
      // Local date (not UTC) — toISOString() rolls to tomorrow after ~4pm
      // Pacific, which would push today's events out of the Day-Of tab.
      var _n = new Date();
      var today = _n.getFullYear() + '-' +
        String(_n.getMonth() + 1).padStart(2, '0') + '-' +
        String(_n.getDate()).padStart(2, '0');
      var todayList = [], soon = [];
      opsAllItems().forEach(function (it) {{
        if (it.hidden) return;
        it._keys = resolveAttendeeKeys(it);
        if (!it._keys.length) return;
        // Only events someone is confirmed ATTENDING or SPEAKING at — never a
        // tentative "Should Attend" (or a speaker merely assigned pre-booking).
        var _st = (it.stages || []).map(function (x) {{ return String(x).toLowerCase(); }});
        var _confirmed = _st.indexOf('booked') !== -1 || _st.indexOf('attending') !== -1 || (it.attendees && it.attendees.length);
        if (!_confirmed) return;
        var s = it.start_date || '', e = it.end_date || it.start_date || '';
        if (s && s <= today && today <= (e || s)) todayList.push(it);
        else if (s && s > today) soon.push(it);
      }});
      todayList.sort(function (a, b) {{ return a.sort - b.sort; }});
      soon.sort(function (a, b) {{ return a.sort - b.sort; }});
      return {{ today: todayList, soon: soon.slice(0, 8) }};
    }}

    function modeBadge(key) {{
      var m = ((window.AB_PERSONAS[key] || {{}}).mode) || 'room';
      return '<span class="mode-badge mode-' + m + '">' + m + '</span>';
    }}

    // Event-level activity (what they're DOING here) — same plain badge as the
    // brief, not the persona's static room/stage label.
    function dayofActivity(it) {{
      var t = (it.stages || []).map(function (s) {{ return String(s).toLowerCase(); }});
      if (t.indexOf('booked') !== -1) return 'Speaking';
      if (t.indexOf('attending') !== -1 || (it.attendees && it.attendees.length)) return 'Attending';
      return 'Targeting';
    }}
    function dayofCard(it, isToday) {{
      var P = window.AB_PERSONAS;
      var act = dayofActivity(it);
      // Same rounded, stage-coloured pill used across the app (Attending = teal,
      // Speaking = the Booked green) instead of the old square blue badge.
      var _actStage = act === 'Speaking' ? 'Booked' : (act === 'Attending' ? 'Attending' : null);
      var who = '<span class="q-stage-pill"' + (_actStage ? ' style="' + stageStyle(_actStage) + '"' : '') + '>' + escapeHtml(act) + '</span> ' +
        it._keys.map(function (k) {{ return '<span class="dayof-who">' + escapeHtml((P[k] || {{}}).name || k) + '</span>'; }}).join(', ');
      var loc = [it.location].filter(Boolean).join(' · ');
      var ready = it.briefing_json ? '<span class="dayof-ready">&#10003; brief ready</span>' : '';
      return '<div class="dayof-card' + (isToday ? ' is-today' : '') + '">' +
        '<div class="dayof-card-main">' +
          '<button type="button" class="dayof-name" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
          '<p class="dayof-meta">' + escapeHtml(it.date_str || '') + (loc ? ' · ' + escapeHtml(loc) : '') + '</p>' +
          '<div class="dayof-who-row">' + who + '</div>' +
        '</div>' +
        '<div class="dayof-actions">' + ready +
          '<button type="button" class="q-btn primary dayof-open" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '">Open brief &rarr;</button>' +
        '</div>' +
      '</div>';
    }}

    function renderDayOf() {{
      var host = document.getElementById('ops-dayof');
      if (!host) return;
      var d = dayofItems();
      var html = '<p class="dayof-intro"><strong>Day-Of briefings:</strong> When a teammate is attending an event, a tailored brief is generated here, which dives into who is in the room, the targets, speaker news, and the angles to use.</p>';
      if (!d.today.length && !d.soon.length) {{
        html += '<div class="dayof-empty">Nobody is marked as attending an event right now.<br>Open an event &rarr; <strong>Edit</strong> &rarr; tick a name under <strong>Attending (day-of)</strong>, and it surfaces here on the day &mdash; pre-generated overnight.</div>';
      }} else {{
        if (d.today.length) {{
          html += '<div class="dayof-section"><div class="dayof-sec-head"><span class="dayof-sec-title">&#9889; Happening today</span><span class="dayof-sec-count">' + d.today.length + '</span></div>' +
                  d.today.map(function (it) {{ return dayofCard(it, true); }}).join('') + '</div>';
        }}
        if (d.soon.length) {{
          html += '<div class="dayof-section"><div class="dayof-sec-head"><span class="dayof-sec-title">&#128197; Coming up &mdash; someone attending</span><span class="dayof-sec-count">' + d.soon.length + '</span></div>' +
                  d.soon.map(function (it) {{ return dayofCard(it, false); }}).join('') + '</div>';
        }}
      }}
      host.innerHTML = html;
      host.querySelectorAll('.dayof-open, .dayof-name').forEach(function (b) {{
        b.addEventListener('click', function () {{ openBriefDrawer(b.dataset.k, b.dataset.key); }});
      }});
      var badge = document.getElementById('vt-dayof-count');
      if (badge) {{ if (d.today.length) {{ badge.textContent = d.today.length; badge.removeAttribute('hidden'); }} else badge.setAttribute('hidden', ''); }}
    }}

    function kindToTable(kind) {{ return kind === 'manual' ? 'manual_events' : 'event_state'; }}

    function openBriefDrawer(kind, key) {{
      var it = opsAllItems().filter(function (x) {{ return x.kind === kind && String(x.key) === String(key); }})[0];
      if (!it) return;
      it._keys = resolveAttendeeKeys(it);
      var ov = document.getElementById('briefing-overlay');
      if (!ov) {{
        ov = document.createElement('div'); ov.id = 'briefing-overlay'; ov.className = 'briefing-overlay';
        ov.innerHTML = '<div class="briefing-card" role="dialog" aria-modal="true" aria-labelledby="bf-dlg-title">' +
          '<div class="briefing-top"><span class="briefing-top-title" id="bf-dlg-title">Day-Of brief</span>' +
          '<div class="briefing-top-actions">' +
            '<button type="button" class="bf-btn bf-targets" title="Find senior, budget-owning people to reach out to before this event (deeper research pass)">&#127919; Targets</button>' +
            '<button type="button" class="bf-btn bf-regen" title="Force a fresh research pass">&#8635; Regenerate</button>' +
            '<button type="button" class="bf-btn bf-copy">Copy</button>' +
            '<button type="button" class="bf-btn bf-close" aria-label="Close">&times;</button>' +
          '</div></div><div class="briefing-body" id="briefing-body"></div></div>';
        document.body.appendChild(ov);
        var _closeBf = function () {{
          ov.classList.remove('show'); document.body.style.overflow = '';
          if (ov._lastFocus && ov._lastFocus.focus) ov._lastFocus.focus();  // return focus to trigger
        }};
        ov.addEventListener('click', function (e) {{ if (e.target === ov) _closeBf(); }});
        ov.querySelector('.bf-close').addEventListener('click', _closeBf);
        document.addEventListener('keydown', function (e) {{
          if (!ov.classList.contains('show')) return;
          if (e.key === 'Escape') _closeBf();
          else if (window.trapTab) window.trapTab(ov.querySelector('.briefing-card'), e);
        }});
      }}
      ov._it = it;
      ov._lastFocus = document.activeElement;  // remember the trigger to restore later
      ov.querySelector('.bf-targets').onclick = function () {{ loadTargets(it, false); }};
      ov.querySelector('.bf-regen').onclick = function () {{ loadBrief(it, true); }};
      ov.querySelector('.bf-copy').onclick = function () {{ copyBrief(it); }};
      ov.classList.add('show');
      document.body.style.overflow = 'hidden';  // lock the page behind the drawer
      ov.querySelector('.bf-close').focus();     // move focus into the drawer
      if (it.briefing_json) renderBrief(it.briefing_json, it, true);
      else loadBrief(it, false);
    }}

    function loadBrief(it, regenerate) {{
      var body = document.getElementById('briefing-body');
      body.innerHTML = '<div class="bf-loading"><span class="bf-spin"></span> Researching the room, the speakers, and the latest news&hellip; this takes a few seconds.</div>';
      fetch('/api/briefing', {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ kind: kindToTable(it.kind), key: it.key, regenerate: !!regenerate }})
      }}).then(function (r) {{ return r.json(); }}).then(function (resp) {{
        if (resp && resp.brief) {{ it.briefing_json = resp.brief; renderBrief(resp.brief, it, !!resp.cached); if (currentView === 'dayof') renderDayOf(); }}
        else body.innerHTML = '<div class="bf-error">Could not generate the brief: ' + escapeHtml((resp && resp.error) || 'unknown error') + '</div>';
      }}).catch(function (e) {{ body.innerHTML = '<div class="bf-error">Briefing service unavailable (it runs on the deployed site). ' + escapeHtml(String(e)) + '</div>'; }});
    }}

    // ── Deep outreach targets (separate heavier pass) ────────────────
    function loadTargets(it, regenerate) {{
      var body = document.getElementById('briefing-body');
      body.innerHTML = '<div class="bf-loading"><span class="bf-spin"></span> Finding senior, budget-owning people, recent signals, and drafting openers&hellip; this is a deeper pass (~20–40s).</div>';
      fetch('/api/briefing', {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ kind: kindToTable(it.kind), key: it.key, deep_targets: true, regenerate: !!regenerate }})
      }}).then(function (r) {{ return r.json(); }}).then(function (resp) {{
        if (resp && resp.targets) {{ it.targets_json = resp.targets; renderTargets(resp.targets, it, resp); }}
        else body.innerHTML = '<div class="bf-error">Could not find targets: ' + escapeHtml((resp && resp.error) || 'unknown error') + '</div>';
      }}).catch(function (e) {{ body.innerHTML = '<div class="bf-error">Targets service unavailable (runs on the deployed site). ' + escapeHtml(String(e)) + '</div>'; }});
    }}

    function renderTargets(t, it, resp) {{
      t = t || {{}}; var people = t.people || [];
      function esc(s) {{ return escapeHtml(s == null ? '' : String(s)); }}
      var html = '<div class="tg-wrap"><div class="tg-bar">' +
        '<button type="button" class="bf-btn tg-back">&larr; Brief</button>' +
        '<button type="button" class="bf-btn tg-regen" title="Re-run the research (uses credits)">&#8635; Regenerate targets</button>' +
        '<span class="tg-count">' + people.length + ' ' + (people.length === 1 ? 'person' : 'people') + '</span></div>';
      if (people.length) html += '<p class="tg-verify">&#9888; Starting points &mdash; confirm each person &amp; their news before you reach out.</p>';
      if (t.note) html += '<p class="tg-note">' + esc(t.note) + '</p>';
      if (!people.length) html += '<p class="bf-muted">No web-confirmed senior targets found yet — usually means the speaker list isn’t public. Worth a re-run closer to the date.</p>';
      people.forEach(function (p, i) {{
        var sig = p.recent_signal || {{}};
        var conf = (p.confidence === 'confirmed')
          ? '<span class="tg-conf ok">confirmed</span>'
          : '<span class="tg-conf est">estimated</span>';
        html += '<div class="tg-card">' +
          '<div class="tg-head"><strong>' + esc(p.name) + '</strong>' + conf + '</div>' +
          (p.title || p.org ? '<div class="tg-role">' + esc([p.title, p.org].filter(Boolean).join(', ')) + '</div>' : '') +
          (p.segment_fit ? '<div class="tg-fit">' + esc(p.segment_fit) + '</div>' : '') +
          (p.session ? '<div class="tg-line">&#128197; ' + esc(p.session) + '</div>' : '') +
          (sig.summary ? '<div class="tg-line">&#128240; ' + esc(sig.summary) +
              (sig.date ? ' <span class="tg-muted">(' + esc(sig.date) + ')</span>' : '') +
              (sig.url ? ' <a href="' + esc(sig.url) + '" target="_blank" rel="noopener">source &#8599;</a>'
                       : ' <span class="tg-unver">unverified &middot; confirm before citing</span>') + '</div>' : '') +
          (p.linkedin_url ? '<div class="tg-line"><a href="' + esc(p.linkedin_url) + '" target="_blank" rel="noopener">Find on LinkedIn &#8599;</a></div>' : '') +
          (p.warm_via ? '<div class="tg-warm">&#128279; Warm via ' + esc(p.warm_via) + '</div>' : '') +
          (p.draft_email ? '<div class="tg-draft"><div class="tg-draft-h"><span class="bf-label">Draft opener</span>' +
              '<button type="button" class="tg-copy" data-i="' + i + '">Copy</button></div>' +
              '<pre class="tg-pre">' + esc(p.draft_email) + '</pre></div>' : '') +
          '</div>';
      }});
      if (resp && resp.persona) html += '<p class="tg-foot">For ' + esc(resp.persona) +
        (resp.model ? ' &middot; ' + esc(resp.model) : '') + (resp.cached ? ' &middot; cached' : '') + '</p>';
      html += '</div>';
      var body = document.getElementById('briefing-body');
      body.innerHTML = html;
      body.querySelector('.tg-back').onclick = function () {{ if (it.briefing_json) renderBrief(it.briefing_json, it, true); else loadBrief(it, false); }};
      body.querySelector('.tg-regen').onclick = function () {{ loadTargets(it, true); }};
      Array.prototype.forEach.call(body.querySelectorAll('.tg-copy'), function (btn) {{
        btn.onclick = function () {{
          var p = people[parseInt(btn.dataset.i, 10)];
          if (p && p.draft_email) {{
            try {{ navigator.clipboard.writeText(p.draft_email); btn.textContent = 'Copied'; setTimeout(function () {{ btn.textContent = 'Copy'; }}, 1500); }} catch (e) {{}}
          }}
        }};
      }});
    }}

    function copyBrief(it) {{
      // Plain-text dump of the WHOLE brief (mirrors the drawer, same order) so a
      // paste into Slack / email / notes carries every section, not just the summary.
      var b = it.briefing_json || {{}};
      var g = b.at_a_glance || {{}}, t = b.targets || {{}}, wir = b.who_in_room || {{}}, lw = b.logistics_win || {{}};
      var act = g.activity || (g.mode === 'stage' ? 'Speaking' : 'Attending');
      var L = [];
      function add(s) {{ L.push(s == null ? '' : String(s)); }}
      function head(title) {{ add(''); add(title.toUpperCase()); }}
      add(g.event || it.name);
      add((g.dates || it.date_str || '') + (g.venue ? ' | ' + g.venue : (it.location ? ' | ' + it.location : '')));
      add(act + (g.covered_by ? ' | covered by ' + g.covered_by : ''));
      if (b.why_were_here) {{ add(''); add(b.why_were_here); }}
      // Who is in the room
      if ((wir.named && wir.named.length) || (wir.titles && wir.titles.length) || (wir.industries && wir.industries.length)) {{
        head('Who is in the room (' + (wir.confidence || 'estimated') + ')');
        if (wir.titles && wir.titles.length) add(wir.titles.join(', '));
        if (wir.industries && wir.industries.length) add(wir.industries.join(' / '));
        (wir.named || []).forEach(function (n) {{
          var extra = [n.title, n.org].filter(Boolean).join(', ');
          add('- ' + (n.name || '') + (extra ? ' (' + extra + ')' : ''));
        }});
      }}
      // Targets
      var tp = t.people_to_find || [];
      if (tp.length || t.speaking_route_open || (t.facilitator_leads && t.facilitator_leads.length)) {{
        head('Targets');
        tp.forEach(function (x) {{
          if (!x || typeof x === 'string') {{ add('- ' + x); return; }}
          var sub = [x.name ? x.org : null, x.role].filter(Boolean).join(', ');
          add('- ' + (x.name || x.org || x.role || '') + (sub ? ' (' + sub + ')' : '') + (x.confidence ? ' [' + x.confidence + ']' : ''));
          if (x.why) add('    why: ' + x.why);
          if (x.where) add('    where: ' + x.where);
        }});
        if (t.speaking_route_open) add('Speaking route: ' + t.speaking_route_open);
        (t.facilitator_leads || []).forEach(function (x) {{ add('- ' + x); }});
      }}
      // Speaker spotlight
      if (b.speaker_spotlight && b.speaker_spotlight.length) {{
        head('Speaker spotlight');
        b.speaker_spotlight.forEach(function (s) {{
          add('- ' + (s.name || '') + (s.who ? ' - ' + s.who : ''));
          (s.news || []).forEach(function (n) {{ add('    ' + (n.headline || '') + (n.date ? ' (' + n.date + ')' : '') + (n.url ? ' ' + n.url : '')); }});
          if (s.hook) add('    hook: ' + s.hook);
        }});
      }}
      // Topic news
      if (b.topic_news && b.topic_news.length) {{
        head('Fresh news on your topic');
        b.topic_news.forEach(function (n) {{
          add('- ' + (n.headline || '') + (n.date ? ' (' + n.date + ')' : '') + (n.url ? ' ' + n.url : ''));
          if (n.relevance) add('    ' + n.relevance);
        }});
      }}
      // Angles
      if (b.angles && b.angles.length) {{
        head('Angles');
        b.angles.forEach(function (a) {{ add('- ' + a); }});
      }}
      // Logistics & win
      var lwL = [];
      if (lw.time) lwL.push('When: ' + lw.time);
      if (lw.room) lwL.push('Where: ' + lw.room);
      if (lw.link) lwL.push('Agenda: ' + lw.link);
      if (lw.move) lwL.push('First move: ' + lw.move);
      if (lw.win) lwL.push('Win: ' + lw.win);
      if (lwL.length) {{ head('Logistics & win'); lwL.forEach(add); }}
      // Unconfirmed
      if (b.unconfirmed && b.unconfirmed.length) {{
        head('Unconfirmed - verify on the ground');
        b.unconfirmed.forEach(function (u) {{ add('- ' + u); }});
      }}
      try {{ navigator.clipboard.writeText(L.join('\\n')); if (typeof flashOk === 'function') flashOk('Brief copied'); }} catch (e) {{}}
    }}

    function renderBrief(b, it, cached) {{
      b = b || {{}};
      function esc(s) {{ return escapeHtml(s == null ? '' : String(s)); }}
      function list(arr, fn) {{ return (arr || []).map(fn).join(''); }}
      function sec(title, inner) {{ return inner ? '<section class="bf-sec"><h3>' + title + '</h3>' + inner + '</section>' : ''; }}
      function newsLi(n) {{ return '<li>' + (n.url ? '<a href="' + esc(n.url) + '" target="_blank" rel="noopener">' + esc(n.headline) + '</a>' : esc(n.headline)) + (n.date ? ' <span class="bf-date">' + esc(n.date) + '</span>' : '') + (n.relevance ? '<br><span class="bf-muted">' + esc(n.relevance) + '</span>' : '') + '</li>'; }}
      var g = b.at_a_glance || {{}}, t = b.targets || {{}}, wir = b.who_in_room || {{}}, lw = b.logistics_win || {{}};
      var act = g.activity || (g.mode === 'stage' ? 'Speaking' : 'Attending');
      var actClass = act === 'Speaking' ? 'mode-stage' : 'mode-room';
      var html = '<div class="bf-head"><h2>' + esc(g.event || it.name) + '</h2>' +
        '<span class="mode-badge ' + actClass + '">' + esc(act) + '</span>' +
        '<p class="bf-sub">' + esc(g.dates || it.date_str || '') + (g.venue ? ' · ' + esc(g.venue) : (it.location ? ' · ' + esc(it.location) : '')) +
        (g.covered_by ? ' · covered by <strong>' + esc(g.covered_by) + '</strong>' : '') + '</p>' +
        (cached ? '<p class="bf-stamp">cached &middot; hit Regenerate for a fresh pass</p>' : '') + '</div>';
      html += sec('Why we are here', b.why_were_here ? '<p>' + esc(b.why_were_here) + '</p>' : '');
      html += sec('Who is in the room <span class="bf-conf">' + esc(wir.confidence || 'estimated') + '</span>',
        (wir.titles && wir.titles.length ? '<p class="bf-chips">' + list(wir.titles, function (x) {{ return '<span class="bf-chip">' + esc(x) + '</span>'; }}) + '</p>' : '') +
        (wir.industries && wir.industries.length ? '<p class="bf-muted">' + esc((wir.industries || []).join(' · ')) + '</p>' : '') +
        (wir.named && wir.named.length ? '<ul class="bf-list">' + list(wir.named, function (n) {{ return '<li><strong>' + esc(n.name) + '</strong>' + (n.title ? ' &mdash; ' + esc(n.title) : '') + (n.org ? ', ' + esc(n.org) : '') + '</li>'; }}) + '</ul>' : ''));
      var tgt = '';
      if (t.people_to_find && t.people_to_find.length) tgt += '<p class="bf-label">People to find</p><ul class="bf-list">' + list(t.people_to_find, function (x) {{
        if (!x || typeof x === 'string') return '<li>' + esc(x) + '</li>';
        var head = esc(x.name || x.org || x.role || '');
        var sub = [x.name ? x.org : null, x.role].filter(Boolean).join(' · ');
        return '<li><strong>' + head + '</strong>' + (sub ? ' &mdash; ' + esc(sub) : '') +
          (x.confidence ? ' <span class="bf-conf">' + esc(x.confidence) + '</span>' : '') +
          (x.why ? '<br><span class="bf-muted">' + esc(x.why) + '</span>' : '') +
          (x.where ? '<br><span class="bf-where">&#128205; ' + esc(x.where) + '</span>' : '') + '</li>';
      }}) + '</ul>';
      // 'Win target' (outcome_target) removed — a generic "have N good
      // conversations" line is a no-brainer, not signal.
      if (t.speaking_route_open) tgt += '<p class="bf-label">Speaking route</p><p>' + esc(t.speaking_route_open) + '</p>';
      if (t.facilitator_leads && t.facilitator_leads.length) tgt += '<p class="bf-label">Facilitator / partner leads</p><ul class="bf-list">' + list(t.facilitator_leads, function (x) {{ return '<li>' + esc(x) + '</li>'; }}) + '</ul>';
      html += sec('&#127919; Targets', tgt || '<p class="bf-muted">No specific targets surfaced yet.</p>');
      if (b.speaker_spotlight && b.speaker_spotlight.length) {{
        html += sec('Speaker spotlight', list(b.speaker_spotlight, function (s) {{
          return '<div class="bf-speaker"><strong>' + esc(s.name) + '</strong>' + (s.who ? ' &mdash; ' + esc(s.who) : '') +
            (s.news && s.news.length ? '<ul class="bf-news">' + list(s.news, newsLi) + '</ul>' : '') +
            (s.hook ? '<p class="bf-hook">&#8627; ' + esc(s.hook) + '</p>' : '') + '</div>';
        }}));
      }}
      if (b.topic_news && b.topic_news.length) html += sec('Fresh news on your topic', '<ul class="bf-news">' + list(b.topic_news, newsLi) + '</ul>');
      if (b.angles && b.angles.length) html += sec('Angles', '<ul class="bf-list">' + list(b.angles, function (x) {{ return '<li>' + esc(x) + '</li>'; }}) + '</ul>');
      var lwh = '';
      var lwLabel = {{ time: 'When', room: 'Where', link: 'Agenda' }};
      ['time', 'room', 'link'].forEach(function (k) {{ if (lw[k]) lwh += '<p><strong>' + lwLabel[k] + ':</strong> ' + (k === 'link' ? '<a href="' + esc(lw[k]) + '" target="_blank" rel="noopener">' + esc(lw[k]) + '</a>' : esc(lw[k])) + '</p>'; }});
      if (lw.move) lwh += '<p class="bf-move">&#9654; <strong>First move:</strong> ' + esc(lw.move) + '</p>';
      if (lw.win) lwh += '<p class="bf-win">&#127937; <strong>Win:</strong> ' + esc(lw.win) + '</p>';
      html += sec('Logistics &amp; win', lwh);
      if (b.unconfirmed && b.unconfirmed.length) html += sec('&#9888; Unconfirmed &mdash; verify on the ground', '<ul class="bf-list bf-unconf">' + list(b.unconfirmed, function (x) {{ return '<li>' + esc(x) + '</li>'; }}) + '</ul>');
      document.getElementById('briefing-body').innerHTML = html;
    }}

    // ── Queue: every flagged "apply for me" event, grouped by progress ──
    // THE queue definition — the tab badge and the rendered list MUST use this
    // same function. They used to carry two different filters (the badge dropped
    // Booked but counted dismissed rows; the list did the opposite), so the
    // number never matched what Angela actually saw in the Queue.
    function queueItems() {{
      return opsAllItems().filter(function (it) {{
        // Rejected leaves the queue entirely (Hurley 2026-07-30). The organiser
        // passed, so there is nothing to apply to and nothing in flight — it was
        // landing in "Submitted / in progress" because the Submitted tag that
        // got it there survives the rejection.
        if (it.stages.indexOf('Rejected') !== -1) return false;
        return window.visibleInterested(it.interested, it.speaker, it.attendees, it.stages).length &&
               !it.past && !it.queue_dismissed && !it.hidden;
      }});
    }}

    function renderQueue() {{
      var host = document.getElementById('ops-queue');
      if (!host) return;
      var order = window.opsStageOrder || ['Submitted', 'Followed up', 'Meeting held', 'Booked', 'Attending'];
      // Queue = events still needing an application. Count only interested
      // people NOT already booked/attending (window.visibleInterested).
      // queue_dismissed = Angela said "not relevant" (the × next to Mark
      // applied) — keeps it off the queue without touching who's interested.
      var items = queueItems();

      function deadlineHtml(it) {{
        if (_isJunkVal(it.deadline) || isDeadlinePast(it.deadline)) return '';
        var soon = isDeadlineSoon(it.deadline);
        return '<span class="q-deadline' + (soon ? ' soon' : '') + '">&#9203; ' + escapeHtml(it.deadline) + '</span>';
      }}
      function rowHtml(it, actions) {{
        var ints = window.visibleInterested(it.interested, it.speaker, it.attendees, it.stages).map(function (n) {{ return '<span class="q-int-chip">' + escapeHtml(n) + '</span>'; }}).join('');
        var dec = it.decision === 'go' ? '<span class="decision-badge go">&#10003; Go</span>' : '';
        var loc = [it.location].filter(Boolean).join(' &middot; ');
        var _cf = String(it.conflict_note || '').trim();
        return '<div class="queue-row queue-row-open" role="button" tabindex="0"' +
               ' data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' +
            '<div class="queue-main">' +
              '<button class="queue-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
              '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' &middot; ' + loc : '') + '</p>' +
              '<div class="queue-chips">' + ints + qStagePills(it.stages) + dec + deadlineHtml(it) + '</div>' +
              (_cf ? '<span class="ops-clash">&#9888; ' + escapeHtml(_cf) + '</span>' : '') +
            '</div>' +
            '<div class="queue-actions">' +
              '<button type="button" class="q-btn q-btn-conflict" data-act="conflict" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '" title="' +
                (_cf ? 'Edit the scheduling conflict' : 'Add a scheduling conflict') + '">&#9888;</button>' +
              actions(it) + '</div>' +
          '</div>';
      }}

      var booked = [], submitted = [], toApply = [];
      items.forEach(function (it) {{
        if (it.stages.indexOf('Booked') !== -1 || it.stages.indexOf('Attending') !== -1) booked.push(it);
        else if (it.stages.indexOf('Submitted') !== -1 || it.stages.indexOf('Followed up') !== -1 || it.stages.indexOf('Meeting held') !== -1) submitted.push(it);
        else toApply.push(it);
      }});
      function bySoonThenDate(a, b) {{
        var as = isDeadlineSoon(a.deadline) ? 0 : 1, bs = isDeadlineSoon(b.deadline) ? 0 : 1;
        if (as !== bs) return as - bs;
        return a.sort - b.sort;
      }}
      toApply.sort(bySoonThenDate); submitted.sort(bySoonThenDate);
      booked.sort(function (a, b) {{ return a.sort - b.sort; }});

      function markStage(it, stage) {{
        var tags = it.stages.slice();
        if (tags.indexOf(stage) === -1) tags.push(stage);
        tags = order.filter(function (s) {{ return tags.indexOf(s) !== -1; }});
        opsQuickWrite(it.kind, it.key, {{ status_tags: tags }});
      }}

      var html = '<p class="queue-intro"><strong>Angela&#39;s application queue.</strong> Every event a teammate flagged as &ldquo;apply for me,&rdquo; grouped by where it stands. Add more from any event &rarr; <em>Edit</em> &rarr; &ldquo;Interested,&rdquo; or from the Planner&#39;s coverage gaps.</p>';

      function section(title, list, kind) {{
        if (!list.length) return '';
        var rows = list.map(function (it) {{
          return rowHtml(it, function (x) {{
            var btns = '';
            if (kind === 'toApply') {{
              btns += '<div class="q-btn-row">' +
                '<button class="q-btn primary" data-act="submitted" data-k="' + x.kind + '" data-key="' + escapeHtml(String(x.key)) + '">&#10003; Mark applied</button>' +
                '<button class="q-btn danger q-btn-x" data-act="dismiss" data-k="' + x.kind + '" data-key="' + escapeHtml(String(x.key)) + '" title="Not relevant — remove from the queue without marking applied" aria-label="Remove from queue">&times;</button>' +
              '</div>';
            }}
            else if (kind === 'submitted') btns += '<button class="q-btn primary" data-act="booked" data-k="' + x.kind + '" data-key="' + escapeHtml(String(x.key)) + '">&#10003; Mark booked</button>';
            // "Details" now sits inline next to the event name (see rowHtml).
            return btns;
          }});
        }}).join('');
        return '<div class="queue-section"><div class="queue-sec-head"><span class="queue-sec-title">' + title + '</span><span class="queue-sec-count">' + list.length + '</span></div>' + rows + '</div>';
      }}

      if (!items.length) {{
        html += '<div class="queue-empty">Nobody has flagged an event yet.<br>Open any event &rarr; <strong>Edit</strong> &rarr; tick a name under &ldquo;Interested,&rdquo; and it lands here.</div>';
      }} else {{
        html += section('To apply', toApply, 'toApply');
        html += section('Submitted / in progress', submitted, 'submitted');
        html += section('Booked / attending', booked, 'booked');
      }}
      host.innerHTML = html;

      host.querySelectorAll('[data-ref-kind]').forEach(function (el) {{
        el.addEventListener('click', function () {{ opsOpenRef(el.getAttribute('data-ref-kind'), el.getAttribute('data-ref-key')); }});
      }});
      host.querySelectorAll('[data-act]').forEach(function (btn) {{
        btn.addEventListener('click', function (e) {{
          e.stopPropagation();
          var it = items.filter(function (x) {{ return x.kind === btn.getAttribute('data-k') && String(x.key) === btn.getAttribute('data-key'); }})[0];
          if (!it) return;
          var act = btn.getAttribute('data-act');
          if (act === 'conflict') {{
            // Add a conflict from where Angela is already working, instead of
            // making her open Details -> Edit for it (Hurley 2026-07-29) — and
            // in the row itself rather than a prompt at the top of the window
            // (Hurley 2026-07-30).
            var host2 = btn.parentNode && btn.parentNode.parentNode &&
                        btn.parentNode.parentNode.querySelector('.queue-main');
            if (!host2 || host2.querySelector('.ab-form')) return;
            var cur = String(it.conflict_note || '').trim();
            var w = document.createElement('div');
            w.className = 'ab-form';
            w.innerHTML = '<textarea class="ab-input" rows="2" ' +
                'placeholder="What\u2019s the clash? e.g. Thor is at the board offsite that week"></textarea>' +
              '<div class="ab-form-actions">' +
                '<button type="button" class="ab-btn-primary" data-go>Save</button>' +
                '<button type="button" class="ab-btn-ghost" data-cancel>Cancel</button>' +
                (cur ? '<button type="button" class="cf-edit" data-clear style="margin-left:auto;">Remove</button>' : '') +
              '</div>';
            // The row itself opens the card — keep clicks in the form local.
            w.addEventListener('click', function (ev) {{ ev.stopPropagation(); }});
            w.addEventListener('keydown', function (ev) {{ ev.stopPropagation(); }});
            host2.appendChild(w);
            var ta2 = w.querySelector('textarea');
            ta2.value = cur; ta2.focus(); ta2.setSelectionRange(cur.length, cur.length);
            function cfDone(val) {{
              it.conflict_note = val || '';
              opsQuickWrite(it.kind, it.key, {{ conflict_note: val || null }});
            }}
            w.querySelector('[data-go]').addEventListener('click', function () {{ cfDone(ta2.value.trim()); }});
            var clr = w.querySelector('[data-clear]');
            if (clr) clr.addEventListener('click', function () {{ cfDone(''); }});
            w.querySelector('[data-cancel]').addEventListener('click', function () {{ w.remove(); }});
            ta2.addEventListener('keydown', function (ev) {{
              if (ev.key === 'Escape') {{ ev.preventDefault(); w.remove(); }}
              if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {{ ev.preventDefault(); cfDone(ta2.value.trim()); }}
            }});
            return;
          }}
          if (act === 'dismiss') {{ opsQuickWrite(it.kind, it.key, {{ queue_dismissed: true }}); }}
          else markStage(it, act === 'submitted' ? 'Submitted' : 'Booked');
        }});
      }});
      updateViewBadges();
    }}

    // ════════════════════════════════════════════════════════════════
    // My events — bespoke to the signed-in person. Two lists Thor + Angela
    // asked for: "You're attending" (Booked/Attending, upcoming) and "Your
    // submissions" (Submitted / Followed up / Meeting held). Support people
    // (Angela/Hurley) coordinate for the whole team, so they see everyone's.
    // ════════════════════════════════════════════════════════════════
    var _myEventsPastOpen = false;   // My Events "Past events" dropdown starts collapsed
    function myEventsBuckets() {{
      var me = getCollabName() || '';
      var meFold = abFold(me);
      var support = !!me && isSupportPerson(me);
      var named = !!meFold;
      // You're "attending" an event if you're a booked speaker there OR a listed
      // attendee. The attendee list is the source of truth (per-account), so this
      // stays accurate even when the event's Attending stage wasn't synced — and
      // it covers BOTH past and upcoming events. Support (Angela/Hurley) see the
      // whole team's.
      var upcoming = [], past = [];
      // Derive from the rendered CARDS (the same merged source as the stat +
      // filter), so My events, the Attending tile, and the grid always agree —
      // opsItem() read attendees inconsistently for some past catalog events.
      if (named && $opsGrid) {{
        Array.prototype.forEach.call($opsGrid.querySelectorAll('.ops-card'), function (c) {{
          if (c.dataset.dupHidden === '1' || c.classList.contains('is-archived')) return;
          var r = c._modalRec; if (!r) return;
          var atts = (c.dataset.attendeeNames || '').split('|').filter(Boolean);
          var isAtt = support ? (atts.length > 0) : (atts.indexOf(meFold) !== -1);
          var stages = (c.dataset.statusTags || '').split('|');
          var isSpk = stages.indexOf('Booked') !== -1 && (support || speakerTokens(c.dataset.speaker || r.speaker || '').indexOf(meFold) !== -1);
          if (!isAtt && !isSpk) return;
          var _pastFlag = c.dataset.past === '1';
          // Use the SAME derived status the card already rendered, so My Lineup
          // reads identically to the grid ("Submitted to speak — Thor ·
          // Attending — Jerome") instead of its own vocabulary.
          var _slEl = c.querySelector('.ops-status-line');
          var item = {{
            kind: (r._table === 'manual_events') ? 'manual' : 'catalog',
            key: r._key, name: r.name || 'Event', date_str: r.date_str || '',
            region: r.region || '', location: r.location || '', speaker: r.speaker || '',
            statusHtml: _slEl ? _slEl.outerHTML : '',
            sort: parseInt(c.dataset.sort || '99999999', 10),
            _past: _pastFlag, briefReady: c.dataset.briefReady === '1',
            // A Day-Of brief researches the event online. A PRIVATE / invite-only
            // event (GDN, GBS …) has no web footprint — no url, no about, no
            // focus areas — so there's nothing to brief from. Skip those.
            briefable: !r.is_private && !!(String(r.url || '').trim() || String(r.about || '').trim() || String(r.focus_areas || '').trim())
          }};
          (_pastFlag ? past : upcoming).push(item);
        }});
        upcoming.sort(function (a, b) {{ return a.sort - b.sort; }});   // soonest first
        past.sort(function (a, b) {{ return b.sort - a.sort; }});       // most recent first
      }}
      return {{ me: me, support: support, named: named, upcoming: upcoming, past: past }};
    }}

    // ── "In the last week" + "Suggested for you" (My Events) ─────────
    // Per-person local read/dismiss state. An item comes down ONLY when it's
    // checked off (Hurley 2026-07-29) — opening the event or reading the thread
    // deliberately leaves it in the feed, so following a link to look at
    // something can't lose your place in the list. Nothing is written to the DB.
    function _wnStoreKey() {{ return 'ab.whatsnew.' + (getCollabName() || '').toLowerCase(); }}
    function _wnState() {{ try {{ return JSON.parse(localStorage.getItem(_wnStoreKey()) || '{{}}'); }} catch (e) {{ return {{}}; }} }}
    function _wnSave(s) {{ try {{ localStorage.setItem(_wnStoreKey(), JSON.stringify(s)); }} catch (e) {{}} }}
    // Mark a whole batch read in ONE write — drives "Mark all as read".
    function _wnDismissMany(items) {{
      var s = _wnState();
      (items || []).forEach(function (item) {{
        if (!item) return;
        // A comment row is cleared by recording the latest message we've shown
        // as seen, so a NEWER reply legitimately brings the row back.
        if (item.chatKey) {{ s.chatSeen = s.chatSeen || {{}}; s.chatSeen[item.chatKey] = ((_chatMeta[item.chatKey] || {{}}).latest) || new Date().toISOString(); }}
        else {{ s.dismissed = s.dismissed || {{}}; s.dismissed[item.id] = 1; }}
      }});
      _wnSave(s);
    }}
    function _wnDismiss(item) {{ _wnDismissMany([item]); }}
    // Compact relative time for the activity feed ("2h", "3d", "1w").
    function _relTime(ts) {{
      try {{
        var diff = (Date.now() - new Date(ts).getTime()) / 1000;
        if (diff < 60) return 'now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h';
        if (diff < 604800) return Math.floor(diff / 86400) + 'd';
        return Math.floor(diff / 604800) + 'w';
      }} catch (e) {{ return ''; }}
    }}
    // 1–2 letter avatar initials from a name.
    function _wnInitials(name) {{
      var parts = String(name || '').trim().split(/\\s+/).filter(Boolean);
      if (!parts.length) return '?';
      return (parts.length > 1 ? (parts[0][0] + parts[parts.length - 1][0]) : parts[0].slice(0, 1)).toUpperCase();
    }}
    function _whatsNewItems(all) {{
      var me = (getCollabName() || '').trim().toLowerCase().split(/\\s+/)[0];
      var st = _wnState(), dis = st.dismissed || {{}}, seen = st.chatSeen || {{}};
      var cutoff = new Date(Date.now() - 7 * 86400000).toISOString();
      var byNum = {{}}, byMid = {{}};
      (_lastEvs || []).forEach(function (e) {{ byNum[e.num] = e; }});
      (_lastManual || []).forEach(function (m) {{ byMid[m.id] = m; }});
      // Only surface updates for events ON YOUR RADAR — ones you're interested
      // in / attending / booked or pending (as speaker) for — otherwise this
      // fills with noise. Support (Angela/Hurley) coordinate for everyone, so
      // they see all of it. Build the radar key-set once.
      var _wnSupport = isSupportPerson(getCollabName() || '');
      var _radar = null;
      if (!_wnSupport && me) {{
        _radar = {{}};
        opsAllItems().forEach(function (it) {{
          var _sp = abFold(it.speaker || '').split(/[,;/&]| and |\\bplus\\b/).some(function (s) {{ return s.trim().split(/\\s+/)[0] === me; }});
          var _pend = _sp && (it.stages.indexOf('Booked') !== -1 || it.stages.indexOf('Submitted') !== -1 || it.stages.indexOf('Followed up') !== -1 || it.stages.indexOf('Meeting held') !== -1);
          var _on = _pend
            || (it.interested || []).some(function (n) {{ return abFold(n).split(/\\s+/)[0] === me; }})
            || (it.attendees || []).some(function (a) {{ return abFold(a).split(/\\s+/)[0] === me; }});
          if (_on) _radar[it.kind + ':' + it.key] = 1;
        }});
      }}
      function _onRadar(kind, key) {{ return !_radar || !!_radar[kind + ':' + key]; }}
      var items = [];
      // Real pipeline progress only — a teammate (never the automated
      // Enrichment writer) advanced the event to Followed up / Meeting held /
      // Booked. Not every edit: priority tweaks, notes, archiving etc. don't
      // belong here — this is "here's what actually moved," not an edit log.
      var _WN_STAGES = {{ 'Followed up': 1, 'Meeting held': 1, 'Booked': 1 }};
      (_lastStateRows || []).forEach(function (r) {{
        if (!r.updated_at || r.updated_at < cutoff) return;
        var whoF = firstNameFromEmail(r.updated_by || '') || '';
        if (!whoF || whoF.toLowerCase() === me || whoF.toLowerCase() === 'enrichment') return;
        var stg = stageTagsOf(r).filter(function (s) {{ return _WN_STAGES[s]; }});
        if (!stg.length) return;
        var ev = byNum[r.event_num]; if (!ev) return;
        var id = 'u:c' + r.event_num + ':' + r.updated_at;
        if (dis[id]) return;
        items.push({{ id: id, ts: r.updated_at, kind: 'catalog', key: ev.num, type: 'update', who: whoF,
          label: whoF + ' marked ' + (ev.name || 'an event') + ' as ' + stg.map(function (s) {{ return s.toLowerCase(); }}).join(' &amp; '),
          detail: 'marked ' + (ev.name || 'an event') + ' as ' + stg.map(function (s) {{ return s.toLowerCase(); }}).join(' &amp; ') }});
      }});
      // Newly added manual events — a teammate adding one by hand, never the
      // automated Dust ingest (dust@arcticblue.ai -> "Dust"), which finds and
      // adds events on its own and isn't news to anyone.
      (_lastManual || []).forEach(function (m) {{
        if (!m.created_at || m.created_at < cutoff) return;
        var whoF = firstNameFromEmail(m.created_by || '') || '';
        if (!whoF || whoF.toLowerCase() === me || whoF.toLowerCase() === 'dust') return;
        var id = 'a:m' + m.id; if (dis[id]) return;
        items.push({{ id: id, ts: m.created_at, kind: 'manual', key: m.id, type: 'update', who: whoF,
          label: whoF + ' added ' + (m.name || 'an event'),
          detail: 'added ' + (m.name || 'an event') }});
      }});
      // New comments since you last opened that event's chat (others' only).
      Object.keys(_chatMeta || {{}}).forEach(function (k) {{
        var meta = _chatMeta[k]; var last = seen[k] || '';
        var fresh = (meta.msgs || []).filter(function (x) {{ return x.at > last && String(x.author || '').toLowerCase().split(/\\s+/)[0] !== me; }});
        if (!fresh.length) return;
        var kind = k.charAt(0) === 'm' ? 'manual' : 'catalog'; var key = k.slice(1);
        var rec = kind === 'manual' ? byMid[key] : byNum[key]; if (!rec) return;
        // A comment that names/@mentions YOU always surfaces — even if the event
        // isn't otherwise on your radar (this is how a teammate flags you in).
        var mentioned = !!me && fresh.some(function (x) {{
          try {{ return new RegExp('(^|[^a-z0-9])@' + me + '([^a-z0-9]|$)', 'i').test(String(x.body || '')); }} catch (e) {{ return false; }}   // require the @ (Hurley)
        }});
        // Latest fresh comment drives the card's author + quote.
        var latestMsg = fresh.reduce(function (a, b) {{ return (a && a.at > b.at) ? a : b; }}, null);
        var cAuthor = latestMsg ? String(latestMsg.author || '').split(/\\s+/)[0] : '';
        items.push({{ id: 'c:' + k, ts: meta.latest, kind: kind, key: key, chatKey: k, mention: mentioned,
          type: 'comment', author: cAuthor, preview: (latestMsg ? String(latestMsg.body || '') : ''),
          eventName: (rec.name || 'an event'), count: fresh.length,
          label: (mentioned ? 'You were mentioned \\u2014 ' : (fresh.length + ' new comment' + (fresh.length > 1 ? 's' : '') + ' on ')) + (rec.name || 'an event') }});
      }});
      // Profile-material uploads (support only) — "Thor uploaded a headshot".
      // A routine, per-person update that opens My Profile (not an event).
      if (_wnSupport && _recentUploads && _recentUploads.length) {{
        _recentUploads.forEach(function (u) {{
          if (!u.at || u.at < cutoff) return;
          var whoF = String(u.who || '').charAt(0).toUpperCase() + String(u.who || '').slice(1);
          if (whoF.toLowerCase() === me) return;
          var id = 'f:' + u.who + ':' + u.cat + ':' + u.name;
          if (dis[id]) return;
          var isLink = /\\.weblink$/i.test(u.name);
          var verb = isLink ? 'added a link to' : 'uploaded';
          items.push({{ id: id, ts: u.at, type: 'update', who: whoF, profile: true,
            detail: verb + ' ' + u.catLabel + (isLink ? '' : ' \\u2014 ' + u.name),
            label: whoF + ' ' + verb + ' ' + u.catLabel }});
        }});
      }}
      // Radar-only — EXCEPT comments that mention you + profile uploads, which
      // always show (for support).
      items = items.filter(function (w) {{ return w.mention || w.profile || _onRadar(w.kind, w.key); }});
      items.sort(function (a, b) {{ return a.ts < b.ts ? 1 : -1; }});
      // The feed SHOWS at most 8 so a busy week can't bury My Lineup. Pass
      // all=true for the real set — "Mark all as read" has to clear the events
      // behind the cap too, or clearing the visible 8 just promotes the next 8
      // and the feed never empties.
      return all ? items : items.slice(0, 8);
    }}
    // Per-person "not for me" list — deciding NO on a suggestion takes it off
    // your list for good, so Plan Ahead is a decision you can clear to zero
    // (the yes side is "I'm interested"). Personal + local, like the "In the
    // last week" read-state — never written to the DB, never seen by others.
    function _sugSkipKey() {{ return 'ab.sugskip.' + (getCollabName() || '').toLowerCase(); }}
    function _sugSkips() {{ try {{ return JSON.parse(localStorage.getItem(_sugSkipKey()) || '{{}}'); }} catch (e) {{ return {{}}; }} }}
    function _sugSkipId(kind, key) {{ return kind + ':' + key; }}
    function _sugSkip(kind, key) {{
      var s = _sugSkips(); s[_sugSkipId(kind, key)] = 1;
      try {{ localStorage.setItem(_sugSkipKey(), JSON.stringify(s)); }} catch (e) {{}}
      _vetoLearn(kind, key);   // and learn from it (see below)
    }}

    // ── "Not for me" LEARNS, per person ──────────────────────────────────
    // A skip used to hide that one event and nothing else. Now each skip also
    // records WHAT was rejected, building a per-person negative profile that
    // narrows that person's My Fit and their suggestions (Hurley 2026-07-29).
    // Personal + local, like the skip list itself — one person's rejections
    // never affect anyone else's fits.
    //
    // The signals, weighted by how much they actually tell us:
    //   organizer (3) — the outfit putting the event on, read off the event URL's
    //                   domain (falling back to the brand word in the title).
    //                   "I don't want this company's events" is the clearest
    //                   thing a rejection can mean.
    //   topics    (2) — what the event is about.
    //   city      (2) — but ONLY a lesser-known city. An established hub (New
    //                   York, London, Dubai, Las Vegas …) can never be vetoed,
    //                   however many events get skipped there: those are the
    //                   cities the personas are built on.
    //   roles     (1) — who attends. Least stringent, per Hurley: it can tip a
    //                   decision, never make one on its own.
    //
    // Deliberately forgiving. Nothing is vetoed until a person has skipped at
    // least twice, every signal needs REPEAT evidence, and no single signal
    // except a twice-rejected organizer can reach the threshold alone.
    var _VETO_MIN = 3;
    var _VETO_REPEAT = 2;    // how many times a signal must recur to count
    function _vetoKey() {{ return 'ab.sugveto.' + (getCollabName() || '').toLowerCase(); }}
    function _vetoProfile() {{
      try {{
        var v = JSON.parse(localStorage.getItem(_vetoKey()) || 'null');
        if (v && typeof v === 'object') {{
          v.n = v.n || 0; v.orgs = v.orgs || {{}}; v.topics = v.topics || {{}};
          v.roles = v.roles || {{}}; v.cities = v.cities || {{}};
          return v;
        }}
      }} catch (e) {{}}
      return {{ n: 0, orgs: {{}}, topics: {{}}, roles: {{}}, cities: {{}} }};
    }}
    // The registrable-ish domain of an event URL — our best available stand-in
    // for "who is offering this event" (there's no organizer column).
    function _urlOrg(url) {{
      var s = String(url || '').trim();
      if (!s) return '';
      try {{
        var h = new URL(s.indexOf('://') === -1 ? 'https://' + s : s).hostname.toLowerCase();
        h = h.replace(/^www\\./, '');
        var parts = h.split('.').filter(Boolean);
        if (parts.length < 2) return '';
        // Keep three labels for co.uk / com.au / com.br style suffixes.
        var tail2 = parts.slice(-2).join('.');
        if (/^(co|com|org|net|gov|ac)\\.[a-z]{{2}}$/.test(tail2) && parts.length >= 3) return parts.slice(-3).join('.');
        return tail2;
      }} catch (e) {{ return ''; }}
    }}
    // Organizer key: the URL domain when we have one, else the distinctive brand
    // word from the title (same first-distinctive-word rule as _brandKey).
    function _orgKeyOf(o) {{
      if (!o) return '';
      var d = _urlOrg(o.url || (o.startObj && o.startObj.url));
      if (d) return 'd:' + d;
      var cityToks = {{}};
      abFold(String(o.location || '') + ' ' + String(o.city || ''))
        .replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).forEach(function (w) {{ if (w) cityToks[w] = 1; }});
      var words = abFold(o.name || '').replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).filter(Boolean);
      for (var i = 0; i < words.length; i++) {{
        var w = words[i];
        if (w.length >= 3 && !_BRAND_STOP[w] && !/^\\d+$/.test(w) && !cityToks[w]) return 'b:' + w;
      }}
      return '';
    }}
    // Every city the personas already target, folded. These are the "current
    // ones" Hurley wants kept — a rejection in one of them teaches us nothing
    // about the city, only about the event.
    var _KNOWN_CITY_TOKS = null;
    function _knownCityToks() {{
      if (_KNOWN_CITY_TOKS) return _KNOWN_CITY_TOKS;
      var t = {{}};
      var P = window.AB_PERSONAS || {{}};
      Object.keys(P).forEach(function (k) {{
        ((P[k] && P[k].geo) || []).forEach(function (g) {{
          abFold(g).replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).forEach(function (w) {{
            if (w && w.length >= 4) t[w] = 1;
          }});
        }});
      }});
      // Only cache a real answer. Caching an empty set (personas not parsed yet)
      // would silently disable the hub protection for the rest of the session.
      if (Object.keys(t).length) _KNOWN_CITY_TOKS = t;
      return t;
    }}
    // The city token for veto purposes — '' when it's an established hub.
    function _lesserCityOf(o) {{
      if (!o) return '';
      var known = _knownCityToks();
      var toks = abFold(String(o.city || '') + ' ' + String(o.location || ''))
        .replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/)
        .filter(function (w) {{ return w && w.length >= 4; }});
      // Any established-hub word in the location -> not a lesser-known city.
      for (var i = 0; i < toks.length; i++) {{ if (known[toks[i]]) return ''; }}
      return toks.length ? toks[0] : '';
    }}
    function _itemByKey(kind, key) {{
      var all = opsAllItems();
      for (var i = 0; i < all.length; i++) {{
        if (all[i].kind === kind && String(all[i].key) === String(key)) return all[i];
      }}
      return null;
    }}
    // Fold one rejected event into the signed-in person's negative profile.
    function _vetoLearn(kind, key) {{
      var it = _itemByKey(kind, key);
      if (!it) return;
      var v = _vetoProfile();
      v.n = (v.n || 0) + 1;
      var _b = it.startObj || it;
      var org = _orgKeyOf({{ name: it.name, url: _b.url || it.url, location: it.location || _b.location, city: it.city || _b.city }});
      if (org) v.orgs[org] = (v.orgs[org] || 0) + 1;
      var city = _lesserCityOf(it.startObj || it);
      if (city) v.cities[city] = (v.cities[city] || 0) + 1;
      var prof = _contentProfile(it);
      Object.keys(prof.topics).forEach(function (t) {{ v.topics[t] = (v.topics[t] || 0) + 1; }});
      Object.keys(prof.roles).forEach(function (r) {{ v.roles[r] = (v.roles[r] || 0) + 1; }});
      try {{ localStorage.setItem(_vetoKey(), JSON.stringify(v)); }} catch (e) {{}}
    }}
    // Score a candidate against the profile. Signals are pre-extracted so this
    // works both from a live item and from a rendered card's dataset.
    function _vetoScore(sig) {{
      var v = _vetoProfile();
      if ((v.n || 0) < 2) return 0;          // one click is not a pattern
      var s = 0;
      if (sig.org) {{
        var oc = v.orgs[sig.org] || 0;
        if (oc >= _VETO_REPEAT) s += 3;      // this outfit, more than once
        else if (oc === 1) s += 1;           // once — a nudge, not a verdict
      }}
      if (sig.city && (v.cities[sig.city] || 0) >= _VETO_REPEAT) s += 2;
      var topicHits = 0, roleHits = 0, k;
      var toks = _simTokens(sig.text || '');
      for (k in toks) {{
        if ((v.topics[k] || 0) >= _VETO_REPEAT) topicHits++;
        if ((v.roles[k]  || 0) >= _VETO_REPEAT) roleHits++;
      }}
      if (topicHits >= 2) s += 2;            // needs two repeatedly-rejected topics
      if (roleHits  >= 3) s += 1;            // audience alone can only ever tip it
      return s;
    }}
    function _vetoedSig(sig) {{ return _vetoScore(sig) >= _VETO_MIN; }}
    // From a live item / event object.
    function _vetoedItem(o) {{
      if (!o) return false;
      var base = o.startObj || o;
      return _vetoedSig({{
        org:  _orgKeyOf({{ name: o.name, url: base.url || o.url, location: o.location || base.location, city: o.city || base.city }}),
        city: _lesserCityOf(base),
        text: abFold([o.name, base.about, base.focus_areas, base.type, base.industry, base.typical_attendees, base.past_speakers].filter(Boolean).join(' '))
      }});
    }}
    // From a rendered card (the signals are stashed on its dataset at build time).
    function _vetoedCard(card) {{
      if (!card || !card.dataset) return false;
      return _vetoedSig({{
        org:  card.dataset.vetoOrg || '',
        city: card.dataset.vetoCity || '',
        text: card.dataset.fitText || ''
      }});
    }}
    // Plan-Ahead "hide this whole block" — dismisses a trip cluster or an Event
    // Radar group (keyed by its anchor event) from Plan Ahead only. Unlike
    // _sugSkip (a "not for me" on a single suggestion), this just declutters the
    // page — the anchor is often an event you're attending / interested in, so we
    // don't touch its status. Personal + local, like the other read-state.
    function _planHideKey() {{ return 'ab.planhide.' + (getCollabName() || '').toLowerCase(); }}
    function _planHides() {{ try {{ return JSON.parse(localStorage.getItem(_planHideKey()) || '{{}}'); }} catch (e) {{ return {{}}; }} }}
    function _planHidden(kind, key) {{ return !!_planHides()[kind + ':' + key]; }}
    function _planHide(kind, key) {{
      var s = _planHides(); s[kind + ':' + key] = 1;
      try {{ localStorage.setItem(_planHideKey(), JSON.stringify(s)); }} catch (e) {{}}
    }}
    // A solo trip's one-click "Find events near <city>" AI search can come back
    // empty — nothing else is on near that place & time (e.g. GBS / YPO). Once
    // it does, remember that per-anchor so we stop offering the (metered) button:
    // it's a dead end, and real nearby events, if any appear, surface as tracked
    // rows anyway. Local + personal, like the other read-state.
    function _planAreaEmptyKey() {{ return 'ab.planempty.' + (getCollabName() || '').toLowerCase(); }}
    function _planAreaEmpties() {{ try {{ return JSON.parse(localStorage.getItem(_planAreaEmptyKey()) || '{{}}'); }} catch (e) {{ return {{}}; }} }}
    function _planAreaEmpty(kind, key) {{ return !!_planAreaEmpties()[kind + ':' + key]; }}
    function _planAreaEmptyMark(kind, key) {{
      if (!kind || key == null || key === '') return;
      var s = _planAreaEmpties(); s[kind + ':' + key] = 1;
      try {{ localStorage.setItem(_planAreaEmptyKey(), JSON.stringify(s)); }} catch (e) {{}}
    }}
    // Proactive solo-trip discovery. Instead of a "Find events near <city>"
    // button, Plan Ahead auto-runs ONE metered area search per solo trip and
    // caches the outcome (found events OR empty) for 10 days — so it never
    // re-spends credits on every render. The result (≤5 events) renders inline.
    function _planAutoKey() {{ return 'ab.planauto.' + (getCollabName() || '').toLowerCase(); }}
    function _planAutos() {{ try {{ return JSON.parse(localStorage.getItem(_planAutoKey()) || '{{}}'); }} catch (e) {{ return {{}}; }} }}
    function _planAutoGet(kind, key) {{
      var a = _planAutos()[kind + ':' + key];
      if (!a || typeof a.ts !== 'number') return null;
      if (Date.now() - a.ts > 10 * 86400000) return null;   // 10-day TTL — refresh at most a few times a month
      return a;
    }}
    function _planAutoSet(kind, key, events) {{
      var a = _planAutos(); a[kind + ':' + key] = {{ ts: Date.now(), events: (events || []).slice(0, 5) }};
      try {{ localStorage.setItem(_planAutoKey(), JSON.stringify(a)); }} catch (e) {{}}
    }}
    var _planAutoInFlight = {{}};
    var _autoBudget = 0;   // new metered searches still allowed this render (reset per render)
    function _autoNearCriteria(o) {{
      var qOpts = _currentQuarterOptions();
      var quarters = (o.quarter && qOpts.indexOf(o.quarter) !== -1) ? [o.quarter] : qOpts.slice(0, 2);
      var recurring = [];
      try {{
        Array.prototype.forEach.call($opsGrid.querySelectorAll('.ops-card[data-past="1"]'), function (c) {{
          var nm = c._modalRec && c._modalRec.name;
          var atts = (c.dataset.attendeeNames || '').split('|').filter(Boolean);
          var stg = (c.dataset.statusTags || '').split('|');
          var bookedSpk = stg.indexOf('Booked') !== -1 && (c.dataset.speaker || '');
          if (nm && (atts.length || bookedSpk) && recurring.indexOf(nm) === -1) recurring.push(nm);
        }});
      }} catch (e) {{}}
      return {{ count: 5, types: SEARCH_TYPE_OPTIONS.slice(), quarters: quarters, regions: [],
        recurring: recurring.slice(0, 30), location: o.loc, date_from: o.dateFrom || '', date_to: o.dateTo || '', exclude: o.exclude || '' }};
    }}
    function _autoNodes(kind, key) {{ return document.querySelectorAll('.trip-auto[data-auto-kind="' + kind + '"][data-auto-key="' + key + '"]'); }}
    function _autoNote(kind, key, html) {{ Array.prototype.forEach.call(_autoNodes(kind, key), function (c) {{ c.innerHTML = html; }}); }}
    // Render ≤5 found events (or a brief empty note) into every live container
    // for this anchor — re-queried so a mid-flight re-render can't strand it.
    function _fillAuto(kind, key, city) {{
      var entry = _planAutoGet(kind, key);
      var events = (entry && entry.events) ? entry.events.slice(0, 5) : [];
      if (!events.length) {{ _autoNote(kind, key, '<p class="trip-nonear-note">No other events found near ' + city + ' around then.</p>'); return; }}
      var rows = events.map(function (ev, i) {{
        var link = ev.url ? ' <a href="' + escapeHtml(ev.url) + '" target="_blank" rel="noopener">\\u2197</a>' : '';
        var dup = isDuplicateName(ev.name, null, ev);
        return '<div class="trip-auto-row"><div class="trip-auto-info">' +
            '<span class="trip-auto-name">' + escapeHtml(ev.name || '(unnamed)') + link + '</span>' +
            '<span class="trip-auto-meta">' + escapeHtml(ev.date_str || '') + (ev.location ? ' \\u00b7 ' + escapeHtml(ev.location) : '') + '</span>' +
          '</div>' +
          (dup ? '<span class="trip-auto-dup">In tracker</span>'
               : '<button type="button" class="q-btn primary trip-auto-add" data-auto-idx="' + i + '">Add</button>') +
        '</div>';
      }}).join('');
      Array.prototype.forEach.call(_autoNodes(kind, key), function (c) {{
        c._autoEvents = events;
        c.innerHTML = '<p class="trip-auto-head">Also happening near ' + city + '</p>' + rows;
        c.querySelectorAll('.trip-auto-add').forEach(function (btn) {{
          btn.addEventListener('click', function (e) {{
            e.stopPropagation();
            var idx = parseInt(btn.getAttribute('data-auto-idx'), 10);
            var ev = (c._autoEvents || [])[idx]; if (!ev) return;
            btn.disabled = true; btn.textContent = 'Adding\\u2026';
            _insertFoundEvent(ev, getCollabName()).then(function (r) {{
              if (r && r.ok) {{ btn.textContent = 'Added \\u2713'; btn.classList.remove('primary'); flashOk('Added \"' + (ev.name || '') + '\"'); loadKnownNames(); }}
              else {{ btn.disabled = false; btn.textContent = (r && r.reason === 'duplicate') ? 'In tracker' : 'Add'; }}
            }});
          }});
        }});
      }});
    }}
    function _runAutoNear(o) {{
      var kind = o.anchorKind, key = o.anchorKey, id = kind + ':' + key;
      var city = escapeHtml(String(o.loc || '').split(',')[0].trim());
      if (!getCollabName() || !o.loc) return;
      if (_planAutoGet(kind, key)) {{ _fillAuto(kind, key, city); return; }}        // cached (found or empty)
      if (_planAreaEmpty(kind, key)) {{ _planAutoSet(kind, key, []); _fillAuto(kind, key, city); return; }}  // honor earlier empty — no re-spend
      if (_planAutoInFlight[id]) return;
      // Credit guard: cap NEW searches per render. Over-cap trips just show the
      // plain note; cached trips don't spend budget, so the next render covers
      // the rest — a big team still gets there, a few per render.
      if (_autoBudget <= 0) {{ _autoNote(kind, key, '<p class="trip-nonear-note">Nothing else tracked near ' + city + ' around then.</p>'); return; }}
      _autoBudget--;
      _planAutoInFlight[id] = 1;
      _autoNote(kind, key, '<p class="trip-nonear-note">\\ud83d\\udd0d Looking for events near ' + city + '\\u2026</p>');
      sb.auth.getSession().then(function (r) {{
        var token = r && r.data && r.data.session && r.data.session.access_token;
        var h = {{ 'Content-Type': 'application/json' }}; if (token) h['Authorization'] = 'Bearer ' + token;
        return fetch('/api/search', {{ method: 'POST', headers: h, body: JSON.stringify(_autoNearCriteria(o)) }})
          .then(function (res) {{ return res.json().then(function (j) {{ return [res.status, j]; }}); }})
          .then(function (pair) {{
            delete _planAutoInFlight[id];
            if (pair[0] !== 200) {{ _autoNote(kind, key, '<p class="trip-nonear-note">Couldn\\u2019t check for nearby events just now.</p>'); return; }}
            var evs = ((pair[1] && pair[1].events) || []).slice(0, 5);
            _planAutoSet(kind, key, evs);              // caches [] too (empty state, TTL'd)
            if (!evs.length) _planAreaEmptyMark(kind, key);
            _fillAuto(kind, key, city);
          }});
      }}).catch(function () {{   // covers a getSession reject too, so in-flight never leaks
        delete _planAutoInFlight[id];
        _autoNote(kind, key, '<p class="trip-nonear-note">Couldn\\u2019t check for nearby events just now.</p>');
      }});
    }}
    // Only events 2–4 months out belong in a "plan ahead" suggestion — Thor's
    // own example ("Colombia Tech Week is a month out, too soon") is a HARD
    // exclusion, not just a lower score. No known date -> can't judge it, skip.
    function _inPlanWindow(sort) {{
      if (!sort || sort >= 99999999) return false;
      var y = Math.floor(sort / 10000), mo = Math.floor((sort % 10000) / 100) - 1, d = sort % 100;
      var days = Math.round((new Date(y, mo, d || 1) - new Date()) / 86400000);
      return days >= 60 && days <= 120;
    }}
    // Personal suggestions, 2–4 months out — persona-matched (region +
    // themes/ICP), buyer-rich/high-priority boosted, quality-thresholded
    // (fewer than 10 is fine; never pad with weak picks). Compliance/
    // regulatory-centric events are excluded outright — not what ArcticBlue
    // does. Returns the FULL scored list — callers slice to their own depth
    // (the My Events widget shows a top-10 taste; the Plan Ahead page shows
    // everything, grouped by region).
    function _suggestionsFor() {{
      var meFirst = (getCollabName() || '').trim().toLowerCase().split(/\\s+/)[0];
      var P = (window.AB_PERSONAS || {{}})[meFirst] || null;
      // Personalization: what this person has actually attended / spoken at
      // (and flagged interested). This is the PRIMARY ranking signal below —
      // the persona is the fallback when there's no track record yet.
      var taste = _tasteProfile(meFirst);
      var BAD = /complian|regulat|regtech|gdpr|\\baudit/i;
      var kws = [];
      if (P) {{
        [].concat(P.themes || [], P.icp_industries || []).join(' ').toLowerCase()
          .replace(/[^a-z0-9]+/g, ' ').split(' ').forEach(function (w) {{
            if (w.length >= 5 && !/complian|governan|regulat|oversight|enterprise|industr|cross|function|market/.test(w) && kws.indexOf(w) === -1) kws.push(w);
          }});
      }}
      // Accent-fold geo tokens so "Sao Paulo"/"Bogota" match the folded
      // location blob, and city names compare cleanly.
      var geo = ((P && P.geo) || []).map(function (g) {{ return abFold(g); }});
      // 'stage' = there to speak (needs a topical reason); 'room' = there to
      // work the floor for buyers (geo + buyers is enough on its own).
      var mode = (P && P.mode) || 'room';
      // Region match. Broad-region tokens (us & canada, europe/emea, latin
      // america, asia-pacific, africa, mena) match the event's canonical
      // region. Anything else is a CITY or COUNTRY name, matched against the
      // event's location text — so a persona targeting specific cities
      // (NYC / Zurich / Sao Paulo …) only hits events actually there, not the
      // whole continent.
      function geoHit(it) {{
        var r = String(it.region || '').toLowerCase();
        // Match city/country tokens against the LOCATION fields only, not the
        // full text blob — otherwise a US event whose blurb mentions "London"
        // would false-match a Europe-targeting persona.
        var loc = abFold([it.location, it.city, it.region].filter(Boolean).join(' '));
        return geo.some(function (g) {{
          if (g === 'us & canada' || g === 'us' || g === 'usa' || g === 'canada' || g === 'north america' || g === 'na')
            return r.indexOf('us') !== -1 || r.indexOf('canada') !== -1 || r.indexOf('americas') !== -1;
          if (g === 'europe' || g === 'emea') return r.indexOf('europe') !== -1;
          if (g === 'latin america' || g === 'latam') return r.indexOf('latin') !== -1;
          if (g === 'asia-pacific' || g === 'apac' || g === 'asia') return r.indexOf('asia') !== -1;
          if (g === 'africa') return r.indexOf('africa') !== -1;
          if (g === 'mena' || g === 'middle east') return r.indexOf('mena') !== -1 || r.indexOf('middle east') !== -1;
          if (g === 'global-flagship') return true;
          // City / country name — match the event's location text.
          return g.length >= 4 && loc.indexOf(g) !== -1;
        }});
      }}
      var skips = _sugSkips();
      var scored = [];
      opsAllItems().forEach(function (it) {{
        if (it.past || it.hidden || it.queue_dismissed) return;
        if (it.stages.length) return;                       // already in the pipeline
        if (BAD.test(it.name)) return;                      // compliance-centric — skip
        if (!_govOk(meFirst) && _isGovDef(it)) return;       // gov/A&D is Jim's lane only
        if (_langBlocked(meFirst, it)) return;               // non-English event — not Thor's / Verma's / Joe's
        if (!_inPlanWindow(it.sort)) return;                 // outside the 2–4 month planning window
        if (skips[_sugSkipId(it.kind, it.key)]) return;      // you decided "not for me"
        if (_vetoedItem(it)) return;                         // looks like what you keep saying no to
        if ((it.interested || []).some(function (n) {{ return String(n).toLowerCase().split(/\\s+/)[0] === meFirst; }})) return;
        var o = it.startObj || {{}};
        var inGeo = (P && geo.length) ? geoHit(it) : false;
        // Default targeting rule: stay within the listed geographies. A hard
        // gate — the spec's "exceptional" out-of-geo events are rare AND meant
        // to be flagged, and the data has no reliable flagship marker (priority
        // is "high" on ~46% of events, too noisy to mean exceptional), so those
        // are left to Catalog search rather than padded into the suggestions.
        if (P && geo.length && !inGeo) return;
        var s = 0, why = [];
        if (inGeo) {{ s += 3; why.push(it.region); }}
        var hits = 0;
        for (var i = 0; i < kws.length && hits < 4; i++) {{
          if (it.text.indexOf(kws[i]) !== -1) {{ hits++; if (why.length < 4) why.push(kws[i]); }}
        }}
        s += hits;
        if (/buyer/i.test(o.audience_type || '')) {{ s += 2; why.push('buyer-rich'); }}
        if (/high/i.test(o.priority_override || o.priority || '')) s += 1;
        // How much this looks like what the person actually shows up for.
        var tScore = _tasteScore(taste, it);
        // Jim's remit is DC + government. Keep only events that are in DC, or
        // clearly gov (named, or matching 2+ of his gov themes); bias DC up.
        if (meFirst === 'jim') {{
          var jloc = abFold([it.location, it.city, it.region].filter(Boolean).join(' '));
          var inDC = jloc.indexOf('washington') !== -1;
          if (!inDC && !_isGovDef(it) && hits < 2) return;
          if (inDC) {{ s += 3; why.push('DC'); }}
        }}
        // A 'stage' persona is there to SPEAK, so a topic-less pick — in-geo and
        // buyer-rich but matching none of their themes — isn't a fit (this was
        // Joe, an HR speaker, getting London financial-services events). But if
        // it strongly matches their track record, keep it.
        if (P && mode === 'stage' && hits === 0 && tScore < 4) return;
        // Include on persona fit OR a strong resemblance to their history.
        if (s >= (P ? 5 : 4) || tScore >= 6) scored.push({{ it: it, s: s, tScore: tScore, why: why }});
      }});
      // Rank by track-record resemblance FIRST (most important), then persona
      // fit, then soonest — so "suggested for you" leads with events like the
      // ones this person keeps attending / speaking at.
      scored.sort(function (a, b) {{ return (b.tScore - a.tScore) || (b.s - a.s) || (a.it.sort - b.it.sort); }});
      return scored;   // callers slice to their own depth (My Events widget vs. the full Plan Ahead page)
    }}
    var _wnLast = [];   // what's on screen (capped at 8)
    var _wnAll  = [];   // everything eligible — what "Mark all as read" clears
    // Display name from a lowercased first-name key ("thor" -> "Thor"). Kept in
    // the ops closure (AB_ROSTER lives in the modal closure), so just capitalize.
    function _outreachName(k) {{
      k = String(k || '').toLowerCase();
      return k ? k.charAt(0).toUpperCase() + k.slice(1) : k;
    }}
    // Events where the signed-in person was asked to reach out (they may have a
    // connection). Support (Angela/Hurley) see every outstanding ask, team-wide.
    function _outreachItems() {{
      var me = getCollabName() || '';
      if (!me) return [];
      var meFirst = abFold(me).split(/\\s+/)[0];
      var support = isSupportPerson(me);
      var out = [];
      opsAllItems().forEach(function (it) {{
        if (it.past || it.hidden) return;
        var asg = (it.outreach_assignees || []).map(function (n) {{ return abFold(n).split(/\\s+/)[0]; }}).filter(Boolean);
        if (!asg.length) return;
        if (!support && asg.indexOf(meFirst) === -1) return;
        out.push({{ kind: it.kind, key: it.key, name: it.name, date_str: it.date_str, location: it.location, note: it.outreach_note || '', assignees: asg, sort: it.sort }});
      }});
      out.sort(function (a, b) {{ return a.sort - b.sort; }});
      return out;
    }}
    function renderMyEvents() {{
      var host = document.getElementById('ops-myevents');
      if (!host) return;
      var b = myEventsBuckets();
      if (!b.named) {{
        host.innerHTML = '<p class="queue-intro myev-intro"><strong>My Lineup.</strong> Set your name (top-right avatar &rarr; Someone else) to see the events you&#39;re booked to speak at or attending.</p>';
        return;
      }}
      function rowHtml(it) {{
        var loc = [it.location].filter(Boolean).join(' &middot; ');
        // Same derived status the grid card shows — one vocabulary everywhere.
        var statusHtml = it.statusHtml || '';
        // The Day-Of brief lives here (no separate tab) — on upcoming rows. A
        // private / invite-only event (no online footprint) can't be briefed,
        // so no brief button (see `briefable`). Briefs are Angela's tool — only
        // her view shows the button (everyone else's lineup rows have no brief).
        var brief = (it._past || !it.briefable || !(window.isAngelaUser && window.isAngelaUser())) ? '' :
          (it.briefReady ? '<span class="dayof-ready">&#10003; brief ready</span>' : '') +
          '<button type="button" class="q-btn primary" data-brief-kind="' + it.kind + '" data-brief-key="' + escapeHtml(String(it.key)) + '">Open brief &rarr;</button>';
        // The whole row opens the event details on click (like the grid cards) —
        // no separate "Details" button. The brief button stops propagation so it
        // still fires its own action.
        return '<div class="queue-row queue-row-open" role="button" tabindex="0" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '"><div class="queue-main">' +
            '<span class="queue-name">' + escapeHtml(it.name) + '</span>' +
            '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' &middot; ' + loc : '') + '</p>' +
            statusHtml +
          '</div>' +
          (brief ? '<div class="queue-actions">' + brief + '</div>' : '') +
          '</div>';
      }}
      function section(title, list, emptyMsg, collapsible, collapsed) {{
        var caret = collapsible ? '<span class="qsec-caret" aria-hidden="true">&#9662;</span>' : '';
        var head = '<div class="queue-sec-head"' + (collapsible ? ' role="button" tabindex="0"' : '') + '>' + caret +
          '<span class="queue-sec-title">' + title + '</span><span class="queue-sec-count">' + list.length + '</span></div>';
        var body = list.length ? list.map(rowHtml).join('') : '<div class="queue-empty">' + emptyMsg + '</div>';
        return '<div class="queue-section' + (collapsible ? ' collapsible' : '') + (collapsed ? ' collapsed' : '') + '">' + head + body + '</div>';
      }}
      var intro = b.support
        ? '<p class="queue-intro myev-intro"><strong>Team events:</strong> Everyone the team is booked to speak at or attending &mdash; upcoming first, past below.</p>'
        : '<p class="queue-intro myev-intro"><strong>' + escapeHtml(b.me) + '&#39;s events:</strong> Events you&#39;re booked to speak at or attending &mdash; upcoming first, past below.</p>';
      var upTitle = b.support ? 'Attending &amp; speaking' : 'You&#39;re attending';
      // Past events collapse into a dropdown, hidden by default (like the grid's
      // month groups). _myEventsPastOpen remembers if the reader expanded them.
      // "In the last week" — teammates' updates + new comments. A row comes down
      // when it's CHECKED OFF and only then; clicking through to the event leaves
      // it in place. "Mark all as read" clears the feed, or one person's routine
      // updates, in a single go.
      // Support: load recent profile uploads once, then re-render to fold them in.
      if (b.support && _recentUploads === null && !_recentUploadsLoading) {{
        _recentUploadsLoading = true;
        _loadRecentUploads(function () {{ _recentUploadsLoading = false; if (currentView === 'myevents') renderMyEvents(); }});
      }}
      // "Reach out" — events Angela asked this person to make contact for. Sits
      // at the very TOP of My Lineup (it's a to-do assigned to them). Support see
      // every outstanding ask across the team.
      var _outreach = _outreachItems();
      var outHtml = '';
      if (_outreach.length) {{
        var outRows = _outreach.map(function (o) {{
          var loc = [o.location].filter(Boolean).join(' &middot; ');
          var ask = b.support
            ? 'You asked ' + o.assignees.map(function (a) {{ return '<strong>' + escapeHtml(_outreachName(a)) + '</strong>'; }}).join(' &amp; ') + ' to reach out'
            : '<strong>Angela</strong> asked you to reach out &mdash; you may have a connection';
          var noteHtml = o.note ? '<p class="outreach-note">&ldquo;' + escapeHtml(o.note) + '&rdquo;</p>' : '';
          return '<div class="queue-row queue-row-open outreach-row" role="button" tabindex="0" data-ref-kind="' + o.kind + '" data-ref-key="' + escapeHtml(String(o.key)) + '"><div class="queue-main">' +
              '<span class="queue-name">' + escapeHtml(o.name) + '</span>' +
              '<p class="queue-meta">' + escapeHtml(o.date_str || 'Date TBD') + (loc ? ' &middot; ' + loc : '') + '</p>' +
              '<p class="outreach-ask"><span class="outreach-ico" aria-hidden="true">&#129309;</span> ' + ask + '</p>' + noteHtml +
            '</div></div>';
        }}).join('');
        outHtml = '<div class="queue-section outreach-section"><div class="queue-sec-head">' +
          '<span class="queue-sec-title">' + (b.support ? 'Outreach asks' : 'Reach out') + '</span>' +
          '<span class="queue-sec-count">' + _outreach.length + '</span></div>' + outRows + '</div>';
      }}
      _wnLast = _whatsNewItems();
      _wnAll  = _whatsNewItems(true);
      var wnHtml = '';
      if (_wnLast.length) {{
        // Comment threads surface at FULL visibility (they likely need a reply);
        // routine pipeline moves get grouped per person into a collapsed
        // "<Name> · N routine updates" row (tap to expand) so they don't drown
        // the conversations that need you.
        var _comments = [], _updates = [];
        _wnLast.forEach(function (w, i) {{ (w.type === 'comment' ? _comments : _updates).push({{ w: w, i: i }}); }});
        var _cardsHtml = _comments.map(function (o) {{
          var w = o.w;
          var quote = w.preview ? '&ldquo;' + escapeHtml(w.preview) + '&rdquo;' : escapeHtml(w.label);
          var head = w.mention
            ? '<strong>' + escapeHtml(w.author || 'Someone') + '</strong> mentioned you on <strong>' + escapeHtml(w.eventName || 'an event') + '</strong>'
            : '<strong>' + escapeHtml(w.author || 'Someone') + '</strong> commented on <strong>' + escapeHtml(w.eventName || 'an event') + '</strong>';
          return '<div class="wn-comment' + (w.mention ? ' is-mention' : '') + '" role="button" tabindex="0" data-wn-open="' + o.i + '">' +
              '<span class="wn-avatar-wrap"><span class="wn-avatar">' + escapeHtml(_wnInitials(w.author)) + '</span>' +
                '<span class="wn-chat-badge" title="Chat comment" aria-label="chat comment"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z"/></svg></span></span>' +
              '<div class="wn-comment-main">' +
                '<div class="wn-comment-head">' + head + '<span class="wn-time">' + escapeHtml(_relTime(w.ts)) + '</span></div>' +
                '<div class="wn-comment-quote">' + quote + '</div>' +
              '</div>' +
              '<button type="button" class="wn-check" data-wn-check="' + o.i + '" title="Mark as seen">&#10003;</button>' +
            '</div>';
        }}).join('');
        // Group routine updates by person.
        var _byWho = {{}}, _whoOrder = [];
        _updates.forEach(function (o) {{
          var who = o.w.who || 'Someone';
          if (!_byWho[who]) {{ _byWho[who] = []; _whoOrder.push(who); }}
          _byWho[who].push(o);
        }});
        var _groupsHtml = _whoOrder.map(function (who) {{
          var list = _byWho[who];
          var rows = list.map(function (o) {{
            return '<div class="queue-row wn-row"><div class="queue-main">' +
                '<button type="button" class="queue-name wn-open" data-wn-open="' + o.i + '">' + escapeHtml(o.w.detail || o.w.label) + '</button>' +
              '</div><div class="queue-actions"><button type="button" class="q-btn wn-check" data-wn-check="' + o.i + '" title="Mark as seen">&#10003;</button></div></div>';
          }}).join('');
          // Batch check-off for this person's routine updates — clearing a run of
          // pipeline moves one ✓ at a time was the tedious part (Hurley). Keyed by
          // the PERSON, not the visible row indexes, so it also clears their
          // updates sitting behind the 8-item display cap.
          return '<div class="wn-group collapsed">' +
              '<div class="wn-group-head" role="button" tabindex="0">' +
                '<span class="wn-avatar wn-avatar--sm">' + escapeHtml(_wnInitials(who)) + '</span>' +
                '<span class="wn-group-name">' + escapeHtml(who) + '</span>' +
                '<span class="wn-group-count">' + list.length + ' routine update' + (list.length === 1 ? '' : 's') + '</span>' +
                '<button type="button" class="wn-readall" data-wn-readgroup="' + escapeHtml(who) + '">Mark all as read</button>' +
                '<span class="qsec-caret" aria-hidden="true">&#9662;</span>' +
              '</div>' +
              '<div class="wn-group-body">' + rows + '</div>' +
            '</div>';
        }}).join('');
        wnHtml = '<div class="queue-section wn-section"><div class="queue-sec-head">' +
            '<span class="queue-sec-title">In the last week</span>' +
            // Say so when there's more behind the 8-item cap, otherwise
            // "Mark all as read" appears to clear 8 and silently clears 14.
            '<span class="queue-sec-count">' + _wnLast.length +
              (_wnAll.length > _wnLast.length ? ' of ' + _wnAll.length : '') + '</span>' +
            // Section-level clear-everything, same wording as the per-person one.
            '<button type="button" class="wn-readall wn-readall--all" data-wn-readall>Mark all as read</button>' +
          '</div>' +
          _cardsHtml + _groupsHtml + '</div>';
      }}
      // Plan Ahead now lives at the BOTTOM of My Lineup (below Past events),
      // replacing the old "Suggested for you" — it's a better version of the
      // same idea (trips + interest recs + monthly picks). renderPlanAhead()
      // fills the embed below; its own intro is the divider between the two.
      host.innerHTML = intro + outHtml + wnHtml +
        section(upTitle, b.upcoming, 'Nothing upcoming yet.') +
        (b.past.length ? section('Past events', b.past, '', true, !_myEventsPastOpen) : '') +
        '<div id="ops-planahead" class="ops-planahead-embed"></div>';
      host.querySelectorAll('[data-ref-kind]').forEach(function (el) {{
        el.addEventListener('click', function () {{ opsOpenRef(el.getAttribute('data-ref-kind'), el.getAttribute('data-ref-key')); }});
      }});
      host.querySelectorAll('[data-wn-open]').forEach(function (el) {{
        var _open = function () {{
          var w = _wnLast[parseInt(el.getAttribute('data-wn-open'), 10)];
          if (!w) return;
          // NOTE: opening does NOT mark it read — only the ✓ does (Hurley). You
          // can click through to the event, come back, and the row is still here.
          // A profile-upload update opens My Profile (it isn't tied to an event).
          if (w.profile) {{ setView('myprofile'); return; }}
          opsOpenRef(w.kind, String(w.key));
        }};
        el.addEventListener('click', _open);
        // Comment cards are role="button" — open on Enter / Space too.
        if (el.classList.contains('wn-comment')) el.addEventListener('keydown', function (e) {{ if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); _open(); }} }});
      }});
      host.querySelectorAll('[data-wn-check]').forEach(function (el) {{
        el.addEventListener('click', function (e) {{
          e.stopPropagation();   // don't also trigger the card/row's open
          var w = _wnLast[parseInt(el.getAttribute('data-wn-check'), 10)];
          if (!w) return;
          _wnDismiss(w);
          renderMyEvents();
        }});
      }});
      // "Mark all as read" — the whole feed.
      host.querySelectorAll('[data-wn-readall]').forEach(function (el) {{
        el.addEventListener('click', function (e) {{
          e.stopPropagation();
          _wnDismissMany(_wnAll);   // everything, not just the visible 8
          renderMyEvents();
        }});
      }});
      // "Mark all as read" — one person's routine updates. stopPropagation keeps
      // the click off the group header, which would otherwise collapse/expand.
      host.querySelectorAll('[data-wn-readgroup]').forEach(function (el) {{
        el.addEventListener('click', function (e) {{
          e.stopPropagation();
          var who = el.getAttribute('data-wn-readgroup') || '';
          _wnDismissMany(_wnAll.filter(function (w) {{
            return w.type !== 'comment' && String(w.who || 'Someone') === who;
          }}));
          renderMyEvents();
        }});
      }});
      // Per-person "routine updates" groups start collapsed; tap the header to
      // expand (ephemeral — no need to persist a one-week feed's open state).
      host.querySelectorAll('.wn-group-head').forEach(function (head) {{
        var _tg = function () {{ head.closest('.wn-group').classList.toggle('collapsed'); }};
        head.addEventListener('click', _tg);
        head.addEventListener('keydown', function (e) {{
          // Only the header itself toggles — Enter/Space on the nested
          // "Mark all as read" button must not also collapse the group.
          if (e.target !== head) return;
          if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); _tg(); }}
        }});
      }});
      host.querySelectorAll('[data-brief-kind]').forEach(function (el) {{
        el.addEventListener('click', function (e) {{ e.stopPropagation(); openBriefDrawer(el.getAttribute('data-brief-kind'), el.getAttribute('data-brief-key')); }});
      }});
      // Whole-row keyboard open (rows are role="button" now).
      host.querySelectorAll('.queue-row-open').forEach(function (row) {{
        row.addEventListener('keydown', function (e) {{
          if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); opsOpenRef(row.getAttribute('data-ref-kind'), row.getAttribute('data-ref-key')); }}
        }});
      }});
      // Past-events section is collapsible too — but the sug-section now shares
      // that class, so target the past one specifically (:not(.sug-section)).
      var _pastHead = host.querySelector('.queue-section.collapsible:not(.sug-section) .queue-sec-head');
      if (_pastHead) {{
        var _togglePast = function () {{
          var sec = _pastHead.closest('.queue-section');
          _myEventsPastOpen = !sec.classList.toggle('collapsed');
        }};
        _pastHead.addEventListener('click', _togglePast);
        _pastHead.addEventListener('keydown', function (e) {{ if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); _togglePast(); }} }});
      }}
      // Plan Ahead is embedded at the bottom (below Past events). Render it into
      // the #ops-planahead embed — it wires its own trips / radar / suggestion
      // rows (I'm interested / Not for me), and its intro is the section divider.
      renderPlanAhead();
      updateViewBadges();
    }}

    // Month label + chronological sort key from an opsItem's YYYYMMDD `sort`.
    function _sugMonth(sort) {{
      if (!sort || sort >= 99999999) return {{ key: 'tbd', label: 'Date TBD', sort: 99999999 }};
      var y = Math.floor(sort / 10000), mo = Math.floor((sort % 10000) / 100);
      if (mo < 1 || mo > 12) return {{ key: 'tbd', label: 'Date TBD', sort: 99999999 }};
      return {{ key: y + '-' + mo, label: OPS_MONTH_NAMES[mo - 1] + ' ' + y, sort: y * 100 + mo }};
    }}
    // ── Trip clustering — when you're already going to a city, what ELSE is on
    // nearby within a few days, so one trip can cover two events. Anchored on
    // the events you're attending / booked at / interested in; a candidate must
    // be close in BOTH place (same or neighbouring city, via the map's city
    // coords) and time (within ~3 days of your anchor's dates).
    function _haversineKm(a, b) {{
      var R = 6371, toR = Math.PI / 180;
      var dLat = (b[0] - a[0]) * toR, dLon = (b[1] - a[1]) * toR;
      var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(a[0] * toR) * Math.cos(b[0] * toR) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
      return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
    }}
    function _sortToDate(s) {{
      if (!s || s >= 99999999) return null;
      return new Date(Math.floor(s / 10000), Math.floor((s % 10000) / 100) - 1, (s % 100) || 1);
    }}
    function _endSortOf(it) {{
      var e = it.end_date;
      if (e && /^\\d{{4}}-\\d{{2}}-\\d{{2}}/.test(e)) {{ return (+e.slice(0, 4)) * 10000 + (+e.slice(5, 7)) * 100 + (+e.slice(8, 10)); }}
      return it.sort;
    }}
    // A "same host, same city" fingerprint. Catches near-identical events that
    // name-dedup misses because their titles differ — e.g. Corinium's
    // "CDAO Defense & Security", "CDAO Government" and "CDAO Washington D.C. 2026"
    // (all CDAO, all Washington DC, all Sep 22-23) collapse to one cluster row.
    // Key = first distinctive title word (the host/brand, e.g. "cdao") + the
    // resolved map coordinates (rounded to ~city scale). Coords come from geoOf
    // — NOT the raw location string, whose first token is often the venue
    // ("Le Méridien Washington…"), which would give the same event three keys.
    // City-name words in the title are skipped when picking the brand (so
    // "Boston Data Forum" vs "Boston AI Summit" don't collapse on "boston");
    // when a title has no distinctive word left, fall back to the full folded
    // name so unrelated events are never over-merged.
    var _BRAND_STOP = {{ the:1, and:1, for:1, ai:1, annual:1, summit:1, conference:1,
      conf:1, forum:1, expo:1, congress:1, event:1, events:1, world:1, global:1,
      national:1, international:1, intl:1, day:1, days:1, week:1, north:1, south:1,
      america:1, americas:1, european:1, europe:1, asia:1, usa:1, uk:1, emea:1,
      apac:1, latam:1 }};
    function _brandKey(it, g) {{
      var cityToks = {{}};
      abFold(String(it.location || '') + ' ' + String(it.city || ''))
        .replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).forEach(function (w) {{ if (w) cityToks[w] = 1; }});
      var words = abFold(it.name || '').replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).filter(Boolean);
      var brand = '';
      for (var i = 0; i < words.length; i++) {{
        var w = words[i];
        if (w.length >= 3 && !_BRAND_STOP[w] && !/^\\d+$/.test(w) && !cityToks[w]) {{ brand = w; break; }}
      }}
      if (!brand) return 'name:' + abFold(it.name || '');   // nothing distinctive -> dedupe exact names only
      var geoKey = g ? (Math.round(g[0] * 2) / 2) + ',' + (Math.round(g[1] * 2) / 2) : '?';
      return brand + '|' + geoKey;
    }}
    // ── Government / Aerospace & Defense is Jim's lane only ──────────────
    // Public-sector, federal, defense and A&D events are Jim's fit; they must
    // not leak into anyone else's suggestions, trip batches or interest recs.
    // Match the event's NAME + structured type only — NOT its blurb or attendee
    // list: broad enterprise events (World Summit AI, London Tech Week …) mention
    // "government" among many attendee types, and matching those free-text fields
    // wrongly pulled ~30 legit events out of Thor's fit. A truly gov/A&D event is
    // named as one ("CDAO Government", "GovTech Summit", "CDAO Defense"). Note:
    // "governance" is deliberately NOT matched — that's an enterprise theme.
    var GOVDEF = /\\b(government|governmental|federal|govtech|defense|defence|military|aerospace|warfare|homeland|nato|army|navy)\\b|\\bpublic sector\\b|\\bnational security\\b|\\barmed forces\\b/i;
    function _isGovDef(it) {{
      var o = it.startObj || {{}};
      return GOVDEF.test([it.name, o.type, o.industry, o.icp_industries].filter(Boolean).join(' '));
    }}
    // Who may see gov/A&D events: Jim (it's his fit) and support (Angela/Hurley,
    // who plan for the whole team, Jim included). Everyone else is filtered.
    function _govOk(first) {{ return first === 'jim' || isSupportPerson(first); }}

    // ── Content similarity — "because you're interested in X" ───────────
    // Match on what an event is ABOUT (industry + topics: focus_areas / about /
    // type) and WHO it's for (target roles: typical_attendees). Ubiquitous words
    // ("ai", "enterprise", "leaders" …) are dropped so matches turn on the
    // distinctive signal (cloud/healthcare/insurance/identity; architects/
    // developers/actuaries), not on words every event shares.
    var _SIM_STOP = {{ the:1, and:1, for:1, with:1, from:1, all:1, new:1, your:1, our:1,
      their:1, this:1, that:1, into:1, across:1, over:1, other:1, more:1, most:1, also:1,
      plus:1, who:1, how:1, why:1, what:1, when:1, where:1, event:1, events:1, summit:1,
      summits:1, conference:1, conferences:1, forum:1, forums:1, expo:1, congress:1,
      annual:1, global:1, world:1, national:1, international:1, series:1, edition:1, day:1,
      days:1, week:1, leaders:1, leader:1, leadership:1, executive:1, executives:1,
      professional:1, professionals:1, director:1, directors:1, manager:1, managers:1,
      management:1, officer:1, officers:1, head:1, heads:1, senior:1, junior:1, decision:1,
      maker:1, makers:1, making:1, teams:1, team:1, people:1, attendees:1, delegates:1,
      practitioner:1, practitioners:1, specialist:1, specialists:1, expert:1, experts:1,
      stakeholder:1, stakeholders:1, representative:1, representatives:1, personnel:1,
      staff:1, members:1, community:1, network:1, business:1, businesses:1, company:1,
      companies:1, organization:1, organizations:1, organisation:1, industry:1, industries:1,
      sector:1, sectors:1, market:1, markets:1, enterprise:1, enterprises:1, technology:1,
      technologies:1, tech:1, digital:1, innovation:1, strategy:1, strategic:1, solutions:1,
      solution:1, including:1, various:1, range:1, large:1, largest:1, leading:1, top:1, key:1,
      major:1, several:1, many:1, attend:1, attending:1, join:1, features:1, featuring:1,
      focus:1, focused:1, area:1, areas:1, ai:1, artificial:1, intelligence:1, data:1,
      transformation:1, future:1, next:1, gen:1, generation:1 }};
    function _simTokens(s) {{
      var out = {{}};
      abFold(String(s || '')).replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).forEach(function (w) {{
        if (w.length >= 4 && !_SIM_STOP[w]) out[w] = 1;
      }});
      return out;
    }}
    function _contentProfile(it) {{
      var o = it.startObj || {{}};
      // What it's about (name + focus/topics + type/industry) and WHO it's for
      // (audience roles + who's spoken/attended there). Name is included so a
      // series/brand a person keeps showing up for (CDAO, Money20/20, Gartner …)
      // scores as familiar; past speakers signal the room's calibre.
      return {{
        topics: _simTokens([it.name, o.focus_areas, o.about, o.type, o.industry].filter(Boolean).join(' ')),
        roles:  _simTokens([o.typical_attendees, o.past_speakers].filter(Boolean).join(' '))
      }};
    }}
    function _overlapN(a, b) {{ var n = 0; for (var k in a) {{ if (b[k]) n++; }} return n; }}
    // Score = how much two events share on industry/topics (weighted 2) + roles
    // (weighted 1). Returns the components so callers can gate on a real
    // industry match, not just a couple of stray role words.
    function _simScore(pa, pb) {{
      var t = _overlapN(pa.topics, pb.topics);
      var r = _overlapN(pa.roles, pb.roles);
      return {{ t: t, r: r, score: t * 2 + r }};
    }}
    // ── Taste profile — what a person actually does ──────────────────────
    // The strongest personalization signal is a person's own track record:
    // events they've ATTENDED or SPOKEN at (weight 2, past included — that IS
    // their history) and events they've flagged INTERESTED in (weight 1). We
    // accumulate the industry/topic + role tokens across all of them, so a
    // candidate that looks like what they keep showing up for scores high.
    // Cached, tokenized My-Profile text per person ({{ first: {{topics, roles}} }}).
    // Populated by _loadProfileTaste() from team_profiles; folded into taste so
    // suggestions get MORE tailored the more someone writes in their profile.
    var _profileTasteCache = null;
    function _tasteProfile(who) {{
      var topics = {{}}, roles = {{}}, n = 0;
      if (!who) return {{ topics: topics, roles: roles, has: false }};
      opsAllItems().forEach(function (it) {{
        var w = 0;
        if ((it.attendees || []).some(function (a) {{ return abFold(a).split(/\\s+/)[0] === who; }})) w = 2;
        else if (it.stages.indexOf('Booked') !== -1 && abFold(it.speaker || '').split(/\\s+/)[0] === who) w = 2;
        else if ((it.interested || []).some(function (x) {{ return abFold(x).split(/\\s+/)[0] === who; }})) w = 1;
        if (!w) return;
        n++;
        var p = _contentProfile(it);
        for (var t in p.topics) {{ topics[t] = (topics[t] || 0) + w; }}
        for (var r in p.roles)  {{ roles[r]  = (roles[r]  || 0) + w; }}
      }});
      // Their own words (bio / speaking topics / past talks / targeting notes)
      // are the most explicit preference signal — weight highest.
      var pt = _profileTasteCache && _profileTasteCache[who];
      if (pt) {{
        for (var pt2 in pt.topics) {{ topics[pt2] = (topics[pt2] || 0) + 3; }}
        for (var pr in pt.roles)  {{ roles[pr]  = (roles[pr]  || 0) + 3; }}
        if (Object.keys(pt.topics).length || Object.keys(pt.roles).length) n++;
      }}
      return {{ topics: topics, roles: roles, has: n > 0 }};
    }}
    // How much a candidate resembles the person's taste (accumulated weights).
    function _tasteScore(taste, it) {{
      if (!taste || !taste.has) return 0;
      var p = _contentProfile(it), s = 0, t;
      for (t in p.topics) {{ if (taste.topics[t]) s += taste.topics[t] * 2; }}
      for (t in p.roles)  {{ if (taste.roles[t])  s += taste.roles[t]; }}
      return s;
    }}
    // Pull each teammate's My-Profile text (bio / speaking topics / past talks /
    // targeting notes) and tokenize it into the taste cache, so the more someone
    // fills in their profile, the more tailored their suggestions become. Runs
    // best-effort (no team_profiles table yet -> stays empty); re-render after.
    function _loadProfileTaste(cb) {{
      if (typeof sb === 'undefined' || !sb || !sb.from) {{ if (cb) cb(); return; }}
      sb.from('team_profiles').select('*').then(function (r) {{
        var cache = {{}};
        ((r && r.data) || []).forEach(function (row) {{
          var who = abFold(String(row.person || row.display_name || '')).split(/\\s+/)[0];
          if (!who) return;
          var blob = [row.bio, row.topics, row.past_talks, row.notes].filter(Boolean).join(' ');
          if (!blob.trim()) return;
          cache[who] = {{ topics: _simTokens(blob), roles: _simTokens([row.topics, row.past_talks].filter(Boolean).join(' ')) }};
        }});
        _profileTasteCache = cache;
        if (cb) cb();
      }}, function () {{ _profileTasteCache = _profileTasteCache || {{}}; if (cb) cb(); }});
    }}
    // Recent profile-material uploads (last 7 days), for Angela's "In the last
    // week" — so she sees when someone adds a bio / deck / headshot / link.
    // Support-only + loaded once per session (storage has no recursive list, so
    // this is persons x material-slots; kept off the hot render path).
    function _loadRecentUploads(cb) {{
      if (typeof sb === 'undefined' || !sb || !sb.storage || !isSupportPerson(getCollabName() || '')) {{ _recentUploads = []; if (cb) cb(); return; }}
      var cutoff = new Date(Date.now() - 7 * 86400000).toISOString();
      sb.storage.from('profiles').list('', {{ limit: 200 }}).then(function (r) {{
        var persons = (((r && r.data) || []).map(function (f) {{ return f.name; }})
          .filter(function (n) {{ return n && n !== '.emptyFolderPlaceholder'; }}));
        var out = [], pending = persons.length * PROFILE_MATERIALS.length;
        if (!pending) {{ _recentUploads = []; if (cb) cb(); return; }}
        function _done() {{ if (--pending === 0) {{ _recentUploads = out; if (cb) cb(); }} }}
        persons.forEach(function (pk) {{
          PROFILE_MATERIALS.forEach(function (m) {{
            sb.storage.from('profiles').list(pk + '/' + m.k, {{ limit: 50 }}).then(function (rr) {{
              (((rr && rr.data) || [])).forEach(function (f) {{
                if (!f.name || f.name === '.emptyFolderPlaceholder') return;
                var at = f.created_at || (f.metadata && f.metadata.lastModified) || '';
                if (at && at >= cutoff) out.push({{ who: pk, cat: m.k, catLabel: m.label, name: f.name, at: at }});
              }});
              _done();
            }}, _done);
          }});
        }});
      }}, function () {{ _recentUploads = []; if (cb) cb(); }});
    }}
    // ── Home bases — trip batching is smarter about time + distance ──────
    // Each teammate's home city. The farther an anchor event is from home, the
    // wider the batch net: a local event batches tight (a day or two, same
    // metro); a long-haul trip batches the whole region for ~2 weeks (already
    // flew to Istanbul — Rome the next week is worth the detour). Support keys
    // map to NYC but go unused (their clusters are per-owner).
    var HOME_BASE = {{
      thor:   [40.71, -74.01],   // New York
      joe:    [40.71, -74.01],   // New York
      verma:  [40.72, -74.05],   // Jersey City
      angela: [40.71, -74.01],   // New York
      hurley: [40.71, -74.01],   // New York
      jerome: [51.51, -0.13],    // London
      carlos: [18.49, -69.93],   // Santo Domingo
      jim:    [38.90, -77.04]     // Washington DC
    }};
    function _homeOf(who) {{ return HOME_BASE[who] || null; }}
    // How wide to cast the batch net, by how far the anchor is from home (km).
    function _tripWindow(homeDist) {{
      if (homeDist > 4000) return {{ maxKm: 1600, maxGap: 12 }};   // intercontinental — batch the region
      if (homeDist > 1200) return {{ maxKm: 650,  maxGap: 6  }};   // cross-country / far domestic
      return {{ maxKm: 320, maxGap: 3 }};                          // near home — tight
    }}
    var SAME_CITY_KM = 40;   // within one metro: same-day is doable; across cities it isn't
    // Whose lineup drives Plan Ahead. A named teammate sees their own; support
    // (Angela/Hurley) plan for everyone, so they get the whole team's — every
    // persona first name. Returns [] when there's no signed-in name.
    // Who the team actually puts on stage, most often first — Thor leads
    // (Hurley 2026-07-30). Support sees every persona, but in THIS order rather
    // than whatever order personas.json happens to be written in.
    var PLAN_ORDER = ['thor', 'verma', 'jerome', 'joe', 'carlos', 'jim', 'scott'];
    function planSort(names) {{
      return names.slice().sort(function (a, b) {{
        var ia = PLAN_ORDER.indexOf(String(a).toLowerCase());
        var ib = PLAN_ORDER.indexOf(String(b).toLowerCase());
        if (ia === -1) ia = 99; if (ib === -1) ib = 99;
        return ia - ib || String(a).localeCompare(String(b));
      }});
    }}
    window.abPlanOrder = planSort;
    function _planOwners() {{
      var me = getCollabName() || '';
      var first = abFold(me).split(/\\s+/)[0];
      if (!first) return [];
      if (isSupportPerson(me)) return planSort(Object.keys(window.AB_PERSONAS || {{}}));
      return [first];
    }}
    // The committed-travel role a given person has for an event (drives trip
    // batching). Interested is NOT here — that's a maybe, handled by content
    // recs, not "you're already going".
    function _travelRole(it, who) {{
      if ((it.attendees || []).some(function (a) {{ return abFold(a).split(/\\s+/)[0] === who; }})) return 'attending';
      if (it.stages.indexOf('Booked') !== -1 && abFold(it.speaker || '').split(/\\s+/)[0] === who) return 'speaking at';
      return null;
    }}
    function _anyRole(it, who) {{
      return _travelRole(it, who) ||
        ((it.interested || []).some(function (n) {{ return abFold(n).split(/\\s+/)[0] === who; }}) ? 'interested in' : null);
    }}
    function _tripClusters() {{
      var owners = _planOwners();
      if (!owners.length) return [];
      var support = isSupportPerson(getCollabName() || '');
      var BADt = /complian|regulat|regtech|gdpr|\\baudit/i;
      var skips = _sugSkips();
      var DAY_MS = 86400000;
      var all = opsAllItems();
      // Anchors = committed travel (attending / booked) for any owner. One anchor
      // per (event, owner); a support user sees every teammate's trips labelled
      // with who's going.
      var anchors = [];
      all.forEach(function (it) {{
        if (it.past || it.hidden) return;
        if (!it.sort || it.sort >= 99999999) return;
        // geo may be null (an unmappable location like "Istanbul" before it was
        // in the coord table) — we still LIST the trip, we just can't batch
        // nearby events onto it.
        var g = geoOf(it);
        owners.forEach(function (who) {{
          var r = _travelRole(it, who); if (!r) return;
          anchors.push({{ it: it, who: who, role: r, geo: g, startD: _sortToDate(it.sort), endD: _sortToDate(_endSortOf(it)) }});
        }});
      }});
      if (!anchors.length) return [];
      anchors.sort(function (a, b) {{ return a.it.sort - b.it.sort; }});
      var clusters = [], usedKeys = {{}};
      anchors.forEach(function (anchor) {{
        if (!anchor.startD || !anchor.endD) return;
        var near = [];
        // Only look for nearby events to batch when we know WHERE the trip is.
        // A trip with no resolvable coords still shows — just with nothing
        // batched onto it (so every committed trip is listed).
        if (anchor.geo) {{
          var ownerGov = _govOk(anchor.who);   // gov/A&D nearby only for Jim's (or support's) trips
          // Widen the batch window with how far this trip already is from home.
          var home = _homeOf(anchor.who);
          var win = _tripWindow(home ? _haversineKm(home, anchor.geo) : 0);
          var seenName = {{}};
          all.forEach(function (it) {{
            if (it === anchor.it) return;
            if (it.past || it.hidden || it.queue_dismissed) return;
            if (it.stages.length) return;                       // already in the pipeline
            if (BADt.test(it.name)) return;
            if (_anyRole(it, anchor.who)) return;               // already on this person's list
            if (!ownerGov && _isGovDef(it)) return;             // gov/A&D is Jim's lane
            if (_langBlocked(anchor.who, it)) return;           // non-English — don't batch it onto their trip
            if (skips[_sugSkipId(it.kind, it.key)]) return;
            if (_vetoedItem(it)) return;                        // learned "not for me" pattern
            if (usedKeys[anchor.who + '|' + it.kind + ':' + it.key]) return;  // don't repeat within this person's trips
            var nm = abFold(it.name); if (seenName[nm]) return;  // collapse duplicate events
            var g = geoOf(it); if (!g) return;
            var km = _haversineKm(anchor.geo, g);
            if (km > win.maxKm) return;
            var cs = _sortToDate(it.sort), ce = _sortToDate(_endSortOf(it));
            if (!cs || !ce) return;
            var gap = Math.max(0, Math.ceil((cs - anchor.endD) / DAY_MS), Math.ceil((anchor.startD - ce) / DAY_MS));
            if (gap > win.maxGap) return;
            // Can't be in two different cities on the same day — only same-metro
            // events may overlap in time. Across cities, require a day between.
            if (km >= SAME_CITY_KM && gap === 0) return;
            seenName[nm] = 1;
            near.push({{ it: it, gap: gap, km: km, geo: g }});
          }});
          if (near.length) {{
            // Rank what to actually surface: a trip batches a HANDFUL, not a
            // continent. Float events that match the anchor's topic (topic
            // overlap >= 2), then the closest, then the soonest.
            var aProf = _contentProfile(anchor.it);
            near.forEach(function (n) {{ n.rel = _simScore(aProf, _contentProfile(n.it)).t; }});
            near.sort(function (a, b) {{
              var ra = a.rel >= 2 ? 0 : 1, rb = b.rel >= 2 ? 0 : 1;
              return ra - rb || a.km - b.km || a.gap - b.gap;
            }});
            // Collapse same-host/same-city near-dupes (CDAO Defense & Security /
            // CDAO Government / CDAO Washington D.C. -> one row).
            var seenBrand = {{}};
            seenBrand[_brandKey(anchor.it, anchor.geo)] = 1;
            near = near.filter(function (n) {{
              var bk = _brandKey(n.it, n.geo);
              if (seenBrand[bk]) return false;
              seenBrand[bk] = 1; return true;
            }});
            near = near.slice(0, 5);    // cap — one trip covers a few, not twenty
            near.sort(function (a, b) {{ return a.it.sort - b.it.sort; }});   // show the kept few chronologically
            near.forEach(function (n) {{ usedKeys[anchor.who + '|' + n.it.kind + ':' + n.it.key] = 1; }});
          }}
        }}
        // Push EVERY committed trip — even a solo one with nothing nearby — so
        // "Batch your trips" lists all of a person's attending/speaking events.
        clusters.push({{ anchor: anchor.it, who: anchor.who, support: support, role: anchor.role, near: near }});
      }});
      return clusters;
    }}
    // "Because you're interested in X" — content recommendations. For each event
    // an owner is INTERESTED in (a maybe, not committed travel), surface upcoming
    // events that match on industry/topics + target roles, wherever they are.
    // This is the content counterpart to trip batching (which is geographic).
    function _contentRecs() {{
      var owners = _planOwners();
      if (!owners.length) return [];
      var BADt = /complian|regulat|regtech|gdpr|\\baudit/i;
      var skips = _sugSkips();
      var all = opsAllItems();
      // Interest anchors: one per (event, owner). Collapse to a single row per
      // event, listing everyone interested, so support doesn't see it repeated.
      var anchorMap = {{}}, anchorOrder = [];
      all.forEach(function (it) {{
        if (it.past || it.hidden) return;
        if (!it.sort || it.sort >= 99999999) return;
        var who = owners.filter(function (w) {{
          return (it.interested || []).some(function (n) {{ return abFold(n).split(/\\s+/)[0] === w; }});
        }});
        if (!who.length) return;
        var id = it.kind + ':' + it.key;
        if (!anchorMap[id]) {{ anchorMap[id] = {{ it: it, who: who.slice() }}; anchorOrder.push(id); }}
      }});
      if (!anchorOrder.length) return [];
      anchorOrder.sort(function (a, b) {{ return anchorMap[a].it.sort - anchorMap[b].it.sort; }});
      var recs = [], MAX_ANCHORS = 6, PER = 3;
      anchorOrder.slice(0, MAX_ANCHORS).forEach(function (id) {{
        var A = anchorMap[id], anchor = A.it;
        var ap = _contentProfile(anchor);
        // Nothing to match on (a sparse manual event with no focus/roles) -> skip.
        if (!Object.keys(ap.topics).length) return;
        var ownerGov = A.who.some(_govOk);
        var cand = [], seenBrand = {{}}, seenName = {{}};
        seenBrand[_brandKey(anchor, geoOf(anchor))] = 1;
        all.forEach(function (it) {{
          if (it === anchor) return;
          if (it.past || it.hidden || it.queue_dismissed) return;
          if (it.stages.length) return;                       // already in the pipeline
          if (BADt.test(it.name)) return;
          if (!ownerGov && _isGovDef(it)) return;             // gov/A&D is Jim's lane
          // Non-English event: drop it only when EVERY owner this rec is for is
          // English-only — if Jerome or Carlos is also interested, it still fits.
          if (A.who.every(function (w) {{ return _langBlocked(w, it); }})) return;
          if (skips[_sugSkipId(it.kind, it.key)]) return;
          if (_vetoedItem(it)) return;                        // learned "not for me" pattern
          // Skip anything an interested owner is already tied to.
          if (A.who.some(function (w) {{ return _anyRole(it, w); }})) return;
          var nm = abFold(it.name); if (seenName[nm]) return;
          var sc = _simScore(ap, _contentProfile(it));
          if (sc.t < 2 || sc.r < 1) return;                    // needs a real industry AND audience overlap
          seenName[nm] = 1;
          cand.push({{ it: it, sc: sc }});
        }});
        if (!cand.length) return;
        cand.sort(function (a, b) {{ return b.sc.score - a.sc.score || a.it.sort - b.it.sort; }});
        // Brand+city dedupe so near-identical hosts don't fill the list.
        var picked = [];
        for (var i = 0; i < cand.length && picked.length < PER; i++) {{
          var bk = _brandKey(cand[i].it, geoOf(cand[i].it));
          if (seenBrand[bk]) continue;
          seenBrand[bk] = 1; picked.push(cand[i]);
        }}
        if (picked.length) recs.push({{ anchor: anchor, who: A.who, recs: picked }});
      }});
      return recs;
    }}
    // ── Plan Ahead: the everyone-facing "decide what to go to" surface —
    // 2–4 month suggestions you clear with one call each: "I'm interested"
    // (goes on Angela's radar to register you) or "Not for me" (off your list
    // for good). No coverage-gap/conflict logic — that stays in Angela's
    // Planner. Decide down to zero, then "you're all caught up".
    function renderPlanAhead() {{
      var host = document.getElementById('ops-planahead');
      if (!host) return;
      var meFirst = (getCollabName() || '').trim().toLowerCase().split(/\\s+/)[0];
      var personalized = !!((window.AB_PERSONAS || {{}})[meFirst]);
      var meName = getCollabName() || '';
      var support = isSupportPerson(meName);
      var intro = '<p class="queue-intro myev-intro"><strong>Plan Ahead:</strong> ' +
        (support ? 'Events around where the team&#39;s already headed, plus others worth a look. '
                 : (personalized ? 'Events around the trips you&#39;re already taking, plus more like the ones you flag. ' : 'Events worth a look. ')) +
        'Flag the ones to go to (Angela registers you) and skip the rest.' +
        // Skipping teaches this page what you don't want (organizer, topic,
        // lesser-known city). Say so plainly, and always offer the undo — a
        // learned pattern you can't clear would quietly shrink your own fits.
        (function () {{
          var v = _vetoProfile();
          if ((v.n || 0) < 2) return '';
          return ' <span class="veto-note">Your skips are narrowing what shows here and in <em>My fits</em>. ' +
                 '<button type="button" class="veto-reset" data-veto-reset>Reset what I&#39;ve taught it</button></span>';
        }})() + '</p>';
      // Person label helpers — trips + interest recs go team-wide for support.
      // Label by the identifier the team actually uses (the persona key: Thor,
      // Jerome, Verma, Carlos, Joe, Jim), which is how attendees are stored.
      function _whoLabel(w) {{ return escapeHtml(w ? w.charAt(0).toUpperCase() + w.slice(1) : ''); }}
      function _whoList(arr) {{ return (arr || []).map(_whoLabel).join(' &amp; '); }}
      // One reusable suggestion row (name · date · loc + interested/skip).
      //
      // `forWho` = the teammate this row is being suggested FOR. Angela and
      // Hurley run the tracker but never attend, so "I'm interested" / "Not for
      // me" was meaningless in their view — the row belongs to Thor, Verma, etc.
      // For them the buttons name that person ("Thor's interested" / "Not for
      // him"); for everyone else the row is their own and the wording stays
      // first-person. See [[sales-support-non-attendees]].
      function sugRow(it, extraHtml, forWho) {{
        var loc = it.location || '';
        var who = (support && forWho) ? String(forWho) : '';
        var whoCap = who ? who.charAt(0).toUpperCase() + who.slice(1) : '';
        // Name rather than a pronoun ("Not for Thor", not "Not for him") — it
        // reads the same and doesn't guess anyone's pronouns.
        var yes = who ? (escapeHtml(whoCap) + '&#39;s interested') : 'I&#39;m interested';
        var no  = who ? ('Not for ' + escapeHtml(whoCap)) : 'Not for me';
        var noTitle = who ? ('Take this off ' + escapeHtml(whoCap) + '&#39;s list (and out of your Plan Ahead)')
                          : 'Take this off your list';
        return '<div class="queue-row sug-row"><div class="queue-main">' +
            '<button class="queue-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
            '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' \\u00b7 ' + escapeHtml(loc) : '') + '</p>' +
            (extraHtml || '') +
          '</div><div class="queue-actions sug-actions">' +
            '<button type="button" class="q-btn primary" data-pa-flag="1" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '"' +
              (who ? ' data-pa-for="' + escapeHtml(who) + '"' : '') + '>' + yes + '</button>' +
            '<button type="button" class="q-btn sug-skip" data-pa-skip="1" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '"' +
              (who ? ' data-pa-for="' + escapeHtml(who) + '"' : '') + ' title="' + noTitle + '">' + no + '</button>' +
          '</div></div>';
      }}
      // Small "hide this whole block from Plan Ahead" ✕ for a trip cluster / radar
      // group, keyed by its anchor event.
      function _planHideX(ev) {{
        return '<button type="button" class="plan-hide-x" data-plan-hide-kind="' + ev.kind +
          '" data-plan-hide-key="' + escapeHtml(String(ev.key)) + '" title="Hide this from Plan Ahead" aria-label="Hide from Plan Ahead">&times;</button>';
      }}
      function anchorHead(lead, ev, extraCls) {{
        var loc = ev.location || ev.city || '';
        return '<div class="queue-section trip-cluster' + (extraCls ? ' ' + extraCls : '') + '">' + _planHideX(ev) + '<p class="trip-anchor">' + lead +
          ' <button class="trip-anchor-name" data-ref-kind="' + ev.kind + '" data-ref-key="' + escapeHtml(String(ev.key)) + '">' + escapeHtml(ev.name) + '</button>' +
          '<span class="trip-anchor-meta">' + escapeHtml(ev.date_str || '') + (loc ? ' \\u00b7 ' + escapeHtml(loc) : '') + '</span></p>';
      }}
      var shownKeys = {{}};   // surfaced in trips / interest recs -> keep out of the monthly list
      // ── Batch your trips (geographic) ─────────────────────────────────
      var clusters = _tripClusters().filter(function (cl) {{ return !_planHidden(cl.anchor.kind, cl.anchor.key); }});
      var tripHtml = '';
      // Map an event's YYYYMMDD sort key to a "Q# YYYY" string, to seed the
      // area search's quarter when there's nothing to batch onto a trip.
      function _quarterOfSort(sort) {{
        var s = String(sort || '');
        if (s.length < 6) return '';
        var y = s.slice(0, 4), mo = parseInt(s.slice(4, 6), 10);
        if (!/^[0-9]{{4}}$/.test(y) || !mo) return '';
        return 'Q' + (Math.floor((mo - 1) / 3) + 1) + ' ' + y;
      }}
      // YYYYMMDD sort key -> ISO "YYYY-MM-DD", to seed the area search's exact
      // date window (so it hunts around the TRIP'S DATES, not the whole quarter).
      function _isoFromSort(sort) {{
        var s = String(sort || '');
        if (s.length < 8) return '';
        return s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8);
      }}
      if (clusters.length) {{
        tripHtml += '<div class="queue-sec-head"><span class="queue-sec-title">&#129517; Batch your trips</span><span class="queue-sec-count">' + clusters.length + '</span></div>' +
          '<p class="queue-meta" style="margin:-4px 0 14px;">' +
          (support ? 'Where the team&#39;s already headed &mdash; and what else is on within a few days, same or nearby city.'
                   : 'You&#39;re already going to these &mdash; here&#39;s what else is on within a few days, in the same or a nearby city.') + '</p>';
        // Render one anchor + its nearby events. The anchor reads
        // "GDN (attending)" / "Web Summit Lisbon (speaking)" — event name first,
        // role in parentheses (works the same under a person header for support).
        function renderCluster(cl) {{
          var ev = cl.anchor, loc = ev.location || ev.city || '';
          var r = (cl.role === 'speaking at') ? 'speaking' : cl.role;
          tripHtml += '<div class="queue-section trip-cluster">' + _planHideX(ev) + '<p class="trip-anchor">' +
            '<button class="trip-anchor-name" data-ref-kind="' + ev.kind + '" data-ref-key="' + escapeHtml(String(ev.key)) + '">' + escapeHtml(ev.name) + '</button>' +
            ' <span class="trip-anchor-role">(' + escapeHtml(r) + ')</span>' +
            '<span class="trip-anchor-meta">' + escapeHtml(ev.date_str || '') + (loc ? ' \\u00b7 ' + escapeHtml(loc) : '') + '</span></p>';
          cl.near.forEach(function (n) {{
            shownKeys[n.it.kind + ':' + n.it.key] = 1;
            var prox = (n.gap === 0 ? 'overlaps' : ('~' + n.gap + ' day' + (n.gap === 1 ? '' : 's') + ' apart')) +
              ' \\u00b7 ' + (n.km < 25 ? 'same city' : ('~' + Math.round(n.km) + ' km away'));
            tripHtml += sugRow(n.it, '<p class="trip-prox">' + prox + '</p>', cl.who);
          }});
          // Nothing else tracked near this trip. Rather than a dead end, we
          // PROACTIVELY hunt for nearby events (≤5) via a one-time, cached AI
          // area search — no click needed. The .trip-auto placeholder is filled
          // by _runAutoNear after render (see the wiring below).
          if (!cl.near.length) {{
            var _city = escapeHtml(String(loc).split(',')[0].trim());
            if (ev.is_private) {{
              // Private / invite-only anchor (GBS, GDN): no public web footprint,
              // so an AI area search is a dead end — never run it.
              if (loc) tripHtml += '<p class="trip-nonear-note">Nothing else tracked near ' + _city + ' around then.</p>';
            }} else if (loc) {{
              var _pStart = ev.start_date || _isoFromSort(ev.sort);
              var _pEnd = ev.end_date || ev.start_date || _isoFromSort(_endSortOf(ev));
              tripHtml += '<div class="trip-auto"' +
                ' data-auto-kind="' + escapeHtml(String(ev.kind)) + '"' +
                ' data-auto-key="' + escapeHtml(String(ev.key)) + '"' +
                ' data-auto-near="' + escapeHtml(loc) + '"' +
                ' data-auto-quarter="' + escapeHtml(_quarterOfSort(ev.sort)) + '"' +
                ' data-auto-start="' + escapeHtml(_pStart) + '"' +
                ' data-auto-end="' + escapeHtml(_pEnd) + '"' +
                ' data-auto-exclude="' + escapeHtml(ev.name || '') + '">' +
                '<p class="trip-nonear-note">\\u2026</p></div>';
            }} else {{
              tripHtml += '<p class="trip-nonear-note">Add a city to this event (Edit \\u2192 Location) to find nearby events to batch.</p>';
            }}
          }}
          tripHtml += '</div>';
        }}
        if (support) {{
          // Angela plans for everyone: group the trips BY PERSON, then by date
          // within each person, so it reads "here's where Thor is going, then
          // Verma, …". Persons ordered by their soonest trip.
          var byWho = {{}}, whoOrder = [];
          clusters.forEach(function (cl) {{
            if (!byWho[cl.who]) {{ byWho[cl.who] = []; whoOrder.push(cl.who); }}
            byWho[cl.who].push(cl);
          }});
          whoOrder.sort(function (a, b) {{ return (byWho[a][0].anchor.sort || 0) - (byWho[b][0].anchor.sort || 0); }});
          whoOrder.forEach(function (who) {{
            var list = byWho[who].slice().sort(function (a, b) {{ return (a.anchor.sort || 0) - (b.anchor.sort || 0); }});
            tripHtml += '<div class="trip-person"><h4 class="trip-person-name">' + _whoLabel(who) +
              '<span class="trip-person-count">' + list.length + ' trip' + (list.length === 1 ? '' : 's') + '</span></h4>';
            list.forEach(function (cl) {{ renderCluster(cl); }});
            tripHtml += '</div>';
          }});
        }} else {{
          clusters.forEach(function (cl) {{ renderCluster(cl); }});
        }}
      }}
      // ── Because you're interested in X (content similarity) ───────────
      var recs = _contentRecs().filter(function (rc) {{ return !_planHidden(rc.anchor.kind, rc.anchor.key); }});
      var recHtml = '';
      if (recs.length) {{
        recHtml += '<div class="queue-sec-head"><span class="queue-sec-title">&#128225; Event Radar</span><span class="queue-sec-count">' + recs.length + '</span></div>' +
          '<p class="queue-meta" style="margin:-4px 0 14px;">' +
          (support ? 'More like what teammates flagged &mdash; same industry, audience and topics.'
                   : 'More like the events you flagged &mdash; same industry, audience and topics.') + '</p>';
        recs.forEach(function (rc) {{
          var lead = support
            ? (_whoList(rc.who) + ' ' + (rc.who.length > 1 ? 'are' : 'is') + ' interested in')
            : 'Because you&#39;re interested in';
          recHtml += anchorHead(lead, rc.anchor, 'rec-cluster');
          rc.recs.forEach(function (p) {{
            shownKeys[p.it.kind + ':' + p.it.key] = 1;
            // Name the person when the recommendation traces to exactly one of
            // them; with several interested it stays generic.
            recHtml += sugRow(p.it, '', (rc.who && rc.who.length === 1) ? rc.who[0] : '');
          }});
          recHtml += '</div>';
        }});
      }}

      // 2–4 month suggestions (excluding anything already surfaced above).
      var sug = _suggestionsFor().filter(function (x) {{ return !shownKeys[x.it.kind + ':' + x.it.key]; }});
      if (!sug.length && !tripHtml && !recHtml) {{
        // Empty because you cleared it vs. because nothing fit yet — say which.
        var anySkipped = Object.keys(_sugSkips()).length > 0;
        host.innerHTML = intro + '<div class="queue-empty">' +
          (anySkipped
            ? '&#10003; You&#39;re all caught up &mdash; you&#39;ve decided on everything in the 2&ndash;4 month window. New events will show up here as they come in.'
            : 'Nothing in the 2&ndash;4 month window fits yet &mdash; check back as new events come in.') +
          '</div>';
        return;
      }}
      // Group by MONTH, not region — chronological reads better for "what's
      // coming up to decide on", and the region label was redundant with the
      // city on every row anyway.
      var groups = {{}}, order = [];
      sug.forEach(function (x) {{
        var m = _sugMonth(x.it.sort);
        if (!groups[m.key]) {{ groups[m.key] = {{ label: m.label, sort: m.sort, items: [] }}; order.push(m.key); }}
        groups[m.key].items.push(x);
      }});
      order.sort(function (a, b) {{ return groups[a].sort - groups[b].sort; }});
      var html = intro + tripHtml + recHtml;
      // The month-by-month suggestion list that follows Event Radar is off for
      // Thor (Hurley 2026-07-29). He gets the two curated blocks — trips he's
      // already taking, and events like the ones the team flagged — and not the
      // long tail underneath them, which is browsing, not a decision queue.
      if (!_PLAN_SUGGESTIONS_OFF[(getCollabName() || '').trim().toLowerCase().split(/\\s+/)[0]]) {{
        order.forEach(function (mkey) {{
          var g = groups[mkey];
          var list = g.items.slice().sort(function (a, b) {{ return a.it.sort - b.it.sort; }});
          html += '<div class="queue-section"><div class="queue-sec-head"><span class="queue-sec-title">' + escapeHtml(g.label) + '</span><span class="queue-sec-count">' + list.length + '</span></div>';
          list.forEach(function (x) {{ html += sugRow(x.it, ''); }});
          html += '</div>';
        }});
      }}
      host.innerHTML = html;
      // ONE delegated listener on the host instead of a listener per button.
      // Plan Ahead rewrites parts of itself after render (the AI area-search
      // fills each .trip-auto placeholder), and any per-element listener on
      // replaced markup dies with it — leaving rows that look clickable and do
      // nothing. Delegation survives every re-render, and closest() means a
      // click anywhere on the row's button still resolves.
      if (!host.dataset.refWired) {{
        host.dataset.refWired = '1';
        host.addEventListener('click', function (e) {{
          var el = e.target && e.target.closest ? e.target.closest('[data-ref-kind]') : null;
          if (!el || !host.contains(el)) return;
          opsOpenRef(el.getAttribute('data-ref-kind'), el.getAttribute('data-ref-key'));
        }});
      }}
      // Solo trips with nothing tracked nearby: proactively fill each with up to
      // 5 AI-found events (one metered search per trip, cached 10 days — never
      // re-fired on a plain re-render). No click needed. Cap NEW searches per
      // render (cached ones are free) so a big team can't burst the AI budget.
      _autoBudget = 5;
      host.querySelectorAll('.trip-auto').forEach(function (c) {{
        _runAutoNear({{
          anchorKind: c.getAttribute('data-auto-kind'),
          anchorKey:  c.getAttribute('data-auto-key'),
          loc:        c.getAttribute('data-auto-near'),
          quarter:    c.getAttribute('data-auto-quarter'),
          dateFrom:   c.getAttribute('data-auto-start'),
          dateTo:     c.getAttribute('data-auto-end'),
          exclude:    c.getAttribute('data-auto-exclude')
        }});
      }});
      host.querySelectorAll('[data-pa-flag]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          var kind = btn.getAttribute('data-k'), key = btn.getAttribute('data-key');
          var it = opsAllItems().filter(function (x) {{ return x.kind === kind && String(x.key) === key; }})[0];
          if (!it) return;
          btn.setAttribute('aria-busy', 'true');
          // Angela/Hurley flag ON BEHALF OF the teammate the row was suggested
          // for — toggleMyInterest would have registered THEM, and they don't
          // attend. Add that person to the shared interested list instead
          // (same write the Planner's "+ Flag for X" does).
          var forWho = btn.getAttribute('data-pa-for');
          if (forWho) {{
            var target = OPS_ROSTER.filter(function (n) {{ return n.toLowerCase() === String(forWho).toLowerCase(); }})[0];
            if (target) {{
              var list = (it.interested || []).slice();
              if (list.indexOf(target) === -1) list.push(target);
              list = OPS_ROSTER.filter(function (x) {{ return list.indexOf(x) !== -1; }});
              opsQuickWrite(kind, key, {{ interested: list }});
              return;
            }}
          }}
          toggleMyInterest(kind, it.key, it.interested, it.startObj && it.startObj.attend_verdict);
        }});
      }});
      // Undo the learning (not the individual skips — those stay decided).
      host.querySelectorAll('[data-veto-reset]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          try {{ localStorage.removeItem(_vetoKey()); }} catch (e) {{}}
          renderPlanAhead();
          if (window.opsRefresh) window.opsRefresh();   // My fits recomputes
        }});
      }});
      host.querySelectorAll('[data-pa-skip]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          _sugSkip(btn.getAttribute('data-k'), btn.getAttribute('data-key'));
          var row = btn.closest('.queue-row');
          if (row) row.style.display = 'none';   // instant feedback
          renderPlanAhead();                     // re-render: counts + empty state update
        }});
      }});
      // ✕ on a trip cluster / radar group → hide that whole block from Plan Ahead.
      host.querySelectorAll('[data-plan-hide-kind]').forEach(function (btn) {{
        btn.addEventListener('click', function (e) {{
          e.stopPropagation();
          _planHide(btn.getAttribute('data-plan-hide-kind'), btn.getAttribute('data-plan-hide-key'));
          renderPlanAhead();
        }});
      }});
    }}

    // ════════════════════════════════════════════════════════════════
    // My Profile — per-person bio, speaking topics, past talks, files,
    // and targeting notes. Editable for whoever's signed in; the rest of
    // the team's text shows read-only below, so we can see where each
    // person has spoken and what they want to target (a targeting aid —
    // no per-event reasoning lives here). Text lives in team_profiles;
    // files live in the private 'profiles' storage bucket. Both degrade
    // to a one-time "run setup" note if they aren't there yet.
    // ════════════════════════════════════════════════════════════════
    var PROFILE_FIELDS = [
      {{ k: 'notes',      label: 'Targeting notes', hint: 'events you want',            ph: 'Types of events you want to be at, specific event names, regions — anything on your mind.' }},
      {{ k: 'bio',        label: 'Short bio',       hint: 'a couple of sentences',      ph: 'Two or three sentences an organizer could drop straight into an agenda.' }},
      {{ k: 'topics',     label: 'Talks & topics',  hint: 'what you speak on',          ph: 'Talk titles, themes, signature angles — one per line.' }}
    ];
    // Speaking materials, organized by what an organizer actually asks for —
    // each is its own upload slot (files live under <person>/<slot>/ in the
    // profiles bucket). This is the point of the profile: a ready-to-send kit.
    var PROFILE_MATERIALS = [
      {{ k: 'bios',            label: 'Bio & one-pagers',  hint: 'formal bio doc, speaker one-pager, leave-behinds' }},
      {{ k: 'speaking_topics', label: 'Speaking Topics',   hint: 'your talk topics / abstracts one-sheet organizers can pick from' }},
      {{ k: 'decks',           label: 'Slides & decks',    hint: 'your talk decks — PDF / PPTX / Keynote' }},
      {{ k: 'other',           label: 'Other materials',   hint: 'press, testimonials, video links saved as a file — anything else' }},
      {{ k: 'headshot',        label: 'Headshot',          hint: 'a professional photo organizers can use' }}
    ];
    function _profileKey(name) {{ return (name || '').trim().toLowerCase().split(/\\s+/)[0]; }}
    function _profileDisplay(row, key) {{
      if (row && row.display_name) return row.display_name;
      var P = (window.AB_PERSONAS || {{}})[key];
      if (P && P.name) return P.name;
      return key ? key.charAt(0).toUpperCase() + key.slice(1) : '';
    }}
    function _profileRole(key) {{ var P = (window.AB_PERSONAS || {{}})[key]; return (P && P.role) || ''; }}
    function _fmtBytes(n) {{
      n = Number(n) || 0;
      if (n < 1024) return n + ' B';
      if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
      return (n / (1024 * 1024)).toFixed(1) + ' MB';
    }}
    // ── Profile materials: preview (not download) + a download icon + links ──
    var PROFILE_DL_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>';
    // Links (Google Drive/Doc etc.) are stored as tiny ".weblink" marker files
    // whose NAME is a base64url of {{t:title, u:url}} (so listing needs no extra
    // fetch). Legacy markers hold just the raw URL.
    function _b64urlEnc(s) {{ try {{ return btoa(unescape(encodeURIComponent(s))).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, ''); }} catch (e) {{ return ''; }} }}
    function _b64urlDec(s) {{ try {{ s = String(s).replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; return decodeURIComponent(escape(atob(s))); }} catch (e) {{ return ''; }} }}
    function _isWeblink(name) {{ return /\\.weblink$/i.test(name || ''); }}
    function _weblinkInfo(name) {{
      var dec = _b64urlDec(String(name).replace(/\\.weblink$/i, ''));
      try {{ var o = JSON.parse(dec); if (o && o.u) return {{ url: String(o.u), title: String(o.t || '') }}; }} catch (e) {{}}
      return {{ url: dec, title: '' }};   // legacy: the name was the raw URL
    }}
    function _isOfficeDoc(name) {{ return /\\.(docx?|pptx?|xlsx?)$/i.test(name || ''); }}
    // PREVIEW a stored file in the right viewer — never a forced download. Office
    // docs render via Microsoft's online viewer; PDFs / images / text open
    // directly (the browser previews those). This is the fix for "clicking it
    // just downloads the .docx".
    function _profilePreview(fullPath, name) {{
      sb.storage.from('profiles').createSignedUrl(fullPath, 600).then(function (r) {{
        var url = r && r.data && r.data.signedUrl;
        if (!url) {{ status('Could not open that file.', 'error'); return; }}
        var dest = _isOfficeDoc(name)
          ? ('https://view.officeapps.live.com/op/view.aspx?src=' + encodeURIComponent(url))
          : url;
        window.open(dest, '_blank', 'noopener');
      }});
    }}
    // DOWNLOAD on demand (Content-Disposition: attachment) — behind its own icon.
    function _profileDownload(fullPath, name) {{
      sb.storage.from('profiles').createSignedUrl(fullPath, 120, {{ download: name || true }}).then(function (r) {{
        var url = r && r.data && r.data.signedUrl;
        if (url) window.open(url, '_blank', 'noopener'); else status('Could not download that file.', 'error');
      }});
    }}
    // One row for a file OR a link: name = preview, a download icon, and an
    // optional delete (own profile only). Links open directly (that IS a preview).
    function _matFileRowHtml(fullPath, name, size, canDelete) {{
      var del = canDelete
        ? '<button type="button" class="profile-file-del" data-delpath="' + escapeHtml(fullPath) + '" data-delname="' + escapeHtml(name) + '" aria-label="Delete ' + escapeHtml(name) + '" title="Delete"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>'
        : '';
      if (_isWeblink(name)) {{
        var info = _weblinkInfo(name);
        var url = info.url;
        var lbl = info.title || (function () {{
          if (/docs\\.google|drive\\.google/i.test(url)) return 'Google Doc';
          try {{ return new URL(url).host.replace(/^www\\./, ''); }} catch (e) {{ return 'Link'; }}
        }})();
        // Rename the link's title after the fact (own profile only).
        var ren = canDelete
          ? '<button type="button" class="profile-file-ren" data-renpath="' + escapeHtml(fullPath) + '" data-renurl="' + escapeHtml(url) + '" data-rentitle="' + escapeHtml(info.title) + '" aria-label="Rename link" title="Rename"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>'
          : '';
        return '<div class="profile-file profile-file--link">' +
          '<a class="profile-file-name" href="' + escapeHtml(url) + '" target="_blank" rel="noopener" title="' + escapeHtml(url) + '">\\ud83d\\udd17 ' + escapeHtml(lbl) + ' \\u2197</a>' + ren + del + '</div>';
      }}
      return '<div class="profile-file">' +
        '<button type="button" class="profile-file-name profile-file-open" data-openpath="' + escapeHtml(fullPath) + '" data-openname="' + escapeHtml(name) + '" title="Preview ' + escapeHtml(name) + '">' + escapeHtml(name) + '</button>' +
        (size ? '<span class="profile-file-size">' + escapeHtml(size) + '</span>' : '') +
        '<button type="button" class="profile-file-dl" data-dlpath="' + escapeHtml(fullPath) + '" data-dlname="' + escapeHtml(name) + '" aria-label="Download ' + escapeHtml(name) + '" title="Download">' + PROFILE_DL_ICON + '</button>' +
        del + '</div>';
    }}
    // Delegated preview / download / rename / delete for a file container (added once).
    function _wireProfileFileContainer($c, onDelete, onRename) {{
      if (!$c || $c.dataset.fcWired) return;
      $c.dataset.fcWired = '1';
      $c.addEventListener('click', function (e) {{
        var t = e.target; if (!t || !t.closest) return;
        var op = t.closest('[data-openpath]'); if (op) {{ e.preventDefault(); _profilePreview(op.getAttribute('data-openpath'), op.getAttribute('data-openname')); return; }}
        var dl = t.closest('[data-dlpath]'); if (dl) {{ e.preventDefault(); _profileDownload(dl.getAttribute('data-dlpath'), dl.getAttribute('data-dlname')); return; }}
        var re = t.closest('[data-renpath]'); if (re && onRename) {{ e.preventDefault(); onRename(re.getAttribute('data-renpath'), re.getAttribute('data-renurl'), re.getAttribute('data-rentitle')); return; }}
        var de = t.closest('[data-delpath]'); if (de && onDelete) {{ e.preventDefault(); onDelete(de.getAttribute('data-delpath'), de.getAttribute('data-delname')); return; }}
      }});
    }}
    function renderMyProfile() {{
      var host = document.getElementById('ops-myprofile');
      if (!host) return;
      var meName = getCollabName();
      if (!meName) {{
        host.innerHTML = '<div class="profile-wrap"><p class="queue-intro myev-intro"><strong>Profile.</strong> Set your name (top-right avatar &rarr; Someone else) to build your profile or see the team&#39;s.</p></div>';
        return;
      }}
      var meKey = _profileKey(meName);
      host.innerHTML = '<div class="profile-wrap"><p class="queue-intro myev-intro">Loading profiles&hellip;</p></div>';
      // Everyone's text (team_profiles) + everyone who has files (storage
      // folders), in parallel, so the directory is complete. Both convert a
      // rejection to a safe empty value so one failing doesn't blank the view.
      Promise.all([
        sb.from('team_profiles').select('*').then(function (r) {{ return r; }}, function () {{ return {{ error: true, data: [] }}; }}),
        sb.storage.from('profiles').list('', {{ limit: 200 }}).then(function (r) {{ return r; }}, function () {{ return {{ data: [] }}; }})
      ]).then(function (res) {{
        var rowsResp = res[0], foldResp = res[1];
        var dbMissing = !!(rowsResp && rowsResp.error);
        var rows = (rowsResp && rowsResp.data) || [];
        var byKey = {{}};
        rows.forEach(function (r) {{ byKey[r.person] = r; }});
        var folders = ((foldResp && foldResp.data) || []).map(function (f) {{ return f.name; }})
          .filter(function (n) {{ return n && n !== '.emptyFolderPlaceholder'; }});
        _paintMyProfile(host, meKey, meName, byKey, rows, folders, dbMissing);
      }});
    }}
    // One read-only person card for the directory: name + role, their written
    // fields, and a Materials slot filled in async by _loadTeammateFiles.
    // Each teammate's LinkedIn — the name links to it, and the full URL shows
    // right below (so Angela can copy/paste it into an organizer email).
    var PROFILE_LINKEDIN = {{
      thor:   'https://www.linkedin.com/in/thorernstsson/',
      verma:  'https://www.linkedin.com/in/anuraagsverma/',
      carlos: 'https://www.linkedin.com/in/carlos-l-chacon-almeida/?locale=en',
      jerome: 'https://www.linkedin.com/in/jeromewouters/',
      joe:    'https://www.linkedin.com/in/joelalley/',
      scott:  'https://www.linkedin.com/in/slpollack/',
      jim:    'https://www.linkedin.com/in/jimchungprofile/'
    }};
    function _directoryCardHtml(key, row, filesId, canEdit) {{
      var d = _profileDisplay(row, key);
      var role = _profileRole(key);
      var li = PROFILE_LINKEDIN[String(key).toLowerCase()] || '';
      var nameEl = li
        ? '<a class="profile-tm-name" href="' + escapeHtml(li) + '" target="_blank" rel="noopener" title="Open ' + escapeHtml(d) + ' on LinkedIn">' + escapeHtml(d) + '</a>'
        : '<span class="profile-tm-name">' + escapeHtml(d) + '</span>';
      var h = '<div class="profile-teammate"><div class="profile-tm-head">' +
        '<span class="profile-avatar">' + escapeHtml((d || '?').charAt(0).toUpperCase()) + '</span>' +
        nameEl +
        (role ? '<span class="profile-tm-role">' + escapeHtml(role) + '</span>' : '') + '</div>' +
        (li ? '<a class="profile-tm-linkedin" href="' + escapeHtml(li) + '" target="_blank" rel="noopener">' + escapeHtml(li) + '</a>' : '');
      if (row) {{
        PROFILE_FIELDS.forEach(function (f) {{
          if (!row[f.k]) return;
          h += '<div class="profile-tm-field"><div class="k">' + escapeHtml(f.label) + '</div><div class="v">' + escapeHtml(row[f.k]) + '</div></div>';
        }});
      }}
      // Angela (canEdit) gets the SAME editable per-slot UI she has on her own —
      // upload / add-link / delete for this teammate. Everyone else is read-only.
      if (canEdit) {{
        h += '<div class="profile-tm-field"><div class="k">Materials</div>' +
          PROFILE_MATERIALS.map(function (m) {{ return _materialSlotHtml(key, m); }}).join('') + '</div>';
      }} else {{
        h += '<div class="profile-tm-field"><div class="k">Materials</div><div class="profile-tm-files" id="' + filesId + '"><p class="profile-file-empty">Loading&hellip;</p></div></div>';
      }}
      return h + '</div>';
    }}
    // Read-only materials for a teammate — grouped by slot, download only.
    // Lists each material category (<person>/<cat>/…) and appends the slots
    // that have files; clicks are handled by delegation so async appends work.
    function _loadTeammateFiles(personKey, containerId) {{
      var $c = document.getElementById(containerId);
      if (!$c) return;
      $c.innerHTML = '';
      _wireProfileFileContainer($c, null);   // preview + download, no delete (read-only)
      var pending = PROFILE_MATERIALS.length, anyShown = false;
      PROFILE_MATERIALS.forEach(function (m) {{
        sb.storage.from('profiles').list(personKey + '/' + m.k, {{ limit: 50 }}).then(function (resp) {{
          var items = ((resp && resp.data) || []).filter(function (f) {{ return f.name && f.name !== '.emptyFolderPlaceholder'; }});
          if (items.length) {{
            anyShown = true;
            var h = '<div class="tm-mat-group"><div class="tm-mat-label">' + escapeHtml(m.label) + '</div>' +
              items.map(function (f) {{
                var size = (f.metadata && f.metadata.size) ? _fmtBytes(f.metadata.size) : '';
                return _matFileRowHtml(personKey + '/' + m.k + '/' + f.name, f.name, size, false);
              }}).join('') + '</div>';
            $c.insertAdjacentHTML('beforeend', h);
          }}
          if (--pending === 0 && !anyShown) $c.innerHTML = '<p class="profile-file-empty">&mdash;</p>';
        }});
      }});
    }}
    function _paintMyProfile(host, meKey, meName, byKey, allRows, folders, dbMissing) {{
      var support = isSupportPerson(meName);
      var myRow = byKey[meKey] || null;
      // Everyone who has added anything: a profile row with text, or files.
      var keySet = {{}};
      (allRows || []).forEach(function (r) {{
        if (r.person && (r.bio || r.topics || r.past_talks || r.notes)) keySet[r.person] = 1;
      }});
      (folders || []).forEach(function (k) {{ keySet[k] = 1; }});
      var dirKeys = Object.keys(keySet).filter(function (k) {{ return support || k !== meKey; }});
      dirKeys.sort(function (a, b) {{ return _profileDisplay(byKey[a], a).localeCompare(_profileDisplay(byKey[b], b)); }});

      var html = '<div class="profile-wrap">';
      if (dbMissing) {{
        html += '<div class="profile-setup-note"><strong>One-time setup needed.</strong> The profile store isn&#39;t in the database yet, so nothing here will save or show. Run the <code>team_profiles</code> setup once, then reload.</div>';
      }}
      // Support (Angela/Hurley) coordinate — they don't speak, so they get the
      // team directory straight away, not their own speaker card.
      if (!support) {{
        var disp = _profileDisplay(myRow, meKey) || meName;
        var initial = escapeHtml((disp || '?').charAt(0).toUpperCase());
        var role = _profileRole(meKey);
        html += '<div class="profile-card">' +
          '<div class="profile-card-head">' +
            '<span class="profile-avatar profile-avatar-lg">' + initial + '</span>' +
            '<span class="profile-id"><span class="profile-who">' + escapeHtml(disp) + '</span>' +
              (role ? '<span class="profile-role">' + escapeHtml(role) + '</span>' : '') + '</span>' +
          '</div>';
        // ── Speaking materials — the point of the profile: a ready-to-send
        // kit, organized by what organizers ask for. Each slot is its own
        // upload + list.
        html += '<div class="profile-section-head">Speaking materials</div>' +
          '<p class="profile-section-sub">Help Angela organize your speaking materials.</p>';
        PROFILE_MATERIALS.forEach(function (m) {{ html += _materialSlotHtml(meKey, m); }});
        // ── Written profile — bio (saved field + hover-edit) and notes/topics
        // (add/edit/delete lists). Each saves immediately; filled by _pfRenderAbout.
        _pfWho = {{ key: meKey, name: meName }};
        _pfMy = {{ bio: (myRow && myRow.bio) || '', notes: (myRow && myRow.notes) || '', topics: (myRow && myRow.topics) || '' }};
        _pfEdit = {{ field: null, index: -1 }};
        html += '<div class="profile-section-head">About you <span class="profile-section-opt">optional \\u00b7 saves as you go</span></div>';
        html += '<div id="pf-about"></div>';
        html += '</div>';   // end .profile-card
      }}
      // The per-person directory — everyone's profile + materials, by person.
      var dirTitle = support ? 'Team profiles' : 'The rest of the team';
      var dirIntro = support
        ? 'Everyone&#39;s bio, topics, targeting notes, and materials &mdash; by person. Updates as each person edits their profile.'
        : 'Read-only &mdash; where each person has spoken, what they want to target, and their materials.';
      html += '<div class="queue-sec-head"' + (support ? '' : ' style="margin-top:8px;"') + '><span class="queue-sec-title">' + dirTitle + '</span><span class="queue-sec-count">' + dirKeys.length + '</span></div>' +
        '<p class="queue-meta" style="margin:-4px 0 14px;">' + dirIntro + '</p>';
      if (!dirKeys.length) {{
        html += '<div class="queue-empty">No one&#39;s added a profile yet &mdash; when someone fills in their bio, topics, or uploads a file, it shows up here by person.</div>';
      }} else {{
        dirKeys.forEach(function (k, i) {{ html += _directoryCardHtml(k, byKey[k] || null, 'tmfiles-' + i, support); }});
      }}
      html += '</div>';   // end .profile-wrap
      host.innerHTML = html;
      // Upload / Add-link buttons carry "<key>|<cat>" — one wiring covers the own
      // card AND (for Angela) every editable teammate slot in the directory.
      host.querySelectorAll('[data-mat-upload]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{ var p = btn.getAttribute('data-mat-upload').split('|'); _uploadProfileFile(p[0], p[1]); }});
      }});
      host.querySelectorAll('[data-mat-link]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{ var p = btn.getAttribute('data-mat-link').split('|'); _addProfileLink(p[0], p[1]); }});
      }});
      if (!support) {{
        var $about = document.getElementById('pf-about');
        if ($about) {{ _pfWireAbout($about); _pfRenderAbout(); }}
        PROFILE_MATERIALS.forEach(function (m) {{ _loadProfileFiles(meKey, m.k, dbMissing); }});
      }}
      // Directory materials: Angela (support) gets editable slots (load each);
      // everyone else gets the read-only grouped list.
      dirKeys.forEach(function (k, i) {{
        if (support) {{ PROFILE_MATERIALS.forEach(function (m) {{ _loadProfileFiles(k, m.k, dbMissing); }}); }}
        else {{ _loadTeammateFiles(k, 'tmfiles-' + i); }}
      }});
    }}
    function _saveMyProfile(meKey, meName) {{
      var row = {{ person: meKey, display_name: meName, updated_by: meName, updated_at: new Date().toISOString() }};
      PROFILE_FIELDS.forEach(function (f) {{ var el = document.getElementById('pf-' + f.k); row[f.k] = el ? el.value : ''; }});
      var $save = document.getElementById('pf-save');
      if ($save) $save.setAttribute('aria-busy', 'true');
      sb.from('team_profiles').upsert(row, {{ onConflict: 'person' }}).then(function (resp) {{
        if ($save) $save.removeAttribute('aria-busy');
        if (resp && resp.error) {{
          status('Could not save your profile: ' + resp.error.message + (/team_profiles|column|relation|does not exist/i.test(resp.error.message) ? ' \\u2014 the one-time team_profiles setup may still be pending.' : ''), 'error');
          return;
        }}
        var $ok = document.getElementById('pf-saved');
        if ($ok) {{ $ok.hidden = false; setTimeout(function () {{ if ($ok) $ok.hidden = true; }}, 2500); }}
        flashOk('Profile saved');
        // Refresh the taste cache so the new profile text personalizes
        // suggestions right away (not just on next load).
        _loadProfileTaste();
      }});
    }}
    // ── About-you (own profile): a saved bio with a hover-pencil to edit, and
    // Targeting notes / Talks & topics as add/edit/delete LISTS. Lists are stored
    // newline-joined in the same team_profiles text columns (no schema change).
    // Every action saves immediately (full-row upsert, so nothing else is lost).
    var PF_PENCIL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
    var PF_TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
    var _pfMy = {{ bio: '', notes: '', topics: '' }};
    var _pfEdit = {{ field: null, index: -1 }};
    var _pfWho = {{ key: '', name: '' }};
    function _pfLines(key) {{ return String(_pfMy[key] || '').split(/\\r?\\n/).map(function (s) {{ return s.trim(); }}).filter(Boolean); }}
    function _pfPersist() {{
      var patch = {{ person: _pfWho.key, display_name: _pfWho.name, updated_by: _pfWho.name, updated_at: new Date().toISOString(),
        bio: _pfMy.bio || '', notes: _pfMy.notes || '', topics: _pfMy.topics || '' }};
      sb.from('team_profiles').upsert(patch, {{ onConflict: 'person' }}).then(function (resp) {{
        if (resp && resp.error) {{ status('Could not save: ' + resp.error.message + (/team_profiles|column|relation|does not exist/i.test(resp.error.message) ? ' \\u2014 the one-time team_profiles setup may still be pending.' : ''), 'error'); return; }}
        flashOk('Saved'); _loadProfileTaste();
      }});
    }}
    function _pfBioHtml() {{
      var head = '<div class="pf-fieldhead">Short bio <span class="hint">\\u00b7 a couple of sentences</span></div>';
      var v = _pfMy.bio || '';
      if (_pfEdit.field === 'bio') {{
        return '<div class="pf-field">' + head +
          '<textarea class="pf-input" id="pf-bio-input" rows="5" data-pf-focus placeholder="Two or three sentences an organizer could drop straight into an agenda.">' + escapeHtml(v) + '</textarea>' +
          '<div class="pf-edit-actions"><button type="button" class="q-btn primary" data-pf="bio-save">Save</button><button type="button" class="q-btn" data-pf="bio-cancel">Cancel</button></div></div>';
      }}
      if (!v) return '<div class="pf-field">' + head + '<button type="button" class="pf-add-btn" data-pf="bio-edit">+ Add a short bio</button></div>';
      return '<div class="pf-field">' + head + '<div class="pf-saved"><div class="pf-saved-text">' + escapeHtml(v) + '</div>' +
        '<button type="button" class="pf-edit" data-pf="bio-edit" title="Edit bio" aria-label="Edit bio">' + PF_PENCIL + '</button></div></div>';
    }}
    function _pfListHtml(key, label, hint, addPh) {{
      var lines = _pfLines(key);
      var head = '<div class="pf-fieldhead">' + escapeHtml(label) + ' <span class="hint">\\u00b7 ' + escapeHtml(hint) + '</span></div>';
      var rows = lines.map(function (line, i) {{
        if (_pfEdit.field === key && _pfEdit.index === i) {{
          return '<div class="pf-item pf-item--edit"><input class="pf-input" data-pf-focus data-key="' + key + '" data-i="' + i + '" value="' + escapeHtml(line) + '">' +
            '<button type="button" class="q-btn primary" data-pf="list-save" data-key="' + key + '" data-i="' + i + '">Save</button>' +
            '<button type="button" class="q-btn" data-pf="list-cancel">Cancel</button></div>';
        }}
        return '<div class="pf-item"><span class="pf-item-text">' + escapeHtml(line) + '</span>' +
          '<button type="button" class="pf-item-btn" data-pf="list-edit" data-key="' + key + '" data-i="' + i + '" title="Edit" aria-label="Edit">' + PF_PENCIL + '</button>' +
          '<button type="button" class="pf-item-btn pf-del" data-pf="list-del" data-key="' + key + '" data-i="' + i + '" title="Delete" aria-label="Delete">' + PF_TRASH + '</button></div>';
      }}).join('');
      var add = '<div class="pf-additem"><input class="pf-input" id="pf-add-' + key + '" data-addkey="' + key + '" placeholder="' + escapeHtml(addPh) + '">' +
        '<button type="button" class="q-btn pf-add" data-pf="list-add" data-key="' + key + '">Add</button></div>';
      return '<div class="pf-field">' + head + rows + add + '</div>';
    }}
    function _pfRenderAbout() {{
      var host = document.getElementById('pf-about'); if (!host) return;
      host.innerHTML = _pfBioHtml() +
        _pfListHtml('notes', 'Targeting notes', 'events you want', 'Add a note \\u2014 an event, region, or type you want') +
        _pfListHtml('topics', 'Talks & topics', 'what you speak on', 'Add a talk title, theme, or signature angle');
      var f = host.querySelector('[data-pf-focus]');
      if (f) {{ f.focus(); try {{ f.selectionStart = f.selectionEnd = f.value.length; }} catch (e) {{}} }}
    }}
    function _pfCommitEdit(key, i, val) {{
      var lines = _pfLines(key); val = (val || '').trim();
      if (val) lines[i] = val; else lines.splice(i, 1);
      _pfMy[key] = lines.join('\\n'); _pfEdit = {{ field: null, index: -1 }}; _pfPersist(); _pfRenderAbout();
    }}
    function _pfCommitAdd(key, val) {{
      val = (val || '').trim(); if (!val) return;
      var lines = _pfLines(key); lines.push(val); _pfMy[key] = lines.join('\\n'); _pfPersist(); _pfRenderAbout();
      var ai = document.getElementById('pf-add-' + key); if (ai) ai.focus();   // ready to add another
    }}
    function _pfWireAbout(host) {{
      if (!host || host.dataset.pfWired) return; host.dataset.pfWired = '1';
      host.addEventListener('click', function (e) {{
        var b = e.target.closest ? e.target.closest('[data-pf]') : null; if (!b) return;
        var act = b.getAttribute('data-pf'), key = b.getAttribute('data-key'), i = parseInt(b.getAttribute('data-i'), 10);
        if (act === 'bio-edit') {{ _pfEdit = {{ field: 'bio', index: -1 }}; _pfRenderAbout(); }}
        else if (act === 'bio-cancel' || act === 'list-cancel') {{ _pfEdit = {{ field: null, index: -1 }}; _pfRenderAbout(); }}
        else if (act === 'bio-save') {{ var el = document.getElementById('pf-bio-input'); _pfMy.bio = el ? el.value.trim() : ''; _pfEdit = {{ field: null, index: -1 }}; _pfPersist(); _pfRenderAbout(); }}
        else if (act === 'list-edit') {{ _pfEdit = {{ field: key, index: i }}; _pfRenderAbout(); }}
        else if (act === 'list-save') {{ var inp = host.querySelector('.pf-item--edit .pf-input[data-key="' + key + '"][data-i="' + i + '"]'); _pfCommitEdit(key, i, inp ? inp.value : ''); }}
        else if (act === 'list-del') {{ var ls = _pfLines(key); ls.splice(i, 1); _pfMy[key] = ls.join('\\n'); _pfPersist(); _pfRenderAbout(); }}
        else if (act === 'list-add') {{ var ai = document.getElementById('pf-add-' + key); _pfCommitAdd(key, ai ? ai.value : ''); }}
      }});
      host.addEventListener('keydown', function (e) {{
        if (e.key !== 'Enter' || e.shiftKey) return;
        var t = e.target; if (!t || !t.hasAttribute) return;
        if (t.hasAttribute('data-addkey')) {{ e.preventDefault(); _pfCommitAdd(t.getAttribute('data-addkey'), t.value); return; }}
        if (t.classList && t.classList.contains('pf-input') && t.hasAttribute('data-i')) {{ e.preventDefault(); _pfCommitEdit(t.getAttribute('data-key'), parseInt(t.getAttribute('data-i'), 10), t.value); return; }}
      }});
    }}
    // One editable material slot for a person (their own card, or any person in
    // Angela's team directory). Element ids are keyed by <person>-<slot> so
    // several people's slots can coexist. Includes an optional link TITLE.
    function _materialSlotHtml(key, m) {{
      var sid = key + '-' + m.k;
      return '<div class="profile-material"><div class="profile-material-head">' +
          '<span class="profile-material-label">' + escapeHtml(m.label) + '</span>' +
          '<span class="hint">' + escapeHtml(m.hint) + '</span></div>' +
        '<div class="profile-files" id="pf-files-' + sid + '"><p class="profile-file-empty">Loading&hellip;</p></div>' +
        '<div class="profile-upload-row"><input type="file" id="pf-file-input-' + sid + '" aria-label="Choose a file for ' + escapeHtml(m.label) + '">' +
          '<button type="button" class="q-btn" data-mat-upload="' + escapeHtml(key + '|' + m.k) + '">Upload</button></div>' +
        '<div class="profile-link-row"><input type="text" id="pf-link-title-' + sid + '" class="pf-link-title" placeholder="Doc title (optional)" aria-label="Title for the ' + escapeHtml(m.label) + ' link">' +
          '<input type="url" id="pf-link-input-' + sid + '" placeholder="paste a Google Drive / Doc link" aria-label="Paste a link for ' + escapeHtml(m.label) + '">' +
          '<button type="button" class="q-btn" data-mat-link="' + escapeHtml(key + '|' + m.k) + '">Add link</button></div>' +
      '</div>';
    }}
    // Files for one material slot (<meKey>/<cat>/…) — download + delete.
    function _loadProfileFiles(meKey, cat, setupPending) {{
      var $files = document.getElementById('pf-files-' + meKey + '-' + cat);
      if (!$files) return;
      var prefix = meKey + '/' + cat;
      // A missing bucket returns an empty list (not an error), so lean on the
      // same setup signal as the text store for the empty-state wording.
      var emptyMsg = setupPending
        ? 'Storage not set up yet.'
        : 'Nothing here yet.';
      sb.storage.from('profiles').list(prefix, {{ limit: 100, sortBy: {{ column: 'created_at', order: 'desc' }} }}).then(function (resp) {{
        if (resp && resp.error) {{
          $files.innerHTML = '<p class="profile-file-empty">File storage isn&#39;t set up yet &mdash; the one-time <code>profiles</code> bucket setup is still pending.</p>';
          return;
        }}
        var items = ((resp && resp.data) || []).filter(function (f) {{ return f.name && f.name !== '.emptyFolderPlaceholder'; }});
        if (!items.length) {{ $files.innerHTML = '<p class="profile-file-empty">' + emptyMsg + '</p>'; return; }}
        $files.innerHTML = items.map(function (f) {{
          var size = (f.metadata && f.metadata.size) ? _fmtBytes(f.metadata.size) : '';
          return _matFileRowHtml(prefix + '/' + f.name, f.name, size, true);
        }}).join('');
        _wireProfileFileContainer($files, function (fullPath, name) {{
          if (!window.confirm('Delete "' + name + '"? This cannot be undone.')) return;
          sb.storage.from('profiles').remove([fullPath]).then(function (r) {{
            if (r && r.error) {{ status('Delete failed: ' + r.error.message, 'error'); return; }}
            flashOk('Deleted'); _loadProfileFiles(meKey, cat, false);
          }});
        }}, function (fullPath, url, curTitle) {{
          // Rename a linked doc's title: re-encode {{t,u}} and MOVE the marker file
          // to the new name (its name is the source of truth; content is unused).
          var raw = window.prompt('Rename this link:', curTitle || '');
          if (raw === null) return;                       // cancelled
          var nt = raw.trim().slice(0, 200);
          var payload = nt ? JSON.stringify({{ t: nt, u: url }}) : url;
          var enc = _b64urlEnc(payload);
          if (!enc || enc.length > 700) {{ status('Could not rename (too long).', 'error'); return; }}
          var newPath = fullPath.replace(/\\/[^\\/]*$/, '/' + enc + '.weblink');
          if (newPath === fullPath) return;               // no change
          sb.storage.from('profiles').move(fullPath, newPath).then(function (r) {{
            if (r && r.error) {{ status('Rename failed: ' + r.error.message, 'error'); return; }}
            flashOk('Renamed'); _loadProfileFiles(meKey, cat, false);
          }});
        }});
      }});
    }}
    // Save a Google Drive / Doc (or any) link into a material slot, stored as a
    // ".weblink" marker file: base64url of {{t:title, u:url}} (or just the URL
    // when no title is given). Title shows as the link's label.
    function _addProfileLink(meKey, cat) {{
      var sid = meKey + '-' + cat;
      var $in = document.getElementById('pf-link-input-' + sid);
      var $title = document.getElementById('pf-link-title-' + sid);
      var url = (($in && $in.value) || '').trim();
      var title = (($title && $title.value) || '').trim().slice(0, 200);
      if (!/^https?:\\/\\//i.test(url)) {{ status('Paste a full link starting with http:// or https://', 'warn'); return; }}
      if (url.length > 600) {{ status('That link is too long to save.', 'error'); return; }}
      var payload = title ? JSON.stringify({{ t: title, u: url }}) : url;
      var enc = _b64urlEnc(payload);
      if (!enc || enc.length > 700) {{ status('Could not save that link (too long).', 'error'); return; }}
      var $btn = document.querySelector('[data-mat-link="' + meKey + '|' + cat + '"]');
      if ($btn) {{ $btn.setAttribute('aria-busy', 'true'); $btn.textContent = 'Adding\\u2026'; }}
      sb.storage.from('profiles').upload(meKey + '/' + cat + '/' + enc + '.weblink',
          new Blob([payload], {{ type: 'text/plain' }}), {{ upsert: true, contentType: 'text/plain' }}).then(function (resp) {{
        if ($btn) {{ $btn.removeAttribute('aria-busy'); $btn.textContent = 'Add link'; }}
        if (resp && resp.error) {{
          status('Could not add the link: ' + resp.error.message + (/bucket|not found/i.test(resp.error.message) ? ' \\u2014 the profiles storage bucket may not be set up yet.' : ''), 'error');
          return;
        }}
        if ($in) $in.value = ''; if ($title) $title.value = '';
        flashOk('Link added'); _loadProfileFiles(meKey, cat, false);
      }});
    }}
    function _uploadProfileFile(meKey, cat) {{
      var $in = document.getElementById('pf-file-input-' + meKey + '-' + cat);
      if (!$in || !$in.files || !$in.files.length) {{ status('Pick a file first.', 'warn'); return; }}
      var file = $in.files[0];
      if (file.size > 25 * 1024 * 1024) {{ status('That file is over 25 MB \\u2014 please upload something smaller.', 'error'); return; }}
      var $up = document.querySelector('[data-mat-upload="' + meKey + '|' + cat + '"]');
      if ($up) {{ $up.setAttribute('aria-busy', 'true'); $up.textContent = 'Uploading\\u2026'; }}
      sb.storage.from('profiles').upload(meKey + '/' + cat + '/' + file.name, file, {{ upsert: true }}).then(function (resp) {{
        if ($up) {{ $up.removeAttribute('aria-busy'); $up.textContent = 'Upload'; }}
        if (resp && resp.error) {{
          status('Upload failed: ' + resp.error.message + (/bucket|not found/i.test(resp.error.message) ? ' \\u2014 the profiles storage bucket may not be set up yet.' : ''), 'error');
          return;
        }}
        if ($in) $in.value = '';
        flashOk('File uploaded');
        _loadProfileFiles(meKey, cat, false);
      }});
    }}

    // ── Planner: scheduling conflicts + coverage gaps by territory ──
    // ── Per-teammate target profiles ────────────────────────────────
    // Single source of truth for "which events are for whom" — drives the
    // Planner's coverage gaps AND the grid "Fits" filter (and is mirrored in
    // prose for the Ask-AI assistant). An event fits a profile if its canonical
    // region is in `regions`, OR any keyword hits the event's folded text blob
    // (matched as whole words). Keep keywords lowercase + punctuation-free.
    var AB_PROFILES = [
      {{ key: 'Jerome', label: 'Europe (enterprise)', regions: ['Europe'], locked: true,
         kw: ['london','dublin','amsterdam','brussels','zurich','geneva','luxembourg','berlin','munich','frankfurt','vienna','stockholm','copenhagen','oslo','helsinki','madrid','barcelona','milan','lisbon','europe','emea','european','financial services','insurance','fintech','healthcare','telco','retail','ecommerce','media','gdpr'] }},
      {{ key: 'Joe', label: 'HR & people (US)', regions: [],
         kw: ['hr','human resources','chro','clo','chief people','people officer','vp of hr','talent','workforce','future of work','upskilling','reskilling','learning','l&d','people analytics','change management','human enablement','human capital','organizational development','employee experience'] }},
      {{ key: 'Thor', label: 'Healthcare (exec)', regions: [],
         kw: ['healthcare','healthtech','health tech','digital health','medtech','med tech','life sciences','pharma','pharmaceutical','biotech','medical','health system','healthcare ai','patient care','telehealth','payer','provider'] }},
      {{ key: 'Verma', label: 'Insurance & regulated (board-level)', regions: [],
         kw: ['insurance','insurtech','life insurance','reinsurance','finance','financial services','bank','banking','capital markets','payments','fintech','board','chief data','regulated','compliance'] }},
      // Carlos runs LatAm — no US cities (Hurley 2026-07-29). 'US & Canada' used
      // to sit in his regions, and because he's region-LOCKED that single token
      // was doing almost all the work: 393 of his 427 fits were US events
      // (Las Vegas, Austin, Nashville…), swamping the 34 that are actually his.
      // NOTE: `locked` returns on the region test, so the kw list below never
      // runs for him — it's kept only as documentation of his territory.
      {{ key: 'Carlos', label: 'Latin America (mid-market)', regions: ['Latin America'], locked: true,
         kw: ['mexico city','monterrey','santo domingo','san juan','sao paulo','bogota','buenos aires','lima','santiago','quito','financial services','insurance','fintech','healthcare','saas','retail','telco','media'] }},
      {{ key: 'Jim', label: 'Government (DC)', regions: [],
         kw: ['government','public sector','federal','defense','national security','govtech','civic','municipal','state and local','washington','washington dc','capitol','congress','white house','agency','gsa','dod','nist','fedramp','public policy'] }},
      // Hurley runs the tracker and doesn't speak — his "fits" are the ones he'd
      // actually walk into: FREE AI events within reach of the Northeast. Unlike
      // the others this is an AND, not a keyword OR: it must be an AI event, AND
      // in the Northeast, AND free. Hence allKw (every group must hit) + freeOnly.
      {{ key: 'Hurley', label: 'Free AI events (Northeast)', regions: [], kw: [], support: true,
         freeOnly: true,
         allKw: [
           ['ai','a i','artificial intelligence','machine learning','deep learning','genai','gen ai','generative ai','llm','llms','agentic','data science','mlops','nlp'],
           ['new york','new york city','nyc','manhattan','brooklyn','queens','bronx','long island','boston','cambridge','somerville','philadelphia','philly','pittsburgh','newark','jersey city','princeton','hoboken','stamford','hartford','new haven','greenwich','providence','portland maine','burlington','albany','buffalo','rochester','syracuse','new england','northeast','tri state','tri-state','connecticut','massachusetts','new jersey','rhode island','new hampshire','vermont','maine','pennsylvania','new york state']
         ] }}
    ];
    var AB_PROFILE_BY_KEY = {{}};
    AB_PROFILES.forEach(function (p) {{ AB_PROFILE_BY_KEY[p.key] = p; }});
    // Profile keys are capitalized ("Thor"); the signed-in first name is folded
    // lowercase ("thor"). Case-insensitive lookup for the "My fits" chip.
    var AB_PROFILE_BY_LCKEY = {{}};
    AB_PROFILES.forEach(function (p) {{ AB_PROFILE_BY_LCKEY[String(p.key).toLowerCase()] = p; }});
    // True if an event (canonical region + folded text blob) fits a profile.
    function _cardPriceNum(card) {{
      var v = card && card.dataset ? card.dataset.price : '';
      if (v === '' || v == null) return null;
      var n = parseFloat(v);
      return isNaN(n) ? null : n;
    }}
    // priceNum: the event's parsed ticket price (0 = free, null = unknown). Only
    // consulted by a freeOnly profile; every other profile ignores it.
    // isForeign: the event's title is in a non-English language. Thor, Verma and
    // Joe present and sell in English, so a Spanish/Portuguese/French/German/
    // Italian-language event is never their fit (Hurley 2026-07-29) — it stays
    // available to Jerome and Carlos, whose territories it belongs to.
    function profileFits(p, blob, region, priceNum, isForeign) {{
      if (!p) return false;
      if (isForeign && _ENGLISH_ONLY_PEOPLE[String(p.key || '').toLowerCase()]) return false;
      // (Australia used to be carved out as Verma's exclusive territory. It was
      // taken off his profile, so this gate went with it — kept on its own it
      // would have left every AU event fitting NOBODY. Australian events now
      // match on their own merits, like anywhere else: an AU insurance event
      // still reaches Verma via 'insurance', an AU healthcare one reaches Thor.)
      // HR / CHRO / people events are JOE'S audience only — keep them off everyone
      // else's fit (a CHRO summit whose attendees span industries was matching
      // Thor on a stray "healthcare"). Matched on the strong HR event signals.
      if (p.key !== 'Joe' && /\\bchro\\b|shrm|chief (human resources|people)|people officer|\\bhr (summit|conference|forum|assembly|exchange|congress|leaders)\\b/.test(String(blob || ''))) return false;
      // AND-profile (Hurley): every keyword group must hit, and a freeOnly
      // profile additionally requires a price we KNOW is zero — an unknown price
      // is not "free", so it stays out rather than pretending.
      if (p.allKw && p.allKw.length) {{
        if (p.freeOnly && priceNum !== 0) return false;
        var hb = ' ' + String(blob || '').replace(/[^a-z0-9]/g, ' ').replace(/ +/g, ' ').trim() + ' ';
        for (var gi = 0; gi < p.allKw.length; gi++) {{
          var grp = p.allKw[gi], hit = false;
          for (var gj = 0; gj < grp.length; gj++) {{
            if (hb.indexOf(' ' + grp[gj] + ' ') !== -1) {{ hit = true; break; }}
          }}
          if (!hit) return false;
        }}
        return true;
      }}
      var regionOk = !!(region && p.regions.indexOf(region) !== -1);
      // Region-locked people (Jerome = Europe, Carlos = Latin America) fit ONLY
      // their own region — a loose keyword (a city named in a blurb, or 'web
      // summit') must not pull an out-of-region event to them.
      if (p.locked) return regionOk;
      if (regionOk) return true;
      var b = ' ' + String(blob || '').replace(/[^a-z0-9 ]/g, ' ').replace(/ +/g, ' ').trim() + ' ';
      for (var i = 0; i < p.kw.length; i++) {{ if (b.indexOf(' ' + p.kw[i] + ' ') !== -1) return true; }}
      return false;
    }}

    // Planner coverage-gap territories, derived from the profiles above.
    var AB_TERRITORIES = AB_PROFILES.filter(function (p) {{ return !p.support; }}).map(function (p) {{
      return {{ who: p.key, label: p.label, test: function (it) {{ return profileFits(p, it.text, it.region, null, _isForeignLangEvent(it)); }} }};
    }});
    // Thor leads the coverage gaps — he's the priority, and this list was in
    // whatever order AB_PROFILES happened to be written (Hurley 2026-07-30).
    AB_TERRITORIES.sort(function (x, y) {{
      var ix = PLAN_ORDER.indexOf(String(x.who).toLowerCase());
      var iy = PLAN_ORDER.indexOf(String(y.who).toLowerCase());
      if (ix === -1) ix = 99; if (iy === -1) iy = 99;
      return ix - iy || String(x.who).localeCompare(String(y.who));
    }});

    function opsDateRange(o) {{
      var s = (o.start_date && /^\\d{{4}}-\\d{{2}}-\\d{{2}}/.test(o.start_date)) ? o.start_date.slice(0, 10) : null;
      var e = (o.end_date && /^\\d{{4}}-\\d{{2}}-\\d{{2}}/.test(o.end_date)) ? o.end_date.slice(0, 10) : null;
      if (!s && o.date_str) {{ try {{ var d = deriveDatesFromText(o.date_str); s = d.start_date; e = d.end_date; }} catch (x) {{}} }}
      if (!s) return null;
      if (!e) e = s;
      var sm = new Date(s + 'T00:00:00').getTime();
      var em = new Date(e + 'T23:59:59').getTime();
      if (isNaN(sm)) return null;
      if (isNaN(em) || em < sm) em = sm;
      return [sm, em];
    }}

    function speakerTokens(sp) {{
      if (!sp) return [];
      return abFold(sp).split(/[,;/&]| and |\\bplus\\b/).map(function (s) {{ return s.trim(); }}).filter(Boolean);
    }}

    function findConflicts() {{
      var byWho = {{}};
      opsAllItems().forEach(function (it) {{
        if (it.past || !it.speaker || it.hidden) return;
        // Only a real clash if the person is committed (Booked or Attending)
        // to both events — not merely considering them.
        if (it.stages.indexOf('Booked') === -1 && it.stages.indexOf('Attending') === -1) return;
        var range = opsDateRange(it.startObj);
        if (!range) return;
        speakerTokens(it.speaker).forEach(function (tok) {{
          if (tok) (byWho[tok] = byWho[tok] || []).push({{ it: it, range: range }});
        }});
      }});
      var conflicts = [];
      Object.keys(byWho).forEach(function (tok) {{
        var list = byWho[tok];
        if (list.length < 2) return;
        for (var i = 0; i < list.length; i++) {{
          for (var j = i + 1; j < list.length; j++) {{
            var a = list[i], b = list[j];
            if (a.range[0] <= b.range[1] && b.range[0] <= a.range[1]) {{
              // Same city = same trip, not a double-booking — only flag
              // overlapping events in DIFFERENT cities as real conflicts.
              if (a.it.city && b.it.city && a.it.city === b.it.city) continue;
              conflicts.push({{ who: tok, a: a.it, b: b.it }});
            }}
          }}
        }}
      }});
      return conflicts;
    }}

    // ── Warm-intro connections (LinkedIn CSV upload) ────────────────
    function _csvLine(line) {{
      var out = [], cur = '', q = false;
      for (var i = 0; i < line.length; i++) {{
        var c = line[i];
        if (q) {{ if (c === '"') {{ if (line[i + 1] === '"') {{ cur += '"'; i++; }} else q = false; }} else cur += c; }}
        else {{ if (c === '"') q = true; else if (c === ',') {{ out.push(cur); cur = ''; }} else cur += c; }}
      }}
      out.push(cur); return out;
    }}
    function parseConnectionsCsv(text, owner) {{
      var lines = text.split(/\\r\\n|\\n|\\r/);
      var hi = -1;
      for (var i = 0; i < lines.length; i++) {{ if (/^"?First Name"?\\s*,/i.test(lines[i])) {{ hi = i; break; }} }}
      if (hi === -1) return [];
      var h = _csvLine(lines[hi]).map(function (x) {{ return x.trim().toLowerCase(); }});
      var ci = {{ first: h.indexOf('first name'), last: h.indexOf('last name'),
                 company: h.indexOf('company'), position: h.indexOf('position'), url: h.indexOf('url') }};
      if (ci.first === -1 || ci.last === -1) return [];
      var rows = [];
      for (var j = hi + 1; j < lines.length; j++) {{
        if (!lines[j].trim()) continue;
        var f = _csvLine(lines[j]);
        var full = ((f[ci.first] || '').trim() + ' ' + (f[ci.last] || '').trim()).trim();
        if (!full) continue;
        rows.push({{ owner: owner, full_name: full.toLowerCase(), display_name: full,
          company: ci.company >= 0 ? (f[ci.company] || '').trim() : null,
          position: ci.position >= 0 ? (f[ci.position] || '').trim() : null,
          profile_url: ci.url >= 0 ? (f[ci.url] || '').trim() : null }});
      }}
      return rows;
    }}
    // The connections table needs a one-time migration. PostgREST reports a
    // missing table several ways ("does not exist", "schema cache", PGRST205),
    // so match them all and show ONE clear setup message instead of a raw error.
    var _CONN_SETUP_MSG = 'Warm intros need a one-time setup — run scripts/2026-06-21_connections.sql in the Supabase SQL editor, then re-upload.';
    function _isMissingTable(err) {{
      var m = ((err && (err.message || '')) + ' ' + (err && (err.code || ''))).toLowerCase();
      return /does not exist|relation|schema cache|find the table|pgrst205/.test(m);
    }}
    function refreshConnCounts() {{
      var el = document.getElementById('conn-counts'); if (!el) return;
      sb.from('connections').select('owner').then(function (r) {{
        if (r.error) {{ el.textContent = _isMissingTable(r.error) ? _CONN_SETUP_MSG : ''; return; }}
        var counts = {{}}; (r.data || []).forEach(function (x) {{ counts[x.owner] = (counts[x.owner] || 0) + 1; }});
        var parts = Object.keys(counts).sort().map(function (o) {{ return o + ': ' + counts[o]; }});
        el.textContent = parts.length ? ('Stored — ' + parts.join(' · ')) : 'No connections uploaded yet.';
      }});
    }}
    function wireConnectionsPanel() {{
      var btn = document.getElementById('conn-upload'); if (!btn) return;
      refreshConnCounts();
      btn.addEventListener('click', function () {{
        var owner = (document.getElementById('conn-owner') || {{}}).value;
        var fileEl = document.getElementById('conn-file');
        var status = document.getElementById('conn-status');
        var file = fileEl && fileEl.files && fileEl.files[0];
        if (!file) {{ status.textContent = 'Choose a CSV first.'; return; }}
        status.textContent = 'Reading…';
        var reader = new FileReader();
        reader.onload = function () {{
          var rows = parseConnectionsCsv(reader.result, owner);
          if (!rows.length) {{ status.textContent = 'No connections found (expected a LinkedIn Connections.csv).'; return; }}
          status.textContent = 'Uploading ' + rows.length + '…';
          // Replace this teammate's set, then insert in chunks.
          sb.from('connections').delete().eq('owner', owner).then(function (d) {{
            if (d.error && _isMissingTable(d.error)) {{ status.textContent = _CONN_SETUP_MSG; return; }}
            var CHUNK = 500, idx = 0;
            (function next() {{
              if (idx >= rows.length) {{ status.textContent = 'Saved ' + rows.length + ' connections for ' + owner + '.'; refreshConnCounts(); return; }}
              sb.from('connections').insert(rows.slice(idx, idx + CHUNK)).then(function (r) {{
                if (r.error) {{ status.textContent = _isMissingTable(r.error) ? _CONN_SETUP_MSG : ('Error: ' + r.error.message); return; }}
                idx += CHUNK; next();
              }});
            }})();
          }});
        }};
        reader.readAsText(file);
      }});
    }}

    function renderPlanner() {{
      var host = document.getElementById('ops-planner');
      if (!host) return;
      var items = opsAllItems();
      var html = '<p class="planner-intro"><strong>Planner:</strong> Checks the calendar: scheduling conflicts (one speaker double-booked)</p>';

      var conflicts = findConflicts();
      html += '<div class="planner-section"><div class="planner-sec-head"><span class="planner-sec-title">&#9888; Scheduling conflicts</span><span class="planner-sec-sub">' + conflicts.length + ' found</span></div>';
      if (!conflicts.length) {{
        html += '<div class="planner-empty">No conflicts &mdash; every assigned speaker is in one place at a time.</div>';
      }} else {{
        conflicts.forEach(function (c) {{
          var who = c.who.charAt(0).toUpperCase() + c.who.slice(1);
          html += '<div class="conflict-row"><span class="conflict-icon">&#9888;</span><div class="conflict-body">' +
            '<span class="conflict-who">' + escapeHtml(who) + '</span> is booked for two overlapping events:' +
            '<span class="conflict-vs">' +
              '<button class="conflict-evt" data-ref-kind="' + c.a.kind + '" data-ref-key="' + escapeHtml(String(c.a.key)) + '">' + escapeHtml(c.a.name) + '</button> (' + escapeHtml(c.a.date_str || '?') + ')' +
              ' &nbsp;vs&nbsp; ' +
              '<button class="conflict-evt" data-ref-kind="' + c.b.kind + '" data-ref-key="' + escapeHtml(String(c.b.key)) + '">' + escapeHtml(c.b.name) + '</button> (' + escapeHtml(c.b.date_str || '?') + ')' +
            '</span></div></div>';
        }});
      }}
      // Conflicts Angela typed — the ones dates can't reveal (a board offsite,
      // leave). Listed alongside the detected ones so the section is the whole
      // picture, not just what the calendar could work out.
      var manualCf = items.filter(function (it) {{
        return !it.past && !it.hidden && String((it.startObj || it).conflict_note || '').trim();
      }});
      manualCf.forEach(function (it) {{
        html += '<div class="conflict-row"><span class="conflict-icon">&#9888;</span><div class="conflict-body">' +
          '<button class="conflict-evt" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' +
          escapeHtml(it.name) + '</button> &mdash; ' +
          escapeHtml(String((it.startObj || it).conflict_note).trim()) +
          ' <button type="button" class="cf-edit" data-cf-kind="' + it.kind + '" data-cf-key="' + escapeHtml(String(it.key)) + '">edit</button>' +
          '</div></div>';
      }});
      html += '<button type="button" class="ab-addbtn" id="planner-cf-add">' +
              '<span class="ab-addbtn-ic" aria-hidden="true">+</span> Add a scheduling conflict</button>' +
              '<div class="ab-form" id="planner-cf-form" hidden>' +
                '<input type="text" class="ab-input" id="planner-cf-q" autocomplete="off" ' +
                  'placeholder="Which event? Start typing its name\u2026">' +
                '<div class="cf-hits" id="planner-cf-hits"></div>' +
                '<textarea class="ab-input" id="planner-cf-note" rows="2" ' +
                  'placeholder="What\u2019s the clash? e.g. Thor is at the board offsite that week"></textarea>' +
                '<div class="ab-form-actions">' +
                  '<button type="button" class="ab-btn-primary" id="planner-cf-save" disabled>Save conflict</button>' +
                  '<button type="button" class="ab-btn-ghost" id="planner-cf-cancel">Cancel</button>' +
                  '<span class="ab-form-hint" id="planner-cf-picked"></span>' +
                '</div>' +
              '</div>';
      html += '</div>';

      html += '<div class="planner-section"><div class="planner-sec-head"><span class="planner-sec-title">&#128506; Coverage gaps by territory</span><span class="planner-sec-sub">upcoming events with no speaker assigned</span></div>';
      var CAP = 12;
      AB_TERRITORIES.forEach(function (terr) {{
        var inTerr = items.filter(function (it) {{ return !it.past && !it.hidden && terr.test(it); }});
        if (!inTerr.length) return;
        var covered = inTerr.filter(function (it) {{ return it.speaker && it.speaker.trim(); }});
        // A "gap" is an event NOBODY has dealt with yet. Once Angela flags it for
        // someone, tags it, notes it, or archives it, it drops off this list —
        // it stayed put before (just re-labelled "✓ Flagged for X"), so the list
        // never shrank as she worked it. opsHandled covers every such action.
        var gaps = inTerr.filter(function (it) {{
          return !(it.speaker && it.speaker.trim()) && !opsHandled(it);
        }});
        gaps.sort(function (a, b) {{ return a.sort - b.sort; }});
        html += '<div class="gap-owner"><div class="gap-owner-head">' +
            '<span class="gap-owner-name">' + escapeHtml(terr.who) + '</span>' +
            '<span class="gap-owner-stat">' + inTerr.length + ' events &middot; ' + covered.length + ' covered &middot; <b>' + gaps.length + ' untouched</b></span>' +
          '</div>';
        if (!gaps.length) {{
          html += '<p class="gap-none">&#10003; Nothing left to triage here &mdash; every event is assigned, flagged or already dealt with.</p>';
        }} else {{
          html += '<div class="gap-list">';
          gaps.slice(0, CAP).forEach(function (it) {{
            var loc = [it.location].filter(Boolean).join(' &middot; ');
            // No "✓ Flagged for X" state any more — flagging removes the row
            // from the gap list entirely (that's the point: the list is work
            // still to do, and it should shrink as she works it).
            html += '<div class="gap-row"><div>' +
                '<button class="gap-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
                '<p class="gap-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' &middot; ' + loc : '') + '</p>' +
              '</div>' +
              '<div class="gap-actions">' +
                '<button class="q-btn primary" data-flag="' + escapeHtml(terr.who) + '" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '">+ Flag for ' + escapeHtml(terr.who) + '</button>' +
              '</div>' +
              '</div>';
          }});
          if (gaps.length > CAP) html += '<p class="gap-more">Showing first ' + CAP + ' of ' + gaps.length + ' &mdash; assign or flag some to clear the list.</p>';
          html += '</div>';
        }}
        html += '</div>';
      }});
      html += '</div>';
      // Warm-intro connections uploader — powers "warm via …" on Deep Targets.
      html += '<div class="planner-section conn-panel"><div class="planner-sec-head">' +
        '<span class="planner-sec-title">&#128279; Warm intros &mdash; team LinkedIn connections</span>' +
        '<span class="planner-sec-sub">flags &ldquo;warm via&hellip;&rdquo; on Deep Targets &middot; stays in our DB, never sent to AI</span></div>' +
        '<p class="conn-help">Each teammate: LinkedIn &rarr; Settings &rarr; Get a copy of your data &rarr; Connections &rarr; upload the CSV here.</p>' +
        '<div class="conn-row"><select id="conn-owner" aria-label="Whose connections">' +
        OPS_ROSTER.map(function (n) {{ return '<option value="' + escapeHtml(n) + '">' + escapeHtml(n) + '</option>'; }}).join('') +
        '</select><input type="file" id="conn-file" accept=".csv" aria-label="Connections CSV">' +
        '<button type="button" class="q-btn primary" id="conn-upload">Upload</button>' +
        '<span id="conn-status" class="conn-status"></span></div>' +
        '<div id="conn-counts" class="conn-counts"></div></div>';
      host.innerHTML = html;
      wireConnectionsPanel();

      host.querySelectorAll('[data-ref-kind]').forEach(function (el) {{
        el.addEventListener('click', function () {{ opsOpenRef(el.getAttribute('data-ref-kind'), el.getAttribute('data-ref-key')); }});
      }});

      // Add / edit a scheduling conflict from the Planner, which is where
      // Angela is looking when she notices one (Hurley 2026-07-30).
      // Editing an existing conflict happens in the row it belongs to — the
      // note becomes a field where the text was, and nothing floats to the top
      // of the window (Hurley 2026-07-30).
      host.querySelectorAll('[data-cf-kind]').forEach(function (el) {{
        el.addEventListener('click', function (e) {{
          e.stopPropagation();
          var it = opsAllItems().filter(function (x) {{
            return x.kind === el.getAttribute('data-cf-kind') &&
                   String(x.key) === el.getAttribute('data-cf-key');
          }})[0];
          var row = el.parentNode;                       // .conflict-body
          if (!it || !row || row.querySelector('.ab-form')) return;
          var cur = String((it.startObj || it).conflict_note || '');
          var keep = row.innerHTML;
          var w = document.createElement('div');
          w.className = 'ab-form';
          w.innerHTML = '<textarea class="ab-input" rows="2"></textarea>' +
            '<div class="ab-form-actions">' +
              '<button type="button" class="ab-btn-primary" data-go>Save</button>' +
              '<button type="button" class="ab-btn-ghost" data-cancel>Cancel</button>' +
              '<button type="button" class="cf-edit" data-clear style="margin-left:auto;">Remove</button>' +
            '</div>';
          row.innerHTML = '<strong>' + escapeHtml(it.name) + '</strong>';
          row.appendChild(w);
          var ta = w.querySelector('textarea');
          ta.value = cur; ta.focus(); ta.setSelectionRange(cur.length, cur.length);
          function done(val) {{ opsQuickWrite(it.kind, it.key, {{ conflict_note: val }}); }}
          w.querySelector('[data-go]').addEventListener('click', function () {{
            done(ta.value.trim() || null);
          }});
          w.querySelector('[data-clear]').addEventListener('click', function () {{ done(null); }});
          w.querySelector('[data-cancel]').addEventListener('click', function () {{
            row.innerHTML = keep;
            renderPlanner();                              // rewire the restored row
          }});
          ta.addEventListener('keydown', function (ev) {{
            if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {{ ev.preventDefault(); done(ta.value.trim() || null); }}
          }});
        }});
      }});
      // "+ Add a scheduling conflict" — pick the event from a filtered list
      // rather than typing part of a name into a prompt and then a number to
      // choose between the matches.
      var cfAdd = document.getElementById('planner-cf-add');
      var cfForm = document.getElementById('planner-cf-form');
      if (cfAdd && cfForm) {{
        var cfQ = document.getElementById('planner-cf-q');
        var cfHits = document.getElementById('planner-cf-hits');
        var cfNote = document.getElementById('planner-cf-note');
        var cfSave = document.getElementById('planner-cf-save');
        var cfPicked = document.getElementById('planner-cf-picked');
        var _pick = null;
        function cfClose() {{
          cfForm.hidden = true; cfAdd.hidden = false;
          _pick = null; cfQ.value = ''; cfNote.value = '';
          cfHits.innerHTML = ''; cfPicked.textContent = ''; cfSave.disabled = true;
        }}
        function cfSync() {{ cfSave.disabled = !(_pick && cfNote.value.trim()); }}
        cfAdd.addEventListener('click', function () {{
          cfForm.hidden = false; cfAdd.hidden = true; cfQ.focus();
        }});
        document.getElementById('planner-cf-cancel').addEventListener('click', cfClose);
        cfQ.addEventListener('input', function () {{
          _pick = null; cfPicked.textContent = ''; cfSync();
          var q = cfQ.value.trim().toLowerCase();
          if (q.length < 2) {{ cfHits.innerHTML = ''; return; }}
          var hits = opsAllItems().filter(function (it) {{
            return !it.past && !it.hidden && String(it.name || '').toLowerCase().indexOf(q) !== -1;
          }}).slice(0, 7);
          if (!hits.length) {{
            cfHits.innerHTML = '<div class="cf-hit-none">No upcoming event matches that.</div>';
            return;
          }}
          cfHits.innerHTML = hits.map(function (it, i) {{
            return '<button type="button" class="cf-hit" data-i="' + i + '">' +
                   escapeHtml(it.name) +
                   '<span class="cf-hit-when">' + escapeHtml(String(it.date_str || '')) + '</span>' +
                   '</button>';
          }}).join('');
          cfHits.querySelectorAll('.cf-hit').forEach(function (b, i) {{
            b.addEventListener('click', function () {{
              _pick = hits[i];
              cfQ.value = _pick.name;
              cfHits.innerHTML = '';
              cfPicked.textContent = 'on ' + _pick.name;
              cfNote.focus();
              cfSync();
            }});
          }});
        }});
        cfNote.addEventListener('input', cfSync);
        cfSave.addEventListener('click', function () {{
          if (!_pick || !cfNote.value.trim()) return;
          opsQuickWrite(_pick.kind, _pick.key, {{ conflict_note: cfNote.value.trim() }});
        }});
        cfNote.addEventListener('keydown', function (e) {{
          if (e.key === 'Escape') {{ e.preventDefault(); cfClose(); }}
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {{ e.preventDefault(); cfSave.click(); }}
        }});
        cfQ.addEventListener('keydown', function (e) {{
          if (e.key === 'Escape') {{ e.preventDefault(); cfClose(); }}
        }});
      }}
      host.querySelectorAll('[data-flag]').forEach(function (btn) {{
        btn.addEventListener('click', function (e) {{
          e.stopPropagation();
          var who = btn.getAttribute('data-flag');
          var kind = btn.getAttribute('data-k'), key = btn.getAttribute('data-key');
          var it = items.filter(function (x) {{ return x.kind === kind && String(x.key) === key; }})[0];
          if (!it) return;
          var list = it.interested.slice();
          if (list.indexOf(who) === -1) list.push(who);
          list = OPS_ROSTER.filter(function (x) {{ return list.indexOf(x) !== -1; }});
          opsQuickWrite(kind, key, {{ interested: list }});
        }});
      }});
      updateViewBadges();
    }}

    // Count badges on the Queue / Planner tabs (open-to-apply count + conflicts).
    function updateViewBadges() {{
      var mc = document.getElementById('vt-myevents-count');
      if (mc) {{
        var mb = myEventsBuckets();
        var mn = mb.upcoming.length;   // badge = upcoming count (the actionable one)
        if (mb.named && mn) {{ mc.textContent = mn; mc.removeAttribute('hidden'); }} else {{ mc.setAttribute('hidden', ''); }}
      }}
      var qc = document.getElementById('vt-queue-count');
      var pc = document.getElementById('vt-planner-count');
      if (qc) {{
        // Same source as the rendered Queue — the badge is a count of the rows
        // she'll actually see when she opens the tab, nothing else.
        var n = queueItems().length;
        if (n) {{ qc.textContent = n; qc.removeAttribute('hidden'); }} else {{ qc.setAttribute('hidden', ''); }}
      }}
      if (pc) {{
        var c = findConflicts().length;
        if (c) {{ pc.textContent = c; pc.classList.add('alert'); pc.removeAttribute('hidden'); }}
        else {{ pc.setAttribute('hidden', ''); pc.classList.remove('alert'); }}
      }}
    }}

    // ── Resilient data loading ─────────────────────────────────────
    // fetch() does NOT reject on HTTP errors, and a mid-deploy edge can serve a
    // non-JSON error page — so check r.ok AND retry twice with backoff before
    // failing. Without this, one transient blip stranded the app on
    // "Loading events…" forever (Thor's 30-minute "no events" outage).
    function fetchEventsJson(attempt) {{
      attempt = attempt || 1;
      return fetch('events.json').then(function (r) {{
        if (!r.ok) throw new Error('events.json HTTP ' + r.status);
        return r.json();
      }}).catch(function (err) {{
        if (attempt >= 3) throw err;
        return new Promise(function (res) {{ setTimeout(res, attempt * 1500); }})
          .then(function () {{ return fetchEventsJson(attempt + 1); }});
      }});
    }}
    // Never leave the grid blank: paint a visible error + keep retrying with
    // escalating backoff (5s → 60s cap) until a load succeeds.
    var _opsRetryTimer = null, _opsRetryDelay = 5000;
    function showOpsLoadError(email, err) {{
      var msg = (err && err.message) ? String(err.message) : 'network error';
      // A re-render failure with cards already on screen keeps the old cards —
      // stale data beats a wiped grid.
      if ($opsGrid.querySelector('.ops-card')) {{
        status('Refresh failed (' + msg + ') — showing the last loaded data.', 'error');
        return;
      }}
      var delay = _opsRetryDelay;
      _opsRetryDelay = Math.min(delay * 2, 60000);
      $opsGrid.innerHTML =
        '<div class="ops-load-error">' +
          '<p><strong>Couldn&rsquo;t load the events.</strong> Usually a brief network or deploy hiccup (' + escapeHtml(msg) + ').</p>' +
          '<p>Retrying automatically in ' + Math.round(delay / 1000) + 's&hellip; ' +
          '<button type="button" class="q-btn primary" id="ops-retry-now">Retry now</button></p>' +
        '</div>';
      var btn = document.getElementById('ops-retry-now');
      if (btn) btn.addEventListener('click', function () {{ clearTimeout(_opsRetryTimer); renderOps(email); }});
      clearTimeout(_opsRetryTimer);
      _opsRetryTimer = setTimeout(function () {{ renderOps(email); }}, delay);
    }}
    // Live tracking (Supabase) failed but the catalog loaded: warn loudly —
    // cards silently losing their stages/attendees reads as data loss.
    function showSbDegraded(errObj, email) {{
      var host = document.getElementById('ops-sb-warning');
      if (!errObj) {{ if (host) host.remove(); return; }}
      if (!host) {{
        host = document.createElement('div');
        host.id = 'ops-sb-warning';
        host.className = 'ops-sb-warning';
        $opsGrid.parentNode.insertBefore(host, $opsGrid);
      }}
      host.innerHTML = '&#9888; Live tracking data couldn&rsquo;t load (' + escapeHtml(errObj.message || String(errObj)) + '). ' +
        'Cards show catalog info only — stages, attendees and edits reappear when it reconnects. ' +
        '<button type="button" class="q-btn" id="ops-sb-retry">Retry now</button>';
      var b = document.getElementById('ops-sb-retry');
      if (b) b.addEventListener('click', function () {{ renderOps(email); }});
      clearTimeout(_opsRetryTimer);
      _opsRetryTimer = setTimeout(function () {{ renderOps(email); }}, 30000);
    }}
    // Safety net: ANY unhandled async failure while the grid is still empty
    // paints the retry card instead of stranding "Loading events…" forever.
    window.addEventListener('unhandledrejection', function (e) {{
      if ($opsGrid && !$opsGrid.querySelector('.ops-card') && !$opsGrid.querySelector('.ops-load-error')) {{
        showOpsLoadError(getCollabName() || 'Team', (e && e.reason) || {{}});
      }}
    }});

    // Tracking-richness score — when two cards are the same event, keep the one
    // carrying the most pipeline/attendee data (so a bare scraped dupe loses to
    // the tracked record). Catalog wins ties (it's the curated source).
    function _trackScore(c) {{
      var r = c._modalRec || {{}};
      var s = (r.stage_tags || []).length * 3;
      if (r.speaker) s += 2;
      if (r.attendees && r.attendees.length) s += 2;
      if (r.interested && r.interested.length) s += 2;
      if (r.attend_verdict) s += 1;
      if (r.saved) s += 2;
      if (r.decision) s += 2;
      if (r.notes) s += 1;
      if (c.dataset.eventNum) s += 0.5;   // prefer catalog on a tie
      return s;
    }}
    // De-duplicate the grid: the scraper sometimes lands a 2nd card for an event
    // already tracked (Angela keeps finding "doubles"). Group by the fuzzy
    // name+city+year key, keep the richest card, mark the rest dupHidden so they
    // drop out of the grid, count, calendar-view + filters. Non-destructive
    // (nothing deleted; a re-render re-evaluates from fresh data).
    // ── Follow-up log ────────────────────────────────────────────────
    // Angela's spreadsheet column ("6/24, 7/20") as real data. Each entry is
    // {{on, by, note}}. Everything about WHEN to chase again is derived, never
    // stored, so it can't go stale when a note changes (Hurley 2026-07-30).
    var FOLLOW_UP_DAYS = 14;
    // A fortnight's silence is fine three months out and useless three weeks
    // out — the cadence tightens as the event approaches (Hurley 2026-07-30).
    var FOLLOW_UP_NEAR_DAYS = 7, FOLLOW_UP_IMMINENT_DAYS = 3;
    function _fuStartIso(o) {{
      var v = (o && (o.start_date || o.startObj && o.startObj.start_date)) || '';
      v = String(v).slice(0, 10);
      return /^\d{{4}}-\d{{2}}-\d{{2}}$/.test(v) ? v : null;
    }}
    function _fuDaysToEvent(o, today) {{
      var iso = _fuStartIso(o);
      return iso ? _fuDaysSince(today, iso) : null;      // negative once it's past
    }}
    // How long we let silence run before it counts as due.
    function followUpEvery(o, today) {{
      var d = _fuDaysToEvent(o, today);
      if (d == null || d < 0) return FOLLOW_UP_DAYS;
      if (d <= 10) return FOLLOW_UP_IMMINENT_DAYS;
      if (d <= 35) return FOLLOW_UP_NEAR_DAYS;
      return FOLLOW_UP_DAYS;
    }}
    function followUps(o) {{
      var v = (o && o.follow_ups) || [];
      if (typeof v === 'string') {{ try {{ v = JSON.parse(v); }} catch (e) {{ v = []; }} }}
      if (!Array.isArray(v)) return [];
      return v.filter(Boolean).slice().sort(function (a2, b2) {{
        return String(a2.on || '') < String(b2.on || '') ? 1 : -1;   // newest first
      }});
    }}
    function lastFollowUp(o) {{
      var f = followUps(o);
      return f.length ? f[0] : null;
    }}
    // A door that is shut needs no chasing. Both signals already exist — a
    // Rejected stage, or a workflow_status the taxonomy files under "Closed"
    // (that's where "Sponsorship Only" lives) — so no new column.
    // "Door closed" meant nothing to anyone reading it (Hurley 2026-07-30), so
    // the reason travels with the fact: the badge says WHY we're not chasing.
    function doorClosedWhy(o, stages) {{
      if ((stages || []).indexOf('Rejected') !== -1) return 'they said no';
      var ws = String((o && o.workflow_status) || '').trim();
      if (!ws || ws === '__deleted__') return '';
      var shut = (STATUS_GROUP_BY_KEY[ws] === 'Closed') ||
                 /sponsorship only|declin|not accepting|no opening|passed on us/i.test(ws);
      if (!shut) return '';
      if (/sponsorship only/i.test(ws)) return 'paid slots only';
      if (/declin|passed on us/i.test(ws)) return 'they said no';
      if (/not accepting|no opening/i.test(ws)) return 'not taking speakers';
      return ws.toLowerCase();
    }}
    function doorClosed(o, stages) {{ return !!doorClosedWhy(o, stages); }}
    var _FU_MONTHS = {{ january:1, february:2, march:3, april:4, may:5, june:6, july:7,
      august:8, september:9, october:10, november:11, december:12,
      jan:1, feb:2, mar:3, apr:4, jun:6, jul:7, aug:8, sep:9, sept:9, oct:10, nov:11, dec:12 }};
    // "unless she says something" — read her own words before nagging her.
    // Returns {{ hold:true, until, why }} when the notes say to wait.
    // A bare month name is almost always the EVENT'S OWN DATE restated in the
    // notes ("(Sep 9-10)", "Postponed from April 13 to Aug 31", a URL slug
    // ".../assembly-august-2026/", "Wave 1 acceptances: Aug 15") — or the plain
    // English word "may" ("Thor may not attend"). Treating any of those as
    // "wait until then" silences the follow-up nudge on events that need
    // chasing most, which is exactly what it did (Hurley 2026-07-30). A month
    // now only means WAIT when a phrase in front of it says so.
    var _FU_WAIT_LEAD = '(?:until|till|back (?:to us )?in|come[sn]? back in|'
      + 'reach(?:ing)? out in|be in touch in|hear(?:ing)? (?:back )?in|'
      + 'decisions? in|deciding in|review(?:ing)? in|announce(?:d|ment)?s? in|'
      + 'opens? (?:again )?in|not before|revisit in|circle back in|'
      + 'follow(?:ing)? up in|check back in|try again in|resubmit in|reapply in)';
    var _FU_MONTH_ALT = '(january|february|march|april|may|june|july|august|september|october|' +
      'november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)';
    function followUpHold(text) {{
      var t = String(text || '').toLowerCase();
      if (!t.trim()) return null;
      // An explicit "they'll come back / we're waiting" state.
      // PERMANENT dead end: they've told us not to chase. A form submission
      // answered only if you're picked is never worth a nudge, so time never
      // releases this one.
      var never = /(only\s+(reach\s+out|contact|be\s+in\s+touch)\s+if|if\s+(you.?re\s+)?(selected|chosen|successful)|do\s+not\s+contact|no\s+need\s+to\s+follow)/.test(t);
      // SOFT wait: the ball is with them for now, but not forever — after a
      // month it's fair to nudge again.
      var waiting = /(will|they.?ll|we.?ll|is|are)\s+(be\s+in\s+touch|reach\s+out|come\s+back|let\s+us\s+know|follow\s+up|connect|connecting|introduc|keep\s+(you|us)\s+(in\s+the\s+loop|posted))/.test(t)
                 || /(keep\s+(you|us)\s+in\s+the\s+loop|on\s+hold|waiting\s+on|awaiting|have\s+everything\s+(they|we)\s+need|going\s+through\s+applications)/.test(t);
      // A named future month, but ONLY behind a phrase that means waiting —
      // "back to us in September", "decisions in October", "not before March".
      var until = null;
      var today = (window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10));
      // Links carry month names in their slugs; they are never a promise.
      var tw = t.replace(/https?:\/\/\S+/g, ' ')
                .replace(/\S+\.(?:com|org|net|io|ai|co)\S*/g, ' ')
                .replace(/[\s\u00a0]+/g, ' ');
      var re = new RegExp(_FU_WAIT_LEAD + ' ' + _FU_MONTH_ALT + '(?![a-z])', 'g');
      var yr = parseInt(today.slice(0, 4), 10), mo = parseInt(today.slice(5, 7), 10);
      var hit;
      while ((hit = re.exec(tw)) !== null) {{
        var n = _FU_MONTHS[hit[1]]; if (!n) continue;
        var y = n >= mo ? yr : yr + 1;                        // next occurrence
        var iso = y + '-' + String(n).padStart(2, '0') + '-01';
        if (iso > today && (!until || iso < until)) until = iso;
      }}
      if (never) return {{ hold: true, until: null, permanent: true, why: 'they contact us' }};
      if (until) return {{ hold: true, until: until, why: 'their timing' }};
      if (waiting) return {{ hold: true, until: null, why: 'waiting on them' }};
      return null;
    }}
    // Events run by the SAME outfit share a follow-up. Chasing Ciara once
    // shouldn't leave four other Web Summit events nagging (Hurley 2026-07-30).
    var _fuByOrg = null;
    function _fuOrgKey(o) {{
      var d = _urlOrg((o && (o.url || (o.startObj && o.startObj.url))) || '');
      return d ? 'd:' + d : '';
    }}
    function _buildFollowUpOrgIndex() {{
      var idx = {{}};
      opsAllItems().forEach(function (it) {{
        var k = _fuOrgKey(it.startObj || it); if (!k) return;
        var f = lastFollowUp(it.startObj || it); if (!f || !f.on) return;
        if (!idx[k] || String(f.on) > String(idx[k].on)) idx[k] = {{ on: f.on, name: it.name }};
      }});
      _fuByOrg = idx;
      return idx;
    }}
    // THE state machine. One of:
    //   closed   - door shut, never chase
    //   hold     - her notes say wait (until a date, or on them)
    //   none     - nothing logged yet
    //   ok       - chased recently
    //   due      - 14+ days since the last chase
    function followUpState(o, stages, extraNotes) {{
      var shutWhy = doorClosedWhy(o, stages);
      if (shutWhy) return {{ state: 'closed', label: 'Closed \u2014 ' + shutWhy }};
      var notes = [ (o && o.notes) || '', extraNotes || '' ].join(' ');
      var hold = followUpHold(notes);
      var today = (window.abTodayIso ? window.abTodayIso() : new Date().toISOString().slice(0, 10));
      var last = lastFollowUp(o);
      // However firm the wait, an event two weeks out overrides it: if we're
      // still not on the programme by then, waiting quietly is not a plan.
      var toEvent = _fuDaysToEvent(o, today);
      if (hold && toEvent != null && toEvent >= 0 && toEvent <= 14) hold = null;
      // Their timing beats our clock.
      if (hold && hold.until && hold.until > today) {{
        return {{ state: 'hold', until: hold.until, label: 'Waiting until ' + _fuNice(hold.until) }};
      }}
      // A permanent hold is never released by the passage of time.
      if (hold && hold.permanent) {{
        return {{ state: 'hold', permanent: true, label: 'No chase needed \u2014 they come back to us' }};
      }}
      // A soft wait expires after a month — then it's fair to nudge again.
      if (hold && !hold.until && (!last || _fuDaysSince(last.on, today) < 30)) {{
        return {{ state: 'hold', label: 'Waiting on them' }};
      }}
      var lastOn = last && last.on;
      // Anyone else chasing the same organiser counts.
      var org = _fuOrgKey(o);
      if (org) {{
        var shared = (_fuByOrg || _buildFollowUpOrgIndex())[org];
        if (shared && shared.on && (!lastOn || String(shared.on) > String(lastOn))) {{
          lastOn = shared.on;
        }}
      }}
      if (!lastOn) return {{ state: 'none', label: 'Not contacted yet' }};
      var days = _fuDaysSince(lastOn, today);
      if (days >= followUpEvery(o, today)) {{
        return {{ state: 'due', days: days, since: lastOn,
                 label: 'Follow up now \u2014 ' + days + ' days since ' + _fuNice(lastOn) }};
      }}
      return {{ state: 'ok', days: days, since: lastOn, label: 'Followed up ' + _fuNice(lastOn) }};
    }}
    function _fuDaysSince(iso, today) {{
      try {{
        var a2 = new Date(String(iso).slice(0, 10) + 'T00:00:00');
        var b2 = new Date(String(today).slice(0, 10) + 'T00:00:00');
        return Math.floor((b2 - a2) / 86400000);
      }} catch (e) {{ return 0; }}
    }}
    function _fuNice(iso) {{
      try {{
        return new Date(String(iso).slice(0, 10) + 'T00:00:00')
          .toLocaleDateString('en-US', {{ month: 'short', day: 'numeric' }});
      }} catch (e) {{ return String(iso || ''); }}
    }}
    window.abFollowUpState = followUpState;
    window.abFollowUps = followUps;

    // ── Scheduling conflicts ─────────────────────────────────────────
    // STATUS 2026-07-30: the MANUAL conflict_note path below is live and
    // renders. The automatic same-person/overlapping-date detection is
    // written but is NOT matching yet — clashesFor() returns [] against
    // real data even though a standalone pass over the same rows finds 99
    // pairs, so the item shape it reads is still wrong somewhere. Do not
    // treat the absence of a chip as 'no conflicts'.
    // Most of these are already implied by data we hold: the same person is
    // down for two events whose dates overlap. 99 such pairs exist right now
    // (Thor is on three separate things on 3 Nov), so this is detected rather
    // than typed (Hurley 2026-07-30). Angela can still record a conflict the
    // data can't see — a board meeting, a holiday — in `conflict_note`.
    //
    // Built ONCE per render into a person -> [event] index; doing it pairwise
    // per card would be ~700^2.
    var _clashIdx = null;
    // Only people who are actually COMMITTED — going, or booked to speak.
    // Overlapping APPLICATIONS are normal and expected: you apply to many
    // things and most don't land, so counting a submitted speaker as committed
    // made every submitted event clash with every other one (Hurley
    // 2026-07-30). Same rule as _travelRole(): an attendee, or the speaker on a
    // Booked event. Submitted / Followed up / Meeting held are NOT commitments.
    function _clashPeople(it) {{
      var out = {{}};
      (it.attendees || []).forEach(function (a) {{
        var f = abFold(a).split(/\s+/)[0]; if (f) out[f] = 1;
      }});
      var stages = it.stages || (it.startObj && it.startObj.stage_tags) || [];
      if (stages.indexOf && stages.indexOf('Booked') !== -1) {{
        String(it.speaker || '').split(/[,;/&]| and /).forEach(function (t) {{
          var f = abFold(t).split(/\s+/)[0]; if (f) out[f] = 1;
        }});
      }}
      return Object.keys(out);
    }}
    function _clashRange(it) {{
      // Use the SAME resolver the rest of the grid uses. Reading start_date off
      // the record directly worked for manual rows but silently returned null
      // for catalog ones — their dates live on the catalog entry, not the ops
      // record — so nothing ever matched (Hurley 2026-07-30).
      var s0 = null;
      try {{ s0 = eventStartIso(it) || eventStartIso(it.startObj || {{}}); }} catch (e) {{}}
      if (!s0 || !/^\d{{4}}-\d{{2}}-\d{{2}}/.test(String(s0))) return null;
      s0 = String(s0).slice(0, 10);
      var o = it.startObj || it;
      var e0 = o.end_date || it.end_date;
      e0 = (e0 && /^\d{{4}}-\d{{2}}-\d{{2}}/.test(String(e0))) ? String(e0).slice(0, 10) : s0;
      return [s0, e0 < s0 ? s0 : e0];
    }}
    function _buildClashIndex() {{
      var idx = {{}};
      opsAllItems().forEach(function (it) {{
        if (it.past || it.hidden) return;
        // Items carry a numeric `sort` key, not start_date — the same thing
        // _tripClusters() reads. Going via the record's start_date worked for
        // the card but left this index empty, so nothing ever matched.
        var sd = null, ed = null;
        try {{ sd = _sortToDate(it.sort); ed = _sortToDate(_endSortOf(it)); }} catch (e) {{}}
        if (!sd || isNaN(sd)) return;
        if (!ed || isNaN(ed)) ed = sd;
        var iso = function (d) {{
          return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') +
                 '-' + String(d.getDate()).padStart(2, '0');
        }};
        var s0 = iso(sd), e0 = iso(ed);
        if (e0 < s0) e0 = s0;
        _clashPeople(it).forEach(function (who) {{
          (idx[who] = idx[who] || []).push({{ key: it.kind + ':' + it.key, name: it.name, s: s0, e: e0 }});
        }});
      }});
      _clashIdx = idx;
      return idx;
    }}
    // [{{ who, name, s }}] — everyone double-booked against THIS event.
    function clashesFor(it) {{
      var r = _clashRange(it); if (!r) return [];
      var idx = _clashIdx || _buildClashIndex();
      var me = it.kind + ':' + it.key, out = [];
      var myName = abFold(it.name || '');
      _clashPeople(it).forEach(function (who) {{
        (idx[who] || []).forEach(function (o) {{
          // Exclude self by key AND by name: the synthetic item a card builds
          // doesn't always reproduce the index's kind:key, which is how "Ai4"
          // ended up listed as its own conflict (Hurley 2026-07-30).
          if (o.key === me) return;
          if (myName && abFold(o.name || '') === myName) return;
          if (r[0] <= o.e && o.s <= r[1]) out.push({{ who: who, name: o.name, s: o.s }});
        }});
      }});
      return out;
    }}
    // Angela sees every clash (she does the scheduling); everyone else sees
    // only the ones that are theirs to resolve.
    function visibleClashes(it) {{
      var all = clashesFor(it);
      if (!all.length) return [];
      if (isSupportPerson(getCollabName() || '')) return all;
      var me = abFold(getCollabName() || '').split(/\s+/)[0];
      return me ? all.filter(function (c) {{ return c.who === me; }}) : [];
    }}
    function clashLabel(list) {{
      if (!list.length) return '';
      var who = [];
      list.forEach(function (c) {{ if (who.indexOf(c.who) === -1) who.push(c.who); }});
      var cap = function (n) {{ return n.charAt(0).toUpperCase() + n.slice(1); }};
      var names = (window.abPlanOrder ? window.abPlanOrder(who) : who).map(cap);
      return names.join(' & ') + ' also on ' + escapeHtml(list[0].name) +
             (list.length > 1 ? ' +' + (list.length - 1) + ' more' : '');
    }}

    // ── Hover peek: the conversation + notes, without opening the card ──
    // One shared popover, not one per card (there are ~700). It is
    // pointer-events:none on purpose — you only ever READ it, so there is no
    // gap to cross and no way to lose it mid-move, which is what made the
    // Should-Attend menu fragile. Click the card for the full thing.
    var _peekEl = null, _peekTimer = null, _peekFor = null;
    function _peekNode() {{
      if (_peekEl) return _peekEl;
      _peekEl = document.createElement('div');
      _peekEl.className = 'card-peek';
      _peekEl.setAttribute('aria-hidden', 'true');
      document.body.appendChild(_peekEl);
      return _peekEl;
    }}
    function _peekHide() {{
      if (_peekTimer) {{ clearTimeout(_peekTimer); _peekTimer = null; }}
      _peekFor = null;
      if (_peekEl) _peekEl.classList.remove('on');
    }}
    // Fold text for comparison: case, punctuation and spacing don't count.
    function _peekFold(t) {{
      return String(t == null ? '' : t).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    }}
    // Something has to have HAPPENED here. A peek on an event nobody has
    // touched is noise, however many notes sit on it (Hurley 2026-07-30).
    var _PEEK_ACTIVE = ['Submitted', 'Followed up', 'Meeting held', 'Booked', 'Attending'];
    function _peekHasActivity(card) {{
      var r = card._modalRec || {{}};
      var tags = (card.dataset.statusTags || '').split('|').filter(Boolean);
      for (var i = 0; i < _PEEK_ACTIVE.length; i++) {{
        if (tags.indexOf(_PEEK_ACTIVE[i]) !== -1) return true;
      }}
      if ((card.dataset.attendeeNames || '').replace(/\|/g, '').trim()) return true;
      if ((r.outreach_assignees || []).length) return true;   // Angela asked someone to reach out
      return false;
    }}
    function _peekHtml(card) {{
      // Gate 1: has anything actually happened on this event?
      if (!_peekHasActivity(card)) return '';
      var rec = card._modalRec || {{}};
      var notes = String(rec.notes || '').trim();
      var ckEl = card.querySelector('.chat-count[data-chatkey]');
      var ck = ckEl ? ckEl.getAttribute('data-chatkey') : null;
      var meta = (ck && _chatMeta[ck]) || null;
      var msgs = (meta && meta.msgs ? meta.msgs.slice() : []);
      msgs.sort(function (a2, b2) {{ return (a2.at || '') < (b2.at || '') ? 1 : -1; }});
      msgs = msgs.slice(0, 3);

      // Gate 2: and is there anything to SAY — a note or a message?
      if (!notes && !msgs.length) return '';

      // Don't print the same sentence twice. When a note and a message say the
      // same thing, keep the CONVERSATION — it carries who said it and when,
      // which the bare note doesn't (Hurley 2026-07-30).
      var fNote = _peekFold(notes);
      var noteCovered = false;
      if (fNote) {{
        msgs.forEach(function (m) {{
          var fm = _peekFold(m.body);
          // Directional on purpose: the note is redundant only when a MESSAGE
          // already contains it. If the NOTE is the fuller one, keep the note
          // and drop the message instead (below) — otherwise we'd throw away
          // the detail and keep the shorter line.
          if (fm && fm.indexOf(fNote) !== -1) noteCovered = true;
        }});
      }}
      // And drop a message the note already states verbatim (the other way round).
      if (fNote && !noteCovered) {{
        msgs = msgs.filter(function (m) {{
          var fm = _peekFold(m.body);
          return !(fm && fNote.indexOf(fm) !== -1);
        }});
      }}
      if (!notes && !msgs.length) return '';

      var h = '';
      if (msgs.length) {{
        h += '<div class="peek-sec"><span class="peek-h">Conversation</span>';
        msgs.forEach(function (m) {{
          h += '<div class="peek-msg"><span class="peek-who">' + escapeHtml(String(m.author || 'Someone').split(/\s+/)[0]) +
               '</span><span class="peek-when">' + escapeHtml(_relTime(m.at)) + '</span>' +
               '<div class="peek-body">' + escapeHtml(m.body || '') + '</div></div>';
        }});
        if (meta && meta.count > msgs.length) {{
          h += '<div class="peek-more">+' + (meta.count - msgs.length) + ' more</div>';
        }}
        h += '</div>';
      }}
      if (notes && !noteCovered) {{
        h += '<div class="peek-sec"><span class="peek-h">Notes</span>' +
             '<div class="peek-notes">' + escapeHtml(notes) + '</div></div>';
      }}
      if (!h) return '';
      h += '<div class="peek-cta">Click the card to open it</div>';
      var _pk = card.dataset.clash || '';
      if (_pk) h = '<div class="peek-clash">&#9888; ' + _pk + '</div>' + h;
      var _pcn = String(rec.conflict_note || '').trim();
      if (_pcn) h = '<div class="peek-clash">&#9888; ' + escapeHtml(_pcn) + '</div>' + h;
      return h;
    }}
    function _peekShow(card) {{
      var html = _peekHtml(card);
      if (!html) return;
      var el = _peekNode();
      el.innerHTML = html;
      el.classList.add('on');
      // Place it beside the card, flipping to the left / above when it would
      // otherwise run off the viewport.
      var r = card.getBoundingClientRect();
      var w = el.offsetWidth, h = el.offsetHeight;
      var left = r.right + 12;
      if (left + w > window.innerWidth - 8) left = Math.max(8, r.left - w - 12);
      var top = r.top;
      if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
      el.style.left = Math.round(left) + 'px';
      el.style.top  = Math.round(top) + 'px';
    }}
    function wireCardPeek() {{
      if (!$opsGrid || $opsGrid.dataset.peekWired) return;
      $opsGrid.dataset.peekWired = '1';
      $opsGrid.addEventListener('mouseover', function (e) {{
        var card = e.target.closest ? e.target.closest('.ops-card') : null;
        if (!card || card === _peekFor) return;
        _peekHide();
        _peekFor = card;
        // A short delay so sweeping the pointer across the grid doesn't strobe.
        _peekTimer = setTimeout(function () {{ if (_peekFor === card) _peekShow(card); }}, 320);
      }});
      $opsGrid.addEventListener('mouseout', function (e) {{
        var to = e.relatedTarget;
        if (to && to.closest && to.closest('.ops-card') === _peekFor) return;
        _peekHide();
      }});
      window.addEventListener('scroll', _peekHide, true);
      $opsGrid.addEventListener('click', _peekHide);
    }}

    function dedupeOpsCards() {{
      if (!$opsGrid) return 0;
      // Reviewing / revealing possible duplicates is Angela's job — for everyone
      // else duplicates stay collapsed, no matter what (covers switching away
      // from Angela's name mid-session with the reveal still on).
      if (!(window.isAngelaUser && window.isAngelaUser())) {{
        _reviewDupes = false;
        document.body.classList.remove('review-dupes');
      }}
      var groups = {{}};
      Array.prototype.forEach.call($opsGrid.querySelectorAll('.ops-card'), function (c) {{
        c.dataset.dupHidden = '';
        c.dataset.dupKeeper = '';
        c.dataset.dupMaybe = '';
        c.dataset.dupGroup = '';
        c.classList.remove('is-dupe');
        var k = dupKeyOf(c._modalRec || {{}});
        if (k) (groups[k] = groups[k] || []).push(c);
      }});
      var hidden = 0;
      Object.keys(groups).forEach(function (k) {{
        var g = groups[k];
        if (g.length < 2) return;
        g.sort(function (a, b) {{ return _trackScore(b) - _trackScore(a); }});
        // Mark the duplicate cards (keep the richest). Hidden by default; the
        // "Review duplicates" toggle reveals them (marked) so they can be deleted.
        // Tag the KEEPER too, and stamp the group id on every card in it, so
        // "Review duplicates" can show each dupe next to the event it duplicates
        // (Angela needs to compare the pair before deleting one).
        g[0].dataset.dupKeeper = '1'; g[0].dataset.dupGroup = k;
        for (var i = 1; i < g.length; i++) {{ g[i].dataset.dupHidden = '1'; g[i].dataset.dupGroup = k; g[i].classList.add('is-dupe'); if (!_reviewDupes) g[i].style.display = 'none'; hidden++; }}
      }});
      // ── Pass 2 — title VARIATIONS the exact key misses ────────────────
      // Same start DATE + same CITY, where one event's distinctive words are a
      // subset of the other's (e.g. "AI in Finance Summit Chicago" vs "RE·WORK
      // AI in Finance Summit Chicago", or a "Gartner …"/"IDC …" organiser
      // prefix). Guarded so genuinely different same-day/city events
      // (CDO vs CAIO Summit) stay separate: needs a shared, specific topic.
      var DUP_GENERIC = {{ summit:1, conference:1, conf:1, forum:1, expo:1, exposition:1, congress:1, symposium:1, festival:1, event:1, meeting:1, week:1, day:1, days:1, the:1, an:1, of:1, for:1, to:1, and:1, in:1, on:1, at:1, by:1, with:1, annual:1, edition:1, series:1, national:1,
        // region words — so "… UK" / "… Europe" / "… EMEA" reduce to the same core.
        uk:1, europe:1, european:1, emea:1, emeia:1, apac:1, americas:1, america:1, mena:1, latam:1, international:1, global:1, worldwide:1 }};
      function _topicSig(o) {{
        var cityToks = {{}}; dupCityOf(o).split(' ').forEach(function (t) {{ if (t) cityToks[t] = 1; }});
        var set = {{}}, n = 0;
        dupNameCore(o.name || '').split(' ').forEach(function (t) {{
          if (t && !DUP_GENERIC[t] && !cityToks[t] && !set[t]) {{ set[t] = 1; n++; }}
        }});
        return {{ set: set, size: n }};
      }}
      function _topicRelated(a, b) {{
        if (a.size < 2 || b.size < 2) return false;   // need a specific shared topic
        var sm = a.size <= b.size ? a : b, lg = a.size <= b.size ? b : a;
        for (var t in sm.set) {{ if (!lg.set[t]) return false; }}
        return true;                                  // smaller topic fully inside larger
      }}
      // ── The event link decides who's actually running an event ──────────
      // Passes 2 and 3 pair events on TITLE SHAPE, which is exactly where a
      // guess goes wrong. The link settles it: two similar-looking events on
      // different companies' domains are different events (Hurley 2026-07-29).
      // A missing link on either side tells us nothing, so the title rules then
      // stand on their own, unchanged.
      function _dupDom(o) {{ return _urlOrg((o && o.url) || ''); }}
      function _domsConflict(a, b) {{ return !!a && !!b && a !== b; }}
      function _domsAgree(a, b) {{ return !!a && !!b && a === b; }}
      var dcGroups = {{}};
      Array.prototype.forEach.call($opsGrid.querySelectorAll('.ops-card'), function (c) {{
        if (c.dataset.dupHidden === '1') return;      // already hidden by pass 1
        var sortk = c.dataset.sort || '';
        if (!sortk || sortk === '99999999') return;   // undated -> can't date-match
        var city = dupCityOf(c._modalRec || {{}});
        if (!city) return;
        var key = sortk + '|' + city;
        (dcGroups[key] = dcGroups[key] || []).push(c);
      }});
      Object.keys(dcGroups).forEach(function (key) {{
        var g = dcGroups[key];
        if (g.length < 2) return;
        g.sort(function (a, b) {{ return _trackScore(b) - _trackScore(a); }});
        var keeper = g[0], sigK = _topicSig(keeper._modalRec || {{}}), merged = 0;
        var domK = _dupDom(keeper._modalRec || {{}});
        for (var i = 1; i < g.length; i++) {{
          if (g[i].dataset.dupHidden === '1') continue;
          // Different outfit -> a different event, however alike the titles read.
          if (_domsConflict(domK, _dupDom(g[i]._modalRec || {{}}))) continue;
          if (_topicRelated(sigK, _topicSig(g[i]._modalRec || {{}}))) {{
            g[i].dataset.dupHidden = '1'; g[i].dataset.dupGroup = key; g[i].classList.add('is-dupe'); if (!_reviewDupes) g[i].style.display = 'none'; hidden++; merged++;
            keeper.dataset.dupKeeper = '1'; keeper.dataset.dupGroup = key;
          }}
        }}
        // (Duplicates marked above; hidden unless "Review duplicates" is on.)
      }});

      // ── Pass 3 — LOOSE "possible duplicate" pass (review only) ────────
      // Passes 1 and 2 key on name-core+city+year / same-date+city+topic, so a
      // trailing qualifier defeats them: "Sibos" and "Sibos 2026 Miami" (same
      // dates, same city) never matched. This pass catches that shape — one
      // title's distinctive words being a SUBSET of the other's, on the same
      // date or in the same city.
      //
      // Crucially it only FLAGS. It never sets dupHidden and never hides a card,
      // because at this looseness it also pairs genuinely different events
      // ("IDC CIO Summit UK" vs "IDC AI & Data Summit UK"). Auto-hiding those
      // would lose real events; a human decides in the Review view instead.
      var _DUP_STOP = {{ the:1, a:1, an:1, and:1, of:1, for:1, to:1, in:1, on:1, at:1, by:1, with:1,
        summit:1, summits:1, conference:1, conferences:1, expo:1, forum:1, event:1, events:1,
        annual:1, edition:1, world:1, global:1, international:1 }};
      function _dupToks(name) {{
        var t = abFold(String(name || '')).replace(/\\b20\d\d\\b/g, ' ').replace(/[^a-z0-9]+/g, ' ');
        var out = {{}}, n = 0;
        t.split(' ').forEach(function (w) {{ if (w.length > 1 && !_DUP_STOP[w] && !out[w]) {{ out[w] = 1; n++; }} }});
        return {{ set: out, n: n }};
      }}
      var _maybe = 0;
      var _live = Array.prototype.filter.call($opsGrid.querySelectorAll('.ops-card'), function (c) {{
        return c.dataset.dupHidden !== '1';           // already handled by pass 1/2
      }});
      for (var pi = 0; pi < _live.length; pi++) {{
        for (var pj = pi + 1; pj < _live.length; pj++) {{
          var A = _live[pi], B = _live[pj];
          var ra = A._modalRec || {{}}, rb = B._modalRec || {{}};
          var ta = _dupToks(ra.name), tb = _dupToks(rb.name);
          if (!ta.n || !tb.n) continue;
          var domA = _dupDom(ra), domB = _dupDom(rb);
          // Different companies' sites -> not a pair. This is what stops the
          // loose pass from nagging about events that merely sound alike.
          if (_domsConflict(domA, domB)) continue;
          var shared = 0, kk;
          for (kk in ta.set) {{ if (tb.set[kk]) shared++; }}
          var sameDate = A.dataset.sort && A.dataset.sort !== '99999999' && A.dataset.sort === B.dataset.sort;
          var ca = dupCityOf(ra), cb = dupCityOf(rb);
          var sameCity = ca && ca === cb;
          var subset = (shared === Math.min(ta.n, tb.n));
          // Normally a full subset is required. But when both events sit on the
          // SAME company's domain on the same date, one distinctive shared word
          // is enough to be worth a look — that's the "HumanX Amsterdam" vs
          // "HumanX Europe" shape, which no subset rule can see. Flag-only, as
          // ever: siblings a single host runs side by side (CDAO Government vs
          // CDAO Defense) land here too, and a human decides.
          if (!subset && !(_domsAgree(domA, domB) && sameDate && shared >= 1)) continue;
          if (!sameDate && !sameCity) continue;
          var mk = 'maybe:' + [A.dataset.sort, ca, Object.keys(ta.set).sort().join('-')].join('|');
          [A, B].forEach(function (el) {{
            if (el.dataset.dupMaybe !== '1') {{ el.dataset.dupMaybe = '1'; _maybe++; }}
            if (!el.dataset.dupGroup) el.dataset.dupGroup = mk;
          }});
        }}
      }}

      // Drive the "Review duplicates" toggle in the results header.
      var _revBtn = document.getElementById('ops-dupe-review');
      if (_revBtn) {{
        if (!_revBtn.dataset.wired) {{
          _revBtn.dataset.wired = '1';
          _revBtn.addEventListener('click', function () {{
            _reviewDupes = !_reviewDupes;
            document.body.classList.toggle('review-dupes', _reviewDupes);
            dedupeOpsCards(); regroupOpsByMonth(); applyFilters();
            if (_reviewDupes) window.scrollTo({{ top: 0, behavior: 'smooth' }});
          }});
        }}
        // Angela-only: only she can review/delete duplicates, so only she sees
        // the toggle. Everyone else just gets the clean, deduped grid.
        var _revTotal = hidden + _maybe;
        _revBtn.hidden = (_revTotal === 0) || !(window.isAngelaUser && window.isAngelaUser());
        _revBtn.textContent = _reviewDupes
          ? '\\u2715 Done \\u00b7 hide duplicates again'
          : ('Review ' + _revTotal + ' possible duplicate' + (_revTotal === 1 ? '' : 's'));
        // Nudge every 3 days so the pile doesn't quietly grow: if it's been that
        // long since duplicates were last reviewed, the button goes red.
        var _dupSeenKey = 'ab.dupseen.' + (getCollabName() || '').toLowerCase();
        var _lastSeen = 0;
        try {{ _lastSeen = parseInt(localStorage.getItem(_dupSeenKey) || '0', 10) || 0; }} catch (e) {{}}
        var _stale = (Date.now() - _lastSeen) > 3 * 86400000;
        _revBtn.classList.toggle('due', _stale && !_reviewDupes && _revTotal > 0);
        if (_reviewDupes) {{ try {{ localStorage.setItem(_dupSeenKey, String(Date.now())); }} catch (e) {{}} }}
      }}
      return hidden;
    }}

    function renderOps(email) {{
      // Keep the reader's place across a re-render. A manual save AND the
      // realtime postgres_changes echo both call renderOps(); without this the
      // grid is wiped and the page snaps back to the top, so you "lose" the
      // event you were just editing. Capture the scroll position + which card's
      // editor is open, then restore both once the fresh grid is built.
      var _prevScrollY = window.scrollY || window.pageYOffset || 0;
      // Carry any open toolbar panel (Add form / Find events / Calendar sync /
      // Spreadsheet) across the rebuild — re-inserting the SAME node keeps its
      // listeners and any half-typed input. Without this, the initial data
      // load (or a teammate's edit) silently wiped an open panel.
      var _panel = $opsGrid.querySelector(':scope > .add-event-card');
      var _openKey = null;
      var _openEd = $opsGrid.querySelector('.ops-card > details.ops-edit[open]');
      if (_openEd) {{
        var _oc = _openEd.closest('.ops-card');
        if (_oc) _openKey = _oc.dataset.manualId
          ? ('m' + _oc.dataset.manualId)
          : (_oc.dataset.eventNum ? ('e' + _oc.dataset.eventNum) : null);
      }}
      // Only paint the "Loading…" placeholder on the first render. On a
      // re-render, leave the current cards in place (no flash) until fresh
      // data arrives and we swap them out below.
      if (!$opsGrid.querySelector('.ops-card')) {{
        $opsGrid.innerHTML = '<p style="grid-column:1/-1;color:var(--ab-fg-3);font-size:0.9rem;">Loading events…</p>';
      }}
      return Promise.all([
        fetchEventsJson(),
        sb.from('event_state').select('*'),
        sb.from('manual_events').select('*').order('created_at', {{ ascending: false }})
      ]).then(function (results) {{
        var data = results[0];
        var stateRows = (results[1] && results[1].data) || [];
        var manualRows = (results[2] && results[2].data) || [];
        // Healthy catalog load: cancel any pending failure-retry + reset backoff.
        clearTimeout(_opsRetryTimer);
        _opsRetryDelay = 5000;
        // Supabase erroring while events.json succeeds = cards silently losing
        // all their tracking. Banner + auto-retry instead of silence.
        showSbDegraded((results[1] && results[1].error) || (results[2] && results[2].error), email);
        // Soft-deleted catalog events carry a '__deleted__' sentinel on their
        // event_state row. Drop them EVERYWHERE — grid, stats, calendar, queue,
        // planner — by excluding both the catalog event AND its state row, so a
        // delete truly removes it from the pipeline (not just hides the card).
        var _deletedNums = {{}};
        stateRows.forEach(function (r) {{ if (r.status === '__deleted__') _deletedNums[r.event_num] = true; }});
        stateRows = stateRows.filter(function (r) {{ return r.status !== '__deleted__'; }});
        var stateMap = {{}};
        stateRows.forEach(function (r) {{ stateMap[r.event_num] = r; }});

        // Include archived (past) catalog events too, so they stay reachable in
        // the collapsible "Archive · past events" group. Stats / calendar /
        // queue / planner keep using `evs` (non-archived) so past events don't
        // inflate counts or surface as false scheduling conflicts.
        var allEvs = (data.events || []).filter(function (e) {{ return !_deletedNums[e.num]; }});
        var evs = allEvs.filter(function (e) {{ return e.status !== 'archived'; }});
        // Catalog events are now fully editable: event_state can override the
        // identity fields (name / date_str / start_date / end_date / location).
        // Apply the override in place BEFORE anything renders, so the edited value
        // wins over the catalog value everywhere downstream — grid card, Details,
        // calendar, map, search + suggestions all read these merged events. A
        // no-op until the 2026-07-14_event_state_identity migration adds the
        // columns (the fields just come back undefined).
        allEvs.forEach(function (e) {{
          var st = stateMap[e.num]; if (!st) return;
          if (st.name != null && String(st.name).trim() !== '') e.name = st.name;
          // Clear the parsed city/country so shortLocation() shows the edited
          // location text (it prefers city+country over the raw location).
          if (st.location != null && String(st.location).trim() !== '') {{ e.location = st.location; e.city = ''; e.country = ''; }}
          if (st.date_str != null && String(st.date_str).trim() !== '') e.date_str = st.date_str;
          if (st.start_date) e.start_date = st.start_date;
          if (st.end_date) e.end_date = st.end_date;
        }});
        // Trailing-year strip for display — the year is redundant with the date.
        allEvs.forEach(function (e) {{ if (e && e.name) e.name = stripTrailingYear(e.name); }});
        manualRows.forEach(function (m) {{ if (m && m.name) m.name = stripTrailingYear(m.name); }});
        $opsGrid.innerHTML = '';
        allEvs.forEach(function (ev) {{
          var card = buildOpsCard(ev, stateMap[ev.num] || {{}}, email);
          $opsGrid.appendChild(card);
          wireOpsCard(card, email);
        }});
        manualRows.forEach(function (mev) {{
          var card = buildManualCard(mev, email);
          $opsGrid.appendChild(card);
          wireManualCard(card, email);
        }});
        updateOpsCount();
        renderStats(evs, stateRows, manualRows);
        rebuildSpeakerFilter(stateRows, manualRows);
        dedupeOpsCards();   // collapse scraped duplicate cards before layout
        regroupOpsByMonth();
        applyFilters();
        loadChatCounts();   // fill the little "💬 N" chat badges on the cards
        // Rebuild the dedup index from this fresh fetch — realtime
        // events from other tabs / sessions land here, so we want every
        // re-render to refresh _knownNames too.
        _knownNameSource = {{}}; _knownKeys = {{}};
        (data.events || []).forEach(function (e) {{ var n = (e.name || '').toLowerCase().trim(); if (n) _knownNameSource[n] = 'catalog'; var k = dupKeyOf(e); if (k && !_knownKeys[k]) _knownKeys[k] = 'catalog'; }});
        manualRows.forEach(function (m) {{ var n = (m.name || '').toLowerCase().trim(); if (n) _knownNameSource[n] = 'manual:' + m.id; var k = dupKeyOf(m); if (k) _knownKeys[k] = 'manual:' + m.id; }});
        _knownNames = Object.keys(_knownNameSource);
        // Mirror into the calendar view (uses the same data set)
        renderCalendar(evs, stateMap, manualRows);
        // Cache for the Queue + Planner views; refresh whichever is active plus
        // the tab-count badges (so flagging / conflicts update live).
        _lastEvs = evs; _lastStateMap = stateMap; _lastStateRows = stateRows; _lastManual = manualRows;
        if (currentView === 'myevents') renderMyEvents();
        else if (currentView === 'queue') renderQueue();
        else if (currentView === 'planner') renderPlanner();
        updateViewBadges();
        // Fold everyone's My-Profile text into the taste cache once (bio /
        // topics / past talks / notes make suggestions more tailored), then
        // refresh the suggestion surfaces so they reflect it.
        if (_profileTasteCache === null) {{
          _loadProfileTaste(function () {{
            if (currentView === 'myevents') renderMyEvents();
          }});
        }}
        // And the map, when it's the active view (realtime echo / saves).
        if (currentView === 'map' && _opsMapLayer) renderOpsMap();
        // Put the reader back where they were (captured at the top): re-open
        // the editor they had open and restore the scroll position so a save
        // or realtime echo no longer snaps them to the top of the list.
        if (_openKey) {{
          var _sel = _openKey.charAt(0) === 'm'
            ? '.ops-card[data-manual-id="' + _openKey.slice(1) + '"]'
            : '.ops-card[data-event-num="' + _openKey.slice(1) + '"]';
          var _again = $opsGrid.querySelector(_sel);
          if (_again) {{
            var _ed2 = _again.querySelector('details.ops-edit');
            if (_ed2) _ed2.open = true;
          }}
        }}
        // Re-seat the open toolbar panel (detached by the rebuild above).
        if (_panel) $opsGrid.insertBefore(_panel, $opsGrid.firstChild);
        window.scrollTo(0, _prevScrollY);
      }}).catch(function (err) {{
        // Fetch failed after retries, OR the render itself threw mid-build —
        // either way, never leave a silent blank grid: show + auto-retry.
        showOpsLoadError(email, err);
      }});
    }}

    // ── Email → event-fields extractor ─────────────────────────────
    function extractFromEmail(text) {{
      var out = {{}};
      text = text || '';
      // URL — first plausible https?:// link, skip common boilerplate
      var urlRe = /https?:\/\/[^\s<>"'\]\)]+/g;
      var urls = text.match(urlRe) || [];
      var skipPat = /unsubscribe|privacy|terms-of-service|googleusercontent|track\.|click\.|notifications?\./i;
      var good = null;
      for (var i = 0; i < urls.length; i++) {{
        if (!skipPat.test(urls[i])) {{ good = urls[i]; break; }}
      }}
      if (good) out.url = good.replace(/[.,;:>'\)]+$/, '');
      // Date — multiple formats, prefer ranges
      var months = 'January|February|March|April|May|June|July|August|September|October|November|December';
      var monthsShort = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec';
      var dateRes = [
        new RegExp('(?:' + months + ')\\\\s+\\\\d{{1,2}}\\\\s*[–—-]\\\\s*(?:(?:' + months + ')\\\\s+)?\\\\d{{1,2}},\\\\s+\\\\d{{4}}', 'i'),
        new RegExp('(?:' + months + ')\\\\s+\\\\d{{1,2}},\\\\s+\\\\d{{4}}', 'i'),
        new RegExp('(?:' + monthsShort + ')\\\\s+\\\\d{{1,2}}\\\\s*[–—-]\\\\s*\\\\d{{1,2}},\\\\s+\\\\d{{4}}', 'i'),
        new RegExp('(?:' + monthsShort + ')\\\\s+\\\\d{{1,2}},\\\\s+\\\\d{{4}}', 'i')
      ];
      for (var j = 0; j < dateRes.length; j++) {{
        var dm = text.match(dateRes[j]);
        if (dm) {{ out.date_str = dm[0]; break; }}
      }}
      // Name — Subject line first; else first reasonable line.
      // Strip Re:/Fwd: prefixes repeatedly to handle chains like "Fwd: Re: …"
      var subj = text.match(/^\s*Subject:\s*(.+)$/im);
      if (subj) {{
        var nm = subj[1].trim();
        while (/^(?:Re:|Fwd?:|FW:)\s*/i.test(nm)) {{
          nm = nm.replace(/^(?:Re:|Fwd?:|FW:)\s*/i, '');
        }}
        out.name = nm;
      }} else {{
        var lines = text.split(/\\r?\\n/).map(function (s) {{ return s.trim(); }}).filter(Boolean);
        for (var k = 0; k < lines.length; k++) {{
          var l = lines[k];
          if (l.length > 5 && l.length < 120 && !/^https?:/i.test(l) && !/^[\w.-]+@[\w.-]+/.test(l)) {{
            out.name = l; break;
          }}
        }}
      }}
      // Location — multi-tier fallback:
      //   1. "Location:" / "Where:" / "Venue:" keyword line (strongest)
      //   2. "City, Country" anchored at end of a standalone line
      //   3. "in <City>" prose (avoid "at" which falsely matches "speak at X")
      var lk = text.match(/^\s*(?:Location|Where|Venue|City)\s*:\s*(.+)$/im);
      if (lk) {{
        out.location = lk[1].trim();
      }} else {{
        var standalone = text.match(/([A-Z][a-zA-Z]+(?:[ \t]+[A-Z][a-zA-Z]+)?,[ \t]+[A-Z][a-zA-Z]+)[ \t]*$/m);
        if (standalone) {{
          out.location = standalone[1].trim();
        }} else {{
          var lc = text.match(/\\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?(?:,\s+[A-Z][a-zA-Z]+)?)/);
          if (lc) out.location = lc[1].trim();
        }}
      }}
      // Region guess from location
      if (out.location) {{
        var lo = out.location.toLowerCase();
        var _g = canonicalRegion({{ location: out.location }});
        if (_g && _g !== 'Global') out.region = _g;
      }}
      return out;
    }}

    // Apply extracted fields to the form (only fills empty inputs by default)
    // Click-to-open calendar popup for the Add-event date field. Supports a
    // single day OR a range: click one day (single), click a second later day
    // (range); a third click starts over. Writes the formatted date into the
    // text input AND stashes exact ISO start/end on its dataset (the submit
    // handler trusts those). The field is still free-text + flexibly parsed.
    function wireDatePicker(wrap) {{
      if (!wrap || wrap.dataset.wired) return;
      wrap.dataset.wired = '1';
      var input = wrap.querySelector('.date-flex-input');
      var pop = wrap.querySelector('.date-cal');
      if (!input || !pop) return;
      var MON = ['January','February','March','April','May','June','July','August','September','October','November','December'];
      var DOW = ['Su','Mo','Tu','We','Th','Fr','Sa'];
      var sel = {{ start: null, end: null }};
      var viewY, viewM;
      function pad(n) {{ return String(n).padStart(2, '0'); }}
      function isoOf(y, m0, d) {{ return y + '-' + pad(m0 + 1) + '-' + pad(d); }}
      function partsOf(iso) {{ var m = /^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})/.exec(iso || ''); return m ? {{ y: +m[1], mo: +m[2] - 1, d: +m[3] }} : null; }}
      function fmt(sIso, eIso) {{
        var s = partsOf(sIso); if (!s) return '';
        var e = partsOf(eIso), sM = MON[s.mo];
        if (!e || (e.y === s.y && e.mo === s.mo && e.d === s.d)) return sM + ' ' + s.d + ', ' + s.y;
        var eM = MON[e.mo];
        if (e.y === s.y && e.mo === s.mo) return sM + ' ' + s.d + '\\u2013' + e.d + ', ' + s.y;
        if (e.y === s.y) return sM + ' ' + s.d + ' \\u2013 ' + eM + ' ' + e.d + ', ' + s.y;
        return sM + ' ' + s.d + ', ' + s.y + ' \\u2013 ' + eM + ' ' + e.d + ', ' + e.y;
      }}
      function writeInput() {{
        if (!sel.start) return;
        var isRange = sel.end && sel.end !== sel.start;
        input.value = fmt(sel.start, isRange ? sel.end : null);
        input.setAttribute('data-start-iso', sel.start);
        input.setAttribute('data-end-iso', isRange ? sel.end : sel.start);
      }}
      function render() {{
        var startDow = new Date(viewY, viewM, 1).getDay();
        var daysIn = new Date(viewY, viewM + 1, 0).getDate();
        var html = '<div class="dc-head">' +
          '<button type="button" class="dc-nav" data-nav="-1" aria-label="Previous month">\\u2039</button>' +
          '<span class="dc-title">' + MON[viewM] + ' ' + viewY + '</span>' +
          '<button type="button" class="dc-nav" data-nav="1" aria-label="Next month">\\u203a</button>' +
          '</div><div class="dc-grid">';
        DOW.forEach(function (d) {{ html += '<span class="dc-dow">' + d + '</span>'; }});
        var i;
        for (i = 0; i < startDow; i++) html += '<span class="dc-day dc-empty"></span>';
        var isR = sel.start && sel.end && sel.start !== sel.end;
        for (var day = 1; day <= daysIn; day++) {{
          var iso = isoOf(viewY, viewM, day), cls = 'dc-day';
          if (isR) {{
            if (iso === sel.start) cls += ' dc-start';
            else if (iso === sel.end) cls += ' dc-end';
            else if (iso > sel.start && iso < sel.end) cls += ' dc-inrange';
          }} else if (sel.start && iso === sel.start) cls += ' dc-single';
          html += '<button type="button" class="' + cls + '" data-iso="' + iso + '">' + day + '</button>';
        }}
        html += '</div><div class="dc-foot"><button type="button" class="dc-clear">Clear</button>' +
          '<span class="dc-hint">One day, or click a 2nd for a range</span>' +
          '<button type="button" class="dc-done">Done</button></div>';
        pop.innerHTML = html;
      }}
      function openCal() {{
        sel = {{ start: null, end: null }};
        var ds = input.getAttribute('data-start-iso'), de = input.getAttribute('data-end-iso');
        if (ds) {{ sel.start = ds; sel.end = de || ds; }}
        else {{
          var t = (input.value || '').trim();
          if (t) {{ try {{ var d = deriveDatesFromText(t); if (d && d.start_date) {{ sel.start = d.start_date; sel.end = d.end_date || d.start_date; }} }} catch (e) {{}} }}
        }}
        var base = sel.start ? partsOf(sel.start) : null, now = new Date();
        viewY = base ? base.y : now.getFullYear();
        viewM = base ? base.mo : now.getMonth();
        render();
        pop.hidden = false;
      }}
      function closeCal() {{ pop.hidden = true; }}
      input.addEventListener('focus', openCal);
      input.addEventListener('click', openCal);
      input.addEventListener('input', function () {{ input.removeAttribute('data-start-iso'); input.removeAttribute('data-end-iso'); }});
      pop.addEventListener('mousedown', function (e) {{ e.preventDefault(); }});  // don't steal focus / blur-close the field
      pop.addEventListener('click', function (e) {{
        // Keep the click inside the popup: render() below replaces the popup's
        // innerHTML, which detaches the element you clicked (the ‹ / › arrow, a
        // day cell). Without this, the click bubbles to the document
        // "outside-click closes" handler, which then sees a now-detached target
        // that's no longer inside .date-pick and closes the calendar — so the
        // month arrows (and mid-range day picks) appeared to "close the picker".
        e.stopPropagation();
        var nav = e.target.closest('[data-nav]');
        if (nav) {{ viewM += parseInt(nav.getAttribute('data-nav'), 10); if (viewM < 0) {{ viewM = 11; viewY--; }} else if (viewM > 11) {{ viewM = 0; viewY++; }} render(); return; }}
        if (e.target.closest('.dc-clear')) {{ sel = {{ start: null, end: null }}; input.value = ''; input.removeAttribute('data-start-iso'); input.removeAttribute('data-end-iso'); render(); return; }}
        if (e.target.closest('.dc-done')) {{ closeCal(); return; }}
        var cell = e.target.closest('[data-iso]');
        if (cell) {{
          var iso = cell.getAttribute('data-iso');
          if (!sel.start || (sel.end && sel.start !== sel.end) || iso < sel.start) sel = {{ start: iso, end: iso }};
          else sel.end = iso;
          writeInput();
          render();
        }}
      }});
      document.addEventListener('click', function (e) {{ if (!wrap.contains(e.target)) closeCal(); }});
    }}

    function applyExtractToForm(form, extracted, opts) {{
      opts = opts || {{}};
      // Map every field the scraper can return — not just the basic 5. Selects
      // (region/type/priority/audience_type/pay_to_play) fill only if the value
      // matches an option; text fields always fill. Best-effort, never clobbers
      // a value the user already typed (overwrite:false).
      var keys = ['name', 'date_str', 'location', 'region', 'url', 'type',
        'priority', 'why', 'about', 'focus_areas', 'typical_attendees',
        'speaking_route', 'contact_info', 'audience_type', 'pay_to_play',
        'pricing', 'attendee_count', 'past_speakers', 'venue', 'deadline',
        'speaker', 'meeting_formats'];
      var filled = 0, skipped = 0;
      keys.forEach(function (k) {{
        var el = form.querySelector('[name="' + k + '"]');
        if (!el) return;
        if (!extracted[k]) return;
        if (el.value && !opts.overwrite) {{ skipped++; return; }}
        el.value = extracted[k];
        filled++;
        // The date field's calendar popup reads the input's ISO stash; a scraped
        // free-text date should fall back to flexible parsing, so clear the stash.
        if (k === 'date_str') {{ el.removeAttribute('data-start-iso'); el.removeAttribute('data-end-iso'); }}
      }});
      return {{ filled: filled, skipped: skipped, total: keys.filter(function (k) {{ return extracted[k]; }}).length }};
    }}

    function buildAddEventForm() {{
      var form = document.createElement('form');
      form.id = 'add-event-card';
      form.className = 'add-event-card ops-form';
      form.innerHTML =
        '<h3>New manual event</h3>' +
        '<details class="ops-edit" id="paste-email-section">' +
          '<summary>Or paste from email / web copy…</summary>' +
          '<div class="ops-form" style="margin-top:8px;">' +
            '<label><span class="key">Paste here</span>' +
              '<textarea id="paste-email-text" placeholder="Paste the full email / web listing TEXT — or just the event LINK (we\\u2019ll scrape the page). Auto-fills name, date, location, region, URL." style="min-height:120px;"></textarea>' +
            '</label>' +
            '<div class="add-actions">' +
              '<button type="button" class="primary" id="paste-extract-btn">Extract fields</button>' +
              '<button type="button" class="secondary" id="paste-clear-btn">Clear</button>' +
            '</div>' +
            '<p class="ops-meta" id="paste-extract-meta"></p>' +
          '</div>' +
        '</details>' +
        '<label><span class="key">URL — paste here to auto-fill ↓</span>' +
          '<div style="display:flex;gap:6px;align-items:stretch;">' +
            '<input type="text" name="url" placeholder="https://event-site.com" style="flex:1;">' +
            '<button type="button" class="primary" id="fill-from-url-btn" style="white-space:nowrap;padding:0 14px;font-size:0.85rem;">Fill from URL</button>' +
          '</div>' +
          '<p class="ops-meta" id="fill-from-url-meta" style="margin:6px 0 0;"></p>' +
        '</label>' +
        '<label><span class="key">Name *</span>' +
          '<input type="text" name="name" required placeholder="e.g. AI Summit San Francisco">' +
        '</label>' +
        '<label><span class="key">Date</span>' +
          '<div class="date-pick">' +
            '<input type="text" name="date_str" class="date-flex-input" autocomplete="off" placeholder="Type any date (e.g. Sept 12–14, 2026 · 9/12 · next single day), or click to pick">' +
            '<div class="date-cal" hidden></div>' +
          '</div>' +
        '</label>' +
        '<div class="row">' +
          '<label><span class="key">Location</span>' +
            '<input type="text" name="location" placeholder="City, Country">' +
          '</label>' +
          '<label><span class="key">Region</span>' +
            '<select name="region">' +
              optionRows(['', 'US & Canada', 'Latin America', 'Europe', 'Africa', 'MENA', 'Asia-Pacific', 'Global'], '') +
            '</select>' +
          '</label>' +
        '</div>' +
        '<div class="row">' +
          '<label><span class="key">Type</span>' +
            '<input type="text" name="type" placeholder="Enterprise, Halo, Research, …">' +
          '</label>' +
          '<label><span class="key">Priority</span>' +
            '<select name="priority">' +
              optionRows(['', 'High', 'Medium', 'Low'], 'Medium') +
            '</select>' +
          '</label>' +
        '</div>' +
        '<label><span class="key">ArcticBlue speaker</span>' +
          '<input type="text" name="speaker" list="ab-speakers" placeholder="Thor, Joe, Jerome, Scott, Verma, Carlos, Jim…">' +
        '</label>' +
        '<div class="ops-fieldset"><span class="key">Pipeline stages</span>' +
          stageCheckboxes([], 'status_tags') +
        '</div>' +
        '<details class="ops-edit"><summary>More details (About, Focus, Deadline, …)</summary>' +
          '<div class="ops-form" style="margin-top:8px;">' + richDetailFields({{}}) + '</div>' +
        '</details>' +
        '<div class="add-actions">' +
          '<button type="submit" class="primary">Add event</button>' +
          '<button type="button" class="secondary" data-cancel>Cancel</button>' +
        '</div>';
      return form;
    }}

    // Dedup index of every event name we know about — refreshed after
    // every insert/update/delete so it stays accurate. The catalog
    // (events.json) is loaded once; manual_events is reloaded each time.
    var _knownNames = null;          // Set of lowercased names
    var _knownNameSource = {{}};      // map: name_lower → 'catalog' | 'manual'
    var _knownKeys = {{}};            // map: fuzzy name+city+year key → source
    var _knownRec = {{}};             // map: name_lower / fuzzy key → {{name,location,date_str}} for clearer dup messages
    // Fuzzy duplicate key: reduce the name to its core (drop parentheticals like
    // "(IPT Edition)", the year, and punctuation), then pin to city + year. So
    // "AI Summit Brasil – Sao Paulo 2026" and "AI Summit Brasil — Sao Paulo
    // (IPT Edition)" collapse to the SAME key and are caught as one event.
    function dupNameCore(name) {{
      return abFold(name)
        // Common abbreviations, so "HR Tech" == "HR Technology" and
        // "AI …" == "Artificial Intelligence …".
        .replace(/\\bartificial intelligence\\b/g, 'ai')
        .replace(/\\btechnology\\b/g, 'tech')
        .replace(/\\bhuman resources\\b/g, 'hr')
        .replace(/\\(.*?\\)/g, ' ')                         // parentheticals
        .replace(/\\b20\\d\\d\\b/g, ' ')                     // years (city+year keyed separately)
        .replace(/(\\d)([a-z])/g, '$1 $2').replace(/([a-z])(\\d)/g, '$1 $2')  // money20 -> money 20
        .replace(/[^a-z0-9 ]/g, ' ')
        // strip generic region/edition words so "X USA" == "X North America" ==
        // "X" (the CITY in dupKeyOf still disambiguates real different editions).
        .replace(/\\b(usa|us|u s a|united states|na|north america|emea|apac|edition|series)\\b/g, ' ')
        .replace(/\\s+/g, ' ').trim();
    }}
    var _DUP_COUNTRIES = {{ usa:1, us:1, 'u s a':1, 'united states':1, america:1, uk:1, 'u k':1, 'united kingdom':1, england:1, scotland:1, wales:1, canada:1, germany:1, france:1, spain:1, italy:1, netherlands:1, holland:1, belgium:1, switzerland:1, austria:1, sweden:1, denmark:1, norway:1, finland:1, ireland:1, portugal:1, poland:1, czechia:1, hungary:1, romania:1, greece:1, australia:1, 'new zealand':1, japan:1, china:1, india:1, korea:1, 'south korea':1, thailand:1, malaysia:1, indonesia:1, vietnam:1, philippines:1, taiwan:1, brazil:1, mexico:1, argentina:1, chile:1, colombia:1, peru:1, turkey:1, turkiye:1, israel:1, egypt:1, morocco:1, nigeria:1, kenya:1, uae:1, 'united arab emirates':1, 'saudi arabia':1, qatar:1, bahrain:1, kuwait:1, oman:1 }};
    function dupCityOf(o) {{
      o = o || {{}};
      var c = String(o.city || '').trim();
      if (!c) {{
        var parts = String(o.location || '').split(',').map(function (s) {{ return s.trim(); }}).filter(Boolean);
        // Read the CITY by walking from the END of the location, skipping the
        // country and any state/province code — so "Convene, 155 Bishopsgate,
        // London, UK" and "583 Park Avenue, New York, NY, USA" both resolve to
        // the real city (London / New York), whatever the venue is called.
        for (var i = parts.length - 1; i >= 0; i--) {{
          var p = parts[i];
          if (_DUP_COUNTRIES[abFold(p)]) continue;   // country
          if (/^[a-z]{{2}}$/i.test(p)) continue;      // state / province code (NY, CA, ON)
          if (/^\\d/.test(p)) continue;               // street number
          c = p; break;
        }}
        if (!c && parts.length) c = parts[0];
      }}
      // Normalise "New York City" -> "new york", "Greater London" -> "london".
      return abFold(c).replace(/\\b(city|greater)\\b/g, '').replace(/\\s+/g, ' ').trim();
    }}
    function dupYearOf(o) {{ var m = ((o.start_date || '') + ' ' + (o.date_str || '')).match(/20\\d\\d/); return m ? m[0] : ''; }}
    function dupKeyOf(o) {{ var core = dupNameCore(o.name || ''); return core ? (core + '|' + dupCityOf(o) + '|' + dupYearOf(o)) : ''; }}
    // ── Strip-and-retry around not-yet-migrated columns ────────────────
    // pricing / audience_type were added 2026-06. If this DB hasn't run the
    // migration yet, PostgREST rejects the whole write. We detect that, drop
    // the offending column, and retry so the save still lands (the buyer/price
    // fields just stay blank until the migration runs).
    // Internal/audit columns: strip SILENTLY on a missing-column error (they
    // aren't user-entered data, so don't warn that they "weren't saved").
    var SILENT_STRIP_COLS = ['updated_by', 'updated_at'];
    function missingColFromErr(err) {{
      // The column name Postgres/PostgREST reports as missing, for either:
      //   PGRST204  "Could not find the 'updated_by' column of 'manual_events' in the schema cache"
      //   42703     "column manual_events.updated_by does not exist"
      // Returning it lets sbWriteRetry strip that one column and retry, so a save
      // never dies just because the DB lacks an optional / not-yet-migrated
      // column (any column, not just a hard-coded list).
      if (!err) return null;
      var msg = (err.message || '') + ' ' + (err.details || '');
      var code = String(err.code || '');
      if (code !== 'PGRST204' && code !== '42703' && msg.toLowerCase().indexOf('column') === -1) return null;
      var m = msg.match(/find the ['"]([A-Za-z0-9_]+)['"] column/i)
           || msg.match(/column ['"]?(?:[A-Za-z0-9_]+\\.)?([A-Za-z0-9_]+)['"]? (?:of |does not exist)/i)
           || msg.match(/['"]([A-Za-z0-9_]+)['"] column/i);
      return m ? m[1] : null;
    }}
    // runFn(payload) -> a Supabase thenable resolving to {{data, error}}.
    // On a missing-column error it strips that column and retries. The final
    // resp carries strippedMigrationCols (user-data columns only) so callers can
    // warn that those values were NOT saved (DB migration still pending).
    function sbWriteRetry(payload, runFn, _stripped) {{
      _stripped = _stripped || [];
      return runFn(payload).then(function (resp) {{
        var col = missingColFromErr(resp.error);
        if (col && Object.prototype.hasOwnProperty.call(payload, col)) {{
          var p2 = {{}};
          for (var k in payload) {{ if (k !== col && Object.prototype.hasOwnProperty.call(payload, k)) p2[k] = payload[k]; }}
          var next = (SILENT_STRIP_COLS.indexOf(col) !== -1) ? _stripped : _stripped.concat([col]);
          return sbWriteRetry(p2, runFn, next);
        }}
        if (_stripped.length) resp.strippedMigrationCols = _stripped;
        return resp;
      }});
    }}

    function loadKnownNames() {{
      var p1 = fetch('events.json').then(function (r) {{ return r.json(); }}).then(function (d) {{
        return ((d && d.events) || []);
      }}).catch(function () {{ return []; }});
      var p2 = sb.from('manual_events').select('id,name,city,location,start_date,date_str').then(function (r) {{
        return ((r && r.data) || []);
      }});
      return Promise.all([p1, p2]).then(function (a) {{
        _knownNameSource = {{}}; _knownKeys = {{}}; _knownRec = {{}};
        function remember(e, src) {{
          var rec = {{ name: e.name || '', location: e.location || e.city || '', date_str: e.date_str || '' }};
          var n = (e.name || '').toLowerCase().trim();
          if (n) {{ _knownNameSource[n] = src; _knownRec[n] = rec; }}
          var k = dupKeyOf(e);
          if (k) {{ if (!_knownKeys[k] || src.indexOf('manual') === 0) _knownKeys[k] = src; if (!_knownRec[k]) _knownRec[k] = rec; }}
        }}
        a[0].forEach(function (e) {{ remember(e, 'catalog'); }});
        a[1].forEach(function (e) {{ remember(e, 'manual:' + e.id); }});
        _knownNames = Object.keys(_knownNameSource);
        return _knownNames;
      }});
    }}
    // Returns null if name is fine, or an object describing the conflict
    // (incl. the matched event's details for a clear message).
    // selfId optional — when editing, ignores a match against the row being edited.
    function findDuplicate(name, selfId, o) {{
      var n = (name || '').toLowerCase().trim();
      if (!_knownNameSource) return null;
      var src = n ? _knownNameSource[n] : null;       // 1) exact name match
      var rec = src ? _knownRec[n] : null;
      if (!src && o) {{                                 // 2) fuzzy name+city+year
        var k = dupKeyOf(o);
        if (k) {{ src = _knownKeys[k] || null; rec = src ? _knownRec[k] : null; }}
      }}
      if (!src) return null;
      if (selfId && src === 'manual:' + selfId) return null;
      return {{ name_lower: n, source: src, rec: rec || null }};
    }}
    // "TEDAI (Vienna, Austria · October 28–30, 2026)" for dup messages.
    function dupLabel(dup) {{
      var r = dup && dup.rec; if (!r) return '';
      var bits = [r.location, r.date_str].filter(Boolean).join(' · ');
      return (r.name || '') + (bits ? ' (' + bits + ')' : '');
    }}
    function isDuplicateName(name, selfId, o) {{ return !!findDuplicate(name, selfId, o); }}

    function attachAddEventHandlers(form, email) {{
      // Warm the duplicate-name cache so the submit handler can synchronously
      // check without an extra round-trip.
      loadKnownNames();
      // Fill from URL — scrape via Exa.ai + extract via Dust, in /api/vet
      var fillBtn  = form.querySelector('#fill-from-url-btn');
      var fillMeta = form.querySelector('#fill-from-url-meta');
      if (fillBtn) {{
        fillBtn.addEventListener('click', function () {{
          var urlInp = form.querySelector('input[name="url"]');
          var url = (urlInp.value || '').trim();
          if (!/^https?:\\/\\//i.test(url)) {{
            fillMeta.textContent = 'Paste an http:// or https:// URL first.';
            return;
          }}
          fillBtn.disabled = true; fillBtn.textContent = 'Scraping…';
          fillMeta.textContent = 'Fetching the page via Exa, then structuring it with AI (gpt-5.4). Usually 10\\u201340 seconds.';
          sb.auth.getSession().then(function (r) {{
            var token = r && r.data && r.data.session && r.data.session.access_token;
            var _vh = {{ 'Content-Type': 'application/json' }};
            if (token) _vh['Authorization'] = 'Bearer ' + token;
            var t0 = Date.now();
            fetch('/api/vet', {{
              method:  'POST',
              headers: _vh,
              body:    JSON.stringify({{ url: url }})
            }}).then(function (res) {{
              return res.json().then(function (j) {{ return [res.status, j]; }});
            }}).then(function (pair) {{
              fillBtn.disabled = false; fillBtn.textContent = 'Fill from URL';
              var st = pair[0], data = pair[1];
              if (st !== 200) {{
                fillMeta.textContent = 'Couldn\\u2019t scrape (' + st + '): ' + (data && data.error || 'unknown');
                return;
              }}
              var f = data.fields || {{}};
              // Only fill empty inputs by default — never clobber what user typed
              var report = applyExtractToForm(form, f, {{ overwrite: false }});
              var dur = Math.round((Date.now() - t0) / 1000);
              var note = 'Filled ' + report.filled + ' of ' + report.total + ' fields in ' + dur + 's' +
                (report.skipped ? ' (' + report.skipped + ' skipped — already had values).' : '.') +
                ' \\u26a0\\ufe0f Double-check the date & location — scrapers often read them wrong; you can fix the date any time in Details \\u2192 Edit.';
              if (data.degraded) {{
                note += ' (AI structuring was unavailable — used the scraped page with basic extraction, so please double-check the fields.)';
              }}
              fillMeta.textContent = note;
            }}).catch(function (err) {{
              fillBtn.disabled = false; fillBtn.textContent = 'Fill from URL';
              fillMeta.textContent = 'Network error: ' + err.message;
            }});
          }});
        }});
      }}

      // Extract from pasted email
      var extractBtn = form.querySelector('#paste-extract-btn');
      var clearBtn   = form.querySelector('#paste-clear-btn');
      var pasteArea  = form.querySelector('#paste-email-text');
      var meta       = form.querySelector('#paste-extract-meta');
      extractBtn.addEventListener('click', function () {{
        var text = pasteArea.value || '';
        var trimmed = text.trim();
        if (trimmed.length < 10) {{ meta.textContent = 'Nothing to extract from yet.'; return; }}
        // Pasted just a link? Local text-parsing can't read a page — route it to
        // the real scraper (Fill from URL → /api/vet) so name/date/location fill.
        if (/^https?:\\/\\/\\S+$/i.test(trimmed)) {{
          var urlInp2 = form.querySelector('input[name="url"]');
          if (urlInp2) urlInp2.value = trimmed;
          if (fillBtn) {{
            meta.textContent = 'That\\u2019s a link — scraping the page (see the URL row above)…';
            fillBtn.click();
            return;
          }}
        }}
        var extracted = extractFromEmail(text);
        var report = applyExtractToForm(form, extracted, {{ overwrite: false }});
        if (report.total === 0) {{
          meta.textContent = 'Couldn\\u2019t find a name / date / location / URL in that text. Fill the form manually.';
          return;
        }}
        meta.textContent = 'Extracted ' + report.filled + ' of ' + report.total + ' fields' + (report.skipped ? ' (' + report.skipped + ' skipped because fields were already filled).' : '.');
      }});
      clearBtn.addEventListener('click', function () {{ pasteArea.value = ''; meta.textContent = ''; }});

      // Cancel
      form.querySelector('[data-cancel]').addEventListener('click', function () {{ form.remove(); }});

      // Date field: flexible text + click-to-open calendar (single day or range).
      wireDatePicker(form.querySelector('.date-pick'));

      // Submit → manual_events insert
      form.addEventListener('submit', function (ev) {{
        ev.preventDefault();
        var fd = new FormData(form);
        var row = {{
          name:       (fd.get('name') || '').toString().trim(),
          date_str:   (fd.get('date_str') || '').toString().trim(),
          location:   (fd.get('location') || '').toString().trim() || null,
          region:     (fd.get('region') || '').toString().trim() || null,
          type:       (fd.get('type') || '').toString().trim() || null,
          priority:   (fd.get('priority') || '').toString().trim() || null,
          why:        (fd.get('why') || '').toString().trim() || null,
          url:        normUrl(fd.get('url')),
          speaker:    (fd.get('speaker') || '').toString().trim() || null,
          status_tags:        normalizeStageTags(fd.getAll('status_tags')),
          about:              (fd.get('about') || '').toString().trim() || null,
          focus_areas:        (fd.get('focus_areas') || '').toString().trim() || null,
          typical_attendees:  (fd.get('typical_attendees') || '').toString().trim() || null,
          speaking_route:     (fd.get('speaking_route') || '').toString().trim() || null,
          contact_info:       (fd.get('contact_info') || '').toString().trim() || null,
          deadline:           (fd.get('deadline') || '').toString().trim() || null,
          attendee_count:     (fd.get('attendee_count') || '').toString().trim() || null,
          audience_type:      (fd.get('audience_type') || '').toString().trim() || null,
          pricing:            (fd.get('pricing') || '').toString().trim() || null,
          past_speakers:      (fd.get('past_speakers') || '').toString().trim() || null,
          meeting_formats:    (fd.get('meeting_formats') || '').toString().trim() || null,
          attend_verdict:     (fd.get('attend_verdict') || '').toString().trim() || null,
          postmortem:         (fd.get('postmortem') || '').toString().trim() || null,
          pay_to_play:        (fd.get('pay_to_play') || '').toString().trim() || null,
          venue:              (fd.get('venue') || '').toString().trim() || null,
          city:               (fd.get('city') || '').toString().trim() || null,
          country:            (fd.get('country') || '').toString().trim() || null,
          seed:               triBool(fd.get('seed')),
          urgent:             triBool(fd.get('urgent')),
          created_by: email
        }};
        if (!row.name) {{ alert('Name is required (it shows on the calendar)'); return; }}
        // Date is a flexible free-text field (parsed super-loosely by
        // deriveDatesFromText) that the calendar popup can also fill. When the
        // calendar is used it stashes exact ISO start/end on the input's
        // dataset — trust those; otherwise parse whatever was typed.
        var _dsEl = form.querySelector('[name="date_str"]');
        var _calS = _dsEl && _dsEl.getAttribute('data-start-iso');
        var _calE = _dsEl && _dsEl.getAttribute('data-end-iso');
        if (!row.date_str) row.date_str = 'Date TBD';
        if (_calS) {{
          row.start_date = _calS;
          row.end_date   = _calE || _calS;
        }} else {{
          var derived = deriveDatesFromText(row.date_str);
          if (derived.start_date) row.start_date = derived.start_date;
          if (derived.end_date)   row.end_date   = derived.end_date;
        }}
        // The user typed a real date the parser couldn't read (e.g. "Q3 2026",
        // "next spring") → start_date stays null and the event silently never
        // shows on the calendar / iCal. Flag it so we can warn on save.
        var unparsedDate = (row.date_str !== 'Date TBD') && !row.start_date;
        // Year is redundant with the date — strip a trailing year on save.
        row.name = stripTrailingYear(row.name);
        // Auto-flag whoever adds the event as interested, so it lands in
        // Angela's Queue ("apply for me") immediately — EXCEPT sales-support
        // staff (Hurley/Angela), who run the tracker but don't attend.
        var _adder = getCollabName() || (email ? firstNameFromEmail(email) : '') || 'Team';
        row.interested = isSupportPerson(_adder) ? [] : [_adder];
        // HARD duplicate-name guard — case-insensitive across catalog + manual_events.
        // No confirm() escape hatch: duplicates land in the calendar as two
        // separate entries with two UIDs, which produces double-rendered
        // events in subscribed calendars. The unique index on the DB
        // (scripts/2026-05-26_dedup_manual_events.sql) is the final defense.
        // Exact-name match. Show WHICH event (location + date) so the user can
        // tell if it's truly the same, and let them override if it's genuinely
        // different (e.g. same name, different city/year) — the DB unique index
        // is the final backstop.
        var dup = findDuplicate(row.name);
        if (dup) {{
          var where = dup.source === 'catalog' ? 'the ArcticBlue catalog' : 'your manual events';
          var lbl = dupLabel(dup) || ('"' + row.name + '"');
          if (!confirm(lbl + ' is already in ' + where + '. If that\\u2019s the same event, open it instead of adding a duplicate. Add it anyway?')) {{
            return;
          }}
        }}
        // Fuzzy guard — same core name + city + year as an existing event (e.g.
        // "… 2026" vs "… (IPT Edition)"). Likely the same event; let the user
        // override in case it's genuinely a different edition.
        var fuzzyDup = dup ? null : findDuplicate(null, null, row);
        if (fuzzyDup) {{
          var flbl = dupLabel(fuzzyDup) || 'an event';
          if (!confirm('This looks like a duplicate of ' + flbl + ' already in ' + (fuzzyDup.source === 'catalog' ? 'the catalog' : 'your manual events') + ' — same name, city and year. Add it anyway?')) {{
            return;
          }}
        }}
        var submitBtn = form.querySelector('button.primary[type="submit"]');
        submitBtn.disabled = true; submitBtn.textContent = 'Saving…';
        sbWriteRetry(row, function (p) {{ return sb.from('manual_events').insert(p).select(); }}).then(function (resp) {{
          submitBtn.disabled = false; submitBtn.textContent = 'Add event';
          if (resp.error) {{
            // 23505 = unique_violation. Hit when the DB unique index catches
            // a race we missed (two concurrent inserts of the same name).
            if (resp.error.code === '23505' || /duplicate key value|unique/i.test(resp.error.message || '')) {{
              status('"' + row.name + '" already exists. Refreshing the duplicate cache…', 'warn');
              loadKnownNames();
              return;
            }}
            status('Add failed: ' + resp.error.message, 'error');
            return;
          }}
          var newRow = (resp.data && resp.data[0]) || row;
          form.remove();
          var card = buildManualCard(newRow, email);
          $opsGrid.insertBefore(card, $opsGrid.firstChild);
          wireManualCard(card, email);
          updateOpsCount();
          regroupOpsByMonth();   // slot the new card into its month section
          applyFilters();
          loadKnownNames();   // keep the dup index fresh
          if (unparsedDate) {{
            status('Added "' + newRow.name + '" — but I couldn’t read a date from "' + row.date_str + '", so it won’t show on the calendar until you edit it to a date like "September 12, 2026".', 'warn');
          }} else {{
            flashOk('Event added');
          }}
        }});
      }});
    }}

    // ── iCal export ─────────────────────────────────────────────────
    function icalEscape(s) {{
      return String(s == null ? '' : s)
        .replace(/\\\\/g, '\\\\\\\\')
        .replace(/;/g, '\\\\;')
        .replace(/,/g, '\\\\,')
        .replace(/\\n/g, '\\\\n');
    }}

    function icsDate(iso) {{
      if (!iso) return '';
      return iso.replace(/-/g, '');
    }}

    // Add one day to a YYYY-MM-DD (ICS DTEND is exclusive for all-day events)
    function icsDatePlus1(iso) {{
      if (!iso) return '';
      var d = new Date(iso + 'T00:00:00Z');
      d.setUTCDate(d.getUTCDate() + 1);
      return d.toISOString().slice(0,10).replace(/-/g, '');
    }}

    function buildIcsForSaved(events, stateMap, manualEvents) {{
      var now = new Date();
      var dtstamp = now.toISOString().replace(/[-:]/g, '').slice(0, 15) + 'Z';
      var lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//ArcticBlue//Event Tracker//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:ArcticBlue · Saved events'
      ];
      function pushEvent(ev, st, uid) {{
        var startIso = ev.start_date || (st && st.start_date) || null;
        var endIso = ev.end_date || startIso;
        var desc = [];
        if (ev.why)         desc.push(ev.why);
        if (st && st.notes) desc.push('Notes: ' + st.notes);
        if (st && st.speaker) desc.push('Speaker: ' + st.speaker);
        if (st && st.status)  desc.push('Status: ' + st.status);
        if (ev.priority || (st && st.priority_override)) desc.push('Priority: ' + (st && st.priority_override || ev.priority || ''));
        var description = desc.join('\\n');
        lines.push('BEGIN:VEVENT');
        lines.push('UID:' + uid);
        lines.push('DTSTAMP:' + dtstamp);
        if (startIso) lines.push('DTSTART;VALUE=DATE:' + icsDate(startIso));
        if (endIso)   lines.push('DTEND;VALUE=DATE:'   + icsDatePlus1(endIso));
        lines.push('SUMMARY:' + icalEscape(ev.name || ''));
        if (ev.location) lines.push('LOCATION:' + icalEscape(ev.location));
        if (description) lines.push('DESCRIPTION:' + icalEscape(description));
        if (ev.url) lines.push('URL:' + ev.url);
        if (st && st.urgent) lines.push('CATEGORIES:URGENT');
        lines.push('END:VEVENT');
      }}
      // Dedup: a catalog row + a manual row for the SAME event (one holding
      // speaking info, one attending) must not double in the exported calendar.
      // Key = normalized name + start date (date included so different-city
      // editions of a series don't false-match).
      var _seenIcs = {{}};
      function _icsKey(name, startIso) {{
        var s = String(name || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ')
          .replace(/\\b(20\\d\\d|usa|north america|europe|edition|the|annual)\\b/g, ' ')
          .replace(/\\s+/g, ' ').trim();
        return s + '|' + String(startIso || '');
      }}
      (events || []).forEach(function (ev) {{
        var st = stateMap[ev.num];
        if (!st || !st.saved) return;
        var k = _icsKey(ev.name, ev.start_date);
        if (_seenIcs[k]) return;
        _seenIcs[k] = 1;
        pushEvent(ev, st, 'event-' + ev.num + '@arcticblue-event-tracker');
      }});
      // Manual events: include all of them (since adding manually is a saved-intent action)
      (manualEvents || []).forEach(function (mev) {{
        if (!mev.start_date) return;
        var k = _icsKey(mev.name, mev.start_date);
        if (_seenIcs[k]) return;
        _seenIcs[k] = 1;
        pushEvent({{
          name: mev.name, location: mev.location, why: mev.why, url: mev.url,
          start_date: mev.start_date, end_date: mev.end_date || mev.start_date,
          priority: mev.priority
        }}, null, 'manual-' + mev.id + '@arcticblue-event-tracker');
      }});
      lines.push('END:VCALENDAR');
      return lines.join('\\r\\n') + '\\r\\n';
    }}

    function exportSavedAsIcs() {{
      Promise.all([
        fetch('events.json').then(function (r) {{ return r.json(); }}),
        sb.from('event_state').select('*'),
        sb.from('manual_events').select('*')
      ]).then(function (results) {{
        var data = results[0];
        var stateRows = (results[1] && results[1].data) || [];
        var manualRows = (results[2] && results[2].data) || [];
        var stateMap = {{}};
        stateRows.forEach(function (r) {{ stateMap[r.event_num] = r; }});
        var evs = (data.events || []).filter(function (e) {{ return e.status !== 'archived'; }});
        var ics = buildIcsForSaved(evs, stateMap, manualRows);
        var savedCount = stateRows.filter(function (r) {{ return r.saved; }}).length;
        if (savedCount === 0 && manualRows.length === 0) {{
          status('Nothing to export yet — save at least one event first.', 'warn');
          return;
        }}
        var blob = new Blob([ics], {{ type: 'text/calendar;charset=utf-8;' }});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = 'arcticblue-saved-' + new Date().toISOString().slice(0,10) + '.ics';
        document.body.appendChild(a); a.click();
        setTimeout(function () {{ URL.revokeObjectURL(url); a.remove(); }}, 0);
        flashOk('iCal downloaded — ' + savedCount + ' saved + ' + manualRows.length + ' manual');
      }});
    }}

    // ── View toggle (Grid / Calendar) ───────────────────────────────
    var VIEW_KEY = 'ab.angela.view';
    var currentView = 'grid';
    // The "Events" tab remembers which of List / Calendar / Map you last used,
    // so returning to it lands you back where you were.
    var _lastEventsSub = 'grid';

    var VIEW_NAMES = ['myevents', 'myprofile', 'grid', 'calendar', 'map', 'queue', 'planner', 'dayof'];   // 'planahead' merged into 'myevents'
    function setView(name) {{
      if (VIEW_NAMES.indexOf(name) === -1) name = 'grid';
      // The Day-Of brief now lives inside My Events — no standalone tab.
      if (name === 'dayof') name = 'myevents';
      // Planner + Queue are Angela-only — redirect anyone else who lands on them.
      if ((name === 'planner' || name === 'queue') && window.isAngelaUser && !window.isAngelaUser()) name = getCollabName() ? 'myevents' : 'grid';
      currentView = name;
      var isEventsView = (name === 'grid' || name === 'calendar' || name === 'map');
      if (isEventsView) _lastEventsSub = name;
      document.querySelectorAll('.view-toggle button[data-view]').forEach(function (b) {{
        var on = b.dataset.view === name;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      }});
      // The merged "Events" tab has no data-view of its own — it's active for
      // ANY of its List / Calendar / Map sub-views, which live in a secondary
      // switcher shown only while you're on one of them.
      var $eventsTab = document.getElementById('tab-events');
      if ($eventsTab) {{
        $eventsTab.classList.toggle('active', isEventsView);
        $eventsTab.setAttribute('aria-selected', isEventsView ? 'true' : 'false');
      }}
      var $subnav = document.getElementById('events-subnav');
      if ($subnav) {{
        $subnav.hidden = !isEventsView;
        Array.prototype.forEach.call($subnav.querySelectorAll('[data-view]'), function (b) {{
          var on = b.dataset.view === name;
          b.classList.toggle('active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        }});
      }}
      // Search + filters are the Events surface's own tools — hide the whole
      // row on the personal tabs (My Lineup / Plan Ahead / My Profile), where
      // there's nothing to filter. (The controls stay in the DOM, so returning
      // to Events restores them with their state intact.)
      var $topf = document.getElementById('ops-topfilters');
      if ($topf) $topf.style.display = isEventsView ? '' : 'none';
      var $afb = document.getElementById('ops-active-filters');
      if ($afb) $afb.style.display = isEventsView ? '' : 'none';
      // The filter drawer is Events-only too; always leave it closed on a switch.
      var $ffd = document.getElementById('tf-drawer');
      if ($ffd) {{ $ffd.hidden = true; }}
      var $fft = document.getElementById('ops-filter-toggle');
      if ($fft) {{ $fft.setAttribute('aria-expanded', 'false'); $fft.style.display = isEventsView ? '' : 'none'; }}
      var g = document.getElementById('ops-grid');
      var c = document.getElementById('ops-calendar');
      var m = document.getElementById('ops-map');
      var q = document.getElementById('ops-queue');
      var p = document.getElementById('ops-planner');
      var d = document.getElementById('ops-dayof');
      var me = document.getElementById('ops-myevents');
      var pr = document.getElementById('ops-myprofile');
      if (g) g.style.display = (name === 'grid') ? '' : 'none';
      var rh = document.getElementById('ops-results-header');
      if (rh) rh.style.display = (name === 'grid') ? '' : 'none';
      if (me) me.classList.toggle('show', name === 'myevents');
      if (pr) pr.classList.toggle('show', name === 'myprofile');
      if (c) c.classList.toggle('show', name === 'calendar');
      if (m) m.classList.toggle('show', name === 'map');
      if (q) q.classList.toggle('show', name === 'queue');
      if (p) p.classList.toggle('show', name === 'planner');
      if (d) d.classList.toggle('show', name === 'dayof');
      if (name === 'myevents') renderMyEvents();
      if (name === 'myprofile') renderMyProfile();
      if (name === 'calendar') recalcCalendar();   // re-apply the live filters
      if (name === 'map') openOpsMap();
      if (name === 'queue') renderQueue();
      if (name === 'planner') renderPlanner();
      if (name === 'dayof') renderDayOf();
      try {{ localStorage.setItem(VIEW_KEY, name); }} catch (e) {{}}
    }}

    function wireViewToggle() {{
      document.querySelectorAll('.view-toggle button[data-view]').forEach(function (b) {{
        // Clone-replace to avoid duplicate listeners on re-route
        var fresh = b.cloneNode(true);
        b.parentNode.replaceChild(fresh, b);
        fresh.addEventListener('click', function () {{ setView(fresh.dataset.view); }});
      }});
      // The merged "Events" tab (no data-view) opens your last-used sub-view;
      // its List / Calendar / Map switcher lives outside .view-toggle.
      var $eventsTab = document.getElementById('tab-events');
      if ($eventsTab && !$eventsTab.dataset.wired) {{
        $eventsTab.dataset.wired = '1';
        $eventsTab.addEventListener('click', function () {{ setView(_lastEventsSub || 'grid'); }});
      }}
      document.querySelectorAll('.events-subnav button[data-view]').forEach(function (b) {{
        if (b.dataset.wired) return;
        b.dataset.wired = '1';
        b.addEventListener('click', function () {{ setView(b.dataset.view); }});
      }});
      // A refresh keeps you on the view you were last on (Calendar / All Events
      // / Map / My Events). Only a FIRST-time visitor with no saved view lands
      // on My Events (if named) or the grid (if not).
      try {{
        var saved = localStorage.getItem(VIEW_KEY);
        if (VIEW_NAMES.indexOf(saved) !== -1) setView(saved);
        else if (getCollabName()) setView('myevents');
        else setView('grid');
      }} catch (e) {{ setView(getCollabName() ? 'myevents' : 'grid'); }}
    }}

    // ── Map view ─────────────────────────────────────────────────────
    // City-level pins (Leaflet + OpenStreetMap, lazy-loaded). Coordinates come
    // from a static lookup keyed by substrings of city/venue/location text —
    // venue names ("Javits Center") resolve to their city. Events whose
    // location matches nothing (Remote, TBD, Podcast) are counted in a note
    // above the map rather than dropped silently.
    var CITY_COORDS = [
      // [substring key, lat, lng] — checked in order, first hit wins, so put
      // longer/more-specific keys before short generic ones.
      ['excel london', 51.508, 0.029], ['olympia london', 51.496, -0.210],
      ['intercontinental london', 51.502, 0.003], ['88 wood street', 51.516, -0.094],
      ['new york', 40.7128, -74.006], ['nyc', 40.7128, -74.006],
      ['javits', 40.7578, -74.0021], ['pier sixty', 40.7466, -74.0086],
      ['583 park', 40.7651, -73.9683], ['marriott marquis', 40.7589, -73.9851],
      ['las vegas', 36.1699, -115.1398], ['venetian', 36.1212, -115.1697],
      ['mandalay bay', 36.0921, -115.1761],
      ['san francisco', 37.7749, -122.4194], ['moscone', 37.7842, -122.4016],
      ['sandy springs', 33.9304, -84.3733], ['atlanta', 33.749, -84.388],
      ['marina bay sands', 1.2834, 103.8607], ['singapore', 1.3521, 103.8198],
      ['san jose', 37.3382, -121.8863], ['santa clara', 37.3541, -121.9552],
      ['mccormick', 41.8512, -87.6093], ['chicago', 41.8781, -87.6298],
      ['paris', 48.8566, 2.3522], ['taets', 52.4338, 4.8167],
      ['amsterdam', 52.3676, 4.9041], ['hynes', 42.3471, -71.0859],
      ['cambridge', 42.3736, -71.1097], ['boston', 42.3601, -71.0589],
      ['dubai exhibition', 25.2048, 55.2708], ['grand hyatt dubai', 25.2285, 55.3273],
      ['dubai', 25.2048, 55.2708],
      ['miami beach', 25.7907, -80.13], ['biltmore', 25.7409, -80.2784],
      ['miami', 25.7617, -80.1918],
      ['barcelona', 41.3851, 2.1734], ['washington', 38.9072, -77.0369],
      ['national harbor', 38.7826, -77.0164], ['nashville', 36.1627, -86.7816],
      ['san diego', 32.7157, -117.1611],
      ['kay bailey', 32.7757, -96.8003], ['frisco', 33.1507, -96.8236],
      ['dallas', 32.7767, -96.797],
      ['los angeles', 34.0522, -118.2437], ['austin', 30.2672, -97.7431],
      ['doha', 25.2854, 51.531],
      ['messe berlin', 52.5005, 13.2697], ['maritim', 52.5108, 13.3806],
      ['berlin', 52.52, 13.405],
      ['cape town', -33.9249, 18.4241], ['zurich', 47.3769, 8.5417],
      ['aspen', 39.1911, -106.8175], ['disney', 28.3658, -81.5494],
      ['orlando', 28.5383, -81.3792], ['munich', 48.1351, 11.582],
      ['hoboken', 40.744, -74.0324], ['riyadh', 24.7136, 46.6753],
      ['fort lauderdale', 26.1224, -80.1373], ['abu dhabi', 24.4539, 54.3773],
      ['vancouver', 49.2827, -123.1207], ['rome', 41.9028, 12.4964],
      ['bahrain', 26.0667, 50.5577],
      ['yonge street', 43.6606, -79.3787], ['george campus', 43.6606, -79.3787],
      ['toronto', 43.6532, -79.3832],
      ['palexpo', 46.2381, 6.1153], ['geneva', 46.2044, 6.1432],
      ['anaheim', 33.8366, -117.9143], ['sao paulo', -23.5505, -46.6333],
      ['notary hotel', 39.9526, -75.1652], ['philadelphia', 39.9526, -75.1652],
      ['ifema', 40.4683, -3.6166], ['madrid', 40.4168, -3.7038],
      ['meo arena', 38.7684, -9.0938], ['lisbon', 38.7223, -9.1393],
      ['brussels', 50.8503, 4.3517], ['stockholm', 59.3293, 18.0686],
      ['san mateo', 37.563, -122.3255], ['berkeley', 37.8715, -122.273],
      ['denver', 39.7392, -104.9903], ['half moon bay', 37.4636, -122.4286],
      ['menlo park', 37.4529, -122.1817], ['phoenix', 33.4484, -112.074],
      ['baltimore', 39.2904, -76.6122], ['muscat', 23.588, 58.3829],
      ['oman', 23.588, 58.3829], ['cannes', 43.5528, 7.0174],
      ['oxford', 51.752, -1.2577], ['oslo', 59.9139, 10.7522],
      ['leesburg', 39.1157, -77.5636], ['dublin', 53.3498, -6.2603],
      ['hong kong', 22.3193, 114.1694], ['dana point', 33.4669, -117.698],
      ['loudoun', 39.09, -77.64],
      ['venezuela', 10.4806, -66.9036], ['bachelor', 39.5806, -106.5347],
      ['new orleans', 29.9511, -90.0715], ['grapevine', 32.9343, -97.0781],
      ['sydney', -33.8688, 151.2093], ['melbourne', -37.8136, 144.9631],
      ['gold coast', -28.0167, 153.4], ['yokohama', 35.4437, 139.638],
      ['tokyo', 35.6762, 139.6503], ['mumbai', 19.076, 72.8777],
      ['bengaluru', 12.9716, 77.5946], ['bangalore', 12.9716, 77.5946],
      ['new delhi', 28.6139, 77.209], ['seoul', 37.5665, 126.978],
      ['shanghai', 31.2304, 121.4737], ['tel aviv', 32.0853, 34.7818],
      ['istanbul', 41.0082, 28.9784], ['jersey city', 40.7178, -74.0431],
      ['doha', 25.2854, 51.531], ['santo domingo', 18.4861, -69.9312],
      ['london', 51.5074, -0.1278]
    ];
    // Strip accents so "São Paulo" / "Bogotá" match "sao paulo" / "bogota".
    function _deaccent(s) {{
      try {{ return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, ''); }} catch (e) {{ return s; }}
    }}
    // Checked BEFORE CITY_COORDS so shared names (San José, Santa Clara,
    // Santiago) resolve to Latin America — not their US namesakes — when the
    // location actually names a LatAm place.
    var LATAM_COORDS = [
      ['costa rica', 9.9281, -84.0907], ['san salvador', 13.6929, -89.2182],
      ['el salvador', 13.6929, -89.2182], ['guatemala', 14.6349, -90.5069],
      ['mexico city', 19.4326, -99.1332], ['ciudad de mexico', 19.4326, -99.1332],
      ['guadalajara', 20.6597, -103.3496], ['monterrey', 25.6866, -100.3161],
      ['cancun', 21.1619, -86.8515], ['bogota', 4.711, -74.0721],
      ['cartagena', 10.391, -75.4794], ['panama city', 8.9824, -79.5199],
      ['medellin', 6.2442, -75.5812], ['lima', -12.0464, -77.0428],
      ['buenos aires', -34.6037, -58.3816], ['santiago', -33.4489, -70.6693],
      ['rio de janeiro', -22.9068, -43.1729], ['quito', -0.1807, -78.4678],
      ['montevideo', -34.9011, -56.1645], ['caracas', 10.4806, -66.9036]
    ];
    // Last resort — no known city matched, so land the pin in the right COUNTRY
    // (its capital / largest city) instead of dropping the event off the map.
    var COUNTRY_COORDS = [
      ['costa rica', 9.9281, -84.0907], ['panama', 8.9824, -79.5199],
      ['guatemala', 14.6349, -90.5069], ['colombia', 4.711, -74.0721],
      ['peru', -12.0464, -77.0428], ['ecuador', -0.1807, -78.4678],
      ['chile', -33.4489, -70.6693], ['argentina', -34.6037, -58.3816],
      ['uruguay', -34.9011, -56.1645], ['brazil', -23.5505, -46.6333],
      ['venezuela', 10.4806, -66.9036], ['dominican republic', 18.4861, -69.9312],
      ['puerto rico', 18.4655, -66.1057], ['mexico', 19.4326, -99.1332],
      ['india', 19.076, 72.8777], ['japan', 35.6762, 139.6503],
      ['australia', -33.8688, 151.2093], ['china', 31.2304, 121.4737],
      ['south korea', 37.5665, 126.978], ['saudi arabia', 24.7136, 46.6753],
      ['united arab emirates', 25.2048, 55.2708]
    ];
    function geoOf(rec) {{
      var raw = (rec.city || '') + ' ' + (rec.venue || '') + ' ' + (rec.location || '');
      if (!raw.trim()) return null;
      // Guard "New Mexico" (US state) from the 'mexico' country fallback.
      var hay = _deaccent(raw.toLowerCase()).replace(/new mexico/g, 'newmex');
      var i;
      for (i = 0; i < LATAM_COORDS.length; i++) {{
        if (hay.indexOf(LATAM_COORDS[i][0]) !== -1) return [LATAM_COORDS[i][1], LATAM_COORDS[i][2]];
      }}
      for (i = 0; i < CITY_COORDS.length; i++) {{
        if (hay.indexOf(CITY_COORDS[i][0]) !== -1) return [CITY_COORDS[i][1], CITY_COORDS[i][2]];
      }}
      for (i = 0; i < COUNTRY_COORDS.length; i++) {{
        if (hay.indexOf(COUNTRY_COORDS[i][0]) !== -1) return [COUNTRY_COORDS[i][1], COUNTRY_COORDS[i][2]];
      }}
      return null;
    }}

    var _leafletLoading = null;
    function loadLeaflet() {{
      if (window.L) return Promise.resolve();
      if (_leafletLoading) return _leafletLoading;
      _leafletLoading = new Promise(function (resolve, reject) {{
        var css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(css);
        var s = document.createElement('script');
        s.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        s.onload = resolve;
        s.onerror = function () {{ _leafletLoading = null; reject(new Error('leaflet load failed')); }};
        document.head.appendChild(s);
      }});
      return _leafletLoading;
    }}

    var _opsMap = null, _opsMapLayer = null;
    // ── One world, exactly once ──────────────────────────────────────────
    // The map used to repeat: zoomed out, you got five side-by-side copies of
    // Earth with the pins scattered across all of them (Hurley 2026-07-29).
    // Three things together fix it:
    //   noWrap        — the tile layer stops painting copies either side.
    //   maxBounds     — you can't drag off into the void where copies lived.
    //   a floor zoom  — computed below, so you can never zoom out past the
    //                   point where one world stops filling the viewport.
    // worldCopyJump is OFF: it exists to move markers to the nearest world
    // COPY, which is meaningless once there's only one.
    var MAP_WORLD = null;   // set once L is loaded
    // Smallest zoom at which a single world still covers the full width. Below
    // this Leaflet has nothing to show either side — which is what produced the
    // repeats. Recomputed on resize, since it depends on the container width.
    function _applyMapMinZoom() {{
      if (!_opsMap) return;
      var w = _opsMap.getSize().x;
      if (!w) return;
      var minZ = Math.ceil(Math.log(w / 256) / Math.LN2 * 100) / 100;
      if (!isFinite(minZ)) return;
      _opsMap.setMinZoom(minZ);
      if (_opsMap.getZoom() < minZ) _opsMap.setZoom(minZ);
    }}
    function openOpsMap() {{
      loadLeaflet().then(function () {{
        if (!_opsMap) {{
          // ±85 is the Mercator limit — past it the projection runs to infinity.
          MAP_WORLD = L.latLngBounds([[-85, -180], [85, 180]]);
          _opsMap = L.map('ops-map-canvas', {{
            worldCopyJump: false,
            maxBounds: MAP_WORLD,
            maxBoundsViscosity: 1.0,   // hard edge, no rubber-banding past it
            zoomSnap: 0.25             // so the floor zoom can be exact, not rounded up
          }}).setView([30, -20], 2);
          L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; OpenStreetMap contributors', maxZoom: 18,
            noWrap: true, bounds: MAP_WORLD
          }}).addTo(_opsMap);
          _opsMapLayer = L.layerGroup().addTo(_opsMap);
          _opsMap.on('resize', _applyMapMinZoom);
          // Sidebar close button + clicking empty map dismisses the panel.
          var sbClose = document.getElementById('msb-close');
          if (sbClose) sbClose.addEventListener('click', closeMapSidebar);
          _opsMap.on('click', closeMapSidebar);
        }}
        renderOpsMap();
        // The container was display:none at init — force a size recalc, then
        // set the zoom floor from the real width.
        setTimeout(function () {{ _opsMap.invalidateSize(); _applyMapMinZoom(); }}, 50);
      }}).catch(function () {{
        var note = document.getElementById('ops-map-note');
        if (note) note.textContent = 'Map could not load (offline or blocked CDN). Use Grid or Calendar instead.';
      }});
    }}

    function renderOpsMap() {{
      if (!_opsMapLayer) return;
      _opsMapLayer.clearLayers();
      closeMapSidebar();  // filters changed → reset the panel
      // Use the cards as the data source so the map honors the SAME filters
      // as the grid (price, buyer-rich, months, search, ...).
      var byCoord = {{}};
      var unplaced = 0, placed = 0, pastPlaced = 0, upcomingPlaced = 0;
      $opsGrid.querySelectorAll('.ops-card').forEach(function (card) {{
        // Use the filter-pass flag, NOT display — past events live in the
        // collapsed Archive group (display:none) but should still map, grayed.
        if (card.dataset.passed !== '1') return;           // failed an active filter
        if (card.classList.contains('is-archived')) return;  // user-hidden — keep off the map
        var rec = card._modalRec || {{}};
        var ll = geoOf(rec);
        if (!ll) {{ unplaced++; return; }}
        placed++;
        var cardPast = card.dataset.past === '1';
        if (cardPast) pastPlaced++; else upcomingPlaced++;
        var key = ll[0].toFixed(3) + ',' + ll[1].toFixed(3);
        var g = (byCoord[key] = byCoord[key] || {{ ll: ll, evs: [], hasUpcoming: false }});
        g.evs.push(rec);
        if (!cardPast) g.hasUpcoming = true;
      }});
      Object.keys(byCoord).forEach(function (key) {{
        var g = byCoord[key];
        var n = g.evs.length;
        // Cluster-style badge: one consistent brand color everywhere — the
        // region data is too patchy to color-code by (same metro area was
        // getting blue AND gray pins). Size alone carries the count signal.
        var size = n === 1 ? 14 : Math.min(26 + n * 1.2, 44);
        var icon = L.divIcon({{
          className: '',  // suppress Leaflet's default white square
          html: '<div class="map-pin' + (n === 1 ? ' single' : '') + (g.hasUpcoming ? '' : ' past') + '">' +
                (n === 1 ? '' : n) + '</div>',
          iconSize: [size, size],
          iconAnchor: [size / 2, size / 2],
          popupAnchor: [0, -size / 2]
        }});
        var marker = L.marker(g.ll, {{ icon: icon }}).addTo(_opsMapLayer);

        // Click a pin → slide this place's events into the right sidebar.
        marker.on('click', function () {{ openMapSidebar(g); }});
      }});
      // Recenter to fit whatever is plotted, so a filter can't leave matching
      // pins off-screen ("the map isn't showing everything"). Cap the zoom so a
      // single event doesn't slam to street level; skip if nothing's placed.
      var _pts = Object.keys(byCoord).map(function (k) {{ return byCoord[k].ll; }});
      if (_pts.length) {{
        try {{ _opsMap.fitBounds(L.latLngBounds(_pts), {{ padding: [40, 40], maxZoom: 10 }}); }} catch (e) {{}}
      }}
      var note = document.getElementById('ops-map-note');
      if (note) {{
        note.textContent = placed + ' events on the map' +
          (pastPlaced ? ' (' + upcomingPlaced + ' upcoming · ' + pastPlaced + ' past, grayed)' : '') +
          (unplaced ? ' · ' + unplaced + ' without a mappable location (Remote / TBD / Podcast)' : '') +
          ' — click a pin to list its events.';
      }}
    }}

    // Short date for the sidebar rows ("Mar 15"), from start_date when we have it.
    function _msbShortDate(r) {{
      if (r.start_date) {{
        var d = new Date(r.start_date + 'T00:00:00');
        if (!isNaN(d)) return d.toLocaleDateString('en-US', {{ month: 'short', day: 'numeric' }});
      }}
      return r.date_str || '';
    }}
    // Populate + reveal the right-hand sidebar with the events at one pin.
    function openMapSidebar(g) {{
      var sb = document.getElementById('map-sidebar');
      if (!sb) return;
      var _past = function (r) {{ return (typeof isPastEvent === 'function') && isPastEvent(r); }};
      var evs = g.evs.slice().sort(function (a, b) {{
        var ap = _past(a) ? 1 : 0, bp = _past(b) ? 1 : 0;
        if (ap !== bp) return ap - bp;  // upcoming first, past sinks to the bottom
        return String(a.start_date || a.date_str || '').localeCompare(String(b.start_date || b.date_str || ''));
      }});
      var city = (evs[0].city || (evs[0].location || '').split(',')[0] || '').trim() || 'Location';
      document.getElementById('msb-title').textContent = city;
      document.getElementById('msb-count').textContent = evs.length;
      var list = document.getElementById('msb-list');
      list.innerHTML = '';
      evs.forEach(function (r) {{
        var row = document.createElement('button');
        row.type = 'button';
        row.className = 'map-sb-ev' + (_past(r) ? ' past' : '');
        var topStage = (r.stage_tags && r.stage_tags.length && typeof mostAdvancedStage === 'function')
          ? mostAdvancedStage(r.stage_tags) : null;
        var badge = '';
        if (topStage && STAGE_BY_KEY[topStage]) {{
          var s = STAGE_BY_KEY[topStage];
          badge = '<span class="msb-badge" style="background:' + s.bg + ';color:' + s.fg + ';">' + escapeHtml(topStage) + '</span>';
        }}
        var dt = _msbShortDate(r);
        row.innerHTML = '<span class="nm">' + escapeHtml(r.name || 'Event') + '</span>' +
          '<span class="meta">' + (dt ? '<span class="dt">' + escapeHtml(dt) + '</span>' : '') + badge + '</span>';
        row.addEventListener('click', function () {{
          if (typeof window.openEventModal === 'function') window.openEventModal(r);
        }});
        list.appendChild(row);
      }});
      list.scrollTop = 0;
      sb.removeAttribute('hidden');
    }}
    function closeMapSidebar() {{
      var sb = document.getElementById('map-sidebar');
      if (sb) sb.setAttribute('hidden', '');
    }}

    // ── Calendar rendering ──────────────────────────────────────────
    var REGION_COLORS = {{
      'US & Canada':   '#2773c2',
      'Latin America': '#0ea5e9',
      'Europe':        '#7c3aed',
      'Africa':        '#db2777',
      'MENA':          '#ca8a04',
      'Asia-Pacific':  '#059669',
      'Global':        '#475569'
    }};

    function regionColor(r) {{ return REGION_COLORS[r] || '#737373'; }}
    // Light translucent tint of a hex color — used so calendar chips without a
    // pipeline stage still get a (region-colored) fill instead of blank white.
    function hexToRgba(hex, a) {{
      hex = String(hex || '').replace('#', '');
      if (hex.length === 3) hex = hex.charAt(0) + hex.charAt(0) + hex.charAt(1) + hex.charAt(1) + hex.charAt(2) + hex.charAt(2);
      var n = parseInt(hex, 16);
      if (isNaN(n)) return 'rgba(115,115,115,' + a + ')';
      return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
    }}

    function initials(name) {{
      if (!name) return '';
      var parts = String(name).trim().split(/\\s+/).filter(Boolean);
      return parts.map(function (w) {{ return w[0]; }}).join('').slice(0, 2).toUpperCase();
    }}

    function isoFromYMD(y, m, d) {{
      return y + '-' + String(m+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    }}

    function buildCalendarMonth(year, month, events, stateMap, onChipClick) {{
      var monthDiv = document.createElement('div');
      monthDiv.className = 'calendar-month';

      // The month/year now lives in the centered nav dropdown above the grid,
      // so no static title here.
      var grid = document.createElement('div');
      grid.className = 'calendar-grid';

      // Weekday header row.
      var hdr = document.createElement('div');
      hdr.className = 'cal-weekhead';
      ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].forEach(function (d) {{
        var dh = document.createElement('div');
        dh.className = 'calendar-day-head';
        dh.textContent = d;
        hdr.appendChild(dh);
      }});
      grid.appendChild(hdr);

      var firstDay = new Date(year, month, 1).getDay();
      var daysInMonth = new Date(year, month + 1, 0).getDate();
      var prevMonthDays = new Date(year, month, 0).getDate();
      var today = new Date(); today.setHours(0, 0, 0, 0);
      var todayIso = isoFromYMD(today.getFullYear(), today.getMonth(), today.getDate());
      var DAY = 86400000;

      // Build every cell of the month grid: previous-month tail, this month,
      // next-month head — padded to whole weeks.
      var cells = [];
      for (var i = 0; i < firstDay; i++) {{
        var dn = prevMonthDays - firstDay + i + 1;
        var pm = new Date(year, month - 1, dn);
        cells.push({{ iso: isoFromYMD(pm.getFullYear(), pm.getMonth(), pm.getDate()), day: dn, outside: true }});
      }}
      for (var day = 1; day <= daysInMonth; day++) {{
        cells.push({{ iso: isoFromYMD(year, month, day), day: day, outside: false }});
      }}
      var trail = (Math.ceil(cells.length / 7) * 7) - cells.length;
      for (var t = 1; t <= trail; t++) {{
        var nm = new Date(year, month + 1, t);
        cells.push({{ iso: isoFromYMD(nm.getFullYear(), nm.getMonth(), nm.getDate()), day: t, outside: true }});
      }}
      cells.forEach(function (c) {{ c.ms = new Date(c.iso + 'T00:00:00Z').getTime(); }});
      var calStartMs = cells[0].ms, calEndMs = cells[cells.length - 1].ms;

      // Resolve ops state for an event (catalog → event_state; manual → baked on).
      function stOf(ev) {{
        return ev._manual
          ? {{ status_tags: ev._manualStatusTags, speaker: ev._manualSpeaker, hidden: ev._manualHidden }}
          : (stateMap[ev.num] || {{}});
      }}

      // Each visible event becomes a span clamped to the grid's date range.
      var spans = [];
      events.forEach(function (ev) {{
        if (!ev.start_date) return;
        var st = stOf(ev);
        if (st.hidden) return;
        var sMs = new Date(ev.start_date + 'T00:00:00Z').getTime();
        var eMs = new Date((ev.end_date || ev.start_date) + 'T00:00:00Z').getTime();
        if (isNaN(sMs)) return;
        if (isNaN(eMs) || eMs < sMs) eMs = sMs;
        if (eMs < calStartMs || sMs > calEndMs) return;
        spans.push({{ ev: ev, st: st, sMs: Math.max(sMs, calStartMs), eMs: Math.min(eMs, calEndMs) }});
      }});

      var weeks = Math.ceil(cells.length / 7);
      for (var w = 0; w < weeks; w++) {{
        var weekCells = cells.slice(w * 7, w * 7 + 7);
        var weekStartMs = weekCells[0].ms, weekEndMs = weekCells[6].ms;
        var weekDiv = document.createElement('div');
        weekDiv.className = 'cal-week';

        // Background day cells + date numbers (each occupies one column; the
        // background spans every row so event lanes sit on top of it).
        weekCells.forEach(function (c, ci) {{
          var bg = document.createElement('div');
          bg.className = 'cal-day-bg' + (c.outside ? ' is-outside' : '') + (c.iso === todayIso ? ' is-today' : '');
          bg.style.gridColumn = (ci + 1);
          bg.style.gridRow = '1 / -1';
          weekDiv.appendChild(bg);
          var num = document.createElement('div');
          num.className = 'cal-daynum' + (c.outside ? ' is-outside' : '');
          num.style.gridColumn = (ci + 1);
          num.style.gridRow = '1';
          num.textContent = c.day;
          weekDiv.appendChild(num);
        }});

        // Event segments that intersect this week → one contiguous bar each.
        var weekSpans = spans.filter(function (sp) {{
          return sp.eMs >= weekStartMs && sp.sMs <= weekEndMs;
        }}).map(function (sp) {{
          var segStart = Math.max(sp.sMs, weekStartMs);
          var segEnd = Math.min(sp.eMs, weekEndMs);
          var startCol = Math.round((segStart - weekStartMs) / DAY);
          var endCol = Math.round((segEnd - weekStartMs) / DAY);
          return {{ sp: sp, startCol: startCol, span: (endCol - startCol + 1) }};
        }}).sort(function (a, b) {{
          return a.startCol - b.startCol || b.span - a.span;
        }});

        // Greedy lane packing so overlapping events stack vertically.
        var lanes = [];
        weekSpans.forEach(function (ws) {{
          var endCol = ws.startCol + ws.span - 1;
          var lane = 0;
          while ((lanes[lane] || []).some(function (r) {{ return !(endCol < r[0] || ws.startCol > r[1]); }})) lane++;
          (lanes[lane] = lanes[lane] || []).push([ws.startCol, endCol]);
          ws.lane = lane;
        }});

        // Pack the date-number row + each event lane as tight auto rows, then a
        // flexible filler row that soaks up the rest of the cell height. Without
        // this the day-cell min-height inflates row 1 (the date number) and the
        // events float far below it; this keeps them right under the date.
        weekDiv.style.gridTemplateRows = 'repeat(' + (lanes.length + 1) + ', auto) 1fr';

        weekSpans.forEach(function (ws) {{
          var ev = ws.sp.ev, st = ws.sp.st;
          var bar = document.createElement('div');
          bar.className = 'cal-evt';
          if (st.saved) bar.classList.add('is-saved');
          if (st.urgent || isDeadlineUrgent(ev.deadline)) bar.classList.add('is-urgent');
          bar.dataset.eventNum = ev.num;
          // Keyboard-reachable: a calendar chip is the only non-button control,
          // so give it button semantics + Enter/Space activation.
          bar.setAttribute('role', 'button');
          bar.tabIndex = 0;
          bar.setAttribute('aria-label', 'Open ' + (ev.name || 'event'));
          bar.style.gridColumn = (ws.startCol + 1) + ' / span ' + ws.span;
          bar.style.gridRow = (ws.lane + 2);
          var calStages = stageTagsOf(st);
          // Calendar shows ONLY the three priority blocks — Submitted (blue),
          // Booked (green), Attending (teal) — everything else stays grey. This
          // kills the old region-color vs stage-color collision (Europe-purple
          // read as 'Meeting held'-purple) and matches Angela's "color the
          // status changes, keep the rest grey" ask.
          var calBlock = calStages.indexOf('Booked') !== -1 ? 'Booked'
                       : calStages.indexOf('Attending') !== -1 ? 'Attending'
                       : calStages.indexOf('Submitted') !== -1 ? 'Submitted' : null;
          if (calBlock && STAGE_BY_KEY[calBlock]) {{
            bar.style.background = STAGE_BY_KEY[calBlock].bg;
            bar.style.borderLeftColor = STAGE_BY_KEY[calBlock].dot;
          }} else {{
            bar.style.background = '#f3f4f6';
            bar.style.borderLeftColor = '#d1d5db';
          }}
          var sp2 = st.speaker || '';
          var ini = sp2 ? initials(sp2) : '';
          var statusInline = '';
          if (calBlock && STAGE_BY_KEY[calBlock]) {{
            var s = STAGE_BY_KEY[calBlock];
            statusInline = '<span class="cal-evt-status" style="background:' + s.bg + ';color:' + s.fg + ';">' + escapeHtml(calBlock) + '</span>';
          }}
          bar.innerHTML =
            '<span class="cal-evt-name">' + escapeHtml(ev.name) + '</span>' +
            (ini ? '<span class="cal-chip-initial" title="' + escapeHtml(sp2) + '">' + escapeHtml(ini) + '</span>' : '') +
            statusInline;
          bar.title = ev.name +
            (sp2 ? ' · Speaker: ' + sp2 : '') +
            (ev.location ? ' · ' + ev.location : '') +
            (calStages.length ? ' · ' + calStages.join(', ') : '') +
            (ev.end_date && ev.end_date !== ev.start_date ? ' · ' + ev.start_date + ' to ' + ev.end_date : '');
          bar.addEventListener('click', function () {{ onChipClick(ev.num); }});
          bar.addEventListener('keydown', function (e) {{
            if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); onChipClick(ev.num); }}
          }});
          weekDiv.appendChild(bar);
        }});

        grid.appendChild(weekDiv);
      }}

      monthDiv.appendChild(grid);
      return monthDiv;
    }}

    // Cached full calendar inputs so we can re-render with the live filters
    // applied — the calendar honors the SAME filters as the grid.
    var _calEvents = null, _calStateMap = null, _calManual = null;
    function recalcCalendar() {{ if (_calEvents) renderCalendar(_calEvents, _calStateMap, _calManual); }}
    // Which events passed the active grid filters? Keyed to the calendar's
    // ev.num (catalog = event_num, manual = 'm'+id). active=false when nothing
    // is filtered out, so an unfiltered calendar shows every event.
    function opsCalPassed() {{
      var map = {{}}, total = 0, passed = 0;
      var cards = $opsGrid ? $opsGrid.querySelectorAll('.ops-card') : [];
      Array.prototype.forEach.call(cards, function (c) {{
        total++;
        var key = c.dataset.manualId ? ('m' + c.dataset.manualId) : c.dataset.eventNum;
        if (c.dataset.passed === '1') {{ map[String(key)] = 1; passed++; }}
      }});
      return {{ map: map, active: total > 0 && passed < total }};
    }}
    function renderCalendar(events, stateMap, manualEvents) {{
      var cal = document.getElementById('ops-calendar');
      if (!cal) return;
      cal.innerHTML = '';
      _calEvents = events; _calStateMap = stateMap; _calManual = manualEvents;

      // Combine regular + manual events. Manual events use bigserial id namespace
      // distinct from event_num, so we tag them so the click handler can find
      // them in the ops-grid by data-manual-id instead.
      var combined = events.slice();
      (manualEvents || []).forEach(function (m) {{
        if (!m.start_date) {{
          var derived = deriveDatesFromText(m.date_str);
          if (derived.start_date) m = Object.assign({{}}, m, {{ start_date: derived.start_date, end_date: m.end_date || derived.end_date }});
        }}
        combined.push({{
          num: 'm' + m.id,
          _manual: true,
          _manualId: m.id,
          name: m.name,
          start_date: m.start_date,
          end_date: m.end_date || m.start_date,
          location: m.location || '',
          region: m.region || '',
          date_str: m.date_str || '',
          deadline: m.deadline || '',
          // Hoist Angela's ops fields onto the calendar entry so the chip
          // can color-tint by pipeline stage + show speaker initials.
          _manualStatus:     m.status || '',
          _manualStatusTags: m.status_tags || [],
          _manualSpeaker:    m.speaker || '',
          _manualHidden:     !!m.hidden
        }});
      }});

      // Drop duplicate events the grid collapsed, so the calendar (and its
      // export) never double-books an event. Same pass collects the events the
      // signed-in person ARCHIVED: archiving is "hide this from MY view", so an
      // archived event must not clutter the calendar either (Angela was checking
      // what clashed with Thor's Munich trip and hit exactly this). The map
      // already skips is-archived cards — the calendar was the one view that
      // didn't. Read the class off the card so per-person archiving, catalog and
      // manual events are all handled by one rule.
      var _dupSet = {{}}, _archSet = {{}};
      Array.prototype.forEach.call($opsGrid ? $opsGrid.querySelectorAll('.ops-card') : [], function (c) {{
        var _k = String(c.dataset.manualId ? ('m' + c.dataset.manualId) : c.dataset.eventNum);
        if (c.dataset.dupHidden === '1') _dupSet[_k] = 1;
        if (c.classList.contains('is-archived')) _archSet[_k] = 1;
      }});
      combined = combined.filter(function (ev) {{ return !_dupSet[String(ev.num)] && !_archSet[String(ev.num)]; }});
      // Honor the active grid filters (stage chips, search, price, region, …):
      // when something is filtered, drop calendar events whose card didn't pass.
      var _pf = opsCalPassed();
      if (_pf.active) combined = combined.filter(function (ev) {{ return _pf.map[String(ev.num)]; }});

      // Determine month range
      var earliest = null, latest = null;
      combined.forEach(function (ev) {{
        if (!ev.start_date) return;
        // Parse as LOCAL midnight (not UTC) so getMonth() matches the ISO
        // string's month — a bare new Date('2026-06-01') is UTC and rolls back
        // a day in the Americas, prepending a spurious empty month here.
        var d = new Date(ev.start_date + 'T00:00:00');
        if (isNaN(d)) return;
        if (!earliest || d < earliest) earliest = d;
        if (!latest || d > latest) latest = d;
      }});
      if (!earliest) {{
        cal.innerHTML = '<p class="alert">No events with dates to display on the calendar yet.</p>';
        return;
      }}
      // Always include current month even if no events
      var now = new Date(); now.setDate(1);
      if (now < earliest) earliest = now;
      // Cap at Dec 2027 to prevent runaway in case of bad data
      var capDate = new Date(2027, 11, 1);
      if (latest > capDate) latest = capDate;

      // Enumerate every month in the range so the dropdown shows the full menu.
      var months = [];
      var y = earliest.getFullYear(), m = earliest.getMonth();
      var endY = latest.getFullYear(), endM = latest.getMonth();
      var guard = 0;
      while ((y < endY || (y === endY && m <= endM)) && guard++ < 48) {{
        months.push({{ y: y, m: m, key: y + '-' + String(m + 1).padStart(2, '0') }});
        m++;
        if (m > 11) {{ m = 0; y++; }}
      }}
      if (months.length === 0) {{
        cal.innerHTML = '<p class="alert">No events with dates to display on the calendar yet.</p>';
        return;
      }}

      // Always open on the CURRENT month (if it has events), else the first
      // month with events — don't reopen wherever you last browsed to.
      var todayKey = new Date().getFullYear() + '-' + String(new Date().getMonth() + 1).padStart(2, '0');
      var defaultKey = months.some(function (x) {{ return x.key === todayKey; }}) ? todayKey : months[0].key;

      // Clean month nav: ‹ prev on the far left, the month/year dropdown
      // centered, next › on the far right (no event count).
      var headerWrap = document.createElement('div');
      headerWrap.className = 'cal-nav';
      headerWrap.innerHTML =
        '<button type="button" id="cal-prev" class="cal-navbtn" aria-label="Previous month">\\u2039</button>' +
        '<select id="cal-month-select" class="cal-month-select" aria-label="Jump to month">' +
          months.map(function (m) {{
            var label = new Date(m.y, m.m, 1).toLocaleString('en-US', {{ month: 'long', year: 'numeric' }});
            return '<option value="' + m.key + '"' + (m.key === defaultKey ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
          }}).join('') +
        '</select>' +
        '<button type="button" id="cal-next" class="cal-navbtn" aria-label="Next month">\\u203a</button>';
      cal.appendChild(headerWrap);

      var monthHost = document.createElement('div');
      monthHost.id = 'cal-month-host';
      cal.appendChild(monthHost);

      // Legend: just the three priority color-blocks + grey for everything else.
      // (Region colors were removed — they collided with the stage colors.)
      var legend = document.createElement('div');
      legend.className = 'cal-legend';
      legend.innerHTML =
        '<span class="cal-legend-label">Calendar key:</span>' +
        ['Submitted', 'Booked', 'Attending'].map(function (k) {{
          return '<span class="cal-legend-pill" style="' + stageStyle(k) + '">' + escapeHtml(k) + '</span>';
        }}).join('') +
        '<span class="cal-legend-pill" style="background:#f3f4f6;color:#6b7280;">Other / no status</span>';
      cal.appendChild(legend);

      function onChipClick(num) {{
        var selector = String(num).charAt(0) === 'm'
          ? '.ops-card[data-manual-id="' + String(num).slice(1) + '"]'
          : '.ops-card[data-event-num="' + num + '"]';
        var card = $opsGrid.querySelector(selector);
        // Primary behaviour: open the rich detail pop-up straight from the
        // calendar so a click goes to the event, not just a scroll-to-card.
        if (card && card._modalRec && typeof window.openEventModal === 'function') {{
          window.openEventModal(card._modalRec);
          return;
        }}
        // Fallback (card not built yet / no stashed record): jump + flash.
        setView('grid');
        if (card) {{
          card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          card.classList.remove('is-highlight');
          void card.offsetWidth;
          card.classList.add('is-highlight');
          setTimeout(function () {{ card.classList.remove('is-highlight'); }}, 1700);
        }}
      }}

      function renderMonthByKey(key) {{
        var match = months.filter(function (x) {{ return x.key === key; }})[0];
        if (!match) match = months[0];
        monthHost.innerHTML = '';
        monthHost.appendChild(buildCalendarMonth(match.y, match.m, combined, stateMap, onChipClick));
        var sel = document.getElementById('cal-month-select');
        if (sel) sel.value = match.key;
      }}

      var sel = headerWrap.querySelector('#cal-month-select');
      sel.addEventListener('change', function () {{ renderMonthByKey(sel.value); }});

      function step(delta) {{
        var idx = months.findIndex(function (x) {{ return x.key === sel.value; }});
        var next = Math.max(0, Math.min(months.length - 1, idx + delta));
        renderMonthByKey(months[next].key);
      }}
      headerWrap.querySelector('#cal-prev').addEventListener('click', function () {{ step(-1); }});
      headerWrap.querySelector('#cal-next').addEventListener('click', function () {{ step(1); }});

      renderMonthByKey(defaultKey);
    }}

    // Parses a free-form event date_str into ISO start_date + end_date.
    // Handles three common shapes:
    //   "Month D, YYYY"             → start == end (single all-day)
    //   "Month D1–D2, YYYY"         → same-month range
    //   "Month1 D1 – Month2 D2, YYYY" → cross-month range
    // Returns {{ start_date, end_date }}; either may be null if the parse fails.
    function deriveDatesFromText(text) {{
      var out = {{ start_date: null, end_date: null }};
      if (!text) return out;
      var months = {{january:1,february:2,march:3,april:4,may:5,june:6,
                    july:7,august:8,september:9,october:10,november:11,december:12,
                    jan:1,feb:2,mar:3,apr:4,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12}};
      function pad(n) {{ return String(n).padStart(2, '0'); }}
      function iso(y, m, d) {{ return y + '-' + pad(m) + '-' + pad(d); }}
      var s = String(text);

      // 1. Cross-month range — "Month D – Month D, YYYY"
      var m1 = s.match(/([A-Za-z]+)\\s+(\\d{{1,2}})\\s*[–—-]\\s*([A-Za-z]+)\\s+(\\d{{1,2}}),?\\s+(\\d{{4}})/);
      if (m1) {{
        var ma = months[m1[1].toLowerCase()], mb = months[m1[3].toLowerCase()];
        if (ma && mb) {{
          var y1 = parseInt(m1[5], 10);
          out.start_date = iso(y1, ma, parseInt(m1[2], 10));
          out.end_date   = iso(y1, mb, parseInt(m1[4], 10));
          return out;
        }}
      }}
      // 2. Same-month range — "Month D1–D2, YYYY"
      var m2 = s.match(/([A-Za-z]+)\\s+(\\d{{1,2}})\\s*[–—-]\\s*(\\d{{1,2}}),?\\s+(\\d{{4}})/);
      if (m2) {{
        var mn2 = months[m2[1].toLowerCase()];
        if (mn2) {{
          var y2 = parseInt(m2[4], 10);
          out.start_date = iso(y2, mn2, parseInt(m2[2], 10));
          out.end_date   = iso(y2, mn2, parseInt(m2[3], 10));
          return out;
        }}
      }}
      // 3. Single date — "Month D, YYYY"
      var m3 = s.match(/([A-Za-z]+)\\s+(\\d{{1,2}}),?\\s+(\\d{{4}})/);
      if (m3) {{
        var mn3 = months[m3[1].toLowerCase()];
        if (mn3) {{
          var d3 = iso(parseInt(m3[3], 10), mn3, parseInt(m3[2], 10));
          out.start_date = d3;
          out.end_date   = d3;
          return out;
        }}
      }}
      // 3b. DAY-FIRST cross-month range — "D Month – D Month YYYY"
      var df1 = s.match(/(\\d{{1,2}})\\s+([A-Za-z]+)\\s*[–—-]\\s*(\\d{{1,2}})\\s+([A-Za-z]+),?\\s+(\\d{{4}})/);
      if (df1) {{
        var dfa = months[df1[2].toLowerCase()], dfb = months[df1[4].toLowerCase()];
        if (dfa && dfb) {{
          var dfy = parseInt(df1[5], 10);
          out.start_date = iso(dfy, dfa, parseInt(df1[1], 10));
          out.end_date   = iso(dfy, dfb, parseInt(df1[3], 10));
          return out;
        }}
      }}
      // 3c. DAY-FIRST same-month range — "D–D Month YYYY"  (e.g. "4-6 May 2027")
      var df2 = s.match(/(\\d{{1,2}})\\s*[–—-]\\s*(\\d{{1,2}})\\s+([A-Za-z]+),?\\s+(\\d{{4}})/);
      if (df2) {{
        var dfm = months[df2[3].toLowerCase()];
        if (dfm) {{
          var dfy2 = parseInt(df2[4], 10);
          out.start_date = iso(dfy2, dfm, parseInt(df2[1], 10));
          out.end_date   = iso(dfy2, dfm, parseInt(df2[2], 10));
          return out;
        }}
      }}
      // 3d. DAY-FIRST single — "D Month YYYY"  (e.g. "4 May 2027")
      var df3 = s.match(/(\\d{{1,2}})\\s+([A-Za-z]+),?\\s+(\\d{{4}})/);
      if (df3) {{
        var dfm3 = months[df3[2].toLowerCase()];
        if (dfm3) {{
          var dfd = iso(parseInt(df3[3], 10), dfm3, parseInt(df3[1], 10));
          out.start_date = dfd; out.end_date = dfd;
          return out;
        }}
      }}
      // 3e. ISO — "YYYY-MM-DD" (optionally a range)
      var dfi = s.match(/(\\d{{4}})-(\\d{{1,2}})-(\\d{{1,2}})(?:\\s*[–—-]\\s*(\\d{{4}})-(\\d{{1,2}})-(\\d{{1,2}}))?/);
      if (dfi) {{
        out.start_date = iso(parseInt(dfi[1], 10), parseInt(dfi[2], 10), parseInt(dfi[3], 10));
        out.end_date   = dfi[4] ? iso(parseInt(dfi[4], 10), parseInt(dfi[5], 10), parseInt(dfi[6], 10)) : out.start_date;
        return out;
      }}
      // 3f. Month + year only — "Month YYYY"  (e.g. "May 2027") -> 1st of month
      var dfmy = s.match(/([A-Za-z]+)\\s+(\\d{{4}})/);
      if (dfmy) {{
        var dmy = months[dfmy[1].toLowerCase()];
        if (dmy) {{
          var dmyd = iso(parseInt(dfmy[2], 10), dmy, 1);
          out.start_date = dmyd; out.end_date = dmyd;
          return out;
        }}
      }}

      // 4-6. Numeric shorthand — Angela's spreadsheet habit: "4/28",
      // "4/28-4/30", "11/9 - 11/12/26", "4/28-30". A missing year is
      // forward-looking: assume the current year, roll to next year when the
      // date passed more than ~6 weeks ago.
      function yr(t) {{
        if (!t) return null;
        var y = parseInt(t, 10);
        return y < 100 ? y + 2000 : y;
      }}
      function inferYear(mo, d) {{
        var now = new Date();
        var y = now.getFullYear();
        if (now - new Date(y, mo - 1, d) > 45 * 86400000) y += 1;
        return y;
      }}
      function okMD(mo, d) {{ return mo >= 1 && mo <= 12 && d >= 1 && d <= 31; }}
      // 4. "M/D - M/D" with optional years on either side
      var n1 = s.match(/(\\d{{1,2}})\\/(\\d{{1,2}})(?:\\/(\\d{{2,4}}))?\\s*[–—-]\\s*(\\d{{1,2}})\\/(\\d{{1,2}})(?:\\/(\\d{{2,4}}))?/);
      if (n1) {{
        var a1 = parseInt(n1[1], 10), a2 = parseInt(n1[2], 10);
        var b1 = parseInt(n1[4], 10), b2 = parseInt(n1[5], 10);
        if (okMD(a1, a2) && okMD(b1, b2)) {{
          var ya = yr(n1[3]) || yr(n1[6]) || inferYear(a1, a2);
          var yb = yr(n1[6]) || ya;
          if (yb === ya && (b1 < a1)) yb = ya + 1;  // 12/30 - 1/2 wraps year
          out.start_date = iso(ya, a1, a2);
          out.end_date   = iso(yb, b1, b2);
          return out;
        }}
      }}
      // 5. "M/D - D" (same month) with optional year — incl. a trailing
      //    comma-year like "9/10-12, 2026" (n2[5]); prefer it over inference.
      var n2 = s.match(/(\\d{{1,2}})\\/(\\d{{1,2}})(?:\\/(\\d{{2,4}}))?\\s*[–—-]\\s*(\\d{{1,2}})(?!\\d*\\/)(?:,?\\s*(\\d{{2,4}}))?/);
      if (n2) {{
        var c1 = parseInt(n2[1], 10), c2 = parseInt(n2[2], 10), c3 = parseInt(n2[4], 10);
        if (okMD(c1, c2) && c3 >= 1 && c3 <= 31) {{
          var yc = yr(n2[3]) || yr(n2[5]) || inferYear(c1, c2);
          out.start_date = iso(yc, c1, c2);
          out.end_date   = iso(yc, c1, c3);
          return out;
        }}
      }}
      // 6. Single "M/D" with optional year
      var n3 = s.match(/(\\d{{1,2}})\\/(\\d{{1,2}})(?:\\/(\\d{{2,4}}))?/);
      if (n3) {{
        var e1 = parseInt(n3[1], 10), e2 = parseInt(n3[2], 10);
        if (okMD(e1, e2)) {{
          var ye = yr(n3[3]) || inferYear(e1, e2);
          var de = iso(ye, e1, e2);
          out.start_date = de;
          out.end_date   = de;
          return out;
        }}
      }}
      return out;
    }}

    // Back-compat shim — older callers want just the start date.
    function deriveStartDateFromText(text) {{
      return deriveDatesFromText(text).start_date;
    }}

    // ── Realtime subscription ───────────────────────────────────────
    // The echo triggers a FULL grid rebuild. If the user is mid-edit (typing
    // into an open editor), rebuilding would throw away their unsaved input —
    // so while an editor is focused we just mark the refresh as pending and
    // flush it the moment the editor closes / loses focus.
    var _opsEchoPending = false;
    function gridHasActiveEditor() {{
      if (!$opsGrid) return false;
      var ed = $opsGrid.querySelector('details.ops-edit[open]');
      return !!(ed && document.activeElement && ed.contains(document.activeElement));
    }}
    function opsEchoRender(email) {{
      if (gridHasActiveEditor()) {{ _opsEchoPending = true; return; }}
      _opsEchoPending = false;
      renderOps(email);
    }}
    function wireEchoFlush(email) {{
      if ($opsGrid.dataset.echoWired) return;
      $opsGrid.dataset.echoWired = '1';
      function maybeFlush() {{
        if (!_opsEchoPending) return;
        // Wait a tick so focus has settled (toggle/focusout fire pre-move).
        setTimeout(function () {{
          if (_opsEchoPending && !gridHasActiveEditor()) {{
            _opsEchoPending = false;
            renderOps(email);
          }}
        }}, 150);
      }}
      $opsGrid.addEventListener('toggle', maybeFlush, true);
      $opsGrid.addEventListener('focusout', maybeFlush);
    }}

    var realtimeChannel = null;
    function setupRealtime(email) {{
      wireEchoFlush(email);
      if (realtimeChannel) {{
        try {{ realtimeChannel.unsubscribe(); }} catch (e) {{}}
        realtimeChannel = null;
      }}
      try {{
        realtimeChannel = sb.channel('ops-realtime-' + Math.random().toString(36).slice(2,8))
          .on('postgres_changes', {{ event: '*', schema: 'public', table: 'event_state' }}, function () {{
            opsEchoRender(email);
          }})
          .on('postgres_changes', {{ event: '*', schema: 'public', table: 'manual_events' }}, function () {{
            opsEchoRender(email);
          }})
          .on('postgres_changes', {{ event: '*', schema: 'public', table: 'event_chat' }}, function () {{
            if (typeof loadChatCounts === 'function') loadChatCounts();
            if (typeof _reloadOpenChat === 'function') _reloadOpenChat();
          }})
          .subscribe();
      }} catch (e) {{
        // Realtime is a nice-to-have; if it fails, polling on user action still works
        console.warn('Realtime setup failed:', e);
      }}
    }}

    // ── CSV import/export ───────────────────────────────────────────
    var CSV_COLUMNS = ['event_num','status_tags','status','speaker','priority_override','track','saved','hidden','urgent','notes','attend_verdict','postmortem'];
    // Optional on import: older CSVs predate these. When the column is absent
    // we leave the existing DB value untouched instead of wiping it.
    var CSV_OPTIONAL = ['status_tags','attend_verdict','postmortem'];

    function toCsvCell(v) {{
      if (v === null || v === undefined) return '';
      v = String(v);
      if (v.indexOf(',') >= 0 || v.indexOf('"') >= 0 || v.indexOf('\\n') >= 0) {{
        return '"' + v.replace(/"/g, '""') + '"';
      }}
      return v;
    }}

    function rowsToCsv(headers, rows) {{
      var lines = [headers.map(toCsvCell).join(',')];
      rows.forEach(function (row) {{
        lines.push(headers.map(function (h) {{ return toCsvCell(row[h]); }}).join(','));
      }});
      return lines.join('\\n') + '\\n';
    }}

    function parseCsvLine(line) {{
      var cells = []; var i = 0, current = '', inQuote = false;
      while (i < line.length) {{
        var ch = line[i];
        if (inQuote) {{
          if (ch === '"') {{
            if (line[i+1] === '"') {{ current += '"'; i += 2; continue; }}
            inQuote = false; i++; continue;
          }}
          current += ch; i++;
        }} else {{
          if (ch === '"') {{ inQuote = true; i++; continue; }}
          if (ch === ',') {{ cells.push(current); current = ''; i++; continue; }}
          current += ch; i++;
        }}
      }}
      cells.push(current);
      return cells;
    }}

    function parseCsv(text) {{
      // Strip BOM, normalize newlines
      text = text.replace(/^\\uFEFF/, '').replace(/\\r\\n?/g, '\\n');
      // Handle multi-line quoted cells by walking the string
      var rows = []; var i = 0; var cur = ''; var rowCells = []; var inQ = false;
      while (i < text.length) {{
        var ch = text[i];
        if (inQ) {{
          if (ch === '"') {{
            if (text[i+1] === '"') {{ cur += '"'; i += 2; continue; }}
            inQ = false; i++; continue;
          }}
          cur += ch; i++;
        }} else {{
          if (ch === '"') {{ inQ = true; i++; continue; }}
          if (ch === ',') {{ rowCells.push(cur); cur = ''; i++; continue; }}
          if (ch === '\\n') {{ rowCells.push(cur); rows.push(rowCells); rowCells = []; cur = ''; i++; continue; }}
          cur += ch; i++;
        }}
      }}
      if (cur !== '' || rowCells.length > 0) {{ rowCells.push(cur); rows.push(rowCells); }}
      if (rows.length === 0) return {{ headers: [], rows: [] }};
      var headers = rows[0].map(function (h) {{ return h.trim(); }});
      var data = rows.slice(1).filter(function (r) {{ return r.some(function (c) {{ return c && c.trim().length > 0; }}); }})
        .map(function (cells) {{
          var obj = {{}};
          headers.forEach(function (h, idx) {{ obj[h] = cells[idx] !== undefined ? cells[idx] : ''; }});
          return obj;
        }});
      return {{ headers: headers, rows: data }};
    }}

    function coerceCsvValue(col, raw) {{
      var v = (raw == null) ? '' : String(raw).trim();
      if (col === 'event_num') {{
        if (!v) return null;
        var n = parseInt(v, 10);
        return Number.isFinite(n) ? n : null;
      }}
      if (col === 'saved' || col === 'hidden' || col === 'urgent') {{
        if (/^(true|1|yes|y|on)$/i.test(v)) return true;
        if (/^(false|0|no|n|off|)$/i.test(v)) return false;
        return false;
      }}
      // Pipeline stages — pipe-separated list → normalized text[] array.
      if (col === 'status_tags') {{
        return normalizeStageTags(v.split('|'));
      }}
      // Text columns: empty becomes null so we don't blow away NULLs to ''
      return v === '' ? null : v;
    }}

    function downloadCsv(filename, csvText) {{
      var blob = new Blob([csvText], {{ type: 'text/csv;charset=utf-8;' }});
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click();
      setTimeout(function () {{ URL.revokeObjectURL(url); a.remove(); }}, 0);
    }}

    function diffRows(currentRows, incomingRows) {{
      var byNum = {{}};
      currentRows.forEach(function (r) {{ byNum[r.event_num] = r; }});
      var added = [], updated = [], unchanged = [];
      incomingRows.forEach(function (row) {{
        if (row.event_num == null) return; // skip invalid
        var existing = byNum[row.event_num];
        if (!existing) {{ added.push(row); return; }}
        var changed = CSV_COLUMNS.some(function (c) {{
          if (c === 'event_num') return false;
          var a = existing[c]; var b = row[c];
          if (b === undefined) return false; // column not supplied by this import
          if (a === null && b === null) return false;
          if (a === false && (b === null || b === false)) return false;
          if (b === false && (a === null || a === false)) return false;
          return String(a == null ? '' : a) !== String(b == null ? '' : b);
        }});
        (changed ? updated : unchanged).push(row);
      }});
      return {{ added: added, updated: updated, unchanged: unchanged }};
    }}

    // ── Toolbar panels: universal ✕ + Esc dismiss ────────────────────
    // Every toolbar panel (Add manually / Find new / Paste email / Ask AI /
    // Spreadsheet / Calendar sync) is a `.add-event-card` injected at the top of
    // the grid. Give each a standard top-right ✕, and let Esc close whichever is
    // open — the familiar way to back out of a panel. (The event modal, when
    // open, keeps Esc priority since it sits on top.)
    function _mountPanelClose(panel) {{
      if (!panel || panel.querySelector('.ops-panel-x')) return;
      var x = document.createElement('button');
      x.type = 'button'; x.className = 'ops-panel-x';
      x.setAttribute('aria-label', 'Close'); x.title = 'Close (Esc)';
      x.innerHTML = '&times;';
      x.addEventListener('click', function () {{ panel.remove(); }});
      panel.appendChild(x);
    }}
    if (!window._opsPanelEscWired) {{
      window._opsPanelEscWired = true;
      document.addEventListener('keydown', function (e) {{
        if (e.key !== 'Escape') return;
        var ov = document.getElementById('event-modal');
        if (ov && !ov.hasAttribute('hidden')) return;   // modal owns Esc while open
        var panel = $opsGrid && $opsGrid.querySelector(':scope > .add-event-card');
        if (panel) panel.remove();
      }});
    }}

    function openCsvPanel(email) {{
      // Toggle close if open
      var existing = document.getElementById('csv-panel');
      if (existing) {{ existing.remove(); return; }}

      var panel = document.createElement('div');
      panel.id = 'csv-panel';
      panel.className = 'add-event-card';
      panel.innerHTML =
        '<h3>CSV import / export</h3>' +
        '<p style="margin:0 0 12px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          'Export current ops state as CSV, edit in any spreadsheet tool, then re-upload. ' +
          'Columns: <code>' + CSV_COLUMNS.join(', ') + '</code>. Booleans: <code>true</code> / <code>false</code>. ' +
          '<code>status_tags</code> is a pipe-joined list of pipeline stages, e.g. <code>Submitted|Meeting held|Booked</code> (optional — omit the column to leave stages untouched).' +
        '</p>' +
        '<div class="add-actions" style="margin-bottom:8px;">' +
          '<button type="button" class="primary" id="csv-export-btn">Download current CSV</button>' +
          '<label class="primary" style="cursor:pointer;display:inline-flex;align-items:center;padding:9px 16px;background:var(--ab-fg);color:var(--ab-bg);border-radius:8px;font-weight:600;font-size:0.9rem;">' +
            'Upload CSV…' +
            '<input type="file" id="csv-file" accept=".csv,text/csv" style="display:none;">' +
          '</label>' +
          '<button type="button" class="secondary" id="csv-cancel-btn">Close</button>' +
        '</div>' +
        '<div id="csv-preview" style="margin-top:8px;"></div>';

      $opsGrid.insertBefore(panel, $opsGrid.firstChild);
      _mountPanelClose(panel);
      panel.querySelector('#csv-cancel-btn').addEventListener('click', function () {{ panel.remove(); }});

      // Export current state
      panel.querySelector('#csv-export-btn').addEventListener('click', function () {{
        sb.from('event_state').select('*').order('event_num').then(function (resp) {{
          if (resp.error) {{ status('Export failed: ' + resp.error.message, 'error'); return; }}
          var rows = resp.data || [];
          // If empty, give a header-only template
          if (rows.length === 0) rows = [];
          // Flatten the status_tags text[] into a pipe-joined string so it
          // round-trips cleanly through a spreadsheet (no comma collisions).
          rows = rows.map(function (r) {{
            var c = Object.assign({{}}, r);
            c.status_tags = Array.isArray(c.status_tags) ? c.status_tags.join('|') : (c.status_tags || '');
            return c;
          }});
          var csv = rowsToCsv(CSV_COLUMNS, rows);
          var stamp = new Date().toISOString().slice(0,10);
          downloadCsv('event_state_' + stamp + '.csv', csv);
          flashOk('CSV downloaded');
        }});
      }});

      // Upload + preview
      panel.querySelector('#csv-file').addEventListener('change', function (ev) {{
        var file = ev.target.files && ev.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function () {{
          var text = String(reader.result || '');
          var parsed = parseCsv(text);
          // Validate headers (optional columns excluded from the required set)
          var missing = CSV_COLUMNS.filter(function (c) {{ return CSV_OPTIONAL.indexOf(c) === -1 && parsed.headers.indexOf(c) === -1; }});
          var $prev = panel.querySelector('#csv-preview');
          if (parsed.rows.length === 0) {{
            $prev.innerHTML = '<p class="alert error">CSV looks empty.</p>';
            return;
          }}
          if (missing.length > 0) {{
            $prev.innerHTML = '<p class="alert error">Missing required columns: ' + missing.map(escapeHtml).join(', ') + '. Use the download button to grab a valid template.</p>';
            return;
          }}
          // Coerce types
          var coerced = parsed.rows.map(function (row) {{
            var out = {{}};
            CSV_COLUMNS.forEach(function (c) {{
              // Optional columns absent from this CSV stay undefined → untouched
              if (CSV_OPTIONAL.indexOf(c) !== -1 && parsed.headers.indexOf(c) === -1) return;
              out[c] = coerceCsvValue(c, row[c]);
            }});
            return out;
          }}).filter(function (r) {{ return r.event_num !== null; }});

          // Diff against current state
          sb.from('event_state').select('*').then(function (resp) {{
            if (resp.error) {{ $prev.innerHTML = '<p class="alert error">Couldn\\u2019t fetch current state: ' + escapeHtml(resp.error.message) + '</p>'; return; }}
            var current = resp.data || [];
            var diff = diffRows(current, coerced);
            var $prev2 = panel.querySelector('#csv-preview');
            $prev2.innerHTML =
              '<div class="alert">' +
                '<strong>Preview:</strong> ' +
                '<span style="color:var(--ab-green);">' + diff.added.length + ' new</span> · ' +
                '<span style="color:var(--ab-blue);">' + diff.updated.length + ' updated</span> · ' +
                '<span style="color:var(--ab-fg-3);">' + diff.unchanged.length + ' unchanged</span>' +
              '</div>' +
              '<div class="add-actions" style="margin-top:8px;">' +
                '<button type="button" class="primary" id="csv-apply-btn">Apply ' + (diff.added.length + diff.updated.length) + ' change' + ((diff.added.length + diff.updated.length) === 1 ? '' : 's') + '</button>' +
                '<button type="button" class="secondary" id="csv-discard-btn">Discard</button>' +
              '</div>';
            $prev2.querySelector('#csv-discard-btn').addEventListener('click', function () {{ $prev2.innerHTML = ''; ev.target.value = ''; }});
            $prev2.querySelector('#csv-apply-btn').addEventListener('click', function () {{
              var btn = $prev2.querySelector('#csv-apply-btn');
              btn.disabled = true; btn.textContent = 'Applying…';
              // Tag updated_by on all changes
              var toUpsert = diff.added.concat(diff.updated).map(function (r) {{
                var row = {{}};
                CSV_COLUMNS.forEach(function (c) {{
                  if (r[c] === undefined) return; // optional column absent — preserve DB value
                  row[c] = r[c];
                }});
                row.updated_by = email;
                return row;
              }});
              if (toUpsert.length === 0) {{ btn.disabled = false; btn.textContent = 'Nothing to apply'; return; }}
              // NOTE: bulk upsert can't strip-and-retry per row; pre-migration
              // CSVs simply shouldn't include attend_verdict/postmortem columns.
              sb.from('event_state').upsert(toUpsert, {{ onConflict: 'event_num' }}).then(function (resp2) {{
                if (resp2.error) {{ btn.disabled = false; btn.textContent = 'Retry'; status('Apply failed: ' + resp2.error.message, 'error'); return; }}
                $prev2.innerHTML = '<p class="alert"><strong>Applied:</strong> ' + diff.added.length + ' new + ' + diff.updated.length + ' updated. Refreshing grid…</p>';
                flashOk('CSV applied');
                setTimeout(function () {{ panel.remove(); renderOps(email); }}, 600);
              }});
            }});
          }});
        }};
        reader.readAsText(file);
      }});
    }}

    // ── Search events via Dust ───────────────────────────────────────
    // Asks the ArcticBlueEventSpeaking agent for N upcoming events
    // matching criteria (count + types + quarters + regions), renders
    // them as a result list, and lets the user add individual rows
    // (or all at once) into manual_events. Replaces the older
    // single-candidate Vet workflow.

    function _currentQuarterOptions() {{
      // Build 8 quarters starting from the current one.
      var now = new Date();
      var qstart = Math.floor(now.getMonth() / 3);   // 0..3
      var year   = now.getFullYear();
      var out = [];
      for (var i = 0; i < 8; i++) {{
        var qi = (qstart + i) % 4;
        var yi = year + Math.floor((qstart + i) / 4);
        out.push('Q' + (qi + 1) + ' ' + yi);
      }}
      return out;
    }}

    var SEARCH_TYPE_OPTIONS    = ['Enterprise', 'Halo', 'Research', 'Industry', 'Sponsor', 'Conference', 'Summit', 'Workshop'];
    var SEARCH_REGION_OPTIONS  = ['US & Canada', 'Latin America', 'Europe', 'Africa', 'MENA', 'Asia-Pacific', 'Global'];

    function _multichip(host, options, defaults) {{
      // Build a chip group inside `host`. Returns getter for selected values.
      options.forEach(function (opt) {{
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'extra-chip';
        btn.dataset.value = opt;
        btn.textContent = opt;
        if (defaults && defaults.indexOf(opt) !== -1) btn.classList.add('is-on');
        btn.addEventListener('click', function () {{ btn.classList.toggle('is-on'); }});
        host.appendChild(btn);
      }});
      return function () {{
        return Array.prototype.map.call(
          host.querySelectorAll('.extra-chip.is-on'),
          function (b) {{ return b.dataset.value; }}
        );
      }};
    }}

    function openSearchPanel(email, seed) {{
      seed = seed || {{}};
      var existing = document.getElementById('search-panel');
      if (existing) {{
        // Plain re-click = toggle closed. A SEEDED open (e.g. from a Plan-Ahead
        // "Find events near <city>" button) always reopens with the new seed.
        existing.remove();
        if (!seed.location && !seed.quarter && !seed.dateFrom) return;
      }}

      var qOpts = _currentQuarterOptions();
      // Seeded with a trip's quarter (if it's within our 8-quarter window) →
      // narrow to just that quarter; otherwise default to the next two.
      var qDefaults = (seed.quarter && qOpts.indexOf(seed.quarter) !== -1)
        ? [seed.quarter] : qOpts.slice(0, 2);

      var panel = document.createElement('div');
      panel.id = 'search-panel';
      panel.className = 'add-event-card';
      panel.innerHTML =
        '<h3>Find events (AI search)</h3>' +
        '<p style="margin:0 0 12px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          (seed.location
            ? 'Searching for events in or near <strong>' + escapeHtml(seed.location) + '</strong>' +
              ((seed.dateFrom && seed.dateTo) ? ' around <strong>' + escapeHtml(seed.dateFrom) + ' \\u2013 ' + escapeHtml(seed.dateTo) + '</strong>' : '') +
              (seed.exclude ? ' (to stack onto ' + escapeHtml(seed.exclude) + ', which is excluded)' : '') +
              ' \\u2014 so you can cover more in one trip. Adjust the fields below and run it.'
            : 'AI web search finds upcoming in-person events matching your criteria — buyer-rich audiences preferred. It first looks for next-year editions of events the team has attended, then fills in with your criteria. Added events are vetted and auto-enriched.') +
        '</p>' +
        '<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">' +
          '<label style="display:inline-flex;align-items:center;gap:8px;font-family:var(--ab-mono);font-size:0.7rem;letter-spacing:0.06em;text-transform:uppercase;color:var(--ab-fg-3);">' +
            'How many:' +
            '<input type="number" id="search-count" min="1" max="25" value="10" style="width:60px;padding:6px 8px;border:1px solid var(--ab-rule-strong);border-radius:6px;font-family:var(--ab-sans);font-size:0.9rem;">' +
          '</label>' +
          '<label style="display:inline-flex;align-items:center;gap:8px;flex:1;min-width:200px;font-family:var(--ab-mono);font-size:0.7rem;letter-spacing:0.06em;text-transform:uppercase;color:var(--ab-fg-3);">' +
            'Near:' +
            '<input type="text" id="search-near" placeholder="City or country \\u2014 optional" style="flex:1;min-width:120px;padding:6px 8px;border:1px solid var(--ab-rule-strong);border-radius:6px;font-family:var(--ab-sans);font-size:0.9rem;text-transform:none;letter-spacing:normal;">' +
          '</label>' +
        '</div>' +
        '<div class="extra-filters" style="margin-bottom:10px;">' +
          '<div class="extra-filter-group" id="search-quarters">' +
            '<span class="extra-filter-label">Quarters</span>' +
          '</div>' +
          '<div class="extra-filter-group" id="search-regions">' +
            '<span class="extra-filter-label">Regions</span>' +
          '</div>' +
        '</div>' +
        '<div class="add-actions" style="margin-top:10px;">' +
          '<button type="button" class="primary" id="search-run-btn">Find events</button>' +
          '<button type="button" class="secondary" id="search-cancel-btn">Close</button>' +
        '</div>' +
        '<p class="ops-meta" id="search-meta" style="margin-top:10px;">AI search usually takes 10\\u201320 seconds.</p>' +
        '<div id="search-results" style="margin-top:12px;"></div>';

      $opsGrid.insertBefore(panel, $opsGrid.firstChild);
      _mountPanelClose(panel);
      if (seed.location) panel.querySelector('#search-near').value = seed.location;

      var getQuarters = _multichip(panel.querySelector('#search-quarters'), qOpts,                  qDefaults);
      var getRegions  = _multichip(panel.querySelector('#search-regions'),  SEARCH_REGION_OPTIONS,  []);

      panel.querySelector('#search-cancel-btn').addEventListener('click', function () {{ panel.remove(); }});

      panel.querySelector('#search-run-btn').addEventListener('click', function () {{
        var count = parseInt(panel.querySelector('#search-count').value, 10);
        if (!Number.isFinite(count) || count < 1) count = 10;
        if (count > 25) count = 25;
        // Types are no longer a manual pick — send the full vocabulary the
        // prompt already knows about (Enterprise, Halo, Research, …) so the AI
        // finds the whole range automatically.
        // Bake in "return next year": collect the events the team ATTENDED or
        // SPOKE at in the past, so the agent hunts for their next-year editions
        // first and only then falls back to the criteria below.
        var _recurring = [];
        try {{
          Array.prototype.forEach.call($opsGrid.querySelectorAll('.ops-card[data-past="1"]'), function (c) {{
            var atts = (c.dataset.attendeeNames || '').split('|').filter(Boolean);
            var stg  = (c.dataset.statusTags || '').split('|');
            var bookedSpk = stg.indexOf('Booked') !== -1 && (c.dataset.speaker || '');
            var nm = c._modalRec && c._modalRec.name;
            if (nm && (atts.length || bookedSpk) && _recurring.indexOf(nm) === -1) _recurring.push(nm);
          }});
        }} catch (e) {{}}
        var _near = (panel.querySelector('#search-near').value || '').trim();
        // Seeded from a trip: search its EXACT date window (overrides quarter) and
        // exclude the trip event itself.
        var criteria = {{ count: count, types: SEARCH_TYPE_OPTIONS.slice(), quarters: getQuarters(), regions: getRegions(), recurring: _recurring.slice(0, 30), location: _near,
          date_from: seed.dateFrom || '', date_to: seed.dateTo || '', exclude: seed.exclude || '' }};
        var runBtn = panel.querySelector('#search-run-btn');
        var meta   = panel.querySelector('#search-meta');
        runBtn.disabled = true; runBtn.textContent = 'Searching\\u2026';
        meta.textContent = 'Asking ArcticBlueEventSpeaking for ' + count + ' events. This can take 10\\u201360 seconds.';

        sb.auth.getSession().then(function (r) {{
          var token = r && r.data && r.data.session && r.data.session.access_token;
          var _sh = {{ 'Content-Type': 'application/json' }};
          if (token) _sh['Authorization'] = 'Bearer ' + token;
          var t0 = Date.now();
          fetch('/api/search', {{
            method:  'POST',
            headers: _sh,
            body:    JSON.stringify(criteria)
          }}).then(function (res) {{
            return res.json().then(function (j) {{ return [res.status, j]; }});
          }}).then(function (pair) {{
            var st = pair[0], data = pair[1];
            var dur = Math.round((Date.now() - t0) / 1000);
            runBtn.disabled = false; runBtn.textContent = 'Find more';
            if (st !== 200) {{
              meta.textContent = 'Find failed (' + st + '): ' + (data && data.error || 'unknown error');
              return;
            }}
            var _filts = [];
            if (data.dupes_filtered) _filts.push(data.dupes_filtered + ' already-tracked');
            if (data.off_target_filtered) _filts.push(data.off_target_filtered + ' off-target');
            meta.textContent = 'Found ' + (data.events || []).length + ' new events in ' + dur + 's' +
              (_filts.length ? ' (' + _filts.join(' + ') + ' filtered out)' : '') + '.';
            // Seeded solo-trip search that found nothing to add → remember this
            // anchor is a dead end, so Plan Ahead stops offering the button.
            if (seed.anchorKey && (data.events || []).length === 0) _planAreaEmptyMark(seed.anchorKind, seed.anchorKey);
            renderSearchResults(panel, data, email);
          }}).catch(function (err) {{
            runBtn.disabled = false; runBtn.textContent = 'Find more';
            meta.textContent = 'Network error: ' + err.message;
          }});
        }});
      }});
    }}

    // Insert one AI-found event into manual_events. Shared by the search panel's
    // "Add to events" and Plan Ahead's inline proactive results.
    function _insertFoundEvent(ev, email) {{
      if (!ev || !ev.name) return Promise.resolve({{ ok: false, reason: 'missing name' }});
      if (isDuplicateName(ev.name, null, ev)) return Promise.resolve({{ ok: false, reason: 'duplicate' }});
      var dates = ev.date_str ? deriveDatesFromText(ev.date_str) : {{}};
      var row = {{
        name:       ev.name.trim(),
        date_str:   ev.date_str || 'Date TBD',
        start_date: dates.start_date || null,
        end_date:   dates.end_date   || null,
        location:   ev.location || null,
        region:     ev.region   || null,
        type:       ev.type     || null,
        priority:   ev.priority || null,
        why:        ev.why      || null,
        url:        ev.url      || null,
        // Attending signals, when the search results carry them. The agent
        // says "audience"; the column is audience_type.
        pricing:         ev.pricing || null,
        audience_type:   ev.audience_type || ev.audience || null,
        past_speakers:   ev.past_speakers || ev.speakers || null,
        meeting_formats: ev.meeting_formats || ev.guaranteed_meetings || null,
        created_by: email
      }};
      return sbWriteRetry(row, function (p) {{ return sb.from('manual_events').insert(p).select(); }}).then(function (resp) {{
        if (resp.error) {{
          if (resp.error.code === '23505') return {{ ok: false, reason: 'duplicate' }};
          return {{ ok: false, reason: resp.error.message }};
        }}
        return {{ ok: true, row: resp.data && resp.data[0] }};
      }});
    }}

    function renderSearchResults(panel, data, email) {{
      var events = (data.events || []);
      var $r = panel.querySelector('#search-results');
      if (events.length === 0) {{
        $r.innerHTML = '<p class="alert">No relevant events</p>';
        return;
      }}

      function recPillHtml(rec) {{
        var r = (rec || '').toLowerCase();
        if (r === 'yes')   return '<span class="ops-tag" style="background:#dcfce7;color:#166534;">Recommend</span>';
        if (r === 'maybe') return '<span class="ops-tag" style="background:#fef3c7;color:#92400e;">Maybe</span>';
        if (r === 'no')    return '<span class="ops-tag" style="background:#fee2e2;color:#991b1b;">Skip</span>';
        return '';
      }}

      var cards = events.map(function (ev, idx) {{
        var url = ev.url ? ' <a href="' + escapeHtml(ev.url) + '" target="_blank" rel="noopener" style="color:var(--ab-blue);text-decoration:none;font-weight:600;">↗</a>' : '';
        var dup = isDuplicateName(ev.name, null, ev) ? '<span class="ops-tag" style="background:#fef2f2;color:#7f1d1d;border:1px solid #fecaca;">Already in tracker</span>' : '';
        return (
          '<div class="search-result" data-idx="' + idx + '" style="border:1px solid var(--ab-rule);border-radius:8px;padding:14px;margin-bottom:10px;background:var(--ab-bg);">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:6px;flex-wrap:wrap;">' +
              '<div style="flex:1;min-width:0;">' +
                '<h4 style="margin:0;font-size:1.02rem;font-weight:700;letter-spacing:-0.01em;color:var(--ab-fg);">' + escapeHtml(ev.name || '(unnamed)') + url + '</h4>' +
                '<p style="margin:4px 0 0;font-size:0.85rem;color:var(--ab-fg-2);">' +
                  escapeHtml(ev.date_str || '') + ' · ' + escapeHtml(ev.region || '') + (ev.location ? ' · ' + escapeHtml(ev.location) : '') +
                  (ev.type && ev.type.toLowerCase() !== 'halo' ? ' · ' + escapeHtml(ev.type) : '') +
                  (ev.priority ? ' · ' + escapeHtml(ev.priority) : '') +
                '</p>' +
              '</div>' +
              '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">' +
                recPillHtml(ev.recommend) + ' ' + dup +
              '</div>' +
            '</div>' +
            (ev.why || ev.reasoning ?
              '<p style="font-size:0.85rem;color:var(--ab-fg-2);margin:4px 0 8px;">' +
                (ev.why ? escapeHtml(ev.why) : '') +
                (ev.why && ev.reasoning ? ' — ' : '') +
                (ev.reasoning ? '<em>' + escapeHtml(ev.reasoning) + '</em>' : '') +
              '</p>' : '') +
            '<div class="add-actions" style="margin-top:6px;">' +
              '<button type="button" class="primary search-add" data-idx="' + idx + '" ' + (dup ? 'disabled' : '') + '>Add to events</button>' +
            '</div>' +
          '</div>'
        );
      }}).join('');

      $r.innerHTML =
        '<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap;">' +
          '<button type="button" class="primary" id="search-add-all">Add all to events</button>' +
          '<button type="button" class="secondary" id="search-raw-btn">Show raw reply</button>' +
        '</div>' +
        '<pre id="search-raw" style="display:none;margin:0 0 10px;padding:12px;background:var(--ab-bg-3);border-radius:6px;font-size:0.78rem;color:var(--ab-fg-2);max-height:280px;overflow:auto;white-space:pre-wrap;"></pre>' +
        cards;

      // Persist data for delegated handlers
      var _eventsByIdx = events;

      $r.querySelector('#search-raw-btn').addEventListener('click', function () {{
        var pre = $r.querySelector('#search-raw');
        if (pre.style.display === 'none') {{
          pre.textContent = data.raw || '(no raw reply)';
          pre.style.display = 'block';
        }} else {{
          pre.style.display = 'none';
        }}
      }});

      function insertOne(ev) {{ return _insertFoundEvent(ev, email); }}

      $r.querySelectorAll('.search-add').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          var idx = parseInt(btn.dataset.idx, 10);
          var ev = _eventsByIdx[idx];
          btn.disabled = true; btn.textContent = 'Adding\\u2026';
          insertOne(ev).then(function (r) {{
            if (r.ok) {{
              btn.textContent = 'Added ✓';
              btn.classList.remove('primary'); btn.classList.add('secondary');
              loadKnownNames();
              renderOps(email);
              flashOk('Added "' + (ev.name || '') + '"');
            }} else {{
              btn.disabled = false;
              btn.textContent = 'Add to events';
              status('Add failed: ' + r.reason, 'error');
            }}
          }});
        }});
      }});

      $r.querySelector('#search-add-all').addEventListener('click', function () {{
        var addAll = $r.querySelector('#search-add-all');
        addAll.disabled = true; addAll.textContent = 'Adding\\u2026';
        var added = 0, skipped = 0, errors = 0;
        // Insert serially so dedup cache stays in sync between rows
        var chain = Promise.resolve();
        events.forEach(function (ev) {{
          chain = chain.then(function () {{ return insertOne(ev); }}).then(function (r) {{
            if (r.ok) {{ added++; loadKnownNames(); }}
            else if (r.reason === 'duplicate') {{ skipped++; }}
            else {{ errors++; }}
          }});
        }});
        chain.then(function () {{
          addAll.disabled = false;
          addAll.textContent = 'Add all to events';
          var msg = 'Added ' + added + ' · skipped ' + skipped + ' duplicate' + (skipped === 1 ? '' : 's');
          if (errors) msg += ' · ' + errors + ' error' + (errors === 1 ? '' : 's');
          flashOk(msg);
          renderOps(email);
        }});
      }});
    }}


    // ── Ask AI — chat over the tracked events (OpenAI via /api/ask) ──
    var _askHistory = [];
    function _mdToHtml(s) {{
      // Tiny, safe markdown → HTML: escape first, then bold + links + bullets.
      var h = escapeHtml(s);
      h = h.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
      h = h.replace(/(https?:\\/\\/[^\\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
      h = h.replace(/^\\s*[-*]\\s+(.*)$/gm, '• $1');
      return h;
    }}
    // Render the AI\\u2019s ranked event recommendations as clickable mini cards.
    // ranked: show "#1, #2…". A conversational reply about ONE event puts its
    // card below the prose purely as a reference — ranking a list of one is
    // meaningless, and "#1" read as a stray character (Hurley 2026-07-29).
    function _askCardsHtml(cards, ranked) {{
      if (!cards || !cards.length) return '';
      var showRank = ranked !== false && cards.length > 1;
      return '<div class="ask-cards">' + cards.map(function (c, i) {{
        var meta = [c.date, c.location || c.region].filter(Boolean).map(escapeHtml).join(' \\u00b7 ');
        var tags = [];
        var _acPri = window.cardPriority ? window.cardPriority({{ priority: c.priority, audience_type: c.audience }}) : '';
        if (_acPri) tags.push('<span class="ac-tag pri-' + _acPri.toLowerCase() + '">' + escapeHtml(_acPri) + '</span>');
        if (c.stage) tags.push('<span class="ac-tag">' + escapeHtml(String(c.stage).split(',')[0].trim()) + '</span>');
        if (c.price) tags.push('<span class="ac-tag">' + escapeHtml(c.price) + '</span>');
        // Carry every identifier we have: catalog num, manual id, AND the name.
        // The name alone is not reliable — the card face trims a trailing year,
        // so the AI's "IDC CIO Summit Spain 2026" never equalled the card's
        // "IDC CIO Summit Spain" and the click did nothing.
        var idAttr = '';
        if (c.num !== null && c.num !== undefined) idAttr += ' data-evnum="' + escapeHtml(String(c.num)) + '"';
        if (c.mid !== null && c.mid !== undefined) idAttr += ' data-evmid="' + escapeHtml(String(c.mid)) + '"';
        idAttr += ' data-evname="' + escapeHtml(c.name || '') + '"';
        return '<button type="button" class="ask-card"' + idAttr + '>' +
          (showRank ? '<span class="rank">#' + (i + 1) + '</span>' : '') +
          '<span class="ac-name">' + escapeHtml(c.name || 'Untitled event') + '</span>' +
          (meta ? '<span class="ac-meta">' + meta + '</span>' : '') +
          (tags.length ? '<span class="ac-tags">' + tags.join('') + '</span>' : '') +
        '</button>';
      }}).join('') + '</div>';
    }}
    // Render an AI reply: lead with the ranked event cards, then a short,
    // de-emphasised note for the reasoning (no big markdown blocks). When there
    // are no matching events (a factual question), fall back to the text.
    window.abMdToHtml = _mdToHtml;
    function _askAnswerHtml(answer, cards, mode) {{
      var txt = (answer || '').trim();
      var hasCards = cards && cards.length;
      // A LIST / ranking ("events" mode, or legacy replies with no mode) leads
      // with the ranked cards and demotes the prose to a small note. A
      // CONVERSATIONAL reply (a specific event, a how-to, or general chat) leads
      // with the prose like a normal chatbot, and any single event card sits
      // below it as a reference.
      if ((mode === 'events' || !mode) && hasCards) {{
        return _askCardsHtml(cards, true) +
          (txt ? '<div class="ask-note">' + _mdToHtml(txt) + '</div>' : '');
      }}
      var out = txt ? '<div class="ask-prose">' + _mdToHtml(txt) + '</div>' : '';
      // Conversational reply — the card is a reference, not a ranking.
      if (hasCards) out += _askCardsHtml(cards, false);
      return out || _mdToHtml(txt);
    }}
    // Click a recommended card \\u2192 open that event\\u2019s detail modal.
    //
    // Resolve against the RENDERED cards first, always. Their _modalRec is the
    // merged record (event_state overrides + _table/_key edit context); the raw
    // CATALOG entry that window.openEventByNum used has none of that, so Details
    // opened with an empty Edit form — and when the num wasn't in the client
    // CATALOG at all (manual events carry no num; a catalog event can be stale)
    // it silently opened nothing, which is the "can't click the details" Angela
    // hit. Falls back to CATALOG with edit context grafted on so a card can
    // still open even if its grid row isn't there.
    // Fold a title down to something comparable across the AI's copy and the
    // card's: lowercase, strip accents (Zürich/Zurich), drop a trailing edition
    // year and any "20xx" token, drop punctuation, collapse whitespace.
    function _askNameKey(s) {{
      var t = String(s || '');
      if (t.normalize) t = t.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
      return t.toLowerCase()
              .replace(/\\b20\\d\\d\\b/g, ' ')
              .replace(/[^a-z0-9]+/g, ' ')
              .trim();
    }}
    function _askResolveRec(num, mid, name) {{
      var cards = $opsGrid ? Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-card')) : [];
      var rec = null;
      var pick = function (table, key) {{
        var k = String(key);
        return (cards.filter(function (c) {{
          return c._modalRec && c._modalRec._table === table && String(c._modalRec._key) === k;
        }})[0] || {{}})._modalRec || null;
      }};
      // 1) By key — exact and unambiguous.
      if (num !== null && num !== undefined && String(num) !== '') rec = pick('event_state', num);
      if (!rec && mid !== null && mid !== undefined && String(mid) !== '') rec = pick('manual_events', mid);
      // 2) Exact name.
      if (!rec && name) {{
        var nm = String(name).trim().toLowerCase();
        rec = (cards.filter(function (c) {{
          return c._modalRec && (c._modalRec.name || '').trim().toLowerCase() === nm;
        }})[0] || {{}})._modalRec || null;
      }}
      // 3) Normalised name — survives the trimmed year, accents and punctuation.
      if (!rec && name) {{
        var key = _askNameKey(name);
        if (key) {{
          var hits = cards.filter(function (c) {{
            return c._modalRec && _askNameKey(c._modalRec.name) === key;
          }});
          // Only accept a fuzzy hit when it's unambiguous.
          if (hits.length === 1) rec = hits[0]._modalRec;
        }}
      }}
      if (!rec && num !== null && num !== undefined && String(num) !== '') {{
        var raw = (window.AB_CATALOG || {{}})[String(num)];
        if (raw) {{
          // Clone + attach the editing context the modal needs, so Edit works.
          rec = {{}};
          for (var kk in raw) {{ if (Object.prototype.hasOwnProperty.call(raw, kk)) rec[kk] = raw[kk]; }}
          rec._table = 'event_state'; rec._key = raw.num;
        }}
      }}
      return rec;
    }}
    function _wireAskCards(container) {{
      container.querySelectorAll('.ask-card').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          var rec = _askResolveRec(btn.getAttribute('data-evnum'), btn.getAttribute('data-evmid'), btn.getAttribute('data-evname'));
          if (rec && typeof window.openEventModal === 'function') {{ window.openEventModal(rec); return; }}
          // Nothing matched — say so instead of looking dead on click.
          if (typeof status === 'function') status('Could not open that event \\u2014 it may have been deleted or renamed.', 'error');
        }});
      }});
    }}
    function openAskPanel() {{
      var existing = document.getElementById('ask-panel');
      if (existing) {{ existing.remove(); return; }}
      var panel = document.createElement('div');
      panel.id = 'ask-panel';
      panel.className = 'add-event-card';
      // Support (Angela/Hurley) can aim the results at the whole team or specific
      // teammates; everyone else just gets their own, tailored to them.
      var _askSupport = isSupportPerson(getCollabName() || '');
      panel.innerHTML =
        '<h3>Ask AI about current results</h3>' +
        '<p style="margin:0 0 12px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          'Ranks your tracked events by how well they fit and answers from their own data \\u2014 statuses, dates, region and verdicts. Tap a card to open it.</p>' +
        '<div class="ask-log" id="ask-log"></div>' +
        (_askSupport
          ? '<div class="ask-forrow" id="ask-forrow"><span class="ask-for-label">Find for</span>' +
              '<button type="button" class="ask-for-chip is-on" data-for="all">Everyone</button>' +
              ['Thor', 'Verma', 'Jerome', 'Joe', 'Scott', 'Carlos', 'Jim'].map(function (n) {{ return '<button type="button" class="ask-for-chip" data-for="' + escapeHtml(n) + '">' + escapeHtml(n) + '</button>'; }}).join('') +
            '</div>'
          : '') +
        '<div class="ask-examples" id="ask-examples">' +
          ['Which events should I attend in September?',
           'What\\u2019s booked for Thor?',
           'Which enterprise events fit us in Q4?',
           'Which CFP deadlines are closing soon?'].map(function (q) {{
            return '<button type="button" class="ask-chip">' + escapeHtml(q) + '</button>';
          }}).join('') +
        '</div>' +
        '<div class="ask-inputrow">' +
          '<input type="text" id="ask-input" placeholder="Ask anything about these events\\u2026" autocomplete="off">' +
          '<button type="button" class="primary" id="ask-send">Ask</button>' +
        '</div>' +
        '<div class="add-actions" style="margin-top:12px;">' +
          '<button type="button" class="secondary" id="ask-close">Close</button>' +
        '</div>';
      $opsGrid.insertBefore(panel, $opsGrid.firstChild);
      _mountPanelClose(panel);

      var log = panel.querySelector('#ask-log');
      var input = panel.querySelector('#ask-input');
      var sendBtn = panel.querySelector('#ask-send');

      // "Find for" chips (support only): Everyone is exclusive; picking a name
      // clears Everyone; clearing all reverts to Everyone.
      var forRow = panel.querySelector('#ask-forrow');
      if (forRow) {{
        forRow.addEventListener('click', function (e) {{
          var c = e.target.closest ? e.target.closest('.ask-for-chip') : null;
          if (!c) return;
          var allChip = forRow.querySelector('.ask-for-chip[data-for="all"]');
          if (c.dataset.for === 'all') {{
            Array.prototype.forEach.call(forRow.querySelectorAll('.ask-for-chip'), function (x) {{ x.classList.toggle('is-on', x === c); }});
          }} else {{
            if (allChip) allChip.classList.remove('is-on');
            c.classList.toggle('is-on');
            if (!forRow.querySelector('.ask-for-chip.is-on') && allChip) allChip.classList.add('is-on');
          }}
        }});
      }}
      function getForPeople() {{
        if (!forRow) return [];
        var out = [];
        Array.prototype.forEach.call(forRow.querySelectorAll('.ask-for-chip.is-on'), function (c) {{ if (c.dataset.for !== 'all') out.push(c.dataset.for); }});
        return out;   // empty = Everyone / whole team
      }}

      function addMsg(role, text, isHtml) {{
        var m = document.createElement('div');
        m.className = 'ask-msg ' + (role === 'user' ? 'user' : 'ai');
        if (isHtml) m.innerHTML = text; else m.textContent = text;
        log.appendChild(m);
        log.scrollTop = log.scrollHeight;
        return m;
      }}
      // Replay prior history when re-opening (including recommended cards).
      _askHistory.forEach(function (h) {{
        if (h.role === 'assistant') {{
          var m = addMsg('ai', _askAnswerHtml(h.content, h.cards, h.mode), true);
          _wireAskCards(m);
        }} else {{
          addMsg(h.role, h.content);
        }}
      }});

      function ask(q) {{
        q = (q || '').trim();
        if (!q) return;
        addMsg('user', q);
        _askHistory.push({{ role: 'user', content: q }});
        input.value = '';
        sendBtn.disabled = true; sendBtn.textContent = 'Thinking\\u2026';
        var thinking = addMsg('ai', 'Thinking\\u2026');
        fetch('/api/ask', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ question: q, history: _askHistory.slice(0, -1), user: (typeof getCollabName === 'function' ? (getCollabName() || '') : ''), for_people: getForPeople() }})
        }}).then(function (r) {{ return r.json().then(function (j) {{ return [r.status, j]; }}); }})
          .then(function (pair) {{
            sendBtn.disabled = false; sendBtn.textContent = 'Ask';
            var st = pair[0], data = pair[1];
            if (st !== 200 || !data.answer) {{
              thinking.textContent = 'Sorry \\u2014 ' + ((data && data.error) || 'the assistant is unavailable right now.');
              return;
            }}
            thinking.innerHTML = _askAnswerHtml(data.answer, data.cards, data.mode);
            _wireAskCards(thinking);
            log.scrollTop = log.scrollHeight;
            _askHistory.push({{ role: 'assistant', content: data.answer, cards: data.cards || [], mode: data.mode }});
          }}).catch(function () {{
            sendBtn.disabled = false; sendBtn.textContent = 'Ask';
            thinking.textContent = 'Network error \\u2014 please try again.';
          }});
      }}

      sendBtn.addEventListener('click', function () {{ ask(input.value); }});
      input.addEventListener('keydown', function (e) {{ if (e.key === 'Enter') ask(input.value); }});
      panel.querySelectorAll('.ask-chip').forEach(function (c) {{
        c.addEventListener('click', function () {{ ask(c.textContent); }});
      }});
      panel.querySelector('#ask-close').addEventListener('click', function () {{ panel.remove(); }});
      setTimeout(function () {{ input.focus(); }}, 50);
    }}


    // ── + Add event / Paste email orchestration ─────────────────────
    // Opens an inline panel that surfaces the public feed URL + a 1-click
    // copy button + paste-instructions for the three common calendar apps.
    function openSubscribePanel() {{
      var existing = document.getElementById('subscribe-panel');
      if (existing) {{ existing.remove(); return; }}
      var feedUrl = window.location.origin + '/calendar.ics';
      var panel = document.createElement('div');
      panel.id = 'subscribe-panel';
      panel.className = 'add-event-card';
      panel.innerHTML =
        '<h3>Calendar sync</h3>' +
        '<p style="margin:0 0 14px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          'One live feed of every saved ★ and manual event. Subscribe once — ' +
          'your calendar updates itself from then on.' +
        '</p>' +
        // HERO: one-click Google Calendar subscribe — the team\'s shared
        // calendar lives in Google, so this is the 95% path.
        '<a href="https://calendar.google.com/calendar/render?cid=' +
          encodeURIComponent('webcal://' + window.location.host + '/calendar.ics') +
          '" target="_blank" rel="noopener" class="primary" id="subscribe-gcal-btn" ' +
          'style="display:block;text-align:center;margin-bottom:14px;font-family:var(--ab-sans);font-weight:600;font-size:1rem;padding:13px 18px;border-radius:8px;background:#1a73e8;color:#fff;text-decoration:none;">' +
          'Add to Google Calendar — one click</a>' +
        '<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;">' +
          '<input type="text" id="subscribe-url" readonly value="' + escapeHtml(feedUrl) + '" ' +
            'style="flex:1;font-family:var(--ab-mono);font-size:0.85rem;padding:10px 12px;border:1px solid var(--ab-rule-strong);border-radius:6px;background:var(--ab-bg-2);color:var(--ab-fg);">' +
          '<button type="button" class="primary" id="subscribe-copy-btn" style="white-space:nowrap;font-family:var(--ab-sans);font-weight:600;font-size:0.9rem;padding:10px 16px;border-radius:6px;border:0;background:var(--ab-fg);color:var(--ab-bg);cursor:pointer;">Copy link</button>' +
        '</div>' +
        '<details style="border-top:1px solid var(--ab-rule);padding-top:12px;">' +
          '<summary style="cursor:pointer;font-family:var(--ab-mono);font-size:0.72rem;color:var(--ab-fg-3);letter-spacing:0.08em;text-transform:uppercase;">Other calendar apps (Apple · Outlook)</summary>' +
          '<div style="display:grid;gap:10px;margin-top:10px;font-size:0.9rem;color:var(--ab-fg-2);line-height:1.55;">' +
            '<div><strong>Apple Calendar (Mac):</strong> File → New Calendar Subscription → paste the link above → Subscribe → choose auto-refresh.</div>' +
            '<div><strong>Apple Calendar (iPhone/iPad):</strong> Settings → Calendar → Accounts → Add Account → Other → Add Subscribed Calendar → paste.</div>' +
            '<div><strong>Outlook (web):</strong> Calendar → Add calendar → Subscribe from web → paste.</div>' +
          '</div>' +
        '</details>' +
        '<div class="add-actions" style="margin-top:14px;align-items:center;">' +
          '<button type="button" class="secondary" id="subscribe-close-btn">Close</button>' +
          '<a id="subscribe-download-btn" style="cursor:pointer;font-size:0.85rem;color:var(--ab-fg-3);text-decoration:underline;margin-left:auto;" title="A one-time snapshot file — does NOT stay in sync; prefer the live feed above">Download one-time .ics file instead</a>' +
        '</div>' +
        '<p class="ops-meta" style="margin-top:10px;">Tip: the feed is empty until at least one event is starred ★ saved, or you add a manual event.</p>';

      $opsGrid.insertBefore(panel, $opsGrid.firstChild);
      _mountPanelClose(panel);

      panel.querySelector('#subscribe-close-btn').addEventListener('click', function () {{ panel.remove(); }});
      panel.querySelector('#subscribe-download-btn').addEventListener('click', function () {{ exportSavedAsIcs(); }});

      var copyBtn = panel.querySelector('#subscribe-copy-btn');
      copyBtn.addEventListener('click', function () {{
        var input = panel.querySelector('#subscribe-url');
        function done() {{
          var original = copyBtn.textContent;
          copyBtn.textContent = '✓ Copied';
          copyBtn.disabled = true;
          setTimeout(function () {{ copyBtn.textContent = original; copyBtn.disabled = false; }}, 1600);
        }}
        // Prefer the async Clipboard API (HTTPS required); fall back to select-and-execCommand
        if (navigator.clipboard && window.isSecureContext) {{
          navigator.clipboard.writeText(feedUrl).then(done, function () {{
            input.select(); input.setSelectionRange(0, 9999);
            try {{ document.execCommand('copy'); done(); }} catch (e) {{ alert('Couldn\\u2019t copy. Select the URL manually and Cmd+C.'); }}
          }});
        }} else {{
          input.select(); input.setSelectionRange(0, 9999);
          try {{ document.execCommand('copy'); done(); }} catch (e) {{ alert('Couldn\\u2019t copy. Select the URL manually and Cmd+C.'); }}
        }}
      }});
    }}

    function wireAddEvent(email) {{
      var $addBtn    = document.getElementById('add-event-btn');
      var $pasteBtn  = document.getElementById('paste-email-btn');
      var $searchBtn = document.getElementById('search-dust-btn');
      var $csvBtn    = document.getElementById('csv-btn');
      var $icalBtn   = document.getElementById('ical-btn');
      var $subBtn    = document.getElementById('ical-subscribe-btn');
      var $askBtn    = document.getElementById('ask-ai-btn');
      if (!$addBtn) return;
      // Clone-replace to clear listeners from any prior route() call
      var freshAdd = $addBtn.cloneNode(true); $addBtn.parentNode.replaceChild(freshAdd, $addBtn); $addBtn = freshAdd;
      if ($pasteBtn)  {{ var fp = $pasteBtn.cloneNode(true);  $pasteBtn.parentNode.replaceChild(fp, $pasteBtn);   $pasteBtn  = fp; }}
      if ($searchBtn) {{ var fs2 = $searchBtn.cloneNode(true); $searchBtn.parentNode.replaceChild(fs2, $searchBtn); $searchBtn = fs2; }}
      if ($csvBtn)    {{ var fc = $csvBtn.cloneNode(true);    $csvBtn.parentNode.replaceChild(fc, $csvBtn);       $csvBtn    = fc; }}
      if ($icalBtn)   {{ var fi = $icalBtn.cloneNode(true);   $icalBtn.parentNode.replaceChild(fi, $icalBtn);     $icalBtn   = fi; }}
      if ($askBtn)    {{ var fk = $askBtn.cloneNode(true);    $askBtn.parentNode.replaceChild(fk, $askBtn);       $askBtn    = fk; }}
      if ($subBtn)    {{ var fs = $subBtn.cloneNode(true);    $subBtn.parentNode.replaceChild(fs, $subBtn);       $subBtn    = fs; }}

      // "+ Add" dropdown: toggle the menu holding the three add paths. The menu
      // button + container are NOT cloned above, so wire once (guard flag) — the
      // item buttons inside keep their own handlers (attached below). Clicking
      // any item runs its action AND closes the menu (delegated on the container).
      var $addMenuBtn = document.getElementById('add-menu-btn');
      var $addMenu    = document.getElementById('add-menu');
      if ($addMenuBtn && $addMenu && !$addMenuBtn._menuWired) {{
        $addMenuBtn._menuWired = true;
        function _closeAddMenu() {{ $addMenu.hidden = true; $addMenuBtn.setAttribute('aria-expanded', 'false'); }}
        $addMenuBtn.addEventListener('click', function (e) {{
          e.stopPropagation();
          var willOpen = $addMenu.hidden;
          $addMenu.hidden = !willOpen;
          $addMenuBtn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        }});
        $addMenu.addEventListener('click', function () {{ _closeAddMenu(); }});   // any item closes it
        document.addEventListener('click', function (e) {{
          if (!$addMenu.hidden && !$addMenu.contains(e.target) && !$addMenuBtn.contains(e.target)) _closeAddMenu();
        }});
        document.addEventListener('keydown', function (e) {{ if (e.key === 'Escape') _closeAddMenu(); }});
      }}

      function openAddForm(opts) {{
        opts = opts || {{}};
        var existing = document.getElementById('add-event-card');
        if (existing) {{
          if (opts.expandPaste) {{
            var section = document.getElementById('paste-email-section');
            if (section) section.setAttribute('open', '');
            var pa = document.getElementById('paste-email-text');
            if (pa) pa.focus();
          }}
          return existing;
        }}
        var form = buildAddEventForm();
        $opsGrid.insertBefore(form, $opsGrid.firstChild);
        _mountPanelClose(form);
        attachAddEventHandlers(form, email);
        if (opts.expandPaste) {{
          form.querySelector('#paste-email-section').setAttribute('open', '');
          setTimeout(function () {{ form.querySelector('#paste-email-text').focus(); }}, 0);
        }} else {{
          form.querySelector('input[name="name"]').focus();
        }}
        return form;
      }}

      // The panels all inject into #ops-grid which is hidden in Calendar
      // view. Auto-switch to Grid so every toolbar button is functional
      // from either view.
      function ensureGridView() {{
        if (typeof currentView !== 'undefined' && currentView !== 'grid') setView('grid');
      }}

      // ── Panel discipline ────────────────────────────────────────────
      // Every toolbar feature is a strict toggle: click opens it, click
      // again closes it. Only ONE panel at a time (opening one closes the
      // rest), the opened panel scrolls into view (it injects at the top of
      // the grid — invisible if you'd scrolled down), and the button shows a
      // pressed state while its panel is open.
      var PANELS = [
        ['add-event-card',  $addBtn],
        ['search-panel',    $searchBtn],
        ['csv-panel',       $csvBtn],
        ['subscribe-panel', $subBtn],
        ['ask-panel',       $askBtn]
      ];
      function closeOtherPanels(keepId) {{
        PANELS.forEach(function (p) {{
          if (p[0] === keepId) return;
          var el = document.getElementById(p[0]);
          if (el) el.remove();
        }});
      }}
      function revealPanel(id) {{
        setTimeout(function () {{
          var el = document.getElementById(id);
          if (el && el.scrollIntoView) el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}, 60);
      }}
      function syncToolbarState() {{
        PANELS.forEach(function (p) {{
          if (p[1]) p[1].classList.toggle('is-open', !!document.getElementById(p[0]));
        }});
        // Paste email lives inside the Add-event card — light it up too.
        if ($pasteBtn) {{
          var sec = document.getElementById('paste-email-section');
          $pasteBtn.classList.toggle('is-open', !!(sec && sec.hasAttribute('open')));
        }}
      }}
      // Panels also close via their own Close buttons / after a save — watch
      // the grid so button states stay truthful no matter how a panel left.
      try {{
        new MutationObserver(syncToolbarState)
          .observe($opsGrid, {{ childList: true, subtree: false }});
      }} catch (e) {{}}

      $addBtn.addEventListener('click', function () {{
        ensureGridView();
        var existing = document.getElementById('add-event-card');
        if (existing) {{ existing.remove(); syncToolbarState(); return; }}
        closeOtherPanels('add-event-card');
        openAddForm({{}});
        revealPanel('add-event-card');
        syncToolbarState();
      }});
      if ($pasteBtn) {{
        $pasteBtn.addEventListener('click', function () {{
          ensureGridView();
          var existing = document.getElementById('add-event-card');
          if (existing) {{ existing.remove(); syncToolbarState(); return; }}
          closeOtherPanels('add-event-card');
          openAddForm({{ expandPaste: true }});
          revealPanel('add-event-card');
          syncToolbarState();
        }});
      }}
      if ($searchBtn) {{
        $searchBtn.addEventListener('click', function () {{
          ensureGridView();
          closeOtherPanels('search-panel');
          openSearchPanel(email);   // self-toggles when already open
          revealPanel('search-panel');
          syncToolbarState();
        }});
      }}
      if ($csvBtn) {{
        $csvBtn.addEventListener('click', function () {{
          ensureGridView();
          closeOtherPanels('csv-panel');
          openCsvPanel(email);
          revealPanel('csv-panel');
          syncToolbarState();
        }});
      }}
      if ($icalBtn) {{
        $icalBtn.addEventListener('click', function () {{ exportSavedAsIcs(); }});
      }}
      if ($subBtn) {{
        $subBtn.addEventListener('click', function () {{
          ensureGridView();
          closeOtherPanels('subscribe-panel');
          openSubscribePanel();
          revealPanel('subscribe-panel');
          syncToolbarState();
        }});
      }}
      if ($askBtn) {{
        $askBtn.addEventListener('click', function () {{
          ensureGridView();
          closeOtherPanels('ask-panel');
          openAskPanel();
          revealPanel('ask-panel');
          syncToolbarState();
        }});
      }}
    }}

    // ── Collaborator identity (no login) ─────────────────────────────
    // The whole team shares this tracker without signing in. We capture a
    // display name once (localStorage) purely so edits are attributed
    // ("Last edit · Thor"). It's not security — just courtesy.
    function getCollabName() {{
      var n = '';
      try {{ n = (localStorage.getItem('ab.collab.name') || '').trim(); }} catch (e) {{}}
      return n;
    }}
    function setCollabName(n) {{
      n = (n || '').trim();
      var prev = getCollabName();
      try {{ localStorage.setItem('ab.collab.name', n); }} catch (e) {{}}
      applyFilterVisibility();   // Angela-only "Filters" panel + urgent follow the name
      // The signed-in name drives identity-specific views: the "My Event
      // Interests" stat, the myinterested filter, and interested highlighting.
      // Changing the name mid-session must recompute them (this was why
      // "My Event Interests" read 0 right after switching to Jerome).
      if (n.toLowerCase() !== (prev || '').toLowerCase() && $opsGrid && $opsGrid.querySelector('.ops-card')) {{
        if (n) setView('myevents');   // Thor's ask: setting your name opens My events
        renderOps(n || 'Team');
      }}
    }}
    function ensureCollabName() {{
      var n = getCollabName();
      if (!n) {{
        n = (window.prompt('Your name (so teammates can see who edited what):', '') || '').trim();
        setCollabName(n);
      }}
      return n || 'Team';
    }}

    // ── Bridge for the detail modal (which lives in a separate closure) ──
    // The modal's quick-action buttons + "Edit Event" call these. opsWrite
    // routes a patch to the right table; opsOpenEditor expands the source
    // card's full edit form.
    var _STAGE_ORDER = ['Submitted', 'Followed up', 'Meeting held', 'Booked', 'Rejected', 'Attending'];
    window.opsStageOrder = _STAGE_ORDER;
    // Bridge so the modal's Edit form (separate closure) can re-derive the
    // structured start/end dates when a manual event's date TEXT is edited.
    window.opsDeriveDates = deriveDatesFromText;
    window.opsWrite = function (table, key, patch) {{
      var who = getCollabName() || 'Team';
      var run;
      if (table === 'manual_events') {{
        // manual_events has no updated_by column (it tracks created_by on
        // insert), so don't stamp it — doing so failed the whole save.
        run = sbWriteRetry(patch, function (p) {{ return sb.from('manual_events').update(p).eq('id', key); }});
      }} else {{
        patch.updated_by = who;
        var pp = dict_assign({{ event_num: key }}, patch);
        run = sbWriteRetry(pp, function (p) {{ return sb.from('event_state').upsert(p, {{ onConflict: 'event_num' }}); }});
      }}
      return run.then(function (resp) {{
        if (resp && resp.error) {{ status('Save failed: ' + resp.error.message, 'error'); }}
        else if (resp && resp.strippedMigrationCols && resp.strippedMigrationCols.length) {{
          // The write LANDED, but one or more user-entered columns don't exist in
          // the database yet (a pending migration), so those values were dropped.
          // Say so instead of flashing a misleading "Saved" (this was the silent
          // "Apply to speak link doesn't store" bug).
          status('Saved the rest — but "' + resp.strippedMigrationCols.join('", "') +
            '" could not be stored: that column is missing from the database. It needs a one-time Supabase migration before it will save.', 'error');
          renderOps(who);
        }}
        else {{ flashOk('Saved'); renderOps(who); }}
        return resp;
      }});
    }};
    function dict_assign(a, b) {{ for (var k in b) {{ if (Object.prototype.hasOwnProperty.call(b, k)) a[k] = b[k]; }} return a; }}
    // Current collaborator's display name, for the modal's "I'm interested"
    // toggle. Pass ensure=true to prompt for a name if none is set yet.
    window.opsCurrentUser = function (ensure) {{
      if (ensure && !getCollabName()) return ensureCollabName();
      return getCollabName() || '';
    }};
    // Re-fetch + re-render everything (used after server-side enrichment writes).
    window.opsRefresh = function () {{ return renderOps(getCollabName() || 'Team'); }};
    // ── "Don't bring this back" backlog ─────────────────────────────
    // Every delete is recorded in deleted_events so the nightly Dust ingest can
    // skip an event someone has already thrown out (api/events.py reads this
    // table and reports it as "previously deleted"). A hard-deleted manual event
    // used to leave no trace at all, so the scraper would re-add it days later.
    //
    // Best-effort by design: a table that hasn't been migrated yet, or a failed
    // insert, NEVER blocks the delete. Worst case the scraper re-suggests it.
    function recordDeleted(info) {{
      if (!info || !info.name) return;
      var row = {{
        name:         String(info.name).slice(0, 300),
        start_date:   (info.start_date && /^\\d{{4}}-\\d{{2}}-\\d{{2}}/.test(info.start_date)) ? String(info.start_date).slice(0, 10) : null,
        location:     info.location ? String(info.location).slice(0, 300) : null,
        source_table: info.table || null,
        source_key:   (info.key == null) ? null : String(info.key),
        deleted_by:   getCollabName() || null,
        reason:       info.reason || 'deleted in the tracker'
      }};
      try {{
        sb.from('deleted_events').insert(row).then(function (r) {{
          if (r && r.error) console.warn('deleted_events not recorded: ' + r.error.message);
        }}, function (e) {{ console.warn('deleted_events not recorded: ' + e); }});
      }} catch (e) {{ console.warn('deleted_events not recorded: ' + e); }}
    }}
    window.opsRecordDeleted = recordDeleted;
    // Name / date / location for the row being deleted, pulled from what's
    // already loaded (an event_state override wins over the catalog value, same
    // as everywhere else). Returns a nameless stub if we can't find it — then
    // recordDeleted no-ops rather than writing a useless row.
    function _deletedInfoFor(table, key) {{
      var o = null, st = {{}};
      if (table === 'manual_events') {{
        o = (_lastManual || []).filter(function (m) {{ return String(m.id) === String(key); }})[0];
        st = o || {{}};
      }} else {{
        o = (_lastEvs || []).filter(function (e) {{ return String(e.num) === String(key); }})[0];
        st = (o && (_lastStateMap || {{}})[o.num]) || {{}};
      }}
      if (!o) return {{ table: table, key: key, name: '' }};
      return {{
        table: table, key: key,
        name:       st.name       || o.name       || '',
        start_date: st.start_date || o.start_date || '',
        location:   st.location   || o.location   || ''
      }};
    }}

    // Delete bridge for the modal's Edit form. Manual events are hard-deleted;
    // catalog events (from the daily ingest) are persistently suppressed via a
    // '__deleted__' sentinel on their event_state row, so they don't reappear.
    // Either way the event goes on the deleted_events backlog first, so the
    // ingest won't offer it again.
    window.opsDelete = function (table, key) {{
      var _info = _deletedInfoFor(table, key);
      if (table === 'manual_events') {{
        return sb.from('manual_events').delete().eq('id', key).then(function (resp) {{
          if (resp && resp.error) {{ status('Delete failed: ' + resp.error.message, 'error'); }}
          else {{
            // Record only once the delete actually landed.
            recordDeleted(_info);
            flashOk('Manual event deleted'); if (typeof loadKnownNames === 'function') loadKnownNames(); renderOps(getCollabName() || 'Team');
          }}
          return resp;
        }});
      }}
      // Catalog event — soft-delete via opsWrite (re-renders + filters it out).
      recordDeleted(_info);
      return window.opsWrite('event_state', key, {{ status: '__deleted__' }});
    }};

    // ── Per-event team chat (the "Discussion" thread) ───────────────
    // The modal lives in a separate closure with no direct `sb`, so it hands us
    // the record and we own fetch / render / send here. Degrades quietly to a
    // "run the migration" note if the event_chat table isn't there yet.
    var _chatCounts = {{}};
    var _chatMeta = {{}};   // per event: {{count, latest, msgs:[{{author, at}}]}} — feeds "In the last week"
    function loadChatCounts() {{
      sb.from('event_chat').select('event_num,manual_id,author,created_at,body').then(function (resp) {{
        if (resp.error || !resp.data) return;   // table not migrated yet -> no counts, no noise
        var counts = {{}}, meta = {{}};
        resp.data.forEach(function (r) {{
          var k = (r.manual_id != null) ? ('m' + r.manual_id) : (r.event_num != null ? ('c' + r.event_num) : null);
          if (!k) return;
          counts[k] = (counts[k] || 0) + 1;
          var m = (meta[k] = meta[k] || {{ count: 0, latest: '', msgs: [] }});
          m.count++;
          if ((r.created_at || '') > m.latest) m.latest = r.created_at || '';
          m.msgs.push({{ author: r.author || '', at: r.created_at || '', body: r.body || '' }});
        }});
        _chatCounts = counts; _chatMeta = meta; _paintChatCounts();
        if (currentView === 'myevents') renderMyEvents();   // refresh "new comments" rows
      }});
    }}
    function _paintChatCounts() {{
      Array.prototype.forEach.call(document.querySelectorAll('.chat-count[data-chatkey]'), function (el) {{
        var n = _chatCounts[el.getAttribute('data-chatkey')] || 0;
        el.textContent = n ? ('\\uD83D\\uDCAC ' + n) : '';
        el.style.display = n ? '' : 'none';
      }});
    }}
    // A message's 👍/👎 tallies (stored in event_chat.reactions jsonb —
    // {{up:[names], down:[names]}}; absent until the migration runs → no line).
    // Quick-reaction palette (thumbs first, then a wider range) — Slack-style.
    var CHAT_EMOJIS = ['\\ud83d\\udc4d', '\\ud83d\\udc4e', '\\u2764\\ufe0f', '\\ud83c\\udf89', '\\u2705', '\\ud83d\\udc40', '\\ud83d\\ude4c'];
    // Normalize a reactions blob to {{emoji: [names]}}, folding the legacy
    // up/down shape into 👍/👎 so old reactions still render.
    function _normReactions(rx) {{
      if (!rx || typeof rx !== 'object') return {{}};
      var out = {{}};
      Object.keys(rx).forEach(function (k) {{
        var em = k === 'up' ? '\\ud83d\\udc4d' : (k === 'down' ? '\\ud83d\\udc4e' : k);
        if (!Array.isArray(rx[k])) return;
        out[em] = (out[em] || []).concat(rx[k]);
      }});
      return out;
    }}
    // Show WHO reacted, not just a count — first names inline (capped, +N).
    function _reactWho(list) {{
      var f = list.map(function (n) {{ return String(n).split(/\\s+/)[0]; }});
      if (f.length <= 3) return f.join(', ');
      return f.slice(0, 2).join(', ') + ' +' + (f.length - 2);
    }}
    function _chatReactLine(rx, me) {{
      rx = _normReactions(rx);
      var out = [];
      Object.keys(rx).forEach(function (em) {{
        var list = rx[em] || []; if (!list.length) return;
        var mine = me && list.some(function (n) {{ return String(n).toLowerCase() === me; }});
        out.push('<span class="chat-react' + (mine ? ' is-mine' : '') + '" title="' + escapeHtml(list.join(', ')) + '">' +
          em + ' <span class="chat-react-who">' + escapeHtml(_reactWho(list)) + '</span></span>');
      }});
      return out.length ? '<div class="chat-reacts">' + out.join(' ') + '</div>' : '';
    }}
    // Toggle my reaction with any emoji from the palette.
    function _chatReact(m, emoji) {{
      var who = (getCollabName() || '').trim(); if (!who) {{ ensureCollabName(); return; }}
      var lc = who.toLowerCase();
      var rx = _normReactions(m.reactions);
      var had = (rx[emoji] || []).some(function (n) {{ return String(n).toLowerCase() === lc; }});
      var cur = (rx[emoji] || []).filter(function (n) {{ return String(n).toLowerCase() !== lc; }});
      if (!had) cur.push(who);
      if (cur.length) rx[emoji] = cur; else delete rx[emoji];
      m.reactions = rx;   // optimistic — so a quick re-toggle sees the new state
      sb.from('event_chat').update({{ reactions: rx }}).eq('id', m.id).select('id, reactions').then(function (resp) {{
        if (resp.error) {{
          status(/column|reactions/i.test(resp.error.message || '')
            ? 'Reactions need the one-time migration (scripts/2026-07-10_chat_reactions.sql) in Supabase.'
            : 'Reaction not saved: ' + resp.error.message, 'error');
          return;
        }}
        // RLS with no UPDATE policy returns success but 0 rows — detect that and
        // tell the user exactly what to run (the updated chat_reactions.sql adds
        // the UPDATE policy).
        if (!resp.data || !resp.data.length) {{
          status('Reactions couldn\\u2019t save \\u2014 event_chat needs an UPDATE policy. Re-run the updated scripts/2026-07-10_chat_reactions.sql in Supabase.', 'error');
          return;
        }}
        _reloadOpenChat();
      }});
    }}
    // Forward a message to a teammate: pick a name, and it posts "↪ @Name — <msg>"
    // into this event's chat, which pings them via the "In the last week" mention.
    // Position a chat popover (forward / more) as a fixed "portal" anchored to
    // its trigger button. Appended to <body> — NOT inside the .chat-list — so it
    // is never clipped by the list's overflow scroll nor covered by the message
    // below it (that was why only the last message's menu was reachable).
    function _positionChatMenu(menu, btn) {{
      // Only ever one chat popover at a time — sweep any other open one (incl.
      // the other type) so forward + ⋯ can't both hang open.
      document.querySelectorAll('.chat-fwd-menu, .chat-more-menu').forEach(function (x) {{ x.remove(); }});
      document.body.appendChild(menu);
      var r = btn.getBoundingClientRect();
      menu.style.position = 'fixed';
      menu.style.left = 'auto';
      menu.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
      var mh = menu.offsetHeight || 44;              // now measurable (in DOM)
      var top = r.bottom + 4;
      if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 4);  // flip up near bottom
      menu.style.top = top + 'px';
      // A fixed menu can't follow the button, so close it on scroll/resize
      // instead of letting it float detached. Self-removing listeners.
      var _dismiss = function () {{ menu.remove(); window.removeEventListener('scroll', _dismiss, true); window.removeEventListener('resize', _dismiss); }};
      window.addEventListener('scroll', _dismiss, true);
      window.addEventListener('resize', _dismiss);
    }}
    function _chatForward(m, btn) {{
      var open = document.querySelector('.chat-fwd-menu'); if (open) open.remove();
      var P = window.AB_PERSONAS || {{}};
      var seen = {{}}, list = [];
      Object.keys(P).forEach(function (k) {{
        var n = (P[k] && P[k].name) ? String(P[k].name).split(/\\s+/)[0] : k;
        var lc = n.toLowerCase(); if (seen[lc]) return; seen[lc] = 1; list.push(n);
      }});
      if (!list.length) return;
      var menu = document.createElement('div'); menu.className = 'chat-fwd-menu';
      menu.innerHTML = '<div class="chat-fwd-head">Forward to</div>' +
        list.map(function (n) {{ return '<button type="button" class="chat-fwd-item" data-fwd="' + escapeHtml(n) + '">' + escapeHtml(n) + '</button>'; }}).join('');
      _positionChatMenu(menu, btn);
      function _close() {{ menu.remove(); }}
      menu.querySelectorAll('[data-fwd]').forEach(function (b) {{
        b.addEventListener('click', function (e) {{
          e.stopPropagation();
          var to = b.getAttribute('data-fwd');
          var who = (window.opsCurrentUser ? window.opsCurrentUser(true) : getCollabName()) || ''; if (!who) return;
          var panel = document.getElementById('event-chat-panel'); if (!panel || !panel.dataset.col) return;
          var row = {{ author: who, body: '\\u21aa @' + to + ' \\u2014 ' + String(m.body || '') }};
          row[panel.dataset.col] = panel.dataset.keyval;
          _close();
          sb.from('event_chat').insert(row).then(function (resp) {{
            if (resp.error) {{ status('Forward failed: ' + resp.error.message, 'error'); return; }}
            flashOk('Forwarded to ' + to); _reloadOpenChat(); loadChatCounts();
          }});
        }});
      }});
      setTimeout(function () {{ document.addEventListener('click', function _c(ev) {{ if (!menu.contains(ev.target)) {{ _close(); document.removeEventListener('click', _c); }} }}); }}, 0);
    }}
    // ⋯ "More" overflow → a small menu whose main item is Delete, so the delete
    // is clearly visible instead of hidden. isMod = deleting someone else's
    // message (support moderation).
    function _chatMore(m, btn, isMod) {{
      var open = document.querySelector('.chat-more-menu');
      if (open) {{ open.remove(); return; }}
      var menu = document.createElement('div'); menu.className = 'chat-more-menu';
      menu.innerHTML = '<button type="button" class="chat-more-item chat-more-del" data-mdel="1">\\u2715 Delete message' +
        (isMod ? ' <span class="chat-more-tag">(moderate)</span>' : '') + '</button>';
      _positionChatMenu(menu, btn);
      function _close() {{ menu.remove(); }}
      menu.querySelector('[data-mdel]').addEventListener('click', function (e) {{
        e.stopPropagation();
        _close();
        if (!window.confirm('Delete this message? This cannot be undone.')) return;
        sb.from('event_chat').delete().eq('id', m.id).then(function (resp) {{
          if (resp.error) {{ status('Delete failed: ' + resp.error.message, 'error'); return; }}
          flashOk('Message deleted'); _reloadOpenChat(); loadChatCounts();
        }});
      }});
      setTimeout(function () {{ document.addEventListener('click', function _c(ev) {{ if (!menu.contains(ev.target)) {{ _close(); document.removeEventListener('click', _c); }} }}); }}, 0);
    }}
    // "Add to notes" — append the message to the event's Notes (fresh-read the
    // current value so we never clobber a concurrent edit), via opsWrite.
    function _chatToNotes(m) {{
      var panel = document.getElementById('event-chat-panel');
      if (!panel || !panel.dataset.col) return;
      var col = panel.dataset.col, key = panel.dataset.keyval;
      var table = col === 'manual_id' ? 'manual_events' : 'event_state';
      var idcol = col === 'manual_id' ? 'id' : 'event_num';
      var line = (m.author ? String(m.author) + ': ' : '') + String(m.body || '');
      sb.from(table).select('notes').eq(idcol, key).maybeSingle().then(function (resp) {{
        var cur = (resp && resp.data && resp.data.notes) ? String(resp.data.notes) : '';
        var next = cur ? (cur.replace(/\\s+$/, '') + '\\n' + line) : line;
        if (window.opsWrite) window.opsWrite(table, key, {{ notes: next }});   // flashes "Saved" + re-renders
      }});
    }}
    // Highlight @<teammate> mentions in a chat body. Runs on ALREADY-escaped
    // text (names are alphanumeric, so injecting a <span> is safe). A mention
    // reaches the person via _whatsNewItems, which flags "@<their name>" comments
    // as "You were mentioned" in their "In the last week".
    function _mentionHtml(escaped) {{
      var P = window.AB_PERSONAS || {{}};
      return String(escaped).replace(/@([a-z][a-z0-9]{{1,20}})/gi, function (full, name) {{
        var lc = name.toLowerCase();
        return (P[lc] || lc === 'angela' || lc === 'hurley') ? '<span class="chat-mention">@' + name + '</span>' : full;
      }});
    }}
    function _paintChatList(list, msgs) {{
      // Drop any portaled forward/⋯ menu before we repaint — a realtime push or
      // a fresh send would otherwise leave one floating, detached from its (now
      // re-rendered) message.
      document.querySelectorAll('.chat-fwd-menu, .chat-more-menu').forEach(function (x) {{ x.remove(); }});
      list.innerHTML = '';
      // "Asked AI" rows are a record of who was curious about what. They're
      // useful to Angela (she can see Thor is circling an event before he says
      // anything) and pure clutter to everyone else, who'd just be re-reading
      // their own questions back (Hurley 2026-07-30). Support sees them; the
      // speakers don't — including their own.
      if (!isSupportPerson(getCollabName() || '')) {{
        msgs = msgs.filter(function (m) {{
          return !/^\s*\u2753\s*Asked AI:/.test(String(m.body || ''));
        }});
      }}
      // An empty thread shows nothing at all (Hurley 2026-07-29) — the composer
      // below it is already the invitation to start one.
      if (!msgs.length) return;
      var me = (getCollabName() || '').trim().toLowerCase();
      // Support (Angela / Hurley) can moderate — delete ANY message, not just
      // their own; everyone else can delete only what they wrote.
      var _canModerate = isSupportPerson(getCollabName() || '');
      msgs.forEach(function (m) {{
        var when = '';
        try {{ when = new Date(m.created_at).toLocaleString('en-US', {{ month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }}); }} catch (e) {{}}
        var mine = me && String(m.author || '').trim().toLowerCase() === me;
        var canDel = mine || _canModerate;
        var div = document.createElement('div'); div.className = 'chat-msg';
        div.dataset.msgId = m.id;
        // Slack-style hover toolbar: emoji reactions (👍 👎 first, then more) ·
        // add-to-notes · a ⋯ overflow that opens a menu with "Delete message"
        // (own message, or any for support). To loop a teammate in, @mention them
        // in the message (e.g. "@verma") — it surfaces in their "In the last week".
        var reactBtns = CHAT_EMOJIS.map(function (em) {{
          return '<button type="button" class="chat-act chat-react-btn" data-react="' + em + '" title="React ' + em + '" aria-label="React">' + em + '</button>';
        }}).join('');
        var actions = '<div class="chat-actions">' +
          reactBtns +
          '<span class="chat-act-sep" aria-hidden="true"></span>' +
          '<button type="button" class="chat-act" data-act="note" title="Add to event notes" aria-label="Add to notes">\\ud83d\\udcdd</button>' +
          (canDel
            ? '<button type="button" class="chat-act chat-more" data-act="more" data-canmod="' + (mine ? '0' : '1') + '" title="More actions" aria-label="More">\\u22ef</button>'
            : '') +
          '</div>';
        div.innerHTML = actions +
          '<div class="chat-meta"><span class="chat-who">' + escapeHtml(String(m.author || '')) +
          '</span> <span class="chat-when">' + escapeHtml(when) + '</span></div>' +
          '<p class="chat-body">' + _mentionHtml(escapeHtml(String(m.body || ''))) + '</p>' +
          _chatReactLine(m.reactions, me);
        div.querySelectorAll('.chat-act').forEach(function (btn) {{
          btn.addEventListener('click', function (e) {{
            e.stopPropagation();
            var react = btn.getAttribute('data-react');
            if (react) return _chatReact(m, react);
            var act = btn.getAttribute('data-act');
            if (act === 'note') return _chatToNotes(m);
            if (act === 'more') return _chatMore(m, btn, btn.getAttribute('data-canmod') === '1');
          }});
        }});
        list.appendChild(div);
      }});
      list.scrollTop = list.scrollHeight;
    }}
    function _reloadOpenChat() {{
      var panel = document.getElementById('event-chat-panel');
      if (!panel || !panel.dataset.col) return;
      var list = document.getElementById('chat-list'); if (!list) return;
      sb.from('event_chat').select('*').eq(panel.dataset.col, panel.dataset.keyval)
        .order('created_at', {{ ascending: true }}).then(function (resp) {{
          if (!resp.error) _paintChatList(list, resp.data || []);
        }});
    }}
    window.opsRenderChat = function (rec) {{
      var panel = document.getElementById('event-chat-panel');
      if (!panel) return;
      if (!rec || rec._key == null) {{ panel.innerHTML = ''; return; }}
      var col = rec._table === 'manual_events' ? 'manual_id' : 'event_num';
      panel.dataset.col = col; panel.dataset.keyval = String(rec._key);
      panel.dataset.chatkey = (col === 'manual_id' ? 'm' : 'c') + rec._key;
      panel.innerHTML =
        '<h4 class="chat-h">Chat with the team</h4>' +
        '<div class="chat-list" id="chat-list"><p class="chat-empty">Loading…</p></div>' +
        '<form class="chat-form" id="chat-form">' +
          '<input class="chat-input" id="chat-input" placeholder="Message the team about this event…" autocomplete="off" maxlength="1000">' +
          '<button type="submit" class="chat-send">Send</button>' +
        '</form>' +
        // Per-event mini assistant. Small, one line, under the thread — you ask
        // about THIS event and the answer lands right here (Hurley 2026-07-30).
        // Every question is also posted into the thread, so Angela can see what
        // Thor asked without anyone having to tell her.
        '<form class="ask1-form" id="ask1-form">' +
          '<input class="ask1-input" id="ask1-input" placeholder="Ask AIngela about this event \u2014 status, follow-ups, who to contact\u2026" autocomplete="off" maxlength="300">' +
          '<button type="submit" class="ask1-go"><span class="ask1-ic" aria-hidden="true">\u2726</span> Ask AIngela</button>' +
        '</form>' +
        '<div class="ask1-answer" id="ask1-answer" hidden></div>' +
        '';
      sb.from('event_chat').select('*').eq(col, rec._key).order('created_at', {{ ascending: true }}).then(function (resp) {{
        var list = document.getElementById('chat-list'); if (!list) return;
        // If the event_chat table hasn't been migrated yet, show the normal
        // empty state instead of a setup warning (a send will surface the error).
        if (resp.error) {{ _paintChatList(list, []); return; }}
        _paintChatList(list, resp.data || []);
        // Reading the thread does NOT clear its "In the last week" row any more
        // (Hurley 2026-07-29) — that row comes down only when it's checked off,
        // so opening an event to look at it can't quietly empty your feed.
      }});
      // ── Mini per-event assistant ──────────────────────────────────
      var a1 = document.getElementById('ask1-form');
      if (a1) a1.addEventListener('submit', function (e) {{
        e.preventDefault();
        var inp = document.getElementById('ask1-input');
        var box = document.getElementById('ask1-answer');
        var q = (inp.value || '').trim();
        if (!q) return;
        var who = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || 'Someone';
        inp.value = '';
        box.removeAttribute('hidden');
        box.textContent = 'Thinking…';
        // Scope the question to THIS event by name so the assistant answers
        // about it rather than searching the catalog.
        fetch('/api/ask', {{
          method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            question: 'About the event "' + (rec.name || '') + '": ' + q,
            // This box is one line under the thread — the answer has to fit it.
            // The server turns this into a hard two-sentence brief that also
            // bans padding a status with a description of the event, which is
            // what made these answers read long (Hurley 2026-07-30).
            brief: true,
            history: [], user: who, for_people: []
          }})
        }}).then(function (r) {{ return r.json(); }}).then(function (j) {{
          var _ans = (j && j.answer) ? j.answer : 'No answer available right now.';
          // Same renderer the main assistant uses (escapes first, then bold and
          // links) — this box used to print raw text, so every **bold** run
          // arrived as literal asterisks (Hurley 2026-07-30).
          if (window.abMdToHtml) box.innerHTML = window.abMdToHtml(_ans);
          else box.textContent = _ans;
          // Post the QUESTION into the thread so Angela sees it was asked. The
          // answer isn't posted — it's derived, and would just add noise.
          var row = {{ author: who, body: '\\u2753 Asked AI: ' + q }};
          row[col] = rec._key;
          sb.from('event_chat').insert(row).then(function () {{
            if (typeof loadChatCounts === 'function') loadChatCounts();
          }}, function () {{}});
        }}).catch(function () {{ box.textContent = 'Could not reach the assistant.'; }});
      }});

      var form = document.getElementById('chat-form');
      if (form) form.addEventListener('submit', function (e) {{
        e.preventDefault();
        var inp = document.getElementById('chat-input');
        var body = (inp.value || '').trim(); if (!body) return;
        var who = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || ''; if (!who) return;
        var row = {{ author: who, body: body }}; row[col] = rec._key; inp.value = '';
        sb.from('event_chat').insert(row).then(function (resp) {{
          if (resp.error) {{ status('Message not sent: ' + resp.error.message, 'error'); inp.value = body; return; }}
          _reloadOpenChat(); loadChatCounts();
        }});
      }});
    }};
    window.opsOpenEditor = function (table, key) {{
      // Editing now lives in the Details pop-up, not an inline card editor.
      if (typeof currentView !== 'undefined' && currentView !== 'grid') setView('grid');
      setTimeout(function () {{
        var sel = table === 'manual_events'
          ? '.ops-card[data-manual-id="' + key + '"]'
          : '.ops-card[data-event-num="' + key + '"]';
        var card = $opsGrid.querySelector(sel);
        if (card) card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        if (card && card._modalRec && window.openEventModal) window.openEventModal(card._modalRec);
      }}, 70);
    }};

    // route() — no auth. Always show the collaborative tracker.
    function route() {{
      var who = getCollabName() || 'Team';
      showOnly($ops);
      wireViewToggle();
      wireFilters();
      buildStageFilters();
      buildRegionFilters();
      buildStatusFilters();
      buildExtraFilters();
      wireFilterDropdowns();
      wireFilterToggle();
      applyFilterVisibility();   // hide the "Filters" panel unless Angela is signed in
      renderOps(who);
      wireAddEvent(who);
      setupRealtime(who);
      // Ask for a name on first edit-intent if we still don't have one.
      if (!getCollabName()) {{
        try {{
          $opsGrid.addEventListener('click', function onceAsk() {{
            ensureCollabName();
            $opsGrid.removeEventListener('click', onceAsk);
          }}, {{ once: true }});
        }} catch (e) {{}}
      }}
    }}

    // "Who am I" — your bubble + a dropdown of everyone else's bubbles to
    // switch, alphabetical by name. "Other…" opens the free-text prompt for
    // anyone not on this roster (unchanged behavior from the old Change Users).
    var WHO_ROSTER = [
      {{ name: 'Angela', init: 'A' }},
      {{ name: 'Carlos', init: 'C' }},
      {{ name: 'Hurley', init: 'H' }},
      {{ name: 'Jerome', init: 'JW' }},
      {{ name: 'Jim',    init: 'JC' }},
      {{ name: 'Joe',    init: 'JL' }},
      {{ name: 'Scott',  init: 'S' }},
      {{ name: 'Thor',   init: 'T' }},
      {{ name: 'Verma',  init: 'V' }}
    ];
    function _whoInitFor(name) {{
      var n = String(name || '').trim().toLowerCase();
      var hit = WHO_ROSTER.filter(function (p) {{ return p.name.toLowerCase() === n; }})[0];
      return hit ? hit.init : (n ? n.charAt(0).toUpperCase() : '?');
    }}
    function _closeWhoDropdown() {{
      var dd = document.getElementById('who-dropdown');
      var btn = document.getElementById('who-current-btn');
      if (dd) dd.setAttribute('hidden', '');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    }}
    function _renderWhoSwitcher() {{
      var host = document.getElementById('who-switcher');
      if (!host) return;
      var cur = getCollabName();
      var others = WHO_ROSTER.filter(function (p) {{ return p.name.toLowerCase() !== cur.toLowerCase(); }});
      host.innerHTML =
        '<button type="button" class="who-init who-current" id="who-current-btn" aria-haspopup="true" aria-expanded="false" title="' +
          (cur ? escapeHtml(cur) + ' — profile & switch' : 'Set who you are') + '">' + escapeHtml(_whoInitFor(cur)) + '</button>' +
        '<div class="who-dropdown" id="who-dropdown" hidden>' +
          '<button type="button" class="who-menu-item" id="who-myprofile-btn">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>' +
            (isSupportPerson(cur) ? 'Team Profiles' : 'My Profile') + '</button>' +
          (others.length
            ? '<div class="who-switch-label">Switch to</div><div class="who-switch-row">' +
              others.map(function (p) {{
                return '<button type="button" class="who-init" data-setname="' + escapeHtml(p.name) + '" title="' + escapeHtml(p.name) + '">' + escapeHtml(p.init) + '</button>';
              }}).join('') + '</div>'
            : '') +
          '<button type="button" class="who-other" id="who-other-btn">Someone else&hellip;</button>' +
        '</div>';
      var curBtn = document.getElementById('who-current-btn');
      var dropdown = document.getElementById('who-dropdown');
      curBtn.addEventListener('click', function (e) {{
        e.stopPropagation();
        var willOpen = dropdown.hasAttribute('hidden');
        _closeWhoDropdown();
        if (willOpen) {{ dropdown.removeAttribute('hidden'); curBtn.setAttribute('aria-expanded', 'true'); }}
      }});
      document.getElementById('who-myprofile-btn').addEventListener('click', function (e) {{
        e.stopPropagation();
        _closeWhoDropdown();
        if (!getCollabName()) {{ var n = (window.prompt('Your name:', '') || '').trim(); if (n) setCollabName(n); else return; }}
        setView('myprofile');
        _renderWhoSwitcher();
      }});
      dropdown.querySelectorAll('.who-init[data-setname]').forEach(function (btn) {{
        btn.addEventListener('click', function (e) {{
          e.stopPropagation();
          setCollabName(btn.getAttribute('data-setname'));
          _renderWhoSwitcher();
        }});
      }});
      document.getElementById('who-other-btn').addEventListener('click', function (e) {{
        e.stopPropagation();
        _closeWhoDropdown();
        var n = (window.prompt('Your name:', cur) || '').trim();
        if (n) {{ setCollabName(n); _renderWhoSwitcher(); }}
      }});
    }}
    document.addEventListener('click', function (e) {{
      var switcher = document.getElementById('who-switcher');
      if (switcher && !switcher.contains(e.target)) _closeWhoDropdown();
    }});
    _renderWhoSwitcher();

    // Open immediately — no session wait, no magic link.
    route();
  }});
}})();
</script>
</body>
</html>
'''

    # Public catalog sections (today/upcoming/archive) were retired with the
    # Public view — the Event Tracker is now the sole, fully client-rendered view.
    html = head + foot
    OUT_SHIP.parent.mkdir(parents=True, exist_ok=True)
    OUT_SHIP.write_text(html, encoding='utf-8')
    print(f'WROTE {OUT_SHIP}  ({len(html):,} bytes)')
    print(f'Events: today={len(today_evs)} · upcoming={upcoming_count} · archived={archived_count}')

    # ── Robot-readable companion file for the Dust agent ──────────────────
    # The agent fetches this URL at the start of every run to dedupe.
    # Schema is intentionally flat + small so it's cheap to read.
    write_events_json(today_evs, upcoming, archived)

    # ── Publicly subscribable iCal feed of saved + manual events ─────────
    # Fetches current Supabase state via REST (anon publishable key). Failure
    # to reach Supabase is non-fatal — the existing calendar.ics is left
    # alone so a network blip can't break the build.
    write_calendar_ics(today_evs, upcoming)


def write_events_json(today_evs, upcoming, archived):
    """Emit public/events.json — the canonical, robot-readable event list.
    Read by the ArcticBlueEventSpeaking Dust agent for deduplication.
    Schema is stable; do not break it without bumping `schema_version`."""
    OUT_JSON = HERE / 'public' / 'events.json'

    RICH_KEYS = (
        'about', 'focus_areas', 'typical_attendees', 'speaking_route',
        'contact_info', 'poc_email', 'deadline', 'attendee_count',
        'pay_to_play', 'pricing', 'audience_type', 'past_speakers',
        'meeting_formats', 'attend_verdict', 'postmortem', 'seed', 'urgent',
        'venue', 'city', 'country',
        'notes', 'speaker', 'workflow_status', 'source', 'external_id',
    )

    def serialize(ev, bucket):
        out = {
            'num':           ev.get('num'),
            'name':          ev.get('name', ''),
            'date_str':      ev.get('date_str', ''),
            'start_date':    ev.get('_start').isoformat() if ev.get('_start') else None,
            'end_date':      ev.get('_end').isoformat()   if ev.get('_end')   else None,
            'location':      ev.get('location', ''),
            # Granular region (e.g. "Bay Area") when the source carries one;
            # otherwise fall back to the coarse Americas/Europe/… mapping.
            'region':        ev.get('region') or region_from_location(ev.get('location', '')),
            'region_coarse': region_from_location(ev.get('location', '')),
            'type':          ev.get('type', ''),
            'priority':      ev.get('priority', ''),
            'priority_full': ev.get('priority_full', ev.get('priority', '')),
            'why':           ev.get('why', ''),
            'url':           EVENT_URLS.get(str(ev.get('num', ''))),
            'status':        bucket,
        }
        for k in RICH_KEYS:
            if ev.get(k) not in (None, ''):
                out[k] = ev.get(k)
        return out

    payload = {
        'schema_version': 1,
        # Per-DAY stamp (not per-second): same-day rebuilds stay byte-identical,
        # so the daily auto-build commit never conflicts with a manual edit.
        'generated_at':   TODAY.isoformat() + 'T00:00:00Z',
        'build_date':     TODAY.isoformat(),
        'source':         'arcticblue-event-tracker',
        'canonical_url':  'https://arcticblue-event-tracker-deploy.vercel.app/events.json',
        'counts': {
            'today':    len(today_evs),
            'upcoming': len(upcoming),
            'archived': len(archived),
            'total':    len(today_evs) + len(upcoming) + len(archived),
        },
        'events': (
            [serialize(ev, 'today')    for ev in today_evs] +
            [serialize(ev, 'upcoming') for ev in upcoming]  +
            [serialize(ev, 'archived') for ev in archived]
        ),
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    print(f'WROTE {OUT_JSON}  ({OUT_JSON.stat().st_size:,} bytes, {len(payload["events"])} events)')


def write_calendar_ics(today_evs, upcoming):
    """Emit public/calendar.ics — a publicly subscribable iCal feed of
    every event that's been marked `saved` in event_state PLUS every
    row in manual_events.

    Designed so Angela (or anyone) can paste the deployed feed URL into
    Apple Calendar / Google Calendar / Outlook → Subscribe to URL and
    have it stay in sync without any per-user auth or OAuth dance. The
    feed is regenerated by the daily auto-build GitHub Action.

    Network call is best-effort: if Supabase is unreachable the existing
    public/calendar.ics (if any) is left alone and the build continues.
    """
    import urllib.request, urllib.error
    OUT_ICS = HERE / 'public' / 'calendar.ics'

    headers = {
        'apikey':        SUPABASE_PUBLISHABLE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_PUBLISHABLE_KEY,
        'Accept':        'application/json',
    }

    def fetch(path):
        url = SUPABASE_URL.rstrip('/') + '/rest/v1/' + path
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode('utf-8'))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            print(f'  iCal: skipping — Supabase fetch failed for {path}: {e}')
            return None

    state_rows  = fetch('event_state?select=*')
    manual_rows = fetch('manual_events?select=*&order=created_at.desc')
    if state_rows is None and manual_rows is None:
        return  # leave the previous file in place

    state_rows  = state_rows  or []
    manual_rows = manual_rows or []

    state_by_num = {r['event_num']: r for r in state_rows if r.get('event_num') is not None}

    def ics_escape(s):
        if s is None:
            return ''
        return (str(s)
                .replace('\\', '\\\\')
                .replace(';', '\\;')
                .replace(',', '\\,')
                .replace('\n', '\\n'))

    def ymd(d):
        if not d:
            return None
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        return d.replace('-', '')[:8] or None

    def ymd_plus1(d):
        if not d:
            return None
        if isinstance(d, str):
            d = date.fromisoformat(d)
        from datetime import timedelta
        return (d + timedelta(days=1)).isoformat().replace('-', '')

    # Per-DAY stamp (midnight UTC of the build date), NOT per-second wall-clock:
    # keeps calendar.ics byte-identical across same-day rebuilds so the daily
    # auto-build commit doesn't conflict with manual edits. Still refreshes daily
    # as events roll into the past. (RFC 5545 only needs a valid UTC DTSTAMP.)
    now_iso = TODAY.strftime('%Y%m%dT000000Z')

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//ArcticBlue//Event Tracker//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:ArcticBlue · Saved events',
        'X-WR-CALDESC:All saved events plus every manual addition. Updated daily.',
    ]

    def push_event(uid, name, start, end, location, description, url, urgent):
        lines.append('BEGIN:VEVENT')
        lines.append('UID:' + uid)
        lines.append('DTSTAMP:' + now_iso)
        if start:
            lines.append('DTSTART;VALUE=DATE:' + start)
        if end:
            lines.append('DTEND;VALUE=DATE:' + end)
        lines.append('SUMMARY:' + ics_escape(name))
        if location:
            lines.append('LOCATION:' + ics_escape(location))
        if description:
            lines.append('DESCRIPTION:' + ics_escape(description))
        if url:
            lines.append('URL:' + url)
        if urgent:
            lines.append('CATEGORIES:URGENT')
        lines.append('END:VEVENT')

    # Saved events from the regular catalog
    saved_count = 0
    # Dedup guard: the same real-world event can exist twice (a catalog row
    # holding speaking info + a manual row holding attending info). Emitting
    # both doubles it in every subscribed calendar (Angela's report), so key
    # each VEVENT by normalized-name + start date and emit only the first.
    # Date must match too — "HumanX" (Vegas, Apr) vs "HumanX Amsterdam" (Sep)
    # share a name-core but are different events.
    _seen_keys = set()
    def _dedup_key(name, start_ymd):
        import re as _re
        s = _re.sub(r'[^a-z0-9 ]', ' ', str(name or '').lower())
        s = _re.sub(r'\b(20\d\d|usa|north america|europe|edition|the|annual)\b', ' ', s)
        return ' '.join(s.split()) + '|' + str(start_ymd or '')

    for ev in (today_evs + upcoming):
        st = state_by_num.get(ev.get('num'))
        if not st or not st.get('saved'):
            continue
        _k = _dedup_key(ev.get('name'), ymd(ev.get('_start')))
        if _k in _seen_keys:
            continue
        _seen_keys.add(_k)
        saved_count += 1
        start = ev.get('_start')
        end   = ev.get('_end') or start
        desc_parts = []
        if ev.get('why'):     desc_parts.append(ev['why'])
        if st.get('notes'):   desc_parts.append('Notes: ' + st['notes'])
        if st.get('speaker'): desc_parts.append('Speaker: ' + st['speaker'])
        if st.get('status'):  desc_parts.append('Status: ' + st['status'])
        priority = st.get('priority_override') or ev.get('priority')
        if priority:
            desc_parts.append('Priority: ' + priority)
        push_event(
            uid         = 'event-{}@arcticblue-event-tracker'.format(ev['num']),
            name        = ev.get('name', ''),
            start       = ymd(start),
            end         = ymd_plus1(end) if end else None,
            location    = ev.get('location'),
            description = '\n'.join(desc_parts),
            url         = EVENT_URLS.get(str(ev.get('num', ''))),
            urgent      = bool(st.get('urgent')),
        )

    # Every manual event (Angela added these deliberately, they're always in)
    skipped_manual = 0
    for m in manual_rows:
        sd = m.get('start_date')
        ed = m.get('end_date') or sd
        # Back-compat: older rows pre-date the JS-side date derivation and
        # have NULL start/end. Reuse the existing Python parse_date() so
        # they still appear in the feed with the right multi-day range.
        if not sd and m.get('date_str'):
            ps, pe = parse_date(m['date_str'])
            if ps:
                sd = ps
                if not ed:
                    ed = pe or ps
        if not sd:
            skipped_manual += 1
            continue
        _k = _dedup_key(m.get('name'), ymd(sd))
        if _k in _seen_keys:
            skipped_manual += 1
            continue
        _seen_keys.add(_k)
        desc_parts = []
        if m.get('why'):  desc_parts.append(m['why'])
        if m.get('priority'): desc_parts.append('Priority: ' + m['priority'])
        if m.get('created_by'): desc_parts.append('Added by: ' + m['created_by'])
        push_event(
            uid         = 'manual-{}@arcticblue-event-tracker'.format(m.get('id')),
            name        = m.get('name', ''),
            start       = ymd(sd),
            end         = ymd_plus1(ed) if ed else None,
            location    = m.get('location'),
            description = '\n'.join(desc_parts),
            url         = m.get('url'),
            urgent      = False,
        )

    lines.append('END:VCALENDAR')
    text = '\r\n'.join(lines) + '\r\n'
    OUT_ICS.write_text(text, encoding='utf-8')
    msg = f'WROTE {OUT_ICS}  ({OUT_ICS.stat().st_size:,} bytes, {saved_count} saved + {len(manual_rows) - skipped_manual} manual'
    if skipped_manual:
        msg += f', {skipped_manual} manual skipped — unparseable date_str'
    print(msg + ')')


if __name__ == '__main__':
    build()
