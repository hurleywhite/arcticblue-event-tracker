-- ====================================================================
-- ArcticBlue Event Tracker — follow-up log
--
-- This is Angela's spreadsheet "Follow Ups" column ("6/24, 7/20", "April,
-- June") turned into real data: each entry carries WHEN, WHO, and optionally
-- what came back.
--
--   follow_ups  jsonb   [{"on":"2026-07-20","by":"Angela","note":"chased Ciara"}]
--
-- Deliberately NOT added:
--
--   a "door" column. Whether a door is closed is already expressed — a
--   Rejected stage, or a workflow_status in the Closed group ("Sponsorship
--   Only" is already one of its values). Adding a second field for the same
--   fact would let them disagree, which is how "Rejected" ended up also
--   reading as "Pending" in three different places.
--
--   a "next follow-up" date. It is derived: 14 days after the last entry,
--   unless the door is closed or the notes say to wait (a named future month,
--   "on hold", "they'll come back to us"). Storing it would go stale the
--   moment a note changed.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq. Until it runs, the follow-up UI reads as empty
-- and logging one fails with the app's standard migration-pending warning;
-- nothing else is affected.
-- ====================================================================

alter table public.event_state   add column if not exists follow_ups jsonb;
alter table public.manual_events add column if not exists follow_ups jsonb;

-- Sanity: confirm the column exists on both tables.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'follow_ups'
order by table_name;
