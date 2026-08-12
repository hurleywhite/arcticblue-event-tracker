#!/usr/bin/env python3
"""Regression test for ingest duplicate detection.  python3 scripts/test_dedupe.py

Every CASE below is real: eight duplicate pairs that actually reached the
tracker and had to be deleted by hand on 2026-08-08, plus the pairs that must
NEVER be merged. Offline by design — no database, no network — so it can be run
on any checkout before touching api/events.py.

Why the negative cases matter as much as the positive ones: a skipped event is
invisible. Nobody is told the ingest threw something away, so a rule that merges
too eagerly loses real events silently and forever. An early attempt at this
used a similarity ratio loose enough to catch all eight; swept over the live
tracker it also paired 29 genuinely different events ("Chicago CIO Executive
Summit" with "Evanta Seattle CIO Community Executive Summit"). Hence a SUBSET
rule with the city as a hard guard rail, never a ratio.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'ev', os.path.join(_HERE, os.pardir, 'api', 'events.py'))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def blocked(inc, exist):
    """Mirror the same-date decision path in api/events.py for one pair.

    Each side is (name, location, url); both are assumed to share a start_date,
    which is what the caller has already indexed on.
    """
    (in_name, in_loc, in_url), (ex_name, ex_loc, ex_url) = inc, exist
    a, b = ev._name_token_set(in_name), ev._name_token_set(ex_name)
    da, db = ev._domain_of(in_url), ev._domain_of(ex_url)
    if ev._domains_conflict(da, db):
        return None
    fp = ev._fingerprint(in_name)
    if fp and fp == ev._fingerprint(ex_name):
        return 'fingerprint'
    if ev._same_event_on_date(a, b):
        return 'same title + date'
    if da and db and da == db and ev._same_event_reworded(
            a, b, da, ev._city_tokens(in_loc), ev._city_tokens(ex_loc)):
        return 'reworded title'
    return None


IV = 'https://iventiv.com/events/learning-futures/'
MA = 'https://mill-all.com/assemblies/'

# (label, incoming, existing, must_block)
CASES = [
    # ── the eight that got in (2026-08-08 cleanup) ───────────────────
    ('iVentiv Learning Futures NY',
     ('Learning Futures New York, Executive Knowledge Exchange', 'New York City, NY', IV + 'a'),
     ('iVentiv Learning Futures New York 2026', 'New York City, NY', IV + 'b'), True),
    ('iVentiv Learning Futures LA',
     ('Learning Futures LA, Executive Knowledge Exchange', 'Los Angeles, CA', IV + 'a'),
     ('iVentiv Learning Futures LA 2026', 'Los Angeles, CA', IV + 'b'), True),
    ('HCI SPARK TALENT',
     ('SPARK TALENT 2026', 'Orlando, FL', 'https://www.hci.org/spark'),
     ('HCI SPARK TALENT 2026', 'Disney Springs, FL', 'https://www.hci.org/spark-talent-conference-2026'), True),
    ('Evanta Washington DC CHRO',
     ('Washington, DC CHRO Executive Summit 2026', 'Washington, DC', 'https://www.evanta.com/chro/washington-dc/a'),
     ('Evanta Washington DC CHRO Community Executive Summit 2026', 'Arlington, VA', 'https://www.evanta.com/chro/washington-dc/b'), True),
    ('Millennium Alliance Miami',
     ('Digital Enterprise CIO Transformation Assembly November 2026', 'Miami, FL', MA + 'a'),
     ('Millennium Alliance Digital Enterprise CIO Transformation Assembly', 'Miami, FL', MA + 'b'), True),
    ('IT Revolution Charlotte',
     ('Enterprise AI Summit — Charlotte, NC', 'Charlotte, NC', 'https://itrevolution.com/charlotte'),
     ('IT Revolution Enterprise AI Summit — Charlotte 2026', 'Charlotte, NC, USA', 'https://events.itrevolution.com/2026-charlotte/'), True),
    # The venue street address is why _city_tokens keeps every comma segment but
    # the last: reading only the first would call this event "155 Bishopsgate",
    # which shares no word with "London", and the pair would look like two cities.
    ('AI in Financial Services London',
     ('8th Annual Artificial Intelligence in Financial Services Conference (AIFS London)', 'London, UK', 'https://aiinfinancesummit.com/'),
     ('AI in Financial Services Conference 2026', '155 Bishopsgate, London, UK', 'https://aiinfinancesummit.com/'), True),
    # City vs region for the same event — only reachable because the locations
    # agree on "barcelona"; with no location this one is allowed to slip.
    ('Millennium Alliance Barcelona',
     ('Digital Enterprise CIO Transformation Assembly Barcelona 2026', 'Barcelona, Spain', MA + 'a'),
     ('Millennium Alliance Digital Enterprise CIO Transformation Assembly Europe — November 2026', 'Barcelona, Spain', MA + 'b'), True),

    # ── must NEVER merge ─────────────────────────────────────────────
    # Two different Millennium Alliance assemblies, same day, same city, same
    # organiser. Kept apart only because neither title is a subset of the other.
    ('Atlanta: two real same-day assemblies',
     ('Enterprise AI CHRO Transformation Assembly – November', 'Atlanta, GA, USA (The Ritz-Carlton, Buckhead)', MA + 'transformational-chro-assembly-november-2026/'),
     ('Millennium Alliance Transformational CHRO Assembly – November 2026', 'Atlanta, GA', MA + 'enterprise-ai-hr-transformation-assembly-november-2026/'), False),
    # One organiser's city series. The city is the ONLY thing telling these
    # apart once the organiser prefix differs — this is the case the ratio
    # approach got wrong.
    ('Evanta city series (Chicago vs Seattle)',
     ('Chicago CIO Executive Summit 2026', 'Chicago, IL', 'https://www.evanta.com/cio/chicago/x'),
     ('Evanta Seattle CIO Community Executive Summit 2026', 'Seattle, WA', 'https://www.evanta.com/cio/seattle/y'), False),
    # Same city, same day, same host — but genuinely different subjects.
    ('Berlin: Chief AI Officer vs Generative AI',
     ('Chief AI Officer Summit Berlin', 'Berlin, Germany', 'https://example-ai.com/berlin-caio'),
     ('Generative AI Summit Berlin', 'Berlin, Germany', 'https://example-ai.com/berlin-genai'), False),
    ('Millennium Alliance: supply chain vs enterprise CIO',
     ('Digital Supply Chain Transformation Assembly Europe – November 2026', 'Barcelona, Spain', MA + 'a'),
     ('Millennium Alliance Digital Enterprise CIO Transformation Assembly Europe — November 2026', 'Barcelona, Spain', MA + 'b'), False),
    # Neighbouring cities sharing only the state, which _city_tokens drops.
    ('Same state, different city',
     ('Enterprise AI Summit Raleigh 2026', 'Raleigh, NC', 'https://itrevolution.com/raleigh'),
     ('Enterprise AI Summit Charlotte 2026', 'Charlotte, NC', 'https://itrevolution.com/charlotte'), False),
    # Different companies' sites are never paired, however alike the titles.
    ('Same title, different organisers',
     ('AI Leadership Summit 2026', 'Boston, MA', 'https://someconf.com/ai-leadership'),
     ('AI Leadership Summit 2026', 'Boston, MA', 'https://otherconf.org/ai-leadership'), False),
]


def main():
    failures = []
    for label, inc, exist, must_block in CASES:
        why = blocked(inc, exist)
        ok = bool(why) == must_block
        if not ok:
            failures.append((label, why, must_block))
        print('%-4s %-42s %s' % (
            'ok' if ok else 'FAIL', label,
            ('blocked: ' + why) if why else 'allowed through'))
    print()
    if failures:
        print('%d FAILED:' % len(failures))
        for label, why, must_block in failures:
            print('  %s — expected %s, got %s'
                  % (label, 'BLOCK' if must_block else 'ALLOW', why or 'allow'))
        return 1
    print('all %d cases pass' % len(CASES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
