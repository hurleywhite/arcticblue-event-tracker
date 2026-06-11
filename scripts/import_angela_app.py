"""One-time import of Angela's EventsCal Replit app data (2026-06-11).

Source: https://events-cal.replit.app/api/* — snapshotted into
data/angela_snapshot/. Her app was seeded from our catalog a month ago and
she has been maintaining statuses there since, so HER data wins on conflict.

Does two things:
  1) Appends her brand-new events (not in our catalog, by name fingerprint)
     to data/events.json, converted to our schema. Run `python3 src/build.py`
     afterwards to regenerate the site.
  2) Emits scripts/2026-06-11_import_angela_state.sql — event_state upserts
     carrying her statuses (mapped to our 5 pipeline stages), speaker, saved,
     hidden, an attend_verdict derived from her Attending/Should-Attend
     statuses, and her submission-tracker notes/POCs.

Run:  python3 scripts/import_angela_app.py
Idempotent: re-running never duplicates catalog rows (fingerprint guard), and
the SQL is a pure upsert.
"""
import importlib.util
import json
import os
import re
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
SNAP = os.path.join(ROOT, 'data', 'angela_snapshot')

# Reuse the production fingerprint logic from the ingest API.
spec = importlib.util.spec_from_file_location('events_mod', os.path.join(ROOT, 'api', 'events.py'))
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)
fingerprint = em._fingerprint

# ── Status vocabulary → our 5 pipeline stages ────────────────────────
BOOKED = {'booked', 'booked prior event', 'booked prior year'}
DECLINED = {'no openings', 'not accepted this yr', "we'll pass", 'date conflict',
            'sponsorship only', 'no external speakers',
            'membership only (to attend or speak)'}
MEETING = {'had mtg', 'in contact with'}
SUBMITTED = {'submitted', 'finish submission', 'submission inquiry',
             'followed up', 'in progress'}
IGNORE = {'--', '?', 'test'}
ATTEND_YES = {'attending', 'should attend'}
ATTEND_MAYBE = {'attending?'}
STAGE_ORDER = ['Identified', 'Submitted', 'Meeting held', 'Booked', 'Declined']


def stages_of(statuses):
    out = set()
    for s in statuses:
        k = (s or '').strip().lower()
        if not k or k in IGNORE:
            continue
        if k in BOOKED:
            out.add('Booked')
        elif k in DECLINED:
            out.add('Declined')
        elif k in MEETING:
            out.add('Meeting held')
        elif k in SUBMITTED:
            out.add('Submitted')
        elif k in ATTEND_YES or k in ATTEND_MAYBE:
            pass  # attending intent, not a speaking-pipeline stage
        else:
            out.add('Identified')
    return [s for s in STAGE_ORDER if s in out]


def attend_verdict_of(statuses):
    ks = {(s or '').strip().lower() for s in statuses}
    if ks & ATTEND_YES:
        return 'Worth attending'
    if ks & ATTEND_MAYBE:
        return 'Maybe'
    return None


def norm_speaker(v):
    """Her app sometimes stored a JSON-array string ('["Thor","Jerome"]')."""
    if not v:
        return None
    v = str(v).strip()
    if v.startswith('['):
        try:
            return ', '.join(str(x) for x in json.loads(v))
        except (ValueError, TypeError):
            pass
    return v


# ── Region / type normalization for HER new events ───────────────────
US_REGIONS = {'bay area', 'boston', 'california', 'east coast', 'florida',
              'las vegas', 'mid-atlantic', 'midwest', 'mountain west', 'nyc',
              'nevada', 'new jersey', 'northeast', 'other us', 'south central',
              'southeast', 'southwest', 'texas', 'west coast', 'canada',
              'latin america', 'venezuela'}
EU_REGIONS = {'europe', 'london', 'catalonia'}
MENA_REGIONS = {'middle east'}
APAC_REGIONS = {'asia'}


def norm_region(her):
    k = (her.get('region') or '').strip().lower()
    if k in US_REGIONS:
        return 'Americas'
    if k in EU_REGIONS:
        return 'Europe'
    if k in MENA_REGIONS:
        return 'MENA'
    if k in APAC_REGIONS:
        return 'Asia-Pacific'
    if k in ('south africa',):
        return 'South Africa'  # matches our existing Cape Town rows
    return 'Global'


VERTICALS = {'finance', 'hr', 'health', 'insurance', 'security', 'education',
             'sales', 'compliance'}


def norm_type(her):
    ts = [t.strip().lower() for t in (her.get('eventType') or [])]
    if 'halo' in ts:
        return 'Halo'
    if 'podcast' in ts:
        return 'Other'
    if any(t in VERTICALS for t in ts):
        return 'Industry'
    return 'Enterprise'


