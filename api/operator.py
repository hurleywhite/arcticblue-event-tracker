"""/api/operator, the event operator: Thor's weekly speaking batch.

  GET  ?person=thor                 the week: the batch, attending, out now,
                                    follow-ups, thank-you notes, needs a record
  POST {"action": "plan"}           pick this week's events and give each a lane
  POST {"action": "prepare"}        find missing contacts and draft, a few at a time
  POST {"action": "digest"}         post the Monday summary to Slack (cron only)
  POST {"action": "approve" | "edit" | "sent" | "submitted" | "followup_sent" |
        "loss_sent" | "outcome" | "skip" | "unskip" | "contact" | "record" |
        "redraft", ...}             what Thor does on /week

Nothing here sends a message or submits an application. LinkedIn has no
messaging API and Sessionize has no speaker API: a person presses send, and the
screen records what was sent. Approved form and email items get the tracker's
existing `decision = 'apply'`, which hands them to Claude's event-apply skill.

GET and the screen's POSTs are same-origin, like the rest of the tracker. plan,
prepare and digest also accept the EVENTS_INGEST_SECRET (the Monday workflow).
Rules live in api/_operator_core.py; see EVENT-OPERATOR.md.
"""
from http.server import BaseHTTPRequestHandler
import datetime as dt
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from api import _operator_core as core
from api import sessionize as sz


def _env(k, d=''):
    return (os.environ.get(k, d) or '').strip()


SUPABASE_URL = _env('SUPABASE_URL', 'https://efkvhlmfdwlobvdmvqiq.supabase.co').rstrip('/')
SERVICE_ROLE = _env('SUPABASE_SERVICE_ROLE_KEY')
INGEST_SECRET = _env('EVENTS_INGEST_SECRET')
TRACKER_BASE = _env('TRACKER_BASE_URL', 'https://arcticblue-event-tracker-deploy.vercel.app').rstrip('/')
OPENAI_API_KEY = _env('OPENAI_API_KEY')
PPLX_API_KEY = _env('PERPLEXITY_API_KEY')
PPLX_MODEL = _env('PERPLEXITY_MODEL', 'sonar')
PPLX_BASE = _env('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai').rstrip('/')
SLACK_WEBHOOK_URL = _env('SLACK_WEBHOOK_URL')
CFG = dict(core.DEFAULTS)
if _env('OPERATOR_WEEKLY_TARGET').isdigit():
    CFG['weekly_target'] = max(1, min(60, int(_env('OPERATOR_WEEKLY_TARGET'))))
if _env('OPERATOR_LINKEDIN_NOTE_MAX').isdigit():
    CFG['linkedin_note_max'] = max(100, min(300, int(_env('OPERATOR_LINKEDIN_NOTE_MAX'))))

try:
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo('America/New_York')
except Exception:  # noqa: BLE001 - no tz database: fall back to EST
    _NY = dt.timezone(dt.timedelta(hours=-5))


def today():
    return dt.datetime.now(_NY).date()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


# ── Supabase ───────────────────────────────────────────────────────────────
def _svc(prefer=''):
    h = {'apikey': SERVICE_ROLE, 'Authorization': 'Bearer ' + SERVICE_ROLE, 'Content-Type': 'application/json'}
    if prefer:
        h['Prefer'] = prefer
    return h


def _http(method, url, headers=None, body=None, timeout=25):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, method=method, headers=dict(headers or {}), data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8')
            try:
                return r.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')[:600]
    except Exception as e:  # noqa: BLE001 - network trouble is a normal answer
        return 0, str(e)[:300]


_READ_COLS = ','.join(sorted(set(core.FIELDS + core.LIST_FIELDS + (
    'status_tags', 'status', 'hidden', 'booking', 'follow_ups'))))


def _select(table):
    key = 'id' if table == 'manual_events' else 'event_num'
    st, rows = _http('GET', '%s/rest/v1/%s?select=%s,%s&limit=5000' % (SUPABASE_URL, table, key, _READ_COLS),
                     headers=_svc())
    if st == 400:   # a column this database does not have yet: read everything instead
        st, rows = _http('GET', '%s/rest/v1/%s?select=*&limit=5000' % (SUPABASE_URL, table), headers=_svc())
    if st != 200 or not isinstance(rows, list):
        raise RuntimeError('%s read failed (%s)' % (table, st))
    return rows


def _catalog():
    st, cat = _http('GET', TRACKER_BASE + '/events.json', headers={'User-Agent': sz._UA})
    if st == 200 and isinstance(cat, dict):
        return cat.get('events') or []
    if st == 200 and isinstance(cat, list):
        return cat
    raise RuntimeError('catalog read failed (%s)' % st)


def load():
    return core.merge(_catalog(), _select('event_state'), _select('manual_events'))


