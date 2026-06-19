"""Re-sync Angela's EventsCal Replit data (2026-06-18 handoff) into the tracker.

Newer than the 2026-06-11 import. Two outputs:
  1) data/events.json — CONSERVATIVE merge of event facts. Angela is the source
     of truth, so her NON-EMPTY values win; where her field is empty we KEEP the
     tracker's existing value (never blanked — protects enrichment). Her brand-
     new events are appended. external_id is backfilled to her UUID so future
     syncs join by id, not just fingerprint.
  2) scripts/angela_state_payload.json — per-event_num tracking values (statuses
     -> the CURRENT 5 stages, speaker, saved, hidden, interested, decision,
     submission notes). Applied to the live event_state by the browser step,
     which merges against existing rows (Angela non-empty wins; keep mine where
     empty; union interested/saved/hidden).

Stage model is the CURRENT one: Identified, Submitted, Meeting held, Booked,
Attending. There is NO 'Declined' stage and NO 'Worth attending' verdict (both
retired this cycle) — declined-type statuses become a decision='no-go'; the
Attending/Should-Attend statuses become the Attending STAGE; Thor/Verma
"Interested" statuses go to the per-person interested list.

Run:  python3 scripts/2026-06-18_resync_angela.py            # dry run (no writes)
      python3 scripts/2026-06-18_resync_angela.py --apply    # write both outputs
"""
import importlib.util
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
SNAP = os.path.join(ROOT, 'data', 'angela_snapshot')
CAT_PATH = os.path.join(ROOT, 'data', 'events.json')
PAYLOAD_PATH = os.path.join(HERE, 'angela_state_payload.json')

spec = importlib.util.spec_from_file_location('events_mod', os.path.join(ROOT, 'api', 'events.py'))
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)
fingerprint = em._fingerprint

EMPTY = {None, '', 'unknown', 'n/a', 'na', 'tbd', 'tba', 'nan', 'none', 'past event'}


def blank(v):
    if v is None:
        return True
    if not isinstance(v, str):
        return False
    s = v.strip().lower()
    if s in EMPTY:
        return True
    # junk sentinels carrying extra text: "n/a (past event)", "unknown — ...", "tbd ..."
    return bool(re.match(r'^(n/?a|unknown|tbd|tba|none)\b', s))


def httpsify(u):
    u = str(u or '').strip()
    if not u:
        return ''
    return u if re.match(r'^https?://', u, re.I) else 'https://' + u


def norm_domain(u):
    u = re.sub(r'^https?://', '', str(u or '').strip().lower())
    u = re.sub(r'^www\.', '', u)
    return u.split('/')[0].rstrip('/')


# ── Status vocabulary → CURRENT model ────────────────────────────────────────
BOOKED = {'booked', 'booked prior year', 'booked prior event'}
ATTENDING = {'attending', 'attending (not speaking)', 'attending?', 'should attend'}
MEETING = {'had mtg', 'in contact with'}
SUBMITTED = {'submitted', 'finish submission', 'submission inquiry', 'in progress',
             'booking in progress', 'followed up'}
NOGO = {'no openings', 'no external speakers', 'not accepted', 'not accepted this yr',
        'passing', "we'll pass", 'date conflict', 'sponsorship only',
        'membership only (to attend or speak)'}
EARLY = {'pending', 'joined waitlist', 'contact/get invited to speak',
         'curated speaking by invite', 'curated industry invite'}
INTEREST = {'thor interested': 'Thor', 'thor contacting': 'Thor', 'verma interested': 'Verma'}
IGNORE = {'--', '?', 'test', 'postponed', 'postponed?'}
STAGE_ORDER = ['Identified', 'Submitted', 'Meeting held', 'Booked', 'Attending']


def stages_of(statuses):
    out = set()
    for s in statuses:
        k = (s or '').strip().lower()
        if not k or k in IGNORE or k in NOGO or k in INTEREST:
            continue
        if k in BOOKED:
            out.add('Booked')
        elif k in ATTENDING:
            out.add('Attending')
        elif k in MEETING:
            out.add('Meeting held')
        elif k in SUBMITTED:
            out.add('Submitted')
        elif k in EARLY:
            out.add('Identified')
        else:
            out.add('Identified')
    return [s for s in STAGE_ORDER if s in out]