def parse_her_date(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def date_str_of(start, end, raw_start, raw_end):
    if not start:
        return (raw_start or 'Date TBD')
    if not end or end == start:
        return start.strftime('%B %-d, %Y')
    if start.month == end.month and start.year == end.year:
        return '%s %d–%d, %Y'.replace('%Y', str(start.year)) % (
            start.strftime('%B'), start.day, end.day)
    return '%s – %s' % (start.strftime('%B %-d, %Y'), end.strftime('%B %-d, %Y'))


def to_our_schema(her, num):
    start = parse_her_date(her.get('startDate'))
    end = parse_her_date(her.get('endDate'))
    ev = {
        'num': num,
        'name': (her.get('title') or '').strip(),
        'date_str': date_str_of(start, end, her.get('startDate'), her.get('endDate')),
        'location': her.get('location') or '',
        'region': norm_region(her),
        'type': norm_type(her),
        'priority': her.get('priority') or 'Medium',
        'source': 'angela-app-2026-06-11',
    }
    if start:
        ev['start_date'] = start.isoformat()
    if end or start:
        ev['end_date'] = (end or start).isoformat()
    if her.get('websiteUrl'):
        ev['url'] = her['websiteUrl']
    opt = {
        'why': her.get('whyItFits'), 'about': her.get('about'),
        'typical_attendees': her.get('typicalAttendees'),
        'attendee_count': her.get('attendeeCount'),
        'pay_to_play': her.get('payToPlay'),
        'speaking_route': her.get('speakingRoute'),
        'contact_info': her.get('contactInfo'),
        'poc_email': her.get('pocEmail'), 'deadline': her.get('deadline'),
        'city': her.get('city'), 'country': her.get('country'),
        'notes': her.get('notes'),
    }
    for k, v in opt.items():
        if v:
            ev[k] = v
    fa = her.get('focusAreas')
    if fa:
        ev['focus_areas'] = '; '.join(fa) if isinstance(fa, list) else str(fa)
    if her.get('isSeed') is not None:
        ev['seed'] = bool(her.get('isSeed'))
    if her.get('isUrgent') is not None:
        ev['urgent'] = bool(her.get('isUrgent'))
    return ev


def sql_str(v):
    if v is None:
        return 'null'
    return "'" + str(v).replace("'", "''") + "'"


def sql_tags(tags):
    if not tags:
        return "'{}'::text[]"
    return 'array[' + ', '.join(sql_str(t) for t in tags) + ']'


def main():
    ai = json.load(open(os.path.join(SNAP, 'ai-events.json')))
    ov = json.load(open(os.path.join(SNAP, 'event-overrides.json')))
    subs = json.load(open(os.path.join(SNAP, 'linked-submissions.json')))
    sov = json.load(open(os.path.join(SNAP, 'submission-field-overrides.json')))

    cat_path = os.path.join(ROOT, 'data', 'events.json')
    cat = json.load(open(cat_path))
    ours = cat['events']

    our_fp = {}
    for e in ours:
        fp = fingerprint(e.get('name') or '')
        if fp:
            our_fp.setdefault(fp, e['num'])

    # 1) Match her events → our nums; collect her brand-new ones.
    her_to_num, new_events = {}, []
    next_num = max(e['num'] for e in ours) + 1
    for her in ai:
        fp = fingerprint(her.get('title') or '')
        if fp and fp in our_fp:
            her_to_num[her['id']] = our_fp[fp]
            continue
        ev = to_our_schema(her, next_num)
        if not ev['name']:
            continue
        new_events.append(ev)
        her_to_num[her['id']] = next_num
        if fp:
            our_fp[fp] = next_num
        next_num += 1

    ours.extend(new_events)
    cat['counts'] = dict(cat.get('counts') or {}, total=len(ours))
    json.dump(cat, open(cat_path, 'w'), indent=1, ensure_ascii=False)
    print('catalog: +%d new events from Angela (now %d total)' % (len(new_events), len(ours)))
    for e in new_events:
        print('  NEW #%d %s  (%s)' % (e['num'], e['name'], e.get('date_str')))

    # 2) Merge submission field-overrides into submissions, group by event.
    sub_notes = {}
    for s in subs:
        o = sov.get(str(s['id'])) or {}
        merged = dict(s)
        for k_src, k_dst in (('date', 'date'), ('eventName', 'eventName'),
                             ('location', 'location'), ('notes', 'notes'),
                             ('poc', 'poc'), ('pocEmail', 'pocEmail')):
            if o.get(k_src):
                merged[k_dst] = o[k_src]
        num = her_to_num.get(merged.get('eventId'))
        if num is None:
            # Fallback: the submission's eventId points at a deleted app event;
            # match by the submission's own event NAME instead.
            f = fingerprint(merged.get('eventName') or '')
            num = our_fp.get(f) if f else None
        if num is None and 'odsc' in (merged.get('eventName') or '').lower():
            num = 139  # "AI X Leadership Summit — ODSC AI East 2026" (renamed)
        if num is None:
            print('  ! submission with unmatched event:', merged.get('eventName'))
            continue
        bits = []
        if merged.get('status'):
            bits.append('Status: ' + merged['status'])
        if merged.get('poc'):
            bits.append('POC: ' + merged['poc'])
        if merged.get('pocEmail'):
            bits.append(merged['pocEmail'])
        if merged.get('notes'):
            bits.append(merged['notes'])
        if bits:
            sub_notes.setdefault(num, []).append(' · '.join(bits))

    # 3) Build event_state upserts from her overrides (+ submission notes).
    # Her app holds a few duplicate events (same conference twice); both rows'
    # overrides land on the SAME our-num, so merge instead of overwriting:
    # union the stages, OR the booleans, keep the first non-null text.
    rows = {}
    for her_id, o in ov.items():
        num = her_to_num.get(her_id)
        if num is None:
            continue
        statuses = [s for s in (o.get('statuses') or []) if s]
        new = {
            'status_tags': stages_of(statuses),
            'status': ', '.join(s for s in statuses
                                if (s or '').strip().lower() not in IGNORE) or None,
            'speaker': norm_speaker(o.get('speaker')),
            'saved': bool(o.get('saved')),
            'hidden': bool(o.get('hidden')),
            'attend_verdict': attend_verdict_of(statuses),
        }
        if num in rows:
            old = rows[num]
            merged_tags = [s for s in STAGE_ORDER
                           if s in set(old['status_tags']) | set(new['status_tags'])]
            rows[num] = {
                'status_tags': merged_tags,
                'status': old['status'] or new['status'],
                'speaker': old['speaker'] or new['speaker'],
                'saved': old['saved'] or new['saved'],
                'hidden': old['hidden'] and new['hidden'],
                'attend_verdict': old['attend_verdict'] or new['attend_verdict'],
            }
        else:
            rows[num] = new
    for num, notes in sub_notes.items():
        rows.setdefault(num, {'status_tags': [], 'status': None, 'speaker': None,
                              'saved': False, 'hidden': False, 'attend_verdict': None})
    out = [
        '-- ====================================================================',
        "-- Import of Angela's EventsCal app state (events-cal.replit.app)",
        '-- Generated %s by scripts/import_angela_app.py -- DO NOT EDIT BY HAND' % datetime.now().date(),
        '--',
        '-- Pure upsert on event_state keyed by event_num. Her statuses map to',
        '-- our 5 pipeline stages; Attending/Should-Attend becomes the',
        '-- attend_verdict; her submission-tracker rows land in notes. Columns',
        '-- she does not carry (postmortem, track, ...) are left untouched.',
        '-- Idempotent -- safe to re-run.',
        '-- ====================================================================',
        '',
    ]
    for num in sorted(rows):
        r = rows[num]
        notes = '\n'.join(sub_notes.get(num, [])) or None
        out.append(
            'insert into public.event_state (event_num, status_tags, status, speaker, '
            'saved, hidden, attend_verdict, notes, updated_by)\n'
            'values (%d, %s, %s, %s, %s, %s, %s, %s, %s)\n'
            'on conflict (event_num) do update set\n'
            '  status_tags = excluded.status_tags,\n'
            '  status = excluded.status,\n'
            '  speaker = coalesce(excluded.speaker, event_state.speaker),\n'
            '  saved = excluded.saved,\n'
            '  hidden = excluded.hidden,\n'
            '  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),\n'
            '  notes = coalesce(excluded.notes, event_state.notes),\n'
            '  updated_by = excluded.updated_by;\n' % (
                num, sql_tags(r['status_tags']), sql_str(r['status']),
                sql_str(r['speaker']), 'true' if r['saved'] else 'false',
                'true' if r['hidden'] else 'false', sql_str(r['attend_verdict']),
                sql_str(notes), sql_str('angela-app-import')))
    out.append('-- Sanity: how many rows now carry stages? (expect >= %d)' % len(rows))
    out.append("select count(*) from public.event_state where cardinality(status_tags) > 0;")
    sql_path = os.path.join(HERE, '2026-06-11_import_angela_state.sql')
    open(sql_path, 'w').write('\n'.join(out) + '\n')
    n_staged = sum(1 for r in rows.values() if r['status_tags'])
    n_attend = sum(1 for r in rows.values() if r['attend_verdict'])
    print('SQL: %d event_state upserts (%d with stages, %d with attend verdicts, %d with notes) -> %s'
          % (len(rows), n_staged, n_attend, len(sub_notes), os.path.relpath(sql_path, ROOT)))


if __name__ == '__main__':
    main()