def _row(table, key):
    col = 'id' if table == 'manual_events' else 'event_num'
    st, rows = _http('GET', '%s/rest/v1/%s?%s=eq.%s&select=*' % (
        SUPABASE_URL, table, col, urllib.parse.quote(str(key))), headers=_svc())
    if st != 200 or not isinstance(rows, list):
        raise RuntimeError('%s read failed (%s)' % (table, st))
    return rows[0] if rows else None


_MISSING_COL = re.compile(r"Could not find the '([A-Za-z0-9_]+)' column")


def _write(table, key, patch):
    """Write one event, the way the tracker does: event_state is upserted (a
    catalog event may not have a row yet), manual_events never gets updated_by.
    A column this database does not have is dropped and the write retried."""
    patch = dict(patch, updated_at=_now())
    if table == 'manual_events':
        patch.pop('updated_by', None)
    else:
        patch.setdefault('updated_by', 'Event operator')
    for _ in range(5):
        if table == 'manual_events':
            st, body = _http('PATCH', '%s/rest/v1/manual_events?id=eq.%s' % (SUPABASE_URL, urllib.parse.quote(str(key))),
                             headers=_svc('return=minimal'), body=patch)
        else:
            st, body = _http('POST', '%s/rest/v1/event_state?on_conflict=event_num' % SUPABASE_URL,
                             headers=_svc('resolution=merge-duplicates,return=minimal'), body=dict(patch, event_num=key))
        if st in (200, 201, 204):
            return True
        m = _MISSING_COL.search(str(body or ''))
        if st == 400 and m and m.group(1) in patch and m.group(1) not in ('booking', 'status_tags'):
            patch.pop(m.group(1))
            continue
        raise RuntimeError('write to %s failed (%s): %s' % (table, st, str(body)[:200]))
    raise RuntimeError('write to %s failed after retries' % table)


def _change(table, key, mutate):
    """Read the row fresh, let `mutate(row, booking, op)` change it, write back.
    Reading first keeps the tracker's own booking keys (sessionize_draft, ...)."""
    row = _row(table, key) or {}
    booking = dict(row.get('booking') or {}) if isinstance(row.get('booking'), dict) else {}
    op = dict(booking.get('operator') or {})
    patch = mutate(row, booking, op) or {}
    booking['operator'] = op
    patch['booking'] = booking
    _write(table, key, patch)
    return row, booking, op


def _follow(row, entry):
    v = row.get('follow_ups')
    v = core._follow_list(v)
    return v + [dict(entry)]


# ── Models ─────────────────────────────────────────────────────────────────
def _outreach_prompt(event, c, library, cfg):
    sp = library.get('speaker') or {}
    first = core.first_name(sp.get('name')) or 'Thor'
    talks = [{k: t.get(k) for k in ('id', 'status', 'title', 'level', 'audience', 'short_abstract', 'takeaways')}
             for t in library.get('talks') or []]
    system = (
        'You write short notes from ' + (sp.get('name') or 'the speaker') + ' to the organiser of a business '
        'conference, asking about a speaking slot. Write in his voice: ' + (sp.get('voice') or 'direct, plain') + '\n'
        'Rules:\n'
        '- The pitch is a talk that teaches this event\'s audience something useful. Do not sell ArcticBlue, '
        'its services, a demo or a meeting.\n'
        '- Use ONLY facts from SPEAKER FACTS and the chosen talk. Never invent numbers, clients, results, mutual '
        'connections, past attendance, or anything about the organiser. Do not claim to know them or their event '
        'beyond what EVENT says.\n'
        '- Choose ONE talk from TALK LIBRARY that best fits this event. Prefer status "approved" when two fit '
        'about equally.\n'
        '- Greet the contact by first name only when CONTACT has a name. Otherwise use no name.\n'
        '- No em dashes, no exclamation marks, no hype (excited, thrilled, game-changing, revolutionize, '
        'leverage, delve, synergy).\n'
        '- linkedin_note: a connection request note of at most ' + str(cfg['linkedin_note_max']) + ' characters '
        'including spaces: who he is in a few words, the talk in a few words, a simple ask.\n'
        '- linkedin_message: sent once they accept, at most ' + str(cfg['linkedin_message_max']) + ' characters: '
        'the talk title, one or two sentences on what the audience takes away, one line on why he can teach it, '
        'and a clear question about how speakers are chosen for this event.\n'
        '- email_subject: at most 70 characters, plain. email_body: at most ' + str(cfg['email_words_max']) +
        ' words, the same content as linkedin_message, signed "' + first + '".\n'
        '- Return one JSON object and nothing else.'
    )
    user = (
        'EVENT:\n' + json.dumps(event, ensure_ascii=False) + '\n\n'
        'CONTACT:\n' + json.dumps({'name': (c or {}).get('name', ''), 'about': (c or {}).get('note', '')},
                                  ensure_ascii=False) + '\n\n'
        'SPEAKER FACTS:\n' + '\n'.join('- ' + f for f in sp.get('facts') or []) + '\n\n'
        'TALK LIBRARY:\n' + json.dumps(talks, ensure_ascii=False) + '\n\n'
        'Return JSON with exactly these keys:\n'
        '{"talk_id": "", "why_this_talk": "one sentence", "linkedin_note": "", "linkedin_message": "", '
        '"email_subject": "", "email_body": ""}'
    )
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def _event_brief(rec):
    return {'name': rec.get('name') or '', 'dates': rec.get('date_str') or rec.get('start_date') or '',
            'location': rec.get('location') or rec.get('city') or '', 'type': rec.get('type') or '',
            'about': core.clip(rec.get('about') or rec.get('why') or '', 1500),
            'focus_areas': rec.get('focus_areas') or '', 'audience': rec.get('typical_attendees') or ''}


