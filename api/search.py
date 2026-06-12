"""POST /api/search — find upcoming in-person AI events matching criteria.

ENGINE: Perplexity (sonar, web-grounded) when PERPLEXITY_API_KEY is set —
~1 cheap call and ~10s instead of a metered 30-90s Dust agent run. Falls
back to the legacy ArcticBlueEventSpeaking Dust agent when only
DUST_API_KEY is configured. Either way, added events still pass the
OpenAI worthiness gate + auto-enrichment, so curation does not depend on
the finder.

Why this exists separately from /api/vet:
  /api/vet takes a single candidate (URL or pasted text) and returns one
  structured object. /api/search takes criteria (count + types + quarters)
  and returns an ARRAY of N candidate events. Different prompt template,
  different response shape, same auth + Dust plumbing.

Input  (POST JSON): {
  "count":    <int 1..25, default 10>,
  "types":    ["Enterprise","Halo",...]      # optional
  "quarters": ["Q3 2026","Q4 2026",...]      # optional
  "regions":  ["Americas","Europe",...]      # optional
}

Output (200 JSON): {
  "events": [
    {name, date_str, location, region, type, priority, why, url, recommend, reasoning},
    ...
  ],
  "raw":    "<agent reply truncated>",
  "caller": "...",
  "criteria": <echoed back>
}

Auth: same as /api/vet — caller's Supabase access_token → allowed_editors.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import re


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL          = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SUPABASE_PUBLISHABLE  = _env('SUPABASE_PUBLISHABLE_KEY')

PPLX_API_KEY = _env('PERPLEXITY_API_KEY')
PPLX_MODEL   = _env('PERPLEXITY_MODEL', 'sonar')
PPLX_BASE    = _env('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai').rstrip('/')

DUST_API_KEY     = _env('DUST_API_KEY')
DUST_WORKSPACE   = _env('DUST_WORKSPACE_ID', 'G5QCSmfJhK')
DUST_AGENT       = _env('DUST_AGENT_ID', 'Dir04hvKfi')
DUST_DOMAIN      = _env('DUST_DOMAIN', 'https://dust.tt').rstrip('/')

MAX_POLL_SECONDS = 110
POLL_INTERVAL    = 3.0


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
            try: return r.status, json.loads(raw)
            except json.JSONDecodeError: return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try: return e.code, json.loads(raw)
        except json.JSONDecodeError: return e.code, raw
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {'error': f'network: {e}'}


def _verify_editor(access_token):
    if not access_token:
        return False, 'missing Authorization bearer token'
    status, user = _http_json('GET', f'{SUPABASE_URL}/auth/v1/user', headers={
        'Authorization': f'Bearer {access_token}',
        'apikey':        SUPABASE_PUBLISHABLE,
    })
    if status != 200 or not isinstance(user, dict):
        return False, f'supabase user lookup returned {status}'
    email = (user.get('email') or '').strip().lower()
    if not email:
        return False, 'no email on user record'
    status, rows = _http_json('GET',
        f"{SUPABASE_URL}/rest/v1/allowed_editors?select=email&email=eq.{urllib.parse.quote(email)}",
        headers={
            'apikey':        SUPABASE_PUBLISHABLE,
            'Authorization': f'Bearer {SUPABASE_PUBLISHABLE}',
        })
    if status != 200 or not isinstance(rows, list) or len(rows) == 0:
        return False, f'{email} is not on the editor allow-list'
    return True, email


def _dust_start(prompt, caller_email):
    url = f'{DUST_DOMAIN}/api/v1/w/{DUST_WORKSPACE}/assistant/conversations'
    body = {
        'title':      'Event search from For Angela',
        'visibility': 'unlisted',
        'message': {
            'content':  prompt,
            'mentions': [{'configurationId': DUST_AGENT}],
            'context': {
                'username':           'event-tracker-search',
                'timezone':           'America/New_York',
                'fullName':           'Event Tracker Search',
                'email':              caller_email,
                'profilePictureUrl':  '',
                'origin':             'api',
            },
        },
        'blocking': False,
    }
    status, payload = _http_json('POST', url, body=body, headers={
        'Authorization': f'Bearer {DUST_API_KEY}',
    }, timeout=30)
    if status not in (200, 201) or not isinstance(payload, dict):
        raise RuntimeError(f'dust create_conversation returned {status}: {payload}')
    conv = payload.get('conversation') or payload
    cid  = conv.get('sId') or conv.get('id')
    if not cid:
        raise RuntimeError(f'no conversation id in dust response: {payload}')
    return cid


def _dust_poll(conv_id):
    url = f'{DUST_DOMAIN}/api/v1/w/{DUST_WORKSPACE}/assistant/conversations/{conv_id}'
    deadline = time.time() + MAX_POLL_SECONDS
    last = None
    while time.time() < deadline:
        status, payload = _http_json('GET', url, headers={
            'Authorization': f'Bearer {DUST_API_KEY}',
        }, timeout=20)
        if status != 200 or not isinstance(payload, dict):
            time.sleep(POLL_INTERVAL); continue
        convo = payload.get('conversation') or payload
        latest = None
        for group in reversed(convo.get('content', []) or []):
            for msg in reversed(group):
                if msg.get('type') == 'agent_message':
                    latest = msg; break
            if latest: break
        if latest is not None:
            st = latest.get('status')
            last = latest
            if st in ('succeeded', 'failed', 'cancelled'):
                return latest
        time.sleep(POLL_INTERVAL)
    if last is not None:
        return last
    raise TimeoutError(f'dust agent did not finish in {MAX_POLL_SECONDS}s')


def _agent_text(reply):
    if not isinstance(reply, dict):
        return ''
    c = reply.get('content')
    if isinstance(c, str): return c
    if isinstance(c, list): return ''.join(str(x) for x in c)
    return reply.get('rawText') or reply.get('text') or ''


def _extract_json_array(text):
    """The agent should return a fenced ```json [...] ``` block. Try that
    first; fall back to the first plausible [...] match."""
    if not text:
        return None
    m = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', text)
    if m:
        try: return json.loads(m.group(1))
        except json.JSONDecodeError: pass
    # Greedy first [ to last ]
    s = text.find('[')
    e = text.rfind(']')
    if s >= 0 and e > s:
        try: return json.loads(text[s:e+1])
        except json.JSONDecodeError: pass
    # Maybe the agent returned a single object — wrap it
    m2 = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if m2:
        try: return [json.loads(m2.group(1))]
        except json.JSONDecodeError: pass
    return None


SEARCH_PROMPT = """You're sourcing in-person AI events for ArcticBlue (applied-AI
consultancy that does enterprise + halo events). Find {count} upcoming
events that match the criteria below. Prefer well-known, reputable
events with verified websites, and STRONGLY prefer buyer-rich audiences
(in-house enterprise decision-makers) over vendor-to-vendor sales expos.

