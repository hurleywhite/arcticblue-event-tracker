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
BRIEFING_MODEL = _env('OPENAI_BRIEFING_MODEL', 'gpt-5-search')
BRIEFING_FALLBACK = _env('OPENAI_BRIEFING_FALLBACK', 'gpt-4o-mini-search-preview')
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
        "ANGLES + WHY-WE'RE-HERE must be EVENT-SPECIFIC and grounded in this "
        "event's real focus and the recent news you find — NOT a recited "
        "marketing tagline. Use the persona's signature_angles only as the "
        "underlying positioning lens; do NOT quote them verbatim. Each angle is a "
        "concrete, usable talking point a smart peer would respect.\n"
        "USE WEB SEARCH for: (a) the event's speakers + their recent news, "
        "(b) audience signal vs the persona's ICP, (c) for stage mode, whether a "
        "speaking route / CFP is currently open (give the link), and (d) 2-3 news "
        "items from the LAST 3 DAYS relevant to the speaker_topic.\n"
        "Return ONLY a JSON object with EXACTLY these keys: "
        "at_a_glance {event, dates, venue, format, priority, track, region, covered_by, mode}; "
        "why_were_here (string, 2-3 sentences); "
        "who_in_room {confidence:'estimated'|'confirmed', titles:[..], industries:[..], named:[{name,title,org}]}; "
        "targets {people_to_find:[..], outcome_target:string, speaking_route_open:string|null, facilitator_leads:[..]}; "
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
    user = (
        "ATTENDEE PERSONA:\n" + json.dumps(persona, ensure_ascii=False) + "\n\n"
        "SPEAKER TOPIC (drives the topic_news search): " + (topic or '(none given — infer from the event + persona themes)') + "\n\n"
        "EVENT:\n" + json.dumps(event, ensure_ascii=False) + "\n\n"
        "Today is " + _today() + ". Write the brief now."
    )
    return [{'role': 'system', 'content': sys}, {'role': 'user', 'content': user}]


def _call_openai(messages, model):
    st, data = _http_json(
        'POST', OPENAI_BASE + '/chat/completions',
        headers={'Authorization': 'Bearer ' + OPENAI_API_KEY},
        # NB: the *-search-preview models reject response_format=json_object, so
        # we ask for raw JSON in the prompt and extract it (see generate_brief).
        body={'model': model, 'messages': messages, 'max_tokens': 3000}, timeout=120)
    return st, data


def generate_brief(event, persona, topic, mode):
    messages = build_messages(event, persona, topic, mode)
    st, data = _call_openai(messages, BRIEFING_MODEL)
    # Fall back if the configured model id is rejected (e.g. not yet available).
    if st in (400, 404) and BRIEFING_FALLBACK and BRIEFING_FALLBACK != BRIEFING_MODEL:
        st, data = _call_openai(messages, BRIEFING_FALLBACK)
    if st != 200 or not isinstance(data, dict):
        raise RuntimeError('openai %s: %s' % (st, str(data)[:300]))
    content = data['choices'][0]['message']['content'] or ''
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
    return normalize_brief(brief, event, persona, mode), model_used


def normalize_brief(brief, event, persona, mode):
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
    g['mode'] = mode
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
    if not regenerate and state.get('briefing_json') and not is_stale(state):
        return {'brief': state['briefing_json'], 'generated_at': state.get('briefing_generated_at'),
                'cached': True, 'persona': keys[0]}, 200
    ev = event_facts_for(kind, facts, state)
    brief, model_used = generate_brief(ev, persona, ev.get('speaker_topic'), mode)
    when = datetime.utcnow().isoformat() + 'Z'
    cache_brief(kind, key, brief, when)
    return {'brief': brief, 'generated_at': when, 'cached': False,
            'persona': keys[0], 'mode': mode, 'model': model_used}, 200


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
            length = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
            kind = body.get('kind') or 'event_state'
            key = body.get('key')
            if key is None:
                return _send(self, 400, {'error': 'key required'})
            payload, status = _one(kind, key, self.headers.get('Host', ''), bool(body.get('regenerate')))
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
        smap = {r['event_num']: r for r in states} if isinstance(states, list) else {}
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
        ev = event_facts_for(kind, facts, state)
        brief, _model = generate_brief(ev, persona, ev.get('speaker_topic'), mode)
        cache_brief(kind, key, brief, datetime.utcnow().isoformat() + 'Z')