def _person_of(rec, op):
    return (op.get('person') or core.DEFAULTS['person']).lower()


def _library(person):
    lib, where = sz.load_talks(person)
    if not lib:
        raise RuntimeError('No talk library for %s yet.' % person.capitalize())
    return lib, where


def _talk_checks(library, talk_id):
    talk = next((t for t in library.get('talks') or [] if t.get('id') == talk_id), {})
    out = []
    if talk and talk.get('status') != 'approved':
        out.append('The talk "%s" is still a draft in the talk library: Thor has not approved it yet.' % talk.get('title'))
    return talk, out


def draft_message(rec, person, model=None):
    library, _ = _library(person)
    c = core.contact(rec) or {}
    event = _event_brief(rec)
    msgs = _outreach_prompt(event, c, library, CFG)
    raw, used = model(msgs) if model else sz.call_model(msgs)
    talk_ids = {t.get('id') for t in library.get('talks') or []}
    if raw.get('talk_id') not in talk_ids:
        raw['talk_id'] = next(iter(talk_ids), '')
    talk, checks = _talk_checks(library, raw.get('talk_id'))
    sources = ' '.join([json.dumps(talk, ensure_ascii=False), ' '.join((library.get('speaker') or {}).get('facts') or []),
                        json.dumps(event, ensure_ascii=False)])
    m = core.tidy_message(raw, CFG, sources)
    m.update({'talk_title': talk.get('title', ''), 'talk_status': talk.get('status', 'draft'), 'model': used,
              'generated_at': _now()})
    m['checks'] = checks + m['checks']
    return m


def draft_form(rec, person, model=None):
    """An application for an organiser's own form (not Sessionize): the same
    drafter as Sessionize, reading whatever the form page shows publicly."""
    library, where = _library(person)
    url = core.apply_link(rec)
    st, page = sz.fetch(url) if url else (0, '')
    details = sz.cfp_details(page) if st == 200 and page else {'text': '', 'perks': {}}
    state, closes = core.call_state(rec, today())
    cfp = {'name': rec.get('name') or '', 'status': state, 'opens': '', 'closes': closes.isoformat() if closes else '',
           'timezone': '', 'event_start': rec.get('start_date') or '', 'event_end': rec.get('end_date') or '',
           'website': rec.get('url') or ''}
    event = _event_brief(rec)
    msgs = sz.draft_prompt(event, cfp, details, library)
    raw, used = model(msgs) if model else sz.call_model(msgs)
    d = sz.clean_draft(raw, library)
    d['terms'] = sz._merge_terms(sz.term_flags(details), d['terms'])
    talk = next((t for t in library.get('talks') or [] if t.get('id') == d['talk_id']), {})
    sources = ' '.join([json.dumps(talk, ensure_ascii=False), ' '.join((library.get('speaker') or {}).get('facts') or []),
                        details.get('text') or '', json.dumps(event, ensure_ascii=False)])
    d['checks'] = sz.number_checks(d, sources)
    if not details.get('text'):
        d['unknowns'] = ['The form page could not be read, so its questions are not covered. Check the form.'] + d['unknowns']
    if d['talk_status'] != 'approved':
        d['checks'].insert(0, 'The talk "%s" is still a draft in the talk library: Thor has not approved it yet.' % d['talk_title'])
    for k in ('title', 'short_abstract', 'abstract', 'why_this_talk'):
        d[k] = core.no_dashes(d.get(k))
    d['answers'] = [{'question': a['question'], 'answer': core.no_dashes(a['answer'])} for a in d['answers']]
    d.update({'status': 'ready', 'person': person, 'library': where, 'model': used, 'form_url': url,
              'form_read': bool(details.get('text')), 'generated_at': _now()})
    return d


