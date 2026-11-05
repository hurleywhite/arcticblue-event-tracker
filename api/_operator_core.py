"""Event operator rules: which events go in Thor's weekly batch, by which lane,
and what the screen shows about each one. Pure functions, no network, so every
rule here is unit tested (scripts/test_operator.py).

The underscore keeps Vercel from deploying this file as its own function; it is
imported by api/operator.py. See EVENT-OPERATOR.md for the why behind each rule.
"""
import datetime as dt
import json
import re
import unicodedata
import urllib.parse

# ── Settings ───────────────────────────────────────────────────────────────
DEFAULTS = {
    'person': 'thor',
    'weekly_target': 30,          # Thor: about 30 a week, 100 is too many
    'max_days_out': 365,          # apply up to 12 months ahead
    'apply_min_days': 14,         # an open call for an event at least two weeks away
    'outreach_min_days': 60,      # organiser outreach needs time to land a slot
    'urgent_close_days': 21,      # calls closing this soon jump the queue
    'follow_up_days': 14,         # same intervals as the tracker's follow-up nudge
    'follow_up_near_days': 7,
    'follow_up_imminent_days': 3,
    'follow_up_cap': 15,
    'loss_lookback_days': 45,
    'linkedin_note_max': 200,     # LinkedIn's limit for a connection note on a free account
    'linkedin_message_max': 700,
    'email_words_max': 130,
    'out_grace_days': 7,          # keep an in-flight item on "Out now" a week past the event
}

STAGES = ['Submitted', 'Initial outreach', 'Followed up', 'Meeting held', 'Booked', 'Rejected', 'Attending']
IN_FLIGHT = ('Submitted', 'Initial outreach', 'Followed up', 'Meeting held')
CHAIN = ['Submitted', 'Initial outreach', 'Followed up']

# Thor's fit profile, copied from AB_PROFILES in src/build.py (the "My Fits"
# filter the team already uses). Broad terms only fill a short batch.
PROFILES = {
    'thor': {
        'kw': ['healthcare', 'healthtech', 'health tech', 'digital health', 'medtech', 'med tech',
               'life sciences', 'pharma', 'pharmaceutical', 'biotech', 'health system', 'healthcare ai',
               'payer', 'health plan', 'hospital executive', 'chief medical officer'],
        'broad_kw': ['chief ai officer', 'caio', 'cio', 'cto', 'cdo', 'c suite', 'executive', 'executives',
                     'enterprise ai', 'ai strategy', 'ai leadership', 'ai leaders', 'transformation',
                     'agentic', 'generative ai', 'board', 'senior leaders', 'decision makers'],
        'english_only': True,
        'no_clinical': True,
    },
    'verma': {
        'kw': ['insurance', 'insurtech', 'life insurance', 'reinsurance', 'finance', 'financial services',
               'bank', 'banking', 'capital markets', 'payments', 'fintech', 'board', 'chief data',
               'regulated', 'compliance'],
        'broad_kw': ['chief ai officer', 'cio', 'cto', 'cdo', 'executive', 'enterprise ai', 'ai strategy',
                     'transformation', 'agentic', 'generative ai'],
        'english_only': True,
        'no_clinical': False,
    },
}

SKIP_REASONS = {
    'not_fit': ('Not a fit', True),
    'pays': ('Pays to speak', True),
    'timing': ('Timing or travel', True),
    'not_this_week': ('Not this week', False),
}

