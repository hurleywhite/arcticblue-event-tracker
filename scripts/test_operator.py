"""Tests for the event operator (api/_operator_core.py and api/operator.py).

Run: python3 -m unittest scripts/test_operator.py

The API tests run against an in-memory stand-in for Supabase, so nothing here
touches the network or the real database.
"""
import copy
import datetime as dt
import json
import os
import re
import sys
import unittest
import urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)

from api import _operator_core as core  # noqa: E402
from api import operator as opx  # noqa: E402
from api import sessionize as sz  # noqa: E402

TODAY = dt.date(2026, 11, 5)
D = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()  # noqa: E731


def ev(num, name, days, **kw):
    base = {'num': num, 'name': name, 'start_date': D(days), 'end_date': D(days + 1), 'date_str': D(days),
            'location': 'New York, NY', 'city': 'New York', 'country': 'USA', 'region': 'US & Canada',
            'type': 'Enterprise', 'priority': 'Medium', 'url': 'https://example.com/%d' % num,
            'about': 'Healthcare executives and health system leaders deploying AI.',
            'audience_type': 'Buyer-rich', 'status': 'upcoming'}
    base.update(kw)
    return base


class CoreSelection(unittest.TestCase):
    def recs(self, catalog, states=(), manuals=()):
        return core.merge(catalog, list(states), list(manuals))

    def test_fit_and_lanes(self):
        cat = [
            ev(1, 'HLTH Health Systems AI Forum', 120, apply_url='https://hlth.example/speak'),
            ev(2, 'Payer AI Summit', 150, contact_info='Jane Doe (Producer) https://www.linkedin.com/in/janedoe'),
            ev(3, 'Digital Health Leaders', 200, contact_info='Bob Smith, bob@example.org'),
            ev(4, 'Pharma Commercial AI', 210),
            ev(5, 'Retail Media Expo', 120, about='Retail marketers and agencies', audience_type='Mixed'),
        ]
        sel = core.select_week(self.recs(cat), TODAY, {}, 'thor')
        lanes = {r['name']: i['lane'] for r, i in sel['items']}
        self.assertEqual(lanes['HLTH Health Systems AI Forum'], 'form')
        self.assertEqual(lanes['Payer AI Summit'], 'linkedin')
        self.assertEqual(lanes['Digital Health Leaders'], 'email')
        self.assertEqual(lanes['Pharma Commercial AI'], 'find')
        self.assertNotIn('Retail Media Expo', lanes)
        self.assertEqual(sel['left_out'].get('not a fit'), 1)

    def test_exclusions(self):
        cat = [
            ev(1, 'Healthcare CHRO Assembly', 120),
            ev(2, 'AIMed Global Summit', 120),
            ev(3, 'Healthcare AI Lagos', 120, location='Lagos, Nigeria', city='Lagos', country='Nigeria'),
            ev(4, 'Foro de Salud Digital', 120),
            ev(5, 'Healthcare Sponsors Only Summit', 120, pay_to_play='Yes', speaking_route='Sponsor packages include speaking'),
            ev(6, 'Healthcare Mixed Summit', 120, pay_to_play='Both', apply_url='https://x.example/apply'),
            ev(7, 'Healthcare Too Soon', 30, contact_info='a@b.com'),
            ev(8, 'Healthcare Far Away', 400, apply_url='https://x.example/apply'),
            ev(9, "Verma's Healthcare Event", 120, speaker='Verma', apply_url='https://x.example/apply'),
        ]
        sel = core.select_week(self.recs(cat), TODAY, {}, 'thor')
        names = [r['name'] for r, _ in sel['items']]
        self.assertEqual(names, ['Healthcare Mixed Summit'])
        self.assertIn('Mixed: check the free route', sel['items'][0][1]['flags'])
        lo = sel['left_out']
        for why in ('HR or L&D', 'clinician audience', 'Africa', 'not in English', 'pay to play',
                    'too soon for outreach', 'more than 12 months out', "another speaker's"):
            self.assertIn(why, lo, why)

    def test_cap_urgent_first_then_date_order(self):
        cat = [ev(i, 'Healthcare Summit %d' % i, 30 + i * 5, apply_url='https://x.example/%d' % i) for i in range(1, 41)]
        cat.append(ev(99, 'Healthcare Late Call', 330, apply_url='https://x.example/late', deadline=D(10)))
        sel = core.select_week(self.recs(cat), TODAY, {'weekly_target': 30}, 'thor')
        names = [r['name'] for r, _ in sel['items']]
        self.assertEqual(len(names), 30)
        self.assertIn('Healthcare Late Call', names)              # urgent call pulled in
        starts = [r['start_date'] for r, _ in sel['items']]
        self.assertEqual(starts, sorted(starts))                    # shown in date order
        self.assertEqual(sel['eligible'], 41)

    def test_broad_fill_after_profile(self):
        cat = [ev(1, 'Healthcare AI Forum', 100, apply_url='https://x.example/1'),
               ev(2, 'Chief AI Officer Summit', 90, about='For enterprise AI executives', apply_url='https://x.example/2')]
        sel = core.select_week(self.recs(cat), TODAY, {'weekly_target': 1}, 'thor')
        self.assertEqual(sel['items'][0][0]['name'], 'Healthcare AI Forum')
        sel = core.select_week(self.recs(cat), TODAY, {'weekly_target': 2}, 'thor')
        broad = [i for r, i in sel['items'] if r['name'] == 'Chief AI Officer Summit'][0]
        self.assertIn('Broader fit', broad['flags'])

    def test_in_flight_and_skips(self):
        cat = [ev(1, 'Healthcare A', 100, apply_url='https://x.example/1'),
               ev(2, 'Healthcare B', 100, apply_url='https://x.example/2'),
               ev(3, 'Healthcare C', 100, apply_url='https://x.example/3')]
        states = [{'event_num': 1, 'status_tags': ['Submitted']},
                  {'event_num': 2, 'booking': {'operator': {'status': 'skipped', 'skip': {'reason': 'not_fit'}}}},
                  {'event_num': 3, 'booking': {'operator': {'status': 'skipped', 'skip': {'reason': 'not_this_week'}}}}]
        sel = core.select_week(self.recs(cat, states), TODAY, {}, 'thor')
        self.assertEqual([r['name'] for r, _ in sel['items']], ['Healthcare C'])

    def test_sessionize_lane_and_closed_call(self):
        link = lambda r: sz.sessionize_link(r)  # noqa: E731
        cat = [ev(1, 'Healthcare Conf', 150, apply_url='https://sessionize.com/healthconf-2027/'),
               ev(2, 'Healthcare Closed', 150, apply_url='https://sessionize.com/closed-2027/',
                  contact_info='https://www.linkedin.com/in/someone')]
        states = [{'event_num': 2, 'booking': {'sessionize_call': {'status': 'closed', 'closes': D(-3)}}}]
        recs = self.recs(cat, states)
        self.assertEqual(core.lane_for(recs[0], TODAY, link), 'sessionize')
        self.assertEqual(core.lane_for(recs[1], TODAY, link), 'linkedin')

    def test_manual_events_merge_and_deleted(self):
        manuals = [{'id': 'm1', 'name': 'Healthcare Manual', 'start_date': D(120), 'apply_url': 'https://x.example/m',
                    'about': 'health system CIOs', 'status_tags': None},
                   {'id': 'm2', 'name': 'Healthcare Gone', 'start_date': D(120), 'status': '__deleted__'}]
        recs = self.recs([], [], manuals)
        self.assertEqual([r['name'] for r in recs], ['Healthcare Manual'])
        self.assertEqual(recs[0]['_table'], 'manual_events')