_RESEARCH = """You find the right person to ask about speaking at a business conference.
Return ONLY one raw JSON object. Find the person who decides or curates the speaker
programme for this exact event, in this order: programme or content director;
conference producer; speaker manager; event director. Prefer someone with a public
LinkedIn profile, and give its URL (linkedin.com/in/...) only if you found it.
Never construct an email address: include one only when it is published. Required:
source_url (where you found the person). Optional: full_name, role, organization,
email, linkedin_url, relevance_reason. If you cannot find a sourced person, return
{"found": false}. Never return attendees or speakers as the contact."""


def research_contact(rec):
    """A sourced organiser contact, or None. Never guessed: the source URL is
    required and an email must be published, as in /api/research_contacts."""
    if not PPLX_API_KEY:
        return None
    from api import research_contacts as rc
    payload = {'model': PPLX_MODEL, 'temperature': 0.05, 'max_tokens': 650, 'messages': [
        {'role': 'system', 'content': _RESEARCH},
        {'role': 'user', 'content': json.dumps({'name': rec.get('name'), 'date': rec.get('start_date'),
                                                'city': rec.get('city') or rec.get('location'),
                                                'official_url': rec.get('url')}, ensure_ascii=False)}]}
    st, data = _http('POST', PPLX_BASE + '/chat/completions', headers={
        'Authorization': 'Bearer ' + PPLX_API_KEY, 'Content-Type': 'application/json'}, body=payload, timeout=40)
    if st != 200 or not isinstance(data, dict):
        return None
    try:
        text = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return None
    raw = sz._json_from(text)
    c = rc._clean_contact(raw) if isinstance(raw, dict) else None
    if not c:
        return None
    if c.get('linkedin_url') and not core._LI.match(c['linkedin_url']):
        c['linkedin_url'] = None
    if not (c.get('linkedin_url') or c.get('email')):
        return None
    return c


# ── Plan and prepare ───────────────────────────────────────────────────────
def _op(rec):
    return (rec.get('booking') or {}).get('operator') or {}


def plan(person='thor'):
    t = today()
    week = core.week_id(t)
    recs = load()
    sel = core.select_week(recs, t, CFG, person, sz.sessionize_link)
    active = [r for r in recs if _op(r).get('week') == week and _op(r).get('person') == person
              and _op(r).get('status') in ('planned', 'ready', 'approved', 'error')]
    room = CFG['weekly_target'] - len(active)
    planned = []
    for order, (rec, info) in enumerate(sel['items']):
        if room <= 0:
            break
        if _op(rec).get('week') == week:
            continue

        def mutate(row, booking, op, info=info, order=order):
            prev_week, prev_status, prev_lane = op.get('week'), op.get('status'), op.get('lane')
            keep = prev_lane == info['lane'] and prev_status in ('ready', 'approved') and (op.get('message') or op.get('draft')
                                                                                            or info['lane'] in ('sessionize', 'find'))
            for k in ('skip', 'error', 'tries'):
                op.pop(k, None)
            op.update({'week': week, 'person': person, 'lane': info['lane'], 'fit': info['fit'], 'flags': info['flags'],
                       'urgent': info['urgent'], 'closes': info['closes'], 'major': info['major'], 'call': info['call'],
                       'order': order, 'planned_at': _now(),
                       'carried': bool(prev_week and prev_week != week and prev_status in ('ready', 'approved')),
                       'status': prev_status if keep else 'planned'})
            if not keep:
                op.pop('message', None)
                op.pop('draft', None)
            return {}
        _change(rec['_table'], rec['_key'], mutate)
        planned.append({'event': rec.get('name'), 'lane': info['lane'], 'start': rec.get('start_date')})
        room -= 1
    return {'ok': True, 'week': week, 'person': person, 'planned_now': len(planned), 'already': len(active),
            'eligible': sel['eligible'], 'shortfall': max(0, CFG['weekly_target'] - len(active) - len(planned)),
            'left_out': sel['left_out'], 'planned': planned}


def prepare_one(rec, person, model=None, research=None):
    """Find a contact if needed, then draft. Returns a short result line."""
    t = today()
    op = _op(rec)
    lane = op.get('lane') or core.lane_for(rec, t, sz.sessionize_link)
    table, key = rec['_table'], rec['_key']
    result = {'event': rec.get('name'), 'lane': lane}
    patch_fields = {}
    if lane == 'find':
        c = (research or research_contact)(rec) if not core.contact(rec) else None
        if c:
            patch_fields = {'poc_name': c.get('full_name') or '', 'poc_email': c.get('email') or '',
                            'poc_linkedin': c.get('linkedin_url') or '',
                            'poc_note': core.clip('%s. Found by the weekly prep, check before sending. Source: %s' % (
                                c.get('role') or 'Organiser contact', c.get('source_url')), 480),
                            'poc_lookup_at': _now()}
            rec.update(patch_fields)
        else:
            patch_fields = {'poc_lookup_at': _now()}
        lane = core.lane_for(rec, t, sz.sessionize_link)
        result['contact_found'] = bool(c)
    content = {}
    if lane == 'sessionize':
        r = sz.make_draft(table=table, key=key, by='Event operator', model=model)
        if not r.get('ok'):
            if 'closed' in str(r.get('error', '')).lower():
                c = core.contact(rec) or {}
                lane = 'linkedin' if c.get('linkedin') else ('email' if c.get('email') else 'find')
            else:
                raise RuntimeError(r.get('error') or 'Sessionize draft failed')
    if lane == 'form':
        content['draft'] = draft_form(rec, person, model)
    if lane in ('linkedin', 'email'):
        content['message'] = draft_message(rec, person, model)

    def mutate(row, booking, op2):
        op2.update(content)
        op2.update({'lane': lane, 'status': 'ready', 'prepared_at': _now()})
        op2.pop('error', None)
        return dict(patch_fields)
    _change(table, key, mutate)
    result['lane'] = lane
    result['status'] = 'ready'
    return result


