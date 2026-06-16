"""Phase 2 of the Replit reconciliation (after user sign-off):
  - delete 7 duplicate catalog entries (ops already migrated to the kept copy)
  - fix 4 same-name events whose dates disagreed with Replit (source of truth)
  - add 1 genuinely-missing event (AIAI Agentic LA, co-located with Generative LA)

Guards: deletions assert the expected name; date fixes assert the current
date_str; the add is skipped if the name already exists.

Usage:  python3 scripts/2026-06_reconcile_replit_phase2.py [--apply]
"""
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
EVENTS = HERE / 'data' / 'events.json'
XLSX = Path('/Users/hurleywhite/Desktop/ArcticBlue Event Tracker/'
            'Replit-vs-Vercel-Reconciliation.xlsx')
TODAY = date(2026, 6, 16)

# num -> expected-name-substring (delete guard). Ops already re-pointed.
DELETE = {
    29: 'Ai4 2026',
    50: 'AI Summit New York',
    67: 'CDOIQ Symposium 2026',
    82: 'Responsible AI Summit North America',
    87: 'ALIGN AI Executive Summit San Francisco',
    94: 'Agentic AI Exchange 2026',
    96: 'AI Summit New York 2026',
}

# num -> (expected current date_str, Replit event name to pull new dates from)
DATEFIX = {
    217: ('POSSIBLE Miami Marketing Conference & Expo'),
    161: ('Ai Everything Abu Dhabi'),
    178: ('World AI Cannes Festival (WAICF)'),
    186: ('GITEX AI Asia'),
}


def norm(s):
    s = str(s or '').lower().replace('–', '-').replace('—', '-').replace('™', ' ')
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', s)).strip()


def parse_iso(s):
    s = str(s or '').strip()
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def date_str_from(start, end):
    si, ei = parse_iso(start), parse_iso(end)
    if not si:
        return str(start or '')
    if not ei or ei == si:
        return si.strftime('%B %-d, %Y')
    if si.month == ei.month and si.year == ei.year:
        return f"{si.strftime('%B %-d')}–{ei.day}, {si.year}"
    if si.year == ei.year:
        return f"{si.strftime('%B %-d')}–{ei.strftime('%B %-d')}, {si.year}"
    return f"{si.strftime('%B %-d, %Y')}–{ei.strftime('%B %-d, %Y')}"


def main(apply):
    doc = json.loads(EVENTS.read_text())
    events = doc['events']
    by_num = {e['num']: e for e in events}
    xl = pd.ExcelFile(XLSX)
    missing = xl.parse('Missing from Vercel').fillna('')
    sot = xl.parse('Replit Source of Truth').fillna('')
    log = []

    # ---- deletions (guarded) ---------------------------------------------
    del_nums = set()
    for num, expect in DELETE.items():
        e = by_num.get(num)
        if not e:
            log.append(f'DELETE #{num}: not found — SKIP')
            continue
        if norm(expect) not in norm(e['name']):
            log.append(f"DELETE #{num}: name {e['name']!r} != expected ~{expect!r} — SKIP")
            continue
        del_nums.add(num)
        log.append(f"DELETE #{num} {e['name']!r} ({e.get('date_str')})")
    if apply:
        doc['events'] = [e for e in events if e['num'] not in del_nums]
        events = doc['events']
        by_num = {e['num']: e for e in events}

    # ---- date fixes (Replit = source of truth) ---------------------------
    mrows = {norm(r['Event']): r for _, r in missing.iterrows()}
    for num, repl_name in DATEFIX.items():
        e = by_num.get(num)
        if not e:
            log.append(f'DATEFIX #{num}: not found — SKIP')
            continue
        r = mrows.get(norm(repl_name))
        if r is None:
            log.append(f'DATEFIX #{num}: {repl_name!r} not in Missing tab — SKIP')
            continue
        new_ds = date_str_from(r['Start'], r['End'])
        si, ei = parse_iso(r['Start']), parse_iso(r['End'])
        log.append(f"DATEFIX #{num} {e['name']!r}: {e.get('date_str')!r} -> {new_ds!r}")
        if apply:
            e['date_str'] = new_ds
            if si:
                e['start_date'] = si.isoformat()
            e['end_date'] = (ei or si).isoformat() if (ei or si) else None

    # ---- add AIAI Agentic LA (co-located, genuinely separate) ------------
    add_name = 'AIAI Agentic AI Summit Los Angeles 2026'
    exists = any(norm(e['name']) == norm(add_name) for e in events)
    if exists:
        log.append(f'ADD {add_name!r}: already present — SKIP')
    else:
        s = None
        for _, r in sot.iterrows():
            if norm(r['Event']) == norm(add_name):
                s = r
                break
        if s is None:
            log.append(f'ADD {add_name!r}: not in Source of Truth — SKIP')
        else:
            si, ei = parse_iso(s['Start']), parse_iso(s['End'])
            new_num = max(e['num'] for e in events) + 1
            ev = {
                'num': new_num,
                'name': str(s['Event']).strip(),
                'date_str': date_str_from(s['Start'], s['End']),
                'start_date': si.isoformat() if si else None,
                'end_date': (ei or si).isoformat() if (ei or si) else None,
                'location': str(s['Location']).strip(),
                'region': str(s['Region']).strip(),
                'type': str(s['Type']).strip(),
                'priority': str(s['Priority']).strip() or 'Medium',
                'priority_full': str(s['Priority']).strip() or 'Medium',
                'why': str(s['Why it fits']).strip(),
                'url': 'https://' + str(s['Website URL']).strip() if str(s['Website URL']).strip() and not str(s['Website URL']).startswith('http') else str(s['Website URL']).strip(),
                'status': 'upcoming' if (si and si >= TODAY) else 'archived',
                'about': str(s['About']).strip(),
                'focus_areas': str(s['Focus areas']).strip(),
                'typical_attendees': str(s['Typical attendees']).strip(),
                'speaking_route': str(s['Speaking route']).strip(),
                'contact_info': str(s['Contact info']).strip(),
                'city': str(s['City']).strip(),
                'country': str(s['Country']).strip(),
                'external_id': 'replit-210',
                'source': 'replit-reconcile',
            }
            ev = {k: v for k, v in ev.items() if v not in ('', None) or k in ('start_date', 'end_date')}
            log.append(f"ADD #{new_num} {ev['name']!r} | {ev['date_str']} | {ev.get('region')} | {ev['priority']}")
            if apply:
                events.append(ev)

    if apply:
        EVENTS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n')

    print(f"{'APPLIED' if apply else 'DRY RUN'} — events now: {len(events)}\n")
    for line in log:
        print('  ', line)


if __name__ == '__main__':
    main('--apply' in sys.argv)