class CoreStatuses(unittest.TestCase):
    def test_stage_rules(self):
        self.assertEqual(core.imply(['Followed up']), ['Submitted', 'Initial outreach', 'Followed up'])
        self.assertEqual(core.with_stage(['Submitted', 'Initial outreach'], 'Rejected'), ['Submitted', 'Rejected'])
        self.assertEqual(core.with_stage(['Submitted', 'Followed up', 'Rejected'], 'Booked'), ['Submitted', 'Booked'])
        self.assertEqual(core.with_stage([], 'Initial outreach'), ['Initial outreach'])
        self.assertEqual(core.stages_of({'status_tags': None, 'status': 'Meeting held with organiser'}), ['Meeting held'])
        self.assertEqual(core.stages_of({'status_tags': None, 'status': 'upcoming', 'workflow_status': 'Submitted'}),
                         ['Submitted'])

    def test_live_lists(self):
        cat = [
            ev(1, 'Healthcare Booked', 40, speaker='Thor'),
            ev(2, 'Healthcare Quiet', 100, speaker='Thor'),
            ev(3, 'Healthcare Recent', 100, speaker='Thor'),
            ev(4, 'Healthcare No Record', 100),
            ev(5, 'Healthcare Rejected', 100, speaker='Thor'),
            ev(6, 'Verma Thing', 100, speaker='Verma'),
            ev(7, 'Healthcare Hold', 100, speaker='Thor', notes='They are on hold until March'),
        ]
        states = [
            {'event_num': 1, 'status_tags': ['Submitted', 'Booked']},
            {'event_num': 2, 'status_tags': ['Submitted'], 'submitted_at': D(-20)},
            {'event_num': 3, 'status_tags': ['Initial outreach'], 'follow_ups': [{'on': D(-3), 'note': 'LinkedIn note'}]},
            {'event_num': 4, 'status_tags': ['Submitted']},
            {'event_num': 5, 'status_tags': ['Submitted', 'Rejected'],
             'booking': {'operator': {'outcome': {'outcome': 'rejected', 'at': D(-5)}}}},
            {'event_num': 6, 'status_tags': ['Submitted'], 'submitted_at': D(-30)},
            {'event_num': 7, 'status_tags': ['Submitted'], 'submitted_at': D(-30), 'notes': 'They are on hold until March'},
        ]
        live = core.live_lists(core.merge(cat, states, []), TODAY, {}, 'thor')
        self.assertEqual([x['rec']['name'] for x in live['attending']], ['Healthcare Booked'])
        self.assertEqual(live['attending'][0]['role'], 'Speaking')
        self.assertEqual([x['rec']['name'] for x in live['follow_ups']], ['Healthcare Quiet'])
        out = {x['rec']['name'] for x in live['out']}
        self.assertEqual(out, {'Healthcare Quiet', 'Healthcare Recent', 'Healthcare Hold'})
        self.assertEqual([x['rec']['name'] for x in live['needs_record']], ['Healthcare No Record'])
        self.assertTrue(live['needs_record'][0]['rec']['_unassigned'])
        self.assertEqual([x['rec']['name'] for x in live['losses']], ['Healthcare Rejected'])

    def test_follow_up_interval_near_event(self):
        rec = core.merge([ev(1, 'Healthcare Soon', 20, speaker='Thor')],
                         [{'event_num': 1, 'status_tags': ['Submitted'], 'submitted_at': D(-8)}], [])
        live = core.live_lists(rec, TODAY, {}, 'thor')
        self.assertEqual([x['rec']['name'] for x in live['follow_ups']], ['Healthcare Soon'])  # 7 days near the event


