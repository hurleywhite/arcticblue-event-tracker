"""POST /api/events — ingest new events into Supabase manual_events.

WHY this exists:
  /api/vet and /api/search are OUTBOUND — they call the Dust agent to find
  or vet events. This endpoint is INBOUND: it lets an external automation
  (the Dust event-tracker agent) push newly-found events straight into the
  tracker WITHOUT a logged-in Supabase user session and WITHOUT handing out
  Supabase tokens. The caller proves itself with a single shared secret; the
  server then inserts using the service-role key (server-side only) which
  bypasses RLS. New rows show up live in the "For Angela" tab immediately.

AUTH (one of):
  - header  X-API-Key: <EVENTS_INGEST_SECRET>
  - header  Authorization: Bearer <EVENTS_INGEST_SECRET>

BODY (any of):
  - a single event object:            { "name": "...", "date_str": "...", ... }
  - a wrapped batch:                  { "events": [ {...}, {...} ] }
  - a top-level array:                [ {...}, {...} ]
  Max 50 events per request. Only known manual_events columns are stored;
  any other keys are ignored. `name` is required per event.

RESPONSE 200: {
  "inserted": [ { "id": <int>, "name": "..." }, ... ],
  "skipped":  [ { "name": "...", "reason": "duplicate" }, ... ],
  "errors":   [ { "name": "...", "reason": "..." }, ... ],
  "counts":   { "inserted": N, "skipped": N, "errors": N }
}

ENV:
  SUPABASE_URL                 (default project URL)
  SUPABASE_SERVICE_ROLE_KEY    (REQUIRED — server-side insert, bypasses RLS)
  EVENTS_INGEST_SECRET         (REQUIRED — shared secret the caller sends)
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import hmac
import urllib.request
import urllib.parse
import urllib.error


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL  = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SERVICE_ROLE  = _env('SUPABASE_SERVICE_ROLE_KEY')
INGEST_SECRET = _env('EVENTS_INGEST_SECRET')

DEFAULT_CREATED_BY = _env('EVENTS_INGEST_CREATED_BY', 'dust@arcticblue.ai')
MAX_EVENTS = 50

# Columns the caller is allowed to set. Mirrors the live manual_events table
# (minus server-managed id / created_at). Anything outside this set is dropped.
ALLOWED = {
    'name', 'date_str', 'location', 'region', 'type', 'priority', 'why', 'url',
    'speaker', 'status', 'status_tags', 'submission_status', 'notes',
    'poc_name', 'poc_email', 'poc_linkedin', 'additional_contacts',
    'speaking_fee', 'paid', 'about', 'focus_areas', 'typical_attendees',
    'speaking_route', 'contact_info', 'deadline', 'attendee_count',
    'pay_to_play', 'venue', 'city', 'country', 'seed', 'urgent',
    'external_id', 'start_date', 'end_date', 'created_by',
}
BOOL_COLS = {'seed', 'urgent', 'paid'}

# Canonical 5-stage pipeline — incoming status_tags are normalized to these.
STAGES = ['Identified', 'Submitted', 'Meeting held', 'Booked', 'Declined']
_STAGE_LOOKUP = {s.lower(): s for s in STAGES}

_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11,
    'december': 12, 'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7,
    'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def _iso(y, m, d):
    return '%04d-%02d-%02d' % (y, m, d)


def _derive_dates(text):
    """Port of the app's deriveDatesFromText(). Returns (start, end) ISO
    strings or (None, None). Mirrors three shapes: cross-month range,
    same-month range, single date."""
    if not text:
        return (None, None)
    s = str(text)

    def ok_day(d):
        return 1 <= d <= 31

    m1 = re.search(r'([A-Za-z]+)\s+(\d{1,2})\s*[–—-]\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', s)
    if m1:
        ma = _MONTHS.get(m1.group(1).lower()); mb = _MONTHS.get(m1.group(3).lower())
        d1 = int(m1.group(2)); d2 = int(m1.group(4))
        if ma and mb and ok_day(d1) and ok_day(d2):
            y = int(m1.group(5))
            return (_iso(y, ma, d1), _iso(y, mb, d2))

    m2 = re.search(r'([A-Za-z]+)\s+(\d{1,2})\s*[–—-]\s*(\d{1,2}),?\s+(\d{4})', s)
    if m2:
        mn = _MONTHS.get(m2.group(1).lower())
        d1 = int(m2.group(2)); d2 = int(m2.group(3))
        if mn and ok_day(d1) and ok_day(d2):
            y = int(m2.group(4))
            return (_iso(y, mn, d1), _iso(y, mn, d2))

    m3 = re.search(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', s)
    if m3:
        mn = _MONTHS.get(m3.group(1).lower())
        d1 = int(m3.group(2))
        if mn and ok_day(d1):
            d = _iso(int(m3.group(3)), mn, d1)
            return (d, d)

    return (None, None)


def _truthy(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def _norm_tags(v):
    if isinstance(v, str):
        v = [p.strip() for p in v.split(',')]
    if not isinstance(v, list):
        return []
    out = []
    for t in v:
        canon = _STAGE_LOOKUP.get(str(t).strip().lower())
        if canon and canon not in out:
            out.append(canon)
    return out


def _coerce(ev):
    """Filter an incoming dict to allowed columns + coerce types. Returns a
    row dict (may be empty) or None if the input isn't an object."""
    if not isinstance(ev, dict):
        return None
    row = {}
    for k, v in ev.items():
        if k not in ALLOWED or v is None:
            continue
        if k == 'status_tags':
            tags = _norm_tags(v)
            if tags:
                row[k] = tags
            continue
        if k in BOOL_COLS:
            row[k] = _truthy(v)
            continue
        sv = str(v).strip()
        if sv:
            row[k] = sv
    return row


