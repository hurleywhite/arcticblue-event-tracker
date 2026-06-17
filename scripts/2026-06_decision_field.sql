-- ====================================================================
-- ArcticBlue Event Tracker — Go / No-go decision state
--
-- WHY: the team wants an explicit pursue-or-pass decision per event,
-- separate from the pipeline stage. Stored as text: 'go' | 'no-go'
-- (null = undecided). Drives the card badge, the Planner conflict scan
-- (no-go events are excluded), and Angela's queue (no-go drops out of
-- "to apply"). text[] `interested` already exists from the prior migration.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS). Run in the Supabase SQL editor
-- for project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state   add column if not exists decision text;
alter table public.manual_events add column if not exists decision text;

-- Sanity: confirm the new columns exist.
select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'decision'
order by table_name;
