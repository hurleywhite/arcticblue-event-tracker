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
print('Sessionize page reading, link checks and acceptance matching passed.')
