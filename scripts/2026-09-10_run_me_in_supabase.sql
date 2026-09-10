-- ====================================================================
-- ArcticBlue Event Tracker — one paste, four pending items
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq.
-- Everything here is additive or a single-row delete. Safe to run twice.
--
-- These cannot be done from the app's public key: RLS silently returns
-- HTTP 200 with zero rows for the delete, and DDL is not possible over
-- PostgREST at all. That silence is why they have sat unapplied.
-- ====================================================================

-- 1. Angela left ArcticBlue (2026-09-10). Remove her approved-editor access
--    so a magic link to her mailbox can no longer manage target accounts,
--    recorded travel or the Action Center's protected data.
delete from public.allowed_editors where email = 'angela@arcticblue.ai';

-- 2. Organiser grouping ("add an event we already track" / sibling events).
--    20 references in build.py and nowhere to store the value, so the whole
--    feature has been silently inert.
alter table public.event_state   add column if not exists org_group text;
alter table public.manual_events add column if not exists org_group text;

-- 3. Edit trail for manually-added events. The write path sets these on every
--    save and sbWriteRetry strips them silently (SILENT_STRIP_COLS), so manual
--    events have no record of ever changing and never appear in "In the last week".
alter table public.manual_events add column if not exists updated_at timestamptz;
alter table public.manual_events add column if not exists updated_by text;

-- 4. Event-type override for catalog events (the edit form writes it).
alter table public.event_state add column if not exists type text;

-- ── Verify: expect 2 editors, and 5 rows below ──────────────────────
select email from public.allowed_editors order by email;

select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and (   (table_name = 'event_state'   and column_name in ('org_group','type'))
       or (table_name = 'manual_events' and column_name in ('org_group','updated_at','updated_by')))
order by table_name, column_name;