Criteria
- Quarters to include:  {quarters_str}
- Event types to include: {types_str}
- Regions to include:   {regions_str}

For each event return a JSON object with this exact schema:
{{
  "name":      "<official event name>",
  "date_str":  "<original date string, e.g. 'September 14–16, 2026'>",
  "location":  "<City, Country or City, State>",
  "region":    "<one of: Americas, Europe, Asia-Pacific, MENA, Global>",
  "type":      "<Enterprise | Halo | Research | Industry | Sponsor | Other>",
  "priority":  "<High | Medium | Low>",
  "why":       "<one sentence on why this is or isn't a fit for ArcticBlue>",
  "url":       "<the event's homepage URL if verified, else null>",
  "audience":  "<Buyer-rich | Mixed | Vendor-heavy — are attendees mostly in-house enterprise buyers, or vendors selling?>",
  "pricing":   "<cost to attend if known, else null>",
  "recommend": "<yes | maybe | no>",
  "reasoning": "<one or two sentences explaining the recommendation>"
}}

Return ONLY a JSON ARRAY of {count} such objects inside a single ```json ``` fenced block. No prose before or after.

CRITICAL: do not invent URLs. If you don't have a verified URL for an event, set "url" to null.
"""


def _build_prompt(count, types, quarters, regions):
    def fmt(arr):
        if not arr: return 'no preference'
        return ', '.join(arr)
    return SEARCH_PROMPT.format(
        count        = max(1, min(int(count or 10), 25)),
        types_str    = fmt(types),
        quarters_str = fmt(quarters),
        regions_str  = fmt(regions),
    )


def _perplexity_search(prompt):
    """One web-grounded sonar call; returns the reply text. Raises on error."""
    status, data = _http_json(
        'POST', f'{PPLX_BASE}/chat/completions',
        headers={'Authorization': f'Bearer {PPLX_API_KEY}'},
        body={'model': PPLX_MODEL,
              'messages': [
                  {'role': 'system', 'content':
                   'You research business conferences using web search. '
                   'Follow the output format instructions exactly.'},
                  {'role': 'user', 'content': prompt}],
              'temperature': 0.2, 'max_tokens': 2400},
        timeout=70)
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(f'perplexity returned {status}: {str(data)[:300]}')
    return data['choices'][0]['message']['content']


def _send(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
    handler.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, {})

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
        if not (PPLX_API_KEY or DUST_API_KEY):
            return _send(self, 500, {'error': 'server not configured: need PERPLEXITY_API_KEY (preferred) or DUST_API_KEY'})
        if not SUPABASE_PUBLISHABLE:
            return _send(self, 500, {'error': 'server not configured: SUPABASE_PUBLISHABLE_KEY missing'})

        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw    = self.rfile.read(length).decode('utf-8') if length else '{}'
            body   = json.loads(raw or '{}')
        except (ValueError, json.JSONDecodeError):
            return _send(self, 400, {'error': 'invalid JSON body'})

        try:
            count = int(body.get('count') or 10)
        except (ValueError, TypeError):
            count = 10
        count = max(1, min(count, 25))

        def _list(v):
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str) and v.strip():
                return [s.strip() for s in v.split(',') if s.strip()]
            return []

        types    = _list(body.get('types'))
        quarters = _list(body.get('quarters'))
        regions  = _list(body.get('regions'))

        # Auth
        auth_header = self.headers.get('Authorization', '')
        token = auth_header[7:].strip() if auth_header.lower().startswith('bearer ') else ''
        ok, who = _verify_editor(token)
        if not ok:
            return _send(self, 403, {'error': f'forbidden: {who}'})
        caller_email = who

        prompt = _build_prompt(count, types, quarters, regions)
        engine = 'perplexity' if PPLX_API_KEY else 'dust'
        if engine == 'perplexity':
            try:
                agent_text = _perplexity_search(prompt)
            except Exception as e:
                return _send(self, 502, {'error': f'perplexity call failed: {e}'})
            reply = {'status': 'succeeded'}
        else:
            try:
                conv_id = _dust_start(prompt, caller_email)
                reply   = _dust_poll(conv_id)
            except TimeoutError as e:
                return _send(self, 504, {'error': f'dust timeout: {e}'})
            except Exception as e:
                err_str = str(e)
                if 'rate_limit' in err_str.lower():
                    return _send(self, 429, {'error': 'Dust rate-limited. Try again in 1-2 minutes.'})
                return _send(self, 502, {'error': f'dust call failed: {e}'})
            agent_text = _agent_text(reply)
        events     = _extract_json_array(agent_text) or []

        # Sanitize each event — drop URLs that are clearly hallucinated
        # patterns (placeholders, .example, etc.) just in case.
        cleaned = []
        for ev in events:
            if not isinstance(ev, dict): continue
            url = ev.get('url')
            if isinstance(url, str):
                u = url.strip()
                if (not u or u.lower() in ('null', 'none', 'n/a', 'tbd') or
                        '.example' in u.lower() or 'placeholder' in u.lower()):
                    ev['url'] = None
                else:
                    ev['url'] = u
            cleaned.append(ev)

        return _send(self, 200, {
            'events':   cleaned,
            'count':    len(cleaned),
            'raw':      agent_text[:8000],
            'status':   reply.get('status'),
            'engine':   engine,
            'caller':   caller_email,
            'criteria': {
                'count':    count,
                'types':    types,
                'quarters': quarters,
                'regions':  regions,
            },
        })
