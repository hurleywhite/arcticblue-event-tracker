"""POST /api/briefing  — persona-aware Day-Of briefing for an attended event.
GET  /api/briefing?cron=1 — overnight pre-generation (Vercel cron).

Generates a sharp, attendee-specific brief for an event happening now (or
tomorrow, for the overnight job) when an ArcticBlue person is attending. The
persona (config/personas.json) bends every section to that person's mode
(room = work the floor / stage = earn the platform), ICP, and message.

Reuses the app's OpenAI plumbing (same key/pattern as Ask AI + ingest). Web
search supplies (a) speaker/company news, (b) audience signal vs the persona's
ICP, (c) for stage personas, whether a speaking route is open, and (d) recent
news (~last 3 days) on the event's speaker_topic.

BODY (POST):  {"kind":"event_state|manual_events", "key":<num|id>, "regenerate":bool}
RESPONSE 200: {"brief": <§3 schema>, "generated_at": iso, "cached": bool, "persona": "joe"}

ENV:
  OPENAI_API_KEY               (required)
  OPENAI_BRIEFING_MODEL        (default gpt-4o-mini-search-preview; set to a
                                newer search model e.g. gpt-5-search to upgrade)
  OPENAI_BRIEFING_FALLBACK     (default gpt-4o-mini-search-preview)
  SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY / SUPABASE_SERVICE_ROLE_KEY
  BRIEFING_CRON_SECRET         (guards the cron GET)
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SUPABASE_PUBLISHABLE = _env('SUPABASE_PUBLISHABLE_KEY')
SUPABASE_SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')
OPENAI_API_KEY = _env('OPENAI_API_KEY')
OPENAI_BASE = _env('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
BRIEFING_MODEL = _env('OPENAI_BRIEFING_MODEL', 'gpt-5.4')
BRIEFING_FALLBACK = _env('OPENAI_BRIEFING_FALLBACK', 'gpt-5-search-api')
# Deep-targets fallback retrieval — Perplexity (web-grounded) is the research API
# already wired into this app (api/search.py); used only when gpt-5.4 surfaces
# too few web-confirmed named people, to keep credit burn bounded.
PERPLEXITY_API_KEY = _env('PERPLEXITY_API_KEY')
PERPLEXITY_MODEL = _env('PERPLEXITY_MODEL', 'sonar')
PERPLEXITY_BASE = _env('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai').rstrip('/')


def _int_env(k, d):
    try:
        return int(_env(k) or d)
    except (ValueError, TypeError):
        return d


TARGETS_MAX = _int_env('TARGETS_MAX', 5)   # cap people per event
TARGETS_MIN = _int_env('TARGETS_MIN', 2)   # below this, escalate to Perplexity
# Vercel auto-sends `Authorization: Bearer ${CRON_SECRET}` on cron invocations
# when a CRON_SECRET env var exists; accept that or an explicit override.
CRON_SECRET = _env('CRON_SECRET') or _env('BRIEFING_CRON_SECRET')
STALE_HOURS = 24

_PERSONAS = None


def load_personas():
    global _PERSONAS
    if _PERSONAS is None:
        with open(os.path.join(ROOT, 'config', 'personas.json')) as f:
            _PERSONAS = json.load(f)
    return _PERSONAS


def _http_json(method, url, headers=None, body=None, timeout=60):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        h.setdefault('Content-Type', 'application/json')
    req = urllib.request.Request(url, method=method, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', errors='replace')
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


# ── attendee → persona resolution ────────────────────────────────────────────
def speaker_to_keys(speaker):
    """An assigned speaker string ('Thor', 'Thor, Jerome') -> persona keys."""
    out = []
    personas = load_personas()['personas']
    if not speaker:
        return out
    folded = re.sub(r'[^a-z ]', ' ', str(speaker).lower())
    for key, p in personas.items():
        first = p['name'].split()[0].lower()
        if re.search(r'\b' + re.escape(key) + r'\b', folded) or re.search(r'\b' + re.escape(first) + r'\b', folded):
            out.append(key)
    return out


def resolve_attendees(ev_state):
    """Union of explicit `attendees` + any persona matched by assigned `speaker`."""
    keys = []
    for k in (ev_state.get('attendees') or []):
        k = (k or '').strip().lower()
        if k and k not in keys:
            keys.append(k)
    for k in speaker_to_keys(ev_state.get('speaker')):
        if k not in keys:
            keys.append(k)
    personas = load_personas()['personas']
    return [k for k in keys if k in personas]


# ── prompt + schema ──────────────────────────────────────────────────────────
SECTIONS = ['at_a_glance', 'why_were_here', 'who_in_room', 'targets',
            'speaker_spotlight', 'topic_news', 'angles', 'logistics_win', 'unconfirmed']


def effective_mode(persona, status_tags):
    """What the person is actually doing at THIS event drives the brief's mode —
    NOT the persona's static default. Booked = speaking -> stage (own the
    platform); Attending = on the floor -> room (work the room). Falls back to
    the persona default only when the event carries no pipeline status. This is
    why two people 'just attending' the same event both read as room."""
    tags = [str(t).strip().lower() for t in (status_tags or [])]
    if 'booked' in tags:
        return 'stage'
    if 'attending' in tags:
        return 'room'
    return persona.get('mode', 'room')


def activity_label(status_tags):
    """The user-facing badge — plain and consistent. Two people both attending
    the same event both read 'Attending' (room/stage is internal framing only)."""
    tags = [str(t).strip().lower() for t in (status_tags or [])]
    if 'booked' in tags:
        return 'Speaking'
    if 'attending' in tags:
        return 'Attending'
    if 'meeting held' in tags or 'submitted' in tags:
        return 'In progress'
    return 'Targeting'


def _today():
    return date.today().isoformat()


def build_messages(event, persona, topic, mode):
    ab = load_personas()['arcticblue']
    sys = (
        "You are ArcticBlue's Day-Of event-briefing engine. You write a sharp, "
        "phone-scannable brief for ONE ArcticBlue person attending ONE event "
        "today, so they walk in knowing exactly what to do.\n"
        "VOICE: " + ab['voice'] + "\n"
        "ANTI-FABRICATION (hard rules): never invent attendee names, metrics, "
        "quotes, or speaker claims. Only state a named person/news item if web "
        "search confirms it; otherwise put it in `unconfirmed`. The ONLY metrics "
        "you may cite are these whitelisted proof points: " + '; '.join(ab['proof_points']) + ".\n"
        "MODE FOR THIS EVENT = '" + mode + "' (derived from what they're doing "
        "here, not a generic label): room = they're ATTENDING — work the floor, "
        "pipeline in their ICP; stage = they're SPEAKING / own a platform — "
        "speaking route, prestige intros. Bend every section to this mode + the "
        "persona's buyer_titles, icp_industries, themes, and outcome_target.\n"
        "ANGLES + WHY-WE'RE-HERE must be EVENT-SPECIFIC. Each angle ties a "
        "concrete fact about THIS event (a theme on its agenda, a speaker, a "
        "recent news item you found) to ArcticBlue's value. HARD RULE: the "
        "'angles' array must NOT contain the persona's positioning-lens phrases "
        "verbatim or any recited marketing tagline — write FRESH lines. "
        "Good angle (sovereignty-themed summit): 'Rome's strategic-autonomy "
        "agenda is the opening — frame go/pivot/kill experimentation as how "
        "sovereign-AI ambitions skip the 12-18-month roadmap trap.' If you can't "
        "ground an angle in an event specific, drop it.\n"
        "KEEP IT TIGHT + phone-scannable so the JSON never truncates: at most 3 "
        "speakers in speaker_spotlight, 5 people_to_find, 3 topic_news, 3 angles; "
        "1-2 news items per speaker.\n"
        "USE WEB SEARCH for: (a) the event's speakers + their recent news, "
        "(b) audience signal vs the persona's ICP, (c) for stage mode, whether a "
        "speaking route / CFP is currently open (give the link), and (d) 2-3 news "
        "items from the LAST 3 DAYS relevant to the speaker_topic.\n"
        "TARGETS = the actionable core. people_to_find must be SPECIFIC, "
        "web-confirmed people or orgs actually at THIS event — prioritize "
        "NON-OBVIOUS targets (sponsors, exhibitors, partner-org reps, "
        "organizers / program leads, named confirmed attendees) over headline "
        "speakers (those are obvious and everyone chases them). For each give "
        "name, org, role, why (tie to the attendee's ICP), and where to find "
        "them (booth / session / track) if known. confidence:'confirmed' ONLY "
        "when web search verifies they are attending/speaking/sponsoring; else "
        "'estimated'. Do NOT pad this list with generic title categories — if "
        "you genuinely cannot web-confirm specific names/orgs, return at most 2 "
        "'estimated' role-types AND add an unconfirmed note that no attendee "
        "roster was found.\n"
        "URLS: every news url MUST be a REAL, working article link you actually "
        "opened via web search — never invent, guess, or pattern-construct a "
        "URL. If you are not certain a url is real, omit that item.\n"
        "Return ONLY a JSON object with EXACTLY these keys: "
        "at_a_glance {event, dates, venue, format, priority, track, region, covered_by, mode}; "
        "why_were_here (string, 2-3 sentences); "
        "who_in_room {confidence:'estimated'|'confirmed', titles:[..], industries:[..], named:[{name,title,org}]}; "
        "targets {people_to_find:[{name, org, role, why, where, confidence:'confirmed'|'estimated'}], outcome_target:string, speaking_route_open:string|null, facilitator_leads:[..]}; "
        "speaker_spotlight:[{name, who, news:[{headline,date,url}], hook}]; "
        "topic_news:[{headline,date,url,relevance}]; "
        "angles:[string,..]; "
        "logistics_win {time, room, link, win}; "
        "unconfirmed:[string,..]. "
        "speaking_route_open and facilitator_leads apply to stage / Joe respectively; "
        "use null / [] otherwise. Every news item MUST carry a real source url.\n"
        "Output ONLY the raw JSON object — no markdown code fences, no commentary "
        "before or after it."
    )
    # Keep signature_angles OUT of the copyable persona blob — pass them as a
    # do-not-quote lens, or the model just pastes them into 'angles'.
    persona_blob = {k: v for k, v in persona.items() if k != 'signature_angles'}
    user = (
        "ATTENDEE PERSONA:\n" + json.dumps(persona_blob, ensure_ascii=False) + "\n\n"
        "POSITIONING LENS (background ONLY — NEVER copy these phrases into "
        "'angles'): " + '; '.join(persona.get('signature_angles') or []) + "\n\n"
        "SPEAKER TOPIC (drives the topic_news search): " + (topic or '(none given — infer from the event + persona themes)') + "\n\n"
        "EVENT:\n" + json.dumps(event, ensure_ascii=False) + "\n\n"
        "Today is " + _today() + ". Write the brief now."
    )
    return [{'role': 'system', 'content': sys}, {'role': 'user', 'content': user}]


def _tok(model, n):
    """gpt-5 / o-series require max_completion_tokens; older models use max_tokens."""
    m = (model or '').lower()
    key = 'max_completion_tokens' if m.startswith(('gpt-5', 'o1', 'o3', 'o4')) else 'max_tokens'
    return {key: n}


def _call_openai(messages, model):
    # NB: search models reject response_format=json_object, so we ask for raw JSON
    # in the prompt and extract it. gpt-5 reasoning shares the token budget, so
    # keep it ample.
    body = {'model': model, 'messages': messages}
    body.update(_tok(model, 6000))
    st, data = _http_json('POST', OPENAI_BASE + '/chat/completions',
                          headers={'Authorization': 'Bearer ' + OPENAI_API_KEY},
                          body=body, timeout=200)
    return st, data


def _url_ok(url):
    """True if the link is real + reachable. A hallucinated path 404s; a fake
    domain errors. Bot-blocks (401/403/405) or rate limits mean the URL is real,
    so we keep those — only a definitive 404/410 or a network failure drops it.
    A slow-but-not-dead host should not block: we time out at 4s and keep the
    link rather than dropping a probably-real URL we couldn't reach in time."""
    u = str(url or '')
    if not u.startswith(('http://', 'https://')):
        return False
    try:
        req = urllib.request.Request(u, method='GET', headers={
            'User-Agent': 'Mozilla/5.0 (ArcticBlueTracker)', 'Range': 'bytes=0-2048'})
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        return e.code not in (404, 410)
    except (urllib.error.URLError, TimeoutError, OSError):
        # timeout / transient network failure → don't punish a likely-real link
        return True
    except Exception:
        return False


