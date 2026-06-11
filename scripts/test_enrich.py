"""Unit tests for the speaking-route enrichment logic in api/events.py.

Run:  python3 scripts/test_enrich.py
No network and no env vars required — Exa is stubbed.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(HERE, '..', 'api', 'events.py')

spec = importlib.util.spec_from_file_location('events_mod', EVENTS)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

passed = 0
failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print('  ok   %s' % label)
    else:
        failed += 1
        print('  FAIL %s' % label)


print('1) classifier: the 3 validated apply links are APPLY (not attend-only)')
APPLY = [
    ('https://ai4.io/application-speaker/', 'Speak at Ai4 2026'),
    ('https://reg.theaisummit.com/new-york-submit-speaker', 'Submit a Speaker | The AI Summit New York'),
    ('https://worldsummit.ai/form-speakers-enquiries/', 'Speaker enquiries - World Summit AI'),
    ('https://ny-ai-finance.re-work.co/suggest-a-speaker', 'Suggest a Speaker | RE-WORK'),
    ('https://sessionize.com/ai-devsummit-new-york-2026/', 'AI DevSummit New York 2026: Call for Speakers'),
]
for url, title in APPLY:
    check('apply: %s' % url, ev._looks_like_apply(url, title))
    check('not attend-only: %s' % url, not ev._looks_like_attend_only(url, title))

print('2) classifier: attend/register links are NOT apply, ARE attend-only')
ATTEND = [
    ('https://ai4.io/register/', 'Register - Ai4 2026'),
    ('https://newyork.theaisummit.com/tickets/', 'Tickets | The AI Summit New York'),
    ('https://worldsummit.ai/pricing/', 'Pricing - World Summit AI'),
]
for url, title in ATTEND:
    check('not apply: %s' % url, not ev._looks_like_apply(url, title))
    check('attend-only: %s' % url, ev._looks_like_attend_only(url, title))

print('3) _domain_of reduces subdomains to the registrable domain')
check('newyork.theaisummit.com -> theaisummit.com',
      ev._domain_of('https://newyork.theaisummit.com/x') == 'theaisummit.com')
check('reg.theaisummit.com -> theaisummit.com',
      ev._domain_of('https://reg.theaisummit.com/new-york-submit-speaker') == 'theaisummit.com')
check('ai4.io -> ai4.io', ev._domain_of('https://ai4.io/') == 'ai4.io')
check('www.worldsummit.ai -> worldsummit.ai',
      ev._domain_of('https://www.worldsummit.ai/speakers/') == 'worldsummit.ai')
check('something.co.uk kept as 3 labels',
      ev._domain_of('https://events.bigconf.co.uk/cfp') == 'bigconf.co.uk')

print('4) _coerce folds apply_url -> speaking_route (and other aliases)')
r = ev._coerce({'name': 'X', 'apply_url': 'https://x.io/cfp'})
check('apply_url folded', r.get('speaking_route') == 'https://x.io/cfp')
check('apply_url itself dropped (not a column)', 'apply_url' not in r)
r2 = ev._coerce({'name': 'X', 'speaking_route': 'KEEP', 'apply_url': 'https://x.io/cfp'})
check('explicit speaking_route wins over alias', r2.get('speaking_route') == 'KEEP')

print('5) _find_speaking_route: same-domain apply only; skips attend + off-site')
ev.EXA_API_KEY = 'test-key'          # enable the code path

# (a) On-site apply page (on a subdomain of the event's registrable domain) is
#     accepted; the attend page on the same site is skipped.
ev._exa_search = lambda q, include_domains=None, num=8: [
    {'url': 'https://newyork.theaisummit.com/register/', 'title': 'Register'},
    {'url': 'https://reg.theaisummit.com/new-york-submit-speaker', 'title': 'Submit a Speaker'},
]
route = ev._find_speaking_route('The AI Summit New York 2026', 'https://newyork.theaisummit.com/')
check('returns on-site apply (subdomain ok)', route == 'https://reg.theaisummit.com/new-york-submit-speaker')

# (b) Exa returns an OFF-DOMAIN apply page (wrong event) -> must be REJECTED.
#     This is the real bug we found: Microsoft Ignite -> Copilot Summit CFP.
ev._exa_search = lambda q, include_domains=None, num=8: [
    {'url': 'https://copilot.summitna.com/call-for-speakers/', 'title': 'Call for Speakers'},
]
check('off-domain apply rejected (wrong event)',
      ev._find_speaking_route('Microsoft Ignite 2026', 'https://ignite.microsoft.com/') is None)

# (c) No apply page anywhere -> None (never attach an attend link).
ev._exa_search = lambda q, include_domains=None, num=8: [
    {'url': 'https://foo.com/register/', 'title': 'Register'},
    {'url': 'https://foo.com/tickets/', 'title': 'Tickets'},
]
check('no apply page -> None', ev._find_speaking_route('Foo', 'https://foo.com/') is None)

# (d) No event homepage URL -> None (can't verify ownership; never guess).
ev._exa_search = lambda q, include_domains=None, num=8: [
    {'url': 'https://random.com/call-for-speakers/', 'title': 'CFP'},
]
check('no event url -> None', ev._find_speaking_route('Some Event', '') is None)

# (e) EXA disabled -> None, no work.
ev.EXA_API_KEY = ''
check('EXA disabled -> None', ev._find_speaking_route('Foo', 'https://foo.com/') is None)

print('6) _fingerprint: reworded titles collapse; distinct editions stay apart')
# The real duplicate that slipped through (id 16 vs catalog).
fp_a = ev._fingerprint('The AI Leadership Summit — The Conference Board')
fp_b = ev._fingerprint('The Conference Board AI Leadership Summit 2026')
check('reworded Conference Board pair -> same fingerprint', fp_a == fp_b and fp_a != '')
# Year / punctuation / spacing invariance.
check('year + punctuation invariant',
      ev._fingerprint('World Summit AI Amsterdam 2026') == ev._fingerprint('World  Summit, AI: Amsterdam!'))
# Distinct city editions must NOT collapse.
check('New York vs London stay distinct',
      ev._fingerprint('Chief AI Officer Summit New York') != ev._fingerprint('Chief AI Officer Summit London 2026'))
check('ISG NY vs Paris stay distinct',
      ev._fingerprint('ISG AI Impact Summit New York') != ev._fingerprint('ISG AI Impact Summit Paris'))
# US vs EMEA Gartner editions stay distinct (region qualifier preserved).
check('Gartner US vs EMEA stay distinct',
      ev._fingerprint('Gartner IT Symposium/Xpo 2026 (US)') != ev._fingerprint('Gartner IT Symposium/Xpo EMEA 2026'))

print('7) dedupe decision uses fingerprint against the catalog (id 16 case)')
catalog_names = {'the conference board ai leadership summit 2026'}
catalog_fps = ev._fps_of(catalog_names)
cand = 'The AI Leadership Summit — The Conference Board'
cfp = ev._fingerprint(cand)
is_dup = (cand.lower() in catalog_names) or (cfp and cfp in catalog_fps)
check('reworded candidate flagged duplicate via fingerprint', bool(is_dup))
# A genuinely new event is NOT a duplicate.
new = 'Quantum Robotics World Forum Tokyo'
nfp = ev._fingerprint(new)
not_dup = (new.lower() in catalog_names) or (nfp and nfp in catalog_fps)
check('genuinely-new event is NOT flagged', not not_dup)

print('8) _norm_audience: free text -> Buyer-rich | Mixed | Vendor-heavy | None')
check('exact Buyer-rich', ev._norm_audience('Buyer-rich') == 'Buyer-rich')
check('case-insensitive vendor-heavy', ev._norm_audience('VENDOR-HEAVY') == 'Vendor-heavy')
check('"buyers" -> Buyer-rich', ev._norm_audience('mostly enterprise buyers') == 'Buyer-rich')
check('"decision-makers" -> Buyer-rich', ev._norm_audience('senior decision-makers') == 'Buyer-rich')
check('"vendors selling" -> Vendor-heavy', ev._norm_audience('lots of vendors selling to each other') == 'Vendor-heavy')
check('"sales reps" -> Vendor-heavy', ev._norm_audience('agencies and sales reps') == 'Vendor-heavy')
check('"sponsors/exhibitors" -> Vendor-heavy', ev._norm_audience('sponsor-driven expo, exhibitors') == 'Vendor-heavy')
check('"mixed" -> Mixed', ev._norm_audience('a mixed crowd') == 'Mixed')
check('"balanced" -> Mixed', ev._norm_audience('balanced room') == 'Mixed')
check('blank -> None', ev._norm_audience('') is None)
check('None -> None', ev._norm_audience(None) is None)
check('unknown text -> None', ev._norm_audience('hot dogs') is None)

print('9) _coerce folds audience -> audience_type (column name)')
ra = ev._coerce({'name': 'X', 'audience': 'Buyer-rich'})
check('audience folded to audience_type', ra.get('audience_type') == 'Buyer-rich')
check('audience itself dropped (not a column)', 'audience' not in ra)
ra2 = ev._coerce({'name': 'X', 'audience_type': 'Mixed', 'audience': 'Buyer-rich'})
check('explicit audience_type wins over alias', ra2.get('audience_type') == 'Mixed')
check('pricing passes through _coerce', ev._coerce({'name': 'X', 'pricing': '$2,495'}).get('pricing') == '$2,495')

print("9b) _coerce folds speaker-lineup + meeting aliases")
rs = ev._coerce({'name': 'X', 'speakers': 'CIO, UnitedHealth'})
check('speakers folded to past_speakers', rs.get('past_speakers') == 'CIO, UnitedHealth')
check('speakers itself dropped', 'speakers' not in rs)
rs2 = ev._coerce({'name': 'X', 'speaker': 'Thor'})
check("'speaker' (ArcticBlue's own) NOT folded", rs2.get('past_speakers') is None and rs2.get('speaker') == 'Thor')
rm = ev._coerce({'name': 'X', 'guaranteed_meetings': '1:1s; roundtables'})
check('guaranteed_meetings folded to meeting_formats', rm.get('meeting_formats') == '1:1s; roundtables')
check('attend_verdict + postmortem pass through', ev._coerce(
    {'name': 'X', 'attend_verdict': 'Worth attending', 'postmortem': '3 leads'}
).get('attend_verdict') == 'Worth attending')

print('10) _unknown_column: detects pending-migration columns in error bodies')
check('PGRST204 pricing', ev._unknown_column(
    {'code': 'PGRST204', 'message': "Could not find the 'pricing' column of 'manual_events' in the schema cache"}) == 'pricing')
check('42703 audience_type', ev._unknown_column(
    {'code': '42703', 'message': 'column "audience_type" of relation "manual_events" does not exist'}) == 'audience_type')
check('unrelated column -> None', ev._unknown_column(
    {'code': '42703', 'message': 'column "speaker" of relation "manual_events" does not exist'}) is None)
check('unique violation -> None', ev._unknown_column({'code': '23505', 'message': 'duplicate key value'}) is None)
check('non-dict -> None', ev._unknown_column('boom') is None)

print("10b) _derive_dates: Angela's numeric shorthand dates")
check('11/9-11/12 (no year, future) -> Nov 2026',
      ev._derive_dates('11/9-11/12') == ('2026-11-09', '2026-11-12'))
check('4/28 - 4/30/27 (explicit short year)',
      ev._derive_dates('4/28 - 4/30/27') == ('2027-04-28', '2027-04-30'))
check('12/30 - 1/2 wraps the year',
      ev._derive_dates('12/30 - 1/2') == ('2026-12-30', '2027-01-02'))
check('7/8-7/9 same month range', ev._derive_dates('7/8-7/9') == ('2026-07-08', '2026-07-09'))
check('9/29 single date', ev._derive_dates('9/29') == ('2026-09-29', '2026-09-29'))
check('4/28-30 short same-month form', ev._derive_dates('4/28-30')[1] is not None
      and ev._derive_dates('4/28-30')[0].endswith('-04-28')
      and ev._derive_dates('4/28-30')[1].endswith('-04-30'))
check('month-name formats still win: April 14, 2026',
      ev._derive_dates('April 14, 2026') == ('2026-04-14', '2026-04-14'))
check('13/45 nonsense -> no dates', ev._derive_dates('13/45') == (None, None))
check('TBD -> no dates', ev._derive_dates('TBD') == (None, None))

print('11) api/enrich.py: merge_missing fills ONLY empty fields')
ENRICH = os.path.join(HERE, '..', 'api', 'enrich.py')
spec2 = importlib.util.spec_from_file_location('enrich_mod', ENRICH)
en = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(en)

row = {'name': 'Web Summit Lisbon', 'venue': 'MEO Arena', 'pricing': None,
       'url': '', 'pay_to_play': '', 'past_speakers': None,
       'meeting_formats': '', 'audience_type': None, 'typical_attendees': None,
       'attendee_count': None, 'deadline': None}
facts = {'official_url': 'https://websummit.com/', 'venue': 'WRONG VENUE',
         'pricing': '€995 general / €1,950 executive', 'pay_to_play': 'no',
         'past_speakers': ['CTO, Siemens', 'CIO, ING'],
         'meeting_formats': 'Attendee app with 1:1 meeting booking',
         'audience': 'mixed crowd', 'attendee_count': '70,000+'}
p = en.merge_missing(row, facts)
check('existing venue NOT overwritten', 'venue' not in p)
check('pricing filled', p.get('pricing') == '€995 general / €1,950 executive')
check('url filled (name token matches domain)', p.get('url') == 'https://websummit.com/')
check('pay_to_play normalized to No', p.get('pay_to_play') == 'No')
check('speakers list joined', p.get('past_speakers') == 'CTO, Siemens; CIO, ING')
check('audience normalized to Mixed', p.get('audience_type') == 'Mixed')
check('attendee_count filled', p.get('attendee_count') == '70,000+')

# Hallucinated homepage: domain shares no token with the event name -> dropped.
p2 = en.merge_missing({'name': 'Quantum Robotics Forum', 'url': ''},
                      {'official_url': 'https://eventbrite.com/e/12345'})
check('mismatched homepage domain dropped', 'url' not in p2)

check('has_gaps true when fields missing', en.has_gaps({'name': 'X', 'url': None}))
check('has_gaps false when all filled', not en.has_gaps(
    {c: 'x' for c in en.GAP_COLUMNS}))

print('12) events.py inline fact merge: fill-only-missing + audience normalize')
rowi = {'name': 'X', 'venue': 'Set Already', 'pricing': ''}
fi = {'venue': 'New Venue', 'pricing': '$1,500', 'audience': 'mostly buyers'}
pi = ev._merge_missing_facts(rowi, fi)
check('inline: existing venue kept', 'venue' not in pi)
check('inline: pricing filled', pi.get('pricing') == '$1,500')
check('inline: audience normalized', pi.get('audience_type') == 'Buyer-rich')
check('inline: gap detector', ev._row_has_fact_gaps({'name': 'X'}))

print('\n%d passed, %d failed' % (passed, failed))
raise SystemExit(1 if failed else 0)
