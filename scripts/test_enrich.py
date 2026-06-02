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

print('\n%d passed, %d failed' % (passed, failed))
raise SystemExit(1 if failed else 0)
