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
      font-family: "Nunito Sans", var(--ab-sans);
      font-weight: 800; font-size: 1.5rem; letter-spacing: -0.02em;
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
    /* One-click "Apply to speak" button on ops cards — the booking shortcut. */
    /* Deadline/closed-to-speak label + Apply button sit side by side in one
       compact row, pinned to the bottom of the card (not each its own
       full-width block). */
    .ops-card-foot {{ display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: auto; }}
    .ops-card-foot .ops-meta {{ margin: 0; }}
    /* Apply always sits flush right — same spot on every card, whether or not
       a deadline/contact note is present to its left. */
    .ops-card-foot .ops-apply-btn {{ margin-left: auto; }}
    .ops-apply-btn {{
      display: inline-flex; align-items: center; justify-content: center;
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
    .modal-date {{
      font-family: var(--ab-mono); font-size: 0.82rem; color: var(--ab-fg-3);
      margin: 0 0 4px; letter-spacing: 0.02em;
    }}
    .modal-title {{
      font-family: var(--ab-sans); font-size: 1.55rem; font-weight: 800;
      line-height: 1.2; letter-spacing: -0.02em; margin: 0 0 8px; color: var(--ab-fg);
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
    .modal-loc {{ font-size: 0.92rem; color: var(--ab-fg-2); margin: 0; }}
    .modal-loc .event-region {{ color: var(--ab-fg); font-weight: 600; }}
    .modal-body {{ display: flex; flex-direction: column; gap: 16px; }}
    .modal-field {{ display: flex; flex-direction: column; gap: 4px; }}
    .modal-field .k {{
      font-family: var(--ab-mono); font-size: 0.64rem; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--ab-fg-3);
    }}
    .modal-field .v {{ font-size: 0.92rem; color: var(--ab-fg); line-height: 1.55; white-space: pre-wrap; }}
    .modal-field .v a {{ color: var(--ab-blue); }}
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
      padding: 0 14px; border-radius: 999px; cursor: pointer; white-space: nowrap;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); text-decoration: underline; text-underline-offset: 2px; transition: all 0.12s;
    }}
    .modal-quickbar .qa:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .modal-quickbar .qa.on {{
      background: #166534; color: #fff; border-color: #166534;
    }}
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
    .modal-quickbar .qa[data-qa="hidden"].on {{ background: var(--ab-fg-3); border-color: var(--ab-fg-3); }}
    .modal-quickbar .qa[data-qa="go"].on {{ background: #1a8c54; border-color: #1a8c54; }}
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

    /* ───────────── archive disclosure ───────────── */
    details.archive-block {{ margin: 64px 0 0; padding-top: 32px; border-top: 1px solid var(--ab-rule); }}
    details.archive-block summary {{
      cursor: pointer; list-style: none;
      display: flex; justify-content: space-between; align-items: baseline;
      gap: 16px; flex-wrap: wrap;
      font-family: var(--ab-sans); font-weight: 800; font-size: 1.4rem;
      letter-spacing: -0.015em; color: var(--ab-fg);
    }}
    details.archive-block summary::-webkit-details-marker {{ display: none; }}
    details.archive-block summary::after {{
      content: "Show / hide";
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.1em; text-transform: uppercase;
      font-weight: 400;
    }}
    details[open].archive-block summary::after {{ content: "Hide"; }}
    .archive-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
      margin-top: 24px;
    }}

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
    .ops-grid {{ display: grid; grid-template-columns: 1fr; gap: 14px; }}
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
    .ops-card.is-saved {{ border-color: var(--ab-blue); }}
    .ops-card.is-mine  {{ border-color: var(--ab-blue); }}   /* the signed-in person starred it */
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
    .chat-h {{ font-family: var(--ab-mono); font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ab-fg-3); margin: 0 0 10px; }}
    .chat-list {{ display: flex; flex-direction: column; gap: 8px; max-height: 260px; overflow-y: auto; margin: 0 0 12px; }}
    .chat-empty {{ font-size: 0.85rem; color: var(--ab-fg-3); font-style: italic; margin: 0; }}
    .chat-msg {{ background: var(--ab-bg-2); border: 1px solid var(--ab-rule); border-radius: 8px; padding: 8px 10px; }}
    .chat-meta {{ display: flex; gap: 8px; align-items: baseline; margin-bottom: 3px; }}
    .chat-who {{ font-weight: 700; font-size: 0.8rem; color: var(--ab-fg); }}
    .chat-when {{ font-family: var(--ab-mono); font-size: 0.6rem; color: var(--ab-fg-3); }}
    /* Delete — only rendered on your own messages. */
    .chat-del {{
      margin-left: auto; border: 0; background: none; cursor: pointer;
      color: var(--ab-fg-3); font-size: 1rem; line-height: 1; padding: 0 2px;
    }}
    .chat-del:hover {{ color: var(--ab-red); }}
    .chat-body {{ margin: 0; font-size: 0.9rem; color: var(--ab-fg-2); line-height: 1.45; white-space: pre-wrap; word-break: break-word; }}
    .chat-form {{ display: flex; gap: 8px; }}
    .chat-input {{ flex: 1; padding: 9px 12px; border: 1px solid var(--ab-rule-strong); border-radius: 8px; font: inherit; font-size: 0.9rem; }}
    .chat-send {{ padding: 9px 16px; border-radius: 8px; border: 1px solid var(--ab-blue); background: var(--ab-blue); color: #fff; font-weight: 600; cursor: pointer; white-space: nowrap; }}
    .chat-send:hover {{ opacity: 0.9; }}
    /* One row: title, then date · place right next to it, then any chips/
       labels (star, urgent, archive, decision, chat count) pushed flush to
       the empty space at the end — same row on every card, so everything
       lands in the same spot instead of shifting card to card. */
    .ops-card-head {{
      display: flex; align-items: flex-start; flex-wrap: wrap;
      column-gap: 14px; row-gap: 6px; margin-bottom: 10px;
    }}
    .ops-card-head .event-name {{ flex: 0 1 auto; min-width: 60px; margin: 0; }}   /* no flex-grow — sizes to its own text so date·place sits right next to it */
    .ops-card-head .event-meta {{ flex: 0 0 auto; margin: 0; white-space: nowrap; }}
    .ops-card-head .ops-chips {{ flex: 0 0 auto; margin-left: auto; }}
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

    .ops-card.is-hidden {{ opacity: 0.55; background: var(--ab-bg-2); }}
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

    /* Stats summary bar */
    .ops-stats {{
      display: grid; gap: 1px;
      grid-template-columns: repeat(6, 1fr);
      background: var(--ab-rule);
      border: 1px solid var(--ab-rule);
      border-radius: 10px;
      overflow: hidden;
      /* More breathing room under the title bar; slightly larger gap below the
         stat bar than between the rows below it. */
      margin-top: 22px;
      margin-bottom: 24px;
    }}
    .ops-stat {{
      background: var(--ab-bg); padding: 14px 16px;
      display: flex; flex-direction: column; gap: 2px;
      align-items: flex-start; text-align: left;
      border: 0; font: inherit; cursor: pointer;
      transition: background 0.12s;
    }}
    .ops-stat:hover {{ background: var(--ab-bg-3); }}
    .ops-stat.is-activestat {{ background: var(--ab-fg); }}
    .ops-stat.is-activestat .num,
    .ops-stat.is-activestat .lbl {{ color: var(--ab-bg) !important; }}
    .ops-stat .num {{
      font-family: var(--ab-mono); font-weight: 600;
      font-size: 1.4rem; letter-spacing: -0.02em;
      color: var(--ab-fg); line-height: 1.1;
    }}
    .ops-stat .lbl {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .ops-stat.saved .num   {{ color: var(--ab-blue); }}
    .ops-stat.urgent .num  {{ color: var(--ab-red); }}
    @media (max-width: 800px) {{
      .ops-stats {{ grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }}
    }}
    @media (max-width: 500px) {{
      .ops-stats {{ grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); }}
    }}

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
    .extra-chip.track-sponsor.is-on  {{ background: #dbeafe; color: #1e40af; border-color: #1e40af; box-shadow: 0 0 0 2px #1e40af; }}
    .extra-chip.track-earned.is-on   {{ background: #fef3c7; color: #92400e; border-color: #92400e; box-shadow: 0 0 0 2px #92400e; }}
    .extra-chip.track-both.is-on     {{ background: #e9d5ff; color: #6b21a8; border-color: #6b21a8; box-shadow: 0 0 0 2px #6b21a8; }}
    .extra-chip.track-unknown.is-on  {{ background: var(--ab-bg-3); color: var(--ab-fg-3); border-color: var(--ab-fg-3); box-shadow: 0 0 0 2px var(--ab-fg-3); }}
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
      grid-column: 1 / -1;
      font-family: var(--ab-mono); font-size: 0.76rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      text-align: right;
    }}

    /* View toggle (Grid / Calendar) */
    .view-toggle {{
      display: inline-flex; flex-wrap: wrap; gap: 4px;
      max-width: 100%; padding: 4px; background: var(--ab-bg-3);
      border-radius: 10px; margin-bottom: 16px;
    }}
    .view-toggle button {{
      font-family: var(--ab-sans); font-weight: 700; font-size: 1.35rem;
      letter-spacing: -0.01em; padding: 9px 20px; border-radius: 7px; border: 0;
      background: transparent; color: var(--ab-fg-2);
      cursor: pointer; transition: background 120ms ease, color 120ms ease;
    }}
    .view-toggle button:hover {{ color: var(--ab-fg); }}
    .view-toggle button.active {{ background: var(--ab-bg); color: var(--ab-fg); box-shadow: 0 1px 2px rgba(0,0,0,0.08); }}
    /* Small count pill inside a view-toggle tab (Queue / Planner alerts). */
    .vt-count {{
      display: inline-block; min-width: 18px; margin-left: 7px; padding: 0 6px;
      font-family: var(--ab-mono); font-size: 0.7rem; line-height: 18px;
      text-align: center; border-radius: 9px; vertical-align: middle;
      background: var(--ab-fg-3); color: #fff;
    }}
    .view-toggle button.active .vt-count {{ background: #1fa0dc; }}
    .vt-count.alert {{ background: #d64545; }}
    /* Secondary view switcher under the merged "Events" tab. List / Calendar
       / Map are three shapes of the same event set, so they read as a
       sub-level, not primary tabs. Shown only on an Events sub-view. */
    .events-subnav {{
      display: inline-flex; gap: 2px; padding: 3px;
      background: var(--ab-bg-3); border-radius: 8px; margin: 0 0 16px;
    }}
    .events-subnav[hidden] {{ display: none; }}
    .subnav-btn {{
      font-family: var(--ab-sans); font-weight: 650; font-size: 0.85rem;
      padding: 6px 15px; border-radius: 6px; border: 0; background: transparent;
      color: var(--ab-fg-2); cursor: pointer;
      transition: background 120ms ease, color 120ms ease;
    }}
    .subnav-btn:hover {{ color: var(--ab-fg); }}
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
    .queue-main {{ min-width: 0; }}
    .queue-name {{
      font-family: var(--ab-sans); font-weight: 650; font-size: 0.98rem; color: var(--ab-fg);
      background: none; border: 0; padding: 0; cursor: pointer; text-align: left;
    }}
    .queue-name:hover {{ color: #1fa0dc; text-decoration: underline; }}
    .queue-meta {{ font-size: 0.8rem; color: var(--ab-fg-3); margin: 3px 0 0; }}
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
    .sug-why {{ margin: 2px 0 0; font-family: var(--ab-mono); font-size: 0.64rem; color: var(--ab-fg-3); letter-spacing: 0.03em; }}
    /* "Mark applied" + the × dismiss sit side by side, not stacked. */
    .q-btn-row {{ display: flex; gap: 6px; align-items: stretch; }}
    .q-btn-row .q-btn.primary {{ flex: 1; }}
    /* Plan Ahead decision buttons: "I'm interested" + "Not for me" side by side. */
    .queue-actions.sug-actions {{ flex-direction: row; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .q-btn.sug-skip {{ color: var(--ab-fg-3); }}
    .q-btn.sug-skip:hover {{ border-color: #d64545; color: #d64545; }}
    /* "Batch your trips" — a cluster of nearby-in-time events under an anchor. */
    .trip-cluster {{ border-left: 3px solid #1fa0dc; padding-left: 12px; margin: 0 0 20px; }}
    .trip-anchor {{ font-size: 0.9rem; color: var(--ab-fg-2); margin: 0 0 8px; }}
    .trip-anchor strong {{ color: var(--ab-fg); }}
    .trip-anchor-name {{ font: inherit; font-weight: 700; color: var(--ab-fg); background: none; border: 0; padding: 0; cursor: pointer; }}
    .trip-anchor-name:hover {{ color: #1271a8; text-decoration: underline; }}
    .trip-anchor-meta {{ display: block; font-family: var(--ab-mono); font-size: 0.72rem; color: var(--ab-fg-3); margin-top: 2px; }}
    .trip-prox {{ font-family: var(--ab-mono); font-size: 0.66rem; color: #1271a8; margin: 3px 0 0; }}
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
    .profile-actions {{ display: flex; align-items: center; gap: 13px; margin: 19px 0 0; }}
    .profile-saved-note {{ font-size: 0.78rem; color: var(--ab-green); font-weight: 600; }}
    .profile-files {{ margin: 8px 0 0; display: flex; flex-direction: column; gap: 7px; }}
    .profile-file {{
      display: flex; align-items: center; gap: 10px; padding: 8px 12px;
      border: 1px solid var(--ab-rule); border-radius: 8px; background: var(--ab-bg-2);
    }}
    .profile-file-name {{ font-size: 0.86rem; color: var(--ab-fg); font-weight: 600; word-break: break-all; flex: 1; text-decoration: none; }}
    .profile-file-name:hover {{ color: var(--ab-blue); text-decoration: underline; }}
    .profile-file-size {{ font-family: var(--ab-mono); font-size: 0.7rem; color: var(--ab-fg-3); white-space: nowrap; }}
    .profile-file-empty {{ font-size: 0.84rem; color: var(--ab-fg-3); font-style: italic; }}
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
    .profile-teammate {{
      border: 1px solid var(--ab-rule); border-radius: 10px; background: var(--ab-bg);
      padding: 14px 16px; margin: 0 0 10px;
    }}
    .profile-tm-head {{ display: flex; align-items: center; gap: 9px; margin: 0 0 6px; }}
    .profile-tm-name {{ font-weight: 700; font-size: 0.96rem; color: var(--ab-fg); }}
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

    /* Row 2: view tabs on the left, add-event actions pushed to the right so
       the row's right edge lines up with the stat cards + filter rows. */
    .ops-controls-row {{
      display: flex; flex-wrap: wrap; align-items: center;
      justify-content: space-between; gap: 16px; margin-bottom: 16px;
    }}
    .ops-controls-row .view-toggle,
    .ops-controls-row .ops-toolbar {{ margin-bottom: 0; }}
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
      padding: 24px;
      border: 1px dashed var(--ab-blue); border-radius: 10px;
      background: var(--ab-bg);
      margin-bottom: 16px;
    }}
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
      .event-grid, .archive-grid, .ops-grid {{ grid-template-columns: 1fr; }}
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
      <h1 class="app-title">ArcticBlue's Event Tracker</h1>
      <div class="nav-meta">{last_updated.upper()} <span class="who">· <span class="who-switcher" id="who-switcher"></span></span></div>
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

    archive_section = f'''
    <details class="archive-block">
      <summary>Archive · {archived_count} past events</summary>
      <div class="archive-grid">
{archived_html}
      </div>
    </details>''' if archived else ''

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
        <div class="ops-stats" id="ops-stats" hidden></div>
        <div class="ops-controls-row">
        <div class="view-toggle" role="tablist" aria-label="View">
          <button type="button" role="tab" data-view="myevents" class="active" aria-selected="true">My Lineup<span class="vt-count" id="vt-myevents-count" hidden></span></button>
          <button type="button" role="tab" data-view="planahead" aria-selected="false">Plan Ahead</button>
          <button type="button" role="tab" id="tab-events" data-events-tab aria-selected="false">Events</button>
          <button type="button" role="tab" data-view="queue"    aria-selected="false">Queue<span class="vt-count" id="vt-queue-count" hidden></span></button>
          <button type="button" role="tab" data-view="planner"  aria-selected="false">Planner<span class="vt-count" id="vt-planner-count" hidden></span></button>
        </div>
        <div class="ops-toolbar" role="group" aria-label="Add events">
            <button class="ab-btn ab-btn--primary" id="add-event-btn">
              <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
              Add event
            </button>
            <button class="ab-btn ab-btn--ghost ab-btn--blue" id="paste-email-btn" title="Paste an event email — name, dates and contacts are pre-filled for you">
              <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg>
              Paste email
            </button>
            <button class="ab-btn ab-btn--ask" id="search-dust-btn" title="Ask the AI to find new speaking events matching your criteria">
              <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .962 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.962 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/></svg>
              Find new events
            </button>
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
        </div>
        </div>
        <div class="events-subnav" id="events-subnav" role="tablist" aria-label="Events view" hidden>
          <button type="button" role="tab" class="subnav-btn" data-view="grid" aria-selected="false">List</button>
          <button type="button" role="tab" class="subnav-btn" data-view="calendar" aria-selected="false">Calendar</button>
          <button type="button" role="tab" class="subnav-btn" data-view="map" aria-selected="false">Map</button>
        </div>
        <div class="ops-topfilters" id="ops-topfilters">
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
          <input type="search" id="ops-search" placeholder="Search: event name, location, key words, etc" aria-label="Search events">
          <button class="ab-btn ab-btn--ask" id="ask-ai-btn" title="Ask the AI to analyse and rank the events currently in view — e.g. 'which of these should I attend in September?'">
            <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .962 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.962 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/></svg>
            Ask Anything
          </button>
        </div>
        <p class="ops-active-filters" id="ops-active-filters" hidden></p>
        <div class="ops-filters collapsed">
          <button type="button" class="ops-filter-toggle" id="ops-filter-toggle" aria-expanded="false" aria-label="Show or hide filters">Filters <span class="ft-caret" aria-hidden="true">▾</span></button>
          <div class="filter-dd" id="filter-price" title="Ticket price as a buyer signal: a pricier pass usually means real buyers, not a hall of vendors">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Ticket price</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- chips injected by buildExtraFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-priority">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Priority</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><!-- chips injected by buildExtraFilters() --></div>
          </div>
          <div class="filter-dd" id="filter-track">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Track</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"></div>
          </div>
          <div class="filter-dd" id="filter-speaker">
            <button type="button" class="filter-dd-btn" aria-haspopup="true" aria-expanded="false"><span class="dd-label">Speaking</span><span class="dd-count"></span> <span class="dd-caret" aria-hidden="true">&#9660;</span></button>
            <div class="filter-dd-menu"><span class="extra-empty" id="filter-speaker-empty">No speakers assigned yet</span></div>
          </div>
          <label class="ops-filter-chip" title="Show only events at the Submitted stage — a speaker application is in"><input type="checkbox" id="ops-f-submitted">Submitted</label>
          <label class="ops-filter-chip" title="Show only events added in the last 7 days (incl. AI-discovered) — the new batch to triage"><input type="checkbox" id="ops-f-recent">Recently added</label>
          <label class="ops-filter-chip" title="Events where an email contact (organizer POC) was found"><input type="checkbox" id="ops-f-contact">Contact found</label>
          <span class="ops-shown" id="ops-shown"></span>
        </div>
        <div class="ops-results-header" id="ops-results-header">
          <button type="button" class="ops-dupe-review" id="ops-dupe-review" title="Show the auto-detected duplicate events so you can delete them (open one, then Details → Edit → Delete this event)" hidden></button>
          <span class="ops-count" id="ops-count"></span>
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
        <div class="ops-planahead" id="ops-planahead"></div>
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
        <div id="modal-head-side"></div>
        <button type="button" class="modal-close" id="modal-close" aria-label="Close">×</button>
      </div>
      <div class="modal-scroll">
        <div class="modal-head">
          <div class="modal-badges" id="modal-badges"></div>
          <p class="modal-date" id="modal-date"></p>
          <h2 class="modal-title" id="modal-title"></h2>
          <p class="modal-loc" id="modal-loc"></p>
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
  function field(label, val, html) {{
    if (val == null || String(val).trim() === '') return '';
    return '<div class="modal-field"><span class="k">' + esc(label) + '</span>' +
           '<span class="v">' + (html ? val : esc(val)) + '</span></div>';
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
    bStage.push('<button type="button" class="qa' + (has('Booked') ? ' on' : '') + '" data-qa="booked">' + (has('Booked') ? '✓ Booked' : 'Speaking Booked') + '</button>');
    // "Attending" is PER-PERSON: it reflects whether the signed-in person is in
    // the attendees list (Thor sees it off when only Jerome attends). Clicking it
    // adds/removes YOU. Angela assigns anyone via the edit-form Attending bubbles.
    var _meKey = ((window.opsCurrentUser ? window.opsCurrentUser() : '') || '').trim().split(/\\s+/)[0].toLowerCase();
    var _iAmAttending = !!(_meKey && (rec.attendees || []).some(function (a) {{ return String(a).toLowerCase() === _meKey; }}));
    bStage.push('<button type="button" class="qa' + (_iAmAttending ? ' on' : '') + '" data-qa="attending" title="Attending is per-person — this marks whether YOU are going">' + (_iAmAttending ? '✓ Attending' : "+ I'm attending") + '</button>');
    // Should Attend is Angela's triage tool — only she sees/sets it here. For
    // everyone else, marking Interested funnels into her Should-Attend list.
    if (window.isAngelaUser && window.isAngelaUser()) {{
      bStage.push('<button type="button" class="qa' + (_saKind === 'human' ? ' on' : '') + '" data-qa="should-attend" title="' +
        (_saKind === 'ai' ? 'AI-suggested — click to confirm as a team Should-Attend' : 'Flag Should Attend — tentative but high on the radar') + '">' +
        (_saKind === 'human' ? '✓ Should Attend' : 'Should Attend') + '</button>');
    }}
    // "Interested" — the current teammate adds themselves to the list of people
    // who want Angela to apply for them. This feeds Angela's Queue.
    var me = (window.opsCurrentUser ? window.opsCurrentUser() : '') || '';
    var iAmIn = !!(me && (rec.interested || []).some(function (n) {{ return String(n).toLowerCase() === me.toLowerCase(); }}));
    // Show the ACTUAL flagged list here (raw), matching the toggle button — using
    // the booked/attending-filtered visibleInterested() made the summary read
    // "No one flagged yet" right after someone (e.g. the speaker) clicked
    // Interested. The dedup still applies to the Planner/Queue + card-face label.
    var summary = formatInterested(rec.interested);
    var intRow =
      '<span class="qa-row-label">Interested:</span>' +
      '<button type="button" class="qa' + (iAmIn ? ' on' : '') + '" data-qa="interested">' + (iAmIn ? '✓ Interested' : "+ I'm interested") + '</button>' +
      (summary
        ? '<span class="qa-int-summary">' + summary + '</span>'
        : '<span class="qa-int-summary qa-int-empty">No one flagged yet</span>');
    // Archive lives at the bottom under a "Hide:" label. Archiving now happens
    // ONLY in this pop-up (the card face just shows an "Archived" label), so the
    // control is here for BOTH catalog and manual events. Manual events also keep
    // their separate "Delete this event" button in the edit form.
    var hideRow = '<span class="qa-row-label">Hide:</span>' +
        '<button type="button" class="qa' + (rec.hidden ? ' on' : '') + '" data-qa="hidden">' + (rec.hidden ? 'Unarchive' : 'Archive') + '</button>';
    return '<div class="modal-quickbar">' +
           '<div class="qa-row" style="align-items:center;"><span class="qa-row-label">Status:</span>' + bStage.join('') + '</div>' +
           '<div class="qa-row" style="margin-top:6px;align-items:center;">' + intRow + '</div>' +
           (hideRow ? '<div class="qa-row" style="margin-top:6px;align-items:center;">' + hideRow + '</div>' : '') +
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
  function wireQuickBar(rec) {{
    var bar = $body.querySelector('.modal-quickbar');
    if (!bar) return;
    bar.addEventListener('click', function (e) {{
      var btn = e.target.closest ? e.target.closest('[data-qa]') : null;
      if (!btn || !window.opsWrite) return;
      var qa = btn.dataset.qa;
      var patch = {{}};
      if (qa === 'saved') {{ rec.saved = !rec.saved; patch.saved = rec.saved; }}
      else if (qa === 'hidden') {{ rec.hidden = !rec.hidden; patch.hidden = rec.hidden; }}
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
      else if (qa === 'submitted' || qa === 'followed-up' || qa === 'booked') {{
        var stage = qa === 'submitted' ? 'Submitted' : (qa === 'followed-up' ? 'Followed up' : 'Booked');
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
      window.opsWrite(rec._table, rec._key, patch);
      openEventModal(rec);
      if (scEl) scEl.scrollTop = sc;
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
    var h = '';
    if (!isCat) {{
      h += ef('Event name', inp('name', rec.name));
      h += ef('Date', inp('date_str', rec.date_str, 'e.g. Sept 14–16, 2026'));
      h += ef('Location', inp('location', rec.location));
    }}
    // Field order (Thor's ask): pipeline stage, notes, ArcticBlue speaker
    // (bubbles), speaker topic, attending, then website link.
    h += ef('Pipeline stage', '<div class="me-stages">' + chips + '</div>');
    h += ef('Notes', ta('notes', rec.notes, 3));
    h += ef('ArcticBlue speaker', '<div class="me-ints">' + spChips + '</div>');
    h += ef('Speaker topic — drives the day-of news pull', inp('speaker_topic', rec.speaker_topic, 'e.g. AI workforce enablement'));
    h += ef('Attending — surfaces a Day-Of brief', '<div class="me-ints">' + attChips + '</div>');
    h += ef((isCat ? 'Website / link' : 'Website'), inp('url', rec.url, 'https://'));
    h += ef('Apply to speak link — powers the card button', inp('apply_url', rec.apply_url, 'https:// CFP or application page'));
    h += ef('Interested (joins Angela\\'s apply queue)', '<div class="me-ints">' + intChips + '</div>');
    h += ef('Priority', '<select class="me-input" data-edit="' + (isCat ? 'priority_override' : 'priority') + '">' + pris.map(function (v) {{ return opt(v, curPri); }}).join('') + '</select>');
    h += ef('Why it fits ArcticBlue', ta('why', rec.why));
    h += ef('About', ta('about', rec.about));
    h += ef('Focus areas', ta('focus_areas', rec.focus_areas, 2));
    h += ef('Typical attendees', ta('typical_attendees', rec.typical_attendees, 2));
    h += ef('Speaking route', ta('speaking_route', rec.speaking_route, 2));
    h += ef('Pay-to-play', '<select class="me-input" data-edit="pay_to_play">' + p2p.map(function (v) {{ return opt(v, rec.pay_to_play); }}).join('') + '</select>');
    h += ef('Venue', inp('venue', rec.venue));
    h += ef('Contact info', inp('contact_info', rec.contact_info));
    h += ef('Deadline', inp('deadline', rec.deadline, 'e.g. July 10, 2026'));
    // Fields that used to live only in the inline card editor — migrated here so
    // editing lives entirely in the Details pop-up (nothing lost).
    if (isCat) {{
      h += ef('Type', inp('type', rec.type, 'e.g. Enterprise'));
      h += ef('Audience (buyers vs sellers)', '<select class="me-input" data-edit="audience_type">' + ['', 'Buyer-rich', 'Mixed', 'Vendor-heavy'].map(function (v) {{ return opt(v, rec.audience_type); }}).join('') + '</select>');
      h += ef('Meetings & networking (1:1s)', inp('meeting_formats', rec.meeting_formats, 'e.g. Hosted 1:1 meetings; roundtables'));
      h += ef('Price to attend', inp('pricing', rec.pricing, 'e.g. $1,995 delegate pass; free for buyers'));
      h += ef('Attendee count', inp('attendee_count', rec.attendee_count, 'e.g. 1,500+'));
      h += ef('Track', '<select class="me-input" data-edit="track">' + ['', 'Sponsor', 'Earned', 'Both', 'Unknown'].map(function (v) {{ return opt(v, rec.track); }}).join('') + '</select>');
      // The free-text "legacy status" label that shows on the card face
      // (e.g. "Sponsorship Only") — editable + clearable; the soft-delete
      // sentinel is hidden so it can't be edited by accident.
      h += ef('Status label (shown on the card)', inp('status', rec.workflow_status === '__deleted__' ? '' : rec.workflow_status, 'e.g. Sponsorship only · clear to remove'));
    }} else {{
      h += ef('Region', '<select class="me-input" data-edit="region">' + ['', 'US & Canada', 'Latin America', 'Europe', 'Africa', 'MENA', 'Asia-Pacific', 'Global'].map(function (v) {{ return opt(v, rec.region); }}).join('') + '</select>');
      h += ef('Type', inp('type', rec.type));
      h += ef('Audience (buyers vs sellers)', '<select class="me-input" data-edit="audience_type">' + ['', 'Buyer-rich', 'Mixed', 'Vendor-heavy'].map(function (v) {{ return opt(v, rec.audience_type); }}).join('') + '</select>');
      h += ef('Price to attend', inp('pricing', rec.pricing));
      h += ef('Attendee count', inp('attendee_count', rec.attendee_count));
      h += ef('Meetings & networking', inp('meeting_formats', rec.meeting_formats));
      h += ef('Past / announced speakers', ta('past_speakers', rec.past_speakers, 2));
      h += ef('Submission status', inp('submission_status', rec.submission_status));
      h += ef('POC name', inp('poc_name', rec.poc_name));
      h += ef('POC email', inp('poc_email', rec.poc_email));
      h += ef('POC LinkedIn', inp('poc_linkedin', rec.poc_linkedin));
      h += ef('Additional contacts', ta('additional_contacts', rec.additional_contacts, 2));
      h += ef('Speaking fee', inp('speaking_fee', rec.speaking_fee));
      var paidCur = rec.paid === true ? 'true' : (rec.paid === false ? 'false' : '');
      h += ef('Paid', '<select class="me-input" data-edit="paid">' + [['', '—'], ['true', 'Yes'], ['false', 'No']].map(function (o) {{ return '<option value="' + o[0] + '"' + (paidCur === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; }}).join('') + '</select>');
    }}
    h += ef('Post-mortem (ROI: contacts · meetings · sales vs cost)', ta('postmortem', rec.postmortem, 2));
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
    box.querySelectorAll('[data-edit]').forEach(function (el) {{
      el.addEventListener('change', function () {{
        var field = el.dataset.edit;
        var val = (el.value == null ? '' : String(el.value)).trim();
        if (field === 'name' && !val) {{ el.value = rec.name || ''; return; }}
        var out = val === '' ? null : val;
        if ((field === 'url' || field === 'apply_url') && out && !/^https?:\\/\\//i.test(out)) out = 'https://' + out;
        // "Paid" is a boolean column on manual_events — coerce the select value.
        if (field === 'paid') out = (val === 'true') ? true : (val === 'false' ? false : null);
        var patch = {{}}; patch[field] = out;
        if (field === 'priority_override') rec.priority = out;
        else rec[field] = out;
        window.opsWrite(rec._table, rec._key, patch);
      }});
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

  function openEventModal(rec) {{
    if (!rec) return;
    var badges = [];
    // Priority range (High / Medium / Low) — shown to everyone. Blends the
    // stored priority with buyer-rich + who's interested (see cardPriority).
    var _mdPri = cardPriority(rec);
    if (_mdPri) badges.push('<span class="badge ' + priClass(_mdPri) + '">' + esc(_mdPri) + '</span>');
    // "Halo" is an internal event-type flag, not something to surface as a label.
    if (rec.type && rec.type.toLowerCase() !== 'halo') badges.push('<span class="badge p-medium">' + esc(rec.type) + '</span>');
    // Pipeline stages (primary). Fall back to the legacy single status badge
    // only when no stages are set, so we don't double up.
    if (rec.stage_tags && rec.stage_tags.length) {{
      rec.stage_tags.forEach(function (k) {{ badges.push('<span class="badge p-low">' + esc(k) + '</span>'); }});
    }} else if (rec.workflow_status) {{
      badges.push('<span class="badge p-low">' + esc(rec.workflow_status) + '</span>');
    }}
    if (rec.status && !(rec.stage_tags && rec.stage_tags.length) && /booked|confirm|attend/i.test(rec.status)) badges.push('<span class="badge p-low">' + esc(rec.status) + '</span>');
    if (rec.pay_to_play && /yes|both/i.test(rec.pay_to_play)) badges.push('<span class="badge p-low">Pay-to-play</span>');
    // (Buyer-rich audience is no longer its own badge — it now feeds the
    //  priority range above, so a buyer-rich room reads as higher priority.)
    if (rec.seed === true)   badges.push('<span class="badge p-low">Seed</span>');
    $badges.innerHTML = badges.join('');

    $date.textContent  = rec.date_str || '';
    if (rec.url) {{
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

    // Read-only view. The edit form below mirrors this exact layout.
    var v = '';
    // (Interest is shown once, in the quick-bar above — no duplicate field here.)
    // "Why it fits ArcticBlue" removed from the read view (Hurley 2026-07-09) —
    // still editable in the Edit form and used by search/suggestions scoring.
    v += field('About', rec.about);
    v += field('Focus areas', rec.focus_areas);
    v += field('Typical attendees', rec.typical_attendees);
    v += field('Past / announced speakers', rec.past_speakers);
    v += field('Meetings & networking', rec.meeting_formats);
    v += field('Speaking route', rec.speaking_route);

    // Short facts in a 2-up grid
    var grid = '';
    grid += field('Deadline', rec.deadline);
    grid += field('Attendee count', rec.attendee_count);
    grid += field('Audience', rec.audience_type);
    grid += field('Price to attend', rec.pricing);
    grid += field('Pay-to-play', rec.pay_to_play);
    grid += field('Venue', rec.venue);
    grid += field('Submission status', rec.submission_status);
    grid += field('Speaking fee', rec.speaking_fee);
    if (grid) v += '<div class="modal-grid">' + grid + '</div>';

    v += field('ArcticBlue speaker', rec.speaker);

    // Contacts
    var contactBits = [];
    if (rec.poc_name)  contactBits.push(esc(rec.poc_name));
    if (rec.poc_email) contactBits.push('<a href="mailto:' + esc(rec.poc_email) + '">' + esc(rec.poc_email) + '</a>');
    if (rec.poc_linkedin) contactBits.push('<a href="' + esc(rec.poc_linkedin) + '" target="_blank" rel="noopener">LinkedIn ↗</a>');
    if (contactBits.length) v += field('Point of contact', contactBits.join(' · '), true);
    v += field('Contact info', rec.contact_info);
    v += field('Additional contacts', rec.additional_contacts);
    v += field('Post-mortem (ROI)', rec.postmortem);
    v += field('Notes', rec.notes);

    html += '<div class="modal-view">' + (v || '<p class="modal-nolink">No extra detail on file for this event yet.</p>') + '</div>';
    var editForm = editFormHtml(rec);
    if (editForm) html += '<div class="modal-editform" hidden>' + editForm + '</div>';

    $body.innerHTML = html;
    wireQuickBar(rec);
    wireEditForm(rec);
    if (window.opsRenderChat) window.opsRenderChat(rec);

    // "Edit event" toggle — header top-right, same spot for every event. It
    // swaps the read-only view for the (identically-laid-out) edit form.
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
        if (form.hasAttribute('hidden')) {{
          form.removeAttribute('hidden'); if (view) view.setAttribute('hidden', '');
          et.classList.add('on'); et.setAttribute('aria-expanded', 'true');
          et.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">✓</span> Done';
        }} else {{
          form.setAttribute('hidden', ''); if (view) view.removeAttribute('hidden');
          et.classList.remove('on'); et.setAttribute('aria-expanded', 'false');
          et.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">✎</span> Edit';
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
  window.visibleInterested = function (interested, speaker, attendees) {{
    if (!interested || !interested.length) return [];
    var covered = {{}};
    (attendees || []).forEach(function (a) {{ var k = String(a).toLowerCase().trim(); if (k) covered[k] = 1; }});
    String(speaker || '').toLowerCase().replace(/\\s+and\\s+/g, ',').split(/[,;\\/&]/).forEach(function (s) {{
      s = s.trim(); if (s) {{ covered[s] = 1; covered[s.split(/\\s+/)[0]] = 1; }}
    }});
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
    var opsCollapsedMonths = {{ hidden: true, archive: true }};
    // Active stat-tile filter ('' | 'saved' | 'urgent' | 'pipeline' | 'booked'
    // | 'buyer' | 'interested') — click a top stat to show only those events.
    var opsStatFilter = '';
    // When true, the auto-detected duplicate cards are REVEALED (marked
    // "DUPLICATE") instead of hidden, so they can be opened + deleted in-app.
    var _reviewDupes = false;

    // Last-fetched data, cached by renderOps() so the Queue + Planner views can
    // render from the SAME set the grid just built (no extra fetch).
    var _lastEvs = [], _lastStateMap = {{}}, _lastStateRows = [], _lastManual = [];
    // Roster used by the Planner's coverage-gap "Flag for X" action. (The modal
    // closure has its own AB_ROSTER; this closure needs its own copy.)
    var OPS_ROSTER = ['Thor', 'Joe', 'Jerome', 'Scott', 'Verma', 'Carlos', 'Jim'];

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
      {{ group: 'Confirmed', value: 'Booked',                                  bg: '#047857', fg: '#ffffff' }},
      {{ group: 'Confirmed', value: 'Self Submitted',                          bg: '#15803d', fg: '#ffffff' }},
      {{ group: 'Confirmed', value: 'Attending',                               bg: '#a78bfa', fg: '#3730a3' }},
      {{ group: 'Confirmed', value: 'Attending (Not Speaking)',                bg: '#c4b5fd', fg: '#4c1d95' }},
      {{ group: 'Confirmed', value: 'Attending?',                              bg: '#ddd6fe', fg: '#5b21b6' }},
      // ── Active / in progress ──
      {{ group: 'Active',    value: 'Submitted',                               bg: '#bbf7d0', fg: '#14532d' }},
      {{ group: 'Active',    value: 'Booking in Progress',                     bg: '#86efac', fg: '#14532d' }},
      {{ group: 'Active',    value: 'In contact with',                         bg: '#d1fae5', fg: '#065f46' }},
      {{ group: 'Active',    value: 'In Progress',                             bg: '#fcd34d', fg: '#78350f' }},
      {{ group: 'Active',    value: 'Received Intro Meeting',                  bg: '#a7f3d0', fg: '#064e3b' }},
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
      {{ group: 'Closed',    value: 'Not Accepted',                            bg: '#dc2626', fg: '#ffffff' }},
      {{ group: 'Closed',    value: 'Not Accepted This Yr',                    bg: '#ef4444', fg: '#ffffff' }},
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
      {{ key: 'Attending',    dot: '#0d9488', bg: '#ccfbf1', fg: '#115e59' }}
    ];
    var STAGE_BY_KEY = {{}};
    STAGE_TAGS.forEach(function (s, i) {{ s.order = i; STAGE_BY_KEY[s.key] = s; }});
    // "Most important" ranking for a single calendar tint when an event
    // carries several stages: a win (Booked) trumps everything, then
    // Attending, then progress backwards.
    var STAGE_DISPLAY_RANK = ['Booked', 'Attending', 'Meeting held', 'Followed up', 'Submitted', 'Identified'];

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
      var now = new Date();
      var todayIso = now.getFullYear() + '-' +
        String(now.getMonth() + 1).padStart(2, '0') + '-' +
        String(now.getDate()).padStart(2, '0');
      return iso <= todayIso;
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
      if (has(/\\b(brazil|brasil|sao paulo|rio de janeiro|mexico|cdmx|argentina|buenos aires|chile|santiago|colombia|bogota|peru|lima|venezuela|caracas|uruguay|ecuador|latin america|latam|south america)\\b/)) return 'Latin America';
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
      if (st.track) {{
        tags.push('<span class="ops-tag">' + escapeHtml(st.track) + '</span>');
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
    function toggleMyInterest(kind, key, list) {{
      var me = (window.opsCurrentUser ? window.opsCurrentUser(true) : '') || '';
      if (!me) return;   // no name -> nothing to flag
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
    function starButtonHtml(list) {{
      var on = meInInterested(list);
      return '<button class="saved-star ops-hover' + (on ? ' is-on' : '') + '" data-star type="button"' +
        ' aria-label="I\\'m interested" title="Star = I\\'m interested (adds you to the interested list + Angela\\'s queue)">' +
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
      // Secondary: small track pill (kept, out of the roster).
      var pills = [];
      if (st.track) pills.push('<span class="ops-tag">' + escapeHtml(st.track) + '</span>');
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
    // Card date label: drop the year when it's THIS year (the month divider
    // above the card already shows it) — but keep it for other years (next year)
    // as an at-a-glance signal.
    function cardDate(dateStr, startIso) {{
      var s = (dateStr || '').trim();
      if (!s) return s;
      var y = (startIso && /^\\d{{4}}-/.test(startIso)) ? startIso.slice(0, 4) : '';
      if (!y) {{ var m = s.match(/\\b20\\d\\d\\b/); if (m) y = m[0]; }}
      if (y && y === String(new Date().getFullYear())) {{
        s = s.split(y).join('');
        s = s.replace(/[\\s,\\/]+$/, '').replace(/^[\\s,\\/]+/, '').trim();
      }}
      return s;
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
    // ONE derived status line per card — computed from the data, never
    // hand-edited (Thor: "closed for speaking, open for attending" must show
    // without anyone editing it in). Examples:
    //   Booked — Thor speaking
    //   Submitted to speak (CFP closed) · Open to attend
    //   Closed to speak · Open to attend
    //   Attending — Jerome
    // Shows NOTHING when we know nothing — no invented status, no filler.
    function cardStatusLine(ev, st) {{
      st = st || ev;
      var stages = stageTagsOf(st);
      var past = isPastEvent(ev);
      var speaker = (st.speaker || '').trim();
      var att = ((st.attendees || ev.attendees) || []).map(_personName).filter(Boolean);
      var d = (st.deadline != null && String(st.deadline).trim()) ? st.deadline : ev.deadline;
      var closed = !past && d && !_isJunkVal(d) && isDeadlinePast(d);
      var speakBit = '', attendBit = '';
      if (stages.indexOf('Booked') !== -1) {{
        speakBit = '<span class="st-bit"><span class="st-dot st-ok"></span>Booked' + (speaker ? ' \\u2014 ' + escapeHtml(speaker) + ' speaking' : '') + '</span>';
      }} else if (stages.indexOf('Submitted') !== -1 || stages.indexOf('Followed up') !== -1 || stages.indexOf('Meeting held') !== -1) {{
        speakBit = '<span class="st-bit"><span class="st-dot st-wait"></span>Submitted to speak' + (closed ? ' (CFP closed)' : '') + '</span>';
      }} else if (closed) {{
        speakBit = '<span class="st-bit"><span class="st-dot st-no"></span>Closed to speak</span>';
      }} else if (!past && d && !_isJunkVal(d)) {{
        speakBit = '<span class="st-bit"><span class="st-dot st-ok"></span>Open to speak</span>';
      }}
      if (att.length) attendBit = '<span class="st-bit"><span class="st-dot st-ok"></span>Attending \\u2014 ' + escapeHtml(att.join(', ')) + '</span>';
      // The Attending STAGE is set but no attendee is named yet — still show it,
      // so ticking "Attending" on the add form holds visibly (add who in Edit).
      else if (stages.indexOf('Attending') !== -1 && !past) attendBit = '<span class="st-bit"><span class="st-dot st-ok"></span>Attending</span>';
      else if (!past && speakBit && stages.indexOf('Booked') === -1) attendBit = '<span class="st-bit">Open to attend</span>';
      var bits = [speakBit, attendBit].filter(Boolean);
      if (!bits.length) return '';
      return '<p class="ops-status-line">' + bits.join('<span class="st-sep">\\u00b7</span>') + '</p>';
    }}
    function deadlineLine(d, o) {{
      // Raw CFP deadline DATES are Angela's business (she runs applications) —
      // the derived open/closed STATUS shows for everyone via cardStatusLine.
      if (!(window.isAngelaUser && window.isAngelaUser())) return '';
      if (d == null || !String(d).trim()) return '';
      var txt = String(d).trim();
      if (_isJunkVal(txt)) return '';   // skip "not specified" / "TBD" / "N/A" clutter
      if (isDeadlinePast(d)) return '';  // closed state is on the status line now
      // A CFP deadline on or after the event itself is nonsensical — you can't
      // submit a talk once the event has started. (Angela saw "CFP deadline:
      // 1 September 2026" on an event running July 7-10.) Hide it rather than
      // confuse. Parse the deadline the same resilient way isDeadlinePast does.
      var evStart = eventStartIso(o);
      if (evStart) {{
        var dl = null;
        try {{ var diso = deriveDatesFromText(txt).start_date; if (diso) dl = new Date(diso + 'T00:00:00'); }} catch (e) {{}}
        if (!dl || isNaN(dl)) {{ var d2 = new Date(txt); if (!isNaN(d2)) dl = d2; }}
        var evd = new Date(evStart + 'T00:00:00');
        if (dl && !isNaN(dl) && !isNaN(evd) && dl >= evd) return '';
      }}
      var cls = isDeadlineSoon(d) ? ' deadline-soon' : '';
      return '<p class="ops-meta deadline-line' + cls + '">CFP deadline: ' + escapeHtml(txt) + '</p>';
    }}

    // "Contact found" = we have a real email to reach this event's organizer,
    // in the structured poc_email or embedded in the free-text contact_info.
    var _EMAIL_RE = /[^\\s@]+@[^\\s@]+\\.[^\\s@]{{2,}}/;
    function hasEmailContact() {{
      for (var i = 0; i < arguments.length; i++) {{
        var o = arguments[i]; if (!o) continue;
        if (_EMAIL_RE.test(String(o.poc_email || ''))) return true;
        if (_EMAIL_RE.test(String(o.contact_info || ''))) return true;
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
      card.dataset.track    = (st.track || '');
      card.dataset.speaker  = (st.speaker || '');
      // Attending signals — an event_state override (edited on the card) wins
      // over the catalog value, so audience / 1:1 / price edits show on the face.
      var _aud   = (st.audience_type  && String(st.audience_type).trim())  ? st.audience_type  : ev.audience_type;
      var _meet  = (st.meeting_formats && String(st.meeting_formats).trim()) ? st.meeting_formats : ev.meeting_formats;
      var _price = (st.pricing && String(st.pricing).trim()) ? st.pricing : ev.pricing;
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
      var _opsPast = isPastEvent(ev);
      card.dataset.past = _opsPast ? '1' : '';
      if (_opsPast) card.classList.add('is-past');
      if (st.saved)  card.classList.add('is-saved');
      if (meInInterested(st.interested)) card.classList.add('is-mine');   // I starred it → blue outline
      if (st.hidden) card.classList.add('is-hidden');
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
      var saBadge = (shouldAttendKind(st.attend_verdict) === 'human' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="sa-badge">★ Should Attend</span>' : '';
      card.dataset.contactFound = hasEmailContact(st, ev) ? '1' : '';
      // Contact (POC) badge is Angela's outreach cue — only she sees it on the card.
      var contactBadge = (card.dataset.contactFound === '1' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="contact-badge" title="An email contact was found for this event">✉ Contact</span>' : '';
      // A link added/edited in event_state (override) wins over the catalog URL,
      // so adding a link to a link-less catalog event lights up the card ↗.
      var _cardUrl = (st.url && String(st.url).trim()) ? String(st.url).trim() : (ev.url || '');

      var metaLine = (st.updated_by && st.updated_at)
        ? '<p class="ops-meta" title="' + escapeHtml(st.updated_by) + '">Last edit · ' + escapeHtml(firstNameFromEmail(st.updated_by)) + ' · ' + escapeHtml(formatStamp(st.updated_at)) + '</p>'
        : '';

      // One-click apply (the booking shortcut) — Angela-only.
      var applyUrl = (st && st.apply_url) || speakingRouteUrl(ev.speaking_route);
      var applyBtn = (applyUrl && window.isAngelaUser && window.isAngelaUser())
        ? '<a class="ops-apply-btn" href="' + escapeHtml(applyUrl) + '" target="_blank" rel="noopener">Apply to speak ↗</a>'
        : '';

      var _cdate = escapeHtml(cardDate(ev.date_str, ev.start_date));
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
          '<p class="event-meta">' + (_cdate ? '<span class="em-date">' + _cdate + '</span>' : '') + ((_cdate && _cloc) ? ' \\u00b7 ' : '') + (_cloc || '') + '</p>' +
          '<div class="ops-chips">' +
            starButtonHtml(st.interested) +
            '<button class="ops-chip urgent' + (st.urgent ? ' is-on' : '') + '" data-field="urgent" data-on="' + (st.urgent ? '1' : '0') + '" type="button">Urgent</button>' +
            // Archived → static label; otherwise a hover-only "hide" icon to archive it.
            (st.hidden
              ? '<span class="ops-archived-tag" title="Archived — open the event to bring it back">Archived</span>'
              : '<button class="ops-archive-x ops-hover" data-field="hidden" data-on="0" type="button" title="Archive — set this event aside" aria-label="Archive event">' + OPS_HIDE_ICON + '</button>') +
            decBadge + saBadge +
            '<span class="chat-count" data-chatkey="c' + escapeHtml(String(ev.num)) + '" style="display:none;" title="Discussion messages"></span>' +
          '</div>' +
        '</div>' +
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
          if (st[f] != null && String(st[f]).trim() !== '') rec[f] = st[f];
        }});
        if (st.interested && st.interested.length) rec.interested = st.interested;
        if (st.attendees && st.attendees.length) rec.attendees = st.attendees;
        if (st.speaker_topic) rec.speaker_topic = st.speaker_topic;
        if (st.decision) rec.decision = st.decision;
        rec.stage_tags = opsStages;
      }}
      rec.saved  = !!(st && st.saved);
      rec.hidden = !!(st && st.hidden);
      // Editing context for the modal's quick-actions / Edit Event button.
      rec._table = 'event_state'; rec._key = ev.num;
      rec.region = canonicalRegion(ev);
      card._modalRec = rec;
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
        '<label><span class="key">Focus areas</span><textarea name="focus_areas">' + v('focus_areas') + '</textarea></label>' +
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
      card.dataset.track    = ''; // manual_events doesn't carry a track column
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
      var mSaBadge = (shouldAttendKind(mev.attend_verdict) === 'human' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="sa-badge">★ Should Attend</span>' : '';
      card.dataset.contactFound = (hasEmailContact(mev) || _EMAIL_RE.test(String(mev.poc_email || ''))) ? '1' : '';
      // Contact (POC) badge is Angela's outreach cue — only she sees it on the card.
      var mContactBadge = (card.dataset.contactFound === '1' && window.isAngelaUser && window.isAngelaUser()) ? '<span class="contact-badge" title="An email contact was found for this event">✉ Contact</span>' : '';
      var mRecent = isRecentlyAdded(mev.created_at);
      card.dataset.recent = mRecent ? '1' : '';
      // The "Recently Added" triage badge is a support-team cue (Angela/Hurley);
      // dataset.recent still set so the Angela-only "Recently added" filter works.
      var mRecentBadge = (mRecent && isSupportPerson(getCollabName() || ''))
        ? '<span class="recent-badge" title="Added ' + escapeHtml(formatStamp(mev.created_at)) + '">Recently Added</span>'
        : '';
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
      var _mdate = escapeHtml(cardDate(mev.date_str, mev.start_date));
      var _mloc  = escapeHtml(shortLocation(mev));
      card.innerHTML =
        '<div class="ops-card-head">' +
          '<h3 class="event-name">' +
            (mev.url
              ? '<a class="event-name-link" href="' + escapeHtml(mev.url) + '" target="_blank" rel="noopener" aria-label="Open website for ' + escapeHtml(mev.name || '') + '">' + escapeHtml(mev.name || '') + '<span class="event-link-arrow" aria-hidden="true">↗</span></a>'
              : escapeHtml(mev.name || '')) +
          '</h3>' +
          '<p class="event-meta">' + (_mdate ? '<span class="em-date">' + _mdate + '</span>' : '') + ((_mdate && _mloc) ? ' \\u00b7 ' : '') + (_mloc || '') + '</p>' +
          '<div class="ops-chips">' +
            starButtonHtml(mev.interested) +
            '<button class="ops-chip urgent' + (mev.urgent ? ' is-on' : '') + '" data-field="urgent" data-on="' + (mev.urgent ? '1' : '0') + '" type="button">Urgent</button>' +
            // Archived → static label; otherwise a hover-only "hide" icon to archive it.
            (mev.hidden
              ? '<span class="ops-archived-tag" title="Archived — open the event to bring it back">Archived</span>'
              : '<button class="ops-archive-x ops-hover" data-field="hidden" data-on="0" type="button" title="Archive — set this event aside" aria-label="Archive event">' + OPS_HIDE_ICON + '</button>') +
            mDecBadge + mSaBadge + mRecentBadge +
            '<span class="chat-count" data-chatkey="m' + escapeHtml(String(mev.id)) + '" style="display:none;" title="Discussion messages"></span>' +
          '</div>' +
        '</div>' +
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

      if (mev.hidden) card.classList.add('is-hidden');
      if (mev.saved)  card.classList.add('is-saved');
      if (meInInterested(mev.interested)) card.classList.add('is-mine');   // I starred it → blue outline
      if (mev.urgent) card.classList.add('is-urgent');
      // Star = "I'm interested" (per-signed-in-person), not a shared bookmark.
      var _manStar = card.querySelector('.saved-star');
      if (_manStar) _manStar.addEventListener('click', function () {{
        _manStar.setAttribute('aria-busy', 'true');
        toggleMyInterest('manual', mev.id, mev.interested);
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
            else if (field === 'hidden') {{ card.classList.toggle('is-hidden', nextOn); regroupOpsByMonth(); applyFilters(); }}
            flashOk();
          }});
        }});
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
        sb.from('manual_events').delete().eq('id', id).then(function (resp) {{
          delBtn.disabled = false; delBtn.textContent = 'Delete event';
          if (resp.error) {{ status('Delete failed: ' + resp.error.message, 'error'); return; }}
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
        toggleMyInterest('catalog', num, (card._modalRec && card._modalRec.interested) || []);
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
            }} else if (field === 'hidden') {{
              card.classList.toggle('is-hidden', nextOn);
              // Move the card into / out of the collapsible "Hidden" section.
              regroupOpsByMonth();
              applyFilters();
            }}
            flashOk();
          }});
        }});
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
            if (f === 'track')             card.dataset.track    = sel.value || '';
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
      // Track (static — values defined in the schema CHECK constraint)
      var trk = document.querySelector('#filter-track .filter-dd-menu');
      if (trk && trk.dataset.built !== '1') {{
        [['Sponsor','track-sponsor'], ['Earned','track-earned'], ['Both','track-both'], ['Unknown','track-unknown']].forEach(function (pair) {{
          trk.appendChild(_makeExtraChip(pair[0], pair[0], pair[1]));
        }});
        var clrT = document.createElement('button');
        clrT.type = 'button'; clrT.className = 'extra-clear'; clrT.textContent = 'Clear';
        clrT.addEventListener('click', function () {{
          trk.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
          applyFilters();
        }});
        trk.appendChild(clrT);
        trk.dataset.built = '1';
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
      ['ops-f-submitted', 'ops-f-recent', 'ops-f-contact'].forEach(function (id) {{ var e = document.getElementById(id); if (e && e.checked) n++; }});
      ['filter-price', 'filter-priority', 'filter-track', 'filter-speaker'].forEach(function (id) {{
        var box = document.getElementById(id);
        if (box && box.querySelector('.filter-dd-btn.has-active')) n++;
      }});
      return n;
    }}
    function updateFilterToggle() {{
      var $ft = document.getElementById('ops-filter-toggle');
      if (!$ft) return;
      var box = $ft.closest('.ops-filters');
      var collapsed = !!(box && box.classList.contains('collapsed'));
      var n = countActiveOpsFilters();
      $ft.innerHTML = 'Filters' + (n ? ' <span class="ft-active">· ' + n + ' active</span>' : '') +
        ' <span class="ft-caret" aria-hidden="true">' + (collapsed ? '▾' : '▴') + '</span>';
    }}
    function wireFilterToggle() {{
      var $ft = document.getElementById('ops-filter-toggle');
      if (!$ft || $ft.dataset.wired) return;
      $ft.dataset.wired = '1';
      $ft.addEventListener('click', function () {{
        var box = $ft.closest('.ops-filters');
        if (!box) return;
        var collapsed = box.classList.toggle('collapsed');
        $ft.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        updateFilterToggle();
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
        $myTab.textContent = _teamView ? 'Team Lineup' : 'My Lineup';
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
      // The whole extra-filters box (Filters toggle + hidden dropdowns) is now
      // Angela-only — the search moved up into the top row for everyone, so this
      // box holds nothing but Angela's power filters. Hide it entirely for others.
      var box = document.querySelector('.ops-filters');
      if (box) {{
        box.style.display = show ? '' : 'none';
        if (!show) box.classList.add('collapsed');   // keep collapsed for when Angela returns
      }}
      var $ft = document.getElementById('ops-filter-toggle');
      if ($ft) {{ $ft.style.display = ''; if (!show) $ft.setAttribute('aria-expanded', 'false'); }}
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
    // "Hidden" group (1), then "Archive · past events" (2) at the very bottom.
    function opsCardTier(card) {{
      if (card.classList.contains('is-hidden')) return 1;
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
        var key = tier === 1 ? 'hidden' : (tier === 2 ? 'archive' : (card.dataset.month || 'tbd'));
        var label = tier === 1 ? 'Archived' : (tier === 2 ? 'Past events' : (card.dataset.monthLabel || 'Date TBD'));
        if (key !== curKey) {{
          curKey = key;
          order.push({{ key: key, label: label }});
          frag.appendChild(buildOpsMonthHeader(key, label));
        }}
        frag.appendChild(card);
      }});
      $opsGrid.appendChild(frag);
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
      var $contact = document.getElementById('ops-f-contact');
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
      var fSaved   = !!($saved && $saved.checked);
      var fUrgent  = !!($urgent && $urgent.checked);
      var fSubmitted = !!($submitted && $submitted.checked);
      var fMeet    = !!($meet && $meet.checked);
      var fContact = !!($contact && $contact.checked);
      // Ticket price + Fits are now MULTI-select bubble dropdowns — OR the chips.
      var activePrices = Array.prototype.map.call(document.querySelectorAll('#filter-price .extra-chip.is-on'), function (b) {{ return b.dataset.value; }});
      var activeFits   = Array.prototype.map.call(document.querySelectorAll('#filter-fits .extra-chip.is-on'), function (b) {{ return b.dataset.value; }});
      var showPast   = !!($past && $past.checked);
      var showHidden = !!($hidden && $hidden.checked);
      var fRecent    = !!($recent && $recent.checked);
      // Toggle has-active classes for chip styling
      [['ops-f-saved',$saved],['ops-f-urgent',$urgent],['ops-f-submitted',$submitted],['ops-f-meetings',$meet],['ops-f-contact',$contact],['ops-f-past',$past],['ops-f-hidden',$hidden],['ops-f-recent',$recent]].forEach(function (pair) {{
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
      var activeTracks = Array.prototype.map.call(
        document.querySelectorAll('#filter-track .extra-chip.is-on'),
        function (b) {{ return b.dataset.value; }}
      );
      var activeSpeakers = Array.prototype.map.call(
        document.querySelectorAll('#filter-speaker .extra-chip.is-on'),
        function (b) {{ return (b.dataset.value || '').toLowerCase(); }}
      );

      var shown = 0, dupSkipped = 0;
      var monthMatched = {{}};
      // Query the card set once per pass (it's also the count denominator) —
      // re-querying inside + again for the count walked the DOM twice/keystroke.
      var opsCards = $opsGrid.querySelectorAll('.ops-card');
      opsCards.forEach(function (card) {{
        // Hidden duplicate of an already-shown event — never render or count it.
        if (card.dataset.dupHidden === '1' && !_reviewDupes) {{ card.style.display = 'none'; dupSkipped++; return; }}
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
            _blob = card._searchBlob = ((card.textContent || '') + ' ' +
              [_r.poc_name, _r.poc_email, _r.contact_info, _r.speaker, _r.past_speakers,
               _r.about, _r.focus_areas, _r.typical_attendees].filter(Boolean).join(' ')).toLowerCase();
          }}
          if (_blob.indexOf(q) === -1) on = false;
        }}
        if (activeRegions.length && activeRegions.indexOf(card.dataset.region) === -1) on = false;
        if (activeMonths.length && activeMonths.indexOf(card.dataset.month) === -1) on = false;
        if (activeFits.length) {{
          var _intNames = (card.dataset.interestedNames || '').split('|').filter(Boolean);
          var _fitHit = activeFits.some(function (k) {{
            var pf = AB_PROFILE_BY_KEY[k]; if (!pf) return false;
            if (profileFits(pf, card.dataset.fitText, card.dataset.region)) return true;
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
        if (fContact && card.dataset.contactFound !== '1') on = false;
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
            var _isPend = (_ps.indexOf('Submitted') !== -1 || _ps.indexOf('Followed up') !== -1 || _ps.indexOf('Meeting held') !== -1) && _ps.indexOf('Booked') === -1;
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
          if (opsStatFilter === 'interested' && card.dataset.interested !== '1') on = false;
        }}
        if (activeStages.length > 0) {{
          var cardStages = (card.dataset.statusTags || '').split('|').filter(Boolean);
          var stageHit = activeStages.some(function (a) {{ return cardStages.indexOf(a) !== -1; }});
          if (!stageHit) on = false;
        }}
        if (activeStatuses.length   > 0 && activeStatuses.indexOf(card.dataset.status   || '') === -1) on = false;
        if (activePriorities.length > 0 && activePriorities.indexOf(card.dataset.priority || '') === -1) on = false;
        if (activeTracks.length     > 0 && activeTracks.indexOf(card.dataset.track     || '') === -1) on = false;
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
        var mkey = _tier === 1 ? 'hidden' : (_tier === 2 ? 'archive' : (card.dataset.month || 'tbd'));
        if (on) {{ monthMatched[mkey] = (monthMatched[mkey] || 0) + 1; shown++; }}
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
        if (cnt) cnt.textContent = n + (n === 1 ? ' event' : ' events') + (collapsed ? ' · hidden' : '');
      }});
      var $shown = document.getElementById('ops-shown');
      if ($shown) $shown.textContent = 'Showing ' + shown + ' of ' + (opsCards.length - dupSkipped);
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
      ['ops-search','ops-f-saved','ops-f-urgent','ops-f-submitted','ops-f-meetings','ops-f-contact','ops-f-past','ops-f-hidden','ops-f-recent'].forEach(function (id) {{
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
      ['ops-f-saved','ops-f-urgent','ops-f-submitted','ops-f-meetings','ops-f-past','ops-f-hidden','ops-f-recent','ops-f-contact'].forEach(function (id) {{
        var el = document.getElementById(id); if (el) el.checked = false;
      }});
      Array.prototype.forEach.call(
        document.querySelectorAll('#filter-pipeline .extra-chip.is-on, #filter-region .extra-chip.is-on, #filter-months .extra-chip.is-on, #filter-should .extra-chip.is-on, .status-filters .status-chip.is-on, #filter-price .extra-chip.is-on, #filter-fits .extra-chip.is-on, #filter-priority .extra-chip.is-on, #filter-track .extra-chip.is-on, #filter-speaker .extra-chip.is-on'),
        function (c) {{ c.classList.remove('is-on'); }}
      );
      opsStatFilter = '';
      var $stats = document.getElementById('ops-stats');
      if ($stats) Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (x) {{ x.classList.remove('is-activestat'); }});
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
      var saved = 0, urgent = 0, inPipeline = 0, booked = 0, attending = 0;
      var buyerRich = 0, interestedCount = 0, myInterested = 0;
      var me = (getCollabName() || 'Team').toLowerCase();
      var meFirst = me.split(/\\s+/)[0];   // attendees are stored as lowercase first names
      var _support = isSupportPerson(getCollabName() || '');   // Angela/Hurley -> team-wide
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
        var pend = (stages.indexOf('Submitted') !== -1 || stages.indexOf('Followed up') !== -1 || stages.indexOf('Meeting held') !== -1) && stages.indexOf('Booked') === -1;
        if (!pend) return false;
        return _support || speakerTokens(speaker || '').indexOf(meFirst) !== -1;
      }}
      (stateRows || []).forEach(function (r) {{
        if (r.saved)  saved++;
        var stages = stageTagsOf(r);
        if (_iPending(stages, r.speaker)) inPipeline++;
        if (stages.indexOf('Booked') !== -1) booked++;
        if (_iAttend(r.attendees)) attending++;
        if (r.interested && r.interested.length) interestedCount++;
        if (_isMine(r.interested)) myInterested++;
      }});
      // Urgent = an apply/CFP deadline closing soon (or a manually-flagged
      // urgent event) — NOT merely an upcoming event. Counted per event.
      (evs || []).forEach(function (ev) {{
        if (((ev.audience_type || '').toLowerCase()).indexOf('buyer') !== -1) buyerRich++;
        var st = stByNum[ev.num] || {{}};
        if (!isPastEvent(ev) && (st.urgent || isDeadlineUrgent(ev.deadline))) urgent++;
      }});
      // Manual events carry their own stage tags + deadlines — fold them in.
      (manualRows || []).forEach(function (m) {{
        var stages = stageTagsOf(m);
        if (_iPending(stages, m.speaker)) inPipeline++;
        if (stages.indexOf('Booked') !== -1) booked++;
        if (_iAttend(m.attendees)) attending++;
        if (((m.audience_type || '').toLowerCase()).indexOf('buyer') !== -1) buyerRich++;
        if (m.interested && m.interested.length) interestedCount++;
        if (_isMine(m.interested)) myInterested++;
        if (!isPastEvent(m) && isDeadlineUrgent(m.deadline)) urgent++;
      }});
      // Each tile is a one-click filter (data-stat). 'all' clears everything.
      function tile(key, num, label, cls) {{
        var sel = opsStatFilter === key;
        return '<button type="button" class="ops-stat' + (cls ? ' ' + cls : '') + (sel ? ' is-activestat' : '') +
          '" data-stat="' + key + '" aria-pressed="' + (sel ? 'true' : 'false') + '"><span class="num">' + num +
          '</span><span class="lbl">' + label + '</span></button>';
      }}
      $stats.innerHTML =
        tile('all', total, 'Upcoming events', '') +
        tile('myinterested', myInterested, 'My Interests', 'saved') +
        tile('pipeline', inPipeline, 'Pending', '') +
        tile('booked', booked, 'Booked', '') +
        tile('interested', interestedCount, 'Team Interests', '') +
        tile('attending', attending, _support ? 'Team Attending' : 'Attending', '');
      $stats.removeAttribute('hidden');
      Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (t) {{
        t.addEventListener('click', function () {{
          var k = t.dataset.stat;
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
            if (!_hasUpcoming) {{ goGrid = true; opsCollapsedMonths.archive = false; }}
          }}
          if (goGrid) setView('grid');
          applyFilters();
          // Reflect the active tile without a full re-render.
          Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (x) {{
            x.classList.toggle('is-activestat', x.dataset.stat === opsStatFilter);
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
    function opsItem(kind, base, st) {{
      var stages = stageTagsOf(st || base);
      var interested = (st && st.interested) || base.interested || [];
      var meta = opsMonthMeta(base.start_date || (st && st.start_date), base.date_str);
      var blob = [base.name, base.about, base.focus_areas, base.typical_attendees,
                  base.location, base.region, base.city, base.country, base.type,
                  base.notes, base.past_speakers].join(' ');
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
        deadline: (st && st.deadline) || base.deadline || '',
        queue_dismissed: !!((st && st.queue_dismissed) || base.queue_dismissed),
        past: isPastEvent(base),
        hidden: !!(st && st.hidden),
        sort: meta.sort,
        startObj: base,
        start_date: base.start_date || (st && st.start_date) || '',
        end_date: base.end_date || (st && st.end_date) || base.start_date || '',
        attendees: ((st && st.attendees) || base.attendees || []).slice ? ((st && st.attendees) || base.attendees || []).slice() : [],
        speaker_topic: (st && st.speaker_topic) || base.speaker_topic || '',
        briefing_json: (st && st.briefing_json) || base.briefing_json || null,
        briefing_generated_at: (st && st.briefing_generated_at) || base.briefing_generated_at || null,
        createdBy: abFold(base.created_by || ''),
        text: abFold(blob)
      }};
    }}

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
    function renderQueue() {{
      var host = document.getElementById('ops-queue');
      if (!host) return;
      var order = window.opsStageOrder || ['Submitted', 'Followed up', 'Meeting held', 'Booked', 'Attending'];
      // Queue = events still needing an application. Count only interested
      // people NOT already booked/attending (window.visibleInterested).
      // queue_dismissed = Angela said "not relevant" (the × next to Mark
      // applied) — keeps it off the queue without touching who's interested.
      var items = opsAllItems().filter(function (it) {{ return window.visibleInterested(it.interested, it.speaker, it.attendees).length && !it.past && !it.queue_dismissed; }});

      function deadlineHtml(it) {{
        if (_isJunkVal(it.deadline) || isDeadlinePast(it.deadline)) return '';
        var soon = isDeadlineSoon(it.deadline);
        return '<span class="q-deadline' + (soon ? ' soon' : '') + '">&#9203; ' + escapeHtml(it.deadline) + '</span>';
      }}
      function rowHtml(it, actions) {{
        var ints = window.visibleInterested(it.interested, it.speaker, it.attendees).map(function (n) {{ return '<span class="q-int-chip">' + escapeHtml(n) + '</span>'; }}).join('');
        var dec = it.decision === 'go' ? '<span class="decision-badge go">&#10003; Go</span>' : '';
        var loc = [it.location].filter(Boolean).join(' &middot; ');
        return '<div class="queue-row">' +
            '<div class="queue-main">' +
              '<button class="queue-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
              '<button type="button" class="ops-details-btn" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">Details &rarr;</button>' +
              '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' &middot; ' + loc : '') + '</p>' +
              '<div class="queue-chips">' + ints + qStagePills(it.stages) + dec + deadlineHtml(it) + '</div>' +
            '</div>' +
            '<div class="queue-actions">' + actions(it) + '</div>' +
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
          if (c.dataset.dupHidden === '1' || c.classList.contains('is-hidden')) return;
          var r = c._modalRec; if (!r) return;
          var atts = (c.dataset.attendeeNames || '').split('|').filter(Boolean);
          var isAtt = support ? (atts.length > 0) : (atts.indexOf(meFold) !== -1);
          var stages = (c.dataset.statusTags || '').split('|');
          var isSpk = stages.indexOf('Booked') !== -1 && (support || speakerTokens(c.dataset.speaker || r.speaker || '').indexOf(meFold) !== -1);
          if (!isAtt && !isSpk) return;
          var _pastFlag = c.dataset.past === '1';
          var _attDisp = atts.map(function (a) {{ return a ? a.charAt(0).toUpperCase() + a.slice(1) : ''; }}).filter(Boolean);
          var item = {{
            kind: (r._table === 'manual_events') ? 'manual' : 'catalog',
            key: r._key, name: r.name || 'Event', date_str: r.date_str || '',
            region: r.region || '', location: r.location || '', speaker: r.speaker || '',
            attendees: _attDisp, stages: stages,
            sort: parseInt(c.dataset.sort || '99999999', 10),
            _myRole: isSpk ? 'Speaking' : 'Attending',
            _past: _pastFlag, briefReady: c.dataset.briefReady === '1'
          }};
          (_pastFlag ? past : upcoming).push(item);
        }});
        upcoming.sort(function (a, b) {{ return a.sort - b.sort; }});   // soonest first
        past.sort(function (a, b) {{ return b.sort - a.sort; }});       // most recent first
      }}
      return {{ me: me, support: support, named: named, upcoming: upcoming, past: past }};
    }}

    // ── "In the last week" + "Suggested for you" (My Events) ─────────
    // Per-person local read/dismiss state — checking an item off, or clicking
    // into it, takes it down (Slack-style). Nothing is written to the DB.
    function _wnStoreKey() {{ return 'ab.whatsnew.' + (getCollabName() || '').toLowerCase(); }}
    function _wnState() {{ try {{ return JSON.parse(localStorage.getItem(_wnStoreKey()) || '{{}}'); }} catch (e) {{ return {{}}; }} }}
    function _wnSave(s) {{ try {{ localStorage.setItem(_wnStoreKey(), JSON.stringify(s)); }} catch (e) {{}} }}
    function _wnDismiss(item) {{
      var s = _wnState();
      if (item.chatKey) {{ s.chatSeen = s.chatSeen || {{}}; s.chatSeen[item.chatKey] = ((_chatMeta[item.chatKey] || {{}}).latest) || new Date().toISOString(); }}
      else {{ s.dismissed = s.dismissed || {{}}; s.dismissed[item.id] = 1; }}
      _wnSave(s);
    }}
    function _whatsNewItems() {{
      var me = (getCollabName() || '').trim().toLowerCase().split(/\\s+/)[0];
      var st = _wnState(), dis = st.dismissed || {{}}, seen = st.chatSeen || {{}};
      var cutoff = new Date(Date.now() - 7 * 86400000).toISOString();
      var byNum = {{}}, byMid = {{}};
      (_lastEvs || []).forEach(function (e) {{ byNum[e.num] = e; }});
      (_lastManual || []).forEach(function (m) {{ byMid[m.id] = m; }});
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
        items.push({{ id: id, ts: r.updated_at, kind: 'catalog', key: ev.num,
          label: whoF + ' marked ' + (ev.name || 'an event') + ' as ' + stg.map(function (s) {{ return s.toLowerCase(); }}).join(' &amp; ') }});
      }});
      // Newly added manual events — a teammate adding one by hand, never the
      // automated Dust ingest (dust@arcticblue.ai -> "Dust"), which finds and
      // adds events on its own and isn't news to anyone.
      (_lastManual || []).forEach(function (m) {{
        if (!m.created_at || m.created_at < cutoff) return;
        var whoF = firstNameFromEmail(m.created_by || '') || '';
        if (!whoF || whoF.toLowerCase() === me || whoF.toLowerCase() === 'dust') return;
        var id = 'a:m' + m.id; if (dis[id]) return;
        items.push({{ id: id, ts: m.created_at, kind: 'manual', key: m.id,
          label: whoF + ' added ' + (m.name || 'an event') }});
      }});
      // New comments since you last opened that event's chat (others' only).
      Object.keys(_chatMeta || {{}}).forEach(function (k) {{
        var meta = _chatMeta[k]; var last = seen[k] || '';
        var fresh = (meta.msgs || []).filter(function (x) {{ return x.at > last && String(x.author || '').toLowerCase().split(/\\s+/)[0] !== me; }});
        if (!fresh.length) return;
        var kind = k.charAt(0) === 'm' ? 'manual' : 'catalog'; var key = k.slice(1);
        var rec = kind === 'manual' ? byMid[key] : byNum[key]; if (!rec) return;
        items.push({{ id: 'c:' + k, ts: meta.latest, kind: kind, key: key, chatKey: k,
          label: fresh.length + ' new comment' + (fresh.length > 1 ? 's' : '') + ' on ' + (rec.name || 'an event') }});
      }});
      items.sort(function (a, b) {{ return a.ts < b.ts ? 1 : -1; }});
      return items.slice(0, 8);
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
        if (!_inPlanWindow(it.sort)) return;                 // outside the 2–4 month planning window
        if (skips[_sugSkipId(it.kind, it.key)]) return;      // you decided "not for me"
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
        // A 'stage' persona is there to SPEAK, so a topic-less pick — in-geo and
        // buyer-rich but matching none of their themes — isn't a fit (this was
        // Joe, an HR speaker, getting London financial-services events).
        if (P && mode === 'stage' && hits === 0) return;
        if (s >= (P ? 5 : 4)) scored.push({{ it: it, s: s, why: why }});
      }});
      scored.sort(function (a, b) {{ return b.s - a.s || a.it.sort - b.it.sort; }});
      return scored;   // callers slice to their own depth (My Events widget vs. the full Plan Ahead page)
    }}
    var _wnLast = [];
    function renderMyEvents() {{
      var host = document.getElementById('ops-myevents');
      if (!host) return;
      var b = myEventsBuckets();
      if (!b.named) {{
        host.innerHTML = '<p class="queue-intro myev-intro"><strong>My Events.</strong> Set your name (hit &ldquo;change&rdquo; up top) to see the events you&#39;re booked to speak at or attending.</p>';
        return;
      }}
      function rowHtml(it) {{
        var loc = [it.location].filter(Boolean).join(' &middot; ');
        var chips;
        if (b.support) {{
          // Team Lineup: show each person with their OWN role — the speaker with
          // their speaking stage, and each attendee as Attending. (Not one role
          // for the whole event: Thor can be Submitted-to-speak while Jerome is
          // the one Attending.)
          var SPK = ['Booked', 'Meeting held', 'Followed up', 'Submitted'];
          var spkStage = null;
          for (var si = 0; si < SPK.length; si++) {{ if ((it.stages || []).indexOf(SPK[si]) !== -1) {{ spkStage = SPK[si]; break; }} }}
          var spkFirst = abFold(it.speaker || '').split(/\\s+/)[0];
          var parts = [];
          if (it.speaker) {{
            parts.push('<span class="q-role-chip"><span class="q-int-chip">' + escapeHtml(it.speaker) + '</span>' +
              (spkStage ? '<span class="q-stage-pill" style="' + stageStyle(spkStage) + '">' + spkStage + '</span>' : '') + '</span>');
          }}
          (it.attendees || []).forEach(function (a) {{
            if (spkFirst && abFold(a).split(/\\s+/)[0] === spkFirst) return;   // don't list the speaker twice
            parts.push('<span class="q-role-chip"><span class="q-int-chip">' + escapeHtml(a) + '</span><span class="q-stage-pill" style="' + stageStyle('Attending') + '">Attending</span></span>');
          }});
          chips = parts.join('');
        }} else {{
          chips = it._myRole ? '<span class="q-stage-pill" style="' + stageStyle(it._myRole === 'Speaking' ? 'Booked' : 'Attending') + '">' + it._myRole + '</span>' : '';
        }}
        // The Day-Of brief now lives here (no separate tab) — on upcoming rows.
        var brief = it._past ? '' :
          (it.briefReady ? '<span class="dayof-ready">&#10003; brief ready</span>' : '') +
          '<button type="button" class="q-btn primary" data-brief-kind="' + it.kind + '" data-brief-key="' + escapeHtml(String(it.key)) + '">Open brief &rarr;</button>';
        return '<div class="queue-row"><div class="queue-main">' +
            '<button class="queue-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
            '<button type="button" class="ops-details-btn" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">Details &rarr;</button>' +
            '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' &middot; ' + loc : '') + '</p>' +
            '<div class="queue-chips">' + chips + '</div>' +
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
      // "In the last week" — teammates' updates + new comments; check one off
      // (or click into it) and it comes down, like Slack read-state.
      _wnLast = _whatsNewItems();
      var wnHtml = _wnLast.length
        ? '<div class="queue-section wn-section"><div class="queue-sec-head"><span class="queue-sec-title">In the last week</span><span class="queue-sec-count">' + _wnLast.length + '</span></div>' +
          _wnLast.map(function (w, i) {{
            return '<div class="queue-row wn-row"><div class="queue-main">' +
              '<button type="button" class="queue-name wn-open" data-wn-open="' + i + '">' + escapeHtml(w.label) + '</button>' +
            '</div><div class="queue-actions"><button type="button" class="q-btn wn-check" data-wn-check="' + i + '" title="Mark as seen — takes this off the list">&#10003;</button></div></div>';
          }}).join('') + '</div>'
        : '';
      // Bottom: only-the-best picks for whoever is signed in.
      var _sug = _suggestionsFor().slice(0, 10);
      var _sugTitle = ((window.AB_PERSONAS || {{}})[(b.me || '').trim().toLowerCase().split(/\\s+/)[0]]) ? 'Suggested for you' : 'Top suggestions for the team';
      var sugHtml = _sug.length
        ? '<div class="queue-section sug-section"><div class="queue-sec-head"><span class="queue-sec-title">' + _sugTitle + '</span><span class="queue-sec-count">' + _sug.length + '</span></div>' +
          _sug.map(function (x) {{
            var it = x.it;
            var loc = [it.location].filter(Boolean).join(' \\u00b7 ');
            return '<div class="queue-row sug-row"><div class="queue-main">' +
              '<button class="queue-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
              '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' \\u00b7 ' + loc : '') + '</p>' +
            '</div></div>';
          }}).join('') + '</div>'
        : '';
      host.innerHTML = intro + wnHtml +
        section(upTitle, b.upcoming, 'Nothing upcoming yet.') +
        (b.past.length ? section('Past events', b.past, '', true, !_myEventsPastOpen) : '') +
        sugHtml;
      host.querySelectorAll('[data-ref-kind]').forEach(function (el) {{
        el.addEventListener('click', function () {{ opsOpenRef(el.getAttribute('data-ref-kind'), el.getAttribute('data-ref-key')); }});
      }});
      host.querySelectorAll('[data-wn-open]').forEach(function (el) {{
        el.addEventListener('click', function () {{
          var w = _wnLast[parseInt(el.getAttribute('data-wn-open'), 10)];
          if (!w) return;
          _wnDismiss(w);
          opsOpenRef(w.kind, String(w.key));
          renderMyEvents();
        }});
      }});
      host.querySelectorAll('[data-wn-check]').forEach(function (el) {{
        el.addEventListener('click', function () {{
          var w = _wnLast[parseInt(el.getAttribute('data-wn-check'), 10)];
          if (!w) return;
          _wnDismiss(w);
          renderMyEvents();
        }});
      }});
      host.querySelectorAll('[data-brief-kind]').forEach(function (el) {{
        el.addEventListener('click', function () {{ openBriefDrawer(el.getAttribute('data-brief-kind'), el.getAttribute('data-brief-key')); }});
      }});
      var _pastHead = host.querySelector('.queue-section.collapsible .queue-sec-head');
      if (_pastHead) {{
        var _togglePast = function () {{
          var sec = _pastHead.closest('.queue-section');
          _myEventsPastOpen = !sec.classList.toggle('collapsed');
        }};
        _pastHead.addEventListener('click', _togglePast);
        _pastHead.addEventListener('keydown', function (e) {{ if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); _togglePast(); }} }});
      }}
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
    function _tripClusters() {{
      var meFirst = abFold(getCollabName() || '').split(/\\s+/)[0];
      if (!meFirst) return [];
      var BADt = /complian|regulat|regtech|gdpr|\\baudit/i;
      var skips = _sugSkips();
      var NEAR_KM = 200, DAY_MS = 86400000, GAP_DAYS = 3;
      var all = opsAllItems();
      function role(it) {{
        if ((it.attendees || []).some(function (a) {{ return abFold(a).split(/\\s+/)[0] === meFirst; }})) return 'attending';
        if (it.stages.indexOf('Booked') !== -1 && abFold(it.speaker || '').split(/\\s+/)[0] === meFirst) return 'speaking at';
        if ((it.interested || []).some(function (n) {{ return abFold(n).split(/\\s+/)[0] === meFirst; }})) return 'interested in';
        return null;
      }}
      var anchors = [];
      all.forEach(function (it) {{
        if (it.past || it.hidden) return;
        var r = role(it); if (!r) return;
        var g = geoOf(it); if (!g) return;
        if (!it.sort || it.sort >= 99999999) return;
        anchors.push({{ it: it, role: r, geo: g, startD: _sortToDate(it.sort), endD: _sortToDate(_endSortOf(it)) }});
      }});
      if (!anchors.length) return [];
      anchors.sort(function (a, b) {{ return a.it.sort - b.it.sort; }});
      var clusters = [], usedKeys = {{}};
      anchors.forEach(function (anchor) {{
        if (!anchor.startD || !anchor.endD) return;
        var near = [], seenName = {{}};
        all.forEach(function (it) {{
          if (it === anchor.it) return;
          if (it.past || it.hidden || it.queue_dismissed) return;
          if (it.stages.length) return;                       // already in the pipeline
          if (BADt.test(it.name)) return;
          if (role(it)) return;                               // already yours
          if (skips[_sugSkipId(it.kind, it.key)]) return;
          if (usedKeys[it.kind + ':' + it.key]) return;       // don't repeat across anchors
          var nm = abFold(it.name); if (seenName[nm]) return;  // collapse duplicate events
          var g = geoOf(it); if (!g) return;
          var km = _haversineKm(anchor.geo, g);
          if (km > NEAR_KM) return;
          var cs = _sortToDate(it.sort), ce = _sortToDate(_endSortOf(it));
          if (!cs || !ce) return;
          var gap = Math.max(0, Math.ceil((cs - anchor.endD) / DAY_MS), Math.ceil((anchor.startD - ce) / DAY_MS));
          if (gap > GAP_DAYS) return;
          seenName[nm] = 1;
          near.push({{ it: it, gap: gap, km: km }});
        }});
        if (near.length) {{
          near.sort(function (a, b) {{ return a.it.sort - b.it.sort; }});
          near.forEach(function (n) {{ usedKeys[n.it.kind + ':' + n.it.key] = 1; }});
          clusters.push({{ anchor: anchor.it, role: anchor.role, near: near }});
        }}
      }});
      return clusters;
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
      var intro = '<p class="queue-intro myev-intro"><strong>Plan Ahead:</strong> ' +
        (personalized ? 'Events 2&ndash;4 months out that fit your focus. ' : 'Events 2&ndash;4 months out worth a look. ') +
        'Decide which to go to &mdash; flag the ones you want (Angela registers you) and skip the rest.</p>';
      // Trip clusters first — "while you're already in X, here's what's nearby".
      var clusters = _tripClusters();
      var clusteredKeys = {{}};
      var tripHtml = '';
      if (clusters.length) {{
        tripHtml += '<div class="queue-sec-head"><span class="queue-sec-title">&#129517; Batch your trips</span><span class="queue-sec-count">' + clusters.length + '</span></div>' +
          '<p class="queue-meta" style="margin:-4px 0 14px;">You&#39;re already going to these &mdash; here&#39;s what else is on within a few days, in the same or a nearby city.</p>';
        clusters.forEach(function (cl) {{
          var aLoc = cl.anchor.location || cl.anchor.city || '';
          tripHtml += '<div class="queue-section trip-cluster"><p class="trip-anchor">You&#39;re ' + escapeHtml(cl.role) +
            ' <button class="trip-anchor-name" data-ref-kind="' + cl.anchor.kind + '" data-ref-key="' + escapeHtml(String(cl.anchor.key)) + '">' + escapeHtml(cl.anchor.name) + '</button>' +
            '<span class="trip-anchor-meta">' + escapeHtml(cl.anchor.date_str || '') + (aLoc ? ' \\u00b7 ' + escapeHtml(aLoc) : '') + '</span></p>';
          cl.near.forEach(function (n) {{
            var it = n.it; clusteredKeys[it.kind + ':' + it.key] = 1;
            var loc = it.location || '';
            var prox = (n.gap === 0 ? 'overlaps' : ('~' + n.gap + ' day' + (n.gap === 1 ? '' : 's') + ' apart')) +
              ' \\u00b7 ' + (n.km < 25 ? 'same city' : ('~' + Math.round(n.km) + ' km away'));
            tripHtml += '<div class="queue-row sug-row"><div class="queue-main">' +
                '<button class="queue-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
                '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' \\u00b7 ' + loc : '') + '</p>' +
                '<p class="trip-prox">' + prox + '</p>' +
              '</div><div class="queue-actions sug-actions">' +
                '<button type="button" class="q-btn primary" data-pa-flag="1" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '">+ I&#39;m interested</button>' +
                '<button type="button" class="q-btn sug-skip" data-pa-skip="1" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '" title="Take this off your list">Not for me</button>' +
              '</div></div>';
          }});
          tripHtml += '</div>';
        }});
      }}

      // 2–4 month suggestions (excluding anything already shown in a trip cluster).
      var sug = _suggestionsFor().filter(function (x) {{ return !clusteredKeys[x.it.kind + ':' + x.it.key]; }});
      if (!sug.length && !tripHtml) {{
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
      var html = intro + tripHtml;
      order.forEach(function (mkey) {{
        var g = groups[mkey];
        var list = g.items.slice().sort(function (a, b) {{ return a.it.sort - b.it.sort; }});
        html += '<div class="queue-section"><div class="queue-sec-head"><span class="queue-sec-title">' + escapeHtml(g.label) + '</span><span class="queue-sec-count">' + list.length + '</span></div>';
        list.forEach(function (x) {{
          var it = x.it;
          var loc = [it.location].filter(Boolean).join(' \\u00b7 ');
          html += '<div class="queue-row sug-row"><div class="queue-main">' +
              '<button class="queue-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
              '<p class="queue-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' \\u00b7 ' + loc : '') + '</p>' +
            '</div><div class="queue-actions sug-actions">' +
              '<button type="button" class="q-btn primary" data-pa-flag="1" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '">+ I&#39;m interested</button>' +
              '<button type="button" class="q-btn sug-skip" data-pa-skip="1" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '" title="Take this off your list">Not for me</button>' +
            '</div></div>';
        }});
        html += '</div>';
      }});
      host.innerHTML = html;
      host.querySelectorAll('[data-ref-kind]').forEach(function (el) {{
        el.addEventListener('click', function () {{ opsOpenRef(el.getAttribute('data-ref-kind'), el.getAttribute('data-ref-key')); }});
      }});
      host.querySelectorAll('[data-pa-flag]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          var kind = btn.getAttribute('data-k'), key = btn.getAttribute('data-key');
          var it = opsAllItems().filter(function (x) {{ return x.kind === kind && String(x.key) === key; }})[0];
          if (!it) return;
          btn.setAttribute('aria-busy', 'true');
          toggleMyInterest(kind, it.key, it.interested);
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
      {{ k: 'bio',        label: 'Short bio',       hint: 'a couple of sentences',      ph: 'Two or three sentences an organizer could drop straight into an agenda.' }},
      {{ k: 'topics',     label: 'Talks & topics',  hint: 'what you speak on',          ph: 'Talk titles, themes, signature angles — one per line.' }},
      {{ k: 'past_talks', label: 'Past talks',      hint: 'what & where you have spoken', ph: 'e.g. "AI adoption keynote — Web Summit Lisbon 2025". Helps us target similar events.' }},
      {{ k: 'notes',      label: 'Targeting notes', hint: 'events you want',            ph: 'Types of events you want to be at, specific event names, regions — anything on your mind.' }}
    ];
    // Speaking materials, organized by what an organizer actually asks for —
    // each is its own upload slot (files live under <person>/<slot>/ in the
    // profiles bucket). This is the point of the profile: a ready-to-send kit.
    var PROFILE_MATERIALS = [
      {{ k: 'headshot', label: 'Headshot',          hint: 'a professional photo organizers can use' }},
      {{ k: 'decks',    label: 'Slides & decks',    hint: 'your talk decks — PDF / PPTX / Keynote' }},
      {{ k: 'bios',     label: 'Bio & one-pagers',  hint: 'formal bio doc, speaker one-pager, leave-behinds' }},
      {{ k: 'other',    label: 'Other materials',   hint: 'press, testimonials, video links saved as a file — anything else' }}
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
    function _directoryCardHtml(key, row, filesId) {{
      var d = _profileDisplay(row, key);
      var role = _profileRole(key);
      var h = '<div class="profile-teammate"><div class="profile-tm-head">' +
        '<span class="profile-avatar">' + escapeHtml((d || '?').charAt(0).toUpperCase()) + '</span>' +
        '<span class="profile-tm-name">' + escapeHtml(d) + '</span>' +
        (role ? '<span class="profile-tm-role">' + escapeHtml(role) + '</span>' : '') + '</div>';
      if (row) {{
        PROFILE_FIELDS.forEach(function (f) {{
          if (!row[f.k]) return;
          h += '<div class="profile-tm-field"><div class="k">' + escapeHtml(f.label) + '</div><div class="v">' + escapeHtml(row[f.k]) + '</div></div>';
        }});
      }}
      h += '<div class="profile-tm-field"><div class="k">Materials</div><div class="profile-tm-files" id="' + filesId + '"><p class="profile-file-empty">Loading&hellip;</p></div></div>';
      return h + '</div>';
    }}
    // Read-only materials for a teammate — grouped by slot, download only.
    // Lists each material category (<person>/<cat>/…) and appends the slots
    // that have files; clicks are handled by delegation so async appends work.
    function _loadTeammateFiles(personKey, containerId) {{
      var $c = document.getElementById(containerId);
      if (!$c) return;
      $c.innerHTML = '';
      if (!$c.dataset.dlWired) {{
        $c.dataset.dlWired = '1';
        $c.addEventListener('click', function (e) {{
          var a = e.target && e.target.closest ? e.target.closest('[data-tmfile]') : null;
          if (!a) return;
          e.preventDefault();
          sb.storage.from('profiles').createSignedUrl(a.getAttribute('data-tmkey') + '/' + a.getAttribute('data-tmfile'), 120).then(function (r) {{
            if (r && r.data && r.data.signedUrl) window.open(r.data.signedUrl, '_blank'); else status('Could not open that file.', 'error');
          }});
        }});
      }}
      var pending = PROFILE_MATERIALS.length, anyShown = false;
      PROFILE_MATERIALS.forEach(function (m) {{
        sb.storage.from('profiles').list(personKey + '/' + m.k, {{ limit: 50 }}).then(function (resp) {{
          var items = ((resp && resp.data) || []).filter(function (f) {{ return f.name && f.name !== '.emptyFolderPlaceholder'; }});
          if (items.length) {{
            anyShown = true;
            var h = '<div class="tm-mat-group"><div class="tm-mat-label">' + escapeHtml(m.label) + '</div>' +
              items.map(function (f) {{
                var size = (f.metadata && f.metadata.size) ? _fmtBytes(f.metadata.size) : '';
                return '<div class="profile-file"><a class="profile-file-name" href="#" data-tmfile="' + escapeHtml(m.k + '/' + f.name) + '" data-tmkey="' + escapeHtml(personKey) + '">' + escapeHtml(f.name) + '</a>' +
                  (size ? '<span class="profile-file-size">' + size + '</span>' : '') + '</div>';
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
          '<p class="profile-section-sub">Upload the things you send organizers &mdash; kept together so anyone can grab your kit fast.</p>';
        PROFILE_MATERIALS.forEach(function (m) {{
          html += '<div class="profile-material"><div class="profile-material-head">' +
              '<span class="profile-material-label">' + escapeHtml(m.label) + '</span>' +
              '<span class="hint">' + escapeHtml(m.hint) + '</span></div>' +
            '<div class="profile-files" id="pf-files-' + m.k + '"><p class="profile-file-empty">Loading&hellip;</p></div>' +
            '<div class="profile-upload-row"><input type="file" id="pf-file-input-' + m.k + '" aria-label="Choose a file for ' + escapeHtml(m.label) + '">' +
              '<button type="button" class="q-btn" data-mat-upload="' + m.k + '">Upload</button></div>' +
          '</div>';
        }});
        // ── Written profile — optional, but helps targeting.
        html += '<div class="profile-section-head">About you <span class="profile-section-opt">optional</span></div>';
        PROFILE_FIELDS.forEach(function (f) {{
          var val = myRow ? (myRow[f.k] || '') : '';
          html += '<div class="profile-field"><label for="pf-' + f.k + '">' + escapeHtml(f.label) +
            ' <span class="hint">&middot; ' + escapeHtml(f.hint) + '</span></label>' +
            '<textarea id="pf-' + f.k + '" rows="3" placeholder="' + escapeHtml(f.ph) + '">' + escapeHtml(val) + '</textarea></div>';
        }});
        html += '<div class="profile-actions"><button type="button" class="q-btn primary" id="pf-save">Save write-ups</button>' +
          '<span class="profile-saved-note" id="pf-saved" hidden>&#10003; Saved</span></div>';
        html += '</div>';   // end .profile-card
      }}
      // The per-person directory — everyone's profile + materials, by person.
      var dirTitle = support ? 'Team profiles' : 'The rest of the team';
      var dirIntro = support
        ? 'Everyone&#39;s bio, topics, past talks, and materials &mdash; by person. Updates as each person edits their profile.'
        : 'Read-only &mdash; where each person has spoken, what they want to target, and their materials.';
      html += '<div class="queue-sec-head"' + (support ? '' : ' style="margin-top:8px;"') + '><span class="queue-sec-title">' + dirTitle + '</span><span class="queue-sec-count">' + dirKeys.length + '</span></div>' +
        '<p class="queue-meta" style="margin:-4px 0 14px;">' + dirIntro + '</p>';
      if (!dirKeys.length) {{
        html += '<div class="queue-empty">No one&#39;s added a profile yet &mdash; when someone fills in their bio, topics, or uploads a file, it shows up here by person.</div>';
      }} else {{
        dirKeys.forEach(function (k, i) {{ html += _directoryCardHtml(k, byKey[k] || null, 'tmfiles-' + i); }});
      }}
      html += '</div>';   // end .profile-wrap
      host.innerHTML = html;
      if (!support) {{
        var $save = document.getElementById('pf-save');
        if ($save) $save.addEventListener('click', function () {{ _saveMyProfile(meKey, meName); }});
        host.querySelectorAll('[data-mat-upload]').forEach(function (btn) {{
          btn.addEventListener('click', function () {{ _uploadProfileFile(meKey, btn.getAttribute('data-mat-upload')); }});
        }});
        PROFILE_MATERIALS.forEach(function (m) {{ _loadProfileFiles(meKey, m.k, dbMissing); }});
      }}
      dirKeys.forEach(function (k, i) {{ _loadTeammateFiles(k, 'tmfiles-' + i); }});
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
      }});
    }}
    // Files for one material slot (<meKey>/<cat>/…) — download + delete.
    function _loadProfileFiles(meKey, cat, setupPending) {{
      var $files = document.getElementById('pf-files-' + cat);
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
          return '<div class="profile-file"><a class="profile-file-name" href="#" data-file="' + escapeHtml(f.name) + '">' + escapeHtml(f.name) + '</a>' +
            (size ? '<span class="profile-file-size">' + size + '</span>' : '') +
            '<button type="button" class="profile-file-del" data-delfile="' + escapeHtml(f.name) + '" aria-label="Delete ' + escapeHtml(f.name) + '" title="Delete this file">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>' +
              '<span>Delete</span></button></div>';
        }}).join('');
        $files.querySelectorAll('[data-file]').forEach(function (a) {{
          a.addEventListener('click', function (e) {{
            e.preventDefault();
            sb.storage.from('profiles').createSignedUrl(prefix + '/' + a.getAttribute('data-file'), 120).then(function (r) {{
              if (r && r.data && r.data.signedUrl) window.open(r.data.signedUrl, '_blank');
              else status('Could not open that file.', 'error');
            }});
          }});
        }});
        $files.querySelectorAll('[data-delfile]').forEach(function (b) {{
          b.addEventListener('click', function () {{
            var name = b.getAttribute('data-delfile');
            if (!window.confirm('Delete "' + name + '"? This cannot be undone.')) return;
            sb.storage.from('profiles').remove([prefix + '/' + name]).then(function (r) {{
              if (r && r.error) {{ status('Delete failed: ' + r.error.message, 'error'); return; }}
              flashOk('File deleted'); _loadProfileFiles(meKey, cat, false);
            }});
          }});
        }});
      }});
    }}
    function _uploadProfileFile(meKey, cat) {{
      var $in = document.getElementById('pf-file-input-' + cat);
      if (!$in || !$in.files || !$in.files.length) {{ status('Pick a file first.', 'warn'); return; }}
      var file = $in.files[0];
      if (file.size > 25 * 1024 * 1024) {{ status('That file is over 25 MB \\u2014 please upload something smaller.', 'error'); return; }}
      var $up = document.querySelector('[data-mat-upload="' + cat + '"]');
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
      {{ key: 'Thor', label: 'Healthcare & tech (exec)', regions: [],
         kw: ['healthcare','healthtech','health tech','digital health','medtech','life sciences','pharma','ceo','chief ai officer','cio','cto','cso','coo','digital transformation','agentic','ai governance','new york','san francisco','washington','las vegas','miami','london','zurich','riyadh','dubai','abu dhabi'] }},
      {{ key: 'Verma', label: 'Regulated (board-level)', regions: [],
         kw: ['insurance','insurtech','finance','financial services','bank','banking','capital markets','payments','wealth','fintech','healthcare','board','chief risk','chief data','governance','regulated'] }},
      {{ key: 'Carlos', label: 'Americas (mid-market)', regions: ['US & Canada','Latin America'], locked: true,
         kw: ['mexico city','monterrey','santo domingo','san juan','sao paulo','bogota','buenos aires','lima','santiago','quito','financial services','insurance','fintech','healthcare','saas','retail','telco','media'] }},
      {{ key: 'Jim', label: 'Government (DC)', regions: [],
         kw: ['government','public sector','federal','defense','national security','govtech','civic','municipal','state and local','washington','washington dc','capitol','congress','white house','agency','gsa','dod','nist','fedramp','public policy'] }}
    ];
    var AB_PROFILE_BY_KEY = {{}};
    AB_PROFILES.forEach(function (p) {{ AB_PROFILE_BY_KEY[p.key] = p; }});
    // True if an event (canonical region + folded text blob) fits a profile.
    function profileFits(p, blob, region) {{
      if (!p) return false;
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
    var AB_TERRITORIES = AB_PROFILES.map(function (p) {{
      return {{ who: p.key, label: p.label, test: function (it) {{ return profileFits(p, it.text, it.region); }} }};
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
      html += '</div>';

      html += '<div class="planner-section"><div class="planner-sec-head"><span class="planner-sec-title">&#128506; Coverage gaps by territory</span><span class="planner-sec-sub">upcoming events with no speaker assigned</span></div>';
      var CAP = 12;
      AB_TERRITORIES.forEach(function (terr) {{
        var inTerr = items.filter(function (it) {{ return !it.past && !it.hidden && terr.test(it); }});
        if (!inTerr.length) return;
        var covered = inTerr.filter(function (it) {{ return it.speaker && it.speaker.trim(); }});
        var gaps = inTerr.filter(function (it) {{ return !(it.speaker && it.speaker.trim()); }});
        gaps.sort(function (a, b) {{ return a.sort - b.sort; }});
        html += '<div class="gap-owner"><div class="gap-owner-head">' +
            '<span class="gap-owner-name">' + escapeHtml(terr.who) + '</span>' +
            '<span class="gap-owner-stat">' + inTerr.length + ' events &middot; ' + covered.length + ' covered &middot; <b>' + gaps.length + ' open</b></span>' +
          '</div>';
        if (!gaps.length) {{
          html += '<p class="gap-none">&#10003; All ' + inTerr.length + ' covered &mdash; nothing open.</p>';
        }} else {{
          html += '<div class="gap-list">';
          gaps.slice(0, CAP).forEach(function (it) {{
            var loc = [it.location].filter(Boolean).join(' &middot; ');
            var flagged = it.interested.indexOf(terr.who) !== -1;
            html += '<div class="gap-row"><div>' +
                '<button class="gap-name" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">' + escapeHtml(it.name) + '</button>' +
                '<p class="gap-meta">' + escapeHtml(it.date_str || 'Date TBD') + (loc ? ' &middot; ' + loc : '') + '</p>' +
              '</div>' +
              '<div class="gap-actions">' +
                '<button class="q-btn" data-ref-kind="' + it.kind + '" data-ref-key="' + escapeHtml(String(it.key)) + '">Details &rarr;</button>' +
                (flagged
                  ? '<span class="q-int-chip">&#10003; Flagged for ' + escapeHtml(terr.who) + '</span>'
                  : '<button class="q-btn primary" data-flag="' + escapeHtml(terr.who) + '" data-k="' + it.kind + '" data-key="' + escapeHtml(String(it.key)) + '">+ Flag for ' + escapeHtml(terr.who) + '</button>') +
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
        var n = opsAllItems().filter(function (it) {{
          return window.visibleInterested(it.interested, it.speaker, it.attendees).length && !it.past && it.stages.indexOf('Booked') === -1;
        }}).length;
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
        for (var i = 1; i < g.length; i++) {{ g[i].dataset.dupHidden = '1'; g[i].classList.add('is-dupe'); if (!_reviewDupes) g[i].style.display = 'none'; hidden++; }}
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
        for (var i = 1; i < g.length; i++) {{
          if (g[i].dataset.dupHidden === '1') continue;
          if (_topicRelated(sigK, _topicSig(g[i]._modalRec || {{}}))) {{
            g[i].dataset.dupHidden = '1'; g[i].classList.add('is-dupe'); if (!_reviewDupes) g[i].style.display = 'none'; hidden++; merged++;
          }}
        }}
        // (Duplicates marked above; hidden unless "Review duplicates" is on.)
      }});
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
        _revBtn.hidden = (hidden === 0) || !(window.isAngelaUser && window.isAngelaUser());
        _revBtn.textContent = _reviewDupes
          ? '\\u2715 Done \\u00b7 hide duplicates again'
          : ('Review ' + hidden + ' possible duplicate' + (hidden === 1 ? '' : 's'));
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
        else if (currentView === 'planahead') renderPlanAhead();
        else if (currentView === 'queue') renderQueue();
        else if (currentView === 'planner') renderPlanner();
        updateViewBadges();
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
        '<label><span class="key">Why it fits</span>' +
          '<textarea name="why" placeholder="One line on why this is on the list"></textarea>' +
        '</label>' +
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
                (report.skipped ? ' (' + report.skipped + ' skipped — already had values).' : '.');
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

    var VIEW_NAMES = ['myevents', 'planahead', 'myprofile', 'grid', 'calendar', 'map', 'queue', 'planner', 'dayof'];
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
      var g = document.getElementById('ops-grid');
      var c = document.getElementById('ops-calendar');
      var m = document.getElementById('ops-map');
      var q = document.getElementById('ops-queue');
      var p = document.getElementById('ops-planner');
      var d = document.getElementById('ops-dayof');
      var me = document.getElementById('ops-myevents');
      var pa = document.getElementById('ops-planahead');
      var pr = document.getElementById('ops-myprofile');
      if (g) g.style.display = (name === 'grid') ? '' : 'none';
      var rh = document.getElementById('ops-results-header');
      if (rh) rh.style.display = (name === 'grid') ? '' : 'none';
      if (me) me.classList.toggle('show', name === 'myevents');
      if (pa) pa.classList.toggle('show', name === 'planahead');
      if (pr) pr.classList.toggle('show', name === 'myprofile');
      if (c) c.classList.toggle('show', name === 'calendar');
      if (m) m.classList.toggle('show', name === 'map');
      if (q) q.classList.toggle('show', name === 'queue');
      if (p) p.classList.toggle('show', name === 'planner');
      if (d) d.classList.toggle('show', name === 'dayof');
      if (name === 'myevents') renderMyEvents();
      if (name === 'planahead') renderPlanAhead();
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
    function openOpsMap() {{
      loadLeaflet().then(function () {{
        if (!_opsMap) {{
          _opsMap = L.map('ops-map-canvas', {{ worldCopyJump: true }})
            .setView([30, -20], 2);
          L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
          }}).addTo(_opsMap);
          _opsMapLayer = L.layerGroup().addTo(_opsMap);
          // Sidebar close button + clicking empty map dismisses the panel.
          var sbClose = document.getElementById('msb-close');
          if (sbClose) sbClose.addEventListener('click', closeMapSidebar);
          _opsMap.on('click', closeMapSidebar);
        }}
        renderOpsMap();
        // The container was display:none at init — force a size recalc.
        setTimeout(function () {{ _opsMap.invalidateSize(); }}, 50);
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
        if (card.classList.contains('is-hidden')) return;  // user-hidden — keep off the map
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
      // export) never double-books an event.
      var _dupSet = {{}};
      Array.prototype.forEach.call($opsGrid ? $opsGrid.querySelectorAll('.ops-card') : [], function (c) {{
        if (c.dataset.dupHidden === '1') {{
          _dupSet[String(c.dataset.manualId ? ('m' + c.dataset.manualId) : c.dataset.eventNum)] = 1;
        }}
      }});
      combined = combined.filter(function (ev) {{ return !_dupSet[String(ev.num)]; }});
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

    function openSearchPanel(email) {{
      var existing = document.getElementById('search-panel');
      if (existing) {{ existing.remove(); return; }}

      var qOpts = _currentQuarterOptions();
      // Default: first two quarters from today
      var qDefaults = qOpts.slice(0, 2);

      var panel = document.createElement('div');
      panel.id = 'search-panel';
      panel.className = 'add-event-card';
      panel.innerHTML =
        '<h3>Find events (AI search)</h3>' +
        '<p style="margin:0 0 12px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          'AI web search finds upcoming in-person events matching your criteria — buyer-rich audiences preferred. It first looks for next-year editions of events the team has attended, then fills in with your criteria. Added events are vetted and auto-enriched.' +
        '</p>' +
        '<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">' +
          '<label style="display:inline-flex;align-items:center;gap:8px;font-family:var(--ab-mono);font-size:0.7rem;letter-spacing:0.06em;text-transform:uppercase;color:var(--ab-fg-3);">' +
            'How many:' +
            '<input type="number" id="search-count" min="1" max="25" value="10" style="width:60px;padding:6px 8px;border:1px solid var(--ab-rule-strong);border-radius:6px;font-family:var(--ab-sans);font-size:0.9rem;">' +
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
        var criteria = {{ count: count, types: SEARCH_TYPE_OPTIONS.slice(), quarters: getQuarters(), regions: getRegions(), recurring: _recurring.slice(0, 30) }};
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
            meta.textContent = 'Found ' + (data.events || []).length + ' new events in ' + dur + 's' +
              (data.dupes_filtered ? ' (' + data.dupes_filtered + ' already-tracked filtered out)' : '') + '.';
            renderSearchResults(panel, data, email);
          }}).catch(function (err) {{
            runBtn.disabled = false; runBtn.textContent = 'Find more';
            meta.textContent = 'Network error: ' + err.message;
          }});
        }});
      }});
    }}

    function renderSearchResults(panel, data, email) {{
      var events = (data.events || []);
      var $r = panel.querySelector('#search-results');
      if (events.length === 0) {{
        $r.innerHTML = '<p class="alert">No events found for these criteria. Try widening the types or quarters.</p>';
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

      function insertOne(ev) {{
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
    function _askCardsHtml(cards) {{
      if (!cards || !cards.length) return '';
      return '<div class="ask-cards">' + cards.map(function (c, i) {{
        var meta = [c.date, c.location || c.region].filter(Boolean).map(escapeHtml).join(' \\u00b7 ');
        var tags = [];
        var _acPri = window.cardPriority ? window.cardPriority({{ priority: c.priority, audience_type: c.audience }}) : '';
        if (_acPri) tags.push('<span class="ac-tag pri-' + _acPri.toLowerCase() + '">' + escapeHtml(_acPri) + '</span>');
        if (c.stage) tags.push('<span class="ac-tag">' + escapeHtml(String(c.stage).split(',')[0].trim()) + '</span>');
        if (c.price) tags.push('<span class="ac-tag">' + escapeHtml(c.price) + '</span>');
        var idAttr = (c.num !== null && c.num !== undefined)
          ? ' data-evnum="' + escapeHtml(String(c.num)) + '"'
          : ' data-evname="' + escapeHtml(c.name || '') + '"';
        return '<button type="button" class="ask-card"' + idAttr + '>' +
          '<span class="rank">#' + (i + 1) + '</span>' +
          '<span class="ac-name">' + escapeHtml(c.name || 'Untitled event') + '</span>' +
          (meta ? '<span class="ac-meta">' + meta + '</span>' : '') +
          (tags.length ? '<span class="ac-tags">' + tags.join('') + '</span>' : '') +
        '</button>';
      }}).join('') + '</div>';
    }}
    // Render an AI reply: lead with the ranked event cards, then a short,
    // de-emphasised note for the reasoning (no big markdown blocks). When there
    // are no matching events (a factual question), fall back to the text.
    function _askAnswerHtml(answer, cards, mode) {{
      var txt = (answer || '').trim();
      var hasCards = cards && cards.length;
      // A LIST / ranking ("events" mode, or legacy replies with no mode) leads
      // with the ranked cards and demotes the prose to a small note. A
      // CONVERSATIONAL reply (a specific event, a how-to, or general chat) leads
      // with the prose like a normal chatbot, and any single event card sits
      // below it as a reference.
      if ((mode === 'events' || !mode) && hasCards) {{
        return _askCardsHtml(cards) +
          (txt ? '<div class="ask-note">' + _mdToHtml(txt) + '</div>' : '');
      }}
      var out = txt ? '<div class="ask-prose">' + _mdToHtml(txt) + '</div>' : '';
      if (hasCards) out += _askCardsHtml(cards);
      return out || _mdToHtml(txt);
    }}
    // Click a recommended card \\u2192 open that event\\u2019s detail modal.
    function _wireAskCards(container) {{
      container.querySelectorAll('.ask-card').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          var num = btn.getAttribute('data-evnum');
          if (num && typeof window.openEventByNum === 'function') {{ window.openEventByNum(num); return; }}
          var nm = (btn.getAttribute('data-evname') || '').trim().toLowerCase();
          if (!nm) return;
          var hit = Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-card'))
            .filter(function (c) {{ return c._modalRec && (c._modalRec.name || '').trim().toLowerCase() === nm; }})[0];
          if (hit && typeof window.openEventModal === 'function') window.openEventModal(hit._modalRec);
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
    var _STAGE_ORDER = ['Submitted', 'Followed up', 'Meeting held', 'Booked', 'Attending'];
    window.opsStageOrder = _STAGE_ORDER;
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
    // Delete bridge for the modal's Edit form. Manual events are hard-deleted;
    // catalog events (from the daily ingest) are persistently suppressed via a
    // '__deleted__' sentinel on their event_state row, so they don't reappear.
    window.opsDelete = function (table, key) {{
      if (table === 'manual_events') {{
        return sb.from('manual_events').delete().eq('id', key).then(function (resp) {{
          if (resp && resp.error) {{ status('Delete failed: ' + resp.error.message, 'error'); }}
          else {{ flashOk('Manual event deleted'); if (typeof loadKnownNames === 'function') loadKnownNames(); renderOps(getCollabName() || 'Team'); }}
          return resp;
        }});
      }}
      // Catalog event — soft-delete via opsWrite (re-renders + filters it out).
      return window.opsWrite('event_state', key, {{ status: '__deleted__' }});
    }};

    // ── Per-event team chat (the "Discussion" thread) ───────────────
    // The modal lives in a separate closure with no direct `sb`, so it hands us
    // the record and we own fetch / render / send here. Degrades quietly to a
    // "run the migration" note if the event_chat table isn't there yet.
    var _chatCounts = {{}};
    var _chatMeta = {{}};   // per event: {{count, latest, msgs:[{{author, at}}]}} — feeds "In the last week"
    function loadChatCounts() {{
      sb.from('event_chat').select('event_num,manual_id,author,created_at').then(function (resp) {{
        if (resp.error || !resp.data) return;   // table not migrated yet -> no counts, no noise
        var counts = {{}}, meta = {{}};
        resp.data.forEach(function (r) {{
          var k = (r.manual_id != null) ? ('m' + r.manual_id) : (r.event_num != null ? ('c' + r.event_num) : null);
          if (!k) return;
          counts[k] = (counts[k] || 0) + 1;
          var m = (meta[k] = meta[k] || {{ count: 0, latest: '', msgs: [] }});
          m.count++;
          if ((r.created_at || '') > m.latest) m.latest = r.created_at || '';
          m.msgs.push({{ author: r.author || '', at: r.created_at || '' }});
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
    function _paintChatList(list, msgs) {{
      list.innerHTML = '';
      if (!msgs.length) {{ list.innerHTML = '<p class="chat-empty">No messages yet — start the conversation.</p>'; return; }}
      var me = (getCollabName() || '').trim().toLowerCase();
      msgs.forEach(function (m) {{
        var when = '';
        try {{ when = new Date(m.created_at).toLocaleString('en-US', {{ month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }}); }} catch (e) {{}}
        var mine = me && String(m.author || '').trim().toLowerCase() === me;
        var div = document.createElement('div'); div.className = 'chat-msg';
        div.dataset.msgId = m.id;
        div.innerHTML = '<div class="chat-meta"><span class="chat-who">' + escapeHtml(String(m.author || '')) +
          '</span> <span class="chat-when">' + escapeHtml(when) + '</span>' +
          (mine ? '<button type="button" class="chat-del" data-chat-del="' + escapeHtml(String(m.id)) + '" title="Delete your message" aria-label="Delete message">&times;</button>' : '') +
          '</div>' +
          '<p class="chat-body">' + escapeHtml(String(m.body || '')) + '</p>';
        list.appendChild(div);
      }});
      list.scrollTop = list.scrollHeight;
      list.querySelectorAll('[data-chat-del]').forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          if (!window.confirm('Delete this message? This cannot be undone.')) return;
          var id = btn.getAttribute('data-chat-del');
          sb.from('event_chat').delete().eq('id', id).then(function (resp) {{
            if (resp.error) {{ status('Delete failed: ' + resp.error.message, 'error'); return; }}
            _reloadOpenChat(); loadChatCounts();
          }});
        }});
      }});
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
        '</form>';
      sb.from('event_chat').select('*').eq(col, rec._key).order('created_at', {{ ascending: true }}).then(function (resp) {{
        var list = document.getElementById('chat-list'); if (!list) return;
        // If the event_chat table hasn't been migrated yet, show the normal
        // empty state instead of a setup warning (a send will surface the error).
        if (resp.error) {{ _paintChatList(list, []); return; }}
        _paintChatList(list, resp.data || []);
        // Opening the thread marks it read — its "new comments" row in
        // My Events comes down automatically (Slack-style).
        try {{
          var _sn = _wnState(); _sn.chatSeen = _sn.chatSeen || {{}};
          _sn.chatSeen[panel.dataset.chatkey] = (resp.data && resp.data.length)
            ? (resp.data[resp.data.length - 1].created_at || new Date().toISOString())
            : new Date().toISOString();
          _wnSave(_sn);
        }} catch (e) {{}}
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
