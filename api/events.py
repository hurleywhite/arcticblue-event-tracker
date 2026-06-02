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
  - the Dust agent's block:           { "new_events": [ {...}, {...} ] }
  - a top-level array:                [ {...}, {...} ]
  Max 50 events per request. Only known manual_events columns are stored;
  any other keys are ignored. `name` is required per event.

WORTHINESS GATE (optional):
  If OPENAI_API_KEY is set, every genuinely-new (non-duplicate) event is
  judged by an OpenAI model BEFORE it is inserted. The judge sees who
  ArcticBlue is (ARCTICBLUE_PROFILE), the worthiness rubric (WORTHINESS_RUBRIC),
  the candidate event, and a sample of events already tracked. It returns
  accept/reject + a reason. Rejected events are NOT inserted; the reason is
  returned in the "rejected" array. If OPENAI_API_KEY is unset the gate is
  skipped and every new event is inserted (original behavior).

RESPONSE 200: {
  "inserted": [ { "id": <int>, "name": "..." }, ... ],
  "rejected": [ { "name": "...", "reason": "...", "score": 0.1 }, ... ],
  "skipped":  [ { "name": "...", "reason": "duplicate" }, ... ],
  "errors":   [ { "name": "...", "reason": "..." }, ... ],
  "counts":   { "inserted": N, "rejected": N, "skipped": N, "errors": N },
  "gate":     { "enabled": true, "model": "gpt-4o-mini" }
}

ENV:
  SUPABASE_URL                 (default project URL)
  SUPABASE_SERVICE_ROLE_KEY    (REQUIRED — server-side insert, bypasses RLS)
  EVENTS_INGEST_SECRET         (REQUIRED — shared secret the caller sends)
  OPENAI_API_KEY               (optional — enables the worthiness gate)
  OPENAI_MODEL                 (optional — default "gpt-4o-mini")
  OPENAI_GATE_FAIL_OPEN        (optional — "true" (default) keeps an event if
                                the judge errors; "false" drops it)
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

# ── Speaking-route enrichment (optional, via Exa) ────────────────────
# For every genuinely-new, gate-accepted event that does NOT already carry a
# speaking_route, we ask Exa to find HOW TO GET ON STAGE: a call-for-speakers /
# "apply to speak" / "submit a speaker" / "suggest a speaker" page. We attach
# that link ONLY — never a plain attend/register/tickets page. Reuses the same
# EXA_API_KEY already configured for /api/vet. If EXA_API_KEY is unset the whole
# step is a no-op (events still insert, just without an auto-found apply link).
EXA_API_KEY = _env('EXA_API_KEY')
EXA_BASE    = _env('EXA_BASE_URL', 'https://api.exa.ai').rstrip('/')
try:
    # Cap Exa lookups per request so a 50-event batch can't blow the function
    # timeout. New events beyond this many still insert, just un-enriched.
    ENRICH_MAX = int(_env('EVENTS_ENRICH_MAX', '12') or '12')
except ValueError:
    ENRICH_MAX = 12

# Incoming aliases folded onto the canonical `speaking_route` column so the
# in-chat agent can name the field naturally.
_ROUTE_ALIASES = ('apply_url', 'cfp_url', 'submit_speaker_url', 'speaker_url')

