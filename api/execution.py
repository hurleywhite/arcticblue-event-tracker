"""GET/POST /api/execution — focused next-best-action queue for event bookings.

This endpoint turns the opportunity pipeline into executable work. It never
sends email, submits an application, or mutates legacy human-owned workflow
fields. Automation may create/surface tasks; humans complete the external act.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
import json
import urllib.parse
from api import opportunities as db


def _get():
    # The DB refresh is idempotent; cron also runs it every six hours. Running
    # here makes the command center current immediately after a user change.
    db._http_json('POST', db.SUPABASE_URL + '/rest/v1/rpc/refresh_event_action_queue',
                  headers=db._svc_headers(), body={})

    actions = db._select(
        'event_action_command_center',
        'select=*&order=commercial_tier.asc,priority_score.desc,due_at.asc.nullslast&limit=80'
    )
    # Keep the main worklist deliberately small. Tier 1 gets most of the slots;
    # Carlos gets a couple; partner-specific work never crowds the main queue.
    tier1 = [a for a in actions if a.get('commercial_tier') == 1]
    tier2 = [a for a in actions if a.get('commercial_tier') == 2]
    partners = [a for a in actions if a.get('commercial_tier') == 3]
    work_now = tier1[:9] + tier2[:2] + partners[:1]
    work_now.sort(key=lambda a: (int(a.get('commercial_tier') or 9), -int(a.get('priority_score') or 0), str(a.get('due_at') or '9999')))

    opp_ids = sorted({str(a['opportunity_id']) for a in work_now if a.get('opportunity_id') is not None})
    contacts = []
    fits = []
    if opp_ids:
        inside = '(' + ','.join(opp_ids) + ')'
        contacts = db._select('event_contacts', 'select=*&opportunity_id=in.' + urllib.parse.quote(inside, safe='(),') + '&limit=300')
        fits = db._select('person_event_fit', 'select=*&opportunity_id=in.' + urllib.parse.quote(inside, safe='(),') + '&limit=300')

    all_open = db._select('event_actions', 'select=id,action_type,status,due_at,owner_person&status=eq.open&limit=1000')
    now = datetime.now(timezone.utc)
    metrics = {
        'work_now': len(work_now),
        'open_actions': len(all_open),
        'overdue': sum(1 for a in all_open if a.get('due_at') and str(a['due_at']) < now.isoformat()),
        'applications': sum(1 for a in all_open if a.get('action_type') == 'apply'),
        'follow_ups': sum(1 for a in all_open if a.get('action_type') in ('follow_up','application_follow_up','escalate')),
        'contact_finding': sum(1 for a in all_open if a.get('action_type') == 'find_contact'),
        'warm_paths': sum(1 for a in all_open if a.get('action_type') == 'warm_intro'),
    }
    return {'ok': True, 'metrics': metrics, 'actions': work_now, 'contacts': contacts, 'fits': fits}


def _post(body, who):
    action = str(body.get('action') or '').strip()
    if action == 'refresh':
        st, payload = db._http_json('POST', db.SUPABASE_URL + '/rest/v1/rpc/refresh_event_action_queue',
                                    headers=db._svc_headers(), body={})
        if st not in (200, 204):
            raise RuntimeError('refresh failed')
        return {'ok': True, 'generated': payload}

    row_id = int(body.get('id') or 0)
    rows = db._select('event_actions', 'select=id,status,metadata&id=eq.' + str(row_id) + '&limit=1')
    if not rows:
        raise ValueError('Action not found.')

    if action == 'complete':
        patch = {'status': 'done', 'completed_at': datetime.now(timezone.utc).isoformat(),
                 'updated_at': datetime.now(timezone.utc).isoformat()}
        meta = dict(rows[0].get('metadata') or {})
        meta['completed_by'] = who
        patch['metadata'] = meta
        db._patch('event_actions', row_id, patch)
        return {'ok': True}

    if action == 'snooze':
        days = int(body.get('days') or 3)
        if days not in (1, 3, 7, 14):
            raise ValueError('Snooze must be 1, 3, 7, or 14 days.')
        db._patch('event_actions', row_id, {
            'due_at': (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        })
        return {'ok': True}

    if action == 'cancel':
        db._patch('event_actions', row_id, {'status': 'cancelled', 'updated_at': datetime.now(timezone.utc).isoformat()})
        return {'ok': True}

    raise ValueError('Unknown action.')


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if not db._same_origin(self):
                return db._send(self, 403, {'error': 'Call from the tracker site.'})
            return db._send(self, 200, _get())
        except Exception:
            return db._send(self, 500, {'error': 'Execution queue could not load.'})

    def do_POST(self):
        try:
            if not db._same_origin(self):
                return db._send(self, 403, {'error': 'Call from the tracker site.'})
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100000:
                return db._send(self, 413, {'error': 'Request too large.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Object required.')
            who = db._caller(self, body)
            return db._send(self, 200, _post(body, who))
        except (ValueError, TypeError) as exc:
            return db._send(self, 400, {'error': str(exc)[:250]})
        except Exception:
            return db._send(self, 500, {'error': 'Execution action failed.'})
