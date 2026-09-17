"""POST /api/research_contacts — resolve top event contact-research actions.

Uses the tracker's existing Perplexity research credential to identify public
conference/program contacts. Saves only sourced public business information and
never sends outreach. A name/email without a public source is discarded rather
than guessed. Intended for the nightly GitHub workflow and manual runs.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import hmac, json, os, re, urllib.parse, urllib.request, urllib.error
from api import opportunities as db

INGEST_SECRET = (os.environ.get('EVENTS_INGEST_SECRET') or '').strip()
PPLX_API_KEY = (os.environ.get('PERPLEXITY_API_KEY') or '').strip()
PPLX_MODEL = (os.environ.get('PERPLEXITY_MODEL') or 'sonar').strip()
PPLX_BASE = (os.environ.get('PERPLEXITY_BASE_URL') or 'https://api.perplexity.ai').rstrip('/')

SYSTEM = """You research business conference organizers for speaker outreach.
Return ONLY one raw JSON object. Identify the best PUBLIC business contact for
this exact event, in this order: conference/program director; speaker/content
lead; relevant track chair; partnerships lead. Never infer or construct an
email address. Include an email only when you found it publicly published.
Required: source_url. Optional: full_name, role, organization, email,
linkedin_url. Add confidence as verified or probable and one short
relevance_reason. If you cannot identify a sourced useful contact, return
{"found": false}. Do not return attendee/speaker targets as organizer contacts."""


def _pplx(event):
    if not PPLX_API_KEY:
        return {}
    payload = {
        'model': PPLX_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': json.dumps(event, ensure_ascii=False)},
        ],
        'temperature': 0.05,
        'max_tokens': 650,
    }
    st, data = db._http_json('POST', PPLX_BASE + '/chat/completions',
        headers={'Authorization': 'Bearer ' + PPLX_API_KEY, 'Content-Type': 'application/json'},
        body=payload, timeout=35)
    if st != 200 or not isinstance(data, dict):
        return {}
    try:
        text = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return {}
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m:
        return {}
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _good_url(value):
    value = str(value or '').strip()
    if not value.startswith(('https://','http://')) or len(value) > 1200:
        return None
    try:
        host = urllib.parse.urlsplit(value).netloc.lower()
    except ValueError:
        return None
    return value if host else None


def _clean_contact(raw):
    if not raw or raw.get('found') is False:
        return None
    source = _good_url(raw.get('source_url'))
    if not source:
        return None
    full_name = str(raw.get('full_name') or '').strip()[:250] or None
    role = str(raw.get('role') or '').strip()[:250] or None
    org = str(raw.get('organization') or '').strip()[:250] or None
    email = str(raw.get('email') or '').strip().lower()[:320] or None
    linkedin = _good_url(raw.get('linkedin_url'))
    if email and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
        email = None
    if not (full_name or email or linkedin):
        return None
    confidence = str(raw.get('confidence') or 'probable').strip().lower()
    if confidence not in ('verified','probable'):
        confidence = 'probable'
    # Model-supplied verification is never enough by itself to claim stronger
    # than probable unless a public source URL exists (required above).
    reason = str(raw.get('relevance_reason') or '').strip()[:1000] or None
    return {'full_name':full_name,'role':role,'organization':org,'email':email,
            'linkedin_url':linkedin,'source_url':source,'confidence':confidence,
            'notes':reason}


def _research(limit):
    # Refresh first so new high-value opportunities enter the queue.
    db._http_json('POST', db.SUPABASE_URL + '/rest/v1/rpc/refresh_event_action_queue', headers=db._svc_headers(), body={})
    actions = db._select('event_action_command_center',
        'select=id,opportunity_id,owner_person,event_name,start_date,city,country,url,priority_score,action_type,commercial_tier'
        '&action_type=eq.find_contact&order=commercial_tier.asc,priority_score.desc,due_at.asc&limit=' + str(limit))
    results = []
    for a in actions:
        opp_id = int(a['opportunity_id'])
        opps = db._select('event_opportunities','select=id,source_table,source_key,name,url,city,country,start_date&id=eq.'+str(opp_id)+'&limit=1')
        if not opps:
            continue
        o = opps[0]
        existing = db._select('event_contacts','select=id,full_name,email,linkedin_url&opportunity_id=eq.'+str(opp_id)+'&limit=20')
        if any(x.get('email') or x.get('linkedin_url') or x.get('full_name') for x in existing):
            db._patch('event_actions', a['id'], {'status':'done','completed_at':datetime.now(timezone.utc).isoformat(),'updated_at':datetime.now(timezone.utc).isoformat()})
            results.append({'opportunity_id':opp_id,'event':o['name'],'result':'already_has_contact'})
            continue
        raw = _pplx({'name':o.get('name'),'date':o.get('start_date'),'city':o.get('city'),'country':o.get('country'),'official_url':o.get('url')})
        c = _clean_contact(raw)
        if not c:
            results.append({'opportunity_id':opp_id,'event':o['name'],'result':'unresolved'})
            continue
        c.update({'opportunity_id':opp_id,'contact_type':'program','owner_person':o.get('owner_person') or a.get('owner_person'),
                  'outreach_status':'not_started'})
        # Dedupe by email first, otherwise by sourced full name.
        dup = []
        if c.get('email'):
            dup = db._select('event_contacts','select=id&opportunity_id=eq.'+str(opp_id)+'&email=eq.'+urllib.parse.quote(c['email'],safe='')+'&limit=1')
        elif c.get('full_name'):
            dup = db._select('event_contacts','select=id&opportunity_id=eq.'+str(opp_id)+'&full_name=ilike.'+urllib.parse.quote(c['full_name'],safe='')+'&limit=1')
        if not dup:
            db._insert('event_contacts', c, resolution='')
        db._patch('event_actions', a['id'], {'status':'done','completed_at':datetime.now(timezone.utc).isoformat(),'updated_at':datetime.now(timezone.utc).isoformat(),
                                             'metadata':{'resolved_by':'nightly public contact research','source_url':c['source_url']}})
        results.append({'opportunity_id':opp_id,'event':o['name'],'result':'contact_found','contact':c.get('full_name') or c.get('email'),'confidence':c.get('confidence')})
    db._http_json('POST', db.SUPABASE_URL + '/rest/v1/rpc/refresh_event_action_queue', headers=db._svc_headers(), body={})
    return results


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            supplied = (self.headers.get('X-API-Key') or '').strip()
            if not INGEST_SECRET or not supplied or not hmac.compare_digest(supplied, INGEST_SECRET):
                return db._send(self, 401, {'error':'Unauthorized'})
            length = int(self.headers.get('Content-Length','0') or 0)
            body = json.loads(self.rfile.read(length)) if length else {}
            limit = max(1,min(8,int(body.get('limit') or 4)))
            rows = _research(limit)
            return db._send(self,200,{'ok':True,'researched':len(rows),'results':rows})
        except Exception:
            return db._send(self,500,{'error':'Contact research failed.'})
