-- ====================================================================
-- ArcticBlue Event Tracker — scheduling conflicts
--
-- Most conflicts don't need typing: the tracker already knows who is down for
-- what and when, so "the same person is on two events whose dates overlap" is
-- DERIVED and needs no column. (There were 99 such pairs the day this went in
-- — Thor alone was on three separate things on 3 Nov.)
--
-- This column is for the conflicts the dates can't reveal:
--   "Thor is at the board offsite that week"
--   "Verma is on leave"
--   "same week as the client onsite — can't travel"
--
-- Angela sets it in Details -> Edit -> "Scheduling conflict (optional)". It
-- shows as an amber chip on the card face and at the top of the hover peek,
-- alongside any automatically-detected clash.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq. Until it runs, automatic clash detection keeps
-- working (it needs no schema); only the typed note is unavailable, and the
-- app's standard "migration pending" warning covers the failed write.
-- ====================================================================

alter table public.event_state   add column if not exists conflict_note text;
alter table public.manual_events add column if not exists conflict_note text;

-- Sanity: confirm the column exists on both tables.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'conflict_note'
order by table_name;
