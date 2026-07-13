-- ====================================================================
-- ArcticBlue Event Tracker — "ask a teammate to reach out" assignment
--
-- WHY: Angela sometimes wants a specific teammate (say Thor) to make the
-- first contact for an event, because THEY have the personal connection to
-- the organizer / a speaker / the host. This records that ask so it lands at
-- the top of that teammate's My Lineup ("Angela asked you to reach out").
--   * catalog events -> event_state override columns
--   * manual events  -> manual_events columns
--
--   outreach_assignees : text[]  — teammates Angela asked to reach out
--                                  (lowercased first names, like `attendees`)
--   outreach_note      : text    — optional context ("you know their CEO")
--
-- Only Angela's Details editor shows the assignment control; the assigned
-- teammate sees the "Reach out" section at the top of their My Lineup.
--
-- Until you run this, assigning a teammate will fail with "column
-- outreach_assignees does not exist". Every other field keeps working.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS). Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state   add column if not exists outreach_assignees text[];
alter table public.event_state   add column if not exists outreach_note       text;
alter table public.manual_events add column if not exists outreach_assignees text[];
alter table public.manual_events add column if not exists outreach_note       text;

-- Sanity: confirm the new columns exist.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name in ('outreach_assignees', 'outreach_note')
order by table_name, column_name;
