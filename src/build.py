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

# Date the build "thinks" today is. Set to date.today() once the build is on
# a daily cron. Hardcoded for reproducible local builds.
TODAY = date(2026, 5, 21)

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
    events = []
    for r in raw:
        events.append({
            'num':           r.get('num'),
            'name':          r.get('name', ''),
            'date_str':      r.get('date_str', ''),
            'location':      r.get('location', ''),
            'type':          r.get('type', ''),
            'priority':      r.get('priority', ''),
            'priority_full': r.get('priority_full', r.get('priority', '')),
            'why':           r.get('why', ''),
        })
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
        start, end = parse_date(ev['date_str'])
        if not start:
            ev['_parse_failed'] = True
            upcoming.append(ev)  # fail safe
            continue
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
    # Verified URL from the source doc (no invented URLs)
    url = EVENT_URLS.get(str(ev.get('num', '')))
    if url:
        # Whole card is a clickable link; opens in new tab
        wrap_open = f'<a class="event-link" href="{e(url)}" target="_blank" rel="noopener" aria-label="Open {e(ev["name"])} in a new tab">'
        wrap_close = '</a>'
        link_indicator = '<span class="event-link-arrow" aria-hidden="true">↗</span>'
        extra_class += ' has-link'
    else:
        wrap_open = ''
        wrap_close = ''
        link_indicator = '<span class="event-no-link" title="No verified URL on file for this event">·</span>'
    return f'''
    {wrap_open}<article class="event{extra_class}"
             data-priority="{e(priority_label)}"
             data-region="{e(region)}"
             data-type="{e(typ)}">
      <header class="event-head">
        <p class="event-date">{e(fmt_date(ev))}</p>
        <span class="badge {pc}">{e(priority_label)}</span>
      </header>
      <h3 class="event-name">{e(ev['name'])} {link_indicator}</h3>
      <p class="event-loc"><span class="event-region">{e(region)}</span> · {e(ev['location'])}</p>
      {f'<p class="event-why">{e(why)}</p>' if why else ''}
      <footer class="event-foot">
        <span class="event-type">{e(typ)}</span>
      </footer>
    </article>{wrap_close}'''


