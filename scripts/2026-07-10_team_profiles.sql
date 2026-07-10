-- ====================================================================
-- ArcticBlue Event Tracker — "My Profile" (bios, topics, past talks,
-- targeting notes) + file storage.
--
-- Adds a per-person profile the whole team can see: each person edits
-- their own (bio, speaking topics, past talks, and the events they want
-- to target), and uploads files (bios, decks, one-pagers). Everyone
-- else's TEXT shows read-only in the tab so we can see where each person
-- has spoken and where to target next.
--
-- TWO things get created:
--   1. public.team_profiles   — the text fields (one row per person)
--   2. a private 'profiles' Storage bucket — the uploaded files
--
-- NO sign-in required — same trust model as the rest of the tracker
-- (star, chat, edit fields): you just type who you are. Read / insert /
-- update / delete are all open. Files live in a PRIVATE bucket and are
-- served through short-lived signed URLs (not public links), so they
-- aren't world-readable even though posting is open.
--
-- Idempotent — safe to run more than once. Run the WHOLE script in the
-- Supabase SQL editor for project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

-- ── 1. Text fields ──────────────────────────────────────────────────
create table if not exists public.team_profiles (
  person       text primary key,          -- lowercase first name (the key)
  display_name text,                       -- the name they typed, for display
  bio          text,
  topics       text,
  past_talks   text,
  notes        text,
  updated_by   text,
  updated_at   timestamptz not null default now()
);

alter table public.team_profiles enable row level security;

-- Anyone can READ every profile (the read-only team roster needs this).
drop policy if exists team_profiles_read on public.team_profiles;
create policy team_profiles_read on public.team_profiles for select using (true);

-- Anyone can create their profile row. Light sanity caps guard against
-- garbage since the endpoint is open to anyone with the public site key.
drop policy if exists team_profiles_insert on public.team_profiles;
create policy team_profiles_insert on public.team_profiles for insert
  with check (
    length(trim(person)) > 0 and length(person) <= 100 and
    length(coalesce(bio, ''))        <= 10000 and
    length(coalesce(topics, ''))     <= 10000 and
    length(coalesce(past_talks, '')) <= 10000 and
    length(coalesce(notes, ''))      <= 10000
  );

-- Anyone can update a profile (the app only ever edits your own, matched
-- by your typed name — enforced in the UI, not by real login).
drop policy if exists team_profiles_update on public.team_profiles;
create policy team_profiles_update on public.team_profiles for update
  using (true)
  with check (
    length(trim(person)) > 0 and length(person) <= 100 and
    length(coalesce(bio, ''))        <= 10000 and
    length(coalesce(topics, ''))     <= 10000 and
    length(coalesce(past_talks, '')) <= 10000 and
    length(coalesce(notes, ''))      <= 10000
  );

-- ── 2. File storage bucket ──────────────────────────────────────────
-- Private bucket (public = false); the app downloads via signed URLs.
-- 25 MB per-file cap matches the client-side check.
insert into storage.buckets (id, name, public, file_size_limit)
values ('profiles', 'profiles', false, 26214400)
on conflict (id) do update set file_size_limit = excluded.file_size_limit,
                               public = excluded.public;

-- Open read / insert / update / delete, scoped to this bucket only.
-- (storage.objects already has RLS enabled by Supabase.)
drop policy if exists profiles_read   on storage.objects;
drop policy if exists profiles_insert on storage.objects;
drop policy if exists profiles_update on storage.objects;
drop policy if exists profiles_delete on storage.objects;

create policy profiles_read   on storage.objects for select using (bucket_id = 'profiles');
create policy profiles_insert on storage.objects for insert with check (bucket_id = 'profiles');
create policy profiles_update on storage.objects for update using (bucket_id = 'profiles') with check (bucket_id = 'profiles');
create policy profiles_delete on storage.objects for delete using (bucket_id = 'profiles');

-- ── Sanity: confirm the table, its policies, and the bucket ─────────
select table_name from information_schema.tables
where table_schema = 'public' and table_name = 'team_profiles';
select policyname, cmd from pg_policies where tablename = 'team_profiles';
select id, public, file_size_limit from storage.buckets where id = 'profiles';
select policyname, cmd from pg_policies where tablename = 'objects' and policyname like 'profiles_%';