def prepare(person='thor', limit=3, model=None, research=None):
    week = core.week_id(today())
    recs = load()
    todo = [r for r in recs if _op(r).get('week') == week and _op(r).get('person') == person and (
        _op(r).get('status') == 'planned' or (_op(r).get('status') == 'error' and int(_op(r).get('tries') or 0) < 2))]
    todo.sort(key=lambda r: (_op(r).get('order', 99), r.get('start_date') or ''))
    done = []
    for rec in todo[:max(1, min(6, limit))]:
        try:
            done.append(prepare_one(rec, person, model, research))
        except Exception as e:  # noqa: BLE001 - one bad event must not stop the batch
            msg = str(e)[:300]

            def mark(row, booking, op, msg=msg):
                op.update({'status': 'error', 'error': msg, 'tries': int(op.get('tries') or 0) + 1})
                return {}
            try:
                _change(rec['_table'], rec['_key'], mark)
            except Exception:  # noqa: BLE001
                pass
            done.append({'event': rec.get('name'), 'status': 'error', 'error': msg})
    return {'ok': True, 'week': week, 'prepared': done, 'remaining': max(0, len(todo) - len(done))}


# ── The screen ─────────────────────────────────────────────────────────────
def _basics(rec):
    return {'table': rec['_table'], 'key': rec['_key'], 'name': rec.get('name') or '',
            'dates': rec.get('date_str') or rec.get('start_date') or '', 'start': rec.get('start_date') or '',
            'place': rec.get('city') or rec.get('location') or '', 'url': rec.get('url') or '',
            'unassigned': bool(rec.get('_unassigned')), 'linkedin_search': core.linkedin_search_url(rec)}


def _item_view(rec, t):
    op = _op(rec)
    c = core.contact(rec)
    lane = op.get('lane') or ''
    v = _basics(rec)
    v.update({'lane': lane, 'status': op.get('status') or 'planned', 'fit': op.get('fit') or '',
              'flags': op.get('flags') or [], 'major': bool(op.get('major')), 'urgent': bool(op.get('urgent')),
              'closes': op.get('closes') or '', 'carried': bool(op.get('carried')), 'error': op.get('error') or '',
              'contact': c, 'apply_link': core.apply_link(rec), 'sessionize': sz.sessionize_link(rec),
              'linkedin_search': core.linkedin_search_url(rec), 'sent': op.get('sent'), 'skip': op.get('skip'),
              'approved_at': op.get('approved_at') or '', 'queued_for_claude': rec.get('decision') in ('apply', 'approved')})
    if lane == 'sessionize':
        v['draft'] = (rec.get('booking') or {}).get('sessionize_draft')
    elif lane == 'form':
        v['draft'] = op.get('draft')
    m = op.get('message')
    if m:
        v['message'] = m
        if c and c.get('email'):
            v['gmail'] = core.gmail_url(c['email'], m.get('email_subject'), m.get('email_body'))
    return v


def _live_view(item, kind, person):
    rec = item['rec']
    c = core.contact(rec)
    v = _basics(rec)
    r = core.receipts(rec)
    v['receipt'] = r[0] if r else None
    v['contact'] = c
    if kind == 'attending':
        v['role'] = item['role']
    elif kind in ('out', 'follow_ups'):
        v.update({k: item[k] for k in ('stage', 'last_touch', 'waiting_days', 'follow_up_on', 'hold')})
        if kind == 'follow_ups':
            v['text'] = core.follow_up_text(rec, c)
            v['channel'] = 'linkedin' if c and c.get('linkedin') else ('email' if c and c.get('email') else '')
            if c and c.get('email'):
                v['gmail'] = core.gmail_url(c['email'], 'Re: speaking at ' + (rec.get('name') or ''), v['text'])
    elif kind == 'losses':
        v['rejected_on'] = item['rejected_on']
        v['text'] = core.loss_text(rec, c)
        v['channel'] = 'linkedin' if c and c.get('linkedin') else ('email' if c and c.get('email') else '')
        if c and c.get('email'):
            v['gmail'] = core.gmail_url(c['email'], 'Thank you: ' + (rec.get('name') or ''), v['text'])
    elif kind == 'needs_record':
        v['stage'] = item['stage']
    return v


