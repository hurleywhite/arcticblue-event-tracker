"""POST /api/enrich — fill missing event fields via Exa + Perplexity.

Sweeps manual_events rows that have gaps (no url / venue / pay_to_play /
speaking_route / pricing / past_speakers / meeting_formats / audience_type /
typical_attendees / deadline) and fills ONLY the empty fields:

  - Perplexity (sonar) researches the facts: venue, attend pricing (incl.
    buyer-vs-vendor tiers), pay-to-play, past/announced speakers with titles
    + companies, built-in meeting mechanisms, buyer/seller audience read,
    official homepage URL, CFP deadline.
  - Exa finds the apply-to-speak link, restricted to the event's OWN domain
    (same precision rule as /api/events — a wrong CFP link is worse than none).

NEVER overwrites a value a human (or the gate) already set. Auth: X-API-Key
must equal EVENTS_INGEST_SECRET (same key the Dust agent uses).

Body: {"limit": 6}  (1..10; rows rotate daily so the same heads aren't
re-queried forever). Returns per-event detail of which fields were filled.

Triggers:
  - nightly via .github/workflows/daily-build.yml (curl)
  - on demand: curl -X POST .../api/enrich -H "X-API-Key: …" -d '{"limit":6}'

NOTE: helper functions are duplicated from api/events.py (the source of
truth) because Vercel bundles each function in isolation — keep them in sync.
"""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os
import random
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import date


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL  = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SERVICE_ROLE  = _env('SUPABASE_SERVICE_ROLE_KEY')
INGEST_SECRET = _env('EVENTS_INGEST_SECRET')

EXA_API_KEY = _env('EXA_API_KEY')
EXA_BASE    = _env('EXA_BASE_URL', 'https://api.exa.ai').rstrip('/')

PPLX_API_KEY = _env('PERPLEXITY_API_KEY')
PPLX_MODEL   = _env('PERPLEXITY_MODEL', 'sonar')
PPLX_BASE    = _env('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai').rstrip('/')

# Columns we try to fill, and the Perplexity-fact key each maps from.
GAP_COLUMNS = ('url', 'venue', 'pay_to_play', 'speaking_route', 'pricing',
               'past_speakers', 'meeting_formats', 'audience_type',
               'typical_attendees', 'attendee_count', 'deadline')


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


# ── Exa apply-link discovery (mirrors api/events.py) ─────────────────
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


# Domains that are never an event's own homepage — listing/social/aggregator
# sites that often outrank the real site in search.
_AGGREGATOR_DOMAINS = {
    'eventbrite.com', 'linkedin.com', 'facebook.com', 'instagram.com',
    'twitter.com', 'x.com', 'youtube.com', 'wikipedia.org', 'medium.com',
    'reddit.com', 'meetup.com', 'lu.ma', '10times.com', 'allevents.in',
    'eventslooped.com', 'conferenceindex.org', 'clocate.com', 'tradefairdates.com',
}


def find_homepage(name, location=None):
    """Exa fallback for the event's official homepage when Perplexity didn't
    return one. Same safety rule as everywhere: only accept a URL whose domain
    matches a distinctive token of the event name — a wrong link is worse
    than none. Returns a URL or None."""
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
    """Apply-to-speak link ON the event's own registrable domain, else None."""
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
    "OMIT every key you are not confident about. Never invent URLs."
)


def perplexity_facts(ev):
    """Research one event. Returns a dict of verified facts (possibly empty)."""
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
    # Strip markdown fences / leading prose; grab the outermost JSON object.
    m = re.search(r'\{.*\}', content, re.S)
    if not m:
        return {}
    try:
        facts = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return facts if isinstance(facts, dict) else {}


def _name_matches_domain(name, url):
    """Guard against a hallucinated homepage: require a distinctive name token
    (3+ chars) to appear in the URL's domain. 'Web Summit' -> websummit.com OK;
    a random aggregator domain fails and the URL is dropped."""
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
    # "Unknown" adds nothing and would block future re-research — omit.
    return None


# Despite "OMIT every key you are not confident about", the model sometimes
# answers "Unknown" / "N/A" / "not verified". Storing those pollutes the UI
# (a meeting_formats of "Unknown" renders a 1:1-meetings chip) and marks the
# field as filled so it's never researched again. Treat them as empty.
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
    """A date if the string names a concrete day (ISO / 'Sep 1, 2026' /
    '1 September 2026'), else None. Used to sanity-check deadlines."""
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
    """False when the deadline resolves to a concrete date AFTER the event
    starts (a CFP deadline can't fall after the event). Unparseable / rolling
    deadlines pass (we can't disprove them)."""
    dl = _parse_concrete_date(deadline)
    if not dl or not start_iso:
        return True
    try:
        return dl <= date.fromisoformat(str(start_iso)[:10])
    except ValueError:
        return True


def merge_missing(row, facts):
    """Build a patch of ONLY the row's empty columns from researched facts.
    Pure function — shared with scripts/enrich_catalog.py and unit-tested."""
    patch = {}

    def empty(col):
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
    return patch