def interested_of(statuses):
    out = []
    for s in statuses:
        who = INTEREST.get((s or '').strip().lower())
        if who and who not in out:
            out.append(who)
    return out


def is_nogo(statuses, stages):
    if 'Booked' in stages or 'Attending' in stages:
        return False
    return any((s or '').strip().lower() in NOGO for s in statuses)


def norm_speaker(v):
    if not v:
        return None
    v = str(v).strip()
    if v.startswith('['):
        try:
            return ', '.join(str(x) for x in json.loads(v))
        except (ValueError, TypeError):
            pass
    return v or None


# ── Region / type normalization for HER new events ───────────────────────────
US_REGIONS = {'bay area', 'boston', 'california', 'east coast', 'florida', 'las vegas',
              'mid-atlantic', 'midwest', 'mountain west', 'nyc', 'nevada', 'new jersey',
              'northeast', 'other us', 'south central', 'southeast', 'southwest', 'texas',
              'west coast', 'canada', 'latin america', 'venezuela'}
EU_REGIONS = {'europe', 'london', 'catalonia'}


def norm_region(her):
    k = (her.get('region') or '').strip().lower()
    if k in US_REGIONS:
        return 'Americas'
    if k in EU_REGIONS:
        return 'Europe'
    if k in {'middle east'}:
        return 'MENA'
    if k in {'asia'}:
        return 'Asia-Pacific'
    if k in {'south africa'}:
        return 'South Africa'
    return 'Global'


VERTICALS = {'finance', 'hr', 'health', 'insurance', 'security', 'education', 'sales', 'compliance'}


def norm_type(her):
    ts = [t.strip().lower() for t in (her.get('eventType') or [])]
    if 'halo' in ts:
        return 'Halo'
    if 'podcast' in ts:
        return 'Other'
    if any(t in VERTICALS for t in ts):
        return 'Industry'
    return 'Enterprise'


