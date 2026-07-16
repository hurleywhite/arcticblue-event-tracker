-- ====================================================================
-- Delete 4 security/cyber events from manual_events (Angela's request).
--
-- These live in Supabase (manual_events), not the catalog, so the app can't
-- remove them from a git deploy — run this in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq.
--
--   id 292 = Millennium Alliance Enterprise AI Security Transformation Assembly – August
--   id 306 = IAPP Privacy. Security. Risk. + AI Governance Global   (Seattle, Oct)
--   id 346 = LATAM CISO Summit
--   id 445 = CDM Media CIO/CISO Ireland Summit
--
-- None have Discussion (event_chat) messages, so there are no dependent rows to
-- clear first. (The other IAPP card — "IAPP Global Privacy Summit", Washington
-- DC — is a DIFFERENT, catalog event and is intentionally NOT touched here.)
-- ====================================================================

-- 1) Preview — should return EXACTLY these 4 rows before you delete:
select id, name, date_str, location
from public.manual_events
where id in (292, 306, 346, 445)
order by id;

-- 2) Delete:
delete from public.manual_events
where id in (292, 306, 346, 445);