# ── OpenAI worthiness gate ───────────────────────────────────────────
# Optional. If OPENAI_API_KEY is unset the gate is SKIPPED and every new
# (non-duplicate) event is inserted, exactly as the original endpoint did.
OPENAI_API_KEY = _env('OPENAI_API_KEY')
OPENAI_MODEL   = _env('OPENAI_MODEL', 'gpt-4o-mini')
OPENAI_BASE    = _env('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
# On an OpenAI error/timeout: keep the event (fail-open, default) so a flaky
# API never silently loses a real opportunity, or drop it (fail-closed).
_GATE_FAIL_OPEN_RAW = _env('OPENAI_GATE_FAIL_OPEN', 'true')

# ---- EDIT ME ---------------------------------------------------------
# Who ArcticBlue is + what makes an event worth tracking. This text is the
# judge's ENTIRE world view — tune it freely; no code change needed.
ARCTICBLUE_PROFILE = (
    "ArcticBlue AI (arcticblue.ai) is an AI company. This tracker collects "
    "SPEAKING opportunities -- conferences, summits, panels, and industry "
    "events where ArcticBlue could put a speaker on stage in front of the "
    "right audience (enterprise leaders and AI/technology decision-makers)."
)

WORTHINESS_RUBRIC = (
    "Decide whether a candidate event belongs in ArcticBlue's speaking tracker.\n"
    "\n"
    "ACCEPT when ALL of these hold:\n"
    "  - It is a real conference / summit / panel / industry event (not a spam\n"
    "    webinar blast, a product launch, or an unrelated social meetup).\n"
    "  - There is, or plausibly could be, a SPEAKING slot (talk, panel,\n"
    "    keynote, fireside) -- not sponsorship-only with zero stage time.\n"
    "  - The topic overlaps AI, data, or enterprise technology (or ArcticBlue's\n"
    "    focus areas) and the audience plausibly includes target decision-makers.\n"
    "  - It is upcoming (a future date), or the date is unknown but the event\n"
    "    is clearly real.\n"
    "\n"
    "REJECT when ANY of these hold:\n"
    "  - Clearly off-topic industry with no AI / tech angle.\n"
    "  - It already happened (a past date).\n"
    "  - Pure pay-to-play sponsorship with NO speaking slot of any kind.\n"
    "  - Obvious spam, a duplicate of an event already tracked, or missing both\n"
    "    a usable name and any topic signal.\n"
    "\n"
    "When genuinely on the fence, lean ACCEPT -- a human reviews the tracker, "
    "and missing a real opportunity costs more than a borderline extra row."
)

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


# ── Duplicate detection ──────────────────────────────────────────────
# Two keys guard against duplicates:
#   1) exact lowercased name  -> catches identical re-submits.
#   2) order-independent fingerprint -> catches the SAME event under a reworded
#      title. It drops punctuation, 4-digit years and generic event words, then
#      sorts the remaining distinctive tokens. So
#        "The AI Leadership Summit — The Conference Board"
#        "The Conference Board AI Leadership Summit 2026"
#      both collapse to "ai board conference leadership" and dedupe. City and
#      region words are KEPT, so New York vs London editions stay distinct.
_DEDUPE_STOP = {
    'the', 'a', 'an', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'at', 'by', 'with',
    'summit', 'summits', 'conference', 'conferences', 'expo', 'forum', 'event', 'events',
}
_YEAR_RE = re.compile(r'^(?:19|20)\d{2}$')


def _fingerprint(name):
    """Order-independent dedupe key. May be '' if the name is all stop-words
    (callers must treat an empty fingerprint as 'no fingerprint match')."""
    s = re.sub(r'[^a-z0-9]+', ' ', (name or '').lower())
    toks = [t for t in s.split() if t not in _DEDUPE_STOP and not _YEAR_RE.match(t)]
    return ' '.join(sorted(set(toks)))


def _fps_of(names):
    """Set of non-empty fingerprints for an iterable of names."""
    return {fp for fp in (_fingerprint(n) for n in names) if fp}


def _coerce(ev):
    """Filter an incoming dict to allowed columns + coerce types. Returns a
    row dict (may be empty) or None if the input isn't an object."""
    if not isinstance(ev, dict):
        return None
    ev = dict(ev)  # don't mutate the caller's object
    # Fold apply-link aliases onto the canonical speaking_route column.
    if not ev.get('speaking_route'):
        for alias in _ROUTE_ALIASES:
            if ev.get(alias):
                ev['speaking_route'] = ev[alias]
                break
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


GATE_FAIL_OPEN = _truthy(_GATE_FAIL_OPEN_RAW)


def _gate_enabled():
    return bool(OPENAI_API_KEY)


def _evaluate_event(row, known_names):
    """Ask OpenAI whether this candidate event is worth tracking.

    Returns {'decision': 'accept'|'reject', 'score': float|None,
             'reason': str, 'error': str|None}. If the gate is disabled
    (no OPENAI_API_KEY) this auto-accepts. On an OpenAI error it honors
    GATE_FAIL_OPEN (keep vs drop)."""
    if not _gate_enabled():
        return {'decision': 'accept', 'score': None, 'reason': 'gate disabled', 'error': None}

    def _fallback(why, err):
        return {
            'decision': 'accept' if GATE_FAIL_OPEN else 'reject',
            'score':    None,
            'reason':   '%s (fail-%s)' % (why, 'open' if GATE_FAIL_OPEN else 'closed'),
            'error':    (err or '')[:300],
        }

    # Only the fields that inform the judgment — keep the prompt compact.
    fields = ('name', 'date_str', 'start_date', 'location', 'region', 'type',
              'about', 'why', 'focus_areas', 'typical_attendees',
              'speaking_route', 'pay_to_play', 'url')
    candidate = {k: row[k] for k in fields if row.get(k)}
    sample = sorted(known_names)[:80]  # so the judge can spot near-duplicates

    system = (
        ARCTICBLUE_PROFILE + "\n\n" + WORTHINESS_RUBRIC + "\n\n"
        'Respond with ONLY a JSON object of the form '
        '{"decision":"accept" or "reject","score":<0..1 confidence the event '
        'is worthy>,"reason":"<=200 chars"}.'
    )
    user = json.dumps({
        'candidate_event': candidate,
        'events_already_tracked': sample,
    }, ensure_ascii=False)

    payload = {
        'model': OPENAI_MODEL,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user',   'content': user},
        ],
        'temperature': 0,
        'max_tokens': 200,
        'response_format': {'type': 'json_object'},
    }
    status, data = _http_json(
        'POST', OPENAI_BASE + '/chat/completions',
        headers={
            'Authorization': 'Bearer ' + OPENAI_API_KEY,
            'Content-Type':  'application/json',
        },
        body=payload, timeout=25)

    if status != 200 or not isinstance(data, dict):
        return _fallback('gate error %s' % status,
                         data if isinstance(data, str) else json.dumps(data)[:300])
    try:
        content = data['choices'][0]['message']['content']
        parsed  = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        return _fallback('gate parse error', str(e))

    decision = str(parsed.get('decision', '')).strip().lower()
    if decision not in ('accept', 'reject'):
        decision = 'accept' if GATE_FAIL_OPEN else 'reject'
    try:
        score = round(float(parsed.get('score')), 3)
    except (TypeError, ValueError):
        score = None
    reason = str(parsed.get('reason', '') or '')[:300]
    return {'decision': decision, 'score': score, 'reason': reason, 'error': None}


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


