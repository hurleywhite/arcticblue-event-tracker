"""/api/sessionize — what Sessionize's PUBLIC pages can tell the tracker.

Sessionize has no API a speaker (or a tool acting for one) can use: its only
feed is read-only and belongs to event organisers. Applying always happens on
sessionize.com, signed in as the speaker. So this endpoint never logs in and
never submits anything. It reads two public pages:

  GET  ?cfp=<call-for-speakers url>   open / closed, opening + closing dates,
                                      event dates (drives the "Apply on
                                      Sessionize" block in the event pop-up)
  GET  ?profile=<speaker-slug>        the events listed on a speaker's public
                                      profile, i.e. the ones that accepted them
  POST (X-API-Key)                    daily acceptance sync: when an event Thor
                                      applied to appears on his profile, mark it
                                      Booked. Body {"dry_run": true} reports
                                      without writing.

GETs are same-origin only (the tracker page calls them). The POST uses the same
EVENTS_INGEST_SECRET as /api/enrich and is called from daily-build.yml.

What the sync cannot see: rejections (Sessionize does not publish them) and
anything before the organiser announces. Those arrive by email, which is what
"Paste email" in the tracker handles.
"""
from http.server import BaseHTTPRequestHandler
import datetime as dt
import hmac
import html as _html
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')
INGEST_SECRET = _env('EVENTS_INGEST_SECRET')
TRACKER_BASE = _env('TRACKER_BASE_URL', 'https://arcticblue-event-tracker-deploy.vercel.app').rstrip('/')

# Whose public profile to watch: "thor:thor-ernstsson,verma:their-slug".
# Thor only for now (Hurley 2026-10-13).
def _profiles():
    out = {}
    for part in _env('SESSIONIZE_PROFILES', 'thor:thor-ernstsson').split(','):
        if ':' in part:
            who, slug = part.split(':', 1)
            who, slug = who.strip().lower(), slug.strip().strip('/')
            if who and _SLUG.match(slug):
                out[who] = slug
    return out


_UA = ('Mozilla/5.0 (compatible; ArcticBlueEventTracker/1.0; '
       '+https://arcticblue-event-tracker-deploy.vercel.app)')
_SLUG = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$')
# First path segments that are Sessionize's own pages, never an event or a speaker.
_RESERVED = {'app', 'api', 'playbook', 's', 'landing', 'features', 'pricing', 'speakers',
             'for-speakers', 'speakers-directory', 'blog', 'login', 'signup', 'about',
             'contact', 'terms', 'privacy', 'view'}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}


# ── Reading Sessionize ─────────────────────────────────────────────────────
def page_url(raw):
    """A user-supplied link -> the canonical https://sessionize.com/<slug>/, or ''.

    This is the only thing that decides what the server fetches, so it is strict:
    sessionize.com only, one clean slug, nothing else of the caller's survives.
    """
    raw = (raw or '').strip()
    if not raw:
        return ''
    if '://' not in raw:
        raw = 'https://' + raw
    try:
        u = urllib.parse.urlsplit(raw)
    except ValueError:
        return ''
    if (u.hostname or '').lower() not in ('sessionize.com', 'www.sessionize.com'):
        return ''
    seg = [s for s in u.path.split('/') if s]
    if not seg or seg[0].lower() in _RESERVED or not _SLUG.match(seg[0]):
        return ''
    return 'https://sessionize.com/' + seg[0] + '/'


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': _UA, 'Accept': 'text/html'})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status, r.read(1_500_000).decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception:  # noqa: BLE001 - network trouble is a normal answer here
        return 0, ''


def _text(s):
    return re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def _iso(dmy):
    """'19 Jun 2026' -> '2026-06-19' ('' when it is not that shape)."""
    m = re.match(r'^\s*(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{4})\s*$', dmy or '')
    if not m or m.group(2).lower() not in _MONTHS:
        return ''
    try:
        return dt.date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    except ValueError:
        return ''


def _after(page, label):
    """The <h2> that follows a small label such as 'event starts' or 'Call closes at'."""
    m = re.search(re.escape(label) + r'.{0,400}?<h2[^>]*>(.*?)</h2>', page, re.S | re.I)
    return _text(m.group(1)) if m else ''


