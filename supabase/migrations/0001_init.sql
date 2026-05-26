-- ArcticBlue Event Tracker — initial schema
--
-- Apply this in Supabase SQL Editor (Project → SQL Editor → New Query → paste → Run).
-- Idempotent: safe to re-run.
--
-- Tables:
--   allowed_editors  — whitelist of emails permitted to edit ops state
--   event_state      — Angela's ops state per event (keyed by event num from events.json)
--   manual_events    — events added manually (Phase 6 — not yet wired into UI)

-- ─────────────────────────────────────────────────────────────────────
-- 1. Allowed editors (whitelist)
-- ─────────────────────────────────────────────────────────────────────
create table if not exists public.allowed_editors (
  email      text primary key,
  added_by   text,
  created_at timestamptz not null default now()
);

insert into public.allowed_editors (email, added_by) values
  ('angela@arcticblue.ai', 'system'),
  ('hurley@arcticblue.ai', 'system'),
  ('thor@arcticblue.ai',   'system')
on conflict (email) do nothing;

-- ─────────────────────────────────────────────────────────────────────
-- 2. Event state (per-event ops mutations)
-- ─────────────────────────────────────────────────────────────────────
create table if not exists public.event_state (
  event_num         integer primary key,
  status            text,
  speaker           text,
  priority_override text check (priority_override in ('High','Medium','Low') or priority_override is null),
  track             text check (track in ('Sponsor','Earned','Both','Unknown') or track is null),
  saved             boolean not null default false,
  hidden            boolean not null default false,
  urgent            boolean not null default false,
  notes             text,
  updated_by        text,
  updated_at        timestamptz not null default now()
);

create index if not exists event_state_saved_idx  on public.event_state (saved)  where saved  is true;
create index if not exists event_state_urgent_idx on public.event_state (urgent) where urgent is true;
create index if not exists event_state_hidden_idx on public.event_state (hidden) where hidden is true;

-- Touch updated_at on row update
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists event_state_touch on public.event_state;
create trigger event_state_touch
  before update on public.event_state
  for each row execute function public.touch_updated_at();

-- ─────────────────────────────────────────────────────────────────────
-- 3. Manual events (Phase 6 — Angela's "Add Event" form writes here)
-- ─────────────────────────────────────────────────────────────────────
create table if not exists public.manual_events (
  id          bigserial primary key,
  name        text not null,
  date_str    text not null,
  start_date  date,
  end_date    date,
  location    text,
  region      text,
  type        text,
  priority    text,
  why         text,
  url         text,
  created_by  text not null,
  created_at  timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────────────
-- 4. Row-Level Security
-- ─────────────────────────────────────────────────────────────────────
alter table public.allowed_editors enable row level security;
alter table public.event_state     enable row level security;
alter table public.manual_events   enable row level security;

-- allowed_editors: readable by anyone; not writable from client (only via SQL/dashboard)
drop policy if exists ae_read on public.allowed_editors;
create policy ae_read on public.allowed_editors for select using (true);

-- event_state: readable by anyone (public dashboard); writable by allowed editors only
drop policy if exists es_read on public.event_state;
create policy es_read on public.event_state for select using (true);

drop policy if exists es_write_insert on public.event_state;
create policy es_write_insert on public.event_state for insert
  with check (
    auth.email() in (select email from public.allowed_editors)
  );

drop policy if exists es_write_update on public.event_state;
create policy es_write_update on public.event_state for update
  using (
    auth.email() in (select email from public.allowed_editors)
  )
  with check (
    auth.email() in (select email from public.allowed_editors)
  );

drop policy if exists es_write_delete on public.event_state;
create policy es_write_delete on public.event_state for delete
  using (
    auth.email() in (select email from public.allowed_editors)
  );

-- manual_events: same rules
drop policy if exists me_read on public.manual_events;
create policy me_read on public.manual_events for select using (true);

drop policy if exists me_insert on public.manual_events;
create policy me_insert on public.manual_events for insert
  with check (
    auth.email() in (select email from public.allowed_editors)
  );

drop policy if exists me_update on public.manual_events;
create policy me_update on public.manual_events for update
  using (
    auth.email() in (select email from public.allowed_editors)
  )
  with check (
    auth.email() in (select email from public.allowed_editors)
  );

drop policy if exists me_delete on public.manual_events;
create policy me_delete on public.manual_events for delete
  using (
    auth.email() in (select email from public.allowed_editors)
  );

-- ─────────────────────────────────────────────────────────────────────
-- 5. Realtime subscriptions (for multi-tab live updates in the UI)
-- ─────────────────────────────────────────────────────────────────────
alter publication supabase_realtime add table public.event_state;
alter publication supabase_realtime add table public.manual_events;