# ── Speaking-route enrichment helpers ────────────────────────────────
# Substrings (matched against URL + page title, lowercased) that mark a page
# as a way to GET ON STAGE. Path/title signals win over the host: e.g.
# reg.theaisummit.com/new-york-submit-speaker is an APPLY page (path has
# "submit-speaker") even though the host starts with "reg".
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
# Pages that are ONLY about attending — never attach these as a speaking route.
_ATTEND_SIGNALS = (
    'register', 'registration', 'ticket', 'tickets', 'buy-', 'pricing',
    'passes', 'book-now', '/attend', 'delegate', 'checkout', 'order',
)


def _looks_like_apply(url, title):
    """True when the page is a way to apply/propose to SPEAK (not just attend)."""
    hay = ('%s %s' % (url or '', title or '')).lower()
    return any(sig in hay for sig in _APPLY_SIGNALS)


def _looks_like_attend_only(url, title):
    hay = ('%s %s' % (url or '', title or '')).lower()
    return any(sig in hay for sig in _ATTEND_SIGNALS) and not _looks_like_apply(url, title)


_TWO_PART_TLDS = ('co.uk', 'com.au', 'co.nz', 'co.jp', 'com.br', 'co.za', 'org.uk')


def _domain_of(url):
    """Registrable-ish domain for an URL, e.g. https://newyork.theaisummit.com/x
    -> 'theaisummit.com'. Used so Exa's includeDomains (which also matches
    subdomains like reg.theaisummit.com) keeps results on the event's site."""
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
    """Best-effort Exa web search. Returns a list of {url, title} (possibly
    empty). Never raises."""
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


