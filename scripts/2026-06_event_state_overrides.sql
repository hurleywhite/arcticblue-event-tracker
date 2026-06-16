-- ====================================================================
-- ArcticBlue Event Tracker — editable descriptive fields on CATALOG events
--
-- WHY: the pop-up "Edit event" panel now lets you edit the descriptive
-- fields (Why it fits, About, Focus areas, Typical attendees, Speaking
-- route, Pay-to-play, Venue, Contact info, Deadline) on ANY event —
-- including catalog events, not just manual ones.
--
-- Catalog events read their base data from the static events.json, but
-- edits need somewhere to live. These columns store per-event OVERRIDES on
-- event_state: when set, the app shows the override; when blank/null, it
-- falls back to the catalog value. (manual_events already has every column,
-- so this only touches event_state.)
--
-- Until you run this, editing those fields on a catalog event will fail
-- with "Save failed: column ... does not exist". Editing them on a manual
-- event already works.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS). Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state
  add column if not exists why               text,
  add column if not exists about             text,
  add column if not exists focus_areas       text,
  add column if not exists typical_attendees text,
  add column if not exists speaking_route    text,
  add column if not exists pay_to_play        text,
  add column if not exists venue             text,
  add column if not exists contact_info      text,
  add column if not exists deadline          text;

-- Sanity: confirm the new columns exist.
select column_name
from information_schema.columns
where table_schema = 'public' and table_name = 'event_state'
  and column_name in ('why','about','focus_areas','typical_attendees',
                      'speaking_route','pay_to_play','venue','contact_info','deadline')
order by column_name;
