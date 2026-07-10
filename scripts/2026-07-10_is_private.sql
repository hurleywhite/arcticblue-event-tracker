-- ====================================================================
-- ArcticBlue Event Tracker — "Private event" flag.
--
-- Adds an editable is_private toggle to events. When an event is marked
-- private (an invite-only dinner, a private roundtable, …), the Details
-- pop-up hides the public-conference fields (about / audience / pricing /
-- focus areas / etc.) and shows just POC, link, notes and the chat.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor
-- for project efkvhlmfdwlobvdmvqiq. Until it runs, ticking "Private event"
-- won't stick (the app warns that the column is missing).
-- ====================================================================

alter table public.event_state   add column if not exists is_private boolean;
alter table public.manual_events  add column if not exists is_private boolean;

-- Sanity: confirm the columns exist.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'is_private'
order by table_name;
