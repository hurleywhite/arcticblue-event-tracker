"""GET/POST /api/opportunities — active event opportunity pipeline.

GET is same-origin and public-read, but sensitive contact/travel details are
returned only when the caller supplies an editor Supabase access token.
POST requires an editor token and supports narrow workflow mutations.

This endpoint intentionally sits on top of the new opportunity tables while
joining live legacy manual_events workflow fields. The legacy row remains the
source of truth for submissions/speaker/notes until the old tracker is retired.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SUPABASE_PUBLISHABLE = _env('SUPABASE_PUBLISHABLE_KEY')
SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')


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
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return 0, {'error': 'network: %s' % e}


def _svc_headers(prefer=None):
    h = {
        'apikey': SERVICE_ROLE,
        'Authorization': 'Bearer ' + SERVICE_ROLE,
        'Content-Type': 'application/json',
    }
    if prefer:
        h['Prefer'] = prefer
    return h


def _same_origin(handler):
    host = (handler.headers.get('Host', '') or '').strip().lower()
    if not host:
        return False
    for key in ('Origin', 'Referer'):
        value = (handler.headers.get(key, '') or '').strip().lower()
        if value:
            try:
                if urllib.parse.urlsplit(value).netloc == host:
                    return True
            except ValueError:
                pass
    return False


def _access_token(handler):
    auth = (handler.headers.get('Authorization', '') or '').strip()
    if auth[:7].lower() == 'bearer ':
        token = auth[7:].strip()
        if token and token != SUPABASE_PUBLISHABLE:
            return token
    return ''


def _editor_email(handler):
    token = _access_token(handler)
    if not token or not (SUPABASE_PUBLISHABLE and SERVICE_ROLE):
        return ''
    st, user = _http_json('GET', SUPABASE_URL + '/auth/v1/user', headers={
        'apikey': SUPABASE_PUBLISHABLE,
        'Authorization': 'Bearer ' + token,
    })
    if st != 200 or not isinstance(user, dict):
        return ''
    email = (user.get('email') or '').strip().lower()
    if not email:
        return ''
    st, rows = _http_json(
        'GET',
        SUPABASE_URL + '/rest/v1/allowed_editors?select=email&email=eq.' + urllib.parse.quote(email),
        headers=_svc_headers(),
    )
    if st == 200 and isinstance(rows, list) and rows:
        return email
    return ''


def _select(table, query):
    st, rows = _http_json('GET', SUPABASE_URL + '/rest/v1/' + table + '?' + query,
                          headers=_svc_headers())
    if st != 200 or not isinstance(rows, list):
        raise RuntimeError('%s select failed: %s' % (table, st))
    return rows


def _patch(table, row_id, payload):
    st, rows = _http_json(
        'PATCH',
        SUPABASE_URL + '/rest/v1/' + table + '?id=eq.' + urllib.parse.quote(str(row_id)),
        headers=_svc_headers('return=representation'),
        body=payload,
    )
    if st not in (200, 204):
        raise RuntimeError('%s update failed: %s %s' % (table, st, rows))
    return rows


def _insert(table, payload, resolution='merge-duplicates'):
    prefer = 'return=representation'
    if resolution:
        prefer += ',resolution=' + resolution
    st, rows = _http_json('POST', SUPABASE_URL + '/rest/v1/' + table,
                          headers=_svc_headers(prefer), body=payload)
    if st not in (200, 201):
        raise RuntimeError('%s insert failed: %s %s' % (table, st, rows))
    return rows


def _summary(opps):
    out = {
        'total_active': 0, 'apply_now': 0, 'reach_out': 0,
        'along_the_route': 0, 'conflicts': 0, 'watchlist': 0,
        'partner_opportunities': 0,
    }
    for o in opps:
        stage = o.get('queue_stage') or 'watchlist'
        if stage != 'retired':
            out['total_active'] += 1
        if stage in out:
            out[stage] += 1
    return out


def _get_payload(editor_email):
    opps = _select(
        'event_opportunities',
        'select=*&queue_stage=neq.retired&order=opportunity_score.desc.nullslast,start_date.asc&limit=120'
    )
    ids = [str(o['id']) for o in opps if o.get('id') is not None]
    fits = []
    contacts = []
    people = []
    if ids:
        inside = '(' + ','.join(ids) + ')'
        fits = _select('person_event_fit', 'select=*&opportunity_id=in.' + urllib.parse.quote(inside, safe='(),') + '&limit=500')
        people = _select('event_people', 'select=*&opportunity_id=in.' + urllib.parse.quote(inside, safe='(),') + '&limit=1000')
        contacts = _select('event_contacts', 'select=*&opportunity_id=in.' + urllib.parse.quote(inside, safe='(),') + '&limit=1000')

    legacy_ids = [o.get('source_key') for o in opps if o.get('source_table') == 'manual_events' and o.get('source_key')]
    legacy = []
    if legacy_ids:
        safe_ids = [x for x in legacy_ids if str(x).isdigit()]
        if safe_ids:
            inside = '(' + ','.join(safe_ids) + ')'
            legacy = _select(
                'manual_events',
                'select=id,location,status,submission_status,submitted_at,speaker,poc_name,poc_email,poc_linkedin,additional_contacts,notes,outreach_assignees,outreach_note,follow_ups,deadline,speaking_route,apply_url,priority,interested,attend_verdict,postmortem&id=in.' + urllib.parse.quote(inside, safe='(),') + '&limit=300'
            )

    if not editor_email:
        for c in contacts:
            c.pop('email', None)
            c.pop('notes', None)
        for row in legacy:
            row.pop('poc_email', None)
            row.pop('additional_contacts', None)
            row.pop('notes', None)
            row.pop('outreach_note', None)
            row.pop('follow_ups', None)
        travel = []
    else:
        travel = _select('travel_windows', 'select=*&end_date=gte.' + urllib.parse.quote(__import__('datetime').date.today().isoformat()) + '&order=start_date.asc&limit=200')

    return {
        'ok': True,
        'editor': bool(editor_email),
        'editor_email': editor_email or None,
        'summary': _summary(opps),
        'opportunities': opps,
        'fits': fits,
        'contacts': contacts,
        'people': people,
        'legacy': legacy,
        'travel_windows': travel,
        'defaults': {'thor': 'New York', 'verma': 'New York', 'jerome': 'London'},
    }


def _clean_date(value):
    value = str(value or '').strip()
    if not value:
        return None
    if len(value) == 10 and value[4] == '-' and value[7] == '-':
        return value
    raise ValueError('date must be YYYY-MM-DD')


ALLOWED_QUEUE = {'apply_now','reach_out','along_the_route','conflicts','watchlist','partner_opportunities','retired'}
ALLOWED_PRIORITY = {'High','Medium','Low'}
ALLOWED_CONTACT_STATUS = {'not_started','drafted','contacted','followed_up','replied','meeting','closed'}


def _post(handler, editor_email, body):
    if not editor_email:
        return 403, {'error': 'editor authorization required'}
    action = str(body.get('action') or '').strip()

    if action == 'update_opportunity':
        row_id = int(body.get('id'))
        patch = {}
        if 'queue_stage' in body:
            value = str(body.get('queue_stage') or '')
            if value not in ALLOWED_QUEUE:
                raise ValueError('invalid queue_stage')
            patch['queue_stage'] = value
        if 'priority' in body:
            value = body.get('priority')
            if value is not None and value not in ALLOWED_PRIORITY:
                raise ValueError('invalid priority')
            patch['priority'] = value
        if 'next_action' in body:
            patch['next_action'] = str(body.get('next_action') or '')[:1000] or None
        if 'next_action_due' in body:
            patch['next_action_due'] = _clean_date(body.get('next_action_due'))
        if 'owner_person' in body:
            patch['owner_person'] = str(body.get('owner_person') or '').strip().lower()[:80]
        if not patch:
            raise ValueError('no allowed fields supplied')
        return 200, {'ok': True, 'rows': _patch('event_opportunities', row_id, patch)}

    if action == 'update_contact_status':
        row_id = int(body.get('id'))
        status = str(body.get('outreach_status') or '')
        if status not in ALLOWED_CONTACT_STATUS:
            raise ValueError('invalid outreach_status')
        patch = {'outreach_status': status}
        if 'next_follow_up_at' in body:
            patch['next_follow_up_at'] = body.get('next_follow_up_at') or None
        if status in ('contacted','followed_up'):
            patch['last_contacted_at'] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        return 200, {'ok': True, 'rows': _patch('event_contacts', row_id, patch)}

    if action == 'add_contact':
        opportunity_id = int(body.get('opportunity_id'))
        payload = {
            'opportunity_id': opportunity_id,
            'full_name': str(body.get('full_name') or '').strip()[:250] or None,
            'role': str(body.get('role') or '').strip()[:250] or None,
            'organization': str(body.get('organization') or '').strip()[:250] or None,
            'email': str(body.get('email') or '').strip()[:320] or None,
            'linkedin_url': str(body.get('linkedin_url') or '').strip()[:1000] or None,
            'contact_type': str(body.get('contact_type') or 'program').strip(),
            'source_url': str(body.get('source_url') or '').strip()[:1000] or None,
            'confidence': str(body.get('confidence') or 'unknown').strip(),
            'warm_via': str(body.get('warm_via') or '').strip()[:250] or None,
            'owner_person': str(body.get('owner_person') or editor_email).strip()[:250],
            'notes': str(body.get('notes') or '').strip()[:3000] or None,
        }
        return 200, {'ok': True, 'rows': _insert('event_contacts', payload, resolution='')}

    if action == 'postmortem':
        payload = {
            'source_table': str(body.get('source_table') or '').strip()[:100],
            'source_key': str(body.get('source_key') or '').strip()[:200],
            'person_key': str(body.get('person_key') or '').strip().lower()[:100] or None,
            'speaking_achieved': body.get('speaking_achieved'),
            'senior_buyer_conversations': body.get('senior_buyer_conversations'),
            'qualified_leads': body.get('qualified_leads'),
            'follow_up_meetings': body.get('follow_up_meetings'),
            'useful_partnerships': body.get('useful_partnerships'),
            'estimated_trip_cost': body.get('estimated_trip_cost'),
            'would_attend_again': body.get('would_attend_again'),
            'why': str(body.get('why') or '').strip()[:5000] or None,
            'completed_by': editor_email,
        }
        if not payload['source_table'] or not payload['source_key']:
            raise ValueError('source_table and source_key required')
        return 200, {'ok': True, 'rows': _insert('event_postmortems', payload)}

    return 400, {'error': 'unknown action'}


def _send(handler, status, payload):
    raw = json.dumps(payload, default=str).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    handler.end_headers()
    handler.wfile.write(raw)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _send(self, 204, {})

    def do_GET(self):
        try:
            if not _same_origin(self):
                return _send(self, 403, {'error': 'forbidden: call from tracker site'})
            if not SERVICE_ROLE:
                return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
            email = _editor_email(self)
            return _send(self, 200, _get_payload(email))
        except Exception as e:  # noqa: BLE001
            return _send(self, 500, {'error': type(e).__name__, 'msg': str(e)[:500]})

    def do_POST(self):
        try:
            if not _same_origin(self):
                return _send(self, 403, {'error': 'forbidden: call from tracker site'})
            if not SERVICE_ROLE:
                return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
            length = min(int(self.headers.get('Content-Length', '0') or '0'), 200000)
            body = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
            email = _editor_email(self)
            status, payload = _post(self, email, body if isinstance(body, dict) else {})
            return _send(self, status, payload)
        except ValueError as e:
            return _send(self, 400, {'error': str(e)})
        except Exception as e:  # noqa: BLE001
            return _send(self, 500, {'error': type(e).__name__, 'msg': str(e)[:500]})
