#!/usr/bin/env python3
"""scripts/dust_feed.py — scheduled auto-feed: Dust agent → /api/events.

WHY this exists:
  /api/events is the INBOUND ingest endpoint (it inserts new speaking events
  into Supabase manual_events, gated by the OpenAI worthiness judge). Something
  has to CALL the Dust "ArcticBlueEventSpeaking" agent on a schedule and hand
  its freshly-found events to that endpoint. This script is that something.

  It runs from a GitHub Action (.github/workflows/dust-feed.yml) ~twice a week.
  No browser, no Supabase login: it talks to the Dust API directly, pulls the
  agent's `{"new_events":[...]}` JSON block out of the reply, and POSTs it to
  /api/events with the shared X-API-Key door secret. The endpoint's OpenAI gate
  then decides which of those events are actually worth keeping.

  Pure standard library (urllib / json / re) so the Action needs no pip install
  — exactly like api/events.py and api/search.py.

ENV (all from GitHub Actions secrets, except the ones with defaults):
  DUST_API_KEY          (REQUIRED) Bearer key for the Dust workspace.
  EVENTS_INGEST_SECRET  (REQUIRED) shared door secret; sent as X-API-Key.
  EVENTS_ENDPOINT       (default https://arcticblue-event-tracker-deploy.vercel.app/api/events)
  DUST_WORKSPACE_ID     (default G5QCSmfJhK)
  DUST_AGENT_ID         (default Dir04hvKfi)
  DUST_DOMAIN           (default https://dust.tt)
  DUST_FEED_COUNT       (default 12) how many events to ask the agent for.
  DUST_FEED_PROMPT      (optional) override the trigger message entirely.

EXIT CODES:
  0  ran end-to-end (events may be 0 — that is fine, the agent found nothing new)
  1  hard failure (missing secret, Dust call failed, endpoint rejected the batch)

NOTE on the Dust agent's side effects:
  The configured agent may also build a .docx and email Angela via its own
  Gmail tool. Those run inside Dust regardless of how it is triggered; this
  script only reads the final JSON block from the reply. If you do NOT want the
  email/doc side effects on the scheduled run, trim those steps in the agent's
  Dust instructions — this script does not control them.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


DUST_API_KEY    = _env('DUST_API_KEY')
DUST_WORKSPACE  = _env('DUST_WORKSPACE_ID', 'G5QCSmfJhK')
DUST_AGENT      = _env('DUST_AGENT_ID', 'Dir04hvKfi')
DUST_DOMAIN     = _env('DUST_DOMAIN', 'https://dust.tt').rstrip('/')

EVENTS_ENDPOINT = _env('EVENTS_ENDPOINT',
                       'https://arcticblue-event-tracker-deploy.vercel.app/api/events')
INGEST_SECRET   = _env('EVENTS_INGEST_SECRET')

FEED_COUNT      = _env('DUST_FEED_COUNT', '12')
CALLER_EMAIL    = _env('DUST_FEED_EMAIL', 'dust-feed@arcticblue.ai')

MAX_POLL_SECONDS = 240          # the agent can be slow when it also drafts docs
POLL_INTERVAL    = 4.0


def _log(msg):
    print(msg, flush=True)


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


# ── Dust agent call (mirrors api/search.py) ──────────────────────────────
def _dust_start(prompt):
    url = '%s/api/v1/w/%s/assistant/conversations' % (DUST_DOMAIN, DUST_WORKSPACE)
    body = {
        'title':      'Scheduled event feed',
        'visibility': 'unlisted',
        'message': {
            'content':  prompt,
            'mentions': [{'configurationId': DUST_AGENT}],
            'context': {
                'username':          'event-tracker-feed',
                'timezone':          'America/New_York',
                'fullName':          'Event Tracker Feed',
                'email':             CALLER_EMAIL,
                'profilePictureUrl': '',
                'origin':            'api',
            },
        },
        'blocking': False,
    }
    status, payload = _http_json('POST', url, body=body, headers={
        'Authorization': 'Bearer ' + DUST_API_KEY,
    }, timeout=30)
    if status not in (200, 201) or not isinstance(payload, dict):
        raise RuntimeError('dust create_conversation returned %s: %s' % (status, payload))
    conv = payload.get('conversation') or payload
    cid  = conv.get('sId') or conv.get('id')
    if not cid:
        raise RuntimeError('no conversation id in dust response: %s' % payload)
    return cid


def _dust_poll(conv_id):
    url = '%s/api/v1/w/%s/assistant/conversations/%s' % (DUST_DOMAIN, DUST_WORKSPACE, conv_id)
    deadline = time.time() + MAX_POLL_SECONDS
    last = None
    while time.time() < deadline:
        status, payload = _http_json('GET', url, headers={
            'Authorization': 'Bearer ' + DUST_API_KEY,
        }, timeout=20)
        if status != 200 or not isinstance(payload, dict):
            time.sleep(POLL_INTERVAL)
            continue
        convo = payload.get('conversation') or payload
        latest = None
        for group in reversed(convo.get('content', []) or []):
            for msg in reversed(group):
                if msg.get('type') == 'agent_message':
                    latest = msg
                    break
            if latest:
                break
        if latest is not None:
            st = latest.get('status')
            last = latest
            if st in ('succeeded', 'failed', 'cancelled'):
                return latest
        time.sleep(POLL_INTERVAL)
    if last is not None:
        return last
    raise TimeoutError('dust agent did not finish in %ss' % MAX_POLL_SECONDS)


def _agent_text(reply):
    if not isinstance(reply, dict):
        return ''
    c = reply.get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return ''.join(str(x) for x in c)
    return reply.get('rawText') or reply.get('text') or ''


# ── Extract the agent's {"new_events":[...]} block ───────────────────────
def _coerce_new_events(obj):
    """Pull a list of event dicts out of whatever JSON we parsed: a
    {"new_events":[...]} / {"events":[...]} object, or a bare [...] array."""
    if isinstance(obj, dict):
        for key in ('new_events', 'events'):
            v = obj.get(key)
            if isinstance(v, list):
                return v
        return None
    if isinstance(obj, list):
        return obj
    return None


def _extract_new_events(text):
    """Find the agent's events array. Tries, in order:
      1. a fenced ```json {...}``` / ```json [...]``` block,
      2. the first balanced {...} object containing "new_events",
      3. a bare [...] array spanning first '[' to last ']'.
    Returns a list (possibly empty) of event dicts, or None if nothing parsed."""
    if not text:
        return None

    # 1. fenced code block (object or array)
    for m in re.finditer(r'```(?:json)?\s*([\[{][\s\S]*?[\]}])\s*```', text):
        try:
            got = _coerce_new_events(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
        if got is not None:
            return got

    # 2. first balanced object that mentions new_events / events
    idx = 0
    while True:
        start = text.find('{', idx)
        if start < 0:
            break
        depth = 0
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            break
        chunk = text[start:end + 1]
        if '"new_events"' in chunk or '"events"' in chunk:
            try:
                got = _coerce_new_events(json.loads(chunk))
                if got is not None:
                    return got
            except json.JSONDecodeError:
                pass
        idx = end + 1

    # 3. greedy bare array
    s = text.find('[')
    e = text.rfind(']')
    if 0 <= s < e:
        try:
            got = _coerce_new_events(json.loads(text[s:e + 1]))
            if got is not None:
                return got
        except json.JSONDecodeError:
            pass

    return None


FEED_PROMPT = """Run your standard event-sourcing routine for ArcticBlue.