def enrich_one(row):
    """Research one event dict and return the fill-only-missing patch.
    Homepage: Perplexity first, Exa search as fallback (same domain guard).
    Exa apply-link uses the row's url (or the freshly-found one)."""
    facts = perplexity_facts(row)
    patch = merge_missing(row, facts)
    home = row.get('url') or patch.get('url')
    if not home:
        try:
            home = find_homepage(row.get('name'), row.get('location'))
        except Exception:
            home = None
        if home:
            patch['url'] = home
    if not (row.get('speaking_route') or '').strip() and home:
        route = None
        try:
            route = find_speaking_route(row.get('name'), home)
        except Exception:
            route = None
        if route:
            patch['speaking_route'] = 'Apply to speak: ' + route
    return patch


def has_gaps(row):
    # A junk value ("Unknown", "N/A") counts as a gap: it gets wiped and the
    # field becomes researchable again (self-healing for early stored junk).
    return any(_junk(row.get(c)) for c in GAP_COLUMNS)


def junk_wipe(row):
    """Columns currently holding a junk non-answer -> explicit nulls."""
    return {c: None for c in GAP_COLUMNS
            if str(row.get(c) or '').strip() and _junk(row.get(c))}


# ── HTTP plumbing ────────────────────────────────────────────────────
def _send(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


def _authorized(handler):
    provided = (handler.headers.get('X-API-Key', '') or
                handler.headers.get('x-api-key', '') or '').strip()
    if not provided:
        ah = handler.headers.get('Authorization', '')
        if ah.lower().startswith('bearer '):
            provided = ah[7:].strip()
    if not provided or not INGEST_SECRET:
        return False
    return hmac.compare_digest(provided, INGEST_SECRET)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        _send(self, 405, {
            'error': 'method not allowed',
            'hint': 'POST {"limit": 6} with header X-API-Key to enrich '
                    'manual events that have missing fields.',
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
        if not _authorized(self):
            return _send(self, 401, {'error': 'unauthorized'})
        if not (PPLX_API_KEY or EXA_API_KEY):
            return _send(self, 200, {'skipped': 'no PERPLEXITY_API_KEY or '
                                                'EXA_API_KEY configured'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
        except (ValueError, json.JSONDecodeError):
            body = {}
        limit = body.get('limit', 6)
        try:
            limit = max(1, min(10, int(limit)))
        except (TypeError, ValueError):
            limit = 6

        # ── Candidates mode: research caller-supplied events, return patches,
        # write NOTHING. Lets the nightly workflow enrich data/events.json
        # (the catalog) using THIS function's API keys — the repo only needs
        # the ingest secret, not the Perplexity/Exa keys.
        if isinstance(body.get('candidates'), list):
            cands = [c for c in body['candidates'] if isinstance(c, dict)][:6]
            patches = []
            for cand in cands:
                wipe = junk_wipe(cand)
                cand_clean = dict(cand)
                for c in wipe:
                    cand_clean[c] = None
                p = dict(wipe, **enrich_one(cand_clean))
                patches.append({'name': cand.get('name'), 'patch': p})
            return _send(self, 200, {
                'mode': 'candidates', 'patches': patches,
                'engines': {'perplexity': bool(PPLX_API_KEY),
                            'exa': bool(EXA_API_KEY)},
            })

        status, rows = _http_json(
            'GET', SUPABASE_URL + '/rest/v1/manual_events?select=*&order=id.desc',
            headers=_svc_headers(), timeout=20)
        if status != 200 or not isinstance(rows, list):
            return _send(self, 502, {'error': 'could not read manual_events',
                                     'status': status})
        gappy = [r for r in rows if has_gaps(r)]
        # Rotate the queue daily so the same un-enrichable heads don't eat the
        # whole budget every night — but events with NO website link always
        # jump the queue (a link unlocks the apply-link lookup too).
        random.Random(date.today().toordinal()).shuffle(gappy)
        gappy.sort(key=lambda r: 0 if not (r.get('url') or '').strip() else 1)
        picked = gappy[:limit]

        results, errors = [], []
        for row in picked:
            # Self-heal: wipe stored junk ("Unknown"/"N/A") so the field is
            # cleared AND researchable; the fresh research may refill it.
            wipe = junk_wipe(row)
            row_clean = dict(row)
            for c in wipe:
                row_clean[c] = None
            patch = dict(wipe, **enrich_one(row_clean))
            if not patch:
                results.append({'id': row.get('id'), 'name': row.get('name'),
                                'filled': []})
                continue
            st, data = _http_json(
                'PATCH',
                SUPABASE_URL + '/rest/v1/manual_events?id=eq.%s' % row.get('id'),
                headers=dict(_svc_headers(), **{'Prefer': 'return=minimal'}),
                body=patch, timeout=20)
            if st in (200, 204):
                results.append({'id': row.get('id'), 'name': row.get('name'),
                                'filled': sorted(k for k, v in patch.items() if v is not None),
                                'cleared_junk': sorted(k for k, v in patch.items() if v is None)})
            else:
                errors.append({'id': row.get('id'), 'name': row.get('name'),
                               'status': st,
                               'detail': (data.get('message')
                                          if isinstance(data, dict) else
                                          str(data)[:200])})
        return _send(self, 200, {
            'examined': len(picked),
            'with_gaps_total': len(gappy),
            'results': results,
            'errors': errors,
            'engines': {'perplexity': bool(PPLX_API_KEY),
                        'exa': bool(EXA_API_KEY)},
        })