class CoreText(unittest.TestCase):
    def test_contact_parsing_never_guesses(self):
        rec = {'contact_info': 'Jay Weintraub (Connectiv Holdings) — jay@connectiv.com'}
        c = core.contact(rec)
        self.assertEqual((c['name'], c['email'], c['linkedin']), ('Jay Weintraub', 'jay@connectiv.com', ''))
        self.assertIsNone(core.contact({'contact_info': 'Ask the organisers'}))
        self.assertEqual(core.contact({'poc_linkedin': 'https://evil.com/in/x'}), None)

    def test_dashes_and_lengths(self):
        self.assertEqual(core.no_dashes('AI — done right, Nov 9–11'), 'AI, done right, Nov 9-11')
        s = core.clip('One sentence here. Two sentences here and more words to cut off', 40)
        self.assertEqual(s, 'One sentence here. Two sentences here')
        self.assertEqual(core.clip('A longer first sentence ends here. Then the rest goes on', 45),
                         'A longer first sentence ends here.')
        m = core.tidy_message({'linkedin_note': 'x' * 260, 'email_body': 'Hi — there', 'linkedin_message': 'Over 50,000 leaders'},
                              core.DEFAULTS, 'facts with 20,000 experiments')
        self.assertLessEqual(len(m['linkedin_note']), 200)
        self.assertNotIn('—', m['email_body'])
        self.assertTrue(any('50000' in c for c in m['checks']))

    def test_urls(self):
        u = core.gmail_url('a@b.com', 'Speaking at X', 'Hi, body & more')
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
        self.assertEqual(q['to'], ['a@b.com'])
        self.assertEqual(q['body'], ['Hi, body & more'])
        self.assertIn('program%20director', core.linkedin_search_url({'name': 'HLTH 2026'}))
        self.assertEqual(core.week_id(TODAY), '2026-W45')

    def test_call_state(self):
        self.assertEqual(core.call_state({'deadline': D(-1)}, TODAY)[0], 'closed')
        self.assertEqual(core.call_state({'deadline': 'Early-bird registration: ' + D(5)}, TODAY)[0], 'unknown')
        self.assertEqual(core.call_state({'deadline': 'CFP closed'}, TODAY)[0], 'closed')
        st, closes = core.call_state({'deadline': 'Dec 1, 2026'}, TODAY)
        self.assertEqual((st, closes), ('open', dt.date(2026, 12, 1)))


