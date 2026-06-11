-- ====================================================================
-- Import of Angela's EventsCal app state (events-cal.replit.app)
-- Generated 2026-06-11 by scripts/import_angela_app.py -- DO NOT EDIT BY HAND
--
-- Pure upsert on event_state keyed by event_num. Her statuses map to
-- our 5 pipeline stages; Attending/Should-Attend becomes the
-- attend_verdict; her submission-tracker rows land in notes. Columns
-- she does not carry (postmortem, track, ...) are left untouched.
-- Idempotent -- safe to re-run.
-- ====================================================================

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (16, array['Submitted', 'Declined'], 'No Openings, Submission Inquiry, Sponsorship Only', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (17, array['Declined'], 'Date Conflict, Sponsorship Only', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (18, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (19, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (20, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (21, array['Identified', 'Declined'], 'Date Conflict, Sponsorship Only, Curated Industry Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (22, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (23, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (24, array['Declined'], 'Date Conflict', 'Thor, Jerome', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (26, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (27, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (28, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (29, array['Submitted', 'Declined'], 'Submitted, Sponsorship Only, Should Attend', 'Thor', false, false, 'Worth attending', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (31, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (35, array['Submitted'], 'Submitted', 'Thor, Jerome', false, false, null, 'Status: Submitted · POC: albert@pmmalliance.com · No Openings. Customer case study speaking reserved for Snowflake customers. Vendor/partner speaking is sponsorship-gated only.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (39, array['Declined'], 'No Openings', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (40, array['Declined'], 'Sponsorship Only', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (48, array['Declined'], 'Attending, Sponsorship Only, No External Speakers', 'Verma', false, false, 'Worth attending', 'Status: Attending · No external speakers. Entry points are AWS partner co-presenting joint case studies with AWS team.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (49, array['Submitted'], 'Submitted', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (50, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (53, array['Identified'], 'Curated Industry Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (57, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · POC: hope@gaiinsights.com; gaiworld.com · Submitted (As part of ATxSG and The AI Summit events: London, Singapore, NYC, Cape Town). Co-located with The AI Summit Singapore at ATxEnterprise. 2026 focus: AI governance, execution, and long-term accountability.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (68, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (72, array['Declined'], 'No Openings', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (78, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · Submitted. In talks via personal contact with Julie Sylvester (via intro from Daniel emc3) for MC/Hosting.

*Thor''s Topic: ''Fail or Scale: What''s the Difference Between Experiments and Pilots?'' (Aligned with 2026 theme: Agentic enterprises). 

CFP is open on a rolling basis — submitted ASAP to secure a spot.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (80, array['Submitted'], 'Attending, Finish Submission', 'Verma', false, false, 'Worth attending', 'Status: Attending · POC: Submission Form · *Thor''s Topic: ''Running Thousands of AI Experiments Without Breaking the Rules.'' 

Skipped online form — reached out personally to speaker manager Caitlin Mehta

600 EUR attendance fee.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (82, array['Identified', 'Declined'], 'Sponsorship Only, Curated Industry Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (86, array['Identified', 'Declined'], 'Curated Speaking by Invite, Sponsorship Only', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (87, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · POC: datasciconnect.com/events/align-ai-executive-summit-san-francisco/ · Submitted speaker package and followed up via Thor''s contact. Contact: Ajit Shah (ajit@lotusholdings.com). Maria followed up via email for all MENA events (mdomingo@ypo.org). Sent 60-min executive workshop description.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (97, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (98, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (99, array['Identified', 'Declined'], 'Date Conflict, Sponsorship Only, Curated Industry Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (100, array['Declined'], 'Date Conflict, Sponsorship Only', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (101, array['Submitted', 'Declined'], 'Submitted, Sponsorship Only', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (102, array['Declined'], 'Sponsorship Only', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (103, array['Submitted', 'Meeting held', 'Declined'], 'Submitted, Had Mtg, Not Accepted This Yr', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (104, '{}'::text[], null, null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (106, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (108, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (109, array['Identified', 'Submitted'], 'Submitted, Postponed?', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (110, array['Identified', 'Declined'], 'Sponsorship Only, Curated Industry Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (111, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (112, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (115, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · *Topic C (and D) relevant to event', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (118, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (119, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (120, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (122, array['Submitted'], 'Submitted', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (123, '{}'::text[], null, null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (124, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · POC: datasciconnect.com/events/align-ai-executive-summit-chicago/', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (126, array['Declined'], 'Sponsorship Only, Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (127, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · Submitted. Applied via speaker application form (riseofai.de/speak). No pay-to-play — speakers receive complimentary access; attendees pay €999–€1,299. 10th anniversary edition.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (128, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · Postponed from April 13 to Aug 31. 
*Followed up with a re-submit for new dates

*Topic A / could also do topic E

Speaker nomination personally sent to Fares Sahnoune: leapspeakers@tahaluf.com 
and also via the form', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (129, array['Identified', 'Declined'], 'Sponsorship Only, Curated Speaking by Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (130, array['Identified', 'Declined'], 'Sponsorship Only, Curated Speaking by Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (131, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (132, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (133, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (134, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (135, array['Identified', 'Declined'], 'Sponsorship Only, Curated Industry Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (139, '{}'::text[], null, 'Thor', false, false, null, 'Status: Submitted · Submitted via online request form. They reached out after submission for follow-up conversation.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (141, array['Submitted', 'Declined'], 'Submitted, Sponsorship Only', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (143, array['Submitted', 'Booked'], 'Submitted, Booked Prior Year', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (145, array['Submitted'], 'Submitted, Followed Up', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (146, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (147, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (148, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (153, array['Submitted'], 'Submission Inquiry', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (155, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (156, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (157, '{}'::text[], null, null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (158, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (160, array['Submitted', 'Declined'], 'Submitted, Sponsorship Only', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (161, array['Submitted', 'Declined'], 'Submitted, Sponsorship Only', 'Thor', false, false, null, 'Status: Submitted · Submitted Thor. Applied via GITEX Asia speaker form. Strong APAC enterprise audience at Marina Bay Sands.

It’s curated + partnership influenced.
Thor would like to make a connection with GITEX to do more stuff with them.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (163, array['Submitted', 'Declined'], 'No Openings, Submission Inquiry', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (166, array['Submitted'], 'Submitted', 'Thor', true, false, null, 'Status: Submitted · Submitted Thor. 
They followed up with sponsor invitation to participate as part of Millennium Alliance''s curated assembly series= Sponsorship required for speaking slot.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (167, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (168, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (169, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (170, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (171, '{}'::text[], null, null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (172, array['Declined'], 'Sponsorship Only', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (173, array['Booked'], 'Booked', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (174, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (175, array['Identified', 'Submitted'], 'Curated Speaking by Invite, Submission Inquiry', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (176, array['Meeting held', 'Declined'], 'We''ll Pass, Had Mtg', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (177, array['Submitted'], 'Submitted', 'Patrick', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (178, array['Submitted', 'Declined'], 'Submitted, Not Accepted This Yr', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (179, array['Identified'], 'Contact/Get Invited to speak', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (180, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (181, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (182, array['Meeting held', 'Declined'], 'We''ll Pass, Had Mtg', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (183, array['Submitted'], 'Submitted', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (184, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (185, array['Submitted'], 'Submitted, Followed Up', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (186, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (187, array['Identified'], 'Postponed?', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (188, array['Submitted'], 'Submitted', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (189, array['Identified', 'Submitted', 'Declined'], 'Submitted, Sponsorship Only, Curated Speaking by Invite', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (190, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (191, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (192, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (193, array['Submitted', 'Meeting held'], 'In Progress, Had Mtg', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (194, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (195, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (196, array['Submitted', 'Meeting held', 'Booked'], 'Submitted, In contact with, Booked Prior Event', 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (198, '{}'::text[], null, 'Thor', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (199, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · POC: Connor — connor@pef.xyz · Submitted speaker package. Organizer confirmed they will contact us if chosen.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (200, '{}'::text[], null, 'Thor', false, false, null, 'Status: Submitted · POC: Online form · Submitted via online form. Registered for Speaker Updates.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (201, array['Submitted', 'Declined'], 'Submitted, No Openings', 'Thor', false, false, null, 'Status: Submitted · POC: Prof Nader Al Bastaki  + Prof Saad Darwish', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (202, array['Booked'], 'Booked', 'Thor', false, false, null, 'Status: Submitted · POC: Ciara Haley + Darragh McCauley  · ciara.haley@websummit.com, darragh.mccauley@websummit.com · Booked for Feb 2.
In contact with Ciara Haley (ciara.haley@websummit.com) who runs Exec Programming for Web Summit. 
Thor spoke at the February 2026 Doha edition.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (203, array['Declined'], 'Attending, No External Speakers', 'Thor', false, false, 'Worth attending', 'Status: Attending · POC: Online Submission -  · https://www.worldgovernmentssummit.org/contact-us?utm_source=chatgpt.com · "Our team will review your inquiry and get back to you shortly."

Submitted. *Thor''s Topic: ''Running Thousands of AI Experiments Without Breaking the Rules'' (Aligned with 2026 theme: Global Government and Effective Leadership). 
Applied via official speaker submission.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (204, array['Booked'], 'Booked', 'Thor', false, false, null, 'Status: Booked · POC: The Information Technology Industry Council (ITI) · Submitted. No Openings — they find/invite speakers themselves. ITI conducts direct outreach for speaker invites; no open application process.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (205, array['Declined'], 'Attending, Sponsorship Only, No External Speakers', null, false, false, 'Worth attending', 'Status: Attending · Attending, not speaking.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (206, array['Booked'], 'Booked', null, false, false, null, 'Status: In Progress · POC: Juan Fernandez (EY Venezuela Partner) · juan.fernandez@ve.ey.com · Juan reached out to Thor via email. Booking in progress.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (207, array['Identified'], 'Attending, Thor Contacting', null, false, false, 'Worth attending', 'Status: Attending · POC: Olga Yaroshevsky - Managing Director SiGMA/AIBC + George Korotkov - Conference Producer SiGMA/AIBC · olga.y@SiGMA.World, George.K@sigma.world · Received intro meeting with AIBC. Decided to pass. 
Interested in AIBC Rome (Italy) in Fall instead.   

AIBC 2025 was focused on regulation and compliance (for all the new business coming to the UAE for tech, new neighborhoods being built for tech, gaming, crypto, ai) and also on marketing.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (208, array['Identified', 'Declined'], 'No Openings, Thor Contacting', null, false, false, null, 'Status: In Progress · POC: Personal Contact · *Submitted Patrick. 
His topic: ''Synthetic Personas Are Inevitable: Here''s How They''ll Shape Decision-Making.'' 
Speaker badge includes all-access complimentary access.

*Submitted Patrick. His topic: ''Synthetic Personas Are Inevitable: Here''s How They''ll Shape Decision-Making.'' Speaker badge includes all-access complimentary access.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (209, array['Booked'], 'Booked', 'Joe', false, false, null, 'Status: Booked · Submitted. We were not accepted this year. 
*Thor''s Topic: ''Building a Learning Organization: Results From 20k+ Experiments.'' Speakers responsible for own travel and accommodation. 

Target for 2027.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (210, '{}'::text[], null, null, false, false, null, 'Status: Attending · Attending (not speaking).', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (211, array['Identified'], 'Attending, Thor Contacting', 'Thor', false, false, 'Worth attending', 'Status: Attending · *Thor looking into connections. 
Main Summit is usually held in March in NYC. 
Must be a member or have an invite or strong connection to the ON_Discourse community to be considered. Keep checking dates.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (212, array['Declined'], 'Attending, Sponsorship Only', 'Thor', false, false, 'Worth attending', 'Status: Attending · Speaking is sponsorship only / FII Institute must invite.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (213, array['Booked'], 'Booked', 'Joe', false, false, null, 'Status: Booked · Self submitted.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (214, array['Meeting held', 'Booked'], 'Booked, In contact with', 'Thor', false, false, null, 'Status: Submitted · POC: gw.edu · Submitted Thor. Open speaker application via humanx.co/speak — merit-based selection, accepted on rolling basis. 

Deadline Jan 1 (recommended). 

Also applied for Amsterdam edition (September).', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (215, array['Submitted'], 'Finish Submission, Attending?', null, false, false, 'Maybe', 'Status: Attending · Sent Verma speaking info — would need his proposal to submit.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (216, array['Submitted', 'Meeting held'], 'In Progress, In contact with', null, false, false, null, 'Status: In Progress · POC: Jay Weintraub (Connectiv Holdings) · jay@connectiv.com · Jay reached out re: AI in life and annuity space. Exploring for Verma speaker slot.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (217, array['Declined'], 'No Openings', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (218, array['Identified'], 'Attending, Contact/Get Invited to speak', 'Thor', false, false, 'Worth attending', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (219, array['Submitted', 'Meeting held', 'Declined'], 'Had Mtg, Submitted, Sponsorship Only, Attending', 'Thor', true, false, 'Worth attending', 'Status: Attending · Originally Apr 7–8. Postponed to October.
*Re-submitted for new dates.
Applied via online speaker form. They will only reach out if chosen.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (220, array['Identified'], 'Attending, Contact/Get Invited to speak', 'Thor', false, false, 'Worth attending', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (221, array['Declined'], 'Should Attend, Sponsorship Only', null, false, false, 'Worth attending', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (222, array['Identified'], 'Attending?, Curated Speaking by Invite', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (225, array['Identified', 'Declined'], 'No External Speakers, Curated Speaking by Invite, Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (226, '{}'::text[], 'Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (227, array['Identified'], 'Curated Speaking by Invite, Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (228, array['Booked'], 'Booked', 'Thor, Verma, Joe, Jerome', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (229, array['Booked'], 'Booked', 'Thor', false, false, null, 'Status: Submitted · Submitted. Applied via speaking inquiry on ai-expo.net/northamerica/
Co-located with 6 other enterprise tech expos as TechEx NA.

Submitted. Applied via speaking inquiry on ai-expo.net/northamerica/. Co-located with 6 other enterprise tech expos as TechEx NA.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (230, '{}'::text[], 'Attending?', 'Jerome', false, false, 'Maybe', 'Status: Submitted · POC: Gabriella Disandolo, Speaking Opportunities · Submitted late, due to ongoing conflict concerns. Will likely be postponed to a new date.
Heavily Sponsored or Invite only, but does offer a free speaker route.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (232, array['Identified', 'Declined'], 'Sponsorship Only, Curated Speaking by Invite, Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (233, '{}'::text[], 'Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (234, '{}'::text[], 'Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (235, array['Identified', 'Meeting held'], 'In contact with, Curated Speaking by Invite', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (236, '{}'::text[], null, 'Thor, Jerome', false, true, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (237, array['Declined'], 'Attending?, Sponsorship Only', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (238, array['Identified', 'Declined'], 'Sponsorship Only, Curated Speaking by Invite, Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (239, array['Identified'], 'Curated Speaking by Invite, Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (240, array['Identified'], 'Curated Speaking by Invite', 'Joe', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (241, '{}'::text[], 'Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (243, array['Submitted'], 'Submitted', 'Joe', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (244, array['Submitted'], 'Submitted', 'Joe', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (245, array['Submitted'], 'Attending, Finish Submission', 'Verma', false, false, 'Worth attending', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (246, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · Apply to speak: https://datasciconnect.com/events/speaker-interest-form/
One submission covers multiple events:
ALIGN AI Executive Summit - ATL (5.20.2026)
ALIGN AI Executive Summit - NYC (6.25.2026)
ALIGN AI Executive Summit - CHI (7.15.2026)
ALIGN AI Executive Summit - SF (8.19.2026)
The AI Enterprise Conference - NYC (9.2.2026)
COLLIDE Data+AI Conference - ATL (10.1.2026)
ALIGN AI Executive Summit - DAL (10.21.2026)
AI for Enterprise Webinar Series

all event descriptions combined here: 
https://datasciconnect.com/events/', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (247, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · Submitted. Originally April 29; postponed to November 4. 
Registered for speaker updates.
Sponsorship only / invite only.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (248, array['Submitted'], 'Submitted', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (250, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · Submitted. 
Speaking by nomination (invite-only format)/ Sponsorship only. 
Also, followed up personally through Thor''s contact.', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (251, array['Submitted'], 'Submitted', 'Thor', false, false, null, 'Status: Submitted · 
Apply to speak: https://datasciconnect.com/events/speaker-interest-form/
One submission covers multiple events:
ALIGN AI Executive Summit - ATL (5.20.2026)
ALIGN AI Executive Summit - NYC (6.25.2026)
ALIGN AI Executive Summit - CHI (7.15.2026)
ALIGN AI Executive Summit - SF (8.19.2026)
The AI Enterprise Conference - NYC (9.2.2026)
COLLIDE Data+AI Conference - ATL (10.1.2026)
ALIGN AI Executive Summit - DAL (10.21.2026)
AI for Enterprise Webinar Series

all event descriptions combined here: 
https://datasciconnect.com/events/', 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (253, array['Submitted'], 'Submitted', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (254, '{}'::text[], 'Attending?', 'Jerome', false, false, 'Maybe', null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (256, array['Declined'], 'Date Conflict', null, false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (258, array['Identified'], 'Contact/Get Invited to speak', 'Joe', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (273, array['Submitted'], 'Submitted', 'Joe', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

insert into public.event_state (event_num, status_tags, status, speaker, saved, hidden, attend_verdict, notes, updated_by)
values (274, array['Submitted'], 'Submitted', 'Joe', false, false, null, null, 'angela-app-import')
on conflict (event_num) do update set
  status_tags = excluded.status_tags,
  status = excluded.status,
  speaker = coalesce(excluded.speaker, event_state.speaker),
  saved = excluded.saved,
  hidden = excluded.hidden,
  attend_verdict = coalesce(excluded.attend_verdict, event_state.attend_verdict),
  notes = coalesce(excluded.notes, event_state.notes),
  updated_by = excluded.updated_by;

-- Sanity: how many rows now carry stages? (expect >= 161)
select count(*) from public.event_state where cardinality(status_tags) > 0;