# Cap how many links we probe per brief so a run of slow hosts can't stack
# sequential timeouts toward Vercel's maxDuration (4s each, budget below).
_VERIFY_BUDGET = 8


def _verify_news(brief):
    """Drop any news item whose source URL doesn't resolve — kills the model's
    plausible-looking-but-fabricated links. Surfaced honestly in unconfirmed.
    Only the first _VERIFY_BUDGET links are probed; the rest are kept as-is."""
    budget = [_VERIFY_BUDGET]

    def ok(url):
        if budget[0] <= 0:
            return True  # out of probe budget — keep without checking
        budget[0] -= 1
        return _url_ok(url)

    dropped = 0
    tn = brief.get('topic_news') or []
    keep = [n for n in tn if ok(n.get('url'))]
    dropped += len(tn) - len(keep)
    brief['topic_news'] = keep
    for s in (brief.get('speaker_spotlight') or []):
        ns = s.get('news') or []
        k = [n for n in ns if ok(n.get('url'))]
        dropped += len(ns) - len(k)
        s['news'] = k
    # The logistics 'link' is model-supplied too — verify it so a fabricated
    # venue/agenda URL doesn't ship. Blank just the link, keep the section.
    lw = brief.get('logistics_win')
    if isinstance(lw, dict) and lw.get('link') and not ok(lw.get('link')):
        lw['link'] = None
        dropped += 1
    if dropped:
        u = brief.get('unconfirmed') or []
        u.append('%d link(s) could not be verified and were removed.' % dropped)
        brief['unconfirmed'] = u
    return brief


