-- ====================================================================
-- ArcticBlue Event Tracker — extra event_state override columns so the
-- per-event "Enrich" button can fill rich facts on CATALOG events too.
--
-- Catalog events read base data from the static events.json; per-event edits
-- and enrichment results live as OVERRIDES on event_state. The earlier
-- override migration added why/about/focus_areas/typical_attendees/
-- speaking_route/pay_to_play/venue/contact_info/deadline. Enrichment also
-- returns url / pricing / audience_type / past_speakers / meeting_formats /
-- attendee_count, so add those columns too (manual_events already has them).
--
-- Idempotent. Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state
  add column if not exists url               text,
  add column if not exists pricing           text,
  add column if not exists audience_type     text,
  add column if not exists past_speakers     text,
  add column if not exists meeting_formats   text,
  add column if not exists attendee_count    text;

-- Sanity: confirm the new columns exist.
select column_name
from information_schema.columns
where table_schema = 'public' and table_name = 'event_state'
  and column_name in ('url','pricing','audience_type','past_speakers',
                      'meeting_formats','attendee_count')
order by column_name;
