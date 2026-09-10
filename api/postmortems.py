"""GET/POST /api/postmortems — lightweight learning loop for attended events.

GET surfaces recent past events that were marked worth attending but do not yet
have a structured postmortem. POST is editor-only and upserts the structured
postmortem without overwriting legacy manual_events.postmortem.
"""
from http.server import BaseHTTPRequestHandler
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()

SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SUPABASE_PUBLISHABLE = _env('SUPABASE_PUBLISHABLE_KEY')
SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')


def _http(method, url, headers=None, body=None):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        h.setdefault('Content-Type', 'application/json')
    req = urllib.request.Request(url, method=method, headers=h, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode('utf-8')
            try: return r.status, json.loads(raw)
            except json.JSONDecodeError: return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try: return e.code, json.loads(raw)
        except json.JSONDecodeError: return e.code, raw
    except Exception as e:
        return 0, {'error': str(e)}


def _svc(prefer=''):
    h={'apikey':SERVICE_ROLE,'Authorization':'Bearer '+SERVICE_ROLE,'Content-Type':'application/json'}
    if prefer: h['Prefer']=prefer
    return h


def _same_origin(handler):
    host=(handler.headers.get('Host','') or '').lower().strip()
    if not host: return False
    for key in ('Origin','Referer'):
        v=(handler.headers.get(key,'') or '').lower().strip()
        if v:
            try:
                if urllib.parse.urlsplit(v).netloc == host: return True
            except ValueError: pass
    return False


def _editor_email(handler):
    auth=(handler.headers.get('Authorization','') or '').strip()
    token=auth[7:].strip() if auth[:7].lower()=='bearer ' else ''
    if not token or not SUPABASE_PUBLISHABLE or not SERVICE_ROLE: return ''
    st,user=_http('GET',SUPABASE_URL+'/auth/v1/user',headers={'apikey':SUPABASE_PUBLISHABLE,'Authorization':'Bearer '+token})
    if st!=200 or not isinstance(user,dict): return ''
    email=(user.get('email') or '').strip().lower()
    if not email: return ''
    st,rows=_http('GET',SUPABASE_URL+'/rest/v1/allowed_editors?select=email&email=eq.'+urllib.parse.quote(email),headers=_svc())
    return email if st==200 and isinstance(rows,list) and rows else ''


def _select(table, query):
    st,rows=_http('GET',SUPABASE_URL+'/rest/v1/'+table+'?'+query,headers=_svc())
    if st!=200 or not isinstance(rows,list): raise RuntimeError('%s select failed %s' % (table,st))
    return rows


def _due():
    today=dt.date.today().isoformat()
    past=_select('manual_events','select=id,name,start_date,end_date,location,attend_verdict,speaker,interested&start_date=lt.'+today+'&order=start_date.desc&limit=120')
    done=_select('event_postmortems','select=source_table,source_key,person_key,completed_at&source_table=eq.manual_events&limit=500')
    completed={str(x.get('source_key')) for x in done}
    out=[]
    for row in past:
        verdict=(row.get('attend_verdict') or '').strip().lower()
        if not verdict.startswith('worth attending') or str(row.get('id')) in completed:
            continue
        owner=''
        speaker=(row.get('speaker') or '').lower()
        if 'verma' in speaker: owner='verma'
        elif 'thor' in speaker: owner='thor'
        elif 'jerome' in speaker: owner='jerome'
        elif 'carlos' in speaker: owner='carlos'
        elif 'joe' in speaker: owner='joe'
        row['person_key']=owner or None
        out.append(row)
    return out[:25]


def _send(handler,status,payload):
    body=json.dumps(payload,default=str).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type','application/json')
    handler.send_header('Cache-Control','no-store')
    handler.send_header('Access-Control-Allow-Origin','*')
    handler.send_header('Access-Control-Allow-Headers','Content-Type, Authorization')
    handler.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
    handler.end_headers(); handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self): _send(self,204,{})
    def do_GET(self):
        try:
            if not _same_origin(self): return _send(self,403,{'error':'forbidden'})
            if not SERVICE_ROLE: return _send(self,500,{'error':'service role missing'})
            rows=_due()
            return _send(self,200,{'ok':True,'editor':bool(_editor_email(self)),'count':len(rows),'due':rows})
        except Exception as e:
            return _send(self,500,{'error':type(e).__name__,'msg':str(e)[:400]})
    def do_POST(self):
        try:
            if not _same_origin(self): return _send(self,403,{'error':'forbidden'})
            email=_editor_email(self)
            if not email: return _send(self,403,{'error':'editor authorization required'})
            n=min(int(self.headers.get('Content-Length','0') or '0'),100000)
            b=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
            source_key=str(b.get('source_key') or '').strip()
            if not source_key: return _send(self,400,{'error':'source_key required'})
            payload={
              'source_table':'manual_events','source_key':source_key,
              'person_key':str(b.get('person_key') or '').strip().lower() or None,
              'speaking_achieved':b.get('speaking_achieved'),
              'senior_buyer_conversations':b.get('senior_buyer_conversations'),
              'qualified_leads':b.get('qualified_leads'),
              'follow_up_meetings':b.get('follow_up_meetings'),
              'useful_partnerships':b.get('useful_partnerships'),
              'estimated_trip_cost':b.get('estimated_trip_cost'),
              'would_attend_again':b.get('would_attend_again'),
              'why':str(b.get('why') or '').strip()[:5000] or None,
              'completed_by':email,
            }
            # Check existing unique key first, then PATCH/POST explicitly.
            q='source_table=eq.manual_events&source_key=eq.'+urllib.parse.quote(source_key)+'&person_key=' + ('is.null' if payload['person_key'] is None else 'eq.'+urllib.parse.quote(payload['person_key'])) + '&select=id'
            existing=_select('event_postmortems',q)
            if existing:
                st,rows=_http('PATCH',SUPABASE_URL+'/rest/v1/event_postmortems?id=eq.'+str(existing[0]['id']),headers=_svc('return=representation'),body=payload)
            else:
                st,rows=_http('POST',SUPABASE_URL+'/rest/v1/event_postmortems',headers=_svc('return=representation'),body=payload)
            if st not in (200,201,204): raise RuntimeError('postmortem write failed %s' % st)
            return _send(self,200,{'ok':True,'rows':rows})
        except Exception as e:
            return _send(self,500,{'error':type(e).__name__,'msg':str(e)[:400]})
