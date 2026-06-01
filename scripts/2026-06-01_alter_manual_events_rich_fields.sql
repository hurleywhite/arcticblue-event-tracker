-- ════════════════════════════════════════════════════════════════════
-- ArcticBlue Event Tracker — Add ArcticScout rich fields to manual_events
--
-- WHY (read before running):
--   The ArcticScout export (184 rows) was merged ADDITIVELY into the
--   public catalog data/events.json -> public/events.json (now 243 events).
--   The For-Angela tab already reads that file and renders every ArcticScout
--   event as an ops card, and the new expanded detail modal shows all of the
--   rich fields. So the ArcticScout events themselves do NOT belong in
--   manual_events — that table is only for events Angela adds by hand that
--   are NOT already in the public catalog. Re-inserting the catalog rows here
--   would duplicate them (and the unique index on lower(name) added by
--   2026-05-26_dedup_manual_events.sql would reject most of them anyway).
--
--   Therefore this migration is ALTER-ONLY. It widens manual_events with the
--   same rich columns the modal can display, so that a HAND-ADDED or EDITED
--   manual event can carry the same metadata (About, Focus Areas, Deadline,
--   Pay-to-Play, Venue, etc.) and light up the same modal fields.
--
-- Idempotent: every statement uses IF NOT EXISTS. Safe to re-run.
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq
-- ("AB Event Tracker [Hurley's Org]").
-- ════════════════════════════════════════════════════════════════════

-- ── New text / metadata columns the modal reads ─────────────────────
alter table public.manual_events add column if not exists about              text;
alter table public.manual_events add column if not exists focus_areas        text;
alter table public.manual_events add column if not exists typical_attendees  text;
alter table public.manual_events add column if not exists speaking_route      text;
alter table public.manual_events add column if not exists contact_info        text;
alter table public.manual_events add column if not exists deadline            text;
alter table public.manual_events add column if not exists attendee_count      text;
alter table public.manual_events add column if not exists pay_to_play         text;
alter table public.manual_events add column if not exists venue               text;
alter table public.manual_events add column if not exists city                text;
alter table public.manual_events add column if not exists country             text;
alter table public.manual_events add column if not exists external_id         text;

-- ── Boolean flags (Seed? / Urgent?) — nullable, default null ────────
alter table public.manual_events add column if not exists seed   boolean;
alter table public.manual_events add column if not exists urgent boolean;

-- ── Sanity report: confirm the columns now exist ───────────────────
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name   = 'manual_events'
  and column_name in (
    'about','focus_areas','typical_attendees','speaking_route','contact_info',
    'deadline','attendee_count','pay_to_play','venue','city','country',
    'external_id','seed','urgent'
  )
order by column_name;

-- Expected: 14 rows. If you see all 14, the migration succeeded.
