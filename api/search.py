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


def _same_origin(handler):
    """True if the request came from our own deployment (Origin or Referer
    host == the request Host). Lightweight abuse guard for the open app."""
    host = (handler.headers.get('Host', '') or '').strip().lower()
    if not host:
        return False
    for h in ('Origin', 'Referer'):
        v = (handler.headers.get(h, '') or '').strip().lower()
        if v:
            try:
                from urllib.parse import urlsplit
                if urlsplit(v).netloc == host:
                    return True
            except ValueError:
                pass
    return False


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

ALREADY TRACKED — do NOT return any of these, nor trivial rewordings of
them. (A different city/region edition of a series IS welcome — e.g. a
Singapore edition when only the London one is tracked.) Use this list as a
TASTE PROFILE: suggest events of similar caliber and audience that are
missing from it:
{tracked_str}

{recurring_block}Criteria
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


def _build_prompt(count, types, quarters, regions, tracked, recurring=None):
    def fmt(arr):
        if not arr: return 'no preference'
        return ', '.join(arr)
    tracked_str = '; '.join(tracked) if tracked else '(list unavailable)'
    recurring = [str(x).strip() for x in (recurring or []) if str(x).strip()]
    if recurring:
        recurring_block = (
            "RETURNING EVENTS (secondary, optional): ArcticBlue attended these in a "
            "past year and they may recur. IF a later edition falls WITHIN the "
            "quarters/regions below AND is NOT already in the ALREADY TRACKED list, "
            "you may include it. But this is a bonus — your PRIMARY job is to fill "
            "the results with NEW events matching the Criteria that are not already "
            "tracked. Do NOT spend result slots on already-tracked or past editions:\n"
            + '; '.join(recurring[:20]) + "\n\n"
        )
    else:
        recurring_block = ''
    return SEARCH_PROMPT.format(
        count           = max(1, min(int(count or 10), 25)),
        types_str       = fmt(types),
        quarters_str    = fmt(quarters),
        regions_str     = fmt(regions),
        tracked_str     = tracked_str,
        recurring_block = recurring_block,
    )


# ── Tracker awareness ────────────────────────────────────────────────
# The search must NOT re-suggest events already tracked, and should use the
# existing list as a taste profile. Names come from the public catalog
# (events.json on this same deployment) + manual_events (public read via RLS).
_DEDUPE_STOP = {
    'the', 'a', 'an', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'at', 'by', 'with',
    'summit', 'summits', 'conference', 'conferences', 'expo', 'forum', 'event', 'events',
}
_YEAR_RE = re.compile(r'^(?:19|20)\d{2}$')


def _fingerprint(name):
    """Order-independent dedupe key (mirrors api/events.py). '' = no key."""
    s = re.sub(r'[^a-z0-9]+', ' ', (name or '').lower())
    toks = [t for t in s.split() if t not in _DEDUPE_STOP and not _YEAR_RE.match(t)]
    return ' '.join(sorted(set(toks)))


def _tracked_names(host):
    """Every event name currently in the tracker (catalog + manual). Failures
    just shrink the list — the client-side dedupe badge is the last resort."""
    names = []
    if host:
        status, data = _http_json('GET', f'https://{host}/events.json', timeout=12)
        if status == 200 and isinstance(data, dict):
            for e in (data.get('events') or []):
                n = (e.get('name') or '').strip()
                if n:
                    names.append(n)
    status, rows = _http_json(
        'GET', f'{SUPABASE_URL}/rest/v1/manual_events?select=name',
        headers={'apikey': SUPABASE_PUBLISHABLE,
                 'Authorization': f'Bearer {SUPABASE_PUBLISHABLE}'},
        timeout=12)
    if status == 200 and isinstance(rows, list):
        for r in rows:
            n = (r.get('name') or '').strip()
            if n:
                names.append(n)
    return names


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
        # Events ArcticBlue attended/spoke at in the past — find their next-year
        # editions first, then fall back to the criteria above.
        recurring = _list(body.get('recurring'))

        # Auth. The tracker is now open (no login), so a Supabase editor token
        # is OPTIONAL — if present we record who, otherwise we allow the call
        # but require it to originate from our own site (Origin/Referer match)
        # to curb random cross-site abuse of this metered endpoint.
        auth_header = self.headers.get('Authorization', '')
        token = auth_header[7:].strip() if auth_header.lower().startswith('bearer ') else ''
        caller_email = 'anonymous'
        if token:
            ok, who = _verify_editor(token)
            if ok:
                caller_email = who
        if caller_email == 'anonymous' and not _same_origin(self):
            return _send(self, 403, {'error': 'forbidden: call from the tracker site'})

        tracked = _tracked_names(self.headers.get('Host', ''))
        tracked_fps = {fp for fp in (_fingerprint(n) for n in tracked) if fp}
        tracked_lows = {n.lower() for n in tracked}
        # Over-ask: the model often returns tracked events despite the exclusion
        # list, and the hard filter then thins results. With a very complete
        # tracker most candidates are dupes, so over-ask generously (single API
        # call) to keep the NEW-event yield near count.
        ask = min(max(count * 4, 15), 25)
        prompt = _build_prompt(ask, types, quarters, regions, tracked, recurring)
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
        # patterns (placeholders, .example, etc.), and HARD-FILTER anything
        # already tracked (exact name or reworded fingerprint match) so the
        # model ignoring the exclusion list can't produce repeats.
        cleaned = []
        dupes_filtered = 0
        for ev in events:
            if not isinstance(ev, dict): continue
            nm = (ev.get('name') or '').strip()
            fp = _fingerprint(nm)
            if nm.lower() in tracked_lows or (fp and fp in tracked_fps):
                dupes_filtered += 1
                continue
            url = ev.get('url')
            if isinstance(url, str):
                u = url.strip()
                if (not u or u.lower() in ('null', 'none', 'n/a', 'tbd') or
                        '.example' in u.lower() or 'placeholder' in u.lower()):
                    ev['url'] = None
                else:
                    ev['url'] = u
            cleaned.append(ev)

        cleaned = cleaned[:count]  # trim the over-ask back to what was requested
        return _send(self, 200, {
            'events':   cleaned,
            'count':    len(cleaned),
            'dupes_filtered': dupes_filtered,
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