def _find_speaking_route(name, home_url):
    """Find a 'how to get on stage' link for this event. Returns a URL string
    or None.

    PRECISION RULE: we only accept an apply/propose-to-speak page that lives on
    the EVENT'S OWN registrable domain. We deliberately do NOT search the open
    web, because a keyword search ('<event> call for speakers') readily returns
    a DIFFERENT same-themed event's CFP (e.g. Microsoft Ignite -> a community
    'Copilot Summit' CFP), and attaching the wrong event's link is worse than
    attaching none. If we have no event domain, or the site has no on-site
    apply page, we return None and leave speaking_route blank ('when confident'
    only). NEVER returns a plain attend/register page."""
    if not (EXA_API_KEY and name):
        return None
    dom = _domain_of(home_url)
    if not dom:
        return None  # no event domain -> can't verify ownership; never guess
    query = ('%s call for speakers OR apply to speak OR submit a speaker '
             'OR speaker application' % name)
    for r in _exa_search(query, include_domains=[dom], num=8):
        # Belt-and-suspenders: require the result to actually be ON the event's
        # registrable domain (so reg./submit. subdomains pass, off-site does not).
        if _looks_like_apply(r['url'], r['title']) and _domain_of(r['url']) == dom:
            return r['url']
    return None


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
        elif isinstance(body, dict) and isinstance(body.get('new_events'), list):
            # Matches the Dust agent's final JSON block: {"new_events":[...]}.
            items = body['new_events']
        elif isinstance(body, dict):
            items = [body]
        else:
            items = []

        if not items:
            return _send(self, 400, {'error': 'no events found in body'})
        if len(items) > MAX_EVENTS:
            return _send(self, 413, {'error': 'too many events (max %d per request)' % MAX_EVENTS})

        # Dedupe sources (fetched once). We keep BOTH exact lowercased names and
        # order-independent fingerprints for each source.
        existing_names = _existing_manual_names()
        catalog_names  = _catalog_names(self.headers.get('Host', ''))
        existing_fps   = _fps_of(existing_names)
        catalog_fps    = _fps_of(catalog_names)
        seen_names, seen_fps = set(), set()

        inserted, rejected, skipped, errors = [], [], [], []
        enrich_used = 0  # how many Exa speaking-route lookups we've spent

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
            fp = _fingerprint(name)
            is_dup = (
                lname in seen_names or lname in existing_names or lname in catalog_names
                or (fp and (fp in seen_fps or fp in existing_fps or fp in catalog_fps))
            )
            if is_dup:
                skipped.append({'name': name, 'reason': 'duplicate'})
                continue

            # Worthiness gate (OpenAI). Runs ONLY on genuinely-new events, so
            # a token is never spent judging a duplicate. No-ops if disabled.
            verdict = _evaluate_event(row, existing_names | catalog_names)
            if verdict['decision'] == 'reject':
                rejected.append({
                    'name':   name,
                    'reason': verdict['reason'] or 'not worthy',
                    'score':  verdict['score'],
                })
                seen_names.add(lname)  # don't re-judge same name in this batch
                if fp:
                    seen_fps.add(fp)
                continue

            # Speaking-route enrichment: only when the caller didn't already
            # supply one, only for accepted events, and capped per request so a
            # big batch can't time out. Best-effort — never blocks the insert.
            if not row.get('speaking_route') and enrich_used < ENRICH_MAX and EXA_API_KEY:
                enrich_used += 1
                try:
                    route = _find_speaking_route(name, row.get('url'))
                except Exception:
                    route = None
                if route:
                    row['speaking_route'] = 'Apply to speak: ' + route

            status, data = _insert_one(row)
            if status in (200, 201) and isinstance(data, list) and data:
                inserted.append({'id': data[0].get('id'), 'name': name,
                                 'speaking_route': row.get('speaking_route')})
                seen_names.add(lname)
                existing_names.add(lname)
                if fp:
                    seen_fps.add(fp)
                    existing_fps.add(fp)
            elif status == 409 or (isinstance(data, dict) and str(data.get('code')) == '23505'):
                skipped.append({'name': name, 'reason': 'duplicate (db unique index)'})
            else:
                detail = data if isinstance(data, str) else (
                    data.get('message') if isinstance(data, dict) else None)
                errors.append({'name': name, 'reason': 'insert failed (%s)' % status, 'detail': detail})

        return _send(self, 200, {
            'inserted': inserted,
            'rejected': rejected,
            'skipped':  skipped,
            'errors':   errors,
            'counts': {
                'inserted': len(inserted),
                'rejected': len(rejected),
                'skipped':  len(skipped),
                'errors':   len(errors),
            },
            'gate': {'enabled': _gate_enabled(), 'model': OPENAI_MODEL if _gate_enabled() else None},
            'enrich': {'enabled': bool(EXA_API_KEY), 'lookups_used': enrich_used},
        })