def parse_cfp(page, today=None):
    """A call-for-speakers page -> what the tracker shows and stores."""
    today = today or dt.date.today()
    out = {'name': '', 'status': '', 'opens': '', 'closes': '', 'timezone': '',
           'event_start': '', 'event_end': '', 'website': ''}
    t = re.search(r'<title>(.*?)</title>', page, re.S | re.I)
    title = _text(t.group(1)) if t else ''
    if 'call for' not in title.lower():
        return None                      # a speaker profile, a 404, anything else
    out['name'] = re.sub(r'\s*:\s*Call for (Speakers|Papers|Proposals).*$', '', title, flags=re.I).strip()
    out['opens'] = _iso(_after(page, 'Call opens at'))
    out['closes'] = _iso(_after(page, 'Call closes at'))
    tz = re.search(r'Call closes in\s*<strong>(.*?)</strong>', page, re.S | re.I)
    out['timezone'] = _text(tz.group(1)) if tz else ''
    out['event_start'] = _iso(_after(page, 'event starts')) or _iso(_after(page, 'event date'))
    out['event_end'] = _iso(_after(page, 'event ends')) or out['event_start']
    w = re.search(r'website\s*</div>\s*<h2[^>]*>\s*<a[^>]+href="([^"]+)"', page, re.S | re.I)
    out['website'] = _html.unescape(w.group(1)) if w else ''
    said = re.search(r'Call for (?:Speakers|Papers|Proposals) is\s*<strong>\s*(\w+)', page, re.I)
    said = said.group(1).lower() if said else ''
    if said == 'closed':
        out['status'] = 'closed'
    elif out['opens'] and today.isoformat() < out['opens']:
        out['status'] = 'not_open_yet'
    elif out['closes'] and today.isoformat() > out['closes']:
        out['status'] = 'closed'
    elif out['closes'] or said == 'open':
        out['status'] = 'open'
    else:
        out['status'] = 'unknown'
    return out


def parse_profile(page):
    """A public speaker profile -> the events listed on it (the acceptances)."""
    t = re.search(r'<title>(.*?)</title>', page, re.S | re.I)
    title = _text(t.group(1)) if t else ''
    if 'speaker profile' not in title.lower():
        return None
    name = re.sub(r"['’]s Speaker Profile.*$", '', title, flags=re.I).strip()
    events = []
    for block in re.findall(r'<div class="c-s-event">(.*?)(?=<div class="c-s-timeline__item|</section>|$)', page, re.S):
        nm = re.search(r'class="c-s-event__name"[^>]*>(.*?)</(?:a|span)>', block, re.S)
        if not nm:
            continue
        href = re.search(r'class="c-s-event__name"[^>]*href="([^"]+)"', block)
        when = re.search(r'c-s-event__meta--date">(.*?)</span>', block, re.S)
        where = re.search(r'c-s-event__meta--location">(.*?)</span>', block, re.S)
        events.append({'name': _text(nm.group(1)),
                       'url': _html.unescape(href.group(1)) if href else '',
                       'date': _text(when.group(1)) if when else '',
                       'location': _text(where.group(1)) if where else ''})
    return {'name': name, 'events': events}


# ── Matching a profile event to a tracker row ──────────────────────────────
_FILLER = {'the', 'a', 'an', 'and', 'of', 'for', 'at', 'in', 'on', 'by', 'to'}


