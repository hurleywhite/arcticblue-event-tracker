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
    .ops-card .ops-link {{
      color: var(--ab-blue); text-decoration: none;
      font-weight: 600; padding: 0 4px;
      transition: color 120ms ease;
    }}
    .ops-card .ops-link:hover {{ color: var(--ab-blue-light); }}
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
      grid-template-columns: repeat(6, 1fr);
      background: var(--ab-rule);
      border: 1px solid var(--ab-rule);
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 18px;
    }}
    .ops-stat {{
      background: var(--ab-bg); padding: 14px 16px;
      display: flex; flex-direction: column; gap: 2px;
    }}
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
      .ops-stats {{ grid-template-columns: repeat(3, 1fr); }}
    }}
    @media (max-width: 500px) {{
      .ops-stats {{ grid-template-columns: repeat(2, 1fr); }}
    }}

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
    .calendar-month {{ margin-bottom: 32px; }}
    .calendar-month-head {{
      font-family: var(--ab-sans); font-weight: 700;
      font-size: 1.1rem; letter-spacing: -0.01em;
      margin: 0 0 12px; color: var(--ab-fg);
    }}
    .calendar-grid {{
      display: grid; grid-template-columns: repeat(7, 1fr);
      gap: 1px; background: var(--ab-rule);
      border: 1px solid var(--ab-rule); border-radius: 8px;
      overflow: hidden;
    }}
    .calendar-day-head {{
      background: var(--ab-bg-2); padding: 8px;
      font-family: var(--ab-mono); font-size: 0.66rem;
      color: var(--ab-fg-3); letter-spacing: 0.08em;
      text-transform: uppercase; text-align: center;
    }}
    .calendar-day {{
      background: var(--ab-bg); padding: 6px 8px;
      min-height: 100px;
      display: flex; flex-direction: column; gap: 2px;
    }}
    .calendar-day.is-outside {{ background: var(--ab-bg-3); }}
    .calendar-day.is-outside .calendar-day-num {{ color: var(--ab-mute); }}
    .calendar-day.is-today {{ background: rgba(39,115,194,0.06); }}
    .calendar-day.is-today .calendar-day-num {{ color: var(--ab-blue); font-weight: 700; }}
    .calendar-day-num {{
      font-family: var(--ab-mono); font-size: 0.72rem;
      color: var(--ab-fg-3); margin-bottom: 4px;
    }}
    .cal-chip {{
      font-family: var(--ab-sans); font-size: 0.7rem; line-height: 1.3;
      padding: 3px 6px 4px; border-radius: 4px;
      background: var(--ab-bg-2);
      border-left: 3px solid var(--ab-rule-strong);
      cursor: pointer; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap;
      transition: background 120ms ease;
      display: flex; align-items: center; gap: 4px; min-width: 0;
    }}
    .cal-chip:hover {{ background: var(--ab-bg-3); }}
    .cal-chip.is-saved {{ background: rgba(39,115,194,0.10); border-left-color: var(--ab-blue); }}
    .cal-chip.is-urgent {{ background: rgba(185,28,28,0.10); border-left-color: var(--ab-red); }}
    .cal-chip-name {{ flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ab-fg); }}
    .cal-chip-initial {{
      display: inline-block; background: var(--ab-fg); color: var(--ab-bg);
      font-family: var(--ab-mono); font-size: 0.6rem; font-weight: 600;
      border-radius: 50%; width: 16px; height: 16px;
      line-height: 16px; text-align: center; flex-shrink: 0;
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
        <div class="ops-stats" id="ops-stats" hidden></div>
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
          <label class="ops-filter-chip"><input type="checkbox" id="ops-f-saved">Saved only</label>
          <label class="ops-filter-chip"><input type="checkbox" id="ops-f-urgent">Urgent only</label>
          <label class="ops-filter-chip"><input type="checkbox" id="ops-f-speaker">Has speaker</label>
          <label class="ops-filter-chip"><input type="checkbox" id="ops-f-hidden">Show hidden</label>
          <span class="ops-shown" id="ops-shown"></span>
        </div>
        <div class="view-toggle" role="tablist" aria-label="View">
          <button type="button" role="tab" data-view="grid"     class="active" aria-selected="true">Grid</button>
          <button type="button" role="tab" data-view="calendar" aria-selected="false">Calendar</button>
        </div>
        <div class="ops-toolbar">
          <button class="add-btn" id="add-event-btn">+ Add event</button>
          <button class="add-btn" id="paste-email-btn">Paste email</button>
          <button class="add-btn" id="vet-dust-btn">Vet with Dust</button>
          <button class="add-btn" id="csv-btn">CSV import/export</button>
          <button class="add-btn" id="ical-btn">Download saved .ics</button>
          <button class="add-btn" id="ical-subscribe-btn">Subscribe in calendar app</button>
          <span class="ops-count" id="ops-count"></span>
        </div>
        <div class="ops-grid" id="ops-grid"></div>
        <div class="ops-calendar" id="ops-calendar"></div>
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

    function renderOpsTags(st) {{
      var tags = [];
      if (st.status) {{
        tags.push('<span class="ops-tag status">' + escapeHtml(st.status) + '</span>');
      }}
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
      if (tags.length === 0) return '';
      return '<div class="ops-tags">' + tags.join('') + '</div>';
    }}

    function buildOpsCard(ev, st, email) {{
      var card = document.createElement('article');
      card.className = 'ops-card';
      card.dataset.eventNum = ev.num;
      card.dataset.kind = 'regular';
      card.dataset.region = ev.region || '';
      card.dataset.hasSpeaker = (st.speaker && st.speaker.trim()) ? '1' : '';
      if (st.saved)  card.classList.add('is-saved');
      if (st.hidden) card.classList.add('is-hidden');
      if (st.urgent) card.classList.add('is-urgent');

      var metaLine = (st.updated_by && st.updated_at)
        ? '<p class="ops-meta" title="' + escapeHtml(st.updated_by) + '">Last edit · ' + escapeHtml(firstNameFromEmail(st.updated_by)) + ' · ' + escapeHtml(formatStamp(st.updated_at)) + '</p>'
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
        '<h3 class="event-name">' + escapeHtml(ev.name) +
          (ev.url ? ' <a class="ops-link" href="' + escapeHtml(ev.url) + '" target="_blank" rel="noopener" aria-label="Open ' + escapeHtml(ev.name) + '">↗</a>' : '') +
        '</h3>' +
        '<p class="event-loc">' + escapeHtml(ev.region || '') + ' · ' + escapeHtml(ev.location || '') + '</p>' +
        renderOpsTags(st) +
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

    function buildManualCard(mev, email) {{
      var card = document.createElement('article');
      card.className = 'ops-card';
      card.dataset.manualId = mev.id;
      card.dataset.kind = 'manual';
      card.dataset.region = mev.region || '';
      card.dataset.hasSpeaker = '';
      var whoText  = mev.created_by ? ('Added by ' + escapeHtml(firstNameFromEmail(mev.created_by)) + ' · ' + escapeHtml(formatStamp(mev.created_at))) : '';
      var whoTitle = mev.created_by ? (' title="' + escapeHtml(mev.created_by) + '"') : '';
      var who      = whoText;
      card.innerHTML =
        '<div class="ops-card-head">' +
          '<div class="ops-chips">' +
            '<span class="ops-chip badge-manual">Manual</span>' +
          '</div>' +
          '<p class="event-date">' + escapeHtml(mev.date_str || '') + '</p>' +
        '</div>' +
        '<h3 class="event-name">' + escapeHtml(mev.name || '') +
          (mev.url ? ' <a class="ops-link" href="' + escapeHtml(mev.url) + '" target="_blank" rel="noopener" aria-label="Open ' + escapeHtml(mev.name || '') + '">↗</a>' : '') +
        '</h3>' +
        '<p class="event-loc">' + escapeHtml(mev.region || '') + (mev.location ? ' · ' + escapeHtml(mev.location) : '') + '</p>' +
        (mev.why  ? '<p class="event-why" style="font-size:0.85rem;color:var(--ab-fg-2);margin:0 0 8px;">' + escapeHtml(mev.why) + '</p>' : '') +
        '<details class="ops-edit">' +
          '<summary>Edit / Delete</summary>' +
          '<form class="ops-form manual-edit">' +
            '<label><span class="key">Name</span>' +
              '<input type="text" name="name" value="' + escapeHtml(mev.name || '') + '" required></label>' +
            '<label><span class="key">Date</span>' +
              '<input type="text" name="date_str" value="' + escapeHtml(mev.date_str || '') + '" required></label>' +
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
            '<label><span class="key">Why it fits</span>' +
              '<textarea name="why">' + escapeHtml(mev.why || '') + '</textarea></label>' +
            '<label><span class="key">URL</span>' +
              '<input type="text" name="url" value="' + escapeHtml(mev.url || '') + '"></label>' +
            '<div class="add-actions">' +
              '<button type="submit" class="primary">Save changes</button>' +
              '<button type="button" class="secondary" data-delete>Delete event</button>' +
            '</div>' +
          '</form>' +
        '</details>' +
        (who ? '<p class="ops-meta"' + whoTitle + '>' + who + '</p>' : '');
      return card;
    }}

    function wireManualCard(card, email) {{
      var form = card.querySelector('form.manual-edit');
      if (!form) return;
      var id = parseInt(card.dataset.manualId, 10);

      form.addEventListener('submit', function (ev) {{
        ev.preventDefault();
        var fd = new FormData(form);
        var patch = {{
          name:     (fd.get('name') || '').toString().trim(),
          date_str: (fd.get('date_str') || '').toString().trim(),
          location: (fd.get('location') || '').toString().trim() || null,
          region:   (fd.get('region') || '').toString().trim() || null,
          type:     (fd.get('type') || '').toString().trim() || null,
          priority: (fd.get('priority') || '').toString().trim() || null,
          why:      (fd.get('why') || '').toString().trim() || null,
          url:      (fd.get('url') || '').toString().trim() || null
        }};
        if (!patch.name || !patch.date_str) {{ alert('Name and date are required'); return; }}
        // Re-derive start_date from date_str (best effort)
        var derived = deriveDatesFromText(patch.date_str);
        if (derived.start_date) patch.start_date = derived.start_date;
        if (derived.end_date)   patch.end_date   = derived.end_date;
        var btn = form.querySelector('button.primary[type="submit"]');
        btn.disabled = true; btn.textContent = 'Saving…';
        sb.from('manual_events').update(patch).eq('id', id).then(function (resp) {{
          btn.disabled = false; btn.textContent = 'Save changes';
          if (resp.error) {{ status('Save failed: ' + resp.error.message, 'error'); return; }}
          flashOk('Manual event saved');
          // Trigger a re-render to refresh card with latest data
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
          flashOk('Manual event deleted');
        }});
      }});
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

    function applyFilters() {{
      var $search  = document.getElementById('ops-search');
      var $region  = document.getElementById('ops-region');
      var $saved   = document.getElementById('ops-f-saved');
      var $urgent  = document.getElementById('ops-f-urgent');
      var $speaker = document.getElementById('ops-f-speaker');
      var $hidden  = document.getElementById('ops-f-hidden');
      if (!$search || !$opsGrid) return;
      var q = ($search.value || '').toLowerCase().trim();
      var rg = $region ? ($region.value || '') : '';
      var fSaved   = !!($saved && $saved.checked);
      var fUrgent  = !!($urgent && $urgent.checked);
      var fSpeaker = !!($speaker && $speaker.checked);
      var showHidden = !!($hidden && $hidden.checked);
      // Toggle has-active classes for chip styling
      [['ops-f-saved',$saved],['ops-f-urgent',$urgent],['ops-f-speaker',$speaker],['ops-f-hidden',$hidden]].forEach(function (pair) {{
        var inp = pair[1]; if (!inp) return;
        var lbl = inp.closest('.ops-filter-chip');
        if (lbl) lbl.classList.toggle('has-active', inp.checked);
      }});
      var shown = 0;
      $opsGrid.querySelectorAll('.ops-card').forEach(function (card) {{
        var on = true;
        if (q && (card.textContent || '').toLowerCase().indexOf(q) === -1) on = false;
        if (rg && card.dataset.region !== rg) on = false;
        if (fSaved && !card.classList.contains('is-saved'))  on = false;
        if (fUrgent && !card.classList.contains('is-urgent')) on = false;
        if (fSpeaker && card.dataset.hasSpeaker !== '1')       on = false;
        if (!showHidden && card.classList.contains('is-hidden')) on = false;
        card.style.display = on ? '' : 'none';
        if (on) shown++;
      }});
      var $shown = document.getElementById('ops-shown');
      if ($shown) $shown.textContent = 'Showing ' + shown + ' of ' + $opsGrid.querySelectorAll('.ops-card').length;
    }}

    function wireFilters() {{
      ['ops-search','ops-region','ops-f-saved','ops-f-urgent','ops-f-speaker','ops-f-hidden'].forEach(function (id) {{
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
      var total = (evs || []).length + (manualRows || []).length;
      var saved = 0, urgent = 0, hidden = 0, withSpeaker = 0, withStatus = 0;
      (stateRows || []).forEach(function (r) {{
        if (r.saved)  saved++;
        if (r.urgent) urgent++;
        if (r.hidden) hidden++;
        if (r.speaker && r.speaker.trim()) withSpeaker++;
        if (r.status && r.status.trim())   withStatus++;
      }});
      $stats.innerHTML =
        '<div class="ops-stat"><span class="num">' + total + '</span><span class="lbl">Upcoming</span></div>' +
        '<div class="ops-stat saved"><span class="num">' + saved + '</span><span class="lbl">Saved</span></div>' +
        '<div class="ops-stat urgent"><span class="num">' + urgent + '</span><span class="lbl">Urgent</span></div>' +
        '<div class="ops-stat"><span class="num">' + withSpeaker + '</span><span class="lbl">Speaker set</span></div>' +
        '<div class="ops-stat"><span class="num">' + withStatus + '</span><span class="lbl">Status set</span></div>' +
        '<div class="ops-stat"><span class="num">' + hidden + '</span><span class="lbl">Hidden</span></div>';
      $stats.removeAttribute('hidden');
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
          var card = buildManualCard(mev, email);
          $opsGrid.appendChild(card);
          wireManualCard(card, email);
        }});
        updateOpsCount();
        renderStats(evs, stateRows, manualRows);
        applyFilters();
        // Mirror into the calendar view (uses the same data set)
        renderCalendar(evs, stateMap, manualRows);
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
        '<label><span class="key">Why it fits</span>' +
          '<textarea name="why" placeholder="One line on why this is on the list"></textarea>' +
        '</label>' +
        '<div class="add-actions">' +
          '<button type="submit" class="primary">Add event</button>' +
          '<button type="button" class="secondary" data-cancel>Cancel</button>' +
        '</div>';
      return form;
    }}

    // Lower-cased trimmed name → list of existing events. Used by the
    // duplicate-name guard at insert time.
    var _knownNames = null;
    function loadKnownNames() {{
      var p1 = fetch('events.json').then(function (r) {{ return r.json(); }}).then(function (d) {{
        return ((d && d.events) || []).map(function (e) {{ return (e.name || '').toLowerCase().trim(); }});
      }}).catch(function () {{ return []; }});
      var p2 = sb.from('manual_events').select('name').then(function (r) {{
        return ((r && r.data) || []).map(function (e) {{ return (e.name || '').toLowerCase().trim(); }});
      }});
      return Promise.all([p1, p2]).then(function (a) {{
        _knownNames = a[0].concat(a[1]).filter(Boolean);
        return _knownNames;
      }});
    }}
    function isDuplicateName(name) {{
      var n = (name || '').toLowerCase().trim();
      return !!_knownNames && _knownNames.indexOf(n) !== -1;
    }}

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
            if (!token) {{
              fillBtn.disabled = false; fillBtn.textContent = 'Fill from URL';
              fillMeta.textContent = 'Sign-in expired. Refresh and try again.';
              return;
            }}
            var t0 = Date.now();
            fetch('/api/vet', {{
              method:  'POST',
              headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }},
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
          url:        (fd.get('url') || '').toString().trim() || null,
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
        // Duplicate-name guard — case-insensitive across catalog + manual_events
        if (isDuplicateName(row.name)) {{
          if (!confirm('"' + row.name + '" already exists in the tracker. Add another copy anyway?')) return;
        }}
        var submitBtn = form.querySelector('button.primary[type="submit"]');
        submitBtn.disabled = true; submitBtn.textContent = 'Saving…';
        sb.from('manual_events').insert(row).select().then(function (resp) {{
          submitBtn.disabled = false; submitBtn.textContent = 'Add event';
          if (resp.error) {{ status('Add failed: ' + resp.error.message, 'error'); return; }}
          var newRow = (resp.data && resp.data[0]) || row;
          form.remove();
          var card = buildManualCard(newRow, email);
          $opsGrid.insertBefore(card, $opsGrid.firstChild);
          wireManualCard(card, email);
          updateOpsCount();
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
      if (name !== 'grid' && name !== 'calendar') name = 'grid';
      currentView = name;
      document.querySelectorAll('.view-toggle button[data-view]').forEach(function (b) {{
        var on = b.dataset.view === name;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      }});
      var g = document.getElementById('ops-grid');
      var c = document.getElementById('ops-calendar');
      if (g) g.style.display = (name === 'grid') ? '' : 'none';
      if (c) c.classList.toggle('show', name === 'calendar');
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
        if (saved === 'grid' || saved === 'calendar') setView(saved);
      }} catch (e) {{}}
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
      ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].forEach(function (d) {{
        var dh = document.createElement('div');
        dh.className = 'calendar-day-head';
        dh.textContent = d;
        grid.appendChild(dh);
      }});

      var firstDay = new Date(year, month, 1).getDay();
      var daysInMonth = new Date(year, month+1, 0).getDate();
      var prevMonthDays = new Date(year, month, 0).getDate();
      var today = new Date(); today.setHours(0,0,0,0);
      var todayIso = isoFromYMD(today.getFullYear(), today.getMonth(), today.getDate());

      // Lead with previous month's tail
      for (var i = 0; i < firstDay; i++) {{
        var dn = prevMonthDays - firstDay + i + 1;
        var cell = document.createElement('div');
        cell.className = 'calendar-day is-outside';
        cell.innerHTML = '<div class="calendar-day-num">' + dn + '</div>';
        grid.appendChild(cell);
      }}

      // Index events by start_date for O(1) lookup
      var byDate = {{}};
      events.forEach(function (ev) {{
        if (!ev.start_date) return;
        (byDate[ev.start_date] = byDate[ev.start_date] || []).push(ev);
      }});

      for (var day = 1; day <= daysInMonth; day++) {{
        var dayIso = isoFromYMD(year, month, day);
        var cell = document.createElement('div');
        cell.className = 'calendar-day';
        if (dayIso === todayIso) cell.classList.add('is-today');
        var head2 = document.createElement('div');
        head2.className = 'calendar-day-num';
        head2.textContent = day;
        cell.appendChild(head2);

        (byDate[dayIso] || []).forEach(function (ev) {{
          var st = stateMap[ev.num] || {{}};
          if (st.hidden) return;
          var chip = document.createElement('div');
          chip.className = 'cal-chip';
          if (st.saved) chip.classList.add('is-saved');
          if (st.urgent) chip.classList.add('is-urgent');
          chip.dataset.eventNum = ev.num;
          var sp = st.speaker || '';
          var ini = sp ? initials(sp) : '';
          chip.innerHTML =
            '<span class="cal-region-dot" style="background:' + regionColor(ev.region) + ';"></span>' +
            '<span class="cal-chip-name">' + escapeHtml(ev.name) + '</span>' +
            (ini ? '<span class="cal-chip-initial" title="' + escapeHtml(sp) + '">' + escapeHtml(ini) + '</span>' : '');
          chip.title = ev.name +
            (sp ? ' · Speaker: ' + sp : '') +
            (ev.location ? ' · ' + ev.location : '') +
            (st.status ? ' · ' + st.status : '');
          chip.addEventListener('click', function () {{ onChipClick(ev.num); }});
          cell.appendChild(chip);
        }});

        grid.appendChild(cell);
      }}

      // Trail: pad to complete the last week
      var totalCells = firstDay + daysInMonth;
      var trail = (Math.ceil(totalCells / 7) * 7) - totalCells;
      for (var t = 1; t <= trail; t++) {{
        var cell2 = document.createElement('div');
        cell2.className = 'calendar-day is-outside';
        cell2.innerHTML = '<div class="calendar-day-num">' + t + '</div>';
        grid.appendChild(cell2);
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
          // Try to derive start_date from date_str — best effort
          var derived = deriveStartDateFromText(m.date_str);
          if (derived) m = Object.assign({{}}, m, {{ start_date: derived }});
        }}
        combined.push({{
          num: 'm' + m.id, // composite key — string for chip data attribute
          _manual: true,
          _manualId: m.id,
          name: m.name,
          start_date: m.start_date,
          location: m.location || '',
          region: m.region || '',
          date_str: m.date_str || ''
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

      function onChipClick(num) {{
        setView('grid');
        var selector = String(num).charAt(0) === 'm'
          ? '.ops-card[data-manual-id="' + String(num).slice(1) + '"]'
          : '.ops-card[data-event-num="' + num + '"]';
        var card = $opsGrid.querySelector(selector);
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
      return out;
    }}

    // Back-compat shim — older callers want just the start date.
    function deriveStartDateFromText(text) {{
      return deriveDatesFromText(text).start_date;
    }}

    // ── Realtime subscription ───────────────────────────────────────
    var realtimeChannel = null;
    function setupRealtime(email) {{
      if (realtimeChannel) {{
        try {{ realtimeChannel.unsubscribe(); }} catch (e) {{}}
        realtimeChannel = null;
      }}
      try {{
        realtimeChannel = sb.channel('ops-realtime-' + Math.random().toString(36).slice(2,8))
          .on('postgres_changes', {{ event: '*', schema: 'public', table: 'event_state' }}, function () {{
            renderOps(email);
          }})
          .on('postgres_changes', {{ event: '*', schema: 'public', table: 'manual_events' }}, function () {{
            renderOps(email);
          }})
          .subscribe();
      }} catch (e) {{
        // Realtime is a nice-to-have; if it fails, polling on user action still works
        console.warn('Realtime setup failed:', e);
      }}
    }}

    // ── CSV import/export ───────────────────────────────────────────
    var CSV_COLUMNS = ['event_num','status','speaker','priority_override','track','saved','hidden','urgent','notes'];

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
          'Columns: <code>' + CSV_COLUMNS.join(', ') + '</code>. Booleans: <code>true</code> / <code>false</code>.' +
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
          // Validate headers
          var missing = CSV_COLUMNS.filter(function (c) {{ return parsed.headers.indexOf(c) === -1; }});
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
            CSV_COLUMNS.forEach(function (c) {{ out[c] = coerceCsvValue(c, row[c]); }});
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
                CSV_COLUMNS.forEach(function (c) {{ row[c] = r[c]; }});
                row.updated_by = email;
                return row;
              }});
              if (toUpsert.length === 0) {{ btn.disabled = false; btn.textContent = 'Nothing to apply'; return; }}
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

    // ── Vet with Dust ────────────────────────────────────────────────
    // Sends the candidate text through the ArcticBlueEventSpeaking Dust
    // agent (via the /api/vet Vercel function which holds the API key)
    // and renders the agent's structured recommendation + lets the user
    // promote it into the + Add Event form with one click.
    function openVetPanel(email) {{
      var existing = document.getElementById('vet-panel');
      if (existing) {{ existing.remove(); return; }}

      var panel = document.createElement('div');
      panel.id = 'vet-panel';
      panel.className = 'add-event-card';
      panel.innerHTML =
        '<h3>Vet a candidate with Dust</h3>' +
        '<p style="margin:0 0 12px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          'Paste the email, web copy, or a description of the event. ' +
          'The <strong>ArcticBlueEventSpeaking</strong> agent will extract the details, ' +
          'rate the fit, and let you promote it into a manual event with one click.' +
        '</p>' +
        '<label><span class="key">Candidate</span>' +
          '<textarea id="vet-text" placeholder="Paste here\\u2026" style="min-height:140px;"></textarea>' +
        '</label>' +
        '<div class="add-actions" style="margin-top:10px;">' +
          '<button type="button" class="primary" id="vet-run-btn">Run vetting</button>' +
          '<button type="button" class="secondary" id="vet-cancel-btn">Close</button>' +
        '</div>' +
        '<p class="ops-meta" id="vet-meta" style="margin-top:10px;">Dust replies usually take 5\\u201340 seconds.</p>' +
        '<div id="vet-result" style="margin-top:12px;"></div>';

      $opsGrid.insertBefore(panel, $opsGrid.firstChild);
      panel.querySelector('#vet-text').focus();

      panel.querySelector('#vet-cancel-btn').addEventListener('click', function () {{ panel.remove(); }});

      panel.querySelector('#vet-run-btn').addEventListener('click', function () {{
        var text = panel.querySelector('#vet-text').value || '';
        if (text.trim().length < 10) {{
          panel.querySelector('#vet-meta').textContent = 'Need at least 10 characters of context.';
          return;
        }}
        var runBtn = panel.querySelector('#vet-run-btn');
        var meta   = panel.querySelector('#vet-meta');
        runBtn.disabled = true; runBtn.textContent = 'Asking Dust\\u2026';
        meta.textContent = 'Sending to ArcticBlueEventSpeaking. This can take 30\\u201360 seconds.';

        sb.auth.getSession().then(function (r) {{
          var token = r && r.data && r.data.session && r.data.session.access_token;
          if (!token) {{
            runBtn.disabled = false; runBtn.textContent = 'Run vetting';
            meta.textContent = 'Couldn\\u2019t read your Supabase session. Try signing out and back in.';
            return;
          }}
          var t0 = Date.now();
          fetch('/api/vet', {{
            method:  'POST',
            headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }},
            body:    JSON.stringify({{ text: text }})
          }}).then(function (res) {{
            return res.json().then(function (j) {{ return [res.status, j]; }});
          }}).then(function (pair) {{
            var status = pair[0], data = pair[1];
            var dur = Math.round((Date.now() - t0) / 1000);
            runBtn.disabled = false; runBtn.textContent = 'Re-run vetting';
            if (status !== 200) {{
              meta.textContent = 'Vetting failed (' + status + '): ' + (data && data.error || 'unknown error');
              return;
            }}
            meta.textContent = 'Done in ' + dur + 's.';
            renderVetResult(panel, data, email);
          }}).catch(function (err) {{
            runBtn.disabled = false; runBtn.textContent = 'Re-run vetting';
            meta.textContent = 'Network error: ' + err.message;
          }});
        }});
      }});
    }}

    function renderVetResult(panel, data, email) {{
      var fields = data.fields || {{}};
      var rec    = (fields.recommend || '').toLowerCase();
      var recPill =
        rec === 'yes'   ? '<span class="ops-tag" style="background:#dcfce7;color:#166534;">Recommend</span>' :
        rec === 'maybe' ? '<span class="ops-tag" style="background:#fef3c7;color:#92400e;">Maybe</span>' :
        rec === 'no'    ? '<span class="ops-tag" style="background:#fee2e2;color:#991b1b;">Skip</span>' :
                          '';
      var degradedBanner = '';
      if (data.degraded) {{
        var why = data.degraded_reason === 'dust_rate_limited'
          ? 'Dust hit its rate limit. The fields below come from a basic page-scrape, not the agent. Treat them as a draft and review carefully before promoting.'
          : data.degraded_reason === 'dust_timeout'
            ? 'Dust took too long to respond. The fields below come from a basic page-scrape; review before promoting.'
            : 'Dust was unavailable. The fields below come from a basic page-scrape; review before promoting.';
        degradedBanner = '<div class="alert warn" style="margin:0 0 12px;">' + escapeHtml(why) + '</div>';
      }}

      function row(k, v) {{
        if (v === null || v === undefined || v === '') return '';
        var safe = escapeHtml(String(v));
        if (k === 'url') {{
          safe = '<a href="' + safe + '" target="_blank" rel="noopener" style="color:var(--ab-blue);text-decoration:none;">' + safe + ' \\u2197</a>';
        }}
        return '<tr><td style="padding:4px 12px 4px 0;font-family:var(--ab-mono);font-size:0.72rem;letter-spacing:0.06em;color:var(--ab-fg-3);text-transform:uppercase;vertical-align:top;">' +
                 escapeHtml(k) +
               '</td><td style="padding:4px 0;color:var(--ab-fg);">' + safe + '</td></tr>';
      }}

      var rows = ['name', 'date_str', 'location', 'region', 'type', 'priority', 'why', 'url'].map(function (k) {{
        return row(k, fields[k]);
      }}).join('');

      var html =
        degradedBanner +
        '<div class="alert" style="margin:0 0 12px;">' +
          (recPill ? recPill + ' ' : '') +
          (fields.reasoning ? escapeHtml(fields.reasoning) : (data.degraded ? 'No agent reasoning — Dust unavailable.' : 'No reasoning returned.')) +
        '</div>' +
        '<table style="width:100%;border-collapse:collapse;font-size:0.9rem;">' + rows + '</table>' +
        '<div class="add-actions" style="margin-top:14px;">' +
          '<button type="button" class="primary" id="vet-promote-btn">' +
            (rec === 'no' ? 'Add anyway' : 'Promote to event') +
          '</button>' +
          '<button type="button" class="secondary" id="vet-rawreply-btn">Show raw reply</button>' +
        '</div>' +
        '<pre id="vet-raw" style="display:none;margin-top:10px;padding:12px;background:var(--ab-bg-3);border-radius:6px;font-size:0.78rem;line-height:1.5;color:var(--ab-fg-2);max-height:280px;overflow:auto;white-space:pre-wrap;"></pre>';

      var $r = panel.querySelector('#vet-result');
      $r.innerHTML = html;

      $r.querySelector('#vet-rawreply-btn').addEventListener('click', function () {{
        var pre = $r.querySelector('#vet-raw');
        if (pre.style.display === 'none') {{
          pre.textContent = data.raw || '(no raw reply)';
          pre.style.display = 'block';
        }} else {{
          pre.style.display = 'none';
        }}
      }});

      $r.querySelector('#vet-promote-btn').addEventListener('click', function () {{
        // Open the add-event form, then fill it with the Dust fields (overwriting any draft)
        panel.remove();
        var form = (function ensureOpen() {{
          var existing = document.getElementById('add-event-card');
          if (existing) return existing;
          // wireAddEvent hooks the button → trigger it programmatically
          var $addBtn = document.getElementById('add-event-btn');
          if ($addBtn) $addBtn.click();
          return document.getElementById('add-event-card');
        }})();
        if (form) {{
          applyExtractToForm(form, fields, {{ overwrite: true }});
          var nameInp = form.querySelector('input[name="name"]');
          if (nameInp) nameInp.focus();
        }}
      }});
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
        '<h3>Subscribe in your calendar app</h3>' +
        '<p style="margin:0 0 12px;color:var(--ab-fg-2);font-size:0.9rem;">' +
          'This URL auto-updates daily with every saved event + every manual event. ' +
          'Once subscribed, your calendar app refreshes on its own — no need to re-download.' +
        '</p>' +
        '<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;">' +
          '<input type="text" id="subscribe-url" readonly value="' + escapeHtml(feedUrl) + '" ' +
            'style="flex:1;font-family:var(--ab-mono);font-size:0.85rem;padding:10px 12px;border:1px solid var(--ab-rule-strong);border-radius:6px;background:var(--ab-bg-2);color:var(--ab-fg);">' +
          '<button type="button" class="primary" id="subscribe-copy-btn" style="white-space:nowrap;font-family:var(--ab-sans);font-weight:600;font-size:0.9rem;padding:10px 16px;border-radius:6px;border:0;background:var(--ab-fg);color:var(--ab-bg);cursor:pointer;">Copy link</button>' +
        '</div>' +
        '<details open style="border-top:1px solid var(--ab-rule);padding-top:12px;">' +
          '<summary style="cursor:pointer;font-family:var(--ab-mono);font-size:0.72rem;color:var(--ab-fg-3);letter-spacing:0.08em;text-transform:uppercase;">Paste it here</summary>' +
          '<div style="display:grid;gap:10px;margin-top:10px;font-size:0.9rem;color:var(--ab-fg-2);line-height:1.55;">' +
            '<div><strong>Apple Calendar (Mac):</strong> File → New Calendar Subscription → paste → Subscribe → choose auto-refresh.</div>' +
            '<div><strong>Apple Calendar (iPhone/iPad):</strong> Settings → Calendar → Accounts → Add Account → Other → Add Subscribed Calendar → paste.</div>' +
            '<div><strong>Google Calendar:</strong> Left sidebar → Other calendars → + → From URL → paste → Add calendar.</div>' +
            '<div><strong>Outlook (web):</strong> Calendar → Add calendar → Subscribe from web → paste.</div>' +
          '</div>' +
        '</details>' +
        '<div class="add-actions" style="margin-top:14px;">' +
          '<button type="button" class="secondary" id="subscribe-close-btn">Close</button>' +
        '</div>' +
        '<p class="ops-meta" style="margin-top:10px;">Tip: the feed is empty until at least one event is starred ★ saved, or you add a manual event.</p>';

      $opsGrid.insertBefore(panel, $opsGrid.firstChild);

      panel.querySelector('#subscribe-close-btn').addEventListener('click', function () {{ panel.remove(); }});

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
      var $addBtn   = document.getElementById('add-event-btn');
      var $pasteBtn = document.getElementById('paste-email-btn');
      var $vetBtn   = document.getElementById('vet-dust-btn');
      var $csvBtn   = document.getElementById('csv-btn');
      var $icalBtn  = document.getElementById('ical-btn');
      var $subBtn   = document.getElementById('ical-subscribe-btn');
      if (!$addBtn) return;
      // Clone-replace to clear listeners from any prior route() call
      var freshAdd = $addBtn.cloneNode(true); $addBtn.parentNode.replaceChild(freshAdd, $addBtn); $addBtn = freshAdd;
      if ($pasteBtn) {{ var fp = $pasteBtn.cloneNode(true); $pasteBtn.parentNode.replaceChild(fp, $pasteBtn); $pasteBtn = fp; }}
      if ($vetBtn)   {{ var fv = $vetBtn.cloneNode(true); $vetBtn.parentNode.replaceChild(fv, $vetBtn); $vetBtn = fv; }}
      if ($csvBtn)   {{ var fc = $csvBtn.cloneNode(true); $csvBtn.parentNode.replaceChild(fc, $csvBtn); $csvBtn = fc; }}
      if ($icalBtn)  {{ var fi = $icalBtn.cloneNode(true); $icalBtn.parentNode.replaceChild(fi, $icalBtn); $icalBtn = fi; }}
      if ($subBtn)   {{ var fs = $subBtn.cloneNode(true); $subBtn.parentNode.replaceChild(fs, $subBtn); $subBtn = fs; }}

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

      $addBtn.addEventListener('click', function () {{
        var existing = document.getElementById('add-event-card');
        if (existing) {{ existing.remove(); return; }}
        openAddForm({{}});
      }});
      if ($pasteBtn) {{
        $pasteBtn.addEventListener('click', function () {{ openAddForm({{ expandPaste: true }}); }});
      }}
      if ($vetBtn) {{
        $vetBtn.addEventListener('click', function () {{ openVetPanel(email); }});
      }}
      if ($csvBtn) {{
        $csvBtn.addEventListener('click', function () {{ openCsvPanel(email); }});
      }}
      if ($icalBtn) {{
        $icalBtn.addEventListener('click', function () {{ exportSavedAsIcs(); }});
      }}
      if ($subBtn) {{
        $subBtn.addEventListener('click', function () {{ openSubscribePanel(); }});
      }}
    }}

    function route(session) {{
      if (!session || !session.user || !session.user.email) {{
        showOnly($signin);
        // Drop any active realtime channel from a previous session
        if (realtimeChannel) {{
          try {{ realtimeChannel.unsubscribe(); }} catch (e) {{}}
          realtimeChannel = null;
        }}
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
        $opsEmail.textContent = firstNameFromEmail(email);
        $opsEmail.setAttribute('title', email);
        showOnly($ops);
        wireViewToggle();
        wireFilters();
        renderOps(email);
        wireAddEvent(email);
        setupRealtime(email);
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
