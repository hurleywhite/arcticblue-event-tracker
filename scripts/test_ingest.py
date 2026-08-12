#!/usr/bin/env python3
"""End-to-end test of the Dust ingest loop.  python3 scripts/test_ingest.py

Drives the REAL do_POST with every outbound call stubbed — no database, no
network, no OpenAI. Offline by design so it can run on any checkout.

WHY THIS EXISTS. On 2026-07-29, commit 92556a8 dedented one block by a single
level, which moved a `continue` out of the reject branch and into the main path.
Every event with a parsable date was then skipped before it could be inserted,
and the next event in the batch hit a tuple that no longer matched its unpack
and threw — so every Dust POST returned 500 and added nothing. The feed was dead
for two weeks and nobody noticed, because a skipped event and an event that was
never offered look exactly the same from the outside, and nobody reads the
response body.

Unit-testing the dedupe helpers would NOT have caught it: every helper was fine.
Only running the loop shows it. So assert on the loop.
"""
import importlib.util
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'ev', os.path.join(_HERE, os.pardir, 'api', 'events.py'))
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

# ── stub every outbound call ──────────────────────────────────────────
EXISTING = [
    ('iVentiv Learning Futures New York 2026', '2026-10-20',
     'https://iventiv.com/events/learning-futures/b', 'New York City, NY'),
    ('Millennium Alliance Transformational CHRO Assembly - November 2026', '2026-11-17',
     'https://mill-all.com/assemblies/enterprise-ai-hr/', 'Atlanta, GA'),
]
ev._existing_manual_dated = lambda: list(EXISTING)
ev._catalog_dated = lambda host: []
ev._deleted_backlog = lambda: []
ev._gate_enabled = lambda: False           # gate off -> 'accept'
ev.VERIFY_ENABLED = False
ev.EXA_API_KEY = ''
ev.PPLX_API_KEY = ''

INSERTED = []
def _fake_insert(row):
    INSERTED.append(row)
    return 201, [{'id': 9000 + len(INSERTED)}]
ev._insert_one = _fake_insert
ev._http_json = lambda *a, **k: (500, {})   # nothing else may reach the network

SENT = {}
def _fake_send(h, status, payload):
    SENT['status'] = status
    SENT['payload'] = payload
ev._send = _fake_send
ev.INGEST_SECRET = 'test-secret'
ev.SERVICE_ROLE = 'test-role'
ev._match_secret = lambda h: 'team'


class FakeHandler(ev.handler):
    def __init__(self, body):
        raw = json.dumps(body).encode()
        self.rfile = io.BytesIO(raw)
        self.headers = {'Content-Length': str(len(raw)), 'Host': 'x.test',
                        'X-API-Key': 'test-secret'}
        self.path = '/api/events'


BATCH = [
    # 1. brand new, fully dated -> MUST insert (this is what broke)
    {'name': 'Quantum Ops Summit Lisbon 2026', 'date_str': 'March 3, 2026',
     'start_date': '2026-03-03', 'location': 'Lisbon, Portugal',
     'url': 'https://quantumops.example/lisbon'},
    # 2. reworded copy of an event already in the tracker -> MUST skip
    {'name': 'Learning Futures New York, Executive Knowledge Exchange',
     'date_str': 'October 20, 2026', 'start_date': '2026-10-20',
     'location': 'New York City, NY',
     'url': 'https://iventiv.com/events/learning-futures/a'},
    # 3. reworded copy of item 1, same batch -> MUST skip (in-batch guard)
    {'name': 'Quantum Ops Summit Lisbon — Executive Edition 2026',
     'date_str': 'March 3, 2026', 'start_date': '2026-03-03',
     'location': 'Lisbon, Portugal', 'url': 'https://quantumops.example/lisbon-exec'},
    # 4. genuinely different event, same host+day+city as the Atlanta one -> MUST insert
    {'name': 'Millennium Alliance Enterprise AI CHRO Transformation Assembly',
     'date_str': 'November 17, 2026', 'start_date': '2026-11-17',
     'location': 'Atlanta, GA', 'url': 'https://mill-all.com/assemblies/other/'},
]

FakeHandler({'events': BATCH}).do_POST()

p = SENT.get('payload') or {}
print('HTTP %s' % SENT.get('status'))
print('inserted: %s' % [e['name'] for e in p.get('inserted', [])])
print('skipped : %s' % [(e['name'][:44], e['reason']) for e in p.get('skipped', [])])
print('rejected: %s' % [e['name'] for e in p.get('rejected', [])])
print('errors  : %s' % p.get('errors'))
print()

ins = {e['name'] for e in p.get('inserted', [])}
skp = {e['name'] for e in p.get('skipped', [])}
checks = [
    ('dated new event is inserted (the regression)', BATCH[0]['name'] in ins),
    ('reworded copy of a stored event is skipped', BATCH[1]['name'] in skp),
    ('reworded copy from the SAME batch is skipped', BATCH[2]['name'] in skp),
    ('different same-day/host/city event still inserted', BATCH[3]['name'] in ins),
    ('no errors', not p.get('errors')),
]
bad = [c for c, ok in checks if not ok]
for c, ok in checks:
    print('%-4s %s' % ('ok' if ok else 'FAIL', c))
print()
print('%d FAILED' % len(bad) if bad else 'all %d checks pass' % len(checks))
sys.exit(1 if bad else 0)
