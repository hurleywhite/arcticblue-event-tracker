-- ====================================================================
-- ArcticBlue Event Tracker — backlog of DELETED events ("don't bring this back")
--
-- WHY: deleting a manual event hard-deleted the row, so the nightly Dust ingest
-- had no memory of it. The scraper would happily re-add the same event a few
-- days later, and someone would delete it again. (Catalog events were already
-- safe — they're suppressed with a '__deleted__' sentinel on their event_state
-- row and stay in events.json, so the ingest's dedupe still sees the name.)
--
-- This table is that memory. Every delete — manual or catalog — records the
-- event here first, and /api/events checks incoming events against it, skipping
-- anything that was previously deleted with reason "previously deleted". The
-- match uses the same three tests as the live dedupe: exact name, the
-- order-independent fingerprint, and title-shape within a few days in the SAME
-- year (so next year's edition of an annual event is never blocked).
--
-- To un-block an event someone deleted by mistake, delete its row here:
--   delete from public.deleted_events where name ilike '%event name%';
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq. Until this runs, deletes still work exactly as
-- before; the backlog just stays empty (the app records best-effort and never
-- blocks a delete on it, and the ingest treats a missing table as "no backlog").
-- ====================================================================

create table if not exists public.deleted_events (
  id           bigserial primary key,
  name         text not null,
  start_date   date,          -- so a re-add a couple of days off still matches
  location     text,
  source_table text,          -- 'manual_events' | 'event_state'
  source_key   text,          -- the manual_events.id / event_state.event_num it had
  deleted_by   text,          -- the typed collaborator name, when we have one
  reason       text,
  created_at   timestamptz not null default now()
);

create index if not exists deleted_events_name_idx  on public.deleted_events (lower(name));
create index if not exists deleted_events_start_idx on public.deleted_events (start_date);

alter table public.deleted_events enable row level security;

-- Read is open — same as the rest of the app, and the ingest reads it with the
-- service role anyway.
drop policy if exists deleted_events_read on public.deleted_events;
create policy deleted_events_read on public.deleted_events for select using (true);

-- Anyone who can delete an event can record it here (no sign-in in this app —
-- you just type who you are). Light sanity check on the name.
drop policy if exists deleted_events_insert on public.deleted_events;
create policy deleted_events_insert on public.deleted_events for insert
  with check (
    length(trim(name)) > 0 and length(name) <= 300
  );

-- Open delete, so un-blocking a mistakenly-deleted event doesn't need SQL access.
drop policy if exists deleted_events_delete on public.deleted_events;
create policy deleted_events_delete on public.deleted_events for delete using (true);

-- ── Seed: the 11 events deleted before this table existed ───────────────────
-- Recovered from the events that vanished from public/calendar.ics between the
-- 2026-07-29 commit and the rebuild — i.e. deletions that left no trace and the
-- nightly scrape could therefore re-add. Dated, so each one blocks re-adds in
-- 2026 only; the 2027 edition of any of them is still welcome.
insert into public.deleted_events (name, start_date, source_table, deleted_by, reason)
select v.name, v.start_date, 'manual_events', 'backfill', 'deleted before the backlog existed'
from (values
  ('IDC AI & Data Summit London 2026',                            date '2026-09-10'),
  ('SHRM BLUEPRINT for Inclusion & Diversity 2026',               date '2026-11-15'),
  ('Learning Futures San Francisco, Executive Knowledge Exchange', date '2026-08-18'),
  ('SHRM New York State Annual Conference 2026',                  date '2026-09-28'),
  ('L&D Practitioner Summit 2026',                                date '2026-09-02'),
  ('HumanX Europe 2026',                                          date '2026-09-22'),
  ('Transformational CHRO Assembly – November 2026',              date '2026-11-17'),
  ('IDC CIO Summit UK 2026',                                      date '2026-09-10'),
  ('SHRM Linkage Leadership Institute 2026',                      date '2026-11-16'),
  ('Data & AI Strategy Practitioner Summit 2026',                 date '2026-09-02'),
  ('TEDAI',                                                       date '2026-10-28')
) as v(name, start_date)
-- Re-runnable: skip anything already on the backlog.
where not exists (
  select 1 from public.deleted_events d
  where lower(d.name) = lower(v.name)
    and coalesce(d.start_date, date '0001-01-01') = coalesce(v.start_date, date '0001-01-01')
);

-- Sanity: confirm the table + its three policies (select / insert / delete).
select tablename, policyname, cmd
from pg_policies
where schemaname = 'public' and tablename = 'deleted_events'
order by policyname;

-- And what's on the backlog now.
select name, start_date, reason from public.deleted_events order by name;