# ── The API against an in-memory Supabase ──────────────────────────────────
class FakeDB:
    def __init__(self, catalog, states=(), manuals=()):
        self.catalog = catalog
        self.t = {'event_state': {str(s['event_num']): dict(s) for s in states},
                  'manual_events': {str(m['id']): dict(m) for m in manuals}}
        self.writes = []

    def http(self, method, url, headers=None, body=None, timeout=25):
        u = urllib.parse.urlsplit(url)
        if u.path.endswith('/events.json'):
            return 200, {'events': copy.deepcopy(self.catalog)}
        m = re.match(r'.*/rest/v1/(event_state|manual_events)$', u.path)
        if not m:
            return 404, 'not found'
        table = m.group(1)
        q = urllib.parse.parse_qs(u.query)
        col = 'id' if table == 'manual_events' else 'event_num'
        if method == 'GET':
            rows = list(self.t[table].values())
            if col in q:
                key = q[col][0][3:]
                rows = [r for r in rows if str(r.get(col)) == key]
            return 200, copy.deepcopy(rows)
        self.writes.append((table, copy.deepcopy(body)))
        if table == 'event_state':
            k = str(body['event_num'])
            self.t[table].setdefault(k, {'event_num': body['event_num']}).update(copy.deepcopy(body))
            return 201, None
        k = q['id'][0][3:]
        assert 'updated_by' not in body, 'manual_events must never get updated_by'
        self.t[table][k].update(copy.deepcopy(body))
        return 204, None


def fake_model(messages):
    sys_text = messages[0]['content']
    if 'connection request' in sys_text:
        return {'talk_id': 'fail-or-scale', 'why_this_talk': 'Fits a buyer audience — well.',
                'linkedin_note': 'Hi Jane, I run ArcticBlue and teach leaders to test AI before they scale it. '
                                 'Would a talk on that fit your program? Thor',
                'linkedin_message': 'Fail or Scale: what 20,000 experiments and 70,000 leaders taught us.',
                'email_subject': 'Speaking at the summit', 'email_body': 'Hi Jane, a short note. Thor'}, 'fake'
    return {'talk_id': 'fail-or-scale', 'fit': 'strong', 'title': 'Fail or Scale', 'short_abstract': 'Short.',
            'abstract': 'Long — abstract.', 'answers': [{'question': 'Why you?', 'answer': 'Experience — lots.'}]}, 'fake'