def week_view(person='thor'):
    t = today()
    week = core.week_id(t)
    recs = load()
    batch = [r for r in recs if _op(r).get('week') == week and _op(r).get('person') == person]
    items = [_item_view(r, t) for r in batch]
    items.sort(key=lambda x: (x['start'] or '9999', x['name'].lower()))
    live = core.live_lists(recs, t, CFG, person)
    out = {'ok': True, 'person': person, 'week': week, 'today': t.isoformat(), 'planned': bool(batch),
           'target': CFG['weekly_target'], 'linkedin_note_max': CFG['linkedin_note_max'],
           'items': [i for i in items if i['status'] != 'skipped'],
           'skipped': [i for i in items if i['status'] == 'skipped'],
           'skip_reasons': {k: v[0] for k, v in core.SKIP_REASONS.items()}}
    if not batch:
        # Before the week is prepared: who would be picked, without writing anything.
        sel = core.select_week(recs, t, CFG, person, sz.sessionize_link)
        out['preview'] = {'eligible': sel['eligible'], 'left_out': sel['left_out'],
                          'items': [dict(_basics(r), lane=i['lane'], fit=i['fit'], flags=i['flags'], major=i['major'])
                                    for r, i in sel['items']]}
    for kind in ('attending', 'out', 'follow_ups', 'losses', 'needs_record'):
        out[kind] = [_live_view(i, kind, person) for i in live[kind]]
    out['counts'] = {
        'ready': sum(1 for i in out['items'] if i['status'] in ('ready', 'approved')),
        'preparing': sum(1 for i in out['items'] if i['status'] in ('planned', 'error')),
        'sent': sum(1 for i in out['items'] if i['status'] == 'sent'),
        'attending': len(out['attending']), 'out': len(out['out']), 'follow_ups': len(out['follow_ups']),
        'losses': len(out['losses']), 'needs_record': len(out['needs_record'])}
    return out


# ── Actions from the screen ────────────────────────────────────────────────
_EDITABLE = {'message': ('linkedin_note', 'linkedin_message', 'email_subject', 'email_body'),
             'draft': ('title', 'short_abstract', 'abstract')}


def _who(body):
    return core.clip(re.sub(r'[^\w .\'-]', '', str(body.get('by') or 'Thor')), 40) or 'Thor'


def _person_name(person):
    return person[:1].upper() + person[1:]


