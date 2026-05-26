# Handoff — ArcticBlue Event Tracker

For the next AI agent or engineer picking this up.

---

## What's done

### Phase 1 — public read-only page (shipped May 2026)
- ✅ Parses 82 events from `data/events.json` (canonical) or the source .docx (legacy fallback)
- ✅ Auto-buckets into TODAY / UPCOMING / ARCHIVED based on `date.today()` (or `BUILD_DATE` env override)
- ✅ Auto-archives events whose end-date is in the past
- ✅ White-primary aesthetic; Hanken Grotesk + Fragment Mono; ArcticBlue logo + #2773c2 accent
- ✅ KPI strip, today/up-next callout, filters (search / priority / region / type)
- ✅ Verified URL linking — only renders ↗ for events with URLs in `event-urls-from-doc.json` or `event-urls-manual.json`
- ✅ Mobile responsive
- ✅ Live on Vercel

### Phase 2 — Supabase auth + ops state for Angela (shipped May 2026)
- ✅ Supabase project `efkvhlmfdwlobvdmvqiq` ("AB Event Tracker [Hurley's Org]")
- ✅ Schema: `allowed_editors`, `event_state`, `manual_events` (see `supabase/migrations/0001_init.sql`)
- ✅ RLS gates writes to `auth.email() in allowed_editors`; reads are public
- ✅ Magic-link sign-in in the "For Angela" tab
- ✅ Allow-list = `angela@arcticblue.ai`, `hurley@arcticblue.ai`, `thor@arcticblue.ai`
- ✅ Per-event ops: Saved ★, Urgent, Hidden, Status, Speaker, Priority override, Track, Notes
- ✅ Inline status/speaker/priority/track badges on cards (no need to open Edit)
- ✅ "Last edit · email · timestamp" per card
- ✅ + Add event form writes to `manual_events`; Edit / Delete on manual events

### Phase 3 — power tools (shipped May 2026)
- ✅ Stats summary bar (Upcoming · Saved · Urgent · Speaker set · Status set · Hidden)
- ✅ Filter bar (search · region · Saved only · Urgent only · Has speaker · Show hidden)
- ✅ Grid / Calendar view toggle (selection persists in `localStorage`)
- ✅ Month-by-month calendar with region-color chips, speaker initials, click-to-jump
- ✅ Realtime updates via Supabase channel — multi-tab live sync
- ✅ Paste-email field extractor (heuristic regex pulls name/date/location/region/URL)
- ✅ CSV import/export of `event_state` with diff preview before commit
- ✅ One-shot iCal download of currently-saved events

### Phase 4 — calendar feed + automation (shipped May 2026)
- ✅ Public iCal feed at `/calendar.ics` — every saved event + every manual event, regenerated daily
- ✅ "Subscribe in calendar app" button with copy-link + paste instructions for Apple / Google / Outlook
- ✅ Manual events store `start_date` + `end_date` (including cross-month ranges) so the feed shows correct multi-day blocks
- ✅ GitHub Action `daily-build.yml` runs at 09:00 UTC and on-demand; only commits when content actually changed
- ✅ `TODAY` defaults to `date.today()`; pinnable via `BUILD_DATE` env var
- ✅ Parser QA: 4 parsers × 5 samples each = 54 assertion checks; bugs found and fixed

---

## What's NOT done — ranked by impact

### High value

1. **Backfill remaining events without verified URLs.** Open the source `.docx` (or whatever new event sources arrive), visit each event in a browser, paste the verified URL into `data/event-urls-manual.json`. Don't guess — only add URLs that load a real page about the event.

2. **Specific start times on events.** Today everything in the iCal feed is all-day. If Angela wants "9am keynote" on the calendar, the schema needs `start_time` / `end_time` columns (nullable), plus form fields and ICS `DTSTART;VALUE=DATE-TIME` output. Roughly a one-hour change.

3. **Email-to-event automation.** Today the paste-email extractor is manual (Angela pastes an email into a textarea). A backend service that *receives* emails and runs the same extractor → inserts into `manual_events` directly would close the loop. Options: Cloudflare Email Workers, Supabase Edge Function with a Postmark inbound webhook, or a Resend route. Needs DNS + service setup.

### Medium value