def generate_brief(event, persona, topic, mode, activity):
    messages = build_messages(event, persona, topic, mode)
    st, data = _call_openai(messages, BRIEFING_MODEL)
    # Fall back if the configured model id is rejected (e.g. not yet available).
    if st in (400, 404) and BRIEFING_FALLBACK and BRIEFING_FALLBACK != BRIEFING_MODEL:
        st, data = _call_openai(messages, BRIEFING_FALLBACK)
    if st != 200 or not isinstance(data, dict):
        raise RuntimeError('openai %s: %s' % (st, str(data)[:300]))
    # A 200 can still carry an empty/refused completion (content filter, no
    # choices). Degrade to a skeleton brief instead of throwing a 502.
    try:
        content = data['choices'][0]['message']['content'] or ''
    except (KeyError, IndexError, TypeError):
        content = ''
    brief = {}
    try:
        brief = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        # strip ```json fences / preamble and grab the outermost {...}
        m = re.search(r'\{.*\}', content, re.S)
        if m:
            try:
                brief = json.loads(m.group(0))
            except (json.JSONDecodeError, TypeError):
                brief = {}
    model_used = data.get('model') if isinstance(data, dict) else None
    b = normalize_brief(brief, event, persona, mode, activity)
    b = _verify_news(b)
    return b, model_used


