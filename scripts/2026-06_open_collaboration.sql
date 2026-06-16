-- ====================================================================
-- ArcticBlue Event Tracker -- OPEN COLLABORATION (no login)
--
-- WHY: the team wants everyone to edit the tracker without signing in.
-- This relaxes Row-Level Security so the public (anon / publishable) key
-- can INSERT / UPDATE / DELETE on event_state and manual_events, not just
-- read. Until you run this, the merged collaborative view will load but
-- every save will FAIL (RLS denies anonymous writes).
--
-- TRADE-OFF (you chose this): anyone who has the site URL can edit or delete
-- events with no sign-in. There is no per-person protection. If you later
-- want to lock it back down, re-add the auth.email() allow-list policies
-- from supabase/migrations/0001_init.sql.
--
-- Idempotent: drops the old write policies and (re)creates open ones.
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

-- event_state: replace the email-gated write policies with an open one.
drop policy if exists es_write_insert on public.event_state;
drop policy if exists es_write_update on public.event_state;
drop policy if exists es_write_delete on public.event_state;
drop policy if exists es_open_all     on public.event_state;
create policy es_open_all on public.event_state
  for all using (true) with check (true);

-- manual_events: same.
drop policy if exists me_insert   on public.manual_events;
drop policy if exists me_update   on public.manual_events;
drop policy if exists me_delete   on public.manual_events;
drop policy if exists me_open_all on public.manual_events;
create policy me_open_all on public.manual_events
  for all using (true) with check (true);

-- Roster cleanup: remove Patrick (he was the speaker on event #177, which is
-- why he showed up as a filter chip). Carlos + Jim are added in the app's
-- speaker suggestion list, not here -- they'll appear as filter chips once
-- they're actually assigned to an event.
update public.event_state set speaker = null
where event_num = 177 and speaker = 'Patrick';

-- Sanity: list the live policies (expect es_open_all + es_read, me_open_all + me_read).
select tablename, policyname, cmd
from pg_policies
where schemaname = 'public'
  and tablename in ('event_state', 'manual_events')
order by tablename, policyname;
