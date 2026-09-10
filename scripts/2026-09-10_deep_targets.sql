-- ====================================================================
-- ArcticBlue Event Tracker — RUN THIS NEXT (Supabase SQL editor,
-- project efkvhlmfdwlobvdmvqiq). Additive only; safe to run twice.
--
-- This is the last known schema gap, and it is not cosmetic: it has been
-- silently disabling the ENTIRE nightly cron since 2026-06-21.
--
-- api/briefing.py::_cron opens with
--     GET /event_state?select=...,targets_json,targets_generated_at
-- Those columns don't exist, so PostgREST answers 400 ("column
-- event_state.targets_json does not exist"). `states` comes back an error
-- dict rather than a list, `smap` falls through to {}, and every event then
-- fails resolve_attendees({}) and hits `continue`. The job finishes with
-- done=[] and no exception -- a clean-looking run, every night, for ~11 weeks.
--
-- Blocked by this, nightly:
--   * Day-Of briefings   -- never generated for anyone
--   * Deep outreach targets -- never pre-cached
--
-- And on demand: cache_targets() no-ops on the missing column, so every open
-- of the targets panel re-runs OpenAI/Exa generation and re-spends the credit.
-- Verified against prod 2026-09-10.
-- ====================================================================

alter table public.event_state   add column if not exists targets_json          jsonb;
alter table public.event_state   add column if not exists targets_generated_at  timestamptz;

alter table public.manual_events add column if not exists targets_json          jsonb;
alter table public.manual_events add column if not exists targets_generated_at  timestamptz;

-- ── Verify: expect 4 rows ───────────────────────────────────────────
select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name in ('targets_json', 'targets_generated_at')
order by table_name, column_name;
