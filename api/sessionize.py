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
  POST {"draft": {table, key}}        draft the application for one event: read
                                      its call for speakers, pick the best talk
                                      from the speaker's talk library, tailor it,
                                      and save it on the event as
                                      booking.sessionize_draft. "dry_run": true
                                      returns the draft without saving it.

GETs and the draft POST are same-origin only (the tracker page calls them). The
sync POST uses the same EVENTS_INGEST_SECRET as /api/enrich and is called from
daily-build.yml.

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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')
INGEST_SECRET = _env('EVENTS_INGEST_SECRET')
TRACKER_BASE = _env('TRACKER_BASE_URL', 'https://arcticblue-event-tracker-deploy.vercel.app').rstrip('/')
OPENAI_API_KEY = _env('OPENAI_API_KEY')
OPENAI_BASE = _env('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
# Same model the day-of briefs use unless a drafting model is set on its own.
DRAFT_MODELS = [m for m in dict.fromkeys([
    _env('OPENAI_DRAFT_MODEL') or _env('OPENAI_BRIEFING_MODEL') or 'gpt-5.4', 'gpt-4.1']) if m]

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
    out['name'] = re.sub(r'\s*:\s*Call for \w+.*$', '', title, flags=re.I).strip()
    out['opens'] = _iso(_after(page, 'Call opens at'))
    out['closes'] = _iso(_after(page, 'Call closes at'))
    tz = re.search(r'Call closes in\s*<strong>(.*?)</strong>', page, re.S | re.I)
    out['timezone'] = _text(tz.group(1)) if tz else ''
    out['event_start'] = _iso(_after(page, 'event starts')) or _iso(_after(page, 'event date'))
    out['event_end'] = _iso(_after(page, 'event ends')) or out['event_start']
    w = re.search(r'website\s*</div>\s*<h2[^>]*>\s*<a[^>]+href="([^"]+)"', page, re.S | re.I)
    out['website'] = _html.unescape(w.group(1)) if w else ''
    said = re.search(r'Call for \w+ is\s*<strong>\s*(\w+)', page, re.I)
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


def _url_key(u):
    """'https://www.developerweek.com/ai-devworld/' -> 'developerweek.com/ai-devworld'."""
    try:
        p = urllib.parse.urlsplit((u or '').strip() if '://' in (u or '') else 'https://' + (u or '').strip())
    except ValueError:
        return ''
    host = (p.hostname or '').lower()
    host = host[4:] if host.startswith('www.') else host
    return (host + p.path.rstrip('/')).lower() if host else ''


def _same_via_link(profile_event, row):
    """A profile entry is the row's event when it carries the name or the website
    the row's own Sessionize call gives (organisers rename events on Sessionize:
    'AI Engineer New York' is 'AIE NYC 2026' there). Dates still have to agree."""
    cfp = row.get('cfp') or {}
    if not cfp:
        return False
    if cfp.get('name') and same_event(profile_event, cfp['name'], cfp.get('event_start') or row.get('start_date')):
        return True
    a, b = _url_key(profile_event.get('url')), _url_key(cfp.get('website'))
    if not a or a != b:
        return False
    pe, ce = _year_month(profile_event.get('date')), _year_month(cfp.get('event_start') or row.get('start_date'))
    return bool(pe and ce and abs((pe[0] * 12 + pe[1]) - (ce[0] * 12 + ce[1])) <= 1)


def find_acceptances(person, profile_events, rows):
    """rows: [{table, key, name, speaker, tags, start_date, cfp?, ...}] -> (to_book, conflicts).
    `cfp` is what the row's saved Sessionize link says (name, website, dates)."""
    to_book, conflicts = [], []
    for row in rows:
        if person not in (row.get('speaker') or '').lower():
            continue
        tags = row.get('tags') or []
        if 'Submitted' not in tags or 'Booked' in tags:
            continue
        hit = next((e for e in profile_events if same_event(e, row.get('name'), row.get('start_date'))
                    or _same_via_link(e, row)), None)
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
                       'status,start_date,notes,booking,apply_url,speaking_route,url,deadline&limit=5000', headers=_svc())
    if st != 200 or not isinstance(manual, list):
        raise RuntimeError('manual_events read failed %s' % st)
    for m in manual:
        if m.get('status') == '__deleted__':
            continue
        rows.append({'table': 'manual_events', 'key': m['id'], 'name': m.get('name') or '',
                     'speaker': m.get('speaker') or '', 'tags': m.get('status_tags') or [],
                     'start_date': m.get('start_date') or '', 'notes': m.get('notes') or '',
                     'link': sessionize_link(m), 'apply_url': m.get('apply_url') or '',
                     'deadline': m.get('deadline') or '',
                     'mentions': bool(re.search('sessionize', ' '.join(str(m.get(f) or '') for f in
                                                                     ('notes', 'speaking_route', 'url')), re.I)),
                     'booking': m.get('booking') if isinstance(m.get('booking'), dict) else {}})
    st, states = _http('GET', SUPABASE_URL + '/rest/v1/event_state?select=event_num,name,speaker,status_tags,'
                       'status,start_date,notes,booking,apply_url,speaking_route,url,deadline&limit=5000', headers=_svc())
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
                     'link': sessionize_link(s, base), 'apply_url': s.get('apply_url') or '',
                     'deadline': s.get('deadline') or base.get('deadline') or '',
                     'mentions': bool(re.search('sessionize', ' '.join(str(x.get(f) or '') for x in (s, base) for f in
                                                                     ('notes', 'speaking_route', 'url')), re.I)),
                     'booking': s.get('booking') if isinstance(s.get('booking'), dict) else {}})
    return rows


