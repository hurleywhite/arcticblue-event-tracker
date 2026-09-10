#!/usr/bin/env python3
"""Fill manual_events.city from the location text.  Dry run by default.

    python3 scripts/backfill_city.py            # show what WOULD change
    python3 scripts/backfill_city.py --write    # write it

WHY: 55 of 370 upcoming events had a venue where the city should be ("Hynes
Convention Center, Boston, MA", "22 Bishopsgate"), and only 6 of 292 upcoming
manual events had `city` filled at all. Every geography feature — trip
stacking, conflicts, "along the route" — matched on that text and found
nothing. Same rules as cityOf() in src/booking-core.js: the city is the LAST
comma segment that is neither a country/state nor a venue; a bare venue with
no city stays empty rather than guessing.

Additive and reversible: only rows whose `city` is empty are touched, and the
dry run prints the exact before/after. Uses the publishable key, so RLS decides
what may be written — the same path the tracker's own edit form uses.
"""
import json, re, sys, unicodedata, urllib.request, subprocess, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir)
KEY = subprocess.check_output("grep -o 'sb_publishable_[A-Za-z0-9_-]*' %s/public/index.html | head -1" % ROOT, shell=True, text=True).strip()
BASE = 'https://efkvhlmfdwlobvdmvqiq.supabase.co/rest/v1'
H = {'apikey': KEY, 'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'}

REGION = re.compile(r'^(usa|us|u\.s\.a?|united states|uk|u\.k\.|united kingdom|england|scotland|germany|france|spain|italy|greece|netherlands|the netherlands|portugal|switzerland|belgium|luxembourg|austria|ireland|sweden|denmark|norway|finland|poland|czech republic|hungary|romania|lithuania|estonia|latvia|uae|united arab emirates|saudi arabia|saudi|ksa|qatar|bahrain|oman|kuwait|egypt|morocco|singapore|japan|india|china|hong kong|sar|taiwan|south korea|korea|thailand|malaysia|indonesia|vietnam|philippines|australia|new zealand|canada|mexico|brazil|argentina|colombia|chile|peru|uruguay|ecuador|dominican republic|puerto rico|panama|costa rica|guatemala|turkey|türkiye|south africa|nigeria|ghana|kenya|rwanda|israel|[a-z]{2})$')
VENUE = re.compile(r'\b(center|centre|hotel|hall|convention|arena|resort|expo|palais|brewery|olympia|venetian|javits|hynes|bishopsgate|aldersgate|convene|westin|hyatt|sofitel|marriott|hilton|sheraton|ritz|carlton|waldorf|mandalay|moscone|excel|rds|society|estate|winery|campus|street|st\.|avenue|ave\.|road|rd\.|suite|floor|room|club|stadium|theatre|theater|museum|university|college|school|event park|business park|rai|jw|kongresshaus|kongress|messe|exhibition)\b|^\d')
ALIAS = {'nyc':'new york','new york city':'new york','manhattan':'new york','brooklyn':'new york','jersey city':'new york','hoboken':'new york','münchen':'munich','munchen':'munich','são paulo':'sao paulo','santiago de chile':'santiago','washington dc':'washington','washington d.c.':'washington','d.c.':'washington','dc':'washington','national harbor':'washington','arlington':'washington','burlingame':'san francisco','santa clara':'san francisco','san jose':'san francisco','dana point':'los angeles','anaheim':'los angeles','irving':'dallas','disney springs':'orlando','lake buena vista':'orlando','multiple':'','various':'','tbc':''}

def fold(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    return ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()

def city_of(location):
    """Mirror of cityOf() in src/booking-core.js — keep the two in step."""
    loc = fold(location)
    if not loc or re.match(r'^(unknown|tbd|tbc|online|remote|virtual|multiple|various)$', loc):
        return ''
    parts = [re.sub(r'\(.*?\)', '', p).strip() for p in re.split(r'[,;|·]', loc)]
    parts = [p for p in parts if p]
    place = list(parts)
    while len(place) > 1 and REGION.match(place[-1]):
        place.pop()
    cities = [p for p in place if not VENUE.search(p)]
    c = cities[-2] if len(cities) >= 2 else (cities[0] if cities else '')
    if not c and len(parts) > 1:
        rest = [w for w in re.sub(r'[^a-z ]', ' ', VENUE.sub('', place[-1])).split() if len(w) >= 4]
        if len(rest) == 1:
            c = rest[0]
    return ALIAS.get(c, c)

def title(s):
    return ' '.join(w.capitalize() for w in s.split())

def get(p):
    r = urllib.request.Request(BASE + p, headers=H)
    return json.load(urllib.request.urlopen(r, timeout=60))

def main():
    write = '--write' in sys.argv
    rows = get('/manual_events?select=id,name,location,city&limit=3000')
    plan, blank = [], []
    for m in rows:
        if (m.get('city') or '').strip():
            continue
        c = city_of(m.get('location'))
        if c:
            plan.append((m['id'], m['name'], m.get('location'), title(c)))
        else:
            blank.append((m['id'], m['name'], m.get('location')))
    print('%d manual events · %d already have a city · %d can be filled · %d cannot be placed'
          % (len(rows), sum(1 for m in rows if (m.get('city') or '').strip()), len(plan), len(blank)))
    print('\nWILL SET (id · location -> city):')
    for i, n, loc, c in plan:
        print('  %-5s %-46s %-44s -> %s' % (i, (n or '')[:44], (loc or '')[:42], c))
    print('\nCANNOT PLACE (left empty on purpose):')
    for i, n, loc in blank:
        print('  %-5s %-46s %r' % (i, (n or '')[:44], (loc or '')[:50]))
    if not write:
        print('\nDry run. Re-run with --write to apply.')
        return
    ok = fail = 0
    for i, _n, _loc, c in plan:
        req = urllib.request.Request(BASE + '/manual_events?id=eq.%s' % i, method='PATCH', headers=dict(H, Prefer='return=minimal'), data=json.dumps({'city': c}).encode())
        try:
            urllib.request.urlopen(req, timeout=30); ok += 1
        except Exception as e:
            fail += 1; print('  FAILED', i, e)
    print('\nwrote %d, failed %d' % (ok, fail))

if __name__ == '__main__':
    main()
