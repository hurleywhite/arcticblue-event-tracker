"""Nightly catalog enrichment — fill missing fields in data/events.json.

Reuses the enrichment core from api/enrich.py (Perplexity facts + Exa
apply-link with the same-domain precision rule). Fills ONLY empty fields,
never overwrites existing data. Picks up to --limit gappy events per run
(rotated daily) so cost stays bounded while gaps shrink night after night —
and brand-new events arriving in the catalog get enriched on the next run.

Run:    python3 scripts/enrich_catalog.py [--limit 10]
Env:    PERPLEXITY_API_KEY and/or EXA_API_KEY (exits 0 quietly if neither set,
        so the GitHub Action never fails when secrets aren't configured).
After:  run python3 src/build.py to regenerate the site.
"""
import argparse
import importlib.util
import json
import os
import random
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')

spec = importlib.util.spec_from_file_location(
    'enrich_mod', os.path.join(ROOT, 'api', 'enrich.py'))
en = importlib.util.module_from_spec(spec)
spec.loader.exec_module(en)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=10,
                    help='max events to research this run (cost cap)')
    args = ap.parse_args()

    if not (en.PPLX_API_KEY or en.EXA_API_KEY):
        print('enrich_catalog: no PERPLEXITY_API_KEY / EXA_API_KEY set — skipping.')
        return 0

    path = os.path.join(ROOT, 'data', 'events.json')
    cat = json.load(open(path))
    evs = cat['events']

    gappy = [e for e in evs if en.has_gaps(e)]
    random.Random(date.today().toordinal()).shuffle(gappy)
    picked = gappy[:max(1, args.limit)]
    print('enrich_catalog: %d/%d events have gaps; researching %d '
          '(perplexity=%s exa=%s)'
          % (len(gappy), len(evs), len(picked),
             bool(en.PPLX_API_KEY), bool(en.EXA_API_KEY)))

    changed = 0
    for ev in picked:
        patch = en.enrich_one(ev)
        if not patch:
            print('  -- #%s %s: nothing verifiable found'
                  % (ev.get('num'), (ev.get('name') or '')[:50]))
            continue
        ev.update(patch)
        changed += 1
        print('  ++ #%s %s: filled %s'
              % (ev.get('num'), (ev.get('name') or '')[:50],
                 ', '.join(sorted(patch.keys()))))

    if changed:
        json.dump(cat, open(path, 'w'), indent=1, ensure_ascii=False)
        print('enrich_catalog: wrote %d enriched events to data/events.json' % changed)
    else:
        print('enrich_catalog: no changes this run')
    return 0


if __name__ == '__main__':
    sys.exit(main())