def act(body):
    action = str(body.get('action') or '')
    table, key = str(body.get('table') or ''), body.get('key')
    by = _who(body)
    day = today().isoformat()
    if action == 'approve':
        n = 0
        for it in body.get('items') or []:
            tb, k = str(it.get('table') or ''), it.get('key')
            if tb not in ('event_state', 'manual_events'):
                continue

            def m(row, booking, op):
                if op.get('status') not in ('ready', 'approved'):
                    return {}
                op.update({'status': 'approved', 'approved_at': _now(), 'approved_by': by})
                # Forms and emails go to Claude's event-apply skill, the same
                # hand-off as "Apply for me" in the event pop-up.
                return {'decision': 'apply'} if op.get('lane') in ('sessionize', 'form', 'email') else {}
            _change(tb, k, m)
            n += 1
        return {'ok': True, 'approved': n}
    if table not in ('event_state', 'manual_events') or key in (None, ''):
        raise ValueError('table and key are required')
    if action == 'edit':
        part, field = str(body.get('part') or 'message'), str(body.get('field') or '')
        if field not in _EDITABLE.get(part, ()):
            raise ValueError('that field cannot be edited here')
        value = core.no_dashes(str(body.get('value') or ''))[:5000]

        def m(row, booking, op):
            if part == 'draft' and op.get('lane') == 'sessionize':
                d = dict(booking.get('sessionize_draft') or {})
                d[field] = value
                booking['sessionize_draft'] = d
            else:
                d = dict(op.get(part) or {})
                d[field] = value
                op[part] = d
            op['edited'] = sorted(set((op.get('edited') or []) + [field]))
            return {}
        _change(table, key, m)
        return {'ok': True}
    if action in ('sent', 'submitted', 'followup_sent', 'loss_sent'):
        channel = str(body.get('channel') or '')[:20]
        text = str(body.get('text') or '')[:4000]
        to = core.clip(str(body.get('to') or ''), 200)
        stage = {'sent': 'Initial outreach', 'submitted': 'Submitted', 'followup_sent': 'Followed up'}.get(action)
        notes = {'sent': '%s to %s' % ('LinkedIn note' if channel == 'linkedin' else 'Email', to or 'the organiser'),
                 'followup_sent': 'Follow-up %s to %s' % ('on LinkedIn' if channel == 'linkedin' else 'email', to or 'the organiser'),
                 'loss_sent': 'Thank-you note after the decision, to %s' % (to or 'the organiser')}

        def m(row, booking, op):
            patch = {}
            tags = core.raw_stages(row)
            if stage:
                patch['status_tags'] = core.with_stage(tags, stage)
            note = notes.get(action)
            if action == 'submitted':
                how = 'Sessionize' if channel == 'sessionize' else "the event's form"
                d = booking.get('sessionize_draft') if channel == 'sessionize' else op.get('draft')
                title = (d or {}).get('title') or ''
                note = 'Applied on %s%s' % (how, (' with "%s"' % title) if title else '')
                patch['submitted_at'] = day
            patch['follow_ups'] = _follow(row, {'on': day, 'by': by, 'note': note, 'channel': channel or 'other',
                                                'to': to, 'text': text})
            if not str(row.get('speaker') or '').strip():
                patch['speaker'] = _person_name(op.get('person') or core.DEFAULTS['person'])
            if action in ('sent', 'submitted'):
                op.update({'status': 'sent', 'sent': {'channel': channel, 'to': to, 'text': text, 'at': _now(), 'by': by}})
                if row.get('decision') in ('apply', 'approved'):
                    patch['decision'] = ''
            if action == 'loss_sent':
                op['loss_sent'] = day
            return patch
        _change(table, key, m)
        return {'ok': True}
    if action == 'outcome':
        outcome = str(body.get('outcome') or '')
        stage = {'meeting': 'Meeting held', 'booked': 'Booked', 'rejected': 'Rejected'}.get(outcome)
        if outcome not in ('replied', 'meeting', 'booked', 'rejected'):
            raise ValueError('outcome must be replied, meeting, booked or rejected')
        note = core.clip(str(body.get('note') or ''), 600)
        label = {'replied': 'They replied', 'meeting': 'Meeting held', 'booked': 'Booked to speak',
                 'rejected': 'They said no'}[outcome]

        def m(row, booking, op):
            patch = {}
            if stage:
                tags = core.raw_stages(row)
                patch['status_tags'] = core.with_stage(tags, stage)
            if outcome == 'booked':
                booking['speaking_booked_at'] = booking.get('speaking_booked_at') or day
            op['outcome'] = {'outcome': outcome, 'at': day, 'by': by, 'note': note}
            patch['follow_ups'] = _follow(row, {'on': day, 'by': by, 'note': label + (': ' + note if note else ''),
                                                'channel': 'reply'})
            return patch
        _change(table, key, m)
        return {'ok': True}
    if action in ('skip', 'unskip'):
        reason = str(body.get('reason') or '')
        if action == 'skip' and reason not in core.SKIP_REASONS:
            raise ValueError('pick a reason')

        def m(row, booking, op):
            if action == 'skip':
                archive = core.SKIP_REASONS[reason][1]
                op.update({'status': 'skipped', 'skip': {'reason': reason, 'at': _now(), 'by': by, 'archived': archive}})
                return {'hidden': True} if archive else {}
            was = op.pop('skip', None) or {}
            op['status'] = 'ready' if (op.get('message') or op.get('draft') or op.get('lane') in ('sessionize', 'find')) else 'planned'
            return {'hidden': False} if was.get('archived') else {}
        _change(table, key, m)
        return {'ok': True}
    if action == 'contact':
        name = core.clip(str(body.get('name') or ''), 120)
        li = str(body.get('linkedin') or '').strip()
        email = str(body.get('email') or '').strip().lower()
        if li and not li.startswith('http'):
            li = 'https://' + li
        if li and not core._LI.match(li):
            raise ValueError('That is not a LinkedIn profile link (linkedin.com/in/...).')
        if email and not core._EMAIL.fullmatch(email):
            raise ValueError('That email address does not look right.')
        if not (li or email):
            raise ValueError('Add a LinkedIn profile or an email.')
        role = core.clip(str(body.get('role') or ''), 160)
        in_batch = not body.get('save_only')

        def m(row, booking, op):
            if in_batch:
                op.update({'lane': 'linkedin' if li else 'email', 'status': 'planned'})
                op.pop('message', None)
            return {'poc_name': name, 'poc_linkedin': li, 'poc_email': email,
                    'poc_note': core.clip('%sAdded on /week by %s.' % ((role + '. ') if role else '', by), 480),
                    'poc_lookup_at': _now()}
        _change(table, key, m)
        # A contact for something already sent (a follow-up) is just saved; one
        # for this week's batch gets its note drafted straight away.
        return _redraft(table, key) if in_batch else {'ok': True}
    if action == 'redraft':
        return _redraft(table, key)
    if action == 'record':
        how = str(body.get('op') or '')
        when = core.parse_day(body.get('date'))

        def m(row, booking, op):
            tags = core.raw_stages(row)
            if how == 'confirm':
                if not when or when > today():
                    raise ValueError('Pick the date it happened.')
                live = [s for s in core.IN_FLIGHT if s in tags]
                patch = {'follow_ups': _follow(row, {'on': when.isoformat(), 'by': by, 'channel': 'other',
                                                     'note': 'Confirmed by %s: %s (no record from the time)' % (by, live[-1] if live else 'sent')})}
                if 'Submitted' in tags and not row.get('submitted_at'):
                    patch['submitted_at'] = when.isoformat()
                if body.get('claim') and not str(row.get('speaker') or '').strip():
                    patch['speaker'] = _person_name(core.DEFAULTS['person'])
                return patch
            if how == 'clear':
                return {'status_tags': [s for s in tags if s not in core.IN_FLIGHT]}
            raise ValueError('op must be confirm or clear')
        _change(table, key, m)
        return {'ok': True}
    raise ValueError('unknown action')


