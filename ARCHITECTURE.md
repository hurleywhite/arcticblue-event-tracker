# ArcticBlue Event Tracker — Architecture

A single-page event tracker for ArcticBlue's speaking/sponsorship pipeline. This
doc exists so an audit (human or AI) anchors on the **right** data stores — see
the "What is NOT part of this app" warning at the bottom.

## The shape of it

- **Frontend**: one static page, `public/index.html`, **generated** by a Python
  f-string generator at `src/build.py` (~8k lines). There is no framework and no
  build step on the server — Vercel just serves `public/` statically.
- **Build**: `BUILD_DATE=YYYY-MM-DD python3 src/build.py` writes
  `public/index.html`, `public/events.json`, and `public/calendar.ics`.
- **Deploy**: push `main` → Vercel auto-deploys `public/` (static) and the
  `api/*.py` serverless functions. (A daily job also commits a fresh build —
  `chore: daily auto-build` — so rebase on `origin/main` before pushing.)
- **Backend (serverless)**: `api/*.py`, Vercel Python functions.

## Where the data lives (the important part)

The data is **layered, not fragmented** — a curated base catalog joined to a
live tracking overlay by `event_num`:

| Layer | Store | What it holds |
|---|---|---|
| **Catalog (base list)** | `data/events.json` → `public/events.json` (in git) | The ~275 curated events: name, dates, location, why, url, etc. The only piece NOT in Supabase. |
| **Tracking overlay** | Supabase `event_state` (keyed by `event_num`) | Everything that *changes*: pipeline `status_tags`, `speaker`, `decision`, `saved`/`hidden`/`urgent`, `interested`, `attendees`, notes, `briefing_json`, `targets_json`, audience/price/venue overrides, `updated_by`/`updated_at`. |
| **Manual / AI-added events** | Supabase `manual_events` (keyed by `id`) | Events not in the catalog — added by hand or by the "Find events (AI)" ingest. Full event record + tracking fields. Tracks `created_by` (NOT `updated_by`). |
| **Warm-intro connections** | Supabase `connections` | Teammates' LinkedIn connection exports, matched locally for Deep-Targets "warm via X". Never sent to any AI API. |

**Supabase project:** `https://efkvhlmfdwlobvdmvqiq.supabase.co`. Tables:
`event_state`, `manual_events`, `connections`. (As of 2026-06-22: ~196
`event_state` rows, ~147 `manual_events` rows, actively written.)

### How a card is rendered
The client fetches `public/events.json` (catalog) + reads `event_state` and
`manual_events` from Supabase, then **merges**: every field reads `st.X || ev.X`
— the `event_state` override wins over the catalog value. Soft-delete sentinel:
`event_state.status = '__deleted__'` (filtered everywhere via `_deletedNums`);
`manual_events` rows are hard-deleted. The UI's "154 tracked · 100 manual"
counts are the *visible* (non-deleted, non-archived) subset of those rows.

### Source-of-truth note
The catalog (`data/events.json`) is the one store outside Supabase, and the one
real drift risk: it is curated/synced from a Replit "EventsCal" app. Match by
`title + date`, not by number, when reconciling Replit ↔ this repo.

## API endpoints (`api/*.py`)

| Endpoint | Purpose | Writes to | AI used |
|---|---|---|---|
| `POST /api/events` | "Find events (AI)" ingest of discovered events | `manual_events` | — (caller supplies events) |
| `POST /api/search` | Dust agent event search (candidate list) | — (returns to client) | Dust / Perplexity |
| `POST /api/vet` | "Fill from URL" — scrape a page into form fields | — (returns to client) | **Exa** fetch + **gpt-5.4** structure (Dust = no-key fallback) |
| `POST /api/enrich_one` | Per-event "Enrich" — fill missing fields | `event_state` **or** `manual_events` | Exa + Perplexity |
| `POST /api/enrich` | Nightly batch enrich sweep | `manual_events` | Exa + Perplexity |
| `POST /api/briefing` | Day-Of briefs + Deep outreach targets; `GET ?cron=1` overnight pre-gen | `event_state` / `manual_events` (`briefing_json`, `targets_json`) | **gpt-5.4** (web search) + **Exa** roster retrieval; Perplexity secondary |
| `POST /api/ask` | "Ask AI" chat (persona-aware) | — | gpt-5.4 |
| `GET /api/calendars` | Team iCal overlay (no OAuth) | — | — |
| `POST /api/mcp` | MCP endpoint | — | — |

**Models:** OpenAI **gpt-5.4** is the default for structuring/briefs/targets/ask
(requires `max_completion_tokens`, not `max_tokens`; has built-in web search).
**Exa** is the retrieval/scrape engine (reliably reaches agenda/event pages
where gpt-5.4's own search often can't). **Perplexity** is a secondary research
fallback. **Dust** is legacy (kept only as a no-OpenAI-key fallback in `vet.py`).

**Secrets** live in Vercel env only (never in the repo):
`OPENAI_API_KEY`, `EXA_API_KEY`, `PERPLEXITY_API_KEY`, `DUST_API_KEY`,
`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`EVENTS_INGEST_SECRET`, `CRON_SECRET`.

## Gotchas (have bitten before)

- **`manual_events` has `created_by`, NOT `updated_by`** (and DOES have `notes`).
  Writing `updated_by` to it makes PostgREST reject the *whole* patch
  (PGRST204). Only `event_state` has `updated_by`. Never stamp `updated_by` on a
  `manual_events` write.
- `src/build.py` is a Python f-string: literal JS/CSS braces are doubled
  `{{`/`}}`, regex backslashes are `\\`, and `{name}` is a Python substitution.
  Edit `src/build.py`, never `public/index.html` directly (it's regenerated).
- Schema changes need a SQL migration in `scripts/` run manually in Supabase
  (MCP write access is not configured). Writes degrade gracefully until run
  (`sbWriteRetry` strips not-yet-migrated columns).

## What is NOT part of this app (audit warning)

There is a **separate, unrelated Supabase project** ("Hurley's Agent Team") that
contains a stray ~47-row `events` table with an AI-relevance-scoring schema
(`relevance_score`, `approved_by`, …), frozen since April 2026. **The tracker
does not read or write that table.** It is leftover from an old experiment. If
an audit reports "47 rows, 100% pending, 2.5 months frozen," it is looking at
that dead table in the wrong project — not this app's backend.
