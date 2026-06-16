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
        if start <= TODAY <= end:
            today_events.append(ev)
        elif end < TODAY:
            archived.append(ev)
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
    if aud:
        low = aud.lower()
        aud_cls = ('aud-buyer' if 'buyer' in low
                   else 'aud-vendor' if ('vendor' in low or 'seller' in low)
                   else 'aud-mixed')
        sig.append(f'<span class="badge {aud_cls}">{e(aud)}</span>')
    if ev.get('pricing'):
        sig.append(f'<span class="attend-sig" title="Price to attend">'
                   f'{e(str(ev["pricing"]))}</span>')
    if ev.get('meeting_formats'):
        sig.append(f'<span class="attend-sig" title="{e(str(ev["meeting_formats"]))}">'
                   f'1:1 meetings</span>')
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
      <p class="event-loc"><span class="event-region">{e(region)}</span> · {e(ev['location'])}</p>
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
  <link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=Fragment+Mono&display=swap" rel="stylesheet">

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
    .nav-inner {{ max-width: var(--ab-max); margin: 0 auto; display: flex; justify-content: space-between; align-items: center; width: 100%; gap: 16px; }}
    .brand {{
      display: flex; align-items: center; gap: 12px;
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
      text-transform: uppercase;
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
    .badge.p-high {{ background: var(--ab-fg); color: #fff; }}
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
    /* One-click "Apply to speak" button on ops cards — the booking shortcut. */
    .ops-apply-btn {{
      display: inline-block; font-family: var(--ab-mono); font-size: 0.7rem;
      letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700;
      padding: 5px 11px; border-radius: 3px; margin: 0 0 8px;
      background: var(--ab-blue, #1d4ed8); color: #fff !important; text-decoration: none;
    }}
    .ops-apply-btn:hover {{ opacity: 0.85; }}
    .event-name {{
      font-family: var(--ab-sans); font-size: 1.1rem; font-weight: 700;
      line-height: 1.25; margin: 0; color: var(--ab-fg); letter-spacing: -0.01em;
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
    .modal-scroll {{ padding: 30px 32px 26px; max-height: 86vh; overflow-y: auto; }}
    /* Fixed top-right toolbar — Edit event + close sit in the SAME spot for
       every event (consistent placement, no floating). */
    .modal-topbar {{
      position: absolute; top: 12px; right: 14px; z-index: 3;
      display: flex; align-items: center; gap: 8px;
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
      font-family: var(--ab-mono); font-size: 0.74rem; color: var(--ab-mute);
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
      color: var(--ab-fg-2); transition: all 0.12s;
    }}
    .modal-quickbar .qa:hover {{ border-color: var(--ab-fg-3); color: var(--ab-fg); }}
    .modal-quickbar .qa.on {{
      background: #166534; color: #fff; border-color: #166534;
    }}
    /* Primary edit affordance — top-right of the modal header, same spot always. */
    .qa-edit {{
      display: inline-flex; align-items: center; gap: 6px; min-height: 34px;
      font-family: var(--ab-sans); font-size: 0.82rem; font-weight: 600;
      padding: 0 16px; border-radius: 8px; cursor: pointer; white-space: nowrap;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg-3); color: var(--ab-fg);
      transition: all 0.12s;
    }}
    .qa-edit:hover, .qa-edit.on {{ background: var(--ab-fg); color: var(--ab-bg); border-color: var(--ab-fg); }}
    .qa-edit-ic {{ font-size: 0.92em; }}
    .modal-quickbar .qa[data-qa="saved"].on {{ background: var(--ab-blue); border-color: var(--ab-blue); }}
    .modal-quickbar .qa[data-qa="hidden"].on {{ background: var(--ab-fg-3); border-color: var(--ab-fg-3); }}
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
      .modal-scroll {{ padding: 26px 20px 22px; }}
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
    .alert button.inline {{
      font: inherit; color: inherit;
      background: transparent; border: 0; padding: 0;
      text-decoration: underline; cursor: pointer; margin-left: 6px;
    }}

    /* Ops grid — same skeleton as .event-grid but with edit controls */
    .ops-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}

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
      font-family: var(--ab-mono); font-size: 0.66rem; letter-spacing: 0.06em;
      text-transform: uppercase; color: var(--ab-fg-2);
      background: var(--ab-bg-3); border: 1px solid var(--ab-rule);
      border-radius: 6px; padding: 5px 10px; cursor: pointer;
      display: inline-flex; align-items: center; gap: 6px;
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
      background: var(--ab-bg);
      transition: border-color 120ms ease;
    }}
    .ops-card:hover {{ border-color: var(--ab-rule-strong); }}
    .ops-card.is-saved {{ border-color: var(--ab-blue); }}
    .ops-card-head {{
      display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;
      margin-bottom: 8px;
    }}
    .ops-card .event-date {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      text-transform: uppercase; margin: 0;
    }}
    .ops-card .event-name {{
      font-family: var(--ab-sans); font-weight: 700;
      font-size: 1.05rem; line-height: 1.3; letter-spacing: -0.01em;
      margin: 0 0 4px; color: var(--ab-fg);
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
      border-radius: 4px; padding: 2px 8px; margin-left: 6px; cursor: pointer;
      vertical-align: 2px; transition: background 0.15s, color 0.15s, border-color 0.15s;
    }}
    .ops-details-btn:hover {{ background: var(--ab-blue); color: #fff; border-color: var(--ab-blue); }}
    .ops-tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }}
    .ops-tag {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.06em; padding: 3px 8px;
      border-radius: 999px; background: var(--ab-bg-3);
      color: var(--ab-fg-2); line-height: 1.4;
      display: inline-flex; align-items: center; gap: 4px;
    }}
    .ops-tag.status   {{ background: #ecfdf5; color: #065f46; }}
    .ops-tag.speaker  {{ background: #eff6ff; color: #1e40af; }}
    .ops-tag.pri-high   {{ background: #1f2937; color: #fff; }}
    .ops-tag.pri-medium {{ background: #fef3c7; color: #92400e; }}
    .ops-tag.pri-low    {{ background: var(--ab-bg-3); color: var(--ab-fg-3); }}
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
    .ops-chips {{ display: flex; gap: 6px; align-items: center; }}
    .ops-chip {{
      font: inherit; cursor: pointer;
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      padding: 3px 8px; border-radius: 999px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-3); line-height: 1.4;
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
    }}
    .ops-chip:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .ops-chip.is-on {{ background: var(--ab-fg); color: var(--ab-bg); border-color: var(--ab-fg); }}
    .ops-chip.is-on.urgent {{ background: var(--ab-red); border-color: var(--ab-red); }}
    .ops-chip[aria-busy="true"] {{ opacity: 0.4; cursor: wait; }}
    .ops-chip.badge-manual {{
      cursor: default; pointer-events: none;
      background: var(--ab-blue); color: var(--ab-bg); border-color: var(--ab-blue);
    }}

    .ops-card.is-hidden {{ opacity: 0.55; background: var(--ab-bg-2); }}
    /* Past events: dimmed when revealed via "Show past" (default: filtered out). */
    .ops-card.is-past {{ opacity: 0.6; }}
    .ops-card.is-past:hover {{ opacity: 1; }}
    .ops-card.is-urgent {{ border-color: var(--ab-red); }}
    .ops-card.is-saved.is-urgent {{ border-color: var(--ab-red); box-shadow: inset 4px 0 0 var(--ab-blue); }}

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
    .ops-form label {{ display: flex; flex-direction: column; gap: 4px; }}
    .ops-form label > .key {{
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
      grid-template-columns: repeat(7, 1fr);
      background: var(--ab-rule);
      border: 1px solid var(--ab-rule);
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 18px;
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

    /* Extra filters — Priority / Track / Speakers rows */
    .extra-filters {{
      display: flex; flex-direction: column; gap: 8px;
      padding: 10px 12px; margin-bottom: 16px;
      border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg);
    }}
    .extra-filter-group {{
      display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    }}
    .extra-filter-label {{
      font-family: var(--ab-mono); font-size: 0.66rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--ab-fg-3); min-width: 84px;
    }}
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
    .extra-chip.pri-high.is-on   {{ background: #1f2937; color: #fff; border-color: #1f2937; box-shadow: 0 0 0 2px #1f2937; }}
    .extra-chip.pri-medium.is-on {{ background: #fef3c7; color: #92400e; border-color: #92400e; box-shadow: 0 0 0 2px #92400e; }}
    .extra-chip.pri-low.is-on    {{ background: var(--ab-bg-3); color: var(--ab-fg-3); border-color: var(--ab-fg-3); box-shadow: 0 0 0 2px var(--ab-fg-3); }}
    .extra-chip.track-sponsor.is-on  {{ background: #dbeafe; color: #1e40af; border-color: #1e40af; box-shadow: 0 0 0 2px #1e40af; }}
    .extra-chip.track-earned.is-on   {{ background: #fef3c7; color: #92400e; border-color: #92400e; box-shadow: 0 0 0 2px #92400e; }}
    .extra-chip.track-both.is-on     {{ background: #e9d5ff; color: #6b21a8; border-color: #6b21a8; box-shadow: 0 0 0 2px #6b21a8; }}
    .extra-chip.track-unknown.is-on  {{ background: var(--ab-bg-3); color: var(--ab-fg-3); border-color: var(--ab-fg-3); box-shadow: 0 0 0 2px var(--ab-fg-3); }}
    .extra-clear {{
      font-family: var(--ab-mono); font-size: 0.62rem;
      letter-spacing: 0.06em; padding: 4px 8px;
      border: 1px solid var(--ab-rule-strong); border-radius: 6px;
      background: var(--ab-bg); color: var(--ab-fg-3);
      cursor: pointer; margin-left: auto;
    }}
    .extra-clear:hover {{ color: var(--ab-fg); }}

    /* Filter bar */
    .ops-filters {{
      display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
      padding: 12px; margin-bottom: 16px;
      border: 1px solid var(--ab-rule); border-radius: 10px;
      background: var(--ab-bg);
    }}
    .ops-filters input[type="search"] {{
      flex: 1; min-width: 180px;
      font-family: var(--ab-sans); font-size: 0.9rem;
      padding: 8px 12px; border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; background: var(--ab-bg);
      color: var(--ab-fg); outline: none;
    }}
    .ops-filters input[type="search"]:focus {{
      border-color: var(--ab-blue); box-shadow: 0 0 0 3px rgba(39,115,194,0.12);
    }}
    .ops-filters select {{
      font-family: var(--ab-sans); font-size: 0.9rem;
      padding: 8px 12px; border: 1px solid var(--ab-rule-strong);
      border-radius: 6px; background: var(--ab-bg);
      color: var(--ab-fg); outline: none;
    }}
    .ops-filter-chip {{
      display: inline-flex; align-items: center; gap: 6px;
      font-family: var(--ab-mono); font-size: 0.72rem;
      letter-spacing: 0.06em; text-transform: uppercase;
      padding: 7px 12px; border-radius: 6px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); cursor: pointer; user-select: none;
    }}
    .ops-filter-chip:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}
    .ops-filter-chip input {{ accent-color: var(--ab-blue); }}
    .ops-filter-chip.has-active {{ background: var(--ab-bg-3); border-color: var(--ab-fg); color: var(--ab-fg); }}
    .ops-shown {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      margin-left: auto;
    }}

    /* View toggle (Grid / Calendar) */
    .view-toggle {{
      display: inline-flex; gap: 2px;
      padding: 3px; background: var(--ab-bg-3);
      border-radius: 8px; margin-bottom: 16px;
    }}
    .view-toggle button {{
      font-family: var(--ab-sans); font-weight: 500; font-size: 0.85rem;
      padding: 6px 14px; border-radius: 6px; border: 0;
      background: transparent; color: var(--ab-fg-2);
      cursor: pointer; transition: background 120ms ease, color 120ms ease;
    }}
    .view-toggle button:hover {{ color: var(--ab-fg); }}
    .view-toggle button.active {{ background: var(--ab-bg); color: var(--ab-fg); box-shadow: 0 1px 2px rgba(0,0,0,0.06); }}

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
    .map-sb-ev .nm {{ font-size: 0.92rem; line-height: 1.35; color: var(--ab-fg); font-weight: 500; }}
    .map-sb-ev .meta {{ display: flex; flex-direction: column; align-items: flex-end; gap: 5px; flex-shrink: 0; }}
    .map-sb-ev .dt {{ font-family: var(--ab-mono); font-size: 0.74rem; color: var(--ab-fg-3); white-space: nowrap; }}
    .msb-badge {{
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 700;
      padding: 2px 7px; border-radius: 999px; white-space: nowrap; letter-spacing: 0.02em;
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
    .calendar-month {{ margin-bottom: 32px; }}
    .calendar-month-head {{
      font-family: var(--ab-sans); font-weight: 700;
      font-size: 1.1rem; letter-spacing: -0.01em;
      margin: 0 0 12px; color: var(--ab-fg);
    }}
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
      grid-auto-rows: min-content;
    }}
    .cal-day-bg {{
      border-top: 1px solid var(--ab-rule); border-right: 1px solid var(--ab-rule);
      min-height: 106px; background: var(--ab-bg);
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
      border-radius: 5px; background: var(--ab-bg-2);
      border-left: 3px solid var(--ab-rule-strong);
      font-family: var(--ab-sans); font-size: 0.74rem; line-height: 1.2;
      cursor: pointer; overflow: hidden; white-space: nowrap;
      box-shadow: 0 1px 0 rgba(0,0,0,0.03); transition: filter 120ms ease;
    }}
    .cal-evt:hover {{ filter: brightness(0.96); }}
    .cal-evt.is-saved {{ background: rgba(39,115,194,0.12); border-left-color: var(--ab-blue); }}
    .cal-evt.is-urgent {{ background: rgba(185,28,28,0.10); border-left-color: var(--ab-red); }}

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
      padding: 2px 7px; border-radius: 999px; border: 1px solid var(--ab-rule);
      background: var(--ab-bg-2); color: var(--ab-fg-2);
    }}
    .ask-card .ac-tag.buyer {{ background: #ecfdf5; color: #047857; border-color: #a7f3d0; }}
    .ask-card .ac-tag.worth {{ background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }}
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

    .ops-toolbar .ops-count {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      margin-left: auto;
    }}

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
      .event-grid, .archive-grid {{ grid-template-columns: 1fr; }}
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
<body>

  <nav class="nav">
    <div class="nav-inner">
      <a class="brand" href="https://arcticblue.ai/" aria-label="ArcticBlue home">
        <img src="arcticblue-logo.png" alt="ArcticBlue" width="32" height="29">
        <span class="brand-text">ArcticBlue</span>
      </a>
      <p class="nav-meta">Last updated · {last_updated.upper()}</p>
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
        <div class="angela-header">
          <span class="who">Editing as <strong id="ops-email">Team</strong> <button type="button" id="change-name" class="inline">change</button></span>
          <span class="collab-note">Live &amp; shared — every edit is visible to the whole team instantly.</span>
        </div>
        <div id="ops-status" class="alert" hidden></div>
        <div class="ops-stats" id="ops-stats" hidden></div>
        <div class="stage-filters" id="stage-filters">
          <span class="label">Pipeline:</span>
          <!-- 5 stage chips injected by buildStageFilters() -->
        </div>
        <details class="legacy-status-wrap">
          <summary>Legacy status filters (detail)</summary>
          <div class="status-filters" id="status-filters">
            <span class="label">Status:</span>
            <!-- chips injected by buildStatusFilters() -->
          </div>
        </details>
        <div class="extra-filters" id="extra-filters">
          <div class="extra-filter-group" id="filter-priority">
            <span class="extra-filter-label">Priority</span>
            <!-- chips injected by buildExtraFilters() -->
          </div>
          <div class="extra-filter-group" id="filter-track">
            <span class="extra-filter-label">Track</span>
          </div>
          <div class="extra-filter-group" id="filter-speaker">
            <span class="extra-filter-label">Speakers</span>
            <span class="extra-empty" id="filter-speaker-empty">No speakers assigned yet</span>
          </div>
        </div>
        <div class="ops-filters">
          <input type="search" id="ops-search" placeholder="Search name / location / notes…" aria-label="Search ops">
          <select id="ops-region" aria-label="Filter region">
            <option value="">All regions</option>
            <option value="Americas">Americas</option>
            <option value="Europe">Europe</option>
            <option value="Asia-Pacific">Asia-Pacific</option>
            <option value="MENA">MENA</option>
            <option value="Global">Global</option>
          </select>
          <select id="ops-price" aria-label="Filter by ticket price" title="Higher ticket price usually means higher-clientele buyers in the room">
            <option value="">Any ticket price</option>
            <option value="free">Free</option>
            <option value="lt1000">Under $1,000</option>
            <option value="1000-2500">$1,000 – $2,500</option>
            <option value="gte2500">$2,500+ (high clientele)</option>
            <option value="known">Price known</option>
          </select>
          <label class="ops-filter-chip"><input type="checkbox" id="ops-f-speaker">Has speaker</label>
          <label class="ops-filter-chip"><input type="checkbox" id="ops-f-buyers">Buyer-rich only</label>
          <div class="ops-months">
            <button type="button" class="ops-months-btn" id="ops-months-btn" aria-haspopup="true" aria-expanded="false">
              Months <span class="mb-caret" aria-hidden="true">&#9660;</span>
            </button>
            <div class="ops-months-menu" id="ops-months-menu" role="menu" aria-label="Show or hide months">
              <div class="ops-months-actions">
                <button type="button" id="ops-months-all">Show all</button>
                <button type="button" id="ops-months-none">Hide all</button>
              </div>
              <div class="ops-months-list" id="ops-months-list"></div>
            </div>
          </div>
          <span class="ops-shown" id="ops-shown"></span>
        </div>
        <div class="view-toggle" role="tablist" aria-label="View">
          <button type="button" role="tab" data-view="grid"     class="active" aria-selected="true">Grid</button>
          <button type="button" role="tab" data-view="calendar" aria-selected="false">Calendar</button>
          <button type="button" role="tab" data-view="map"      aria-selected="false">Map</button>
        </div>
        <div class="ops-toolbar">
          <div class="ops-toolbar-group" role="group" aria-label="Add events">
            <span class="ops-toolbar-label">Add</span>
            <button class="ab-btn ab-btn--primary" id="add-event-btn">
              <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
              Add event
            </button>
            <button class="ab-btn ab-btn--ghost ab-btn--blue" id="paste-email-btn" title="Paste an event email — name, dates and contacts are pre-filled for you">
              <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg>
              Paste email
            </button>
            <button class="ab-btn ab-btn--ghost ab-btn--purple" id="search-dust-btn" title="Ask the AI to find new speaking events matching your criteria">
              <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v2"/><path d="M12 19v2"/><path d="M3 12h2"/><path d="M19 12h2"/><path d="m5.6 5.6 1.5 1.5"/><path d="m16.9 16.9 1.5 1.5"/><path d="m5.6 18.4 1.5-1.5"/><path d="m16.9 7.1 1.5-1.5"/><circle cx="12" cy="12" r="4"/></svg>
              Find events (AI)
            </button>
          </div>
          <div class="ops-toolbar-group" role="group" aria-label="Sync and export">
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
          <button class="ab-btn ab-btn--ask" id="ask-ai-btn" title="Ask anything about these events — e.g. 'which events should I attend in September?'">
            <svg class="ab-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v2"/><path d="M12 19v2"/><path d="M3 12h2"/><path d="M19 12h2"/><path d="m5.6 5.6 1.5 1.5"/><path d="m16.9 16.9 1.5 1.5"/><path d="m5.6 18.4 1.5-1.5"/><path d="m16.9 7.1 1.5-1.5"/><circle cx="12" cy="12" r="4"/></svg>
            Ask AI
          </button>
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
      </div>

    </div><!-- /panel-angela -->

    <footer class="foot">
      <p class="foot-text">ArcticBlue · Event Tracker · Auto-archives events one day after end-date.</p>
      <p class="foot-mono">v1.2 · {today_iso}</p>
    </footer>
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
  var AB_ROSTER = ['Thor', 'Joe', 'Jerome', 'Scott', 'Verma', 'Carlos', 'Jim'];

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
  // Numeric ticket price from a free-text pricing string ('$2,495 delegate
  // pass' -> 2495, 'Free' -> 0, unknown -> null). Used by the price filter;
  // when several numbers appear (buyer vs vendor tiers) the HIGHEST wins,
  // since the top tier is the high-clientele signal Verma filters on.
  function priceNumOf(p) {{
    if (p == null) return null;
    var s = String(p).toLowerCase();
    if (!s.trim()) return null;
    if (/\\bfree\\b|\\bcomplimentary\\b|\\bno cost\\b/.test(s)) return 0;
    var m = s.replace(/,/g, '').match(/\\d{{2,6}}(?:\\.\\d+)?/g);
    if (!m) return null;
    return Math.max.apply(null, m.map(parseFloat));
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
  // Renders only when the modal was opened from an editable ops/manual card
  // (rec._table + rec._key present). Each button writes a single field via
  // window.opsWrite (bridged from the ops closure). Save/Hide are catalog-
  // only (manual_events has no saved/hidden column).
  function quickBarHtml(rec) {{
    if (!rec || !rec._table || rec._key == null) return '';
    var stages = rec.stage_tags || [];
    function has(s) {{ return stages.indexOf(s) !== -1; }}
    var isCat = rec._table === 'event_state';
    var att = (rec.attend_verdict || '').indexOf('Worth') === 0;
    var b = [];
    if (isCat) {{
      b.push('<button type="button" class="qa' + (rec.saved ? ' on' : '') + '" data-qa="saved">' + (rec.saved ? '★ Saved' : '☆ Save') + '</button>');
      b.push('<button type="button" class="qa' + (rec.hidden ? ' on' : '') + '" data-qa="hidden">' + (rec.hidden ? 'Unhide' : 'Hide') + '</button>');
    }}
    b.push('<button type="button" class="qa' + (has('Submitted') ? ' on' : '') + '" data-qa="submitted">' + (has('Submitted') ? '✓ Submitted' : 'Mark Submitted') + '</button>');
    b.push('<button type="button" class="qa' + (has('Booked') ? ' on' : '') + '" data-qa="booked">' + (has('Booked') ? '✓ Booked' : 'Speaking Booked') + '</button>');
    b.push('<button type="button" class="qa' + (att ? ' on' : '') + '" data-qa="attending">' + (att ? '✓ Attending' : 'Attending') + '</button>');
    // Fast one-tap actions. (The "Edit event" toggle lives in the modal header,
    // top-right, in the same spot for every event.)
    return '<div class="modal-quickbar"><div class="qa-row">' + b.join('') + '</div></div>';
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
      else if (qa === 'attending') {{
        var on = (rec.attend_verdict || '').indexOf('Worth') === 0;
        rec.attend_verdict = on ? null : 'Worth attending';
        patch.attend_verdict = rec.attend_verdict;
      }} else if (qa === 'submitted' || qa === 'booked') {{
        var stage = qa === 'submitted' ? 'Submitted' : 'Booked';
        var tags = (rec.stage_tags || []).slice();
        var idx = tags.indexOf(stage);
        if (idx === -1) tags.push(stage); else tags.splice(idx, 1);
        var order = window.opsStageOrder || [];
        if (order.length) tags = order.filter(function (s) {{ return tags.indexOf(s) !== -1; }});
        rec.stage_tags = tags;
        patch.status_tags = tags;
      }} else {{ return; }}
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
      return '<div class="modal-field"><span class="k">' + esc(label) + '</span>' + control + '</div>';
    }}
    function inp(f, val, ph) {{
      return '<input class="me-input" type="text" data-edit="' + f + '" value="' + esc(val || '') + '"' + (ph ? ' placeholder="' + esc(ph) + '"' : '') + '>';
    }}
    function ta(f, val, rows) {{
      return '<textarea class="me-input" data-edit="' + f + '" rows="' + (rows || 3) + '">' + esc(val || '') + '</textarea>';
    }}
    var stages = rec.stage_tags || [];
    var order = window.opsStageOrder || ['Identified', 'Submitted', 'Meeting held', 'Booked', 'Declined'];
    var chips = order.map(function (s) {{
      return '<button type="button" class="me-stage' + (stages.indexOf(s) !== -1 ? ' on' : '') + '" data-stage="' + esc(s) + '">' + esc(s) + '</button>';
    }}).join('');
    var interested = rec.interested || [];
    var intChips = AB_ROSTER.map(function (n) {{
      return '<label class="me-int' + (interested.indexOf(n) !== -1 ? ' on' : '') + '"><input type="checkbox" data-interested="' + esc(n) + '"' + (interested.indexOf(n) !== -1 ? ' checked' : '') + '>' + esc(n) + '</label>';
    }}).join('');
    var verdicts = ['', 'Worth attending', 'Maybe', 'Not worth it'];
    var pris = ['', 'High', 'Medium', 'Low'];
    var p2p = ['', 'Yes', 'No', 'Both'];
    var curPri = isCat ? (rec.priority_override || rec.priority || '') : (rec.priority || '');
    var h = '';
    if (!isCat) {{
      h += ef('Event name', inp('name', rec.name));
      h += ef('Date', inp('date_str', rec.date_str, 'e.g. Sept 14–16, 2026'));
      h += ef('Location', inp('location', rec.location));
      h += ef('Website', inp('url', rec.url, 'https://'));
    }}
    h += ef('Pipeline stage', '<div class="me-stages">' + chips + '</div>');
    h += ef('ArcticBlue speaker', '<input class="me-input" type="text" data-edit="speaker" list="ab-speakers" value="' + esc(rec.speaker || '') + '" placeholder="Unassigned">');
    h += ef('Interested — wants Angela to apply', '<div class="me-ints">' + intChips + '</div>');
    h += ef('Worth attending?', '<select class="me-input" data-edit="attend_verdict">' + verdicts.map(function (v) {{ return opt(v, rec.attend_verdict); }}).join('') + '</select>');
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
    h += ef('Notes', ta('notes', rec.notes, 2));
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
        list = AB_ROSTER.filter(function (x) {{ return list.indexOf(x) !== -1; }});
        rec.interested = list;
        var lbl = cb.closest('.me-int'); if (lbl) lbl.classList.toggle('on', cb.checked);
        window.opsWrite(rec._table, rec._key, {{ interested: list }});
      }});
    }});
    box.querySelectorAll('[data-edit]').forEach(function (el) {{
      el.addEventListener('change', function () {{
        var field = el.dataset.edit;
        var val = (el.value == null ? '' : String(el.value)).trim();
        if (field === 'name' && !val) {{ el.value = rec.name || ''; return; }}
        var out = val === '' ? null : val;
        if (field === 'url' && out && !/^https?:\\/\\//i.test(out)) out = 'https://' + out;
        var patch = {{}}; patch[field] = out;
        if (field === 'priority_override') rec.priority = out;
        else rec[field] = out;
        window.opsWrite(rec._table, rec._key, patch);
      }});
    }});
  }}

  function openEventModal(rec) {{
    if (!rec) return;
    var badges = [];
    if (rec.priority) badges.push('<span class="badge ' + priClass(rec.priority) + '">' + esc(rec.priority) + '</span>');
    if (rec.type)     badges.push('<span class="badge p-medium">' + esc(rec.type) + '</span>');
    // Pipeline stages (primary). Fall back to the legacy single status badge
    // only when no stages are set, so we don't double up.
    if (rec.stage_tags && rec.stage_tags.length) {{
      rec.stage_tags.forEach(function (k) {{ badges.push('<span class="badge p-low">' + esc(k) + '</span>'); }});
    }} else if (rec.workflow_status) {{
      badges.push('<span class="badge p-low">' + esc(rec.workflow_status) + '</span>');
    }}
    if (rec.status && !(rec.stage_tags && rec.stage_tags.length) && /booked|confirm|attend/i.test(rec.status)) badges.push('<span class="badge p-low">' + esc(rec.status) + '</span>');
    if (rec.pay_to_play && /yes|both/i.test(rec.pay_to_play)) badges.push('<span class="badge p-low">Pay-to-play</span>');
    if (rec.audience_type) badges.push('<span class="badge ' + audienceClass(rec.audience_type) + '">' + esc(rec.audience_type) + '</span>');
    if (rec.meeting_formats) badges.push('<span class="badge p-medium" title="' + esc(rec.meeting_formats) + '">1:1 meetings</span>');
    if (rec.attend_verdict) badges.push('<span class="badge ' + attendClass(rec.attend_verdict) + '">' + esc(rec.attend_verdict) + '</span>');
    if (rec.urgent === true) badges.push('<span class="badge p-high">Urgent</span>');
    if (rec.seed === true)   badges.push('<span class="badge p-low">Seed</span>');
    $badges.innerHTML = badges.join('');

    $date.textContent  = rec.date_str || '';
    if (rec.url) {{
      $title.innerHTML = '<a class="modal-title-link" href="' + esc(rec.url) + '" target="_blank" rel="noopener">' + esc(rec.name || 'Event') + ' <span class="event-link-arrow" aria-hidden="true">↗</span></a>';
    }} else {{
      $title.textContent = rec.name || 'Event';
    }}
    var regionTxt = rec.region ? '<span class="event-region">' + esc(rec.region) + '</span>' : '';
    var locTxt = esc(rec.location || '');
    $loc.innerHTML = regionTxt + (regionTxt && locTxt ? ' · ' : '') + locTxt;

    var html = '';
    html += quickBarHtml(rec);

    // Read-only view. The edit form below mirrors this exact layout.
    var v = '';
    if (rec.interested && rec.interested.length) {{
      v += field('Interested — wants Angela to apply',
        rec.interested.map(function (n) {{ return '<span class="int-chip">' + esc(n) + '</span>'; }}).join(''), true);
    }}
    v += field('Why it fits ArcticBlue', rec.why);
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
    grid += field('Worth attending?', rec.attend_verdict);
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

    // "Edit event" toggle — header top-right, same spot for every event. It
    // swaps the read-only view for the (identically-laid-out) edit form.
    var $side = document.getElementById('modal-head-side');
    if ($side) {{
      $side.innerHTML = editForm
        ? '<button type="button" class="qa-edit" id="modal-edit-toggle" aria-expanded="false"><span class="qa-edit-ic" aria-hidden="true">✎</span> Edit event</button>'
        : '';
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
          et.innerHTML = '<span class="qa-edit-ic" aria-hidden="true">✎</span> Edit event';
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
  // Shared helpers — the ops tab lives in a SEPARATE closure, so these must
  // ride on window or buildManualCard's calls throw ReferenceError.
  window.audienceClass = audienceClass;
  window.priceNumOf = priceNumOf;
  window.speakingRouteUrl = speakingRouteUrl;
  window.attendClass = attendClass;
  window.closeEventModal = closeModal;
  window.openEventByNum = function (num) {{ openEventModal(CATALOG[String(num)]); }};

  closeBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', function (ev) {{ if (ev.target === overlay) closeModal(); }});
  document.addEventListener('keydown', function (ev) {{
    if (ev.key === 'Escape' && !overlay.hasAttribute('hidden')) closeModal();
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
    var btn = ev.target.closest ? ev.target.closest('[data-detail]') : null;
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    var card = btn.closest('.ops-card');
    if (card && card._modalRec) openEventModal(card._modalRec);
  }});
  document.addEventListener('keydown', function (ev) {{
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    var t = ev.target;
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

  // Wait for the deferred Supabase UMD script to attach window.supabase
  function ready(cb) {{
    if (window.supabase && window.supabase.createClient) return cb();
    setTimeout(function () {{ ready(cb); }}, 50);
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
    var $opsEmail     = document.getElementById('ops-email');
    var $signoutUnauth = document.getElementById('signout-unauth');
    var $signoutOps    = document.getElementById('signout-ops');
    var $opsGrid   = document.getElementById('ops-grid');
    var $opsStatus = document.getElementById('ops-status');
    // Month keys ('YYYY-MM' or 'tbd') the user has collapsed in the ops grid.
    // A truthy value means that month's cards are hidden via the dropdown / header.
    var opsCollapsedMonths = {{}};
    // Active stat-tile filter ('' | 'saved' | 'urgent' | 'pipeline' | 'booked'
    // | 'buyer' | 'worth') — click a top stat to show only those events.
    var opsStatFilter = '';

    function showOnly(el) {{
      [$loading, $signin, $sent, $unauth, $ops].forEach(function (n) {{
        if (n) n.setAttribute('hidden', '');
      }});
      if (el) el.removeAttribute('hidden');
    }}

    function status(msg, kind) {{
      if (!msg) {{ $opsStatus.setAttribute('hidden', ''); return; }}
      $opsStatus.removeAttribute('hidden');
      $opsStatus.textContent = msg;
      $opsStatus.className = 'alert' + (kind ? ' ' + kind : '');
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
    // with Declined as the terminal off-ramp last.
    var STAGE_TAGS = [
      {{ key: 'Identified',   dot: '#737373', bg: '#e5e7eb', fg: '#374151' }},
      {{ key: 'Submitted',    dot: '#0ea5e9', bg: '#bae6fd', fg: '#075985' }},
      {{ key: 'Meeting held', dot: '#8b5cf6', bg: '#ddd6fe', fg: '#5b21b6' }},
      {{ key: 'Booked',       dot: '#047857', bg: '#bbf7d0', fg: '#14532d' }},
      {{ key: 'Declined',     dot: '#dc2626', bg: '#fee2e2', fg: '#991b1b' }}
    ];
    var STAGE_BY_KEY = {{}};
    STAGE_TAGS.forEach(function (s, i) {{ s.order = i; STAGE_BY_KEY[s.key] = s; }});
    // "Most important" ranking for a single calendar tint when an event
    // carries several stages: a win (Booked) trumps everything, then the
    // terminal Declined, then progress backwards.
    var STAGE_DISPLAY_RANK = ['Booked', 'Declined', 'Meeting held', 'Submitted', 'Identified'];

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
      if (/book|self submitted|attending|confirmed/i.test(s)) return ['Booked'];
      if (/not accept|declin|\\bskip\\b|passing|we.ll pass|no opening|date conflict|sponsorship only|don.?t call/i.test(s)) return ['Declined'];
      if (/intro meeting|received intro|in contact|cc.?d on mtg|\\bmeeting\\b/i.test(s)) return ['Meeting held'];
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
    function isPastEvent(o) {{
      var iso = eventEndIso(o);
      if (!iso || !/^\\d{{4}}-\\d{{2}}-\\d{{2}}/.test(iso)) return false;  // undated -> not past
      var now = new Date();
      var todayIso = now.getFullYear() + '-' +
        String(now.getMonth() + 1).padStart(2, '0') + '-' +
        String(now.getDate()).padStart(2, '0');
      return iso < todayIso;  // strictly before today; an event ending today is NOT past
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
      // Legacy single status — kept as a small muted detail so nothing
      // Angela typed is lost, but visually demoted beneath the stages.
      // Suppressed when it merely repeats a stage pill already shown
      // (status "Booked" + stage Booked was rendering "Booked" twice).
      if (st.status) {{
        var _legacyLow = String(st.status).trim().toLowerCase();
        var dupOfStage = stages.some(function (k) {{ return k.toLowerCase() === _legacyLow; }});
        if (!dupOfStage) {{
          var style = statusStyle(st.status);
          var styleAttr = style ? ' style="' + style + '"' : '';
          tags.push('<span class="ops-tag status legacy"' + styleAttr + ' title="Legacy status detail">' + escapeHtml(st.status) + '</span>');
        }}
      }}
      if (tags.length === 0) return '';
      return '<div class="ops-tags">' + tags.join('') + '</div>';
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
    function deadlineLine(d) {{
      if (d == null || !String(d).trim()) return '';
      var txt = String(d).trim();
      var cls = isDeadlineSoon(d) ? ' deadline-soon' : '';
      return '<p class="ops-meta deadline-line' + cls + '">CFP deadline: ' + escapeHtml(txt) + '</p>';
    }}

    function buildOpsCard(ev, st, email) {{
      var card = document.createElement('article');
      card.className = 'ops-card';
      card.dataset.eventNum = ev.num;
      card.dataset.kind = 'regular';
      card.dataset.region = ev.region || '';
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
      // Attending signals (catalog fields; verdict is ops-editable state)
      card.dataset.audience = (ev.audience_type || '');
      var _pn = priceNumOf(ev.pricing);
      card.dataset.price    = (_pn == null ? '' : String(_pn));
      card.dataset.meetings = (ev.meeting_formats ? '1' : '');
      card.dataset.attend   = (st.attend_verdict || '');
      var _opsPast = isPastEvent(ev);
      card.dataset.past = _opsPast ? '1' : '';
      if (_opsPast) card.classList.add('is-past');
      if (st.saved)  card.classList.add('is-saved');
      if (st.hidden) card.classList.add('is-hidden');
      // Urgent = manually flagged OR an apply/CFP deadline that's closing soon.
      // (The event merely being upcoming does NOT make it urgent.)
      var _soon = isDeadlineSoon(ev.deadline) && !_opsPast;
      if (_soon) card.dataset.deadlineSoon = '1';
      if (st.urgent || _soon) card.classList.add('is-urgent');

      var metaLine = (st.updated_by && st.updated_at)
        ? '<p class="ops-meta" title="' + escapeHtml(st.updated_by) + '">Last edit · ' + escapeHtml(firstNameFromEmail(st.updated_by)) + ' · ' + escapeHtml(formatStamp(st.updated_at)) + '</p>'
        : '';

      // Attending-signal strip + one-click apply (the booking shortcut).
      var sigBits = [];
      if (ev.audience_type) sigBits.push('<span class="badge ' + audienceClass(ev.audience_type) + '">' + escapeHtml(ev.audience_type) + '</span>');
      if (st.attend_verdict) sigBits.push('<span class="badge ' + attendClass(st.attend_verdict) + '">' + escapeHtml(st.attend_verdict) + '</span>');
      if (ev.pricing) sigBits.push('<span class="attend-sig" title="Price to attend">' + escapeHtml(ev.pricing) + '</span>');
      if (ev.meeting_formats) sigBits.push('<span class="attend-sig" title="' + escapeHtml(ev.meeting_formats) + '">1:1 meetings</span>');
      var sigRow = sigBits.length ? '<p class="attend-signals">' + sigBits.join('') + '</p>' : '';
      var applyUrl = speakingRouteUrl(ev.speaking_route);
      var applyBtn = applyUrl
        ? '<a class="ops-apply-btn" href="' + escapeHtml(applyUrl) + '" target="_blank" rel="noopener">Apply to speak ↗</a> '
        : '';

      card.innerHTML =
        '<div class="ops-card-head">' +
          '<div class="ops-chips">' +
            '<button class="saved-star' + (st.saved ? ' is-on' : '') + '" data-field="saved" data-on="' + (st.saved ? '1' : '0') + '" aria-label="Toggle saved" type="button">' + (st.saved ? '★' : '☆') + '</button>' +
            '<button class="ops-chip urgent' + (st.urgent ? ' is-on' : '') + '" data-field="urgent" data-on="' + (st.urgent ? '1' : '0') + '" type="button">Urgent</button>' +
            '<button class="ops-chip' + (st.hidden ? ' is-on' : '') + '" data-field="hidden" data-on="' + (st.hidden ? '1' : '0') + '" type="button">Hidden</button>' +
          '</div>' +
          '<p class="event-date">' + escapeHtml(ev.date_str) + '</p>' +
        '</div>' +
        '<h3 class="event-name">' +
          (ev.url
            ? '<a class="event-name-link" href="' + escapeHtml(ev.url) + '" target="_blank" rel="noopener" aria-label="Open website for ' + escapeHtml(ev.name) + '">' + escapeHtml(ev.name) + ' <span class="event-link-arrow" aria-hidden="true">↗</span></a>'
            : escapeHtml(ev.name)) +
          ' <button type="button" class="ops-details-btn" data-detail>Details →</button>' +
        '</h3>' +
        '<p class="event-loc">' + escapeHtml(ev.region || '') + ' · ' + escapeHtml(ev.location || '') + '</p>' +
        deadlineLine(ev.deadline) +
        sigRow +
        (st.interested && st.interested.length ? '<p class="ops-meta ops-interested">★ Interested: ' + escapeHtml(st.interested.join(', ')) + '</p>' : '') +
        applyBtn +
        renderOpsTags(st) +
        '<details class="ops-edit">' +
          '<summary>Edit</summary>' +
          '<div class="ops-form">' +
            '<label><span class="key">Pipeline stages</span>' +
              stageCheckboxes(opsStages) +
            '</label>' +
            '<label><span class="key">Speaker</span>' +
              '<input type="text" data-field="speaker" list="ab-speakers" value="' + escapeHtml(st.speaker || '') + '" placeholder="Who from AB is speaking?">' +
            '</label>' +
            '<div class="row">' +
              '<label><span class="key">Priority override</span>' +
                '<select data-field="priority_override">' + optionRows(['', 'High', 'Medium', 'Low'], st.priority_override) + '</select>' +
              '</label>' +
              '<label><span class="key">Track</span>' +
                '<select data-field="track">' + optionRows(['', 'Sponsor', 'Earned', 'Both', 'Unknown'], st.track) + '</select>' +
              '</label>' +
            '</div>' +
            '<label><span class="key">Notes</span>' +
              '<textarea data-field="notes" placeholder="Anything Angela should know…">' + escapeHtml(st.notes || '') + '</textarea>' +
            '</label>' +
            '<label><span class="key">Worth attending?</span>' +
              '<select data-field="attend_verdict">' + optionRows(['', 'Worth attending', 'Maybe', 'Not worth it'], st.attend_verdict) + '</select>' +
            '</label>' +
            '<label><span class="key">Post-mortem (ROI: contacts · meetings · sales vs cost)</span>' +
              '<textarea data-field="postmortem" placeholder="After the event: contacts made, client meetings, sales — was it worth the ticket + travel?">' + escapeHtml(st.postmortem || '') + '</textarea>' +
            '</label>' +
            '<details class="ops-edit"><summary>Legacy status (detail)</summary>' +
              '<div class="ops-form" style="margin-top:8px;">' +
                '<label><span class="key">Legacy status</span>' +
                  '<select data-field="status">' + statusOptionRows(st.status || '') + '</select>' +
                '</label>' +
              '</div>' +
            '</details>' +
          '</div>' +
          metaLine +
        '</details>';
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
         'pay_to_play', 'venue', 'contact_info', 'deadline'].forEach(function (f) {{
          if (st[f] != null && String(st[f]).trim() !== '') rec[f] = st[f];
        }});
        if (st.interested && st.interested.length) rec.interested = st.interested;
        rec.stage_tags = opsStages;
      }}
      rec.saved  = !!(st && st.saved);
      rec.hidden = !!(st && st.hidden);
      // Editing context for the modal's quick-actions / Edit Event button.
      rec._table = 'event_state'; rec._key = ev.num;
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
        '<div class="row">' +
          '<label><span class="key">Worth attending?</span><select name="attend_verdict">' + optionRows(['', 'Worth attending', 'Maybe', 'Not worth it'], o.attend_verdict || '') + '</select></label>' +
          '<label><span class="key">Post-mortem (ROI)</span><input type="text" name="postmortem" value="' + v('postmortem') + '" placeholder="Contacts / meetings / sales vs cost"></label>' +
        '</div>' +
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
      card.dataset.manualId = mev.id;
      card.dataset.kind = 'manual';
      card.dataset.region = mev.region || '';
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
      var _manPast = isPastEvent(mev);
      card.dataset.past = _manPast ? '1' : '';
      if (_manPast) card.classList.add('is-past');
      // Urgent = an apply/CFP deadline that's closing soon (not just upcoming).
      var _manSoon = isDeadlineSoon(mev.deadline) && !_manPast;
      if (_manSoon) {{ card.dataset.deadlineSoon = '1'; card.classList.add('is-urgent'); }}
      var manualMeta = opsMonthMeta(mev.start_date, mev.date_str);
      card.dataset.month = manualMeta.key;
      card.dataset.monthLabel = manualMeta.label;
      card.dataset.sort = manualMeta.sort;
      var whoText  = mev.created_by ? ('Added by ' + escapeHtml(firstNameFromEmail(mev.created_by)) + ' · ' + escapeHtml(formatStamp(mev.created_at))) : '';
      var whoTitle = mev.created_by ? (' title="' + escapeHtml(mev.created_by) + '"') : '';
      var who      = whoText;

      // Reuse renderOpsTags by adapting the manual row into a state-like object
      var tagsHtml = renderOpsTags({{
        status:      mev.status,
        status_tags: mev.status_tags,
        speaker:     mev.speaker,
        priority_override: mev.priority,
        track:    null
      }});

      // Contact strip below the location line — only render if at least one field
      var pocBits = [];
      if (mev.poc_name)  pocBits.push(escapeHtml(mev.poc_name));
      if (mev.poc_email) pocBits.push('<a href="mailto:' + escapeHtml(mev.poc_email) + '" style="color:var(--ab-blue);text-decoration:none;">' + escapeHtml(mev.poc_email) + '</a>');
      if (mev.poc_linkedin) pocBits.push('<a href="' + escapeHtml(mev.poc_linkedin) + '" target="_blank" rel="noopener" style="color:var(--ab-blue);text-decoration:none;">LinkedIn ↗</a>');
      var pocLine = pocBits.length ? '<p class="event-loc" style="font-size:0.8rem;">POC: ' + pocBits.join(' · ') + '</p>' : '';

      var addtlLine = (mev.additional_contacts && mev.additional_contacts.trim())
        ? '<details style="margin:6px 0;"><summary style="cursor:pointer;font-family:var(--ab-mono);font-size:0.66rem;color:var(--ab-fg-3);letter-spacing:0.06em;text-transform:uppercase;">+ Additional contacts</summary><p style="font-size:0.82rem;color:var(--ab-fg-2);white-space:pre-wrap;margin:6px 0;">' + escapeHtml(mev.additional_contacts) + '</p></details>'
        : '';

      var notesLine = (mev.notes && mev.notes.trim())
        ? '<p class="event-why" style="font-size:0.85rem;color:var(--ab-fg-2);margin:0 0 8px;white-space:pre-wrap;">' + escapeHtml(mev.notes) + '</p>'
        : '';

      var submLine = (mev.submission_status && mev.submission_status.trim() && mev.submission_status !== mev.status)
        ? '<p class="ops-meta">Submission notes: ' + escapeHtml(mev.submission_status) + '</p>'
        : '';

      var feeLine = (mev.speaking_fee || mev.paid !== null && mev.paid !== undefined)
        ? '<p class="ops-meta">' +
            (mev.speaking_fee ? 'Fee: ' + escapeHtml(mev.speaking_fee) : '') +
            (mev.speaking_fee && (mev.paid !== null && mev.paid !== undefined) ? ' · ' : '') +
            (mev.paid !== null && mev.paid !== undefined ? 'Paid: ' + (mev.paid ? 'yes' : 'no') : '') +
          '</p>'
        : '';
      // Buyer/seller read + ticket price — ArcticBlue wants buyer-rich rooms.
      var audChip = mev.audience_type
        ? '<span class="badge ' + audienceClass(mev.audience_type) + '">' + escapeHtml(mev.audience_type) + '</span>'
        : '';
      var attendChip = mev.attend_verdict
        ? '<span class="badge ' + attendClass(mev.attend_verdict) + '">' + escapeHtml(mev.attend_verdict) + '</span>'
        : '';
      var meetChip = mev.meeting_formats
        ? '<span class="attend-sig" title="' + escapeHtml(mev.meeting_formats) + '">1:1 meetings</span>'
        : '';
      var priceLine = (mev.pricing && String(mev.pricing).trim())
        ? '<p class="ops-meta">Price to attend: ' + escapeHtml(mev.pricing) + '</p>'
        : '';
      var speakersLine = (mev.past_speakers && String(mev.past_speakers).trim())
        ? '<p class="ops-meta" title="Past / announced speakers">Speakers: ' + escapeHtml(mev.past_speakers) + '</p>'
        : '';
      var mApplyUrl = speakingRouteUrl(mev.speaking_route);
      var mApplyBtn = mApplyUrl
        ? '<a class="ops-apply-btn" href="' + escapeHtml(mApplyUrl) + '" target="_blank" rel="noopener">Apply to speak ↗</a> '
        : '';
      card.innerHTML =
        '<div class="ops-card-head">' +
          '<div class="ops-chips">' +
            '<span class="ops-chip badge-manual">Manual</span>' +
            audChip +
            attendChip +
            meetChip +
          '</div>' +
          '<p class="event-date">' + escapeHtml(mev.date_str || '') + '</p>' +
        '</div>' +
        '<h3 class="event-name">' +
          (mev.url
            ? '<a class="event-name-link" href="' + escapeHtml(mev.url) + '" target="_blank" rel="noopener" aria-label="Open website for ' + escapeHtml(mev.name || '') + '">' + escapeHtml(mev.name || '') + ' <span class="event-link-arrow" aria-hidden="true">↗</span></a>'
            : escapeHtml(mev.name || '')) +
          ' <button type="button" class="ops-details-btn" data-detail>Details →</button>' +
        '</h3>' +
        '<p class="event-loc">' + escapeHtml(mev.region || '') + (mev.location ? ' · ' + escapeHtml(mev.location) : '') + '</p>' +
        (mev.interested && mev.interested.length ? '<p class="ops-meta ops-interested">★ Interested: ' + escapeHtml(mev.interested.join(', ')) + '</p>' : '') +
        tagsHtml +
        pocLine +
        (mev.why  ? '<p class="event-why" style="font-size:0.85rem;color:var(--ab-fg-2);margin:0 0 8px;">' + escapeHtml(mev.why) + '</p>' : '') +
        notesLine +
        addtlLine +
        submLine +
        deadlineLine(mev.deadline) +
        priceLine +
        speakersLine +
        feeLine +
        mApplyBtn +
        '<details class="ops-edit">' +
          '<summary>Edit</summary>' +
          '<form class="ops-form manual-edit">' +
            '<label><span class="key">Name</span>' +
              '<input type="text" name="name" value="' + escapeHtml(mev.name || '') + '" required></label>' +
            '<label><span class="key">Date</span>' +
              '<input type="text" name="date_str" value="' + escapeHtml(mev.date_str || '') + '"></label>' +
            '<div class="row">' +
              '<label><span class="key">Location</span>' +
                '<input type="text" name="location" value="' + escapeHtml(mev.location || '') + '"></label>' +
              '<label><span class="key">Region</span>' +
                '<select name="region">' + optionRows(['', 'Americas', 'Europe', 'Asia-Pacific', 'MENA', 'Global'], mev.region || '') + '</select></label>' +
            '</div>' +
            '<div class="row">' +
              '<label><span class="key">Type</span>' +
                '<input type="text" name="type" value="' + escapeHtml(mev.type || '') + '"></label>' +
              '<label><span class="key">Priority</span>' +
                '<select name="priority">' + optionRows(['', 'High', 'Medium', 'Low'], mev.priority || '') + '</select></label>' +
            '</div>' +
            '<label><span class="key">Pipeline stages</span>' +
              stageCheckboxes(manualStages, 'status_tags') +
            '</label>' +
            '<label><span class="key">Speaker</span>' +
              '<input type="text" name="speaker" list="ab-speakers" value="' + escapeHtml(mev.speaker || '') + '"></label>' +
            '<details class="ops-edit"><summary>Legacy status (detail)</summary>' +
              '<div class="ops-form" style="margin-top:8px;">' +
                '<label><span class="key">Legacy status</span>' +
                  '<select name="status">' + statusOptionRows(mev.status || '') + '</select></label>' +
              '</div>' +
            '</details>' +
            '<label><span class="key">Submission status (free text)</span>' +
              '<input type="text" name="submission_status" value="' + escapeHtml(mev.submission_status || '') + '"></label>' +
            '<div class="row">' +
              '<label><span class="key">POC name</span>' +
                '<input type="text" name="poc_name" value="' + escapeHtml(mev.poc_name || '') + '"></label>' +
              '<label><span class="key">POC email</span>' +
                '<input type="text" name="poc_email" value="' + escapeHtml(mev.poc_email || '') + '"></label>' +
            '</div>' +
            '<label><span class="key">POC LinkedIn</span>' +
              '<input type="text" name="poc_linkedin" value="' + escapeHtml(mev.poc_linkedin || '') + '"></label>' +
            '<label><span class="key">Additional contacts</span>' +
              '<textarea name="additional_contacts">' + escapeHtml(mev.additional_contacts || '') + '</textarea></label>' +
            '<label><span class="key">Why it fits</span>' +
              '<textarea name="why">' + escapeHtml(mev.why || '') + '</textarea></label>' +
            '<label><span class="key">Notes</span>' +
              '<textarea name="notes">' + escapeHtml(mev.notes || '') + '</textarea></label>' +
            '<div class="row">' +
              '<label><span class="key">Speaking fee</span>' +
                '<input type="text" name="speaking_fee" value="' + escapeHtml(mev.speaking_fee || '') + '"></label>' +
              '<label><span class="key">Paid</span>' +
                '<select name="paid">' +
                  '<option value=""'        + (mev.paid === null || mev.paid === undefined ? ' selected' : '') + '>—</option>' +
                  '<option value="true"'    + (mev.paid === true  ? ' selected' : '') + '>Yes</option>' +
                  '<option value="false"'   + (mev.paid === false ? ' selected' : '') + '>No</option>' +
                '</select></label>' +
            '</div>' +
            '<label><span class="key">URL</span>' +
              '<input type="text" name="url" value="' + escapeHtml(mev.url || '') + '"></label>' +
            '<details class="ops-edit"><summary>More details (About, Focus, Deadline, …)</summary>' +
              '<div class="ops-form" style="margin-top:8px;">' + richDetailFields(mev) + '</div>' +
            '</details>' +
            '<div class="add-actions">' +
              '<button type="submit" class="primary">Save changes</button>' +
              '<button type="button" class="secondary" data-delete>Delete event</button>' +
            '</div>' +
          '</form>' +
        '</details>' +
        (who ? '<p class="ops-meta"' + whoTitle + '>' + who + '</p>' : '');
      // Stash a modal record on the node for the delegated "Details" handler.
      var mrec = {{}};
      for (var mk in mev) {{ if (Object.prototype.hasOwnProperty.call(mev, mk)) mrec[mk] = mev[mk]; }}
      mrec.workflow_status = mev.status || null;
      mrec.stage_tags = manualStages;
      // Editing context for the modal's quick-actions / Edit Event button.
      mrec._table = 'manual_events'; mrec._key = mev.id;
      card._modalRec = mrec;
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
        // Rename-into-existing guard: a fresh name must not collide with
        // another manual event or anything in the catalog.
        var dup = findDuplicate(patch.name, id);
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

      // Boolean toggles (saved-star + urgent + hidden chips)
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
      var regular = $opsGrid.querySelectorAll('.ops-card[data-kind="regular"]').length;
      var manual  = $opsGrid.querySelectorAll('.ops-card[data-kind="manual"]').length;
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
      btn.title = 'Click to filter by ' + label;
      btn.addEventListener('click', function () {{
        btn.classList.toggle('is-on');
        applyFilters();
      }});
      return btn;
    }}

    function buildExtraFilters() {{
      // Priority (static)
      var pri = document.getElementById('filter-priority');
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
      var trk = document.getElementById('filter-track');
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
    }}

    // Rebuild the Speakers row from the current data set. Called from
    // renderOps() so the chip list reflects who's actually assigned right
    // now (including changes that just synced in via realtime).
    function rebuildSpeakerFilter(stateRows, manualRows) {{
      var host = document.getElementById('filter-speaker');
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
        host.appendChild(_makeExtraChip(name, name));
      }});
      var clr = document.createElement('button');
      clr.type = 'button'; clr.className = 'extra-clear'; clr.textContent = 'Clear';
      clr.addEventListener('click', function () {{
        host.querySelectorAll('.extra-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
        applyFilters();
      }});
      host.appendChild(clr);
    }}

    // The new primary filter row: one chip per pipeline stage. Selecting
    // chips keeps any card carrying ANY of the chosen stages (OR).
    function buildStageFilters() {{
      var host = document.getElementById('stage-filters');
      if (!host || host.dataset.built === '1') return;
      var frag = document.createDocumentFragment();
      STAGE_TAGS.forEach(function (s) {{
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'stage-chip';
        btn.dataset.stage = s.key;
        btn.style.background = s.bg;
        btn.style.color = s.fg;
        btn.style.borderColor = s.bg;
        btn.textContent = s.key;
        btn.title = 'Filter by ' + s.key;
        btn.addEventListener('click', function () {{
          btn.classList.toggle('is-on');
          applyFilters();
        }});
        frag.appendChild(btn);
      }});
      var clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.className = 'clear-btn';
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', function () {{
        host.querySelectorAll('.stage-chip.is-on').forEach(function (b) {{ b.classList.remove('is-on'); }});
        applyFilters();
      }});
      frag.appendChild(clearBtn);
      host.appendChild(frag);
      host.dataset.built = '1';
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

    // Re-sort every .ops-card chronologically and (re)insert month dividers.
    // Cards keep their DOM nodes — we only move them — so wired handlers and
    // open <details> survive. Also (re)builds the Months dropdown list.
    function regroupOpsByMonth() {{
      if (!$opsGrid) return;
      Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-month-header'))
        .forEach(function (h) {{ if (h.parentNode) h.parentNode.removeChild(h); }});
      var cards = Array.prototype.slice.call($opsGrid.querySelectorAll('.ops-card'));
      if (!cards.length) {{ buildMonthsMenu([]); return; }}
      cards.sort(function (a, b) {{
        return (parseInt(a.dataset.sort || '99999999', 10)) - (parseInt(b.dataset.sort || '99999999', 10));
      }});
      var frag = document.createDocumentFragment();
      var curKey = null;
      var order = [];
      cards.forEach(function (card) {{
        var key = card.dataset.month || 'tbd';
        if (key !== curKey) {{
          curKey = key;
          order.push({{ key: key, label: card.dataset.monthLabel || 'Date TBD' }});
          frag.appendChild(buildOpsMonthHeader(key, card.dataset.monthLabel || 'Date TBD'));
        }}
        frag.appendChild(card);
      }});
      $opsGrid.appendChild(frag);
      buildMonthsMenu(order);
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

    // (Re)render the per-month checkbox list inside the Months dropdown.
    // A CHECKED box means the month is SHOWN; unchecked means collapsed.
    function buildMonthsMenu(order) {{
      var list = document.getElementById('ops-months-list');
      if (!list) return;
      if (!order || !order.length) {{
        list.innerHTML = '<p style="font-size:0.78rem;color:var(--ab-fg-3);padding:6px;margin:0;">No months yet</p>';
        return;
      }}
      list.innerHTML = order.map(function (m) {{
        var checked = opsCollapsedMonths[m.key] ? '' : ' checked';
        return '<label><input type="checkbox" data-month-toggle="' + escapeHtml(m.key) + '"' + checked + '>' +
               '<span>' + escapeHtml(m.label) + '</span>' +
               '<span class="mc-count" data-mc-count="' + escapeHtml(m.key) + '"></span></label>';
      }}).join('');
      Array.prototype.slice.call(list.querySelectorAll('input[data-month-toggle]')).forEach(function (cb) {{
        cb.addEventListener('change', function () {{
          opsCollapsedMonths[cb.getAttribute('data-month-toggle')] = !cb.checked;
          applyFilters();
        }});
      }});
    }}

    // Wire the Months dropdown button + Show all / Hide all (once).
    function wireMonthsMenu() {{
      var btn = document.getElementById('ops-months-btn');
      var menu = document.getElementById('ops-months-menu');
      if (!btn || !menu || btn.dataset.wired) return;
      btn.dataset.wired = '1';
      btn.addEventListener('click', function (e) {{
        e.stopPropagation();
        var open = menu.classList.toggle('open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      }});
      menu.addEventListener('click', function (e) {{ e.stopPropagation(); }});
      document.addEventListener('click', function () {{
        menu.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
      }});
      var allBtn  = document.getElementById('ops-months-all');
      var noneBtn = document.getElementById('ops-months-none');
      if (allBtn)  allBtn.addEventListener('click', function () {{ setAllMonths(false); }});
      if (noneBtn) noneBtn.addEventListener('click', function () {{ setAllMonths(true); }});
    }}

    function applyFilters() {{
      var $search  = document.getElementById('ops-search');
      var $region  = document.getElementById('ops-region');
      var $saved   = document.getElementById('ops-f-saved');
      var $urgent  = document.getElementById('ops-f-urgent');
      var $speaker = document.getElementById('ops-f-speaker');
      var $buyers  = document.getElementById('ops-f-buyers');
      var $meet    = document.getElementById('ops-f-meetings');
      var $worth   = document.getElementById('ops-f-worth');
      var $price   = document.getElementById('ops-price');
      var $past    = document.getElementById('ops-f-past');
      var $hidden  = document.getElementById('ops-f-hidden');
      if (!$search || !$opsGrid) return;
      var q = ($search.value || '').toLowerCase().trim();
      var rg = $region ? ($region.value || '') : '';
      var fSaved   = !!($saved && $saved.checked);
      var fUrgent  = !!($urgent && $urgent.checked);
      var fSpeaker = !!($speaker && $speaker.checked);
      var fBuyers  = !!($buyers && $buyers.checked);
      var fMeet    = !!($meet && $meet.checked);
      var fWorth   = !!($worth && $worth.checked);
      var fPrice   = $price ? ($price.value || '') : '';
      var showPast   = !!($past && $past.checked);
      var showHidden = !!($hidden && $hidden.checked);
      // Toggle has-active classes for chip styling
      [['ops-f-saved',$saved],['ops-f-urgent',$urgent],['ops-f-speaker',$speaker],['ops-f-buyers',$buyers],['ops-f-meetings',$meet],['ops-f-worth',$worth],['ops-f-past',$past],['ops-f-hidden',$hidden]].forEach(function (pair) {{
        var inp = pair[1]; if (!inp) return;
        var lbl = inp.closest('.ops-filter-chip');
        if (lbl) lbl.classList.toggle('has-active', inp.checked);
      }});
      // Pipeline-stage filter — keep a card if it carries ANY selected stage.
      var activeStages = Array.prototype.map.call(
        document.querySelectorAll('#stage-filters .stage-chip.is-on'),
        function (b) {{ return b.dataset.stage; }}
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

      var shown = 0;
      var monthMatched = {{}};
      $opsGrid.querySelectorAll('.ops-card').forEach(function (card) {{
        var on = true;
        if (q && (card.textContent || '').toLowerCase().indexOf(q) === -1) on = false;
        if (rg && card.dataset.region !== rg) on = false;
        if (fSaved && !card.classList.contains('is-saved'))  on = false;
        if (fUrgent && !card.classList.contains('is-urgent')) on = false;
        if (fSpeaker && card.dataset.hasSpeaker !== '1')       on = false;
        if (fBuyers && (card.dataset.audience || '').toLowerCase().indexOf('buyer') === -1) on = false;
        if (fMeet && card.dataset.meetings !== '1') on = false;
        if (fWorth && (card.dataset.attend || '').toLowerCase().indexOf('worth attending') !== 0) on = false;
        if (fPrice) {{
          var pn = card.dataset.price === '' || card.dataset.price == null ? null : parseFloat(card.dataset.price);
          if (fPrice === 'known'        && pn == null)               on = false;
          if (fPrice === 'free'         && pn !== 0)                 on = false;
          if (fPrice === 'lt1000'       && !(pn != null && pn > 0 && pn < 1000)) on = false;
          if (fPrice === '1000-2500'    && !(pn != null && pn >= 1000 && pn < 2500)) on = false;
          if (fPrice === 'gte2500'      && !(pn != null && pn >= 2500)) on = false;
        }}
        if (!showPast && card.dataset.past === '1') on = false;
        if (!showHidden && card.classList.contains('is-hidden')) on = false;
        // Top stat-tile filter (one click on a stat shows only those events).
        if (opsStatFilter) {{
          var tagsS = (card.dataset.statusTags || '');
          if (opsStatFilter === 'saved'   && !card.classList.contains('is-saved'))  on = false;
          if (opsStatFilter === 'urgent'  && !card.classList.contains('is-urgent')) on = false;
          if (opsStatFilter === 'pipeline'&& !tagsS) on = false;
          if (opsStatFilter === 'booked'  && tagsS.split('|').indexOf('Booked') === -1) on = false;
          if (opsStatFilter === 'buyer'   && (card.dataset.audience || '').toLowerCase().indexOf('buyer') === -1) on = false;
          if (opsStatFilter === 'worth'   && (card.dataset.attend || '').toLowerCase().indexOf('worth attending') !== 0) on = false;
        }}
        if (activeStages.length > 0) {{
          var cardStages = (card.dataset.statusTags || '').split('|').filter(Boolean);
          var stageHit = activeStages.some(function (a) {{ return cardStages.indexOf(a) !== -1; }});
          if (!stageHit) on = false;
        }}
        if (activeStatuses.length   > 0 && activeStatuses.indexOf(card.dataset.status   || '') === -1) on = false;
        if (activePriorities.length > 0 && activePriorities.indexOf(card.dataset.priority || '') === -1) on = false;
        if (activeTracks.length     > 0 && activeTracks.indexOf(card.dataset.track     || '') === -1) on = false;
        // Speakers — the card's speaker field may carry multiple names
        // ("Thor, Verma"). Treat ANY token-level overlap as a match.
        if (activeSpeakers.length > 0) {{
          var sp = (card.dataset.speaker || '').toLowerCase();
          if (!sp) {{
            on = false;
          }} else {{
            var tokens = sp.split(/[,;/&]| and |\\bplus\\b/i).map(function (s) {{ return s.trim(); }}).filter(Boolean);
            var hit = activeSpeakers.some(function (a) {{ return tokens.indexOf(a) !== -1; }});
            if (!hit) on = false;
          }}
        }}
        // Collapsing a month is a view convenience, not a filter: a card that
        // passes the filters still counts toward "shown" even when its month
        // is folded — we only hide it from view.
        var mkey = card.dataset.month || 'tbd';
        if (on) {{ monthMatched[mkey] = (monthMatched[mkey] || 0) + 1; shown++; }}
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
      // Keep the Months dropdown in sync: checkbox checked = month shown.
      Array.prototype.slice.call(document.querySelectorAll('#ops-months-list input[data-month-toggle]')).forEach(function (cb) {{
        cb.checked = !opsCollapsedMonths[cb.getAttribute('data-month-toggle')];
      }});
      Array.prototype.slice.call(document.querySelectorAll('#ops-months-list [data-mc-count]')).forEach(function (sp) {{
        sp.textContent = (monthMatched[sp.getAttribute('data-mc-count')] || 0);
      }});
      var $shown = document.getElementById('ops-shown');
      if ($shown) $shown.textContent = 'Showing ' + shown + ' of ' + $opsGrid.querySelectorAll('.ops-card').length;
      // The map mirrors the grid's filters — keep its pins in sync.
      if (currentView === 'map' && _opsMapLayer) renderOpsMap();
    }}

    function wireFilters() {{
      ['ops-search','ops-region','ops-price','ops-f-saved','ops-f-urgent','ops-f-speaker','ops-f-buyers','ops-f-meetings','ops-f-worth','ops-f-past','ops-f-hidden'].forEach(function (id) {{
        var el = document.getElementById(id); if (!el) return;
        if (el.dataset.wired) return;
        el.dataset.wired = '1';
        var ev = (el.tagName === 'INPUT' && el.type !== 'checkbox') ? 'input' : 'change';
        el.addEventListener(ev, applyFilters);
      }});
    }}

    function renderStats(evs, stateRows, manualRows) {{
      var $stats = document.getElementById('ops-stats');
      if (!$stats) return;
      // The "Upcoming" headline excludes events that already happened.
      var total = (evs || []).filter(function (e) {{ return !isPastEvent(e); }}).length +
                  (manualRows || []).filter(function (m) {{ return !isPastEvent(m); }}).length;
      var stByNum = {{}};
      (stateRows || []).forEach(function (r) {{ stByNum[r.event_num] = r; }});
      var saved = 0, urgent = 0, inPipeline = 0, booked = 0;
      var buyerRich = 0, worthIt = 0;
      (stateRows || []).forEach(function (r) {{
        if (r.saved)  saved++;
        var stages = stageTagsOf(r);
        if (stages.length) inPipeline++;
        if (stages.indexOf('Booked') !== -1) booked++;
        if ((r.attend_verdict || '').indexOf('Worth') === 0) worthIt++;
      }});
      // Urgent = an apply/CFP deadline closing soon (or a manually-flagged
      // urgent event) — NOT merely an upcoming event. Counted per event.
      (evs || []).forEach(function (ev) {{
        if (((ev.audience_type || '').toLowerCase()).indexOf('buyer') !== -1) buyerRich++;
        var st = stByNum[ev.num] || {{}};
        if (!isPastEvent(ev) && (st.urgent || isDeadlineSoon(ev.deadline))) urgent++;
      }});
      // Manual events carry their own stage tags + deadlines — fold them in.
      (manualRows || []).forEach(function (m) {{
        var stages = stageTagsOf(m);
        if (stages.length) inPipeline++;
        if (stages.indexOf('Booked') !== -1) booked++;
        if (((m.audience_type || '').toLowerCase()).indexOf('buyer') !== -1) buyerRich++;
        if ((m.attend_verdict || '').indexOf('Worth') === 0) worthIt++;
        if (!isPastEvent(m) && isDeadlineSoon(m.deadline)) urgent++;
      }});
      // Each tile is a one-click filter (data-stat). 'all' clears everything.
      function tile(key, num, label, cls) {{
        var on = opsStatFilter === key ? ' is-activestat' : '';
        return '<button type="button" class="ops-stat' + (cls ? ' ' + cls : '') + on +
          '" data-stat="' + key + '"><span class="num">' + num +
          '</span><span class="lbl">' + label + '</span></button>';
      }}
      $stats.innerHTML =
        tile('all', total, 'Upcoming', '') +
        tile('saved', saved, 'Saved', 'saved') +
        tile('urgent', urgent, 'Urgent', 'urgent') +
        tile('pipeline', inPipeline, 'In pipeline', '') +
        tile('booked', booked, 'Booked', '') +
        tile('buyer', buyerRich, 'Buyer-rich', '') +
        tile('worth', worthIt, 'Worth attending', '');
      $stats.removeAttribute('hidden');
      Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (t) {{
        t.addEventListener('click', function () {{
          var k = t.dataset.stat;
          opsStatFilter = (k === 'all' || opsStatFilter === k) ? '' : k;
          applyFilters();
          // Reflect the active tile without a full re-render.
          Array.prototype.forEach.call($stats.querySelectorAll('[data-stat]'), function (x) {{
            x.classList.toggle('is-activestat', x.dataset.stat === opsStatFilter);
          }});
        }});
      }});
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
        fetch('events.json').then(function (r) {{ return r.json(); }}),
        sb.from('event_state').select('*'),
        sb.from('manual_events').select('*').order('created_at', {{ ascending: false }})
      ]).then(function (results) {{
        var data = results[0];
        var stateRows = (results[1] && results[1].data) || [];
        var manualRows = (results[2] && results[2].data) || [];
        var stateMap = {{}};
        stateRows.forEach(function (r) {{ stateMap[r.event_num] = r; }});

        var evs = (data.events || []).filter(function (e) {{ return e.status !== 'archived'; }});
        $opsGrid.innerHTML = '';
        evs.forEach(function (ev) {{
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
        regroupOpsByMonth();
        wireMonthsMenu();
        applyFilters();
        // Rebuild the dedup index from this fresh fetch — realtime
        // events from other tabs / sessions land here, so we want every
        // re-render to refresh _knownNames too.
        _knownNameSource = {{}};
        (data.events || []).forEach(function (e) {{ var n = (e.name || '').toLowerCase().trim(); if (n) _knownNameSource[n] = 'catalog'; }});
        manualRows.forEach(function (m) {{ var n = (m.name || '').toLowerCase().trim(); if (n) _knownNameSource[n] = 'manual:' + m.id; }});
        _knownNames = Object.keys(_knownNameSource);
        // Mirror into the calendar view (uses the same data set)
        renderCalendar(evs, stateMap, manualRows);
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
        new RegExp('(?:' + months + ')\\s+\\d{{1,2}}\\s*[–—-]\\s*(?:(?:' + months + ')\\s+)?\\d{{1,2}},\\s+\\d{{4}}', 'i'),
        new RegExp('(?:' + months + ')\\s+\\d{{1,2}},\\s+\\d{{4}}', 'i'),
        new RegExp('(?:' + monthsShort + ')\\s+\\d{{1,2}}\\s*[–—-]\\s*\\d{{1,2}},\\s+\\d{{4}}', 'i'),
        new RegExp('(?:' + monthsShort + ')\\s+\\d{{1,2}},\\s+\\d{{4}}', 'i')
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
        if (/(usa|united states|canada|mexico|brazil|new york|san francisco|los angeles|chicago|boston|seattle|austin|miami|toronto|vancouver)/.test(lo)) out.region = 'Americas';
        else if (/(uk|united kingdom|london|paris|berlin|amsterdam|madrid|barcelona|lisbon|munich|zurich|brussels|dublin|stockholm|copenhagen|oslo)/.test(lo)) out.region = 'Europe';
        else if (/(singapore|hong kong|tokyo|seoul|shanghai|beijing|sydney|melbourne|delhi|mumbai|bangalore)/.test(lo)) out.region = 'Asia-Pacific';
        else if (/(dubai|abu dhabi|riyadh|doha|tel aviv|cairo)/.test(lo)) out.region = 'MENA';
      }}
      return out;
    }}

    // Apply extracted fields to the form (only fills empty inputs by default)
    function applyExtractToForm(form, extracted, opts) {{
      opts = opts || {{}};
      var keys = ['name', 'date_str', 'location', 'region', 'url'];
      var filled = 0, skipped = 0;
      keys.forEach(function (k) {{
        var el = form.querySelector('[name="' + k + '"]');
        if (!el) return;
        if (!extracted[k]) return;
        if (el.value && !opts.overwrite) {{ skipped++; return; }}
        el.value = extracted[k];
        filled++;
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
              '<textarea id="paste-email-text" placeholder="Paste the full email or web event listing text. We\\u2019ll auto-fill name, date, location, region, and URL." style="min-height:120px;"></textarea>' +
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
          '<input type="text" name="date_str" placeholder="Optional · e.g. September 12, 2026 or September 10–12, 2026">' +
        '</label>' +
        '<div class="row">' +
          '<label><span class="key">Location</span>' +
            '<input type="text" name="location" placeholder="City, Country">' +
          '</label>' +
          '<label><span class="key">Region</span>' +
            '<select name="region">' +
              optionRows(['', 'Americas', 'Europe', 'Asia-Pacific', 'MENA', 'Global'], '') +
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
        '<label><span class="key">Pipeline stages</span>' +
          stageCheckboxes([], 'status_tags') +
        '</label>' +
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
    // ── Strip-and-retry around not-yet-migrated columns ────────────────
    // pricing / audience_type were added 2026-06. If this DB hasn't run the
    // migration yet, PostgREST rejects the whole write. We detect that, drop
    // the offending column, and retry so the save still lands (the buyer/price
    // fields just stay blank until the migration runs).
    var MIGRATION_COLS = ['pricing', 'audience_type', 'past_speakers',
                          'meeting_formats', 'attend_verdict', 'postmortem'];
    function unknownMigrationCol(err) {{
      if (!err) return null;
      var msg = ((err.message || '') + ' ' + (err.details || '')).toLowerCase();
      var code = String(err.code || '');
      if (code !== 'PGRST204' && code !== '42703' && msg.indexOf('column') === -1) return null;
      for (var i = 0; i < MIGRATION_COLS.length; i++) {{
        var c = MIGRATION_COLS[i];
        if (msg.indexOf("'" + c + "'") !== -1 || msg.indexOf('"' + c + '"') !== -1 ||
            msg.indexOf(' ' + c + ' ') !== -1) return c;
      }}
      return null;
    }}
    // runFn(payload) -> a Supabase thenable resolving to {{data, error}}.
    // The final resp carries strippedMigrationCols so callers can warn that
    // those values were NOT saved (DB migration still pending).
    function sbWriteRetry(payload, runFn, _stripped) {{
      _stripped = _stripped || [];
      return runFn(payload).then(function (resp) {{
        var col = unknownMigrationCol(resp.error);
        if (col && Object.prototype.hasOwnProperty.call(payload, col)) {{
          var p2 = {{}};
          for (var k in payload) {{ if (k !== col && Object.prototype.hasOwnProperty.call(payload, k)) p2[k] = payload[k]; }}
          return sbWriteRetry(p2, runFn, _stripped.concat([col]));
        }}
        if (_stripped.length) resp.strippedMigrationCols = _stripped;
        return resp;
      }});
    }}

    function loadKnownNames() {{
      var p1 = fetch('events.json').then(function (r) {{ return r.json(); }}).then(function (d) {{
        return ((d && d.events) || []).map(function (e) {{ return (e.name || '').toLowerCase().trim(); }});
      }}).catch(function () {{ return []; }});
      var p2 = sb.from('manual_events').select('id,name').then(function (r) {{
        return ((r && r.data) || []).map(function (e) {{ return [(e.name || '').toLowerCase().trim(), e.id]; }});
      }});
      return Promise.all([p1, p2]).then(function (a) {{
        _knownNameSource = {{}};
        a[0].forEach(function (n) {{ if (n) _knownNameSource[n] = 'catalog'; }});
        a[1].forEach(function (pair) {{ if (pair[0]) _knownNameSource[pair[0]] = 'manual:' + pair[1]; }});
        _knownNames = Object.keys(_knownNameSource);
        return _knownNames;
      }});
    }}
    // Returns null if name is fine, or an object describing the conflict.
    // selfId optional — when editing, ignores a match against the row being edited.
    function findDuplicate(name, selfId) {{
      var n = (name || '').toLowerCase().trim();
      if (!n || !_knownNameSource) return null;
      var src = _knownNameSource[n];
      if (!src) return null;
      if (selfId && src === 'manual:' + selfId) return null;
      return {{ name_lower: n, source: src }};
    }}
    function isDuplicateName(name, selfId) {{ return !!findDuplicate(name, selfId); }}

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
          fillMeta.textContent = 'Fetching page via Exa.ai, then asking the Dust agent to structure it. Usually 10\\u201340 seconds.';
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
                var why = data.degraded_reason === 'dust_rate_limited'
                  ? 'Dust hit its rate limit — used the scraped page directly with basic extraction. Please double-check the fields.'
                  : data.degraded_reason === 'dust_timeout'
                    ? 'Dust took too long — used the scraped page directly with basic extraction. Please double-check the fields.'
                    : 'Dust unavailable — used the scraped page directly with basic extraction. Please double-check the fields.';
                note += ' ' + why;
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
        if (text.trim().length < 10) {{ meta.textContent = 'Nothing to extract from yet.'; return; }}
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
        // Date is optional — fall back to "Date TBD" since the schema column
        // is NOT NULL. start_date / end_date stay null and the iCal feed will
        // skip the event until a real date is filled in.
        if (!row.date_str) row.date_str = 'Date TBD';
        // Derive start_date + end_date from date_str so the row is calendar-ready
        // (used by both the in-app calendar view and the public iCal feed).
        var derived = deriveDatesFromText(row.date_str);
        if (derived.start_date) row.start_date = derived.start_date;
        if (derived.end_date)   row.end_date   = derived.end_date;
        // HARD duplicate-name guard — case-insensitive across catalog + manual_events.
        // No confirm() escape hatch: duplicates land in the calendar as two
        // separate entries with two UIDs, which produces double-rendered
        // events in subscribed calendars. The unique index on the DB
        // (scripts/2026-05-26_dedup_manual_events.sql) is the final defense.
        var dup = findDuplicate(row.name);
        if (dup) {{
          var srcLabel = dup.source === 'catalog'
            ? 'the public ArcticBlue catalog (events.json)'
            : 'manual events';
          alert('"' + row.name + '" already exists in ' + srcLabel + '. Use the existing entry instead of adding a duplicate.');
          return;
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
          flashOk('Event added');
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
      (events || []).forEach(function (ev) {{
        var st = stateMap[ev.num];
        if (!st || !st.saved) return;
        pushEvent(ev, st, 'event-' + ev.num + '@arcticblue-event-tracker');
      }});
      // Manual events: include all of them (since adding manually is a saved-intent action)
      (manualEvents || []).forEach(function (mev) {{
        if (!mev.start_date) return;
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

    function setView(name) {{
      if (name !== 'grid' && name !== 'calendar' && name !== 'map') name = 'grid';
      currentView = name;
      document.querySelectorAll('.view-toggle button[data-view]').forEach(function (b) {{
        var on = b.dataset.view === name;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      }});
      var g = document.getElementById('ops-grid');
      var c = document.getElementById('ops-calendar');
      var m = document.getElementById('ops-map');
      if (g) g.style.display = (name === 'grid') ? '' : 'none';
      if (c) c.classList.toggle('show', name === 'calendar');
      if (m) m.classList.toggle('show', name === 'map');
      if (name === 'map') openOpsMap();
      try {{ localStorage.setItem(VIEW_KEY, name); }} catch (e) {{}}
    }}

    function wireViewToggle() {{
      document.querySelectorAll('.view-toggle button[data-view]').forEach(function (b) {{
        // Clone-replace to avoid duplicate listeners on re-route
        var fresh = b.cloneNode(true);
        b.parentNode.replaceChild(fresh, b);
        fresh.addEventListener('click', function () {{ setView(fresh.dataset.view); }});
      }});
      try {{
        var saved = localStorage.getItem(VIEW_KEY);
        if (saved === 'grid' || saved === 'calendar' || saved === 'map') setView(saved);
      }} catch (e) {{}}
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
      ['london', 51.5074, -0.1278]
    ];

    function geoOf(rec) {{
      var hay = ((rec.city || '') + ' ' + (rec.venue || '') + ' ' +
                 (rec.location || '')).toLowerCase();
      if (!hay.trim()) return null;
      for (var i = 0; i < CITY_COORDS.length; i++) {{
        if (hay.indexOf(CITY_COORDS[i][0]) !== -1) {{
          return [CITY_COORDS[i][1], CITY_COORDS[i][2]];
        }}
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
      var unplaced = 0, placed = 0;
      $opsGrid.querySelectorAll('.ops-card').forEach(function (card) {{
        if (card.style.display === 'none') return;  // filtered out
        var rec = card._modalRec || {{}};
        var ll = geoOf(rec);
        if (!ll) {{ unplaced++; return; }}
        placed++;
        var key = ll[0].toFixed(3) + ',' + ll[1].toFixed(3);
        (byCoord[key] = byCoord[key] || {{ ll: ll, evs: [] }}).evs.push(rec);
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
          html: '<div class="map-pin' + (n === 1 ? ' single' : '') + '">' +
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
          (unplaced ? ' · ' + unplaced + ' without a mappable location (Remote / TBD / Podcast)' : '') +
          ' — pins follow the filters above; click a pin to list its events.';
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
      var evs = g.evs.slice().sort(function (a, b) {{
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
        row.className = 'map-sb-ev';
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
      'Americas':     '#2773c2',
      'Europe':       '#7c3aed',
      'Asia-Pacific': '#059669',
      'MENA':         '#ca8a04',
      'Global':       '#475569'
    }};

    function regionColor(r) {{ return REGION_COLORS[r] || '#737373'; }}

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

      var head = document.createElement('h3');
      head.className = 'calendar-month-head';
      head.textContent = new Date(year, month, 1).toLocaleString('en-US', {{ month: 'long', year: 'numeric' }});
      monthDiv.appendChild(head);

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
          ? {{ status_tags: ev._manualStatusTags, speaker: ev._manualSpeaker }}
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

        weekSpans.forEach(function (ws) {{
          var ev = ws.sp.ev, st = ws.sp.st;
          var bar = document.createElement('div');
          bar.className = 'cal-evt';
          if (st.saved) bar.classList.add('is-saved');
          if (st.urgent || isDeadlineSoon(ev.deadline)) bar.classList.add('is-urgent');
          bar.dataset.eventNum = ev.num;
          bar.style.gridColumn = (ws.startCol + 1) + ' / span ' + ws.span;
          bar.style.gridRow = (ws.lane + 2);
          var calStages = stageTagsOf(st);
          var topStage = mostAdvancedStage(calStages);
          var grpDot = topStage ? stageDot(topStage) : null;
          var spanBg = (topStage && STAGE_BY_KEY[topStage]) ? STAGE_BY_KEY[topStage].bg : null;
          if (spanBg) bar.style.background = spanBg;
          bar.style.borderLeftColor = grpDot || regionColor(ev.region);
          var sp2 = st.speaker || '';
          var ini = sp2 ? initials(sp2) : '';
          var statusInline = '';
          if (topStage && STAGE_BY_KEY[topStage]) {{
            var s = STAGE_BY_KEY[topStage];
            var extra = calStages.length > 1 ? ' +' + (calStages.length - 1) : '';
            statusInline = '<span class="cal-evt-status" style="background:' + s.bg + ';color:' + s.fg + ';">' + escapeHtml(topStage) + extra + '</span>';
          }}
          bar.innerHTML =
            '<span class="cal-region-dot" style="background:' + regionColor(ev.region) + ';"></span>' +
            '<span class="cal-evt-name">' + escapeHtml(ev.name) + '</span>' +
            (ini ? '<span class="cal-chip-initial" title="' + escapeHtml(sp2) + '">' + escapeHtml(ini) + '</span>' : '') +
            statusInline;
          bar.title = ev.name +
            (sp2 ? ' · Speaker: ' + sp2 : '') +
            (ev.location ? ' · ' + ev.location : '') +
            (calStages.length ? ' · ' + calStages.join(', ') : '') +
            (ev.end_date && ev.end_date !== ev.start_date ? ' · ' + ev.start_date + ' to ' + ev.end_date : '');
          bar.addEventListener('click', function () {{ onChipClick(ev.num); }});
          weekDiv.appendChild(bar);
        }});

        grid.appendChild(weekDiv);
      }}

      monthDiv.appendChild(grid);
      return monthDiv;
    }}

    function renderCalendar(events, stateMap, manualEvents) {{
      var cal = document.getElementById('ops-calendar');
      if (!cal) return;
      cal.innerHTML = '';

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
          _manualSpeaker:    m.speaker || ''
        }});
      }});

      // Determine month range
      var earliest = null, latest = null;
      combined.forEach(function (ev) {{
        if (!ev.start_date) return;
        var d = new Date(ev.start_date);
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

      // Default: current month if it's in range, else first month with events
      var todayKey = new Date().getFullYear() + '-' + String(new Date().getMonth() + 1).padStart(2, '0');
      var savedKey = null;
      try {{ savedKey = localStorage.getItem('ab.calendar.month'); }} catch (e) {{}}
      var defaultKey = savedKey && months.some(function (x) {{ return x.key === savedKey; }})
        ? savedKey
        : (months.some(function (x) {{ return x.key === todayKey; }}) ? todayKey : months[0].key);

      // Count events per month for the dropdown label
      var byMonth = {{}};
      combined.forEach(function (ev) {{
        var sd = ev.start_date; if (!sd) return;
        var k = sd.slice(0, 7);
        byMonth[k] = (byMonth[k] || 0) + 1;
      }});

      // Build dropdown
      var headerWrap = document.createElement('div');
      headerWrap.style.cssText = 'display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:18px;';
      headerWrap.innerHTML =
        '<label style="display:flex;align-items:center;gap:8px;font-family:var(--ab-mono);font-size:0.74rem;color:var(--ab-fg-3);letter-spacing:0.06em;text-transform:uppercase;">' +
          'Month' +
          '<select id="cal-month-select" style="font-family:var(--ab-sans);font-size:0.95rem;padding:8px 12px;border:1px solid var(--ab-rule-strong);border-radius:6px;background:var(--ab-bg);color:var(--ab-fg);">' +
            months.map(function (m) {{
              var label = new Date(m.y, m.m, 1).toLocaleString('en-US', {{ month: 'long', year: 'numeric' }});
              var n = byMonth[m.key] || 0;
              var suffix = n ? '  (' + n + ' event' + (n === 1 ? '' : 's') + ')' : '  (0)';
              return '<option value="' + m.key + '"' + (m.key === defaultKey ? ' selected' : '') + '>' + escapeHtml(label) + escapeHtml(suffix) + '</option>';
            }}).join('') +
          '</select>' +
        '</label>' +
        '<button type="button" id="cal-prev" class="add-btn">‹ Prev</button>' +
        '<button type="button" id="cal-next" class="add-btn">Next ›</button>';
      cal.appendChild(headerWrap);

      var monthHost = document.createElement('div');
      monthHost.id = 'cal-month-host';
      cal.appendChild(monthHost);

      // Legend: one row of color dots showing status-group meanings
      var legend = document.createElement('div');
      legend.className = 'cal-legend';
      legend.innerHTML =
        '<span class="cal-legend-label">Pipeline stages:</span>' +
        STAGE_TAGS.map(function (g) {{
          return '<span class="cal-legend-item"><span class="cal-legend-dot" style="background:' + g.dot + ';"></span>' + escapeHtml(g.key) + '</span>';
        }}).join('');
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
        try {{ localStorage.setItem('ab.calendar.month', match.key); }} catch (e) {{}}
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
      // 5. "M/D - D" (same month) with optional year
      var n2 = s.match(/(\\d{{1,2}})\\/(\\d{{1,2}})(?:\\/(\\d{{2,4}}))?\\s*[–—-]\\s*(\\d{{1,2}})(?!\\d*\\/)/);
      if (n2) {{
        var c1 = parseInt(n2[1], 10), c2 = parseInt(n2[2], 10), c3 = parseInt(n2[4], 10);
        if (okMD(c1, c2) && c3 >= 1 && c3 <= 31) {{
          var yc = yr(n2[3]) || inferYear(c1, c2);
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
    var SEARCH_REGION_OPTIONS  = ['Americas', 'Europe', 'Asia-Pacific', 'MENA', 'Global'];

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
          'AI web search finds upcoming in-person events matching your criteria — buyer-rich audiences preferred. Added events are vetted and auto-enriched.' +
        '</p>' +
        '<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">' +
          '<label style="display:inline-flex;align-items:center;gap:8px;font-family:var(--ab-mono);font-size:0.7rem;letter-spacing:0.06em;text-transform:uppercase;color:var(--ab-fg-3);">' +
            'How many:' +
            '<input type="number" id="search-count" min="1" max="25" value="10" style="width:60px;padding:6px 8px;border:1px solid var(--ab-rule-strong);border-radius:6px;font-family:var(--ab-sans);font-size:0.9rem;">' +
          '</label>' +
        '</div>' +
        '<div class="extra-filters" style="margin-bottom:10px;">' +
          '<div class="extra-filter-group" id="search-types">' +
            '<span class="extra-filter-label">Types</span>' +
          '</div>' +
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

      var getTypes    = _multichip(panel.querySelector('#search-types'),    SEARCH_TYPE_OPTIONS,   ['Enterprise', 'Halo']);
      var getQuarters = _multichip(panel.querySelector('#search-quarters'), qOpts,                  qDefaults);
      var getRegions  = _multichip(panel.querySelector('#search-regions'),  SEARCH_REGION_OPTIONS,  []);

      panel.querySelector('#search-cancel-btn').addEventListener('click', function () {{ panel.remove(); }});

      panel.querySelector('#search-run-btn').addEventListener('click', function () {{
        var count = parseInt(panel.querySelector('#search-count').value, 10);
        if (!Number.isFinite(count) || count < 1) count = 10;
        if (count > 25) count = 25;
        var criteria = {{ count: count, types: getTypes(), quarters: getQuarters(), regions: getRegions() }};
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
        var dup = isDuplicateName(ev.name) ? '<span class="ops-tag" style="background:#fef2f2;color:#7f1d1d;border:1px solid #fecaca;">Already in tracker</span>' : '';
        return (
          '<div class="search-result" data-idx="' + idx + '" style="border:1px solid var(--ab-rule);border-radius:8px;padding:14px;margin-bottom:10px;background:var(--ab-bg);">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:6px;flex-wrap:wrap;">' +
              '<div style="flex:1;min-width:0;">' +
                '<h4 style="margin:0;font-size:1.02rem;font-weight:700;letter-spacing:-0.01em;color:var(--ab-fg);">' + escapeHtml(ev.name || '(unnamed)') + url + '</h4>' +
                '<p style="margin:4px 0 0;font-size:0.85rem;color:var(--ab-fg-2);">' +
                  escapeHtml(ev.date_str || '') + ' · ' + escapeHtml(ev.region || '') + (ev.location ? ' · ' + escapeHtml(ev.location) : '') +
                  (ev.type ? ' · ' + escapeHtml(ev.type) : '') +
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
        if (isDuplicateName(ev.name)) return Promise.resolve({{ ok: false, reason: 'duplicate' }});
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
        if (c.audience && /buyer/i.test(c.audience))
          tags.push('<span class="ac-tag buyer">Buyer-rich</span>');
        if (c.attend && /worth/i.test(c.attend))
          tags.push('<span class="ac-tag worth">Worth attending</span>');
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
      panel.innerHTML =
        '<h3>Ask AI about your events</h3>' +
        '<p style="margin:0 0 12px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          'Answers come from this tracker\\u2019s own data \\u2014 statuses, dates, audience, verdicts and all.</p>' +
        '<div class="ask-log" id="ask-log"></div>' +
        '<div class="ask-examples" id="ask-examples">' +
          ['Which events should I attend in September?',
           'What\\u2019s booked for Thor?',
           'Best buyer-rich events in Q4?',
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
          var m = addMsg('ai', _mdToHtml(h.content) + _askCardsHtml(h.cards), true);
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
          body: JSON.stringify({{ question: q, history: _askHistory.slice(0, -1) }})
        }}).then(function (r) {{ return r.json().then(function (j) {{ return [r.status, j]; }}); }})
          .then(function (pair) {{
            sendBtn.disabled = false; sendBtn.textContent = 'Ask';
            var st = pair[0], data = pair[1];
            if (st !== 200 || !data.answer) {{
              thinking.textContent = 'Sorry \\u2014 ' + ((data && data.error) || 'the assistant is unavailable right now.');
              return;
            }}
            thinking.innerHTML = _mdToHtml(data.answer) + _askCardsHtml(data.cards);
            _wireAskCards(thinking);
            log.scrollTop = log.scrollHeight;
            _askHistory.push({{ role: 'assistant', content: data.answer, cards: data.cards || [] }});
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
      try {{ localStorage.setItem('ab.collab.name', n); }} catch (e) {{}}
      if ($opsEmail) $opsEmail.textContent = n || 'Team';
    }}
    function ensureCollabName() {{
      var n = getCollabName();
      if (!n) {{
        n = (window.prompt('Your name (so teammates can see who edited what):', '') || '').trim();
        setCollabName(n);
      }}
      if ($opsEmail) $opsEmail.textContent = n || 'Team';
      return n || 'Team';
    }}

    // ── Bridge for the detail modal (which lives in a separate closure) ──
    // The modal's quick-action buttons + "Edit Event" call these. opsWrite
    // routes a patch to the right table; opsOpenEditor expands the source
    // card's full edit form.
    var _STAGE_ORDER = ['Identified', 'Submitted', 'Meeting held', 'Booked', 'Declined'];
    window.opsStageOrder = _STAGE_ORDER;
    window.opsWrite = function (table, key, patch) {{
      var who = getCollabName() || 'Team';
      patch.updated_by = who;
      var run;
      if (table === 'manual_events') {{
        run = sbWriteRetry(patch, function (p) {{ return sb.from('manual_events').update(p).eq('id', key); }});
      }} else {{
        var pp = dict_assign({{ event_num: key }}, patch);
        run = sbWriteRetry(pp, function (p) {{ return sb.from('event_state').upsert(p, {{ onConflict: 'event_num' }}); }});
      }}
      return run.then(function (resp) {{
        if (resp && resp.error) {{ status('Save failed: ' + resp.error.message, 'error'); }}
        else {{ flashOk('Saved'); renderOps(who); }}
        return resp;
      }});
    }};
    function dict_assign(a, b) {{ for (var k in b) {{ if (Object.prototype.hasOwnProperty.call(b, k)) a[k] = b[k]; }} return a; }}
    window.opsOpenEditor = function (table, key) {{
      if (window.closeEventModal) window.closeEventModal();
      if (typeof currentView !== 'undefined' && currentView !== 'grid') setView('grid');
      setTimeout(function () {{
        var sel = table === 'manual_events'
          ? '.ops-card[data-manual-id="' + key + '"]'
          : '.ops-card[data-event-num="' + key + '"]';
        var card = $opsGrid.querySelector(sel);
        if (card) {{
          var ed = card.querySelector('details.ops-edit');
          if (ed) ed.open = true;
          card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        }}
      }}, 70);
    }};

    // route() — no auth. Always show the collaborative tracker.
    function route() {{
      var who = getCollabName() || 'Team';
      if ($opsEmail) $opsEmail.textContent = who;
      showOnly($ops);
      wireViewToggle();
      wireFilters();
      buildStageFilters();
      buildStatusFilters();
      buildExtraFilters();
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

    var $changeName = document.getElementById('change-name');
    if ($changeName) {{
      $changeName.addEventListener('click', function () {{
        var cur = getCollabName();
        var n = (window.prompt('Your name:', cur) || '').trim();
        if (n) setCollabName(n);
      }});
    }}

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
        'generated_at':   datetime.utcnow().isoformat() + 'Z',
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

    now_iso = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')

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
    for ev in (today_evs + upcoming):
        st = state_by_num.get(ev.get('num'))
        if not st or not st.get('saved'):
            continue
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
