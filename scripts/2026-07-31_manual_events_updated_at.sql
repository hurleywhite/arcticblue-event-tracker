-- ====================================================================
-- ArcticBlue Event Tracker — an edit trail for manual_events
--
-- WHY: manual_events records created_at / created_by and nothing else, so
-- once a row exists there is no record that it ever changed, or who changed
-- it. event_state has had updated_at / updated_by all along; manual_events
-- never did. 426 of the ~656 tracked rows are manual, so this is the
-- majority of the data, not an edge case.
--
-- What it broke: "In the last week" now reports what actually changed on an
-- event (interest, status, notes, contacts). For a catalog event it dates
-- the change from event_state.updated_at. For a manual event there was
-- nothing to date it from, so the scan fell back to created_at — meaning an
-- edit to an event added three months ago looked three months old and fell
-- straight out of the 7-day window. Manual-event edits were invisible.
--
--   updated_at  timestamptz  when the row last changed
--   updated_by  text         who changed it (the app stamps a first name,
--                            same convention as event_state.updated_by)
--
-- The trigger maintains updated_at on EVERY update, including writes that
-- don't come from the app (SQL editor, a script, the Dust ingest). updated_by
-- is left to the caller, because the database cannot know which teammate is
-- sitting behind a shared publishable key.
--
-- Until this runs: the app already stamps both columns and sbWriteRetry
-- silently strips them when the schema lacks them, so saves keep working
-- exactly as they do today — manual-event edits simply stay out of the
-- activity feed. Deliberately NOT backfilled: there is no honest value to
-- put in updated_at for a row whose history was never recorded, and seeding
-- it with created_at would fabricate an edit trail. Existing rows report
-- their first real edit after this runs.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor
-- for project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.manual_events add column if not exists updated_at timestamptz;
alter table public.manual_events add column if not exists updated_by text;

-- Keep updated_at honest regardless of who writes the row.
create or replace function public.manual_events_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists manual_events_set_updated_at on public.manual_events;
create trigger manual_events_set_updated_at
  before update on public.manual_events
  for each row
  execute function public.manual_events_touch_updated_at();

-- The activity feed filters on "changed in the last 7 days", so index it.
create index if not exists manual_events_updated_at_idx
  on public.manual_events (updated_at desc);

-- Sanity: both columns present, trigger attached.
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'manual_events'
  and column_name in ('updated_at', 'updated_by')
order by column_name;

select tgname as trigger_name
from pg_trigger
where tgrelid = 'public.manual_events'::regclass
  and not tgisinternal;
