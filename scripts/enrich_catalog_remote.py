"""Catalog enrichment THROUGH the deployed /api/enrich endpoint.

The Perplexity/Exa keys live only in Vercel. This script sends catalog events
with gaps to /api/enrich's candidates mode (auth: EVENTS_INGEST_SECRET, which
the GitHub workflow already has), gets fill-only-missing patches back, and
applies them to data/events.json. Events with NO website link jump the queue.

Run:   python3 scripts/enrich_catalog_remote.py [--limit 10] [--site URL]
Env:   EVENTS_INGEST_SECRET (exits 0 quietly when unset, so CI never fails)
After: python3 src/build.py to regenerate the site.
"""
import argparse
import importlib.util
import json
import os
import random
import sys
import urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
DEFAULT_SITE = 'https://arcticblue-event-tracker-deploy.vercel.app'

# Pure helpers (gap detection / junk rules) from the endpoint module — no
# API keys are needed to import these.
spec = importlib.util.spec_from_file_location(
    'enrich_mod', os.path.join(ROOT, 'api', 'enrich.py'))
en = importlib.util.module_from_spec(spec)
spec.loader.exec_module(en)


def post_candidates(site, secret, candidates):
    body = json.dumps({'candidates': candidates}).encode('utf-8')
    req = urllib.request.Request(
        site.rstrip('/') + '/api/enrich', method='POST', data=body,
        headers={'Content-Type': 'application/json', 'X-API-Key': secret})
    with urllib.request.urlopen(req, timeout=110) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=10,
                    help='max events to research this run (cost cap)')
    ap.add_argument('--site', default=os.environ.get('ENRICH_SITE', DEFAULT_SITE))
    args = ap.parse_args()

    secret = (os.environ.get('EVENTS_INGEST_SECRET') or '').strip()
    if not secret:
        print('enrich_catalog_remote: EVENTS_INGEST_SECRET not set — skipping.')
        return 0

    path = os.path.join(ROOT, 'data', 'events.json')
    cat = json.load(open(path))
    evs = cat['events']

    gappy = [e for e in evs if en.has_gaps(e)]
    random.Random(date.today().toordinal()).shuffle(gappy)
    # Link-less events first: a homepage unlocks cards AND the apply-link search.
    gappy.sort(key=lambda e: 0 if not (e.get('url') or '').strip() else 1)
    picked = gappy[:max(1, args.limit)]
    no_url = sum(1 for e in picked if not (e.get('url') or '').strip())
    print('enrich_catalog_remote: %d/%d events have gaps; researching %d '
          '(%d without a link) via %s'
          % (len(gappy), len(evs), len(picked), no_url, args.site))

    fields = ('name', 'date_str', 'location', 'url', 'venue', 'pay_to_play',
              'speaking_route', 'pricing', 'past_speakers', 'meeting_formats',
              'audience_type', 'typical_attendees', 'attendee_count', 'deadline')
    changed = 0
    # The endpoint caps candidates per request; send small batches.
    for i in range(0, len(picked), 5):
        batch = picked[i:i + 5]
        cands = [{k: e.get(k) for k in fields if e.get(k) is not None} for e in batch]
        try:
            resp = post_candidates(args.site, secret, cands)
        except Exception as exc:  # noqa: BLE001 — partial progress is fine
            print('  !! batch failed: %s' % exc)
            continue
        for ev, item in zip(batch, resp.get('patches') or []):
            patch = (item or {}).get('patch') or {}
            # Apply: real values fill, explicit nulls clear stored junk.
            for k, v in patch.items():
                if v is None:
                    ev.pop(k, None)
                else:
                    ev[k] = v
            if patch:
                changed += 1
                print('  ++ #%s %s: %s' % (
                    ev.get('num'), (ev.get('name') or '')[:48],
                    ', '.join(sorted(k for k, v in patch.items() if v is not None)) or
                    'cleared junk'))
            else:
                print('  -- #%s %s: nothing verifiable found'
                      % (ev.get('num'), (ev.get('name') or '')[:48]))

    if changed:
        json.dump(cat, open(path, 'w'), indent=1, ensure_ascii=False)
        print('enrich_catalog_remote: wrote %d enriched events to data/events.json' % changed)
    else:
        print('enrich_catalog_remote: no changes this run')
    return 0


if __name__ == '__main__':
    sys.exit(main())