def normalize_brief(brief, event, persona, mode, activity):
    """Guarantee every §3 section exists so the UI renders deterministically."""
    if not isinstance(brief, dict):
        brief = {}
    g = brief.get('at_a_glance') or {}
    if not isinstance(g, dict):
        g = {}
    g.setdefault('event', event.get('name'))
    g.setdefault('dates', event.get('date_str'))
    g.setdefault('region', event.get('region'))
    # covered_by + mode are authoritative from the persona — never let the model
    # override them (it sometimes echoes the event source, e.g. 'arcticscout').
    g['covered_by'] = persona.get('name')
    # Plain, consistent badge (Attending / Speaking). room/stage is internal
    # framing only and is NOT shown as a label — it confused the read.
    g['activity'] = activity
    g.pop('mode', None)
    brief['at_a_glance'] = g
    brief.setdefault('why_were_here', '')
    wir = brief.get('who_in_room') or {}
    if not isinstance(wir, dict):
        wir = {}
    wir.setdefault('confidence', 'estimated')
    for k in ('titles', 'industries', 'named'):
        if not isinstance(wir.get(k), list):
            wir[k] = []
    brief['who_in_room'] = wir
    t = brief.get('targets') or {}
    if not isinstance(t, dict):
        t = {}
    if not isinstance(t.get('people_to_find'), list):
        t['people_to_find'] = []
    t.setdefault('outcome_target', persona.get('outcome_target'))
    if mode != 'stage':
        t['speaking_route_open'] = t.get('speaking_route_open') or None
    if persona.get('name') != load_personas()['personas']['joe']['name']:
        t['facilitator_leads'] = t.get('facilitator_leads') if isinstance(t.get('facilitator_leads'), list) else []
    brief['targets'] = t
    for k in ('speaker_spotlight', 'topic_news', 'angles', 'unconfirmed'):
        if not isinstance(brief.get(k), list):
            brief[k] = []
    # Belt-and-suspenders: a canned signature_angle must never reach the output,
    # even if the model parrots it. Drop verbatim matches; cap at 3.
    sig = {str(s).strip().lower() for s in (persona.get('signature_angles') or [])}
    brief['angles'] = [a for a in brief['angles'] if str(a).strip().lower() not in sig][:3]
    lw = brief.get('logistics_win') or {}
    if not isinstance(lw, dict):
        lw = {}
    lw.setdefault('win', persona.get('outcome_target'))
    brief['logistics_win'] = lw
    return brief


# ── Supabase load + cache ─────────────────────────────────────────────────────
def _sb_headers(service=False):
    key = SUPABASE_SERVICE_ROLE if (service and SUPABASE_SERVICE_ROLE) else SUPABASE_PUBLISHABLE
    return {'apikey': key, 'Authorization': 'Bearer ' + key}


