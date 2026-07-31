-- ====================================================================
-- ArcticBlue Event Tracker — Angela's outreach email templates
--
-- WHY: Angela writes to the organiser immediately after marking an event
-- Submitted, and her friction was never the writing — it was re-checking
-- the event name and the dates against a template kept in a Google Doc,
-- every single time. "Draft outreach" now builds that email on the event
-- itself, pre-filled from the row she is already looking at.
--
-- The wording has to be hers, and it has to be editable without a deploy,
-- so the two variants live in the database rather than in the build:
--
--   email_template_global  text   used outside the US. Leads with the
--                                 Middle East programme.
--   email_template_us      text   used inside the US. Same body, with the
--                                 Middle East angle moved below the
--                                 signature as context, not the headline.
--
-- Both hang off the team_profiles row for person = 'angela'. They are a
-- team asset rather than a personal one, but she is the one who writes
-- them, and reusing team_profiles avoids a table for two strings.
--
-- Placeholders are [square brackets] and fill themselves in from the
-- event: [contact_first] [contact_name] [event_name] [event_dates]
-- [event_location] [speaker_name] [speaker_topic] [bio_link]. An unknown
-- placeholder is left visible rather than blanked, so a typo shows up
-- instead of silently deleting a line.
--
-- Deliberately NOT seeded here: the build ships sensible defaults and uses
-- them whenever a column is null or blank, so the composer works before
-- this runs and before anyone edits anything. Seeding SQL copies of the
-- defaults would just create two places to change the wording.
--
-- Until this runs: Draft outreach works on the built-in defaults. Saving
-- from Team Profiles reports "run the email-templates migration first"
-- and changes nothing.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor
-- for project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.team_profiles add column if not exists email_template_global text;
alter table public.team_profiles add column if not exists email_template_us     text;

-- Sanity: both columns present.
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'team_profiles'
  and column_name in ('email_template_global', 'email_template_us')
order by column_name;
