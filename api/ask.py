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
OPENAI_MODEL = _env('OPENAI_CHAT_MODEL', _env('OPENAI_MODEL', 'gpt-4o-mini'))
OPENAI_BASE = _env('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')

MAX_EVENTS_CONTEXT = 300


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


def _gather_events(host):
    """Compact, model-friendly list of every event: catalog (events.json) +
    manual (manual_events) merged with ops state (event_state)."""
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
                if ops.get('hidden'):
                    continue  # hidden events are noise for recommendations
                out.append({
                    'num': e.get('num'),
                    'name': e.get('name'), 'date': e.get('date_str'),
                    'location': e.get('location'), 'region': e.get('region'),
                    'type': e.get('type'), 'priority': e.get('priority'),
                    'audience': e.get('audience_type'), 'price': e.get('pricing'),
                    'deadline': e.get('deadline'),
                    'stage': ', '.join(stages) if stages else None,
                    'speaker': ops.get('speaker'),
                    'attend': ops.get('attend_verdict'),
                    'saved': bool(ops.get('saved')),
                    'why': _truncate(e.get('why'), 220),
                    'url': e.get('url'),
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
            out.append({
                'name': m.get('name'), 'date': m.get('date_str'),
                'location': m.get('location'), 'region': m.get('region'),
                'type': m.get('type'), 'priority': m.get('priority'),
                'audience': m.get('audience_type'), 'price': m.get('pricing'),
                'deadline': m.get('deadline'),
                'stage': ', '.join(stages) if stages else None,
                'speaker': m.get('speaker'), 'attend': m.get('attend_verdict'),
                'why': _truncate(m.get('why'), 220), 'url': m.get('url'),
            })
    # Drop empty-name rows, cap size.
    out = [e for e in out if (e.get('name') or '').strip()][:MAX_EVENTS_CONTEXT]
    return out


_SYSTEM = (
    "You are the ArcticBlue Event Tracker assistant. ArcticBlue is an applied-AI "
    "company that wants speaking slots and attendance at events full of BUYERS "
    "(in-house enterprise decision-makers), not vendor-to-vendor sales expos.\n"
    "Answer the user's question using ONLY the EVENTS data provided in the next "
    "message. Today's date is {today}.\n"
    "Return ONLY a JSON object: {{\"answer\": \"<1-3 sentence markdown summary>\", "
    "\"recommended\": [\"<exact event name>\", ...]}}.\n"
    "- 'recommended' is the events that answer the question, MOST RELEVANT FIRST "
    "(max 8). Use each event's EXACT name from the data. Empty list if none fit.\n"
    "- Keep 'answer' short — the events render as cards below it, so don't repeat "
    "their dates/locations; just give the gist or the reasoning.\n"
    "- When ranking what to attend/skip, weigh: buyer-rich audience, who's "
    "flagged Interested, pipeline stage, priority, fit (why), and upcoming date "
    "(ignore past events unless asked). Never invent events not in the data.\n"
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
    "- Joe — HR / human-enablement speaker & author. Events about HR/CHRO, L&D "
    "and learning, talent/workforce, future of work, design thinking, "
    "curiosity, and the human side of AI adoption (AI mindset/literacy). "
    "Audience: CHRO, CLO, people & L&D leaders. US/general; not region-locked.\n"
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


def _ask_openai(question, history, events, user=''):
    messages = [{'role': 'system',
                 'content': _SYSTEM.format(today=date.today().isoformat())}]
    messages.append({'role': 'system', 'content': _TEAM_CONTEXT})
    user = (user or '').strip()
    if user and user.lower() != 'team':
        messages.append({'role': 'system', 'content': (
            'The person asking is signed in as "%s". When they say "me", "I", '
            '"my", or "us", tailor recommendations to that person\'s coverage '
            'profile from TEAM COVERAGE above; otherwise answer neutrally.' % user)})
    if _COMPANY_CONTEXT:
        messages.append({'role': 'system',
                         'content': 'ARCTICBLUE CONTEXT:\n' + _COMPANY_CONTEXT})
    messages.append({'role': 'system',
                     'content': 'EVENTS (JSON):\n' + json.dumps(events, ensure_ascii=False)})
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and h.get('role') in ('user', 'assistant') and h.get('content'):
            messages.append({'role': h['role'], 'content': str(h['content'])[:2000]})
    messages.append({'role': 'user', 'content': str(question)[:1000]})
    st, data = _http_json(
        'POST', OPENAI_BASE + '/chat/completions',
        headers={'Authorization': 'Bearer ' + OPENAI_API_KEY},
        body={'model': OPENAI_MODEL, 'messages': messages,
              'temperature': 0.2, 'max_tokens': 700,
              'response_format': {'type': 'json_object'}}, timeout=60)
    if st != 200 or not isinstance(data, dict):
        raise RuntimeError('openai %s: %s' % (st, str(data)[:300]))
    content = data['choices'][0]['message']['content']
    try:
        parsed = json.loads(content)
        return (str(parsed.get('answer', '') or ''),
                [str(n) for n in (parsed.get('recommended') or []) if n])
    except (json.JSONDecodeError, TypeError):
        return content, []


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
            answer, names = _ask_openai(question, body.get('history'), events, body.get('user'))
        except Exception as e:  # noqa: BLE001
            return _send(self, 502, {'error': 'assistant failed: %s' % str(e)[:300]})
        cards = _match_cards(names, events)
        return _send(self, 200, {'answer': answer, 'cards': cards,
                                 'model': OPENAI_MODEL,
                                 'events_considered': len(events)})
