#!/usr/bin/env python3
"""ingest_block.py — pull the JSON block out of the agent's chat reply,
merge new events into the canonical events.json, and rebuild the site.

Usage (macOS, simplest):
    pbpaste | python3.11 src/ingest_block.py

Or from a file:
    python3.11 src/ingest_block.py < /tmp/agent_reply.txt

What it does:
1.  Reads the agent's chat reply from stdin (paste the whole thing)
2.  Extracts the ```json {...} ``` block at the end (or any JSON it finds)
3.  Validates the "new_events" array
4.  Dedupes against the existing events.json (by lowercased name)
5.  Assigns event numbers starting from max(existing)+1
6.  Merges into events.json AND event-urls-manual.json
7.  Re-runs build.py so public/index.html is regenerated

Then run `vercel deploy --prod --yes` from public/ to push live.

No-hallucination contract preserved: a `url: null` field stays null in our
urls map — the rendered card will be non-clickable.
"""
import sys
sys.path.insert(0, '/Users/hurleywhite/Library/Python/3.11/lib/python/site-packages')

import json
import re
import subprocess
from datetime import date
from pathlib import Path

HERE        = Path(__file__).resolve().parent.parent
EVENTS_JSON = HERE / 'data'   / 'events.json'     # canonical source — build.py reads from here
URLS_MANUAL = HERE / 'data'   / 'event-urls-manual.json'
BUILD_PY    = HERE / 'src'    / 'build.py'

REQUIRED_FIELDS = ('name', 'date_str', 'location', 'type', 'priority', 'why')


def extract_json_block(raw: str) -> dict:
    """Find the first valid JSON object in `raw`. Prefer fenced ```json blocks;
    fall back to greedy { ... } match."""
    # 1. fenced ```json ... ```
    m = re.search(r'```json\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2. fenced ``` ... ``` (no language tag)
    m = re.search(r'```\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. last resort: greedy match on outermost braces containing "new_events"
    for m in re.finditer(r'\{[^\{]*?"new_events"\s*:.*\}', raw, re.DOTALL):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    raise ValueError('No JSON block with "new_events" found in input')


def normalize_event(ev: dict, num: int) -> dict:
    """Coerce an agent-provided event into our canonical schema."""
    out = {
        'num':           num,
        'name':          (ev.get('name') or '').strip(),
        'date_str':      (ev.get('date_str') or '').strip(),
        'start_date':    ev.get('start_date'),
        'end_date':      ev.get('end_date'),
        'location':      (ev.get('location') or '').strip(),
        'region':        ev.get('region') or '',
        'type':          (ev.get('type') or 'Enterprise').strip(),
        'priority':      (ev.get('priority') or 'Medium').strip(),
        'priority_full': (ev.get('priority_full') or ev.get('priority') or 'Medium').strip(),
        'why':           (ev.get('why') or '').strip(),
        'url':           ev.get('url'),       # may be None — that's fine
        'status':        'upcoming',
    }
    # Infer region if missing
    if not out['region']:
        loc = out['location'].lower()
        if any(c in loc for c in ['usa', 'canada', 'brazil', 'mexico']):
            out['region'] = 'Americas'
        elif any(c in loc for c in ['uk', 'germany', 'france', 'spain', 'netherlands',
                                     'belgium', 'portugal', 'switzerland', 'italy', 'ireland']):
            out['region'] = 'Europe'
        elif any(c in loc for c in ['singapore', 'hong kong', 'china', 'australia', 'japan', 'korea', 'india']):
            out['region'] = 'Asia-Pacific'
        elif any(c in loc for c in ['saudi', 'dubai', 'uae', 'qatar', 'doha', 'riyadh']):
            out['region'] = 'MENA'
        else:
            out['region'] = 'Global'
    return out


def validate(ev: dict, idx: int) -> list[str]:
    errs = []
    for f in REQUIRED_FIELDS:
        if not ev.get(f):
            errs.append(f'event[{idx}]: missing or empty field "{f}" (name={ev.get("name", "?")!r})')
    return errs


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit('ERROR: no input on stdin. Try: pbpaste | python3.11 src/ingest_block.py')

    block = extract_json_block(raw)
    new_events = block.get('new_events') or []
    if not new_events:
        sys.exit('ERROR: JSON block has no "new_events" array (or it is empty)')
    print(f'→ parsed {len(new_events)} candidate new event(s) from agent reply')

    # Validate up front — refuse to ingest if any required field is missing
    errs = []
    for i, ev in enumerate(new_events):
        errs.extend(validate(ev, i))
    if errs:
        print('VALIDATION FAILED:', file=sys.stderr)
        for e in errs:
            print('  ' + e, file=sys.stderr)
        sys.exit(1)

    # Load existing canonical state
    existing = json.loads(EVENTS_JSON.read_text())
    existing_events = existing['events']
    existing_names = {e['name'].lower().strip() for e in existing_events}
    next_num = max((e.get('num') or 0) for e in existing_events) + 1

    # Load manual URL overrides
    manual_urls = {}
    if URLS_MANUAL.exists():
        manual_urls = json.loads(URLS_MANUAL.read_text())

    added = []
    skipped_dup = []
    for ev in new_events:
        nm = ev['name'].lower().strip()
        if nm in existing_names:
            skipped_dup.append(ev['name'])
            continue
        normalized = normalize_event(ev, next_num)
        existing_events.append(normalized)
        existing_names.add(nm)
        # Stash URL into manual map only if non-null (no-hallucination rule)
        if normalized['url']:
            manual_urls[str(next_num)] = normalized['url']
        added.append((next_num, normalized['name']))
        next_num += 1

    # Re-sort and re-count
    existing['events'] = existing_events
    existing['counts'] = {
        'today':    sum(1 for e in existing_events if e.get('status') == 'today'),
        'upcoming': sum(1 for e in existing_events if e.get('status') == 'upcoming'),
        'archived': sum(1 for e in existing_events if e.get('status') == 'archived'),
        'total':    len(existing_events),
    }
    existing['generated_at'] = date.today().isoformat() + 'T00:00:00Z'

    # Write events.json + manual URL map
    EVENTS_JSON.write_text(json.dumps(existing, indent=2) + '\n', encoding='utf-8')
    URLS_MANUAL.write_text(json.dumps(manual_urls, indent=2) + '\n', encoding='utf-8')

    print(f'→ added {len(added)} new event(s):')
    for num, nm in added:
        print(f'    #{num}  {nm}')
    if skipped_dup:
        print(f'→ skipped {len(skipped_dup)} duplicate(s):')
        for nm in skipped_dup:
            print(f'    (dup) {nm}')

    # Re-run build so public/index.html reflects the new events
    print('→ regenerating public/index.html …')
    r = subprocess.run([sys.executable, str(BUILD_PY)], cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print('BUILD FAILED:', file=sys.stderr)
        print(r.stdout, file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        sys.exit(2)
    print(r.stdout.strip().splitlines()[-2] if r.stdout else '')
    print()
    print('NEXT: run this to deploy:')
    print('    cd "{}/public" && vercel deploy --prod --yes'.format(HERE))


if __name__ == '__main__':
    main()