def load_event(kind, key, host):
    """Return (event_facts, state_row) for a catalog (event_state) or manual row."""
    if kind == 'manual_events':
        st, rows = _http_json('GET', SUPABASE_URL + '/rest/v1/manual_events?id=eq.' + urllib.parse.quote(str(key)),
                              headers=_sb_headers(service=True))
        row = rows[0] if (st == 200 and isinstance(rows, list) and rows) else None
        return (row or {}), (row or {})
    # catalog: facts from events.json, tracking from event_state
    facts = {}
    if host:
        st, data = _http_json('GET', 'https://%s/events.json' % host, timeout=15)
        if st == 200 and isinstance(data, dict):
            facts = next((e for e in (data.get('events') or []) if str(e.get('num')) == str(key)), {}) or {}
    st, rows = _http_json('GET', SUPABASE_URL + '/rest/v1/event_state?event_num=eq.' + urllib.parse.quote(str(key)),
                          headers=_sb_headers(service=True))
    state = rows[0] if (st == 200 and isinstance(rows, list) and rows) else {}
    return facts, state


def cache_brief(kind, key, brief, when):
    """Best-effort: store the brief. Silently no-ops if columns don't exist yet."""
    col = 'event_num' if kind == 'event_state' else 'id'
    patch = {'briefing_json': brief, 'briefing_generated_at': when}
    url = '%s/rest/v1/%s?%s=eq.%s' % (SUPABASE_URL, kind, col, urllib.parse.quote(str(key)))
    h = dict(_sb_headers(service=True)); h['Prefer'] = 'return=minimal'
    return _http_json('PATCH', url, headers=h, body=patch)


def event_facts_for(kind, facts, state):
    """Flatten event facts + tracking into the dict handed to the model."""
    e = dict(facts or {})
    s = state or {}
    for k in ('speaker', 'speaker_topic', 'status_tags', 'status', 'attendees', 'venue', 'past_speakers'):
        if s.get(k) not in (None, '', []):
            e[k] = s[k]
    return e


def is_stale(state):
    when = (state or {}).get('briefing_generated_at')
    if not when:
        return True
    try:
        gen = datetime.fromisoformat(str(when).replace('Z', '+00:00'))
        return (datetime.now(gen.tzinfo) - gen) > timedelta(hours=STALE_HOURS)
    except (ValueError, TypeError):
        return True


# ── handler ───────────────────────────────────────────────────────────────────
def _send(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    handler.end_headers()
    handler.wfile.write(body)


def _one(kind, key, host, regenerate):
    facts, state = load_event(kind, key, host)
    keys = resolve_attendees(state if kind == 'event_state' else facts)
    if not keys:
        return {'error': 'no attendees on this event'}, 400
    persona = load_personas()['personas'][keys[0]]
    row = state if kind == 'event_state' else facts
    mode = effective_mode(persona, row.get('status_tags'))
    activity = activity_label(row.get('status_tags'))
    if not regenerate and state.get('briefing_json') and not is_stale(state):
        return {'brief': state['briefing_json'], 'generated_at': state.get('briefing_generated_at'),
                'cached': True, 'persona': keys[0], 'activity': activity}, 200
    ev = event_facts_for(kind, facts, state)
    brief, model_used = generate_brief(ev, persona, ev.get('speaker_topic'), mode, activity)
    when = datetime.utcnow().isoformat() + 'Z'
    cache_brief(kind, key, brief, when)
    return {'brief': brief, 'generated_at': when, 'cached': False, 'persona': keys[0],
            'activity': activity, 'mode': mode, 'model': model_used}, 200


# ── Deep outreach targets ─────────────────────────────────────────────────────
# A heavier, on-demand pass (separate from the cheap auto-brief): finds the
# senior, BUDGET-OWNING decision-makers worth reaching out to before an event,
# with a recent signal + a drafted opener for each. gpt-5.4 (web search) first;
# Perplexity retrieval only when too few web-confirmed people surface.
def _content_of(st, data):
    if st != 200 or not isinstance(data, dict):
        return ''
    try:
        return data['choices'][0]['message']['content'] or ''
    except (KeyError, IndexError, TypeError):
        return ''


def _extract_json(content):
    if not content:
        return {}
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r'\{.*\}', content, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, TypeError):
                return {}
    return {}


