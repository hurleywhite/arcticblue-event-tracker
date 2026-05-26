-- ════════════════════════════════════════════════════════════════════
-- ArcticBlue Event Tracker — Ingest Angela's events_calendar_upload.xlsx
--
-- Run this whole file in Supabase SQL Editor.
-- Two phases:
--   1. ALTER manual_events to add Angela's ops columns
--   2. INSERT … WHERE NOT EXISTS by name — safe to re-run
-- ════════════════════════════════════════════════════════════════════

alter table public.manual_events
  add column if not exists status              text,
  add column if not exists submission_status   text,
  add column if not exists speaker             text,
  add column if not exists notes               text,
  add column if not exists poc_name            text,
  add column if not exists poc_email           text,
  add column if not exists poc_linkedin        text,
  add column if not exists additional_contacts text,
  add column if not exists speaking_fee        text,
  add column if not exists paid                boolean;


INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'ICBDT The International Conference on Business and Digital Technology',
  '11/26 - 11/27/25',
  '2025-11-26',
  '2025-11-27',
  'Bahrain',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry, Late Inquiry',
  'Thor',
  'Reached out personally.  Inquiry on speaker openings/cancellations and for interest in how to apply for next session/ any future events; (Both were cc''d on email)',
  'Organizing Committee Heads:                           Prof Nader Al Bastaki, Kingdom University, Bahrain (Chair)',
  'Nalbastaki@ku.edu.bh',
  NULL,
  'Prof Saad Darwish, Kingdom University (Deputy Chair) <Saad.darwish@ku.edu.bh>',
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('ICBDT The International Conference on Business and Digital Technology')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Web Summit',
  '2/1 - 2/4',
  '2026-02-01',
  '2026-02-04',
  'Doha, Qatar',
  'MENA',
  'Speaking',
  'High',
  'Booked',
  'Personal Contact/Inquiry, Booked',
  'Thor',
  'Booked for 2/2.',
  'Ciara Haley',
  'ciara.haley@websummit.com, darragh.mccauley@websummit.com',
  NULL,
  NULL,
  '"It''s ok if we cover all expenses in order to go"',
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Web Summit')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  '(ITI) The Intersect: Tech + Policy Summit',
  '2026-02-03 00:00:00',
  '2026-02-03',
  '2026-02-03',
  'Washington, DC',
  'Americas',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, """Don''t call us, we call you"""',
  'Thor',
  'No open call - reached out for speaker inquiry--- Response: "We are conducting direct outreach for speaker invites. We have your information and will reach out if we are interested."',
  'The Information Technology Industry Council (ITI)',
  'events@itic.org',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('(ITI) The Intersect: Tech + Policy Summit')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'World Governments Summit (WGS)',
  '2/3 - 2/5',
  '2026-02-03',
  '2026-02-05',
  'Dubai',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  '"Our team will review your inquiry and get back to you shortly. We appreciate your interest and look forward to connecting with you soon!"',
  NULL,
  'Online Submission',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('World Governments Summit (WGS)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Aspen Institute "Socrates Winter"',
  '2/6 - 2/9',
  '2026-02-06',
  '2026-02-09',
  'Aspen, CO',
  'Americas',
  'Speaking',
  'Medium',
  'Attending (Not Speaking)',
  'Not accepting External Company Speakers',
  NULL,
  'Attending and Participating: No Speakers',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Aspen Institute "Socrates Winter"')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'AIBC Eurasia',
  '2/10 - 2/12',
  '2026-02-10',
  '2026-02-12',
  'Dubai, UAE',
  'MENA',
  'Speaking',
  'Medium',
  'Received Intro Meeting',
  'Received Intro Meeting, Personal Contact/Inquiry',
  'Thor',
  'The general form submission did not work, so I was able to get her email address and submitted an inquiry and speaker package.  ----2025 AIBC focused on regulation and compliance (for all the new business coming to the UAE for tech, new neighborhoods being built for tech, gaming, crypto, ai) and also on marketing.',
  'Olga Yaroshevsky - Managing Director AIBC',
  'olga.y@SiGMA.World',
  'LinkedIn',
  'George Korotkov - Conference Producer @SiGMA AIBC <George.K@sigma.world> [LI: LinkedIn]',
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('AIBC Eurasia')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Generative AI Expo',
  '2/10 - 2/12',
  '2026-02-10',
  '2026-02-12',
  'Fort Lauderdale, Florida',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Patrick',
  'Your SPEAKER badge is an All Access Pass to the entire Generative AI Expo/ITEXPO #TECHSUPERSHOW conference. You save as much as $1,599. Complimentary access to all breakout sessions. All meals, networking receptions and breaks included complimentary. Free admission to all conference parties',
  'Generative AI Expo Editorial Team',
  'Online Form    events@tmcnet.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Generative AI Expo')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'World AI Cannes Festival (WAICF)',
  '2/12 - 2/13',
  '2026-02-12',
  '2026-02-13',
  'Cannes, France',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Speakers are responsible for travel and accommodation. 