def _redraft(table, key):
    recs = [r for r in load() if r['_table'] == table and str(r['_key']) == str(key)]
    if not recs:
        raise LookupError('no such event')
    rec = recs[0]
    res = prepare_one(rec, _person_of(rec, _op(rec)))
    fresh = [r for r in load() if r['_table'] == table and str(r['_key']) == str(key)]
    return {'ok': True, 'result': res, 'item': _item_view(fresh[0], today()) if fresh else None}


def digest(person='thor'):
    w = week_view(person)
    lanes = {}
    for i in w['items']:
        lanes[i['lane']] = lanes.get(i['lane'], 0) + 1
    names = {'sessionize': 'Sessionize', 'form': 'forms', 'linkedin': 'LinkedIn notes', 'email': 'emails',
             'find': 'need a contact'}
    parts = ['%d %s' % (n, names.get(k, k)) for k, n in sorted(lanes.items(), key=lambda x: -x[1])]
    text = ('This week\'s speaking batch for %s: %d events (%s). %d follow-ups due, %d out now, %d to confirm. '
            'Open it: %s/week' % (_person_name(person), len(w['items']), ', '.join(parts) or 'none',
                                  w['counts']['follow_ups'], w['counts']['out'], w['counts']['needs_record'],
                                  TRACKER_BASE))
    posted = False
    if SLACK_WEBHOOK_URL:
        st, _ = _http('POST', SLACK_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, body={'text': text})
        posted = st == 200
    return {'ok': True, 'text': text, 'posted': posted}


# ── HTTP ───────────────────────────────────────────────────────────────────
def _send(handler, status, payload):
    body = json.dumps(payload, default=str).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


def _person(v):
    p = re.sub(r'[^a-z]', '', str(v or '').lower())
    return p if p in core.PROFILES else core.DEFAULTS['person']


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if not sz._same_origin(self):
                return _send(self, 403, {'error': 'forbidden: call from tracker site'})
            if not SERVICE_ROLE:
                return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return _send(self, 200, week_view(_person((q.get('person') or [''])[0])))
        except Exception as e:  # noqa: BLE001 - always answer JSON
            return _send(self, 500, {'error': type(e).__name__, 'msg': str(e)[:300]})

    def do_POST(self):
        try:
            n = min(int(self.headers.get('Content-Length', '0') or '0'), 40000)
            try:
                body = json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}
            except json.JSONDecodeError:
                body = {}
            body = body if isinstance(body, dict) else {}
            keyed, same = sz._authorized(self), sz._same_origin(self)
            action = str(body.get('action') or '')
            if action == 'digest' and not keyed:
                return _send(self, 401, {'error': 'unauthorized'})
            if not (keyed or same):
                return _send(self, 403, {'error': 'forbidden: call from tracker site'})
            if not SERVICE_ROLE:
                return _send(self, 500, {'error': 'SUPABASE_SERVICE_ROLE_KEY missing'})
            person = _person(body.get('person'))
            if action == 'plan':
                return _send(self, 200, plan(person))
            if action == 'prepare':
                if not OPENAI_API_KEY:
                    return _send(self, 500, {'error': 'OPENAI_API_KEY missing'})
                return _send(self, 200, prepare(person, int(body.get('limit') or 3)))
            if action == 'digest':
                return _send(self, 200, digest(person))
            try:
                return _send(self, 200, act(body))
            except LookupError as e:
                return _send(self, 404, {'ok': False, 'error': str(e)})
            except ValueError as e:
                return _send(self, 400, {'ok': False, 'error': str(e)})
        except Exception as e:  # noqa: BLE001
            return _send(self, 500, {'error': type(e).__name__, 'msg': str(e)[:300]})