def slug_guesses(name, start):
    """Likely Sessionize addresses for an event: its name with and without the
    year, hyphenated and run together (e.g. aidevworld-2027)."""
    yr = (start or '')[:4]
    base = unicodedata.normalize('NFD', name or '')
    base = ''.join(c for c in base if unicodedata.category(c) != 'Mn').lower()
    base = re.sub(r'\(.*?\)|\b(19|20)\d{2}\b|\b\d{1,2}(st|nd|rd|th)\b', ' ', base)
    words = [w for w in re.sub(r'[^a-z0-9]+', ' ', base).split() if w != 'the']
    out = []
    for ws in (words, [w for w in words if w not in ('summit', 'conference', 'forum', 'and', 'of')]):
        for s in ([('-'.join(ws)) + '-' + yr, ''.join(ws) + '-' + yr] if yr else []) + ['-'.join(ws), ''.join(ws)]:
            if ws and s.strip('-') and s not in out and _SLUG.match(s):
                out.append(s)
    return out[:6]


def tidy(rows, today, dry_run=False, max_guess=5):
    """Daily upkeep of the Sessionize side of upcoming events:
    - a linked call: remember whether it is open and when it closes
      (booking.sessionize_call, read by the queue), and use the closing date as
      the CFP deadline when the event has none;
    - an event whose notes say Sessionize but which has no link: try its likely
      addresses and save the one whose name and dates match."""
    report = {'calls_checked': 0, 'deadlines_set': [], 'links_found': [], 'writes': 0}
    guesses = 0
    for row in rows:
        if not row.get('start_date') or row['start_date'] < today:
            continue
        patch = {}
        if not row.get('link') and row.get('mentions') and not row.get('apply_url') and guesses < max_guess:
            guesses += 1
            for slug in slug_guesses(row['name'], row['start_date']):
                cst, cpage = fetch('https://sessionize.com/' + slug + '/')
                info = parse_cfp(cpage) if cst == 200 else None
                if info and same_event({'name': info['name'], 'date': info['event_start']}, row['name'], row['start_date']):
                    row['link'] = patch['apply_url'] = 'https://sessionize.com/' + slug + '/'
                    report['links_found'].append({'event': row['name'], 'link': row['link']})
                    break
        if row.get('link'):
            cst, cpage = fetch(row['link'])
            info = parse_cfp(cpage, dt.date.fromisoformat(today)) if cst == 200 else None
            if info:
                report['calls_checked'] += 1
                call = {'status': info['status'], 'opens': info['opens'], 'closes': info['closes'],
                        'timezone': info['timezone'], 'checked': today}
                old = dict((row.get('booking') or {}).get('sessionize_call') or {})
                old.pop('checked', None)
                if {k: v for k, v in call.items() if k != 'checked'} != old:
                    patch['booking'] = dict(row.get('booking') or {}, sessionize_call=call)
                if info['closes'] and not str(row.get('deadline') or '').strip():
                    patch['deadline'] = info['closes']
                    report['deadlines_set'].append({'event': row['name'], 'deadline': info['closes']})
        if patch and not dry_run:
            col = 'id' if row['table'] == 'manual_events' else 'event_num'
            patch['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            if row['table'] == 'event_state':
                patch['updated_by'] = 'Sessionize check'
                wst, _ = _http('POST', '%s/rest/v1/event_state?on_conflict=event_num' % SUPABASE_URL,
                               headers=_svc('resolution=merge-duplicates,return=minimal'),
                               body=dict(patch, event_num=row['key']))
            else:
                wst, _ = _http('PATCH', '%s/rest/v1/manual_events?id=eq.%s' % (SUPABASE_URL, urllib.parse.quote(str(row['key']))),
                               headers=_svc('return=minimal'), body=patch)
            if wst in (200, 201, 204):
                report['writes'] += 1
                if 'booking' in patch:
                    row['booking'] = patch['booking']
    return report


def sync(dry_run=False, today=None):
    today = (today or dt.date.today()).isoformat()
    report = {'ok': True, 'dry_run': bool(dry_run), 'people': {}, 'booked': [], 'conflicts': []}
    rows = _tracker_rows()
    report['tidy'] = tidy(rows, today, dry_run)
    for person, slug in _profiles().items():
        st, page = fetch('https://sessionize.com/' + slug + '/')
        prof = parse_profile(page) if st == 200 else None
        if not prof:
            report['people'][person] = {'profile': slug, 'error': 'profile not readable (%s)' % st}
            continue
        report['people'][person] = {'profile': slug, 'events_on_profile': len(prof['events'])}
        if not prof['events']:
            continue                      # nothing accepted yet: no need to load the tracker
        # Organisers rename events on Sessionize, so read each pending
        # application's own call (name, website, dates) to match by those too.
        for row in rows:
            if (row.get('link') and 'cfp' not in row and person in (row.get('speaker') or '').lower()
                    and 'Submitted' in (row.get('tags') or []) and 'Booked' not in (row.get('tags') or [])):
                cst, cpage = fetch(row['link'])
                row['cfp'] = (parse_cfp(cpage) if cst == 200 else None) or {}
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


# ── Drafting an application ────────────────────────────────────────────────
# The speaker picks events in the Application queue ("Apply"); for each one with
# a Sessionize link this writes the application: the best talk from their talk
# library (config/talks/<person>.json, or the copy edited in the tracker, saved
# to storage at profiles/<person>/talks/library.json), tailored to what the
# call for speakers asks for. It is saved on the event for a person to check,
# copy into the form and submit. Nothing here touches Sessionize beyond reading
# the public page.
_LINK = re.compile(r'(?:https?://|(?<![\w@./]))(?:www\.)?sessionize\.com/[^\s)"\'<>\]]+', re.I)
_PERK = re.compile(r'<h3 class="no-margins font-normal">(.*?)</h3>\s*<div class="font-bold text-navy">(.*?)</div>', re.S)
_TERM_KINDS = ('fee', 'sponsorship', 'travel', 'accommodation', 'in_person', 'recording',
               'code_of_conduct', 'exclusivity', 'other')


def sessionize_link(*records):
    """The first Sessionize event link in the fields the tracker keeps it in."""
    for rec in records:
        for f in ('apply_url', 'speaking_route', 'url', 'notes'):
            for m in _LINK.finditer(str((rec or {}).get(f) or '')):
                url = page_url(m.group(0).rstrip('.,;:!?'))
                if url:
                    return url
    return ''


def cfp_details(page):
    """The organiser's own words on a call-for-speakers page, plus the perks box
    (event fee, travel, accommodation). Only what any visitor can see: tracks,
    session formats and custom questions often appear only on the signed-in form."""
    perks = {}
    for label, value in _PERK.findall(page or ''):
        k, v = _text(label).lower(), _text(value)
        if k and v:
            perks[k] = v
    body = page or ''
    i = body.find('<body')
    body = body[i:] if i >= 0 else body
    body = re.sub(r'<(script|style|noscript)\b.*?</\1>', ' ', body, flags=re.S | re.I)
    body = re.sub(r'<br\s*/?>|</p>|</div>|</li>|</h\d>', '\n', body, flags=re.I)
    text = _html.unescape(re.sub(r'<[^>]+>', ' ', body))
    lines = [re.sub(r'[ \t\xa0]+', ' ', ln).strip() for ln in text.split('\n')]
    text = '\n'.join(ln for ln in lines if ln)
    for stop in ('Submit a session', 'Login with your preferred account'):
        j = text.find(stop)
        if j > 0:
            text = text[:j]
    text = re.sub(r'^\s*Sessionize\.com\s+Log in\s*', '', text)
    return {'text': text.strip()[:9000], 'perks': perks}


def term_flags(details):
    """What the perks box alone says a speaker signs up to. The model adds what it
    finds in the organiser's text; these never depend on the model."""
    out = []
    perks = (details or {}).get('perks') or {}
    fee = perks.get('event fee', '')
    if fee and 'free' not in fee.lower():
        out.append({'kind': 'fee', 'text': 'Event fee: ' + fee,
                    'why_it_matters': 'Speaking here may cost money (pay-to-play). Decide before submitting.'})
    for k in ('travel', 'accommodation'):
        v = perks.get(k, '')
        if v and re.search(r'\b(not|no|own|self)\b', v, re.I):
            out.append({'kind': k, 'text': k.capitalize() + ': ' + v,
                        'why_it_matters': 'Thor pays his own ' + ('travel' if k == 'travel' else 'hotel') + ' if accepted.'})
    text = (details or {}).get('text', '')
    m = re.search(r'[^.\n]*\b(?:must|required to|need to)\b[^.\n]*\bin[- ]person\b[^.\n]*|[^.\n]*\bin[- ]person\b[^.\n]*\b(?:required|only|must)\b[^.\n]*', text, re.I)
    if m:
        out.append({'kind': 'in_person', 'text': m.group(0).strip()[:240],
                    'why_it_matters': 'Accepting means being there in person on the date.'})
    return out


def load_talks(person):
    """(library, where) — the copy saved from the tracker wins over the starting set."""
    person = re.sub(r'[^a-z]', '', (person or '').lower())
    if not person:
        return None, ''
    if SERVICE_ROLE:
        st, data = _http('GET', '%s/storage/v1/object/profiles/%s/talks/library.json' % (SUPABASE_URL, person),
                         headers=_svc())
        if st == 200 and isinstance(data, dict) and data.get('talks'):
            return data, 'saved'
    try:
        with open(os.path.join(ROOT, 'config', 'talks', person + '.json')) as f:
            return json.load(f), 'starting set'
    except (OSError, ValueError):
        return None, ''


def _event_row(table, key):
    """The tracker's record for one event: the row itself plus, for a catalog
    event, the static catalog entry its name and dates live in."""
    if table not in ('manual_events', 'event_state'):
        raise ValueError('table must be manual_events or event_state')
    col = 'id' if table == 'manual_events' else 'event_num'
    st, rows = _http('GET', '%s/rest/v1/%s?%s=eq.%s&select=*' % (
        SUPABASE_URL, table, col, urllib.parse.quote(str(key))), headers=_svc())
    if st != 200 or not isinstance(rows, list):
        raise RuntimeError('%s read failed %s' % (table, st))
    row = rows[0] if rows else None
    base = {}
    if table == 'event_state':
        cst, cat = _http('GET', TRACKER_BASE + '/events.json', headers={'User-Agent': _UA})
        if cst == 200 and isinstance(cat, dict):
            base = next((e for e in cat.get('events') or [] if str(e.get('num')) == str(key)), {})
        if not base and not row:
            raise LookupError('no event %s' % key)
    elif not row:
        raise LookupError('no manual event %s' % key)
    return row, base


def _pick(row, base, f):
    v = (row or {}).get(f)
    if v in (None, '', '__cleared__'):
        v = (base or {}).get(f)
    return v if v not in (None, '__cleared__') else ''


_NUM = re.compile(r'\d[\d,.]*')


def _numbers(s):
    return {n.replace(',', '').rstrip('.') for n in _NUM.findall(s or '')}


def number_checks(draft, sources):
    """Numbers in the draft that appear in none of its sources — a likely
    invention, shown to whoever reviews the draft."""
    allowed = _numbers(sources)
    seen = []
    texts = [draft.get('title'), draft.get('short_abstract'), draft.get('abstract')] + \
        list(draft.get('takeaways') or []) + [a.get('answer') for a in draft.get('answers') or []]
    for t in texts:
        for n in sorted(_numbers(t)):
            if n not in allowed and n not in seen:
                seen.append(n)
    return ['Check this number, it is not in the talk, the bio or the call: ' + n for n in seen]


def _clip(s, n):
    s = re.sub(r'[ \t]+', ' ', str(s or '')).strip()
    return s if len(s) <= n else s[:n - 1].rsplit(' ', 1)[0] + '…'


def clean_draft(raw, library):
    """The model's JSON -> the stored draft. Anything malformed is dropped rather
    than trusted, and the talk must be one from the library."""
    talks = {t.get('id'): t for t in (library or {}).get('talks') or [] if t.get('id')}
    raw = raw if isinstance(raw, dict) else {}
    tid = raw.get('talk_id') if raw.get('talk_id') in talks else next(iter(talks), '')
    talk = talks.get(tid, {})
    take = [_clip(x, 300) for x in (raw.get('takeaways') or []) if isinstance(x, str) and x.strip()][:5]
    answers = []
    for a in raw.get('answers') or []:
        if isinstance(a, dict) and str(a.get('question') or '').strip() and str(a.get('answer') or '').strip():
            answers.append({'question': _clip(a['question'], 400), 'answer': _clip(a['answer'], 2500)})
    terms = []
    for t in raw.get('terms') or []:
        if isinstance(t, dict) and str(t.get('text') or '').strip():
            k = t.get('kind') if t.get('kind') in _TERM_KINDS else 'other'
            terms.append({'kind': k, 'text': _clip(t['text'], 400),
                          'why_it_matters': _clip(t.get('why_it_matters'), 300)})
    return {
        'talk_id': tid,
        'talk_title': talk.get('title', ''),
        'talk_status': talk.get('status', 'draft'),
        'fit': raw.get('fit') if raw.get('fit') in ('strong', 'fair', 'weak') else 'fair',
        'why_this_talk': _clip(raw.get('why_this_talk'), 400),
        'title': _clip(raw.get('title') or talk.get('title'), 200),
        'short_abstract': _clip(raw.get('short_abstract') or talk.get('short_abstract'), 800),
        'abstract': _clip(raw.get('abstract') or talk.get('abstract'), 4000),
        'format': _clip(raw.get('format'), 120),
        'track': _clip(raw.get('track'), 160),
        'level': _clip(raw.get('level') or talk.get('level'), 80),
        'takeaways': take or list(talk.get('takeaways') or []),
        'answers': answers[:12],
        'terms': terms[:12],
        'unknowns': [_clip(u, 300) for u in (raw.get('unknowns') or []) if isinstance(u, str) and u.strip()][:8],
    }


def _merge_terms(fixed, found):
    out, kinds = list(fixed), {t['kind'] for t in fixed}
    for t in found:
        if t['kind'] in kinds and t['kind'] != 'other':
            continue
        if t['kind'] == 'fee' and re.search(r'\bfree\b', t['text'], re.I) and not re.search(r'[$€£]|\d', t['text']):
            continue                  # "free for speakers" commits nobody to anything
        out.append(t)
    return out


def draft_prompt(event, cfp, details, library):
    sp = library.get('speaker') or {}
    talks = [{k: t.get(k) for k in ('id', 'status', 'title', 'alt_titles', 'level', 'formats', 'audience',
                                    'short_abstract', 'abstract', 'takeaways')}
             for t in library.get('talks') or []]
    system = (
        'You draft conference speaking applications for ' + (sp.get('name') or 'the speaker') + '. '
        'Write in their voice: ' + (sp.get('voice') or 'direct, plain, no hype') + '\n'
        'Rules:\n'
        '- Use ONLY facts from SPEAKER FACTS and the chosen talk. Never invent numbers, clients, results, '
        'quotes, awards, past events or credentials. If an answer needs a fact you do not have, write '
        '[ASK THOR: <what is needed>] in its place.\n'
        '- Choose the ONE talk from TALK LIBRARY that best fits this call. When two fit about equally, '
        'prefer one whose status is "approved".\n'
        '- Keep the talk\'s argument and examples. Tailor lightly: the title keeps its recognisable core; '
        'the abstract speaks to this event\'s audience, themes and tracks in the call\'s own vocabulary.\n'
        '- Respect any length limit the call states. Otherwise: abstract at most 950 characters, '
        'short_abstract at most 350.\n'
        '- format and level: pick from options the call lists. If it lists none, leave the field empty and '
        'add it to unknowns (it will be on the signed-in form).\n'
        '- track: if the call names tracks, themes or topic areas (even "for inspiration"), put the closest '
        'one here, prefixed by its group when there is one (e.g. "Main Stage: Change Management"). Leave it '
        'empty only when the call names none.\n'
        '- answers: one entry for each question or requirement the call text asks speakers to address '
        '(why you, audience, preferred date, in person, etc.). Do not invent questions the call does not ask. '
        'A question that is the speaker\'s own decision or availability (can you attend in person, which '
        'date, travel, joining future events, paying anything) is never answered for them: its answer is '
        '[ASK THOR: <the question>].\n'
        '- terms: everything submitting or accepting would commit the speaker to: fees to speak or attend '
        '(pay-to-play), sponsorship, paying own travel or hotel, in-person attendance, recording or '
        'publishing consent, code of conduct, exclusivity, content rules. Only what the call actually '
        'states, quoting its words in text; never infer a term from a venue or location (put open '
        'questions in unknowns). A free event fee is not a term.\n'
        '- Return one JSON object and nothing else.'
    )
    user = (
        'EVENT (from our tracker):\n' + json.dumps(event, ensure_ascii=False) + '\n\n'
        'CALL FOR SPEAKERS (public page; tracks, formats and custom questions may only appear on the '
        'signed-in form):\n' + json.dumps({k: cfp.get(k) for k in ('name', 'status', 'opens', 'closes', 'timezone',
                                                                   'event_start', 'event_end', 'website')},
                                          ensure_ascii=False) +
        '\nPerks box: ' + json.dumps(details.get('perks') or {}, ensure_ascii=False) +
        '\nPage text:\n"""\n' + (details.get('text') or '') + '\n"""\n\n'
        'SPEAKER FACTS:\n' + '\n'.join('- ' + f for f in sp.get('facts') or []) + '\n\n'
        'TALK LIBRARY:\n' + json.dumps(talks, ensure_ascii=False) + '\n\n'
        'Return JSON with exactly these keys:\n'
        '{"talk_id": "", "fit": "strong|fair|weak", "why_this_talk": "one sentence", "title": "", '
        '"short_abstract": "", "abstract": "", "format": "", "track": "", "level": "", '
        '"takeaways": ["", "", ""], "answers": [{"question": "", "answer": ""}], '
        '"terms": [{"kind": "fee|sponsorship|travel|accommodation|in_person|recording|code_of_conduct|exclusivity|other", '
        '"text": "", "why_it_matters": ""}], "unknowns": [""]}'
    )
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def _json_from(text):
    text = (text or '').strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def call_model(messages):
    """(parsed JSON, model) from the first model that answers with JSON."""
    last = ''
    for model in DRAFT_MODELS:
        m = model.lower()
        body = {'model': model, 'messages': messages}
        body['max_completion_tokens' if m.startswith(('gpt-5', 'o1', 'o3', 'o4')) else 'max_tokens'] = 6000
        if 'search' not in m:
            body['response_format'] = {'type': 'json_object'}
        req = urllib.request.Request(OPENAI_BASE + '/chat/completions', method='POST', data=json.dumps(body).encode(),
                                     headers={'Authorization': 'Bearer ' + OPENAI_API_KEY,
                                              'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=100) as r:
                data = json.loads(r.read().decode('utf-8'))
            out = _json_from(((data.get('choices') or [{}])[0].get('message') or {}).get('content'))
            if isinstance(out, dict):
                return out, model
            last = model + ': no JSON in the answer'
        except urllib.error.HTTPError as e:
            last = '%s: HTTP %s %s' % (model, e.code, e.read().decode('utf-8', errors='replace')[:200])
        except Exception as e:  # noqa: BLE001
            last = '%s: %s' % (model, str(e)[:200])
    raise RuntimeError('drafting model failed (' + last + ')')


def make_draft(table='', key=None, cfp_url='', event=None, dry_run=False, by='', today=None, model=None):
    """Draft one application. table/key name a tracker event; cfp_url + event is
    a dry run against any call (nothing to save it on). `model` replaces the
    OpenAI call in tests."""
    today = today or dt.date.today()
    row, base = (None, {})
    if table:
        row, base = _event_row(table, key)
        cfp_url = sessionize_link(row, base)
        if not cfp_url:
            return {'ok': False, 'error': 'This event has no Sessionize link.'}
        event = {'name': _pick(row, base, 'name'), 'dates': _pick(row, base, 'date_str') or _pick(row, base, 'start_date'),
                 'location': _pick(row, base, 'location'), 'type': _pick(row, base, 'type'),
                 'about': _clip(_pick(row, base, 'about') or _pick(row, base, 'why'), 1500),
                 'focus_areas': _pick(row, base, 'focus_areas')}
    else:
        cfp_url = page_url(cfp_url)
        if not cfp_url:
            return {'ok': False, 'error': 'not a Sessionize event link'}
        if not dry_run:
            return {'ok': False, 'error': 'a draft with no tracker event can only be a dry run'}
        event = event or {}
    person = re.sub(r'[^a-z]', ' ', str(_pick(row, base, 'speaker') if row or base else '').lower()).split()
    person = person[0] if person else 'thor'
    library, where = load_talks(person)
    if not library:
        return {'ok': False, 'error': 'No talk library for %s yet.' % person.capitalize()}
    st, page = fetch(cfp_url)
    cfp = parse_cfp(page, today) if st == 200 else None
    if not cfp:
        return {'ok': False, 'error': 'Could not read the call for speakers at %s.' % cfp_url}
    if cfp['status'] == 'closed':
        return {'ok': False, 'error': 'The call for speakers closed%s.' % (' on ' + cfp['closes'] if cfp['closes'] else '')}
    details = cfp_details(page)
    raw, used = model(draft_prompt(event, cfp, details, library)) if model else call_model(
        draft_prompt(event, cfp, details, library))
    d = clean_draft(raw, library)
    d['terms'] = _merge_terms(term_flags(details), d['terms'])
    talk = next((t for t in library.get('talks') or [] if t.get('id') == d['talk_id']), {})
    sources = ' '.join([json.dumps(talk, ensure_ascii=False), ' '.join((library.get('speaker') or {}).get('facts') or []),
                        details['text'], json.dumps(event, ensure_ascii=False), json.dumps(cfp)])
    d['checks'] = number_checks(d, sources)
    if len(d['abstract']) > 1000:
        d['checks'].append('The abstract is %d characters. Many forms cap it at 1,000: check the limit and trim.'
                           % len(d['abstract']))
    if d['talk_status'] != 'approved':
        d['checks'].insert(0, 'The talk “%s” is still a draft in the talk library: Thor has not approved it yet.' % d['talk_title'])
    d.update({'status': 'ready', 'person': person, 'library': where, 'model': used,
              'cfp': {'url': cfp_url, 'status': cfp['status'], 'closes': cfp['closes'], 'timezone': cfp['timezone']},
              'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'by': by or ''})
    out = {'ok': True, 'draft': d, 'written': False, 'dry_run': bool(dry_run)}
    if dry_run or not table:
        return out
    booking = dict((row or {}).get('booking') or {}) if isinstance((row or {}).get('booking'), dict) else {}
    booking['sessionize_draft'] = d
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    col = 'id' if table == 'manual_events' else 'event_num'
    if row:
        wst, _ = _http('PATCH', '%s/rest/v1/%s?%s=eq.%s' % (SUPABASE_URL, table, col, urllib.parse.quote(str(key))),
                       headers=_svc('return=minimal'), body={'booking': booking, 'updated_at': now})
    else:   # a catalog event nobody has touched yet: start its state row
        wst, _ = _http('POST', '%s/rest/v1/event_state' % SUPABASE_URL, headers=_svc('return=minimal'),
                       body={'event_num': key, 'booking': booking, 'updated_by': by or 'Sessionize draft',
                             'updated_at': now})
    out['written'] = wst in (200, 201, 204)
    if not out['written']:
        out['error'] = 'The draft was written but could not be saved (%s).' % wst
    return out


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
            n = min(int(self.headers.get('Content-Length', '0') or '0'), 20000)
            try:
                body = json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}
            except json.JSONDecodeError:
                body = {}
            if isinstance(body, dict) and isinstance(body.get('draft'), dict):
                # The tracker page asks for a draft: same-origin, like the GETs.
                if not (_same_origin(self) or _authorized(self)):
                    return _send(self, 403, {'error': 'forbidden: call from tracker site'})
                if not OPENAI_API_KEY:
                    return _send(self, 500, {'error': 'OPENAI_API_KEY missing'})
                if not SERVICE_ROLE:
                    return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
                d = body['draft']
                try:
                    return _send(self, 200, make_draft(
                        table=str(d.get('table') or ''), key=d.get('key'), cfp_url=str(d.get('cfp') or ''),
                        event=d.get('event') if isinstance(d.get('event'), dict) else None,
                        dry_run=bool(body.get('dry_run')), by=str(body.get('by') or '')[:80]))
                except LookupError as e:
                    return _send(self, 404, {'ok': False, 'error': str(e)})
                except ValueError as e:
                    return _send(self, 400, {'ok': False, 'error': str(e)})
            if not _authorized(self):
                return _send(self, 401, {'error': 'unauthorized'})
            if not SERVICE_ROLE:
                return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
            return _send(self, 200, sync(dry_run=bool(body.get('dry_run'))))
        except Exception as e:  # noqa: BLE001
            return _send(self, 500, {'error': type(e).__name__, 'msg': str(e)[:300]})
