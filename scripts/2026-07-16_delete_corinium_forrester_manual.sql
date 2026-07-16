-- ====================================================================
-- Delete the Corinium (CDAO) + Forrester events that live in manual_events.
-- Angela's request. Run in the Supabase SQL editor (project efkvhlmfdwlobvdmvqiq).
--
-- These 10 are the manual-event half; the catalog half was removed via git.
--
--   Corinium:
--     85  CDAO Melbourne
--     89  Enterprise AI Melbourne
--     90  CDAO Government
--     128 CAIO Fall
--     138 CDAO Dallas 2026 (Corinium)
--     147 CDAO Washington D.C. - Enterprise (Corinium)
--     360 CDAO Defense & Security
--     411 Chief AI Officer Fall
--     412 CDAO Benelux
--   Forrester:
--     348 Forrester AI Forum Singapore
--
-- KEPT (different organizers, intentionally not deleted): Evanta's
-- "CDAO Executive Summit" series, and Re-Work events including the co-branded
-- "Chief AI Officer Summit NY (Re-Work / Corinium)".
-- ====================================================================

-- 1) Preview — should return EXACTLY these 10 rows before deleting:
select id, name, date_str, location
from public.manual_events
where id in (85, 89, 90, 128, 138, 147, 348, 360, 411, 412)
order by id;

-- 2) Clear any Discussion (event_chat) rows first, so a foreign key can't
--    block the delete (harmless if there are none):
delete from public.event_chat
where manual_id in (85, 89, 90, 128, 138, 147, 348, 360, 411, 412);

-- 3) Delete the events:
delete from public.manual_events
where id in (85, 89, 90, 128, 138, 147, 348, 360, 411, 412);
