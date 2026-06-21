-- Warm-intro connections: each teammate uploads their LinkedIn connections
-- export (CSV) so Deep Targets can flag "warm via <teammate>" when a surfaced
-- person is in someone's network. This data stays in our DB and is matched
-- LOCALLY in api/briefing.py — it is NEVER sent to OpenAI/Exa.
--
-- Safe to run more than once.

create table if not exists public.connections (
  id            bigint generated always as identity primary key,
  owner         text not null,          -- teammate roster key (e.g. 'thor','jerome')
  full_name     text not null,          -- lower(first + ' ' + last) for matching
  display_name  text,                   -- original "First Last"
  company       text,
  position      text,
  profile_url   text,
  created_at    timestamptz default now()
);

create index if not exists connections_full_name_idx on public.connections (full_name);
create index if not exists connections_owner_idx     on public.connections (owner);

-- Match the app's existing anon-key access pattern (same as event_state).
alter table public.connections enable row level security;

drop policy if exists "connections read"   on public.connections;
drop policy if exists "connections insert" on public.connections;
drop policy if exists "connections delete" on public.connections;
create policy "connections read"   on public.connections for select using (true);
create policy "connections insert" on public.connections for insert with check (true);
create policy "connections delete" on public.connections for delete using (true);