WAICF doesn''t cover speaker expense/fees',
  NULL,
  'Online Form',
  NULL,
  NULL,
  'Expenses not covered',
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('World AI Cannes Festival (WAICF)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'GWU Student Session (and contest sponsorship)',
  '2026-02-13 00:00:00',
  '2026-02-13',
  '2026-02-13',
  'Zoom',
  'Global',
  'Speaking',
  'High',
  'Booked',
  'Personal Contact/Inquiry',
  'Thor',
  NULL,
  'Jessica Vodilka',
  'jvodilka@email.gwu.edu',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('GWU Student Session (and contest sponsorship)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'PULSE (EMC3)',
  '2026-02-27 00:00:00',
  '2026-02-27',
  '2026-02-27',
  'NYC',
  'Global',
  'Speaking',
  'High',
  'Booked',
  'Personal Contact/Inquiry',
  'Thor',
  'Thor booked via emc3 contacts',
  'Ewan Jamieson- Exec Producer  and Daniel Curtis (emc3 CSO/Partner)',
  'ewan.jamieson@emc3.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('PULSE (EMC3)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Mobile World Congress',
  '3/2-3/5',
  '2026-03-02',
  '2026-03-05',
  'Barcelona, Spain',
  'Europe',
  'Speaking',
  'Low',
  'No Openings',
  'No Openings',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Mobile World Congress')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Big Data and AI World London (Tech Show London)',
  '3/4 - 3/5',
  '2026-03-04',
  '2026-03-05',
  'London',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Registered for speaker updates   Under the umbrella of Tech Show London: (Cloud & AI Infrastructure, Cloud & Cyber Security Expo, Big Data & AI World, Data Centre World, and DevOps Live.); He had mtg with them for sponsorship-- but it''s too expensive. (Aleyna Bozan, London show only); Event Details Page',
  'CloserStill Media',
  NULL,
  NULL,
  'Submit: speaker/ run a session',
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Big Data and AI World London (Tech Show London)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'AIBC Africa 2026',
  '3/9 - 3/11',
  '2026-03-09',
  '2026-03-11',
  'Cape Town, Africa',
  'Global',
  'Speaking',
  'Low',
  'We''ll Pass',
  NULL,
  NULL,
  'Submit online -- Already in contact with Olga',
  'Emily Demajo',
  'emily.d@sigma.world',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('AIBC Africa 2026')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Nvidia Conference',
  '3/15-3/19',
  '2026-03-15',
  '2026-03-19',
  'San Jose, CA',
  'Global',
  'Speaking',
  'Medium',
  'Attending (Not Speaking)',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Nvidia Conference')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'InnovEYtion Summit 2026',
  '2026-03-23 00:00:00',
  '2026-03-23',
  '2026-03-23',
  'Venezuela',
  'Global',
  'Speaking',
  'Medium',
  'Personal Contact/Inquiry',
  'Personal Contact/Inquiry',
  'Thor',
  'Juan reached out to Thor via email',
  'Juan Fernandez (Partner: EY Venezuela)',
  'juan.fernandez@ve.ey.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('InnovEYtion Summit 2026')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Economist Business Innovation Summit: AI and Business Innovation Summit',
  '3/24 - 3/25',
  '2026-03-24',
  '2026-03-25',
  'London',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry',
  'Thor',
  'Skipped online form and contacted their speaking mgr directly.',
  'For speaking enquiries email Caitlin Mehta: caitlinmehta@economist.com',
  'caitlinmehta@economist.com',
  'Submit Online',
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Economist Business Innovation Summit: AI and Business Innovation Summit')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Fii - Miami',
  '3/25 - 3/27',
  '2026-03-25',
  '2026-03-27',
  'Miami, FL',
  'Americas',
  'Speaking',
  'Medium',
  'Attending (Not Speaking)',
  'Personal Contact/Inquiry',
  'Thor',
  'Thor will email his personal contacts',
  NULL,
  'communications@fii-institute.org',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Fii - Miami')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Chief Product Officer Summit NYC',
  '2026-03-26 00:00:00',
  '2026-03-26',
  '2026-03-26',
  'NYC',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Submitted online request form to speak. Then they reached out.; March is fully booked with travel/speaking/events/retreats --Do not submit further--',
  'Rose Johnstone - Head of Community & Events
Producer, Product-Led Alliance',
  'rose@productledalliance.com',
  'Submit Online',
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Chief Product Officer Summit NYC')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'HumanX',
  '4/6-4/9',
  '2026-04-06',
  '2026-04-09',
  'San Francisco',
  'Americas',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Be aware: Apparently had bad experience with them in Vegas/not well run.',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('HumanX')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Dubai AI Festival (Postponed to Oct 26)',
  '4/7-4/8',
  '2026-04-07',
  '2026-04-08',
  'Dubai',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  NULL,
  'Submitted via online speaker form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Dubai AI Festival (Postponed to Oct 26)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Enterprise AI Maturity Assembly via The Millennium Alliance- ongoing events',
  '4/8-4/9',
  '2026-04-08',
  '2026-04-09',
  'The Biltmore, Miami',
  'Americas',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  NULL,
  'Submitted via online speaker form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Enterprise AI Maturity Assembly via The Millennium Alliance- ongoing events')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'GITEX AI ASIA',
  '4/9-4/10',
  '2026-04-09',
  '2026-04-10',
  'Singapore',
  'Asia-Pacific',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Topic C: Turning Chaos Into Learning: Handling AI Workslop with AI Literacy',
  'Submitted via online form',
  'For any urgent enquiries, please contact us directly at conference@gitexasia.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('GITEX AI ASIA')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Leap 2026 (was postponed to Aug 31st)',
  '4/13-4/16',
  '2026-04-13',
  '2026-04-16',
  'Riyadh, Saudi',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry',
  'Thor',
  NULL,
  'Fares Sahnoune',
  'leapspeakers@tahaluf.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Leap 2026 (was postponed to Aug 31st)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'BAHRAIN WORKSHOPS (Postponed to MAY)',
  '4/19-4/23',
  '2026-04-19',
  '2026-04-23',
  NULL,
  NULL,
  'Speaking',
  'Medium',
  'Date Conflict',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('BAHRAIN WORKSHOPS (Postponed to MAY)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Skoll World Forum',
  '4/21-4/24',
  '2026-04-21',
  '2026-04-24',
  'Oxford, UK',
  'Europe',
  'Speaking',
  'Medium',
  'Personal Contact/Inquiry',
  'Personal Contact/Inquiry',
  'Thor',
  NULL,
  '"We know the organizers"',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Skoll World Forum')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'YPO: Global Entrepreneurship Summit Dubai (Postponed?)',
  '4/22 - 4/24',
  '2026-04-22',
  '2026-04-24',
  'Dubai',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry',
  'Thor',
  'Submitted speaker package and followed up. Thor''s contact- via a personal email chain. We then sent a 60 Min executive workshop description to Aman.; Maria Domingo followed up for our rates and for interest on future ypo events as well.',
  'Ajit Shah (+ Partner Aman Merchant)',
  'ajit@lotusholdings.com',
  NULL,
  'Maria Luz Domingo, Regional Forum & Learning Manager, MENA YPO: followed up via email for all MENA events: <mdomingo@ypo.org>',
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('YPO: Global Entrepreneurship Summit Dubai (Postponed?)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Joe Speaking at Business School Engagement Collective',
  '2026-04-24 00:00:00',
  '2026-04-24',
  '2026-04-24',
  'California',
  'Global',
  'Speaking',
  'High',
  'Booked',
  'Self Submitted',
  'Joe',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Joe Speaking at Business School Engagement Collective')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Possible 2026',
  '4/27-4/29',
  '2026-04-27',
  '2026-04-29',
  'Miami',
  'Americas',
  'Speaking',
  'Low',
  'No Openings',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Possible 2026')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Reuters Momentum AI New York 2026',
  '4/27-4/28',
  '2026-04-27',
  '2026-04-28',
  'NYC',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Registered for Speaker Updates',
  'Thor',
  'Thanks for your interest in a speaking role at Reuters Momentum AI New York (April 27–28).
For organizations like ArcticBlue.AI who provide solutions and services relating to enterprise AI, speaking engagements are available as part of our sponsorship program. The alternative option would be to look at an AI Lab Demo, which is a great way to showcase your product and generate engaged leads directly with our audience of senior stakeholders.',
  'Registered for speaker interest via form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Reuters Momentum AI New York 2026')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'ODSC East 2026',
  '4/28-4/30',
  '2026-04-28',
  '2026-04-30',
  'Boston',
  'Americas',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Topic A: Fail or Scale: What’s the difference between Experiments and Pilots?',
  'Submitted via link',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('ODSC East 2026')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Digital Transformation Summit UAE (Postponed to Nov 4)',
  '2026-04-29 00:00:00',
  '2026-04-29',
  '2026-04-29',
  'Abu Dhabi',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Registered for Speaker Updates',
  'Thor',
  NULL,
  'Sumbitted interest via form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Digital Transformation Summit UAE (Postponed to Nov 4)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Middle East Enterprise AI Summit (Postponed to Aug 30)',
  '2026-04-30 00:00:00',
  '2026-04-30',
  '2026-04-30',
  'Riyadh, Saudi Arabia',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Registered for Speaker Updates',
  'Thor',
  'April is fully booked with travel/speaking/events                            --Do not submit further--',
  'Registered for speaking and future events via form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Middle East Enterprise AI Summit (Postponed to Aug 30)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'AI Agent Conference',
  '5/4–5/5',
  '2026-05-04',
  '2026-05-05',
  'New York City',
  'Americas',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  NULL,
  'Simon Chan, conf organizer',
  NULL,
  'Linkedin',
  'Julie Sylvester - Head of Events <julie@firsthand.vc> [LI: 917-868-7160]',
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('AI Agent Conference')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Rise of AI Conference Berlin (+online)',
  '5/5-5/6',
  '2026-05-05',
  '2026-05-06',
  'Berlin',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  '"We will come back to you once we have made up our mind. In the meanwhile feel free to send us an email to push for your submission. We like persistent people."',
  NULL,
  'Submission Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Rise of AI Conference Berlin (+online)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'DIS2026 X1 (Data Innovation Summit)',
  '5/6- 5/8',
  '2026-05-06',
  '2026-05-08',
  'Stockholm',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Topic A: Fail or Scale: What’s the difference between Experiments and Pilots?',
  NULL,
  'Nomination Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('DIS2026 X1 (Data Innovation Summit)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Web Summit Vancouver',
  '5/11-5/13',
  '2026-05-11',
  '2026-05-13',
  'Vancouver, Canada',
  'Americas',
  'Speaking',
  'Low',
  'No Openings',
  'No Openings',
  'Thor',
  NULL,
  'Speaker Submit',
  'pickaspeaker@websummit.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Web Summit Vancouver')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'SaaStr Annual X AI Summit',
  '5/12-5/14',
  '2026-05-12',
  '2026-05-14',
  'San Francisco',
  'Americas',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('SaaStr Annual X AI Summit')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'YPO Geopolitical Summit: London',
  '5/13-5/14',
  '2026-05-13',
  '2026-05-14',
  'London',
  'Europe',
  'Speaking',
  'High',
  'Attending',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('YPO Geopolitical Summit: London')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Chief AI Officer Summit Dubai',
  '2026-05-14 00:00:00',
  '2026-05-14',
  '2026-05-14',
  'Dubai',
  'MENA',
  'Speaking',
  'Medium',
  'Not yet',
  'Not yet',
  'Thor',
  NULL,
  'Did not submit yet due to ongoing war conflict - will most likely be postponed to a new date',
  'Submission form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Chief AI Officer Summit Dubai')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'AI & Big Data Expo North America',
  '5/18-5/19',
  '2026-05-18',
  '2026-05-19',
  'San Jose',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  NULL,
  'Applied via speaker form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('AI & Big Data Expo North America')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'ATxSG - Asia Tech x Singapore',
  '5/20-5/22',
  '2026-05-20',
  '2026-05-22',
  'Singapore',
  'Asia-Pacific',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry, Application Process Inquiry',
  'Thor',
  NULL,
  'Reached out personally as the call for speakers page had no process attached',
  'info@asiatechxsg.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('ATxSG - Asia Tech x Singapore')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'The AI Summit - Singapore (at ATxSG)',
  '5/20-5/22',
  '2026-05-20',
  '2026-05-22',
  'Singapore',
  'Asia-Pacific',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Speakers are responsible for their own travel and accommodation.',
  NULL,
  'Online Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('The AI Summit - Singapore (at ATxSG)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Travels (SF, Munich, Bareclona)',
  '5/20-5/29',
  '2026-05-20',
  '2026-05-29',
  NULL,
  NULL,
  'Speaking',
  'Medium',
  'Date Conflict',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Travels (SF, Munich, Bareclona)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'BAHRAIN WORKSHOPS (Postponed to JUNE)',
  '5/24-5/28',
  '2026-05-24',
  '2026-05-28',
  NULL,
  NULL,
  'Speaking',
  'Medium',
  'Date Conflict',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('BAHRAIN WORKSHOPS (Postponed to JUNE)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Will be in Oslo - do not submit for the events in this travel time frame',
  '5/31-6/5-ish',
  '2026-05-31',
  '2026-06-05',
  NULL,
  NULL,
  'Speaking',
  'Medium',
  'Date Conflict',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Will be in Oslo - do not submit for the events in this travel time frame')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Oslo Freedom Forum',
  '6/1-6/3',
  '2026-06-01',
  '2026-06-03',
  'Oslo, Norway',
  'Europe',
  'Speaking',
  'Medium',
  'Attending (Not Speaking)',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Oslo Freedom Forum')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Snowflake Summit 26',
  '6/1-6/4',
  '2026-06-01',
  '2026-06-04',
  'San Francisco',
  'Americas',
  'Speaking',
  'Low',
  'No Openings',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Snowflake Summit 26')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Bahrain NEW Dates',
  '6/7-6/11',
  '2026-06-07',
  '2026-06-11',
  NULL,
  NULL,
  'Speaking',
  'Medium',
  'Date Conflict',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Bahrain NEW Dates')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'London Tech Week',
  '6/8-6/12',
  '2026-06-08',
  '2026-06-12',
  'London',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  NULL,
  'Applied via speaker form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('London Tech Week')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'AI Summit London',
  '6/10-6/11',
  '2026-06-10',
  '2026-06-11',
  'Tobacco Dock, London',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Speakers are responsible for their own travel and accommodation.',
  NULL,
  'Online Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('AI Summit London')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'FII PRIORITY Europe 2026',
  '6/17-6/19',
  '2026-06-17',
  '2026-06-19',
  'Rome, Italy',
  'Europe',
  'Speaking',
  'High',
  'Attending',
  NULL,
  NULL,
  'Speaking is Sponsorship only/FII institute must invite you',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('FII PRIORITY Europe 2026')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Joe Speaking at UXPA International 2026 Conference',
  '2026-06-23 00:00:00',
  '2026-06-23',
  '2026-06-23',
  'Las Vegas',
  'Americas',
  'Speaking',
  'High',
  'Booked',
  'Self Submitted',
  'Joe',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Joe Speaking at UXPA International 2026 Conference')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'GWU TBD (7th or 9th)',
  '2026-07-07 00:00:00',
  '2026-07-07',
  '2026-07-07',
  'DC',
  'Global',
  'Speaking',
  'Medium',
  'In contact with',
  'In contact with',
  'Thor',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('GWU TBD (7th or 9th)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Raise Summit',
  '7/8-7/9',
  '2026-07-08',
  '2026-07-09',
  'Carrousel du Louvre, Paris',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Joined Waitlist',
  'Thor',
  'Joined Speaker Waitlist to be contacted',
  NULL,
  'contact@send.raisesummitai.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Raise Summit')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Ai4: Las Vegas ("Should attend")',
  '8/4-8/6',
  '2026-08-04',
  '2026-08-06',
  'Vegas',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Our “earned” speaking spots are available to end-user type companies only (ex. hospitals, banks, retailers, etc). Anyone with an AI or tech-related product/service must apply to speak via our sponsor form.',
  NULL,
  'Online Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Ai4: Las Vegas ("Should attend")')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Middle East Enterprise AI Summit (Postponed from April 30)',
  '2026-08-30 00:00:00',
  '2026-08-30',
  '2026-08-30',
  'Riyadh, Saudi Arabia',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Registered for Speaker Updates',
  'Thor',
  NULL,
  'Registered for speaking and future events via form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Middle East Enterprise AI Summit (Postponed from April 30)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Leap 2026 (was postponed from April)',
  '8/31-9/3',
  '2026-08-31',
  '2026-09-03',
  'Riyadh, Saudi',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry',
  'Thor',
  NULL,
  'Fares Sahnoune',
  'leapspeakers@tahaluf.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Leap 2026 (was postponed from April)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'HumanX: Amsterdam',
  '9/22-9/24',
  '2026-09-22',
  '2026-09-24',
  'Amsterdam',
  'Europe',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('HumanX: Amsterdam')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Digital Transformation Summit -Doha',
  '2026-09-29 00:00:00',
  '2026-09-29',
  '2026-09-29',
  'Doha, Qatar',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Registered for Speaker Updates',
  'Thor',
  NULL,
  'Registered for speaker interest via form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Digital Transformation Summit -Doha')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'ITC Vegas: Verma attending?',
  '9/29-10/1',
  '2026-09-29',
  '2026-10-01',
  'Vegas',
  'Global',
  'Speaking',
  'High',
  'Attending',
  NULL,
  NULL,
  NULL,
  'Sent Verma speaking info/ would need his proposal to submit',
  'Submission Info',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('ITC Vegas: Verma attending?')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Thor conflicts. Do not book anything during these dates',
  '10/14-10/21',
  '2026-10-14',
  '2026-10-21',
  NULL,
  NULL,
  'Speaking',
  'Medium',
  'Date Conflict',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Thor conflicts. Do not book anything during these dates')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Money 20/20 Las Vegas: (should attend)',
  '10/18-10/21',
  '2026-10-18',
  '2026-10-21',
  'Vegas',
  'Global',
  'Speaking',
  'High',
  'Attending',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Money 20/20 Las Vegas: (should attend)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Dubai AI Festival (Postponed from April)',
  '10/26-10/27',
  '2026-10-26',
  '2026-10-27',
  'Dubai',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  NULL,
  'Submitted via online speaker form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Dubai AI Festival (Postponed from April)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'AIBC Rome',
  '11/2-11/5',
  '2026-11-02',
  '2026-11-05',
  'Rome, Italy',
  'Europe',
  'Speaking',
  'Medium',
  'In contact with',
  'Personal Contact/Inquiry, In contact with',
  'Thor',
  NULL,
  'Thor had mtg with Olga regarding other AIBC events, passed on those, interested in Italy',
  'olga.y@SiGMA.World',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('AIBC Rome')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Digital Transformation Summit UAE (Postponed from April 29)',
  '2026-11-04 00:00:00',
  '2026-11-04',
  '2026-11-04',
  'Abu Dhabi',
  'MENA',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Registered for Speaker Updates',
  'Thor',
  NULL,
  'Sumbitted interest via form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Digital Transformation Summit UAE (Postponed from April 29)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Protectors (Ins / Thor''s Contact)',
  '11/9-11/11',
  '2026-11-09',
  '2026-11-11',
  'Vegas',
  'Global',
  'Speaking',
  'Medium',
  'In contact with',
  'In contact with, Personal Contact/Inquiry',
  'Verma',
  'Saw your post on launching Protectors. Not sure if you remember, but we''ve done a ton of work on the intersection of AI and the life and annuity space. For some reason when we suggest giving talks on it, tech and AI event organizers aren''t super interested in having MetLife, Farmers, Zurich, or the reinsurers on stage :) Anyway, figured I''d throw my partner''s name in the hat for a speaker on AI in the insurance space. We can also promote the event to what I assume is your exact target market.',
  'Jay Weintraub - CEO & Founder, Connectiv Holdings. We create, own, and operate industry leading/ industry defining events.',
  'jay@connectiv.com',
  'Jay''s LinkedIn  +  Protectors LinkedIn',
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Protectors (Ins / Thor''s Contact)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Web Summit Lisbon',
  '11/9-11/12',
  '2026-11-09',
  '2026-11-12',
  'Lisbon, Portugal',
  'Europe',
  'Speaking',
  'Medium',
  'Personal Contact/Inquiry',
  'Personal Contact/Inquiry',
  'Thor',
  NULL,
  'Ciara Haley',
  'ciara.haley@websummit.com, darragh.mccauley@websummit.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Web Summit Lisbon')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'HLTH USA in Las Vegas: (should attend)',
  '11/15-11/18',
  '2026-11-15',
  '2026-11-18',
  'Vegas',
  'Global',
  'Speaking',
  'High',
  'Attending',
  NULL,
  NULL,
  'HLTH’s main program is not pay-to-play and does not pay honorariums to speakers or accept sponsorship dollars for a main agenda speaking role. HLTH does not cover travel & accommodations for speakers.
