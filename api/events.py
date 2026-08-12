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
from datetime import date as _dt_date
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
# Optional SECOND key for Carlos's own Dust agent. When this key is used, the
# server stamps created_by = CARLOS_CREATED_BY so his events are reliably
# attributed (and surface in Carlos's Planner section). Falls back to the
# single-key setup when unset.
INGEST_SECRET_CARLOS = _env('EVENTS_INGEST_SECRET_CARLOS')

# Each speaker's Dust search agent can carry its OWN key, so an authenticated
# GET returns only that person's targeting rules instead of the whole roster
# (Hurley 2026-07-31). Carlos already worked this way for POST; this
# generalises it. Any of these left unset simply means that agent doesn't
# exist yet and the team key covers them.
#
# Jim deliberately has no dedicated agent — he is sourced by the team agent,
# and his criteria are still served under ?person=jim so events are ready if
# he wants them.
PERSON_SECRETS = {}
for _p in ('thor', 'verma', 'jerome', 'joe', 'carlos'):
    _k = _env('EVENTS_INGEST_SECRET_' + _p.upper())
    if _k:
        PERSON_SECRETS[_p] = _k
if INGEST_SECRET_CARLOS and 'carlos' not in PERSON_SECRETS:
    PERSON_SECRETS['carlos'] = INGEST_SECRET_CARLOS

NO_AGENT_PEOPLE = {'jim'}   # served on request, but no key of their own


def _person_created_by(person):
    """Attribution address for a person's own search agent. Overridable per
    person via EVENTS_INGEST_<NAME>_CREATED_BY; Carlos keeps his existing
    variable so nothing already deployed changes."""
    if person == 'carlos':
        return CARLOS_CREATED_BY
    return _env('EVENTS_INGEST_' + person.upper() + '_CREATED_BY',
                '%s@arcticblue.ai' % person)

_PERSONAS_CACHE = None


def _personas():
    """Load config/personas.json (the single source of truth the tracker UI and
    the Day-Of briefing already read). Returns {} if it can't be found, so a
    GET degrades to just the deleted-events backlog rather than failing."""
    global _PERSONAS_CACHE
    if _PERSONAS_CACHE is not None:
        return _PERSONAS_CACHE
    here = os.path.dirname(os.path.abspath(__file__))
    # Same resolution api/briefing.py uses (proven in production), plus a couple
    # of fallbacks. vercel.json must also carry
    #   "api/events.py": { "includeFiles": "config/personas.json" }
    # or the file is not bundled and this silently returns {}.
    root = os.path.abspath(os.path.join(here, '..'))
    cands = [os.path.join(root, 'config', 'personas.json'),
             os.path.join(here, 'config', 'personas.json'),
             os.path.join(os.getcwd(), 'config', 'personas.json')]
    for rel in cands:
        try:
            with open(os.path.normpath(rel), 'r') as fh:
                _PERSONAS_CACHE = json.load(fh)
                return _PERSONAS_CACHE
        except Exception:
            continue
    _PERSONAS_CACHE = {}
    return _PERSONAS_CACHE


def _person_payload(key, p):
    """One person's targeting rules, shaped for a search agent: what to look
    for, where, and what to skip. Field names mirror personas.json so the
    tracker and the agent never drift."""
    return {
        'person':            key,
        'name':              p.get('name', key.title()),
        'role':              p.get('role', ''),
        'mode':              p.get('mode', ''),
        'target_industries': p.get('icp_industries', []),
        'buyer_titles':      p.get('buyer_titles', []),
        'themes':            p.get('themes', []),
        'signature_angles':  p.get('signature_angles', []),
        'geo':               p.get('geo', []),
        'geo_note':          'Preferred cities/regions. A strong enough event outside this list is '
                             'still worth surfacing — treat geo as a preference, not a hard filter.',
        'rules':             p.get('flags', []),
        'event_rules':       p.get('event_rules', {}),
        'outcome_target':    p.get('outcome_target', ''),
        'has_dedicated_agent': key not in NO_AGENT_PEOPLE,
    }

DEFAULT_CREATED_BY = _env('EVENTS_INGEST_CREATED_BY', 'dust@arcticblue.ai')
CARLOS_CREATED_BY  = _env('EVENTS_INGEST_CARLOS_CREATED_BY', 'carlos@arcticblue.ai')
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

# ── Perplexity fact enrichment (optional) ────────────────────────────
# For newly-inserted events missing venue / pricing / pay-to-play / speakers /
# meeting formats, one Perplexity research call fills the blanks at insert
# time. Capped per request (the 60s function budget is shared with the gate +
# Exa); whatever this misses, the nightly /api/enrich sweep picks up.
PPLX_API_KEY = _env('PERPLEXITY_API_KEY')
PPLX_MODEL   = _env('PERPLEXITY_MODEL', 'sonar')
PPLX_BASE    = _env('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai').rstrip('/')
try:
    PPLX_INLINE_MAX = int(_env('EVENTS_PPLX_MAX', '3') or '3')
except ValueError:
    PPLX_INLINE_MAX = 3

# ── OpenAI worthiness gate ───────────────────────────────────────────
# Optional. If OPENAI_API_KEY is unset the gate is SKIPPED and every new
# (non-duplicate) event is inserted, exactly as the original endpoint did.
OPENAI_API_KEY = _env('OPENAI_API_KEY')
OPENAI_MODEL   = _env('OPENAI_MODEL', 'gpt-5.4')
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
    "right audience (enterprise leaders and AI/technology decision-makers).\n"
    "ArcticBlue wants stage time in front of BUYERS -- in-house enterprise "
    "leaders, operators, and AI/technology decision-makers who could become "
    "clients -- NOT rooms full of other AI vendors, agencies, consultancies, "
    "and sales reps selling to each other. Buyer-rich audiences are far more "
    "valuable than vendor-heavy, sponsor-driven expos."
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
    "BUYERS-OVER-SELLERS (the most important ranking signal):\n"
    "  - Strongly PREFER events whose audience is buyer-rich -- in-house\n"
    "    enterprise leaders, operators, practitioners, and end-user\n"
    "    decision-makers who buy / adopt AI -- over vendor-heavy, sponsor-driven\n"
    "    expos where most attendees are sales / business-development / vendors\n"
    "    selling to each other.\n"
    "  - A buyer-rich audience should raise the score; a vendor-heavy one should\n"
    "    lower it. A high ticket price and senior job titles usually signal a\n"
    "    buyer-rich room; a free or sponsor-funded expo floor usually signals a\n"
    "    seller-heavy one.\n"
    "  - Senior past/announced speakers (C-suite titles at well-known end-user\n"
    "    companies, not vendor CEOs pitching) are a strong buyer signal.\n"
    "  - Built-in meeting mechanisms -- guaranteed 1:1 meetings, hosted\n"
    "    roundtables, or an attendee app for pre-booking meetings -- raise the\n"
    "    score: they make it easy to actually talk to buyers in the room.\n"
    "\n"
    "REJECT when ANY of these hold:\n"
    "  - Clearly off-topic industry with no AI / tech angle.\n"
    "  - It already happened (a past date).\n"
    "  - Pure pay-to-play sponsorship with NO speaking slot of any kind.\n"
    "  - A pure vendor-to-vendor lead-gen expo with little or no buyer / end-user\n"
    "    audience (everyone in the room is there to sell).\n"
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
    # Buyer-quality + attending signals (require the 2026-06 migration; writes
    # that hit a DB without these columns are stripped + retried, so ingest
    # never breaks).
    'pricing', 'audience_type', 'past_speakers', 'meeting_formats',
    'attend_verdict', 'postmortem',
}
BOOL_COLS = {'seed', 'urgent', 'paid'}