def build_targets_messages(event, persona, extra_context=''):
    ab = load_personas()['arcticblue']
    titles = ', '.join(persona.get('buyer_titles') or [])
    inds = ', '.join(persona.get('icp_industries') or [])
    themes = ', '.join(persona.get('themes') or [])
    first = (persona.get('name') or '').split(' ')[0]
    sys = (
        "You are ArcticBlue's pre-event outreach researcher. For ONE event you "
        "find the SENIOR, BUDGET-OWNING decision-makers worth contacting before "
        "it, and draft a short personalized opener for each.\n"
        "VOICE for the drafts: " + ab['voice'] + "\n"
        "ANTI-FABRICATION (hard rules): NEVER invent a person, title, org, "
        "session, quote, date, or news item. Only include a named person if web "
        "search confirms they are SPEAKING at, hosting, sponsoring, or confirmed "
        "attending THIS event (from the official agenda/speaker page or a "
        "credible source). If you cannot web-confirm any such people, return an "
        "EMPTY people list and explain in `note` — never pad with guesses. The "
        "ONLY metrics a draft may cite are these whitelisted proof points: "
        + '; '.join(ab['proof_points']) + ". Never invent metrics or quotes.\n"
        "WHO TO PICK: senior decision-makers with BUDGET AUTHORITY in the "
        "persona's segment — titles like " + titles + " — at " + inds + " "
        "organizations. EXCLUDE operators, individual contributors, engineers, "
        "junior/mid managers, vendors selling competing tooling, and generic "
        "startup traffic. Prefer people on the published agenda (speakers / "
        "panelists / fireside guests) and named hosts/sponsors.\n"
        "FOR EACH PERSON (max " + str(TARGETS_MAX) + "): name; title; org; "
        "segment_fit (one line: why they're an ICP budget-holder, e.g. owns the "
        "AI/transformation budget at a regulated enterprise); session (their "
        "panel/talk title + day/time if on the agenda, else their confirmed role "
        "at the event); recent_signal = ONE item from roughly the LAST TWO "
        "MONTHS (a company launch/announcement, their interview/podcast/post, a "
        "board/hire move) as {summary (1 line), date (approx), url (a REAL link "
        "you actually opened — never invent or pattern-build a url; omit the url "
        "if unsure)}; linkedin_url (their real profile if findable, else null); "
        "draft_email = a 3-5 sentence opener in the VOICE above, FROM " + first +
        " TO that person, opening 'Hi <first name>,', referencing the "
        "recent_signal AND their event session, tying to an ArcticBlue theme ("
        + themes + "), ending with '" + first + "'. No invented mutual "
        "connections. confidence:'confirmed' only if web-confirmed at this event, "
        "else 'estimated'.\n"
        "Return ONLY a JSON object: {people:[{name,title,org,segment_fit,session,"
        "recent_signal:{summary,date,url},linkedin_url,draft_email,confidence}],"
        "note:string}. `note` states coverage honestly (e.g. 'No public speaker "
        "list yet — these are confirmed sponsors only' or 'Full agenda found'). "
        "Output ONLY the raw JSON object — no markdown fences, no commentary."
    )
    persona_blob = {k: v for k, v in persona.items() if k != 'signature_angles'}
    user = (
        "PERSONA (the sender):\n" + json.dumps(persona_blob, ensure_ascii=False) + "\n\n"
        "EVENT:\n" + json.dumps(event, ensure_ascii=False) + "\n\n"
        + (("RESEARCH FINDINGS to ground your answer (from a web-search engine — "
            "verify, then structure these named people/signals; do not add "
            "unconfirmed names):\n" + extra_context + "\n\n") if extra_context else "")
        + "RESEARCH STEPS: (1) Open the event's official URL above and actively "
        "look for its Speakers / Agenda / Programme / Sponsors pages (try the "
        "site's /speakers, /agenda, /programme, /line-up paths). Most enterprise "
        "conferences publish a named speaker + session list — read it. (2) From "
        "that list, keep only the senior budget-holders in the persona's ICP. "
        "(3) For each, search their name for a recent signal + LinkedIn. Only "
        "after genuinely checking the official agenda should you conclude no "
        "roster is public. Today is " + _today() + ". Find the people and draft now."
    )
    return [{'role': 'system', 'content': sys}, {'role': 'user', 'content': user}]


