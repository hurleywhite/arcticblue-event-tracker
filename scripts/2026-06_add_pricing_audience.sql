-- ====================================================================
-- ArcticBlue Event Tracker -- Buyer-quality + attending fields
--                            + one-time data cleanup
--
-- WHY (read before running):
--   ArcticBlue wants stage time in front of BUYERS (in-house enterprise
--   leaders / decision-makers who could become clients) -- NOT rooms full of
--   other AI vendors and sales reps selling to each other. Verma's "shopping
--   list" for ATTENDING events adds more signals. New columns:
--
--   manual_events:
--     pricing          text -- cost to ATTEND ('$2,495 delegate pass'). High
--                             price + senior titles = buyer-rich signal. If an
--                             event prices buyers vs vendors differently, both
--                             tiers go here.
--     audience_type    text -- who is in the room: 'Buyer-rich' | 'Mixed' |
--                             'Vendor-heavy'.
--     past_speakers    text -- past/announced speakers as 'Title, Company'
--                             (e.g. 'CIO, UnitedHealth; CDO, Pfizer').
--     meeting_formats  text -- built-in ways to MEET people: guaranteed 1:1
--                             meetings, roundtables, attendee meeting app.
--     attend_verdict   text -- 'Worth attending' | 'Maybe' | 'Not worth it'.
--     postmortem       text -- Thor's post-event ROI notes (contacts, client
--                             meetings, sales vs ticket + travel cost).
--
--   event_state (the per-catalog-event ops row) gets the two ops-editable
--   verdict fields as well:
--     attend_verdict   text
--     postmortem       text
--
-- SAFE TO DEPLOY BEFORE RUNNING THIS: server ingest (_insert_one) and the
--   client write helper (sbWriteRetry) both detect a missing new column,
--   strip it, and retry -- saves still land; the new fields just stay blank
--   (with an on-screen warning) until this migration runs.
--
-- Idempotent: every ADD uses IF NOT EXISTS; the cleanup UPDATEs/DELETE match
--   on id AND name so re-running (or running against already-clean data)
--   changes nothing. Safe to re-run.
--
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq
-- ("AB Event Tracker [Hurley's Org]").
-- ====================================================================

-- -- 1 . manual_events: buyer-quality + attending columns (all nullable) --
alter table public.manual_events add column if not exists pricing         text;
alter table public.manual_events add column if not exists audience_type   text;
alter table public.manual_events add column if not exists past_speakers   text;
alter table public.manual_events add column if not exists meeting_formats text;
alter table public.manual_events add column if not exists attend_verdict  text;
alter table public.manual_events add column if not exists postmortem      text;

-- -- 2 . event_state: the ops-editable verdict fields for catalog events ---
alter table public.event_state add column if not exists attend_verdict text;
alter table public.event_state add column if not exists postmortem     text;

-- -- 3 . One-time data cleanup ------------------------------------------
-- 3a. Four manual events got a speaking_route link that belongs to a
--     DIFFERENT event (cross-event CFP links found during QA). Clear them so
--     nobody applies at the wrong conference. Guarded by id AND name.
update public.manual_events set speaking_route = null
where (id = 12 and name ilike '%ISG AI Impact%')
   or (id = 14 and name ilike '%Agentic Transformation%')
   or (id = 17 and name ilike '%Microsoft Ignite%')
   or (id = 18 and name ilike '%Enterprise AI Expo%');

-- 3b. Duplicate manual row: "The AI Leadership Summit — The Conference Board"
--     duplicates the catalog's "The Conference Board AI Leadership Summit
--     2026". Delete the manual copy (the catalog copy stays).
delete from public.manual_events
where name ilike '%AI Leadership Summit%Conference Board%'
  and name ilike 'The AI Leadership Summit%';

-- -- 4 . Sanity reports ---------------------------------------------------
-- (a) New manual_events columns exist (expect 6 rows).
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name   = 'manual_events'
  and column_name in ('pricing','audience_type','past_speakers',
                      'meeting_formats','attend_verdict','postmortem')
order by column_name;

-- (b) New event_state columns exist (expect 2 rows).
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name   = 'event_state'
  and column_name in ('attend_verdict','postmortem')
order by column_name;

-- (c) The 4 cleaned rows now have no speaking_route (expect 0 rows).
select id, name, speaking_route
from public.manual_events
where id in (12, 14, 17, 18) and speaking_route is not null;
