"""GET /api/calendars — read-only overlay of the team's shared calendars.

NO OAUTH. Each calendar is configured as a private iCal/ICS feed URL — the
"Secret address in iCal format" you get from Google Calendar settings (or
"Publish" -> ICS in Outlook / Apple). That link is not OAuth and not the API;
it just lets a server fetch the calendar as a .ics file. We fetch + parse it
server-side (browsers can't fetch those feeds directly — cross-site blocked)
and the secret URLs live ONLY in this env var, never in the public page.

CONFIGURE (Vercel env var TEAM_CALENDARS, a JSON array):
  [
    {"name": "Jerome", "url": "https://calendar.google.com/.../basic.ics", "kind": "person"},
    {"name": "Joe",    "url": "https://outlook.../calendar.ics",            "kind": "person"},
    {"name": "Events", "url": "https://.../team-events.ics",                "kind": "events"}
  ]
  kind "person" = a teammate's calendar (private). kind "events" = a shared
  non-private events calendar.

PRIVACY (the tracker is publicly readable):
  - FREE/BUSY for people (dates only, NO titles/locations) is ALWAYS returned —
    that's all the Planner conflict check needs, and it leaks nothing sensitive.
  - FULL details for people (titles/locations) are returned ONLY to a signed-in
    editor: the caller's Supabase access token is verified server-side and the
    email must be in allowed_editors (read with the service-role key).
  - "events" calendars are treated as non-private -> full details always.

RESPONSE 200: {
  "configured":  true,                       // any feeds set up?
  "detail_visible": false,                   // were person titles returned?
  "people":      ["Jerome", "Joe"],
  "busy":        { "Jerome": [ {"start":"2026-06-20","end":"2026-06-22","all_day":true}, ... ] },
  "events":      [ {"owner":"Events","kind":"events","title":"...","start":"...","end":"...","location":"..."} ],
  "fetched":     2,
  "recurring_skipped": 3,                    // recurring events are not expanded (v1)
  "errors":      [ {"name":"Joe","reason":"..."} ]
}

ENV:
  TEAM_CALENDARS               (JSON array described above; empty -> inert)
  SUPABASE_URL                 (default project URL)
  SUPABASE_PUBLISHABLE_KEY     (verifies the caller's session token)
  SUPABASE_SERVICE_ROLE_KEY    (reads allowed_editors to gate full detail)
  CALENDAR_WINDOW_PAST_DAYS    (default 31)   how far back to include
  CALENDAR_WINDOW_FUTURE_DAYS  (default 400)  how far ahead to include
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, timedelta


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SUPABASE_PUBLISHABLE = _env('SUPABASE_PUBLISHABLE_KEY')
SUPABASE_SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')

WINDOW_PAST = int(_env('CALENDAR_WINDOW_PAST_DAYS', '31') or '31')
WINDOW_FUTURE = int(_env('CALENDAR_WINDOW_FUTURE_DAYS', '400') or '400')
MAX_EVENTS_PER_FEED = 400


def _http(method, url, headers=None, timeout=15, raw=False):
    h = dict(headers or {})
    req = urllib.request.Request(url, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', errors='replace')
            if raw:
                return r.status, body
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return e.code, body
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return 0, 'network: %s' % e


def _same_origin(handler):
    host = (handler.headers.get('Host', '') or '').strip().lower()
    if not host:
        return False
    for h in ('Origin', 'Referer'):
        v = (handler.headers.get(h, '') or '').strip().lower()
        if v:
            try:
                if urllib.parse.urlsplit(v).netloc == host:
                    return True
            except ValueError:
                pass
    return False


# ── iCal / ICS parsing (stdlib only) ────────────────────────────────────────
def _unfold(text):
    """RFC 5545 line folding: a CRLF + space/tab continues the previous line."""
    return re.sub(r'\r?\n[ \t]', '', text)


def _ics_unescape(v):
    return (v.replace('\\n', ' ').replace('\\N', ' ').replace('\\,', ',')
             .replace('\\;', ';').replace('\\\\', '\\')).strip()


def _parse_dt(value, params):
    """A DTSTART/DTEND value -> (YYYY-MM-DD, all_day). Date granularity is all
    the tracker needs (events are matched on day ranges). Timed values keep
    their date; UTC 'Z' values are treated as that calendar date."""
    m = re.match(r'(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2}))?', value.strip())
    if not m:
        return None, False
    iso = '%s-%s-%s' % (m.group(1), m.group(2), m.group(3))
    all_day = ('VALUE=DATE' in params.upper()) or (m.group(4) is None)
    return iso, all_day


def _parse_ics(text):
    """Return a list of raw VEVENT dicts from ICS text."""
    text = _unfold(text)
    events, cur = [], None
    for line in text.split('\n'):
        line = line.rstrip('\r')
        if line == 'BEGIN:VEVENT':
            cur = {}
        elif line == 'END:VEVENT':
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ':' in line:
            name, _, value = line.partition(':')
            prop, _, params = name.partition(';')
            prop = prop.upper()
            if prop == 'DTSTART':
                cur['start'], cur['all_day'] = _parse_dt(value, params)
            elif prop == 'DTEND':
                cur['end'], _ = _parse_dt(value, params)
            elif prop == 'SUMMARY':
                cur['summary'] = _ics_unescape(value)
            elif prop == 'LOCATION':
                cur['location'] = _ics_unescape(value)
            elif prop == 'STATUS':
                cur['status'] = value.strip().upper()
            elif prop == 'TRANSP':
                cur['transp'] = value.strip().upper()
            elif prop == 'RRULE':
                cur['rrule'] = value.strip()
    return events


def _normalize(raw, lo, hi):
    """Filter + normalize parsed VEVENTs to busy blocks within [lo, hi].
    Returns (blocks, recurring_skipped). Each block: {start, end, all_day,
    summary, location}. end is INCLUSIVE (ICS all-day DTEND is exclusive)."""
    blocks, recurring = [], 0
    for e in raw:
        start = e.get('start')
        if not start:
            continue
        if e.get('status') == 'CANCELLED':
            continue
        if e.get('transp') == 'TRANSPARENT':   # marked "free", not busy
            continue
        if e.get('rrule'):                      # v1: recurring events not expanded
            recurring += 1
            continue
        end = e.get('end') or start
        if e.get('all_day') and end > start:
            # ICS all-day DTEND is the day AFTER the last day -> make inclusive.
            try:
                d = date.fromisoformat(end) - timedelta(days=1)
                end = d.isoformat()
            except ValueError:
                pass
        if end < start:
            end = start
        if end < lo or start > hi:              # outside the window
            continue
        blocks.append({
            'start': start, 'end': end, 'all_day': bool(e.get('all_day')),
            'summary': (e.get('summary') or '').strip(),
            'location': (e.get('location') or '').strip(),
        })
    blocks.sort(key=lambda b: b['start'])
    return blocks[:MAX_EVENTS_PER_FEED], recurring


def _is_editor(handler):
    """True if the caller presents a valid Supabase session whose email is in
    allowed_editors (checked with the service-role key, bypassing RLS)."""
    if not (SUPABASE_PUBLISHABLE and SUPABASE_SERVICE_ROLE):
        return False
    auth = (handler.headers.get('Authorization', '') or '').strip()
    token = auth[7:].strip() if auth[:7].lower() == 'bearer ' else ''
    if not token or token == SUPABASE_PUBLISHABLE:
        return False
    st, user = _http('GET', SUPABASE_URL + '/auth/v1/user',
                     headers={'apikey': SUPABASE_PUBLISHABLE,
                              'Authorization': 'Bearer ' + token})
    if st != 200 or not isinstance(user, dict):
        return False
    email = (user.get('email') or '').strip().lower()
    if not email:
        return False
    st, rows = _http('GET', SUPABASE_URL + '/rest/v1/allowed_editors?select=email&email=eq.'
                     + urllib.parse.quote(email),
                     headers={'apikey': SUPABASE_SERVICE_ROLE,
                              'Authorization': 'Bearer ' + SUPABASE_SERVICE_ROLE})
    return st == 200 and isinstance(rows, list) and len(rows) > 0


def _feeds():
    """Parse TEAM_CALENDARS env into a clean list of {name, url, kind}."""
    raw = _env('TEAM_CALENDARS')
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for f in (data if isinstance(data, list) else []):
        if not isinstance(f, dict):
            continue
        name = (f.get('name') or '').strip()
        url = (f.get('url') or '').strip()
        kind = (f.get('kind') or 'person').strip().lower()
        if name and url.startswith(('http://', 'https://', 'webcal://')):
            out.append({'name': name, 'url': url.replace('webcal://', 'https://', 1),
                        'kind': 'events' if kind == 'events' else 'person'})
    return out


def _gather(detail_ok):
    feeds = _feeds()
    today = date.today()
    lo = (today - timedelta(days=WINDOW_PAST)).isoformat()
    hi = (today + timedelta(days=WINDOW_FUTURE)).isoformat()
    busy, events, errors = {}, [], []
    fetched, recurring_skipped = 0, 0
    people = [f['name'] for f in feeds if f['kind'] == 'person']
    for f in feeds:
        st, body = _http('GET', f['url'], timeout=15, raw=True,
                         headers={'User-Agent': 'ArcticBlueTracker/1.0'})
        if st != 200 or not isinstance(body, str) or 'BEGIN:VCALENDAR' not in body:
            errors.append({'name': f['name'],
                           'reason': 'fetch failed (%s)' % (st if st else 'network')})
            continue
        fetched += 1
        blocks, rec = _normalize(_parse_ics(body), lo, hi)
        recurring_skipped += rec
        is_events = f['kind'] == 'events'
        show_detail = is_events or detail_ok
        if not is_events:
            # free/busy (no titles) — always safe to expose
            busy[f['name']] = [{'start': b['start'], 'end': b['end'],
                                'all_day': b['all_day']} for b in blocks]
        for b in blocks:
            if not show_detail:
                continue
            events.append({
                'owner': f['name'], 'kind': f['kind'],
                'title': b['summary'] or ('(busy)' if not is_events else ''),
                'start': b['start'], 'end': b['end'], 'all_day': b['all_day'],
                'location': b['location'],
            })
    events.sort(key=lambda e: e['start'])
    return {
        'configured': bool(feeds),
        'detail_visible': bool(detail_ok),
        'people': people,
        'busy': busy,
        'events': events,
        'fetched': fetched,
        'recurring_skipped': recurring_skipped,
        'errors': errors,
        'window': {'from': lo, 'to': hi},
    }


def _send(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    handler.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, {})

    def do_GET(self):
        try:
            if not _same_origin(self):
                return _send(self, 403, {'error': 'forbidden: call from the tracker site'})
            detail_ok = _is_editor(self)
            return _send(self, 200, _gather(detail_ok))
        except Exception as e:  # noqa: BLE001
            return _send(self, 500, {'error': 'unhandled', 'type': type(e).__name__,
                                     'msg': str(e)[:400]})