# Canonical pipeline stages — incoming status_tags are normalized to these.
# "Rejected" = rejected to speak (organizer passed); distinct from "Declined"
# (the team passed on the event).
STAGES = ['Identified', 'Submitted', 'Followed up', 'Meeting held', 'Booked',
          'Rejected', 'Attending', 'Declined']
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

    # Numeric shorthand (Angela's spreadsheet habit): "4/28", "4/28-4/30",
    # "11/9 - 11/12/26", "4/28-30". Missing year is forward-looking: current
    # year, rolled to next year when the date passed more than ~6 weeks ago.
    def yr(t):
        if not t:
            return None
        y = int(t)
        return y + 2000 if y < 100 else y

    def infer_year(mo, d):
        today = _dt_date.today()
        try:
            cand = _dt_date(today.year, mo, d)
        except ValueError:
            return today.year
        return today.year + 1 if (today - cand).days > 45 else today.year

    def ok_md(mo, d):
        return 1 <= mo <= 12 and ok_day(d)

    n1 = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*[–—-]\s*'
                   r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', s)
    if n1:
        a1, a2 = int(n1.group(1)), int(n1.group(2))
        b1, b2 = int(n1.group(4)), int(n1.group(5))
        if ok_md(a1, a2) and ok_md(b1, b2):
            ya = yr(n1.group(3)) or yr(n1.group(6)) or infer_year(a1, a2)
            yb = yr(n1.group(6)) or ya
            if yb == ya and b1 < a1:
                yb = ya + 1  # 12/30 - 1/2 wraps the year
            return (_iso(ya, a1, a2), _iso(yb, b1, b2))

    n2 = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*[–—-]\s*(\d{1,2})(?!\d*/)', s)
    if n2:
        c1, c2, c3 = int(n2.group(1)), int(n2.group(2)), int(n2.group(4))
        if ok_md(c1, c2) and ok_day(c3):
            yc = yr(n2.group(3)) or infer_year(c1, c2)
            return (_iso(yc, c1, c2), _iso(yc, c1, c3))

    n3 = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', s)
    if n3:
        e1, e2 = int(n3.group(1)), int(n3.group(2))
        if ok_md(e1, e2):
            ye = yr(n3.group(3)) or infer_year(e1, e2)
            d = _iso(ye, e1, e2)
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


# ── Buyer/seller audience read ───────────────────────────────────────
# ArcticBlue wants stage time in front of BUYERS (in-house enterprise leaders
# who could become clients), not rooms full of other vendors selling to each
# other. The gate returns a free-text audience label which we squeeze into one
# of three canonical buckets so the UI can tag + filter on it consistently.
_AUDIENCE_LABELS = ('Buyer-rich', 'Mixed', 'Vendor-heavy')


def _norm_audience(v):
    """Map free-text / case-insensitive audience input to one canonical label
    ('Buyer-rich' | 'Mixed' | 'Vendor-heavy') or None when unknown/blank."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if not s:
        return None
    # Exact canonical match first (cheap, case-insensitive).
    for lab in _AUDIENCE_LABELS:
        if s == lab.lower():
            return lab
    # Vendor-heavy: anyone there to sell (vendors/sellers/sponsors/exhibitors).
    if any(w in s for w in ('vendor', 'seller', 'sell', 'sales', 'sponsor', 'exhibitor')):
        return 'Vendor-heavy'
    # Buyer-rich: end users / decision-makers / in-house enterprise buyers.
    if any(w in s for w in ('buyer', 'buy', 'end user', 'end-user', 'enduser',
                            'decision', 'in-house', 'in house', 'enterprise lead',
                            'practitioner', 'client')):
        return 'Buyer-rich'
    if 'mixed' in s or 'balanced' in s or 'both' in s:
        return 'Mixed'
    return None


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
    'usa', 'edition',
}
_YEAR_RE = re.compile(r'^(?:19|20)\d{2}$')


def _fingerprint(name):
    """Order-independent dedupe key. May be '' if the name is all stop-words
    (callers must treat an empty fingerprint as 'no fingerprint match')."""
    s = (name or '').lower()
    s = re.sub(r'(\d)([a-z])', r'\1 \2', s)   # split digit/letter so
    s = re.sub(r'([a-z])(\d)', r'\1 \2', s)   # "money20/20" == "money 20 20"
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    toks = [t for t in s.split() if t not in _DEDUPE_STOP and not _YEAR_RE.match(t)]
    return ' '.join(sorted(set(toks)))


def _fps_of(names):
    """Set of non-empty fingerprints for an iterable of names."""
    return {fp for fp in (_fingerprint(n) for n in names) if fp}


def _name_token_set(name):
    """The distinctive tokens of a name as a set (same normalization as
    _fingerprint, but unordered) — for date-scoped duplicate matching."""
    s = (name or '').lower()
    s = re.sub(r'(\d)([a-z])', r'\1 \2', s)
    s = re.sub(r'([a-z])(\d)', r'\1 \2', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return frozenset(t for t in s.split() if t not in _DEDUPE_STOP and not _YEAR_RE.match(t))


def _iso_day(d):
    """'2026-09-28...' -> a date, or None when it isn't a usable ISO day."""
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', (d or '').strip())
    if not m:
        return None
    try:
        return _dt_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _row3(row):
    """Normalize a (name, date) or (name, date, url) tuple to all three."""
    if len(row) >= 3:
        return row[0], row[1], row[2]
    return row[0], row[1], ''


