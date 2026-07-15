-- ====================================================================
-- ArcticBlue Event Tracker — make catalog events fully editable
--
-- WHY: manual events could always edit their name / date / location (those are
-- real manual_events columns). Catalog events (from data/events.json) could
-- only edit override fields, so the Details editor hid the Event name / Date /
-- Location inputs for them. These columns let a catalog event override its own
-- identity fields via event_state, exactly like every other override:
--
--   name        text  -- overrides the catalog title on the card + modal
--   date_str    text  -- free-text date shown on the card
--   start_date  date  -- structured dates that drive the card / calendar / iCal
--   end_date    date
--   location    text
--
-- The client applies these overrides at load (event_state value wins over the
-- catalog value), so the edited title/date/location show everywhere — grid,
-- Details, calendar, map, search, suggestions.
--
-- Until you run this, editing a CATALOG event's name / date / location fails
-- with "column ... does not exist" (manual events + every other field keep
-- working, and the card just shows the original catalog value).
--
-- Idempotent (ADD COLUMN IF NOT EXISTS). Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state add column if not exists name       text;
alter table public.event_state add column if not exists date_str   text;
alter table public.event_state add column if not exists start_date date;
alter table public.event_state add column if not exists end_date   date;
alter table public.event_state add column if not exists location   text;

-- Sanity: confirm the new columns exist.
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'event_state'
  and column_name in ('name', 'date_str', 'start_date', 'end_date', 'location')
order by column_name;
