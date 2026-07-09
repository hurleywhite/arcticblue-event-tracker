-- ====================================================================
-- ArcticBlue Event Tracker — per-event team chat (the "Discussion" thread)
--
-- Adds a Discussion thread to every event: a small "💬 N" indicator shows on
-- each card, and opening an event shows the thread + a box to post a message.
-- Read is open (like the rest of the app); only allow-listed editors can post.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq. Until this runs, the Discussion panel shows a
-- "needs a one-time database setup" note and no counts appear.
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

-- Public can READ the thread (matches the rest of the app: read is open).
drop policy if exists event_chat_read on public.event_chat;
create policy event_chat_read on public.event_chat for select using (true);

-- Only allow-listed editors can POST a message.
drop policy if exists event_chat_insert on public.event_chat;
create policy event_chat_insert on public.event_chat for insert
  with check (auth.email() in (select email from public.allowed_editors));

-- Live updates across tabs / users.
do $$ begin
  alter publication supabase_realtime add table public.event_chat;
exception when duplicate_object then null; end $$;

-- Sanity: confirm the table exists.
select table_name from information_schema.tables
where table_schema = 'public' and table_name = 'event_chat';
