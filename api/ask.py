"""POST /api/ask — chat with an AI assistant about the tracked events.

The assistant answers questions like "which events should I attend in
September?" or "what's booked for Thor in Q3?" using ONLY the tracker's own
event data (the public catalog + manual events + each event's ops state).
Powered by OpenAI (same OPENAI_API_KEY as the worthiness gate).

Body:  {"question": "...", "history": [{"role":"user|assistant","content":"..."}]}
Reply: {"answer": "...", "model": "gpt-4o-mini"}

Auth: open app (no login). Same-origin guard curbs cross-site abuse of this
metered endpoint. Reads are anon (RLS allows select).
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
SUPABASE_PUBLISHABLE = _env('SUPABASE_PUBLISHABLE_KEY')

OPENAI_API_KEY = _env('OPENAI_API_KEY')
OPENAI_MODEL = _env('OPENAI_CHAT_MODEL', _env('OPENAI_MODEL', 'gpt-5.4'))
# If the primary model id is rejected (not available on the account), retry once
# with this known-good model so Ask AI never hard-fails.
OPENAI_FALLBACK = _env('OPENAI_FALLBACK_MODEL', 'gpt-4o-mini')


def _tok(model, n):
    """gpt-5 / o-series require max_completion_tokens; older models use max_tokens."""
    m = (model or '').lower()
    key = 'max_completion_tokens' if m.startswith(('gpt-5', 'o1', 'o3', 'o4')) else 'max_tokens'
    return {key: n}
OPENAI_BASE = _env('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')

MAX_EVENTS_CONTEXT = 300
# Past events are noise for "what's upcoming / what fits me / should I attend"
# questions (and cost tokens), but keep a recent slice so "what happened at X?"
# still works. Upcoming events are never truncated (they sort first).
PAST_EVENTS_CONTEXT = 50


def _http_json(method, url, headers=None, body=None, timeout=30):
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


def _truncate(v, n):
    s = str(v or '').strip()
    return s[:n] if s else ''


# ── Team coverage profiles — ported from AB_PROFILES in src/build.py. KEEP IN
# SYNC with that list (and the prose _TEAM_CONTEXT below). 'regions' are the
# canonical grid regions; 'kw' are lowercase, punctuation-free whole-word tokens
# matched against a folded text blob. Used to pre-compute, server-side, which
# teammate each event fits, so the model gets a hard signal instead of guessing
# (e.g. it must never hand Jerome — Europe-only — a Brazil event).
AB_PROFILES = [
    {'key': 'Jerome', 'label': 'Europe (European events only)', 'regions': ['Europe'], 'locked': True,
     'kw': ['london', 'dublin', 'amsterdam', 'brussels', 'zurich', 'geneva', 'luxembourg', 'berlin', 'munich', 'frankfurt', 'vienna', 'stockholm', 'copenhagen', 'oslo', 'helsinki', 'madrid', 'barcelona', 'milan', 'lisbon', 'europe', 'emea', 'european', 'uk', 'united kingdom', 'gdpr', 'web summit', 'vivatech', 'viva technology', 'dld', 'tnw', 'ai summit london']},
    {'key': 'Joe', 'label': 'HR / human enablement (L&D, people, future of work)', 'regions': [],
     'kw': ['hr', 'human resources', 'chro', 'clo', 'chief people', 'people officer', 'talent', 'workforce', 'future of work', 'upskilling', 'reskilling', 'design thinking', 'curiosity', 'critical thinking', 'change management', 'shadow ai', 'question to learn', 'employee experience', 'human enablement', 'human capital', 'people analytics', 'organizational development', 'uxpa']},
    {'key': 'Thor', 'label': 'Flagship / C-suite stages (global catch-all)', 'regions': [],
     'kw': ['ceo', 'chief executive', 'cio', 'cto', 'chief information', 'chief technology', 'chief ai officer', 'caio', 'cdo', 'chief data', 'coo', 'chief operating', 'cpo', 'chief product', 'chief digital', 'board', 'government compliance', 'davos', 'world economic forum', 'ai strategy', 'ai literacy']},
    {'key': 'Verma', 'label': 'Regulated industries — insurance, healthcare, finance (esp. APAC & Europe)', 'regions': ['Asia-Pacific', 'Europe'],
     'kw': ['insurance', 'insurtech', 'healthcare', 'health tech', 'pharma', 'life sciences', 'medical', 'finance', 'financial services', 'bank', 'banking', 'capital markets', 'payments', 'wealth', 'fintech', 'regulated', 'compliance']},
    {'key': 'Carlos', 'label': 'Latin America (all of it)', 'regions': ['Latin America'], 'locked': True,
     'kw': ['latin america', 'latam', 'south america', 'brazil', 'brasil', 'sao paulo', 'mexico', 'cdmx', 'argentina', 'buenos aires', 'chile', 'santiago', 'colombia', 'bogota', 'peru', 'lima', 'medellin', 'monterrey']},
]
PROFILE_BY_KEY = {p['key']: p for p in AB_PROFILES}


def _fold(s):
    return re.sub(r' +', ' ', re.sub(r'[^a-z0-9 ]', ' ', str(s or '').lower())).strip()


# Best-effort map of an event's geography to one of the 7 canonical grid regions
# (mirrors canonicalRegion() in build.py closely enough for coverage matching).
# Order matters: Latin America is tested before US & Canada so "Americas + Sao
# Paulo" resolves to Latin America rather than the bare word "america".
_REGION_RULES = [
    ('Latin America', ['latin america', 'latam', 'south america', 'brazil', 'brasil', 'sao paulo', 'mexico', 'cdmx', 'argentina', 'buenos aires', 'chile', 'santiago', 'colombia', 'bogota', 'peru', 'lima', 'medellin', 'monterrey']),
    ('Europe', ['united kingdom', 'uk', 'england', 'britain', 'london', 'ireland', 'dublin', 'france', 'paris', 'germany', 'berlin', 'munich', 'frankfurt', 'spain', 'madrid', 'barcelona', 'italy', 'milan', 'rome', 'netherlands', 'amsterdam', 'belgium', 'brussels', 'switzerland', 'zurich', 'geneva', 'sweden', 'stockholm', 'denmark', 'copenhagen', 'norway', 'oslo', 'finland', 'helsinki', 'portugal', 'lisbon', 'austria', 'vienna', 'luxembourg', 'poland', 'warsaw', 'europe', 'european']),
    ('Asia-Pacific', ['singapore', 'japan', 'tokyo', 'china', 'beijing', 'shanghai', 'hong kong', 'india', 'mumbai', 'bangalore', 'bengaluru', 'new delhi', 'delhi', 'australia', 'sydney', 'melbourne', 'korea', 'seoul', 'indonesia', 'jakarta', 'malaysia', 'kuala lumpur', 'thailand', 'bangkok', 'vietnam', 'philippines', 'manila', 'asia', 'apac', 'asia pacific']),
    ('MENA', ['dubai', 'abu dhabi', 'uae', 'saudi', 'riyadh', 'qatar', 'doha', 'bahrain', 'kuwait', 'israel', 'tel aviv', 'middle east', 'mena', 'turkey', 'istanbul']),
    ('Africa', ['nigeria', 'lagos', 'kenya', 'nairobi', 'south africa', 'johannesburg', 'cape town', 'egypt', 'cairo', 'ghana', 'accra', 'rwanda', 'kigali', 'africa']),
    ('US & Canada', ['usa', 'united states', 'america', 'new york', 'san francisco', 'chicago', 'boston', 'austin', 'seattle', 'las vegas', 'los angeles', 'washington', 'atlanta', 'dallas', 'miami', 'denver', 'canada', 'toronto', 'vancouver', 'montreal', 'ottawa']),
]


def _canon_region(*parts):
    b = ' ' + _fold(' '.join(str(p or '') for p in parts)) + ' '
    for region, toks in _REGION_RULES:
        for t in toks:
            if (' ' + t + ' ') in b:
                return region
    return 'Global'


def _fits(blob_folded, region_canon):
    """Which ArcticBlue people an event suits. Region-locked people (Jerome =
    Europe, Carlos = Latin America) fit ONLY events in their canonical region —
    loose keywords like 'web summit' or a city named in a description must not
    pull an out-of-region event to them. Theme-based people (Joe/Verma/Thor) fit
    by region OR keyword, since their coverage is global/topical."""
    b = ' ' + blob_folded + ' '
    out = []
    for p in AB_PROFILES:
        region_ok = bool(region_canon and region_canon in p['regions'])
        if p.get('locked'):
            hit = region_ok
        else:
            hit = region_ok
            if not hit:
                for kw in p['kw']:
                    if (' ' + kw + ' ') in b:
                        hit = True
                        break
        if hit:
            out.append(p['key'])
    return out


_MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
           'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}


def _endish_iso(start_date, end_date, date_str):
    """Best ISO date for "is this still upcoming?" — prefer the END of the event.
    Catalog rows carry ISO start/end; manual rows often only have a date_str like
    'June 15-18, 2026', so parse year + month + last day number from it."""
    for v in (end_date, start_date):
        if v and re.match(r'^\d{4}-\d{2}-\d{2}', str(v)):
            return str(v)[:10]
    s = str(date_str or '')
    ym = re.search(r'(19|20)\d{2}', s)
    year = ym.group(0) if ym else None
    mo = None
    low = s.lower()
    for name, n in _MONTHS.items():
        if name in low:
            mo = n
            break
    days = re.findall(r'\b(\d{1,2})\b', s)  # 4-digit year won't match \d{1,2}
    day = int(days[-1]) if days else 28
    if year and mo:
        return '%s-%02d-%02d' % (year, mo, min(day, 31))
    if year:
        return '%s-12-31' % year
    return None


# A speaking application is IN once the event carries any of these stages.
# 'Identified' (or no stage at all) means the event is only LOGGED — not yet
# applied to — which is the distinction the team keeps tripping over.
_APPLIED_STAGES = ('Submitted', 'Followed up', 'Meeting held', 'Booked')


def _is_submitted(stages):
    return any(s in (stages or []) for s in _APPLIED_STAGES)


def _gather_events(host):
    """Compact, model-friendly list of every event: catalog (events.json) +
    manual (manual_events) merged with ops state (event_state). Each event is
    annotated with a canonical region, an 'upcoming' flag (vs today), and a
    'fits' list (which teammates it suits) so the model can answer "what's
    upcoming / what fits me / should I attend" reliably. Upcoming events sort
    first and are never truncated; only old past events get trimmed."""
    today = date.today().isoformat()
    out = []
    # Ops state for catalog events, indexed by event_num.
    by_num = {}
    st, rows = _http_json(
        'GET', SUPABASE_URL + '/rest/v1/event_state?select=event_num,status_tags,'
        'status,speaker,attend_verdict,saved,hidden',
        headers={'apikey': SUPABASE_PUBLISHABLE,
                 'Authorization': 'Bearer ' + SUPABASE_PUBLISHABLE}, timeout=12)
    if st == 200 and isinstance(rows, list):
        for r in rows:
            by_num[r.get('event_num')] = r
    # Catalog (events.json) merged with its ops state.
    if host:
        st, data = _http_json('GET', 'https://%s/events.json' % host, timeout=12)
        if st == 200 and isinstance(data, dict):
            for e in (data.get('events') or []):
                ops = by_num.get(e.get('num')) or {}
                stages = ops.get('status_tags') or []
                if ops.get('hidden') or ops.get('status') == '__deleted__':
                    continue  # hidden / soft-deleted events are noise for recs
                region = _canon_region(e.get('region'), e.get('country'),
                                       e.get('city'), e.get('location'), e.get('name'))
                blob = _fold(' '.join(str(x or '') for x in (
                    e.get('name'), e.get('location'), e.get('region'), e.get('country'),
                    e.get('city'), e.get('type'), e.get('audience_type'),
                    e.get('focus_areas'), e.get('typical_attendees'), e.get('why'))))
                endish = _endish_iso(e.get('start_date'), e.get('end_date'), e.get('date_str'))
                out.append({
                    'num': e.get('num'),
                    'name': e.get('name'), 'date': e.get('date_str'),
                    'location': e.get('location'), 'region': region,
                    'type': e.get('type'),
                    # A per-event priority override (set in the Details editor)
                    # wins over the catalog's base priority — same as the cards.
                    'priority': ops.get('priority_override') or e.get('priority'),
                    'audience': e.get('audience_type'), 'price': e.get('pricing'),
                    'deadline': e.get('deadline'),
                    'stage': ', '.join(stages) if stages else None,
                    # True only once a speaking application is actually IN.
                    # 'Identified' / no stage => submitted=False (a candidate).
                    'submitted': _is_submitted(stages),
                    # booked = CONFIRMED to speak; submitted-but-not-booked is NOT booked.
                    'booked': 'Booked' in stages,
                    'attending': 'Attending' in stages,
                    'speaker': ops.get('speaker'),
                    'attend': ops.get('attend_verdict'),
                    'saved': bool(ops.get('saved')),
                    'fits': _fits(blob, region),
                    'upcoming': (endish is None) or (endish >= today),
                    'why': _truncate(e.get('why'), 200),
                    'url': e.get('url'),
                    '_sort': endish or '9999-99-99',
                })
    # Manual events
    st, rows = _http_json(
        'GET', SUPABASE_URL + '/rest/v1/manual_events?select=name,date_str,location,'
        'region,type,priority,status_tags,speaker,attend_verdict,audience_type,'
        'pricing,deadline,why,url',
        headers={'apikey': SUPABASE_PUBLISHABLE,
                 'Authorization': 'Bearer ' + SUPABASE_PUBLISHABLE}, timeout=12)
    if st == 200 and isinstance(rows, list):
        for m in rows:
            stages = m.get('status_tags') or []
            region = _canon_region(m.get('region'), m.get('location'), m.get('name'))
            blob = _fold(' '.join(str(x or '') for x in (
                m.get('name'), m.get('location'), m.get('region'),
                m.get('type'), m.get('audience_type'), m.get('why'))))
            endish = _endish_iso(None, None, m.get('date_str'))
            out.append({
                'name': m.get('name'), 'date': m.get('date_str'),
                'location': m.get('location'), 'region': region,
                'type': m.get('type'), 'priority': m.get('priority'),
                'audience': m.get('audience_type'), 'price': m.get('pricing'),
                'deadline': m.get('deadline'),
                'stage': ', '.join(stages) if stages else None,
                'submitted': _is_submitted(stages),
                'booked': 'Booked' in stages,
                'attending': 'Attending' in stages,
                'speaker': m.get('speaker'), 'attend': m.get('attend_verdict'),
                'fits': _fits(blob, region),
                'upcoming': (endish is None) or (endish >= today),
                'why': _truncate(m.get('why'), 200), 'url': m.get('url'),
                '_sort': endish or '9999-99-99',
            })
    # Drop empty-name rows; upcoming first (soonest first, never truncated),
    # then a recent slice of past events; cap total size.
    out = [e for e in out if (e.get('name') or '').strip()]
    upcoming = sorted([e for e in out if e['upcoming']], key=lambda e: e['_sort'])
    past = [e for e in out if not e['upcoming']]
    past.sort(key=lambda e: e['_sort'], reverse=True)   # most-recent past first
    # A past event that carries a pipeline stage (booked / attending / submitted)
    # is a REAL engagement worth recalling ("what's booked for <person>"). Reserve
    # room for these so they survive the overall cap — otherwise, with hundreds of
    # upcoming events, the [:MAX] slice fills entirely with upcoming and NO past
    # event reaches the model (why "what's booked" returned "none").
    past_tracked  = [e for e in past if e.get('stage')]
    past_untracked = [e for e in past if not e.get('stage')][:PAST_EVENTS_CONTEXT]
    room = max(0, MAX_EVENTS_CONTEXT - len(past_tracked))
    merged = (upcoming[:room] + past_tracked + past_untracked)[:MAX_EVENTS_CONTEXT]
    for e in merged:
        e.pop('_sort', None)
    return merged


_SYSTEM = (
    "You are the ArcticBlue Event Tracker assistant. ArcticBlue is an applied-AI "
    "company that wants speaking slots and attendance at events full of BUYERS "
    "(in-house enterprise decision-makers), not vendor-to-vendor sales expos.\n"
    "Today's date is {today}.\n"
    "FIRST decide what the user actually wants, then answer in that MODE. Return "
    "ONLY a JSON object: {{\"mode\": \"events|event|app|chat\", \"answer\": "
    "\"<markdown>\", \"recommended\": [\"<exact event name>\", ...]}}.\n"
    "MODES:\n"
    "- \"events\" — they want a LIST or RANKING of events (find / what should I "
    "attend / which events / recommend / what haven't we applied to / what's "
    "booked / best buyer-rich, and the like). Put the matching events in "
    "'recommended', HIGHEST-PRIORITY + MOST RELEVANT FIRST (see RANKING below; "
    "max 8), EXACT names from the data, empty if none fit. Keep 'answer' to 1-2 "
    "sentences of reasoning — the events render "
    "as cards, so don't repeat their dates/locations.\n"
    "- \"event\" — they ask ABOUT ONE specific event (tell me about X / is X worth "
    "it / who's speaking at X / when's the CFP for X). Reply conversationally in "
    "2-5 sentences from that event's data (dates, location, audience, fit, stage, "
    "who's interested, price, deadline) plus what you reliably know about it; be "
    "honest when a detail isn't on file. Put just that one event in 'recommended' "
    "so its card shows. If it isn't in the data, say so — never invent it.\n"
    "- \"app\" — they ask HOW TO USE the tracker or what a label/feature means (how "
    "do I add an event / what does Pending mean / how do I mark attending / where's "
    "the apply link / how does this work). Answer briefly and warmly (2-4 "
    "sentences, like a helpful colleague, never a robotic manual) using the APP "
    "GUIDE. Leave 'recommended' EMPTY — no cards.\n"
    "- \"chat\" — anything else: answer helpfully and briefly; 'recommended' empty "
    "unless a specific event is genuinely relevant.\n"
    "Never invent events or facts. If torn between 'events' and 'app', pick "
    "'events' when they want to SEE events and 'app' when they want to know HOW. "
    "The data rules below apply in 'events' and 'event' modes.\n"
    "- PIPELINE STAGES: each event has 'stage' (its pipeline tags) and 'submitted' "
    "(true/false). 'submitted' is the ONLY thing that says whether a speaking "
    "application has been sent. Stage meanings: 'Identified' = we have merely "
    "LOGGED this event as a candidate and have NOT applied — submitted=false; "
    "'Submitted'/'Followed up'/'Meeting held'/'Booked' = an application is in or "
    "progressing — submitted=true; 'Attending' = going without speaking. CRITICAL: "
    "'Identified' and an empty/missing stage BOTH mean NOT SUBMITTED. For any "
    "question about events \"not submitted to yet\", \"haven't applied to\", "
    "\"still open to apply\", or \"what should we apply to\", return events where "
    "submitted=false — and NEVER exclude 'Identified' events; they are exactly the "
    "not-yet-submitted candidates.\n"
    "- BOOKED vs SUBMITTED — do not conflate them. 'booked'=true means CONFIRMED "
    "to speak (the Booked stage). An event that is only Submitted / Followed up / "
    "Meeting held has an application IN but is NOT booked (booked=false). For "
    "\"what's booked\", \"confirmed\", \"where are we speaking\", or \"booked for "
    "<person>\", return ONLY booked=true events — never a merely-submitted one, "
    "even if that person is its speaker. 'attending'=true (the Attending stage) = "
    "going without speaking; keep it separate from booked/speaking too. Match a "
    "named person via the event's 'speaker' field. IMPORTANT: booked/attending are "
    "real engagements regardless of date — for \"what's booked / where has <person> "
    "spoken\", INCLUDE past booked events (upcoming=false) too and note which have "
    "passed; do NOT answer \"none booked\" when booked=true events exist in the "
    "data, even if all of them are in the past.\n"
    "- Each event carries 'upcoming' (true/false), 'region' (canonical), and "
    "'fits' (the ArcticBlue people it suits). For 'upcoming' / 'next' / "
    "'this month' questions, return ONLY upcoming=true events, soonest first. "
    "Treat 'fits' as the authority on who an event is for — never recommend an "
    "event for a person unless their name appears in that event's 'fits'.\n"
    "- RANKING (applies to every 'recommended' list): each event carries a "
    "'priority' (High / Medium / Low; missing or blank = lowest). ALWAYS order the "
    "results by PRIORITY FIRST — High before Medium before Low before none — and, "
    "within the same priority, by fit to the question, then buyer-rich audience, "
    "who's flagged Interested, pipeline stage, and soonest upcoming date. The most "
    "relevant, highest-priority event MUST come first, and reflect that order in "
    "'answer'. Ignore past events unless asked. Never invent events not in the "
    "data.\n"
    "- If the question names a teammate or asks who should go, use the TEAM "
    "COVERAGE notes to match the right person to each event by region/theme, "
    "and prefer events that fit that person's coverage."
)

# Who covers what — used to answer "which event should <person> attend?" or
# "where should I send someone in September?" by matching people to events by
# region/theme. Distilled from the ArcticBlue Obsidian notes (team-roles);
# edit here as the team or their focus areas change.
_TEAM_CONTEXT = (
    "TEAM COVERAGE — match the right ArcticBlue person to an event by geography, "
    "buyer audience, industry, and theme:\n"
    "- Jerome — Head of Sales, EUROPE. Owns European events only: UK/London, "
    "Dublin, Amsterdam, Brussels, Zurich, Geneva, Luxembourg, Berlin, Munich, "
    "Frankfurt, Vienna, Stockholm, Copenhagen, Oslo, Helsinki, Madrid, "
    "Barcelona, Milan, Lisbon. Buyers: CPO/CMO/CDO/CTO/CIO/COO/Chief Strategy or "
    "Innovation/CRO/Chief Customer/VP of AI at 500+ employee firms. Industries: "
    "financial services & insurance, healthcare, fintech, enterprise SaaS, "
    "retail/eCommerce, telco, media. Themes: GTM innovation, scaling AI past "
    "proof-of-concept, GDPR-safe AI, AI governance. Marquee: Web Summit, "
    "VivaTech, DLD Munich, AI Summit London, TNW, GITEX.\n"
    "- Joe — HR / human-enablement speaker & author of 'Question to Learn' "
    "(Co-Founder, ArcticMind). His angle is the HUMAN side of AI adoption: "
    "enablement, practice-based fluency, critical thinking, curiosity, and a "
    "'problem-first' (not 'AI-first') mindset. Signature talks cover L&D in the "
    "era of AI, preventing skill atrophy, the HR playbook for Shadow AI, and "
    "curiosity as the ultimate AI input. Best-fit events: HR/CHRO, L&D and "
    "learning, talent/workforce, future of work, design thinking, change "
    "management, and people-side AI-adoption topics. Audience: CHRO, CLO, "
    "people & L&D leaders. US/general; not region-locked.\n"
    "- Thor — CEO & founder. Flagship, top-of-funnel C-suite stages. Audience: "
    "CEO, CIO/CTO, Chief AI Officer, COO, CDO, CPO, Head of Government "
    "Compliance, boards. Themes: AI strategy, culture of experimentation, AI "
    "literacy, enterprise innovation. Global; the catch-all for anything "
    "high-profile.\n"
    "- Verma — co-founder; REGULATED industries: insurance, healthcare, finance "
    "/ banking, capital markets, fintech. Audience: boards, exec teams, CIO/CTO, "
    "CEO, COO, CDO, CPO. Themes: de-risking AI, scaling experimentation, "
    "evidence-based decisions. Global, especially Asia-Pacific and Europe; "
    "catch-all alongside Thor.\n"
    "- Carlos — all of LATIN AMERICA (Brazil/Sao Paulo, Mexico, Argentina, "
    "Chile, Colombia, Peru, etc.). Usually mid-market but open to anything in "
    "the region; events he sources are his.\n"
    "Guidance: a European event -> Jerome; an HR / L&D / people or "
    "design-thinking event -> Joe; an insurance / health / finance event -> "
    "Verma; a Latin-American event -> Carlos; a flagship C-suite stage -> Thor. "
    "Thor and Verma are the catch-alls for high-profile events or anything "
    "outside the others' areas."
)

# Concise, non-sensitive company background (distilled from the ArcticBlue
# Obsidian overview — positioning + target buyers only; no client names or
# figures). Helps the assistant judge which events are a real fit. Override at
# runtime with the ARCTICBLUE_CONTEXT env var.
_COMPANY_CONTEXT = (os.environ.get('ARCTICBLUE_CONTEXT') or (
    "ArcticBlue AI is an enterprise-AI consulting and product studio (New York "
    "& San Francisco) that helps enterprise leadership teams de-risk and scale "
    "AI via sprint-based prototyping, synthetic user research, vendor "
    "feasibility tests, and executive AI-literacy workshops. Sweet-spot "
    "industries: insurance, healthcare, fintech, enterprise SaaS, retail / "
    "eCommerce, telco, and media. The best events are dense with in-house "
    "enterprise BUYERS (CxOs, heads of data / AI, transformation leaders) in "
    "those industries — not vendor-to-vendor expos."
)).strip()


# How the tracker itself works — so the assistant can answer "how do I…" and
# "what does … mean" questions accurately and in plain language. Keep it short;
# it's sent on every call.
_APP_GUIDE = (
    "APP GUIDE — how the ArcticBlue Event Tracker works (use for 'how do I…' and "
    "'what does … mean' questions):\n"
    "- It's a shared tracker of real-world AI/enterprise events ArcticBlue could "
    "speak at or attend. No login — you set your name via 'change' at the top so "
    "your edits and personal lists are attributed to you.\n"
    "- VIEWS (tabs): 'My Events' = the events you're booked to speak at or "
    "attending (plus a day-of brief); 'All Events' = the full catalog; 'Calendar' "
    "and 'Map' show the same events by date and by place.\n"
    "- TOP FILTERS: Pipeline (stage), Region, Fits (which teammate an event "
    "suits), Months, plus a keyword Search. 'Ask Anything' (this box) answers "
    "questions and ranks events.\n"
    "- ADD BUTTONS: '+ Add event' logs one by hand; 'Paste email' fills an event "
    "from a pasted invite; 'Find new events' asks the AI to discover new speaking "
    "events.\n"
    "- ON EACH EVENT CARD: the star = 'I'm interested' (personal, tied to your "
    "name); 'Apply to speak' opens that event's application/CFP link; 'Details' "
    "opens the full record, where 'Edit' lets you change the stage, ArcticBlue "
    "speaker, notes, links, and the 'Apply to speak link'.\n"
    "- STAT TILES across the top (click one to filter the list): Upcoming events, "
    "My Interests, Pending, Booked, Team Interests, Attending.\n"
    "- WHAT THE LABELS MEAN: Pending = a speaking application is in but not yet "
    "confirmed (Submitted / Followed up / Meeting held); Booked = confirmed to "
    "speak; Attending = going without speaking; Buyer-rich = the audience is full "
    "of in-house enterprise buyers (the events we want).\n"
    "Keep how-to answers short and friendly, and point people to the button or "
    "tab by name."
)


def _ask_openai(question, history, events, user=''):
    messages = [{'role': 'system',
                 'content': _SYSTEM.format(today=date.today().isoformat())}]
    messages.append({'role': 'system', 'content': _TEAM_CONTEXT})
    user = (user or '').strip()
    _first = user.split()[0].lower() if user.split() else ''
    if _first in ('angela', 'hurley'):
        # Sales-support: they run the tracker and Angela submits applications on
        # behalf of the WHOLE team, so never scope answers to one person's ICP.
        messages.append({'role': 'system', 'content': (
            'The person asking is "%s" — ArcticBlue SALES SUPPORT. Angela submits '
            'the speaking applications on behalf of the ENTIRE team, so "we", "us", '
            '"I", and "should we" refer to the whole team, NOT one person\'s '
            'coverage. When they ask what "we haven\'t submitted to yet", "still '
            'need to apply to", or "should apply to", answer with events where '
            'submitted=false across ALL teammates — this INCLUDES events tagged '
            'only "Identified" and events with no stage (both mean not-yet-applied). '
            'Do not restrict to any single territory; when helpful, note which '
            'teammate each event fits via its "fits" list. Neither Angela nor '
            'Hurley attend events themselves, so do not recommend events "for" '
            'them personally.' % user)})
    elif user and user.lower() != 'team':
        prof = PROFILE_BY_KEY.get(user) or (PROFILE_BY_KEY.get(user.split()[0]) if user.split() else None)
        if prof:
            messages.append({'role': 'system', 'content': (
                'The person asking is signed in as "%s", whose ArcticBlue coverage is: '
                '%s. When they say "me", "I", "my", "us", "should I", or ask which '
                'events fit them or where they should go, recommend ONLY upcoming '
                'events whose "fits" list includes "%s" (their coverage). Rank those '
                'HIGHEST-PRIORITY FIRST (priority High > Medium > Low > none), then '
                'by buyer-rich audience, anyone flagged Interested, pipeline stage, '
                'and soonest date. If none fit, say so plainly rather than '
                'offering events outside their coverage. When they ask generally (not '
                'about themselves), answer neutrally over all events.'
                % (prof['key'], prof['label'], prof['key']))})
        else:
            messages.append({'role': 'system', 'content': (
                'The person asking is signed in as "%s" (no specific coverage '
                'territory). When they say "me"/"I"/"my", tailor to any matching TEAM '
                'COVERAGE notes; otherwise answer neutrally over all events.' % user)})
    if _COMPANY_CONTEXT:
        messages.append({'role': 'system',
                         'content': 'ARCTICBLUE CONTEXT:\n' + _COMPANY_CONTEXT})
    messages.append({'role': 'system', 'content': _APP_GUIDE})
    messages.append({'role': 'system',
                     'content': 'EVENTS (JSON):\n' + json.dumps(events, ensure_ascii=False)})
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and h.get('role') in ('user', 'assistant') and h.get('content'):
            messages.append({'role': h['role'], 'content': str(h['content'])[:2000]})
    messages.append({'role': 'user', 'content': str(question)[:1000]})
    # No temperature override — newer models (gpt-5 / reasoning tier) only accept
    # the default, and the prompt is already tightly constrained.
    body = {'model': OPENAI_MODEL, 'messages': messages,
            'response_format': {'type': 'json_object'}}
    body.update(_tok(OPENAI_MODEL, 2000))  # gpt-5 reasoning shares this budget
    hdr = {'Authorization': 'Bearer ' + OPENAI_API_KEY}
    st, data = _http_json('POST', OPENAI_BASE + '/chat/completions', headers=hdr, body=body, timeout=90)
    if st in (400, 404) and OPENAI_FALLBACK and OPENAI_FALLBACK != OPENAI_MODEL:
        body.pop('max_tokens', None)
        body.pop('max_completion_tokens', None)
        body['model'] = OPENAI_FALLBACK
        body.update(_tok(OPENAI_FALLBACK, 2000))
        st, data = _http_json('POST', OPENAI_BASE + '/chat/completions', headers=hdr, body=body, timeout=90)
    if st != 200 or not isinstance(data, dict):
        raise RuntimeError('openai %s: %s' % (st, str(data)[:300]))
    served = data.get('model')
    content = data['choices'][0]['message']['content']
    try:
        parsed = json.loads(content)
        return (str(parsed.get('answer', '') or ''),
                [str(n) for n in (parsed.get('recommended') or []) if n],
                str(parsed.get('mode', '') or '').strip().lower(), served)
    except (json.JSONDecodeError, TypeError):
        return content, [], '', served


_PRIORITY_RANK = {'high': 3, 'medium': 2, 'low': 1}


def _priority_rank(card):
    return _PRIORITY_RANK.get((card.get('priority') or '').strip().lower(), 0)


def _match_cards(names, events):
    """Map model-recommended names to real event objects, preserving order."""
    by_lower = {}
    for e in events:
        nm = (e.get('name') or '').strip().lower()
        if nm and nm not in by_lower:
            by_lower[nm] = e
    cards, seen = [], set()
    for n in names:
        key = (n or '').strip().lower()
        hit = by_lower.get(key)
        if not hit:  # fall back to substring match
            for nm, e in by_lower.items():
                if key and (key in nm or nm in key):
                    hit = e
                    break
        if hit and id(hit) not in seen:
            seen.add(id(hit))
            cards.append({k: hit.get(k) for k in (
                'num', 'name', 'date', 'location', 'region', 'audience',
                'attend', 'stage', 'price', 'url', 'priority')})
        if len(cards) >= 8:
            break
    return cards


def _send(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type')
    handler.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, {})

    def do_GET(self):
        _send(self, 405, {'error': 'method not allowed',
                          'hint': 'POST {"question": "..."}'})

    def do_POST(self):
        try:
            self._handle()
        except Exception as e:  # noqa: BLE001
            _send(self, 500, {'error': 'unhandled', 'type': type(e).__name__,
                              'msg': str(e)[:400]})

    def _handle(self):
        if not OPENAI_API_KEY:
            return _send(self, 500, {'error': 'server not configured: OPENAI_API_KEY missing'})
        if not _same_origin(self):
            return _send(self, 403, {'error': 'forbidden: call from the tracker site'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
        except (ValueError, json.JSONDecodeError):
            return _send(self, 400, {'error': 'invalid JSON body'})
        question = (body.get('question') or '').strip()
        if not question:
            return _send(self, 400, {'error': 'no question'})
        events = _gather_events(self.headers.get('Host', ''))
        try:
            answer, names, mode, served = _ask_openai(question, body.get('history'), events, body.get('user'))
        except Exception as e:  # noqa: BLE001
            return _send(self, 502, {'error': 'assistant failed: %s' % str(e)[:300]})
        cards = _match_cards(names, events)
        # Guarantee highest-priority-first (High > Medium > Low > none) no matter
        # how the model ordered them. Python's sort is stable, so the model's
        # relevance order is preserved WITHIN each priority tier.
        cards.sort(key=_priority_rank, reverse=True)
        # How-to answers are about the tool, not any event — never attach cards
        # even if the model slipped an event name into 'recommended'.
        if mode == 'app':
            cards = []
        return _send(self, 200, {'answer': answer, 'cards': cards, 'mode': mode,
                                 'model': served or OPENAI_MODEL,
                                 'events_considered': len(events)})