def _row4(row):
    """As _row3, plus location ('' when the row predates it)."""
    n, d, u = _row3(row)
    return n, d, u, (row[3] if len(row) >= 4 else '')


# ── Same event, reworded ──────────────────────────────────────────────
# The strict-subset rule below catches a title that merely GAINED a word. What
# repeatedly got past it is the shape where each side carries a word the other
# lacks — "Learning Futures New York, Executive Knowledge Exchange" against
# "iVentiv Learning Futures New York 2026". Neither is a subset, yet it is one
# event entered twice (Hurley 2026-08-09).
#
# The fix is NOT a similarity ratio. Measured over the whole live tracker, a
# containment threshold loose enough to pair those also pairs "Chicago CIO
# Executive Summit" with "Evanta Seattle CIO Community Executive Summit" — 29
# real events it would have swallowed. A skipped event is invisible: nobody
# ever learns it was dropped. So this stays a SUBSET rule, and only removes
# tokens that provably carry no distinguishing power first:
#   · the organiser's own name, when the domain already says it (iventiv.com,
#     itrevolution.com) — one side prints the brand, the other doesn't
#   · month names and ordinals ("… – November", "8th Annual")
#   · region words, but NEVER city words (see below)
#
# CITY IS THE GUARD RAIL, not noise. Two events on the same organiser's site on
# the same day in DIFFERENT cities are different events — that single check is
# what keeps every Evanta / Red Hat / Gartner city series apart. Only when the
# cities agree (or one side doesn't say) are the shared city words dropped so
# "… Barcelona" and "… Europe" can meet.
_DUP_MONTHS = {
    'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december',
    'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec',
}
_DUP_REGIONS = {
    'uk', 'europe', 'european', 'emea', 'emeia', 'apac', 'americas', 'america',
    'mena', 'latam', 'international', 'global', 'worldwide', 'national', 'annual',
}
_ORDINAL_RE = re.compile(r'^\d+$|^(?:st|nd|rd|th)$')


def _city_tokens(location):
    """Distinctive PLACE words — everything except the trailing country/state.

    'Barcelona, Spain'            -> {'barcelona'}
    '155 Bishopsgate, London, UK' -> {'bishopsgate', 'london'}
    'Charlotte, NC'               -> {'charlotte'}

    Dropping only the LAST segment matters: taking just the first would read the
    venue street as the city, and '155 Bishopsgate' shares no word with 'London',
    so one event would look like it was somewhere else entirely. Keeping the
    middle segments means an address and a bare city still meet on 'london',
    while Charlotte and Raleigh — which share only the state we dropped — still
    read as different places. House numbers go: they are not place names.
    """
    parts = [p for p in (location or '').split(',') if p.strip()]
    if len(parts) > 1:
        parts = parts[:-1]
    text = re.sub(r'[^a-z0-9]+', ' ', ' '.join(parts).lower())
    return {t for t in text.split()
            if t and t not in _DUP_REGIONS and not _ORDINAL_RE.match(t)}


def _brand_tokens(domain):
    """Words the domain itself already tells us, e.g. 'iventiv.com' -> tokens
    that appear inside 'iventiv'. Substring test, not equality, because domains
    run the words together ('itrevolution.com' covers both 'it' and
    'revolution')."""
    stem = (domain or '').split('.')[0]
    return stem if len(stem) >= 3 else ''


def _dedupe_noise(tokens, brand, drop_city):
    """Strip the tokens that cannot distinguish two events by the same organiser
    on the same day."""
    out = set()
    for t in tokens:
        if t in _DUP_MONTHS or t in _DUP_REGIONS or _ORDINAL_RE.match(t):
            continue
        if t in drop_city:
            continue
        if brand and len(t) >= 2 and t in brand:
            continue
        out.add(t)
    return out


def _cities_conflict(a, b):
    """True when both sides name a city and they share no word — the one check
    that keeps a city series (Evanta, Red Hat, Gartner) from collapsing."""
    return bool(a) and bool(b) and not (a & b)


def _same_event_reworded(a, b, domain, city_a, city_b):
    """Same organiser + same date + same (or unstated) city, and once the
    non-distinguishing words are gone one title is a subset of the other."""
    if _cities_conflict(city_a, city_b):
        return False
    brand = _brand_tokens(domain)
    shared_city = city_a & city_b
    ta = _dedupe_noise(a, brand, shared_city)
    tb = _dedupe_noise(b, brand, shared_city)
    if not ta or not tb:
        return False
    return _same_event_on_date(ta, tb)


def _year_index(pairs):
    """{year: [(token_set, date, domain), ...]} for near-date dup matching."""
    idx = {}
    for row in pairs:
        name, d, url = _row3(row)
        day = _iso_day(d)
        if not day:
            continue
        idx.setdefault(day.year, []).append((_name_token_set(name), day, _domain_of(url)))
    return idx


def _domains_conflict(a, b):
    """True when two events are demonstrably run by DIFFERENT outfits.

    The event link is the only handle we have on who is actually offering an
    event, and it settles cases the title alone can't: two events whose names
    look alike but live on different companies' sites are different events, and
    must not be merged (Hurley 2026-07-29). When either side has no link we know
    nothing, so this returns False and the title rules decide on their own.
    """
    if not a or not b:
        return False
    return a != b


# How many days apart two records can be and still be the same event. Small on
# purpose: a real annual event never recurs within a fortnight, so this can only
# ever pair up records inside one edition.
_DUP_DAY_WINDOW = 4


