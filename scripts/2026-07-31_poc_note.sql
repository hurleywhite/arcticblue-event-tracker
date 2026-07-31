-- ====================================================================
-- ArcticBlue Event Tracker — who this contact actually is
--
-- WHY: a name and an email don't tell Angela what to send. "Leona Fletcher"
-- could be the programme director who decides the agenda, or the person who
-- books exhibition stands — and the email you write is completely different.
--
--   poc_note  text   a few words on who they are and why they're the contact,
--                    e.g. "Programme director — owns the speaker agenda"
--                         "Sponsorship lead — booked our stand in 2025"
--                         "Posted the CFP on LinkedIn, replies there"
--
-- Deliberately NOT added:
--
--   a confidence score. Hurley: no score next to the contact. A number invites
--   the question "is 0.7 good enough to email?" and nobody can answer it. The
--   words say who the person is, and Angela decides — which is the judgement
--   she was making anyway.
--
--   a separate contacts table. One point of contact per event is what the team
--   works with today (additional_contacts already holds the overflow as text),
--   and a join table would be a bigger change than the problem needs.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq. Until it runs, contacts display exactly as they
-- do today; writing a note reports the app's standard migration-pending warning
-- and nothing else changes.
-- ====================================================================

alter table public.event_state   add column if not exists poc_note text;
-- The structured pair manual_events has always had. Without these on
-- event_state, a contact found for a CATALOG event could only be written to
-- the free-text contact_info blob — which the outreach composer cannot read,
-- so those drafts opened "Hello there," even when we knew the name.
alter table public.event_state   add column if not exists poc_name text;
alter table public.event_state   add column if not exists poc_email text;
alter table public.event_state   add column if not exists poc_linkedin text;
-- When we last went looking, so a failed lookup is not retried forever and a
-- successful one is not repeated. Null = never tried.
alter table public.event_state   add column if not exists poc_lookup_at timestamptz;
alter table public.manual_events add column if not exists poc_lookup_at timestamptz;
alter table public.manual_events add column if not exists poc_note text;

-- Sanity: confirm the column exists on both tables.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'poc_note'
order by table_name;
