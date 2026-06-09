-- ====================================================================
-- ArcticBlue Event Tracker -- Buyer-quality fields: pricing + audience_type
--
-- WHY (read before running):
--   ArcticBlue wants stage time in front of BUYERS (in-house enterprise
--   leaders / decision-makers who could become clients) -- NOT rooms full of
--   other AI vendors and sales reps selling to each other. To support that we
--   capture two new signals on every event:
--
--     pricing        text -- the cost to ATTEND (delegate/ticket price), e.g.
--                            '$2,495 delegate pass'. A high attend price + senior
--                            titles is a buyer-richness signal.
--     audience_type  text -- the read of who is actually in the room. One of
--                            'Buyer-rich' | 'Mixed' | 'Vendor-heavy' (free text,
--                            but the app + worthiness gate only emit those 3).
--
--   The worthiness gate (api/events.py) now scores buyer-richness and returns
--   an `audience` label; the For-Angela tab shows a colored audience badge and
--   a "Buyer-rich only" filter. Both write to these columns.
--
-- SAFE TO DEPLOY BEFORE RUNNING THIS: server ingest (_insert_one) and the
--   client write helper (sbWriteRetry) both detect a missing pricing/
--   audience_type column, strip it, and retry -- so events still save without
--   these columns; the new fields simply stay blank until this migration runs.
--
-- Idempotent: both ADDs use IF NOT EXISTS. Safe to re-run.
--
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq
-- ("AB Event Tracker [Hurley's Org]").
-- ====================================================================

-- -- 1 . manual_events: the two buyer-quality columns (both nullable) ----
alter table public.manual_events add column if not exists pricing       text;
alter table public.manual_events add column if not exists audience_type text;

-- -- 2 . Sanity report: confirm both columns now exist (expect 2 rows). --
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name   = 'manual_events'
  and column_name in ('pricing', 'audience_type')
order by column_name;