def _same_event_on_date(a, b):
    """True when two token sets look like the SAME event (to be paired with an
    equal start_date). Catches the case the plain fingerprint misses: the same
    event re-added with an extra organizer / edition word — e.g.
      "CDAO New York"                -> {cdao, new, york}
      "CDAO New York 2026 - Corinium"-> {cdao, corinium, new, york}
    one set is a subset of the other, so on the same date they're a duplicate.
    Distinct co-located events ("CDAO Defense" vs "CDAO Government", share only
    {cdao}) are NOT merged — a strict SUBSET with >= 2 shared tokens is
    required, so events that merely share a common prefix ("Big Data LDN" vs
    "Big Data & AI World London") stay separate."""
    if not a or not b:
        return False
    inter = a & b
    if not inter:
        return False
    if inter != a and inter != b:
        return False                      # must be a strict subset either way
    if len(inter) < 2:
        # A single shared token only counts when it's a distinctive BRAND name —
        # "Sibos" / "Dreamforce" reduce to one token, so demanding two shared
        # words meant they could never be matched against "Sibos 2026 Miami" or
        # "Salesforce Dreamforce". Short tokens ("ai", "cdao") stay excluded, so
        # co-located siblings that merely share a prefix are still kept apart.
        return len(next(iter(inter))) >= 4
    return True


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
    # Fold the buyer/seller audience label alias onto audience_type. The agent
    # (and the gate) speak in terms of "audience"; the column is audience_type.
    if not ev.get('audience_type') and ev.get('audience'):
        ev['audience_type'] = ev['audience']
    # Fold speaker-lineup aliases onto past_speakers (the column). NOTE:
    # 'speaker' (singular) is NOT an alias — that's ArcticBlue's own speaker.
    if not ev.get('past_speakers'):
        for alias in ('speakers', 'speaker_lineup', 'upcoming_speakers'):
            if ev.get(alias):
                ev['past_speakers'] = ev[alias]
                break
    # Fold meeting-mechanism aliases onto meeting_formats.
    if not ev.get('meeting_formats'):
        for alias in ('guaranteed_meetings', 'meetups', 'networking_formats'):
            if ev.get(alias):
                ev['meeting_formats'] = ev[alias]
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

# ── Existence verification (web-confirm a real event) ────────────────
# A REQUIRED check on each genuinely-new event: an OpenAI web-search model must
# find a real, event-specific page for THIS exact edition, or the event is
# rejected as a likely hallucination. The text-only worthiness gate can't tell
# a real event from a plausible-sounding fake (e.g. an invented city/edition of
# a real conference series), so this is the actual "does it exist?" check.
# Uses the same OPENAI_API_KEY. Fail-OPEN on an API error so an outage never
# silently drops real opportunities; set EVENTS_VERIFY_FAIL_OPEN=false to
# fail-closed, or EVENTS_VERIFY_EXISTENCE=false to disable the check.
VERIFY_MODEL     = _env('OPENAI_VERIFY_MODEL', 'gpt-5-search-api')
VERIFY_ENABLED   = bool(OPENAI_API_KEY) and _truthy(_env('EVENTS_VERIFY_EXISTENCE', 'true'))
VERIFY_FAIL_OPEN = _truthy(_env('EVENTS_VERIFY_FAIL_OPEN', 'true'))


def _gate_enabled():
    return bool(OPENAI_API_KEY)


def _evaluate_event(row, known_names):
    """Ask OpenAI whether this candidate event is worth tracking.

    Returns {'decision': 'accept'|'reject', 'score': float|None,
             'audience': str|None, 'audience_note': str|None,
             'reason': str, 'error': str|None}. If the gate is disabled
    (no OPENAI_API_KEY) this auto-accepts. On an OpenAI error it honors
    GATE_FAIL_OPEN (keep vs drop)."""
    if not _gate_enabled():
        return {'decision': 'accept', 'score': None, 'audience': None,
                'audience_note': None, 'reason': 'gate disabled', 'error': None}

    def _fallback(why, err):
        return {
            'decision':      'accept' if GATE_FAIL_OPEN else 'reject',
            'score':         None,
            'audience':      None,
            'audience_note': None,
            'reason':        '%s (fail-%s)' % (why, 'open' if GATE_FAIL_OPEN else 'closed'),
            'error':         (err or '')[:300],
        }

    # Only the fields that inform the judgment — keep the prompt compact.
    fields = ('name', 'date_str', 'start_date', 'location', 'region', 'type',
              'about', 'why', 'focus_areas', 'typical_attendees', 'attendee_count',
              'pricing', 'past_speakers', 'meeting_formats', 'speaking_route',
              'pay_to_play', 'url')
    candidate = {k: row[k] for k in fields if row.get(k)}
    sample = sorted(known_names)[:80]  # so the judge can spot near-duplicates

    system = (
        ARCTICBLUE_PROFILE + "\n\n" + WORTHINESS_RUBRIC + "\n\n"
        'Respond with ONLY a JSON object of the form '
        '{"decision":"accept" or "reject",'
        '"score":<0..1 confidence the event is worthy, weighing buyer-richness>,'
        '"audience":"Buyer-rich" or "Mixed" or "Vendor-heavy"'
        ' (your read of who is actually in the room),'
        '"audience_note":"<=120 chars on who attends and why that helps or hurts",'
        '"reason":"<=200 chars"}.'
    )
    user = json.dumps({
        'candidate_event': candidate,
        'events_already_tracked': sample,
    }, ensure_ascii=False)

    # gpt-5 / o-series require max_completion_tokens and reject a temperature
    # override; older models use max_tokens + temperature.
    _is5 = OPENAI_MODEL.lower().startswith(('gpt-5', 'o1', 'o3', 'o4'))
    payload = {
        'model': OPENAI_MODEL,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user',   'content': user},
        ],
        'response_format': {'type': 'json_object'},
    }
    if _is5:
        payload['max_completion_tokens'] = 1200  # reasoning shares this budget
    else:
        payload['temperature'] = 0
        payload['max_tokens'] = 200
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
    audience = _norm_audience(parsed.get('audience'))
    audience_note = str(parsed.get('audience_note', '') or '')[:200] or None
    return {'decision': decision, 'score': score, 'audience': audience,
            'audience_note': audience_note, 'reason': reason, 'error': None}


def _svc_headers():
    return {
        'apikey':        SERVICE_ROLE,
        'Authorization': 'Bearer ' + SERVICE_ROLE,
        'Content-Type':  'application/json',
    }


