"""POST /api/mcp — a Remote MCP server the Dust agent calls IN-CHAT.

WHY this exists:
  The Dust "ArcticBlueEventSpeaking" agent finds new speaking events when YOU
  run it in the chatbot. We want those events pushed into the tracker WITHOUT
  spending Dust *API* tokens (no outside automation calling the Dust API) and
  WITHOUT extra agent runs. The clean way: give the agent a TOOL it invokes
  during your normal in-chat run. Dust supports "Remote MCP Server" tools, so
  this endpoint speaks MCP (Model Context Protocol) over HTTP and exposes one
  tool — `add_events` — that forwards events into the existing /api/events
  ingest endpoint (which runs the OpenAI worthiness gate + inserts to Supabase).

  Flow:  you run the Dust chatbot  ->  agent finds events  ->  agent calls the
  `add_events` MCP tool  ->  this server POSTs them to /api/events  ->  gate
  filters  ->  Supabase manual_events  ->  they appear in the "For Angela" tab.
  All on IN-CHAT tokens. No GitHub Action, no Dust API key.

TRANSPORT:
  MCP "Streamable HTTP". Dust POSTs JSON-RPC 2.0 messages here. We answer
  requests with a single application/json JSON-RPC response and answer
  notifications with 202 (no body). Stateless — fine for serverless. A GET
  returns 405 (we offer no server-initiated SSE stream), which compliant MCP
  clients tolerate.

AUTH:
  Dust sends  Authorization: Bearer <token>  on every call. We compare it to
  MCP_BEARER_TOKEN. To minimize setup, if MCP_BEARER_TOKEN is unset we fall
  back to EVENTS_INGEST_SECRET (already configured), so you can paste that one
  value into Dust and set zero new Vercel env vars.

METHODS handled: initialize, notifications/initialized, ping, tools/list,
  tools/call (tool: add_events).

ENV:
  MCP_BEARER_TOKEN       (token Dust sends; falls back to EVENTS_INGEST_SECRET)
  EVENTS_INGEST_SECRET   (REQUIRED — door key forwarded to /api/events)
  EVENTS_ENDPOINT        (optional — defaults to https://<this-host>/api/events)
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import hmac
import urllib.request
import urllib.error


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


EVENTS_INGEST_SECRET = _env('EVENTS_INGEST_SECRET')
# Token Dust holds. Default to the ingest secret so the user sets nothing new.
MCP_BEARER_TOKEN     = _env('MCP_BEARER_TOKEN') or EVENTS_INGEST_SECRET
# Where to forward accepted events. Defaults to this same deployment (built
# from the inbound Host header at request time) but can be pinned via env.
EVENTS_ENDPOINT_ENV  = _env('EVENTS_ENDPOINT')

PROTOCOL_VERSION = '2025-06-18'   # echoed/fallback MCP protocol version
SERVER_INFO      = {'name': 'arcticblue-event-tracker', 'version': '1.0.0'}

ADD_EVENTS_TOOL = {
    'name': 'add_events',
    'description': (
        "Add newly-found ArcticBlue speaking events to the tracker. Call this "
        "with the events you found as `new_events`. Each event is screened by "
        "an AI worthiness gate; only accepted, non-duplicate events are saved. "
        "Returns counts of inserted / rejected / skipped(duplicate) / errored "
        "plus per-event detail. Call it once per run with all events at once.\n\n"
        "IMPORTANT — capture HOW TO GET ON STAGE for each event:\n"
        "  - If the event has a public call-for-speakers / 'apply to speak' / "
        "'submit a speaker' / 'suggest a speaker' page, put that URL in "
        "`apply_url`. This must be the APPLY-TO-SPEAK link, NOT a plain "
        "attend/register/tickets link. `url` stays the event homepage.\n"
        "  - If there is no public apply page but you are CONFIDENT who decides "
        "the speakers (e.g. the conference's Head of Content / Program "
        "Director), put their name in `poc_name` and, if known, `poc_email` / "
        "`poc_linkedin`. Only do this when you actually know who it is — never "
        "guess a name.\n"
        "  - If you provide neither, the server will try to find an apply-to- "
        "speak link automatically; that's fine.\n\n"
        "BUYERS OVER SELLERS — the most important signal:\n"
        "  ArcticBlue wants stage time in front of BUYERS (in-house enterprise "
        "leaders / decision-makers who could become clients), NOT rooms full of "
        "other AI vendors, agencies and sales reps selling to each other. For "
        "each event, read who is actually in the room and set `audience` to one "
        "of 'Buyer-rich', 'Mixed', or 'Vendor-heavy', and put a short note on "
        "who attends in `typical_attendees`. High ticket prices and senior "
        "buyer titles are buyer signals; sponsor-driven expos skew vendor-heavy.\n\n"
        "ALSO CAPTURE when you can find them (all optional):\n"
        "  - `pricing`: the cost to ATTEND (e.g. '$2,495 delegate pass'). If "
        "the event prices buyers and vendors differently (end-user rate vs "
        "vendor/supplier rate), note BOTH tiers — that split is itself a "
        "strong signal that buyers will be in the room.\n"
        "  - `past_speakers`: 3-8 notable past or announced speakers as "
        "'Title, Company' (e.g. 'CIO, UnitedHealth; CDO, Pfizer'). Senior "
        "titles at well-known end-user companies = buyer-rich signal.\n"
        "  - `meeting_formats`: any built-in way to actually MEET people — "
        "guaranteed / hosted 1:1 meetings, curated roundtables, or an "
        "attendee app where you can book meetings with other attendees "
        "ahead of time (e.g. 'Guaranteed 1:1s; roundtables; Brella app')."
    ),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'new_events': {
                'type': 'array',
                'description': 'The events to add. Each needs at least a name.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'name':       {'type': 'string', 'description': 'Official event name (required).'},
                        'date_str':   {'type': 'string', 'description': "Original date string, e.g. 'September 14-16, 2026'."},
                        'start_date': {'type': 'string', 'description': 'ISO YYYY-MM-DD if known.'},
                        'end_date':   {'type': 'string', 'description': 'ISO YYYY-MM-DD if known.'},
                        'location':   {'type': 'string', 'description': 'City, Country or City, State.'},
                        'region':     {'type': 'string', 'description': 'Americas | Europe | Asia-Pacific | MENA | Global.'},
                        'type':       {'type': 'string', 'description': 'Enterprise | Halo | Research | Industry | Sponsor | Other.'},
                        'priority':   {'type': 'string', 'description': 'High | Medium | Low.'},
                        'why':        {'type': 'string', 'description': 'One sentence on why it fits ArcticBlue.'},
                        'url':        {'type': 'string', 'description': 'Verified event HOMEPAGE URL, else omit.'},
                        'audience':   {'type': 'string', 'description': "Your read of who is in the room: 'Buyer-rich' (in-house enterprise buyers / decision-makers), 'Mixed', or 'Vendor-heavy' (mostly other vendors/agencies/sales reps selling to each other)."},
                        'typical_attendees': {'type': 'string', 'description': 'Short note on who attends and their seniority/role mix, e.g. "Fortune 500 CIOs & Heads of Data".'},
                        'pricing':    {'type': 'string', 'description': "Cost to ATTEND (delegate/ticket price), e.g. '$2,495 delegate pass' or 'Free'. If buyers and vendors pay different rates, note both tiers. Omit if unknown."},
                        'past_speakers': {'type': 'string', 'description': "Notable past or announced speakers as 'Title, Company' pairs, e.g. 'CIO, UnitedHealth; Chief Data Officer, Pfizer'. Omit if unknown."},
                        'meeting_formats': {'type': 'string', 'description': "Built-in meeting mechanisms: guaranteed/hosted 1:1 meetings, roundtables, or an attendee app for pre-booking meetings. Omit if none found."},
                        'apply_url':  {'type': 'string', 'description': "Apply-to-speak / call-for-speakers / 'submit a speaker' page URL. NOT an attend/register/tickets link. Omit if none."},
                        'poc_name':   {'type': 'string', 'description': 'Name of the person who decides speakers — ONLY if you are confident who it is. Else omit.'},
                        'poc_email':  {'type': 'string', 'description': "That decision-maker's email, if known. Else omit."},
                        'poc_linkedin': {'type': 'string', 'description': "That decision-maker's LinkedIn URL, if known. Else omit."},
                    },
                    'required': ['name'],
                },
            },
        },
        'required': ['new_events'],
    },
}


def _http_json(method, url, headers=None, body=None, timeout=60):
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


def _events_endpoint(host):
    if EVENTS_ENDPOINT_ENV:
        return EVENTS_ENDPOINT_ENV
    if host:
        return 'https://%s/api/events' % host
    return 'https://arcticblue-event-tracker-deploy.vercel.app/api/events'


def _ingest(new_events, host):
    """Forward events into the existing /api/events gate. Returns a human
    summary string + the raw counts dict (for isError decisions)."""
    if not isinstance(new_events, list) or not new_events:
        return 'No events were provided, so nothing was added.', {'errors': 0}, False

    endpoint = _events_endpoint(host)
    status, data = _http_json('POST', endpoint,
                              headers={'X-API-Key': EVENTS_INGEST_SECRET},
                              body={'new_events': new_events}, timeout=90)

    if status != 200 or not isinstance(data, dict):
        return ('The tracker rejected the batch (HTTP %s): %s'
                % (status, data if isinstance(data, str) else json.dumps(data)[:400])), \
               {'errors': 1}, True

    counts = data.get('counts', {}) if isinstance(data, dict) else {}
    lines = ['Tracker ingest complete: inserted=%s, rejected=%s, skipped(duplicate)=%s, errors=%s.'
             % (counts.get('inserted', 0), counts.get('rejected', 0),
                counts.get('skipped', 0), counts.get('errors', 0))]
    for ev in (data.get('inserted') or []):
        tags = []
        if ev.get('audience_type'):
            tags.append(ev['audience_type'])
        if ev.get('pricing'):
            tags.append(ev['pricing'])
        if ev.get('speaking_route'):
            tags.append(ev['speaking_route'])
        lines.append('  ADDED: %s%s' % (ev.get('name'),
                                        ('  [%s]' % ' | '.join(tags)) if tags else ''))
    for ev in (data.get('rejected') or []):
        lines.append('  REJECTED (not worthy): %s -- %s' % (ev.get('name'), ev.get('reason')))
    for ev in (data.get('skipped') or []):
        lines.append('  SKIPPED (already tracked): %s' % ev.get('name'))
    for ev in (data.get('errors') or []):
        lines.append('  ERROR: %s -- %s' % (ev.get('name'), ev.get('reason')))
    gate = data.get('gate') or {}
    lines.append('Worthiness gate: enabled=%s model=%s.'
                 % (gate.get('enabled'), gate.get('model')))
    is_error = bool(counts.get('errors'))
    return '\n'.join(lines), counts, is_error


# ── JSON-RPC dispatch ────────────────────────────────────────────────────
def _result(msg_id, result):
    return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}


def _error(msg_id, code, message):
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}


def _dispatch(msg, host):
    """Handle ONE JSON-RPC message. Returns a response dict for requests, or
    None for notifications (no id)."""
    if not isinstance(msg, dict):
        return _error(None, -32600, 'invalid request')
    method = msg.get('method')
    msg_id = msg.get('id')
    params = msg.get('params') or {}
    is_request = 'id' in msg and msg_id is not None

    # Notifications (no id) get no response.
    if not is_request:
        return None

    if method == 'initialize':
        client_ver = params.get('protocolVersion') or PROTOCOL_VERSION
        return _result(msg_id, {
            'protocolVersion': client_ver,
            'capabilities':    {'tools': {'listChanged': False}},
            'serverInfo':      SERVER_INFO,
        })

    if method == 'ping':
        return _result(msg_id, {})

    if method == 'tools/list':
        return _result(msg_id, {'tools': [ADD_EVENTS_TOOL]})

    if method == 'tools/call':
        name = params.get('name')
        args = params.get('arguments') or {}
        if name != 'add_events':
            return _error(msg_id, -32602, 'unknown tool: %s' % name)
        try:
            summary, _counts, is_error = _ingest(args.get('new_events'), host)
        except Exception as e:  # never crash the protocol on a tool fault
            summary, is_error = 'add_events failed: %s' % e, True
        return _result(msg_id, {
            'content': [{'type': 'text', 'text': summary}],
            'isError': is_error,
        })

    return _error(msg_id, -32601, 'method not found: %s' % method)


# ── HTTP layer ───────────────────────────────────────────────────────────
def _bearer_ok(handler):
    if not MCP_BEARER_TOKEN:
        return False
    ah = handler.headers.get('Authorization', '') or ''
    if not ah.lower().startswith('bearer '):
        return False
    return hmac.compare_digest(ah[7:].strip(), MCP_BEARER_TOKEN)


def _send(handler, status, payload, ctype='application/json', extra_headers=None):
    body = b''
    if payload is not None:
        body = (payload if isinstance(payload, (bytes, bytearray))
                else json.dumps(payload).encode('utf-8'))
    handler.send_response(status)
    if payload is not None:
        handler.send_header('Content-Type', ctype)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, Mcp-Session-Id, MCP-Protocol-Version')
    handler.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
    for k, v in (extra_headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    if body:
        handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, None)

    def do_GET(self):
        # No server-initiated SSE stream offered at this endpoint.
        _send(self, 405, {'error': 'method not allowed; POST JSON-RPC to this endpoint'},
              extra_headers={'Allow': 'POST, OPTIONS'})

    def do_POST(self):
        try:
            self._handle()
        except Exception as e:
            import traceback
            _send(self, 500, _error(None, -32603, 'internal error: %s' % e))
            try:
                # best-effort log to function output
                print(traceback.format_exc()[-1500:], flush=True)
            except Exception:
                pass

    def _handle(self):
        if not EVENTS_INGEST_SECRET:
            return _send(self, 500, _error(None, -32603,
                         'server not configured: EVENTS_INGEST_SECRET missing'))
        if not _bearer_ok(self):
            return _send(self, 401, _error(None, -32001, 'unauthorized: bad or missing Bearer token'),
                         extra_headers={'WWW-Authenticate': 'Bearer'})

        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw    = self.rfile.read(length).decode('utf-8') if length else ''
            msg    = json.loads(raw) if raw else None
        except (ValueError, json.JSONDecodeError):
            return _send(self, 200, _error(None, -32700, 'parse error'))

        host = self.headers.get('Host', '')

        # Batch (array) or single message.
        if isinstance(msg, list):
            responses = []
            for one in msg:
                r = _dispatch(one, host)
                if r is not None:
                    responses.append(r)
            if not responses:
                return _send(self, 202, None)        # all notifications
            return _send(self, 200, responses)

        if isinstance(msg, dict):
            r = _dispatch(msg, host)
            if r is None:
                return _send(self, 202, None)         # a notification
            return _send(self, 200, r)

        return _send(self, 200, _error(None, -32600, 'invalid request'))