4. **Per-user iCal feeds.** Today `/calendar.ics` is one shared feed of everything-saved. If different team members want their own shortlists, we'd need `/calendar/<token>.ics` with signed URLs. A small Supabase Edge Function could handle it.

5. **Slack notification on new manual event.** Supabase database webhook → Slack incoming-webhook URL on every `manual_events` insert. Two-line config job.

6. **Map view.** Each event has a city/country. A choropleth or pin map of upcoming events would be visually compelling. Use a vector world SVG (Natural Earth) — do NOT load Mapbox from a third-party CDN.

7. **Tier-level prioritization metadata.** The doc has richer info per event (pay-to-play, speaking deadline, contact email). Expose those on a card-flip or details disclosure.

### Polish

8. **A11y audit** — screen-reader testing on the today/up-next callout, sign-in flow, ops form.
9. **Print stylesheet** — Thor occasionally prints these. A `@media print` block that flattens to one column, removes filters, shows the URL inline.
10. **`utcnow()` deprecation** — `build.py` uses `datetime.utcnow()` which warns in Python 3.12+. Migrate to `datetime.now(datetime.UTC)`.

---

## What NOT to break

- **Cards without URLs are non-clickable.** Don't make the build invent URLs. Fill `event-urls-manual.json` after visiting in a browser.
- **White background, not dark.** Internal tool aesthetic. The marketing site at arcticblue.ai is dark — different register.
- **Single self-contained HTML file.** No webpack, no Vite, no Next.js conversion. The page must work via `file:///` for the public view (Supabase Auth needs HTTP origin — that's expected).
- **One single HTML file as the deploy target.** Don't split into a SPA without explicit ask.
- **No tracking / no analytics scripts.** The page is intentionally analytics-free.
- **Publishable key in HTML is OK; service-role key never is.** RLS is the security boundary.
- **The hardcoded TODAY is gone — don't put it back.** `date.today()` is what makes the daily build meaningful.

---

## Known gotchas

- **The `.docx` hyperlink XPath is fragile.** `extract-urls.py` reads `<w:hyperlink r:id=...>` elements. If the doc gets re-saved by a different Word version the relationship-XML structure may shift.

- **Cross-month date ranges only work in manual events.** Regular events (from `events.json`) get their range from Python `parse_date()` which handles cross-month. Manual events get theirs from the JS `deriveDatesFromText()` which also handles cross-month. Same logic, two languages — keep them in sync if you change one.

- **DTEND in the iCal feed is exclusive.** Per RFC 5545 for all-day events, `DTEND` is the day *after* the last day of the event. "June 1–4, 2026" emits `DTSTART:20260601` + `DTEND:20260605`. Don't "fix" this — it's correct.

- **The Supabase publishable key is embedded in the built HTML.** That's intentional — it's the anon/publishable role which RLS gates. Service-role keys must never appear in `src/build.py` or anywhere committed.

- **Vercel project switching.** This deploys to `arcticblue-event-tracker-deploy` (project id `prj_aIPEIr1LJVyx37aZ1wTqgzBszg2M`). GitHub auto-deploy is wired; manual `cd public && vercel deploy --prod --yes` still works.

- **iCloud-synced project paths are dangerous.** macOS's "Optimize Mac Storage" can evict `.git/objects/` and lock all git operations. Keep the working copy at `~/Developer/` or another non-iCloud location, not on Desktop.

---

## Files you can safely edit without breaking the build

- `data/event-urls-manual.json` — add manual URL overrides
- `data/events.json` — canonical event list (the Dust agent writes this in production)
- `data/ArcticBlue AI 2026 Event Tracker.docx` — legacy source (extract-urls.py reads it)
- `src/build.py` — generators (keep the no-hallucination contract intact)
- `public/arcticblue-logo.png` — swap the logo asset
- `supabase/migrations/0001_init.sql` — schema (re-runnable, idempotent)
- `.github/workflows/daily-build.yml` — cron schedule, build steps

## Files you should leave alone

- `public/index.html` — this is the BUILD OUTPUT. Edit `src/build.py`, not this file directly.
- `public/events.json` — same, generated by `build.py`.
- `public/calendar.ics` — generated by `build.py`.
- `public/.vercel/` — Vercel CLI link, gitignored.
