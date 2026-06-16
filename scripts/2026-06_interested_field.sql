-- ====================================================================
-- ArcticBlue Event Tracker — "Interested (apply for me)" per-event field
--
-- WHY: teammates want to flag that they're interested in an event and want
-- Angela to submit a speaking application on their behalf. Stored as a list
-- of names (Thor / Jerome / Scott / Verma / Carlos / Jim / Joe) per event.
--
-- text[] array on BOTH tables. Idempotent. Run in the Supabase SQL editor
-- for project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state   add column if not exists interested text[];
alter table public.manual_events add column if not exists interested text[];
