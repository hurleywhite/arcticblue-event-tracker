"""Private application workspace and read-only Attio integration.

Every operation requires the existing approved-editor session. Secrets and
drafts live in service-only tables, never the public booking JSON or build.
No operation sends mail, submits applications or writes to Attio.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import json
import os
import re
import urllib.parse
from uuid import UUID
from api import opportunities as db


def _connection(key):
    rows = db._select('event_integrations', 'select=config&key=eq.' + urllib.parse.quote(key, safe=''))
    return rows[0]['config'] if rows else {}


def _save_connection(key, config, email):
    db._insert('event_integrations', {'key': key, 'config': config,
               'updated_by': email, 'updated_at': datetime.now(timezone.utc).isoformat()})


def _status():
    configs = db._select('event_integrations', 'select=key,updated_at')
    keys = {r['key']: r for r in configs}
    from api.calendars import _feeds
    feeds = _feeds()
    return {'attio_configured': bool(os.environ.get('ATTIO_API_KEY') or 'attio' in keys),
            'calendars': [{'person': p, 'configured': any(f['name'].lower() == p for f in feeds)}
                          for p in ('thor', 'verma', 'jerome')]}


def _attio(method, path, body=None, token=None):
    token = token or os.environ.get('ATTIO_API_KEY') or _connection('attio').get('token')
    if not token:
        raise ValueError('Connect Attio first, or enter a personal contact manually.')
    status, data = db._http_json(method, 'https://api.attio.com/v2/' + path,
                              headers={'Authorization': 'Bearer ' + token}, body=body, timeout=15)
    if status != 200 or not isinstance(data, dict):
        raise ValueError('Attio request failed (%s). Check the connection and read permissions.' % status)
    return data


def _contact(record):
    values = record.get('values', {})
    def first(key, field='value'):
        arr = values.get(key) or []
        return arr[0].get(field, '') if arr else ''
    return {'record_id': record.get('id', {}).get('record_id'),
            'name': first('name', 'full_name'), 'email': first('email_addresses', 'email_address'),
            'role': first('job_title'), 'linkedin': first('linkedin'),
            'attio_url': record.get('web_url', ''), 'source': 'Attio',
            'relationship': 'Not verified'}


def _identity(body):
    table, key = str(body.get('source_table', '')), str(body.get('source_key', ''))
    if table not in ('manual_events', 'event_state') or not re.fullmatch(r'\d{1,12}', key):
        raise ValueError('A valid original event is required.')
    return table, key


def _clean_document(body):
    document = body.get('document')
    if not isinstance(document, dict):
        raise ValueError('Workspace document required.')
    limits = {'owner':80, 'contact_name':250, 'contact_email':320, 'contact_role':250,
              'contact_company':250, 'contact_source':1000, 'attio_url':1000,
              'attio_record_id':80, 'warm_via':250, 'relationship_context':3000,
              'route':80, 'angle':5000, 'ask':2000, 'subject':500, 'body':15000,
              'status':40, 'follow_up_due':10, 'sent_at':10, 'reply_at':10}
    result = {k:str(document.get(k) or '').strip()[:n] for k,n in limits.items()}
    if result['status'] not in ('Not started', 'Drafting', 'Ready', 'Sent', 'Replied', 'Closed'):
        raise ValueError('Invalid outreach status.')
    if result['route'] not in ('Speaker pitch', 'Warm introduction', 'Follow-up', 'Meeting request'):
        raise ValueError('Choose an outreach route.')
    if result['contact_email'] and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', result['contact_email']):
        raise ValueError('Enter a valid contact email.')
    for k in ('sent_at', 'reply_at', 'follow_up_due'):
        if result[k]: db._clean_date(result[k])
    today = datetime.now(timezone.utc).date().isoformat()
    if any(result[k] and result[k] > today for k in ('sent_at','reply_at')):
        raise ValueError('Sent and reply dates cannot be in the future.')
    if result['reply_at'] and (not result['sent_at'] or result['reply_at'] < result['sent_at']):
        raise ValueError('A reply needs a sent date on or before the reply.')
    if result['status'] in ('Sent','Replied') and not result['sent_at']:
        raise ValueError('Record the actual sent date.')
    if result['status'] == 'Replied' and not result['reply_at']:
        raise ValueError('Record the actual reply date.')
    return result


def _post(email, body):
    if not email:
        return 403, {'error':'Editor sign-in required.'}
    action = body.get('action')
    if action == 'connect_attio':
        token = str(body.get('token') or '').strip()
        if not 15 <= len(token) <= 5000 or '\n' in token or '\r' in token:
            raise ValueError('Enter a valid Attio access token.')
        _attio('POST', 'objects/people/records/query', {'limit':1}, token=token)
        _save_connection('attio', {'token':token}, email)
        return 200, {'ok':True}
    if action == 'connect_calendar':
        from api.calendars import _fetch_google_feed
        person, url = str(body.get('person','')).lower(), str(body.get('url','')).strip()
        if person not in ('thor','verma','jerome'): raise ValueError('Select a teammate.')
        _fetch_google_feed(url)  # validate origin and content before saving
        _save_connection('calendar:'+person, {'url':url}, email)
        return 200, {'ok':True}
    if action == 'disconnect':
        key = str(body.get('key',''))
        if key not in ('attio','calendar:thor','calendar:verma','calendar:jerome'):
            raise ValueError('Unknown connection.')
        status, _ = db._http_json('DELETE', db.SUPABASE_URL+'/rest/v1/event_integrations?key=eq.'+urllib.parse.quote(key), headers=db._svc_headers())
        if status != 204: raise ValueError('Could not disconnect.')
        return 200, {'ok':True}
    if action == 'search_contacts':
        query = str(body.get('query') or '').strip()[:256]
        if len(query) < 2: raise ValueError('Search by name, company domain or email.')
        result = _attio('POST', 'objects/records/search', {'query':query,'objects':['people'],
                         'request_as':{'type':'workspace'},'limit':10})
        return 200, {'contacts':[{'record_id':r['id']['record_id'], 'name':r.get('record_text','')}
                                for r in result.get('data', [])]}
    if action == 'get_contact':
        record_id = str(UUID(str(body.get('record_id'))))
        return 200, {'contact':_contact(_attio('GET','objects/people/records/'+record_id)['data'])}
    if action == 'preview_calendar':
        from api.calendars import _parse_ics, _normalize, _trip_candidates
        from datetime import date, timedelta
        person = str(body.get('person','')).lower()
        text = str(body.get('ics',''))
        if person not in ('thor','verma','jerome') or 'BEGIN:VCALENDAR' not in text:
            raise ValueError('Choose a teammate and a valid .ics export.')
        blocks, skipped = _normalize(_parse_ics(text), date.today().isoformat(), (date.today()+timedelta(days=400)).isoformat())
        return 200, {'candidates':_trip_candidates(person, blocks, 'Calendar export'), 'recurring_skipped':skipped}
    if action == 'save_trip':
        person = str(body.get('person_key','')).lower()
        city = str(body.get('city','')).strip()[:250]
        start, end = db._clean_date(body.get('start_date')), db._clean_date(body.get('end_date'))
        uid = str(body.get('source_event_id',''))[:500]
        if person not in ('thor','verma','jerome') or not city or not start or not end or end < start or not uid:
            raise ValueError('Review the person, city, dates and calendar source first.')
        rows = db._select('travel_windows','select=id&person_key=eq.'+person+'&source_event_id=eq.'+urllib.parse.quote(uid,safe=''))
        payload = {'person_key':person,'city':city,'start_date':start,'end_date':end,
                   'source':'Calendar reviewed','source_event_id':uid,'confidence':'confirmed',
                   'notes':'Calendar dates and destination reviewed by '+email}
        # Merge a previously recorded identical window instead of duplicating it.
        if not rows:
            rows = db._select('travel_windows','select=id&person_key=eq.'+person+'&city=ilike.'+urllib.parse.quote(city,safe='')+'&start_date=eq.'+start+'&end_date=eq.'+end)
        result = db._patch('travel_windows',rows[0]['id'],payload) if rows else db._insert('travel_windows',payload,resolution='')
        return 200, {'ok':True,'rows':result}
    if action == 'save_workspace':
        table,key = _identity(body)
        document = _clean_document(body)
        version = int(body.get('version') or 0)
        event_key = table+':'+key
        payload = {'event_key':event_key,'source_table':table,'source_key':key,
                   'document':document,'version':version+1,'updated_by':email,
                   'updated_at':datetime.now(timezone.utc).isoformat()}
        if version:
            status,result = db._http_json('PATCH',db.SUPABASE_URL+'/rest/v1/event_application_workspaces?event_key=eq.'+urllib.parse.quote(event_key)+'&version=eq.'+str(version),headers=db._svc_headers('return=representation'),body=payload)
            if status == 200 and not result:
                return 409, {'error':'Another editor changed this workspace. Close and reopen before saving.'}
        else:
            status,result = db._http_json('POST',db.SUPABASE_URL+'/rest/v1/event_application_workspaces',headers=db._svc_headers('return=representation'),body=payload)
        if status == 409:
            return 409, {'error':'Another editor saved this workspace. Close and reopen before saving.'}
        if status not in (200,201): raise RuntimeError('Workspace save failed.')
        return 200, {'ok':True,'workspace':result[0]}
    return 400, {'error':'Unknown workflow action.'}


def _get(query):
    if query.get('source_table'):
        table,key = _identity({k:v[0] for k,v in query.items()})
        rows = db._select('event_application_workspaces','select=*&event_key=eq.'+urllib.parse.quote(table+':'+key))
        return {'workspace':rows[0] if rows else None, **_status()}
    rows = db._select('event_application_workspaces','select=event_key,document,version,updated_at&limit=1000')
    return {'workspaces':rows, **_status()}


class handler(BaseHTTPRequestHandler):
    def do_GET(self): self._handle(False)
    def do_POST(self): self._handle(True)
    def _handle(self, post):
        try:
            if not db._same_origin(self): return db._send(self,403,{'error':'Call from the tracker site.'})
            email = db._editor_email(self)
            if not email: return db._send(self,403,{'error':'Editor sign-in required.'})
            if post:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 2000000: return db._send(self,413,{'error':'Request is too large.'})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body,dict): raise ValueError('Object required.')
                status,payload = _post(email,body)
            else:
                status,payload = 200,_get(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
            return db._send(self,status,payload)
        except (ValueError,TypeError) as exc:
            return db._send(self,400,{'error':str(exc)[:250]})
        except Exception:
            # Never echo upstream bodies, credentials or calendar URLs.
            return db._send(self,500,{'error':'Workflow could not load. Please refresh or check the connection.'})