def _perplexity_lookup(event, persona):
    """Web-grounded retrieval fallback — returns a plain-text findings blob."""
    if not PERPLEXITY_API_KEY:
        return ''
    titles = ', '.join(persona.get('buyer_titles') or [])
    inds = ', '.join(persona.get('icp_industries') or [])
    q = (
        "List the senior, budget-owning decision-makers (titles like " + titles +
        ") from " + inds + " organizations who are confirmed SPEAKING, hosting, "
        "sponsoring, or attending this event: '" + str(event.get('name') or '') +
        "' on " + str(event.get('date_str') or '') + " in " +
        str(event.get('location') or '') + " (official site: " +
        str(event.get('url') or 'n/a') + "). For each give name, title, company, "
        "the session/panel they're on (day/time if listed), and ONE recent "
        "(~last 2 months) company or personal news item WITH its source URL. Only "
        "include people you can confirm from the official agenda or a credible "
        "source. If no speaker list is public, say so plainly."
    )
    st, data = _http_json('POST', PERPLEXITY_BASE + '/chat/completions',
                          headers={'Authorization': 'Bearer ' + PERPLEXITY_API_KEY},
                          body={'model': PERPLEXITY_MODEL,
                                'messages': [{'role': 'user', 'content': q}]},
                          timeout=60)
    return _content_of(st, data)


def _clean_linkedin(u):
    u = (u or '').strip()
    return u if (u and 'linkedin.com/in' in u.lower()) else None


def normalize_targets(data, event, persona):
    """Enforce the schema, drop nameless rows, verify signal URLs, cap at MAX."""
    if not isinstance(data, dict):
        data = {}
    people = data.get('people') if isinstance(data.get('people'), list) else []
    budget = [_VERIFY_BUDGET]
    out = []
    for p in people:
        if not isinstance(p, dict):
            continue
        name = (p.get('name') or '').strip()
        if not name:
            continue
        sig = p.get('recent_signal') if isinstance(p.get('recent_signal'), dict) else {}
        url = (sig.get('url') or '').strip()
        # Verify the signal source (shared probe budget) — drop a dead/fake link
        # but keep the signal text so the lead is still usable.
        if url and budget[0] > 0:
            budget[0] -= 1
            if not _url_ok(url):
                url = ''
        out.append({
            'name': name,
            'title': (p.get('title') or '').strip(),
            'org': (p.get('org') or '').strip(),
            'segment_fit': (p.get('segment_fit') or '').strip(),
            'session': (p.get('session') or '').strip(),
            'recent_signal': {
                'summary': (sig.get('summary') or '').strip(),
                'date': (sig.get('date') or '').strip(),
                'url': url,
            },
            'linkedin_url': _clean_linkedin(p.get('linkedin_url')),
            'draft_email': (p.get('draft_email') or '').strip(),
            'warm_via': None,   # reserved for the connections-CSV feature
            'confidence': 'confirmed' if p.get('confidence') == 'confirmed' else 'estimated',
        })
        if len(out) >= TARGETS_MAX:
            break
    return {'people': out, 'note': (data.get('note') or '').strip()}


def generate_targets(event, persona):
    msgs = build_targets_messages(event, persona)
    st, data = _call_openai(msgs, BRIEFING_MODEL)
    if st in (400, 404) and BRIEFING_FALLBACK and BRIEFING_FALLBACK != BRIEFING_MODEL:
        st, data = _call_openai(msgs, BRIEFING_FALLBACK)
    model_used = data.get('model') if isinstance(data, dict) else None
    result = normalize_targets(_extract_json(_content_of(st, data)), event, persona)
    # Escalate to Perplexity retrieval only when gpt-5.4 found too few people.
    if len(result['people']) < TARGETS_MIN and PERPLEXITY_API_KEY:
        ctx = (_perplexity_lookup(event, persona) or '').strip()
        if ctx:
            st2, data2 = _call_openai(build_targets_messages(event, persona, extra_context=ctx), BRIEFING_MODEL)
            merged = normalize_targets(_extract_json(_content_of(st2, data2)), event, persona)
            if len(merged['people']) > len(result['people']):
                result = merged
                model_used = (data2.get('model') if isinstance(data2, dict) else model_used)
                result['note'] = (result.get('note') + ' ' if result.get('note') else '') + '(augmented via Perplexity retrieval)'
    return result, model_used


def cache_targets(kind, key, targets, when):
    """Best-effort cache — no-ops if the targets_json column isn't there yet."""
    col = 'event_num' if kind == 'event_state' else 'id'
    patch = {'targets_json': targets, 'targets_generated_at': when}
    url = '%s/rest/v1/%s?%s=eq.%s' % (SUPABASE_URL, kind, col, urllib.parse.quote(str(key)))
    h = dict(_sb_headers(service=True)); h['Prefer'] = 'return=minimal'
    return _http_json('PATCH', url, headers=h, body=patch)


