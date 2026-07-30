"""POST /api/enrich_one — research ONE event on demand and fill its gaps.

Powers the per-event "Enrich" button in the tracker UI. Given a single event
(name, date, location, plus whatever is already known), it researches the
missing facts via Perplexity + Exa and writes ONLY the empty fields back to
the right table:

  - table="manual_events", key=<id>      -> PATCH that row
  - table="event_state",   key=<event_num> -> UPSERT override columns for a
                                              catalog event (base data stays in
                                              events.json; overrides win in UI)

NEVER overwrites a value already present in the posted event. Returns the patch
that was applied so the client can update the open modal immediately.

This endpoint is intentionally open (the whole tracker is no-login) but is
capped to ONE event per call and only acts on events that carry a name — it
spends one research credit per click, by design. The heavy nightly sweep
(/api/enrich) stays behind the ingest secret.

NOTE: helper functions are duplicated from api/enrich.py because Vercel bundles
each function in isolation — keep them in sync.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import date


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')

EXA_API_KEY = _env('EXA_API_KEY')
EXA_BASE    = _env('EXA_BASE_URL', 'https://api.exa.ai').rstrip('/')

PPLX_API_KEY = _env('PERPLEXITY_API_KEY')
PPLX_MODEL   = _env('PERPLEXITY_MODEL', 'sonar')
PPLX_BASE    = _env('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai').rstrip('/')

# Columns we are allowed to write (exist on BOTH manual_events and, after the
# enrich-columns migration, event_state).
WRITABLE = ('url', 'venue', 'pay_to_play', 'speaking_route', 'pricing',
            'past_speakers', 'meeting_formats', 'audience_type',
            'typical_attendees', 'attendee_count', 'deadline',
            'about', 'focus_areas')


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


def _svc_headers():
    return {
        'apikey':        SERVICE_ROLE,
        'Authorization': 'Bearer ' + SERVICE_ROLE,
        'Content-Type':  'application/json',
    }


# ── Exa apply-link discovery ─────────────────────────────────────────
_APPLY_SIGNALS = (
    'call-for-speaker', 'call_for_speaker', 'callforspeaker', 'call for speaker',
    'call-for-paper', 'call for paper', 'cfp',
    'submit-speaker', 'submit-a-speaker', 'submit a speaker', 'submit-talk',
    'speaker-application', 'application-speaker', 'speaker-submission',
    'apply-to-speak', 'apply to speak', 'become-a-speaker', 'become a speaker',
    'speak-at', 'speaking-opportunit', 'speaking opportunit',
    'speaker-enquir', 'speakers-enquir', 'speaker enquir', 'speaker-inquir',
    'suggest-a-speaker', 'suggest a speaker', 'speaker-opt-in', 'speaker opt-in',
    'speaker-interest', 'propose-a-talk', 'propose a talk', 'sessionize.com',
)
_TWO_PART_TLDS = ('co.uk', 'com.au', 'co.nz', 'co.jp', 'com.br', 'co.za', 'org.uk')


def _looks_like_apply(url, title):
    hay = ('%s %s' % (url or '', title or '')).lower()
    return any(sig in hay for sig in _APPLY_SIGNALS)


def _domain_of(url):
    if not url:
        return ''
    try:
        netloc = urllib.parse.urlsplit(url if '://' in url else 'https://' + url).netloc
    except ValueError:
        return ''
    netloc = netloc.split('@')[-1].split(':')[0].strip().lower()
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    labels = [p for p in netloc.split('.') if p]
    if len(labels) <= 2:
        return '.'.join(labels)
    last3 = '.'.join(labels[-3:])
    for tld in _TWO_PART_TLDS:
        if last3.endswith(tld):
            return last3
    return '.'.join(labels[-2:])


def _exa_search(query, include_domains=None, num=8):
    if not EXA_API_KEY:
        return []
    body = {'query': query, 'numResults': num, 'type': 'auto'}
    if include_domains:
        body['includeDomains'] = include_domains
    status, data = _http_json(
        'POST', EXA_BASE + '/search',
        headers={'x-api-key': EXA_API_KEY, 'Content-Type': 'application/json'},
        body=body, timeout=12)
    out = []
    if status == 200 and isinstance(data, dict):
        for r in (data.get('results') or []):
            if isinstance(r, dict) and r.get('url'):
                out.append({'url': r.get('url'), 'title': r.get('title') or ''})
    return out


_AGGREGATOR_DOMAINS = {
    'eventbrite.com', 'linkedin.com', 'facebook.com', 'instagram.com',
    'twitter.com', 'x.com', 'youtube.com', 'wikipedia.org', 'medium.com',
    'reddit.com', 'meetup.com', 'lu.ma', '10times.com', 'allevents.in',
    'eventslooped.com', 'conferenceindex.org', 'clocate.com', 'tradefairdates.com',
}


def find_homepage(name, location=None):
    if not (EXA_API_KEY and name):
        return None
    q = '%s official website' % name
    if location:
        q += ' %s' % str(location).split(',')[0]
    for r in _exa_search(q, num=8):
        dom = _domain_of(r['url'])
        if not dom or dom in _AGGREGATOR_DOMAINS:
            continue
        if _name_matches_domain(name, r['url']):
            return r['url']
    return None


def find_speaking_route(name, home_url):
    if not (EXA_API_KEY and name):
        return None
    dom = _domain_of(home_url)
    if not dom:
        return None
    query = ('%s call for speakers OR apply to speak OR submit a speaker '
             'OR speaker application' % name)
    for r in _exa_search(query, include_domains=[dom], num=8):
        if _looks_like_apply(r['url'], r['title']) and _domain_of(r['url']) == dom:
            return r['url']
    return None


# ── Perplexity fact research ─────────────────────────────────────────
_PPLX_SYSTEM = (
    "You research business conferences. Given ONE specific event (name, date, "
    "location), return ONLY a raw JSON object — no prose, no markdown fences — "
    "with any of these keys you can verify for THIS exact event edition:\n"
    '  "official_url": the event\'s official homepage URL\n'
    '  "venue": the venue name\n'
    '  "pricing": cost to ATTEND (delegate/ticket price). If buyers/end-users '
    "and vendors/suppliers pay different rates, state both tiers\n"
    '  "pay_to_play": "Yes" | "No" | "Unknown" — are speaking slots typically '
    "tied to paid sponsorship?\n"
    '  "past_speakers": 3-8 notable past or announced speakers as '
    '"Title, Company" pairs, semicolon-separated\n'
    '  "meeting_formats": built-in ways attendees MEET: guaranteed/hosted 1:1 '
    "meetings, curated roundtables, or an attendee app for pre-booking "
    "meetings\n"
    '  "audience": "Buyer-rich" | "Mixed" | "Vendor-heavy" — are attendees '
    "mostly in-house enterprise buyers/decision-makers, or vendors selling?\n"
    '  "typical_attendees": one short line on who attends (roles/seniority)\n'
    '  "attendee_count": approximate attendance, e.g. "5,000+"\n'
    '  "deadline": call-for-speakers deadline if published\n'
    '  "about": what this event IS — plain English, brief, and dense with '
    "fact. Cover the INDUSTRIES it serves, the kind and SCALE of event, WHO it "
    "draws, WHAT GETS DISCUSSED, and anything genuinely distinctive. Two to "
    "three sentences, roughly 25-60 words.\n"
    "    - THIS IS THE BAR (Hurley's own example): \"Ai4 is one of the largest "
    "enterprise AI conferences, bringing together thousands of enterprise "
    "leaders, practitioners, and vendors focused on real-world AI deployment.\" "
    "Every clause there earns its place — scale, audience, angle.\n"
    "    - Leading with the name is fine ONLY if what follows adds something. "
    "\"World Health AI Forum is a World Health AI conference focused on the "
    "intersection of healthcare and artificial intelligence\" defines the event "
    "with its own words and is worthless.\n"
    "    - Never repeat the date or the city — the card shows them directly "
    "above this text.\n"
    "    - Cut any phrase that would fit ANY conference: \"focused on the "
    "intersection of\", \"centers on\", \"brings together leaders to discuss\", "
    "\"innovation and data-driven models\", \"cutting-edge\", \"premier\", "
    "\"leading\".\n"
    "    - HOW PEOPLE MEET belongs in \"meeting_formats\", not here — the card "
    "merges that in for you. Mention format here only when it defines the event "
    "(invite-only assembly, hosted-buyer model, 1:1 matchmaking).\n"
    '  "focus_areas": the event\'s main themes / tracks / topics as a short '
    "comma-separated list (e.g. 'AI governance, agentic workflows, fintech')\n"
    '  "speaking_route": how a speaker gets on stage — a CFP / speaker-'
    "application / nomination URL or a one-line note, if published\n"
    "OMIT every key you are not confident about. Never invent URLs or facts."
)


def perplexity_facts(ev):
    if not PPLX_API_KEY:
        return {}
    known = {k: ev.get(k) for k in ('name', 'date_str', 'location', 'url')
             if ev.get(k)}
    payload = {
        'model': PPLX_MODEL,
        'messages': [
            {'role': 'system', 'content': _PPLX_SYSTEM},
            {'role': 'user', 'content': json.dumps(known, ensure_ascii=False)},
        ],
        'temperature': 0.1,
        'max_tokens': 700,
    }
    status, data = _http_json(
        'POST', PPLX_BASE + '/chat/completions',
        headers={'Authorization': 'Bearer ' + PPLX_API_KEY},
        body=payload, timeout=30)
    if status != 200 or not isinstance(data, dict):
        return {}
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return {}
    m = re.search(r'\{.*\}', content, re.S)
    if not m:
        return {}
    try:
        facts = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return facts if isinstance(facts, dict) else {}


def _name_matches_domain(name, url):
    dom = _domain_of(url).replace('-', '')
    if not dom:
        return False
    toks = re.findall(r'[a-z0-9]{3,}', (name or '').lower())
    skip = {'the', 'and', 'for', 'summit', 'conference', 'expo', 'forum',
            'event', 'events', '2025', '2026', '2027', 'world', 'global'}
    toks = [t for t in toks if t not in skip]
    return any(t in dom for t in toks)


def _norm_audience(v):
    s = str(v or '').strip().lower()
    if not s:
        return None
    if 'buyer' in s:
        return 'Buyer-rich'
    if 'vendor' in s or 'seller' in s:
        return 'Vendor-heavy'
    if 'mixed' in s or 'balanced' in s:
        return 'Mixed'
    return None


def _norm_p2p(v):
    s = str(v or '').strip().lower()
    if s.startswith('yes'):
        return 'Yes'
    if s.startswith('no') and not s.startswith('not'):
        return 'No'
    return None


_JUNK_PREFIXES = ('unknown', 'n/a', 'na', 'none', 'not available', 'not verified',
                  'not specified', 'not publicly', 'not announced', 'not found',
                  'not yet', 'not published', 'not listed', 'not disclosed',
                  'no deadline', 'no public', 'no cfp', 'likely passed',
                  'unclear', 'tbd', 'to be', 'varies', 'unavailable')


def _junk(v):
    s = str(v or '').strip().lower()
    if not s:
        return True
    return any(s.startswith(p) for p in _JUNK_PREFIXES)


_MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july',
     'august', 'september', 'october', 'november', 'december'], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})


def _parse_concrete_date(s):
    if not s:
        return None
    s = str(s)
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', s)
    if m and m.group(1).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', s)
    if m and m.group(2).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    return None


def _deadline_sane(deadline, start_iso):
    dl = _parse_concrete_date(deadline)
    if not dl or not start_iso:
        return True
    try:
        return dl <= date.fromisoformat(str(start_iso)[:10])
    except ValueError:
        return True


def merge_missing(row, facts, rewrite=None):
    """Fill blanks. `rewrite` names columns that may be REPLACED even when they
    already hold something — used to re-do a weak description without having to
    clear the field by hand first (Hurley 2026-07-29). Default stays fill-only,
    so the normal Enrich button can never overwrite someone's typing.
    """
    patch = {}
    rewrite = {str(c).strip() for c in (rewrite or []) if str(c).strip()}

    def empty(col):
        if col in rewrite:
            return True
        v = row.get(col)
        return v is None or str(v).strip() == ''

    if empty('url') and not _junk(facts.get('official_url')):
        u = str(facts['official_url']).strip()
        if u.startswith('http') and _name_matches_domain(row.get('name'), u):
            patch['url'] = u
    if empty('venue') and not _junk(facts.get('venue')):
        patch['venue'] = str(facts['venue']).strip()[:200]
    if empty('pricing') and not _junk(facts.get('pricing')):
        patch['pricing'] = str(facts['pricing']).strip()[:300]
    if empty('pay_to_play'):
        p = _norm_p2p(facts.get('pay_to_play'))
        if p:
            patch['pay_to_play'] = p
    if empty('past_speakers') and facts.get('past_speakers'):
        v = facts['past_speakers']
        if isinstance(v, list):
            v = '; '.join(str(x) for x in v)
        if not _junk(v):
            patch['past_speakers'] = str(v).strip()[:600]
    if empty('meeting_formats') and not _junk(facts.get('meeting_formats')):
        patch['meeting_formats'] = str(facts['meeting_formats']).strip()[:300]
    if empty('audience_type'):
        a = _norm_audience(facts.get('audience'))
        if a:
            patch['audience_type'] = a
    if empty('typical_attendees') and not _junk(facts.get('typical_attendees')):
        patch['typical_attendees'] = str(facts['typical_attendees']).strip()[:300]
    if empty('attendee_count') and not _junk(facts.get('attendee_count')):
        patch['attendee_count'] = str(facts['attendee_count']).strip()[:60]
    if empty('deadline') and not _junk(facts.get('deadline')):
        dl = str(facts['deadline']).strip()[:120]
        if _deadline_sane(dl, row.get('start_date')):
            patch['deadline'] = dl
    # The "bigger" descriptive sections Angela wants filled (not just small facts).
    if empty('about') and not _junk(facts.get('about')):
        patch['about'] = str(facts['about']).strip()[:600]
    if empty('focus_areas') and not _junk(facts.get('focus_areas')):
        v = facts['focus_areas']
        if isinstance(v, list):
            v = ', '.join(str(x) for x in v)
        if not _junk(v):
            patch['focus_areas'] = str(v).strip()[:400]
    return patch


def enrich_one(row, rewrite=None):
    facts = perplexity_facts(row)
    patch = merge_missing(row, facts, rewrite=rewrite)
    home = row.get('url') or patch.get('url')
    if not home:
        try:
            home = find_homepage(row.get('name'), row.get('location'))
        except Exception:
            home = None
        if home:
            patch['url'] = home
    if not (row.get('speaking_route') or '').strip():
        route = None
        if home:
            try:
                route = find_speaking_route(row.get('name'), home)
            except Exception:
                route = None
        if route:
            patch['speaking_route'] = 'Apply to speak: ' + route
        elif not _junk(facts.get('speaking_route')):
            # Perplexity fallback when the Exa speaker-page search finds nothing
            # (so Angela doesn't have to add the route by hand).
            patch['speaking_route'] = str(facts['speaking_route']).strip()[:300]
    return patch


# ── HTTP plumbing ────────────────────────────────────────────────────
def _send(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        _send(self, 405, {
            'error': 'method not allowed',
            'hint': 'POST {"event": {...}, "table": "event_state|manual_events", '
                    '"key": <num|id>} to research one event and fill its gaps.',
        })

    def do_POST(self):
        try:
            self._handle()
        except Exception as e:  # noqa: BLE001 — always answer JSON
            _send(self, 500, {'error': 'unhandled', 'type': type(e).__name__,
                              'msg': str(e)[:500]})

    def _handle(self):
        if not SERVICE_ROLE:
            return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
        if not (PPLX_API_KEY or EXA_API_KEY):
            return _send(self, 200, {'skipped': 'no PERPLEXITY_API_KEY or '
                                                'EXA_API_KEY configured'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
        except (ValueError, json.JSONDecodeError):
            body = {}

        ev = body.get('event')
        table = body.get('table')
        key = body.get('key')
        # Columns the caller explicitly wants REDONE even though they already
        # hold something. The Enrich button never sends this, so a click can
        # still only fill blanks; it exists so a weak description can be
        # rewritten without clearing the field by hand (Hurley 2026-07-29).
        rewrite = body.get('rewrite') or []
        if rewrite is True:
            rewrite = ['about']
        if isinstance(rewrite, str):
            rewrite = [rewrite]
        rewrite = [c for c in rewrite if c in WRITABLE]
        if not isinstance(ev, dict) or not (ev.get('name') or '').strip():
            return _send(self, 400, {'error': 'event with a name is required'})
        if table not in ('event_state', 'manual_events') or key in (None, ''):
            return _send(self, 400, {'error': 'table (event_state|manual_events) '
                                              'and key are required'})

        patch = enrich_one(ev, rewrite=rewrite)
        # Only keep columns we know exist on the table.
        patch = {k: v for k, v in patch.items() if k in WRITABLE and v}
        if not patch:
            return _send(self, 200, {
                'ok': True, 'patch': {}, 'filled': [],
                'note': 'nothing missing, or no new facts found',
                'engines': {'perplexity': bool(PPLX_API_KEY), 'exa': bool(EXA_API_KEY)},
            })

        write = dict(patch)
        if table == 'manual_events':
            # manual_events has NO updated_by column (it tracks created_by) —
            # writing one makes PostgREST reject the whole patch (PGRST204).
            # Just write the enriched fields.
            st, data = _http_json(
                'PATCH',
                SUPABASE_URL + '/rest/v1/manual_events?id=eq.%s' % urllib.parse.quote(str(key)),
                headers=dict(_svc_headers(), **{'Prefer': 'return=minimal'}),
                body=write, timeout=20)
            ok = st in (200, 204)
        else:
            write['updated_by'] = 'Enrichment'   # event_state has this column
            write['event_num'] = key
            st, data = _http_json(
                'POST',
                SUPABASE_URL + '/rest/v1/event_state?on_conflict=event_num',
                headers=dict(_svc_headers(), **{
                    'Prefer': 'resolution=merge-duplicates,return=minimal'}),
                body=write, timeout=20)
            ok = st in (200, 201, 204)

        if not ok:
            return _send(self, 502, {
                'error': 'write failed', 'status': st,
                'detail': (data.get('message') if isinstance(data, dict) else str(data)[:300]),
                'patch': patch,
            })
        return _send(self, 200, {
            'ok': True,
            'table': table, 'key': key,
            'patch': patch,
            'filled': sorted(patch.keys()),
            'engines': {'perplexity': bool(PPLX_API_KEY), 'exa': bool(EXA_API_KEY)},
        })