def _svc_headers():
    return {
        'apikey':        SERVICE_ROLE,
        'Authorization': 'Bearer ' + SERVICE_ROLE,
        'Content-Type':  'application/json',
    }


def _http_json(method, url, headers=None, body=None, timeout=20):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        h.setdefault('Content-Type', 'application/json')
    req = urllib.request.Request(url, method=method, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8')
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {'error': 'network: %s' % e}


def _existing_manual_names():
    status, rows = _http_json(
        'GET', SUPABASE_URL + '/rest/v1/manual_events?select=name',
        headers=_svc_headers(), timeout=15)
    if status == 200 and isinstance(rows, list):
        return set((r.get('name') or '').strip().lower() for r in rows if r.get('name'))
    return set()


def _catalog_names(host):
    """Best-effort dedupe against the public catalog (events.json) served by
    this same deployment. Failures just return an empty set."""
    if not host:
        return set()
    url = 'https://%s/events.json' % host
    status, data = _http_json('GET', url, timeout=15)
    names = set()
    if status == 200 and isinstance(data, dict):
        for e in (data.get('events') or []):
            n = (e.get('name') or '').strip().lower()
            if n:
                names.add(n)
    return names


def _insert_one(row):
    return _http_json(
        'POST', SUPABASE_URL + '/rest/v1/manual_events',
        headers=dict(_svc_headers(), **{'Prefer': 'return=representation'}),
        body=row, timeout=20)


def _send(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-API-Key')
    handler.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
    handler.end_headers()
    handler.wfile.write(body)


def _authorized(handler):
    provided = (handler.headers.get('X-API-Key', '') or handler.headers.get('x-api-key', '') or '').strip()
    if not provided:
        ah = handler.headers.get('Authorization', '')
        if ah.lower().startswith('bearer '):
            provided = ah[7:].strip()
    if not provided or not INGEST_SECRET:
        return False
    return hmac.compare_digest(provided, INGEST_SECRET)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, {})

    def do_GET(self):
        _send(self, 405, {
            'error': 'method not allowed',
            'hint':  'POST a JSON event (or {"events":[...]}) with header X-API-Key.',
        })

    def do_POST(self):
        try:
            self._handle()
        except Exception as e:
            import traceback
            _send(self, 500, {
                'error': 'unhandled exception',
                'type':  type(e).__name__,
                'msg':   str(e),
                'trace': traceback.format_exc()[-2000:],
            })

    def _handle(self):
        # Config guards first.
        if not INGEST_SECRET:
            return _send(self, 500, {'error': 'server not configured: EVENTS_INGEST_SECRET missing'})
        if not SERVICE_ROLE:
            return _send(self, 500, {'error': 'server not configured: SUPABASE_SERVICE_ROLE_KEY missing'})

        # Auth.
        if not _authorized(self):
            return _send(self, 401, {'error': 'unauthorized: missing or invalid X-API-Key'})

        # Parse body.
        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw    = self.rfile.read(length).decode('utf-8') if length else '{}'
            body   = json.loads(raw or '{}')
        except (ValueError, json.JSONDecodeError):
            return _send(self, 400, {'error': 'invalid JSON body'})

        if isinstance(body, list):
            items = body
        elif isinstance(body, dict) and isinstance(body.get('events'), list):
            items = body['events']
        elif isinstance(body, dict):
            items = [body]
        else:
            items = []

        if not items:
            return _send(self, 400, {'error': 'no events found in body'})
        if len(items) > MAX_EVENTS:
            return _send(self, 413, {'error': 'too many events (max %d per request)' % MAX_EVENTS})

        # Dedupe sources (fetched once).
        existing = _existing_manual_names()
        catalog  = _catalog_names(self.headers.get('Host', ''))
        seen_this_run = set()

        inserted, skipped, errors = [], [], []

        for ev in items:
            row = _coerce(ev)
            if row is None:
                errors.append({'name': None, 'reason': 'not an object'})
                continue
            name = (row.get('name') or '').strip()
            if not name:
                errors.append({'name': None, 'reason': 'missing name'})
                continue

            # date_str is NOT NULL in the schema — default it.
            if not row.get('date_str'):
                row['date_str'] = 'Date TBD'
            # Derive start/end so the row is calendar + iCal ready immediately.
            if not row.get('start_date'):
                s, e = _derive_dates(row['date_str'])
                if s:
                    row['start_date'] = s
                if e and not row.get('end_date'):
                    row['end_date'] = e

            row.setdefault('created_by', DEFAULT_CREATED_BY)
            row.setdefault('external_id', 'dust')

            lname = name.lower()
            if lname in seen_this_run or lname in existing or lname in catalog:
                skipped.append({'name': name, 'reason': 'duplicate'})
                continue

            status, data = _insert_one(row)
            if status in (200, 201) and isinstance(data, list) and data:
                inserted.append({'id': data[0].get('id'), 'name': name})
                seen_this_run.add(lname)
                existing.add(lname)
            elif status == 409 or (isinstance(data, dict) and str(data.get('code')) == '23505'):
                skipped.append({'name': name, 'reason': 'duplicate (db unique index)'})
            else:
                detail = data if isinstance(data, str) else (
                    data.get('message') if isinstance(data, dict) else None)
                errors.append({'name': name, 'reason': 'insert failed (%s)' % status, 'detail': detail})

        return _send(self, 200, {
            'inserted': inserted,
            'skipped':  skipped,
            'errors':   errors,
            'counts': {
                'inserted': len(inserted),
                'skipped':  len(skipped),
                'errors':   len(errors),
            },
        })