def _targets_one(kind, key, host, regenerate):
    facts, state = load_event(kind, key, host)
    row = state if kind == 'event_state' else facts
    keys = resolve_attendees(row)
    if not keys:
        return {'error': 'assign an attendee first — targets are tailored to that person\'s ICP'}, 400
    persona = load_personas()['personas'].get(keys[0])
    if not persona:
        return {'error': 'unknown persona: %s' % keys[0]}, 400
    cached = row.get('targets_json')
    if not regenerate and isinstance(cached, dict) and isinstance(cached.get('people'), list):
        return {'targets': cached, 'cached': True, 'persona': keys[0],
                'generated_at': row.get('targets_generated_at')}, 200
    ev = event_facts_for(kind, facts, state)
    targets, model_used = generate_targets(ev, persona)
    when = datetime.utcnow().isoformat() + 'Z'
    try:
        cache_targets(kind, key, targets, when)
    except Exception:  # noqa: BLE001
        pass
    return {'targets': targets, 'cached': False, 'persona': keys[0],
            'generated_at': when, 'model': model_used}, 200


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, {})

    def do_GET(self):
        # Overnight cron: pre-generate briefs for events in range tomorrow/today.
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if qs.get('cron'):
            secret = (self.headers.get('Authorization', '') or '').replace('Bearer ', '').strip() or (qs.get('secret', [''])[0])
            if CRON_SECRET and secret != CRON_SECRET:
                return _send(self, 403, {'error': 'bad cron secret'})
            return self._cron()
        return _send(self, 405, {'error': 'POST {kind,key} or GET ?cron=1'})

    def do_POST(self):
        try:
            if not OPENAI_API_KEY:
                return _send(self, 500, {'error': 'OPENAI_API_KEY missing'})
            if not _same_origin(self):
                return _send(self, 403, {'error': 'forbidden: call from the tracker site'})
            try:
                length = int(self.headers.get('Content-Length', '0') or '0')
                body = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
            except (ValueError, json.JSONDecodeError):
                return _send(self, 400, {'error': 'invalid JSON body'})
            kind = body.get('kind') or 'event_state'
            key = body.get('key')
            if key is None:
                return _send(self, 400, {'error': 'key required'})
            host = self.headers.get('Host', '')
            # Deep outreach targets are a separate, heavier on-demand pass.
            if body.get('deep_targets'):
                payload, status = _targets_one(kind, key, host, bool(body.get('regenerate')))
                return _send(self, status, payload)
            payload, status = _one(kind, key, host, bool(body.get('regenerate')))
            return _send(self, status, payload)
        except Exception as e:  # noqa: BLE001
            return _send(self, 502, {'error': 'briefing failed: %s' % str(e)[:300]})

    def _cron(self):
        host = self.headers.get('Host', '')
        done, errors = [], []
        target = (date.today() + timedelta(days=1)).isoformat()  # generate the night before
        # catalog: events.json in range + event_state attendees
        st, data = _http_json('GET', 'https://%s/events.json' % host, timeout=20)
        st2, states = _http_json('GET', SUPABASE_URL + '/rest/v1/event_state?select=event_num,attendees,speaker,speaker_topic,briefing_generated_at,briefing_json',
                                 headers=_sb_headers(service=True))
        smap = {r.get('event_num'): r for r in states if isinstance(r, dict)} if isinstance(states, list) else {}
        for e in (data.get('events') or []) if isinstance(data, dict) else []:
            s = smap.get(e.get('num'), {})
            lo, hi = e.get('start_date'), e.get('end_date') or e.get('start_date')
            if not (lo and lo <= target <= (hi or lo)):
                continue
            if not resolve_attendees(s):
                continue
            try:
                self._gen_cache('event_state', e.get('num'), host); done.append(e.get('num'))
            except Exception as ex:  # noqa: BLE001
                errors.append({'num': e.get('num'), 'err': str(ex)[:120]})
        return _send(self, 200, {'pre_generated': done, 'errors': errors, 'for_date': target})

    def _gen_cache(self, kind, key, host):
        facts, state = load_event(kind, key, host)
        keys = resolve_attendees(state if kind == 'event_state' else facts)
        if not keys:
            return
        persona = load_personas()['personas'][keys[0]]
        row = state if kind == 'event_state' else facts
        mode = effective_mode(persona, row.get('status_tags'))
        activity = activity_label(row.get('status_tags'))
        ev = event_facts_for(kind, facts, state)
        brief, _model = generate_brief(ev, persona, ev.get('speaker_topic'), mode, activity)
        cache_brief(kind, key, brief, datetime.utcnow().isoformat() + 'Z')
