-- ====================================================================
-- ArcticBlue Event Tracker — dedicated "Apply to speak" link per event
--
-- WHY: the card's "Apply to speak ↗" button used to only appear when a URL
-- happened to be buried inside the free-text "Speaking route" field (the app
-- parsed the first http(s) URL out of it). The Details editor now has a
-- proper "Apply to speak link" field so you can set that URL explicitly on
-- ANY event. It needs somewhere to live:
--   * catalog events  -> event_state override column (apply_url)
--   * manual events    -> manual_events column (apply_url)
--
-- When apply_url is set, the Apply button links straight to it. When it's
-- blank, the app still falls back to a URL found in Speaking route, so
-- nothing that works today stops working.
--
-- Until you run this, editing the "Apply to speak link" field will fail with
-- "column apply_url does not exist". Every other field keeps working.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS). Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq.
-- ====================================================================

alter table public.event_state   add column if not exists apply_url text;
alter table public.manual_events add column if not exists apply_url text;

-- Sanity: confirm the new columns exist.
select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'apply_url'
order by table_name;