def name_tokens(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower()
    s = re.sub(r'\b(19|20)\d{2}\b', ' ', s)          # the year is checked separately
    s = re.sub(r'\b\d{1,2}(st|nd|rd|th)\b', ' ', s)   # "15th African ..." vs "African ..."
    return [w for w in re.sub(r'[^a-z0-9]+', ' ', s).split() if w not in _FILLER]


def _year_month(s):
    """'February 2027' or '2027-02-09' -> (2027, 2); None when unreadable."""
    s = (s or '').strip()
    m = re.match(r'^(\d{4})-(\d{2})', s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{4})', s)
    if m and m.group(1).lower() in _MONTHS:
        return int(m.group(2)), _MONTHS[m.group(1).lower()]
    return None


def same_event(profile_event, row_name, row_start):
    """Is this profile entry the tracker's event? Strict on purpose: a wrong
    match would mark an event Booked that is not."""
    a, b = name_tokens(profile_event.get('name')), name_tokens(row_name)
    if not a or not b:
        return False
    exact = a == b
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    contained = len(short) >= 2 and all(w in long_ for w in short) and len(short) / len(long_) >= 0.6
    if not (exact or contained):
        return False
    pe, re_ = _year_month(profile_event.get('date')), _year_month(row_start)
    if pe and re_:
        return abs((pe[0] * 12 + pe[1]) - (re_[0] * 12 + re_[1])) <= 1
    return exact        # no date to confirm with: only an exact name will do


def find_acceptances(person, profile_events, rows):
    """rows: [{table, key, name, speaker, tags, start_date, ...}] -> (to_book, conflicts)."""
    to_book, conflicts = [], []
    for row in rows:
        if person not in (row.get('speaker') or '').lower():
            continue
        tags = row.get('tags') or []
        if 'Submitted' not in tags or 'Booked' in tags:
            continue
        hit = next((e for e in profile_events if same_event(e, row.get('name'), row.get('start_date'))), None)
        if not hit:
            continue
        (conflicts if 'Rejected' in tags else to_book).append({'row': row, 'event': hit})
    return to_book, conflicts


def booked_tags(tags):
    """Same rule as the tracker's own Booked button: it ends the application, so
    the in-flight steps and a Rejected retire; Submitted stays as the record."""
    keep = [t for t in (tags or []) if t not in ('Rejected', 'Initial outreach', 'Followed up', 'Booked')]
    return keep + ['Booked']


# ── Supabase ───────────────────────────────────────────────────────────────
def _http(method, url, headers=None, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, method=method, headers=dict(headers or {}), data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode('utf-8')
            try:
                return r.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')[:300]
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:300]


def _svc(prefer=''):
    h = {'apikey': SERVICE_ROLE, 'Authorization': 'Bearer ' + SERVICE_ROLE,
         'Content-Type': 'application/json'}
    if prefer:
        h['Prefer'] = prefer
    return h


def _tracker_rows():
    rows = []
    st, manual = _http('GET', SUPABASE_URL + '/rest/v1/manual_events?select=id,name,speaker,status_tags,'
                       'status,start_date,notes,booking&limit=5000', headers=_svc())
    if st != 200 or not isinstance(manual, list):
        raise RuntimeError('manual_events read failed %s' % st)
    for m in manual:
        if m.get('status') == '__deleted__':
            continue
        rows.append({'table': 'manual_events', 'key': m['id'], 'name': m.get('name') or '',
                     'speaker': m.get('speaker') or '', 'tags': m.get('status_tags') or [],
                     'start_date': m.get('start_date') or '', 'notes': m.get('notes') or '',
                     'booking': m.get('booking') if isinstance(m.get('booking'), dict) else {}})
    st, states = _http('GET', SUPABASE_URL + '/rest/v1/event_state?select=event_num,name,speaker,status_tags,'
                       'status,start_date,notes,booking&limit=5000', headers=_svc())
    if st != 200 or not isinstance(states, list):
        raise RuntimeError('event_state read failed %s' % st)
    # A catalog event's name and date live in the static events.json, not the state row.
    catalog = {}
    cst, cat = _http('GET', TRACKER_BASE + '/events.json', headers={'User-Agent': _UA})
    if cst == 200 and isinstance(cat, (dict, list)):
        for e in (cat.get('events') if isinstance(cat, dict) else cat) or []:
            if isinstance(e, dict) and e.get('num') is not None:
                catalog[str(e['num'])] = e
    for s in states:
        if s.get('status') == '__deleted__':
            continue
        base = catalog.get(str(s.get('event_num')), {})
        rows.append({'table': 'event_state', 'key': s['event_num'],
                     'name': s.get('name') or base.get('name') or '',
                     'speaker': s.get('speaker') or '', 'tags': s.get('status_tags') or [],
                     'start_date': s.get('start_date') or base.get('start_date') or '',
                     'notes': s.get('notes') or '',
                     'booking': s.get('booking') if isinstance(s.get('booking'), dict) else {}})
    return rows


def sync(dry_run=False, today=None):
    today = (today or dt.date.today()).isoformat()
    report = {'ok': True, 'dry_run': bool(dry_run), 'people': {}, 'booked': [], 'conflicts': []}
    rows = None
    for person, slug in _profiles().items():
        st, page = fetch('https://sessionize.com/' + slug + '/')
        prof = parse_profile(page) if st == 200 else None
        if not prof:
            report['people'][person] = {'profile': slug, 'error': 'profile not readable (%s)' % st}
            continue
        report['people'][person] = {'profile': slug, 'events_on_profile': len(prof['events'])}
        if not prof['events']:
            continue                      # nothing accepted yet: no need to load the tracker
        if rows is None:
            rows = _tracker_rows()
        to_book, conflicts = find_acceptances(person, prof['events'], rows)
        for c in conflicts:
            report['conflicts'].append({'event': c['row']['name'], 'person': person,
                                        'why': 'on the Sessionize profile but marked Rejected in the tracker'})
        for hit in to_book:
            row = hit['row']
            line = 'Accepted on Sessionize (auto-detected %s)' % today
            patch = {'status_tags': booked_tags(row['tags']),
                     'notes': (row['notes'].rstrip() + '\n' if row['notes'].strip() else '') + line,
                     'booking': dict(row['booking'], accepted_via='sessionize',
                                     speaking_booked_at=row['booking'].get('speaking_booked_at') or today),
                     'updated_by': 'Sessionize sync',
                     'updated_at': dt.datetime.now(dt.timezone.utc).isoformat()}
            entry = {'event': row['name'], 'person': person, 'table': row['table'], 'key': row['key'],
                     'matched': hit['event']['name'], 'written': False}
            if not dry_run:
                col = 'id' if row['table'] == 'manual_events' else 'event_num'
                wst, _ = _http('PATCH', '%s/rest/v1/%s?%s=eq.%s' % (
                    SUPABASE_URL, row['table'], col, urllib.parse.quote(str(row['key']))),
                    headers=_svc('return=minimal'), body=patch)
                entry['written'] = wst in (200, 204)
                if not entry['written']:
                    entry['error'] = 'write failed %s' % wst
            report['booked'].append(entry)
    return report


# ── HTTP ───────────────────────────────────────────────────────────────────
def _same_origin(handler):
    host = (handler.headers.get('Host', '') or '').lower().strip()
    if not host:
        return False
    for key in ('Origin', 'Referer'):
        v = (handler.headers.get(key, '') or '').lower().strip()
        if v:
            try:
                if urllib.parse.urlsplit(v).netloc == host:
                    return True
            except ValueError:
                pass
    return False


def _authorized(handler):
    provided = (handler.headers.get('X-API-Key', '') or '').strip()
    return bool(INGEST_SECRET) and bool(provided) and hmac.compare_digest(provided, INGEST_SECRET)


def _send(handler, status, payload, cache=''):
    body = json.dumps(payload, default=str).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', cache or 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if not _same_origin(self):
                return _send(self, 403, {'error': 'forbidden: call from tracker site'})
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if q.get('cfp'):
                url = page_url(q['cfp'][0])
                if not url:
                    return _send(self, 400, {'error': 'not a Sessionize event link'})
                st, page = fetch(url)
                info = parse_cfp(page) if st == 200 else None
                if not info:
                    return _send(self, 200, {'ok': False, 'url': url,
                                             'error': 'No call for speakers found at that link.'})
                return _send(self, 200, dict(info, ok=True, url=url), cache='private, max-age=600')
            if q.get('profile'):
                slug = q['profile'][0].strip().strip('/')
                if not _SLUG.match(slug) or slug.lower() in _RESERVED:
                    return _send(self, 400, {'error': 'not a speaker profile name'})
                st, page = fetch('https://sessionize.com/' + slug + '/')
                prof = parse_profile(page) if st == 200 else None
                if not prof:
                    return _send(self, 200, {'ok': False, 'error': 'No public speaker profile there.'})
                return _send(self, 200, dict(prof, ok=True), cache='private, max-age=600')
            return _send(self, 200, {'ok': True, 'hint': '?cfp=<sessionize link> or ?profile=<speaker-slug>',
                                     'watching': _profiles()})
        except Exception as e:  # noqa: BLE001 - always answer JSON
            return _send(self, 500, {'error': type(e).__name__, 'msg': str(e)[:300]})

    def do_POST(self):
        try:
            if not _authorized(self):
                return _send(self, 401, {'error': 'unauthorized'})
            if not SERVICE_ROLE:
                return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
            n = min(int(self.headers.get('Content-Length', '0') or '0'), 10000)
            try:
                body = json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}
            except json.JSONDecodeError:
                body = {}
            return _send(self, 200, sync(dry_run=bool(body.get('dry_run'))))
        except Exception as e:  # noqa: BLE001
            return _send(self, 500, {'error': type(e).__name__, 'msg': str(e)[:300]})