def build():
    events = parse_events()
    today_evs, upcoming, archived = classify(events)
    upcoming_count = len(upcoming)
    archived_count = len(archived)

    # Find the next single event
    next_up = upcoming[0] if upcoming else None

    # Render groups
    today_html = '\n'.join(render_event_card(ev) for ev in today_evs) if today_evs else ''
    upcoming_html = '\n'.join(render_event_card(ev) for ev in upcoming)
    archived_html = '\n'.join(render_event_card(ev, archived=True) for ev in archived)

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
    .event-name {{
      font-family: var(--ab-sans); font-size: 1.1rem; font-weight: 700;
      line-height: 1.25; margin: 0; color: var(--ab-fg); letter-spacing: -0.01em;
    }}
    .event-loc {{ font-size: 0.85rem; color: var(--ab-fg-3); margin: 0; }}
    .event-region {{ color: var(--ab-fg-2); font-weight: 500; }}
    .event-why {{ font-size: 0.85rem; color: var(--ab-fg-2); line-height: 1.5; margin: 4px 0 0; }}
    .event-foot {{ margin-top: auto; padding-top: 10px; border-top: 1px solid var(--ab-rule); }}
    .event-type {{
      font-family: var(--ab-mono); font-size: 0.68rem;
      color: var(--ab-fg-3); letter-spacing: 0.1em; text-transform: uppercase;
    }}
    .event.archived {{ opacity: 0.6; }}
    .event.archived:hover {{ opacity: 1; }}

    /* Whole-card links */
    a.event-link {{
      display: contents;
      color: inherit;
      text-decoration: none;
    }}
    a.event-link .event {{ cursor: pointer; }}
    a.event-link:hover .event.has-link {{ border-color: var(--ab-blue); }}
    .event-link-arrow {{
      display: inline-block; font-family: var(--ab-mono);
      font-size: 0.85rem; color: var(--ab-fg-3);
      transition: color 0.15s, transform 0.15s;
      margin-left: 4px;
      vertical-align: 1px;
    }}
    a.event-link:hover .event-link-arrow {{
      color: var(--ab-blue);
      transform: translate(2px, -2px);
    }}
    .event-no-link {{
      display: inline-block; color: var(--ab-rule-strong);
      font-family: var(--ab-mono); font-size: 0.85rem;
      margin-left: 4px; vertical-align: 1px;
      cursor: help;
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
    .angela-header button {{
      font-family: var(--ab-mono); font-size: 0.72rem;
      letter-spacing: 0.08em; text-transform: uppercase;
      padding: 8px 14px; border-radius: 6px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg-2); cursor: pointer;
    }}
    .angela-header button:hover {{ color: var(--ab-fg); border-color: var(--ab-fg-3); }}

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

    /* Toolbar with + Add event */
    .ops-toolbar {{
      display: flex; gap: 10px; align-items: center;
      margin-bottom: 18px;
    }}
    .ops-toolbar .add-btn {{
      font-family: var(--ab-sans); font-weight: 600; font-size: 0.9rem;
      padding: 9px 16px; border-radius: 8px;
      border: 1px solid var(--ab-rule-strong); background: var(--ab-bg);
      color: var(--ab-fg); cursor: pointer;
      transition: background 120ms ease, border-color 120ms ease;
    }}
    .ops-toolbar .add-btn:hover {{ background: var(--ab-bg-2); border-color: var(--ab-fg-3); }}
    .ops-toolbar .ops-count {{
      font-family: var(--ab-mono); font-size: 0.74rem;
      color: var(--ab-fg-3); letter-spacing: 0.06em;
      margin-left: auto;
    }}

    .add-event-card {{
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

  <div class="tabs" role="tablist" aria-label="View selector">
    <div class="tabs-inner">
      <button class="tab active" role="tab" data-tab="everyone" aria-selected="true" aria-controls="panel-everyone">For Everyone</button>
      <button class="tab"        role="tab" data-tab="angela"   aria-selected="false" aria-controls="panel-angela">For Angela <span class="tab-badge">ops</span></button>
    </div>
  </div>

  <main class="wrap">
    <div class="panel" id="panel-everyone" role="tabpanel" data-tab="everyone">
    <section class="hero">
      <p class="eyebrow">ArcticBlue Labs · Internal</p>
      <h1>In-person AI events <em>worth showing up for</em>.</h1>
      <p class="lede">A live tracker of every enterprise and halo AI event between now and end of 2026 — sorted by priority, location, and speaking route. Today's, upcoming, and yesterday's events are managed automatically.</p>

      <dl class="kpi-row">
        <div class="kpi">
          <dt class="kpi-num">{len(events)}</dt>
          <dd class="kpi-label">Events tracked</dd>
        </div>
        <div class="kpi">
          <dt class="kpi-num">{upcoming_count}</dt>
          <dd class="kpi-label">Upcoming</dd>
        </div>
        <div class="kpi">
          <dt class="kpi-num">{archived_count}</dt>
          <dd class="kpi-label">Archived</dd>
        </div>
        <div class="kpi">
          <dt class="kpi-num">5<span class="plus">+</span></dt>
          <dd class="kpi-label">Regions</dd>
        </div>
      </dl>
    </section>'''

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
    </div><!-- /panel-everyone -->

    <div class="panel" id="panel-angela" role="tabpanel" data-tab="angela" hidden aria-labelledby="tab-angela">

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

      <!-- State 5 · signed in and authorized — the ops UI -->
      <div id="angela-ops" hidden>
        <div class="angela-header">
          <span class="who">Signed in as <strong id="ops-email"></strong></span>
          <button id="signout-ops">Sign out</button>
        </div>
        <div id="ops-status" class="alert" hidden></div>
        <div class="ops-toolbar">
          <button class="add-btn" id="add-event-btn">+ Add event</button>
          <span class="ops-count" id="ops-count"></span>
        </div>
        <div class="ops-grid" id="ops-grid"></div>
      </div>

    </div><!-- /panel-angela -->

    <footer class="foot">
      <p class="foot-text">ArcticBlue · Event Tracker · Auto-archives events one day after end-date.</p>
      <p class="foot-mono">v1.1 · {today_iso}</p>
    </footer>
  </main>

<script>
// ── Tab switcher (For Everyone / For Angela) ──────────────────────────
(function () {{
  var TAB_KEY = 'ab.tracker.activeTab';
  var tabs = document.querySelectorAll('.tab[data-tab]');
  var panels = document.querySelectorAll('.panel[data-tab]');
  function show(name) {{
    tabs.forEach(function (t) {{
      var on = t.dataset.tab === name;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    }});
    panels.forEach(function (p) {{
      var on = p.dataset.tab === name;
      if (on) {{ p.removeAttribute('hidden'); }} else {{ p.setAttribute('hidden', ''); }}
    }});
    try {{ localStorage.setItem(TAB_KEY, name); }} catch (e) {{}}
  }}
  tabs.forEach(function (t) {{
    t.addEventListener('click', function () {{ show(t.dataset.tab); }});
  }});
  // Restore last-used tab
  try {{
    var saved = localStorage.getItem(TAB_KEY);
    if (saved === 'angela' || saved === 'everyone') show(saved);
  }} catch (e) {{}}
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
    counter.textContent = 'Showing ' + shown + ' of ' + TOTAL + ' upcoming events';
  }}
  [search, priority, region, type].forEach(function (el) {{
    if (el) el.addEventListener(el.tagName === 'INPUT' ? 'input' : 'change', apply);
  }});
  apply();
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
      return sb.from('event_state').upsert(patch, {{ onConflict: 'event_num' }}).then(function (resp) {{
        return resp.error || null;
      }});
    }}

    function buildOpsCard(ev, st, email) {{
      var card = document.createElement('article');
      card.className = 'ops-card';
      card.dataset.eventNum = ev.num;
      card.dataset.kind = 'regular';
      if (st.saved)  card.classList.add('is-saved');
      if (st.hidden) card.classList.add('is-hidden');
      if (st.urgent) card.classList.add('is-urgent');

      var metaLine = (st.updated_by && st.updated_at)
        ? '<p class="ops-meta">Last edit · ' + escapeHtml(st.updated_by) + ' · ' + escapeHtml(formatStamp(st.updated_at)) + '</p>'
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
        '<h3 class="event-name">' + escapeHtml(ev.name) + '</h3>' +
        '<p class="event-loc">' + escapeHtml(ev.region || '') + ' · ' + escapeHtml(ev.location || '') + '</p>' +
        '<details class="ops-edit">' +
          '<summary>Edit ops</summary>' +
          '<div class="ops-form">' +
            '<label><span class="key">Status</span>' +
              '<input type="text" data-field="status" value="' + escapeHtml(st.status || '') + '" placeholder="e.g. confirmed, declined, waiting on Angela…">' +
            '</label>' +
            '<label><span class="key">Speaker</span>' +
              '<input type="text" data-field="speaker" value="' + escapeHtml(st.speaker || '') + '" placeholder="Who from AB is speaking?">' +
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
          '</div>' +
          metaLine +
        '</details>';
      return card;
    }}

    function buildManualCard(mev) {{
      var card = document.createElement('article');
      card.className = 'ops-card';
      card.dataset.manualId = mev.id;
      card.dataset.kind = 'manual';
      var who = mev.created_by ? ('Added by ' + escapeHtml(mev.created_by) + ' · ' + escapeHtml(formatStamp(mev.created_at))) : '';
      card.innerHTML =
        '<div class="ops-card-head">' +
          '<div class="ops-chips">' +
            '<span class="ops-chip badge-manual">Manual</span>' +
          '</div>' +
          '<p class="event-date">' + escapeHtml(mev.date_str || '') + '</p>' +
        '</div>' +
        '<h3 class="event-name">' + escapeHtml(mev.name || '') + '</h3>' +
        '<p class="event-loc">' + escapeHtml(mev.region || '') + (mev.location ? ' · ' + escapeHtml(mev.location) : '') + '</p>' +
        (mev.why  ? '<p class="event-why" style="font-size:0.85rem;color:var(--ab-fg-2);margin:0 0 8px;">' + escapeHtml(mev.why) + '</p>' : '') +
        (mev.url  ? '<p class="event-loc"><a href="' + escapeHtml(mev.url) + '" target="_blank" rel="noopener" style="color:var(--ab-blue);text-decoration:none;">' + escapeHtml(mev.url) + ' ↗</a></p>' : '') +
        (who ? '<p class="ops-meta">' + who + '</p>' : '');
      return card;
    }}

    function wireOpsCard(card, email) {{
      var num = parseInt(card.dataset.eventNum, 10);

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

      // Selects (priority_override, track) — save on change
      card.querySelectorAll('select[data-field]').forEach(function (sel) {{
        sel.addEventListener('change', function () {{
          var patch = {{}};
          patch[sel.dataset.field] = sel.value || null;
          upsertEventState(num, patch, email).then(function (err) {{
            if (err) {{ status('Save failed: ' + err.message, 'error'); return; }}
            flashOk();
          }});
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

    function renderOps(email) {{
      $opsGrid.innerHTML = '<p style="grid-column:1/-1;color:var(--ab-fg-3);font-size:0.9rem;">Loading events…</p>';
      Promise.all([
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
          $opsGrid.appendChild(buildManualCard(mev));
        }});
        updateOpsCount();
      }});
    }}

    // ── + Add event flow ─────────────────────────────────────────────
    function wireAddEvent(email) {{
      var $addBtn = document.getElementById('add-event-btn');
      if (!$addBtn) return;
      // Clone-and-replace to clear any listeners from a prior route() call
      var fresh = $addBtn.cloneNode(true);
      $addBtn.parentNode.replaceChild(fresh, $addBtn);
      $addBtn = fresh;
      $addBtn.addEventListener('click', function () {{
        // Toggle: if a form is already open, close it
        var existing = document.getElementById('add-event-card');
        if (existing) {{ existing.remove(); return; }}

        var form = document.createElement('form');
        form.id = 'add-event-card';
        form.className = 'add-event-card ops-form';
        form.innerHTML =
          '<h3>New manual event</h3>' +
          '<label><span class="key">Name *</span>' +
            '<input type="text" name="name" required placeholder="e.g. AI Summit San Francisco">' +
          '</label>' +
          '<label><span class="key">Date *</span>' +
            '<input type="text" name="date_str" required placeholder="e.g. September 12, 2026 or September 10–12, 2026">' +
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
          '<label><span class="key">Why it fits</span>' +
            '<textarea name="why" placeholder="One line on why this is on the list"></textarea>' +
          '</label>' +
          '<label><span class="key">URL</span>' +
            '<input type="text" name="url" placeholder="https://…">' +
          '</label>' +
          '<div class="add-actions">' +
            '<button type="submit" class="primary">Add event</button>' +
            '<button type="button" class="secondary" data-cancel>Cancel</button>' +
          '</div>';

        $opsGrid.insertBefore(form, $opsGrid.firstChild);
        form.querySelector('input[name="name"]').focus();

        form.querySelector('[data-cancel]').addEventListener('click', function () {{ form.remove(); }});

        form.addEventListener('submit', function (ev) {{
          ev.preventDefault();
          var fd = new FormData(form);
          var row = {{
            name:      (fd.get('name') || '').toString().trim(),
            date_str:  (fd.get('date_str') || '').toString().trim(),
            location:  (fd.get('location') || '').toString().trim() || null,
            region:    (fd.get('region') || '').toString().trim() || null,
            type:      (fd.get('type') || '').toString().trim() || null,
            priority:  (fd.get('priority') || '').toString().trim() || null,
            why:       (fd.get('why') || '').toString().trim() || null,
            url:       (fd.get('url') || '').toString().trim() || null,
            created_by: email
          }};
          if (!row.name || !row.date_str) {{ alert('Name and date are required'); return; }}
          var submitBtn = form.querySelector('button.primary');
          submitBtn.disabled = true; submitBtn.textContent = 'Saving…';
          sb.from('manual_events').insert(row).select().then(function (resp) {{
            submitBtn.disabled = false; submitBtn.textContent = 'Add event';
            if (resp.error) {{ status('Add failed: ' + resp.error.message, 'error'); return; }}
            var newRow = (resp.data && resp.data[0]) || row;
            form.remove();
            var card = buildManualCard(newRow);
            // Insert at the top of the grid so it's immediately visible
            $opsGrid.insertBefore(card, $opsGrid.firstChild);
            updateOpsCount();
            flashOk('Event added');
          }});
        }});
      }});
    }}

    function route(session) {{
      if (!session || !session.user || !session.user.email) {{
        showOnly($signin);
        return;
      }}
      var email = session.user.email.toLowerCase();
      sb.from('allowed_editors').select('email').then(function (r) {{
        var allow = (r.data || []).map(function (x) {{ return (x.email || '').toLowerCase(); }});
        if (allow.indexOf(email) === -1) {{
          $unauthEmail.textContent = email;
          showOnly($unauth);
          return;
        }}
        $opsEmail.textContent = email;
        showOnly($ops);
        renderOps(email);
        wireAddEvent(email);
      }});
    }}

    $signinForm.addEventListener('submit', function (ev) {{
      ev.preventDefault();
      var email = ($signinEmail.value || '').trim().toLowerCase();
      if (!email) return;
      $signinSubmit.disabled = true;
      $signinSubmit.textContent = 'Sending…';
      sb.auth.signInWithOtp({{
        email: email,
        options: {{ emailRedirectTo: window.location.origin + window.location.pathname }}
      }}).then(function (r) {{
        $signinSubmit.disabled = false;
        $signinSubmit.textContent = 'Send magic link';
        if (r.error) {{
          alert('Sign-in failed: ' + r.error.message);
          return;
        }}
        $sentTo.textContent = email;
        showOnly($sent);
      }});
    }});

    function signOut() {{
      sb.auth.signOut().then(function () {{ route(null); }});
    }}
    if ($signoutUnauth) $signoutUnauth.addEventListener('click', signOut);
    if ($signoutOps)    $signoutOps.addEventListener('click', signOut);

    // Initial routing + react to auth-state changes (magic-link callback fires this)
    sb.auth.getSession().then(function (r) {{
      route(r.data ? r.data.session : null);
    }});
    sb.auth.onAuthStateChange(function (event, session) {{
      route(session);
    }});
  }});
}})();
</script>
</body>
</html>
'''

    html = head + today_section + upcoming_section + archive_section + foot
    OUT_SHIP.parent.mkdir(parents=True, exist_ok=True)
    OUT_SHIP.write_text(html, encoding='utf-8')
    print(f'WROTE {OUT_SHIP}  ({len(html):,} bytes)')
    print(f'Events: today={len(today_evs)} · upcoming={upcoming_count} · archived={archived_count}')

    # ── Robot-readable companion file for the Dust agent ──────────────────
    # The agent fetches this URL at the start of every run to dedupe.
    # Schema is intentionally flat + small so it's cheap to read.
    write_events_json(today_evs, upcoming, archived)


def write_events_json(today_evs, upcoming, archived):
    """Emit public/events.json — the canonical, robot-readable event list.
    Read by the ArcticBlueEventSpeaking Dust agent for deduplication.
    Schema is stable; do not break it without bumping `schema_version`."""
    OUT_JSON = HERE / 'public' / 'events.json'

    def serialize(ev, bucket):
        return {
            'num':           ev.get('num'),
            'name':          ev.get('name', ''),
            'date_str':      ev.get('date_str', ''),
            'start_date':    ev.get('_start').isoformat() if ev.get('_start') else None,
            'end_date':      ev.get('_end').isoformat()   if ev.get('_end')   else None,
            'location':      ev.get('location', ''),
            'region':        region_from_location(ev.get('location', '')),
            'type':          ev.get('type', ''),
            'priority':      ev.get('priority', ''),
            'priority_full': ev.get('priority_full', ev.get('priority', '')),
            'why':           ev.get('why', ''),
            'url':           EVENT_URLS.get(str(ev.get('num', ''))),
            'status':        bucket,
        }

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


if __name__ == '__main__':
    build()