def parse_date(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def date_str_of(start, end, raw_start):
    if not start:
        return raw_start or 'Date TBD'
    if not end or end == start:
        return start.strftime('%B %-d, %Y')
    if start.month == end.month and start.year == end.year:
        return '%s %d–%d, %Y' % (start.strftime('%B'), start.day, end.day, start.year) if False else \
               '{} {}–{}, {}'.format(start.strftime('%B'), start.day, end.day, start.year)
    return '%s – %s' % (start.strftime('%B %-d, %Y'), end.strftime('%B %-d, %Y'))


# Map an ai-event field -> (catalog key, transform) for the conservative refresh.
def her_facts(her):
    start, end = parse_date(her.get('startDate')), parse_date(her.get('endDate'))
    fa = her.get('focusAreas')
    facts = {
        'name': (her.get('title') or '').strip() or None,
        'location': her.get('location'),
        'city': her.get('city'),
        'country': her.get('country'),
        'why': her.get('whyItFits'),
        'about': her.get('about'),
        'typical_attendees': her.get('typicalAttendees'),
        'speaking_route': her.get('speakingRoute'),
        'contact_info': her.get('contactInfo'),
        'pay_to_play': her.get('payToPlay'),
        'attendee_count': her.get('attendeeCount'),
        'deadline': her.get('deadline'),
        'poc_email': her.get('pocEmail'),
        'priority': her.get('priority'),
        'focus_areas': ('; '.join(fa) if isinstance(fa, list) else fa) if fa else None,
    }
    if start:
        facts['start_date'] = start.isoformat()
        facts['end_date'] = (end or start).isoformat()
        facts['date_str'] = date_str_of(start, end, her.get('startDate'))
    return {k: v for k, v in facts.items() if not blank(v)}


def new_event(her, num):
    ev = {'num': num, 'source': 'angela-resync-2026-06-18', 'external_id': her['id'],
          'region': norm_region(her), 'type': norm_type(her),
          'priority': her.get('priority') or 'Medium'}
    ev['priority_full'] = ev['priority']
    ev.update(her_facts(her))
    if not blank(her.get('websiteUrl')):
        ev['url'] = httpsify(her['websiteUrl'])
    ev.setdefault('priority_full', ev.get('priority'))
    if her.get('isSeed') is not None:
        ev['seed'] = bool(her.get('isSeed'))
    if her.get('isUrgent') is not None:
        ev['urgent'] = bool(her.get('isUrgent'))
    ev.setdefault('date_str', 'Date TBD')
    return ev


def main(apply):
    ai = json.load(open(os.path.join(SNAP, 'ai-events.json')))
    ov = json.load(open(os.path.join(SNAP, 'event-overrides.json')))
    subs = json.load(open(os.path.join(SNAP, 'linked-submissions.json')))
    sov = json.load(open(os.path.join(SNAP, 'submission-field-overrides.json')))
    cat = json.load(open(CAT_PATH))
    ours = cat['events']

    by_ext = {e['external_id']: e for e in ours if e.get('external_id')}
    by_fp = {}
    for e in ours:
        fp = fingerprint(e.get('name') or '')
        if fp:
            by_fp.setdefault(fp, e)

    rep = {'matched': 0, 'new': 0, 'fields_updated': 0, 'extid_backfilled': 0}
    her_to_num, new_events = {}, []
    next_num = max(e['num'] for e in ours) + 1

    for her in ai:
        hid = her['id']
        ev = by_ext.get(hid)
        if ev is None:
            fp = fingerprint(her.get('title') or '')
            ev = by_fp.get(fp) if fp else None
        if ev is not None:
            rep['matched'] += 1
            her_to_num[hid] = ev['num']
            if not ev.get('external_id'):
                if apply:
                    ev['external_id'] = hid
                by_ext[hid] = ev
                rep['extid_backfilled'] += 1
            # conservative fact refresh: Angela non-empty wins; keep ours where empty
            for k, v in her_facts(her).items():
                if blank(ev.get(k)) or str(ev.get(k)) != str(v):
                    if apply:
                        ev[k] = v
                        if k == 'priority':
                            ev['priority_full'] = v
                    rep['fields_updated'] += 1
            # URL: keep our (enriched, https) link when it's the same domain;
            # only adopt Angela's when ours is empty or points elsewhere.
            hv = httpsify(her.get('websiteUrl')) if not blank(her.get('websiteUrl')) else ''
            if hv and (blank(ev.get('url')) or norm_domain(ev.get('url')) != norm_domain(hv)):
                if apply:
                    ev['url'] = hv
                rep['fields_updated'] += 1
        else:
            ne = new_event(her, next_num)
            if not ne.get('name'):
                continue
            new_events.append(ne)
            her_to_num[hid] = next_num
            fp = fingerprint(ne['name'])
            if fp:
                by_fp[fp] = ne
            by_ext[hid] = ne
            next_num += 1
            rep['new'] += 1

    if apply:
        ours.extend(new_events)
        cat['counts'] = dict(cat.get('counts') or {}, total=len(ours))
        cat['build_date'] = str(datetime.now().date())
        json.dump(cat, open(CAT_PATH, 'w'), indent=1, ensure_ascii=False)

    # ── submissions: notes (+ derive stage from submission status) by num ──
    sub_notes, sub_stage, sub_speaker = {}, {}, {}
    orphans_sub = []
    for s in subs:
        # NB: submission-field-overrides (sov) are intentionally NOT merged. Their
        # id space drifted in the DB recovery — a sov key's content belongs to a
        # DIFFERENT submission than the same id in linked-submissions (e.g. sov["6"]
        # is ITI/No-Openings but submission 6 is PULSE NYC), so joining by id
        # attaches the wrong notes. The linked-submission's own fields are
        # internally consistent (id, eventId, notes all from one scrape), so use
        # those. The detached sov layer is reported as orphaned.
        m = dict(s)
        num = her_to_num.get(m.get('eventId'))
        if num is None:
            fp = fingerprint(m.get('eventName') or '')
            ev = by_fp.get(fp) if fp else None
            num = ev['num'] if ev else None
        if num is None:
            orphans_sub.append(m.get('eventName'))
            continue
        bits = []
        if m.get('status'):
            bits.append('Status: ' + m['status'])
        if m.get('poc'):
            bits.append('POC: ' + m['poc'])
        if m.get('pocEmail'):
            bits.append(m['pocEmail'])
        if m.get('notes'):
            bits.append(m['notes'])
        if bits:
            sub_notes.setdefault(num, []).append(' · '.join(bits))
        for st in stages_of([m.get('status')]):
            sub_stage.setdefault(num, set()).add(st)
        sp = norm_speaker(m.get('speaker'))
        if sp and sp != '–' and num not in sub_speaker:
            sub_speaker[num] = sp

    # ── overrides → per-num tracking (handle ::YEAR + JSON-array speaker) ──
    rows = {}
    orphan_ov = 0
    for key, o in ov.items():
        base = key.split('::')[0]
        num = her_to_num.get(base)
        if num is None:
            orphan_ov += 1
            continue
        statuses = [s for s in (o.get('statuses') or []) if s]
        stages = stages_of(statuses)
        new = {
            'status_tags': set(stages),
            'status': ', '.join(s for s in statuses if (s or '').strip().lower() not in IGNORE) or None,
            'speaker': norm_speaker(o.get('speaker')),
            'saved': bool(o.get('saved')),
            'hidden': bool(o.get('hidden')),
            'interested': set(interested_of(statuses)),
            'decision': 'no-go' if is_nogo(statuses, stages) else None,
        }
        if num in rows:
            r = rows[num]
            r['status_tags'] |= new['status_tags']
            r['status'] = r['status'] or new['status']
            r['speaker'] = r['speaker'] or new['speaker']
            r['saved'] = r['saved'] or new['saved']
            r['hidden'] = r['hidden'] or new['hidden']
            r['interested'] |= new['interested']
            r['decision'] = r['decision'] or new['decision']
        else:
            rows[num] = new

    # fold in submission-derived stages / speaker / notes
    for num, sts in sub_stage.items():
        rows.setdefault(num, {'status_tags': set(), 'status': None, 'speaker': None,
                              'saved': False, 'hidden': False, 'interested': set(), 'decision': None})
        rows[num]['status_tags'] |= sts
    for num, sp in sub_speaker.items():
        rows.setdefault(num, {'status_tags': set(), 'status': None, 'speaker': None,
                              'saved': False, 'hidden': False, 'interested': set(), 'decision': None})
        if not rows[num]['speaker']:
            rows[num]['speaker'] = sp
    for num in sub_notes:
        rows.setdefault(num, {'status_tags': set(), 'status': None, 'speaker': None,
                              'saved': False, 'hidden': False, 'interested': set(), 'decision': None})

    payload = []
    for num in sorted(rows):
        r = rows[num]
        payload.append({
            'num': num,
            'status_tags': [s for s in STAGE_ORDER if s in r['status_tags']],
            'status': r['status'],
            'speaker': r['speaker'],
            'saved': r['saved'],
            'hidden': r['hidden'],
            'interested': sorted(r['interested']),
            'decision': r['decision'],
            'notes': '\n'.join(sub_notes.get(num, [])) or None,
        })
    if apply:
        json.dump(payload, open(PAYLOAD_PATH, 'w'), indent=1, ensure_ascii=False)

    # ── report ──
    print('%s' % ('APPLIED' if apply else 'DRY RUN'))
    print('catalog: matched=%d  new=%d  fields_updated=%d  external_id_backfilled=%d'
          % (rep['matched'], rep['new'], rep['fields_updated'], rep['extid_backfilled']))
    print('catalog total now: %d' % (len(ours) + (0 if apply else len(new_events))))
    for e in new_events[:50]:
        print('   NEW #%d %s (%s)' % (e['num'], e['name'], e.get('date_str')))
    staged = sum(1 for p in payload if p['status_tags'])
    nogo = sum(1 for p in payload if p['decision'] == 'no-go')
    intr = sum(1 for p in payload if p['interested'])
    notes = sum(1 for p in payload if p['notes'])
    print('tracking payload: %d events  (%d staged, %d no-go, %d interested, %d with notes)'
          % (len(payload), staged, nogo, intr, notes))
    print('orphans: overrides=%d  submissions=%d %s' % (orphan_ov, len(orphans_sub), orphans_sub or ''))
    print('detached (recovery id-drift, intentionally skipped): submission-field-overrides=%d' % len(sov))


if __name__ == '__main__':
    main('--apply' in sys.argv)