# ── Text helpers ───────────────────────────────────────────────────────────
def fold(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower()


def words_blob(*parts):
    """' a b c ': lowercased, accent-free, punctuation as spaces, padded."""
    t = re.sub(r'[^a-z0-9]+', ' ', fold(' '.join(str(p or '') for p in parts))).strip()
    return ' ' + re.sub(r' +', ' ', t) + ' '


def has_kw(blob, kws):
    return any(' ' + k + ' ' in blob for k in kws)


def no_dashes(s):
    """Hurley's rule for anything Thor sends: no em dashes. En dashes become hyphens."""
    s = str(s or '')
    s = re.sub(r'\s*\u2014\s*', ', ', s)
    s = s.replace('–', '-')
    s = re.sub(r',\s*,', ',', s)
    return s


def clip(s, n):
    s = re.sub(r'[ \t]+', ' ', str(s or '')).strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    # Prefer ending on a full sentence, then on a word.
    end = max(cut.rfind('. '), cut.rfind('? '))
    if end >= n * 0.6:
        return cut[:end + 1]
    return cut.rsplit(' ', 1)[0].rstrip(',;:')


def first_name(full):
    full = re.sub(r'\(.*?\)', ' ', str(full or '')).strip()
    for w in full.split():
        if w.lower().strip('.') in ('dr', 'mr', 'ms', 'mrs', 'prof'):
            continue
        return w.strip(',')
    return ''


def week_id(day):
    y, w, _ = day.isocalendar()
    return '%d-W%02d' % (y, w)


def parse_day(s):
    """'2026-11-09', '2026-11-09T..', 'Nov 9, 2026', '9 November 2026' -> date or None."""
    s = str(s or '').strip()
    if not s:
        return None
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    months = {m_: i + 1 for i, m_ in enumerate(
        ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
    m = re.search(r'\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', s)
    if m and m.group(1)[:3].lower() in months:
        try:
            return dt.date(int(m.group(3)), months[m.group(1)[:3].lower()], int(m.group(2)))
        except ValueError:
            return None
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b', s)
    if m and m.group(2)[:3].lower() in months:
        try:
            return dt.date(int(m.group(3)), months[m.group(2)[:3].lower()], int(m.group(1)))
        except ValueError:
            return None
    return None


# ── Exclusion gates (ported from src/build.py so both agree) ───────────────
_HR_NAME = re.compile(r"\b(hr|chro|shrm|pshra|hrci|clo|cupa)\b|human resources?|chief (human resources|people|learning) officer|"
                      r"people (officer|analytics)|talent (management|acquisition|strategy|forum)|"
                      r"workforce (summit|forum|conference|institute)|learning (futures|technologies)|\bl&d\b|"
                      r"employee experience|total rewards|compensation (and|&) benefits", re.I)
_HR_HOST = re.compile(r"\b(shrm\.org|eane\.org|pshra\.org|hrci\.org|cupahr\.org|iventiv\.com|joshbersin\.com|unleash\.ai|"
                      r"td\.org|corporatelearningnetwork\.com|hrexchangenetwork\.com|hrtechnologyconference\.com)\b", re.I)
_HR_BLOB = re.compile(r"\bchro\b|shrm|chief (human resources|people)|people officer|\bhr (summit|conference|forum|assembly|exchange|congress|leaders)\b")
_CLIN_NAME = re.compile(r"\baimed\d*\b|\bbmj\b|king'?s fund|giant health|\bnhs\b|clinical (trials?|research|practice|excellence)|\bcme\b|"
                        r"grand rounds|nursing|physicians?|clinicians?|oncolog|radiolog|cardiolog|surgical|surgery|"
                        r"\bmedical (association|society|congress)\b", re.I)
_CLIN_HOST = re.compile(r"\b(ai-med\.io|aimed\.com|bmj\.com|kingsfund\.org\.uk|giant\.health|nhs\.uk|americanhealthlaw\.org|ncqa\.org)\b", re.I)
_CLIN_BLOB = re.compile(r"\b(practising|practicing) (clinicians?|physicians?)\b|for (clinicians?|physicians?|nurses)\b|"
                        r"clinical (trials?|research|workflows?|practice)\b|bedside|point of care|care delivery")
_AFRICA = re.compile(r"\b(south africa|johannesburg|cape town|nigeria|lagos|kenya|nairobi|ghana|accra|ethiopia|rwanda|kigali|"
                     r"tanzania|uganda|senegal|mauritius|seychelles|botswana|zambia|africa)\b")
_FL_STRONG = set('foro foros congreso congresso cumbre jornada jornadas encuentro encuentros feria semana iberoamericano '
                 'iberoamericana latinoamericano latinoamericana inteligencia tecnologia tecnologias innovacion inovacao '
                 'empresas empresarial negocios seguridad educacion educacao gestion gestao transformacion transformacao '
                 'kongress tagung wirtschaft kunstliche digitalisierung convegno giornata settimana intelligenza imprese '
                 'numerique journee journees rencontres assises entreprise entreprises donnees'.split())
_FL_FUNC = set('de del la el los y para con da do dos das em sobre du des pour les sur avec und fur der die per della '
               'delle sul nel datos dados salon messe fiera'.split())


def is_hr(ev):
    return bool(_HR_NAME.search(ev.get('name') or '') or _HR_HOST.search(ev.get('url') or '')
                or _HR_BLOB.search(fold(ev.get('_blob') or '')))


def is_clinical(ev):
    return bool(_CLIN_NAME.search(ev.get('name') or '') or _CLIN_HOST.search(ev.get('url') or '')
                or _CLIN_BLOB.search(fold(ev.get('_blob') or '')))


def is_africa(ev):
    return bool(_AFRICA.search(fold(' '.join(str(ev.get(f) or '') for f in ('location', 'city', 'country', 'region')))))


def is_foreign(ev):
    loc = set(words_blob(ev.get('location'), ev.get('city'), ev.get('country'), ev.get('region')).split())
    strong = func = 0
    for w in words_blob(ev.get('name')).split():
        if w in loc:
            continue
        if w in _FL_STRONG:
            strong += 1
        elif w in _FL_FUNC:
            func += 1
    return strong >= 1 or func >= 2


# ── Merging the three stores into one record per event ─────────────────────
FIELDS = ('name', 'date_str', 'start_date', 'end_date', 'location', 'city', 'country', 'region', 'type',
          'priority', 'url', 'apply_url', 'speaking_route', 'deadline', 'pay_to_play', 'about', 'why',
          'focus_areas', 'typical_attendees', 'past_speakers', 'audience_type', 'speaker', 'workflow_status',
          'poc_name', 'poc_email', 'poc_linkedin', 'poc_note', 'poc_lookup_at', 'contact_info',
          'additional_contacts', 'submitted_at', 'notes', 'decision')
LIST_FIELDS = ('interested', 'attendees', 'outreach_assignees')


def _val(v):
    return v not in (None, '', '__cleared__')


def merge(catalog, states, manuals):
    """catalog events.json rows + event_state overrides + manual_events -> one
    list of records with `_table`/`_key`, the tracker's own `st.X || ev.X` rule."""
    out = []
    by_num = {str(s.get('event_num')): s for s in states or [] if s.get('event_num') is not None}
    for ev in catalog or []:
        if ev.get('num') is None:
            continue
        st = by_num.pop(str(ev['num']), None) or {}
        if st.get('status') == '__deleted__':
            continue
        rec = {'_table': 'event_state', '_key': ev['num'], '_has_state': bool(st)}
        for f in FIELDS:
            v = st.get(f)
            rec[f] = v if _val(v) else (ev.get(f) if _val(ev.get(f)) else '')
        for f in LIST_FIELDS:
            rec[f] = st.get(f) if st.get(f) is not None else (ev.get(f) or [])
        rec['status_tags'] = st.get('status_tags') if st else None
        rec['status'] = st.get('status') if _val(st.get('status')) else ev.get('status')
        rec['hidden'] = st.get('hidden') is True
        rec['booking'] = st.get('booking') if isinstance(st.get('booking'), dict) else {}
        rec['follow_ups'] = _follow_list(st.get('follow_ups'))
        out.append(_finish(rec))
    for m in manuals or []:
        if m.get('status') == '__deleted__':
            continue
        rec = {'_table': 'manual_events', '_key': m.get('id'), '_has_state': True}
        for f in FIELDS:
            rec[f] = m.get(f) if _val(m.get(f)) else ''
        for f in LIST_FIELDS:
            rec[f] = m.get(f) or []
        rec['status_tags'] = m.get('status_tags')
        rec['status'] = m.get('status')
        rec['hidden'] = m.get('hidden') is True
        rec['booking'] = m.get('booking') if isinstance(m.get('booking'), dict) else {}
        rec['follow_ups'] = _follow_list(m.get('follow_ups'))
        out.append(_finish(rec))
    return out


def _follow_list(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = []
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _finish(rec):
    rec['_blob'] = ' '.join(str(rec.get(f) or '') for f in (
        'name', 'about', 'focus_areas', 'typical_attendees', 'location', 'city', 'country', 'type',
        'past_speakers', 'audience_type'))
    rec['_start'] = parse_day(rec.get('start_date'))
    rec['_end'] = parse_day(rec.get('end_date')) or rec['_start']
    rec['stages'] = stages_of(rec)
    return rec


# ── Stages ─────────────────────────────────────────────────────────────────
_LEGACY = [
    (re.compile(r'attending|will attend|attend only', re.I), ['Attending']),
    (re.compile(r'book|self submitted|speaking|confirmed', re.I), ['Booked']),
    (re.compile(r'reject|turned down|not selected|not chosen|declined to speak', re.I), ['Rejected']),
    (re.compile(r"not accept|declin|\bskip\b|passing|we.ll pass|no opening|date conflict|sponsorship only|don.?t call", re.I), []),
    (re.compile(r'intro meeting|received intro|in contact|cc.?d on mtg|\bmeeting\b', re.I), ['Meeting held']),
    (re.compile(r'follow.?up|followed up|chased|nudged', re.I), ['Followed up']),
    (re.compile(r'submit|application|finish submission', re.I), ['Submitted']),
]


def _legacy(raw):
    s = str(raw or '').strip()
    if not s or s == '__deleted__' or s.lower() in ('upcoming', 'archived', 'today', 'past event'):
        return []
    s = ','.join(t for t in s.split(',') if not t.strip().endswith('?'))
    s = re.sub(r'curated speaking by invite|curated industry invite|no external speakers|membership only[^,]*', '', s, flags=re.I)
    s = re.sub(r'[,\s]+', ' ', s).strip()
    if not s:
        return []
    for rx, tags in _LEGACY:
        if rx.search(s):
            return list(tags)
    return []


def imply(tags):
    tags = [t for t in tags if t in STAGES]
    deepest = max([i for i, t in enumerate(CHAIN) if t in tags], default=-1)
    for i in range(deepest):
        if CHAIN[i] not in tags:
            tags.append(CHAIN[i])
    if 'Rejected' in tags and 'Submitted' not in tags:
        tags.append('Submitted')
    return [s for s in STAGES if s in tags]


def stages_of(rec):
    raw = rec.get('status_tags')
    if isinstance(raw, str):
        raw = [t.strip() for t in re.split(r'[|,]', raw)]
    if raw is None:
        tags = _legacy(rec.get('status')) or _legacy(rec.get('workflow_status'))
    else:
        tags = [t for t in raw if t in STAGES]
    return imply(tags)


def with_stage(tags, stage):
    """The stored tags after recording `stage`, with the tracker's own rules: an
    outcome (Booked, Rejected) retires the in-flight steps but keeps Submitted.
    Stores what happened; the tracker implies earlier steps when it displays."""
    tags = [t for t in (tags or []) if t in STAGES]
    if stage == 'Booked':
        tags = [t for t in tags if t not in ('Rejected', 'Initial outreach', 'Followed up')]
    elif stage == 'Rejected':
        tags = [t for t in tags if t not in ('Initial outreach', 'Followed up', 'Booked')]
    if stage not in tags:
        tags.append(stage)
    return [s for s in STAGES if s in tags]


def raw_stages(row):
    """A row's literal stage tags, for writing back (no implied steps)."""
    raw = row.get('status_tags')
    if isinstance(raw, str):
        raw = [t.strip() for t in re.split(r'[|,]', raw)]
    if raw is None:
        return _legacy(row.get('status')) or _legacy(row.get('workflow_status'))
    return [t for t in raw if t in STAGES]


# ── Who, routes and contacts ───────────────────────────────────────────────
def _names(v):
    if isinstance(v, str):
        v = re.split(r'[,;/&]| and ', v)
    return [fold(x).strip() for x in (v or []) if str(x or '').strip()]


def engaged(rec, person):
    if any(person in n for n in _names(rec.get('speaker'))):
        return True
    return any(n.split()[0] == person for f in LIST_FIELDS for n in _names(rec.get(f)) if n)


def other_speaker(rec, person):
    sp = _names(rec.get('speaker'))
    return bool(sp) and not any(person in n for n in sp)


_URL = re.compile(r'https?://[^\s)\]\'"<>]+')
_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_LI = re.compile(r'https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_%\-]+/?', re.I)


def apply_link(rec):
    if str(rec.get('apply_url') or '').startswith(('http://', 'https://')):
        return rec['apply_url'].strip()
    m = _URL.search(str(rec.get('speaking_route') or ''))
    return m.group(0).rstrip('.,;:') if m else ''


def contact(rec):
    """The organiser contact on file. Structured fields first, then anything
    already written in the free-text contact field. Nothing is guessed."""
    name, email, li = (str(rec.get('poc_name') or '').strip(), str(rec.get('poc_email') or '').strip(),
                       str(rec.get('poc_linkedin') or '').strip())
    info = str(rec.get('contact_info') or '')
    if not email:
        m = _EMAIL.search(info)
        email = m.group(0) if m else ''
    if not li:
        m = _LI.search(info)
        li = m.group(0) if m else ''
    if not name and info and (email or li):
        head = re.split(r'[(\u2014\u2013\-:,<]|https?://|\S+@', info, maxsplit=1)[0].strip()
        if 1 <= len(head.split()) <= 4 and not re.search(r'\d', head):
            name = head
    if li and not _LI.match(li):
        li = ''
    if email and not _EMAIL.fullmatch(email):
        email = ''
    if not (name or email or li):
        return None
    return {'name': name, 'email': email.lower(), 'linkedin': li, 'note': str(rec.get('poc_note') or '').strip()}


def call_state(rec, today):
    """('open'|'closed'|'unknown', closes date or None) for the event's call."""
    sz = (rec.get('booking') or {}).get('sessionize_call') or {}
    closes = parse_day(sz.get('closes')) if sz else None
    if sz.get('status') == 'closed':
        return 'closed', closes
    dl_txt = str(rec.get('deadline') or '')
    dl = parse_day(dl_txt) if len(dl_txt) <= 40 else None
    if closes is None and dl and not re.search(r'early.?bird|registration|hotel|ticket|pricing|nominations?', dl_txt, re.I):
        closes = dl
    if re.search(r'\b(cfp|call)\b[^.;]*\bclosed\b|^\s*closed\b', dl_txt, re.I):
        return 'closed', closes
    if closes and closes < today:
        return 'closed', closes
    if sz.get('status') in ('open', 'not_open_yet') or closes:
        return 'open', closes
    return 'unknown', closes


def pay_state(rec):
    """'free' | 'mixed' | 'pays'. 'Yes' with an open application is mixed."""
    p = fold(rec.get('pay_to_play')).strip()
    if p in ('both', 'mix', 'mixed', 'partial'):
        return 'mixed'
    if p == 'yes':
        route = fold(rec.get('speaking_route'))
        if apply_link(rec) or re.search(r'apply|call for|submit|speaker interest|proposal', route):
            if not re.search(r'sponsor|package|paid', route):
                return 'mixed'
        return 'pays'
    return 'free'


def lane_for(rec, today, link_fn=None):
    """The most direct route to a speaking slot, in the order Thor asked for:
    an application link first, then the organiser."""
    sz_link = link_fn(rec) if link_fn else ''
    state, _ = call_state(rec, today)
    if sz_link and state != 'closed':
        return 'sessionize'
    if apply_link(rec) and state != 'closed' and not re.search(r'sessionize\.com', apply_link(rec), re.I):
        return 'form'
    c = contact(rec) or {}
    if c.get('linkedin'):
        return 'linkedin'
    if c.get('email'):
        return 'email'
    return 'find'


# ── Receipts and timing ────────────────────────────────────────────────────
def receipts(rec):
    """Every dated record of something actually done, newest first."""
    out = []
    for f in rec.get('follow_ups') or []:
        d = parse_day(f.get('on'))
        if d:
            out.append({'on': d.isoformat(), 'by': f.get('by') or '', 'note': f.get('note') or '',
                        'channel': f.get('channel') or '', 'text': f.get('text') or '', 'to': f.get('to') or ''})
    sub = parse_day(rec.get('submitted_at'))
    if sub and not any(r['on'] == sub.isoformat() for r in out):
        out.append({'on': sub.isoformat(), 'by': '', 'note': 'Submitted', 'channel': '', 'text': '', 'to': ''})
    bk = rec.get('booking') or {}
    if bk.get('accepted_via') == 'sessionize':
        d = parse_day(bk.get('speaking_booked_at'))
        out.append({'on': d.isoformat() if d else '', 'by': 'Sessionize check',
                    'note': 'Accepted on Sessionize', 'channel': 'sessionize', 'text': '', 'to': ''})
    return sorted(out, key=lambda r: r['on'], reverse=True)


def last_touch(rec):
    days = [parse_day(r['on']) for r in receipts(rec)]
    days = [d for d in days if d]
    return max(days) if days else None


_HOLD = re.compile(r"on hold|come back to us|get back to us|will (be in touch|reach out|let us know)|"
                   r"do ?n.?t (chase|follow up)|no need to follow|waiting (on|for) them", re.I)
_SHUT = re.compile(r'sponsorship only|declin|not accepting|no opening|passed on us', re.I)


def follow_interval(rec, today, cfg):
    if rec.get('_start'):
        d = (rec['_start'] - today).days
        if 0 <= d <= 10:
            return cfg['follow_up_imminent_days']
        if 0 <= d <= 35:
            return cfg['follow_up_near_days']
    return cfg['follow_up_days']


# ── The weekly selection ───────────────────────────────────────────────────
def fit_of(rec, person):
    prof = PROFILES.get(person) or {}
    blob = words_blob(rec.get('_blob'))
    if has_kw(blob, prof.get('kw') or []):
        return 'profile'
    if engaged(rec, person):
        return 'engaged'
    if has_kw(blob, prof.get('broad_kw') or []) and fold(rec.get('audience_type')) != 'mixed':
        return 'broad'
    return ''


def screen(rec, today, cfg, person, link_fn=None):
    """Why an event is or is not a new item for this week.
    Returns (None, info) when it qualifies, else (reason, None)."""
    if rec.get('hidden'):
        return 'archived', None
    start = rec.get('_start')
    if not start or start < today:
        return 'past or no date', None
    days = (start - today).days
    if days > cfg['max_days_out']:
        return 'more than 12 months out', None
    if any(s in rec['stages'] for s in IN_FLIGHT + ('Booked', 'Rejected', 'Attending')):
        return 'already in flight', None
    op = (rec.get('booking') or {}).get('operator') or {}
    if op.get('status') == 'sent':
        return 'already sent', None
    if op.get('status') == 'skipped' and (op.get('skip') or {}).get('reason') != 'not_this_week':
        return 'skipped', None
    if other_speaker(rec, person):
        return "another speaker's", None
    prof = PROFILES.get(person) or {}
    if is_hr(rec):
        return 'HR or L&D', None
    if prof.get('no_clinical') and is_clinical(rec):
        return 'clinician audience', None
    if is_africa(rec):
        return 'Africa', None
    if prof.get('english_only') and is_foreign(rec):
        return 'not in English', None
    if _SHUT.search(str(rec.get('workflow_status') or '')):
        return 'door closed', None
    pay = pay_state(rec)
    if pay == 'pays':
        return 'pay to play', None
    fit = fit_of(rec, person)
    if not fit:
        return 'not a fit', None
    lane = lane_for(rec, today, link_fn)
    state, closes = call_state(rec, today)
    if lane in ('sessionize', 'form'):
        if days < cfg['apply_min_days']:
            return 'too soon to apply', None
    elif days < cfg['outreach_min_days']:
        return 'too soon for outreach', None
    urgent = bool(closes and 0 <= (closes - today).days <= cfg['urgent_close_days'])
    flags = []
    if pay == 'mixed':
        flags.append('Mixed: check the free route')
    if fit == 'broad':
        flags.append('Broader fit')
    if urgent:
        flags.append('Closes %s' % closes.strftime('%b %-d'))
    return None, {'lane': lane, 'fit': fit, 'urgent': urgent, 'closes': closes.isoformat() if closes else '',
                  'major': fold(rec.get('priority')) == 'high', 'flags': flags, 'days_out': days,
                  'call': state}


def select_week(records, today, cfg=None, person='thor', link_fn=None):
    """The new items for this week, plus what was left out and why."""
    cfg = dict(DEFAULTS, **(cfg or {}))
    picked, left = [], {}
    for rec in records:
        why, info = screen(rec, today, cfg, person, link_fn)
        if why:
            left[why] = left.get(why, 0) + 1
            continue
        picked.append((rec, info))
    fit_rank = {'profile': 0, 'engaged': 0, 'broad': 1}
    # Urgent calls first, then the profile/engaged events, then broad fill; each by date.
    picked.sort(key=lambda p: (0 if p[1]['urgent'] else 1, fit_rank[p[1]['fit']], p[0]['_start'], fold(p[0].get('name'))))
    chosen = picked[:cfg['weekly_target']]
    chosen.sort(key=lambda p: (p[0]['_start'], fold(p[0].get('name'))))   # shown in date order
    return {'items': chosen, 'eligible': len(picked), 'left_out': left,
            'shortfall': max(0, cfg['weekly_target'] - len(chosen))}


def live_lists(records, today, cfg=None, person='thor'):
    """What the screen shows besides the batch, computed fresh on every load:
    attending, out now, follow-ups due, losses to thank, and stages with no record."""
    cfg = dict(DEFAULTS, **(cfg or {}))
    attending, out, follow, losses, needs = [], [], [], [], []
    for rec in records:
        if rec.get('hidden'):
            continue
        start, end = rec.get('_start'), rec.get('_end')
        tags = rec['stages']
        # Thor is the default speaker: events nobody is named on are shown to him
        # marked "No speaker set", so old applications are claimed or cleared.
        unassigned = not _names(rec.get('speaker')) and not engaged(rec, person)
        if not engaged(rec, person) and not (unassigned and person == DEFAULTS['person']):
            continue
        rec['_unassigned'] = unassigned
        if 'Booked' in tags or 'Attending' in tags:
            if end and end >= today and not unassigned:
                attending.append({'rec': rec, 'role': 'Speaking' if 'Booked' in tags else 'Attending'})
            continue
        live = [t for t in IN_FLIGHT if t in tags]
        if 'Rejected' in tags:
            op = (rec.get('booking') or {}).get('operator') or {}
            rej = parse_day((op.get('outcome') or {}).get('at')) if (op.get('outcome') or {}).get('outcome') == 'rejected' else None
            if rej and (today - rej).days <= cfg['loss_lookback_days'] and not op.get('loss_sent'):
                losses.append({'rec': rec, 'rejected_on': rej.isoformat()})
            continue
        if 'Booked' in tags or not live:
            continue
        if not end or end < today - dt.timedelta(days=cfg['out_grace_days']):
            continue
        lt = last_touch(rec)
        if not lt:
            needs.append({'rec': rec, 'stage': live[-1]})
            continue
        every = follow_interval(rec, today, cfg)
        due = lt + dt.timedelta(days=every)
        hold = bool(_HOLD.search(str(rec.get('notes') or ''))) or bool(_SHUT.search(str(rec.get('workflow_status') or '')))
        item = {'rec': rec, 'stage': live[-1], 'last_touch': lt.isoformat(), 'waiting_days': (today - lt).days,
                'follow_up_on': due.isoformat(), 'hold': hold}
        out.append(item)
        if not hold and due <= today and 'Meeting held' not in tags and start and start >= today:
            follow.append(item)
    attending.sort(key=lambda x: x['rec']['_start'] or dt.date.max)
    out.sort(key=lambda x: x['follow_up_on'])
    follow.sort(key=lambda x: x['rec']['_start'] or dt.date.max)
    needs.sort(key=lambda x: x['rec']['_start'] or dt.date.max)
    return {'attending': attending, 'out': out, 'follow_ups': follow[:cfg['follow_up_cap']],
            'losses': losses, 'needs_record': needs}


# ── Drafts that need no model ──────────────────────────────────────────────
def follow_up_text(rec, c, speaker='Thor'):
    first = first_name((c or {}).get('name'))
    hi = ('Hi %s,' % first) if first else 'Hi,'
    return no_dashes('%s following up on my note about speaking at %s. Happy to send a short abstract, '
                     'or shape the session around what your audience most needs this year. %s'
                     % (hi, rec.get('name') or 'your event', speaker))


def loss_text(rec, c, speaker='Thor'):
    first = first_name((c or {}).get('name'))
    hi = ('Hi %s,' % first) if first else 'Hi,'
    return no_dashes('%s thank you for considering me for %s. If a slot opens late, or for next year\'s '
                     'program, I would be glad to help. Any feedback on what you were looking for would '
                     'help me pitch better next time. %s' % (hi, rec.get('name') or 'your event', speaker))


def gmail_url(to, subject, body):
    q = {'view': 'cm', 'fs': '1', 'to': to or '', 'su': subject or '', 'body': body or ''}
    return 'https://mail.google.com/mail/?' + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def linkedin_search_url(rec):
    name = re.sub(r'\b(19|20)\d{2}\b', '', str(rec.get('name') or '')).strip()
    return ('https://www.linkedin.com/search/results/people/?keywords=' +
            urllib.parse.quote(name + ' program director'))


_NUM = re.compile(r'\d[\d,.]*')


def unsourced_numbers(texts, sources):
    allowed = {n.replace(',', '').rstrip('.') for n in _NUM.findall(sources or '')}
    found = []
    for t in texts:
        for n in _NUM.findall(t or ''):
            n = n.replace(',', '').rstrip('.')
            if n and n not in allowed and n not in found:
                found.append(n)
    return ['Check this number, it is not in the talk, the bio or the event: ' + n for n in found]


def tidy_message(raw, cfg, sources):
    """Model output -> what is stored and shown. Length and dash rules are
    enforced here, not trusted to the model."""
    raw = raw if isinstance(raw, dict) else {}
    note = clip(no_dashes(raw.get('linkedin_note')), cfg['linkedin_note_max'])
    msg = clip(no_dashes(raw.get('linkedin_message')), cfg['linkedin_message_max'])
    subject = clip(no_dashes(raw.get('email_subject')), 90)
    body = no_dashes(raw.get('email_body'))
    words = body.split()
    if len(words) > cfg['email_words_max'] + 20:
        body = clip(body, len(' '.join(words[:cfg['email_words_max']])) + 1)
    out = {'talk_id': str(raw.get('talk_id') or ''), 'why_this_talk': clip(no_dashes(raw.get('why_this_talk')), 300),
           'linkedin_note': note, 'linkedin_message': msg, 'email_subject': subject, 'email_body': body.strip()}
    out['checks'] = unsourced_numbers([note, msg, subject, body], sources)
    return out