Confirmed main program speakers receive a complimentary pass to attend HLTH, but we are not able to offer complimentary guest passes to speakers’ teams. *Exceptions are made for professional security personnel.',
  '“Speaker applications for HLTH 2026 will open in mid-May” **June 12th deadline',
  'Submission Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('HLTH USA in Las Vegas: (should attend)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Africa Tech Festival',
  '11/17-11/19',
  '2026-11-17',
  '2026-11-19',
  'Cape Town, South Africa',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry',
  'Thor',
  '*AI Literacy Topic',
  'Reached out personally ("apply to be a speaker by sending us an email")',
  'info@africatechfestival.com',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Africa Tech Festival')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'The AI Summit Cape Town (at Africa Tech Fest)',
  '11/17-11/19',
  '2026-11-17',
  '2026-11-19',
  'Cape Town, South Africa',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  'Speakers are responsible for their own travel and accommodation.',
  'Applied via speaker form',
  'Online Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('The AI Summit Cape Town (at Africa Tech Fest)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'AWS re:Invent- Vegas: (should attend)',
  '11/30-12/4',
  '2026-11-30',
  '2026-12-04',
  'Vegas',
  'Global',
  'Speaking',
  'High',
  'Attending',
  NULL,
  NULL,
  'If you want to speak at re:Invent, entry points are: AWS partners co-presenting joint case studies with AWS team',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('AWS re:Invent- Vegas: (should attend)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'The AI Summit New York - Javits Center',
  '12/9-12/10',
  '2026-12-09',
  '2026-12-10',
  'NYC',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted',
  'Thor',
  '(Same event host as AI Summit: London, Singapore, Cape Town)',
  NULL,
  'Online Form',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('The AI Summit New York - Javits Center')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'On_Discourse Summit - TBD (usually March, if they have one this year??)',
  'TBD',
  NULL,
  NULL,
  'NYC',
  'Global',
  'Speaking',
  'Medium',
  'Thor Contacting',
  NULL,
  'Thor',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('On_Discourse Summit - TBD (usually March, if they have one this year??)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'Post-Exit Founders (PEF)',
  'TBD',
  NULL,
  NULL,
  'Podcast',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Personal Contact/Inquiry',
  'Thor',
  'Submitted speaker package. Organizer confirmed they will contact us if chosen to add to the future schedule.',
  'Connor',
  'connor@pef.xyz',
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('Post-Exit Founders (PEF)')
);

INSERT INTO public.manual_events (
  name, date_str, start_date, end_date, location, region, type, priority,
  status, submission_status, speaker, notes,
  poc_name, poc_email, poc_linkedin, additional_contacts,
  speaking_fee, paid, created_by
)
SELECT
  'The Millennium Alliance- ongoing events',
  'TBD',
  NULL,
  NULL,
  'Various (US + Europe)',
  'Global',
  'Speaking',
  'Medium',
  'Submitted',
  'Submitted, Registered for Speaker Updates',
  'Thor',
  NULL,
  'Submitted via online form',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'hurley@arcticblue.ai'
WHERE NOT EXISTS (
  SELECT 1 FROM public.manual_events WHERE lower(name) = lower('The Millennium Alliance- ongoing events')
);

-- 75 INSERTs total.
SELECT count(*) AS manual_events_total FROM public.manual_events;
