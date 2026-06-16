"""One-off reconciliation: apply Angela's Replit-vs-Vercel spreadsheet to the
catalog (data/events.json). Replit is the source of truth.

SAFE SET ONLY (this script):
  - Missing URL in Vercel        -> fill url (only if currently empty)
  - Wrong URL domain in Vercel   -> replace url (guard: current == stated)
  - Wrong priority               -> set priority (guard: current == stated)
  - Wrong event type             -> set type (guard: current == stated)
  - Wrong date (AI & Big Data Expo NA only) -> set dates (guard: current == stated)
  - Missing from Vercel          -> append new events (dedup-guard by name)

HELD (NOT touched here): duplicate removals, orphan "review" events, the two
Dallas<->ATL / AIAI-Agentic<->Generative conflations and their title/date
fixes, "extra URL in Vercel" removals, optional URL-path tweaks.

Every field fix is GUARDED: we only change a value when the event's current
value equals the "Vercel value (current)" the sheet recorded. A wrong name
match therefore can't corrupt data — it just gets skipped and reported.

Usage:  python3 scripts/2026-06_reconcile_replit.py            # dry run
        python3 scripts/2026-06_reconcile_replit.py --apply    # write file
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
EVENTS = HERE / 'data' / 'events.json'
XLSX = Path('/Users/hurleywhite/Desktop/ArcticBlue Event Tracker/'
            'Replit-vs-Vercel-Reconciliation.xlsx')
TODAY = date(2026, 6, 16)

# The two conflations flagged "for your eyes" — never auto-apply anything that
# touches these (title/date fixes get held).
CONFLATION_EVENTS = {
    'aiai agentic ai summit los angeles 2026',
    'generative ai summit los angeles',
    'align ai executive summit dallas',
    'align ai executive summit atl',
}


def norm(s):
    """Normalize an event name for matching."""
    s = str(s or '').lower()
    s = s.replace('™', ' ').replace('®', ' ')      # ™ ®
    s = s.replace('–', '-').replace('—', '-')      # – —
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def norm_url(u):
    u = str(u or '').strip()
    if not u:
        return ''
    return re.sub(r'/+$', '', u.lower().replace('https://', '').replace('http://', '').lstrip('www.') if False else re.sub(r'^https?://', '', u.lower())).rstrip('/')


def httpsify(u):
    u = str(u or '').strip()
    if not u:
        return ''
    if not re.match(r'^https?://', u):
        u = 'https://' + u
    return u


def parse_iso(s):
    s = str(s or '').strip()
    if not s or s == 'nan':
        return None
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%Y-%m-%d'):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def date_str_from(start, end):
    si = parse_iso(start)
    ei = parse_iso(end)
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
    xl = pd.ExcelFile(XLSX)
    iss = xl.parse('Issues & Corrections').fillna('')
    sot = xl.parse('Replit Source of Truth').fillna('')
    missing = xl.parse('Missing from Vercel').fillna('')

    # name -> [events]
    idx = {}
    for e in events:
        idx.setdefault(norm(e.get('name')), []).append(e)

    sot_by_num = {}
    for _, r in sot.iterrows():
        rn = str(r['Replit #']).split('.')[0]
        if rn.isdigit():
            sot_by_num[int(rn)] = r

    report = {'applied': [], 'skipped': [], 'unmatched': [], 'held': [], 'added': []}

    def find(event_name, want_field, want_current):
        """Find the catalog event whose `want_field` currently equals
        `want_current`. Disambiguates multi-matches via the guard itself."""
        cands = idx.get(norm(event_name), [])
        if not cands:
            return None, 'no name match'
        # Prefer the one whose current value matches what the sheet expects.
        exact = [e for e in cands if str(e.get(want_field) or '') == str(want_current)]
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            return exact[0], None  # identical dupes; first is fine
        # Name matched but current value differs -> drift / bad match.
        return None, f'current {want_field}={cands[0].get(want_field)!r} != sheet {want_current!r}'

    # ---- priority / type fixes -------------------------------------------
    for issue, field in [('Wrong priority', 'priority'), ('Wrong event type', 'type')]:
        for _, r in iss[iss['Issue'] == issue].iterrows():
            name = r['Event']
            if norm(name) in CONFLATION_EVENTS:
                report['held'].append(f'{issue}: {name} (conflation)')
                continue
            correct = r['Replit value (CORRECT)']
            current = r['Vercel value (current)']
            e, err = find(name, field, current)
            if not e:
                report['unmatched'].append(f'{issue}: {name} -> {err}')
                continue
            if str(e.get(field) or '') == str(correct):
                report['skipped'].append(f'{issue}: {name} (already {correct})')
                continue
            report['applied'].append(f"{issue}: {name}  {e.get(field)!r}->{correct!r}")
            if apply:
                e[field] = correct
                if field == 'priority':
                    e['priority_full'] = correct

    # ---- wrong URL domain -------------------------------------------------
    for _, r in iss[iss['Issue'] == 'Wrong URL domain in Vercel'].iterrows():
        name = r['Event']
        if norm(name) in CONFLATION_EVENTS:
            report['held'].append(f'Wrong URL domain: {name} (conflation)')
            continue
        correct = httpsify(r['Replit value (CORRECT)'])
        current = r['Vercel value (current)']
        cands = idx.get(norm(name), [])
        match = [e for e in cands if norm_url(e.get('url')) == norm_url(current)]
        if not match:
            report['unmatched'].append(
                f'Wrong URL domain: {name} -> no event with current url {current!r}')
            continue
        e = match[0]
        report['applied'].append(f'Wrong URL domain: {name}  {e.get("url")!r}->{correct!r}')
        if apply:
            e['url'] = correct

    # ---- missing URL (fill only if empty) --------------------------------
    for _, r in iss[iss['Issue'] == 'Missing URL in Vercel'].iterrows():
        name = r['Event']
        if norm(name) in CONFLATION_EVENTS:
            report['held'].append(f'Missing URL: {name} (conflation)')
            continue
        correct = httpsify(r['Replit value (CORRECT)'])
        cands = idx.get(norm(name), [])
        if not cands:
            report['unmatched'].append(f'Missing URL: {name} -> no name match')
            continue
        # pick a candidate with empty url
        empties = [e for e in cands if not (e.get('url') or '').strip()]
        if not empties:
            report['skipped'].append(f'Missing URL: {name} (already has a url)')
            continue
        e = empties[0]
        report['applied'].append(f'Missing URL: {name}  +{correct}')
        if apply:
            e['url'] = correct

    # ---- wrong date: AI & Big Data Expo North America only ----------------
    for _, r in iss[iss['Issue'] == 'Wrong date'].iterrows():
        name = r['Event']
        if norm(name) in CONFLATION_EVENTS:
            report['held'].append(f'Wrong date: {name} (conflation — Dallas/ATL)')
            continue
        current = r['Vercel value (current)']
        e, err = find(name, 'date_str', current)
        if not e:
            report['unmatched'].append(f'Wrong date: {name} -> {err}')
            continue
        # pull real start/end from Source of Truth by name
        sr = None
        for _, s in sot.iterrows():
            if norm(s['Event']) == norm(name):
                sr = s
                break
        if sr is None:
            report['unmatched'].append(f'Wrong date: {name} -> not in Source of Truth')
            continue
        si, ei = parse_iso(sr['Start']), parse_iso(sr['End'])
        new_ds = date_str_from(sr['Start'], sr['End'])
        report['applied'].append(f'Wrong date: {name}  {e.get("date_str")!r}->{new_ds!r}')
        if apply:
            e['date_str'] = new_ds
            if si:
                e['start_date'] = si.isoformat()
            if ei:
                e['end_date'] = ei.isoformat()
            elif si:
                e['end_date'] = si.isoformat()

    # ---- add missing events ----------------------------------------------
    existing_norms = set(idx.keys())
    next_num = max((e.get('num') or 0) for e in events) + 1
    for _, r in missing.iterrows():
        name = r['Event']
        if norm(name) in existing_norms:
            report['skipped'].append(f'Add: {name} (already in catalog)')
            continue
        if norm(name) in CONFLATION_EVENTS:
            report['held'].append(f'Add: {name} (conflation — review with the pair)')
            continue
        rn = str(r['Replit #']).split('.')[0]
        s = sot_by_num.get(int(rn)) if rn.isdigit() else None
        start, end = r['Start'], r['End']
        si, ei = parse_iso(start), parse_iso(end)
        status = 'upcoming'
        if ei and ei < TODAY:
            status = 'archived'
        elif si and si < TODAY and not ei:
            status = 'archived'
        ev = {
            'num': next_num,
            'name': str(name).strip(),
            'date_str': date_str_from(start, end),
            'start_date': si.isoformat() if si else None,
            'end_date': (ei or si).isoformat() if (ei or si) else None,
            'location': str(r['Location']).strip(),
            'region': str(r['Region']).strip(),
            'type': str(r['Type']).strip(),
            'priority': str(r['Priority']).strip() or 'Medium',
            'priority_full': str(r['Priority']).strip() or 'Medium',
            'why': str(r['Why it fits']).strip(),
            'url': httpsify(r['Website URL']),
            'status': status,
            'source': 'replit-reconcile',
        }
        if s is not None:
            ev['about'] = str(s['About']).strip()
            ev['focus_areas'] = str(s['Focus areas']).strip()
            ev['typical_attendees'] = str(s['Typical attendees']).strip()
            ev['speaking_route'] = str(s['Speaking route']).strip()
            ev['contact_info'] = str(s['Contact info']).strip()
            ev['pay_to_play'] = str(s['Pay-to-Play']).strip()
            ev['city'] = str(s['City']).strip()
            ev['country'] = str(s['Country']).strip()
            ev['external_id'] = f'replit-{rn}'
        ev = {k: v for k, v in ev.items() if v not in ('', None) or k in ('start_date', 'end_date')}
        report['added'].append(f"[{next_num}] {ev['name']} | {ev['date_str']} | {ev.get('region')} | {ev['priority']}")
        if apply:
            events.append(ev)
        next_num += 1

    # ---- write ------------------------------------------------------------
    if apply:
        doc['counts'] = {
            'today': sum(1 for e in events if e.get('status') == 'today'),
            'upcoming': sum(1 for e in events if e.get('status') == 'upcoming'),
            'archived': sum(1 for e in events if e.get('status') == 'archived'),
            'total': len(events),
        }
        EVENTS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n')

    # ---- report -----------------------------------------------------------
    print(f"{'APPLIED' if apply else 'DRY RUN'} — events now: {len(events)}\n")
    for k in ('applied', 'added', 'skipped', 'unmatched', 'held'):
        print(f"== {k.upper()} ({len(report[k])}) ==")
        for line in report[k]:
            print('   ', line)
        print()


if __name__ == '__main__':
    main('--apply' in sys.argv)
