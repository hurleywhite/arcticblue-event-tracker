"""POST /api/vet — proxy a candidate event through the ArcticBlue Dust agent.

Why this exists:
  Dust API keys can't be embedded in the public HTML (anyone could drain
  the quota). This function holds DUST_API_KEY as a Vercel env var, verifies
  the caller is an allow-listed editor via Supabase Auth, then asks the
  ArcticBlueEventSpeaking agent to extract + rate the candidate. The
  response is returned for the frontend to pre-fill the + Add Event form.

Auth:
  Caller passes their Supabase access_token as `Authorization: Bearer …`.
  We hit the Supabase /auth/v1/user endpoint with that token. If the email
  isn't in `allowed_editors`, we 403.

Note on cold-start + timeouts:
  Dust conversations are async (we poll). Most replies arrive in 5–40s.
  Vercel Pro maxDuration is 300s; we cap our poll at 90s so a slow agent
  surfaces as a clean 504 instead of a hung connection. See vercel.json.

Input  (POST JSON): { "text": "<candidate event text>" }
Output (200 JSON):  { "fields": {name, date_str, location, …}, "raw": "<agent reply>" }
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import re


# All env reads are strip()'d because piping via `echo` (e.g. `echo "..." |
# vercel env add KEY production`) bakes in a trailing newline that breaks
# urllib (InvalidURL: control character).
def _env(key, default=''):
    return (os.environ.get(key, default) or '').strip()

SUPABASE_URL          = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SUPABASE_PUBLISHABLE  = _env('SUPABASE_PUBLISHABLE_KEY')

DUST_API_KEY     = _env('DUST_API_KEY')
DUST_WORKSPACE   = _env('DUST_WORKSPACE_ID', 'G5QCSmfJhK')
DUST_AGENT       = _env('DUST_AGENT_ID', 'Dir04hvKfi')
DUST_DOMAIN      = _env('DUST_DOMAIN', 'https://dust.tt').rstrip('/')

MAX_POLL_SECONDS = 90
POLL_INTERVAL    = 3.0


def _http_json(method, url, headers=None, body=None, timeout=20):
    """Tiny urllib JSON helper. Returns (status_code, parsed_body|raw_string)."""
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
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, {'error': f'network: {e}'}


def _verify_editor(access_token):
    """Resolve a Supabase access_token → email → allow-list check.
    Returns (ok, email_or_error_message)."""
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
    # Cross-check against allowed_editors via REST (RLS allows public read)
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
    """Open a Dust conversation that mentions the agent. Returns conv_id."""
    url = f'{DUST_DOMAIN}/api/v1/w/{DUST_WORKSPACE}/assistant/conversations'
    body = {
        'title':      'Event vetting from For Angela',
        'visibility': 'unlisted',
        'message': {
            'content':  prompt,
            'mentions': [{'configurationId': DUST_AGENT}],
            'context': {
                'username':           'event-tracker-vet',
                'timezone':           'America/New_York',
                'fullName':           'Event Tracker Vet',
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
    """Poll until the latest agent_message reaches a terminal status."""
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
        # Return whatever we have; caller will treat as partial
        return last
    raise TimeoutError(f'dust agent did not finish in {MAX_POLL_SECONDS}s')


def _extract_json(text):
    """Pull a JSON object out of the agent's reply. Tries fenced blocks first."""
    if not text:
        return None
    # ```json {...} ```
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # First {...} that contains "name" — greedy match across newlines
    m = re.search(r'\{[\s\S]*?"name"[\s\S]*?\}', text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


VET_PROMPT = """You are evaluating a potential AI event for ArcticBlue (an applied-AI consultancy
that does enterprise + halo events). Given the candidate event text below, do TWO things:

1. Extract the event details into a single JSON object with this exact schema:
   {{
     "name":        "<event name>",
     "date_str":    "<original date string, e.g. 'September 14–16, 2026'>",
     "location":    "<City, Country or City, State>",
     "region":      "<one of: Americas, Europe, Asia-Pacific, MENA, Global>",
     "type":        "<Enterprise | Halo | Research | Industry>",
     "priority":    "<High | Medium | Low>",
     "why":         "<one sentence on why this is or isn't a fit for ArcticBlue>",
     "url":         "<the event's homepage URL if you can verify one, else null>",
     "recommend":   "<yes | maybe | no>",
     "reasoning":   "<one or two sentences explaining the recommendation>"
   }}

2. Return ONLY that JSON object inside a ```json ``` fenced block. No prose before or after.

CRITICAL: do not invent URLs. If you don't have a verified URL for this exact event,
set "url" to null. This is the no-hallucination rule from AGENT-CONTEXT.md.

Candidate event text:
---
{text}
---
"""


def _build_prompt(text):
    safe = (text or '').strip()
    if len(safe) > 8000:
        safe = safe[:8000] + '\n…[truncated]'
    return VET_PROMPT.format(text=safe)


def _agent_text(reply):
    """Pull the agent's final text out of a Dust agent_message payload."""
    if not isinstance(reply, dict):
        return ''
    c = reply.get('content')
    if isinstance(c, str):
        return c
    # Some agent_message shapes nest content
    if isinstance(c, list):
        return ''.join(str(x) for x in c)
    # Fallback: serialize the whole reply
    return reply.get('rawText') or reply.get('text') or ''


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
            self._handle_post()
        except Exception as e:
            import traceback
            _send(self, 500, {
                'error': 'unhandled exception in handler',
                'type':  type(e).__name__,
                'msg':   str(e),
                'trace': traceback.format_exc()[-2000:],
            })

    def _handle_post(self):
        # Config sanity
        if not DUST_API_KEY:
            return _send(self, 500, {'error': 'server not configured: DUST_API_KEY missing'})
        if not SUPABASE_PUBLISHABLE:
            return _send(self, 500, {'error': 'server not configured: SUPABASE_PUBLISHABLE_KEY missing'})

        # Read body
        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw    = self.rfile.read(length).decode('utf-8') if length else '{}'
            body   = json.loads(raw or '{}')
        except (ValueError, json.JSONDecodeError):
            return _send(self, 400, {'error': 'invalid JSON body'})

        text = (body.get('text') or '').strip()
        if len(text) < 10:
            return _send(self, 400, {'error': 'need at least 10 chars of candidate text'})

        # Auth — must be an allow-listed editor
        auth_header = self.headers.get('Authorization', '')
        token = auth_header[7:].strip() if auth_header.lower().startswith('bearer ') else ''
        ok, who = _verify_editor(token)
        if not ok:
            return _send(self, 403, {'error': f'forbidden: {who}'})
        caller_email = who

        # Call Dust
        try:
            conv_id = _dust_start(_build_prompt(text), caller_email)
            reply   = _dust_poll(conv_id)
        except TimeoutError as e:
            return _send(self, 504, {'error': f'dust timeout: {e}'})
        except Exception as e:
            return _send(self, 502, {'error': f'dust call failed: {e}'})

        agent_text = _agent_text(reply)
        fields     = _extract_json(agent_text) or {}
        return _send(self, 200, {
            'fields': fields,
            'raw':    agent_text[:8000],     # cap reply size
            'status': reply.get('status'),
            'caller': caller_email,
        })