class Api(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, 'config', 'talks', 'thor.json')) as f:
            self.lib = json.load(f)
        self.saved = (opx._http, opx.today, sz.load_talks, sz.fetch, opx.SERVICE_ROLE)
        opx.today = lambda: TODAY
        sz.load_talks = lambda person: (self.lib, 'starting set')
        sz.fetch = lambda url: (200, '<html><body><p>Tell us why you should speak.</p></body></html>')

    def tearDown(self):
        opx._http, opx.today, sz.load_talks, sz.fetch, opx.SERVICE_ROLE = self.saved

    def use(self, db):
        opx._http = db.http

    def test_plan_prepare_view_and_actions(self):
        db = FakeDB([
            ev(1, 'Healthcare Form Event', 120, apply_url='https://form.example/speak'),
            ev(2, 'Healthcare LinkedIn Event', 150, contact_info='Jane Doe https://www.linkedin.com/in/janedoe'),
            ev(3, 'Healthcare Unknown Contact', 160),
        ], states=[{'event_num': 9, 'status_tags': ['Submitted']}],
            manuals=[{'id': 'm1', 'name': 'Healthcare Email Event', 'start_date': D(170), 'status_tags': None,
                      'about': 'health system CIOs', 'poc_email': 'org@example.org', 'poc_name': 'Org Person'}])
        self.use(db)
        p = opx.plan('thor')
        self.assertEqual(p['planned_now'], 4)
        self.assertEqual(opx.plan('thor')['planned_now'], 0)          # idempotent within the week

        found = {'full_name': 'Pat Producer', 'role': 'Programme director', 'email': None,
                 'linkedin_url': 'https://www.linkedin.com/in/patp', 'source_url': 'https://example.com/team'}
        r = opx.prepare('thor', limit=6, model=fake_model, research=lambda rec: found)
        self.assertEqual(r['remaining'], 0)
        self.assertTrue(all(x.get('status') == 'ready' for x in r['prepared']), r)

        w = opx.week_view('thor')
        by = {i['name']: i for i in w['items']}
        self.assertEqual(by['Healthcare Form Event']['lane'], 'form')
        self.assertNotIn('—', by['Healthcare Form Event']['draft']['abstract'])
        self.assertEqual(by['Healthcare Unknown Contact']['lane'], 'linkedin')      # research found someone
        self.assertEqual(by['Healthcare Unknown Contact']['contact']['linkedin'], 'https://www.linkedin.com/in/patp')
        li = by['Healthcare LinkedIn Event']['message']
        self.assertLessEqual(len(li['linkedin_note']), 200)
        self.assertTrue(any('70000' in c for c in li['checks']))                     # unsourced number flagged
        self.assertFalse(any('20000' in c for c in li['checks']))                    # a sourced one is not
        self.assertTrue(any('not approved' in c for c in li['checks']))              # draft talk flagged
        self.assertIn('mail.google.com', by['Healthcare Email Event']['gmail'])

        # Approve all: forms and emails are handed to Claude, LinkedIn is not.
        opx.act({'action': 'approve', 'items': [{'table': i['table'], 'key': i['key']} for i in w['items']]})
        self.assertEqual(db.t['event_state']['1'].get('decision'), 'apply')
        self.assertEqual(db.t['manual_events']['m1'].get('decision'), 'apply')
        self.assertNotEqual(db.t['event_state']['2'].get('decision'), 'apply')

        # Sent on LinkedIn: stage, receipt and speaker, all recorded.
        opx.act({'action': 'sent', 'table': 'event_state', 'key': 2, 'channel': 'linkedin',
                 'to': 'Jane Doe', 'text': li['linkedin_note'], 'by': 'Thor'})
        row = db.t['event_state']['2']
        self.assertEqual(row['status_tags'], ['Initial outreach'])
        self.assertEqual(row['follow_ups'][-1]['text'], li['linkedin_note'])
        self.assertEqual(row['follow_ups'][-1]['on'], TODAY.isoformat())
        self.assertEqual(row['speaker'], 'Thor')
        self.assertEqual(row['booking']['operator']['status'], 'sent')

        # Submitted a form: Submitted + date, decision cleared.
        opx.act({'action': 'submitted', 'table': 'event_state', 'key': 1, 'channel': 'form'})
        row = db.t['event_state']['1']
        self.assertEqual(row['status_tags'], ['Submitted'])
        self.assertEqual(row['submitted_at'], TODAY.isoformat())
        self.assertEqual(row['decision'], '')
        self.assertIn('Applied on the event', row['follow_ups'][-1]['note'])

        # The screen now shows them as out, with receipts.
        w2 = opx.week_view('thor')
        out = {o['name']: o for o in w2['out']}
        self.assertIn('Healthcare LinkedIn Event', out)
        self.assertEqual(out['Healthcare LinkedIn Event']['receipt']['channel'], 'linkedin')
        self.assertEqual(w2['counts']['sent'], 2)

        # Outcome and skip.
        opx.act({'action': 'outcome', 'table': 'event_state', 'key': 1, 'outcome': 'rejected', 'note': 'Full program'})
        self.assertEqual(db.t['event_state']['1']['status_tags'], ['Submitted', 'Rejected'])
        w3 = opx.week_view('thor')
        self.assertEqual([x['name'] for x in w3['losses']], ['Healthcare Form Event'])
        opx.act({'action': 'skip', 'table': 'manual_events', 'key': 'm1', 'reason': 'pays'})
        self.assertTrue(db.t['manual_events']['m1']['hidden'])
        opx.act({'action': 'unskip', 'table': 'manual_events', 'key': 'm1'})
        self.assertFalse(db.t['manual_events']['m1']['hidden'])
        with self.assertRaises(ValueError):
            opx.act({'action': 'skip', 'table': 'manual_events', 'key': 'm1', 'reason': 'whatever'})

    def test_needs_record_confirm_and_clear(self):
        db = FakeDB([ev(1, 'Healthcare Old App', 90), ev(2, 'Healthcare Other Old', 90)],
                    states=[{'event_num': 1, 'status_tags': ['Submitted']},
                            {'event_num': 2, 'status_tags': ['Submitted', 'Initial outreach']}])
        self.use(db)
        self.assertEqual(len(opx.week_view('thor')['needs_record']), 2)
        opx.act({'action': 'record', 'table': 'event_state', 'key': 1, 'op': 'confirm', 'date': D(-40), 'claim': True})
        opx.act({'action': 'record', 'table': 'event_state', 'key': 2, 'op': 'clear'})
        self.assertEqual(db.t['event_state']['1']['submitted_at'], D(-40))
        self.assertEqual(db.t['event_state']['1']['speaker'], 'Thor')
        self.assertEqual(db.t['event_state']['2']['status_tags'], [])
        w = opx.week_view('thor')
        self.assertEqual(w['needs_record'], [])
        self.assertEqual([x['name'] for x in w['follow_ups']], ['Healthcare Old App'])
        with self.assertRaises(ValueError):
            opx.act({'action': 'record', 'table': 'event_state', 'key': 1, 'op': 'confirm', 'date': D(3)})

    def test_edit_and_contact_validation(self):
        db = FakeDB([ev(1, 'Healthcare LinkedIn Event', 150, contact_info='https://www.linkedin.com/in/janedoe')])
        self.use(db)
        opx.plan('thor')
        opx.prepare('thor', model=fake_model)
        opx.act({'action': 'edit', 'table': 'event_state', 'key': 1, 'part': 'message', 'field': 'linkedin_note',
                 'value': 'Edited — note'})
        op = db.t['event_state']['1']['booking']['operator']
        self.assertEqual(op['message']['linkedin_note'], 'Edited, note')
        self.assertEqual(op['edited'], ['linkedin_note'])
        with self.assertRaises(ValueError):
            opx.act({'action': 'edit', 'table': 'event_state', 'key': 1, 'part': 'message', 'field': 'speaker', 'value': 'x'})
        with self.assertRaises(ValueError):
            opx.act({'action': 'contact', 'table': 'event_state', 'key': 1, 'linkedin': 'https://example.com/jane'})

    def test_writes_keep_other_booking_keys(self):
        db = FakeDB([ev(1, 'Healthcare Form Event', 120, apply_url='https://form.example/speak')],
                    states=[{'event_num': 1, 'booking': {'sessionize_call': {'status': 'open'}, 'other': 1}}])
        self.use(db)
        opx.plan('thor')
        b = db.t['event_state']['1']['booking']
        self.assertEqual(b['other'], 1)
        self.assertEqual(b['sessionize_call'], {'status': 'open'})
        self.assertEqual(b['operator']['week'], '2026-W45')


if __name__ == '__main__':
    unittest.main()
