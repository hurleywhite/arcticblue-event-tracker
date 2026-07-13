-- ====================================================================
-- ArcticBlue Event Tracker — record WHEN a speaking application was submitted
--
-- WHY: for events at the "Submitted to speak" stage, Angela wants to note the
-- date the application actually went out, so the pipeline shows how long each
-- submission has been outstanding. It needs somewhere to live:
--   * catalog events -> event_state override column (submitted_at)
--   * manual events  -> manual_events column (submitted_at)
--
-- The "Submitted on" date picker only appears in Angela's Details editor, on
-- events tagged "Submitted", and the recorded date shows on the status line
-- ("Submitted to speak — Thor · submitted Jul 2") in her view.
--
-- Until you run this, setting a "Submitted on" date will fail with
-- "column submitted_at does not exist". Every other field keeps working, and
-- the status line simply omits the date.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS). Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state   add column if not exists submitted_at date;
alter table public.manual_events add column if not exists submitted_at date;

-- Sanity: confirm the new columns exist.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'submitted_at'
order by table_name;
