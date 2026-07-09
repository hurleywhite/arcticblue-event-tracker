-- ====================================================================
-- ArcticBlue Event Tracker — per-event team chat ("Chat with the team")
--
-- Adds a chat thread to every event: a small "💬 N" indicator shows on each
-- card, and opening an event shows the thread + a box to post a message.
--
-- NO sign-in required to post — same trust model as the rest of the tracker
-- (star, archive, edit fields): you just type who you are, and that's it.
-- Read AND write are both open (RLS is enabled mainly so future policies can
-- be tightened later without a schema change, and to keep delete/update
-- locked down since the UI never issues those).
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq.
--
-- NOTE: if you previously ran an earlier version of this script, re-running
-- this one replaces the old "allow-listed editors only" insert policy with
-- the open one below.
-- ====================================================================

create table if not exists public.event_chat (
  id         bigserial primary key,
  event_num  int,          -- catalog event (event_state.event_num); null for manual
  manual_id  bigint,       -- manual_events.id; null for catalog
  author     text not null,
  body       text not null,
  created_at timestamptz not null default now()
);

create index if not exists event_chat_num_idx    on public.event_chat (event_num);
create index if not exists event_chat_manual_idx on public.event_chat (manual_id);

alter table public.event_chat enable row level security;

-- Anyone can READ the thread (matches the rest of the app: read is open).
drop policy if exists event_chat_read on public.event_chat;
create policy event_chat_read on public.event_chat for select using (true);

-- Anyone can POST a message — no sign-in, just a typed name. A couple of
-- light sanity checks (non-empty, reasonable length) guard against garbage
-- since this endpoint is open to anyone with the public site's key.
drop policy if exists event_chat_insert on public.event_chat;
create policy event_chat_insert on public.event_chat for insert
  with check (
    length(trim(author)) > 0 and length(author) <= 100 and
    length(trim(body))   > 0 and length(body)   <= 2000
  );

-- Live updates across tabs / users.
do $$ begin
  alter publication supabase_realtime add table public.event_chat;
exception when duplicate_object then null; end $$;

-- Sanity: confirm the table + open insert policy.
select table_name from information_schema.tables
where table_schema = 'public' and table_name = 'event_chat';
select polname, permissive, roles, cmd from pg_policies where tablename = 'event_chat';