Find up to {count} upcoming, real, in-person AI / enterprise-technology events
(conferences, summits, panels) where ArcticBlue could put a speaker on stage.
First de-duplicate against the events already in the tracker, then return ONLY
the genuinely NEW ones.

Return your result as a single fenced ```json block containing exactly this
shape and nothing else after it:

```json
{{
  "new_events": [
    {{
      "name": "<official event name>",
      "date_str": "<original date string, e.g. 'September 14-16, 2026'>",
      "start_date": "<YYYY-MM-DD or null>",
      "end_date": "<YYYY-MM-DD or null>",
      "location": "<City, Country or City, State>",
      "region": "<Americas | Europe | Asia-Pacific | MENA | Global>",
      "type": "<Enterprise | Halo | Research | Industry | Sponsor | Other>",
      "priority": "<High | Medium | Low>",
      "why": "<one sentence on why it fits ArcticBlue>",
      "url": "<verified homepage URL, else null>"
    }}
  ]
}}
```

CRITICAL: do not invent URLs — use null if you cannot verify one. If there are
no genuinely new events, return {{"new_events": []}}.
"""


def _build_prompt():
    if _env('DUST_FEED_PROMPT'):
        return _env('DUST_FEED_PROMPT')
    try:
        count = max(1, min(int(FEED_COUNT or 12), 25))
    except (TypeError, ValueError):
        count = 12
    return FEED_PROMPT.format(count=count)


def main():
    missing = [k for k, v in (('DUST_API_KEY', DUST_API_KEY),
                              ('EVENTS_INGEST_SECRET', INGEST_SECRET)) if not v]
    if missing:
        _log('FATAL: missing required env: %s' % ', '.join(missing))
        return 1

    _log('Dust feed → %s' % EVENTS_ENDPOINT)
    _log('  workspace=%s agent=%s' % (DUST_WORKSPACE, DUST_AGENT))

    # 1. Ask the Dust agent.
    prompt = _build_prompt()
    try:
        conv_id = _dust_start(prompt)
        _log('  started conversation %s; polling up to %ss…' % (conv_id, MAX_POLL_SECONDS))
        reply = _dust_poll(conv_id)
    except TimeoutError as e:
        _log('FATAL: %s' % e)
        return 1
    except Exception as e:
        _log('FATAL: dust call failed: %s' % e)
        return 1

    reply_status = reply.get('status') if isinstance(reply, dict) else None
    text = _agent_text(reply)
    _log('  agent status=%s, reply chars=%d' % (reply_status, len(text)))

    events = _extract_new_events(text)
    if events is None:
        _log('FATAL: could not find a new_events JSON block in the agent reply.')
        _log('  --- first 1200 chars of reply ---')
        _log(text[:1200])
        return 1

    # Keep only dict items with a name.
    clean = [e for e in events if isinstance(e, dict) and (e.get('name') or '').strip()]
    _log('  agent returned %d event(s) (%d usable)' % (len(events), len(clean)))

    if not clean:
        _log('Done: agent found no new events. Nothing to post.')
        return 0

    # 2. POST to /api/events. The endpoint's OpenAI gate filters from here.
    status, data = _http_json('POST', EVENTS_ENDPOINT,
                              headers={'X-API-Key': INGEST_SECRET},
                              body={'new_events': clean}, timeout=60)

    if status != 200 or not isinstance(data, dict):
        _log('FATAL: /api/events returned %s: %s' % (status, data))
        return 1

    counts = data.get('counts', {}) if isinstance(data, dict) else {}
    _log('Ingest result: inserted=%s rejected=%s skipped=%s errors=%s' % (
        counts.get('inserted', '?'), counts.get('rejected', '?'),
        counts.get('skipped', '?'), counts.get('errors', '?')))

    for ev in (data.get('inserted') or []):
        _log('  + inserted: %s (id %s)' % (ev.get('name'), ev.get('id')))
    for ev in (data.get('rejected') or []):
        _log('  - rejected: %s — %s (score %s)' % (
            ev.get('name'), ev.get('reason'), ev.get('score')))
    for ev in (data.get('skipped') or []):
        _log('  = skipped:  %s — %s' % (ev.get('name'), ev.get('reason')))
    for ev in (data.get('errors') or []):
        _log('  ! error:    %s — %s' % (ev.get('name'), ev.get('reason')))

    gate = data.get('gate') or {}
    _log('Gate: enabled=%s model=%s' % (gate.get('enabled'), gate.get('model')))

    # A failed insert is the only thing worth turning the run red for.
    if counts.get('errors'):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
