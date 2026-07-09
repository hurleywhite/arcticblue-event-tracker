-- ====================================================================
-- ArcticBlue Event Tracker — dismiss an event from Angela's apply queue
--
-- Adds a small "×" next to "Mark applied" in the Queue's "To apply" section,
-- so an event that isn't actually relevant can be taken off the queue WITHOUT
-- lying that someone applied to it. It does NOT touch the "interested" list
-- (nobody's star/flag is removed) — it just stops that one item from showing
-- in the queue.
--
-- If a teammate later flags interest again on a dismissed event, the flag
-- automatically un-dismisses it so it shows back up in the queue.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq. Until this runs, the × still works in the UI
-- for the current session but the dismissal won't be saved (the app will
-- warn "could not be stored" — see the app's standard migration-pending note).
-- ====================================================================

alter table public.event_state   add column if not exists queue_dismissed boolean;
alter table public.manual_events add column if not exists queue_dismissed boolean;

-- Sanity: confirm the new columns exist.
select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'queue_dismissed'
order by table_name;