def _extract_verdict(text):
    """Lenient JSON parse — pull a {...} verdict object out of a model reply."""
    text = text or ''
    try:
        return json.loads(text)
    except (ValueError, json.JSONDecodeError):
        pass
    m = re.search(r'\{.*\}', text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except (ValueError, json.JSONDecodeError):
            pass
    return None


def _verify_exists(row):
    """Web-confirm the event is a real, specific edition via an OpenAI
    web-search model. Returns {'ok': bool, 'url': str, 'reason': str,
    'confidence': float}. Fail-OPEN on API error (per VERIFY_FAIL_OPEN)."""
    name = (row.get('name') or '').strip()
    if not name:
        return {'ok': False, 'url': '', 'reason': 'no name', 'confidence': 0.0}
    loc = (row.get('location') or '').strip()
    dt  = (row.get('date_str') or '').strip()
    prompt = (
        "Use web search to decide whether this is a REAL, scheduled event — a "
        "specific edition that actually exists, not a plausible-sounding guess.\n"
        "Event name: %s\nLocation: %s\nDate: %s\n\n"
        "Find the official page for THIS exact edition (matching the name, city, "
        "and timeframe). A generic company website or an event-series homepage "
        "is NOT sufficient on its own. Reply with ONLY a JSON object:\n"
        '{"exists": true or false, "url": "<official event-specific URL, or empty>", '
        '"confidence": <0 to 1>, "note": "<=120 chars on what you found>"}\n'
        "Set exists=false (and url empty) if you cannot confirm a real, specific "
        "page for this exact event."
    ) % (name, loc or 'unspecified', dt or 'unspecified')
    payload = {
        'model': VERIFY_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'web_search_options': {},
    }
    status, data = _http_json(
        'POST', OPENAI_BASE + '/chat/completions',
        headers={'Authorization': 'Bearer ' + OPENAI_API_KEY,
                 'Content-Type':  'application/json'},
        body=payload, timeout=60)
    if status != 200 or not isinstance(data, dict):
        return {'ok': VERIFY_FAIL_OPEN, 'url': '',
                'reason': 'verify api error %s' % status, 'confidence': 0.0}
    try:
        content = data['choices'][0]['message']['content'] or ''
    except (KeyError, IndexError, TypeError):
        return {'ok': VERIFY_FAIL_OPEN, 'url': '', 'reason': 'verify: no content', 'confidence': 0.0}
    v = _extract_verdict(content)
    if not isinstance(v, dict):
        return {'ok': VERIFY_FAIL_OPEN, 'url': '', 'reason': 'verify: unparseable', 'confidence': 0.0}
    try:
        conf = float(v.get('confidence'))
    except (TypeError, ValueError):
        conf = 0.0
    url = (v.get('url') or '').strip()
    ok = bool(v.get('exists')) and bool(url) and conf >= 0.5
    return {'ok': ok, 'url': url, 'reason': (v.get('note') or '')[:200], 'confidence': conf}


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


# ── Perplexity fact research (insert-time; see also api/enrich.py) ───
_PPLX_SYSTEM = (
    "You research business conferences. Given ONE specific event, return ONLY "
    "a raw JSON object — no prose, no markdown fences — with any of these "
    "keys you can verify for THIS exact event edition: "
    '"venue", "pricing" (cost to ATTEND; if buyers and vendors pay different '
    'rates state both tiers), "pay_to_play" ("Yes"|"No"|"Unknown" — speaking '
    'tied to paid sponsorship?), "past_speakers" (3-8 "Title, Company" pairs, '
    'semicolon-separated), "meeting_formats" (guaranteed/hosted 1:1 meetings, '
    'roundtables, or an attendee app for pre-booking meetings), "audience" '
    '("Buyer-rich"|"Mixed"|"Vendor-heavy"), "typical_attendees" (one short '
    'who-attends line), "attendee_count", "deadline" (CFP deadline). '
    "OMIT every key you are not confident about. Never invent facts."
)
# Insert-time fillable columns <- Perplexity fact key.
_FACT_COLS = (('venue', 'venue'), ('pricing', 'pricing'),
              ('pay_to_play', 'pay_to_play'), ('past_speakers', 'past_speakers'),
              ('meeting_formats', 'meeting_formats'),
              ('audience_type', 'audience'),
              ('typical_attendees', 'typical_attendees'),
              ('attendee_count', 'attendee_count'), ('deadline', 'deadline'))


def _perplexity_facts(row):
    """One research call for a new event. Returns a facts dict (maybe {})."""
    if not PPLX_API_KEY:
        return {}
    known = {k: row[k] for k in ('name', 'date_str', 'location', 'url') if row.get(k)}
    status, data = _http_json(
        'POST', PPLX_BASE + '/chat/completions',
        headers={'Authorization': 'Bearer ' + PPLX_API_KEY},
        body={'model': PPLX_MODEL,
              'messages': [{'role': 'system', 'content': _PPLX_SYSTEM},
                           {'role': 'user', 'content': json.dumps(known, ensure_ascii=False)}],
              'temperature': 0.1, 'max_tokens': 700},
        timeout=25)
    if status != 200 or not isinstance(data, dict):
        return {}
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return {}
    m = re.search(r'\{.*\}', content or '', re.S)
    if not m:
        return {}
    try:
        facts = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return facts if isinstance(facts, dict) else {}


# The model sometimes answers "Unknown"/"N/A" instead of omitting a key.
# Storing those pollutes the UI and blocks future re-research — drop them.
_JUNK_PREFIXES = ('unknown', 'n/a', 'na', 'none', 'not available', 'not verified',
                  'not specified', 'not publicly', 'not announced', 'not found',
                  'not yet', 'not published', 'not listed', 'not disclosed',
                  'no deadline', 'no public', 'no cfp', 'likely passed',
                  'unclear', 'tbd', 'to be', 'varies', 'unavailable')


def _junk_fact(v):
    s = str(v or '').strip().lower()
    return (not s) or any(s.startswith(p) for p in _JUNK_PREFIXES)


def _merge_missing_facts(row, facts):
    """Patch of ONLY the row's empty columns from researched facts — values a
    human (or the gate) already set are never touched."""
    patch = {}
    for col, key in _FACT_COLS:
        if (row.get(col) or '') and str(row.get(col)).strip():
            continue
        v = facts.get(key)
        if not v:
            continue
        if col == 'audience_type':
            v = _norm_audience(v)
            if not v:
                continue
        elif isinstance(v, list):
            v = '; '.join(str(x) for x in v)
        if col != 'audience_type' and _junk_fact(v):
            continue
        if col == 'pay_to_play':
            v = ('Yes' if str(v).strip().lower().startswith('yes')
                 else 'No' if str(v).strip().lower().startswith('no') else None)
            if not v:
                continue
        patch[col] = str(v).strip()[:600]
    return patch


def _row_has_fact_gaps(row):
    return any(not (row.get(col) and str(row.get(col)).strip())
               for col, _k in _FACT_COLS)


def _existing_manual_dated():
    """(name, start_date, url, location) for every manual event — any may be ''."""
    status, rows = _http_json(
        'GET', SUPABASE_URL + '/rest/v1/manual_events?select=name,start_date,url,location',
        headers=_svc_headers(), timeout=15)
    out = []
    if status == 200 and isinstance(rows, list):
        for r in rows:
            n = (r.get('name') or '').strip()
            if n:
                out.append((n, (r.get('start_date') or '').strip(),
                            (r.get('url') or '').strip(), (r.get('location') or '').strip()))
    return out


def _catalog_dated(host):
    """(name, start_date, url) from the public catalog (events.json) served by
    this same deployment. Best-effort — failures just return an empty list."""
    if not host:
        return []
    url = 'https://%s/events.json' % host
    status, data = _http_json('GET', url, timeout=15)
    out = []
    if status == 200 and isinstance(data, dict):
        for e in (data.get('events') or []):
            n = (e.get('name') or '').strip()
            if n:
                out.append((n, (e.get('start_date') or '').strip(),
                            (e.get('url') or '').strip(), (e.get('location') or '').strip()))
    return out


def _date_index(dated):
    """start_date -> [(name token-set, domain, city tokens)], for date-scoped
    dup matching."""
    idx = {}
    for row in dated:
        n, d, u, loc = _row4(row)
        if d:
            idx.setdefault(d, []).append((_name_token_set(n), _domain_of(u), _city_tokens(loc)))
    return idx


def _deleted_backlog():
    """(name, start_date) for every event a human DELETED in the tracker.

    Deleting used to leave nothing behind for a manual event, so the nightly
    scrape would cheerfully re-add it and someone would delete it again. This is
    the "don't bring this back" list (see scripts/2026-07-29_deleted_events.sql).

    Best-effort: if the table hasn't been migrated yet the request 404s and we
    return an empty backlog, so ingest carries on exactly as before.
    """
    status, rows = _http_json(
        'GET', SUPABASE_URL + '/rest/v1/deleted_events?select=name,start_date',
        headers=_svc_headers(), timeout=15)
    out = []
    if status == 200 and isinstance(rows, list):
        for r in rows:
            n = (r.get('name') or '').strip()
            if n:
                out.append((n, (r.get('start_date') or '').strip()))
    return out


def _deleted_index(dated):
    """Index the deleted-events backlog for matching.

    Two buckets, because how hard a deletion should bite depends on whether we
    recorded a date for it:

      undated — all we have is the name, so it blocks by name / fingerprint
                outright, in any year.
      by year — a dated deletion blocks only within THAT year, so next year's
                edition of an annual event is still welcome. Same year
                discipline as the live dedupe above.
    """
    idx = {
        'undated_names': set(),
        'undated_fps':   set(),
        'year_names':    {},
        'year_fps':      {},
        'year_tokens':   _year_index(dated),
        'all_names':     {n.lower() for n, _d in dated},
    }
    for name, d in dated:  # backlog rows are (name, start_date) — no url stored
        day = _iso_day(d)
        if not day:
            idx['undated_names'].add(name.lower())
            fp = _fingerprint(name)
            if fp:
                idx['undated_fps'].add(fp)
            continue
        idx['year_names'].setdefault(day.year, set()).add(name.lower())
        fp = _fingerprint(name)
        if fp:
            idx['year_fps'].setdefault(day.year, set()).add(fp)
    return idx


def _deleted_match(name, fp, start_date, idx):
    """Reason string if this incoming event was previously deleted, else None."""
    if not idx:
        return None
    lname = (name or '').strip().lower()
    if not lname:
        return None
    if lname in idx['undated_names'] or (fp and fp in idx['undated_fps']):
        return 'previously deleted'
    day = _iso_day((start_date or '').strip())
    if not day:
        # No usable date on the incoming event, so there's no year to disagree
        # about — an exact name match anywhere in the backlog is enough.
        return 'previously deleted' if lname in idx['all_names'] else None
    if lname in idx['year_names'].get(day.year, ()) or (fp and fp in idx['year_fps'].get(day.year, ())):
        return 'previously deleted'
    # Same title-shape a few days off, within the same year — the re-add that
    # landed on a different day of a multi-day run.
    tokens = _name_token_set(name)
    for other_tokens, other_day, _other_dom in idx['year_tokens'].get(day.year, ()):
        if abs((other_day - day).days) <= _DUP_DAY_WINDOW and _same_event_on_date(tokens, other_tokens):
            return 'previously deleted (same title, within %d days)' % _DUP_DAY_WINDOW
    return None


# Columns that may not exist yet on older DBs (added by the 2026-06 migration).
# If PostgREST rejects a write for one of these, we strip it and retry so the
# whole row still lands — the feature just stays dark until the migration runs.
_MIGRATION_COLS = ('pricing', 'audience_type', 'past_speakers',
                   'meeting_formats', 'attend_verdict', 'postmortem')


def _unknown_column(data):
    """Return the column name PostgREST is complaining about (one of the
    pending-migration columns) given an error body, else None.

    Handles both shapes:
      PGRST204  "Could not find the 'pricing' column of 'manual_events' ..."
      42703     "column \"pricing\" of relation \"manual_events\" does not exist"
    """
    if not isinstance(data, dict):
        return None
    code = str(data.get('code') or '')
    msg = str(data.get('message') or '') + ' ' + str(data.get('details') or '')
    if code not in ('PGRST204', '42703') and 'column' not in msg.lower():
        return None
    low = msg.lower()
    for col in _MIGRATION_COLS:
        # Match 'pricing' / "pricing" / `pricing` however it's quoted.
        if ("'%s'" % col) in low or ('"%s"' % col) in low or (' %s ' % col) in low:
            return col
    return None


def _insert_one(row):
    """POST a row, stripping any not-yet-migrated column the DB rejects and
    retrying, so ingest never breaks before the migration runs."""
    row = dict(row)
    url = SUPABASE_URL + '/rest/v1/manual_events'
    headers = dict(_svc_headers(), **{'Prefer': 'return=representation'})
    for _ in range(len(_MIGRATION_COLS) + 1):
        status, data = _http_json('POST', url, headers=headers, body=row, timeout=20)
        if status in (200, 201):
            return status, data
        col = _unknown_column(data)
        if col and col in row:
            row.pop(col, None)
            continue  # retry without the offending column
        return status, data
    return status, data


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


def _match_secret(handler):
    """Return which agent's key authenticated: a person key ('thor', 'verma',
    'jerome', 'joe', 'carlos'), 'team', or None. Accepts the main
    EVENTS_INGEST_SECRET (team) or any configured EVENTS_INGEST_SECRET_<NAME>,
    so every Dust agent can carry its own key."""
    provided = (handler.headers.get('X-API-Key', '') or handler.headers.get('x-api-key', '') or '').strip()
    if not provided:
        ah = handler.headers.get('Authorization', '')
        if ah.lower().startswith('bearer '):
            provided = ah[7:].strip()
    if not provided:
        return None
    for _person, _secret in PERSON_SECRETS.items():
        if _secret and hmac.compare_digest(provided, _secret):
            return _person
    if INGEST_SECRET and hmac.compare_digest(provided, INGEST_SECRET):
        return 'team'
    return None


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, {})

    def do_GET(self):
        # An authenticated GET is the search agent's BRIEF: who to look for, and
        # what never to bring back. Each person's Dust agent carries its own key
        # and gets only its own targeting rules; the shared team key gets the
        # whole roster, or one person via ?person=thor (Hurley 2026-07-31).
        who = _match_secret(self)
        if who is None:
            return _send(self, 405, {
                'error': 'method not allowed',
                'hint':  'POST a JSON event (or {"events":[...]}) with header X-API-Key. '
                         'An authenticated GET returns your search brief: targeting rules '
                         'plus the deleted-events backlog.',
            })
        if not SERVICE_ROLE:
            return _send(self, 500, {'error': 'server not configured: SUPABASE_SERVICE_ROLE_KEY missing'})

        try:
            qs = urllib.parse.urlparse(self.path).query
            asked = (urllib.parse.parse_qs(qs).get('person', [''])[0] or '').strip().lower()
        except Exception:
            asked = ''

        people = (_personas() or {}).get('personas', {}) or {}
        # A person's own key pins them to their own brief — ?person= is ignored
        # so one agent's key can never pull another's rules. The team key may
        # ask for anyone, which is how Jim gets sourced without his own agent.
        if who != 'team':
            wanted = [who]
        elif asked:
            wanted = [asked] if asked in people else []
        else:
            wanted = list(people.keys())

        if asked and not wanted:
            return _send(self, 404, {
                'error': 'unknown person',
                'known': sorted(people.keys()),
            })

        backlog = _deleted_backlog()
        out = {
            'authenticated_as': who,
            'people': [_person_payload(k, people[k]) for k in wanted if k in people],
            'deleted_events': [{'name': n, 'start_date': d or None} for n, d in backlog],
            'deleted_count': len(backlog),
            'count': len(backlog),   # kept for callers written against the old shape
            'note':  'deleted_events are events a human deleted in the tracker. Do not submit '
                     'these again. A dated entry blocks re-adds in that year only, so a later '
                     'edition of an annual event is still welcome.',
            'how_to_use': 'Search for events matching each person in `people`: target_industries '
                          'plus buyer_titles plus themes, honouring `event_rules.exclude_when` and '
                          '`rules`. Treat `geo` as a preference, not a hard filter. Then POST what '
                          'you find back to this same endpoint.',
        }
        if who == 'team' and not asked:
            out['no_dedicated_agent'] = sorted(NO_AGENT_PEOPLE)
            out['no_dedicated_agent_note'] = ('These people have no search agent of their own — '
                                              'source them with the team key so events are ready '
                                              'if they want them.')
        _send(self, 200, out)

    def do_POST(self):
        try:
            self._handle()
        except Exception as e:
            # Don't leak a full traceback (file paths / internals) to callers.
            _send(self, 500, {
                'error': 'unhandled exception',
                'type':  type(e).__name__,
                'msg':   str(e)[:300],
            })

    def _handle(self):
        # Config guards first.
        if not INGEST_SECRET:
            return _send(self, 500, {'error': 'server not configured: EVENTS_INGEST_SECRET missing'})
        if not SERVICE_ROLE:
            return _send(self, 500, {'error': 'server not configured: SUPABASE_SERVICE_ROLE_KEY missing'})

        # Auth — which agent's key is this?
        agent = _match_secret(self)
        if agent is None:
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

        # Dedupe sources (fetched once). We keep exact lowercased names,
        # order-independent fingerprints, AND a start_date -> token-sets index
        # (so a re-add of the same event on the same date with an extra
        # organizer/edition word is caught even when its fingerprint differs).
        manual_dated   = _existing_manual_dated()
        catalog_dated  = _catalog_dated(self.headers.get('Host', ''))
        existing_names = {n.lower() for n, _d, _u, _l in manual_dated}
        catalog_names  = {n.lower() for n, _d, _u, _l in catalog_dated}
        existing_fps   = _fps_of(n for n, _d, _u, _l in manual_dated)
        catalog_fps    = _fps_of(n for n, _d, _u, _l in catalog_dated)
        date_index     = _date_index(manual_dated + catalog_dated)
        # Same event re-added a day or two off (organisers shift dates, or the
        # scrape lands on the wrong day of a multi-day run) escaped the
        # exact-date index. This one is keyed by YEAR so a near-date match can be
        # found — and keying on the year is also the guard that keeps the 2026
        # and 2027 editions of an annual event apart.
        year_index     = _year_index(manual_dated + catalog_dated)
        seen_names, seen_fps = set(), set()

        # "Don't bring this back" — events a human already deleted in the tracker.
        deleted_idx = _deleted_index(_deleted_backlog())

        inserted, rejected, skipped, errors = [], [], [], []
        enrich_used = 0  # how many Exa speaking-route lookups we've spent
        pplx_used   = 0  # how many Perplexity fact lookups we've spent

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

            # A person's own agent: stamp their attribution server-side
            # (overriding any payload value) so the events are reliably theirs and
            # surface in their Planner section. This started as a Carlos-only rule
            # and now covers every per-person agent (Hurley 2026-07-31). The team
            # key keeps the default — created_by is never forced for it.
            if agent and agent != 'team':
                row['created_by'] = _person_created_by(agent)
            else:
                row.setdefault('created_by', DEFAULT_CREATED_BY)
            row.setdefault('external_id', 'dust')

            lname = name.lower()
            fp = _fingerprint(name)
            dup_reason = None
            if (lname in seen_names or lname in existing_names or lname in catalog_names
                    or (fp and (fp in seen_fps or fp in existing_fps or fp in catalog_fps))):
                dup_reason = 'duplicate'
            else:
                # The LOOSE title rules below pair events on title shape alone, so
                # they're the ones that can get it wrong. The event link is the
                # tiebreaker: if this event and the one we'd pair it with live on
                # different companies' domains, they're different events run by
                # different outfits and must both be kept (Hurley 2026-07-29).
                # A missing link on either side tells us nothing, so the title
                # rules stand on their own exactly as before.
                dom = _domain_of(row.get('url') or '')
                # Same event, same DATE, re-worded title (extra organizer/edition
                # word the fingerprint keeps) — e.g. "CDAO New York" vs
                # "CDAO New York 2026 - Corinium" both on 2026-06-10.
                sd = (row.get('start_date') or '').strip()
                rcity = _city_tokens(row.get('location') or '')
                if sd and sd in date_index:
                    rt = _name_token_set(name)
                    for ot, od_dom, ocity in date_index[sd]:
                        if _domains_conflict(dom, od_dom):
                            continue
                        if _same_event_on_date(rt, ot):
                            dup_reason = 'duplicate (same title + date)'
                            break
                        # Same organiser, same day, same city, one title a subset
                        # of the other once the organiser's own name / month /
                        # region words are set aside. Requires a KNOWN shared
                        # domain — on an unknown domain the plain subset rule
                        # above stands alone, exactly as before.
                        if (dom and od_dom and dom == od_dom
                                and _same_event_reworded(rt, ot, dom, rcity, ocity)):
                            dup_reason = 'duplicate (same event, reworded title)'
                            break
                # Same title-shape a few days off, WITHIN THE SAME YEAR. The year
                # bound is deliberate: "Chief AI Officer Summit New York" in 2026
                # and in 2027 are different editions and must both be kept, so a
                # cross-year pair can never match here however alike the names.
                if not dup_reason:
                    day = _iso_day(sd)
                    if day:
                        rt = _name_token_set(name)
                        for ot, od, od_dom in year_index.get(day.year, ()):
                            if (abs((od - day).days) <= _DUP_DAY_WINDOW
                                    and _same_event_on_date(rt, ot)
                                    and not _domains_conflict(dom, od_dom)):
                                dup_reason = 'duplicate (same title, within %d days)' % _DUP_DAY_WINDOW
                                break
            if not dup_reason:
                # Someone already threw this event out — don't put it back.
                # (A deleted event is NOT a duplicate: it isn't in the tracker
                # any more, so none of the checks above can see it.)
                dup_reason = _deleted_match(name, fp, row.get('start_date'), deleted_idx)
            if dup_reason:
                skipped.append({'name': name, 'reason': dup_reason})
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
                # Don't re-judge the same name later in this batch.
                #
                # THIS BLOCK BELONGS TO THE REJECT BRANCH. It was dedented one
                # level in 92556a8 (2026-07-29), which made the `continue` run
                # for EVERY event that had a parsable start_date — so the ingest
                # skipped every dated event before it could be inserted and the
                # Dust feed went silently dead the same day. Nothing was added
                # for the next two weeks and nothing reported an error, because
                # a skip is a normal outcome (Hurley 2026-08-09).
                seen_names.add(lname)
                if fp:
                    seen_fps.add(fp)
                _nd = _iso_day((row.get('start_date') or '').strip())
                if _nd:
                    year_index.setdefault(_nd.year, []).append(
                        (_name_token_set(name), _nd, dom))
                continue

            # Buyer/seller read from the gate. Persist the canonical audience
            # label, and fall back to the gate's audience_note as the typical-
            # attendees blurb when the caller didn't supply one.
            if not row.get('audience_type') and verdict.get('audience'):
                row['audience_type'] = verdict['audience']
            if not row.get('typical_attendees') and verdict.get('audience_note'):
                row['typical_attendees'] = verdict['audience_note']

            # REQUIRED existence check — a web-search model must confirm this is
            # a real, specific event (with an event-specific page) before we add
            # it. Rejects hallucinated events that the text-only gate can't catch
            # (plausible details + a generic link). New, gate-accepted events only.
            if VERIFY_ENABLED:
                vr = _verify_exists(row)
                if not vr['ok']:
                    rejected.append({
                        'name':   name,
                        'reason': 'unverified — could not web-confirm a real event page: ' + (vr.get('reason') or 'not found'),
                        'verify': vr,
                    })
                    seen_names.add(lname)
                    if fp:
                        seen_fps.add(fp)
                    continue
                # Backfill the confirmed official URL when the caller had none.
                if vr.get('url') and not row.get('url'):
                    row['url'] = vr['url']

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

            # Perplexity fact enrichment: fill venue / pricing / pay-to-play /
            # speakers / meeting formats the caller didn't supply. Capped per
            # request; the nightly /api/enrich sweep covers whatever's left.
            if PPLX_API_KEY and pplx_used < PPLX_INLINE_MAX and _row_has_fact_gaps(row):
                pplx_used += 1
                try:
                    facts = _perplexity_facts(row)
                    for col, val in _merge_missing_facts(row, facts).items():
                        row[col] = val
                except Exception:
                    pass  # enrichment is best-effort, never blocks the insert

            status, data = _insert_one(row)
            if status in (200, 201) and isinstance(data, list) and data:
                inserted.append({'id': data[0].get('id'), 'name': name,
                                 'speaking_route': row.get('speaking_route'),
                                 'audience_type': row.get('audience_type'),
                                 'pricing': row.get('pricing')})
                seen_names.add(lname)
                existing_names.add(lname)
                if fp:
                    seen_fps.add(fp)
                    existing_fps.add(fp)
                # Index what we just inserted so the REST of this batch is
                # checked against it too — two rewordings of one event arriving
                # in the same payload is exactly how several of the duplicates
                # deleted on 2026-08-08 got in. The shapes must match what the
                # readers unpack: date_index holds (tokens, domain, city) and
                # year_index (tokens, day, domain). They were appending a bare
                # token set and a 2-tuple, which unpacked into nonsense — or
                # raised — on the next same-date event (Hurley 2026-08-09).
                _isd = (row.get('start_date') or '').strip()
                if _isd:
                    date_index.setdefault(_isd, []).append(
                        (_name_token_set(name), dom, rcity))
                    _iday = _iso_day(_isd)
                    if _iday:
                        year_index.setdefault(_iday.year, []).append(
                            (_name_token_set(name), _iday, dom))
            elif status == 409 or (isinstance(data, dict) and str(data.get('code')) == '23505'):
                skipped.append({'name': name, 'reason': 'duplicate (db unique index)'})
            else:
                detail = data if isinstance(data, str) else (
                    data.get('message') if isinstance(data, dict) else None)
                errors.append({'name': name, 'reason': 'insert failed (%s)' % status, 'detail': detail})

        return _send(self, 200, {
            'agent':    agent,
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
            'verify': {'enabled': VERIFY_ENABLED, 'model': VERIFY_MODEL if VERIFY_ENABLED else None},
            'enrich': {'enabled': bool(EXA_API_KEY), 'lookups_used': enrich_used,
                       'perplexity': bool(PPLX_API_KEY), 'facts_lookups_used': pplx_used},
        })
