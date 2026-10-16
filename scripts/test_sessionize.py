"""Tests for api/sessionize.py. Run: python3 scripts/test_sessionize.py

The fixtures are cut-down copies of Sessionize's real markup (a call-for-speakers
page and a speaker profile, captured 2026-10-13), so a layout change on their
side shows up here as a failing parse rather than as silently empty data.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'api'))
import sessionize as S  # noqa: E402

CFP = '''<html><head><title>AI DevWorld 2027: Call for Speakers @ Sessionize.com</title></head><body>
<div class="alert alert-danger"><span>Call for Speakers is <strong>closed</strong>. Submissions are no longer possible. Sorry.</span></div>
<div class="ibox-title"><h4>AI DevWorld 2027</h4></div>
<div class="font-bold text-navy"><i class="fal fa-calendar"></i> event starts </div> <h2 class="no-margins">9 Feb 2027</h2>
<div class="font-bold text-navy"><i class="fal fa-calendar"></i> event ends </div> <h2 class="no-margins">11 Feb 2027</h2>
<div class="font-bold text-navy"><i class="fal fa-globe"></i> website </div> <h2 class="no-margins"> <a href="https://www.developerweek.com/ai-devworld/">developerweek.com/ai-devworld/</a></h2>
<span class="font-bold text-navy">Call opens at 12:00 AM</span> </div> <h2 class="no-margins">19 Jun 2026</h2>
<span class="font-bold text-navy">Call closes at 11:59 PM</span> </div> <h2 class="no-margins">18 Sep 2026</h2>
<small class="text-muted"> Call closes in <strong>Pacific Daylight Time (UTC-07:00)</strong> timezone. </small>
</body></html>'''
OPEN_CFP = CFP.replace('<div class="alert alert-danger"><span>Call for Speakers is <strong>closed</strong>. Submissions are no longer possible. Sorry.</span></div>', '')

PROFILE = '''<html><head><title>Thor Ernstsson&#39;s Speaker Profile @ Sessionize</title></head><body>
<div class="c-s-timeline"><div class="c-s-timeline__item"><div class="c-s-event"> <h3 class="c-s-event__title">
 <a class="c-s-event__name" href="https://www.developerweek.com/ai-devworld/" rel="nofollow" target="_blank">AI DevWorld 2027</a>
 <span class="c-s-event__type" title="Sessionize Event"></span></h3>
 <span class="c-s-event__meta c-s-event__meta--date"> February 2027 </span>
 <span class="c-s-event__meta c-s-event__meta--location">Santa Clara, California, United States</span> </div> </div>
<div class="c-s-timeline__item"><div class="c-s-event"> <h3 class="c-s-event__title">
 <span class="c-s-event__name">African Internet Governance Forum 2026</span></h3>
 <span class="c-s-event__meta c-s-event__meta--date"> November 2026 </span>
 <span class="c-s-event__meta c-s-event__meta--location">Nairobi, Kenya</span> </div> </div></div>
</section></body></html>'''
EMPTY_PROFILE = '<html><head><title>Thor Ernstsson&#39;s Speaker Profile @ Sessionize</title></head><body></body></html>'

# What the server may fetch: one clean sessionize.com event or speaker page, nothing else.
assert S.page_url('https://sessionize.com/aidevworld-2027/') == 'https://sessionize.com/aidevworld-2027/'
assert S.page_url('sessionize.com/aidevworld-2027') == 'https://sessionize.com/aidevworld-2027/'
assert S.page_url('http://www.sessionize.com/ndc-london-2027/?x=1#f') == 'https://sessionize.com/ndc-london-2027/'
for bad in ('https://evil.com/sessionize.com/x', 'https://sessionize.com.evil.com/x', 'https://sessionize.com/app/speaker',
            'https://sessionize.com/../etc', 'javascript:alert(1)', 'https://sessionize.com/', ''):
    assert S.page_url(bad) == '', bad

c = S.parse_cfp(CFP, dt.date(2026, 10, 13))
assert c == {'name': 'AI DevWorld 2027', 'status': 'closed', 'opens': '2026-06-19', 'closes': '2026-09-18',
             'timezone': 'Pacific Daylight Time (UTC-07:00)', 'event_start': '2027-02-09',
             'event_end': '2027-02-11', 'website': 'https://www.developerweek.com/ai-devworld/'}, c
assert S.parse_cfp(OPEN_CFP, dt.date(2026, 7, 1))['status'] == 'open'
assert S.parse_cfp(OPEN_CFP, dt.date(2026, 6, 1))['status'] == 'not_open_yet'
assert S.parse_cfp(OPEN_CFP, dt.date(2026, 9, 19))['status'] == 'closed'      # past the closing date
assert S.parse_cfp(PROFILE) is None and S.parse_cfp('<html><title>Not found</title></html>') is None

p = S.parse_profile(PROFILE)
assert p['name'] == 'Thor Ernstsson' and len(p['events']) == 2, p
assert p['events'][0] == {'name': 'AI DevWorld 2027', 'url': 'https://www.developerweek.com/ai-devworld/',
                          'date': 'February 2027', 'location': 'Santa Clara, California, United States'}
assert p['events'][1]['url'] == ''                      # an event with no website link still parses
assert S.parse_profile(EMPTY_PROFILE) == {'name': 'Thor Ernstsson', 'events': []}
assert S.parse_profile(CFP) is None

# Matching is strict: a wrong match would mark an event Booked that is not.
E = lambda name, date='': {'name': name, 'date': date}
assert S.same_event(E('AI DevWorld 2027', 'February 2027'), 'AI DevWorld', '2027-02-09')
assert S.same_event(E('AI DevCon Fall 2026', 'November 2026'), 'AI DevCon Fall', '2026-11-02')
assert S.same_event(E('African Internet Governance Forum 2026', 'November 2026'),
                    '15th African Internet Governance Forum (AfIGF 2026)', '2026-11-02')
assert S.same_event(E('AI DevWorld 2027', 'January 2027'), 'AI DevWorld', '2027-02-09')        # a month either side
assert not S.same_event(E('AI DevWorld 2027', 'February 2027'), 'AI DevWorld', '2026-02-09')    # last year's edition
assert not S.same_event(E('AI Summit New York', 'December 2026'), 'AI Summit', '2026-12-09')    # too loose
assert not S.same_event(E('DevWorld', 'February 2027'), 'AI DevWorld', '2027-02-09')            # one word proves nothing
assert not S.same_event(E('AI DevWorld 2027', 'February 2027'), 'ProductWorld', '2027-02-09')
assert S.same_event(E('AI DevWorld'), 'AI DevWorld', '')                                        # no dates: exact name only
assert not S.same_event(E('AI DevWorld West'), 'AI DevWorld', '')

rows = [
    {'table': 'manual_events', 'key': 'a', 'name': 'AI DevWorld', 'speaker': 'Thor', 'tags': ['Submitted', 'Followed up'], 'start_date': '2027-02-09'},
    {'table': 'manual_events', 'key': 'b', 'name': 'AI DevWorld', 'speaker': 'Verma', 'tags': ['Submitted'], 'start_date': '2027-02-09'},   # someone else's
    {'table': 'manual_events', 'key': 'c', 'name': 'AI DevWorld', 'speaker': 'Thor', 'tags': ['Submitted', 'Booked'], 'start_date': '2027-02-09'},  # already booked
    {'table': 'manual_events', 'key': 'd', 'name': 'AI DevWorld', 'speaker': 'Thor', 'tags': [], 'start_date': '2027-02-09'},                # never applied
    {'table': 'event_state', 'key': 7, 'name': '15th African Internet Governance Forum (AfIGF 2026)', 'speaker': 'Thor', 'tags': ['Submitted', 'Rejected'], 'start_date': '2026-11-02'},
]
book, conflicts = S.find_acceptances('thor', p['events'], rows)
assert [h['row']['key'] for h in book] == ['a'], book
assert [h['row']['key'] for h in conflicts] == [7]       # marked Rejected by hand: reported, never overwritten
assert S.find_acceptances('thor', [], rows) == ([], [])
assert S.booked_tags(['Submitted', 'Initial outreach', 'Followed up']) == ['Submitted', 'Booked']
assert S.booked_tags(['Submitted', 'Rejected']) == ['Submitted', 'Booked']
assert S.booked_tags(None) == ['Booked']

# ── Drafting an application ────────────────────────────────────────────────
# A cut-down open call (AI Summit NA 2027, captured 2026-10-16): themes in the
# organiser's text, the perks box, a paid-travel line added to test the flags.
OPEN = """<html><head><title>AI Summit NA 2027: Call for Speakers @ Sessionize.com</title></head><body>
<a>Sessionize.com</a><a>Log in</a>
<div class="font-bold text-navy"><i class="fal fa-calendar"></i> event starts </div> <h2 class="no-margins">30 Mar 2027</h2>
<div class="font-bold text-navy"><i class="fal fa-calendar"></i> event ends </div> <h2 class="no-margins">1 Apr 2027</h2>
<span class="font-bold text-navy">Call opens at 7:00 AM</span> </div> <h2 class="no-margins">28 Sep 2026</h2>
<span class="font-bold text-navy">Call closes at 12:00 PM</span> </div> <h2 class="no-margins">04 Dec 2026</h2>
<small class="text-muted"> Call closes in <strong>Pacific Standard Time (UTC-08:00)</strong> timezone. </small>
<script>var x = "Submit a session";</script>
<p>Main Stage Themes for Inspiration:<br>Business Process Reimagination<br>Change Management Strategies &amp; Execution</p>
<p>Speakers must attend in-person in San Diego.</p>
<div class="col-sm-4 m-b-md"><h3 class="no-margins font-normal">event fee</h3> <div class="font-bold text-navy">$499 speaker package</div></div>
<div class="col-sm-4 m-b-md"><h3 class="no-margins font-normal">travel</h3> <div class="font-bold text-navy">not covered</div></div>
<button>Submit a session</button> <p>Login with your preferred account</p> <p>Classic login</p>
</body></html>"""

assert S.sessionize_link({'apply_url': '', 'notes': 'Apply at https://sessionize.com/ai-summitna-2027/.'}) == 'https://sessionize.com/ai-summitna-2027/'
assert S.sessionize_link({'url': 'https://example.com'}, {'speaking_route': 'sessionize.com/app/speaker'}) == ''
assert S.sessionize_link({}, {'speaking_route': 'CFP: https://sessionize.com/boshug/'}) == 'https://sessionize.com/boshug/'

det = S.cfp_details(OPEN)
assert det['perks'] == {'event fee': '$499 speaker package', 'travel': 'not covered'}, det['perks']
assert 'Business Process Reimagination' in det['text'] and 'Change Management' in det['text']
assert 'Classic login' not in det['text'] and 'var x' not in det['text'] and not det['text'].startswith('Sessionize.com')
flags = S.term_flags(det)
assert [f['kind'] for f in flags] == ['fee', 'travel', 'in_person'], flags
assert S.term_flags(S.cfp_details(OPEN.replace('$499 speaker package', 'free for speakers')
                                  .replace('not covered', 'covered').replace('must attend in-person', 'attend')))== []

LIB = {'speaker': {'name': 'Thor Ernstsson', 'facts': ['Has led more than 20,000 enterprise experiments.'], 'voice': 'Direct.'},
       'talks': [{'id': 'fail-or-scale', 'status': 'draft', 'title': 'Fail or Scale', 'abstract': 'Pilots vs experiments.',
                  'short_abstract': 'Short.', 'level': 'Intermediate', 'takeaways': ['a', 'b', 'c']},
                 {'id': 'safely', 'status': 'approved', 'title': 'Safely', 'abstract': 'Governance.', 'takeaways': ['x']}]}
c = S.clean_draft({'talk_id': 'nope', 'title': ' Fail or Scale  for Builders ', 'takeaways': ['one', '', 3],
                   'answers': [{'question': 'Why you?', 'answer': 'Because.'}, {'question': 'Empty'}],
                   'terms': [{'kind': 'weird', 'text': 'Recording consent'}], 'fit': 'great'}, LIB)
assert c['talk_id'] == 'fail-or-scale' and c['talk_status'] == 'draft'      # unknown talk -> the first one, never made up
assert c['title'] == 'Fail or Scale for Builders' and c['takeaways'] == ['one'] and c['fit'] == 'fair'
assert c['answers'] == [{'question': 'Why you?', 'answer': 'Because.'}]
assert c['terms'] == [{'kind': 'other', 'text': 'Recording consent', 'why_it_matters': ''}]
assert S.clean_draft(None, LIB)['abstract'] == 'Pilots vs experiments.'     # a broken answer falls back to the talk
chk = S.number_checks({'abstract': 'Over 20,000 experiments and 37% faster.', 'takeaways': ['in 2027']},
                      'more than 20,000 experiments, event 2027')
assert chk == ['Check this number, it is not in the talk, the bio or the call: 37'], chk

# make_draft end to end, with the network and the model replaced.
calls = []
def fake_http(method, url, headers=None, body=None):
    calls.append((method, url, body))
    if '/storage/' in url:
        return 400, 'not found'
    if url.endswith('events.json'):
        return 200, {'events': [{'num': 42, 'name': 'AI Summit NA 2027', 'date_str': 'Mar 30-Apr 1, 2027',
                                 'location': 'San Diego', 'speaking_route': 'https://sessionize.com/ai-summitna-2027/'}]}
    if '/rest/v1/event_state?event_num=eq.42' in url and method == 'GET':
        return 200, [{'event_num': 42, 'speaker': 'Thor', 'booking': {'next_action': 'keep me'}}]
    return 204, None
def fake_model(messages):
    assert 'AI Summit NA 2027' in messages[1]['content'] and 'Business Process Reimagination' in messages[1]['content']
    assert '[ASK THOR' in messages[0]['content']
    return {'talk_id': 'fail-or-scale', 'fit': 'strong', 'title': 'Fail or Scale: Reimagining Business Processes',
            'abstract': 'Pilots are built to succeed; 37 of them failed.', 'takeaways': ['a', 'b', 'c'],
            'terms': [{'kind': 'fee', 'text': 'duplicate of the perks box'}, {'kind': 'recording', 'text': 'Sessions are recorded'}]}, 'fake-model'
assert S._merge_terms([], [{'kind': 'fee', 'text': 'event fee: free for speakers', 'why_it_matters': ''},
                           {'kind': 'fee', 'text': 'Free pass, but a $99 booking fee', 'why_it_matters': ''}]) == \
    [{'kind': 'fee', 'text': 'Free pass, but a $99 booking fee', 'why_it_matters': ''}]
S._http, S.fetch, S.SERVICE_ROLE = fake_http, (lambda url: (200, OPEN)), 'svc'
S.ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
r = S.make_draft('event_state', 42, dry_run=True, by='Hurley', model=fake_model, today=dt.date(2026, 10, 16))
d = r['draft']
assert r['ok'] and r['written'] is False and r['dry_run']
assert not [x for x in calls if x[0] in ('PATCH', 'POST')]                 # dry run: nothing saved
assert d['library'] == 'starting set' and d['person'] == 'thor' and d['talk_status'] == 'draft'
assert d['cfp'] == {'url': 'https://sessionize.com/ai-summitna-2027/', 'status': 'open', 'closes': '2026-12-04',
                    'timezone': 'Pacific Standard Time (UTC-08:00)'}
assert [t['kind'] for t in d['terms']] == ['fee', 'travel', 'in_person', 'recording'], d['terms']   # the perks box wins over the model's fee
assert any('still a draft' in x for x in d['checks']) and any(x.endswith(': 37') for x in d['checks']), d['checks']
calls.clear()
r = S.make_draft('event_state', 42, by='Hurley', model=fake_model, today=dt.date(2026, 10, 16))
w = [x for x in calls if x[0] == 'PATCH']
assert r['written'] and len(w) == 1 and 'event_num=eq.42' in w[0][1]
assert w[0][2]['booking']['next_action'] == 'keep me'                      # the rest of the booking survives
assert w[0][2]['booking']['sessionize_draft']['title'] == 'Fail or Scale: Reimagining Business Processes'
assert S.make_draft(cfp_url='https://sessionize.com/ai-summitna-2027/', model=fake_model)['ok'] is False   # no event: dry run only
assert S.make_draft(cfp_url='https://evil.com/x', dry_run=True, model=fake_model)['ok'] is False
S.fetch = lambda url: (200, CFP)            # AI DevWorld: closed, so no model call and nothing saved
calls.clear()
r = S.make_draft('event_state', 42, model=lambda m: (_ for _ in ()).throw(AssertionError('no model call')))
assert r == {'ok': False, 'error': 'The call for speakers closed on 2026-09-18.'} and not [x for x in calls if x[0] != 'GET'], r
print('Sessionize page reading, link checks, acceptance matching and drafting passed.')
