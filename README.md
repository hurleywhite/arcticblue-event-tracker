# ArcticBlue Event Tracker

Internal tracker for every in-person AI event ArcticBlue is considering. Public, read-only for everyone; editing (interest, pipeline stage, speaker, priority, notes, manual events) is gated to an ArcticBlue editor allow-list. Daily auto-build, Vercel-hosted, Supabase-backed.

**Live:** https://arcticblue-event-tracker-deploy.vercel.app/
**Public calendar feed:** https://arcticblue-event-tracker-deploy.vercel.app/calendar.ics

---

## Two audiences: read vs. edit

It's **one app** — everyone can read it; signing in unlocks editing.

- **Anyone (no login)** — the whole tracker is public and read-only. Browse every tracked event across four views — **My Events · All Events · Calendar · Map** — with a stats bar (Upcoming · My Interests · Pending · Booked · Team Interests · Attending) and filters (keyword search · **Pipeline · Region · Fits · Months**). **Click any card** to open its full detail pop-up. Cards show date, location, type, a **priority** read (High / Medium / Low), pipeline **stage** (Submitted = blue, Booked = green, …), an **Apply to speak** link, and verified event URLs only (no invented URLs — see AGENT-CONTEXT.md Rule 2). An **Ask Anything** AI box ranks and answers questions over the current events.

- **ArcticBlue editors (magic-link sign-in)** — editing is gated to team emails on the `allowed_editors` allow-list (managed in Supabase). RLS on `event_state` and `manual_events` blocks any other authenticated user even if they bypass the UI. Pick who you are ("Viewing as …") and you can:
  - **★ Star events you're interested in** — feeds the per-person **My Events** view and the My / Team Interests stats
  - **Set pipeline stage, speaker, priority, notes and links** from a card's detail pop-up → **Edit**
  - **Archive** events you're setting aside (from the pop-up; the card then shows an "Archived" label)
  - **+ Add event** by hand, or **Paste email** / web copy to auto-extract name / date / location / URL
  - **Find new events** — AI web search that adds fresh in-person events to the catalog
  - **Download saved `.ics`** or **subscribe** to the always-fresh public calendar feed (Apple / Google / Outlook)
  - **Realtime** — a Supabase channel keeps multiple tabs / users in sync without a refresh

---

## Repo layout

```
arcticblue-event-tracker/
├── README.md                          ← this file
├── HANDOFF.md                         ← what's done, what's next, what NOT to break
├── AGENT-CONTEXT.md                   ← rules for the AI agent improving this
├── .github/workflows/daily-build.yml  ← scheduled rebuild at 09:00 UTC
├── data/
│   ├── ArcticBlue AI 2026 Event Tracker.docx   ← legacy bootstrap fallback
│   ├── events.json                              ← canonical events list
│   ├── event-urls-from-doc.json                 ← extracted hyperlinks
│   └── event-urls-manual.json                   ← manual URL overrides
├── src/
│   ├── extract-urls.py                ← parses hyperlinks out of the .docx
│   ├── build.py                       ← renders public/index.html + events.json + calendar.ics
│   ├── dust_client.py                 ← Dust agent helper
│   └── ingest_block.py                ← Dust agent ingest entry-point
├── public/                            ← deploy target (gitignored .vercel/ inside)
│   ├── index.html                     ← built page
│   ├── events.json                    ← robot-readable companion (Dust agent reads this)
│   ├── calendar.ics                   ← public iCal feed, regenerated daily
│   └── arcticblue-logo.png
└── supabase/migrations/
    └── 0001_init.sql                  ← allowed_editors · event_state · manual_events · RLS
```

---

## Daily build

A GitHub Action (`.github/workflows/daily-build.yml`) runs **09:00 UTC every day** plus on-demand via `workflow_dispatch`. It re-runs `src/build.py`, which:

1. Reads `data/events.json` (the canonical event list)
2. Renders `public/index.html` with Today / Upcoming / Archived buckets based on `date.today()`
3. Writes `public/events.json` (companion for the Dust agent)
4. Hits Supabase REST for `event_state` + `manual_events`, writes `public/calendar.ics`
5. Commits + pushes only if `public/` actually changed

Vercel auto-deploys on push, so the live site and the calendar feed stay current without manual intervention.

To trigger manually: `gh workflow run "Daily auto-build"`.

---

## Manual build (rare — usually only when iterating locally)

```bash
python3 src/build.py
# Optional: pin a snapshot date for reproducible builds
BUILD_DATE=2026-05-21 python3 src/build.py
```

Outputs:
- `public/index.html`
- `public/events.json`
- `public/calendar.ics` (best-effort — Supabase fetch failure is non-fatal; existing file is left in place)

---

## Manual deploy (rare — auto-deploy handles the normal case)

```bash
cd public && vercel deploy --prod --yes
```

---

## How to add a verified URL for an event

The build only links cards whose URLs come from one of:
- `data/event-urls-from-doc.json` — extracted from the source `.docx`
- `data/event-urls-manual.json` — manually curated after a real visit

To add one manually:

1. Edit `data/event-urls-manual.json`
2. Add an entry like `"31": "https://www.ai-bigdataexpo.com/north-america/"` (key is event num; value is a verified URL)
3. Re-run `python3 src/build.py` (or just commit — the daily build will pick it up)

**Never invent URLs.** See AGENT-CONTEXT.md Rule 2.

---

## Tech stack

- **Build:** Python 3.11 + stdlib (`urllib`, `json`, `re`, `datetime`). No third-party deps required at build time (the lazy `python-docx` import is only used as a fallback when `events.json` is missing).
- **Frontend:** Single self-contained HTML file with inline CSS + JS. No bundler, no framework, no React. Page must still work when opened with `file:///` (auth tab won't, but the public read-only view will).
- **Auth + data:** Supabase (Postgres + Auth + Realtime). Magic-link sign-in; RLS gates writes on `auth.email() in allowed_editors`.
- **Hosting:** Vercel — auto-deploys on push to `main`. `public/` is the deploy root.
- **Fonts:** Hanken Grotesk + Fragment Mono from Google Fonts. No other third-party CDNs except the Supabase JS client.

---

## Database schema

`supabase/migrations/0001_init.sql` defines three tables:

- `allowed_editors (email PK, added_by, created_at)` — whitelist of editor emails. Public read; not writable from the client (admin via SQL Editor only).
- `event_state (event_num PK, status, speaker, priority_override, track, saved, hidden, urgent, notes, updated_by, updated_at)` — ops mutations per event, keyed on the integer `num` from `events.json`. Public read; writes gated to `auth.email() in allowed_editors` by RLS.
- `manual_events (id bigserial PK, name, date_str, start_date, end_date, location, region, type, priority, why, url, created_by, created_at)` — events added through the For Angela tab's "+ Add event" form. Same RLS rules.

Realtime publication is enabled on both `event_state` and `manual_events` so the For Angela tab updates live across tabs / users.

---

## Pointers for the next AI agent

Read **`AGENT-CONTEXT.md`** before changing anything. The most important rules:

1. **No invented URLs.** If you don't have a verified URL, the card stays unlinked.
2. **White-primary aesthetic.** Internal ArcticBlue tools are white-on-black with a single blue accent. Don't pivot to dark mode without explicit user direction.
3. **Single self-contained HTML file** for the public view. No build chains, no React, no bundlers.
4. **The source `.docx` is the seed.** Once `events.json` exists it's the source of truth for the public catalog; the docx is legacy bootstrap.
5. **Supabase publishable key is safe in HTML** — RLS protects the data. Service-role keys must never appear in the build output.

See `HANDOFF.md` for the prioritized improvement list.
